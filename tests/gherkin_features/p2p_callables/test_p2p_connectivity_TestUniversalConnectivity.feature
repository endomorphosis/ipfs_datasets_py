Feature: TestUniversalConnectivity class from tests/unit/test_p2p_connectivity.py
  This class tests UniversalConnectivity class

  Scenario: test_initialize_connectivity method
    Given ConnectivityConfig instance
    When creating UniversalConnectivity
    Then config is not None
    And discovered_peers is a set
    And relay_peers is a list

  Scenario: test_configure_transports method
    Given UniversalConnectivity instance
    And MockHost object
    When calling configure_transports
    Then no exception is raised

  Scenario: test_start_mdns_discovery method
    Given UniversalConnectivity instance
    And MockHost object
    When calling start_mdns_discovery
    Then no exception is raised

  Scenario: test_configure_dht method
    Given UniversalConnectivity instance
    And MockHost object
    When calling configure_dht
    Then no exception is raised

  Scenario: test_setup_circuit_relay method
    Given UniversalConnectivity instance
    And MockHost object
    And relay addresses list with 2 items
    When calling setup_circuit_relay
    Then relay_peers length equals 2
    And relay_peers equals relay addresses

  Scenario: test_enable_autonat method
    Given UniversalConnectivity instance
    And MockHost object
    When calling enable_autonat
    Then no exception is raised

  Scenario: test_enable_hole_punching method
    Given UniversalConnectivity instance
    And MockHost object
    When calling enable_hole_punching
    Then no exception is raised

  Scenario: test_discover_peers_multimethod method with no sources
    Given UniversalConnectivity instance
    When calling discover_peers_multimethod
    Then peers list is returned
    And peers length equals 0

  Scenario: test_discover_peers_multimethod method with bootstrap peers
    Given UniversalConnectivity instance
    And bootstrap list with 2 addresses
    When calling discover_peers_multimethod with bootstrap_peers
    Then peers length equals 2
    And all peers are in bootstrap list

  Scenario: test_discover_peers_with_mock_registry method
    Given UniversalConnectivity instance
    And MockRegistry with 2 peers
    When calling discover_peers_multimethod with github_registry
    Then peers length is at least 2

  Scenario: test_attempt_connection method
    Given UniversalConnectivity instance
    And MockHost object
    And peer address string
    When calling attempt_connection
    Then result is true

  Scenario: test_get_connectivity_status method
    Given UniversalConnectivity instance
    When calling get_connectivity_status
    Then status contains discovered_peers
    And status contains relay_peers
    And status contains reachability
    And status contains transports
    And status contains discovery
    And status contains nat_traversal
    And status transports tcp is true
    And status discovery mdns is true
    And status nat_traversal autonat is true

  Scenario: test_connectivity_disabled_features method
    Given ConnectivityConfig with enable_mdns false, enable_dht false, enable_relay false
    When creating UniversalConnectivity
    And calling get_connectivity_status
    Then status discovery mdns is false
    And status discovery dht is false
    And status discovery relay is false
