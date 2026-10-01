"""Bound temporary F-logic bookkeeping without altering the historical check."""
from threading import RLock

from ._daemon_snapshot.flogic_optimizer import FLogicSemanticOptimizer


class ObservationScopedFLogicOptimizer(FLogicSemanticOptimizer):
    """Preserve the historical check while discarding its temporary frames.

    The frozen checker reads the supplied triples, adds temporary frames, then
    checks those same triples. It never queries previously accumulated frames.
    Preserve caller-preloaded frames/classes/rules and remove this call's tail
    even when checking raises. The lock serializes observations on this owned
    optimizer; callers must not concurrently mutate its private Ergo ontology.
    Pass the original codec optimizer's config to preserve its exact thresholds
    and ontology name. This grants no proof or semantic qualification authority.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._observation_frame_lock = RLock()

    def _check_flogic_consistency(self, kg_triples):
        with self._observation_frame_lock:
            ergo = self._get_ergo()
            frames = ergo.ontology.frames
            before = len(frames)
            try:
                return super()._check_flogic_consistency(kg_triples)
            finally:
                # ErgoAIWrapper.add_frame only appends to this list; the frozen
                # checker does not replace or edit pre-existing ontology rows.
                del frames[before:]


__all__ = ["ObservationScopedFLogicOptimizer"]
