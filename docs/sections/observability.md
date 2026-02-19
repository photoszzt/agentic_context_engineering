# Observability Specification: Sections Module

## Overview

The sections module extends the playbook lifecycle with section-based organization. Observability is needed to verify migration correctness (flat-to-sections) and detect systematic LLM categorization failures (unknown section names falling back to OTHERS). The module continues to use the file-based diagnostic pattern established by the scoring module.

## Instrumentation Approach

This module uses **file-based diagnostics**, not structured metrics or a logging framework. The existing `save_diagnostic()` function (in `src/hooks/common.py`) writes timestamped plain-text files to `.claude/diagnostic/`. All diagnostic output is gated by `is_diagnostic_mode()`, which checks for the presence of a `.claude/diagnostic_mode` flag file in the project directory.

| Component | Mechanism | Gate | Output Location |
|-----------|-----------|------|-----------------|
| `save_diagnostic(content, name)` | Writes `{timestamp}_{name}.txt` | `is_diagnostic_mode()` returns `True` | `{project_dir}/.claude/diagnostic/` |
| `is_diagnostic_mode()` | Checks existence of flag file | N/A (is the gate) | `{project_dir}/.claude/diagnostic_mode` |

## Observability Traceability

| OBS-* | Observability Requirement | LOG-* | Function | File |
|-------|---------------------------|-------|----------|------|
| OBS-SECT-001 | When migration from flat format to sections occurs, log count of migrated entries | LOG-SECT-001 | `load_playbook()` | `src/hooks/common.py` |
| OBS-SECT-002 | When a new key point falls back to OTHERS due to unrecognized section name, log the original section name | LOG-SECT-002 | `update_playbook_data()` | `src/hooks/common.py` |

## Log Events

### LOG-SECT-001: Sections Migration Diagnostic {#LOG-SECT-001}

- **Implements**: OBS-SECT-001
- **Trigger**: `load_playbook()` detects a flat-format `playbook.json` (has `key_points` key but no `sections` key) and migrates entries to the sections structure.
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"sections_migration"`
  - `content`: Human-readable text including:
    - Count of entries migrated to the OTHERS section (integer)
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_sections_migration.txt`
- **When NOT emitted**: If the file already has a `sections` key (no migration needed), if the file does not exist (default empty playbook returned), or if `is_diagnostic_mode()` returns `False`.

**Example output**:
```
Migrated 5 entries from flat key_points to OTHERS section
```

### LOG-SECT-002: Unknown Section Fallback Diagnostic {#LOG-SECT-002}

- **Implements**: OBS-SECT-002
- **Trigger**: `update_playbook_data()` processes a new key point entry from the LLM where the `section` field does not match any canonical section name (case-insensitive exact match fails) and the entry is assigned to OTHERS as a fallback. This diagnostic is NOT emitted when `section` is missing, None, or empty string (those are expected fallback cases), only when a non-empty section name was provided but did not match.
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"sections_unknown_section"`
  - `content`: Human-readable text including:
    - The original section name provided by the LLM (exact string)
    - The key point text (truncated to 80 characters)
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_sections_unknown_section.txt`
- **When NOT emitted**: If the section name matches a canonical name, if the section field is missing/None/empty (expected fallback), or if `is_diagnostic_mode()` returns `False`.

**Example output**:
```
Unknown section 'CODING TIPS' for key point: "Use list comprehensions instead of manual loops for simple transformations". Assigned to OTHERS.
```

### LOG-SECT-003: Dual-Key Warning Diagnostic {#LOG-SECT-003}

- **Implements**: (defensive, not in OBS-* -- detects file corruption)
- **Trigger**: `load_playbook()` detects a `playbook.json` file containing both a `sections` key and a `key_points` key simultaneously (corrupted or dual-format file).
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"sections_dual_key_warning"`
  - `content`: Human-readable warning message
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_sections_dual_key_warning.txt`
- **When NOT emitted**: If the file has only `sections` or only `key_points` (normal cases), or if `is_diagnostic_mode()` returns `False`.

**Example output**:
```
Dual-key playbook.json detected: both 'sections' and 'key_points' present. Using 'sections', ignoring 'key_points'.
```

## Carried-Forward Diagnostics (from Scoring Module)

The following diagnostics from the scoring module remain active and are unchanged:

| LOG-* | Diagnostic File Name | When Written | Relevant to Sections? |
|-------|---------------------|--------------|----------------------|
| LOG-SCORE-001 | `playbook_migration` | When scoring-level migration (bare string, dict with score) occurs during flat-format loading | Yes -- scoring migration runs as part of flat-to-sections migration |
| LOG-SCORE-002 | `playbook_pruning` | When pruning removes entries | Yes -- pruning now traverses all sections |

**Note**: When a flat-format playbook is loaded, BOTH LOG-SCORE-001 (if scoring-level migration happens) AND LOG-SECT-001 (sections migration) may be emitted in the same load. This is expected: scoring migration is applied to individual entries, then all entries are placed into sections.

## Sensitive Data Handling

- **ALLOW**: Key point `name` (e.g., `pat-001`, `kpt_001`), `helpful` count, `harmful` count, section names, LLM-provided section names.
- **ALLOW with truncation**: Key point `text` is truncated to 80 characters in LOG-SECT-002 to limit file size while providing enough context for identification.
- **No sensitive data**: Key point text is developer-authored guidance (e.g., "use type hints"), not user PII. LLM-provided section names are category labels. No redaction is required.

## Input Sources

- `/data/agentic_context_engineering/.planning/intent.md` -- OBS-SECT-001, OBS-SECT-002 definitions
- `/data/agentic_context_engineering/docs/sections/design.md` -- Instrumentation hooks section, diagnostic pattern details
- `/data/agentic_context_engineering/docs/sections/spec.md` -- REQ-SECT-006, REQ-SECT-007 (migration and dual-key requirements)
- `/data/agentic_context_engineering/docs/scoring/observability.md` -- LOG-SCORE-001, LOG-SCORE-002 carry-forward
- `/data/agentic_context_engineering/src/hooks/common.py` -- `save_diagnostic()` and `is_diagnostic_mode()` implementation (lines 27-41)
