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
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

try:
    from ipfs_accelerate_py.mcplusplus_module.p2p.libp2p_runtime import (
        LIBP2P_INSTALL_HINT,
        PY_LIBP2P_MAIN_SPEC,
        create_libp2p_key_pair,
        ensure_libp2p_runtime,
        install_libp2p_runtime,
        install_libp2p_runtime_async,
        make_multiaddr,
        new_libp2p_host,
        peer_id_from_base58,
        peerinfo_from_multiaddr,
    )
except Exception:  # pragma: no cover - optional MCP++ provider dependency
    LIBP2P_INSTALL_HINT = "pip install 'ipfs_accelerate_py[mcp-p2p]'"
    PY_LIBP2P_MAIN_SPEC = "libp2p @ git+https://github.com/libp2p/py-libp2p.git@main"
    create_libp2p_key_pair = None  # type: ignore[assignment]
    ensure_libp2p_runtime = None  # type: ignore[assignment]
    install_libp2p_runtime = None  # type: ignore[assignment]
    install_libp2p_runtime_async = None  # type: ignore[assignment]
    make_multiaddr = None  # type: ignore[assignment]
    new_libp2p_host = None  # type: ignore[assignment]
    peer_id_from_base58 = None  # type: ignore[assignment]
    peerinfo_from_multiaddr = None  # type: ignore[assignment]

logger = logging.getLogger("ipfs_datasets.mcp_server.p2p_libp2p")


def ensure_libp2p_installed() -> bool:
    """Auto-install libp2p from git if not already available.

    Returns True if libp2p is importable after this call.
    """
    if callable(ensure_libp2p_runtime) and ensure_libp2p_runtime():
        return True

    if not callable(install_libp2p_runtime):
        logger.error("MCP++ libp2p runtime provider is unavailable; install ipfs_accelerate_py[mcp-p2p]")
        return False

    logger.info("libp2p not found — delegating install to MCP++ py-libp2p runtime...")
    if install_libp2p_runtime(quiet=True, timeout=120, upgrade=True):
        logger.info("libp2p installed successfully")
        return True
    return False


async def ensure_libp2p_installed_async() -> bool:
    """Trio-native async version for use within a running Trio context."""
    if callable(ensure_libp2p_runtime) and ensure_libp2p_runtime():
        return True

    if not callable(install_libp2p_runtime_async):
        logger.error("MCP++ libp2p runtime provider is unavailable; install ipfs_accelerate_py[mcp-p2p]")
        return False

    logger.info("libp2p not found — async-delegating install to MCP++ py-libp2p runtime...")
    try:
        if await install_libp2p_runtime_async(quiet=True, timeout=120, upgrade=True):
            logger.info("libp2p installed successfully (async)")
            return True
    except OSError as e:
        logger.error("Failed to auto-install libp2p: %s", e)
    return False

# Protocol ID per MCP++ spec
MCP_P2P_PROTOCOL = "/mcp+p2p/1.0.0"

# Maximum P2P message size (16 MiB) — prevents allocation attacks via 4-byte length prefix
MAX_P2P_MESSAGE_SIZE = 16 * 1024 * 1024

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

        # Auto-install libp2p if missing through MCP++ runtime.
        if not await ensure_libp2p_installed_async():
            logger.error(
                "libp2p could not be installed. P2P transport in stub mode. "
                "Manual install: pip install %r"
                % (PY_LIBP2P_MAIN_SPEC,)
            )
            self._started = True
            return

        try:
            if not callable(create_libp2p_key_pair):
                raise ImportError("ipfs_accelerate_py MCP++ libp2p runtime is unavailable")
            key_pair = create_libp2p_key_pair()
            if not callable(new_libp2p_host) or not callable(make_multiaddr):
                raise ImportError("ipfs_accelerate_py MCP++ libp2p runtime is unavailable")
            self._host = await new_libp2p_host(key_pair=key_pair)

            # Register protocol handler
            self._host.set_stream_handler(MCP_P2P_PROTOCOL, self._handle_stream)

            # Start listening
            for addr in self._listen_addrs:
                await self._host.get_network().listen(make_multiaddr(addr))

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
        if self._host:
            await self._host.close()
        self._started = False
        self._peers.clear()
        logger.info("P2P node stopped")

    async def _connect_peer(self, peer_addr: str) -> None:
        """Connect to a peer by multiaddr."""
        try:
            if not callable(peerinfo_from_multiaddr):
                raise ImportError("ipfs_accelerate_py MCP++ libp2p runtime is unavailable")
            peer_info = peerinfo_from_multiaddr(peer_addr)
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
        """Handle incoming /mcp+p2p/1.0.0 stream."""
        try:
            # Read length-prefixed message
            length_bytes = await stream.read(4)
            if len(length_bytes) < 4:
                return
            length = int.from_bytes(length_bytes, "big")
            if length > MAX_P2P_MESSAGE_SIZE:
                logger.warning("Rejecting oversized P2P message: %d bytes", length)
                return
            payload = await stream.read(length)

            msg = P2PMessage.decode(length_bytes + payload)

            if msg.msg_type == "request" and self._tool_handler:
                try:
                    result = await self._tool_handler(msg.method, msg.params)
                    response = P2PMessage(
                        msg_type="response", method=msg.method,
                        msg_id=msg.msg_id, result=result,
                        sender_peer_id=self.peer_id,
                    )
                except Exception as e:
                    response = P2PMessage(
                        msg_type="response", method=msg.method,
                        msg_id=msg.msg_id, error=str(e),
                        sender_peer_id=self.peer_id,
                    )
                await stream.write(response.encode())

            await stream.close()
        except Exception as e:
            logger.debug(f"Stream handler error: {e}")

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

            if not callable(peer_id_from_base58):
                raise ImportError("ipfs_accelerate_py MCP++ libp2p runtime is unavailable")
            target = peer_id_from_base58(peer_id)
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
            raise ConnectionError(f"libp2p not available. Install via MCP++ runtime: {LIBP2P_INSTALL_HINT}")

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
