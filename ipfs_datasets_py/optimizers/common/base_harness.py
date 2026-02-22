"""Base harness for orchestrating the generate → critique → optimize → validate loop.

A harness coordinates a generator, critic, and optimizer through multiple
refinement rounds, using a :class:`~ipfs_datasets_py.optimizers.common.BaseSession`
to track state.

Concrete harness implementations (``OntologyHarness``, ``LogicHarness``, …) should
extend :class:`BaseHarness` and supply their domain-specific generator, critic, and
optimizer.

Example::

    class MyHarness(BaseHarness):
        def _generate(self, data, context):
            return self.generator.extract_entities(data, context)

        def _critique(self, artifact, context):
            return self.critic.evaluate(artifact, context)

        def _optimize(self, artifact, result, context):
            return self.optimizer.refine(artifact, result, context)

    harness = MyHarness(generator=gen, critic=critic, optimizer=opt)
    session = harness.run(data, context)
    print(session.best_score)
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .base_critic import BaseCritic, CriticResult
from .base_session import BaseSession
from .base_optimizer import BaseOptimizer, OptimizationContext, OptimizerConfig

logger = logging.getLogger(__name__)


@dataclass
class HarnessConfig:
    """Configuration for a harness run.

    Attributes:
        max_rounds: Maximum refinement rounds.
        target_score: Score at which the harness stops early.
        convergence_threshold: Minimum per-round improvement to continue.
        verbose: Whether to log per-round details.
    """

    max_rounds: int = 10
    target_score: float = 0.85
    convergence_threshold: float = 0.01
    verbose: bool = False


class BaseHarness(ABC):
    """Abstract orchestrator for the generate → critique → optimize loop.

    Subclasses must implement :meth:`_generate`, :meth:`_critique`, and
    :meth:`_optimize`.  The :meth:`run` method drives the loop and returns
    a populated :class:`~ipfs_datasets_py.optimizers.common.BaseSession`.

    Args:
        config: Harness configuration.
    """

    def __init__(self, config: Optional[HarnessConfig] = None) -> None:
        self.config = config or HarnessConfig()

    # ------------------------------------------------------------------ #
    # Abstract interface                                                   #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def _generate(self, data: Any, context: Any) -> Any:
        """Generate an initial artifact from *data*."""

    @abstractmethod
    def _critique(self, artifact: Any, context: Any) -> CriticResult:
        """Evaluate *artifact* and return a :class:`CriticResult`."""

    @abstractmethod
    def _optimize(self, artifact: Any, critique: CriticResult, context: Any) -> Any:
        """Produce an improved artifact given *critique* feedback."""

    def _validate(self, artifact: Any, context: Any) -> bool:
        """Optional final validation step.  Default: always passes."""
        return True

    # ------------------------------------------------------------------ #
    # Orchestration                                                        #
    # ------------------------------------------------------------------ #

    def run(
        self,
        data: Any,
        context: Any,
        *,
        session_id: Optional[str] = None,
        domain: str = "general",
    ) -> BaseSession:
        """Run the full refinement loop.

        Args:
            data: Input data to generate an artifact from.
            context: Optimization or generation context.
            session_id: Optional session identifier.
            domain: Domain label stored on the session.

        Returns:
            Completed :class:`~ipfs_datasets_py.optimizers.common.BaseSession`.
        """
        import uuid as _uuid

        sid = session_id or f"harness-{_uuid.uuid4().hex[:8]}"
        session = BaseSession(
            session_id=sid,
            domain=domain,
            max_rounds=self.config.max_rounds,
            target_score=self.config.target_score,
            convergence_threshold=self.config.convergence_threshold,
        )

        logger.info(f"[{sid}] Harness starting — max_rounds={self.config.max_rounds}")

        # Generate initial artifact
        session.start_round()
        artifact = self._generate(data, context)
        critique = self._critique(artifact, context)
        session.record_round(
            score=critique.score,
            feedback=critique.feedback,
            metadata={'phase': 'initial'},
        )

        if self.config.verbose:
            logger.info(f"[{sid}] Round 1 (initial) score={critique.score:.4f}")

        # Refinement loop
        for _round in range(1, self.config.max_rounds):
            if session.converged:
                logger.info(f"[{sid}] Converged after {session.current_round} rounds")
                break

            session.start_round()
            artifact = self._optimize(artifact, critique, context)
            critique = self._critique(artifact, context)
            session.record_round(
                score=critique.score,
                feedback=critique.feedback,
                metadata={'phase': 'refinement', 'round': _round + 1},
            )

            if self.config.verbose:
                logger.info(f"[{sid}] Round {_round + 1} score={critique.score:.4f}")

        # Final validation
        valid = self._validate(artifact, context)
        session.metadata['final_valid'] = valid
        session.metadata['final_artifact_type'] = type(artifact).__name__
        session.finish()

        logger.info(
            f"[{sid}] Done — rounds={session.current_round} "
            f"best={session.best_score:.4f} trend={session.trend} valid={valid}"
        )
        return session

    def get_config(self) -> Dict[str, Any]:
        """Return harness configuration as a plain dict."""
        return {
            'max_rounds': self.config.max_rounds,
            'target_score': self.config.target_score,
            'convergence_threshold': self.config.convergence_threshold,
            'verbose': self.config.verbose,
            'harness_class': type(self).__name__,
        }


__all__ = ["BaseHarness", "HarnessConfig"]
