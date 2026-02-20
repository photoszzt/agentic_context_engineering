# Requirements Specification: Reflector Module

## Intent Traceability

This section preserves the success criteria from the approved intent.
The full intent document is in `.planning/intent.md` for historical reference.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* |
|------|-------------------|-------------------|
| SC-ACE-002 | **Bullet ID Referencing During Generation** -- The `playbook.txt` injection template instructs Claude to cite key point IDs (e.g., `[pat-001]`) in its reasoning when a key point influences its response. The injection prompt includes a directive: "When a key point from the playbook influences your response, cite its ID in your reasoning." `extract_cited_ids(messages)` scans assistant messages for `[pat-NNN]` patterns and returns a deduplicated list. | REQ-REFL-001, REQ-REFL-002, SCN-REFL-001-01, SCN-REFL-001-02, SCN-REFL-001-03, SCN-REFL-002-01, SCN-REFL-002-02, INV-REFL-001 |
| SC-ACE-003 | **Separate Reflector Role** -- A dedicated reflection step analyzes the session transcript and tags each existing key point as `helpful`, `harmful`, or `neutral` based on evidence from the conversation. The reflector receives the full transcript, the playbook dict, and cited IDs. It produces: (a) a textual analysis of what went well/poorly, and (b) per-key-point tags with rationale. Fallback when no citations present: content-based analysis. On failure (API error, unparseable JSON): returns `{analysis: "", bullet_tags: []}`. Robust JSON extraction with balanced-brace counting. | REQ-REFL-003, REQ-REFL-004, REQ-REFL-005, REQ-REFL-006, REQ-REFL-007, REQ-REFL-008, SCN-REFL-003-01, SCN-REFL-003-02, SCN-REFL-003-03, SCN-REFL-004-01, SCN-REFL-004-02, SCN-REFL-005-01, SCN-REFL-005-02, SCN-REFL-006-01, SCN-REFL-006-02, SCN-REFL-007-01, SCN-REFL-008-01, SCN-REFL-008-02, INV-REFL-002, INV-REFL-003, INV-REFL-004 |

---

## Requirements

### REQ-REFL-001: Extract Cited IDs from Transcript {#REQ-REFL-001}
- **Implements**: SC-ACE-002
- **GIVEN**: A list of messages (`list[dict]`) from a session transcript, where each message has `role` and `content` keys
- **WHEN**: `extract_cited_ids(messages)` is called
- **THEN**:
  - Only messages with `role == "assistant"` are scanned
  - The function searches message content for patterns matching `[{slug}-{NNN}]` where `slug` is one of the section slug prefixes (`pat`, `mis`, `pref`, `ctx`, `oth`) or the legacy prefix (`kpt_NNN`), and `NNN` is one or more digits
  - The regex pattern is: `\[((?:pat|mis|pref|ctx|oth)-\d+|kpt_\d+)\]`
  - Returns a deduplicated `list[str]` of the matched ID strings (without the surrounding brackets)
  - Order is not guaranteed (deduplication via set)
  - If no assistant messages exist or no citations are found, returns an empty list `[]`
  - User messages are never scanned (they are echoes from the human, not Claude's reasoning)

### REQ-REFL-002: Citation Directive in playbook.txt {#REQ-REFL-002}
- **Implements**: SC-ACE-002
- **GIVEN**: The `playbook.txt` injection template used by `format_playbook()`
- **WHEN**: The template content is inspected
- **THEN**:
  - The template includes a directive instructing Claude to cite key point IDs (e.g., `[pat-001]`) in its reasoning when a key point influences its response
  - The directive text includes language such as: "When a key point from the playbook influences your response, cite its ID in your reasoning"
  - The directive uses the bracket format `[ID]` consistent with the extraction pattern in REQ-REFL-001
  - The existing `{key_points}` placeholder and template structure are preserved (QG-ACE-001)

### REQ-REFL-003: Reflector LLM Call {#REQ-REFL-003}
- **Implements**: SC-ACE-003
- **GIVEN**: A session transcript (`messages: list[dict]`), a playbook (`playbook: dict`), and a list of cited IDs (`cited_ids: list[str]`)
- **WHEN**: `run_reflector(messages, playbook, cited_ids)` is called
- **THEN**:
  - The function loads the `reflector.txt` prompt template via `load_template("reflector.txt")`
  - The function formats the playbook into prompt-friendly text via `format_playbook(playbook)` internally
  - The function constructs an LLM prompt containing: the full transcript, the formatted playbook, and the cited IDs
  - The function makes an async Anthropic API call with the same model, API key, and client configuration as `extract_keypoints()`
  - The function uses the same retry logic (MAX_RETRIES=3, BASE_DELAY=2.0s, exponential backoff with jitter) as `extract_keypoints()`
  - The function parses the LLM response JSON to extract `analysis` (string) and `bullet_tags` (list of dicts)
  - The function returns a dict matching the reflector output schema: `{"analysis": str, "bullet_tags": list[dict]}`

### REQ-REFL-004: Reflector Output Schema {#REQ-REFL-004}
- **Implements**: SC-ACE-003
- **GIVEN**: A successful reflector LLM call that returns parseable JSON
- **WHEN**: The response is parsed
- **THEN**:
  - The returned dict contains `"analysis"` (string): textual analysis of what went well/poorly in the session
  - The returned dict contains `"bullet_tags"` (list of dicts): per-key-point tags
  - Each entry in `bullet_tags` has:
    - `"name"` (string): key point ID, e.g., `"pat-001"` -- this is the `name` field from the playbook entry, NOT `id`
    - `"tag"` (string): one of `"helpful"`, `"harmful"`, `"neutral"`
    - `"rationale"` (string): explanation of why this tag was assigned
  - Tags for key points not found in the playbook are ignored by downstream consumers (`apply_bullet_tags()` skips unmatched names)

### REQ-REFL-005: Reflector Fallback When No Citations {#REQ-REFL-005}
- **Implements**: SC-ACE-003
- **GIVEN**: `run_reflector()` is called with `cited_ids` as an empty list
- **WHEN**: The reflector prompt is constructed
- **THEN**:
  - The reflector prompt must explicitly handle both modes:
    - **Citation-guided** (preferred): When `cited_ids` is non-empty, the prompt tells the reflector to focus its analysis on the cited key points and tag them based on their contribution to the session
    - **Content-based** (fallback): When `cited_ids` is empty, the prompt tells the reflector to analyze the full playbook and transcript, tagging key points based on whether the session transcript provides evidence of their helpfulness or harmfulness
  - The output schema is identical in both modes: `{"analysis": str, "bullet_tags": list[dict]}`
  - Content-based fallback matches the current system's behavior where no IDs are cited

### REQ-REFL-006: Reflector Error Handling {#REQ-REFL-006}
- **Implements**: SC-ACE-003
- **GIVEN**: `run_reflector()` encounters a failure
- **WHEN**: The failure is an API error (timeout, connection, rate limit, 5xx, 4xx), an unparseable JSON response, or any other exception
- **THEN**:
  - The function returns the empty result: `{"analysis": "", "bullet_tags": []}`
  - The function does NOT raise an exception to the caller
  - In diagnostic mode, the error is logged via `save_diagnostic()`
  - The session-end flow continues with the empty reflector output (graceful degradation: no bullet tags applied, curator sees empty analysis)

### REQ-REFL-007: Apply Bullet Tags to Playbook {#REQ-REFL-007}
- **Implements**: SC-ACE-003
- **GIVEN**: A playbook dict and a list of bullet tags from the reflector output
- **WHEN**: `apply_bullet_tags(playbook, bullet_tags)` is called
- **THEN**:
  - A name-to-keypoint lookup is built by iterating ALL sections (same as current evaluations logic in `update_playbook_data()`)
  - For each tag in `bullet_tags`:
    - If `tag["name"]` matches a key point in the lookup:
      - `"helpful"` tag: increment the key point's `helpful` counter by 1
      - `"harmful"` tag: increment the key point's `harmful` counter by 1
      - `"neutral"` tag: no change
      - Unrecognized tag value: no change (logged to stderr)
    - If `tag["name"]` does NOT match any key point: the tag is logged to stderr and skipped
  - Returns the modified playbook dict (same reference, mutated in place)

### REQ-REFL-008: Robust JSON Extraction from LLM Response {#REQ-REFL-008}
- **Implements**: SC-ACE-003 (JSON Parsing Robustness, see `.planning/intent.md`)
- **GIVEN**: The LLM response from the reflector call is a text string that may contain JSON embedded in prose, code fences, or be raw JSON
- **WHEN**: `run_reflector()` parses the response
- **THEN**:
  - The function attempts JSON extraction in this order:
    1. Look for ` ```json...``` ` code fence; extract content between fences
    2. Look for ` ```...``` ` code fence (no language tag); extract content
    3. Use balanced-brace counting: find the outermost `{` and scan forward counting braces, stopping at the matching `}`. Extract that substring.
    4. Attempt `json.loads()` on the full response text (raw parse)
  - The FIRST strategy that produces valid JSON (parseable by `json.loads()`) is used
  - If no strategy succeeds, `run_reflector()` returns the fallback result `{"analysis": "", "bullet_tags": []}` (per REQ-REFL-006)
  - If a strategy produces valid JSON but the result does not have `analysis` or `bullet_tags` keys, the function uses `.get()` with defaults (empty string, empty list) -- the partial result is accepted, not rejected

---

## Scenarios

### SCN-REFL-001-01: Extract Cited IDs from Assistant Messages {#SCN-REFL-001-01}
- **Implements**: REQ-REFL-001
- **GIVEN**: Messages:
  ```python
  [
      {"role": "user", "content": "Help me refactor this code"},
      {"role": "assistant", "content": "Based on [pat-001] and [mis-002], I recommend..."},
      {"role": "user", "content": "What about [pat-003]?"},
      {"role": "assistant", "content": "Good point. Also applying [pat-001] here..."}
  ]
  ```
- **WHEN**: `extract_cited_ids(messages)` is called
- **THEN**: Returns `["pat-001", "mis-002"]` (deduplicated; `pat-003` from user message is NOT included)
- **NOTE**: Order within the returned list is not guaranteed; the test should use set comparison.

### SCN-REFL-001-02: No Citations Found {#SCN-REFL-001-02}
- **Implements**: REQ-REFL-001
- **GIVEN**: Messages:
  ```python
  [
      {"role": "user", "content": "Help me with this"},
      {"role": "assistant", "content": "Sure, here is the solution..."}
  ]
  ```
- **WHEN**: `extract_cited_ids(messages)` is called
- **THEN**: Returns `[]` (no citations found in assistant messages)

### SCN-REFL-001-03: Legacy kpt_NNN IDs Cited {#SCN-REFL-001-03}
- **Implements**: REQ-REFL-001
- **GIVEN**: Messages:
  ```python
  [
      {"role": "assistant", "content": "Following [kpt_001] and [oth-003], I suggest..."}
  ]
  ```
- **WHEN**: `extract_cited_ids(messages)` is called
- **THEN**: Returns `["kpt_001", "oth-003"]` (both modern and legacy ID formats are captured)

### SCN-REFL-002-01: playbook.txt Contains Citation Directive {#SCN-REFL-002-01}
- **Implements**: REQ-REFL-002
- **GIVEN**: The `playbook.txt` template file
- **WHEN**: The template content is inspected
- **THEN**: The template contains text instructing Claude to cite key point IDs in bracket notation, such as "cite its ID" and "[pat-001]" or similar example

### SCN-REFL-002-02: format_playbook Still Works After Template Change {#SCN-REFL-002-02}
- **Implements**: REQ-REFL-002
- **GIVEN**: A playbook with entries in PATTERNS & APPROACHES
- **WHEN**: `format_playbook(playbook)` is called after the `playbook.txt` template has been updated with the citation directive
- **THEN**: The output still contains the section headers and formatted entries as before (the `{key_points}` placeholder is preserved)

### SCN-REFL-003-01: Reflector Produces Analysis and Bullet Tags {#SCN-REFL-003-01}
- **Implements**: REQ-REFL-003, REQ-REFL-004
- **GIVEN**: A transcript with messages, a playbook with entries `[{name: "pat-001", text: "use type hints", helpful: 3, harmful: 0}]`, and `cited_ids = ["pat-001"]`
- **WHEN**: `run_reflector(messages, playbook, cited_ids)` is called and the LLM returns:
  ```json
  {
    "analysis": "The session showed good use of type hints as recommended by pat-001.",
    "bullet_tags": [
      {"name": "pat-001", "tag": "helpful", "rationale": "Type hints were applied correctly throughout the refactoring."}
    ]
  }
  ```
- **THEN**: The function returns:
  ```python
  {
      "analysis": "The session showed good use of type hints as recommended by pat-001.",
      "bullet_tags": [
          {"name": "pat-001", "tag": "helpful", "rationale": "Type hints were applied correctly throughout the refactoring."}
      ]
  }
  ```

### SCN-REFL-003-02: Reflector with Empty Cited IDs (Fallback Mode) {#SCN-REFL-003-02}
- **Implements**: REQ-REFL-003, REQ-REFL-005
- **GIVEN**: A transcript with messages, a playbook with entries, and `cited_ids = []`
- **WHEN**: `run_reflector(messages, playbook, [])` is called
- **THEN**: The function still returns a valid `{"analysis": str, "bullet_tags": list}` result based on content-based analysis (the LLM analyzes the full transcript and playbook without citation guidance)

### SCN-REFL-003-03: Reflector with Empty Playbook {#SCN-REFL-003-03}
- **Implements**: REQ-REFL-003
- **GIVEN**: A transcript with messages, a playbook with all empty sections, and `cited_ids = []`
- **WHEN**: `run_reflector(messages, playbook, [])` is called
- **THEN**: The function returns a valid result; `bullet_tags` is empty (no key points to tag) and `analysis` contains observations about the session

### SCN-REFL-004-01: Reflector Output with Multiple Tags {#SCN-REFL-004-01}
- **Implements**: REQ-REFL-004
- **GIVEN**: A reflector LLM response containing:
  ```json
  {
    "analysis": "Session had mixed results...",
    "bullet_tags": [
      {"name": "pat-001", "tag": "helpful", "rationale": "Applied correctly"},
      {"name": "mis-001", "tag": "harmful", "rationale": "Led to incorrect approach"},
      {"name": "pref-001", "tag": "neutral", "rationale": "Not relevant to this session"}
    ]
  }
  ```
- **WHEN**: The response is parsed
- **THEN**: All three tags are preserved with their names, tags, and rationales intact

### SCN-REFL-004-02: Reflector Tags Non-Existent Key Point {#SCN-REFL-004-02}
- **Implements**: REQ-REFL-004, REQ-REFL-007
- **GIVEN**: A reflector output with `bullet_tags: [{"name": "pat-999", "tag": "helpful", "rationale": "Phantom entry"}]`
- **AND**: A playbook with no entry named `"pat-999"`
- **WHEN**: `apply_bullet_tags(playbook, bullet_tags)` is called
- **THEN**: The tag for `"pat-999"` is logged to stderr and skipped; no counter is incremented; no exception is raised

### SCN-REFL-005-01: Reflector API Error Returns Empty Result {#SCN-REFL-005-01}
- **Implements**: REQ-REFL-006
- **GIVEN**: The Anthropic API is unreachable (connection error) and all retries are exhausted
- **WHEN**: `run_reflector(messages, playbook, cited_ids)` is called
- **THEN**: Returns `{"analysis": "", "bullet_tags": []}` without raising an exception

### SCN-REFL-005-02: Reflector Unparseable JSON Returns Empty Result {#SCN-REFL-005-02}
- **Implements**: REQ-REFL-006
- **GIVEN**: The LLM returns a response that cannot be parsed as JSON (e.g., free-form text, malformed JSON)
- **WHEN**: `run_reflector(messages, playbook, cited_ids)` processes the response
- **THEN**: Returns `{"analysis": "", "bullet_tags": []}` without raising an exception

### SCN-REFL-006-01: Apply Bullet Tags Increments Counters {#SCN-REFL-006-01}
- **Implements**: REQ-REFL-007
- **GIVEN**: A playbook with:
  - PATTERNS & APPROACHES: `[{name: "pat-001", text: "use types", helpful: 3, harmful: 1}]`
  - OTHERS: `[{name: "oth-001", text: "legacy tip", helpful: 0, harmful: 0}]`
- **AND**: Bullet tags:
  ```python
  [
      {"name": "pat-001", "tag": "helpful", "rationale": "Applied correctly"},
      {"name": "oth-001", "tag": "harmful", "rationale": "Led to wrong approach"}
  ]
  ```
- **WHEN**: `apply_bullet_tags(playbook, bullet_tags)` is called
- **THEN**: `pat-001.helpful == 4` (was 3, incremented by 1) and `oth-001.harmful == 1` (was 0, incremented by 1)

### SCN-REFL-006-02: Apply Bullet Tags with Neutral Tag {#SCN-REFL-006-02}
- **Implements**: REQ-REFL-007
- **GIVEN**: A playbook with PATTERNS & APPROACHES: `[{name: "pat-001", text: "use types", helpful: 3, harmful: 1}]`
- **AND**: Bullet tags: `[{"name": "pat-001", "tag": "neutral", "rationale": "Not relevant"}]`
- **WHEN**: `apply_bullet_tags(playbook, bullet_tags)` is called
- **THEN**: `pat-001.helpful` remains 3 and `pat-001.harmful` remains 1 (neutral tag causes no change)

### SCN-REFL-007-01: Reflector Prompt Template Structure {#SCN-REFL-007-01}
- **Implements**: REQ-REFL-003, REQ-REFL-005
- **GIVEN**: The `reflector.txt` prompt template
- **WHEN**: The template content is inspected
- **THEN**:
  - The template includes placeholders for the transcript, the formatted playbook, and cited IDs
  - The template instructs the LLM to produce a JSON response with `"analysis"` and `"bullet_tags"` keys
  - The template provides at least one example of the expected output format
  - The template handles both citation-guided and content-based modes (e.g., conditional instruction based on whether cited IDs are present)
  - The `bullet_tags` schema uses `"name"` (not `"id"`) for the key point identifier, matching the playbook entry `name` field (FM-ACE-015)
  - The `bullet_tags` schema uses `"tag"` (not `"rating"`) for the assessment value, with allowed values `"helpful"`, `"harmful"`, `"neutral"`

### SCN-REFL-008-01: LLM Returns JSON in Prose; Balanced-Brace Extraction Succeeds {#SCN-REFL-008-01}
- **Implements**: REQ-REFL-008
- **GIVEN**: The reflector LLM returns a response like:
  ```
  Here is my analysis of the session:

  {"analysis": "The session showed good use of type hints.", "bullet_tags": [{"name": "pat-001", "tag": "helpful", "rationale": "Type hints were applied correctly."}]}

  Let me know if you need more detail.
  ```
- **WHEN**: `run_reflector()` parses the response
- **THEN**:
  - Code fence extraction (strategies 1 and 2) fails (no code fences present)
  - Balanced-brace counting (strategy 3) finds the outermost `{` and scans forward, matching braces to extract the JSON object
  - The extracted JSON is parsed successfully by `json.loads()`
  - The function returns the parsed dict with `analysis` and `bullet_tags` fields intact

### SCN-REFL-008-02: LLM Returns Only JSON Code Fence; Fence Extraction Succeeds {#SCN-REFL-008-02}
- **Implements**: REQ-REFL-008
- **GIVEN**: The reflector LLM returns a response like:
  ````
  ```json
  {"analysis": "No significant observations.", "bullet_tags": []}
  ```
  ````
- **WHEN**: `run_reflector()` parses the response
- **THEN**:
  - Code fence extraction (strategy 1) succeeds: content between ` ```json ` and ` ``` ` is extracted
  - The extracted JSON is parsed successfully by `json.loads()`
  - The function returns `{"analysis": "No significant observations.", "bullet_tags": []}`

---

## Invariants

### INV-REFL-001: Cited IDs Are Deduplicated {#INV-REFL-001}
- **Implements**: SC-ACE-002
- **Statement**: `extract_cited_ids(messages)` never returns duplicate ID strings. Each unique ID appears at most once in the returned list.
- **Enforced by**: Internal use of a `set` for deduplication before converting to a list.

### INV-REFL-002: Reflector Never Raises to Caller {#INV-REFL-002}
- **Implements**: SC-ACE-003, FM-ACE-001
- **Statement**: `run_reflector()` never raises an exception to its caller. All failure modes (API errors, JSON parse errors, unexpected exceptions) are caught internally and result in the empty return value `{"analysis": "", "bullet_tags": []}`.
- **Enforced by**: A top-level try/except in `run_reflector()` that catches `Exception` and returns the empty result. Specific error types (API errors) are handled first for proper retry logic; the outer catch is a defensive fallback.

### INV-REFL-003: Counter Non-Negativity Preserved Through Bullet Tags {#INV-REFL-003}
- **Implements**: SC-ACE-003, INV-SCORE-001, INV-SCORE-002
- **Statement**: `apply_bullet_tags()` only increments counters (by +1). It never decrements, resets, or sets counters to arbitrary values. Since all existing counters are `>= 0` and the only operation is `+= 1`, counters remain `>= 0` after `apply_bullet_tags()`.
- **Enforced by**: The function body contains only `+= 1` operations for `helpful` and `harmful` counters.

### INV-REFL-004: Bullet Tag Application Is Idempotent per Tag List {#INV-REFL-004}
- **Implements**: SC-ACE-003
- **Statement**: Calling `apply_bullet_tags(playbook, bullet_tags)` once applies each tag exactly once. Calling it a second time with the same tag list would double-count. This is the expected behavior (each call represents one session's evaluation). The function is NOT designed to be called multiple times with the same tags.
- **Enforced by**: Simple iteration over the tags list with no deduplication of tag names within a single call (if the reflector produces two tags for the same key point, both are applied).

---

## Constraints (from Intent)

| ID | Constraint | Enforced By |
|----|-----------|-------------|
| CON-ACE-001 | Claude Code Hook Architecture: playbook updates happen in SessionEnd/PreCompact hooks only | REQ-REFL-002 (injection is read-only), REQ-REFL-003 (reflector runs in session-end flow) |
| CON-ACE-003 | Anthropic API Primary: reflector uses Anthropic API, not OpenAI | REQ-REFL-003 (same client config as extract_keypoints) |
| CON-ACE-004 | Playbook Format Continuity: playbook.json schema unchanged | REQ-REFL-007 (apply_bullet_tags mutates existing entries, no schema change) |
| QG-ACE-001 | Backward Compatibility: existing playbook.json files work; format_playbook output compatible | REQ-REFL-002 (playbook.txt template preserves {key_points} placeholder) |
| QG-ACE-003 | Hook Contract Preserved: hooks read from stdin, write to stdout | REQ-REFL-001 (extract_cited_ids is a pure function, no I/O contract change) |
