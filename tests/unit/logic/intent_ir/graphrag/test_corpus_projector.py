from __future__ import annotations

from dataclasses import replace
import inspect

import pytest

from ipfs_datasets_py.logic.intent_ir.graphrag import corpus_projector
from ipfs_datasets_py.logic.intent_ir.graphrag.corpus_projector import (
    CorpusCitation,
    CorpusEvidenceRecord,
    CorpusMention,
    CorpusProjectionError,
    CorpusProjector,
    IPLDArtifactStore,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.ontology import (
    AddressedArtifact,
    CORPUS_GRAPH_SCHEMA_VERSION,
    CORPUS_ONTOLOGY,
    CORPUS_ONTOLOGY_VERSION,
    CorpusEdgeType,
    CorpusGraphEdge,
    CorpusGraphNode,
    CorpusGraphValidationError,
    CorpusNodeType,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.policy import (
    AllowedUseDecision,
    SkillSourcePolicy,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (
    SkillCenterSkillRecord,
)
from ipfs_datasets_py.logic.ir_core.identity import cid_v1


class RecordingStore:
    def __init__(self) -> None:
        self.blocks: dict[str, tuple[bytes, str]] = {}
        self.calls: list[tuple[str, str]] = []

    def put_bytes(self, payload: bytes, *, media_type: str) -> str:
        cid = cid_v1(payload)
        self.blocks[cid] = (payload, media_type)
        self.calls.append((cid, media_type))
        return cid


def _record(**changes: object) -> SkillCenterSkillRecord:
    values: dict[str, object] = {
        "skill_id": "skill-1",
        "domain": "security",
        "profile": "security",
        "source_type": "github",
        "source_url": "https://github.com/example/project/blob/main/SKILL.md",
        "title": "Bounded fixture",
        "overall_score": 4.0,
        "skill_kind": "github",
        "language": "en",
        "source_id": "source-1",
        "primary_source_id": "primary-1",
        "metadata_yaml": (
            'license_spdx: "MIT"\n'
            'author: "Example Maintainer"\n'
            "tools: [git, curl]\n"
        ),
        "skill_md": (
            "# Install\n\nUse the package.\n"
            "## Verify\n\nSee https://example.test/reference.\n"
        ),
        "library_md": "",
        "dataset_id": "example/skillcenter",
        "dataset_revision": "revision-123",
        "repository_file": "pilot/security.sqlite",
        "bundle_sha256": "a" * 64,
    }
    values.update(changes)
    return SkillCenterSkillRecord(**values)  # type: ignore[arg-type]


def test_versioned_ontology_declares_exact_corpus_vocabulary() -> None:
    assert CORPUS_ONTOLOGY.version == CORPUS_ONTOLOGY_VERSION
    assert set(CORPUS_ONTOLOGY.node_types) == {
        "dataset_revision",
        "bundle",
        "source_document",
        "repository",
        "skill",
        "section",
        "source_span",
        "license",
        "domain",
        "author_publisher",
        "tool_mention",
        "entity_mention",
    }
    assert set(CORPUS_ONTOLOGY.edge_types) == {
        "CONTAINS",
        "DERIVED_FROM",
        "SAME_PRIMARY_SOURCE",
        "DUPLICATE_OF",
        "MENTIONS",
        "HAS_LICENSE",
        "HAS_DOMAIN",
        "CITES",
        "NEIGHBOR_OF",
    }
    CORPUS_ONTOLOGY.validate_edge(
        CorpusEdgeType.MENTIONS,
        CorpusNodeType.SECTION,
        CorpusNodeType.TOOL_MENTION,
    )
    with pytest.raises(CorpusGraphValidationError, match="does not permit"):
        CORPUS_ONTOLOGY.validate_edge(
            CorpusEdgeType.HAS_LICENSE,
            CorpusNodeType.LICENSE,
            CorpusNodeType.SKILL,
        )


def test_projector_builds_complete_digest_bound_evidence_graph() -> None:
    store = RecordingStore()
    graph = CorpusProjector(store).project(
        _record(),
        embedding=(0.25, -0.5, 1.0),
        embedding_model="fixture-embedding/v1",
        mentions=(
            CorpusMention(
                "artifact",
                kind=CorpusNodeType.ENTITY_MENTION,
                section_title="Verify",
            ),
        ),
        citations=(CorpusCitation("https://docs.example.test/guide"),),
    )

    assert graph.schema_version == CORPUS_GRAPH_SCHEMA_VERSION
    assert graph.ontology_version == CORPUS_ONTOLOGY_VERSION
    assert graph.graph_digest.startswith("sha256:")
    assert graph.graph_cid in store.blocks
    assert graph.graph_cid == cid_v1(graph.canonical_bytes())
    assert {node.node_type for node in graph.nodes} == set(CorpusNodeType)
    assert {
        CorpusEdgeType.CONTAINS,
        CorpusEdgeType.DERIVED_FROM,
        CorpusEdgeType.MENTIONS,
        CorpusEdgeType.HAS_LICENSE,
        CorpusEdgeType.HAS_DOMAIN,
        CorpusEdgeType.CITES,
    } <= {edge.edge_type for edge in graph.edges}

    for node in graph.nodes:
        assert node.graph_digest == graph.graph_digest
        assert node.source_digest in graph.source_digests
        assert "skill_md" not in node.properties
        assert "embedding" not in node.properties
    for edge in graph.edges:
        assert edge.graph_digest == graph.graph_digest
        assert edge.source_digest in graph.source_digests

    assert len(graph.source_bodies) == 1
    assert len(graph.embeddings) == 1
    body_ref = graph.source_bodies[0]
    embedding_ref = graph.embeddings[0]
    assert body_ref.stored is True
    assert body_ref.cid in store.blocks
    assert embedding_ref.cid in store.blocks
    assert len({body_ref.cid, embedding_ref.cid, graph.graph_cid}) == 3
    assert store.blocks[body_ref.cid][0] == _record().skill_md.encode("utf-8")
    assert b"fixture-embedding/v1" in store.blocks[embedding_ref.cid][0]
    assert _record().skill_md.encode("utf-8") not in store.blocks[graph.graph_cid][0]


def test_deterministic_batch_projects_duplicate_and_source_family_edges() -> None:
    first = _record()
    second = replace(
        first,
        skill_id="skill-2",
        source_id="source-2",
        title="Same body, another record",
    )
    first_evidence = CorpusEvidenceRecord(
        first,
        neighbor_skill_ids=("skill-2",),
    )
    second_evidence = CorpusEvidenceRecord(second)

    graph_a = CorpusProjector(RecordingStore()).project(
        (first_evidence, second_evidence)
    )
    graph_b = CorpusProjector(RecordingStore()).project(
        (second_evidence, first_evidence)
    )

    assert graph_a == graph_b
    edge_types = [edge.edge_type for edge in graph_a.edges]
    assert edge_types.count(CorpusEdgeType.DUPLICATE_OF) == 1
    assert edge_types.count(CorpusEdgeType.SAME_PRIMARY_SOURCE) == 1
    assert edge_types.count(CorpusEdgeType.NEIGHBOR_OF) == 1
    duplicate = next(
        edge
        for edge in graph_a.edges
        if edge.edge_type is CorpusEdgeType.DUPLICATE_OF
    )
    assert duplicate.properties["content_digest"] == (
        "sha256:" + first.content_sha256
    )


def test_policy_limited_record_is_indexed_without_copying_its_body() -> None:
    record = _record(metadata_yaml="title: no license declaration\n")
    decision = SkillSourcePolicy().evaluate(record)
    assert decision.allowed_use is AllowedUseDecision.QUARANTINED_UNKNOWN
    store = RecordingStore()

    graph = CorpusProjector(store).project(
        record,
        policy_decision=decision,
    )

    assert graph.source_bodies[0].stored is False
    assert graph.source_bodies[0].cid not in store.blocks
    assert len(store.blocks) == 1  # graph block only
    skill = next(
        node for node in graph.nodes if node.node_type is CorpusNodeType.SKILL
    )
    assert skill.properties["allowed_use"] == "quarantined_unknown"
    assert skill.properties["body_stored"] is False

    with pytest.raises(CorpusProjectionError, match="does not permit embeddings"):
        CorpusProjector(RecordingStore()).project(
            record,
            policy_decision=decision,
            embedding=(1.0,),
            embedding_model="fixture/v1",
        )


def test_identical_body_with_conflicting_use_decisions_fails_closed() -> None:
    allowed = _record()
    restricted = replace(
        allowed,
        skill_id="skill-2",
        source_id="source-2",
        primary_source_id="primary-2",
        metadata_yaml="title: no license declaration\n",
    )
    store = RecordingStore()

    graph = CorpusProjector(store).project((allowed, restricted))

    assert len(graph.source_bodies) == 1
    assert graph.source_bodies[0].stored is False
    assert graph.source_bodies[0].cid not in store.blocks
    assert all(
        node.properties["body_stored"] is False
        for node in graph.nodes
        if node.node_type is CorpusNodeType.SKILL
    )


def test_graph_records_reject_inline_payloads_and_bad_digest_bindings() -> None:
    digest = "sha256:" + ("1" * 64)
    with pytest.raises(CorpusGraphValidationError, match="separately"):
        CorpusGraphNode(
            node_id="corpus:node:skill:test",
            node_type=CorpusNodeType.SKILL,
            source_digest=digest,
            graph_digest=digest,
            properties={"source_text": "must remain separately addressed"},
        )
    with pytest.raises(CorpusGraphValidationError, match="separately"):
        CorpusGraphNode(
            node_id="corpus:node:skill:nested",
            node_type=CorpusNodeType.SKILL,
            source_digest=digest,
            graph_digest=digest,
            properties={"nested": {"embedding_vector": [0.1, 0.2]}},
        )
    with pytest.raises(CorpusGraphValidationError, match="sha256"):
        CorpusGraphEdge(
            edge_id="corpus:edge:CONTAINS:test",
            edge_type=CorpusEdgeType.CONTAINS,
            source="corpus:node:dataset:test",
            target="corpus:node:bundle:test",
            source_digest="not-a-digest",
            graph_digest=digest,
        )
    with pytest.raises(CorpusGraphValidationError, match="does not match"):
        AddressedArtifact(
            cid=cid_v1(b"different bytes"),
            digest=digest,
            media_type="application/octet-stream",
            size_bytes=1,
        )


def test_graph_artifact_rejects_tampered_addresses() -> None:
    graph = CorpusProjector(RecordingStore()).project(_record())

    with pytest.raises(CorpusGraphValidationError, match="graph_cid"):
        replace(graph, graph_cid=cid_v1(b"another graph"))

    body = graph.source_bodies[0]
    undeclared_body = AddressedArtifact.from_bytes(
        b"not a declared source",
        media_type="text/plain",
    )
    with pytest.raises(CorpusGraphValidationError, match="not declared"):
        replace(
            graph,
            graph_cid="",
            source_bodies=tuple(sorted((body, undeclared_body), key=lambda item: item.digest)),
        )


def test_current_ipld_adapter_wraps_store_without_legacy_graph_module() -> None:
    class RawStore:
        def __init__(self) -> None:
            self.calls: list[tuple[bytes, bool | None, str]] = []

        def store(
            self,
            payload: bytes,
            pin: bool | None = None,
            codec: str = "dag-json",
        ) -> str:
            self.calls.append((payload, pin, codec))
            return cid_v1(payload)

    raw_store = RawStore()
    adapter = IPLDArtifactStore(raw_store)
    payload = b"current IPLD adapter"

    assert adapter.put_bytes(payload, media_type="application/octet-stream") == (
        cid_v1(payload)
    )
    assert raw_store.calls == [(payload, True, "raw")]
    module_source = inspect.getsource(corpus_projector)
    assert "from ipfs_datasets_py.knowledge_graphs.ipld" not in module_source
    assert "from ipfs_datasets_py.processors.storage.ipld" not in module_source


def test_projector_rejects_mismatched_policy_and_dangling_neighbor() -> None:
    record = _record()
    other_decision = SkillSourcePolicy().evaluate(
        replace(record, skill_id="other")
    )
    with pytest.raises(CorpusProjectionError, match="does not match"):
        CorpusEvidenceRecord(record, policy_decision=other_decision)
    store = RecordingStore()
    with pytest.raises(CorpusProjectionError, match="not in this graph"):
        CorpusProjector(store).project(
            record,
            neighbor_skill_ids=("missing",),
        )
    assert store.calls == []

    stale_decision = SkillSourcePolicy().evaluate(record)
    changed_record = replace(
        record,
        metadata_yaml="license_spdx: GPL-3.0-only\n",
    )
    with pytest.raises(CorpusProjectionError, match="does not match evaluation"):
        CorpusProjector(RecordingStore()).project(
            changed_record,
            policy_decision=stale_decision,
        )


def test_evidence_record_freezes_observation_sequences() -> None:
    mentions = [CorpusMention("tool", kind=CorpusNodeType.TOOL_MENTION)]
    citations = [CorpusCitation("https://example.test")]

    evidence = CorpusEvidenceRecord(
        _record(),
        mentions=mentions,  # type: ignore[arg-type]
        citations=citations,  # type: ignore[arg-type]
    )
    mentions.clear()
    citations.clear()

    assert len(evidence.mentions) == 1
    assert len(evidence.citations) == 1
