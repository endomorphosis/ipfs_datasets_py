Feature: print_banner function from scripts/monitor_p2p_cache.py
  This function prints monitoring banner

  Scenario: Banner contains P2P CACHE SYSTEM
    When print_banner() is called
    Then output contains "P2P CACHE SYSTEM"

  Scenario: Banner contains current timestamp
    When print_banner() is called
    Then output contains timestamp matching ISO format
