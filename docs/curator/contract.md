# Data Contract: Curator Operations Module

## Overview

This document defines the data contracts introduced by the curator operations feature. All types are implicit (Python dicts with documented key/value schemas), consistent with the existing codebase. No formal class definitions are introduced.

---

## Schema Definitions

### Operation (base schema)

Every operation is a `dict` with at minimum a `type` field.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `type` | `str` | One of `"ADD"`, `"MERGE"`, `"DELETE"`. Case-sensitive. | The operation type. |

Unknown `type` values are skipped during processing (REQ-CUR-009).

---

### ADD Operation

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `type` | `str` | `"ADD"` (literal) | Operation type identifier. |
| `text` | `str` | Non-empty after strip. Required. | The key point text to add. |
| `section` | `str` | Optional. Should be one of the canonical section names. Resolved case-insensitively via `_resolve_section()`. Falls back to `"OTHERS"` if missing, `None`, empty, or unrecognized. | Target section for the new entry. |

**JSON example**:
```json
{"type": "ADD", "text": "Use structured logging for debugging", "section": "PATTERNS & APPROACHES"}
```

**Validation (QG-CUR-001)**: If `text` is missing, empty, or not a string, the ADD is skipped.

---

### MERGE Operation

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `type` | `str` | `"MERGE"` (literal) | Operation type identifier. |
| `source_ids` | `list[str]` | Required. Must have `len >= 2` at schema level. After filtering non-existent IDs, must still have `>= 2` valid entries. | IDs of existing key points to merge. |
| `merged_text` | `str` | Non-empty after strip. Required. | The combined text for the merged entry. |
| `section` | `str` | Optional. If provided and valid, the merged entry goes there. If absent/empty/invalid, defaults to the section of the first valid `source_id`. | Target section for the merged entry. |

**JSON example**:
```json
{
  "type": "MERGE",
  "source_ids": ["pat-001", "pat-003"],
  "merged_text": "Use complete type annotations including return types and parameter types",
  "section": "PATTERNS & APPROACHES"
}
```

**Validation (QG-CUR-001)**:
- If `source_ids` is missing, not a list, or has fewer than 2 entries: skip.
- If `merged_text` is missing, empty, or not a string: skip.
- After filtering non-existent IDs: if fewer than 2 valid IDs remain: skip.

**Counter aggregation**: The merged entry's `helpful` = sum of `helpful` from all valid source entries. Same for `harmful`. See INV-CUR-003.

---

### DELETE Operation

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `type` | `str` | `"DELETE"` (literal) | Operation type identifier. |
| `target_id` | `str` | Non-empty. Required. Must reference an existing entry ID. | ID of the key point to remove. |
| `reason` | `str` | Optional. Logged via OBS-CUR-003 but NOT stored in the playbook. | Explanation for why the entry is being deleted. |

**JSON example**:
```json
{"type": "DELETE", "target_id": "mis-002", "reason": "Contradicts current project conventions"}
```

**Validation (QG-CUR-001)**: If `target_id` is missing, empty, or not a string: skip. If `target_id` does not reference an existing entry: skip (OBS-CUR-002 logged).

---

### ExtractionResult (updated)

The output of `extract_keypoints()`. The `operations` field is new; `new_key_points` and `evaluations` are unchanged.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `new_key_points` | `list[str \| dict]` | May be empty. Ignored when `operations` is present. | New key points (legacy format). |
| `evaluations` | `list[dict]` | May be empty. Each entry has `name` (str) and `rating` (str). | Ratings of existing key points. |
| `operations` | `list[dict]` | Optional key. May be empty list. Each entry is an ADD, MERGE, or DELETE operation dict. | Curator operations (new format). |

**Precedence rule (REQ-CUR-008)**:
- If `"operations"` key is present in the dict (even if the list is empty): use operations path, ignore `new_key_points`.
- If `"operations"` key is absent: use `new_key_points` path (backward compat).

**JSON example (new format with operations)**:
```json
{
  "evaluations": [
    {"name": "pat-001", "rating": "helpful"},
    {"name": "kpt_001", "rating": "neutral"}
  ],
  "operations": [
    {"type": "ADD", "text": "Use structured logging", "section": "PATTERNS & APPROACHES"},
    {"type": "MERGE", "source_ids": ["pat-002", "pat-005"], "merged_text": "Combined guidance on error handling"},
    {"type": "DELETE", "target_id": "mis-003", "reason": "No longer relevant after refactor"}
  ]
}
```

**JSON example (old format, backward compat)**:
```json
{
  "evaluations": [
    {"name": "pat-001", "rating": "helpful"}
  ],
  "new_key_points": [
    {"text": "Some new insight", "section": "OTHERS"}
  ]
}
```

**JSON example (operations present but empty)**:
```json
{
  "evaluations": [
    {"name": "pat-001", "rating": "helpful"}
  ],
  "operations": []
}
```
In this case, `new_key_points` is ignored (operations key is present). No structural changes are made. Evaluations and pruning still run.

---

### PlaybookEntry (unchanged)

The canonical schema for a single key point. Unchanged by this task.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `name` | `str` | Non-empty. Format: `{slug}-NNN` for new entries or `kpt_NNN` for legacy. Unique across all sections. | Stable identifier. |
| `text` | `str` | Non-empty. | Key point content. |
| `helpful` | `int` | `>= 0` | Count of times rated "helpful". |
| `harmful` | `int` | `>= 0` | Count of times rated "harmful". |

Merged entries follow this same schema. Their `helpful` and `harmful` values are the sums of the source entries' counters.

---

## Function Signatures

### `update_playbook_data(playbook: dict, extraction_result: dict) -> dict`

**Signature**: UNCHANGED. Callers (`session_end.py`, `precompact.py`) do not need modification (CON-CUR-002).

| Parameter | Type | Description |
|-----------|------|-------------|
| `playbook` | `dict` | Sections-based playbook dict. |
| `extraction_result` | `dict` | The extraction result containing `evaluations`, and either `operations` (new) or `new_key_points` (legacy). |
| **Returns** | `dict` | The modified playbook dict. |

**Behavior**:
1. **Precedence check**: If `"operations" in extraction_result`, enter operations path; else enter `new_key_points` path.
2. **Operations path** (REQ-CUR-006, REQ-CUR-008):
   - `copy.deepcopy(playbook)` -> `playbook_copy`
   - `_apply_curator_operations(playbook_copy, operations)` -> modified copy
   - On exception: return original `playbook` (rollback)
   - `new_key_points` is NOT consulted
3. **new_key_points path** (CON-CUR-001): Existing behavior, unchanged.
4. **Evaluations**: Always applied (cross-section name lookup, counter increment).
5. **Pruning**: Always applied (`harmful >= 3 AND harmful > helpful`).

---

### `_apply_curator_operations(playbook: dict, operations: list[dict]) -> dict`

**New private function**. Not part of the public API.

| Parameter | Type | Description |
|-----------|------|-------------|
| `playbook` | `dict` | A deep copy of the playbook. Mutations are safe. |
| `operations` | `list[dict]` | The operations list from the extraction result. |
| **Returns** | `dict` | The modified playbook. |

**Behavior**:
1. Truncate `operations` to first 10 entries (CON-CUR-004).
2. For each operation in list order:
   - Validate required fields per operation type (REQ-CUR-009).
   - Apply if valid; skip with diagnostic if invalid.
3. Emit OBS-CUR-001 summary diagnostic.
4. Return modified playbook.

**Error contract**: This function does NOT raise exceptions for invalid operations. All validation failures are handled internally as skips. Only unexpected runtime errors (bugs) propagate as exceptions, to be caught by the caller's try/except for rollback.

---

### `extract_keypoints(messages, playbook, diagnostic_name) -> dict`

**Signature**: UNCHANGED.

**Return shape change**: The returned dict now conditionally includes an `operations` key:

```python
# If LLM response contains "operations":
{
    "new_key_points": [...],    # still present for backward compat
    "evaluations": [...],
    "operations": [...]          # NEW -- only present if LLM returned it
}

# If LLM response does NOT contain "operations" (old-format response):
{
    "new_key_points": [...],
    "evaluations": [...]
    # no "operations" key
}
```

**Key contract**: The `operations` key is present in the returned dict if and only if the LLM response JSON contained an `operations` key. This is the signal that `update_playbook_data()` uses for precedence (REQ-CUR-008).

---

## Error Contracts

### Exceptions Raised

| Function | Exception | When | Caller Action |
|----------|-----------|------|---------------|
| `update_playbook_data()` | None (by design) | N/A | N/A |
| `_apply_curator_operations()` | None for invalid operations | Invalid fields, non-existent IDs, unknown types | Skipped internally |
| `_apply_curator_operations()` | Unexpected `Exception` (bug) | Runtime error in operation logic | Caught by `update_playbook_data()` for rollback |

### Exceptions Swallowed

| Function | Exception | When | Action Taken |
|----------|-----------|------|-------------|
| `update_playbook_data()` | Any `Exception` from `_apply_curator_operations()` | Uncaught error during operations processing | Returns original (unmodified) playbook; logs rollback diagnostic (OBS) |

### Validation Failures (Not Exceptions)

| Situation | Result | Diagnostic |
|-----------|--------|-----------|
| ADD with empty `text` | Skipped | Included in OBS-CUR-001 summary |
| MERGE with `source_ids` < 2 entries | Skipped | Included in OBS-CUR-001 summary |
| MERGE with empty `merged_text` | Skipped | Included in OBS-CUR-001 summary |
| MERGE with < 2 valid source IDs after filtering | Skipped | OBS-CUR-002 per non-existent ID + OBS-CUR-001 summary |
| DELETE with empty `target_id` | Skipped | Included in OBS-CUR-001 summary |
| DELETE with non-existent `target_id` | Skipped | OBS-CUR-002 + OBS-CUR-001 summary |
| Unknown operation `type` | Skipped | Included in OBS-CUR-001 summary |
| Operations list > 10 entries | Truncated to 10 | OBS-CUR-001 truncation note |
