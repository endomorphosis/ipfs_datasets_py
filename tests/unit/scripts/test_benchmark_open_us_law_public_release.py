"""Unit tests for the Open US Law public-pin retrieval benchmark (OUL-046).

Acceptance:

* Cold and warm public queries meet declared relevance, latency, bytes,
  shard-count, and graph-budget thresholds.
* No query downloads the complete BM25, vector, graph, or corpus family.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_sparse_graphrag import (
    QUERY_MODES,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    LocalRootTransport,
    MappingTransport,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = (
    _REPO_ROOT
    / "scripts"
    / "ops"
    / "legal_data"
    / "benchmark_open_us_law_public_release.py"
)
_RECEIPT_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "public_benchmark.json"
)
_PRODUCER_PATHS = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "publication_receipt.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "public_canary.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "evaluation.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "query_contract.json",
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "canary_open_us_law_hf_release.py",
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "check_open_us_law_public_release.py",
)


def _load_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing public-benchmark CLI: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "benchmark_open_us_law_public_release_oul046",
        _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.name is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    return _load_module()


@pytest.fixture(scope="module")
def receipt(cli: ModuleType) -> dict[str, Any]:
    payload, path = cli.materialize_default_receipt()
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    assert on_disk["task_id"] == payload["task_id"]
    assert on_disk["receipt_sha256"] == payload["receipt_sha256"]
    assert on_disk["dataset_revision"] == payload["dataset_revision"]
    return payload


def test_script_and_dependencies_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    for path in _PRODUCER_PATHS:
        assert path.is_file(), f"missing producer input: {path}"


def test_help_exits_zero(cli: ModuleType) -> None:
    assert cli.main(["--help"]) == 0


def test_fixture_receipt_acceptance(receipt: dict[str, Any], cli: ModuleType) -> None:
    result = cli.check_public_benchmark_receipt(receipt)
    assert result["ok"] is True
    assert result["task_id"] == "OUL-046"
    assert result["goal_id"] == "OUL-G080"
    assert result["publication_authorized"] is False
    assert result["live_network"] is False
    assert result["local_artifact_fallback"] is False
    assert result["require_public_pin"] is True
    assert result["mismatches"] == []
    assert len(result["dataset_revision"]) == 40
    assert result["bucket_content_root"].startswith("releases/")
    assert result["bucket_content_root"].endswith("/")
    assert result["manifest_digest"]
    assert len(result["manifest_digest"]) == 64
    assert result["query_mode_count"] == 5
    assert result["cold_latency_ms_max"] <= cli.COLD_LATENCY_MS_GATE
    assert result["warm_latency_ms_max"] <= cli.WARM_LATENCY_MS_GATE

    acceptance = receipt["acceptance"]
    assert acceptance["cold_queries_meet_relevance"] is True
    assert acceptance["warm_queries_meet_relevance"] is True
    assert acceptance["cold_queries_meet_latency"] is True
    assert acceptance["warm_queries_meet_latency"] is True
    assert acceptance["cold_queries_meet_bytes"] is True
    assert acceptance["warm_queries_meet_bytes"] is True
    assert acceptance["cold_queries_meet_shard_count"] is True
    assert acceptance["warm_queries_meet_shard_count"] is True
    assert acceptance["graph_budget_met"] is True
    assert acceptance["no_complete_bm25_family_download"] is True
    assert acceptance["no_complete_vector_family_download"] is True
    assert acceptance["no_complete_graph_family_download"] is True
    assert acceptance["no_complete_corpus_family_download"] is True
    assert acceptance["bound_to_public_pin"] is True
    assert acceptance["no_secret_or_path_leak"] is True
    assert acceptance["all_expected_outputs_required"] is True
    assert acceptance["criteria"] == cli.ACCEPTANCE_CRITERIA


def test_bound_to_public_pin(receipt: dict[str, Any], cli: ModuleType) -> None:
    publication = cli.load_publication_receipt()
    canary = cli.load_public_canary()
    assert receipt["dataset_revision"] == publication["dataset_revision"]
    assert receipt["bucket_content_root"] == publication["bucket_release_prefix"]
    assert receipt["manifest_digest"] == publication["manifest_digest"]
    assert receipt["dataset_revision"] == canary["dataset_revision"]
    assert receipt["bucket_content_root"] == canary["bucket_content_root"]
    assert cli._GIT_SHA_RE.fullmatch(receipt["dataset_revision"])
    assert receipt["dataset_revision"].casefold() not in cli.PRODUCTION_REFS
    assert receipt["bucket_content_root"] == f"releases/{receipt['manifest_digest']}/"
    assert receipt["publication"]["receipt_sha256"] == publication["receipt_sha256"]
    assert receipt["target_repo"] == "justicedao/open-us-law-sparse-graphrag"
    assert receipt["bucket_id"] == "justicedao/open-us-law-bucket"
    assert receipt["require_public_pin"] is True


def test_every_public_mode_has_cold_and_warm_measurements(
    receipt: dict[str, Any],
) -> None:
    modes = [row["mode"] for row in receipt["queries"]]
    assert modes == list(QUERY_MODES)
    assert receipt["query_modes"] == list(QUERY_MODES)
    assert receipt["query_mode_count"] == 5
    for row in receipt["queries"]:
        assert row["id"]
        assert row["cold"]["phase"] == "cold"
        assert row["warm"]["phase"] == "warm"
        assert row["cold"]["relevance_ok"] is True
        assert row["warm"]["relevance_ok"] is True
        assert row["cold"]["hit_at_k"] >= 1.0
        assert row["warm"]["hit_at_k"] >= 1.0
        assert row["cold"]["top_entry_cid"] == row["expected_top_entry_cid"]
        assert row["warm"]["top_entry_cid"] == row["expected_top_entry_cid"]
        assert row["thresholds_met"]["cold"]["relevance"] is True
        assert row["thresholds_met"]["warm"]["relevance"] is True
        assert row["thresholds_met"]["warm_faster_than_cold"] is True


def test_declared_latency_bytes_and_shard_thresholds(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    thresholds = receipt["thresholds"]
    assert thresholds == cli.declared_thresholds()
    assert thresholds["relevance_hit_at_k"] == cli.RELEVANCE_HIT_AT_K_GATE
    assert thresholds["cold_latency_ms"] == cli.COLD_LATENCY_MS_GATE
    assert thresholds["warm_latency_ms"] == cli.WARM_LATENCY_MS_GATE
    assert thresholds["max_shards"] == cli.MAX_SHARDS_GATE
    assert thresholds["max_graph_nodes"] == cli.MAX_GRAPH_NODES_GATE
    for row in receipt["queries"]:
        cold = row["cold"]
        warm = row["warm"]
        assert cold["latency_ms"] <= cli.COLD_LATENCY_MS_GATE
        assert warm["latency_ms"] <= cli.WARM_LATENCY_MS_GATE
        assert warm["latency_ms"] <= cold["latency_ms"]
        assert cold["bytes"] <= cli.COLD_BYTES_GATE
        assert warm["bytes"] <= cli.WARM_BYTES_GATE
        assert warm["network_bytes"] <= cli.WARM_NETWORK_BYTES_GATE
        assert warm["network_bytes"] <= cold["network_bytes"]
        assert cold["shard_count"] <= cli.MAX_SHARDS_GATE
        assert warm["shard_count"] <= cli.MAX_SHARDS_GATE
        assert warm["cache_hits"] > 0
        assert cold["cache_hits"] == 0
        assert cold["cache_misses"] > 0
        graph = cold["graph_budget"]
        assert graph["nodes"] <= cli.MAX_GRAPH_NODES_GATE
        assert graph["edges"] <= cli.MAX_GRAPH_EDGES_GATE
        assert graph["depth"] <= cli.MAX_GRAPH_DEPTH_GATE
    assert receipt["phases"]["cold"]["latency_ms_max"] <= cli.COLD_LATENCY_MS_GATE
    assert receipt["phases"]["warm"]["latency_ms_max"] <= cli.WARM_LATENCY_MS_GATE
    assert receipt["phases"]["cold"]["bytes_max"] <= cli.COLD_BYTES_GATE
    assert receipt["phases"]["warm"]["network_bytes_max"] <= cli.WARM_NETWORK_BYTES_GATE


def test_graph_budget_recorded_for_graph_modes(receipt: dict[str, Any]) -> None:
    by_id = {row["id"]: row for row in receipt["queries"]}
    for query_id in ("graph_entry_a", "semantic_graph_entry_a"):
        graph = by_id[query_id]["cold"]["graph_budget"]
        assert graph["nodes"] > 0
        assert graph["edges"] > 0
        assert graph["depth"] > 0
        assert graph["nodes"] <= 16
        assert graph["edges"] <= 32
        assert graph["depth"] <= 2
    lexical = by_id["bm25_foia"]["cold"]["graph_budget"]
    assert lexical == {"depth": 0, "edges": 0, "nodes": 0}


def test_no_query_downloads_complete_index_family(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    family = receipt["family_completeness"]
    assert family["complete_download"] is False
    for name in cli.INDEX_FAMILIES:
        block = family["families"][name]
        available = list(block["available"])
        assert len(available) >= 3, name
        assert block["complete_download"] is False, name
        assert block["max_fetched"] < len(available), name
        assert set(block["union_fetched"]) != set(available), name
        unused = set(block["unused_siblings"])
        assert unused
        assert cli.NEVER_ROUTED_SIBLINGS[name] in unused
        assert unused.isdisjoint(set(block["union_fetched"])), name
        assert unused.issubset(set(available)), name
    for row in receipt["queries"]:
        unused = set(row["unused_siblings_not_fetched"])
        fetched = set(row["cold"]["fetched_paths"]) | set(row["warm"]["fetched_paths"])
        assert unused
        assert unused.isdisjoint(fetched), row["id"]
        for name in cli.INDEX_FAMILIES:
            members = set(cli.FAMILY_INVENTORY[name])
            taken = set(row["cold"]["family_paths"][name])
            assert taken != members, f"{row['id']} {name}"
            assert len(taken) < len(members), f"{row['id']} {name}"


def test_bm25_vector_graph_and_corpus_unused_siblings(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    unused = {
        path
        for row in receipt["queries"]
        for path in row["unused_siblings_not_fetched"]
    }
    assert "data/bm25/postings/part-000001.parquet" in unused
    assert "data/vectors/centroid-000001-part-000000.parquet" in unused
    assert "data/graph/adjacency/out/part-000001.parquet" in unused
    assert "data/corpus/part-000001.parquet" in unused
    for family, path in cli.NEVER_ROUTED_SIBLINGS.items():
        assert path in unused, family
    by_id = {row["id"]: row for row in receipt["queries"]}
    assert (
        "data/bm25/postings/part-000001.parquet"
        in by_id["bm25_foia"]["unused_siblings_not_fetched"]
    )
    assert (
        "data/vectors/centroid-000001-part-000000.parquet"
        in by_id["vector_centroid0"]["unused_siblings_not_fetched"]
    )
    assert (
        "data/graph/adjacency/out/part-000001.parquet"
        in by_id["graph_entry_a"]["unused_siblings_not_fetched"]
    )
    assert (
        "data/bm25/postings/part-000002.parquet"
        in by_id["bm25_foia"]["unused_siblings_not_fetched"]
    )


def test_relevance_controls_match_public_canary_recipe(
    receipt: dict[str, Any],
) -> None:
    by_id = {row["id"]: row for row in receipt["queries"]}
    assert by_id["bm25_foia"]["expected_top_entry_cid"] == "entry-a"
    assert by_id["vector_centroid0"]["expected_top_entry_cid"] == "entry-a"
    assert by_id["hybrid_foia_agency"]["expected_top_entry_cid"] == "entry-a"
    assert by_id["graph_entry_a"]["start_node_cid"] == "entry-a"
    assert by_id["semantic_graph_entry_a"]["start_node_cid"] == "entry-a"
    assert by_id["bm25_foia"]["query"] == "foia"
    assert by_id["hybrid_foia_agency"]["query"] == "foia agency"


def test_evaluation_and_canary_dependencies_are_bound(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    evaluation = cli.load_evaluation_receipt()
    assert receipt["evaluation"]["task_id"] == "OUL-037"
    assert receipt["evaluation"]["bounded_shard_selection"] is True
    assert receipt["evaluation"]["substantially_less_than_full_release"] is True
    assert evaluation["acceptance"]["bounded_shard_selection"] is True
    assert receipt["public_canary"]["task_id"] == "OUL-045"
    assert receipt["depends_on"] == ["OUL-037", "OUL-045"]


def test_no_local_artifact_fallback(receipt: dict[str, Any], cli: ModuleType) -> None:
    assert receipt["transport"] == "isolated_recorded_public_store"
    assert receipt["isolated_transport"] is True
    assert receipt["local_artifact_fallback"] is False
    assert receipt["local_root_used"] is False
    canary = cli.load_canary_module()
    with pytest.raises(canary.CanaryFallbackError):
        canary.open_pinned_query_client(
            repo_id="justicedao/open-us-law-sparse-graphrag",
            revision=receipt["dataset_revision"],
            transport=MappingTransport({"manifest.json": b"{}"}),
            cache_dir=Path("unused-cache"),
            local_root=Path("."),
        )


def test_mapping_transport_is_required_for_live_proof(
    receipt: dict[str, Any], cli: ModuleType, tmp_path: Path
) -> None:
    canary = cli.load_canary_module()
    root = tmp_path / "release"
    root.mkdir()
    (root / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(canary.CanaryFallbackError):
        canary.open_pinned_query_client(
            repo_id="justicedao/open-us-law-sparse-graphrag",
            revision=receipt["dataset_revision"],
            transport=LocalRootTransport(root),  # type: ignore[arg-type]
            cache_dir=tmp_path / "cache",
        )


def test_mutable_revision_rejected(cli: ModuleType) -> None:
    for value in ("main", "latest", "HEAD", "staging", "canary", ""):
        with pytest.raises(cli.PublicPinError):
            cli.require_immutable_public_revision(value)


def test_bucket_content_root_must_match_manifest(cli: ModuleType) -> None:
    digest = "ab" * 32
    assert cli.require_bucket_content_root(
        f"releases/{digest}/", manifest_digest=digest
    )
    with pytest.raises(cli.PublicPinError):
        cli.require_bucket_content_root("releases/other/", manifest_digest=digest)
    with pytest.raises(cli.PublicPinError):
        cli.require_bucket_content_root("LATEST.json", manifest_digest=digest)


def test_benchmark_is_deterministic(cli: ModuleType) -> None:
    first = cli.build_default_public_benchmark()
    second = cli.build_default_public_benchmark()
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert first["dataset_revision"] == second["dataset_revision"]
    assert first["queries"] == second["queries"]
    assert first["family_completeness"] == second["family_completeness"]
    assert first["phases"] == second["phases"]


def test_require_public_pin_missing_receipt(
    cli: ModuleType, tmp_path: Path
) -> None:
    missing = tmp_path / "publication_receipt.json"
    with pytest.raises(cli.MissingInputError):
        cli.load_publication_receipt(missing, require_public_pin=True)


def test_require_public_pin_rejects_mutable_revision(
    cli: ModuleType, tmp_path: Path
) -> None:
    publication = cli.load_publication_receipt()
    tampered = copy.deepcopy(publication)
    tampered["dataset_revision"] = "main"
    path = tmp_path / "publication_receipt.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises((cli.PublicPinError, cli.MismatchError)):
        cli.load_publication_receipt(path, require_public_pin=True)


def test_secrets_on_argv_rejected(cli: ModuleType) -> None:
    with pytest.raises(cli.SecretLeakError):
        cli.reject_secrets_in_argv(
            ["--hf_token=hf_secretvalue1234567890", "--check"]
        )
    with pytest.raises(cli.SecretLeakError):
        cli.reject_secrets_in_argv(["Authorization: Bearer abc", "--write"])


def test_credentials_in_payload_rejected(cli: ModuleType) -> None:
    with pytest.raises(cli.SecretLeakError):
        cli.reject_credentials_in_payload(
            {"receipt_sha256": "x", "hf_token": "hf_should_not_appear_here_12345"},
            label="test",
        )


def test_receipt_has_no_absolute_local_paths_or_secrets(
    receipt: dict[str, Any], cli: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = json.dumps(receipt)
    assert "/home/" not in rendered
    assert "file://" not in rendered
    assert "hf_token" not in rendered.casefold()
    assert "bearer " not in rendered.casefold()
    monkeypatch.setenv("HF_TOKEN", "super-secret-auth-value-xyz")
    cli.reject_credentials_in_payload(receipt, label="receipt")
    assert "super-secret-auth-value-xyz" not in rendered


def test_live_hub_is_refused(cli: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["--live"])
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "live_hub_refused"
    assert payload["live_network"] is False
    assert payload["mutation_executed"] is False


def test_main_check(cli: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    cli.materialize_default_receipt()
    rc = cli.main(["--check"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["task_id"] == "OUL-046"
    assert payload["mismatches"] == []
    assert payload["require_public_pin"] is True
    assert payload["local_artifact_fallback"] is False
    assert len(payload["dataset_revision"]) == 40


def test_check_receipt_detects_drift(cli: ModuleType, receipt: dict[str, Any]) -> None:
    tampered = copy.deepcopy(receipt)
    tampered["dataset_revision"] = "0" * 40
    tampered["receipt_sha256"] = cli.digest_mapping(
        {key: value for key, value in tampered.items() if key != "receipt_sha256"}
    )
    with pytest.raises((cli.StaleInputError, cli.MismatchError, cli.PublicPinError)):
        cli.check_public_benchmark_receipt(tampered)


def test_complete_family_download_fails_closed(cli: ModuleType) -> None:
    cold = cli.measure_phase(cli.QUERY_SPECS[0], phase="cold")
    cold["family_paths"] = {
        family: list(cli.FAMILY_INVENTORY[family]) for family in cli.INDEX_FAMILIES
    }
    with pytest.raises(cli.PublicBenchmarkFamilyError):
        cli.family_completeness_for_measurements((cold,))


def test_threshold_breach_fails_closed(cli: ModuleType) -> None:
    spec = copy.deepcopy(cli.QUERY_SPECS[0])
    cold = cli.measure_phase(spec, phase="cold")
    cold["latency_ms"] = cli.COLD_LATENCY_MS_GATE + 1
    verdict = cli.evaluate_thresholds(cold, phase="cold")
    assert verdict["latency"] is False
    warm = cli.measure_phase(spec, phase="warm")
    warm["network_bytes"] = 1
    warm_verdict = cli.evaluate_thresholds(warm, phase="warm")
    assert warm_verdict["network_bytes"] is False


def test_further_publication_never_authorized(receipt: dict[str, Any]) -> None:
    assert receipt["publication_authorized"] is False
    assert receipt["public_mutation_authorized"] is False
    assert receipt["live_network"] is False
    assert receipt["network_required"] is False
    assert receipt["tokens_used"] is False


def test_on_disk_receipt_matches_builder(receipt: dict[str, Any], cli: ModuleType) -> None:
    on_disk = json.loads(_RECEIPT_PATH.read_text(encoding="utf-8"))
    assert on_disk["receipt_sha256"] == receipt["receipt_sha256"]
    assert on_disk["task_id"] == "OUL-046"
    assert on_disk["schema"] == "ipfs_datasets_py/open-us-law-public-benchmark@1"
    assert on_disk["acceptance"]["criteria"] == receipt["acceptance"]["criteria"]
    assert on_disk["measurement_model"] == "deterministic_sparse_io_accounting"


def test_live_proof_when_pyarrow_available(cli: ModuleType) -> None:
    canary = cli.load_canary_module()
    if getattr(canary, "pa", None) is None:
        pytest.skip("pyarrow is unavailable in this environment")
    publication = cli.load_publication_receipt()
    proof = cli.prove_live_queries(publication=publication)
    assert proof["executed"] is True
    assert proof["query_count"] == 5
    assert proof["status"] == "live_mapping_transport"
    modes = [row["mode"] for row in proof["queries"]]
    assert modes == list(QUERY_MODES)
    for row in proof["queries"]:
        assert row["sparse_io"] is True
        fetched = set(row["paths"])
        for family, members in cli.FAMILY_INVENTORY.items():
            present = [path for path in members if path in fetched]
            assert set(present) != set(members), f"{row['id']} {family}"
        unused = set(cli.unused_siblings_for_spec(
            next(spec for spec in cli.QUERY_SPECS if spec["id"] == row["id"])
        ))
        assert unused.isdisjoint(fetched), row["id"]
        for family, path in cli.NEVER_ROUTED_SIBLINGS.items():
            assert path not in fetched, f"{row['id']} fetched never-routed {family}"
