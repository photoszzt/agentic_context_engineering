# Requirements Specification: Bootstrap Playbook Command

**Module:** `bootstrap_playbook` (src/hooks/bootstrap_playbook.py + src/commands/bootstrap-playbook.md)
**Version:** 1.0
**Status:** APPROVED

---

## Intent Traceability

This section preserves the success criteria from the approved intent.
The full intent document is in `.planning/intent.md` for historical reference.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* |
|------|-------------------|-------------------|
| SC-BOOT-001 | **Session Discovery** -- Discovers all session transcript files for the current project by scanning `~/.claude/projects/` using a dash-separated encoding of `CLAUDE_PROJECT_DIR`. Two glob patterns: `*.jsonl` (top-level sessions) and `*/subagents/agent-*.jsonl` (subagent transcripts). Subagent opt-out via `AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS=true`. Override via `AGENTIC_CONTEXT_TRANSCRIPT_DIR`. | REQ-BOOT-001, REQ-BOOT-002, SCN-BOOT-001-01, SCN-BOOT-001-02, SCN-BOOT-001-03, SCN-BOOT-001-04 |
| SC-BOOT-002 | **Transcript Loading** -- Each discovered session transcript is loaded using `load_transcript()` from `common.py`. Sessions producing empty message lists are skipped. | REQ-BOOT-003, SCN-BOOT-003-01, SCN-BOOT-003-02 |
| SC-BOOT-003 | **Per-Session Pipeline Execution** -- Each non-empty transcript is processed through the same async pipeline as `session_end.py`: `extract_cited_ids -> await run_reflector -> apply_bullet_tags -> await run_curator -> apply_structured_operations -> run_deduplication -> prune_harmful`. Uses `async def main()` + `asyncio.run(main())`. Playbook saved after each session. | REQ-BOOT-004, REQ-BOOT-005, SCN-BOOT-004-01, SCN-BOOT-004-02, SCN-BOOT-004-03, SCN-BOOT-004-04, INV-BOOT-001, INV-BOOT-002 |
| SC-BOOT-004 | **Chronological Processing Order** -- All transcript files (sessions + subagents) sorted by mtime ascending (oldest first). Single interleaved list, not separate passes. | REQ-BOOT-006, SCN-BOOT-006-01, INV-BOOT-003 |
| SC-BOOT-005 | **Cumulative Playbook Accumulation** -- Playbook loaded once before loop. Session N+1's reflector/curator see playbook modified by sessions 1..N. | REQ-BOOT-007, SCN-BOOT-007-01, INV-BOOT-004 |
| SC-BOOT-006 | **Playbook Compatibility** -- Uses `load_playbook()` and `save_playbook()` from `common.py`. Resulting playbook indistinguishable from hook-built playbook. | REQ-BOOT-008, SCN-BOOT-008-01, INV-BOOT-005 |
| SC-BOOT-007 | **Slash Command Interface** -- `src/commands/bootstrap-playbook.md` installed to `~/.claude/commands/` by `copyDir`. `src/hooks/bootstrap_playbook.py` installed to `~/.claude/hooks/` by `copyDir`. Slash command instructs Claude to run `uv run --project <project-dir> python ~/.claude/hooks/bootstrap_playbook.py`. | REQ-BOOT-009, SCN-BOOT-009-01 |
| SC-BOOT-008 | **Rate Limit Resilience** -- Sequential processing only. Configurable delay between sessions (`AGENTIC_CONTEXT_BOOTSTRAP_DELAY`, default 2s). On pipeline failure: log, skip, continue. | REQ-BOOT-010, SCN-BOOT-010-01, SCN-BOOT-010-02, SCN-BOOT-010-03, INV-BOOT-006 |
| SC-BOOT-009 | **Progress Reporting** -- Structured progress events to stderr with `BOOTSTRAP:` prefix. Five event types with exact format strings. Counter identity: `processed + skipped + failed == total`. | REQ-BOOT-011, SCN-BOOT-011-01, SCN-BOOT-011-02, SCN-BOOT-011-03, SCN-BOOT-011-04, SCN-BOOT-011-05, INV-BOOT-007, INV-BOOT-010 |
| SC-BOOT-010 | **Already-Processed Session Tracking** -- State file `.claude/bootstrap_state.json` records processed sessions. Atomic write via temp file + `os.replace()`. Corrupted state file: log warning, treat all as unprocessed. | REQ-BOOT-012, REQ-BOOT-013, SCN-BOOT-012-01, SCN-BOOT-012-02, SCN-BOOT-012-03, SCN-BOOT-012-04, INV-BOOT-008 |
| SC-BOOT-011 | **Existing Playbook Preservation** -- If playbook exists, load and add to it (never overwrite on start). Existing key points visible to reflector/curator. | REQ-BOOT-014, SCN-BOOT-014-01, INV-BOOT-009 |
| SC-BOOT-012 | **Subagent Transcript Inclusion** -- Subagent transcripts processed through same pipeline as top-level sessions. Default: included. Opt-out: `AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS=true`. | REQ-BOOT-015, SCN-BOOT-015-01, SCN-BOOT-015-02 |

---

## Requirements

### REQ-BOOT-001: Session Directory Discovery {#REQ-BOOT-001}
- **Traces-to**: SC-BOOT-001
- **Type**: FUNCTIONAL
- **Description**: The bootstrap script computes the transcript directory path as `~/.claude/projects/{encoded_project_dir}/` where `encoded_project_dir` is derived from `CLAUDE_PROJECT_DIR` by the encoding algorithm in REQ-BOOT-002. It discovers two categories of transcript files within this directory:
  - **(a) Top-level sessions**: `glob("*.jsonl")` -- non-recursive, matches files directly in the project directory.
  - **(b) Subagent transcripts**: `glob("*/subagents/agent-*.jsonl")` -- matches subagent files in session UUID subdirectories.
  Both categories are included by default. If `AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS` env var is set to the string `"true"` (case-sensitive), only top-level sessions are discovered (subagent glob is skipped).
  If `AGENTIC_CONTEXT_TRANSCRIPT_DIR` env var is set, its value is used as the transcript directory path instead of the computed path (the encoding algorithm is bypassed entirely).
- **Acceptance**: Given a project directory with N `.jsonl` files at top level and M `agent-*.jsonl` files in `*/subagents/` subdirectories, the script discovers exactly N+M files (or N files if skip-subagents is set). With `AGENTIC_CONTEXT_TRANSCRIPT_DIR` override, files are discovered from the overridden path.

### REQ-BOOT-002: Project Directory Encoding Algorithm {#REQ-BOOT-002}
- **Traces-to**: SC-BOOT-001
- **Type**: FUNCTIONAL
- **Description**: The function `encode_project_dir(project_dir: str) -> str` transforms the absolute project directory path into the `~/.claude/projects/` subdirectory name using three sequential character replacements:
  1. Replace every `/` with `-`
  2. Replace every `.` with `-`
  3. Replace every `_` with `-`
  The replacements are applied to the full path string. No other characters are modified.
  **Verified examples:**
  - `/Users/zhitingz/Documents/agentic_context_engineering` -> `-Users-zhitingz-Documents-agentic-context-engineering`
  - `/Users/zhitingz/.codex` -> `-Users-zhitingz--codex` (dot -> `-` creates adjacent dashes)
  - `/Users/zhitingz/Documents/vscode-tlaplus` -> `-Users-zhitingz-Documents-vscode-tlaplus` (existing dashes preserved)
- **Acceptance**: For each verified example above, `encode_project_dir(input) == expected_output`.

### REQ-BOOT-003: Transcript Loading and Empty Skip {#REQ-BOOT-003}
- **Traces-to**: SC-BOOT-002
- **Type**: FUNCTIONAL
- **Description**: Each discovered transcript file path is passed to `load_transcript(path)` from `common.py` (imported, not reimplemented). The function returns a `list[dict]` of messages. If the returned list is empty (no valid user/assistant messages after filtering), the session is skipped -- the skip is logged via the progress event format in REQ-BOOT-011 with reason `"empty transcript"` and the session is NOT recorded in the state file (so it will be retried on subsequent runs in case the file was still being written).
- **Acceptance**: A `.jsonl` file containing only `{"type":"system","message":{}}` lines produces an empty list from `load_transcript()` and is skipped with the correct log message.

### REQ-BOOT-004: Async Per-Session Pipeline {#REQ-BOOT-004}
- **Traces-to**: SC-BOOT-003
- **Type**: FUNCTIONAL
- **Description**: Each non-empty transcript is processed through the following pipeline steps, in this exact order:
  ```
  1. cited_ids = extract_cited_ids(messages)
  2. reflector_output = await run_reflector(messages, playbook, cited_ids)
  3. apply_bullet_tags(playbook, reflector_output.get("bullet_tags", []))
  4. curator_output = await run_curator(reflector_output, playbook)
  5. playbook = apply_structured_operations(playbook, curator_output.get("operations", []))
  6. playbook = run_deduplication(playbook)
  7. playbook = prune_harmful(playbook)
  ```
  Steps 2 and 4 are `await` calls (async functions). The overall script structure is `async def main()` containing the session loop, invoked via `asyncio.run(main())` in the `if __name__ == "__main__"` block. All pipeline functions are imported from `common.py`.
  If `run_reflector()` returns an empty result (`{"analysis": "", "bullet_tags": []}`), the pipeline is considered failed for this session. The session is skipped per REQ-BOOT-010 with reason `"pipeline failed (reflector returned empty)"`.
  If `run_curator()` returns an empty result (`{"reasoning": "", "operations": []}`), the pipeline is considered failed for this session. The session is skipped per REQ-BOOT-010 with reason `"pipeline failed (curator returned empty)"`.
  When a pipeline failure occurs, the playbook is NOT saved (preserves state from last successful session), the session is NOT recorded in the state file, and the `failed` counter is incremented.
- **Acceptance**: Given a valid transcript with messages, all 7 pipeline steps execute in order. The `playbook` variable is mutated in-place by steps 3 and 7 and reassigned by steps 5 and 6.

### REQ-BOOT-005: Save Playbook After Each Session {#REQ-BOOT-005}
- **Traces-to**: SC-BOOT-003
- **Type**: FUNCTIONAL
- **Description**: After each successful session pipeline completion (all 7 steps in REQ-BOOT-004 completed without skipping), `save_playbook(playbook)` from `common.py` is called to persist the playbook to disk. This ensures that if the process is interrupted (Ctrl+C, crash), all progress from completed sessions is preserved.
- **Acceptance**: After processing session K, `playbook.json` on disk reflects the cumulative state of sessions 1..K.

### REQ-BOOT-006: Chronological Ordering by mtime {#REQ-BOOT-006}
- **Traces-to**: SC-BOOT-004
- **Type**: FUNCTIONAL
- **Description**: After discovery (REQ-BOOT-001), ALL transcript files (top-level sessions AND subagent transcripts) are combined into a single list and sorted by file modification time (`os.path.getmtime()` or `Path.stat().st_mtime`) in ascending order (oldest first). There is no separate "sessions first, subagents second" pass -- the list is a single interleaved chronological sequence. The sorted list is then filtered by the state file (already-processed sessions removed) before processing begins.
- **Acceptance**: Given files with mtimes [t3, t1, t2], the processing order is [t1, t2, t3].

### REQ-BOOT-007: Cumulative Accumulation {#REQ-BOOT-007}
- **Traces-to**: SC-BOOT-005
- **Type**: BEHAVIORAL
- **Description**: The playbook is loaded exactly once (via `load_playbook()`) before the processing loop begins. The same in-memory `playbook` dict is passed to each session's pipeline. After each session's pipeline modifies the playbook, the updated playbook is used as input for the next session. This means:
  - Session 2's `run_reflector()` receives the playbook as modified by session 1
  - Session 2's `run_curator()` can UPDATE, DELETE, or MERGE entries added by session 1
  - The `apply_bullet_tags()` in session 2 can tag entries from session 1
- **Acceptance**: After processing 2 sessions, the playbook passed to session 2's reflector contains entries added by session 1's curator.

### REQ-BOOT-008: Playbook Format Compatibility {#REQ-BOOT-008}
- **Traces-to**: SC-BOOT-006
- **Type**: CONSTRAINT
- **Description**: The bootstrap script uses ONLY `load_playbook()` and `save_playbook()` from `common.py` for playbook I/O. It does not construct playbook dicts manually, does not modify the playbook structure outside of the pipeline functions, and does not use any custom serialization. The playbook format invariants (INV-SECT-001: sections key always present, INV-SECT-007: no key_points key) are maintained by the common.py functions.
- **Acceptance**: A playbook produced by bootstrap is byte-for-byte structurally identical (same keys, same nesting) to one produced by `session_end.py` processing the same sessions in the same order.

### REQ-BOOT-009: Slash Command File {#REQ-BOOT-009}
- **Traces-to**: SC-BOOT-007
- **Type**: FUNCTIONAL
- **Description**: The file `src/commands/bootstrap-playbook.md` is a Markdown file that serves as a Claude Code slash command template. When invoked via `/bootstrap-playbook` in Claude Code, its content is injected as a prompt to Claude. The content instructs Claude to:
  1. Use `$CLAUDE_PROJECT_DIR` environment variable (set by Claude Code) as the project directory path
  2. Run the bootstrap script via `uv run --project <project-dir> python ~/.claude/hooks/bootstrap_playbook.py`
  3. Report the output to the user
  The exact file content is specified in the Command Template section below.
  The Python script is located at `src/hooks/bootstrap_playbook.py`. Both files are installed to `~/.claude/` by the existing `copyDir(sourceDir, claudeDir)` mechanism in `install.js`.
- **Acceptance**: The file `src/commands/bootstrap-playbook.md` exists, is valid Markdown, and contains the exact content specified in the Command Template section.

### REQ-BOOT-010: Rate Limit Resilience {#REQ-BOOT-010}
- **Traces-to**: SC-BOOT-008
- **Type**: BEHAVIORAL
- **Description**: Sessions are processed strictly sequentially (one at a time, never parallel). After each session completes (success or failure), the script sleeps for a configurable delay before starting the next session. The delay is read from `AGENTIC_CONTEXT_BOOTSTRAP_DELAY` env var (parsed as float, in seconds). If the env var is not set or is not a valid float, the default delay is `2.0` seconds. If a session's pipeline fails (reflector or curator returns empty), the script:
  1. Logs the failure via progress event (REQ-BOOT-011)
  2. Increments the `failed` counter
  3. Does NOT save the playbook
  4. Does NOT record the session in the state file
  5. Continues to the next session after the inter-session delay
  The playbook state is preserved from the last successfully processed session.
- **Acceptance**: With 3 sessions where session 2 fails, the script processes session 1 (success), session 2 (fail, logged), session 3 (success). The playbook reflects sessions 1 and 3. The delay between each session pair is observed.

### REQ-BOOT-011: Progress Reporting Events {#REQ-BOOT-011}
- **Traces-to**: SC-BOOT-009
- **Type**: BEHAVIORAL
- **Description**: All progress events are printed to stderr via `print(..., file=sys.stderr)`. All events are prefixed with `BOOTSTRAP:`. There are exactly five event types with the following format strings (fields in `{braces}` are substituted at runtime):

  **(a) Discovery summary** -- emitted once, after scanning and state-file filtering:
  ```
  BOOTSTRAP: discovered {total} transcript(s) in {project_dir_name} ({session_count} sessions, {subagent_count} subagents), {skipped} already processed, {to_process} to process
  ```
  Where:
  - `{total}` = total files discovered (before state-file filtering)
  - `{project_dir_name}` = the encoded project directory name (e.g., `-Users-zhitingz-Documents-agentic-context-engineering`)
  - `{session_count}` = count of top-level session `.jsonl` files discovered
  - `{subagent_count}` = count of subagent `agent-*.jsonl` files discovered (0 if skip-subagents)
  - `{skipped}` = count of files already in state file
  - `{to_process}` = total - skipped

  **(b) Session start** -- emitted before each session pipeline begins:
  ```
  BOOTSTRAP: [{current}/{to_process}] processing {session_filename} ({file_size_kb:.1f} KB)
  ```
  Where:
  - `{current}` = 1-based index of current session in the to-process list
  - `{to_process}` = total sessions to process (same as discovery summary)
  - `{session_filename}` = the file name only (not full path), e.g., `f7efe581-c057-40f4-88ec-3fb68391abef.jsonl` or `agent-abc123.jsonl`
  - `{file_size_kb:.1f}` = file size in kilobytes, formatted to one decimal place

  **(c) Session skip** -- emitted when a session is skipped for any reason:
  ```
  BOOTSTRAP: [{current}/{to_process}] skipped {session_filename}: {reason}
  ```
  Where `{reason}` is one of:
  - `empty transcript`
  - `pipeline failed (reflector returned empty)`
  - `pipeline failed (curator returned empty)`
  - `pipeline failed (unexpected error)`
  - `transcript too large ({size_mb:.1f} MB, max {max_mb:.1f} MB)` (where size_mb and max_mb are substituted, both formatted as `:.1f`)
  - `already processed` (used in the state-file filtering count, but NOT emitted as individual per-session events -- the count is reported in the discovery summary instead)

  **(d) Session complete** -- emitted after each successful session pipeline:
  ```
  BOOTSTRAP: [{current}/{to_process}] completed {session_filename} in {duration:.1f}s (playbook: {keypoint_count} key points, delta: +{added} -{removed})
  ```
  Where:
  - `{duration:.1f}` = wall-clock time for this session's pipeline in seconds
  - `{keypoint_count}` = total key points across all sections in the playbook after this session
  - `{added}` = number of key points added by this session (keypoint_count_after - keypoint_count_before + removed)
  - `{removed}` = number of key points removed by this session (keypoint_count_before + added_raw - keypoint_count_after, where added_raw and removed are computed by comparing before/after counts)

  **Simplified delta computation**: Count total keypoints before the pipeline (`count_before`), count after (`count_after`). `delta = count_after - count_before`. If `delta >= 0`: `added = delta`, `removed = 0`. If `delta < 0`: `added = 0`, `removed = abs(delta)`. This is an approximation (does not capture simultaneous adds+removes) but is sufficient for progress reporting.

  **(e) Final summary** -- emitted once, after all sessions:
  ```
  BOOTSTRAP: complete. {processed} processed, {skipped} skipped, {failed} failed. Playbook: {total_keypoints} key points. Elapsed: {total_elapsed:.0f}s
  ```
  Where:
  - `{processed}` = sessions successfully completed
  - `{skipped}` = sessions skipped (empty transcript + too large + already processed from state file)
  - `{failed}` = sessions where pipeline failed (reflector empty, curator empty, or unexpected exception)
  - `{total_keypoints}` = total key points across all sections in final playbook
  - `{total_elapsed:.0f}` = total wall-clock time in seconds, rounded to integer

  **Counter identity (INV-BOOT-010)**: `processed + skipped + failed == total` where `total` is the count from the discovery summary (event (a) above). `skipped` includes already-processed sessions (from state file) + empty transcripts + too-large transcripts. `failed` includes reflector-returned-empty + curator-returned-empty + unexpected exceptions. This identity must hold after every run.

  **Keypoint count helper**: Total keypoints is computed by summing `len(entries)` across all sections:
  ```python
  def count_keypoints(playbook: dict) -> int:
      return sum(len(entries) for entries in playbook.get("sections", {}).values())
  ```
  This helper is defined in `bootstrap_playbook.py` (not in common.py per CON-BOOT-002).
- **Acceptance**: Running bootstrap against a project with 3 sessions (1 empty, 1 valid, 1 valid) produces exactly: 1 discovery summary, 2 session-start events (for non-already-processed), 1 skip event (empty), 2 complete events (or 1 complete + 1 fail), 1 final summary. All format strings match exactly.

### REQ-BOOT-012: State File Management {#REQ-BOOT-012}
- **Traces-to**: SC-BOOT-010
- **Type**: FUNCTIONAL
- **Description**: The state file is located at `{CLAUDE_PROJECT_DIR}/.claude/bootstrap_state.json`. The schema is:
  ```json
  {
    "version": "1.0",
    "processed_sessions": {
      "<absolute_file_path>": {
        "processed_at": "<ISO8601 timestamp>",
        "key_points_after": <int>
      }
    }
  }
  ```
  Where:
  - `<absolute_file_path>` = the absolute path to the `.jsonl` file (string, used as dict key)
  - `processed_at` = ISO 8601 timestamp of when the session was processed (`datetime.now().isoformat()`)
  - `key_points_after` = total keypoint count in the playbook after processing this session
  The state file is loaded at startup. Already-processed sessions (keys present in `processed_sessions`) are excluded from the to-process list. After each successful session, the state file is updated with the new session entry and written atomically (REQ-BOOT-013).
  If the state file does not exist, it is treated as empty (all sessions are unprocessed).
- **Acceptance**: After processing 3 sessions, the state file contains exactly 3 entries in `processed_sessions`, each with the correct file path and timestamp.

### REQ-BOOT-013: Atomic State File Write {#REQ-BOOT-013}
- **Traces-to**: SC-BOOT-010
- **Type**: FUNCTIONAL
- **Description**: Every write to the state file uses a two-step atomic write pattern:
  1. Write the JSON content to a temporary file at `{CLAUDE_PROJECT_DIR}/.claude/bootstrap_state.json.tmp`
  2. Call `os.replace("{CLAUDE_PROJECT_DIR}/.claude/bootstrap_state.json.tmp", "{CLAUDE_PROJECT_DIR}/.claude/bootstrap_state.json")`
  `os.replace()` is atomic on POSIX systems (single rename syscall). This prevents corruption if the process is killed mid-write. The `.claude/` directory is created if it does not exist (`mkdir -p` equivalent via `Path.mkdir(parents=True, exist_ok=True)`).
- **Acceptance**: If the process is killed during a state file write, the state file on disk is either the old version (if killed before `os.replace`) or the new version (if killed after). It is never a partial write.

### REQ-BOOT-014: Preserve Existing Playbook {#REQ-BOOT-014}
- **Traces-to**: SC-BOOT-011
- **Type**: BEHAVIORAL
- **Description**: The playbook is loaded via `load_playbook()` before the processing loop begins. If a `playbook.json` exists, its contents (including all existing key points, sections, scores) are loaded into the in-memory playbook. The bootstrap script never calls `_default_playbook()` directly or overwrites the playbook at the start. The loaded playbook is passed to session 1's pipeline, making existing entries visible to the reflector and curator for tagging, updating, merging, or deduplication.
- **Acceptance**: Given an existing playbook with 5 key points, after bootstrap processes 2 sessions, the playbook contains the original 5 key points (possibly modified by the curator) plus any new entries from the 2 sessions.

### REQ-BOOT-015: Subagent Transcript Inclusion {#REQ-BOOT-015}
- **Traces-to**: SC-BOOT-012
- **Type**: FUNCTIONAL
- **Description**: By default, the discovery step (REQ-BOOT-001) includes subagent transcripts via the glob pattern `*/subagents/agent-*.jsonl`. Each subagent transcript is processed through the identical pipeline as top-level sessions (REQ-BOOT-004). Subagent transcripts are sorted alongside top-level sessions by mtime (REQ-BOOT-006) into a single interleaved list. When `AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS=true` (env var), the subagent glob is not executed and `subagent_count` in the discovery summary is reported as `0`.
- **Acceptance**: With skip-subagents unset, subagent files are discovered, sorted, and processed. With skip-subagents set to `"true"`, only top-level sessions are discovered.

### REQ-BOOT-016: API Key Verification {#REQ-BOOT-016}
- **Traces-to**: CON-BOOT-005
- **Type**: CONSTRAINT
- **Description**: Before any processing begins (before discovery), the script checks for an API key by reading env vars in this order: `AGENTIC_CONTEXT_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`. If none of these env vars is set (or all are empty strings), the script prints an error to stderr and exits with code 1:
  ```
  BOOTSTRAP: error: no API key found. Set AGENTIC_CONTEXT_API_KEY, ANTHROPIC_AUTH_TOKEN, or ANTHROPIC_API_KEY.
  ```
  The script does NOT validate that the key is actually valid (no test API call). It only checks that a non-empty value exists.
- **Acceptance**: With no API key env vars set, the script exits with code 1 and the exact error message. With any one of the three set, the script proceeds.

### REQ-BOOT-017: CLAUDE_PROJECT_DIR Verification {#REQ-BOOT-017}
- **Traces-to**: CON-BOOT-006
- **Type**: CONSTRAINT
- **Description**: Before any processing begins, the script checks that `CLAUDE_PROJECT_DIR` env var is set and non-empty. If unset or empty, the script prints an error to stderr and exits with code 1:
  ```
  BOOTSTRAP: error: CLAUDE_PROJECT_DIR is not set. Run this command from within a Claude Code session.
  ```
- **Acceptance**: With `CLAUDE_PROJECT_DIR` unset, the script exits with code 1 and the exact error message.

### REQ-BOOT-018: Template File Prerequisite Check {#REQ-BOOT-018}
- **Traces-to**: CON-BOOT-008
- **Type**: CONSTRAINT
- **Description**: Before any processing begins (after API key and project dir checks), the script verifies that the following template files exist:
  - `~/.claude/prompts/reflector.txt`
  - `~/.claude/prompts/curator.txt`
  - `~/.claude/prompts/playbook.txt`
  If any template file is missing, the script prints an error to stderr and exits with code 1:
  ```
  BOOTSTRAP: error: required template not found: {missing_path}
  ```
  Where `{missing_path}` is the absolute path to the first missing template file. All three are checked before exiting (report the first missing one).
- **Acceptance**: With `reflector.txt` missing, the script exits with code 1 and reports the missing path.

### REQ-BOOT-019: Large Transcript Guard {#REQ-BOOT-019}
- **Traces-to**: FM-BOOT-012
- **Type**: FUNCTIONAL
- **Description**: Before loading a transcript (before calling `load_transcript()`), the script checks the file size in bytes via `Path.stat().st_size`. The maximum allowed size is configurable via `AGENTIC_CONTEXT_MAX_TRANSCRIPT_MB` env var (parsed as float, in megabytes). If the env var is not set or is not a valid float, the default maximum is `5.0` MB. If the file size exceeds the maximum (in bytes: `max_mb * 1024 * 1024`), the session is skipped with a progress event:
  ```
  BOOTSTRAP: [{current}/{to_process}] skipped {session_filename}: transcript too large ({size_mb:.1f} MB, max {max_mb:.1f} MB)
  ```
  Where `{size_mb:.1f}` is the actual file size in MB and `{max_mb:.1f}` is the configured maximum, both formatted as `:.1f` (one decimal place). The skipped session is counted in the `skipped` counter (not `failed`). The session is NOT recorded in the state file (so a future run with a higher limit can process it).
- **Acceptance**: A 6 MB transcript file is skipped with the correct log message when the default 5 MB limit is in effect. A 4 MB transcript file is NOT skipped.

---

## Invariants

### INV-BOOT-001: Pipeline Step Order {#INV-BOOT-001}
- **Description**: For every session processed, the pipeline steps execute in the exact order specified in REQ-BOOT-004. No step may be reordered, skipped (unless the pipeline is aborted due to empty reflector/curator output), or executed in parallel.
- **Traces-to**: SC-BOOT-003

### INV-BOOT-002: Single Asyncio Event Loop {#INV-BOOT-002}
- **Description**: The script uses exactly one `asyncio.run(main())` call. All `await` calls (run_reflector, run_curator) occur within the single `async def main()` coroutine. No nested event loops, no `loop.run_until_complete()`, no threads with separate event loops.
- **Traces-to**: SC-BOOT-003

### INV-BOOT-003: Monotonic Processing Order {#INV-BOOT-003}
- **Description**: Sessions are processed in strictly ascending mtime order. Once sorted, the order is never reshuffled. Session N+1 always has `mtime >= mtime` of session N.
- **Traces-to**: SC-BOOT-004

### INV-BOOT-004: Cumulative Playbook Identity {#INV-BOOT-004}
- **Description**: The same in-memory `playbook` dict object (or its reassigned successor from `apply_structured_operations` / `run_deduplication`) is passed to every session's pipeline. There is no `load_playbook()` call inside the loop. The playbook is loaded exactly once before the loop.
- **Traces-to**: SC-BOOT-005

### INV-BOOT-005: No Direct Playbook Construction {#INV-BOOT-005}
- **Description**: The bootstrap script never creates a playbook dict manually (no `{"version": ..., "sections": ...}` literals). All playbook creation/loading is via `load_playbook()` from common.py.
- **Traces-to**: SC-BOOT-006

### INV-BOOT-006: Sequential Processing {#INV-BOOT-006}
- **Description**: At most one session pipeline is executing at any time. No `asyncio.gather()`, no `asyncio.create_task()` for parallel sessions. The session loop is a simple `for` loop with `await` calls inside.
- **Traces-to**: SC-BOOT-008

### INV-BOOT-007: Progress Event Format Compliance {#INV-BOOT-007}
- **Description**: Every progress event printed to stderr matches one of the defined format strings in REQ-BOOT-011 (five event types; six valid reason strings for skip events). No ad-hoc print statements. All bootstrap output to stderr uses the `BOOTSTRAP:` prefix.
- **Traces-to**: SC-BOOT-009

### INV-BOOT-008: State File Atomicity {#INV-BOOT-008}
- **Description**: Every write to the state file goes through the temp-file + `os.replace()` pattern in REQ-BOOT-013. No direct writes to `bootstrap_state.json`.
- **Traces-to**: SC-BOOT-010

### INV-BOOT-009: Playbook Never Reset {#INV-BOOT-009}
- **Description**: The bootstrap script never calls `_default_playbook()`, never assigns `playbook = {}`, and never overwrites the playbook with an empty structure. The playbook only grows or is modified through the pipeline functions.
- **Traces-to**: SC-BOOT-011

### INV-BOOT-010: Counter Identity {#INV-BOOT-010}
- **Description**: After the processing loop completes, `processed + skipped + failed == total` where `total` is the count from the discovery summary (REQ-BOOT-011(a)). `skipped` includes already-processed sessions (from state file) + empty transcripts + too-large transcripts. `failed` includes reflector-returned-empty + curator-returned-empty + unexpected exceptions. This identity holds regardless of which sessions succeed, fail, or are skipped.
- **Traces-to**: SC-BOOT-009

---

## Scenarios

### SCN-BOOT-001-01: Happy Path -- Session Discovery with Sessions and Subagents {#SCN-BOOT-001-01}
- **Implements**: REQ-BOOT-001
- **GIVEN**: `CLAUDE_PROJECT_DIR=/Users/zhitingz/Documents/agentic_context_engineering` and the transcript directory contains 3 top-level `.jsonl` files and 5 `agent-*.jsonl` files in `*/subagents/` subdirectories
- **WHEN**: The bootstrap script runs discovery
- **THEN**: 8 files are discovered total (3 sessions + 5 subagents)

### SCN-BOOT-001-02: Session Discovery with SKIP_SUBAGENTS {#SCN-BOOT-001-02}
- **Implements**: REQ-BOOT-001
- **GIVEN**: Same as SCN-BOOT-001-01 but `AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS=true`
- **WHEN**: The bootstrap script runs discovery
- **THEN**: Only 3 top-level `.jsonl` files are discovered. `subagent_count` in discovery summary is `0`.

### SCN-BOOT-001-03: Session Discovery with Transcript Dir Override {#SCN-BOOT-001-03}
- **Implements**: REQ-BOOT-001
- **GIVEN**: `AGENTIC_CONTEXT_TRANSCRIPT_DIR=/tmp/test-transcripts` and that directory contains 2 `.jsonl` files
- **WHEN**: The bootstrap script runs discovery
- **THEN**: The encoding algorithm is not invoked. 2 files are discovered from the override path.

### SCN-BOOT-001-04: Session Discovery with Non-Existent Directory {#SCN-BOOT-001-04}
- **Implements**: REQ-BOOT-001
- **GIVEN**: The computed transcript directory does not exist
- **WHEN**: The bootstrap script runs discovery
- **THEN**: 0 files are discovered. The discovery summary reports `0 transcript(s)`. The script completes normally (exit code 0) after printing the final summary with 0 processed, 0 skipped, 0 failed.

### SCN-BOOT-003-01: Transcript Loading -- Valid Transcript {#SCN-BOOT-003-01}
- **Implements**: REQ-BOOT-003
- **GIVEN**: A `.jsonl` file with valid user and assistant message entries
- **WHEN**: `load_transcript(path)` is called
- **THEN**: Returns a non-empty list of message dicts. The session proceeds to the pipeline.

### SCN-BOOT-003-02: Transcript Loading -- Empty Result {#SCN-BOOT-003-02}
- **Implements**: REQ-BOOT-003
- **GIVEN**: A `.jsonl` file with only system/meta messages (no valid user/assistant pairs)
- **WHEN**: `load_transcript(path)` is called
- **THEN**: Returns an empty list. The session is skipped with reason `"empty transcript"`.

### SCN-BOOT-004-01: Pipeline Success {#SCN-BOOT-004-01}
- **Implements**: REQ-BOOT-004
- **GIVEN**: A non-empty transcript and functioning API
- **WHEN**: The per-session pipeline executes
- **THEN**: All 7 steps execute in order. The playbook is modified. `save_playbook()` is called. The session is recorded in the state file. The `processed` counter is incremented.

### SCN-BOOT-004-02: Pipeline Failure -- Reflector Returns Empty {#SCN-BOOT-004-02}
- **Implements**: REQ-BOOT-004
- **GIVEN**: A non-empty transcript but `run_reflector()` returns `{"analysis": "", "bullet_tags": []}`
- **WHEN**: The per-session pipeline executes
- **THEN**: The pipeline is aborted after step 2. The playbook is NOT saved. The session is NOT recorded in the state file. The skip event is logged with reason `"pipeline failed (reflector returned empty)"`. The `failed` counter is incremented.

### SCN-BOOT-004-03: Pipeline Failure -- Curator Returns Empty {#SCN-BOOT-004-03}
- **Implements**: REQ-BOOT-004
- **GIVEN**: A non-empty session transcript AND `run_reflector()` returns a non-empty result AND `run_curator()` returns empty `operations` (`{"reasoning": "", "operations": []}`)
- **WHEN**: The per-session pipeline executes
- **THEN**:
  - `apply_bullet_tags()` is called with the reflector output
  - `run_curator()` is awaited and returns empty operations
  - The pipeline aborts at the curator check
  - `skip` event emitted: `BOOTSTRAP: [{current}/{to_process}] skipped {filename}: pipeline failed (curator returned empty)`
  - Playbook is NOT saved for this session
  - Session is NOT recorded in state file
  - `failed` counter is incremented
  - Processing continues to the next session
  - Inter-session delay is applied

### SCN-BOOT-004-04: Pipeline Failure -- Unexpected Exception {#SCN-BOOT-004-04}
- **Implements**: REQ-BOOT-004, REQ-BOOT-010
- **GIVEN**: A non-empty session transcript AND an unexpected exception (e.g., `RuntimeError`) is raised during any pipeline step after `load_transcript()`
- **WHEN**: The per-session pipeline executes
- **THEN**:
  - The exception is caught by the catch-all handler
  - `skip` event emitted: `BOOTSTRAP: [{current}/{to_process}] skipped {filename}: pipeline failed (unexpected error)`
  - Playbook is NOT saved for this session
  - Session is NOT recorded in state file
  - `failed` counter is incremented
  - Processing continues to the next session
  - Inter-session delay is applied

### SCN-BOOT-006-01: Chronological Interleaving {#SCN-BOOT-006-01}
- **Implements**: REQ-BOOT-006
- **GIVEN**: 2 top-level sessions (mtime: t1, t3) and 1 subagent transcript (mtime: t2, where t1 < t2 < t3)
- **WHEN**: Files are sorted for processing
- **THEN**: Processing order is: session(t1), subagent(t2), session(t3)

### SCN-BOOT-007-01: Cumulative Playbook Across Sessions {#SCN-BOOT-007-01}
- **Implements**: REQ-BOOT-007
- **GIVEN**: An empty playbook and 2 sessions to process
- **WHEN**: Session 1 is processed and adds 3 key points
- **THEN**: Session 2's `run_reflector()` receives a playbook containing those 3 key points

### SCN-BOOT-008-01: Playbook Format After Bootstrap {#SCN-BOOT-008-01}
- **Implements**: REQ-BOOT-008
- **GIVEN**: Bootstrap processes 3 sessions
- **WHEN**: The final `playbook.json` is loaded by `load_playbook()`
- **THEN**: The playbook has a `"sections"` key, no `"key_points"` key, a `"version"` key, and a `"last_updated"` key. All section names are from the canonical set.

### SCN-BOOT-009-01: Slash Command Invocation {#SCN-BOOT-009-01}
- **Implements**: REQ-BOOT-009
- **GIVEN**: The user types `/bootstrap-playbook` in Claude Code
- **WHEN**: Claude reads the command template
- **THEN**: Claude executes the bootstrap script via `uv run` and reports the stderr output to the user

### SCN-BOOT-010-01: Inter-Session Delay {#SCN-BOOT-010-01}
- **Implements**: REQ-BOOT-010
- **GIVEN**: 2 sessions to process with default delay (2s)
- **WHEN**: Session 1 completes
- **THEN**: The script sleeps for 2.0 seconds before starting session 2

### SCN-BOOT-010-02: Custom Delay via Env Var {#SCN-BOOT-010-02}
- **Implements**: REQ-BOOT-010
- **GIVEN**: `AGENTIC_CONTEXT_BOOTSTRAP_DELAY=5.0`
- **WHEN**: Session 1 completes
- **THEN**: The script sleeps for 5.0 seconds before starting session 2

### SCN-BOOT-010-03: Pipeline Failure Does Not Halt Processing {#SCN-BOOT-010-03}
- **Implements**: REQ-BOOT-010
- **GIVEN**: 3 sessions where session 2's reflector returns empty
- **WHEN**: The processing loop reaches session 2
- **THEN**: Session 2 is logged as failed, and session 3 is still processed

### SCN-BOOT-011-01: Discovery Summary Event {#SCN-BOOT-011-01}
- **Implements**: REQ-BOOT-011
- **GIVEN**: 10 total transcripts discovered (7 sessions, 3 subagents), 2 already processed
- **WHEN**: Discovery completes
- **THEN**: Stderr receives: `BOOTSTRAP: discovered 10 transcript(s) in -Users-zhitingz-Documents-agentic-context-engineering (7 sessions, 3 subagents), 2 already processed, 8 to process`

### SCN-BOOT-011-02: Session Start Event {#SCN-BOOT-011-02}
- **Implements**: REQ-BOOT-011
- **GIVEN**: Processing the 3rd of 8 sessions, file `abc123.jsonl` is 245.7 KB
- **WHEN**: The pipeline begins for this session
- **THEN**: Stderr receives: `BOOTSTRAP: [3/8] processing abc123.jsonl (245.7 KB)`

### SCN-BOOT-011-03: Session Skip Event {#SCN-BOOT-011-03}
- **Implements**: REQ-BOOT-011
- **GIVEN**: Processing session 2 of 8, file `def456.jsonl` has empty transcript
- **WHEN**: `load_transcript()` returns empty
- **THEN**: Stderr receives: `BOOTSTRAP: [2/8] skipped def456.jsonl: empty transcript`

### SCN-BOOT-011-04: Session Complete Event {#SCN-BOOT-011-04}
- **Implements**: REQ-BOOT-011
- **GIVEN**: Session 1 of 8 completed in 12.3 seconds, playbook now has 5 key points (was 0, so delta +5 -0)
- **WHEN**: The pipeline completes
- **THEN**: Stderr receives: `BOOTSTRAP: [1/8] completed abc123.jsonl in 12.3s (playbook: 5 key points, delta: +5 -0)`

### SCN-BOOT-011-05: Final Summary Event {#SCN-BOOT-011-05}
- **Implements**: REQ-BOOT-011
- **GIVEN**: 6 processed, 1 skipped, 1 failed, 15 total keypoints, 95 seconds elapsed
- **WHEN**: The processing loop finishes
- **THEN**: Stderr receives: `BOOTSTRAP: complete. 6 processed, 1 skipped, 1 failed. Playbook: 15 key points. Elapsed: 95s`

### SCN-BOOT-012-01: State File -- First Run {#SCN-BOOT-012-01}
- **Implements**: REQ-BOOT-012
- **GIVEN**: No state file exists (`.claude/bootstrap_state.json` does not exist)
- **WHEN**: The bootstrap script starts
- **THEN**: All discovered sessions are treated as unprocessed. After processing, the state file is created with entries for each processed session.

### SCN-BOOT-012-02: State File -- Resume After Interruption {#SCN-BOOT-012-02}
- **Implements**: REQ-BOOT-012
- **GIVEN**: State file exists with 3 processed sessions. 5 total sessions discovered.
- **WHEN**: The bootstrap script starts
- **THEN**: 2 sessions are to-process (5 - 3). The 3 already-processed sessions are skipped.

### SCN-BOOT-012-03: State File -- Corrupted JSON {#SCN-BOOT-012-03}
- **Implements**: REQ-BOOT-012
- **GIVEN**: State file exists but contains invalid JSON (e.g., `{truncated`)
- **WHEN**: The bootstrap script loads the state file
- **THEN**: A warning is printed to stderr: `BOOTSTRAP: warning: state file corrupted, treating all sessions as unprocessed`. All sessions are treated as unprocessed.

### SCN-BOOT-012-04: State File -- Atomic Write on Kill {#SCN-BOOT-012-04}
- **Implements**: REQ-BOOT-013
- **GIVEN**: The script is killed (SIGKILL) during state file write
- **WHEN**: The script restarts
- **THEN**: The state file is either the previous version (kill before `os.replace()`) or the new version (kill after `os.replace()`). No partial JSON.

### SCN-BOOT-014-01: Existing Playbook Preserved {#SCN-BOOT-014-01}
- **Implements**: REQ-BOOT-014
- **GIVEN**: An existing `playbook.json` with 5 key points across 3 sections
- **WHEN**: Bootstrap starts and loads the playbook
- **THEN**: All 5 key points are present in the in-memory playbook passed to session 1's pipeline. The reflector and curator can see and operate on them.

### SCN-BOOT-015-01: Subagent Transcripts Processed {#SCN-BOOT-015-01}
- **Implements**: REQ-BOOT-015
- **GIVEN**: 2 top-level sessions and 3 subagent transcripts, skip-subagents not set
- **WHEN**: Bootstrap runs
- **THEN**: All 5 transcripts are processed through the same pipeline. The discovery summary reports `(2 sessions, 3 subagents)`.

### SCN-BOOT-015-02: Subagent Transcripts Skipped {#SCN-BOOT-015-02}
- **Implements**: REQ-BOOT-015
- **GIVEN**: 2 top-level sessions and 3 subagent transcripts, `AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS=true`
- **WHEN**: Bootstrap runs
- **THEN**: Only 2 top-level sessions are processed. The discovery summary reports `(2 sessions, 0 subagents)`.

---

## Pseudocode

This pseudocode is the authoritative implementation reference for `src/hooks/bootstrap_playbook.py`. The Coding Agent should translate this to Python, preserving the exact structure, variable names, error handling, and progress event format strings.

```python
#!/usr/bin/env python3
# Module: bootstrap_playbook -- Batch-process historic session transcripts
#         to seed/populate the playbook.
#
# Spec: docs/bootstrap/spec.md
import json
import os
import sys
import time
import asyncio
from pathlib import Path
from datetime import datetime

from common import (
    load_playbook,
    save_playbook,
    load_transcript,
    extract_cited_ids,
    run_reflector,
    apply_bullet_tags,
    run_curator,
    apply_structured_operations,
    run_deduplication,
    prune_harmful,
)

# --- Helper: keypoint counter ---
# @implements REQ-BOOT-011
def count_keypoints(playbook: dict) -> int:
    """Count total key points across all sections."""
    return sum(len(entries) for entries in playbook.get("sections", {}).values())


# --- Helper: project dir encoding ---
# @implements REQ-BOOT-002
def encode_project_dir(project_dir: str) -> str:
    """Encode CLAUDE_PROJECT_DIR to ~/.claude/projects/ subdirectory name.

    Algorithm: replace '/' -> '-', '.' -> '-', '_' -> '-'
    """
    return project_dir.replace("/", "-").replace(".", "-").replace("_", "-")


# --- Helper: state file I/O ---
# @implements REQ-BOOT-012, REQ-BOOT-013
def load_state(state_path: Path) -> dict:
    """Load bootstrap state file. Returns default if missing or corrupted."""
    if not state_path.exists():
        return {"version": "1.0", "processed_sessions": {}}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "processed_sessions" not in data:
            print("BOOTSTRAP: warning: state file corrupted, treating all sessions as unprocessed",
                  file=sys.stderr)
            return {"version": "1.0", "processed_sessions": {}}
        return data
    except (json.JSONDecodeError, OSError):
        print("BOOTSTRAP: warning: state file corrupted, treating all sessions as unprocessed",
              file=sys.stderr)
        return {"version": "1.0", "processed_sessions": {}}


def save_state(state_path: Path, state: dict):
    """Atomically save bootstrap state file via temp + os.replace()."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_suffix(".json.tmp")  # produces bootstrap_state.json.tmp
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(str(tmp_path), str(state_path))


async def main():
    # ============================================================
    # PHASE 0: Prerequisite checks (REQ-BOOT-016, REQ-BOOT-017, REQ-BOOT-018)
    # ============================================================

    # REQ-BOOT-017: CLAUDE_PROJECT_DIR must be set
    project_dir = os.getenv("CLAUDE_PROJECT_DIR")
    if not project_dir:
        print("BOOTSTRAP: error: CLAUDE_PROJECT_DIR is not set. Run this command from within a Claude Code session.",
              file=sys.stderr)
        sys.exit(1)

    # REQ-BOOT-016: API key must be available
    api_key = (
        os.getenv("AGENTIC_CONTEXT_API_KEY")
        or os.getenv("ANTHROPIC_AUTH_TOKEN")
        or os.getenv("ANTHROPIC_API_KEY")
    )
    if not api_key:
        print("BOOTSTRAP: error: no API key found. Set AGENTIC_CONTEXT_API_KEY, ANTHROPIC_AUTH_TOKEN, or ANTHROPIC_API_KEY.",
              file=sys.stderr)
        sys.exit(1)

    # REQ-BOOT-018: Template files must exist
    user_claude_dir = Path.home() / ".claude"
    required_templates = ["reflector.txt", "curator.txt", "playbook.txt"]
    for template_name in required_templates:
        template_path = user_claude_dir / "prompts" / template_name
        if not template_path.exists():
            print(f"BOOTSTRAP: error: required template not found: {template_path}",
                  file=sys.stderr)
            sys.exit(1)

    # ============================================================
    # PHASE 1: Configuration (env vars with defaults)
    # ============================================================

    skip_subagents = os.getenv("AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS") == "true"

    try:
        inter_session_delay = float(os.getenv("AGENTIC_CONTEXT_BOOTSTRAP_DELAY", "2.0"))
    except ValueError:
        inter_session_delay = 2.0

    try:
        max_transcript_mb = float(os.getenv("AGENTIC_CONTEXT_MAX_TRANSCRIPT_MB", "5.0"))
    except ValueError:
        max_transcript_mb = 5.0

    max_transcript_bytes = max_transcript_mb * 1024 * 1024

    # ============================================================
    # PHASE 2: Session discovery (REQ-BOOT-001, REQ-BOOT-002)
    # ============================================================

    transcript_dir_override = os.getenv("AGENTIC_CONTEXT_TRANSCRIPT_DIR")
    if transcript_dir_override:
        transcript_dir = Path(transcript_dir_override)
    else:
        encoded = encode_project_dir(project_dir)
        transcript_dir = Path.home() / ".claude" / "projects" / encoded

    project_dir_name = transcript_dir.name

    # Discover files
    session_files = sorted(transcript_dir.glob("*.jsonl")) if transcript_dir.exists() else []
    if not skip_subagents and transcript_dir.exists():
        subagent_files = sorted(transcript_dir.glob("*/subagents/agent-*.jsonl"))
    else:
        subagent_files = []

    session_count = len(session_files)
    subagent_count = len(subagent_files)

    # REQ-BOOT-006: Combine and sort by mtime ascending
    all_files = session_files + subagent_files
    all_files.sort(key=lambda f: f.stat().st_mtime)

    total = len(all_files)

    # ============================================================
    # PHASE 3: State file loading (REQ-BOOT-012)
    # ============================================================

    state_path = Path(project_dir) / ".claude" / "bootstrap_state.json"
    state = load_state(state_path)

    # Filter out already-processed
    already_processed_count = 0
    to_process_files = []
    for f in all_files:
        if str(f) in state["processed_sessions"]:
            already_processed_count += 1
        else:
            to_process_files.append(f)

    to_process = len(to_process_files)

    # REQ-BOOT-011(a): Discovery summary
    print(f"BOOTSTRAP: discovered {total} transcript(s) in {project_dir_name} "
          f"({session_count} sessions, {subagent_count} subagents), "
          f"{already_processed_count} already processed, {to_process} to process",
          file=sys.stderr)

    # ============================================================
    # PHASE 4: Main processing loop
    # ============================================================

    # REQ-BOOT-014: Load existing playbook once (INV-BOOT-004, INV-BOOT-009)
    playbook = load_playbook()

    processed = 0
    skipped = 0     # includes empty transcripts, too-large, already-processed
    failed = 0
    skipped += already_processed_count  # already-processed counted as skipped

    overall_start = time.time()

    for idx, file_path in enumerate(to_process_files, start=1):
        filename = file_path.name
        file_size_bytes = file_path.stat().st_size
        file_size_kb = file_size_bytes / 1024

        # REQ-BOOT-019: Large transcript guard
        if file_size_bytes > max_transcript_bytes:
            size_mb = file_size_bytes / (1024 * 1024)
            print(f"BOOTSTRAP: [{idx}/{to_process}] skipped {filename}: "
                  f"transcript too large ({size_mb:.1f} MB, max {max_transcript_mb:.1f} MB)",
                  file=sys.stderr)
            skipped += 1
            if inter_session_delay > 0 and idx < to_process:
                await asyncio.sleep(inter_session_delay)
            continue

        # REQ-BOOT-011(b): Session start event
        print(f"BOOTSTRAP: [{idx}/{to_process}] processing {filename} ({file_size_kb:.1f} KB)",
              file=sys.stderr)

        session_start = time.time()

        try:
            # REQ-BOOT-003: Load transcript
            messages = load_transcript(str(file_path))

            if not messages:
                print(f"BOOTSTRAP: [{idx}/{to_process}] skipped {filename}: empty transcript",
                      file=sys.stderr)
                skipped += 1
                # Do NOT record in state file -- retry on next run
                if inter_session_delay > 0 and idx < to_process:
                    await asyncio.sleep(inter_session_delay)
                continue

            count_before = count_keypoints(playbook)

            # REQ-BOOT-004: Per-session pipeline (INV-BOOT-001)
            # Step 1
            cited_ids = extract_cited_ids(messages)

            # Step 2 (await -- async)
            reflector_output = await run_reflector(messages, playbook, cited_ids)

            # Check for reflector failure
            if not reflector_output.get("analysis") and not reflector_output.get("bullet_tags"):
                print(f"BOOTSTRAP: [{idx}/{to_process}] skipped {filename}: "
                      f"pipeline failed (reflector returned empty)",
                      file=sys.stderr)
                failed += 1
                if inter_session_delay > 0 and idx < to_process:
                    await asyncio.sleep(inter_session_delay)
                continue

            # Step 3
            apply_bullet_tags(playbook, reflector_output.get("bullet_tags", []))

            # Step 4 (await -- async)
            curator_output = await run_curator(reflector_output, playbook)

            # Check for curator failure
            if not curator_output.get("reasoning") and not curator_output.get("operations"):
                print(f"BOOTSTRAP: [{idx}/{to_process}] skipped {filename}: "
                      f"pipeline failed (curator returned empty)",
                      file=sys.stderr)
                failed += 1
                if inter_session_delay > 0 and idx < to_process:
                    await asyncio.sleep(inter_session_delay)
                continue

            # Step 5
            playbook = apply_structured_operations(playbook, curator_output.get("operations", []))

            # Step 6
            playbook = run_deduplication(playbook)

            # Step 7
            playbook = prune_harmful(playbook)

            # REQ-BOOT-005: Save playbook after each successful session
            save_playbook(playbook)

            count_after = count_keypoints(playbook)

            # Simplified delta computation (REQ-BOOT-011)
            delta = count_after - count_before
            if delta >= 0:
                added = delta
                removed = 0
            else:
                added = 0
                removed = abs(delta)

            duration = time.time() - session_start

            # REQ-BOOT-011(d): Session complete event
            print(f"BOOTSTRAP: [{idx}/{to_process}] completed {filename} in {duration:.1f}s "
                  f"(playbook: {count_after} key points, delta: +{added} -{removed})",
                  file=sys.stderr)

            # REQ-BOOT-012: Update state file
            state["processed_sessions"][str(file_path)] = {
                "processed_at": datetime.now().isoformat(),
                "key_points_after": count_after,
            }
            save_state(state_path, state)

            processed += 1

        except Exception:
            # Catch-all for unexpected errors in a single session
            print(f"BOOTSTRAP: [{idx}/{to_process}] skipped {filename}: "
                  f"pipeline failed (unexpected error)",
                  file=sys.stderr)
            failed += 1

        # REQ-BOOT-010: Inter-session delay
        if inter_session_delay > 0 and idx < to_process:
            await asyncio.sleep(inter_session_delay)

    # ============================================================
    # PHASE 5: Final summary (REQ-BOOT-011(e))
    # ============================================================

    total_elapsed = time.time() - overall_start
    total_keypoints = count_keypoints(playbook)

    print(f"BOOTSTRAP: complete. {processed} processed, {skipped} skipped, {failed} failed. "
          f"Playbook: {total_keypoints} key points. Elapsed: {total_elapsed:.0f}s",
          file=sys.stderr)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBOOTSTRAP: interrupted by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"BOOTSTRAP: fatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
```

### Notes on Pseudocode

1. **Reflector/curator failure detection**: The check `not output.get("analysis") and not output.get("bullet_tags")` detects the empty result `{"analysis": "", "bullet_tags": []}` returned by `run_reflector()` on failure. An empty string is falsy, an empty list is falsy. Similarly for curator with `"reasoning"` and `"operations"`. This means a reflector that returns a non-empty analysis with zero bullet_tags is considered a SUCCESS (it analyzed the session but found nothing to tag), which is correct behavior.

2. **Inter-session delay placement**: The delay is applied after each session (success, skip, or fail) but NOT after the last session. The `idx < to_process` guard prevents an unnecessary sleep at the end. This guard is applied consistently at ALL delay points: the inline `continue` statements (empty transcript, too-large, reflector failure, curator failure) and the bottom-of-loop delay (success and catch-all exception paths).

3. **State file not updated on skip/fail**: When a session is skipped (empty, too large) or fails (pipeline error), it is NOT recorded in the state file. This means the next run will retry it. This is intentional: the file might have been incomplete (still being written), or the API might recover.

4. **KeyboardInterrupt handling**: Ctrl+C is caught separately from other exceptions and exits with code 130 (Unix convention for SIGINT). The playbook is already saved after each successful session, so no data is lost.

5. **`max_transcript_mb` display in log**: Both `size_mb` and `max_transcript_mb` are formatted with `:.1f` (one decimal place) for consistency. The default `5.0` displays as `5.0 MB`.

---

## Command Template

The exact content of `src/commands/bootstrap-playbook.md`:

```markdown
# Bootstrap Playbook

Analyze all historic session transcripts for this project and use them to build up the playbook with accumulated insights.

## Instructions

Run the bootstrap playbook script. The script will:
1. Discover all session transcripts for this project
2. Process each transcript chronologically through the reflector/curator pipeline
3. Build up the playbook cumulatively, saving after each session

Execute this command:

```bash
uv run --project $CLAUDE_PROJECT_DIR python ~/.claude/hooks/bootstrap_playbook.py
```

Report the output to the user. The script prints progress to stderr showing discovery, per-session processing, and a final summary.

If the script reports an error (missing API key, missing templates, etc.), inform the user of the issue and suggest remediation.

This is a long-running operation (may take 30-60+ minutes for projects with many sessions). The script saves progress after each session, so it can be interrupted and resumed.
```

---

## Environment Variables Reference

| Variable | Default | Description | Used By |
|----------|---------|-------------|---------|
| `CLAUDE_PROJECT_DIR` | (required) | Absolute path to the project directory | REQ-BOOT-002, REQ-BOOT-012, REQ-BOOT-017 |
| `AGENTIC_CONTEXT_TRANSCRIPT_DIR` | (none -- use computed path) | Override transcript directory path | REQ-BOOT-001 |
| `AGENTIC_CONTEXT_BOOTSTRAP_SKIP_SUBAGENTS` | (none -- include subagents) | Set to `"true"` to skip subagent transcripts | REQ-BOOT-001, REQ-BOOT-015 |
| `AGENTIC_CONTEXT_BOOTSTRAP_DELAY` | `2.0` | Seconds to sleep between sessions (float) | REQ-BOOT-010 |
| `AGENTIC_CONTEXT_MAX_TRANSCRIPT_MB` | `5.0` | Maximum transcript file size in MB (float) | REQ-BOOT-019 |
| `AGENTIC_CONTEXT_API_KEY` | (none) | API key (highest priority) | REQ-BOOT-016 |
| `ANTHROPIC_AUTH_TOKEN` | (none) | API key (second priority) | REQ-BOOT-016 |
| `ANTHROPIC_API_KEY` | (none) | API key (third priority) | REQ-BOOT-016 |

---

## File Inventory

| File | Location | Installed To | Purpose |
|------|----------|-------------|---------|
| `bootstrap_playbook.py` | `src/hooks/bootstrap_playbook.py` | `~/.claude/hooks/bootstrap_playbook.py` | Python orchestration script |
| `bootstrap-playbook.md` | `src/commands/bootstrap-playbook.md` | `~/.claude/commands/bootstrap-playbook.md` | Slash command template |

---

## Imports from common.py

The bootstrap script imports exactly these functions from `common.py` (no more, no less):

```python
from common import (
    load_playbook,
    save_playbook,
    load_transcript,
    extract_cited_ids,
    run_reflector,
    apply_bullet_tags,
    run_curator,
    apply_structured_operations,
    run_deduplication,
    prune_harmful,
)
```

No other functions from `common.py` are imported. No modifications to `common.py` are made (CON-BOOT-002).

---

## Quality Gates (process verification, not traced to REQ-*)

- **QG-BOOT-001**: No modifications to `common.py` -- verified by git diff.
- **QG-BOOT-002**: All existing tests pass -- verified by `uv run pytest tests/`.
- **QG-BOOT-003**: Import smoke test -- `python -c "import bootstrap_playbook"` succeeds (from `src/hooks/` directory, or equivalent test).
- **QG-BOOT-004**: `src/commands/bootstrap-playbook.md` is valid Markdown -- verified by linter or manual inspection.
