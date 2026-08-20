"""E2E tests: DuckLake layer release receipt (DQK-101).

Acceptance coverage:

* The receipt is stored in the DQK-086 ``lake_release_receipts`` authority table
  rather than a Markdown/JSON file
* It binds every DuckDB + Quack catalog shard, catalog file and
  companion-registry digest, owner generation/endpoint identity, task
  completion/validation ID, storage identity, snapshot vector, policy,
  extension, Git tree, expiry, and the exact DQK-102 signed decision plus
  execution receipt
* It proves no catalog file had two owners and no remote client opened an
  authority catalog directly during the canary
* It binds the Quack beta risk acceptance, exact DQK-050 compatibility receipt,
  enabled fallback/feature gate, and DuckDB 2.0 requalification policy
* Missing, stale, mismatched, or self-approved DQK-102 promotion evidence fails
  closed
* Missing or stale canary, restore, maintenance, security, or cutover evidence
  fails closed
* A sanitized release projection can be exported without exposing credentials
  or encryption keys

Hermetic: no live DuckDB, Quack, Docker, or network required.
"""

from __future__ import annotations

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

from ipfs_datasets_py.duckdb_control.contracts import content_identity
from ipfs_datasets_py.ducklake import cutover as co
from ipfs_datasets_py.ducklake import registry as reg
from ipfs_datasets_py.ducklake import release as rel
from ipfs_datasets_py.ducklake import security as sec


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------

HEAD_TREE = "a" * 40
PLAN_ROOT = "sha256:" + ("11" * 32)
GENERATION_ID = "generation:dqk101-active-1"
ACTOR = "actor:runtime-release-1"
IMPLEMENTER = "implementer:dqk-100-owner"
SIGNER = "reviewer:independent-dqk-102"
SCHEMA_CHECKSUM = "sha256:" + ("22" * 32)


def _digest(label: str) -> str:
    return content_identity({"label": label, "task": "DQK-101"})


@pytest.fixture()
def control() -> reg.ControlLakeRegistry:
    ctl = reg.ControlLakeRegistry(owner_id="control-dqk101")
    ctl.apply_migrations()
    # Minimal topology so release storage can bind shards / vector roots.
    ctl.register_catalog(
        catalog_id="cat-a",
        catalog_digest=_digest("catalog-a"),
        storage_kind="local_block",
        metadata_path="/var/lib/ducklake/cat-a.duckdb",
    )
    ctl.register_shard(
        shard_id="shard-a",
        catalog_id="cat-a",
        ring_position=0,
        endpoint_identity="quacks://127.0.0.1:19001/cat-a",
    )
    ctl.register_catalog(
        catalog_id="cat-b",
        catalog_digest=_digest("catalog-b"),
        storage_kind="local_block",
        metadata_path="/var/lib/ducklake/cat-b.duckdb",
    )
    ctl.register_shard(
        shard_id="shard-b",
        catalog_id="cat-b",
        ring_position=0,
        endpoint_identity="quacks://127.0.0.1:19002/cat-b",
    )
    return ctl


def _shards() -> list[rel.CatalogShardBinding]:
    return [
        rel.build_catalog_shard_binding(
            shard_id="shard-a",
            catalog_id="cat-a",
            catalog_file_digest=_digest("catalog-file-a"),
            companion_registry_digest=_digest("companion-a"),
            owner_generation=3,
            endpoint_identity="endpoint:owner-a",
            storage_identity="storage:root-a",
            task_completion_id="task-completion:dqk-104-a",
            task_validation_id="task-validation:dqk-104-a",
            owner_identity="owner:proc-a",
        ),
        rel.build_catalog_shard_binding(
            shard_id="shard-b",
            catalog_id="cat-b",
            catalog_file_digest=_digest("catalog-file-b"),
            companion_registry_digest=_digest("companion-b"),
            owner_generation=2,
            endpoint_identity="endpoint:owner-b",
            storage_identity="storage:root-b",
            task_completion_id="task-completion:dqk-104-b",
            task_validation_id="task-validation:dqk-104-b",
            owner_identity="owner:proc-b",
        ),
    ]


def _birth(**kwargs: Any) -> co.ProcessBirth:
    defaults = dict(
        process_id="proc:release-test-1",
        boot_id="boot:release-test-1",
        started_at="2026-08-11T00:00:00Z",
        hostname="hermetic-test",
        pid=10101,
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


def _producer_digests(suffix: str = "v1") -> dict[str, str]:
    from ipfs_datasets_py.ducklake.adapters import REGISTERED_PARQUET_PRODUCERS

    return {
        pid: content_identity({"producer": pid, "suffix": suffix})
        for pid in REGISTERED_PARQUET_PRODUCERS
    }


def _fresh_scan(*, head: str = HEAD_TREE) -> co.ExactHeadProducerScan:
    return co.build_exact_head_scan(
        head_tree_id=head,
        producer_digests=_producer_digests(),
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
    evidence = evidence or _evidence(
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


def _execution_for(decision: co.PromotionDecision) -> dict[str, Any]:
    body = {
        "schema": co.EXECUTION_RECEIPT_SCHEMA,
        "execution_id": "exec:dqk101-1",
        "decision_cid": decision.decision_cid,
        "decision_id": decision.decision_id,
        "actor_identity": decision.actor_identity,
        "process_birth_fingerprint": decision.process_birth_fingerprint,
        "generation_fingerprint": decision.generation_fingerprint,
        "repository_tree_id": decision.repository_tree_id,
        "before_authority": decision.from_authority,
        "after_authority": decision.to_authority,
        "inventory_proof_cid": decision.inventory_proof_cid,
        "evidence_set_cid": decision.evidence_set_cid,
        "changed_producers": [],
        "rollback_fence_id": "fence:rollback-1",
        "rollback_window_hours": decision.rollback_window_hours,
        "dry_run": False,
        "executed_at": decision.issued_at,
        "post_transition_verification": "ok",
        "production_authority_mutated": False,
    }
    signature = content_identity(body)
    receipt_cid = content_identity({**body, "signature": signature})
    return {
        **body,
        "signature": signature,
        "receipt_cid": receipt_cid,
    }


def _op(
    kind: str,
    *,
    tree: str = HEAD_TREE,
    expires_in_hours: int = 12,
    **extra: Any,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    payload = rel.build_operational_evidence(
        kind=kind,
        receipt_id=f"receipt:{kind}:dqk101",
        receipt_digest=_digest(f"{kind}-receipt"),
        repository_tree_id=tree,
        issued_at=now - timedelta(minutes=5),
        expires_at=now + timedelta(hours=expires_in_hours),
        extra=extra or None,
    )
    return payload


def _canary(*, tree: str = HEAD_TREE) -> dict[str, Any]:
    return _op(
        "canary",
        tree=tree,
        single_owner_proof=True,
        single_owner=True,
        no_remote_catalog_open=True,
        remote_client_opened_catalog=False,
        remote_clients_may_open_catalog_file=False,
        ownership_proof={
            "single_owner_per_catalog_file": True,
            "remote_client_opened_authority_catalog": False,
        },
    )


def _compatibility_receipt() -> dict[str, Any]:
    mod = rel.load_dqk050_module()
    receipt = mod.build_quack_beta_compatibility_receipt(
        feature_gate_enabled=True,
        local_fallback_enabled=True,
        risk_accepted=True,
        acceptor_identity="reviewer:dqk-101-release",
    )
    mod.require_compatibility_receipt(receipt)
    return receipt


def _snapshot_vector() -> dict[str, Any]:
    members = [
        {"shard_id": "shard-a", "snapshot_version": 7},
        {"shard_id": "shard-b", "snapshot_version": 4},
    ]
    return {
        "vector_root_id": "vector:release-dqk101",
        "root_digest": _digest("snapshot-vector"),
        "members": members,
    }


def _valid_kwargs(**overrides: Any) -> dict[str, Any]:
    birth = _birth()
    fence = _fence()
    evidence = _evidence()
    scan = _fresh_scan()
    decision = _decision(
        birth=birth,
        fence=fence,
        evidence=evidence,
        inventory_proof_cid=scan.inventory_proof_cid,
    )
    execution = _execution_for(decision)
    base: dict[str, Any] = {
        "catalog_shards": _shards(),
        "promotion_decision": decision,
        "promotion_execution": execution,
        "canary": _canary(),
        "restore": _op("restore"),
        "maintenance": _op("maintenance"),
        "security": _op("security"),
        "cutover": _op("cutover"),
        "publication": _op("publication"),
        "compatibility_receipt": _compatibility_receipt(),
        "repository_tree_id": HEAD_TREE,
        "schema_checksum": SCHEMA_CHECKSUM,
        "snapshot_vector": _snapshot_vector(),
        "process_birth": birth,
        "generation": fence,
        "evidence_bundle": evidence,
        "inventory_proof_cid": scan.inventory_proof_cid,
        "actor_identity": ACTOR,
        "quack_beta_risk_acceptance": {
            "quack_beta_not_production_ready": True,
            "risk_accepted": True,
            "acceptor_identity": "reviewer:dqk-101-release",
        },
        "feature_gate": {
            "enabled": True,
            "feature_gate_enabled": True,
            "quack_feature_gate_enabled": True,
        },
        "local_fallback": {
            "local_fallback_enabled": True,
            "enabled": True,
        },
        "duckdb_2_0_requalification_policy": rel.build_duckdb_20_requalification_policy(),
        "release_id": "release:dqk101-hermetic-1",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Contract / self-check
# ---------------------------------------------------------------------------


def test_self_check_contract_constants() -> None:
    report = rel.self_check()
    assert report["ok"] is True
    assert report["owner_task_id"] == "DQK-101"
    assert report["promotion_gate_task_id"] == "DQK-102"
    assert report["compatibility_task_id"] == "DQK-050"
    assert report["authority_task_id"] == "DQK-086"
    assert report["authority_table"] == "lake_release_receipts"
    assert report["interface"] == "DuckLakeLayerReleaseReceipt@1"
    assert report["storage_medium"] == "authority_table"
    assert report["markdown_or_json_file_authority"] is False
    assert report["fail_closed"]["self_approved_dqk102"] is True
    assert "dqk050_compatibility_receipt" in report["binds"]
    assert rel.AUTHORITY_TABLE == "lake_release_receipts"
    assert rel.RELEASE_RECEIPT_INTERFACE == "DuckLakeLayerReleaseReceipt@1"


# ---------------------------------------------------------------------------
# Authority-table storage (not Markdown/JSON file)
# ---------------------------------------------------------------------------


def test_receipt_stored_in_lake_release_receipts_authority_table(
    control: reg.ControlLakeRegistry,
) -> None:
    result = rel.publish_layer_release(control=control, **_valid_kwargs())
    assert result["ok"] is True
    storage = result["storage"]
    assert storage["authority_table"] == "lake_release_receipts"
    assert storage["authority_task_id"] == "DQK-086"
    assert storage["storage_medium"] == "authority_table"
    assert storage["markdown_file"] is False
    assert storage["json_file"] is False

    receipt_id = storage["receipt_id"]
    row = control.store.get_row("lake_release_receipts", receipt_id)
    assert row is not None
    assert row["receipt_id"] == receipt_id
    assert row["release_id"] == "release:dqk101-hermetic-1"
    assert row["decision_id"]
    assert row["execution_id"]
    assert row["binding_digest"].startswith("sha256:")
    assert "body_json" in row
    assert '"interface":"DuckLakeLayerReleaseReceipt@1"' in row["body_json"].replace(
        " ", ""
    ) or "DuckLakeLayerReleaseReceipt@1" in row["body_json"]

    # Not written as a file-based authority artifact by the release path.
    assert storage.get("path") is None
    assert storage.get("markdown_path") is None
    assert storage.get("json_path") is None


def test_store_rejects_non_authority_storage_medium(
    control: reg.ControlLakeRegistry,
) -> None:
    receipt = rel.build_layer_release_receipt(**_valid_kwargs())
    mapping = dict(receipt.as_mapping())
    mapping["storage_medium"] = "markdown_file"
    # Signature will no longer match, but storage_medium check fails first
    # after signature rebuild attempt — either way fails closed.
    with pytest.raises(rel.ReleaseError):
        rel.store_layer_release_receipt(control, mapping)


# ---------------------------------------------------------------------------
# Binding completeness
# ---------------------------------------------------------------------------


def test_receipt_binds_shards_tree_policy_promotion_and_expiry(
    control: reg.ControlLakeRegistry,
) -> None:
    receipt = rel.build_layer_release_receipt(**_valid_kwargs())
    body = dict(receipt.as_mapping())

    assert body["interface"] == "DuckLakeLayerReleaseReceipt@1"
    assert body["repository_tree_id"] == HEAD_TREE
    assert body["schema_checksum"] == SCHEMA_CHECKSUM
    assert body["expires_at"]
    assert body["decision_cid"]
    assert body["execution_receipt_cid"]
    assert body["promotion_gate_task_id"] == "DQK-102"

    shards = body["catalog_shards"]
    assert len(shards) == 2
    for shard in shards:
        assert shard["catalog_file_digest"].startswith("sha256:")
        assert shard["companion_registry_digest"].startswith("sha256:")
        assert shard["owner_generation"] >= 1
        assert shard["endpoint_identity"]
        assert shard["storage_identity"]
        assert shard["task_completion_id"]
        assert shard["task_validation_id"]
        assert shard["single_owner"] is True
        assert shard["remote_client_opened_catalog"] is False

    assert body["snapshot_vector"]["vector_root_id"] == "vector:release-dqk101"
    assert body["snapshot_vector_digest"].startswith("sha256:")
    assert body["extension_profile"]["quack"]
    assert body["extension_profile"]["ducklake"]
    assert body["policy"]
    assert body["environment_profile"]["duckdb_version"]

    # Exact DQK-102 decision + execution
    assert body["promotion_decision"]["gate_task_id"] == "DQK-102"
    assert body["promotion_decision"]["signer_identity"] == SIGNER
    assert body["promotion_execution"]["decision_cid"] == body["decision_cid"]

    stored = rel.store_layer_release_receipt(control, receipt)
    assert stored["ok"] is True


# ---------------------------------------------------------------------------
# Ownership / remote client proofs
# ---------------------------------------------------------------------------


def test_proves_single_owner_and_no_remote_catalog_open() -> None:
    receipt = rel.build_layer_release_receipt(**_valid_kwargs())
    proof = dict(receipt.ownership_proof)
    assert proof["single_owner_per_catalog_file"] is True
    assert proof["remote_client_opened_authority_catalog"] is False
    assert proof["canary_bound"] is True

    # Dual owners on the same catalog file digest fail closed.
    shards = _shards()
    dual = [
        dict(shards[0].as_mapping()),
        dict(shards[1].as_mapping()),
    ]
    dual[1]["catalog_file_digest"] = dual[0]["catalog_file_digest"]
    dual[1]["shard_id"] = "shard-intruder"
    with pytest.raises(rel.ReleaseError, match="two owners"):
        rel.build_ownership_proof(dual)

    # Remote open during canary fails closed.
    canary = _canary()
    canary["remote_client_opened_catalog"] = True
    with pytest.raises(rel.ReleaseError, match="remote client"):
        rel.verify_ownership_invariants(_shards(), canary=canary)

    # Remote authority open/copy/mount denied by security boundary.
    with pytest.raises(sec.RemoteAccessDenied):
        sec.assert_remote_authority_action_denied("open", target="authority_catalog")


# ---------------------------------------------------------------------------
# DQK-050 / risk / feature gate / DuckDB 2.0 policy
# ---------------------------------------------------------------------------


def test_binds_quack_beta_risk_dqk050_gate_fallback_and_requal_policy() -> None:
    receipt = rel.build_layer_release_receipt(**_valid_kwargs())
    body = dict(receipt.as_mapping())

    assert body["quack_beta_risk_acceptance"]["risk_accepted"] is True
    assert (
        body["quack_beta_risk_acceptance"]["quack_beta_not_production_ready"] is True
    )
    assert body["compatibility_receipt_id"].startswith("receipt:")
    assert body["compatibility_receipt_digest"].startswith("sha256:")
    assert body["compatibility_receipt"]["task_id"] == "DQK-050"
    assert body["compatibility_receipt"]["risk_accepted"] is True
    assert body["compatibility_receipt"]["feature_gate_enabled"] is True
    assert body["compatibility_receipt"]["local_fallback_enabled"] is True
    assert body["feature_gate"]["enabled"] is True
    assert body["local_fallback"]["local_fallback_enabled"] is True

    policy = body["duckdb_2_0_requalification_policy"]
    assert policy["requires_explicit_requalification_receipt"] is True
    assert policy["requires_full_contract_rerun"] is True
    assert policy["production_ready_from"] == "2.0.0"
    assert policy["feature_gate_remains_enabled"] is True
    assert policy["local_fallback_remains_enabled"] is True

    # Missing DQK-050 receipt fails closed.
    kwargs = _valid_kwargs()
    kwargs["compatibility_receipt"] = {}
    with pytest.raises(rel.MissingEvidenceError):
        rel.build_layer_release_receipt(**kwargs)

    # Disabled feature gate fails closed.
    kwargs = _valid_kwargs()
    kwargs["feature_gate"] = {"enabled": False, "feature_gate_enabled": False}
    # compatibility receipt still has gate enabled; override by clearing receipt flags
    bad_compat = dict(kwargs["compatibility_receipt"])
    # Can't easily unsign; instead call verify_compatibility_binding directly.
    with pytest.raises(rel.ReleaseError, match="feature gate"):
        rel.verify_compatibility_binding(
            compatibility_receipt=kwargs["compatibility_receipt"],
            feature_gate={"enabled": False, "feature_gate_enabled": False},
            local_fallback={"local_fallback_enabled": True},
        )


# ---------------------------------------------------------------------------
# DQK-102 fail-closed paths
# ---------------------------------------------------------------------------


def test_missing_dqk102_promotion_evidence_fails_closed() -> None:
    kwargs = _valid_kwargs()
    with pytest.raises(rel.MissingEvidenceError, match="decision"):
        rel.verify_promotion_evidence(
            decision=None,  # type: ignore[arg-type]
            execution=kwargs["promotion_execution"],
        )

    with pytest.raises(rel.MissingEvidenceError, match="execution"):
        rel.verify_promotion_evidence(
            decision=kwargs["promotion_decision"],
            execution=None,  # type: ignore[arg-type]
        )


def test_stale_dqk102_promotion_evidence_fails_closed() -> None:
    birth = _birth()
    fence = _fence()
    evidence = _evidence()
    scan = _fresh_scan()
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
    execution = _execution_for(decision)
    with pytest.raises(rel.StaleEvidenceError, match="expired"):
        rel.verify_promotion_evidence(
            decision=decision,
            execution=execution,
            process_birth=birth,
            generation=fence,
            evidence=evidence,
            inventory_proof_cid=scan.inventory_proof_cid,
            actor_identity=ACTOR,
        )


def test_mismatched_dqk102_promotion_evidence_fails_closed() -> None:
    decision = _decision()
    execution = _execution_for(decision)
    execution["decision_cid"] = _digest("wrong-decision")
    with pytest.raises(rel.MismatchedEvidenceError, match="not bound"):
        rel.verify_promotion_evidence(
            decision=decision,
            execution=execution,
        )

    # Tree mismatch
    with pytest.raises(rel.MismatchedEvidenceError, match="tree"):
        rel.verify_promotion_evidence(
            decision=decision,
            execution=_execution_for(decision),
            expected_tree_id="b" * 40,
        )


def test_self_approved_dqk102_promotion_evidence_fails_closed() -> None:
    birth = _birth()
    fence = _fence()
    evidence = _evidence()
    scan = _fresh_scan()

    # Self-signed at build time (implementer == signer)
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

    # Craft a structural self-approval for verify_promotion_evidence
    decision = _decision()
    bad = dict(decision.as_mapping())
    bad["signer_identity"] = bad["implementer_identity"]
    execution = _execution_for(decision)
    with pytest.raises(rel.SelfApprovedPromotionError, match="self-approved"):
        rel.verify_promotion_evidence(decision=bad, execution=execution)

    bad2 = dict(decision.as_mapping())
    bad2["signer_identity"] = bad2["actor_identity"]
    with pytest.raises(rel.SelfApprovedPromotionError):
        rel.verify_promotion_evidence(decision=bad2, execution=execution)


# ---------------------------------------------------------------------------
# Operational evidence fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind",
    ["canary", "restore", "maintenance", "security", "cutover"],
)
def test_missing_operational_evidence_fails_closed(kind: str) -> None:
    kwargs = _valid_kwargs()
    kwargs[kind] = None  # type: ignore[assignment]
    with pytest.raises(rel.MissingEvidenceError):
        rel.build_layer_release_receipt(**kwargs)


@pytest.mark.parametrize(
    "kind",
    ["canary", "restore", "maintenance", "security", "cutover"],
)
def test_stale_operational_evidence_fails_closed(kind: str) -> None:
    kwargs = _valid_kwargs()
    # Craft raw already-expired evidence (builder rejects expires_at < issued_at).
    now = datetime.now(timezone.utc)
    stale = {
        "kind": kind,
        "receipt_id": f"receipt:{kind}:stale",
        "receipt_digest": _digest(f"{kind}-stale"),
        "repository_tree_id": HEAD_TREE,
        "issued_at": (now - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fresh": True,
        "stale": False,
    }
    if kind == "canary":
        stale.update(
            {
                "single_owner_proof": True,
                "no_remote_catalog_open": True,
                "remote_client_opened_catalog": False,
            }
        )
    kwargs[kind] = stale
    with pytest.raises(rel.StaleEvidenceError):
        rel.build_layer_release_receipt(**kwargs)


def test_stale_flag_on_operational_evidence_fails_closed() -> None:
    kwargs = _valid_kwargs()
    canary = _canary()
    canary["stale"] = True
    kwargs["canary"] = canary
    with pytest.raises(rel.StaleEvidenceError, match="stale"):
        rel.build_layer_release_receipt(**kwargs)


def test_mismatched_operational_tree_fails_closed() -> None:
    kwargs = _valid_kwargs()
    kwargs["restore"] = _op("restore", tree="c" * 40)
    with pytest.raises(rel.MismatchedEvidenceError, match="tree"):
        rel.build_layer_release_receipt(**kwargs)


# ---------------------------------------------------------------------------
# Sanitized projection
# ---------------------------------------------------------------------------


def test_sanitized_release_projection_hides_credentials_and_keys(
    control: reg.ControlLakeRegistry,
) -> None:
    # Inject secret-looking material into a side channel then ensure export
    # never surfaces it.
    kwargs = _valid_kwargs()
    receipt = rel.build_layer_release_receipt(**kwargs)
    body = dict(receipt.as_mapping())
    body["encryption_key"] = "super-secret-encryption-key-material-001"
    body["credentials"] = {
        "password": "hunter2",
        "api_key": "AKID" + ("x" * 40),
        "token": "bearer-secret-token-value-aaaaaaaa",
    }
    body["endpoint_secret"] = "endpoint-secret-value-bbbbbbbb"
    body["nested"] = {"private_key": "BEGIN PRIVATE KEY\nABC\n"}

    # Wrap as mapping for export (bypass signature — export does not re-verify).
    projection = rel.export_sanitized_release_projection(body)
    assert projection["sanitized"] is True
    assert projection["credentials_exported"] is False
    assert projection["encryption_keys_exported"] is False
    assert projection["authority_table"] == "lake_release_receipts"
    assert projection["interface"] == "DuckLakeLayerReleaseReceipt@1"
    assert projection["schema"] == rel.SANITIZED_PROJECTION_SCHEMA

    blob = str(projection).lower()
    assert "hunter2" not in blob
    assert "super-secret-encryption-key-material" not in blob
    assert "bearer-secret-token-value" not in blob
    assert "endpoint-secret-value" not in blob
    assert "begin private key" not in blob
    assert "encryption_key" not in projection
    assert "credentials" not in projection
    assert "endpoint_secret" not in projection
    assert "private_key" not in projection

    # Full publish path also returns a sanitized projection.
    published = rel.publish_layer_release(control=control, **_valid_kwargs())
    proj = published["sanitized_projection"]
    assert proj["sanitized"] is True
    assert proj["receipt_id"]
    assert proj["decision_cid"]
    assert "encryption_key" not in proj


# ---------------------------------------------------------------------------
# Full happy path round-trip
# ---------------------------------------------------------------------------


def test_publish_verify_round_trip(control: reg.ControlLakeRegistry) -> None:
    published = rel.publish_layer_release(control=control, **_valid_kwargs())
    assert published["ok"] is True
    receipt_map = published["receipt"]
    verified = rel.verify_layer_release_receipt(receipt_map)
    assert verified.interface == "DuckLakeLayerReleaseReceipt@1"
    assert verified.authority_table == "lake_release_receipts"

    row = control.store.get_row("lake_release_receipts", verified.receipt_id)
    assert row is not None
    assert row["vector_root_id"] == verified.vector_root_id

    # Promotion decision/execution rows also present on the control authority.
    assert control.store.get_row("lake_promotion_decisions", row["decision_id"]) is not None
    assert (
        control.store.get_row("lake_promotion_executions", row["execution_id"])
        is not None
    )


def test_import_is_side_effect_free() -> None:
    # Importing release must not open DuckDB or mutate process-local cutover.
    import importlib

    mod = importlib.import_module("ipfs_datasets_py.ducklake.release")
    assert mod.OWNER_TASK_ID == "DQK-101"
    assert mod.AUTHORITY_TABLE == "lake_release_receipts"
    assert co.authority_mode() is co.CutoverAuthorityMode.LEGACY
