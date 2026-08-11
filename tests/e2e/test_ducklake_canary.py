"""E2E tests: DuckLake shadow and distributed canary (DQK-099).

Acceptance coverage:

* Every representative domain passes schema, row, identity, snapshot,
  performance, security, and restore parity using the final domain-producer
  lineage consumed by DQK-053
* The canary inspects every non-bootstrap or non-migration ATTACH and proves
  CREATE_IF_NOT_EXISTS=false, OVERRIDE_DATA_PATH=false, and
  AUTOMATIC_MIGRATION=false
* Concurrent writes and analytical scans preserve control heartbeat SLOs
* Failure rolls back or quarantines one dataset without deleting source files
* The canary proves the Quack beta feature gate and local fallback, and emits
  the exact DQK-050 compatibility/risk receipt
* The canary emits a database-native DuckLakeCanaryReceipt@1

Hermetic: no live DuckDB, Quack, Docker, or network required. The owned canary
lives in ``scripts/ops/ducklake_canary.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()
_CANARY_PATH = _REPO_ROOT / "scripts/ops/ducklake_canary.py"


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _load_canary_module() -> ModuleType:
    """Load the ops canary without requiring scripts.ops package install."""

    module_name = "ducklake_canary"
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "CONTRACT_TASK_ID", None) == "DQK-099":
        return existing
    if not _CANARY_PATH.is_file():
        raise AssertionError(
            f"owned canary module missing at {_CANARY_PATH}; "
            "validation suite fails rather than skips"
        )
    spec = importlib.util.spec_from_file_location(module_name, _CANARY_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load canary module from {_CANARY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


canary = _load_canary_module()

from ipfs_datasets_py.ducklake import adapters as ad  # noqa: E402
from ipfs_datasets_py.ducklake import capabilities as lake_caps  # noqa: E402
from ipfs_datasets_py.ducklake.config import AttachMode, build_attach_options  # noqa: E402
from ipfs_datasets_py.duckdb_control import capabilities as control_caps  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_canary_store() -> None:
    canary.reset_default_canary_store()
    yield
    canary.reset_default_canary_store()


@pytest.fixture(scope="module")
def install_report() -> dict[str, Any]:
    return dict(canary.install_check())


# ---------------------------------------------------------------------------
# Module contract / install
# ---------------------------------------------------------------------------


def test_canary_module_contract_constants() -> None:
    assert canary.CONTRACT_TASK_ID == "DQK-099"
    assert canary.CONSUMED_BY_TASK_ID == "DQK-053"
    assert canary.COMPATIBILITY_TASK_ID == "DQK-050"
    assert canary.CANARY_RECEIPT_INTERFACE == "DuckLakeCanaryReceipt@1"
    assert canary.CANARY_RECEIPT_SCHEMA.endswith("@1")
    assert canary.STORE_TABLE == "lake_canary_receipts"
    assert set(canary.PARITY_DIMENSIONS) == {
        "schema",
        "row",
        "identity",
        "snapshot",
        "performance",
        "security",
        "restore",
    }
    assert "admission" in canary.PIPELINE_PHASES
    assert "rollback" in canary.PIPELINE_PHASES
    assert canary.SAFE_ATTACH_FLAGS == {
        "CREATE_IF_NOT_EXISTS": False,
        "OVERRIDE_DATA_PATH": False,
        "AUTOMATIC_MIGRATION": False,
    }


def test_install_check_reports_representative_domains(
    install_report: dict[str, Any],
) -> None:
    assert install_report["ok"] is True
    assert install_report["owner_task_id"] == "DQK-099"
    assert install_report["consumed_by"] == "DQK-053"
    domains = set(install_report["representative_domains"])
    assert domains == {
        "knowledge-graph",
        "vector",
        "proof-evidence",
        "ast",
        "wallet-public",
        "legal",
        "general",
    }
    assert install_report["legacy_producers_remain_shadow_projections"] is True
    assert install_report["interface"] == "DuckLakeCanaryReceipt@1"
    assert install_report["database_native_table"] == "lake_canary_receipts"
    assert install_report["dqk050_contract"] == "DQK-050"


# ---------------------------------------------------------------------------
# Domain-producer lineage (consumed by DQK-053)
# ---------------------------------------------------------------------------


def test_domain_producer_lineage_uses_registered_producers() -> None:
    lineage = canary.domain_lineage_receipt()
    assert lineage["schema"] == canary.DOMAIN_LINEAGE_SCHEMA
    assert lineage["consumed_by"] == "DQK-053"
    assert lineage["legacy_producers_remain_shadow_projections"] is True
    assert lineage["producer_registry_task_id"] == ad.OWNER_TASK_ID
    registered = set(ad.list_registered_producers())
    assert set(lineage["producer_ids"]).issubset(registered)

    bindings = canary.build_domain_producer_lineage()
    assert len(bindings) == 7
    domains = [b.domain.value for b in bindings]
    assert domains == list(canary.REPRESENTATIVE_DOMAINS)
    for binding in bindings:
        assert binding.producer_id in registered
        assert binding.module_path
        assert binding.fields
        assert binding.sample_rows
        assert binding.home_shard
        assert binding.catalog_id


def test_lineage_covers_every_representative_domain_once() -> None:
    bindings = canary.build_domain_producer_lineage()
    domain_ids = [b.domain.value for b in bindings]
    assert len(domain_ids) == len(set(domain_ids))
    for required in (
        "knowledge-graph",
        "vector",
        "proof-evidence",
        "ast",
        "wallet-public",
        "legal",
        "general",
    ):
        assert required in domain_ids


# ---------------------------------------------------------------------------
# ATTACH inspection
# ---------------------------------------------------------------------------


def test_safe_attach_flags_match_capability_contract() -> None:
    safe = build_attach_options(AttachMode.SAFE)
    assert safe.create_if_not_exists is False
    assert safe.override_data_path is False
    assert safe.automatic_migration is False
    assert dict(lake_caps.ATTACH_SAFE_OPTIONS) == {
        "CREATE_IF_NOT_EXISTS": False,
        "OVERRIDE_DATA_PATH": False,
        "AUTOMATIC_MIGRATION": False,
    }
    with pytest.raises(Exception, match="CREATE_IF_NOT_EXISTS|SAFE"):
        build_attach_options(AttachMode.SAFE, create_if_not_exists=True)


def test_attach_inspector_proves_non_bootstrap_safe_flags() -> None:
    inspector = canary.AttachInspector()
    # Privileged bootstrap does not enter the non-bootstrap proof set.
    inspector.record(
        purpose="bootstrap-init",
        catalog_id="catalog_bootstrap",
        catalog_path="/tmp/bootstrap.duckdb",
        data_path="/tmp/bootstrap-data",
        mode=AttachMode.BOOTSTRAP,
        is_bootstrap_or_migration=True,
        authorization_receipt_id="auth-bootstrap-1",
    )
    for i, catalog_id in enumerate(("catalog_a", "catalog_b", "catalog_c")):
        inspection = inspector.record(
            purpose=f"owner-read-{i}",
            catalog_id=catalog_id,
            catalog_path=f"/tmp/{catalog_id}.duckdb",
            data_path=f"/tmp/{catalog_id}-data",
            mode=AttachMode.SAFE,
            snapshot_version=i + 1,
        )
        assert inspection.safe is True
        assert inspection.create_if_not_exists is False
        assert inspection.override_data_path is False
        assert inspection.automatic_migration is False
        assert "CREATE_IF_NOT_EXISTS false" in inspection.sql
        assert "OVERRIDE_DATA_PATH false" in inspection.sql
        assert "AUTOMATIC_MIGRATION false" in inspection.sql

    proof = dict(inspector.prove_all_safe())
    assert proof["ok"] is True
    assert proof["all_safe"] is True
    assert proof["CREATE_IF_NOT_EXISTS"] is False
    assert proof["OVERRIDE_DATA_PATH"] is False
    assert proof["AUTOMATIC_MIGRATION"] is False
    assert proof["inspected_count"] == 3
    assert len(inspector.all()) == 4  # includes bootstrap


def test_attach_inspector_requires_at_least_one_non_bootstrap() -> None:
    inspector = canary.AttachInspector()
    inspector.record(
        purpose="bootstrap-only",
        catalog_id="catalog_bootstrap",
        catalog_path="/tmp/bootstrap.duckdb",
        data_path="/tmp/bootstrap-data",
        mode=AttachMode.BOOTSTRAP,
        is_bootstrap_or_migration=True,
        authorization_receipt_id="auth-bootstrap-only",
    )
    with pytest.raises(canary.AttachInspectionError, match="at least one"):
        inspector.prove_all_safe()


# ---------------------------------------------------------------------------
# Full canary run — primary acceptance
# ---------------------------------------------------------------------------


def test_full_canary_every_domain_passes_all_parity_dimensions() -> None:
    result = canary.run_ducklake_canary(run_id="e2e-parity")
    assert result.ok is True
    report = dict(result.report)
    assert report["all_domains_parity_passed"] is True
    assert set(report["domains"]) == set(canary.REPRESENTATIVE_DOMAINS)

    for domain_result in result.receipt["domain_results"]:
        parity = domain_result["parity"]
        for dim in canary.PARITY_DIMENSIONS:
            assert parity[dim] is True, (
                f"domain {domain_result['domain']} failed {dim} parity"
            )
        assert domain_result["parity_passed"] is True
        assert domain_result["legacy_shadow_projection"] is True
        assert domain_result["producer_id"] in ad.list_registered_producers()
        assert domain_result["source_digest"].startswith("sha256:")
        assert domain_result["schema_digest"].startswith("sha256:")
        assert domain_result["row_count"] >= 1
        assert domain_result["snapshot_id"] >= 1


def test_full_canary_attach_proof_safe_flags() -> None:
    result = canary.run_ducklake_canary(run_id="e2e-attach")
    attach = result.report["attach_proof"]
    assert attach["all_safe"] is True
    assert attach["CREATE_IF_NOT_EXISTS"] is False
    assert attach["OVERRIDE_DATA_PATH"] is False
    assert attach["AUTOMATIC_MIGRATION"] is False
    assert attach["inspected_count"] >= 7
    for record in attach["records"]:
        assert record["is_bootstrap_or_migration"] is False
        assert record["CREATE_IF_NOT_EXISTS"] is False
        assert record["OVERRIDE_DATA_PATH"] is False
        assert record["AUTOMATIC_MIGRATION"] is False
        assert record["safe"] is True


def test_full_canary_concurrency_preserves_heartbeat_slo() -> None:
    result = canary.run_ducklake_canary(run_id="e2e-heartbeat")
    conc = result.report["concurrency_proof"]
    assert conc["ok"] is True
    assert conc["heartbeat_within_slo"] is True
    assert conc["concurrent_writes"] is True
    assert conc["analytical_scans"] is True
    assert conc["control_lease_count"] == 5
    assert float(conc["max_control_lease_acquire_s"]) < float(conc["heartbeat_slo_s"])
    assert conc["long_readers_proof"]["ok"] is True
    assert conc["long_readers_proof"]["long_ops_blocked_control"] is False


def test_full_canary_failure_quarantines_without_deleting_sources() -> None:
    result = canary.run_ducklake_canary(
        run_id="e2e-failure",
        inject_failure_domain="general",
    )
    action = result.report["failure_action"]
    assert action["action"] in {"quarantine", "rollback"}
    assert action["source_deleted"] is False
    assert action["source_still_present"] is True
    assert action["domain"] == "general"
    assert action["source_digest"].startswith("sha256:")
    # Pipeline recovered the domain after quarantine.
    assert result.report["pipeline_phases"]["rollback"]["source_preserved"] is True
    assert result.report["pipeline_phases"]["rollback"]["recovered"] is True


def test_full_canary_proves_quack_beta_gate_and_local_fallback() -> None:
    result = canary.run_ducklake_canary(run_id="e2e-gate")
    gate = result.report["feature_gate"]
    fallback = result.report["local_fallback"]
    assert gate["feature_gate_enabled"] is True
    assert gate["quack_feature_gate_enabled"] is True
    assert gate["enabled"] is True
    assert gate["quack_beta"] is True
    assert gate["control_plane_affected"] is False
    assert fallback["local_fallback_enabled"] is True
    assert fallback["local_fallback_available"] is True
    assert fallback["fell_back"] is True
    assert fallback["transport_mode"] == control_caps.TransportMode.LOCAL.value


def test_full_canary_emits_exact_dqk050_compatibility_receipt() -> None:
    result = canary.run_ducklake_canary(run_id="e2e-dqk050")
    compat = result.receipt["compatibility_receipt"]
    assert compat["task_id"] == "DQK-050"
    assert compat["schema"] == (
        "ipfs_datasets_py/duckdb-quack-compatibility-risk-receipt@1"
    )
    assert compat["interface"] == "QuackCompatibilityRiskReceipt@1"
    assert compat["risk_accepted"] is True
    assert compat["feature_gate_enabled"] is True
    assert compat["local_fallback_enabled"] is True
    assert compat["quack_beta"] is True
    assert compat["receipt_id"] == result.report["compatibility_receipt_id"]
    # Re-validate through the DQK-050 require path.
    mod = canary._load_dqk050_module()
    mod.require_compatibility_receipt(compat)


def test_full_canary_emits_database_native_ducklake_canary_receipt() -> None:
    store = canary.DuckLakeCanaryStore()
    result = canary.run_ducklake_canary(run_id="e2e-receipt", store=store)
    receipt = result.receipt
    assert receipt["schema"] == canary.CANARY_RECEIPT_SCHEMA
    assert receipt["interface"] == "DuckLakeCanaryReceipt@1"
    assert receipt["task_id"] == "DQK-099"
    assert receipt["consumed_by"] == "DQK-053"
    assert receipt["database_native_table"] == "lake_canary_receipts"
    assert receipt["legacy_producers_remain_shadow_projections"] is True
    assert receipt["receipt_id"].startswith("receipt:sha256:")
    assert receipt["signature"]["algorithm"] == "content-bound-sha256@1"
    canary.require_canary_receipt(receipt)

    # Database-native store (not a file authority).
    stored = store.get_receipt(receipt["receipt_id"])
    assert stored is not None
    assert stored["receipt_id"] == receipt["receipt_id"]
    assert stored["task_id"] == "DQK-099"
    body = store.load_body(receipt["receipt_id"])
    assert body["interface"] == "DuckLakeCanaryReceipt@1"
    assert result.stored_row["receipt_id"] == receipt["receipt_id"]


def test_pipeline_phases_all_succeed() -> None:
    result = canary.run_ducklake_canary(run_id="e2e-phases")
    phases = result.report["pipeline_phases"]
    for phase in canary.PIPELINE_PHASES:
        assert phase in phases, f"missing phase {phase}"
        assert phases[phase]["ok"] is True, f"phase {phase} failed"
    assert phases["ingestion"]["sources_untouched"] is True
    assert phases["backup_restore"]["claims_pitr"] is False
    assert phases["backup_restore"]["claims_replication"] is False
    assert phases["backup_restore"]["claims_built_in_ha"] is False
    assert phases["sanitized_publication"]["secrets_denied"] is True
    assert phases["multi_catalog_aggregation"]["catalog_count"] == 7


# ---------------------------------------------------------------------------
# Receipt validation fail-closed
# ---------------------------------------------------------------------------


def test_require_canary_receipt_rejects_tampered_signature() -> None:
    result = canary.run_ducklake_canary(run_id="e2e-tamper")
    bad = dict(result.receipt)
    bad["run_id"] = "tampered-run"
    with pytest.raises(canary.ReceiptError, match="signature|receipt_id"):
        canary.require_canary_receipt(bad)


def test_require_canary_receipt_rejects_wrong_interface() -> None:
    result = canary.run_ducklake_canary(run_id="e2e-wrong-iface")
    bad = dict(result.receipt)
    bad["interface"] = "NotACanaryReceipt@1"
    # Rebuild signature so we hit interface check after re-sign would pass —
    # leave signature stale so either signature or interface fails closed.
    with pytest.raises(canary.ReceiptError):
        canary.require_canary_receipt(bad)


def test_build_canary_receipt_requires_all_domains() -> None:
    result = canary.run_ducklake_canary(run_id="e2e-partial")
    receipt = result.receipt
    partial_domains = list(receipt["domain_results"])[:3]
    with pytest.raises(canary.ReceiptError, match="exactly"):
        canary.build_canary_receipt(
            run_id="partial",
            domain_results=partial_domains,
            attach_proof=receipt["attach_proof"],
            concurrency_proof=receipt["concurrency_proof"],
            pipeline_phases=receipt["pipeline_phases"],
            failure_action=receipt["failure_action"],
            compatibility_receipt=receipt["compatibility_receipt"],
            feature_gate=receipt["quack_beta_feature_gate"],
            local_fallback=receipt["local_fallback"],
            lineage=receipt["domain_producer_lineage"],
        )


def test_build_canary_receipt_rejects_source_deletion() -> None:
    result = canary.run_ducklake_canary(run_id="e2e-src-del")
    receipt = result.receipt
    bad_action = dict(receipt["failure_action"])
    bad_action["source_deleted"] = True
    bad_action["source_still_present"] = False
    with pytest.raises(canary.ReceiptError, match="source"):
        canary.build_canary_receipt(
            run_id="src-del",
            domain_results=receipt["domain_results"],
            attach_proof=receipt["attach_proof"],
            concurrency_proof=receipt["concurrency_proof"],
            pipeline_phases=receipt["pipeline_phases"],
            failure_action=bad_action,
            compatibility_receipt=receipt["compatibility_receipt"],
            feature_gate=receipt["quack_beta_feature_gate"],
            local_fallback=receipt["local_fallback"],
            lineage=receipt["domain_producer_lineage"],
        )


# ---------------------------------------------------------------------------
# Failure / quarantine unit paths
# ---------------------------------------------------------------------------


def test_quarantine_preserves_source_bytes(tmp_path: Path) -> None:
    workspace = canary.CanaryWorkspace(tmp_path / "ws")
    binding = canary.build_domain_producer_lineage()[0]
    material = canary.materialize_domain_source(workspace, binding)
    source_digest = material.source_digest
    lake_copy = tmp_path / "lake" / material.source_path.name
    lake_copy.parent.mkdir(parents=True)
    lake_copy.write_bytes(material.source_path.read_bytes())

    decision = canary.quarantine_or_rollback_one_dataset(
        material,
        lake_copy_path=lake_copy,
        action="quarantine",
        reason="test inject",
    )
    assert decision.source_deleted is False
    assert decision.source_still_present is True
    assert decision.lake_object_removed is True
    assert not lake_copy.exists()
    assert material.source_path.is_file()
    assert canary._file_digest(material.source_path) == source_digest
    assert material.quarantined is True


def test_rollback_preserves_source_bytes(tmp_path: Path) -> None:
    workspace = canary.CanaryWorkspace(tmp_path / "ws")
    binding = canary.build_domain_producer_lineage()[1]
    material = canary.materialize_domain_source(workspace, binding, snapshot_id=3)
    material.ingested = True
    source_digest = material.source_digest
    lake_copy = tmp_path / "lake" / material.source_path.name
    lake_copy.parent.mkdir(parents=True)
    lake_copy.write_bytes(material.source_path.read_bytes())

    decision = canary.quarantine_or_rollback_one_dataset(
        material,
        lake_copy_path=lake_copy,
        action="rollback",
        reason="test rollback",
    )
    assert decision.action == "rollback"
    assert decision.source_deleted is False
    assert material.source_path.is_file()
    assert canary._file_digest(material.source_path) == source_digest
    assert material.rolled_back is True
    assert material.snapshot_id == 2


# ---------------------------------------------------------------------------
# Concurrency / feature-gate helpers
# ---------------------------------------------------------------------------


def test_prove_concurrency_preserves_heartbeat_slo_standalone() -> None:
    proof = dict(canary.prove_concurrency_preserves_heartbeat_slo())
    assert proof["ok"] is True
    assert proof["heartbeat_within_slo"] is True
    assert proof["max_control_lease_acquire_s"] < proof["heartbeat_slo_s"]


def test_prove_quack_beta_feature_gate_and_fallback_standalone() -> None:
    proof = dict(canary.prove_quack_beta_feature_gate_and_fallback())
    assert proof["ok"] is True
    assert proof["feature_gate"]["enabled"] is True
    assert proof["feature_gate"]["quack_beta"] is True
    assert proof["local_fallback"]["local_fallback_enabled"] is True
    assert proof["local_fallback"]["fell_back"] is True


def test_emit_dqk050_compatibility_receipt_standalone() -> None:
    receipt = canary.emit_dqk050_compatibility_receipt(
        acceptor_identity="reviewer:e2e-test"
    )
    assert receipt["task_id"] == "DQK-050"
    assert receipt["risk_accepted"] is True
    assert receipt["feature_gate_enabled"] is True
    assert receipt["local_fallback_enabled"] is True
    mod = canary._load_dqk050_module()
    mod.require_compatibility_receipt(receipt)


# ---------------------------------------------------------------------------
# Self-check / CLI surfaces
# ---------------------------------------------------------------------------


def test_self_check_passes() -> None:
    report = dict(canary.self_check())
    assert report["ok"] is True
    assert report["self_check"]["ok"] is True
    assert report["self_check"]["domains_passed"] == 7
    assert report["self_check"]["heartbeat_within_slo"] is True
    assert report["self_check"]["source_deleted"] is False
    assert report["self_check"]["database_native_stored"] is True
    assert report["self_check"]["receipt_id"].startswith("receipt:sha256:")


def test_main_install_check_exit_zero() -> None:
    rc = canary.main([])
    assert rc == 0


def test_main_self_check_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = canary.main(["--self-check", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["self_check"]["ok"] is True


def test_main_emit_receipt(capsys: pytest.CaptureFixture[str]) -> None:
    rc = canary.main(["--emit-receipt", "--run-id", "cli-emit"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["interface"] == "DuckLakeCanaryReceipt@1"
    assert payload["task_id"] == "DQK-099"
    assert payload["run_id"] == "cli-emit"
    canary.require_canary_receipt(payload)


# ---------------------------------------------------------------------------
# Store CAS / idempotency
# ---------------------------------------------------------------------------


def test_canary_store_put_is_idempotent_for_same_digest() -> None:
    store = canary.DuckLakeCanaryStore()
    result = canary.run_ducklake_canary(run_id="e2e-store-idem", store=store)
    again = store.put_receipt(result.receipt)
    assert again["receipt_id"] == result.receipt["receipt_id"]
    assert len(store.list_receipts()) == 1


def test_canary_store_rejects_digest_conflict() -> None:
    store = canary.DuckLakeCanaryStore()
    result = canary.run_ducklake_canary(run_id="e2e-store-conflict", store=store)
    conflicting = dict(result.receipt)
    # Keep receipt_id, change body and signature artificially.
    conflicting["issued_at_ms"] = int(conflicting["issued_at_ms"]) + 1
    conflicting["signature"] = {
        "algorithm": "content-bound-sha256@1",
        "digest": "sha256:" + ("ff" * 32),
    }
    with pytest.raises(canary.ReceiptError):
        # require_canary_receipt fails first on signature, which is correct fail-closed.
        store.put_receipt(conflicting)
