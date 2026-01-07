"""
Test stubs for signal_handler

This feature file describes the signal_handler callable
from scripts/monitor_p2p_cache.py.
"""

import pytest
import sys
import signal
from scripts.monitor_p2p_cache import signal_handler


def test_sigint_signal_exits_with_code_0():
    """
    Scenario: SIGINT signal exits with code 0

    Given:
        monitor running

    When:
        SIGINT signal received

    Then:
        exit_code == 0
    """
    expected_exit_code = 0
    
    # signal_handler calls sys.exit(0), which will raise SystemExit
    with pytest.raises(SystemExit) as exc_info:
        signal_handler(signal.SIGINT, None)
    
    actual_exit_code = exc_info.value.code
    assert actual_exit_code == expected_exit_code, f"expected {expected_exit_code}, got {actual_exit_code}"


