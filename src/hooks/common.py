#!/usr/bin/env python3
# Module: common -- shared utilities for playbook lifecycle hooks.
#
# Spec: docs/sections/spec.md, docs/curator/spec.md, docs/retry/spec.md,
#       docs/reflector/spec.md, docs/dedup/spec.md
# Contract: docs/sections/contract.md, docs/curator/contract.md, docs/retry/contract.md
# Observability: docs/curator/observability.md, docs/retry/observability.md
import copy
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from datetime import datetime

try:
    import anthropic

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


# @implements REQ-SECT-010
# Single source of truth for canonical section names, slugs, and ordering.
# Iteration order = canonical section order (Python 3.7+ dict insertion order).
SECTION_SLUGS = {
    "PATTERNS & APPROACHES": "pat",
    "MISTAKES TO AVOID": "mis",
    "USER PREFERENCES": "pref",
    "PROJECT CONTEXT": "ctx",
    "OTHERS": "oth",
}

# Retry configuration for extract_keypoints() API calls.
# @implements REQ-RETRY-008
MAX_RETRIES = 3    # Total attempts (0-indexed: attempt 0, 1, 2)
BASE_DELAY = 2.0   # Base delay in seconds for exponential backoff


def get_project_dir() -> Path:
    project_dir = os.getenv("CLAUDE_PROJECT_DIR")
    if project_dir:
        return Path(project_dir)
    return Path.home()


def get_user_claude_dir() -> Path:
    home = Path.home()
    return home / ".claude"


def is_diagnostic_mode() -> bool:
    flag_file = get_project_dir() / ".claude" / "diagnostic_mode"
    return flag_file.exists()


def save_diagnostic(content: str, name: str):
    diagnostic_dir = get_project_dir() / ".claude" / "diagnostic"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = diagnostic_dir / f"{timestamp}_{name}.txt"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def is_first_message(session_id: str) -> bool:
    session_file = get_project_dir() / ".claude" / "last_session.txt"

    if session_file.exists():
        last_session_id = session_file.read_text().strip()
        return session_id != last_session_id

    return True


def mark_session(session_id: str):
    session_file = get_project_dir() / ".claude" / "last_session.txt"
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(session_id)


def clear_session():
    session_file = get_project_dir() / ".claude" / "last_session.txt"
    if session_file.exists():
        session_file.unlink()


def extract_cited_ids(messages: list[dict]) -> list[str]:
    """Extract deduplicated cited key point IDs from assistant messages.

    Scans only assistant messages for bracket-cited IDs matching section slug
    prefixes (pat, mis, pref, ctx, oth) or legacy kpt_ prefix.

    @implements REQ-REFL-001
    @invariant INV-REFL-001 (cited IDs are deduplicated)
    """
    pattern = re.compile(r"\[((?:pat|mis|pref|ctx|oth)-\d+|kpt_\d+)\]")
    found = set()
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            found.update(pattern.findall(content))
    return list(found)


def generate_keypoint_name(section_entries: list[dict], slug: str) -> str:
    """Generate the next key point name for a section.

    Scans section_entries for names matching {slug}-NNN pattern,
    finds the highest NNN, returns {slug}-{max+1:03d}.

    Legacy kpt_NNN names in section_entries are ignored.

    @implements REQ-SECT-002
    @invariant INV-SECT-005 (slug prefix consistency)
    """
    pattern = re.compile(rf"^{re.escape(slug)}-(\d+)$")
    max_num = 0
    for entry in section_entries:
        match = pattern.match(entry.get("name", ""))
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"{slug}-{max_num + 1:03d}"


def _generate_legacy_keypoint_name(existing_names: set) -> str:
    """Generate a legacy kpt_NNN name for migration of bare strings.

    Used only during flat-to-sections migration in load_playbook().
    Preserves the legacy naming pattern for migrated entries (contract.md).
    """
    max_num = 0
    for name in existing_names:
        if name.startswith("kpt_"):
            try:
                num = int(name.split("_")[1])
                max_num = max(max_num, num)
            except (IndexError, ValueError):
                continue
    return f"kpt_{max_num + 1:03d}"


def _default_playbook() -> dict:
    """Return a default empty sections-based playbook.

    @implements REQ-SECT-001
    """
    return {
        "version": "1.0",
        "last_updated": None,
        "sections": {name: [] for name in SECTION_SLUGS},
    }


def _resolve_section(section_name: str) -> str:
    """Resolve a section name via case-insensitive exact match.

    Strips leading/trailing whitespace before matching.
    Returns the canonical section name if matched, or "OTHERS" as fallback.

    @implements REQ-SECT-005
    @invariant INV-SECT-002 (section names from canonical set)
    """
    if not section_name or not section_name.strip():
        return "OTHERS"
    stripped = section_name.strip()
    for canonical in SECTION_SLUGS:
        if canonical.upper() == stripped.upper():
            return canonical
    return "OTHERS"


def load_settings() -> dict:
    settings_path = get_user_claude_dir() / "settings.json"

    if not settings_path.exists():
        return {"playbook_update_on_exit": False, "playbook_update_on_clear": False}

    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return {"playbook_update_on_exit": False, "playbook_update_on_clear": False}


def load_playbook() -> dict:
    """Load playbook from disk, migrating flat format to sections if needed.

    @implements REQ-SECT-006, REQ-SECT-007, REQ-SCORE-004, REQ-SCORE-005, REQ-SCORE-006
    @invariant INV-SECT-001 (sections key always present)
    @invariant INV-SECT-004 (legacy IDs preserved during migration)
    @invariant INV-SECT-006 (migration round-trip stability)
    @invariant INV-SECT-007 (no key_points key in output)
    """
    playbook_path = get_project_dir() / ".claude" / "playbook.json"

    if not playbook_path.exists():
        return _default_playbook()

    try:
        with open(playbook_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # REQ-SECT-007: Dual-key handling -- sections takes precedence
        if "sections" in data and "key_points" in data:
            data.pop("key_points")
            # LOG-SECT-003: Dual-key warning diagnostic
            if is_diagnostic_mode():
                save_diagnostic(
                    "Dual-key playbook.json detected: both 'sections' and 'key_points' present. "
                    "Using 'sections', ignoring 'key_points'.",
                    "sections_dual_key_warning"
                )

        if "sections" in data:
            # Already migrated: ensure all 5 canonical sections exist
            for section_name in SECTION_SLUGS:
                if section_name not in data["sections"]:
                    data["sections"][section_name] = []
            # @invariant INV-SECT-007: no key_points key in output
            data.pop("key_points", None)
            return data

        if "key_points" not in data:
            return _default_playbook()

        # REQ-SECT-006: Flat format migration to sections
        # Apply scoring migration to each entry (same branches as scoring module)
        keypoints = []
        existing_names = set()
        migrated_entries = []

        for item in data["key_points"]:
            if isinstance(item, str):
                # Branch 1: Bare string (REQ-SCORE-004, SCN-SCORE-004-01)
                # Uses legacy kpt_NNN naming during migration (contract.md)
                name = _generate_legacy_keypoint_name(existing_names)
                keypoints.append({"name": name, "text": item, "helpful": 0, "harmful": 0})
                existing_names.add(name)
                migrated_entries.append({"name": name, "from": "bare_string", "original_score": None})
            elif isinstance(item, dict):
                if "helpful" in item and "harmful" in item:
                    # Branch 0: Already migrated (no-op, keep as-is)
                    if "name" not in item:
                        item["name"] = _generate_legacy_keypoint_name(existing_names)
                    # Drop "score" if it somehow co-exists (defensive, SCN-SCORE-006-02)
                    item.pop("score", None)
                    existing_names.add(item["name"])
                    keypoints.append(item)
                elif "score" in item:
                    # Branch 3: Dict with score (REQ-SCORE-006, SCN-SCORE-006-01)
                    if "name" not in item:
                        item["name"] = _generate_legacy_keypoint_name(existing_names)
                    original_score = item.pop("score")
                    item["helpful"] = max(original_score, 0)
                    item["harmful"] = max(-original_score, 0)
                    existing_names.add(item["name"])
                    keypoints.append(item)
                    migrated_entries.append({"name": item["name"], "from": "dict_with_score", "original_score": original_score})
                else:
                    # Branch 2: Dict without score or counters (REQ-SCORE-005, SCN-SCORE-005-01)
                    if "name" not in item:
                        item["name"] = _generate_legacy_keypoint_name(existing_names)
                    item["helpful"] = 0
                    item["harmful"] = 0
                    existing_names.add(item["name"])
                    keypoints.append(item)
                    migrated_entries.append({"name": item["name"], "from": "dict_no_score", "original_score": None})

        # @invariant INV-SCORE-001, INV-SCORE-002 (counters >= 0)
        # @invariant INV-SCORE-004 (no score field)
        # @invariant INV-SCORE-005 (round-trip stability: migrated entries re-load as Branch 0 no-op)

        # LOG-SCORE-001: Diagnostic logging for scoring migration
        if migrated_entries and is_diagnostic_mode():
            migration_summary = json.dumps(migrated_entries, indent=2)
            save_diagnostic(
                f"Migrated {len(migrated_entries)} playbook entries:\n{migration_summary}",
                "playbook_migration"
            )

        # Place ALL migrated entries into OTHERS section
        # @invariant INV-SECT-004: Legacy IDs preserved (no renaming)
        sections = {name: [] for name in SECTION_SLUGS}
        sections["OTHERS"] = keypoints

        # LOG-SECT-001: Sections migration diagnostic
        if keypoints and is_diagnostic_mode():
            save_diagnostic(
                f"Migrated {len(keypoints)} entries from flat key_points to OTHERS section",
                "sections_migration"
            )

        data["sections"] = sections
        data.pop("key_points", None)
        # @invariant INV-SECT-007: no key_points key in output
        return data

    except Exception:
        return _default_playbook()


def save_playbook(playbook: dict):
    """Save playbook to disk.

    @implements INV-SECT-001 (assertion that sections key is present)
    @invariant INV-SECT-001 (sections key always present after write)
    @invariant INV-SECT-007 (no key_points key in output)
    """
    assert "sections" in playbook, (
        "Playbook must have 'sections' key. "
        "Got keys: " + str(list(playbook.keys()))
    )
    playbook.pop("key_points", None)  # INV-SECT-007: strip legacy key if present
    playbook["last_updated"] = datetime.now().isoformat()
    playbook_path = get_project_dir() / ".claude" / "playbook.json"

    playbook_path.parent.mkdir(parents=True, exist_ok=True)
    with open(playbook_path, "w", encoding="utf-8") as f:
        json.dump(playbook, f, indent=2, ensure_ascii=False)


def format_playbook(playbook: dict) -> str:
    """Format playbook with section headers for prompt injection.

    @implements REQ-SECT-003
    """
    sections = playbook.get("sections", {})

    section_blocks = []
    for section_name in SECTION_SLUGS:  # Canonical order
        entries = sections.get(section_name, [])
        if not entries:
            continue  # Omit empty sections (SCN-SECT-003-02)

        lines = [f"## {section_name}"]
        for kp in entries:
            lines.append(
                f"[{kp['name']}] helpful={kp['helpful']} harmful={kp['harmful']} :: {kp['text']}"
            )
        section_blocks.append("\n".join(lines))

    if not section_blocks:
        return ""

    key_points_text = "\n\n".join(section_blocks)

    template = load_template("playbook.txt")
    return template.format(key_points=key_points_text)


def apply_bullet_tags(playbook: dict, bullet_tags: list[dict]) -> dict:
    """Apply reflector bullet tags to playbook key point counters.

    Builds a name-to-keypoint lookup across ALL sections, then increments
    helpful/harmful counters based on each tag. Neutral tags cause no change.
    Unrecognized tag values and unmatched names are logged to stderr and skipped.

    @implements REQ-REFL-007
    @invariant INV-REFL-003 (counter non-negativity preserved -- only += 1)
    @invariant INV-REFL-004 (each tag applied exactly once per call)
    """
    # Build name-to-keypoint lookup across ALL sections
    name_to_kp = {}
    for entries in playbook.get("sections", {}).values():
        for kp in entries:
            name_to_kp[kp["name"]] = kp

    for tag in bullet_tags:
        name = tag.get("name", "")
        tag_value = tag.get("tag", "")

        if name not in name_to_kp:
            print(f"apply_bullet_tags: name {name!r} not found in playbook, skipping", file=sys.stderr)
            continue

        if tag_value == "helpful":
            name_to_kp[name]["helpful"] += 1
        elif tag_value == "harmful":
            name_to_kp[name]["harmful"] += 1
        elif tag_value == "neutral":
            pass  # No change for neutral
        else:
            print(f"apply_bullet_tags: unrecognized tag value {tag_value!r} for {name!r}, skipping", file=sys.stderr)

    return playbook


def _apply_curator_operations(playbook: dict, operations: list) -> dict:
    """Apply curator operations (ADD, UPDATE, MERGE, DELETE) to the playbook.

    The playbook passed in is a deep copy -- mutations are safe.
    Operations are applied sequentially in list order.
    Invalid operations are skipped (no-op with diagnostic log).

    @implements REQ-CUR-002, REQ-CUR-003, REQ-CUR-004, REQ-CUR-005, REQ-CUR-009, REQ-CUR-013
    @invariant INV-CUR-002 (no crash on invalid operations)
    @invariant INV-CUR-004 (section names remain canonical)
    @invariant INV-CUR-005 (operations bounded to 10)
    @invariant INV-CUR-007 (UPDATE preserves entry identity)
    @invariant INV-CUR-009 (UPDATE validates both fields)
    """
    # @invariant INV-CUR-005: Truncate to CON-CUR-004 max
    MAX_OPS = 10
    truncated_from = None
    if len(operations) > MAX_OPS:
        truncated_from = len(operations)
        if is_diagnostic_mode():
            save_diagnostic(
                f"Operations list truncated from {truncated_from} to {MAX_OPS}",
                "curator_ops_truncated"
            )
        operations = operations[:MAX_OPS]

    # Counters for OBS-CUR-001 summary
    counts = {"ADD": 0, "UPDATE": 0, "MERGE": 0, "DELETE": 0}
    skipped = {"ADD": 0, "UPDATE": 0, "MERGE": 0, "DELETE": 0, "unknown": 0}
    skip_reasons = []

    for op in operations:
        op_type = op.get("type", "")

        if op_type == "ADD":
            # REQ-CUR-002: ADD operation
            # @invariant INV-CUR-002: validate before applying
            text = op.get("text", "")
            if not text or not isinstance(text, str) or not text.strip():
                skipped["ADD"] += 1
                skip_reasons.append("ADD: empty or missing text")
                continue

            raw_section = op.get("section", "") or ""
            # @invariant INV-CUR-004: section names remain canonical
            section_name = _resolve_section(raw_section)

            # Dedup against all existing texts across all sections
            existing_texts = set()
            for entries in playbook["sections"].values():
                for kp in entries:
                    existing_texts.add(kp["text"])

            if text in existing_texts:
                skipped["ADD"] += 1
                skip_reasons.append(f"ADD: duplicate text \"{text[:40]}...\"")
                continue

            slug = SECTION_SLUGS[section_name]
            target_entries = playbook["sections"][section_name]
            name = generate_keypoint_name(target_entries, slug)
            target_entries.append({"name": name, "text": text, "helpful": 0, "harmful": 0})
            counts["ADD"] += 1

        elif op_type == "MERGE":
            # REQ-CUR-003: MERGE operation
            source_ids = op.get("source_ids", [])
            merged_text = op.get("merged_text", "")

            # Validation (QG-CUR-001)
            if not isinstance(source_ids, list) or len(source_ids) < 2:
                skipped["MERGE"] += 1
                skip_reasons.append("MERGE: source_ids has fewer than 2 entries")
                continue
            if not merged_text or not isinstance(merged_text, str) or not merged_text.strip():
                skipped["MERGE"] += 1
                skip_reasons.append("MERGE: empty or missing merged_text")
                continue

            # Build ID-to-entry and ID-to-section lookup from current state
            id_to_entry = {}
            id_to_section = {}
            for sec_name, entries in playbook["sections"].items():
                for kp in entries:
                    id_to_entry[kp["name"]] = kp
                    id_to_section[kp["name"]] = sec_name

            # Filter valid source_ids
            valid_ids = []
            for sid in source_ids:
                if sid in id_to_entry:
                    valid_ids.append(sid)
                else:
                    # OBS-CUR-002 (LOG-CUR-002): non-existent ID
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"MERGE references non-existent ID: {sid!r}",
                            "curator_nonexistent_id"
                        )
                    skip_reasons.append(f"MERGE: source_id {sid!r} not found")

            if len(valid_ids) < 2:
                skipped["MERGE"] += 1
                skip_reasons.append("MERGE: fewer than 2 valid source_ids remain after filtering")
                continue

            # Resolve target section
            raw_section = op.get("section", "") or ""
            if raw_section and raw_section.strip():
                # @invariant INV-CUR-004: section names remain canonical
                target_section = _resolve_section(raw_section)
            else:
                target_section = id_to_section[valid_ids[0]]  # section of first valid source

            # @invariant INV-CUR-003: Sum counters from valid sources (non-negative preserved)
            total_helpful = sum(id_to_entry[sid]["helpful"] for sid in valid_ids)
            total_harmful = sum(id_to_entry[sid]["harmful"] for sid in valid_ids)

            # Create new entry in target section
            slug = SECTION_SLUGS[target_section]
            target_entries = playbook["sections"][target_section]
            name = generate_keypoint_name(target_entries, slug)
            target_entries.append({
                "name": name,
                "text": merged_text,
                "helpful": total_helpful,
                "harmful": total_harmful,
            })

            # Remove all valid source entries from their sections
            for sid in valid_ids:
                sec = id_to_section[sid]
                playbook["sections"][sec] = [
                    kp for kp in playbook["sections"][sec] if kp["name"] != sid
                ]

            counts["MERGE"] += 1

        elif op_type == "UPDATE":
            # REQ-CUR-013: UPDATE operation
            # @invariant INV-CUR-009: validate both target_id and text
            target_id = op.get("target_id", "")
            text = op.get("text", "")

            if not target_id or not isinstance(target_id, str) or not target_id.strip():
                skipped["UPDATE"] += 1
                skip_reasons.append("UPDATE: empty or missing target_id")
                continue

            if not text or not isinstance(text, str) or not text.strip():
                skipped["UPDATE"] += 1
                skip_reasons.append("UPDATE: empty or missing text")
                continue

            # Find the entry across all sections
            found_entry = None
            for sec_name, entries in playbook["sections"].items():
                for kp in entries:
                    if kp["name"] == target_id:
                        found_entry = kp
                        break
                if found_entry:
                    break

            if not found_entry:
                skipped["UPDATE"] += 1
                print(f"UPDATE: target_id {target_id!r} not found in playbook, skipping", file=sys.stderr)
                # OBS-CUR-002: non-existent ID
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"UPDATE references non-existent ID: {target_id!r}",
                        "curator_nonexistent_id"
                    )
                skip_reasons.append(f"UPDATE: target_id {target_id!r} not found")
                continue

            # @invariant INV-CUR-007: only text field is updated; name/helpful/harmful unchanged
            old_text = found_entry["text"]
            found_entry["text"] = text

            # OBS-CUR-004: UPDATE audit diagnostic
            if is_diagnostic_mode():
                save_diagnostic(
                    f"UPDATE applied: target_id={target_id!r}, "
                    f"old_text=\"{old_text[:80]}\", new_text=\"{text[:80]}\"",
                    "curator_update_audit"
                )

            counts["UPDATE"] += 1

        elif op_type == "DELETE":
            # REQ-CUR-004: DELETE operation
            target_id = op.get("target_id", "")
            reason = op.get("reason", "")

            if not target_id or not isinstance(target_id, str) or not target_id.strip():
                skipped["DELETE"] += 1
                skip_reasons.append("DELETE: empty or missing target_id")
                continue

            # Find the entry
            found_section = None
            found_entry = None
            for sec_name, entries in playbook["sections"].items():
                for kp in entries:
                    if kp["name"] == target_id:
                        found_section = sec_name
                        found_entry = kp
                        break
                if found_section:
                    break

            if not found_section:
                skipped["DELETE"] += 1
                # OBS-CUR-002 (LOG-CUR-002): non-existent ID
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"DELETE references non-existent ID: {target_id!r}",
                        "curator_nonexistent_id"
                    )
                skip_reasons.append(f"DELETE: target_id {target_id!r} not found")
                continue

            # OBS-CUR-003 (LOG-CUR-003): DELETE reason audit
            if is_diagnostic_mode():
                save_diagnostic(
                    f"DELETE applied: target_id={target_id!r}, "
                    f"text=\"{found_entry['text'][:80]}\", "
                    f"reason={reason!r}",
                    "curator_delete_audit"
                )

            # Remove entry
            playbook["sections"][found_section] = [
                kp for kp in playbook["sections"][found_section] if kp["name"] != target_id
            ]
            counts["DELETE"] += 1

        else:
            skipped["unknown"] += 1
            skip_reasons.append(f"Unknown operation type: {op_type!r}")

    # OBS-CUR-001 (LOG-CUR-001): Summary diagnostic
    if is_diagnostic_mode():
        summary_parts = ["Curator operations summary:"]
        if truncated_from is not None:
            summary_parts.append(f"  Operations list truncated from {truncated_from} to {MAX_OPS}")
        summary_parts.append(f"  ADD: {counts['ADD']} applied, {skipped['ADD']} skipped")
        summary_parts.append(f"  UPDATE: {counts['UPDATE']} applied, {skipped['UPDATE']} skipped")
        summary_parts.append(f"  MERGE: {counts['MERGE']} applied, {skipped['MERGE']} skipped")
        summary_parts.append(f"  DELETE: {counts['DELETE']} applied, {skipped['DELETE']} skipped")
        summary_parts.append(f"  Unknown type: {skipped['unknown']} skipped")
        if skip_reasons:
            summary_parts.append("  Skip reasons:")
            for r in skip_reasons:
                summary_parts.append(f"    - {r}")
        save_diagnostic("\n".join(summary_parts), "curator_ops_summary")

    return playbook


def apply_structured_operations(playbook: dict, operations: list[dict]) -> dict:
    """Apply structured curator operations to the playbook with deep copy isolation.

    If operations is empty, returns the original playbook unmodified (no deepcopy).
    Otherwise, creates a deep copy, applies operations via _apply_curator_operations(),
    and returns the modified copy. On exception, returns the original playbook.

    @implements REQ-CUR-014
    @invariant INV-CUR-010 (deep copy isolation)
    """
    if not operations:
        return playbook

    try:
        playbook_copy = copy.deepcopy(playbook)
        playbook_copy = _apply_curator_operations(playbook_copy, operations)
        return playbook_copy
    except Exception:
        if is_diagnostic_mode():
            import traceback
            save_diagnostic(
                f"apply_structured_operations rollback due to exception:\n{traceback.format_exc()}",
                "curator_ops_rollback"
            )
        return playbook


def prune_harmful(playbook: dict) -> dict:
    """Remove key points where harmful >= 3 AND harmful > helpful.

    Zero-evaluation entries (helpful=0, harmful=0) are NEVER pruned.
    Same thresholds as pruning logic in update_playbook_data().

    @implements REQ-CUR-015
    @invariant INV-CUR-011 (thresholds identical to baseline)
    """
    pruned_entries = []
    for section_name in playbook.get("sections", {}):
        surviving = []
        for kp in playbook["sections"][section_name]:
            harmful = kp.get("harmful", 0)
            helpful = kp.get("helpful", 0)
            if harmful >= 3 and harmful > helpful:
                pruned_entries.append(kp)
            else:
                surviving.append(kp)
        playbook["sections"][section_name] = surviving

    if pruned_entries:
        for kp in pruned_entries:
            print(
                f"prune_harmful: pruned {kp['name']}: \"{kp['text'][:80]}\" "
                f"(helpful={kp['helpful']}, harmful={kp['harmful']})",
                file=sys.stderr,
            )
        if is_diagnostic_mode():
            prune_details = []
            for kp in pruned_entries:
                prune_details.append(
                    f"  - {kp['name']}: \"{kp['text'][:80]}\" "
                    f"(helpful={kp['helpful']}, harmful={kp['harmful']}) "
                    f"reason: harmful >= 3 AND harmful > helpful"
                )
            save_diagnostic(
                f"Pruned {len(pruned_entries)} key points:\n" + "\n".join(prune_details),
                "playbook_pruning"
            )

    return playbook


def update_playbook_data(playbook: dict, extraction_result: dict) -> dict:
    """Apply operations or new_key_points, evaluations, and pruning across all sections.

    Signature is UNCHANGED from the scoring module -- callers must not break.

    @implements REQ-CUR-006, REQ-CUR-008, REQ-SECT-005, REQ-SECT-008
    @invariant INV-CUR-001 (deep copy isolation)
    @invariant INV-CUR-006 (precedence prevents double-processing)
    @invariant INV-SECT-002 (section names from canonical set)
    @invariant INV-SECT-003 (counter non-negativity)
    @invariant INV-SECT-005 (section-slug ID prefix consistency)
    """
    # @invariant INV-CUR-006: REQ-CUR-008 Precedence rule
    if "operations" in extraction_result:
        # Operations path: deep copy + apply operations
        operations = extraction_result.get("operations", [])
        if isinstance(operations, list) and operations:
            try:
                # @invariant INV-CUR-001: deep copy isolation
                playbook_copy = copy.deepcopy(playbook)
                playbook = _apply_curator_operations(playbook_copy, operations)
            except Exception:
                # INV-CUR-001: rollback to original on uncaught exception
                if is_diagnostic_mode():
                    import traceback
                    save_diagnostic(
                        f"Operations rollback due to exception:\n{traceback.format_exc()}",
                        "curator_ops_rollback"
                    )
                # playbook remains the original (unmodified)
        # Skip new_key_points entirely (even if present) -- INV-CUR-006
    else:
        # Backward compat: use new_key_points as before (CON-CUR-001)
        new_key_points = extraction_result.get("new_key_points", [])

        # Collect all existing texts across all sections for dedup
        existing_texts = set()
        for entries in playbook["sections"].values():
            for kp in entries:
                existing_texts.add(kp["text"])

        # REQ-SECT-005: New key point insertion with section resolution
        for item in new_key_points:
            # Backward compat: plain string -> {"text": str, "section": "OTHERS"}
            # (SCN-SECT-004-03)
            if isinstance(item, str):
                text = item
                section_name = "OTHERS"
            elif isinstance(item, dict):
                text = item.get("text", "")
                raw_section = item.get("section", "") or ""
                section_name = _resolve_section(raw_section)
                # LOG-SECT-002: Unknown section fallback diagnostic
                # Only emitted for non-empty strings that don't match canonical names
                # (SCN-SECT-004-05: missing/None/empty do NOT trigger this)
                if section_name == "OTHERS" and raw_section and raw_section.strip():
                    # Check if the resolved "OTHERS" was due to unknown name vs. explicit "OTHERS"
                    stripped_upper = raw_section.strip().upper()
                    if stripped_upper != "OTHERS":
                        if is_diagnostic_mode():
                            save_diagnostic(
                                f"Unknown section '{raw_section}' for key point: \"{text[:80]}\". "
                                f"Assigned to OTHERS.",
                                "sections_unknown_section"
                            )
            else:
                continue  # Skip invalid entry types

            if not text or text in existing_texts:
                continue

            slug = SECTION_SLUGS[section_name]
            target_entries = playbook["sections"][section_name]
            name = generate_keypoint_name(target_entries, slug)
            target_entries.append({"name": name, "text": text, "helpful": 0, "harmful": 0})
            existing_texts.add(text)

    evaluations = extraction_result.get("evaluations", [])

    # REQ-SECT-008: Evaluations across ALL sections
    # Build name-to-keypoint lookup across ALL sections
    name_to_kp = {}
    for entries in playbook["sections"].values():
        for kp in entries:
            name_to_kp[kp["name"]] = kp

    for eval_item in evaluations:
        name = eval_item.get("name", "")
        rating = eval_item.get("rating", "")

        if name in name_to_kp:
            if rating == "helpful":
                name_to_kp[name]["helpful"] += 1
            elif rating == "harmful":
                name_to_kp[name]["harmful"] += 1
            # "neutral" and unrecognized ratings: no change (SCN-SCORE-002-03, SCN-SCORE-002-04)

    # REQ-SECT-008: Pruning across ALL sections
    # @invariant INV-SCORE-003: Zero-evaluation entries (helpful=0, harmful=0) are never pruned
    pruned_entries = []
    for section_name in playbook["sections"]:
        surviving = []
        for kp in playbook["sections"][section_name]:
            harmful = kp.get("harmful", 0)
            helpful = kp.get("helpful", 0)
            if harmful >= 3 and harmful > helpful:
                pruned_entries.append(kp)
            else:
                surviving.append(kp)
        playbook["sections"][section_name] = surviving

    # LOG-SCORE-002: Diagnostic logging for pruning
    if pruned_entries and is_diagnostic_mode():
        prune_details = []
        for kp in pruned_entries:
            prune_details.append(
                f"  - {kp['name']}: \"{kp['text'][:80]}\" "
                f"(helpful={kp['helpful']}, harmful={kp['harmful']}) "
                f"reason: harmful >= 3 AND harmful > helpful"
            )
        save_diagnostic(
            f"Pruned {len(pruned_entries)} key points:\n" + "\n".join(prune_details),
            "playbook_pruning"
        )

    return playbook


def load_transcript(transcript_path: str) -> list[dict]:
    if not transcript_path or not Path(transcript_path).exists():
        return []

    conversations = []

    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") not in ["user", "assistant"]:
                continue
            if entry.get("isMeta") or entry.get("isVisibleInTranscriptOnly"):
                continue

            message = entry.get("message", {})
            role = message.get("role")
            content = message.get("content", "")

            if not role or not content:
                continue

            if isinstance(content, str) and (
                "<command-name>" in content or "<local-command-stdout>" in content
            ):
                continue

            if isinstance(content, list):
                text_parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                if text_parts:
                    conversations.append(
                        {"role": role, "content": "\n".join(text_parts)}
                    )
            else:
                conversations.append({"role": role, "content": content})

    return conversations


def load_template(template_name: str) -> str:
    template_path = get_user_claude_dir() / "prompts" / template_name
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


def _extract_json_robust(response_text: str) -> dict | None:
    """Attempt to extract JSON from LLM response using 4 strategies.

    Strategy order:
    1. ```json...``` code fence extraction
    2. ```...``` code fence extraction (no language tag)
    3. Balanced-brace counting (outermost { to matching })
    4. Raw json.loads() on full response

    Returns parsed dict on success, None if all strategies fail.

    @implements REQ-REFL-008, REQ-CUR-016
    """
    # Strategy 1: ```json...``` fence
    if "```json" in response_text:
        start = response_text.find("```json") + 7
        end = response_text.find("```", start)
        if end != -1:
            candidate = response_text[start:end].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    # Strategy 2: ```...``` fence (no language tag)
    if "```" in response_text:
        start = response_text.find("```") + 3
        end = response_text.find("```", start)
        if end != -1:
            candidate = response_text[start:end].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    # Strategy 3: Balanced-brace counting
    brace_start = response_text.find("{")
    if brace_start != -1:
        depth = 0
        in_string = False
        escape_next = False
        for i in range(brace_start, len(response_text)):
            ch = response_text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                if in_string:
                    escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = response_text[brace_start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    # Strategy 4: Raw json.loads()
    try:
        return json.loads(response_text.strip())
    except json.JSONDecodeError:
        pass

    return None


def run_deduplication(playbook: dict, threshold: float = None) -> dict:
    """Deduplicate semantically similar key points across all sections.

    Uses SentenceTransformers for embedding and cosine similarity.
    Dependencies (sentence_transformers, numpy) are optional -- if unavailable,
    returns playbook unmodified with a warning to stderr.

    @implements REQ-DEDUP-001, REQ-DEDUP-002, REQ-DEDUP-003, REQ-DEDUP-004, REQ-DEDUP-005, REQ-DEDUP-006
    @invariant INV-DEDUP-001 (no crash on missing dependencies)
    @invariant INV-DEDUP-002 (counter non-negativity preserved through sum)
    @invariant INV-DEDUP-003 (section names remain canonical)
    @invariant INV-DEDUP-004 (post-dedup no pair exceeds threshold)
    @invariant INV-DEDUP-005 (playbook structure preserved)
    """
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
        DEDUP_AVAILABLE = True
    except ImportError:
        DEDUP_AVAILABLE = False

    if not DEDUP_AVAILABLE:
        print("run_deduplication: sentence-transformers not available, skipping deduplication", file=sys.stderr)
        return playbook

    # REQ-DEDUP-004: Threshold resolution (explicit > env var > default)
    if threshold is None:
        env_val = os.getenv("AGENTIC_CONTEXT_DEDUP_THRESHOLD")
        if env_val is not None:
            try:
                threshold = float(env_val)
            except ValueError:
                threshold = 0.85
        else:
            threshold = 0.85
    # Clamp to [0.0, 1.0]
    threshold = max(0.0, min(1.0, threshold))

    # Collect flat list of (section_name, entry) in canonical order
    flat_entries = []
    for section_name in SECTION_SLUGS:
        for entry in playbook.get("sections", {}).get(section_name, []):
            flat_entries.append((section_name, entry))

    # REQ-DEDUP-006: < 2 total entries -> return unmodified
    if len(flat_entries) < 2:
        return playbook

    # @invariant INV-DEDUP-001: top-level try/except wrapping all computation
    try:
        # Embed all entry texts
        texts = [entry["text"] for _, entry in flat_entries]
        model = SentenceTransformer("all-MiniLM-L6-v2")
        embeddings = model.encode(texts, normalize_embeddings=True)
        embeddings = np.array(embeddings)

        # Compute pairwise cosine similarities and build connected components
        # (Union-Find for transitive grouping)
        n = len(flat_entries)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Compute cosine similarity matrix via dot product (embeddings are normalized)
        sim_matrix = embeddings @ embeddings.T

        for i in range(n):
            for j in range(i + 1, n):
                if sim_matrix[i][j] >= threshold:
                    union(i, j)

        # Group by connected component
        components = {}
        for i in range(n):
            root = find(i)
            if root not in components:
                components[root] = []
            components[root].append(i)

        # For each component with > 1 member: first entry is survivor
        to_remove = set()
        for root, members in components.items():
            if len(members) <= 1:
                continue
            # Sort members by original iteration order (they are already in order since
            # we iterate range(n) and append in order)
            members.sort()
            survivor_idx = members[0]
            survivor_entry = flat_entries[survivor_idx][1]

            # Sum counters from all members
            total_helpful = sum(flat_entries[m][1]["helpful"] for m in members)
            total_harmful = sum(flat_entries[m][1]["harmful"] for m in members)
            survivor_entry["helpful"] = total_helpful
            survivor_entry["harmful"] = total_harmful

            # Mark non-survivors for removal
            for m in members[1:]:
                to_remove.add(m)

        # Remove non-survivors from their sections
        # Build set of entry references to remove
        entries_to_remove = set()
        for idx in to_remove:
            entries_to_remove.add(id(flat_entries[idx][1]))

        for section_name in SECTION_SLUGS:
            playbook["sections"][section_name] = [
                kp for kp in playbook["sections"].get(section_name, [])
                if id(kp) not in entries_to_remove
            ]

        return playbook

    except Exception as exc:
        print(f"run_deduplication: unexpected error ({type(exc).__name__}: {exc}), returning playbook unmodified", file=sys.stderr)
        if is_diagnostic_mode():
            import traceback
            save_diagnostic(
                f"run_deduplication exception:\n{traceback.format_exc()}",
                "dedup_unexpected_error"
            )
        return playbook


async def run_reflector(messages: list[dict], playbook: dict, cited_ids: list[str]) -> dict:
    """Run the reflector LLM call to analyze the session and tag key points.

    Makes an async Anthropic API call with same model/api_key/client config
    as extract_keypoints(). Uses robust 4-strategy JSON extraction.

    On ANY failure, returns {"analysis": "", "bullet_tags": []} without raising.

    @implements REQ-REFL-003, REQ-REFL-004, REQ-REFL-005, REQ-REFL-006, REQ-REFL-007, REQ-REFL-008
    @invariant INV-REFL-002 (never raises to caller)
    """
    empty_result = {"analysis": "", "bullet_tags": []}

    try:
        if not ANTHROPIC_AVAILABLE:
            return empty_result

        model = (
            os.getenv("AGENTIC_CONTEXT_MODEL")
            or os.getenv("ANTHROPIC_MODEL")
            or os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL")
            or "claude-sonnet-4-5-20250929"
        )
        if not model:
            return empty_result

        api_key = (
            os.getenv("AGENTIC_CONTEXT_API_KEY")
            or os.getenv("ANTHROPIC_AUTH_TOKEN")
            or os.getenv("ANTHROPIC_API_KEY")
        )
        if not api_key:
            return empty_result

        base_url = os.getenv("AGENTIC_CONTEXT_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL")

        template = load_template("reflector.txt")
        formatted_playbook = format_playbook(playbook)

        prompt = template.format(
            transcript=json.dumps(messages, indent=2, ensure_ascii=False),
            playbook=formatted_playbook,
            cited_ids=json.dumps(cited_ids, ensure_ascii=False),
        )

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**client_kwargs)

        # Same retry logic as extract_keypoints()
        response = None
        for attempt in range(MAX_RETRIES):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=30.0,
                )
                break
            except (
                anthropic.APITimeoutError,
                anthropic.APIConnectionError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
            ) as exc:
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                    time.sleep(delay)
                    continue
                else:
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"All {MAX_RETRIES} attempts failed for run_reflector(): {exc}",
                            "retry_reflector",
                        )
                    return empty_result
            except anthropic.APIStatusError as exc:
                if exc.status_code >= 500 and attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                    time.sleep(delay)
                    continue
                else:
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"Non-retryable or exhausted error in run_reflector(): {exc}",
                            "retry_reflector",
                        )
                    return empty_result
            except Exception as exc:
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Non-retryable error in run_reflector(): {type(exc).__name__}: {exc}",
                        "retry_reflector",
                    )
                return empty_result

        if response is None:
            return empty_result

        # Extract response text
        response_text_parts = []
        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                response_text_parts.append(block.text)
        response_text = "".join(response_text_parts)

        if is_diagnostic_mode():
            save_diagnostic(
                f"# REFLECTOR PROMPT\n{prompt}\n\n{'=' * 80}\n\n# REFLECTOR RESPONSE\n{response_text}\n",
                "reflector",
            )

        if not response_text:
            return empty_result

        # Robust JSON extraction (REQ-REFL-008)
        result = _extract_json_robust(response_text)
        if result is None:
            return empty_result

        return {
            "analysis": result.get("analysis", ""),
            "bullet_tags": result.get("bullet_tags", []),
        }

    except Exception as exc:
        # INV-REFL-002: defensive fallback -- never raise to caller
        if is_diagnostic_mode():
            import traceback
            save_diagnostic(
                f"run_reflector() unexpected error:\n{traceback.format_exc()}",
                "reflector_error",
            )
        return empty_result


async def run_curator(reflector_output: dict, playbook: dict) -> dict:
    """Run the curator LLM call to produce structured playbook operations.

    Receives the reflector's analysis and the current playbook (NOT the raw
    transcript). Makes an async Anthropic API call with same config as
    extract_keypoints(). Uses robust 4-strategy JSON extraction.

    On ANY failure, returns {"reasoning": "", "operations": []} without raising.

    @implements REQ-CUR-010, REQ-CUR-011, REQ-CUR-012, REQ-CUR-016
    @invariant INV-CUR-008 (never raises to caller)
    """
    empty_result = {"reasoning": "", "operations": []}

    try:
        if not ANTHROPIC_AVAILABLE:
            return empty_result

        model = (
            os.getenv("AGENTIC_CONTEXT_MODEL")
            or os.getenv("ANTHROPIC_MODEL")
            or os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL")
            or "claude-sonnet-4-5-20250929"
        )
        if not model:
            return empty_result

        api_key = (
            os.getenv("AGENTIC_CONTEXT_API_KEY")
            or os.getenv("ANTHROPIC_AUTH_TOKEN")
            or os.getenv("ANTHROPIC_API_KEY")
        )
        if not api_key:
            return empty_result

        base_url = os.getenv("AGENTIC_CONTEXT_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL")

        template = load_template("curator.txt")
        formatted_playbook = format_playbook(playbook)

        # Apply .get() defaults per REQ-CUR-010
        normalized_reflector = {
            "analysis": reflector_output.get("analysis", ""),
            "bullet_tags": reflector_output.get("bullet_tags", []),
        }
        prompt = template.format(
            reflector_output=json.dumps(normalized_reflector, indent=2, ensure_ascii=False),
            playbook=formatted_playbook,
        )

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**client_kwargs)

        # Same retry logic as extract_keypoints()
        response = None
        for attempt in range(MAX_RETRIES):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=30.0,
                )
                break
            except (
                anthropic.APITimeoutError,
                anthropic.APIConnectionError,
                anthropic.RateLimitError,
                anthropic.InternalServerError,
            ) as exc:
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                    time.sleep(delay)
                    continue
                else:
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"All {MAX_RETRIES} attempts failed for run_curator(): {exc}",
                            "retry_curator",
                        )
                    return empty_result
            except anthropic.APIStatusError as exc:
                if exc.status_code >= 500 and attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                    time.sleep(delay)
                    continue
                else:
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"Non-retryable or exhausted error in run_curator(): {exc}",
                            "retry_curator",
                        )
                    return empty_result
            except Exception as exc:
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Non-retryable error in run_curator(): {type(exc).__name__}: {exc}",
                        "retry_curator",
                    )
                return empty_result

        if response is None:
            return empty_result

        # Extract response text
        response_text_parts = []
        for block in response.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                response_text_parts.append(block.text)
        response_text = "".join(response_text_parts)

        if is_diagnostic_mode():
            save_diagnostic(
                f"# CURATOR PROMPT\n{prompt}\n\n{'=' * 80}\n\n# CURATOR RESPONSE\n{response_text}\n",
                "curator",
            )

        if not response_text:
            return empty_result

        # Robust JSON extraction (REQ-CUR-016)
        result = _extract_json_robust(response_text)
        if result is None:
            return empty_result

        return {
            "reasoning": result.get("reasoning", ""),
            "operations": result.get("operations", []),
        }

    except Exception as exc:
        # INV-CUR-008: defensive fallback -- never raise to caller
        if is_diagnostic_mode():
            import traceback
            save_diagnostic(
                f"run_curator() unexpected error:\n{traceback.format_exc()}",
                "curator_error",
            )
        return empty_result


async def extract_keypoints(
    messages: list[dict], playbook: dict, diagnostic_name: str = "reflection"
) -> dict:
    """Extract key points from reasoning trajectories via LLM.

    @implements REQ-CUR-001, REQ-SECT-009,
               REQ-RETRY-001, REQ-RETRY-002, REQ-RETRY-003, REQ-RETRY-004,
               REQ-RETRY-005, REQ-RETRY-006, REQ-RETRY-007, REQ-RETRY-008
    @invariant INV-RETRY-001 (function signature unchanged)
    @invariant INV-RETRY-002 (only client.messages.create() is retried)
    @invariant INV-RETRY-003 (total time within hook timeout)
    @invariant INV-RETRY-004 (always returns valid extraction result)
    """
    if not ANTHROPIC_AVAILABLE:
        return {"new_key_points": [], "evaluations": []}

    settings = load_settings()

    model = (
        os.getenv("AGENTIC_CONTEXT_MODEL")
        or os.getenv("ANTHROPIC_MODEL")
        or os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or "claude-sonnet-4-5-20250929"
    )
    if not model:
        return {"new_key_points": [], "evaluations": []}

    api_key = (
        os.getenv("AGENTIC_CONTEXT_API_KEY")
        or os.getenv("ANTHROPIC_AUTH_TOKEN")
        or os.getenv("ANTHROPIC_API_KEY")
    )
    if not api_key:
        return {"new_key_points": [], "evaluations": []}

    base_url = os.getenv("AGENTIC_CONTEXT_BASE_URL") or os.getenv("ANTHROPIC_BASE_URL")

    template = load_template("reflection.txt")

    # @implements REQ-SECT-009: Build flat {name: text} dict from ALL sections
    playbook_dict = {}
    for entries in playbook.get("sections", {}).values():
        for kp in entries:
            playbook_dict[kp["name"]] = kp["text"]

    prompt = template.format(
        trajectories=json.dumps(messages, indent=2, ensure_ascii=False),
        playbook=json.dumps(playbook_dict, indent=2, ensure_ascii=False),
    )

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = anthropic.Anthropic(**client_kwargs)

    # @implements REQ-RETRY-001, REQ-RETRY-002, REQ-RETRY-003, REQ-RETRY-004,
    #             REQ-RETRY-005, REQ-RETRY-006, REQ-RETRY-007
    # @invariant INV-RETRY-002 (only client.messages.create() is inside the retry loop)
    # @invariant INV-RETRY-004 (every error path returns a valid extraction result dict)
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                timeout=30.0,
            )
            # Success: log if this was a retry (attempt > 0)
            if attempt > 0 and is_diagnostic_mode():
                save_diagnostic(
                    f"extract_keypoints() succeeded on attempt {attempt + 1} after {attempt} retries.",
                    "retry_extract_keypoints",
                )
            break

        except anthropic.APITimeoutError as exc:
            # Retryable: transient timeout (must be caught before APIConnectionError)
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                        f"APITimeoutError: {exc}. Next attempt in {delay:.1f}s",
                        "retry_extract_keypoints",
                    )
                time.sleep(delay)
                continue
            else:
                # Final attempt exhausted
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                        f"Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.APIConnectionError as exc:
            # Retryable: transient connection failure
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                        f"APIConnectionError: {exc}. Next attempt in {delay:.1f}s",
                        "retry_extract_keypoints",
                    )
                time.sleep(delay)
                continue
            else:
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                        f"Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.RateLimitError as exc:
            # Retryable: HTTP 429
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                        f"RateLimitError: {exc}. Next attempt in {delay:.1f}s",
                        "retry_extract_keypoints",
                    )
                time.sleep(delay)
                continue
            else:
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                        f"Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.InternalServerError as exc:
            # Retryable: HTTP 500
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                        f"InternalServerError: {exc}. Next attempt in {delay:.1f}s",
                        "retry_extract_keypoints",
                    )
                time.sleep(delay)
                continue
            else:
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                        f"Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.APIStatusError as exc:
            # Catch-all for APIStatusError: check status_code to decide
            if exc.status_code >= 500:
                # Retryable: 5xx not caught by InternalServerError above
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                            f"{type(exc).__name__}: {exc}. Next attempt in {delay:.1f}s",
                            "retry_extract_keypoints",
                        )
                    time.sleep(delay)
                    continue
                else:
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                            f"Returning empty result.",
                            "retry_extract_keypoints",
                        )
                    return {"new_key_points": [], "evaluations": []}
            else:
                # Non-retryable: 4xx (except 429, already caught by RateLimitError)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Non-retryable error in extract_keypoints(): "
                        f"{type(exc).__name__}: {exc}. Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.APIResponseValidationError as exc:
            # Non-retryable: SDK could not parse response (APIError but not APIStatusError)
            if is_diagnostic_mode():
                save_diagnostic(
                    f"Non-retryable error in extract_keypoints(): "
                    f"APIResponseValidationError: {exc}. Returning empty result.",
                    "retry_extract_keypoints",
                )
            return {"new_key_points": [], "evaluations": []}

        except anthropic.APIError as exc:
            # Non-retryable: unknown APIError subclass (defensive fallback)
            if is_diagnostic_mode():
                save_diagnostic(
                    f"Non-retryable error in extract_keypoints(): "
                    f"{type(exc).__name__}: {exc}. Returning empty result.",
                    "retry_extract_keypoints",
                )
            return {"new_key_points": [], "evaluations": []}

        except Exception as exc:
            # Non-retryable: non-API exception (may be a programming bug)
            if is_diagnostic_mode():
                save_diagnostic(
                    f"Non-retryable error in extract_keypoints(): "
                    f"{type(exc).__name__}: {exc}. Returning empty result.",
                    "retry_extract_keypoints",
                )
            return {"new_key_points": [], "evaluations": []}

    response_text_parts = []
    for block in response.content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            response_text_parts.append(block.text)

    response_text = "".join(response_text_parts)

    if is_diagnostic_mode():
        save_diagnostic(
            f"# PROMPT\n{prompt}\n\n{'=' * 80}\n\n# RESPONSE\n{response_text}\n",
            diagnostic_name,
        )

    if not response_text:
        return {"new_key_points": [], "evaluations": []}

    if "```json" in response_text:
        start = response_text.find("```json") + 7
        end = response_text.find("```", start)
        json_text = response_text[start:end].strip()
    elif "```" in response_text:
        start = response_text.find("```") + 3
        end = response_text.find("```", start)
        json_text = response_text[start:end].strip()
    else:
        json_text = response_text.strip()

    try:
        result = json.loads(json_text)
    except json.JSONDecodeError:
        return {"new_key_points": [], "evaluations": []}

    extraction = {
        "new_key_points": result.get("new_key_points", []),
        "evaluations": result.get("evaluations", []),
    }
    # SC-CUR-001: Include operations if present in LLM response AND is a list
    # SCN-CUR-001-04: Non-list values (null, string, int) treated as absent
    if "operations" in result and isinstance(result["operations"], list):
        extraction["operations"] = result["operations"]
    return extraction
