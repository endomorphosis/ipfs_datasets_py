"""Conformance tests for canonical CVEfixes derived dataset records."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import math

import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import (
    CVEFIXES_SCHEMA_VERSION,
    CVEfixesSchemaError,
    CodeUnit,
    DerivedDataset,
    EvaluationRecord,
    FormalView,
    GraphEdge,
    GraphNode,
    PolicyCandidate,
    ReleaseManifest,
    SourceRecord,
    canonical_config_cid,
    record_from_dict,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="test", schema_version="test/v1"
    ).cid


SOURCE_CID = _cid("pinned-source")
PARENT_CID = _cid("parent")
CONFIG_CID = canonical_config_cid({"projector": "1.0", "bounded": True})


def _bindings(parent: str = PARENT_CID) -> dict[str, object]:
    return {
        "source_cids": (SOURCE_CID,),
        "parent_cids": (parent,),
        "config_cid": CONFIG_CID,
    }


def _records() -> tuple[object, ...]:
    source = SourceRecord(
        **_bindings(),
        source_uri="hf://datasets/hitoshura25/cvefixes",
        source_revision="d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2",
        row_key="CVE-2020-0001:abc123",
        payload={"cve_id": "CVE-2020-0001", "description": "inert text"},
    )
    vulnerable = CodeUnit(
        **_bindings(source.cid),
        unit_kind="hunk",
        language="python",
        path="src/parser.py",
        polarity="vulnerable",
        payload={"start_line": 10, "end_line": 12},
    )
    node = GraphNode(
        **_bindings(vulnerable.cid),
        node_type="code_unit",
        payload={"code_unit_cid": vulnerable.cid},
    )
    other_node = GraphNode(
        **_bindings(source.cid),
        node_type="cwe",
        payload={"cwe_id": "CWE-20"},
    )
    edge = GraphEdge(
        **_bindings(node.cid),
        edge_type="HAS_WEAKNESS",
        source_node_cid=node.cid,
        target_node_cid=other_node.cid,
    )
    candidate = PolicyCandidate(
        **_bindings(vulnerable.cid),
        effect="deny",
        scope={"language": "python", "operation": "unsafe_parse"},
        payload={"review_status": "unreviewed"},
    )
    formal = FormalView(
        **_bindings(candidate.cid),
        formalism="smtlib2",
        expression="(assert (not unsafe_parse))",
    )
    evaluation = EvaluationRecord(
        **_bindings(formal.cid),
        subject_cids=(candidate.cid, formal.cid),
        metrics={"fixed_negative_accuracy": 1.0, "vulnerable_recall": 0.9},
    )
    manifest = ReleaseManifest(
        **_bindings(evaluation.cid),
        dataset_id="Publicus/cvefixes-security-ir-graphrag",
        profile="public",
        record_cids=tuple(
            item.cid
            for item in (
                source,
                vulnerable,
                node,
                other_node,
                edge,
                candidate,
                formal,
                evaluation,
            )
        ),
        shard_cids=(_cid("shard-0"),),
    )
    return (
        source,
        vulnerable,
        node,
        other_node,
        edge,
        candidate,
        formal,
        evaluation,
        manifest,
    )


def test_every_record_round_trips_with_stable_canonical_identity() -> None:
    for record in _records():
        encoded = record.to_dict()
        decoded = record_from_dict(encoded)

        assert decoded == record
        assert decoded.to_dict() == encoded
        assert decoded.cid == record.cid
        assert decoded.identity.cid == record.record_id
        assert decoded.canonical_bytes() == record.canonical_bytes()
        assert type(record).from_json(record.to_json()) == record
        assert record.schema_version == CVEFIXES_SCHEMA_VERSION
        assert record.cid.startswith("bafkre")


def test_records_and_nested_payloads_are_immutable() -> None:
    source = _records()[0]

    with pytest.raises(FrozenInstanceError):
        source.row_key = "changed"
    with pytest.raises(TypeError):
        source.payload["cve_id"] = "changed"


def test_identity_is_order_stable_for_lineage_and_inventory_sets() -> None:
    source = _records()[0]
    first = ReleaseManifest(
        source_cids=(SOURCE_CID, _cid("source-2")),
        parent_cids=(source.cid, PARENT_CID),
        config_cid=CONFIG_CID,
        dataset_id="dataset/name",
        profile="internal",
        record_cids=(source.cid, _cid("record-2")),
        shard_cids=(_cid("shard-1"), _cid("shard-2")),
    )
    second = ReleaseManifest(
        source_cids=tuple(reversed(first.source_cids)),
        parent_cids=tuple(reversed(first.parent_cids)),
        config_cid=CONFIG_CID,
        dataset_id=first.dataset_id,
        profile=first.profile,
        record_cids=tuple(reversed(first.record_cids)),
        shard_cids=tuple(reversed(first.shard_cids)),
    )

    assert first == second
    assert first.cid == second.cid
    assert first.canonical_bytes() == second.canonical_bytes()


@pytest.mark.parametrize("missing", ["source_cids", "parent_cids", "config_cid"])
def test_source_parent_and_config_identities_are_mandatory(missing: str) -> None:
    values = {
        **_bindings(),
        "node_type": "cve",
        "payload": {"cve_id": "CVE-2020-0001"},
    }
    values.pop(missing)

    with pytest.raises((TypeError, CVEfixesSchemaError)):
        GraphNode(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_cids", ("not-a-cid",)),
        ("parent_cids", ()),
        ("config_cid", "sha256:" + "0" * 64),
    ],
)
def test_identity_bindings_must_use_shared_ir_core_cids(
    field: str, value: object
) -> None:
    values = {**_bindings(), "node_type": "cve"}
    values[field] = value

    with pytest.raises(CVEfixesSchemaError, match="CID|empty"):
        GraphNode(**values)


def test_nan_and_other_non_finite_numbers_fail_closed_at_construction() -> None:
    with pytest.raises(CVEfixesSchemaError, match="finite"):
        EvaluationRecord(
            **_bindings(),
            subject_cids=(_cid("subject"),),
            metrics={"recall": math.nan},
        )

    with pytest.raises(CVEfixesSchemaError, match="finite"):
        SourceRecord(
            **_bindings(),
            source_uri="hf://dataset",
            source_revision="revision",
            row_key="row",
            payload={"nested": [{"score": math.inf}]},
        )


def test_unknown_fields_and_unknown_record_types_fail_closed() -> None:
    source = _records()[0].to_dict()

    with pytest.raises(CVEfixesSchemaError, match="unknown source_record field"):
        record_from_dict({**source, "surprise": True})
    with pytest.raises(CVEfixesSchemaError, match="unknown record_type"):
        record_from_dict({**source, "record_type": "vendor_extension"})


def test_json_decoder_rejects_duplicate_keys_and_non_finite_numbers() -> None:
    with pytest.raises(CVEfixesSchemaError, match="duplicate field"):
        SourceRecord.from_json(
            '{"record_type":"source_record","record_type":"source_record"}'
        )
    with pytest.raises(CVEfixesSchemaError, match="non-finite"):
        SourceRecord.from_json('{"payload":{"score":NaN}}')


@pytest.mark.parametrize(
    "authority", ["authoritative", "reviewed", "execution_authority", True]
)
def test_derived_records_cannot_broaden_authority(authority: object) -> None:
    source = _records()[0].to_dict()
    candidate = _records()[5].to_dict()

    with pytest.raises(CVEfixesSchemaError, match="cannot grant authority"):
        record_from_dict({**source, "authority": authority})
    with pytest.raises(CVEfixesSchemaError, match="cannot grant authority"):
        record_from_dict({**candidate, "authority": authority})


def test_record_kind_cannot_switch_between_candidate_and_non_authoritative() -> None:
    source = _records()[0].to_dict()
    candidate = _records()[5].to_dict()

    with pytest.raises(CVEfixesSchemaError, match="cannot broaden authority"):
        record_from_dict({**source, "authority": "candidate"})
    with pytest.raises(CVEfixesSchemaError, match="cannot broaden authority"):
        record_from_dict({**candidate, "authority": "non_authoritative"})


def test_stale_or_caller_selected_record_ids_fail_integrity_check() -> None:
    source = _records()[0]

    with pytest.raises(CVEfixesSchemaError, match="record_id does not match"):
        SourceRecord.from_dict({**source.to_dict(), "record_id": _cid("forged")})
    with pytest.raises(CVEfixesSchemaError, match="record_id does not match"):
        replace(source, payload={"cve_id": "changed"})


def test_duplicate_ids_fail_in_lineage_manifest_and_dataset() -> None:
    source = _records()[0]

    with pytest.raises(CVEfixesSchemaError, match="duplicate IDs"):
        GraphNode(
            source_cids=(SOURCE_CID, SOURCE_CID),
            parent_cids=(source.cid,),
            config_cid=CONFIG_CID,
            node_type="cve",
        )
    with pytest.raises(CVEfixesSchemaError, match="duplicate IDs"):
        ReleaseManifest(
            **_bindings(source.cid),
            dataset_id="dataset/name",
            profile="public",
            record_cids=(source.cid, source.cid),
            shard_cids=(_cid("shard"),),
        )
    with pytest.raises(CVEfixesSchemaError, match="duplicate IDs"):
        DerivedDataset(records=(source, source))


def test_dataset_round_trip_is_order_independent_and_tamper_evident() -> None:
    records = _records()
    first = DerivedDataset(records=records)
    second = DerivedDataset(records=tuple(reversed(records)))

    assert first == second
    assert first.cid == second.cid
    assert DerivedDataset.from_dict(first.to_dict()) == first
    assert DerivedDataset.from_json(first.to_json()) == first
    assert first.canonical_bytes() == second.canonical_bytes()

    with pytest.raises(CVEfixesSchemaError, match="dataset_id does not match"):
        DerivedDataset.from_dict(
            {**first.to_dict(), "dataset_id": _cid("forged-dataset")}
        )


def test_policy_scope_and_metrics_are_required_and_finite() -> None:
    with pytest.raises(CVEfixesSchemaError, match="scope must not be empty"):
        PolicyCandidate(**_bindings(), effect="deny", scope={})
    with pytest.raises(CVEfixesSchemaError, match="metrics must not be empty"):
        EvaluationRecord(
            **_bindings(), subject_cids=(_cid("subject"),), metrics={}
        )
