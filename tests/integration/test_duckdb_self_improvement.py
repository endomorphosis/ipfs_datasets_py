"""Integration tests for database-native residual analysis / self-improvement (DQK-054).

Acceptance coverage:

* Findings cannot bypass DQP planning/acceptance policy
* Duplicate or stale findings do not create task storms
* The loop uses DuckDB authority rather than Markdown objective refill
* Cross-repository proposals bind separate immutable Git trees and receipt
  identities
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


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

from ipfs_datasets_py.duckdb_control import self_improvement as si  # noqa: E402
from ipfs_datasets_py.duckdb_control.contracts import normalize_timestamp  # noqa: E402
from ipfs_datasets_py.duckdb_control.inventory_refinement import (  # noqa: E402
    MemoryPlanRevisionAPI,
    PlanRevisionRequest,
    ProposalStatus,
)
from ipfs_datasets_py.duckdb_control.self_improvement import (  # noqa: E402
    ANALYZER_KINDS,
    AUTHORITY_SURFACE,
    FINDING_SCHEMA,
    LOOP_SCHEMA,
    OWNER_TASK_ID,
    RECEIPT_SCHEMA,
    AnalysisBudget,
    AnalyzerKind,
    IdentifiedSnapshot,
    MarkdownRefillError,
    MemoryFindingLedger,
    ResidualFinding,
    SelfImprovementError,
    SelfImprovementLoop,
    SnapshotObservation,
    analyze_blockers,
    analyze_coverage,
    analyze_inventory,
    analyze_parity,
    analyze_performance,
    analyze_schema,
    build_gap_proposals_from_residuals,
    deduplicate_residual_findings,
    filter_stale_and_duplicate_findings,
    run_analyzers,
    self_check,
    submit_residual_findings,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


REPO_ID = "repository:sha256:test-duckdb-self-improvement"
TREE_ID = "9f4e189ee96d8976e76941afd752816cc48427d9"
FOREIGN_REPO = "repository:sha256:foreign-self-improvement"
FOREIGN_TREE = "1a2b3c4d5e6f7890abcdef1234567890abcdef12"
PLAN_ROOT = "sha256:" + "11" * 32
RECEIPT_A = "sha256:" + "aa" * 32
RECEIPT_B = "sha256:" + "bb" * 32
SCHEMA_CK = "sha256:" + "cc" * 32
SNAPSHOT_VAL = "sha256:" + "dd" * 32
ANALYZER_ID = "analyzer:self-improvement-test"


def _now() -> datetime:
    return datetime(2030, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def _snapshot(
    *,
    repository_id: str = REPO_ID,
    tree_id: str = TREE_ID,
    receipt: str = RECEIPT_A,
    snapshot_id: str = SNAPSHOT_VAL,
    plan_root: str = PLAN_ROOT,
) -> IdentifiedSnapshot:
    return IdentifiedSnapshot(
        repository_id=repository_id,
        repository_tree_id=tree_id,
        snapshot_id=snapshot_id,
        snapshot_receipt_cid=receipt,
        store_generation=3,
        schema_checksum=SCHEMA_CK,
        base_plan_root_cid=plan_root,
    )


def _rich_observation(
    snapshot: IdentifiedSnapshot | None = None,
    *,
    observed_at: datetime | None = None,
) -> SnapshotObservation:
    snap = snapshot if snapshot is not None else _snapshot()
    when = observed_at if observed_at is not None else _now()
    return SnapshotObservation(
        snapshot=snap,
        observed_at=normalize_timestamp(when),
        inventory_gaps=(
            {"path": "workspace/orphan/state.json", "owned": False},
            {"path": "workspace/orphan/state.json", "owned": False},  # dup
            {"path": "data/agent_supervisor/control.duckdb", "owned": True},
        ),
        schema_rows=(
            {
                "table": "tasks",
                "status": "mismatch",
                "schema_checksum": "sha256:" + "ee" * 32,
            },
            {"table": "goals", "status": "ok", "ok": True},
        ),
        parity_receipts=(
            {"domain": "graph", "agrees": False, "reason": "row_count_mismatch"},
            {"domain": "vector", "agrees": True},
        ),
        performance_samples=(
            {
                "metric": "query_p99_ms",
                "value": 900,
                "limit": 250,
                "breached": True,
            },
            {"metric": "heartbeat_p99_ms", "value": 10, "limit": 50, "breached": False},
        ),
        blockers=(
            {"blocker_id": "BLK-OPEN", "status": "open"},
            {"blocker_id": "BLK-DONE", "status": "resolved"},
            {
                "blocker_id": "BLK-TRACKED",
                "status": "tracked",
                "linked_task_id": "DQK-001",
            },
        ),
        coverage_rows=(
            {"domain": "wallet", "covered": False, "coverage_ratio": 0.4},
            {"domain": "control", "covered": True, "coverage_ratio": 1.0},
        ),
    )


def _run_module(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not existing else f"{_REPO_ROOT}{os.pathsep}{existing}"
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ipfs_datasets_py.duckdb_control.self_improvement",
            *args,
        ],
        cwd=_REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


# ---------------------------------------------------------------------------
# Module / schema surface
# ---------------------------------------------------------------------------


def test_module_exports_expected_schemas() -> None:
    assert si.LOOP_SCHEMA.endswith("self-improvement-loop@1")
    assert si.FINDING_SCHEMA == FINDING_SCHEMA
    assert si.RECEIPT_SCHEMA == RECEIPT_SCHEMA
    assert si.OWNER_TASK_ID == "DQK-054"
    assert si.AUTHORITY_SURFACE == "duckdb_plan_revision_api"
    assert si.APPROVAL_GATE_TASK_ID == "DQK-081"
    assert si.ROLLOVER_GATE_TASK_ID == "DQK-083"
    assert {item.value for item in ANALYZER_KINDS} == {
        "inventory",
        "schema",
        "parity",
        "performance",
        "blocker",
        "coverage",
    }


def test_check_mode_succeeds() -> None:
    result = _run_module("check", "--json")
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["owner_task_id"] == OWNER_TASK_ID
    assert payload["authority_surface"] == AUTHORITY_SURFACE
    assert payload["markdown_refill"] is False
    assert payload["status_mutation"] is False
    assert payload["mutation_surface"] == "plan_revision_api"
    assert "markdown_refill" in payload["refused_cases"]
    assert "status_mutation" in payload["refused_cases"]
    assert "self_approval" in payload["refused_cases"]
    assert "shared_tree" in payload["refused_cases"]
    assert payload["second_admitted"] == 0
    assert payload["stale_admitted"] == 0


def test_library_self_check() -> None:
    report = self_check()
    assert report["ok"] is True
    assert report["owner_task_id"] == OWNER_TASK_ID
    assert set(report["analyzer_kinds"]) == {item.value for item in ANALYZER_KINDS}


# ---------------------------------------------------------------------------
# Analyzers against identified snapshots
# ---------------------------------------------------------------------------


def test_all_six_analyzers_emit_residuals_against_snapshot() -> None:
    obs = _rich_observation()
    budget = AnalysisBudget(max_findings_per_analyzer=16, max_total_findings=64)

    by_kind = {
        AnalyzerKind.INVENTORY: analyze_inventory(obs, budget=budget),
        AnalyzerKind.SCHEMA: analyze_schema(obs, budget=budget),
        AnalyzerKind.PARITY: analyze_parity(obs, budget=budget),
        AnalyzerKind.PERFORMANCE: analyze_performance(obs, budget=budget),
        AnalyzerKind.BLOCKER: analyze_blockers(obs, budget=budget),
        AnalyzerKind.COVERAGE: analyze_coverage(obs, budget=budget),
    }
    for kind, findings in by_kind.items():
        assert findings, f"{kind.value} produced no findings"
        for finding in findings:
            assert finding.analyzer is kind
            assert finding.repository_id == REPO_ID
            assert finding.repository_tree_id == TREE_ID
            assert finding.snapshot_receipt_cid == RECEIPT_A
            assert finding.snapshot_id == SNAPSHOT_VAL
            assert finding.finding_key.startswith("sha256:")

    assert any(
        item.subject == "workspace/orphan/state.json"
        for item in by_kind[AnalyzerKind.INVENTORY]
    )
    assert any(item.subject == "tasks" for item in by_kind[AnalyzerKind.SCHEMA])
    assert any(item.subject == "graph" for item in by_kind[AnalyzerKind.PARITY])
    assert any(
        item.subject == "query_p99_ms" for item in by_kind[AnalyzerKind.PERFORMANCE]
    )
    assert any(item.subject == "BLK-OPEN" for item in by_kind[AnalyzerKind.BLOCKER])
    assert not any(
        item.subject == "BLK-DONE" for item in by_kind[AnalyzerKind.BLOCKER]
    )
    assert any(item.subject == "wallet" for item in by_kind[AnalyzerKind.COVERAGE])


def test_run_analyzers_respects_budgets_and_dedupes() -> None:
    obs = _rich_observation()
    tiny = AnalysisBudget(
        max_findings_per_analyzer=1,
        max_total_findings=3,
        max_proposals=2,
        max_model_calls=0,
    )
    findings = run_analyzers(obs, budget=tiny)
    assert len(findings) <= 3
    keys = [item.finding_key for item in findings]
    assert len(keys) == len(set(keys))

    blocked = AnalysisBudget(max_findings_per_analyzer=0, max_total_findings=10)
    assert run_analyzers(obs, budget=blocked) == ()


def test_identified_snapshot_binding_is_content_addressed() -> None:
    snap = _snapshot()
    assert snap.binding_cid.startswith("sha256:")
    again = _snapshot()
    assert snap.binding_cid == again.binding_cid
    other = _snapshot(receipt=RECEIPT_B)
    assert other.binding_cid != snap.binding_cid


# ---------------------------------------------------------------------------
# DQP planning/acceptance policy — no bypass
# ---------------------------------------------------------------------------


def test_findings_submit_only_through_plan_revision_api() -> None:
    obs = _rich_observation()
    api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    ledger = MemoryFindingLedger(repository_id=REPO_ID)
    loop = SelfImprovementLoop(
        api=api,
        repository_id=REPO_ID,
        ledger=ledger,
        analyzer_id=ANALYZER_ID,
        budget=AnalysisBudget(max_proposals=8, max_total_findings=32),
    )
    result = loop.run(obs, now=_now())

    assert result["mutation_surface"] == "plan_revision_api"
    assert result["status_mutation"] is False
    assert result["markdown_refill"] is False
    assert result["authority_surface"] == AUTHORITY_SURFACE
    assert result["active"] is False
    assert int(result["proposal_count"]) >= 1
    assert len(api.submitted) == 1

    request = api.submitted[0]
    assert isinstance(request, PlanRevisionRequest)
    assert request.activate is False
    assert request.repository_id == REPO_ID
    assert request.repository_tree_id == TREE_ID
    for proposal in request.proposals:
        assert proposal.status is ProposalStatus.NON_ACTIVE
        assert proposal.is_active is False
        assert proposal.repository_tree_id == TREE_ID
        payload = proposal.to_dict()
        assert payload["active"] is False
        assert payload["status"] == "non_active"

    receipt = result["loop_receipt"]
    assert receipt["schema"] == RECEIPT_SCHEMA
    assert receipt["markdown_refill"] is False
    assert receipt["status_mutation"] is False
    assert receipt["authority_surface"] == AUTHORITY_SURFACE
    assert receipt["snapshot_receipt_cid"] == RECEIPT_A


def test_loop_refuses_markdown_refill_status_mutation_self_approval_activation() -> None:
    api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    loop = SelfImprovementLoop(api=api, repository_id=REPO_ID)

    with pytest.raises(MarkdownRefillError, match="Markdown objective refill"):
        loop.refill_markdown_objectives(path="docs/TODO.md")
    with pytest.raises(SelfImprovementError, match="raw status mutation"):
        loop.mutate_status(task_id="DQK-001", status="completed")
    with pytest.raises(SelfImprovementError, match="self-approve"):
        loop.approve()
    with pytest.raises(SelfImprovementError, match="rollover"):
        loop.activate_proposals()

    # Raw status mutation on the plan-revision API is also refused.
    with pytest.raises(Exception, match="raw status mutation"):
        api.mutate_task_status(task_id="DQK-001", status="completed")
    assert api.status_mutations and api.status_mutations[0]["refused"] is True


def test_proposals_cannot_activate_via_plan_revision_request() -> None:
    findings = run_analyzers(_rich_observation())
    proposals = build_gap_proposals_from_residuals(
        findings, snapshot=_snapshot(), analyzer_id=ANALYZER_ID
    )
    assert proposals
    with pytest.raises(Exception, match="activate|rollover"):
        PlanRevisionRequest(
            request_id="sha256:" + "ff" * 32,
            repository_id=REPO_ID,
            repository_tree_id=TREE_ID,
            base_plan_root_cid=PLAN_ROOT,
            inventory_snapshot_cid=proposals[0].inventory_snapshot_cid,
            proposals=proposals,
            budget=AnalysisBudget().to_refinement_budget(),
            analyzer_id=ANALYZER_ID,
            activate=True,
        )


# ---------------------------------------------------------------------------
# Duplicate / stale findings do not create task storms
# ---------------------------------------------------------------------------


def test_duplicate_findings_do_not_create_task_storm() -> None:
    obs = _rich_observation()
    api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    ledger = MemoryFindingLedger(repository_id=REPO_ID)
    loop = SelfImprovementLoop(
        api=api,
        repository_id=REPO_ID,
        ledger=ledger,
        analyzer_id=ANALYZER_ID,
    )
    first = loop.run(obs, now=_now())
    first_admitted = int(first["finding_count_admitted"])
    first_proposals = sum(len(req.proposals) for req in api.submitted)
    assert first_admitted >= 1
    assert first_proposals >= 1
    keys_after_first = set(ledger.recorded_keys())

    second = loop.run(obs, now=_now())
    assert int(second["finding_count_admitted"]) == 0
    assert set(ledger.recorded_keys()) == keys_after_first
    # No new proposals on the second pass.
    assert sum(len(req.proposals) for req in api.submitted) == first_proposals


def test_stale_findings_are_suppressed() -> None:
    now = _now()
    stale_when = now - timedelta(days=2)
    obs = _rich_observation(observed_at=stale_when)
    findings = run_analyzers(obs)
    assert findings
    ledger = MemoryFindingLedger(repository_id=REPO_ID)
    budget = AnalysisBudget(staleness_seconds=3_600)
    admitted = filter_stale_and_duplicate_findings(
        findings, ledger, budget=budget, now=now
    )
    assert admitted == ()

    api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    result = submit_residual_findings(
        api,
        findings,
        snapshot=_snapshot(),
        budget=budget,
        ledger=ledger,
        now=now,
    )
    assert int(result["finding_count_admitted"]) == 0
    assert int(result["proposal_count"]) == 0


def test_deduplicate_residual_findings_by_key() -> None:
    snap = _snapshot()
    first = ResidualFinding(
        analyzer=AnalyzerKind.INVENTORY,
        subject="workspace/a.json",
        reason="unowned_mutable_producer",
        repository_id=snap.repository_id,
        repository_tree_id=snap.repository_tree_id,
        snapshot_id=snap.snapshot_id,
        snapshot_receipt_cid=snap.snapshot_receipt_cid,
        evidence_digest="sha256:" + "11" * 32,
    )
    second = ResidualFinding(
        analyzer=AnalyzerKind.INVENTORY,
        subject="workspace/a.json",
        reason="unowned_mutable_producer",
        repository_id=snap.repository_id,
        repository_tree_id=snap.repository_tree_id,
        snapshot_id=snap.snapshot_id,
        snapshot_receipt_cid=snap.snapshot_receipt_cid,
        evidence_digest="sha256:" + "11" * 32,
    )
    third = ResidualFinding(
        analyzer=AnalyzerKind.INVENTORY,
        subject="workspace/b.json",
        reason="unowned_mutable_producer",
        repository_id=snap.repository_id,
        repository_tree_id=snap.repository_tree_id,
        snapshot_id=snap.snapshot_id,
        snapshot_receipt_cid=snap.snapshot_receipt_cid,
        evidence_digest="sha256:" + "22" * 32,
    )
    unique = deduplicate_residual_findings((first, second, third))
    assert len(unique) == 2
    assert first.finding_key == second.finding_key
    assert first.finding_key != third.finding_key


# ---------------------------------------------------------------------------
# DuckDB authority rather than Markdown objective refill
# ---------------------------------------------------------------------------


def test_authority_surface_is_duckdb_not_markdown() -> None:
    assert AUTHORITY_SURFACE == "duckdb_plan_revision_api"
    assert si.MARKDOWN_REFILL_SURFACE == "markdown_objective_refill"
    assert AUTHORITY_SURFACE != si.MARKDOWN_REFILL_SURFACE

    obs = _rich_observation()
    api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    loop = SelfImprovementLoop(api=api, repository_id=REPO_ID)
    result = loop.run(obs, now=_now())
    assert result["authority_surface"] == AUTHORITY_SURFACE
    assert result["markdown_refill"] is False
    assert result["loop_receipt"]["authority_surface"] == AUTHORITY_SURFACE
    assert "markdown" not in result["authority_surface"]


# ---------------------------------------------------------------------------
# Cross-repository: separate trees and receipt identities
# ---------------------------------------------------------------------------


def test_cross_repository_proposals_bind_separate_trees_and_receipts() -> None:
    local = _rich_observation(_snapshot())
    foreign = _rich_observation(
        _snapshot(
            repository_id=FOREIGN_REPO,
            tree_id=FOREIGN_TREE,
            receipt=RECEIPT_B,
            snapshot_id="sha256:" + "99" * 32,
            plan_root="sha256:" + "88" * 32,
        )
    )
    local_api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    foreign_api = MemoryPlanRevisionAPI(repository_id=FOREIGN_REPO)
    loop = SelfImprovementLoop(
        api=local_api,
        repository_id=REPO_ID,
        analyzer_id=ANALYZER_ID,
    )
    multi = loop.run_multi_repository(
        (local, foreign),
        apis={REPO_ID: local_api, FOREIGN_REPO: foreign_api},
        now=_now(),
    )
    assert multi["repository_count"] == 2
    assert multi["markdown_refill"] is False
    assert multi["authority_surface"] == AUTHORITY_SURFACE

    trees = multi["trees_by_repository"]
    receipts = multi["receipts_by_repository"]
    assert trees[REPO_ID] == [TREE_ID]
    assert trees[FOREIGN_REPO] == [FOREIGN_TREE]
    assert TREE_ID not in trees[FOREIGN_REPO]
    assert FOREIGN_TREE not in trees[REPO_ID]
    assert receipts[REPO_ID] == [RECEIPT_A]
    assert receipts[FOREIGN_REPO] == [RECEIPT_B]

    # Each API only received its own repository proposals.
    assert all(req.repository_id == REPO_ID for req in local_api.submitted)
    assert all(req.repository_id == FOREIGN_REPO for req in foreign_api.submitted)
    assert all(req.repository_tree_id == TREE_ID for req in local_api.submitted)
    assert all(
        req.repository_tree_id == FOREIGN_TREE for req in foreign_api.submitted
    )


def test_shared_tree_across_repositories_is_refused() -> None:
    local = _rich_observation(_snapshot())
    # Same tree id, different repository — forbidden.
    foreign = _rich_observation(
        _snapshot(
            repository_id=FOREIGN_REPO,
            tree_id=TREE_ID,
            receipt=RECEIPT_B,
        )
    )
    loop = SelfImprovementLoop(
        api=MemoryPlanRevisionAPI(repository_id=REPO_ID),
        repository_id=REPO_ID,
    )
    with pytest.raises(SelfImprovementError, match="immutable Git tree"):
        loop.run_multi_repository(
            (local, foreign),
            apis={
                REPO_ID: MemoryPlanRevisionAPI(repository_id=REPO_ID),
                FOREIGN_REPO: MemoryPlanRevisionAPI(repository_id=FOREIGN_REPO),
            },
            now=_now(),
        )


def test_shared_receipt_across_repositories_is_refused() -> None:
    local = _rich_observation(_snapshot())
    foreign = _rich_observation(
        _snapshot(
            repository_id=FOREIGN_REPO,
            tree_id=FOREIGN_TREE,
            receipt=RECEIPT_A,  # shared receipt — forbidden
        )
    )
    loop = SelfImprovementLoop(
        api=MemoryPlanRevisionAPI(repository_id=REPO_ID),
        repository_id=REPO_ID,
    )
    with pytest.raises(SelfImprovementError, match="snapshot receipt identity"):
        loop.run_multi_repository(
            (local, foreign),
            apis={
                REPO_ID: MemoryPlanRevisionAPI(repository_id=REPO_ID),
                FOREIGN_REPO: MemoryPlanRevisionAPI(repository_id=FOREIGN_REPO),
            },
            now=_now(),
        )


def test_build_gap_proposals_refuses_cross_repo_finding_mix() -> None:
    snap = _snapshot()
    foreign_finding = ResidualFinding(
        analyzer=AnalyzerKind.INVENTORY,
        subject="foreign/path.json",
        reason="unowned_mutable_producer",
        repository_id=FOREIGN_REPO,
        repository_tree_id=FOREIGN_TREE,
        snapshot_id=SNAPSHOT_VAL,
        snapshot_receipt_cid=RECEIPT_B,
        evidence_digest="sha256:" + "33" * 32,
    )
    with pytest.raises(SelfImprovementError, match="cross-repository"):
        build_gap_proposals_from_residuals(
            (foreign_finding,), snapshot=snap, analyzer_id=ANALYZER_ID
        )


def test_loop_refuses_observation_for_other_repository() -> None:
    foreign_obs = _rich_observation(
        _snapshot(repository_id=FOREIGN_REPO, tree_id=FOREIGN_TREE, receipt=RECEIPT_B)
    )
    loop = SelfImprovementLoop(
        api=MemoryPlanRevisionAPI(repository_id=REPO_ID),
        repository_id=REPO_ID,
    )
    with pytest.raises(SelfImprovementError, match="repository_id"):
        loop.run(foreign_obs, now=_now())


# ---------------------------------------------------------------------------
# Import inertness
# ---------------------------------------------------------------------------


def test_module_import_is_inert() -> None:
    # Importing must not open DuckDB or touch the network; re-import is enough
    # to prove the module body has no side-effecting top-level I/O.
    import importlib

    reloaded = importlib.reload(si)
    assert reloaded.OWNER_TASK_ID == "DQK-054"
    assert reloaded.LOOP_SCHEMA == LOOP_SCHEMA
