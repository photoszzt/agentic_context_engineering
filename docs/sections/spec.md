# Requirements Specification: Sections Module

## Intent Traceability

This section preserves the success criteria from the approved intent.
The full intent document is in `.planning/intent.md` for historical reference.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* |
|------|-------------------|-------------------|
| SC-SECT-001 | `playbook.json` stores key points organized under named sections. The schema supports a `sections` object where each key is a section name and each value is a list of key point objects. Canonical default sections: PATTERNS & APPROACHES, MISTAKES TO AVOID, USER PREFERENCES, PROJECT CONTEXT, OTHERS. Key point objects retain `{name, text, helpful, harmful}`. | REQ-SECT-001, INV-SECT-001, INV-SECT-002, INV-SECT-003 |
| SC-SECT-002 | Key point IDs use section-derived prefixes (`{slug}-{NNN}`) with per-section counters. Slug mapping defined in code. `generate_keypoint_name()` accepts slug, scans section entries for `{slug}-NNN`, returns `{slug}-{max+1:03d}`. | REQ-SECT-002, SCN-SECT-002-01, SCN-SECT-002-02, SCN-SECT-002-03 |
| SC-SECT-003 | `format_playbook()` outputs key points grouped under markdown section headers (`## SECTION_NAME`) in canonical order. Empty sections omitted. | REQ-SECT-003, SCN-SECT-003-01, SCN-SECT-003-02, SCN-SECT-003-03 |
| SC-SECT-004 | The extraction prompt instructs the LLM to assign each new key point to a section. `new_key_points` changes from `list[str]` to `list[dict]` with `{"text": "...", "section": "..."}`. Case-insensitive exact match for section normalization, fallback to OTHERS. Backward compat: plain strings treated as `{"text": str, "section": "OTHERS"}`. | REQ-SECT-004, REQ-SECT-005, SCN-SECT-004-01, SCN-SECT-004-02, SCN-SECT-004-03, SCN-SECT-004-04, SCN-SECT-004-05 |
| SC-SECT-005 | `load_playbook()` detects old-format (flat `key_points`) and migrates to sections, placing all existing entries into OTHERS with IDs preserved. Legacy `kpt_NNN` IDs are never auto-renamed. Dual-key files: `sections` takes precedence, `key_points` ignored with warning. | REQ-SECT-006, REQ-SECT-007, SCN-SECT-006-01, SCN-SECT-006-02, SCN-SECT-006-03, SCN-SECT-006-04, INV-SECT-004, INV-SECT-005 |
| SC-SECT-006 | `update_playbook_data()` iterates over ALL sections for evaluations/pruning. New key points inserted into target section using slug-based ID generator. `extract_keypoints()` builds flat `{name: text}` dict from all sections. | REQ-SECT-008, REQ-SECT-009, SCN-SECT-008-01, SCN-SECT-008-02, SCN-SECT-009-01 |
| QG-SECT-001 | Section slug mapping defined in a single constant (`SECTION_SLUGS`) used by all code paths. | REQ-SECT-010 |

---

## Requirements

### REQ-SECT-001: Sections-Based Playbook Schema {#REQ-SECT-001}
- **Implements**: SC-SECT-001
- **GIVEN**: A `playbook.json` file written by `save_playbook()`
- **WHEN**: The file is inspected
- **THEN**:
  - The top-level object contains a `sections` key
  - `sections` is a JSON object (dict) where each key is a section name (string) and each value is a list of key point objects
  - Each key point object has exactly the keys: `name` (string), `text` (string), `helpful` (integer), `harmful` (integer)
  - The section names are drawn from the canonical set: `"PATTERNS & APPROACHES"`, `"MISTAKES TO AVOID"`, `"USER PREFERENCES"`, `"PROJECT CONTEXT"`, `"OTHERS"`
  - A `key_points` key does NOT exist in newly written files (the flat list is replaced by the `sections` structure)
  - The `version` and `last_updated` top-level keys are preserved

### REQ-SECT-002: Section-Prefixed Key Point IDs {#REQ-SECT-002}
- **Implements**: SC-SECT-002
- **GIVEN**: A new key point being added to a section
- **WHEN**: `generate_keypoint_name(section_entries, slug)` is called
- **THEN**:
  - The function scans `section_entries` (list of key point dicts) for names matching the regex `^{slug}-(\d+)$`
  - It finds the highest NNN among matches (or 0 if no matches)
  - It returns `"{slug}-{max+1:03d}"` (e.g., `"pat-001"`, `"mis-002"`)
  - Legacy `kpt_NNN` entries in the list do NOT affect the counter (they are ignored by the regex scan)

### REQ-SECT-003: Formatted Output with Section Headers {#REQ-SECT-003}
- **Implements**: SC-SECT-003
- **GIVEN**: A playbook with sections containing key points
- **WHEN**: `format_playbook(playbook)` is called
- **THEN**:
  - The output groups key points under markdown section headers (`## SECTION_NAME`)
  - Sections are output in canonical order: PATTERNS & APPROACHES, MISTAKES TO AVOID, USER PREFERENCES, PROJECT CONTEXT, OTHERS
  - Each key point within a section is formatted as `[{name}] helpful={helpful} harmful={harmful} :: {text}` (preserving scoring format from REQ-SCORE-003)
  - Sections with zero entries are omitted entirely (no header, no blank lines)
  - When all sections are empty, `format_playbook()` returns `""` directly, without performing template insertion
  - Template insertion only occurs when at least one section has at least one entry: the formatted text is inserted into the `playbook.txt` template at the `{key_points}` placeholder

### REQ-SECT-004: LLM Categorization of New Key Points {#REQ-SECT-004}
- **Implements**: SC-SECT-004
- **GIVEN**: The `reflection.txt` template
- **WHEN**: The template is loaded and used by `extract_keypoints()`
- **THEN**:
  - The template lists all canonical section names so the LLM knows the available categories
  - The template instructs the LLM to assign each new key point to one of the sections
  - The expected JSON output format shows `new_key_points` as `list[dict]` with each entry having `{"text": "...", "section": "..."}`
  - The template uses the exact canonical section names (case-sensitive)

### REQ-SECT-005: Backward Compatible Handling of new_key_points {#REQ-SECT-005}
- **Implements**: SC-SECT-004
- **GIVEN**: An extraction result from the LLM
- **WHEN**: `update_playbook_data()` processes `new_key_points`
- **THEN**:
  - If an entry is a plain string (old format): it is treated as `{"text": string, "section": "OTHERS"}`
  - Before matching, the `section` field value is stripped of leading and trailing whitespace. Empty string after stripping is treated as missing (-> OTHERS).
  - If an entry is a dict with a valid `section` field: the section is resolved via case-insensitive exact match against canonical names
  - If an entry is a dict with `section` that is missing, `None`, or empty string (including empty after stripping): the key point is assigned to `"OTHERS"`
  - If an entry is a dict with `section` that does not match any canonical name (case-insensitive, after stripping): the key point is assigned to `"OTHERS"` and an OBS-SECT-002 diagnostic is emitted

### REQ-SECT-006: Migration from Flat Format to Sections {#REQ-SECT-006}
- **Implements**: SC-SECT-005
- **GIVEN**: A `playbook.json` with a flat `key_points` array and NO `sections` key
- **WHEN**: `load_playbook()` is called
- **THEN**:
  - All entries from `key_points` are placed into the `"OTHERS"` section
  - Existing IDs (e.g., `kpt_NNN`) are preserved unchanged
  - All other sections are initialized as empty lists
  - The returned dict contains a `sections` key (not a `key_points` key)
  - An OBS-SECT-001 diagnostic is emitted with the count of migrated entries

### REQ-SECT-007: Dual-Key File Handling {#REQ-SECT-007}
- **Implements**: SC-SECT-005
- **GIVEN**: A `playbook.json` containing BOTH a `sections` key AND a `key_points` key
- **WHEN**: `load_playbook()` is called
- **THEN**:
  - `sections` takes precedence; the `sections` data is used as the authoritative source
  - `key_points` is ignored
  - A diagnostic warning is logged (via `save_diagnostic()` gated by `is_diagnostic_mode()`) indicating dual-key detection
  - The returned dict contains only the `sections` key (no `key_points` key)

### REQ-SECT-008: Evaluations and Pruning Across Sections {#REQ-SECT-008}
- **Implements**: SC-SECT-006
- **GIVEN**: A playbook with sections and an extraction result containing evaluations
- **WHEN**: `update_playbook_data(playbook, extraction_result)` is called (signature unchanged; the function internally destructures `extraction_result["new_key_points"]` and `extraction_result["evaluations"]`)
- **THEN**:
  - A name-to-keypoint lookup is built by iterating ALL sections
  - For each evaluation, the matching key point is found regardless of which section it resides in
  - Counter increments follow existing rules: `"helpful"` -> `helpful += 1`, `"harmful"` -> `harmful += 1`, `"neutral"` -> no-op, unrecognized -> no-op
  - Pruning (`harmful >= 3 AND harmful > helpful`) is applied across ALL sections
  - Pruned entries are removed from their respective sections

### REQ-SECT-009: Flat Key Point Extraction for LLM Prompt {#REQ-SECT-009}
- **Implements**: SC-SECT-006
- **GIVEN**: A playbook with sections containing key points
- **WHEN**: `extract_keypoints()` builds the `playbook_dict` for the LLM prompt
- **THEN**:
  - A flat `{name: text}` dict is constructed by iterating over ALL sections
  - If all sections are empty, the returned dict is `{}`
  - The dict is passed to the `reflection.txt` template as the `{playbook}` variable
  - Section information is NOT included in this flat dict (the LLM gets section context from the formatted playbook output per REQ-SECT-003)

### REQ-SECT-010: Canonical Section-to-Slug Mapping {#REQ-SECT-010}
- **Implements**: QG-SECT-001
- **Statement**: A module-level constant `SECTION_SLUGS` (`dict[str, str]`) maps each canonical section name to its slug prefix:
  - `"PATTERNS & APPROACHES"` -> `"pat"`
  - `"MISTAKES TO AVOID"` -> `"mis"`
  - `"USER PREFERENCES"` -> `"pref"`
  - `"PROJECT CONTEXT"` -> `"ctx"`
  - `"OTHERS"` -> `"oth"`
- The iteration order of `SECTION_SLUGS` determines the canonical section order used by `format_playbook()` (SC-SECT-003).

---

## Scenarios

### SCN-SECT-002-01: Generate First ID for Empty Section {#SCN-SECT-002-01}
- **Implements**: REQ-SECT-002
- **GIVEN**: An empty section (no entries) for "PATTERNS & APPROACHES" (slug: `pat`)
- **WHEN**: `generate_keypoint_name([], "pat")` is called
- **THEN**: Returns `"pat-001"`

### SCN-SECT-002-02: Generate Next ID After Existing Entries {#SCN-SECT-002-02}
- **Implements**: REQ-SECT-002
- **GIVEN**: A section with entries `[{name: "pat-001", ...}, {name: "pat-003", ...}]` (slug: `pat`)
- **WHEN**: `generate_keypoint_name(section_entries, "pat")` is called
- **THEN**: Returns `"pat-004"` (max existing is 003, next is 004)

### SCN-SECT-002-03: Legacy kpt_NNN IDs Ignored in Counter {#SCN-SECT-002-03}
- **Implements**: REQ-SECT-002
- **GIVEN**: The OTHERS section with entries `[{name: "kpt_001", ...}, {name: "kpt_005", ...}, {name: "oth-002", ...}]` (slug: `oth`)
- **WHEN**: `generate_keypoint_name(section_entries, "oth")` is called
- **THEN**: Returns `"oth-003"` (scans only `oth-NNN` pattern; `kpt_001` and `kpt_005` are ignored; max `oth-NNN` is 002)

### SCN-SECT-003-01: Format Playbook with Multiple Sections {#SCN-SECT-003-01}
- **Implements**: REQ-SECT-003
- **GIVEN**: A playbook with:
  - PATTERNS & APPROACHES: `[{name: "pat-001", text: "use type hints", helpful: 5, harmful: 1}]`
  - MISTAKES TO AVOID: `[]` (empty)
  - USER PREFERENCES: `[{name: "pref-001", text: "prefer pathlib", helpful: 2, harmful: 0}]`
  - PROJECT CONTEXT: `[]` (empty)
  - OTHERS: `[{name: "kpt_001", text: "legacy point", helpful: 0, harmful: 0}]`
- **WHEN**: `format_playbook(playbook)` is called
- **THEN**: The key points text block is:
  ```
  ## PATTERNS & APPROACHES
  [pat-001] helpful=5 harmful=1 :: use type hints

  ## USER PREFERENCES
  [pref-001] helpful=2 harmful=0 :: prefer pathlib

  ## OTHERS
  [kpt_001] helpful=0 harmful=0 :: legacy point
  ```
- **AND**: MISTAKES TO AVOID and PROJECT CONTEXT are omitted (empty sections)

### SCN-SECT-003-02: Format Empty Playbook Returns Empty String {#SCN-SECT-003-02}
- **Implements**: REQ-SECT-003
- **GIVEN**: A playbook where all sections are empty lists
- **WHEN**: `format_playbook(playbook)` is called
- **THEN**: Returns `""`

### SCN-SECT-003-03: Format Output Overhead Within 20% {#SCN-SECT-003-03}
- **Implements**: REQ-SECT-003, CON-SECT-004
- **GIVEN**: A synthetic playbook with 20 key points distributed across all 5 sections (4 per section)
- **WHEN**: `format_playbook(playbook)` is called and the output size is compared against a flat-list equivalent (same key points, no section headers)
- **THEN**: The sections-based output size does not exceed the flat-list output size by more than 20%

### SCN-SECT-004-01: LLM Returns Dict with Valid Section {#SCN-SECT-004-01}
- **Implements**: REQ-SECT-005
- **GIVEN**: An extraction result with `new_key_points: [{"text": "avoid globals", "section": "MISTAKES TO AVOID"}]`
- **WHEN**: `update_playbook_data()` processes the new key points
- **THEN**: The key point is added to the "MISTAKES TO AVOID" section with ID `mis-001` (or next available)

### SCN-SECT-004-02: LLM Returns Dict with Unknown Section {#SCN-SECT-004-02}
- **Implements**: REQ-SECT-005
- **GIVEN**: An extraction result with `new_key_points: [{"text": "some tip", "section": "RANDOM STUFF"}]`
- **WHEN**: `update_playbook_data()` processes the new key points
- **THEN**: The key point is added to the "OTHERS" section with ID `oth-NNN`
- **AND**: An OBS-SECT-002 diagnostic is emitted with the original section name `"RANDOM STUFF"`

### SCN-SECT-004-03: LLM Returns Plain String (Backward Compat) {#SCN-SECT-004-03}
- **Implements**: REQ-SECT-005
- **GIVEN**: An extraction result with `new_key_points: ["use structured logging"]`
- **WHEN**: `update_playbook_data()` processes the new key points
- **THEN**: The key point is treated as `{"text": "use structured logging", "section": "OTHERS"}` and added to the "OTHERS" section

### SCN-SECT-004-04: LLM Returns Dict with Case Mismatch or Whitespace {#SCN-SECT-004-04}
- **Implements**: REQ-SECT-005
- **GIVEN**: An extraction result with `new_key_points: [{"text": "use patterns", "section": "patterns & approaches"}, {"text": "another pattern", "section": "  patterns & approaches  "}]`
- **WHEN**: `update_playbook_data()` processes the new key points
- **THEN**: Both entries are matched (after stripping and case-insensitive comparison) to `"PATTERNS & APPROACHES"` and added there

### SCN-SECT-004-05: LLM Returns Dict Without Section Key or With Null/Empty Section {#SCN-SECT-004-05}
- **Implements**: REQ-SECT-005
- **GIVEN**: `extraction_result["new_key_points"] = [{"text": "Some insight"}, {"text": "Another", "section": None}, {"text": "Third", "section": ""}]`
- **WHEN**: `update_playbook_data()` processes the extraction result
- **THEN**:
  - All three entries are added to the "OTHERS" section with `oth-NNN` IDs
  - NO OBS-SECT-002 log is emitted (missing/null/empty section field is not an "unknown section name" event; OBS-SECT-002 is only for non-empty strings that don't match the canonical list)

### SCN-SECT-006-01: Migrate Flat Playbook with Mixed IDs {#SCN-SECT-006-01}
- **Implements**: REQ-SECT-006
- **GIVEN**: A `playbook.json`:
  ```json
  {
    "version": "1.0",
    "last_updated": "2026-01-15T10:00:00",
    "key_points": [
      {"name": "kpt_001", "text": "use types", "helpful": 5, "harmful": 1},
      {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0}
    ]
  }
  ```
- **WHEN**: `load_playbook()` is called
- **THEN**: The returned dict is:
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
        {"name": "kpt_002", "text": "prefer pathlib", "helpful": 0, "harmful": 0}
      ]
    }
  }
  ```
- **AND**: `kpt_001` and `kpt_002` IDs are preserved (not re-prefixed)

### SCN-SECT-006-02: Migrate Flat Playbook with Legacy Score Field {#SCN-SECT-006-02}
- **Implements**: REQ-SECT-006
- **GIVEN**: A `playbook.json` with old-format entries:
  ```json
  {
    "version": "1.0",
    "key_points": [
      "bare string entry",
      {"name": "kpt_002", "text": "some tip", "score": -3}
    ]
  }
  ```
- **WHEN**: `load_playbook()` is called
- **THEN**: The returned dict has all entries in OTHERS with scoring migration applied:
  ```json
  {
    "version": "1.0",
    "last_updated": null,
    "sections": {
      "PATTERNS & APPROACHES": [],
      "MISTAKES TO AVOID": [],
      "USER PREFERENCES": [],
      "PROJECT CONTEXT": [],
      "OTHERS": [
        {"name": "kpt_001", "text": "bare string entry", "helpful": 0, "harmful": 0},
        {"name": "kpt_002", "text": "some tip", "helpful": 0, "harmful": 3}
      ]
    }
  }
  ```
- **AND**: Both scoring migration (REQ-SCORE-004/005/006) and sections migration happen in one load (per REQ-SCORE-006: `helpful=max(score,0)=0`, `harmful=max(-score,0)=3` for `score=-3`)

### SCN-SECT-006-03: Load Already Sections-Based Playbook {#SCN-SECT-006-03}
- **Implements**: REQ-SECT-006
- **GIVEN**: A `playbook.json` that already has a `sections` key (new format)
- **WHEN**: `load_playbook()` is called
- **THEN**: The sections data is returned as-is (no migration needed)
- **AND**: No OBS-SECT-001 migration diagnostic is emitted

### SCN-SECT-006-04: Dual-Key File Handling {#SCN-SECT-006-04}
- **Implements**: REQ-SECT-007
- **GIVEN**: A `playbook.json` with both `sections` and `key_points` keys
- **WHEN**: `load_playbook()` is called
- **THEN**: `sections` is used; `key_points` is ignored
- **AND**: A diagnostic warning is logged (if diagnostic mode is active)
- **AND**: The returned dict does NOT contain a `key_points` key

### SCN-SECT-008-01: Evaluation Finds Key Point Across Sections {#SCN-SECT-008-01}
- **Implements**: REQ-SECT-008
- **GIVEN**: A playbook with:
  - PATTERNS & APPROACHES: `[{name: "pat-001", text: "use types", helpful: 3, harmful: 1}]`
  - OTHERS: `[{name: "kpt_001", text: "legacy tip", helpful: 0, harmful: 0}]`
- **AND**: An extraction result with evaluations `[{name: "pat-001", rating: "helpful"}, {name: "kpt_001", rating: "harmful"}]`
- **WHEN**: `update_playbook_data()` is called
- **THEN**: `pat-001.helpful == 4` (in PATTERNS & APPROACHES) and `kpt_001.harmful == 1` (in OTHERS)

### SCN-SECT-008-02: Pruning Removes Entry from Correct Section {#SCN-SECT-008-02}
- **Implements**: REQ-SECT-008
- **GIVEN**: A playbook with:
  - MISTAKES TO AVOID: `[{name: "mis-001", text: "bad advice", helpful: 1, harmful: 4}]`
  - OTHERS: `[{name: "kpt_001", text: "good tip", helpful: 5, harmful: 0}]`
- **WHEN**: `update_playbook_data()` applies the pruning step
- **THEN**: `mis-001` is removed from MISTAKES TO AVOID (harmful >= 3 AND harmful > helpful)
- **AND**: `kpt_001` is retained in OTHERS

### SCN-SECT-009-01: Extract Flat Dict from Sections {#SCN-SECT-009-01}
- **Implements**: REQ-SECT-009
- **GIVEN**: A playbook with:
  - PATTERNS & APPROACHES: `[{name: "pat-001", text: "use types", helpful: 5, harmful: 1}]`
  - OTHERS: `[{name: "kpt_001", text: "legacy tip", helpful: 0, harmful: 0}]`
- **WHEN**: `extract_keypoints()` builds the `playbook_dict`
- **THEN**: The dict is `{"pat-001": "use types", "kpt_001": "legacy tip"}`
- **AND**: Section names are NOT keys in the dict

---

## Invariants

### INV-SECT-001: Sections Key Always Present After Write {#INV-SECT-001}
- **Implements**: SC-SECT-001, FM-SECT-008
- **Statement**: After any call to `save_playbook()`, the written `playbook.json` file MUST contain a `sections` key. The `save_playbook()` function asserts the presence of `sections` in the playbook dict before writing; if absent, it raises an `AssertionError`.
- **Enforced by**: `save_playbook()` contains `assert "sections" in playbook`, which prevents any code path from accidentally writing a flat-format file.

### INV-SECT-002: Section Names from Canonical Set {#INV-SECT-002}
- **Implements**: SC-SECT-001
- **Statement**: Every key in the `sections` dict (both in memory and on disk) is a member of the canonical set: `{"PATTERNS & APPROACHES", "MISTAKES TO AVOID", "USER PREFERENCES", "PROJECT CONTEXT", "OTHERS"}`.
- **Enforced by**: `load_playbook()` initializes all sections from the canonical set during migration; `update_playbook_data()` resolves section names against the canonical set (with fallback to OTHERS); no code path creates arbitrary section names.

### INV-SECT-003: Counter Non-Negativity (Carried Forward) {#INV-SECT-003}
- **Implements**: SC-SECT-001 (key point schema unchanged)
- **Statement**: For every key point entry in any section, `helpful >= 0` and `harmful >= 0` at all times.
- **Enforced by**: INV-SCORE-001 and INV-SCORE-002 mechanisms are unchanged. Migration formulas use `max(value, 0)`; new entries initialize to `0`; increments are always `+1`; no decrement operation exists.

### INV-SECT-004: Legacy IDs Preserved During Migration {#INV-SECT-004}
- **Implements**: SC-SECT-005
- **Statement**: When `load_playbook()` migrates a flat-format playbook to sections, every existing key point's `name` field is preserved unchanged. No ID is re-prefixed during migration.
- **Enforced by**: The migration code copies entries into the OTHERS section without modifying the `name` field.

### INV-SECT-005: Section-Slug ID Prefix Consistency {#INV-SECT-005}
- **Implements**: SC-SECT-002, SC-SECT-005
- **Statement**: Every newly generated key point name in a section uses the slug prefix from `SECTION_SLUGS[section_name]`. Within the OTHERS section, legacy `kpt_NNN` names may coexist with `oth-NNN` names; the ID generator scans only for the section's slug prefix pattern.
- **Enforced by**: `generate_keypoint_name(section_entries, slug)` regex matches only `^{slug}-(\d+)$`; `update_playbook_data()` always passes the correct slug from `SECTION_SLUGS`.

### INV-SECT-006: Migration Round-Trip Stability {#INV-SECT-006}
- **Implements**: SC-SECT-005
- **Statement**: If a playbook file is loaded via `load_playbook()`, immediately saved via `save_playbook()`, and loaded again, the in-memory representation is identical between the first and second load for: (1) the `sections` dict (all entries in canonical schema), and (2) the `version` field. Only `last_updated` changes on save.
- **Enforced by**: After migration, all entries are in canonical `{name, text, helpful, harmful}` schema within their sections. A second load finds the `sections` key present and performs no migration. The `version` field is read from disk and written back unchanged.

### INV-SECT-007: No key_points Key in Output {#INV-SECT-007}
- **Implements**: SC-SECT-001, FM-SECT-008
- **Statement**: After `load_playbook()` returns, the returned dict does NOT contain a `key_points` key. After `save_playbook()` writes, the JSON file does NOT contain a `key_points` key.
- **Enforced by**: `load_playbook()` migration builds the `sections` structure and does not set `key_points`. For dual-key files, `key_points` is explicitly deleted from the dict. `save_playbook()` asserts `"sections" in playbook` and strips any `key_points` key from the dict before writing (`playbook.pop("key_points", None)`).

---

## Pruning Contract (Carried Forward from Scoring)

The pruning rule is unchanged. See `docs/scoring/spec.md` REQ-SCORE-007 for the canonical definition. The only change is that pruning now iterates over all sections (REQ-SECT-008) instead of a single flat list.

### Decision Table (unchanged)

| `helpful` | `harmful` | `harmful >= 3` | `harmful > helpful` | **Pruned?** |
|-----------|-----------|-----------------|---------------------|-------------|
| 0 | 0 | False | False | **No** (zero evaluations) |
| 0 | 2 | False | True | **No** (below floor) |
| 0 | 3 | True | True | **Yes** |
| 1 | 4 | True | True | **Yes** |
| 10 | 4 | True | False | **No** (majority helpful) |
| 3 | 3 | True | False | **No** (equal) |
