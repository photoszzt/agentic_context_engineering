# Requirements Specification: Scoring Module

## Intent Traceability

This section preserves the success criteria from the approved intent.
The full intent document is in `.planning/intent.md` for historical reference.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* |
|------|-------------------|-------------------|
| SC-SCORE-001 | Each key point carries `{name, text, helpful, harmful}` schema. `helpful >= 0`, `harmful >= 0`. No `score` field in newly written files. | REQ-SCORE-001, INV-SCORE-001, INV-SCORE-002 |
| SC-SCORE-002 | "helpful" rating increments `helpful` by 1; "harmful" increments `harmful` by 1; "neutral" changes neither counter. | REQ-SCORE-002, SCN-SCORE-002-01, SCN-SCORE-002-02, SCN-SCORE-002-03, SCN-SCORE-002-04 |
| SC-SCORE-003 | `format_playbook()` outputs `[name] helpful=X harmful=Y :: text` format, enabling ratio-aware decisions. | REQ-SCORE-003, SCN-SCORE-003-01, SCN-SCORE-003-02 |
| SC-SCORE-004 | `load_playbook()` migrates 3 legacy formats: bare strings, dicts without score, dicts with score. | REQ-SCORE-004, REQ-SCORE-005, REQ-SCORE-006, SCN-SCORE-004-01, SCN-SCORE-005-01, SCN-SCORE-006-01, SCN-SCORE-006-02 |
| SC-SCORE-005 | Pruning removes entries where `harmful >= 3 AND harmful > helpful`. Zero-evaluation entries never pruned. | REQ-SCORE-007, INV-SCORE-003, SCN-SCORE-007-01, SCN-SCORE-007-02, SCN-SCORE-007-03, SCN-SCORE-007-04 |
| SC-SCORE-006 | `playbook.txt` template updated to explain helpful/harmful semantics to Claude. | REQ-SCORE-008, SCN-SCORE-008-01 |

---

## Requirements

### REQ-SCORE-001: PlaybookEntry Schema {#REQ-SCORE-001}
- **Implements**: SC-SCORE-001
- **GIVEN**: A key point entry in `playbook.json`
- **WHEN**: The entry is written to disk by `save_playbook()`
- **THEN**:
  - The entry is a JSON object with exactly the keys: `name` (string), `text` (string), `helpful` (integer), `harmful` (integer)
  - No `score` key exists in the written object
  - All other top-level playbook keys (`version`, `last_updated`, `key_points`) are preserved unchanged

### REQ-SCORE-002: Counter Increment on Rating {#REQ-SCORE-002}
- **Implements**: SC-SCORE-002
- **GIVEN**: A playbook with existing key points and an extraction result containing evaluations
- **WHEN**: `update_playbook_data(playbook, extraction_result)` is called
- **THEN**:
  - For each evaluation with `rating == "helpful"`: the matching key point's `helpful` counter is incremented by 1
  - For each evaluation with `rating == "harmful"`: the matching key point's `harmful` counter is incremented by 1
  - For each evaluation with `rating == "neutral"`: neither counter changes
  - For each evaluation with an unrecognized rating value: neither counter changes (defensive)
  - For each evaluation referencing a `name` not in the playbook: the evaluation is silently ignored

### REQ-SCORE-003: Formatted Output with Counts {#REQ-SCORE-003}
- **Implements**: SC-SCORE-003
- **GIVEN**: A playbook with key points
- **WHEN**: `format_playbook(playbook)` is called
- **THEN**:
  - Each key point is formatted as `[{name}] helpful={helpful} harmful={harmful} :: {text}`
  - Key points are joined by newlines
  - The formatted key points are inserted into the `playbook.txt` template at the `{key_points}` placeholder
  - An empty key points list returns an empty string (existing behavior preserved)

### REQ-SCORE-004: Migration -- Bare String Entries {#REQ-SCORE-004}
- **Implements**: SC-SCORE-004
- **GIVEN**: A `playbook.json` where `key_points` contains a bare string entry (e.g., `"always use type hints"`)
- **WHEN**: `load_playbook()` is called
- **THEN**:
  - The string is converted to `{name: <generated>, text: <string>, helpful: 0, harmful: 0}`
  - `name` is generated via `generate_keypoint_name()` using existing names
  - No `score` field is present in the resulting dict

### REQ-SCORE-005: Migration -- Dict Without Score {#REQ-SCORE-005}
- **Implements**: SC-SCORE-004
- **GIVEN**: A `playbook.json` where `key_points` contains a dict entry that has `text` (and optionally `name`) but neither `score` nor `helpful`/`harmful` fields
- **WHEN**: `load_playbook()` is called
- **THEN**:
  - `helpful` defaults to `0`
  - `harmful` defaults to `0`
  - If `name` is missing, it is generated via `generate_keypoint_name()`
  - No `score` field is present in the resulting dict

### REQ-SCORE-006: Migration -- Dict With Score {#REQ-SCORE-006}
- **Implements**: SC-SCORE-004
- **GIVEN**: A `playbook.json` where `key_points` contains a dict entry with a `score` field but no `helpful`/`harmful` fields
- **WHEN**: `load_playbook()` is called
- **THEN**:
  - `helpful` is set to `max(score, 0)`
  - `harmful` is set to `max(-score, 0)`
  - The `score` field is removed from the dict (dropped)
  - If `name` is missing, it is generated via `generate_keypoint_name()`
- **Edge case**: If a dict has BOTH `helpful`/`harmful` fields AND a residual `score` field, the entry is treated as already-migrated (Branch 0 in design.md): the existing `helpful`/`harmful` values are preserved unchanged, and `score` is defensively dropped. See SCN-SCORE-006-02.

### REQ-SCORE-007: Pruning Rule {#REQ-SCORE-007}
- **Implements**: SC-SCORE-005
- **GIVEN**: A playbook with key points after counter updates
- **WHEN**: `update_playbook_data()` applies the pruning step
- **THEN**:
  - A key point is removed if and only if: `harmful >= 3 AND harmful > helpful`
  - A key point with `helpful == 0 AND harmful == 0` is never removed (guard condition)
  - All other key points are retained
  - The old pruning rule (`score > -5`) is completely replaced

### REQ-SCORE-008: Playbook Template Update {#REQ-SCORE-008}
- **Implements**: SC-SCORE-006
- **GIVEN**: The `playbook.txt` template file
- **WHEN**: The template is loaded and used by `format_playbook()`
- **THEN**:
  - The template explains to Claude that each key point has `helpful` and `harmful` counts
  - The template indicates that higher `helpful` counts signal proven value
  - The template indicates that higher `harmful` counts signal problematic guidance
  - The template instructs Claude to weigh the ratio when deciding how much to trust each key point
  - The `{key_points}` placeholder is preserved for formatted entry injection

---

## Scenarios

### SCN-SCORE-002-01: Helpful Rating Increments Counter {#SCN-SCORE-002-01}
- **Implements**: REQ-SCORE-002
- **GIVEN**: A playbook with key point `{name: "kpt_001", text: "use types", helpful: 3, harmful: 1}`
- **AND**: An extraction result with evaluations `[{name: "kpt_001", rating: "helpful"}]`
- **WHEN**: `update_playbook_data(playbook, extraction_result)` is called
- **THEN**: `kpt_001.helpful == 4` and `kpt_001.harmful == 1`

### SCN-SCORE-002-02: Harmful Rating Increments Counter {#SCN-SCORE-002-02}
- **Implements**: REQ-SCORE-002
- **GIVEN**: A playbook with key point `{name: "kpt_001", text: "use types", helpful: 3, harmful: 1}`
- **AND**: An extraction result with evaluations `[{name: "kpt_001", rating: "harmful"}]`
- **WHEN**: `update_playbook_data(playbook, extraction_result)` is called
- **THEN**: `kpt_001.helpful == 3` and `kpt_001.harmful == 2`

### SCN-SCORE-002-03: Neutral Rating Changes Nothing {#SCN-SCORE-002-03}
- **Implements**: REQ-SCORE-002
- **GIVEN**: A playbook with key point `{name: "kpt_001", text: "use types", helpful: 3, harmful: 1}`
- **AND**: An extraction result with evaluations `[{name: "kpt_001", rating: "neutral"}]`
- **WHEN**: `update_playbook_data(playbook, extraction_result)` is called
- **THEN**: `kpt_001.helpful == 3` and `kpt_001.harmful == 1`

### SCN-SCORE-002-04: Unknown Rating Changes Nothing {#SCN-SCORE-002-04}
- **Implements**: REQ-SCORE-002
- **GIVEN**: A playbook with key point `{name: "kpt_001", text: "use types", helpful: 3, harmful: 1}`
- **AND**: An extraction result with evaluations `[{name: "kpt_001", rating: "bogus"}]`
- **WHEN**: `update_playbook_data(playbook, extraction_result)` is called
- **THEN**: `kpt_001.helpful == 3` and `kpt_001.harmful == 1`

### SCN-SCORE-003-01: Format Includes Counts {#SCN-SCORE-003-01}
- **Implements**: REQ-SCORE-003
- **GIVEN**: A playbook with key points:
  - `{name: "kpt_001", text: "use type hints", helpful: 5, harmful: 1}`
  - `{name: "kpt_002", text: "prefer pathlib", helpful: 0, harmful: 0}`
- **WHEN**: `format_playbook(playbook)` is called
- **THEN**: The key points text block contains:
  ```
  [kpt_001] helpful=5 harmful=1 :: use type hints
  [kpt_002] helpful=0 harmful=0 :: prefer pathlib
  ```

### SCN-SCORE-003-02: Empty Playbook Returns Empty String {#SCN-SCORE-003-02}
- **Implements**: REQ-SCORE-003
- **GIVEN**: A playbook with `key_points: []`
- **WHEN**: `format_playbook(playbook)` is called
- **THEN**: Returns `""`

### SCN-SCORE-004-01: Load Bare String Entry {#SCN-SCORE-004-01}
- **Implements**: REQ-SCORE-004
- **GIVEN**: A `playbook.json` with `key_points: ["always use type hints"]`
- **WHEN**: `load_playbook()` is called
- **THEN**: Result contains key point `{name: "kpt_001", text: "always use type hints", helpful: 0, harmful: 0}`
- **AND**: No `score` key exists on the entry

### SCN-SCORE-005-01: Load Dict Without Score or Counters {#SCN-SCORE-005-01}
- **Implements**: REQ-SCORE-005
- **GIVEN**: A `playbook.json` with `key_points: [{"name": "kpt_001", "text": "use types"}]`
- **WHEN**: `load_playbook()` is called
- **THEN**: Result contains key point `{name: "kpt_001", text: "use types", helpful: 0, harmful: 0}`
- **AND**: No `score` key exists on the entry

### SCN-SCORE-006-01: Load Dict With Score Field {#SCN-SCORE-006-01}
- **Implements**: REQ-SCORE-006
- **GIVEN**: A `playbook.json` with `key_points: [{"name": "kpt_001", "text": "use types", "score": -3}]`
- **WHEN**: `load_playbook()` is called
- **THEN**: Result contains key point `{name: "kpt_001", text: "use types", helpful: 0, harmful: 3}`
- **AND**: No `score` key exists on the entry

### SCN-SCORE-006-02: Load Dict With Score AND Existing Helpful/Harmful Fields {#SCN-SCORE-006-02}
- **Implements**: REQ-SCORE-006
- **GIVEN**: A `playbook.json` with `key_points: [{"name": "kpt_001", "text": "use types", "helpful": 3, "harmful": 1, "score": 2}]` (all fields present: `helpful`, `harmful`, AND residual `score`)
- **WHEN**: `load_playbook()` is called
- **THEN**: Result contains key point `{name: "kpt_001", text: "use types", helpful: 3, harmful: 1}`
- **AND**: The existing `helpful` and `harmful` values are preserved unchanged (canonical fields win)
- **AND**: The `score` field is defensively dropped
- **AND**: No `score` key exists on the entry
- **RATIONALE**: This is an edge case where a dict already has the canonical `helpful`/`harmful` fields but also carries a residual `score` field (e.g., from a partial migration or manual edit). The canonical fields take precedence; `score` is silently removed. This corresponds to Branch 0 (already-migrated) in `design.md`, which defensively calls `item.pop("score", None)`.

### SCN-SCORE-007-01: Prune Consistently Harmful Entry {#SCN-SCORE-007-01}
- **Implements**: REQ-SCORE-007
- **GIVEN**: A playbook with key point `{name: "kpt_001", text: "bad advice", helpful: 1, harmful: 4}`
- **WHEN**: `update_playbook_data()` applies the pruning step
- **THEN**: `kpt_001` is removed from the playbook
- **BECAUSE**: `harmful (4) >= 3` AND `harmful (4) > helpful (1)`

### SCN-SCORE-007-02: Retain Entry with High Harmful but Higher Helpful {#SCN-SCORE-007-02}
- **Implements**: REQ-SCORE-007
- **GIVEN**: A playbook with key point `{name: "kpt_001", text: "controversial", helpful: 10, harmful: 4}`
- **WHEN**: `update_playbook_data()` applies the pruning step
- **THEN**: `kpt_001` is retained
- **BECAUSE**: `harmful (4) >= 3` but `harmful (4) > helpful (10)` is False

### SCN-SCORE-007-03: Retain Zero-Evaluation Entry {#SCN-SCORE-007-03}
- **Implements**: REQ-SCORE-007, INV-SCORE-003
- **GIVEN**: A playbook with key point `{name: "kpt_001", text: "new untested", helpful: 0, harmful: 0}`
- **WHEN**: `update_playbook_data()` applies the pruning step
- **THEN**: `kpt_001` is retained
- **BECAUSE**: `harmful (0) >= 3` is False (floor check fails)

### SCN-SCORE-007-04: Retain Entry with Harmful Below Floor {#SCN-SCORE-007-04}
- **Implements**: REQ-SCORE-007
- **GIVEN**: A playbook with key point `{name: "kpt_001", text: "new entry", helpful: 0, harmful: 2}`
- **WHEN**: `update_playbook_data()` applies the pruning step
- **THEN**: `kpt_001` is retained
- **BECAUSE**: `harmful (2) >= 3` is False (below floor threshold)

### SCN-SCORE-008-01: Template Explains Scoring Semantics {#SCN-SCORE-008-01}
- **Implements**: REQ-SCORE-008
- **GIVEN**: The `playbook.txt` template file after modification
- **WHEN**: The template content is inspected
- **THEN**:
  - The template contains guidance that `helpful` counts indicate proven value
  - The template contains guidance that `harmful` counts indicate problematic guidance
  - The template instructs Claude to consider the ratio of helpful to harmful
  - The `{key_points}` placeholder is present

---

## Invariants

### INV-SCORE-001: Helpful Counter Non-Negative {#INV-SCORE-001}
- **Implements**: SC-SCORE-001
- **Statement**: For every key point entry in memory and on disk, `helpful >= 0` at all times.
- **Enforced by**: Migration formulas use `max(value, 0)` (REQ-SCORE-006); new entries initialize to `0` (REQ-SCORE-004, REQ-SCORE-005); increments are always `+1` (REQ-SCORE-002); no decrement operation exists.

### INV-SCORE-002: Harmful Counter Non-Negative {#INV-SCORE-002}
- **Implements**: SC-SCORE-001
- **Statement**: For every key point entry in memory and on disk, `harmful >= 0` at all times.
- **Enforced by**: Same mechanisms as INV-SCORE-001.

### INV-SCORE-003: Zero-Evaluation Entries Never Pruned {#INV-SCORE-003}
- **Implements**: SC-SCORE-005
- **Statement**: An entry with `helpful == 0 AND harmful == 0` is never removed by the pruning rule.
- **Enforced by**: The pruning condition `harmful >= 3 AND harmful > helpful` evaluates to `0 >= 3 AND 0 > 0` which is `False AND False` = `False`. The `harmful >= 3` floor prevents any entry with fewer than 3 harmful ratings from being pruned.

### INV-SCORE-004: No Score Field in Output {#INV-SCORE-004}
- **Implements**: SC-SCORE-001
- **Statement**: After `load_playbook()` completes, no key point entry in the returned dict contains a `score` key. After `save_playbook()` writes, no key point entry in the JSON file contains a `score` key.
- **Enforced by**: Migration in `load_playbook()` explicitly drops the `score` key (REQ-SCORE-006); new entries created in `update_playbook_data()` never include a `score` key (REQ-SCORE-001).

### INV-SCORE-005: Migration Round-Trip Stability {#INV-SCORE-005}
- **Implements**: CON-SCORE-002
- **Statement**: If a playbook file is loaded via `load_playbook()`, immediately saved via `save_playbook()`, and loaded again, the in-memory representation is identical between the first and second load for: (1) the `key_points` list (all entries in canonical `{name, text, helpful, harmful}` schema), and (2) the `version` field (preserved unchanged through the round-trip). The `version` field is never modified by this module. Only `last_updated` changes on save and is excluded from the stability guarantee.
- **Enforced by**: After migration, all key point entries are in the canonical `{name, text, helpful, harmful}` schema. A second load finds `helpful`/`harmful` fields already present and performs no further migration. The `version` field is read from disk by `load_playbook()` and written back unchanged by `save_playbook()` -- neither function modifies it. `last_updated` is set to the current timestamp on each `save_playbook()` call, so its value changes between saves but this is expected and excluded from the round-trip stability guarantee.
