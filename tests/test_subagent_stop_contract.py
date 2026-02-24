# Spec: docs/hooks/spec.md
# Testing: docs/hooks/testing.md
"""
Contract (black-box) tests for the subagent_stop hook (src/hooks/subagent_stop.py).

These tests run subagent_stop.py as a subprocess, feeding it stdin JSON and
verifying observable behavior: exit codes and playbook changes.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
SUBAGENT_STOP_PY = os.path.join(PROJECT_ROOT, "src", "hooks", "subagent_stop.py")
SRC_HOOKS_DIR = os.path.join(PROJECT_ROOT, "src", "hooks")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_subagent_stop(stdin_json, env_overrides=None, home_override=None, timeout=30):
    """Run subagent_stop.py as a subprocess with the given stdin JSON."""
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env.pop("AGENTIC_CONTEXT_API_KEY", None)
    env["PYTHONPATH"] = SRC_HOOKS_DIR + os.pathsep + env.get("PYTHONPATH", "")
    if home_override is not None:
        env["HOME"] = home_override
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(
        [sys.executable, SUBAGENT_STOP_PY],
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


def _create_project_dir(tmp_path, settings=None, home_dir=None):
    """Create a project dir with .claude/playbook.json (and optional settings.json).

    If home_dir is provided, settings.json is written under home_dir/.claude/
    so that load_settings() (which reads from Path.home()/.claude/settings.json)
    picks it up when HOME is overridden in the subprocess environment.
    """
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
    with open(claude_dir / "playbook.json", "w") as f:
        json.dump(playbook, f)

    if settings is not None:
        if home_dir is not None:
            # Write settings under the fake HOME so load_settings() finds them
            fake_claude_dir = Path(home_dir) / ".claude"
            fake_claude_dir.mkdir(parents=True, exist_ok=True)
            with open(fake_claude_dir / "settings.json", "w") as f:
                json.dump(settings, f)
        else:
            with open(claude_dir / "settings.json", "w") as f:
                json.dump(settings, f)

    return str(project_dir)


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestContractEmptyTranscript:
    def test_empty_transcript_exits_0(self, tmp_path):
        """Empty transcript -> exit 0."""
        transcript_path = _create_transcript_file(tmp_path, [])
        project_dir = _create_project_dir(tmp_path)
        stdin_json = json.dumps({"transcript_path": transcript_path})

        result = _run_subagent_stop(
            stdin_json,
            env_overrides={"CLAUDE_PROJECT_DIR": project_dir},
        )

        assert result.returncode == 0, (
            f"Empty transcript should exit 0.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_missing_transcript_path_exits_0(self, tmp_path):
        """Missing transcript_path in stdin -> exit 0."""
        project_dir = _create_project_dir(tmp_path)
        stdin_json = json.dumps({})

        result = _run_subagent_stop(
            stdin_json,
            env_overrides={"CLAUDE_PROJECT_DIR": project_dir},
        )

        assert result.returncode == 0, (
            f"Missing transcript_path should exit 0.\nstderr: {result.stderr}"
        )

    def test_nonexistent_transcript_exits_0(self, tmp_path):
        """Nonexistent transcript path -> exit 0."""
        project_dir = _create_project_dir(tmp_path)
        stdin_json = json.dumps({"transcript_path": "/nonexistent/path/transcript.jsonl"})

        result = _run_subagent_stop(
            stdin_json,
            env_overrides={"CLAUDE_PROJECT_DIR": project_dir},
        )

        assert result.returncode == 0, (
            f"Nonexistent transcript should exit 0.\nstderr: {result.stderr}"
        )


class TestContractPipelineRuns:
    def test_pipeline_runs_with_valid_transcript(self, tmp_path):
        """Valid transcript + no API key -> exit 0 (graceful LLM degradation)."""
        entries = _make_transcript_entries(5)
        transcript_path = _create_transcript_file(tmp_path, entries)
        project_dir = _create_project_dir(tmp_path)
        stdin_json = json.dumps({"transcript_path": transcript_path})

        result = _run_subagent_stop(
            stdin_json,
            env_overrides={"CLAUDE_PROJECT_DIR": project_dir},
        )

        assert result.returncode == 0, (
            f"Pipeline should complete successfully (with graceful LLM degradation).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestContractSettingsDisabled:
    def test_disabled_setting_exits_0_no_pipeline(self, tmp_path):
        """playbook_update_on_subagent_stop=false -> exit 0, playbook unchanged."""
        entries = _make_transcript_entries(3)
        transcript_path = _create_transcript_file(tmp_path, entries)
        fake_home = str(tmp_path / "fakehome")
        project_dir = _create_project_dir(
            tmp_path,
            settings={"playbook_update_on_subagent_stop": False},
            home_dir=fake_home,
        )

        # Record playbook mtime before
        playbook_path = Path(project_dir) / ".claude" / "playbook.json"
        mtime_before = playbook_path.stat().st_mtime

        stdin_json = json.dumps({"transcript_path": transcript_path})
        result = _run_subagent_stop(
            stdin_json,
            env_overrides={"CLAUDE_PROJECT_DIR": project_dir},
            home_override=fake_home,
        )

        assert result.returncode == 0, (
            f"Disabled setting should exit 0.\nstderr: {result.stderr}"
        )

        mtime_after = playbook_path.stat().st_mtime
        assert mtime_before == mtime_after, (
            "Playbook should NOT be modified when playbook_update_on_subagent_stop=false"
        )


class TestContractErrorHandling:
    def test_malformed_stdin_exits_1(self, tmp_path):
        """Malformed stdin JSON -> exit 1 with Error: in stderr."""
        result = _run_subagent_stop("not valid json at all")

        assert result.returncode == 1, (
            f"Malformed stdin should cause exit 1.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "Error:" in result.stderr

    def test_malformed_stdin_has_traceback(self, tmp_path):
        """Malformed stdin -> traceback in stderr."""
        result = _run_subagent_stop("{{{invalid json")

        assert result.returncode == 1
        assert "Traceback" in result.stderr


class TestContractImportSmoke:
    def test_import_succeeds(self):
        """subagent_stop.py can be imported without errors."""
        result = subprocess.run(
            [sys.executable, "-c", "import sys; sys.path.insert(0, 'src/hooks'); import subagent_stop"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, (
            f"Import of subagent_stop should succeed.\nstderr: {result.stderr}"
        )


class TestContractNoClearSession:
    def test_source_has_no_clear_session(self):
        """Black-box: subagent_stop.py source must not reference clear_session."""
        source = Path(SUBAGENT_STOP_PY).read_text()
        assert "clear_session" not in source, (
            "subagent_stop.py must not call clear_session "
            "(the main session is still running when a subagent stops)"
        )
