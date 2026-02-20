# Test Strategy: Retry Logic with Exponential Backoff

## Coverage Targets
- Retry-logic line coverage: >= 80% (target applies to retry-relevant code paths within `extract_keypoints()` and module-level constants `MAX_RETRIES`, `BASE_DELAY`)
- Branch coverage: >= 70% (retry logic branches)
- All REQ-RETRY-* covered by both white-box and contract tests
- All SCN-RETRY-* covered by white-box tests
- All INV-RETRY-* covered by white-box invariant tests
- Contract test coverage: every REQ-RETRY-* must have a contract test OR a documented justification below
- Instrumentation coverage: LOG-RETRY-001, LOG-RETRY-002, LOG-RETRY-003 tested via white-box tests

### Coverage Scope Explanation

The tests cover `src/hooks/common.py`, which contains retry-relevant code as well as scoring, curator, sections, session management, transcript loading, and LLM API call functions. The overall file coverage will be lower than 80% because non-retry functions are not exercised by the retry test suite.

The >= 80% target applies only to the retry-relevant code paths:
- The retry loop within `extract_keypoints()` (all except/break/continue branches)
- Module-level constants `MAX_RETRIES` and `BASE_DELAY`
- Backoff delay computation and `time.sleep()` call
- Diagnostic logging within the retry loop (`save_diagnostic` calls for LOG-RETRY-001, LOG-RETRY-002, LOG-RETRY-003)

Pre-existing functions covered by other test suites (`load_playbook`, `save_playbook`, `update_playbook_data`, `format_playbook`, `_apply_curator_operations`, etc.) are not the primary coverage target. Verify that all missed lines in `--cov-report=term-missing` output fall within non-retry functions, and that zero missed lines fall within the retry loop of `extract_keypoints()`.

---

## Intent Traceability

Success criteria from spec.md traceability matrix, mapped to test IDs.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* | Test Type | Test Function |
|------|-------------------|-------------------|-----------|---------------|
| SC-RETRY-001 | extract_keypoints() retries up to MAX_RETRIES total attempts; returns empty on exhaustion | REQ-RETRY-001 | White-box | test_retry_loop_retries_on_retryable_error |
| SC-RETRY-001 | (same) | REQ-RETRY-001 | Contract | test_contract_retry_returns_result_after_transient_failure |
| SC-RETRY-001 | (same) | REQ-RETRY-008 | White-box | test_module_constants_defined |
| SC-RETRY-001 | (same) | REQ-RETRY-008 | Contract | test_contract_module_constants_accessible |
| SC-RETRY-001 | (same) | SCN-RETRY-001-01 | White-box | test_scn_first_attempt_succeeds_no_retry |
| SC-RETRY-001 | (same) | SCN-RETRY-001-02 | White-box | test_scn_first_fails_second_succeeds |
| SC-RETRY-001 | (same) | SCN-RETRY-001-03 | White-box | test_scn_first_two_fail_third_succeeds |
| SC-RETRY-001 | (same) | SCN-RETRY-001-04 | White-box | test_scn_all_three_fail_return_empty |
| SC-RETRY-001 | (same) | INV-RETRY-004 | White-box | test_invariant_return_value_always_valid |
| SC-RETRY-002 | Exponential backoff with jitter | REQ-RETRY-002 | White-box | test_exponential_backoff_delay_values |
| SC-RETRY-002 | (same) | REQ-RETRY-002 | Contract | test_contract_backoff_no_immediate_retry |
| SC-RETRY-002 | (same) | SCN-RETRY-002-01 | White-box | test_scn_jitter_applied_to_delay |
| SC-RETRY-003 | Error classification: retryable vs non-retryable | REQ-RETRY-003 | White-box | test_error_classification_retryable, test_error_classification_non_retryable |
| SC-RETRY-003 | (same) | REQ-RETRY-003 | Contract | test_contract_retryable_errors_are_retried, test_contract_non_retryable_returns_empty |
| SC-RETRY-003 | (same) | REQ-RETRY-004 | White-box | test_non_retryable_immediate_return |
| SC-RETRY-003 | (same) | REQ-RETRY-004 | Contract | test_contract_non_retryable_returns_empty |
| SC-RETRY-003 | (same) | SCN-RETRY-003-01 | White-box | test_scn_api_status_error_503_retried |
| SC-RETRY-003 | (same) | SCN-RETRY-003-02 | White-box | test_scn_api_status_error_404_not_retried |
| SC-RETRY-003 | (same) | SCN-RETRY-003-03 | White-box | test_scn_api_response_validation_error_not_retried |
| SC-RETRY-003 | (same) | SCN-RETRY-003-04 | White-box | test_scn_runtime_error_not_retried |
| SC-RETRY-003 | (same) | SCN-RETRY-003-05 | White-box | test_scn_api_timeout_caught_before_api_connection |
| SC-RETRY-003 | (same) | SCN-RETRY-003-06 | White-box | test_scn_unknown_api_error_not_retried |
| SC-RETRY-003 | (same) | INV-RETRY-004 | White-box | test_invariant_return_value_always_valid |
| SC-RETRY-004 | Non-retryable errors return empty immediately | REQ-RETRY-004 | White-box | test_non_retryable_immediate_return |
| SC-RETRY-004 | (same) | SCN-RETRY-004-01 | White-box | test_scn_non_retryable_logs_then_returns_empty |
| SC-RETRY-004 | (same) | SCN-RETRY-004-02 | White-box | test_scn_non_retryable_no_log_when_diagnostic_off |
| SC-RETRY-004 | (same) | SCN-RETRY-004-03 | White-box | test_scn_permission_denied_immediate_return |
| SC-RETRY-004 | (same) | SCN-RETRY-004-04 | White-box | test_scn_unprocessable_entity_immediate_return |
| SC-RETRY-005 | Post-exhaustion returns empty | REQ-RETRY-005 | White-box | test_exhaustion_returns_empty |
| SC-RETRY-005 | (same) | REQ-RETRY-005 | Contract | test_contract_exhaustion_returns_empty |
| SC-RETRY-005 | (same) | SCN-RETRY-005-01 | White-box | test_scn_exhaustion_logs_and_returns_empty |
| SC-RETRY-005 | (same) | INV-RETRY-004 | White-box | test_invariant_return_value_always_valid |
| SC-RETRY-006 | Per-request timeout of 30s | REQ-RETRY-006 | White-box | test_timeout_parameter_passed |
| SC-RETRY-006 | (same) | REQ-RETRY-006 | Contract | test_contract_timeout_parameter_set |
| SC-RETRY-006 | (same) | SCN-RETRY-006-01 | White-box | test_scn_timeout_on_every_attempt |
| SC-RETRY-007 | Diagnostic logging for retries | REQ-RETRY-007 | White-box | test_diagnostic_logging_per_attempt, test_diagnostic_logging_exhaustion, test_diagnostic_logging_success_after_retry |
| SC-RETRY-007 | (same) | REQ-RETRY-007 | Contract | test_contract_no_diagnostic_when_mode_off |
| SC-RETRY-007 | (same) | SCN-RETRY-007-01 | White-box | test_scn_per_attempt_diagnostic_log |
| SC-RETRY-007 | (same) | SCN-RETRY-007-02 | White-box | test_scn_no_diagnostic_when_mode_off |
| SC-RETRY-007 | (same) | SCN-RETRY-007-03 | White-box | test_scn_success_after_retry_logged |
| SC-RETRY-007 | (same) | SCN-RETRY-007-04 | White-box | test_scn_no_diagnostic_on_first_attempt_success |
| (invariant) | Function signature unchanged | INV-RETRY-001 | White-box | test_invariant_function_signature_unchanged |
| (invariant) | Only client.messages.create() retried | INV-RETRY-002 | White-box | test_invariant_only_api_call_retried |
| (invariant) | Total time within hook timeout | INV-RETRY-003 | White-box | test_invariant_total_time_bounded |
| (invariant) | Return value always valid extraction result | INV-RETRY-004 | White-box | test_invariant_return_value_always_valid |

---

## Mocking Strategy

### External Dependencies

| Dependency | Mock Approach | Testability Hook |
|------------|---------------|------------------|
| `anthropic.Anthropic().messages.create` | Mock the SDK client constructor to return a mock client whose `messages.create` method raises specific exceptions or returns mock response objects. Use `side_effect` list or a stateful callable to control per-attempt behavior. | Monkeypatch `anthropic.Anthropic` in `src.hooks.common` module to return a mock client. |
| `time.sleep` | Monkeypatch `time.sleep` to a no-op or to a list-appending callable that captures delay values. | Direct monkeypatch: `monkeypatch.setattr(time, "sleep", capture_fn)`. Prevents real delays in tests. |
| `random.uniform` | Monkeypatch `random.uniform` to return a deterministic value (e.g., `1.0` for no jitter, or `0.75`/`1.25` for boundary testing). | Direct monkeypatch: `monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)`. |
| `is_diagnostic_mode()` | Create/remove `.claude/diagnostic_mode` flag file in temp directory controlled by `CLAUDE_PROJECT_DIR` env var. | `is_diagnostic_mode()` checks `get_project_dir() / ".claude" / "diagnostic_mode"`. Tests create the flag file to enable diagnostic mode for instrumentation tests. |
| `save_diagnostic()` | Monkeypatch to a callable that captures `(content, name)` pairs. This avoids file I/O and allows precise assertion on log content. Alternatively, for integration-style tests: use real file writes to tmp_path and read back. | Monkeypatch `save_diagnostic` in `src.hooks.common` module, OR verify actual files written to `{tmp_dir}/.claude/diagnostic/`. |
| `MAX_RETRIES` | Monkeypatch `common.MAX_RETRIES` to test edge cases (e.g., `MAX_RETRIES=1` for single-attempt, `MAX_RETRIES=2` for minimal retry). | Module-level variable: `monkeypatch.setattr(_common_module, "MAX_RETRIES", 1)`. |
| `BASE_DELAY` | Monkeypatch `common.BASE_DELAY` to test delay computation with different base values. | Module-level variable: `monkeypatch.setattr(_common_module, "BASE_DELAY", 1.0)`. |
| `ANTHROPIC_AVAILABLE` | Monkeypatch to `True` (to enable the API path) or `False` (to test the early-return guard branch). | Module-level variable: `monkeypatch.setattr(_common_module, "ANTHROPIC_AVAILABLE", True)`. |
| `load_template()` | Monkeypatch to return a known template string for prompt construction. | `monkeypatch.setattr(_common_module, "load_template", lambda name: "template {trajectories} {playbook}")`. |
| `load_settings()` | Monkeypatch to return known settings dict (or rely on env vars for model/api_key). | `monkeypatch.setattr(_common_module, "load_settings", lambda: {})`. |

### Detailed Mocking Approach Per Test Area

#### Retry Loop (REQ-RETRY-001, SCN-RETRY-001-*)

- **Setup**: Mock `anthropic.Anthropic` constructor to return a mock client. Configure `mock_client.messages.create` with a `side_effect` list: first N calls raise a retryable exception, then return a mock response.
- **Pattern**: Same as existing `_setup_extract_keypoints_mocks()` in curator tests, extended with `side_effect` for per-attempt control.
- **Key mocks**: `time.sleep` (no-op), `random.uniform` (fixed 1.0), `ANTHROPIC_AVAILABLE` (True), `load_template` (stub), env vars `CLAUDE_PROJECT_DIR` and `ANTHROPIC_API_KEY`.

#### Backoff Delays (REQ-RETRY-002, SCN-RETRY-002-01)

- **Setup**: Capture `time.sleep` calls in a list. Fix `random.uniform` to return a known jitter factor.
- **Assertion**: Verify `sleep_calls[0] == BASE_DELAY * 2^0 * jitter` and `sleep_calls[1] == BASE_DELAY * 2^1 * jitter`.
- **Boundary variants**: Test with `random.uniform` returning `0.75` (min jitter) and `1.25` (max jitter) to verify range boundaries.

#### Error Classification (REQ-RETRY-003, REQ-RETRY-004, SCN-RETRY-003-*, SCN-RETRY-004-*)

- **Setup**: Configure `mock_client.messages.create` to raise each specific exception type once.
- **Pattern**: For retryable errors, verify that `messages.create` is called more than once (retried). For non-retryable errors, verify exactly 1 call (no retry) and empty result returned.
- **Exception construction**: Use actual `anthropic` exception classes where possible. For `APIStatusError` with specific status codes, construct with `status_code=503` (retryable) vs `status_code=404` (non-retryable). For `APIResponseValidationError`, construct without status code.

#### Diagnostic Logging (REQ-RETRY-007, SCN-RETRY-007-*, LOG-RETRY-*)

- **Setup**: Enable diagnostic mode via flag file in tmp_path. Monkeypatch `save_diagnostic` to capture calls.
- **Assertion**: Verify content strings match the exact format from observability.md. Verify `name` parameter is always `"retry_extract_keypoints"`.
- **Negative tests**: Disable diagnostic mode and verify `save_diagnostic` is NOT called.

### Contract Test Mocking Approach

Contract tests exercise `extract_keypoints()` as documented in contract.md. They use the same mock setup pattern but do NOT inspect internal state, internal branching, delay computations, or exact call counts beyond what the contract promises.

- **For retry behavior**: Mock the API call to fail transiently then succeed. Verify the function returns a valid result (not empty).
- **For non-retryable errors**: Mock the API call to raise a non-retryable error. Verify the function returns the empty result dict.
- **For exhaustion**: Mock all attempts to fail. Verify the function returns the empty result dict.
- **For timeout parameter**: Mock the API call and capture kwargs. Verify `timeout=30.0` is present.
- **For signature**: Inspect the function signature via `inspect.signature()`. Verify no change from contract.md.

---

## Test Types

| Type | When to Use |
|------|-------------|
| Unit / White-box tests | Individual retry branches, exact delay values, exact call counts, exact diagnostic content, internal state (attempt counter, sleep calls). |
| Contract / Black-box tests | Exercise `extract_keypoints()` public API as documented in contract.md. Verify return value schema, no-exception guarantee, timeout parameter. |
| **Deliverable tests** | **Exercise the retry behavior end-to-end as a caller would: call `extract_keypoints()` with a mocked API that fails transiently, verify the function returns a valid result without crashing. Also: call with a permanently failing API, verify graceful degradation (empty result, no exception).** |

### Deliverable Test Strategy

A deliverable test exercises the retry logic from the caller's perspective:
1. Mock the Anthropic SDK to fail with a retryable error on the first attempt and succeed on the second.
2. Call `extract_keypoints(messages, playbook)` as `session_end.py` or `precompact.py` would.
3. Verify: the function returns a dict containing `new_key_points` (list) and `evaluations` (list).
4. Verify: no exception propagates to the caller.

A second deliverable test exercises exhaustion:
1. Mock the Anthropic SDK to fail on all attempts.
2. Call `extract_keypoints(messages, playbook)`.
3. Verify: the function returns `{"new_key_points": [], "evaluations": []}`.
4. Verify: no exception propagates to the caller.

A third deliverable test exercises the ANTHROPIC_AVAILABLE guard:
1. Set `ANTHROPIC_AVAILABLE = False`.
2. Call `extract_keypoints(messages, playbook)`.
3. Verify: the function returns the empty result without attempting any API call.

These deliverable tests are included in the contract test file as `test_contract_deliverable_*` functions.

---

## Adversarial Test Categories

### Category 1: Boundary Conditions (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-BOUND-001 | Exactly MAX_RETRIES attempts exhausted (not MAX_RETRIES+1) | REQ-RETRY-001, SCN-RETRY-001-04 | With MAX_RETRIES=3, exactly 3 API calls are made (attempts 0, 1, 2). Not 4. Verify call count. |
| TC-BOUND-002 | Exactly MAX_RETRIES-1 delays (not MAX_RETRIES delays) | REQ-RETRY-002, SCN-RETRY-001-04 | With MAX_RETRIES=3, exactly 2 `time.sleep()` calls. No sleep after final attempt. |
| TC-BOUND-003 | MAX_RETRIES=1: single attempt, no retry, no delay | REQ-RETRY-001, REQ-RETRY-008 | Monkeypatch MAX_RETRIES=1. Fail once = immediate exhaustion. Zero sleep calls. |
| TC-BOUND-004 | APIStatusError at status=500 (retryable boundary) | REQ-RETRY-003, SCN-RETRY-003-01 | `status_code >= 500` is True at exactly 500. Verify retried. |
| TC-BOUND-005 | APIStatusError at status=499 (non-retryable boundary) | REQ-RETRY-003, SCN-RETRY-003-02 | `status_code >= 500` is False at 499. Verify NOT retried. |
| TC-BOUND-006 | Jitter minimum: random.uniform returns 0.75 | REQ-RETRY-002, SCN-RETRY-002-01 | Delay = BASE_DELAY * 2^attempt * 0.75. For attempt 0: 2.0 * 1 * 0.75 = 1.5s. |
| TC-BOUND-007 | Jitter maximum: random.uniform returns 1.25 | REQ-RETRY-002, SCN-RETRY-002-01 | Delay = BASE_DELAY * 2^attempt * 1.25. For attempt 0: 2.0 * 1 * 1.25 = 2.5s. |
| TC-BOUND-008 | Success on final attempt (attempt MAX_RETRIES-1) | REQ-RETRY-001, SCN-RETRY-001-03 | Exactly MAX_RETRIES-1 delays occur, then success. No exhaustion log. |

### Category 2: Error Classification Edge Cases (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-ERR-001 | APITimeoutError is caught as retryable (not as APIConnectionError) | REQ-RETRY-003, SCN-RETRY-003-05 | APITimeoutError IS-A APIConnectionError. Verify the correct handler catches it and logs "APITimeoutError" not "APIConnectionError". |
| TC-ERR-002 | RateLimitError (429) is retryable, not caught by 4xx handler | REQ-RETRY-003 | RateLimitError must be caught before the APIStatusError handler. Verify retried. |
| TC-ERR-003 | APIStatusError with status_code=503 retried via 5xx branch | REQ-RETRY-003, SCN-RETRY-003-01 | Falls through to APIStatusError handler, `status_code >= 500` branch. |
| TC-ERR-004 | APIStatusError with status_code=404 not retried | REQ-RETRY-003, SCN-RETRY-003-02 | Falls to APIStatusError handler, `status_code < 500` branch. Returns empty. |
| TC-ERR-005 | APIResponseValidationError not retried | REQ-RETRY-003, SCN-RETRY-003-03 | Sibling of APIStatusError under APIError. NOT caught by APIStatusError handler. Returns empty. |
| TC-ERR-006 | Unknown APIError subclass not retried | REQ-RETRY-003, SCN-RETRY-003-06 | Caught by APIError catch-all. Returns empty. |
| TC-ERR-007 | Bare Exception (RuntimeError) not retried | REQ-RETRY-003, SCN-RETRY-003-04 | Caught by Exception catch-all. Returns empty. |
| TC-ERR-008 | AuthenticationError (401) not retried | REQ-RETRY-004, SCN-RETRY-004-01 | Subclass of APIStatusError with status < 500. Returns empty. |
| TC-ERR-009 | PermissionDeniedError (403) not retried | REQ-RETRY-004, SCN-RETRY-004-03 | Subclass of APIStatusError with status < 500. Returns empty. |
| TC-ERR-010 | UnprocessableEntityError (422) not retried | REQ-RETRY-004, SCN-RETRY-004-04 | Subclass of APIStatusError with status < 500. Returns empty. |
| TC-ERR-011 | BadRequestError (400) not retried, no diagnostic when mode off | REQ-RETRY-004, SCN-RETRY-004-02 | Non-retryable + diagnostic mode disabled. No save_diagnostic call. |

### Category 3: Negative Paths (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-NEG-001 | Non-retryable error on first attempt | REQ-RETRY-004, SCN-RETRY-004-01 | Single API call, immediate empty return. Zero delays. |
| TC-NEG-002 | Retryable errors on all attempts leading to exhaustion | REQ-RETRY-005, SCN-RETRY-005-01 | MAX_RETRIES API calls, MAX_RETRIES-1 delays, then empty return. |
| TC-NEG-003 | Mixed error types: retryable then non-retryable | REQ-RETRY-003, REQ-RETRY-004 | Attempt 0 raises APITimeoutError (retried), attempt 1 raises AuthenticationError (not retried). Returns empty immediately. Only 1 delay. |
| TC-NEG-004 | ANTHROPIC_AVAILABLE = False: early return before retry loop | REQ-RETRY-001, INV-RETRY-002 | The guard branch returns empty before the retry loop is ever entered. Zero API calls, zero delays. |
| TC-NEG-005 | No diagnostic log on first-attempt success | REQ-RETRY-007, SCN-RETRY-007-04 | Normal path: attempt 0 succeeds. No retry-related save_diagnostic calls even with diagnostic mode on. |

### Category 4: Jitter and Timing (COVERED)

| TC-* | Test Case | REQ/INV | Description |
|------|-----------|---------|-------------|
| TC-TIME-001 | Sleep called with correct value in [0.75*base, 1.25*base] | REQ-RETRY-002, SCN-RETRY-002-01 | Fix jitter, verify exact sleep argument matches formula. |
| TC-TIME-002 | No sleep after final attempt | REQ-RETRY-001, REQ-RETRY-002, SCN-RETRY-001-04 | After attempt MAX_RETRIES-1 fails, return immediately. No time.sleep call for final attempt. |
| TC-TIME-003 | Delay doubles between consecutive attempts | REQ-RETRY-002 | Attempt 0 delay base = 2.0. Attempt 1 delay base = 4.0. Verify doubling. |
| TC-TIME-004 | Timeout=30.0 passed on every attempt | REQ-RETRY-006, SCN-RETRY-006-01 | Capture kwargs of every messages.create call. Verify timeout=30.0 on each. |

**Summary: 4 of 5 adversarial categories covered (Boundary, Error Classification, Negative Paths, Jitter/Timing). Resource exhaustion is out of scope -- the retry loop is bounded by MAX_RETRIES (max 3 attempts) and per-request timeout (30s), making resource exhaustion infeasible.**

---

## Invariant Test Coverage

| INV-* | Invariant | Test Function | Verification |
|-------|-----------|---------------|-------------|
| INV-RETRY-001 | Function signature unchanged | test_invariant_function_signature_unchanged | Use `inspect.signature()` on `extract_keypoints`. Verify parameters are `(messages: list[dict], playbook: dict, diagnostic_name: str = "reflection")` and return type is `dict`. |
| INV-RETRY-002 | Only client.messages.create() is retried | test_invariant_only_api_call_retried | Mock `load_template` and `load_settings` with call counters. After a retry scenario (1 failure + 1 success), verify `load_template` called exactly once, `load_settings` called exactly once, but `messages.create` called exactly twice. Prompt construction runs once. |
| INV-RETRY-003 | Total time within hook timeout | test_invariant_total_time_bounded | Compute worst-case: `MAX_RETRIES * 30 + sum(BASE_DELAY * 2^i * 1.25 for i in range(MAX_RETRIES-1))`. With defaults: `3*30 + 2.5 + 5.0 = 97.5`. Assert `97.5 < 120`. This is a mathematical assertion, not a timing test. |
| INV-RETRY-004 | Return value always valid extraction result | test_invariant_return_value_always_valid | Test all error paths (each retryable type exhausted, each non-retryable type, bare Exception). For every path, assert result is a dict with keys `"new_key_points"` (list) and `"evaluations"` (list). No exception propagates. |

---

## Instrumentation Test Strategy

The retry module uses file-based diagnostics (not metrics or structured logging). Instrumentation tests verify that `save_diagnostic()` is called at the right times and with the right content.

### Diagnostic Mocking Approach

| Component | Mock Approach | Verification |
|-----------|---------------|-------------|
| `is_diagnostic_mode()` | Create/remove `.claude/diagnostic_mode` flag file in temp directory controlled by `CLAUDE_PROJECT_DIR` | Check return value of `is_diagnostic_mode()` |
| `save_diagnostic()` | Monkeypatch to a callable that appends `(content, name)` to a list. This provides deterministic capture without file I/O timing issues. | Assert content and name match expected LOG-RETRY-* format from observability.md. |

### LOG-RETRY-001: Per-Attempt Retry Failure

| Test Function | Scenario | Verification |
|---------------|----------|-------------|
| test_instrumentation_per_attempt_log_on_retryable | Diagnostic mode enabled + APITimeoutError on attempt 0, success on attempt 1 | `save_diagnostic` called with content matching `"Retry attempt 1/3 failed: APITimeoutError: {msg}. Next attempt in {delay}s"` and name `"retry_extract_keypoints"`. |
| test_instrumentation_per_attempt_log_two_failures | Diagnostic mode enabled + APIConnectionError on attempts 0 and 1, success on attempt 2 | `save_diagnostic` called twice for per-attempt logs (attempt 0 and attempt 1). Content includes correct 1-indexed attempt numbers ("1/3" and "2/3") and correct delay values. |
| test_instrumentation_per_attempt_not_emitted_diagnostic_off | Diagnostic mode disabled + retryable error on attempt 0, success on attempt 1 | `save_diagnostic` NOT called. Retry still proceeds normally. |
| test_instrumentation_per_attempt_not_emitted_on_final_attempt | Diagnostic mode enabled + retryable error on all 3 attempts | Per-attempt log emitted for attempts 0 and 1 only (not attempt 2). Attempt 2 triggers LOG-RETRY-002 exhaustion instead. |

### LOG-RETRY-002: Final Outcome

| Test Function | Scenario | Verification |
|---------------|----------|-------------|
| test_instrumentation_exhaustion_logged | Diagnostic mode enabled + InternalServerError on all 3 attempts | `save_diagnostic` called with content `"All 3 attempts failed for extract_keypoints(). Returning empty result."` and name `"retry_extract_keypoints"`. |
| test_instrumentation_success_after_retry_logged | Diagnostic mode enabled + RateLimitError on attempt 0, success on attempt 1 | `save_diagnostic` called with content `"extract_keypoints() succeeded on attempt 2 after 1 retries."` and name `"retry_extract_keypoints"`. |
| test_instrumentation_success_after_two_retries_logged | Diagnostic mode enabled + failure on attempts 0 and 1, success on attempt 2 | `save_diagnostic` called with content `"extract_keypoints() succeeded on attempt 3 after 2 retries."`. |
| test_instrumentation_no_success_log_on_first_attempt | Diagnostic mode enabled + success on attempt 0 | No retry-related `save_diagnostic` calls at all (attempt 0 success is normal path). |
| test_instrumentation_exhaustion_not_logged_diagnostic_off | Diagnostic mode disabled + all attempts fail | `save_diagnostic` NOT called. Empty result still returned. |

### LOG-RETRY-003: Non-Retryable Error

| Test Function | Scenario | Verification |
|---------------|----------|-------------|
| test_instrumentation_non_retryable_logged | Diagnostic mode enabled + AuthenticationError on attempt 0 | `save_diagnostic` called with content `"Non-retryable error in extract_keypoints(): AuthenticationError: {msg}. Returning empty result."` and name `"retry_extract_keypoints"`. |
| test_instrumentation_non_retryable_api_response_validation | Diagnostic mode enabled + APIResponseValidationError on attempt 0 | Content includes `"APIResponseValidationError"`. |
| test_instrumentation_non_retryable_bare_exception | Diagnostic mode enabled + RuntimeError on attempt 0 | Content includes `"RuntimeError"`. |
| test_instrumentation_non_retryable_unknown_api_error | Diagnostic mode enabled + unknown APIError subclass on attempt 0 | Content includes the actual class name via `type(exc).__name__`. |
| test_instrumentation_non_retryable_not_logged_diagnostic_off | Diagnostic mode disabled + non-retryable error | `save_diagnostic` NOT called. Empty result still returned. |

---

## Contract Test Exclusions

| REQ-* | Contract Test? | Notes |
|-------|---------------|-------|
| REQ-RETRY-001 | YES | Contract test verifies that `extract_keypoints()` returns a valid result after transient API failure (retry succeeds). |
| REQ-RETRY-002 | YES | Contract test verifies that backoff occurs (time.sleep is called at least once between retry attempts). Exact delay formula is white-box concern. |
| REQ-RETRY-003 | YES | Contract test verifies retryable errors are retried and non-retryable errors return empty immediately. |
| REQ-RETRY-004 | YES | Contract test verifies non-retryable errors return the empty result dict immediately without retry. |
| REQ-RETRY-005 | YES | Contract test verifies that exhaustion of all attempts returns the empty result dict. |
| REQ-RETRY-006 | YES | Contract test captures `messages.create` kwargs and verifies `timeout=30.0`. |
| REQ-RETRY-007 | YES | Contract test verifies diagnostic behavior: no diagnostic logs when diagnostic mode is off. Exact log content format is white-box concern. |
| REQ-RETRY-008 | YES | Contract test verifies `MAX_RETRIES` and `BASE_DELAY` are accessible as module-level attributes with expected types. |

All REQ-RETRY-* have contract tests. No exclusions needed.

---

## Failure Mode Coverage

Mapping failure modes from the design and spec to test cases.

| FM-* | Failure Mode | Mitigated By | Test Functions |
|------|-------------|-------------|----------------|
| FM-RETRY-001 | Exception propagates to caller, crashing hook | INV-RETRY-004, REQ-RETRY-004, REQ-RETRY-005 | test_invariant_return_value_always_valid, test_contract_non_retryable_returns_empty, test_contract_exhaustion_returns_empty |
| FM-RETRY-002 | Retry count off-by-one (4 attempts instead of 3) | REQ-RETRY-001, SCN-RETRY-001-04 | test_scn_all_three_fail_return_empty (verifies exactly 3 API calls), TC-BOUND-001 |
| FM-RETRY-003 | Sleep after final attempt (wasted time) | REQ-RETRY-002, SCN-RETRY-001-04 | test_scn_all_three_fail_return_empty (verifies exactly 2 sleep calls), TC-BOUND-002 |
| FM-RETRY-004 | Non-retryable error retried (wasted time + delay) | REQ-RETRY-003, REQ-RETRY-004 | test_non_retryable_immediate_return, test_scn_api_status_error_404_not_retried |
| FM-RETRY-005 | APITimeoutError caught as APIConnectionError (wrong log) | REQ-RETRY-003, SCN-RETRY-003-05 | test_scn_api_timeout_caught_before_api_connection, TC-ERR-001 |
| FM-RETRY-006 | RateLimitError (429) caught by 4xx handler as non-retryable | REQ-RETRY-003 | TC-ERR-002 (verify RateLimitError is retried) |
| FM-RETRY-007 | Backoff delay has no jitter (thundering herd) | REQ-RETRY-002, SCN-RETRY-002-01 | test_scn_jitter_applied_to_delay (verify random.uniform is called) |
| FM-RETRY-008 | Total retry time exceeds hook timeout | INV-RETRY-003, REQ-RETRY-006, REQ-RETRY-008 | test_invariant_total_time_bounded |
| FM-RETRY-009 | Function signature changed, breaking callers | INV-RETRY-001 | test_invariant_function_signature_unchanged |
| FM-RETRY-010 | Prompt construction runs inside retry loop (wasteful) | INV-RETRY-002 | test_invariant_only_api_call_retried |
| FM-RETRY-011 | Diagnostic logging crashes the retry loop | REQ-RETRY-007 | test_scn_no_diagnostic_when_mode_off, test_scn_per_attempt_diagnostic_log |

---

## Test File Organization

| File | Purpose | Location |
|------|---------|----------|
| `tests/test_retry_whitebox.py` | White-box tests covering all REQ-RETRY-*, SCN-RETRY-*, INV-RETRY-*, LOG-RETRY-* + adversarial tests | `/data/agentic_context_engineering/tests/test_retry_whitebox.py` |
| `tests/test_retry_contract.py` | Contract/black-box tests covering all REQ-RETRY-* + deliverable tests | `/data/agentic_context_engineering/tests/test_retry_contract.py` |

### File Headers

White-box test file:
```python
# Spec: docs/retry/spec.md
# Testing: docs/retry/testing.md
```

Contract test file:
```python
# Spec: docs/retry/spec.md
# Contract: docs/retry/contract.md
# Testing: docs/retry/testing.md
```

### Fixtures and Helpers Needed

#### Common to Both Files

```
project_dir(tmp_path, monkeypatch)       -- Set CLAUDE_PROJECT_DIR to temp dir, create .claude/ structure
enable_diagnostic(project_dir)           -- Create diagnostic_mode flag file
_setup_extract_keypoints_mocks(monkeypatch) -- Mock Anthropic client, load_template, load_settings,
                                             ANTHROPIC_AVAILABLE, env vars. Returns (mock_client, mock_text_block).
_make_mock_response(json_text)           -- Create a mock response object with content[0].text = json_text
```

#### White-box File Only

```
_capture_sleep(monkeypatch)              -- Monkeypatch time.sleep to capture delay values in a list
_capture_diagnostic(monkeypatch)         -- Monkeypatch save_diagnostic to capture (content, name) pairs
_fix_jitter(monkeypatch, value=1.0)     -- Monkeypatch random.uniform to return a fixed value
_make_side_effects(failures, success)    -- Create a side_effect list: N exceptions then a success response
```

#### Contract File Only

```
_setup_retry_mocks(monkeypatch)          -- Minimal mock setup for contract tests (same as common helper
                                            but contract tests do not inspect internal call details)
```

---

## Verification Plan (Phase 2 Checklist)

Before claiming Phase 2 COMPLETE, the following must pass:

1. `pytest tests/test_retry_whitebox.py tests/test_retry_contract.py -v` -- all tests pass
2. `pytest tests/test_retry_whitebox.py tests/test_retry_contract.py --cov=src/hooks/common --cov-report=term-missing` -- retry-logic coverage >= 80%. **Scope limitation:** The overall file coverage will be lower because `src/hooks/common.py` contains non-retry functions that are outside this test scope. Verify that all missed lines in the `term-missing` output fall within non-retry functions, and that zero missed lines fall within the retry loop of `extract_keypoints()`.
3. `pytest tests/test_retry_whitebox.py tests/test_retry_contract.py -x --tb=short` -- quick validation
4. `pytest tests/test_retry_whitebox.py tests/test_retry_contract.py -p pytest_repeat --count=1000 --failfast` -- flaky detection (requires `pytest-repeat`)
5. Break-the-code verification: comment out a critical line (e.g., the `if attempt < MAX_RETRIES - 1:` check, or the `break` after success), run tests, verify failure. **Restore immediately after each break test.**
6. Every `@tests` annotation references a valid REQ-RETRY-*/SCN-RETRY-* from spec.md
7. Every `@tests-contract` annotation references a valid REQ-RETRY-* from spec.md
8. Every `@tests-invariant` annotation references a valid INV-RETRY-* from spec.md
9. Every `@tests-instrumentation` annotation references a valid LOG-RETRY-* from observability.md
10. No `pytest.skip()` or `@pytest.mark.skip` anywhere
