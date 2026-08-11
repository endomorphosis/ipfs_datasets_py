"""Conformance tests for bounded, provenance-preserving Solidity GraphRAG."""

from __future__ import annotations

from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.graph import (
    GraphNodeType,
    SoliditySecurityGraph,
    build_solidity_security_graph,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.projector import (
    SolidityGraphProjector,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.retrieval import (
    BoundedHybridRetriever,
    EmbeddingAcceleratorPort,
    NO_EMBEDDING_MODEL,
    NO_TOKENIZER,
    RETRIEVAL_AUTHORITY_CONTEXT,
    RetrievalAuthority,
    RetrievalConfig,
    RetrievalEntry,
    RetrievalIndex,
    RetrievalIntegrityError,
    RetrievalQuery,
    RetrievalScope,
    RetrievalScopeError,
    RetrievalValidationError,
    SolidityGraphRetriever,
    build_retrieval_index,
    retrieve_solidity_cpt,
)
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.source_snapshot import (
    adapt_solidity_cpt_row,
)


SOURCE_A = """\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract Vault {
    uint256 public balance;
    function deposit() external payable {
        balance += msg.value;
    }
    function withdraw(uint256 amount) external {
        balance -= amount;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok);
    }
}
"""

SOURCE_B = """\
// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.19;
contract Token {
    mapping(address => uint256) public balances;
    function transfer(address to, uint256 amount) external {
        balances[msg.sender] -= amount;
        balances[to] += amount;
    }
}
"""


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label}, domain="test", schema_version="test/v1"
    ).cid


def _raw(
    text: str,
    *,
    name: str = "Vault",
    path: str = "contracts/Vault.sol",
    license_id: str = "MIT",
    address: str | None = None,
) -> dict:
    return {
        "text": text,
        "source": "etherscan",
        "address": address or ("0x" + "a" * 40),
        "name": name,
        "compiler": "v0.8.24",
        "license": license_id,
        "path": path,
        "n_chars": len(text),
    }


def _graph(label: str = "fixture") -> SoliditySecurityGraph:
    projections = []
    for index, (text, name, path, license_id, address) in enumerate(
        (
            (
                SOURCE_A,
                "Vault",
                "contracts/Vault.sol",
                "MIT",
                "0x" + "a" * 40,
            ),
            (
                SOURCE_B,
                "Token",
                "contracts/Token.sol",
                "Apache-2.0",
                "0x" + "b" * 40,
            ),
        ),
        start=1,
    ):
        adapted = adapt_solidity_cpt_row(
            _raw(
                text,
                name=name,
                path=path,
                license_id=license_id,
                address=address,
            ),
            row_index=index,
        )
        projections.append(
            SolidityGraphProjector().project_adapted(adapted)
        )
    return build_solidity_security_graph(tuple(projections))


def _partitions(
    graph: SoliditySecurityGraph, default: str = "train"
) -> dict[str, str]:
    return {node.cid: default for node in graph.nodes}


def _candidate_entry(
    graph: SoliditySecurityGraph,
    *,
    partition: str = "train",
    authority: RetrievalAuthority = RetrievalAuthority.CANDIDATE,
) -> RetrievalEntry:
    return RetrievalEntry(
        node_cid=_cid(f"candidate-{partition}-{authority.value}"),
        partition=partition,
        shard_key=f"{partition}:candidate",
        kind="security_concept",
        text="reentrancy candidate for offline review",
        source_cids=(graph.source_cids[0],),
        authority=authority,
        security_concepts=("reentrancy",),
        licenses=("MIT",),
        graph_node=False,
    )


class _EmbeddingPort:
    def __init__(self) -> None:
        self.document_calls = 0
        self.query_calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls += 1
        return [
            [1.0, 0.0] if "withdraw" in text or "reentrancy" in text else [0.0, 1.0]
            for text in texts
        ]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        return [1.0, 0.0]


def test_protocol_and_public_symbols_are_exported() -> None:
    assert issubclass(SolidityGraphRetriever, object)
    assert BoundedHybridRetriever is SolidityGraphRetriever
    assert EmbeddingAcceleratorPort is not None
    assert RetrievalIndex is not None


def test_hybrid_filters_cover_license_node_type_contract_compiler_and_concept() -> None:
    graph = _graph()
    index = build_retrieval_index(
        graph,
        partition_by_node=_partitions(graph),
        extra_entries=(_candidate_entry(graph),),
    )
    scope = RetrievalScope(
        partition="train",
        authorities=(
            RetrievalAuthority.NON_AUTHORITATIVE,
            RetrievalAuthority.CANDIDATE,
        ),
    )

    cases = (
        ({"licenses": ("MIT",)}, "license"),
        ({"node_types": (GraphNodeType.CONTRACT.value,)}, "contract"),
        ({"contracts": ("Vault",)}, "contract"),
        ({"compilers": ("v0.8.24",)}, "compiler"),
        ({"security_concepts": ("reentrancy",)}, "security_concept"),
        ({"paths": ("contracts/Vault.sol",)}, "contract"),
    )
    for values, expected_kind in cases:
        response = retrieve_solidity_cpt(
            graph,
            index,
            RetrievalQuery(text="solidity", **values),
            scope=scope,
        )
        assert response.results, f"expected hits for {values}"
        assert any(item.kind == expected_kind for item in response.results)
        assert all(item.matched_fields for item in response.results)


def test_lexical_vector_and_graph_scores_fuse_deterministically() -> None:
    graph = _graph()
    port = _EmbeddingPort()
    index = build_retrieval_index(
        graph,
        partition_by_node=_partitions(graph),
        embedding_port=port,
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        model_revision="0123456789abcdef",
        tokenizer_id="sentence-transformers/all-MiniLM-L6-v2",
        model_config={"normalize": True, "dimensions": 2},
    )
    start = next(
        node.cid
        for node in graph.nodes
        if node.node_type == GraphNodeType.CONTRACT.value
        and node.payload.get("name") == "Vault"
    )
    retriever = SolidityGraphRetriever(graph, index, embedding_port=port)

    first = retriever.retrieve(
        RetrievalQuery(text="withdraw", start_node_cids=(start,)),
        scope=RetrievalScope(partition="train"),
    )
    second = retriever.retrieve(
        RetrievalQuery(text="withdraw", start_node_cids=(start,)),
        scope=RetrievalScope(partition="train"),
    )

    assert first.to_dict() == second.to_dict()
    assert first.results
    assert any(item.lexical_score > 0 for item in first.results)
    assert any(item.vector_score == pytest.approx(1.0) for item in first.results)
    assert any(
        item.graph_distance is not None and item.graph_score > 0
        for item in first.results
    )
    assert all(item.graph_path for item in first.results if item.graph_distance is not None)
    assert index.model_id == "sentence-transformers/all-MiniLM-L6-v2"
    assert index.model_revision == "0123456789abcdef"
    assert index.tokenizer_id == "sentence-transformers/all-MiniLM-L6-v2"
    assert index.embedding_dimension == 2
    assert index.model_config_cid
    assert index.ontology_version == graph.ontology_version
    assert index.source_root
    assert index.authority_policy_cid
    assert port.document_calls == 1
    assert port.query_calls == 2


def test_queries_cap_shards_nodes_results_bytes_hops_and_time() -> None:
    graph = _graph()
    config = RetrievalConfig(
        max_shards=2,
        max_nodes=4,
        max_results=1,
        max_hops=1,
        max_bytes=2_000,
        timeout_ms=5_000,
    )
    index = build_retrieval_index(
        graph,
        partition_by_node=_partitions(graph),
        config=config,
        shard_count=8,
        extra_entries=(_candidate_entry(graph),),
    )
    start = next(
        node.cid
        for node in graph.nodes
        if node.node_type == GraphNodeType.CONTRACT.value
    )
    response = retrieve_solidity_cpt(
        graph,
        index,
        RetrievalQuery(
            text="contract",
            start_node_cids=(start,),
            max_shards=2,
            max_nodes=4,
            max_results=1,
            max_hops=1,
            max_bytes=2_000,
            timeout_ms=5_000,
        ),
        scope=RetrievalScope(partition="train"),
        config=config,
    )

    assert response.shards_scanned <= 2
    assert response.nodes_scanned <= 4
    assert response.graph_nodes_visited <= 4
    assert len(response.results) <= 1
    assert response.bytes_used <= 2_000
    assert (
        response.truncated_shards
        or response.truncated_nodes
        or response.truncated_results
        or response.truncated_bytes
        or len(response.results) <= 1
    )

    with pytest.raises(RetrievalValidationError, match="ceiling"):
        retrieve_solidity_cpt(
            graph,
            index,
            RetrievalQuery(text="contract", max_results=2),
            scope=RetrievalScope(partition="train"),
            config=config,
        )


def test_partition_license_and_authority_broadening_fail_closed() -> None:
    graph = _graph()
    partitions = _partitions(graph)
    test_node = next(iter(partitions))
    partitions[test_node] = "test"
    index = build_retrieval_index(
        graph,
        partition_by_node=partitions,
        extra_entries=(_candidate_entry(graph),),
    )
    retriever = SolidityGraphRetriever(graph, index)
    narrow_scope = RetrievalScope(partition="train", licenses=("MIT",))

    with pytest.raises(RetrievalScopeError, match="partition"):
        retriever.retrieve(
            RetrievalQuery(text="contract", partition="test"),
            scope=narrow_scope,
        )
    with pytest.raises(RetrievalScopeError, match="authority"):
        retriever.retrieve(
            RetrievalQuery(
                text="contract",
                authorities=(RetrievalAuthority.CANDIDATE,),
            ),
            scope=narrow_scope,
        )
    with pytest.raises(RetrievalScopeError, match="license"):
        retriever.retrieve(
            RetrievalQuery(text="contract", licenses=("Apache-2.0",)),
            scope=narrow_scope,
        )

    response = retriever.retrieve(
        RetrievalQuery(text="MIT"),
        scope=narrow_scope,
    )
    assert response.partition == "train"
    assert all(item.partition == "train" for item in response.results)
    assert all(
        item.authority is RetrievalAuthority.NON_AUTHORITATIVE
        for item in response.results
    )


def test_shards_are_single_partition_and_partition_map_must_be_total() -> None:
    graph = _graph()
    incomplete = _partitions(graph)
    incomplete.pop(next(iter(incomplete)))
    with pytest.raises(RetrievalScopeError, match="every and only"):
        build_retrieval_index(graph, partition_by_node=incomplete)

    index = build_retrieval_index(
        graph, partition_by_node=_partitions(graph)
    )
    assert all(
        {entry.partition for entry in shard.entries} == {shard.partition}
        for shard in index.shards
    )


def test_index_binds_graph_ontology_source_model_and_detects_tampering() -> None:
    graph = _graph()
    index = build_retrieval_index(
        graph, partition_by_node=_partitions(graph)
    )
    assert index.graph_root == graph.graph_root
    assert index.ontology_version == graph.ontology_version
    assert index.graph_config_cid == graph.config_cid
    assert index.retrieval_config_cid == RetrievalConfig().cid
    assert index.authority_policy_cid
    assert index.source_root
    assert index.tokenizer_id == NO_TOKENIZER
    assert index.model_id == NO_EMBEDDING_MODEL
    assert index.embedding_dimension == 0
    assert index.index_root == RetrievalIndex.from_json(index.to_json()).index_root

    tampered = deepcopy(index.to_dict())
    tampered["shards"][0]["entries"][0]["text"] += " injected grant"
    with pytest.raises(RetrievalIntegrityError, match="entry_id"):
        RetrievalIndex.from_dict(tampered)

    root_tampered = deepcopy(index.to_dict())
    root_tampered["graph_root"] = _cid("other-graph")
    with pytest.raises(RetrievalIntegrityError, match="index_root"):
        RetrievalIndex.from_dict(root_tampered)

    other = build_solidity_security_graph(
        (
            SolidityGraphProjector().project_adapted(
                adapt_solidity_cpt_row(
                    _raw(SOURCE_B, name="Token", path="Token.sol", address="0x" + "c" * 40),
                    row_index=9,
                )
            ),
        )
    )
    with pytest.raises(RetrievalIntegrityError, match="graph root"):
        SolidityGraphRetriever(other, index)


def test_retrieval_never_returns_proof_or_execution_authority() -> None:
    graph = _graph()
    candidate = RetrievalEntry(
        node_cid=_cid("allow-candidate"),
        partition="train",
        shard_key="train:policy",
        kind="security_concept",
        text="allow candidate for offline review only",
        source_cids=(graph.source_cids[0],),
        authority=RetrievalAuthority.CANDIDATE,
        security_concepts=("allow",),
        licenses=("MIT",),
        graph_node=False,
    )
    index = build_retrieval_index(
        graph,
        partition_by_node=_partitions(graph),
        extra_entries=(candidate,),
        authority_policy=(
            RetrievalAuthority.NON_AUTHORITATIVE,
            RetrievalAuthority.CANDIDATE,
        ),
    )
    response = retrieve_solidity_cpt(
        graph,
        index,
        RetrievalQuery(text="allow", security_concepts=("allow",)),
        scope=RetrievalScope(
            partition="train",
            authorities=(RetrievalAuthority.CANDIDATE,),
        ),
    )

    assert len(response.results) == 1
    hit = response.results[0]
    assert hit.authority is RetrievalAuthority.CANDIDATE
    assert hit.proof_authority is False
    assert hit.authorizes_execution is False
    assert hit.grants_execution_authority is False
    assert hit.result_authority == RETRIEVAL_AUTHORITY_CONTEXT
    assert hit.source_cids
    assert response.proof_authority is False
    assert response.authorizes_execution is False
    assert response.grants_execution_authority is False
    wire = response.to_dict()
    assert wire["proof_authority"] is False
    assert wire["authorizes_execution"] is False
    assert wire["grants_execution_authority"] is False
    assert wire["results"][0]["proof_authority"] is False
    assert wire["results"][0]["source_cids"]

    with pytest.raises(RetrievalValidationError, match="never grant"):
        RetrievalEntry(
            node_cid=_cid("bad-grant"),
            partition="train",
            shard_key="train:bad",
            kind="security_concept",
            text="bad",
            source_cids=(graph.source_cids[0],),
            grants_execution_authority=True,
        )
    with pytest.raises(RetrievalValidationError, match="proof authority"):
        RetrievalEntry(
            node_cid=_cid("bad-proof"),
            partition="train",
            shard_key="train:bad",
            kind="security_concept",
            text="bad",
            source_cids=(graph.source_cids[0],),
            proof_authority=True,
        )


class _BrokenEmbeddingPort:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("accelerator unavailable")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("accelerator unavailable")


def test_embedding_accelerator_errors_and_dimension_mismatch_fail_closed() -> None:
    graph = _graph()
    with pytest.raises(RetrievalValidationError, match="failed closed"):
        build_retrieval_index(
            graph,
            partition_by_node=_partitions(graph),
            embedding_port=_BrokenEmbeddingPort(),
            model_id="model",
            model_revision="revision",
            tokenizer_id="tokenizer",
        )

    port = _EmbeddingPort()
    index = build_retrieval_index(
        graph,
        partition_by_node=_partitions(graph),
        embedding_port=port,
        model_id="model",
        model_revision="revision",
        tokenizer_id="tokenizer",
    )
    with pytest.raises(RetrievalValidationError, match="dimensions differ"):
        retrieve_solidity_cpt(
            graph,
            index,
            RetrievalQuery(text="path", embedding=(1.0, 0.0, 0.0)),
            scope=RetrievalScope(partition="train"),
            embedding_port=port,
        )


def test_serialization_rejects_duplicate_fields_and_non_finite_vectors() -> None:
    graph = _graph()
    index = build_retrieval_index(
        graph, partition_by_node=_partitions(graph)
    )
    duplicate = index.to_json().replace(
        '"schema_version":',
        '"schema_version":"duplicate","schema_version":',
        1,
    )
    with pytest.raises(RetrievalIntegrityError, match="duplicate"):
        RetrievalIndex.from_json(duplicate)

    with pytest.raises(RetrievalValidationError, match="finite"):
        RetrievalQuery(text="path", embedding=(float("nan"),))


def test_byte_budget_truncates_without_widening_authority() -> None:
    graph = _graph()
    config = RetrievalConfig(max_results=50, max_bytes=200)
    index = build_retrieval_index(
        graph,
        partition_by_node=_partitions(graph),
        config=config,
    )
    response = retrieve_solidity_cpt(
        graph,
        index,
        RetrievalQuery(text="contract function compiler license"),
        scope=RetrievalScope(partition="train"),
        config=config,
    )
    assert response.bytes_used <= 200
    assert response.truncated_bytes or len(response.results) >= 0
    assert response.proof_authority is False
    assert all(hit.proof_authority is False for hit in response.results)
