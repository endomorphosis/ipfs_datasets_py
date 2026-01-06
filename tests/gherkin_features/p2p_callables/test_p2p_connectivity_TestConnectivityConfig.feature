Feature: TestConnectivityConfig class from tests/unit/test_p2p_connectivity.py
  This class tests ConnectivityConfig dataclass

  Scenario: test_default_config method
    Given no custom configuration
    When creating ConnectivityConfig with defaults
    Then enable_tcp is true

  Scenario: test_default_config method - assertion 2
    Given no custom configuration
    When creating ConnectivityConfig with defaults
    Then enable_mdns is true

  Scenario: test_default_config method - assertion 3
    Given no custom configuration
    When creating ConnectivityConfig with defaults
    Then enable_dht is true

  Scenario: test_default_config method - assertion 4
    Given no custom configuration
    When creating ConnectivityConfig with defaults
    Then enable_relay is true

  Scenario: test_default_config method - assertion 5
    Given no custom configuration
    When creating ConnectivityConfig with defaults
    Then enable_autonat is true

  Scenario: test_default_config method - assertion 6
    Given no custom configuration
    When creating ConnectivityConfig with defaults
    Then enable_hole_punching is true

  Scenario: test_custom_config method
    Given custom configuration parameters
    When creating ConnectivityConfig with enable_tcp true, enable_quic true, enable_mdns false, dht_bucket_size 50
    Then enable_tcp is true

  Scenario: test_custom_config method - assertion 2
    Given custom configuration parameters
    When creating ConnectivityConfig with enable_tcp true, enable_quic true, enable_mdns false, dht_bucket_size 50
    Then enable_quic is true

  Scenario: test_custom_config method - assertion 3
    Given custom configuration parameters
    When creating ConnectivityConfig with enable_tcp true, enable_quic true, enable_mdns false, dht_bucket_size 50
    Then enable_mdns is false

  Scenario: test_custom_config method - assertion 4
    Given custom configuration parameters
    When creating ConnectivityConfig with enable_tcp true, enable_quic true, enable_mdns false, dht_bucket_size 50
    Then dht_bucket_size equals 50
