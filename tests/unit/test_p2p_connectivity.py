"""
Unit tests for P2P connectivity module.

Tests the libp2p universal-connectivity patterns for robust peer discovery
and NAT traversal.
"""

import pytest
import anyio

from ipfs_datasets_py.p2p_networking.p2p_connectivity import (
    UniversalConnectivity,
    ConnectivityConfig,
    get_universal_connectivity
)


class TestConnectivityConfig:
    """Test ConnectivityConfig dataclass."""
    
    def test_default_config(self):
        """Test default configuration."""
        config = ConnectivityConfig()
        
        assert config.enable_tcp is True
        assert config.enable_mdns is True
        assert config.enable_dht is True
        assert config.enable_relay is True
        assert config.enable_autonat is True
        assert config.enable_hole_punching is True
    
    def test_custom_config(self):
        """Test custom configuration."""
        config = ConnectivityConfig(
            enable_tcp=True,
            enable_quic=True,
            enable_mdns=False,
            dht_bucket_size=50
        )
        
        assert config.enable_tcp is True
        assert config.enable_quic is True
        assert config.enable_mdns is False
        assert config.dht_bucket_size == 50


class TestUniversalConnectivity:
    """Test UniversalConnectivity class."""
    
    @pytest.fixture
    def connectivity(self):
        """Create UniversalConnectivity instance for testing."""
        config = ConnectivityConfig()
        return UniversalConnectivity(config)
    
    def test_initialize_connectivity(self, connectivity):
        """Test connectivity initialization."""
        assert connectivity.config is not None
        assert isinstance(connectivity.discovered_peers, set)
        assert isinstance(connectivity.relay_peers, list)
    
    @pytest.mark.asyncio
    async def test_configure_transports(self, connectivity):
        """Test transport configuration."""
        # Mock host object
        class MockHost:
            pass
        
        host = MockHost()
        
        # Should not raise exception
        await connectivity.configure_transports(host)
    
    @pytest.mark.asyncio
    async def test_start_mdns_discovery(self, connectivity):
        """Test mDNS discovery start."""
        class MockHost:
            pass
        
        host = MockHost()
        
        # Should not raise exception
        await connectivity.start_mdns_discovery(host)
    
    @pytest.mark.asyncio
    async def test_configure_dht(self, connectivity):
        """Test DHT configuration."""
        class MockHost:
            pass
        
        host = MockHost()
        
        # Should not raise exception
        await connectivity.configure_dht(host)
    
    @pytest.mark.asyncio
    async def test_setup_circuit_relay(self, connectivity):
        """Test circuit relay setup."""
        class MockHost:
            pass
        
        host = MockHost()
        relay_addrs = [
            "/ip4/192.168.1.100/tcp/9000/p2p/QmTest1",
            "/ip4/10.0.0.50/tcp/9001/p2p/QmTest2"
        ]
        
        await connectivity.setup_circuit_relay(host, relay_addrs)
        
        assert len(connectivity.relay_peers) == 2
        assert connectivity.relay_peers == relay_addrs
    
    @pytest.mark.asyncio
    async def test_enable_autonat(self, connectivity):
        """Test AutoNAT enablement."""
        class MockHost:
            pass
        
        host = MockHost()
        
        # Should not raise exception
        await connectivity.enable_autonat(host)
    
    @pytest.mark.asyncio
    async def test_enable_hole_punching(self, connectivity):
        """Test hole punching enablement."""
        class MockHost:
            pass
        
        host = MockHost()
        
        # Should not raise exception
        await connectivity.enable_hole_punching(host)
    
    @pytest.mark.asyncio
    async def test_discover_peers_multimethod(self, connectivity):
        """Test multi-method peer discovery."""
        # Test with no discovery sources
        peers = await connectivity.discover_peers_multimethod()
        assert isinstance(peers, list)
        assert len(peers) == 0
        
        # Test with bootstrap peers
        bootstrap = [
            "/ip4/192.168.1.100/tcp/9000/p2p/QmTest1",
            "/ip4/10.0.0.50/tcp/9001/p2p/QmTest2"
        ]
        peers = await connectivity.discover_peers_multimethod(
            bootstrap_peers=bootstrap
        )
        
        assert len(peers) == 2
        assert all(p in bootstrap for p in peers)
    
    @pytest.mark.asyncio
    async def test_discover_peers_with_mock_registry(self, connectivity):
        """Test peer discovery with mock GitHub registry."""
        # Mock GitHub registry
        class MockRegistry:
            def discover_peers(self, max_peers=10):
                return [
                    {
                        "peer_id": "QmTest123",
                        "multiaddr": "/ip4/192.168.1.100/tcp/9000/p2p/QmTest123"
                    },
                    {
                        "peer_id": "QmTest456",
                        "multiaddr": "/ip4/10.0.0.50/tcp/9001/p2p/QmTest456"
                    }
                ]
        
        registry = MockRegistry()
        peers = await connectivity.discover_peers_multimethod(
            github_registry=registry
        )
        
        assert len(peers) >= 2
    
    @pytest.mark.asyncio
    async def test_attempt_connection(self, connectivity):
        """Test connection attempt with fallback."""
        class MockHost:
            pass
        
        host = MockHost()
        peer_addr = "/ip4/192.168.1.100/tcp/9000/p2p/QmTest"
        
        # Should return True (simulated connection in the method)
        result = await connectivity.attempt_connection(host, peer_addr)
        assert result is True
    
    def test_get_connectivity_status(self, connectivity):
        """Test connectivity status retrieval."""
        status = connectivity.get_connectivity_status()
        
        assert "discovered_peers" in status
        assert "relay_peers" in status
        assert "reachability" in status
        assert "transports" in status
        assert "discovery" in status
        assert "nat_traversal" in status
        
        assert status["transports"]["tcp"] is True
        assert status["discovery"]["mdns"] is True
        assert status["nat_traversal"]["autonat"] is True
    
    def test_connectivity_disabled_features(self):
        """Test with disabled connectivity features."""
        config = ConnectivityConfig(
            enable_mdns=False,
            enable_dht=False,
            enable_relay=False
        )
        connectivity = UniversalConnectivity(config)
        
        status = connectivity.get_connectivity_status()
        
        assert status["discovery"]["mdns"] is False
        assert status["discovery"]["dht"] is False
        assert status["discovery"]["relay"] is False


class TestGlobalConnectivity:
    """Test global connectivity instance management."""
    
    def test_get_global_connectivity(self):
        """Test getting global connectivity instance."""
        conn1 = get_universal_connectivity()
        conn2 = get_universal_connectivity()
        
        # Should return same instance
        assert conn1 is conn2
    
    def test_get_with_custom_config(self):
        """Test getting connectivity with custom config."""
        # Global instance is already created, so we can't change it
        # Just verify it exists and has a config
        conn = get_universal_connectivity()
        assert conn.config is not None
        assert isinstance(conn.config, ConnectivityConfig)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
