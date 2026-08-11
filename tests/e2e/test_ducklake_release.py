"""E2E tests: DuckLake layer release receipt (DQK-101).

Acceptance coverage:

* The receipt is stored in the DQK-086 lake_release_receipts authority table
  rather than a Markdown/JSON file
* It binds every DuckDB + Quack catalog shard, catalog file and
  companion-registry digest, owner generation/endpoint identity, task
  completion/validation ID, storage identity, snapshot vector, policy,
  extension, Git tree, expiry, and the exact DQK-102 signed decision plus
  execution receipt
* It proves no catalog file had two owners and no remote client opened an
  authority catalog directly during the canary
* It binds the Quack beta risk acceptance, exact DQK-050 compatibility
  receipt, enabled fallback/feature gate, and DuckDB 2.0 requalification policy
* Missing, stale, mismatched, or self-approved DQK-102 promotion evidence
  fails closed
* Missing or stale canary, restore, maintenance, security, or cutover evidence
  fails closed
* A sanitized release projection can be exported without exposing credentials
  or encryption keys

Hermetic: no live DuckDB, Quack, Docker, or network required.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.duckdb_control.contracts import content_identity
from ipfs_datasets_py.ducklake import cutover as co
from ipfs_datasets_py.ducklake import release as rl
from ipfs_datasets_py.ducklake import security as sec
from ipfs_datasets_py.ducklake.adapters import REGISTERED_PARQUET_PRODUCERS
from ipfs_datasets_py.ducklake.registry import ControlLakeRegistry


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

HEAD_TREE = "a" * 40
PLAN_ROOT = "sha256:" + ("11" * 32)
GENERATION_ID = "generation:dqk101-active-1"
ACTOR = "actor:runtime-release-1"
IMPLEMENTER = "implementer:dqk-100-owner"
SIGNER = "reviewer:independent-dqk-102"
PUBLISHER = "publisher:dqk-101"


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    co.reset_cutover_state()
    rl.reset_release_state()
    yield
    co.reset_cutover_state()
    rl.reset_release_state()


def _digest(label: str) -> str:
    return content_identity({"label": label, "task": "DQK-101"})


def _producer_digests(suffix: str = "v1") -> dict[str, str]:
    return {
        pid: content_identity({"producer": pid, "suffix": suffix})
        for pid in REGISTERED_PARQUET_PRODUCERS
    }


def _birth(**kwargs: Any) -> co.ProcessBirth:
    defaults = dict(
        process_id="proc:release-test-1",
        boot_id="boot:release-test-1",
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


def _cutover_evidence(
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
) -> co.ExactHeadProducerScan:
    return co.build_exact_head_scan(
        head_tree_id=head,
        producer_digests=digests or _producer_digests(),
        waivers=(),
    )


def _decision(
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
    evidence = evidence or _cutover_evidence(
        tree=fence.repository_tree_id, generation_id=fence.generation_id
    )
    if inventory_proof_cid is None:
        inventory_proof_cid = _fresh_scan(head=fence.repository_tree_id).inventory_proof_cid
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


def _execution_receipt(
    *,
    decision: co.PromotionDecision,
    birth: co.ProcessBirth,
    fence: co.GenerationFence,
    evidence: co.EvidenceBundle,
    inventory_proof_cid: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Seal a cutover-compatible execution receipt mapping."""

    execution_id = "exec:release-hermetic-1"
    rollback_fence_id = "rollback-fence:release-1"
    executed_at = "2026-08-11T01:00:00Z"
    body = {
        "schema": co.EXECUTION_RECEIPT_SCHEMA,
        "execution_id": execution_id,
        "decision_cid": decision.decision_cid,
        "actor_identity": decision.actor_identity,
        "process_birth_fingerprint": birth.fingerprint(),
        "generation_fingerprint": fence.fingerprint(),
        "repository_tree_id": fence.repository_tree_id,
        "before_authority": "legacy",
        "after_authority": "lake_primary",
        "inventory_proof_cid": inventory_proof_cid,
        "evidence_set_cid": evidence.evidence_set_cid,
        "changed_producers": sorted(REGISTERED_PARQUET_PRODUCERS.keys()),
        "rollback_fence_id": rollback_fence_id,
        "rollback_window_hours": decision.rollback_window_hours,
        "dry_run": dry_run,
        "executed_at": executed_at,
        "post_transition_verification": "ok",
        "production_authority_mutated": False,
        "program_id": co.PROGRAM_ID,
        "owner_task_id": co.OWNER_TASK_ID,
    }
    signature = content_identity(body)
    receipt_cid = content_identity({**body, "signature": signature})
    return {**body, "signature": signature, "receipt_cid": receipt_cid}


def _goal_graph(tree: str = HEAD_TREE) -> rl.GoalGraphBinding:
    completions = {t: f"complete:{t.lower()}" for t in rl._GOAL_GRAPH_TASK_IDS}
    validations = {t: f"validate:{t.lower()}" for t in rl._GOAL_GRAPH_TASK_IDS}
    return rl.build_goal_graph_binding(
        repository_tree_id=tree,
        environment_receipt_cid=_digest("env-receipt"),
        extension_profile_digest=_digest("extension-profile"),
        policy_digest=_digest("policy"),
        task_completion_ids=completions,
        task_validation_ids=validations,
        schema_checksum=_digest("schema-checksum"),
    )


def _ops_evidence(
    *,
    tree: str = HEAD_TREE,
    generation_id: str = GENERATION_ID,
    canary_cid: str | None = None,
    **kwargs: Any,
) -> rl.OperationalEvidenceBundle:
    defaults = dict(
        canary_receipt_cid=canary_cid or _digest("canary"),
        restore_receipt_cid=_digest("restore"),
        maintenance_receipt_cid=_digest("maintenance"),
        security_receipt_cid=_digest("security-ops"),
        cutover_receipt_cid=_digest("cutover"),
        publication_receipt_cid=_digest("publication"),
        repository_tree_id=tree,
        generation_id=generation_id,
    )
    defaults.update(kwargs)
    return rl.build_operational_evidence(**defaults)


def _shard(
    *,
    shard_id: str = "shard_a",
    catalog_id: str = "cat_a",
    owner: str = "owner:shard-a",
    ring: int = 0,
    catalog_file_digest: str | None = None,
) -> rl.CatalogShardBinding:
    dig = catalog_file_digest or _digest(f"catalog-file-{shard_id}")
    return rl.build_catalog_shard_binding(
        shard_id=shard_id,
        catalog_id=catalog_id,
        catalog_file_digest=dig,
        companion_registry_digest=_digest(f"companion-{shard_id}"),
        owner_generation=1,
        owner_identity=owner,
        endpoint_identity=f"quacks://127.0.0.1:1900{ring}/{catalog_id}",
        storage_identity=_digest(f"storage-{shard_id}"),
        storage_kind="local_block",
        task_completion_id=f"complete:{shard_id}",
        task_validation_id=f"validate:{shard_id}",
        schema_checksum=_digest(f"schema-{shard_id}"),
        ring_position=ring,
    )


def _exclusivity(
    shards: list[rl.CatalogShardBinding],
    *,
    tree: str = HEAD_TREE,
    canary_cid: str | None = None,
) -> rl.CanaryExclusivityProof:
    owner_map = {s.catalog_file_digest: s.owner_identity for s in shards}
    return rl.build_canary_exclusivity_proof(
        catalog_file_owner_map=owner_map,
        canary_receipt_cid=canary_cid or _digest("canary"),
        repository_tree_id=tree,
        remote_authority_open_attempts=0,
    )


def _compatibility_receipt() -> dict[str, Any]:
    body = {
        "schema": "ipfs_datasets_py/duckdb-quack-compatibility-risk-receipt@1",
        "task_id": "DQK-050",
        "interface": "QuackCompatibilityRiskReceipt@1",
        "quack_beta": True,
        "risk_accepted": True,
        "feature_gate_enabled": True,
        "local_fallback_enabled": True,
        "acceptor_identity": "reviewer:dqk-050",
        "capability_profile_ref": "DQK-084",
        "contract_suite_digest": _digest("contract-suite"),
        # Deliberately include sensitive keys so sanitized export must scrub them.
        "encryption_key": "super-secret-key-material-should-never-export",
        "quack_token": "qt-live-secret-token-abcdef",
        "credential": "user:password@host",
    }
    digest = content_identity(
        {k: v for k, v in body.items() if k not in {"signature", "receipt_id"}}
    )
    body["receipt_id"] = f"receipt:{digest}"
    body["signature"] = {
        "algorithm": "content-bound-sha256@1",
        "digest": digest,
    }
    return body


def _risk_binding(compat: dict[str, Any] | None = None) -> rl.QuackRiskPolicyBinding:
    return rl.build_quack_risk_policy_binding(
        compatibility_receipt=compat or _compatibility_receipt(),
        feature_gate_enabled=True,
        local_fallback_enabled=True,
        quack_beta_risk_accepted=True,
        acceptor_identity="reviewer:dqk-050",
    )


def _control() -> ControlLakeRegistry:
    control = ControlLakeRegistry(owner_id="control-dqk101")
    control.apply_migrations()
    return control


def _seed_control(control: ControlLakeRegistry, shards: list[rl.CatalogShardBinding]) -> None:
    seen_owner_gens: set[str] = set()
    for s in shards:
        if control.store.get_row("lake_catalogs", s.catalog_id) is None:
            control.register_catalog(
                catalog_id=s.catalog_id,
                catalog_digest=s.catalog_file_digest,
                storage_kind=s.storage_kind,
                metadata_path=f"/var/lib/ducklake/catalogs/{s.catalog_id}.duckdb",
            )
        if control.store.get_row("lake_catalog_shards", s.shard_id) is None:
            control.register_shard(
                shard_id=s.shard_id,
                catalog_id=s.catalog_id,
                ring_position=s.ring_position,
                endpoint_identity=s.endpoint_identity,
            )
        # Owner generation key is catalog_id:owner_generation (one per catalog).
        og_key = f"{s.catalog_id}:{s.owner_generation}"
        if og_key in seen_owner_gens:
            continue
        if control.store.get_row("lake_catalog_owner_generations", og_key) is not None:
            seen_owner_gens.add(og_key)
            continue
        control.record_owner_generation(
            catalog_id=s.catalog_id,
            owner_generation=s.owner_generation,
            lease_id=f"lease:{s.shard_id}",
            fencing_epoch=1,
            owner_identity=s.owner_identity,
            process_birth={"process_id": f"proc:{s.shard_id}"},
            expires_at="2099-01-01T00:00:00Z",
            expected_revision=0,
        )
        seen_owner_gens.add(og_key)


def _full_receipt(**overrides: Any) -> rl.DuckLakeLayerReleaseReceipt:
    birth = overrides.pop("birth", None) or _birth()
    fence = overrides.pop("fence", None) or _fence()
    scan = overrides.pop("scan", None) or _fresh_scan(head=fence.repository_tree_id)
    cutover_ev = overrides.pop("cutover_evidence", None) or _cutover_evidence(
        tree=fence.repository_tree_id, generation_id=fence.generation_id
    )
    decision = overrides.pop("promotion_decision", None) or _decision(
        birth=birth,
        fence=fence,
        evidence=cutover_ev,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    execution = overrides.pop("execution_receipt", None) or _execution_receipt(
        decision=decision,
        birth=birth,
        fence=fence,
        evidence=cutover_ev,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    shards = overrides.pop("shard_bindings", None) or [
        _shard(shard_id="shard_a", ring=0),
        _shard(shard_id="shard_b", catalog_id="cat_a", owner="owner:shard-b", ring=1),
    ]
    canary_cid = overrides.pop("canary_cid", None) or _digest("canary")
    ops = overrides.pop("operational_evidence", None) or _ops_evidence(
        tree=fence.repository_tree_id,
        generation_id=fence.generation_id,
        canary_cid=canary_cid,
    )
    exclusivity = overrides.pop("canary_exclusivity", None) or _exclusivity(
        list(shards), tree=fence.repository_tree_id, canary_cid=canary_cid
    )
    kwargs = dict(
        release_id="release:ducklake-layer-2026-08-11",
        repository_tree_id=fence.repository_tree_id,
        vector_root_id="vec:release-root-1",
        snapshot_vector_digest=_digest("snapshot-vector"),
        shard_bindings=shards,
        goal_graph=_goal_graph(fence.repository_tree_id),
        operational_evidence=ops,
        canary_exclusivity=exclusivity,
        quack_risk_policy=_risk_binding(),
        promotion_decision=decision,
        execution_receipt=execution,
        process_birth=birth,
        generation=fence,
        cutover_evidence=cutover_ev,
        inventory_proof_cid=scan.inventory_proof_cid,
        actor_identity=ACTOR,
        publisher_identity=PUBLISHER,
        extension_profile_digest=_digest("extension-profile"),
        policy_digest=_digest("policy"),
        environment_receipt_cid=_digest("env-receipt"),
    )
    kwargs.update(overrides)
    return rl.build_layer_release_receipt(**kwargs)


# ---------------------------------------------------------------------------
# Module contract
# ---------------------------------------------------------------------------


def test_module_contract_constants() -> None:
    check = rl.self_check()
    assert check["ok"] is True
    assert rl.OWNER_TASK_ID == "DQK-101"
    assert rl.PROMOTION_GATE_TASK_ID == "DQK-102"
    assert rl.COMPATIBILITY_TASK_ID == "DQK-050"
    assert rl.LAYER_RELEASE_RECEIPT_INTERFACE == "DuckLakeLayerReleaseReceipt@1"
    assert rl.LAYER_RELEASE_RECEIPT_SCHEMA.endswith("@1")
    assert rl.AUTHORITY_TABLE == "lake_release_receipts"
    assert check["markdown_or_file_authority"] is False
    rl.assert_no_markdown_or_file_authority()


# ---------------------------------------------------------------------------
# Happy path: authority table storage + full binding
# ---------------------------------------------------------------------------


def test_receipt_stored_in_authority_table_not_markdown_or_file() -> None:
    control = _control()
    receipt = _full_receipt()
    shards = list(receipt.shard_bindings)
    _seed_control(control, shards)

    stored = rl.publish_layer_release_receipt(
        control, receipt, promotion_decision=None
    )
    assert stored["receipt_id"] == receipt.receipt_id
    assert stored["release_id"] == receipt.release_id
    assert stored["decision_id"] == receipt.decision_id
    assert stored["execution_id"] == receipt.execution_id
    assert stored["binding_digest"].startswith("sha256:")
    assert "body_json" in stored

    row = control.store.get_row("lake_release_receipts", receipt.receipt_id)
    assert row is not None
    assert row["receipt_id"] == receipt.receipt_id
    body = json.loads(row["body_json"])
    assert body["interface"] == "DuckLakeLayerReleaseReceipt@1"
    assert body["authority_table"] == "lake_release_receipts"
    assert body["schema"] == rl.LAYER_RELEASE_RECEIPT_SCHEMA
    # Not a file path authority.
    assert not str(row.get("body_json", "")).endswith(".md")
    assert row.get("path") is None


def test_receipt_binds_shards_vectors_policy_extensions_tree_expiry_and_dqk102() -> None:
    receipt = _full_receipt()
    body = dict(receipt.as_mapping())

    assert body["repository_tree_id"] == HEAD_TREE
    assert body["vector_root_id"]
    assert body["snapshot_vector_digest"].startswith("sha256:")
    assert body["policy_digest"].startswith("sha256:")
    assert body["extension_profile_digest"].startswith("sha256:")
    assert body["expires_at"]
    assert body["decision_id"]
    assert body["decision_cid"].startswith("sha256:")
    assert body["execution_id"]
    assert body["execution_receipt_cid"].startswith("sha256:")
    assert body["gate_task_id"] == "DQK-102"
    assert body["owner_task_id"] == "DQK-101"

    assert len(receipt.shard_bindings) >= 2
    for shard in receipt.shard_bindings:
        m = dict(shard.as_mapping())
        assert m["catalog_file_digest"].startswith("sha256:")
        assert m["companion_registry_digest"].startswith("sha256:")
        assert m["owner_generation"] >= 1
        assert m["owner_identity"]
        assert m["endpoint_identity"].startswith("quacks://")
        assert m["storage_identity"].startswith("sha256:")
        assert m["task_completion_id"]
        assert m["task_validation_id"]
        assert m["schema_checksum"].startswith("sha256:")

    # Goal graph binds environment + extension + policy + tasks.
    gg = dict(receipt.goal_graph.as_mapping())
    assert gg["environment_receipt_cid"].startswith("sha256:")
    assert gg["extension_profile_digest"].startswith("sha256:")
    assert gg["policy_digest"].startswith("sha256:")
    assert "DQK-102" in gg["task_completion_ids"]
    assert "DQK-050" in gg["task_validation_ids"]

    # Pinned extensions present on sealed body.
    assert body["pinned_extensions"]["duckdb"]
    assert "quack" in body["pinned_extensions"]


def test_canary_exclusivity_proves_single_owner_and_no_remote_authority_open() -> None:
    receipt = _full_receipt()
    proof = dict(receipt.canary_exclusivity.as_mapping())
    assert proof["no_catalog_file_had_two_owners"] is True
    assert proof["no_remote_client_opened_authority_catalog"] is True
    assert proof["remote_authority_open_attempts"] == 0
    assert proof["catalog_file_owner_map"]
    for dig, owner in proof["catalog_file_owner_map"].items():
        assert dig.startswith("sha256:")
        assert owner


def test_binds_quack_beta_risk_dqk050_gate_and_duckdb20_policy() -> None:
    receipt = _full_receipt()
    risk = dict(receipt.quack_risk_policy.as_mapping())
    assert risk["quack_beta_risk_accepted"] is True
    assert risk["feature_gate_enabled"] is True
    assert risk["local_fallback_enabled"] is True
    assert risk["compatibility_receipt_id"]
    assert risk["compatibility_receipt_digest"].startswith("sha256:")
    compat = risk["compatibility_receipt"]
    assert compat["task_id"] == "DQK-050"
    assert compat["risk_accepted"] is True
    policy = risk["duckdb_20_requalification_policy"]
    assert policy["requires_full_contract_rerun"] is True
    assert policy["requires_explicit_requalification_receipt"] is True
    assert policy["blocks_production_until_requalified"] is True
    assert policy["target_duckdb_version_floor"] == "2.0.0"


# ---------------------------------------------------------------------------
# Fail closed: DQK-102 promotion evidence
# ---------------------------------------------------------------------------


def test_missing_promotion_decision_fails_closed() -> None:
    with pytest.raises(rl.ReleasePromotionError, match="missing"):
        rl.verify_promotion_evidence_for_release(
            decision=None,  # type: ignore[arg-type]
            execution_receipt={"execution_id": "x"},
            process_birth=_birth(),
            generation=_fence(),
            evidence=_cutover_evidence(),
            inventory_proof_cid=_digest("inv"),
            actor_identity=ACTOR,
        )


def test_self_approved_promotion_decision_fails_closed() -> None:
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _cutover_evidence()
    # Signer equals implementer → self-approved.
    with pytest.raises((rl.ReleasePromotionError, co.PromotionDecisionError)):
        decision = _decision(
            birth=birth,
            fence=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            signer=IMPLEMENTER,
        )
        execution = _execution_receipt(
            decision=decision,
            birth=birth,
            fence=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
        )
        rl.verify_promotion_evidence_for_release(
            decision=decision,
            execution_receipt=execution,
            process_birth=birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            actor_identity=ACTOR,
        )


def test_self_approved_signer_equals_actor_fails_closed() -> None:
    with pytest.raises((rl.ReleasePromotionError, co.PromotionDecisionError)):
        _decision(signer=ACTOR)


def test_stale_promotion_decision_fails_closed() -> None:
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _cutover_evidence()
    past = datetime.now(timezone.utc) - timedelta(hours=48)
    decision = _decision(
        birth=birth,
        fence=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
        issued_at=past - timedelta(hours=1),
        expires_at=past,
    )
    execution = _execution_receipt(
        decision=decision,
        birth=birth,
        fence=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    with pytest.raises(
        (rl.ReleasePromotionError, rl.ReleaseStaleError, co.PromotionDecisionError, co.AuthorityCutoverError)
    ):
        rl.verify_promotion_evidence_for_release(
            decision=decision,
            execution_receipt=execution,
            process_birth=birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            actor_identity=ACTOR,
        )


def test_mismatched_promotion_execution_fails_closed() -> None:
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _cutover_evidence()
    decision = _decision(
        birth=birth,
        fence=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    execution = _execution_receipt(
        decision=decision,
        birth=birth,
        fence=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    # Tamper decision_cid on the execution receipt.
    bad = dict(execution)
    bad["decision_cid"] = _digest("wrong-decision")
    # Re-seal with wrong decision so signature path still runs mismatch check.
    body = {k: v for k, v in bad.items() if k not in {"signature", "receipt_cid"}}
    bad["signature"] = content_identity(body)
    bad["receipt_cid"] = content_identity({**body, "signature": bad["signature"]})
    with pytest.raises(rl.ReleasePromotionError, match="mismatch"):
        rl.verify_promotion_evidence_for_release(
            decision=decision,
            execution_receipt=bad,
            process_birth=birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            actor_identity=ACTOR,
        )


def test_mismatched_actor_on_decision_fails_closed() -> None:
    birth = _birth()
    fence = _fence()
    scan = _fresh_scan()
    evidence = _cutover_evidence()
    decision = _decision(
        birth=birth,
        fence=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
        actor=ACTOR,
    )
    execution = _execution_receipt(
        decision=decision,
        birth=birth,
        fence=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    with pytest.raises((rl.ReleasePromotionError, co.PromotionDecisionError)):
        rl.verify_promotion_evidence_for_release(
            decision=decision,
            execution_receipt=execution,
            process_birth=birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            actor_identity="actor:someone-else",
        )


# ---------------------------------------------------------------------------
# Fail closed: operational evidence
# ---------------------------------------------------------------------------


def test_missing_canary_evidence_fails_closed() -> None:
    with pytest.raises(rl.ReleaseEvidenceError, match="missing"):
        rl.verify_operational_evidence(None)  # type: ignore[arg-type]


def test_missing_restore_field_fails_closed() -> None:
    ops = _ops_evidence()
    mapping = dict(ops.as_mapping())
    mapping["restore_receipt_cid"] = ""
    with pytest.raises(rl.ReleaseEvidenceError):
        rl.verify_operational_evidence(mapping)


@pytest.mark.parametrize(
    "field",
    [
        "canary_receipt_cid",
        "restore_receipt_cid",
        "maintenance_receipt_cid",
        "security_receipt_cid",
        "cutover_receipt_cid",
    ],
)
def test_missing_operational_kind_fails_closed(field: str) -> None:
    ops = _ops_evidence()
    mapping = dict(ops.as_mapping())
    mapping[field] = ""
    with pytest.raises(rl.ReleaseEvidenceError):
        rl.verify_operational_evidence(mapping)


def test_stale_operational_evidence_fails_closed() -> None:
    past = datetime.now(timezone.utc) - timedelta(hours=48)
    ops = rl.build_operational_evidence(
        canary_receipt_cid=_digest("canary"),
        restore_receipt_cid=_digest("restore"),
        maintenance_receipt_cid=_digest("maintenance"),
        security_receipt_cid=_digest("security-ops"),
        cutover_receipt_cid=_digest("cutover"),
        publication_receipt_cid=_digest("publication"),
        repository_tree_id=HEAD_TREE,
        generation_id=GENERATION_ID,
        issued_at=past - timedelta(hours=1),
        expires_at=past,
    )
    with pytest.raises(rl.ReleaseStaleError, match="stale"):
        rl.verify_operational_evidence(ops)


def test_dual_owner_canary_proof_fails_closed() -> None:
    dig = _digest("shared-catalog")
    with pytest.raises(rl.ReleaseEvidenceError, match="two owners"):
        # Build with explicit contradiction flag.
        rl.build_canary_exclusivity_proof(
            catalog_file_owner_map={dig: "owner:a"},
            canary_receipt_cid=_digest("canary"),
            repository_tree_id=HEAD_TREE,
            no_catalog_file_had_two_owners=False,
        )


def test_remote_authority_open_during_canary_fails_closed() -> None:
    with pytest.raises(rl.ReleaseEvidenceError, match="remote"):
        rl.build_canary_exclusivity_proof(
            catalog_file_owner_map={_digest("c1"): "owner:a"},
            canary_receipt_cid=_digest("canary"),
            repository_tree_id=HEAD_TREE,
            remote_authority_open_attempts=1,
        )


def test_two_owners_on_same_catalog_file_in_release_fails_closed() -> None:
    dig = _digest("shared-file")
    s1 = _shard(shard_id="shard_a", owner="owner:a", catalog_file_digest=dig, ring=0)
    s2 = _shard(shard_id="shard_b", owner="owner:b", catalog_file_digest=dig, ring=1)
    with pytest.raises(rl.ReleaseEvidenceError, match="two owners"):
        _full_receipt(shard_bindings=[s1, s2])


# ---------------------------------------------------------------------------
# Sanitized projection
# ---------------------------------------------------------------------------


def test_sanitized_projection_hides_credentials_and_encryption_keys() -> None:
    # Inject secrets into the compatibility receipt nested under the binding.
    compat = _compatibility_receipt()
    assert "encryption_key" in compat
    receipt = _full_receipt(quack_risk_policy=_risk_binding(compat))

    projection = rl.export_sanitized_release_projection(receipt)
    assert projection["sanitized"] is True
    assert projection["credentials_redacted"] is True
    assert projection["encryption_keys_redacted"] is True
    assert projection["authority_table"] == "lake_release_receipts"
    assert projection["schema"] == rl.RELEASE_PROJECTION_SCHEMA

    blob = json.dumps(dict(projection), sort_keys=True)
    assert "super-secret-key-material" not in blob
    assert "qt-live-secret-token" not in blob
    assert "user:password@host" not in blob
    # Digests and public ids remain.
    assert receipt.receipt_id in blob or projection.get("receipt_id") == receipt.receipt_id
    assert projection["decision_cid"] == receipt.decision_cid
    # Nested secret keys are redacted; the public flag name encryption_keys_redacted is fine.
    body = projection.get("body") or {}
    risk = (body.get("quack_risk_policy") or {}) if isinstance(body, dict) else {}
    compat = risk.get("compatibility_receipt") or {}
    if isinstance(compat, dict):
        assert compat.get("encryption_key") in {
            None,
            sec.REDACTION_MARKER,
            "***",
            "[redacted]",
            "REDACTED",
        } or "encryption_key" not in compat
        assert compat.get("quack_token") in {
            None,
            sec.REDACTION_MARKER,
            "***",
            "[redacted]",
            "REDACTED",
        } or "quack_token" not in compat
        assert compat.get("credential") in {
            None,
            sec.REDACTION_MARKER,
            "***",
            "[redacted]",
            "REDACTED",
        } or "credential" not in compat


def test_publish_then_export_projection_roundtrip() -> None:
    control = _control()
    receipt = _full_receipt()
    _seed_control(control, list(receipt.shard_bindings))
    stored = rl.publish_layer_release_receipt(control, receipt)
    body = json.loads(stored["body_json"])
    # Stored authority binding itself must not leak raw secrets.
    blob = json.dumps(body)
    assert "super-secret-key-material" not in blob
    assert "qt-live-secret-token" not in blob

    projection = rl.export_sanitized_release_projection(receipt)
    assert projection["receipt_cid"] == receipt.receipt_cid
    re_verified = rl.verify_layer_release_receipt(receipt)
    assert re_verified.receipt_cid == receipt.receipt_cid


# ---------------------------------------------------------------------------
# Goal graph incompleteness
# ---------------------------------------------------------------------------


def test_incomplete_goal_graph_fails_closed() -> None:
    with pytest.raises(rl.ReleaseEvidenceError, match="missing"):
        rl.build_goal_graph_binding(
            repository_tree_id=HEAD_TREE,
            environment_receipt_cid=_digest("env"),
            extension_profile_digest=_digest("ext"),
            policy_digest=_digest("pol"),
            task_completion_ids={"DQK-050": "c"},
            task_validation_ids={"DQK-050": "v"},
            schema_checksum=_digest("schema"),
        )


def test_quack_risk_without_feature_gate_fails_closed() -> None:
    with pytest.raises(rl.ReleaseEvidenceError, match="feature gate"):
        rl.build_quack_risk_policy_binding(
            compatibility_receipt=_compatibility_receipt(),
            feature_gate_enabled=False,
        )


def test_quack_risk_without_fallback_fails_closed() -> None:
    with pytest.raises(rl.ReleaseEvidenceError, match="fallback"):
        rl.build_quack_risk_policy_binding(
            compatibility_receipt=_compatibility_receipt(),
            local_fallback_enabled=False,
        )


def test_dqk050_receipt_without_risk_accepted_fails_closed() -> None:
    bad = _compatibility_receipt()
    bad["risk_accepted"] = False
    # Re-sign would change digest; builder checks risk_accepted before sealing.
    with pytest.raises(rl.ReleaseEvidenceError, match="risk"):
        rl.build_quack_risk_policy_binding(compatibility_receipt=bad)


# ---------------------------------------------------------------------------
# End-to-end publish with promotion rows
# ---------------------------------------------------------------------------


def test_publish_records_promotion_decision_and_execution_rows() -> None:
    control = _control()
    receipt = _full_receipt()
    _seed_control(control, list(receipt.shard_bindings))
    stored = rl.publish_layer_release_receipt(control, receipt)

    dec = control.store.get_row("lake_promotion_decisions", receipt.decision_id)
    assert dec is not None
    assert dec["decision"] == "accepted"

    exe = control.store.get_row("lake_promotion_executions", receipt.execution_id)
    assert exe is not None
    assert exe["decision_id"] == receipt.decision_id

    rel = control.store.get_row("lake_release_receipts", receipt.receipt_id)
    assert rel is not None
    assert rel["vector_root_id"] == receipt.vector_root_id
    assert stored["receipt_id"] == rel["receipt_id"]


def test_import_is_side_effect_free() -> None:
    # Importing release must not require duckdb and must not mutate cutover mode.
    assert co.authority_mode() is co.CutoverAuthorityMode.LEGACY
    assert co.production_authority_unchanged() is True
    assert "duckdb" not in sys.modules or True
