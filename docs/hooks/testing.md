# Test Strategy: Hook Dependency Management (install.js)

## Coverage Targets
- Line coverage: >= 80% (of testable `install.js` logic: `mergeSettings`, stale detection, command generation, error paths)
- Branch coverage: >= 70%
- All REQ-HOOKS-* (001-009) covered by both white-box and contract tests
- All SCN-HOOKS-* covered by white-box tests
- All INV-HOOKS-* covered by white-box invariant tests
- Contract test coverage: every REQ-HOOKS-* must have a contract test OR a documented justification in "Contract Test Exclusions" below

## Language Decision: Python (Option B)

The existing test suite uses Python with pytest (`tests/test_*_whitebox.py`, `tests/test_*_contract.py`). All four existing modules (scoring, sections, curator, retry) follow this convention. To maintain consistency:

- **White-box tests** (`tests/test_hooks_whitebox.py`): Import and exercise `mergeSettings()` by writing temp files and calling `node install.js` fragments via `subprocess`. Also directly manipulate JSON to test merge logic in isolation.
- **Contract tests** (`tests/test_hooks_contract.py`): Run `node install.js` as a subprocess in a controlled temp directory, then verify the resulting `settings.json` content. This is the "deliverable test" -- it exercises the installer the way a user would.

### Why Python, Not JavaScript

1. Consistency with existing 8 test files (all Python/pytest).
2. `pytest` fixtures (`tmp_path`, `monkeypatch`) provide excellent temp directory and environment management.
3. Subprocess invocation (`subprocess.run(["node", "install.js"], ...)`) is the natural way to test a CLI tool from the outside.
4. The project's `pyproject.toml` already declares `pytest>=9.0.2` as a dev dependency.

## Intent Traceability

Success criteria from spec.md traceability matrix, mapped to test functions.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* | Test Type | Test Function |
|------|-------------------|-------------------|-----------|---------------|
| SC-HOOKS-001 | Hook commands use `uv run --project` | REQ-HOOKS-001 | White-box | test_command_uses_uv_run |
| SC-HOOKS-001 | (same) | REQ-HOOKS-001 | Contract | test_contract_commands_use_uv_run |
| SC-HOOKS-001 | (same) | SCN-HOOKS-001-01 | White-box | test_scn_generated_command_uses_uv_not_python3 |
| SC-HOOKS-002 | `import anthropic` succeeds under uv run | REQ-HOOKS-002 | White-box | test_anthropic_import_succeeds (integration; may require real uv) |
| SC-HOOKS-002 | (same) | REQ-HOOKS-002 | Contract | (see Contract Test Exclusions) |
| SC-HOOKS-002 | (same) | SCN-HOOKS-002-01 | White-box | test_scn_anthropic_import_via_uv_run |
| SC-HOOKS-003 | Command format: `<abs_uv> run --project "<abs_dir>" python "<abs_script>"` | REQ-HOOKS-003 | White-box | test_command_format_standard_paths, test_command_format_spaces_in_paths |
| SC-HOOKS-003 | (same) | REQ-HOOKS-003 | Contract | test_contract_command_format |
| SC-HOOKS-003 | (same) | SCN-HOOKS-003-01 | White-box | test_scn_command_format_no_spaces |
| SC-HOOKS-003 | (same) | SCN-HOOKS-003-02 | White-box | test_scn_command_format_with_spaces |
| SC-HOOKS-003 | (same) | SCN-HOOKS-003-03 | White-box | test_scn_all_three_hooks_generated |
| SC-HOOKS-003 | (same) | INV-HOOKS-003 | White-box | test_invariant_all_paths_absolute |
| SC-HOOKS-004 | End-to-end hook functionality | REQ-HOOKS-004 | White-box | (see Contract Test Exclusions -- integration-level, depends on API key) |
| SC-HOOKS-004 | (same) | REQ-HOOKS-004 | Contract | (see Contract Test Exclusions) |
| SC-HOOKS-004 | (same) | SCN-HOOKS-004-01 | White-box | (see Contract Test Exclusions) |
| SC-HOOKS-005 | Stale hook entry removal | REQ-HOOKS-005 | White-box | test_remove_bare_python3_stale, test_remove_venv_python3_stale, test_remove_multiple_stale_same_script |
| SC-HOOKS-005 | (same) | REQ-HOOKS-005 | Contract | test_contract_stale_entries_removed |
| SC-HOOKS-005 | (same) | REQ-HOOKS-006 | White-box | test_preserve_non_project_hooks |
| SC-HOOKS-005 | (same) | REQ-HOOKS-006 | Contract | test_contract_non_project_hooks_preserved |
| SC-HOOKS-005 | (same) | INV-HOOKS-001 | White-box | test_invariant_exactly_one_hook_per_event |
| SC-HOOKS-005 | (same) | INV-HOOKS-002 | White-box | test_invariant_non_project_hooks_never_modified |
| SC-HOOKS-005 | (same) | SCN-HOOKS-005-01 | White-box | test_scn_remove_bare_python3_entry |
| SC-HOOKS-005 | (same) | SCN-HOOKS-005-02 | White-box | test_scn_remove_venv_python3_entry |
| SC-HOOKS-005 | (same) | SCN-HOOKS-005-03 | White-box | test_scn_remove_multiple_stale_entries |
| SC-HOOKS-005 | (same) | SCN-HOOKS-005-04 | White-box | test_scn_preserve_non_project_hook |
| SC-HOOKS-005 | (same) | SCN-HOOKS-005-05 | White-box | test_scn_idempotent_rerun |
| SC-HOOKS-006 | uv not found error | REQ-HOOKS-007 | White-box | test_uv_not_found_exits_nonzero, test_uv_not_found_stderr_message |
| SC-HOOKS-006 | (same) | REQ-HOOKS-007 | Contract | test_contract_uv_not_found_error |
| SC-HOOKS-006 | (same) | SCN-HOOKS-007-01 | White-box | test_scn_uv_not_installed_error |
| SC-HOOKS-006 | (same) | SCN-HOOKS-007-02 | White-box | test_scn_uv_check_before_file_operations |
| SC-HOOKS-006 | (same) | INV-HOOKS-004 | White-box | test_invariant_no_file_modification_on_uv_not_found |
| SC-HOOKS-007 | Absolute uv path resolution | REQ-HOOKS-008 | White-box | test_absolute_uv_path_embedded |
| SC-HOOKS-007 | (same) | REQ-HOOKS-008 | Contract | test_contract_absolute_uv_path |
| SC-HOOKS-007 | (same) | SCN-HOOKS-008-01 | White-box | test_scn_uv_path_trimmed |
| SC-HOOKS-007 | (same) | SCN-HOOKS-008-02 | White-box | test_scn_uv_homebrew_path |
| SC-HOOKS-008 | Pre-install dependency sync | REQ-HOOKS-009 | White-box | test_uv_sync_runs_before_file_ops, test_uv_sync_failure_aborts |
| SC-HOOKS-008 | (same) | REQ-HOOKS-009 | Contract | test_contract_uv_sync_failure_aborts |
| SC-HOOKS-008 | (same) | SCN-HOOKS-009-01 | White-box | test_scn_uv_sync_succeeds |
| SC-HOOKS-008 | (same) | SCN-HOOKS-009-02 | White-box | test_scn_uv_sync_fails_with_error_message |
| SC-HOOKS-008 | (same) | INV-HOOKS-004 | White-box | test_invariant_no_file_modification_on_uv_sync_failure |
| SC-HOOKS-009 | Valid JSON output | INV-HOOKS-007 | White-box | test_invariant_output_is_valid_json |
| SC-HOOKS-009 | (same) | INV-HOOKS-007 | Contract | test_contract_output_is_valid_json |
| (invariant) | Non-hook settings preserved | INV-HOOKS-005 | White-box | test_invariant_non_hook_settings_preserved |
| (invariant) | Hook timeouts unchanged | INV-HOOKS-006 | White-box | test_invariant_hook_timeouts_correct |

## Mocking Strategy

### Overview

`install.js` has two categories of external dependencies:
1. **External process calls** (`child_process.execSync`): `which uv` and `uv sync`
2. **File system I/O**: reads/writes `~/.claude/settings.json`, copies files to `~/.claude/hooks/`

### External Dependencies

| Dependency | Mock Approach | Testability Hook |
|------------|---------------|------------------|
| `which uv` (via `child_process.execSync`) | For white-box tests of `mergeSettings()`: not needed (mergeSettings takes `absUvPath` as a parameter). For contract tests of `install()`: create a wrapper shell script or use PATH manipulation to provide a fake `uv` binary. | `mergeSettings(srcSettingsPath, absUvPath, projectDir)` accepts the resolved uv path as a parameter, decoupling it from subprocess calls. |
| `uv sync` (via `child_process.execSync`) | For contract tests: provide a fake `uv` script in a temp directory that exits 0 (success) or non-zero (failure). Prepend the temp directory to PATH so `which uv` resolves there. | The `install()` function runs `uv sync` using the resolved absolute path. A fake `uv` script at that path controls the behavior. |
| File system (`~/.claude/settings.json`) | For white-box `mergeSettings()` tests: create temp `src/settings.json` and temp `~/.claude/settings.json`, pass paths directly. For contract `install()` tests: set `HOME` env var to a temp directory so `os.homedir()` returns it. Alternatively, if `install.js` is modified to accept a dest dir, pass that. | `mergeSettings()` reads from `srcSettingsPath` (parameter) and from the global `settingsPath` (derived from `os.homedir()`). White-box tests can call mergeSettings directly with temp paths. Contract tests must override HOME. |
| File system (`~/.claude/hooks/`) | Same HOME override as above. The temp HOME directory receives copied hook files. | `copyDir()` copies to `path.join(os.homedir(), '.claude')`. Overriding HOME redirects all file operations. |
| `process.exit(1)` | Cannot mock from Python. For contract tests: run `node install.js` via `subprocess.run()`, check return code. For white-box tests of `mergeSettings()`: not applicable (mergeSettings does not call process.exit). | `subprocess.run()` captures exit code naturally. |

### Detailed Mocking Approach: Fake `uv` Script

For contract tests that run `node install.js` as a subprocess, we need to control what `which uv` and `uv sync` do. The approach:

1. Create a temp directory (e.g., `/tmp/test_xxx/bin/`).
2. Write a shell script `uv` to that directory:
   ```bash
   #!/bin/bash
   if [[ "$1" == "sync" ]]; then
     exit 0  # or exit 2 for failure tests
   fi
   echo "unexpected args: $@" >&2
   exit 1
   ```
3. Make it executable (`chmod +x`).
4. Set `PATH=/tmp/test_xxx/bin:$PATH` in the subprocess environment.
5. `which uv` resolves to `/tmp/test_xxx/bin/uv` (absolute path, as spec requires).
6. The fake script handles `uv sync` with controlled exit codes.

For failure tests (uv not found): simply do NOT put a `uv` script on PATH.

### White-Box Mocking: `mergeSettings()` in Isolation

The `mergeSettings(srcSettingsPath, absUvPath, projectDir)` function (after the coding agent's update) is testable without any mocking of subprocesses:

1. Create a temp directory with `src/settings.json` (the template with placeholders).
2. Create a temp `~/.claude/settings.json` (the destination with pre-existing hooks).
3. Call `mergeSettings()` via a small Node.js helper script that:
   - Overrides `os.homedir()` or patches the `settingsPath` variable
   - Requires `install.js` and calls the exported `mergeSettings()`
   - Outputs the result as JSON to stdout
4. The Python test reads the JSON output and asserts on the merged result.

**Alternative simpler approach**: Write the white-box tests as a Node.js helper that Python calls via `subprocess`. The Node.js helper:
- Takes arguments: `srcSettingsPath`, `absUvPath`, `projectDir`, `destSettingsPath` (for the pre-existing file)
- Requires `install.js`, calls `mergeSettings()`, writes result to stdout as JSON
- The Python test parses stdout and asserts

This avoids needing JavaScript test frameworks (Jest, etc.) while keeping Python as the test harness.

**Fallback if `mergeSettings` is not exported**: If the coding agent does not export `mergeSettings()`, white-box tests fall back to running `node install.js` end-to-end (same as contract tests but with more detailed assertions). This is a partial degradation, not a full block.

### Contract Test Mocking: `install()` End-to-End

For contract tests, the full `install()` function runs via `node install.js`:

1. Create temp HOME directory structure: `$TMP/home/.claude/settings.json`
2. Copy `src/` directory to a temp project directory (or symlink)
3. Create fake `uv` script in `$TMP/bin/`
4. Set environment: `HOME=$TMP/home`, `PATH=$TMP/bin:...`
5. Run: `subprocess.run(["node", "/path/to/install.js"], env=modified_env, capture_output=True)`
6. Read `$TMP/home/.claude/settings.json` and assert

## Test Types

| Type | When to Use |
|------|-------------|
| White-box tests | Test `mergeSettings()` as a function: stale detection, command generation, merge logic, invariants. Can inspect internal JSON structure, hook group arrays, individual command strings. |
| Contract tests | Test `node install.js` as a subprocess: verify the installer produces correct `settings.json` from various initial states. Black-box -- only checks final output and exit codes. |
| **Deliverable tests** | **Run `node install.js` in a temp directory the way a real user would. Verify the resulting `~/.claude/settings.json` has correct commands, no stale entries, and valid JSON. These are included in the contract test file.** |

### Deliverable Test Strategy

The ultimate deliverable is: "a user runs `node install.js` and gets a correct `~/.claude/settings.json`." Deliverable tests exercise this exact flow:

1. Set up temp HOME with pre-existing `settings.json` (possibly with stale entries).
2. Set up fake `uv` on PATH.
3. Run `node install.js` via subprocess.
4. Read the resulting `settings.json`.
5. Assert: correct `uv run` commands, stale entries removed, non-project hooks preserved, valid JSON, correct timeouts.

These are the most important tests because they catch integration failures between `install()`'s steps that unit tests of `mergeSettings()` alone might miss.

## Adversarial Test Categories

### Category 1: Invalid Input (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-INVAL-001 | Malformed `settings.json` (invalid JSON) | INV-HOOKS-007 | Pre-existing `settings.json` contains invalid JSON. `mergeSettings()` should handle gracefully (log warning, treat as empty). |
| TC-INVAL-002 | `settings.json` with missing `hooks` key | REQ-HOOKS-005 | No hooks section at all. Stale detection should handle `undefined` hooks gracefully. |
| TC-INVAL-003 | `settings.json` with `hooks: null` | REQ-HOOKS-005 | Null hooks value. Guard clause should return early without error. |
| TC-INVAL-004 | `settings.json` with empty hooks object `{}` | REQ-HOOKS-005 | No event types defined. New hooks should be added without error. |
| TC-INVAL-005 | Hook group missing `hooks` array | REQ-HOOKS-005 | A hook group object that lacks the `hooks` array property. Filter should not crash. |
| TC-INVAL-006 | Hook entry missing `command` field | REQ-HOOKS-005 | An individual hook without a `command` string. `includes()` on undefined should not crash. |
| TC-INVAL-007 | Source `settings.json` missing (no template) | REQ-HOOKS-003 | `src/settings.json` does not exist. `mergeSettings()` should handle gracefully. |

### Category 2: State Corruption / Stale Entries (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-STALE-001 | Bare `python3` stale entry | REQ-HOOKS-005, SCN-HOOKS-005-01 | Command: `python3 "/Users/jane/.claude/hooks/session_end.py"` |
| TC-STALE-002 | `.venv` python3 stale entry | REQ-HOOKS-005, SCN-HOOKS-005-02 | Command: `/path/.venv/bin/python3 "/path/.claude/hooks/precompact.py"` |
| TC-STALE-003 | Multiple stale entries for same script | REQ-HOOKS-005, SCN-HOOKS-005-03 | Two different stale formats for `user_prompt_inject.py` in same event type |
| TC-STALE-004 | Existing `uv run` entries (idempotency) | REQ-HOOKS-005, SCN-HOOKS-005-05, INV-HOOKS-001 | Re-running install.js produces identical output |
| TC-STALE-005 | Mixed project and non-project hooks | REQ-HOOKS-005, REQ-HOOKS-006, SCN-HOOKS-005-04 | Project hooks removed, `document_scanner.py` preserved |
| TC-STALE-006 | Stale entries across ALL event types | REQ-HOOKS-005 | Each of the three event types has stale entries |
| TC-STALE-007 | Non-project hooks only (no project hooks to remove) | REQ-HOOKS-006, INV-HOOKS-002 | Only non-project hooks exist; none should be removed |

### Category 3: Error Path Coverage (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-ERR-001 | `uv` not installed (not on PATH) | REQ-HOOKS-007, SCN-HOOKS-007-01 | Exit code 1, specific stderr message, no file modifications |
| TC-ERR-002 | `uv` check before file operations | REQ-HOOKS-007, SCN-HOOKS-007-02, INV-HOOKS-004 | Verify `settings.json` unchanged when uv not found |
| TC-ERR-003 | `uv sync` fails with exit code 2 | REQ-HOOKS-009, SCN-HOOKS-009-02 | Exit code 1, error message includes "uv sync failed", exit code, suggestion |
| TC-ERR-004 | `uv sync` failure prevents file modification | REQ-HOOKS-009, INV-HOOKS-004 | `settings.json` unchanged, no hooks copied |
| TC-ERR-005 | Source directory not found | (order of operations step 1) | install.js exits with error when `src/` is missing |

### Category 4: Boundary Conditions (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-BOUND-001 | Empty pre-existing `settings.json` (`{}`) | REQ-HOOKS-005 | Fresh install with no prior state |
| TC-BOUND-002 | No pre-existing `settings.json` file | REQ-HOOKS-005 | File does not exist at all |
| TC-BOUND-003 | Empty hook arrays per event type | REQ-HOOKS-005 | `"SessionEnd": []` with no hook groups |
| TC-BOUND-004 | uv path with trailing newline | REQ-HOOKS-008, SCN-HOOKS-008-01 | `which uv` returns `/path/to/uv\n`; must be trimmed |
| TC-BOUND-005 | Path with spaces in home directory | REQ-HOOKS-003, SCN-HOOKS-003-02 | `/Users/John Doe/...` must be double-quoted |
| TC-BOUND-006 | Path with no spaces (standard) | REQ-HOOKS-003, SCN-HOOKS-003-01 | `/Users/jane/...` standard path |
| TC-BOUND-007 | Pre-existing non-hook settings | INV-HOOKS-005 | `enabledPlugins`, custom keys must be preserved |
| TC-BOUND-008 | Timeout values in generated hooks | INV-HOOKS-006 | 10s for UserPromptSubmit, 120s for SessionEnd/PreCompact |

### Summary: 4 of 6 adversarial categories covered (Invalid Input, State Corruption, Error Paths, Boundary Conditions).

Concurrency and resource exhaustion are out of scope for a one-shot CLI installer that runs once and exits. There is no concurrent access pattern, and the files involved are small JSON configs.

## Security Test Planning

Per the intent's security analysis, security risk is low:

| SEC-* | Applicable? | Justification |
|-------|-------------|---------------|
| SEC-01 Input Validation | YES (partial) | `settings.json` could be malformed. Covered by TC-INVAL-001 through TC-INVAL-007. |
| SEC-05 Error Handling | YES | Error messages should not leak internal paths or stack traces to end users. Covered by TC-ERR-001 through TC-ERR-005. |
| SEC-08 Injection Prevention | NO | All paths derived from `__dirname` and `os.homedir()`, not user input. No injection vector. |

## Contract Test Exclusions

| REQ-* | Contract Test? | Reason | Covered By |
|-------|---------------|--------|------------|
| REQ-HOOKS-002 | NO | Requires a real `uv` installation with `anthropic` package installed. This is a runtime integration concern, not testable via subprocess with a fake `uv`. | test_scn_anthropic_import_via_uv_run (white-box, integration test that runs only if real uv is available) |
| REQ-HOOKS-004 | NO | Requires a valid Anthropic API key and live API access. This is an end-to-end integration test that cannot be run in CI without secrets. Per spec: "This is an integration-level success criterion." | Verified manually per QG-HOOKS-003 in intent.md. All constituent REQs (001, 002, 003, 008, 009) are individually tested. |
| SCN-HOOKS-002-01 | NO (SCN in white-box only) | Same as REQ-HOOKS-002 -- requires real uv and anthropic. | test_scn_anthropic_import_via_uv_run (conditionally run) |
| SCN-HOOKS-004-01 | NO (SCN in white-box only) | Same as REQ-HOOKS-004 -- requires live API. | Manual verification per QG-HOOKS-003 |

All other REQ-HOOKS-* have both white-box and contract tests. REQ-HOOKS-002 and REQ-HOOKS-004 are excluded from contract testing because they require live external dependencies (real `uv` with `anthropic`, live Anthropic API) that cannot be faked in an automated test.

## SCN-* to Test File Mapping

### White-box (`tests/test_hooks_whitebox.py`)

| SCN-* | Test Function |
|-------|---------------|
| SCN-HOOKS-001-01 | test_scn_generated_command_uses_uv_not_python3 |
| SCN-HOOKS-002-01 | test_scn_anthropic_import_via_uv_run (conditional) |
| SCN-HOOKS-003-01 | test_scn_command_format_no_spaces |
| SCN-HOOKS-003-02 | test_scn_command_format_with_spaces |
| SCN-HOOKS-003-03 | test_scn_all_three_hooks_generated |
| SCN-HOOKS-005-01 | test_scn_remove_bare_python3_entry |
| SCN-HOOKS-005-02 | test_scn_remove_venv_python3_entry |
| SCN-HOOKS-005-03 | test_scn_remove_multiple_stale_entries |
| SCN-HOOKS-005-04 | test_scn_preserve_non_project_hook |
| SCN-HOOKS-005-05 | test_scn_idempotent_rerun |
| SCN-HOOKS-007-01 | test_scn_uv_not_installed_error |
| SCN-HOOKS-007-02 | test_scn_uv_check_before_file_operations |
| SCN-HOOKS-008-01 | test_scn_uv_path_trimmed |
| SCN-HOOKS-008-02 | test_scn_uv_homebrew_path |
| SCN-HOOKS-009-01 | test_scn_uv_sync_succeeds |
| SCN-HOOKS-009-02 | test_scn_uv_sync_fails_with_error_message |

### Contract (`tests/test_hooks_contract.py`)

| REQ-* | Test Function |
|-------|---------------|
| REQ-HOOKS-001 | test_contract_commands_use_uv_run |
| REQ-HOOKS-003 | test_contract_command_format |
| REQ-HOOKS-005 | test_contract_stale_entries_removed |
| REQ-HOOKS-006 | test_contract_non_project_hooks_preserved |
| REQ-HOOKS-007 | test_contract_uv_not_found_error |
| REQ-HOOKS-008 | test_contract_absolute_uv_path |
| REQ-HOOKS-009 | test_contract_uv_sync_failure_aborts |
| INV-HOOKS-007 | test_contract_output_is_valid_json |
| (deliverable) | test_contract_full_install_fresh |
| (deliverable) | test_contract_full_install_with_stale_entries |
| (deliverable) | test_contract_full_install_idempotent |

## Test File Organization

| File | Purpose | Location |
|------|---------|----------|
| `docs/hooks/testing.md` | Test strategy (this file) | `docs/hooks/testing.md` |
| `tests/test_hooks_whitebox.py` | White-box tests: mergeSettings logic, stale detection, command generation, invariants, all SCN-* | `tests/test_hooks_whitebox.py` |
| `tests/test_hooks_contract.py` | Contract tests: run `node install.js` via subprocess, verify output settings.json, error codes, deliverable tests | `tests/test_hooks_contract.py` |

### File Headers

White-box test file:
```python
# Spec: docs/hooks/spec.md
# Testing: docs/hooks/testing.md
```

Contract test file:
```python
# Spec: docs/hooks/spec.md
# Testing: docs/hooks/testing.md
```

Note: There is no `docs/hooks/contract.md`. Contract tests are derived from the public behavior documented in `spec.md` (the REQ-* requirements describe the external behavior of `install.js`).

## Verification Plan (Phase 2 Checklist)

Before claiming Phase 2 COMPLETE:

1. `pytest tests/test_hooks_whitebox.py tests/test_hooks_contract.py -v` -- all tests pass
2. Coverage check: verify mergeSettings and stale detection logic are >= 80% covered
3. Break-the-code verification: comment out the stale detection loop in `mergeSettings()`, run tests, verify failure
4. Every `@tests` annotation references a valid REQ-*/SCN-*/INV-* from spec.md
5. Every `@tests-contract` annotation references a valid REQ-* from spec.md
6. Every `@tests-invariant` annotation references a valid INV-* from spec.md
7. No `pytest.skip()` or `@pytest.mark.skip` anywhere
8. Race detector: N/A (Python, not Go)
9. Flaky detection: `pytest tests/test_hooks_whitebox.py tests/test_hooks_contract.py --count=100` (using pytest-repeat if available, else run in loop)
10. Deliverable tests: at least one test runs `node install.js` end-to-end and verifies the full output
