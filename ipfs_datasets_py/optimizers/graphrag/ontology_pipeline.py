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

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this result to a plain dictionary."""
        score_data = self.score.to_dict() if hasattr(self.score, "to_dict") else self.score
        return {
            "ontology": self.ontology,
            "score": score_data,
            "entities": self.entities,
            "relationships": self.relationships,
            "actions_applied": self.actions_applied,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PipelineResult":
        """Deserialize a :class:`PipelineResult` from a dictionary."""
        score_obj = d.get("score")
        if isinstance(score_obj, dict):
            try:
                from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore

                score_obj = CriticScore.from_dict(score_obj)
            except Exception:
                pass

        return cls(
            ontology=dict(d.get("ontology", {})),
            score=score_obj,
            entities=list(d.get("entities", [])),
            relationships=list(d.get("relationships", [])),
            actions_applied=list(d.get("actions_applied", [])),
            metadata=dict(d.get("metadata", {})),
        )

    def to_json(self) -> str:
        """Serialize this result to JSON."""
        import json

        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> "PipelineResult":
        """Deserialize a :class:`PipelineResult` from JSON."""
        import json

        return cls.from_dict(json.loads(payload))


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

        self._domain = domain
        self._log = logger or _logger
        self._generator = OntologyGenerator()
        self._critic = OntologyCritic(use_llm=use_llm)
        self._mediator = OntologyMediator(
            generator=self._generator,
            critic=self._critic,
            max_rounds=max_rounds,
        )
        self._adapter = OntologyLearningAdapter(domain=domain)
        self._run_history: List["PipelineResult"] = []

    def __repr__(self) -> str:
        """Return a concise developer-readable summary of this pipeline."""
        return (
            f"OntologyPipeline("
            f"domain={self._domain!r}, "
            f"runs={len(self._run_history)})"
        )

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

        result = PipelineResult(
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
        self._run_history.append(result)
        return result

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

    def clone(self) -> "OntologyPipeline":
        """Return a deep copy of this pipeline with completely fresh state.

        The clone shares the same configuration (``domain``, ``use_llm``,
        ``max_rounds``) but gets brand-new generator, critic, mediator, and
        adapter instances so runs against the clone don't pollute this
        pipeline's internal state (caches, action counts, etc.).

        Returns:
            A new :class:`OntologyPipeline` with the same settings.

        Example:
            >>> pipeline = OntologyPipeline(domain="legal")
            >>> pipeline.run("some text.", data_source="s1")
            >>> fresh = pipeline.clone()
            >>> fresh._adapter is not pipeline._adapter
            True
        """
        return OntologyPipeline(
            domain=self.domain,
            use_llm=getattr(self._critic, "_use_llm", False),
            max_rounds=self._mediator.max_rounds,
            logger=self._log if self._log is not _logger else None,
        )

    async def run_async(
        self,
        data: Any,
        *,
        data_source: str = "pipeline",
        data_type: str = "text",
        refine: bool = True,
    ) -> "PipelineResult":
        """Async coroutine wrapper around :meth:`run`.

        Delegates to the synchronous :meth:`run` in a thread-pool executor so
        it does not block the event loop.

        Args:
            data: Input text or data.
            data_source: Data source identifier (default: ``"pipeline"``).
            data_type: Data type hint (default: ``"text"``).
            refine: Whether to run mediator refinement (default: True).

        Returns:
            :class:`PipelineResult` from the synchronous :meth:`run`.

        Example:
            >>> result = await pipeline.run_async("Alice works at ACME.")
        """
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.run(data, data_source=data_source, data_type=data_type, refine=refine),
        )

    def as_dict(self) -> Dict[str, Any]:
        """Serialize pipeline configuration to a plain dictionary.

        Returns a snapshot of the pipeline's constructor-level settings.
        The returned dict can be used to recreate an equivalent pipeline with
        :class:`OntologyPipeline(**as_dict())`.

        Returns:
            Dict with keys ``domain``, ``use_llm``, and ``max_rounds``.

        Example:
            >>> d = pipeline.as_dict()
            >>> clone = OntologyPipeline(**d)
        """
        return {
            "domain": self.domain,
            "use_llm": getattr(self._critic, "_use_llm", False),
            "max_rounds": self._mediator.max_rounds,
        }

    def reset(self) -> None:
        """Reset internal adapter and mediator state.

        Clears the learning adapter's feedback history and the mediator's
        undo stack and action counts, returning the pipeline to a clean
        post-construction state without recreating the underlying objects.

        Example:
            >>> pipeline.reset()
        """
        self._adapter.reset()
        if hasattr(self._mediator, "reset_state"):
            self._mediator.reset_state()

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "OntologyPipeline":
        """Reconstruct an :class:`OntologyPipeline` from a plain dict.

        Complements :meth:`as_dict` for configuration round-trips.

        Args:
            d: Dict as returned by :meth:`as_dict` (keys ``domain``,
                ``use_llm``, ``max_rounds``).

        Returns:
            A new :class:`OntologyPipeline` instance.

        Example:
            >>> p2 = OntologyPipeline.from_dict(pipeline.as_dict())
        """
        return cls(
            domain=d.get("domain", "general"),
            use_llm=bool(d.get("use_llm", False)),
            max_rounds=int(d.get("max_rounds", 3)),
        )

    def run_with_metrics(
        self,
        data: Any,
        *,
        data_source: str = "pipeline",
        data_type: str = "text",
        refine: bool = True,
    ) -> Dict[str, Any]:
        """Run the pipeline and return a metrics dict alongside the result.

        Wraps :meth:`run` and captures wall-clock latency and score.

        Args:
            data: Input text or data.
            data_source: Data source identifier (default: ``"pipeline"``).
            data_type: Data type hint (default: ``"text"``).
            refine: Whether to run mediator refinement (default: True).

        Returns:
            Dict with keys:

            * ``"result"`` -- the :class:`PipelineResult`.
            * ``"latency_seconds"`` -- wall-clock seconds elapsed.
            * ``"score"`` -- the overall critic score (float).
            * ``"entity_count"`` -- number of entities in the result.

        Example:
            >>> metrics = pipeline.run_with_metrics("Alice works at ACME.")
            >>> metrics["latency_seconds"] >= 0
            True
        """
        import time
        start = time.perf_counter()
        result = self.run(data, data_source=data_source, data_type=data_type, refine=refine)
        latency = time.perf_counter() - start
        return {
            "result": result,
            "latency_seconds": latency,
            "score": result.score.overall if hasattr(result.score, "overall") else float(result.score),
            "entity_count": len(result.entities),
        }

    def with_domain(self, domain: str) -> "OntologyPipeline":
        """Return a new pipeline with *domain* overridden.

        All other settings (``use_llm``, ``max_rounds``) are inherited from
        ``self``.  The current pipeline is **not** mutated.

        Args:
            domain: Domain string for the new pipeline.

        Returns:
            A fresh :class:`OntologyPipeline` instance.

        Example:
            >>> legal_pipeline = pipeline.with_domain("legal")
        """
        d = self.as_dict()
        d["domain"] = domain
        return OntologyPipeline.from_dict(d)

    def clone_with(
        self,
        domain: Optional[str] = None,
        max_rounds: Optional[int] = None,
        use_llm: Optional[bool] = None,
    ) -> "OntologyPipeline":
        """Return a shallow clone with selected fields overridden.

        Only the supplied keyword arguments are changed; everything else is
        inherited from ``self``.

        Args:
            domain: Override the domain string.
            max_rounds: Override the maximum refinement rounds.
            use_llm: Override the LLM flag.

        Returns:
            A new :class:`OntologyPipeline` instance.

        Example:
            >>> fast = pipeline.clone_with(max_rounds=1)
        """
        d = self.as_dict()
        if domain is not None:
            d["domain"] = domain
        if max_rounds is not None:
            d["max_rounds"] = max_rounds
        if use_llm is not None:
            d["use_llm"] = use_llm
        return OntologyPipeline.from_dict(d)

    def get_stage_names(self) -> List[str]:
        """Return the ordered names of the pipeline stages.

        The canonical GraphRAG pipeline has three stages: extraction,
        evaluation, and refinement.

        Returns:
            List of stage-name strings in execution order.

        Example:
            >>> pipeline.get_stage_names()
            ['extraction', 'evaluation', 'refinement']
        """
        return ["extraction", "evaluation", "refinement"]

    @property
    def domain_list(self) -> List[str]:
        """Return a list of known domain presets supported by the pipeline.

        These are the well-tested domain strings that receive specialised
        entity-type vocabularies in the underlying generator.

        Returns:
            Sorted list of domain preset strings.

        Example:
            >>> "legal" in OntologyPipeline().domain_list
            True
        """
        return sorted([
            "general",
            "legal",
            "medical",
            "finance",
            "science",
            "technology",
            "news",
        ])

    @domain_list.setter
    def domain_list(self, value: List[str]) -> None:
        raise AttributeError("domain_list is read-only; set pipeline.domain instead.")

    @property
    def domain(self) -> str:  # type: ignore[override]
        """The active domain string for this pipeline."""
        return self._domain

    @domain.setter
    def domain(self, value: str) -> None:
        """Update the domain at runtime.

        Args:
            value: New domain string (e.g. ``"legal"``, ``"medical"``).

        Example:
            >>> pipeline.domain = "legal"
            >>> pipeline.domain
            'legal'
        """
        self._domain = value

    @property
    def history(self) -> List["PipelineResult"]:
        """Return a read-only view of past :class:`PipelineResult` objects.

        Each call to :meth:`run` appends one entry.  Useful for inspecting
        how scores evolved over repeated invocations.

        Returns:
            List of :class:`PipelineResult` in chronological order.

        Example:
            >>> len(pipeline.history) == 0  # before any run
            True
        """
        return list(self._run_history)

    def total_runs(self) -> int:
        """Return the total number of times :meth:`run` has been called.

        Returns:
            Non-negative integer count.

        Example:
            >>> pipeline.total_runs()
            0
        """
        return len(self._run_history)

    def run_count(self) -> int:
        """Return the total number of times :meth:`run` has been called.

        Alias for :meth:`total_runs` for a more natural name.

        Returns:
            Non-negative integer count.

        Example:
            >>> pipeline.run_count()
            0
        """
        return self.total_runs()

    def last_score(self) -> float:
        """Return the ``overall`` score from the most recent :meth:`run` call.

        Returns:
            ``PipelineResult.score.overall`` of the last run, or 0.0 if
            no runs have been executed.

        Example:
            >>> pipeline.last_score()
            0.0
        """
        if not self._run_history:
            return 0.0
        return self._run_history[-1].score.overall

    def run_batch(self, texts: List[str], **kwargs: Any) -> List[Any]:
        """Run :meth:`run` on each text in *texts* and return the results list.

        Args:
            texts: Sequence of raw text strings to process.
            **kwargs: Additional keyword arguments forwarded to each :meth:`run`
                call (e.g. ``data_source``, ``threshold_hint``).

        Returns:
            List of :class:`PipelineResult` objects in the same order as
            *texts*.  An empty list is returned for an empty input.

        Example:
            >>> results = pipeline.run_batch(["Alice at ACME.", "Bob at Corp."])
            >>> len(results) == 2
            True
        """
        return [self.run(text, **kwargs) for text in texts]

    def reset(self) -> int:
        """Clear the run history and reset internal mediator state.

        Does not affect the underlying generator or critic configuration.

        Returns:
            Number of history entries that were cleared.

        Example:
            >>> pipeline.reset()
            0
        """
        n = len(self._run_history)
        self._run_history.clear()
        self._mediator.reset_all_state()
        return n

    def has_run(self) -> bool:
        """Return ``True`` if :meth:`run` has been called at least once.

        Returns:
            Boolean.

        Example:
            >>> pipeline.has_run()
            False
        """
        return len(self._run_history) > 0

    def score_trend(self) -> List[float]:
        """Return the sequence of ``overall`` scores across all runs.

        Returns:
            List of floats in chronological order.  Empty list before any
            calls to :meth:`run`.

        Example:
            >>> pipeline.score_trend()
            []
        """
        return [r.score.overall for r in self._run_history]

    def best_run(self) -> Optional[Any]:
        """Return the :class:`PipelineResult` with the highest ``overall`` score.

        Returns:
            The run with the maximum ``score.overall``, or ``None`` if no
            runs have been executed.

        Example:
            >>> best = pipeline.best_run()
        """
        if not self._run_history:
            return None
        return max(self._run_history, key=lambda r: r.score.overall)

    def warmup(self, n_texts: int = 3) -> None:
        """Pre-warm the pipeline by running *n_texts* dummy single-word texts.

        Results are discarded and do NOT appear in :meth:`history`.  This is
        useful to trigger any lazy initialization (e.g. LLM model loading)
        before live requests.

        Args:
            n_texts: Number of dummy runs to execute.  Defaults to 3.

        Example:
            >>> pipeline.warmup()
        """
        saved = list(self._run_history)
        for i in range(n_texts):
            try:
                self.run(f"warmup_{i}")
            except Exception:
                pass
        self._run_history[:] = saved

    def summary(self) -> str:
        """Return a compact one-line description of this pipeline's configuration.

        Returns:
            String of the form ``"OntologyPipeline(domain=<domain>, use_llm=<bool>, stages=<n>)"``.

        Example:
            >>> print(pipeline.summary())
            OntologyPipeline(domain=legal, use_llm=False, stages=3)
        """
        stages = len(self.get_stage_names())
        use_llm = getattr(self._critic, "use_llm", False)
        return f"OntologyPipeline(domain={self.domain}, use_llm={use_llm}, stages={stages})"

    def average_run_score(self) -> float:
        """Return the mean ``score.overall`` across all completed runs.

        Returns:
            Mean overall score; ``0.0`` when no runs have been made.

        Example:
            >>> pipeline.average_run_score()
            0.0
        """
        if not self._run_history:
            return 0.0
        return sum(r.score.overall for r in self._run_history) / len(self._run_history)

    def score_at(self, index: int) -> float:
        """Return the ``score.overall`` for the run at *index* in history.

        Args:
            index: Zero-based position in run history.

        Returns:
            ``PipelineResult.score.overall`` at the given index.

        Raises:
            IndexError: If *index* is out of bounds.

        Example:
            >>> pipeline.score_at(0)
        """
        return self._run_history[index].score.overall

    def worst_run(self) -> Optional[Any]:
        """Return the :class:`PipelineResult` with the lowest ``overall`` score."""
        if not self._run_history:
            return None
        return min(self._run_history, key=lambda r: r.score.overall)

    def median_run_score(self) -> float:
        """Return the median ``overall`` score across run history."""
        if not self._run_history:
            return 0.0
        vals = sorted(r.score.overall for r in self._run_history)
        n = len(vals)
        mid = n // 2
        if n % 2 == 1:
            return vals[mid]
        return (vals[mid - 1] + vals[mid]) / 2.0

    def score_variance(self) -> float:
        """Return the variance of ``overall`` scores across run history.

        Returns:
            Variance as a float; ``0.0`` when fewer than 2 runs have been recorded.
        """
        if len(self._run_history) < 2:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        mean = sum(scores) / len(scores)
        return sum((s - mean) ** 2 for s in scores) / len(scores)

    def score_stddev(self) -> float:
        """Return the standard deviation of run scores.

        Returns:
            Std-dev as a float; ``0.0`` when fewer than 2 runs are recorded.
        """
        import math as _math
        return _math.sqrt(self.score_variance())

    def passing_run_count(self, threshold: float = 0.6) -> int:
        """Return the number of runs whose ``overall`` score exceeds *threshold*.

        Args:
            threshold: Minimum score (exclusive) to count a run as passing.

        Returns:
            Integer count.
        """
        return sum(1 for r in self._run_history if r.score.overall > threshold)

    def run_summary(self) -> dict:
        """Return a compact summary of run history statistics.

        Returns:
            Dict with keys ``count``, ``mean``, ``min``, ``max``, and
            ``trend`` (list of overall scores in order).  When no runs have
            been recorded, numeric fields are ``0.0`` and ``trend`` is ``[]``.
        """
        if not self._run_history:
            return {"count": 0, "mean": 0.0, "min": 0.0, "max": 0.0, "trend": []}
        scores = [r.score.overall for r in self._run_history]
        return {
            "count": len(scores),
            "mean": sum(scores) / len(scores),
            "min": min(scores),
            "max": max(scores),
            "trend": list(scores),
        }

    def is_stable(self, threshold: float = 0.02, window: int = 3) -> bool:
        """Return ``True`` if the last *window* runs have low score variance.

        ``Stable`` means the variance of the most recent *window* overall
        scores is at or below *threshold*.

        Args:
            threshold: Maximum allowed variance (default 0.02).
            window: Number of most recent runs to examine (default 3).

        Returns:
            ``True`` when the window variance is ≤ *threshold*; ``False``
            when fewer than *window* runs are available.
        """
        if len(self._run_history) < window:
            return False
        recent = [r.score.overall for r in self._run_history[-window:]]
        mean = sum(recent) / len(recent)
        variance = sum((s - mean) ** 2 for s in recent) / len(recent)
        return variance <= threshold

    def top_n_runs(self, n: int = 3) -> list:
        """Return the top *n* run results ordered by descending ``overall`` score.

        Args:
            n: Maximum number of runs to return (default 3).

        Returns:
            List of run result objects sorted by ``score.overall`` descending.
            May be shorter than *n* when fewer runs are recorded.
        """
        if not self._run_history:
            return []
        sorted_runs = sorted(self._run_history, key=lambda r: r.score.overall, reverse=True)
        return sorted_runs[:n]

    def score_momentum(self, window: int = 3) -> float:
        """Return the average score change over the last *window* entries.

        Positive means improving, negative means declining, zero means flat.

        Args:
            window: Number of most-recent runs to inspect (default 3).

        Returns:
            Mean score delta per step; ``0.0`` if fewer than 2 runs.
        """
        entries = self._run_history[-window:] if len(self._run_history) >= 2 else []
        if len(entries) < 2:
            return 0.0
        scores = [r.score.overall for r in entries]
        diffs = [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]
        return sum(diffs) / len(diffs)

    def worst_n_runs(self, n: int = 3) -> list:
        """Return the bottom *n* run results ordered by ascending ``overall`` score.

        Args:
            n: Maximum number of runs to return (default 3).

        Returns:
            List of run result objects sorted by ``score.overall`` ascending.
        """
        if not self._run_history:
            return []
        sorted_runs = sorted(self._run_history, key=lambda r: r.score.overall)
        return sorted_runs[:n]

    def pass_rate(self, threshold: float = 0.6) -> float:
        """Return fraction of runs whose ``score.overall`` is >= *threshold*.

        Args:
            threshold: Passing score threshold (default 0.6).

        Returns:
            Float in [0.0, 1.0]; ``0.0`` when no runs recorded.
        """
        if not self._run_history:
            return 0.0
        passing = sum(1 for r in self._run_history if r.score.overall >= threshold)
        return passing / len(self._run_history)

    def score_range(self) -> tuple:
        """Return ``(min_score, max_score)`` across all recorded runs.

        Returns:
            Tuple of floats; ``(0.0, 0.0)`` when no runs recorded.
        """
        if not self._run_history:
            return (0.0, 0.0)
        scores = [r.score.overall for r in self._run_history]
        return (min(scores), max(scores))

    def run_count_above(self, threshold: float = 0.6) -> int:
        """Return the number of runs with ``score.overall > threshold``.

        Args:
            threshold: Score threshold (exclusive, default 0.6).

        Returns:
            Count of runs strictly above the threshold.
        """
        return sum(1 for r in self._run_history if r.score.overall > threshold)

    def average_score(self) -> float:
        """Return the mean ``score.overall`` across all recorded runs.

        Returns:
            Mean score float; ``0.0`` when no runs recorded.
        """
        if not self._run_history:
            return 0.0
        return sum(r.score.overall for r in self._run_history) / len(self._run_history)

    def best_score(self) -> float:
        """Return the highest ``score.overall`` across all recorded runs.

        Returns:
            Maximum score float; ``0.0`` when no runs recorded.
        """
        if not self._run_history:
            return 0.0
        return max(r.score.overall for r in self._run_history)

    def worst_score(self) -> float:
        """Return the lowest ``score.overall`` across all recorded runs.

        Returns:
            Minimum score float; ``0.0`` when no runs recorded.
        """
        if not self._run_history:
            return 0.0
        return min(r.score.overall for r in self._run_history)

    def stabilization_index(self, window: int = 5) -> float:
        """Return a score-change metric for the last *window* runs.

        The stabilization index is ``1 - mean(abs(score_diffs))`` clamped to
        [0.0, 1.0].  A value close to 1.0 means the pipeline has stabilized;
        close to 0.0 means high variability.

        Args:
            window: Number of most-recent runs to inspect (default 5).

        Returns:
            Float in [0.0, 1.0]; ``0.0`` when fewer than 2 runs recorded.
        """
        entries = self._run_history[-window:] if len(self._run_history) >= 2 else []
        if len(entries) < 2:
            return 0.0
        scores = [r.score.overall for r in entries]
        diffs = [abs(scores[i + 1] - scores[i]) for i in range(len(scores) - 1)]
        mean_change = sum(diffs) / len(diffs)
        return max(0.0, min(1.0, 1.0 - mean_change))

    def run_improvement(self) -> float:
        """Return the score change from the first recorded run to the last.

        Returns:
            ``last_score - first_score``; ``0.0`` when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        return self._run_history[-1].score.overall - self._run_history[0].score.overall

    def rolling_average(self, window: int = 5) -> list:
        """Return a list of rolling-window averages of overall scores.

        Each element is the mean of up to *window* consecutive run scores,
        starting from the first run.

        Args:
            window: Number of runs to average (default 5).

        Returns:
            List of float averages, same length as ``_run_history``.
            Empty when no runs recorded.
        """
        if not self._run_history:
            return []
        scores = [r.score.overall for r in self._run_history]
        result = []
        for i in range(len(scores)):
            start = max(0, i - window + 1)
            chunk = scores[start : i + 1]
            result.append(sum(chunk) / len(chunk))
        return result

    def score_at_run(self, index: int) -> float:
        """Return the overall score of the run at *index*.

        Args:
            index: Zero-based run index. Negative indices are supported.

        Returns:
            ``overall`` score of the indexed run.

        Raises:
            IndexError: When *index* is out of range.
        """
        return self._run_history[index].score.overall

    def score_percentile(self, value: float) -> float:
        """Return the percentile rank of *value* among recorded run scores.

        Args:
            value: Score to rank.

        Returns:
            Float in [0.0, 100.0]; ``0.0`` when no runs recorded.
        """
        if not self._run_history:
            return 0.0
        scores = sorted(r.score.overall for r in self._run_history)
        below = sum(1 for s in scores if s < value)
        return 100.0 * below / len(scores)

    def is_plateau(self, window: int = 5, tolerance: float = 0.01) -> bool:
        """Return ``True`` when recent score movement is within *tolerance*.

        A plateau is detected when the absolute difference between the max and
        min score in the last *window* runs is <= *tolerance*.

        Args:
            window: Number of recent runs to inspect (default 5).
            tolerance: Maximum score change to still count as a plateau.

        Returns:
            ``True`` when plateaued; ``False`` when fewer than 2 runs or high
            variability.
        """
        recent = self._run_history[-window:]
        if len(recent) < 2:
            return False
        scores = [r.score.overall for r in recent]
        return (max(scores) - min(scores)) <= tolerance

    def peak_run_index(self) -> int:
        """Return the zero-based index of the run with the highest overall score.

        Returns:
            Index of peak run; ``-1`` when no runs recorded.
        """
        if not self._run_history:
            return -1
        return max(range(len(self._run_history)),
                   key=lambda i: self._run_history[i].score.overall)

    def score_ewma(self, alpha: float = 0.3) -> list:
        """Return a list of exponentially weighted moving averages of run scores.

        Args:
            alpha: Smoothing factor in (0, 1].  Higher values weight recent
                observations more heavily.

        Returns:
            List of float EWMA values, same length as ``_run_history``.
            Empty when no runs recorded.
        """
        if not self._run_history:
            return []
        scores = [r.score.overall for r in self._run_history]
        ewma = [scores[0]]
        for s in scores[1:]:
            ewma.append(alpha * s + (1 - alpha) * ewma[-1])
        return ewma

    def trend_slope(self) -> float:
        """Return the linear regression slope of overall scores over run indices.

        A positive value indicates an improving trend; negative means declining.

        Returns:
            Slope as float; ``0.0`` when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        n = len(scores)
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(scores) / n
        num = sum((xs[i] - x_mean) * (scores[i] - y_mean) for i in range(n))
        den = sum((xs[i] - x_mean) ** 2 for i in range(n))
        if den == 0:
            return 0.0
        return num / den

    def pipeline_score_range(self) -> float:
        """Return the range (max - min) of overall scores in run history.

        Returns:
            Float range; ``0.0`` when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        return max(scores) - min(scores)

    def score_at_percentile(self, p: float) -> float:
        """Return the *p*-th percentile of overall scores in run history.

        Args:
            p: Percentile in [0, 100].

        Returns:
            Float score at the requested percentile; ``0.0`` when no runs.

        Raises:
            ValueError: If *p* is outside [0, 100].
        """
        if not (0 <= p <= 100):
            raise ValueError(f"Percentile must be in [0, 100], got {p}")
        if not self._run_history:
            return 0.0
        scores = sorted(r.score.overall for r in self._run_history)
        idx = (p / 100.0) * (len(scores) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(scores) - 1)
        return scores[lo] + (idx - lo) * (scores[hi] - scores[lo])

    def best_run_index(self) -> int:
        """Return the index of the run with the highest overall score.

        Returns:
            Integer index into ``_run_history``; ``-1`` when no runs.
        """
        if not self._run_history:
            return -1
        return max(range(len(self._run_history)),
                   key=lambda i: self._run_history[i].score.overall)

    def score_improvement_rate(self) -> float:
        """Return the mean per-step improvement in overall scores.

        Computed as ``(last_score - first_score) / (n - 1)``.

        Returns:
            Float; ``0.0`` when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        first = self._run_history[0].score.overall
        last = self._run_history[-1].score.overall
        return (last - first) / (len(self._run_history) - 1)

    def scores_above_mean(self) -> list:
        """Return run records whose overall score exceeds the mean overall score.

        Returns:
            List of run records with ``score.overall > mean``.  Empty when
            no runs exist.
        """
        if not self._run_history:
            return []
        scores = [r.score.overall for r in self._run_history]
        mean = sum(scores) / len(scores)
        return [r for r in self._run_history if r.score.overall > mean]

    def last_n_scores(self, n: int) -> list:
        """Return the overall scores from the last *n* runs.

        Args:
            n: Number of most recent runs to include.

        Returns:
            List of float overall scores, oldest first.  Fewer than *n*
            values are returned when history has fewer than *n* runs.
        """
        recent = self._run_history[-n:]
        return [r.score.overall for r in recent]

    def all_runs_above(self, threshold: float = 0.5) -> bool:
        """Return True if every run score exceeds *threshold*.

        Args:
            threshold: Minimum value (exclusive). Defaults to ``0.5``.

        Returns:
            ``True`` when all run overall scores are strictly greater than
            *threshold*; ``False`` when history is empty or any score fails.
        """
        if not self._run_history:
            return False
        return all(r.score.overall > threshold for r in self._run_history)

    def run_score_at(self, idx: int) -> float:
        """Return the overall score of the run at *idx* in run history.

        Args:
            idx: Integer index into ``_run_history`` (supports negatives).

        Returns:
            Float overall score at the given index.

        Raises:
            IndexError: When *idx* is out of range.
        """
        return self._run_history[idx].score.overall

    def run_score_deltas(self) -> list:
        """Return list of consecutive score differences (score[i+1] - score[i]).

        Returns:
            List of floats; empty list when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return []
        scores = [r.score.overall for r in self._run_history]
        return [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]

    def run_score_variance(self) -> float:
        """Return the population variance of all run overall scores.

        Returns:
            Float variance; ``0.0`` when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        mean = sum(scores) / len(scores)
        return sum((s - mean) ** 2 for s in scores) / len(scores)

    def run_trend(self, n: int = 5) -> str:
        """Return the overall trend direction of the last *n* run scores.

        Args:
            n: Number of recent runs to consider. Defaults to ``5``.

        Returns:
            ``"up"`` if the linear trend is positive, ``"down"`` if negative,
            ``"flat"`` if fewer than 2 runs or slope is zero.
        """
        recent = self._run_history[-n:]
        if len(recent) < 2:
            return "flat"
        scores = [r.score.overall for r in recent]
        n_pts = len(scores)
        x_mean = (n_pts - 1) / 2.0
        y_mean = sum(scores) / n_pts
        numerator = sum((i - x_mean) * (scores[i] - y_mean) for i in range(n_pts))
        denominator = sum((i - x_mean) ** 2 for i in range(n_pts))
        if denominator == 0 or numerator == 0:
            return "flat"
        return "up" if numerator > 0 else "down"

    def best_k_scores(self, k: int = 3) -> list:
        """Return the top-k overall scores across all runs, descending.

        Args:
            k: Number of scores to return. Defaults to 3.

        Returns:
            List of float scores, highest first. Fewer than k if fewer runs.
        """
        scores = sorted(
            (r.score.overall for r in self._run_history), reverse=True
        )
        return scores[:k]

    def worst_k_scores(self, k: int = 3) -> list:
        """Return the bottom-k overall scores across all runs, ascending.

        Args:
            k: Number of scores to return. Defaults to 3.

        Returns:
            List of float scores, lowest first. Fewer than k if fewer runs.
        """
        scores = sorted(r.score.overall for r in self._run_history)
        return scores[:k]

    def run_moving_average(self, n: int = 3) -> list:
        """Return a list of moving averages of run scores with window size n.

        Args:
            n: Window size. Defaults to 3.

        Returns:
            List of float averages, length = max(0, len(runs) - n + 1).
        """
        scores = [r.score.overall for r in self._run_history]
        if len(scores) < n:
            return []
        return [
            sum(scores[i:i + n]) / n
            for i in range(len(scores) - n + 1)
        ]

    def convergence_round(self, variance_threshold: float = 0.01) -> int:
        """Return the first run index where variance of last 3 scores drops below threshold.

        Args:
            variance_threshold: Maximum variance to be considered converged.

        Returns:
            Integer run index (0-based); -1 if convergence is never achieved.
        """
        scores = [r.score.overall for r in self._run_history]
        for i in range(2, len(scores)):
            window = scores[i - 2:i + 1]
            mean = sum(window) / 3
            var = sum((s - mean) ** 2 for s in window) / 3
            if var < variance_threshold:
                return i
        return -1

    def score_histogram(self, bins: int = 5) -> dict:
        """Return a histogram of run overall scores.

        The score range [0, 1] is divided into *bins* equal-width buckets.
        Keys are formatted as "lo-hi" strings.

        Args:
            bins: Number of equal-width buckets. Defaults to 5.

        Returns:
            Dict mapping "lo-hi" string → integer count. Empty dict when no runs.
        """
        if not self._run_history:
            return {}
        width = 1.0 / bins
        result = {}
        for i in range(bins):
            lo = i * width
            hi = lo + width
            key = f"{lo:.2f}-{hi:.2f}"
            result[key] = 0
        for run in self._run_history:
            s = run.score.overall
            bucket = min(int(s / width), bins - 1)
            key = f"{bucket * width:.2f}-{(bucket + 1) * width:.2f}"
            if key in result:
                result[key] += 1
            else:
                result[key] = 1
        return result

    def score_std(self) -> float:
        """Return the population std-dev of all run overall scores.

        Returns:
            Float std-dev; 0.0 when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        return variance ** 0.5

    def improvement_count(self) -> int:
        """Return the number of runs that improved on the immediately preceding run.

        Returns:
            Integer count of consecutive-improving transitions; 0 when fewer
            than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0
        scores = [r.score.overall for r in self._run_history]
        return sum(1 for i in range(1, len(scores)) if scores[i] > scores[i - 1])

    def first_score(self) -> float:
        """Return the overall score from the first pipeline run.

        Returns:
            Float score; 0.0 when no runs have been recorded.
        """
        if not self._run_history:
            return 0.0
        return self._run_history[0].score.overall

    def score_below_mean_count(self) -> int:
        """Return the number of runs whose score is strictly below the mean.

        Returns:
            Integer count; 0 when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0
        scores = [r.score.overall for r in self._run_history]
        mean = sum(scores) / len(scores)
        return sum(1 for s in scores if s < mean)

    def run_score_ewma(self, alpha: float = 0.3) -> list:
        """Return the exponential weighted moving average of run overall scores.

        Processes ``_run_history`` in chronological order.

        Args:
            alpha: Smoothing factor (0 < alpha <= 1).

        Returns:
            List of floats with same length as ``_run_history``; empty when no
            runs have been recorded.
        """
        if not self._run_history:
            return []
        scores = [r.score.overall for r in self._run_history]
        result = [scores[0]]
        for s in scores[1:]:
            result.append(alpha * s + (1.0 - alpha) * result[-1])
        return result

    def run_score_percentile(self, p: float = 50.0) -> float:
        """Return the *p*-th percentile of run overall scores.

        Uses linear interpolation.

        Args:
            p: Percentile in [0, 100].

        Returns:
            Float percentile; 0.0 when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        scores = sorted(r.score.overall for r in self._run_history)
        n = len(scores)
        idx = (p / 100.0) * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return scores[lo] + (scores[hi] - scores[lo]) * (idx - lo)

    def run_score_median(self) -> float:
        """Return the median of all run overall scores.

        Returns:
            Float median; 0.0 when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        scores = sorted(r.score.overall for r in self._run_history)
        n = len(scores)
        if n % 2 == 1:
            return scores[n // 2]
        return (scores[n // 2 - 1] + scores[n // 2]) / 2.0

    def run_count_above(self, threshold: float = 0.7) -> int:
        """Return the count of runs whose overall score exceeds *threshold*.

        Args:
            threshold: Score threshold (exclusive).

        Returns:
            Integer count; 0 when no runs recorded.
        """
        return sum(1 for r in self._run_history if r.score.overall > threshold)

    def consecutive_improvements(self) -> int:
        """Return the length of the current (ending) improving streak.

        Counts how many consecutive final runs each improved on the one before.

        Returns:
            Integer; 0 when fewer than 2 runs or latest run did not improve.
        """
        if len(self._run_history) < 2:
            return 0
        scores = [r.score.overall for r in self._run_history]
        count = 0
        for i in range(len(scores) - 1, 0, -1):
            if scores[i] > scores[i - 1]:
                count += 1
            else:
                break
        return count

    def run_score_iqr(self) -> float:
        """Return the interquartile range (Q3 - Q1) of run overall scores.

        Returns:
            Float IQR; 0.0 when fewer than 4 runs.
        """
        if len(self._run_history) < 4:
            return 0.0
        scores = sorted(r.score.overall for r in self._run_history)
        n = len(scores)

        def _percentile(p: float) -> float:
            idx = (p / 100.0) * (n - 1)
            lo, hi = int(idx), min(int(idx) + 1, n - 1)
            return scores[lo] + (scores[hi] - scores[lo]) * (idx - lo)

        return _percentile(75.0) - _percentile(25.0)

    def score_variance_trend(self) -> float:
        """Return variance(second_half) - variance(first_half) of run scores.

        Positive means variance is growing; negative means it is shrinking.

        Returns:
            Float; 0.0 when fewer than 4 runs.
        """
        n = len(self._run_history)
        if n < 4:
            return 0.0
        scores = [r.score.overall for r in self._run_history]

        def _var(vals: list) -> float:
            if len(vals) < 2:
                return 0.0
            mean = sum(vals) / len(vals)
            return sum((v - mean) ** 2 for v in vals) / len(vals)

        mid = n // 2
        return _var(scores[mid:]) - _var(scores[:mid])

    def run_score_coefficient_of_variation(self) -> float:
        """Return std / mean of run overall scores (coefficient of variation).

        Returns:
            Float; 0.0 when fewer than 2 runs or mean is 0.
        """
        n = len(self._run_history)
        if n < 2:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        mean = sum(scores) / n
        if mean == 0.0:
            return 0.0
        variance = sum((v - mean) ** 2 for v in scores) / n
        return (variance ** 0.5) / mean

    def run_score_range(self) -> tuple:
        """Return (min, max) tuple of run overall scores.

        Returns:
            Tuple ``(lo, hi)``; ``(0.0, 0.0)`` when no runs.
        """
        if not self._run_history:
            return (0.0, 0.0)
        scores = [r.score.overall for r in self._run_history]
        return (min(scores), max(scores))

    def run_score_above_mean_fraction(self) -> float:
        """Return fraction of runs whose score is above the mean.

        Returns:
            Float in [0, 1]; 0.0 when no runs.
        """
        if not self._run_history:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        mean = sum(scores) / len(scores)
        return sum(1 for s in scores if s > mean) / len(scores)

    def run_score_kurtosis(self) -> float:
        """Return the excess kurtosis of run overall scores.

        Returns:
            Float; 0.0 when fewer than 4 runs.
        """
        n = len(self._run_history)
        if n < 4:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        mean = sum(scores) / n
        m2 = sum((s - mean) ** 2 for s in scores) / n
        if m2 == 0.0:
            return 0.0
        m4 = sum((s - mean) ** 4 for s in scores) / n
        return m4 / (m2 ** 2) - 3.0

    def run_score_sum(self) -> float:
        """Return the sum of all run overall scores.

        Returns:
            Float; 0.0 when no runs.
        """
        return sum(r.score.overall for r in self._run_history)

    def run_score_geometric_mean(self) -> float:
        """Return the geometric mean of run overall scores.

        Scores of 0 are replaced by a small epsilon.

        Returns:
            Float; 0.0 when no runs.
        """
        if not self._run_history:
            return 0.0
        epsilon = 1e-9
        scores = [max(r.score.overall, epsilon) for r in self._run_history]
        product = 1.0
        for s in scores:
            product *= s
        return product ** (1.0 / len(scores))

    def best_run_index(self) -> int:
        """Return the index of the run with the highest overall score.

        Returns:
            Integer index; -1 when no runs.
        """
        if not self._run_history:
            return -1
        return max(range(len(self._run_history)), key=lambda i: self._run_history[i].score.overall)

    def run_score_harmonic_mean(self) -> float:
        """Return the harmonic mean of run overall scores.

        Scores of 0 are replaced by a small epsilon.

        Returns:
            Float; 0.0 when no runs.
        """
        if not self._run_history:
            return 0.0
        epsilon = 1e-9
        scores = [max(r.score.overall, epsilon) for r in self._run_history]
        n = len(scores)
        return n / sum(1.0 / s for s in scores)

    def worst_run_index(self) -> int:
        """Return the index of the run with the lowest overall score.

        Returns:
            Integer index; -1 when no runs.
        """
        if not self._run_history:
            return -1
        return min(range(len(self._run_history)), key=lambda i: self._run_history[i].score.overall)

    def run_score_delta_sum(self) -> float:
        """Return the sum of consecutive run-score deltas (last - first overall).

        Returns:
            Float; 0.0 when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        return scores[-1] - scores[0]

    def run_score_improving_fraction(self) -> float:
        """Return the fraction of consecutive pairs where score improved.

        Returns:
            Float in [0, 1]; 0.0 when fewer than 2 runs.
        """
        n = len(self._run_history)
        if n < 2:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        improving = sum(1 for i in range(1, n) if scores[i] > scores[i - 1])
        return improving / (n - 1)

    def run_score_acceleration(self) -> float:
        """Return mean second derivative of run overall scores.

        Positive means rate of improvement is increasing; negative means slowing.

        Returns:
            Float; 0.0 when fewer than 3 runs.
        """
        n = len(self._run_history)
        if n < 3:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        fd = [scores[i + 1] - scores[i] for i in range(n - 1)]
        sd = [fd[i + 1] - fd[i] for i in range(len(fd) - 1)]
        return sum(sd) / len(sd)

    def run_score_peak_count(self) -> int:
        """Return the number of local maxima in run overall scores.

        Returns:
            Integer count; 0 when fewer than 3 runs.
        """
        n = len(self._run_history)
        if n < 3:
            return 0
        scores = [r.score.overall for r in self._run_history]
        return sum(1 for i in range(1, n - 1) if scores[i] > scores[i - 1] and scores[i] > scores[i + 1])

    def run_score_trend_direction(self) -> str:
        """Return "improving", "declining", or "stable" based on recent runs.

        Uses the last 5 run scores (or all if fewer) and checks if the
        linear trend slope is positive, negative, or near zero.

        Returns:
            String label.
        """
        n = len(self._run_history)
        if n < 2:
            return "stable"
        recent = self._run_history[-5:]
        scores = [r.score.overall for r in recent]
        m = len(scores)
        indices = list(range(m))
        mx = sum(indices) / m
        my = sum(scores) / m
        num = sum((i - mx) * (s - my) for i, s in zip(indices, scores))
        di = sum((i - mx) ** 2 for i in indices)
        if di == 0.0:
            return "stable"
        slope = num / di
        if slope > 0.005:
            return "improving"
        if slope < -0.005:
            return "declining"
        return "stable"

    def run_score_first(self) -> float:
        """Return the score from the very first run in history.

        Returns:
            Float score of the first run; 0.0 when no runs recorded.
        """
        if not self._run_history:
            return 0.0
        return self._run_history[0].score.overall

    def run_score_last(self) -> float:
        """Return the score from the most recent run in history.

        Returns:
            Float score of the last run; 0.0 when no runs recorded.
        """
        if not self._run_history:
            return 0.0
        return self._run_history[-1].score.overall

    def run_score_delta(self) -> float:
        """Return the difference between the last and first run scores.

        Returns:
            Float delta (last - first); 0.0 when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        return self._run_history[-1].score.overall - self._run_history[0].score.overall

    def run_improvement_rate(self) -> float:
        """Return the fraction of consecutive run pairs where score improved.

        Returns:
            Float in [0, 1]; 0.0 when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        improvements = sum(
            1 for i in range(len(self._run_history) - 1)
            if self._run_history[i + 1].score.overall > self._run_history[i].score.overall
        )
        return improvements / (len(self._run_history) - 1)

    def run_score_mean(self) -> float:
        """Return the arithmetic mean of all run scores.

        Returns:
            Float mean; 0.0 when no runs.
        """
        if not self._run_history:
            return 0.0
        return sum(r.score.overall for r in self._run_history) / len(self._run_history)

    def run_score_std(self) -> float:
        """Return the standard deviation of all run scores.

        Returns:
            Float std dev; 0.0 when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        return variance ** 0.5

    def run_score_min(self) -> float:
        """Return the minimum score across all run history.

        Returns:
            Float minimum; 0.0 when no runs.
        """
        if not self._run_history:
            return 0.0
        return min(r.score.overall for r in self._run_history)

    def run_score_max(self) -> float:
        """Return the maximum score across all run history.

        Returns:
            Float maximum; 0.0 when no runs.
        """
        if not self._run_history:
            return 0.0
        return max(r.score.overall for r in self._run_history)

    def run_score_count_above_mean(self) -> int:
        """Return the count of run scores above the mean score.

        Returns:
            Integer count; 0 when no runs.
        """
        if not self._run_history:
            return 0
        scores = [r.score.overall for r in self._run_history]
        mean = sum(scores) / len(scores)
        return sum(1 for s in scores if s > mean)

    def run_score_geometric_mean(self) -> float:
        """Return the geometric mean of all run scores.

        Returns:
            Float geometric mean; 0.0 when no runs or any score <= 0.
        """
        if not self._run_history:
            return 0.0
        import math
        scores = [r.score.overall for r in self._run_history]
        if any(s <= 0 for s in scores):
            return 0.0
        log_sum = sum(math.log(s) for s in scores)
        return math.exp(log_sum / len(scores))

    def run_score_harmonic_mean(self) -> float:
        """Return the harmonic mean of all run scores.

        Returns:
            Float harmonic mean; 0.0 when no runs or any score == 0.
        """
        if not self._run_history:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        if any(s == 0 for s in scores):
            return 0.0
        n = len(scores)
        return n / sum(1.0 / s for s in scores)

    def run_score_above_first(self) -> int:
        """Return the count of run scores that are strictly above the first run score.

        Returns:
            Integer count; 0 when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0
        first = self._run_history[0].score.overall
        return sum(1 for r in self._run_history[1:] if r.score.overall > first)

    def run_score_below_last(self) -> int:
        """Return the count of run scores strictly below the last run score.

        Returns:
            Integer count; 0 when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0
        last = self._run_history[-1].score.overall
        return sum(1 for r in self._run_history[:-1] if r.score.overall < last)

    def run_score_trend_slope(self) -> float:
        """Return the linear trend slope of run scores over time.

        Uses ordinary least squares to compute slope = cov(t, s) / var(t).

        Returns:
            Float slope; 0.0 when fewer than 2 runs.
        """
        if len(self._run_history) < 2:
            return 0.0
        scores = [r.score.overall for r in self._run_history]
        n = len(scores)
        t_vals = list(range(n))
        t_mean = (n - 1) / 2.0
        s_mean = sum(scores) / n
        cov = sum((t - t_mean) * (s - s_mean) for t, s in zip(t_vals, scores))
        var_t = sum((t - t_mean) ** 2 for t in t_vals)
        return cov / var_t if var_t != 0 else 0.0

    def run_score_rolling_std(self, window: int = 3) -> float:
        """Return the standard deviation of the last *window* run scores.

        Args:
            window: Rolling window size. Defaults to 3.

        Returns:
            Float std; 0.0 when fewer than 2 runs in window.
        """
        if len(self._run_history) < 2:
            return 0.0
        tail = [r.score.overall for r in self._run_history[-window:]]
        if len(tail) < 2:
            return 0.0
        mean = sum(tail) / len(tail)
        var = sum((s - mean) ** 2 for s in tail) / len(tail)
        return var ** 0.5
