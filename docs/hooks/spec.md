# Requirements Specification: Hook Dependency Management (uv run)

## Intent Traceability

This section preserves the success criteria from the approved intent.
The full intent document is in `.planning/intent.md` for historical reference.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* |
|------|-------------------|-------------------|
| SC-HOOKS-001 | Hook commands in `~/.claude/settings.json` use `uv run --project <project_dir>` instead of bare `python3`, ensuring `anthropic` is importable. | REQ-HOOKS-001, SCN-HOOKS-001-01 |
| SC-HOOKS-002 | When hooks execute via the generated command, `import anthropic` succeeds (`ANTHROPIC_AVAILABLE` is `True`). | REQ-HOOKS-002, SCN-HOOKS-002-01 |
| SC-HOOKS-003 | `install.js` generates the correct command format: `<abs_uv_path> run --project "<abs_project_dir>" python "<script_path>"` with all paths absolute and properly quoted. | REQ-HOOKS-003, SCN-HOOKS-003-01, SCN-HOOKS-003-02, SCN-HOOKS-003-03 |
| SC-HOOKS-004 | After running `node install.js`, `SessionEnd` and `PreCompact` hooks can successfully make Anthropic API calls (given a valid API key). | REQ-HOOKS-004, SCN-HOOKS-004-01 |
| SC-HOOKS-005 | `install.js` removes stale hook entries before adding new ones. Stale = command contains `/.claude/hooks/<script_name>.py` for the three project scripts. Non-project hooks preserved. Exactly one entry per event type after install. | REQ-HOOKS-005, REQ-HOOKS-006, INV-HOOKS-001, INV-HOOKS-002, SCN-HOOKS-005-01, SCN-HOOKS-005-02, SCN-HOOKS-005-03, SCN-HOOKS-005-04, SCN-HOOKS-005-05 |
| SC-HOOKS-006 | If `uv` is not found on PATH at install time, `install.js` prints a specific error to stderr and exits non-zero. | REQ-HOOKS-007, SCN-HOOKS-007-01, SCN-HOOKS-007-02 |
| SC-HOOKS-007 | `install.js` resolves the absolute path to `uv` at install time (via `which uv`) and embeds it in generated commands. | REQ-HOOKS-008, SCN-HOOKS-008-01, SCN-HOOKS-008-02 |
| SC-HOOKS-008 | `install.js` runs `uv sync --project <path>` during installation to pre-install dependencies. If `uv sync` fails, installation aborts with a clear error. | REQ-HOOKS-009, SCN-HOOKS-009-01, SCN-HOOKS-009-02 |
| SC-HOOKS-009 | `install.js` writes valid JSON (parseable by `JSON.parse()`) to `~/.claude/settings.json`. Hook command strings embedded within are properly escaped for JSON encoding. | INV-HOOKS-007 |

---

## Requirements

### REQ-HOOKS-001: Hook Command Uses uv run {#REQ-HOOKS-001}
- **Implements**: SC-HOOKS-001
- **GIVEN**: `install.js` is generating hook commands for `settings.json`
- **WHEN**: The command string for any hook is constructed
- **THEN**:
  - The command uses `uv run --project` to invoke Python, NOT bare `python3`
  - The `--project` flag points to the project root directory (where `pyproject.toml` lives)
  - The command ensures that `uv` resolves dependencies from `pyproject.toml` and `uv.lock` at hook runtime

### REQ-HOOKS-002: Anthropic Package Available at Hook Runtime {#REQ-HOOKS-002}
- **Implements**: SC-HOOKS-002
- **GIVEN**: A hook script (`user_prompt_inject.py`, `session_end.py`, or `precompact.py`) is executed via the generated `uv run` command
- **WHEN**: The script reaches `import anthropic` (in `common.py`)
- **THEN**:
  - The import succeeds without `ImportError`
  - `ANTHROPIC_AVAILABLE` is set to `True`
  - All LLM-dependent features (reflector, curator, keypoint extraction) can proceed
- **Verification**: Run the generated command manually and check `python -c "import anthropic; print(anthropic.__version__)"` via `uv run --project`

### REQ-HOOKS-003: Command Format Specification {#REQ-HOOKS-003}
- **Implements**: SC-HOOKS-003
- **GIVEN**: `install.js` is generating a hook command for script `<script_name>.py`
- **WHEN**: The command string is constructed
- **THEN**: The command has the exact format:
  ```
  <abs_uv_path> run --project "<abs_project_dir>" python "<abs_script_path>"
  ```
  Where:
  - `<abs_uv_path>` is the absolute filesystem path to the `uv` binary, resolved at install time (e.g., `/Users/jane/.local/bin/uv`). NOT quoted (shell will not word-split a single token without spaces; uv install paths do not contain spaces).
  - `<abs_project_dir>` is the absolute path to the directory containing `pyproject.toml`, derived from `__dirname` in `install.js`. Double-quoted to handle spaces in the path.
  - `<abs_script_path>` is the absolute path to the hook script in `~/.claude/hooks/`, derived from `path.join(os.homedir(), '.claude', 'hooks', scriptName)`. Double-quoted to handle spaces in the path (e.g., `/Users/John Doe/.claude/hooks/session_end.py`).
  - The word `python` (not `python3`) is the argument to `uv run`, which tells uv to invoke its managed Python interpreter.
- **Constraint**: All three path components MUST be absolute. Relative paths are forbidden because hooks execute from an unpredictable working directory (Claude Code's cwd). See CON-HOOKS-003.

### REQ-HOOKS-004: End-to-End Hook Functionality {#REQ-HOOKS-004}
- **Implements**: SC-HOOKS-004
- **GIVEN**: `node install.js` has been executed successfully
- **AND**: A valid Anthropic API key is configured in the environment
- **WHEN**: Claude Code triggers a `SessionEnd` or `PreCompact` hook
- **THEN**:
  - The hook script executes via the `uv run` command
  - `import anthropic` succeeds
  - The hook can create an Anthropic client and make API calls
  - Diagnostic logs show actual LLM responses instead of "no client available"
- **Note**: This is an integration-level success criterion. It is satisfied when REQ-HOOKS-001, REQ-HOOKS-002, REQ-HOOKS-003, REQ-HOOKS-008, and REQ-HOOKS-009 are all satisfied.

### REQ-HOOKS-005: Stale Hook Entry Removal {#REQ-HOOKS-005}
- **Implements**: SC-HOOKS-005
- **GIVEN**: `~/.claude/settings.json` exists and contains hook entries under one or more event types (`UserPromptSubmit`, `SessionEnd`, `PreCompact`)
- **WHEN**: `install.js` merges new hook entries
- **THEN**:
  - **Before** adding new entries, the merge logic scans all existing hook entries across all event types
  - For each event type, for each hook group, for each individual hook: if the hook's `command` string contains the substring `/.claude/hooks/<script_name>.py` where `<script_name>` is one of `user_prompt_inject`, `session_end`, or `precompact`, that hook entry is removed
  - The substring match is literal (no regex). It matches regardless of the command prefix (bare `python3 "..."`, `/path/to/.venv/bin/python3 "..."`, `/path/to/uv run ... python "..."`, or any other invocation)
  - After removal, if a hook group has zero remaining hooks, the entire group object is removed from the event's array
  - After removal, if an event type's array is empty, the key is preserved as an empty array (to be filled by the subsequent add step)
- **Order of operations**: Remove stale entries FIRST, then add new entries. This order is critical for idempotency.

### REQ-HOOKS-006: Non-Project Hook Preservation {#REQ-HOOKS-006}
- **Implements**: SC-HOOKS-005
- **GIVEN**: `~/.claude/settings.json` contains hook entries that are NOT from this project (e.g., commands referencing `document_scanner.py`, `git_scanner.py`, or any script NOT matching the three project script names)
- **WHEN**: `install.js` performs stale entry removal (REQ-HOOKS-005)
- **THEN**:
  - These non-project hook entries are NOT removed
  - Their `command`, `type`, `timeout`, and any other properties are preserved exactly as they were
  - Their position within the event type's hook group array may shift (due to removal of project hooks), but they remain present

### REQ-HOOKS-007: uv Not Found Error Handling {#REQ-HOOKS-007}
- **Implements**: SC-HOOKS-006
- **GIVEN**: `install.js` is executing and attempts to locate the `uv` binary
- **WHEN**: `uv` is not found on the system PATH (i.e., `which uv` returns non-zero or equivalent Node.js mechanism fails)
- **THEN**:
  - The following exact error message is printed to stderr:
    ```
    Error: 'uv' is not installed or not found on PATH. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh
    See https://docs.astral.sh/uv/getting-started/installation/ for other methods.
    ```
  - `process.exit(1)` is called
  - No files are modified (no hooks copied, no settings.json written)
  - The uv check occurs BEFORE any file operations (copy hooks, merge settings)

### REQ-HOOKS-008: Absolute uv Path Resolution {#REQ-HOOKS-008}
- **Implements**: SC-HOOKS-007
- **GIVEN**: `install.js` is executing and `uv` is found on the system PATH
- **WHEN**: The installer resolves the `uv` binary location
- **THEN**:
  - The absolute filesystem path to `uv` is determined (e.g., via `which uv` or Node.js `child_process.execSync('which uv')`)
  - The resolved path is trimmed of trailing whitespace/newline
  - This absolute path is used in ALL generated hook commands (per REQ-HOOKS-003)
  - The resolved path is NOT the bare string `"uv"` -- it is a fully qualified path (e.g., `/Users/jane/.local/bin/uv`, `/usr/local/bin/uv`, `/opt/homebrew/bin/uv`)

### REQ-HOOKS-009: Pre-Install Dependency Sync {#REQ-HOOKS-009}
- **Implements**: SC-HOOKS-008
- **GIVEN**: `install.js` is executing, `uv` has been found and its absolute path resolved
- **WHEN**: The installer reaches the dependency sync step
- **THEN**:
  - The installer executes: `<abs_uv_path> sync --project "<abs_project_dir>"`
  - This runs AFTER the uv check (REQ-HOOKS-007, REQ-HOOKS-008) and BEFORE file copy / settings merge
  - If `uv sync` exits with code 0: installation continues normally
  - If `uv sync` exits with non-zero code: installation aborts with an error message to stderr that includes:
    - The fact that `uv sync` failed
    - The exit code
    - A suggestion to run `uv sync --project "<abs_project_dir>"` manually as a troubleshooting step
  - No files are modified if `uv sync` fails (no hooks copied, no settings.json written)

---

## Scenarios

### SCN-HOOKS-001-01: Generated Command Uses uv run Instead of python3 {#SCN-HOOKS-001-01}
- **Implements**: REQ-HOOKS-001
- **GIVEN**: `install.js` has detected `uv` at `/Users/jane/.local/bin/uv`
- **AND**: The project root is `/Users/jane/projects/ace`
- **WHEN**: The installer generates the hook command for `session_end.py`
- **THEN**: The generated command is:
  ```
  /Users/jane/.local/bin/uv run --project "/Users/jane/projects/ace" python "/Users/jane/.claude/hooks/session_end.py"
  ```
- **AND**: The command does NOT contain the string `python3 "`  (bare python3 invocation)

### SCN-HOOKS-002-01: Anthropic Import Succeeds Under uv run {#SCN-HOOKS-002-01}
- **Implements**: REQ-HOOKS-002
- **GIVEN**: `uv sync` has been run for the project (dependencies installed)
- **AND**: `pyproject.toml` declares `anthropic>=0.83.0` as a dependency
- **WHEN**: The command `<abs_uv_path> run --project "<abs_project_dir>" python -c "import anthropic; print(anthropic.__version__)"` is executed
- **THEN**: The command exits with code 0 and prints a version string (e.g., `0.83.0`)
- **AND**: No `ModuleNotFoundError` is raised

### SCN-HOOKS-003-01: Command Format with Standard Paths (No Spaces) {#SCN-HOOKS-003-01}
- **Implements**: REQ-HOOKS-003
- **GIVEN**: `uv` is at `/Users/jane/.local/bin/uv`
- **AND**: Project root is `/Users/jane/projects/ace`
- **AND**: Home directory is `/Users/jane`
- **WHEN**: `install.js` generates the command for `user_prompt_inject.py`
- **THEN**: The command string is exactly:
  ```
  /Users/jane/.local/bin/uv run --project "/Users/jane/projects/ace" python "/Users/jane/.claude/hooks/user_prompt_inject.py"
  ```

### SCN-HOOKS-003-02: Command Format with Spaces in Home Directory {#SCN-HOOKS-003-02}
- **Implements**: REQ-HOOKS-003
- **GIVEN**: `uv` is at `/usr/local/bin/uv`
- **AND**: Project root is `/Users/John Doe/projects/ace`
- **AND**: Home directory is `/Users/John Doe`
- **WHEN**: `install.js` generates the command for `precompact.py`
- **THEN**: The command string is exactly:
  ```
  /usr/local/bin/uv run --project "/Users/John Doe/projects/ace" python "/Users/John Doe/.claude/hooks/precompact.py"
  ```
- **AND**: Both the project dir and script path are double-quoted to prevent shell word splitting

### SCN-HOOKS-003-03: All Three Hook Scripts Get Commands {#SCN-HOOKS-003-03}
- **Implements**: REQ-HOOKS-003
- **GIVEN**: `install.js` is generating hook entries
- **WHEN**: Settings are merged into `~/.claude/settings.json`
- **THEN**: Exactly three hook commands are generated, one for each script:
  - `user_prompt_inject.py` under event `UserPromptSubmit` with timeout `10`
  - `session_end.py` under event `SessionEnd` with timeout `120`
  - `precompact.py` under event `PreCompact` with timeout `120`
- **AND**: Each command follows the format specified in REQ-HOOKS-003

### SCN-HOOKS-004-01: Generated uv run Command Enables Anthropic Import {#SCN-HOOKS-004-01}
- **Implements**: REQ-HOOKS-004
- **GIVEN**: `install.js` has run successfully (uv found, uv sync succeeded, settings.json written)
- **AND**: A valid Anthropic API key is configured in the environment
- **WHEN**: The generated `uv run` command for `session_end.py` is executed
- **THEN**: `import anthropic` succeeds, `ANTHROPIC_AVAILABLE` is `True`, and the script can instantiate an `Anthropic` client without raising

### SCN-HOOKS-005-01: Remove Bare python3 Stale Entry {#SCN-HOOKS-005-01}
- **Implements**: REQ-HOOKS-005
- **GIVEN**: `~/.claude/settings.json` has `SessionEnd` entry with command `python3 "/Users/jane/.claude/hooks/session_end.py"`
- **WHEN**: `install.js` merges settings
- **THEN**: The old `python3` entry is removed
- **AND**: A new `uv run` entry for `session_end.py` is added
- **AND**: The `SessionEnd` array contains exactly one hook group with one hook referencing `session_end.py`

### SCN-HOOKS-005-02: Remove .venv python3 Stale Entry {#SCN-HOOKS-005-02}
- **Implements**: REQ-HOOKS-005
- **GIVEN**: `~/.claude/settings.json` has `PreCompact` entry with command `/Users/jane/.claude/.venv/bin/python3 "/Users/jane/.claude/hooks/precompact.py"`
- **WHEN**: `install.js` merges settings
- **THEN**: The `.venv/bin/python3` entry is removed
- **AND**: A new `uv run` entry for `precompact.py` is added

### SCN-HOOKS-005-03: Remove Multiple Stale Entries for Same Script {#SCN-HOOKS-005-03}
- **Implements**: REQ-HOOKS-005
- **GIVEN**: `~/.claude/settings.json` has `UserPromptSubmit` with TWO entries for `user_prompt_inject.py`:
  1. `python3 "/Users/jane/.claude/hooks/user_prompt_inject.py"` (original)
  2. `/Users/jane/.claude/.venv/bin/python3 "/Users/jane/.claude/hooks/user_prompt_inject.py"` (failed .venv attempt)
- **WHEN**: `install.js` merges settings
- **THEN**: Both stale entries are removed
- **AND**: Exactly one new `uv run` entry for `user_prompt_inject.py` is added
- **AND**: The final `UserPromptSubmit` array has exactly one hook group with one hook for this script

### SCN-HOOKS-005-04: Preserve Non-Project Hook Entries {#SCN-HOOKS-005-04}
- **Implements**: REQ-HOOKS-005, REQ-HOOKS-006
- **GIVEN**: `~/.claude/settings.json` has `UserPromptSubmit` with entries:
  1. `python3 "/Users/jane/.claude/hooks/user_prompt_inject.py"` (project hook -- stale)
  2. `python3 "/Users/jane/.claude/hooks/document_scanner.py"` (non-project hook)
- **WHEN**: `install.js` merges settings
- **THEN**: The `user_prompt_inject.py` entry is removed and replaced with a `uv run` entry
- **AND**: The `document_scanner.py` entry is preserved unchanged (command, type, timeout all intact)
- **BECAUSE**: `document_scanner.py` does not match any of the three project script names (`user_prompt_inject`, `session_end`, `precompact`)

### SCN-HOOKS-005-05: Idempotent Re-run {#SCN-HOOKS-005-05}
- **Implements**: REQ-HOOKS-005, INV-HOOKS-001
- **GIVEN**: `install.js` has already been run once, producing valid `uv run` entries in `settings.json`
- **WHEN**: `install.js` is run a second time (with the same uv path and project dir)
- **THEN**: The existing `uv run` entries are removed (they match the stale detection pattern)
- **AND**: New identical `uv run` entries are added
- **AND**: The final state of `settings.json` is identical to after the first run
- **AND**: There are no duplicate hook entries

### SCN-HOOKS-007-01: uv Not Installed {#SCN-HOOKS-007-01}
- **Implements**: REQ-HOOKS-007
- **GIVEN**: `uv` is not installed on the system (not on PATH)
- **WHEN**: `install.js` is executed
- **THEN**: The error message is printed to stderr:
  ```
  Error: 'uv' is not installed or not found on PATH. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh
  See https://docs.astral.sh/uv/getting-started/installation/ for other methods.
  ```
- **AND**: The process exits with code 1
- **AND**: `~/.claude/settings.json` is NOT modified
- **AND**: No files are copied to `~/.claude/hooks/`

### SCN-HOOKS-007-02: uv Check Occurs Before File Operations {#SCN-HOOKS-007-02}
- **Implements**: REQ-HOOKS-007
- **GIVEN**: `uv` is not installed
- **AND**: `~/.claude/settings.json` exists with existing content
- **WHEN**: `install.js` is executed
- **THEN**: The uv check fails and the process exits
- **AND**: The content of `~/.claude/settings.json` is byte-for-byte identical to before the run
- **AND**: No new files appear in `~/.claude/hooks/`
- **BECAUSE**: The uv check is the FIRST step in `install()`, before any file copy or settings merge

### SCN-HOOKS-008-01: Absolute uv Path Embedded in Command {#SCN-HOOKS-008-01}
- **Implements**: REQ-HOOKS-008
- **GIVEN**: `uv` is installed at `/Users/jane/.local/bin/uv`
- **AND**: `which uv` returns `/Users/jane/.local/bin/uv\n` (with trailing newline)
- **WHEN**: `install.js` resolves the uv path
- **THEN**: The resolved path is `/Users/jane/.local/bin/uv` (trimmed)
- **AND**: All generated hook commands start with `/Users/jane/.local/bin/uv run --project`
- **AND**: No generated command starts with the bare string `uv run`

### SCN-HOOKS-008-02: uv Installed via Homebrew {#SCN-HOOKS-008-02}
- **Implements**: REQ-HOOKS-008
- **GIVEN**: `uv` is installed via Homebrew at `/opt/homebrew/bin/uv`
- **WHEN**: `install.js` resolves the uv path
- **THEN**: The resolved path is `/opt/homebrew/bin/uv`
- **AND**: Generated commands use `/opt/homebrew/bin/uv run --project ...`

### SCN-HOOKS-009-01: uv sync Succeeds {#SCN-HOOKS-009-01}
- **Implements**: REQ-HOOKS-009
- **GIVEN**: `uv` is found at `/Users/jane/.local/bin/uv`
- **AND**: The project has a valid `pyproject.toml` and `uv.lock`
- **WHEN**: `install.js` runs `uv sync --project "/Users/jane/projects/ace"`
- **THEN**: `uv sync` exits with code 0
- **AND**: Installation continues to the file copy step
- **AND**: The virtual environment and all dependencies (including `anthropic`) are installed

### SCN-HOOKS-009-02: uv sync Fails {#SCN-HOOKS-009-02}
- **Implements**: REQ-HOOKS-009
- **GIVEN**: `uv` is found but `uv sync` fails (e.g., network error, corrupted lock file)
- **AND**: `uv sync` exits with code 2
- **WHEN**: `install.js` checks the exit code
- **THEN**: An error message is printed to stderr that includes:
  - The text `uv sync failed` (or equivalent clear phrasing)
  - The exit code (e.g., `exit code 2`)
  - The suggestion: `Try running manually: uv sync --project "<abs_project_dir>"`
- **AND**: The process exits with code 1
- **AND**: `~/.claude/settings.json` is NOT modified
- **AND**: No files are copied to `~/.claude/hooks/`

---

## Invariants

### INV-HOOKS-001: Exactly One Project Hook Per Event Type {#INV-HOOKS-001}
- **Implements**: SC-HOOKS-005
- **Statement**: After `install.js` completes successfully, for each event type (`UserPromptSubmit`, `SessionEnd`, `PreCompact`), `~/.claude/settings.json` contains exactly one hook entry whose command references the corresponding project script (`user_prompt_inject.py`, `session_end.py`, `precompact.py` respectively). There are no duplicates regardless of how many times `install.js` has been run or what stale entries existed prior.
- **Enforced by**: REQ-HOOKS-005 removes ALL matching entries before REQ-HOOKS-001 adds new ones. The remove-then-add order guarantees exactly one entry per script per event type.

### INV-HOOKS-002: Non-Project Hooks Are Never Modified {#INV-HOOKS-002}
- **Implements**: SC-HOOKS-005
- **Statement**: Hook entries in `~/.claude/settings.json` whose `command` string does NOT contain the substring `/.claude/hooks/user_prompt_inject.py`, `/.claude/hooks/session_end.py`, or `/.claude/hooks/precompact.py` are never removed, modified, or reordered by `install.js`. Their `command`, `type`, `timeout`, and all other properties are preserved exactly.
- **Enforced by**: REQ-HOOKS-005 stale detection only matches commands containing one of the three specific script-path substrings. REQ-HOOKS-006 explicitly requires non-matching entries to be preserved.

### INV-HOOKS-003: All Paths Are Absolute {#INV-HOOKS-003}
- **Implements**: SC-HOOKS-003, CON-HOOKS-003
- **Statement**: Every path embedded in a generated hook command (the uv binary path, the project directory, and the script path) is an absolute filesystem path starting with `/`. No relative paths, no `~` expansion, no environment variable references.
- **Enforced by**: REQ-HOOKS-008 resolves uv via `which` (returns absolute path). REQ-HOOKS-003 derives project dir from `__dirname` (absolute in Node.js) and script path from `path.join(os.homedir(), ...)` (absolute).

### INV-HOOKS-004: No File Modification on Error {#INV-HOOKS-004}
- **Implements**: SC-HOOKS-006, SC-HOOKS-008
- **Statement**: If `install.js` encounters a fatal error (uv not found, uv sync failure), no files are modified. `~/.claude/settings.json` retains its pre-run content. No files are copied to `~/.claude/hooks/`. The installer fails atomically with respect to the filesystem.
- **Enforced by**: REQ-HOOKS-007 and REQ-HOOKS-009 specify that uv check and uv sync occur BEFORE any file copy or settings merge operations. Failure at either step calls `process.exit(1)` before reaching file operations.

### INV-HOOKS-005: Non-Hook Settings Preserved {#INV-HOOKS-005}
- **Implements**: CON-HOOKS-006
- **Statement**: All top-level keys in `~/.claude/settings.json` other than `hooks` (e.g., `enabledPlugins`, `playbook_update_on_exit`, `playbook_update_on_clear`, `document_scanning_enabled`, `git_scanning_enabled`) are never overwritten by `install.js`. Existing keys retain their existing values. New keys from the source template are added only if they do not already exist in the destination.
- **Enforced by**: The `mergeSettings()` function's non-hook merge logic: `if (key !== 'hooks' && !(key in destSettings)) { destSettings[key] = value; }`. This must be preserved in the updated implementation.

### INV-HOOKS-006: Hook Timeouts Unchanged {#INV-HOOKS-006}
- **Implements**: CON-HOOKS-004
- **Statement**: The timeout values in generated hook entries are: `10` seconds for `UserPromptSubmit`, `120` seconds for `SessionEnd`, `120` seconds for `PreCompact`. These values match the source template `src/settings.json` and must not be altered by the uv command change.
- **Enforced by**: The template `src/settings.json` defines these timeouts. The command generation only changes the `command` field, not the `timeout` field.

### INV-HOOKS-007: Generated JSON Is Valid {#INV-HOOKS-007}
- **Implements**: SC-HOOKS-009
- **Statement**: The `settings.json` written by `install.js` is valid JSON parseable by `JSON.parse()`. The hook command strings embedded within are properly escaped for JSON (double quotes within the command string are escaped as `\"`).
- **Enforced by**: `saveSettings()` uses `JSON.stringify(settings, null, 2)` which guarantees valid JSON output. Command strings containing double-quoted paths are naturally escaped by `JSON.stringify` when they are values within the object.

---

## Order of Operations

The `install()` function in `install.js` must execute steps in this exact order. Steps are numbered to make the sequence unambiguous for the Coding Agent.

1. **Check source directory** -- Verify `src/` exists. Exit with error if not found.
2. **Check for uv** (REQ-HOOKS-007) -- Attempt to resolve the absolute path to `uv`. If not found, print the error message to stderr and `process.exit(1)`. NO file operations have occurred yet (INV-HOOKS-004).
3. **Resolve absolute uv path** (REQ-HOOKS-008) -- Trim the resolved path. Store it for use in command generation and uv sync.
4. **Run uv sync** (REQ-HOOKS-009) -- Execute `<abs_uv_path> sync --project "<abs_project_dir>"`. If it fails, print error to stderr and `process.exit(1)`. NO file operations have occurred yet (INV-HOOKS-004).
5. **Copy hooks and prompts** -- Copy `src/` contents to `~/.claude/` (existing `copyDir` logic, excluding `settings.json`).
6. **Merge settings.json** -- Call `mergeSettings(srcSettingsPath, absUvPath, projectDir)`. This loads the source template, replaces placeholders with `uv run` commands (using the resolved absolute uv path and project directory), loads destination settings, removes stale entries (REQ-HOOKS-005), adds new entries, preserves non-hook settings (INV-HOOKS-005), and returns the merged object. Write the result via `saveSettings()`.
7. **Print success message** -- Display installation summary.

---

## Stale Entry Detection Algorithm

This section specifies the exact algorithm for REQ-HOOKS-005, to eliminate any ambiguity.

**Input**: The `destSettings.hooks` object from the existing `~/.claude/settings.json`.

**Project script names** (constant list): `['user_prompt_inject.py', 'session_end.py', 'precompact.py']`

**Matching substrings** (derived from script names): `['/.claude/hooks/user_prompt_inject.py', '/.claude/hooks/session_end.py', '/.claude/hooks/precompact.py']`

**Algorithm**:
```
if destSettings.hooks is undefined or null:
  return  // nothing to clean up

for each eventName in destSettings.hooks:
  for each hookGroup in destSettings.hooks[eventName]:
    hookGroup.hooks = hookGroup.hooks.filter(hook =>
      // KEEP the hook if its command does NOT contain any matching substring
      !matchingSubstrings.some(sub => hook.command.includes(sub))
    )
  // Remove empty hook groups (those with zero hooks remaining)
  destSettings.hooks[eventName] = destSettings.hooks[eventName].filter(
    group => group.hooks && group.hooks.length > 0
  )
```

**Key properties**:
- Uses `String.prototype.includes()` for substring matching (not regex)
- Matches against the `command` field of each individual hook object
- Removes the entire hook object if its command matches, not just the command string
- Removes empty hook groups after filtering
- Runs BEFORE new entries are added (order matters for idempotency)

---

## Placeholder Replacement Update

The current `mergeSettings()` function replaces placeholders in `src/settings.json` with `python3 "<script_path>"`. This must be updated.

### Updated Function Signature

**Current** (line 53 of `install.js`):
```javascript
function mergeSettings(srcSettingsPath)
```

**New**:
```javascript
function mergeSettings(srcSettingsPath, absUvPath, projectDir)
```

The two new parameters supply the values needed for command generation:
- `absUvPath` -- the absolute path to `uv`, resolved in step 2/3 of the order of operations (e.g., `/Users/jane/.local/bin/uv`)
- `projectDir` -- `__dirname` (the directory containing `install.js`, which is the project root)

### Updated Call Site

In the `install()` function, the call to `mergeSettings` must pass all three arguments:

```javascript
const mergedSettings = mergeSettings(srcSettingsPath, absUvPath, projectDir);
```

Where `absUvPath` and `projectDir` are the variables already resolved earlier in `install()` (steps 2-3 of the order of operations).

### Updated Command Generation

**Current** (line 68 of `install.js`):
```javascript
const command = `python3 "${path.join(hooksDir, scriptName)}"`;
```

**New**:
```javascript
const command = `${absUvPath} run --project "${projectDir}" python "${path.join(hooksDir, scriptName)}"`;
```

Where:
- `absUvPath` is the parameter passed into `mergeSettings()`
- `projectDir` is the parameter passed into `mergeSettings()`
- `path.join(hooksDir, scriptName)` remains the absolute path to the hook script in `~/.claude/hooks/`

The placeholder names in `src/settings.json` (`{{HOOK_COMMAND_USER_PROMPT_INJECT}}`, etc.) do NOT need to change -- only the replacement values change.

---

## Testability

This section specifies how to test `install.js` changes in isolation, without modifying the real `~/.claude/` directory or requiring a live `uv` installation.

### 1. `mergeSettings()` Is a Pure Function (Given File Paths)

`mergeSettings(srcSettingsPath, absUvPath, projectDir)` reads a source template from `srcSettingsPath`, replaces placeholders using `absUvPath` and `projectDir`, loads the destination `settings.json`, performs stale entry removal, merges hooks, and returns the merged object. It can be tested by:

- Creating temporary `src/settings.json` and `~/.claude/settings.json` files in a temp directory
- Passing the temp file paths as arguments
- Asserting on the returned merged object (hook commands, stale entry removal, non-hook preservation)

No mocking of external processes is needed to test `mergeSettings()` in isolation.

### 2. External Process Calls Must Be Mockable

The `install()` function calls external processes via `child_process.execSync`:
- `which uv` (or equivalent) to resolve the uv path
- `uv sync --project <path>` to pre-install dependencies

For unit-level testing, these calls should be mockable. Two approaches:

- **Parameter injection**: Extract the uv-check and uv-sync logic into functions that accept an `exec` callback (e.g., `function resolveUvPath(execFn)` where `execFn` defaults to `child_process.execSync`). Tests pass a stub that returns a known path or throws.
- **Module-level mocking**: Use a test framework that can intercept `child_process.execSync` calls (e.g., Jest's `jest.mock('child_process')`).

The Coding Agent should choose the approach that best fits the project's test infrastructure. The key requirement is that tests can exercise the uv-not-found and uv-sync-failure code paths without requiring an actual `uv` binary.

### 3. Tests Should Use a Temp Directory

Tests must NOT read or write the real `~/.claude/settings.json`. Instead:

- The `install()` function (or a testable inner function) should accept a `destDir` parameter that defaults to `path.join(os.homedir(), '.claude')` but can be overridden in tests with a temporary directory.
- Alternatively, tests can set the destination path via an environment variable or by directly calling `mergeSettings()` with temp file paths (bypassing `install()` entirely).

### 4. Contract Tests for Stale Detection

The stale entry detection algorithm (REQ-HOOKS-005) should be exercised with these input states:

| Test Case | Input `destSettings.hooks` | Expected Behavior |
|-----------|---------------------------|-------------------|
| No existing hooks | `undefined` / `null` | Guard returns early; no error |
| No existing hooks | `{}` (empty object) | No stale entries to remove; new entries added |
| Bare `python3` entries | Commands like `python3 "/path/.claude/hooks/session_end.py"` | Stale entries removed |
| `.venv` python3 entries | Commands like `/path/.venv/bin/python3 "/path/.claude/hooks/session_end.py"` | Stale entries removed |
| Existing `uv run` entries (idempotency) | Commands matching the new `uv run` format | Stale entries removed, fresh entries added; result identical to first run |
| Non-project hooks only | Commands referencing `document_scanner.py`, `git_scanner.py` | All non-project hooks preserved unchanged |
| Mixed project and non-project hooks | Both project and non-project hooks in same event type | Only project hooks removed; non-project hooks preserved |

### 5. Refactoring Guidance

To enable the testing described above, `install.js` should export the following for test access:

- `mergeSettings(srcSettingsPath, absUvPath, projectDir)` -- the core merge/stale-removal logic
- Optionally, the stale detection filter function (if extracted as a separate helper)

The `install()` function itself remains the CLI entry point and does not need to be exported, but its internal steps should delegate to testable functions rather than inlining all logic.
