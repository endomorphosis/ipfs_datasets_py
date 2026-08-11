"""E2E tests: DuckLake authority cutover controls (DQK-100).

Acceptance coverage:

* Completing DQK-100 does not alter production authority or disable a legacy
  producer
* Promotion is rejected without an unexpired independently signed DQK-102
  decision bound to exact actor/process birth, generation, repository tree,
  evidence set, and requested transition
* Cutover requires a fresh exact-HEAD producer scan or a signed baseline plus a
  complete content-addressed delta through HEAD
* A stale baseline, incomplete delta, or new/changed/unowned producer gap cannot
  authorize promotion
* Inventory gaps route to governed DQK-081 plan revision and DQK-083 generation
  rollover rather than retrying against a stale generation
* Every waiver in the resulting exact-tree inventory is current, reviewer-signed,
  path-scoped, justified, and expiring
* Synthetic-decision tests prove unregistered directory contents cannot silently
  enter a query and immutable source Parquet data remains content addressed
* A successful invocation emits a generation-fenced execution receipt binding
  before/after authorities and a bounded receipted rollback

Hermetic: no live DuckDB, no production promotion.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.ducklake import cutover as co
from ipfs_datasets_py.ducklake.adapters import (
    REGISTERED_PARQUET_PRODUCERS,
    WaiverValidationError,
    build_producer_waiver,
    list_registered_producers,
)
from ipfs_datasets_py.duckdb_control.contracts import content_identity


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

HEAD_TREE = "a" * 40
BASELINE_TREE = "b" * 40
MID_TREE = "c" * 40
PLAN_ROOT = "sha256:" + ("11" * 32)
GENERATION_ID = "generation:dqk100-active-1"
ACTOR = "actor:runtime-cutover-1"
IMPLEMENTER = "implementer:dqk-100-owner"
SIGNER = "reviewer:independent-dqk-102"
BASELINE_SIGNER = "reviewer:inventory-baseline"


@pytest.fixture(autouse=True)
def _reset_cutover_state() -> None:
    co.reset_cutover_state()
    yield
    co.reset_cutover_state()


def _digest(label: str) -> str:
    return content_identity({"label": label, "task": "DQK-100"})


def _producer_digests(suffix: str = "v1") -> dict[str, str]:
    return {
        pid: content_identity({"producer": pid, "suffix": suffix})
        for pid in REGISTERED_PARQUET_PRODUCERS
    }


def _birth(**kwargs: Any) -> co.ProcessBirth:
    defaults = dict(
        process_id="proc:cutover-test-1",
        boot_id="boot:cutover-test-1",
        started_at="2026-08-11T00:00:00Z",
        hostname="hermetic-test",
        pid=4242,
    )
    defaults.update(kwargs)
    return co.build_process_birth(**defaults)


def _fence(**kwargs: Any) -> co.GenerationFence:
    defaults = dict(
        generation_id=GENERATION_ID,
        repository_tree_id=HEAD_TREE,
        plan_root_cid=PLAN_ROOT,
        catalog_owner_generation=1,
    )
    defaults.update(kwargs)
    return co.build_generation_fence(**defaults)


def _evidence(
    *,
    tree: str = HEAD_TREE,
    generation_id: str = GENERATION_ID,
    **kwargs: Any,
) -> co.EvidenceBundle:
    defaults = dict(
        canary_receipt_cid=_digest("canary"),
        recovery_receipt_cid=_digest("recovery"),
        security_receipt_cid=_digest("security"),
        repository_tree_id=tree,
        generation_id=generation_id,
    )
    defaults.update(kwargs)
    return co.build_evidence_bundle(**defaults)


def _fresh_scan(
    *,
    head: str = HEAD_TREE,
    digests: dict[str, str] | None = None,
    waivers: list[dict[str, Any]] | None = None,
) -> co.ExactHeadProducerScan:
    return co.build_exact_head_scan(
        head_tree_id=head,
        producer_digests=digests or _producer_digests(),
        waivers=waivers or (),
    )


def _decision_for(
    *,
    birth: co.ProcessBirth | None = None,
    fence: co.GenerationFence | None = None,
    evidence: co.EvidenceBundle | None = None,
    inventory_proof_cid: str | None = None,
    actor: str = ACTOR,
    implementer: str = IMPLEMENTER,
    signer: str = SIGNER,
    **kwargs: Any,
) -> co.PromotionDecision:
    birth = birth or _birth()
    fence = fence or _fence()
    evidence = evidence or _evidence(
        tree=fence.repository_tree_id, generation_id=fence.generation_id
    )
    if inventory_proof_cid is None:
        scan = _fresh_scan(head=fence.repository_tree_id)
        inventory_proof_cid = scan.inventory_proof_cid
    return co.build_promotion_decision(
        actor_identity=actor,
        implementer_identity=implementer,
        signer_identity=signer,
        process_birth=birth,
        generation=fence,
        evidence=evidence,
        inventory_proof_cid=inventory_proof_cid,
        **kwargs,
    )


def _command(
    *,
    dry_run: bool = True,
    execute_process_local: bool = False,
    birth: co.ProcessBirth | None = None,
    fence: co.GenerationFence | None = None,
    decision: co.PromotionDecision | None = None,
    evidence: co.EvidenceBundle | None = None,
    scan: co.ExactHeadProducerScan | None = None,
    baseline: co.SignedInventoryBaseline | None = None,
    delta: co.ContentAddressedDelta | None = None,
    waivers: tuple = (),
    expected_producer_digests: dict[str, str] | None = None,
    actor: str = ACTOR,
) -> co.CutoverCommand:
    birth = birth or _birth()
    fence = fence or _fence()
    scan = scan
    if scan is None and baseline is None:
        scan = _fresh_scan(head=fence.repository_tree_id)
    evidence = evidence or _evidence(
        tree=fence.repository_tree_id, generation_id=fence.generation_id
    )
    inv_cid = (
        scan.inventory_proof_cid
        if scan is not None
        else (baseline.inventory_proof_cid if baseline is not None else _digest("inv"))
    )
    # For baseline+delta path, compute proof after apply inside invoke; bind
    # decision to a temporary proof that verify will re-check. Build decision
    # after we know inventory proof when possible.
    if decision is None:
        if scan is not None:
            inv_cid = scan.inventory_proof_cid
        decision = _decision_for(
            birth=birth,
            fence=fence,
            evidence=evidence,
            inventory_proof_cid=inv_cid,
            actor=actor,
        )
    return co.CutoverCommand(
        actor_identity=actor,
        process_birth=birth,
        generation=fence,
        decision=decision,
        evidence=evidence,
        head_tree_id=fence.repository_tree_id,
        exact_head_scan=scan,
        baseline=baseline,
        delta=delta,
        waivers=waivers,
        expected_producer_digests=expected_producer_digests,
        dry_run=dry_run,
        execute_process_local=execute_process_local,
    )


# ---------------------------------------------------------------------------
# Implementation non-authority
# ---------------------------------------------------------------------------


def test_self_check_implementation_grants_no_authority() -> None:
    report = co.self_check()
    assert report["ok"] is True
    assert report["owner_task_id"] == "DQK-100"
    assert report["promotion_gate_task_id"] == "DQK-102"
    assert report["plan_revision_task_id"] == "DQK-081"
    assert report["generation_rollover_task_id"] == "DQK-083"
    assert report["implementation_grants_no_authority"] is True
    assert co.IMPLEMENTATION_GRANTS_NO_AUTHORITY is True

    impl = co.implementation_self_check()
    assert impl["completing_dqk_100_alters_production_authority"] is False
    assert impl["completing_dqk_100_disables_legacy_producer"] is False


def test_completing_dqk100_does_not_alter_production_or_disable_legacy() -> None:
    # Import / self-check / default state: legacy fully enabled.
    assert co.authority_mode() is co.CutoverAuthorityMode.LEGACY
    assert co.legacy_producers_enabled() is True
    assert co.mutable_sidecar_authority_enabled() is True
    assert co.implicit_directory_scan_enabled() is True
    assert co.production_authority_unchanged() is True
    assert co.is_lake_authority_active() is False

    # Dry-run success still leaves legacy enabled and production untouched.
    result = co.dry_run_cutover(_command(dry_run=True))
    assert result.ok is True
    assert co.authority_mode() is co.CutoverAuthorityMode.LEGACY
    assert co.legacy_producers_enabled() is True
    assert co.production_authority_unchanged() is True

    # Registered producers still listed (not disabled by implementation).
    producers = list_registered_producers()
    assert len(producers) == 6
    assert "dataset_loader" in producers


# ---------------------------------------------------------------------------
# DQK-102 decision gate
# ---------------------------------------------------------------------------


def test_rejects_promotion_without_decision() -> None:
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _evidence()
    # Craft an empty/invalid decision mapping.
    with pytest.raises(co.PromotionDecisionError):
        co.verify_promotion_decision(
            {},
            process_birth=birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            actor_identity=ACTOR,
        )


def test_rejects_expired_decision() -> None:
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _evidence()
    issued = datetime.now(timezone.utc) - timedelta(hours=48)
    expires = datetime.now(timezone.utc) - timedelta(hours=1)
    decision = co.build_promotion_decision(
        actor_identity=ACTOR,
        implementer_identity=IMPLEMENTER,
        signer_identity=SIGNER,
        process_birth=birth,
        generation=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
        issued_at=issued,
        expires_at=expires,
    )
    with pytest.raises(co.PromotionDecisionError, match="expired"):
        co.verify_promotion_decision(
            decision,
            process_birth=birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            actor_identity=ACTOR,
        )


def test_rejects_self_signed_decision() -> None:
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _evidence()
    # Signer equals implementer — not independent.
    with pytest.raises(co.PromotionDecisionError, match="independent"):
        co.build_promotion_decision(
            actor_identity=ACTOR,
            implementer_identity=IMPLEMENTER,
            signer_identity=IMPLEMENTER,
            process_birth=birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
        )
    # Signer equals actor — not independent.
    with pytest.raises(co.PromotionDecisionError, match="independent"):
        co.build_promotion_decision(
            actor_identity=ACTOR,
            implementer_identity=IMPLEMENTER,
            signer_identity=ACTOR,
            process_birth=birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
        )


def test_rejects_decision_unbound_to_process_birth_or_generation() -> None:
    birth = _birth()
    other_birth = _birth(process_id="proc:other", boot_id="boot:other")
    fence = _fence()
    other_fence = _fence(generation_id="generation:other")
    scan = _fresh_scan()
    evidence = _evidence()
    decision = co.build_promotion_decision(
        actor_identity=ACTOR,
        implementer_identity=IMPLEMENTER,
        signer_identity=SIGNER,
        process_birth=birth,
        generation=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    with pytest.raises(co.PromotionDecisionError, match="process birth"):
        co.verify_promotion_decision(
            decision,
            process_birth=other_birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            actor_identity=ACTOR,
        )
    with pytest.raises(co.PromotionDecisionError, match="generation"):
        co.verify_promotion_decision(
            decision,
            process_birth=birth,
            generation=other_fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            actor_identity=ACTOR,
        )


def test_rejects_decision_unbound_to_evidence_or_inventory() -> None:
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _evidence()
    decision = co.build_promotion_decision(
        actor_identity=ACTOR,
        implementer_identity=IMPLEMENTER,
        signer_identity=SIGNER,
        process_birth=birth,
        generation=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    other_evidence = co.build_evidence_bundle(
        canary_receipt_cid=_digest("canary-other"),
        recovery_receipt_cid=_digest("recovery"),
        security_receipt_cid=_digest("security"),
        repository_tree_id=HEAD_TREE,
        generation_id=GENERATION_ID,
    )
    with pytest.raises(co.PromotionDecisionError, match="evidence"):
        co.verify_promotion_decision(
            decision,
            process_birth=birth,
            generation=fence,
            evidence=other_evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            actor_identity=ACTOR,
        )
    with pytest.raises(co.PromotionDecisionError, match="inventory"):
        co.verify_promotion_decision(
            decision,
            process_birth=birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=_digest("other-inventory"),
            actor_identity=ACTOR,
        )


def test_rejects_decision_wrong_transition_or_tree() -> None:
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _evidence()
    decision = co.build_promotion_decision(
        actor_identity=ACTOR,
        implementer_identity=IMPLEMENTER,
        signer_identity=SIGNER,
        process_birth=birth,
        generation=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    with pytest.raises(co.PromotionDecisionError, match="transition"):
        co.verify_promotion_decision(
            decision,
            process_birth=birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            actor_identity=ACTOR,
            expected_transition=("legacy", "legacy"),
        )


# ---------------------------------------------------------------------------
# Inventory: exact-HEAD or baseline+delta
# ---------------------------------------------------------------------------


def test_cutover_accepts_fresh_exact_head_scan() -> None:
    result = co.dry_run_cutover(_command(dry_run=True))
    assert result.ok is True
    assert result.dry_run is True
    assert result.before_authority == "legacy"
    assert result.after_authority == "lake_primary"
    assert result.inventory_proof_cid.startswith("sha256:")
    assert result.production_authority_unchanged is True
    assert co.authority_mode() is co.CutoverAuthorityMode.LEGACY


def test_cutover_accepts_signed_baseline_plus_complete_delta() -> None:
    base_digests = _producer_digests("baseline")
    # HEAD digests start equal to baseline; only one producer changes in the delta.
    head_digests = dict(base_digests)
    changed_pid = "dataset_loader"
    head_digests[changed_pid] = content_identity(
        {"producer": changed_pid, "suffix": "head-changed"}
    )

    baseline = co.build_signed_baseline(
        baseline_tree_id=BASELINE_TREE,
        producer_digests=base_digests,
        signer_identity=BASELINE_SIGNER,
    )
    delta = co.build_content_addressed_delta(
        from_tree_id=BASELINE_TREE,
        to_tree_id=HEAD_TREE,
        steps=[
            {
                "from_tree_id": BASELINE_TREE,
                "to_tree_id": MID_TREE,
                "producer_changes": {},
            },
            {
                "from_tree_id": MID_TREE,
                "to_tree_id": HEAD_TREE,
                "producer_changes": {changed_pid: head_digests[changed_pid]},
            },
        ],
        resulting_producer_digests=head_digests,
    )
    # Apply to get digests, then build proof for decision binding.
    applied = co.apply_content_addressed_delta(
        baseline, delta, head_tree_id=HEAD_TREE
    )
    assert applied[changed_pid] == head_digests[changed_pid]

    fence = _fence()
    birth = _birth()
    evidence = _evidence()
    # Build a temporary exact-head scan at HEAD for the inventory proof cid
    # used by the decision (same HEAD digests).
    scan_for_proof = co.build_exact_head_scan(
        head_tree_id=HEAD_TREE, producer_digests=head_digests
    )
    decision = co.build_promotion_decision(
        actor_identity=ACTOR,
        implementer_identity=IMPLEMENTER,
        signer_identity=SIGNER,
        process_birth=birth,
        generation=fence,
        evidence=evidence,
        inventory_proof_cid=scan_for_proof.inventory_proof_cid,
    )
    # For baseline+delta path, verify_inventory_through_head rebuilds proof;
    # bind decision to that rebuilt proof.
    proof_cid, digests, _ = co.verify_inventory_through_head(
        head_tree_id=HEAD_TREE,
        generation=fence,
        baseline=baseline,
        delta=delta,
    )
    decision = co.build_promotion_decision(
        actor_identity=ACTOR,
        implementer_identity=IMPLEMENTER,
        signer_identity=SIGNER,
        process_birth=birth,
        generation=fence,
        evidence=evidence,
        inventory_proof_cid=proof_cid,
    )
    cmd = co.CutoverCommand(
        actor_identity=ACTOR,
        process_birth=birth,
        generation=fence,
        decision=decision,
        evidence=evidence,
        head_tree_id=HEAD_TREE,
        exact_head_scan=None,
        baseline=baseline,
        delta=delta,
        dry_run=True,
        execute_process_local=False,
    )
    result = co.dry_run_cutover(cmd)
    assert result.ok is True
    assert result.inventory_proof_cid == proof_cid
    assert digests[changed_pid] == head_digests[changed_pid]


def test_stale_baseline_cannot_authorize_promotion() -> None:
    base_digests = _producer_digests("baseline")
    head_digests = dict(base_digests)
    # Baseline at wrong tree relative to delta start.
    baseline = co.build_signed_baseline(
        baseline_tree_id="d" * 40,  # stale / wrong
        producer_digests=base_digests,
        signer_identity=BASELINE_SIGNER,
    )
    delta = co.build_content_addressed_delta(
        from_tree_id=BASELINE_TREE,
        to_tree_id=HEAD_TREE,
        steps=[
            {
                "from_tree_id": BASELINE_TREE,
                "to_tree_id": HEAD_TREE,
                "producer_changes": {},
            }
        ],
        resulting_producer_digests=head_digests,
    )
    fence = _fence()
    with pytest.raises(co.CutoverBlockedError) as exc_info:
        co.verify_inventory_through_head(
            head_tree_id=HEAD_TREE,
            generation=fence,
            baseline=baseline,
            delta=delta,
        )
    err = exc_info.value
    assert err.reason in {"stale_baseline", "incomplete_delta", "changed_producer"}
    assert err.gap_routing["plan_revision_task_id"] == "DQK-081"
    assert err.gap_routing["generation_rollover_task_id"] == "DQK-083"
    assert err.gap_routing["retry_against_stale_generation_allowed"] is False


def test_incomplete_delta_cannot_authorize_promotion() -> None:
    base_digests = _producer_digests("baseline")
    head_digests = dict(base_digests)
    baseline = co.build_signed_baseline(
        baseline_tree_id=BASELINE_TREE,
        producer_digests=base_digests,
        signer_identity=BASELINE_SIGNER,
    )
    # Delta claims to_tree=HEAD but chain stops at MID_TREE.
    with pytest.raises(co.IncompleteDeltaError):
        co.build_content_addressed_delta(
            from_tree_id=BASELINE_TREE,
            to_tree_id=HEAD_TREE,
            steps=[
                {
                    "from_tree_id": BASELINE_TREE,
                    "to_tree_id": MID_TREE,
                    "producer_changes": {},
                }
            ],
            resulting_producer_digests=head_digests,
        )
    # Build a delta to MID then force-apply as if complete to HEAD.
    delta_partial = co.build_content_addressed_delta(
        from_tree_id=BASELINE_TREE,
        to_tree_id=MID_TREE,
        steps=[
            {
                "from_tree_id": BASELINE_TREE,
                "to_tree_id": MID_TREE,
                "producer_changes": {},
            }
        ],
        resulting_producer_digests=head_digests,
    )
    fence = _fence()
    with pytest.raises(co.CutoverBlockedError) as exc_info:
        co.verify_inventory_through_head(
            head_tree_id=HEAD_TREE,
            generation=fence,
            baseline=baseline,
            delta=delta_partial,
        )
    assert exc_info.value.gap_routing["plan_revision_task_id"] == "DQK-081"
    assert exc_info.value.gap_routing["generation_rollover_task_id"] == "DQK-083"


def test_new_changed_unowned_producer_gap_cannot_authorize() -> None:
    fence = _fence()
    digests = _producer_digests()
    scan = _fresh_scan(digests=digests)
    # Expected digests disagree (changed producer).
    expected = dict(digests)
    expected["dataset_saver"] = content_identity({"changed": True})
    with pytest.raises(co.CutoverBlockedError) as exc_info:
        co.verify_inventory_through_head(
            head_tree_id=HEAD_TREE,
            generation=fence,
            exact_head_scan=scan,
            expected_producer_digests=expected,
        )
    err = exc_info.value
    assert err.reason == "producer_inventory_gap"
    assert err.gap_routing["plan_revision_task_id"] == "DQK-081"
    assert err.gap_routing["generation_rollover_task_id"] == "DQK-083"
    assert err.gap_routing["retry_against_stale_generation_allowed"] is False
    kinds = {g["kind"] for g in err.gap_routing["gaps"]}
    assert "changed_producer" in kinds


def test_inventory_gaps_route_to_dqk081_and_dqk083() -> None:
    fence = _fence(generation_id="generation:stale-should-not-retry")
    gaps = [
        co.InventoryGap(
            kind=co.InventoryGapKind.UNOWNED_PRODUCER,
            path="unregistered/dir/data.parquet",
            detail="unowned public producer",
        )
    ]
    routing = co.route_inventory_gaps(gaps, generation=fence)
    assert routing.plan_revision_task_id == "DQK-081"
    assert routing.generation_rollover_task_id == "DQK-083"
    assert routing.requires_new_generation is True
    assert routing.retry_against_stale_generation_allowed is False
    assert routing.stale_generation_id == "generation:stale-should-not-retry"


# ---------------------------------------------------------------------------
# Waivers
# ---------------------------------------------------------------------------


def test_waivers_must_be_current_signed_path_scoped_justified_expiring() -> None:
    # Valid waiver.
    valid = build_producer_waiver(
        path="ipfs_datasets_py/experimental/orphan_parquet.py",
        producer_id="orphan",
        reviewer_id="reviewer:waiver-1",
        justification="temporary path-scoped waiver for experimental producer",
        repository_tree_id=HEAD_TREE,
    )
    verified = co.verify_waivers_current([valid], repository_tree_id=HEAD_TREE)
    assert len(verified) == 1
    assert verified[0].path.endswith("orphan_parquet.py")

    # Expired waiver rejected.
    issued = datetime.now(timezone.utc) - timedelta(days=2)
    expires = datetime.now(timezone.utc) - timedelta(hours=1)
    expired = build_producer_waiver(
        path="ipfs_datasets_py/experimental/old.py",
        producer_id="old",
        reviewer_id="reviewer:waiver-1",
        justification="expired waiver must not authorize cutover inventory",
        repository_tree_id=HEAD_TREE,
        issued_at=issued,
        expires_at=expires,
    )
    with pytest.raises(WaiverValidationError):
        co.verify_waivers_current([expired], repository_tree_id=HEAD_TREE)

    # Wrong tree rejected.
    other_tree_waiver = build_producer_waiver(
        path="ipfs_datasets_py/experimental/x.py",
        producer_id="x",
        reviewer_id="reviewer:waiver-1",
        justification="waiver bound to a different repository tree",
        repository_tree_id="e" * 40,
    )
    with pytest.raises(WaiverValidationError):
        co.verify_waivers_current(
            [other_tree_waiver], repository_tree_id=HEAD_TREE
        )


# ---------------------------------------------------------------------------
# Synthetic decision: query discovery + content addressing
# ---------------------------------------------------------------------------


def test_synthetic_decision_blocks_unregistered_directory_in_query() -> None:
    # Execute process-local promotion with a valid signed decision.
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _evidence()
    decision = co.build_promotion_decision(
        actor_identity=ACTOR,
        implementer_identity=IMPLEMENTER,
        signer_identity=SIGNER,
        process_birth=birth,
        generation=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    cmd = co.CutoverCommand(
        actor_identity=ACTOR,
        process_birth=birth,
        generation=fence,
        decision=decision,
        evidence=evidence,
        head_tree_id=HEAD_TREE,
        exact_head_scan=scan,
        dry_run=False,
        execute_process_local=True,
    )
    receipt = co.invoke_cutover(cmd)
    assert isinstance(receipt, co.ExecutionReceipt)
    assert receipt.after_authority == "lake_primary"
    assert receipt.production_authority_mutated is False
    assert co.is_lake_authority_active() is True
    assert co.legacy_producers_enabled() is False
    # Production flag remains false — hermetic only.
    assert co.production_authority_unchanged() is True

    with pytest.raises(co.CutoverBlockedError, match="unregistered"):
        co.assert_query_discovery_authorized(
            path="tmp/unregistered_scan/dataset/"
        )
    with pytest.raises(co.CutoverBlockedError, match="mutable sidecar"):
        co.assert_query_discovery_authorized(
            path="datasets.manifest.json",
            is_mutable_sidecar_manifest=True,
        )
    with pytest.raises(co.CutoverBlockedError, match="directory scan"):
        co.assert_query_discovery_authorized(
            path="data/",
            allow_directory_scan=True,
        )
    # Registered producer module path is still authorized.
    co.assert_query_discovery_authorized(
        path="ipfs_datasets_py/core_operations/dataset_loader.py"
    )


def test_synthetic_decision_keeps_parquet_content_addressed() -> None:
    payload = b"PAR1-immutable-parquet-bytes-for-dqk100"
    digest = co.digest_bytes(payload) if hasattr(co, "digest_bytes") else None
    from ipfs_datasets_py.ducklake.adapters import digest_bytes

    digest = digest_bytes(payload)
    assert co.assert_source_content_addressed(
        source_digest=digest, source_bytes=payload, media_type="parquet"
    ) == digest
    with pytest.raises(co.AuthorityCutoverError, match="content address"):
        co.assert_source_content_addressed(
            source_digest=digest,
            source_bytes=b"tampered-bytes",
            media_type="parquet",
        )


def test_maybe_enforce_lake_discovery_noop_under_legacy() -> None:
    assert co.is_lake_authority_active() is False
    assert (
        co.maybe_enforce_lake_discovery(
            producer_id="dataset_loader",
            path="tmp/unregistered/",
            uses_implicit_directory_scan=True,
            uses_mutable_sidecar=True,
        )
        is None
    )


# ---------------------------------------------------------------------------
# Successful invocation receipt + rollback
# ---------------------------------------------------------------------------


def test_successful_invocation_emits_execution_receipt_and_rollback() -> None:
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _evidence()
    decision = co.build_promotion_decision(
        actor_identity=ACTOR,
        implementer_identity=IMPLEMENTER,
        signer_identity=SIGNER,
        process_birth=birth,
        generation=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    cmd = co.CutoverCommand(
        actor_identity=ACTOR,
        process_birth=birth,
        generation=fence,
        decision=decision,
        evidence=evidence,
        head_tree_id=HEAD_TREE,
        exact_head_scan=scan,
        dry_run=False,
        execute_process_local=True,
    )
    receipt = co.invoke_cutover(cmd)
    assert isinstance(receipt, co.ExecutionReceipt)
    assert receipt.schema == co.EXECUTION_RECEIPT_SCHEMA
    assert receipt.before_authority == "legacy"
    assert receipt.after_authority == "lake_primary"
    assert receipt.decision_cid == decision.decision_cid
    assert receipt.process_birth_fingerprint == birth.fingerprint()
    assert receipt.generation_fingerprint == fence.fingerprint()
    assert receipt.repository_tree_id == HEAD_TREE
    assert receipt.rollback_fence_id
    assert receipt.rollback_window_hours >= 1
    assert receipt.post_transition_verification == "ok"
    assert receipt.production_authority_mutated is False
    assert receipt.dry_run is False
    assert set(receipt.changed_producers) == set(REGISTERED_PARQUET_PRODUCERS)
    assert receipt.receipt_cid.startswith("sha256:")
    assert receipt.signature.startswith("sha256:")

    # Bounded receipted rollback restores legacy (process-local).
    rb = co.rollback_cutover(
        execution=receipt,
        actor_identity=ACTOR,
        process_birth=birth,
        generation=fence,
    )
    assert isinstance(rb, co.RollbackReceipt)
    assert rb.schema == co.ROLLBACK_RECEIPT_SCHEMA
    assert rb.from_authority == "lake_primary"
    assert rb.to_authority == "legacy"
    assert rb.bounded_by_execution is True
    assert rb.execution_id == receipt.execution_id
    assert rb.decision_cid == decision.decision_cid
    assert rb.generation_fingerprint == fence.fingerprint()
    assert co.authority_mode() is co.CutoverAuthorityMode.LEGACY
    assert co.legacy_producers_enabled() is True
    assert co.production_authority_unchanged() is True


def test_rollback_rejects_mismatched_fence_or_dry_run() -> None:
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _evidence()
    decision = co.build_promotion_decision(
        actor_identity=ACTOR,
        implementer_identity=IMPLEMENTER,
        signer_identity=SIGNER,
        process_birth=birth,
        generation=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    cmd = co.CutoverCommand(
        actor_identity=ACTOR,
        process_birth=birth,
        generation=fence,
        decision=decision,
        evidence=evidence,
        head_tree_id=HEAD_TREE,
        exact_head_scan=scan,
        dry_run=False,
        execute_process_local=True,
    )
    receipt = co.invoke_cutover(cmd)
    assert isinstance(receipt, co.ExecutionReceipt)

    other_fence = _fence(generation_id="generation:other-rollback")
    with pytest.raises(co.CutoverBlockedError, match="generation"):
        co.rollback_cutover(
            execution=receipt,
            actor_identity=ACTOR,
            process_birth=birth,
            generation=other_fence,
        )

    # Dry-run result cannot be rolled back.
    co.reset_cutover_state()
    dry = co.dry_run_cutover(
        co.CutoverCommand(
            actor_identity=ACTOR,
            process_birth=birth,
            generation=fence,
            decision=decision,
            evidence=evidence,
            head_tree_id=HEAD_TREE,
            exact_head_scan=scan,
            dry_run=True,
        )
    )
    assert dry.ok is True
    with pytest.raises(co.CutoverBlockedError, match="execution receipt"):
        co.rollback_cutover(
            actor_identity=ACTOR,
            process_birth=birth,
            generation=fence,
        )


def test_default_invoke_is_dry_run_and_non_mutating() -> None:
    result = co.invoke_cutover(_command())
    assert isinstance(result, co.CutoverDryRunResult)
    assert result.ok is True
    assert result.dry_run is True
    assert co.authority_mode() is co.CutoverAuthorityMode.LEGACY
    assert co.production_authority_unchanged() is True


def test_retired_generation_cannot_fence_cutover() -> None:
    with pytest.raises(co.AuthorityCutoverError, match="retired generation"):
        co.build_generation_fence(
            generation_id=GENERATION_ID,
            repository_tree_id=HEAD_TREE,
            plan_root_cid=PLAN_ROOT,
            retired=True,
        )


def test_controller_verify_fails_closed_without_inventory_path() -> None:
    birth = _birth()
    fence = _fence()
    evidence = _evidence()
    # Decision with a dummy inventory proof; no scan or baseline.
    decision = co.build_promotion_decision(
        actor_identity=ACTOR,
        implementer_identity=IMPLEMENTER,
        signer_identity=SIGNER,
        process_birth=birth,
        generation=fence,
        evidence=evidence,
        inventory_proof_cid=_digest("orphan-proof"),
    )
    cmd = co.CutoverCommand(
        actor_identity=ACTOR,
        process_birth=birth,
        generation=fence,
        decision=decision,
        evidence=evidence,
        head_tree_id=HEAD_TREE,
        exact_head_scan=None,
        baseline=None,
        delta=None,
        dry_run=True,
    )
    result = co.dry_run_cutover(cmd)
    assert result.ok is False
    assert result.blockers
    assert co.authority_mode() is co.CutoverAuthorityMode.LEGACY
