"""Trusted hammer/Leanstral feature-bus tests for the modal autoencoder."""

from __future__ import annotations

import json

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    TRUSTED_HAMMER_FEATURE_BUS_MAX_FEATURES,
    TRUSTED_HAMMER_FEATURE_BUS_MAX_VALUES_PER_FAMILY,
    TRUSTED_HAMMER_FEATURE_BUS_SCHEMA_VERSION,
    TRUSTED_HAMMER_FEATURE_FAMILIES,
    AdaptiveModalAutoencoder,
    build_trusted_hammer_leanstral_feature_bus,
    trusted_hammer_leanstral_feature_bus,
)


_RAW_LEANSTRAL_TEXT = "RAW_LEANSTRAL_PROOF_TEXT_MUST_NEVER_BE_LEARNED"
_FULL_SOURCE_SPAN = "FULL_SOURCE_SPAN_MUST_NEVER_BE_LEARNED"


def _trusted_guidance(*, reconstruction_status: str = "verified") -> dict:
    return {
        "accepted": True,
        "backend_statuses": {"cvc5": "unknown", "z3": "proved"},
        "contract_id": "legal-ir-view/deontic/v1",
        "drafted_logic_candidates": [
            {
                "candidate": _RAW_LEANSTRAL_TEXT,
                "confidence": 0.91,
                "contract_id": "legal-ir-view/deontic/v1",
                "logic_family": "deontic",
                "premise_hints": ["exception_scope_precedence"],
                "proof_text": _RAW_LEANSTRAL_TEXT,
                "source_span": _FULL_SOURCE_SPAN,
                "target_view": "deontic.ir",
            }
        ],
        "guidance_id": "trusted-feature-bus-1",
        "legal_ir_view": "deontic.ir",
        "metadata": {
            "obligation_family": "exception_scope_precedence",
            "raw_leanstral_text": _RAW_LEANSTRAL_TEXT,
            "source_text": _FULL_SOURCE_SPAN,
        },
        "obligation_family": "exception_scope_precedence",
        "obligation_id": "lir-obligation-1",
        "proof_checked": True,
        "proved": True,
        "ranked_guidance_features": [{"feature": _RAW_LEANSTRAL_TEXT}],
        "reconstruction_status": reconstruction_status,
        "repair_lane": "repair_deontic_bridge_quality_gate",
        "selected_premises": ["exception_scope_precedence"],
        "source": "hammer_verified_guidance",
        "source_span": _FULL_SOURCE_SPAN,
        "target_component": "deontic.ir",
        "trusted": True,
    }


def test_feature_bus_emits_all_bounded_contract_families_and_repair_labels() -> None:
    packet = build_trusted_hammer_leanstral_feature_bus(_trusted_guidance())
    receipt = packet.to_dict()

    assert receipt["schema_version"] == TRUSTED_HAMMER_FEATURE_BUS_SCHEMA_VERSION
    assert receipt["trusted"] is True
    assert receipt["bounded"] is True
    assert tuple(receipt["feature_families"]) == TRUSTED_HAMMER_FEATURE_FAMILIES
    assert receipt["feature_families"]["contract_id"] == [
        "legal-ir-view/deontic/v1"
    ]
    assert receipt["feature_families"]["obligation_family"] == [
        "exception_scope_precedence"
    ]
    assert receipt["feature_families"]["premise_family"] == [
        "exception_scope_precedence"
    ]
    assert receipt["feature_families"]["backend_status"] == [
        "cvc5:unknown",
        "z3:proved",
    ]
    assert receipt["feature_families"]["reconstruction_status"] == ["verified"]
    assert receipt["feature_families"]["repair_lane"] == [
        "deontic.ir:deontic.norm_semantics"
    ]
    assert receipt["per_view_repair_labels"] == {
        "deontic.ir": ["deontic.norm_semantics"]
    }
    assert "hammer:contract-id:legal_ir_view_deontic_v1" in packet.feature_keys
    assert "hammer:obligation-family:exception_scope_precedence" in packet.feature_keys
    assert "hammer:premise-family:exception_scope_precedence" in packet.feature_keys
    assert "hammer:backend-status:z3:proved" in packet.feature_keys
    assert "hammer:reconstruction-status:verified" in packet.feature_keys
    assert (
        "hammer:repair-lane:deontic_ir:deontic_norm_semantics"
        in packet.feature_keys
    )


def test_feature_bus_receipt_and_learning_payload_exclude_all_raw_text() -> None:
    packet = build_trusted_hammer_leanstral_feature_bus(_trusted_guidance())
    serialized_receipt = json.dumps(packet.to_dict(), sort_keys=True)
    serialized_target = json.dumps(packet.learning_payload, sort_keys=True)

    assert _RAW_LEANSTRAL_TEXT not in serialized_receipt
    assert _FULL_SOURCE_SPAN not in serialized_receipt
    assert _RAW_LEANSTRAL_TEXT not in serialized_target
    assert _FULL_SOURCE_SPAN not in serialized_target
    assert "drafted_logic_candidates[0].candidate" in packet.excluded_field_paths
    assert "drafted_logic_candidates[0].proof_text" in packet.excluded_field_paths
    assert "drafted_logic_candidates[0].source_span" in packet.excluded_field_paths
    assert "metadata.raw_leanstral_text" in packet.excluded_field_paths
    assert "metadata.source_text" in packet.excluded_field_paths
    assert "ranked_guidance_features" in packet.excluded_field_paths
    assert "source_span" in packet.excluded_field_paths
    assert set(packet.learning_payload["drafted_logic_candidates"][0]) == {
        "confidence",
        "logic_family",
        "target_view",
    }


def test_feature_bus_caps_vocabularies_and_collapses_unknown_statuses() -> None:
    guidance = _trusted_guidance()
    guidance["contract_ids"] = ["legal-ir-view/deontic/v1"] + [
        f"attacker-contract-{index}" for index in range(100)
    ]
    guidance["obligation_families"] = ["exception_scope_precedence"] + [
        f"attacker-obligation-{index}" for index in range(100)
    ]
    guidance["premise_families"] = ["theorem_template"] + [
        f"attacker-premise-{index}" for index in range(100)
    ]
    guidance["backend_statuses"] = {
        f"attacker-backend-{index}": f"attacker-status-{index}"
        for index in range(100)
    }
    guidance["backend_statuses"]["z3"] = "proved"
    guidance["reconstruction_receipts"] = [
        {"reconstruction_status": f"attacker-outcome-{index}"}
        for index in range(100)
    ]

    receipt = trusted_hammer_leanstral_feature_bus(guidance)

    assert receipt["feature_count"] <= TRUSTED_HAMMER_FEATURE_BUS_MAX_FEATURES
    assert all(
        len(values) <= TRUSTED_HAMMER_FEATURE_BUS_MAX_VALUES_PER_FAMILY
        for values in receipt["feature_families"].values()
    )
    assert "other:other" in receipt["feature_families"]["backend_status"]
    assert "other" in receipt["feature_families"]["reconstruction_status"]
    serialized = json.dumps(receipt, sort_keys=True)
    assert "attacker-contract" not in serialized
    assert "attacker-obligation" not in serialized
    assert "attacker-premise" not in serialized
    assert "attacker-backend" not in serialized
    assert "attacker-status" not in serialized
    assert "attacker-outcome" not in serialized


def test_untrusted_or_source_claim_only_guidance_produces_no_learning_features() -> None:
    explicitly_untrusted = _trusted_guidance()
    explicitly_untrusted["trusted"] = False
    source_claim_only = {
        "guidance_id": "source-claim-only",
        "source": "hammer_verified_guidance",
        "source_text": _FULL_SOURCE_SPAN,
        "target_component": "deontic.ir",
    }

    for guidance in (explicitly_untrusted, source_claim_only):
        receipt = trusted_hammer_leanstral_feature_bus(guidance)
        assert receipt["trusted"] is False
        assert receipt["feature_count"] == 0
        assert receipt["target_views"] == []
        assert all(not values for values in receipt["feature_families"].values())


def test_apply_guidance_learns_only_feature_bus_keys_and_reports_omissions() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall provide notice unless an exception applies.",
    )
    guidance = _trusted_guidance()
    guidance["sample_id"] = sample.sample_id
    autoencoder = AdaptiveModalAutoencoder()

    report = autoencoder.apply_leanstral_guidance(
        guidance,
        samples_by_id={sample.sample_id: sample},
        learning_rate=0.5,
    )

    assert report["status"] == "applied"
    assert report["trusted_feature_bus_item_count"] == 1
    assert report["trusted_feature_bus_feature_count"] > 0
    assert report["trusted_feature_bus_excluded_field_count"] >= 6
    assert (
        report["trusted_feature_bus_schema_version"]
        == TRUSTED_HAMMER_FEATURE_BUS_SCHEMA_VERSION
    )
    learned_keys = tuple(autoencoder.state.feature_legal_ir_view_logits)
    assert "hammer:contract-id:legal_ir_view_deontic_v1" in learned_keys
    assert "hammer:obligation-family:exception_scope_precedence" in learned_keys
    assert "hammer:premise-family:exception_scope_precedence" in learned_keys
    serialized_keys = json.dumps(learned_keys)
    assert _RAW_LEANSTRAL_TEXT not in serialized_keys
    assert _FULL_SOURCE_SPAN not in serialized_keys
    assert "ranked-guidance" not in serialized_keys


def test_failed_trusted_reconstruction_uses_registered_lane_for_each_view() -> None:
    guidance = _trusted_guidance(reconstruction_status="kernel_rejected")
    guidance.pop("repair_lane")
    packet = build_trusted_hammer_leanstral_feature_bus(guidance)

    assert packet.per_view_repair_labels == {
        "deontic.ir": ("deontic.norm_semantics",)
    }
    assert packet.feature_families["repair_lane"] == (
        "deontic.ir:deontic.norm_semantics",
    )
