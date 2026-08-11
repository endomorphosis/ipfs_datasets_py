"""E2E tests: multi-namespace domain canary and cutover/rollback (DQK-053).

Acceptance coverage:

* Each authority promotion has evidence and a tested rollback
* Canary failures quarantine only their namespace
* Legacy producers become export-only after promotion

Also covers sealed dependency order, shadow/dual authority ladder, DuckLake
lineage consumption from DQK-099, and database-native DuckDBQuackCanaryReceipt@1.
"""

from __future__ import annotations

import importlib.util
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

from ipfs_datasets_py.duckdb_control.authority_transition import (  # noqa: E402
    AuthorityMode,
    MemoryAuthorityBackend,
)


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
    assert canary.AUTHORITY_TASK_ID == "DQK-046"
    assert canary.DUCKLAKE_CANARY_TASK_ID == "DQK-099"
    assert canary.CANARY_RECEIPT_INTERFACE == "DuckDBQuackCanaryReceipt@1"
    assert canary.CANARY_RECEIPT_SCHEMA.endswith("@1")
    assert canary.STORE_TABLE == "domain_canary_receipts"
    assert set(canary.EVIDENCE_DIMENSIONS) == {
        "slo",
        "parity",
        "security",
        "restore",
    }
    assert list(canary.PROMOTION_LADDER) == [
        "legacy",
        "shadow",
        "dual",
        "db-primary",
        "export-only",
    ]
    assert canary.POST_PROMOTION_MODE == "export-only"
    assert list(canary.CANARY_NAMESPACE_ORDER) == [
        "supervisor",
        "proof",
        "graph-vector",
        "ast",
        "wallet",
        "observability",
        "ducklake",
    ]


def test_install_check_reports_namespaces_and_acceptance(
    install_report: dict[str, Any],
) -> None:
    assert install_report["ok"] is True
    assert install_report["owner_task_id"] == "DQK-053"
    assert install_report["authority_task_id"] == "DQK-046"
    assert install_report["ducklake_canary_task_id"] == "DQK-099"
    assert set(install_report["namespaces"]) == set(
        canary.CANARY_NAMESPACE_ORDER
    )
    assert install_report["post_promotion_mode"] == "export-only"
    assert install_report["interface"] == "DuckDBQuackCanaryReceipt@1"
    assert install_report["database_native_table"] == "domain_canary_receipts"
    acceptance = install_report["acceptance"]
    assert (
        "Each authority promotion has evidence and a tested rollback"
        in acceptance
    )
    assert "Canary failures quarantine only their namespace" in acceptance
    assert (
        "Legacy producers become export-only after promotion" in acceptance
    )
    assert str(install_report["ducklake_lineage_digest"]).startswith("sha256:")


def test_namespace_order_is_dependency_safe() -> None:
    order = canary.namespace_order_receipt()
    assert order["task_id"] == "DQK-053"
    assert list(order["order"]) == list(canary.CANARY_NAMESPACE_ORDER)
    assert str(order["order_digest"]).startswith("sha256:")
    specs = canary.build_namespace_specs()
    assert len(specs) == 7
    seen: set[str] = set()
    for spec in specs:
        for dep in spec.depends_on:
            assert dep in seen, f"{spec.namespace.value} depends on unseen {dep}"
        seen.add(spec.namespace.value)


def test_namespace_specs_cover_required_domains() -> None:
    domains = [s.namespace.value for s in canary.build_namespace_specs()]
    assert domains == [
        "supervisor",
        "proof",
        "graph-vector",
        "ast",
        "wallet",
        "observability",
        "ducklake",
    ]
    assert "graph-vector" in domains


# ---------------------------------------------------------------------------
# Full multi-namespace canary
# ---------------------------------------------------------------------------


def test_full_canary_each_promotion_has_evidence_and_tested_rollback() -> None:
    result = canary.run_domain_canary(run_id="e2e-evidence-rollback")
    assert result.ok is True
    report = dict(result.report)
    assert report["each_promotion_has_evidence_and_tested_rollback"] is True
    for ns in report["namespace_results"]:
        assert ns["ok"] is True or ns["quarantined"] is True
        assert ns["every_promotion_has_evidence_and_rollback"] is True
        assert len(ns["steps"]) == 4
        for step in ns["steps"]:
            evidence = step["evidence"]
            assert evidence["all_passed"] is True
            assert set(evidence["dimensions"]) == set(
                canary.EVIDENCE_DIMENSIONS
            )
            window = step["rollback_window"]
            assert window["rollback_tested"] is True
            assert window["re_promoted"] is True
            assert str(window["promotion_receipt_cid"]).startswith("sha256:")
            assert str(window["rollback_receipt_cid"]).startswith("sha256:")
            assert window["schema"] == canary.ROLLBACK_WINDOW_SCHEMA
            assert window["opened_at"]
            assert window["closes_at"]


def test_full_canary_legacy_producers_export_only_after_promotion() -> None:
    result = canary.run_domain_canary(run_id="e2e-export-only")
    report = dict(result.report)
    assert report["all_namespaces_promoted_export_only"] is True
    assert report["post_promotion_mode"] == "export-only"
    for ns in report["namespace_results"]:
        assert ns["final_mode"] == "export-only"
        assert ns["export_only_after_promotion"] is True
        assert ns["legacy_producers_export_only"] is True
        last = ns["steps"][-1]
        assert last["to_mode"] == "export-only"
        assert "export-only-writes-rejected" in last["evidence"]["security_notes"]
    for ns_name in canary.CANARY_NAMESPACE_ORDER:
        # Locate authority domain via namespace results
        pass
    for ns in report["namespace_results"]:
        domain = ns["authority_domain"]
        st = result.backend.get_state(domain)
        assert st is not None
        assert st.mode is AuthorityMode.EXPORT_ONLY


def test_full_canary_failure_quarantines_only_its_namespace() -> None:
    result = canary.run_domain_canary(
        run_id="e2e-isolation",
        inject_failure_namespace="wallet",
    )
    proof = result.report["isolation_proof"]
    assert proof["ok"] is True
    assert proof["isolation_proven"] is True
    assert proof["failing_namespace"] == "wallet"
    assert proof["open_quarantine_count"] >= 1
    assert proof["leaked_namespaces"] == []
    assert proof["other_namespaces_export_only"] is True

    for ns in result.report["namespace_results"]:
        if ns["namespace"] == "wallet":
            assert ns["quarantined"] is True
            assert ns["quarantine_record"]["domain"]
            assert ns["final_mode"] == "export-only"
        else:
            assert ns["quarantined"] is False
            assert ns["final_mode"] == "export-only"
            open_q = list(
                result.backend.list_open_quarantine(ns["authority_domain"])
            )
            assert open_q == [], f"unexpected quarantine on {ns['namespace']}"

    others = (
        "supervisor",
        "proof",
        "graph-vector",
        "ast",
        "observability",
        "ducklake",
    )
    for name in others:
        assert name in {
            n["namespace"] for n in result.report["namespace_results"]
        }


def test_full_canary_respects_dependency_order() -> None:
    result = canary.run_domain_canary(run_id="e2e-order")
    report = dict(result.report)
    assert list(report["namespaces"]) == list(canary.CANARY_NAMESPACE_ORDER)
    assert list(report["completed_namespaces"]) == list(
        canary.CANARY_NAMESPACE_ORDER
    )
    assert [
        r["namespace"] for r in report["namespace_results"]
    ] == list(canary.CANARY_NAMESPACE_ORDER)
    duck = next(
        r
        for r in report["namespace_results"]
        if r["namespace"] == "ducklake"
    )
    assert str(duck["ducklake_lineage_digest"]).startswith("sha256:")


def test_full_canary_uses_shadow_dual_authority_ladder() -> None:
    result = canary.run_domain_canary(run_id="e2e-ladder")
    expected_edges = (
        ("legacy", "shadow"),
        ("shadow", "dual"),
        ("dual", "db-primary"),
        ("db-primary", "export-only"),
    )
    for ns in result.report["namespace_results"]:
        edges = [(s["from_mode"], s["to_mode"]) for s in ns["steps"]]
        assert edges == list(expected_edges)
        for step in ns["steps"]:
            promo = step["promotion"]
            assert promo["kind"] == "promote"
            assert promo["accepted"] is True
            assert promo["atomic_across_filesystems"] is False


def test_full_canary_emits_database_native_receipt() -> None:
    store = canary.DomainCanaryStore()
    result = canary.run_domain_canary(run_id="e2e-receipt", store=store)
    receipt = result.receipt
    assert receipt["schema"] == canary.CANARY_RECEIPT_SCHEMA
    assert receipt["interface"] == "DuckDBQuackCanaryReceipt@1"
    assert receipt["task_id"] == "DQK-053"
    assert receipt["database_native_table"] == "domain_canary_receipts"
    assert receipt["all_namespaces_promoted_export_only"] is True
    assert receipt["each_promotion_has_evidence_and_tested_rollback"] is True
    assert str(receipt["receipt_id"]).startswith("receipt:sha256:")
    assert receipt["signature"]["algorithm"] == "content-bound-sha256@1"
    assert receipt["atomic_across_filesystems"] is False
    assert receipt["ducklake_lineage"]["consumed_by"] == "DQK-053"
    canary.require_canary_receipt(receipt)
    stored = store.get_receipt(receipt["receipt_id"])
    assert stored is not None
    body = store.load_body(receipt["receipt_id"])
    assert body["receipt_id"] == result.stored_row["receipt_id"]


@pytest.mark.parametrize("ns", list(canary.CANARY_NAMESPACE_ORDER))
def test_quarantine_isolation_for_each_namespace(ns: str) -> None:
    result = canary.run_domain_canary(
        run_id=f"e2e-iso-{ns}",
        inject_failure_namespace=ns,
    )
    proof = result.report["isolation_proof"]
    assert proof["failing_namespace"] == ns
    assert proof["isolation_proven"] is True
    assert proof["leaked_namespaces"] == []
    for row in result.report["namespace_results"]:
        if row["namespace"] == ns:
            assert row["quarantined"] is True
        else:
            assert row["quarantined"] is False
        assert row["final_mode"] == "export-only"


# ---------------------------------------------------------------------------
# Receipt fail-closed gates
# ---------------------------------------------------------------------------


def test_require_canary_receipt_rejects_tampered_signature() -> None:
    result = canary.run_domain_canary(run_id="e2e-tamper")
    bad = dict(result.receipt)
    bad["run_id"] = "tampered-run"
    with pytest.raises(canary.ReceiptError, match="signature|receipt_id|digest"):
        canary.require_canary_receipt(bad)


def test_require_canary_receipt_rejects_wrong_interface() -> None:
    result = canary.run_domain_canary(run_id="e2e-wrong-iface")
    bad = dict(result.receipt)
    bad["interface"] = "NotACanaryReceipt@1"
    with pytest.raises(canary.ReceiptError):
        canary.require_canary_receipt(bad)


def test_build_canary_receipt_requires_exact_namespace_order() -> None:
    result = canary.run_domain_canary(run_id="e2e-partial-order")
    partial = list(result.receipt["namespace_results"])
    partial = list(reversed(partial))
    with pytest.raises(canary.ReceiptError, match="exactly|order"):
        canary.build_canary_receipt(
            run_id="partial",
            namespace_results=partial,
            isolation_proof=result.receipt["isolation_proof"],
            namespace_order=result.receipt["namespace_order"],
            ducklake_lineage=result.receipt["ducklake_lineage"],
            authority_install=result.receipt["authority_install"],
            inject_failure_namespace=result.receipt[
                "inject_failure_namespace"
            ],
        )


def test_build_canary_receipt_requires_isolation_proof() -> None:
    result = canary.run_domain_canary(run_id="e2e-no-iso")
    bad_iso = dict(result.receipt["isolation_proof"])
    bad_iso["isolation_proven"] = False
    with pytest.raises(canary.ReceiptError, match="isolation"):
        canary.build_canary_receipt(
            run_id="no-iso",
            namespace_results=result.receipt["namespace_results"],
            isolation_proof=bad_iso,
            namespace_order=result.receipt["namespace_order"],
            ducklake_lineage=result.receipt["ducklake_lineage"],
            authority_install=result.receipt["authority_install"],
            inject_failure_namespace=result.receipt[
                "inject_failure_namespace"
            ],
        )


# ---------------------------------------------------------------------------
# Single-namespace unit paths
# ---------------------------------------------------------------------------


def test_single_namespace_ladder_to_export_only() -> None:
    backend = MemoryAuthorityBackend()
    specs = canary.build_namespace_specs()
    state = canary.canary_one_namespace(
        backend,
        specs[0],
        run_id="unit-supervisor",
        inject_failure=False,
    )
    assert state.ok is True
    assert state.final_mode == "export-only"
    assert state.export_only_after_promotion is True
    assert len(state.steps) == 4
    assert state.port.mode is AuthorityMode.EXPORT_ONLY
    with pytest.raises(Exception, match="export-only|authority writes"):
        state.port.write(
            state.spec.sample_key,
            dict(state.spec.sample_payload),
            operation_id="op:should-fail",
        )


def test_isolation_proof_fails_when_quarantine_leaks() -> None:
    backend = MemoryAuthorityBackend()
    specs = canary.build_namespace_specs()
    results: list[Any] = []
    for spec in specs[:2]:
        state = canary.canary_one_namespace(
            backend,
            spec,
            run_id="unit-leak",
            inject_failure=(spec.namespace.value == "supervisor"),
        )
        results.append(state)
    # Leak quarantine into the second namespace domain.
    other = results[1]
    other.port.quarantine_disagreement(
        key=other.spec.sample_key,
        operation_id="op:leaked",
        reason="simulated-leak",
    )
    with pytest.raises(canary.IsolationError, match="leaked"):
        canary.prove_namespace_isolation(
            backend,
            failing_namespace="supervisor",
            all_results=results,
        )


def test_ducklake_namespace_requires_lineage_digest() -> None:
    backend = MemoryAuthorityBackend()
    dl = next(
        s
        for s in canary.build_namespace_specs()
        if s.namespace is canary.CanaryNamespace.DUCKLAKE
    )
    with pytest.raises(canary.CanaryError, match="lineage_digest"):
        canary.canary_one_namespace(
            backend,
            dl,
            run_id="unit-dl-missing-lineage",
            ducklake_lineage={"consumed_by": "DQK-053"},
        )


# ---------------------------------------------------------------------------
# Self-check / CLI
# ---------------------------------------------------------------------------


def test_self_check_passes() -> None:
    report = dict(canary.self_check())
    assert report["ok"] is True
    sc = report["self_check"]
    assert sc["ok"] is True
    assert sc["export_only"] is True
    assert sc["evidence_and_rollback"] is True
    assert sc["isolation_proven"] is True
    assert sc["database_native_stored"] is True


def test_cli_install_check_exit_zero() -> None:
    assert canary.main([]) == 0


def test_cli_emit_receipt_json() -> None:
    assert (
        canary.main(
            ["--emit-receipt", "--run-id", "e2e-cli", "--json"]
        )
        == 0
    )
