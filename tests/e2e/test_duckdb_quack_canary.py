"""E2E tests: domain canaries and cutover/rollback gates (DQK-053).

Acceptance coverage:

* Each authority promotion has evidence and a tested rollback
* Canary failures quarantine only their namespace
* Legacy producers become export-only after promotion

Hermetic: no live DuckDB, Quack, Docker, or network required. The owned canary
lives in ``scripts/ops/duckdb_quack_canary.py``.
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
_CANARY_PATH = _REPO_ROOT / "scripts/ops/duckdb_quack_canary.py"


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

    module_name = "duckdb_quack_canary"
    existing = sys.modules.get(module_name)
    if existing is not None and getattr(existing, "CONTRACT_TASK_ID", None) == "DQK-053":
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

from ipfs_datasets_py.duckdb_control import authority_transition as at  # noqa: E402
from ipfs_datasets_py.duckdb_control import parallel_query as pq  # noqa: E402
from ipfs_datasets_py.duckdb_control import recovery as rec  # noqa: E402


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
    assert canary.CONTRACT_TASK_ID == "DQK-053"
    assert canary.AUTHORITY_PORT_TASK_ID == "DQK-046"
    assert canary.RECOVERY_TASK_ID == "DQK-047"
    assert canary.DUCKLAKE_CANARY_TASK_ID == "DQK-099"
    assert canary.CANARY_RECEIPT_INTERFACE == "DuckDBQuackDomainCanaryReceipt@1"
    assert canary.CANARY_RECEIPT_SCHEMA.endswith("@1")
    assert canary.STORE_TABLE == "domain_canary_receipts"
    assert canary.PROMOTION_LADDER[0] == "legacy"
    assert canary.PROMOTION_LADDER[-1] == "export-only"
    assert "shadow" in canary.PROMOTION_LADDER
    assert "dual" in canary.PROMOTION_LADDER
    assert set(canary.EVIDENCE_DIMENSIONS) == {
        "slo",
        "parity",
        "security",
        "restore",
        "rollback",
    }
    assert canary.DEFAULT_ROLLBACK_WINDOW_S > 0


def test_install_check_reports_namespaces_in_dependency_order(
    install_report: dict[str, Any],
) -> None:
    assert install_report["ok"] is True
    assert install_report["owner_task_id"] == "DQK-053"
    assert install_report["namespaces"] == [
        "supervisor",
        "proof",
        "graph",
        "vector",
        "ast",
        "wallet",
        "observability",
        "ducklake",
    ]
    assert install_report["namespace_order"] == list(canary.CANARY_NAMESPACES)
    assert install_report["promotion_ladder"][-1] == "export-only"
    assert install_report["interface"] == "DuckDBQuackDomainCanaryReceipt@1"
    assert install_report["database_native_table"] == "domain_canary_receipts"
    assert install_report["acceptance"][
        "each_authority_promotion_has_evidence_and_tested_rollback"
    ] is True
    assert install_report["acceptance"][
        "canary_failures_quarantine_only_their_namespace"
    ] is True
    assert install_report["acceptance"][
        "legacy_producers_become_export_only_after_promotion"
    ] is True


def test_namespace_dependencies_are_topologically_ordered() -> None:
    order = list(canary.CANARY_NAMESPACES)
    for ns in order:
        canary.assert_dependency_order(order[: order.index(ns)], ns)
    # Proof requires supervisor.
    with pytest.raises(canary.DependencyOrderError, match="supervisor"):
        canary.assert_dependency_order([], "proof")
    # DuckLake requires all prior namespaces.
    with pytest.raises(canary.DependencyOrderError):
        canary.assert_dependency_order(["supervisor"], "ducklake")


# ---------------------------------------------------------------------------
# Evidence collectors
# ---------------------------------------------------------------------------


def test_collect_slo_evidence_within_heartbeat_budget() -> None:
    proof = dict(canary.collect_slo_evidence(namespace="supervisor"))
    assert proof["ok"] is True
    assert proof["within_slo"] is True
    assert proof["heartbeat_p99_ms"] <= proof["heartbeat_p99_slo_ms"]
    assert proof["sample_count"] >= 3
    assert proof["reserved_control_plane_slots"] == pq.DEFAULT_RESERVED_CONTROL_PLANE_SLOTS


def test_collect_restore_evidence_proves_schema_and_snapshot() -> None:
    proof = dict(
        canary.collect_restore_evidence(
            namespace="graph",
            payload={"vertices": 2, "edges": 1},
        )
    )
    assert proof["ok"] is True
    assert proof["schema_matched"] is True
    assert proof["snapshot_matched"] is True
    assert proof["schema_digest"].startswith("sha256:")
    assert proof["snapshot_digest"].startswith("sha256:")
    assert proof["atomic_across_databases"] is False
    assert proof["claims_pitr"] is False
    assert proof["claims_replication"] is False


def test_collect_security_evidence_denies_cross_fs_atomicity() -> None:
    proof = dict(canary.collect_security_evidence(namespace="wallet"))
    assert proof["ok"] is True
    assert proof["atomic_across_filesystems"] is False
    assert proof["authority_writes_fenced"] is True
    assert "cross_filesystem_atomicity_claim" in proof["denied_surfaces"]


def test_collect_parity_evidence_matches_after_shadow_write() -> None:
    backend = at.MemoryAuthorityBackend()
    port = at.build_authority_port(
        backend, domain="parity-ns", initial_mode=at.AuthorityMode.SHADOW
    )
    port.write("k", {"v": 1}, operation_id="op:parity:1")
    port.recover_outbox()
    canary._resolve_quarantines(backend, "parity-ns")
    proof = dict(canary.collect_parity_evidence(port, key="k"))
    assert proof["ok"] is True
    assert proof["matched"] is True
    assert proof["receipt_cid"].startswith("sha256:")


# ---------------------------------------------------------------------------
# Rollback window
# ---------------------------------------------------------------------------


def test_rollback_window_open_close_and_expiry() -> None:
    window = canary.open_rollback_window(
        namespace="proof",
        from_mode="shadow",
        to_mode="dual",
        duration_s=60,
        opened_at_ms=1_000_000,
    )
    assert window.open is True
    window.assert_open(now_ms=1_000_000)
    mapping = dict(window.as_mapping())
    assert mapping["duration_s"] == 60
    assert mapping["expires_at_ms"] == 1_000_000 + 60_000
    closed = canary.close_rollback_window(window)
    assert closed.open is False
    with pytest.raises(canary.RollbackWindowError, match="closed"):
        closed.assert_open(now_ms=1_000_000)
    expired = canary.open_rollback_window(
        namespace="proof",
        from_mode="dual",
        to_mode="db-primary",
        duration_s=1,
        opened_at_ms=0,
    )
    with pytest.raises(canary.RollbackWindowError, match="expired"):
        expired.assert_open(now_ms=5_000)


# ---------------------------------------------------------------------------
# Full canary run — primary acceptance
# ---------------------------------------------------------------------------


def test_full_canary_each_promotion_has_evidence_and_tested_rollback() -> None:
    result = canary.run_domain_canary(run_id="e2e-evidence")
    assert result.ok is True
    report = dict(result.report)
    assert report["all_promotions_have_evidence_and_tested_rollback"] is True

    for ns_result in result.receipt["namespace_results"]:
        assert ns_result["ok"] is True
        assert ns_result["each_promotion_has_evidence"] is True
        assert ns_result["each_non_terminal_promotion_has_tested_rollback"] is True
        steps = ns_result["promotion_steps"]
        assert steps, f"namespace {ns_result['namespace']} has no promotion steps"
        for step in steps:
            assert step["accepted"] is True
            assert step.get("evidence"), (
                f"{ns_result['namespace']} {step['from_mode']}->"
                f"{step['to_mode']} missing evidence"
            )
            evidence = step["evidence"]
            assert evidence["slo"]["ok"] is True
            assert evidence["slo"]["within_slo"] is True
            assert evidence["security"]["ok"] is True
            assert evidence["restore"]["ok"] is True
            assert evidence["restore"]["schema_matched"] is True
            if step["to_mode"] != "export-only" and not step.get("noop"):
                assert step["rollback_tested"] is True
                assert step["rollback_proof"]["tested"] is True
                assert step["rollback_window"] is not None
                assert step["rollback_window"]["duration_s"] > 0
                assert step["rollback_window"]["open"] is False  # closed after use


def test_full_canary_legacy_producers_become_export_only() -> None:
    result = canary.run_domain_canary(run_id="e2e-export-only")
    assert result.report["all_namespaces_export_only"] is True
    assert result.receipt["legacy_producers_export_only_after_promotion"] is True
    for ns_result in result.receipt["namespace_results"]:
        assert ns_result["final_mode"] == "export-only"
        assert ns_result["legacy_export_only"] is True
        # Final ladder step must land on export-only.
        assert ns_result["promotion_steps"][-1]["to_mode"] == "export-only"


def test_full_canary_failures_quarantine_only_their_namespace() -> None:
    result = canary.run_domain_canary(
        run_id="e2e-quarantine",
        inject_failure_namespace="ast",
    )
    isolation = result.report["quarantine_isolation"]
    assert isolation["ok"] is True
    assert isolation["isolated"] is True
    assert isolation["peer_namespaces_unaffected"] is True
    assert isolation["failing_namespace"] == "ast"
    assert isolation["peer_violations"] == []
    # Only the failing namespace gains open quarantine.
    after = isolation["open_quarantine_after"]
    before = isolation["open_quarantine_before"]
    assert after["ast"] > before["ast"]
    for ns, count in after.items():
        if ns == "ast":
            continue
        assert count == before[ns], f"peer namespace {ns} quarantine leaked"


def test_full_canary_runs_namespaces_in_dependency_order() -> None:
    result = canary.run_domain_canary(run_id="e2e-order")
    assert result.report["namespaces"] == list(canary.CANARY_NAMESPACES)
    assert result.receipt["namespace_order"] == [
        "supervisor",
        "proof",
        "graph",
        "vector",
        "ast",
        "wallet",
        "observability",
        "ducklake",
    ]
    # Dependencies of each result must appear earlier in the result list.
    seen: list[str] = []
    for ns_result in result.receipt["namespace_results"]:
        for dep in ns_result["dependencies"]:
            assert dep in seen
        seen.append(ns_result["namespace"])


def test_full_canary_uses_shadow_and_dual_authority() -> None:
    result = canary.run_domain_canary(run_id="e2e-shadow-dual")
    for ns_result in result.receipt["namespace_results"]:
        modes = [s["to_mode"] for s in ns_result["promotion_steps"]]
        assert "shadow" in modes
        assert "dual" in modes
        assert "db-primary" in modes
        assert "export-only" in modes


def test_full_canary_emits_database_native_receipt() -> None:
    store = canary.DomainCanaryStore()
    result = canary.run_domain_canary(run_id="e2e-receipt", store=store)
    receipt = result.receipt
    assert receipt["schema"] == canary.CANARY_RECEIPT_SCHEMA
    assert receipt["interface"] == "DuckDBQuackDomainCanaryReceipt@1"
    assert receipt["task_id"] == "DQK-053"
    assert receipt["database_native_table"] == "domain_canary_receipts"
    assert receipt["receipt_id"].startswith("receipt:sha256:")
    assert receipt["signature"]["algorithm"] == "content-bound-sha256@1"
    canary.require_canary_receipt(receipt)

    stored = store.get_receipt(receipt["receipt_id"])
    assert stored is not None
    assert stored["task_id"] == "DQK-053"
    body = store.load_body(receipt["receipt_id"])
    assert body["interface"] == "DuckDBQuackDomainCanaryReceipt@1"
    assert result.stored_row["receipt_id"] == receipt["receipt_id"]


def test_full_canary_acceptance_block() -> None:
    result = canary.run_domain_canary(run_id="e2e-acceptance")
    acceptance = result.receipt["acceptance"]
    assert acceptance[
        "each_authority_promotion_has_evidence_and_tested_rollback"
    ] is True
    assert acceptance[
        "canary_failures_quarantine_only_their_namespace"
    ] is True
    assert acceptance[
        "legacy_producers_become_export_only_after_promotion"
    ] is True


# ---------------------------------------------------------------------------
# Isolation unit path
# ---------------------------------------------------------------------------


def test_inject_namespace_failure_does_not_touch_peers() -> None:
    bundles = canary.build_namespace_ports(["supervisor", "proof", "wallet"])
    # Promote each to dual so modes are non-trivial.
    for ns, bundle in bundles.items():
        canary._promote_step(
            bundle,
            to_mode="shadow",
            decision_id=f"dec:{ns}:shadow",
            require_parity=False,
            rollback_window_s=60,
            heartbeat_p99_slo_ms=canary.DEFAULT_HEARTBEAT_P99_SLO_MS,
            test_rollback=False,
        )
        canary._promote_step(
            bundle,
            to_mode="dual",
            decision_id=f"dec:{ns}:dual",
            require_parity=True,
            rollback_window_s=60,
            heartbeat_p99_slo_ms=canary.DEFAULT_HEARTBEAT_P99_SLO_MS,
            test_rollback=False,
        )
    modes_before = {ns: b.port.state().mode.value for ns, b in bundles.items()}
    isolation = dict(
        canary.inject_namespace_failure(
            bundles,
            failing_namespace="proof",
            reason="unit isolation inject",
        )
    )
    assert isolation["isolated"] is True
    assert isolation["failing_namespace"] == "proof"
    assert bundles["proof"].quarantined is True
    assert bundles["supervisor"].quarantined is False
    assert bundles["wallet"].quarantined is False
    assert bundles["supervisor"].port.state().mode.value == modes_before["supervisor"]
    assert bundles["wallet"].port.state().mode.value == modes_before["wallet"]
    assert len(bundles["proof"].backend.list_open_quarantine("proof")) >= 1
    assert len(bundles["wallet"].backend.list_open_quarantine("wallet")) == 0


def test_export_only_rejects_authority_writes() -> None:
    bundles = canary.build_namespace_ports(["supervisor"])
    result = dict(
        canary.promote_namespace_to_export_only(
            bundles["supervisor"],
            test_each_rollback=False,
        )
    )
    assert result["final_mode"] == "export-only"
    with pytest.raises(at.AuthorityTransitionError, match="export-only"):
        bundles["supervisor"].port.write(
            bundles["supervisor"].seed_key,
            {"x": 1},
            operation_id="op:should-fail",
        )


# ---------------------------------------------------------------------------
# Receipt validation fail-closed
# ---------------------------------------------------------------------------


def test_require_canary_receipt_rejects_tampered_signature() -> None:
    result = canary.run_domain_canary(run_id="e2e-tamper")
    bad = dict(result.receipt)
    bad["run_id"] = "tampered-run"
    with pytest.raises(canary.ReceiptError, match="signature|receipt_id"):
        canary.require_canary_receipt(bad)


def test_require_canary_receipt_rejects_wrong_interface() -> None:
    result = canary.run_domain_canary(run_id="e2e-wrong-iface")
    bad = dict(result.receipt)
    bad["interface"] = "NotADomainCanaryReceipt@1"
    with pytest.raises(canary.ReceiptError):
        canary.require_canary_receipt(bad)


def test_build_canary_receipt_requires_export_only() -> None:
    result = canary.run_domain_canary(run_id="e2e-partial-export")
    receipt = result.receipt
    bad_results = [dict(r) for r in receipt["namespace_results"]]
    bad_results[0]["legacy_export_only"] = False
    bad_results[0]["final_mode"] = "db-primary"
    with pytest.raises(canary.ReceiptError, match="export-only"):
        canary.build_canary_receipt(
            run_id="partial-export",
            namespace_results=bad_results,
            quarantine_isolation=receipt["quarantine_isolation"],
            ducklake_lineage=receipt["ducklake_lineage"],
            namespace_order=receipt["namespace_order"],
        )


def test_build_canary_receipt_requires_isolation() -> None:
    result = canary.run_domain_canary(run_id="e2e-no-isolation")
    receipt = result.receipt
    bad_isolation = dict(receipt["quarantine_isolation"])
    bad_isolation["isolated"] = False
    with pytest.raises(canary.ReceiptError, match="isolation"):
        canary.build_canary_receipt(
            run_id="no-isolation",
            namespace_results=receipt["namespace_results"],
            quarantine_isolation=bad_isolation,
            ducklake_lineage=receipt["ducklake_lineage"],
            namespace_order=receipt["namespace_order"],
        )


def test_build_canary_receipt_requires_tested_rollback() -> None:
    result = canary.run_domain_canary(run_id="e2e-no-rollback")
    receipt = result.receipt
    bad_results = [dict(r) for r in receipt["namespace_results"]]
    steps = [dict(s) for s in bad_results[0]["promotion_steps"]]
    # Strip rollback from the first non-terminal step.
    for step in steps:
        if step["to_mode"] != "export-only":
            step["rollback_tested"] = False
            step["rollback_proof"] = None
            break
    bad_results[0]["promotion_steps"] = steps
    with pytest.raises(canary.ReceiptError, match="tested rollback"):
        canary.build_canary_receipt(
            run_id="no-rollback",
            namespace_results=bad_results,
            quarantine_isolation=receipt["quarantine_isolation"],
            ducklake_lineage=receipt["ducklake_lineage"],
            namespace_order=receipt["namespace_order"],
        )


# ---------------------------------------------------------------------------
# DuckLake lineage binding
# ---------------------------------------------------------------------------


def test_ducklake_lineage_binding_when_available() -> None:
    binding = dict(canary.ducklake_lineage_binding())
    # Module is present in this repository (DQK-099).
    assert binding["task_id"] == "DQK-099"
    assert binding["consumed_by"] == "DQK-053"
    if binding.get("available"):
        assert binding["ok"] is True
        assert binding["lineage_digest"].startswith("sha256:")
        assert "knowledge-graph" in binding["domain_ids"]
        assert binding["legacy_producers_remain_shadow_projections"] is True


# ---------------------------------------------------------------------------
# Self-check / CLI surfaces
# ---------------------------------------------------------------------------


def test_self_check_passes() -> None:
    report = dict(canary.self_check())
    assert report["ok"] is True
    assert report["self_check"]["ok"] is True
    assert report["self_check"]["namespaces_passed"] == 8
    assert report["self_check"]["all_export_only"] is True
    assert report["self_check"]["promotions_evidenced"] is True
    assert report["self_check"]["quarantine_isolated"] is True
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
    assert payload["interface"] == "DuckDBQuackDomainCanaryReceipt@1"
    assert payload["task_id"] == "DQK-053"
    assert payload["run_id"] == "cli-emit"
    canary.require_canary_receipt(payload)


# ---------------------------------------------------------------------------
# Store CAS / idempotency
# ---------------------------------------------------------------------------


def test_canary_store_put_is_idempotent_for_same_digest() -> None:
    store = canary.DomainCanaryStore()
    result = canary.run_domain_canary(run_id="e2e-store-idem", store=store)
    again = store.put_receipt(result.receipt)
    assert again["receipt_id"] == result.receipt["receipt_id"]
    assert len(store.list_receipts()) == 1


def test_canary_store_rejects_digest_conflict() -> None:
    store = canary.DomainCanaryStore()
    result = canary.run_domain_canary(run_id="e2e-store-conflict", store=store)
    conflicting = dict(result.receipt)
    conflicting["issued_at_ms"] = int(conflicting["issued_at_ms"]) + 1
    conflicting["signature"] = {
        "algorithm": "content-bound-sha256@1",
        "digest": "sha256:" + ("ab" * 32),
    }
    # Keep receipt_id so store detects digest conflict on same id.
    with pytest.raises(canary.ReceiptError):
        store.put_receipt(conflicting)


# ---------------------------------------------------------------------------
# Recovery / authority install wiring
# ---------------------------------------------------------------------------


def test_depends_on_authority_and_recovery_install_checks() -> None:
    at_install = at.install_check()
    rec_install = rec.install_check()
    assert at_install["ok"] is True
    assert at_install["owner_task_id"] == "DQK-046"
    assert rec_install["ok"] is True
    assert rec_install["owner_task_id"] == "DQK-047"
    assert "export-only" in at_install["modes"]
    assert "restore" in rec_install["workflows"]
