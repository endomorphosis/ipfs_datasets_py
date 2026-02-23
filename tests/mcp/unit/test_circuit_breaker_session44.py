"""Phase H44 — Integration: CircuitBreaker CLOSED → OPEN → HALF_OPEN lifecycle.

Covers lines 79-191 of hierarchical_tool_manager.py (CircuitBreaker class):
- CircuitBreaker.__init__ (lines 79-85)
- state property, OPEN → HALF_OPEN auto-transition (lines 92-106)
- is_open() (line 108-110)
- call() — OPEN rejection, async call, sync call, exception path (lines 112-146)
- reset() (lines 148-153)
- info() (lines 155-157)
- _on_success() HALF_OPEN → CLOSED (lines 170-177)
- _on_failure() → OPEN threshold (lines 179-191)

Test Format: GIVEN-WHEN-THEN
"""

import asyncio
import time
import pytest
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
    CircuitBreaker,
    CircuitState,
)
from ipfs_datasets_py.mcp_server.exceptions import ToolExecutionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cb(failure_threshold: int = 3, recovery_timeout: float = 60.0, name: str = "test") -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=failure_threshold, recovery_timeout=recovery_timeout, name=name)


async def _failing_async(**kwargs):
    raise RuntimeError("async failure")


def _failing_sync(**kwargs):
    raise RuntimeError("sync failure")


async def _ok_async(**kwargs) -> Dict[str, Any]:
    return {"status": "success", "source": "async"}


def _ok_sync(**kwargs) -> Dict[str, Any]:
    return {"status": "success", "source": "sync"}


# ---------------------------------------------------------------------------
# Tests: construction & basic state
# ---------------------------------------------------------------------------

class TestCircuitBreakerInit:
    """Verify that CircuitBreaker initialises correctly (lines 73-85)."""

    def test_defaults(self):
        """GIVEN no arguments
        WHEN CircuitBreaker() is called
        THEN state is CLOSED, counts are zero, name is 'default'.
        """
        cb = CircuitBreaker()
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60.0
        assert cb.name == "default"
        assert cb._state == CircuitState.CLOSED
        assert cb._failure_count == 0
        assert cb._opened_at is None

    def test_custom_params(self):
        """GIVEN custom threshold and timeout
        WHEN CircuitBreaker(failure_threshold=2, recovery_timeout=10, name='x') is called
        THEN attributes match the supplied values.
        """
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0, name="x")
        assert cb.failure_threshold == 2
        assert cb.recovery_timeout == 10.0
        assert cb.name == "x"


class TestCircuitBreakerStateProperty:
    """Verify state transitions via the state property (lines 92-106)."""

    def test_initial_state_is_closed(self):
        """GIVEN a fresh CircuitBreaker
        WHEN state is read
        THEN it returns CLOSED.
        """
        cb = _make_cb()
        assert cb.state == CircuitState.CLOSED

    def test_open_state_returned_when_not_expired(self):
        """GIVEN a breaker in OPEN state whose recovery_timeout has not elapsed
        WHEN state is read
        THEN OPEN is returned (no transition yet).
        """
        cb = _make_cb(recovery_timeout=9999.0)
        cb._state = CircuitState.OPEN
        cb._opened_at = time.monotonic()  # just set to now — not expired
        assert cb.state == CircuitState.OPEN

    def test_open_transitions_to_half_open_after_timeout(self):
        """GIVEN a breaker in OPEN state whose recovery window has passed
        WHEN state is read
        THEN it auto-transitions to HALF_OPEN.
        """
        cb = _make_cb(recovery_timeout=1.0)
        cb._state = CircuitState.OPEN
        # Simulate that the breaker was opened 5 seconds ago
        cb._opened_at = time.monotonic() - 5.0
        result = cb.state
        assert result == CircuitState.HALF_OPEN
        assert cb._state == CircuitState.HALF_OPEN

    def test_half_open_stays_half_open_when_read(self):
        """GIVEN a breaker already in HALF_OPEN
        WHEN state is read
        THEN HALF_OPEN is returned (not further changed).
        """
        cb = _make_cb()
        cb._state = CircuitState.HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN


class TestCircuitBreakerIsOpen:
    """Verify is_open() helper (lines 108-110)."""

    def test_is_open_false_when_closed(self):
        cb = _make_cb()
        assert cb.is_open() is False

    def test_is_open_true_when_open(self):
        cb = _make_cb(recovery_timeout=9999.0)
        cb._state = CircuitState.OPEN
        cb._opened_at = time.monotonic()
        assert cb.is_open() is True

    def test_is_open_false_when_half_open(self):
        cb = _make_cb()
        cb._state = CircuitState.HALF_OPEN
        assert cb.is_open() is False


# ---------------------------------------------------------------------------
# Tests: call() method
# ---------------------------------------------------------------------------

class TestCircuitBreakerCall:
    """Verify CircuitBreaker.call() for all branches (lines 112-146)."""

    @pytest.mark.asyncio
    async def test_call_async_func_success(self):
        """GIVEN a CLOSED breaker and an async function that succeeds
        WHEN call() is invoked
        THEN the result is returned and state remains CLOSED.
        """
        cb = _make_cb()
        result = await cb.call(_ok_async)
        assert result["status"] == "success"
        assert cb._state == CircuitState.CLOSED
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_call_sync_func_success(self):
        """GIVEN a CLOSED breaker and a sync function that succeeds
        WHEN call() is invoked
        THEN the result is returned and state remains CLOSED.
        """
        cb = _make_cb()
        result = await cb.call(_ok_sync)
        assert result["status"] == "success"
        assert cb._state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_call_open_circuit_returns_error_dict(self):
        """GIVEN a breaker in OPEN state (recovery not elapsed)
        WHEN call() is invoked
        THEN an error dict is returned without calling the function.
        """
        cb = _make_cb(recovery_timeout=9999.0)
        cb._state = CircuitState.OPEN
        cb._opened_at = time.monotonic()

        called = []
        async def probe(**kw):
            called.append(1)
            return {"status": "success"}

        result = await cb.call(probe)
        assert result["status"] == "error"
        # circuit_state key is set to CircuitState.OPEN ("open") in the rejection dict
        assert result.get("circuit_state") == CircuitState.OPEN
        assert called == []  # function was NOT invoked

    @pytest.mark.asyncio
    async def test_call_async_func_failure_increments_count(self):
        """GIVEN a CLOSED breaker with threshold=5
        WHEN call() is invoked with a function that raises
        THEN failure_count increments and ToolExecutionError is raised.
        """
        cb = _make_cb(failure_threshold=5)
        with pytest.raises(ToolExecutionError):
            await cb.call(_failing_async)
        assert cb._failure_count == 1
        assert cb._state == CircuitState.CLOSED  # threshold not yet reached

    @pytest.mark.asyncio
    async def test_call_sync_func_failure_raises_tool_execution_error(self):
        """GIVEN a CLOSED breaker
        WHEN call() wraps a sync function that raises
        THEN ToolExecutionError is raised.
        """
        cb = _make_cb(failure_threshold=5)
        with pytest.raises(ToolExecutionError):
            await cb.call(_failing_sync)

    @pytest.mark.asyncio
    async def test_call_keyboard_interrupt_propagates(self):
        """GIVEN a function that raises KeyboardInterrupt
        WHEN call() is invoked
        THEN KeyboardInterrupt propagates without wrapping.
        """
        def ki_raiser():
            raise KeyboardInterrupt

        cb = _make_cb()
        with pytest.raises(KeyboardInterrupt):
            await cb.call(ki_raiser)

    @pytest.mark.asyncio
    async def test_call_system_exit_propagates(self):
        """GIVEN a function that raises SystemExit
        WHEN call() is invoked
        THEN SystemExit propagates without wrapping.
        """
        def se_raiser():
            raise SystemExit(0)

        cb = _make_cb()
        with pytest.raises(SystemExit):
            await cb.call(se_raiser)


# ---------------------------------------------------------------------------
# Tests: CLOSED → OPEN lifecycle
# ---------------------------------------------------------------------------

class TestCircuitBreakerClosedToOpen:
    """Verify that enough failures open the circuit (lines 179-191)."""

    @pytest.mark.asyncio
    async def test_reaches_open_after_threshold_failures(self):
        """GIVEN a breaker with failure_threshold=3
        WHEN 3 failures occur
        THEN state transitions to OPEN and opened_at is set.
        """
        cb = _make_cb(failure_threshold=3)
        for _ in range(3):
            try:
                await cb.call(_failing_async)
            except ToolExecutionError:
                pass
        assert cb._state == CircuitState.OPEN
        assert cb._opened_at is not None

    @pytest.mark.asyncio
    async def test_stays_closed_before_threshold(self):
        """GIVEN a breaker with failure_threshold=4
        WHEN only 3 failures occur
        THEN state stays CLOSED.
        """
        cb = _make_cb(failure_threshold=4)
        for _ in range(3):
            try:
                await cb.call(_failing_async)
            except ToolExecutionError:
                pass
        assert cb._state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_count_resets_after_success(self):
        """GIVEN a breaker that had some failures but not enough to open
        WHEN a successful call is made
        THEN failure count resets to zero.
        """
        cb = _make_cb(failure_threshold=5)
        for _ in range(2):
            try:
                await cb.call(_failing_async)
            except ToolExecutionError:
                pass
        assert cb._failure_count == 2

        # Now a success
        await cb.call(_ok_async)
        assert cb._failure_count == 0
        assert cb._state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Tests: OPEN → HALF_OPEN → CLOSED / OPEN recovery
# ---------------------------------------------------------------------------

class TestCircuitBreakerRecovery:
    """Verify the OPEN → HALF_OPEN → CLOSED / OPEN lifecycle."""

    @pytest.mark.asyncio
    async def test_half_open_success_closes_circuit(self):
        """GIVEN a breaker in HALF_OPEN state
        WHEN a successful call is made via call()
        THEN state transitions to CLOSED and failure count resets.
        """
        cb = _make_cb()
        cb._state = CircuitState.HALF_OPEN

        result = await cb.call(_ok_async)
        assert result["status"] == "success"
        assert cb._state == CircuitState.CLOSED
        assert cb._failure_count == 0
        assert cb._opened_at is None

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self):
        """GIVEN a breaker in HALF_OPEN state
        WHEN the probe call fails
        THEN state transitions back to OPEN and opened_at is refreshed.
        """
        cb = _make_cb()
        cb._state = CircuitState.HALF_OPEN

        with pytest.raises(ToolExecutionError):
            await cb.call(_failing_async)

        assert cb._state == CircuitState.OPEN
        assert cb._opened_at is not None

    @pytest.mark.asyncio
    async def test_open_rejects_then_auto_transitions_to_half_open(self):
        """GIVEN a breaker that opened 5 seconds ago (recovery_timeout=1s)
        WHEN state is read
        THEN it is HALF_OPEN and the next call is allowed through.
        """
        cb = _make_cb(failure_threshold=2, recovery_timeout=1.0)
        cb._state = CircuitState.OPEN
        cb._opened_at = time.monotonic() - 2.0  # 2 seconds ago > 1s recovery

        assert cb.state == CircuitState.HALF_OPEN
        result = await cb.call(_ok_async)
        assert result["status"] == "success"
        assert cb._state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Tests: reset() and info()
# ---------------------------------------------------------------------------

class TestCircuitBreakerResetAndInfo:
    """Verify reset() and info() helpers (lines 148-164)."""

    def test_reset_returns_to_closed(self):
        """GIVEN a breaker in OPEN state
        WHEN reset() is called
        THEN state is CLOSED, failure count is 0, opened_at is None.
        """
        cb = _make_cb()
        cb._state = CircuitState.OPEN
        cb._failure_count = 7
        cb._opened_at = time.monotonic()

        cb.reset()

        assert cb._state == CircuitState.CLOSED
        assert cb._failure_count == 0
        assert cb._opened_at is None

    def test_info_returns_snapshot(self):
        """GIVEN a breaker in OPEN state with known values
        WHEN info() is called
        THEN the returned dict matches the breaker's attributes.
        """
        cb = CircuitBreaker(failure_threshold=4, recovery_timeout=30.0, name="svc")
        cb._state = CircuitState.OPEN
        cb._failure_count = 4
        ts = time.monotonic()
        cb._opened_at = ts

        info = cb.info()

        assert info["name"] == "svc"
        assert info["state"] == CircuitState.OPEN
        assert info["failure_count"] == 4
        assert info["failure_threshold"] == 4
        assert info["recovery_timeout"] == 30.0
        assert info["opened_at"] == ts

    def test_info_closed_circuit(self):
        """GIVEN a fresh (CLOSED) breaker
        WHEN info() is called
        THEN state is CLOSED and opened_at is None.
        """
        cb = _make_cb(name="closed-svc")
        info = cb.info()
        assert info["state"] == CircuitState.CLOSED
        assert info["opened_at"] is None
        assert info["failure_count"] == 0


# ---------------------------------------------------------------------------
# Tests: full CLOSED → OPEN → HALF_OPEN → CLOSED scenario
# ---------------------------------------------------------------------------

class TestCircuitBreakerFullLifecycle:
    """End-to-end state machine walk-through (all major transitions)."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """GIVEN a breaker with threshold=2 and short recovery_timeout
        WHEN a sequence of failures, waits, and successes occurs
        THEN state follows the CLOSED → OPEN → HALF_OPEN → CLOSED path.
        """
        cb = _make_cb(failure_threshold=2, recovery_timeout=0.05)

        # Step 1: CLOSED — two failures open the circuit
        for _ in range(2):
            with pytest.raises(ToolExecutionError):
                await cb.call(_failing_async)
        assert cb.state == CircuitState.OPEN

        # Step 2: while OPEN, a call is rejected immediately
        result = await cb.call(_ok_async)
        assert result["status"] == "error"

        # Step 3: wait for recovery window then check state → HALF_OPEN
        await asyncio.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN

        # Step 4: successful probe in HALF_OPEN → CLOSED
        result = await cb.call(_ok_async)
        assert result["status"] == "success"
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_full_lifecycle_probe_fails(self):
        """GIVEN a breaker opened after failures
        WHEN the recovery probe also fails
        THEN it returns to OPEN.
        """
        cb = _make_cb(failure_threshold=1, recovery_timeout=0.05)

        # CLOSED → OPEN
        with pytest.raises(ToolExecutionError):
            await cb.call(_failing_async)
        assert cb.state == CircuitState.OPEN

        # Wait → HALF_OPEN
        await asyncio.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN

        # Probe fails → back to OPEN
        with pytest.raises(ToolExecutionError):
            await cb.call(_failing_async)
        assert cb._state == CircuitState.OPEN
