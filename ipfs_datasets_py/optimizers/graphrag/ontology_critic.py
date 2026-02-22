"""
Ontology Critic for GraphRAG Optimization.

This module provides an LLM-based critic that evaluates knowledge graph ontology
quality across multiple dimensions. Inspired by the critic agent from the
complaint-generator adversarial harness.

The critic analyzes ontologies and provides structured feedback with scores across
multiple evaluation dimensions, along with actionable recommendations for improvement.

Key Features:
    - Multi-dimensional ontology evaluation
    - Structured scoring with weighted dimensions
    - Actionable recommendations for improvement
    - Comparison between ontologies
    - Domain-aware evaluation

Evaluation Dimensions:
    - Completeness (22%): Coverage of key concepts and relationships
    - Consistency (22%): Internal logical consistency
    - Clarity (14%): Clear entity definitions and relationships
    - Granularity (14%): Appropriate level of detail
    - Relationship Coherence (13%): Quality and semantic coherence of relationships
    - Domain Alignment (15%): Adherence to domain conventions

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import (
    ...     OntologyCritic,
    ...     OntologyGenerationContext
    ... )
    >>> 
    >>> critic = OntologyCritic(backend_config={
    ...     'model': 'gpt-4',
    ...     'temperature': 0.3
    ... })
    >>> 
    >>> score = critic.evaluate_ontology(
    ...     ontology=ontology,
    ...     context=context,
    ...     source_data=data
    ... )
    >>> 
    >>> print(f"Overall: {score.overall}, Completeness: {score.completeness}")

References:
    - complaint-generator critic.py: Multi-dimensional evaluation patterns
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.optimizers.common.base_critic import BaseCritic, CriticResult
from ipfs_datasets_py.optimizers.common.backend_selection import resolve_backend_settings

logger = logging.getLogger(__name__)


# Evaluation dimension weights (must sum to 1.0)
DIMENSION_WEIGHTS = {
    'completeness': 0.22,
    'consistency': 0.22,
    'clarity': 0.14,
    'granularity': 0.14,
    'relationship_coherence': 0.13,
    'domain_alignment': 0.15,
}


@dataclass
class BackendConfig:
    """
    Typed configuration for the LLM backend used by OntologyCritic.

    Attributes:
        provider: Backend provider, e.g. 'openai', 'anthropic', 'accelerate'.
        model: Model name / identifier.
        temperature: Sampling temperature (0.0 - 1.0).
        max_tokens: Maximum tokens to generate.
        extra: Any additional provider-specific options.
    """

    provider: str = "accelerate"
    model: str = "gpt-4"
    temperature: float = 0.3
    max_tokens: int = 2048
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BackendConfig":
        resolved = resolve_backend_settings(
            d,
            default_provider="accelerate",
            default_model="gpt-4",
            use_ipfs_accelerate=bool(d.get("use_ipfs_accelerate", True)),
            prefer_accelerate=True,
        )
        return cls(
            provider=resolved.provider,
            model=resolved.model,
            temperature=resolved.temperature,
            max_tokens=resolved.max_tokens,
            extra=resolved.extra,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            **self.extra,
        }


@dataclass
class CriticScore:
    """
    Structured ontology quality score.
    
    Provides a comprehensive evaluation of an ontology across multiple dimensions,
    with weighted overall score and actionable feedback.
    
    Attributes:
        overall: Overall quality score (0.0 to 1.0), weighted average of dimensions
        completeness: Coverage of key concepts and relationships (0.0 to 1.0)
        consistency: Internal logical consistency (0.0 to 1.0)
        clarity: Clarity of entity definitions and relationships (0.0 to 1.0)
        granularity: Appropriateness of detail level (0.0 to 1.0)
        relationship_coherence: Quality and semantic coherence of relationships (0.0 to 1.0)
        domain_alignment: Adherence to domain conventions (0.0 to 1.0)
        strengths: List of ontology strengths
        weaknesses: List of ontology weaknesses
        recommendations: Actionable recommendations for improvement
        metadata: Additional evaluation metadata
        
    Example:
        >>> score = CriticScore(
        ...     completeness=0.85,
        ...     consistency=0.90,
        ...     clarity=0.75,
        ...     granularity=0.80,
        ...     relationship_coherence=0.82,
        ...     domain_alignment=0.88
        ... )
        >>> print(f"Overall: {score.overall:.2f}")
    """
    
    completeness: float
    consistency: float
    clarity: float
    granularity: float
    relationship_coherence: float
    domain_alignment: float
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def overall(self) -> float:
        """
        Calculate weighted overall score.
        
        Returns:
            Overall score as weighted average of dimension scores
        """
        return (
            DIMENSION_WEIGHTS['completeness'] * self.completeness +
            DIMENSION_WEIGHTS['consistency'] * self.consistency +
            DIMENSION_WEIGHTS['clarity'] * self.clarity +
            DIMENSION_WEIGHTS['granularity'] * self.granularity +
            DIMENSION_WEIGHTS['relationship_coherence'] * self.relationship_coherence +
            DIMENSION_WEIGHTS['domain_alignment'] * self.domain_alignment
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert score to dictionary representation.
        
        Returns:
            Dictionary with all score components and feedback
        """
        return {
            'overall': self.overall,
            'dimensions': {
                'completeness': self.completeness,
                'consistency': self.consistency,
                'clarity': self.clarity,
                'granularity': self.granularity,
                'relationship_coherence': self.relationship_coherence,
                'domain_alignment': self.domain_alignment,
            },
            'weights': DIMENSION_WEIGHTS,
            'strengths': self.strengths,
            'weaknesses': self.weaknesses,
            'recommendations': self.recommendations,
            'metadata': self.metadata,
        }

    def to_list(self) -> List[float]:
        """Return dimension values as a flat list.

        Order: ``[completeness, consistency, clarity, granularity, relationship_coherence, domain_alignment]``.

        Returns:
            List of 6 floats in the canonical dimension order.

        Example:
            >>> score.to_list()
            [0.8, 0.7, 0.6, 0.5, 0.82, 0.9]
        """
        return [
            self.completeness,
            self.consistency,
            self.clarity,
            self.granularity,
            self.relationship_coherence,
            self.domain_alignment,
        ]

    def is_passing(self, threshold: float = 0.6) -> bool:
        """Return ``True`` if ``overall`` is at or above *threshold*.

        Args:
            threshold: Minimum acceptable overall score.  Defaults to 0.6.

        Returns:
            ``True`` when ``self.overall >= threshold``.

        Example:
            >>> score.is_passing()
            True
            >>> score.is_passing(threshold=0.95)
            False
        """
        return self.overall >= threshold

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CriticScore":
        """Reconstruct a :class:`CriticScore` from a dictionary.

        Accepts the format produced by :meth:`to_dict` (where dimension values
        live under a ``"dimensions"`` sub-key) **or** a flat dict with
        dimension names at the top level.

        Args:
            d: Dictionary with score data.

        Returns:
            A new :class:`CriticScore` instance.

        Example:
            >>> d = score.to_dict()
            >>> restored = CriticScore.from_dict(d)
            >>> restored.completeness == score.completeness
            True
        """
        # Support both nested (to_dict format) and flat dicts
        dims = d.get("dimensions", d)
        return cls(
            completeness=float(dims.get("completeness", 0.0)),
            consistency=float(dims.get("consistency", 0.0)),
            clarity=float(dims.get("clarity", 0.0)),
            granularity=float(dims.get("granularity", 0.0)),
            relationship_coherence=float(dims.get("relationship_coherence", 0.0)),
            domain_alignment=float(dims.get("domain_alignment", 0.0)),
            strengths=list(d.get("strengths", [])),
            weaknesses=list(d.get("weaknesses", [])),
            recommendations=list(d.get("recommendations", [])),
            metadata=dict(d.get("metadata", {})),
        )

    def __sub__(self, other: "CriticScore") -> "CriticScore":
        """Return a delta :class:`CriticScore` (``self - other``).

        Each dimension is the arithmetic difference.  ``strengths``,
        ``weaknesses``, and ``recommendations`` are cleared; ``metadata``
        gets a ``'delta': True`` marker.  Negative scores are allowed so the
        caller can tell whether each dimension improved or regressed.

        Args:
            other: The baseline :class:`CriticScore` to subtract.

        Returns:
            A new :class:`CriticScore` representing the change.

        Raises:
            TypeError: If *other* is not a :class:`CriticScore`.
        """
        if not isinstance(other, CriticScore):
            return NotImplemented
        return CriticScore(
            completeness=self.completeness - other.completeness,
            consistency=self.consistency - other.consistency,
            clarity=self.clarity - other.clarity,
            granularity=self.granularity - other.granularity,
            relationship_coherence=self.relationship_coherence - other.relationship_coherence,
            domain_alignment=self.domain_alignment - other.domain_alignment,
            metadata={"delta": True},
        )

    def to_radar_chart_data(self) -> Dict[str, Any]:
        """Return data suitable for rendering a radar / spider chart.

        The returned dict has two keys:

        * ``"axes"`` - ordered list of dimension names.
        * ``"values"`` - list of float scores in the same order (0.0-1.0).

        The ordering is fixed so that repeated calls produce comparable
        structures across multiple :class:`CriticScore` instances.

        Returns:
            Dict with ``"axes"`` and ``"values"`` lists.

        Example:
            >>> data = score.to_radar_chart_data()
            >>> list(zip(data["axes"], data["values"]))
            [('completeness', 0.8), ('consistency', 0.9), ...]
        """
        axes = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"]
        return {
            "axes": axes,
            "values": [getattr(self, ax) for ax in axes],
        }

    def weighted_overall(self, weights: Dict[str, float]) -> float:
        """Compute an overall score using *caller-supplied* dimension weights.

        Unlike the :attr:`overall` property (which uses the module-level
        :data:`DIMENSION_WEIGHTS`), this method normalises the supplied
        weights so they sum to 1.0 before computing the dot product.

        Args:
            weights: Mapping of dimension name -> weight.  Only the five
                standard dimensions are used; unknown keys are silently
                ignored.  At least one dimension must have a positive weight.

        Returns:
            Weighted overall score in [0.0, 1.0].

        Raises:
            ValueError: If *weights* sums to zero or is empty after filtering.
        """
        dims = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"]
        filtered = {k: v for k, v in weights.items() if k in dims and v > 0}
        if not filtered:
            raise ValueError("weights must contain at least one positive standard dimension")
        total_w = sum(filtered.values())
        return sum(getattr(self, d) * w / total_w for d, w in filtered.items())

    def to_html_report(self) -> str:
        """Render this :class:`CriticScore` as a simple HTML table.

        Produces a self-contained ``<div>`` containing a ``<table>`` of
        dimension scores, an overall score row, and an unordered list of
        recommendations.

        Returns:
            HTML string (UTF-8 compatible).

        Example:
            >>> html = score.to_html_report()
            >>> "<table" in html
            True
        """
        _DIMS = [
            ("Completeness", self.completeness),
            ("Consistency", self.consistency),
            ("Clarity", self.clarity),
            ("Granularity", self.granularity),
            ("Domain Alignment", self.domain_alignment),
            ("Overall", self.overall),
        ]
        rows = "\n".join(
            f"  <tr><td>{label}</td><td>{score:.4f}</td></tr>"
            for label, score in _DIMS
        )
        recs_html = "".join(f"<li>{r}</li>" for r in self.recommendations)
        recs_section = f"<ul>{recs_html}</ul>" if self.recommendations else "<p>No recommendations.</p>"
        return (
            "<div class='critic-report'>\n"
            f"<table>\n<tr><th>Dimension</th><th>Score</th></tr>\n{rows}\n</table>\n"
            f"<h3>Recommendations</h3>{recs_section}\n"
            "</div>"
        )

    def __eq__(self, other: object) -> bool:
        """Check equality based on overall score within tolerance.
        
        Two :class:`CriticScore` instances are considered equal if their
        overall scores differ by less than 0.0001 (tolerance for floating point).
        
        Args:
            other: The object to compare with.
            
        Returns:
            ``True`` if both are ``CriticScore`` instances with equal overall
            scores (within tolerance).
        """
        if not isinstance(other, CriticScore):
            return NotImplemented
        return abs(self.overall - other.overall) < 0.0001

    def __lt__(self, other: "CriticScore") -> bool:
        """Compare based on overall score (less than).
        
        Args:
            other: The :class:`CriticScore` to compare with.
            
        Returns:
            ``True`` if this score's overall is less than the other's.
            
        Raises:
            TypeError: If *other* is not a :class:`CriticScore`.
        """
        if not isinstance(other, CriticScore):
            return NotImplemented
        return self.overall < other.overall

    def __le__(self, other: "CriticScore") -> bool:
        """Compare based on overall score (less than or equal).
        
        Args:
            other: The :class:`CriticScore` to compare with.
            
        Returns:
            ``True`` if this score's overall is less than or equal to the other's.
            
        Raises:
            TypeError: If *other* is not a :class:`CriticScore`.
        """
        if not isinstance(other, CriticScore):
            return NotImplemented
        return self.overall <= other.overall

    def __gt__(self, other: "CriticScore") -> bool:
        """Compare based on overall score (greater than).
        
        Args:
            other: The :class:`CriticScore` to compare with.
            
        Returns:
            ``True`` if this score's overall is greater than the other's.
            
        Raises:
            TypeError: If *other* is not a :class:`CriticScore`.
        """
        if not isinstance(other, CriticScore):
            return NotImplemented
        return self.overall > other.overall

    def __ge__(self, other: "CriticScore") -> bool:
        """Compare based on overall score (greater than or equal).
        
        Args:
            other: The :class:`CriticScore` to compare with.
            
        Returns:
            ``True`` if this score's overall is greater than or equal to the other's.
            
        Raises:
            TypeError: If *other* is not a :class:`CriticScore`.
        """
        if not isinstance(other, CriticScore):
            return NotImplemented
        return self.overall >= other.overall

    def __ne__(self, other: object) -> bool:
        """Check inequality based on overall score.
        
        Args:
            other: The object to compare with.
            
        Returns:
            ``True`` if the objects differ in overall score (or type).
        """
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __repr__(self) -> str:
        """Return a readable string representation of this score.
        
        Shows dimensions and overall score in a compact format suitable for
        REPL inspection and logging.
        
        Returns:
            A string like ``CriticScore(overall=0.8210, C:0.80 Co:0.85 Cl:0.75 G:0.80 RC:0.82 DA:0.88)``
        """
        dim_abbr = {
            'completeness': 'C',
            'consistency': 'Co', 
            'clarity': 'Cl',
            'granularity': 'G',
            'relationship_coherence': 'RC',
            'domain_alignment': 'DA'
        }
        dims_str = ' '.join(
            f"{dim_abbr[dim]}:{getattr(self, dim):.2f}"
            for dim in ['completeness', 'consistency', 'clarity', 'granularity', 'relationship_coherence', 'domain_alignment']
        )
        return f"CriticScore(overall={self.overall:.4f}, {dims_str})"
    
    def to_json(self) -> str:
        """Return JSON representation of this score.
        
        Useful for structured logging and programmatic result handling.
        The JSON contains all dimension scores, weights, strengths, weaknesses,
        recommendations, and metadata.
        
        Returns:
            JSON string representation of the score
        
        Example:
            >>> score.to_json()
            '{"overall": 0.821, "dimensions": {...}, ...}'
        """
        import json
        return json.dumps(self.to_dict(), default=str, indent=None)


class OntologyCritic(BaseCritic):
    """
    LLM-based critic for evaluating ontology quality.

    Extends :class:`~ipfs_datasets_py.optimizers.common.BaseCritic` so it can
    be used interchangeably with other critic types in the common optimizer loop.

    Evaluate an ontology via the standard ``BaseCritic`` interface using
    :meth:`evaluate`, or use the richer :meth:`evaluate_ontology` for a full
    :class:`CriticScore` with per-dimension breakdown.

    The critic uses rule-based heuristics (and optionally an LLM backend) to
    evaluate quality across five dimensions:
        ...     'model': 'gpt-4',
        ...     'temperature': 0.3
        ... })
        >>> 
        >>> score = critic.evaluate_ontology(ontology, context, data)
        >>> if score.overall < 0.7:
        ...     print("Needs improvement:", score.recommendations)

    Class-level cache
    -----------------
    ``_SHARED_EVAL_CACHE`` is a class-level dict shared across *all* instances
    so that equal ontologies are only evaluated once per Python process.  The
    cache is bounded at 256 entries (cleared on overflow).  Pass
    ``source_data`` to bypass caching.
    """

    # Shared across all instances -- survives instance teardown / recreation.
    _SHARED_EVAL_CACHE: Dict[str, "CriticScore"] = {}
    _SHARED_EVAL_CACHE_MAX: int = 256
    
    def __init__(
        self,
        backend_config: Optional[Union[Dict[str, Any], BackendConfig]] = None,
        use_llm: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the ontology critic.
        
        Args:
            backend_config: Configuration for LLM backend. Accepts either a
                ``BackendConfig`` instance or a plain dict with keys 'provider',
                'model', 'temperature', 'max_tokens', etc.
            use_llm: Whether to use LLM for evaluation. If False, uses
                rule-based heuristics.
            logger: Optional :class:`logging.Logger` to use instead of the
                module-level logger.  Useful for dependency injection in tests.
                
        Raises:
            ImportError: If LLM backend is required but not available
        """
        import logging as _logging
        self._log = logger or _logging.getLogger(__name__)
        if backend_config is None:
            self.backend_config: BackendConfig = BackendConfig()
        elif isinstance(backend_config, dict):
            self.backend_config = BackendConfig.from_dict(backend_config)
        else:
            self.backend_config = backend_config
        self.use_llm = use_llm
        self._llm_client = None
        
        if use_llm:
            try:
                # Try to import LLM backend
                # LLM backend integration is gated on ipfs_accelerate availability.
                # No action needed here; _llm_available stays False.
                self._llm_available = False
                self._log.info("LLM backend not configured; using rule-based evaluation")
            except ImportError as e:
                self._log.warning(
                    f"LLM backend not available: {e}. "
                    "Falling back to rule-based evaluation."
                )
                self._llm_available = False
                self.use_llm = False
        else:
            self._llm_available = False

    # ------------------------------------------------------------------ #
    # Class-level shared cache helpers                                     #
    # ------------------------------------------------------------------ #

    @classmethod
    def clear_shared_cache(cls) -> None:
        """Clear the class-level evaluation cache shared across all instances."""
        cls._SHARED_EVAL_CACHE.clear()

    @classmethod
    def shared_cache_size(cls) -> int:
        """Return the number of entries in the shared evaluation cache."""
        return len(cls._SHARED_EVAL_CACHE)

    def explain_score(self, score: "CriticScore") -> Dict[str, str]:
        """Return human-readable explanations for each dimension score.

        Args:
            score: A :class:`CriticScore` returned by :meth:`evaluate_ontology`.

        Returns:
            Dict mapping each dimension name to a one-sentence explanation
            that interprets the numeric score in plain English.
        """
        def _band(v: float) -> str:
            if v >= 0.85:
                return "excellent"
            if v >= 0.70:
                return "good"
            if v >= 0.50:
                return "acceptable"
            if v >= 0.30:
                return "weak"
            return "poor"

        explanations: Dict[str, str] = {}
        explanations["completeness"] = (
            f"Coverage is {_band(score.completeness)} ({score.completeness:.0%}): "
            + (
                "the ontology captures most expected concepts and relationships."
                if score.completeness >= 0.7
                else "many expected concepts or relationships appear to be missing."
            )
        )
        explanations["consistency"] = (
            f"Internal consistency is {_band(score.consistency)} ({score.consistency:.0%}): "
            + (
                "no significant contradictions were detected."
                if score.consistency >= 0.7
                else "logical contradictions or inconsistencies were detected."
            )
        )
        explanations["clarity"] = (
            f"Clarity is {_band(score.clarity)} ({score.clarity:.0%}): "
            + (
                "entity definitions and relationship labels are clear and unambiguous."
                if score.clarity >= 0.7
                else "some entities lack definitions or have ambiguous labels."
            )
        )
        explanations["granularity"] = (
            f"Granularity is {_band(score.granularity)} ({score.granularity:.0%}): "
            + (
                "the level of detail is appropriate for the domain."
                if score.granularity >= 0.7
                else "the ontology may be too coarse or too fine-grained for the domain."
            )
        )
        explanations["relationship_coherence"] = (
            f"Relationship coherence is {_band(score.relationship_coherence)} ({score.relationship_coherence:.0%}): "
            + (
                "relationships are well-formed, semantically meaningful, and appropriately typed."
                if score.relationship_coherence >= 0.7
                else "relationships lack semantic coherence or use overly generic/inconsistent types."
            )
        )
        explanations["domain_alignment"] = (
            f"Domain alignment is {_band(score.domain_alignment)} ({score.domain_alignment:.0%}): "
            + (
                "entities and relationships follow domain conventions."
                if score.domain_alignment >= 0.7
                else "some entities or relationships deviate from expected domain conventions."
            )
        )
        explanations["overall"] = (
            f"Overall quality is {_band(score.overall)} ({score.overall:.0%}): "
            + (
                "the ontology is ready for use."
                if score.overall >= 0.7
                else "further refinement is recommended before production use."
            )
        )
        return explanations

    # ------------------------------------------------------------------ #
    # BaseCritic interface                                                  #
    # ------------------------------------------------------------------ #

    @property
    def dimension_weights(self) -> Dict[str, float]:
        """Return the scoring weights for each evaluation dimension (read-only copy)."""
        return dict(DIMENSION_WEIGHTS)

    def evaluate(
        self,
        artifact: Any,
        context: Any,
        *,
        source_data: Optional[Any] = None,
    ) -> CriticResult:
        """Satisfy the :class:`~ipfs_datasets_py.optimizers.common.BaseCritic` interface.

        Delegates to :meth:`evaluate_ontology` and wraps the result in a
        :class:`~ipfs_datasets_py.optimizers.common.CriticResult`.

        Args:
            artifact: An ontology dictionary.
            context: Optimization or generation context.
            source_data: Optional source data for context-aware evaluation.

        Returns:
            :class:`~ipfs_datasets_py.optimizers.common.CriticResult`
        """
        score_obj = self.evaluate_ontology(artifact, context, source_data=source_data)
        return CriticResult(
            score=score_obj.overall,
            feedback=list(score_obj.recommendations),
            dimensions={
                'completeness': score_obj.completeness,
                'consistency': score_obj.consistency,
                'clarity': score_obj.clarity,
                'granularity': score_obj.granularity,
                'relationship_coherence': score_obj.relationship_coherence,
                'domain_alignment': score_obj.domain_alignment,
            },
            strengths=list(score_obj.strengths),
            weaknesses=list(score_obj.weaknesses),
            metadata=dict(score_obj.metadata),
        )

    def evaluate_ontology(
        self,
        ontology: Dict[str, Any],
        context: Any,  # OntologyGenerationContext
        source_data: Optional[Any] = None,
        timeout: Optional[float] = None,
    ) -> CriticScore:
        """
        Evaluate ontology across all quality dimensions.
        
        Performs comprehensive evaluation of an ontology, analyzing completeness,
        consistency, clarity, granularity, and domain alignment. Returns a
        structured score with actionable recommendations.
        
        Args:
            ontology: Ontology to evaluate (dictionary format)
            context: Context with domain and configuration information
            source_data: Optional source data for context-aware evaluation
            timeout: Optional wall-clock timeout in seconds.  If the evaluation
                takes longer than *timeout* seconds, a :exc:`TimeoutError` is
                raised.  ``None`` (default) means no timeout.
            
        Returns:
            CriticScore with evaluation results and recommendations
            
        Raises:
            TimeoutError: If *timeout* is set and evaluation exceeds it.
            
        Example:
            >>> score = critic.evaluate_ontology(
            ...     ontology={'entities': [...], 'relationships': [...]},
            ...     context=generation_context,
            ...     source_data="Original document text..."
            ... )
            >>> print(f"Score: {score.overall:.2f}")
            >>> for rec in score.recommendations:
            ...     print(f"- {rec}")
        """
        if timeout is not None:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                _fut = _ex.submit(
                    self._evaluate_ontology_impl, ontology, context, source_data
                )
                try:
                    return _fut.result(timeout=timeout)
                except _cf.TimeoutError:
                    raise TimeoutError(
                        f"evaluate_ontology() exceeded timeout of {timeout}s"
                    )
        return self._evaluate_ontology_impl(ontology, context, source_data)

    def _evaluate_ontology_impl(
        self,
        ontology: Dict[str, Any],
        context: Any,
        source_data: Optional[Any] = None,
    ) -> CriticScore:
        import hashlib as _hashlib
        import json as _json

        # LRU-style cache keyed on ontology content hash (skipped when source_data provided)
        if source_data is None:
            try:
                _cache_key = _hashlib.sha256(
                    _json.dumps(ontology, sort_keys=True, default=str).encode()
                ).hexdigest()
                # Check instance-local cache first, then shared class-level cache
                if not hasattr(self, '_eval_cache'):
                    self._eval_cache: dict = {}
                if _cache_key in self._eval_cache:
                    self._log.debug("OntologyCritic instance cache hit")
                    return self._eval_cache[_cache_key]
                if _cache_key in OntologyCritic._SHARED_EVAL_CACHE:
                    self._log.debug("OntologyCritic shared cache hit")
                    cached = OntologyCritic._SHARED_EVAL_CACHE[_cache_key]
                    self._eval_cache[_cache_key] = cached
                    return cached
            except (TypeError, ValueError, OverflowError):
                _cache_key = None
        else:
            _cache_key = None

        self._log.info("Evaluating ontology quality")
        
        # Evaluate each dimension
        completeness = self._evaluate_completeness(ontology, context, source_data)
        consistency = self._evaluate_consistency(ontology, context)
        clarity = self._evaluate_clarity(ontology, context)
        granularity = self._evaluate_granularity(ontology, context)
        relationship_coherence = self._evaluate_relationship_coherence(ontology, context)
        domain_alignment = self._evaluate_domain_alignment(ontology, context)
        
        # Identify strengths and weaknesses
        strengths = self._identify_strengths(
            completeness, consistency, clarity, granularity, relationship_coherence, domain_alignment
        )
        weaknesses = self._identify_weaknesses(
            completeness, consistency, clarity, granularity, relationship_coherence, domain_alignment
        )
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            ontology, context, completeness, consistency, clarity,
            granularity, relationship_coherence, domain_alignment
        )
        
        # Create score
        # Compute per-entity-type completeness breakdown for metadata
        _ent_type_counts: Dict[str, int] = {}
        for _ent in (ontology.get("entities") or []):
            if isinstance(_ent, dict):
                _etype = str(_ent.get("type", "Unknown"))
            else:
                _etype = str(getattr(_ent, "type", "Unknown"))
            _ent_type_counts[_etype] = _ent_type_counts.get(_etype, 0) + 1
        _total = sum(_ent_type_counts.values()) or 1
        _ent_type_fractions = {k: round(v / _total, 4) for k, v in _ent_type_counts.items()}

        score = CriticScore(
            completeness=completeness,
            consistency=consistency,
            clarity=clarity,
            granularity=granularity,
            relationship_coherence=relationship_coherence,
            domain_alignment=domain_alignment,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
            metadata={
                'evaluator': 'OntologyCritic',
                'use_llm': self.use_llm,
                'domain': getattr(context, 'domain', 'unknown'),
                'entity_type_counts': _ent_type_counts,
                'entity_type_fractions': _ent_type_fractions,
                'provenance_score': self._evaluate_provenance(ontology),
            }
        )
        
        self._log.info(f"Evaluation complete. Overall score: {score.overall:.2f}")
        if _cache_key is not None:
            # Populate both instance-local and shared class-level cache
            if len(self._eval_cache) >= 128:
                self._eval_cache.clear()
            self._eval_cache[_cache_key] = score
            if len(OntologyCritic._SHARED_EVAL_CACHE) >= OntologyCritic._SHARED_EVAL_CACHE_MAX:
                OntologyCritic._SHARED_EVAL_CACHE.clear()
            OntologyCritic._SHARED_EVAL_CACHE[_cache_key] = score
        return score

    def evaluate_batch(
        self,
        ontologies: List[Dict[str, Any]],
        context: Any,
        source_data: Optional[Any] = None,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Evaluate a list of ontologies and return aggregated statistics.

        Args:
            ontologies: List of ontology dictionaries to evaluate.
            context: Shared evaluation context for all ontologies.
            source_data: Optional source text passed to each evaluation.
            progress_callback: Optional callable invoked after each ontology is
                evaluated.  Called as ``progress_callback(index, total, score)``
                where *index* is 0-based.

        Returns:
            Dictionary with keys:
                - ``scores``: list of :class:`CriticScore` objects (one per ontology)
                - ``mean_overall``: mean of the per-ontology overall scores
                - ``min_overall``: minimum overall score across the batch
                - ``max_overall``: maximum overall score across the batch
                - ``count``: number of ontologies evaluated
        """
        scores: List[CriticScore] = []
        total = len(ontologies)
        for idx, ontology in enumerate(ontologies):
            score = self.evaluate_ontology(ontology, context, source_data=source_data)
            scores.append(score)
            if progress_callback is not None:
                try:
                    progress_callback(idx, total, score)
                except Exception as e:
                    # Never let a callback crash the batch
                    self._log.warning(f"Progress callback failed at index {idx}: {e}")

        if not scores:
            return {
                "scores": [],
                "mean_overall": 0.0,
                "min_overall": 0.0,
                "max_overall": 0.0,
                "count": 0,
            }

        overalls = [s.overall for s in scores]
        return {
            "scores": scores,
            "mean_overall": sum(overalls) / len(overalls),
            "min_overall": min(overalls),
            "max_overall": max(overalls),
            "count": len(scores),
        }
    
    def evaluate_batch_parallel(
        self,
        ontologies: List[Dict[str, Any]],
        context: Any,
        source_data: Optional[Any] = None,
        progress_callback: Optional[Any] = None,
        max_workers: int = 4,
    ) -> Dict[str, Any]:
        """Evaluate a list of ontologies in parallel using ThreadPoolExecutor.

        This method provides the same interface as :meth:`evaluate_batch` but
        uses multiple threads to evaluate ontologies concurrently, improving
        throughput for large batches.

        Thread Safety:
            Evaluation results are collected from worker threads and
            aggregated in the main thread. The progress callback is invoked
            from each worker thread after evaluation completes.

        Args:
            ontologies: List of ontology dictionaries to evaluate.
            context: Shared evaluation context for all ontologies.
            source_data: Optional source text passed to each evaluation.
            progress_callback: Optional callable invoked after each ontology is
                evaluated.  Called as ``progress_callback(index, total, score)``
                where *index* is 0-based.
            max_workers: Maximum number of worker threads.  Defaults to 4.

        Returns:
            Dictionary with same structure as :meth:`evaluate_batch`:
                - ``scores``: list of :class:`CriticScore` objects (one per ontology)
                - ``mean_overall``: mean of the per-ontology overall scores
                - ``min_overall``: minimum overall score across the batch
                - ``max_overall``: maximum overall score across the batch
                - ``count``: number of ontologies evaluated
        """
        if not ontologies:
            return {
                "scores": [],
                "mean_overall": 0.0,
                "min_overall": 0.0,
                "max_overall": 0.0,
                "count": 0,
            }

        total = len(ontologies)
        scores: List[Optional[CriticScore]] = [None] * total

        def _evaluate_with_index(idx_ontology_pair: tuple) -> tuple:
            """Evaluate single ontology and return (index, score) pair."""
            idx, ontology = idx_ontology_pair
            try:
                score = self.evaluate_ontology(
                    ontology, context, source_data=source_data
                )
                if progress_callback is not None:
                    try:
                        progress_callback(idx, total, score)
                    except Exception as e:
                        self._log.warning(
                            f"Progress callback failed at index {idx}: {e}"
                        )
                return (idx, score)
            except Exception as e:
                self._log.error(f"Evaluation failed for ontology {idx}: {e}")
                return (idx, None)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = executor.map(
                _evaluate_with_index,
                enumerate(ontologies),
            )
            for idx, score in results:
                if score is not None:
                    scores[idx] = score

        # Filter out any None values (failed evaluations)
        valid_scores = [s for s in scores if s is not None]

        if not valid_scores:
            return {
                "scores": [],
                "mean_overall": 0.0,
                "min_overall": 0.0,
                "max_overall": 0.0,
                "count": 0,
            }

        overalls = [s.overall for s in valid_scores]
        return {
            "scores": valid_scores,
            "mean_overall": sum(overalls) / len(overalls),
            "min_overall": min(overalls),
            "max_overall": max(overalls),
            "count": len(valid_scores),
        }
    
    def compare_batch(
        self,
        ontologies: List[Dict[str, Any]],
        context: Any,
    ) -> List[Dict[str, Any]]:
        """Rank a list of ontologies by their overall critic score.

        Each ontology is evaluated with :meth:`evaluate_ontology` and the
        results are returned sorted from highest to lowest overall score.

        Args:
            ontologies: List of ontology dicts to compare.
            context: Shared evaluation context forwarded to each call.

        Returns:
            List of dicts, each containing:

            * ``"index"`` - original position in *ontologies* (0-based).
            * ``"rank"`` - 1-based rank (1 = best).
            * ``"overall"`` - overall :class:`CriticScore` value.
            * ``"score"`` - the full :class:`CriticScore` object.

        Example:
            >>> ranking = critic.compare_batch([ont_a, ont_b, ont_c], ctx)
            >>> print(ranking[0]["rank"], ranking[0]["overall"])
            1 0.87
        """
        scored = []
        for idx, ontology in enumerate(ontologies):
            score = self.evaluate_ontology(ontology, context)
            scored.append({"index": idx, "overall": score.overall, "score": score})
        scored.sort(key=lambda d: d["overall"], reverse=True)
        for rank, item in enumerate(scored, start=1):
            item["rank"] = rank
        return scored

    def calibrate_thresholds(
        self,
        scores: List["CriticScore"],
        percentile: float = 75.0,
    ) -> Dict[str, float]:
        """Compute recommended per-dimension thresholds from a history of scores.

        For each of the five evaluation dimensions the *percentile*-th value of
        the supplied scores is used as a recommended "good enough" threshold.
        The result is stored in ``self._calibrated_thresholds`` and also
        returned for immediate use.

        Args:
            scores: Non-empty list of :class:`CriticScore` objects (e.g., from
                :meth:`evaluate_batch`).
            percentile: Target percentile in (0, 100] used as threshold
                (default: 75 — top quartile).

        Returns:
            Dict mapping dimension name to its recommended threshold value.

        Raises:
            ValueError: If *scores* is empty or *percentile* is out of range.

        Example:
            >>> thresholds = critic.calibrate_thresholds(score_history, 80)
            >>> thresholds["completeness"]  # e.g. 0.72
            0.72
        """
        if not scores:
            raise ValueError("scores must be non-empty")
        if not (0 < percentile <= 100):
            raise ValueError(f"percentile must be in (0, 100]; got {percentile}")

        _DIMS = ("completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment")

        def _pct(values: List[float], p: float) -> float:
            sorted_vals = sorted(values)
            idx = (p / 100) * (len(sorted_vals) - 1)
            lo, hi = int(idx), min(int(idx) + 1, len(sorted_vals) - 1)
            frac = idx - lo
            return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

        thresholds = {
            dim: round(_pct([getattr(s, dim) for s in scores], percentile), 6)
            for dim in _DIMS
        }
        self._calibrated_thresholds = thresholds
        return thresholds

    def score_trend(
        self,
        scores: List["CriticScore"],
    ) -> str:
        """Determine the trend direction across a sequence of scores.

        Fits a simple linear regression (least-squares slope) to the
        :attr:`~CriticScore.overall` values.  Returns a human-readable
        direction label:

        * ``"improving"`` — positive slope > 0.01
        * ``"degrading"`` — negative slope < -0.01
        * ``"stable"`` — |slope| ≤ 0.01

        Args:
            scores: Ordered list of :class:`CriticScore` objects (at least 2).

        Returns:
            One of ``"improving"``, ``"stable"``, or ``"degrading"``.

        Raises:
            ValueError: If *scores* has fewer than 2 entries.

        Example:
            >>> direction = critic.score_trend(score_history)
            >>> direction in ("improving", "stable", "degrading")
            True
        """
        if len(scores) < 2:
            raise ValueError("score_trend requires at least 2 scores")

        ys = [s.overall for s in scores]
        n = len(ys)
        xs = list(range(n))
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denom = sum((x - mean_x) ** 2 for x in xs)
        slope = num / denom if denom != 0 else 0.0

        if slope > 0.01:
            return "improving"
        if slope < -0.01:
            return "degrading"
        return "stable"

    def emit_dimension_histogram(
        self,
        scores: List["CriticScore"],
        bins: int = 5,
    ) -> Dict[str, List[int]]:
        """Compute a frequency histogram for each quality dimension.

        Divides the [0, 1] range into *bins* equal-width buckets and counts how
        many scores fall into each bucket for every dimension.

        Args:
            scores: List of :class:`CriticScore` objects.
            bins: Number of histogram buckets (default: 5).

        Returns:
            Dict mapping dimension name to a list of *bins* bucket counts.

        Raises:
            ValueError: If *scores* is empty or *bins* < 1.

        Example:
            >>> hist = critic.emit_dimension_histogram(score_list, bins=4)
            >>> len(hist["completeness"]) == 4
            True
        """
        if not scores:
            raise ValueError("scores must be non-empty")
        if bins < 1:
            raise ValueError(f"bins must be >= 1; got {bins}")

        _DIMS = ("completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment")
        histogram: Dict[str, List[int]] = {}
        for dim in _DIMS:
            counts = [0] * bins
            for s in scores:
                val = max(0.0, min(1.0, getattr(s, dim)))
                bucket = min(int(val * bins), bins - 1)
                counts[bucket] += 1
            histogram[dim] = counts
        return histogram

    def compare_with_baseline(
        self,
        ontology: Dict[str, Any],
        baseline: Dict[str, Any],
        context: Any,
        source_data: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Compare *ontology* against a *baseline* and return the deltas.

        Both ontologies are evaluated with :meth:`evaluate_ontology` and the
        per-dimension deltas (``current - baseline``) are computed.

        Args:
            ontology: Candidate ontology to evaluate.
            baseline: Reference ontology to compare against.
            context: Evaluation context (passed straight through).
            source_data: Optional source text / data.

        Returns:
            Dict with keys:

            * ``"current_score"`` -- overall score for *ontology*.
            * ``"baseline_score"`` -- overall score for *baseline*.
            * ``"delta"`` -- ``current_score - baseline_score``.
            * ``"dimension_deltas"`` -- dict of per-dimension deltas.
            * ``"improved"`` -- True if delta > 0.

        Example:
            >>> cmp = critic.compare_with_baseline(new_ont, old_ont, ctx)
            >>> cmp["improved"]  # True if new is better
            True
        """
        current = self.evaluate_ontology(ontology, context, source_data)
        baseline_score = self.evaluate_ontology(baseline, context, source_data)
        dims = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"]
        dimension_deltas: Dict[str, float] = {
            d: round(getattr(current, d) - getattr(baseline_score, d), 6) for d in dims
        }
        delta = round(current.overall - baseline_score.overall, 6)
        return {
            "current_score": current.overall,
            "baseline_score": baseline_score.overall,
            "delta": delta,
            "dimension_deltas": dimension_deltas,
            "improved": delta > 0,
        }

    def summarize_batch_results(
        self,
        batch_result: List[Dict[str, Any]],
        context: Optional[Any] = None,
        source_data: Optional[Any] = None,
    ) -> List[str]:
        """Return a one-line summary string for each ontology in *batch_result*.

        Args:
            batch_result: List of ontology dicts to summarise.
            context: Optional shared evaluation context.  A minimal stub is
                created if *None*.
            source_data: Optional source text for evaluation.

        Returns:
            List of strings, one per ontology in the same order.

        Example:
            >>> lines = critic.summarize_batch_results([ont1, ont2], ctx)
            >>> len(lines) == 2
            True
        """
        if context is None:
            from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
                OntologyGenerationContext,
            )
            context = OntologyGenerationContext(
                data_source="batch", data_type="text", domain="general"
            )
        summaries: List[str] = []
        for i, ontology in enumerate(batch_result):
            try:
                score = self.evaluate_ontology(ontology, context, source_data)
                entity_count = len(ontology.get("entities") or [])
                line = (
                    f"[{i}] entities={entity_count} overall={score.overall:.3f} "
                    f"completeness={score.completeness:.3f} "
                    f"consistency={score.consistency:.3f}"
                )
            except Exception as exc:  # pragma: no cover
                line = f"[{i}] ERROR: {exc}"
            summaries.append(line)
        return summaries

    def compare_batch(
        self,
        ontologies: List[Dict[str, Any]],
        context: Any,
        source_data: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Rank a list of ontologies by overall score (descending).

        Each ontology in *ontologies* is evaluated and the results are
        returned sorted highest-first with the original index included.

        Args:
            ontologies: List of ontology dicts to compare.
            context: Evaluation context passed to :meth:`evaluate_ontology`.
            source_data: Optional source text.

        Returns:
            List of dicts sorted by ``"overall"`` descending, each with:

            * ``"rank"`` -- 1-based rank (1 = best).
            * ``"index"`` -- original position in *ontologies*.
            * ``"overall"`` -- overall critic score.
            * ``"completeness"`` -- completeness dimension.
            * ``"consistency"`` -- consistency dimension.

        Example:
            >>> ranked = critic.compare_batch([ont1, ont2, ont3], ctx)
            >>> ranked[0]["rank"]
            1
        """
        scored = []
        for idx, ontology in enumerate(ontologies):
            try:
                score = self.evaluate_ontology(ontology, context, source_data)
                scored.append({
                    "index": idx,
                    "overall": score.overall,
                    "completeness": score.completeness,
                    "consistency": score.consistency,
                    "score": score,
                })
            except Exception:  # pragma: no cover
                scored.append({"index": idx, "overall": 0.0, "completeness": 0.0, "consistency": 0.0, "score": None})
        scored.sort(key=lambda d: -d["overall"])
        for rank, entry in enumerate(scored, start=1):
            entry["rank"] = rank
        return scored

    def weighted_overall(
        self,
        score: "CriticScore",
        weights: Optional[Dict[str, float]] = None,
    ) -> float:
        """Compute a weighted overall score with caller-supplied dimension weights.

        The five dimensions are ``completeness``, ``consistency``, ``clarity``,
        ``granularity``, and ``domain_alignment``.  If *weights* is ``None``
        the module-level :data:`DIMENSION_WEIGHTS` defaults are used.  Weights
        are normalised so they sum to 1.0 before application.

        Args:
            score: :class:`CriticScore` to re-weight.
            weights: Optional mapping of dimension name → weight.  Missing
                dimensions get a weight of 0.

        Returns:
            Float in [0, 1].

        Raises:
            ValueError: If all weights are zero.

        Example:
            >>> w = {"completeness": 1.0, "consistency": 1.0}
            >>> val = critic.weighted_overall(score, w)
        """
        dims = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"]
        effective = dict(DIMENSION_WEIGHTS) if weights is None else {d: weights.get(d, 0.0) for d in dims}
        total_weight = sum(effective.values())
        if total_weight == 0:
            raise ValueError("All dimension weights are zero — cannot compute weighted overall.")
        return sum(getattr(score, d) * effective[d] / total_weight for d in dims)

    def evaluate_with_rubric(
        self,
        ontology: Dict[str, Any],
        context: Any,
        rubric: Dict[str, float],
        source_data: Optional[Any] = None,
    ) -> "CriticScore":
        """Evaluate an ontology with caller-supplied dimension weights.

        Runs a normal :meth:`evaluate_ontology` call and then rebuilds the
        overall score using *rubric* weights instead of the defaults.

        Args:
            ontology: Ontology dict to evaluate.
            context: Evaluation context.
            rubric: Mapping of dimension name to weight.  Recognised keys:
                ``completeness``, ``consistency``, ``clarity``,
                ``granularity``, ``domain_alignment``.  Unknown keys are
                silently ignored.  Weights need not sum to 1 -- they are
                normalised internally.
            source_data: Optional source text forwarded to the evaluator.

        Returns:
            A :class:`CriticScore` whose ``overall`` reflects *rubric* weights.

        Raises:
            ValueError: If *rubric* is empty or all weights are zero.

        Example:
            >>> rubric = {"completeness": 0.5, "consistency": 0.5}
            >>> score = critic.evaluate_with_rubric(ontology, ctx, rubric)
        """
        _DIMS = ("completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment")
        base = self.evaluate_ontology(ontology, context, source_data=source_data)

        filtered = {k: float(v) for k, v in rubric.items() if k in _DIMS and float(v) > 0}
        if not filtered:
            raise ValueError("rubric must contain at least one recognised dimension with a positive weight")

        total_w = sum(filtered.values())
        weighted = sum(getattr(base, dim) * w for dim, w in filtered.items()) / total_w

        import dataclasses as _dc
        updated_metadata = dict(base.metadata)
        updated_metadata["rubric_overall"] = round(weighted, 6)
        updated_metadata["rubric"] = dict(filtered)
        return _dc.replace(base, metadata=updated_metadata)

    def compare_ontologies(
        self,
        ontology1: Dict[str, Any],
        ontology2: Dict[str, Any],
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Compare two ontologies and identify improvements.

        Evaluates both ontologies and provides a comparative analysis,
        highlighting which ontology performs better in each dimension
        and identifying specific improvements.
        
        Args:
            ontology1: First ontology to compare
            ontology2: Second ontology to compare
            context: Optional context for evaluation
            
        Returns:
            Dictionary with comparative analysis:
                - 'score1': Score for ontology1
                - 'score2': Score for ontology2
                - 'better': Which ontology is better overall
                - 'improvements': List of specific improvements in better ontology
                - 'regressions': List of specific regressions
                
        Example:
            >>> comparison = critic.compare_ontologies(old_ontology, new_ontology)
            >>> if comparison['better'] == 'ontology2':
            ...     print("New ontology is better!")
            ...     print("Improvements:", comparison['improvements'])
        """
        self._log.info("Comparing two ontologies")
        
        # Evaluate both ontologies
        score1 = self.evaluate_ontology(ontology1, context) if context else None
        score2 = self.evaluate_ontology(ontology2, context) if context else None
        
        # Determine which is better
        better = 'ontology2' if (score2 and score1 and score2.overall > score1.overall) else 'ontology1'
        
        # Identify improvements and regressions
        improvements = []
        regressions = []
        
        if score1 and score2:
            dimensions = ['completeness', 'consistency', 'clarity', 'granularity', 'domain_alignment']
            for dim in dimensions:
                val1 = getattr(score1, dim)
                val2 = getattr(score2, dim)
                if val2 > val1:
                    improvements.append(f"{dim}: {val1:.2f} -> {val2:.2f}")
                elif val2 < val1:
                    regressions.append(f"{dim}: {val1:.2f} -> {val2:.2f}")
        
        return {
            'score1': score1.to_dict() if score1 else None,
            'score2': score2.to_dict() if score2 else None,
            'better': better,
            'improvements': improvements,
            'regressions': regressions,
        }

    def compare_versions(
        self,
        v1: Dict[str, Any],
        v2: Dict[str, Any],
        context: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Compare two ontology versions and return per-dimension score diffs.

        This is an alias for :meth:`compare_ontologies` with a cleaner return
        that also includes per-dimension delta values (``delta_<dim>``).

        Args:
            v1: First (older) ontology version.
            v2: Second (newer) ontology version.
            context: Optional evaluation context.

        Returns:
            Dict with keys from :meth:`compare_ontologies` plus:
            - ``delta_<dim>``: float difference (v2 - v1) for each of the 5 dimensions
            - ``delta_overall``: overall score difference (v2 - v1)
        """
        result = self.compare_ontologies(v1, v2, context)
        if result.get("score1") and result.get("score2"):
            dims = ("completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment")
            for dim in dims:
                result[f"delta_{dim}"] = round(
                    result["score2"].get(dim, 0.0) - result["score1"].get(dim, 0.0), 4
                )
            result["delta_overall"] = round(
                result["score2"].get("overall", 0.0) - result["score1"].get("overall", 0.0), 4
            )
        return result

    def _evaluate_completeness(
        self,
        ontology: Dict[str, Any],
        context: Any,
        source_data: Optional[Any]
    ) -> float:
        """
        Evaluate completeness of ontology.
        
        Assesses how well the ontology covers key concepts and relationships
        in the domain and source data.

        When *source_data* is a non-empty string, an extra sub-score measures
        what fraction of extracted entity texts appear verbatim in the source.
        """
        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])

        if not entities:
            return 0.0

        # Sub-score 1: entity count (target >= 10 for "complete")
        entity_count_score = min(len(entities) / 10.0, 1.0)

        # Sub-score 2: relationship density (>= 1 rel per entity)
        rel_density_score = min(len(relationships) / max(len(entities), 1), 1.0)

        # Sub-score 3: entity-type diversity (at least 3 distinct types)
        types = {e.get('type') for e in entities if isinstance(e, dict) and e.get('type')}
        diversity_score = min(len(types) / 3.0, 1.0)

        # Sub-score 4: orphan penalty (entities with no relationships)
        entity_ids_in_rels: set = set()
        for rel in relationships:
            if isinstance(rel, dict):
                entity_ids_in_rels.add(rel.get('source_id'))
                entity_ids_in_rels.add(rel.get('target_id'))
        entity_ids = {e.get('id') for e in entities if isinstance(e, dict)}
        orphan_ratio = len(entity_ids - entity_ids_in_rels) / max(len(entity_ids), 1)
        orphan_penalty = max(0.0, 1.0 - orphan_ratio)

        # Sub-score 5 (optional): source coverage -- fraction of entity texts found in source
        source_coverage_score: Optional[float] = None
        if isinstance(source_data, str) and source_data:
            src_lower = source_data.lower()
            covered = sum(
                1 for e in entities
                if isinstance(e, dict)
                and (e.get('text') or '').lower()
                and (e.get('text') or '').lower() in src_lower
            )
            source_coverage_score = covered / len(entities)

        if source_coverage_score is not None:
            score = (
                entity_count_score * 0.25
                + rel_density_score * 0.25
                + diversity_score * 0.15
                + orphan_penalty * 0.15
                + source_coverage_score * 0.20
            )
        else:
            score = (
                entity_count_score * 0.3
                + rel_density_score * 0.3
                + diversity_score * 0.2
                + orphan_penalty * 0.2
            )
        return round(min(max(score, 0.0), 1.0), 4)

    def _evaluate_consistency(
        self,
        ontology: Dict[str, Any],
        context: Any
    ) -> float:
        """
        Evaluate internal logical consistency.
        
        Checks for dangling references, duplicate IDs, and circular
        is_a / part_of dependency chains.
        """
        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])

        entity_ids = {e.get('id') for e in entities if isinstance(e, dict) and e.get('id')}

        # Penalty: dangling references
        invalid_refs = 0
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            if rel.get('source_id') not in entity_ids:
                invalid_refs += 1
            if rel.get('target_id') not in entity_ids:
                invalid_refs += 1

        total_ref_slots = len(relationships) * 2
        ref_score = 1.0 if total_ref_slots == 0 else max(0.0, 1.0 - invalid_refs / total_ref_slots)

        # Penalty: duplicate entity IDs
        all_ids = [e.get('id') for e in entities if isinstance(e, dict) and e.get('id')]
        dup_ratio = (len(all_ids) - len(set(all_ids))) / max(len(all_ids), 1)
        dup_score = 1.0 - dup_ratio

        # Penalty: circular is_a / part_of chains (DFS cycle detection)
        hierarchy_adj: dict[str, list[str]] = {}
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            if rel.get('type') in ('is_a', 'part_of'):
                src = rel.get('source_id')
                tgt = rel.get('target_id')
                if src and tgt:
                    hierarchy_adj.setdefault(src, []).append(tgt)

        def _has_cycle(graph: dict) -> bool:
            visited: set = set()
            rec_stack: set = set()

            def _dfs(node: str) -> bool:
                visited.add(node)
                rec_stack.add(node)
                for nb in graph.get(node, []):
                    if nb not in visited:
                        if _dfs(nb):
                            return True
                    elif nb in rec_stack:
                        return True
                rec_stack.discard(node)
                return False

            return any(_dfs(n) for n in graph if n not in visited)

        cycle_penalty = 0.15 if (hierarchy_adj and _has_cycle(hierarchy_adj)) else 0.0

        score = ref_score * 0.5 + dup_score * 0.3 + (1.0 - cycle_penalty) * 0.2
        return round(min(max(score, 0.0), 1.0), 4)

    def _evaluate_clarity(
        self,
        ontology: Dict[str, Any],
        context: Any
    ) -> float:
        """
        Evaluate clarity of entity definitions and naming conventions.

        Scores based on:
        - property completeness (entities with >= 1 property)
        - naming convention consistency (camelCase / snake_case / PascalCase)
        - non-empty text field
        - short-name penalty (entity texts < 3 chars suggest poor extraction)
        - confidence coverage (entities with explicit confidence > 0)
        """
        import re as _re

        entities = ontology.get('entities', [])

        if not entities:
            return 0.0

        # Sub-score 1: property completeness (entities with >= 1 property)
        with_props = sum(1 for e in entities if isinstance(e, dict) and e.get('properties'))
        prop_score = with_props / len(entities)

        # Sub-score 2: naming convention consistency (all camelCase OR all snake_case)
        names = [e.get('text', '') or e.get('id', '') for e in entities if isinstance(e, dict)]
        camel = sum(1 for n in names if _re.match(r'^[a-z][a-zA-Z0-9]*$', n))
        snake = sum(1 for n in names if _re.match(r'^[a-z][a-z0-9_]*$', n))
        pascal = sum(1 for n in names if _re.match(r'^[A-Z][a-zA-Z0-9]*$', n))
        dominant = max(camel, snake, pascal)
        naming_score = dominant / max(len(names), 1)

        # Sub-score 3: non-empty text field
        with_text = sum(1 for e in entities if isinstance(e, dict) and e.get('text'))
        text_score = with_text / len(entities)

        # Sub-score 4: short-name penalty -- texts with < 3 chars suggest noisy extraction
        short_names = sum(
            1 for e in entities
            if isinstance(e, dict) and len((e.get('text') or e.get('id') or '').strip()) < 3
        )
        short_penalty = short_names / len(entities)

        # Sub-score 5: confidence coverage -- fraction with explicit confidence > 0
        with_confidence = sum(
            1 for e in entities
            if isinstance(e, dict) and isinstance(e.get('confidence'), (int, float)) and e['confidence'] > 0
        )
        confidence_score = with_confidence / len(entities)

        score = (
            prop_score * 0.3
            + naming_score * 0.2
            + text_score * 0.2
            + confidence_score * 0.2
            - short_penalty * 0.1
        )
        return round(min(max(score, 0.0), 1.0), 4)

    def _evaluate_granularity(
        self,
        ontology: Dict[str, Any],
        context: Any
    ) -> float:
        """
        Evaluate appropriateness of detail level.
        
        Scores based on average properties-per-entity and relationship-to-entity ratio.
        """
        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])

        if not entities:
            return 0.0

        # Target: ~3 properties per entity is "good granularity"
        target_props = 3.0
        prop_counts = [
            len(e.get('properties', {}))
            for e in entities if isinstance(e, dict)
        ]
        avg_props = sum(prop_counts) / max(len(prop_counts), 1)
        prop_score = min(avg_props / target_props, 1.0)

        # Target: ~1.5 relationships per entity
        target_rels = 1.5
        rel_ratio = len(relationships) / max(len(entities), 1)
        rel_score = min(rel_ratio / target_rels, 1.0)

        # Penalty for entities with zero properties (too coarse)
        no_props = sum(1 for c in prop_counts if c == 0)
        coarseness_penalty = no_props / max(len(entities), 1) * 0.3

        score = prop_score * 0.45 + rel_score * 0.4 - coarseness_penalty
        return round(min(max(score, 0.0), 1.0), 4)

    def _evaluate_domain_alignment(
        self,
        ontology: Dict[str, Any],
        context: Any
    ) -> float:
        """
        Evaluate how well entity types and relationship types align with domain vocabulary.
        """
        _DOMAIN_VOCAB: dict[str, set[str]] = {
            'legal': {'obligation', 'party', 'contract', 'clause', 'breach', 'liability', 'penalty', 'jurisdiction', 'provision', 'agreement'},
            'medical': {'patient', 'diagnosis', 'treatment', 'symptom', 'medication', 'procedure', 'physician', 'condition', 'dosage', 'outcome'},
            'technical': {'component', 'service', 'api', 'endpoint', 'module', 'interface', 'dependency', 'version', 'protocol', 'event'},
            'financial': {'asset', 'liability', 'transaction', 'account', 'balance', 'payment', 'interest', 'principal', 'collateral', 'risk'},
            'general': {'person', 'organization', 'location', 'date', 'event', 'concept', 'action', 'property', 'relation', 'category'},
        }

        domain = (getattr(context, 'domain', None) or ontology.get('domain', 'general')).lower()
        vocab = _DOMAIN_VOCAB.get(domain, _DOMAIN_VOCAB['general'])

        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])

        if not entities:
            return 0.5

        # Check what fraction of entity types / rel types are in domain vocab
        ent_types = [e.get('type', '').lower() for e in entities if isinstance(e, dict)]
        rel_types = [r.get('type', '').lower() for r in relationships if isinstance(r, dict)]
        all_terms = ent_types + rel_types

        if not all_terms:
            return 0.5

        hits = sum(
            1 for t in all_terms
            if any(v in t or t in v for v in vocab)
        )
        score = hits / len(all_terms)
        return round(min(max(score, 0.0), 1.0), 4)

    def _evaluate_provenance(
        self,
        ontology: Dict[str, Any],
    ) -> float:
        """Evaluate whether entities have source-span provenance annotations.

        Checks each entity for a ``'source_span'``, ``'span'``, or
        ``'source'`` property.  Entities with provenance annotations score
        1.0; those without score 0.0.  Returns the fraction of annotated
        entities.

        Args:
            ontology: Ontology dict with an ``'entities'`` list.

        Returns:
            Float in [0, 1].  ``0.5`` when no entities are present (neutral).
        """
        entities = [e for e in (ontology.get("entities") or []) if isinstance(e, dict)]
        if not entities:
            return 0.5

        _provenance_keys = {"source_span", "span", "source", "source_doc_index", "provenance"}
        annotated = sum(
            1 for ent in entities
            if (
                _provenance_keys & set(ent.keys())
                or _provenance_keys & set((ent.get("properties") or {}).keys())
            )
        )
        return round(annotated / len(entities), 4)

    def _evaluate_relationship_coherence(
        self,
        ontology: Dict[str, Any],
        context: Any
    ) -> float:
        """
        Evaluate the semantic coherence and quality of relationships.
        
        Checks for well-formed relationship types, appropriate directionality,
        balanced relationship distribution, and semantic consistency.
        
        Sub-scores:
        1. Type quality: Are relationship types meaningful and well-formed?
        2. Directionality: Are relationships appropriately directional vs symmetric?
        3. Distribution balance: Is there good variety in relationship types?
        4. Semantic consistency: Do relationship types match entity types?
        
        Returns:
            Float in [0, 1] indicating relationship coherence quality.
        """
        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])

        if not relationships:
            # No relationships to evaluate
            return 0.3 if entities else 0.5

        # Sub-score 1: Type quality - check for meaningful relationship types
        # Good types: 'has_part', 'causes', 'implements', 'manages'
        # Poor types: generic ('relates_to'), empty, or single chars
        rel_types = [r.get('type', '') for r in relationships if isinstance(r, dict)]
        _GENERIC_RELS = {'relates_to', 'related_to', 'links', 'connected', 'associated', 'rel'}
        _MEANINGFUL_PATTERNS = {
            'has_', 'is_', 'contains_', 'performs_', 'implements_', 'manages_',
            'causes_', 'affects_', 'depends_on', 'requires_', 'uses_', 'provides_'
        }
        
        meaningful = sum(
            1 for rt in rel_types
            if rt and len(rt) > 3 and rt.lower() not in _GENERIC_RELS
            and any(pattern in rt.lower() for pattern in _MEANINGFUL_PATTERNS)
        )
        specific_but_not_generic = sum(
            1 for rt in rel_types
            if rt and len(rt) > 3 and rt.lower() not in _GENERIC_RELS
        )
        type_quality_score = (
            (meaningful / len(rel_types)) * 0.7 +
            (specific_but_not_generic / len(rel_types)) * 0.3
        ) if rel_types else 0.0

        # Sub-score 2: Directionality - check for appropriate use of directed edges
        # Asymmetric types should be directed: 'causes', 'is_part_of', 'manages'
        # Symmetric types can be bidirectional: 'collaborates_with', 'similar_to'
        _SYMMETRIC_PATTERNS = {'similar', 'collaborates', 'related', 'connected', 'associated'}
        directed_count = sum(
            1 for r in relationships
            if isinstance(r, dict)
            and r.get('source_id') != r.get('target_id')
        )
        directionality_score = directed_count / len(relationships) if relationships else 0.5

        # Sub-score 3: Distribution balance - variety in relationship types
        unique_types = set(rt for rt in rel_types if rt)
        # Good: 3+ unique types for 10+ relationships
        # Excellent: 5+ unique types for 20+ relationships
        if len(relationships) < 5:
            distribution_score = min(len(unique_types) / 2.0, 1.0)
        elif len(relationships) < 10:
            distribution_score = min(len(unique_types) / 3.0, 1.0)
        else:
            distribution_score = min(len(unique_types) / 5.0, 1.0)

        # Sub-score 4: Semantic consistency - do relationships make sense for entity types?
        # Check if relationship types align with connected entity types
        # Example: 'manages' should connect Person/Organization entities, not Concept/Location
        _TYPE_AFFINITY: Dict[str, set] = {
            'manages': {'person', 'organization', 'manager', 'team', 'department'},
            'located_in': {'location', 'place', 'address', 'city', 'region'},
            'has_symptom': {'patient', 'person', 'condition', 'disease'},
            'implements': {'component', 'module', 'service', 'interface', 'class'},
            'part_of': {'component', 'organization', 'location', 'structure'},
        }
        
        entity_type_map = {
            e.get('id'): (e.get('type', '') or '').lower()
            for e in entities if isinstance(e, dict) and e.get('id')
        }
        
        coherent_relationships = 0
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            rel_type = (rel.get('type', '') or '').lower()
            src_id = rel.get('source_id')
            tgt_id = rel.get('target_id')
            
            if not rel_type or not src_id or not tgt_id:
                continue
                
            # Check if this relationship type has expected entity type affinities
            for pattern, expected_types in _TYPE_AFFINITY.items():
                if pattern in rel_type:
                    src_type = entity_type_map.get(src_id, '')
                    tgt_type = entity_type_map.get(tgt_id, '')
                    # At least one entity should match expected types
                    if any(et in src_type or et in tgt_type for et in expected_types):
                        coherent_relationships += 1
                        break
            else:
                # No specific affinity rule - count as neutral (0.5)
                coherent_relationships += 0.5
        
        semantic_consistency_score = (
            coherent_relationships / len(relationships) if relationships else 0.5
        )

        # Weighted combination
        overall = (
            type_quality_score * 0.35 +
            directionality_score * 0.20 +
            distribution_score * 0.25 +
            semantic_consistency_score * 0.20
        )
        
        return round(min(max(overall, 0.0), 1.0), 4)

    def _identify_strengths(
        self,
        completeness: float,
        consistency: float,
        clarity: float,
        granularity: float,
        relationship_coherence: float,
        domain_alignment: float
    ) -> List[str]:
        """Identify ontology strengths based on dimension scores."""
        strengths = []
        
        threshold = 0.8
        
        if completeness >= threshold:
            strengths.append("Comprehensive entity and relationship coverage")
        if consistency >= threshold:
            strengths.append("Strong internal logical consistency")
        if clarity >= threshold:
            strengths.append("Clear and well-defined entities")
        if granularity >= threshold:
            strengths.append("Appropriate level of detail")
        if relationship_coherence >= threshold:
            strengths.append("High-quality, semantically coherent relationships")
        if domain_alignment >= threshold:
            strengths.append("Good adherence to domain conventions")
        
        return strengths
    
    def _identify_weaknesses(
        self,
        completeness: float,
        consistency: float,
        clarity: float,
        granularity: float,
        relationship_coherence: float,
        domain_alignment: float
    ) -> List[str]:
        """Identify ontology weaknesses based on dimension scores."""
        weaknesses = []
        
        threshold = 0.6
        
        if completeness < threshold:
            weaknesses.append("Incomplete coverage of key concepts")
        if consistency < threshold:
            weaknesses.append("Logical inconsistencies detected")
        if clarity < threshold:
            weaknesses.append("Unclear or ambiguous entity definitions")
        if granularity < threshold:
            weaknesses.append("Inappropriate level of detail")
        if relationship_coherence < threshold:
            weaknesses.append("Poor relationship quality or semantic incoherence")
        if domain_alignment < threshold:
            weaknesses.append("Poor alignment with domain conventions")
        
        return weaknesses

    def score_batch_summary(self, scores: List["CriticScore"]) -> Dict[str, Any]:
        """Return descriptive statistics for a list of :class:`CriticScore` objects.

        Args:
            scores: Non-empty list of scores to summarise.

        Returns:
            Dict with keys ``"count"``, ``"mean_overall"``, ``"min_overall"``,
            ``"max_overall"``, ``"std_overall"`` (population std).

        Raises:
            ValueError: If *scores* is empty.

        Example:
            >>> summary = critic.score_batch_summary([score1, score2])
            >>> summary["count"]
            2
        """
        if not scores:
            raise ValueError("score_batch_summary requires at least one score")
        overalls = [s.overall for s in scores]
        count = len(overalls)
        mean = sum(overalls) / count
        variance = sum((x - mean) ** 2 for x in overalls) / count
        import math as _math
        return {
            "count": count,
            "mean_overall": round(mean, 6),
            "min_overall": round(min(overalls), 6),
            "max_overall": round(max(overalls), 6),
            "std_overall": round(_math.sqrt(variance), 6),
        }

    def dimension_report(self, score: "CriticScore") -> str:
        """Return a multi-line human-readable breakdown of all five dimensions.

        Args:
            score: :class:`CriticScore` to report on.

        Returns:
            Multi-line string with one line per dimension plus an overall line.

        Example:
            >>> print(critic.dimension_report(score))
            completeness      : 0.750
            ...
        """
        dims = [
            ("completeness", score.completeness),
            ("consistency", score.consistency),
            ("clarity", score.clarity),
            ("granularity", score.granularity),
            ("domain_alignment", score.domain_alignment),
        ]
        lines = [f"{name:18s}: {val:.3f}" for name, val in dims]
        lines.append(f"{'overall':18s}: {score.overall:.3f}")
        return "\n".join(lines)

    def score_delta(
        self,
        score_a: "CriticScore",
        score_b: "CriticScore",
    ) -> Dict[str, float]:
        """Return per-dimension delta (score_b - score_a) for two CriticScores.

        Args:
            score_a: Baseline score.
            score_b: Target score.

        Returns:
            Dict mapping dimension name → (score_b.dim - score_a.dim), rounded
            to 6 decimal places.  Includes ``"overall"`` as well as the five
            individual dimensions.

        Example:
            >>> delta = critic.score_delta(old_score, new_score)
            >>> delta["overall"] > 0  # improvement
            True
        """
        dims = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment", "overall"]
        return {d: round(getattr(score_b, d) - getattr(score_a, d), 6) for d in dims}

    def critical_weaknesses(
        self,
        score: "CriticScore",
        threshold: float = 0.5,
    ) -> Dict[str, float]:
        """Return dimensions whose value is below *threshold*.

        Args:
            score: A :class:`CriticScore` to inspect.
            threshold: Dimensions strictly below this value are considered
                critical weaknesses.  Defaults to ``0.5``.

        Returns:
            Dict mapping dimension name → score value for each weak dimension.
            Empty dict means no critical weaknesses.

        Example:
            >>> weak = critic.critical_weaknesses(score)
            >>> all(v < 0.5 for v in weak.values())
            True
        """
        dims = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"]
        return {d: getattr(score, d) for d in dims if getattr(score, d) < threshold}

    def top_dimension(self, score: "CriticScore") -> str:
        """Return the name of the dimension with the highest value.

        Args:
            score: A :class:`CriticScore` to inspect.

        Returns:
            Dimension name string (one of: ``completeness``, ``consistency``,
            ``clarity``, ``granularity``, ``domain_alignment``).

        Example:
            >>> critic.top_dimension(score)
            'domain_alignment'
        """
        dims = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"]
        return max(dims, key=lambda d: getattr(score, d))

    def bottom_dimension(self, score: "CriticScore") -> str:
        """Return the name of the dimension with the lowest value.

        Args:
            score: A :class:`CriticScore` to inspect.

        Returns:
            Dimension name string (one of the five standard dimensions).

        Example:
            >>> critic.bottom_dimension(score)
            'granularity'
        """
        dims = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"]
        return min(dims, key=lambda d: getattr(score, d))

    def score_range(
        self,
        scores: List["CriticScore"],
    ) -> tuple:
        """Return the (min, max) ``overall`` values from a list of CriticScores.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Tuple ``(min_overall, max_overall)``.  Returns ``(0.0, 0.0)`` for
            an empty list.

        Example:
            >>> lo, hi = critic.score_range([s1, s2, s3])
        """
        if not scores:
            return (0.0, 0.0)
        overalls = [s.overall for s in scores]
        return (min(overalls), max(overalls))

    def improve_score_suggestion(self, score: "CriticScore") -> str:
        """Return the name of the dimension most needing improvement.

        Returns the dimension with the lowest value — the best candidate for
        focused improvement effort.

        Args:
            score: A :class:`CriticScore` to inspect.

        Returns:
            Dimension name string.

        Example:
            >>> critic.improve_score_suggestion(score)
            'granularity'
        """
        return self.bottom_dimension(score)

    def dimension_gap(
        self,
        score: "CriticScore",
        target: float = 1.0,
    ) -> Dict[str, float]:
        """Return how far each dimension is from *target*.

        Args:
            score: A :class:`CriticScore` to inspect.
            target: Desired value for all dimensions (defaults to 1.0).

        Returns:
            Dict mapping dimension name → (target - dim_value), rounded to 6
            decimal places.  Positive means below target (needs improvement).

        Example:
            >>> gaps = critic.dimension_gap(score)
            >>> all(v >= 0 for v in gaps.values())
            True
        """
        dims = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"]
        return {d: round(target - getattr(score, d), 6) for d in dims}

    def dimension_z_scores(self, score: "CriticScore") -> Dict[str, float]:
        """Return z-scores for each dimension relative to their history/baseline.

        This method requires that the critic has historical context or configuration
        of baseline/mean/std for each dimension. For now, it returns normalized
        distance scores based on the current score's dimensions.

        Args:
            score: A :class:`CriticScore` to analyze.

        Returns:
            Dict mapping dimension name → z-score (float). Each z-score expresses
            how far a dimension is from "center" (0.5 nominal), measured in
            units of 0.2 (representing 1 std dev zone).

        Example:
            >>> critic = OntologyCritic()
            >>> score = CriticScore(completeness=0.7, consistency=0.5, ...)
            >>> z_scores = critic.dimension_z_scores(score)
            >>> z_scores['completeness']
            1.0
        """
        dims = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"]
        nominal = 0.5  # nominal center (0 to 1 scale)
        std_dev = 0.2  # approximate std dev zone
        
        z_scores = {}
        for dim in dims:
            val = getattr(score, dim, 0.5)
            if std_dev > 0:
                z_scores[dim] = round((val - nominal) / std_dev, 4)
            else:
                z_scores[dim] = 0.0
        
        return z_scores

    def worst_score(self, scores: List["CriticScore"]) -> Optional["CriticScore"]:
        """Return the :class:`CriticScore` with the lowest ``overall`` value.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            The score with the minimum ``overall``, or ``None`` for an empty list.

        Example:
            >>> critic.worst_score([s1, s2, s3])
        """
        if not scores:
            return None
        return min(scores, key=lambda s: s.overall)

    def best_score(self, scores: List["CriticScore"]) -> Optional["CriticScore"]:
        """Return the :class:`CriticScore` with the highest ``overall`` value.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            The score with the maximum ``overall``, or ``None`` for an empty list.

        Example:
            >>> critic.best_score([s1, s2, s3])
        """
        if not scores:
            return None
        return max(scores, key=lambda s: s.overall)

    def score_mean(self, scores: List["CriticScore"]) -> float:
        """Return the mean ``overall`` value across *scores*.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Mean of ``overall`` values, or ``0.0`` for an empty list.

        Example:
            >>> critic.score_mean([s1, s2])
            0.72
        """
        if not scores:
            return 0.0
        return sum(s.overall for s in scores) / len(scores)

    def score_std(self, scores: List["CriticScore"]) -> float:
        """Return the standard deviation of ``overall`` values across *scores*.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Population standard deviation of ``overall`` values, or ``0.0``
            when the list has fewer than 2 entries.

        Example:
            >>> critic.score_std([s1, s2])
            0.1
        """
        if len(scores) < 2:
            return 0.0
        import math as _math
        mean = sum(s.overall for s in scores) / len(scores)
        variance = sum((s.overall - mean) ** 2 for s in scores) / len(scores)
        return _math.sqrt(variance)

    def dimension_scores(self, score: "CriticScore") -> Dict[str, float]:
        """Return a dict mapping each dimension name to its score value.

        Args:
            score: A :class:`CriticScore` to inspect.

        Returns:
            Dict with keys ``completeness``, ``consistency``, ``clarity``,
            ``granularity``, ``domain_alignment``, and ``overall``.

        Example:
            >>> d = critic.dimension_scores(score)
            >>> "completeness" in d
            True
        """
        return {
            "completeness": score.completeness,
            "consistency": score.consistency,
            "clarity": score.clarity,
            "granularity": score.granularity,
            "domain_alignment": score.domain_alignment,
            "overall": score.overall,
        }

    def passes_all(self, scores: List["CriticScore"], threshold: float = 0.6) -> bool:
        """Return ``True`` if every score in *scores* passes *threshold*.

        Args:
            scores: List of :class:`CriticScore` objects.
            threshold: Minimum ``overall`` required.  Defaults to 0.6.

        Returns:
            ``True`` when all scores have ``overall >= threshold``, or when
            *scores* is empty.

        Example:
            >>> critic.passes_all([s1, s2])
            True
        """
        return all(s.is_passing(threshold) for s in scores)

    def all_pass(self, scores: List["CriticScore"], threshold: float = 0.6) -> bool:
        """Strict variant of :meth:`passes_all` using ``overall > threshold``.

        Args:
            scores: List of :class:`CriticScore` objects.
            threshold: Strict lower bound for ``overall``. Defaults to 0.6.

        Returns:
            ``True`` when every score has ``overall > threshold`` (or when
            *scores* is empty), else ``False``.
        """
        return all(s.overall > threshold for s in scores)

    def score_range(self, scores: List["CriticScore"]) -> tuple:
        """Return a ``(min, max)`` tuple of ``overall`` values from *scores*.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Tuple ``(min_overall, max_overall)``, or ``(0.0, 0.0)`` for an
            empty list.

        Example:
            >>> lo, hi = critic.score_range([s1, s2, s3])
        """
        if not scores:
            return (0.0, 0.0)
        vals = [s.overall for s in scores]
        return (min(vals), max(vals))

    def score_improvement(self, score_a: "CriticScore", score_b: "CriticScore") -> float:
        """Return the improvement in ``overall`` from *score_a* to *score_b*.

        A positive value means *score_b* is better than *score_a*.

        Args:
            score_a: Baseline score.
            score_b: Comparison score.

        Returns:
            ``score_b.overall - score_a.overall``

        Example:
            >>> critic.score_improvement(old_score, new_score)
            0.05
        """
        return score_b.overall - score_a.overall

    def above_threshold_count(self, scores: List["CriticScore"], threshold: float = 0.6) -> int:
        """Return the count of scores with ``overall >= threshold``.

        Args:
            scores: List of :class:`CriticScore` objects.
            threshold: Minimum acceptable overall score.  Defaults to 0.6.

        Returns:
            Integer count of passing scores.

        Example:
            >>> critic.above_threshold_count([s1, s2, s3], threshold=0.7)
            2
        """
        return sum(1 for s in scores if s.overall >= threshold)

    def top_n_scores(self, scores: List["CriticScore"], n: int = 5) -> List["CriticScore"]:
        """Return the top *n* :class:`CriticScore` objects by ``overall`` value.

        Args:
            scores: List of :class:`CriticScore` objects.
            n: Number of top scores to return.  Defaults to 5.

        Returns:
            List of up to *n* :class:`CriticScore` objects in descending order.

        Example:
            >>> top3 = critic.top_n_scores(scores, n=3)
            >>> len(top3) <= 3
            True
        """
        return sorted(scores, key=lambda s: s.overall, reverse=True)[:n]

    def evaluate_list(
        self,
        ontologies: List[Dict[str, Any]],
        context: Any,
    ) -> List["CriticScore"]:
        """Evaluate each ontology in *ontologies* and return a list of scores.

        This is a convenience batch wrapper around :meth:`evaluate_ontology`.

        Args:
            ontologies: List of ontology dicts to evaluate.
            context: Shared :class:`OntologyGenerationContext` passed to each
                individual evaluation.

        Returns:
            List of :class:`CriticScore` objects in the same order as the
            input.  An empty list is returned for an empty input.

        Example:
            >>> scores = critic.evaluate_list([ont1, ont2], ctx)
            >>> len(scores) == 2
            True
        """
        return [self.evaluate_ontology(ont, context) for ont in ontologies]

    def score_distribution(self, scores: List["CriticScore"]) -> Dict[str, float]:
        """Return summary statistics for a list of :class:`CriticScore` overall values.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Dict with keys ``'mean'``, ``'std'``, ``'min'``, ``'max'``, ``'count'``.
            All numeric values are ``0.0`` for an empty list (count is 0).

        Example:
            >>> dist = critic.score_distribution([s1, s2])
            >>> dist.keys()
            dict_keys(['mean', 'std', 'min', 'max', 'count'])
        """
        if not scores:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "count": 0}
        vals = [s.overall for s in scores]
        n = len(vals)
        mean = sum(vals) / n
        std = (sum((v - mean) ** 2 for v in vals) / n) ** 0.5
        return {
            "mean": mean,
            "std": std,
            "min": min(vals),
            "max": max(vals),
            "count": n,
        }

    def score_gap(self, scores: List["CriticScore"]) -> float:
        """Return the difference between the highest and lowest ``overall`` values.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            ``max(overall) - min(overall)``; ``0.0`` for an empty or
            single-element list.

        Example:
            >>> critic.score_gap([s_low, s_high])
            0.4
        """
        if len(scores) < 2:
            return 0.0
        vals = [s.overall for s in scores]
        return max(vals) - min(vals)

    def median_score(self, scores: List["CriticScore"]) -> float:
        """Return the median ``overall`` value across *scores*.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Median of ``overall`` values, or ``0.0`` for an empty list.
            For an even-length list the average of the two middle values
            is returned.

        Example:
            >>> critic.median_score([s1, s2, s3])
        """
        if not scores:
            return 0.0
        vals = sorted(s.overall for s in scores)
        n = len(vals)
        mid = n // 2
        if n % 2 == 1:
            return vals[mid]
        return (vals[mid - 1] + vals[mid]) / 2.0

    def scores_above_threshold(
        self, scores: List["CriticScore"], threshold: float = 0.6
    ) -> List["CriticScore"]:
        """Return all scores whose ``overall`` value exceeds *threshold*.

        Args:
            scores: List of :class:`CriticScore` objects.
            threshold: Minimum ``overall`` (exclusive). Defaults to 0.6.

        Returns:
            Filtered list of :class:`CriticScore` objects where
            ``overall > threshold``.  Returns an empty list for empty input.

        Example:
            >>> passing = critic.scores_above_threshold(scores, threshold=0.7)
        """
        return [s for s in scores if s.overall > threshold]

    def best_dimension(self, score: "CriticScore") -> str:
        """Return the name of the highest-scoring dimension in *score*.

        Args:
            score: A :class:`CriticScore` object.

        Returns:
            One of ``'completeness'``, ``'consistency'``, ``'clarity'``,
            ``'granularity'``, ``'domain_alignment'``.

        Example:
            >>> critic.best_dimension(score)
            'clarity'
        """
        dims = {
            "completeness": score.completeness,
            "consistency": score.consistency,
            "clarity": score.clarity,
            "granularity": score.granularity,
            "domain_alignment": score.domain_alignment,
        }
        return max(dims, key=dims.__getitem__)

    def worst_dimension(self, score: "CriticScore") -> str:
        """Return the name of the lowest-scoring dimension in *score*.

        Args:
            score: A :class:`CriticScore` object.

        Returns:
            One of the 6 dimension names.

        Example:
            >>> critic.worst_dimension(score)
            'granularity'
        """
        dims = {
            "completeness": score.completeness,
            "consistency": score.consistency,
            "clarity": score.clarity,
            "granularity": score.granularity,
            "relationship_coherence": score.relationship_coherence,
            "domain_alignment": score.domain_alignment,
        }
        return min(dims, key=dims.__getitem__)

    def get_worst_entity(self, ontology: Dict[str, Any]) -> Optional[str]:
        """Return the ID of the entity with the lowest confidence score.

        Args:
            ontology: A dictionary with an ``entities`` key containing a list
                of entity dictionaries or :class:`Entity` objects. Each entity
                must have ``id`` and ``confidence`` fields.

        Returns:
            The ``id`` string of the worst entity, or ``None`` if the ontology
            is empty or contains no valid entities.

        Example:
            >>> ontology = {
            ...     'entities': [
            ...         {'id': 'e1', 'confidence': 0.9},
            ...         {'id': 'e2', 'confidence': 0.3},
            ...         {'id': 'e3', 'confidence': 0.7},
            ...     ]
            ... }
            >>> critic.get_worst_entity(ontology)
            'e2'
        """
        entities = ontology.get("entities", [])
        if not entities:
            return None

        worst_entity = None
        worst_confidence = float("inf")

        for entity in entities:
            # Handle both dict and Entity object formats
            if isinstance(entity, dict):
                entity_id = entity.get("id")
                confidence = entity.get("confidence", 1.0)
            else:  # Assume it's an Entity-like object with attributes
                entity_id = getattr(entity, "id", None)
                confidence = getattr(entity, "confidence", 1.0)

            # Skip entities without valid IDs
            if entity_id is None:
                continue

            # Track the entity with the lowest confidence
            if confidence < worst_confidence:
                worst_confidence = confidence
                worst_entity = entity_id

        return worst_entity

    def failing_scores(
        self, scores: List["CriticScore"], threshold: float = 0.6
    ) -> List["CriticScore"]:
        """Return scores whose ``overall`` value does NOT exceed *threshold*.

        Args:
            scores: List of :class:`CriticScore` objects to filter.
            threshold: Cut-off (scores with ``overall <= threshold`` are
                returned).

        Returns:
            List of failing :class:`CriticScore` objects.
        """
        return [s for s in scores if s.overall <= threshold]

    def average_dimension(self, scores: List["CriticScore"], dim: str) -> float:
        """Return the mean value of dimension *dim* across *scores*.

        Args:
            scores: List of :class:`CriticScore` objects.
            dim: One of ``completeness``, ``consistency``, ``clarity``,
                ``granularity``, or ``domain_alignment``.

        Returns:
            Mean as a float; ``0.0`` when *scores* is empty.

        Raises:
            AttributeError: If *dim* is not a valid dimension name.
        """
        if not scores:
            return 0.0
        return sum(getattr(s, dim) for s in scores) / len(scores)

    def score_summary(self, scores: List["CriticScore"]) -> dict:
        """Return a compact summary dict for a list of critic scores.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Dict with keys ``count``, ``mean``, ``min``, ``max``, and
            ``passing_fraction`` (fraction with ``overall > 0.6``).
            Numeric fields are ``0.0`` when *scores* is empty.
        """
        if not scores:
            return {
                "count": 0,
                "mean": 0.0,
                "min": 0.0,
                "max": 0.0,
                "passing_fraction": 0.0,
            }
        overalls = [s.overall for s in scores]
        mean = sum(overalls) / len(overalls)
        passing = sum(1 for v in overalls if v > 0.6)
        return {
            "count": len(overalls),
            "mean": mean,
            "min": min(overalls),
            "max": max(overalls),
            "passing_fraction": passing / len(overalls),
        }

    def percentile_overall(self, scores: List["CriticScore"], p: float) -> float:
        """Return the *p*-th percentile of ``overall`` values across *scores*.

        Uses linear interpolation.

        Args:
            scores: List of :class:`CriticScore` objects.
            p: Percentile in range [0, 100].

        Returns:
            Float percentile value; ``0.0`` when *scores* is empty.

        Raises:
            ValueError: If *p* is outside [0, 100].
        """
        if not 0 <= p <= 100:
            raise ValueError(f"p must be in [0, 100]; got {p}")
        if not scores:
            return 0.0
        vals = sorted(s.overall for s in scores)
        idx = (len(vals) - 1) * p / 100.0
        lo = int(idx)
        hi = lo + 1
        if hi >= len(vals):
            return vals[-1]
        return vals[lo] + (vals[hi] - vals[lo]) * (idx - lo)

    def normalize_scores(self, scores: List["CriticScore"]) -> List["CriticScore"]:
        """Return a list of scores with ``overall``-equivalent values scaled to [0, 1].

        Applies min-max normalization to the 5 dimensions of each score so
        that the overall values span [0, 1].  When the range is zero (all
        scores equal), the original list is returned unchanged.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            New list of :class:`CriticScore` objects with scaled dimensions;
            or the original list when fewer than 2 scores are provided or all
            overall values are identical.
        """
        import dataclasses as _dc
        if len(scores) < 2:
            return list(scores)
        overalls = [s.overall for s in scores]
        lo, hi = min(overalls), max(overalls)
        if hi == lo:
            return list(scores)
        # Scale all 5 dimensions uniformly by the same factor that maps overall to [0,1]
        factor = 1.0 / (hi - lo)
        new_scores = []
        for s in scores:
            shift = lo
            new_scores.append(
                _dc.replace(
                    s,
                    completeness=max(0.0, min(1.0, (s.completeness - shift) * factor)),
                    consistency=max(0.0, min(1.0, (s.consistency - shift) * factor)),
                    clarity=max(0.0, min(1.0, (s.clarity - shift) * factor)),
                    granularity=max(0.0, min(1.0, (s.granularity - shift) * factor)),
                    domain_alignment=max(0.0, min(1.0, (s.domain_alignment - shift) * factor)),
                )
            )
        return new_scores

    def compare_runs(
        self, score_a: "CriticScore", score_b: "CriticScore"
    ) -> Dict[str, Any]:
        """Return a comparison dict showing how *score_b* differs from *score_a*.

        Args:
            score_a: Baseline :class:`CriticScore` (earlier / previous run).
            score_b: Candidate :class:`CriticScore` (later / current run).

        Returns:
            Dict with keys:

            - ``'overall_delta'`` (float) — ``score_b.overall - score_a.overall``
            - ``'improved'`` (bool) — ``True`` when overall_delta > 0
            - ``'dim_deltas'`` (dict) — per-dimension deltas (positive = improved)
        """
        dims = ("completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment")
        dim_deltas = {d: getattr(score_b, d) - getattr(score_a, d) for d in dims}
        overall_delta = score_b.overall - score_a.overall
        return {
            "overall_delta": overall_delta,
            "improved": overall_delta > 0,
            "dim_deltas": dim_deltas,
        }

    def dimension_rankings(self, score: "CriticScore") -> List[str]:
        """Return dimension names sorted from best (highest) to worst (lowest).

        Args:
            score: A :class:`CriticScore` object.

        Returns:
            List of the 5 dimension name strings in descending score order.

        Example:
            >>> critic.dimension_rankings(score)
            ['domain_alignment', 'completeness', 'consistency', 'clarity', 'granularity', 'relationship_coherence']
        """
        dims = {
            "completeness": score.completeness,
            "consistency": score.consistency,
            "clarity": score.clarity,
            "granularity": score.granularity,
            "relationship_coherence": score.relationship_coherence,
            "domain_alignment": score.domain_alignment,
        }
        return sorted(dims.keys(), key=lambda d: -dims[d])

    def weakest_scores(self, scores: List["CriticScore"], n: int = 3) -> List["CriticScore"]:
        """Return the bottom *n* :class:`CriticScore` objects by overall value.

        Args:
            scores: List of :class:`CriticScore` objects.
            n: Maximum number of weak scores to return (default 3).

        Returns:
            List of up to *n* :class:`CriticScore` objects with the lowest
            ``overall`` values, sorted ascending (weakest first).
        """
        sorted_scores = sorted(scores, key=lambda s: s.overall)
        return sorted_scores[:n]

    def score_delta_between(self, a: "CriticScore", b: "CriticScore") -> float:
        """Return the signed difference ``b.overall - a.overall``.

        Positive means *b* is better than *a*.

        Args:
            a: Earlier / baseline score.
            b: Later / new score.

        Returns:
            Float difference.
        """
        return b.overall - a.overall

    def all_pass(self, scores: list, threshold: float = 0.6) -> bool:
        """Return ``True`` if every score's ``overall`` value is >= *threshold*.

        Args:
            scores: List of :class:`CriticScore` objects.
            threshold: Minimum acceptable overall score (default 0.6).

        Returns:
            ``True`` when all scores meet the threshold; ``False`` otherwise.
            Returns ``True`` for an empty list.
        """
        return all(s.overall > threshold for s in scores)

    def score_variance(self, scores: list) -> float:
        """Return the population variance of the ``overall`` values.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Variance float; ``0.0`` for empty or single-element lists.
        """
        if len(scores) < 2:
            return 0.0
        vals = [s.overall for s in scores]
        mean = sum(vals) / len(vals)
        return sum((v - mean) ** 2 for v in vals) / len(vals)

    def best_score(self, scores: list) -> "CriticScore | None":
        """Return the :class:`CriticScore` with the highest ``overall`` value.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Best score, or ``None`` when list is empty.
        """
        if not scores:
            return None
        return max(scores, key=lambda s: s.overall)

    def worst_score(self, scores: list) -> "CriticScore | None":
        """Return the :class:`CriticScore` with the lowest ``overall`` value.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Worst score, or ``None`` when list is empty.
        """
        if not scores:
            return None
        return min(scores, key=lambda s: s.overall)

    def average_overall(self, scores: list) -> float:
        """Return the mean ``overall`` across all scores.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Mean float; ``0.0`` for empty list.
        """
        if not scores:
            return 0.0
        return sum(s.overall for s in scores) / len(scores)

    def count_failing(self, scores: list, threshold: float = 0.6) -> int:
        """Return the count of scores with ``overall <= threshold``.

        Args:
            scores: List of :class:`CriticScore` objects.
            threshold: Upper bound (inclusive) for a failing score (default 0.6).

        Returns:
            Count of scores that fail (overall <= threshold).
        """
        return sum(1 for s in scores if s.overall <= threshold)

    def _generate_recommendations(
        self,
        ontology: Dict[str, Any],
        context: Any,
        completeness: float,
        consistency: float,
        clarity: float,
        granularity: float,
        relationship_coherence: float,
        domain_alignment: float
    ) -> List[str]:
        """Generate specific, actionable recommendations for improvement.

        Recommendations are tailored to the actual ontology content rather than
        being generic -- they cite entity counts, missing properties, dangling
        references, etc.
        """
        recommendations: List[str] = []

        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])
        entity_ids = {e.get('id') for e in entities if isinstance(e, dict) and e.get('id')}

        # -- Completeness recommendations -------------------------------------
        if completeness < 0.7:
            n = len(entities)
            if n == 0:
                recommendations.append(
                    "No entities found. Extract key concepts and named entities from the source data."
                )
            elif n < 5:
                recommendations.append(
                    f"Only {n} entit{'y' if n == 1 else 'ies'} extracted -- aim for at least 10 "
                    "to ensure adequate coverage."
                )

            n_rels = len(relationships)
            if n > 0 and n_rels == 0:
                recommendations.append(
                    f"No relationships defined for {n} entities. "
                    "Add at least one relationship per entity to improve connectivity."
                )
            elif n > 0 and n_rels < n * 0.5:
                recommendations.append(
                    f"Relationship density is low ({n_rels} relationships for {n} entities). "
                    "Aim for at least one relationship per entity."
                )

            types = {e.get('type') for e in entities if isinstance(e, dict) and e.get('type')}
            if len(types) < 2:
                recommendations.append(
                    "All entities share the same type. "
                    "Introduce multiple entity types (e.g. Person, Organization, Concept) for richer semantics."
                )

        # -- Consistency recommendations ---------------------------------------
        if consistency < 0.7:
            dangling = [
                r for r in relationships
                if isinstance(r, dict)
                and (r.get('source_id') not in entity_ids or r.get('target_id') not in entity_ids)
            ]
            if dangling:
                rel_ids = [r.get('id', '?') for r in dangling[:3]]
                recommendations.append(
                    f"{len(dangling)} relationship(s) have dangling references "
                    f"(e.g. {', '.join(str(r) for r in rel_ids)}). "
                    "Ensure all source_id / target_id values match existing entity IDs."
                )

            all_ids = [e.get('id') for e in entities if isinstance(e, dict) and e.get('id')]
            dupes = len(all_ids) - len(set(all_ids))
            if dupes > 0:
                recommendations.append(
                    f"{dupes} duplicate entity ID(s) detected. "
                    "Assign unique IDs to prevent ambiguous references."
                )

        # -- Clarity recommendations -------------------------------------------
        if clarity < 0.7:
            no_props = [e for e in entities if isinstance(e, dict) and not e.get('properties')]
            if len(no_props) > len(entities) * 0.5:
                recommendations.append(
                    f"{len(no_props)} of {len(entities)} entities lack properties. "
                    "Add descriptive properties (e.g. role, description, domain) to improve interpretability."
                )

            no_text = [e for e in entities if isinstance(e, dict) and not e.get('text')]
            if no_text:
                recommendations.append(
                    f"{len(no_text)} entit{'y' if len(no_text) == 1 else 'ies'} missing the 'text' field. "
                    "Populate 'text' with the original surface form for traceability."
                )

            short = [
                e for e in entities
                if isinstance(e, dict) and len((e.get('text') or '').strip()) < 3
            ]
            if short:
                recommendations.append(
                    f"{len(short)} entit{'y' if len(short) == 1 else 'ies'} have very short names "
                    "(< 3 characters). Review these for extraction noise."
                )

        # -- Granularity recommendations ---------------------------------------
        if granularity < 0.7:
            prop_counts = [len(e.get('properties', {})) for e in entities if isinstance(e, dict)]
            avg_props = sum(prop_counts) / max(len(prop_counts), 1)
            if avg_props < 1.0:
                recommendations.append(
                    f"Average {avg_props:.1f} properties per entity is very low. "
                    "Enrich entities with domain-specific attributes."
                )

            n_rels = len(relationships)
            rel_ratio = n_rels / max(len(entities), 1)
            if rel_ratio > 5.0:
                recommendations.append(
                    "Relationship count is very high relative to entity count -- consider merging redundant entities "
                    "or collapsing similar relationship types."
                )

        # -- Relationship coherence recommendations ----------------------------
        if relationship_coherence < 0.7:
            _GENERIC_RELS = {'relates_to', 'related_to', 'links', 'connected', 'associated', 'rel'}
            rel_types = [r.get('type', '') for r in relationships if isinstance(r, dict)]
            generic_count = sum(1 for rt in rel_types if rt.lower() in _GENERIC_RELS)
            
            if generic_count > len(rel_types) * 0.3:
                recommendations.append(
                    f"{generic_count} of {len(rel_types)} relationships use generic types "
                    "(e.g. 'relates_to', 'connected'). Replace with specific verbs like 'manages', 'causes', 'implements'."
                )
            
            unique_types = set(rt for rt in rel_types if rt)
            if len(unique_types) == 1 and len(relationships) > 5:
                recommendations.append(
                    "All relationships use the same type. Add variety by using domain-specific relationship types."
                )
            
            no_type = [r for r in relationships if isinstance(r, dict) and not r.get('type')]
            if no_type:
                recommendations.append(
                    f"{len(no_type)} relationship(s) missing type field. "
                    "Assign meaningful types to all relationships."
                )

        # -- Domain alignment recommendations ---------------------------------
        if domain_alignment < 0.7:
            domain = (getattr(context, 'domain', None) or ontology.get('domain', 'general')).lower()
            recommendations.append(
                f"Many entity/relationship types don't align with '{domain}' domain vocabulary. "
                "Review type names and replace generic labels with domain-specific terms."
            )

        return recommendations

    def passing_rate(self, scores: list, threshold: float = 0.6) -> float:
        """Return the fraction of scores with ``overall > threshold``.

        Args:
            scores: List of :class:`CriticScore` objects.
            threshold: Exclusive lower bound (default 0.6).

        Returns:
            Float in [0.0, 1.0]; ``0.0`` for empty list.
        """
        if not scores:
            return 0.0
        return sum(1 for s in scores if s.overall > threshold) / len(scores)

    def failing_scores(self, scores: list, threshold: float = 0.6) -> list:
        """Return only scores that do NOT pass *threshold*.

        Scores are considered "failing" if their ``overall`` value is
        **not greater than** *threshold* (i.e., ``overall <= threshold``).

        Args:
            scores: List of :class:`CriticScore` objects.
            threshold: Passing threshold (default 0.6).  Scores with
                ``overall <= threshold`` are included in the result.

        Returns:
            List of :class:`CriticScore` objects where ``overall <= threshold``,
            in the original order.  Empty list if no scores fail or if
            *scores* is empty.

        Example:
            >>> failing = critic.failing_scores(all_scores, threshold=0.7)
            >>> print(f"Found {len(failing)} scores below 0.7")
        """
        return [s for s in scores if s.overall <= threshold]

    def score_spread(self, scores: list) -> float:
        """Return the range (max - min) of ``overall`` values.

        Args:
            scores: List of :class:`CriticScore` objects.

        Returns:
            Float spread; ``0.0`` for empty or single-element lists.
        """
        if len(scores) < 2:
            return 0.0
        vals = [s.overall for s in scores]
        return max(vals) - min(vals)

    def top_k_scores(self, scores: list, k: int = 3) -> list:
        """Return the top-*k* ``CriticScore`` objects sorted by overall score.

        Args:
            scores: List of ``CriticScore`` objects.
            k: Number of top items to return.

        Returns:
            Up to *k* scores, highest first.
        """
        if not scores:
            return []
        return sorted(scores, key=lambda s: s.overall, reverse=True)[:k]

    def below_threshold_count(self, scores: list, threshold: float = 0.5) -> int:
        """Count scores strictly below *threshold*.

        Args:
            scores: List of ``CriticScore`` objects.
            threshold: Cut-off value (default 0.5).

        Returns:
            Integer count of scores with ``overall < threshold``.
        """
        return sum(1 for s in scores if s.overall < threshold)

    def bucket_scores(self, scores: list, buckets: int = 4) -> dict:
        """Partition scores into equal-width buckets across [0.0, 1.0].

        Args:
            scores: List of ``CriticScore`` objects.
            buckets: Number of equal-width buckets.

        Returns:
            Dict mapping label string (e.g. ``"0.00-0.25"``) to count.
        """
        if buckets < 1:
            buckets = 1
        width = 1.0 / buckets
        result: dict = {}
        for i in range(buckets):
            lo = round(i * width, 6)
            hi = round((i + 1) * width, 6)
            label = f"{lo:.2f}-{hi:.2f}"
            result[label] = sum(1 for s in scores if lo <= s.overall < hi)
        # clamp exact 1.0 into last bucket
        last = list(result.keys())[-1]
        result[last] += sum(1 for s in scores if s.overall == 1.0)
        return result

    def log_evaluation_json(
        self, 
        score: CriticScore, 
        log_level: str = "INFO"
    ) -> None:
        """Log evaluation result as structured JSON.

        Outputs the evaluation score as a single JSON line to the class logger,
        useful for structured logging systems, analytics, and audit trails.

        Args:
            score: CriticScore to log
            log_level: Logging level ('DEBUG', 'INFO', 'WARNING', 'ERROR').
                       Defaults to 'INFO'.

        Example:
            >>> critic.log_evaluation_json(score, log_level='INFO')
            # Logs: INFO {"overall": 0.821, "dimensions": {...}}
        """
        json_str = score.to_json()
        log_fn = getattr(self._log, log_level.lower(), self._log.info)
        log_fn(f"Evaluation result: {json_str}")

    def improvement_over_baseline(self, scores: list, baseline: float = 0.5) -> float:
        """Return the fraction of scores strictly above *baseline*.

        Args:
            scores: List of ``CriticScore`` objects.
            baseline: Reference threshold.

        Returns:
            Float in [0.0, 1.0]; ``0.0`` when *scores* is empty.
        """
        if not scores:
            return 0.0
        return sum(1 for s in scores if s.overall > baseline) / len(scores)

    def score_iqr(self, scores: list) -> float:
        """Return the inter-quartile range (Q3 - Q1) of overall scores.

        Args:
            scores: List of ``CriticScore`` objects.

        Returns:
            Float IQR; ``0.0`` when fewer than 4 scores.
        """
        if len(scores) < 4:
            return 0.0
        vals = sorted(s.overall for s in scores)
        n = len(vals)
        q1_idx = n // 4
        q3_idx = 3 * n // 4
        return vals[q3_idx] - vals[q1_idx]

    def dimension_covariance(self, scores: list, dim_a: str, dim_b: str) -> float:
        """Return the sample covariance between two CriticScore dimensions.

        Args:
            scores: Iterable of ``CriticScore`` objects.
            dim_a: First dimension name (e.g. ``"completeness"``).
            dim_b: Second dimension name.

        Returns:
            Sample covariance as float; ``0.0`` when fewer than 2 scores.

        Raises:
            AttributeError: If either dimension does not exist on ``CriticScore``.
        """
        vals = list(scores)
        if len(vals) < 2:
            return 0.0
        a_vals = [getattr(s, dim_a) for s in vals]
        b_vals = [getattr(s, dim_b) for s in vals]
        n = len(vals)
        mean_a = sum(a_vals) / n
        mean_b = sum(b_vals) / n
        return sum((a_vals[i] - mean_a) * (b_vals[i] - mean_b) for i in range(n)) / (n - 1)

    _DIMENSIONS = ("completeness", "consistency", "clarity", "granularity",
                   "relationship_coherence", "domain_alignment")

    def top_improving_dimension(self, before: "CriticScore", after: "CriticScore") -> str:
        """Return the dimension with the largest improvement between two scores.

        Args:
            before: The earlier ``CriticScore``.
            after:  The later ``CriticScore``.

        Returns:
            Name of the dimension whose ``after - before`` delta is largest.
            If all deltas are equal (or zero) returns the first dimension.
        """
        deltas = {d: getattr(after, d, 0.0) - getattr(before, d, 0.0)
                  for d in self._DIMENSIONS}
        return max(deltas, key=lambda d: deltas[d])

    def critic_dimension_rank(self, score) -> list:
        """Return dimensions ranked from lowest to highest score.

        Args:
            score: A ``CriticScore`` instance.

        Returns:
            List of dimension name strings sorted ascending by their value on
            *score* (weakest first).
        """
        return sorted(self._DIMENSIONS, key=lambda d: getattr(score, d, 0.0))

    def dimension_variance(self, scores: list, dim: str) -> float:
        """Return the population variance of *dim* across a list of scores.

        Args:
            scores: Iterable of ``CriticScore`` objects.
            dim: Dimension name (e.g. ``"completeness"``).

        Returns:
            Float population variance; ``0.0`` when fewer than 2 scores.

        Raises:
            AttributeError: If *dim* does not exist on ``CriticScore``.
        """
        vals = list(scores)
        if len(vals) < 2:
            return 0.0
        dim_vals = [getattr(s, dim) for s in vals]
        n = len(dim_vals)
        mean = sum(dim_vals) / n
        return sum((v - mean) ** 2 for v in dim_vals) / n

    def weakest_dimension(self, score) -> str:
        """Return the name of the lowest-scoring dimension in *score*.

        Args:
            score: A ``CriticScore`` instance.

        Returns:
            Name of the dimension with the smallest value.
        """
        return min(self._DIMENSIONS, key=lambda d: getattr(score, d, 0.0))

    def dimension_delta_summary(self, before, after) -> dict:
        """Return a dict of per-dimension deltas between two ``CriticScore`` objects.

        Args:
            before: Earlier ``CriticScore``.
            after: Later ``CriticScore``.

        Returns:
            Dict mapping dimension name → ``after_dim - before_dim`` float delta.
        """
        return {d: getattr(after, d, 0.0) - getattr(before, d, 0.0)
                for d in self._DIMENSIONS}

    def all_dimensions_above(self, score, threshold: float = 0.5) -> bool:
        """Return True if all dimensions of *score* exceed *threshold*.

        Args:
            score: A ``CriticScore`` instance.
            threshold: Minimum value (exclusive). Defaults to ``0.5``.

        Returns:
            ``True`` when every dimension value is strictly greater than
            *threshold*; ``False`` otherwise.
        """
        return all(getattr(score, d, 0.0) > threshold for d in self._DIMENSIONS)


    def dimension_ratio(self, score) -> dict:
        """Return each dimension score as a fraction of the total score sum.

        Args:
            score: A ``CriticScore`` instance.

        Returns:
            Dict mapping dimension name → fraction. All fractions sum to 1.0.
            Returns equal fractions when total is 0.
        """
        total = sum(getattr(score, d, 0.0) for d in self._DIMENSIONS)
        if total == 0.0:
            frac = 1.0 / len(self._DIMENSIONS)
            return {d: frac for d in self._DIMENSIONS}
        return {d: getattr(score, d, 0.0) / total for d in self._DIMENSIONS}

    def all_dimensions_below(self, score, threshold: float = 0.5) -> bool:
        """Return True if all dimensions of *score* are below *threshold*.

        Args:
            score: A ``CriticScore`` instance.
            threshold: Maximum value (exclusive). Defaults to ``0.5``.

        Returns:
            ``True`` when every dimension value is strictly less than
            *threshold*; ``False`` otherwise.
        """
        return all(getattr(score, d, 0.0) < threshold for d in self._DIMENSIONS)

    def dimension_mean(self, score) -> float:
        """Return the mean value across all dimensions of *score*.

        Args:
            score: A ``CriticScore`` instance.

        Returns:
            Float average of all dimension values.
        """
        vals = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        return sum(vals) / len(vals)

    def dimension_count_above(self, score, threshold: float = 0.5) -> int:
        """Return the number of dimensions strictly above *threshold*.

        Args:
            score: A ``CriticScore`` instance.
            threshold: Minimum value (exclusive). Defaults to ``0.5``.

        Returns:
            Integer count of dimensions with value > *threshold*.
        """
        return sum(1 for d in self._DIMENSIONS if getattr(score, d, 0.0) > threshold)

    def dimension_std(self, score) -> float:
        """Return the standard deviation of dimension values in *score*.

        Args:
            score: A ``CriticScore`` instance.

        Returns:
            Float population std-dev; ``0.0`` when all dims are equal.
        """
        vals = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        return variance ** 0.5

    def dimension_improvement_mask(self, before, after) -> dict:
        """Return a bool dict indicating which dimensions improved.

        Args:
            before: A ``CriticScore`` instance (baseline).
            after: A ``CriticScore`` instance (new).

        Returns:
            Dict mapping dimension name → ``True`` if ``after > before``,
            ``False`` otherwise.
        """
        return {
            d: getattr(after, d, 0.0) > getattr(before, d, 0.0)
            for d in self._DIMENSIONS
        }

    def passing_dimensions(self, score, threshold: float = 0.5) -> list:
        """Return list of dimension names strictly above *threshold*.

        Args:
            score: A ``CriticScore`` instance.
            threshold: Minimum value (exclusive). Defaults to ``0.5``.

        Returns:
            List of dimension name strings.
        """
        return [d for d in self._DIMENSIONS if getattr(score, d, 0.0) > threshold]

    def weighted_score(self, score, weights: dict = None) -> float:
        """Return a custom-weighted overall score.

        Args:
            score: A ``CriticScore`` instance.
            weights: Dict mapping dimension name → float weight. Missing
                dimensions get weight 1.0. If ``None``, uses equal weights.

        Returns:
            Float weighted average across all dimensions.
        """
        if weights is None:
            weights = {}
        total_w = 0.0
        total_s = 0.0
        for d in self._DIMENSIONS:
            w = weights.get(d, 1.0)
            total_w += w
            total_s += getattr(score, d, 0.0) * w
        if total_w == 0.0:
            return 0.0
        return total_s / total_w

    def dimension_correlation(self, scores_a: list, scores_b: list, dimension: str = "completeness") -> float:
        """Return Pearson correlation for *dimension* across two score lists.

        Args:
            scores_a: List of ``CriticScore`` instances (series A).
            scores_b: List of ``CriticScore`` instances (series B). Must be
                the same length as *scores_a*.
            dimension: Dimension name to compare. Defaults to ``"completeness"``.

        Returns:
            Float Pearson r in [-1, 1]; ``0.0`` when fewer than 2 samples or
            std-dev is zero.
        """
        n = min(len(scores_a), len(scores_b))
        if n < 2:
            return 0.0
        a = [getattr(s, dimension, 0.0) for s in scores_a[:n]]
        b = [getattr(s, dimension, 0.0) for s in scores_b[:n]]
        mean_a = sum(a) / n
        mean_b = sum(b) / n
        cov = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n)) / n
        std_a = (sum((v - mean_a) ** 2 for v in a) / n) ** 0.5
        std_b = (sum((v - mean_b) ** 2 for v in b) / n) ** 0.5
        if std_a == 0.0 or std_b == 0.0:
            return 0.0
        return cov / (std_a * std_b)

    def dimension_entropy(self, score) -> float:
        """Return Shannon entropy of dimension values in *score*.

        Treats dimension values as a probability distribution (after
        normalization). Values of 0 contribute 0 to entropy.

        Args:
            score: A ``CriticScore`` instance.

        Returns:
            Float entropy in bits; ``0.0`` when all dims are zero or equal.
        """
        import math
        vals = [max(getattr(score, d, 0.0), 0.0) for d in self._DIMENSIONS]
        total = sum(vals)
        if total == 0.0:
            return 0.0
        entropy = 0.0
        for v in vals:
            p = v / total
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy

    def compare_scores(self, before, after) -> dict:
        """Return per-dimension diffs plus overall delta.

        Args:
            before: A ``CriticScore`` instance (baseline).
            after: A ``CriticScore`` instance (new).

        Returns:
            Dict with dimension names as keys (float diffs) plus
            ``"overall"`` key showing after.overall - before.overall.
        """
        diffs = {d: getattr(after, d, 0.0) - getattr(before, d, 0.0)
                 for d in self._DIMENSIONS}
        diffs["overall"] = getattr(after, "overall", 0.0) - getattr(before, "overall", 0.0)
        return diffs

    def score_is_above_baseline(self, score: "CriticScore", baseline: float = 0.5) -> bool:
        """Return whether every dimension in *score* exceeds *baseline*.

        Args:
            score: :class:`CriticScore` to evaluate.
            baseline: Threshold that each dimension must strictly exceed.

        Returns:
            ``True`` when all 6 dimensions are > *baseline*, ``False``
            otherwise.
        """
        return all(getattr(score, d, 0.0) > baseline for d in self._DIMENSIONS)

    def top_k_dimensions(self, score: "CriticScore", k: int = 3) -> list:
        """Return the *k* highest-scoring dimension names for *score*.

        Args:
            score: :class:`CriticScore` to inspect.
            k: Number of top dimensions to return; clamped to the number of
               available dimensions.

        Returns:
            List of dimension-name strings sorted descending by value, length
            min(k, 6).
        """
        dims = [(d, getattr(score, d, 0.0)) for d in self._DIMENSIONS]
        dims_sorted = sorted(dims, key=lambda x: x[1], reverse=True)
        k = max(0, min(k, len(dims_sorted)))
        return [d for d, _ in dims_sorted[:k]]

    def dimension_improvement_rate(
        self, before: "CriticScore", after: "CriticScore"
    ) -> float:
        """Return the fraction of dimensions that improved from *before* to *after*.

        Args:
            before: Earlier :class:`CriticScore`.
            after: Later :class:`CriticScore`.

        Returns:
            Float in [0, 1]; 0.0 when no dimensions improved.
        """
        improved = sum(
            1 for d in self._DIMENSIONS
            if getattr(after, d, 0.0) > getattr(before, d, 0.0)
        )
        return improved / len(self._DIMENSIONS)

    def dimension_weighted_sum(
        self, score: "CriticScore", weights: dict = None
    ) -> float:
        """Return a weighted sum of all dimension scores.

        Args:
            score: :class:`CriticScore` to evaluate.
            weights: Optional dict mapping dimension names to floats.  If
                ``None``, uses the module-level ``DIMENSION_WEIGHTS``.

        Returns:
            Float weighted sum.
        """
        w = weights if weights is not None else DIMENSION_WEIGHTS
        return sum(getattr(score, d, 0.0) * w.get(d, 1.0) for d in self._DIMENSIONS)

    def dimension_min(self, score: "CriticScore") -> str:
        """Return the name of the lowest-scoring dimension.

        Args:
            score: :class:`CriticScore` to inspect.

        Returns:
            String dimension name.
        """
        return min(self._DIMENSIONS, key=lambda d: getattr(score, d, 0.0))

    def dimension_max(self, score: "CriticScore") -> str:
        """Return the name of the highest-scoring dimension.

        Args:
            score: :class:`CriticScore` to inspect.

        Returns:
            String dimension name.
        """
        return max(self._DIMENSIONS, key=lambda d: getattr(score, d, 0.0))

    def dimension_range(self, score: "CriticScore") -> float:
        """Return the range (max - min) across all dimension values.

        Args:
            score: :class:`CriticScore` to inspect.

        Returns:
            Non-negative float.
        """
        vals = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        return max(vals) - min(vals)

    def score_reliability(self, scores: list) -> float:
        """Return a reliability measure for a list of :class:`CriticScore` objects.

        Reliability is defined as 1 - (population std-dev of overall scores).
        A value near 1 indicates consistent evaluation; near 0 indicates high
        variance.

        Args:
            scores: List of :class:`CriticScore` instances.

        Returns:
            Float in [0, 1] (clamped); 0.0 when fewer than 2 scores.
        """
        if len(scores) < 2:
            return 0.0
        overalls = [getattr(s, "overall", 0.0) for s in scores]
        mean = sum(overalls) / len(overalls)
        variance = sum((v - mean) ** 2 for v in overalls) / len(overalls)
        std = variance ** 0.5
        return max(0.0, min(1.0, 1.0 - std))

    def dimensions_above_count(
        self, score: "CriticScore", threshold: float = 0.5
    ) -> int:
        """Return the number of dimensions strictly above *threshold*.

        Args:
            score: :class:`CriticScore` to evaluate.
            threshold: Comparison threshold.

        Returns:
            Integer count in [0, 6].
        """
        return sum(1 for d in self._DIMENSIONS if getattr(score, d, 0.0) > threshold)

    def score_letter_grade(self, score: "CriticScore") -> str:
        """Return a letter grade (A–F) based on the overall score.

        Grading scale:
          - A: overall >= 0.9
          - B: overall >= 0.75
          - C: overall >= 0.6
          - D: overall >= 0.45
          - F: overall < 0.45

        Args:
            score: :class:`CriticScore` to evaluate.

        Returns:
            Single-character string: ``"A"``, ``"B"``, ``"C"``, ``"D"``, or
            ``"F"``.
        """
        overall = getattr(score, "overall", 0.0)
        if overall >= 0.9:
            return "A"
        if overall >= 0.75:
            return "B"
        if overall >= 0.6:
            return "C"
        if overall >= 0.45:
            return "D"
        return "F"

    def dimension_coefficient_of_variation(self, score: "CriticScore") -> float:
        """Return the coefficient of variation (std / mean) of dimension values.

        A low value indicates consistent dimension scores; a high value
        indicates uneven performance across dimensions.

        Args:
            score: :class:`CriticScore` to evaluate.

        Returns:
            Float; 0.0 when mean is zero.
        """
        vals = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        n = len(vals)
        mean = sum(vals) / n
        if mean == 0.0:
            return 0.0
        variance = sum((v - mean) ** 2 for v in vals) / n
        return (variance ** 0.5) / mean

    def dimensions_at_max_count(self, score: "CriticScore", threshold: float = 0.9) -> int:  # type: ignore[name-defined]
        """Return the number of dimensions at or above *threshold*.

        Args:
            score: ``CriticScore`` to inspect.
            threshold: Minimum value to consider "at max" (default 0.9).

        Returns:
            Integer count in range [0, 6].
        """
        return sum(
            1 for d in self._DIMENSIONS
            if getattr(score, d, 0.0) >= threshold
        )

    def dimension_harmonic_mean(self, score: "CriticScore") -> float:  # type: ignore[name-defined]
        """Return the harmonic mean of the six dimension values.

        Dimensions with value 0 are replaced by a small epsilon to avoid
        division by zero.

        Args:
            score: ``CriticScore`` to inspect.

        Returns:
            Float in (0, 1].
        """
        epsilon = 1e-9
        vals = [max(getattr(score, d, 0.0), epsilon) for d in self._DIMENSIONS]
        return len(vals) / sum(1.0 / v for v in vals)

    def dimension_geometric_mean(self, score: "CriticScore") -> float:  # type: ignore[name-defined]
        """Return the geometric mean of the six dimension values.

        Dimensions with value 0 are replaced by a small epsilon.

        Args:
            score: ``CriticScore`` to inspect.

        Returns:
            Float in (0, 1].
        """
        epsilon = 1e-9
        vals = [max(getattr(score, d, 0.0), epsilon) for d in self._DIMENSIONS]
        product = 1.0
        for v in vals:
            product *= v
        return product ** (1.0 / len(vals))

    def dimensions_below_count(self, score: "CriticScore", threshold: float = 0.3) -> int:  # type: ignore[name-defined]
        """Return the number of dimensions below *threshold*.

        Args:
            score: ``CriticScore`` to inspect.
            threshold: Maximum value to consider "below" (default 0.3).

        Returns:
            Integer count in range [0, 6].
        """
        return sum(
            1 for d in self._DIMENSIONS
            if getattr(score, d, 0.0) < threshold
        )

    def dimension_spread(self, score: "CriticScore") -> float:  # type: ignore[name-defined]
        """Return max - min of the six dimension values.

        Args:
            score: ``CriticScore`` to inspect.

        Returns:
            Float in [0, 1].
        """
        vals = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        return max(vals) - min(vals)

    def top_dimension(self, score: "CriticScore") -> str:  # type: ignore[name-defined]
        """Return the name of the highest-scoring dimension.

        Args:
            score: ``CriticScore`` to inspect.

        Returns:
            String dimension name.
        """
        return max(self._DIMENSIONS, key=lambda d: getattr(score, d, 0.0))

    def bottom_dimension(self, score: "CriticScore") -> str:  # type: ignore[name-defined]
        """Return the name of the lowest-scoring dimension.

        Args:
            score: ``CriticScore`` to inspect.

        Returns:
            String dimension name.
        """
        return min(self._DIMENSIONS, key=lambda d: getattr(score, d, 0.0))

    def score_above_threshold_count(self, score: "CriticScore", threshold: float = 0.7) -> int:  # type: ignore[name-defined]
        """Return count of dimensions at or above *threshold*.

        Args:
            score: ``CriticScore`` to inspect.
            threshold: Minimum acceptable value (default 0.7).

        Returns:
            Integer count in [0, 6].
        """
        return sum(1 for d in self._DIMENSIONS if getattr(score, d, 0.0) >= threshold)

    def dimension_balance_score(self, score: "CriticScore") -> float:  # type: ignore[name-defined]
        """Return a "balance" score in [0, 1].

        Perfect balance (all dims equal) → 1.0; extreme imbalance → 0.0.
        Computed as 1 - (std / 0.5) clipped to [0, 1], where 0.5 is the
        maximum possible std for values in [0, 1].

        Args:
            score: ``CriticScore`` to inspect.

        Returns:
            Float in [0, 1].
        """
        vals = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        n = len(vals)
        mean = sum(vals) / n
        std = (sum((v - mean) ** 2 for v in vals) / n) ** 0.5
        return max(0.0, 1.0 - std / 0.5)

    def score_percentile_rank(self, score: "CriticScore", history: list) -> float:  # type: ignore[name-defined]
        """Return the percentile rank of *score* overall within *history*.

        Args:
            score: ``CriticScore`` to rank.
            history: List of ``CriticScore`` objects to compare against.

        Returns:
            Float in [0, 100]; 0.0 when history is empty.
        """
        if not history:
            return 0.0
        overall = score.overall
        below = sum(1 for h in history if h.overall < overall)
        return 100.0 * below / len(history)

    def score_classification(self, score: "CriticScore") -> str:  # type: ignore[name-defined]
        """Return a human-readable quality bucket for *score*.

        Buckets: "excellent" (≥0.85), "good" (≥0.70), "fair" (≥0.50), "poor" (<0.50).

        Args:
            score: ``CriticScore`` to classify.

        Returns:
            String label.
        """
        o = score.overall
        if o >= 0.85:
            return "excellent"
        if o >= 0.70:
            return "good"
        if o >= 0.50:
            return "fair"
        return "poor"

    def dimension_rank_order(self, score: "CriticScore") -> list:  # type: ignore[name-defined]
        """Return dimension names sorted from highest to lowest value.

        Args:
            score: ``CriticScore`` to inspect.

        Returns:
            List of 6 dimension name strings.
        """
        return sorted(self._DIMENSIONS, key=lambda d: getattr(score, d, 0.0), reverse=True)


    def dimension_normalized_vector(self, score: "CriticScore") -> list:  # type: ignore[name-defined]
        """Return dimension values normalized to a unit vector (L2).

        Args:
            score: ``CriticScore`` to normalize.

        Returns:
            List of 6 floats; all zeros when the vector magnitude is 0.
        """
        vals = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        magnitude = sum(v ** 2 for v in vals) ** 0.5
        if magnitude == 0.0:
            return [0.0] * len(vals)
        return [v / magnitude for v in vals]

    def score_above_median(self, score: "CriticScore", history: list) -> bool:  # type: ignore[name-defined]
        """Return True if *score* overall is above the median of *history*.

        Args:
            score: ``CriticScore`` to test.
            history: List of ``CriticScore`` objects.

        Returns:
            Bool; True when history is empty (no evidence of failure).
        """
        if not history:
            return True
        overalls = sorted(h.overall for h in history)
        n = len(overalls)
        if n % 2 == 0:
            median = (overalls[n // 2 - 1] + overalls[n // 2]) / 2.0
        else:
            median = overalls[n // 2]
        return score.overall > median

    def dimension_cosine_similarity(self, score1: "CriticScore", score2: "CriticScore") -> float:  # type: ignore[name-defined]
        """Return cosine similarity between two CriticScore dimension vectors.

        Args:
            score1: First ``CriticScore``.
            score2: Second ``CriticScore``.

        Returns:
            Float in [-1, 1]; 0.0 when either vector is zero.
        """
        v1 = [getattr(score1, d, 0.0) for d in self._DIMENSIONS]
        v2 = [getattr(score2, d, 0.0) for d in self._DIMENSIONS]
        dot = sum(a * b for a, b in zip(v1, v2))
        mag1 = sum(a ** 2 for a in v1) ** 0.5
        mag2 = sum(b ** 2 for b in v2) ** 0.5
        if mag1 == 0.0 or mag2 == 0.0:
            return 0.0
        return dot / (mag1 * mag2)

    def score_distance(self, score1: "CriticScore", score2: "CriticScore") -> float:  # type: ignore[name-defined]
        """Return Euclidean distance between two CriticScore dimension vectors.

        Args:
            score1: First ``CriticScore``.
            score2: Second ``CriticScore``.

        Returns:
            Float; 0.0 when scores are identical.
        """
        return sum((getattr(score1, d, 0.0) - getattr(score2, d, 0.0)) ** 2 for d in self._DIMENSIONS) ** 0.5

    def dimension_percentile(self, score: "CriticScore", p: float = 50.0) -> float:
        """Return the p-th percentile of dimension values in a CriticScore.

        Args:
            score: CriticScore object to inspect.
            p: Percentile in [0, 100]. Defaults to 50 (median).

        Returns:
            Float p-th percentile of dimension scores.
        """
        vals = sorted(getattr(score, d, 0.0) for d in self._DIMENSIONS)
        n = len(vals)
        if n == 0:
            return 0.0
        idx = (p / 100.0) * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        frac = idx - lo
        return vals[lo] + frac * (vals[hi] - vals[lo])

    def dimension_above_threshold(self, score: "CriticScore", threshold: float = 0.7) -> int:
        """Count how many dimensions in a CriticScore exceed a threshold.

        Args:
            score: CriticScore to evaluate.
            threshold: Exclusive lower bound. Defaults to 0.7.

        Returns:
            Integer count of dimensions with value > threshold.
        """
        return sum(1 for d in self._DIMENSIONS if getattr(score, d, 0.0) > threshold)

    def dimension_mean(self, score: "CriticScore") -> float:
        """Return the arithmetic mean of all dimension values in a CriticScore.

        Args:
            score: CriticScore to evaluate.

        Returns:
            Float mean; 0.0 when no dimensions.
        """
        if not self._DIMENSIONS:
            return 0.0
        return sum(getattr(score, d, 0.0) for d in self._DIMENSIONS) / len(self._DIMENSIONS)

    def dimension_below_threshold(self, score: "CriticScore", threshold: float = 0.5) -> int:
        """Count how many dimensions in a CriticScore fall below *threshold*.

        Args:
            score: CriticScore to evaluate.
            threshold: Exclusive upper bound. Defaults to 0.5.

        Returns:
            Integer count of dimensions with value < threshold.
        """
        return sum(1 for d in self._DIMENSIONS if getattr(score, d, 0.0) < threshold)

    def dimension_weighted_score(self, score: "CriticScore", weights: dict | None = None) -> float:
        """Return a weighted average of dimension scores.

        Args:
            score: CriticScore to evaluate.
            weights: Optional dict mapping dimension name to weight float.
                     Defaults to equal weights (same as dimension_mean).

        Returns:
            Float weighted mean; 0.0 when no dimensions.
        """
        if not self._DIMENSIONS:
            return 0.0
        if weights is None:
            weights = {d: 1.0 for d in self._DIMENSIONS}
        total_w = sum(weights.get(d, 1.0) for d in self._DIMENSIONS)
        if total_w == 0:
            return 0.0
        return sum(getattr(score, d, 0.0) * weights.get(d, 1.0) for d in self._DIMENSIONS) / total_w

    def dimension_top_k(self, score: "CriticScore", k: int = 3) -> list:
        """Return the names of the top-k highest-scoring dimensions.

        Args:
            score: CriticScore to evaluate.
            k: Number of top dimensions to return. Defaults to 3.

        Returns:
            List of dimension name strings sorted descending by value.
        """
        ranked = sorted(self._DIMENSIONS, key=lambda d: getattr(score, d, 0.0), reverse=True)
        return ranked[:k]

    def dimension_bottom_k(self, score: "CriticScore", k: int = 3) -> list:
        """Return the names of the bottom-k lowest-scoring dimensions.

        Args:
            score: CriticScore to evaluate.
            k: Number of bottom dimensions to return. Defaults to 3.

        Returns:
            List of dimension name strings sorted ascending by value.
        """
        ranked = sorted(self._DIMENSIONS, key=lambda d: getattr(score, d, 0.0))
        return ranked[:k]

    def dimension_sum(self, score: "CriticScore") -> float:
        """Return the sum of all dimension values in a CriticScore.

        Args:
            score: CriticScore to evaluate.

        Returns:
            Float sum of all 6 dimension values.
        """
        return sum(getattr(score, d, 0.0) for d in self._DIMENSIONS)

    def score_diff_from_mean(self, score: "CriticScore") -> float:
        """Return the difference between overall score and dimension mean.

        Args:
            score: CriticScore with an ``overall`` attribute.

        Returns:
            Float difference (overall - dimension_mean); 0.0 when no overall.
        """
        overall = getattr(score, "overall", None)
        if overall is None:
            return 0.0
        return overall - self.dimension_mean(score)

    # ------------------------------------------------------------------ #
    # Batch 202: Cache and score distribution analysis methods           #
    # ------------------------------------------------------------------ #

    def cache_hit_potential(self) -> float:
        """Calculate potential benefit of caching (shared/instance).

        Returns:
            Ratio of shared cache size to maximum (0.0-1.0). Higher means
            more cache utilization, approaching capacity limit.
        """
        return self.shared_cache_size() / max(self._SHARED_EVAL_CACHE_MAX, 1)

    def score_dimension_variance(self, score: "CriticScore") -> float:
        """Calculate variance across the six dimension scores.

        Args:
            score: CriticScore to analyze.

        Returns:
            Variance (spread) of dimension values. Low variance indicates
            balanced quality; high variance shows uneven scores.
        """
        dims = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        if not dims:
            return 0.0
        mean_val = sum(dims) / len(dims)
        variance = sum((v - mean_val) ** 2 for v in dims) / len(dims)
        return variance

    def dimension_range(self, score: "CriticScore") -> float:
        """Get range (max - min) of dimension scores.

        Args:
            score: CriticScore to evaluate.

        Returns:
            Difference between highest and lowest dimension score.
        """
        dims = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        if not dims:
            return 0.0
        return max(dims) - min(dims)

    def weakest_dimension(self, score: "CriticScore") -> str:
        """Identify the dimension with lowest score.

        Args:
            score: CriticScore to analyze.

        Returns:
            Name of the weakest dimension (e.g., 'completeness'),
            or 'unknown' if no dimensions available.
        """
        dims = [(d, getattr(score, d, 0.0)) for d in self._DIMENSIONS]
        if not dims:
            return 'unknown'
        return min(dims, key=lambda x: x[1])[0]

    def strongest_dimension(self, score: "CriticScore") -> str:
        """Identify the dimension with highest score.

        Args:
            score: CriticScore to analyze.

        Returns:
            Name of the strongest dimension, or 'unknown' if unavailable.
        """
        dims = [(d, getattr(score, d, 0.0)) for d in self._DIMENSIONS]
        if not dims:
            return 'unknown'
        return max(dims, key=lambda x: x[1])[0]

    def score_balance_ratio(self, score: "CriticScore") -> float:
        """Calculate balance ratio (min/max dimension score).

        Args:
            score: CriticScore to evaluate.

        Returns:
            Ratio of weakest to strongest dimension (0.0-1.0). Values near
            1.0 indicate balanced quality; low values show imbalance.
        """
        dims = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        if not dims:
            return 0.0
        max_val = max(dims)
        min_val = min(dims)
        if max_val == 0.0:
            return 0.0
        return min_val / max_val

    def dimensions_above_threshold(self, score: "CriticScore", threshold: float = 0.7) -> int:
        """Count dimensions with scores above threshold.

        Args:
            score: CriticScore to analyze.
            threshold: Minimum acceptable score (default 0.7).

        Returns:
            Number of dimensions meeting or exceeding threshold.
        """
        dims = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        return sum(1 for v in dims if v >= threshold)

    def overall_vs_best_dimension(self, score: "CriticScore") -> float:
        """Compare overall score to strongest dimension.

        Args:
            score: CriticScore with overall and dimension scores.

        Returns:
            Difference (overall - max_dimension). Positive values indicate
            weighted aggregation boosts overall above individual dimensions.
        """
        overall = getattr(score, "overall", 0.0)
        dims = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        if not dims:
            return 0.0
        return overall - max(dims)

    def score_consistency_coefficient(self, score: "CriticScore") -> float:
        """Calculate coefficient of variation (CV) for dimension scores.

        Returns:
            CV ratio (std_dev / mean). Low CV indicates consistent scores
            across dimensions; high CV shows variability.
        """
        dims = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        if not dims:
            return 0.0
        mean_val = sum(dims) / len(dims)
        if mean_val == 0.0:
            return 0.0
        variance = sum((v - mean_val) ** 2 for v in dims) / len(dims)
        std_dev = variance ** 0.5
        return std_dev / mean_val

    def recommendation_density(self, score: "CriticScore") -> float:
        """Calculate density of recommendations relative to weaknesses.

        Args:
            score: CriticScore with recommendations and weaknesses.

        Returns:
            Ratio (recommendations / (weaknesses + 1)). Higher values indicate
            more actionable guidance per identified problem.
        """
        rec_count = len(getattr(score, "recommendations", []))
        weak_count = len(getattr(score, "weaknesses", [])) + 1  # +1 to avoid division by zero
        return rec_count / weak_count

    def dimension_iqr(self, score: "CriticScore") -> float:
        """Return the interquartile range (IQR) of dimension values in a score.

        Args:
            score: CriticScore whose dimension values are analysed.

        Returns:
            Float IQR (Q3 - Q1) across the 6 evaluation dimensions;
            ``0.0`` when fewer than 4 dimension values are available.
        """
        vals = sorted(getattr(score, d, 0.0) for d in self._DIMENSIONS)
        if len(vals) < 4:
            return 0.0
        n = len(vals)
        q1_idx = n // 4
        q3_idx = (3 * n) // 4
        return vals[q3_idx] - vals[q1_idx]

    def dimension_coefficient_of_variation(self, score: "CriticScore") -> float:
        """Return the coefficient of variation (std / mean) of dimension values.

        Args:
            score: CriticScore whose dimension values are analysed.

        Returns:
            Float CV; ``0.0`` when mean is zero or no dimensions exist.
        """
        vals = [getattr(score, d, 0.0) for d in self._DIMENSIONS]
        if not vals:
            return 0.0
        mean_val = sum(vals) / len(vals)
        if mean_val == 0.0:
            return 0.0
        variance = sum((v - mean_val) ** 2 for v in vals) / len(vals)
        return variance ** 0.5 / mean_val


# Export public API
__all__ = [
    'OntologyCritic',
    'CriticScore',
    'DIMENSION_WEIGHTS',
]
