"""Formula regex compilation is reusable; parser results remain uncached."""

import re

from ipfs_datasets_py.logic.deontic.formula_builder import _compiled_normalization_pattern
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements


def test_repeated_parse_survives_shared_regex_cache_eviction():
    _compiled_normalization_pattern.cache_clear()
    text = "The agency shall submit the report within 10 days unless emergency."
    first = extract_normative_elements(text)
    compiled = _compiled_normalization_pattern.cache_info()
    assert compiled.misses > 512  # More than the shared regex cache can hold.
    re.purge()
    second = extract_normative_elements(text)
    repeated = _compiled_normalization_pattern.cache_info()
    assert second == first
    assert repeated.misses == compiled.misses
    assert repeated.hits > compiled.hits
    # Returning independent parser structures is part of the existing contract.
    second[0]["subject"].append("mutated")
    assert "mutated" not in first[0]["subject"]
    changed = extract_normative_elements("The agency shall not disclose records.")
    assert changed[0]["deontic_operator"] == "F"
    assert changed[0]["action"] != first[0]["action"]


def test_pattern_cache_remains_bounded_under_distinct_patterns():
    _compiled_normalization_pattern.cache_clear()
    for index in range(4096):
        _compiled_normalization_pattern(f"^pattern_{index}$")
    assert _compiled_normalization_pattern.cache_info().currsize <= 2048
    _compiled_normalization_pattern.cache_clear()
