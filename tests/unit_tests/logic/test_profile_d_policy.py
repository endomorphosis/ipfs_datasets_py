"""Canonical package-export tests for MCP++ Profile D policy evaluation."""

import asyncio
import base64
import hashlib
import json

import pytest
from multiformats import CID
from starlette.requests import Request

from ipfs_datasets_py.logic.profile_d_policy import ProfileDPolicyError, evaluate_execution_policy


def _policy(*clauses):
    return {"clauses": list(clauses)}


def test_logic_namespace_exposes_the_canonical_profile_d_package_export():
    from ipfs_datasets_py.logic import evaluate_execution_policy as package_export

    assert package_export is evaluate_execution_policy


def test_explicit_policy_is_content_addressed_and_zkp_statement_is_not_a_proof():
    result = evaluate_execution_policy(
        actor="did:key:alice",
        action="tools.call",
        resource="dataset/a",
        policy=_policy(
            {"clause_type": "permission", "actor": "did:key:alice", "action": "tools.call", "resource": "dataset/a"},
            {"clause_type": "obligation", "actor": "did:key:alice", "action": "tools.call", "obligation_deadline": "2030-01-01T00:00:00Z"},
        ),
        evaluated_at="2026-07-11T00:00:00Z",
        request_zkp_certificate=True,
    )

    assert result["decision"] == "allow_with_obligations"
    assert result["allowed"] is True
    assert result["policy_cid"]
    assert result["decision_cid"]
    assert result["formal_logic"]
    for cid in (
        result["policy_cid"],
        result["decision_cid"],
        result["intent_cid"],
        result["formal_logic_cid"],
        result["zkp_certificate"]["statement_cid"],
    ):
        parsed = CID.decode(cid)
        assert parsed.version == 1
        assert parsed.codec.name == "dag-json"
        assert parsed.hashfun.name == "sha2-256"
    assert result["zkp_certificate"]["status"] == "statement_ready"
    assert result["zkp_certificate"]["zero_knowledge"] is False
    assert result["zkp_certificate"]["proof"] is None


def test_managed_adapter_blocks_are_exact_canonical_dag_json_bytes(monkeypatch):
    monkeypatch.setenv("MCPPLUSPLUS_PROFILE_D_INCLUDE_ARTIFACT_BLOCKS", "1")
    result = evaluate_execution_policy(
        actor="did:key:alice",
        action="tools.call",
        policy=_policy({"clause_type": "permission", "actor": "did:key:alice", "action": "tools.call"}),
        evaluated_at="2026-07-12T00:00:00Z",
        request_zkp_certificate=True,
    )

    blocks = result["_artifact_blocks"]
    assert set(blocks) == {"policy", "intent", "decision", "formal_logic", "statement"}
    for block in blocks.values():
        parsed = CID.decode(block["cid"])
        raw = base64.b64decode(block["bytes_base64"])
        assert parsed.codec.name == "dag-json"
        assert bytes(parsed.raw_digest) == hashlib.sha256(raw).digest()


def test_prohibition_and_missing_scoped_resource_fail_closed():
    prohibited = evaluate_execution_policy(
        actor="did:key:alice",
        action="tools.call",
        resource="dataset/private",
        policy=_policy(
            {"clause_type": "permission", "actor": "did:key:alice", "action": "tools.call", "resource": "dataset/*"},
            {"clause_type": "prohibition", "actor": "did:key:alice", "action": "tools.call", "resource": "dataset/private"},
        ),
    )
    missing_resource = evaluate_execution_policy(
        actor="did:key:alice",
        action="tools.call",
        policy=_policy({"clause_type": "permission", "actor": "did:key:alice", "action": "tools.call", "resource": "dataset/private"}),
    )

    assert prohibited["decision"] == "deny"
    assert missing_resource["decision"] == "deny"


def test_prefix_resource_scope_matches_in_the_canonical_evaluator():
    result = evaluate_execution_policy(
        actor="did:key:alice",
        action="tools.call",
        resource="dataset/public",
        policy=_policy({"clause_type": "permission", "actor": "did:key:alice", "action": "tools.call", "resource": "dataset/*"}),
    )

    assert result["decision"] == "allow"


def test_plain_text_is_compiled_to_formal_logic_before_evaluation():
    result = evaluate_execution_policy(
        actor="alice",
        action="read",
        policy_text="Alice may read files.",
    )

    assert result["decision"] == "allow"
    assert result["policy_source"] in {"plain_text_dcec", "plain_text_fallback"}
    assert result["formal_logic"]


def test_profile_d_http_method_rejects_missing_policy_and_evaluates_valid_input():
    from ipfs_datasets_py.mcp_server.fastapi_service import mcp_jsonrpc_handler

    async def call(params):
        body = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "mcp++/policy/evaluate", "params": params}).encode()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        return await mcp_jsonrpc_handler(Request({"type": "http", "method": "POST", "path": "/mcp", "headers": []}, receive))

    invalid = asyncio.run(call({"actor": "did:key:alice", "action": "tools.call"}))
    valid = asyncio.run(call({
        "actor": "did:key:alice",
        "action": "tools.call",
        "policy": _policy({"clause_type": "permission", "actor": "did:key:alice", "action": "tools.call"}),
    }))

    assert invalid["error"]["code"] == -32602
    assert valid["result"]["decision"] == "allow"


def test_profile_d_rest_alias_uses_the_same_fail_closed_evaluator():
    from ipfs_datasets_py.mcp_server.fastapi_service import evaluate_deontic_policy

    async def call(payload):
        body = json.dumps(payload).encode()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        return await evaluate_deontic_policy(
            Request({"type": "http", "method": "POST", "path": "/mcp/policy/evaluate", "headers": []}, receive)
        )

    response = asyncio.run(call({
        "actor": "did:key:alice",
        "action": "tools.call",
        "policy": _policy({"clause_type": "prohibition", "actor": "did:key:alice", "action": "tools.call"}),
        "request_zkp_certificate": True,
    }))

    assert response["decision"] == "deny"
    assert response["zkp_certificate"]["status"] == "statement_ready"


def test_rejects_ambiguous_policy_input():
    with pytest.raises(ProfileDPolicyError, match="exactly one"):
        evaluate_execution_policy(
            actor="did:key:alice",
            action="tools.call",
            policy=_policy({"clause_type": "permission"}),
            policy_text="Alice may call tools",
        )
