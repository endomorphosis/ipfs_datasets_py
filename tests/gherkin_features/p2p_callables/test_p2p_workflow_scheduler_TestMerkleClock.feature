Feature: TestMerkleClock class from tests/test_p2p_workflow_scheduler.py
  This class tests Merkle Clock implementation

  Scenario: test_clock_initialization method
    Given peer ID "peer1"
    When creating MerkleClock
    Then peer_id equals "peer1"

  Scenario: test_clock_initialization method - assertion 2
    Given peer ID "peer1"
    When creating MerkleClock
    Then counter equals 0

  Scenario: test_clock_initialization method - assertion 3
    Given peer ID "peer1"
    When creating MerkleClock
    Then parent_hash is None

  Scenario: test_clock_tick method
    Given initialized MerkleClock with peer "peer1"
    And initial hash computed
    When calling tick
    Then counter equals 1

  Scenario: test_clock_tick method - assertion 2
    Given initialized MerkleClock with peer "peer1"
    And initial hash computed
    When calling tick
    Then parent_hash equals initial hash

  Scenario: test_clock_hash_deterministic method
    Given two clocks with peer "peer1", counter 5, parent_hash "abc123", timestamp 1000.0
    When computing hashes
    Then clock1 hash equals clock2 hash

  Scenario: test_clock_hash_different_state method
    Given clock1 with peer "peer1" counter 5
    And clock2 with peer "peer1" counter 6
    When computing hashes
    Then clock1 hash not equals clock2 hash

  Scenario: test_clock_merge method
    Given clock1 with peer "peer1" counter 3
    And clock2 with peer "peer2" counter 5
    When merging clock2 into clock1
    Then merged counter equals 6

  Scenario: test_clock_merge method - assertion 2
    Given clock1 with peer "peer1" counter 3
    And clock2 with peer "peer2" counter 5
    When merging clock2 into clock1
    Then merged peer_id equals "peer1"

  Scenario: test_clock_to_dict method
    Given MerkleClock with peer "peer1", counter 5, parent_hash "abc123"
    When converting to dictionary
    Then dict peer_id equals "peer1"

  Scenario: test_clock_to_dict method - assertion 2
    Given MerkleClock with peer "peer1", counter 5, parent_hash "abc123"
    When converting to dictionary
    Then dict counter equals 5

  Scenario: test_clock_to_dict method - assertion 3
    Given MerkleClock with peer "peer1", counter 5, parent_hash "abc123"
    When converting to dictionary
    Then dict parent_hash equals "abc123"

  Scenario: test_clock_to_dict method - assertion 4
    Given MerkleClock with peer "peer1", counter 5, parent_hash "abc123"
    When converting to dictionary
    Then dict contains hash

  Scenario: test_clock_to_dict method - assertion 5
    Given MerkleClock with peer "peer1", counter 5, parent_hash "abc123"
    When converting to dictionary
    Then dict contains timestamp

  Scenario: test_clock_from_dict method
    Given clock dictionary with peer_id "peer1", counter 5, parent_hash "abc123", timestamp 1000.0
    When creating clock from dictionary
    Then clock peer_id equals "peer1"

  Scenario: test_clock_from_dict method - assertion 2
    Given clock dictionary with peer_id "peer1", counter 5, parent_hash "abc123", timestamp 1000.0
    When creating clock from dictionary
    Then clock counter equals 5

  Scenario: test_clock_from_dict method - assertion 3
    Given clock dictionary with peer_id "peer1", counter 5, parent_hash "abc123", timestamp 1000.0
    When creating clock from dictionary
    Then clock parent_hash equals "abc123"
