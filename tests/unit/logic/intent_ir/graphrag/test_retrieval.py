from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.intent_ir.graphrag.corpus_projector import (
    CorpusEvidenceRecord,
    CorpusProjector,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.ontology import (
    CorpusEdgeType,
    CorpusNodeType,
)
from ipfs_datasets_py.logic.intent_ir.graphrag.retrieval import (
    GraphSnapshot,
    IntentGraphRetriever,
    MAX_K,
    NeighborCandidate,
    PartitionAssignment,
    RETRIEVAL_AUTHORITY,
    RetrievalFilters,
    RetrievalRequest,
    RetrievalStatus,
    RetrievalValidationError,
)
from ipfs_datasets_py.logic.intent_ir.source_adapters.skillcenter import (
    SkillCenterSkillRecord,
)
from ipfs_datasets_py.logic.ir_core.identity import cid_v1


class RecordingStore:
    def put_bytes(self, payload: bytes, *, media_type: str) -> str:
        return cid_v1(payload)


def _record(skill_id: str) -> SkillCenterSkillRecord:
    return SkillCenterSkillRecord(
        skill_id=skill_id,
        domain="testing",
        profile="testing",
        source_type="github",
        source_url=f"https://example.test/{skill_id}/SKILL.md",
        title=f"Fixture {skill_id}",
        overall_score=4.0,
        skill_kind="github",
        language="en",
        source_id=f"source-{skill_id}",
        primary_source_id=f"primary-{skill_id}",
        metadata_yaml='license_spdx: "MIT"\n',
        skill_md=f"# {skill_id}\n\nUnique content for {skill_id}.\n",
        library_md="",
        dataset_id="example/retrieval",
        dataset_revision="revision-1",
        repository_file="retrieval.sqlite",
        bundle_sha256="a" * 64,
    )


@pytest.fixture
def retrieval_fixture():
    skill_ids = (
        "query",
        "alpha",
        "beta",
        "same-family",
        "training",
        "poison",
    )
    graph = CorpusProjector(RecordingStore()).project(
        (
            CorpusEvidenceRecord(
                _record("query"),
                neighbor_skill_ids=skill_ids[1:],
            ),
            *(_record(skill_id) for skill_id in skill_ids[1:]),
        )
    )
    skill_nodes = {
        node.properties["skill_id"]: node
        for node in graph.nodes
        if node.node_type is CorpusNodeType.SKILL
    }
    query_id = skill_nodes["query"].node_id
    neighbor_edges = {}
    for edge in graph.edges:
        if edge.edge_type is not CorpusEdgeType.NEIGHBOR_OF:
            continue
        other = edge.target if edge.source == query_id else edge.source
        neighbor_edges[other] = edge

    assignments = {
        skill_nodes["query"].node_id: PartitionAssignment(
            "evaluation", "family-query"
        ),
        skill_nodes["alpha"].node_id: PartitionAssignment(
            "evaluation", "family-alpha"
        ),
        skill_nodes["beta"].node_id: PartitionAssignment(
            "evaluation", "family-beta"
        ),
        skill_nodes["same-family"].node_id: PartitionAssignment(
            "evaluation", "family-query"
        ),
        skill_nodes["training"].node_id: PartitionAssignment(
            "training", "family-training"
        ),
        skill_nodes["poison"].node_id: PartitionAssignment(
            "evaluation", "family-poison", adversarial=True
        ),
    }

    def candidate(skill_id: str, score: float) -> NeighborCandidate:
        node = skill_nodes[skill_id]
        return NeighborCandidate(
            node_id=node.node_id,
            edge_id=neighbor_edges[node.node_id].edge_id,
            score=score,
            graph_digest=graph.graph_digest,
        )

    request = RetrievalRequest(
        query_node_id=query_id,
        snapshot=GraphSnapshot.from_graph(graph),
        partition="evaluation",
        source_family="family-query",
        k=2,
        max_bytes=32_000,
        timeout_ms=1_000,
        candidates=(
            candidate("alpha", 0.75),
            candidate("beta", 0.75),
        ),
    )
    return graph, skill_nodes, assignments, candidate, request


def test_fixed_k_and_deterministic_tie_breaking(retrieval_fixture) -> None:
    graph, _nodes, assignments, candidate, request = retrieval_fixture
    candidates = (
        candidate("beta", 0.75),
        candidate("alpha", 0.75),
        candidate("training", 0.99),
    )
    retriever = IntentGraphRetriever(graph, assignments)

    first = retriever.retrieve(replace(request, k=1, candidates=candidates))
    second = retriever.retrieve(
        replace(request, k=1, candidates=tuple(reversed(candidates)))
    )

    expected = min(candidate("alpha", 0).node_id, candidate("beta", 0).node_id)
    assert first.status is RetrievalStatus.OK
    assert first == second
    assert len(first.premises) == 1
    assert first.premises[0].node_id == expected
    assert first.requested_k == 1


def test_partition_source_family_and_adversarial_neighbors_are_isolated(
    retrieval_fixture,
) -> None:
    graph, _nodes, assignments, candidate, request = retrieval_fixture
    retriever = IntentGraphRetriever(graph, assignments)

    result = retriever.retrieve(
        replace(
            request,
            k=5,
            candidates=(
                candidate("same-family", 1.0),
                candidate("training", 0.99),
                candidate("poison", 0.98),
                candidate("alpha", 0.5),
            ),
        )
    )

    assert [item.node_id for item in result.premises] == [
        candidate("alpha", 0).node_id
    ]
    assert all(item.partition == "evaluation" for item in result.premises)
    assert all(item.source_family != "family-query" for item in result.premises)

    adversarial_query = replace(
        request,
        query_node_id=candidate("poison", 0).node_id,
        source_family="family-poison",
        adversarial=True,
        candidates=(),
    )
    # The poisoned node cannot use a normal query's scope, even when its node
    # identifier and graph snapshot are otherwise valid.
    mismatch = retriever.retrieve(replace(adversarial_query, adversarial=False))
    assert mismatch.status is RetrievalStatus.UNSUPPORTED
    assert mismatch.reason_codes == ("query_isolation_binding_mismatch",)


def test_filters_are_applied_before_ranking(retrieval_fixture) -> None:
    graph, nodes, assignments, candidate, request = retrieval_fixture
    retriever = IntentGraphRetriever(graph, assignments)
    alpha = nodes["alpha"]

    result = retriever.retrieve(
        replace(
            request,
            k=3,
            filters=RetrievalFilters(
                node_types=("skill",),
                edge_types=("NEIGHBOR_OF",),
                excluded_source_digests=(alpha.source_digest,),
                excluded_source_families=("family-beta",),
            ),
        )
    )
    assert result.status is RetrievalStatus.EMPTY
    assert result.premises == ()
    assert set(result.reason_codes) == {
        "source_digest_excluded",
        "source_family_excluded",
    }

    unsupported = retriever.retrieve(
        replace(
            request,
            filters=RetrievalFilters(node_types=("future_node_type",)),
        )
    )
    assert unsupported.status is RetrievalStatus.UNSUPPORTED
    assert unsupported.reason_codes == ("unsupported_node_filter",)


def test_graph_snapshot_and_candidate_bindings_fail_closed(
    retrieval_fixture,
) -> None:
    graph, _nodes, assignments, candidate, request = retrieval_fixture
    retriever = IntentGraphRetriever(graph, assignments)

    wrong_snapshot = replace(request.snapshot, graph_cid="bafk-wrong")
    result = retriever.retrieve(replace(request, snapshot=wrong_snapshot))
    assert result.status is RetrievalStatus.UNSUPPORTED
    assert result.reason_codes == ("graph_snapshot_mismatch",)
    assert result.premises == ()

    wrong_candidate = replace(
        candidate("alpha", 1.0),
        graph_digest="sha256:" + ("f" * 64),
    )
    empty = retriever.retrieve(replace(request, candidates=(wrong_candidate,)))
    assert empty.status is RetrievalStatus.EMPTY
    assert empty.reason_codes == ("candidate_snapshot_mismatch",)


def test_byte_budget_is_hard_and_reports_empty_or_partial(
    retrieval_fixture,
) -> None:
    graph, _nodes, assignments, _candidate, request = retrieval_fixture
    retriever = IntentGraphRetriever(graph, assignments)
    complete = retriever.retrieve(request)
    first_size = len(complete.premises[0].canonical_bytes())

    none = retriever.retrieve(replace(request, max_bytes=first_size - 1))
    assert none.status is RetrievalStatus.BUDGET_EXHAUSTED
    assert none.bytes_used == 0
    assert none.reason_codes == ("byte_budget_exhausted",)

    partial = retriever.retrieve(replace(request, max_bytes=first_size))
    assert partial.status is RetrievalStatus.PARTIAL
    assert len(partial.premises) == 1
    assert partial.bytes_used == first_size
    assert partial.bytes_used <= partial.max_bytes


def test_time_budget_is_checked_before_candidate_admission(
    retrieval_fixture,
) -> None:
    graph, _nodes, assignments, _candidate, request = retrieval_fixture
    readings = iter((0.0, 0.0, 0.002))
    retriever = IntentGraphRetriever(
        graph,
        assignments,
        monotonic=lambda: next(readings),
    )

    result = retriever.retrieve(replace(request, timeout_ms=1))
    assert result.status is RetrievalStatus.BUDGET_EXHAUSTED
    assert result.premises == ()
    assert result.examined_candidates == 1
    assert result.reason_codes == ("time_budget_exhausted",)

    scan_readings = iter((0.0, 0.002))
    scan_retriever = IntentGraphRetriever(
        graph,
        assignments,
        monotonic=lambda: next(scan_readings),
    )
    scan_result = scan_retriever.retrieve(
        replace(request, candidates=(), timeout_ms=1)
    )
    assert scan_result.status is RetrievalStatus.BUDGET_EXHAUSTED
    assert scan_result.reason_codes == ("time_budget_exhausted",)


def test_premises_preserve_provenance_and_never_have_proof_authority(
    retrieval_fixture,
) -> None:
    graph, _nodes, assignments, _candidate, request = retrieval_fixture
    result = IntentGraphRetriever(graph, assignments).retrieve(request)

    assert result.status is RetrievalStatus.OK
    assert result.authority == RETRIEVAL_AUTHORITY == "context_only"
    assert result.snapshot == request.snapshot
    for premise in result.premises:
        assert premise.proof_authority is False
        assert premise.authority == "context_only"
        assert premise.graph_digest == graph.graph_digest
        assert premise.graph_cid == graph.graph_cid
        assert premise.edge_id
        assert premise.source_digest.startswith("sha256:")
        assert premise.source_ids


def test_invalid_bounds_and_unassigned_query_are_explicit(
    retrieval_fixture,
) -> None:
    graph, _nodes, assignments, _candidate, request = retrieval_fixture
    with pytest.raises(RetrievalValidationError, match="k"):
        replace(request, k=0)
    with pytest.raises(RetrievalValidationError, match="k"):
        replace(request, k=MAX_K + 1)
    with pytest.raises(RetrievalValidationError, match="max_bytes"):
        replace(request, max_bytes=0)
    with pytest.raises(RetrievalValidationError, match="timeout_ms"):
        replace(request, timeout_ms=0)

    without_query = {
        key: value
        for key, value in assignments.items()
        if key != request.query_node_id
    }
    result = IntentGraphRetriever(graph, without_query).retrieve(request)
    assert result.status is RetrievalStatus.UNSUPPORTED
    assert result.reason_codes == ("query_partition_unassigned",)
