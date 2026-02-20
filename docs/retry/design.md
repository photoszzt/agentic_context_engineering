# Implementation Design: Retry Logic with Exponential Backoff

## Overview

This document specifies the exact changes to `src/hooks/common.py` required to add retry with exponential backoff around the `client.messages.create()` call in `extract_keypoints()`. The change is surgical: only lines 769-771 are wrapped in a retry loop; all other code in the function is untouched.

---

## New Module-Level Constants

**File**: `src/hooks/common.py`

**Placement**: After the `SECTION_SLUGS` dict (line 31) and before the first function definition (`get_project_dir()` at line 34). This keeps constants grouped together at the top of the module.

**Implements**: REQ-RETRY-008

```python
# Retry configuration for extract_keypoints() API calls.
# @implements REQ-RETRY-008
MAX_RETRIES = 3    # Total attempts (0-indexed: attempt 0, 1, 2)
BASE_DELAY = 2.0   # Base delay in seconds for exponential backoff
```

---

## New Imports

**File**: `src/hooks/common.py`

Add to existing imports at the top of the file (lines 7-12):

```python
import time
import random
```

These are stdlib modules, satisfying CON-RETRY-001. `time` is used for `time.sleep()`. `random` is used for `random.uniform(0.75, 1.25)` jitter.

---

## Modified Function: `extract_keypoints()`

**File**: `src/hooks/common.py`

**Implements**: REQ-RETRY-001, REQ-RETRY-002, REQ-RETRY-003, REQ-RETRY-004, REQ-RETRY-005, REQ-RETRY-006, REQ-RETRY-007

**Current code (lines 769-771)**:
```python
    response = client.messages.create(
        model=model, max_tokens=4096, messages=[{"role": "user", "content": prompt}]
    )
```

**New code replacing lines 769-771**:

```python
    # @implements REQ-RETRY-001, REQ-RETRY-002, REQ-RETRY-003, REQ-RETRY-004,
    #             REQ-RETRY-005, REQ-RETRY-006, REQ-RETRY-007
    # @invariant INV-RETRY-002 (only client.messages.create() is inside the retry loop)
    # @invariant INV-RETRY-004 (every error path returns a valid extraction result dict)
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                timeout=30.0,
            )
            # Success: log if this was a retry (attempt > 0)
            if attempt > 0 and is_diagnostic_mode():
                save_diagnostic(
                    f"extract_keypoints() succeeded on attempt {attempt + 1} after {attempt} retries.",
                    "retry_extract_keypoints",
                )
            break

        except anthropic.APITimeoutError as exc:
            # Retryable: transient timeout (must be caught before APIConnectionError)
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                        f"APITimeoutError: {exc}. Next attempt in {delay:.1f}s",
                        "retry_extract_keypoints",
                    )
                time.sleep(delay)
                continue
            else:
                # Final attempt exhausted
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                        f"Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.APIConnectionError as exc:
            # Retryable: transient connection failure
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                        f"APIConnectionError: {exc}. Next attempt in {delay:.1f}s",
                        "retry_extract_keypoints",
                    )
                time.sleep(delay)
                continue
            else:
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                        f"Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.RateLimitError as exc:
            # Retryable: HTTP 429
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                        f"RateLimitError: {exc}. Next attempt in {delay:.1f}s",
                        "retry_extract_keypoints",
                    )
                time.sleep(delay)
                continue
            else:
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                        f"Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.InternalServerError as exc:
            # Retryable: HTTP 500
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                        f"InternalServerError: {exc}. Next attempt in {delay:.1f}s",
                        "retry_extract_keypoints",
                    )
                time.sleep(delay)
                continue
            else:
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                        f"Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.APIStatusError as exc:
            # Catch-all for APIStatusError: check status_code to decide
            if exc.status_code >= 500:
                # Retryable: 5xx not caught by InternalServerError above
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                            f"{type(exc).__name__}: {exc}. Next attempt in {delay:.1f}s",
                            "retry_extract_keypoints",
                        )
                    time.sleep(delay)
                    continue
                else:
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                            f"Returning empty result.",
                            "retry_extract_keypoints",
                        )
                    return {"new_key_points": [], "evaluations": []}
            else:
                # Non-retryable: 4xx (except 429, already caught by RateLimitError)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Non-retryable error in extract_keypoints(): "
                        f"{type(exc).__name__}: {exc}. Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.APIResponseValidationError as exc:
            # Non-retryable: SDK could not parse response (APIError but not APIStatusError)
            if is_diagnostic_mode():
                save_diagnostic(
                    f"Non-retryable error in extract_keypoints(): "
                    f"APIResponseValidationError: {exc}. Returning empty result.",
                    "retry_extract_keypoints",
                )
            return {"new_key_points": [], "evaluations": []}

        except anthropic.APIError as exc:
            # Non-retryable: unknown APIError subclass (defensive fallback)
            if is_diagnostic_mode():
                save_diagnostic(
                    f"Non-retryable error in extract_keypoints(): "
                    f"{type(exc).__name__}: {exc}. Returning empty result.",
                    "retry_extract_keypoints",
                )
            return {"new_key_points": [], "evaluations": []}

        except Exception as exc:
            # Non-retryable: non-API exception (may be a programming bug)
            if is_diagnostic_mode():
                save_diagnostic(
                    f"Non-retryable error in extract_keypoints(): "
                    f"{type(exc).__name__}: {exc}. Returning empty result.",
                    "retry_extract_keypoints",
                )
            return {"new_key_points": [], "evaluations": []}
```

**IMPORTANT -- Exception catch ordering note**: In the code above, `anthropic.APIResponseValidationError` is caught AFTER `anthropic.APIStatusError`. This is safe because `APIResponseValidationError` is NOT a subclass of `APIStatusError` -- they are sibling subclasses of `APIError`. The `APIStatusError` handler will never catch `APIResponseValidationError`. However, if the Coding Agent prefers to reorder for explicit clarity, moving `APIResponseValidationError` before `APIStatusError` is also correct and arguably clearer. Both orderings produce identical behavior.

**Alternative (DRY) implementation**: The Coding Agent MAY refactor the retryable error handlers to reduce code duplication. One acceptable approach:

```python
    response = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                timeout=30.0,
            )
            if attempt > 0 and is_diagnostic_mode():
                save_diagnostic(
                    f"extract_keypoints() succeeded on attempt {attempt + 1} after {attempt} retries.",
                    "retry_extract_keypoints",
                )
            break

        except (
            anthropic.APITimeoutError,
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        ) as exc:
            # Known retryable errors
            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                        f"{type(exc).__name__}: {exc}. Next attempt in {delay:.1f}s",
                        "retry_extract_keypoints",
                    )
                time.sleep(delay)
                continue
            else:
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                        f"Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                # Retryable: 5xx not caught above
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt) * random.uniform(0.75, 1.25)
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"Retry attempt {attempt + 1}/{MAX_RETRIES} failed: "
                            f"{type(exc).__name__}: {exc}. Next attempt in {delay:.1f}s",
                            "retry_extract_keypoints",
                        )
                    time.sleep(delay)
                    continue
                else:
                    if is_diagnostic_mode():
                        save_diagnostic(
                            f"All {MAX_RETRIES} attempts failed for extract_keypoints(). "
                            f"Returning empty result.",
                            "retry_extract_keypoints",
                        )
                    return {"new_key_points": [], "evaluations": []}
            else:
                # Non-retryable: 4xx (except 429)
                if is_diagnostic_mode():
                    save_diagnostic(
                        f"Non-retryable error in extract_keypoints(): "
                        f"{type(exc).__name__}: {exc}. Returning empty result.",
                        "retry_extract_keypoints",
                    )
                return {"new_key_points": [], "evaluations": []}

        except anthropic.APIError as exc:
            # Catch-all for APIError (includes APIResponseValidationError and unknown subclasses)
            if is_diagnostic_mode():
                save_diagnostic(
                    f"Non-retryable error in extract_keypoints(): "
                    f"{type(exc).__name__}: {exc}. Returning empty result.",
                    "retry_extract_keypoints",
                )
            return {"new_key_points": [], "evaluations": []}

        except Exception as exc:
            # Non-API exception
            if is_diagnostic_mode():
                save_diagnostic(
                    f"Non-retryable error in extract_keypoints(): "
                    f"{type(exc).__name__}: {exc}. Returning empty result.",
                    "retry_extract_keypoints",
                )
            return {"new_key_points": [], "evaluations": []}
```

This DRY version groups all known retryable exception types into a single tuple handler. The key constraints that MUST be preserved in any implementation:
1. `APITimeoutError` and `APIConnectionError` are both in the retryable tuple. Since `APITimeoutError` IS-A `APIConnectionError`, any `APITimeoutError` exception matches both types in the tuple. However, since it is a SINGLE handler, the exception is caught once and `type(exc).__name__` reports the actual type (`APITimeoutError`). Tuple ordering does not affect behavior for `isinstance` matching -- Python checks `isinstance(exc, (A, B))`, which is equivalent to `isinstance(exc, A) or isinstance(exc, B)`, regardless of order
2. `RateLimitError` (HTTP 429) is in the retryable tuple, NOT in the `APIStatusError` handler (where it would be caught by the 4xx non-retryable branch)
3. `InternalServerError` (HTTP 500) is in the retryable tuple, NOT falling through to `APIStatusError >= 500` (functionally equivalent but clearer)
4. `APIStatusError` handles the split: `status_code >= 500` is retryable, else non-retryable
5. `APIError` catch-all comes after `APIStatusError` (catches `APIResponseValidationError` and unknown subclasses)
6. Bare `Exception` is the outermost/last handler

**Either implementation (expanded or DRY) is acceptable.** The DRY version is preferred for maintainability.

---

## Unchanged Code

The following sections of `extract_keypoints()` are NOT modified:

| Lines (current) | Code | Why Unchanged |
|------------------|------|---------------|
| 720-722 | Function signature + docstring | INV-RETRY-001 |
| 727-728 | `if not ANTHROPIC_AVAILABLE` early return | Runs before API call |
| 730-747 | Settings, model, API key resolution | Prompt/config setup, not retried |
| 749-767 | Template loading, prompt construction, client init | Preparation, not retried |
| 773-785 | Response text extraction + existing diagnostic log | Runs after successful API call |
| 787-814 | Empty response check, JSON parsing, result construction | Post-processing, not retried |

---

## Function Composition

### Call Graph (updated)

```
PostToolUseHook / StopHook (session_end.py / precompact.py)
    --> extract_keypoints(messages, playbook, diagnostic_name)
        --> load_settings()                    # unchanged
        --> load_template()                    # unchanged
        --> anthropic.Anthropic(**client_kwargs)  # unchanged
        --> [RETRY LOOP: for attempt in range(MAX_RETRIES)]
            --> client.messages.create(timeout=30.0, ...)
            --> [on success]: break
            --> [on retryable error + not final attempt]:
                --> random.uniform(0.75, 1.25)   # jitter
                --> time.sleep(delay)            # backoff
                --> is_diagnostic_mode()         # gate
                --> save_diagnostic()            # LOG-RETRY-001
                --> continue
            --> [on retryable error + final attempt]:
                --> is_diagnostic_mode()         # gate
                --> save_diagnostic()            # LOG-RETRY-002
                --> return {"new_key_points": [], "evaluations": []}
            --> [on non-retryable error]:
                --> is_diagnostic_mode()         # gate
                --> save_diagnostic()            # LOG-RETRY-003
                --> return {"new_key_points": [], "evaluations": []}
        --> [after successful break]:
            --> response text extraction         # unchanged
            --> JSON parsing                     # unchanged
            --> result construction              # unchanged
```

### Data Flow

```
extract_keypoints() called by session_end.py or precompact.py
    |
    v
[Preparation: model, api_key, prompt, client -- runs once]
    |
    v
[Retry Loop: attempt 0, 1, 2]
    |
    +--> client.messages.create(timeout=30.0) -- the ONLY call inside the loop
    |       |
    |       +--> [Success] --> response object --> break out of loop
    |       |
    |       +--> [Retryable error, not final attempt]
    |       |       --> compute delay: BASE_DELAY * 2^attempt * jitter
    |       |       --> time.sleep(delay)
    |       |       --> continue to next attempt
    |       |
    |       +--> [Retryable error, final attempt]
    |       |       --> log exhaustion
    |       |       --> return {"new_key_points": [], "evaluations": []}
    |       |
    |       +--> [Non-retryable error]
    |               --> log error
    |               --> return {"new_key_points": [], "evaluations": []}
    |
    v
[Post-processing: text extraction, diagnostic log, JSON parse -- runs once]
    |
    v
return extraction result dict
```

### Initialization Order

No change. The retry loop is entirely within the existing function flow:
1. `extract_keypoints()` is called with `messages`, `playbook`, `diagnostic_name`
2. Settings/model/API key resolved (early returns if missing)
3. Template loaded, prompt constructed
4. Client initialized
5. **NEW**: Retry loop around `client.messages.create()` (replaces single call)
6. Response text extraction (unchanged, runs after successful attempt)
7. Existing diagnostic log (unchanged)
8. JSON parsing and result construction (unchanged)

---

## Testability Hooks

### External Dependencies

| Dependency | Testability Hook | Implementation |
|------------|------------------|----------------|
| Anthropic SDK client | `anthropic.Anthropic` constructor | Tests mock `client.messages.create` to raise specific exceptions or return mock responses |
| `time.sleep()` | Direct function | Tests monkeypatch `time.sleep` to a no-op (or capture calls to verify delay values) |
| `random.uniform()` | Direct function | Tests monkeypatch `random.uniform` to return a fixed value (e.g., 1.0 for no jitter, or 0.75/1.25 for boundary testing) |
| `is_diagnostic_mode()` | Flag file existence | Tests create/remove `.claude/diagnostic_mode` flag file in temp directory via `CLAUDE_PROJECT_DIR` env var |
| `save_diagnostic()` | File write | Tests check for diagnostic files in temp directory, or monkeypatch to capture calls |
| Module constants `MAX_RETRIES`, `BASE_DELAY` | Module-level variables | Tests can monkeypatch `common.MAX_RETRIES` and `common.BASE_DELAY` to test different retry configurations |
| `ANTHROPIC_AVAILABLE` flag | Module-level variable | Tests can monkeypatch to `True` (to enable the API path) or `False` (to test early return) |

### How Tests Mock the API Call

The primary testing pattern is to mock `client.messages.create` to control success/failure on each attempt:

```python
# Example: test retry on APITimeoutError then success
def test_retry_on_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(time, "sleep", lambda _: None)  # no-op sleep
    monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)  # fixed jitter

    call_count = 0
    def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise anthropic.APITimeoutError(request=None)
        # Return a mock response on second call
        return MockResponse(content=[MockTextBlock(type="text", text='{"new_key_points": [], "evaluations": []}')])

    # Setup mock client...
    # monkeypatch anthropic.Anthropic to return a mock client with mock_create

    result = asyncio.run(extract_keypoints(messages, playbook))
    assert call_count == 2  # 1 failure + 1 success
    assert "new_key_points" in result
```

### Test Strategy for Delay Verification

```python
# Verify exact delay values by capturing time.sleep calls
def test_backoff_delays(monkeypatch, tmp_path):
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda d: sleep_calls.append(d))
    monkeypatch.setattr(random, "uniform", lambda a, b: 1.0)  # no jitter

    # Mock all 3 attempts to fail with retryable error
    # ... setup mock ...

    result = asyncio.run(extract_keypoints(messages, playbook))
    assert len(sleep_calls) == 2  # 2 delays for 3 attempts
    assert sleep_calls[0] == 2.0  # BASE_DELAY * 2^0 * 1.0
    assert sleep_calls[1] == 4.0  # BASE_DELAY * 2^1 * 1.0
    assert result == {"new_key_points": [], "evaluations": []}
```

---

## Instrumentation Hooks

### Diagnostic Pattern (OBS-RETRY-001, OBS-RETRY-002)

This module uses the existing diagnostic pattern (`is_diagnostic_mode()` + `save_diagnostic()`) consistent with all other modules in `common.py`.

| OBS-* | Diagnostic File Name | When Written | Content |
|-------|---------------------|--------------|---------|
| OBS-RETRY-001 (LOG-RETRY-001) | `retry_extract_keypoints` | After each failed retryable attempt (not the final attempt) | Attempt number, error type, error message, delay before next attempt |
| OBS-RETRY-002 (LOG-RETRY-002) | `retry_extract_keypoints` | After final outcome: success after retry, or exhaustion | "succeeded on attempt N after M retries" or "All N attempts failed..." |
| (LOG-RETRY-003) | `retry_extract_keypoints` | After non-retryable error caught | Error type, error message, "Returning empty result" |

### Wiring

All diagnostic outputs use:
- Gate: `is_diagnostic_mode()`
- Output: `save_diagnostic(content, "retry_extract_keypoints")`
- Output file: `{project_dir}/.claude/diagnostic/{timestamp}_retry_extract_keypoints.txt`

No new instrumentation infrastructure is needed.
