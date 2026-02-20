# Test Strategy: Curator Operations Module

## Coverage Targets
- Curator-function line coverage: >= 80% (target applies to curator-specific code paths within `update_playbook_data()` and the new `_apply_curator_operations()` function)
- Branch coverage: >= 70% (curator functions)
- All REQ-CUR-* covered by both white-box and contract tests
- All SCN-CUR-* covered by white-box tests
- All INV-CUR-* covered by white-box invariant tests
- Contract test coverage: every REQ-CUR-* must have a contract test OR a documented justification below
- Instrumentation coverage: LOG-CUR-001, LOG-CUR-002, LOG-CUR-003 tested via white-box tests

### Coverage Scope Explanation

The tests cover `src/hooks/common.py`, which contains curator-relevant functions as well as scoring, sections, session management, transcript loading, and LLM API call functions. The overall file coverage will be lower than 80% because non-curator functions are not exercised by the curator test suite.

The >= 80% target applies only to the curator-relevant code paths:
- `_apply_curator_operations()` (new function -- 100% coverage expected)
- `update_playbook_data()` operations branch (the `if "operations" in extraction_result` path)
- `extract_keypoints()` operations extraction (the `if "operations" in result and isinstance(result["operations"], list)` guard)

Pre-existing functions covered by scoring/sections tests (`load_playbook`, `save_playbook`, `format_playbook`, `generate_keypoint_name`, `_resolve_section`, `is_diagnostic_mode`, `save_diagnostic`) are exercised as dependencies but are not the primary coverage target. Verify that all missed lines in `--cov-report=term-missing` output fall within non-curator functions, and that zero missed lines fall within `_apply_curator_operations()` or the operations branch of `update_playbook_data()`.

---

## Intent Traceability

Success criteria from spec.md traceability matrix, mapped to test IDs.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* | Test Type | Test Function |
|------|-------------------|-------------------|-----------|---------------|
| SC-CUR-001 | extract_keypoints returns structured operations | REQ-CUR-001 | White-box | test_extract_keypoints_returns_operations |
| SC-CUR-001 | (same) | REQ-CUR-001 | Contract | test_contract_extraction_includes_operations |
| SC-CUR-001 | (same) | SCN-CUR-001-01 | White-box | test_scn_extract_operations_present |
| SC-CUR-001 | (same) | SCN-CUR-001-02 | White-box | test_scn_extract_empty_operations |
| SC-CUR-001 | (same) | SCN-CUR-001-03 | White-box | test_scn_extract_no_operations_key |
| SC-CUR-001 | (same) | SCN-CUR-001-04 | White-box | test_scn_extract_non_list_operations |
| SC-CUR-002 | ADD operation creates new entry | REQ-CUR-002 | White-box | test_add_creates_entry_in_target_section |
| SC-CUR-002 | (same) | REQ-CUR-002 | Contract | test_contract_add_operation |
| SC-CUR-002 | (same) | SCN-CUR-002-01 | White-box | test_scn_add_creates_entry_in_target_section |
| SC-CUR-002 | (same) | SCN-CUR-002-02 | White-box | test_scn_add_defaults_to_others |
| SC-CUR-002 | (same) | SCN-CUR-002-03 | White-box | test_scn_add_skips_duplicate_text |
| SC-CUR-002 | (same) | SCN-CUR-002-04 | White-box | test_scn_add_skips_empty_text |
| SC-CUR-002 | (same) | SCN-CUR-002-05 | White-box | test_scn_add_resolves_section_case_insensitive |
| SC-CUR-003 | MERGE combines entries | REQ-CUR-003 | White-box | test_merge_combines_two_entries |
| SC-CUR-003 | (same) | REQ-CUR-003 | Contract | test_contract_merge_operation |
| SC-CUR-003 | (same) | SCN-CUR-003-01 | White-box | test_scn_merge_combines_two_entries |
| SC-CUR-003 | (same) | SCN-CUR-003-02 | White-box | test_scn_merge_explicit_section_override |
| SC-CUR-003 | (same) | SCN-CUR-003-03 | White-box | test_scn_merge_some_nonexistent_source_ids |
| SC-CUR-003 | (same) | SCN-CUR-003-04 | White-box | test_scn_merge_skipped_fewer_than_2_valid |
| SC-CUR-003 | (same) | SCN-CUR-003-05 | White-box | test_scn_merge_skipped_source_ids_fewer_than_2 |
| SC-CUR-003 | (same) | SCN-CUR-003-06 | White-box | test_scn_merge_inherits_section_from_first_valid |
| SC-CUR-003 | (same) | SCN-CUR-003-07 | White-box | test_scn_merge_first_source_deleted_by_prior_op |
| SC-CUR-003 | (same) | SCN-CUR-003-08 | White-box | test_scn_merge_all_source_ids_nonexistent |
| SC-CUR-004 | DELETE removes entry | REQ-CUR-004 | White-box | test_delete_removes_entry |
| SC-CUR-004 | (same) | REQ-CUR-004 | Contract | test_contract_delete_operation |
| SC-CUR-004 | (same) | SCN-CUR-004-01 | White-box | test_scn_delete_removes_entry |
| SC-CUR-004 | (same) | SCN-CUR-004-02 | White-box | test_scn_delete_skips_nonexistent_id |
| SC-CUR-004 | (same) | SCN-CUR-004-03 | White-box | test_scn_delete_empty_target_id |
| SC-CUR-005 | Sequential processing order | REQ-CUR-005 | White-box | test_sequential_processing_order |
| SC-CUR-005 | (same) | REQ-CUR-005 | Contract | test_contract_sequential_processing |
| SC-CUR-005 | (same) | SCN-CUR-005-01 | White-box | test_scn_delete_before_merge |
| SC-CUR-005 | (same) | SCN-CUR-005-02 | White-box | test_scn_add_then_merge_referencing_new_entry |
| SC-CUR-005 | Deep copy atomicity and rollback | REQ-CUR-006 | White-box | test_rollback_on_exception |
| SC-CUR-005 | (same) | REQ-CUR-006 | Contract | test_contract_rollback_on_exception |
| SC-CUR-005 | (same) | SCN-CUR-005-03 | White-box | test_scn_exception_rollback_returns_original |
| SC-CUR-005 | (same) | SCN-CUR-005-04 | White-box | test_scn_skipped_ops_do_not_trigger_rollback |
| SC-CUR-005 | (same) | INV-CUR-001 | White-box | test_invariant_deep_copy_isolation |
| SC-CUR-005 | (same) | INV-CUR-002 | White-box | test_invariant_no_crash_on_invalid_operations |
| SC-CUR-006 | Updated prompt structure | REQ-CUR-007 | White-box | test_prompt_includes_operations_instructions |
| SC-CUR-006 | (same) | REQ-CUR-007 | Contract | test_contract_prompt_structure |
| SC-CUR-006 | (same) | SCN-CUR-007-01 | White-box | test_scn_prompt_includes_entry_ids_and_examples |
| SC-CUR-007 | Operations vs new_key_points precedence | REQ-CUR-008 | White-box | test_operations_suppress_new_key_points |
| SC-CUR-007 | (same) | REQ-CUR-008 | Contract | test_contract_operations_precedence |
| SC-CUR-007 | (same) | SCN-CUR-008-01 | White-box | test_scn_operations_key_present_nkp_ignored |
| SC-CUR-007 | (same) | SCN-CUR-008-02 | White-box | test_scn_operations_key_absent_nkp_used |
| SC-CUR-007 | (same) | SCN-CUR-008-03 | White-box | test_scn_empty_operations_list_nkp_still_ignored |
| (validation) | Operations validation and truncation | REQ-CUR-009 | White-box | test_operations_truncated_to_10 |
| (validation) | (same) | REQ-CUR-009 | Contract | test_contract_operations_validation |
| (validation) | (same) | SCN-CUR-009-01 | White-box | test_scn_operations_truncated_15_to_10 |
| (validation) | (same) | SCN-CUR-009-02 | White-box | test_scn_unknown_operation_type_skipped |
| (validation) | (same) | SCN-CUR-009-03 | White-box | test_scn_exactly_10_operations_no_truncation |
| (validation) | (same) | SCN-CUR-009-04 | White-box | test_scn_exactly_11_operations_truncation |
| (invariant) | Counter non-negativity through MERGE | INV-CUR-003 | White-box | test_invariant_counter_non_negativity_through_merge |
| (invariant) | Section names canonical after operations | INV-CUR-004 | White-box | test_invariant_section_names_canonical_after_ops |
| (invariant) | Operations bounded by max 10 | INV-CUR-005 | White-box | test_invariant_operations_bounded_to_10 |
| (invariant) | Precedence prevents double-processing | INV-CUR-006 | White-box | test_invariant_precedence_prevents_double_processing |

---

## Mocking Strategy

### External Dependencies

| Dependency | Mock Approach | Testability Hook |
|------------|---------------|------------------|
| File system (`playbook.json`) | Temp directory via `CLAUDE_PROJECT_DIR` env var | `get_project_dir()` reads `CLAUDE_PROJECT_DIR`. Tests set this env var to a `tmp_path` (pytest fixture). |
| Diagnostic mode (`is_diagnostic_mode()`) | Create/remove `.claude/diagnostic_mode` flag file in temp directory | `is_diagnostic_mode()` checks `get_project_dir() / ".claude" / "diagnostic_mode"`. Tests create the flag file to enable diagnostic mode for instrumentation tests. |
| Diagnostic output (`save_diagnostic()`) | No mock needed -- reads written file from temp directory | `save_diagnostic()` writes to `get_project_dir() / ".claude" / "diagnostic/"`. Tests read files from this directory to verify content. |
| `generate_keypoint_name()` | Real function (no mock) | Used as-is. Tests verify generated names match expected `{slug}-NNN` format. This is a pure function with no side effects -- mocking would reduce test fidelity. |
| `_resolve_section()` | Real function (no mock) | Used as-is. Section resolution is a pure function. Tests verify correct section assignment by checking which section contains the new entry. |
| `copy.deepcopy()` | Real function (no mock) | Used as-is. Deep copy is fundamental to atomicity (INV-CUR-001). Mocking it would defeat the invariant under test. |
| `_apply_curator_operations()` | Monkeypatch (for rollback test only) | For SCN-CUR-005-03, monkeypatch `_apply_curator_operations` to raise `RuntimeError("injected failure")` when called. This tests the try/except rollback path in `update_playbook_data()`. |
| LLM API (`extract_keypoints()`) | Mock Anthropic client via monkeypatch | For REQ-CUR-001 (extraction tests), mock the Anthropic client to return pre-constructed JSON responses. Same pattern as `_setup_extract_keypoints_mocks()` in existing test files. Set `mock_text_block.text` to include `"operations"` key in the JSON response. |
| `load_template()` | Monkeypatch to return known template string | For REQ-CUR-007 (prompt tests), either read the actual `reflection.txt` template to verify content, or monkeypatch `load_template` for unit tests that need controlled template content. |

### Detailed Mocking Approach Per Test Area

#### `update_playbook_data()` operations path (core curator tests)

- **Setup**: Construct a sections-based `playbook` dict and an `extraction_result` dict with the desired `operations` list directly in memory. No file I/O needed for the core logic.
- **Pattern**: Same as existing scoring/sections tests. Call `update_playbook_data(playbook, extraction_result)`, assert the returned playbook matches expected state.
- **Diagnostic gating**: For non-instrumentation tests, set `CLAUDE_PROJECT_DIR` to a temp dir without the diagnostic flag file so `is_diagnostic_mode()` returns `False` and `save_diagnostic()` is never called. For instrumentation tests, create the flag file.

#### `extract_keypoints()` operations extraction (REQ-CUR-001)

- **Setup**: Mock the Anthropic client to return a JSON response that includes `"operations"` key. Use the `_setup_extract_keypoints_mocks()` helper pattern from existing tests.
- **Pattern**: Override `mock_text_block.text` with the desired JSON string containing operations. Call `extract_keypoints()`, verify the returned dict includes `"operations"`.
- **Variants**: Test with operations present (SCN-CUR-001-01), empty operations (SCN-CUR-001-02), no operations key (SCN-CUR-001-03), non-list operations value (SCN-CUR-001-04).

#### `_apply_curator_operations()` monkeypatch for rollback (SCN-CUR-005-03)

- **Setup**: Monkeypatch `_apply_curator_operations` in the `src.hooks.common` module to raise `RuntimeError("injected failure")`.
- **Pattern**: Call `update_playbook_data()` with a valid operations list. The try/except in `update_playbook_data()` catches the exception and returns the original playbook.
- **Assertion**: The returned playbook is unchanged from the original. Verify specific entry values to confirm no partial mutations leaked.

#### Reflection template verification (REQ-CUR-007)

- **Approach**: Read the actual `reflection.txt` template file from disk and verify it contains the required operation instructions. This is a content test, not a mock test.
- **Fallback**: If the template path is not easily determinable in tests, monkeypatch `load_template` and verify the test expectation against the real template content separately.

### Contract Test Mocking Approach

Contract tests exercise the public API as documented in contract.md. They use the same in-memory dict construction approach but do NOT inspect internal state, internal function calls, or implementation details.

- **For operations processing**: Construct playbook and extraction_result per contract.md schemas, call `update_playbook_data()`, verify output matches contract.
- **For precedence**: Construct extraction_result with both `operations` and `new_key_points`, verify only operations path executes.
- **For rollback**: Monkeypatch `_apply_curator_operations` to raise, verify original playbook returned.

---

## Test Types

| Type | When to Use |
|------|-------------|
| Unit / White-box tests | Individual functions with known internal logic. Can inspect operation dispatch branches, counter summing internals, skip reasons, diagnostic output content. |
| Contract / Black-box tests | Exercise public API as documented in contract.md. No knowledge of internal branching or implementation details. |
| **Deliverable tests** | **Exercise the end-to-end operations flow as a user would: construct a playbook, apply a batch of operations (ADD + MERGE + DELETE), verify the final playbook state, then verify backward compat with old-format extraction results.** |

### Deliverable Test Strategy

A deliverable test exercises the full curator lifecycle:
1. Construct a sections-based playbook with entries across multiple sections.
2. Construct an extraction_result with a mixed operations list (ADD, MERGE, DELETE) and evaluations.
3. Call `update_playbook_data(playbook, extraction_result)`.
4. Verify: ADD created new entry in correct section with generated ID.
5. Verify: MERGE created merged entry with summed counters, removed sources.
6. Verify: DELETE removed target entry.
7. Verify: Evaluations still applied (counters incremented on surviving entries).
8. Verify: Pruning still runs after operations.

A second deliverable test exercises backward compatibility:
1. Construct a playbook.
2. Construct an extraction_result with `new_key_points` (no `operations` key).
3. Call `update_playbook_data()`, verify entries added via legacy path.

These deliverable tests are included in the contract test file as `test_contract_full_lifecycle_*` functions.

---

## Adversarial Test Categories

### Category 1: Invalid Inputs (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-INVAL-001 | ADD with empty `text` | REQ-CUR-002, SCN-CUR-002-04 | Operation skipped. No entry created. |
| TC-INVAL-002 | ADD with `text: None` (not a string) | REQ-CUR-002, REQ-CUR-009 | Operation skipped. Validates `isinstance(text, str)` check. |
| TC-INVAL-003 | ADD with missing `text` key entirely | REQ-CUR-002, REQ-CUR-009 | `op.get("text", "")` returns `""`. Skipped. |
| TC-INVAL-004 | MERGE with `source_ids` as single string (not list) | REQ-CUR-003, REQ-CUR-009 | `isinstance(source_ids, list)` fails. Skipped. |
| TC-INVAL-005 | MERGE with `source_ids` containing 1 entry | REQ-CUR-003, SCN-CUR-003-05 | `len(source_ids) < 2`. Skipped. |
| TC-INVAL-006 | MERGE with empty `merged_text` | REQ-CUR-003, REQ-CUR-009 | Skipped (validation failure). |
| TC-INVAL-007 | DELETE with empty `target_id` | REQ-CUR-004, SCN-CUR-004-03 | Skipped (validation failure). |
| TC-INVAL-008 | DELETE with `target_id: None` | REQ-CUR-004, REQ-CUR-009 | `isinstance(target_id, str)` fails. Skipped. |
| TC-INVAL-009 | Unknown `type` value `"UPDATE"` | REQ-CUR-009, SCN-CUR-009-02 | Skipped with diagnostic log. |
| TC-INVAL-010 | Missing `type` key entirely | REQ-CUR-009, SCN-CUR-009-02 | `op.get("type", "")` returns `""`. Falls through to else branch. Skipped. |
| TC-INVAL-011 | Operation is not a dict (e.g., string `"ADD"`) | REQ-CUR-009, INV-CUR-002 | `op.get("type", "")` raises AttributeError if op is not a dict. Test that this does not crash `update_playbook_data()` (caught by try/except rollback). |
| TC-INVAL-012 | `operations` value is `null` in LLM response | REQ-CUR-001, SCN-CUR-001-04 | `isinstance(result["operations"], list)` is False. Operations key not included in extraction result. |
| TC-INVAL-013 | `operations` value is a string in LLM response | REQ-CUR-001, SCN-CUR-001-04 | Same as TC-INVAL-012 but with string value. |
| TC-INVAL-014 | `operations` value is an integer in LLM response | REQ-CUR-001, SCN-CUR-001-04 | Same as TC-INVAL-012 but with integer value. |
| TC-INVAL-015 | MERGE with `source_ids: []` (empty list) | REQ-CUR-003, REQ-CUR-009 | `len(source_ids) < 2`. Skipped. |
| TC-INVAL-016 | ADD with `text: "   "` (whitespace-only) | REQ-CUR-002, REQ-CUR-009 | `text.strip()` is empty. Skipped. |

### Category 2: Boundary Conditions (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-BOUND-001 | Exactly 10 operations (no truncation) | REQ-CUR-009, SCN-CUR-009-03, INV-CUR-005 | All 10 processed. No truncation diagnostic emitted. |
| TC-BOUND-002 | Exactly 11 operations (truncation to 10) | REQ-CUR-009, SCN-CUR-009-04, INV-CUR-005 | Only first 10 processed. Truncation diagnostic emitted. |
| TC-BOUND-003 | 15 operations (truncation) | REQ-CUR-009, SCN-CUR-009-01 | Only first 10 processed. |
| TC-BOUND-004 | Empty operations list `[]` | REQ-CUR-008, SCN-CUR-008-03 | No deep copy created (optimization). No operations processed. `new_key_points` still ignored. |
| TC-BOUND-005 | Single source_id in MERGE | REQ-CUR-003, SCN-CUR-003-05 | Validation failure: `len < 2`. Skipped. |
| TC-BOUND-006 | MERGE with exactly 2 valid source_ids (minimum valid) | REQ-CUR-003, SCN-CUR-003-01 | MERGE proceeds successfully. |
| TC-BOUND-007 | MERGE with 3 source_ids where 1 is non-existent (2 remain) | REQ-CUR-003, SCN-CUR-003-03 | Filters to 2 valid. MERGE proceeds. |
| TC-BOUND-008 | MERGE with 3 source_ids where 2 are non-existent (1 remains) | REQ-CUR-003, SCN-CUR-003-04 | Fewer than 2 valid. MERGE skipped. Source entries NOT removed. |
| TC-BOUND-009 | MERGE with ALL source_ids non-existent | REQ-CUR-003, SCN-CUR-003-08 | 0 valid. MERGE skipped. Playbook unchanged. |
| TC-BOUND-010 | DELETE text truncation in diagnostic (entry text > 80 chars) | REQ-CUR-004, LOG-CUR-003 | Diagnostic contains text truncated to 80 characters. |

### Category 3: Concurrency / Ordering (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-ORD-001 | DELETE before MERGE in same batch | REQ-CUR-005, SCN-CUR-005-01 | MERGE does not find deleted entry. Sequential semantics verified. |
| TC-ORD-002 | ADD then MERGE referencing new entry | REQ-CUR-005, SCN-CUR-005-02 | MERGE references entry created by prior ADD. Sequential semantics allow this. |
| TC-ORD-003 | DELETE first source_id, MERGE with remaining | REQ-CUR-005, SCN-CUR-003-07 | First source deleted by prior op. MERGE inherits section from second valid source. |
| TC-ORD-004 | ADD duplicate text then ADD same text again | REQ-CUR-002 | First ADD succeeds. Second ADD skipped (duplicate). Sequential dedup. |
| TC-ORD-005 | DELETE then ADD same text | REQ-CUR-005 | DELETE removes entry; ADD can re-add same text (it was removed, no longer in existing_texts). |

### Category 4: Data Integrity (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-INTEG-001 | MERGE counter summing: 3 entries with various counts | REQ-CUR-003, INV-CUR-003 | Merged entry `helpful = sum(sources)`, `harmful = sum(sources)`. Non-negative. |
| TC-INTEG-002 | ADD dedup across sections | REQ-CUR-002, SCN-CUR-002-03 | Text exists in OTHERS, ADD targets PATTERNS. Skipped (dedup checks all sections). |
| TC-INTEG-003 | Atomicity rollback on exception | REQ-CUR-006, INV-CUR-001, SCN-CUR-005-03 | Monkeypatch `_apply_curator_operations` to raise. Original playbook returned unchanged. |
| TC-INTEG-004 | Deep copy isolation: original not mutated | INV-CUR-001 | After successful operations, verify original playbook dict passed to `update_playbook_data()` was not mutated. |
| TC-INTEG-005 | Section names remain canonical after all operations | INV-CUR-004 | After a mix of ADD/MERGE/DELETE, all section keys are still in the canonical set from `SECTION_SLUGS`. |
| TC-INTEG-006 | New ADD entries have `helpful=0, harmful=0` | REQ-CUR-002 | Verify schema of newly created entries. |
| TC-INTEG-007 | MERGE creates entry with correct schema | REQ-CUR-003 | Merged entry has `name`, `text`, `helpful`, `harmful` keys. |
| TC-INTEG-008 | DELETE reason not stored in playbook | REQ-CUR-004 | After DELETE, no entry in playbook contains the reason string. |

### Category 5: Integration / Backward Compatibility (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-COMPAT-001 | Old format: `new_key_points` only (no `operations` key) | REQ-CUR-008, SCN-CUR-008-02 | Falls back to `new_key_points` path. Entries added to OTHERS. |
| TC-COMPAT-002 | Both `operations` and `new_key_points` present | REQ-CUR-008, SCN-CUR-008-01, INV-CUR-006 | Only operations processed. `new_key_points` ignored. |
| TC-COMPAT-003 | Empty `operations: []` with `new_key_points` present | REQ-CUR-008, SCN-CUR-008-03 | Operations key present (even though empty). `new_key_points` ignored. No entries added. |
| TC-COMPAT-004 | Evaluations still work after operations | REQ-CUR-005 | Operations applied, then evaluations update counters on surviving entries. |
| TC-COMPAT-005 | Pruning still runs after operations | REQ-CUR-006 | A merged entry with high harmful count gets pruned in same cycle. |
| TC-COMPAT-006 | MERGE then evaluation on merged entry | REQ-CUR-003, REQ-CUR-005 | MERGE creates entry with new name. Evaluation in same cycle can reference the new name. (Note: evaluations come from the same extraction, so the LLM would need to know the new name. In practice this is unlikely since the LLM cannot predict the generated name. This test verifies that evaluations do not crash on unknown names.) |
| TC-COMPAT-007 | Full lifecycle: load playbook, apply operations, save, reload | INV-CUR-001 | End-to-end round-trip stability. |

**Summary: 5 of 5 adversarial categories covered (Invalid Inputs, Boundary Conditions, Ordering, Data Integrity, Backward Compatibility).**

---

## Invariant Test Coverage

| INV-* | Invariant | Test Function | Verification |
|-------|-----------|---------------|-------------|
| INV-CUR-001 | Deep copy isolation | test_invariant_deep_copy_isolation | After `update_playbook_data()` with operations, verify the original playbook dict was not mutated. Also: monkeypatch `_apply_curator_operations` to raise, verify original returned unchanged. |
| INV-CUR-002 | No crash on invalid operations | test_invariant_no_crash_on_invalid_operations | Pass a batch of malformed operations (empty text, missing type, non-existent IDs, unknown type, non-dict operation). Verify `update_playbook_data()` returns without raising. All invalid ops skipped. |
| INV-CUR-003 | Counter non-negativity through MERGE | test_invariant_counter_non_negativity_through_merge | MERGE 3 entries with `helpful={2,3,5}`, `harmful={0,1,0}`. Merged entry: `helpful=10`, `harmful=1`. Both >= 0. |
| INV-CUR-004 | Section names canonical after operations | test_invariant_section_names_canonical_after_ops | After ADD to "mistakes to avoid" (lowercase) and MERGE with explicit section, all keys in `playbook["sections"]` are in `SECTION_SLUGS`. |
| INV-CUR-005 | Operations bounded to max 10 | test_invariant_operations_bounded_to_10 | Pass 20 ADD operations. Verify only 10 entries created. |
| INV-CUR-006 | Precedence prevents double-processing | test_invariant_precedence_prevents_double_processing | Pass extraction with both `operations` (1 ADD) and `new_key_points` (1 entry). Verify only 1 entry created (from operations), not 2. |

---

## Instrumentation Test Strategy

The curator module uses file-based diagnostics (not metrics or structured logging). Instrumentation tests verify that `save_diagnostic()` is called at the right times and with the right content.

### Diagnostic Mocking Approach

| Component | Mock Approach | Verification |
|-----------|---------------|-------------|
| `is_diagnostic_mode()` | Create/remove `.claude/diagnostic_mode` flag file in temp directory controlled by `CLAUDE_PROJECT_DIR` | Check return value of `is_diagnostic_mode()` |
| `save_diagnostic()` | No mock -- verify actual files written to `{tmp_dir}/.claude/diagnostic/` | Read diagnostic file content, assert expected fields present |

### LOG-CUR-001: Curator Operations Summary (including Truncation)

| Test Function | Scenario | Verification |
|---------------|----------|-------------|
| test_instrumentation_ops_summary_created | Diagnostic mode enabled + operations applied (mix of ADD/MERGE/DELETE with some skipped) | A file matching `*_curator_ops_summary.txt` exists in `.claude/diagnostic/`. Content includes per-type counts (applied/skipped). If skips occurred, skip reasons listed. |
| test_instrumentation_ops_summary_not_created_when_disabled | Diagnostic mode disabled + operations applied | No `*_curator_ops_summary.txt` file exists in `.claude/diagnostic/`. |
| test_instrumentation_truncation_diagnostic_created | Diagnostic mode enabled + 15 operations passed | A file matching `*_curator_ops_truncated.txt` exists (separate from summary). Content notes truncation from 15 to 10. Summary file also notes truncation. |
| test_instrumentation_truncation_not_emitted_at_10 | Diagnostic mode enabled + exactly 10 operations | No `*_curator_ops_truncated.txt` file exists (10 is not over the limit). Summary file does NOT mention truncation. |

### LOG-CUR-002: Non-Existent ID Reference

| Test Function | Scenario | Verification |
|---------------|----------|-------------|
| test_instrumentation_nonexistent_id_merge | Diagnostic mode enabled + MERGE with non-existent source_id | A file matching `*_curator_nonexistent_id.txt` exists. Content includes the non-existent ID and operation type "MERGE". |
| test_instrumentation_nonexistent_id_delete | Diagnostic mode enabled + DELETE with non-existent target_id | A file matching `*_curator_nonexistent_id.txt` exists. Content includes the non-existent ID and operation type "DELETE". |
| test_instrumentation_nonexistent_id_not_created_when_disabled | Diagnostic mode disabled + non-existent ID reference | No `*_curator_nonexistent_id.txt` file exists. |

### LOG-CUR-003: DELETE Reason Audit

| Test Function | Scenario | Verification |
|---------------|----------|-------------|
| test_instrumentation_delete_audit_created | Diagnostic mode enabled + DELETE applied successfully | A file matching `*_curator_delete_audit.txt` exists. Content includes `target_id`, deleted entry text (truncated to 80 chars), and reason. |
| test_instrumentation_delete_audit_not_created_when_disabled | Diagnostic mode disabled + DELETE applied | No `*_curator_delete_audit.txt` file exists. |
| test_instrumentation_delete_audit_not_created_when_skipped | Diagnostic mode enabled + DELETE skipped (non-existent ID) | No `*_curator_delete_audit.txt` file exists (DELETE was not applied, only LOG-CUR-002 fires). |
| test_instrumentation_delete_audit_text_truncated | Diagnostic mode enabled + DELETE entry text > 80 chars | Diagnostic file content shows text truncated to 80 characters. |

---

## Contract Test Exclusions

| REQ-* | Contract Test? | Notes |
|-------|---------------|-------|
| REQ-CUR-001 | YES | Contract test mocks LLM to return operations in JSON response, verifies extraction result includes `operations` key. |
| REQ-CUR-002 | YES | Contract test calls `update_playbook_data()` with ADD operation, verifies entry created in correct section with correct schema. |
| REQ-CUR-003 | YES | Contract test calls `update_playbook_data()` with MERGE operation, verifies merged entry has summed counters, sources removed. |
| REQ-CUR-004 | YES | Contract test calls `update_playbook_data()` with DELETE operation, verifies entry removed. |
| REQ-CUR-005 | YES | Contract test calls `update_playbook_data()` with ordered operations, verifies sequential semantics (later ops see earlier state). |
| REQ-CUR-006 | YES | Contract test monkeypatches `_apply_curator_operations` to raise, verifies original playbook returned. |
| REQ-CUR-007 | YES | Contract test reads `reflection.txt` template, verifies it contains operation instructions and examples. |
| REQ-CUR-008 | YES | Contract test passes extraction with both `operations` and `new_key_points`, verifies only operations processed. |
| REQ-CUR-009 | YES | Contract test passes > 10 operations, verifies only 10 processed. Contract test passes unknown type, verifies it is skipped. |

All REQ-CUR-* have contract tests. No exclusions needed.

---

## Failure Mode Coverage

Mapping failure modes from intent.md to test cases.

| FM-* | Failure Mode | Mitigated By | Test Functions |
|------|-------------|-------------|----------------|
| FM-CUR-001 | LLM returns unexpected format, all ops silently skipped | QG-CUR-001 | test_invariant_no_crash_on_invalid_operations, test_scn_unknown_operation_type_skipped |
| FM-CUR-002 | MERGE references IDs deleted by prior DELETE | SC-CUR-005 | test_scn_merge_first_source_deleted_by_prior_op, test_scn_delete_before_merge |
| FM-CUR-003 | LLM aggressively deletes/merges | CON-CUR-004 | test_invariant_operations_bounded_to_10, test_scn_exactly_11_operations_truncation |
| FM-CUR-004 | Old-format responses not handled | CON-CUR-001 | test_scn_operations_key_absent_nkp_used, test_contract_operations_precedence |
| FM-CUR-005 | Shallow copy leaks mutations | CON-CUR-005 | test_invariant_deep_copy_isolation, test_scn_exception_rollback_returns_original |
| FM-CUR-006 | MERGE produces inflated counters | Accepted trade-off | test_invariant_counter_non_negativity_through_merge (verifies correctness of sum, not inflation) |
| FM-CUR-007 | Operations never used in practice | OBS-CUR-001 | test_instrumentation_ops_summary_created (verifies diagnostic exists for monitoring) |
| FM-CUR-008 | Callers crash on signature change | CON-CUR-002 | test_contract_add_operation (verifies `update_playbook_data()` signature unchanged) |
| FM-CUR-009 | Double-processing with both operations + new_key_points | SC-CUR-007 | test_invariant_precedence_prevents_double_processing, test_scn_operations_key_present_nkp_ignored |
| FM-CUR-010 | LLM cannot reference entry IDs | SC-CUR-006 | test_scn_prompt_includes_entry_ids_and_examples |
| FM-CUR-011 | MERGE with single source_id as text rewrite | QG-CUR-001 | test_scn_merge_skipped_source_ids_fewer_than_2 |
| FM-CUR-012 | LLM returns 50 operations | CON-CUR-004 | test_invariant_operations_bounded_to_10, test_scn_operations_truncated_15_to_10 |

---

## Test File Organization

| File | Purpose | Location |
|------|---------|----------|
| `tests/test_curator_whitebox.py` | White-box tests covering all REQ-CUR-*, SCN-CUR-*, INV-CUR-*, LOG-CUR-* + adversarial tests | `/data/agentic_context_engineering/tests/test_curator_whitebox.py` |
| `tests/test_curator_contract.py` | Contract/black-box tests covering all REQ-CUR-* + deliverable tests | `/data/agentic_context_engineering/tests/test_curator_contract.py` |

### File Headers

White-box test file:
```python
# Spec: docs/curator/spec.md
# Testing: docs/curator/testing.md
```

Contract test file:
```python
# Spec: docs/curator/spec.md
# Contract: docs/curator/contract.md
# Testing: docs/curator/testing.md
```

### Fixtures and Helpers Needed

#### Common to Both Files

```
project_dir(tmp_path, monkeypatch)  -- Set CLAUDE_PROJECT_DIR to temp dir, create .claude/ structure
enable_diagnostic(project_dir)      -- Create diagnostic_mode flag file
diagnostic_dir(project_dir)         -- Return path to .claude/diagnostic/ dir
```

#### White-box File Only

```
_make_empty_playbook()              -- Return sections-based playbook with all empty sections
_make_playbook_with_entries(...)    -- Return playbook with specified entries in specified sections
_collect_all_entries(playbook)      -- Flatten all entries from all sections into a single list
_collect_all_texts(playbook)        -- Collect all entry texts from all sections into a set
_setup_extract_keypoints_mocks(monkeypatch)  -- Mock Anthropic client for extract_keypoints tests
```

#### Contract File Only

```
_make_sections_playbook(entries, section)  -- Construct playbook per contract.md schema
_setup_extract_keypoints_mocks(monkeypatch)  -- Mock Anthropic client (same pattern as whitebox)
```

---

## Verification Plan (Phase 2 Checklist)

Before claiming Phase 2 COMPLETE, the following must pass:

1. `pytest tests/test_curator_whitebox.py tests/test_curator_contract.py -v` -- all tests pass
2. `pytest tests/test_curator_whitebox.py tests/test_curator_contract.py --cov=src/hooks/common --cov-report=term-missing` -- curator-function coverage >= 80%. **Scope limitation:** The overall file coverage will be lower because `src/hooks/common.py` contains non-curator functions that are outside the curator test scope. Verify that all missed lines in `term-missing` output fall within non-curator functions, and that zero missed lines fall within `_apply_curator_operations()` or the operations branch of `update_playbook_data()` / `extract_keypoints()`.
3. `pytest tests/test_curator_whitebox.py tests/test_curator_contract.py -x --tb=short` -- quick validation
4. `pytest tests/test_curator_whitebox.py tests/test_curator_contract.py --count=1000 --failfast` -- flaky detection (requires `pytest-repeat`)
5. `pytest tests/test_curator_whitebox.py tests/test_curator_contract.py` with `-race` equivalent (Python: use `threading` tests if applicable -- not directly applicable for pure dict transforms; skip this check for non-concurrent code)
6. Break-the-code verification: comment out a critical line (e.g., the deep copy in `update_playbook_data()`, or the counter summing in MERGE), run tests, verify failure. **Restore immediately after each break test.**
7. Every `@tests` annotation references a valid REQ-CUR-*/SCN-CUR-* from spec.md
8. Every `@tests-contract` annotation references a valid REQ-CUR-* from spec.md
9. Every `@tests-invariant` annotation references a valid INV-CUR-* from spec.md
10. Every `@tests-instrumentation` annotation references a valid LOG-CUR-* from observability.md
11. No `pytest.skip()` or `@pytest.mark.skip` anywhere
