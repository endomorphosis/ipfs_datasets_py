Feature: test_multiaddr_support function from scripts/test_p2p_networking.py
  This function tests multiaddr support for bootstrap peers

  Scenario: Create multiaddr with peer ID
    Given multiaddr string "/ip4/127.0.0.1/tcp/4001/p2p/12D3KooWD3bfmNbuuuVCYwkjnFt3ukm3qaB8jy1G9kZfeLVT8jRz"
    When creating Multiaddr instance
    Then multiaddr object is created

  Scenario: Create simple multiaddr without peer ID
    Given multiaddr string "/ip4/192.168.1.1/tcp/4001"
    When creating Multiaddr instance
    Then simple multiaddr is created

  Scenario: Verify multiaddr support available
    Given multiaddr creation succeeds
    When test completes
    Then function returns true

  Scenario: Multiaddr creation fails
    Given multiaddr import fails
    When calling test_multiaddr_support
    Then function returns false
