"""Regression coverage for mandatory LegalIR guidance promotion evidence."""

from __future__ import annotations

import json

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_guidance_replay import (
    LEGAL_IR_GUIDANCE_CANDIDATE_SCHEMA_VERSION,
    GuidanceReplayPolicy,
    GuidanceReplayRejection,
    LegalIRGuidanceReplay,
    sign_guidance_replay_payload,
)


SECRET = "promotion-evidence-test-secret"


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
        trusted_signers={"promotion-signer": SECRET},
        expected_report_count=1,
        expected_candidate_count=1,
        evaluation_time="2026-07-23T12:00:00+00:00",
    )


def _signed_candidate(policy: GuidanceReplayPolicy) -> dict:
    payload = {
        "schema_version": LEGAL_IR_GUIDANCE_CANDIDATE_SCHEMA_VERSION,
        "created_at": "2026-07-23T11:00:00+00:00",
        "compiler_commit": policy.compiler_commit,
        "compiler_schema_version": policy.compiler_schema_version,
        "canonicalization_version": policy.canonicalization_version,
        "fixed_holdout_id": policy.fixed_holdout_id,
        "fixed_holdout_digest": policy.fixed_holdout_digest,
        "lineage_id": policy.lineage_id,
        "has_candidates": True,
        "promotion_allowed": True,
        "promotion_block_reason": "",
        "quality_gate": "pass",
        "recommended_mode": "promote_deterministic_rules",
        "guidance_attribution": {"basis": "source-free"},
        "top_feature_groups": {"logic_view_contract": 2},
    }
    payload["signature"] = sign_guidance_replay_payload(
        payload,
        signer_id="promotion-signer",
        secret=SECRET,
    )
    return payload


def test_signed_candidate_still_requires_fresh_current_evidence(tmp_path) -> None:
    policy = _policy()
    path = tmp_path / "candidate.compiler-guidance-distillation.json"
    path.write_text(json.dumps(_signed_candidate(policy)), encoding="utf-8")

    report = LegalIRGuidanceReplay(policy=policy).run([path])

    assert report.audits[0].rejection_reasons == ()
    assert report.accepted_count == 0
    assert report.outcomes[0].rejection_reasons == (
        GuidanceReplayRejection.REVALIDATION_UNAVAILABLE.value,
        GuidanceReplayRejection.NONRECONSTRUCTIBLE.value,
    )


def test_revalidator_exception_is_classified_without_serializing_message(
    tmp_path,
) -> None:
    policy = _policy()
    path = tmp_path / "candidate.compiler-guidance-distillation.json"
    path.write_text(json.dumps(_signed_candidate(policy)), encoding="utf-8")
    raw_exception_text = "decoded secret source appeared in compiler exception"

    def failed_revalidator(_report, _context):
        raise RuntimeError(raw_exception_text)

    report = LegalIRGuidanceReplay(
        policy=policy,
        revalidator=failed_revalidator,
    ).run([path])
    serialized = json.dumps(report.to_dict(), sort_keys=True)

    assert report.outcomes[0].rejection_reasons == (
        GuidanceReplayRejection.REVALIDATOR_ERROR.value,
        GuidanceReplayRejection.NONRECONSTRUCTIBLE.value,
    )
    assert raw_exception_text not in serialized
