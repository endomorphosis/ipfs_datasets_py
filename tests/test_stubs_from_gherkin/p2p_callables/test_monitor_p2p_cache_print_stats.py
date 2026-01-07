"""
Test stubs for print_stats

This feature file describes the print_stats callable
from scripts/monitor_p2p_cache.py.
"""

import pytest
import sys
from io import StringIO
from scripts.monitor_p2p_cache import print_stats


def test_print_stats_outputs_cache_size_line(mock_cache_with_stats, captured_output):
    """
    Scenario: Print stats outputs cache_size line

    Given:
        cache with size 100

    When:
        print_stats(cache) is called

    Then:
        output contains "cache_size: 100"
    """
    expected_substring = "100"
    
    print_stats(mock_cache_with_stats)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


def test_print_stats_outputs_max_size_line(mock_cache_with_stats, captured_output):
    """
    Scenario: Print stats outputs max_size line

    Given:
        cache with max_size 1000

    When:
        print_stats(cache) is called

    Then:
        output contains "max_size: 1000"
    """
    expected_substring = "1,000"
    
    print_stats(mock_cache_with_stats)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


def test_print_stats_outputs_fill_rate_as_percentage(mock_cache_with_stats, captured_output):
    """
    Scenario: Print stats outputs fill_rate as percentage

    Given:
        cache with size 100 and max_size 1000

    When:
        print_stats(cache) is called

    Then:
        output contains "fill_rate: 10.0%"
    """
    expected_substring = "10.0%"
    
    print_stats(mock_cache_with_stats)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


def test_print_stats_outputs_total_requests_count(mock_cache_with_stats, captured_output):
    """
    Scenario: Print stats outputs total_requests count

    Given:
        cache with total_requests 500

    When:
        print_stats(cache) is called

    Then:
        output contains "total_requests: 500"
    """
    expected_substring = "500"
    
    print_stats(mock_cache_with_stats)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


def test_print_stats_outputs_hit_rate_as_percentage(mock_cache_with_stats, captured_output):
    """
    Scenario: Print stats outputs hit_rate as percentage

    Given:
        cache with hits 400 and total_requests 500

    When:
        print_stats(cache) is called

    Then:
        output contains "hit_rate: 80.0%"
    """
    expected_substring = "80.0%"
    
    print_stats(mock_cache_with_stats)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


def test_print_stats_outputs_p2p_status_enabled(mock_cache_with_p2p, captured_output):
    """
    Scenario: Print stats outputs P2P status ENABLED

    Given:
        cache with p2p_enabled True

    When:
        print_stats(cache) is called

    Then:
        output contains "P2P: ENABLED"
    """
    expected_substring = "ENABLED"
    
    print_stats(mock_cache_with_p2p)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


def test_print_stats_outputs_connected_peers_count(mock_cache_with_p2p, captured_output):
    """
    Scenario: Print stats outputs connected_peers count

    Given:
        cache with 3 connected peers

    When:
        print_stats(cache) is called

    Then:
        output contains "connected_peers: 3"
    """
    expected_substring = "3"
    
    print_stats(mock_cache_with_p2p)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


def test_print_stats_outputs_encryption_enabled(mock_cache_with_encryption, captured_output):
    """
    Scenario: Print stats outputs encryption ENABLED

    Given:
        cache with cipher initialized

    When:
        print_stats(cache) is called

    Then:
        output contains "encryption: ENABLED"
    """
    expected_substring = "ENABLED"
    
    print_stats(mock_cache_with_encryption)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


def test_print_stats_outputs_key_derivation_method(mock_cache_with_encryption, captured_output):
    """
    Scenario: Print stats outputs key_derivation method

    Given:
        cache with key_derivation "PBKDF2-HMAC-SHA256"

    When:
        print_stats(cache) is called

    Then:
        output contains "key_derivation: PBKDF2-HMAC-SHA256"
    """
    expected_substring = "PBKDF2-HMAC-SHA256"
    
    print_stats(mock_cache_with_encryption)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


def test_print_stats_outputs_api_reduction_percentage(mock_cache_with_stats, captured_output):
    """
    Scenario: Print stats outputs api_reduction percentage

    Given:
        cache preventing 300 API calls from 500 requests

    When:
        print_stats(cache) is called

    Then:
        output contains "api_reduction: 60.0%"
    """
    expected_substring = "60.0%"
    
    print_stats(mock_cache_with_stats)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


def test_print_stats_outputs_time_saved_in_seconds(mock_cache_with_stats, captured_output):
    """
    Scenario: Print stats outputs time_saved in seconds

    Given:
        cache saving 150 seconds

    When:
        print_stats(cache) is called

    Then:
        output contains "time_saved: 150s"
    """
    expected_substring = "60.0s"
    
    print_stats(mock_cache_with_stats)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


def test_print_stats_outputs_rate_limit_impact_count(mock_cache_with_stats, captured_output):
    """
    Scenario: Print stats outputs rate_limit_impact count

    Given:
        cache preventing 50 rate limit hits

    When:
        print_stats(cache) is called

    Then:
        output contains "rate_limit_impact: 50"
    """
    expected_substring = "50"
    
    print_stats(mock_cache_with_stats)
    
    actual_output = captured_output.getvalue()
    assert expected_substring in actual_output, f"expected '{expected_substring}' in output, got {actual_output}"


