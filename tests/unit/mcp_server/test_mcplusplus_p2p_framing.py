"""Runtime binding tests for hardened Profile E (MCPP-065).

Interface: RuntimeP2pAdapter@1
Acceptance:
  * Runtime tests reuse the MCPP-064 abuse vectors (P2pAbuseVector@1).
  * Untracked datasets P2P transport is dispositioned (integrated), not discarded.
  * Datasets and kit use versioned protocol IDs and shared framing rules.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Tuple

import pytest

# ---------------------------------------------------------------------------
# Path setup: datasets package + kit package + abuse suite (MCPP-064)
# ---------------------------------------------------------------------------

_TESTS_DIR = Path(__file__).resolve().parent
_DATASETS_ROOT = _TESTS_DIR.parents[2]  # .../ipfs_datasets_py
_WORKSPACE_ROOT = _DATASETS_ROOT.parent  # monorepo / workspace root
_KIT_ROOT = _WORKSPACE_ROOT / "ipfs_kit_py"
_ACCEL_MCPP_TESTS = (
    _WORKSPACE_ROOT / "ipfs_accelerate_py" / "mcplusplus" / "tests-py"
)


def _ensure_on_path(path: Path) -> None:
    text = str(path)
    if path.exists() and text not in sys.path:
        sys.path.insert(0, text)


_ensure_on_path(_DATASETS_ROOT)
_ensure_on_path(_KIT_ROOT)
_ensure_on_path(_ACCEL_MCPP_TESTS)
# Prefer local accelerate checkout for validators used by the abuse suite.
_ensure_on_path(_WORKSPACE_ROOT / "ipfs_accelerate_py")


from ipfs_datasets_py.mcp_server.mcplusplus import p2p_framing as framing  # noqa: E402
from ipfs_datasets_py.mcp_server.mcplusplus import (  # noqa: E402
    p2p_libp2p_transport as datasets_rt,
)


def _load_kit_p2p() -> ModuleType:
    """Import kit p2p_transport without requiring a full kit install."""
    try:
        return importlib.import_module("ipfs_kit_py.mcp_server.p2p_transport")
    except Exception:
        path = _KIT_ROOT / "ipfs_kit_py" / "mcp_server" / "p2p_transport.py"
        if not path.is_file():
            raise
        spec = importlib.util.spec_from_file_location(
            "ipfs_kit_py.mcp_server.p2p_transport", path
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod


kit_rt = _load_kit_p2p()


def _load_abuse_suite() -> ModuleType:
    """Load MCPP-064 P2pAbuseVector@1 recipes + evaluator."""
    # Preferred: package-style import via tests-py on sys.path
    try:
        return importlib.import_module("integration.test_transport_abuse")
    except Exception:
        pass
    path = _ACCEL_MCPP_TESTS / "integration" / "test_transport_abuse.py"
    if not path.is_file():
        pytest.skip(f"abuse suite not found at {path}")
    # Ensure validators package resolves
    _ensure_on_path(_ACCEL_MCPP_TESTS)
    spec = importlib.util.spec_from_file_location(
        "mcpp_test_transport_abuse", path
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Parent package stubs so relative imports inside the suite keep working
    sys.modules.setdefault("integration", ModuleType("integration"))
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        pytest.skip(f"abuse suite import failed: {exc}")
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def abuse() -> ModuleType:
    return _load_abuse_suite()


@pytest.fixture(scope="module")
def abuse_recipes(abuse: ModuleType) -> Dict[str, Dict[str, Any]]:
    return abuse.build_abuse_recipes()


@pytest.fixture(scope="module")
def abuse_case_ids(abuse: ModuleType) -> Tuple[str, ...]:
    return tuple(abuse.ABUSE_CASE_IDS)


# ---------------------------------------------------------------------------
# Protocol / framing parity
# ---------------------------------------------------------------------------


class TestProtocolAndFramingParity:
    def test_interface_label(self) -> None:
        assert datasets_rt.INTERFACE_LABEL == "RuntimeP2pAdapter@1"
        assert kit_rt.INTERFACE_LABEL == "RuntimeP2pAdapter@1"

    def test_versioned_protocol_id_shared(self) -> None:
        assert datasets_rt.PROTOCOL_ID == "/mcp+p2p/1.0.0"
        assert kit_rt.PROTOCOL_ID == "/mcp+p2p/1.0.0"
        assert framing.PROTOCOL_ID_DEFAULT == "/mcp+p2p/1.0.0"
        assert datasets_rt.PROTOCOL_ID in datasets_rt.SUPPORTED_PROTOCOL_IDS
        assert kit_rt.PROTOCOL_ID in kit_rt.SUPPORTED_PROTOCOL_IDS

    def test_max_frame_default_16mib(self) -> None:
        assert datasets_rt.MAX_FRAME_BYTES == 16 * 1024 * 1024
        assert kit_rt.MAX_FRAME_BYTES == 16 * 1024 * 1024
        assert framing.DEFAULT_MAX_FRAME_BYTES == 16 * 1024 * 1024

    def test_length_prefixed_roundtrip_datasets(self) -> None:
        adapter = datasets_rt.RuntimeP2pAdapter(max_frame_bytes=4096)
        payload = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
        frame = adapter.encode_frame(payload)
        assert frame[:4] == len(frame[4:]).to_bytes(4, "big")
        assert adapter.decode_frame(frame) == payload

    def test_length_prefixed_roundtrip_kit(self) -> None:
        adapter = kit_rt.RuntimeP2pAdapter(max_frame_bytes=4096)
        payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        frame = adapter.encode_frame(payload)
        assert adapter.decode_frame(frame) == payload

    def test_shared_framing_encode_matches_datasets_helper(self) -> None:
        payload = {"jsonrpc": "2.0", "id": "x", "method": "ping", "params": {}}
        a = framing.encode_jsonrpc_frame(payload, max_frame_bytes=1024)
        b = datasets_rt.encode_jsonrpc_frame(payload, max_frame_bytes=1024)
        c = kit_rt.encode_frame(payload, max_frame_bytes=1024)
        assert a == b == c

    def test_forged_protocol_id_rejected(self) -> None:
        assert datasets_rt.is_forged_protocol_version("/mcp+p2p/9.9.9-forged")
        assert kit_rt.is_forged_protocol_version("/mcp+p2p/9.9.9-forged")
        with pytest.raises(datasets_rt.FramingError):
            datasets_rt.RuntimeP2pAdapter().negotiate_protocol(
                "/mcp+p2p/9.9.9-forged"
            )
        with pytest.raises(kit_rt.FramingError):
            kit_rt.RuntimeP2pAdapter().negotiate_protocol("/mcp+p2p/9.9.9-forged")


# ---------------------------------------------------------------------------
# Legacy disposition (do not discard untracked datasets transport)
# ---------------------------------------------------------------------------


class TestLegacyTransportDisposition:
    def test_disposition_recorded_and_not_discarded(self) -> None:
        disp = datasets_rt.legacy_transport_disposition()
        assert disp["discarded"] is False
        assert disp["status"] in {"integrated", "recorded_unavailable"}
        assert "p2p_libp2p_transport" in disp["module"]
        assert disp["path"].endswith("p2p_libp2p_transport.py")

    def test_legacy_module_still_importable(self) -> None:
        # Disposition requires integrating prior work — the source module
        # must remain loadable when present on disk.
        legacy_path = (
            _DATASETS_ROOT
            / "ipfs_datasets_py"
            / "mcp_server"
            / "p2p_libp2p_transport.py"
        )
        assert legacy_path.is_file(), "untracked/legacy transport must not be deleted"
        if datasets_rt.LEGACY_TRANSPORT_AVAILABLE:
            assert datasets_rt.MCPp2pNode is not None
            assert datasets_rt.MCP_P2P_PROTOCOL == "/mcp+p2p/1.0.0"
            assert "MCPp2pNode" in datasets_rt.LEGACY_TRANSPORT_DISPOSITION["exports"]


# ---------------------------------------------------------------------------
# Abuse vectors reused at the runtime adapter (datasets + kit framing)
# ---------------------------------------------------------------------------


class TestAbuseVectorsReusedByRuntime:
    def test_recipe_set_covers_all_required_cases(
        self, abuse_recipes: Dict[str, Dict[str, Any]], abuse_case_ids: Tuple[str, ...]
    ) -> None:
        assert set(abuse_recipes.keys()) == set(abuse_case_ids)

    def test_canonical_evaluator_still_fails_closed(
        self,
        abuse: ModuleType,
        abuse_recipes: Dict[str, Dict[str, Any]],
        abuse_case_ids: Tuple[str, ...],
    ) -> None:
        """Reuse the MCPP-064 evaluator: every case must fail closed."""
        failures: List[str] = []
        for case_id in abuse_case_ids:
            verdict = abuse.evaluate_p2p_abuse_vector(abuse_recipes[case_id])
            if verdict.admitted or not verdict.fail_closed:
                failures.append(
                    f"{case_id}: admitted={verdict.admitted} reasons={verdict.reasons}"
                )
        assert not failures, "abuse cases must fail closed:\n" + "\n".join(failures)

    def test_datasets_runtime_adapter_fails_closed_on_all_recipes(
        self,
        abuse_recipes: Dict[str, Dict[str, Any]],
        abuse_case_ids: Tuple[str, ...],
    ) -> None:
        adapter = datasets_rt.RuntimeP2pAdapter(max_frame_bytes=1024)
        failures: List[str] = []
        for case_id in abuse_case_ids:
            verdict = adapter.evaluate_abuse_vector(abuse_recipes[case_id])
            if verdict.admitted or not verdict.fail_closed:
                failures.append(
                    f"{case_id}: admitted={verdict.admitted} reasons={verdict.reasons}"
                )
            if verdict.case_id != case_id:
                failures.append(f"{case_id}: case_id mismatch {verdict.case_id}")
        assert not failures, "datasets runtime must fail closed:\n" + "\n".join(
            failures
        )

    @pytest.mark.parametrize(
        "case_id",
        [
            "oversized",
            "truncated",
            "invalid_length",
            "request_before_negotiation",
            "forged_version",
            "unknown_method",
            "empty_success_on_transport_failure",
            "replay",
            "flood",
            "excessive_streams",
            "valid_peerid_invalid_ucan",
            "stale_fence",
            "duplicate_response",
            "wrong_correlation_id",
        ],
    )
    def test_datasets_adapter_case_parametrized(
        self, abuse_recipes: Dict[str, Dict[str, Any]], case_id: str
    ) -> None:
        adapter = datasets_rt.RuntimeP2pAdapter(max_frame_bytes=1024)
        verdict = adapter.evaluate_abuse_vector(abuse_recipes[case_id])
        assert verdict.case_id == case_id
        assert verdict.admitted is False
        assert verdict.fail_closed is True
        assert len(verdict.reasons) >= 1

    def test_kit_framing_rejects_oversized_and_truncated(
        self, abuse_recipes: Dict[str, Dict[str, Any]]
    ) -> None:
        max_frame = 1024
        adapter = kit_rt.RuntimeP2pAdapter(max_frame_bytes=max_frame)
        oversized = abuse_recipes["oversized"]
        with pytest.raises(kit_rt.FrameSizeExceededError):
            adapter.encode_frame(oversized["payload"])
        with pytest.raises((kit_rt.FramingError, kit_rt.FrameSizeExceededError)):
            adapter.decode_frame(bytes(oversized["frame"]))
        with pytest.raises(kit_rt.FramingError):
            adapter.decode_frame(bytes(abuse_recipes["truncated"]["frame"]))

    def test_kit_rejects_request_before_negotiation(
        self, abuse_recipes: Dict[str, Dict[str, Any]]
    ) -> None:
        adapter = kit_rt.RuntimeP2pAdapter(max_frame_bytes=1024)
        frame = kit_rt.encode_frame(
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
            max_frame_bytes=1024,
        )
        with pytest.raises(kit_rt.FramingError, match="request_before_negotiation"):
            adapter.admit_frame(frame)

    def test_kit_stream_quota_fail_closed(
        self, abuse_recipes: Dict[str, Dict[str, Any]]
    ) -> None:
        recipe = abuse_recipes["excessive_streams"]
        max_streams = int(recipe["max_streams_per_peer"])
        adapter = kit_rt.RuntimeP2pAdapter(
            max_frame_bytes=1024, max_streams_per_peer=max_streams
        )
        adapter.negotiate_protocol(kit_rt.PROTOCOL_ID)
        peer = str(recipe["peer_id"])
        for _ in range(max_streams):
            adapter.stream_quota.open(peer)
        with pytest.raises(kit_rt.QuotaExceededError):
            adapter.stream_quota.open(peer)

    def test_kit_replay_fail_closed(self, abuse_recipes: Dict[str, Dict[str, Any]]) -> None:
        frames = list(abuse_recipes["replay"]["frames"])
        adapter = kit_rt.RuntimeP2pAdapter(max_frame_bytes=1024)
        adapter.negotiate_protocol(kit_rt.PROTOCOL_ID)
        adapter.open_stream("peer-replay")
        adapter.admit_frame(bytes(frames[0]), now=1.0)
        with pytest.raises(kit_rt.ReplayDetectedError):
            adapter.admit_frame(bytes(frames[1]), now=1.1)


# ---------------------------------------------------------------------------
# Negotiation + authority gates on datasets adapter
# ---------------------------------------------------------------------------


class TestDatasetsRuntimeGates:
    def test_negotiate_and_admit_happy_path(self) -> None:
        adapter = datasets_rt.RuntimeP2pAdapter(max_frame_bytes=4096)
        adapter.negotiate_protocol(datasets_rt.PROTOCOL_ID)
        adapter.open_stream("12D3KooWTestPeer")
        frame = adapter.encode_frame(
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
        )
        payload = adapter.admit_frame(frame, now=10.0)
        assert payload["method"] == "ping"

    def test_peerid_not_execution_authority(self) -> None:
        adapter = datasets_rt.RuntimeP2pAdapter()
        with pytest.raises(PermissionError):
            adapter.admit_execution(
                peer_id="12D3KooWValid",
                ucan_present=True,
                ucan_valid=False,
            )

    def test_stale_fence_denied(self) -> None:
        adapter = datasets_rt.RuntimeP2pAdapter()
        with pytest.raises(PermissionError):
            adapter.admit_execution(
                peer_id="12D3KooWValid",
                ucan_present=True,
                ucan_valid=True,
                fencing_token=1,
                current_fence=5,
            )

    def test_empty_success_under_transport_failure(self) -> None:
        assert datasets_rt.treat_empty_success_as_failure(
            {"jsonrpc": "2.0", "id": 1, "result": {}},
            status=503,
            transport_error="stream_reset",
            stream_closed=True,
        )

    def test_snapshot_includes_legacy_disposition(self) -> None:
        snap = datasets_rt.RuntimeP2pAdapter().snapshot()
        assert snap["interface"] == "RuntimeP2pAdapter@1"
        assert snap["legacy_disposition"]["discarded"] is False


# ---------------------------------------------------------------------------
# Kit handle_stream_message framing modes
# ---------------------------------------------------------------------------


class TestKitStreamHandler:
    def test_raw_json_roundtrip_compat(self) -> None:
        import asyncio
        import json

        async def handler(req: dict) -> dict:
            return {"jsonrpc": "2.0", "id": req.get("id"), "result": {"ok": True}}

        raw = b'{"jsonrpc":"2.0","id":7,"method":"tools/list","params":{}}'
        out = asyncio.run(kit_rt.handle_stream_message(raw, handler))
        resp = json.loads(out.decode("utf-8"))
        assert resp["result"]["ok"] is True
        assert resp["id"] == 7

    def test_framed_roundtrip(self) -> None:
        import asyncio

        async def handler(req: dict) -> dict:
            return {"jsonrpc": "2.0", "id": req.get("id"), "result": {"ok": True}}

        frame = kit_rt.encode_frame(
            {"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {}},
            max_frame_bytes=1024,
        )
        out = asyncio.run(kit_rt.handle_stream_message(frame, handler))
        payload, consumed = kit_rt.decode_frame(out, max_frame_bytes=1024)
        assert consumed == len(out)
        assert payload["result"]["ok"] is True
        assert payload["id"] == 9
