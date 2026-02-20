# Requirements Specification: Curator Operations Module

## Intent Traceability

This section preserves the success criteria from the approved intent.
The full intent document is in `.planning/intent.md` for historical reference.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* |
|------|-------------------|-------------------|
| SC-CUR-001 | `extract_keypoints()` returns a structured response containing an `operations` list in addition to the existing `evaluations` field. Each operation is a dict with a `type` field (one of "ADD", "UPDATE", "MERGE", "DELETE"). The `evaluations` field continues to exist for tagging existing bullets. | REQ-CUR-001, SCN-CUR-001-01, SCN-CUR-001-02, SCN-CUR-001-03, SCN-CUR-001-04 |
| SC-CUR-002 | ADD operation creates a new key point. Fields: `{"type": "ADD", "text": "...", "section": "..."}`. The `section` field is optional (defaults to "OTHERS"). `update_playbook_data()` handles ADD by generating a new ID and appending to the target section. ADD deduplicates against existing playbook texts. | REQ-CUR-002, SCN-CUR-002-01, SCN-CUR-002-02, SCN-CUR-002-03, SCN-CUR-002-04, SCN-CUR-002-05 |
| SC-CUR-003 | MERGE operation combines two or more existing key points into one. Fields: `{"type": "MERGE", "source_ids": [...], "merged_text": "...", "section": "..."}`. Section defaults to section of first valid source_id. Counter summing. Source removal. | REQ-CUR-003, SCN-CUR-003-01, SCN-CUR-003-02, SCN-CUR-003-03, SCN-CUR-003-04, SCN-CUR-003-05, SCN-CUR-003-06, SCN-CUR-003-07, SCN-CUR-003-08 |
| SC-CUR-004 | DELETE operation removes an existing key point. Fields: `{"type": "DELETE", "target_id": "...", "reason": "..."}`. Reason logged via OBS-CUR-003 but not stored. | REQ-CUR-004, SCN-CUR-004-01, SCN-CUR-004-02, SCN-CUR-004-03 |
| SC-CUR-005 | Operations processed sequentially in list order. Deep copy atomicity. Exception rollback. Skip-invalid is a no-op, not an exception. | REQ-CUR-005, REQ-CUR-006, INV-CUR-001, INV-CUR-002, SCN-CUR-005-01, SCN-CUR-005-02, SCN-CUR-005-03, SCN-CUR-005-04 |
| SC-CUR-006 | The LLM prompt instructs the LLM to return a combined JSON response containing BOTH `evaluations` AND `operations`. The prompt provides entry IDs. Includes examples of each operation type. | REQ-CUR-007, SCN-CUR-007-01 |
| SC-CUR-007 | Precedence rule: if `operations` key present, use it exclusively (ignore `new_key_points`). If absent, fall back to `new_key_points` treating each as ADD. | REQ-CUR-008, SCN-CUR-008-01, SCN-CUR-008-02, SCN-CUR-008-03 |
| SC-CUR-008 | **Separate Curator Role** (implements SC-ACE-004) -- `run_curator(reflector_output, playbook)` is a dedicated async LLM call that receives the reflector's analysis and the current playbook, then produces structured operations. The curator does NOT re-analyze the transcript -- it works solely from the reflector's output. On failure (API error, unparseable JSON), returns `{"reasoning": "", "operations": []}`. Uses the same retry logic as `extract_keypoints()`. Loads `curator.txt` prompt template. | REQ-CUR-010, REQ-CUR-011, REQ-CUR-012, REQ-CUR-016, SCN-CUR-010-01, SCN-CUR-010-02, SCN-CUR-010-03, SCN-CUR-011-01, SCN-CUR-012-01, SCN-CUR-016-01, SCN-CUR-016-02, INV-CUR-008 |
| SC-CUR-009 | **UPDATE Operation** (implements SC-ACE-005) -- `{"type": "UPDATE", "target_id": "...", "text": "..."}` revises the text of an existing key point. The entry's `name` (ID) and `helpful`/`harmful` counters are preserved. If `target_id` does not exist, the UPDATE is skipped and logged. | REQ-CUR-013, SCN-CUR-013-01, SCN-CUR-013-02, SCN-CUR-013-03, SCN-CUR-013-04, INV-CUR-009 |
| SC-CUR-010 | **apply_structured_operations()** (implements SC-ACE-005) -- A public wrapper function that applies structured curator operations to the playbook. Reuses the existing `_apply_curator_operations()` logic plus UPDATE support. Includes deep copy isolation and rollback on exception. Signature: `apply_structured_operations(playbook: dict, operations: list[dict]) -> dict`. | REQ-CUR-014, SCN-CUR-014-01, SCN-CUR-014-02, SCN-CUR-014-03, SCN-CUR-014-04, INV-CUR-010 |
| SC-CUR-011 | **prune_harmful()** (implements SC-ACE-005) -- Standalone function extracted from `update_playbook_data()`. Removes key points where `harmful >= 3 AND harmful > helpful`. Zero-evaluation entries (helpful=0, harmful=0) are NEVER pruned (INV-SCORE-003). Thresholds identical to current implementation. | REQ-CUR-015, SCN-CUR-015-01, SCN-CUR-015-02, SCN-CUR-015-03, SCN-CUR-015-04, INV-CUR-011 |

**SC-ACE-* to SC-CUR-* Mapping:**
- SC-ACE-004 (Separate Curator Role) is implemented by SC-CUR-008
- SC-ACE-005 (Structured Playbook Operations -- UPDATE, function extraction, prune extraction) is implemented by SC-CUR-009, SC-CUR-010, SC-CUR-011

---

## Requirements

### REQ-CUR-001: Structured Operations in Extraction Result {#REQ-CUR-001}
- **Implements**: SC-CUR-001
- **GIVEN**: An LLM response parsed by `extract_keypoints()`
- **WHEN**: The response JSON contains an `operations` key
- **THEN**:
  - The returned dict includes an `operations` field (`list[dict]`)
  - Each operation dict has at minimum a `type` field (`str`) with value `"ADD"`, `"UPDATE"`, `"MERGE"`, or `"DELETE"`
  - The `evaluations` field continues to be returned (unchanged from prior behavior)
  - If the LLM response does not contain an `operations` key, the returned dict does NOT include an `operations` key (the key is absent, not set to empty list). This is critical for the precedence rule in REQ-CUR-008.
  - If the LLM response contains an `operations` key but its value is NOT a list (e.g., `null`, a string, an integer), treat it as if the `operations` key were absent (do not include `operations` in the extraction result). This prevents a crash in `_apply_curator_operations()` which expects `list[dict]`. See SCN-CUR-001-04. [Resolves SPEC_CHALLENGE Q1]

### REQ-CUR-002: ADD Operation {#REQ-CUR-002}
- **Implements**: SC-CUR-002
- **GIVEN**: An operation `{"type": "ADD", "text": "...", "section": "..."}`
- **WHEN**: `_apply_curator_operations()` processes this operation
- **THEN**:
  - A new entry is created with schema `{"name": <generated>, "text": <text>, "helpful": 0, "harmful": 0}`
  - The entry is appended to the target section resolved from the `section` field (case-insensitive, fallback to `"OTHERS"` if missing/invalid)
  - The `name` is generated via `generate_keypoint_name(target_entries, slug)` using the target section's slug from `SECTION_SLUGS`
  - Before adding, the text is checked against all existing texts across all sections; if a duplicate exists, the ADD is skipped (no-op with diagnostic log)
  - If `text` is empty or missing, the ADD is skipped (validation failure per QG-CUR-001)

### REQ-CUR-003: MERGE Operation {#REQ-CUR-003}
- **Implements**: SC-CUR-003
- **GIVEN**: An operation `{"type": "MERGE", "source_ids": ["id1", "id2", ...], "merged_text": "...", "section": "..."}`
- **WHEN**: `_apply_curator_operations()` processes this operation
- **THEN**:
  - **Validation (QG-CUR-001)**: If `source_ids` has fewer than 2 entries, the MERGE is skipped entirely (validation failure). If `merged_text` is empty or missing, the MERGE is skipped entirely.
  - **Source ID filtering**: Source IDs that do not exist in the current playbook state are filtered out (logged via OBS-CUR-002). If fewer than 2 valid source IDs remain after filtering, the MERGE is skipped entirely.
  - **Section resolution**: If `section` is provided and valid, the merged entry is placed there. If `section` is absent/empty/invalid, the merged entry is placed in the section of the first valid source_id (i.e., the first source_id in the `source_ids` list that still exists in the playbook).
  - **Counter summing**: The new entry's `helpful` counter is the sum of `helpful` from all valid source entries. The new entry's `harmful` counter is the sum of `harmful` from all valid source entries.
  - **New entry creation**: A new entry `{"name": <generated>, "text": <merged_text>, "helpful": <summed>, "harmful": <summed>}` is appended to the resolved target section. The `name` is generated via `generate_keypoint_name()` using the target section's slug.
  - **Source removal**: All valid source entries are removed from their respective sections.

### REQ-CUR-004: DELETE Operation {#REQ-CUR-004}
- **Implements**: SC-CUR-004
- **GIVEN**: An operation `{"type": "DELETE", "target_id": "...", "reason": "..."}`
- **WHEN**: `_apply_curator_operations()` processes this operation
- **THEN**:
  - If `target_id` is empty or missing, the DELETE is skipped (validation failure per QG-CUR-001)
  - If `target_id` does not exist in the current playbook state, the DELETE is skipped (logged via OBS-CUR-002)
  - If `target_id` exists, the entry is removed from its section
  - The `reason` field is logged via OBS-CUR-003 diagnostics (along with `target_id` and the deleted entry's text truncated to 80 chars)
  - The `reason` field is NOT stored in the playbook

### REQ-CUR-005: Sequential Processing Order {#REQ-CUR-005}
- **Implements**: SC-CUR-005
- **GIVEN**: An `operations` list with N operations
- **WHEN**: `_apply_curator_operations()` processes the list
- **THEN**:
  - Operations are applied in list index order (0, 1, 2, ..., N-1)
  - Each operation sees the playbook state left by all preceding operations (e.g., a MERGE after a DELETE will not find the deleted entry)
  - A skipped operation (validation failure, non-existent ID) does not affect the playbook state; subsequent operations proceed normally

### REQ-CUR-006: Deep Copy Atomicity and Exception Rollback {#REQ-CUR-006}
- **Implements**: SC-CUR-005, CON-CUR-005
- **GIVEN**: `update_playbook_data()` is called with a playbook and an extraction result containing `operations`
- **WHEN**: Operations processing begins
- **THEN**:
  - A `copy.deepcopy()` of the playbook is created before any operations are applied. **Clarification**: the deep copy is only created when the (validated) operations list is non-empty (`isinstance(operations, list) and operations`). When `operations` is present but empty (`[]`), no deep copy is created -- an empty list is a no-op that requires no deep copy. [Resolves SPEC_CHALLENGE Q2]
  - All operations are applied to the deep copy, not the original
  - If all operations complete (including skipped ones -- skipping is not an error), the modified copy is returned
  - If an uncaught exception occurs during processing, the original unmodified playbook is returned (rollback)
  - Skipping an invalid operation (non-existent ID, validation failure) is NOT an exception -- it is a normal no-op
- **Atomicity scope note**: Atomicity covers ONLY the operations processing path (the `_apply_curator_operations()` call wrapped in try/except). The evaluations counter update and pruning logic that run after operations are NOT wrapped in the same try/except. If evaluations or pruning raise an exception, the caller sees an unhandled exception (not a silent rollback). This is acceptable because evaluations/pruning failures are programming errors, not expected runtime conditions. [Resolves SPEC_CHALLENGE Q8]

### REQ-CUR-007: Updated Prompt Structure {#REQ-CUR-007}
- **Implements**: SC-CUR-006
- **GIVEN**: The `reflection.txt` template used by `extract_keypoints()`
- **WHEN**: The template is loaded and used to construct the LLM prompt
- **THEN**:
  - The prompt instructs the LLM to return a combined JSON response with both `evaluations` and `operations` keys
  - The prompt provides the current playbook entries with their IDs (names) so the LLM can reference them in MERGE `source_ids` and DELETE `target_id`
  - The prompt includes at least one example of each operation type (ADD, MERGE, DELETE)
  - The prompt explicitly tells the LLM it may return zero operations if no changes are needed
  - The prompt instructs a maximum of 10 operations (CON-CUR-004)

### REQ-CUR-008: Operations vs new_key_points Precedence {#REQ-CUR-008}
- **Implements**: SC-CUR-007, CON-CUR-001
- **GIVEN**: An extraction result dict returned by `extract_keypoints()`
- **WHEN**: `update_playbook_data()` determines how to process playbook changes
- **THEN**:
  - If the extraction result contains an `operations` key (even if the list is empty), the operations path is used exclusively; `new_key_points` is ignored even if present
  - If the extraction result does NOT contain an `operations` key, fall back to `new_key_points` and treat each entry as an ADD operation (existing behavior per CON-CUR-001)
  - This prevents double-processing where both `operations` and `new_key_points` would add entries

### REQ-CUR-009: Operations Validation and Truncation {#REQ-CUR-009}
- **Implements**: QG-CUR-001, CON-CUR-004
- **GIVEN**: An `operations` list from the LLM response
- **WHEN**: `_apply_curator_operations()` begins processing
- **THEN**:
  - If the list has more than 10 entries, it is truncated to the first 10 (with a diagnostic log via OBS-CUR-001 noting truncation)
  - Each operation is validated before application:
    - ADD: requires non-empty `text` (`str`); missing/empty `text` causes skip
    - UPDATE: requires non-empty `target_id` (`str`) and non-empty `text` (`str`); missing/empty causes skip (Phase 1 addition via REQ-CUR-013)
    - MERGE: requires `source_ids` (`list[str]`) with `len >= 2` and non-empty `merged_text` (`str`); violations cause skip
    - DELETE: requires non-empty `target_id` (`str`); missing/empty causes skip
    - Unknown `type` value: operation is skipped with diagnostic log
  - Invalid operations are skipped (no-op), not raised as exceptions

### REQ-CUR-010: Curator LLM Call {#REQ-CUR-010}
- **Implements**: SC-CUR-008
- **GIVEN**: A reflector output dict and a playbook dict
  - The `reflector_output` dict matches the schema defined in REQ-REFL-004:
    `{"analysis": str, "bullet_tags": list[{"name": str, "tag": "helpful"|"harmful"|"neutral", "rationale": str}]}`
    (Cross-reference: see `docs/reflector/spec.md` REQ-REFL-004)
  - If `reflector_output` keys are missing (e.g., due to a reflector fallback returning empty dict), the function uses `reflector_output.get("analysis", "")` and `reflector_output.get("bullet_tags", [])` with defaults
- **WHEN**: `run_curator(reflector_output, playbook)` is called
- **THEN**:
  - The function loads the `curator.txt` prompt template via `load_template("curator.txt")`
  - The function formats the playbook into prompt-friendly text via `format_playbook(playbook)` internally
  - The function constructs an LLM prompt containing: the reflector's full JSON output and the formatted playbook
  - The function does NOT receive or use the raw transcript -- it works solely from the reflector's output (separation of concerns: reflector diagnoses, curator decides)
  - The function makes an async Anthropic API call with the same model, API key, and client configuration as `extract_keypoints()`
  - The function uses the same retry logic (MAX_RETRIES=3, BASE_DELAY=2.0s, exponential backoff with jitter) as `extract_keypoints()`
  - The function parses the LLM response JSON to extract `reasoning` (string) and `operations` (list of dicts)
  - The function returns a dict matching the curator output schema: `{"reasoning": str, "operations": list[dict]}`

### REQ-CUR-011: Curator Output Schema {#REQ-CUR-011}
- **Implements**: SC-CUR-008
- **GIVEN**: A successful curator LLM call that returns parseable JSON
- **WHEN**: The response is parsed
- **THEN**:
  - The returned dict contains `"reasoning"` (string): curator's chain of thought explaining its decisions
  - The returned dict contains `"operations"` (list of dicts): structured operations (ADD, UPDATE, DELETE, MERGE)
  - Each operation follows the same schema as existing operations (REQ-CUR-002 through REQ-CUR-004, plus REQ-CUR-013 for UPDATE)
  - The operations use the field names established in the existing codebase: `target_id` (DELETE, UPDATE), `source_ids` (MERGE), `merged_text` (MERGE), `text` (ADD, UPDATE), `section` (ADD, MERGE), `reason` (DELETE)
  - The operations list may be empty (curator decides no changes are needed)

### REQ-CUR-012: Curator Error Handling {#REQ-CUR-012}
- **Implements**: SC-CUR-008
- **GIVEN**: `run_curator()` encounters a failure
- **WHEN**: The failure is an API error (timeout, connection, rate limit, 5xx, 4xx), an unparseable JSON response, or any other exception
- **THEN**:
  - The function returns the empty result: `{"reasoning": "", "operations": []}`
  - The function does NOT raise an exception to the caller
  - In diagnostic mode, the error is logged via `save_diagnostic()`
  - The session-end flow continues with no operations (graceful degradation: playbook unchanged by curator for this session)

### REQ-CUR-013: UPDATE Operation {#REQ-CUR-013}
- **Implements**: SC-CUR-009
- **GIVEN**: An operation `{"type": "UPDATE", "target_id": "...", "text": "..."}`
- **WHEN**: `_apply_curator_operations()` (or `apply_structured_operations()`) processes this operation
- **THEN**:
  - **Validation**: If `target_id` is empty or missing, the UPDATE is skipped (validation failure)
  - **Validation**: If `text` is empty or missing, the UPDATE is skipped (validation failure)
  - If `target_id` does not exist in the current playbook state, the UPDATE is skipped (logged to stderr and via OBS-CUR-002 diagnostics)
  - If `target_id` exists, the entry's `text` field is replaced with the new `text` value
  - The entry's `name` (ID) is preserved unchanged
  - The entry's `helpful` and `harmful` counters are preserved unchanged
  - The entry remains in its current section (UPDATE does not move entries between sections)
  - The operation is logged via OBS-CUR-004 diagnostics (target_id, old text truncated to 80 chars, new text truncated to 80 chars)

### REQ-CUR-014: Public apply_structured_operations() Function {#REQ-CUR-014}
- **Implements**: SC-CUR-010
- **GIVEN**: A playbook dict and an operations list
- **WHEN**: `apply_structured_operations(playbook, operations)` is called
- **THEN**:
  - The function creates a `copy.deepcopy()` of the playbook before any operations are applied (same atomicity as the operations path in `update_playbook_data()`)
  - The function applies operations to the deep copy using the same logic as `_apply_curator_operations()`, with the addition of UPDATE support (REQ-CUR-013)
  - Operations are processed in list order (REQ-CUR-005)
  - Operations are truncated to 10 maximum (CON-CUR-004, INV-CUR-005)
  - Invalid operations are skipped (INV-CUR-002)
  - If all operations complete successfully, the modified copy is returned
  - If an uncaught exception occurs during processing, the original unmodified playbook is returned (rollback, INV-CUR-001)
  - Supported operation types: ADD, UPDATE, DELETE, MERGE (UPDATE is NEW; the other three are existing)
  - **Empty operations list**: If `operations` is an empty list `[]`, the function returns the original playbook dict UNMODIFIED (no deep copy, no mutations). This matches the behavior established in REQ-CUR-006 for `update_playbook_data()`. An empty operations list is a no-op with zero overhead.
  - This function is publicly callable (not prefixed with `_`) and is the intended interface for the session-end flow after Phase 1

### REQ-CUR-015: Standalone prune_harmful() Function {#REQ-CUR-015}
- **Implements**: SC-CUR-011
- **GIVEN**: A playbook dict with key points distributed across sections
- **WHEN**: `prune_harmful(playbook)` is called
- **THEN**:
  - The function iterates ALL sections in the playbook
  - A key point is pruned if BOTH conditions hold:
    - `harmful >= 3`
    - `harmful > helpful`
  - Zero-evaluation entries (`helpful == 0` AND `harmful == 0`) are NEVER pruned (INV-SCORE-003)
  - Pruned entries are removed from their respective sections
  - Pruned entries are logged to stderr with name, text preview (truncated to 80 chars), and counters
  - In diagnostic mode, a detailed prune report is saved via `save_diagnostic()`
  - The pruning thresholds and logic are identical to the existing pruning code in `update_playbook_data()` (lines 641-667 of current `common.py`)
  - Returns the modified playbook dict

### REQ-CUR-016: Robust JSON Extraction from LLM Response {#REQ-CUR-016}
- **Implements**: SC-CUR-008 (JSON Parsing Robustness, see `.planning/intent.md`)
- **GIVEN**: The LLM response from the curator call is a text string that may contain JSON embedded in prose, code fences, or be raw JSON
- **WHEN**: `run_curator()` parses the response
- **THEN**:
  - The function attempts JSON extraction in this order:
    1. Look for ` ```json...``` ` code fence; extract content between fences
    2. Look for ` ```...``` ` code fence (no language tag); extract content
    3. Use balanced-brace counting: find the outermost `{` and scan forward counting braces, stopping at the matching `}`. Extract that substring.
    4. Attempt `json.loads()` on the full response text (raw parse)
  - The FIRST strategy that produces valid JSON (parseable by `json.loads()`) is used
  - If no strategy succeeds, `run_curator()` returns the fallback result `{"reasoning": "", "operations": []}` (per REQ-CUR-012)
  - If a strategy produces valid JSON but the result does not have `reasoning` or `operations` keys, the function uses `.get()` with defaults (empty string, empty list) -- the partial result is accepted, not rejected

---

## Scenarios

### SCN-CUR-001-01: extract_keypoints Returns Operations {#SCN-CUR-001-01}
- **Implements**: REQ-CUR-001
- **GIVEN**: An LLM response JSON:
  ```json
  {
    "evaluations": [{"name": "pat-001", "rating": "helpful"}],
    "operations": [{"type": "ADD", "text": "new insight", "section": "PATTERNS & APPROACHES"}]
  }
  ```
- **WHEN**: `extract_keypoints()` parses the response
- **THEN**: The returned dict contains:
  - `evaluations`: `[{"name": "pat-001", "rating": "helpful"}]`
  - `operations`: `[{"type": "ADD", "text": "new insight", "section": "PATTERNS & APPROACHES"}]`

### SCN-CUR-001-02: extract_keypoints Returns Empty Operations {#SCN-CUR-001-02}
- **Implements**: REQ-CUR-001
- **GIVEN**: An LLM response JSON:
  ```json
  {
    "evaluations": [{"name": "pat-001", "rating": "helpful"}],
    "operations": []
  }
  ```
- **WHEN**: `extract_keypoints()` parses the response
- **THEN**: The returned dict contains:
  - `evaluations`: `[{"name": "pat-001", "rating": "helpful"}]`
  - `operations`: `[]`

### SCN-CUR-001-03: extract_keypoints with No Operations Key {#SCN-CUR-001-03}
- **Implements**: REQ-CUR-001
- **GIVEN**: An LLM response JSON (old format):
  ```json
  {
    "new_key_points": ["some new point"],
    "evaluations": [{"name": "pat-001", "rating": "helpful"}]
  }
  ```
- **WHEN**: `extract_keypoints()` parses the response
- **THEN**: The returned dict contains:
  - `new_key_points`: `["some new point"]`
  - `evaluations`: `[{"name": "pat-001", "rating": "helpful"}]`
  - `operations` key is absent (backward compatibility -- old-format response)

### SCN-CUR-001-04: extract_keypoints with Non-List Operations Value {#SCN-CUR-001-04}
- **Implements**: REQ-CUR-001
- **GIVEN**: An LLM response JSON where `operations` is present but is NOT a list (e.g., `null`, a string, an integer):
  ```json
  {
    "evaluations": [{"name": "pat-001", "rating": "helpful"}],
    "operations": null
  }
  ```
- **WHEN**: `extract_keypoints()` parses the response
- **THEN**: The returned dict treats the non-list `operations` value as if the `operations` key were absent -- the `operations` key is NOT included in the extraction result. This causes `update_playbook_data()` to fall back to the `new_key_points` path (REQ-CUR-008), preventing a crash in `_apply_curator_operations()` which expects a `list[dict]`.
- **NOTE**: This applies to any non-list value: `null`, `"string"`, `42`, `{}`, `true`. The guard is `isinstance(operations, list)`. [Resolves SPEC_CHALLENGE Q1]

### SCN-CUR-002-01: ADD Creates New Entry in Target Section {#SCN-CUR-002-01}
- **Implements**: REQ-CUR-002
- **GIVEN**: A playbook with PATTERNS & APPROACHES section containing `[{name: "pat-001", text: "use types", helpful: 5, harmful: 1}]`
- **AND**: An operation `{"type": "ADD", "text": "prefer composition", "section": "PATTERNS & APPROACHES"}`
- **WHEN**: The operation is applied
- **THEN**: PATTERNS & APPROACHES section now contains:
  - `{name: "pat-001", text: "use types", helpful: 5, harmful: 1}`
  - `{name: "pat-002", text: "prefer composition", helpful: 0, harmful: 0}`

### SCN-CUR-002-02: ADD Defaults to OTHERS When Section Missing {#SCN-CUR-002-02}
- **Implements**: REQ-CUR-002
- **GIVEN**: An operation `{"type": "ADD", "text": "some insight"}`  (no `section` field)
- **WHEN**: The operation is applied
- **THEN**: The entry is added to the OTHERS section with an `oth-NNN` ID

### SCN-CUR-002-03: ADD Skips Duplicate Text {#SCN-CUR-002-03}
- **Implements**: REQ-CUR-002
- **GIVEN**: A playbook with OTHERS containing `[{name: "oth-001", text: "prefer pathlib", helpful: 2, harmful: 0}]`
- **AND**: An operation `{"type": "ADD", "text": "prefer pathlib", "section": "PATTERNS & APPROACHES"}`
- **WHEN**: The operation is applied
- **THEN**: The operation is skipped (duplicate text exists in OTHERS section); no new entry is created in any section

### SCN-CUR-002-04: ADD Skips Empty Text {#SCN-CUR-002-04}
- **Implements**: REQ-CUR-002, REQ-CUR-009
- **GIVEN**: An operation `{"type": "ADD", "text": "", "section": "OTHERS"}`
- **WHEN**: The operation is validated
- **THEN**: The operation is skipped (validation failure: empty text)

### SCN-CUR-002-05: ADD Resolves Section Case-Insensitively {#SCN-CUR-002-05}
- **Implements**: REQ-CUR-002
- **GIVEN**: An operation `{"type": "ADD", "text": "new tip", "section": "mistakes to avoid"}`
- **WHEN**: The operation is applied
- **THEN**: The entry is added to "MISTAKES TO AVOID" section with a `mis-NNN` ID

### SCN-CUR-003-01: MERGE Combines Two Entries {#SCN-CUR-003-01}
- **Implements**: REQ-CUR-003
- **GIVEN**: A playbook with:
  - PATTERNS & APPROACHES: `[{name: "pat-001", text: "use type hints", helpful: 5, harmful: 1}, {name: "pat-003", text: "annotate return types", helpful: 3, harmful: 0}]`
- **AND**: An operation `{"type": "MERGE", "source_ids": ["pat-001", "pat-003"], "merged_text": "use complete type annotations"}`
- **WHEN**: The operation is applied
- **THEN**:
  - `pat-001` and `pat-003` are removed from PATTERNS & APPROACHES
  - A new entry `{name: "pat-004", text: "use complete type annotations", helpful: 8, harmful: 1}` is added to PATTERNS & APPROACHES (section of first valid source_id)
  - `helpful = 5 + 3 = 8`, `harmful = 1 + 0 = 1`

### SCN-CUR-003-02: MERGE with Explicit Section Override {#SCN-CUR-003-02}
- **Implements**: REQ-CUR-003
- **GIVEN**: A playbook with:
  - PATTERNS & APPROACHES: `[{name: "pat-001", text: "hint A", helpful: 2, harmful: 0}]`
  - OTHERS: `[{name: "oth-001", text: "hint B", helpful: 1, harmful: 0}]`
- **AND**: An operation `{"type": "MERGE", "source_ids": ["pat-001", "oth-001"], "merged_text": "combined hint", "section": "PATTERNS & APPROACHES"}`
- **WHEN**: The operation is applied
- **THEN**:
  - `pat-001` removed from PATTERNS & APPROACHES, `oth-001` removed from OTHERS
  - New entry `{name: "pat-002", text: "combined hint", helpful: 3, harmful: 0}` in PATTERNS & APPROACHES
  - `helpful = 2 + 1 = 3`, `harmful = 0 + 0 = 0`

### SCN-CUR-003-03: MERGE with Some Non-Existent Source IDs {#SCN-CUR-003-03}
- **Implements**: REQ-CUR-003, CON-CUR-003
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "A", helpful: 2, harmful: 0}, {name: "pat-002", text: "B", helpful: 1, harmful: 0}]`
- **AND**: An operation `{"type": "MERGE", "source_ids": ["pat-001", "pat-002", "pat-999"], "merged_text": "combined"}`
- **WHEN**: The operation is applied
- **THEN**:
  - `pat-999` is logged as non-existent (OBS-CUR-002) and filtered out
  - 2 valid source IDs remain (>= 2), so MERGE proceeds
  - `pat-001` and `pat-002` removed; new entry with summed counters added

### SCN-CUR-003-04: MERGE Skipped When Fewer Than 2 Valid Source IDs {#SCN-CUR-003-04}
- **Implements**: REQ-CUR-003, CON-CUR-003
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "A", helpful: 2, harmful: 0}]`
- **AND**: An operation `{"type": "MERGE", "source_ids": ["pat-001", "pat-999"], "merged_text": "combined"}`
- **WHEN**: The operation is applied
- **THEN**:
  - `pat-999` is filtered out (non-existent); only 1 valid source ID remains
  - MERGE is skipped entirely (fewer than 2 valid source_ids)
  - `pat-001` is NOT removed (MERGE did not proceed)

### SCN-CUR-003-05: MERGE Skipped When source_ids Has Fewer Than 2 Entries {#SCN-CUR-003-05}
- **Implements**: REQ-CUR-003, REQ-CUR-009
- **GIVEN**: An operation `{"type": "MERGE", "source_ids": ["pat-001"], "merged_text": "rewritten"}`
- **WHEN**: The operation is validated
- **THEN**: The MERGE is skipped (validation failure: `source_ids` has fewer than 2 entries)

### SCN-CUR-003-06: MERGE Inherits Section from First Valid Source ID {#SCN-CUR-003-06}
- **Implements**: REQ-CUR-003
- **GIVEN**: A playbook with:
  - MISTAKES TO AVOID: `[{name: "mis-001", text: "avoid globals", helpful: 3, harmful: 0}]`
  - OTHERS: `[{name: "oth-001", text: "no bare except", helpful: 1, harmful: 0}]`
- **AND**: An operation `{"type": "MERGE", "source_ids": ["mis-001", "oth-001"], "merged_text": "combined advice"}`  (no `section` field)
- **WHEN**: The operation is applied
- **THEN**: The merged entry is placed in MISTAKES TO AVOID (section of first valid source_id `mis-001`) with a `mis-NNN` ID

### SCN-CUR-003-07: MERGE Where First Source ID Was Deleted by Prior Op {#SCN-CUR-003-07}
- **Implements**: REQ-CUR-003, REQ-CUR-005
- **GIVEN**: A playbook with:
  - PATTERNS & APPROACHES: `[{name: "pat-001", text: "A", helpful: 2, harmful: 0}, {name: "pat-002", text: "B", helpful: 1, harmful: 0}, {name: "pat-003", text: "C", helpful: 3, harmful: 0}]`
- **AND**: Operations list:
  1. `{"type": "DELETE", "target_id": "pat-001", "reason": "obsolete"}`
  2. `{"type": "MERGE", "source_ids": ["pat-001", "pat-002", "pat-003"], "merged_text": "combined"}`
- **WHEN**: Operations are applied sequentially
- **THEN**:
  - Op 1: `pat-001` is deleted
  - Op 2: `pat-001` is non-existent (already deleted), filtered out; `pat-002` and `pat-003` remain valid (2 >= 2), MERGE proceeds
  - Merged entry inherits section from `pat-002` (first valid source_id after filtering)
  - Counters: `helpful = 1 + 3 = 4`, `harmful = 0 + 0 = 0`

### SCN-CUR-003-08: MERGE Skipped When ALL Source IDs Non-Existent {#SCN-CUR-003-08}
- **Implements**: REQ-CUR-003, CON-CUR-003
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "use type hints", helpful: 5, harmful: 1}]`
- **AND**: An operation `{"type": "MERGE", "source_ids": ["pat-999", "pat-888"], "merged_text": "combined"}`
- **WHEN**: The operation is applied
- **THEN**:
  - `pat-999` is logged as non-existent (OBS-CUR-002)
  - `pat-888` is logged as non-existent (OBS-CUR-002)
  - 0 valid source IDs remain after filtering (0 < 2), so MERGE is skipped entirely
  - Playbook is unchanged: PATTERNS & APPROACHES still contains only `[{name: "pat-001", text: "use type hints", helpful: 5, harmful: 1}]`
- **NOTE**: [Resolves SPEC_CHALLENGE Q4]

### SCN-CUR-004-01: DELETE Removes Entry {#SCN-CUR-004-01}
- **Implements**: REQ-CUR-004
- **GIVEN**: A playbook with MISTAKES TO AVOID: `[{name: "mis-001", text: "bad advice", helpful: 0, harmful: 2}]`
- **AND**: An operation `{"type": "DELETE", "target_id": "mis-001", "reason": "contradicts project standards"}`
- **WHEN**: The operation is applied
- **THEN**:
  - `mis-001` is removed from MISTAKES TO AVOID
  - OBS-CUR-003 diagnostic logged with: target_id `mis-001`, text `"bad advice"`, reason `"contradicts project standards"`

### SCN-CUR-004-02: DELETE Skips Non-Existent ID {#SCN-CUR-004-02}
- **Implements**: REQ-CUR-004, CON-CUR-003
- **GIVEN**: A playbook with no entry named `"pat-999"`
- **AND**: An operation `{"type": "DELETE", "target_id": "pat-999", "reason": "cleanup"}`
- **WHEN**: The operation is applied
- **THEN**:
  - The operation is skipped (no entry found)
  - OBS-CUR-002 diagnostic logged with: target_id `pat-999`, operation type `DELETE`

### SCN-CUR-004-03: DELETE with Empty target_id {#SCN-CUR-004-03}
- **Implements**: REQ-CUR-004, REQ-CUR-009
- **GIVEN**: An operation `{"type": "DELETE", "target_id": "", "reason": "cleanup"}`
- **WHEN**: The operation is validated
- **THEN**: The operation is skipped (validation failure: empty `target_id`)

### SCN-CUR-005-01: Sequential Processing -- DELETE Before MERGE {#SCN-CUR-005-01}
- **Implements**: REQ-CUR-005
- **GIVEN**: A playbook with OTHERS: `[{name: "oth-001", text: "A", helpful: 1, harmful: 0}, {name: "oth-002", text: "B", helpful: 2, harmful: 0}, {name: "oth-003", text: "C", helpful: 3, harmful: 0}]`
- **AND**: Operations:
  1. `{"type": "DELETE", "target_id": "oth-001", "reason": "outdated"}`
  2. `{"type": "MERGE", "source_ids": ["oth-002", "oth-003"], "merged_text": "combined BC"}`
- **WHEN**: Operations are applied
- **THEN**:
  - After op 1: `oth-001` removed
  - After op 2: `oth-002` and `oth-003` removed, new entry with `helpful=5, harmful=0` added
  - Final OTHERS section has one entry (the merged one)

### SCN-CUR-005-02: ADD Then MERGE Referencing New Entry {#SCN-CUR-005-02}
- **Implements**: REQ-CUR-005
- **GIVEN**: A playbook with OTHERS section containing one pre-existing entry: `[{name: "oth-001", text: "prefer pathlib", helpful: 2, harmful: 0}]`
- **AND**: Operations:
  1. `{"type": "ADD", "text": "use structured logging", "section": "OTHERS"}`
  2. `{"type": "MERGE", "source_ids": ["oth-002", "oth-001"], "merged_text": "prefer pathlib and use structured logging for all file operations"}`
- **WHEN**: Operations are applied sequentially
- **THEN**:
  - Op 1 creates `{name: "oth-002", text: "use structured logging", helpful: 0, harmful: 0}` in OTHERS
  - Op 2 references `oth-002` (created by op 1) and `oth-001` (pre-existing); both exist, so MERGE proceeds
  - `oth-001` and `oth-002` are removed from OTHERS
  - A new entry `{name: "oth-003", text: "prefer pathlib and use structured logging for all file operations", helpful: 2, harmful: 0}` is added to OTHERS (section of first valid source_id `oth-002`)
  - Counters: `helpful = 0 + 2 = 2`, `harmful = 0 + 0 = 0`
  - Final OTHERS section: `[{name: "oth-003", text: "prefer pathlib and use structured logging for all file operations", helpful: 2, harmful: 0}]`
- **NOTE**: This scenario demonstrates that sequential processing allows later operations to reference entries created by earlier ones. [Resolves SPEC_CHALLENGE Q3]

### SCN-CUR-005-03: Exception Rollback Returns Original Playbook {#SCN-CUR-005-03}
- **Implements**: REQ-CUR-006
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "A", helpful: 5, harmful: 1}]`
- **AND**: An extraction result containing `"operations": [{"type": "ADD", "text": "will fail"}]`
- **AND**: `_apply_curator_operations` is monkeypatched to raise `RuntimeError("injected failure")` when called
- **WHEN**: `update_playbook_data()` catches the exception in the try/except wrapping `_apply_curator_operations`
- **THEN**: The original playbook is returned unchanged
- **AND**: `pat-001` still exists with `helpful=5, harmful=1`
- **NOTE**: Tests for this scenario use monkeypatching to inject a `RuntimeError` during operations processing. The specific exception type does not matter -- any uncaught exception triggers rollback. [Resolves SPEC_CHALLENGE Q5]

### SCN-CUR-005-04: Skipped Operations Do Not Trigger Rollback {#SCN-CUR-005-04}
- **Implements**: REQ-CUR-005, REQ-CUR-006
- **GIVEN**: A playbook with OTHERS: `[{name: "oth-001", text: "keep me", helpful: 1, harmful: 0}]`
- **AND**: Operations:
  1. `{"type": "DELETE", "target_id": "nonexistent", "reason": "cleanup"}`  (will be skipped)
  2. `{"type": "ADD", "text": "new entry", "section": "OTHERS"}`
- **WHEN**: Operations are applied
- **THEN**:
  - Op 1 is skipped (non-existent ID, no-op)
  - Op 2 succeeds, adding new entry
  - Both `oth-001` and the new entry exist in OTHERS
  - No rollback occurs (skipping is normal)

### SCN-CUR-007-01: Prompt Includes Entry IDs and Operation Examples {#SCN-CUR-007-01}
- **Implements**: REQ-CUR-007
- **GIVEN**: The updated `reflection.txt` template
- **WHEN**: The template content is inspected
- **THEN**:
  - The template includes instructions for `operations` as a list of objects
  - At least one ADD example: `{"type": "ADD", "text": "...", "section": "..."}`
  - At least one MERGE example: `{"type": "MERGE", "source_ids": [...], "merged_text": "...", "section": "..."}`
  - At least one DELETE example: `{"type": "DELETE", "target_id": "...", "reason": "..."}`
  - The template states the LLM may return `"operations": []` if no changes needed
  - The template states a maximum of 10 operations
  - The `{playbook}` variable provides entry IDs (names) visible to the LLM

### SCN-CUR-008-01: Operations Key Present -- new_key_points Ignored {#SCN-CUR-008-01}
- **Implements**: REQ-CUR-008
- **GIVEN**: An extraction result:
  ```json
  {
    "operations": [{"type": "ADD", "text": "from ops", "section": "OTHERS"}],
    "new_key_points": ["from nkp"],
    "evaluations": []
  }
  ```
- **AND**: A playbook with empty sections
- **WHEN**: `update_playbook_data()` is called
- **THEN**:
  - Only `"from ops"` is added to the playbook (via operations path)
  - `"from nkp"` is NOT added (new_key_points ignored when operations present)

### SCN-CUR-008-02: Operations Key Absent -- new_key_points Used {#SCN-CUR-008-02}
- **Implements**: REQ-CUR-008
- **GIVEN**: An extraction result:
  ```json
  {
    "new_key_points": ["legacy point"],
    "evaluations": []
  }
  ```
  (no `operations` key)
- **AND**: A playbook with empty sections
- **WHEN**: `update_playbook_data()` is called
- **THEN**:
  - `"legacy point"` is added to OTHERS section (treated as ADD, backward compat)

### SCN-CUR-008-03: Empty Operations List -- new_key_points Still Ignored {#SCN-CUR-008-03}
- **Implements**: REQ-CUR-008
- **GIVEN**: An extraction result:
  ```json
  {
    "operations": [],
    "new_key_points": ["should not be added"],
    "evaluations": []
  }
  ```
- **WHEN**: `update_playbook_data()` is called
- **THEN**:
  - No entries are added (operations list is empty)
  - `"should not be added"` is NOT added (operations key is present, even though empty)

### SCN-CUR-009-01: Operations Truncated to 10 {#SCN-CUR-009-01}
- **Implements**: REQ-CUR-009, CON-CUR-004
- **GIVEN**: An `operations` list with 15 entries (all valid ADDs)
- **WHEN**: `_apply_curator_operations()` processes the list
- **THEN**:
  - Only the first 10 operations are processed
  - Operations 11-15 are discarded
  - A diagnostic log is emitted noting truncation from 15 to 10

### SCN-CUR-009-03: Exactly 10 Operations -- No Truncation {#SCN-CUR-009-03}
- **Implements**: REQ-CUR-009, CON-CUR-004
- **GIVEN**: An `operations` list with exactly 10 entries (all valid ADDs with distinct texts)
- **WHEN**: `_apply_curator_operations()` processes the list
- **THEN**:
  - All 10 operations are processed (no truncation occurs)
  - NO truncation diagnostic log is emitted (list size does not exceed 10)
  - 10 new entries are created in the playbook
- **NOTE**: 10 is the boundary -- truncation only fires at 11+. [Resolves SPEC_CHALLENGE Q6]

### SCN-CUR-009-04: Exactly 11 Operations -- Truncation to 10 {#SCN-CUR-009-04}
- **Implements**: REQ-CUR-009, CON-CUR-004
- **GIVEN**: An `operations` list with exactly 11 entries (all valid ADDs with distinct texts)
- **WHEN**: `_apply_curator_operations()` processes the list
- **THEN**:
  - Only the first 10 operations are processed
  - Operation 11 (index 10) is discarded
  - A truncation diagnostic log is emitted noting truncation from 11 to 10 (OBS-CUR-001)
  - 10 new entries are created in the playbook (not 11)
- **NOTE**: [Resolves SPEC_CHALLENGE Q6]

### SCN-CUR-009-02: Unknown or Missing Operation Type Skipped {#SCN-CUR-009-02}
- **Implements**: REQ-CUR-009
- **GIVEN**: Two operations:
  - (a) `{"type": "REPLACE", "target_id": "pat-001", "text": "rewritten"}` (unknown type string)
  - (b) `{"target_id": "pat-001", "text": "rewritten"}` (no `type` key at all)
- **WHEN**: Each operation is validated
- **THEN**:
  - (a) is skipped with a diagnostic log (unknown type `"REPLACE"`)
  - (b) is skipped with a diagnostic log (unknown type `""` -- `op.get("type", "")` returns empty string when key is absent, which does not match `"ADD"`, `"UPDATE"`, `"MERGE"`, or `"DELETE"`)
- **NOTE**: Both cases fall through to the `else` branch in the operation dispatch. The `op.get("type", "")` pattern means a missing `type` key defaults to empty string, which is treated as an unknown type. Recognized types are: `"ADD"`, `"UPDATE"`, `"MERGE"`, `"DELETE"`. [Resolves SPEC_CHALLENGE Q12]

### SCN-CUR-010-01: Curator Produces Reasoning and Operations {#SCN-CUR-010-01}
- **Implements**: REQ-CUR-010, REQ-CUR-011
- **GIVEN**: A reflector output:
  ```json
  {
    "analysis": "The session showed poor error handling. pat-001 was not applied.",
    "bullet_tags": [
      {"name": "pat-001", "tag": "harmful", "rationale": "Error handling advice was ignored"}
    ]
  }
  ```
- **AND**: A playbook with entries including `pat-001`
- **WHEN**: `run_curator(reflector_output, playbook)` is called and the LLM returns:
  ```json
  {
    "reasoning": "pat-001 has been tagged harmful repeatedly. The advice may need updating.",
    "operations": [
      {"type": "UPDATE", "target_id": "pat-001", "text": "Use structured error handling with try/except blocks and specific exception types"}
    ]
  }
  ```
- **THEN**: The function returns the parsed dict with `reasoning` and `operations` fields intact

### SCN-CUR-010-02: Curator API Error Returns Empty Result {#SCN-CUR-010-02}
- **Implements**: REQ-CUR-012
- **GIVEN**: The Anthropic API is unreachable and all retries are exhausted
- **WHEN**: `run_curator(reflector_output, playbook)` is called
- **THEN**: Returns `{"reasoning": "", "operations": []}` without raising an exception

### SCN-CUR-010-03: Curator with Empty Reflector Output {#SCN-CUR-010-03}
- **Implements**: REQ-CUR-010
- **GIVEN**: A reflector output `{"analysis": "", "bullet_tags": []}` (reflector failed or no analysis)
- **AND**: A playbook with entries
- **WHEN**: `run_curator(reflector_output, playbook)` is called
- **THEN**: The function still returns a valid `{"reasoning": str, "operations": list}` result; the curator may produce zero operations if the reflector output is empty

### SCN-CUR-011-01: Curator Prompt Template Structure {#SCN-CUR-011-01}
- **Implements**: REQ-CUR-010
- **GIVEN**: The `curator.txt` prompt template
- **WHEN**: The template content is inspected
- **THEN**:
  - The template includes placeholders for the reflector's output and the formatted playbook
  - The template instructs the LLM to produce a JSON response with `"reasoning"` and `"operations"` keys
  - The template includes examples of ADD, UPDATE, DELETE, and MERGE operations using the correct field names (`target_id`, `source_ids`, `merged_text`)
  - The template explicitly states a maximum of 10 operations
  - The template states the LLM may return `"operations": []` if no changes are needed
  - The template does NOT include the raw transcript (the curator works from reflector output only)

### SCN-CUR-012-01: Curator Unparseable JSON Returns Empty Result {#SCN-CUR-012-01}
- **Implements**: REQ-CUR-012
- **GIVEN**: The LLM returns a response that cannot be parsed as JSON
- **WHEN**: `run_curator(reflector_output, playbook)` processes the response
- **THEN**: Returns `{"reasoning": "", "operations": []}` without raising an exception

### SCN-CUR-013-01: UPDATE Revises Entry Text {#SCN-CUR-013-01}
- **Implements**: REQ-CUR-013
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "use type hints", helpful: 5, harmful: 1}]`
- **AND**: An operation `{"type": "UPDATE", "target_id": "pat-001", "text": "use type hints for all function parameters and return values"}`
- **WHEN**: The operation is applied
- **THEN**:
  - `pat-001` text is now `"use type hints for all function parameters and return values"`
  - `pat-001` name is still `"pat-001"` (preserved)
  - `pat-001` counters are still `helpful=5, harmful=1` (preserved)
  - `pat-001` remains in PATTERNS & APPROACHES (not moved)

### SCN-CUR-013-02: UPDATE Skips Non-Existent target_id {#SCN-CUR-013-02}
- **Implements**: REQ-CUR-013
- **GIVEN**: A playbook with no entry named `"pat-999"`
- **AND**: An operation `{"type": "UPDATE", "target_id": "pat-999", "text": "new text"}`
- **WHEN**: The operation is applied
- **THEN**:
  - The operation is skipped (target_id not found)
  - A log message is emitted to stderr noting the non-existent ID
  - OBS-CUR-002 diagnostic is logged (in diagnostic mode)
  - No entries are modified

### SCN-CUR-013-03: UPDATE Skips Empty target_id {#SCN-CUR-013-03}
- **Implements**: REQ-CUR-013
- **GIVEN**: An operation `{"type": "UPDATE", "target_id": "", "text": "new text"}`
- **WHEN**: The operation is validated
- **THEN**: The operation is skipped (validation failure: empty target_id)

### SCN-CUR-013-04: UPDATE Skips Empty Text {#SCN-CUR-013-04}
- **Implements**: REQ-CUR-013
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "use type hints", helpful: 5, harmful: 1}]`
- **AND**: An operation `{"type": "UPDATE", "target_id": "pat-001", "text": ""}`
- **WHEN**: The operation is validated
- **THEN**: The operation is skipped (validation failure: empty text); `pat-001` retains its original text

### SCN-CUR-014-01: apply_structured_operations Applies Operations with Deep Copy {#SCN-CUR-014-01}
- **Implements**: REQ-CUR-014
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "A", helpful: 5, harmful: 1}]`
- **AND**: Operations: `[{"type": "ADD", "text": "new insight", "section": "OTHERS"}]`
- **WHEN**: `apply_structured_operations(playbook, operations)` is called
- **THEN**:
  - The returned playbook has the ADD applied (new entry in OTHERS)
  - The original `playbook` dict passed in is NOT mutated (deep copy isolation)

### SCN-CUR-014-02: apply_structured_operations Rollback on Exception {#SCN-CUR-014-02}
- **Implements**: REQ-CUR-014
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "A", helpful: 5, harmful: 1}]`
- **AND**: `_apply_curator_operations` is monkeypatched to raise `RuntimeError("injected failure")`
- **WHEN**: `apply_structured_operations(playbook, operations)` is called
- **THEN**: The original playbook is returned unchanged (rollback on exception)

### SCN-CUR-014-03: apply_structured_operations Supports UPDATE {#SCN-CUR-014-03}
- **Implements**: REQ-CUR-014, REQ-CUR-013
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "old text", helpful: 3, harmful: 0}]`
- **AND**: Operations: `[{"type": "UPDATE", "target_id": "pat-001", "text": "revised text"}]`
- **WHEN**: `apply_structured_operations(playbook, operations)` is called
- **THEN**: The returned playbook has `pat-001.text == "revised text"` with counters preserved (`helpful=3, harmful=0`)

### SCN-CUR-014-04: Empty Operations List Returns Original Playbook Reference Unmodified {#SCN-CUR-014-04}
- **Implements**: REQ-CUR-014
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "A", helpful: 5, harmful: 1}]`
- **AND**: Operations: `[]` (empty list)
- **WHEN**: `apply_structured_operations(playbook, [])` is called
- **THEN**:
  - The returned playbook is the SAME reference as the input (no deep copy created)
  - The playbook is unmodified: `pat-001` still exists with `helpful=5, harmful=1`
  - No operations processing occurs (zero overhead)
- **NOTE**: This is the no-op fast path. An empty operations list requires no deep copy, no try/except, and no iteration. The function returns the original playbook immediately.

### SCN-CUR-015-01: prune_harmful Removes Entries Meeting Threshold {#SCN-CUR-015-01}
- **Implements**: REQ-CUR-015
- **GIVEN**: A playbook with:
  - MISTAKES TO AVOID: `[{name: "mis-001", text: "bad advice", helpful: 1, harmful: 4}]`
  - OTHERS: `[{name: "oth-001", text: "good tip", helpful: 5, harmful: 0}]`
- **WHEN**: `prune_harmful(playbook)` is called
- **THEN**:
  - `mis-001` is removed (harmful=4 >= 3 AND harmful=4 > helpful=1)
  - `oth-001` is retained (harmful=0, does not meet threshold)

### SCN-CUR-015-02: prune_harmful Preserves Zero-Evaluation Entries {#SCN-CUR-015-02}
- **Implements**: REQ-CUR-015
- **GIVEN**: A playbook with OTHERS: `[{name: "oth-001", text: "new entry", helpful: 0, harmful: 0}]`
- **WHEN**: `prune_harmful(playbook)` is called
- **THEN**: `oth-001` is retained (zero evaluations: harmful=0 < 3, so first condition fails)

### SCN-CUR-015-03: prune_harmful Equal Counters Not Pruned {#SCN-CUR-015-03}
- **Implements**: REQ-CUR-015
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "controversial", helpful: 3, harmful: 3}]`
- **WHEN**: `prune_harmful(playbook)` is called
- **THEN**: `pat-001` is retained (harmful=3 >= 3 is TRUE, but harmful=3 > helpful=3 is FALSE -- equal, not greater)

### SCN-CUR-015-04: prune_harmful Logs Pruned Entries {#SCN-CUR-015-04}
- **Implements**: REQ-CUR-015
- **GIVEN**: A playbook with MISTAKES TO AVOID: `[{name: "mis-001", text: "bad advice that is very long and should be truncated in the log output", helpful: 0, harmful: 5}]`
- **WHEN**: `prune_harmful(playbook)` is called
- **THEN**:
  - `mis-001` is pruned
  - A log message is emitted to stderr with the entry's name, truncated text, and counters
  - In diagnostic mode, `save_diagnostic()` is called with the prune details

### SCN-CUR-016-01: Curator LLM Returns JSON in Prose; Balanced-Brace Extraction Succeeds {#SCN-CUR-016-01}
- **Implements**: REQ-CUR-016
- **GIVEN**: The curator LLM returns a response like:
  ```
  Here is my analysis of the playbook:

  {"reasoning": "pat-001 has been harmful", "operations": [{"type": "DELETE", "target_id": "pat-001", "reason": "consistently harmful"}]}

  I hope this helps improve the playbook.
  ```
- **WHEN**: `run_curator()` parses the response
- **THEN**:
  - Code fence extraction (strategies 1 and 2) fails (no code fences present)
  - Balanced-brace counting (strategy 3) finds the outermost `{` and scans forward, matching braces to extract the JSON object
  - The extracted JSON is parsed successfully by `json.loads()`
  - The function returns `{"reasoning": "pat-001 has been harmful", "operations": [{"type": "DELETE", "target_id": "pat-001", "reason": "consistently harmful"}]}`

### SCN-CUR-016-02: Curator LLM Returns JSON Code Fence; Fence Extraction Succeeds {#SCN-CUR-016-02}
- **Implements**: REQ-CUR-016
- **GIVEN**: The curator LLM returns a response like:
  ````
  ```json
  {"reasoning": "No changes needed", "operations": []}
  ```
  ````
- **WHEN**: `run_curator()` parses the response
- **THEN**:
  - Code fence extraction (strategy 1) succeeds: content between ` ```json ` and ` ``` ` is extracted
  - The extracted JSON is parsed successfully by `json.loads()`
  - The function returns `{"reasoning": "No changes needed", "operations": []}`

---

## Invariants

### INV-CUR-001: Deep Copy Isolation {#INV-CUR-001}
- **Implements**: SC-CUR-005, CON-CUR-005, FM-CUR-005
- **Statement**: When `operations` are being processed, mutations are applied to a `copy.deepcopy()` of the playbook. The original playbook reference passed to `update_playbook_data()` is never mutated by the operations path. If an uncaught exception occurs, the original is returned unchanged.
- **Enforced by**: `update_playbook_data()` calls `copy.deepcopy(playbook)` before entering the operations processing loop. The try/except wrapping the operations loop returns the original on exception. On success, the modified copy is returned.
- **Scope**: The deep copy and try/except cover ONLY the operations processing path. Evaluations and pruning run outside this protection. See REQ-CUR-006 atomicity scope note. [Resolves SPEC_CHALLENGE Q8]

### INV-CUR-002: No Crash on Invalid Operations {#INV-CUR-002}
- **Implements**: SC-CUR-005, QG-CUR-001, CON-CUR-003, FM-CUR-001
- **Statement**: No individual operation (regardless of malformed fields, non-existent IDs, or unexpected types) causes `update_playbook_data()` to raise an exception. Invalid operations are skipped with diagnostic logging.
- **Enforced by**: Validation checks in `_apply_curator_operations()` for each operation type (REQ-CUR-009). Non-existent ID references are filtered or skipped (CON-CUR-003). Unknown operation types are skipped.

### INV-CUR-003: Counter Non-Negativity Preserved Through MERGE {#INV-CUR-003}
- **Implements**: SC-CUR-003, INV-SCORE-001, INV-SCORE-002
- **Statement**: The `helpful` and `harmful` counters on a merged entry are the sum of the corresponding counters from valid source entries. Since all source counters are `>= 0` (INV-SCORE-001, INV-SCORE-002), the summed counters are also `>= 0`.
- **Enforced by**: MERGE counter logic uses `sum()` of non-negative source values. No subtraction or reset occurs.
- **Upstream assumption**: This invariant assumes upstream data integrity: all entries in the playbook have non-negative `helpful`/`harmful` counters. If `playbook.json` is manually edited to have negative counters, the MERGE may produce negative sums. The spec does not require defensive clamping of source counter values. [Resolves SPEC_CHALLENGE Q7]

### INV-CUR-004: Section Names Canonical After Operations {#INV-CUR-004}
- **Implements**: INV-SECT-002
- **Statement**: After operations processing, every key in the `sections` dict remains a member of the canonical set defined by `SECTION_SLUGS`. Operations never create new section names.
- **Enforced by**: ADD and MERGE resolve section names via `_resolve_section()` which always returns a canonical name. DELETE removes entries from existing sections but never creates or renames sections.

### INV-CUR-005: Operations Bounded by CON-CUR-004 {#INV-CUR-005}
- **Implements**: CON-CUR-004, FM-CUR-012
- **Statement**: At most 10 operations are processed per invocation of `_apply_curator_operations()`, regardless of how many the LLM returns.
- **Enforced by**: The operations list is truncated to `operations[:10]` before the processing loop begins (REQ-CUR-009).

### INV-CUR-006: Precedence Rule Prevents Double-Processing {#INV-CUR-006}
- **Implements**: SC-CUR-007, FM-CUR-009
- **Statement**: In a single `update_playbook_data()` call, entries are added either via the `operations` path (ADD operations) or via the `new_key_points` path, never both.
- **Enforced by**: The `operations` key check at the beginning of `update_playbook_data()` branches exclusively: if `"operations" in extraction_result`, the operations path runs and `new_key_points` is not consulted (REQ-CUR-008).

### INV-CUR-007: UPDATE Preserves Entry Identity {#INV-CUR-007}
- **Implements**: SC-CUR-009
- **Statement**: An UPDATE operation modifies ONLY the `text` field of the target entry. The entry's `name` (ID), `helpful` counter, `harmful` counter, and section placement are preserved unchanged.
- **Enforced by**: The UPDATE handler in `_apply_curator_operations()` (or `apply_structured_operations()`) sets only `entry["text"] = new_text` after locating the entry. No other fields are modified.

### INV-CUR-008: Curator Never Raises to Caller {#INV-CUR-008}
- **Implements**: SC-CUR-008, FM-ACE-001
- **Statement**: `run_curator()` never raises an exception to its caller. All failure modes (API errors, JSON parse errors, unexpected exceptions) are caught internally and result in the empty return value `{"reasoning": "", "operations": []}`.
- **Enforced by**: A top-level try/except in `run_curator()` that catches `Exception` and returns the empty result. Specific error types (API errors) are handled first for proper retry logic; the outer catch is a defensive fallback.

### INV-CUR-009: UPDATE Validates Both Fields {#INV-CUR-009}
- **Implements**: SC-CUR-009
- **Statement**: An UPDATE operation is skipped (validation failure) if EITHER `target_id` is empty/missing OR `text` is empty/missing. Both fields are required for a valid UPDATE.
- **Enforced by**: Validation checks at the top of the UPDATE handler: `if not target_id or not text: skip`.

### INV-CUR-010: apply_structured_operations Deep Copy Isolation {#INV-CUR-010}
- **Implements**: SC-CUR-010
- **Statement**: `apply_structured_operations()` creates a `copy.deepcopy()` of the playbook before processing operations. The original playbook reference is never mutated. On exception, the original is returned unchanged.
- **Enforced by**: Same deep copy + try/except pattern as the operations path in `update_playbook_data()` (REQ-CUR-006), but as a standalone public function.

### INV-CUR-011: prune_harmful Thresholds Identical to Baseline {#INV-CUR-011}
- **Implements**: SC-CUR-011
- **Statement**: `prune_harmful()` uses exactly the same pruning conditions as the pruning logic in `update_playbook_data()`: `harmful >= 3 AND harmful > helpful`. The thresholds are NOT configurable and MUST NOT differ from the baseline.
- **Enforced by**: The function body uses the same conditional expression. Tests verify the decision table (see Pruning Contract below).

---

## Pruning Interaction Note

After curator operations are applied, pruning (`harmful >= 3 AND harmful > helpful`) runs as the final step. In the baseline flow, this is the pruning code within `update_playbook_data()`. In the Phase 1 flow, this is the standalone `prune_harmful()` function (REQ-CUR-015). The logic and thresholds are identical (INV-CUR-011). This means:
- A merged entry whose summed counters exceed the pruning threshold will be pruned in the same cycle
- A newly ADDed entry (with `helpful=0, harmful=0`) will never be pruned (INV-SCORE-003)
- An UPDATEd entry retains its counters; if those counters already exceeded the pruning threshold before the UPDATE, the entry will still be pruned after the UPDATE
- This is intentional -- pruning is a safety net that runs regardless of how entries were created or modified

---

## Constraints (from Intent)

| ID | Constraint | Enforced By |
|----|-----------|-------------|
| CON-CUR-001 | Backward compat: old-format LLM responses still work | REQ-CUR-008, SCN-CUR-008-02 |
| CON-CUR-002 | No new dependencies; `update_playbook_data()` signature unchanged | REQ-CUR-006 (signature), all REQ-CUR-* (implementation in common.py) |
| CON-CUR-003 | Non-existent ID references silently skipped | REQ-CUR-003 (MERGE filtering), REQ-CUR-004 (DELETE skip), INV-CUR-002 |
| CON-CUR-004 | Max 10 operations per cycle (code-enforced) | REQ-CUR-009, INV-CUR-005 |
| CON-CUR-005 | Atomicity via `copy.deepcopy()` | REQ-CUR-006, INV-CUR-001, REQ-CUR-014, INV-CUR-010 |
| CON-CUR-006 | Curator does not re-analyze transcript; works from reflector output only | REQ-CUR-010 |
| CON-CUR-007 | UPDATE preserves entry identity (name, counters, section) | REQ-CUR-013, INV-CUR-007 |
| CON-CUR-008 | prune_harmful() thresholds identical to baseline pruning logic | REQ-CUR-015, INV-CUR-011 |
