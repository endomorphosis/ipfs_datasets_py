"""Shared lifecycle hook mixin for optimizer session orchestration."""

from __future__ import annotations

from typing import Any, Dict, List


class LifecycleHooksMixin:
    """No-op lifecycle hooks used by BaseOptimizer.run_session.

    Subclasses can override any hook to add instrumentation, tracing, audit
    logging, or side effects around each pipeline stage.
    """

    def on_session_start(self, context: Any, input_data: Any) -> None:
        """Called once at the beginning of ``run_session``."""

    def on_generate_complete(self, artifact: Any, context: Any) -> None:
        """Called after ``generate`` returns."""

    def on_critique_complete(
        self, artifact: Any, score: float, feedback: List[str], context: Any
    ) -> None:
        """Called after each ``critique`` call (initial + iterative)."""

    def on_optimize_complete(
        self,
        artifact: Any,
        score: float,
        feedback: List[str],
        iteration: int,
        context: Any,
    ) -> None:
        """Called after each ``optimize`` call."""

    def on_validate_complete(self, artifact: Any, valid: bool, context: Any) -> None:
        """Called after ``validate`` when validation is enabled."""

    def on_session_complete(self, result: Dict[str, Any], context: Any) -> None:
        """Called once at the end of ``run_session``."""

