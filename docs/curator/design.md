# Implementation Design: Curator Operations Module

## Overview

This document specifies the exact changes to `src/hooks/common.py` and `src/prompts/reflection.txt` required to implement curator-style explicit operations (ADD, MERGE, DELETE). Each section maps to REQ-* in `spec.md`.

---

## New Function: `_apply_curator_operations()`

**File**: `src/hooks/common.py` (new private function, placed before `update_playbook_data()`)

**Implements**: REQ-CUR-002, REQ-CUR-003, REQ-CUR-004, REQ-CUR-005, REQ-CUR-009

This is the core processing function that applies a validated, truncated list of operations to a playbook (already deep-copied by the caller).

```python
def _apply_curator_operations(playbook: dict, operations: list[dict]) -> dict:
    """Apply curator operations (ADD, MERGE, DELETE) to the playbook.

    The playbook passed in is a deep copy -- mutations are safe.
    Operations are applied sequentially in list order.
    Invalid operations are skipped (no-op with diagnostic log).

    @implements REQ-CUR-002, REQ-CUR-003, REQ-CUR-004, REQ-CUR-005, REQ-CUR-009
    @invariant INV-CUR-002 (no crash on invalid operations)
    @invariant INV-CUR-004 (section names remain canonical)
    """
    ...
```

### Operation Dispatch

```python
# Truncate to CON-CUR-004 max
MAX_OPS = 10
if len(operations) > MAX_OPS:
    if is_diagnostic_mode():
        save_diagnostic(
            f"Operations list truncated from {len(operations)} to {MAX_OPS}",
            "curator_ops_truncated"
        )
    operations = operations[:MAX_OPS]

# Counters for OBS-CUR-001 summary
counts = {"ADD": 0, "MERGE": 0, "DELETE": 0}
skipped = {"ADD": 0, "MERGE": 0, "DELETE": 0, "unknown": 0}
skip_reasons = []

for op in operations:
    op_type = op.get("type", "")
    if op_type == "ADD":
        ... # see ADD handling below
    elif op_type == "MERGE":
        ... # see MERGE handling below
    elif op_type == "DELETE":
        ... # see DELETE handling below
    else:
        skipped["unknown"] += 1
        skip_reasons.append(f"Unknown operation type: {op_type!r}")

# OBS-CUR-001: Summary diagnostic
if is_diagnostic_mode():
    save_diagnostic(
        f"Curator operations summary:\n"
        f"  ADD: {counts['ADD']} applied, {skipped['ADD']} skipped\n"
        f"  MERGE: {counts['MERGE']} applied, {skipped['MERGE']} skipped\n"
        f"  DELETE: {counts['DELETE']} applied, {skipped['DELETE']} skipped\n"
        f"  Unknown type: {skipped['unknown']} skipped\n"
        + (f"  Skip reasons:\n" + "\n".join(f"    - {r}" for r in skip_reasons) if skip_reasons else ""),
        "curator_ops_summary"
    )

return playbook
```

### ADD Handling

```python
# Within the ADD branch:
text = op.get("text", "")
if not text or not isinstance(text, str) or not text.strip():
    skipped["ADD"] += 1
    skip_reasons.append(f"ADD: empty or missing text")
    continue

raw_section = op.get("section", "") or ""
section_name = _resolve_section(raw_section)

# Dedup against all existing texts
existing_texts = set()
for entries in playbook["sections"].values():
    for kp in entries:
        existing_texts.add(kp["text"])

if text in existing_texts:
    skipped["ADD"] += 1
    skip_reasons.append(f"ADD: duplicate text \"{text[:40]}...\"")
    continue

slug = SECTION_SLUGS[section_name]
target_entries = playbook["sections"][section_name]
name = generate_keypoint_name(target_entries, slug)
target_entries.append({"name": name, "text": text, "helpful": 0, "harmful": 0})
counts["ADD"] += 1
```

### MERGE Handling

```python
# Within the MERGE branch:
source_ids = op.get("source_ids", [])
merged_text = op.get("merged_text", "")

# Validation (QG-CUR-001)
if not isinstance(source_ids, list) or len(source_ids) < 2:
    skipped["MERGE"] += 1
    skip_reasons.append(f"MERGE: source_ids has fewer than 2 entries")
    continue
if not merged_text or not isinstance(merged_text, str) or not merged_text.strip():
    skipped["MERGE"] += 1
    skip_reasons.append(f"MERGE: empty or missing merged_text")
    continue

# Build ID-to-entry and ID-to-section lookup from current state
id_to_entry = {}
id_to_section = {}
for sec_name, entries in playbook["sections"].items():
    for kp in entries:
        id_to_entry[kp["name"]] = kp
        id_to_section[kp["name"]] = sec_name

# Filter valid source_ids
valid_ids = []
for sid in source_ids:
    if sid in id_to_entry:
        valid_ids.append(sid)
    else:
        # OBS-CUR-002: non-existent ID
        if is_diagnostic_mode():
            save_diagnostic(
                f"MERGE references non-existent ID: {sid!r}",
                "curator_nonexistent_id"
            )
        skip_reasons.append(f"MERGE: source_id {sid!r} not found")

if len(valid_ids) < 2:
    skipped["MERGE"] += 1
    skip_reasons.append(f"MERGE: fewer than 2 valid source_ids remain after filtering")
    continue

# Resolve target section
raw_section = op.get("section", "") or ""
if raw_section and raw_section.strip():
    target_section = _resolve_section(raw_section)
else:
    target_section = id_to_section[valid_ids[0]]  # section of first valid source

# Sum counters from valid sources
total_helpful = sum(id_to_entry[sid]["helpful"] for sid in valid_ids)
total_harmful = sum(id_to_entry[sid]["harmful"] for sid in valid_ids)

# Create new entry in target section
slug = SECTION_SLUGS[target_section]
target_entries = playbook["sections"][target_section]
name = generate_keypoint_name(target_entries, slug)
target_entries.append({
    "name": name,
    "text": merged_text,
    "helpful": total_helpful,
    "harmful": total_harmful,
})

# Remove all valid source entries from their sections
for sid in valid_ids:
    sec = id_to_section[sid]
    playbook["sections"][sec] = [
        kp for kp in playbook["sections"][sec] if kp["name"] != sid
    ]

counts["MERGE"] += 1
```

### DELETE Handling

```python
# Within the DELETE branch:
target_id = op.get("target_id", "")
reason = op.get("reason", "")

if not target_id or not isinstance(target_id, str) or not target_id.strip():
    skipped["DELETE"] += 1
    skip_reasons.append(f"DELETE: empty or missing target_id")
    continue

# Find the entry
found_section = None
found_entry = None
for sec_name, entries in playbook["sections"].items():
    for kp in entries:
        if kp["name"] == target_id:
            found_section = sec_name
            found_entry = kp
            break
    if found_section:
        break

if not found_section:
    skipped["DELETE"] += 1
    # OBS-CUR-002: non-existent ID
    if is_diagnostic_mode():
        save_diagnostic(
            f"DELETE references non-existent ID: {target_id!r}",
            "curator_nonexistent_id"
        )
    skip_reasons.append(f"DELETE: target_id {target_id!r} not found")
    continue

# OBS-CUR-003: DELETE reason audit
if is_diagnostic_mode():
    save_diagnostic(
        f"DELETE applied: target_id={target_id!r}, "
        f"text=\"{found_entry['text'][:80]}\", "
        f"reason={reason!r}",
        "curator_delete_audit"
    )

# Remove entry
playbook["sections"][found_section] = [
    kp for kp in playbook["sections"][found_section] if kp["name"] != target_id
]
counts["DELETE"] += 1
```

---

## Modified Function: `update_playbook_data()`

**File**: `src/hooks/common.py`

**Implements**: REQ-CUR-006, REQ-CUR-008

**Current signature** (UNCHANGED): `update_playbook_data(playbook: dict, extraction_result: dict) -> dict`

### Precedence Logic (new code, inserted at the top of the function)

```python
import copy

def update_playbook_data(playbook: dict, extraction_result: dict) -> dict:
    """Apply operations or new_key_points, evaluations, and pruning.

    @implements REQ-CUR-006, REQ-CUR-008, REQ-SECT-005, REQ-SECT-008
    @invariant INV-CUR-001 (deep copy isolation)
    @invariant INV-CUR-006 (precedence prevents double-processing)
    """

    # REQ-CUR-008: Precedence rule
    if "operations" in extraction_result:
        # Operations path: deep copy + apply operations
        operations = extraction_result.get("operations", [])
        if isinstance(operations, list) and operations:
            try:
                playbook_copy = copy.deepcopy(playbook)
                playbook = _apply_curator_operations(playbook_copy, operations)
            except Exception:
                # INV-CUR-001: rollback to original on uncaught exception
                if is_diagnostic_mode():
                    import traceback
                    save_diagnostic(
                        f"Operations rollback due to exception:\n{traceback.format_exc()}",
                        "curator_ops_rollback"
                    )
                # playbook remains the original (unmodified)
        # Skip new_key_points entirely (even if present)
    else:
        # Backward compat: use new_key_points as before (CON-CUR-001)
        new_key_points = extraction_result.get("new_key_points", [])
        # ... existing new_key_points insertion logic (unchanged) ...
        # [existing code for iterating new_key_points, resolving sections,
        #  dedup, generating names, appending entries]

    # Evaluations (runs regardless of which path was taken)
    evaluations = extraction_result.get("evaluations", [])
    # ... existing evaluations logic (unchanged) ...

    # Pruning (runs regardless of which path was taken)
    # ... existing pruning logic (unchanged) ...

    return playbook
```

**Key design decisions**:
1. The `if "operations" in extraction_result` check uses key presence (not truthiness) -- even an empty `operations: []` triggers the operations path and suppresses `new_key_points`
2. The deep copy + try/except wraps ONLY the operations processing, not evaluations/pruning (those continue to operate on the playbook in-place as before). **Atomicity scope**: If evaluations or pruning raise an exception, the caller sees an unhandled exception (not a silent rollback). This is acceptable because evaluations/pruning failures are programming errors, not expected runtime conditions. [Resolves SPEC_CHALLENGE Q8]
3. When `operations` is present but empty (`[]`), no operations are applied and no deep copy is created (optimization: empty list is a no-op). This is consistent with REQ-CUR-006 which clarifies that deep copy is only created when the validated operations list is non-empty (`isinstance(operations, list) and operations`). [Resolves SPEC_CHALLENGE Q2]
4. Evaluations and pruning always run after the operations/new_key_points path, regardless of which branch was taken

---

## Modified Function: `extract_keypoints()`

**File**: `src/hooks/common.py`

**Implements**: REQ-CUR-001

**Current return** (line 574-577):
```python
return {
    "new_key_points": result.get("new_key_points", []),
    "evaluations": result.get("evaluations", []),
}
```

**New return**:
```python
extraction = {
    "new_key_points": result.get("new_key_points", []),
    "evaluations": result.get("evaluations", []),
}
# SC-CUR-001: Include operations if present in LLM response AND is a list
# SCN-CUR-001-04: Non-list values (null, string, int) treated as absent
if "operations" in result and isinstance(result["operations"], list):
    extraction["operations"] = result["operations"]
return extraction
```

**Key decision**: The `operations` key is only added to the extraction result if the LLM response contains it AND the value is a `list`. This preserves backward compat: old-format LLM responses that lack `operations` produce extraction results without the key, triggering the `new_key_points` fallback in `update_playbook_data()` (REQ-CUR-008). Non-list `operations` values (e.g., `null`, a string, an integer) are treated as if the key were absent, preventing a crash in `_apply_curator_operations()`. [Resolves SPEC_CHALLENGE Q1]

---

## Modified Template: `reflection.txt`

**File**: `src/prompts/reflection.txt` (or `~/.claude/prompts/reflection.txt`)

**Implements**: REQ-CUR-007, QG-CUR-002

The template must be updated to instruct the LLM to return combined `evaluations` + `operations`. The exact content depends on the existing template, but the additions are:

### New Sections to Add to reflection.txt

```
# Curator Operations
After evaluating existing key points, you may also propose structural operations on the playbook.
Available operations:

1. ADD -- Add a new key point (same as what you would put in new_key_points)
2. MERGE -- Combine two or more overlapping/redundant key points into one
3. DELETE -- Remove a key point that is wrong, outdated, or harmful

Rules:
- You may return zero operations if no changes are needed
- Maximum 10 operations per response
- For MERGE and DELETE, use the key point IDs (names) shown in the playbook above
- MERGE requires at least 2 source_ids
- DELETE requires a reason explaining why the entry should be removed

# Output Format
{{
  "evaluations": [
    {{"name": "pat-001", "rating": "helpful"}},
    {{"name": "kpt_001", "rating": "neutral"}}
  ],
  "operations": [
    {{"type": "ADD", "text": "New insight from this session", "section": "PATTERNS & APPROACHES"}},
    {{"type": "MERGE", "source_ids": ["pat-001", "pat-003"], "merged_text": "Combined type annotation guidance", "section": "PATTERNS & APPROACHES"}},
    {{"type": "DELETE", "target_id": "mis-002", "reason": "Contradicts current project conventions"}}
  ]
}}

Note: The "operations" list replaces "new_key_points". Do NOT include a "new_key_points" field.
If you have no operations to propose, return "operations": [].
```

**Changes from current template**:
1. New `# Curator Operations` section explaining the three operation types
2. Updated output format showing `operations` instead of `new_key_points`
3. Examples of each operation type (QG-CUR-002)
4. Explicit instruction that `operations` replaces `new_key_points`
5. Explicit max-10-operations instruction (CON-CUR-004)
6. Explicit zero-operations allowance

---

## Function Composition

### Call Graph (updated)

```
PostToolUseHook / StopHook
    --> load_playbook()               # reads playbook.json (unchanged)
    --> load_transcript()             # reads session transcript (unchanged)
    --> extract_keypoints()           # calls LLM; now also extracts 'operations' from response
        --> load_template()           # reads reflection.txt (updated prompt)
    --> update_playbook_data()        # applies operations OR new_key_points, then evaluations + pruning
        |
        +--> [if "operations" in extraction_result]:
        |       --> copy.deepcopy(playbook)
        |       --> _apply_curator_operations(playbook_copy, operations)
        |           --> _resolve_section()          # normalize section names
        |           --> generate_keypoint_name()    # per-section ID generation
        |           --> is_diagnostic_mode()        # gate diagnostic output
        |           --> save_diagnostic()           # OBS-CUR-001/002/003 logging
        |
        +--> [else -- no "operations" key]:
        |       --> _resolve_section()              # existing new_key_points path
        |       --> generate_keypoint_name()
        |
        +--> [always -- evaluations]:
        |       --> (cross-section name lookup, counter increment)
        |
        +--> [always -- pruning]:
                --> (harmful >= 3 AND harmful > helpful)
    --> save_playbook()               # writes playbook.json (unchanged)
```

### Data Flow

```
LLM response (JSON)
    |
    v
extract_keypoints()
    |  parses: evaluations, operations (if present), new_key_points (fallback)
    v
extraction_result dict
    {
      "evaluations": [...],
      "operations": [...],          # present only if LLM returned it
      "new_key_points": [...]       # present for backward compat
    }
    |
    v
update_playbook_data(playbook, extraction_result)
    |
    +--> Precedence check: "operations" in extraction_result?
    |
    +--> [YES: operations path]
    |       |
    |       v
    |     copy.deepcopy(playbook) --> playbook_copy
    |       |
    |       v
    |     _apply_curator_operations(playbook_copy, operations)
    |       |
    |       +--> Truncate to 10 (CON-CUR-004)
    |       +--> For each op in list order (REQ-CUR-005):
    |       |       +--> Validate fields (REQ-CUR-009)
    |       |       +--> ADD:    resolve section, dedup, generate ID, append
    |       |       +--> MERGE:  filter source_ids, sum counters, create merged, remove sources
    |       |       +--> DELETE: find entry, remove, log reason
    |       |       +--> Skip invalid (no-op + diagnostic)
    |       |
    |       +--> Return modified playbook_copy
    |       |
    |       +--> [on exception: return original playbook -- rollback]
    |
    +--> [NO: new_key_points path -- existing behavior]
    |       |
    |       v
    |     Iterate new_key_points, resolve sections, dedup, generate IDs, append
    |
    +--> [ALWAYS: evaluations]
    |       |
    |       v
    |     Build cross-section name lookup
    |     Increment helpful/harmful counters per evaluation
    |
    +--> [ALWAYS: pruning]
    |       |
    |       v
    |     Remove entries where harmful >= 3 AND harmful > helpful
    |
    v
Modified playbook --> save_playbook()
```

### Initialization Order

No change. The existing initialization order is:
1. `load_playbook()` -- must be called first to get playbook state
2. `extract_keypoints()` -- calls LLM, returns extraction result
3. `update_playbook_data()` -- applies changes to playbook
4. `save_playbook()` -- writes to disk

---

## Where Each Operation Type Is Handled

| Operation | Function | Location in Flow | Key Dependencies |
|-----------|----------|-----------------|------------------|
| ADD | `_apply_curator_operations()` | Within the `op_type == "ADD"` branch | `_resolve_section()`, `generate_keypoint_name()`, dedup check |
| MERGE | `_apply_curator_operations()` | Within the `op_type == "MERGE"` branch | `_resolve_section()`, `generate_keypoint_name()`, ID lookup, counter summing |
| DELETE | `_apply_curator_operations()` | Within the `op_type == "DELETE"` branch | ID lookup, section entry removal |
| Validation | `_apply_curator_operations()` | At the start of each branch | Field existence and type checks |
| Truncation | `_apply_curator_operations()` | Before the loop begins | `MAX_OPS = 10` constant |
| Precedence | `update_playbook_data()` | At the top, before any processing | `"operations" in extraction_result` check |
| Deep copy | `update_playbook_data()` | Before calling `_apply_curator_operations()` | `copy.deepcopy()` |
| Rollback | `update_playbook_data()` | try/except around `_apply_curator_operations()` | Returns original on exception |

---

## Testability Hooks

### External Dependencies

| Dependency | Testability Hook | Implementation |
|------------|------------------|----------------|
| File system (playbook.json) | `get_project_dir()` returns a path | Tests set `CLAUDE_PROJECT_DIR` env var to a temp directory |
| Diagnostic mode | `is_diagnostic_mode()` checks for flag file | Tests create/remove the flag file in the temp directory |
| LLM API (extract_keypoints) | Not under test for curator logic | Curator tests call `update_playbook_data()` directly with pre-constructed extraction results |
| `SECTION_SLUGS` constant | Importable from `common.py` | Tests reference directly for canonical names/slugs |

### How Tests Inject Mock LLM Responses

Curator operation tests do NOT need to mock the LLM. The testable boundary is `update_playbook_data(playbook, extraction_result)`:

1. Construct a sections-based `playbook` dict directly (no file I/O)
2. Construct an `extraction_result` dict with the desired `operations` list
3. Call `update_playbook_data(playbook, extraction_result)`
4. Assert the returned playbook matches expected state

**Example test structure**:
```python
def test_add_operation():
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
    extraction = {
        "operations": [
            {"type": "ADD", "text": "new insight", "section": "PATTERNS & APPROACHES"}
        ],
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    pat = result["sections"]["PATTERNS & APPROACHES"]
    assert len(pat) == 1
    assert pat[0]["text"] == "new insight"
    assert pat[0]["name"] == "pat-001"
    assert pat[0]["helpful"] == 0
    assert pat[0]["harmful"] == 0
```

### Test Strategy for Deep Copy Atomicity

```python
def test_rollback_on_exception(monkeypatch):
    playbook = _make_playbook_with_entries()
    original_sections = copy.deepcopy(playbook["sections"])

    # Inject a faulty operation that will cause an exception
    # (e.g., monkeypatch _apply_curator_operations to raise)
    extraction = {
        "operations": [{"type": "ADD", "text": "will fail"}],
        "evaluations": [],
    }
    # ... setup to cause exception inside _apply_curator_operations ...

    result = update_playbook_data(playbook, extraction)
    # Original should be returned unchanged
    assert result["sections"] == original_sections
```

### Test Strategy for Precedence

```python
def test_operations_suppress_new_key_points():
    playbook = _make_empty_playbook()
    extraction = {
        "operations": [{"type": "ADD", "text": "from ops", "section": "OTHERS"}],
        "new_key_points": ["from nkp"],  # should be ignored
        "evaluations": [],
    }
    result = update_playbook_data(playbook, extraction)
    all_texts = _collect_all_texts(result)
    assert "from ops" in all_texts
    assert "from nkp" not in all_texts
```

---

## Instrumentation Hooks

### Diagnostic Pattern (OBS-CUR-001, OBS-CUR-002, OBS-CUR-003)

This module continues to use the existing diagnostic pattern (`is_diagnostic_mode()` + `save_diagnostic()`) consistent with the scoring and sections modules.

| OBS-* | Diagnostic File Name | When Written | Content |
|-------|---------------------|--------------|---------|
| OBS-CUR-001 (LOG-CUR-001) | `curator_ops_summary` | After `_apply_curator_operations()` completes | Counts of applied/skipped per type, skip reasons, truncation note |
| OBS-CUR-001 (LOG-CUR-001 truncation sub-event) | `curator_ops_truncated` | When operations list exceeds 10 and is truncated (before processing begins) | Original count and truncated count |
| OBS-CUR-002 (LOG-CUR-002) | `curator_nonexistent_id` | When MERGE `source_ids` or DELETE `target_id` references a non-existent ID | The non-existent ID and operation type |
| OBS-CUR-003 (LOG-CUR-003) | `curator_delete_audit` | When a DELETE operation is successfully applied | `target_id`, deleted entry text (truncated to 80 chars), `reason` |
| (rollback) | `curator_ops_rollback` | When an uncaught exception causes rollback | Exception traceback |

### Wiring

All diagnostic outputs are gated by `is_diagnostic_mode()` and written via `save_diagnostic()`. No new instrumentation infrastructure is needed.
