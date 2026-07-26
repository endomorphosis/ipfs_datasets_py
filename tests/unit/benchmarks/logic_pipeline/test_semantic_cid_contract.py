"""CID and leakage invariants for the additive semantic protocol revision."""

from __future__ import annotations

import copy

import pytest

from benchmarks.logic_pipeline import contracts
from ipfs_datasets_py.utils.cid_utils import (
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)


FROZEN_V1_PROTOCOL_SHA256 = (
    "a12067c4239b9628fde065db3fe10e623148c95a55891a642306e0c90dee8fa3"
)
FROZEN_V1_VARIANT_REGISTRY_SHA256 = (
    "53a106ddd6c68af445d0a3a912b0d7d09e04c6b23500d4c6362bb5c089f2e44f"
)


def _projection(
    *,
    producer_id: str = "compiler",
    evidence_cid: str | None = None,
    validation_errors: tuple[str, ...] = (),
) -> contracts.SemanticProjection:
    return contracts.SemanticProjection.create(
        producer_id=producer_id,
        source_text="A licensed agency shall retain each record.",
        logic_family="Deontic Logic",
        target="retain_record",
        semantic_class="proved",
        predicates=("retain_record", "licensed_agency"),
        entities=("record", "licensed_agency"),
        ambiguity_flags=(),
        validation_errors=validation_errors,
        evidence_cid=(
            evidence_cid
            if evidence_cid is not None
            else cid_for_dag_json({"formulas": [{"id": "f1"}]})
        ),
    )


def test_semantic_v2_is_additive_and_v1_digest_is_immutable() -> None:
    from benchmarks.logic_pipeline.variants import VARIANT_REGISTRY_SHA256

    assert contracts.DEFAULT_PROTOCOL_SHA256 == FROZEN_V1_PROTOCOL_SHA256
    assert VARIANT_REGISTRY_SHA256 == FROZEN_V1_VARIANT_REGISTRY_SHA256
    assert (
        contracts.SEMANTIC_PARENT_VARIANT_REGISTRY_SHA256_V1
        == FROZEN_V1_VARIANT_REGISTRY_SHA256
    )
    assert contracts.SEMANTIC_PROTOCOL_V2.protocol_version == 2
    assert contracts.SEMANTIC_PROTOCOL_V2.parent_protocol_sha256 == (
        FROZEN_V1_PROTOCOL_SHA256
    )
    assert validate_cid(
        contracts.SEMANTIC_PROTOCOL_V2_CID,
        codecs=("dag-json",),
    ) == contracts.SEMANTIC_PROTOCOL_V2_CID


@pytest.mark.parametrize(
    "value",
    [
        contracts.SEMANTIC_PROJECTION_SCHEMA_V2_CID,
        contracts.SEMANTIC_NORMALIZATION_V2_CID,
        contracts.SEMANTIC_RESPONSE_SCHEMA_V2_CID,
        contracts.SEMANTIC_PRODUCER_REGISTRY_V2_CID,
        contracts.SEMANTIC_PROMPT_V2_CID,
        contracts.SEMANTIC_CALIBRATION_ROUTE_MANIFEST_V2_CID,
        contracts.SEMANTIC_CALIBRATION_METRIC_SPEC_V2_CID,
        contracts.SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID,
        contracts.SEMANTIC_PROTOCOL_V2_CID,
    ],
)
def test_semantic_protocol_components_are_dag_json_cids(value: str) -> None:
    assert validate_cid(value, codecs=("dag-json",)) == value


def test_reviewed_target_source_cid_recomputes_from_exact_spec() -> None:
    assert cid_for_dag_json(
        contracts.semantic_reviewed_target_source_v2()
    ) == contracts.SEMANTIC_REVIEWED_TARGET_SOURCE_V2_CID


def test_producer_registry_binds_adapter_and_evidence_identities() -> None:
    producers = contracts.semantic_producer_registry_v2()["producers"]

    assert isinstance(producers, list)
    assert {producer["producer_id"] for producer in producers} == set(
        contracts.SEMANTIC_PRODUCER_IDS_V2
    )
    for producer in producers:
        assert producer["adapter_version"] == "2"
        assert str(producer["evidence_schema"]).endswith(".v2")
        assert producer["evidence_cid_codec"] == "dag-json"
    symai = next(
        producer
        for producer in producers
        if producer["producer_id"] == "symai"
    )
    assert symai["raw_output_cid_codec"] == "raw"


def test_projection_round_trip_preserves_cid_codec_boundaries() -> None:
    projection = _projection(
        evidence_cid=cid_for_dag_json({"model": "validated response"})
    )

    assert projection.source_cid == cid_for_bytes(
        "A licensed agency shall retain each record.".encode("utf-8")
    )
    assert validate_cid(projection.source_cid, codecs=("raw",))
    assert validate_cid(projection.evidence_cid, codecs=("dag-json",))
    assert validate_cid(
        projection.semantic_content_cid,
        codecs=("dag-json",),
    )
    assert validate_cid(projection.projection_cid, codecs=("dag-json",))
    assert contracts.SemanticProjection.from_dict(
        projection.to_dict()
    ) == projection


def test_projection_rejects_raw_cid_for_structured_evidence() -> None:
    with pytest.raises(
        contracts.ProtocolContractError,
        match="evidence_cid is not a canonical CID",
    ):
        _projection(
            evidence_cid=cid_for_bytes(b'{"model":"raw response"}')
        )


def test_semantic_content_cid_is_producer_independent() -> None:
    evidence_cid = cid_for_dag_json({"same": "normalized evidence"})
    compiler = _projection(producer_id="compiler", evidence_cid=evidence_cid)
    spacy = _projection(
        producer_id="spacy_full_model",
        evidence_cid=evidence_cid,
    )

    assert compiler.semantic_content_cid == spacy.semantic_content_cid
    assert compiler.projection_cid != spacy.projection_cid


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_cid", cid_for_bytes(b"different source")),
        ("evidence_cid", cid_for_dag_json({"different": "evidence"})),
        ("semantic_content_cid", cid_for_dag_json({"forged": "semantics"})),
        ("projection_cid", cid_for_dag_json({"forged": "projection"})),
    ],
)
def test_projection_rejects_valid_but_mismatched_cids(
    field: str,
    replacement: str,
) -> None:
    record = copy.deepcopy(_projection().to_dict())
    record[field] = replacement

    with pytest.raises(
        contracts.ProtocolContractError,
        match="identity changed",
    ):
        contracts.SemanticProjection.from_dict(record)


def test_projection_rejects_unknown_or_missing_fields() -> None:
    unknown = dict(_projection().to_dict())
    unknown["expected_class"] = "proved"
    with pytest.raises(contracts.ProtocolContractError, match="unknown"):
        contracts.SemanticProjection.from_dict(unknown)

    missing = dict(_projection().to_dict())
    missing.pop("source_cid")
    with pytest.raises(contracts.ProtocolContractError, match="missing"):
        contracts.SemanticProjection.from_dict(missing)


def test_validation_errors_take_precedence_over_ambiguity() -> None:
    projection = contracts.SemanticProjection.create(
        producer_id="symai",
        source_text="The clause is structurally ambiguous.",
        logic_family="fol",
        target="ambiguous_clause",
        semantic_class="ambiguous",
        predicates=("ambiguous_clause",),
        entities=("clause",),
        ambiguity_flags=("multiple_valid_readings",),
        validation_errors=("response_schema_mismatch",),
        evidence_cid=cid_for_dag_json({"validated": "response"}),
    )

    assert projection.ambiguity_flags
    assert projection.validation_errors
    assert projection.scoreable is False


@pytest.mark.parametrize("value", [-1, 1_000_001, True, 0.5])
def test_projection_confidence_is_canonical_integer_millionths(
    value: object,
) -> None:
    with pytest.raises(
        contracts.ProtocolContractError,
        match="confidence_millionths",
    ):
        contracts.SemanticProjection.create(
            producer_id="compiler",
            source_text="Source",
            logic_family="fol",
            target="target",
            semantic_class="proved",
            predicates=("target",),
            entities=("entity",),
            confidence_millionths=value,  # type: ignore[arg-type]
            evidence_cid=cid_for_dag_json({"evidence": True}),
        )
