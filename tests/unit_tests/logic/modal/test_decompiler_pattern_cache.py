"""Compiled-pattern reuse preserves each scan and its native regex semantics."""
import re

import pytest

from ipfs_datasets_py.logic.modal import decompiler


@pytest.fixture(autouse=True)
def isolated_pattern_cache():
    decompiler._compiled_decompiler_pattern.cache_clear()
    yield
    decompiler._compiled_decompiler_pattern.cache_clear()


def match_signature(match):
    if match is None:
        return None
    return (match.group(), match.groups(), match.groupdict(), match.span(),
            match.re.pattern, match.re.flags, match.string)


@pytest.mark.parametrize("pattern,text,flags", [
    (r"\bshall\b", "Shall\nmay", re.IGNORECASE),
    (r"^two$", "one\ntwo\nthree", re.MULTILINE),
    (r"a.b", "a\nb", re.DOTALL),
    (r"\w+", "café", re.ASCII),
    (r"a \s+ b", "a b", re.VERBOSE),
    ("é", "É", re.IGNORECASE),
    (r"(?P<word>\w+)", "first second", 0),
    (r"(?<=a)b", "ab", 0),
    (r"a", "A", re.IGNORECASE | re.MULTILINE),
])
def test_search_matches_native_flags_groups_spans_and_objects(pattern, text, flags):
    expected = re.search(pattern, text, flags)
    actual = decompiler._decompiler_search(pattern, text, flags)
    assert type(actual) is type(expected)
    assert match_signature(actual) == match_signature(expected)
    assert match_signature(decompiler._decompiler_search(pattern, text, flags)) == match_signature(expected)
    assert decompiler._compiled_decompiler_pattern.cache_info().hits == 1


def test_cache_key_keeps_flags_distinct_and_never_caches_text_or_matches():
    assert decompiler._decompiler_search("a", "A") is None
    assert decompiler._decompiler_search("a", "A", re.IGNORECASE).group() == "A"
    first = decompiler._decompiler_search("a", "a")
    second = decompiler._decompiler_search("a", "a")
    assert first is not second and first.re is second.re
    assert decompiler._decompiler_search("a", "b") is None
    assert decompiler._compiled_decompiler_pattern.cache_info().currsize == 2


def test_compiled_objects_and_bytes_keep_native_behavior_without_local_retention():
    pattern = re.compile("a", re.IGNORECASE)
    assert decompiler._decompiler_search(pattern, "A").re is pattern
    assert match_signature(decompiler._decompiler_search(b"a", b"a")) == match_signature(re.search(b"a", b"a"))
    assert decompiler._compiled_decompiler_pattern.cache_info().currsize == 0


@pytest.mark.parametrize("pattern,text,flags", [
    ("[", "x", 0),
    (r"(?P<bad>.)\2", "x", 0),
    (re.compile("x"), "x", re.IGNORECASE),
    ([], "x", 0),
    (object(), "x", 0),
    ("x", "x", None),
    ("x", "x", 0.5),
    ("x", b"x", 0),
    (b"x", "x", 0),
    ("x", "x", re.LOCALE),
])
def test_errors_match_native_types_messages_and_pattern_positions(pattern, text, flags):
    with pytest.raises(Exception) as expected:
        re.search(pattern, text, flags)
    with pytest.raises(type(expected.value)) as actual:
        decompiler._decompiler_search(pattern, text, flags)
    assert str(actual.value) == str(expected.value)
    assert getattr(actual.value, "pos", None) == getattr(expected.value, "pos", None)


def test_debug_recompiles_and_prints_on_every_call(capsys):
    re.search("debug", "debug", re.DEBUG)
    expected = capsys.readouterr().out
    assert expected
    for _ in range(2):
        decompiler._decompiler_search("debug", "debug", re.DEBUG)
        assert capsys.readouterr().out == expected
    assert decompiler._compiled_decompiler_pattern.cache_info().currsize == 0


def test_compiled_pattern_cache_has_a_hard_lru_bound():
    for index in range(2065):
        decompiler._decompiler_search(f"bounded_{index:04d}", "")
    info = decompiler._compiled_decompiler_pattern.cache_info()
    assert info.maxsize == info.currsize == 2048
    decompiler._decompiler_search("bounded_0000", "")
    assert decompiler._compiled_decompiler_pattern.cache_info().misses == info.misses + 1
    assert decompiler._compiled_decompiler_pattern.cache_info().currsize == 2048


TEXTS = (
    "The agency shall retain records for five years unless otherwise provided by law.",
    "No person may knowingly mail obscene matter or nonmailable lottery advertisements.",
    "The Secretary may appoint commissioners to investigate Indian affairs and enter agreements.",
    "The corporation shall adopt bylaws; members have voting rights at meetings of the members.",
    "The Secretary shall report annually to Congress not later than January 1 of each fiscal year.",
    "Section 901 was repealed by Public Law 91-513. Editorial Notes: Codification.",
    "The compact of free association and the National Security Act of 1947 apply.",
    "Café records must_not be withheld, except as otherwise provided in this subsection.",
    "Nothing in this section shall affect existing rights; this provision applies after enactment.",
    "", "  ",
)


@pytest.mark.parametrize("text", TEXTS)
def test_complete_helper_outputs_match_uncached_original_search(text, monkeypatch):
    actual = (decompiler._legal_semantic_atoms_from_text(text), decompiler._bridge_cues_from_text(text))
    with monkeypatch.context() as patch:
        patch.setattr(decompiler, "_decompiler_search", re.search)
        expected = (decompiler._legal_semantic_atoms_from_text(text), decompiler._bridge_cues_from_text(text))
    assert actual == expected
    for values in actual:
        values.clear()
    assert (decompiler._legal_semantic_atoms_from_text(text), decompiler._bridge_cues_from_text(text)) == expected


def test_warm_rule_scans_survive_process_regex_cache_churn():
    text = TEXTS[0]
    expected = (decompiler._legal_semantic_atoms_from_text(text), decompiler._bridge_cues_from_text(text))
    before = decompiler._compiled_decompiler_pattern.cache_info()
    assert before.currsize > 100
    # Other parsers sharing re can evict these rules; the local cache retains
    # only their compiled objects while every actual search still runs.
    for index in range(1200):
        re.compile(f"unrelated_parser_pattern_{index:04d}")
    assert (decompiler._legal_semantic_atoms_from_text(text), decompiler._bridge_cues_from_text(text)) == expected
    after = decompiler._compiled_decompiler_pattern.cache_info()
    assert after.misses == before.misses
    assert after.hits > before.hits
