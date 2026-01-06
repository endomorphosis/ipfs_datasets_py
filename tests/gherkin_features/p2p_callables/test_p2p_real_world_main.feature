Feature: main function from scripts/test_p2p_real_world.py
  This function is main entry point

  Scenario: Import required modules
    When importing libp2p.peer.peerinfo.info_from_p2p_addr
    Then import succeeds

  Scenario: Run async tests with asyncio.run
    Given run_all_tests async function
    When calling asyncio.run
    Then async tests execute
    And exit code is returned

  Scenario: Test suite fails to start
    Given import or setup fails
    When calling main
    Then exit code is 1
    And error message displays
