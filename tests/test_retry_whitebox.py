# Spec: docs/retry/spec.md
# Testing: docs/retry/testing.md
"""
White-box tests for retry logic with exponential backoff in extract_keypoints().

Covers all REQ-RETRY-001 through REQ-RETRY-008, all 21 SCN-RETRY-* scenarios,
all 4 INV-RETRY-* invariants, all 3 LOG-RETRY-* instrumentation events,
and adversarial test categories TC-BOUND-*, TC-ERR-*, TC-NEG-*, TC-TIME-*.
"""

import asyncio
import inspect
import json
import random
import sys
import time
from types import ModuleType
from unittest.mock import MagicMock

import anthropic
import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

import src.hooks.common as _common_module

from src.hooks.common import (
    BASE_DELAY,
    MAX_RETRIES,
    extract_keypoints,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_JSON = '{"new_key_points": [], "evaluations": []}'
SUCCESS_JSON = '{"new_key_points": ["insight"], "evaluations": [{"name": "pat-001", "rating": "helpful"}]}'


def _setup_extract_keypoints_mocks(monkeypatch):
    """Set up all mocks needed to call extract_keypoints() without a real LLM.

    Returns (mock_client, mock_text_block) so callers can configure
    mock_client.messages.create behavior for per-attempt control.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("AGENTIC_CONTEXT_MODEL", "claude-test")
    monkeypatch.setattr(_common_module, "ANTHROPIC_AVAILABLE", True)
    monkeypatch.setattr(
        _common_module,
        "load_template",
        lambda name: "Trajectories: {trajectories}\nPlaybook: {playbook}",
    )

    mock_response = MagicMock()
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = VALID_JSON
    mock_response.content = [mock_text_block]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    mock_anthropic_cls = MagicMock(return_value=mock_client)
    fake_anthropic = ModuleType("anthropic")
    setattr(fake_anthropic, "Anthropic", mock_anthropic_cls)
    # Copy all exception classes from real anthropic module to fake module
    for attr_name in dir(anthropic):
        obj = getattr(anthropic, attr_name)
        if isinstance(obj, type) and issubclass(obj, BaseException):
            setattr(fake_anthropic, attr_name, obj)
    monkeypatch.setattr(_common_module, "anthropic", fake_anthropic, raising=False)

    return mock_client, mock_text_block


def _make_mock_response(json_text):
    """Create a mock response object with content[0].text = json_text."""
    mock_response = MagicMock()
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = json_text
    mock_response.content = [mock_text_block]
    return mock_response


def _capture_sleep(monkeypatch):
    """Monkeypatch time.sleep to capture delay values. Returns the list."""
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda d: sleep_calls.append(d))
    return sleep_calls


def _capture_diagnostic(monkeypatch):
    """Monkeypatch save_diagnostic to capture (content, name) pairs. Returns the list."""
    diag_calls = []
    monkeypatch.setattr(
        _common_module,
        "save_diagnostic",
        lambda content, name: diag_calls.append((content, name)),
    )
    return diag_calls


def _fix_jitter(monkeypatch, value=1.0):
    """Monkeypatch random.uniform to return a fixed value."""
    monkeypatch.setattr(random, "uniform", lambda a, b: value)


def _make_side_effects(failures, success):
    """Create a side_effect list: N exceptions then a success response."""
    effects = list(failures)
    if success is not None:
        effects.append(success)
    return effects


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """Set CLAUDE_PROJECT_DIR to a temp directory and create .claude/ structure."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def enable_diagnostic(project_dir):
    """Enable diagnostic mode by creating the flag file."""
    flag_file = project_dir / ".claude" / "diagnostic_mode"
    flag_file.touch()
    return project_dir


# ===========================================================================
# REQ-RETRY-001: Retry Loop
# ===========================================================================


# @tests REQ-RETRY-001
def test_retry_loop_retries_on_retryable_error(monkeypatch, project_dir):
    """The retry loop retries on retryable errors and succeeds on subsequent attempt."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(SUCCESS_JSON),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 2
    assert len(sleep_calls) == 1
    assert result["new_key_points"] == ["insight"]


# ===========================================================================
# SCN-RETRY-001-01: First Attempt Succeeds -- No Retry
# ===========================================================================


# @tests SCN-RETRY-001-01
def test_scn_first_attempt_succeeds_no_retry(monkeypatch, project_dir, enable_diagnostic):
    """First attempt succeeds: no retry, no delay, no retry diagnostic log."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.return_value = _make_mock_response(SUCCESS_JSON)

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0
    assert result["new_key_points"] == ["insight"]
    # No retry-related diagnostic logs
    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) == 0


# ===========================================================================
# SCN-RETRY-001-02: First Attempt Fails Retryable, Second Succeeds
# ===========================================================================


# @tests SCN-RETRY-001-02
def test_scn_first_fails_second_succeeds(monkeypatch, project_dir):
    """Attempt 0 fails with APITimeoutError, attempt 1 succeeds."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(SUCCESS_JSON),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 2
    assert len(sleep_calls) == 1
    # Delay = BASE_DELAY * 2^0 * 1.0 = 2.0
    assert sleep_calls[0] == pytest.approx(2.0)
    assert result["new_key_points"] == ["insight"]


# ===========================================================================
# SCN-RETRY-001-03: First Two Attempts Fail Retryable, Third Succeeds
# ===========================================================================


# @tests SCN-RETRY-001-03
def test_scn_first_two_fail_third_succeeds(monkeypatch, project_dir):
    """Attempts 0 and 1 fail with APIConnectionError, attempt 2 succeeds."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APIConnectionError(request=MagicMock()),
        anthropic.APIConnectionError(request=MagicMock()),
        _make_mock_response(SUCCESS_JSON),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 3
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == pytest.approx(2.0)  # BASE_DELAY * 2^0
    assert sleep_calls[1] == pytest.approx(4.0)  # BASE_DELAY * 2^1
    assert result["new_key_points"] == ["insight"]


# ===========================================================================
# SCN-RETRY-001-04: All Three Attempts Fail Retryable -- Return Empty
# ===========================================================================


# @tests SCN-RETRY-001-04
def test_scn_all_three_fail_return_empty(monkeypatch, project_dir):
    """All 3 attempts fail with RateLimitError: returns empty, 2 sleeps, no exception."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
        ),
        anthropic.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
        ),
        anthropic.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
        ),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 3
    assert len(sleep_calls) == 2  # No sleep after final attempt
    assert result == {"new_key_points": [], "evaluations": []}


# ===========================================================================
# REQ-RETRY-002: Exponential Backoff with Jitter
# ===========================================================================


# @tests REQ-RETRY-002
def test_exponential_backoff_delay_values(monkeypatch, project_dir):
    """Delay follows BASE_DELAY * 2^attempt * jitter formula."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.InternalServerError(
            message="error", response=MagicMock(status_code=500, headers={}), body={}
        ),
        anthropic.InternalServerError(
            message="error", response=MagicMock(status_code=500, headers={}), body={}
        ),
        anthropic.InternalServerError(
            message="error", response=MagicMock(status_code=500, headers={}), body={}
        ),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert len(sleep_calls) == 2
    # Attempt 0: BASE_DELAY * 2^0 * 1.0 = 2.0
    assert sleep_calls[0] == pytest.approx(2.0)
    # Attempt 1: BASE_DELAY * 2^1 * 1.0 = 4.0
    assert sleep_calls[1] == pytest.approx(4.0)


# ===========================================================================
# SCN-RETRY-002-01: Jitter Applied to Delay
# ===========================================================================


# @tests SCN-RETRY-002-01
def test_scn_jitter_applied_to_delay(monkeypatch, project_dir):
    """Jitter factor is applied: delay = BASE_DELAY * 2^attempt * jitter."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    # Test with jitter = 0.75 (minimum)
    _fix_jitter(monkeypatch, 0.75)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert len(sleep_calls) == 1
    # BASE_DELAY * 2^0 * 0.75 = 2.0 * 1 * 0.75 = 1.5
    assert sleep_calls[0] == pytest.approx(1.5)


# ===========================================================================
# REQ-RETRY-003: Error Classification
# ===========================================================================


# @tests REQ-RETRY-003
def test_error_classification_retryable(monkeypatch, project_dir):
    """All retryable error types cause retry (more than 1 API call)."""
    retryable_errors = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APIConnectionError(request=MagicMock()),
        anthropic.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
        ),
        anthropic.InternalServerError(
            message="server error", response=MagicMock(status_code=500, headers={}), body={}
        ),
        anthropic.APIStatusError(
            message="service unavailable", response=MagicMock(status_code=503, headers={}), body={}
        ),
    ]

    for error in retryable_errors:
        mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
        _capture_sleep(monkeypatch)
        _fix_jitter(monkeypatch, 1.0)

        mock_client.messages.create.side_effect = [
            error,
            _make_mock_response(VALID_JSON),
        ]

        result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))
        assert mock_client.messages.create.call_count == 2, (
            f"{type(error).__name__} should be retried but was not"
        )
        assert "new_key_points" in result


# @tests REQ-RETRY-003
def test_error_classification_non_retryable(monkeypatch, project_dir):
    """All non-retryable error types cause immediate return (exactly 1 API call)."""
    non_retryable_errors = [
        anthropic.AuthenticationError(
            message="auth failed", response=MagicMock(status_code=401, headers={}), body={}
        ),
        anthropic.PermissionDeniedError(
            message="forbidden", response=MagicMock(status_code=403, headers={}), body={}
        ),
        anthropic.NotFoundError(
            message="not found", response=MagicMock(status_code=404, headers={}), body={}
        ),
        anthropic.BadRequestError(
            message="bad request", response=MagicMock(status_code=400, headers={}), body={}
        ),
        anthropic.UnprocessableEntityError(
            message="unprocessable", response=MagicMock(status_code=422, headers={}), body={}
        ),
        anthropic.APIResponseValidationError(
            response=MagicMock(status_code=200, headers={}), body={}, message="validation failed"
        ),
        RuntimeError("unexpected"),
    ]

    for error in non_retryable_errors:
        mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
        sleep_calls = _capture_sleep(monkeypatch)
        _fix_jitter(monkeypatch, 1.0)

        mock_client.messages.create.side_effect = error

        result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))
        assert mock_client.messages.create.call_count == 1, (
            f"{type(error).__name__} should NOT be retried"
        )
        assert result == {"new_key_points": [], "evaluations": []}
        assert len(sleep_calls) == 0


# ===========================================================================
# SCN-RETRY-003-01: APIStatusError with 503 -- Retried
# ===========================================================================


# @tests SCN-RETRY-003-01
def test_scn_api_status_error_503_retried(monkeypatch, project_dir):
    """APIStatusError with status_code=503 is retried (status >= 500)."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APIStatusError(
            message="service unavailable", response=MagicMock(status_code=503, headers={}), body={}
        ),
        _make_mock_response(VALID_JSON),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 2
    assert len(sleep_calls) == 1
    assert "new_key_points" in result


# ===========================================================================
# SCN-RETRY-003-02: APIStatusError with 404 -- Not Retried
# ===========================================================================


# @tests SCN-RETRY-003-02
def test_scn_api_status_error_404_not_retried(monkeypatch, project_dir):
    """NotFoundError (APIStatusError with status_code=404) is NOT retried."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = anthropic.NotFoundError(
        message="not found", response=MagicMock(status_code=404, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0
    assert result == {"new_key_points": [], "evaluations": []}


# ===========================================================================
# SCN-RETRY-003-03: APIResponseValidationError -- Not Retried
# ===========================================================================


# @tests SCN-RETRY-003-03
def test_scn_api_response_validation_error_not_retried(monkeypatch, project_dir):
    """APIResponseValidationError is NOT retried (sibling of APIStatusError)."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.APIResponseValidationError(
        response=MagicMock(status_code=200, headers={}), body={}, message="validation failed"
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0
    assert result == {"new_key_points": [], "evaluations": []}


# ===========================================================================
# SCN-RETRY-003-04: Unknown Non-APIError Exception -- Not Retried
# ===========================================================================


# @tests SCN-RETRY-003-04
def test_scn_runtime_error_not_retried(monkeypatch, project_dir):
    """RuntimeError (non-APIError) is NOT retried."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    mock_client.messages.create.side_effect = RuntimeError("unexpected")

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0
    assert result == {"new_key_points": [], "evaluations": []}


# ===========================================================================
# SCN-RETRY-003-05: APITimeoutError Caught Before APIConnectionError
# ===========================================================================


# @tests SCN-RETRY-003-05
def test_scn_api_timeout_caught_before_api_connection(monkeypatch, project_dir, enable_diagnostic):
    """APITimeoutError is caught correctly and logged as 'APITimeoutError', not 'APIConnectionError'."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # Find the per-attempt diagnostic
    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) >= 1
    # The first per-attempt log should say "APITimeoutError", not "APIConnectionError"
    assert "APITimeoutError" in retry_diags[0][0]
    assert "APIConnectionError" not in retry_diags[0][0]


# ===========================================================================
# SCN-RETRY-003-06: Unknown APIError Subclass -- Not Retried
# ===========================================================================


# @tests SCN-RETRY-003-06
def test_scn_unknown_api_error_not_retried(monkeypatch, project_dir):
    """Unknown APIError subclass is NOT retried (caught by APIError catch-all)."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    # Create a custom subclass of APIError to simulate an unknown future exception
    exc = anthropic.APIError(
        message="unknown api error", request=MagicMock(), body=None
    )

    mock_client.messages.create.side_effect = exc

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0
    assert result == {"new_key_points": [], "evaluations": []}


# ===========================================================================
# REQ-RETRY-004: Non-Retryable Immediate Return
# ===========================================================================


# @tests REQ-RETRY-004
def test_non_retryable_immediate_return(monkeypatch, project_dir):
    """Non-retryable errors immediately return empty with no retry and no delay."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.AuthenticationError(
        message="auth failed", response=MagicMock(status_code=401, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0
    assert result == {"new_key_points": [], "evaluations": []}


# ===========================================================================
# SCN-RETRY-004-01: Non-Retryable Error Logs Then Returns Empty
# ===========================================================================


# @tests SCN-RETRY-004-01
def test_scn_non_retryable_logs_then_returns_empty(monkeypatch, project_dir, enable_diagnostic):
    """AuthenticationError on attempt 0 with diagnostic mode: logs then returns empty."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.AuthenticationError(
        message="auth failed", response=MagicMock(status_code=401, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}
    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) == 1
    assert "Non-retryable error in extract_keypoints()" in retry_diags[0][0]
    assert "AuthenticationError" in retry_diags[0][0]
    assert "Returning empty result." in retry_diags[0][0]


# ===========================================================================
# SCN-RETRY-004-02: Non-Retryable Error Without Diagnostic Mode
# ===========================================================================


# @tests SCN-RETRY-004-02
def test_scn_non_retryable_no_log_when_diagnostic_off(monkeypatch, project_dir):
    """BadRequestError with diagnostic mode OFF: no save_diagnostic call."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.BadRequestError(
        message="bad request", response=MagicMock(status_code=400, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}
    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0
    # No diagnostic calls since mode is off
    assert len(diag_calls) == 0


# ===========================================================================
# SCN-RETRY-004-03: PermissionDeniedError (403) -- Immediate Return, No Retry
# ===========================================================================


# @tests SCN-RETRY-004-03
def test_scn_permission_denied_immediate_return(monkeypatch, project_dir, enable_diagnostic):
    """PermissionDeniedError (403) classified as non-retryable, returns empty."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.PermissionDeniedError(
        message="forbidden", response=MagicMock(status_code=403, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}
    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) == 1
    assert "PermissionDeniedError" in retry_diags[0][0]
    assert "Non-retryable error" in retry_diags[0][0]


# ===========================================================================
# SCN-RETRY-004-04: UnprocessableEntityError (422) -- Immediate Return, No Retry
# ===========================================================================


# @tests SCN-RETRY-004-04
def test_scn_unprocessable_entity_immediate_return(monkeypatch, project_dir, enable_diagnostic):
    """UnprocessableEntityError (422) classified as non-retryable, returns empty."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.UnprocessableEntityError(
        message="unprocessable", response=MagicMock(status_code=422, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}
    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) == 1
    assert "UnprocessableEntityError" in retry_diags[0][0]
    assert "Non-retryable error" in retry_diags[0][0]


# ===========================================================================
# REQ-RETRY-005: Post-Exhaustion Return
# ===========================================================================


# @tests REQ-RETRY-005
def test_exhaustion_returns_empty(monkeypatch, project_dir):
    """After exhausting MAX_RETRIES, returns empty result without propagating."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APIConnectionError(request=MagicMock()),
        anthropic.APIConnectionError(request=MagicMock()),
        anthropic.APIConnectionError(request=MagicMock()),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}
    assert mock_client.messages.create.call_count == 3
    assert len(sleep_calls) == 2  # No delay after final attempt


# ===========================================================================
# SCN-RETRY-005-01: Exhaustion Returns Empty After MAX_RETRIES
# ===========================================================================


# @tests SCN-RETRY-005-01
def test_scn_exhaustion_logs_and_returns_empty(monkeypatch, project_dir, enable_diagnostic):
    """All 3 attempts fail with InternalServerError: logs per-attempt + exhaustion."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.InternalServerError(
            message="server error", response=MagicMock(status_code=500, headers={}), body={}
        ),
        anthropic.InternalServerError(
            message="server error", response=MagicMock(status_code=500, headers={}), body={}
        ),
        anthropic.InternalServerError(
            message="server error", response=MagicMock(status_code=500, headers={}), body={}
        ),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}
    assert len(sleep_calls) == 2

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    # 2 per-attempt logs (attempts 0, 1) + 1 exhaustion log
    assert len(retry_diags) == 3
    # Per-attempt logs
    assert "Retry attempt 1/3 failed" in retry_diags[0][0]
    assert "Retry attempt 2/3 failed" in retry_diags[1][0]
    # Exhaustion log
    assert "All 3 attempts failed for extract_keypoints()" in retry_diags[2][0]
    assert "Returning empty result." in retry_diags[2][0]


# ===========================================================================
# REQ-RETRY-006: Per-Request Timeout
# ===========================================================================


# @tests REQ-RETRY-006
def test_timeout_parameter_passed(monkeypatch, project_dir):
    """timeout=30.0 is passed to client.messages.create on every call."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)

    mock_client.messages.create.return_value = _make_mock_response(VALID_JSON)

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    call_kwargs = mock_client.messages.create.call_args
    assert call_kwargs.kwargs.get("timeout") == 30.0 or call_kwargs[1].get("timeout") == 30.0


# ===========================================================================
# SCN-RETRY-006-01: Timeout Parameter Passed to SDK
# ===========================================================================


# @tests SCN-RETRY-006-01
def test_scn_timeout_on_every_attempt(monkeypatch, project_dir):
    """timeout=30.0 is set on every attempt (0, 1, 2)."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 3
    for call in mock_client.messages.create.call_args_list:
        timeout_val = call.kwargs.get("timeout") or call[1].get("timeout")
        assert timeout_val == 30.0


# ===========================================================================
# REQ-RETRY-007: Diagnostic Logging
# ===========================================================================


# @tests REQ-RETRY-007
def test_diagnostic_logging_per_attempt(monkeypatch, project_dir, enable_diagnostic):
    """Per-attempt diagnostic log emitted on retryable errors (not final attempt)."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    # 1 per-attempt log + 1 success-after-retry log
    assert len(retry_diags) == 2
    assert "Retry attempt 1/3 failed" in retry_diags[0][0]
    assert "Next attempt in 2.0s" in retry_diags[0][0]


# @tests REQ-RETRY-007
def test_diagnostic_logging_exhaustion(monkeypatch, project_dir, enable_diagnostic):
    """Exhaustion diagnostic log emitted when all attempts fail."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
        ),
        anthropic.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
        ),
        anthropic.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
        ),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    exhaustion_logs = [c for c in retry_diags if "All 3 attempts failed" in c[0]]
    assert len(exhaustion_logs) == 1


# @tests REQ-RETRY-007
def test_diagnostic_logging_success_after_retry(monkeypatch, project_dir, enable_diagnostic):
    """Success-after-retry diagnostic log emitted when attempt > 0 succeeds."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    success_logs = [c for c in retry_diags if "succeeded on attempt" in c[0]]
    assert len(success_logs) == 1
    assert "succeeded on attempt 2 after 1 retries." in success_logs[0][0]


# ===========================================================================
# SCN-RETRY-007-01: Per-Attempt Diagnostic Log on Retryable Error
# ===========================================================================


# @tests SCN-RETRY-007-01
def test_scn_per_attempt_diagnostic_log(monkeypatch, project_dir, enable_diagnostic):
    """Per-attempt log has correct format: 'Retry attempt 1/3 failed: APITimeoutError: ...'"""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    per_attempt = [c for c in retry_diags if "Retry attempt" in c[0]]
    assert len(per_attempt) == 1
    content = per_attempt[0][0]
    assert content.startswith("Retry attempt 1/3 failed: APITimeoutError:")
    assert "Next attempt in 2.0s" in content
    assert per_attempt[0][1] == "retry_extract_keypoints"


# ===========================================================================
# SCN-RETRY-007-02: No Diagnostic Log When Diagnostic Mode Off
# ===========================================================================


# @tests SCN-RETRY-007-02
def test_scn_no_diagnostic_when_mode_off(monkeypatch, project_dir):
    """Diagnostic mode off: no save_diagnostic calls, but retry still proceeds."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # Retry still works
    assert mock_client.messages.create.call_count == 2
    assert len(sleep_calls) == 1
    # But no diagnostic logs
    assert len(diag_calls) == 0


# ===========================================================================
# SCN-RETRY-007-03: Success After Retry Logged
# ===========================================================================


# @tests SCN-RETRY-007-03
def test_scn_success_after_retry_logged(monkeypatch, project_dir, enable_diagnostic):
    """Success after 1 retry: log 'succeeded on attempt 2 after 1 retries.'"""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    success_logs = [c for c in retry_diags if "succeeded on attempt" in c[0]]
    assert len(success_logs) == 1
    assert "extract_keypoints() succeeded on attempt 2 after 1 retries." == success_logs[0][0]


# ===========================================================================
# SCN-RETRY-007-04: No Diagnostic Log on First-Attempt Success
# ===========================================================================


# @tests SCN-RETRY-007-04
def test_scn_no_diagnostic_on_first_attempt_success(monkeypatch, project_dir, enable_diagnostic):
    """First attempt succeeds: no retry-related diagnostic logs emitted."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.return_value = _make_mock_response(VALID_JSON)

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) == 0


# ===========================================================================
# REQ-RETRY-008: Module-Level Constants
# ===========================================================================


# @tests REQ-RETRY-008
def test_module_constants_defined():
    """MAX_RETRIES=3 and BASE_DELAY=2.0 are module-level constants."""
    assert _common_module.MAX_RETRIES == 3
    assert isinstance(_common_module.MAX_RETRIES, int)
    assert _common_module.BASE_DELAY == 2.0
    assert isinstance(_common_module.BASE_DELAY, float)


# ===========================================================================
# INV-RETRY-001: Function Signature Unchanged
# ===========================================================================


# @tests-invariant INV-RETRY-001
def test_invariant_function_signature_unchanged():
    """extract_keypoints signature matches contract: (messages, playbook, diagnostic_name)."""
    sig = inspect.signature(extract_keypoints)
    params = list(sig.parameters.keys())
    assert params == ["messages", "playbook", "diagnostic_name"]

    # Check parameter annotations
    messages_param = sig.parameters["messages"]
    playbook_param = sig.parameters["playbook"]
    diagnostic_name_param = sig.parameters["diagnostic_name"]

    assert diagnostic_name_param.default == "reflection"

    # Verify type annotations per INV-RETRY-001
    assert messages_param.annotation == list[dict], (
        f"messages annotation should be list[dict], got {messages_param.annotation}"
    )
    assert playbook_param.annotation == dict, (
        f"playbook annotation should be dict, got {playbook_param.annotation}"
    )
    assert diagnostic_name_param.annotation == str, (
        f"diagnostic_name annotation should be str, got {diagnostic_name_param.annotation}"
    )
    assert sig.return_annotation == dict, (
        f"return annotation should be dict, got {sig.return_annotation}"
    )


# ===========================================================================
# INV-RETRY-002: Only client.messages.create() Is Retried
# ===========================================================================


# @tests-invariant INV-RETRY-002
def test_invariant_only_api_call_retried(monkeypatch, project_dir):
    """Prompt construction, template loading, and settings loading run once; only API call is retried."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    load_template_calls = []
    original_load_template = lambda name: "Trajectories: {trajectories}\nPlaybook: {playbook}"

    def counting_load_template(name):
        load_template_calls.append(name)
        return original_load_template(name)

    monkeypatch.setattr(_common_module, "load_template", counting_load_template)

    load_settings_calls = []
    original_load_settings = _common_module.load_settings

    def counting_load_settings():
        load_settings_calls.append(1)
        return original_load_settings()

    monkeypatch.setattr(_common_module, "load_settings", counting_load_settings)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # load_template called exactly once (not retried)
    assert len(load_template_calls) == 1
    # load_settings called exactly once (not retried)
    assert len(load_settings_calls) == 1
    # API call made twice (1 failure + 1 success)
    assert mock_client.messages.create.call_count == 2


# ===========================================================================
# INV-RETRY-003: Total Time Within Hook Timeout
# ===========================================================================


# @tests-invariant INV-RETRY-003
def test_invariant_total_time_bounded():
    """Worst-case total time < 120s hook timeout (mathematical assertion)."""
    max_retries = _common_module.MAX_RETRIES
    base_delay = _common_module.BASE_DELAY
    per_request_timeout = 30.0
    max_jitter = 1.25

    worst_case_time = max_retries * per_request_timeout
    for attempt in range(max_retries - 1):
        worst_case_time += base_delay * (2 ** attempt) * max_jitter

    # With defaults: 3*30 + 2.0*1*1.25 + 2.0*2*1.25 = 90 + 2.5 + 5.0 = 97.5
    assert worst_case_time == pytest.approx(97.5)
    assert worst_case_time < 120.0


# ===========================================================================
# INV-RETRY-004: Return Value Always Valid Extraction Result
# ===========================================================================


# @tests-invariant INV-RETRY-004
def test_invariant_return_value_always_valid(monkeypatch, project_dir):
    """Every error path returns a dict with new_key_points and evaluations lists."""
    error_scenarios = [
        # Retryable errors leading to exhaustion
        [
            anthropic.APITimeoutError(request=MagicMock()),
            anthropic.APITimeoutError(request=MagicMock()),
            anthropic.APITimeoutError(request=MagicMock()),
        ],
        [
            anthropic.APIConnectionError(request=MagicMock()),
            anthropic.APIConnectionError(request=MagicMock()),
            anthropic.APIConnectionError(request=MagicMock()),
        ],
        [
            anthropic.RateLimitError(
                message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
            ),
            anthropic.RateLimitError(
                message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
            ),
            anthropic.RateLimitError(
                message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
            ),
        ],
        # Non-retryable errors (single)
        [anthropic.AuthenticationError(
            message="auth", response=MagicMock(status_code=401, headers={}), body={}
        )],
        [anthropic.PermissionDeniedError(
            message="forbidden", response=MagicMock(status_code=403, headers={}), body={}
        )],
        [anthropic.NotFoundError(
            message="not found", response=MagicMock(status_code=404, headers={}), body={}
        )],
        [anthropic.BadRequestError(
            message="bad", response=MagicMock(status_code=400, headers={}), body={}
        )],
        [anthropic.UnprocessableEntityError(
            message="unprocessable", response=MagicMock(status_code=422, headers={}), body={}
        )],
        [anthropic.APIResponseValidationError(
            response=MagicMock(status_code=200, headers={}), body={}, message="validation"
        )],
        [anthropic.APIError(message="unknown", request=MagicMock(), body=None)],
        [RuntimeError("unexpected")],
    ]

    for errors in error_scenarios:
        mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
        _capture_sleep(monkeypatch)
        _fix_jitter(monkeypatch, 1.0)

        if len(errors) == 1:
            mock_client.messages.create.side_effect = errors[0]
        else:
            mock_client.messages.create.side_effect = errors

        result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

        # Validate structure
        assert isinstance(result, dict), f"Result should be dict for {type(errors[0]).__name__}"
        assert "new_key_points" in result
        assert "evaluations" in result
        assert isinstance(result["new_key_points"], list)
        assert isinstance(result["evaluations"], list)


# ===========================================================================
# Adversarial: Boundary Conditions (TC-BOUND-*)
# ===========================================================================


# @tests REQ-RETRY-001, SCN-RETRY-001-04 (TC-BOUND-001)
def test_tc_bound_001_exactly_max_retries_attempts(monkeypatch, project_dir):
    """TC-BOUND-001: Exactly MAX_RETRIES=3 API calls, not 4."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 3  # Not 4


# @tests REQ-RETRY-002, SCN-RETRY-001-04 (TC-BOUND-002)
def test_tc_bound_002_exactly_max_retries_minus_1_delays(monkeypatch, project_dir):
    """TC-BOUND-002: Exactly 2 sleep calls for MAX_RETRIES=3 (no sleep after final)."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert len(sleep_calls) == 2  # Not 3


# @tests REQ-RETRY-001, REQ-RETRY-008 (TC-BOUND-003)
def test_tc_bound_003_max_retries_1_single_attempt(monkeypatch, project_dir):
    """TC-BOUND-003: MAX_RETRIES=1 means single attempt, no retry, no delay."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)
    monkeypatch.setattr(_common_module, "MAX_RETRIES", 1)

    mock_client.messages.create.side_effect = anthropic.APITimeoutError(request=MagicMock())

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0
    assert result == {"new_key_points": [], "evaluations": []}


# @tests REQ-RETRY-003, SCN-RETRY-003-01 (TC-BOUND-004)
def test_tc_bound_004_status_500_retried(monkeypatch, project_dir):
    """TC-BOUND-004: Generic APIStatusError at exactly status=500 is retried via catch-all handler."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    # Use generic APIStatusError (not InternalServerError subclass) so it reaches
    # the APIStatusError catch-all handler and tests the status_code >= 500 boundary.
    mock_client.messages.create.side_effect = [
        anthropic.APIStatusError(
            message="server error",
            response=MagicMock(status_code=500, headers={}),
            body={},
        ),
        _make_mock_response(VALID_JSON),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 2


# @tests REQ-RETRY-003, SCN-RETRY-003-02 (TC-BOUND-005)
def test_tc_bound_005_status_499_not_retried(monkeypatch, project_dir):
    """TC-BOUND-005: APIStatusError at status=499 is NOT retried (< 500)."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.APIStatusError(
        message="client error", response=MagicMock(status_code=499, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0
    assert result == {"new_key_points": [], "evaluations": []}


# @tests REQ-RETRY-002, SCN-RETRY-002-01 (TC-BOUND-006)
def test_tc_bound_006_jitter_minimum(monkeypatch, project_dir):
    """TC-BOUND-006: Jitter=0.75 produces minimum delay: 2.0*2^0*0.75=1.5s."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 0.75)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert sleep_calls[0] == pytest.approx(1.5)


# @tests REQ-RETRY-002, SCN-RETRY-002-01 (TC-BOUND-007)
def test_tc_bound_007_jitter_maximum(monkeypatch, project_dir):
    """TC-BOUND-007: Jitter=1.25 produces maximum delay: 2.0*2^0*1.25=2.5s."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.25)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert sleep_calls[0] == pytest.approx(2.5)


# @tests REQ-RETRY-001, SCN-RETRY-001-03 (TC-BOUND-008)
def test_tc_bound_008_success_on_final_attempt(monkeypatch, project_dir, enable_diagnostic):
    """TC-BOUND-008: Success on final attempt: MAX_RETRIES-1 delays, no exhaustion log."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 3
    assert len(sleep_calls) == 2
    assert "new_key_points" in result

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    exhaustion_logs = [c for c in retry_diags if "All 3 attempts failed" in c[0]]
    assert len(exhaustion_logs) == 0  # No exhaustion since final attempt succeeded

    success_logs = [c for c in retry_diags if "succeeded on attempt 3" in c[0]]
    assert len(success_logs) == 1


# ===========================================================================
# Adversarial: Error Classification Edge Cases (TC-ERR-*)
# ===========================================================================


# @tests REQ-RETRY-003, SCN-RETRY-003-05 (TC-ERR-001)
def test_tc_err_001_timeout_not_caught_as_connection(monkeypatch, project_dir, enable_diagnostic):
    """TC-ERR-001: APITimeoutError logged as 'APITimeoutError', not 'APIConnectionError'."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    per_attempt = [c for c in retry_diags if "Retry attempt" in c[0]]
    assert len(per_attempt) >= 1
    assert "APITimeoutError" in per_attempt[0][0]
    assert "APIConnectionError" not in per_attempt[0][0]


# @tests REQ-RETRY-003 (TC-ERR-002)
def test_tc_err_002_rate_limit_retried_not_4xx(monkeypatch, project_dir):
    """TC-ERR-002: RateLimitError (429) is retryable, not caught by 4xx handler."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
        ),
        _make_mock_response(VALID_JSON),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 2  # Was retried
    assert "new_key_points" in result


# @tests REQ-RETRY-003, SCN-RETRY-003-01 (TC-ERR-003)
def test_tc_err_003_status_503_retried_via_5xx(monkeypatch, project_dir):
    """TC-ERR-003: APIStatusError with 503 retried through 5xx branch."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APIStatusError(
            message="service unavailable",
            response=MagicMock(status_code=503, headers={}),
            body={},
        ),
        _make_mock_response(VALID_JSON),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 2


# @tests REQ-RETRY-003, SCN-RETRY-003-02 (TC-ERR-004)
def test_tc_err_004_status_404_not_retried(monkeypatch, project_dir):
    """TC-ERR-004: NotFoundError (404) not retried (status < 500)."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.NotFoundError(
        message="not found", response=MagicMock(status_code=404, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0


# @tests REQ-RETRY-003, SCN-RETRY-003-03 (TC-ERR-005)
def test_tc_err_005_response_validation_not_retried(monkeypatch, project_dir):
    """TC-ERR-005: APIResponseValidationError not retried (sibling of APIStatusError)."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.APIResponseValidationError(
        response=MagicMock(status_code=200, headers={}), body={}, message="fail"
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0


# @tests REQ-RETRY-003, SCN-RETRY-003-06 (TC-ERR-006)
def test_tc_err_006_unknown_api_error_not_retried(monkeypatch, project_dir):
    """TC-ERR-006: Unknown APIError subclass not retried."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    exc = anthropic.APIError(message="unknown", request=MagicMock(), body=None)
    mock_client.messages.create.side_effect = exc

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0


# @tests REQ-RETRY-003, SCN-RETRY-003-04 (TC-ERR-007)
def test_tc_err_007_bare_exception_not_retried(monkeypatch, project_dir):
    """TC-ERR-007: Bare Exception (RuntimeError) not retried."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    mock_client.messages.create.side_effect = RuntimeError("unexpected")

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0


# @tests REQ-RETRY-004, SCN-RETRY-004-01 (TC-ERR-008)
def test_tc_err_008_auth_error_not_retried(monkeypatch, project_dir):
    """TC-ERR-008: AuthenticationError (401) not retried."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.AuthenticationError(
        message="auth", response=MagicMock(status_code=401, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert result == {"new_key_points": [], "evaluations": []}


# @tests REQ-RETRY-004, SCN-RETRY-004-03 (TC-ERR-009)
def test_tc_err_009_permission_denied_not_retried(monkeypatch, project_dir):
    """TC-ERR-009: PermissionDeniedError (403) not retried."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.PermissionDeniedError(
        message="forbidden", response=MagicMock(status_code=403, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert result == {"new_key_points": [], "evaluations": []}


# @tests REQ-RETRY-004, SCN-RETRY-004-04 (TC-ERR-010)
def test_tc_err_010_unprocessable_entity_not_retried(monkeypatch, project_dir):
    """TC-ERR-010: UnprocessableEntityError (422) not retried."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.UnprocessableEntityError(
        message="unprocessable", response=MagicMock(status_code=422, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert result == {"new_key_points": [], "evaluations": []}


# @tests REQ-RETRY-004, SCN-RETRY-004-02 (TC-ERR-011)
def test_tc_err_011_bad_request_no_diagnostic_when_off(monkeypatch, project_dir):
    """TC-ERR-011: BadRequestError (400) with diagnostic off: no save_diagnostic."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.BadRequestError(
        message="bad request", response=MagicMock(status_code=400, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}
    assert len(diag_calls) == 0


# ===========================================================================
# Adversarial: Negative Paths (TC-NEG-*)
# ===========================================================================


# @tests REQ-RETRY-004, SCN-RETRY-004-01 (TC-NEG-001)
def test_tc_neg_001_non_retryable_on_first_attempt(monkeypatch, project_dir):
    """TC-NEG-001: Non-retryable on first attempt: 1 API call, immediate empty."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.AuthenticationError(
        message="auth", response=MagicMock(status_code=401, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 1
    assert len(sleep_calls) == 0
    assert result == {"new_key_points": [], "evaluations": []}


# @tests REQ-RETRY-005, SCN-RETRY-005-01 (TC-NEG-002)
def test_tc_neg_002_all_retryable_exhaustion(monkeypatch, project_dir):
    """TC-NEG-002: All retryable errors lead to exhaustion."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 3
    assert len(sleep_calls) == 2
    assert result == {"new_key_points": [], "evaluations": []}


# @tests REQ-RETRY-003, REQ-RETRY-004 (TC-NEG-003)
def test_tc_neg_003_mixed_retryable_then_non_retryable(monkeypatch, project_dir):
    """TC-NEG-003: Retryable then non-retryable: returns empty immediately."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.AuthenticationError(
            message="auth", response=MagicMock(status_code=401, headers={}), body={}
        ),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert mock_client.messages.create.call_count == 2
    assert len(sleep_calls) == 1  # Delay after first retryable error
    assert result == {"new_key_points": [], "evaluations": []}


# @tests REQ-RETRY-001, INV-RETRY-002 (TC-NEG-004)
def test_tc_neg_004_anthropic_not_available_early_return(monkeypatch, project_dir):
    """TC-NEG-004: ANTHROPIC_AVAILABLE=False: early return, no API call, no delay."""
    monkeypatch.setattr(_common_module, "ANTHROPIC_AVAILABLE", False)

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}


# @tests REQ-RETRY-007, SCN-RETRY-007-04 (TC-NEG-005)
def test_tc_neg_005_no_diagnostic_on_first_success(monkeypatch, project_dir, enable_diagnostic):
    """TC-NEG-005: First attempt succeeds: no retry-related diagnostics even with mode on."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.return_value = _make_mock_response(VALID_JSON)

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) == 0


# ===========================================================================
# Adversarial: Jitter and Timing (TC-TIME-*)
# ===========================================================================


# @tests REQ-RETRY-002, SCN-RETRY-002-01 (TC-TIME-001)
def test_tc_time_001_sleep_value_correct(monkeypatch, project_dir):
    """TC-TIME-001: Sleep called with correct value matching formula."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 0.9)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # BASE_DELAY * 2^0 * 0.9 = 2.0 * 1 * 0.9 = 1.8
    assert sleep_calls[0] == pytest.approx(1.8)


# @tests REQ-RETRY-001, REQ-RETRY-002, SCN-RETRY-001-04 (TC-TIME-002)
def test_tc_time_002_no_sleep_after_final_attempt(monkeypatch, project_dir):
    """TC-TIME-002: No sleep after final attempt (attempt MAX_RETRIES-1)."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert len(sleep_calls) == 2  # Not 3


# @tests REQ-RETRY-002 (TC-TIME-003)
def test_tc_time_003_delay_doubles_between_attempts(monkeypatch, project_dir):
    """TC-TIME-003: Delay doubles: attempt 0 base=2.0, attempt 1 base=4.0."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert len(sleep_calls) == 2
    assert sleep_calls[1] / sleep_calls[0] == pytest.approx(2.0)


# @tests REQ-RETRY-006, SCN-RETRY-006-01 (TC-TIME-004)
def test_tc_time_004_timeout_30_on_every_attempt(monkeypatch, project_dir):
    """TC-TIME-004: timeout=30.0 on every API call."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    for call in mock_client.messages.create.call_args_list:
        timeout_val = call.kwargs.get("timeout") or call[1].get("timeout")
        assert timeout_val == 30.0


# ===========================================================================
# Instrumentation Tests (LOG-RETRY-*)
# ===========================================================================


# @tests-instrumentation LOG-RETRY-001
def test_instrumentation_per_attempt_log_on_retryable(monkeypatch, project_dir, enable_diagnostic):
    """LOG-RETRY-001: Per-attempt log emitted with correct format on retryable error."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    per_attempt = [c for c in retry_diags if "Retry attempt" in c[0]]
    assert len(per_attempt) == 1
    content = per_attempt[0][0]
    # Verify format: "Retry attempt 1/3 failed: APITimeoutError: <msg>. Next attempt in 2.0s"
    assert "Retry attempt 1/3 failed: APITimeoutError:" in content
    assert "Next attempt in 2.0s" in content
    assert per_attempt[0][1] == "retry_extract_keypoints"


# @tests-instrumentation LOG-RETRY-001
def test_instrumentation_per_attempt_log_two_failures(monkeypatch, project_dir, enable_diagnostic):
    """LOG-RETRY-001: Two per-attempt logs for attempts 0 and 1."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APIConnectionError(request=MagicMock()),
        anthropic.APIConnectionError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    per_attempt = [c for c in retry_diags if "Retry attempt" in c[0]]
    assert len(per_attempt) == 2
    assert "1/3" in per_attempt[0][0]
    assert "2/3" in per_attempt[1][0]
    # Verify delay values: attempt 0 delay=2.0, attempt 1 delay=4.0
    assert "2.0s" in per_attempt[0][0]
    assert "4.0s" in per_attempt[1][0]


# @tests-instrumentation LOG-RETRY-001
def test_instrumentation_per_attempt_not_emitted_diagnostic_off(monkeypatch, project_dir):
    """LOG-RETRY-001: No per-attempt logs when diagnostic mode is off."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert len(diag_calls) == 0


# @tests-instrumentation LOG-RETRY-001
def test_instrumentation_per_attempt_not_emitted_on_final_attempt(
    monkeypatch, project_dir, enable_diagnostic
):
    """LOG-RETRY-001: Per-attempt log NOT emitted for final attempt (triggers exhaustion instead)."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    per_attempt = [c for c in retry_diags if "Retry attempt" in c[0]]
    # Only attempts 0 and 1 get per-attempt logs, NOT attempt 2
    assert len(per_attempt) == 2
    assert "3/3" not in per_attempt[0][0] and "3/3" not in per_attempt[1][0]


# @tests-instrumentation LOG-RETRY-002
def test_instrumentation_exhaustion_logged(monkeypatch, project_dir, enable_diagnostic):
    """LOG-RETRY-002: Exhaustion log emitted when all attempts fail."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.InternalServerError(
            message="error", response=MagicMock(status_code=500, headers={}), body={}
        ),
        anthropic.InternalServerError(
            message="error", response=MagicMock(status_code=500, headers={}), body={}
        ),
        anthropic.InternalServerError(
            message="error", response=MagicMock(status_code=500, headers={}), body={}
        ),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    exhaustion = [c for c in retry_diags if "All 3 attempts failed" in c[0]]
    assert len(exhaustion) == 1
    assert exhaustion[0][0] == "All 3 attempts failed for extract_keypoints(). Returning empty result."
    assert exhaustion[0][1] == "retry_extract_keypoints"


# @tests-instrumentation LOG-RETRY-002
def test_instrumentation_success_after_retry_logged(monkeypatch, project_dir, enable_diagnostic):
    """LOG-RETRY-002: Success-after-retry log emitted for attempt 1 success."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
        ),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    success = [c for c in retry_diags if "succeeded on attempt" in c[0]]
    assert len(success) == 1
    assert success[0][0] == "extract_keypoints() succeeded on attempt 2 after 1 retries."
    assert success[0][1] == "retry_extract_keypoints"


# @tests-instrumentation LOG-RETRY-002
def test_instrumentation_success_after_two_retries_logged(monkeypatch, project_dir, enable_diagnostic):
    """LOG-RETRY-002: Success-after-2-retries log: 'succeeded on attempt 3 after 2 retries.'"""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    success = [c for c in retry_diags if "succeeded on attempt" in c[0]]
    assert len(success) == 1
    assert success[0][0] == "extract_keypoints() succeeded on attempt 3 after 2 retries."


# @tests-instrumentation LOG-RETRY-002
def test_instrumentation_no_success_log_on_first_attempt(monkeypatch, project_dir, enable_diagnostic):
    """LOG-RETRY-002: No success-after-retry log when attempt 0 succeeds."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.return_value = _make_mock_response(VALID_JSON)

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) == 0


# @tests-instrumentation LOG-RETRY-002
def test_instrumentation_exhaustion_not_logged_diagnostic_off(monkeypatch, project_dir):
    """LOG-RETRY-002: Exhaustion log NOT emitted when diagnostic mode is off."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}
    assert len(diag_calls) == 0


# @tests-instrumentation LOG-RETRY-003
def test_instrumentation_non_retryable_logged(monkeypatch, project_dir, enable_diagnostic):
    """LOG-RETRY-003: Non-retryable error logged with correct format."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.AuthenticationError(
        message="auth failed", response=MagicMock(status_code=401, headers={}), body={}
    )

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) == 1
    content = retry_diags[0][0]
    assert content.startswith("Non-retryable error in extract_keypoints(): AuthenticationError:")
    assert "Returning empty result." in content


# @tests-instrumentation LOG-RETRY-003
def test_instrumentation_non_retryable_api_response_validation(
    monkeypatch, project_dir, enable_diagnostic
):
    """LOG-RETRY-003: APIResponseValidationError logged with class name."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.APIResponseValidationError(
        response=MagicMock(status_code=200, headers={}), body={}, message="validation failed"
    )

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) == 1
    assert "APIResponseValidationError" in retry_diags[0][0]


# @tests-instrumentation LOG-RETRY-003
def test_instrumentation_non_retryable_bare_exception(monkeypatch, project_dir, enable_diagnostic):
    """LOG-RETRY-003: RuntimeError logged with class name."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.side_effect = RuntimeError("unexpected error")

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) == 1
    assert "RuntimeError" in retry_diags[0][0]
    assert "unexpected error" in retry_diags[0][0]


# @tests-instrumentation LOG-RETRY-003
def test_instrumentation_non_retryable_unknown_api_error(monkeypatch, project_dir, enable_diagnostic):
    """LOG-RETRY-003: Unknown APIError subclass logged with type(exc).__name__."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    exc = anthropic.APIError(message="unknown api error", request=MagicMock(), body=None)
    mock_client.messages.create.side_effect = exc

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) == 1
    assert "APIError" in retry_diags[0][0]
    assert "Non-retryable error" in retry_diags[0][0]


# @tests-instrumentation LOG-RETRY-003
def test_instrumentation_non_retryable_not_logged_diagnostic_off(monkeypatch, project_dir):
    """LOG-RETRY-003: Non-retryable error NOT logged when diagnostic mode is off."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)

    mock_client.messages.create.side_effect = anthropic.AuthenticationError(
        message="auth failed", response=MagicMock(status_code=401, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}
    assert len(diag_calls) == 0


# ===========================================================================
# Additional Branch Coverage: APIConnectionError exhaustion with diagnostic
# ===========================================================================


# @tests REQ-RETRY-005, REQ-RETRY-007, SCN-RETRY-005-01
def test_api_connection_error_exhaustion_diagnostic(monkeypatch, project_dir, enable_diagnostic):
    """APIConnectionError exhaustion branch with diagnostic mode on: covers line 839."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APIConnectionError(request=MagicMock()),
        anthropic.APIConnectionError(request=MagicMock()),
        anthropic.APIConnectionError(request=MagicMock()),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}
    assert len(sleep_calls) == 2

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    exhaustion = [c for c in retry_diags if "All 3 attempts failed" in c[0]]
    assert len(exhaustion) == 1


# ===========================================================================
# Additional Branch Coverage: APIStatusError 5xx per-attempt diagnostic + exhaustion
# ===========================================================================


# @tests REQ-RETRY-003, REQ-RETRY-005, REQ-RETRY-007, SCN-RETRY-003-01
def test_api_status_error_5xx_exhaustion_diagnostic(monkeypatch, project_dir, enable_diagnostic):
    """APIStatusError (503) exhaustion with diagnostic mode on: covers lines 895, 903-909."""
    mock_client, _ = _setup_extract_keypoints_mocks(monkeypatch)
    sleep_calls = _capture_sleep(monkeypatch)
    diag_calls = _capture_diagnostic(monkeypatch)
    _fix_jitter(monkeypatch, 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APIStatusError(
            message="service unavailable", response=MagicMock(status_code=503, headers={}), body={}
        ),
        anthropic.APIStatusError(
            message="service unavailable", response=MagicMock(status_code=503, headers={}), body={}
        ),
        anthropic.APIStatusError(
            message="service unavailable", response=MagicMock(status_code=503, headers={}), body={}
        ),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}
    assert len(sleep_calls) == 2

    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    # 2 per-attempt logs + 1 exhaustion log
    per_attempt = [c for c in retry_diags if "Retry attempt" in c[0]]
    exhaustion = [c for c in retry_diags if "All 3 attempts failed" in c[0]]
    assert len(per_attempt) == 2
    assert len(exhaustion) == 1
    # Per-attempt logs should use type(exc).__name__
    assert "APIStatusError" in per_attempt[0][0]
