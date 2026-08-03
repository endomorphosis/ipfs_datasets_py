"""Conformance tests for strict Solidity CPT derived schemas."""

from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError, replace

import pytest
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.release_policy import (
    SOLIDITY_CPT_DATASET_ID,
    SOLIDITY_CPT_REVISION,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.schemas import (
    SOLIDITY_CPT_SCHEMA_VERSION,
    CodeUnit,
    DerivedDataset,
    GraphNode,
    PolicyCandidate,
    ProducerConfig,
    SolidityCPTSchemaError,
    SourceRecord,
    TrustedLineage,
    record_from_dict,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.source_snapshot import (
    DEFAULT_ROW_BOUNDS,
    PINNED_SOURCE_SNAPSHOT,
    SolidityCPTRow,
    adapt_solidity_cpt_row,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label},
        domain="solidity-cpt-schema-test",
        schema_version="test/v1",
    ).cid


SOURCE_ROOT = PINNED_SOURCE_SNAPSHOT.cid
EXTERNAL_PARENT = _cid("source-observation")


def _raw_row() -> dict:
    text = "contract Vault { function read() public {} }"
    return {
        "text": text,
        "source": "etherscan",
        "address": "0x" + "1" * 40,
        "name": "Vault",
        "compiler": "v0.8.24",
        "license": "MIT",
        "path": "contracts/Vault.sol",
        "n_chars": len(text),
    }


ADAPTED = adapt_solidity_cpt_row(_raw_row(), row_index=7)
CONFIG = ProducerConfig(config=DEFAULT_ROW_BOUNDS.to_dict())
LINEAGE = TrustedLineage(
    source_cids=(SOURCE_ROOT,),
    producer_configs=(CONFIG,),
    source_rows=(ADAPTED.row,),
    external_parent_cids=(EXTERNAL_PARENT,),
)


def _source(
    *,
    source_cid: str = SOURCE_ROOT,
    parent_cid: str = EXTERNAL_PARENT,
    config_cid: str = CONFIG.config_cid,
    source_row: SolidityCPTRow = ADAPTED.row,
    payload: dict | None = None,
) -> SourceRecord:
    return SourceRecord(
        source_cids=(source_cid,),
        parent_cids=(parent_cid,),
        config_cid=config_cid,
        source_uri=f"hf://datasets/{SOLIDITY_CPT_DATASET_ID}",
        source_revision=SOLIDITY_CPT_REVISION,
        row_key="train:7",
        source_row_id=source_row.row_id,
        raw_row_cid=source_row.raw_row_cid,
        source_body_cid=source_row.source_body_cid,
        source_body_sha256=source_row.source_body_sha256,
        payload=payload
        or {
            "address": source_row.address,
            "compiler": source_row.compiler,
            "license": source_row.license,
            "n_chars": source_row.n_chars,
            "name": source_row.name,
            "path": source_row.path,
            "row_index": source_row.row_index,
            "source_provider": source_row.source,
        },
    )


def _dataset() -> DerivedDataset:
    source = _source()
    node = GraphNode(
        source_cids=(SOURCE_ROOT,),
        parent_cids=(source.cid,),
        config_cid=CONFIG.config_cid,
        node_type="source_unit",
        payload={"source_record_cid": source.cid},
    )
    unit = CodeUnit(
        source_cids=(SOURCE_ROOT,),
        parent_cids=(node.cid,),
        config_cid=CONFIG.config_cid,
        unit_kind="contract",
        language="solidity",
        path="contracts/Vault.sol",
        payload={"name": "Vault"},
    )
    candidate = PolicyCandidate(
        source_cids=(SOURCE_ROOT,),
        parent_cids=(unit.cid,),
        config_cid=CONFIG.config_cid,
        effect="require",
        scope={"operation": "external_call", "mitigation": "checks_effects"},
        payload={"review_status": "unreviewed"},
    )
    return DerivedDataset(
        records=(candidate, unit, node, source),
        lineage=LINEAGE,
    )


def test_records_round_trip_with_stable_rehashed_identity() -> None:
    dataset = _dataset()
    for record in dataset.records:
        wire = record.to_dict()
        decoded = record_from_dict(wire)

        assert decoded == record
        assert decoded.cid == record.cid
        assert decoded.identity.cid == record.record_id
        assert type(record).from_json(record.to_json()) == record
        assert record.schema_version == SOLIDITY_CPT_SCHEMA_VERSION
        assert record.cid.startswith("bafkre")

    source = next(item for item in dataset.records if isinstance(item, SourceRecord))
    with pytest.raises(FrozenInstanceError):
        source.row_key = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        source.payload["path"] = "changed"


def test_persisted_record_rejects_payload_lineage_and_caller_id_tampering() -> None:
    source = _source()
    wire = source.to_dict()

    with pytest.raises(SolidityCPTSchemaError, match="record_id"):
        SourceRecord.from_dict({**wire, "payload": {**wire["payload"], "license": "changed"}})
    with pytest.raises(SolidityCPTSchemaError, match="record_id"):
        SourceRecord.from_dict({**wire, "source_cids": [_cid("foreign-source")]})
    with pytest.raises(SolidityCPTSchemaError, match="record_id"):
        SourceRecord.from_dict({**wire, "parent_cids": [_cid("foreign-parent")]})
    with pytest.raises(SolidityCPTSchemaError, match="record_id"):
        SourceRecord.from_dict({**wire, "config_cid": _cid("foreign-config")})
    with pytest.raises(SolidityCPTSchemaError, match="record_id"):
        SourceRecord.from_dict({**wire, "record_id": _cid("caller-selected")})


def test_persisted_identity_fields_are_mandatory_not_silently_minted() -> None:
    source_wire = _source().to_dict()
    source_wire.pop("record_id")
    with pytest.raises(SolidityCPTSchemaError, match="requires record_id|missing=record_id"):
        SourceRecord.from_dict(source_wire)

    config_wire = CONFIG.to_dict()
    config_wire.pop("config_cid")
    with pytest.raises(SolidityCPTSchemaError, match="schema drift"):
        ProducerConfig.from_dict(config_wire)

    lineage_wire = LINEAGE.to_dict()
    lineage_wire.pop("context_id")
    with pytest.raises(SolidityCPTSchemaError, match="schema drift"):
        TrustedLineage.from_dict(lineage_wire)

    dataset_wire = _dataset().to_dict()
    dataset_wire.pop("dataset_id")
    with pytest.raises(SolidityCPTSchemaError, match="schema drift"):
        DerivedDataset.from_dict(dataset_wire, expected_lineage=LINEAGE)


def test_nested_dataset_rehash_rejects_stale_inner_and_outer_ids() -> None:
    dataset = DerivedDataset(records=(_source(),), lineage=LINEAGE)
    wire = dataset.to_dict()
    nested = dict(wire["records"][0])
    nested["payload"] = {**nested["payload"], "compiler": "changed"}
    stale_inner = {**wire, "records": [nested]}

    with pytest.raises(SolidityCPTSchemaError, match="record_id"):
        DerivedDataset.from_dict(stale_inner, expected_lineage=LINEAGE)

    source = _source()
    added = GraphNode(
        source_cids=(SOURCE_ROOT,),
        parent_cids=(source.cid,),
        config_cid=CONFIG.config_cid,
        node_type="source_unit",
        payload={"source_record_cid": source.cid},
    )
    stale_outer = {**wire, "records": [source.to_dict(), added.to_dict()]}
    with pytest.raises(SolidityCPTSchemaError, match="dataset_id"):
        DerivedDataset.from_dict(stale_outer, expected_lineage=LINEAGE)

    forged = {**wire, "dataset_id": _cid("caller-dataset")}
    with pytest.raises(SolidityCPTSchemaError, match="dataset_id"):
        DerivedDataset.from_dict(forged, expected_lineage=LINEAGE)


def test_fully_rehashed_foreign_lineage_still_fails_trusted_context() -> None:
    foreign_parent = _cid("foreign-parent")
    foreign_config = ProducerConfig(config={"adapter": "foreign"})
    foreign_row = replace(
        ADAPTED.row,
        config_cid=foreign_config.config_cid,
        row_id="",
    )
    foreign_lineage = TrustedLineage(
        source_cids=(SOURCE_ROOT,),
        producer_configs=(foreign_config,),
        source_rows=(foreign_row,),
        external_parent_cids=(foreign_parent,),
    )
    foreign_record = _source(
        source_cid=SOURCE_ROOT,
        parent_cid=foreign_parent,
        config_cid=foreign_config.config_cid,
        source_row=foreign_row,
    )
    self_consistent_foreign = DerivedDataset(
        records=(foreign_record,),
        lineage=foreign_lineage,
    )

    with pytest.raises(SolidityCPTSchemaError, match="trusted context"):
        DerivedDataset.from_dict(
            self_consistent_foreign.to_dict(),
            expected_lineage=LINEAGE,
        )


def test_dataset_round_trip_is_order_independent_and_requires_lineage() -> None:
    dataset = _dataset()
    reversed_dataset = DerivedDataset(
        records=tuple(reversed(dataset.records)),
        lineage=LINEAGE,
    )

    assert reversed_dataset == dataset
    assert reversed_dataset.cid == dataset.cid
    assert DerivedDataset.from_dict(dataset.to_dict(), expected_lineage=LINEAGE) == dataset
    assert DerivedDataset.from_json(dataset.to_json(), expected_lineage=LINEAGE) == dataset
    with pytest.raises(TypeError):
        DerivedDataset.from_dict(dataset.to_dict())  # type: ignore[call-arg]


def test_derived_records_are_source_body_free_and_non_granting() -> None:
    sentinel = "SOURCE-BODY-SENTINEL"
    with pytest.raises(SolidityCPTSchemaError, match="source body"):
        _source(payload={"nested": {"text": sentinel}})
    with pytest.raises(SolidityCPTSchemaError, match="non-projection"):
        _source(payload={"solidity": sentinel + " contract X {}"})
    changed_projection = dict(_source().payload)
    changed_projection["compiler"] = sentinel
    with pytest.raises(SolidityCPTSchemaError, match="normalized row"):
        DerivedDataset(
            records=(_source(payload=changed_projection),),
            lineage=LINEAGE,
        )
    with pytest.raises(SolidityCPTSchemaError, match="grant authority"):
        _source(payload={"nested": {"grants_authority": True}})
    with pytest.raises(SolidityCPTSchemaError, match="bytecode equality"):
        _source(payload={"deployed_bytecode_equal": True})

    serialized = json.dumps(_dataset().to_dict(), sort_keys=True)
    assert sentinel not in serialized
    assert '"text"' not in serialized
    source = _source()
    assert source.address_is_unverified_hint is True
    assert source.deployed_bytecode_equality is False


@pytest.mark.parametrize("authority", ["authoritative", "reviewed", True])
def test_unknown_or_granting_authority_fails_closed(authority: object) -> None:
    wire = _source().to_dict()
    wire["authority"] = authority

    with pytest.raises(SolidityCPTSchemaError, match="authority"):
        SourceRecord.from_dict(wire)


def test_json_duplicate_keys_nonfinite_values_and_duplicate_ids_fail() -> None:
    with pytest.raises(SolidityCPTSchemaError, match="duplicate field"):
        SourceRecord.from_json('{"record_type":"source_record","record_type":"source_record"}')
    with pytest.raises(SolidityCPTSchemaError, match="non-finite"):
        SourceRecord.from_json('{"payload":{"score":NaN}}')
    with pytest.raises(SolidityCPTSchemaError, match="finite"):
        _source(payload={"score": math.nan})

    source = _source()
    with pytest.raises(SolidityCPTSchemaError, match="duplicate IDs"):
        DerivedDataset(records=(source, source), lineage=LINEAGE)


def test_config_and_lineage_artifacts_rehash_on_load() -> None:
    assert ProducerConfig.from_dict(CONFIG.to_dict()) == CONFIG
    assert TrustedLineage.from_dict(LINEAGE.to_dict()) == LINEAGE

    stale_config = {**CONFIG.to_dict(), "config": {"adapter": "changed"}}
    with pytest.raises(SolidityCPTSchemaError, match="config_cid"):
        ProducerConfig.from_dict(stale_config)

    stale_lineage = {
        **LINEAGE.to_dict(),
        "external_parent_cids": [_cid("changed-parent")],
    }
    with pytest.raises(SolidityCPTSchemaError, match="context_id"):
        TrustedLineage.from_dict(stale_lineage)
