"""Unit tests for federated legal-corpora query compatibility (LCR-067).

Acceptance:

* Cross-corpus queries are reproducible and provenance-safe.
* Dimension alone cannot establish vector-space compatibility.
* Graph and retrieval output is never legal authority or advice.
* Shared resolver/descriptor/vector contracts are proven.
* Normalized fusion keeps per-corpus scores labeled.
* Filters, bounded federated fetch, and abstention behave fail-closed.
"""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.legal_data.legal_corpora_query import (
    ACCEPTANCE_FLAGS,
    CORPUS_FEDERAL_REGISTER,
    CORPUS_STATE_LAWS,
    CorpusPin,
    DEFAULT_DIMENSION,
    DEFAULT_REPORT_RELPATH,
    FederatedBudgetError,
    FederatedFilters,
    FederatedFusionConfig,
    FederatedLimits,
    GraphOntologyIncompatibilityError,
    LegalAuthorityCollisionError,
    LegalCorporaQueryClient,
    LegalCorporaQueryInputError,
    QUERY_MODES,
    REPORT_SCHEMA,
    REPORT_SCHEMA_VERSION,
    RESEARCH_AID_DISCLAIMER,
    SHARED_VECTOR_SPACE_ID,
    TASK_ID,
    SharedSubstrateIncompatibilityError,
    VectorSpaceIncompatibilityError,
    annotate_hit_provenance,
    annotate_non_authority,
    assert_federated_fetch_within_budget,
    assert_immutable_revision,
    assert_no_retrieval_as_legal_authority,
    build_cross_corpus_canary,
    compact_federated_fetch_traces,
    compact_federated_recipe_hits,
    compare_vector_spaces,
    default_federal_pin,
    default_report_path,
    default_state_pin,
    dimension_only_incompatibility_case,
    fuse_federated_results,
    hit_matches_corpus_filters,
    open_legal_corpora_query_client,
    prove_graph_ontologies_remain_private,
    prove_shared_substrate,
    prove_vector_space_compatibility,
    query_replay_fingerprint,
    require_compatible_vector_spaces,
    research_aid_semantics,
    run_compact_federated_canaries,
    shared_vector_space_id,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import digest_mapping


STATE_PUBLIC_SHA = "8f6dc9a2279a3c9b3899bd9630e76262d6efa6da"
FEDERAL_PUBLIC_SHA = "71f277d8af6dd22bb6bbde46e5e6335579314fd6"
CONTRACT_PATH = default_report_path()


def _client() -> LegalCorporaQueryClient:
    return open_legal_corpora_query_client(
        state_revision=STATE_PUBLIC_SHA,
        federal_revision=FEDERAL_PUBLIC_SHA,
    )


def test_shared_vector_space_builders_agree() -> None:
    assert shared_vector_space_id() == SHARED_VECTOR_SPACE_ID
    assert "gte-small@" in SHARED_VECTOR_SPACE_ID
    assert f":d{DEFAULT_DIMENSION}:" in SHARED_VECTOR_SPACE_ID
    assert "pool=mean" in SHARED_VECTOR_SPACE_ID
    assert "norm=l2" in SHARED_VECTOR_SPACE_ID


def test_default_pins_share_substrate_and_space() -> None:
    state = default_state_pin(revision=STATE_PUBLIC_SHA)
    federal = default_federal_pin(revision=FEDERAL_PUBLIC_SHA)
    substrate = prove_shared_substrate(state, federal)
    vector = prove_vector_space_compatibility(state, federal)
    graph = prove_graph_ontologies_remain_private(state, federal)
    assert substrate["ok"] is True
    assert vector["compatible"] is True
    assert vector["fuse_vectors"] is True
    assert graph["fuse_graphs"] is False
    assert state.vector_space_id == federal.vector_space_id == SHARED_VECTOR_SPACE_ID
    assert state.repo_id != federal.repo_id
    assert state.graph_ontology_version != federal.graph_ontology_version


def test_dimension_alone_cannot_establish_compatibility() -> None:
    case = dimension_only_incompatibility_case()
    assert case["ok"] is True
    assert case["comparison"]["dimension_match"] is True
    assert case["comparison"]["compatible"] is False
    assert case["comparison"]["dimension_alone_cannot_establish_compatibility"] is True
    with pytest.raises(VectorSpaceIncompatibilityError, match="dimensions alone"):
        require_compatible_vector_spaces(
            case["left"],
            case["right"],
            left_name="gte",
            right_name="minilm",
        )


def test_missing_vector_space_id_fails_even_when_dimensions_match() -> None:
    left = {"dimension": 384, "vector_space_id": SHARED_VECTOR_SPACE_ID}
    right = {"dimension": 384, "vector_space_id": ""}
    comparison = compare_vector_spaces(left, right)
    assert comparison["dimension_match"] is True
    assert comparison["compatible"] is False
    with pytest.raises(VectorSpaceIncompatibilityError, match="required"):
        require_compatible_vector_spaces(left, right)


def test_shared_substrate_rejects_missing_family() -> None:
    state = default_state_pin(revision=STATE_PUBLIC_SHA)
    federal = default_federal_pin(revision=FEDERAL_PUBLIC_SHA)
    broken = federal.to_dict()
    broken["families"] = [item for item in broken["families"] if item != "centroids"]
    with pytest.raises(SharedSubstrateIncompatibilityError, match="centroids"):
        prove_shared_substrate(state, broken)


def test_shared_substrate_rejects_bound_drift() -> None:
    state = default_state_pin(revision=STATE_PUBLIC_SHA)
    federal = default_federal_pin(revision=FEDERAL_PUBLIC_SHA)
    broken = federal.to_dict()
    bounds = dict(broken["physical_bounds"])
    bounds["max_rows_per_physical_shard"] = 4097
    broken["physical_bounds"] = bounds
    with pytest.raises(SharedSubstrateIncompatibilityError, match="max_rows"):
        prove_shared_substrate(state, broken)


def test_graph_ontologies_cannot_be_merged() -> None:
    state = default_state_pin(revision=STATE_PUBLIC_SHA)
    federal = default_federal_pin(revision=FEDERAL_PUBLIC_SHA)
    proof = prove_graph_ontologies_remain_private(state, federal)
    assert proof["compatible_for_merge"] is False
    same = federal.to_dict()
    same["graph_ontology_version"] = state.graph_ontology_version
    with pytest.raises(GraphOntologyIncompatibilityError, match="domain-private"):
        prove_graph_ontologies_remain_private(state, same)


def test_mutable_revision_fails_closed() -> None:
    with pytest.raises(Exception, match="mutable"):
        assert_immutable_revision("main", name="revision")
    with pytest.raises(Exception):
        default_state_pin(revision="latest")


def test_hybrid_fusion_labels_corpus_scores_and_is_reproducible() -> None:
    client = _client()
    hits = compact_federated_recipe_hits()
    traces = compact_federated_fetch_traces()
    first = client.search(
        "inspection",
        mode="hybrid",
        per_corpus_hits=hits,
        fetch_traces=traces,
        top_k=4,
    )
    second = client.search(
        "inspection",
        mode="hybrid",
        per_corpus_hits=hits,
        fetch_traces=traces,
        top_k=4,
    )
    assert first.replay_fingerprint == second.replay_fingerprint
    assert first.ordered_result_cids() == second.ordered_result_cids()
    corpora = {item["corpus_id"] for item in first.results}
    assert corpora == {CORPUS_STATE_LAWS, CORPUS_FEDERAL_REGISTER}
    for item in first.results:
        assert item["legal_authority"] is False
        assert item["legal_advice"] is False
        assert item["provenance"]["corpus_id"] == item["corpus_id"]
        assert item["provenance"]["revision"]
        assert item["provenance"]["dataset_repo_id"]
        assert item["vector_space_id"] == SHARED_VECTOR_SPACE_ID
        assert "corpus_score" in item
        assert item["disclaimer"] == RESEARCH_AID_DISCLAIMER


def test_per_corpus_filters_do_not_leak_across_releases() -> None:
    client = _client()
    result = client.search(
        "inspection",
        mode="bm25",
        filters={
            "state": {"jurisdiction": "DC"},
            "federal": {"agency": "Federal Aviation Administration"},
        },
        per_corpus_hits=compact_federated_recipe_hits(),
        fetch_traces=compact_federated_fetch_traces(),
        top_k=4,
    )
    assert result.result_count >= 1
    for item in result.results:
        if item["corpus_id"] == CORPUS_STATE_LAWS:
            assert item["jurisdiction"] == "DC"
        else:
            assert item["agency"] == "Federal Aviation Administration"


def test_incompatible_space_abstains_from_vector_fusion() -> None:
    state = default_state_pin(revision=STATE_PUBLIC_SHA)
    foreign = default_federal_pin(revision=FEDERAL_PUBLIC_SHA).to_dict()
    foreign["vector_space_id"] = (
        "all-minilm-l6-v2@c9745ed1c9a4e3e7d8d7a3d1f1c8d8d8d8d8d8d8"
        f":d{DEFAULT_DIMENSION}:pool=mean:norm=l2"
    )
    client = LegalCorporaQueryClient((state, CorpusPin.from_mapping(foreign)))
    assert client.vector_compatibility["compatible"] is False
    result = client.search(
        "inspection",
        mode="vector",
        per_corpus_hits=compact_federated_recipe_hits(),
        fetch_traces=compact_federated_fetch_traces(),
        top_k=4,
    )
    assert any(
        item.get("reason") == "dimension_match_insufficient" for item in result.abstentions
    )
    assert all(item.get("fused") is False for item in result.results)
    assert result.result_count >= 2


def test_graph_mode_never_fuses_across_ontologies() -> None:
    result = _client().search(
        "entry",
        mode="neighbors",
        per_corpus_hits=compact_federated_recipe_hits(),
        fetch_traces=compact_federated_fetch_traces(),
        top_k=4,
    )
    assert any(
        item.get("reason") == "graph_ontology_incompatible" for item in result.abstentions
    )
    assert all(item.get("fused") is False for item in result.results)
    assert all(item.get("legal_authority") is False for item in result.results)


def test_retrieval_cannot_be_packaged_as_legal_authority_or_advice() -> None:
    with pytest.raises(LegalAuthorityCollisionError, match="legal_authority"):
        annotate_non_authority({"legal_authority": True, "entry_cid": "x"})
    with pytest.raises(LegalAuthorityCollisionError, match="legal_advice"):
        annotate_non_authority({"legal_advice": True, "entry_cid": "x"})
    with pytest.raises(LegalAuthorityCollisionError):
        assert_no_retrieval_as_legal_authority(
            [{"entry_cid": "x", "legal_authority": True}]
        )
    semantics = research_aid_semantics()
    assert semantics["legal_authority"] is False
    assert semantics["legal_advice"] is False
    assert "not legal authority" in semantics["disclaimer"]


def test_bounded_federated_fetch_rejects_over_budget() -> None:
    summary = assert_federated_fetch_within_budget(
        compact_federated_fetch_traces(),
        FederatedLimits(max_bytes=200_000, max_shards=16, max_rows=64),
    )
    assert summary["within_budget"] is True
    with pytest.raises(FederatedBudgetError, match="bytes"):
        assert_federated_fetch_within_budget(
            {"bytes": 9_000_000, "shards": 1, "rows": 1},
            FederatedLimits(max_bytes=1000, max_shards=16, max_rows=64),
        )
    with pytest.raises(Exception, match="unsafe"):
        assert_federated_fetch_within_budget(
            {"bytes": 10, "shards": 1, "rows": 1, "fetched_paths": ["../secret.parquet"]}
        )


def test_hit_filters_and_provenance() -> None:
    pin = default_state_pin(revision=STATE_PUBLIC_SHA)
    hit = annotate_hit_provenance(
        {"entry_cid": "state-entry-dc", "jurisdiction": "DC", "score": 1.0},
        pin,
        mode="bm25",
    )
    assert hit["corpus_id"] == CORPUS_STATE_LAWS
    assert hit["provenance"]["entry_cid"] == "state-entry-dc"
    assert hit_matches_corpus_filters(hit, {"jurisdiction": "DC"})
    assert not hit_matches_corpus_filters(hit, {"jurisdiction": "CA"})


def test_weighted_fusion_preserves_component_scores() -> None:
    pins = {
        CORPUS_STATE_LAWS: default_state_pin(revision=STATE_PUBLIC_SHA),
        CORPUS_FEDERAL_REGISTER: default_federal_pin(revision=FEDERAL_PUBLIC_SHA),
    }
    fused, diagnostics = fuse_federated_results(
        compact_federated_recipe_hits(),
        pins,
        mode="hybrid",
        config=FederatedFusionConfig(method="weighted", state_weight=0.6, federal_weight=0.4),
        top_k=4,
        fuse_vectors=True,
    )
    assert diagnostics["abstained_from_fusion"] is False
    assert fused
    assert all("component_scores" in item for item in fused)
    assert all(item["fusion_method"] == "weighted" for item in fused)


def test_unknown_corpus_filter_fails_closed() -> None:
    with pytest.raises(LegalCorporaQueryInputError, match="unknown corpora"):
        FederatedFilters.from_mapping({"corpora": ["patents"]})


def test_client_requires_both_pins() -> None:
    with pytest.raises(LegalCorporaQueryInputError, match="at least two"):
        LegalCorporaQueryClient((default_state_pin(revision=STATE_PUBLIC_SHA),))


def test_replay_fingerprint_changes_when_ranking_changes() -> None:
    results = [
        {"corpus_id": CORPUS_STATE_LAWS, "entry_cid": "a", "score": 1.0},
        {"corpus_id": CORPUS_FEDERAL_REGISTER, "entry_cid": "b", "score": 0.5},
    ]
    first = query_replay_fingerprint(mode="bm25", query="inspection", results=results)
    swapped = [
        {"corpus_id": CORPUS_FEDERAL_REGISTER, "entry_cid": "b", "score": 2.0},
        {"corpus_id": CORPUS_STATE_LAWS, "entry_cid": "a", "score": 0.1},
    ]
    second = query_replay_fingerprint(mode="bm25", query="inspection", results=swapped)
    assert first != second


def test_compact_canaries_pass() -> None:
    report = run_compact_federated_canaries(_client())
    assert report["ok"] is True
    for case in report["cases"].values():
        assert case["ok"] is True


def test_cross_corpus_canary_contract_is_sealed() -> None:
    payload = build_cross_corpus_canary(
        state_revision=STATE_PUBLIC_SHA,
        federal_revision=FEDERAL_PUBLIC_SHA,
    )
    assert payload["task_id"] == TASK_ID
    assert payload["schema"] == REPORT_SCHEMA
    assert payload["schema_version"] == REPORT_SCHEMA_VERSION
    assert payload["status"] == "passed"
    assert payload["network_required"] is False
    assert payload["vector_space_id"] == SHARED_VECTOR_SPACE_ID
    for flag in ACCEPTANCE_FLAGS:
        assert payload["acceptance"][flag] is True, flag
    assert payload["research_aid"]["legal_authority"] is False
    assert payload["research_aid"]["legal_advice"] is False
    assert "modes" in payload
    assert set(QUERY_MODES).issubset(set(payload["modes"]))
    rebuilt = build_cross_corpus_canary(
        state_revision=STATE_PUBLIC_SHA,
        federal_revision=FEDERAL_PUBLIC_SHA,
    )
    assert payload["digest"] == rebuilt["digest"]
    assert digest_mapping(
        {key: value for key, value in payload.items() if not key.endswith("digest") and key != "digest"}
    )


def test_sealed_report_path_and_file() -> None:
    assert DEFAULT_REPORT_RELPATH.as_posix().endswith("cross_corpus_canary.json")
    if CONTRACT_PATH.is_file():
        sealed = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        assert sealed["task_id"] == TASK_ID
        assert sealed["status"] == "passed"
        assert sealed["acceptance"]["dimension_alone_cannot_establish_compatibility"] is True
        assert sealed["acceptance"]["graph_retrieval_not_legal_authority"] is True
        assert sealed["acceptance"]["graph_retrieval_not_legal_advice"] is True
        assert sealed["research_aid"]["legal_authority"] is False


def test_canary_script_check_passes() -> None:
    from scripts.ops.legal_data.canary_legal_corpora_public_releases import (
        check_cross_corpus_canary,
        main,
    )

    if not CONTRACT_PATH.is_file():
        pytest.skip("sealed cross_corpus_canary.json is written by the implementation pass")
    result = check_cross_corpus_canary()
    assert result["ok"] is True
    assert result["dimension_alone_cannot_establish_compatibility"] is True
    assert result["graph_retrieval_not_legal_authority"] is True
    assert main(["--check"]) == 0
