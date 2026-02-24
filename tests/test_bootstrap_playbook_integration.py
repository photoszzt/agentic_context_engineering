# Spec: docs/bootstrap/spec.md
# Testing: docs/bootstrap/testing.md
"""
Behavioral integration tests for the bootstrap_playbook async main() function.

These tests exercise the full async pipeline by mocking all LLM-calling and I/O
functions (run_reflector, run_curator, load_transcript, etc.) while letting
main() orchestrate discovery, state management, and progress reporting against
real filesystem artifacts in tmp_path.

Covers:
- SCN-BOOT-001-04: Empty discovery (no files found)
- SCN-BOOT-004-01: Happy path -- one session processed successfully
- SCN-BOOT-004-02: Reflector returns empty -> pipeline failed
- SCN-BOOT-004-03: Curator returns empty -> pipeline failed
- SCN-BOOT-003-02: Empty transcript skip
- SCN-BOOT-004-04: Unexpected exception -> caught, continues
- SCN-BOOT-006-01: Chronological ordering (mtime-based)
- SCN-BOOT-010-03: Pipeline failure doesn't halt processing
- SCN-BOOT-014-01: Existing playbook preserved (already-processed skip)
- SCN-BOOT-015-01: Subagent transcripts included by default
- SCN-BOOT-015-02: Subagents excluded when SKIP_SUBAGENTS=true
- INV-BOOT-010:    Counter identity: processed + skipped + failed == total

Adversarial categories: Boundary (empty dirs), Invalid Input (empty reflector/curator),
Failure Injection (RuntimeError mid-pipeline).
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock, call

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_src_hooks_dir = str(Path(__file__).resolve().parent.parent / "src" / "hooks")
if _src_hooks_dir not in sys.path:
    sys.path.insert(0, _src_hooks_dir)

import bootstrap_playbook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_playbook():
    """Return the default playbook structure matching common.py format."""
    return {
        "version": "1.0",
        "last_updated": "2026-01-01T00:00:00",
        "sections": {
            "PATTERNS & APPROACHES": [],
            "MISTAKES TO AVOID": [],
            "USER PREFERENCES": [],
            "PROJECT CONTEXT": [],
            "OTHERS": [],
        },
    }


def _reflector_output():
    """Default non-empty reflector output."""
    return {
        "analysis": "test analysis",
        "bullet_tags": [{"tag": "PAT-001", "messages": [0]}],
    }


def _curator_output():
    """Default non-empty curator output."""
    return {
        "reasoning": "test reasoning",
        "operations": [
            {"op": "ADD", "section": "PATTERNS & APPROACHES", "text": "test insight", "score": 5}
        ],
    }


def _one_item_playbook():
    """Playbook after one successful pipeline (1 key point added)."""
    return {
        "version": "1.0",
        "last_updated": "2026-01-01T00:00:00",
        "sections": {
            "PATTERNS & APPROACHES": [
                {"id": "PAT-001", "text": "test insight", "helpful": 1, "harmful": 0}
            ],
            "MISTAKES TO AVOID": [],
            "USER PREFERENCES": [],
            "PROJECT CONTEXT": [],
            "OTHERS": [],
        },
    }


def _create_jsonl(path: Path, content: str = '{"role":"user","content":"hello"}\n'):
    """Create a minimal .jsonl file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _parse_final_summary(stderr_text: str):
    """Extract processed/skipped/failed from the final summary line."""
    m = re.search(
        r"BOOTSTRAP: complete\. (\d+) processed, (\d+) skipped, (\d+) failed\.",
        stderr_text,
    )
    if not m:
        return None
    return {
        "processed": int(m.group(1)),
        "skipped": int(m.group(2)),
        "failed": int(m.group(3)),
    }


def _parse_discovery(stderr_text: str):
    """Extract total/sessions/subagents/already/to_process from discovery line."""
    m = re.search(
        r"BOOTSTRAP: discovered (\d+) transcript\(s\) in .+ "
        r"\((\d+) sessions, (\d+) subagents\), "
        r"(\d+) already processed, (\d+) to process",
        stderr_text,
    )
    if not m:
        return None
    return {
        "total": int(m.group(1)),
        "sessions": int(m.group(2)),
        "subagents": int(m.group(3)),
        "already": int(m.group(4)),
        "to_process": int(m.group(5)),
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def bootstrap_env(tmp_path, monkeypatch):
    """Set up a minimal environment for running bootstrap_playbook.main().

    Returns a dict with:
      - project_dir: Path to the temporary project directory
      - transcript_dir: Path where .jsonl files should be placed
      - state_path: Path to the bootstrap state file
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir()

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-for-integration-tests")
    monkeypatch.setenv("AGENTIC_CONTEXT_TRANSCRIPT_DIR", str(transcript_dir))
    # Zero delay so tests run fast
    monkeypatch.setenv("AGENTIC_CONTEXT_BOOTSTRAP_DELAY", "0")

    state_path = project_dir / ".claude" / "bootstrap_state.json"

    return {
        "project_dir": project_dir,
        "transcript_dir": transcript_dir,
        "state_path": state_path,
    }


def _default_patches(
    load_transcript_rv=None,
    reflector_rv=None,
    curator_rv=None,
    apply_ops_rv=None,
    dedup_side_effect=None,
    prune_side_effect=None,
    load_playbook_rv=None,
    extract_cited_rv=None,
    reflector_side_effect=None,
    curator_side_effect=None,
    apply_bullet_tags_side_effect=None,
    load_transcript_side_effect=None,
):
    """Build a dict of patch context managers for common mocking.

    All patches target the bootstrap_playbook module namespace (where the names
    are imported to), NOT common.py.
    """
    patches = {}

    # load_playbook -- returns empty playbook by default
    patches["load_playbook"] = patch(
        "bootstrap_playbook.load_playbook",
        return_value=load_playbook_rv if load_playbook_rv is not None else _empty_playbook(),
    )
    # save_playbook -- no-op
    patches["save_playbook"] = patch("bootstrap_playbook.save_playbook")

    # load_transcript
    if load_transcript_side_effect is not None:
        patches["load_transcript"] = patch(
            "bootstrap_playbook.load_transcript",
            side_effect=load_transcript_side_effect,
        )
    else:
        patches["load_transcript"] = patch(
            "bootstrap_playbook.load_transcript",
            return_value=load_transcript_rv if load_transcript_rv is not None else [{"role": "user", "content": "test"}],
        )

    # extract_cited_ids
    patches["extract_cited_ids"] = patch(
        "bootstrap_playbook.extract_cited_ids",
        return_value=extract_cited_rv if extract_cited_rv is not None else [],
    )

    # run_reflector (async)
    if reflector_side_effect is not None:
        patches["run_reflector"] = patch(
            "bootstrap_playbook.run_reflector",
            new_callable=AsyncMock,
            side_effect=reflector_side_effect,
        )
    else:
        patches["run_reflector"] = patch(
            "bootstrap_playbook.run_reflector",
            new_callable=AsyncMock,
            return_value=reflector_rv if reflector_rv is not None else _reflector_output(),
        )

    # apply_bullet_tags
    if apply_bullet_tags_side_effect is not None:
        patches["apply_bullet_tags"] = patch(
            "bootstrap_playbook.apply_bullet_tags",
            side_effect=apply_bullet_tags_side_effect,
        )
    else:
        patches["apply_bullet_tags"] = patch("bootstrap_playbook.apply_bullet_tags")

    # run_curator (async)
    if curator_side_effect is not None:
        patches["run_curator"] = patch(
            "bootstrap_playbook.run_curator",
            new_callable=AsyncMock,
            side_effect=curator_side_effect,
        )
    else:
        patches["run_curator"] = patch(
            "bootstrap_playbook.run_curator",
            new_callable=AsyncMock,
            return_value=curator_rv if curator_rv is not None else _curator_output(),
        )

    # apply_structured_operations
    patches["apply_structured_operations"] = patch(
        "bootstrap_playbook.apply_structured_operations",
        return_value=apply_ops_rv if apply_ops_rv is not None else _one_item_playbook(),
    )

    # run_deduplication
    patches["run_deduplication"] = patch(
        "bootstrap_playbook.run_deduplication",
        side_effect=dedup_side_effect if dedup_side_effect is not None else (lambda x: x),
    )

    # prune_harmful
    patches["prune_harmful"] = patch(
        "bootstrap_playbook.prune_harmful",
        side_effect=prune_side_effect if prune_side_effect is not None else (lambda x: x),
    )

    # Path.home -- needed for template file check; use real home so templates are found
    # (they exist on the dev machine at ~/.claude/prompts/)

    return patches


class _PatchContext:
    """Helper to enter/exit a dict of patches and expose mocks."""

    def __init__(self, patches: dict):
        self._patches = patches
        self.mocks = {}

    def __enter__(self):
        for name, p in self._patches.items():
            self.mocks[name] = p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches.values():
            p.stop()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyDiscovery:
    """SCN-BOOT-001-04: Empty discovery (no files found)."""

    # @tests REQ-BOOT-001, SCN-BOOT-001-04
    def test_empty_discovery_produces_zero_counts(self, bootstrap_env, capsys):
        """When transcript directory has no files, discovery reports 0 and exits cleanly."""
        patches = _default_patches()
        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        captured = capsys.readouterr()
        assert "discovered 0 transcript(s)" in captured.err

        summary = _parse_final_summary(captured.err)
        assert summary is not None, f"No final summary found in stderr: {captured.err!r}"
        assert summary["processed"] == 0
        assert summary["skipped"] == 0
        assert summary["failed"] == 0

    # @tests REQ-BOOT-001, SCN-BOOT-001-04, INV-BOOT-010
    def test_empty_discovery_counter_identity(self, bootstrap_env, capsys):
        """Counter identity holds: processed + skipped + failed == total == 0."""
        patches = _default_patches()
        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        captured = capsys.readouterr()
        discovery = _parse_discovery(captured.err)
        summary = _parse_final_summary(captured.err)
        assert discovery is not None
        assert summary is not None
        total = discovery["total"]
        assert total == 0
        assert summary["processed"] + summary["skipped"] + summary["failed"] == total


class TestHappyPathOneSession:
    """SCN-BOOT-004-01: Happy path -- one session processed successfully."""

    # @tests REQ-BOOT-004, SCN-BOOT-004-01, REQ-BOOT-005, REQ-BOOT-012
    def test_one_session_full_pipeline(self, bootstrap_env, capsys):
        """One transcript file is discovered, processed, and recorded in state."""
        transcript_dir = bootstrap_env["transcript_dir"]
        state_path = bootstrap_env["state_path"]

        # Create one .jsonl file
        jsonl_file = transcript_dir / "session-abc.jsonl"
        _create_jsonl(jsonl_file)

        patches = _default_patches()
        with _PatchContext(patches) as ctx:
            asyncio.run(bootstrap_playbook.main())

            # Verify pipeline functions were called
            ctx.mocks["load_transcript"].assert_called_once()
            ctx.mocks["extract_cited_ids"].assert_called_once()
            ctx.mocks["run_reflector"].assert_awaited_once()
            ctx.mocks["apply_bullet_tags"].assert_called_once()
            ctx.mocks["run_curator"].assert_awaited_once()
            ctx.mocks["apply_structured_operations"].assert_called_once()
            ctx.mocks["run_deduplication"].assert_called_once()
            ctx.mocks["prune_harmful"].assert_called_once()
            ctx.mocks["save_playbook"].assert_called_once()

        captured = capsys.readouterr()

        # Discovery
        assert "discovered 1 transcript(s)" in captured.err
        assert "1 sessions" in captured.err

        # Session start
        assert "processing session-abc.jsonl" in captured.err

        # Session complete
        assert "completed session-abc.jsonl" in captured.err

        # Final summary
        summary = _parse_final_summary(captured.err)
        assert summary is not None
        assert summary["processed"] == 1
        assert summary["skipped"] == 0
        assert summary["failed"] == 0

        # State file created with session entry
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert str(jsonl_file) in state["processed_sessions"]


class TestReflectorEmpty:
    """SCN-BOOT-004-02: Reflector returns empty -> pipeline failed."""

    # @tests REQ-BOOT-004, SCN-BOOT-004-02
    def test_reflector_empty_increments_failed(self, bootstrap_env, capsys):
        """When reflector returns empty, session is failed (not skipped)."""
        transcript_dir = bootstrap_env["transcript_dir"]
        state_path = bootstrap_env["state_path"]

        _create_jsonl(transcript_dir / "session-ref-empty.jsonl")

        patches = _default_patches(
            reflector_rv={"analysis": "", "bullet_tags": []},
        )
        with _PatchContext(patches) as ctx:
            asyncio.run(bootstrap_playbook.main())

            # save_playbook should NOT be called (pipeline failed)
            ctx.mocks["save_playbook"].assert_not_called()

        captured = capsys.readouterr()
        assert "pipeline failed (reflector returned empty)" in captured.err

        summary = _parse_final_summary(captured.err)
        assert summary is not None
        assert summary["failed"] == 1
        assert summary["processed"] == 0

        # State file should not record this session
        if state_path.exists():
            state = json.loads(state_path.read_text())
            assert len(state["processed_sessions"]) == 0


class TestCuratorEmpty:
    """SCN-BOOT-004-03: Curator returns empty -> pipeline failed."""

    # @tests REQ-BOOT-004, SCN-BOOT-004-03
    def test_curator_empty_increments_failed(self, bootstrap_env, capsys):
        """When curator returns empty, session is failed (not skipped)."""
        transcript_dir = bootstrap_env["transcript_dir"]
        state_path = bootstrap_env["state_path"]

        _create_jsonl(transcript_dir / "session-cur-empty.jsonl")

        patches = _default_patches(
            curator_rv={"reasoning": "", "operations": []},
        )
        with _PatchContext(patches) as ctx:
            asyncio.run(bootstrap_playbook.main())

            # apply_bullet_tags SHOULD have been called (reflector succeeded)
            ctx.mocks["apply_bullet_tags"].assert_called_once()
            # save_playbook should NOT be called (pipeline failed at curator)
            ctx.mocks["save_playbook"].assert_not_called()

        captured = capsys.readouterr()
        assert "pipeline failed (curator returned empty)" in captured.err

        summary = _parse_final_summary(captured.err)
        assert summary is not None
        assert summary["failed"] == 1
        assert summary["processed"] == 0

        # State file should not record this session
        if state_path.exists():
            state = json.loads(state_path.read_text())
            assert len(state["processed_sessions"]) == 0


class TestEmptyTranscriptSkip:
    """SCN-BOOT-003-02: Empty transcript skip."""

    # @tests REQ-BOOT-003, SCN-BOOT-003-02
    def test_empty_transcript_counted_as_skipped(self, bootstrap_env, capsys):
        """When load_transcript returns [], session is skipped."""
        transcript_dir = bootstrap_env["transcript_dir"]
        state_path = bootstrap_env["state_path"]

        _create_jsonl(transcript_dir / "session-empty.jsonl")

        patches = _default_patches(load_transcript_rv=[])
        with _PatchContext(patches) as ctx:
            asyncio.run(bootstrap_playbook.main())

            # Pipeline should not proceed past load_transcript
            ctx.mocks["run_reflector"].assert_not_awaited()
            ctx.mocks["save_playbook"].assert_not_called()

        captured = capsys.readouterr()
        assert "empty transcript" in captured.err

        summary = _parse_final_summary(captured.err)
        assert summary is not None
        assert summary["skipped"] == 1
        assert summary["processed"] == 0
        assert summary["failed"] == 0

        # State file should NOT record empty transcript (retry on next run)
        if state_path.exists():
            state = json.loads(state_path.read_text())
            assert len(state["processed_sessions"]) == 0


class TestUnexpectedException:
    """SCN-BOOT-004-04: Unexpected exception -> caught, continues."""

    # @tests REQ-BOOT-004, SCN-BOOT-004-04, REQ-BOOT-010
    def test_runtime_error_caught_and_failed(self, bootstrap_env, capsys):
        """RuntimeError during pipeline is caught; session counted as failed."""
        transcript_dir = bootstrap_env["transcript_dir"]

        _create_jsonl(transcript_dir / "session-crash.jsonl")

        patches = _default_patches(
            reflector_side_effect=RuntimeError("simulated API failure"),
        )
        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        captured = capsys.readouterr()
        assert "pipeline failed (unexpected error)" in captured.err

        summary = _parse_final_summary(captured.err)
        assert summary is not None
        assert summary["failed"] == 1
        assert summary["processed"] == 0

    # @tests SCN-BOOT-004-04
    def test_exception_doesnt_crash_final_summary(self, bootstrap_env, capsys):
        """Final summary is always emitted even when exception occurs."""
        transcript_dir = bootstrap_env["transcript_dir"]

        _create_jsonl(transcript_dir / "session-crash2.jsonl")

        patches = _default_patches(
            reflector_side_effect=ValueError("bad data"),
        )
        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        captured = capsys.readouterr()
        assert "BOOTSTRAP: complete." in captured.err


class TestChronologicalOrdering:
    """SCN-BOOT-006-01: Chronological ordering (mtime-based)."""

    # @tests REQ-BOOT-006, SCN-BOOT-006-01, INV-BOOT-003
    def test_files_processed_oldest_first(self, bootstrap_env, capsys):
        """Files are processed in mtime ascending order (oldest first)."""
        transcript_dir = bootstrap_env["transcript_dir"]

        # Create 3 files with controlled mtimes
        file_a = transcript_dir / "session-a.jsonl"
        file_b = transcript_dir / "session-b.jsonl"
        file_c = transcript_dir / "session-c.jsonl"

        _create_jsonl(file_a)
        _create_jsonl(file_b)
        _create_jsonl(file_c)

        # Set mtimes: b=oldest, c=middle, a=newest
        base_time = time.time() - 300
        os.utime(str(file_b), (base_time, base_time))
        os.utime(str(file_c), (base_time + 100, base_time + 100))
        os.utime(str(file_a), (base_time + 200, base_time + 200))

        # Track order of load_transcript calls
        call_order = []

        def _track_load(path):
            call_order.append(Path(path).name)
            return [{"role": "user", "content": "test"}]

        patches = _default_patches(load_transcript_side_effect=_track_load)
        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        # Expected order: b (oldest) -> c (middle) -> a (newest)
        assert call_order == ["session-b.jsonl", "session-c.jsonl", "session-a.jsonl"], (
            f"Expected chronological order, got: {call_order}"
        )


class TestPipelineFailureDoesntHalt:
    """SCN-BOOT-010-03: Pipeline failure doesn't halt processing."""

    # @tests REQ-BOOT-010, SCN-BOOT-010-03
    def test_failure_then_success(self, bootstrap_env, capsys):
        """First session fails (reflector empty), second succeeds."""
        transcript_dir = bootstrap_env["transcript_dir"]
        state_path = bootstrap_env["state_path"]

        file_fail = transcript_dir / "session-fail.jsonl"
        file_ok = transcript_dir / "session-ok.jsonl"
        _create_jsonl(file_fail)
        _create_jsonl(file_ok)

        # Ensure ordering: fail first, ok second
        base_time = time.time() - 200
        os.utime(str(file_fail), (base_time, base_time))
        os.utime(str(file_ok), (base_time + 100, base_time + 100))

        call_count = [0]

        async def _reflector_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: return empty (pipeline fail)
                return {"analysis": "", "bullet_tags": []}
            # Second call: return valid output
            return _reflector_output()

        patches = _default_patches(reflector_side_effect=_reflector_side_effect)
        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        captured = capsys.readouterr()

        summary = _parse_final_summary(captured.err)
        assert summary is not None
        assert summary["failed"] == 1, f"Expected 1 failed, got: {summary}"
        assert summary["processed"] == 1, f"Expected 1 processed, got: {summary}"

        # State file should have 1 entry (the successful session)
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert len(state["processed_sessions"]) == 1
        assert str(file_ok) in state["processed_sessions"]


class TestExistingPlaybookPreserved:
    """SCN-BOOT-014-01: Existing playbook preserved and already-processed skipped."""

    # @tests REQ-BOOT-014, SCN-BOOT-014-01, REQ-BOOT-012, SCN-BOOT-012-02
    def test_already_processed_not_reprocessed(self, bootstrap_env, capsys):
        """Already-processed sessions are skipped; new session is processed."""
        transcript_dir = bootstrap_env["transcript_dir"]
        state_path = bootstrap_env["state_path"]
        project_dir = bootstrap_env["project_dir"]

        # Create 2 .jsonl files
        file_old = transcript_dir / "session-old.jsonl"
        file_new = transcript_dir / "session-new.jsonl"
        _create_jsonl(file_old)
        _create_jsonl(file_new)

        base_time = time.time() - 200
        os.utime(str(file_old), (base_time, base_time))
        os.utime(str(file_new), (base_time + 100, base_time + 100))

        # Pre-populate state: file_old already processed
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "version": "1.0",
            "processed_sessions": {
                str(file_old): {
                    "processed_at": "2026-01-01T00:00:00",
                    "key_points_after": 3,
                }
            },
        }
        state_path.write_text(json.dumps(state))

        patches = _default_patches()
        with _PatchContext(patches) as ctx:
            asyncio.run(bootstrap_playbook.main())

            # load_transcript called only for the NEW file
            ctx.mocks["load_transcript"].assert_called_once()

        captured = capsys.readouterr()

        # Discovery should show 1 already processed, 1 to process
        discovery = _parse_discovery(captured.err)
        assert discovery is not None
        assert discovery["already"] == 1
        assert discovery["to_process"] == 1

        summary = _parse_final_summary(captured.err)
        assert summary is not None
        assert summary["processed"] == 1
        # skipped includes already-processed
        assert summary["skipped"] == 1
        assert summary["failed"] == 0


class TestSubagentInclusion:
    """SCN-BOOT-015-01: Subagent transcripts included by default."""

    # @tests REQ-BOOT-015, SCN-BOOT-015-01
    def test_subagent_files_discovered(self, bootstrap_env, capsys):
        """Both top-level session and subagent files are discovered."""
        transcript_dir = bootstrap_env["transcript_dir"]

        # Top-level session
        _create_jsonl(transcript_dir / "session-top.jsonl")

        # Subagent file: {session_uuid}/subagents/agent-{id}.jsonl
        subagent_dir = transcript_dir / "abc123" / "subagents"
        _create_jsonl(subagent_dir / "agent-1.jsonl")

        patches = _default_patches()
        with _PatchContext(patches) as ctx:
            asyncio.run(bootstrap_playbook.main())

            # Both files should trigger load_transcript
            assert ctx.mocks["load_transcript"].call_count == 2

        captured = capsys.readouterr()
        discovery = _parse_discovery(captured.err)
        assert discovery is not None
        assert discovery["total"] == 2
        assert discovery["sessions"] == 1
        assert discovery["subagents"] == 1


class TestSubagentExclusion:
    """SCN-BOOT-015-02: Subagents excluded when SKIP_SUBAGENTS=true."""

    # @tests REQ-BOOT-015, SCN-BOOT-015-02
    def test_skip_subagents_env_excludes_subagents(self, bootstrap_env, capsys, monkeypatch):
        """Setting SKIP_SUBAGENTS=true excludes subagent files from discovery."""
        transcript_dir = bootstrap_env["transcript_dir"]
        monkeypatch.setenv("AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS", "true")

        # Top-level session
        _create_jsonl(transcript_dir / "session-top.jsonl")

        # Subagent file
        subagent_dir = transcript_dir / "abc123" / "subagents"
        _create_jsonl(subagent_dir / "agent-1.jsonl")

        patches = _default_patches()
        with _PatchContext(patches) as ctx:
            asyncio.run(bootstrap_playbook.main())

            # Only the top-level file should trigger load_transcript
            assert ctx.mocks["load_transcript"].call_count == 1

        captured = capsys.readouterr()
        discovery = _parse_discovery(captured.err)
        assert discovery is not None
        assert discovery["total"] == 1
        assert discovery["sessions"] == 1
        assert discovery["subagents"] == 0


class TestCounterIdentity:
    """INV-BOOT-010: Counter identity: processed + skipped + failed == total."""

    # @tests INV-BOOT-010, SCN-BOOT-004-01, SCN-BOOT-003-02, SCN-BOOT-004-02
    def test_mixed_outcomes_counter_identity(self, bootstrap_env, capsys):
        """With 3 files (1 success, 1 reflector-fail, 1 empty), counters add up."""
        transcript_dir = bootstrap_env["transcript_dir"]

        file_ok = transcript_dir / "session-ok.jsonl"
        file_fail = transcript_dir / "session-fail.jsonl"
        file_empty = transcript_dir / "session-empty.jsonl"
        _create_jsonl(file_ok)
        _create_jsonl(file_fail)
        _create_jsonl(file_empty)

        # Control ordering
        base_time = time.time() - 300
        os.utime(str(file_ok), (base_time, base_time))
        os.utime(str(file_fail), (base_time + 100, base_time + 100))
        os.utime(str(file_empty), (base_time + 200, base_time + 200))

        call_count = [0]

        def _load_transcript_side_effect(path):
            call_count[0] += 1
            name = Path(path).name
            if name == "session-empty.jsonl":
                return []  # empty transcript -> skipped
            return [{"role": "user", "content": "test"}]

        reflector_call_count = [0]

        async def _reflector_side_effect(*args, **kwargs):
            reflector_call_count[0] += 1
            if reflector_call_count[0] == 2:
                # Second reflector call (file_fail) returns empty
                return {"analysis": "", "bullet_tags": []}
            return _reflector_output()

        patches = _default_patches(
            load_transcript_side_effect=_load_transcript_side_effect,
            reflector_side_effect=_reflector_side_effect,
        )
        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        captured = capsys.readouterr()

        discovery = _parse_discovery(captured.err)
        summary = _parse_final_summary(captured.err)
        assert discovery is not None, f"No discovery in stderr: {captured.err!r}"
        assert summary is not None, f"No summary in stderr: {captured.err!r}"

        total = discovery["total"]
        assert total == 3
        assert summary["processed"] == 1
        assert summary["skipped"] == 1   # empty transcript
        assert summary["failed"] == 1    # reflector empty
        assert summary["processed"] + summary["skipped"] + summary["failed"] == total


class TestPipelineStepOrder:
    """INV-BOOT-001: Pipeline steps execute in correct order."""

    # @tests INV-BOOT-001, REQ-BOOT-004
    def test_pipeline_steps_called_in_order(self, bootstrap_env, capsys):
        """Verify the 7 pipeline steps are called in the correct sequence."""
        transcript_dir = bootstrap_env["transcript_dir"]

        _create_jsonl(transcript_dir / "session-order.jsonl")

        call_log = []

        def _make_tracker(name, rv=None):
            def _tracker(*args, **kwargs):
                call_log.append(name)
                return rv
            return _tracker

        async def _async_tracker(name, rv):
            async def _tracker(*args, **kwargs):
                call_log.append(name)
                return rv
            return _tracker

        patches = _default_patches()

        # Override with tracking versions
        patches["extract_cited_ids"] = patch(
            "bootstrap_playbook.extract_cited_ids",
            side_effect=_make_tracker("extract_cited_ids", []),
        )
        patches["apply_bullet_tags"] = patch(
            "bootstrap_playbook.apply_bullet_tags",
            side_effect=_make_tracker("apply_bullet_tags", None),
        )
        patches["apply_structured_operations"] = patch(
            "bootstrap_playbook.apply_structured_operations",
            side_effect=_make_tracker("apply_structured_operations", _one_item_playbook()),
        )
        patches["run_deduplication"] = patch(
            "bootstrap_playbook.run_deduplication",
            side_effect=_make_tracker("run_deduplication", _one_item_playbook()),
        )
        patches["prune_harmful"] = patch(
            "bootstrap_playbook.prune_harmful",
            side_effect=_make_tracker("prune_harmful", _one_item_playbook()),
        )

        # Async trackers
        async def _reflector_tracker(*args, **kwargs):
            call_log.append("run_reflector")
            return _reflector_output()

        async def _curator_tracker(*args, **kwargs):
            call_log.append("run_curator")
            return _curator_output()

        patches["run_reflector"] = patch(
            "bootstrap_playbook.run_reflector",
            new_callable=AsyncMock,
            side_effect=_reflector_tracker,
        )
        patches["run_curator"] = patch(
            "bootstrap_playbook.run_curator",
            new_callable=AsyncMock,
            side_effect=_curator_tracker,
        )

        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        expected_order = [
            "extract_cited_ids",
            "run_reflector",
            "apply_bullet_tags",
            "run_curator",
            "apply_structured_operations",
            "run_deduplication",
            "prune_harmful",
        ]
        assert call_log == expected_order, f"Pipeline step order wrong: {call_log}"


class TestCumulativeAccumulation:
    """SCN-BOOT-007-01: Cumulative playbook across sessions."""

    # @tests REQ-BOOT-007, SCN-BOOT-007-01, INV-BOOT-004
    def test_session2_receives_modified_playbook(self, bootstrap_env, capsys):
        """Session 2's reflector receives playbook modified by session 1."""
        transcript_dir = bootstrap_env["transcript_dir"]

        file_1 = transcript_dir / "session-1.jsonl"
        file_2 = transcript_dir / "session-2.jsonl"
        _create_jsonl(file_1)
        _create_jsonl(file_2)

        base_time = time.time() - 200
        os.utime(str(file_1), (base_time, base_time))
        os.utime(str(file_2), (base_time + 100, base_time + 100))

        # Track what playbook run_reflector receives in session 2
        reflector_playbooks = []
        reflector_call_count = [0]

        async def _reflector_side_effect(messages, playbook, cited_ids):
            reflector_call_count[0] += 1
            import copy
            reflector_playbooks.append(copy.deepcopy(playbook))
            return _reflector_output()

        # apply_structured_operations returns a playbook with 1 item
        apply_ops_call_count = [0]

        def _apply_ops_side_effect(playbook, operations):
            apply_ops_call_count[0] += 1
            return _one_item_playbook()

        patches = _default_patches(
            reflector_side_effect=_reflector_side_effect,
        )
        patches["apply_structured_operations"] = patch(
            "bootstrap_playbook.apply_structured_operations",
            side_effect=_apply_ops_side_effect,
        )
        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        # Session 1 reflector receives empty playbook
        assert len(reflector_playbooks) == 2
        session_1_pb = reflector_playbooks[0]
        session_2_pb = reflector_playbooks[1]

        # Session 1 starts with empty sections
        assert len(session_1_pb.get("sections", {}).get("PATTERNS & APPROACHES", [])) == 0

        # Session 2 sees the playbook modified by session 1 (has 1 item)
        assert len(session_2_pb.get("sections", {}).get("PATTERNS & APPROACHES", [])) == 1


class TestLoadPlaybookCalledOnce:
    """INV-BOOT-004, INV-BOOT-009: Playbook loaded once, never reset."""

    # @tests INV-BOOT-004, INV-BOOT-009, REQ-BOOT-014
    def test_load_playbook_called_exactly_once(self, bootstrap_env, capsys):
        """load_playbook is called exactly once (before the loop)."""
        transcript_dir = bootstrap_env["transcript_dir"]

        _create_jsonl(transcript_dir / "s1.jsonl")
        _create_jsonl(transcript_dir / "s2.jsonl")
        _create_jsonl(transcript_dir / "s3.jsonl")

        patches = _default_patches()
        with _PatchContext(patches) as ctx:
            asyncio.run(bootstrap_playbook.main())

            ctx.mocks["load_playbook"].assert_called_once()


class TestSavePlaybookPerSession:
    """REQ-BOOT-005: Playbook saved after each successful session."""

    # @tests REQ-BOOT-005
    def test_save_called_per_session(self, bootstrap_env, capsys):
        """save_playbook is called once per successful session."""
        transcript_dir = bootstrap_env["transcript_dir"]

        _create_jsonl(transcript_dir / "s1.jsonl")
        _create_jsonl(transcript_dir / "s2.jsonl")

        patches = _default_patches()
        with _PatchContext(patches) as ctx:
            asyncio.run(bootstrap_playbook.main())

            assert ctx.mocks["save_playbook"].call_count == 2


class TestStateFileUpdatedPerSession:
    """REQ-BOOT-012: State file updated after each successful session."""

    # @tests REQ-BOOT-012, SCN-BOOT-012-01
    def test_state_has_entry_per_processed_session(self, bootstrap_env, capsys):
        """After processing N sessions, state file has N entries."""
        transcript_dir = bootstrap_env["transcript_dir"]
        state_path = bootstrap_env["state_path"]

        _create_jsonl(transcript_dir / "s1.jsonl")
        _create_jsonl(transcript_dir / "s2.jsonl")

        patches = _default_patches()
        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert len(state["processed_sessions"]) == 2

        # Each entry has required fields
        for path, entry in state["processed_sessions"].items():
            assert "processed_at" in entry
            assert "key_points_after" in entry


class TestProgressEventSequence:
    """REQ-BOOT-011: Progress events emitted in correct sequence."""

    # @tests REQ-BOOT-011, SCN-BOOT-011-01, SCN-BOOT-011-02, SCN-BOOT-011-04, SCN-BOOT-011-05
    def test_all_event_types_present(self, bootstrap_env, capsys):
        """With 1 session, all relevant event types appear in order."""
        transcript_dir = bootstrap_env["transcript_dir"]

        _create_jsonl(transcript_dir / "session-events.jsonl")

        patches = _default_patches()
        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        captured = capsys.readouterr()
        lines = [l for l in captured.err.splitlines() if l.startswith("BOOTSTRAP:")]

        # Should have: discovery, session-start, session-complete, final-summary
        assert len(lines) >= 4, f"Expected >= 4 progress lines, got {len(lines)}: {lines}"

        assert "discovered" in lines[0]
        assert "processing" in lines[1]
        assert "completed" in lines[2]
        assert "complete." in lines[3]

    # @tests REQ-BOOT-011, SCN-BOOT-011-03
    def test_skip_event_for_empty_transcript(self, bootstrap_env, capsys):
        """Skip event appears between start and final summary."""
        transcript_dir = bootstrap_env["transcript_dir"]

        _create_jsonl(transcript_dir / "session-empty.jsonl")

        patches = _default_patches(load_transcript_rv=[])
        with _PatchContext(patches):
            asyncio.run(bootstrap_playbook.main())

        captured = capsys.readouterr()
        assert "skipped session-empty.jsonl: empty transcript" in captured.err


class TestInterSessionDelay:
    """REQ-BOOT-010: Inter-session delay."""

    # @tests REQ-BOOT-010, SCN-BOOT-010-01
    def test_sleep_called_between_sessions(self, bootstrap_env, capsys, monkeypatch):
        """asyncio.sleep is called between sessions (not after the last one)."""
        transcript_dir = bootstrap_env["transcript_dir"]
        monkeypatch.setenv("AGENTIC_CONTEXT_BOOTSTRAP_DELAY", "0.5")

        file_1 = transcript_dir / "s1.jsonl"
        file_2 = transcript_dir / "s2.jsonl"
        _create_jsonl(file_1)
        _create_jsonl(file_2)

        base_time = time.time() - 200
        os.utime(str(file_1), (base_time, base_time))
        os.utime(str(file_2), (base_time + 100, base_time + 100))

        sleep_calls = []
        original_sleep = asyncio.sleep

        async def _tracked_sleep(seconds):
            sleep_calls.append(seconds)
            # Don't actually sleep to keep tests fast

        patches = _default_patches()
        with _PatchContext(patches), patch("asyncio.sleep", side_effect=_tracked_sleep):
            asyncio.run(bootstrap_playbook.main())

        # Sleep should be called between session 1 and session 2, but not after session 2
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == 0.5


class TestTranscriptDirOverride:
    """SCN-BOOT-001-03: Transcript dir override via env var."""

    # @tests REQ-BOOT-001, SCN-BOOT-001-03
    def test_override_dir_used(self, bootstrap_env, capsys, monkeypatch):
        """AGENTIC_CONTEXT_TRANSCRIPT_DIR overrides the computed path."""
        transcript_dir = bootstrap_env["transcript_dir"]

        # Create an alternative transcript dir
        alt_dir = bootstrap_env["project_dir"] / "alt_transcripts"
        alt_dir.mkdir()
        _create_jsonl(alt_dir / "alt-session.jsonl")

        monkeypatch.setenv("AGENTIC_CONTEXT_TRANSCRIPT_DIR", str(alt_dir))

        patches = _default_patches()
        with _PatchContext(patches) as ctx:
            asyncio.run(bootstrap_playbook.main())

            ctx.mocks["load_transcript"].assert_called_once()
            call_path = ctx.mocks["load_transcript"].call_args[0][0]
            assert "alt-session.jsonl" in call_path
