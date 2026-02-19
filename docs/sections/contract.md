# Data Contract: Sections Module

## Overview

This document defines the public data contracts for the section-based playbook organization system. All types are implicit (Python dicts with documented key/value schemas). No formal class definitions are introduced -- the codebase uses plain dicts.

---

## Schema Definitions

### SECTION_SLUGS Constant

**Location**: `src/hooks/common.py` (module-level constant)

**Type**: `dict[str, str]`

**Value**:
```python
SECTION_SLUGS = {
    "PATTERNS & APPROACHES": "pat",
    "MISTAKES TO AVOID": "mis",
    "USER PREFERENCES": "pref",
    "PROJECT CONTEXT": "ctx",
    "OTHERS": "oth",
}
```

**Semantics**:
- Keys: Canonical section names (used in `playbook.json`, in formatted output, and in the LLM prompt)
- Values: Short slug prefixes (used in key point ID generation)
- Iteration order: Defines canonical section ordering for `format_playbook()` output
- This dict is the single source of truth for all section-related operations (REQ-SECT-010)

---

### PlaybookEntry (unchanged from scoring)

The canonical schema for a single key point. Unchanged by this task.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `name` | `str` | Non-empty. Format: `{slug}-NNN` for new entries (e.g., `pat-001`, `mis-002`) or `kpt_NNN` for legacy entries. Unique within the entire playbook (across all sections). | Stable identifier for the key point. |
| `text` | `str` | Non-empty. | The key point content (guidance text). |
| `helpful` | `int` | `>= 0` (INV-SCORE-001, INV-SECT-003) | Count of times rated "helpful". |
| `harmful` | `int` | `>= 0` (INV-SCORE-002, INV-SECT-003) | Count of times rated "harmful". |

**Absent fields**: The `score` field does NOT exist in canonical entries (INV-SCORE-004).

**ID format notes**:
- New entries generated after sections migration use `{slug}-NNN` format (e.g., `pat-001`, `mis-002`, `oth-003`)
- Legacy entries migrated from flat format retain their `kpt_NNN` IDs in the OTHERS section
- Both formats coexist in the OTHERS section; the ID generator only scans for `{slug}-NNN` (INV-SECT-005)

**JSON example** (on disk):
```json
{
  "name": "pat-001",
  "text": "Always use type hints for function signatures",
  "helpful": 5,
  "harmful": 1
}
```

---

### Playbook (sections-based)

The top-level playbook structure stored in `playbook.json`.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `version` | `str` | Currently `"1.0"`. Not bumped by this migration (A5). | Schema version identifier. |
| `last_updated` | `str \| None` | ISO 8601 format when set. `None` for newly created playbooks. | Timestamp of last `save_playbook()` call. |
| `sections` | `dict[str, list[PlaybookEntry]]` | All 5 canonical section names present as keys. Each value is a list (may be empty). | Key points organized by section. |

**Absent fields**: The `key_points` key does NOT exist in the sections-based format (INV-SECT-007).

**JSON example** (on disk):
```json
{
  "version": "1.0",
  "last_updated": "2026-02-18T14:30:00.000000",
  "sections": {
    "PATTERNS & APPROACHES": [
      {"name": "pat-001", "text": "Always use type hints", "helpful": 5, "harmful": 1}
    ],
    "MISTAKES TO AVOID": [],
    "USER PREFERENCES": [
      {"name": "pref-001", "text": "Prefer pathlib over os.path", "helpful": 2, "harmful": 0}
    ],
    "PROJECT CONTEXT": [],
    "OTHERS": [
      {"name": "kpt_001", "text": "Legacy migrated point", "helpful": 0, "harmful": 0},
      {"name": "oth-001", "text": "New uncategorized point", "helpful": 1, "harmful": 0}
    ]
  }
}
```

**Empty playbook** (returned by `load_playbook()` when file does not exist or is corrupt):
```json
{
  "version": "1.0",
  "last_updated": null,
  "sections": {
    "PATTERNS & APPROACHES": [],
    "MISTAKES TO AVOID": [],
    "USER PREFERENCES": [],
    "PROJECT CONTEXT": [],
    "OTHERS": []
  }
}
```

---

### ExtractionResult (updated)

The output of `extract_keypoints()`. The `new_key_points` field changes from `list[str]` to `list[str | dict]`.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `new_key_points` | `list[str \| dict]` | May be empty. Each entry is either a string (legacy format) or a dict with `text` and `section`. | New key points discovered by the reflector LLM. |
| `evaluations` | `list[Evaluation]` | May be empty. | Ratings of existing key points. |

#### NewKeyPoint Entry (sub-schema of ExtractionResult.new_key_points)

Each entry in `new_key_points` can be:

**Format A: Dict (new format)**

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `text` | `str` | Non-empty. | The key point content. |
| `section` | `str` | Should be one of the canonical section names. Resolved case-insensitively. Falls back to `"OTHERS"` if unrecognized, missing, None, or empty. | Target section for this key point. |

**Format B: String (legacy backward compat)**

A plain string is treated as `{"text": string, "section": "OTHERS"}`.

**JSON example (new format)**:
```json
{
  "new_key_points": [
    {"text": "Use structured logging instead of print", "section": "PATTERNS & APPROACHES"},
    {"text": "Avoid bare except clauses", "section": "MISTAKES TO AVOID"},
    {"text": "User prefers dark mode", "section": "USER PREFERENCES"}
  ],
  "evaluations": [
    {"name": "pat-001", "rating": "helpful"},
    {"name": "kpt_001", "rating": "neutral"}
  ]
}
```

**JSON example (legacy backward compat)**:
```json
{
  "new_key_points": [
    "Use structured logging instead of print statements"
  ],
  "evaluations": [
    {"name": "kpt_001", "rating": "helpful"}
  ]
}
```

#### Evaluation (sub-schema, unchanged from scoring)

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `name` | `str` | Should match an existing `PlaybookEntry.name` in any section. Unmatched names silently ignored. | The key point being evaluated. |
| `rating` | `str` | One of `"helpful"`, `"harmful"`, `"neutral"`. Unrecognized values are no-op. | The reflector's assessment. |

---

## Function Signatures

### `generate_keypoint_name(section_entries: list[dict], slug: str) -> str`

**Previous signature**: `generate_keypoint_name(existing_names: set) -> str`

**New signature**: `generate_keypoint_name(section_entries: list[dict], slug: str) -> str`

| Parameter | Type | Description |
|-----------|------|-------------|
| `section_entries` | `list[dict]` | The list of key point entries in the target section. Each entry is a `PlaybookEntry` dict. |
| `slug` | `str` | The slug prefix for the section (e.g., `"pat"`, `"mis"`, `"oth"`). Obtained from `SECTION_SLUGS`. |
| **Returns** | `str` | The next available ID in `{slug}-{NNN:03d}` format. |

**Behavior**:
- Scans `section_entries` for names matching `^{slug}-(\d+)$` regex
- Finds the highest NNN among matches (0 if no matches)
- Returns `f"{slug}-{max_num + 1:03d}"`
- Legacy `kpt_NNN` entries in `section_entries` are ignored (do not match the regex)

---

### `load_playbook() -> dict`

**Signature**: Unchanged.

**Return shape**: Always returns a sections-based dict:
```python
{
    "version": str,         # "1.0"
    "last_updated": str | None,
    "sections": {
        "PATTERNS & APPROACHES": list[PlaybookEntry],
        "MISTAKES TO AVOID": list[PlaybookEntry],
        "USER PREFERENCES": list[PlaybookEntry],
        "PROJECT CONTEXT": list[PlaybookEntry],
        "OTHERS": list[PlaybookEntry],
    }
}
```

**Migration behaviors**:

| File State | Behavior |
|------------|----------|
| File does not exist | Returns default empty playbook (all sections empty) |
| File is corrupt/unparseable JSON | Returns default empty playbook (all sections empty) |
| File has `sections` key only | Returns sections data; ensures all 5 canonical sections exist (adds empty lists for missing) |
| File has `key_points` key only (flat format) | Migrates: applies scoring migration to each entry, places all into OTHERS, initializes other sections as empty. Emits OBS-SECT-001 diagnostic. |
| File has both `sections` and `key_points` | Uses `sections`, ignores `key_points`. Emits dual-key warning diagnostic. |
| File has neither `sections` nor `key_points` | Returns default empty playbook |

**Key guarantee**: The returned dict NEVER contains a `key_points` key (INV-SECT-007).

---

### `save_playbook(playbook: dict) -> None`

**Signature**: Unchanged.

**Precondition**: `playbook` dict MUST contain a `sections` key. If absent, raises `AssertionError` (INV-SECT-001).

**Behavior**:
1. Asserts `"sections" in playbook`
2. Sets `playbook["last_updated"]` to current ISO 8601 timestamp
3. Writes to `{project_dir}/.claude/playbook.json` via `json.dump()`

**Key guarantee**: The written file will always have a `sections` key and never have a `key_points` key.

---

### `format_playbook(playbook: dict) -> str`

**Signature**: Unchanged.

**Input**: A sections-based playbook dict.

**Output**: A formatted string for injection into the prompt, or `""` if all sections are empty.

**Format**:
```
## SECTION_NAME_1
[id-001] helpful=X harmful=Y :: text
[id-002] helpful=X harmful=Y :: text

## SECTION_NAME_2
[id-003] helpful=X harmful=Y :: text
```

**Rules**:
- Sections output in canonical order (PATTERNS & APPROACHES, MISTAKES TO AVOID, USER PREFERENCES, PROJECT CONTEXT, OTHERS)
- Empty sections are omitted (no header, no blank line)
- Section blocks separated by blank lines
- Each entry formatted as `[{name}] helpful={helpful} harmful={harmful} :: {text}`
- Output inserted into `playbook.txt` template at `{key_points}` placeholder

---

### `update_playbook_data(playbook: dict, extraction_result: dict) -> dict`

**Signature**: `update_playbook_data(playbook: dict, extraction_result: dict) -> dict` (UNCHANGED -- callers do not need modification).

The function internally destructures `extraction_result["new_key_points"]` and `extraction_result["evaluations"]`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `playbook` | `dict` | Sections-based playbook dict. Modified in-place and returned. |
| `extraction_result` | `dict` | The extraction result dict containing `new_key_points` (`list[str \| dict]`) and `evaluations` (`list[dict]`). |
| **Returns** | `dict` | The modified playbook dict (same reference as input). |

**Behavior**:
1. **Add new key points**: For each entry in `new_key_points`:
   - Resolve section name (case-insensitive match, fallback to OTHERS)
   - Skip if text is empty or already exists in any section
   - Generate ID using `generate_keypoint_name(target_section_entries, slug)`
   - Append to target section with `helpful=0, harmful=0`
2. **Apply evaluations**: Build cross-section name lookup. For each evaluation, increment the appropriate counter on the matching entry (regardless of section).
3. **Prune**: Remove entries where `harmful >= 3 AND harmful > helpful` from all sections.

---

## Migration Contracts

### Flat-to-Sections Migration

`load_playbook()` handles the one-time migration from flat `key_points` format to sections.

**Input** (flat format `playbook.json`):
```json
{
  "version": "1.0",
  "last_updated": "2026-01-15T10:00:00",
  "key_points": [
    {"name": "kpt_001", "text": "use types", "helpful": 5, "harmful": 1},
    {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0},
    "bare string entry",
    {"name": "kpt_004", "text": "avoid globals", "score": -3}
  ]
}
```

**Output** (after `load_playbook()`):
```json
{
  "version": "1.0",
  "last_updated": "2026-01-15T10:00:00",
  "sections": {
    "PATTERNS & APPROACHES": [],
    "MISTAKES TO AVOID": [],
    "USER PREFERENCES": [],
    "PROJECT CONTEXT": [],
    "OTHERS": [
      {"name": "kpt_001", "text": "use types", "helpful": 5, "harmful": 1},
      {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0},
      {"name": "kpt_003", "text": "bare string entry", "helpful": 0, "harmful": 0},
      {"name": "kpt_004", "text": "avoid globals", "helpful": 0, "harmful": 3}
    ]
  }
}
```

**Migration rules**:
1. Scoring migration (branches 0-3 from `docs/scoring/design.md`) is applied to each entry first
2. All migrated entries are placed into the OTHERS section
3. All other sections are initialized as empty lists
4. Existing IDs are preserved unchanged (INV-SECT-004)
5. `key_points` key is removed from the dict
6. The scoring migration branch for bare strings uses `generate_keypoint_name()` -- during migration this still uses the legacy `kpt_NNN` pattern (the entries are being migrated, not newly categorized)

**Important note on bare-string ID generation during migration**: During flat-to-sections migration, bare strings (Branch 1 in scoring migration) need name generation. Since these entries are being migrated into OTHERS (not newly added by the LLM), the migration code generates names using the legacy `kpt_NNN` pattern by scanning the existing names set, consistent with the current behavior. Post-migration, all NEW key points use slug-based IDs.

---

### Section Name Resolution

`_resolve_section()` normalizes section names from LLM responses.

| Input | Output | Diagnostic |
|-------|--------|-----------|
| `"PATTERNS & APPROACHES"` | `"PATTERNS & APPROACHES"` | None |
| `"patterns & approaches"` | `"PATTERNS & APPROACHES"` | None |
| `"Patterns & Approaches"` | `"PATTERNS & APPROACHES"` | None |
| `"  patterns & approaches  "` | `"PATTERNS & APPROACHES"` | None (stripped before matching) |
| `"MISTAKES TO AVOID"` | `"MISTAKES TO AVOID"` | None |
| `"OTHERS"` | `"OTHERS"` | None |
| `"others"` | `"OTHERS"` | None |
| `"RANDOM STUFF"` | `"OTHERS"` | OBS-SECT-002 |
| `""` | `"OTHERS"` | None |
| `"   "` | `"OTHERS"` | None (empty after stripping) |
| `None` | `"OTHERS"` | None |

**Rule**: Leading/trailing whitespace is stripped before matching. Case-insensitive exact match against canonical names. No fuzzy matching, no substring matching.

---

## Formatted Output Contract

### Format String (per entry, unchanged from scoring)

```python
f"[{kp['name']}] helpful={kp['helpful']} harmful={kp['harmful']} :: {kp['text']}"
```

### Section Header Format

```python
f"## {section_name}"
```

### Complete Output Example

```
## PATTERNS & APPROACHES
[pat-001] helpful=5 harmful=1 :: Always use type hints for function signatures
[pat-002] helpful=3 harmful=0 :: Prefer composition over inheritance

## MISTAKES TO AVOID
[mis-001] helpful=2 harmful=0 :: Never catch bare exceptions

## OTHERS
[kpt_001] helpful=0 harmful=0 :: Legacy migrated point
[oth-001] helpful=1 harmful=0 :: New uncategorized point
```

### Parsing Contract (for Claude's interpretation)

The format is designed so that Claude (the LLM reading the prompt) can:
- See semantic categories via `## SECTION_NAME` headers
- Identify each key point by its `[name]` tag
- Read the `helpful=N` and `harmful=N` counts
- Access the guidance text after the `::` delimiter
- Prioritize section-appropriate application (e.g., actively avoid items under MISTAKES TO AVOID)
