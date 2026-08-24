"""Unit tests for the Open US Law public-release canary (OUL-045).

Acceptance:

* The public 40-hex dataset revision is independently verified.
* Viewer configs, bucket content root, exact-51 coverage, and the model
  receipt are independently verified.
* Every descriptor, sparse query mode, fetch trace, attribution notice,
  and legacy raw preservation are independently verified.
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

from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    ALL_CONFIGURATION_NAMES,
    DEFAULT_CONFIGURATION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    EXACT_51_JURISDICTION_CODES,
    EXPECTED_JURISDICTION_COUNT,
)
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
    / "check_open_us_law_public_release.py"
)
_RECEIPT_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "public_canary.json"
)
_PUBLICATION_PATH = (
    _REPO_ROOT
    / "docs"
    / "reports"
    / "open_us_law_reindex"
    / "publication_receipt.json"
)
_PRODUCER_PATHS = (
    _PUBLICATION_PATH,
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "release_candidate.json",
    _REPO_ROOT
    / "docs"
    / "reports"
    / "open_us_law_reindex"
    / "prepublication_seal.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "staging_upload.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "bucket_snapshot.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "exact_51_coverage.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "embedding_receipt.json",
    _REPO_ROOT / "data" / "legal" / "open_us_law" / "source_admission.json",
    _REPO_ROOT
    / "scripts"
    / "ops"
    / "legal_data"
    / "publish_open_us_law_hf_release.py",
    _REPO_ROOT / "scripts" / "ops" / "legal_data" / "canary_open_us_law_hf_release.py",
)


def _load_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing public-release CLI: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "check_open_us_law_public_release_oul045",
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
    result = cli.check_public_release_receipt(receipt)
    assert result["ok"] is True
    assert result["task_id"] == "OUL-045"
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
    assert result["exact_51_count"] == 51
    assert result["legacy_raw_object_count"] == 107
    assert result["viewer_default"] == DEFAULT_CONFIGURATION
    assert result["model_revision"] == DEFAULT_EMBEDDING_MODEL_REVISION
    assert result["descriptor_count"] == 25

    acceptance = receipt["acceptance"]
    assert acceptance["public_40_hex_dataset_revision"] is True
    assert acceptance["viewer_configs"] is True
    assert acceptance["bucket_content_root"] is True
    assert acceptance["exact_51_coverage"] is True
    assert acceptance["model_receipt"] is True
    assert acceptance["every_descriptor"] is True
    assert acceptance["sparse_query_mode"] is True
    assert acceptance["fetch_trace"] is True
    assert acceptance["attribution_notice"] is True
    assert acceptance["legacy_raw_preservation"] is True
    assert acceptance["no_secret_or_path_leak"] is True
    assert acceptance["all_expected_outputs_required"] is True
    assert acceptance["criteria"] == cli.ACCEPTANCE_CRITERIA


def test_bound_to_public_pin(receipt: dict[str, Any], cli: ModuleType) -> None:
    publication = cli.load_publication_receipt()
    assert receipt["dataset_revision"] == publication["dataset_revision"]
    assert receipt["bucket_content_root"] == publication["bucket_release_prefix"]
    assert receipt["manifest_digest"] == publication["manifest_digest"]
    assert cli._GIT_SHA_RE.fullmatch(receipt["dataset_revision"])
    assert receipt["dataset_revision"].casefold() not in cli.PRODUCTION_REFS
    assert receipt["dataset_revision"] != publication["staging_revision"]
    assert receipt["bucket_content_root"] == f"releases/{receipt['manifest_digest']}/"
    assert receipt["publication"]["receipt_sha256"] == publication["receipt_sha256"]
    assert receipt["publication"]["identities_digest"] == publication["identities_digest"]
    assert receipt["target_repo"] == "justicedao/open-us-law-sparse-graphrag"
    assert receipt["bucket_id"] == "justicedao/open-us-law-bucket"
    assert receipt["require_public_pin"] is True


def test_public_40_hex_dataset_revision_independently_verified(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    publication = cli.load_publication_receipt()
    verified = cli.verify_public_40_hex_revision(publication)
    assert verified["ok"] is True
    assert verified["verified"] is True
    assert verified["public_revision"] == receipt["dataset_revision"]
    assert verified["public_revision_differs_from_staging"] is True
    assert len(verified["public_revision"]) == 40
    pointer = publication["pointer"]
    assert pointer["dataset_revision"] == receipt["dataset_revision"]
    for row in publication["remote_objects"]:
        assert row["dataset_object"]["revision"] == receipt["dataset_revision"]
        assert receipt["dataset_revision"] in row["dataset_object"]["object_id"]


def test_viewer_configs_independently_verified(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    viewer = cli.verify_viewer_configs()
    assert viewer["ok"] is True
    assert viewer["verified"] is True
    assert viewer["schema_coherent"] is True
    assert viewer["exactly_one_default"] is True
    assert viewer["default_config"] == DEFAULT_CONFIGURATION
    assert viewer["default_excludes_recovery"] is True
    assert viewer["default_excludes_quarantine"] is True
    assert viewer["hidden_configurations"] == ["recovery", "quarantine"]
    assert tuple(viewer["config_names"]) == ALL_CONFIGURATION_NAMES
    assert receipt["viewer"]["default_config"] == DEFAULT_CONFIGURATION
    assert receipt["viewer"]["config_names"] == list(ALL_CONFIGURATION_NAMES)
    defaults = [cfg for cfg in viewer["configs"] if cfg["default"]]
    assert len(defaults) == 1
    assert defaults[0]["name"] == DEFAULT_CONFIGURATION
    assert defaults[0]["viewer_visible"] is True
    assert defaults[0]["satisfies_exact_51_gate"] is True
    hidden = {
        cfg["name"]: cfg
        for cfg in viewer["configs"]
        if cfg["name"] in {"recovery", "quarantine"}
    }
    assert hidden["recovery"]["viewer_visible"] is False
    assert hidden["quarantine"]["viewer_visible"] is False
    assert hidden["recovery"]["satisfies_exact_51_gate"] is False


def test_bucket_content_root_independently_verified(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    publication = cli.load_publication_receipt()
    verified = cli.verify_bucket_content_root(publication)
    assert verified["ok"] is True
    assert verified["content_root"] == f"releases/{receipt['manifest_digest']}/"
    assert verified["prefix_redownload_verified"] is True
    assert verified["prefix_complete"] is True
    assert receipt["bucket_content_root"] == verified["content_root"]
    for row in publication["remote_objects"]:
        assert row["bucket_object"]["path"].startswith(verified["content_root"])
        assert row["bucket_object"]["path"] != "LATEST.json"


def test_exact_51_coverage_independently_verified(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    coverage = cli.verify_exact_51_coverage()
    assert coverage["ok"] is True
    assert coverage["verified"] is True
    assert coverage["jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    assert coverage["dc_counted_once"] is True
    assert coverage["configuration"] == DEFAULT_CONFIGURATION
    assert coverage["jurisdiction_codes"] == list(EXACT_51_JURISDICTION_CODES)
    assert coverage["jurisdiction_codes"][-1] == "DC"
    assert coverage["jurisdiction_codes"].count("DC") == 1
    assert "PR" not in coverage["jurisdiction_codes"]
    assert receipt["exact_51"]["jurisdiction_codes"] == list(EXACT_51_JURISDICTION_CODES)
    assert receipt["exact_51"]["jurisdiction_count"] == 51


def test_model_receipt_independently_verified(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    publication = cli.load_publication_receipt()
    model = cli.verify_model_receipt(publication=publication)
    assert model["ok"] is True
    assert model["verified"] is True
    assert model["model_id"] == DEFAULT_EMBEDDING_MODEL_ID
    assert model["model_revision"] == DEFAULT_EMBEDDING_MODEL_REVISION
    assert model["dimension"] == 384
    assert model["pooling"] == "mean"
    assert model["normalization"] == "l2"
    assert model["max_tokens"] == 512
    assert model["published_embeddings_descriptor"] is True
    assert model["vector_space_id"] == cli.VECTOR_SPACE_ID
    assert receipt["model"]["model_id"] == DEFAULT_EMBEDDING_MODEL_ID
    assert receipt["model"]["model_revision"] == DEFAULT_EMBEDDING_MODEL_REVISION
    assert DEFAULT_EMBEDDING_MODEL_REVISION in receipt["model"]["vector_space_id"]


def test_every_descriptor_independently_verified(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    publication = cli.load_publication_receipt()
    descriptors = cli.verify_every_descriptor(publication)
    assert descriptors["ok"] is True
    assert descriptors["verified"] is True
    assert descriptors["descriptor_count"] == 25
    assert descriptors["verified_count"] == 25
    assert descriptors["configuration_descriptor_count"] == len(ALL_CONFIGURATION_NAMES)
    assert set(descriptors["configuration_descriptors"]) == set(ALL_CONFIGURATION_NAMES)
    published = {row["relative_path"] for row in publication["remote_objects"]}
    assert set(descriptors["paths"]) == published
    assert "evidence/embeddings" in descriptors["paths"]
    assert "evidence/exact_51_coverage" in descriptors["paths"]
    assert "evidence/rights_matrix" in descriptors["paths"]
    assert receipt["descriptors"]["paths"] == descriptors["paths"]
    identities = receipt["redownload"]["public_identities"]
    assert identities["bytes_verified"] is True
    assert identities["verified_count"] == identities["file_count"]
    assert identities["file_count"] == 25
    for row in identities["files"]:
        assert row["verified"] is True
        assert cli._SHA256_RE.fullmatch(row["sha256"])
        assert row["dataset_object_id"].startswith("dataset:")
        assert row["bucket_object_id"].startswith("bucket:")
        assert receipt["dataset_revision"] in row["dataset_object_id"]
        assert receipt["manifest_digest"] in row["bucket_object_id"]


def test_sparse_query_mode_independently_verified(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    assert receipt["query_modes"] == list(QUERY_MODES)
    assert receipt["query_mode_count"] == 5
    modes = [row["mode"] for row in receipt["queries"]]
    assert modes == list(QUERY_MODES)
    by_id = {row["id"]: row for row in receipt["queries"]}
    assert by_id["bm25_foia"]["top_entry_cid"] == "entry-a"
    assert by_id["vector_centroid0"]["top_entry_cid"] == "entry-a"
    assert by_id["hybrid_foia_agency"]["top_entry_cid"] == "entry-a"
    assert by_id["graph_entry_a"]["start_node_cid"] == "entry-a"
    assert by_id["semantic_graph_entry_a"]["start_node_cid"] == "entry-a"
    for row in receipt["queries"]:
        assert row["sparse_io"] is True
        assert row["id"]
        assert row["mode"] in QUERY_MODES


def test_fetch_trace_independently_verified(receipt: dict[str, Any]) -> None:
    trace = receipt["fetch_trace"]
    assert trace["ok"] is True
    assert trace["verified"] is True
    assert trace["credential_free"] is True
    assert trace["local_path_free"] is True
    assert trace["full_index_downloaded"] is False
    assert trace["query_count"] == 5
    assert {row["mode"] for row in trace["queries"]} == set(QUERY_MODES)
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
    assert "data/bm25/postings/part-000001.parquet" in set(
        trace["unused_siblings_not_fetched"]
    )


def test_attribution_notice_independently_verified(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    attribution = cli.verify_attribution_notice()
    assert attribution["ok"] is True
    assert attribution["verified"] is True
    assert attribution["required"] is True
    assert attribution["jurisdiction_count"] == 51
    assert attribution["notice_count"] == 51
    codes = [row["jurisdiction_code"] for row in attribution["notices"]]
    assert codes == list(EXACT_51_JURISDICTION_CODES)
    for row in attribution["notices"]:
        assert row["required"] is True
        assert row["currentness_disclaimer_required"] is True
        assert "official" in row["notice"].casefold()
        assert len(row["notice"]) >= 24
    assert "not a substitute for the official source" in attribution[
        "currentness_disclaimer"
    ].casefold()
    assert receipt["attribution"]["notice_count"] == 51
    assert receipt["attribution"]["required"] is True
    assert receipt["attribution"]["notices"][0]["jurisdiction_code"] == "AL"
    assert receipt["attribution"]["notices"][-1]["jurisdiction_code"] == "DC"


def test_legacy_raw_preservation_independently_verified(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    publication = cli.load_publication_receipt()
    legacy = cli.verify_legacy_raw_preservation(publication)
    assert legacy["ok"] is True
    assert legacy["verified"] is True
    assert legacy["object_count"] == 107
    assert legacy["raw_root_untouched"] is True
    assert legacy["root_raw_object_overwritten"] is False
    assert legacy["deletion_occurred"] is False
    assert "README.md" in legacy["protected_raw_root_present"]
    assert "SHA256SUMS.json" in legacy["protected_raw_root_present"]
    assert legacy["raw_parquet_count"] >= 90
    assert receipt["legacy_raw"]["object_count"] == 107
    assert receipt["legacy_raw"]["raw_root_untouched"] is True
    assert publication["raw_bucket_root_untouched"] is True
    assert publication["raw_bucket_root_object_count"] == 107


def test_no_local_artifact_fallback(receipt: dict[str, Any], cli: ModuleType) -> None:
    assert receipt["transport"] == "isolated_recorded_public_store"
    assert receipt["isolated_transport"] is True
    assert receipt["redownload"]["transport"] == "isolated_recorded_public_store"
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


def test_mapping_transport_is_required_for_queries(
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


def test_canary_is_deterministic(cli: ModuleType) -> None:
    first = cli.build_default_public_canary()
    second = cli.build_default_public_canary()
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert first["dataset_revision"] == second["dataset_revision"]
    assert first["queries"] == second["queries"]
    assert first["redownload"]["public_identities"] == second["redownload"][
        "public_identities"
    ]
    assert first["viewer"] == second["viewer"]
    assert first["exact_51"] == second["exact_51"]
    assert first["model"] == second["model"]


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


def test_main_require_public_pin_check(
    cli: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.materialize_default_receipt()
    rc = cli.main(["--require-public-pin", "--check"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["task_id"] == "OUL-045"
    assert payload["mismatches"] == []
    assert payload["require_public_pin"] is True
    assert payload["local_artifact_fallback"] is False
    assert len(payload["dataset_revision"]) == 40
    assert payload["exact_51_count"] == 51
    assert payload["legacy_raw_object_count"] == 107


def test_check_receipt_detects_drift(cli: ModuleType, receipt: dict[str, Any]) -> None:
    tampered = copy.deepcopy(receipt)
    tampered["dataset_revision"] = "0" * 40
    tampered["receipt_sha256"] = cli.digest_mapping(
        {key: value for key, value in tampered.items() if key != "receipt_sha256"}
    )
    with pytest.raises((cli.StaleInputError, cli.MismatchError, cli.PublicPinError)):
        cli.check_public_release_receipt(tampered)


def test_further_publication_never_authorized(receipt: dict[str, Any]) -> None:
    assert receipt["publication_authorized"] is False
    assert receipt["public_mutation_authorized"] is False
    assert receipt["live_network"] is False
    assert receipt["network_required"] is False
    assert receipt["tokens_used"] is False


def test_on_disk_receipt_matches_builder(receipt: dict[str, Any]) -> None:
    on_disk = json.loads(_RECEIPT_PATH.read_text(encoding="utf-8"))
    assert on_disk["receipt_sha256"] == receipt["receipt_sha256"]
    assert on_disk["task_id"] == "OUL-045"
    assert on_disk["schema"] == "ipfs_datasets_py/open-us-law-public-canary@1"
    assert on_disk["acceptance"]["criteria"] == receipt["acceptance"]["criteria"]


def test_independent_verifiers_fail_closed(cli: ModuleType) -> None:
    publication = cli.load_publication_receipt()
    broken_revision = copy.deepcopy(publication)
    broken_revision["dataset_revision"] = publication["staging_revision"]
    with pytest.raises(cli.PublicPinError):
        cli.verify_public_40_hex_revision(broken_revision)

    broken_root = copy.deepcopy(publication)
    broken_root["bucket_release_prefix"] = "releases/not-the-manifest/"
    with pytest.raises(cli.PublicPinError):
        cli.verify_bucket_content_root(broken_root)

    broken_legacy = copy.deepcopy(publication)
    broken_legacy["raw_bucket_root_untouched"] = False
    with pytest.raises(cli.PublicLegacyError):
        cli.verify_legacy_raw_preservation(broken_legacy)

    broken_descriptors = copy.deepcopy(publication)
    broken_descriptors["remote_objects"] = publication["remote_objects"][:-1]
    with pytest.raises(cli.PublicDescriptorError):
        cli.verify_every_descriptor(broken_descriptors)
