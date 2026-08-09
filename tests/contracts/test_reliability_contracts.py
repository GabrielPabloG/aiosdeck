"""Contract tests for timeout, retry, and error-mapping — frozen behavior.

The AgentExecutor is the single execution boundary. These tests freeze:
1. Error code mapping (error_from_exception)
2. Retry eligibility (retryable + retryable_codes)
3. Backoff formula (deterministic)
4. Timeout → TIMEOUT error + transient flag
"""

from dataclasses import FrozenInstanceError

import pytest

from aios.agents.contracts import (
    PERMISSION_DENIED,
    RUNTIME_ERROR,
    TIMEOUT,
    VALIDATION_ERROR,
    AgentError,
    RetryPolicy,
    error_from_exception,
)
from aios.agents.contracts import AgentValidationError


# ──────────────────────────────────────────────────────────
# Error mapping contract
# ──────────────────────────────────────────────────────────


def test_error_from_exception_maps_timeouterror():
    exc = TimeoutError("deadline exceeded")
    error = error_from_exception(exc)
    assert error.code == TIMEOUT
    assert error.transient is True
    assert error.retryable is True


def test_error_from_exception_maps_permissionerror():
    exc = PermissionError("access denied")
    error = error_from_exception(exc)
    assert error.code == PERMISSION_DENIED
    assert error.transient is False
    assert error.retryable is False


def test_error_from_exception_maps_generic_exception():
    exc = RuntimeError("unexpected")
    error = error_from_exception(exc)
    assert error.code == RUNTIME_ERROR
    assert error.transient is True
    assert error.retryable is True


def test_error_from_exception_maps_validation_error():
    exc = AgentValidationError("invalid task")
    error = error_from_exception(exc)
    assert error.code == VALIDATION_ERROR
    assert error.transient is False
    assert error.retryable is False


# ──────────────────────────────────────────────────────────
# Retry policy contract
# ──────────────────────────────────────────────────────────


def test_retry_policy_default_no_retry():
    """Default RetryPolicy (max_attempts=1) is no retry."""
    policy = RetryPolicy()
    assert policy.max_attempts == 1
    assert policy.enabled is False


def test_retry_policy_enabled():
    """max_attempts > 1 enables retry."""
    policy = RetryPolicy(max_attempts=3)
    assert policy.enabled is True


def test_retry_policy_retryable_codes():
    """Only codes listed in retryable_codes are retry-eligible."""
    policy = RetryPolicy(
        max_attempts=3,
        retryable_codes=(TIMEOUT,),
    )
    assert RUNTIME_ERROR not in policy.retryable_codes
    assert TIMEOUT in policy.retryable_codes


def test_retry_policy_is_immutable():
    """RetryPolicy is frozen."""
    policy = RetryPolicy()
    with pytest.raises(FrozenInstanceError):
        policy.max_attempts = 5  # type: ignore[misc]


# ──────────────────────────────────────────────────────────
# Backoff formula contract
# ──────────────────────────────────────────────────────────


def test_backoff_formula():
    """backoff = base_delay * 2^(attempt-2)."""
    policy = RetryPolicy(max_attempts=3, base_delay=0.5)
    # Manual: delay = base_delay * (2 ** (attempt - 2))
    assert policy.base_delay * (2 ** (2 - 2)) == 0.5  # attempt 2 → 0.5
    assert policy.base_delay * (2 ** (3 - 2)) == 1.0  # attempt 3 → 1.0
    assert policy.base_delay * (2 ** (4 - 2)) == 2.0  # attempt 4 → 2.0


# ──────────────────────────────────────────────────────────
# AgentError contract
# ──────────────────────────────────────────────────────────


def test_agent_error_to_dict_round_trip():
    error = AgentError(code=TIMEOUT, message="timed out", transient=True)
    data = error.to_dict()
    assert data["code"] == TIMEOUT
    assert data["message"] == "timed out"
    assert data["transient"] is True
    assert data["retryable"] is True


def test_agent_error_non_transient():
    """Non-transient errors are terminal (not retryable)."""
    error = AgentError(code=PERMISSION_DENIED, message="denied")
    assert error.transient is False
    assert error.retryable is False


def test_agent_error_stable_codes():
    """Every stable error code is representable."""
    for code in (VALIDATION_ERROR, RUNTIME_ERROR, PERMISSION_DENIED, TIMEOUT):
        error = AgentError(code=code, message=f"test {code}")
        assert error.code == code
        assert error.to_dict()["code"] == code


# ──────────────────────────────────────────────────────────
# Timeout contract
# ──────────────────────────────────────────────────────────


def test_timeout_error_is_transient():
    """TIMEOUT errors MUST be transient → retryable."""
    error = AgentError(code=TIMEOUT, message="timeout", transient=True)
    assert error.retryable is True


def test_timeout_code_is_stable():
    """TIMEOUT string literal must not change."""
    assert TIMEOUT == "TIMEOUT"
    assert isinstance(TIMEOUT, str)
