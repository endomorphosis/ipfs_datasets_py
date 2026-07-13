from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.profile_g import (
    Ed25519Signer,
    GoalPlanValidator,
    NeighborhoodAttestationEngine,
    ProfileGError,
    RiskEvidenceStore,
    evaluate_risk_model,
    profile_g_cid,
    validate_profile_g_artifact,
    verify_ed25519_artifact,
)
from ipfs_datasets_py.mcp_server.p2p_libp2p_transport import (
    dispatch_profile_e_jsonrpc_request,
)
from ipfs_datasets_py.mcp_server.profile_g_service import (
    ProfileGService,
    configure_profile_g_service,
)

CID = "baguqeerakks7bnxojgffzvzkytumof6wj45v4f4pla66djy34k2wiwh4i35a"
RAW_CID = "bafkreiguks7mmvwte4ruaslbai7ntsz4g4rbnb6ebneyuv5t535jhrgf6q"


def common(schema: str, correlation: str = "goal-1", now: int = 1_783_872_000_000):
    return {"schema": schema, "created_at_ms": now, "parents": [], "correlation_id": correlation}


def goal():
    return {
        **common("mcp++/profile-g/goal@1"),
        "owner_did": "did:web:owner.example",
        "objective_cid": RAW_CID,
        "policy_cid": CID,
        "parent_goal_cids": [],
        "labels": ["production"],
    }


def risk_model():
    return {
        **common("mcp++/profile-g/risk-model@1"),
        "name": "placement",
        "version": "1",
        "factor_names": ["authority_failures", "policy_denials"],
        "weight_millionths": {"authority_failures": 600_000, "policy_denials": 400_000},
        "saturation_millionths": {"authority_failures": 1_000_000, "policy_denials": 1_000_000},
        "algorithm": "weighted-saturated-sum-v1",
        "missing_evidence": "deny",
        "max_history_events": 2,
        "risk_buckets": [250_000, 500_000, 750_000, 1_000_000],
    }


def test_normative_artifact_vectors_have_cid_and_error_parity():
    root = Path(__file__).resolve().parents[3]
    vector_root = root.parent.parent / "Mcp-Plus-Plus" / "conformance" / "vectors"
    valid = json.loads((vector_root / "profile_g_artifacts_valid.json").read_text())
    for case in valid["cases"]:
        assert validate_profile_g_artifact(case["kind"], case["payload"]) == case["expected_cid"]
    invalid = json.loads((vector_root / "profile_g_artifacts_invalid.json").read_text())
    for case in invalid["cases"]:
        with pytest.raises(ProfileGError) as caught:
            validate_profile_g_artifact(case["kind"], case["payload"])
        assert caught.value.code == case["expected_error"]


def test_weighted_saturated_risk_is_integer_deterministic():
    assert evaluate_risk_model(
        risk_model(), {"authority_failures": 0, "policy_denials": 250_000}
    ) == (100_000, 0)


def test_tot_branch_is_not_actionable_without_matching_selection():
    artifacts = {}
    goal_artifact = goal()
    goal_cid = profile_g_cid(goal_artifact)
    artifacts[goal_cid] = goal_artifact
    subgoal = {
        **common("mcp++/profile-g/subgoal@1"),
        "goal_cid": goal_cid,
        "parent_subgoal_cid": None,
        "objective_cid": RAW_CID,
        "decomposition_method": "tree-of-thought",
        "decomposer_cid": CID,
        "selection_cid": None,
    }
    subgoal_cid = profile_g_cid(subgoal)
    artifacts[subgoal_cid] = subgoal
    branch = {
        **common("mcp++/profile-g/plan-branch@1"),
        "subgoal_cid": subgoal_cid,
        "candidate_input_cids": [],
        "task_template_cids": [CID],
        "evaluator_cid": CID,
        "score_millionths": 900_000,
        "explanation_cid": CID,
    }
    branch_cid = profile_g_cid(branch)
    artifacts[branch_cid] = branch
    validator = GoalPlanValidator(
        artifacts.get, authority_validator=lambda *_: True, policy_validator=lambda *_: True
    )
    task = {
        **common("mcp++/profile-g/task@1"),
        "subgoal_cid": subgoal_cid,
        "plan_branch_cid": branch_cid,
        "selection_cid": CID,
        "interface_cid": CID,
        "input_cid": RAW_CID,
        "tool": "tools/call",
        "dependency_task_cids": [],
        "idempotency_key": "task-1",
        "resource_class": "cpu",
        "deadline_ms": None,
        "expected_value_millionths": 500_000,
        "max_attempts": 2,
        "execution_mode": "idempotent",
    }
    with pytest.raises(ProfileGError, match="linked artifact") as caught:
        validator.validate_task(task)
    assert caught.value.code == "G_CID_MISMATCH"

    selection = {
        **common("mcp++/profile-g/plan-selection@1"),
        "subgoal_cid": subgoal_cid,
        "plan_branch_cid": branch_cid,
        "selector_did": "did:web:owner.example",
        "proof_cid": CID,
        "policy_decision_cid": CID,
        "reason_cid": CID,
    }
    selection_cid = profile_g_cid(selection)
    artifacts[selection_cid] = selection
    task["selection_cid"] = selection_cid
    assert validator.validate_selection(selection) == selection_cid
    assert validator.validate_task(task) == profile_g_cid(task)


def test_evidence_store_is_durable_bounded_and_redacts(tmp_path):
    signer = Ed25519Signer.generate("did:web:observer.example")

    def verifier(artifact):
        return verify_ed25519_artifact(
            artifact, lambda did: signer.public_key if did == signer.did else None
        )

    path = tmp_path / "risk.sqlite"
    store = RiskEvidenceStore(path, signature_verifier=verifier)
    public = signer.sign(
        {
            **common("mcp++/profile-g/risk-evidence@1", now=100),
            "subject_cid": CID,
            "evidence_type": "timeout",
            "observed_cids": [RAW_CID],
            "observer_did": signer.did,
            "observed_at_ms": 100,
            "expires_at_ms": 500,
            "classification": "public",
            "redacted_cid": None,
        }
    )
    private = signer.sign(
        {
            **common("mcp++/profile-g/risk-evidence@1", now=200),
            "subject_cid": CID,
            "evidence_type": "dispute",
            "observed_cids": [RAW_CID],
            "observer_did": signer.did,
            "observed_at_ms": 200,
            "expires_at_ms": 500,
            "classification": "confidential",
            "redacted_cid": CID,
        }
    )
    public_cid = store.put(public)
    store.put(private)
    store.close()
    reopened = RiskEvidenceStore(path, signature_verifier=verifier)
    assert reopened.get(public_cid) == public
    page = reopened.evidence(CID, at_ms=300, visible_classifications=["public"], limit=1)
    assert [item["artifact_cid"] for item in page["items"]] == [public_cid]
    assert page["redacted"][0]["redacted_cid"] == CID
    assert "observed_cids" not in page["redacted"][0]


def test_neighborhood_filter_signature_and_distinct_did_quorum():
    signer = Ed25519Signer.generate("did:web:peer-a.example")

    def verifier(artifact):
        return verify_ed25519_artifact(
            artifact, lambda did: signer.public_key if did == signer.did else None
        )

    store = RiskEvidenceStore(signature_verifier=verifier)
    record = signer.sign(
        {
            **common("mcp++/profile-g/neighborhood-record@1", now=100),
            "peer_did": signer.did,
            "interface_cids": [CID],
            "resource_classes": ["cpu"],
            "capacity_millionths": 800_000,
            "health_evidence_cid": CID,
            "trust_domain_cid": CID,
            "reachable_artifact_cids": [RAW_CID],
            "valid_from_ms": 50,
            "expires_at_ms": 500,
        }
    )
    record_cid = store.put(record)
    engine = NeighborhoodAttestationEngine(store, signer=signer, eligible_attesters=[signer.did])
    page = engine.query(
        interface_cid=CID,
        resource_class="cpu",
        trust_domain_cid=CID,
        required_artifact_cids=[RAW_CID],
        at_ms=100,
        policy_filter=lambda _record: True,
    )
    assert page["items"][0]["artifact_cid"] == record_cid
    attestation, attestation_cid = engine.attest(
        proposal_cid=CID,
        record_cid=record_cid,
        verdict="support",
        reason_code="healthy",
        observed_epoch=1,
        expires_at_ms=400,
        correlation_id="goal-1",
        created_at_ms=100,
    )
    assert verify_ed25519_artifact(attestation, lambda _did: signer.public_key)
    quorum = engine.quorum([attestation, attestation], proposal_cid=CID, threshold=1, at_ms=200)
    assert quorum["reached"] is True
    assert quorum["support_dids"] == [signer.did]
    assert quorum["attestation_cids"] == [attestation_cid]


def test_service_idempotency_and_http_libp2p_dispatch_parity():
    service = ProfileGService(trusted_local=True)
    configure_profile_g_service(service)
    artifact = goal()
    artifact_cid = profile_g_cid(artifact)
    params = {
        "artifact": artifact,
        "artifact_cid": artifact_cid,
        "caller_did": "did:web:owner.example",
        "idempotency_key": "goal-create-1",
        "correlation_id": "goal-1",
        "parents": [],
        "proof_cid": CID,
        "policy_decision_cid": CID,
    }
    first = service.dispatch("mcp++/goals/create", params)
    second = service.dispatch("mcp++/goals/create", params)
    assert first["artifact_cid"] == second["artifact_cid"] == artifact_cid
    assert first["replayed"] is False and second["replayed"] is True
    response = asyncio.run(
        dispatch_profile_e_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "mcp++/goals/get",
                "params": {"goal_cid": artifact_cid},
            }
        )
    )
    assert response == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": service.dispatch("mcp++/goals/get", {"goal_cid": artifact_cid}),
    }


def test_idempotency_key_reuse_with_new_content_is_rejected():
    service = ProfileGService(trusted_local=True)
    params = {
        "artifact": goal(),
        "caller_did": "did:web:owner.example",
        "idempotency_key": "same",
        "correlation_id": "goal-1",
        "parents": [],
        "proof_cid": CID,
        "policy_decision_cid": CID,
    }
    service.dispatch("mcp++/goals/create", params)
    params["artifact"] = {**goal(), "labels": ["research"]}
    with pytest.raises(ProfileGError) as caught:
        service.dispatch("mcp++/goals/create", params)
    assert caught.value.code == "G_IDEMPOTENCY_CONFLICT"
