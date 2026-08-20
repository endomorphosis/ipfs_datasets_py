"""Contracts for versioned source, derived, lineage, and corpus records."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ir_core.provenance import SourceRef, SourceReviewStatus
from ipfs_datasets_py.logic.ir_core.schema_registry import CompatibilityStatus
from ipfs_datasets_py.logic.ir_core.source_lineage import (
    CORPUS_MANIFEST_SCHEMA,
    SOURCE_RECORD_SCHEMA,
    SOURCE_RECORD_SCHEMA_V1_1,
    CorpusManifest,
    DerivedArtifactRecord,
    LineageEdge,
    LineageGraph,
    LineageRelation,
    RecordKind,
    RightsDisposition,
    RightsRecord,
    SourceLineageError,
    SourceRecord,
    SourceRelease,
    TemporalCoverage,
    source_lineage_schema_registry,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _rights(*, disposition: RightsDisposition = RightsDisposition.QUARANTINED) -> RightsRecord:
    return RightsRecord(
        disposition=disposition,
        license_expression="cc0-1.0",
        source_rights_status="resolved" if disposition is RightsDisposition.ADMITTED else "unresolved",
        transformation_rights_status="unresolved",
        scope="every named configuration",
    )


def _temporal() -> TemporalCoverage:
    return TemporalCoverage(cutoff_status="unknown", cutoff_value=None, observed_at_ms=1_700_000_000_000)


def _source_ref() -> SourceRef:
    return SourceRef(
        ref_id="ref:patent-1",
        source_uri="hf://datasets/justicedao/patent-legal-ir-graphrag@deadbeef",
        source_id="justicedao/patent-legal-ir-graphrag",
        source_revision="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        content_sha256=DIGEST_A,
        review_status=SourceReviewStatus.MACHINE_EXTRACTED,
    )


def _release() -> SourceRelease:
    return SourceRelease(
        release_id="rel:patent",
        repository_id="justicedao/patent-legal-ir-graphrag",
        revision="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        pinset_id="JDAO-PINSET-1",
        rights=_rights(),
        temporal=_temporal(),
        configuration_ids=("articles",),
    )


def _source() -> SourceRecord:
    return SourceRecord(
        record_id="src:patent-1",
        release_id="rel:patent",
        lineage_group_id="grp:patent-1",
        source_ref=_source_ref(),
        rights=_rights(),
        temporal=_temporal(),
        jurisdiction="US",
    )


def test_round_trip_preserves_identity_and_kind_separation() -> None:
    release = _release()
    source = _source()
    derived = DerivedArtifactRecord(
        artifact_id="drv:patent-1-embedding",
        parent_record_ids=("src:patent-1",),
        derivation_kind="embedding",
        content_sha256=DIGEST_B,
        rights=_rights(),
    )
    graph = LineageGraph(
        graph_id="lin:patent-1",
        node_ids=("src:patent-1", "drv:patent-1-embedding"),
        edges=(
            LineageEdge(
                parent_id="src:patent-1",
                child_id="drv:patent-1-embedding",
                relation=LineageRelation.DERIVED_FROM,
            ),
        ),
    )
    corpus = CorpusManifest(
        manifest_id="corp:pilot",
        source_record_ids=("src:patent-1",),
        derived_artifact_ids=("drv:patent-1-embedding",),
        lineage_graph_id="lin:patent-1",
        rights=_rights(),
    )

    assert SourceRelease.from_dict(release.to_dict()).record_cid == release.record_cid
    assert SourceRecord.from_dict(source.to_dict()).record_cid == source.record_cid
    assert DerivedArtifactRecord.from_dict(derived.to_dict()).record_cid == derived.record_cid
    assert LineageGraph.from_dict(graph.to_dict()).record_cid == graph.record_cid
    assert CorpusManifest.from_dict(corpus.to_dict()).record_cid == corpus.record_cid
    assert release.to_dict()["kind"] == RecordKind.SOURCE_RELEASE.value
    assert source.to_dict()["kind"] == RecordKind.SOURCE_RECORD.value
    assert derived.to_dict()["kind"] == RecordKind.DERIVED_ARTIFACT.value
    assert corpus.source_count == 1
    assert corpus.derived_count == 1


def test_unknown_fields_and_float_timestamps_fail_closed() -> None:
    payload = _source().to_dict()
    payload["extra"] = True
    with pytest.raises(SourceLineageError, match="unknown field"):
        SourceRecord.from_dict(payload)

    temporal = _temporal().to_dict()
    temporal["observed_at_ms"] = 1.5
    with pytest.raises(SourceLineageError, match="integer"):
        TemporalCoverage.from_dict(temporal)


def test_admitted_rights_and_derived_source_inflation_fail_closed() -> None:
    with pytest.raises(SourceLineageError, match="resolved source-rights"):
        RightsRecord(
            disposition=RightsDisposition.ADMITTED,
            license_expression="cc0-1.0",
            source_rights_status="unresolved",
            transformation_rights_status="unresolved",
            scope="all",
        ).validate()

    with pytest.raises(SourceLineageError, match="cannot be admitted as training sources"):
        DerivedArtifactRecord(
            artifact_id="drv:bad",
            parent_record_ids=("src:patent-1",),
            derivation_kind="embedding",
            content_sha256=DIGEST_B,
            rights=_rights(disposition=RightsDisposition.ADMITTED),
        ).validate()

    with pytest.raises(SourceLineageError, match="cannot be counted as source"):
        CorpusManifest(
            manifest_id="corp:bad",
            source_record_ids=("src:patent-1",),
            derived_artifact_ids=("src:patent-1",),
            lineage_graph_id="lin:patent-1",
            rights=_rights(),
        ).validate()


def test_lineage_cycles_and_missing_nodes_fail_closed() -> None:
    with pytest.raises(SourceLineageError, match="cycle"):
        LineageGraph(
            graph_id="lin:cycle",
            node_ids=("a", "b"),
            edges=(
                LineageEdge("a", "b", LineageRelation.DERIVED_FROM),
                LineageEdge("b", "a", LineageRelation.DERIVED_FROM),
            ),
        ).validate()

    with pytest.raises(SourceLineageError, match="unknown node"):
        LineageGraph(
            graph_id="lin:missing",
            node_ids=("a",),
            edges=(LineageEdge("a", "missing", LineageRelation.DERIVED_FROM),),
        ).validate()


def test_canonical_identity_is_stable_and_not_a_float() -> None:
    first = _source().record_cid
    second = _source().record_cid
    assert first == second
    assert first.startswith("b")
    mutated = SourceRecord(
        record_id="src:patent-1",
        release_id="rel:patent",
        lineage_group_id="grp:patent-2",
        source_ref=_source_ref(),
        rights=_rights(),
        temporal=_temporal(),
        jurisdiction="US",
    )
    assert mutated.record_cid != first


def test_schema_registry_migration_and_unknown_schema_fail_closed() -> None:
    registry = source_lineage_schema_registry()
    payload = _source().identity_payload()

    negotiated = registry.negotiate(SOURCE_RECORD_SCHEMA, SOURCE_RECORD_SCHEMA_V1_1)
    assert negotiated.status is CompatibilityStatus.COMPATIBLE

    migrated = registry.migrate(
        payload,
        source_schema_id=SOURCE_RECORD_SCHEMA,
        destination_schema_id=SOURCE_RECORD_SCHEMA_V1_1,
    )
    assert migrated.payload["schema_version"] == SOURCE_RECORD_SCHEMA_V1_1
    assert migrated.payload["annotation"] == ""
    assert migrated.payload["record_id"] == "src:patent-1"

    exact = registry.negotiate(CORPUS_MANIFEST_SCHEMA, CORPUS_MANIFEST_SCHEMA)
    assert exact.status is CompatibilityStatus.EXACT

    with pytest.raises(Exception):
        registry.negotiate("ir-source-record/v9", SOURCE_RECORD_SCHEMA)
