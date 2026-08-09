"""Integration tests for the US Code sparse GraphRAG adapter (USCIR-029)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.knowledge_graphs.adapters.uscode import (
    CORPUS_ID,
    UscodeCorpusAdapter,
    register_uscode_adapter,
)
from ipfs_datasets_py.processors.legal_data.uscode_sparse_graphrag import (
    PRIMARY_KEY_V2,
    RELEASE_PROFILE,
    content_cid,
    reconcile_adapter_roots,
    AdapterRootSet,
    build_family_root_cid,
)

pytestmark = pytest.mark.integration


def test_register_uscode_adapter_descriptor() -> None:
    registration = register_uscode_adapter()
    assert registration["corpus_id"] == CORPUS_ID
    assert registration["dataset_repo_id"] == "justicedao/ipfs_uscode"
    assert registration["primary_key"] == PRIMARY_KEY_V2
    assert registration["profile"] == RELEASE_PROFILE
    assert registration["adapter_class"] == "UscodeCorpusAdapter"
    assert registration["capability"]["release_gate_capable"] is True


def test_adapter_validate_without_release_root() -> None:
    adapter = UscodeCorpusAdapter()
    receipt = adapter.validate()
    assert receipt["schema"] == "uscode-corpus-validation-receipt/v1"
    assert receipt["registry_reconciled"] is True
    assert receipt["primary_key"] == "entry_cid"
    assert receipt["identity"]["corpus_id"] == "uscode"
    assert receipt["capability"]["differential_capable"] is True


def test_adapter_identity_and_registry_resolution() -> None:
    adapter = UscodeCorpusAdapter()
    identity = adapter.identity()
    assert identity["task_id"] == "USCIR-029"
    assert identity["primary_key"] == PRIMARY_KEY_V2
    registry = adapter.registry_resolution()
    assert registry["reconciled"] is True
    assert "laws.parquet" in " ".join(registry["accepted_parquet_paths"])


def test_adapter_root_reconciliation() -> None:
    corpus = content_cid({"corpus": "uscode", "n": 1})
    bm25 = build_family_root_cid("bm25", {"rows": 2}, parent_root_cid=corpus)
    vectors = build_family_root_cid("vectors", {"rows": 2}, parent_root_cid=corpus)
    graph = build_family_root_cid("graph", {"rows": 2}, parent_root_cid=corpus)
    roots = AdapterRootSet(
        corpus_root_cid=corpus,
        bm25_root_cid=bm25,
        vector_root_cid=vectors,
        graph_root_cid=graph,
    )
    adapter = UscodeCorpusAdapter()
    receipt = adapter.reconcile_roots(roots, require_all_families=True)
    assert receipt["reconciled"] is True
    assert set(receipt["families_present"]) >= {"bm25", "vector", "graph"}


def test_adapter_legacy_opt_in_path() -> None:
    adapter = UscodeCorpusAdapter().use_legacy_compatibility()
    assert adapter.compatibility_config_name == "legacy-uscode-parquet/v1"
    # Default adapter remains v2.
    assert UscodeCorpusAdapter().compatibility_config_name == "publicus-ir-graphrag/v2"


def test_offline_query_client_against_mini_release(tmp_path: Path) -> None:
    # Optional path: only when mini release builder is available.
    from tests.unit.retrieval.hf_graphrag.test_query import (
        PINNED_REVISION,
        REPO_ID,
        build_mini_release,
    )

    release = tmp_path / "release"
    release.mkdir()
    build_mini_release(release)
    adapter = UscodeCorpusAdapter(
        release_root=release,
        dataset_repo_id=REPO_ID,
        revision=PINNED_REVISION,
    )
    client = adapter.open_query_client()
    result = client.bm25_search("foia agency", top_k=2, hydrate=True)
    assert result.mode == "bm25"
    assert result.results is not None
