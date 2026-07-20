"""Tests for hammer-verified guidance ingestion by the modal autoencoder."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
)


def _sample():
    return build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall provide notice unless an exception applies.",
    )


def _hammer_artifact(sample_id: str, *, trusted: bool = True) -> dict:
    return {
        "accepted": trusted,
        "backend_statuses": {"z3": "proved"},
        "drafted_logic_candidates": [
            {
                "candidate": "obligation(agency, provide_notice) unless exception",
                "compiler_surface": "deontic.ir",
                "confidence": 0.9,
                "expected_failure_mode": "hammer_unproved",
                "logic_family": "deontic",
                "premise_hints": ["exception_scope_precedence"],
                "proof_obligation_ids": ["lir-obligation-1"],
                "source_copy_policy": "reject_full_span_copy",
                "source_copy_rejected": False,
                "target_view": "deontic.ir",
            }
        ],
        "failure_reason": "" if trusted else "reconstruction_failed",
        "goal_name": "lir-obligation-1",
        "goal_statement_hash": "abc",
        "guidance_id": "hammer-guidance-1" if trusted else "hammer-guidance-failed",
        "legal_ir_view": "deontic.ir",
        "logic_family": "deontic",
        "obligation_id": "lir-obligation-1",
        "premise_views": ["deontic.ir"],
        "proof_checked": trusted,
        "proof_obligation_ids": ["lir-obligation-1"],
        "proved": trusted,
        "reconstruction_status": "verified" if trusted else "kernel_rejected",
        "rejection_reasons": [] if trusted else ["reconstruction_failed"],
        "schema_version": "legal-ir-hammer-guidance-v1",
        "selected_premises": ["exception_scope_precedence"],
        "source": "hammer_verified_guidance",
        "sample_id": sample_id,
        "target_component": "deontic.ir",
        "target_metrics": ["compiler_ir_cross_entropy_loss"],
        "trusted": trusted,
        "winner_backend": "z3",
    }


def test_autoencoder_applies_trusted_hammer_guidance_to_view_and_feature_logits() -> None:
    sample = _sample()
    autoencoder = AdaptiveModalAutoencoder()
    guidance = _hammer_artifact(sample.sample_id)
    target_distribution = autoencoder._leanstral_guidance_target_distribution(guidance)

    report = autoencoder.apply_leanstral_guidance(
        [guidance],
        samples_by_id={sample.sample_id: sample},
        learning_rate=0.5,
    )

    assert report["status"] == "applied"
    assert report["applied_count"] == 1
    assert report["hammer_guidance_count"] == 1
    assert report["target_view_counts"]["deontic.ir"] > 0.0
    assert target_distribution["deontic.ir"] > target_distribution["TDFOL.prover"]
    assert autoencoder.state.applied_leanstral_guidance_ids == ["hammer-guidance-1"]
    feature_logits = autoencoder.state.feature_legal_ir_view_logits
    assert "hammer:backend-status:z3:proved" in feature_logits
    assert "hammer:reconstruction-status:verified" in feature_logits
    assert "hammer:selected-premise:exception_scope_precedence" in feature_logits
    assert "hammer:obligation:lir_obligation_1" in feature_logits
    assert feature_logits["hammer:backend-status:z3:proved"]["deontic.ir"] > 0.0


def test_autoencoder_flattens_nested_hammer_verification_reports() -> None:
    sample = _sample()
    autoencoder = AdaptiveModalAutoencoder()
    artifact = _hammer_artifact(sample.sample_id)
    nested_report = {
        "candidate_results": [
            {
                "trusted": True,
                "verified_guidance": [artifact],
                "hammer_report": {"artifacts": [artifact]},
            }
        ]
    }

    report = autoencoder.apply_leanstral_guidance(
        nested_report,
        samples_by_id={sample.sample_id: sample},
        learning_rate=0.5,
    )

    assert report["status"] == "applied"
    assert report["applied_count"] == 1
    assert report["guidance_ids"] == ["hammer-guidance-1"]


def test_autoencoder_skips_untrusted_hammer_guidance() -> None:
    sample = _sample()
    autoencoder = AdaptiveModalAutoencoder()
    report = autoencoder.apply_leanstral_guidance(
        [_hammer_artifact(sample.sample_id, trusted=False)],
        samples_by_id={sample.sample_id: sample},
        learning_rate=0.5,
    )

    assert report["status"] == "no_applicable_guidance"
    assert report["skipped_untrusted_count"] == 1
    assert autoencoder.state.applied_leanstral_guidance_ids == []

