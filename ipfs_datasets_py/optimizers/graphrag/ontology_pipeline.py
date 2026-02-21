"""OntologyPipeline — single-entry-point facade for the full ontology workflow.

Wraps :class:`~ipfs_datasets_py.optimizers.graphrag.ontology_generator.OntologyGenerator`,
:class:`~ipfs_datasets_py.optimizers.graphrag.ontology_critic.OntologyCritic`,
:class:`~ipfs_datasets_py.optimizers.graphrag.ontology_mediator.OntologyMediator`, and
:class:`~ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter.OntologyLearningAdapter`
into a single convenience class so callers don't need to wire them up manually.

Usage
-----
.. code-block:: python

    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline

    pipeline = OntologyPipeline(domain="legal")
    result = pipeline.run("Alice must pay Bob by Friday.", data_source="test")
    print(result["score"].overall, result["entities"])
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Result returned by :meth:`OntologyPipeline.run`.

    Attributes:
        ontology: Raw ontology dict (entities + relationships).
        score: :class:`~ontology_critic.CriticScore` for the final ontology.
        entities: Shortcut list of entity dicts from ``ontology['entities']``.
        relationships: Shortcut list of relationship dicts.
        actions_applied: Refinement actions applied by the mediator.
        metadata: Extra timing / adapter stats.
    """
    ontology: Dict[str, Any]
    score: Any  # CriticScore
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    actions_applied: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class OntologyPipeline:
    """Facade that runs the full ontology workflow in a single call.

    Args:
        domain: Domain string passed to the generator/critic context.
        use_llm: Whether to enable LLM extraction/evaluation (default: False).
        max_rounds: Maximum mediator refinement rounds (default: 3).
        logger: Optional :class:`logging.Logger`.
    """

    def __init__(
        self,
        domain: str = "general",
        use_llm: bool = False,
        max_rounds: int = 3,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator,
        )
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
        from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
            OntologyLearningAdapter,
        )

        self.domain = domain
        self._log = logger or _logger
        self._generator = OntologyGenerator()
        self._critic = OntologyCritic(use_llm=use_llm)
        self._mediator = OntologyMediator(
            generator=self._generator,
            critic=self._critic,
            max_rounds=max_rounds,
        )
        self._adapter = OntologyLearningAdapter(domain=domain)

    def run(
        self,
        data: Any,
        *,
        data_source: str = "pipeline",
        data_type: str = "text",
        refine: bool = True,
    ) -> PipelineResult:
        """Extract, evaluate, and optionally refine an ontology from *data*.

        Args:
            data: Input text or data to process.
            data_source: Identifier for the data source (metadata only).
            data_type: Data type hint (``"text"``, ``"json"``, etc.).
            refine: Whether to run the mediator refinement cycle (default: True).

        Returns:
            :class:`PipelineResult` with the final ontology and score.
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerationContext,
        )

        ctx = OntologyGenerationContext(
            data_source=data_source,
            data_type=data_type,
            domain=self.domain,
        )

        # 1. Extract entities
        hint = self._adapter.get_extraction_hint()
        self._log.info("OntologyPipeline.run: threshold_hint=%.3f domain=%s", hint, self.domain)
        extraction = self._generator.extract_entities(data, ctx)

        # 2. Build initial ontology dict
        ontology: Dict[str, Any] = {
            "entities": [
                {
                    "id": e.id, "text": e.text, "type": e.type,
                    "confidence": e.confidence,
                    "properties": getattr(e, "properties", {}),
                }
                for e in extraction.entities
            ],
            "relationships": [
                {
                    "id": r.id, "source_id": r.source_id, "target_id": r.target_id,
                    "type": r.type, "confidence": r.confidence,
                }
                for r in extraction.relationships
            ],
        }

        actions_applied: List[str] = []

        # 3. Evaluate and optionally refine
        if refine:
            score = self._critic.evaluate_ontology(ontology, ctx)
            refined = self._mediator.refine_ontology(ontology, score, ctx)
            ontology = refined
            actions_applied = refined.get("metadata", {}).get("refinement_actions", [])
            score = self._critic.evaluate_ontology(ontology, ctx)
        else:
            score = self._critic.evaluate_ontology(ontology, ctx)

        # 4. Feed result back to adapter
        self._adapter.apply_feedback(
            final_score=score.overall,
            actions=[{"action": a} for a in actions_applied],
        )

        return PipelineResult(
            ontology=ontology,
            score=score,
            entities=ontology.get("entities", []),
            relationships=ontology.get("relationships", []),
            actions_applied=actions_applied,
            metadata={
                "domain": self.domain,
                "adapter_threshold": self._adapter.get_extraction_hint(),
                "entity_count": len(ontology.get("entities", [])),
            },
        )

    def run_batch(
        self,
        docs: List[Any],
        *,
        data_source: str = "pipeline",
        data_type: str = "text",
        refine: bool = True,
    ) -> List[PipelineResult]:
        """Run the full pipeline on each document in *docs*.

        Args:
            docs: List of input texts/data objects.
            data_source: Shared data source identifier.
            data_type: Shared data type hint.
            refine: Whether to run mediator refinement (default: True).

        Returns:
            List of :class:`PipelineResult` in the same order as *docs*.
        """
        return [
            self.run(doc, data_source=data_source, data_type=data_type, refine=refine)
            for doc in docs
        ]

    def warm_cache(
        self,
        reference_data: Any,
        *,
        data_source: str = "warmup",
        data_type: str = "text",
    ) -> None:
        """Pre-evaluate a reference ontology to fill the critic's shared cache.

        Runs the full generation + evaluation pipeline on *reference_data* once
        so subsequent calls to :meth:`run` benefit from a warm
        :attr:`OntologyCritic._SHARED_EVAL_CACHE` and skip redundant evaluation
        of identical ontologies.

        Args:
            reference_data: Input text or data used as the warmup corpus.
            data_source: Data-source identifier string (default: ``"warmup"``).
            data_type: Data-type hint (default: ``"text"``).

        Example:
            >>> pipeline = OntologyPipeline(domain="legal")
            >>> pipeline.warm_cache(REFERENCE_CONTRACT_TEXT)
            >>> result = pipeline.run(new_text)  # critic cache pre-warmed
        """
        self._log.info("Warming pipeline cache with reference data")
        self.run(reference_data, data_source=data_source, data_type=data_type, refine=False)
