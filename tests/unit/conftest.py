"""
Pytest configuration for tests/unit directory.

Excludes template/stub directories from test collection.
"""
import pytest

# Ignore the test stubs and gherkin features directories during collection
collect_ignore_glob = [
    "test_stubs_from_gherkin/**",
    "gherkin_features/**",
]
