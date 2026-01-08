"""
Test stubs for print_banner

This feature file describes the print_banner callable
from scripts/monitor_p2p_cache.py.
"""

import pytest
import sys
from io import StringIO
from scripts.monitor_p2p_cache import print_banner
import re


def test_banner_contains_p2p_cache_system(capsys):
    """
    Scenario: Banner contains P2P CACHE SYSTEM

    Given:

    When:
        print_banner() is called

    Then:
        output contains "P2P CACHE SYSTEM"
    """
    expected_contains = True
    search_string = "P2P CACHE SYSTEM"
    
    print_banner()
    
    captured = capsys.readouterr()
    actual_contains = search_string in captured.out
    assert actual_contains == expected_contains, f"expected {expected_contains}, got {actual_contains}"


def test_banner_contains_current_timestamp(capsys):
    """
    Scenario: Banner contains current timestamp

    Given:

    When:
        print_banner() is called

    Then:
        output contains timestamp matching ISO format
    """
    expected_contains = True
    # ISO format timestamp pattern: YYYY-MM-DD HH:MM:SS
    timestamp_pattern = r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
    
    print_banner()
    
    captured = capsys.readouterr()
    actual_contains = re.search(timestamp_pattern, captured.out) is not None
    assert actual_contains == expected_contains, f"expected {expected_contains}, got {actual_contains}"


