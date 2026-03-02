"""Planning utilities for unified search execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..contracts import OperationMode, UnifiedSearchRequest
from .scoring import ProviderScore, ProviderScorer


@dataclass
class SearchExecutionPlan:
    """Concrete provider plan for one unified search request."""

    query: str
    max_results: int
    offset: int
    mode: OperationMode
    providers_ordered: List[str] = field(default_factory=list)
    provider_scores: List[ProviderScore] = field(default_factory=list)
    metadata: Dict[str, object] = field(default_factory=dict)


class SearchPlanner:
    """Plan provider order for search requests using dynamic scoring."""

    def __init__(
        self,
        scorer: ProviderScorer,
        default_search_engines: Sequence[str],
    ):
        self.scorer = scorer
        self.default_search_engines = list(default_search_engines)

    def plan(
        self,
        request: UnifiedSearchRequest,
        *,
        cost_hints: Optional[Dict[str, float]] = None,
        scoring_window_seconds: Optional[int] = None,
    ) -> SearchExecutionPlan:
        """Build a ranked provider execution plan."""
        candidates = self._resolve_candidates(request)
        ranked_scores = self.scorer.rank_providers(
            providers=candidates,
            operation="search",
            mode=request.mode,
            window_seconds=scoring_window_seconds,
            cost_hints=cost_hints,
        )

        ordered = [score.provider for score in ranked_scores]
        if not ordered:
            raise ValueError("No provider candidates available for search planning")

        return SearchExecutionPlan(
            query=request.query,
            max_results=request.max_results,
            offset=request.offset,
            mode=request.mode,
            providers_ordered=ordered,
            provider_scores=ranked_scores,
            metadata={
                "candidate_count": len(candidates),
                "scoring_window_seconds": scoring_window_seconds,
            },
        )

    def _resolve_candidates(self, request: UnifiedSearchRequest) -> List[str]:
        base: Sequence[str]
        if request.provider_allowlist:
            base = list(request.provider_allowlist)
        else:
            base = list(self.default_search_engines)

        deny = set(request.provider_denylist or [])
        return [engine for engine in base if engine not in deny]


__all__ = [
    "SearchExecutionPlan",
    "SearchPlanner",
]
