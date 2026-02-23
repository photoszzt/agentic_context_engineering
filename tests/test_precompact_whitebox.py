# Spec: docs/hooks/spec.md
# Testing: docs/hooks/testing.md
"""
White-box tests for the precompact pipeline (src/hooks/precompact.py).

Covers all 9 REQ-PRECOMPACT-* requirements, all 11 SCN-PRECOMPACT-* scenarios,
and all 3 INV-PRECOMPACT-* invariants.
"""

import asyncio
import importlib
import io
import json
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# Ensure the project root and src/hooks are on sys.path.
# precompact.py uses `from common import ...` (bare import), so src/hooks/
# must be on sys.path for the import to succeed.
_project_root = str(Path(__file__).resolve().parent.parent)
_src_hooks_dir = str(Path(__file__).resolve().parent.parent / "src" / "hooks")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _src_hooks_dir not in sys.path:
    sys.path.insert(0, _src_hooks_dir)

import src.hooks.precompact as _precompact_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Path to the precompact.py source file for source inspection tests
PRECOMPACT_SOURCE = Path(__file__).resolve().parent.parent / "src" / "hooks" / "precompact.py"
SESSION_END_SOURCE = Path(__file__).resolve().parent.parent / "src" / "hooks" / "session_end.py"


def _make_playbook():
    """Return a minimal valid playbook dict for testing."""
    return {
        "version": "1.0",
        "last_updated": None,
        "sections": {
            "PATTERNS & APPROACHES": [],
            "MISTAKES TO AVOID": [],
            "USER PREFERENCES": [],
            "PROJECT CONTEXT": [],
            "OTHERS": [],
        },
    }


def _make_stdin_json(transcript_path="/tmp/fake_transcript.jsonl"):
    """Return a JSON string suitable for stdin."""
    return json.dumps({"transcript_path": transcript_path})


def _make_messages(count=3):
    """Return a list of fake messages."""
    msgs = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"Message {i}"})
    return msgs


def _setup_pipeline_mocks(monkeypatch, messages=None, playbook=None):
    """Mock all common.py functions used by precompact.py.

    Returns a dict of all mocks for assertion.
    """
    if messages is None:
        messages = _make_messages()
    if playbook is None:
        playbook = _make_playbook()

    # Stdin mock
    stdin_data = _make_stdin_json()
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_data))

    # Pipeline function mocks -- all patched on the precompact module
    mock_load_transcript = MagicMock(return_value=messages)
    monkeypatch.setattr(_precompact_module, "load_transcript", mock_load_transcript)

    mock_load_playbook = MagicMock(return_value=playbook)
    monkeypatch.setattr(_precompact_module, "load_playbook", mock_load_playbook)

    mock_save_playbook = MagicMock()
    monkeypatch.setattr(_precompact_module, "save_playbook", mock_save_playbook)

    mock_clear_session = MagicMock()
    monkeypatch.setattr(_precompact_module, "clear_session", mock_clear_session)

    mock_extract_cited_ids = MagicMock(return_value=["pat-001"])
    monkeypatch.setattr(_precompact_module, "extract_cited_ids", mock_extract_cited_ids)

    mock_run_reflector = AsyncMock(
        return_value={"analysis": "test analysis", "bullet_tags": [{"name": "pat-001", "tag": "helpful"}]}
    )
    monkeypatch.setattr(_precompact_module, "run_reflector", mock_run_reflector)

    mock_apply_bullet_tags = MagicMock(return_value=playbook)
    monkeypatch.setattr(_precompact_module, "apply_bullet_tags", mock_apply_bullet_tags)

    mock_run_curator = AsyncMock(
        return_value={"reasoning": "test reasoning", "operations": [{"type": "ADD", "text": "new bullet", "section": "OTHERS"}]}
    )
    monkeypatch.setattr(_precompact_module, "run_curator", mock_run_curator)

    mock_apply_structured_operations = MagicMock(return_value=playbook)
    monkeypatch.setattr(_precompact_module, "apply_structured_operations", mock_apply_structured_operations)

    mock_run_deduplication = MagicMock(return_value=playbook)
    monkeypatch.setattr(_precompact_module, "run_deduplication", mock_run_deduplication)

    mock_prune_harmful = MagicMock(return_value=playbook)
    monkeypatch.setattr(_precompact_module, "prune_harmful", mock_prune_harmful)

    return {
        "load_transcript": mock_load_transcript,
        "load_playbook": mock_load_playbook,
        "save_playbook": mock_save_playbook,
        "clear_session": mock_clear_session,
        "extract_cited_ids": mock_extract_cited_ids,
        "run_reflector": mock_run_reflector,
        "apply_bullet_tags": mock_apply_bullet_tags,
        "run_curator": mock_run_curator,
        "apply_structured_operations": mock_apply_structured_operations,
        "run_deduplication": mock_run_deduplication,
        "prune_harmful": mock_prune_harmful,
    }


# ---------------------------------------------------------------------------
# REQ-PRECOMPACT-001: Pipeline Replacement
# ---------------------------------------------------------------------------


class TestPipelineReplacement:
    """@tests REQ-PRECOMPACT-001, SCN-PRECOMPACT-001-01, SCN-PRECOMPACT-001-02"""

    def test_pipeline_replacement_no_old_imports(self):
        """@tests REQ-PRECOMPACT-001

        Verify precompact.py does NOT import extract_keypoints or update_playbook_data,
        and DOES import all 7 new pipeline functions plus load_playbook, save_playbook, etc.
        """
        source = PRECOMPACT_SOURCE.read_text()

        # Old functions must NOT appear
        assert "extract_keypoints" not in source, "precompact.py must not reference extract_keypoints"
        assert "update_playbook_data" not in source, "precompact.py must not reference update_playbook_data"

        # New pipeline functions MUST appear in imports
        required_imports = [
            "load_playbook",
            "save_playbook",
            "load_transcript",
            "extract_cited_ids",
            "run_reflector",
            "apply_bullet_tags",
            "run_curator",
            "apply_structured_operations",
            "run_deduplication",
            "prune_harmful",
            "clear_session",
        ]
        for func_name in required_imports:
            assert func_name in source, f"precompact.py must import {func_name}"

    def test_scn_old_imports_removed(self):
        """@tests SCN-PRECOMPACT-001-01

        GIVEN the upgraded precompact.py source file
        WHEN the import statements are inspected
        THEN zero matches for extract_keypoints or update_playbook_data
        AND the import block includes all 7 new pipeline functions
        """
        source = PRECOMPACT_SOURCE.read_text()

        # Neither function name appears anywhere in the file
        assert "extract_keypoints" not in source
        assert "update_playbook_data" not in source

        # All 7 pipeline functions in the import block
        new_pipeline_funcs = [
            "extract_cited_ids",
            "run_reflector",
            "apply_bullet_tags",
            "run_curator",
            "apply_structured_operations",
            "run_deduplication",
            "prune_harmful",
        ]
        for func_name in new_pipeline_funcs:
            assert func_name in source, f"Missing pipeline import: {func_name}"

    def test_scn_import_smoke_test(self):
        """@tests SCN-PRECOMPACT-001-02

        GIVEN the upgraded precompact.py exists at src/hooks/precompact.py
        WHEN import precompact is executed
        THEN no ImportError or AttributeError is raised
        """
        # Force re-import to verify no import errors
        try:
            importlib.import_module("src.hooks.precompact")
        except (ImportError, AttributeError) as exc:
            pytest.fail(f"Import of precompact.py failed: {exc}")

    def test_pipeline_call_order(self, monkeypatch):
        """@tests REQ-PRECOMPACT-001

        Verify the pipeline functions are called in this exact order:
        extract_cited_ids, run_reflector, apply_bullet_tags, run_curator,
        apply_structured_operations, run_deduplication, prune_harmful
        """
        call_order = []
        messages = _make_messages()
        playbook = _make_playbook()

        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        monkeypatch.setattr(_precompact_module, "load_transcript", lambda p: messages)
        monkeypatch.setattr(_precompact_module, "load_playbook", lambda: playbook)

        def track(name, return_value=None, is_async=False):
            if is_async:
                async def async_fn(*args, **kwargs):
                    call_order.append(name)
                    return return_value
                return async_fn
            else:
                def fn(*args, **kwargs):
                    call_order.append(name)
                    return return_value
                return fn

        reflector_output = {"analysis": "test", "bullet_tags": []}
        curator_output = {"reasoning": "test", "operations": []}

        monkeypatch.setattr(_precompact_module, "extract_cited_ids", track("extract_cited_ids", []))
        monkeypatch.setattr(_precompact_module, "run_reflector", track("run_reflector", reflector_output, is_async=True))
        monkeypatch.setattr(_precompact_module, "apply_bullet_tags", track("apply_bullet_tags", playbook))
        monkeypatch.setattr(_precompact_module, "run_curator", track("run_curator", curator_output, is_async=True))
        monkeypatch.setattr(_precompact_module, "apply_structured_operations", track("apply_structured_operations", playbook))
        monkeypatch.setattr(_precompact_module, "run_deduplication", track("run_deduplication", playbook))
        monkeypatch.setattr(_precompact_module, "prune_harmful", track("prune_harmful", playbook))
        monkeypatch.setattr(_precompact_module, "save_playbook", track("save_playbook"))
        monkeypatch.setattr(_precompact_module, "clear_session", track("clear_session"))

        asyncio.run(_precompact_module.main())

        expected_order = [
            "extract_cited_ids",
            "run_reflector",
            "apply_bullet_tags",
            "run_curator",
            "apply_structured_operations",
            "run_deduplication",
            "prune_harmful",
            "save_playbook",
            "clear_session",
        ]
        assert call_order == expected_order, f"Expected {expected_order}, got {call_order}"


# ---------------------------------------------------------------------------
# REQ-PRECOMPACT-002: Two-Step LLM Flow (Async)
# ---------------------------------------------------------------------------


class TestTwoStepLLMFlow:
    """@tests REQ-PRECOMPACT-002, SCN-PRECOMPACT-002-01"""

    def test_reflector_curator_arguments(self, monkeypatch):
        """@tests REQ-PRECOMPACT-002

        Verify run_reflector is called with (messages, playbook, cited_ids)
        and run_curator is called with (reflector_output, playbook).
        """
        mocks = _setup_pipeline_mocks(monkeypatch)
        asyncio.run(_precompact_module.main())

        # Reflector should receive (messages, playbook, cited_ids)
        mocks["run_reflector"].assert_called_once()
        reflector_args = mocks["run_reflector"].call_args[0]
        assert len(reflector_args) == 3, "run_reflector must receive 3 positional args"
        # First arg is messages (list)
        assert isinstance(reflector_args[0], list)
        # Second arg is playbook (dict with 'sections')
        assert "sections" in reflector_args[1]
        # Third arg is cited_ids (list)
        assert isinstance(reflector_args[2], list)

        # Curator should receive (reflector_output, playbook)
        mocks["run_curator"].assert_called_once()
        curator_args = mocks["run_curator"].call_args[0]
        assert len(curator_args) == 2, "run_curator must receive 2 positional args"
        # First arg is reflector_output (dict with 'analysis')
        assert "analysis" in curator_args[0]
        # Second arg is playbook
        assert "sections" in curator_args[1]

    def test_scn_reflector_curator_call_arguments(self, monkeypatch):
        """@tests SCN-PRECOMPACT-002-01

        GIVEN precompact.py is running with a non-empty transcript and playbook
        AND extract_cited_ids has returned cited_ids
        WHEN the reflector call executes
        THEN run_reflector is called with (messages, playbook, cited_ids)
        AND run_curator is called with (reflector_output, playbook)
        AND the curator does NOT receive messages directly
        """
        messages = _make_messages(5)
        playbook = _make_playbook()
        # Add some sections so it's realistic
        playbook["sections"]["PATTERNS & APPROACHES"] = [
            {"name": "pat-001", "text": "test", "helpful": 1, "harmful": 0},
            {"name": "pat-002", "text": "test2", "helpful": 0, "harmful": 0},
            {"name": "pat-003", "text": "test3", "helpful": 2, "harmful": 1},
        ]
        cited_ids = ["pat-001", "pat-002"]

        mocks = _setup_pipeline_mocks(monkeypatch, messages=messages, playbook=playbook)
        mocks["extract_cited_ids"].return_value = cited_ids

        asyncio.run(_precompact_module.main())

        # Reflector args: (messages, playbook, cited_ids)
        ref_args = mocks["run_reflector"].call_args[0]
        assert ref_args[0] is messages, "reflector should receive the raw transcript"
        assert ref_args[1] is playbook, "reflector should receive the playbook"
        assert ref_args[2] is cited_ids, "reflector should receive cited_ids"

        # Curator args: (reflector_output, playbook) -- NOT messages
        cur_args = mocks["run_curator"].call_args[0]
        assert cur_args[0] is mocks["run_reflector"].return_value, "curator receives reflector output"
        assert cur_args[1] is playbook, "curator receives playbook"
        # Curator must NOT receive messages
        for arg in cur_args:
            assert arg is not messages, "curator must NOT receive messages directly"

    def test_await_usage(self, monkeypatch):
        """@tests REQ-PRECOMPACT-002

        Verify that run_reflector and run_curator are awaited (async).
        AsyncMock will raise TypeError if called without await.
        """
        mocks = _setup_pipeline_mocks(monkeypatch)

        # If main() does not use await, AsyncMock would return a coroutine
        # that is never awaited, and the pipeline would get coroutine objects
        # instead of dicts. This test verifies correct await usage.
        asyncio.run(_precompact_module.main())

        # AsyncMock tracks .await_count
        assert mocks["run_reflector"].await_count == 1, "run_reflector must be awaited exactly once"
        assert mocks["run_curator"].await_count == 1, "run_curator must be awaited exactly once"


# ---------------------------------------------------------------------------
# REQ-PRECOMPACT-003: Counter Update Before Curator
# ---------------------------------------------------------------------------


class TestCounterUpdateBeforeCurator:
    """@tests REQ-PRECOMPACT-003, SCN-PRECOMPACT-003-01, INV-PRECOMPACT-001"""

    def test_counter_update_before_curator(self, monkeypatch):
        """@tests REQ-PRECOMPACT-003

        Verify apply_bullet_tags is called BEFORE run_curator.
        """
        call_order = []
        messages = _make_messages()
        playbook = _make_playbook()

        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        monkeypatch.setattr(_precompact_module, "load_transcript", lambda p: messages)
        monkeypatch.setattr(_precompact_module, "load_playbook", lambda: playbook)
        monkeypatch.setattr(_precompact_module, "extract_cited_ids", lambda m: [])

        async def mock_reflector(*args):
            call_order.append("run_reflector")
            return {"analysis": "", "bullet_tags": []}
        monkeypatch.setattr(_precompact_module, "run_reflector", mock_reflector)

        def mock_apply_bt(*args):
            call_order.append("apply_bullet_tags")
            return playbook
        monkeypatch.setattr(_precompact_module, "apply_bullet_tags", mock_apply_bt)

        async def mock_curator(*args):
            call_order.append("run_curator")
            return {"reasoning": "", "operations": []}
        monkeypatch.setattr(_precompact_module, "run_curator", mock_curator)

        monkeypatch.setattr(_precompact_module, "apply_structured_operations", lambda p, ops: playbook)
        monkeypatch.setattr(_precompact_module, "run_deduplication", lambda p: playbook)
        monkeypatch.setattr(_precompact_module, "prune_harmful", lambda p: playbook)
        monkeypatch.setattr(_precompact_module, "save_playbook", lambda p: None)
        monkeypatch.setattr(_precompact_module, "clear_session", lambda: None)

        asyncio.run(_precompact_module.main())

        bt_idx = call_order.index("apply_bullet_tags")
        cur_idx = call_order.index("run_curator")
        assert bt_idx < cur_idx, "apply_bullet_tags must be called BEFORE run_curator"

    def test_scn_bullet_tags_applied_before_curator(self, monkeypatch):
        """@tests SCN-PRECOMPACT-003-01

        GIVEN run_reflector returned {"analysis": "...", "bullet_tags": [{"id": "b1", "tag": "helpful"}]}
        WHEN the pipeline proceeds
        THEN apply_bullet_tags(playbook, [{"id": "b1", "tag": "helpful"}]) is called
        AND run_curator(reflector_output, playbook) is called AFTER apply_bullet_tags completes
        """
        bullet_tags = [{"id": "b1", "tag": "helpful"}]
        reflector_output = {"analysis": "some analysis", "bullet_tags": bullet_tags}

        mocks = _setup_pipeline_mocks(monkeypatch)
        mocks["run_reflector"].return_value = reflector_output

        asyncio.run(_precompact_module.main())

        # apply_bullet_tags receives playbook and bullet_tags from reflector
        mocks["apply_bullet_tags"].assert_called_once()
        bt_args = mocks["apply_bullet_tags"].call_args[0]
        assert bt_args[1] == bullet_tags, "apply_bullet_tags should receive the reflector's bullet_tags"

    def test_invariant_counter_update_precedes_curator(self, monkeypatch):
        """@tests-invariant INV-PRECOMPACT-001

        In precompact.py, apply_bullet_tags() is ALWAYS called before run_curator().
        The curator NEVER sees stale helpful/harmful counters.
        """
        call_sequence = []
        messages = _make_messages()
        playbook = _make_playbook()

        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        monkeypatch.setattr(_precompact_module, "load_transcript", lambda p: messages)
        monkeypatch.setattr(_precompact_module, "load_playbook", lambda: playbook)
        monkeypatch.setattr(_precompact_module, "extract_cited_ids", lambda m: [])

        async def mock_reflector(*args):
            return {"analysis": "", "bullet_tags": [{"name": "x", "tag": "helpful"}]}
        monkeypatch.setattr(_precompact_module, "run_reflector", mock_reflector)

        def mock_bt(*args):
            call_sequence.append("apply_bullet_tags")
            return args[0]
        monkeypatch.setattr(_precompact_module, "apply_bullet_tags", mock_bt)

        async def mock_curator(*args):
            call_sequence.append("run_curator")
            return {"reasoning": "", "operations": []}
        monkeypatch.setattr(_precompact_module, "run_curator", mock_curator)

        monkeypatch.setattr(_precompact_module, "apply_structured_operations", lambda p, ops: playbook)
        monkeypatch.setattr(_precompact_module, "run_deduplication", lambda p: playbook)
        monkeypatch.setattr(_precompact_module, "prune_harmful", lambda p: playbook)
        monkeypatch.setattr(_precompact_module, "save_playbook", lambda p: None)
        monkeypatch.setattr(_precompact_module, "clear_session", lambda: None)

        asyncio.run(_precompact_module.main())

        assert "apply_bullet_tags" in call_sequence, "apply_bullet_tags must be called"
        assert "run_curator" in call_sequence, "run_curator must be called"
        assert call_sequence.index("apply_bullet_tags") < call_sequence.index("run_curator"), \
            "INV-PRECOMPACT-001: apply_bullet_tags MUST precede run_curator"


# ---------------------------------------------------------------------------
# REQ-PRECOMPACT-004: Post-Curator Dedup and Prune
# ---------------------------------------------------------------------------


class TestPostCuratorDedupAndPrune:
    """@tests REQ-PRECOMPACT-004, SCN-PRECOMPACT-004-01"""

    def test_dedup_then_prune_ordering(self, monkeypatch):
        """@tests REQ-PRECOMPACT-004

        Verify run_deduplication is called before prune_harmful,
        and both occur AFTER apply_structured_operations.
        """
        call_order = []
        messages = _make_messages()
        playbook = _make_playbook()

        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        monkeypatch.setattr(_precompact_module, "load_transcript", lambda p: messages)
        monkeypatch.setattr(_precompact_module, "load_playbook", lambda: playbook)
        monkeypatch.setattr(_precompact_module, "extract_cited_ids", lambda m: [])

        async def mock_reflector(*args):
            return {"analysis": "", "bullet_tags": []}
        monkeypatch.setattr(_precompact_module, "run_reflector", mock_reflector)
        monkeypatch.setattr(_precompact_module, "apply_bullet_tags", lambda p, bt: p)

        async def mock_curator(*args):
            return {"reasoning": "", "operations": []}
        monkeypatch.setattr(_precompact_module, "run_curator", mock_curator)

        def track(name):
            def fn(*args, **kwargs):
                call_order.append(name)
                return playbook
            return fn

        monkeypatch.setattr(_precompact_module, "apply_structured_operations", track("apply_structured_operations"))
        monkeypatch.setattr(_precompact_module, "run_deduplication", track("run_deduplication"))
        monkeypatch.setattr(_precompact_module, "prune_harmful", track("prune_harmful"))
        monkeypatch.setattr(_precompact_module, "save_playbook", lambda p: None)
        monkeypatch.setattr(_precompact_module, "clear_session", lambda: None)

        asyncio.run(_precompact_module.main())

        aso_idx = call_order.index("apply_structured_operations")
        dedup_idx = call_order.index("run_deduplication")
        prune_idx = call_order.index("prune_harmful")
        assert aso_idx < dedup_idx < prune_idx, \
            "Order must be: apply_structured_operations < run_deduplication < prune_harmful"

    def test_scn_dedup_then_prune_after_curator_ops(self, monkeypatch):
        """@tests SCN-PRECOMPACT-004-01

        GIVEN run_curator returned {"operations": [{"op": "add", ...}]}
        AND apply_structured_operations has returned an updated playbook
        WHEN the final pipeline steps execute
        THEN run_deduplication is called and its return value becomes the new playbook
        AND prune_harmful is called on the deduplication result
        AND save_playbook receives the pruned result
        """
        messages = _make_messages()
        dedup_playbook = _make_playbook()
        dedup_playbook["_marker"] = "deduped"
        pruned_playbook = _make_playbook()
        pruned_playbook["_marker"] = "pruned"

        mocks = _setup_pipeline_mocks(monkeypatch, messages=messages)
        mocks["run_deduplication"].return_value = dedup_playbook
        mocks["prune_harmful"].return_value = pruned_playbook

        asyncio.run(_precompact_module.main())

        # prune_harmful should receive the deduplication result
        prune_args = mocks["prune_harmful"].call_args[0]
        assert prune_args[0] is dedup_playbook, "prune_harmful must receive run_deduplication's output"

        # save_playbook should receive the pruned result
        save_args = mocks["save_playbook"].call_args[0]
        assert save_args[0] is pruned_playbook, "save_playbook must receive prune_harmful's output"


# ---------------------------------------------------------------------------
# REQ-PRECOMPACT-005: Pipeline Parity with session_end.py
# ---------------------------------------------------------------------------


class TestPipelineParity:
    """@tests REQ-PRECOMPACT-005, SCN-PRECOMPACT-005-01, INV-PRECOMPACT-002"""

    def test_parity_with_session_end(self):
        """@tests REQ-PRECOMPACT-005

        Verify precompact.py and session_end.py share the same pipeline function
        call sequence from load_playbook through clear_session.
        Checks both presence AND order (sequential .find() like test_scn_side_by_side_parity).
        Note: Ordering is also verified by SCN-PRECOMPACT-005-01 and INV-PRECOMPACT-002.
        """
        precompact_src = PRECOMPACT_SOURCE.read_text()
        session_end_src = SESSION_END_SOURCE.read_text()

        # Extract the pipeline function call sequence from both files
        pipeline_funcs = [
            "extract_cited_ids",
            "run_reflector",
            "apply_bullet_tags",
            "run_curator",
            "apply_structured_operations",
            "run_deduplication",
            "prune_harmful",
            "save_playbook",
            "clear_session",
        ]

        # Check presence in both files
        for func in pipeline_funcs:
            assert func in precompact_src, f"precompact.py missing pipeline function: {func}"
            assert func in session_end_src, f"session_end.py missing pipeline function: {func}"

        # Check order in precompact.py (sequential .find())
        prev_pos = 0
        for func in pipeline_funcs:
            pos = precompact_src.find(func + "(", prev_pos)
            assert pos >= prev_pos, (
                f"In precompact.py, '{func}(' not found after position {prev_pos}; "
                f"pipeline functions must appear in the specified order"
            )
            prev_pos = pos + 1  # advance past this match

        # Check order in session_end.py (sequential .find())
        prev_pos = 0
        for func in pipeline_funcs:
            pos = session_end_src.find(func + "(", prev_pos)
            assert pos >= prev_pos, (
                f"In session_end.py, '{func}(' not found after position {prev_pos}; "
                f"pipeline functions must appear in the specified order"
            )
            prev_pos = pos + 1  # advance past this match

    def test_scn_side_by_side_parity(self):
        """@tests SCN-PRECOMPACT-005-01

        GIVEN the upgraded precompact.py and current session_end.py
        WHEN the pipeline section of each is compared
        THEN the function call sequence is identical
        AND precompact.py does NOT contain load_settings, update_on_exit, or update_on_clear
        AND precompact.py does NOT extract a reason field from input_data
        """
        precompact_src = PRECOMPACT_SOURCE.read_text()
        session_end_src = SESSION_END_SOURCE.read_text()

        # Verify call sequence match (both files have same order)
        expected_sequence = [
            "extract_cited_ids",
            "run_reflector",
            "apply_bullet_tags",
            "run_curator",
            "apply_structured_operations",
            "run_deduplication",
            "prune_harmful",
            "save_playbook",
            "clear_session",
        ]

        # Check order in precompact source
        prev_pos = 0
        for func in expected_sequence:
            pos = precompact_src.find(func + "(", prev_pos)
            assert pos > prev_pos or prev_pos == 0, \
                f"In precompact.py, {func} should appear after previous function"
            prev_pos = pos

        # Check order in session_end source
        prev_pos = 0
        for func in expected_sequence:
            pos = session_end_src.find(func + "(", prev_pos)
            assert pos > prev_pos or prev_pos == 0, \
                f"In session_end.py, {func} should appear after previous function"
            prev_pos = pos

        # Precompact-specific exclusions
        assert "load_settings" not in precompact_src
        assert "update_on_exit" not in precompact_src
        assert "update_on_clear" not in precompact_src
        # No reason = input_data.get("reason" pattern
        assert 'input_data.get("reason"' not in precompact_src

    def test_invariant_pipeline_function_parity(self):
        """@tests-invariant INV-PRECOMPACT-002

        The set of pipeline functions called by precompact.py between
        load_playbook() and save_playbook() is identical to those called
        by session_end.py in the same span.
        """
        precompact_src = PRECOMPACT_SOURCE.read_text()
        session_end_src = SESSION_END_SOURCE.read_text()

        # Extract function calls between load_playbook and save_playbook
        pipeline_func_pattern = re.compile(
            r"(?:extract_cited_ids|run_reflector|apply_bullet_tags|run_curator|"
            r"apply_structured_operations|run_deduplication|prune_harmful)\("
        )

        def extract_pipeline_calls(source):
            # Find the section between load_playbook and save_playbook
            lb_pos = source.find("load_playbook()")
            sp_pos = source.find("save_playbook(")
            assert lb_pos != -1, "load_playbook() not found"
            assert sp_pos != -1, "save_playbook() not found"
            section = source[lb_pos:sp_pos]
            return [m.group().rstrip("(") for m in pipeline_func_pattern.finditer(section)]

        precompact_calls = extract_pipeline_calls(precompact_src)
        session_end_calls = extract_pipeline_calls(session_end_src)

        assert precompact_calls == session_end_calls, \
            f"Pipeline parity violated:\n  precompact: {precompact_calls}\n  session_end: {session_end_calls}"


# ---------------------------------------------------------------------------
# REQ-PRECOMPACT-006: No Settings Checks
# ---------------------------------------------------------------------------


class TestNoSettingsChecks:
    """@tests REQ-PRECOMPACT-006, SCN-PRECOMPACT-006-01"""

    def test_no_settings_logic(self):
        """@tests REQ-PRECOMPACT-006

        Verify precompact.py does NOT call load_settings(), and does NOT
        contain update_on_exit or update_on_clear conditionals.
        """
        source = PRECOMPACT_SOURCE.read_text()
        assert "load_settings" not in source, "precompact.py must not call load_settings()"
        assert "update_on_exit" not in source, "precompact.py must not check update_on_exit"
        assert "update_on_clear" not in source, "precompact.py must not check update_on_clear"

    def test_scn_no_settings_logic_present(self):
        """@tests SCN-PRECOMPACT-006-01

        GIVEN the upgraded precompact.py source file
        WHEN the source is searched for settings-related code
        THEN the strings load_settings, update_on_exit, and update_on_clear do not appear
        AND the import list does NOT include load_settings
        AND the file does NOT contain the assignment pattern reason = input_data.get("reason"
        """
        source = PRECOMPACT_SOURCE.read_text()
        assert "load_settings" not in source
        assert "update_on_exit" not in source
        assert "update_on_clear" not in source
        # Check for the behavioral pattern of reading a reason field
        assert 'input_data.get("reason"' not in source, \
            "precompact.py must not extract a reason field from input_data"


# ---------------------------------------------------------------------------
# REQ-PRECOMPACT-007: clear_session Called After Save
# ---------------------------------------------------------------------------


class TestClearSessionAfterSave:
    """@tests REQ-PRECOMPACT-007, SCN-PRECOMPACT-007-01"""

    def test_clear_session_after_save(self, monkeypatch):
        """@tests REQ-PRECOMPACT-007

        Verify clear_session() is called after save_playbook().
        """
        call_order = []
        messages = _make_messages()
        playbook = _make_playbook()

        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        monkeypatch.setattr(_precompact_module, "load_transcript", lambda p: messages)
        monkeypatch.setattr(_precompact_module, "load_playbook", lambda: playbook)
        monkeypatch.setattr(_precompact_module, "extract_cited_ids", lambda m: [])

        async def mock_reflector(*a):
            return {"analysis": "", "bullet_tags": []}
        monkeypatch.setattr(_precompact_module, "run_reflector", mock_reflector)
        monkeypatch.setattr(_precompact_module, "apply_bullet_tags", lambda p, bt: p)

        async def mock_curator(*a):
            return {"reasoning": "", "operations": []}
        monkeypatch.setattr(_precompact_module, "run_curator", mock_curator)

        monkeypatch.setattr(_precompact_module, "apply_structured_operations", lambda p, ops: p)
        monkeypatch.setattr(_precompact_module, "run_deduplication", lambda p: p)
        monkeypatch.setattr(_precompact_module, "prune_harmful", lambda p: p)

        def mock_save(p):
            call_order.append("save_playbook")
        monkeypatch.setattr(_precompact_module, "save_playbook", mock_save)

        def mock_clear():
            call_order.append("clear_session")
        monkeypatch.setattr(_precompact_module, "clear_session", mock_clear)

        asyncio.run(_precompact_module.main())

        save_idx = call_order.index("save_playbook")
        clear_idx = call_order.index("clear_session")
        assert save_idx < clear_idx, "clear_session must be called AFTER save_playbook"

    def test_scn_clear_session_called_as_final_step(self, monkeypatch):
        """@tests SCN-PRECOMPACT-007-01

        GIVEN the pipeline has run to completion and save_playbook succeeded
        WHEN the main function reaches its final line
        THEN clear_session() is the last call before the function returns
        AND clear_session is in the import list from common
        """
        call_order = []

        def track(name, return_value=None):
            def fn(*a, **kw):
                call_order.append(name)
                return return_value
            return fn

        messages = _make_messages()
        playbook = _make_playbook()

        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        monkeypatch.setattr(_precompact_module, "load_transcript", lambda p: messages)
        monkeypatch.setattr(_precompact_module, "load_playbook", lambda: playbook)
        monkeypatch.setattr(_precompact_module, "extract_cited_ids", track("extract_cited_ids", []))

        async def mock_reflector(*a):
            call_order.append("run_reflector")
            return {"analysis": "", "bullet_tags": []}
        monkeypatch.setattr(_precompact_module, "run_reflector", mock_reflector)
        monkeypatch.setattr(_precompact_module, "apply_bullet_tags", track("apply_bullet_tags", playbook))

        async def mock_curator(*a):
            call_order.append("run_curator")
            return {"reasoning": "", "operations": []}
        monkeypatch.setattr(_precompact_module, "run_curator", mock_curator)

        monkeypatch.setattr(_precompact_module, "apply_structured_operations", track("apply_structured_operations", playbook))
        monkeypatch.setattr(_precompact_module, "run_deduplication", track("run_deduplication", playbook))
        monkeypatch.setattr(_precompact_module, "prune_harmful", track("prune_harmful", playbook))
        monkeypatch.setattr(_precompact_module, "save_playbook", track("save_playbook"))
        monkeypatch.setattr(_precompact_module, "clear_session", track("clear_session"))

        asyncio.run(_precompact_module.main())

        assert call_order[-1] == "clear_session", \
            f"clear_session must be the last call, but got: {call_order[-1]}"

        # Also verify clear_session is in the import list
        source = PRECOMPACT_SOURCE.read_text()
        assert "clear_session" in source


# ---------------------------------------------------------------------------
# REQ-PRECOMPACT-008: Graceful Error Handling
# ---------------------------------------------------------------------------


class TestGracefulErrorHandling:
    """@tests REQ-PRECOMPACT-008, SCN-PRECOMPACT-008-01, SCN-PRECOMPACT-008-02"""

    def test_error_handling_top_level(self, monkeypatch):
        """@tests REQ-PRECOMPACT-008

        Verify the __main__ block catches exceptions and exits with code 1.
        """
        source = PRECOMPACT_SOURCE.read_text()

        # Verify structural elements exist in source
        assert 'if __name__ == "__main__"' in source
        assert "try:" in source
        assert "except Exception" in source
        assert "traceback.print_exc" in source
        assert "sys.exit(1)" in source

    def test_scn_top_level_exception_handling(self, tmp_path):
        """@tests SCN-PRECOMPACT-008-01

        GIVEN precompact.py is invoked and an unexpected exception occurs
        WHEN the exception propagates to the __main__ block
        THEN the try/except catches it
        AND "Error: <message>" is printed to stderr
        AND a traceback is printed to stderr
        AND the process exits with code 1

        This test runs precompact.py as a subprocess with a wrapper that
        injects a fake 'common' module into sys.modules BEFORE precompact.py
        is loaded via runpy. This ensures precompact.py's 'from common import ...'
        picks up the fake module with a load_playbook that raises. The REAL
        __main__ block's try/except is then exercised -- not a simulated one.
        """
        import subprocess as _sp

        # Write a wrapper script that:
        # 1. Injects a fake 'common' module with load_playbook that raises
        # 2. Provides valid stdin JSON
        # 3. Uses runpy.run_path to execute precompact.py as __main__
        wrapper = tmp_path / "run_failing_precompact.py"
        wrapper.write_text(
            "import sys, io, json, types\n"
            "\n"
            "# Create a fake 'common' module with a load_playbook that raises.\n"
            "# This MUST be inserted into sys.modules BEFORE precompact.py is\n"
            "# loaded, so that 'from common import ...' resolves to our fake.\n"
            "fake_common = types.ModuleType('common')\n"
            "fake_common.load_transcript = lambda p: [{'role': 'user', 'content': 'hi'}]\n"
            "def _boom():\n"
            "    raise RuntimeError('disk full')\n"
            "fake_common.load_playbook = _boom\n"
            "fake_common.save_playbook = lambda p: None\n"
            "fake_common.clear_session = lambda: None\n"
            "fake_common.extract_cited_ids = lambda m: []\n"
            "import asyncio as _asyncio\n"
            "async def _noop_reflector(*a): return {'analysis': '', 'bullet_tags': []}\n"
            "async def _noop_curator(*a): return {'reasoning': '', 'operations': []}\n"
            "fake_common.run_reflector = _noop_reflector\n"
            "fake_common.run_curator = _noop_curator\n"
            "fake_common.apply_bullet_tags = lambda p, bt: p\n"
            "fake_common.apply_structured_operations = lambda p, ops: p\n"
            "fake_common.run_deduplication = lambda p: p\n"
            "fake_common.prune_harmful = lambda p: p\n"
            "sys.modules['common'] = fake_common\n"
            "\n"
            "# Provide valid stdin JSON so json.load succeeds\n"
            "sys.stdin = io.StringIO(json.dumps({'transcript_path': '/fake/path'}))\n"
            "\n"
            "# Run precompact.py as __main__ -- this triggers its if __name__\n"
            "# == '__main__' block with the real try/except handler.\n"
            "import runpy\n"
            "runpy.run_path(\n"
            f"    {str(PRECOMPACT_SOURCE)!r},\n"
            "    run_name='__main__',\n"
            ")\n"
        )

        result = _sp.run(
            [sys.executable, str(wrapper)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 from __main__ error handler, got {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # The __main__ block prints 'Error: <msg>' via print(f"Error: {e}", file=sys.stderr)
        # as a standalone line. Without the handler, only 'RuntimeError: disk full' appears
        # in the traceback. We check for a line starting with 'Error:' (not 'RuntimeError:')
        # to confirm the explicit error message from the handler, not just Python's default
        # unhandled exception output.
        stderr_lines = result.stderr.splitlines()
        has_error_line = any(
            line.strip().startswith("Error:") and "disk full" in line
            for line in stderr_lines
        )
        assert has_error_line, (
            f"Expected a line starting with 'Error:' containing 'disk full' in stderr "
            f"(from the __main__ handler's print statement).\nstderr: {result.stderr}"
        )
        assert "Traceback" in result.stderr, (
            f"Expected traceback in stderr.\nstderr: {result.stderr}"
        )

    def test_scn_llm_call_graceful_degradation(self, monkeypatch):
        """@tests SCN-PRECOMPACT-008-02

        GIVEN run_reflector encounters an LLM API error internally
        WHEN run_reflector handles the error
        THEN it returns an empty/default result
        AND the pipeline continues: apply_bullet_tags receives empty list,
            run_curator receives the empty reflector output
        """
        messages = _make_messages()
        playbook = _make_playbook()

        mocks = _setup_pipeline_mocks(monkeypatch, messages=messages, playbook=playbook)

        # Simulate reflector returning empty result (graceful degradation)
        empty_reflector_output = {"analysis": "", "bullet_tags": []}
        mocks["run_reflector"].return_value = empty_reflector_output

        asyncio.run(_precompact_module.main())

        # apply_bullet_tags should receive empty bullet_tags list
        bt_args = mocks["apply_bullet_tags"].call_args[0]
        assert bt_args[1] == [], "apply_bullet_tags should receive empty bullet_tags"

        # run_curator should still be called with the empty reflector output
        cur_args = mocks["run_curator"].call_args[0]
        assert cur_args[0] is empty_reflector_output, "curator receives the empty reflector output"

        # Pipeline should complete fully (save and clear called)
        mocks["save_playbook"].assert_called_once()
        mocks["clear_session"].assert_called_once()


# ---------------------------------------------------------------------------
# REQ-PRECOMPACT-009: Empty Transcript Early Exit
# ---------------------------------------------------------------------------


class TestEmptyTranscriptEarlyExit:
    """@tests REQ-PRECOMPACT-009, SCN-PRECOMPACT-009-01"""

    def test_empty_transcript_early_exit(self, monkeypatch):
        """@tests REQ-PRECOMPACT-009

        Verify that when load_transcript returns [], sys.exit(0) is called
        and load_playbook is NOT called.
        """
        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        mock_load_transcript = MagicMock(return_value=[])
        monkeypatch.setattr(_precompact_module, "load_transcript", mock_load_transcript)

        mock_load_playbook = MagicMock()
        monkeypatch.setattr(_precompact_module, "load_playbook", mock_load_playbook)

        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(_precompact_module.main())

        assert exc_info.value.code == 0, "Empty transcript should exit with code 0"
        mock_load_playbook.assert_not_called(), "load_playbook must NOT be called when transcript is empty"

    def test_scn_empty_transcript_exits_immediately(self, monkeypatch):
        """@tests SCN-PRECOMPACT-009-01

        GIVEN precompact.py receives stdin JSON with transcript_path
        AND load_transcript returns []
        WHEN the empty check executes
        THEN the process exits with code 0
        AND load_playbook was NOT called
        AND no LLM calls were made
        AND no playbook file was written
        """
        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        mock_lt = MagicMock(return_value=[])
        monkeypatch.setattr(_precompact_module, "load_transcript", mock_lt)

        mock_lp = MagicMock()
        monkeypatch.setattr(_precompact_module, "load_playbook", mock_lp)

        mock_reflector = AsyncMock()
        monkeypatch.setattr(_precompact_module, "run_reflector", mock_reflector)

        mock_curator = AsyncMock()
        monkeypatch.setattr(_precompact_module, "run_curator", mock_curator)

        mock_save = MagicMock()
        monkeypatch.setattr(_precompact_module, "save_playbook", mock_save)

        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(_precompact_module.main())

        assert exc_info.value.code == 0
        mock_lp.assert_not_called()
        mock_reflector.assert_not_called()
        mock_curator.assert_not_called()
        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# INV-PRECOMPACT-003: No Old Pipeline Functions
# ---------------------------------------------------------------------------


class TestNoOldPipelineFunctions:
    """@tests-invariant INV-PRECOMPACT-003"""

    def test_no_old_pipeline_functions(self):
        """@tests-invariant INV-PRECOMPACT-003

        precompact.py NEVER imports or calls extract_keypoints or
        update_playbook_data. These function names do not appear anywhere
        in the file -- not in imports, not in function bodies, not in comments.
        """
        source = PRECOMPACT_SOURCE.read_text()
        assert "extract_keypoints" not in source, \
            "INV-PRECOMPACT-003 violated: extract_keypoints found in precompact.py"
        assert "update_playbook_data" not in source, \
            "INV-PRECOMPACT-003 violated: update_playbook_data found in precompact.py"


# ---------------------------------------------------------------------------
# Full Pipeline Integration (White-Box)
# ---------------------------------------------------------------------------


class TestFullPipelineIntegration:
    """@tests REQ-PRECOMPACT-001, REQ-PRECOMPACT-002, REQ-PRECOMPACT-003, REQ-PRECOMPACT-004, REQ-PRECOMPACT-005, REQ-PRECOMPACT-007"""

    def test_full_pipeline_success(self, monkeypatch):
        """@tests REQ-PRECOMPACT-001, REQ-PRECOMPACT-002, REQ-PRECOMPACT-003, REQ-PRECOMPACT-004, REQ-PRECOMPACT-005, REQ-PRECOMPACT-007

        Full pipeline integration test: verify all functions are called in order
        with correct arguments and the pipeline completes successfully.
        """
        messages = _make_messages(5)
        playbook = _make_playbook()
        playbook["sections"]["PATTERNS & APPROACHES"] = [
            {"name": "pat-001", "text": "Use typing", "helpful": 2, "harmful": 0},
        ]

        mocks = _setup_pipeline_mocks(monkeypatch, messages=messages, playbook=playbook)

        asyncio.run(_precompact_module.main())

        # All pipeline functions called exactly once
        mocks["load_transcript"].assert_called_once()
        mocks["load_playbook"].assert_called_once()
        mocks["extract_cited_ids"].assert_called_once()
        mocks["run_reflector"].assert_called_once()
        mocks["apply_bullet_tags"].assert_called_once()
        mocks["run_curator"].assert_called_once()
        mocks["apply_structured_operations"].assert_called_once()
        mocks["run_deduplication"].assert_called_once()
        mocks["prune_harmful"].assert_called_once()
        mocks["save_playbook"].assert_called_once()
        mocks["clear_session"].assert_called_once()
