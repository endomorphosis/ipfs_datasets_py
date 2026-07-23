"""Execution utilities for unified search plans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from .planner import SearchExecutionPlan
from .resilience import CircuitBreakerRegistry, RetryPolicy, execute_with_retry

try:
    from ..search_engines.base import SearchEngineQuotaExceededError, SearchEngineRateLimitError
except Exception:  # pragma: no cover - keeps executor decoupled from optional adapters
    SearchEngineQuotaExceededError = None  # type: ignore[assignment]
    SearchEngineRateLimitError = None  # type: ignore[assignment]


@dataclass
class SearchExecutionResult:
    """Normalized outcome of executing a search plan."""

    raw_response: Any
    providers_attempted: List[str]
    providers_skipped: List[str]
    provider_selected: Optional[str]
    fallback_count: int
    retry_attempts: int


class SearchExecutor:
    """Execute search plans via the existing multi-engine orchestrator."""

    def __init__(
        self,
        orchestrator: Any,
        *,
        circuit_breaker: Optional[CircuitBreakerRegistry] = None,
        retry_policy: Optional[RetryPolicy] = None,
    ):
        self.orchestrator = orchestrator
        self.circuit_breaker = circuit_breaker or CircuitBreakerRegistry()
        self.retry_policy = retry_policy or RetryPolicy()

    def execute(self, plan: SearchExecutionPlan) -> SearchExecutionResult:
        """Execute a ranked provider plan and normalize attempt metadata."""
        attempted: List[str] = []
        skipped: List[str] = []
        retry_attempts = 0
        errors: List[str] = []

        for provider in plan.providers_ordered:
            breaker_key = f"{provider}:search"
            if not self.circuit_breaker.allow_request(breaker_key):
                skipped.append(provider)
                continue

            attempted.append(provider)

            try:
                raw_response = execute_with_retry(
                    lambda: self.orchestrator.search(
                        query=plan.query,
                        max_results=plan.max_results,
                        offset=plan.offset,
                        engines=[provider],
                    ),
                    policy=self.retry_policy,
                    is_retryable=self._is_retryable_error,
                )

                providers_used = list(getattr(raw_response, "metadata", {}).get("engines_used", []) or [])
                if not providers_used:
                    providers_used = [provider]

                self.circuit_breaker.record_success(breaker_key)
                selected = providers_used[0] if providers_used else provider
                fallback_count = max(0, len(attempted) - 1)

                return SearchExecutionResult(
                    raw_response=raw_response,
                    providers_attempted=attempted,
                    providers_skipped=skipped,
                    provider_selected=selected,
                    fallback_count=fallback_count,
                    retry_attempts=retry_attempts,
                )

            except Exception as exc:
                self.circuit_breaker.record_failure(breaker_key)
                errors.append(f"{provider}: {exc}")
                retry_attempts += max(0, self.retry_policy.max_attempts - 1)

        if skipped and not attempted:
            raise RuntimeError(
                "All providers skipped by circuit breaker",
            )

        if errors:
            raise RuntimeError("All providers failed: " + " | ".join(errors))

        raise RuntimeError("No providers available for execution")

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        if SearchEngineRateLimitError is not None and isinstance(exc, SearchEngineRateLimitError):
            return False
        if SearchEngineQuotaExceededError is not None and isinstance(exc, SearchEngineQuotaExceededError):
            return False
        message = str(exc or "").lower()
        if "rate limit" in message or "rate-limited" in message or "too many requests" in message:
            return False
        if "quota" in message or "http 429" in message or "status code 429" in message:
            return False
        return True


__all__ = [
    "SearchExecutionResult",
    "SearchExecutor",
]
