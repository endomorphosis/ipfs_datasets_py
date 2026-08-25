"""Unit tests for the Open US Law isolated staging canary (OUL-042).

Acceptance:

* A clean cache redownloads descriptors and routed shards from the exact
  40-hex dataset revision and content-addressed bucket prefix.
* Every staged identity and routed byte is verified.
* Every query mode runs.
* Sparse I/O is demonstrated without a local artifact fallback.
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

from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ImmutableHubResolver,
    LocalRootTransport,
    MappingTransport,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = (
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "canary_open_us_law_hf_release.py"
)
_RECEIPT_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "staging_canary.json"
)
_STAGING_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "staging_upload.json"
)
_PRODUCER_PATHS = (
    _STAGING_PATH,
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "release_candidate.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "bucket_snapshot.json",
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "stage_open_us_law_hf_release.py",
)


def _load_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing canary CLI: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "canary_open_us_law_hf_release_oul042",
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
    result = cli.check_canary_receipt(receipt)
    assert result["ok"] is True
    assert result["task_id"] == "OUL-042"
    assert result["goal_id"] == "OUL-G070"
    assert result["publication_authorized"] is False
    assert result["live_network"] is False
    assert result["local_artifact_fallback"] is False
    assert result["require_live_staging"] is True
    assert result["mismatches"] == []
    assert len(result["dataset_revision"]) == 40
    assert result["bucket_staging_prefix"].startswith("releases/")
    assert result["bucket_staging_prefix"].endswith("/")
    assert result["manifest_digest"]
    assert len(result["manifest_digest"]) == 64
    assert result["query_mode_count"] == 5

    acceptance = receipt["acceptance"]
    assert acceptance["clean_cache_redownload"] is True
    assert acceptance["exact_40_hex_dataset_revision"] is True
    assert acceptance["content_addressed_bucket_prefix"] is True
    assert acceptance["all_bytes_verified"] is True
    assert acceptance["every_query_mode_ran"] is True
    assert acceptance["sparse_io"] is True
    assert acceptance["local_artifact_fallback_absent"] is True
    assert acceptance["publication_not_authorized"] is True
    assert acceptance["no_secret_or_path_leak"] is True
    assert acceptance["all_expected_outputs_required"] is True
    assert acceptance["criteria"] == cli.ACCEPTANCE_CRITERIA


def test_bound_to_live_staging_coordinates(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    staging = cli.load_staging_receipt()
    assert receipt["dataset_revision"] == staging["dataset_revision"]
    assert receipt["bucket_staging_prefix"] == staging["bucket_staging_prefix"]
    assert receipt["manifest_digest"] == staging["manifest_digest"]
    assert cli._GIT_SHA_RE.fullmatch(receipt["dataset_revision"])
    assert receipt["dataset_revision"].casefold() not in cli.PRODUCTION_REFS
    assert receipt["bucket_staging_prefix"] == f"releases/{receipt['manifest_digest']}/"
    assert receipt["staging"]["receipt_sha256"] == staging["receipt_sha256"]
    assert receipt["staging"]["identities_digest"] == staging["identities_digest"]
    assert receipt["target_repo"] == "justicedao/open-us-law-sparse-graphrag"
    assert receipt["bucket_id"] == "justicedao/open-us-law-bucket"


def test_every_query_mode_ran(receipt: dict[str, Any], cli: ModuleType) -> None:
    assert receipt["query_modes"] == [
        "bm25",
        "vector",
        "hybrid",
        "graph",
        "semantic-graph",
    ]
    modes = [row["mode"] for row in receipt["queries"]]
    assert modes == list(cli.QUERY_MODES)
    by_id = {row["id"]: row for row in receipt["queries"]}
    assert by_id["bm25_foia"]["top_entry_cid"] == "entry-a"
    assert by_id["vector_centroid0"]["top_entry_cid"] == "entry-a"
    assert by_id["hybrid_foia_agency"]["top_entry_cid"] == "entry-a"
    assert by_id["graph_entry_a"]["start_node_cid"] == "entry-a"
    assert by_id["semantic_graph_entry_a"]["start_node_cid"] == "entry-a"
    assert by_id["graph_entry_a"]["expected_min_results"] >= 1
    assert by_id["semantic_graph_entry_a"]["expected_min_results"] >= 1
    for row in receipt["queries"]:
        assert row["sparse_io"] is True
        assert row["id"]
        assert row["mode"] in cli.QUERY_MODES


def test_sparse_io_skips_unused_sibling_shards(receipt: dict[str, Any]) -> None:
    by_id = {row["id"]: row for row in receipt["queries"]}
    assert "data/bm25/postings/part-000001.parquet" in set(
        by_id["bm25_foia"]["unused_siblings_not_fetched"]
    )
    assert "data/vectors/centroid-000001-part-000000.parquet" in set(
        by_id["vector_centroid0"]["unused_siblings_not_fetched"]
    )
    assert receipt["sparse_io"]["full_index_downloaded"] is False
    assert receipt["sparse_io"]["local_artifact_fallback"] is False
    assert "data/bm25/postings/part-000001.parquet" in set(
        receipt["sparse_io"]["unused_siblings_not_fetched"]
    )


def test_clean_cache_redownload_covers_descriptors_and_shards(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    assert receipt["clean_cache"] is True
    assert receipt["local_root_used"] is False
    assert receipt["local_artifact_fallback"] is False
    control = receipt["control_redownload"]
    shards = receipt["selected_shard_redownload"]
    assert control["within_budget"] is True
    assert shards["within_budget"] is True
    assert set(control["paths"]) == set(cli.CONTROL_INDEXES)
    assert set(shards["paths"]) == set(cli.SELECTED_SHARDS)
    staged = receipt["redownload"]["staged_identities"]
    assert staged["bytes_verified"] is True
    assert staged["clean_cache"] is True
    assert staged["file_count"] > 0
    assert staged["verified_count"] == staged["file_count"]
    for row in staged["files"]:
        assert row["verified"] is True
        assert cli._SHA256_RE.fullmatch(row["sha256"])
        assert row["dataset_object_id"].startswith("dataset:")
        assert row["bucket_object_id"].startswith("bucket:")
        assert receipt["dataset_revision"] in row["dataset_object_id"]
        assert receipt["manifest_digest"] in row["bucket_object_id"]


def test_no_local_artifact_fallback(receipt: dict[str, Any], cli: ModuleType) -> None:
    assert receipt["transport"] == "mapping_isolated_staging_store"
    assert receipt["isolated_transport"] is True
    assert receipt["redownload"]["transport"] == "mapping_isolated_staging_store"
    with pytest.raises(cli.CanaryFallbackError):
        cli.open_pinned_query_client(
            repo_id="justicedao/open-us-law-sparse-graphrag",
            revision=receipt["dataset_revision"],
            transport=MappingTransport({"manifest.json": b"{}"}),
            cache_dir=Path("unused-cache"),
            local_root=Path("."),
        )


def test_mapping_transport_is_required_for_queries(
    receipt: dict[str, Any], cli: ModuleType, tmp_path: Path
) -> None:
    root = tmp_path / "release"
    root.mkdir()
    (root / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(cli.CanaryFallbackError):
        cli.open_pinned_query_client(
            repo_id="justicedao/open-us-law-sparse-graphrag",
            revision=receipt["dataset_revision"],
            transport=LocalRootTransport(root),  # type: ignore[arg-type]
            cache_dir=tmp_path / "cache",
        )


def test_mutable_revision_rejected(cli: ModuleType) -> None:
    for value in ("main", "latest", "HEAD", "staging", "canary", ""):
        with pytest.raises(cli.CanaryRemoteError):
            cli.require_immutable_staging_revision(value)


def test_bucket_prefix_must_match_manifest(cli: ModuleType) -> None:
    digest = "ab" * 32
    assert cli.require_bucket_prefix(f"releases/{digest}/", manifest_digest=digest)
    with pytest.raises(cli.CanaryRemoteError):
        cli.require_bucket_prefix("releases/other/", manifest_digest=digest)
    with pytest.raises(cli.CanaryRemoteError):
        cli.require_bucket_prefix("LATEST.json", manifest_digest=digest)


def test_canary_is_deterministic(cli: ModuleType) -> None:
    first = cli.build_default_canary_receipt()
    second = cli.build_default_canary_receipt()
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert first["dataset_revision"] == second["dataset_revision"]
    assert first["queries"] == second["queries"]
    assert first["redownload"]["staged_identities"] == second["redownload"][
        "staged_identities"
    ]


def test_require_live_staging_missing_receipt(
    cli: ModuleType, tmp_path: Path
) -> None:
    missing = tmp_path / "staging_upload.json"
    with pytest.raises(cli.MissingInputError):
        cli.load_staging_receipt(missing, require_live_staging=True)


def test_require_live_staging_rejects_mutable_revision(
    cli: ModuleType, tmp_path: Path
) -> None:
    staging = cli.load_staging_receipt()
    tampered = copy.deepcopy(staging)
    tampered["dataset_revision"] = "main"
    path = tmp_path / "staging_upload.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises((cli.CanaryRemoteError, cli.MismatchError)):
        cli.load_staging_receipt(path, require_live_staging=True)


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


def test_main_require_live_staging_check(
    cli: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.materialize_default_receipt()
    rc = cli.main(["--require-live-staging", "--check"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["task_id"] == "OUL-042"
    assert payload["mismatches"] == []
    assert payload["require_live_staging"] is True
    assert payload["local_artifact_fallback"] is False
    assert len(payload["dataset_revision"]) == 40


def test_check_receipt_detects_drift(cli: ModuleType, receipt: dict[str, Any]) -> None:
    tampered = copy.deepcopy(receipt)
    tampered["dataset_revision"] = "0" * 40
    tampered["receipt_sha256"] = cli.digest_mapping(
        {key: value for key, value in tampered.items() if key != "receipt_sha256"}
    )
    with pytest.raises((cli.StaleInputError, cli.MismatchError)):
        cli.check_canary_receipt(tampered)


def test_publication_never_authorized(receipt: dict[str, Any]) -> None:
    assert receipt["publication_authorized"] is False
    assert receipt["public_mutation_authorized"] is False
    assert receipt["live_network"] is False
    assert receipt["network_required"] is False
    assert receipt["tokens_used"] is False


def test_redownload_uses_clean_cache_resolver(
    cli: ModuleType, tmp_path: Path
) -> None:
    pytest.importorskip("pyarrow")
    root = tmp_path / "release"
    root.mkdir()
    cli.materialize_query_fixture(root)
    transport = cli.mapping_transport_from_root(root)
    cache = tmp_path / "cache"
    cache.mkdir()
    resolver = ImmutableHubResolver(
        repo_id="justicedao/open-us-law-sparse-graphrag",
        revision="7600bf397a749996b7157b45a738a1856d728905",
        cache_dir=cache,
        transport=transport,
        local_root=None,
        supported_schemas={"hf-graphrag-release/v1", "open-us-law-sparse-graphrag/v1"},
    )
    report = cli.redownload_paths(
        resolver,
        ["manifest.json"],
        budget_bytes=1_000_000,
        budget_shards=4,
        label="control_indexes",
    )
    assert report["file_count"] == 1
    assert report["files"][0]["verified"] is True
    assert report["files"][0]["relative_path"] == "manifest.json"
    again = resolver.resolve("manifest.json")
    assert again.cache_hit is True
    with pytest.raises(cli.CanaryFallbackError):
        cli.redownload_paths(
            resolver,
            ["manifest.json"],
            budget_bytes=1_000_000,
            budget_shards=4,
            label="control_indexes",
        )


def test_on_disk_receipt_matches_builder(receipt: dict[str, Any]) -> None:
    on_disk = json.loads(_RECEIPT_PATH.read_text(encoding="utf-8"))
    assert on_disk["receipt_sha256"] == receipt["receipt_sha256"]
    assert on_disk["task_id"] == "OUL-042"
    assert on_disk["schema"] == "ipfs_datasets_py/open-us-law-staging-canary@1"
