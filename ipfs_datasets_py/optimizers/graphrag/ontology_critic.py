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
    - Completeness (25%): Coverage of key concepts and relationships
    - Consistency (25%): Internal logical consistency
    - Clarity (15%): Clear entity definitions and relationships
    - Granularity (15%): Appropriate level of detail
    - Domain Alignment (20%): Adherence to domain conventions

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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.optimizers.common.base_critic import BaseCritic, CriticResult
from ipfs_datasets_py.optimizers.common.backend_selection import resolve_backend_settings

logger = logging.getLogger(__name__)


# Evaluation dimension weights (must sum to 1.0)
DIMENSION_WEIGHTS = {
    'completeness': 0.25,
    'consistency': 0.25,
    'clarity': 0.15,
    'granularity': 0.15,
    'domain_alignment': 0.20,
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
        ...     domain_alignment=0.88
        ... )
        >>> print(f"Overall: {score.overall:.2f}")
    """
    
    completeness: float
    consistency: float
    clarity: float
    granularity: float
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

        Order: ``[completeness, consistency, clarity, granularity, domain_alignment]``.

        Returns:
            List of 5 floats in the canonical dimension order.

        Example:
            >>> score.to_list()
            [0.8, 0.7, 0.6, 0.5, 0.9]
        """
        return [
            self.completeness,
            self.consistency,
            self.clarity,
            self.granularity,
            self.domain_alignment,
        ]

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
        axes = ["completeness", "consistency", "clarity", "granularity", "domain_alignment"]
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
        dims = ["completeness", "consistency", "clarity", "granularity", "domain_alignment"]
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
            A string like ``CriticScore(overall=0.8210, C:0.80 Co:0.85 Cl:0.75 G:0.80 DA:0.88)``
        """
        dim_abbr = {
            'completeness': 'C',
            'consistency': 'Co', 
            'clarity': 'Cl',
            'granularity': 'G',
            'domain_alignment': 'DA'
        }
        dims_str = ' '.join(
            f"{dim_abbr[dim]}:{getattr(self, dim):.2f}"
            for dim in ['completeness', 'consistency', 'clarity', 'granularity', 'domain_alignment']
        )
        return f"CriticScore(overall={self.overall:.4f}, {dims_str})"


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
        domain_alignment = self._evaluate_domain_alignment(ontology, context)
        
        # Identify strengths and weaknesses
        strengths = self._identify_strengths(
            completeness, consistency, clarity, granularity, domain_alignment
        )
        weaknesses = self._identify_weaknesses(
            completeness, consistency, clarity, granularity, domain_alignment
        )
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            ontology, context, completeness, consistency, clarity,
            granularity, domain_alignment
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
                except Exception:
                    pass  # never let a callback crash the batch

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

        _DIMS = ("completeness", "consistency", "clarity", "granularity", "domain_alignment")

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

        _DIMS = ("completeness", "consistency", "clarity", "granularity", "domain_alignment")
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
        dims = ["completeness", "consistency", "clarity", "granularity", "domain_alignment"]
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
        dims = ["completeness", "consistency", "clarity", "granularity", "domain_alignment"]
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
        _DIMS = ("completeness", "consistency", "clarity", "granularity", "domain_alignment")
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
            dims = ("completeness", "consistency", "clarity", "granularity", "domain_alignment")
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

    def _identify_strengths(
        self,
        completeness: float,
        consistency: float,
        clarity: float,
        granularity: float,
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
        if domain_alignment >= threshold:
            strengths.append("Good adherence to domain conventions")
        
        return strengths
    
    def _identify_weaknesses(
        self,
        completeness: float,
        consistency: float,
        clarity: float,
        granularity: float,
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
        dims = ["completeness", "consistency", "clarity", "granularity", "domain_alignment", "overall"]
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
        dims = ["completeness", "consistency", "clarity", "granularity", "domain_alignment"]
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
        dims = ["completeness", "consistency", "clarity", "granularity", "domain_alignment"]
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
        dims = ["completeness", "consistency", "clarity", "granularity", "domain_alignment"]
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
        dims = ["completeness", "consistency", "clarity", "granularity", "domain_alignment"]
        return {d: round(target - getattr(score, d), 6) for d in dims}

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

    def _generate_recommendations(
        self,
        ontology: Dict[str, Any],
        context: Any,
        completeness: float,
        consistency: float,
        clarity: float,
        granularity: float,
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

        # -- Domain alignment recommendations ---------------------------------
        if domain_alignment < 0.7:
            domain = (getattr(context, 'domain', None) or ontology.get('domain', 'general')).lower()
            recommendations.append(
                f"Many entity/relationship types don't align with '{domain}' domain vocabulary. "
                "Review type names and replace generic labels with domain-specific terms."
            )

        return recommendations


# Export public API
__all__ = [
    'OntologyCritic',
    'CriticScore',
    'DIMENSION_WEIGHTS',
]
