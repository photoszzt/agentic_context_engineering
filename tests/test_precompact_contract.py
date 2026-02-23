# Spec: docs/hooks/spec.md
# Testing: docs/hooks/testing.md
"""
Contract (black-box) tests for the precompact pipeline (src/hooks/precompact.py).

These tests run precompact.py as a subprocess, feeding it stdin JSON and
verifying observable behavior: exit codes and stderr output.

They do NOT reference internal function call ordering, internal variable names,
or design.md. They verify only the documented external behavior from spec.md.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
PRECOMPACT_PY = os.path.join(PROJECT_ROOT, "src", "hooks", "precompact.py")
SRC_HOOKS_DIR = os.path.join(PROJECT_ROOT, "src", "hooks")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_precompact(stdin_json, env_overrides=None, timeout=30):
    """Run precompact.py as a subprocess with the given stdin JSON.

    Returns subprocess.CompletedProcess.
    """
    env = os.environ.copy()
    # Remove API keys to prevent real LLM calls
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env.pop("AGENTIC_CONTEXT_API_KEY", None)
    # Ensure src/hooks is importable (PYTHONPATH includes src/hooks)
    env["PYTHONPATH"] = SRC_HOOKS_DIR + os.pathsep + env.get("PYTHONPATH", "")
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(
        [sys.executable, PRECOMPACT_PY],
        input=stdin_json,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result


def _create_transcript_file(tmp_path, messages):
    """Create a JSONL transcript file and return its path."""
    transcript_path = tmp_path / "transcript.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return str(transcript_path)


def _make_transcript_entries(count=3):
    """Create transcript entries in the JSONL format that load_transcript expects."""
    entries = []
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        entries.append({
            "type": role,
            "message": {"role": role, "content": f"Message {i}"},
        })
    return entries


def _create_playbook_file(tmp_path):
    """Create a minimal playbook.json in the expected location and return the project dir."""
    project_dir = tmp_path / "project"
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(parents=True)
    playbook = {
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
    playbook_path = claude_dir / "playbook.json"
    with open(playbook_path, "w") as f:
        json.dump(playbook, f)
    return str(project_dir)


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestContractPipelineRuns:
    """@tests-contract REQ-PRECOMPACT-001"""

    def test_contract_pipeline_runs_successfully(self, tmp_path):
        """@tests-contract REQ-PRECOMPACT-001

        GIVEN precompact.py is invoked with a non-empty transcript
        AND no API key is set (LLM calls degrade gracefully to empty results)
        WHEN the pipeline executes
        THEN the process exits with code 0 (pipeline completes successfully
        because LLM functions return empty results without raising)

        NOTE: This test only verifies exit code 0 (pipeline runs without crashing),
        which proves REQ-PRECOMPACT-001 (pipeline replacement works). It does NOT
        verify ordering (REQ-002/003/004), parity (REQ-005), or clear_session
        timing (REQ-007) -- those require behavioral assertions covered by
        white-box tests.
        """
        # Create transcript with real entries
        entries = _make_transcript_entries(5)
        transcript_path = _create_transcript_file(tmp_path, entries)
        project_dir = _create_playbook_file(tmp_path)

        stdin_json = json.dumps({"transcript_path": transcript_path})

        result = _run_precompact(
            stdin_json,
            env_overrides={"CLAUDE_PROJECT_DIR": project_dir},
        )

        assert result.returncode == 0, (
            f"Pipeline should complete successfully (with graceful LLM degradation).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestContractEmptyTranscript:
    """@tests-contract REQ-PRECOMPACT-009"""

    def test_contract_empty_transcript_exit_0(self, tmp_path):
        """@tests-contract REQ-PRECOMPACT-009

        GIVEN precompact.py receives stdin JSON with transcript_path pointing
        to an empty conversation
        AND load_transcript returns []
        WHEN the empty check executes
        THEN the process exits with code 0
        """
        # Create an empty transcript file
        transcript_path = _create_transcript_file(tmp_path, [])
        project_dir = _create_playbook_file(tmp_path)

        stdin_json = json.dumps({"transcript_path": transcript_path})

        result = _run_precompact(
            stdin_json,
            env_overrides={"CLAUDE_PROJECT_DIR": project_dir},
        )

        assert result.returncode == 0, (
            f"Empty transcript should exit with code 0.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_contract_missing_transcript_path_exit_0(self, tmp_path):
        """@tests-contract REQ-PRECOMPACT-009

        GIVEN precompact.py receives stdin JSON without transcript_path
        WHEN load_transcript is called with None
        THEN the process exits with code 0 (empty transcript path means empty messages)
        """
        project_dir = _create_playbook_file(tmp_path)
        stdin_json = json.dumps({})

        result = _run_precompact(
            stdin_json,
            env_overrides={"CLAUDE_PROJECT_DIR": project_dir},
        )

        assert result.returncode == 0, (
            f"Missing transcript_path should exit 0.\n"
            f"stderr: {result.stderr}"
        )

    def test_contract_nonexistent_transcript_path_exit_0(self, tmp_path):
        """@tests-contract REQ-PRECOMPACT-009

        GIVEN precompact.py receives stdin JSON with transcript_path pointing
        to a nonexistent file
        WHEN load_transcript returns []
        THEN the process exits with code 0
        """
        project_dir = _create_playbook_file(tmp_path)
        stdin_json = json.dumps({"transcript_path": "/nonexistent/path/transcript.jsonl"})

        result = _run_precompact(
            stdin_json,
            env_overrides={"CLAUDE_PROJECT_DIR": project_dir},
        )

        assert result.returncode == 0, (
            f"Nonexistent transcript should exit 0.\n"
            f"stderr: {result.stderr}"
        )


class TestContractErrorHandling:
    """@tests-contract REQ-PRECOMPACT-008"""

    def test_contract_exception_causes_exit_1(self, tmp_path):
        """@tests-contract REQ-PRECOMPACT-008

        GIVEN precompact.py is invoked
        WHEN an unhandled exception occurs (e.g., malformed stdin JSON)
        THEN the process exits with code 1
        AND "Error:" appears in stderr
        """
        # Feed invalid JSON to stdin -- json.load will raise JSONDecodeError
        result = _run_precompact("not valid json at all")

        assert result.returncode == 1, (
            f"Malformed stdin should cause exit code 1.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "Error:" in result.stderr, (
            f"stderr should contain 'Error:' message.\n"
            f"stderr: {result.stderr}"
        )

    def test_contract_traceback_in_stderr(self, tmp_path):
        """@tests-contract REQ-PRECOMPACT-008

        GIVEN precompact.py is invoked with malformed stdin
        WHEN the exception is caught by the top-level handler
        THEN a traceback is printed to stderr
        """
        result = _run_precompact("{{{invalid json")

        assert result.returncode == 1
        assert "Traceback" in result.stderr, (
            f"stderr should contain a traceback.\n"
            f"stderr: {result.stderr}"
        )


class TestContractNoSettings:
    """@tests-contract REQ-PRECOMPACT-006"""

    def test_contract_no_settings_behavior(self, tmp_path):
        """@tests-contract REQ-PRECOMPACT-006

        GIVEN precompact.py is invoked with a non-empty transcript
        WHEN the pipeline runs
        THEN the process does not fail due to missing settings file
        (because precompact.py does not call load_settings)
        """
        entries = _make_transcript_entries(3)
        transcript_path = _create_transcript_file(tmp_path, entries)
        project_dir = _create_playbook_file(tmp_path)

        stdin_json = json.dumps({"transcript_path": transcript_path})

        # Ensure no settings file exists in the home directory
        # The pipeline should not need it
        result = _run_precompact(
            stdin_json,
            env_overrides={"CLAUDE_PROJECT_DIR": project_dir},
        )

        assert result.returncode == 0, (
            f"Pipeline should succeed without any settings file.\n"
            f"stderr: {result.stderr}"
        )

    def test_contract_no_settings_source_inspection(self):
        """@tests-contract REQ-PRECOMPACT-006

        Verify from a black-box perspective that the precompact.py source
        does not reference settings-related behavior (load_settings,
        update_on_exit, update_on_clear).
        """
        # Read the source as a black-box artifact to verify absence of
        # settings-related strings. This is a valid contract test because
        # the contract states precompact does NOT call load_settings.
        source = Path(PRECOMPACT_PY).read_text()
        assert "load_settings" not in source, "precompact.py must not reference load_settings"
        assert "update_on_exit" not in source
        assert "update_on_clear" not in source


class TestContractImportSmoke:
    """@tests-contract REQ-PRECOMPACT-001"""

    def test_contract_import_succeeds(self):
        """@tests-contract REQ-PRECOMPACT-001

        GIVEN precompact.py exists
        WHEN it is imported
        THEN no ImportError is raised
        """
        result = subprocess.run(
            [sys.executable, "-c", "import sys; sys.path.insert(0, 'src/hooks'); import precompact"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, (
            f"Import of precompact should succeed.\n"
            f"stderr: {result.stderr}"
        )
