# Observability Specification: Retry Logic with Exponential Backoff

## Overview

The retry logic wraps the `client.messages.create()` call in `extract_keypoints()` with a retry loop. Observability is needed to understand retry behavior in production: when retries occur, why they occur, whether they succeed or exhaust, and when non-retryable errors are encountered. All observability uses the existing file-based diagnostic pattern, gated by `is_diagnostic_mode()`.

## Instrumentation Approach

This module uses **file-based diagnostics**, consistent with all other modules in `common.py`. The existing `save_diagnostic()` function writes timestamped plain-text files to `.claude/diagnostic/`. All diagnostic output is gated by `is_diagnostic_mode()`, which checks for the presence of a `.claude/diagnostic_mode` flag file.

| Component | Mechanism | Gate | Output Location |
|-----------|-----------|------|-----------------|
| `save_diagnostic(content, name)` | Writes `{timestamp}_{name}.txt` | `is_diagnostic_mode()` returns `True` | `{project_dir}/.claude/diagnostic/` |
| `is_diagnostic_mode()` | Checks existence of flag file | N/A (is the gate) | `{project_dir}/.claude/diagnostic_mode` |

## Observability Traceability

| OBS-* | Observability Requirement | LOG-* | Function | File |
|-------|---------------------------|-------|----------|------|
| OBS-RETRY-001 | Each retry attempt must be observable with: attempt number, error type, error message, and planned delay before next attempt | LOG-RETRY-001 | `extract_keypoints()` | `src/hooks/common.py` |
| OBS-RETRY-002 | The final outcome of the retry sequence must be logged: either "succeeded on attempt N" or "failed after N attempts, returning empty result" | LOG-RETRY-002 | `extract_keypoints()` | `src/hooks/common.py` |
| (SC-RETRY-004) | Non-retryable errors must be logged before returning empty result | LOG-RETRY-003 | `extract_keypoints()` | `src/hooks/common.py` |

**Note on LOG-RETRY-003 traceability**: LOG-RETRY-003 traces directly to SC-RETRY-004 (behavioral success criterion) rather than through a formal OBS-RETRY-* requirement. This is because the intent's observability requirements (OBS-RETRY-001, OBS-RETRY-002) focus on retry attempts and final outcomes. Non-retryable error logging derives directly from SC-RETRY-004's requirement to log before returning empty. Testing should verify LOG-RETRY-003 emission as part of SC-RETRY-004/REQ-RETRY-004 coverage.

## Log Events

### LOG-RETRY-001: Per-Attempt Retry Failure {#LOG-RETRY-001}

- **Implements**: OBS-RETRY-001
- **Trigger**: A retryable error occurs on attempt N where N < MAX_RETRIES - 1 (not the final attempt). The retry loop will continue to the next attempt after sleeping.
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"retry_extract_keypoints"`
  - `content`: `"Retry attempt {N+1}/{MAX_RETRIES} failed: {ErrorClassName}: {error_message}. Next attempt in {delay:.1f}s"`
  - Fields in content:
    - Attempt number: 1-indexed (`attempt + 1`) for human readability
    - MAX_RETRIES: total attempts (module constant, default 3)
    - Error class name: `type(exc).__name__` (e.g., `APITimeoutError`, `RateLimitError`, `APIConnectionError`, `InternalServerError`, or the specific `APIStatusError` subclass name for 5xx catch-all)
    - Error message: `str(exc)`
    - Delay: the actual computed delay in seconds (after jitter), formatted to 1 decimal place
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_retry_extract_keypoints.txt`
- **When NOT emitted**: If `is_diagnostic_mode()` returns `False`. Also NOT emitted on the final attempt (attempt MAX_RETRIES - 1) -- that triggers LOG-RETRY-002 instead.
- **Frequency**: At most `MAX_RETRIES - 1` times per `extract_keypoints()` invocation (once per non-final failed attempt). With defaults: at most 2 times.

**Example output (attempt 0 fails with timeout)**:
```
Retry attempt 1/3 failed: APITimeoutError: Request timed out. Next attempt in 2.3s
```

**Example output (attempt 1 fails with rate limit)**:
```
Retry attempt 2/3 failed: RateLimitError: Error code: 429 - Rate limit exceeded. Next attempt in 4.1s
```

### LOG-RETRY-002: Final Outcome {#LOG-RETRY-002}

- **Implements**: OBS-RETRY-002
- **Trigger**: Either (a) the retry loop exhausts all attempts and the final attempt fails with a retryable error, OR (b) the API call succeeds on attempt N > 0 (at least one retry occurred before success).
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"retry_extract_keypoints"`

  **Variant A -- Exhaustion** (all attempts failed):
  - `content`: `"All {MAX_RETRIES} attempts failed for extract_keypoints(). Returning empty result."`
  - Fields: MAX_RETRIES (module constant)

  **Variant B -- Success after retry** (attempt N > 0 succeeded):
  - `content`: `"extract_keypoints() succeeded on attempt {N+1} after {N} retries."`
  - Fields: 1-indexed attempt number, 0-indexed retry count
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_retry_extract_keypoints.txt`
- **When NOT emitted**:
  - If `is_diagnostic_mode()` returns `False`
  - Variant B is NOT emitted when attempt 0 succeeds (no retry occurred -- this is the normal happy path and requires no log)
- **Frequency**: At most once per `extract_keypoints()` invocation.

**Example output (exhaustion)**:
```
All 3 attempts failed for extract_keypoints(). Returning empty result.
```

**Example output (success after 1 retry)**:
```
extract_keypoints() succeeded on attempt 2 after 1 retries.
```

### LOG-RETRY-003: Non-Retryable Error {#LOG-RETRY-003}

- **Implements**: SC-RETRY-004
- **Trigger**: A non-retryable error is caught by the retry loop. This includes:
  - `anthropic.APIStatusError` with `status_code < 500` (4xx except 429, which is caught as `RateLimitError`)
  - `anthropic.APIResponseValidationError`
  - `anthropic.APIError` catch-all (unknown subclass)
  - Bare `Exception` catch-all (non-API error)
- **Gate**: `is_diagnostic_mode()` must return `True`
- **Output**: `save_diagnostic()` call with:
  - `name`: `"retry_extract_keypoints"`
  - `content`: `"Non-retryable error in extract_keypoints(): {ErrorClassName}: {error_message}. Returning empty result."`
  - Fields:
    - Error class name: `type(exc).__name__` (e.g., `AuthenticationError`, `BadRequestError`, `APIResponseValidationError`, `RuntimeError`)
    - Error message: `str(exc)`
- **Output file**: `{project_dir}/.claude/diagnostic/{timestamp}_retry_extract_keypoints.txt`
- **When NOT emitted**: If `is_diagnostic_mode()` returns `False`.
- **Frequency**: At most once per `extract_keypoints()` invocation (non-retryable errors cause immediate return, so only one can occur).

**Example output (AuthenticationError)**:
```
Non-retryable error in extract_keypoints(): AuthenticationError: Error code: 401 - Invalid API key. Returning empty result.
```

**Example output (APIResponseValidationError)**:
```
Non-retryable error in extract_keypoints(): APIResponseValidationError: Failed to parse response. Returning empty result.
```

**Example output (bare Exception)**:
```
Non-retryable error in extract_keypoints(): RuntimeError: unexpected error. Returning empty result.
```

## Diagnostic Visibility Note

All retry diagnostic logs are gated by `is_diagnostic_mode()`. This means retry events are **invisible in production** unless the `.claude/diagnostic_mode` flag file exists. This is consistent with the existing diagnostic pattern throughout `common.py` (e.g., the prompt/response diagnostic at line 781-785, curator operation diagnostics, etc.).

**Rationale** (from OBS-RETRY-001 in intent):
- The codebase has no general-purpose stderr logging infrastructure -- all debug output goes through diagnostic mode
- Retry events in production are rare and transient
- Introducing unconditional stderr logging for retries would be inconsistent with the rest of the codebase
- If retries exhaust, the function returns empty result gracefully (the hook does not crash)

**To enable retry diagnostics**: Create the flag file at `{project_dir}/.claude/diagnostic_mode`. Diagnostic files will appear in `{project_dir}/.claude/diagnostic/`.

## Carried-Forward Diagnostics

The following existing diagnostic in `extract_keypoints()` remains active and unchanged:

| Existing Diagnostic | File Name | When Written | Interaction with Retry |
|--------------------|-----------|--------------|----------------------|
| Prompt + Response log (line 781-785) | `{diagnostic_name}` (default: `"reflection"`) | After successful API call, before JSON parsing | Only emitted after a successful attempt. If all attempts fail, this diagnostic is NOT emitted (the function returns empty before reaching line 781). |

## Sensitive Data Handling

- **ALLOW**: Error class names, HTTP status codes, attempt numbers, delay values, MAX_RETRIES value
- **ALLOW**: Error messages from the Anthropic SDK (`str(exc)`). These contain HTTP status codes and API error descriptions (e.g., "Error code: 429 - Rate limit exceeded"). They do NOT contain user data, API keys, or request payloads.
- **No sensitive data**: Retry diagnostics contain only error metadata. The API key is never logged. The prompt content is logged separately by the existing diagnostic (line 781-785), which is outside the retry loop.

## Input Sources

- `/data/agentic_context_engineering/.planning/intent.md` -- OBS-RETRY-001, OBS-RETRY-002 definitions, SC-RETRY-004, SC-RETRY-007
- `/data/agentic_context_engineering/docs/retry/design.md` -- Instrumentation hooks, diagnostic pattern
- `/data/agentic_context_engineering/docs/retry/spec.md` -- REQ-RETRY-007, SCN-RETRY-007-01 through SCN-RETRY-007-04
- `/data/agentic_context_engineering/docs/curator/observability.md` -- Format conventions (LOG-* structure)
- `/data/agentic_context_engineering/src/hooks/common.py` -- `save_diagnostic()` and `is_diagnostic_mode()` implementation
