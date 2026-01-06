Feature: print_banner function from scripts/monitor_p2p_cache.py
  This function prints monitoring banner

  Scenario: Display monitor banner
    When calling print_banner
    Then P2P CACHE SYSTEM banner displays
    And current time displays
