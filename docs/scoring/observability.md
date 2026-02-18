# Observability Specification: Scoring Module

## Overview

The scoring module manages the `playbook.json` lifecycle: loading (with legacy migration), counter updates based on LLM evaluations, pruning of consistently harmful entries, and formatted output for context injection. Observability is needed to verify migration correctness and detect unexpected pruning behavior, especially during the one-time migration from the old `score` field to separate `helpful`/`harmful` counters.

## Instrumentation Approach

This module uses **file-based diagnostics**, not structured metrics or a logging framework. The existing `save_diagnostic()` function (in `src/hooks/common.py`) writes timestamped plain-text files to `.claude/diagnostic/`. All diagnostic output is gated by `is_diagnostic_mode()`, which checks for the presence of a `.claude/diagnostic_mode` flag file in the project directory.

| Component | Mechanism | Gate | Output Location |
|-----------|-----------|------|-----------------|
| `save_diagnostic(content, name)` | Writes `{timestamp}_{name}.txt` | `is_diagnostic_mode()` returns `True` | `{project_dir}/.claude/diagnostic/` |
| `is_diagnostic_mode()` | Checks existence of flag file | N/A (is the gate) | `{project_dir}/.claude/diagnostic_mode` |

## Observability Traceability

| OBS-* | Observability Requirement | LOG-* | Function | File |
|-------|---------------------------|-------|----------|------|
| OBS-SCORE-001 | When migration from old format occurs, log diagnostic with migration details | LOG-SCORE-001 | `load_playbook()` | `src/hooks/common.py` |
| OBS-SCORE-002 | When pruning removes entries, log diagnostic with pruning details | LOG-SCORE-002 | `update_playbook_data()` | `src/hooks/common.py` |
| OBS-SCORE-003 | Per-update counter logging | (non-goal) | N/A | N/A |

## Log Events

### LOG-SCORE-001: Migration Diagnostic Log {#LOG-SCORE-001}

- **Implements**: OBS-SCORE-001
- **Trigger**: `load_playbook()` detects one or more legacy entries during the `key_points` iteration. A legacy entry is any entry that requires migration: a bare string (Branch 1), a dict without `score` or `helpful`/`harmful` fields (Branch 2), or a dict with a `score` field but no `helpful`/`harmful` fields (Branch 3). Entries already in canonical form (Branch 0 -- dict with both `helpful` and `harmful`) do NOT trigger this log.
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"playbook_migration"`
  - `content`: Human-readable text including:
    - Count of migrated entries (integer)
    - Per-entry details: `name`, source format type (`bare_string`, `dict_no_score`, or `dict_with_score`), original `score` value if applicable (`None` for bare strings and dicts without score)
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_playbook_migration.txt`
- **When NOT emitted**: If all entries are already in canonical form (no migration needed), or if `is_diagnostic_mode()` returns `False`.

### LOG-SCORE-002: Pruning Diagnostic Log {#LOG-SCORE-002}

- **Implements**: OBS-SCORE-002
- **Trigger**: `update_playbook_data()` prunes one or more entries (i.e., the pruning step removes at least one key point where `harmful >= 3 AND harmful > helpful`).
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"playbook_pruning"`
  - `content`: Human-readable text including:
    - Count of pruned entries (integer)
    - Per-entry details: `name`, `text` (truncated to 80 characters), `helpful` count, `harmful` count, pruning reason string (e.g., `"harmful >= 3 AND harmful > helpful"` with actual values substituted)
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_playbook_pruning.txt`
- **When NOT emitted**: If no entries are pruned, or if `is_diagnostic_mode()` returns `False`.

## Non-Goals

### OBS-SCORE-003: Per-Update Counter Logging (NOT IMPLEMENTED)

Per-update counter increment logging (i.e., logging each individual `helpful += 1` or `harmful += 1` operation) is explicitly not implemented. Rationale:

- The evaluations are already visible in diagnostic mode via the `extract_keypoints` diagnostic output (which uses the same `save_diagnostic()` mechanism).
- Per-update logging would produce excessive noise: one log line per key point per session.
- The pruning diagnostic (LOG-SCORE-002) is sufficient for detecting misbehavior in the persistent state modifications.
- If a specific counter update needs investigation, the `extract_keypoints` diagnostic output already contains the full LLM response including all evaluations.

## Sensitive Data Handling

- **ALLOW**: Key point `name` (e.g., `kpt_001`), `helpful` count, `harmful` count, source format type, original `score` value.
- **ALLOW with truncation**: Key point `text` is truncated to 80 characters in pruning diagnostics to limit file size while providing enough context for identification.
- **No sensitive data**: Key point text is developer-authored guidance (e.g., "use type hints"), not user PII. No redaction is required.

## Input Sources

- `/data/agentic_context_engineering/.planning/intent.md` -- OBS-SCORE-001, OBS-SCORE-002, OBS-SCORE-003 definitions
- `/data/agentic_context_engineering/docs/scoring/design.md` -- Instrumentation hooks section, diagnostic pattern details
- `/data/agentic_context_engineering/docs/scoring/spec.md` -- REQ-SCORE-004 through REQ-SCORE-007 (migration and pruning requirements)
- `/data/agentic_context_engineering/src/hooks/common.py` -- `save_diagnostic()` and `is_diagnostic_mode()` implementation (lines 27-41)
