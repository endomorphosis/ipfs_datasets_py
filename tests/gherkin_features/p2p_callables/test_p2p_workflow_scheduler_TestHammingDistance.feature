Feature: TestHammingDistance class from tests/test_p2p_workflow_scheduler.py
  This class tests hamming distance calculation

  Scenario: test_hamming_distance_identical method
    Given hash1 "abcd1234"
    And hash2 "abcd1234"
    When calculating hamming distance
    Then distance equals 0

  Scenario: test_hamming_distance_different method
    Given hash1 "0000"
    And hash2 "ffff"
    When calculating hamming distance
    Then distance is greater than 0

  Scenario: test_hamming_distance_one_bit method
    Given hash1 "0"
    And hash2 "1"
    When calculating hamming distance
    Then distance equals 1
