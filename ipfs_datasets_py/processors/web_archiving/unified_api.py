"""Unified web archiving API facade.

This module provides a single high-level API for multi-provider search and fetch
workflows. The initial implementation focuses on unified search backed by the
existing multi-engine search orchestrator.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Union

from .contracts import (
    ErrorSeverity,
    ExecutionTrace,
    OperationMode,
    UnifiedDocument,
    UnifiedError,
    UnifiedFetchRequest,
    UnifiedFetchResponse,
    UnifiedSearchHit,
    UnifiedSearchRequest,
    UnifiedSearchResponse,
)
from .metrics.registry import MetricsRegistry
from .orchestration.executor import SearchExecutor
from .orchestration.planner import SearchPlanner
from .orchestration.scoring import ProviderScorer
from .search_engines.orchestrator import MultiEngineOrchestrator, OrchestratorConfig


DEFAULT_SEARCH_ENGINES = ["brave", "duckduckgo", "google_cse"]


@dataclass
class UnifiedAPIConfig:
    """Configuration for the UnifiedWebArchivingAPI facade."""

    default_search_engines: List[str]
    orchestrator_timeout_seconds: int = 30
    parallel_enabled: bool = True
    fallback_enabled: bool = True


class UnifiedWebArchivingAPI:
    """Unified facade for web archiving search and retrieval workflows."""

    def __init__(
        self,
        orchestrator: Optional[MultiEngineOrchestrator] = None,
        metrics_registry: Optional[MetricsRegistry] = None,
        config: Optional[UnifiedAPIConfig] = None,
        scorer: Optional[ProviderScorer] = None,
        search_planner: Optional[SearchPlanner] = None,
        search_executor: Optional[SearchExecutor] = None,
        scraper: Optional[Any] = None,
    ):
        self.config = config or UnifiedAPIConfig(default_search_engines=list(DEFAULT_SEARCH_ENGINES))
        self.metrics_registry = metrics_registry or MetricsRegistry()
        self.orchestrator = orchestrator or self._build_orchestrator()
        self.scorer = scorer or ProviderScorer(metrics_registry=self.metrics_registry)
        self.search_planner = search_planner or SearchPlanner(
            scorer=self.scorer,
            default_search_engines=self.config.default_search_engines,
        )
        self.search_executor = search_executor or SearchExecutor(orchestrator=self.orchestrator)
        self.scraper = scraper

    def _build_orchestrator(self) -> MultiEngineOrchestrator:
        orchestrator_config = OrchestratorConfig(
            engines=list(self.config.default_search_engines),
            parallel_enabled=bool(self.config.parallel_enabled),
            fallback_enabled=bool(self.config.fallback_enabled),
            timeout_seconds=int(self.config.orchestrator_timeout_seconds),
        )
        return MultiEngineOrchestrator(orchestrator_config)

    def search(
        self,
        request: Union[UnifiedSearchRequest, str],
        **kwargs: Any,
    ) -> UnifiedSearchResponse:
        """Execute a unified search request.

        Args:
            request: UnifiedSearchRequest object or query string.
            **kwargs: Optional request fields when request is a query string.

        Returns:
            UnifiedSearchResponse with normalized hits and execution trace.
        """
        if isinstance(request, str):
            search_request = UnifiedSearchRequest(query=request, **kwargs)
        else:
            search_request = request

        start_time = time.time()
        request_id = str(uuid.uuid4())
        plan = self.search_planner.plan(search_request)

        trace = ExecutionTrace(
            request_id=request_id,
            operation="search",
            mode=search_request.mode,
            providers_attempted=list(plan.providers_ordered),
            provider_selected=None,
            fallback_count=0,
            total_latency_ms=0.0,
            retries=0,
        )

        try:
            execution = self.search_executor.execute(plan)
            raw_response = execution.raw_response

            hits = [self._to_unified_hit(item) for item in raw_response.results]
            providers_used = execution.providers_attempted
            trace.providers_attempted = providers_used
            trace.provider_selected = execution.provider_selected or self._choose_selected_provider(providers_used, hits)
            trace.fallback_count = execution.fallback_count
            trace.total_latency_ms = float(raw_response.took_ms)
            trace.finished_at = datetime.utcnow().isoformat()

            response = UnifiedSearchResponse(
                query=search_request.query,
                results=hits,
                trace=trace,
                errors=[],
                total_results=len(hits),
                success=True,
                metadata={
                    "engines_used": trace.providers_attempted,
                    "requested_mode": search_request.mode.value,
                    "planned_provider_order": list(plan.providers_ordered),
                    "provider_scores": [
                        {
                            "provider": score.provider,
                            "score": score.score,
                            "components": score.components,
                        }
                        for score in plan.provider_scores
                    ],
                },
            )

            self.metrics_registry.record_event(
                provider=trace.provider_selected or "multi_engine",
                operation="search",
                success=True,
                latency_ms=trace.total_latency_ms,
                items_processed=len(hits),
            )
            return response

        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000.0
            trace.total_latency_ms = elapsed_ms
            trace.finished_at = datetime.utcnow().isoformat()
            trace.provider_selected = trace.provider_selected or (
                trace.providers_attempted[0] if trace.providers_attempted else None
            )
            trace.fallback_count = max(0, len(trace.providers_attempted) - 1)

            error = UnifiedError(
                code="search_failed",
                message=str(exc),
                provider=trace.provider_selected,
                retryable=True,
                severity=ErrorSeverity.ERROR,
                context={"request_id": request_id},
            )

            self.metrics_registry.record_event(
                provider=trace.provider_selected or "multi_engine",
                operation="search",
                success=False,
                latency_ms=elapsed_ms,
                items_processed=0,
                error_type=type(exc).__name__,
            )

            return UnifiedSearchResponse(
                query=search_request.query,
                results=[],
                trace=trace,
                errors=[error],
                total_results=0,
                success=False,
                metadata={
                    "engines_used": trace.providers_attempted,
                    "requested_mode": search_request.mode.value,
                    "planned_provider_order": list(plan.providers_ordered),
                },
            )

    def health(self) -> Dict[str, Any]:
        """Return orchestrator and metrics health snapshot."""
        stats = {}
        try:
            stats = self.orchestrator.get_stats()
        except Exception as exc:
            stats = {"status": "error", "error": str(exc)}

        metrics_summary = {}
        for provider, operation in self.metrics_registry.provider_operation_keys():
            key = f"{provider}:{operation}"
            metrics_summary[key] = self.metrics_registry.snapshot(
                provider=provider,
                operation=operation,
                window_seconds=300,
            )

        return {
            "orchestrator": stats,
            "metrics_5m": metrics_summary,
        }

    def fetch(
        self,
        request: Union[UnifiedFetchRequest, str],
        **kwargs: Any,
    ) -> UnifiedFetchResponse:
        """Execute a unified fetch request via the configured scraper backend."""
        if isinstance(request, str):
            fetch_request = UnifiedFetchRequest(url=request, **kwargs)
        else:
            fetch_request = request

        start_time = time.time()
        request_id = str(uuid.uuid4())
        provider = "unified_scraper"
        trace = ExecutionTrace(
            request_id=request_id,
            operation="fetch",
            mode=fetch_request.mode,
            providers_attempted=[provider],
            provider_selected=provider,
            fallback_count=0,
            total_latency_ms=0.0,
            retries=0,
        )

        try:
            scraper = self._get_scraper()
            scraper_result = scraper.scrape_sync(fetch_request.url)
            trace.total_latency_ms = (time.time() - start_time) * 1000.0
            trace.finished_at = datetime.utcnow().isoformat()

            if not getattr(scraper_result, "success", False):
                errors = [
                    UnifiedError(
                        code="fetch_failed",
                        message="; ".join(getattr(scraper_result, "errors", []) or ["fetch failed"]),
                        provider=provider,
                        retryable=True,
                        severity=ErrorSeverity.ERROR,
                        context={"request_id": request_id},
                    )
                ]
                self.metrics_registry.record_event(
                    provider=provider,
                    operation="fetch",
                    success=False,
                    latency_ms=trace.total_latency_ms,
                    items_processed=0,
                    error_type="scrape_failed",
                )
                return UnifiedFetchResponse(
                    url=fetch_request.url,
                    document=None,
                    trace=trace,
                    errors=errors,
                    success=False,
                    quality_score=0.0,
                    metadata={"requested_mode": fetch_request.mode.value},
                )

            text = getattr(scraper_result, "text", "") or ""
            html = getattr(scraper_result, "html", "") or ""
            quality_score = 1.0 if text else (0.4 if html else 0.0)
            doc = UnifiedDocument(
                url=fetch_request.url,
                title=getattr(scraper_result, "title", "") or "",
                text=text,
                html=html,
                content_type=(getattr(scraper_result, "metadata", {}) or {}).get("content_type", ""),
                metadata=getattr(scraper_result, "metadata", {}) or {},
                extraction_provenance={
                    "method": getattr(getattr(scraper_result, "method_used", None), "value", None),
                    "extraction_time": getattr(scraper_result, "extraction_time", 0.0),
                },
            )

            self.metrics_registry.record_event(
                provider=provider,
                operation="fetch",
                success=True,
                latency_ms=trace.total_latency_ms,
                items_processed=1,
                quality_score=quality_score,
            )
            return UnifiedFetchResponse(
                url=fetch_request.url,
                document=doc,
                trace=trace,
                errors=[],
                success=True,
                quality_score=quality_score,
                metadata={"requested_mode": fetch_request.mode.value},
            )

        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000.0
            trace.total_latency_ms = elapsed_ms
            trace.finished_at = datetime.utcnow().isoformat()
            self.metrics_registry.record_event(
                provider=provider,
                operation="fetch",
                success=False,
                latency_ms=elapsed_ms,
                items_processed=0,
                error_type=type(exc).__name__,
            )
            return UnifiedFetchResponse(
                url=fetch_request.url,
                document=None,
                trace=trace,
                errors=[
                    UnifiedError(
                        code="fetch_exception",
                        message=str(exc),
                        provider=provider,
                        retryable=True,
                        severity=ErrorSeverity.ERROR,
                        context={"request_id": request_id},
                    )
                ],
                success=False,
                quality_score=0.0,
                metadata={"requested_mode": fetch_request.mode.value},
            )

    def search_and_fetch(
        self,
        request: Union[UnifiedSearchRequest, str],
        *,
        max_documents: int = 5,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Run unified search then fetch top results.

        Returns a simple envelope that includes the search response and fetch
        responses to keep MCP integration straightforward.
        """
        search_response = self.search(request, **kwargs)
        documents: List[UnifiedFetchResponse] = []

        if search_response.success:
            for hit in search_response.results[: max(0, int(max_documents))]:
                documents.append(
                    self.fetch(
                        UnifiedFetchRequest(
                            url=hit.url,
                            mode=search_response.trace.mode if search_response.trace else OperationMode.BALANCED,
                        )
                    )
                )

        return {
            "status": "success" if search_response.success else "error",
            "search": search_response.to_dict(),
            "documents": [doc.to_dict() for doc in documents],
            "documents_count": len(documents),
        }

    def _get_scraper(self) -> Any:
        if self.scraper is not None:
            return self.scraper
        # Lazy import to reduce startup dependency load.
        from .unified_web_scraper import UnifiedWebScraper

        self.scraper = UnifiedWebScraper()
        return self.scraper

    @staticmethod
    def _to_unified_hit(item: Any) -> UnifiedSearchHit:
        """Map orchestrator result to unified search hit contract."""
        score = getattr(item, "score", 1.0)
        try:
            score_f = float(score)
        except Exception:
            score_f = 1.0

        metadata = getattr(item, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {"raw_metadata": metadata}

        return UnifiedSearchHit(
            title=getattr(item, "title", "") or "",
            url=getattr(item, "url", ""),
            snippet=getattr(item, "snippet", "") or "",
            source=str(getattr(item, "engine", "unknown")),
            score=score_f,
            metadata=metadata,
        )

    @staticmethod
    def _choose_selected_provider(
        providers_used: Iterable[str],
        hits: List[UnifiedSearchHit],
    ) -> Optional[str]:
        providers = [p for p in providers_used if p]
        if providers:
            return providers[0]
        if hits:
            return hits[0].source
        return None


__all__ = [
    "DEFAULT_SEARCH_ENGINES",
    "UnifiedAPIConfig",
    "UnifiedWebArchivingAPI",
]
