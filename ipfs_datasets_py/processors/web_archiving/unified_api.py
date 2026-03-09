"""Unified web archiving API facade.

This module provides a single high-level API for multi-provider search and fetch
workflows. The initial implementation focuses on unified search backed by the
existing multi-engine search orchestrator.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Union
from urllib.parse import urlparse

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
from .agentic_scrape_optimizer import AgenticScrapeOptimizer, ParsedScrapeResult
from .metrics.registry import MetricsRegistry
from .orchestration.executor import SearchExecutor
from .orchestration.planner import SearchPlanner
from .orchestration.scoring import ProviderScorer
from .structured_schema_compat import normalize_structured_fields
from .search_engines.orchestrator import MultiEngineOrchestrator, OrchestratorConfig


DEFAULT_SEARCH_ENGINES = ["brave", "duckduckgo", "google_cse"]

STATE_ABBREVIATION_TERMS: Dict[str, List[str]] = {
    "al": ["alabama"],
    "ak": ["alaska"],
    "az": ["arizona"],
    "ar": ["arkansas"],
    "ca": ["california"],
    "co": ["colorado"],
    "ct": ["connecticut"],
    "de": ["delaware"],
    "dc": ["district", "columbia", "district of columbia"],
    "fl": ["florida"],
    "ga": ["georgia"],
    "hi": ["hawaii"],
    "id": ["idaho"],
    "il": ["illinois"],
    "in": ["indiana"],
    "ia": ["iowa"],
    "ks": ["kansas"],
    "ky": ["kentucky"],
    "la": ["louisiana"],
    "me": ["maine"],
    "md": ["maryland"],
    "ma": ["massachusetts"],
    "mi": ["michigan"],
    "mn": ["minnesota"],
    "ms": ["mississippi"],
    "mo": ["missouri"],
    "mt": ["montana"],
    "ne": ["nebraska"],
    "nv": ["nevada"],
    "nh": ["new hampshire"],
    "nj": ["new jersey"],
    "nm": ["new mexico"],
    "ny": ["new york"],
    "nc": ["north carolina"],
    "nd": ["north dakota"],
    "oh": ["ohio"],
    "ok": ["oklahoma"],
    "or": ["oregon"],
    "pa": ["pennsylvania"],
    "ri": ["rhode island"],
    "sc": ["south carolina"],
    "sd": ["south dakota"],
    "tn": ["tennessee"],
    "tx": ["texas"],
    "ut": ["utah"],
    "vt": ["vermont"],
    "va": ["virginia"],
    "wa": ["washington"],
    "wv": ["west virginia"],
    "wi": ["wisconsin"],
    "wy": ["wyoming"],
}


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
        agentic_optimizer: Optional[AgenticScrapeOptimizer] = None,
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
        self.agentic_optimizer = agentic_optimizer or AgenticScrapeOptimizer()

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
                    "requested_domain": search_request.domain,
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
                    "requested_domain": search_request.domain,
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

            if scraper_result is None:
                raise RuntimeError("scraper returned no result")
            parsed = self._prepare_scrape_result(
                requested_url=fetch_request.url,
                scraper_result=scraper_result,
                domain=fetch_request.domain,
            )

            relocation_allowed = not bool((fetch_request.metadata or {}).get("suppress_relocation_search"))
            if relocation_allowed and self._should_try_relocation_search(scraper_result=scraper_result, parsed=parsed):
                relocated_response = self._fetch_via_relocation_search(
                    fetch_request=fetch_request,
                    trace=trace,
                    request_id=request_id,
                )
                if relocated_response is not None:
                    relocated_response.trace = trace
                    trace.total_latency_ms = (time.time() - start_time) * 1000.0
                    trace.finished_at = datetime.utcnow().isoformat()
                    if relocated_response.success:
                        self.metrics_registry.record_event(
                            provider=provider,
                            operation="fetch",
                            success=True,
                            latency_ms=trace.total_latency_ms,
                            items_processed=1,
                            quality_score=relocated_response.quality_score,
                        )
                    else:
                        self.metrics_registry.record_event(
                            provider=provider,
                            operation="fetch",
                            success=False,
                            latency_ms=trace.total_latency_ms,
                            items_processed=0,
                            error_type="relocation_fetch_failed",
                        )
                    return relocated_response

            trace.total_latency_ms = (time.time() - start_time) * 1000.0
            trace.finished_at = datetime.utcnow().isoformat()

            if not getattr(scraper_result, "success", False):
                return self._build_failed_fetch_response(
                    fetch_request=fetch_request,
                    trace=trace,
                    request_id=request_id,
                    provider=provider,
                    scraper_result=scraper_result,
                )

            quality_score = self._calculate_quality_score(scraper_result=scraper_result, parsed=parsed)
            doc = self._build_document(
                requested_url=fetch_request.url,
                document_url=fetch_request.url,
                scraper_result=scraper_result,
                parsed=parsed,
                domain=fetch_request.domain,
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
                metadata={
                    "requested_mode": fetch_request.mode.value,
                    "requested_domain": fetch_request.domain,
                },
            )

        except BaseException as exc:
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
                        code="fetch_interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "fetch_exception",
                        message=str(exc),
                        provider=provider,
                        retryable=not isinstance(exc, SystemExit),
                        severity=ErrorSeverity.WARNING if isinstance(exc, (KeyboardInterrupt, SystemExit)) else ErrorSeverity.ERROR,
                        context={"request_id": request_id},
                    )
                ],
                success=False,
                quality_score=0.0,
                metadata={
                    "requested_mode": fetch_request.mode.value,
                    "requested_domain": fetch_request.domain,
                },
            )

    def _prepare_scrape_result(
        self,
        *,
        requested_url: str,
        scraper_result: Any,
        domain: str,
    ) -> ParsedScrapeResult:
        # Best-effort PDF bytes fetch for document-style links.
        if requested_url.lower().endswith(".pdf"):
            raw_bytes = self._fetch_raw_bytes(requested_url)
            if raw_bytes:
                if not isinstance(getattr(scraper_result, "metadata", None), dict):
                    scraper_result.metadata = {}
                scraper_result.metadata["raw_bytes"] = raw_bytes
                scraper_result.metadata.setdefault("content_type", "application/pdf")

        return self.agentic_optimizer.transform(
            url=requested_url,
            title=getattr(scraper_result, "title", "") or "",
            text=getattr(scraper_result, "text", "") or "",
            html=getattr(scraper_result, "html", "") or "",
            metadata=getattr(scraper_result, "metadata", {}) or {},
            domain=domain,
        )

    def _build_document(
        self,
        *,
        requested_url: str,
        document_url: str,
        scraper_result: Any,
        parsed: ParsedScrapeResult,
        domain: str,
        relocation_metadata: Optional[Dict[str, Any]] = None,
    ) -> UnifiedDocument:
        normalized_fields, migration_meta = normalize_structured_fields(
            fields=parsed.structured_fields,
            requested_domain=domain,
            source_type=parsed.source_type,
        )
        metadata = {
            **(getattr(scraper_result, "metadata", {}) or {}),
            "source_type": parsed.source_type,
            "domain": domain,
            "entities": parsed.entities,
            "structured_fields": normalized_fields,
            "structured_fields_version": normalized_fields.get("schema", "general_v1"),
            "links": getattr(scraper_result, "links", []) or [],
            **migration_meta,
        }
        if relocation_metadata:
            metadata.update(relocation_metadata)

        extraction_provenance = {
            "method": getattr(getattr(scraper_result, "method_used", None), "value", None),
            "extraction_time": getattr(scraper_result, "extraction_time", 0.0),
        }
        if relocation_metadata and relocation_metadata.get("relocated_via_search"):
            extraction_provenance["relocated_from"] = requested_url
            extraction_provenance["relocated_to"] = document_url

        return UnifiedDocument(
            url=document_url,
            title=parsed.title,
            text=parsed.cleaned_text,
            html=getattr(scraper_result, "html", "") or "",
            content_type=(getattr(scraper_result, "metadata", {}) or {}).get("content_type", ""),
            metadata=metadata,
            extraction_provenance=extraction_provenance,
        )

    @staticmethod
    def _calculate_quality_score(*, scraper_result: Any, parsed: ParsedScrapeResult) -> float:
        text = getattr(scraper_result, "text", "") or ""
        html = getattr(scraper_result, "html", "") or ""
        return 1.0 if parsed.cleaned_text else (0.4 if (text or html) else 0.0)

    def _build_failed_fetch_response(
        self,
        *,
        fetch_request: UnifiedFetchRequest,
        trace: ExecutionTrace,
        request_id: str,
        provider: str,
        scraper_result: Any,
    ) -> UnifiedFetchResponse:
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
            metadata={
                "requested_mode": fetch_request.mode.value,
                "requested_domain": fetch_request.domain,
            },
        )

    def _should_try_relocation_search(self, *, scraper_result: Any, parsed: ParsedScrapeResult) -> bool:
        if not getattr(scraper_result, "success", False):
            return True

        title = str(getattr(scraper_result, "title", "") or "").strip()
        text = str(getattr(scraper_result, "text", "") or "").strip()
        html = str(getattr(scraper_result, "html", "") or "").strip()
        cleaned = str(parsed.cleaned_text or "").strip()

        hay = " ".join(
            [
                title,
                text,
                html,
                cleaned,
            ]
        ).lower()
        relocation_signals = [
            "404 not found",
            "page not found",
            "document not found",
            "resource not found",
            "has moved",
            "moved permanently",
            "301 moved permanently",
            "410 gone",
        ]
        if any(signal in hay for signal in relocation_signals):
            return True

        # Some archive-origin fetches return a technically successful but empty shell.
        # Treat those as relocation candidates so search engines can discover the live replacement.
        thin_success = not cleaned and len(title) < 8 and len(text) < 80 and len(html) < 400
        return thin_success

    def _fetch_via_relocation_search(
        self,
        *,
        fetch_request: UnifiedFetchRequest,
        trace: ExecutionTrace,
        request_id: str,
    ) -> Optional[UnifiedFetchResponse]:
        if "relocation_search" not in trace.providers_attempted:
            trace.providers_attempted.append("relocation_search")
            trace.fallback_count += 1

        title_hint = str((fetch_request.metadata or {}).get("title_hint") or "")
        target_terms = self._relocation_target_terms(
            source_url=fetch_request.url,
            target_terms=[],
            title_hint=title_hint,
        )
        candidates = self._search_relocation_candidates(
            source_url=fetch_request.url,
            target_terms=target_terms,
            mode=fetch_request.mode,
            title_hint=title_hint,
            domain=fetch_request.domain,
        )
        if not candidates:
            return None

        for candidate in candidates:
            candidate_request = UnifiedFetchRequest(
                url=candidate,
                mode=fetch_request.mode,
                timeout_seconds=fetch_request.timeout_seconds,
                fallback_enabled=fetch_request.fallback_enabled,
                min_quality=fetch_request.min_quality,
                provider_allowlist=fetch_request.provider_allowlist,
                provider_denylist=fetch_request.provider_denylist,
                domain=fetch_request.domain,
                metadata={
                    **(fetch_request.metadata or {}),
                    "suppress_relocation_search": True,
                },
            )
            candidate_response = self.fetch(candidate_request)
            if not candidate_response.success or candidate_response.document is None:
                continue

            candidate_response.url = fetch_request.url
            candidate_response.metadata = {
                **(candidate_response.metadata or {}),
                "requested_mode": fetch_request.mode.value,
                "requested_domain": fetch_request.domain,
                "relocated_via_search": True,
                "relocated_from": fetch_request.url,
                "relocated_to": candidate,
                "request_id": request_id,
            }
            candidate_response.document.metadata = {
                **(candidate_response.document.metadata or {}),
                "relocated_via_search": True,
                "relocated_from": fetch_request.url,
                "relocated_to": candidate,
            }
            candidate_response.document.extraction_provenance = {
                **(candidate_response.document.extraction_provenance or {}),
                "relocated_from": fetch_request.url,
                "relocated_to": candidate,
            }
            return candidate_response

        return None

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
                            domain=search_response.metadata.get("requested_domain", "general"),
                        )
                    )
                )

        return {
            "status": "success" if search_response.success else "error",
            "search": search_response.to_dict(),
            "documents": [doc.to_dict() for doc in documents],
            "documents_count": len(documents),
        }

    def agentic_discover_and_fetch(
        self,
        *,
        seed_urls: List[str],
        target_terms: List[str],
        max_hops: int = 2,
        max_pages: int = 10,
        mode: OperationMode = OperationMode.BALANCED,
    ) -> Dict[str, Any]:
        """Agentically discover and fetch pages when data location is unknown.

        The loop fetches seed pages, ranks outgoing links against target terms,
        and follows the most promising links up to hop/page limits.
        """
        visited = set()
        frontier = list(seed_urls)
        collected: List[Dict[str, Any]] = []
        relocation_searches = 0
        relocation_candidates_added = 0

        for _hop in range(max(0, int(max_hops)) + 1):
            if not frontier or len(visited) >= max_pages:
                break

            next_frontier: List[str] = []
            for url in frontier:
                if url in visited or len(visited) >= max_pages:
                    continue
                visited.add(url)

                response = self.fetch(UnifiedFetchRequest(url=url, mode=mode))
                collected.append(response.to_dict())

                ranked_same_host: List[Dict[str, Any]] = []
                if not response.success or not response.document:
                    relocation_added = self._extend_frontier_with_relocation_hits(
                        next_frontier=next_frontier,
                        source_url=url,
                        target_terms=target_terms,
                        visited=visited,
                        mode=mode,
                    )
                    if relocation_added:
                        relocation_searches += 1
                        relocation_candidates_added += relocation_added
                    continue

                links = response.document.metadata.get("links") or []
                if not isinstance(links, list):
                    links = []
                ranked = self.agentic_optimizer.rank_links(links, target_terms)
                ranked_same_host = [
                    item
                    for item in ranked
                    if self._is_http_url(str(item.get("url") or ""))
                    and str(item.get("url") or "") not in visited
                    and self._same_host(url, str(item.get("url") or ""))
                ]

                for item in ranked_same_host[:5]:
                    link_url = str(item.get("url") or "")
                    if link_url not in next_frontier:
                        next_frontier.append(link_url)

                should_search_relocation = (
                    response.quality_score < 0.5
                    or not ranked_same_host
                )
                if should_search_relocation:
                    relocation_added = self._extend_frontier_with_relocation_hits(
                        next_frontier=next_frontier,
                        source_url=url,
                        target_terms=target_terms,
                        visited=visited,
                        mode=mode,
                        response=response,
                    )
                    if relocation_added:
                        relocation_searches += 1
                        relocation_candidates_added += relocation_added

            frontier = next_frontier

        return {
            "status": "success",
            "visited_count": len(visited),
            "results": collected,
            "relocation_searches": relocation_searches,
            "relocation_candidates_added": relocation_candidates_added,
        }

    def _extend_frontier_with_relocation_hits(
        self,
        *,
        next_frontier: List[str],
        source_url: str,
        target_terms: List[str],
        visited: set[str],
        mode: OperationMode,
        response: Optional[UnifiedFetchResponse] = None,
    ) -> int:
        """Search for likely relocated URLs and queue strong candidates."""
        added = 0
        candidates = self._search_relocation_candidates(
            source_url=source_url,
            target_terms=target_terms,
            mode=mode,
            response=response,
            domain="general",
        )
        for candidate in candidates:
            if candidate in visited or candidate in next_frontier:
                continue
            next_frontier.append(candidate)
            added += 1
        return added

    def _search_relocation_candidates(
        self,
        *,
        source_url: str,
        target_terms: List[str],
        mode: OperationMode,
        response: Optional[UnifiedFetchResponse] = None,
        title_hint: str = "",
        domain: str = "general",
    ) -> List[str]:
        """Use configured search engines to find pages that likely replaced a dead URL."""
        candidates: List[str] = []
        seen_urls = set()

        for query in self._build_relocation_queries(
            source_url=source_url,
            target_terms=target_terms,
            response=response,
            title_hint=title_hint,
        ):
            search_response = self.search(
                UnifiedSearchRequest(
                    query=query,
                    mode=mode,
                    max_results=5,
                    domain=domain,
                )
            )
            if not search_response.success:
                continue

            ranked_hits = self.agentic_optimizer.rank_links(
                [
                    {
                        "url": hit.url,
                        "text": " ".join([hit.title, hit.snippet]).strip(),
                    }
                    for hit in search_response.results
                ],
                self._relocation_target_terms(
                    source_url=source_url,
                    target_terms=target_terms,
                    response=response,
                    title_hint=title_hint,
                ),
            )
            for item in ranked_hits[:3]:
                candidate_url = str(item.get("url") or "")
                candidate_text = str(item.get("text") or "")
                score = float(item.get("score", 0) or 0)
                if not self._is_http_url(candidate_url):
                    continue
                if candidate_url == source_url or candidate_url in seen_urls:
                    continue
                if not self._is_plausible_relocation_candidate(
                    source_url=source_url,
                    candidate_url=candidate_url,
                    candidate_text=candidate_text,
                    score=score,
                    domain=domain,
                ):
                    continue
                seen_urls.add(candidate_url)
                candidates.append(candidate_url)

            if candidates:
                break

        return candidates

    def _build_relocation_queries(
        self,
        *,
        source_url: str,
        target_terms: List[str],
        response: Optional[UnifiedFetchResponse] = None,
        title_hint: str = "",
    ) -> List[str]:
        """Construct search queries that can surface relocated content."""
        parsed = urlparse(source_url)
        host = parsed.netloc.lower()
        path_tokens = self._tokenize_for_search(parsed.path)
        host_tokens = self._tokenize_for_search(host)
        title_tokens = self._tokenize_for_search(
            getattr(getattr(response, "document", None), "title", "") or title_hint or ""
        )
        terms = self._relocation_target_terms(
            source_url=source_url,
            target_terms=target_terms,
            response=response,
            title_hint=title_hint,
        )

        exact_url = f'"{source_url}"'
        host_query = " ".join([host] + host_tokens[:4] + terms[:4]).strip()
        slug_query = " ".join(host_tokens[:2] + path_tokens[:6] + terms[:4]).strip()
        title_query = " ".join(title_tokens[:6] + terms[:4]).strip()

        queries: List[str] = []
        for candidate in [exact_url, host_query, slug_query, title_query]:
            normalized = " ".join(candidate.split()).strip()
            if normalized and normalized not in queries:
                queries.append(normalized)
        return queries

    def _relocation_target_terms(
        self,
        *,
        source_url: str,
        target_terms: List[str],
        response: Optional[UnifiedFetchResponse] = None,
        title_hint: str = "",
    ) -> List[str]:
        parsed = urlparse(source_url)
        base_terms = list(target_terms)
        base_terms.extend(self._jurisdiction_terms_from_url(source_url))
        base_terms.extend(self._tokenize_for_search(parsed.netloc)[:4])
        base_terms.extend(self._tokenize_for_search(parsed.path)[:4])
        if response and response.document and response.document.title:
            base_terms.extend(self._tokenize_for_search(response.document.title)[:4])
        elif title_hint:
            base_terms.extend(self._tokenize_for_search(title_hint)[:4])

        deduped: List[str] = []
        seen = set()
        for term in base_terms:
            normalized = term.strip().lower()
            if len(normalized) < 3 or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(term)
        return deduped

    @staticmethod
    def _tokenize_for_search(value: str) -> List[str]:
        return [token for token in re.findall(r"[A-Za-z0-9]+", value or "") if token]

    @staticmethod
    def _jurisdiction_terms_from_url(source_url: str) -> List[str]:
        parsed = urlparse(source_url)
        tokens = [token.lower() for token in re.findall(r"[A-Za-z0-9]+", f"{parsed.netloc} {parsed.path}") if token]
        terms: List[str] = []
        seen = set()
        for token in tokens:
            expansions = STATE_ABBREVIATION_TERMS.get(token, [])
            for expansion in expansions:
                normalized = expansion.lower()
                if normalized not in seen:
                    seen.add(normalized)
                    terms.append(expansion)
        return terms

    def _is_plausible_relocation_candidate(
        self,
        *,
        source_url: str,
        candidate_url: str,
        candidate_text: str,
        score: float,
        domain: str,
    ) -> bool:
        source = urlparse(source_url)
        candidate = urlparse(candidate_url)
        source_host = source.netloc.lower()
        candidate_host = candidate.netloc.lower()
        source_host_tokens = self._host_identity_tokens(source_host)
        candidate_host_tokens = self._host_identity_tokens(candidate_host)

        if not candidate_host:
            return False

        if candidate_host == source_host:
            return True

        if self._same_registered_domain(source_host, candidate_host):
            return score >= 1

        hay = f"{candidate_url} {candidate_text}".lower()
        legal_hints = ["code", "law", "laws", "statute", "statutes", "rule", "rules", "regulation", "regulations", "legis"]
        blocked_hosts = ["wikipedia.org", "youtube.com", "facebook.com", "instagram.com", "linkedin.com", "x.com", "twitter.com"]
        if any(host in candidate_host for host in blocked_hosts):
            return False

        if domain == "legal":
            host_overlap = bool(source_host_tokens & candidate_host_tokens)
            return score >= 1 and any(hint in hay for hint in legal_hints) and host_overlap

        return score >= 2

    @staticmethod
    def _same_registered_domain(source_host: str, candidate_host: str) -> bool:
        def _tail(host: str) -> str:
            parts = [part for part in (host or "").split(".") if part]
            if len(parts) >= 2:
                return ".".join(parts[-2:])
            return host or ""

        return _tail(source_host) == _tail(candidate_host) and bool(_tail(source_host))

    @staticmethod
    def _host_identity_tokens(host: str) -> set[str]:
        generic = {"www", "gov", "com", "org", "net", "edu", "legis", "law", "laws", "rule", "rules"}
        tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9]+", host or "") if token}
        return {token for token in tokens if token not in generic}

    def _get_scraper(self) -> Any:
        if self.scraper is not None:
            return self.scraper
        # Lazy import to reduce startup dependency load.
        from .unified_web_scraper import UnifiedWebScraper

        self.scraper = UnifiedWebScraper()
        return self.scraper

    @staticmethod
    def _fetch_raw_bytes(url: str) -> bytes:
        try:
            import requests

            resp = requests.get(url, timeout=30)
            if resp.ok:
                return resp.content
        except Exception:
            return b""
        return b""

    @staticmethod
    def _is_http_url(value: str) -> bool:
        try:
            parsed = urlparse(value)
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False

    @staticmethod
    def _same_host(base_url: str, candidate_url: str) -> bool:
        try:
            return urlparse(base_url).netloc == urlparse(candidate_url).netloc
        except Exception:
            return False

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
