# Test Strategy: Sections Module

## Coverage Targets
- Sections-function line coverage: >= 80% (target applies to these functions: `load_playbook`, `save_playbook`, `update_playbook_data`, `format_playbook`, `generate_keypoint_name`, `extract_keypoints`, `_resolve_section`)
- Branch coverage: >= 70% (sections functions)
- All REQ-SECT-* covered by both white-box and contract tests
- All SCN-SECT-* covered by white-box tests
- All INV-SECT-* covered by white-box invariant tests
- Contract test coverage: every REQ-SECT-* must have a contract test OR a documented justification below
- Instrumentation coverage: LOG-SECT-001, LOG-SECT-002, LOG-SECT-003 tested via white-box tests

### Coverage Scope Explanation

The tests cover `src/hooks/common.py`, which contains both sections-relevant functions and non-sections utility functions that belong to other concerns (session management, transcript loading, LLM API calls, settings). The overall file coverage will be lower than 80% because non-sections functions (`load_transcript`, `load_settings`, `is_first_message`, `mark_session`, `clear_session`, `get_user_claude_dir`, `load_template`) are not exercised by the sections test suite.

The >= 80% target applies only to the sections-relevant functions listed above. Verify that all missed lines in `--cov-report=term-missing` output fall within non-sections functions, and that zero missed lines fall within the sections-relevant functions.

---

## Intent Traceability

Success criteria from spec.md traceability matrix, mapped to test IDs.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* | Test Type | Test Function |
|------|-------------------|-------------------|-----------|---------------|
| SC-SECT-001 | playbook.json stores key points under named sections | REQ-SECT-001 | White-box | test_save_playbook_sections_schema |
| SC-SECT-001 | (same) | REQ-SECT-001 | Contract | test_contract_playbook_sections_schema |
| SC-SECT-001 | (same) | INV-SECT-001 | White-box | test_invariant_sections_key_always_present_after_save |
| SC-SECT-001 | (same) | INV-SECT-002 | White-box | test_invariant_section_names_canonical |
| SC-SECT-001 | (same) | INV-SECT-003 | White-box | test_invariant_counters_non_negative |
| SC-SECT-002 | Key point IDs use section-derived prefixes | REQ-SECT-002 | White-box | test_generate_keypoint_name_basic, test_generate_keypoint_name_existing, test_generate_keypoint_name_legacy_ignored |
| SC-SECT-002 | (same) | REQ-SECT-002 | Contract | test_contract_generate_keypoint_name |
| SC-SECT-002 | (same) | SCN-SECT-002-01 | White-box | test_scn_generate_first_id_empty_section |
| SC-SECT-002 | (same) | SCN-SECT-002-02 | White-box | test_scn_generate_next_id_after_existing |
| SC-SECT-002 | (same) | SCN-SECT-002-03 | White-box | test_scn_legacy_kpt_ids_ignored_in_counter |
| SC-SECT-003 | format_playbook outputs section headers in canonical order | REQ-SECT-003 | White-box | test_format_playbook_section_headers, test_format_empty_sections_omitted, test_format_all_empty_returns_empty |
| SC-SECT-003 | (same) | REQ-SECT-003 | Contract | test_contract_format_playbook_sections |
| SC-SECT-003 | (same) | SCN-SECT-003-01 | White-box | test_scn_format_multiple_sections |
| SC-SECT-003 | (same) | SCN-SECT-003-02 | White-box | test_scn_format_empty_playbook_returns_empty |
| SC-SECT-003 | (same) | SCN-SECT-003-03 | White-box | test_scn_format_overhead_within_20_percent |
| SC-SECT-004 | Extraction prompt instructs LLM to assign sections | REQ-SECT-004 | White-box | test_reflection_template_lists_sections |
| SC-SECT-004 | (same) | REQ-SECT-004 | Contract | test_contract_reflection_template_sections |
| SC-SECT-004 | Backward compat for new_key_points | REQ-SECT-005 | White-box | test_update_dict_with_valid_section, test_update_dict_with_unknown_section, test_update_plain_string_backward_compat, test_update_case_insensitive_match, test_update_missing_null_empty_section |
| SC-SECT-004 | (same) | REQ-SECT-005 | Contract | test_contract_new_keypoint_section_assignment, test_contract_new_keypoint_backward_compat |
| SC-SECT-004 | (same) | SCN-SECT-004-01 | White-box | test_scn_dict_with_valid_section |
| SC-SECT-004 | (same) | SCN-SECT-004-02 | White-box | test_scn_dict_with_unknown_section |
| SC-SECT-004 | (same) | SCN-SECT-004-03 | White-box | test_scn_plain_string_backward_compat |
| SC-SECT-004 | (same) | SCN-SECT-004-04 | White-box | test_scn_case_mismatch_and_whitespace |
| SC-SECT-004 | (same) | SCN-SECT-004-05 | White-box | test_scn_missing_null_empty_section_to_others |
| SC-SECT-005 | Migration from flat format to sections | REQ-SECT-006 | White-box | test_load_migrates_flat_to_sections, test_load_migrates_flat_with_legacy_scores |
| SC-SECT-005 | (same) | REQ-SECT-006 | Contract | test_contract_flat_migration |
| SC-SECT-005 | (same) | REQ-SECT-007 | White-box | test_load_dual_key_sections_precedence |
| SC-SECT-005 | (same) | REQ-SECT-007 | Contract | test_contract_dual_key_handling |
| SC-SECT-005 | (same) | SCN-SECT-006-01 | White-box | test_scn_migrate_flat_with_mixed_ids |
| SC-SECT-005 | (same) | SCN-SECT-006-02 | White-box | test_scn_migrate_flat_with_legacy_score_field |
| SC-SECT-005 | (same) | SCN-SECT-006-03 | White-box | test_scn_load_already_sections_based |
| SC-SECT-005 | (same) | SCN-SECT-006-04 | White-box | test_scn_dual_key_file_handling |
| SC-SECT-005 | (same) | INV-SECT-004 | White-box | test_invariant_legacy_ids_preserved |
| SC-SECT-005 | (same) | INV-SECT-005 | White-box | test_invariant_slug_id_prefix_consistency |
| SC-SECT-005 | (same) | INV-SECT-006 | White-box | test_invariant_migration_round_trip_stability |
| SC-SECT-005 | (same) | INV-SECT-007 | White-box | test_invariant_no_key_points_key_after_load, test_invariant_no_key_points_key_after_save |
| SC-SECT-006 | update_playbook_data iterates all sections | REQ-SECT-008 | White-box | test_evaluations_across_sections, test_pruning_across_sections |
| SC-SECT-006 | (same) | REQ-SECT-008 | Contract | test_contract_evaluations_across_sections, test_contract_pruning_across_sections |
| SC-SECT-006 | (same) | SCN-SECT-008-01 | White-box | test_scn_evaluation_finds_keypoint_across_sections |
| SC-SECT-006 | (same) | SCN-SECT-008-02 | White-box | test_scn_pruning_removes_from_correct_section |
| SC-SECT-006 | extract_keypoints builds flat dict from sections | REQ-SECT-009 | White-box | test_extract_keypoints_flat_dict |
| SC-SECT-006 | (same) | REQ-SECT-009 | Contract | test_contract_extract_keypoints_flat_dict |
| SC-SECT-006 | (same) | SCN-SECT-009-01 | White-box | test_scn_extract_flat_dict_from_sections |
| QG-SECT-001 | SECTION_SLUGS constant is single source of truth | REQ-SECT-010 | White-box | test_section_slugs_constant |
| QG-SECT-001 | (same) | REQ-SECT-010 | Contract | test_contract_section_slugs_constant |

---

## Mocking Strategy

### External Dependencies

| Dependency | Mock Approach | Testability Hook |
|------------|---------------|------------------|
| File system (`playbook.json`) | Temp directory via `CLAUDE_PROJECT_DIR` env var | `get_project_dir()` reads `CLAUDE_PROJECT_DIR`. Tests set this env var to a `tmp_path` (pytest fixture). |
| File system (`playbook.txt` template) | Monkeypatch `load_template()` in `common` module to return a known template string | `load_template()` reads from `get_user_claude_dir() / "prompts/"`. Tests monkeypatch `load_template` to return `"HEADER\n{key_points}\nFOOTER"`. |
| File system (`reflection.txt` template) | Monkeypatch `load_template()` OR place template in temp dir | Tests for REQ-SECT-004 read the actual template file to verify section listing. |
| Diagnostic mode (`is_diagnostic_mode()`) | Create/remove `.claude/diagnostic_mode` flag file in temp directory | `is_diagnostic_mode()` checks `get_project_dir() / ".claude" / "diagnostic_mode"`. Tests create the flag file to enable diagnostic mode. |
| Diagnostic output (`save_diagnostic()`) | No mock needed -- reads written file from temp directory | `save_diagnostic()` writes to `get_project_dir() / ".claude" / "diagnostic/"`. Tests read files from this directory to verify content. |
| Time (`datetime.now()`) | Not mocked -- only used in `save_playbook()` for `last_updated` and `save_diagnostic()` for filename timestamp. Assertions check field presence, not exact value. | If needed, monkeypatch `datetime` in the module. |
| `SECTION_SLUGS` constant | Importable directly from `src/hooks/common.py` | Tests import `SECTION_SLUGS` and reference it for canonical names and slugs. |
| LLM API (`extract_keypoints`) | Not relevant to sections unit tests | `extract_keypoints()` LLM call path is not under test. Only the `playbook_dict` construction inside `extract_keypoints()` is tested via white-box tests (by calling with a pre-constructed playbook and verifying the dict building logic). |

### Detailed Mocking Approach Per Function

#### `load_playbook()` (file I/O)
- **Setup**: Create a temp directory, set `CLAUDE_PROJECT_DIR` env var to it, write a `playbook.json` file with the desired format (flat, sections-based, dual-key, corrupt, etc.).
- **Assertion**: Call `load_playbook()`, inspect the returned dict for sections-based schema.
- **Cleanup**: pytest `tmp_path` fixture handles cleanup automatically. Restore env var via monkeypatch.

#### `save_playbook()` (file I/O + assertion)
- **Setup**: Construct sections-based playbook dict in memory, set `CLAUDE_PROJECT_DIR` to temp dir.
- **Assertion**: Call `save_playbook()`, read back the written JSON file, verify `sections` key present, no `key_points` key.
- **Negative test**: Pass a playbook without `sections` key, verify `AssertionError` is raised.

#### `format_playbook()` (string formatting with template I/O)
- **Setup**: Construct sections-based playbook dict in memory. Monkeypatch `load_template` in `common` module to return a known template string (e.g., `"HEADER\n{key_points}\nFOOTER"`).
- **Assertion**: Call `format_playbook()`, check returned string for `## SECTION_NAME` headers, correct ordering, empty section omission.

#### `update_playbook_data()` (dict transformation + diagnostics)
- **Setup**: Construct sections-based playbook dict and extraction_result dict directly in memory. No file I/O needed for the core logic.
- **Caveat**: `update_playbook_data()` calls `is_diagnostic_mode()` and `save_diagnostic()` during pruning and unknown section detection. For non-instrumentation tests, set `CLAUDE_PROJECT_DIR` to a temp dir without the diagnostic flag file so `is_diagnostic_mode()` returns `False`.
- **For instrumentation tests**: Create the diagnostic flag file to enable diagnostic mode, then verify diagnostic output files.

#### `generate_keypoint_name()` (pure function)
- **Setup**: Construct `section_entries` list and `slug` string directly in memory. No I/O.
- **Assertion**: Call `generate_keypoint_name(section_entries, slug)`, verify returned string matches expected `{slug}-{NNN}` format.

#### `_resolve_section()` (pure function)
- **Setup**: Call with various section name strings directly. No I/O.
- **Assertion**: Verify returned canonical section name matches expected result.

#### `extract_keypoints()` -- playbook_dict building (requires white-box access)
- **Setup**: Construct a sections-based playbook dict. The test verifies the `playbook_dict = {}` building logic from `playbook.get("sections", {})`.
- **Note**: Testing the full `extract_keypoints()` function requires LLM API mocking, which is out of scope. White-box tests verify only the dict-building logic by constructing the intermediate result and asserting the shape. Contract tests verify the documented behavior (flat `{name: text}` dict from all sections).

### Contract Test Mocking Approach

Contract tests exercise the public API as documented in contract.md. They use the same temp directory strategy but do NOT inspect internal state, internal function calls, or migration branches.

- **For load + save round-trip**: Write legacy JSON to temp dir, call `load_playbook()`, call `save_playbook()`, read JSON back, verify sections-based schema.
- **For update**: Construct dicts per contract.md schemas, call `update_playbook_data()`, verify output matches contract.
- **For format**: Monkeypatch `load_template`, call `format_playbook()`, verify format string contains section headers.
- **For generate_keypoint_name**: Call with section_entries and slug per contract.md, verify returned ID format.

---

## Test Types

| Type | When to Use |
|------|-------------|
| Unit / White-box tests | Individual functions with known internal logic. Can inspect migration branches, internal state, invariants, `_resolve_section()`. |
| Contract / Black-box tests | Exercise public API as documented in contract.md. No knowledge of internal branching or implementation details. |
| **Deliverable tests** | **Exercise the end-to-end flow as a user would: write a legacy playbook file, run the full load-update-save-format cycle, verify the output has section headers, entries in correct sections, and round-trip stability.** |

### Deliverable Test Strategy

A deliverable test exercises the full lifecycle:
1. Write a flat-format `playbook.json` to temp dir (simulating pre-migration state).
2. Call `load_playbook()` (migration runs -- flat entries moved to OTHERS).
3. Call `update_playbook_data()` with new key points that have section assignments and evaluations (entries distributed to sections, counters updated, pruning runs).
4. Call `save_playbook()` (writes sections-based JSON).
5. Call `load_playbook()` again (verify round-trip stability -- no re-migration).
6. Call `format_playbook()` (verify output has section headers, correct ordering, empty sections omitted).

This catches integration failures between functions that unit tests might miss (e.g., `update_playbook_data()` expects flat `key_points` that `load_playbook()` already converted to `sections`).

These deliverable tests are included in the contract test file as `test_contract_full_lifecycle_*` functions.

---

## Adversarial Test Categories

### Category 1: Migration Correctness (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-MIG-001 | Flat playbook with bare string + dict-without-score + dict-with-score + already-migrated | REQ-SECT-006, SCN-SECT-006-02 | All 4 legacy entry types migrate to OTHERS correctly. Scoring migration applied first, then all placed in OTHERS. |
| TC-MIG-002 | Flat playbook with zero entries | REQ-SECT-006 | Empty `key_points: []` migrates to all-empty sections. No OBS-SECT-001 emitted (nothing migrated). |
| TC-MIG-003 | Dual-key: sections + key_points both present | REQ-SECT-007, SCN-SECT-006-04 | `sections` takes precedence. `key_points` data is completely ignored. Dual-key warning emitted. |
| TC-MIG-004 | Already sections-based file loaded twice | SCN-SECT-006-03, INV-SECT-006 | Second load produces identical result. No migration diagnostic emitted. |
| TC-MIG-005 | Missing file -> default empty playbook | REQ-SECT-001 | `load_playbook()` returns empty sections dict with all 5 canonical sections. |
| TC-MIG-006 | Corrupt JSON file -> default empty playbook | REQ-SECT-001 | Same fallback as missing file. |
| TC-MIG-007 | Sections file missing one canonical section | Design: ensuring canonical sections | After load, all 5 sections present (empty list added for missing). |
| TC-MIG-008 | Round-trip stability: load -> save -> load produces identical sections and version | INV-SECT-006 | Only `last_updated` changes. Sections dict and version are identical. |

### Category 2: Section Name Resolution Edge Cases (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-RES-001 | Exact canonical name: `"PATTERNS & APPROACHES"` | REQ-SECT-005 | Returns `"PATTERNS & APPROACHES"` with no diagnostic. |
| TC-RES-002 | Case-insensitive match: `"patterns & approaches"` | REQ-SECT-005, SCN-SECT-004-04 | Returns `"PATTERNS & APPROACHES"`. |
| TC-RES-003 | Leading/trailing whitespace: `"  MISTAKES TO AVOID  "` | REQ-SECT-005, SCN-SECT-004-04 | Stripped before matching. Returns `"MISTAKES TO AVOID"`. |
| TC-RES-004 | Unknown section name: `"RANDOM STUFF"` | REQ-SECT-005, SCN-SECT-004-02 | Returns `"OTHERS"`. OBS-SECT-002 emitted. |
| TC-RES-005 | Empty string after strip: `"   "` | REQ-SECT-005, SCN-SECT-004-05 | Returns `"OTHERS"`. No OBS-SECT-002 (empty is expected fallback). |
| TC-RES-006 | None value | REQ-SECT-005, SCN-SECT-004-05 | Returns `"OTHERS"`. No OBS-SECT-002. |
| TC-RES-007 | Empty string `""` | REQ-SECT-005, SCN-SECT-004-05 | Returns `"OTHERS"`. No OBS-SECT-002. |
| TC-RES-008 | Section key missing from dict entirely | REQ-SECT-005, SCN-SECT-004-05 | `item.get("section", "")` returns `""`. Treated as empty -> OTHERS. No OBS-SECT-002. |
| TC-RES-009 | `"others"` (lowercase canonical) | REQ-SECT-005 | Returns `"OTHERS"`. No OBS-SECT-002 (matches canonically). |

### Category 3: ID Generation Correctness (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-ID-001 | Empty section, slug `"pat"` | REQ-SECT-002, SCN-SECT-002-01 | Returns `"pat-001"`. |
| TC-ID-002 | Section with `pat-001`, `pat-003` (gap) | REQ-SECT-002, SCN-SECT-002-02 | Returns `"pat-004"` (max is 003, next is 004). |
| TC-ID-003 | OTHERS with `kpt_001`, `kpt_005`, `oth-002` | REQ-SECT-002, SCN-SECT-002-03 | Returns `"oth-003"`. `kpt_*` entries ignored by regex. |
| TC-ID-004 | Section entries with no `name` key (defensive) | REQ-SECT-002 | `entry.get("name", "")` returns `""`, does not match regex. Returns `{slug}-001`. |
| TC-ID-005 | All slugs produce correct format | REQ-SECT-010, INV-SECT-005 | For each slug in SECTION_SLUGS, verify `generate_keypoint_name([], slug)` returns `{slug}-001`. |

### Category 4: Format Output Correctness (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-FMT-001 | Multiple sections with entries, some empty | REQ-SECT-003, SCN-SECT-003-01 | Output has headers for non-empty sections only, in canonical order. |
| TC-FMT-002 | All sections empty | REQ-SECT-003, SCN-SECT-003-02 | Returns `""` directly. No template insertion. |
| TC-FMT-003 | Only OTHERS has entries (common after migration) | REQ-SECT-003 | Only `## OTHERS` header appears. |
| TC-FMT-004 | Overhead within 20% | SCN-SECT-003-03 | 20 entries across 5 sections (4 each). Sections output no more than 20% larger than flat equivalent. |
| TC-FMT-005 | Single entry in one section | REQ-SECT-003 | One header, one entry, no trailing blank line issues. |
| TC-FMT-006 | Entry format unchanged from scoring | REQ-SECT-003 | `[name] helpful=X harmful=Y :: text` format preserved within each section block. |

### Category 5: Backward Compatibility (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-BC-001 | Plain strings in `new_key_points` | REQ-SECT-005, SCN-SECT-004-03 | Plain string treated as `{"text": str, "section": "OTHERS"}`. Added to OTHERS with `oth-NNN` ID. |
| TC-BC-002 | Legacy `kpt_NNN` IDs coexist with `oth-NNN` in OTHERS | INV-SECT-005, SCN-SECT-002-03 | ID generator only scans `oth-NNN` pattern. Legacy IDs untouched. |
| TC-BC-003 | Evaluations find legacy `kpt_001` across sections | REQ-SECT-008, SCN-SECT-008-01 | Cross-section name lookup finds `kpt_001` in OTHERS, increments counter. |
| TC-BC-004 | Old extraction results (list of strings) still work | REQ-SECT-005 | Mixed list of strings and dicts in `new_key_points` processes correctly. |
| TC-BC-005 | Empty text in new_key_points skipped | REQ-SECT-005 | Guard: `if not text` prevents appending empty key points. |
| TC-BC-006 | Duplicate text in new_key_points skipped | REQ-SECT-005 | Guard: `text in existing_texts` prevents duplicates across sections. |

**Summary: 5 of 5 adversarial categories covered (Migration, Resolution, ID Generation, Format, Backward Compatibility).**

---

## Invariant Test Coverage

| INV-* | Invariant | Test Function | Verification |
|-------|-----------|---------------|-------------|
| INV-SECT-001 | `sections` key always present after `save_playbook()` | test_invariant_sections_key_always_present_after_save | Call `save_playbook()` with sections-based dict, read back JSON, assert `"sections"` key exists. Also: pass dict without `sections`, assert `AssertionError` raised. |
| INV-SECT-002 | Section names from canonical set | test_invariant_section_names_canonical | After `load_playbook()` from various formats, assert all keys in `sections` dict are members of the canonical set from `SECTION_SLUGS`. |
| INV-SECT-003 | Counter non-negativity (helpful >= 0, harmful >= 0) | test_invariant_counters_non_negative | After migration from all legacy formats, verify every entry in every section has `helpful >= 0` and `harmful >= 0`. |
| INV-SECT-004 | Legacy IDs preserved during migration | test_invariant_legacy_ids_preserved | Write flat playbook with `kpt_001`, `kpt_002`. Call `load_playbook()`. Assert entries in OTHERS retain their original names unchanged. |
| INV-SECT-005 | Section-slug ID prefix consistency | test_invariant_slug_id_prefix_consistency | Add new key points to each section via `update_playbook_data()`. Verify each new entry's name starts with the correct slug from `SECTION_SLUGS[section_name]`. |
| INV-SECT-006 | Migration round-trip stability | test_invariant_migration_round_trip_stability | Load flat playbook (migration runs), save immediately, load again. Assert `sections` and `version` identical between first and second load. Only `last_updated` differs. |
| INV-SECT-007 | No `key_points` key in output | test_invariant_no_key_points_key_after_load, test_invariant_no_key_points_key_after_save | After `load_playbook()` from flat format, assert `"key_points" not in result`. After `save_playbook()`, read JSON back, assert `"key_points" not in data`. |

---

## Instrumentation Test Strategy

The sections module uses file-based diagnostics (not metrics or structured logging). Instrumentation tests verify that `save_diagnostic()` is called at the right times and with the right content.

### Diagnostic Mocking Approach

| Component | Mock Approach | Verification |
|-----------|---------------|-------------|
| `is_diagnostic_mode()` | Create/remove `.claude/diagnostic_mode` flag file in temp directory controlled by `CLAUDE_PROJECT_DIR` | Check return value of `is_diagnostic_mode()` |
| `save_diagnostic()` | No mock -- verify actual files written to `{tmp_dir}/.claude/diagnostic/` | Read diagnostic file content, assert expected fields present |

### LOG-SECT-001: Sections Migration Diagnostic

| Test Function | Scenario | Verification |
|---------------|----------|-------------|
| test_instrumentation_migration_diagnostic_created | Diagnostic mode enabled + flat playbook with entries | A file matching `*_sections_migration.txt` exists in `.claude/diagnostic/`. Content includes count of migrated entries. |
| test_instrumentation_migration_diagnostic_not_created_when_disabled | Diagnostic mode disabled + flat playbook with entries | No `*_sections_migration.txt` file exists in `.claude/diagnostic/`. |
| test_instrumentation_migration_diagnostic_not_created_when_no_migration | Diagnostic mode enabled + already sections-based playbook | No `*_sections_migration.txt` file exists (no migration occurred). |

### LOG-SECT-002: Unknown Section Fallback Diagnostic

| Test Function | Scenario | Verification |
|---------------|----------|-------------|
| test_instrumentation_unknown_section_diagnostic_created | Diagnostic mode enabled + new_key_points with `{"text": "...", "section": "RANDOM STUFF"}` | A file matching `*_sections_unknown_section.txt` exists. Content includes original section name `"RANDOM STUFF"` and key point text (truncated to 80 chars). |
| test_instrumentation_unknown_section_diagnostic_not_created_when_disabled | Diagnostic mode disabled + unknown section name | No `*_sections_unknown_section.txt` file exists. |
| test_instrumentation_unknown_section_diagnostic_not_emitted_for_missing_null_empty | Diagnostic mode enabled + new_key_points with `section: None`, `section: ""`, missing `section` key | No `*_sections_unknown_section.txt` file exists. Missing/null/empty is expected fallback, not "unknown". |

### LOG-SECT-003: Dual-Key Warning Diagnostic

| Test Function | Scenario | Verification |
|---------------|----------|-------------|
| test_instrumentation_dual_key_diagnostic_created | Diagnostic mode enabled + playbook.json with both `sections` and `key_points` | A file matching `*_sections_dual_key_warning.txt` exists. Content includes warning about dual-key detection. |
| test_instrumentation_dual_key_diagnostic_not_created_when_disabled | Diagnostic mode disabled + dual-key playbook | No `*_sections_dual_key_warning.txt` file exists. |
| test_instrumentation_dual_key_diagnostic_not_created_for_normal_files | Diagnostic mode enabled + playbook with only `sections` key | No `*_sections_dual_key_warning.txt` file exists (normal case, no dual-key). |

---

## Contract Test Exclusions

| REQ-* | Contract Test? | Notes |
|-------|---------------|-------|
| REQ-SECT-001 | YES | Contract test writes sections-based playbook via `save_playbook()`, reads back, verifies schema. |
| REQ-SECT-002 | YES | Contract test calls `generate_keypoint_name()` with documented inputs, verifies output format. |
| REQ-SECT-003 | YES | Contract test calls `format_playbook()`, verifies section headers and ordering. Requires monkeypatching `load_template`. |
| REQ-SECT-004 | YES | Contract test reads `reflection.txt` template, verifies section names are listed and JSON format shows `{"text": ..., "section": ...}`. |
| REQ-SECT-005 | YES | Contract test calls `update_playbook_data()` with various `new_key_points` formats, verifies section assignment. |
| REQ-SECT-006 | YES | Contract test writes flat JSON, calls `load_playbook()`, verifies sections-based output with entries in OTHERS. |
| REQ-SECT-007 | YES | Contract test writes dual-key JSON, calls `load_playbook()`, verifies sections used, no `key_points` key. |
| REQ-SECT-008 | YES | Contract test calls `update_playbook_data()` with evaluations, verifies counters updated across sections and pruning applied. |
| REQ-SECT-009 | YES | Contract test constructs sections-based playbook, verifies flat `{name: text}` dict built from all sections. Note: requires white-box knowledge of how `extract_keypoints()` builds the dict internally, so contract test verifies the documented contract behavior by calling the function and checking the dict shape. |
| REQ-SECT-010 | YES | Contract test imports `SECTION_SLUGS`, verifies canonical names and slug values match contract.md. |

All REQ-SECT-* have contract tests. No exclusions needed.

---

## Test File Organization

| File | Purpose | Location |
|------|---------|----------|
| `tests/test_sections_whitebox.py` | White-box tests covering all REQ-SECT-*, INV-SECT-*, SCN-SECT-*, LOG-SECT-* + adversarial tests | `/data/agentic_context_engineering/tests/test_sections_whitebox.py` |
| `tests/test_sections_contract.py` | Contract/black-box tests covering all REQ-SECT-* + deliverable tests | `/data/agentic_context_engineering/tests/test_sections_contract.py` |

### File Headers

White-box test file:
```python
# Spec: docs/sections/spec.md
# Testing: docs/sections/testing.md
```

Contract test file:
```python
# Spec: docs/sections/spec.md
# Contract: docs/sections/contract.md
# Testing: docs/sections/testing.md
```

---

## Verification Plan (Phase 2 Checklist)

Before claiming Phase 2 COMPLETE, the following must pass:

1. `pytest tests/test_sections_whitebox.py tests/test_sections_contract.py -v` -- all tests pass
2. `pytest tests/test_sections_whitebox.py tests/test_sections_contract.py --cov=src/hooks/common --cov-report=term-missing` -- sections-function coverage >= 80%. **Scope limitation:** The overall file coverage will be lower because `src/hooks/common.py` contains non-sections functions (`load_transcript`, `load_settings`, `is_first_message`, `mark_session`, `clear_session`, `get_user_claude_dir`, `load_template`) that are outside the sections module's test scope. Verify that all missed lines in `term-missing` output fall within non-sections functions, and that zero missed lines fall within the sections-relevant functions: `load_playbook`, `save_playbook`, `update_playbook_data`, `format_playbook`, `generate_keypoint_name`, `_resolve_section`, `extract_keypoints` (playbook_dict building only).
3. `pytest tests/test_sections_whitebox.py tests/test_sections_contract.py -x --tb=short` -- quick validation
4. `pytest tests/test_sections_whitebox.py tests/test_sections_contract.py -count=1000 --failfast` -- flaky detection
5. Break-the-code verification: comment out a critical line (e.g., the `_resolve_section()` OTHERS fallback, or the `SECTION_SLUGS` iteration in `format_playbook()`), run tests, verify failure
6. Every `@tests` annotation references a valid REQ-SECT-*/SCN-SECT-*/INV-SECT-* from spec.md
7. Every `@tests-contract` annotation references a valid REQ-SECT-* from spec.md
8. Every `@tests-invariant` annotation references a valid INV-SECT-* from spec.md
9. Every `@tests-instrumentation` annotation references a valid LOG-SECT-* from observability.md
10. No `pytest.skip()` or `@pytest.mark.skip` anywhere
