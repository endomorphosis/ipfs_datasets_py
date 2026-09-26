"""Compatibility gates for native tuple prefix dispatch; no timing assertions."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import frame_bm25_selector as selector


# Exact pre-change functions from selector SHA 612d472efaf9cb5bb2f57914125d9fc87cde3a55f14dc5a105cc80f268df430a.
# This local oracle preserves private override/error behavior as well as native results.
_LEGACY_SOURCE = r'''
def _is_contextual_frame_ontology_predicate(predicate: str) -> bool:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    return normalized in _FRAME_ONTOLOGY_CONTEXTUAL_FLOGIC_PREDICATES or any(
        normalized.startswith(prefix)
        for prefix in _FRAME_ONTOLOGY_CONTEXTUAL_FLOGIC_PREDICATE_PREFIXES
    )

def _is_slot_frame_ontology_predicate(predicate: str) -> bool:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if not normalized:
        return False
    return any(
        normalized.startswith(prefix) for prefix in _FRAME_ONTOLOGY_SLOT_FRAME_PREDICATE_PREFIXES
    )

def _predicate_allows_numeric_ontology_tokens(predicate: str) -> bool:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if not normalized:
        return False
    canonical = _FRAME_ONTOLOGY_PREDICATE_ALIASES.get(normalized, normalized)
    if canonical.endswith("_count"):
        return any(
            canonical.endswith(suffix)
            for suffix in _FRAME_ONTOLOGY_NUMERIC_COUNT_PREDICATE_SUFFIXES
        )
    if canonical in _FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATES:
        return True
    return any(
        canonical.startswith(prefix) for prefix in _FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATE_PREFIXES
    )

def _predicate_allows_single_character_alpha_tokens(predicate: str) -> bool:
    normalized = _FRAME_ONTOLOGY_PREDICATE_TOKEN_RE.sub(
        "_",
        str(predicate or "").strip().lower(),
    ).strip("_")
    if not normalized or normalized.endswith("_count"):
        return False
    canonical = _FRAME_ONTOLOGY_PREDICATE_ALIASES.get(normalized, normalized)
    if canonical in _FRAME_ONTOLOGY_SINGLE_CHAR_ALPHA_VALUE_PREDICATES:
        return True
    if canonical in _FRAME_ONTOLOGY_SINGLE_CHAR_ALPHA_PREDICATES:
        return True
    if canonical.endswith("_modal_operator"):
        return True
    if not any(
        canonical.startswith(prefix) for prefix in _FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATE_PREFIXES
    ):
        return False
    return "_suffix" in canonical
'''

_LEGACY_CODE = compile(_LEGACY_SOURCE, "<legacy-prefix-dispatch>", "exec")
_CASES = (
    ("_is_contextual_frame_ontology_predicate", "_FRAME_ONTOLOGY_CONTEXTUAL_FLOGIC_PREDICATE_PREFIXES"),
    ("_is_slot_frame_ontology_predicate", "_FRAME_ONTOLOGY_SLOT_FRAME_PREDICATE_PREFIXES"),
    ("_predicate_allows_numeric_ontology_tokens", "_FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATE_PREFIXES"),
    ("_predicate_allows_single_character_alpha_tokens", "_FRAME_ONTOLOGY_NUMERIC_VALUE_PREDICATE_PREFIXES"),
)


def _legacy_functions():
    namespace = vars(selector).copy()
    exec(_LEGACY_CODE, namespace)
    return namespace


def _outcome(function, predicate):
    try:
        return ("return", function(predicate))
    except Exception as error:
        return ("raise", type(error), str(error))


@pytest.mark.parametrize("name,prefix_name", _CASES)
def test_native_prefixes_match_legacy_across_every_declared_prefix(name, prefix_name):
    predicates = [
        "", "___", "unknown", "modal_cue", "modal_operator", "predicate_argument",
        "citation_count", "citation_zero_digit_count", "citation_suffix",
        "source_id_section_suffix", "selected_frame", "condition_token",
        "citation_Kelvin_İ", None, 0, True,
    ]
    for prefix in getattr(selector, prefix_name):
        predicates.extend((prefix, prefix + "detail", prefix + "detail_suffix", "x" + prefix))
        predicates.append("  " + (prefix + "detail").upper().replace("_", "-") + "  ")
    legacy = _legacy_functions()[name]
    for predicate in predicates:
        assert _outcome(getattr(selector, name), predicate) == _outcome(legacy, predicate), predicate


@pytest.mark.parametrize("name,prefix_name", _CASES)
@pytest.mark.parametrize(
    "kind",
    ("empty", "list", "string", "match_before_invalid", "invalid_before_match", "match_before_raise", "miss_then_raise"),
)
def test_replaced_prefix_sequence_keeps_iteration_errors_and_short_circuit(
    monkeypatch, name, prefix_name, kind
):
    def run(legacy):
        events = []

        class Prefixes:
            def __iter__(self):
                events.append("iter")
                prefix = "unmatched" if kind == "match_before_raise" else "different"
                events.append(("yield", prefix))
                yield prefix
                events.append("raise")
                raise ValueError("prefix iterator failed after first item")

        replacements = {
            "empty": (),
            "list": ["different", "unmatched"],
            "string": "unmatched",
            "match_before_invalid": ("unmatched", None),
            "invalid_before_match": (None, "unmatched"),
        }
        replacement = replacements.get(kind, Prefixes())
        with monkeypatch.context() as patch:
            patch.setattr(selector, prefix_name, replacement)
            function = _legacy_functions()[name] if legacy else getattr(selector, name)
            outcome = _outcome(function, "unmatched_suffix")
        return outcome, events

    assert run(False) == run(True)


@pytest.mark.parametrize(
    "name,prefix_name,predicate,expected",
    (
        (*_CASES[0], "modal_cue", True),
        (*_CASES[1], "", False),
        (*_CASES[2], "predicate_alnum_segment", True),
        (*_CASES[2], "citation_count", False),
        (*_CASES[3], "modal_operator", True),
        (*_CASES[3], "unknown_count", False),
    ),
)
@pytest.mark.parametrize("deleted", (False, True))
def test_existing_early_return_does_not_consume_replaced_prefixes(
    monkeypatch, name, prefix_name, predicate, expected, deleted
):
    class UnusablePrefixes:
        def __iter__(self):
            raise AssertionError("early return must not touch prefix iterable")

    if deleted:
        monkeypatch.delattr(selector, prefix_name)
    else:
        monkeypatch.setattr(selector, prefix_name, UnusablePrefixes())
    assert getattr(selector, name)(predicate) is expected
    assert _legacy_functions()[name](predicate) is expected


@pytest.mark.parametrize("name,prefix_name", _CASES)
def test_custom_normalized_string_keeps_individual_startswith_calls(
    monkeypatch, name, prefix_name
):
    def run(legacy):
        events = []

        class Normalized(str):
            def strip(self, chars=None):
                events.append(("strip", chars))
                return self

            def startswith(self, prefix, *args):
                events.append(("startswith", prefix))
                assert not isinstance(prefix, tuple)
                return super().startswith(prefix, *args)

            def endswith(self, suffix, *args):
                events.append(("endswith", suffix))
                return super().endswith(suffix, *args)

        class Pattern:
            def sub(self, replacement, value):
                events.append(("sub", replacement, value))
                return Normalized("citation_suffix")

        with monkeypatch.context() as patch:
            patch.setattr(selector, "_FRAME_ONTOLOGY_PREDICATE_TOKEN_RE", Pattern())
            function = _legacy_functions()[name] if legacy else getattr(selector, name)
            result = _outcome(function, "  Mixed INPUT  ")
        assert any(event[0] == "startswith" for event in events)
        return result, events

    assert run(False) == run(True)


@pytest.mark.parametrize("name,prefix_name", _CASES[2:])
def test_custom_alias_value_keeps_individual_prefix_calls(monkeypatch, name, prefix_name):
    def run(legacy):
        events = []

        class Alias(str):
            def startswith(self, prefix, *args):
                events.append(prefix)
                assert not isinstance(prefix, tuple)
                return super().startswith(prefix, *args)

        with monkeypatch.context() as patch:
            patch.setattr(selector, "_FRAME_ONTOLOGY_PREDICATE_ALIASES", {"custom": Alias("citation_suffix")})
            function = _legacy_functions()[name] if legacy else getattr(selector, name)
            result = _outcome(function, "custom")
        assert events
        return result, events

    assert run(False) == run(True)


@pytest.mark.parametrize("name,prefix_name", _CASES)
def test_input_coercion_side_effects_match_legacy(name, prefix_name):
    def run(legacy):
        events = []

        class Predicate:
            def __bool__(self):
                events.append("bool")
                return True

            def __str__(self):
                events.append("str")
                return "  CITATION Section Suffix  "

        function = _legacy_functions()[name] if legacy else getattr(selector, name)
        return _outcome(function, Predicate()), events

    assert run(False) == run(True)


def test_downstream_terms_keep_citation_numbers_suffixes_and_modal_stopwords(monkeypatch):
    triples = [
        {"predicate": "citation_section_number", "object": "1472"},
        {"predicate": "citation_section_suffix", "object": "i"},
        {"predicate": "modal_cue", "object": "shall not"},
        {"predicate": "citation_section_component_count", "object": "3"},
        {"predicate": "unknown_predicate", "object": "unrelated evidence"},
    ]
    features = ["flogic:" + row["predicate"] + ":" + row["object"] for row in triples]
    actual = (
        selector.frame_ontology_terms_from_triples(triples),
        selector.frame_ontology_terms_from_feature_keys(features),
    )
    historical = _legacy_functions()
    with monkeypatch.context() as patch:
        for name, _prefix_name in _CASES:
            patch.setattr(selector, name, historical[name])
        expected = (
            selector.frame_ontology_terms_from_triples(triples),
            selector.frame_ontology_terms_from_feature_keys(features),
        )
    assert actual == expected
    for terms in actual:
        assert {"1472", "i", "shall_not"}.issubset(terms)
        assert "3" not in terms
        assert "unrelated_evidence" not in terms


@pytest.mark.parametrize("name,prefix_name", _CASES)
def test_deleted_prefix_global_keeps_failure_at_prefix_evaluation(monkeypatch, name, prefix_name):
    monkeypatch.delattr(selector, prefix_name)
    actual = _outcome(getattr(selector, name), "unmatched_suffix")
    expected = _outcome(_legacy_functions()[name], "unmatched_suffix")
    assert actual == expected
    assert actual[0:2] == ("raise", NameError)


def test_contextual_membership_can_rebind_prefixes_before_dispatch(monkeypatch):
    name, prefix_name = _CASES[0]
    original_prefixes = getattr(selector, prefix_name)

    def run(legacy):
        events = []

        class RebindingMembership:
            namespace = None

            def __contains__(self, value):
                events.append(("contains", value))
                self.namespace[prefix_name] = ["citation_"]
                return False

        membership = RebindingMembership()
        with monkeypatch.context() as patch:
            # Register restoration before __contains__ mutates the module global.
            patch.setattr(selector, prefix_name, original_prefixes)
            patch.setattr(selector, "_FRAME_ONTOLOGY_CONTEXTUAL_FLOGIC_PREDICATES", membership)
            function = _legacy_functions()[name] if legacy else getattr(selector, name)
            membership.namespace = function.__globals__
            result = _outcome(function, "citation_suffix")
        return result, events

    assert run(False) == run(True) == (
        ("return", True), [("contains", "citation_suffix")]
    )
