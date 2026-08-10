"""Integration tests for inventory refinement / DQP plan-revision adapter (DQK-080).

Acceptance coverage:

* Adapter uses DQP's canonical plan-revision API rather than raw status mutation
* Proposals bind exact repository tree and inventory snapshot; non-active until
  DQK-083 rollover
* Budgets cap generated goals, tasks, depth, retries, and model calls
* No analyzer can self-approve or directly mutate another repository plan
* Verifier rejects unsigned, stale, mismatched, incomplete, or self-approved
  refinement receipts
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

# Prefer the sealed validator's accelerator checkout in nested worktrees.
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

from ipfs_datasets_py.duckdb_control.inventory import (
    ArtifactKind,
    InventoryRecord,
    ProposedAuthority,
)
from ipfs_datasets_py.duckdb_control import inventory_refinement as refinement
from ipfs_datasets_py.duckdb_control.inventory_refinement import (
    APPROVAL_RECEIPT_SCHEMA,
    OWNER_TASK_ID,
    PROPOSAL_STATUS_NON_ACTIVE,
    ROLLOVER_GATE_TASK_ID,
    VERIFICATION_SCHEMA,
    GapFinding,
    InventoryRefinementError,
    MemoryPlanRevisionAPI,
    PlanRevisionAdapter,
    PlanRevisionRequest,
    ProposalStatus,
    RefinementBudget,
    TaskEffectDeclaration,
    build_approval_receipt,
    build_gap_proposals,
    compare_inventory_to_effects,
    deduplicate_findings,
    inventory_snapshot_cid,
    self_check,
    submit_gap_proposals,
    verify_receipt,
    verify_signature,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


REPO_ID = "repository:sha256:test-duckdb-inventory-refinement"
TREE_ID = "9f4e189ee96d8976e76941afd752816cc48427d9"
PLAN_ROOT = "sha256:" + "11" * 32
ANALYZER_ID = "analyzer:inventory-refinement"
REVIEWER_ID = "reviewer:independent-dqk-081"


def _record(
    path: str,
    *,
    kind: ArtifactKind = ArtifactKind.MUTABLE_STATE,
    digest: str | None = None,
    authority: ProposedAuthority = ProposedAuthority.CONTROL_DUCKDB,
    producer: str = "test producer",
    consumer: str = "test consumer",
    size: int = 8,
) -> InventoryRecord:
    hex_digest = digest if digest is not None else (hashlib_for(path))
    return InventoryRecord(
        path=path,
        kind=kind,
        size=size,
        digest=hex_digest,
        producer=producer,
        consumer=consumer,
        proposed_authority=authority,
    )


def hashlib_for(path: str) -> str:
    import hashlib

    return hashlib.sha256(path.encode("utf-8")).hexdigest()


def _fresh_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return now - timedelta(minutes=1), now + timedelta(hours=2)


def _corpus() -> tuple[InventoryRecord, ...]:
    return (
        _record(
            "data/agent_supervisor/control.duckdb",
            authority=ProposedAuthority.CONTROL_DUCKDB,
        ),
        _record(
            "docs/architecture/PLAN.md",
            kind=ArtifactKind.AUTHORED_DOCUMENTATION,
            authority=ProposedAuthority.GIT_AUTHORED,
        ),
        _record(
            "workspace/orphan/state.json",
            authority=ProposedAuthority.RETAIN_FILE,
            producer="unclassified producer",
        ),
        _record(
            "ipfs_datasets_py/vector_stores/index.pkl",
            kind=ArtifactKind.UNSAFE_SERIALIZATION,
            authority=ProposedAuthority.QUARANTINE,
        ),
        _record(
            "archive/evidence/bundle.car",
            kind=ArtifactKind.IMMUTABLE_EVIDENCE,
            authority=ProposedAuthority.CONTENT_ADDRESSED,
        ),
    )


def _effects_covering_control() -> tuple[TaskEffectDeclaration, ...]:
    return (
        TaskEffectDeclaration(
            task_id="DQK-001",
            owned_paths=("data/agent_supervisor/",),
            repository_id=REPO_ID,
            goal_id="DQK-G100",
        ),
    )


def _valid_receipt(
    *,
    snapshot_cid: str,
    tree_id: str = TREE_ID,
    plan_root: str = PLAN_ROOT,
    unresolved_gap_count: int = 0,
    generation_changed: bool = False,
    generation_rollover_receipt_cid: str = "",
    reviewer_id: str = REVIEWER_ID,
    analyzer_id: str = ANALYZER_ID,
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    issued, expires = _fresh_window()
    if issued_at is not None:
        issued = issued_at
    if expires_at is not None:
        expires = expires_at
    return build_approval_receipt(
        repository_id=REPO_ID,
        repository_tree_id=tree_id,
        inventory_snapshot_cid=snapshot_cid,
        base_plan_root_cid=plan_root,
        accepted_plan_root_cid=plan_root,
        active_plan_root_cid=plan_root,
        reviewer_id=reviewer_id,
        analyzer_id=analyzer_id,
        unresolved_gap_count=unresolved_gap_count,
        generation_changed=generation_changed,
        generation_rollover_receipt_cid=generation_rollover_receipt_cid,
        issued_at=issued,
        expires_at=expires,
    )


def _run_module(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_REPO_ROOT) if not existing else f"{_REPO_ROOT}{os.pathsep}{existing}"
    )
    return subprocess.run(
        [sys.executable, "-m", "ipfs_datasets_py.duckdb_control.inventory_refinement", *args],
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
    assert refinement.REFINEMENT_SCHEMA.endswith("inventory-refinement@1")
    assert refinement.VERIFICATION_SCHEMA == (
        "ipfs_datasets_py/duckdb-control/inventory-refinement-verification@1"
    )
    assert refinement.APPROVAL_RECEIPT_SCHEMA == APPROVAL_RECEIPT_SCHEMA
    assert refinement.OWNER_TASK_ID == "DQK-080"
    assert refinement.ROLLOVER_GATE_TASK_ID == "DQK-083"
    assert refinement.PROPOSAL_STATUS_NON_ACTIVE == "non_active"
    assert refinement.SIGNATURE_ALGORITHM == "content-bound-sha256@1"


def test_check_mode_succeeds() -> None:
    result = _run_module("verify", "--check", "--json")
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["verification_schema"] == VERIFICATION_SCHEMA
    assert payload["mutation_surface"] == "plan_revision_api"
    assert payload["status_mutation"] is False
    assert "unsigned" in payload["rejected_cases"]
    assert "self_approved" in payload["rejected_cases"]
    assert "stale" in payload["rejected_cases"]
    assert "mismatched" in payload["rejected_cases"]
    assert "incomplete" in payload["rejected_cases"]


def test_library_self_check() -> None:
    report = self_check()
    assert report["ok"] is True
    assert report["owner_task_id"] == OWNER_TASK_ID
    assert report["rollover_gate_task_id"] == ROLLOVER_GATE_TASK_ID


# ---------------------------------------------------------------------------
# Inventory vs effect comparison
# ---------------------------------------------------------------------------


def test_compare_finds_unowned_mutable_producers() -> None:
    records = _corpus()
    effects = _effects_covering_control()
    findings = compare_inventory_to_effects(records, effects, repository_id=REPO_ID)
    paths = {item.path for item in findings}
    # Covered by DQK-001
    assert "data/agent_supervisor/control.duckdb" not in paths
    # Authored docs / immutable evidence do not require ownership
    assert "docs/architecture/PLAN.md" not in paths
    assert "archive/evidence/bundle.car" not in paths
    # Unowned mutable / unsafe
    assert "workspace/orphan/state.json" in paths
    assert "ipfs_datasets_py/vector_stores/index.pkl" in paths
    assert all(item.reason == "unowned_mutable_producer" for item in findings)


def test_foreign_repository_effects_do_not_cover_local_paths() -> None:
    records = (_record("data/agent_supervisor/control.duckdb"),)
    effects = (
        TaskEffectDeclaration(
            task_id="FOREIGN-1",
            owned_paths=("data/agent_supervisor/",),
            repository_id="repository:other",
        ),
    )
    findings = compare_inventory_to_effects(records, effects, repository_id=REPO_ID)
    assert len(findings) == 1
    assert findings[0].path == "data/agent_supervisor/control.duckdb"


def test_deduplicate_findings_by_path_and_digest() -> None:
    first = GapFinding(
        path="workspace/a.json",
        kind="mutable_state",
        digest="a" * 64,
        producer="p",
        consumer="c",
        proposed_authority="retain_file",
        reason="unowned_mutable_producer",
    )
    second = GapFinding(
        path="workspace/a.json",
        kind="mutable_state",
        digest="a" * 64,
        producer="p",
        consumer="c",
        proposed_authority="retain_file",
        reason="duplicate",
    )
    third = GapFinding(
        path="workspace/a.json",
        kind="mutable_state",
        digest="b" * 64,
        producer="p",
        consumer="c",
        proposed_authority="retain_file",
        reason="changed_digest",
    )
    unique = deduplicate_findings((first, second, third))
    assert len(unique) == 2
    assert unique[0].reason == "unowned_mutable_producer"
    digests = {item.digest for item in unique}
    assert digests == {"a" * 64, "b" * 64}


# ---------------------------------------------------------------------------
# Plan-revision adapter
# ---------------------------------------------------------------------------


def test_adapter_uses_plan_revision_api_not_status_mutation() -> None:
    api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    adapter = PlanRevisionAdapter(
        api=api,
        repository_id=REPO_ID,
        analyzer_id=ANALYZER_ID,
        budget=RefinementBudget(max_goals=8, max_tasks=16, max_depth=3, max_retries=1),
    )
    admission = adapter.refine(
        _corpus(),
        _effects_covering_control(),
        repository_tree_id=TREE_ID,
        base_plan_root_cid=PLAN_ROOT,
    )
    assert admission["mutation_surface"] == "plan_revision_api"
    assert admission["status_mutation"] is False
    assert admission["active"] is False
    assert admission["status"] == PROPOSAL_STATUS_NON_ACTIVE
    assert admission["proposal_count"] >= 1
    assert len(api.submitted) == 1
    request = api.submitted[0]
    assert isinstance(request, PlanRevisionRequest)
    assert request.activate is False
    assert request.repository_tree_id == TREE_ID
    assert request.inventory_snapshot_cid == inventory_snapshot_cid(_corpus())
    for proposal in request.proposals:
        assert proposal.status is ProposalStatus.NON_ACTIVE
        assert proposal.is_active is False
        assert proposal.repository_tree_id == TREE_ID
        assert proposal.inventory_snapshot_cid == request.inventory_snapshot_cid
        payload = proposal.to_dict()
        assert payload["active"] is False
        assert payload["rollover_gate"] == ROLLOVER_GATE_TASK_ID
        assert payload["status"] == "non_active"

    with pytest.raises(InventoryRefinementError, match="raw status mutation"):
        adapter.mutate_status(task_id="DQK-001", status="completed")
    with pytest.raises(InventoryRefinementError, match="raw status mutation"):
        api.mutate_task_status(task_id="DQK-001", status="completed")
    assert api.status_mutations and api.status_mutations[0]["refused"] is True


def test_proposals_remain_non_active_until_rollover() -> None:
    findings = compare_inventory_to_effects(
        _corpus(), _effects_covering_control(), repository_id=REPO_ID
    )
    snapshot = inventory_snapshot_cid(_corpus())
    proposals = build_gap_proposals(
        findings,
        repository_id=REPO_ID,
        repository_tree_id=TREE_ID,
        inventory_snapshot_cid=snapshot,
        base_plan_root_cid=PLAN_ROOT,
    )
    assert proposals
    for proposal in proposals:
        assert proposal.status is ProposalStatus.NON_ACTIVE
        assert proposal.is_active is False
    api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    with pytest.raises(InventoryRefinementError, match="rollover"):
        api.activate_proposals(proposals)


def test_budgets_cap_goals_tasks_depth_retries_and_model_calls() -> None:
    # Generate many unowned mutable paths.
    records = tuple(
        _record(f"workspace/gap/{index:03d}.json") for index in range(50)
    )
    tiny = RefinementBudget(
        max_goals=2,
        max_tasks=5,
        max_depth=1,
        max_retries=0,
        max_model_calls=0,
    )
    assert tiny.allows_model_calls is False
    snapshot = inventory_snapshot_cid(records)
    findings = compare_inventory_to_effects(records, (), repository_id=REPO_ID)
    assert len(findings) == 50
    proposals = build_gap_proposals(
        findings,
        repository_id=REPO_ID,
        repository_tree_id=TREE_ID,
        inventory_snapshot_cid=snapshot,
        base_plan_root_cid=PLAN_ROOT,
        budget=tiny,
    )
    # All findings share the workspace prefix → one goal group, capped by max_goals.
    assert len(proposals) <= tiny.max_goals
    total_tasks = sum(len(item.proposed_tasks) for item in proposals)
    total_findings = sum(len(item.findings) for item in proposals)
    assert total_tasks <= tiny.max_tasks
    assert total_findings <= tiny.max_tasks
    for proposal in proposals:
        assert proposal.depth <= tiny.max_depth
        assert proposal.budget.max_retries == 0
        assert proposal.budget.max_model_calls == 0

    blocked = RefinementBudget(
        max_goals=0, max_tasks=10, max_depth=2, max_retries=1, max_model_calls=0
    )
    assert (
        build_gap_proposals(
            findings,
            repository_id=REPO_ID,
            repository_tree_id=TREE_ID,
            inventory_snapshot_cid=snapshot,
            base_plan_root_cid=PLAN_ROOT,
            budget=blocked,
        )
        == ()
    )


def test_analyzer_cannot_self_approve() -> None:
    api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    adapter = PlanRevisionAdapter(api=api, repository_id=REPO_ID, analyzer_id=ANALYZER_ID)
    with pytest.raises(InventoryRefinementError, match="self-approve"):
        adapter.approve()
    with pytest.raises(InventoryRefinementError, match="self-approval"):
        build_approval_receipt(
            repository_id=REPO_ID,
            repository_tree_id=TREE_ID,
            inventory_snapshot_cid="sha256:" + "a" * 64,
            base_plan_root_cid=PLAN_ROOT,
            accepted_plan_root_cid=PLAN_ROOT,
            active_plan_root_cid=PLAN_ROOT,
            reviewer_id=ANALYZER_ID,
            analyzer_id=ANALYZER_ID,
        )


def test_analyzer_cannot_mutate_another_repository_plan() -> None:
    api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    foreign_findings = (
        GapFinding(
            path="foreign/path.json",
            kind="mutable_state",
            digest="c" * 64,
            producer="p",
            consumer="c",
            proposed_authority="retain_file",
            reason="unowned_mutable_producer",
        ),
    )
    foreign_proposals = build_gap_proposals(
        foreign_findings,
        repository_id="repository:foreign",
        repository_tree_id=TREE_ID,
        inventory_snapshot_cid="sha256:" + "d" * 64,
        base_plan_root_cid=PLAN_ROOT,
    )
    adapter = PlanRevisionAdapter(api=api, repository_id=REPO_ID, analyzer_id=ANALYZER_ID)
    with pytest.raises(InventoryRefinementError, match="another repository"):
        adapter.submit(foreign_proposals, base_plan_root_cid=PLAN_ROOT)

    # Direct API call with mismatched repository_id is also refused.
    with pytest.raises(InventoryRefinementError, match="another repository"):
        api.submit_plan_revision(
            PlanRevisionRequest(
                request_id="sha256:" + "e" * 64,
                repository_id="repository:foreign",
                repository_tree_id=TREE_ID,
                base_plan_root_cid=PLAN_ROOT,
                inventory_snapshot_cid="sha256:" + "d" * 64,
                proposals=foreign_proposals,
                budget=RefinementBudget(),
                analyzer_id=ANALYZER_ID,
            )
        )


def test_submit_gap_proposals_convenience() -> None:
    api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    findings = compare_inventory_to_effects(
        _corpus(), _effects_covering_control(), repository_id=REPO_ID
    )
    snapshot = inventory_snapshot_cid(_corpus())
    proposals = build_gap_proposals(
        findings,
        repository_id=REPO_ID,
        repository_tree_id=TREE_ID,
        inventory_snapshot_cid=snapshot,
        base_plan_root_cid=PLAN_ROOT,
    )
    admission = submit_gap_proposals(
        api,
        proposals,
        repository_id=REPO_ID,
        base_plan_root_cid=PLAN_ROOT,
    )
    assert admission["proposal_count"] == len(proposals)
    assert admission["status_mutation"] is False


# ---------------------------------------------------------------------------
# Receipt verification
# ---------------------------------------------------------------------------


def test_verify_accepts_valid_receipt() -> None:
    snapshot = inventory_snapshot_cid(_corpus())
    receipt = _valid_receipt(snapshot_cid=snapshot)
    verify_signature(receipt)
    verification = verify_receipt(
        receipt,
        expected_repository_tree_id=TREE_ID,
        expected_inventory_snapshot_cid=snapshot,
        expected_active_plan_root_cid=PLAN_ROOT,
        expected_accepted_plan_root_cid=PLAN_ROOT,
    )
    assert verification["schema"] == VERIFICATION_SCHEMA
    assert verification["accepted"] is True
    assert verification["inventory_snapshot_cid"] == snapshot
    assert verification["decision_cid"]
    assert verification["authorization_cid"]
    assert verification["unresolved_gap_count"] == 0
    assert verification["repository_tree_id"] == TREE_ID


def test_verify_rejects_unsigned_receipt() -> None:
    snapshot = inventory_snapshot_cid(_corpus())
    receipt = _valid_receipt(snapshot_cid=snapshot)
    receipt["signature"] = "sha256:" + "0" * 64
    with pytest.raises(InventoryRefinementError, match="signature"):
        verify_receipt(receipt)


def test_verify_rejects_stale_receipt() -> None:
    snapshot = inventory_snapshot_cid(_corpus())
    receipt = _valid_receipt(
        snapshot_cid=snapshot,
        issued_at=datetime(2000, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2000, 1, 2, tzinfo=timezone.utc),
    )
    with pytest.raises(InventoryRefinementError, match="stale|expired"):
        verify_receipt(receipt)


def test_verify_rejects_mismatched_tree() -> None:
    snapshot = inventory_snapshot_cid(_corpus())
    receipt = _valid_receipt(snapshot_cid=snapshot, tree_id="0" * 40)
    with pytest.raises(InventoryRefinementError, match="mismatched repository_tree"):
        verify_receipt(receipt, expected_repository_tree_id=TREE_ID)


def test_verify_rejects_mismatched_inventory_snapshot() -> None:
    snapshot = inventory_snapshot_cid(_corpus())
    receipt = _valid_receipt(snapshot_cid=snapshot)
    with pytest.raises(InventoryRefinementError, match="mismatched inventory_snapshot"):
        verify_receipt(
            receipt,
            expected_inventory_snapshot_cid="sha256:" + "f" * 64,
        )


def test_verify_rejects_incomplete_receipt() -> None:
    snapshot = inventory_snapshot_cid(_corpus())
    receipt = _valid_receipt(snapshot_cid=snapshot)
    del receipt["decision_cid"]
    with pytest.raises(InventoryRefinementError, match="incomplete"):
        verify_receipt(receipt)


def test_verify_rejects_self_approved_receipt() -> None:
    snapshot = inventory_snapshot_cid(_corpus())
    # Forge a sealed receipt that reuses analyzer as reviewer by rebuilding
    # after bypassing build_approval_receipt's guard.
    issued, expires = _fresh_window()
    base = build_approval_receipt(
        repository_id=REPO_ID,
        repository_tree_id=TREE_ID,
        inventory_snapshot_cid=snapshot,
        base_plan_root_cid=PLAN_ROOT,
        accepted_plan_root_cid=PLAN_ROOT,
        active_plan_root_cid=PLAN_ROOT,
        reviewer_id=REVIEWER_ID,
        analyzer_id=ANALYZER_ID,
        issued_at=issued,
        expires_at=expires,
    )
    forged = dict(base)
    forged["reviewer_id"] = ANALYZER_ID
    forged.pop("signature", None)
    forged.pop("receipt_cid", None)
    forged["signature"] = refinement.compute_signature(forged)
    forged["receipt_cid"] = refinement.compute_receipt_cid(forged)
    with pytest.raises(InventoryRefinementError, match="self-approved"):
        verify_receipt(forged)


def test_verify_rejects_generation_changed_without_rollover_cid() -> None:
    snapshot = inventory_snapshot_cid(_corpus())
    with pytest.raises(InventoryRefinementError, match="generation_rollover"):
        build_approval_receipt(
            repository_id=REPO_ID,
            repository_tree_id=TREE_ID,
            inventory_snapshot_cid=snapshot,
            base_plan_root_cid=PLAN_ROOT,
            accepted_plan_root_cid=PLAN_ROOT,
            active_plan_root_cid=PLAN_ROOT,
            reviewer_id=REVIEWER_ID,
            analyzer_id=ANALYZER_ID,
            generation_changed=True,
            generation_rollover_receipt_cid="",
        )


def test_cli_verify_receipt_json(tmp_path: Path) -> None:
    snapshot = inventory_snapshot_cid(_corpus())
    receipt = _valid_receipt(snapshot_cid=snapshot)
    path = tmp_path / "refinement-receipt.json"
    path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    result = _run_module(
        "verify",
        "--receipt",
        str(path),
        "--repository-tree-id",
        TREE_ID,
        "--inventory-snapshot-cid",
        snapshot,
        "--active-plan-root-cid",
        PLAN_ROOT,
        "--accepted-plan-root-cid",
        PLAN_ROOT,
        "--json",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["schema"] == VERIFICATION_SCHEMA
    assert payload["accepted"] is True
    assert payload["inventory_snapshot_cid"] == snapshot
    assert payload["decision_cid"]
    assert payload["authorization_cid"]


def test_cli_rejects_unsigned_receipt(tmp_path: Path) -> None:
    snapshot = inventory_snapshot_cid(_corpus())
    receipt = _valid_receipt(snapshot_cid=snapshot)
    receipt["signature"] = "sha256:" + "0" * 64
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    result = _run_module("verify", "--receipt", str(path), "--json")
    assert result.returncode != 0
    assert "signature" in (result.stderr or result.stdout).lower() or "error" in (
        result.stderr or ""
    )


def test_empty_findings_submit_is_non_active_noop() -> None:
    api = MemoryPlanRevisionAPI(repository_id=REPO_ID)
    adapter = PlanRevisionAdapter(api=api, repository_id=REPO_ID, analyzer_id=ANALYZER_ID)
    # Full coverage: every mutable path owned.
    records = (
        _record("data/agent_supervisor/control.duckdb"),
    )
    effects = (
        TaskEffectDeclaration(
            task_id="DQK-001",
            owned_paths=("data/agent_supervisor/",),
            repository_id=REPO_ID,
        ),
    )
    admission = adapter.refine(
        records,
        effects,
        repository_tree_id=TREE_ID,
        base_plan_root_cid=PLAN_ROOT,
    )
    assert admission["proposal_count"] == 0
    assert admission["active"] is False
    assert admission["status_mutation"] is False
    assert api.submitted == []
