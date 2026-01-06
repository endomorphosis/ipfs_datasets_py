Feature: test_p2p_cache_operations function from test_p2p_async.py
  This async function tests cache operations with P2P

  Scenario: Check libp2p availability
    When importing libp2p
    Then libp2p is available or skipped

  Scenario: Create two cache instances
    Given temp directory
    When creating cache1 on port 19001
    And creating cache2 on port 19002
    Then both caches are created

  Scenario: Connect cache2 to cache1
    Given cache1 as bootstrap peer
    When cache2 connects with bootstrap_peers
    Then wait 2 seconds for connection

  Scenario: Test put operation on cache1
    Given cache1 instance
    When putting data with key "test_operation"
    Then data is stored

  Scenario: Test get operation on cache1
    Given data in cache1
    When getting data from cache1
    Then data matches original

  Scenario: Wait for P2P gossip
    Given data in cache1
    When waiting 1 second
    Then P2P has time to propagate

  Scenario: Check both cache statistics
    Given both caches active
    When getting stats from cache1
    And getting stats from cache2
    Then stats show p2p_enabled
    And stats show connected_peers

  Scenario: Both caches have P2P enabled
    Given cache1 with p2p_enabled
    And cache2 with p2p_enabled
    When checking both
    Then function returns true

  Scenario: P2P not fully enabled
    Given at least one cache without P2P
    When checking status
    Then function returns true with warning

  Scenario: Libp2p not installed
    Given libp2p not available
    When calling test_p2p_cache_operations
    Then function returns true with skip message
