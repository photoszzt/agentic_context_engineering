# Spec: docs/hooks/spec.md
# Testing: docs/hooks/testing.md
"""
White-box tests for the subagent_stop pipeline (src/hooks/subagent_stop.py).

Covers the SubagentStop hook behavior:
- Empty transcript early exit
- Settings check (playbook_update_on_subagent_stop)
- Full pipeline execution (no clear_session)
"""

import asyncio
import importlib
import io
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure src/hooks is on sys.path for bare imports like `from common import ...`
_project_root = str(Path(__file__).resolve().parent.parent)
_src_hooks_dir = str(Path(__file__).resolve().parent.parent / "src" / "hooks")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _src_hooks_dir not in sys.path:
    sys.path.insert(0, _src_hooks_dir)

import src.hooks.subagent_stop as _subagent_stop_module

# ---------------------------------------------------------------------------
# Path constants for source inspection
# ---------------------------------------------------------------------------

SUBAGENT_STOP_SOURCE = Path(__file__).resolve().parent.parent / "src" / "hooks" / "subagent_stop.py"
SESSION_END_SOURCE = Path(__file__).resolve().parent.parent / "src" / "hooks" / "session_end.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_playbook():
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
    return json.dumps({"transcript_path": transcript_path})


def _make_messages(count=3):
    msgs = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"Message {i}"})
    return msgs


def _setup_pipeline_mocks(monkeypatch, messages=None, playbook=None, settings=None):
    """Mock all common.py functions used by subagent_stop.py."""
    if messages is None:
        messages = _make_messages()
    if playbook is None:
        playbook = _make_playbook()
    if settings is None:
        settings = {"playbook_update_on_subagent_stop": True}

    monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))

    mock_load_transcript = MagicMock(return_value=messages)
    monkeypatch.setattr(_subagent_stop_module, "load_transcript", mock_load_transcript)

    mock_load_settings = MagicMock(return_value=settings)
    monkeypatch.setattr(_subagent_stop_module, "load_settings", mock_load_settings)

    mock_load_playbook = MagicMock(return_value=playbook)
    monkeypatch.setattr(_subagent_stop_module, "load_playbook", mock_load_playbook)

    mock_save_playbook = MagicMock()
    monkeypatch.setattr(_subagent_stop_module, "save_playbook", mock_save_playbook)

    mock_extract_cited_ids = MagicMock(return_value=["pat-001"])
    monkeypatch.setattr(_subagent_stop_module, "extract_cited_ids", mock_extract_cited_ids)

    mock_run_reflector = AsyncMock(
        return_value={"analysis": "test analysis", "bullet_tags": [{"name": "pat-001", "tag": "helpful"}]}
    )
    monkeypatch.setattr(_subagent_stop_module, "run_reflector", mock_run_reflector)

    mock_apply_bullet_tags = MagicMock(return_value=playbook)
    monkeypatch.setattr(_subagent_stop_module, "apply_bullet_tags", mock_apply_bullet_tags)

    mock_run_curator = AsyncMock(
        return_value={"reasoning": "test reasoning", "operations": [{"type": "ADD", "text": "new bullet", "section": "OTHERS"}]}
    )
    monkeypatch.setattr(_subagent_stop_module, "run_curator", mock_run_curator)

    mock_apply_structured_operations = MagicMock(return_value=playbook)
    monkeypatch.setattr(_subagent_stop_module, "apply_structured_operations", mock_apply_structured_operations)

    mock_run_deduplication = MagicMock(return_value=playbook)
    monkeypatch.setattr(_subagent_stop_module, "run_deduplication", mock_run_deduplication)

    mock_prune_harmful = MagicMock(return_value=playbook)
    monkeypatch.setattr(_subagent_stop_module, "prune_harmful", mock_prune_harmful)

    return {
        "load_transcript": mock_load_transcript,
        "load_settings": mock_load_settings,
        "load_playbook": mock_load_playbook,
        "save_playbook": mock_save_playbook,
        "extract_cited_ids": mock_extract_cited_ids,
        "run_reflector": mock_run_reflector,
        "apply_bullet_tags": mock_apply_bullet_tags,
        "run_curator": mock_run_curator,
        "apply_structured_operations": mock_apply_structured_operations,
        "run_deduplication": mock_run_deduplication,
        "prune_harmful": mock_prune_harmful,
    }


# ---------------------------------------------------------------------------
# Import smoke test
# ---------------------------------------------------------------------------


class TestImportSmoke:
    def test_import_succeeds(self):
        """Verify subagent_stop.py can be imported without errors."""
        try:
            importlib.import_module("src.hooks.subagent_stop")
        except (ImportError, AttributeError) as exc:
            pytest.fail(f"Import of subagent_stop.py failed: {exc}")


# ---------------------------------------------------------------------------
# Source inspection: correct imports, no clear_session, no reason field
# ---------------------------------------------------------------------------


class TestSourceInspection:
    def test_imports_required_functions(self):
        """Verify subagent_stop.py imports all required pipeline functions."""
        source = SUBAGENT_STOP_SOURCE.read_text()
        required = [
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
            "load_settings",
        ]
        for func_name in required:
            assert func_name in source, f"subagent_stop.py must import {func_name}"

    def test_does_not_import_clear_session(self):
        """Verify subagent_stop.py does NOT import or call clear_session."""
        source = SUBAGENT_STOP_SOURCE.read_text()
        assert "clear_session" not in source, (
            "subagent_stop.py must NOT call clear_session "
            "(the main session is still running)"
        )

    def test_no_reason_field(self):
        """Verify subagent_stop.py does NOT extract a reason field from input_data."""
        source = SUBAGENT_STOP_SOURCE.read_text()
        assert 'input_data.get("reason"' not in source, (
            "subagent_stop.py must not extract a reason field (SubagentStop has no reason)"
        )

    def test_checks_playbook_update_on_subagent_stop_setting(self):
        """Verify subagent_stop.py checks the playbook_update_on_subagent_stop setting."""
        source = SUBAGENT_STOP_SOURCE.read_text()
        assert "playbook_update_on_subagent_stop" in source

    def test_error_handling_structure(self):
        """Verify the __main__ block has proper error handling."""
        source = SUBAGENT_STOP_SOURCE.read_text()
        assert 'if __name__ == "__main__"' in source
        assert "try:" in source
        assert "except Exception" in source
        assert "traceback.print_exc" in source
        assert "sys.exit(1)" in source


# ---------------------------------------------------------------------------
# Empty transcript: early exit, no pipeline
# ---------------------------------------------------------------------------


class TestEmptyTranscriptEarlyExit:
    def test_empty_transcript_exits_0(self, monkeypatch):
        """Empty transcript -> sys.exit(0), load_playbook NOT called."""
        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        mock_lt = MagicMock(return_value=[])
        monkeypatch.setattr(_subagent_stop_module, "load_transcript", mock_lt)
        mock_lp = MagicMock()
        monkeypatch.setattr(_subagent_stop_module, "load_playbook", mock_lp)

        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(_subagent_stop_module.main())

        assert exc_info.value.code == 0
        mock_lp.assert_not_called()

    def test_empty_transcript_no_llm_calls(self, monkeypatch):
        """Empty transcript -> no LLM calls, no playbook save."""
        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        monkeypatch.setattr(_subagent_stop_module, "load_transcript", MagicMock(return_value=[]))
        monkeypatch.setattr(_subagent_stop_module, "load_playbook", MagicMock())
        mock_reflector = AsyncMock()
        monkeypatch.setattr(_subagent_stop_module, "run_reflector", mock_reflector)
        mock_curator = AsyncMock()
        monkeypatch.setattr(_subagent_stop_module, "run_curator", mock_curator)
        mock_save = MagicMock()
        monkeypatch.setattr(_subagent_stop_module, "save_playbook", mock_save)

        with pytest.raises(SystemExit):
            asyncio.run(_subagent_stop_module.main())

        mock_reflector.assert_not_called()
        mock_curator.assert_not_called()
        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Settings check: playbook_update_on_subagent_stop = false -> early exit
# ---------------------------------------------------------------------------


class TestSettingsCheck:
    def test_disabled_setting_exits_0(self, monkeypatch):
        """playbook_update_on_subagent_stop=false -> sys.exit(0), no pipeline."""
        settings = {"playbook_update_on_subagent_stop": False}
        mocks = _setup_pipeline_mocks(monkeypatch, settings=settings)

        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(_subagent_stop_module.main())

        assert exc_info.value.code == 0
        mocks["load_playbook"].assert_not_called()
        mocks["run_reflector"].assert_not_called()
        mocks["save_playbook"].assert_not_called()

    def test_enabled_setting_runs_pipeline(self, monkeypatch):
        """playbook_update_on_subagent_stop=true (default) -> full pipeline runs."""
        settings = {"playbook_update_on_subagent_stop": True}
        mocks = _setup_pipeline_mocks(monkeypatch, settings=settings)

        asyncio.run(_subagent_stop_module.main())

        mocks["load_playbook"].assert_called_once()
        mocks["run_reflector"].assert_called_once()
        mocks["save_playbook"].assert_called_once()

    def test_missing_setting_defaults_to_true(self, monkeypatch):
        """Missing playbook_update_on_subagent_stop key defaults to True -> pipeline runs."""
        settings = {}  # key absent
        mocks = _setup_pipeline_mocks(monkeypatch, settings=settings)

        asyncio.run(_subagent_stop_module.main())

        mocks["save_playbook"].assert_called_once()


# ---------------------------------------------------------------------------
# Pipeline call order
# ---------------------------------------------------------------------------


class TestPipelineCallOrder:
    def test_pipeline_call_order(self, monkeypatch):
        """Verify pipeline functions are called in the correct order."""
        call_order = []
        messages = _make_messages()
        playbook = _make_playbook()

        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        monkeypatch.setattr(_subagent_stop_module, "load_transcript", lambda p: messages)
        monkeypatch.setattr(_subagent_stop_module, "load_settings", lambda: {"playbook_update_on_subagent_stop": True})
        monkeypatch.setattr(_subagent_stop_module, "load_playbook", lambda: playbook)

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

        monkeypatch.setattr(_subagent_stop_module, "extract_cited_ids", track("extract_cited_ids", []))
        monkeypatch.setattr(_subagent_stop_module, "run_reflector", track("run_reflector", reflector_output, is_async=True))
        monkeypatch.setattr(_subagent_stop_module, "apply_bullet_tags", track("apply_bullet_tags", playbook))
        monkeypatch.setattr(_subagent_stop_module, "run_curator", track("run_curator", curator_output, is_async=True))
        monkeypatch.setattr(_subagent_stop_module, "apply_structured_operations", track("apply_structured_operations", playbook))
        monkeypatch.setattr(_subagent_stop_module, "run_deduplication", track("run_deduplication", playbook))
        monkeypatch.setattr(_subagent_stop_module, "prune_harmful", track("prune_harmful", playbook))
        monkeypatch.setattr(_subagent_stop_module, "save_playbook", track("save_playbook"))

        asyncio.run(_subagent_stop_module.main())

        expected_order = [
            "extract_cited_ids",
            "run_reflector",
            "apply_bullet_tags",
            "run_curator",
            "apply_structured_operations",
            "run_deduplication",
            "prune_harmful",
            "save_playbook",
        ]
        assert call_order == expected_order, f"Expected {expected_order}, got {call_order}"

    def test_clear_session_not_called(self, monkeypatch):
        """Verify clear_session is NOT called (main session still running)."""
        call_order = []
        messages = _make_messages()
        playbook = _make_playbook()

        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        monkeypatch.setattr(_subagent_stop_module, "load_transcript", lambda p: messages)
        monkeypatch.setattr(_subagent_stop_module, "load_settings", lambda: {"playbook_update_on_subagent_stop": True})
        monkeypatch.setattr(_subagent_stop_module, "load_playbook", lambda: playbook)
        monkeypatch.setattr(_subagent_stop_module, "extract_cited_ids", lambda m: [])

        async def mock_reflector(*a):
            return {"analysis": "", "bullet_tags": []}
        monkeypatch.setattr(_subagent_stop_module, "run_reflector", mock_reflector)
        monkeypatch.setattr(_subagent_stop_module, "apply_bullet_tags", lambda p, bt: p)

        async def mock_curator(*a):
            return {"reasoning": "", "operations": []}
        monkeypatch.setattr(_subagent_stop_module, "run_curator", mock_curator)

        monkeypatch.setattr(_subagent_stop_module, "apply_structured_operations", lambda p, ops: p)
        monkeypatch.setattr(_subagent_stop_module, "run_deduplication", lambda p: p)
        monkeypatch.setattr(_subagent_stop_module, "prune_harmful", lambda p: p)

        def mock_save(p):
            call_order.append("save_playbook")
        monkeypatch.setattr(_subagent_stop_module, "save_playbook", mock_save)

        asyncio.run(_subagent_stop_module.main())

        assert "save_playbook" in call_order, "save_playbook must be called"
        assert "clear_session" not in call_order, "clear_session must NOT be called"


# ---------------------------------------------------------------------------
# Full pipeline integration
# ---------------------------------------------------------------------------


class TestFullPipelineIntegration:
    def test_full_pipeline_success(self, monkeypatch):
        """Full pipeline integration: all functions called exactly once."""
        messages = _make_messages(5)
        playbook = _make_playbook()
        mocks = _setup_pipeline_mocks(monkeypatch, messages=messages, playbook=playbook)

        asyncio.run(_subagent_stop_module.main())

        mocks["load_transcript"].assert_called_once()
        mocks["load_settings"].assert_called_once()
        mocks["load_playbook"].assert_called_once()
        mocks["extract_cited_ids"].assert_called_once()
        mocks["run_reflector"].assert_called_once()
        mocks["apply_bullet_tags"].assert_called_once()
        mocks["run_curator"].assert_called_once()
        mocks["apply_structured_operations"].assert_called_once()
        mocks["run_deduplication"].assert_called_once()
        mocks["prune_harmful"].assert_called_once()
        mocks["save_playbook"].assert_called_once()

    def test_async_functions_are_awaited(self, monkeypatch):
        """Verify run_reflector and run_curator are awaited."""
        mocks = _setup_pipeline_mocks(monkeypatch)
        asyncio.run(_subagent_stop_module.main())
        assert mocks["run_reflector"].await_count == 1
        assert mocks["run_curator"].await_count == 1

    def test_save_is_last_call(self, monkeypatch):
        """Verify save_playbook is the final call in the pipeline."""
        call_order = []
        messages = _make_messages()
        playbook = _make_playbook()

        monkeypatch.setattr("sys.stdin", io.StringIO(_make_stdin_json()))
        monkeypatch.setattr(_subagent_stop_module, "load_transcript", lambda p: messages)
        monkeypatch.setattr(_subagent_stop_module, "load_settings", lambda: {"playbook_update_on_subagent_stop": True})
        monkeypatch.setattr(_subagent_stop_module, "load_playbook", lambda: playbook)
        monkeypatch.setattr(_subagent_stop_module, "extract_cited_ids", lambda m: [])

        async def mock_reflector(*a):
            call_order.append("run_reflector")
            return {"analysis": "", "bullet_tags": []}
        monkeypatch.setattr(_subagent_stop_module, "run_reflector", mock_reflector)
        monkeypatch.setattr(_subagent_stop_module, "apply_bullet_tags", lambda p, bt: (call_order.append("apply_bullet_tags") or p))

        async def mock_curator(*a):
            call_order.append("run_curator")
            return {"reasoning": "", "operations": []}
        monkeypatch.setattr(_subagent_stop_module, "run_curator", mock_curator)

        def track(name):
            def fn(*a):
                call_order.append(name)
                return playbook
            return fn

        monkeypatch.setattr(_subagent_stop_module, "apply_structured_operations", track("apply_structured_operations"))
        monkeypatch.setattr(_subagent_stop_module, "run_deduplication", track("run_deduplication"))
        monkeypatch.setattr(_subagent_stop_module, "prune_harmful", track("prune_harmful"))
        monkeypatch.setattr(_subagent_stop_module, "save_playbook", track("save_playbook"))

        asyncio.run(_subagent_stop_module.main())

        assert call_order[-1] == "save_playbook", (
            f"save_playbook must be the last call, got: {call_order[-1]}"
        )
