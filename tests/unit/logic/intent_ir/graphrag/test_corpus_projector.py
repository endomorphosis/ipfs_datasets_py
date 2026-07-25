from __future__ import annotations

import hashlib
import json

import pytest

from ipfs_datasets_py.logic.intent_ir.graphrag.corpus_projector import (
    CorpusGraphProjector,
    CorpusMention,
    CorpusNeighbor,
    CorpusProjectionInput,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.ontology import (
    CORPUS_GRAPH_ONTOLOGY,
    CORPUS_GRAPH_SCHEMA_VERSION,
    INTENT_GRAPH_ONTOLOGY_VERSION,
    CorpusEdgeKind,
    CorpusGraphValidationError,
    CorpusNodeKind,
    IntentCorpusGraph,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (
    SkillCenterSkillRecord,
)
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.identity import cid_v1


def _record(
    skill_id: str,
    *,
    body: str,
    primary_source_id: str,
    bundle: str = "a" * 64,
    source_url: str = "https://github.com/acme/example/blob/main/SKILL.md",
) -> SkillCenterSkillRecord:
    return SkillCenterSkillRecord(
        skill_id=skill_id,
        domain="security",
        profile="lite",
        source_type="github",
        source_url=source_url,
        title=f"Skill {skill_id}",
        overall_score=0.8,
        skill_kind="procedure",
        language="en",
        source_id=f"source-{skill_id}",
        primary_source_id=primary_source_id,
        metadata_yaml="license: MIT\npublisher: Acme",
        skill_md=body,
        library_md="Library notes",
        dataset_id="owner/skills",
        dataset_revision="0123456789abcdef",
        repository_file="bundle.sqlite",
        bundle_sha256=bundle,
    )


class _MemoryIPLDBackend:
    def __init__(self) -> None:
        self.raw_blocks: dict[str, bytes] = {}
        self.graphs: dict[str, dict] = {}

    def store(self, data, pin=None, codec="dag-json"):
        assert pin is True
        payload = data.encode() if isinstance(data, str) else data
        if not isinstance(payload, bytes):
            payload = canonical_json_bytes(payload)
        address = cid_v1(payload)
        assert codec == "raw"
        self.raw_blocks[address] = payload
        return address

    def store_graph(self, nodes, relationships, metadata=None):
        payload = {
            "metadata": metadata or {},
            "nodes": nodes,
            "relationships": relationships,
        }
        address = cid_v1(canonical_json_bytes(payload))
        self.graphs[address] = payload
        return address


def test_ontology_versions_complete_corpus_vocabulary() -> None:
    assert CORPUS_GRAPH_ONTOLOGY.version == INTENT_GRAPH_ONTOLOGY_VERSION
    assert set(CORPUS_GRAPH_ONTOLOGY.node_kinds) == {
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
    assert set(CORPUS_GRAPH_ONTOLOGY.edge_kinds) == {
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
    assert CORPUS_GRAPH_ONTOLOGY.permits(
        CorpusEdgeKind.CONTAINS,
        CorpusNodeKind.DATASET_REVISION,
        CorpusNodeKind.BUNDLE,
    )
    assert not CORPUS_GRAPH_ONTOLOGY.permits(
        CorpusEdgeKind.CONTAINS,
        CorpusNodeKind.LICENSE,
        CorpusNodeKind.SKILL,
    )


def test_projection_is_deterministic_and_every_element_is_digest_bound() -> None:
    first = _record(
        "first",
        body="# Install\nRun the installer.",
        primary_source_id="family-a",
    )
    second = _record(
        "second",
        body="# Verify\nCheck the result.",
        primary_source_id="family-a",
    )
    projector = CorpusGraphProjector()

    graph = projector.project([first, second])
    reversed_graph = projector.project([second, first])

    assert graph.schema_version == CORPUS_GRAPH_SCHEMA_VERSION
    assert graph.ontology_version == INTENT_GRAPH_ONTOLOGY_VERSION
    assert graph.canonical_bytes() == reversed_graph.canonical_bytes()
    assert graph.validate() is graph
    assert all(node.graph_digest == graph.graph_digest for node in graph.nodes)
    assert all(node.source_digest.startswith("sha256:") for node in graph.nodes)
    assert all(edge.graph_digest == graph.graph_digest for edge in graph.edges)
    assert all(edge.source_digest.startswith("sha256:") for edge in graph.edges)
    assert any(
        edge.kind is CorpusEdgeKind.SAME_PRIMARY_SOURCE for edge in graph.edges
    )
    assert IntentCorpusGraph.from_dict(json.loads(graph.canonical_bytes())) == graph


def test_source_bodies_and_embeddings_are_stored_outside_graph() -> None:
    body = "# Deploy\nNever inline this unique source sentence."
    record = _record("deploy", body=body, primary_source_id="deploy-source")
    backend = _MemoryIPLDBackend()
    embedding = b"\x00\x01separately-addressed-vector"

    receipt = CorpusGraphProjector().project_and_store(
        [record],
        storage=backend,
        embeddings={"deploy": embedding},
    )

    assert receipt.graph_cid in backend.graphs
    assert embedding in backend.raw_blocks.values()
    assert body.encode() in backend.raw_blocks.values()
    assert record.metadata_yaml.encode() in backend.raw_blocks.values()
    assert record.library_md.encode() in backend.raw_blocks.values()
    graph_payload = canonical_json_bytes(backend.graphs[receipt.graph_cid])
    assert body.encode() not in graph_payload
    assert embedding not in graph_payload
    assert b"skill_md" not in graph_payload
    assert b"metadata_yaml" not in graph_payload


def test_duplicate_family_similarity_and_mentions_remain_distinct() -> None:
    shared_body = "# Use tool\nCall `scanner` now."
    first = _record("one", body=shared_body, primary_source_id="same-family")
    second = _record("two", body=shared_body, primary_source_id="same-family")
    start = len("# Use tool\nCall `".encode())
    graph = CorpusGraphProjector().project(
        [
            CorpusProjectionInput(
                record=first,
                mentions=(
                    CorpusMention(
                        value="scanner",
                        kind=CorpusNodeKind.TOOL_MENTION,
                        start_byte=start,
                        end_byte=start + len("scanner"),
                    ),
                ),
            ),
            second,
        ],
        neighbors=(
            CorpusNeighbor(
                source_skill_id="one",
                target_skill_id="two",
                score=0.99,
                embedding_cid="bafy-neighbor-index",
                embedding_digest="sha256:" + "b" * 64,
            ),
        ),
    )

    kinds = {edge.kind for edge in graph.edges}
    assert {
        CorpusEdgeKind.DUPLICATE_OF,
        CorpusEdgeKind.SAME_PRIMARY_SOURCE,
        CorpusEdgeKind.MENTIONS,
        CorpusEdgeKind.NEIGHBOR_OF,
    } <= kinds
    neighbor = next(
        edge for edge in graph.edges if edge.kind is CorpusEdgeKind.NEIGHBOR_OF
    )
    assert neighbor.relation_class == "similarity"
    assert neighbor.properties["semantic_assertion"] is False
    assert neighbor.embedding_cid == "bafy-neighbor-index"


def test_markdown_citation_is_grounded_without_copying_cited_text() -> None:
    body = "# Reference\nRead [the guide](https://example.org/guide?q=1)."
    graph = CorpusGraphProjector().project(
        [_record("cites", body=body, primary_source_id="citation-family")]
    )

    citation = next(edge for edge in graph.edges if edge.kind is CorpusEdgeKind.CITES)
    cited = next(node for node in graph.nodes if node.id == citation.target_node_id)
    assert cited.kind is CorpusNodeKind.SOURCE_DOCUMENT
    assert cited.properties["source_uri"] == "https://example.org/guide?q=1"
    assert cited.source_body_cid == ""


def test_projection_rejects_invalid_digest_and_ungrounded_spans() -> None:
    record = _record("bad", body="# Valid\nBody", primary_source_id="bad-family")
    object.__setattr__(record, "bundle_sha256", "not-a-digest")
    with pytest.raises(CorpusGraphValidationError, match="bundle_sha256"):
        CorpusGraphProjector().project([record])

    good = _record("span", body="# Valid\nBody", primary_source_id="span-family")
    with pytest.raises(CorpusGraphValidationError, match="exceeds"):
        CorpusGraphProjector().project(
            [
                CorpusProjectionInput(
                    record=good,
                    mentions=(
                        CorpusMention(
                            value="tool",
                            kind=CorpusNodeKind.TOOL_MENTION,
                            start_byte=100,
                            end_byte=104,
                        ),
                    ),
                )
            ]
        )
    with pytest.raises(CorpusGraphValidationError, match="exactly match"):
        CorpusGraphProjector().project(
            [
                CorpusProjectionInput(
                    record=good,
                    mentions=(
                        CorpusMention(
                            value="wrong",
                            kind=CorpusNodeKind.ENTITY_MENTION,
                            start_byte=2,
                            end_byte=7,
                        ),
                    ),
                )
            ]
        )


def test_graph_digest_detects_tampering() -> None:
    graph = CorpusGraphProjector().project(
        [_record("stable", body="# Stable\nContent", primary_source_id="stable")]
    )
    payload = graph.to_dict()
    payload["nodes"][0]["properties"]["revision"] = "tampered"
    with pytest.raises(CorpusGraphValidationError, match="graph_digest"):
        IntentCorpusGraph.from_dict(payload)

    payload = graph.to_dict()
    payload["nodes"][0]["source_digest"] = "sha256:" + "0" * 64
    with pytest.raises(CorpusGraphValidationError, match="source_digest"):
        IntentCorpusGraph.from_dict(payload)


def test_projection_digest_changes_with_source_address() -> None:
    record = _record(
        "addressed",
        body="# Addressed\nContent",
        primary_source_id="address-family",
    )
    first = CorpusGraphProjector().project(
        [record], source_body_cids={"addressed": "bafy-source-one"}
    )
    second = CorpusGraphProjector().project(
        [record], source_body_cids={"addressed": "bafy-source-two"}
    )

    assert first.graph_digest != second.graph_digest
    assert hashlib.sha256(first.canonical_bytes()).digest() != hashlib.sha256(
        second.canonical_bytes()
    ).digest()
