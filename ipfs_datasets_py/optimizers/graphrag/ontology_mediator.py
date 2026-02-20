"""
Ontology Mediator for GraphRAG Optimization.

This module provides a mediator that coordinates between the ontology generator
and critic, managing multi-round refinement cycles with dynamic prompt generation
based on feedback. Inspired by the mediator from complaint-generator.

The mediator implements an iterative refinement loop where:
1. Generator creates initial ontology
2. Critic evaluates and provides feedback
3. Mediator adapts prompts based on feedback
4. Generator refines ontology
5. Process continues until convergence or max rounds

Key Features:
    - Multi-round refinement cycles
    - Dynamic prompt generation based on critic feedback
    - Convergence detection
    - Extraction history tracking
    - Adaptive strategy selection

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import (
    ...     OntologyMediator,
    ...     OntologyGenerator,
    ...     OntologyCritic,
    ...     OntologyGenerationContext
    ... )
    >>> 
    >>> generator = OntologyGenerator()
    >>> critic = OntologyCritic()
    >>> mediator = OntologyMediator(
    ...     generator=generator,
    ...     critic=critic,
    ...     max_rounds=10,
    ...     convergence_threshold=0.85
    ... )
    >>> 
    >>> state = mediator.run_refinement_cycle(data, context)
    >>> print(f"Converged: {state.converged} after {state.current_round} rounds")

References:
    - complaint-generator mediator: Refinement cycle patterns
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MediatorState:
    """
    Tracks state across refinement rounds.
    
    Maintains complete history of the refinement process including all
    ontology versions, critic scores, and refinement decisions.
    
    Attributes:
        current_ontology: Current version of the ontology
        refinement_history: History of all refinement steps
        critic_scores: Scores from each evaluation round
        converged: Whether refinement has converged
        current_round: Current refinement round number
        total_time_ms: Total time spent in refinement (milliseconds)
        metadata: Additional state metadata
        
    Example:
        >>> state = MediatorState(
        ...     current_ontology=ontology,
        ...     current_round=3,
        ...     converged=False
        ... )
        >>> print(f"Round {state.current_round}, Score: {state.critic_scores[-1].overall}")
    """
    
    current_ontology: Dict[str, Any]
    refinement_history: List[Dict[str, Any]] = field(default_factory=list)
    critic_scores: List[Any] = field(default_factory=list)  # List[CriticScore]
    converged: bool = False
    current_round: int = 0
    total_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_round(
        self,
        ontology: Dict[str, Any],
        score: Any,  # CriticScore
        refinement_action: str
    ):
        """
        Add a refinement round to the history.
        
        Args:
            ontology: Ontology for this round
            score: Critic score for this round
            refinement_action: Description of refinement action taken
        """
        self.current_round += 1
        self.current_ontology = ontology
        self.critic_scores.append(score)
        self.refinement_history.append({
            'round': self.current_round,
            'ontology': ontology,
            'score': score.to_dict() if hasattr(score, 'to_dict') else score,
            'action': refinement_action
        })
    
    def get_score_trend(self) -> str:
        """
        Get the trend of scores over rounds.
        
        Returns:
            'improving', 'stable', or 'degrading'
        """
        if len(self.critic_scores) < 2:
            return 'insufficient_data'
        
        recent_scores = [s.overall for s in self.critic_scores[-3:]]
        
        if recent_scores[-1] > recent_scores[0] + 0.05:
            return 'improving'
        elif recent_scores[-1] < recent_scores[0] - 0.05:
            return 'degrading'
        else:
            return 'stable'


class OntologyMediator:
    """
    Mediates ontology generation and refinement cycles.
    
    The mediator orchestrates the iterative refinement of ontologies by
    coordinating between the generator and critic. It adapts extraction
    prompts based on critic feedback and monitors convergence.
    
    Inspired by the mediator pattern from complaint-generator, adapted
    for ontology refinement with focus on logical consistency and quality.
    
    Attributes:
        generator: OntologyGenerator instance
        critic: OntologyCritic instance
        max_rounds: Maximum number of refinement rounds
        convergence_threshold: Quality score threshold for convergence
        
    Example:
        >>> mediator = OntologyMediator(
        ...     generator=generator,
        ...     critic=critic,
        ...     max_rounds=10,
        ...     convergence_threshold=0.85
        ... )
        >>> 
        >>> state = mediator.run_refinement_cycle(data, context)
        >>> if state.converged:
        ...     print(f"Converged after {state.current_round} rounds")
        >>> else:
        ...     print("Did not converge within max rounds")
    """
    
    def __init__(
        self,
        generator: Any,  # OntologyGenerator
        critic: Any,  # OntologyCritic
        max_rounds: int = 10,
        convergence_threshold: float = 0.85
    ):
        """
        Initialize the ontology mediator.
        
        Args:
            generator: OntologyGenerator for creating/refining ontologies
            critic: OntologyCritic for evaluating quality
            max_rounds: Maximum refinement rounds before stopping
            convergence_threshold: Score threshold for convergence (0.0 to 1.0)
            
        Raises:
            ValueError: If convergence_threshold is not in valid range
        """
        if not 0.0 <= convergence_threshold <= 1.0:
            raise ValueError("convergence_threshold must be between 0.0 and 1.0")
        
        self.generator = generator
        self.critic = critic
        self.max_rounds = max_rounds
        self.convergence_threshold = convergence_threshold
        
        logger.info(
            f"Initialized mediator: max_rounds={max_rounds}, "
            f"threshold={convergence_threshold}"
        )
    
    def generate_prompt(
        self,
        context: Any,  # OntologyGenerationContext
        feedback: Optional[Any] = None  # Optional[CriticScore]
    ) -> str:
        """
        Generate extraction prompt incorporating critic feedback.
        
        Creates a prompt for the generator that incorporates lessons from
        previous rounds of refinement, focusing on areas identified as
        weak by the critic.
        
        Args:
            context: Generation context with domain and strategy
            feedback: Optional critic feedback from previous round
            
        Returns:
            Generated prompt string
            
        Example:
            >>> prompt = mediator.generate_prompt(context, previous_score)
            >>> print(f"Generated prompt: {prompt[:100]}...")
        """
        _DOMAIN_FOCUS: dict[str, str] = {
            'legal': (
                "Focus on legal parties (persons, organisations), obligations, rights, "
                "duties, breaches, penalties, dates, and monetary amounts."
            ),
            'medical': (
                "Focus on patients, diagnoses, symptoms, treatments, medications, "
                "procedures, outcomes, and temporal relationships."
            ),
            'technical': (
                "Focus on software components, services, APIs, interfaces, dependencies, "
                "protocols, events, and version relationships."
            ),
            'financial': (
                "Focus on assets, liabilities, transactions, accounts, payments, "
                "interest rates, counterparties, and risk factors."
            ),
        }

        domain = getattr(context, 'domain', 'general')
        strategy = getattr(getattr(context, 'extraction_strategy', None), 'value', 'hybrid')

        lines: list[str] = [
            f"Extract a structured ontology from the following {domain} domain data.",
            f"Extraction strategy: {strategy}.",
        ]

        # Domain-specific focus
        domain_hint = _DOMAIN_FOCUS.get(domain)
        if domain_hint:
            lines.append(domain_hint)
        else:
            lines.append("Identify key concepts (entities) and the relationships between them.")

        # Standard output schema instruction
        lines.append(
            "For each entity, provide: id (unique slug), type, text (verbatim or canonical name), "
            "and a 'properties' dict with at least one descriptive key."
        )
        lines.append(
            "For each relationship, provide: id, source_id, target_id, type (verb phrase), "
            "and a confidence score."
        )

        # Feedback-driven refinements
        if feedback:
            if getattr(feedback, 'completeness', 1.0) < 0.7:
                lines.append(
                    "⚠ Previous round had LOW COMPLETENESS — ensure broad coverage: "
                    "include at least 10 entities of at least 3 distinct types."
                )
            if getattr(feedback, 'consistency', 1.0) < 0.7:
                lines.append(
                    "⚠ Previous round had LOW CONSISTENCY — every relationship must "
                    "reference entity IDs that exist in the entities list."
                )
            if getattr(feedback, 'clarity', 1.0) < 0.7:
                lines.append(
                    "⚠ Previous round had LOW CLARITY — each entity must have a non-empty "
                    "text field and at least one property."
                )
            if getattr(feedback, 'granularity', 1.0) < 0.7:
                lines.append(
                    "⚠ Previous round had LOW GRANULARITY — aim for ~3 properties per "
                    "entity and ~1.5 relationships per entity."
                )
            if getattr(feedback, 'domain_alignment', 1.0) < 0.7:
                lines.append(
                    f"⚠ Previous round had LOW DOMAIN ALIGNMENT — use {domain}-specific "
                    "vocabulary for entity and relationship types."
                )
            for rec in getattr(feedback, 'recommendations', [])[:3]:
                lines.append(f"• Recommendation: {rec}")

        return " ".join(lines)
    
    def refine_ontology(
        self,
        ontology: Dict[str, Any],
        feedback: Any,  # CriticScore
        context: Any  # OntologyGenerationContext
    ) -> Dict[str, Any]:
        """
        Refine ontology based on critic feedback.
        
        Applies targeted refinements to the ontology based on specific
        weaknesses identified by the critic. Can add missing entities,
        clarify relationships, or fix inconsistencies.
        
        Args:
            ontology: Current ontology to refine
            feedback: Critic feedback with scores and recommendations
            context: Generation context
            
        Returns:
            Refined ontology
            
        Example:
            >>> refined = mediator.refine_ontology(
            ...     ontology,
            ...     critic_score,
            ...     context
            ... )
            >>> print(f"Added {len(refined['entities']) - len(ontology['entities'])} entities")
        """
        import copy as _copy
        import re as _re

        logger.info(f"Refining ontology based on {len(feedback.recommendations)} recommendations")

        refined = _copy.deepcopy(ontology)
        refined.setdefault('entities', [])
        refined.setdefault('relationships', [])

        actions_applied: list[str] = []

        for recommendation in feedback.recommendations:
            rec_lower = recommendation.lower()
            logger.debug(f"Applying recommendation: {recommendation}")

            # Action: add missing entity properties when clarity is low
            if any(k in rec_lower for k in ('property', 'detail', 'clarity', 'definition')):
                for ent in refined['entities']:
                    if isinstance(ent, dict) and not ent.get('properties'):
                        ent['properties'] = {'description': f"Auto-populated for {ent.get('text', ent.get('id', ''))}"}
                actions_applied.append('add_missing_properties')

            # Action: normalize entity/relationship type names to PascalCase
            elif any(k in rec_lower for k in ('naming', 'convention', 'normalize', 'consistent')):
                def _to_pascal(s: str) -> str:
                    return ''.join(w.capitalize() for w in _re.split(r'[_\s]+', s) if w)
                for ent in refined['entities']:
                    if isinstance(ent, dict) and ent.get('type'):
                        ent['type'] = _to_pascal(ent['type'])
                for rel in refined['relationships']:
                    if isinstance(rel, dict) and rel.get('type'):
                        rel['type'] = _to_pascal(rel['type'])
                actions_applied.append('normalize_names')

            # Action: remove orphan entities (no relationships) when completeness is flagged
            elif any(k in rec_lower for k in ('orphan', 'prune', 'coverage', 'coverage')):
                linked_ids: set = set()
                for rel in refined['relationships']:
                    if isinstance(rel, dict):
                        linked_ids.add(rel.get('source_id'))
                        linked_ids.add(rel.get('target_id'))
                before = len(refined['entities'])
                refined['entities'] = [
                    e for e in refined['entities']
                    if not isinstance(e, dict) or e.get('id') in linked_ids
                ]
                pruned = before - len(refined['entities'])
                if pruned:
                    logger.info(f"Pruned {pruned} orphan entities")
                actions_applied.append('prune_orphans')

            # Action: deduplicate entities by (type, text) when consistency is flagged
            elif any(k in rec_lower for k in ('duplicate', 'consistency', 'dedup', 'merge')):
                seen: dict[tuple, str] = {}  # (type, text_lower) → kept id
                keep_ids: set = set()
                id_remap: dict[str, str] = {}
                for ent in refined['entities']:
                    if not isinstance(ent, dict):
                        continue
                    key = (ent.get('type', ''), (ent.get('text') or '').lower())
                    if key not in seen:
                        seen[key] = ent['id']
                        keep_ids.add(ent['id'])
                    else:
                        id_remap[ent['id']] = seen[key]
                refined['entities'] = [e for e in refined['entities'] if isinstance(e, dict) and e.get('id') in keep_ids]
                for rel in refined['relationships']:
                    if isinstance(rel, dict):
                        rel['source_id'] = id_remap.get(rel['source_id'], rel['source_id'])
                        rel['target_id'] = id_remap.get(rel['target_id'], rel['target_id'])
                actions_applied.append('merge_duplicates')

        refined.setdefault('metadata', {})
        refined['metadata']['refinement_actions'] = actions_applied
        logger.info(f"Refinement complete. Actions applied: {actions_applied}")
        return refined
    
    def run_refinement_cycle(
        self,
        data: Any,
        context: Any  # OntologyGenerationContext
    ) -> MediatorState:
        """
        Run complete refinement cycle.
        
        Executes multiple rounds of ontology generation, evaluation, and
        refinement until convergence or max rounds reached. Returns complete
        state including all intermediate results.
        
        Args:
            data: Source data for ontology generation
            context: Generation context with configuration
            
        Returns:
            Final MediatorState with complete refinement history
            
        Example:
            >>> state = mediator.run_refinement_cycle(
            ...     pdf_data,
            ...     context
            ... )
            >>> 
            >>> print(f"Final score: {state.critic_scores[-1].overall:.2f}")
            >>> print(f"Rounds: {state.current_round}")
            >>> print(f"Converged: {state.converged}")
            >>> 
            >>> # Review history
            >>> for round_info in state.refinement_history:
            ...     print(f"Round {round_info['round']}: {round_info['score']['overall']:.2f}")
        """
        import time
        start_time = time.time()
        
        logger.info(f"Starting refinement cycle (max {self.max_rounds} rounds)")
        
        # Generate initial ontology
        initial_ontology = self.generator.generate_ontology(data, context)
        initial_score = self.critic.evaluate_ontology(initial_ontology, context, data)
        
        # Initialize state
        state = MediatorState(
            current_ontology=initial_ontology,
            current_round=0
        )
        state.add_round(initial_ontology, initial_score, "initial_generation")
        
        logger.info(f"Initial score: {initial_score.overall:.2f}")
        
        # Refinement loop
        for round_num in range(1, self.max_rounds):
            # Check convergence
            if initial_score.overall >= self.convergence_threshold:
                logger.info(f"Converged at round {round_num} (score: {initial_score.overall:.2f})")
                state.converged = True
                break
            
            # Generate refined prompt
            prompt = self.generate_prompt(context, initial_score)
            
            # Refine ontology
            refined_ontology = self.refine_ontology(
                state.current_ontology,
                initial_score,
                context
            )
            
            # Evaluate refined version
            refined_score = self.critic.evaluate_ontology(
                refined_ontology,
                context,
                data
            )
            
            # Update state
            state.add_round(
                refined_ontology,
                refined_score,
                f"refinement_round_{round_num}"
            )
            
            logger.info(
                f"Round {round_num}: score={refined_score.overall:.2f} "
                f"(Δ={refined_score.overall - initial_score.overall:+.2f})"
            )
            
            # Check for degradation
            if refined_score.overall < initial_score.overall - 0.1:
                logger.warning("Score degraded significantly, stopping refinement")
                break
            
            # Update for next iteration
            initial_score = refined_score
        
        # Finalize state
        state.total_time_ms = (time.time() - start_time) * 1000
        state.metadata['final_score'] = state.critic_scores[-1].overall
        state.metadata['score_trend'] = state.get_score_trend()
        state.metadata['improvement'] = (
            state.critic_scores[-1].overall - state.critic_scores[0].overall
        )
        
        logger.info(
            f"Refinement cycle complete: {state.current_round} rounds, "
            f"final score={state.metadata['final_score']:.2f}, "
            f"improvement={state.metadata['improvement']:+.2f}"
        )
        
        return state
    
    def check_convergence(
        self,
        state: MediatorState
    ) -> bool:
        """
        Check if refinement has converged.
        
        Convergence is determined by:
        1. Score exceeds threshold
        2. Score has stabilized (no improvement in recent rounds)
        3. Max rounds reached
        
        Args:
            state: Current mediator state
            
        Returns:
            True if converged, False otherwise
        """
        if not state.critic_scores:
            return False
        
        current_score = state.critic_scores[-1].overall
        
        # Check threshold
        if current_score >= self.convergence_threshold:
            return True
        
        # Check stabilization (no improvement in last 3 rounds)
        if len(state.critic_scores) >= 3:
            recent_scores = [s.overall for s in state.critic_scores[-3:]]
            improvement = recent_scores[-1] - recent_scores[0]
            if abs(improvement) < 0.01:  # Less than 1% improvement
                logger.info("Score stabilized, considering as converged")
                return True
        
        return False


# Export public API
__all__ = [
    'OntologyMediator',
    'MediatorState',
]
