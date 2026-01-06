Feature: TestGetScheduler class from tests/test_p2p_workflow_scheduler.py
  This class tests global scheduler instance

  Scenario: test_get_scheduler_creates_instance method
    Given global scheduler instance is None
    When calling get_scheduler with peer_id "test_peer"
    Then scheduler is not None
    And scheduler peer_id equals "test_peer"

  Scenario: test_get_scheduler_reuses_instance method
    Given global scheduler instance is None
    When calling get_scheduler with "test_peer"
    And calling get_scheduler with "different_peer"
    Then scheduler1 equals scheduler2
    And scheduler2 peer_id equals "test_peer"
