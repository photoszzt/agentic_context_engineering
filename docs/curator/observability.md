# Observability Specification: Curator Operations Module

## Overview

The curator operations module extends the playbook lifecycle with structured ADD, UPDATE, MERGE, and DELETE operations. Observability is needed to verify that operations are being applied correctly, detect when the LLM references non-existent IDs (indicating prompt or playbook synchronization issues), audit DELETE and UPDATE operations for accountability, and detect truncation when the LLM exceeds the operations limit.

## Instrumentation Approach

This module uses **file-based diagnostics**, not structured metrics or a logging framework. The existing `save_diagnostic()` function (in `src/hooks/common.py`) writes timestamped plain-text files to `.claude/diagnostic/`. All diagnostic output is gated by `is_diagnostic_mode()`, which checks for the presence of a `.claude/diagnostic_mode` flag file in the project directory.

| Component | Mechanism | Gate | Output Location |
|-----------|-----------|------|-----------------|
| `save_diagnostic(content, name)` | Writes `{timestamp}_{name}.txt` | `is_diagnostic_mode()` returns `True` | `{project_dir}/.claude/diagnostic/` |
| `is_diagnostic_mode()` | Checks existence of flag file | N/A (is the gate) | `{project_dir}/.claude/diagnostic_mode` |

## Observability Traceability

| OBS-* | Observability Requirement | LOG-* | Function | File |
|-------|---------------------------|-------|----------|------|
| OBS-CUR-001 | When operations are applied, log summary: counts per type (applied/skipped), skip reasons, truncation note. Also log if the operations list was truncated due to CON-CUR-004. | LOG-CUR-001 (includes truncation sub-event) | `_apply_curator_operations()` | `src/hooks/common.py` |
| OBS-CUR-002 | When MERGE or DELETE references a non-existent ID, log the specific ID and operation type | LOG-CUR-002 | `_apply_curator_operations()` | `src/hooks/common.py` |
| OBS-CUR-003 | When DELETE is applied, log target_id, deleted entry text (truncated to 80 chars), and reason | LOG-CUR-003 | `_apply_curator_operations()` | `src/hooks/common.py` |
| OBS-CUR-004 | When UPDATE is applied, log target_id, old text (truncated to 80 chars), new text (truncated to 80 chars) for audit trail | LOG-CUR-004 | `_apply_curator_operations()` | `src/hooks/common.py` |

## Log Events

### LOG-CUR-001: Curator Operations Summary (including Truncation) {#LOG-CUR-001}

- **Implements**: OBS-CUR-001 (includes truncation logging per OBS-CUR-001 scope: "Also log if the operations list was truncated due to CON-CUR-004")
- **Trigger**: `_apply_curator_operations()` completes processing the operations list (regardless of how many were applied or skipped).
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"curator_ops_summary"`
  - `content`: Human-readable text including:
    - Count of ADD operations applied and skipped (integers)
    - Count of UPDATE operations applied and skipped (integers)
    - Count of MERGE operations applied and skipped (integers)
    - Count of DELETE operations applied and skipped (integers)
    - Count of unknown-type operations skipped (integer)
    - If any operations were skipped: list of skip reasons (human-readable strings)
    - If the operations list was truncated (CON-CUR-004): a line noting the original count and truncated count (10), placed at the top of the summary before per-type counts
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_curator_ops_summary.txt`
- **When NOT emitted**: If `is_diagnostic_mode()` returns `False`. Always emitted (even if all counts are zero) when diagnostic mode is active and the operations path was taken.
- **Truncation sub-event**: In addition to the summary, a separate diagnostic file is emitted at the point of truncation (before processing begins) for immediate visibility. This uses `save_diagnostic()` with `name: "curator_ops_truncated"` and content noting the original count and truncated count. This separate file is only emitted when truncation actually occurs (list has more than 10 entries). [Resolves SPEC_CHALLENGE Q10 -- LOG-CUR-004 merged into LOG-CUR-001]

**Example output (no truncation)**:
```
Curator operations summary:
  ADD: 2 applied, 1 skipped
  UPDATE: 1 applied, 0 skipped
  MERGE: 1 applied, 0 skipped
  DELETE: 1 applied, 1 skipped
  Unknown type: 0 skipped
  Skip reasons:
    - ADD: duplicate text "prefer pathlib over os.path for all fi..."
    - DELETE: target_id 'pat-999' not found
```

**Example output with truncation**:
```
Curator operations summary:
  Operations list truncated from 15 to 10
  ADD: 5 applied, 0 skipped
  UPDATE: 0 applied, 0 skipped
  MERGE: 3 applied, 1 skipped
  DELETE: 1 applied, 0 skipped
  Unknown type: 0 skipped
  Skip reasons:
    - MERGE: source_id 'pat-099' not found
    - MERGE: fewer than 2 valid source_ids remain after filtering
```

**Example truncation sub-event file** (`{timestamp}_curator_ops_truncated.txt`):
```
Operations list truncated from 15 to 10
```

### LOG-CUR-002: Non-Existent ID Reference {#LOG-CUR-002}

- **Implements**: OBS-CUR-002
- **Trigger**: During MERGE processing, a `source_id` in the `source_ids` list does not exist in the current playbook state. Or during DELETE or UPDATE processing, the `target_id` does not exist in the current playbook state.
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"curator_nonexistent_id"`
  - `content`: Human-readable text including:
    - The non-existent ID (exact string)
    - The operation type (`"MERGE"`, `"DELETE"`, or `"UPDATE"`)
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_curator_nonexistent_id.txt`
- **When NOT emitted**: If the referenced ID exists in the playbook, or if `is_diagnostic_mode()` returns `False`.

**Example output (MERGE)**:
```
MERGE references non-existent ID: 'pat-099'
```

**Example output (DELETE)**:
```
DELETE references non-existent ID: 'mis-005'
```

**Note**: This event may fire multiple times per operation (e.g., a MERGE with 3 source_ids where 2 are non-existent produces 2 LOG-CUR-002 events). Each is written to a separate diagnostic file with a unique timestamp. UPDATE operations that reference non-existent IDs also trigger this event (same as DELETE/MERGE).

### LOG-CUR-003: DELETE Reason Audit {#LOG-CUR-003}

- **Implements**: OBS-CUR-003
- **Trigger**: A DELETE operation is successfully applied (the entry was found and removed).
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"curator_delete_audit"`
  - `content`: Human-readable text including:
    - `target_id`: the ID of the deleted entry (exact string)
    - `text`: the deleted entry's text (truncated to 80 characters)
    - `reason`: the LLM-provided reason (exact string, may be empty if LLM omitted it)
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_curator_delete_audit.txt`
- **When NOT emitted**: If the DELETE was skipped (non-existent ID or validation failure), or if `is_diagnostic_mode()` returns `False`.

**Example output**:
```
DELETE applied: target_id='mis-002', text="Never use bare except clauses in production code because they catch syste", reason='Contradicts current project conventions'
```

### LOG-CUR-004: UPDATE Operation Audit Log {#LOG-CUR-004}

- **Implements**: OBS-CUR-004
- **Trigger**: When an UPDATE operation is applied successfully (the entry was found and its text was replaced).
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"curator_update_audit"`
  - `content`: Human-readable text including:
    - `target_id`: the ID of the updated entry (exact string)
    - `old_text`: the entry's text before the update (truncated to 80 characters)
    - `new_text`: the entry's new text after the update (truncated to 80 characters)
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_curator_update_audit.txt`
- **When NOT emitted**: If the UPDATE was skipped (non-existent ID, empty target_id, empty text, or validation failure), or if `is_diagnostic_mode()` returns `False`.

**Example output**:
```
UPDATE applied: target_id='pat-001', old_text="use type hints for function parameters", new_text="use type hints for all function parameters and return values"
```

## Carried-Forward Diagnostics

The following diagnostics from prior modules remain active and are unchanged:

| LOG-* | Diagnostic File Name | When Written | Interaction with Curator |
|-------|---------------------|--------------|-------------------------|
| LOG-SCORE-002 | `playbook_pruning` | When pruning removes entries | Pruning runs AFTER curator operations. A merged entry whose summed counters exceed the threshold will be pruned and logged here. |
| LOG-SECT-002 | `sections_unknown_section` | When an ADD operation's `section` field doesn't match canonical names | Fires for ADD operations with unknown section names, same as for `new_key_points` entries. |

## Sensitive Data Handling

- **ALLOW**: Key point `name` (e.g., `pat-001`, `kpt_001`), `helpful` count, `harmful` count, section names, operation types, skip reasons.
- **ALLOW with truncation**: Key point `text` is truncated to 80 characters in LOG-CUR-003 (DELETE audit) and in skip reason messages to limit file size while providing enough context for identification.
- **ALLOW**: DELETE `reason` field (LLM-generated justification). These are brief explanations like "contradicts project conventions" -- not user PII.
- **No sensitive data**: Key point text is developer-authored guidance. LLM-provided reasons are brief justifications. Operation IDs are system-generated identifiers. No redaction is required.

## Input Sources

- `/data/agentic_context_engineering/.planning/intent.md` -- OBS-CUR-001, OBS-CUR-002, OBS-CUR-003 definitions
- `/data/agentic_context_engineering/docs/curator/design.md` -- Instrumentation hooks section, diagnostic pattern details
- `/data/agentic_context_engineering/docs/curator/spec.md` -- REQ-CUR-002 through REQ-CUR-009
- `/data/agentic_context_engineering/docs/scoring/observability.md` -- LOG-SCORE-002 carry-forward
- `/data/agentic_context_engineering/docs/sections/observability.md` -- LOG-SECT-002 carry-forward
- `/data/agentic_context_engineering/src/hooks/common.py` -- `save_diagnostic()` and `is_diagnostic_mode()` implementation
