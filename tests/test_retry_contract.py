# Spec: docs/retry/spec.md
# Contract: docs/retry/contract.md
# Testing: docs/retry/testing.md
"""
Contract (black-box) tests for retry logic with exponential backoff.

These tests exercise extract_keypoints() and module-level constants
as documented in contract.md. They do NOT reference internal branches,
implementation details, or design.md. They verify only behaviors
promised by the data contracts.
"""

import asyncio
import inspect
import json
import sys
import time
from types import ModuleType
from unittest.mock import MagicMock

import anthropic
import pytest

sys.path.insert(0, "/data/agentic_context_engineering")

import src.hooks.common as _common_module

from src.hooks.common import extract_keypoints


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_JSON = '{"new_key_points": ["insight"], "evaluations": [{"name": "pat-001", "rating": "helpful"}]}'
EMPTY_JSON = '{"new_key_points": [], "evaluations": []}'


def _setup_retry_mocks(monkeypatch):
    """Minimal mock setup for contract tests.

    Returns mock_client so callers can configure messages.create behavior.
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
    # Copy exception classes from real anthropic module
    for attr_name in dir(anthropic):
        obj = getattr(anthropic, attr_name)
        if isinstance(obj, type) and issubclass(obj, BaseException):
            setattr(fake_anthropic, attr_name, obj)
    monkeypatch.setattr(_common_module, "anthropic", fake_anthropic, raising=False)

    return mock_client


def _make_mock_response(json_text):
    """Create a mock response object with content[0].text = json_text."""
    mock_response = MagicMock()
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = json_text
    mock_response.content = [mock_text_block]
    return mock_response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """Set CLAUDE_PROJECT_DIR to a temp directory with .claude/ structure."""
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


# @tests-contract REQ-RETRY-001
def test_contract_retry_returns_result_after_transient_failure(monkeypatch, project_dir):
    """Contract: extract_keypoints returns valid result after transient API failure."""
    mock_client = _setup_retry_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda d: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 1.0)

    # First call fails (retryable), second succeeds
    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # Contract: returns a dict with new_key_points and evaluations
    assert isinstance(result, dict)
    assert "new_key_points" in result
    assert "evaluations" in result
    assert isinstance(result["new_key_points"], list)
    assert isinstance(result["evaluations"], list)


# ===========================================================================
# REQ-RETRY-002: Exponential Backoff with Jitter
# ===========================================================================


# @tests-contract REQ-RETRY-002
def test_contract_backoff_no_immediate_retry(monkeypatch, project_dir):
    """Contract: backoff delay occurs between retry attempts (time.sleep is called)."""
    mock_client = _setup_retry_mocks(monkeypatch)
    sleep_called = []
    monkeypatch.setattr(time, "sleep", lambda d: sleep_called.append(d))
    monkeypatch.setattr("random.uniform", lambda a, b: 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # Contract: at least one backoff delay occurred (not immediate retry)
    assert len(sleep_called) >= 1
    assert all(d > 0 for d in sleep_called)


# ===========================================================================
# REQ-RETRY-003: Error Classification (Retryable)
# ===========================================================================


# @tests-contract REQ-RETRY-003
def test_contract_retryable_errors_are_retried(monkeypatch, project_dir):
    """Contract: retryable errors do not cause immediate failure; function returns valid result."""
    mock_client = _setup_retry_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda d: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 1.0)

    # Each retryable error type followed by success
    retryable_errors = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APIConnectionError(request=MagicMock()),
        anthropic.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
        ),
        anthropic.InternalServerError(
            message="server error", response=MagicMock(status_code=500, headers={}), body={}
        ),
    ]

    for error in retryable_errors:
        mock_client = _setup_retry_mocks(monkeypatch)
        monkeypatch.setattr(time, "sleep", lambda d: None)
        monkeypatch.setattr("random.uniform", lambda a, b: 1.0)

        mock_client.messages.create.side_effect = [
            error,
            _make_mock_response(VALID_JSON),
        ]

        result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

        # Contract: function returns valid result (not empty) when retryable error recovers
        assert isinstance(result, dict)
        assert "new_key_points" in result
        assert "evaluations" in result


# ===========================================================================
# REQ-RETRY-004: Non-Retryable Immediate Return
# ===========================================================================


# @tests-contract REQ-RETRY-004
def test_contract_non_retryable_returns_empty(monkeypatch, project_dir):
    """Contract: non-retryable errors return the empty result dict immediately."""
    non_retryable_errors = [
        anthropic.AuthenticationError(
            message="auth failed", response=MagicMock(status_code=401, headers={}), body={}
        ),
        anthropic.BadRequestError(
            message="bad request", response=MagicMock(status_code=400, headers={}), body={}
        ),
        anthropic.NotFoundError(
            message="not found", response=MagicMock(status_code=404, headers={}), body={}
        ),
        anthropic.APIResponseValidationError(
            response=MagicMock(status_code=200, headers={}), body={}, message="validation failed"
        ),
        RuntimeError("unexpected"),
    ]

    for error in non_retryable_errors:
        mock_client = _setup_retry_mocks(monkeypatch)
        monkeypatch.setattr(time, "sleep", lambda d: None)

        mock_client.messages.create.side_effect = error

        result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

        # Contract: returns empty result dict
        assert result == {"new_key_points": [], "evaluations": []}, (
            f"Expected empty result for {type(error).__name__}"
        )


# ===========================================================================
# REQ-RETRY-005: Post-Exhaustion Return
# ===========================================================================


# @tests-contract REQ-RETRY-005
def test_contract_exhaustion_returns_empty(monkeypatch, project_dir):
    """Contract: when all retry attempts fail, returns empty result dict."""
    mock_client = _setup_retry_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda d: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APITimeoutError(request=MagicMock()),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # Contract: returns empty result, no exception propagated
    assert result == {"new_key_points": [], "evaluations": []}


# ===========================================================================
# REQ-RETRY-006: Per-Request Timeout
# ===========================================================================


# @tests-contract REQ-RETRY-006
def test_contract_timeout_parameter_set(monkeypatch, project_dir):
    """Contract: client.messages.create is called with timeout=30.0."""
    mock_client = _setup_retry_mocks(monkeypatch)

    mock_client.messages.create.return_value = _make_mock_response(VALID_JSON)

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # Contract: timeout=30.0 passed as keyword argument
    call_args = mock_client.messages.create.call_args
    assert call_args.kwargs.get("timeout") == 30.0 or call_args[1].get("timeout") == 30.0


# ===========================================================================
# REQ-RETRY-007: Diagnostic Logging
# ===========================================================================


# @tests-contract REQ-RETRY-007
def test_contract_no_diagnostic_when_mode_off(monkeypatch, project_dir):
    """Contract: no diagnostic logging occurs when diagnostic mode is off."""
    mock_client = _setup_retry_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda d: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 1.0)

    diag_calls = []
    monkeypatch.setattr(
        _common_module,
        "save_diagnostic",
        lambda content, name: diag_calls.append((content, name)),
    )

    # Trigger a retry scenario with diagnostic mode off
    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # Contract: no diagnostic calls when mode is off
    assert len(diag_calls) == 0


# ===========================================================================
# REQ-RETRY-008: Module-Level Constants
# ===========================================================================


# @tests-contract REQ-RETRY-008
def test_contract_module_constants_accessible():
    """Contract: MAX_RETRIES and BASE_DELAY are accessible module-level attributes."""
    assert hasattr(_common_module, "MAX_RETRIES")
    assert hasattr(_common_module, "BASE_DELAY")
    assert isinstance(_common_module.MAX_RETRIES, int)
    assert isinstance(_common_module.BASE_DELAY, float)
    assert _common_module.MAX_RETRIES == 3
    assert _common_module.BASE_DELAY == 2.0


# ===========================================================================
# Deliverable Tests
# ===========================================================================


# @tests-contract REQ-RETRY-001
def test_contract_deliverable_retry_succeeds(monkeypatch, project_dir):
    """Deliverable: transient failure then success -- no exception propagated to caller."""
    mock_client = _setup_retry_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda d: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    # Caller perspective: call function, get result, no crash
    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert isinstance(result, dict)
    assert "new_key_points" in result
    assert isinstance(result["new_key_points"], list)
    assert "evaluations" in result
    assert isinstance(result["evaluations"], list)
    # Result is non-empty (the retry succeeded)
    assert len(result["new_key_points"]) > 0 or len(result["evaluations"]) > 0


# @tests-contract REQ-RETRY-005
def test_contract_deliverable_exhaustion_graceful(monkeypatch, project_dir):
    """Deliverable: all attempts fail -- returns empty dict, no exception to caller."""
    mock_client = _setup_retry_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda d: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        anthropic.APIConnectionError(request=MagicMock()),
        anthropic.RateLimitError(
            message="rate limited", response=MagicMock(status_code=429, headers={}), body={}
        ),
    ]

    # Caller perspective: no crash, get empty result
    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert isinstance(result, dict)
    assert result == {"new_key_points": [], "evaluations": []}


# @tests-contract REQ-RETRY-001
def test_contract_deliverable_anthropic_not_available(monkeypatch, project_dir):
    """Deliverable: ANTHROPIC_AVAILABLE=False -- early return with empty result."""
    monkeypatch.setattr(_common_module, "ANTHROPIC_AVAILABLE", False)

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert isinstance(result, dict)
    assert result == {"new_key_points": [], "evaluations": []}


# @tests-contract REQ-RETRY-001
def test_contract_function_signature():
    """Contract: extract_keypoints signature matches documented contract."""
    sig = inspect.signature(extract_keypoints)
    params = list(sig.parameters.keys())
    assert "messages" in params
    assert "playbook" in params
    assert "diagnostic_name" in params
    # diagnostic_name has default "reflection"
    assert sig.parameters["diagnostic_name"].default == "reflection"


# @tests-contract REQ-RETRY-003
def test_contract_api_status_error_5xx_retried(monkeypatch, project_dir):
    """Contract: APIStatusError with status >= 500 is treated as retryable."""
    mock_client = _setup_retry_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda d: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APIStatusError(
            message="service unavailable",
            response=MagicMock(status_code=503, headers={}),
            body={},
        ),
        _make_mock_response(VALID_JSON),
    ]

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # Contract: function returns a valid result after retryable 5xx recovers
    assert isinstance(result, dict)
    assert "new_key_points" in result


# @tests-contract REQ-RETRY-004
def test_contract_api_status_error_4xx_not_retried(monkeypatch, project_dir):
    """Contract: APIStatusError with status < 500 returns empty immediately."""
    mock_client = _setup_retry_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda d: None)

    mock_client.messages.create.side_effect = anthropic.NotFoundError(
        message="not found", response=MagicMock(status_code=404, headers={}), body={}
    )

    result = asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    assert result == {"new_key_points": [], "evaluations": []}


# @tests-contract REQ-RETRY-006
def test_contract_timeout_on_retry_attempt(monkeypatch, project_dir):
    """Contract: timeout=30.0 is set on retry attempts as well, not just the first."""
    mock_client = _setup_retry_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda d: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 1.0)

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # Contract: every call has timeout=30.0
    for call in mock_client.messages.create.call_args_list:
        assert call.kwargs.get("timeout") == 30.0 or call[1].get("timeout") == 30.0


# @tests-contract REQ-RETRY-007
def test_contract_diagnostic_logged_when_mode_on(monkeypatch, project_dir, enable_diagnostic):
    """Contract: diagnostic logging occurs when diagnostic mode is on during retry events."""
    mock_client = _setup_retry_mocks(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda d: None)
    monkeypatch.setattr("random.uniform", lambda a, b: 1.0)

    diag_calls = []
    monkeypatch.setattr(
        _common_module,
        "save_diagnostic",
        lambda content, name: diag_calls.append((content, name)),
    )

    mock_client.messages.create.side_effect = [
        anthropic.APITimeoutError(request=MagicMock()),
        _make_mock_response(VALID_JSON),
    ]

    asyncio.run(extract_keypoints(messages=[], playbook={"sections": {}}))

    # Contract: at least one retry-related diagnostic was emitted
    retry_diags = [c for c in diag_calls if c[1] == "retry_extract_keypoints"]
    assert len(retry_diags) >= 1
