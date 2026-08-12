"""Contract tests for non-executing Python semantic extraction."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import SymbolKind
from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import (
    PythonFrontendDisposition,
    aggregate_logical_bindings,
    analyze_python_source,
)


def _by_name(source: str, path: str = "pkg/example.py"):
    result = analyze_python_source(source, path, "repo:example")
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


def test_except_and_match_definitions_are_inventoried_with_frontend_declarations() -> None:
    source = dedent("""\
        try:
            work()
        except ValueError:
            def recovered():
                return 1

        match payload:
            case {"ok": True}:
                class Matched:
                    ready = True
        """)
    frontend = PythonASTExtractor().extract(source, path="pkg/example.py", repository_id="repo:example")
    analysis = analyze_python_source(source, "pkg/example.py", "repo:example")
    by_name = {fact.symbol.qualified_name: fact for fact in analysis.symbols}

    assert "pkg.example.recovered" in by_name
    assert "pkg.example.Matched" in by_name
    assert by_name["pkg.example.recovered"].symbol.confidence != "exact"
    assert by_name["pkg.example.Matched"].symbol.confidence != "exact"
    assert "conditional_binding" in by_name["pkg.example.recovered"].confidence_reasons

    for name in ("pkg.example.recovered", "pkg.example.Matched"):
        frontend_ids = [
            symbol.symbol_id
            for symbol in frontend.symbols
            if symbol.qualified_name == name and symbol.kind in {"function", "class", "method", "variable", "constructor"}
        ]
        assert list(by_name[name].symbol.metadata["frontend_declarations"]) == frontend_ids


def test_recursive_child_isolation_under_control_flow() -> None:
    def source(inner: int) -> str:
        return dedent(f"""\
            FLAG = True
            def outer():
                if FLAG:
                    def inner():
                        return {inner}
                return inner
            """)

    before = _by_name(source(1))
    after = _by_name(source(99))
    assert before["pkg.example.outer.inner"].symbol.version_cid != after["pkg.example.outer.inner"].symbol.version_cid
    assert before["pkg.example.outer"].symbol.version_cid == after["pkg.example.outer"].symbol.version_cid
    assert before["pkg.example"].symbol.version_cid == after["pkg.example"].symbol.version_cid


def test_overload_only_edit_changes_public_signature() -> None:
    before = _by_name(dedent("""\
        from typing import overload

        @overload
        def convert(value: int) -> int: ...

        @overload
        def convert(value: bytes) -> bytes: ...

        def convert(value):
            return value
        """))["pkg.example.convert"].symbol
    after = _by_name(dedent("""\
        from typing import overload

        @overload
        def convert(value: float) -> float: ...

        @overload
        def convert(value: bytes) -> bytes: ...

        def convert(value):
            return value
        """))["pkg.example.convert"].symbol

    assert before.stable_id == after.stable_id
    assert before.signature != after.signature
    assert "overloads" in before.signature
    assert before.version_cid != after.version_cid


def test_module_and_local_aliases_classify_model_kinds() -> None:
    facts = _by_name(Path(__file__).resolve().parents[4].joinpath(
        "fixtures/software_contracts/incremental_semantic_index/python_constructs/alias_models.py"
    ).read_text())
    assert facts["pkg.example.AliasedEnum"].symbol.kind == SymbolKind.ENUM
    assert facts["pkg.example.AliasedDictionary"].symbol.kind == SymbolKind.TYPED_DICT
    assert facts["pkg.example.AliasedRecord"].symbol.kind == SymbolKind.DATACLASS
    assert facts["pkg.example.AliasedModel"].symbol.annotations["pydantic_model"] is True
    assert facts["pkg.example.local_models.LocalEnum"].symbol.kind == SymbolKind.ENUM
    assert facts["pkg.example.local_models.LocalDictionary"].symbol.kind == SymbolKind.TYPED_DICT
    assert facts["pkg.example.local_models.LocalRecord"].symbol.kind == SymbolKind.DATACLASS
    assert facts["pkg.example.local_models.LocalModel"].symbol.annotations["pydantic_model"] is True


def test_functional_typed_dict_keywords_and_total_version() -> None:
    optional = _by_name(dedent("""\
        from typing import TypedDict as Dictionary
        Movie = Dictionary("Movie", title=str, year=int, total=False)
        """))["pkg.example.Movie"].symbol
    required = _by_name(dedent("""\
        from typing import TypedDict as Dictionary
        Movie = Dictionary("Movie", title=str, year=int, total=True)
        """))["pkg.example.Movie"].symbol
    assert optional.kind == required.kind == SymbolKind.TYPED_DICT
    assert dict(optional.annotations["fields"]) == {"title": "str", "year": "int"}
    assert optional.annotations["total"] != required.annotations["total"]
    assert optional.version_cid != required.version_cid


def test_prefix_alias_call_resolves_like_direct_import() -> None:
    aliased = _by_name(dedent("""\
        import json as js
        def dump(value):
            return js.dumps(value)
        """))["pkg.example.dump"]
    direct = _by_name(dedent("""\
        import json
        def dump(value):
            return json.dumps(value)
        """))["pkg.example.dump"]
    assert any(edge.relation == "serializes" for edge in aliased.edges)
    assert {edge.relation for edge in aliased.edges} == {edge.relation for edge in direct.edges}


def test_nonfatal_notices_attach_to_symbols_without_whole_file_opacity() -> None:
    source = dedent("""\
        import importlib

        def evaluated(text):
            return eval(text)

        def loaded(name):
            return importlib.import_module(name)

        class Generated(metaclass=type):
            pass

        def outer():
            value = 0
            def mutate():
                nonlocal value
                value += 1
                return value
            return mutate
        """)
    analysis = analyze_python_source(source, "pkg/example.py", "repo:example")
    by_name = {fact.symbol.qualified_name: fact for fact in analysis.symbols}

    assert not analysis.diagnostics
    assert by_name["pkg.example.evaluated"].symbol.confidence == "opaque"
    assert by_name["pkg.example.loaded"].symbol.confidence in {"conservative", "opaque"}
    assert by_name["pkg.example.Generated"].symbol.confidence == "opaque"
    mutate = by_name["pkg.example.outer.mutate"]
    assert mutate.symbol.confidence in {"conservative", "opaque"}
    assert mutate.symbol.metadata["frontend_notices"]
    assert mutate.symbol.metadata["confidence_reasons"]


def test_malformed_input_is_fatal_only() -> None:
    analysis = analyze_python_source("def broken(:\n", "broken.py", "repo:example")
    assert not analysis.symbols
    assert "python.parse_error" in analysis.diagnostics
    disposition = PythonFrontendDisposition(fatal_diagnostics=("python.parse_error",))
    assert disposition.is_fatal


def test_aggregate_logical_bindings_rejects_duplicate_stable_ids() -> None:
    facts = analyze_python_source("def one():\n    return 1\n", "pkg/example.py", "repo:example").symbols
    try:
        aggregate_logical_bindings((*facts, facts[0]))
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("expected duplicate stable ID rejection")
