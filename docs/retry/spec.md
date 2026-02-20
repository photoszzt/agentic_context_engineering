# Requirements Specification: Retry Logic with Exponential Backoff

## Intent Traceability

This section preserves the success criteria from the approved intent.
The full intent document is in `.planning/intent.md` for historical reference.

| SC-* | Success Criterion | REQ-*/SCN-*/INV-* |
|------|-------------------|-------------------|
| SC-RETRY-001 | `extract_keypoints()` retries the `client.messages.create()` call up to `MAX_RETRIES` total attempts (module-level constant, default: 3) when a retryable error occurs. Semantics: `MAX_RETRIES=3` means 3 total attempts -- attempt 0 is the initial try, attempts 1 and 2 are retries. There are 2 backoff delays (between attempts 0-1 and between attempts 1-2). There is NO delay after the final attempt. After exhausting all attempts, it returns the empty result `{"new_key_points": [], "evaluations": []}` instead of propagating the exception. | REQ-RETRY-001, REQ-RETRY-008, SCN-RETRY-001-01, SCN-RETRY-001-02, SCN-RETRY-001-03, SCN-RETRY-001-04, INV-RETRY-004 |
| SC-RETRY-002 | Delay between retries follows exponential backoff: `BASE_DELAY * (2 ^ attempt)` where `BASE_DELAY` is 2.0 seconds (module-level constant) and `attempt` is the 0-indexed attempt number that just failed. Delays occur ONLY between attempts (not after the final attempt). With MAX_RETRIES=3, there are exactly 2 delays: delay after attempt 0 = `2 * 2^0 = 2s`, delay after attempt 1 = `2 * 2^1 = 4s`. A jitter of +/- 25% is applied to each delay (multiply by uniform random in [0.75, 1.25]). Sleep is performed with `time.sleep()`. | REQ-RETRY-002, REQ-RETRY-008, SCN-RETRY-002-01 |
| SC-RETRY-003 | Error classification: retryable errors (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError, APIStatusError with status_code >= 500) are retried; non-retryable errors (AuthenticationError, PermissionDeniedError, NotFoundError, BadRequestError, UnprocessableEntityError, APIStatusError with 4xx except 429, APIResponseValidationError) return empty immediately; APIError catch-all and bare Exception catch-all return empty immediately. APITimeoutError must be caught before APIConnectionError. | REQ-RETRY-003, REQ-RETRY-004, SCN-RETRY-003-01, SCN-RETRY-003-02, SCN-RETRY-003-03, SCN-RETRY-003-04, SCN-RETRY-003-05, SCN-RETRY-003-06, INV-RETRY-004 |
| SC-RETRY-004 | Non-retryable errors immediately return the empty result `{"new_key_points": [], "evaluations": []}` without retry. They are logged to diagnostics before returning. | REQ-RETRY-004, SCN-RETRY-004-01, SCN-RETRY-004-02, SCN-RETRY-004-03, SCN-RETRY-004-04 |
| SC-RETRY-005 | After exhausting all retries on a retryable error, the function returns the empty result `{"new_key_points": [], "evaluations": []}`. | REQ-RETRY-005, SCN-RETRY-005-01, INV-RETRY-004 |
| SC-RETRY-006 | Each `client.messages.create()` call uses a per-request timeout of 30 seconds via the Anthropic SDK `timeout` parameter. | REQ-RETRY-006, SCN-RETRY-006-01 |
| SC-RETRY-007 | When retries occur, each attempt is logged to diagnostics with: attempt number (1-indexed for human readability), error type (class name), error message, delay before next attempt. The final outcome (success after N retries, or failure after exhausting retries) is also logged. Logging uses `save_diagnostic()` gated by `is_diagnostic_mode()`. | REQ-RETRY-007, SCN-RETRY-007-01, SCN-RETRY-007-02, SCN-RETRY-007-03, SCN-RETRY-007-04 |

---

## Requirements

### REQ-RETRY-001: Retry Loop {#REQ-RETRY-001}
- **Implements**: SC-RETRY-001
- **GIVEN**: `extract_keypoints()` is called and reaches the `client.messages.create()` call
- **WHEN**: A retryable error occurs (as classified in REQ-RETRY-003)
- **THEN**:
  - The call is retried up to `MAX_RETRIES` total attempts (default: 3)
  - Attempts are 0-indexed: attempt 0 is the initial try, attempts 1 and 2 are retries
  - Between attempts, an exponential backoff delay is applied (REQ-RETRY-002)
  - There are exactly `MAX_RETRIES - 1` delays (2 delays for MAX_RETRIES=3)
  - There is NO delay after the final attempt
  - If the call succeeds on any attempt, the response is used normally (no change to downstream processing)
  - If all attempts are exhausted, the function returns the empty result (REQ-RETRY-005)
  - The retry loop structure is: `for attempt in range(MAX_RETRIES):`

### REQ-RETRY-002: Exponential Backoff with Jitter {#REQ-RETRY-002}
- **Implements**: SC-RETRY-002
- **GIVEN**: A retryable error occurred on attempt N (0-indexed) and N < MAX_RETRIES - 1 (not the final attempt)
- **WHEN**: The retry loop prepares to sleep before the next attempt
- **THEN**:
  - Base delay is computed as: `BASE_DELAY * (2 ** attempt)` where `attempt` is the 0-indexed attempt number that just failed
  - With defaults (BASE_DELAY=2.0): attempt 0 delay = 2.0s, attempt 1 delay = 4.0s
  - Jitter is applied by multiplying the base delay by `random.uniform(0.75, 1.25)`
  - The actual sleep duration = `base_delay * jitter_factor`
  - Sleep is performed with `time.sleep(actual_delay)`
  - No delay occurs after the final attempt (attempt == MAX_RETRIES - 1)

### REQ-RETRY-003: Error Classification {#REQ-RETRY-003}
- **Implements**: SC-RETRY-003
- **GIVEN**: An exception is raised by `client.messages.create()`
- **WHEN**: The retry loop catches the exception
- **THEN**: The exception is classified according to this table, and the catch order in the except chain matches the order below (top to bottom):

  **Retryable errors (will be retried):**

  | # | Exception Type | Condition | Catch Order Position | Why Retryable |
  |---|----------------|-----------|---------------------|---------------|
  | 1 | `anthropic.APITimeoutError` | Always | FIRST (before APIConnectionError because APITimeoutError IS-A APIConnectionError) | Transient network/server timeout |
  | 2 | `anthropic.APIConnectionError` | Always | SECOND | Transient connection failure |
  | 3 | `anthropic.RateLimitError` | Always (HTTP 429) | THIRD | Rate limit, likely clears after backoff |
  | 4 | `anthropic.InternalServerError` | Always (HTTP 500) | FOURTH | Transient server error |
  | 5 | `anthropic.APIStatusError` | `status_code >= 500` | FIFTH (catch-all for 5xx not covered above) | Fallback for any 5xx |

  **Non-retryable errors (immediate graceful degradation):**

  | # | Exception Type | Condition | Catch Order Position | Why Non-Retryable |
  |---|----------------|-----------|---------------------|-------------------|
  | 6 | `anthropic.APIStatusError` | `status_code < 500` (4xx except 429, already caught by RateLimitError) | SIXTH (catches AuthenticationError 401, PermissionDeniedError 403, NotFoundError 404, BadRequestError 400, UnprocessableEntityError 422, ConflictError 409, and any other 4xx) | Client errors don't self-resolve |
  | 7 | `anthropic.APIResponseValidationError` | Always | SEVENTH | SDK could not parse response; not transient |

  **Note on row 6 vs row 7 ordering**: `APIResponseValidationError` is NOT a subclass of `APIStatusError` (they are siblings under `APIError`). Either ordering of rows 6 and 7 produces identical behavior because neither except clause can catch the other's exception type. This document uses the ordering where `APIStatusError` (row 6) precedes `APIResponseValidationError` (row 7) to match the implementation in design.md.

  **Fallback catch-all:**

  | # | Exception Type | Condition | Catch Order Position | Behavior |
  |---|----------------|-----------|---------------------|----------|
  | 8 | `anthropic.APIError` | Any subclass not matched above | EIGHTH | NOT retried -- defensive fallback for unknown APIError subclasses |
  | 9 | `Exception` | Any non-APIError exception | NINTH (outermost) | NOT retried -- may indicate programming bugs |

  **Implementation note on catch ordering**: Rows 1-5 (retryable) and rows 6-7 (non-retryable) can share a single `except` clause each using a tuple, OR be separate `except` clauses. The critical ordering requirements are:
  - `APITimeoutError` MUST be caught before `APIConnectionError` (row 1 before row 2)
  - `RateLimitError` (row 3, HTTP 429) MUST be caught before the `APIStatusError` 4xx handler (row 6), since 429 is retryable but other 4xx are not
  - `InternalServerError` (row 4, HTTP 500) MUST be caught before the `APIStatusError` 5xx catch-all (row 5)
  - `APIStatusError` (row 6) and `APIResponseValidationError` (row 7) may appear in either order -- they are sibling classes under `APIError` and neither catches the other's exceptions (see note above)
  - The `APIError` catch-all (row 8) MUST come after all specific APIError subclass handlers
  - The bare `Exception` catch-all (row 9) MUST be the outermost/last handler

  **Note on APIStatusError row 5 vs row 6**: A single `except anthropic.APIStatusError` clause can handle both by checking `exc.status_code >= 500` inside the handler -- if True, treat as retryable; if False, treat as non-retryable. This is an acceptable implementation approach.

### REQ-RETRY-004: Non-Retryable Immediate Return {#REQ-RETRY-004}
- **Implements**: SC-RETRY-004
- **GIVEN**: A non-retryable error is caught (rows 6-9 in REQ-RETRY-003)
- **WHEN**: The error is classified as non-retryable
- **THEN**:
  - The error is logged to diagnostics (REQ-RETRY-007)
  - The function immediately returns `{"new_key_points": [], "evaluations": []}`
  - No retry is attempted
  - No backoff delay occurs

### REQ-RETRY-005: Post-Exhaustion Return {#REQ-RETRY-005}
- **Implements**: SC-RETRY-005
- **GIVEN**: All `MAX_RETRIES` attempts have been made and all failed with retryable errors
- **WHEN**: The final attempt (attempt MAX_RETRIES - 1) fails
- **THEN**:
  - The exhaustion is logged to diagnostics (REQ-RETRY-007)
  - The function returns `{"new_key_points": [], "evaluations": []}`
  - No delay occurs after the final failed attempt

### REQ-RETRY-006: Per-Request Timeout {#REQ-RETRY-006}
- **Implements**: SC-RETRY-006
- **GIVEN**: `extract_keypoints()` calls `client.messages.create()`
- **WHEN**: The call is made (on any attempt, 0 through MAX_RETRIES - 1)
- **THEN**:
  - The `timeout` parameter is set to `30.0` (seconds)
  - This overrides the SDK default timeout of 600 seconds
  - The call signature becomes: `client.messages.create(model=model, max_tokens=4096, messages=[...], timeout=30.0)`

### REQ-RETRY-007: Diagnostic Logging {#REQ-RETRY-007}
- **Implements**: SC-RETRY-007
- **GIVEN**: A retry event occurs (retryable error caught, non-retryable error caught, success after retry, or all retries exhausted)
- **WHEN**: The event is processed
- **THEN**:
  - All logging is gated by `is_diagnostic_mode()` -- if False, no logging occurs
  - All logging uses `save_diagnostic(content, name)` with `name="retry_extract_keypoints"`
  - **Per-attempt logging (retryable error, not final attempt)**:
    - Content: `"Retry attempt {N}/{MAX_RETRIES} failed: {ErrorClassName}: {error_message}. Next attempt in {delay:.1f}s"`
    - N is 1-indexed for human readability (attempt 0 logs as "1", attempt 1 logs as "2")
  - **Per-attempt logging (non-retryable error)**:
    - Content: `"Non-retryable error in extract_keypoints(): {ErrorClassName}: {error_message}. Returning empty result."`
  - **Exhaustion logging (final retryable error, no more attempts)**:
    - Content: `"All {MAX_RETRIES} attempts failed for extract_keypoints(). Returning empty result."`
  - **Success after retry logging**:
    - Content: `"extract_keypoints() succeeded on attempt {N} after {N-1} retries."`
    - N is 1-indexed (attempt 0 succeeding is NOT logged since that is the normal case with no retry)
    - Only logged when N > 1 (i.e., at least one retry occurred before success)

### REQ-RETRY-008: Module-Level Constants {#REQ-RETRY-008}
- **Implements**: SC-RETRY-001, SC-RETRY-002, CON-RETRY-003
- **GIVEN**: The retry logic needs configurable parameters
- **WHEN**: `common.py` is loaded
- **THEN**:
  - `MAX_RETRIES = 3` is defined as a module-level constant (int)
  - `BASE_DELAY = 2.0` is defined as a module-level constant (float)
  - These constants are placed near the top of `common.py` alongside existing constants (e.g., after `SECTION_SLUGS`)
  - These constants are internal to `common.py` and do not change the public API

---

## Scenarios

### SCN-RETRY-001-01: First Attempt Succeeds -- No Retry {#SCN-RETRY-001-01}
- **Implements**: REQ-RETRY-001
- **GIVEN**: `extract_keypoints()` is called with valid inputs
- **AND**: `client.messages.create()` succeeds on the first attempt (attempt 0)
- **WHEN**: The API call completes successfully
- **THEN**:
  - The response is processed normally (JSON parsing, extraction)
  - No retry occurs
  - No backoff delay occurs
  - No retry-related diagnostic log is emitted
  - `time.sleep()` is NOT called

### SCN-RETRY-001-02: First Attempt Fails Retryable, Second Succeeds {#SCN-RETRY-001-02}
- **Implements**: REQ-RETRY-001, REQ-RETRY-002
- **GIVEN**: `extract_keypoints()` is called with valid inputs
- **AND**: `client.messages.create()` raises `anthropic.APITimeoutError` on attempt 0
- **AND**: `client.messages.create()` succeeds on attempt 1
- **WHEN**: The retry loop executes
- **THEN**:
  - Attempt 0 fails with APITimeoutError
  - One backoff delay occurs: `2.0 * 2^0 * jitter = ~2.0s` (between 1.5s and 2.5s)
  - `time.sleep()` is called exactly once
  - Attempt 1 succeeds
  - The response from attempt 1 is processed normally
  - Total: 2 API calls, 1 delay, 1 retry

### SCN-RETRY-001-03: First Two Attempts Fail Retryable, Third Succeeds {#SCN-RETRY-001-03}
- **Implements**: REQ-RETRY-001, REQ-RETRY-002
- **GIVEN**: `extract_keypoints()` is called with valid inputs
- **AND**: `client.messages.create()` raises `anthropic.APIConnectionError` on attempts 0 and 1
- **AND**: `client.messages.create()` succeeds on attempt 2
- **WHEN**: The retry loop executes
- **THEN**:
  - Attempt 0 fails: delay ~2.0s (BASE_DELAY * 2^0 * jitter)
  - Attempt 1 fails: delay ~4.0s (BASE_DELAY * 2^1 * jitter)
  - Attempt 2 succeeds
  - `time.sleep()` is called exactly twice
  - The response from attempt 2 is processed normally
  - Total: 3 API calls, 2 delays, 2 retries

### SCN-RETRY-001-04: All Three Attempts Fail Retryable -- Return Empty {#SCN-RETRY-001-04}
- **Implements**: REQ-RETRY-001, REQ-RETRY-005
- **GIVEN**: `extract_keypoints()` is called with valid inputs
- **AND**: `client.messages.create()` raises `anthropic.RateLimitError` on all 3 attempts (0, 1, 2)
- **WHEN**: The retry loop exhausts all attempts
- **THEN**:
  - Attempt 0 fails: delay ~2.0s
  - Attempt 1 fails: delay ~4.0s
  - Attempt 2 fails: NO delay (final attempt)
  - `time.sleep()` is called exactly twice (not three times)
  - The function returns `{"new_key_points": [], "evaluations": []}`
  - The exception is NOT propagated

### SCN-RETRY-002-01: Jitter Applied to Delay {#SCN-RETRY-002-01}
- **Implements**: REQ-RETRY-002
- **GIVEN**: A retryable error occurs on attempt 0
- **AND**: `random.uniform(0.75, 1.25)` returns a specific jitter factor J
- **WHEN**: The backoff delay is computed
- **THEN**:
  - Base delay = `2.0 * 2^0 = 2.0`
  - Actual delay = `2.0 * J`
  - If J = 0.75: actual delay = 1.5s
  - If J = 1.25: actual delay = 2.5s
  - `time.sleep()` is called with the actual delay value
  - The delay is always in the range `[BASE_DELAY * 2^attempt * 0.75, BASE_DELAY * 2^attempt * 1.25]`

### SCN-RETRY-003-01: APIStatusError with 503 -- Retried {#SCN-RETRY-003-01}
- **Implements**: REQ-RETRY-003
- **GIVEN**: `client.messages.create()` raises `anthropic.APIStatusError` with `status_code=503`
- **WHEN**: The error is classified
- **THEN**:
  - `status_code >= 500` is True
  - The error is classified as retryable
  - The retry loop continues to the next attempt (with backoff delay if not the final attempt)

### SCN-RETRY-003-02: APIStatusError with 404 -- Not Retried {#SCN-RETRY-003-02}
- **Implements**: REQ-RETRY-003, REQ-RETRY-004
- **GIVEN**: `client.messages.create()` raises `anthropic.APIStatusError` with `status_code=404`
- **WHEN**: The error is classified
- **THEN**:
  - `status_code >= 500` is False
  - The error is classified as non-retryable
  - The function immediately returns `{"new_key_points": [], "evaluations": []}`
  - No retry, no delay

### SCN-RETRY-003-03: APIResponseValidationError -- Not Retried {#SCN-RETRY-003-03}
- **Implements**: REQ-RETRY-003, REQ-RETRY-004
- **GIVEN**: `client.messages.create()` raises `anthropic.APIResponseValidationError`
- **WHEN**: The error is classified
- **THEN**:
  - The error is a subclass of `APIError` but NOT of `APIStatusError`
  - The error is classified as non-retryable
  - The function immediately returns `{"new_key_points": [], "evaluations": []}`
  - No retry, no delay

### SCN-RETRY-003-04: Unknown Non-APIError Exception -- Not Retried {#SCN-RETRY-003-04}
- **Implements**: REQ-RETRY-003, REQ-RETRY-004
- **GIVEN**: `client.messages.create()` raises a `RuntimeError("unexpected")` (not an `anthropic.APIError` subclass)
- **WHEN**: The error is caught by the bare `Exception` handler
- **THEN**:
  - The error is classified as non-retryable
  - The function immediately returns `{"new_key_points": [], "evaluations": []}`
  - No retry, no delay

### SCN-RETRY-003-05: APITimeoutError Caught Before APIConnectionError {#SCN-RETRY-003-05}
- **Implements**: REQ-RETRY-003
- **GIVEN**: `client.messages.create()` raises `anthropic.APITimeoutError` (which IS-A `APIConnectionError`)
- **WHEN**: The except chain processes the exception
- **THEN**:
  - The `APITimeoutError` handler catches it (not the `APIConnectionError` handler)
  - Both are retryable, so functional behavior is the same
  - But the diagnostic log reports the correct error type: `"APITimeoutError"`, not `"APIConnectionError"`

### SCN-RETRY-003-06: Unknown APIError Subclass -- Not Retried {#SCN-RETRY-003-06}
- **Implements**: REQ-RETRY-003
- **GIVEN**: `client.messages.create()` raises an exception that is a subclass of `anthropic.APIError` but is not matched by any specific handler (hypothetical future SDK exception)
- **WHEN**: The `APIError` catch-all handler catches it
- **THEN**:
  - The error is classified as non-retryable
  - The function immediately returns `{"new_key_points": [], "evaluations": []}`
  - The diagnostic log records the exception class name and message

### SCN-RETRY-004-01: Non-Retryable Error Logs Then Returns Empty {#SCN-RETRY-004-01}
- **Implements**: REQ-RETRY-004, REQ-RETRY-007
- **GIVEN**: `client.messages.create()` raises `anthropic.AuthenticationError` on attempt 0
- **AND**: `is_diagnostic_mode()` returns True
- **WHEN**: The error is caught
- **THEN**:
  - `save_diagnostic()` is called with content containing `"Non-retryable error in extract_keypoints(): AuthenticationError: {message}. Returning empty result."`
  - The function returns `{"new_key_points": [], "evaluations": []}`
  - `time.sleep()` is NOT called
  - Only 1 API call was made (no retry)

### SCN-RETRY-004-02: Non-Retryable Error Without Diagnostic Mode {#SCN-RETRY-004-02}
- **Implements**: REQ-RETRY-004, REQ-RETRY-007
- **GIVEN**: `client.messages.create()` raises `anthropic.BadRequestError` on attempt 0
- **AND**: `is_diagnostic_mode()` returns False
- **WHEN**: The error is caught
- **THEN**:
  - `save_diagnostic()` is NOT called (diagnostic mode off)
  - The function returns `{"new_key_points": [], "evaluations": []}`
  - `time.sleep()` is NOT called
  - Only 1 API call was made (no retry)

### SCN-RETRY-004-03: PermissionDeniedError (403) -- Immediate Return, No Retry {#SCN-RETRY-004-03}
- **Implements**: REQ-RETRY-004, REQ-RETRY-003
- **GIVEN**: `client.messages.create()` raises `anthropic.PermissionDeniedError` (HTTP 403) on attempt 0
- **AND**: `is_diagnostic_mode()` returns True
- **WHEN**: The error is caught
- **THEN**:
  - The error is classified as non-retryable (`APIStatusError` with `status_code < 500`)
  - `save_diagnostic()` is called with content containing `"Non-retryable error in extract_keypoints(): PermissionDeniedError: {message}. Returning empty result."`
  - The function returns `{"new_key_points": [], "evaluations": []}`
  - `time.sleep()` is NOT called
  - Only 1 API call was made (no retry)

### SCN-RETRY-004-04: UnprocessableEntityError (422) -- Immediate Return, No Retry {#SCN-RETRY-004-04}
- **Implements**: REQ-RETRY-004, REQ-RETRY-003
- **GIVEN**: `client.messages.create()` raises `anthropic.UnprocessableEntityError` (HTTP 422) on attempt 0
- **AND**: `is_diagnostic_mode()` returns True
- **WHEN**: The error is caught
- **THEN**:
  - The error is classified as non-retryable (`APIStatusError` with `status_code < 500`)
  - `save_diagnostic()` is called with content containing `"Non-retryable error in extract_keypoints(): UnprocessableEntityError: {message}. Returning empty result."`
  - The function returns `{"new_key_points": [], "evaluations": []}`
  - `time.sleep()` is NOT called
  - Only 1 API call was made (no retry)

### SCN-RETRY-005-01: Exhaustion Returns Empty After MAX_RETRIES {#SCN-RETRY-005-01}
- **Implements**: REQ-RETRY-005, REQ-RETRY-007
- **GIVEN**: `client.messages.create()` raises `anthropic.InternalServerError` on all 3 attempts
- **AND**: `is_diagnostic_mode()` returns True
- **WHEN**: The retry loop exhausts all attempts
- **THEN**:
  - `save_diagnostic()` is called for each failed attempt (2 per-attempt logs for attempts 0 and 1) PLUS one exhaustion log
  - The exhaustion log content: `"All 3 attempts failed for extract_keypoints(). Returning empty result."`
  - The function returns `{"new_key_points": [], "evaluations": []}`
  - `time.sleep()` was called exactly twice (delays after attempts 0 and 1, not after attempt 2)

### SCN-RETRY-006-01: Timeout Parameter Passed to SDK {#SCN-RETRY-006-01}
- **Implements**: REQ-RETRY-006
- **GIVEN**: `extract_keypoints()` calls `client.messages.create()`
- **WHEN**: The call is made on any attempt
- **THEN**:
  - The call includes `timeout=30.0` as a keyword argument
  - Full call: `client.messages.create(model=model, max_tokens=4096, messages=[{"role": "user", "content": prompt}], timeout=30.0)`
  - This applies to every attempt (0, 1, 2)

### SCN-RETRY-007-01: Per-Attempt Diagnostic Log on Retryable Error {#SCN-RETRY-007-01}
- **Implements**: REQ-RETRY-007
- **GIVEN**: Attempt 0 fails with `anthropic.APITimeoutError("Request timed out")`
- **AND**: Attempt 1 will be tried (not the final attempt)
- **AND**: `is_diagnostic_mode()` returns True
- **AND**: The computed delay is 2.3s (after jitter)
- **WHEN**: The per-attempt log is emitted
- **THEN**:
  - `save_diagnostic()` is called with:
    - `name`: `"retry_extract_keypoints"`
    - `content`: `"Retry attempt 1/3 failed: APITimeoutError: Request timed out. Next attempt in 2.3s"`

### SCN-RETRY-007-02: No Diagnostic Log When Diagnostic Mode Off {#SCN-RETRY-007-02}
- **Implements**: REQ-RETRY-007
- **GIVEN**: A retryable error occurs on attempt 0
- **AND**: `is_diagnostic_mode()` returns False
- **WHEN**: The retry loop processes the error
- **THEN**:
  - `save_diagnostic()` is NOT called
  - The retry still proceeds normally (diagnostic logging does not affect retry behavior)
  - `time.sleep()` is still called with the computed delay

### SCN-RETRY-007-03: Success After Retry Logged {#SCN-RETRY-007-03}
- **Implements**: REQ-RETRY-007
- **GIVEN**: Attempt 0 fails with a retryable error
- **AND**: Attempt 1 succeeds
- **AND**: `is_diagnostic_mode()` returns True
- **WHEN**: The success is detected
- **THEN**:
  - `save_diagnostic()` is called with:
    - `name`: `"retry_extract_keypoints"`
    - `content`: `"extract_keypoints() succeeded on attempt 2 after 1 retries."`
  - (attempt 1 is 0-indexed; "attempt 2" is 1-indexed for human readability)

### SCN-RETRY-007-04: No Diagnostic Log on First-Attempt Success {#SCN-RETRY-007-04}
- **Implements**: REQ-RETRY-007
- **GIVEN**: Attempt 0 succeeds immediately
- **AND**: `is_diagnostic_mode()` returns True
- **WHEN**: The function completes successfully
- **THEN**:
  - No retry-related `save_diagnostic()` calls are made
  - The normal diagnostic log for the prompt/response (existing line 781-785) is still emitted

---

## Invariants

### INV-RETRY-001: Function Signature Unchanged {#INV-RETRY-001}
- **Implements**: CON-RETRY-003
- **Statement**: The signature of `extract_keypoints(messages: list[dict], playbook: dict, diagnostic_name: str = "reflection") -> dict` is unchanged. Callers (`session_end.py`, `precompact.py`) require no modification.
- **Enforced by**: The retry logic is entirely internal to the function. Module-level constants `MAX_RETRIES` and `BASE_DELAY` are not part of the public API.

### INV-RETRY-002: Only client.messages.create() Is Retried {#INV-RETRY-002}
- **Implements**: CON-RETRY-004
- **Statement**: The retry loop wraps ONLY the `client.messages.create()` call. Prompt construction (lines 751-762), client initialization (lines 764-767), response text extraction (lines 773-779), JSON parsing (lines 790-804), and result construction (lines 806-814) are NOT inside the retry loop. They execute exactly once.
- **Enforced by**: The retry loop's `try` block contains only the `client.messages.create()` call and the `break` statement on success. All other code is outside the loop.

### INV-RETRY-003: Total Time Within Hook Timeout {#INV-RETRY-003}
- **Implements**: CON-RETRY-002, CON-RETRY-005
- **Statement**: The worst-case total time for retry is bounded: `MAX_RETRIES * 30s (per-request timeout) + sum of max delays`. With defaults: `3 * 30 + (2.0 * 1.25) + (4.0 * 1.25) = 90 + 2.5 + 5.0 = 97.5s`, which is within the 120-second hook timeout with ~22.5s margin. Note: delay after attempt 0 has base `2.0 * 2^0 = 2.0s` and delay after attempt 1 has base `2.0 * 2^1 = 4.0s`; the two delays have different bases, so they must be summed individually rather than using a single `(MAX_RETRIES - 1) * max_delay` formula.
- **Enforced by**: REQ-RETRY-006 (30s per-request timeout), REQ-RETRY-002 (bounded delays with known max), REQ-RETRY-008 (MAX_RETRIES=3).

### INV-RETRY-004: Return Value Always Valid Extraction Result {#INV-RETRY-004}
- **Implements**: SC-RETRY-001, SC-RETRY-003, SC-RETRY-005
- **Statement**: `extract_keypoints()` never propagates an exception from `client.messages.create()`. Every error path -- retryable (after exhaustion), non-retryable, unknown APIError, and bare Exception -- returns `{"new_key_points": [], "evaluations": []}`. The function's return type contract is preserved: callers always receive a dict with `new_key_points` (list) and `evaluations` (list).
- **Enforced by**: REQ-RETRY-004 (non-retryable returns empty), REQ-RETRY-005 (exhaustion returns empty), REQ-RETRY-003 (all error paths terminate in return empty).

---

## Constraints (from Intent)

| ID | Constraint | Enforced By |
|----|-----------|-------------|
| CON-RETRY-001 | No new pip dependencies; stdlib only (time, random, exception handling) | REQ-RETRY-002 (time.sleep, random.uniform) |
| CON-RETRY-002 | Total retry time within hook timeout (~97.5s worst case, 120s budget) | INV-RETRY-003, REQ-RETRY-006, REQ-RETRY-008 |
| CON-RETRY-003 | Function signature unchanged; module-level constants are internal | INV-RETRY-001, REQ-RETRY-008 |
| CON-RETRY-004 | Retry wraps only client.messages.create(), not the entire function | INV-RETRY-002 |
| CON-RETRY-005 | Per-request timeout of 30s via SDK parameter | REQ-RETRY-006 |
