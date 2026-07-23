"""Regression coverage for legacy compiler-guidance distillation artifacts."""

from __future__ import annotations

import json

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_guidance_replay import (
    GuidanceReplayPolicy,
    GuidanceReplayRejection,
    LegalIRGuidanceReplay,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    compiler_guidance_distillation_candidates,
)


def _policy() -> GuidanceReplayPolicy:
    return GuidanceReplayPolicy(
        compiler_commit="compiler-current",
        compiler_schema_version="compiler-schema-current",
        canonicalization_version="canonical-current",
        fixed_holdout_id="fixed-holdout-current",
        fixed_holdout_digest="sha256:" + "a" * 64,
        proof_policy_version="proof-current",
        provenance_policy_version="provenance-current",
        source_copy_policy_version="anti-copy-current",
        lineage_id="accepted-state-v2",
        base_state_digest="sha256:" + "b" * 64,
        expected_report_count=1,
        expected_candidate_count=1,
        evaluation_time="2026-07-23T12:00:00+00:00",
    )


def test_legacy_distillation_promotion_is_replay_eligibility_not_authority(
    tmp_path,
) -> None:
    artifact = compiler_guidance_distillation_candidates(
        {
            "compiler_guidance_feature_groups": {"logic_view_contract": 3},
            "compiler_guidance_todo_routes": {
                "repair_deontic_bridge_quality_gate": 3
            },
        },
        {"applied_count": 3, "quality_gate": "pass"},
    )
    path = tmp_path / "old.compiler-guidance-distillation.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    report = LegalIRGuidanceReplay(policy=_policy()).run([path])

    assert artifact["promotion_allowed"] is True
    assert report.replay_candidate_count == 1
    assert report.accepted_count == 0
    assert GuidanceReplayRejection.UNSIGNED.value in (
        report.outcomes[0].rejection_reasons
    )
    assert GuidanceReplayRejection.SCHEMA_MISMATCH.value in (
        report.outcomes[0].rejection_reasons
    )
    assert GuidanceReplayRejection.NONRECONSTRUCTIBLE.value in (
        report.outcomes[0].rejection_reasons
    )


def test_source_bearing_distillation_examples_are_never_replayed(tmp_path) -> None:
    raw_text = "The private source paragraph shall not enter replay state."
    artifact = compiler_guidance_distillation_candidates(
        {
            "compiler_guidance_todo_routes": {
                "refine_semantic_decompiler_reconstruction": 2
            },
            "compiler_guidance_todo_route_examples": {
                "refine_semantic_decompiler_reconstruction": [
                    {"sample_id": "private-sample", "text_preview": raw_text}
                ]
            },
        },
        {"applied_count": 2, "quality_gate": "pass"},
    )
    path = tmp_path / "source.compiler-guidance-distillation.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    replay = LegalIRGuidanceReplay(policy=_policy()).run([path])
    serialized = json.dumps(replay.to_dict(), sort_keys=True)

    assert GuidanceReplayRejection.SOURCE_BEARING.value in (
        replay.outcomes[0].rejection_reasons
    )
    assert raw_text not in serialized
    assert "private-sample" not in serialized
