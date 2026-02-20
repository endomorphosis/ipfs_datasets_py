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
        temperature: Sampling temperature (0.0 – 1.0).
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
        known = {"provider", "model", "temperature", "max_tokens"}
        extra = {k: v for k, v in d.items() if k not in known}
        return cls(
            provider=d.get("provider", "accelerate"),
            model=d.get("model", "gpt-4"),
            temperature=float(d.get("temperature", 0.3)),
            max_tokens=int(d.get("max_tokens", 2048)),
            extra=extra,
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
    """
    
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
    # BaseCritic interface                                                  #
    # ------------------------------------------------------------------ #

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
        source_data: Optional[Any] = None
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
            
        Returns:
            CriticScore with evaluation results and recommendations
            
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
        import hashlib as _hashlib
        import json as _json

        # LRU-style cache keyed on ontology content hash (skipped when source_data provided)
        if source_data is None:
            try:
                _cache_key = _hashlib.sha256(
                    _json.dumps(ontology, sort_keys=True, default=str).encode()
                ).hexdigest()
                if not hasattr(self, '_eval_cache'):
                    self._eval_cache: dict = {}
                if _cache_key in self._eval_cache:
                    self._log.debug("OntologyCritic cache hit")
                    return self._eval_cache[_cache_key]
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
                'domain': getattr(context, 'domain', 'unknown')
            }
        )
        
        self._log.info(f"Evaluation complete. Overall score: {score.overall:.2f}")
        if _cache_key is not None:
            # Limit cache to 128 entries (simple eviction: clear when full)
            if len(self._eval_cache) >= 128:
                self._eval_cache.clear()
            self._eval_cache[_cache_key] = score
        return score

    def evaluate_batch(
        self,
        ontologies: List[Dict[str, Any]],
        context: Any,
        source_data: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Evaluate a list of ontologies and return aggregated statistics.

        Args:
            ontologies: List of ontology dictionaries to evaluate.
            context: Shared evaluation context for all ontologies.
            source_data: Optional source text passed to each evaluation.

        Returns:
            Dictionary with keys:
                - ``scores``: list of :class:`CriticScore` objects (one per ontology)
                - ``mean_overall``: mean of the per-ontology overall scores
                - ``min_overall``: minimum overall score across the batch
                - ``max_overall``: maximum overall score across the batch
                - ``count``: number of ontologies evaluated
        """
        scores: List[CriticScore] = []
        for ontology in ontologies:
            score = self.evaluate_ontology(ontology, context, source_data=source_data)
            scores.append(score)

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
                    improvements.append(f"{dim}: {val1:.2f} → {val2:.2f}")
                elif val2 < val1:
                    regressions.append(f"{dim}: {val1:.2f} → {val2:.2f}")
        
        return {
            'score1': score1.to_dict() if score1 else None,
            'score2': score2.to_dict() if score2 else None,
            'better': better,
            'improvements': improvements,
            'regressions': regressions,
        }
    
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
        """
        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])

        if not entities:
            return 0.0

        # Sub-score 1: entity count (target ≥ 10 for "complete")
        entity_count_score = min(len(entities) / 10.0, 1.0)

        # Sub-score 2: relationship density (≥ 1 rel per entity)
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
        """
        import re as _re

        entities = ontology.get('entities', [])

        if not entities:
            return 0.0

        # Sub-score 1: property completeness (entities with ≥ 1 property)
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

        score = prop_score * 0.4 + naming_score * 0.3 + text_score * 0.3
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
        """Generate actionable recommendations for improvement."""
        recommendations = []
        
        # Prioritize based on lowest scores
        scores = [
            (completeness, "completeness"),
            (consistency, "consistency"),
            (clarity, "clarity"),
            (granularity, "granularity"),
            (domain_alignment, "domain_alignment")
        ]
        
        # Sort by score (lowest first)
        sorted_scores = sorted(scores, key=lambda x: x[0])
        
        # Generate recommendations for lowest scoring dimensions
        for score, dimension in sorted_scores[:3]:  # Top 3 areas for improvement
            if score < 0.7:
                if dimension == "completeness":
                    recommendations.append(
                        "Add more entities and relationships to improve coverage"
                    )
                elif dimension == "consistency":
                    recommendations.append(
                        "Review and fix logical inconsistencies in relationships"
                    )
                elif dimension == "clarity":
                    recommendations.append(
                        "Add more properties and descriptions to entities"
                    )
                elif dimension == "granularity":
                    recommendations.append(
                        "Adjust the level of detail to be more appropriate"
                    )
                elif dimension == "domain_alignment":
                    recommendations.append(
                        "Better align entity types with domain conventions"
                    )
        
        return recommendations


# Export public API
__all__ = [
    'OntologyCritic',
    'CriticScore',
    'DIMENSION_WEIGHTS',
]
