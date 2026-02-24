#!/usr/bin/env python3
# Module: bootstrap_playbook -- Batch-process historic session transcripts
#         to seed/populate the playbook.
#
# Spec: docs/bootstrap/spec.md
import json
import os
import sys
import time
import asyncio
from pathlib import Path
from datetime import datetime

from common import (
    load_playbook,
    save_playbook,
    load_transcript,
    extract_cited_ids,
    run_reflector,
    apply_bullet_tags,
    run_curator,
    apply_structured_operations,
    run_deduplication,
    prune_harmful,
)


# --- Helper: keypoint counter ---
# @implements REQ-BOOT-011
def count_keypoints(playbook: dict) -> int:
    """Count total key points across all sections."""
    return sum(len(entries) for entries in playbook.get("sections", {}).values())


# --- Helper: project dir encoding ---
# @implements REQ-BOOT-002
def encode_project_dir(project_dir: str) -> str:
    """Encode CLAUDE_PROJECT_DIR to ~/.claude/projects/ subdirectory name.

    Algorithm: replace '/' -> '-', '.' -> '-', '_' -> '-'
    """
    return project_dir.replace("/", "-").replace(".", "-").replace("_", "-")


# --- Helper: state file I/O ---
# @implements REQ-BOOT-012, REQ-BOOT-013
def load_state(state_path: Path) -> dict:
    """Load bootstrap state file. Returns default if missing or corrupted."""
    if not state_path.exists():
        return {"version": "1.0", "processed_sessions": {}}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "processed_sessions" not in data:
            print("BOOTSTRAP: warning: state file corrupted, treating all sessions as unprocessed",
                  file=sys.stderr)
            return {"version": "1.0", "processed_sessions": {}}
        return data
    except (json.JSONDecodeError, OSError):
        print("BOOTSTRAP: warning: state file corrupted, treating all sessions as unprocessed",
              file=sys.stderr)
        return {"version": "1.0", "processed_sessions": {}}


def save_state(state_path: Path, state: dict):
    """Atomically save bootstrap state file via temp + os.replace().

    @implements REQ-BOOT-013
    @invariant INV-BOOT-008 (atomic write via temp file + os.replace)
    """
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(".json.tmp")  # produces bootstrap_state.json.tmp
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(str(tmp_path), str(state_path))


async def main():
    """Bootstrap playbook from historic session transcripts.

    @implements REQ-BOOT-001, REQ-BOOT-003, REQ-BOOT-004, REQ-BOOT-005,
                REQ-BOOT-006, REQ-BOOT-007, REQ-BOOT-008, REQ-BOOT-010,
                REQ-BOOT-011, REQ-BOOT-012, REQ-BOOT-014, REQ-BOOT-015,
                REQ-BOOT-016, REQ-BOOT-017, REQ-BOOT-018, REQ-BOOT-019
    @invariant INV-BOOT-001 (pipeline step order)
    @invariant INV-BOOT-002 (single asyncio event loop)
    @invariant INV-BOOT-003 (monotonic processing order)
    @invariant INV-BOOT-004 (cumulative playbook identity)
    @invariant INV-BOOT-005 (no direct playbook construction)
    @invariant INV-BOOT-006 (sequential processing)
    @invariant INV-BOOT-007 (progress event format compliance)
    @invariant INV-BOOT-009 (playbook never reset)
    @invariant INV-BOOT-010 (counter identity)
    """
    # ============================================================
    # PHASE 0: Prerequisite checks (REQ-BOOT-016, REQ-BOOT-017, REQ-BOOT-018)
    # ============================================================

    # REQ-BOOT-017: CLAUDE_PROJECT_DIR must be set
    project_dir = os.getenv("CLAUDE_PROJECT_DIR")
    if not project_dir:
        print("BOOTSTRAP: error: CLAUDE_PROJECT_DIR is not set. Run this command from within a Claude Code session.",
              file=sys.stderr)
        sys.exit(1)

    # REQ-BOOT-016: API key must be available
    api_key = (
        os.getenv("AGENTIC_CONTEXT_API_KEY")
        or os.getenv("ANTHROPIC_AUTH_TOKEN")
        or os.getenv("ANTHROPIC_API_KEY")
    )
    if not api_key:
        print("BOOTSTRAP: error: no API key found. Set AGENTIC_CONTEXT_API_KEY, ANTHROPIC_AUTH_TOKEN, or ANTHROPIC_API_KEY.",
              file=sys.stderr)
        sys.exit(1)

    # REQ-BOOT-018: Template files must exist
    user_claude_dir = Path.home() / ".claude"
    required_templates = ["reflector.txt", "curator.txt", "playbook.txt"]
    for template_name in required_templates:
        template_path = user_claude_dir / "prompts" / template_name
        if not template_path.exists():
            print(f"BOOTSTRAP: error: required template not found: {template_path}",
                  file=sys.stderr)
            sys.exit(1)

    # ============================================================
    # PHASE 1: Configuration (env vars with defaults)
    # ============================================================

    skip_subagents = os.getenv("AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS") == "true"

    try:
        inter_session_delay = float(os.getenv("AGENTIC_CONTEXT_BOOTSTRAP_DELAY", "2.0"))
    except ValueError:
        inter_session_delay = 2.0

    try:
        max_transcript_mb = float(os.getenv("AGENTIC_CONTEXT_MAX_TRANSCRIPT_MB", "5.0"))
    except ValueError:
        max_transcript_mb = 5.0

    max_transcript_bytes = max_transcript_mb * 1024 * 1024

    # ============================================================
    # PHASE 2: Session discovery (REQ-BOOT-001, REQ-BOOT-002)
    # ============================================================

    transcript_dir_override = os.getenv("AGENTIC_CONTEXT_TRANSCRIPT_DIR")
    if transcript_dir_override:
        transcript_dir = Path(transcript_dir_override)
    else:
        encoded = encode_project_dir(project_dir)
        transcript_dir = Path.home() / ".claude" / "projects" / encoded

    project_dir_name = transcript_dir.name

    # Discover files
    session_files = sorted(transcript_dir.glob("*.jsonl")) if transcript_dir.exists() else []
    if not skip_subagents and transcript_dir.exists():
        subagent_files = sorted(transcript_dir.glob("*/subagents/agent-*.jsonl"))
    else:
        subagent_files = []

    session_count = len(session_files)
    subagent_count = len(subagent_files)

    # REQ-BOOT-006: Combine and sort by mtime ascending
    all_files = session_files + subagent_files
    all_files.sort(key=lambda f: f.stat().st_mtime)

    total = len(all_files)

    # ============================================================
    # PHASE 3: State file loading (REQ-BOOT-012)
    # ============================================================

    state_path = Path(project_dir) / ".claude" / "bootstrap_state.json"
    state = load_state(state_path)

    # Filter out already-processed
    already_processed_count = 0
    to_process_files = []
    for f in all_files:
        if str(f) in state["processed_sessions"]:
            already_processed_count += 1
        else:
            to_process_files.append(f)

    to_process = len(to_process_files)

    # REQ-BOOT-011(a): Discovery summary
    print(f"BOOTSTRAP: discovered {total} transcript(s) in {project_dir_name} "
          f"({session_count} sessions, {subagent_count} subagents), "
          f"{already_processed_count} already processed, {to_process} to process",
          file=sys.stderr)

    # ============================================================
    # PHASE 4: Main processing loop
    # ============================================================

    # REQ-BOOT-014: Load existing playbook once (INV-BOOT-004, INV-BOOT-009)
    playbook = load_playbook()

    processed = 0
    skipped = 0     # includes empty transcripts, too-large, already-processed
    failed = 0
    skipped += already_processed_count  # already-processed counted as skipped

    overall_start = time.time()

    for idx, file_path in enumerate(to_process_files, start=1):
        filename = file_path.name
        file_size_bytes = file_path.stat().st_size
        file_size_kb = file_size_bytes / 1024

        # REQ-BOOT-019: Large transcript guard
        if file_size_bytes > max_transcript_bytes:
            size_mb = file_size_bytes / (1024 * 1024)
            print(f"BOOTSTRAP: [{idx}/{to_process}] skipped {filename}: "
                  f"transcript too large ({size_mb:.1f} MB, max {max_transcript_mb:.1f} MB)",
                  file=sys.stderr)
            skipped += 1
            if inter_session_delay > 0 and idx < to_process:
                await asyncio.sleep(inter_session_delay)
            continue

        # REQ-BOOT-011(b): Session start event
        print(f"BOOTSTRAP: [{idx}/{to_process}] processing {filename} ({file_size_kb:.1f} KB)",
              file=sys.stderr)

        session_start = time.time()

        try:
            # REQ-BOOT-003: Load transcript
            messages = load_transcript(str(file_path))

            if not messages:
                print(f"BOOTSTRAP: [{idx}/{to_process}] skipped {filename}: empty transcript",
                      file=sys.stderr)
                skipped += 1
                # Do NOT record in state file -- retry on next run
                if inter_session_delay > 0 and idx < to_process:
                    await asyncio.sleep(inter_session_delay)
                continue

            count_before = count_keypoints(playbook)

            # REQ-BOOT-004: Per-session pipeline (INV-BOOT-001)
            # Step 1
            cited_ids = extract_cited_ids(messages)

            # Step 2 (await -- async)
            reflector_output = await run_reflector(messages, playbook, cited_ids)

            # Check for reflector failure
            if not reflector_output.get("analysis") and not reflector_output.get("bullet_tags"):
                print(f"BOOTSTRAP: [{idx}/{to_process}] skipped {filename}: "
                      f"pipeline failed (reflector returned empty)",
                      file=sys.stderr)
                failed += 1
                if inter_session_delay > 0 and idx < to_process:
                    await asyncio.sleep(inter_session_delay)
                continue

            # Step 3
            apply_bullet_tags(playbook, reflector_output.get("bullet_tags", []))

            # Step 4 (await -- async)
            curator_output = await run_curator(reflector_output, playbook)

            # Check for curator failure
            if not curator_output.get("reasoning") and not curator_output.get("operations"):
                print(f"BOOTSTRAP: [{idx}/{to_process}] skipped {filename}: "
                      f"pipeline failed (curator returned empty)",
                      file=sys.stderr)
                failed += 1
                if inter_session_delay > 0 and idx < to_process:
                    await asyncio.sleep(inter_session_delay)
                continue

            # Step 5
            playbook = apply_structured_operations(playbook, curator_output.get("operations", []))

            # Step 6
            playbook = run_deduplication(playbook)

            # Step 7
            playbook = prune_harmful(playbook)

            # REQ-BOOT-005: Save playbook after each successful session
            save_playbook(playbook)

            count_after = count_keypoints(playbook)

            # Simplified delta computation (REQ-BOOT-011)
            delta = count_after - count_before
            if delta >= 0:
                added = delta
                removed = 0
            else:
                added = 0
                removed = abs(delta)

            duration = time.time() - session_start

            # REQ-BOOT-011(d): Session complete event
            print(f"BOOTSTRAP: [{idx}/{to_process}] completed {filename} in {duration:.1f}s "
                  f"(playbook: {count_after} key points, delta: +{added} -{removed})",
                  file=sys.stderr)

            # REQ-BOOT-012: Update state file
            state["processed_sessions"][str(file_path)] = {
                "processed_at": datetime.now().isoformat(),
                "key_points_after": count_after,
            }
            save_state(state_path, state)

            processed += 1

        except Exception:
            # Catch-all for unexpected errors in a single session
            print(f"BOOTSTRAP: [{idx}/{to_process}] skipped {filename}: "
                  f"pipeline failed (unexpected error)",
                  file=sys.stderr)
            failed += 1

        # REQ-BOOT-010: Inter-session delay
        if inter_session_delay > 0 and idx < to_process:
            await asyncio.sleep(inter_session_delay)

    # ============================================================
    # PHASE 5: Final summary (REQ-BOOT-011(e))
    # ============================================================

    total_elapsed = time.time() - overall_start
    total_keypoints = count_keypoints(playbook)

    print(f"BOOTSTRAP: complete. {processed} processed, {skipped} skipped, {failed} failed. "
          f"Playbook: {total_keypoints} key points. Elapsed: {total_elapsed:.0f}s",
          file=sys.stderr)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBOOTSTRAP: interrupted by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"BOOTSTRAP: fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
