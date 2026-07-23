from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.modal import (
    INTROSPECTION_METRIC_CONFIG_VERSION,
    INTROSPECTION_METRIC_SCHEMA_VERSION,
    LEANSTRAL_CANARY_MANIFEST_VERSION,
    REQUIRED_LEGAL_LOGIC_FAMILIES,
    IntrospectionMetricRecord,
    IntrospectionMetricSchemaError,
    LeanstralCanaryManifest,
    build_introspection_metric_record,
    load_leanstral_canary_manifest,
    validate_leanstral_canary_manifest,
)


FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "logic"
    / "modal"
    / "leanstral_canary_manifest.json"
)


def _fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_canary_manifest_is_frozen_versioned_and_stratified() -> None:
    manifest = load_leanstral_canary_manifest(FIXTURE)
    payload = manifest.to_dict()

    assert manifest.manifest_version == LEANSTRAL_CANARY_MANIFEST_VERSION
    assert manifest.metric_schema_version == INTROSPECTION_METRIC_SCHEMA_VERSION
    assert tuple(manifest.required_families) == REQUIRED_LEGAL_LOGIC_FAMILIES
    assert manifest.frozen is True
    assert {case.family for case in manifest.cases} == set(REQUIRED_LEGAL_LOGIC_FAMILIES)
    assert len(manifest.cases) >= len(REQUIRED_LEGAL_LOGIC_FAMILIES)
    assert payload == _fixture_payload()

    for case in manifest.cases:
        assert case.schema_version == INTROSPECTION_METRIC_SCHEMA_VERSION
        assert case.record_id == case.expected_record_id()
        assert case.family in case.learned_ir_view_by_family
        assert case.compiler_ir.cross_entropy_loss >= 0.0
        assert case.compiler_ir.cosine_loss >= 0.0
        assert case.source_to_decoded.embedding_cosine_loss >= 0.0
        assert case.source_to_decoded.token_loss >= 0.0
        assert case.validity.structural_valid is True
        assert case.validity.prover_compiles is True
        assert case.anti_copy.anti_copy_penalty >= 0.0
        assert case.versions.state_version
        assert case.versions.config_version == INTROSPECTION_METRIC_CONFIG_VERSION
        assert {timing.phase for timing in case.phase_timings} == {
            "compiler_ir_metrics",
            "encode",
            "learned_ir_view_metrics",
            "prover_validation",
        }


def test_metric_record_round_trip_is_stable_and_hash_bound() -> None:
    raw = _fixture_payload()["cases"][0]
    record = IntrospectionMetricRecord.from_mapping(raw)
    encoded = record.to_json()
    again = IntrospectionMetricRecord.from_mapping(json.loads(encoded))

    assert encoded == again.to_json()
    assert json.loads(encoded)["record_id"] == raw["record_id"]

    changed = json.loads(encoded)
    changed["compiler_ir"]["cross_entropy_loss"] += 0.001
    with pytest.raises(IntrospectionMetricSchemaError, match="record_id"):
        IntrospectionMetricRecord.from_mapping(changed)


def test_build_metric_record_freezes_all_required_metric_groups() -> None:
    record = build_introspection_metric_record(
        case_id="unit-deontic",
        family="deontic",
        source_text="The agency shall provide notice.",
        modal_ir_hash="modal-ir-unit",
        losses={
            "cosine_loss": 0.12,
            "cosine_similarity": 0.88,
            "cross_entropy_excess_loss": 0.04,
            "cross_entropy_loss": 0.22,
            "source_copy_loss": 0.02,
            "source_copy_reward_hack_penalty": 0.01,
            "source_decompiled_text_embedding_cosine_loss": 0.08,
            "source_decompiled_text_embedding_cosine_similarity": 0.92,
            "source_decompiled_text_token_loss": 0.07,
            "source_decompiled_text_token_similarity": 0.93,
            "source_span_copy_ratio": 0.02,
        },
        learned_ir_view_by_family={
            "deontic": {
                "cosine_loss": 0.05,
                "cosine_similarity": 0.95,
                "cross_entropy_excess_loss": 0.03,
                "cross_entropy_loss": 0.18,
                "family": "deontic",
                "predicted_probability": 0.91,
                "target_probability": 1.0,
            }
        },
        validity={
            "attempted_count": 2,
            "failure_ratio": 0.0,
            "modal_ir_valid": True,
            "proofs_valid": True,
            "proved_count": 2,
            "prover_compiles": True,
            "structural_valid": True,
            "valid_count": 2,
        },
        phase_timings={
            "compiler_ir_metrics": 0.4,
            "encode": 1.0,
            "learned_ir_view_metrics": 0.5,
            "prover_validation": 0.6,
        },
    )

    payload = record.to_dict()
    assert payload["record_id"].startswith("lir-metric-")
    assert payload["compiler_ir"]["cross_entropy_loss"] == 0.22
    assert payload["compiler_ir"]["cosine_similarity"] == 0.88
    assert payload["learned_ir_view_by_family"]["deontic"]["cross_entropy_loss"] == 0.18
    assert payload["source_to_decoded"]["embedding_cosine_loss"] == 0.08
    assert payload["validity"]["proofs_valid"] is True
    assert payload["anti_copy"]["anti_copy_penalty"] == 0.01
    assert payload["versions"]["config_version"] == INTROSPECTION_METRIC_CONFIG_VERSION
    assert len(payload["phase_timings"]) == 4


def test_unknown_versions_fail_closed() -> None:
    payload = _fixture_payload()
    payload["manifest_version"] = "legal-ir-leanstral-canary-manifest-v999"
    with pytest.raises(IntrospectionMetricSchemaError, match="manifest_version"):
        validate_leanstral_canary_manifest(payload)

    payload = _fixture_payload()
    payload["metric_schema_version"] = "legal-ir-introspection-metrics-v999"
    with pytest.raises(IntrospectionMetricSchemaError, match="metric_schema_version"):
        validate_leanstral_canary_manifest(payload)

    payload = _fixture_payload()
    payload["cases"][0]["schema_version"] = "legal-ir-introspection-metrics-v999"
    with pytest.raises(IntrospectionMetricSchemaError, match="schema_version"):
        LeanstralCanaryManifest.from_mapping(payload)


def test_manifest_rejects_missing_required_family_and_unknown_record_family() -> None:
    payload = _fixture_payload()
    payload["cases"] = [
        case for case in payload["cases"] if case["family"] != REQUIRED_LEGAL_LOGIC_FAMILIES[0]
    ]
    with pytest.raises(IntrospectionMetricSchemaError, match="missing required families"):
        validate_leanstral_canary_manifest(payload)

    payload = _fixture_payload()
    payload["cases"][0]["family"] = "invented_family"
    payload["cases"][0]["learned_ir_view_by_family"]["invented_family"] = (
        payload["cases"][0]["learned_ir_view_by_family"].pop("alethic")
    )
    payload["cases"][0]["learned_ir_view_by_family"]["invented_family"]["family"] = (
        "invented_family"
    )
    payload["cases"][0]["record_id"] = ""
    with pytest.raises(IntrospectionMetricSchemaError, match="unknown LegalIR family"):
        validate_leanstral_canary_manifest(payload)
