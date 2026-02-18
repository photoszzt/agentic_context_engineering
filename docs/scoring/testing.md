# Test Strategy: Scoring Module

## Coverage Targets
- Scoring-function line coverage: >= 80% (target applies to these 7 scoring-relevant functions only: `load_playbook`, `save_playbook`, `update_playbook_data`, `format_playbook`, `generate_keypoint_name`, `is_diagnostic_mode`, `save_diagnostic`)
- Branch coverage: >= 70% (scoring functions)
- All REQ-SCORE-* covered by both white-box and contract tests
- All SCN-SCORE-* covered by white-box tests
- All INV-SCORE-* covered by white-box invariant tests
- Contract test coverage: every REQ-SCORE-* must have a contract test OR a documented justification below
- Instrumentation coverage: LOG-SCORE-001 and LOG-SCORE-002 tested via white-box tests

### Coverage Scope Explanation

The tests cover `src/hooks/common.py`, which contains both scoring-relevant functions and non-scoring utility functions that belong to other concerns (session management, transcript loading, LLM API calls). The overall file coverage is **59%** because the non-scoring functions (`load_transcript`, `extract_keypoints`, `load_settings`, `is_first_message`, `mark_session`, `clear_session`, `get_user_claude_dir`, `load_template`) are not exercised by the scoring test suite.

The **scoring-function coverage is 100%** -- all 94 missed statements fall exclusively within non-scoring functions. Zero missed lines exist in the 7 scoring-relevant functions listed above. The >= 80% target is met and exceeded for the in-scope code.

## Intent Traceability

Success criteria from spec.md traceability matrix, mapped to test IDs.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* | Test Type | Test Function |
|------|-------------------|-------------------|-----------|---------------|
| SC-SCORE-001 | Each key point carries `{name, text, helpful, harmful}` schema. `helpful >= 0`, `harmful >= 0`. No `score` field in newly written files. | REQ-SCORE-001 | White-box | test_save_playbook_entry_schema |
| SC-SCORE-001 | (same) | REQ-SCORE-001 | Contract | test_contract_playbook_entry_schema |
| SC-SCORE-001 | (same) | INV-SCORE-001 | White-box | test_invariant_helpful_non_negative |
| SC-SCORE-001 | (same) | INV-SCORE-002 | White-box | test_invariant_harmful_non_negative |
| SC-SCORE-001 | (same) | INV-SCORE-004 | White-box | test_invariant_no_score_field_after_load, test_invariant_no_score_field_after_save |
| SC-SCORE-002 | "helpful" rating increments `helpful` by 1; "harmful" increments `harmful` by 1; "neutral" changes neither counter. | REQ-SCORE-002 | White-box | test_update_helpful_rating, test_update_harmful_rating, test_update_neutral_rating, test_update_unknown_rating, test_update_nonexistent_name |
| SC-SCORE-002 | (same) | REQ-SCORE-002 | Contract | test_contract_helpful_increment, test_contract_harmful_increment, test_contract_neutral_no_change |
| SC-SCORE-002 | (same) | SCN-SCORE-002-01 | White-box | test_scn_helpful_rating_increments_counter |
| SC-SCORE-002 | (same) | SCN-SCORE-002-02 | White-box | test_scn_harmful_rating_increments_counter |
| SC-SCORE-002 | (same) | SCN-SCORE-002-03 | White-box | test_scn_neutral_rating_changes_nothing |
| SC-SCORE-002 | (same) | SCN-SCORE-002-04 | White-box | test_scn_unknown_rating_changes_nothing |
| SC-SCORE-003 | `format_playbook()` outputs `[name] helpful=X harmful=Y :: text` format. | REQ-SCORE-003 | White-box | test_format_playbook_with_counts |
| SC-SCORE-003 | (same) | REQ-SCORE-003 | Contract | test_contract_format_output_structure |
| SC-SCORE-003 | (same) | SCN-SCORE-003-01 | White-box | test_scn_format_includes_counts |
| SC-SCORE-003 | (same) | SCN-SCORE-003-02 | White-box | test_scn_empty_playbook_returns_empty |
| SC-SCORE-004 | `load_playbook()` migrates 3 legacy formats. | REQ-SCORE-004 | White-box | test_load_migrates_bare_string |
| SC-SCORE-004 | (same) | REQ-SCORE-004 | Contract | test_contract_bare_string_migration |
| SC-SCORE-004 | (same) | REQ-SCORE-005 | White-box | test_load_migrates_dict_without_score |
| SC-SCORE-004 | (same) | REQ-SCORE-005 | Contract | test_contract_dict_no_score_migration |
| SC-SCORE-004 | (same) | REQ-SCORE-006 | White-box | test_load_migrates_dict_with_score |
| SC-SCORE-004 | (same) | REQ-SCORE-006 | Contract | test_contract_dict_with_score_migration |
| SC-SCORE-004 | (same) | SCN-SCORE-004-01 | White-box | test_scn_load_bare_string_entry |
| SC-SCORE-004 | (same) | SCN-SCORE-005-01 | White-box | test_scn_load_dict_without_score |
| SC-SCORE-004 | (same) | SCN-SCORE-006-01 | White-box | test_scn_load_dict_with_score_field |
| SC-SCORE-004 | (same) | SCN-SCORE-006-02 | White-box | test_scn_load_dict_with_score_and_counters |
| SC-SCORE-005 | Pruning removes entries where `harmful >= 3 AND harmful > helpful`. Zero-evaluation entries never pruned. | REQ-SCORE-007 | White-box | test_pruning_removes_harmful_entry, test_pruning_retains_helpful_majority, test_pruning_retains_zero_evaluation, test_pruning_retains_below_floor |
| SC-SCORE-005 | (same) | REQ-SCORE-007 | Contract | test_contract_pruning_removes_harmful, test_contract_pruning_retains_helpful |
| SC-SCORE-005 | (same) | INV-SCORE-003 | White-box | test_invariant_zero_evaluation_never_pruned |
| SC-SCORE-005 | (same) | SCN-SCORE-007-01 | White-box | test_scn_prune_consistently_harmful |
| SC-SCORE-005 | (same) | SCN-SCORE-007-02 | White-box | test_scn_retain_high_harmful_higher_helpful |
| SC-SCORE-005 | (same) | SCN-SCORE-007-03 | White-box | test_scn_retain_zero_evaluation |
| SC-SCORE-005 | (same) | SCN-SCORE-007-04 | White-box | test_scn_retain_harmful_below_floor |
| SC-SCORE-006 | `playbook.txt` template updated to explain helpful/harmful semantics. | REQ-SCORE-008 | White-box | test_template_explains_scoring_semantics |
| SC-SCORE-006 | (same) | REQ-SCORE-008 | Contract | test_contract_template_explains_semantics |
| SC-SCORE-006 | (same) | SCN-SCORE-008-01 | White-box | test_scn_template_content |
| (invariant) | Migration round-trip stability. | INV-SCORE-005 | White-box | test_invariant_migration_round_trip_stability |

## Mocking Strategy

### External Dependencies

| Dependency | Mock Approach | Testability Hook |
|------------|---------------|------------------|
| File system (`playbook.json`) | Temp directory via `CLAUDE_PROJECT_DIR` env var | `get_project_dir()` reads `CLAUDE_PROJECT_DIR`. Tests set this env var to a `tmp_path` (pytest fixture). |
| File system (`playbook.txt` template) | Temp directory via monkeypatching `load_template()` OR placing template file in temp dir | `load_template()` reads from `get_user_claude_dir() / "prompts/"`. Tests can monkeypatch `load_template` to return known template content directly, OR monkeypatch `get_user_claude_dir` to point at temp dir. |
| Diagnostic mode (`is_diagnostic_mode()`) | Create/remove `.claude/diagnostic_mode` flag file in temp directory | `is_diagnostic_mode()` checks `get_project_dir() / ".claude" / "diagnostic_mode"`. Tests create the flag file to enable diagnostic mode. |
| Diagnostic output (`save_diagnostic()`) | No mock needed -- reads written file from temp directory | `save_diagnostic()` writes to `get_project_dir() / ".claude" / "diagnostic/"`. Tests read files from this directory to verify content. |
| Time (`datetime.now()`) | Not mocked for unit tests -- only used in `save_playbook()` for `last_updated` and `save_diagnostic()` for filename timestamp. Assertions check field presence, not exact value. | If needed, monkeypatch `datetime` in the module. |
| LLM API (`extract_keypoints()`) | Not relevant to scoring tests | `extract_keypoints()` is not under test in this module. |

### Detailed Mocking Approach Per Function

#### `load_playbook()` (file I/O)
- **Setup**: Create a temp directory, set `CLAUDE_PROJECT_DIR` env var to it, write a `playbook.json` file with the desired legacy format entries.
- **Assertion**: Call `load_playbook()`, inspect the returned dict for canonical schema.
- **Cleanup**: pytest `tmp_path` fixture handles cleanup automatically. Restore env var via monkeypatch.

#### `update_playbook_data()` (pure dict transformation)
- **Setup**: Construct playbook dict and extraction_result dict directly in memory. No file I/O needed.
- **Caveat**: `update_playbook_data()` calls `is_diagnostic_mode()` and `save_diagnostic()` during pruning. For white-box tests that verify pruning behavior only (not diagnostics), set `CLAUDE_PROJECT_DIR` to a temp dir without the diagnostic flag file, so `is_diagnostic_mode()` returns `False` and `save_diagnostic()` is never called.
- **For instrumentation tests**: Create the diagnostic flag file to enable diagnostic mode, then verify diagnostic output files.

#### `format_playbook()` (string formatting with template I/O)
- **Setup**: Construct playbook dict in memory. Monkeypatch `load_template` in `common` module to return a known template string (e.g., `"HEADER\n{key_points}\nFOOTER"`).
- **Assertion**: Call `format_playbook()`, check the returned string for expected format.

#### `save_playbook()` (file I/O)
- **Setup**: Construct playbook dict in memory, set `CLAUDE_PROJECT_DIR` to temp dir.
- **Assertion**: Call `save_playbook()`, read back the written JSON file, verify schema.

#### `is_diagnostic_mode()` / `save_diagnostic()` (file I/O)
- **Setup**: Set `CLAUDE_PROJECT_DIR` to temp dir. Create or omit `.claude/diagnostic_mode` flag file.
- **Assertion for `is_diagnostic_mode()`**: Verify return value matches flag file presence.
- **Assertion for `save_diagnostic()`**: Verify file is written to `.claude/diagnostic/` with expected content.

#### `load_template()` (file I/O)
- **Setup**: Either monkeypatch `get_user_claude_dir()` to point at temp dir and place template file there, or monkeypatch `load_template` directly.
- **Assertion**: Verify returned content matches expected template.

### Contract Test Mocking Approach

Contract tests exercise the public API as documented in contract.md. They use the same temp directory strategy but do NOT inspect internal state, internal function calls, or migration branches.

- **For load + save round-trip**: Write legacy JSON to temp dir, call `load_playbook()`, call `save_playbook()`, read JSON back, verify canonical schema.
- **For update + pruning**: Construct dicts per contract.md schemas, call `update_playbook_data()`, verify output matches contract.
- **For format**: Monkeypatch `load_template`, call `format_playbook()`, verify format string.

## Adversarial Test Categories

### Category 1: Boundary Conditions (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-BOUND-001 | Pruning at exact threshold: `helpful=2, harmful=3` | REQ-SCORE-007 | `harmful >= 3` is True, `harmful > helpful` is True (3 > 2). Entry IS pruned. Boundary of the floor check. |
| TC-BOUND-002 | Pruning just below threshold: `helpful=3, harmful=3` | REQ-SCORE-007 | `harmful >= 3` is True, but `harmful > helpful` is False (3 > 3 is False). Entry is NOT pruned. Tests the `>` vs `>=` distinction. |
| TC-BOUND-003 | Harmful at exact floor: `helpful=0, harmful=3` | REQ-SCORE-007 | `harmful >= 3` is True, `harmful > helpful` is True. Pruned. Minimum harmful count that triggers pruning. |
| TC-BOUND-004 | Harmful one below floor: `helpful=0, harmful=2` | REQ-SCORE-007, SCN-SCORE-007-04 | `harmful >= 3` is False. NOT pruned despite harmful > helpful. |
| TC-BOUND-005 | Score migration edge: `score=0` | REQ-SCORE-006 | `helpful = max(0, 0) = 0`, `harmful = max(0, 0) = 0`. Both zero. |
| TC-BOUND-006 | Score migration edge: `score=1` (positive) | REQ-SCORE-006 | `helpful = 1`, `harmful = 0`. |
| TC-BOUND-007 | Score migration edge: `score=-1` (small negative) | REQ-SCORE-006 | `helpful = 0`, `harmful = 1`. |
| TC-BOUND-008 | Empty key_points list | REQ-SCORE-003, SCN-SCORE-003-02 | `format_playbook()` returns `""`. No entries to format. |
| TC-BOUND-009 | Single entry playbook | REQ-SCORE-003 | Format produces exactly one line. No trailing newline issues. |

### Category 2: Invalid Inputs (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-INVAL-001 | Unrecognized rating string `"bogus"` | REQ-SCORE-002, SCN-SCORE-002-04 | Neither counter changes. Defensive no-op. |
| TC-INVAL-002 | Evaluation references nonexistent key point name | REQ-SCORE-002 | Evaluation is silently ignored. |
| TC-INVAL-003 | Empty evaluation name `""` | REQ-SCORE-002 | Should not match any key point (silently ignored). |
| TC-INVAL-004 | Missing `rating` key in evaluation dict | REQ-SCORE-002 | `eval_item.get("rating", "")` returns `""`, which is unrecognized. No-op. |
| TC-INVAL-005 | Missing `name` key in evaluation dict | REQ-SCORE-002 | `eval_item.get("name", "")` returns `""`, which matches no entry. Silently ignored. |
| TC-INVAL-006 | `playbook.json` file does not exist | REQ-SCORE-001 | `load_playbook()` returns empty playbook `{version: "1.0", last_updated: null, key_points: []}`. |
| TC-INVAL-007 | `playbook.json` contains invalid JSON | REQ-SCORE-001 | `load_playbook()` returns empty playbook (exception handler). |
| TC-INVAL-008 | `playbook.json` missing `key_points` key | REQ-SCORE-001 | `load_playbook()` defaults to `key_points: []`. |
| TC-INVAL-009 | New key point text is empty string | REQ-SCORE-002 | Empty text in `new_key_points` should not be appended (guard: `if text and text not in existing_texts`). |
| TC-INVAL-010 | Duplicate new key point text | REQ-SCORE-002 | Second occurrence of same text should be silently skipped. |

### Category 3: Edge Cases / Migration Corner Cases (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-EDGE-001 | Mixed-format playbook: all 3 legacy types + 1 canonical entry | REQ-SCORE-004, REQ-SCORE-005, REQ-SCORE-006 | A single `playbook.json` containing a bare string, a dict without score, a dict with score, and a dict with helpful/harmful. All should be migrated/preserved correctly. |
| TC-EDGE-002 | Dict with score AND existing helpful/harmful fields | REQ-SCORE-006, SCN-SCORE-006-02 | Canonical fields take precedence; `score` is defensively dropped. |
| TC-EDGE-003 | Dict without `name` field (generated name) | REQ-SCORE-004, REQ-SCORE-005, REQ-SCORE-006 | Name should be auto-generated via `generate_keypoint_name()`. |
| TC-EDGE-004 | Large negative score (e.g., `score=-100`) | REQ-SCORE-006 | `harmful = 100`, `helpful = 0`. Tests that the formula handles extreme values. |
| TC-EDGE-005 | Large positive score (e.g., `score=50`) | REQ-SCORE-006 | `helpful = 50`, `harmful = 0`. |
| TC-EDGE-006 | Pruning after update in same call | REQ-SCORE-007 | An entry at `harmful=2` receives a harmful rating, going to `harmful=3`, and is then pruned in the same `update_playbook_data()` call. |
| TC-EDGE-007 | New key points are never pruned in the same call | REQ-SCORE-007, INV-SCORE-003 | New entries start at `helpful=0, harmful=0`, which fails the `harmful >= 3` floor check. |

### Category 4: Invariant Violations (COVERED)

| TC-* | Test Case | INV-* | Description |
|------|-----------|-------|-------------|
| TC-INV-001 | Helpful counter >= 0 after all migration paths | INV-SCORE-001 | After migrating any legacy format, verify `helpful >= 0`. |
| TC-INV-002 | Harmful counter >= 0 after all migration paths | INV-SCORE-002 | After migrating any legacy format, verify `harmful >= 0`. |
| TC-INV-003 | Zero-evaluation entries never pruned | INV-SCORE-003 | Run pruning on a playbook with only `helpful=0, harmful=0` entries. All must survive. |
| TC-INV-004 | No `score` field after load | INV-SCORE-004 | After `load_playbook()`, no entry has a `score` key. Checked across all migration branches. |
| TC-INV-005 | No `score` field after save | INV-SCORE-004 | After `save_playbook()`, read back JSON and verify no entry has a `score` key. |
| TC-INV-006 | Round-trip stability | INV-SCORE-005 | Load a legacy playbook, save immediately, load again. The `key_points` and `version` fields must be identical between first and second load. `last_updated` is excluded. |

### Category 5: Failure Injection (NOT IN SCOPE)

Resource exhaustion (huge playbooks) and file system failure injection are out of scope for this module. The functions are simple dict transformations and JSON serialization; Python's built-in exception handling covers corrupt files (TC-INVAL-007).

**Summary: 4 of 5 adversarial categories covered (Boundary, Invalid Input, Edge Cases, Invariant Violations).**

## Instrumentation Test Strategy

The scoring module uses file-based diagnostics (not metrics or structured logging). Instrumentation tests verify that `save_diagnostic()` is called at the right times and with the right content.

### Diagnostic Mocking Approach

| Component | Mock Approach | Verification |
|-----------|---------------|-------------|
| `is_diagnostic_mode()` | Create/remove `.claude/diagnostic_mode` flag file in temp directory controlled by `CLAUDE_PROJECT_DIR` | Check return value of `is_diagnostic_mode()` |
| `save_diagnostic()` | No mock -- verify actual files written to `{tmp_dir}/.claude/diagnostic/` | Read diagnostic file content, assert expected fields present |

### LOG-SCORE-001: Migration Diagnostic

| Test Function | Scenario | Verification |
|---------------|----------|-------------|
| test_instrumentation_migration_diagnostic_created | Diagnostic mode enabled + legacy entries present | A file matching `*_playbook_migration.txt` exists in `.claude/diagnostic/`. Content includes count of migrated entries and per-entry details (name, source format, original score). |
| test_instrumentation_migration_diagnostic_not_created_when_disabled | Diagnostic mode disabled + legacy entries present | No `*_playbook_migration.txt` file exists in `.claude/diagnostic/`. |
| test_instrumentation_migration_diagnostic_not_created_when_no_migration | Diagnostic mode enabled + all entries already canonical | No `*_playbook_migration.txt` file exists (no migration occurred). |

### LOG-SCORE-002: Pruning Diagnostic

| Test Function | Scenario | Verification |
|---------------|----------|-------------|
| test_instrumentation_pruning_diagnostic_created | Diagnostic mode enabled + at least one entry pruned | A file matching `*_playbook_pruning.txt` exists in `.claude/diagnostic/`. Content includes: count of pruned entries, per-entry `name`, truncated `text` (up to 80 chars), `helpful` count, `harmful` count, reason string. |
| test_instrumentation_pruning_diagnostic_not_created_when_disabled | Diagnostic mode disabled + entries would be pruned | No `*_playbook_pruning.txt` file exists. |
| test_instrumentation_pruning_diagnostic_not_created_when_no_pruning | Diagnostic mode enabled + no entries meet pruning condition | No `*_playbook_pruning.txt` file exists. |
| test_instrumentation_pruning_text_truncated | Diagnostic mode enabled + pruned entry has text > 80 chars | Diagnostic file content contains the `text` truncated to 80 characters. |

## Contract Test Exclusions

The following REQ-* are covered by contract tests, but some aspects require white-box testing only.

| REQ-* | Contract Test? | Notes |
|-------|---------------|-------|
| REQ-SCORE-001 | YES | Contract test verifies schema of entries via load/save round-trip. |
| REQ-SCORE-002 | YES | Contract test verifies counter increments via `update_playbook_data()` input/output. |
| REQ-SCORE-003 | YES | Contract test verifies format string structure. Requires monkeypatching `load_template` since template file is external dependency. |
| REQ-SCORE-004 | YES | Contract test writes legacy JSON, calls `load_playbook()`, verifies output schema. |
| REQ-SCORE-005 | YES | Same approach as REQ-SCORE-004. |
| REQ-SCORE-006 | YES | Same approach as REQ-SCORE-004. |
| REQ-SCORE-007 | YES | Contract test constructs playbook and extraction_result, calls `update_playbook_data()`, verifies retained/removed entries. |
| REQ-SCORE-008 | YES | Contract test verifies template content contains required semantic phrases. Requires reading the template file or monkeypatching. |

All REQ-SCORE-* have contract tests. No exclusions needed.

## Test Types

| Type | When to Use |
|------|-------------|
| Unit / White-box tests | Individual functions with known internal logic. Can inspect migration branches, internal state, invariants. |
| Contract / Black-box tests | Exercise public API as documented in contract.md. No knowledge of internal branching or implementation details. |
| **Deliverable tests** | **Exercise the end-to-end flow as a user would: write a legacy playbook file, run the full load-update-save-format cycle, verify the output is correct.** |

### Deliverable Test Strategy

A deliverable test exercises the full lifecycle:
1. Write a legacy `playbook.json` to temp dir (simulating pre-migration state).
2. Call `load_playbook()` (migration runs).
3. Call `update_playbook_data()` with evaluations (counters update, pruning runs).
4. Call `save_playbook()` (writes canonical JSON).
5. Call `load_playbook()` again (verify round-trip stability).
6. Call `format_playbook()` (verify output format includes counts).

This catches integration failures between functions that unit tests might miss (e.g., `update_playbook_data()` expects `score` field that `load_playbook()` dropped).

These deliverable tests are included in the contract test file as `test_contract_full_lifecycle_*` functions.

## Test File Organization

| File | Purpose | Location |
|------|---------|----------|
| `tests/test_scoring_whitebox.py` | White-box tests covering all REQ-*, INV-*, SCN-*, LOG-* + adversarial tests | `/data/agentic_context_engineering/tests/test_scoring_whitebox.py` |
| `tests/test_scoring_contract.py` | Contract/black-box tests covering all REQ-* + deliverable tests | `/data/agentic_context_engineering/tests/test_scoring_contract.py` |

Note: The project does not currently have a `tests/` directory. One will be created in Phase 2. The test files use pytest conventions (`test_` prefix). The `src/hooks/common.py` module is imported directly.

### File Headers

White-box test file:
```python
# Spec: docs/scoring/spec.md
# Testing: docs/scoring/testing.md
```

Contract test file:
```python
# Spec: docs/scoring/spec.md
# Contract: docs/scoring/contract.md
# Testing: docs/scoring/testing.md
```

## Failure Mode Coverage

Mapping failure modes from intent.md to test cases.

| FM-* | Failure Mode | Mitigated By | Test Functions |
|------|-------------|-------------|----------------|
| FM-SCORE-001 | Old playbook with `score` causes KeyError | SC-SCORE-004 | test_load_migrates_dict_with_score, test_contract_dict_with_score_migration |
| FM-SCORE-002 | Zero-evaluation entries pruned incorrectly | SC-SCORE-005 | test_invariant_zero_evaluation_never_pruned, test_scn_retain_zero_evaluation |
| FM-SCORE-003 | `format_playbook()` still outputs old format | SC-SCORE-003 | test_scn_format_includes_counts, test_contract_format_output_structure |
| FM-SCORE-004 | reflection.txt expects old schema | A1 (unchanged) | Out of scope -- reflection.txt is not modified |
| FM-SCORE-005 | Migration produces negative counters | SC-SCORE-004 | test_invariant_helpful_non_negative, test_invariant_harmful_non_negative |
| FM-SCORE-006 | Save + re-load produces different state | CON-SCORE-002 | test_invariant_migration_round_trip_stability, test_contract_full_lifecycle_round_trip |
| FM-SCORE-007 | Pruning too aggressive or too lenient | SC-SCORE-005 | TC-BOUND-001 through TC-BOUND-004, test_scn_prune_consistently_harmful, test_scn_retain_high_harmful_higher_helpful |
| FM-SCORE-008 | Template does not explain semantics | SC-SCORE-006 | test_scn_template_content, test_contract_template_explains_semantics |
| FM-SCORE-009 | Migrated entries with inflated harmful get pruned | Accepted trade-off | test_load_migrates_dict_with_score (verifies formula); pruning behavior on migrated entries is tested via TC-EDGE-006 |

## Verification Plan (Phase 2 Checklist)

Before claiming Phase 2 COMPLETE, the following must pass:

1. `pytest tests/test_scoring_whitebox.py tests/test_scoring_contract.py -v` -- all tests pass
2. `pytest tests/test_scoring_whitebox.py tests/test_scoring_contract.py --cov=src/hooks/common --cov-report=term-missing` -- scoring-function coverage >= 80%. **Scope limitation:** The overall file coverage will report ~59% because `src/hooks/common.py` contains non-scoring functions (`load_transcript`, `extract_keypoints`, `load_settings`, `is_first_message`, `mark_session`, `clear_session`, `get_user_claude_dir`, `load_template`) that are outside the scoring module's test scope. Verify that all missed lines in the `term-missing` output fall within these non-scoring functions and that zero missed lines fall within the 7 scoring-relevant functions: `load_playbook`, `save_playbook`, `update_playbook_data`, `format_playbook`, `generate_keypoint_name`, `is_diagnostic_mode`, `save_diagnostic`.
3. Break-the-code verification: comment out a critical line (e.g., the `max()` in score migration), run tests, verify failure
4. Every `@tests` annotation references a valid REQ-*/SCN-*/INV-* from spec.md
5. Every `@tests-contract` annotation references a valid REQ-* from spec.md
6. Every `@tests-invariant` annotation references a valid INV-* from spec.md
7. Every `@tests-instrumentation` annotation references a valid LOG-* from observability.md
8. No `pytest.skip()` or `@pytest.mark.skip` anywhere
