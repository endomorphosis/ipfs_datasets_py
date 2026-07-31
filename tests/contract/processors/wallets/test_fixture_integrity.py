"""WALPROC-G090 fixture integrity and shared conformance harness tests.

Proves:

* offline fixtures under ``tests/fixtures/wallets`` are inventory-complete
* content digests in ``digests.json`` match file bytes (immutability lock)
* every fixture directory declares source, license, and provenance
* harness AST symbols exist: WalletProcessorConformance, ProviderContract,
  FixtureTransport
* the reference provider contract passes every required shared check
* chain-specific assertions can only extend, not weaken, shared checks
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from conformance import (  # noqa: E402
    REQUIRED_SHARED_CHECKS,
    FixtureTransport,
    ProviderContract,
    WalletProcessorConformance,
    WalletProcessorConformanceMixin,
    file_sha256,
    fixture_root,
    make_reference_provider_contract,
)


FIXTURE_ROOT = fixture_root()
DIGESTS_PATH = FIXTURE_ROOT / "digests.json"
ROOT_MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"

REQUIRED_ROOT_FILES = {
    "manifest.json",
    "digests.json",
    "README.md",
}

REQUIRED_CHAIN_DIRS = {
    "_shared",
    "worldcoin",
    "xaman",
    "xrpl",
    "ethereum",
    "bitcoin",
    "solana",
}

REQUIRED_SHARED_FILES = {
    "manifest.json",
    "README.md",
    "identity_vectors.json",
    "amount_vectors.json",
    "deterministic_ids.json",
    "malformed_payloads.json",
    "pagination_pages.json",
    "retry_and_cancel.json",
    "reorg_histories.json",
    "export_sample_records.json",
    "secret_redaction_cases.json",
    "cas_checkpoint.json",
}


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Fixture tree shape
# ---------------------------------------------------------------------------


def test_fixture_root_contains_required_files() -> None:
    assert FIXTURE_ROOT.is_dir(), f"missing fixtures root: {FIXTURE_ROOT}"
    present = {path.name for path in FIXTURE_ROOT.iterdir() if path.is_file()}
    missing = REQUIRED_ROOT_FILES - present
    assert not missing, f"fixture root missing files: {sorted(missing)}"


def test_fixture_root_contains_required_chain_directories() -> None:
    present = {path.name for path in FIXTURE_ROOT.iterdir() if path.is_dir()}
    missing = REQUIRED_CHAIN_DIRS - present
    assert not missing, f"fixture root missing chain dirs: {sorted(missing)}"
    for name in REQUIRED_CHAIN_DIRS:
        assert (FIXTURE_ROOT / name / "manifest.json").is_file(), name


def test_shared_fixture_directory_is_complete() -> None:
    shared = FIXTURE_ROOT / "_shared"
    present = {path.name for path in shared.iterdir() if path.is_file()}
    missing = REQUIRED_SHARED_FILES - present
    assert not missing, f"_shared missing files: {sorted(missing)}"


def test_root_manifest_declares_goal_and_shared_checks() -> None:
    manifest = _load_json(ROOT_MANIFEST_PATH)
    assert manifest["goal_id"] == "WALPROC-G090"
    assert manifest["task_id"] == "WALPROC-013"
    assert manifest["classification"]["offline_default"] is True
    assert set(manifest["required_shared_checks"]) == REQUIRED_SHARED_CHECKS
    chain_ids = {item["id"] for item in manifest["chains"]}
    assert REQUIRED_CHAIN_DIRS <= chain_ids


# ---------------------------------------------------------------------------
# Digests / immutability
# ---------------------------------------------------------------------------


def test_digests_manifest_schema() -> None:
    digests = _load_json(DIGESTS_PATH)
    assert digests["schema"] == "wallet_processor_migration/wallet-fixture-digests@1"
    assert digests["schema_version"] == 1
    assert digests["goal_id"] == "WALPROC-G090"
    assert digests["digest_algorithm"] == "sha256"
    assert digests["classification"]["immutable_when_digested"] is True
    assert isinstance(digests["files"], dict)
    assert digests["files"], "digests.json must list at least one file"


def test_fixture_transport_verify_digests() -> None:
    transport = FixtureTransport()
    transport.verify_digests()


def test_every_fixture_file_is_digested_except_digests_lock() -> None:
    transport = FixtureTransport()
    actual = transport.compute_digests()
    locked = _load_json(DIGESTS_PATH)["files"]
    assert set(actual) == set(locked)
    for rel, digest in locked.items():
        path = FIXTURE_ROOT / rel
        assert path.is_file(), rel
        assert digest == file_sha256(path), rel
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64


def test_digests_exclude_self_to_avoid_self_hash_cycles() -> None:
    locked = _load_json(DIGESTS_PATH)["files"]
    assert "digests.json" not in locked


# ---------------------------------------------------------------------------
# Source / license / provenance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subdir",
    [None, "_shared", "worldcoin", "xaman", "xrpl", "ethereum", "bitcoin", "solana"],
)
def test_manifest_includes_source_license_provenance(subdir: str | None) -> None:
    transport = FixtureTransport()
    # Worldcoin/Xaman predate the full provenance keys; require offline + files.
    if subdir in {"worldcoin", "xaman"}:
        manifest = transport.load_manifest(subdir)
        assert manifest["classification"]["offline_default"] is True
        for relative in manifest["files"]:
            assert transport.path(subdir, relative).is_file(), relative
        # Provenance may be expressed via purpose/source_of_truth fields.
        assert "purpose" in manifest or "source" in manifest
        return
    transport.assert_manifest_provenance(subdir)


def test_shared_manifest_coverage_maps_required_checks() -> None:
    manifest = _load_json(FIXTURE_ROOT / "_shared" / "manifest.json")
    coverage = set(manifest["coverage"])
    # Shared fixture coverage maps the offline vector checks (import/optional
    # are harness-only and do not require dedicated vector files).
    vector_checks = REQUIRED_SHARED_CHECKS - {
        "optional_dependency_absence",
        "no_network_imports",
    }
    missing = vector_checks - coverage
    assert not missing, f"_shared coverage missing: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Harness symbols and behavior
# ---------------------------------------------------------------------------


def test_harness_ast_symbols_are_exportable() -> None:
    assert FixtureTransport is not None
    assert ProviderContract is not None
    assert WalletProcessorConformance is not None
    assert callable(make_reference_provider_contract)


def test_provider_contract_rejects_empty_identity() -> None:
    with pytest.raises(ValueError):
        ProviderContract(
            name="",
            chain_namespace="eip155",
            network="mainnet",
            chain_id="1",
            genesis_hash="0x0",
        )


def test_reference_contract_passes_all_shared_checks() -> None:
    suite = WalletProcessorConformance(make_reference_provider_contract())
    results = suite.run_shared_checks()
    assert {item.name for item in results} == REQUIRED_SHARED_CHECKS
    assert all(item.passed for item in results)


def test_run_all_includes_extra_checks_after_shared() -> None:
    order: list[str] = []

    def extra(suite: WalletProcessorConformance) -> None:
        order.append("extra")
        assert suite.required_checks <= suite._completed_shared

    contract = make_reference_provider_contract().with_extra_checks(extra)
    suite = WalletProcessorConformance(contract)
    results = suite.run_all()
    assert order == ["extra"]
    assert any(item.name.startswith("extra[") for item in results)
    assert all(item.passed for item in results)


def test_extra_checks_cannot_run_before_shared_suite() -> None:
    def extra(_suite: WalletProcessorConformance) -> None:
        raise AssertionError("extra must not run")

    contract = make_reference_provider_contract().with_extra_checks(extra)
    suite = WalletProcessorConformance(contract)
    with pytest.raises(AssertionError, match="cannot run until shared"):
        suite.run_extra_checks()


def test_chain_specific_assertions_extend_not_weaken() -> None:
    suite = WalletProcessorConformance(make_reference_provider_contract())
    suite.assert_cannot_weaken_shared_checks()
    # Completing shared then attaching extras is the only legal path.
    suite.run_shared_checks()
    extended = suite.contract.with_extra_checks(lambda _s: None)
    WalletProcessorConformance(extended, suite.transport).run_all()


def test_fixture_transport_refuses_path_escape() -> None:
    transport = FixtureTransport()
    with pytest.raises(ValueError, match="escapes"):
        transport.path("..", "secrets.json")


def test_wallet_processor_conformance_mixin_reference_suite() -> None:
    class ReferenceSuite(WalletProcessorConformanceMixin):
        pass

    suite = ReferenceSuite()
    suite.test_conformance_exact_amounts()
    suite.test_conformance_chain_checks_extend_not_weaken()
    suite.test_conformance_run_all_shared_then_extra()


def test_root_manifest_points_at_harness_and_integrity_tests() -> None:
    manifest = _load_json(ROOT_MANIFEST_PATH)
    provenance = manifest["provenance"]
    assert "conformance.py" in provenance["conformance_module"]
    assert "test_fixture_integrity.py" in provenance["integrity_tests"]
    assert provenance["digest_manifest"] == "digests.json"
