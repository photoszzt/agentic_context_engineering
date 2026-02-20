# Requirements Specification: Semantic Deduplication Module

## Intent Traceability

This section preserves the success criteria from the approved intent.
The full intent document is in `.planning/intent.md` for historical reference.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* |
|------|-------------------|-------------------|
| SC-ACE-001 | **Semantic Deduplication** -- Before saving the playbook, similar key points (cosine similarity >= configurable threshold, default 0.85) are detected and merged. Deduplication operates on the ENTIRE playbook as a flat collection of entries, ignoring section boundaries (cross-section scope). The merge preserves the FIRST entry's ID and text (by list order) and SUMS the helpful and harmful counters of all merged entries. No LLM call is used -- dedup is purely algorithmic. After deduplication, no two entries in the entire playbook have cosine similarity >= threshold. Graceful degradation: if deps unavailable, return playbook unmodified (log warning to stderr). | REQ-DEDUP-001, REQ-DEDUP-002, REQ-DEDUP-003, REQ-DEDUP-004, REQ-DEDUP-005, REQ-DEDUP-006, SCN-DEDUP-001-01, SCN-DEDUP-001-02, SCN-DEDUP-001-03, SCN-DEDUP-002-01, SCN-DEDUP-002-02, SCN-DEDUP-003-01, SCN-DEDUP-003-02, SCN-DEDUP-004-01, SCN-DEDUP-005-01, SCN-DEDUP-005-02, SCN-DEDUP-006-01, INV-DEDUP-001, INV-DEDUP-002, INV-DEDUP-003, INV-DEDUP-004, INV-DEDUP-005 |

---

## Requirements

### REQ-DEDUP-001: Cross-Section Semantic Similarity Detection {#REQ-DEDUP-001}
- **Implements**: SC-ACE-001
- **GIVEN**: A playbook dict with key points distributed across multiple sections
- **WHEN**: `run_deduplication(playbook, threshold)` is called
- **THEN**:
  - All key points from ALL sections are collected into a flat list (ignoring section boundaries)
  - Each key point's `text` field is embedded into a vector using a SentenceTransformers model
  - Pairwise cosine similarity is computed across all key points (cross-section, not within-section only)
  - Groups of entries with pairwise cosine similarity >= `threshold` are identified as duplicates
  - The iteration order for building the flat list follows canonical section order (as defined by `SECTION_SLUGS`) and within each section, list order
  - **Model selection**: The specific SentenceTransformers model is an implementation choice. Recommended: `all-MiniLM-L6-v2` (fast, widely used, produces 384-dim embeddings with reasonable cosine similarity distributions for short text). The implementation MAY use any model that produces normalized embeddings compatible with cosine similarity. The 0.85 threshold default was calibrated against short English text (< 50 words per key point); if a model with significantly different similarity distribution is used, the threshold may need adjustment.

### REQ-DEDUP-002: First-Entry-Wins Merge Semantics {#REQ-DEDUP-002}
- **Implements**: SC-ACE-001
- **GIVEN**: A group of duplicate entries identified by REQ-DEDUP-001
- **WHEN**: The group is merged
- **THEN**:
  - The FIRST entry in the group (by iteration order from REQ-DEDUP-001) is the survivor
  - The survivor retains its original `name`, `text`, and section placement
  - The survivor's `helpful` counter becomes the SUM of `helpful` from all entries in the group
  - The survivor's `harmful` counter becomes the SUM of `harmful` from all entries in the group
  - All other entries in the group are removed from their respective sections
  - No LLM call is used to produce merged text -- the survivor's text is preserved unchanged

### REQ-DEDUP-003: Post-Dedup Similarity Guarantee {#REQ-DEDUP-003}
- **Implements**: SC-ACE-001
- **GIVEN**: A playbook after `run_deduplication()` has completed
- **WHEN**: Pairwise cosine similarity is computed across all remaining entries
- **THEN**: No two remaining entries have cosine similarity >= `threshold`
- **NOTE**: This is a postcondition invariant. Transitive duplicates (A similar to B, B similar to C, but A not similar to C) must still result in all three being grouped if connected through the similarity graph.

### REQ-DEDUP-004: Configurable Threshold {#REQ-DEDUP-004}
- **Implements**: SC-ACE-001
- **GIVEN**: The `run_deduplication()` function
- **WHEN**: Called with or without explicit threshold
- **THEN**:
  - Default threshold is `0.85`
  - The `AGENTIC_CONTEXT_DEDUP_THRESHOLD` environment variable, if set, overrides the default (parsed as float)
  - An explicit `threshold` parameter passed to the function takes precedence over both the env var and the default
  - The threshold must be a float in the range `[0.0, 1.0]`; values outside this range are clamped to the nearest bound

### REQ-DEDUP-005: Graceful Degradation When Dependencies Unavailable {#REQ-DEDUP-005}
- **Implements**: SC-ACE-001, QG-ACE-002
- **GIVEN**: `sentence-transformers` (or its dependency `numpy`) is NOT installed in the current Python environment
- **WHEN**: `run_deduplication(playbook)` is called
- **THEN**:
  - The function logs a warning to stderr indicating that deduplication is skipped because dependencies are unavailable
  - The function returns the playbook dict UNMODIFIED (same reference, no mutations)
  - No exception is raised
  - This is the expected behavior for environments without optional ML dependencies

### REQ-DEDUP-006: Deduplication Does Not Affect Empty or Single-Entry Playbooks {#REQ-DEDUP-006}
- **Implements**: SC-ACE-001
- **GIVEN**: A playbook with 0 or 1 total entries across all sections
- **WHEN**: `run_deduplication(playbook)` is called
- **THEN**:
  - The function returns the playbook unmodified
  - No embedding computation or similarity comparison is performed (optimization: skip for trivially non-duplicate cases)

---

## Scenarios

### SCN-DEDUP-001-01: Merge Two Similar Entries in Same Section {#SCN-DEDUP-001-01}
- **Implements**: REQ-DEDUP-001, REQ-DEDUP-002
- **GIVEN**: A playbook with PATTERNS & APPROACHES:
  ```python
  [
      {"name": "pat-001", "text": "always use type hints for function parameters", "helpful": 5, "harmful": 0},
      {"name": "pat-002", "text": "use type hints on all function parameters", "helpful": 3, "harmful": 1}
  ]
  ```
- **AND**: Cosine similarity between `pat-001` and `pat-002` texts is >= 0.85
- **WHEN**: `run_deduplication(playbook, threshold=0.85)` is called
- **THEN**:
  - `pat-001` survives (first entry in iteration order)
  - `pat-001` counters become: `helpful = 5 + 3 = 8`, `harmful = 0 + 1 = 1`
  - `pat-001` text remains `"always use type hints for function parameters"` (unchanged)
  - `pat-002` is removed from PATTERNS & APPROACHES
  - Final section has 1 entry

### SCN-DEDUP-001-02: Merge Entries Across Different Sections {#SCN-DEDUP-001-02}
- **Implements**: REQ-DEDUP-001, REQ-DEDUP-002
- **GIVEN**: A playbook with:
  - PATTERNS & APPROACHES: `[{name: "pat-001", text: "avoid using the any type", helpful: 4, harmful: 0}]`
  - MISTAKES TO AVOID: `[{name: "mis-001", text: "don't use any type in TypeScript", helpful: 2, harmful: 1}]`
- **AND**: Cosine similarity between `pat-001` and `mis-001` texts is >= 0.85
- **WHEN**: `run_deduplication(playbook, threshold=0.85)` is called
- **THEN**:
  - `pat-001` survives (PATTERNS & APPROACHES comes before MISTAKES TO AVOID in canonical order)
  - `pat-001` counters become: `helpful = 4 + 2 = 6`, `harmful = 0 + 1 = 1`
  - `mis-001` is removed from MISTAKES TO AVOID
  - PATTERNS & APPROACHES has 1 entry; MISTAKES TO AVOID has 0 entries

### SCN-DEDUP-001-03: No Merge When Below Threshold {#SCN-DEDUP-001-03}
- **Implements**: REQ-DEDUP-001
- **GIVEN**: A playbook with PATTERNS & APPROACHES:
  ```python
  [
      {"name": "pat-001", "text": "use type hints for parameters", "helpful": 5, "harmful": 0},
      {"name": "pat-002", "text": "prefer composition over inheritance", "helpful": 3, "harmful": 0}
  ]
  ```
- **AND**: Cosine similarity between `pat-001` and `pat-002` texts is < 0.85
- **WHEN**: `run_deduplication(playbook, threshold=0.85)` is called
- **THEN**: Both entries remain unchanged; no merging occurs

### SCN-DEDUP-002-01: Transitive Duplicates Grouped {#SCN-DEDUP-002-01}
- **Implements**: REQ-DEDUP-003
- **GIVEN**: Three entries where:
  - A and B have similarity 0.90 (>= 0.85)
  - B and C have similarity 0.88 (>= 0.85)
  - A and C have similarity 0.80 (< 0.85)
- **WHEN**: `run_deduplication(playbook, threshold=0.85)` is called
- **THEN**: All three are merged into one (A is the survivor, being first in order); after dedup, no two remaining entries have similarity >= 0.85
- **NOTE**: The grouping algorithm must handle transitive relationships through the similarity graph (e.g., union-find or connected components).

### SCN-DEDUP-002-02: Multiple Independent Groups Merged {#SCN-DEDUP-002-02}
- **Implements**: REQ-DEDUP-001, REQ-DEDUP-002
- **GIVEN**: A playbook with 4 entries where entries 1 and 2 are duplicates, entries 3 and 4 are duplicates, but the two groups are not similar to each other
- **WHEN**: `run_deduplication(playbook)` is called
- **THEN**: Both groups are independently merged; result has 2 entries (one survivor from each group)

### SCN-DEDUP-003-01: Graceful Degradation -- Dependencies Missing {#SCN-DEDUP-003-01}
- **Implements**: REQ-DEDUP-005
- **GIVEN**: `sentence-transformers` is not installed (import raises `ImportError`)
- **AND**: A playbook with multiple entries
- **WHEN**: `run_deduplication(playbook)` is called
- **THEN**: Returns the playbook UNMODIFIED (same entries, same counters, same sections)
- **AND**: A warning is logged to stderr
- **AND**: No exception is raised

### SCN-DEDUP-003-02: Graceful Degradation -- Unexpected Exception During Processing {#SCN-DEDUP-003-02}
- **Implements**: INV-DEDUP-001
- **GIVEN**: `sentence-transformers` is installed and imports succeed
- **AND**: A playbook with multiple entries
- **AND**: The SentenceTransformer model's `encode()` call raises a `RuntimeError` (e.g., model file corrupted, out of memory)
- **WHEN**: `run_deduplication(playbook)` is called
- **THEN**: Returns the playbook UNMODIFIED (same reference, no mutations)
- **AND**: The exception details are logged to stderr
- **AND**: No exception is raised to the caller

### SCN-DEDUP-004-01: Environment Variable Overrides Default Threshold {#SCN-DEDUP-004-01}
- **Implements**: REQ-DEDUP-004
- **GIVEN**: `AGENTIC_CONTEXT_DEDUP_THRESHOLD` is set to `"0.90"` in the environment
- **AND**: `run_deduplication(playbook)` is called WITHOUT an explicit `threshold` argument
- **WHEN**: Two entries have cosine similarity 0.87 (below 0.90 but above the default 0.85)
- **THEN**: The entries are NOT merged (threshold is 0.90 from env var)

### SCN-DEDUP-005-01: Empty Playbook -- No-op {#SCN-DEDUP-005-01}
- **Implements**: REQ-DEDUP-006
- **GIVEN**: A playbook with all empty sections
- **WHEN**: `run_deduplication(playbook)` is called
- **THEN**: Returns the playbook unmodified; no embedding computation occurs

### SCN-DEDUP-005-02: Single Entry -- No-op {#SCN-DEDUP-005-02}
- **Implements**: REQ-DEDUP-006
- **GIVEN**: A playbook with exactly one entry total (in any section)
- **WHEN**: `run_deduplication(playbook)` is called
- **THEN**: Returns the playbook unmodified; no embedding computation occurs

### SCN-DEDUP-006-01: Counter Summing During Dedup Merge {#SCN-DEDUP-006-01}
- **Implements**: REQ-DEDUP-002
- **GIVEN**: A playbook with:
  - PATTERNS & APPROACHES: `[{name: "pat-001", text: "always add type hints", helpful: 10, harmful: 2}]`
  - OTHERS: `[{name: "oth-001", text: "remember to add type hints always", helpful: 3, harmful: 0}]`
- **AND**: These two entries have cosine similarity >= 0.85
- **WHEN**: `run_deduplication(playbook)` is called
- **THEN**:
  - `pat-001` survives with `helpful = 10 + 3 = 13`, `harmful = 2 + 0 = 2`
  - `oth-001` is removed from OTHERS
  - `pat-001` text remains `"always add type hints"` (first entry's text preserved)

---

## Invariants

### INV-DEDUP-001: No Crash on Missing Dependencies {#INV-DEDUP-001}
- **Implements**: SC-ACE-001, QG-ACE-002, FM-ACE-006
- **Statement**: `run_deduplication()` never raises an `ImportError` or any other exception to the caller, regardless of whether `sentence-transformers` (and its dependency `numpy`) are installed. When dependencies are unavailable, the function returns the playbook unmodified after logging a warning to stderr. When dependencies are available but an unexpected exception occurs during processing (e.g., model loading failure, encoding error, malformed playbook data), the function also returns the playbook unmodified after logging the exception to stderr.
- **Enforced by**: Import of optional dependencies (`sentence_transformers`, `numpy`) is wrapped in try/except at the top of `run_deduplication()`. The function body checks the availability flag before proceeding. Additionally, the entire function body (post-import-guard) is wrapped in a top-level try/except that catches any unexpected exception, logs the exception details to stderr, and returns the playbook unmodified.

### INV-DEDUP-002: Counter Non-Negativity Preserved Through Dedup Merge {#INV-DEDUP-002}
- **Implements**: SC-ACE-001, INV-SCORE-001, INV-SCORE-002
- **Statement**: The `helpful` and `harmful` counters on a dedup-merged entry are the sum of the corresponding counters from all entries in the duplicate group. Since all source counters are `>= 0`, the summed counters are also `>= 0`.
- **Enforced by**: Dedup merge uses `sum()` of non-negative source values. No subtraction or reset occurs.

### INV-DEDUP-003: Section Names Remain Canonical After Dedup {#INV-DEDUP-003}
- **Implements**: SC-ACE-001, INV-SECT-002
- **Statement**: `run_deduplication()` only removes entries from existing sections. It never creates new sections, renames sections, or moves entries between sections (the survivor stays in its original section).
- **Enforced by**: The function only performs deletion of non-survivor entries from their current sections and counter updates on survivor entries. No section creation or entry relocation occurs.

### INV-DEDUP-004: Post-Dedup No Pair Exceeds Threshold {#INV-DEDUP-004}
- **Implements**: SC-ACE-001, REQ-DEDUP-003
- **Statement**: After `run_deduplication()` completes successfully (dependencies available), no two remaining entries in the playbook have cosine similarity >= the configured threshold.
- **Enforced by**: The grouping algorithm uses connected components (or equivalent) on the similarity graph to ensure all transitively connected duplicates are merged into a single group. The first entry in each group survives; all others are removed.

### INV-DEDUP-005: Playbook Structure Preserved {#INV-DEDUP-005}
- **Implements**: SC-ACE-001, CON-ACE-004
- **Statement**: `run_deduplication()` does not modify the playbook schema. The `{version, last_updated, sections}` top-level structure is preserved. Only the contents of section entry lists are modified (entries removed, counters updated on survivors).
- **Enforced by**: The function operates exclusively on `playbook["sections"][section_name]` lists. No top-level keys are added or removed.

---

## Constraints (from Intent)

| ID | Constraint | Enforced By |
|----|-----------|-------------|
| CON-ACE-004 | Playbook Format Continuity: playbook.json schema unchanged | INV-DEDUP-005 (only section entry lists modified) |
| QG-ACE-002 | No Heavy Dependencies Without Justification: sentence-transformers (which brings numpy) is the only optional dependency | REQ-DEDUP-005, INV-DEDUP-001 (graceful degradation) |
| FM-ACE-003 | Dedup may merge distinct concepts at too-low threshold | REQ-DEDUP-004 (configurable threshold, default conservative at 0.85) |
| FM-ACE-006 | Embedding model load latency on first dedup call | REQ-DEDUP-005 (dedup is optional; model loaded lazily) |
