"""Frozen ordered-output oracle; no spaCy, embeddings, training or admission."""
from __future__ import annotations

import ast
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import inspect
import json
from pathlib import Path
import sys
import types

import pytest

from ipfs_datasets_py.logic.modal import decompiler as d
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument, ModalIRFormula, ModalIROperator, ModalIRPredicate, ModalIRProvenance,
)

ORACLE_PATH = Path(__file__).resolve().parents[3] / "fixtures/modal_surface_profiles_before.py.txt"
ORACLE_SHA = "164c8ae5edf960909e9196f66599ed375fecc57fa0ebea64418ea2a6bf068521"
TEXTS = (
    "Sec. 799 - Regulation of power resources.",
    "Section 141 was repealed. Editorial Notes: Codification. Viruses, serums, and antitoxins.",
    "The agency shall retain records for five years unless otherwise provided by law.",
    "The Secretary shall report annually to Congress not later than January 1 of each fiscal year.",
    "The effective date applies after enactment; notice shall be given at least 20 days before action.",
    "National flood insurance policy disclosures and conditions and exclusions apply.",
    "The National Security Act of 1947 was reclassified and transferred.",
    "The corporation shall adopt bylaws; members have voting rights at meetings.",
    "Café records must_not be withheld, except as otherwise provided in this subsection.",
    "No classified surface is present in this ordinary sentence.",
    "", "   ",
)


@pytest.fixture
def original():
    raw = ORACLE_PATH.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ORACLE_SHA
    namespace = dict(vars(d))
    exec(compile(raw, str(ORACLE_PATH), "exec"), namespace)
    compiled = namespace["_typed_decompiler_target_surface_profiles"]
    # Live globals preserve replacements; expected body is pinned pre-edit code.
    return types.FunctionType(compiled.__code__, vars(d), compiled.__name__)


def document(text, *, family="frame", multiple=False):
    def formula(identifier, family, start=0):
        return ModalIRFormula(formula_id=identifier,
            operator=ModalIROperator(family=family, system="fixture", symbol="Frame" if family == "frame" else "O", label="fixture"),
            predicate=ModalIRPredicate(name="retain_records", arguments=["subject:agency", "object:records"], role="clause"),
            provenance=ModalIRProvenance(source_id="us-code-42-799-fixture", start_char=start,
                end_char=len(text), citation="42 U.S.C. 799"),
            conditions=["after enactment"] if "after" in text else [],
            exceptions=["otherwise provided by law"] if "unless" in text else [],
            metadata={"cue": "shall", "fallback_rule": "uscode_section_heading_v1"})
    formulas = [formula("z-last-id", family)]
    if multiple:
        formulas.append(formula("a-first-id", "temporal", min(3, len(text))))
    return ModalIRDocument(document_id="us-code-42-799-fixture", source="us_code", normalized_text=text,
        formulas=formulas, metadata={"citation": "42 U.S.C. 799", "parser_warnings": ["fixture warning"]})


def reconstruction(doc):
    formula = doc.formulas[0]
    return d._typed_decompiler_target_reconstruction_slots(formula=formula, document=doc,
        predicate_text="retain records", condition_values=formula.conditions, exception_values=formula.exceptions)


def classify(doc, memo=None):
    kwargs = {} if memo is None else {"_surface_text_memo": memo}
    return d._typed_decompiler_target_surface_profiles(document=doc, formula=doc.formulas[0], **kwargs)


@contextmanager
def count_calls(function):
    code, previous, calls = function.__code__, sys.getprofile(), []
    def observe(frame, event, arg):
        if event == "call" and frame.f_code is code:
            calls.append(None)
        if previous is not None:
            previous(frame, event, arg)
    sys.setprofile(observe)
    try:
        yield calls
    finally:
        sys.setprofile(previous)


@pytest.mark.parametrize("text", TEXTS)
def test_classifier_and_ordered_reconstruction_match_frozen_helper(text, original, monkeypatch):
    doc = document(text)
    assert classify(doc) == original(document=doc, formula=doc.formulas[0])
    actual = reconstruction(doc)
    with monkeypatch.context() as patch:
        patch.setattr(d, "_typed_decompiler_target_surface_profiles", original)
        expected = reconstruction(document(text))
    assert actual == expected


@pytest.mark.parametrize("text", TEXTS[:9])
def test_every_decoded_field_and_order_match_frozen_classifier(text, original, monkeypatch):
    actual = d.decode_modal_ir_document(document(text, multiple=True)).to_dict()
    with monkeypatch.context() as patch:
        patch.setattr(d, "_typed_decompiler_target_surface_profiles", original)
        expected = d.decode_modal_ir_document(document(text, multiple=True)).to_dict()
    # JSON preserves ordered phrase/span/formula arrays and signed float zero.
    assert json.dumps(actual, ensure_ascii=False, allow_nan=False) == json.dumps(expected, ensure_ascii=False, allow_nan=False)
    assert actual["parser_warnings"] == ["fixture warning"]


def test_extracted_tail_statements_are_identical_to_frozen_source():
    old = ast.parse(ORACLE_PATH.read_text()).body[-1]
    new = ast.parse(inspect.getsource(d._typed_decompiler_text_surface_profiles)).body[0]
    def tail(node):
        start = next(index for index, child in enumerate(node.body) if isinstance(child, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == "lowered" for target in child.targets))
        return ast.dump(ast.Module(body=node.body[start:], type_ignores=[]), include_attributes=False)
    assert tail(new) == tail(old)


def test_native_reconstruction_classifies_text_once_per_invocation():
    doc = document(TEXTS[0])
    with count_calls(d._typed_decompiler_text_surface_profiles) as calls:
        first = reconstruction(doc)
        assert len(calls) == 1
        second = reconstruction(doc)
        assert len(calls) == 2
    assert first == second
    targets = [value for name, value in first if name == "typed-decompiler-target-reconstruction-family"]
    assert len(set(targets)) >= 3


def test_direct_helpers_uncached_and_return_independent_lists():
    doc = document(TEXTS[5])
    with count_calls(d._typed_decompiler_text_surface_profiles) as calls:
        first, second = classify(doc), classify(doc)
    assert len(calls) == 2 and first == second and first is not second
    first.clear()
    assert classify(doc) == second


@pytest.mark.parametrize("text,expected", [("", 1), ("x" * 65536, 1), ("x" * 65537, 2)])
def test_memo_successful_exact_string_bound(text, expected):
    memo = d._SurfaceTextProfileMemo()
    with count_calls(d._typed_decompiler_text_surface_profiles) as calls:
        first, second = memo.profiles(text), memo.profiles(text)
    assert len(calls) == expected
    assert list(first) == list(second)


def test_changed_text_evicts_previous_entry_and_returned_lists_are_detached():
    memo = d._SurfaceTextProfileMemo()
    with count_calls(d._typed_decompiler_text_surface_profiles) as calls:
        a = classify(document(TEXTS[5]), memo)
        expected = list(a)
        a.clear()
        assert classify(document(TEXTS[5]), memo) == expected
        classify(document(TEXTS[6]), memo)
        assert classify(document(TEXTS[5]), memo) == expected
    assert len(calls) == 3


def test_heading_status_calls_remain_ordered_on_hits(original, monkeypatch):
    def run(function):
        trace, values = [], iter([False, True, True, False])
        doc = document(TEXTS[5])
        def heading(**kwargs):
            trace.append("heading")
            return next(values)
        def status(**kwargs):
            trace.append("status")
            return next(values)
        with monkeypatch.context() as patch:
            patch.setattr(d, "_fallback_section_heading_tail_text", heading)
            patch.setattr(d, "_uscode_status_clause_keywords", status)
            memo = d._SurfaceTextProfileMemo()
            results = []
            for _ in range(2):
                kwargs = {"_surface_text_memo": memo} if function is d._typed_decompiler_target_surface_profiles else {}
                results.append(function(document=doc, formula=doc.formulas[0], **kwargs))
        return results, trace
    assert run(d._typed_decompiler_target_surface_profiles) == run(original)


def test_str_subclass_lower_is_repeated_not_memoized():
    lower_calls = []
    class Text(str):
        def lower(self):
            lower_calls.append(None)
            return super().lower()
    text = Text(TEXTS[5])
    memo = d._SurfaceTextProfileMemo()
    with count_calls(d._typed_decompiler_text_surface_profiles) as calls:
        first, second = memo.profiles(text), memo.profiles(text)
    assert list(first) == list(second)
    assert len(calls) == len(lower_calls) == 2


@pytest.mark.parametrize("name", ["_typed_decompiler_surface_profile_slots", "_typed_decompiler_reconstruction_profile_slots"])
def test_replaced_slot_renderer_receives_original_kwargs_without_private_memo(name, monkeypatch):
    seen = []
    original_renderer = getattr(d, name)
    allowed = set(inspect.signature(original_renderer).parameters) - {"_surface_text_memo"}
    def replacement(**kwargs):
        assert set(kwargs) == allowed
        seen.append(kwargs["pair"])
        return [("fixture_custom_renderer", kwargs["pair"])]
    monkeypatch.setattr(d, name, replacement)
    slots = reconstruction(document(TEXTS[0]))
    assert len(seen) >= 3
    assert [value for key, value in slots if key == "fixture_custom_renderer"] == seen


def test_replaced_target_helper_keeps_old_signature_and_every_call(monkeypatch):
    seen = []
    def replacement(*, document, formula):
        seen.append((document, formula))
        return [f"custom_surface_{len(seen)}"]
    monkeypatch.setattr(d, "_typed_decompiler_target_surface_profiles", replacement)
    doc = document(TEXTS[0])
    slots = reconstruction(doc)
    targets = [value for key, value in slots if key == "typed-decompiler-target-reconstruction-family"]
    assert len(targets) >= 3 and len(seen) == 2 * len(targets)
    assert all(pair == (doc, doc.formulas[0]) for pair in seen)


def test_replaced_tail_invalidates_warm_entry_and_failure_never_populates_it(monkeypatch):
    text, memo = TEXTS[5], d._SurfaceTextProfileMemo()
    expected = list(memo.profiles(text))
    failure = RuntimeError("tail failure")
    def fail(text):
        raise failure
    with monkeypatch.context() as patch:
        patch.setattr(d, "_typed_decompiler_text_surface_profiles", fail)
        with pytest.raises(RuntimeError) as caught:
            memo.profiles(text)
        assert caught.value is failure
    with count_calls(d._typed_decompiler_text_surface_profiles) as calls:
        assert list(memo.profiles(text)) == expected
        assert list(memo.profiles(text)) == expected
    assert len(calls) == 1


def test_replaced_tail_runs_each_time_and_does_not_retain_partial_output(monkeypatch):
    memo = d._SurfaceTextProfileMemo()
    memo.profiles(TEXTS[5])
    calls = []
    def tail(text):
        calls.append(text)
        return [f"changed_{len(calls)}"]
    monkeypatch.setattr(d, "_typed_decompiler_text_surface_profiles", tail)
    assert list(memo.profiles(TEXTS[5])) == ["changed_1"]
    assert list(memo.profiles(TEXTS[5])) == ["changed_2"]


def test_same_function_changed_tail_code_is_not_treated_as_native(monkeypatch):
    memo = d._SurfaceTextProfileMemo()
    memo.profiles(TEXTS[5])
    native = d._typed_decompiler_text_surface_profiles
    def replacement(text):
        return ["modified_native_code"]
    with monkeypatch.context() as patch:
        patch.setattr(native, "__code__", replacement.__code__)
        with count_calls(native) as calls:
            assert list(memo.profiles(TEXTS[5])) == ["modified_native_code"]
            assert list(memo.profiles(TEXTS[5])) == ["modified_native_code"]
        assert len(calls) == 2
    assert "modified_native_code" not in memo.profiles(TEXTS[5])


def test_replaced_search_identity_preserves_dynamic_calls_and_exception(monkeypatch):
    memo, text = d._SurfaceTextProfileMemo(), TEXTS[5]
    memo.profiles(text)
    original_search, seen = d.re.search, []
    failure = RuntimeError("search failure")
    def search(pattern, string, flags=0):
        seen.append(pattern)
        if len(seen) == 1:
            raise failure
        return original_search(pattern, string, flags)
    with monkeypatch.context() as patch:
        patch.setattr(d.re, "search", search)
        with pytest.raises(RuntimeError) as caught:
            memo.profiles(text)
        assert caught.value is failure
        first = list(memo.profiles(text))
        after_first = len(seen)
        assert list(memo.profiles(text)) == first
        assert len(seen) > after_first


def test_same_search_function_code_change_invalidates_memo(monkeypatch):
    memo, text = d._SurfaceTextProfileMemo(), TEXTS[5]
    expected = list(memo.profiles(text))
    native = d.re.search
    # Code runs with the native re module globals; no closure is introduced.
    def changed_search(pattern, string, flags=0):
        return _compile(pattern, flags).search(string)
    with monkeypatch.context() as patch:
        patch.setattr(native, "__code__", changed_search.__code__)
        with count_calls(d._typed_decompiler_text_surface_profiles) as calls:
            assert list(memo.profiles(text)) == expected
            assert list(memo.profiles(text)) == expected
        assert len(calls) == 2


def test_search_default_flags_change_invalidates_warm_memo(monkeypatch):
    memo, text = d._SurfaceTextProfileMemo(), "épolicy disclosures"
    before = list(memo.profiles(text))
    assert "uscode_policy_disclosure_surface" not in before
    with monkeypatch.context() as patch:
        patch.setattr(d.re.search, "__defaults__", (d.re.ASCII,))
        with count_calls(d._typed_decompiler_text_surface_profiles) as calls:
            after = list(memo.profiles(text))
            assert list(memo.profiles(text)) == after
        assert len(calls) == 2
        assert "uscode_policy_disclosure_surface" in after
    assert list(memo.profiles(text)) == before


def test_replaced_regex_compiler_invalidates_warm_memo_and_preserves_failure(monkeypatch):
    memo, text = d._SurfaceTextProfileMemo(), "épolicy disclosures"
    before = list(memo.profiles(text))
    assert "uscode_policy_disclosure_surface" not in before
    native_compile, seen = d.re._compile, []
    failure = RuntimeError("regex compiler failure")
    should_fail = [True]

    def changed_compile(pattern, flags):
        if type(pattern) is str and "policy\\s+disclosures?" in pattern:
            seen.append(pattern)
            if should_fail:
                should_fail.pop()
                raise failure
        return native_compile(pattern, flags | d.re.ASCII)

    with monkeypatch.context() as patch:
        patch.setattr(d.re, "_compile", changed_compile)
        with pytest.raises(RuntimeError) as caught:
            memo.profiles(text)
        assert caught.value is failure
        after = list(memo.profiles(text))
        assert "uscode_policy_disclosure_surface" in after
        first_count = len(seen)
        assert list(memo.profiles(text)) == after
        assert len(seen) > first_count
    assert list(memo.profiles(text)) == before


def test_import_with_callable_search_without_code_keeps_uncached_behavior(monkeypatch):
    # Execute the candidate bytes under an isolated module name: dataclasses
    # need that temporary sys.modules entry, but canonical d stays untouched.
    source_path = Path(d.__file__)
    candidate_code = compile(source_path.read_bytes(), str(source_path), "exec")
    module_name = d.__name__ + "_surface_profile_import_fixture"
    isolated = types.ModuleType(module_name)
    isolated.__file__, isolated.__package__ = str(source_path), d.__package__
    native_search = d.re.search
    expected = d._typed_decompiler_text_surface_profiles(TEXTS[5])

    class CallableSearch:
        def __call__(self, pattern, string, flags=0):
            return native_search(pattern, string, flags)

    search = CallableSearch()
    assert not hasattr(search, "__code__")
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, module_name, isolated)
        patch.setattr(d.re, "search", search)
        exec(candidate_code, vars(isolated))
        memo = isolated._SurfaceTextProfileMemo()
        with count_calls(isolated._typed_decompiler_text_surface_profiles) as calls:
            assert list(memo.profiles(TEXTS[5])) == expected
            assert list(memo.profiles(TEXTS[5])) == expected
        assert len(calls) == 2
    assert d.re.search is native_search
    assert module_name not in sys.modules


def test_reentrant_nested_reconstruction_has_independent_memo(monkeypatch):
    outer, inner = document(TEXTS[5]), document(TEXTS[6])
    baseline_outer, baseline_inner = reconstruction(outer), reconstruction(inner)
    original_heading = d._fallback_section_heading_tail_text
    entered, nested = [], []
    def heading(*, document, formula, **kwargs):
        if document is outer and not entered:
            entered.append(True)
            nested.append(reconstruction(inner))
        return original_heading(document=document, formula=formula, **kwargs)
    monkeypatch.setattr(d, "_fallback_section_heading_tail_text", heading)
    with count_calls(d._typed_decompiler_text_surface_profiles) as calls:
        actual = reconstruction(outer)
    assert actual == baseline_outer and nested == [baseline_inner]
    assert len(calls) == 2


def test_empty_family_preserves_short_circuit_without_classifier():
    doc = document(TEXTS[0], family="")
    with count_calls(d._typed_decompiler_text_surface_profiles) as calls:
        assert reconstruction(doc) == []
    assert not calls


@pytest.mark.parametrize("helper_name", ["_typed_decompiler_surface_profile_slots", "_typed_decompiler_reconstruction_profile_slots"])
def test_direct_renderer_invalid_family_branch_keeps_existing_call_order(helper_name, original, monkeypatch):
    renderer = getattr(d, helper_name)
    doc = document(TEXTS[5])
    kwargs = dict(document=doc, formula=doc.formulas[0], source_family="", target_family="deontic", pair="")
    if helper_name == "_typed_decompiler_reconstruction_profile_slots":
        kwargs.update(force="", polarity="", predicate_key="", semantic_predicate_key="", semantic_atoms=[])
    actual_trace = []
    original_source = d._typed_decompiler_source_surface_profile
    def source(document):
        actual_trace.append("source")
        return original_source(document)
    def target(*, document, formula):
        actual_trace.append("target")
        return original(document=document, formula=formula)
    with monkeypatch.context() as patch:
        patch.setattr(d, "_typed_decompiler_source_surface_profile", source)
        patch.setattr(d, "_typed_decompiler_target_surface_profiles", target)
        assert renderer(**kwargs) == []
    assert actual_trace == (["source", "target"] if helper_name == "_typed_decompiler_surface_profile_slots" else [])



def test_text_capture_precedes_heading_mutation(original, monkeypatch):
    def run(function):
        doc, trace = document(TEXTS[5]), []
        def heading(**kwargs):
            trace.append(doc.normalized_text)
            object.__setattr__(doc, "normalized_text", TEXTS[6])
            return "heading"
        with monkeypatch.context() as patch:
            patch.setattr(d, "_fallback_section_heading_tail_text", heading)
            patch.setattr(d, "_uscode_status_clause_keywords", lambda **kwargs: [])
            memo = d._SurfaceTextProfileMemo()
            kwargs = {"_surface_text_memo": memo} if function is d._typed_decompiler_target_surface_profiles else {}
            values = [function(document=doc, formula=doc.formulas[0], **kwargs) for _ in range(2)]
        return values, trace
    assert run(d._typed_decompiler_target_surface_profiles) == run(original)


def test_scripted_getter_and_custom_clean_string_remain_dynamic(original, monkeypatch):
    class Text(str):
        pass
    def run(function):
        native = document(TEXTS[5])
        trace, texts = [], iter([TEXTS[5], TEXTS[6], TEXTS[5]])
        class Proxy:
            @property
            def normalized_text(self):
                value = next(texts)
                trace.append(value)
                return value
        with monkeypatch.context() as patch:
            patch.setattr(d, "_fallback_section_heading_tail_text", lambda **kwargs: "")
            patch.setattr(d, "_uscode_status_clause_keywords", lambda **kwargs: [])
            patch.setattr(d, "_clean_text", lambda value: Text(value))
            memo = d._SurfaceTextProfileMemo()
            kwargs = {"_surface_text_memo": memo} if function is d._typed_decompiler_target_surface_profiles else {}
            values = [function(document=Proxy(), formula=native.formulas[0], **kwargs) for _ in range(3)]
        return values, trace
    assert run(d._typed_decompiler_target_surface_profiles) == run(original)


@pytest.mark.parametrize("helper", ["_fallback_section_heading_tail_text", "_uscode_status_clause_keywords"])
def test_dynamic_helper_exception_identity_and_order(helper, original, monkeypatch):
    failure = RuntimeError("scripted helper failure")
    def run(function):
        trace = []
        def heading(**kwargs):
            trace.append("heading")
            if helper.endswith("tail_text"):
                raise failure
            return ""
        def status(**kwargs):
            trace.append("status")
            raise failure
        doc = document(TEXTS[0])
        with monkeypatch.context() as patch:
            patch.setattr(d, "_fallback_section_heading_tail_text", heading)
            patch.setattr(d, "_uscode_status_clause_keywords", status)
            with pytest.raises(RuntimeError) as caught:
                kwargs = {"_surface_text_memo": d._SurfaceTextProfileMemo()} if function is d._typed_decompiler_target_surface_profiles else {}
                function(document=doc, formula=doc.formulas[0], **kwargs)
        assert caught.value is failure
        return trace
    assert run(d._typed_decompiler_target_surface_profiles) == run(original)


def test_native_status_helper_observes_each_mutable_metadata_get(original):
    def run(function):
        trace = []
        class Metadata(dict):
            def get(self, key, default=None):
                trace.append(key)
                if key == "status_keyword":
                    return "repealed" if trace.count(key) == 1 else ""
                return super().get(key, default)
        doc = document(TEXTS[5])
        formula = replace(doc.formulas[0], metadata=Metadata())
        doc = replace(doc, formulas=[formula])
        memo = d._SurfaceTextProfileMemo()
        kwargs = {"_surface_text_memo": memo} if function is d._typed_decompiler_target_surface_profiles else {}
        values = [function(document=doc, formula=formula, **kwargs) for _ in range(2)]
        return values, trace
    actual, expected = run(d._typed_decompiler_target_surface_profiles), run(original)
    assert actual == expected
    assert actual[1].count("status_keyword") >= 2
