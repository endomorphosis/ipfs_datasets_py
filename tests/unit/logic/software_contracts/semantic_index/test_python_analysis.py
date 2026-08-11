"""Contract tests for non-executing Python semantic extraction."""

from __future__ import annotations

from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import analyze_python_source


def _by_name(source: str):
    result = analyze_python_source(source, "pkg/example.py", "repo:example")
    return {item.symbol.qualified_name: item for item in result.symbols}


def test_extracts_symbol_contracts_and_position_free_ast() -> None:
    first = _by_name("\n\ndef answer(value: int = 1) -> int:\n    return value + 1\n")
    second = _by_name("def answer(value: int = 1) -> int:\n\treturn value + 1\n")
    fact = first["pkg.example.answer"]
    assert fact.symbol.confidence == "exact"
    assert fact.symbol.signature["parameters"][0]["annotation"] == "int"
    assert fact.symbol.version_cid == second["pkg.example.answer"].symbol.version_cid
    assert "lineno" not in repr(fact.normalized_ast)


def test_effects_and_dynamic_behavior_are_explicit_and_scoped() -> None:
    facts = _by_name("""
import json
class Service:
    def safe(self):
        return json.dumps({"ok": True})
    def dynamic(self, text):
        return eval(text)
""")
    safe = facts["pkg.example.Service.safe"]
    dynamic = facts["pkg.example.Service.dynamic"]
    assert safe.symbol.confidence == "exact"
    assert dynamic.symbol.confidence == "opaque"
    assert "eval_or_exec" in dynamic.confidence_reasons
    assert any(edge.relation == "serializes" for edge in safe.edges)


def test_monkey_patching_makes_affected_class_and_method_opaque() -> None:
    facts = _by_name("""
class Target:
    def method(self):
        return 1
Target.method = lambda self: 2
""")
    assert facts["pkg.example.Target"].symbol.confidence == "opaque"
    assert facts["pkg.example.Target.method"].symbol.confidence == "opaque"
    assert "monkey_patch" in facts["pkg.example.Target.method"].confidence_reasons


def test_unknown_decorator_and_dynamic_import_do_not_claim_exactness() -> None:
    facts = _by_name("""
@framework.decorator
def extension(name):
    return importlib.import_module(name)
""")
    fact = facts["pkg.example.extension"]
    assert fact.symbol.confidence == "conservative"
    assert {"unknown_decorator", "dynamic_import"} <= set(fact.confidence_reasons)
