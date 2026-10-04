"""Cooperative deadline and cancellation scope for a complete proof operation.

Native transports consume the remaining deadline. Python callbacks are checked
at call boundaries and are not forcibly preempted. An observed interruption is
latched, including through nested scopes, so clearing a cancellation event cannot
make a late result admissible.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import math
import time

from ..process import _is_cancelled

MAX_OPERATION_TIMEOUT_MS = 2**31 - 1


class ProofOperationInterrupted(RuntimeError):
    """A complete proof operation stopped without returning conclusive evidence."""

    def __init__(self, *, kind: str, phase: str, elapsed_ms: int, timeout_ms: int):
        self.kind = kind
        self.phase = phase
        self.elapsed_ms = elapsed_ms
        self.timeout_ms = timeout_ms
        super().__init__(f"proof operation {kind} during {phase}")

    def to_dict(self):
        return {"kind": self.kind, "phase": self.phase,
                "elapsed_ms": self.elapsed_ms, "timeout_ms": self.timeout_ms}

    def __reduce__(self):
        # Process-pool futures must be able to deliver this typed failure to
        # their caller without rerunning a keyword-only exception constructor.
        return (_restore_interruption, (type(self), self.to_dict(), self.args))


class ProofOperationTimeout(ProofOperationInterrupted, TimeoutError):
    """The complete operation exhausted its monotonic wall-clock deadline."""


class ProofOperationCancelled(ProofOperationInterrupted):
    """The complete operation observed a cancellation signal."""


def _restore_interruption(error_type, details, arguments):
    error = error_type(**details)
    error.args = arguments
    return error


def validate_operation_timeout_ms(value):
    if value is not None and (type(value) is not int or not 0 < value <= MAX_OPERATION_TIMEOUT_MS):
        raise ValueError(f"operation_timeout_ms must be an integer in 1..{MAX_OPERATION_TIMEOUT_MS} or None")
    return value


class _Signals:
    def __init__(self, *signals):
        self.signals = tuple(signal for signal in signals if signal is not None)

    def is_set(self):
        return any(_is_cancelled(signal) for signal in self.signals)


class _ProofOperation:
    __slots__ = ("_started", "_deadline", "_timeout_ms", "_signal", "_parent", "_interruption")

    def __init__(self, timeout_ms, cancellation, parent):
        self._started = time.monotonic()
        own_deadline = self._started + timeout_ms / 1000
        if not math.isfinite(self._started) or not math.isfinite(own_deadline):
            raise ValueError("proof operation requires a finite monotonic deadline")
        self._deadline = min(own_deadline, parent.deadline) if parent is not None else own_deadline
        self._timeout_ms = timeout_ms
        self._signal = cancellation
        self._parent = parent
        self._interruption = None

    @property
    def deadline(self):
        return self._deadline

    def _latch(self, interruption):
        if self._interruption is None:
            self._interruption = interruption
        if self._parent is not None:
            self._parent._latch(self._interruption)

    def _observe(self, phase):
        if self._interruption is not None:
            return self._interruption
        if self._parent is not None:
            inherited = self._parent._observe(phase)
            if inherited is not None:
                self._latch(inherited)
                return self._interruption
        kind = "cancelled" if _is_cancelled(self._signal) else None
        if kind is None and time.monotonic() >= self._deadline:
            kind = "timeout"
        if kind is not None:
            error_type = ProofOperationCancelled if kind == "cancelled" else ProofOperationTimeout
            self._latch(error_type(kind=kind, phase=phase,
                elapsed_ms=max(0, int((time.monotonic() - self._started) * 1000)),
                timeout_ms=self._timeout_ms))
        return self._interruption

    def checkpoint(self, phase="operation boundary"):
        interruption = self._observe(phase)
        if interruption is not None:
            raise interruption
        return max(0.0, self._deadline - time.monotonic())

    def is_set(self):
        """Native polling observes and latches both cancellation and deadline."""
        return self._observe("native execution") is not None


_CURRENT_OPERATION = ContextVar("proof_operation_budget", default=None)


def current_proof_operation():
    return _CURRENT_OPERATION.get()


@contextmanager
def proof_operation_scope(*, timeout_ms: int, cancellation=None):
    """Start one bounded operation, inheriting any tighter parent scope.

    Timeout values are positive milliseconds up to 2**31-1. A stopped child also
    revokes its parent operation. No shared scheduler is consulted here. Normal
    and exceptional exits check the latched stop state; KeyboardInterrupt and
    other BaseExceptions propagate.
"""
    validate_operation_timeout_ms(timeout_ms)
    if timeout_ms is None:
        raise ValueError("timeout_ms must be a positive integer")
    operation = _ProofOperation(timeout_ms, cancellation, current_proof_operation())
    token = _CURRENT_OPERATION.set(operation)
    try:
        operation.checkpoint("operation entry")
        try:
            yield operation
        except Exception:
            operation.checkpoint("exception boundary")
            raise
        operation.checkpoint("operation return")
    finally:
        _CURRENT_OPERATION.reset(token)


__all__ = ["ProofOperationInterrupted", "ProofOperationTimeout", "ProofOperationCancelled",
           "proof_operation_scope", "current_proof_operation"]
