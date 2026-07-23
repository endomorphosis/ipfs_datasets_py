import asyncio

from ipfs_datasets_py.mcp_server.p2p_libp2p_transport import dispatch_profile_e_jsonrpc_request
from ipfs_datasets_py.mcp_server.profile_g_service import PROFILE_G_METHODS, ProfileGService


def test_profile_g_descriptor_lists_every_method_and_transport():
    profile = ProfileGService(trusted_local=True).profile
    assert profile["methods"] == list(PROFILE_G_METHODS)
    assert profile["transports"] == ["jsonrpc-http", "mcp+p2p"]
    assert len(profile["interface_descriptor"]["methods"]) == len(PROFILE_G_METHODS)


def test_profile_e_rejects_unnegotiated_profile_g():
    response = asyncio.run(dispatch_profile_e_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 3, "method": "mcp++/risk/profile", "params": {}},
        initialized=True, profile_g_negotiated=False,
    ))
    assert response["error"]["data"]["code"] == "G_CAPABILITY_NOT_NEGOTIATED"


def test_profile_e_rejects_profile_g_before_initialize():
    response = asyncio.run(dispatch_profile_e_jsonrpc_request(
        {"jsonrpc": "2.0", "id": 4, "method": "mcp++/risk/profile", "params": {}},
        initialized=False,
    ))
    assert response["error"]["message"] == "init_required"
