# Spec: docs/hooks/spec.md
# Testing: docs/hooks/testing.md
"""
Contract (black-box) tests for the hooks module (install.js).

These tests run `node install.js` as a subprocess in a controlled temp
directory with a fake `uv` binary on PATH and HOME overridden.  They
verify only the external behaviour: exit code, resulting settings.json
content, and stderr messages.

They do NOT reference internal function signatures, internal data
structures, or design.md.  They verify only the documented public
behaviour from the spec.
"""

import json
import os
import platform
import stat
import subprocess
import textwrap

import shutil

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = str(
    __import__("pathlib").Path(__file__).resolve().parent.parent
)
INSTALL_JS = os.path.join(PROJECT_ROOT, "install.js")
SRC_DIR = os.path.join(PROJECT_ROOT, "src")

# Resolve the directory containing the `node` binary so we can construct
# a PATH that includes node but excludes `uv` for "uv not found" tests.
_NODE_BIN = shutil.which("node")
_NODE_DIR = os.path.dirname(_NODE_BIN) if _NODE_BIN else "/usr/local/bin"

# The three event types and their expected script names
EVENT_SCRIPT_MAP = {
    "UserPromptSubmit": "user_prompt_inject.py",
    "SessionEnd": "session_end.py",
    "PreCompact": "precompact.py",
}

EVENT_TIMEOUT_MAP = {
    "UserPromptSubmit": 10,
    "SessionEnd": 120,
    "PreCompact": 120,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def contract_env(tmp_path):
    """
    Set up a complete contract test environment:
    - Fake HOME directory with .claude/ structure
    - Fake uv binary on PATH that handles 'sync' subcommand
    - Environment dict ready for subprocess.run
    - Helper to read the resulting settings.json

    Returns a namespace-like dict with helpers.
    """
    home_dir = str(tmp_path / "home")
    claude_dir = os.path.join(home_dir, ".claude")
    hooks_dir = os.path.join(claude_dir, "hooks")
    settings_path = os.path.join(claude_dir, "settings.json")
    bin_dir = str(tmp_path / "bin")

    os.makedirs(hooks_dir, exist_ok=True)
    os.makedirs(bin_dir, exist_ok=True)

    # Create fake uv binary
    uv_script = os.path.join(bin_dir, "uv")
    with open(uv_script, "w") as f:
        f.write(textwrap.dedent("""\
            #!/bin/bash
            if [[ "$1" == "sync" ]]; then
                exit 0
            fi
            echo "fake uv called with: $@" >&2
            exit 0
        """))
    os.chmod(uv_script, stat.S_IRWXU)

    # Build environment
    env = os.environ.copy()
    env["HOME"] = home_dir
    if platform.system() == "Windows":
        env["USERPROFILE"] = home_dir
    # Prepend our bin dir so `which uv` finds our fake
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")

    class Env:
        pass

    e = Env()
    e.home_dir = home_dir
    e.claude_dir = claude_dir
    e.hooks_dir = hooks_dir
    e.settings_path = settings_path
    e.bin_dir = bin_dir
    e.uv_script = uv_script
    e.env = env
    e.tmp_path = tmp_path

    def run_install(extra_env=None, check=False):
        """Run node install.js and return the subprocess result."""
        run_env = dict(e.env)
        if extra_env:
            run_env.update(extra_env)
        return subprocess.run(
            ["node", INSTALL_JS],
            capture_output=True,
            text=True,
            env=run_env,
            timeout=30,
        )

    def read_settings():
        """Read and parse the resulting settings.json."""
        with open(settings_path) as f:
            return json.load(f)

    def write_settings(content):
        """Write pre-existing settings.json."""
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        if isinstance(content, dict):
            content = json.dumps(content, indent=2)
        with open(settings_path, "w") as f:
            f.write(content)

    def extract_commands(settings, event_name):
        """Extract all command strings from a settings dict event type."""
        commands = []
        for group in settings.get("hooks", {}).get(event_name, []):
            for hook in group.get("hooks", []):
                commands.append(hook.get("command", ""))
        return commands

    def path_without_uv():
        """Return a PATH string that includes node but does NOT include uv."""
        # We build a minimal PATH: node's directory + standard system dirs.
        # This ensures `which uv` will fail but `node` is still available.
        dirs = [_NODE_DIR, "/usr/bin", "/bin"]
        return os.pathsep.join(dirs)

    e.run_install = run_install
    e.read_settings = read_settings
    e.write_settings = write_settings
    e.extract_commands = extract_commands
    e.path_without_uv = path_without_uv
    return e


def make_hook_group(command, hook_type="command", timeout=10):
    """Build a hook group object matching the settings.json structure."""
    return {
        "hooks": [
            {
                "type": hook_type,
                "command": command,
                "timeout": timeout,
            }
        ]
    }


# ---------------------------------------------------------------------------
# REQ-HOOKS-001: Hook Command Uses uv run
# ---------------------------------------------------------------------------


def test_contract_commands_use_uv_run(contract_env):
    # @tests-contract REQ-HOOKS-001
    result = contract_env.run_install()
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    settings = contract_env.read_settings()
    for event_name in EVENT_SCRIPT_MAP:
        commands = contract_env.extract_commands(settings, event_name)
        assert len(commands) >= 1, f"No commands for {event_name}"
        for cmd in commands:
            assert "uv run --project" in cmd, (
                f"Command for {event_name} does not use uv run: {cmd}"
            )


# ---------------------------------------------------------------------------
# REQ-HOOKS-003: Command Format
# ---------------------------------------------------------------------------


def test_contract_command_format(contract_env):
    # @tests-contract REQ-HOOKS-003
    result = contract_env.run_install()
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    settings = contract_env.read_settings()
    uv_path = contract_env.uv_script  # absolute path to our fake uv

    for event_name, script_name in EVENT_SCRIPT_MAP.items():
        commands = contract_env.extract_commands(settings, event_name)
        assert len(commands) == 1, (
            f"Expected 1 command for {event_name}, got {len(commands)}"
        )
        cmd = commands[0]
        # Verify format: <abs_uv> run --project "<abs_dir>" python "<abs_script>"
        assert cmd.startswith(uv_path + " run --project"), (
            f"Command does not start with absolute uv path: {cmd}"
        )
        assert f'python "' in cmd
        # Script path should point to ~/.claude/hooks/<script_name>
        expected_script = os.path.join(
            contract_env.home_dir, ".claude", "hooks", script_name
        )
        assert f'python "{expected_script}"' in cmd, (
            f"Script path mismatch in: {cmd}"
        )


# ---------------------------------------------------------------------------
# REQ-HOOKS-005: Stale Entries Removed
# ---------------------------------------------------------------------------


def test_contract_stale_entries_removed(contract_env):
    # @tests-contract REQ-HOOKS-005
    # Pre-populate with stale entries
    contract_env.write_settings({
        "hooks": {
            "SessionEnd": [
                make_hook_group(
                    'python3 "/Users/jane/.claude/hooks/session_end.py"',
                    timeout=120,
                ),
            ],
            "UserPromptSubmit": [
                make_hook_group(
                    '/old/.venv/bin/python3 "/old/.claude/hooks/user_prompt_inject.py"',
                    timeout=10,
                ),
            ],
        }
    })

    result = contract_env.run_install()
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    settings = contract_env.read_settings()
    for event_name in EVENT_SCRIPT_MAP:
        commands = contract_env.extract_commands(settings, event_name)
        for cmd in commands:
            # No stale python3 commands should remain
            assert 'python3 "' not in cmd, (
                f"Stale python3 entry not removed in {event_name}: {cmd}"
            )
            assert "uv run" in cmd


# ---------------------------------------------------------------------------
# REQ-HOOKS-006: Non-Project Hooks Preserved
# ---------------------------------------------------------------------------


def test_contract_non_project_hooks_preserved(contract_env):
    # @tests-contract REQ-HOOKS-006
    non_project_cmd = 'python3 "/Users/jane/.claude/hooks/document_scanner.py"'
    contract_env.write_settings({
        "hooks": {
            "UserPromptSubmit": [
                make_hook_group(
                    'python3 "/Users/jane/.claude/hooks/user_prompt_inject.py"',
                    timeout=10,
                ),
                make_hook_group(non_project_cmd, timeout=30),
            ],
        }
    })

    result = contract_env.run_install()
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    settings = contract_env.read_settings()
    commands = contract_env.extract_commands(settings, "UserPromptSubmit")
    assert non_project_cmd in commands, (
        f"Non-project hook not preserved: {commands}"
    )


# ---------------------------------------------------------------------------
# REQ-HOOKS-007: uv Not Found Error
# ---------------------------------------------------------------------------


def test_contract_uv_not_found_error(contract_env):
    # @tests-contract REQ-HOOKS-007
    # If there's a pre-existing settings.json, verify it's not modified
    contract_env.write_settings({"existing": "value"})

    no_uv_path = contract_env.path_without_uv()
    result = contract_env.run_install(extra_env={"PATH": no_uv_path})
    assert result.returncode != 0, "Should exit non-zero when uv not found"
    assert "not installed" in result.stderr or "not found" in result.stderr, (
        f"Expected error message about uv not found, got: {result.stderr}"
    )

    # Settings should not be modified
    with open(contract_env.settings_path) as f:
        content = json.load(f)
    assert content == {"existing": "value"}, (
        "Settings were modified despite uv not found error"
    )


# ---------------------------------------------------------------------------
# REQ-HOOKS-008: Absolute uv Path
# ---------------------------------------------------------------------------


def test_contract_absolute_uv_path(contract_env):
    # @tests-contract REQ-HOOKS-008
    result = contract_env.run_install()
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    settings = contract_env.read_settings()
    for event_name in EVENT_SCRIPT_MAP:
        commands = contract_env.extract_commands(settings, event_name)
        for cmd in commands:
            # Command should start with an absolute path, not bare "uv"
            assert cmd.startswith("/"), (
                f"Command does not start with absolute path: {cmd}"
            )
            assert not cmd.startswith("uv "), (
                f"Command uses bare 'uv' instead of absolute path: {cmd}"
            )


# ---------------------------------------------------------------------------
# REQ-HOOKS-009: uv sync Failure Aborts
# ---------------------------------------------------------------------------


def test_contract_uv_sync_failure_aborts(contract_env):
    # @tests-contract REQ-HOOKS-009
    # Replace fake uv with one that fails on sync
    with open(contract_env.uv_script, "w") as f:
        f.write(textwrap.dedent("""\
            #!/bin/bash
            if [[ "$1" == "sync" ]]; then
                exit 2
            fi
            echo "fake uv called with: $@" >&2
            exit 0
        """))
    os.chmod(contract_env.uv_script, stat.S_IRWXU)

    # Write pre-existing settings
    contract_env.write_settings({"existing": "value"})

    result = contract_env.run_install()
    assert result.returncode != 0, "Should exit non-zero when uv sync fails"
    assert "uv sync failed" in result.stderr.lower() or "uv sync" in result.stderr.lower(), (
        f"Expected error about uv sync failure, got: {result.stderr}"
    )

    # Settings should not be modified
    with open(contract_env.settings_path) as f:
        content = json.load(f)
    assert content == {"existing": "value"}, (
        "Settings were modified despite uv sync failure"
    )


# ---------------------------------------------------------------------------
# INV-HOOKS-007: Output Is Valid JSON
# ---------------------------------------------------------------------------


def test_contract_output_is_valid_json(contract_env):
    # @tests-contract INV-HOOKS-007
    result = contract_env.run_install()
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    with open(contract_env.settings_path) as f:
        raw = f.read()

    # Must be parseable JSON
    parsed = json.loads(raw)
    assert isinstance(parsed, dict), "settings.json is not a JSON object"
    assert "hooks" in parsed, "settings.json has no hooks key"


# ---------------------------------------------------------------------------
# Deliverable Tests
# ---------------------------------------------------------------------------


def test_contract_full_install_fresh(contract_env):
    # @tests-contract REQ-HOOKS-001, REQ-HOOKS-003, REQ-HOOKS-008
    # Fresh install with no prior settings.json
    result = contract_env.run_install()
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    settings = contract_env.read_settings()

    # All three event types should have hooks
    for event_name, script_name in EVENT_SCRIPT_MAP.items():
        commands = contract_env.extract_commands(settings, event_name)
        assert len(commands) == 1, (
            f"Expected 1 command for {event_name}, got {len(commands)}: {commands}"
        )
        cmd = commands[0]
        assert "uv run --project" in cmd
        assert script_name in cmd
        # Command starts with absolute path
        assert cmd.startswith("/")

    # Valid JSON
    assert isinstance(settings, dict)

    # Timeouts correct
    for event_name, expected_timeout in EVENT_TIMEOUT_MAP.items():
        for group in settings["hooks"][event_name]:
            for hook in group["hooks"]:
                assert hook["timeout"] == expected_timeout


def test_contract_full_install_with_stale_entries(contract_env):
    # @tests-contract REQ-HOOKS-005, REQ-HOOKS-006
    # Install with stale entries and a non-project hook
    non_project_cmd = 'python3 "/Users/jane/.claude/hooks/document_scanner.py"'
    contract_env.write_settings({
        "hooks": {
            "UserPromptSubmit": [
                make_hook_group(
                    'python3 "/Users/jane/.claude/hooks/user_prompt_inject.py"',
                    timeout=10,
                ),
                make_hook_group(non_project_cmd, timeout=30),
            ],
            "SessionEnd": [
                make_hook_group(
                    '/old/.venv/bin/python3 "/old/.claude/hooks/session_end.py"',
                    timeout=120,
                ),
            ],
        },
        "enabledPlugins": ["keep-me"],
    })

    result = contract_env.run_install()
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    settings = contract_env.read_settings()

    # Stale entries removed
    for event_name in EVENT_SCRIPT_MAP:
        for cmd in contract_env.extract_commands(settings, event_name):
            assert 'python3 "' not in cmd or "document_scanner" in cmd

    # Non-project hook preserved
    user_cmds = contract_env.extract_commands(settings, "UserPromptSubmit")
    assert non_project_cmd in user_cmds

    # Non-hook settings preserved
    assert settings.get("enabledPlugins") == ["keep-me"]


def test_contract_full_install_idempotent(contract_env):
    # @tests-contract REQ-HOOKS-005, INV-HOOKS-001
    # Run install twice, verify identical result
    result1 = contract_env.run_install()
    assert result1.returncode == 0, f"First install failed: {result1.stderr}"
    settings1 = contract_env.read_settings()

    result2 = contract_env.run_install()
    assert result2.returncode == 0, f"Second install failed: {result2.stderr}"
    settings2 = contract_env.read_settings()

    assert settings1["hooks"] == settings2["hooks"], (
        "Idempotency violated: second install produced different hooks"
    )


# ---------------------------------------------------------------------------
# Error Path Tests (TC-ERR-*)
# ---------------------------------------------------------------------------


def test_contract_err_uv_not_found_no_file_modification(contract_env):
    # @tests-contract REQ-HOOKS-007 (TC-ERR-002)
    # @tests-invariant INV-HOOKS-004
    # Verify settings.json is NOT modified when uv is not found
    original_content = {"hooks": {"SessionEnd": [make_hook_group("keep me")]}}
    contract_env.write_settings(original_content)

    no_uv_path = contract_env.path_without_uv()
    result = contract_env.run_install(extra_env={"PATH": no_uv_path})
    assert result.returncode != 0

    with open(contract_env.settings_path) as f:
        after = json.load(f)
    assert after == original_content, "File was modified despite uv-not-found error"


def test_contract_err_uv_sync_failure_no_file_modification(contract_env):
    # @tests-contract REQ-HOOKS-009 (TC-ERR-004)
    # @tests-invariant INV-HOOKS-004
    # Replace uv with a script that fails on sync
    with open(contract_env.uv_script, "w") as f:
        f.write(textwrap.dedent("""\
            #!/bin/bash
            if [[ "$1" == "sync" ]]; then
                exit 2
            fi
            exit 0
        """))
    os.chmod(contract_env.uv_script, stat.S_IRWXU)

    original_content = {"hooks": {"SessionEnd": [make_hook_group("keep me")]}}
    contract_env.write_settings(original_content)

    result = contract_env.run_install()
    assert result.returncode != 0

    with open(contract_env.settings_path) as f:
        after = json.load(f)
    assert after == original_content, "File was modified despite uv sync failure"


def test_contract_err_uv_sync_error_message(contract_env):
    # @tests-contract REQ-HOOKS-009 (TC-ERR-003)
    with open(contract_env.uv_script, "w") as f:
        f.write(textwrap.dedent("""\
            #!/bin/bash
            if [[ "$1" == "sync" ]]; then
                exit 2
            fi
            exit 0
        """))
    os.chmod(contract_env.uv_script, stat.S_IRWXU)

    result = contract_env.run_install()
    assert result.returncode != 0
    stderr_lower = result.stderr.lower()
    # Should mention uv sync failure
    assert "uv sync" in stderr_lower, (
        f"Error message should mention uv sync: {result.stderr}"
    )


def test_contract_err_uv_not_found_error_message(contract_env):
    # @tests-contract REQ-HOOKS-007 (TC-ERR-001)
    no_uv_path = contract_env.path_without_uv()
    result = contract_env.run_install(extra_env={"PATH": no_uv_path})
    assert result.returncode != 0

    # Q8: Assert the EXACT full error message from REQ-HOOKS-007 (both lines)
    expected_line1 = (
        "Error: 'uv' is not installed or not found on PATH. "
        "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    )
    expected_line2 = (
        "See https://docs.astral.sh/uv/getting-started/installation/ for other methods."
    )
    assert expected_line1 in result.stderr, (
        f"Missing first line of REQ-HOOKS-007 error message.\n"
        f"Expected: {expected_line1}\nGot stderr: {result.stderr}"
    )
    assert expected_line2 in result.stderr, (
        f"Missing second line of REQ-HOOKS-007 error message.\n"
        f"Expected: {expected_line2}\nGot stderr: {result.stderr}"
    )


def test_contract_err_hooks_dir_created(contract_env):
    # @tests-contract REQ-HOOKS-003 (TC-ERR-005 variant: verify hooks are copied)
    # On successful install, hook scripts should be copied to ~/.claude/hooks/
    result = contract_env.run_install()
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    # Verify hook script files exist in the destination
    for script_name in EVENT_SCRIPT_MAP.values():
        script_path = os.path.join(contract_env.hooks_dir, script_name)
        assert os.path.exists(script_path), (
            f"Hook script not copied: {script_path}"
        )
