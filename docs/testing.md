# Test Strategy: Phase 1 ACE Implementation

## Coverage Targets
- Line coverage: >= 80%
- Branch coverage: >= 70%
- All REQ-* covered by tests (REQ-REFL-001..008, REQ-DEDUP-001..006, REQ-CUR-001..016)
- All SCN-* covered by tests (17 reflector, 10 dedup, 44 curator scenarios)
- All INV-* covered by tests (4 reflector, 5 dedup, 11 curator invariants)
- Contract test coverage: every REQ-* that has a testable public API must have a contract test OR documented justification below

## Intent Traceability

SC-* definitions from spec.md traceability matrices:

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* | Test Type | Test Function |
|------|-------------------|-------------------|-----------|---------------|
| SC-ACE-002 | Bullet ID Referencing During Generation | REQ-REFL-001, SCN-REFL-001-01 | White-box | test_extract_cited_ids_assistant_only |
| SC-ACE-002 | Bullet ID Referencing During Generation | REQ-REFL-001, SCN-REFL-001-02 | White-box | test_extract_cited_ids_empty |
| SC-ACE-002 | Bullet ID Referencing During Generation | REQ-REFL-001, SCN-REFL-001-03 | White-box | test_extract_cited_ids_legacy_ids |
| SC-ACE-002 | Bullet ID Referencing During Generation | INV-REFL-001 | White-box | test_extract_cited_ids_deduplication |
| SC-ACE-002 | Citation Directive in playbook.txt | REQ-REFL-002, SCN-REFL-002-01 | White-box | test_playbook_txt_contains_citation_directive |
| SC-ACE-002 | Citation Directive in playbook.txt | REQ-REFL-002, SCN-REFL-002-02 | White-box | test_format_playbook_preserves_key_points_placeholder |
| SC-ACE-003 | Separate Reflector Role | REQ-REFL-007, SCN-REFL-006-01 | White-box | test_apply_bullet_tags_increments_counters |
| SC-ACE-003 | Separate Reflector Role | REQ-REFL-007, SCN-REFL-006-02 | White-box | test_apply_bullet_tags_neutral_no_change |
| SC-ACE-003 | Separate Reflector Role | REQ-REFL-007, SCN-REFL-004-02 | White-box | test_apply_bullet_tags_unmatched_name_skipped |
| SC-ACE-003 | Separate Reflector Role | REQ-REFL-007 | White-box | test_apply_bullet_tags_all_sections |
| SC-ACE-003 | Separate Reflector Role | INV-REFL-003 | White-box | test_apply_bullet_tags_increments_counters |
| SC-ACE-003 | Separate Reflector Role | INV-REFL-004 | White-box | test_apply_bullet_tags_increments_counters |
| SC-ACE-003 | Separate Reflector Role | REQ-REFL-008, SCN-REFL-008-02 | White-box | test_extract_json_robust_code_fence_json |
| SC-ACE-003 | Separate Reflector Role | REQ-REFL-008, SCN-REFL-008-01 | White-box | test_extract_json_robust_balanced_brace |
| SC-ACE-003 | Separate Reflector Role | REQ-REFL-008 | White-box | test_extract_json_robust_raw_json |
| SC-ACE-003 | Separate Reflector Role | REQ-REFL-008 | White-box | test_extract_json_robust_all_fail_returns_none |
| SC-ACE-003 | Separate Reflector Role | REQ-REFL-006, SCN-REFL-005-01 | White-box | test_run_reflector_returns_empty_on_api_failure |
| SC-ACE-003 | Separate Reflector Role | REQ-REFL-006, SCN-REFL-005-02 | White-box | test_run_reflector_returns_empty_on_json_parse_failure |
| SC-ACE-003 | Separate Reflector Role | INV-REFL-002 | White-box | test_run_reflector_returns_empty_on_api_failure |
| SC-ACE-003 | Reflector Prompt Structure | REQ-CUR-007, SCN-CUR-007-01, REQ-REFL-003 | White-box | test_reflector_txt_template_structure |
| SC-ACE-001 | Semantic Deduplication | REQ-DEDUP-005, SCN-DEDUP-003-01 | White-box | test_dedup_missing_deps_returns_unmodified |
| SC-ACE-001 | Semantic Deduplication | INV-DEDUP-001, SCN-DEDUP-003-02 | White-box | test_dedup_unexpected_exception_returns_unmodified |
| SC-ACE-001 | Semantic Deduplication | REQ-DEDUP-006, SCN-DEDUP-005-01 | White-box | test_dedup_empty_playbook_no_op |
| SC-ACE-001 | Semantic Deduplication | REQ-DEDUP-006, SCN-DEDUP-005-02 | White-box | test_dedup_single_entry_no_op |
| SC-ACE-001 | Semantic Deduplication | REQ-DEDUP-004, SCN-DEDUP-004-01 | White-box | test_dedup_threshold_from_env_var |
| SC-ACE-001 | Semantic Deduplication | REQ-DEDUP-004 | White-box | test_dedup_threshold_clamping |
| SC-ACE-001 | Semantic Deduplication | REQ-DEDUP-001, REQ-DEDUP-002, SCN-DEDUP-001-01 | White-box | test_dedup_first_entry_wins |
| SC-ACE-001 | Semantic Deduplication | REQ-DEDUP-002, SCN-DEDUP-006-01 | White-box | test_dedup_counter_summing |
| SC-ACE-001 | Semantic Deduplication | REQ-DEDUP-001, SCN-DEDUP-001-02 | White-box | test_dedup_cross_section_merge |
| SC-ACE-001 | Semantic Deduplication | REQ-DEDUP-003, SCN-DEDUP-002-01 | White-box | test_dedup_transitive_grouping |
| SC-ACE-001 | Semantic Deduplication | REQ-DEDUP-001, SCN-DEDUP-001-03 | White-box | test_dedup_no_merge_below_threshold |
| SC-ACE-001 | Semantic Deduplication | REQ-DEDUP-001, REQ-DEDUP-002, SCN-DEDUP-002-02 | White-box | test_dedup_multiple_independent_groups |
| SC-ACE-001 | Semantic Deduplication | INV-DEDUP-003 | White-box | test_dedup_section_names_remain_canonical |
| SC-ACE-001 | Semantic Deduplication | INV-DEDUP-005 | White-box | test_dedup_top_level_structure_preserved |
| SC-CUR-001 | Structured Operations in Extraction | REQ-CUR-001, SCN-CUR-001-01 | White-box | test_extract_keypoints_includes_operations_key |
| SC-CUR-001 | Structured Operations in Extraction | REQ-CUR-001, SCN-CUR-001-02 | White-box | test_extract_keypoints_includes_empty_operations |
| SC-CUR-001 | Structured Operations in Extraction | REQ-CUR-001, SCN-CUR-001-03 | White-box | test_extract_keypoints_no_operations_key_absent_from_result |
| SC-CUR-001 | Structured Operations in Extraction | REQ-CUR-001, SCN-CUR-001-04 | White-box | test_extract_keypoints_non_list_operations_treated_as_absent |
| SC-CUR-002 | ADD Operation | REQ-CUR-002, SCN-CUR-002-01 | White-box | test_add_creates_entry_with_correct_schema |
| SC-CUR-002 | ADD Operation | REQ-CUR-002, SCN-CUR-002-02 | White-box | test_add_defaults_to_others_when_section_missing |
| SC-CUR-002 | ADD Operation | REQ-CUR-002, SCN-CUR-002-03 | White-box | test_add_skips_duplicate_text |
| SC-CUR-002 | ADD Operation | REQ-CUR-002, REQ-CUR-009, SCN-CUR-002-04 | White-box | test_add_skips_empty_text |
| SC-CUR-002 | ADD Operation | REQ-CUR-002, SCN-CUR-002-05 | White-box | test_add_resolves_section_case_insensitively |
| SC-CUR-003 | MERGE Operation | REQ-CUR-003, SCN-CUR-003-01, INV-CUR-003 | White-box | test_merge_combines_entries |
| SC-CUR-003 | MERGE Operation | REQ-CUR-003, SCN-CUR-003-02 | White-box | test_merge_with_explicit_section_override |
| SC-CUR-003 | MERGE Operation | REQ-CUR-003, SCN-CUR-003-03 | White-box | test_merge_with_nonexistent_source_ids_filtered |
| SC-CUR-003 | MERGE Operation | REQ-CUR-003, SCN-CUR-003-04 | White-box | test_merge_skipped_when_fewer_than_2_valid_source_ids |
| SC-CUR-003 | MERGE Operation | REQ-CUR-003, REQ-CUR-009, SCN-CUR-003-05 | White-box | test_merge_skipped_when_source_ids_has_fewer_than_2_entries |
| SC-CUR-003 | MERGE Operation | REQ-CUR-003, SCN-CUR-003-06 | White-box | test_merge_inherits_section_from_first_valid_source_id |
| SC-CUR-003 | MERGE Operation | REQ-CUR-003, REQ-CUR-005, SCN-CUR-003-07 | White-box | test_merge_where_first_source_deleted_by_prior_op |
| SC-CUR-003 | MERGE Operation | REQ-CUR-003, SCN-CUR-003-08 | White-box | test_merge_skipped_when_all_source_ids_nonexistent |
| SC-CUR-004 | DELETE Operation | REQ-CUR-004, SCN-CUR-004-01 | White-box | test_delete_removes_entry |
| SC-CUR-004 | DELETE Operation | REQ-CUR-004, SCN-CUR-004-02 | White-box | test_delete_skips_nonexistent_target_id |
| SC-CUR-004 | DELETE Operation | REQ-CUR-004, REQ-CUR-009, SCN-CUR-004-03 | White-box | test_delete_skips_empty_target_id |
| SC-CUR-005 | Sequential Processing | REQ-CUR-005, SCN-CUR-005-01 | White-box | test_sequential_delete_then_merge |
| SC-CUR-005 | Sequential Processing | REQ-CUR-005, SCN-CUR-005-02 | White-box | test_sequential_add_then_merge_references_new_entry |
| SC-CUR-005 | Sequential Processing | REQ-CUR-005, REQ-CUR-006, SCN-CUR-005-03 | White-box | test_update_playbook_data_rollback_on_exception |
| SC-CUR-005 | Sequential Processing | REQ-CUR-005, REQ-CUR-006, SCN-CUR-005-04 | White-box | test_sequential_skipped_op_does_not_trigger_rollback |
| SC-CUR-006 | Deep Copy Atomicity | REQ-CUR-006 | White-box | test_update_playbook_data_uses_operations_path |
| SC-CUR-006 | Deep Copy Atomicity | REQ-CUR-006, SCN-CUR-005-03 | White-box | test_update_playbook_data_rollback_on_exception |
| SC-CUR-007 | Precedence Rule | REQ-CUR-008, SCN-CUR-008-01, INV-CUR-006 | White-box | test_operations_key_present_ignores_new_key_points |
| SC-CUR-007 | Precedence Rule | REQ-CUR-008, SCN-CUR-008-02 | White-box | test_no_operations_key_uses_new_key_points |
| SC-CUR-007 | Precedence Rule | REQ-CUR-008, SCN-CUR-008-03 | White-box | test_empty_operations_list_ignores_new_key_points |
| SC-CUR-008 | Separate Curator Role | REQ-CUR-012, SCN-CUR-010-02 | White-box | test_run_curator_returns_empty_on_api_failure |
| SC-CUR-008 | Separate Curator Role | REQ-CUR-012, SCN-CUR-012-01 | White-box | test_run_curator_returns_empty_on_json_parse_failure |
| SC-CUR-008 | Separate Curator Role | REQ-CUR-010, SCN-CUR-010-03 | White-box | test_run_curator_with_empty_reflector_output |
| SC-CUR-008 | Separate Curator Role | INV-CUR-008 | White-box | test_run_curator_returns_empty_on_api_failure |
| SC-CUR-008 | Curator Prompt Structure | SCN-CUR-011-01 | White-box | test_curator_txt_template_structure |
| SC-CUR-009 | UPDATE Operation | REQ-CUR-013, SCN-CUR-013-01, INV-CUR-007 | White-box | test_update_revises_text_preserves_counters |
| SC-CUR-009 | UPDATE Operation | REQ-CUR-013, SCN-CUR-013-02 | White-box | test_update_skips_nonexistent_target_id |
| SC-CUR-009 | UPDATE Operation | REQ-CUR-013, SCN-CUR-013-03, INV-CUR-009 | White-box | test_update_skips_empty_target_id |
| SC-CUR-009 | UPDATE Operation | REQ-CUR-013, SCN-CUR-013-04, INV-CUR-009 | White-box | test_update_skips_empty_text |
| SC-CUR-010 | apply_structured_operations() | REQ-CUR-014, SCN-CUR-014-04 | White-box | test_apply_ops_empty_returns_same_reference |
| SC-CUR-010 | apply_structured_operations() | REQ-CUR-014, SCN-CUR-014-01, INV-CUR-010 | White-box | test_apply_ops_deep_copy_isolation |
| SC-CUR-010 | apply_structured_operations() | REQ-CUR-014, SCN-CUR-014-02, INV-CUR-001 | White-box | test_apply_ops_rollback_on_exception |
| SC-CUR-010 | apply_structured_operations() | REQ-CUR-014, REQ-CUR-013, SCN-CUR-014-03 | White-box | test_apply_ops_supports_update |
| SC-CUR-011 | prune_harmful() | REQ-CUR-015, SCN-CUR-015-01 | White-box | test_prune_harmful_removes_above_threshold |
| SC-CUR-011 | prune_harmful() | REQ-CUR-015, SCN-CUR-015-02 | White-box | test_prune_harmful_preserves_zero_eval |
| SC-CUR-011 | prune_harmful() | REQ-CUR-015, SCN-CUR-015-03, INV-CUR-011 | White-box | test_prune_harmful_equal_counters_not_pruned |
| SC-CUR-011 | prune_harmful() | REQ-CUR-015, SCN-CUR-015-04 | White-box | test_prune_harmful_logs_pruned_entries |
| SC-CUR-009 | Operations Truncation | REQ-CUR-009, SCN-CUR-009-03 | White-box | test_exactly_10_operations_no_truncation |
| SC-CUR-009 | Operations Truncation | REQ-CUR-009, SCN-CUR-009-04 | White-box | test_exactly_11_operations_truncated_to_10 |
| SC-CUR-009 | Operations Validation | REQ-CUR-009, INV-CUR-002 | White-box | test_unknown_operation_type_skipped |
| SC-CUR-009 | Operations Validation | REQ-CUR-009, INV-CUR-005 | White-box | test_operations_truncated_to_10 |
| -- | Invariant: INV-CUR-004 | INV-CUR-004 | White-box | test_section_names_canonical_after_operations |

## Mocking Strategy

| Dependency | Mock Approach | Testability Hook Needed |
|------------|---------------|------------------------|
| Anthropic API client | `unittest.mock.patch('common.anthropic')` with MagicMock; configure `mock_client.messages.create` to return mock response or raise | None -- module-level `anthropic` import with `ANTHROPIC_AVAILABLE` flag |
| Anthropic API availability | `unittest.mock.patch('common.ANTHROPIC_AVAILABLE', True/False)` | None -- module attribute |
| SentenceTransformer | `unittest.mock.patch('common.SentenceTransformer')` or `patch.dict('sys.modules')` to simulate ImportError | None -- lazy import in `run_deduplication()` |
| numpy | `unittest.mock.patch` or `patch.dict('sys.modules')` to simulate ImportError | None -- lazy import in `run_deduplication()` |
| Template loading (`load_template`) | `unittest.mock.patch('common.load_template')` returning known string | None -- function call |
| `format_playbook` | `unittest.mock.patch('common.format_playbook')` returning known string | None -- function call |
| Environment variables | `unittest.mock.patch.dict(os.environ)` | None -- standard os.getenv |
| `is_diagnostic_mode` | `unittest.mock.patch('common.is_diagnostic_mode', return_value=False)` | None -- function call |
| `save_diagnostic` | `unittest.mock.patch('common.save_diagnostic')` | None -- function call |
| `time.sleep` | `unittest.mock.patch('time.sleep')` to avoid actual delays in retry tests | None -- standard library |

### External API: Anthropic Client
- Mock approach: `unittest.mock.patch('common.anthropic')` with MagicMock
- Testability hook needed: None (anthropic module is imported at top level)
- Mock response objects simulate `response.content[0].text` for text extraction
- For error testing: configure `messages.create` to raise `Exception`

### External Dependency: SentenceTransformer
- Mock approach: `patch.dict('sys.modules', {'sentence_transformers': None})` for ImportError simulation, or `patch` on the module-level import within `run_deduplication` to mock `.encode()` returning fixed numpy arrays
- Testability hook needed: None (lazy import inside function)
- For embedding tests: provide pre-computed cosine similarity matrices via mock

## Test Types

| Type | When to Use |
|------|-------------|
| Unit tests (white-box) | Individual functions, internal state verification, mocked dependencies |
| Contract tests (black-box) | Public API behavior verification using only contract.md |
| Deliverable tests | Exercise session_end.py flow as a user would |
| Error injection | API failures, import failures, exceptions during processing |

### Deliverable Tests
The session_end.py hook is the deliverable. A full end-to-end test would require mocking stdin, the Anthropic API, file system, etc. The test suite includes integration-level tests that exercise the public functions in the order that session_end.py calls them, verifying the pipeline works end-to-end with mocked LLM calls.

## Contract Test Exclusions

| REQ-* | Reason Contract Testing Is Impossible | Covered By |
|-------|--------------------------------------|------------|
| REQ-REFL-003 | Requires Anthropic API client mock; internal retry logic | test_run_reflector_returns_empty_on_api_failure (white-box) |
| REQ-REFL-004 | Output schema is tested through reflector mock responses | test_run_reflector_returns_empty_on_json_parse_failure (white-box) |
| REQ-REFL-005 | Fallback mode requires observing prompt construction internals | test_run_reflector_parses_valid_response (white-box, exercises empty cited_ids path) |
| REQ-REFL-006 | Error handling requires API mock injection | test_run_reflector_returns_empty_on_api_failure (white-box) |
| REQ-CUR-001 | Requires Anthropic API mock to drive extract_keypoints | test_extract_keypoints_includes_operations_key (white-box) |
| REQ-CUR-010 | Requires Anthropic API client mock; internal retry logic | test_run_curator_returns_empty_on_api_failure (white-box) |
| REQ-CUR-011 | Output schema tested through curator mock responses | test_run_curator_returns_empty_on_json_parse_failure (white-box) |
| REQ-CUR-012 | Error handling requires API mock injection | test_run_curator_returns_empty_on_api_failure (white-box) |
| REQ-CUR-016 | Tested via _extract_json_robust which is an internal function | test_extract_json_robust_* (white-box) |

## Adversarial Test Categories

| Category | Covered | Example Tests |
|----------|---------|---------------|
| Boundary | YES | test_dedup_threshold_clamping (0.0, 1.0 edges), test_dedup_single_entry_no_op, test_apply_ops_empty_returns_same_reference, test_exactly_10_operations_no_truncation, test_exactly_11_operations_truncated_to_10 |
| Invalid input | YES | test_extract_cited_ids_empty, test_extract_json_robust_all_fail_returns_none, test_update_skips_empty_target_id, test_update_skips_empty_text, test_add_skips_empty_text, test_delete_skips_empty_target_id, test_merge_skipped_when_source_ids_has_fewer_than_2_entries, test_extract_keypoints_non_list_operations_treated_as_absent |
| Error injection | YES | test_dedup_missing_deps_returns_unmodified (ImportError), test_dedup_unexpected_exception_returns_unmodified (RuntimeError), test_run_reflector_returns_empty_on_api_failure, test_apply_ops_rollback_on_exception, test_update_playbook_data_rollback_on_exception |
| State isolation | YES | test_apply_ops_deep_copy_isolation, test_apply_ops_rollback_on_exception, test_sequential_skipped_op_does_not_trigger_rollback |
| Concurrency | NO | Out of scope -- all functions are synchronous or single-threaded async |

**4 of 5 adversarial categories covered.**

## Test File Organization

| File | Purpose |
|------|---------|
| `src/hooks/test_common_ace.py` | White-box tests (knows implementation) + contract tests for public API functions |

Note: Since this is a Python project (not Go), both white-box and contract tests are in a single file for simplicity. Contract-style tests are clearly annotated with `@tests-contract` comments. The test file uses unittest as the test framework.

## Contract Test Boundary Fix (F11)

The class `TestContractExtractJsonRobust` had `@tests-contract` annotations for `_extract_json_robust()` which is a PRIVATE function (prefixed with `_`). This was a contract test boundary violation. Fixed: renamed to `TestExtractJsonRobustAdditional` with `@tests` annotations (white-box).

## Backward Compatibility Tests (QG-ACE-001)

| Function | Test | Purpose |
|----------|------|---------|
| `extract_keypoints()` | test_backward_compat_extract_keypoints_signature | Verify signature unchanged; mock call works |
| `update_playbook_data()` | test_backward_compat_update_playbook_data_signature | Verify signature unchanged; basic call works |
