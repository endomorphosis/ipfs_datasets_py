"""Profile E: libp2p+Trio P2P Transport for ipfs_datasets_py MCP++ server.

Implements the MCP++ Profile E specification using libp2p with Trio:
- Peer identity (Ed25519 keypair → PeerId)
- Stream multiplexing over /mcp+p2p/1.0.0 protocol
- Peer discovery (mDNS local, DHT wide-area)
- Tool invocation over P2P streams

Integrates with the existing MCP server to expose all registered tools
over the libp2p network, allowing peer-to-peer dataset operations.

Module: ipfs_datasets_py.mcp_server.p2p_libp2p_transport
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

logger = logging.getLogger("ipfs_datasets.mcp_server.p2p_libp2p")


def ensure_libp2p_installed() -> bool:
    """Auto-install libp2p from git if not already available.

    Returns True if libp2p is importable after this call.
    """
    try:
        import libp2p  # noqa: F401
        return True
    except ImportError:
        pass

    logger.info("libp2p not found — auto-installing from git (py-libp2p@main)...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "libp2p @ git+https://github.com/libp2p/py-libp2p.git@main",
             "multiaddr", "protobuf>=3.20.0"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=120,
        )
        import libp2p  # noqa: F401
        logger.info("libp2p installed successfully")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ImportError) as e:
        logger.error("Failed to auto-install libp2p: %s", e)
        return False


async def ensure_libp2p_installed_async() -> bool:
    """Trio-native async version for use within a running Trio context."""
    try:
        import libp2p  # noqa: F401
        return True
    except ImportError:
        pass

    import trio
    logger.info("libp2p not found — async-installing from git (py-libp2p@main)...")
    try:
        result = await trio.run_process(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "libp2p @ git+https://github.com/libp2p/py-libp2p.git@main",
             "multiaddr", "protobuf>=3.20.0"],
            capture_stdout=True, capture_stderr=True,
        )
        if result.returncode != 0:
            logger.error("pip install failed: %s", result.stderr.decode())
            return False
        import libp2p  # noqa: F401
        logger.info("libp2p installed successfully (async)")
        return True
    except (OSError, ImportError) as e:
        logger.error("Failed to auto-install libp2p: %s", e)
        return False

# Protocol ID per MCP++ spec
MCP_P2P_PROTOCOL = "/mcp+p2p/1.0.0"

# Maximum P2P message size (16 MiB) — prevents allocation attacks via 4-byte length prefix
MAX_P2P_MESSAGE_SIZE = 16 * 1024 * 1024
MAX_PROFILE_E_FRAMES_PER_SESSION = 200
MCP_PROTOCOL_VERSION = "2024-11-05"

# Default bootstrap peers
DEFAULT_BOOTSTRAP_PEERS = [
    "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
]


@dataclass
class PeerInfo:
    """Information about a connected P2P peer."""
    peer_id: str
    multiaddrs: List[str] = field(default_factory=list)
    protocols: List[str] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)
    capabilities: List[str] = field(default_factory=list)
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "multiaddrs": self.multiaddrs,
            "protocols": self.protocols,
            "last_seen": self.last_seen,
            "capabilities": self.capabilities,
            "latency_ms": self.latency_ms,
        }


@dataclass
class P2PMessage:
    """A message sent over the /mcp+p2p/1.0.0 protocol.

    Wire format: 4-byte big-endian length prefix + JSON payload.
    """
    msg_type: str  # "request" | "response" | "notification"
    method: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    msg_id: str = ""
    result: Any = None
    error: Optional[str] = None
    sender_peer_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def encode(self) -> bytes:
        """Encode as length-prefixed JSON."""
        payload = json.dumps({
            "type": self.msg_type,
            "method": self.method,
            "params": self.params,
            "id": self.msg_id,
            "result": self.result,
            "error": self.error,
            "sender": self.sender_peer_id,
            "timestamp": self.timestamp,
        }, separators=(",", ":")).encode("utf-8")
        length = len(payload).to_bytes(4, "big")
        return length + payload

    @classmethod
    def decode(cls, data: bytes) -> "P2PMessage":
        """Decode a length-prefixed JSON message."""
        if len(data) < 4:
            raise ValueError("Message too short")
        length = int.from_bytes(data[:4], "big")
        if length > MAX_P2P_MESSAGE_SIZE:
            raise ValueError(f"Message size {length} exceeds limit {MAX_P2P_MESSAGE_SIZE}")
        if len(data) < 4 + length:
            raise ValueError(f"Incomplete message: expected {length} bytes, got {len(data) - 4}")
        payload = json.loads(data[4:4 + length].decode("utf-8"))
        return cls(
            msg_type=payload.get("type", "request"),
            method=payload.get("method", ""),
            params=payload.get("params", {}),
            msg_id=payload.get("id", ""),
            result=payload.get("result"),
            error=payload.get("error"),
            sender_peer_id=payload.get("sender", ""),
            timestamp=payload.get("timestamp", time.time()),
        )


async def dispatch_profile_e_jsonrpc_request(
    request: Mapping[str, Any], *, initialized: bool = True,
    profile_g_negotiated: bool = True,
) -> dict[str, Any] | None:
    """Dispatch one canonical MCP++ Profile E JSON-RPC request.

    This is deliberately independent of the FastAPI server and optional model
    integrations. It keeps the native datasets libp2p surface usable for
    policy gates and ceremony verification even when no HTTP server is
    running, while the managed SwissKnife bridge can use the same operations
    against a live backend.
    """

    request_id = request.get("id")
    if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return _jsonrpc_error(request_id, -32600, "invalid JSON-RPC request")

    method = str(request["method"])
    params = request.get("params", {})
    if not isinstance(params, Mapping):
        return _jsonrpc_error(request_id, -32602, "params must be an object")

    # Notifications do not carry a request id and must not generate a reply.
    if method == "notifications/initialized":
        return None
    if not initialized and method != "initialize":
        return _jsonrpc_error(request_id, -32000, "init_required")
    if method == "initialize":
        return _jsonrpc_result(request_id, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "serverInfo": {"name": "ipfs-datasets-mcp-profile-e", "version": "1.0.0"},
            "capabilities": {
                "tools": {"listChanged": True},
                "mcpPlusPlusProfiles": [
                    "mcp++/deontic-policy",
                    "mcp++/event-dag",
                    "mcp++/p2p-transport",
                    "mcp++/risk-scheduling",
                ],
                "experimental": {
                    "mcp++/deontic-policy": True,
                    "mcp++/event-dag": True,
                    "mcp++/groth16-mpc-ceremony": True,
                    "mcp++/p2p-transport": True,
                    "mcp++/risk-scheduling": {
                        "version": "1.0",
                        "artifact_schema_major": 1,
                    },
                },
            },
        })
    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": []})
    if method == "mcp++/policy/evaluate":
        try:
            from ipfs_datasets_py.logic.profile_d_policy import (
                ProfileDPolicyError,
                evaluate_execution_policy,
            )

            result = evaluate_execution_policy(
                actor=params.get("actor", ""),
                action=params.get("action", ""),
                resource=params.get("resource"),
                policy=params.get("policy") if isinstance(params.get("policy"), Mapping) else None,
                policy_text=params.get("policy_text"),
                evaluated_at=params.get("evaluated_at"),
                intent_cid=params.get("intent_cid"),
                request_zkp_certificate=bool(params.get("request_zkp_certificate", False)),
            )
            return _jsonrpc_result(request_id, result)
        except ProfileDPolicyError as error:
            return _jsonrpc_error(request_id, -32602, str(error))
        except Exception as error:  # pragma: no cover - defensive transport boundary
            return _jsonrpc_error(request_id, -32603, str(error))
    if method == "mcp++/zk/ceremony/validate":
        manifest = params.get("manifest")
        if not isinstance(manifest, Mapping):
            return _jsonrpc_error(request_id, -32602, "manifest must be an object")
        try:
            from ipfs_datasets_py.logic.zkp.ceremony import validate_groth16_mpc_ceremony

            return _jsonrpc_result(request_id, validate_groth16_mpc_ceremony(manifest).to_dict())
        except Exception as error:  # pragma: no cover - defensive transport boundary
            return _jsonrpc_error(request_id, -32603, str(error))
    if method.startswith(("mcp++/goals/", "mcp++/tasks/", "mcp++/risk/", "mcp++/neighborhood/", "mcp++/schedule/")):
        from ipfs_datasets_py.logic.profile_g import ProfileGError
        from ipfs_datasets_py.mcp_server.profile_g_service import (
            get_profile_g_service,
            profile_g_jsonrpc_error,
        )

        if not profile_g_negotiated:
            error = ProfileGError(
                "G_CAPABILITY_NOT_NEGOTIATED", "Profile G was not negotiated"
            )
            return profile_g_jsonrpc_error(request_id, error)
        try:
            return _jsonrpc_result(request_id, get_profile_g_service().dispatch(method, params))
        except ProfileGError as error:
            return profile_g_jsonrpc_error(request_id, error)
    return _jsonrpc_error(request_id, -32601, f"unsupported method: {method}")


def _jsonrpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def _read_exact(stream: Any, size: int) -> bytes | None:
    """Read exactly ``size`` bytes, tolerating fragmented libp2p reads."""

    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = await stream.read(remaining)
        if not chunk:
            return None if not chunks else b""
        chunks.append(bytes(chunk))
        remaining -= len(chunk)
    return b"".join(chunks)


def _jsonrpc_frame(message: Mapping[str, Any]) -> bytes:
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return len(payload).to_bytes(4, "big") + payload


class MCPp2pNode:
    """A libp2p node for the ipfs_datasets MCP++ server.

    Uses Trio as the async runtime. Exposes all registered MCP tools
    over the /mcp+p2p/1.0.0 protocol for peer-to-peer invocation.

    Usage::

        import trio

        async def main():
            async with trio.open_nursery() as nursery:
                node = MCPp2pNode()
                await node.start(nursery)
                # Node is now accepting P2P tool calls
                await trio.sleep_forever()

        trio.run(main)
    """

    def __init__(self, listen_addrs: Optional[List[str]] = None,
                 bootstrap_peers: Optional[List[str]] = None):
        self._listen_addrs = listen_addrs or ["/ip4/0.0.0.0/tcp/0"]
        self._bootstrap_peers = bootstrap_peers or DEFAULT_BOOTSTRAP_PEERS
        self._host = None
        self._peers: Dict[str, PeerInfo] = {}
        self._tool_handler: Optional[Callable] = None
        self._started = False
        self._nursery = None
        self._network_ready = None
        self._network_cancel_scope = None

    @property
    def peer_id(self) -> str:
        if self._host:
            return str(self._host.get_id())
        return ""

    @property
    def multiaddrs(self) -> List[str]:
        if self._host:
            return [str(a) for a in self._host.get_addrs()]
        return []

    @property
    def connected_peers(self) -> List[PeerInfo]:
        return list(self._peers.values())

    def set_tool_handler(self, handler: Callable) -> None:
        """Set handler for incoming tool calls.

        Signature: async def handler(method: str, params: dict) -> Any
        """
        self._tool_handler = handler

    async def start(self, nursery) -> None:
        """Start the libp2p node with Trio structured concurrency."""
        self._nursery = nursery

        # Auto-install libp2p if missing
        if not ensure_libp2p_installed():
            logger.error(
                "libp2p could not be installed. P2P transport in stub mode. "
                "Manual install: pip install 'libp2p @ git+https://github.com/libp2p/py-libp2p.git@main'"
            )
            self._started = True
            return

        try:
            import trio
            from libp2p import new_host
            from libp2p.crypto.secp256k1 import create_new_key_pair
            from libp2p.tools.async_service import background_trio_service
            from multiaddr import Multiaddr

            key_pair = create_new_key_pair()
            self._host = new_host(key_pair=key_pair)

            # Register protocol handler
            self._host.set_stream_handler(MCP_P2P_PROTOCOL, self._handle_stream)

            # py-libp2p only accepts listeners while its network service is
            # running. Keep that service under the caller-provided nursery so
            # native Profile E obeys Trio lifecycle rules.
            self._network_ready = trio.Event()

            async def run_network_service() -> None:
                with trio.CancelScope() as cancel_scope:
                    self._network_cancel_scope = cancel_scope
                    async with background_trio_service(self._host.get_network()):
                        self._network_ready.set()
                        await trio.sleep_forever()

            nursery.start_soon(run_network_service)
            await self._network_ready.wait()

            # Start listening after the network service is accepting events.
            for addr in self._listen_addrs:
                await self._host.get_network().listen(Multiaddr(addr))

            self._started = True
            logger.info(f"P2P node started: peer_id={self.peer_id}, addrs={self.multiaddrs}")

            # Bootstrap
            for peer_addr in self._bootstrap_peers:
                nursery.start_soon(self._connect_peer, peer_addr)

        except ImportError as e:
            logger.warning(f"libp2p not available ({e}). P2P in stub mode.")
            self._started = True

    async def stop(self) -> None:
        """Stop the libp2p node."""
        if self._network_cancel_scope is not None:
            self._network_cancel_scope.cancel()
            self._network_cancel_scope = None
        if self._host:
            await self._host.close()
        self._started = False
        self._peers.clear()
        logger.info("P2P node stopped")

    async def _connect_peer(self, peer_addr: str) -> None:
        """Connect to a peer by multiaddr."""
        try:
            from libp2p.peer.peerinfo import info_from_p2p_addr
            from multiaddr import Multiaddr

            peer_info = info_from_p2p_addr(Multiaddr(peer_addr))
            await self._host.connect(peer_info)
            self._peers[str(peer_info.peer_id)] = PeerInfo(
                peer_id=str(peer_info.peer_id),
                multiaddrs=[peer_addr],
                protocols=[MCP_P2P_PROTOCOL],
            )
            logger.info(f"Connected to peer: {peer_info.peer_id}")
        except Exception as e:
            logger.debug(f"Failed to connect to {peer_addr}: {e}")

    async def _handle_stream(self, stream) -> None:
        """Handle canonical JSON-RPC plus legacy P2P messages on one stream."""
        initialized = False
        profile_g_negotiated = False
        try:
            for _frame_number in range(MAX_PROFILE_E_FRAMES_PER_SESSION):
                length_bytes = await _read_exact(stream, 4)
                if length_bytes is None:
                    break
                if len(length_bytes) != 4:
                    logger.warning("Closing truncated Profile E frame header")
                    break
                length = int.from_bytes(length_bytes, "big")
                if length > MAX_P2P_MESSAGE_SIZE:
                    logger.warning("Rejecting oversized P2P message: %d bytes", length)
                    break
                payload = await _read_exact(stream, length)
                if payload is None or len(payload) != length:
                    logger.warning("Closing truncated Profile E frame payload")
                    break

                decoded = json.loads(payload.decode("utf-8"))
                if isinstance(decoded, Mapping) and decoded.get("jsonrpc") == "2.0":
                    response = await dispatch_profile_e_jsonrpc_request(
                        decoded, initialized=initialized,
                        profile_g_negotiated=profile_g_negotiated,
                    )
                    if response is not None:
                        await stream.write(_jsonrpc_frame(response))
                    if decoded.get("method") == "initialize":
                        initialized = True
                        init_params = decoded.get("params") if isinstance(decoded.get("params"), Mapping) else {}
                        experimental = (
                            init_params.get("capabilities", {}).get("experimental", {})
                            if isinstance(init_params.get("capabilities"), Mapping) else {}
                        )
                        profile_g_negotiated = bool(
                            isinstance(experimental, Mapping)
                            and experimental.get("mcp++/risk-scheduling")
                        ) or init_params.get("profile") == "mcp++/risk-scheduling" or (
                            isinstance(init_params.get("profiles"), list)
                            and "mcp++/risk-scheduling" in init_params["profiles"]
                        )
                    continue

                # Preserve the original message shape for existing tool callers
                # while canonical JSON-RPC is used for all MCP++ profiles.
                msg = P2PMessage.decode(length_bytes + payload)
                if msg.msg_type == "request" and self._tool_handler:
                    try:
                        result = await self._tool_handler(msg.method, msg.params)
                        response = P2PMessage(
                            msg_type="response", method=msg.method,
                            msg_id=msg.msg_id, result=result,
                            sender_peer_id=self.peer_id,
                        )
                    except Exception as error:
                        response = P2PMessage(
                            msg_type="response", method=msg.method,
                            msg_id=msg.msg_id, error=str(error),
                            sender_peer_id=self.peer_id,
                        )
                    await stream.write(response.encode())
            else:
                logger.warning("Closing Profile E stream after %d frames", MAX_PROFILE_E_FRAMES_PER_SESSION)
        except Exception as e:
            logger.debug(f"Stream handler error: {e}")
        finally:
            await stream.close()

    async def call_tool(self, peer_id: str, method: str,
                        params: Dict[str, Any], timeout: float = 30.0) -> Any:
        """Call a tool on a remote peer via /mcp+p2p/1.0.0.

        Args:
            peer_id: Target peer ID
            method: Tool name
            params: Tool parameters
            timeout: Timeout in seconds

        Returns:
            Tool result from remote peer
        """
        if not self._host:
            raise ConnectionError("P2P node not started")

        try:
            import trio
            from libp2p.peer.id import ID as PeerID

            target = PeerID.from_base58(peer_id)
            stream = await self._host.new_stream(target, [MCP_P2P_PROTOCOL])

            request = P2PMessage(
                msg_type="request", method=method, params=params,
                msg_id=f"{method}_{time.time()}", sender_peer_id=self.peer_id,
            )
            await stream.write(request.encode())

            with trio.move_on_after(timeout) as cancel_scope:
                length_bytes = await stream.read(4)
                if len(length_bytes) < 4:
                    raise ConnectionError("Peer closed connection")
                length = int.from_bytes(length_bytes, "big")
                payload = await stream.read(length)
                response = P2PMessage.decode(length_bytes + payload)

            if cancel_scope.cancelled_caught:
                await stream.close()
                raise TimeoutError(f"Peer {peer_id} timeout after {timeout}s")

            await stream.close()

            if response.error:
                raise RuntimeError(f"Remote error: {response.error}")
            return response.result

        except ImportError:
            raise ConnectionError("libp2p not available")

    async def discover_local(self, service_tag: str = "mcp-datasets") -> List[PeerInfo]:
        """Discover local peers via mDNS."""
        try:
            import trio
            from zeroconf import Zeroconf, ServiceBrowser

            discovered = []
            zc = Zeroconf()

            class Listener:
                def add_service(self, zc, type_, name):
                    info = zc.get_service_info(type_, name)
                    if info and info.parsed_addresses():
                        discovered.append(PeerInfo(
                            peer_id=name.split(".")[0],
                            multiaddrs=[f"/ip4/{info.parsed_addresses()[0]}/tcp/{info.port}"],
                            protocols=[MCP_P2P_PROTOCOL],
                        ))

                def remove_service(self, zc, type_, name):
                    pass

                def update_service(self, zc, type_, name):
                    pass

            ServiceBrowser(zc, f"_{service_tag}._tcp.local.", Listener())
            await trio.sleep(2.0)
            zc.close()

            for peer in discovered:
                self._peers[peer.peer_id] = peer
            return discovered

        except ImportError:
            logger.debug("zeroconf not available for mDNS")
            return []
        except Exception as e:
            logger.debug(f"mDNS discovery failed: {e}")
            return []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "multiaddrs": self.multiaddrs,
            "protocol": MCP_P2P_PROTOCOL,
            "started": self._started,
            "connected_peers": len(self._peers),
            "peers": [p.to_dict() for p in self._peers.values()],
        }


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_NODE: Optional[MCPp2pNode] = None


def get_p2p_node() -> MCPp2pNode:
    """Get or create the global P2P node singleton."""
    global _NODE
    if _NODE is None:
        _NODE = MCPp2pNode()
    return _NODE
