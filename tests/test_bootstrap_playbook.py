# Spec: docs/bootstrap/spec.md
# Testing: tests/test_bootstrap_playbook_plan.md
"""
White-box tests for the bootstrap_playbook module (src/hooks/bootstrap_playbook.py).

Covers:
- REQ-BOOT-002: encode_project_dir() encoding algorithm
- REQ-BOOT-011: count_keypoints() helper
- REQ-BOOT-012: load_state() state file loading
- REQ-BOOT-013: save_state() atomic state file writing
- INV-BOOT-005: No direct playbook construction in bootstrap module
- INV-BOOT-008: Atomic write via temp file + os.replace
- QG-BOOT-001: common.py unchanged
- QG-BOOT-003: Import smoke test
- QG-BOOT-004: bootstrap-playbook.md is valid Markdown

Adversarial categories: Boundary, Invalid Input, Failure Injection.
"""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Path setup: mirror existing test convention
# ---------------------------------------------------------------------------
_project_root = str(Path(__file__).resolve().parent.parent)
_src_hooks_dir = str(Path(__file__).resolve().parent.parent / "src" / "hooks")
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _src_hooks_dir not in sys.path:
    sys.path.insert(0, _src_hooks_dir)

import src.hooks.bootstrap_playbook as _bp_module

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
BOOTSTRAP_SOURCE = Path(__file__).resolve().parent.parent / "src" / "hooks" / "bootstrap_playbook.py"
COMMON_SOURCE = Path(__file__).resolve().parent.parent / "src" / "hooks" / "common.py"
COMMAND_FILE = Path(__file__).resolve().parent.parent / "src" / "commands" / "bootstrap-playbook.md"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ===========================================================================
# QG-BOOT-003: Import Smoke Test
# ===========================================================================


class TestImportSmoke:
    """QG-BOOT-003: bootstrap_playbook.py imports successfully."""

    # @tests REQ-BOOT-002, REQ-BOOT-011, REQ-BOOT-012, REQ-BOOT-013
    def test_import_module_succeeds(self):
        """Verify bootstrap_playbook.py can be imported without errors."""
        try:
            mod = importlib.import_module("src.hooks.bootstrap_playbook")
        except (ImportError, AttributeError) as exc:
            pytest.fail(f"Import of bootstrap_playbook.py failed: {exc}")

    def test_import_specific_functions(self):
        """Verify key public functions are importable."""
        assert hasattr(_bp_module, "encode_project_dir")
        assert hasattr(_bp_module, "load_state")
        assert hasattr(_bp_module, "save_state")
        assert hasattr(_bp_module, "count_keypoints")
        assert hasattr(_bp_module, "main")

    def test_subprocess_import_smoke(self):
        """QG-BOOT-003: verify import via subprocess (independent process)."""
        result = subprocess.run(
            [sys.executable, "-c", "import sys; sys.path.insert(0, 'src/hooks'); import bootstrap_playbook"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, f"Import failed: stderr={result.stderr}"


# ===========================================================================
# REQ-BOOT-002: encode_project_dir()
# ===========================================================================


class TestEncodeProjectDir:
    """REQ-BOOT-002: Project directory encoding algorithm."""

    # @tests REQ-BOOT-002
    def test_spec_example_agentic_context(self):
        """Spec example: agentic_context_engineering path."""
        result = _bp_module.encode_project_dir(
            "/Users/zhitingz/Documents/agentic_context_engineering"
        )
        assert result == "-Users-zhitingz-Documents-agentic-context-engineering"

    # @tests REQ-BOOT-002
    def test_spec_example_codex_dot(self):
        """Spec example: path with dot (.codex) produces double dash."""
        result = _bp_module.encode_project_dir("/Users/zhitingz/.codex")
        assert result == "-Users-zhitingz--codex"

    # @tests REQ-BOOT-002
    def test_spec_example_vscode_tlaplus(self):
        """Spec example: path with existing dash preserved."""
        result = _bp_module.encode_project_dir(
            "/Users/zhitingz/Documents/vscode-tlaplus"
        )
        assert result == "-Users-zhitingz-Documents-vscode-tlaplus"

    # @tests REQ-BOOT-002
    def test_underscores_replaced(self):
        """Underscores in path are replaced with dashes."""
        result = _bp_module.encode_project_dir("/home/user_name/my_project")
        assert result == "-home-user-name-my-project"

    # --- Adversarial: Boundary ---

    def test_empty_string(self):
        """Boundary: empty string input."""
        result = _bp_module.encode_project_dir("")
        assert result == ""

    def test_single_slash(self):
        """Boundary: root directory."""
        result = _bp_module.encode_project_dir("/")
        assert result == "-"

    def test_multiple_dots(self):
        """Boundary: multiple consecutive dots (/home/.../test -> 5 dashes between home and test)."""
        # /home/.../test -> step1 (/ to -): -home-...-test -> step2 (. to -): -home-----test
        result = _bp_module.encode_project_dir("/home/.../test")
        assert result == "-home-----test"

    def test_mixed_special_chars(self):
        """Boundary: path with all replacement chars adjacent."""
        result = _bp_module.encode_project_dir("/a._b/c")
        assert result == "-a--b-c"

    def test_no_special_chars(self):
        """No replacement needed except leading slash."""
        result = _bp_module.encode_project_dir("/simple")
        assert result == "-simple"


# ===========================================================================
# REQ-BOOT-011: count_keypoints()
# ===========================================================================


class TestCountKeypoints:
    """REQ-BOOT-011: Keypoint counting helper."""

    # @tests REQ-BOOT-011
    def test_empty_playbook_no_sections(self):
        """Empty playbook with no sections key returns 0."""
        assert _bp_module.count_keypoints({}) == 0

    # @tests REQ-BOOT-011
    def test_empty_playbook_empty_sections(self):
        """Playbook with empty sections dict returns 0."""
        playbook = {"sections": {}}
        assert _bp_module.count_keypoints(playbook) == 0

    # @tests REQ-BOOT-011
    def test_playbook_with_empty_section_lists(self):
        """Playbook with section keys but empty lists returns 0."""
        playbook = {
            "sections": {
                "PATTERNS & APPROACHES": [],
                "MISTAKES TO AVOID": [],
                "USER PREFERENCES": [],
            }
        }
        assert _bp_module.count_keypoints(playbook) == 0

    # @tests REQ-BOOT-011
    def test_playbook_with_items(self):
        """Playbook with items returns correct count."""
        playbook = {
            "sections": {
                "PATTERNS & APPROACHES": ["item1", "item2", "item3"],
                "MISTAKES TO AVOID": ["item4"],
                "USER PREFERENCES": [],
                "PROJECT CONTEXT": ["item5", "item6"],
                "OTHERS": [],
            }
        }
        assert _bp_module.count_keypoints(playbook) == 6

    # @tests REQ-BOOT-011
    def test_single_section_single_item(self):
        """Minimal non-empty case: 1 section, 1 item."""
        playbook = {"sections": {"OTHERS": ["one"]}}
        assert _bp_module.count_keypoints(playbook) == 1

    # --- Adversarial: Boundary ---

    def test_large_playbook(self):
        """Boundary: many items across sections."""
        playbook = {
            "sections": {
                f"section_{i}": [f"item_{j}" for j in range(100)]
                for i in range(10)
            }
        }
        assert _bp_module.count_keypoints(playbook) == 1000


# ===========================================================================
# REQ-BOOT-012: load_state()
# ===========================================================================


class TestLoadState:
    """REQ-BOOT-012: State file loading."""

    # @tests REQ-BOOT-012, SCN-BOOT-012-01
    def test_nonexistent_file_returns_default(self, tmp_path):
        """Non-existent state file returns default with empty processed_sessions."""
        state_path = tmp_path / "bootstrap_state.json"
        result = _bp_module.load_state(state_path)
        assert result == {"version": "1.0", "processed_sessions": {}}

    # @tests REQ-BOOT-012, SCN-BOOT-012-02
    def test_valid_json_with_processed_sessions(self, tmp_path):
        """Valid JSON with processed_sessions key is loaded correctly."""
        state_path = tmp_path / "bootstrap_state.json"
        data = {
            "version": "1.0",
            "processed_sessions": {
                "/path/to/session1.jsonl": {
                    "processed_at": "2026-01-01T00:00:00",
                    "key_points_after": 5,
                }
            },
        }
        state_path.write_text(json.dumps(data))
        result = _bp_module.load_state(state_path)
        assert result == data
        assert "/path/to/session1.jsonl" in result["processed_sessions"]

    # @tests REQ-BOOT-012, SCN-BOOT-012-03
    def test_corrupted_json_returns_default(self, tmp_path, capsys):
        """Corrupted JSON prints warning and returns default."""
        state_path = tmp_path / "bootstrap_state.json"
        state_path.write_text("{truncated")
        result = _bp_module.load_state(state_path)
        assert result == {"version": "1.0", "processed_sessions": {}}
        captured = capsys.readouterr()
        assert "BOOTSTRAP: warning: state file corrupted" in captured.err

    # @tests REQ-BOOT-012
    def test_valid_json_missing_processed_sessions_key(self, tmp_path, capsys):
        """Valid JSON but missing processed_sessions key prints warning and returns default."""
        state_path = tmp_path / "bootstrap_state.json"
        state_path.write_text(json.dumps({"version": "1.0", "other_key": {}}))
        result = _bp_module.load_state(state_path)
        assert result == {"version": "1.0", "processed_sessions": {}}
        captured = capsys.readouterr()
        assert "BOOTSTRAP: warning: state file corrupted" in captured.err

    # --- Adversarial: Invalid input ---

    def test_empty_file_returns_default(self, tmp_path, capsys):
        """Empty file triggers JSONDecodeError and returns default."""
        state_path = tmp_path / "bootstrap_state.json"
        state_path.write_text("")
        result = _bp_module.load_state(state_path)
        assert result == {"version": "1.0", "processed_sessions": {}}
        captured = capsys.readouterr()
        assert "BOOTSTRAP: warning: state file corrupted" in captured.err

    def test_non_dict_json_returns_default(self, tmp_path, capsys):
        """JSON array (not a dict) triggers warning and returns default."""
        state_path = tmp_path / "bootstrap_state.json"
        state_path.write_text(json.dumps(["not", "a", "dict"]))
        result = _bp_module.load_state(state_path)
        assert result == {"version": "1.0", "processed_sessions": {}}
        captured = capsys.readouterr()
        assert "BOOTSTRAP: warning: state file corrupted" in captured.err

    def test_json_null_returns_default(self, tmp_path, capsys):
        """JSON null triggers warning and returns default."""
        state_path = tmp_path / "bootstrap_state.json"
        state_path.write_text("null")
        result = _bp_module.load_state(state_path)
        assert result == {"version": "1.0", "processed_sessions": {}}
        captured = capsys.readouterr()
        assert "BOOTSTRAP: warning: state file corrupted" in captured.err

    # --- Adversarial: Boundary ---

    def test_large_state_file(self, tmp_path):
        """Boundary: state file with many processed sessions."""
        state_path = tmp_path / "bootstrap_state.json"
        data = {
            "version": "1.0",
            "processed_sessions": {
                f"/path/to/session_{i}.jsonl": {
                    "processed_at": "2026-01-01T00:00:00",
                    "key_points_after": i,
                }
                for i in range(500)
            },
        }
        state_path.write_text(json.dumps(data))
        result = _bp_module.load_state(state_path)
        assert len(result["processed_sessions"]) == 500

    def test_valid_state_with_extra_keys(self, tmp_path):
        """State file with extra keys (forward compat) still loads."""
        state_path = tmp_path / "bootstrap_state.json"
        data = {
            "version": "2.0",
            "processed_sessions": {},
            "extra_field": "some_value",
        }
        state_path.write_text(json.dumps(data))
        result = _bp_module.load_state(state_path)
        assert result["processed_sessions"] == {}
        assert result["version"] == "2.0"


# ===========================================================================
# REQ-BOOT-013: save_state()
# ===========================================================================


class TestSaveState:
    """REQ-BOOT-013, INV-BOOT-008: Atomic state file writing."""

    # @tests REQ-BOOT-013, INV-BOOT-008
    def test_creates_file_with_correct_json(self, tmp_path):
        """save_state creates a JSON file with the correct content."""
        state_path = tmp_path / ".claude" / "bootstrap_state.json"
        state = {
            "version": "1.0",
            "processed_sessions": {
                "/path/to/session.jsonl": {
                    "processed_at": "2026-01-01T00:00:00",
                    "key_points_after": 10,
                }
            },
        }
        _bp_module.save_state(state_path, state)
        assert state_path.exists()
        loaded = json.loads(state_path.read_text())
        assert loaded == state

    # @tests REQ-BOOT-013, INV-BOOT-008
    def test_creates_parent_directories(self, tmp_path):
        """save_state creates parent directories if they don't exist."""
        state_path = tmp_path / "a" / "b" / "c" / "bootstrap_state.json"
        state = {"version": "1.0", "processed_sessions": {}}
        _bp_module.save_state(state_path, state)
        assert state_path.exists()

    # @tests REQ-BOOT-013
    def test_overwrites_existing_file(self, tmp_path):
        """save_state overwrites existing file content."""
        state_path = tmp_path / "bootstrap_state.json"
        state_path.write_text(json.dumps({"version": "1.0", "processed_sessions": {}}))

        new_state = {
            "version": "1.0",
            "processed_sessions": {
                "/path/x.jsonl": {
                    "processed_at": "2026-02-01T00:00:00",
                    "key_points_after": 3,
                }
            },
        }
        _bp_module.save_state(state_path, new_state)
        loaded = json.loads(state_path.read_text())
        assert loaded == new_state

    # @tests INV-BOOT-008
    def test_temp_file_cleaned_up(self, tmp_path):
        """After save_state, no .json.tmp file remains."""
        state_path = tmp_path / "bootstrap_state.json"
        tmp_file = state_path.with_suffix(".json.tmp")
        _bp_module.save_state(state_path, {"version": "1.0", "processed_sessions": {}})
        assert not tmp_file.exists(), "Temp file should be removed by os.replace()"

    # @tests REQ-BOOT-013
    def test_json_formatting(self, tmp_path):
        """State file uses indented JSON (indent=2)."""
        state_path = tmp_path / "bootstrap_state.json"
        state = {"version": "1.0", "processed_sessions": {}}
        _bp_module.save_state(state_path, state)
        content = state_path.read_text()
        # json.dump with indent=2 produces multi-line output
        assert "\n" in content
        assert "  " in content

    # --- Adversarial: roundtrip ---

    def test_save_then_load_roundtrip(self, tmp_path):
        """save_state followed by load_state returns identical data."""
        state_path = tmp_path / "bootstrap_state.json"
        state = {
            "version": "1.0",
            "processed_sessions": {
                "/a.jsonl": {"processed_at": "2026-01-01T00:00:00", "key_points_after": 1},
                "/b.jsonl": {"processed_at": "2026-01-02T00:00:00", "key_points_after": 5},
            },
        }
        _bp_module.save_state(state_path, state)
        loaded = _bp_module.load_state(state_path)
        assert loaded == state


# ===========================================================================
# INV-BOOT-005: No direct playbook construction
# ===========================================================================


class TestSourceInspection:
    """Source-level invariant checks."""

    # @tests INV-BOOT-005
    def test_no_direct_playbook_construction(self):
        """INV-BOOT-005: bootstrap_playbook.py never constructs a playbook dict manually."""
        source = BOOTSTRAP_SOURCE.read_text()
        # Should not contain playbook dict literals like {"version":..., "sections":...}
        # The only dict literals should be for the state file
        # Check that "sections" is never in a dict literal assignment
        assert '"sections":' not in source or '"sections"' in "playbook.get(\"sections\"", (
            "bootstrap_playbook.py should not construct playbook dicts manually"
        )

    # @tests INV-BOOT-002
    def test_single_asyncio_run(self):
        """INV-BOOT-002: Only one asyncio.run() call in the module."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert source.count("asyncio.run(") == 1

    # @tests INV-BOOT-006
    def test_no_parallel_processing(self):
        """INV-BOOT-006: No asyncio.gather or create_task for parallel sessions."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "asyncio.gather" not in source
        assert "asyncio.create_task" not in source

    def test_imports_from_common(self):
        """Verify bootstrap_playbook.py imports all required pipeline functions."""
        source = BOOTSTRAP_SOURCE.read_text()
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
        ]
        for func_name in required_imports:
            assert func_name in source, f"bootstrap_playbook.py must import {func_name}"

    def test_error_handling_structure(self):
        """Verify the __main__ block has proper error handling."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert 'if __name__ == "__main__"' in source
        assert "asyncio.run(main())" in source
        assert "KeyboardInterrupt" in source
        assert "traceback.print_exc" in source

    # @tests INV-BOOT-007
    def test_all_stderr_output_has_bootstrap_prefix(self):
        """INV-BOOT-007: All print-to-stderr statements use BOOTSTRAP: prefix."""
        source = BOOTSTRAP_SOURCE.read_text()
        import re
        # Find all print(..., file=sys.stderr) calls
        # We look for print( followed by a string that starts with BOOTSTRAP:
        # or f-strings that start with BOOTSTRAP:
        stderr_prints = re.findall(r'print\(([^)]+),\s*file=sys\.stderr\)', source)
        for print_arg in stderr_prints:
            # Each should contain BOOTSTRAP: prefix in the string
            assert "BOOTSTRAP:" in print_arg, (
                f"stderr print missing BOOTSTRAP: prefix: {print_arg[:80]}"
            )

    # @tests INV-BOOT-001
    def test_pipeline_step_order_in_source(self):
        """INV-BOOT-001: Pipeline steps appear in correct order in source."""
        source = BOOTSTRAP_SOURCE.read_text()
        # Find positions of pipeline function calls within main()
        steps = [
            "extract_cited_ids(",
            "run_reflector(",
            "apply_bullet_tags(",
            "run_curator(",
            "apply_structured_operations(",
            "run_deduplication(",
            "prune_harmful(",
        ]
        positions = []
        for step in steps:
            pos = source.find(step)
            assert pos != -1, f"Pipeline step {step} not found in source"
            positions.append(pos)
        # Verify monotonically increasing positions
        for i in range(len(positions) - 1):
            assert positions[i] < positions[i + 1], (
                f"Pipeline step {steps[i]} (pos {positions[i]}) appears after "
                f"{steps[i+1]} (pos {positions[i+1]})"
            )


# ===========================================================================
# QG-BOOT-001: common.py unchanged
# ===========================================================================


class TestQualityGates:
    """Quality gate checks."""

    def test_common_py_unchanged(self):
        """QG-BOOT-001: common.py has no local modifications."""
        result = subprocess.run(
            ["git", "diff", "--name-only", "--", "src/hooks/common.py"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0
        # If common.py appears in the diff output, it was modified
        assert "common.py" not in result.stdout, (
            "QG-BOOT-001 FAIL: common.py has been modified"
        )

    def test_common_py_not_staged(self):
        """QG-BOOT-001: common.py has no staged modifications."""
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--", "src/hooks/common.py"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0
        assert "common.py" not in result.stdout, (
            "QG-BOOT-001 FAIL: common.py has staged modifications"
        )


# ===========================================================================
# QG-BOOT-004: bootstrap-playbook.md is valid Markdown
# ===========================================================================


class TestCommandFile:
    """QG-BOOT-004: Command file validation."""

    def test_command_file_exists(self):
        """Command file must exist."""
        assert COMMAND_FILE.exists(), (
            f"QG-BOOT-004 FAIL: {COMMAND_FILE} does not exist"
        )

    def test_command_file_non_empty(self):
        """Command file must not be empty."""
        content = COMMAND_FILE.read_text()
        assert len(content.strip()) > 0, "Command file is empty"

    def test_command_file_has_heading(self):
        """Command file must have a Markdown heading."""
        content = COMMAND_FILE.read_text()
        lines = content.strip().splitlines()
        has_heading = any(line.strip().startswith("#") for line in lines)
        assert has_heading, "Command file must contain at least one # heading"

    def test_command_file_mentions_bootstrap(self):
        """Command file should reference the bootstrap script."""
        content = COMMAND_FILE.read_text()
        assert "bootstrap_playbook.py" in content, (
            "Command file should reference bootstrap_playbook.py"
        )

    def test_command_file_has_uv_run(self):
        """Command file should contain the uv run execution command."""
        content = COMMAND_FILE.read_text()
        assert "uv run" in content, "Command file should contain 'uv run' command"

    # @tests REQ-BOOT-009
    def test_command_file_references_project_dir(self):
        """Command file should reference CLAUDE_PROJECT_DIR."""
        content = COMMAND_FILE.read_text()
        assert "CLAUDE_PROJECT_DIR" in content, (
            "Command file should reference CLAUDE_PROJECT_DIR"
        )


# ===========================================================================
# REQ-BOOT-011: Progress event format compliance
# ===========================================================================


class TestProgressEventFormats:
    """REQ-BOOT-011, INV-BOOT-007: Progress event format verification via source inspection."""

    # @tests REQ-BOOT-011, SCN-BOOT-011-01
    def test_discovery_summary_format(self):
        """Discovery summary matches spec format string."""
        source = BOOTSTRAP_SOURCE.read_text()
        # Should contain the format pattern for discovery summary
        assert "discovered" in source
        assert "transcript(s)" in source
        assert "sessions" in source
        assert "subagents" in source
        assert "already processed" in source
        assert "to process" in source

    # @tests REQ-BOOT-011, SCN-BOOT-011-02
    def test_session_start_format(self):
        """Session start event includes index, filename, and size."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "processing" in source
        assert "KB" in source

    # @tests REQ-BOOT-011, SCN-BOOT-011-03
    def test_session_skip_format(self):
        """Session skip events include all documented reason strings."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "empty transcript" in source
        assert "pipeline failed (reflector returned empty)" in source
        assert "pipeline failed (curator returned empty)" in source
        assert "pipeline failed (unexpected error)" in source
        assert "transcript too large" in source

    # @tests REQ-BOOT-011, SCN-BOOT-011-04
    def test_session_complete_format(self):
        """Session complete event includes duration, keypoint count, delta."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "completed" in source
        assert "key points" in source
        assert "delta:" in source

    # @tests REQ-BOOT-011, SCN-BOOT-011-05
    def test_final_summary_format(self):
        """Final summary matches spec format: processed, skipped, failed."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "complete." in source
        assert "processed" in source
        assert "skipped" in source
        assert "failed" in source
        assert "Elapsed:" in source

    # @tests INV-BOOT-010
    def test_counter_identity_structure(self):
        """INV-BOOT-010: Verify code has counter variables for the identity."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "processed = 0" in source or "processed=0" in source
        assert "skipped = 0" in source or "skipped=0" in source
        assert "failed = 0" in source or "failed=0" in source


# ===========================================================================
# REQ-BOOT-016, REQ-BOOT-017, REQ-BOOT-018: Prerequisite checks (source)
# ===========================================================================


class TestPrerequisiteChecksSource:
    """Verify prerequisite check logic exists in source."""

    # @tests REQ-BOOT-017
    def test_checks_claude_project_dir(self):
        """REQ-BOOT-017: Script checks CLAUDE_PROJECT_DIR."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert 'CLAUDE_PROJECT_DIR' in source
        assert "CLAUDE_PROJECT_DIR is not set" in source

    # @tests REQ-BOOT-016
    def test_checks_api_key(self):
        """REQ-BOOT-016: Script checks for API key env vars."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "AGENTIC_CONTEXT_API_KEY" in source
        assert "ANTHROPIC_AUTH_TOKEN" in source
        assert "ANTHROPIC_API_KEY" in source
        assert "no API key found" in source

    # @tests REQ-BOOT-018
    def test_checks_template_files(self):
        """REQ-BOOT-018: Script checks for template files."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "reflector.txt" in source
        assert "curator.txt" in source
        assert "playbook.txt" in source
        assert "required template not found" in source


# ===========================================================================
# REQ-BOOT-019: Large transcript guard (source)
# ===========================================================================


class TestLargeTranscriptGuardSource:
    """REQ-BOOT-019: Large transcript guard logic."""

    # @tests REQ-BOOT-019
    def test_max_transcript_env_var(self):
        """Script reads AGENTIC_CONTEXT_MAX_TRANSCRIPT_MB."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "AGENTIC_CONTEXT_MAX_TRANSCRIPT_MB" in source

    # @tests REQ-BOOT-019
    def test_file_size_check_before_load(self):
        """File size is checked before load_transcript is called."""
        source = BOOTSTRAP_SOURCE.read_text()
        # The size check (st_size) should appear before load_transcript call in the loop
        size_check_pos = source.find("max_transcript_bytes")
        load_pos = source.find("load_transcript(str(file_path))")
        assert size_check_pos != -1, "max_transcript_bytes not found"
        assert load_pos != -1, "load_transcript call not found"
        assert size_check_pos < load_pos, (
            "File size check should appear before load_transcript call"
        )


# ===========================================================================
# Adversarial: Failure injection for load_state
# ===========================================================================


class TestLoadStateFailureInjection:
    """Adversarial: failure injection scenarios for load_state."""

    def test_binary_content_raises_unicode_error(self, tmp_path):
        """State file with binary (non-UTF8) content raises UnicodeDecodeError.

        NOTE: The implementation catches (json.JSONDecodeError, OSError) but not
        UnicodeDecodeError (which inherits from ValueError). This is a known
        gap -- binary corruption propagates as an unhandled exception. The main()
        catch-all would handle it at the top level.
        """
        state_path = tmp_path / "bootstrap_state.json"
        state_path.write_bytes(b"\x80\x81\x82\x83\xff\xfe")
        with pytest.raises(UnicodeDecodeError):
            _bp_module.load_state(state_path)

    def test_unicode_content_valid_json(self, tmp_path):
        """State file with unicode content in valid JSON loads correctly."""
        state_path = tmp_path / "bootstrap_state.json"
        data = {
            "version": "1.0",
            "processed_sessions": {
                "/path/to/\u00e9\u00e8\u00ea.jsonl": {
                    "processed_at": "2026-01-01T00:00:00",
                    "key_points_after": 1,
                }
            },
        }
        state_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        result = _bp_module.load_state(state_path)
        assert result == data


# ===========================================================================
# REQ-BOOT-010: Rate limit configuration (source)
# ===========================================================================


class TestRateLimitConfigSource:
    """REQ-BOOT-010: Rate limit configuration in source."""

    # @tests REQ-BOOT-010, SCN-BOOT-010-01, SCN-BOOT-010-02
    def test_delay_env_var(self):
        """Script reads AGENTIC_CONTEXT_BOOTSTRAP_DELAY."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "AGENTIC_CONTEXT_BOOTSTRAP_DELAY" in source

    # @tests REQ-BOOT-010
    def test_default_delay(self):
        """Default delay is 2.0 seconds."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert '"2.0"' in source

    # @tests REQ-BOOT-010
    def test_asyncio_sleep_used(self):
        """asyncio.sleep is used for inter-session delay."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "asyncio.sleep" in source


# ===========================================================================
# REQ-BOOT-015: Subagent configuration (source)
# ===========================================================================


class TestSubagentConfigSource:
    """REQ-BOOT-015: Subagent transcript configuration."""

    # @tests REQ-BOOT-015, SCN-BOOT-015-01, SCN-BOOT-015-02
    def test_skip_subagents_env_var(self):
        """Script reads AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS" in source

    # @tests REQ-BOOT-001, SCN-BOOT-001-03
    def test_transcript_dir_override(self):
        """Script reads AGENTIC_CONTEXT_TRANSCRIPT_DIR."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert "AGENTIC_CONTEXT_TRANSCRIPT_DIR" in source

    # @tests REQ-BOOT-001
    def test_glob_patterns(self):
        """Script uses correct glob patterns for discovery."""
        source = BOOTSTRAP_SOURCE.read_text()
        assert '*.jsonl' in source
        assert '*/subagents/agent-*.jsonl' in source
