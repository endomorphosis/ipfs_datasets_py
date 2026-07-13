"""Profile D parity for the datasets MCP++ Profile E dispatcher."""

import asyncio

from ipfs_datasets_py.mcp_server.p2p_libp2p_transport import dispatch_profile_e_jsonrpc_request


def test_profile_d_p2p_dispatch_matches_http_policy_semantics() -> None:
    response = asyncio.run(dispatch_profile_e_jsonrpc_request({
        "jsonrpc": "2.0",
        "id": 11,
        "method": "mcp++/policy/evaluate",
        "params": {
            "actor": "did:key:alice",
            "action": "tools.call",
            "policy": {"clauses": [{"clause_type": "prohibition", "actor": "did:key:alice", "action": "tools.call"}]},
            "request_zkp_certificate": True,
        },
    }))

    assert response is not None
    assert response["result"]["decision"] == "deny"
    assert response["result"]["zkp_certificate"]["status"] == "statement_ready"
