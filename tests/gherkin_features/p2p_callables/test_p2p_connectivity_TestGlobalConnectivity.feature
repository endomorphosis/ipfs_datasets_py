Feature: TestGlobalConnectivity class from tests/unit/test_p2p_connectivity.py
  This class tests global connectivity instance management

  Scenario: test_get_global_connectivity method
    When calling get_universal_connectivity twice
    Then conn1 equals conn2
    And same instance is returned

  Scenario: test_get_with_custom_config method
    When calling get_universal_connectivity
    Then conn config is not None
    And conn config is ConnectivityConfig instance
