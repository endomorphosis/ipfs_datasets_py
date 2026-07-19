from __future__ import annotations

from ipfs_datasets_py.logic.profile_d_policy import evaluate_execution_policy


def test_profile_d_policy_evaluator_returns_transport_artifacts() -> None:
    result = evaluate_execution_policy(
        actor="did:example:alice",
        action="compile.legal_ir",
        resource="uscode:17",
        evaluated_at="2026-01-02T03:04:05Z",
        request_zkp_certificate=True,
        policy={
            "clauses": [
                {
                    "clause_type": "permission",
                    "actor": "did:example:alice",
                    "action": "compile.legal_ir",
                    "resource": "uscode:17",
                },
                {
                    "clause_type": "obligation",
                    "actor": "did:example:alice",
                    "action": "compile.legal_ir",
                    "resource": "uscode:17",
                    "obligation_deadline": "2026-01-03T00:00:00Z",
                    "metadata": {"audit": "required"},
                },
            ]
        },
    )

    assert result["decision"] == "allow_with_obligations"
    assert result["policy_cid"]
    assert result["formal_logic_cid"]
    assert result["formal_logic"]["logic_system"] == "temporal_deontic_policy"
    assert result["zkp_certificate"]["status"] == "statement_ready"
    assert result["zkp_certificate"]["statement"]["policy_cid"] == result["policy_cid"]
    assert result["obligations"][0]["status"] == "pending"


def test_profile_d_policy_prohibition_overrides_permission() -> None:
    result = evaluate_execution_policy(
        actor="did:example:alice",
        action="compile.legal_ir",
        resource="uscode:17",
        evaluated_at="2026-01-02T03:04:05Z",
        policy={
            "clauses": [
                {
                    "clause_type": "permission",
                    "actor": "did:example:alice",
                    "action": "compile.legal_ir",
                    "resource": "uscode:17",
                },
                {
                    "clause_type": "prohibition",
                    "actor": "did:example:alice",
                    "action": "compile.legal_ir",
                    "resource": "uscode:17",
                },
            ]
        },
    )

    assert result["decision"] == "deny"
    assert result["obligations"] == []
    assert result["formal_logic"]["decision"] == "deny"
