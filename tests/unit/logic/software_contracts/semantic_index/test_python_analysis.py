"""Contract tests for non-executing Python semantic extraction."""

from __future__ import annotations

from pathlib import Path

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


def test_logical_bindings_are_aggregated_and_child_bodies_are_local() -> None:
    before = _by_name("""
from typing import overload
class Value:
    @property
    def item(self): return 1
    @item.setter
    def item(self, value): self._item = value
    @item.deleter
    def item(self): del self._item
    def left(self): return 1
    def right(self): return 2
@overload
def parse(value: int) -> int: ...
@overload
def parse(value: str) -> str: ...
def parse(value): return value
""")
    after = _by_name("""
from typing import overload
class Value:
    @property
    def item(self): return 1
    @item.setter
    def item(self, value): self._item = value
    @item.deleter
    def item(self): del self._item
    def left(self): return 99
    def right(self): return 2
@overload
def parse(value: int) -> int: ...
@overload
def parse(value: str) -> str: ...
def parse(value): return value
""")
    assert len([key for key in before if key.endswith(".parse")]) == 1
    property_fact = before["pkg.example.Value.item"]
    assert property_fact.symbol.kind == "property"
    assert property_fact.symbol.metadata["facet_count"] == 3
    assert [facet["role"] for facet in property_fact.symbol.metadata["facets"]] == ["getter", "setter", "deleter"]
    assert before["pkg.example.Value.left"].symbol.version_cid != after["pkg.example.Value.left"].symbol.version_cid
    assert before["pkg.example.Value.right"].symbol.version_cid == after["pkg.example.Value.right"].symbol.version_cid
    assert before["pkg.example"].symbol.version_cid == after["pkg.example"].symbol.version_cid


def test_literals_keep_whitespace_and_construct_fixture_is_opaque_where_needed() -> None:
    literals = _by_name('def one(value="a  b"): return value\ndef two(value="a b"): return value\n')
    assert literals["pkg.example.one"].symbol.signature != literals["pkg.example.two"].symbol.signature
    fixture = Path(__file__).resolve().parents[4] / "fixtures/software_contracts/incremental_semantic_index/python_constructs/authority_cases.py"
    facts = _by_name(fixture.read_text())
    assert facts["pkg.example.Movie"].symbol.kind == "typed_dict"
    assert facts["pkg.example.Movie"].symbol.annotations["fields"] == {"title": "str"}
    assert {facts[f"pkg.example.{name}"].symbol.kind for name in ("Priority", "Label", "Options")} == {"enum"}
    assert facts["pkg.example.Request"].symbol.annotations["pydantic_model"] is True
    run = facts["pkg.example.Service.run"]
    assert {edge.relation for edge in run.edges} >= {"reads_state", "writes_state", "catches", "serializes", "validates", "calls"}
    assert facts["pkg.example.Service.dynamic"].symbol.confidence == "opaque"
    assert facts["pkg.example.Service.native"].symbol.confidence == "opaque"
    assert any(edge.confidence == "opaque" for edge in facts["pkg.example.Service.native"].edges)
    assert "pkg.example.conditional" in facts
