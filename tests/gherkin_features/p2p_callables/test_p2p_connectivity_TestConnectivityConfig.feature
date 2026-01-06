Feature: TestConnectivityConfig class from tests/unit/test_p2p_connectivity.py
  This class tests ConnectivityConfig dataclass

  Scenario: test_default_config method
    Given no custom configuration
    When creating ConnectivityConfig with defaults
    Then enable_tcp is true
    And enable_mdns is true
    And enable_dht is true
    And enable_relay is true
    And enable_autonat is true
    And enable_hole_punching is true

  Scenario: test_custom_config method
    Given custom configuration parameters
    When creating ConnectivityConfig with enable_tcp true, enable_quic true, enable_mdns false, dht_bucket_size 50
    Then enable_tcp is true
    And enable_quic is true
    And enable_mdns is false
    And dht_bucket_size equals 50
