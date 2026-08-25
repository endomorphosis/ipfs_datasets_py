"""Unit tests for Open US Law operations rehearsal (OUL-047).

Acceptance:

* Rollback repoints without deleting immutable releases.
* Quarterly delta builds preserve identities and rebuild affected indexes.
* Interrupted uploads resume safely.
* All refill findings are completed and prior public pins remain queryable.
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
    REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_sparse_graphrag import (
    QUERY_MODES,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = (
    _REPO_ROOT
    / "scripts"
    / "ops"
    / "legal_data"
    / "rehearse_open_us_law_operations.py"
)
_RECEIPT_PATH = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "operations_rehearsal.json"
)
_PRODUCER_PATHS = (
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "publication_receipt.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "public_canary.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "public_benchmark.json",
    _REPO_ROOT
    / "docs"
    / "reports"
    / "open_us_law_reindex"
    / "acquisition_refill_closure.json",
    _REPO_ROOT / "docs" / "reports" / "open_us_law_reindex" / "exact_51_coverage.json",
)


def _load_module() -> ModuleType:
    assert _SCRIPT_PATH.is_file(), f"missing operations rehearsal CLI: {_SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location(
        "rehearse_open_us_law_operations_oul047",
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
    payload, path = cli.materialize_default_report()
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)
    assert on_disk["task_id"] == payload["task_id"]
    assert on_disk["receipt_sha256"] == payload["receipt_sha256"]
    return payload


def test_script_and_dependencies_exist() -> None:
    assert _SCRIPT_PATH.is_file()
    for path in _PRODUCER_PATHS:
        assert path.is_file(), f"missing producer input: {path}"


def test_help_exits_zero(cli: ModuleType) -> None:
    assert cli.main(["--help"]) == 0


def test_fixture_receipt_acceptance(receipt: dict[str, Any], cli: ModuleType) -> None:
    result = cli.check_operations_rehearsal(receipt)
    assert result["ok"] is True
    assert result["task_id"] == "OUL-047"
    assert result["goal_id"] == "OUL-G090"
    assert result["publication_authorized"] is False
    assert result["mutation_executed"] is False
    assert result["no_mutate"] is True
    assert result["mismatches"] == []
    assert result["refill_unresolved_count"] == 0
    assert len(result["prior_dataset_revision"]) == 40
    assert len(result["quarterly_dataset_revision"]) == 40
    assert result["prior_dataset_revision"] != result["quarterly_dataset_revision"]

    acceptance = receipt["acceptance"]
    assert acceptance["rollback_repoints_without_deleting_immutable_releases"] is True
    assert acceptance["quarterly_delta_preserves_identities"] is True
    assert acceptance["quarterly_delta_rebuilds_affected_indexes"] is True
    assert acceptance["interrupted_uploads_resume_safely"] is True
    assert acceptance["all_refill_findings_completed"] is True
    assert acceptance["prior_public_pins_remain_queryable"] is True
    assert acceptance["no_deletion"] is True
    assert acceptance["no_secret_or_path_leak"] is True
    assert acceptance["all_expected_outputs_required"] is True
    assert acceptance["pointer_updated_last"] is True
    assert acceptance["no_root_raw_object_overwritten"] is True
    assert acceptance["mutation_not_executed"] is True
    assert acceptance["criteria"] == cli.ACCEPTANCE_CRITERIA


def test_sealed_report_on_disk_matches(receipt: dict[str, Any], cli: ModuleType) -> None:
    assert _RECEIPT_PATH.is_file()
    on_disk = json.loads(_RECEIPT_PATH.read_text(encoding="utf-8"))
    assert cli.compare_receipts(receipt, on_disk) == []
    result = cli.check_operations_rehearsal(on_disk)
    assert result["ok"] is True


def test_bound_to_public_pin(receipt: dict[str, Any], cli: ModuleType) -> None:
    publication = cli.load_publication_receipt()
    prior = receipt["prior_public_pin"]
    assert prior["dataset_revision"] == publication["dataset_revision"]
    assert prior["bucket_prefix"] == publication["bucket_release_prefix"]
    assert prior["manifest_digest"] == publication["manifest_digest"]
    assert prior["receipt_sha256"] == publication["receipt_sha256"]
    assert prior["identities_digest"] == publication["identities_digest"]
    assert prior["task_id"] == "OUL-044"
    assert cli._GIT_SHA_RE.fullmatch(prior["dataset_revision"])
    assert prior["dataset_revision"].casefold() not in cli.PRODUCTION_REFS
    assert prior["bucket_prefix"] == f"releases/{prior['manifest_digest']}/"
    assert prior["dataset_id"] == "justicedao/open-us-law-sparse-graphrag"
    assert prior["bucket_id"] == "justicedao/open-us-law-bucket"
    canary = receipt["public_canary"]
    assert canary["dataset_revision"] == prior["dataset_revision"]
    assert canary["require_public_pin"] is True


def test_rollback_repoints_without_deleting_immutable_releases(
    receipt: dict[str, Any],
) -> None:
    rollback = receipt["rollback"]
    prior = receipt["prior_public_pin"]
    quarterly = receipt["quarterly"]

    assert rollback["path"] == "rollback"
    assert rollback["status"] == "rehearsed"
    assert rollback["ok"] is True
    assert rollback["deletion_performed"] is False
    assert rollback["legacy_files_deleted"] is False
    assert rollback["candidate_tree_retained"] is True
    assert rollback["force_push_performed"] is False
    assert rollback["visibility_changed"] is False
    assert rollback["pointer_updated_last"] is True
    assert rollback["pointer_path"] == "LATEST.json"
    assert rollback["prior_advertised_revision"] == prior["dataset_revision"]
    assert rollback["prior_bucket_prefix"] == prior["bucket_prefix"]
    assert rollback["prior_manifest_digest"] == prior["manifest_digest"]
    advertised = rollback["advertised_mapping"]
    assert advertised["dataset_revision"] == prior["dataset_revision"]
    assert advertised["bucket_prefix"] == prior["bucket_prefix"]
    assert advertised["manifest_sha256"] == prior["manifest_digest"]
    assert rollback["quarterly_prefix_retained"] == quarterly["bucket_prefix"]
    assert rollback["quarterly_revision_retained"] == quarterly["dataset_revision"]
    assert prior["bucket_prefix"] in rollback["retained_prefixes"]
    assert quarterly["bucket_prefix"] in rollback["retained_prefixes"]
    assert rollback.get("deleted_prefixes", []) == []
    assert "delete" not in json.dumps(rollback["advertised_mapping"])


def test_quarterly_delta_preserves_identities_and_rebuilds_indexes(
    receipt: dict[str, Any], cli: ModuleType
) -> None:
    quarterly = receipt["quarterly"]
    prior = receipt["prior_public_pin"]
    assert quarterly["ok"] is True
    assert quarterly["status"] == "rehearsed"
    assert quarterly["window"] == "2026-Q3"
    assert quarterly["affected_jurisdictions"] == ["CA"]
    assert quarterly["affected_indexes"] == ["bm25", "vectors", "graph"]
    assert "corpus/root" in quarterly["reused_relative_paths"]
    assert "bm25/index_root" in quarterly["rebuilt_relative_paths"]
    assert "vectors/index_root" in quarterly["rebuilt_relative_paths"]
    assert "graph/adjacency" in quarterly["rebuilt_relative_paths"]
    assert quarterly["dataset_revision"] != prior["dataset_revision"]
    assert quarterly["manifest_digest"] != prior["manifest_digest"]
    assert quarterly["bucket_prefix"] == f"releases/{quarterly['manifest_digest']}/"
    assert quarterly["bucket_prefix"] != prior["bucket_prefix"]
    assert len(quarterly["dataset_revision"]) == 40
    assert len(quarterly["manifest_digest"]) == 64
    assert quarterly["pointer_updated_last"] is True
    assert quarterly["prior_pin_retained"]["prefix_present"] is True
    assert quarterly["prior_pin_retained"]["revision_present"] is True
    assert quarterly["prior_pin_retained"]["dataset_revision"] == prior["dataset_revision"]

    identities = quarterly["identities"]
    assert identities["ok"] is True
    assert identities["preserved_count"] == 2
    assert identities["rebuilt_count"] == 1
    assert any(legal_id.startswith("oul:al:") for legal_id in identities["preserved_legal_ids"])
    assert any(legal_id.startswith("oul:dc:") for legal_id in identities["preserved_legal_ids"])
    assert any(legal_id.startswith("oul:ca:") for legal_id in identities["rebuilt_legal_ids"])

    prior_rows = cli.prior_identity_rows()
    delta = cli.apply_quarterly_observation(prior_rows)
    compared = cli.compare_identity_preservation(prior_rows, delta["rows"])
    assert compared["ok"] is True
    by_code = {row["jurisdiction_code"]: row for row in delta["rows"]}
    prior_by_code = {row["jurisdiction_code"]: row for row in prior_rows}
    for code in ("AL", "DC"):
        for field in REQUIRED_DEFAULT_STATUTE_IDENTITY_FIELDS:
            assert by_code[code][field] == prior_by_code[code][field]
    assert by_code["CA"]["legal_id"] == prior_by_code["CA"]["legal_id"]
    assert by_code["CA"]["hierarchy"] == prior_by_code["CA"]["hierarchy"]
    assert by_code["CA"]["edition"] == prior_by_code["CA"]["edition"]
    assert by_code["CA"]["text_hash"] != prior_by_code["CA"]["text_hash"]
    assert by_code["CA"]["source_cid"] != prior_by_code["CA"]["source_cid"]
    assert by_code["CA"]["entry_cid"] != prior_by_code["CA"]["entry_cid"]


def test_interrupted_uploads_resume_safely(receipt: dict[str, Any], cli: ModuleType) -> None:
    resume = receipt["resume"]
    assert resume["ok"] is True
    assert resume["resumed_safely"] is True
    assert resume["status"] == "resumed"
    assert resume["interrupt_after"] == cli.INTERRUPT_AFTER
    assert resume["first_pass"]["interrupted"] is True
    assert resume["first_pass"]["pointer_still_prior"] is True
    assert resume["first_pass"]["uploaded_count"] == cli.INTERRUPT_AFTER
    assert resume["resume_pass"]["interrupted"] is False
    assert resume["resume_pass"]["skipped_count"] == cli.INTERRUPT_AFTER
    assert resume["resume_pass"]["uploaded_count"] == (
        len(cli.QUARTERLY_RELATIVE_PATHS) - cli.INTERRUPT_AFTER
    )
    assert resume["prefix_complete"] is True
    assert resume["redownload"]["verified"] is True
    skipped = resume["resume_pass"]["skipped_paths"]
    uploaded = resume["resume_pass"]["uploaded_paths"]
    assert skipped == list(cli.QUARTERLY_RELATIVE_PATHS[: cli.INTERRUPT_AFTER])
    assert uploaded == list(cli.QUARTERLY_RELATIVE_PATHS[cli.INTERRUPT_AFTER :])
    assert "delete" in resume["forbidden_operations"]
    assert "overwrite_prior_prefix" in resume["forbidden_operations"]


def test_all_refill_findings_completed(receipt: dict[str, Any], cli: ModuleType) -> None:
    refill = receipt["refill_closure"]
    closure = cli.load_refill_closure()
    verified = cli.rehearse_refill_closure(closure)
    assert refill["ok"] is True
    assert refill["task_id"] == "OUL-023"
    assert refill["every_finding_terminal"] is True
    assert refill["unresolved_count"] == 0
    assert refill["unresolved_finding_ids"] == []
    assert refill["finding_count"] == closure["finding_count"]
    assert refill["finding_count"] == 260
    assert refill["completed_repair_count"] == 255
    assert refill["typed_terminal_quarantine_count"] == 5
    assert (
        refill["completed_repair_count"] + refill["typed_terminal_quarantine_count"]
        == refill["finding_count"]
    )
    assert verified["finding_count"] == refill["finding_count"]
    assert refill["path"] == "docs/reports/open_us_law_reindex/acquisition_refill_closure.json"
    assert not refill["path"].startswith("/")


def test_prior_public_pins_remain_queryable(receipt: dict[str, Any]) -> None:
    queries = receipt["queries"]
    assert queries["ok"] is True
    assert queries["prior_pin_queryable_after_rollback"] is True
    assert queries["quarterly_pin_queryable_after_rollback"] is True
    assert queries["canary_bound_to_prior_pin"] is True
    assert queries["used_mutable_pointer"] is False
    assert queries["query_mode_count"] == 5
    pins = {row["kind"]: row for row in queries["pins"]}
    assert pins["prior_public"]["queryable"] is True
    assert pins["quarterly_delta"]["queryable"] is True
    assert pins["prior_public"]["dataset_revision"] == receipt["prior_public_pin"][
        "dataset_revision"
    ]
    assert pins["quarterly_delta"]["dataset_revision"] == receipt["quarterly"][
        "dataset_revision"
    ]
    assert pins["prior_public"]["modes"] == list(QUERY_MODES)
    assert pins["quarterly_delta"]["modes"] == list(QUERY_MODES)
    assert pins["prior_public"]["bucket_prefix"] != pins["quarterly_delta"]["bucket_prefix"]


def test_no_mutate_check_cli(receipt: dict[str, Any], cli: ModuleType) -> None:
    assert cli.main(["--no-mutate", "--check"]) == 0


def test_authorize_mutation_refused(cli: ModuleType) -> None:
    assert cli.main(["--authorize-mutation"]) == 2


def test_rehearsal_is_deterministic(cli: ModuleType) -> None:
    first = cli.build_operations_rehearsal()
    second = cli.build_operations_rehearsal()
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert first["quarterly"]["dataset_revision"] == second["quarterly"]["dataset_revision"]
    assert first["rollback"]["advertised_mapping"] == second["rollback"]["advertised_mapping"]


def test_report_has_no_secret_or_path_leak(receipt: dict[str, Any], cli: ModuleType) -> None:
    cli.reject_credentials_in_payload(receipt, label="test_rehearsal")
    cli.reject_path_leaks(receipt, label="test_rehearsal")
    rendered = json.dumps(receipt)
    assert "hf_token" not in rendered.casefold()
    assert "access_token" not in rendered.casefold()
    assert "bearer " not in rendered.casefold()
    assert "/home/" not in rendered
    assert "file://" not in rendered.casefold()
    assert "C:\\Users" not in rendered
    assert str(_REPO_ROOT) not in rendered
    assert not receipt["prior_public_pin"]["path"].startswith("/")
    assert not receipt["public_canary"]["path"].startswith("/")
    assert not receipt["refill_closure"]["path"].startswith("/")


def test_path_leak_rejected(cli: ModuleType) -> None:
    with pytest.raises(cli.PathLeakError):
        cli.reject_path_leaks(
            {"candidate": {"root_label": "/home/operator/secret-tree"}},
            label="test",
        )


def test_credentials_in_payload_rejected(cli: ModuleType) -> None:
    with pytest.raises(cli.SecretLeakError):
        cli.reject_credentials_in_payload(
            {"plan_digest": "x", "hf_token": "hf_should_not_appear_here_12345"},
            label="test",
        )


def test_secrets_on_argv_rejected(cli: ModuleType) -> None:
    with pytest.raises(cli.SecretLeakError):
        cli.reject_secrets_in_argv(
            ["--hf_token=hf_secretvalue1234567890", "--no-mutate"]
        )
    with pytest.raises(cli.SecretLeakError):
        cli.reject_secrets_in_argv(["Authorization: Bearer abc", "--check"])


def test_mutable_revision_rejected(cli: ModuleType) -> None:
    for value in ("main", "latest", "HEAD", "staging", "canary", ""):
        with pytest.raises((cli.MismatchError, ValueError, RuntimeError)):
            cli.require_immutable_public_revision(value)


def test_store_refuses_delete(cli: ModuleType) -> None:
    store = cli.IsolatedOperationsStore()
    with pytest.raises(cli.OperationsSafetyError):
        store.refuse_delete("releases/abc/")


def test_store_refuses_raw_root_and_prior_prefix(receipt: dict[str, Any], cli: ModuleType) -> None:
    publication = cli.load_publication_receipt()
    store = cli.IsolatedOperationsStore()
    cli.seed_store_from_publication(store, publication)
    digest = "ab" * 32
    with pytest.raises(cli.OperationsSafetyError):
        store.add_bucket(
            bucket_id="justicedao/open-us-law-bucket",
            path="README.md",
            sha256=digest,
        )
    with pytest.raises(cli.OperationsSafetyError):
        store.add_bucket(
            bucket_id="justicedao/open-us-law-bucket",
            path=f"{publication['bucket_release_prefix']}manifest.json",
            sha256=digest,
        )
    with pytest.raises(cli.OperationsSafetyError):
        store.add_bucket(
            bucket_id="justicedao/open-us-law-bucket",
            path="LATEST.json",
            sha256=digest,
        )


def test_store_resume_skips_matching_and_rejects_drift(cli: ModuleType) -> None:
    store = cli.IsolatedOperationsStore()
    store.seed_raw_root()
    revision = "a" * 40
    prefix = "releases/" + ("b" * 64) + "/"
    store.begin_prefix(prefix=prefix)
    first = store.add_dataset(
        repo_id="justicedao/open-us-law-sparse-graphrag",
        revision=revision,
        path="manifest.json",
        sha256="c" * 64,
    )
    assert first["skipped"] is False
    again = store.add_dataset(
        repo_id="justicedao/open-us-law-sparse-graphrag",
        revision=revision,
        path="manifest.json",
        sha256="c" * 64,
    )
    assert again["skipped"] is True
    with pytest.raises(cli.OperationsSafetyError):
        store.add_dataset(
            repo_id="justicedao/open-us-law-sparse-graphrag",
            revision=revision,
            path="manifest.json",
            sha256="d" * 64,
        )


def test_pointer_update_refused_before_prefix_complete(cli: ModuleType) -> None:
    store = cli.IsolatedOperationsStore()
    store.seed_raw_root()
    store.begin_prefix(prefix="releases/" + ("e" * 64) + "/")
    with pytest.raises(cli.OperationsSafetyError):
        store.update_pointer(
            cli.build_pointer_document(
                dataset_revision="f" * 40,
                manifest_digest="e" * 64,
            )
        )


def test_drifted_receipt_fails_check(receipt: dict[str, Any], cli: ModuleType) -> None:
    drifted = copy.deepcopy(receipt)
    drifted["rollback"]["deletion_performed"] = True
    with pytest.raises((cli.OperationsSafetyError, cli.MismatchError, cli.StaleInputError)):
        cli.check_operations_rehearsal(drifted)


def test_nonterminal_refill_fails(cli: ModuleType) -> None:
    closure = cli.load_refill_closure()
    broken = copy.deepcopy(closure)
    broken["findings"][0]["terminal"] = False
    with pytest.raises(cli.RefillClosureError):
        cli.rehearse_refill_closure(broken)
    broken = copy.deepcopy(closure)
    broken["repair_summary"]["unresolved_count"] = 1
    with pytest.raises(cli.RefillClosureError):
        cli.rehearse_refill_closure(broken)


def test_receipt_never_authorizes_mutation(receipt: dict[str, Any]) -> None:
    assert receipt["publication_authorized"] is False
    assert receipt["public_mutation_authorized"] is False
    assert receipt["mutation_authorized"] is False
    assert receipt["mutation_executed"] is False
    assert receipt["live_network"] is False
    assert receipt["network_required"] is False
    assert receipt["remote_write_contacted"] is False
    assert receipt["no_mutate"] is True
    assert receipt["dry_run"] is True
    assert receipt["task_id"] == "OUL-047"
    assert receipt["goal_id"] == "OUL-G090"
    assert receipt["schema"] == "ipfs_datasets_py/open-us-law-operations-rehearsal@1"
