# Spec: docs/hooks/spec.md
# Testing: docs/hooks/testing.md
"""
White-box tests for the hooks module (install.js mergeSettings function).

Covers all REQ-HOOKS-*, SCN-HOOKS-*, INV-HOOKS-* from spec.md,
plus adversarial test categories TC-INVAL-*, TC-STALE-*, TC-BOUND-*.

Test approach: call mergeSettings() via a small Node.js helper that
requires install.js with HOME overridden so that all path derivation
points to a temp directory. The helper writes JSON output to stdout
which the Python test parses and asserts on.
"""

import json
import os
import platform
import shutil
import subprocess
import textwrap

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = str(
    __import__("pathlib").Path(__file__).resolve().parent.parent
)
INSTALL_JS = os.path.join(PROJECT_ROOT, "install.js")
SRC_SETTINGS = os.path.join(PROJECT_ROOT, "src", "settings.json")

# The three project scripts as referenced by install.js
PROJECT_SCRIPTS = ["user_prompt_inject.py", "session_end.py", "precompact.py"]

# Event types and their expected script mappings
EVENT_SCRIPT_MAP = {
    "UserPromptSubmit": "user_prompt_inject.py",
    "SessionEnd": "session_end.py",
    "PreCompact": "precompact.py",
}

# Expected timeouts per spec
EVENT_TIMEOUT_MAP = {
    "UserPromptSubmit": 10,
    "SessionEnd": 120,
    "PreCompact": 120,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def call_merge_settings(
    tmp_path, src_settings_path, abs_uv_path, project_dir,
    dest_settings_content=None,
):
    """
    Call mergeSettings() in a Node.js subprocess with HOME set to tmp_path
    so that the module-level settingsPath resolves to tmp_path/.claude/settings.json.

    If dest_settings_content is provided, write it to the destination path
    before calling mergeSettings.

    Returns the merged settings dict parsed from JSON stdout.
    """
    home_dir = str(tmp_path / "home")
    claude_dir = os.path.join(home_dir, ".claude")
    hooks_dir = os.path.join(claude_dir, "hooks")
    dest_settings_path = os.path.join(claude_dir, "settings.json")

    os.makedirs(hooks_dir, exist_ok=True)

    if dest_settings_content is not None:
        with open(dest_settings_path, "w") as f:
            f.write(dest_settings_content)

    # Node.js helper: require install.js with HOME overridden, call mergeSettings,
    # output the result as JSON.
    # We must set HOME BEFORE require() so that os.homedir() returns our temp dir.
    helper_js = textwrap.dedent(f"""\
        // Override HOME before requiring install.js so module-level paths use temp dir
        process.env.HOME = {json.dumps(home_dir)};
        // Also set USERPROFILE for Windows compatibility
        process.env.USERPROFILE = {json.dumps(home_dir)};

        // Clear the require cache to pick up new HOME
        delete require.cache[require.resolve({json.dumps(INSTALL_JS)})];

        // Monkey-patch process.exit to prevent it from terminating our helper
        const originalExit = process.exit;
        let exitCalled = false;
        let exitCode = null;
        process.exit = function(code) {{
            exitCalled = true;
            exitCode = code;
            // Don't actually exit
        }};

        // Suppress console.log from install() running at require time
        const originalLog = console.log;
        const originalError = console.error;
        const originalWrite = process.stderr.write;
        console.log = function() {{}};
        console.error = function() {{}};
        process.stderr.write = function() {{ return true; }};

        try {{
            const mod = require({json.dumps(INSTALL_JS)});
            // Restore
            console.log = originalLog;
            console.error = originalError;
            process.stderr.write = originalWrite;
            process.exit = originalExit;

            const result = mod.mergeSettings(
                {json.dumps(src_settings_path)},
                {json.dumps(abs_uv_path)},
                {json.dumps(project_dir)}
            );
            process.stdout.write(JSON.stringify(result));
        }} catch (e) {{
            console.log = originalLog;
            console.error = originalError;
            process.stderr.write = originalWrite;
            process.exit = originalExit;

            process.stdout.write(JSON.stringify({{__error__: e.message}}));
        }}
    """)

    helper_path = str(tmp_path / "helper.js")
    with open(helper_path, "w") as f:
        f.write(helper_js)

    env = os.environ.copy()
    env["HOME"] = home_dir
    if platform.system() == "Windows":
        env["USERPROFILE"] = home_dir

    result = subprocess.run(
        ["node", helper_path],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Node helper failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    parsed = json.loads(result.stdout)
    if isinstance(parsed, dict) and "__error__" in parsed:
        raise RuntimeError(f"mergeSettings threw: {parsed['__error__']}")
    return parsed


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


def make_settings_with_hooks(hook_entries):
    """
    Build a settings.json string from a dict of event_type -> list of
    (command, timeout) tuples.
    """
    hooks = {}
    for event_name, entries in hook_entries.items():
        hooks[event_name] = []
        for cmd, timeout in entries:
            hooks[event_name].append(make_hook_group(cmd, timeout=timeout))
    return json.dumps({"hooks": hooks}, indent=2)


def extract_commands(merged, event_name):
    """Extract all command strings from a merged settings event type."""
    commands = []
    for group in merged.get("hooks", {}).get(event_name, []):
        for hook in group.get("hooks", []):
            commands.append(hook.get("command", ""))
    return commands


def count_project_hooks(merged, event_name, script_name):
    """Count hook entries whose command references a specific project script."""
    substring = f"/.claude/hooks/{script_name}"
    return sum(
        1
        for cmd in extract_commands(merged, event_name)
        if substring in cmd
    )


# ---------------------------------------------------------------------------
# REQ-HOOKS-001: Hook Command Uses uv run
# ---------------------------------------------------------------------------


def test_command_uses_uv_run(tmp_path):
    # @tests REQ-HOOKS-001
    merged = call_merge_settings(
        tmp_path,
        SRC_SETTINGS,
        "/usr/local/bin/uv",
        "/Users/jane/projects/ace",
    )
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        assert len(commands) >= 1, f"No commands for {event_name}"
        for cmd in commands:
            assert "uv run --project" in cmd, (
                f"Command for {event_name} does not use 'uv run --project': {cmd}"
            )


def test_scn_generated_command_uses_uv_not_python3(tmp_path):
    # @tests SCN-HOOKS-001-01
    merged = call_merge_settings(
        tmp_path,
        SRC_SETTINGS,
        "/Users/jane/.local/bin/uv",
        "/Users/jane/projects/ace",
    )
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        for cmd in commands:
            assert 'python3 "' not in cmd, (
                f"Command still uses bare python3: {cmd}"
            )
            assert "/Users/jane/.local/bin/uv run --project" in cmd


# ---------------------------------------------------------------------------
# REQ-HOOKS-003: Command Format Specification
# ---------------------------------------------------------------------------


def test_command_format_standard_paths(tmp_path):
    # @tests REQ-HOOKS-003
    uv_path = "/Users/jane/.local/bin/uv"
    project_dir = "/Users/jane/projects/ace"
    home = str(tmp_path / "home")

    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, uv_path, project_dir,
    )
    # Check the session_end command format
    commands = extract_commands(merged, "SessionEnd")
    assert len(commands) == 1
    expected_script = os.path.join(home, ".claude", "hooks", "session_end.py")
    expected = f'{uv_path} run --project "{project_dir}" python "{expected_script}"'
    assert commands[0] == expected, f"Got: {commands[0]}\nExpected: {expected}"


def test_command_format_spaces_in_paths(tmp_path):
    # @tests REQ-HOOKS-003
    uv_path = "/usr/local/bin/uv"
    project_dir = "/Users/John Doe/projects/ace"
    home = str(tmp_path / "home")

    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, uv_path, project_dir,
    )
    commands = extract_commands(merged, "PreCompact")
    assert len(commands) == 1
    expected_script = os.path.join(home, ".claude", "hooks", "precompact.py")
    expected = f'{uv_path} run --project "{project_dir}" python "{expected_script}"'
    assert commands[0] == expected, f"Got: {commands[0]}\nExpected: {expected}"


def test_scn_command_format_no_spaces(tmp_path):
    # @tests SCN-HOOKS-003-01
    uv_path = "/Users/jane/.local/bin/uv"
    project_dir = "/Users/jane/projects/ace"
    home = str(tmp_path / "home")

    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, uv_path, project_dir,
    )
    commands = extract_commands(merged, "UserPromptSubmit")
    assert len(commands) == 1
    expected_script = os.path.join(home, ".claude", "hooks", "user_prompt_inject.py")
    expected = f'{uv_path} run --project "{project_dir}" python "{expected_script}"'
    assert commands[0] == expected


def test_scn_command_format_with_spaces(tmp_path):
    # @tests SCN-HOOKS-003-02
    uv_path = "/usr/local/bin/uv"
    project_dir = "/Users/John Doe/projects/ace"
    home = str(tmp_path / "home")

    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, uv_path, project_dir,
    )
    commands = extract_commands(merged, "PreCompact")
    assert len(commands) == 1
    # Both project dir and script path are double-quoted in the command
    assert f'--project "{project_dir}"' in commands[0]
    script_path = os.path.join(home, ".claude", "hooks", "precompact.py")
    assert f'python "{script_path}"' in commands[0]


def test_scn_all_three_hooks_generated(tmp_path):
    # @tests SCN-HOOKS-003-03
    uv_path = "/usr/local/bin/uv"
    project_dir = "/Users/jane/projects/ace"
    home = str(tmp_path / "home")

    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, uv_path, project_dir,
    )
    for event_name, script_name in EVENT_SCRIPT_MAP.items():
        commands = extract_commands(merged, event_name)
        assert len(commands) == 1, (
            f"Expected exactly 1 command for {event_name}, got {len(commands)}"
        )
        expected_script = os.path.join(home, ".claude", "hooks", script_name)
        assert f'python "{expected_script}"' in commands[0]


# ---------------------------------------------------------------------------
# REQ-HOOKS-005: Stale Hook Entry Removal
# ---------------------------------------------------------------------------


def test_remove_bare_python3_stale(tmp_path):
    # @tests REQ-HOOKS-005
    dest = make_settings_with_hooks({
        "SessionEnd": [
            ('python3 "/Users/jane/.claude/hooks/session_end.py"', 120),
        ],
    })
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    commands = extract_commands(merged, "SessionEnd")
    assert len(commands) == 1
    assert "uv run" in commands[0]
    assert 'python3 "' not in commands[0]


def test_remove_venv_python3_stale(tmp_path):
    # @tests REQ-HOOKS-005
    dest = make_settings_with_hooks({
        "PreCompact": [
            ('/Users/jane/.claude/.venv/bin/python3 "/Users/jane/.claude/hooks/precompact.py"', 120),
        ],
    })
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    commands = extract_commands(merged, "PreCompact")
    assert len(commands) == 1
    assert "uv run" in commands[0]
    assert ".venv/bin/python3" not in commands[0]


def test_remove_multiple_stale_same_script(tmp_path):
    # @tests REQ-HOOKS-005
    dest = make_settings_with_hooks({
        "UserPromptSubmit": [
            ('python3 "/Users/jane/.claude/hooks/user_prompt_inject.py"', 10),
            ('/Users/jane/.claude/.venv/bin/python3 "/Users/jane/.claude/hooks/user_prompt_inject.py"', 10),
        ],
    })
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    commands = extract_commands(merged, "UserPromptSubmit")
    assert len(commands) == 1
    assert "uv run" in commands[0]


# ---------------------------------------------------------------------------
# REQ-HOOKS-006: Non-Project Hook Preservation
# ---------------------------------------------------------------------------


def test_preserve_non_project_hooks(tmp_path):
    # @tests REQ-HOOKS-006
    non_project_cmd = 'python3 "/Users/jane/.claude/hooks/document_scanner.py"'
    dest = json.dumps({
        "hooks": {
            "UserPromptSubmit": [
                make_hook_group('python3 "/Users/jane/.claude/hooks/user_prompt_inject.py"', timeout=10),
                make_hook_group(non_project_cmd, timeout=30),
            ],
        }
    }, indent=2)
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    commands = extract_commands(merged, "UserPromptSubmit")
    # Non-project hook preserved, stale project hook replaced
    assert non_project_cmd in commands, (
        f"Non-project hook not preserved: {commands}"
    )
    # The new uv run command should also be present
    uv_commands = [c for c in commands if "uv run" in c]
    assert len(uv_commands) == 1


# ---------------------------------------------------------------------------
# SCN-HOOKS-005-*: Stale Removal Scenarios
# ---------------------------------------------------------------------------


def test_scn_remove_bare_python3_entry(tmp_path):
    # @tests SCN-HOOKS-005-01
    dest = make_settings_with_hooks({
        "SessionEnd": [
            ('python3 "/Users/jane/.claude/hooks/session_end.py"', 120),
        ],
    })
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/Users/jane/.local/bin/uv",
        "/Users/jane/projects/ace", dest,
    )
    commands = extract_commands(merged, "SessionEnd")
    assert len(commands) == 1
    assert "/Users/jane/.local/bin/uv run --project" in commands[0]


def test_scn_remove_venv_python3_entry(tmp_path):
    # @tests SCN-HOOKS-005-02
    dest = make_settings_with_hooks({
        "PreCompact": [
            ('/Users/jane/.claude/.venv/bin/python3 "/Users/jane/.claude/hooks/precompact.py"', 120),
        ],
    })
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    commands = extract_commands(merged, "PreCompact")
    assert len(commands) == 1
    assert "uv run" in commands[0]


def test_scn_remove_multiple_stale_entries(tmp_path):
    # @tests SCN-HOOKS-005-03
    dest = make_settings_with_hooks({
        "UserPromptSubmit": [
            ('python3 "/Users/jane/.claude/hooks/user_prompt_inject.py"', 10),
            ('/Users/jane/.claude/.venv/bin/python3 "/Users/jane/.claude/hooks/user_prompt_inject.py"', 10),
        ],
    })
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    # Exactly one entry for user_prompt_inject after merge
    count = count_project_hooks(merged, "UserPromptSubmit", "user_prompt_inject.py")
    assert count == 1


def test_scn_preserve_non_project_hook(tmp_path):
    # @tests SCN-HOOKS-005-04
    non_project_cmd = 'python3 "/Users/jane/.claude/hooks/document_scanner.py"'
    stale_cmd = 'python3 "/Users/jane/.claude/hooks/user_prompt_inject.py"'
    dest = json.dumps({
        "hooks": {
            "UserPromptSubmit": [
                make_hook_group(stale_cmd, timeout=10),
                make_hook_group(non_project_cmd, timeout=30),
            ],
        }
    }, indent=2)
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    commands = extract_commands(merged, "UserPromptSubmit")
    assert non_project_cmd in commands
    # Stale project hook should be gone
    assert stale_cmd not in commands


def test_scn_idempotent_rerun(tmp_path):
    # @tests SCN-HOOKS-005-05
    uv_path = "/usr/local/bin/uv"
    project_dir = "/Users/jane/projects/ace"

    # First run: fresh install
    merged1 = call_merge_settings(
        tmp_path, SRC_SETTINGS, uv_path, project_dir,
    )
    # Write the result as the "pre-existing" destination for the second run.
    # Use the same tmp_path so HOME resolves identically for both runs.
    home_dir = str(tmp_path / "home")
    dest_settings_path = os.path.join(home_dir, ".claude", "settings.json")
    with open(dest_settings_path, "w") as f:
        json.dump(merged1, f, indent=2)

    # Second run: re-run with the output of the first run as destination.
    # Rewriting the helper.js in the same tmp_path is fine -- call_merge_settings
    # overwrites it each time.
    merged2 = call_merge_settings(
        tmp_path, SRC_SETTINGS, uv_path, project_dir,
        dest_settings_content=json.dumps(merged1, indent=2),
    )

    # The hooks section should be identical
    assert merged1["hooks"] == merged2["hooks"], (
        "Idempotency violated: second run produced different hooks"
    )


# ---------------------------------------------------------------------------
# INV-HOOKS-001: Exactly One Project Hook Per Event Type
# ---------------------------------------------------------------------------


def test_invariant_exactly_one_hook_per_event(tmp_path):
    # @tests-invariant INV-HOOKS-001
    # Start with multiple stale entries across all event types
    dest = make_settings_with_hooks({
        "UserPromptSubmit": [
            ('python3 "/x/.claude/hooks/user_prompt_inject.py"', 10),
            ('/y/.venv/bin/python3 "/z/.claude/hooks/user_prompt_inject.py"', 10),
        ],
        "SessionEnd": [
            ('python3 "/x/.claude/hooks/session_end.py"', 120),
        ],
        "PreCompact": [
            ('python3 "/x/.claude/hooks/precompact.py"', 120),
            ('/y/.venv/bin/python3 "/z/.claude/hooks/precompact.py"', 120),
        ],
    })
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    for event_name, script_name in EVENT_SCRIPT_MAP.items():
        count = count_project_hooks(merged, event_name, script_name)
        assert count == 1, (
            f"INV-HOOKS-001 violated: {event_name} has {count} entries for {script_name}"
        )


# ---------------------------------------------------------------------------
# INV-HOOKS-002: Non-Project Hooks Are Never Modified
# ---------------------------------------------------------------------------


def test_invariant_non_project_hooks_never_modified(tmp_path):
    # @tests-invariant INV-HOOKS-002
    non_project_hooks = {
        "UserPromptSubmit": [
            make_hook_group('python3 "/Users/jane/.claude/hooks/document_scanner.py"', timeout=30),
        ],
        "SessionEnd": [
            make_hook_group('/usr/bin/my-tool --flag', timeout=60),
        ],
    }
    dest = json.dumps({"hooks": non_project_hooks}, indent=2)
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    # All non-project hooks must still be present, unchanged
    user_cmds = extract_commands(merged, "UserPromptSubmit")
    assert 'python3 "/Users/jane/.claude/hooks/document_scanner.py"' in user_cmds
    session_cmds = extract_commands(merged, "SessionEnd")
    assert '/usr/bin/my-tool --flag' in session_cmds


# ---------------------------------------------------------------------------
# INV-HOOKS-003: All Paths Are Absolute
# ---------------------------------------------------------------------------


def test_invariant_all_paths_absolute(tmp_path):
    # @tests-invariant INV-HOOKS-003
    uv_path = "/opt/homebrew/bin/uv"
    project_dir = "/Users/jane/projects/ace"
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, uv_path, project_dir,
    )
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        for cmd in commands:
            # The command starts with the absolute uv path
            assert cmd.startswith("/"), (
                f"Command does not start with absolute path: {cmd}"
            )
            # Check that --project arg is absolute (inside double quotes)
            import re
            project_match = re.search(r'--project "([^"]+)"', cmd)
            assert project_match, f"No --project arg found in: {cmd}"
            assert project_match.group(1).startswith("/"), (
                f"Project dir is not absolute: {project_match.group(1)}"
            )
            # Check that script path is absolute (inside double quotes after python)
            script_match = re.search(r'python "([^"]+)"', cmd)
            assert script_match, f"No script path found in: {cmd}"
            assert script_match.group(1).startswith("/"), (
                f"Script path is not absolute: {script_match.group(1)}"
            )


# ---------------------------------------------------------------------------
# INV-HOOKS-005: Non-Hook Settings Preserved
# ---------------------------------------------------------------------------


def test_invariant_non_hook_settings_preserved(tmp_path):
    # @tests-invariant INV-HOOKS-005
    dest = json.dumps({
        "enabledPlugins": ["some-plugin"],
        "customSetting": True,
        "hooks": {},
    }, indent=2)
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    assert merged["enabledPlugins"] == ["some-plugin"]
    assert merged["customSetting"] is True
    # The source settings.json has playbook keys; they should NOT overwrite existing
    # dest values, but they CAN be added if not present in dest.


# ---------------------------------------------------------------------------
# INV-HOOKS-006: Hook Timeouts Unchanged
# ---------------------------------------------------------------------------


def test_invariant_hook_timeouts_correct(tmp_path):
    # @tests-invariant INV-HOOKS-006
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj",
    )
    for event_name, expected_timeout in EVENT_TIMEOUT_MAP.items():
        groups = merged.get("hooks", {}).get(event_name, [])
        assert len(groups) >= 1, f"No hook groups for {event_name}"
        for group in groups:
            for hook in group.get("hooks", []):
                assert hook["timeout"] == expected_timeout, (
                    f"Timeout mismatch for {event_name}: "
                    f"expected {expected_timeout}, got {hook['timeout']}"
                )


# ---------------------------------------------------------------------------
# INV-HOOKS-007: Generated JSON Is Valid
# ---------------------------------------------------------------------------


def test_invariant_output_is_valid_json(tmp_path):
    # @tests-invariant INV-HOOKS-007
    # Use a path with spaces AND double quotes to stress JSON escaping.
    # The command strings contain double-quoted paths (e.g., python "/path/my project/...")
    # which must be properly escaped as \" in the JSON serialization.
    result = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/home/user/bin/uv", "/proj/my project",
    )

    # Verify round-trip integrity
    serialized = json.dumps(result)
    reparsed = json.loads(serialized)
    assert reparsed == result, "Round-trip through json.dumps/json.loads failed"

    # Verify that the command strings contain properly quoted paths.
    # The project dir with spaces should appear inside double quotes in the command.
    commands = extract_commands(result, "SessionEnd")
    assert len(commands) == 1
    cmd = commands[0]
    # The command should contain the project dir in double quotes
    assert '"/proj/my project"' in cmd, (
        f"Project path with spaces not properly quoted in command: {cmd}"
    )
    # When we JSON-serialize the command string, the inner double quotes
    # must be escaped as \"
    cmd_json = json.dumps(cmd)
    assert r'\"' in cmd_json, (
        f"Double quotes in command not properly JSON-escaped: {cmd_json}"
    )


# ---------------------------------------------------------------------------
# REQ-HOOKS-008: Absolute uv Path Resolution
# ---------------------------------------------------------------------------


def test_absolute_uv_path_embedded(tmp_path):
    # @tests REQ-HOOKS-008
    uv_path = "/Users/jane/.local/bin/uv"
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, uv_path, "/proj",
    )
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        for cmd in commands:
            assert cmd.startswith(uv_path + " "), (
                f"Command does not start with absolute uv path: {cmd}"
            )
            # Must NOT start with bare "uv "
            assert not cmd.startswith("uv "), (
                f"Command uses bare 'uv' instead of absolute path: {cmd}"
            )


def test_scn_uv_path_trimmed(tmp_path):
    # @tests SCN-HOOKS-008-01
    # SCN-HOOKS-008-01 is about install()'s `execSync('which uv').toString().trim()`
    # call. Since mergeSettings takes the already-trimmed path, we test the full
    # install() function via subprocess with a fake `uv` whose `which` output
    # contains a trailing newline (as real `which` does). We then verify the
    # resulting settings.json command uses the trimmed path with no trailing
    # whitespace.
    home_dir = str(tmp_path / "home")
    claude_dir = os.path.join(home_dir, ".claude")
    hooks_dir = os.path.join(claude_dir, "hooks")
    bin_dir = str(tmp_path / "bin")

    os.makedirs(hooks_dir, exist_ok=True)
    os.makedirs(bin_dir, exist_ok=True)

    # Create a fake uv script. `which uv` will return the absolute path
    # with a trailing newline (this is normal `which` behavior). The install.js
    # code calls .trim() to remove it. We verify the generated command uses the
    # trimmed path.
    fake_uv = os.path.join(bin_dir, "uv")
    with open(fake_uv, "w") as f:
        f.write("#!/bin/bash\n")
        f.write('if [[ "$1" == "sync" ]]; then exit 0; fi\n')
        f.write("exit 0\n")
    os.chmod(fake_uv, 0o755)

    env = os.environ.copy()
    env["HOME"] = home_dir
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")

    result = subprocess.run(
        ["node", INSTALL_JS],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    settings_path = os.path.join(claude_dir, "settings.json")
    with open(settings_path) as f:
        settings = json.load(f)

    # The generated commands must start with the exact trimmed uv path
    # (no trailing newline or whitespace)
    for event_name in EVENT_SCRIPT_MAP:
        for group in settings.get("hooks", {}).get(event_name, []):
            for hook in group.get("hooks", []):
                cmd = hook["command"]
                # Must start with the absolute path to our fake uv (trimmed)
                assert cmd.startswith(fake_uv + " run --project"), (
                    f"Command does not start with trimmed uv path '{fake_uv}': {cmd}"
                )
                # Must NOT contain a newline anywhere
                assert "\n" not in cmd, f"Command contains newline: {repr(cmd)}"
                # Must NOT start with whitespace after the uv path
                after_uv = cmd[len(fake_uv):]
                assert after_uv.startswith(" run"), (
                    f"Unexpected whitespace between uv path and 'run': {repr(after_uv)}"
                )


def test_scn_uv_homebrew_path(tmp_path):
    # @tests SCN-HOOKS-008-02
    uv_path = "/opt/homebrew/bin/uv"
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, uv_path, "/proj",
    )
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        assert all(
            cmd.startswith("/opt/homebrew/bin/uv run --project") for cmd in commands
        )


# ---------------------------------------------------------------------------
# Adversarial: TC-INVAL-* Invalid Input Tests
# ---------------------------------------------------------------------------


def test_adversarial_malformed_json_dest(tmp_path):
    # @tests REQ-HOOKS-005 (TC-INVAL-001)
    # Destination settings.json is invalid JSON
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj",
        dest_settings_content="this is { not valid json !!!",
    )
    # mergeSettings should handle gracefully -- treat as empty and add new hooks
    assert "hooks" in merged
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        assert len(commands) >= 1


def test_adversarial_missing_hooks_key(tmp_path):
    # @tests REQ-HOOKS-005 (TC-INVAL-002)
    dest = json.dumps({"someOtherKey": "value"}, indent=2)
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    assert "hooks" in merged
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        assert len(commands) >= 1


def test_adversarial_null_hooks(tmp_path):
    # @tests REQ-HOOKS-005 (TC-INVAL-003)
    dest = json.dumps({"hooks": None}, indent=2)
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    assert "hooks" in merged
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        assert len(commands) >= 1


def test_adversarial_empty_hooks(tmp_path):
    # @tests REQ-HOOKS-005 (TC-INVAL-004)
    dest = json.dumps({"hooks": {}}, indent=2)
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    assert "hooks" in merged
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        assert len(commands) >= 1


def test_adversarial_hook_group_missing_hooks_array(tmp_path):
    # @tests REQ-HOOKS-005 (TC-INVAL-005)
    # A hook group object that lacks the `hooks` array property.
    # The implementation calls group.hooks.filter() which throws if hooks is
    # undefined. This is acceptable behavior for malformed input -- the test
    # documents the behavior: mergeSettings either handles it gracefully or
    # throws an error.
    dest = json.dumps({
        "hooks": {
            "SessionEnd": [
                {"type": "command"}  # missing "hooks" array
            ],
        }
    }, indent=2)
    try:
        merged = call_merge_settings(
            tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
        )
        # If it succeeds, verify hooks are still added
        commands = extract_commands(merged, "SessionEnd")
        assert len(commands) >= 1
        assert "uv run" in commands[0]
    except RuntimeError as exc:
        # Implementation throws TypeError for malformed input -- acceptable
        assert "filter" in str(exc) or "Cannot read" in str(exc), (
            f"Unexpected error: {exc}"
        )


def test_adversarial_hook_entry_missing_command(tmp_path):
    # @tests REQ-HOOKS-005 (TC-INVAL-006)
    # A hook entry without a `command` field
    dest = json.dumps({
        "hooks": {
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {"type": "command", "timeout": 10}  # missing command
                    ]
                }
            ],
        }
    }, indent=2)
    # This may error since hook.command.includes() will fail on undefined
    # The test documents the behavior
    try:
        merged = call_merge_settings(
            tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
        )
        # If it succeeds, verify hooks are still added correctly
        commands = extract_commands(merged, "UserPromptSubmit")
        assert len(commands) >= 1, (
            "mergeSettings succeeded but produced no hooks for UserPromptSubmit"
        )
        # The new uv run command should be present
        uv_commands = [c for c in commands if "uv run" in c]
        assert len(uv_commands) >= 1, (
            "mergeSettings succeeded but no uv run command was added"
        )
    except RuntimeError as exc:
        # mergeSettings may throw TypeError because hook.command is undefined
        # and calling .includes() on undefined fails. This is acceptable for
        # malformed input, but we assert the error is specifically about the
        # missing command field (not an unrelated crash).
        error_msg = str(exc)
        assert (
            "includes" in error_msg
            or "Cannot read" in error_msg
            or "undefined" in error_msg
        ), f"Unexpected error for missing-command input: {exc}"


def test_adversarial_fresh_install_no_prior_settings(tmp_path):
    # @tests REQ-HOOKS-005 (TC-BOUND-001, TC-BOUND-002)
    # No pre-existing settings.json at all
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj",
    )
    assert "hooks" in merged
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        assert len(commands) == 1
        assert "uv run" in commands[0]


def test_adversarial_empty_hook_arrays(tmp_path):
    # @tests REQ-HOOKS-005 (TC-BOUND-003)
    dest = json.dumps({
        "hooks": {
            "SessionEnd": [],
            "UserPromptSubmit": [],
            "PreCompact": [],
        }
    }, indent=2)
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        assert len(commands) == 1
        assert "uv run" in commands[0]


def test_adversarial_stale_across_all_event_types(tmp_path):
    # @tests REQ-HOOKS-005 (TC-STALE-006)
    dest = make_settings_with_hooks({
        "UserPromptSubmit": [
            ('python3 "/old/.claude/hooks/user_prompt_inject.py"', 10),
        ],
        "SessionEnd": [
            ('/old/.venv/bin/python3 "/old/.claude/hooks/session_end.py"', 120),
        ],
        "PreCompact": [
            ('python3 "/old/.claude/hooks/precompact.py"', 120),
        ],
    })
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    for event_name in EVENT_SCRIPT_MAP:
        commands = extract_commands(merged, event_name)
        assert len(commands) == 1
        assert "uv run" in commands[0]
        assert "python3" not in commands[0].split("python")[0]  # no python3 prefix


def test_adversarial_non_project_hooks_only(tmp_path):
    # @tests REQ-HOOKS-006 (TC-STALE-007)
    dest = json.dumps({
        "hooks": {
            "UserPromptSubmit": [
                make_hook_group('python3 "/Users/jane/.claude/hooks/document_scanner.py"', timeout=30),
                make_hook_group('bash "/Users/jane/.claude/hooks/git_scanner.sh"', timeout=20),
            ],
        }
    }, indent=2)
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    commands = extract_commands(merged, "UserPromptSubmit")
    # Both non-project hooks preserved, plus the new project hook
    assert 'python3 "/Users/jane/.claude/hooks/document_scanner.py"' in commands
    assert 'bash "/Users/jane/.claude/hooks/git_scanner.sh"' in commands
    uv_commands = [c for c in commands if "uv run" in c]
    assert len(uv_commands) == 1


def test_adversarial_pre_existing_non_hook_settings_preserved(tmp_path):
    # @tests INV-HOOKS-005 (TC-BOUND-007)
    dest = json.dumps({
        "enabledPlugins": ["plugin-a", "plugin-b"],
        "document_scanning_enabled": True,
        "git_scanning_enabled": False,
        "customKey": {"nested": "value"},
        "hooks": {},
    }, indent=2)
    merged = call_merge_settings(
        tmp_path, SRC_SETTINGS, "/usr/local/bin/uv", "/proj", dest,
    )
    assert merged["enabledPlugins"] == ["plugin-a", "plugin-b"]
    assert merged["document_scanning_enabled"] is True
    assert merged["git_scanning_enabled"] is False
    assert merged["customKey"] == {"nested": "value"}


# ---------------------------------------------------------------------------
# Subprocess Helper for install() tests
# ---------------------------------------------------------------------------


def _setup_install_env(tmp_path, *, fake_uv_sync_exit=0, include_uv=True,
                       pre_existing_settings=None):
    """
    Set up a temp environment to run `node install.js` as a subprocess.

    Args:
        tmp_path: pytest tmp_path fixture
        fake_uv_sync_exit: exit code for fake uv sync (0=success)
        include_uv: if False, PATH will not include a uv binary
        pre_existing_settings: optional string content for settings.json

    Returns:
        (env_dict, home_dir, settings_path, bin_dir)
    """
    home_dir = str(tmp_path / "home")
    claude_dir = os.path.join(home_dir, ".claude")
    hooks_dir = os.path.join(claude_dir, "hooks")
    settings_path = os.path.join(claude_dir, "settings.json")
    bin_dir = str(tmp_path / "bin")

    os.makedirs(hooks_dir, exist_ok=True)
    os.makedirs(bin_dir, exist_ok=True)

    if pre_existing_settings is not None:
        with open(settings_path, "w") as f:
            f.write(pre_existing_settings)

    env = os.environ.copy()
    env["HOME"] = home_dir
    if platform.system() == "Windows":
        env["USERPROFILE"] = home_dir

    if include_uv:
        # Create fake uv binary
        fake_uv = os.path.join(bin_dir, "uv")
        with open(fake_uv, "w") as f:
            f.write("#!/bin/bash\n")
            f.write(f'if [[ "$1" == "sync" ]]; then exit {fake_uv_sync_exit}; fi\n')
            f.write("exit 0\n")
        os.chmod(fake_uv, 0o755)
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    else:
        # PATH with NO uv: just the directory containing node + system dirs
        _node_bin = shutil.which("node")
        _node_dir = os.path.dirname(_node_bin) if _node_bin else "/usr/local/bin"
        env["PATH"] = os.pathsep.join([_node_dir, "/usr/bin", "/bin"])

    return env, home_dir, settings_path, bin_dir


def _run_install(env, timeout=30):
    """Run node install.js with the given environment and return the result."""
    return subprocess.run(
        ["node", INSTALL_JS],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# REQ-HOOKS-007: uv Not Found Error Handling (Subprocess Tests)
# ---------------------------------------------------------------------------


def test_uv_not_found_exits_nonzero(tmp_path):
    # @tests REQ-HOOKS-007
    # Run node install.js via subprocess with no uv on PATH, check exit code 1
    env, home_dir, settings_path, _ = _setup_install_env(
        tmp_path, include_uv=False,
    )
    result = _run_install(env)
    assert result.returncode == 1, (
        f"Expected exit code 1 when uv not found, got {result.returncode}"
    )


def test_uv_not_found_stderr_message(tmp_path):
    # @tests REQ-HOOKS-007
    # Run node install.js via subprocess with no uv on PATH,
    # check exact stderr contains the full error message from REQ-HOOKS-007
    env, home_dir, settings_path, _ = _setup_install_env(
        tmp_path, include_uv=False,
    )
    result = _run_install(env)
    assert result.returncode == 1

    # REQ-HOOKS-007 specifies the EXACT error message (both lines)
    expected_line1 = (
        "Error: 'uv' is not installed or not found on PATH. "
        "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    )
    expected_line2 = (
        "See https://docs.astral.sh/uv/getting-started/installation/ for other methods."
    )
    assert expected_line1 in result.stderr, (
        f"Missing first line of error message.\nExpected: {expected_line1}\nGot stderr: {result.stderr}"
    )
    assert expected_line2 in result.stderr, (
        f"Missing second line of error message.\nExpected: {expected_line2}\nGot stderr: {result.stderr}"
    )


def test_scn_uv_not_installed_error(tmp_path):
    # @tests SCN-HOOKS-007-01
    # Exact error text, exit code 1, no files modified
    pre_settings = json.dumps({"existing": "untouched"}, indent=2)
    env, home_dir, settings_path, _ = _setup_install_env(
        tmp_path, include_uv=False, pre_existing_settings=pre_settings,
    )
    result = _run_install(env)

    # Exit code 1
    assert result.returncode == 1

    # Exact error text per SCN-HOOKS-007-01
    assert "Error: 'uv' is not installed or not found on PATH" in result.stderr
    assert "curl -LsSf https://astral.sh/uv/install.sh | sh" in result.stderr
    assert "https://docs.astral.sh/uv/getting-started/installation/" in result.stderr

    # No files modified
    with open(settings_path) as f:
        content = json.load(f)
    assert content == {"existing": "untouched"}, (
        "settings.json was modified despite uv-not-found error"
    )


def test_scn_uv_check_before_file_operations(tmp_path):
    # @tests SCN-HOOKS-007-02
    # Run without uv, verify settings.json UNCHANGED
    pre_settings = json.dumps({"hooks": {"SessionEnd": []}}, indent=2)
    env, home_dir, settings_path, _ = _setup_install_env(
        tmp_path, include_uv=False, pre_existing_settings=pre_settings,
    )

    # Record the byte content before
    with open(settings_path, "rb") as f:
        before_bytes = f.read()

    result = _run_install(env)
    assert result.returncode == 1

    # settings.json byte-for-byte identical after failed install
    with open(settings_path, "rb") as f:
        after_bytes = f.read()
    assert before_bytes == after_bytes, (
        "settings.json was modified despite uv check failing before file operations"
    )

    # No new files in ~/.claude/hooks/
    hooks_dir = os.path.join(home_dir, ".claude", "hooks")
    hook_files = os.listdir(hooks_dir)
    assert len(hook_files) == 0, (
        f"Files were copied to hooks dir despite uv-not-found: {hook_files}"
    )


def test_invariant_no_file_modification_on_uv_not_found(tmp_path):
    # @tests-invariant INV-HOOKS-004
    # settings.json byte-for-byte identical after failed install (uv not found)
    pre_settings = json.dumps({
        "hooks": {"SessionEnd": [{"hooks": [{"type": "command",
                   "command": "keep me", "timeout": 120}]}]},
        "customKey": True,
    }, indent=2)
    env, home_dir, settings_path, _ = _setup_install_env(
        tmp_path, include_uv=False, pre_existing_settings=pre_settings,
    )

    with open(settings_path, "rb") as f:
        before_bytes = f.read()

    result = _run_install(env)
    assert result.returncode == 1

    with open(settings_path, "rb") as f:
        after_bytes = f.read()
    assert before_bytes == after_bytes, (
        "INV-HOOKS-004 violated: settings.json modified when uv not found"
    )


# ---------------------------------------------------------------------------
# REQ-HOOKS-009: Pre-Install Dependency Sync (Subprocess Tests)
# ---------------------------------------------------------------------------


def test_uv_sync_runs_before_file_ops(tmp_path):
    # @tests REQ-HOOKS-009
    # Fake uv sync succeeds; verify install continues and produces settings
    env, home_dir, settings_path, _ = _setup_install_env(
        tmp_path, fake_uv_sync_exit=0,
    )
    result = _run_install(env)
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    # settings.json should exist and have hooks
    assert os.path.exists(settings_path), "settings.json was not created"
    with open(settings_path) as f:
        settings = json.load(f)
    assert "hooks" in settings
    for event_name in EVENT_SCRIPT_MAP:
        assert event_name in settings["hooks"], (
            f"Missing event type {event_name} after successful uv sync"
        )


def test_uv_sync_failure_aborts(tmp_path):
    # @tests REQ-HOOKS-009
    # Fake uv sync fails; verify exit code 1
    pre_settings = json.dumps({"existing": "value"}, indent=2)
    env, home_dir, settings_path, _ = _setup_install_env(
        tmp_path, fake_uv_sync_exit=2, pre_existing_settings=pre_settings,
    )
    result = _run_install(env)
    assert result.returncode == 1, (
        f"Expected exit code 1 when uv sync fails, got {result.returncode}"
    )

    # Settings should not be modified
    with open(settings_path) as f:
        content = json.load(f)
    assert content == {"existing": "value"}, (
        "settings.json was modified despite uv sync failure"
    )


def test_scn_uv_sync_succeeds(tmp_path):
    # @tests SCN-HOOKS-009-01
    # uv sync exits 0, install continues, file is written
    env, home_dir, settings_path, _ = _setup_install_env(
        tmp_path, fake_uv_sync_exit=0,
    )
    result = _run_install(env)
    assert result.returncode == 0, f"Install failed: {result.stderr}"

    # settings.json should be written with hook entries
    assert os.path.exists(settings_path)
    with open(settings_path) as f:
        settings = json.load(f)

    # All three hooks present
    for event_name, script_name in EVENT_SCRIPT_MAP.items():
        commands = []
        for group in settings.get("hooks", {}).get(event_name, []):
            for hook in group.get("hooks", []):
                commands.append(hook.get("command", ""))
        assert len(commands) == 1, (
            f"Expected 1 command for {event_name}, got {len(commands)}"
        )
        assert "uv run --project" in commands[0]
        assert script_name in commands[0]


def test_scn_uv_sync_fails_with_error_message(tmp_path):
    # @tests SCN-HOOKS-009-02
    # uv sync exits non-zero; stderr includes "uv sync failed", exit code value,
    # and the "Try running manually" suggestion
    env, home_dir, settings_path, _ = _setup_install_env(
        tmp_path, fake_uv_sync_exit=2,
    )
    result = _run_install(env)
    assert result.returncode == 1

    stderr = result.stderr
    # Must mention uv sync failure
    assert "uv sync failed" in stderr, (
        f"Error message should contain 'uv sync failed': {stderr}"
    )
    # Must include the exit code
    assert "exit code 2" in stderr or "exit code: 2" in stderr, (
        f"Error message should include exit code: {stderr}"
    )
    # Must include the manual run suggestion
    assert "Try running manually" in stderr, (
        f"Error message should suggest manual run: {stderr}"
    )
    assert "uv sync --project" in stderr, (
        f"Error message should include uv sync --project command: {stderr}"
    )


def test_invariant_no_file_modification_on_uv_sync_failure(tmp_path):
    # @tests-invariant INV-HOOKS-004
    # settings.json UNCHANGED when uv sync fails
    pre_settings = json.dumps({
        "hooks": {"PreCompact": [{"hooks": [{"type": "command",
                   "command": "original", "timeout": 120}]}]},
    }, indent=2)
    env, home_dir, settings_path, _ = _setup_install_env(
        tmp_path, fake_uv_sync_exit=2, pre_existing_settings=pre_settings,
    )

    with open(settings_path, "rb") as f:
        before_bytes = f.read()

    result = _run_install(env)
    assert result.returncode == 1

    with open(settings_path, "rb") as f:
        after_bytes = f.read()
    assert before_bytes == after_bytes, (
        "INV-HOOKS-004 violated: settings.json modified when uv sync failed"
    )


# ---------------------------------------------------------------------------
# REQ-HOOKS-002: Anthropic Package Available (Conditional Integration Test)
# ---------------------------------------------------------------------------


def test_scn_anthropic_import_via_uv_run(tmp_path):
    # @tests SCN-HOOKS-002-01
    # Run `uv run --project <project> python -c "import anthropic"`.
    # This test is conditional: it only runs if real `uv` is available.
    uv_path = shutil.which("uv")
    if uv_path is None:
        pytest.skip("uv is not available on this system (conditional test)")

    # Run uv run with the project's pyproject.toml
    result = subprocess.run(
        [uv_path, "run", "--project", PROJECT_ROOT,
         "python", "-c", "import anthropic; print(anthropic.__version__)"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Failed to import anthropic via uv run: {result.stderr}"
    )
    # Should print a version string
    version = result.stdout.strip()
    assert len(version) > 0, "No version output from anthropic import"
    # Basic version format check (e.g., "0.83.0")
    assert "." in version, f"Unexpected version format: {version}"
