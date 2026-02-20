# Data Contract: Retry Logic with Exponential Backoff

## Overview

This document defines the data contracts for the retry logic added to `extract_keypoints()` in `src/hooks/common.py`. The change is narrow: two new module-level constants, a retry loop wrapping one API call, and diagnostic log messages. No new types, classes, or public functions are introduced.

---

## Module-Level Constants

### `MAX_RETRIES`

| Property | Value |
|----------|-------|
| Name | `MAX_RETRIES` |
| Type | `int` |
| Value | `3` |
| Scope | Module-level in `src/hooks/common.py` |
| Semantics | Total number of attempts (not retries-after-initial). Attempt indices: 0, 1, 2. Number of backoff delays: `MAX_RETRIES - 1 = 2`. |
| Public API | No -- internal to `common.py`. Not imported by callers. |

### `BASE_DELAY`

| Property | Value |
|----------|-------|
| Name | `BASE_DELAY` |
| Type | `float` |
| Value | `2.0` |
| Scope | Module-level in `src/hooks/common.py` |
| Semantics | Base delay in seconds for exponential backoff formula: `BASE_DELAY * (2 ** attempt)`. |
| Public API | No -- internal to `common.py`. Not imported by callers. |

---

## Function Signatures

### `extract_keypoints(messages, playbook, diagnostic_name) -> dict`

**Signature**: UNCHANGED (INV-RETRY-001).

```python
async def extract_keypoints(
    messages: list[dict], playbook: dict, diagnostic_name: str = "reflection"
) -> dict:
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `messages` | `list[dict]` | Conversation transcript messages. |
| `playbook` | `dict` | Current playbook state (sections-based). |
| `diagnostic_name` | `str` | Name for diagnostic file output. Default: `"reflection"`. |
| **Returns** | `dict` | Extraction result with `new_key_points` (list), `evaluations` (list), and optionally `operations` (list). |

**Behavior contract (NEW -- replaces crash behavior)**:
- `extract_keypoints()` **never raises** an exception originating from `client.messages.create()`.
- On any API error (retryable after exhaustion, non-retryable, or unknown), the function returns the empty result: `{"new_key_points": [], "evaluations": []}`.
- This is a **change from current behavior** where exceptions propagate uncaught, crashing the hook process.
- The return value always contains `new_key_points` (list) and `evaluations` (list). It may also contain `operations` (list) if the LLM response included it (per existing REQ-CUR-001 logic).

---

## Per-Request Timeout Parameter

| Property | Value |
|----------|-------|
| Parameter name | `timeout` |
| Type | `float` |
| Value | `30.0` |
| Applied to | `client.messages.create()` on every attempt |
| SDK behavior | Overrides the Anthropic SDK default of 600 seconds. If the request does not complete within 30 seconds, the SDK raises `anthropic.APITimeoutError`. |

**Call signature with timeout**:
```python
client.messages.create(
    model=model,
    max_tokens=4096,
    messages=[{"role": "user", "content": prompt}],
    timeout=30.0,
)
```

---

## Backoff Delay Formula

| Property | Formula |
|----------|---------|
| Base delay | `BASE_DELAY * (2 ** attempt)` where `attempt` is 0-indexed |
| Jitter | Multiply base delay by `random.uniform(0.75, 1.25)` |
| Actual delay | `BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)` |
| Sleep | `time.sleep(actual_delay)` |
| When applied | After attempts 0 through MAX_RETRIES - 2 (not after the final attempt) |

**Concrete values with defaults (MAX_RETRIES=3, BASE_DELAY=2.0)**:

| After Attempt | Base Delay | Min Delay (jitter=0.75) | Max Delay (jitter=1.25) |
|---------------|-----------|------------------------|------------------------|
| 0 | 2.0s | 1.5s | 2.5s |
| 1 | 4.0s | 3.0s | 5.0s |
| 2 (final) | N/A -- no delay | N/A | N/A |

---

## Diagnostic Log Formats

All diagnostic logs use `save_diagnostic(content, name)` with `name="retry_extract_keypoints"`. All are gated by `is_diagnostic_mode()`.

### LOG-RETRY-001: Per-Attempt Retry Failure

**Trigger**: A retryable error occurs on attempt N where N < MAX_RETRIES - 1 (not the final attempt).

**Format**:
```
Retry attempt {N_1indexed}/{MAX_RETRIES} failed: {ErrorClassName}: {error_message}. Next attempt in {delay:.1f}s
```

| Placeholder | Type | Description |
|-------------|------|-------------|
| `{N_1indexed}` | int | 1-indexed attempt number (`attempt + 1`). Range: 1 to MAX_RETRIES - 1. |
| `{MAX_RETRIES}` | int | Total attempts (module constant). |
| `{ErrorClassName}` | str | Python class name of the exception (e.g., `APITimeoutError`, `RateLimitError`). Obtained via `type(exc).__name__` for `APIStatusError` catch-all, or the literal class name for specific handlers. |
| `{error_message}` | str | `str(exc)` -- the exception's string representation. |
| `{delay:.1f}` | float | The actual sleep delay in seconds, formatted to 1 decimal place. |

**Example**:
```
Retry attempt 1/3 failed: APITimeoutError: Request timed out. Next attempt in 2.3s
```

**Example (RateLimitError)**:
```
Retry attempt 2/3 failed: RateLimitError: Error code: 429 - Rate limit exceeded. Next attempt in 4.1s
```

### LOG-RETRY-002: Final Outcome -- Exhaustion

**Trigger**: The final attempt (attempt MAX_RETRIES - 1) fails with a retryable error.

**Format**:
```
All {MAX_RETRIES} attempts failed for extract_keypoints(). Returning empty result.
```

| Placeholder | Type | Description |
|-------------|------|-------------|
| `{MAX_RETRIES}` | int | Total attempts (module constant). |

**Example**:
```
All 3 attempts failed for extract_keypoints(). Returning empty result.
```

### LOG-RETRY-002: Final Outcome -- Success After Retry

**Trigger**: The API call succeeds on attempt N where N > 0 (at least one retry occurred).

**Format**:
```
extract_keypoints() succeeded on attempt {N_1indexed} after {N_retries} retries.
```

| Placeholder | Type | Description |
|-------------|------|-------------|
| `{N_1indexed}` | int | 1-indexed attempt number (`attempt + 1`). Range: 2 to MAX_RETRIES. |
| `{N_retries}` | int | Number of retries (`attempt`). Range: 1 to MAX_RETRIES - 1. |

**Example**:
```
extract_keypoints() succeeded on attempt 2 after 1 retries.
```

**Not emitted when**: Attempt 0 succeeds (no retry occurred -- this is the normal happy path).

### LOG-RETRY-003: Non-Retryable Error

**Trigger**: A non-retryable error is caught (4xx APIStatusError, APIResponseValidationError, unknown APIError, or bare Exception).

**Format**:
```
Non-retryable error in extract_keypoints(): {ErrorClassName}: {error_message}. Returning empty result.
```

| Placeholder | Type | Description |
|-------------|------|-------------|
| `{ErrorClassName}` | str | Python class name (e.g., `AuthenticationError`, `BadRequestError`, `APIResponseValidationError`, `RuntimeError`). |
| `{error_message}` | str | `str(exc)` -- the exception's string representation. |

**Example (AuthenticationError)**:
```
Non-retryable error in extract_keypoints(): AuthenticationError: Error code: 401 - Invalid API key. Returning empty result.
```

**Example (APIResponseValidationError)**:
```
Non-retryable error in extract_keypoints(): APIResponseValidationError: Failed to parse response. Returning empty result.
```

**Example (bare Exception)**:
```
Non-retryable error in extract_keypoints(): RuntimeError: unexpected error. Returning empty result.
```

---

## Empty Result Contract

The "empty result" returned on all error paths is always:

```python
{"new_key_points": [], "evaluations": []}
```

| Field | Type | Value | Description |
|-------|------|-------|-------------|
| `new_key_points` | `list` | `[]` | Empty list -- no new key points extracted. |
| `evaluations` | `list` | `[]` | Empty list -- no evaluations of existing key points. |

This dict does NOT contain an `operations` key. When passed to `update_playbook_data()`, the absence of `operations` triggers the `new_key_points` fallback path (REQ-CUR-008), which processes an empty list (no-op). Evaluations are also empty (no-op). The net effect: the playbook is unchanged, and the hook completes successfully without crashing.

---

## Error Classification Contract

### Exception Hierarchy (Anthropic SDK)

```
BaseException
  Exception
    anthropic.APIError
      anthropic.APIConnectionError
        anthropic.APITimeoutError          # IS-A APIConnectionError
      anthropic.APIStatusError
        anthropic.BadRequestError          # HTTP 400
        anthropic.AuthenticationError      # HTTP 401
        anthropic.PermissionDeniedError    # HTTP 403
        anthropic.NotFoundError            # HTTP 404
        anthropic.ConflictError            # HTTP 409
        anthropic.UnprocessableEntityError # HTTP 422
        anthropic.RateLimitError           # HTTP 429
        anthropic.InternalServerError      # HTTP 500
      anthropic.APIResponseValidationError # NOT a subclass of APIStatusError
```

### Classification Table

| Exception | HTTP Status | Retryable? | Behavior |
|-----------|-------------|------------|----------|
| `APITimeoutError` | N/A (timeout) | YES | Retry with backoff |
| `APIConnectionError` | N/A (connection) | YES | Retry with backoff |
| `RateLimitError` | 429 | YES | Retry with backoff |
| `InternalServerError` | 500 | YES | Retry with backoff |
| `APIStatusError` (status >= 500) | 5xx | YES | Retry with backoff |
| `BadRequestError` | 400 | NO | Return empty immediately |
| `AuthenticationError` | 401 | NO | Return empty immediately |
| `PermissionDeniedError` | 403 | NO | Return empty immediately |
| `NotFoundError` | 404 | NO | Return empty immediately |
| `ConflictError` | 409 | NO | Return empty immediately |
| `UnprocessableEntityError` | 422 | NO | Return empty immediately |
| `APIStatusError` (status < 500) | 4xx | NO | Return empty immediately |
| `APIResponseValidationError` | N/A | NO | Return empty immediately |
| `APIError` (catch-all) | varies | NO | Return empty immediately |
| `Exception` (catch-all) | N/A | NO | Return empty immediately |
