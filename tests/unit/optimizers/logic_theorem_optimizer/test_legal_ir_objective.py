"""Compatibility entrypoint for the LegalIR objective regression suite.

PORTAL-LIR-HAMMER-122's validation packet uses the historical
``test_legal_ir_objective.py`` path.  The objective contracts were later
expanded and renamed to ``test_trainable_legal_ir_objective.py``.  Re-export
that suite here so the lineage-bound validation command continues to execute
the authoritative tests instead of failing during path collection.
"""

from tests.unit.optimizers.logic_theorem_optimizer.test_trainable_legal_ir_objective import (  # noqa: F401
    test_generalizable_projection_trains_legal_ir_view_head_from_cached_targets,
    test_legal_ir_objective_component_tracks_view_family_and_proof_losses,
    test_proof_head_training_reports_finite_nonzero_proof_norms,
    test_projection_update_reports_compiler_semantic_slot_and_decompiler_norms,
    test_training_objective_can_weight_legal_ir_independently,
)
