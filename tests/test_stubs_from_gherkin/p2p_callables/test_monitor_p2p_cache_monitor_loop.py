"""
Test stubs for monitor_loop

This feature file describes the monitor_loop callable
from scripts/monitor_p2p_cache.py.
"""

import pytest
from unittest.mock import Mock, patch, call
# from scripts.monitor_p2p_cache import monitor_loop


def test_monitor_loop_calls_print_banner_once():
    """
    Scenario: Monitor loop calls print_banner once

    Given:
        interval 10

    When:
        monitor_loop(interval=10) is called

    Then:
        print_banner() called 1 time
    """
    expected_call_count = 1
    interval_value = 10
    
    with patch('scripts.monitor_p2p_cache.print_banner') as mock_banner:
        with patch('scripts.monitor_p2p_cache.GitHubAPICache'):
            with patch('scripts.monitor_p2p_cache.print_stats'):
                with patch('scripts.monitor_p2p_cache.time.sleep', side_effect=KeyboardInterrupt):
                    with patch('builtins.print'):
                        from scripts.monitor_p2p_cache import monitor_loop
                        try:
                            monitor_loop(interval_value)
                        except KeyboardInterrupt:
                            pass
                        
                        actual_call_count = mock_banner.call_count
                        assert actual_call_count == expected_call_count, f"expected {expected_call_count}, got {actual_call_count}"


def test_monitor_loop_creates_cache_instance():
    """
    Scenario: Monitor loop creates cache instance

    Given:
        interval 10

    When:
        monitor_loop(interval=10) is called

    Then:
        GitHubAPICache() is instantiated
    """
    expected_call_count = 1
    interval_value = 10
    
    with patch('scripts.monitor_p2p_cache.print_banner'):
        with patch('scripts.monitor_p2p_cache.GitHubAPICache') as mock_cache:
            with patch('scripts.monitor_p2p_cache.print_stats'):
                with patch('scripts.monitor_p2p_cache.time.sleep', side_effect=KeyboardInterrupt):
                    with patch('builtins.print'):
                        from scripts.monitor_p2p_cache import monitor_loop
                        try:
                            monitor_loop(interval_value)
                        except KeyboardInterrupt:
                            pass
                        
                        actual_call_count = mock_cache.call_count
                        assert actual_call_count == expected_call_count, f"expected {expected_call_count}, got {actual_call_count}"


def test_monitor_loop_outputs_monitoring_interval(captured_output):
    """
    Scenario: Monitor loop outputs monitoring interval

    Given:
        interval 10

    When:
        monitor_loop(interval=10) is called

    Then:
        output contains "interval: 10"
    """
    expected_substring = "interval: 10"
    interval_value = 10
    
    with patch('scripts.monitor_p2p_cache.print_banner'):
        with patch('scripts.monitor_p2p_cache.GitHubAPICache'):
            with patch('scripts.monitor_p2p_cache.print_stats'):
                with patch('scripts.monitor_p2p_cache.time.sleep', side_effect=KeyboardInterrupt):
                    from scripts.monitor_p2p_cache import monitor_loop
                    try:
                        monitor_loop(interval_value)
                    except KeyboardInterrupt:
                        pass
                    
                    actual_output = captured_output.getvalue()
                    assert expected_substring in actual_output, f"expected {expected_substring}, got {actual_output}"


def test_monitor_loop_calls_print_stats_each_iteration():
    """
    Scenario: Monitor loop calls print_stats each iteration

    Given:
        interval 10
        3 iterations

    When:
        monitor_loop(interval=10) runs 3 iterations

    Then:
        print_stats() called 3 times
    """
    expected_call_count = 3
    interval_value = 10
    iteration_count = 3
    
    with patch('scripts.monitor_p2p_cache.print_banner'):
        with patch('scripts.monitor_p2p_cache.GitHubAPICache'):
            with patch('scripts.monitor_p2p_cache.print_stats') as mock_stats:
                sleep_counter = [0]
                def sleep_side_effect(seconds):
                    sleep_counter[0] += 1
                    if sleep_counter[0] >= iteration_count:
                        raise KeyboardInterrupt
                
                with patch('scripts.monitor_p2p_cache.time.sleep', side_effect=sleep_side_effect):
                    with patch('builtins.print'):
                        from scripts.monitor_p2p_cache import monitor_loop
                        try:
                            monitor_loop(interval_value)
                        except KeyboardInterrupt:
                            pass
                        
                        actual_call_count = mock_stats.call_count
                        assert actual_call_count == expected_call_count, f"expected {expected_call_count}, got {actual_call_count}"


def test_monitor_loop_sleeps_for_interval_seconds():
    """
    Scenario: Monitor loop sleeps for interval seconds

    Given:
        interval 10

    When:
        monitor_loop(interval=10) completes iteration

    Then:
        time.sleep(10) is called
    """
    expected_sleep_seconds = 10
    interval_value = 10
    
    with patch('scripts.monitor_p2p_cache.print_banner'):
        with patch('scripts.monitor_p2p_cache.GitHubAPICache'):
            with patch('scripts.monitor_p2p_cache.print_stats'):
                with patch('scripts.monitor_p2p_cache.time.sleep', side_effect=KeyboardInterrupt) as mock_sleep:
                    with patch('builtins.print'):
                        from scripts.monitor_p2p_cache import monitor_loop
                        try:
                            monitor_loop(interval_value)
                        except KeyboardInterrupt:
                            pass
                        
                        actual_sleep_seconds = mock_sleep.call_args[0][0]
                        assert actual_sleep_seconds == expected_sleep_seconds, f"expected {expected_sleep_seconds}, got {actual_sleep_seconds}"


def test_monitor_loop_outputs_update_header_each_iteration(captured_output):
    """
    Scenario: Monitor loop outputs update header each iteration

    Given:
        interval 10
        2 iterations

    When:
        monitor_loop(interval=10) runs 2 iterations

    Then:
        output contains "UPDATE" 2 times
    """
    expected_update_count = 2
    interval_value = 10
    iteration_count = 2
    
    with patch('scripts.monitor_p2p_cache.print_banner'):
        with patch('scripts.monitor_p2p_cache.GitHubAPICache'):
            with patch('scripts.monitor_p2p_cache.print_stats'):
                sleep_counter = [0]
                def sleep_side_effect(seconds):
                    sleep_counter[0] += 1
                    if sleep_counter[0] >= iteration_count:
                        raise KeyboardInterrupt
                
                with patch('scripts.monitor_p2p_cache.time.sleep', side_effect=sleep_side_effect):
                    from scripts.monitor_p2p_cache import monitor_loop
                    try:
                        monitor_loop(interval_value)
                    except KeyboardInterrupt:
                        pass
                    
                    actual_update_count = captured_output.getvalue().count("UPDATE")
                    assert actual_update_count == expected_update_count, f"expected {expected_update_count}, got {actual_update_count}"


def test_monitor_loop_outputs_tip_on_first_iteration(captured_output):
    """
    Scenario: Monitor loop outputs tip on first iteration

    Given:
        interval 10

    When:
        monitor_loop(interval=10) runs first iteration

    Then:
        output contains "Tip:"
    """
    expected_substring = "Tip:"
    interval_value = 10
    
    with patch('scripts.monitor_p2p_cache.print_banner'):
        with patch('scripts.monitor_p2p_cache.GitHubAPICache'):
            with patch('scripts.monitor_p2p_cache.print_stats'):
                with patch('scripts.monitor_p2p_cache.time.sleep', side_effect=KeyboardInterrupt):
                    from scripts.monitor_p2p_cache import monitor_loop
                    try:
                        monitor_loop(interval_value)
                    except KeyboardInterrupt:
                        pass
                    
                    actual_output = captured_output.getvalue()
                    assert expected_substring in actual_output, f"expected {expected_substring}, got {actual_output}"


def test_keyboardinterrupt_stops_monitor_loop():
    """
    Scenario: KeyboardInterrupt stops monitor loop

    Given:
        interval 10

    When:
        KeyboardInterrupt raised

    Then:
        monitor_loop exits
    """
    expected_exception_handled = True
    interval_value = 10
    
    with patch('scripts.monitor_p2p_cache.print_banner'):
        with patch('scripts.monitor_p2p_cache.GitHubAPICache'):
            with patch('scripts.monitor_p2p_cache.print_stats'):
                with patch('scripts.monitor_p2p_cache.time.sleep', side_effect=KeyboardInterrupt):
                    with patch('builtins.print'):
                        from scripts.monitor_p2p_cache import monitor_loop
                        exception_handled = False
                        try:
                            monitor_loop(interval_value)
                            exception_handled = False
                        except KeyboardInterrupt:
                            exception_handled = True
                        
                        actual_exception_handled = exception_handled
                        assert actual_exception_handled == expected_exception_handled, f"expected {expected_exception_handled}, got {actual_exception_handled}"

