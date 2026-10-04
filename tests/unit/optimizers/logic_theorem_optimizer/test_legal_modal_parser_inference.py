"""Compiled cues preserve original parser filters, ordering and registry edits."""
import importlib
from dataclasses import replace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_modal_parser_inference as subject


@pytest.fixture(params=subject._PARSER_MODULES)
def parsers(request):
    module = importlib.import_module(request.param)
    return module.LegalModalParser(), subject.build_parser(request.param), module


@pytest.mark.parametrize("text", [
    "", "No modal cues here.", "The agency shall submit reports.",
    "The operator must not destroy records.",
    "The agency may inspect records within thirty days unless notice was provided.",
    "The agency shall act if approval is given and must retain records afterward.",
    "The requirement was amended in May 2020 and may be repealed.",
    "Editorial Notes: amendments required by Public Law 100-5.",
    "The operator is required to report, except when the court directs otherwise.",
    "The agency shall always preserve evidence and eventually provide notice.",
])
def test_exact_cue_and_full_parse_parity(parsers, text):
    original, fast, _ = parsers
    assert fast.extract_cues(text) == original.extract_cues(text)
    assert fast.parse(text, document_id="test", source="us_code").to_dict() == original.parse(
        text, document_id="test", source="us_code").to_dict()


def test_warm_cues_survive_standard_cache_eviction_without_recompilation(parsers, monkeypatch):
    original, fast, module = parsers
    subject._compile.cache_clear()
    text = "The agency shall submit reports."
    expected = original.extract_cues(text)
    assert fast.extract_cues(text) == expected
    module.re.purge()
    def forbidden(*args, **options):
        raise AssertionError("cached cue pattern was compiled again")
    monkeypatch.setattr(module.re, "compile", forbidden)
    assert fast.extract_cues(text) == expected
    assert subject._compile.cache_info().maxsize == 4096


def test_current_parser_globals_remain_visible_between_calls(parsers, monkeypatch):
    original, fast, module = parsers
    text = "The agency is required to report."
    fast.extract_cues(text)
    monkeypatch.setattr(module, "_USCODE_EDITORIAL_REQUIRED_CUES", frozenset({"shall"}))
    assert fast.extract_cues(text) == original.extract_cues(text)


def test_source_drift_and_unknown_parser_are_rejected(monkeypatch):
    with pytest.raises(ValueError, match="unknown Legal parser"):
        subject.build_parser("unknown.module")
    parser = subject.build_parser()
    monkeypatch.setattr(subject, "_source_sha256", lambda: "0" * 64)
    with pytest.raises(ValueError, match="changed since import"):
        parser.extract_cues("The agency shall report.")


def test_escaped_cues_are_reused_and_replaced_dependency_is_observed(monkeypatch):
    subject._escaped.cache_clear()
    original = subject.re.escape
    calls = []
    def tracked(text):
        calls.append(text)
        return original(text)
    monkeypatch.setattr(subject.re, "escape", tracked)
    assert subject._REGEX.escape("a.b") == original("a.b")
    assert subject._REGEX.escape("a.b") == original("a.b")
    assert calls == ["a.b"]
    monkeypatch.setattr(subject.re, "escape", lambda text: "new dependency")
    assert subject._REGEX.escape("a.b") == "new dependency"
    assert subject._escaped.cache_info().maxsize == 4096


def test_custom_string_translation_is_not_cached():
    calls = []
    class CustomCue(str):
        def translate(self, table):
            calls.append(self)
            return str(self).translate(table)
    cue = CustomCue("a.b")
    assert subject._REGEX.escape(cue) == r"a\.b"
    assert subject._REGEX.escape(cue) == r"a\.b"
    assert len(calls) == 2
    assert subject._REGEX.escape(b"a.b") == subject.re.escape(b"a.b")


def test_new_registry_cues_are_observed_after_warming(parsers):
    original, _, module = parsers
    profile = original.registry.all_profiles()[0]
    operator = replace(profile.operators[0], cue_terms=("first.cue",))
    profile = replace(profile, operators=(operator,))
    registry = module.ModalRegistry((profile,))
    fast = subject.build_parser(module.__name__, registry=registry)
    ordinary = module.LegalModalParser(registry)
    text = "first.cue second+cue"
    assert fast.extract_cues(text) == ordinary.extract_cues(text)
    changed = replace(profile, operators=(replace(operator, cue_terms=("second+cue",)),))
    registry._profiles[profile.profile_id] = changed
    assert fast.extract_cues(text) == ordinary.extract_cues(text)
    assert [cue.cue for cue in fast.extract_cues(text)] == ["second+cue"]
