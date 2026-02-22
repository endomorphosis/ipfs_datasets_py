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
import uuid

from ipfs_datasets_py.optimizers.common.base_session import BaseSession

logger = logging.getLogger(__name__)


def _new_session_id() -> str:
    return f"mediator-{uuid.uuid4().hex[:8]}"


@dataclass
class MediatorState(BaseSession):
    """Tracks state across refinement rounds.

    Maintains complete history of the refinement process including all
    ontology versions, critic scores, and refinement decisions. Extends
    :class:`BaseSession` for shared round tracking and convergence metadata.

    Attributes:
        current_ontology: Current version of the ontology.
        refinement_history: History of all refinement steps.
        critic_scores: Scores from each evaluation round.
        total_time_ms: Total time spent in refinement (milliseconds).

    Example:
        >>> state = MediatorState(current_ontology=ontology)
        >>> print(f"Round {state.current_round}, Score: {state.critic_scores[-1].overall}")
    """
    
    session_id: str = field(default_factory=_new_session_id)
    domain: str = "graphrag"
    max_rounds: int = 10
    target_score: float = 0.85
    convergence_threshold: float = 0.01
    current_ontology: Dict[str, Any] = field(default_factory=dict)
    refinement_history: List[Dict[str, Any]] = field(default_factory=list)
    critic_scores: List[Any] = field(default_factory=list)  # List[CriticScore]
    total_time_ms: float = 0.0
    
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
        self.start_round()
        self.current_ontology = ontology
        self.critic_scores.append(score)
        round_number = len(self.refinement_history) + 1
        self.refinement_history.append({
            'round': round_number,
            'ontology': ontology,
            'score': score.to_dict() if hasattr(score, 'to_dict') else score,
            'action': refinement_action,
        })

        score_value = 0.0
        if hasattr(score, "overall"):
            score_value = float(score.overall)
        elif isinstance(score, (int, float)):
            score_value = float(score)

        self.record_round(
            score=score_value,
            feedback=[refinement_action],
            artifact_snapshot=ontology,
            metadata={"action": refinement_action},
        )
    
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

    def __repr__(self) -> str:
        """Concise REPL-friendly representation."""
        latest_score = self.critic_scores[-1].overall if self.critic_scores else 0.0
        trend = self.get_score_trend()
        return (
            f"MediatorState(id={self.session_id!r}, rounds={len(self.refinement_history)}/{self.max_rounds}, "
            f"latest_score={latest_score:.3f}, trend={trend})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize MediatorState to a dictionary, including all refinement-specific fields."""
        # Get base session fields from parent
        result = super().to_dict()
        
        # Override rounds serialization to include full detail
        result["rounds"] = [
            {
                "round": r.round_number,
                "score": r.score,
                "feedback": list(r.feedback),
                "artifact_snapshot": r.artifact_snapshot,
                "duration_ms": r.duration_ms,
                "metadata": r.metadata,
            }
            for r in self.rounds
        ]
        
        # Add MediatorState-specific fields
        result["current_ontology"] = self.current_ontology
        result["refinement_history"] = self.refinement_history
        result["critic_scores"] = [
            s.to_dict() if hasattr(s, "to_dict") else s
            for s in self.critic_scores
        ]
        result["total_time_ms"] = self.total_time_ms
        result["convergence_threshold"] = self.convergence_threshold
        
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediatorState":
        """Reconstruct a MediatorState from a dictionary.
        
        Args:
            data: Dictionary as produced by :meth:`to_dict`.
            
        Returns:
            A new MediatorState with all fields restored.
        """
        import datetime as _dt
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        from ipfs_datasets_py.optimizers.common.base_session import RoundRecord
        
        # Create base instance
        state = cls(
            session_id=data.get("session_id", "unknown"),
            domain=data.get("domain", "graphrag"),
            max_rounds=data.get("max_rounds", 10),
            target_score=data.get("target_score", 0.85),
            convergence_threshold=data.get("convergence_threshold", 0.01),
            current_ontology=data.get("current_ontology", {}),
            total_time_ms=data.get("total_time_ms", 0.0),
        )
        
        # Restore refinement history
        state.refinement_history = data.get("refinement_history", [])
        
        # Restore critic scores
        critic_scores_data = data.get("critic_scores", [])
        state.critic_scores = []
        for score_data in critic_scores_data:
            if isinstance(score_data, dict):
                state.critic_scores.append(CriticScore.from_dict(score_data))
            else:
                state.critic_scores.append(score_data)
        
        # Restore base session rounds directly (not via record_round)
        rounds_data = data.get("rounds", [])
        state.rounds = []
        for r in rounds_data:
            round_record = RoundRecord(
                round_number=r.get("round", len(state.rounds) + 1),
                score=r.get("score", 0.0),
                feedback=r.get("feedback", []),
                artifact_snapshot=r.get("artifact_snapshot"),
                duration_ms=r.get("duration_ms", 0.0),
                metadata=r.get("metadata", {}),
            )
            state.rounds.append(round_record)
        
        # Restore convergence state
        state.converged = data.get("converged", False)
        
        # Restore metadata and timestamps
        state.metadata.update(data.get("metadata") or {})
        try:
            state.started_at = _dt.datetime.fromisoformat(data["started_at"])
        except (KeyError, ValueError):
            pass
        if data.get("finished_at"):
            try:
                state.finished_at = _dt.datetime.fromisoformat(data["finished_at"])
            except (ValueError,):
                pass
        
        return state


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
        convergence_threshold: float = 0.85,
        logger: Optional[Any] = None,
    ):
        """
        Initialize the ontology mediator.
        
        Args:
            generator: OntologyGenerator for creating/refining ontologies
            critic: OntologyCritic for evaluating quality
            max_rounds: Maximum refinement rounds before stopping
            convergence_threshold: Score threshold for convergence (0.0 to 1.0)
            logger: Optional :class:`logging.Logger` instance.  If ``None``,
                uses the module-level logger.
            
        Raises:
            ValueError: If convergence_threshold is not in valid range
        """
        import logging as _logging
        if not 0.0 <= convergence_threshold <= 1.0:
            raise ValueError("convergence_threshold must be between 0.0 and 1.0")
        
        self.generator = generator
        self.critic = critic
        self.max_rounds = max_rounds
        self.convergence_threshold = convergence_threshold
        self._log = logger or _logging.getLogger(__name__)
        # Tracks cumulative action invocation counts across all refine_ontology() calls
        self._action_counts: Dict[str, int] = {}
        # Stack of (ontology_snapshot, action_name) for undo support
        self._undo_stack: list = []
        # Tracks unique recommendation phrases seen across all refine_ontology() calls
        self._recommendation_counts: Dict[str, int] = {}
        # Ordered log of (action_name, round_index) entries for action_log()
        self._action_entries: list = []

        self._log.info(
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

        self._log.info(f"Refining ontology based on {len(feedback.recommendations)} recommendations")

        refined = _copy.deepcopy(ontology)
        # Save snapshot BEFORE applying refinements (for undo support)
        self._undo_stack.append(_copy.deepcopy(ontology))
        refined.setdefault('entities', [])
        refined.setdefault('relationships', [])

        actions_applied: list[str] = []

        for recommendation in feedback.recommendations:
            rec_lower = recommendation.lower()
            self._log.debug(f"Applying recommendation: {recommendation}")
            # Track recommendation phrase counts
            self._recommendation_counts[recommendation] = (
                self._recommendation_counts.get(recommendation, 0) + 1
            )

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
                    self._log.info(f"Pruned {pruned} orphan entities")
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

            # Action: link orphan entities via co-occurrence when coverage is flagged
            elif any(k in rec_lower for k in ('missing relationship', 'orphan link', 'add_missing_relationships', 'unlinked')):
                import uuid as _uuid
                linked_ids: set = set()
                for rel in refined['relationships']:
                    if isinstance(rel, dict):
                        linked_ids.add(rel.get('source_id'))
                        linked_ids.add(rel.get('target_id'))
                orphans = [
                    e for e in refined['entities']
                    if isinstance(e, dict) and e.get('id') not in linked_ids
                ]
                # Link consecutive orphan pairs via co_occurrence
                for i in range(0, len(orphans) - 1, 2):
                    src = orphans[i].get('id')
                    tgt = orphans[i + 1].get('id')
                    if src and tgt:
                        refined['relationships'].append({
                            'id': f"auto_{_uuid.uuid4().hex[:8]}",
                            'source_id': src,
                            'target_id': tgt,
                            'type': 'co_occurrence',
                            'confidence': 0.3,
                            'provenance': ['add_missing_relationships'],
                        })
                actions_applied.append('add_missing_relationships')

            # Action: split_entity — when granularity is flagged, detect entities
            # whose text contains multiple comma/conjunction-delimited tokens and
            # replace them with individual entities.
            elif any(k in rec_lower for k in ('split', 'granular', 'too broad', 'overloaded')):
                import uuid as _uuid
                new_entities = []
                removed_ids: set = set()
                for ent in list(refined['entities']):
                    if not isinstance(ent, dict):
                        new_entities.append(ent)
                        continue
                    text = ent.get('text', '')
                    # Only split on " and " or commas with 2+ parts, each ≥ 2 chars
                    import re as _split_re
                    parts = [p.strip() for p in _split_re.split(r'\s+and\s+|,\s*', text) if p.strip()]
                    if len(parts) >= 2 and all(len(p) >= 2 for p in parts):
                        removed_ids.add(ent.get('id'))
                        for part in parts:
                            new_ent = dict(ent)
                            new_ent['id'] = f"split_{_uuid.uuid4().hex[:8]}"
                            new_ent['text'] = part
                            new_ent.setdefault('properties', {})
                            new_ent['properties']['split_from'] = ent.get('id', '')
                            new_entities.append(new_ent)
                    else:
                        new_entities.append(ent)
                if removed_ids:
                    # Remove relationships to/from removed IDs
                    refined['relationships'] = [
                        r for r in refined['relationships']
                        if isinstance(r, dict)
                        and r.get('source_id') not in removed_ids
                        and r.get('target_id') not in removed_ids
                    ]
                    refined['entities'] = new_entities
                    actions_applied.append('split_entity')

            # Action: rename_entity — normalise entity text to Title Case when
            # casing issues are flagged (e.g. "alice" → "Alice", "LONDON" → "London").
            elif any(k in rec_lower for k in ('rename', 'casing', 'normalise', 'normalize name', 'title case')):
                for ent in refined['entities']:
                    if isinstance(ent, dict) and isinstance(ent.get('text'), str):
                        old_text = ent['text']
                        new_text = old_text.title()
                        if new_text != old_text:
                            ent['text'] = new_text
                actions_applied.append('rename_entity')

        refined.setdefault('metadata', {})
        refined['metadata']['refinement_actions'] = actions_applied
        
        # Structured JSON logging for per-round metrics
        try:
            import json as _json
            from datetime import datetime as _datetime
            
            round_number = len(self._undo_stack)
            entity_delta = len(refined.get('entities', [])) - len(ontology.get('entities', []))
            relationship_delta = len(refined.get('relationships', [])) - len(ontology.get('relationships', []))
            
            round_metrics = {
                'event': 'ontology_refinement_round',
                'round': round_number,
                'recommendations_count': len(feedback.recommendations),
                'actions_applied': actions_applied,
                'actions_count': len(actions_applied),
                'entity_delta': entity_delta,
                'relationship_delta': relationship_delta,
                'final_entity_count': len(refined.get('entities', [])),
                'final_relationship_count': len(refined.get('relationships', [])),
                'feedback_score': feedback.overall,
                'feedback_dimensions': {
                    'completeness': feedback.completeness,
                    'consistency': feedback.consistency,
                    'clarity': feedback.clarity,
                    'granularity': getattr(feedback, 'granularity', 0.0),
                    'relationship_coherence': getattr(feedback, 'relationship_coherence', 0.0),
                    'domain_alignment': getattr(feedback, 'domain_alignment', 0.0),
                },
                'timestamp': _datetime.now().isoformat()
            }
            
            # Log as structured JSON
            self._log.info(f"REFINEMENT_ROUND: {_json.dumps(round_metrics)}")
        except Exception as e:
            self._log.debug(f"Could not log structured metrics: {e}")
        
        self._log.info(f"Refinement complete. Actions applied: {actions_applied}")
        # Update cumulative action counts
        for action in actions_applied:
            self._action_counts[action] = self._action_counts.get(action, 0) + 1
            self._action_entries.append({"action": action, "round": len(self._undo_stack)})
        return refined

    def get_action_stats(self) -> Dict[str, int]:
        """Return cumulative per-action invocation counts across all :meth:`refine_ontology` calls.

        Returns:
            Dict mapping action name (str) to number of times it was applied.
            Returns an empty dict if ``refine_ontology`` has not yet been called.
        """
        return dict(self._action_counts)

    def get_action_summary(self, top_n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return action statistics sorted by invocation count (descending).

        Args:
            top_n: If given, limit the result to the *top_n* most-frequent
                actions.  ``None`` (default) returns all actions.

        Returns:
            List of dicts, each with keys:

            * ``"action"`` -- action name.
            * ``"count"`` -- number of times applied.
            * ``"rank"``  -- 1-based rank (1 = most frequent).

        Example:
            >>> summary = mediator.get_action_summary(top_n=3)
            >>> summary[0]["rank"]
            1
        """
        sorted_items = sorted(self._action_counts.items(), key=lambda kv: kv[1], reverse=True)
        if top_n is not None:
            sorted_items = sorted_items[:top_n]
        return [
            {"action": action, "count": count, "rank": rank}
            for rank, (action, count) in enumerate(sorted_items, start=1)
        ]

    def preview_recommendations(
        self,
        ontology: Dict[str, Any],
        score: Any,
        context: Any,
    ) -> List[str]:
        """Return the recommendations that *would* be applied without mutating state.

        Runs the internal recommendation-generation logic (same as the first
        step of :meth:`refine_ontology`) but does **not** apply any actions,
        update counters, or modify the ontology.

        Args:
            ontology: Current ontology dict.
            score: A :class:`~ipfs_datasets_py.optimizers.graphrag.ontology_critic.CriticScore`
                (or any object with a ``.recommendations`` attribute).
            context: Ontology generation context.

        Returns:
            List of recommendation strings that would be processed next round.

        Example:
            >>> recs = mediator.preview_recommendations(ont, score, ctx)
            >>> isinstance(recs, list)
            True
        """
        recs = getattr(score, "recommendations", None)
        if recs is None:
            return []
        return list(recs)

    def undo_last_action(self) -> Dict[str, Any]:
        """Revert the last applied refinement action.

        Returns the ontology snapshot that was saved immediately *before* the
        most-recent :meth:`refine_ontology` call.  The matching entry is removed
        from the internal undo stack so successive calls step further back.

        Returns:
            The ontology dict as it was before the last refinement.

        Raises:
            IndexError: If there is nothing to undo (no refinements have been
                applied yet).

        Example:
            >>> refined = mediator.refine_ontology(ontology, score, ctx)
            >>> original = mediator.undo_last_action()
            >>> original == ontology
            True
        """
        if not self._undo_stack:
            raise IndexError("Nothing to undo: no refinements have been applied")
        return self._undo_stack.pop()

    def undo_all(self) -> Optional[Dict[str, Any]]:
        """Undo all refinements and return the oldest ontology snapshot.

        Pops every entry from the undo stack and returns the first (oldest)
        snapshot, which represents the state before any refinements were applied.

        Returns:
            The oldest ontology snapshot dict, or ``None`` if the stack is empty.

        Example:
            >>> original = mediator.undo_all()
        """
        if not self._undo_stack:
            return None
        oldest = self._undo_stack[0]
        self._undo_stack.clear()
        return oldest

    def get_recommendation_stats(self) -> Dict[str, int]:
        """Return counts of unique recommendation phrases seen across all refinements.

        Each time :meth:`refine_ontology` processes a recommendation, its exact
        string is counted.  This method returns a snapshot of those counts so
        callers can identify the most-frequently-repeated suggestions.

        Returns:
            Dict mapping recommendation phrase (str) to occurrence count.
            Empty if :meth:`refine_ontology` has not been called or no
            recommendations were provided.

        Example:
            >>> mediator.refine_ontology(ont, score, ctx)
            >>> stats = mediator.get_recommendation_stats()
            >>> max(stats, key=stats.get)  # most common recommendation
            'Add more entity properties'
        """
        return dict(self._recommendation_counts)

    def reset_state(self) -> None:
        """Clear all internal mutable state accumulated across refinement calls.

        Resets the following:

        * ``_action_counts`` -- per-action invocation counters.
        * ``_undo_stack`` -- ontology snapshots used by :meth:`undo_last_action`.
        * ``_recommendation_counts`` -- recommendation phrase frequency table.

        After calling this method the mediator behaves as if no refinements
        have yet been applied.

        Example:
            >>> mediator.refine_ontology(ontology, score, ctx)
            >>> mediator.reset_state()
            >>> mediator.get_action_stats()
            {}
        """
        self._action_counts.clear()
        self._undo_stack.clear()
        self._recommendation_counts.clear()

    def reset_all_state(self) -> None:
        """Clear all internal mutable state including the action entry log.

        Like :meth:`reset_state` but additionally clears the ``_action_entries``
        list populated by :meth:`action_log`.

        Example:
            >>> mediator.reset_all_state()
            >>> mediator.action_log()
            []
        """
        self.reset_state()
        self._action_entries.clear()

    def top_recommended_action(self) -> Optional[str]:
        """Return the action name with the highest recommendation count.

        Uses :attr:`_recommendation_counts` which tracks how many times each
        recommendation phrase has been generated.

        Returns:
            Action/recommendation string with the highest frequency, or
            ``None`` if no recommendations have been generated.

        Example:
            >>> mediator.top_recommended_action()
            None
        """
        if not self._recommendation_counts:
            return None
        return max(self._recommendation_counts, key=self._recommendation_counts.get)

    def pending_recommendation(self) -> Optional[str]:
        """Return the top recommendation phrase without modifying any state.

        Alias for :meth:`top_recommended_action`.

        Returns:
            The most-frequent recommendation string, or ``None`` if none have
            been tracked yet.

        Example:
            >>> rec = mediator.pending_recommendation()
        """
        return self.top_recommended_action()

    def most_frequent_action(self) -> Optional[str]:
        """Return the action with the highest cumulative invocation count.

        Uses :attr:`_action_counts` which is updated during
        :meth:`refine_ontology`.

        Returns:
            Action name string, or ``None`` if no actions have been applied.

        Example:
            >>> mediator.most_frequent_action()
            None
        """
        if not self._action_counts:
            return None
        return max(self._action_counts, key=self._action_counts.get)

    def action_count_for(self, action: str) -> int:
        """Return the cumulative invocation count for a specific *action*.

        Args:
            action: Action name string to query.

        Returns:
            Non-negative integer count.  Returns 0 if the action has never
            been applied.

        Example:
            >>> mediator.action_count_for("add_entity")
            0
        """
        return self._action_counts.get(action, 0)

    def action_types(self) -> list:
        """Return a sorted list of distinct action type strings that have been applied.

        Returns:
            Sorted list of action name strings from the action count log.
            Returns an empty list if no actions have been applied.

        Example:
            >>> mediator.action_types()
            []
        """
        return sorted(self._action_counts.keys())

    def total_action_count(self) -> int:
        """Return the total count of all action invocations.

        Sums the per-action counts in :attr:`_action_counts`.

        Returns:
            Non-negative integer total; ``0`` when no actions have been applied.

        Example:
            >>> mediator.total_action_count()
            0
        """
        return sum(self._action_counts.values())

    def top_actions(self, n: int = 3) -> list:
        """Return the top *n* most-frequently applied action names.

        Args:
            n: Maximum number of actions to return (default 3).

        Returns:
            List of action name strings sorted by descending count (ties broken
            alphabetically).  May be shorter than *n* when fewer distinct
            actions have been applied.
        """
        if not self._action_counts:
            return []
        sorted_actions = sorted(
            self._action_counts.keys(),
            key=lambda a: (-self._action_counts[a], a),
        )
        return sorted_actions[:n]

    def undo_depth(self) -> int:
        """Return the number of undoable snapshots in the undo stack.

        Alias for :meth:`get_undo_depth`.

        Returns:
            Non-negative integer count.
        """
        return self.get_undo_depth()

    def reset_action_counts(self) -> int:
        """Clear all accumulated action count statistics.

        Returns:
            Number of action types that were cleared.

        Example:
            >>> n = mediator.reset_action_counts()
        """
        n = len(self._action_counts)
        self._action_counts.clear()
        return n

    def apply_action_bulk(self, actions: list) -> int:
        """Increment action counts for each action name in *actions*.

        This is a convenience method for registering multiple actions at once
        without calling :meth:`get_action_stats` or manual dict surgery.

        Args:
            actions: Sequence of action name strings to record.

        Returns:
            Total number of actions recorded (len of input).

        Example:
            >>> mediator.apply_action_bulk(["add_entity", "add_entity", "remove_rel"])
            3
        """
        for action in actions:
            self._action_counts[action] = self._action_counts.get(action, 0) + 1
        return len(actions)

    def clear_recommendation_history(self) -> int:
        """Clear the recommendation phrase frequency table.

        Removes all entries from :attr:`_recommendation_counts` without
        touching action counts or the undo stack.

        Returns:
            Number of recommendation entries cleared.

        Example:
            >>> n = mediator.clear_recommendation_history()
            >>> mediator.get_recommendation_stats()
            {}
        """
        count = len(self._recommendation_counts)
        self._recommendation_counts.clear()
        return count

    def get_round_count(self) -> int:
        """Return the total number of refinement rounds performed.

        Computed as the length of the undo stack (each round pushes one
        snapshot) plus any rounds that have already been undone.  In
        practice this returns the current undo stack depth — a simple
        proxy for how many rounds have been executed without undo.

        Returns:
            Integer >= 0.

        Example:
            >>> mediator.get_round_count()
            0
        """
        return len(self._undo_stack)

    def action_log(self, max_entries: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent action log entries.

        Each entry is a dict with keys:

        * ``"action"`` -- action name string applied during refinement.
        * ``"round"`` -- undo stack depth at the time of the action.

        Args:
            max_entries: Maximum number of entries to return (most recent).
                Defaults to 50.

        Returns:
            List of entry dicts, newest last.

        Example:
            >>> log = mediator.action_log()
            >>> all("action" in e for e in log)
            True
        """
        return list(self._action_entries[-max_entries:])

    def get_undo_depth(self) -> int:
        """Return the number of snapshots in the undo stack.

        Each call to :meth:`refine_ontology` pushes one snapshot onto the
        stack (before applying changes).  :meth:`undo_last_action` pops one.

        Returns:
            Non-negative integer.

        Example:
            >>> mediator.get_undo_depth()
            0
        """
        return len(self._undo_stack)

    def peek_undo(self) -> Optional[Dict[str, Any]]:
        """Return the top snapshot from the undo stack without popping it.

        Returns:
            The most recent ontology snapshot dict, or ``None`` if the undo
            stack is empty.

        Example:
            >>> snap = mediator.peek_undo()
            >>> snap is not None or mediator.get_undo_depth() == 0
            True
        """
        if not self._undo_stack:
            return None
        return self._undo_stack[-1]

    def stash(self, ontology: Dict[str, Any]) -> int:
        """Push a snapshot of *ontology* onto the undo stack without running a
        refinement step.

        This is useful when the caller wants to manually save a checkpoint that
        can later be restored via :meth:`undo_last_action`.

        Args:
            ontology: Ontology dict to snapshot (deep-copied before storage).

        Returns:
            New undo-stack depth after the stash.

        Example:
            >>> depth = mediator.stash({"entities": [], "relationships": []})
            >>> depth >= 1
            True
        """
        import copy as _copy
        self._undo_stack.append(_copy.deepcopy(ontology))
        return len(self._undo_stack)

    def snapshot_count(self) -> int:
        """Return the number of snapshots currently on the undo stack.

        Alias for :meth:`get_undo_depth`.

        Returns:
            Non-negative integer.

        Example:
            >>> mediator.snapshot_count()
            0
        """
        return len(self._undo_stack)

    def clear_stash(self) -> int:
        """Clear all snapshots from the undo stack.

        Returns:
            Number of snapshots removed.

        Example:
            >>> mediator.stash({"entities": [], "relationships": []})
            >>> mediator.clear_stash()
            1
        """
        count = len(self._undo_stack)
        self._undo_stack.clear()
        return count

    def log_snapshot(self, label: str, ontology: Dict[str, Any]) -> None:
        """Store a labeled snapshot in the undo stack.

        Pushes a deep copy of *ontology* onto the undo stack and records
        *label* in ``_action_entries`` for traceability.

        Args:
            label: Human-readable label for this snapshot.
            ontology: Ontology dict to snapshot.

        Example:
            >>> mediator.log_snapshot("before_refinement", my_ontology)
        """
        import copy as _copy
        self._undo_stack.append(_copy.deepcopy(ontology))
        self._action_entries.append({"action": f"snapshot:{label}", "round": len(self._undo_stack)})

    def set_max_rounds(self, n: int) -> None:
        """Update the maximum refinement rounds at runtime.

        Args:
            n: New value for ``max_rounds`` (must be >= 1).

        Raises:
            ValueError: If *n* < 1.

        Example:
            >>> mediator.set_max_rounds(5)
            >>> mediator.max_rounds
            5
        """
        if n < 1:
            raise ValueError(f"max_rounds must be >= 1; got {n}")
        self.max_rounds = n

    def log_action_summary(self, top_n: Optional[int] = 10) -> None:
        """Log the top action counts at INFO level.

        Calls :meth:`get_action_summary` and emits one INFO log line
        containing a comma-separated ranking of the most-used mediator
        actions.

        Args:
            top_n: How many top entries to include in the log message.

        Example:
            >>> mediator.log_action_summary(top_n=5)
            # logs: "Action summary: [1] refine_ontology=12, ..."
        """
        entries = self.get_action_summary(top_n=top_n)
        if not entries:
            self._log.info("Action summary: (no actions recorded)")
            return
        parts = ", ".join(
            f"[{e['rank']}] {e['action']}={e['count']}" for e in entries
        )
        self._log.info("Action summary: %s", parts)

    def undo_last_action(self) -> Optional[Dict[str, Any]]:
        """Revert the last applied refinement action by popping the undo stack.

        Pops the most recently pushed state from :attr:`_undo_stack` and
        returns it.  The caller is responsible for applying the returned state
        to the ontology.

        Returns:
            The previous ontology state dict, or ``None`` if the undo stack
            is empty.

        Example:
            >>> prev_state = mediator.undo_last_action()
            >>> prev_state is None  # nothing to undo
            True
        """
        if not self._undo_stack:
            raise IndexError("undo stack is empty — no action to undo")
        return self._undo_stack.pop()

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
        
        self._log.info(f"Starting refinement cycle (max {self.max_rounds} rounds)")
        
        # Generate initial ontology
        initial_ontology = self.generator.generate_ontology(data, context)
        initial_score = self.critic.evaluate_ontology(initial_ontology, context, data)
        
        # Initialize state
        state = MediatorState(
            current_ontology=initial_ontology,
            max_rounds=self.max_rounds,
            target_score=self.convergence_threshold,
        )
        state.add_round(initial_ontology, initial_score, "initial_generation")
        
        self._log.info(f"Initial score: {initial_score.overall:.2f}")
        
        # Refinement loop
        for round_num in range(1, self.max_rounds):
            # Check convergence
            if initial_score.overall >= self.convergence_threshold:
                self._log.info(f"Converged at round {round_num} (score: {initial_score.overall:.2f})")
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
            
            self._log.info(
                f"Round {round_num}: score={refined_score.overall:.2f} "
                f"(Δ={refined_score.overall - initial_score.overall:+.2f})"
            )
            
            # Check for degradation
            if refined_score.overall < initial_score.overall - 0.1:
                self._log.warning("Score degraded significantly, stopping refinement")
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
        
        self._log.info(
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
                self._log.info("Score stabilized, considering as converged")
                return True
        
        return False

    def action_frequency(self) -> dict:
        """Return a normalised frequency map of action names.

        Each value is the fraction of total actions for that action type.

        Returns:
            Dict mapping action name → frequency in [0.0, 1.0].
            Empty dict if no actions recorded.
        """
        total = sum(self._action_counts.values())
        if total == 0:
            return {}
        return {k: v / total for k, v in self._action_counts.items()}

    def has_actions(self) -> bool:
        """Return ``True`` if any actions have been recorded.

        Returns:
            ``True`` when at least one action type has a positive count.
        """
        return bool(self._action_counts) and any(v > 0 for v in self._action_counts.values())

    def action_diversity(self) -> int:
        """Return the number of distinct action types that have been used.

        Returns:
            Count of action types with at least one invocation.
        """
        return sum(1 for v in self._action_counts.values() if v > 0)

    def most_used_action(self) -> "str | None":
        """Return the action name with the highest recorded count.

        Returns:
            Action name string, or ``None`` when no actions have been recorded.
        """
        if not self._action_counts:
            return None
        return max(self._action_counts, key=lambda k: self._action_counts[k])

    def least_used_action(self) -> "str | None":
        """Return the action name with the lowest positive recorded count.

        Returns:
            Action name string among actions that have been used at least once,
            or ``None`` when no actions have been recorded.
        """
        active = {k: v for k, v in self._action_counts.items() if v > 0}
        if not active:
            return None
        return min(active, key=lambda k: active[k])

    def undo_stack_summary(self) -> list:
        """Return a list of labels for each item on the mediator's undo stack.

        Walks ``self._undo_stack`` (if it exists and is iterable) and extracts
        the ``"action"`` key when items are dicts, or their string
        representation otherwise.

        Returns:
            List of label strings, oldest first.  Empty list when no undo stack
            is present or when the stack is empty.
        """
        stack = getattr(self, "_undo_stack", None) or []
        labels = []
        for item in stack:
            if isinstance(item, dict):
                labels.append(str(item.get("action", item)))
            else:
                labels.append(str(item))
        return labels

    def undo_stack_depth(self) -> int:
        """Return the number of items currently on the undo stack.

        Returns:
            Integer length of ``_undo_stack``; 0 when no stack exists.
        """
        return len(getattr(self, "_undo_stack", None) or [])

    def total_actions_taken(self) -> int:
        """Return the total number of actions recorded across all action types.

        Returns:
            Sum of all values in ``_action_counts``; ``0`` when no actions taken.
        """
        return sum(self._action_counts.values())

    def unique_action_count(self) -> int:
        """Return the number of distinct action types that have been used.

        Returns:
            Count of action types with at least one recorded use.
        """
        return sum(1 for v in self._action_counts.values() if v > 0)

    def apply_feedback_list(self, scores: list) -> None:
        """Apply a list of ``CriticScore`` objects to the mediator's feedback loop.

        Iterates through each score and calls ``self.apply_feedback(score)``
        for each one, allowing batch ingestion of evaluation results.

        Args:
            scores: List of ``CriticScore`` objects to apply in order.
        """
        for score in scores:
            self.apply_feedback(score)

    def feedback_history_size(self) -> int:
        """Return the number of feedback records stored in the mediator.

        Returns:
            Integer count; ``0`` when no feedback has been recorded.
        """
        history = getattr(self, '_feedback_history', None) or getattr(self, '_feedback', None) or []
        return len(history)

    def action_count_unique(self) -> int:
        """Return the number of distinct action types that have been invoked.

        Returns:
            Integer count of unique action names recorded in
            ``_action_counts``; ``0`` when no actions have been taken.
        """
        return len(self._action_counts)

    def clear_feedback(self) -> int:
        """Clear all recorded feedback history and return how many were removed.

        Clears ``_feedback_history`` and/or ``_feedback`` depending on which
        attribute is present.

        Returns:
            Integer count of records that were removed.
        """
        removed = 0
        if hasattr(self, '_feedback_history') and self._feedback_history:
            removed += len(self._feedback_history)
            self._feedback_history.clear()
        if hasattr(self, '_feedback') and isinstance(self._feedback, list):
            removed += len(self._feedback)
            self._feedback.clear()
        return removed

    def feedback_score_mean(self) -> float:
        """Return the mean feedback score seen by this mediator.

        Reads from ``_feedback_history`` or ``_feedback`` (whichever exists),
        looking for a ``.score`` or ``.final_score`` numeric attribute on each
        record.

        Returns:
            Float mean; ``0.0`` when no feedback records.
        """
        history = getattr(self, '_feedback_history', None) or getattr(self, '_feedback', None) or []
        if not history:
            return 0.0
        scores = []
        for rec in history:
            v = getattr(rec, 'score', None) or getattr(rec, 'final_score', None)
            if isinstance(v, (int, float)):
                scores.append(float(v))
        return sum(scores) / len(scores) if scores else 0.0

    def most_improved_action(self) -> Optional[str]:
        """Return the action type with the highest average score across feedback.

        Scans the mediator's refinement history for feedback scores tagged with
        action types and returns the action with the best mean score.  Falls
        back to returning the most-frequently-used action when no scored
        feedback is available.

        Returns:
            String action type, or ``None`` when no feedback is recorded.
        """
        # Try scored feedback first (populated by subclasses / external callers)
        scored_store = (
            getattr(self, "_feedback_history", None)
            or getattr(self, "_feedback", None)
            or []
        )
        totals: dict = {}
        counts: dict = {}
        for entry in scored_store:
            score = entry.get("score", 0.0) if isinstance(entry, dict) else getattr(entry, "final_score", 0.0)
            actions = entry.get("actions", []) if isinstance(entry, dict) else getattr(entry, "action_types", [])
            for action in actions:
                totals[action] = totals.get(action, 0.0) + score
                counts[action] = counts.get(action, 0) + 1
        if totals:
            return max(totals, key=lambda a: totals[a] / counts[a])
        # Fallback: most-used action from _action_counts
        action_counts = getattr(self, "_action_counts", {})
        if not action_counts:
            return None
        return max(action_counts, key=lambda a: action_counts[a])

    def feedback_count_by_action(self, action: str) -> int:
        """Return how many times *action* appears in ``_action_counts``.

        Args:
            action: Action type string to look up.

        Returns:
            Integer count; 0 when the action has never been recorded.
        """
        return self._action_counts.get(action, 0)

    def action_success_rate(self, action: str) -> float:
        """Return the stored success rate for *action*.

        Uses ``_action_success[action] / _action_count[action]`` when
        available.

        Args:
            action: Action type string.

        Returns:
            Float in [0, 1]; 0.0 when no data is available for the action.
        """
        count = self._action_count.get(action, 0) if hasattr(self, "_action_count") else 0
        success = self._action_success.get(action, 0.0) if hasattr(self, "_action_success") else 0.0
        if count == 0:
            return 0.0
        return float(success) / count

    def action_entropy(self) -> float:
        """Return the Shannon entropy of the action count distribution.

        A uniform distribution gives maximum entropy; a single dominant
        action gives entropy near 0.

        Returns:
            Float; 0.0 when no actions recorded.
        """
        import math
        counts = [v for v in self._action_counts.values() if v > 0]
        total = sum(counts)
        if total == 0:
            return 0.0
        return -sum((c / total) * math.log(c / total) for c in counts)

    def total_action_count(self) -> int:
        """Return the total number of action invocations recorded.

        Returns:
            Integer count; 0 when no actions recorded.
        """
        return sum(self._action_counts.values())

    def action_ratio(self, action: str) -> float:
        """Return the fraction of total actions attributed to a given action.

        Args:
            action: Name of the action to query.

        Returns:
            Float in [0, 1]; 0.0 when no actions or action not found.
        """
        total = sum(self._action_counts.values())
        if total == 0:
            return 0.0
        return self._action_counts.get(action, 0) / total

    def action_mode(self) -> str:
        """Return the action name with the highest count.

        Returns:
            String action name; empty string when no actions recorded.
        """
        if not self._action_counts:
            return ""
        return max(self._action_counts, key=lambda a: self._action_counts[a])

    def action_least_frequent(self) -> str:
        """Return the action name with the lowest count.

        Returns:
            String action name; empty string when no actions recorded.
        """
        if not self._action_counts:
            return ""
        return min(self._action_counts, key=lambda a: self._action_counts[a])

    def action_diversity_score(self) -> float:
        """Return a diversity score based on the entropy of action distribution.

        Returns a value in [0, 1] where 1 = perfectly uniform distribution.

        Returns:
            Float diversity; 0.0 when no actions or only one unique action.
        """
        import math
        total = sum(self._action_counts.values())
        if total == 0 or len(self._action_counts) <= 1:
            return 0.0
        max_entropy = math.log(len(self._action_counts))
        if max_entropy == 0:
            return 0.0
        entropy = -sum(
            (cnt / total) * math.log(cnt / total)
            for cnt in self._action_counts.values()
            if cnt > 0
        )
        return entropy / max_entropy

    def action_gini(self) -> float:
        """Return the Gini coefficient of the action count distribution.

        A value of 0 = perfect equality; 1 = complete concentration.

        Returns:
            Float Gini coefficient; 0.0 when no actions or only one action type.
        """
        counts = list(self._action_counts.values())
        n = len(counts)
        if n <= 1 or sum(counts) == 0:
            return 0.0
        counts_sorted = sorted(counts)
        total = sum(counts_sorted)
        numerator = sum((i + 1) * v for i, v in enumerate(counts_sorted))
        return (2 * numerator) / (n * total) - (n + 1) / n


# Export public API
__all__ = [
    'OntologyMediator',
    'MediatorState',
]
