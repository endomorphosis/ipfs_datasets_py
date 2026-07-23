"""Tests for fail-closed replay of historical compiler guidance."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_guidance_replay import (
    CANONICAL_HISTORICAL_PROMOTION_CANDIDATE_COUNT,
    CANONICAL_HISTORICAL_REPORT_COUNT,
    LEGAL_IR_GUIDANCE_CANDIDATE_SCHEMA_VERSION,
    LEGAL_IR_GUIDANCE_REVALIDATION_SCHEMA_VERSION,
    CurrentGuidanceRevalidation,
    GuidanceFeatureDelta,
    GuidanceReplayPolicy,
    GuidanceReplayRejection,
    GuidanceRevalidationContext,
    GuidanceRevalidationError,
    LegalIRGuidanceReplay,
    load_historical_compiler_guidance_reports,
    sign_guidance_replay_payload,
)
from scripts.ops.legal_ir.revalidate_compiler_guidance import main as replay_cli_main


SECRET = "unit-test-trust-key"
RAW_PROMPT = "SECRET PROMPT: reproduce the entire private statute"
RAW_DECODED = "The Secretary shall disclose the private source paragraph."
SOURCE_TERM = "private-source-lexeme"
HOLDOUT_DIGEST = "sha256:" + "a" * 64
STATE_DIGEST = "sha256:" + "b" * 64
PROVENANCE_DIGEST = "sha256:" + "c" * 64


def _policy(**overrides) -> GuidanceReplayPolicy:
    values = {
        "compiler_commit": "compiler-current-7",
        "compiler_schema_version": "legal-ir-compiler-schema-v7",
        "canonicalization_version": "legal-ir-canonical-v5",
        "fixed_holdout_id": "fixed-holdout-2026q3",
        "fixed_holdout_digest": HOLDOUT_DIGEST,
        "proof_policy_version": "proof-policy-v4",
        "provenance_policy_version": "provenance-policy-v3",
        "source_copy_policy_version": "source-copy-policy-v6",
        "lineage_id": "accepted-state-v2",
        "base_state_digest": STATE_DIGEST,
        "trusted_signers": {"current-replay-signer": SECRET},
        "expected_report_count": 1,
        "expected_candidate_count": 1,
        "evaluation_time": "2026-07-23T12:00:00+00:00",
        "max_report_age_seconds": 24 * 60 * 60,
        "max_feature_deltas": 8,
    }
    values.update(overrides)
    return GuidanceReplayPolicy(**values)


def _candidate_payload(
    policy: GuidanceReplayPolicy,
    *,
    promotion_allowed: bool = True,
    signed: bool = True,
    **overrides,
) -> dict:
    payload = {
        "schema_version": LEGAL_IR_GUIDANCE_CANDIDATE_SCHEMA_VERSION,
        "created_at": "2026-07-23T11:00:00+00:00",
        "compiler_commit": policy.compiler_commit,
        "compiler_schema_version": policy.compiler_schema_version,
        "canonicalization_version": policy.canonicalization_version,
        "fixed_holdout_id": policy.fixed_holdout_id,
        "fixed_holdout_digest": policy.fixed_holdout_digest,
        "lineage_id": policy.lineage_id,
        "has_candidates": promotion_allowed,
        "promotion_allowed": promotion_allowed,
        "promotion_block_reason": "" if promotion_allowed else "quality_gate_fail",
        "quality_gate": "pass" if promotion_allowed else "fail",
        "recommended_mode": (
            "promote_deterministic_rules" if promotion_allowed else "canary_only"
        ),
        "guidance_attribution": {"basis": "source-free-current-replay"},
        "top_feature_groups": {"logic_view_contract": 4},
        "top_todo_routes": {"repair_deontic_bridge_quality_gate": 4},
    }
    payload.update(overrides)
    if signed:
        payload["signature"] = sign_guidance_replay_payload(
            payload,
            signer_id="current-replay-signer",
            secret=SECRET,
        )
    return payload


def _write_report(path, payload) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _receipt_mapping(report, context, **overrides) -> dict:
    receipt = CurrentGuidanceRevalidation(
        report_digest=report.content_digest,
        policy_fingerprint=context.policy_fingerprint,
        compiler_commit=context.compiler_commit,
        compiler_schema_version=context.compiler_schema_version,
        canonicalization_version=context.canonicalization_version,
        fixed_holdout_id=context.fixed_holdout_id,
        fixed_holdout_digest=context.fixed_holdout_digest,
        proof_policy_version=context.proof_policy_version,
        provenance_policy_version=context.provenance_policy_version,
        source_copy_policy_version=context.source_copy_policy_version,
        lineage_id=context.lineage_id,
        base_state_digest=context.base_state_digest,
        reconstructed=True,
        compiler_valid=True,
        schema_valid=True,
        canonicalization_valid=True,
        holdout_valid=True,
        proof_valid=True,
        provenance_valid=True,
        source_copy_valid=True,
        proof_receipt_ids=("proof-receipt-current-1",),
        provenance_digest=PROVENANCE_DIGEST,
        feature_deltas=(
            GuidanceFeatureDelta(
                feature_id="family:deontic",
                family="deontic",
                weight_delta=0.25,
                support_count=4,
                evidence_digest=report.content_digest,
            ),
            GuidanceFeatureDelta(
                feature_id="repair-lane:deontic-compiler",
                family="deontic",
                weight_delta=0.125,
                support_count=4,
                evidence_digest=report.content_digest,
            ),
        ),
    ).to_dict()
    receipt.update(overrides)
    receipt["signature"] = sign_guidance_replay_payload(
        receipt,
        signer_id="current-replay-signer",
        secret=SECRET,
    )
    return receipt


def _inventory(tmp_path, payload=None):
    path = tmp_path / "one.compiler-guidance-distillation.json"
    policy = _policy()
    _write_report(path, payload or _candidate_payload(policy))
    return policy, load_historical_compiler_guidance_reports([tmp_path])


def test_signed_current_revalidation_emits_content_addressed_bounded_update(
    tmp_path,
) -> None:
    policy, inventory = _inventory(tmp_path)

    def revalidator(report, context):
        return _receipt_mapping(report, context)

    first = LegalIRGuidanceReplay(
        policy=policy, revalidator=revalidator
    ).run(inventory)
    second = LegalIRGuidanceReplay(
        policy=policy, revalidator=revalidator
    ).run(inventory)

    assert first.to_dict() == second.to_dict()
    assert first.audited_report_count == 1
    assert first.replay_candidate_count == 1
    assert first.accepted_count == 1
    assert first.rejected_candidate_count == 0
    assert first.audits[0].rejection_reasons == ()
    update = first.feature_updates[0]
    assert update.update_id.startswith("lir-guidance-update-")
    assert update.base_state_digest == STATE_DIGEST
    assert update.lineage_id == policy.lineage_id
    assert len(update.feature_deltas) == 2
    assert {item.feature_id for item in update.feature_deltas} == {
        "family:deontic",
        "repair-lane:deontic-compiler",
    }
    assert first.to_dict()["report_sha256"].startswith("sha256:")


def test_old_promotion_flag_is_only_candidate_eligibility(tmp_path) -> None:
    policy, inventory = _inventory(
        tmp_path,
        _candidate_payload(_policy(), signed=False),
    )
    calls = 0

    def revalidator(report, context):
        nonlocal calls
        calls += 1
        return _receipt_mapping(report, context)

    result = LegalIRGuidanceReplay(
        policy=policy, revalidator=revalidator
    ).run(inventory)

    assert calls == 1  # reconstruction was attempted, but cannot grant trust
    assert result.replay_candidate_count == 1
    assert result.accepted_count == 0
    assert GuidanceReplayRejection.UNSIGNED.value in (
        result.outcomes[0].rejection_reasons
    )
    assert result.feature_updates == ()


def test_audits_exact_historical_142_and_replays_only_17(tmp_path) -> None:
    policy = _policy(
        expected_report_count=CANONICAL_HISTORICAL_REPORT_COUNT,
        expected_candidate_count=CANONICAL_HISTORICAL_PROMOTION_CANDIDATE_COUNT,
    )
    for index in range(CANONICAL_HISTORICAL_REPORT_COUNT):
        candidate = index < CANONICAL_HISTORICAL_PROMOTION_CANDIDATE_COUNT
        # Model the actual legacy shape: old flag, no schema/signature/bindings.
        payload = {
            "has_candidates": True,
            "promotion_allowed": candidate,
            "promotion_block_reason": "" if candidate else "quality_gate_warn",
            "quality_gate": "pass" if candidate else "warn",
            "recommended_mode": (
                "promote_deterministic_rules" if candidate else "canary_only"
            ),
            "top_todo_routes": {"repair_deontic_bridge_quality_gate": index + 1},
        }
        _write_report(
            tmp_path
            / f"historical-{index:03d}.compiler-guidance-distillation.json",
            payload,
        )

    result = LegalIRGuidanceReplay(policy=policy).run([tmp_path])
    serialized = json.dumps(result.to_dict(), sort_keys=True)

    assert result.audited_report_count == 142
    assert len(result.audits) == 142
    assert result.replay_candidate_count == 17
    assert len(result.outcomes) == 17
    assert result.accepted_count == 0
    assert result.inventory_errors == ()
    assert all(
        GuidanceReplayRejection.UNSIGNED.value in item.rejection_reasons
        and GuidanceReplayRejection.STALE.value in item.rejection_reasons
        and GuidanceReplayRejection.NONRECONSTRUCTIBLE.value
        in item.rejection_reasons
        for item in result.outcomes
    )
    assert "top_todo_routes" not in serialized
    assert "repair_deontic_bridge_quality_gate" not in serialized


def test_every_source_field_is_reported_by_path_but_never_copied(tmp_path) -> None:
    policy = _policy()
    payload = _candidate_payload(
        policy,
        signed=False,
        prompt=RAW_PROMPT,
        decoded_text=RAW_DECODED,
        top_semantic_overlay_terms={SOURCE_TERM: 8},
        top_todo_route_examples={
            "repair_deontic_bridge_quality_gate": [
                {"sample_id": "private-sample", "text_preview": RAW_DECODED}
            ]
        },
    )
    # Sign after all source-bearing fields are present, so signature validity
    # cannot mask the source-copy rejection.
    payload["signature"] = sign_guidance_replay_payload(
        payload,
        signer_id="current-replay-signer",
        secret=SECRET,
    )
    _, inventory = _inventory(tmp_path, payload)

    result = LegalIRGuidanceReplay(policy=policy).run(inventory)
    serialized = json.dumps(result.to_dict(), sort_keys=True)

    assert GuidanceReplayRejection.SOURCE_BEARING.value in (
        result.outcomes[0].rejection_reasons
    )
    paths = result.audits[0].source_bearing_field_paths
    assert "$.prompt" in paths
    assert "$.decoded_text" in paths
    assert "$.top_semantic_overlay_terms" in paths
    assert any(path.endswith(".text_preview") for path in paths)
    for secret in (RAW_PROMPT, RAW_DECODED, SOURCE_TERM, "private-sample"):
        assert secret not in serialized


def test_stale_contradictory_and_lineage_mismatched_report_collects_all_reasons(
    tmp_path,
) -> None:
    policy = _policy()
    payload = _candidate_payload(
        policy,
        signed=False,
        created_at="2025-01-01T00:00:00+00:00",
        compiler_commit="compiler-obsolete",
        lineage_id="other-lineage",
        promotion_block_reason="should-not-be-set",
        guidance_attribution={
            "todo_routes": {
                "repair_deontic": {"quality_gate": "fail", "count": 3}
            }
        },
    )
    payload["signature"] = sign_guidance_replay_payload(
        payload,
        signer_id="current-replay-signer",
        secret=SECRET,
    )
    _, inventory = _inventory(tmp_path, payload)

    result = LegalIRGuidanceReplay(policy=policy).run(inventory)
    reasons = set(result.outcomes[0].rejection_reasons)

    assert GuidanceReplayRejection.STALE.value in reasons
    assert GuidanceReplayRejection.CONTRADICTORY.value in reasons
    assert GuidanceReplayRejection.LINEAGE_MISMATCH.value in reasons
    assert GuidanceReplayRejection.NONRECONSTRUCTIBLE.value in reasons


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"reconstructed": False}, GuidanceReplayRejection.NONRECONSTRUCTIBLE),
        ({"compiler_valid": False}, GuidanceReplayRejection.COMPILER_REJECTED),
        ({"schema_valid": False}, GuidanceReplayRejection.COMPILER_REJECTED),
        (
            {"canonicalization_valid": False},
            GuidanceReplayRejection.CANONICALIZATION_REJECTED,
        ),
        (
            {"canonicalization_version": "canonical-other"},
            GuidanceReplayRejection.CANONICALIZATION_REJECTED,
        ),
        ({"holdout_valid": False}, GuidanceReplayRejection.FIXED_HOLDOUT_REJECTED),
        (
            {"fixed_holdout_digest": "sha256:" + "d" * 64},
            GuidanceReplayRejection.FIXED_HOLDOUT_REJECTED,
        ),
        ({"proof_valid": False}, GuidanceReplayRejection.PROOF_REJECTED),
        ({"proof_receipt_ids": []}, GuidanceReplayRejection.PROOF_REJECTED),
        (
            {"provenance_valid": False},
            GuidanceReplayRejection.PROVENANCE_REJECTED,
        ),
        (
            {"provenance_digest": ""},
            GuidanceReplayRejection.PROVENANCE_REJECTED,
        ),
        (
            {"source_copy_valid": False},
            GuidanceReplayRejection.SOURCE_COPY_REJECTED,
        ),
        (
            {"contains_source_material": True},
            GuidanceReplayRejection.SOURCE_COPY_REJECTED,
        ),
        ({"contradictory": True}, GuidanceReplayRejection.CONTRADICTORY),
        ({"lineage_id": "other-lineage"}, GuidanceReplayRejection.LINEAGE_MISMATCH),
        (
            {"report_digest": "sha256:" + "e" * 64},
            GuidanceReplayRejection.RECEIPT_MISMATCH,
        ),
        ({"feature_deltas": []}, GuidanceReplayRejection.FEATURE_UPDATE_INVALID),
    ],
)
def test_current_gate_failures_never_emit_update(tmp_path, overrides, expected) -> None:
    policy, inventory = _inventory(tmp_path)

    def revalidator(report, context):
        return _receipt_mapping(report, context, **overrides)

    result = LegalIRGuidanceReplay(
        policy=policy, revalidator=revalidator
    ).run(inventory)

    assert expected.value in result.outcomes[0].rejection_reasons
    assert result.outcomes[0].accepted is False
    assert result.outcomes[0].feature_update is None


def test_tampered_receipt_signature_fails_closed(tmp_path) -> None:
    policy, inventory = _inventory(tmp_path)

    def revalidator(report, context):
        receipt = _receipt_mapping(report, context)
        receipt["compiler_valid"] = False  # mutate after signing
        return receipt

    result = LegalIRGuidanceReplay(
        policy=policy, revalidator=revalidator
    ).run(inventory)

    assert GuidanceReplayRejection.RECEIPT_UNSIGNED.value in (
        result.outcomes[0].rejection_reasons
    )
    assert result.accepted_count == 0


@pytest.mark.parametrize(
    "feature_id",
    [
        "token:shall",
        "source-text:private statute",
        "family:contains decoded output",
        "unbounded-free-form-feature",
    ],
)
def test_source_or_unbounded_feature_keys_are_rejected(feature_id) -> None:
    with pytest.raises(GuidanceRevalidationError):
        GuidanceFeatureDelta(
            feature_id=feature_id,
            family="deontic",
            weight_delta=0.1,
        )


def test_inventory_count_mismatch_blocks_otherwise_valid_candidate(tmp_path) -> None:
    policy, inventory = _inventory(tmp_path)
    policy = replace(policy, expected_report_count=142, expected_candidate_count=17)

    def revalidator(report, context):
        return _receipt_mapping(report, context)

    result = LegalIRGuidanceReplay(
        policy=policy, revalidator=revalidator
    ).run(inventory)

    assert len(result.inventory_errors) == 2
    assert GuidanceReplayRejection.INVENTORY_MISMATCH.value in (
        result.outcomes[0].rejection_reasons
    )
    assert result.accepted_count == 0


def test_non_candidate_is_audited_but_never_sent_to_revalidator(tmp_path) -> None:
    policy = _policy(expected_candidate_count=0)
    payload = _candidate_payload(policy, promotion_allowed=False)
    path = tmp_path / "blocked.compiler-guidance-distillation.json"
    _write_report(path, payload)
    calls = 0

    def revalidator(_report, _context):
        nonlocal calls
        calls += 1
        raise AssertionError("non-candidate must not be replayed")

    result = LegalIRGuidanceReplay(
        policy=policy, revalidator=revalidator
    ).run([tmp_path])

    assert calls == 0
    assert result.audited_report_count == 1
    assert result.replay_candidate_count == 0
    assert result.outcomes == ()
    assert GuidanceReplayRejection.HISTORICAL_PROMOTION_NOT_ALLOWED.value in (
        result.audits[0].rejection_reasons
    )


def test_malformed_report_is_counted_and_source_free(tmp_path) -> None:
    path = tmp_path / "broken.compiler-guidance-distillation.json"
    path.write_text("{this is not valid json and contains SECRET}", encoding="utf-8")
    policy = _policy(expected_candidate_count=0)

    result = LegalIRGuidanceReplay(policy=policy).run([tmp_path])
    serialized = json.dumps(result.to_dict(), sort_keys=True)

    assert result.audited_report_count == 1
    assert result.audits[0].rejection_reasons == (
        GuidanceReplayRejection.HISTORICAL_PROMOTION_NOT_ALLOWED.value,
        GuidanceReplayRejection.INVALID_REPORT.value,
    )
    assert "SECRET" not in serialized


def test_receipt_requires_current_schema_even_when_other_gates_pass(tmp_path) -> None:
    policy, inventory = _inventory(tmp_path)

    def revalidator(report, context):
        return _receipt_mapping(
            report,
            context,
            schema_version="legacy-revalidation-schema",
        )

    result = LegalIRGuidanceReplay(
        policy=policy, revalidator=revalidator
    ).run(inventory)

    assert LEGAL_IR_GUIDANCE_REVALIDATION_SCHEMA_VERSION != (
        "legacy-revalidation-schema"
    )
    assert GuidanceReplayRejection.SCHEMA_MISMATCH.value in (
        result.outcomes[0].rejection_reasons
    )
    assert result.accepted_count == 0


def test_cli_consumes_signed_current_receipt_and_writes_safe_report(
    tmp_path, capsys
) -> None:
    policy = _policy(expected_report_count=None, expected_candidate_count=None)
    report_path = tmp_path / "cli.compiler-guidance-distillation.json"
    _write_report(report_path, _candidate_payload(policy))
    inventory = load_historical_compiler_guidance_reports([report_path])
    historical = inventory.reports[0]
    context = GuidanceRevalidationContext.for_report(historical, policy)
    receipt = _receipt_mapping(historical, context)
    receipts_path = tmp_path / "receipts.json"
    receipts_path.write_text(
        json.dumps({"receipts": {historical.content_digest: receipt}}),
        encoding="utf-8",
    )
    trust_path = tmp_path / "trust.json"
    trust_path.write_text(
        json.dumps({"trusted_signers": {"current-replay-signer": SECRET}}),
        encoding="utf-8",
    )
    output = tmp_path / "result.json"

    exit_code = replay_cli_main(
        [
            "--input",
            str(report_path),
            "--output",
            str(output),
            "--compiler-commit",
            policy.compiler_commit,
            "--compiler-schema-version",
            policy.compiler_schema_version,
            "--canonicalization-version",
            policy.canonicalization_version,
            "--fixed-holdout-id",
            policy.fixed_holdout_id,
            "--fixed-holdout-digest",
            policy.fixed_holdout_digest,
            "--proof-policy-version",
            policy.proof_policy_version,
            "--provenance-policy-version",
            policy.provenance_policy_version,
            "--source-copy-policy-version",
            policy.source_copy_policy_version,
            "--lineage-id",
            policy.lineage_id,
            "--base-state-digest",
            policy.base_state_digest,
            "--evaluation-time",
            policy.evaluation_time,
            "--max-report-age-seconds",
            str(policy.max_report_age_seconds),
            "--max-feature-deltas",
            str(policy.max_feature_deltas),
            "--trust-store",
            str(trust_path),
            "--revalidation-receipts",
            str(receipts_path),
            "--allow-noncanonical-counts",
            "--require-accepted",
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    captured = capsys.readouterr()

    assert exit_code == 0
    assert payload["accepted_count"] == 1
    assert payload["feature_updates"][0]["capacity_family"] == "compiler_guidance"
    assert payload["feature_updates"][0]["bounded"] is True
    assert payload["privacy"]["raw_reports_serialized"] is False
    assert SECRET not in output.read_text(encoding="utf-8")
    assert "accepted=1" in captured.out
