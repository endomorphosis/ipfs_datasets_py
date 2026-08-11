"""Protected ISI-044 gates for source-bound Python relation authority."""

from __future__ import annotations

from textwrap import dedent

from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    RelationType,
    SourceSpan,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.python_analysis import (
    PythonSymbolFacts,
    analyze_python_source,
)

PATH = "pkg/relations.py"
REPOSITORY_ID = "repo:python-relation-adversarial"
_NONEXACT = {
    AnalysisConfidence.CONSERVATIVE,
    AnalysisConfidence.OPAQUE,
}


def _analyze(source: str):
    return analyze_python_source(source, PATH, REPOSITORY_ID)


def _facts(source: str) -> dict[str, PythonSymbolFacts]:
    return {fact.symbol.qualified_name: fact for fact in _analyze(source).symbols}


def _source_span(source: str, containing: str, token: str | None = None) -> SourceSpan:
    assert source.count(containing) == 1, containing
    fragment_start = source.index(containing)
    token = containing if token is None else token
    assert containing.count(token) == 1, (containing, token)
    start = fragment_start + containing.index(token)
    line_start = source.rfind("\n", 0, start) + 1
    line = source.count("\n", 0, start) + 1
    column = len(source[line_start:start].encode("utf-8"))
    return SourceSpan(
        PATH,
        line,
        column,
        line,
        column + len(token.encode("utf-8")),
    )


def _assert_edge(
    fact: PythonSymbolFacts,
    source: str,
    *,
    relation: RelationType,
    target: str,
    method: str,
    confidence: AnalysisConfidence,
    containing: str,
    token: str | None = None,
) -> None:
    expected = (
        fact.symbol.stable_id,
        target,
        relation.value,
        method,
        confidence.value,
        _source_span(source, containing, token),
    )
    contracts = [
        (
            edge.source_id,
            edge.target_id,
            edge.relation,
            edge.extraction_method,
            edge.confidence,
            edge.span,
        )
        for edge in fact.edges
    ]
    assert contracts.count(expected) == 1, (expected, contracts)


def _assert_nonexact_call(
    fact: PythonSymbolFacts,
    source: str,
    *,
    target: str,
    containing: str,
    reason: str,
    token: str | None = None,
) -> None:
    span = _source_span(source, containing, token)
    matching = [
        edge
        for edge in fact.edges
        if edge.relation == RelationType.CALLS
        and edge.target_id == target
        and edge.extraction_method == "lexical"
        and edge.span == span
    ]
    assert len(matching) == 1
    assert matching[0].confidence in _NONEXACT
    assert fact.symbol.confidence in _NONEXACT
    assert reason in fact.confidence_reasons


def test_inheritance_implements_and_composition_have_exact_type_targets() -> None:
    source = dedent("""\
        from typing import Protocol

        class Interface(Protocol):
            def run(self) -> None: ...

        class Base:
            pass

        class Component:
            pass

        class Concrete(Base, Interface):
            component: Component

            def run(self) -> None:
                return None
        """)
    facts = _facts(source)
    concrete = facts["pkg.relations.Concrete"]

    _assert_edge(
        concrete,
        source,
        relation=RelationType.INHERITS,
        target=facts["pkg.relations.Base"].symbol.stable_id,
        method="class_base",
        confidence=AnalysisConfidence.EXACT,
        containing="class Concrete(Base, Interface):",
        token="Base",
    )
    _assert_edge(
        concrete,
        source,
        relation=RelationType.IMPLEMENTS,
        target=facts["pkg.relations.Interface"].symbol.stable_id,
        method="static-protocol-inheritance",
        confidence=AnalysisConfidence.EXACT,
        containing="class Concrete(Base, Interface):",
        token="Interface",
    )
    _assert_edge(
        concrete,
        source,
        relation=RelationType.READS_STATE,
        target=facts["pkg.relations.Component"].symbol.stable_id,
        method="annotation_composition",
        confidence=AnalysisConfidence.EXACT,
        containing="component: Component",
        token="Component",
    )


def test_module_local_self_and_nested_calls_resolve_only_bounded_targets() -> None:
    source = dedent("""\
        import pkg.relations as module_alias

        def target():
            return 1

        def direct_caller():
            return target()

        def module_alias_caller():
            return module_alias.target()

        def local_alias_caller():
            import pkg.relations as local_alias
            return local_alias.target()

        class Worker:
            def helper(self):
                return 1

            def caller(self):
                return self.helper()

        def outer():
            def nested():
                return 1

            return nested()
        """)
    facts = _facts(source)
    target = facts["pkg.relations.target"].symbol.stable_id
    cases = (
        (
            "pkg.relations.direct_caller",
            target,
            "return target()",
            "target()",
        ),
        (
            "pkg.relations.module_alias_caller",
            target,
            "return module_alias.target()",
            "module_alias.target()",
        ),
        (
            "pkg.relations.local_alias_caller",
            target,
            "return local_alias.target()",
            "local_alias.target()",
        ),
        (
            "pkg.relations.Worker.caller",
            facts["pkg.relations.Worker.helper"].symbol.stable_id,
            "return self.helper()",
            "self.helper()",
        ),
        (
            "pkg.relations.outer",
            facts["pkg.relations.outer.nested"].symbol.stable_id,
            "return nested()",
            "nested()",
        ),
    )
    for caller, destination, containing, token in cases:
        _assert_edge(
            facts[caller],
            source,
            relation=RelationType.CALLS,
            target=destination,
            method="lexical",
            confidence=AnalysisConfidence.EXACT,
            containing=containing,
            token=token,
        )


def test_scope_and_augassign_effects_distinguish_every_static_binding() -> None:
    source = dedent("""\
        counter = 0

        def mutate_global(amount):
            global counter
            counter += amount

        def shadowed():
            counter = 10
            counter += 1
            return counter

        def outer():
            total = 0

            def mutate_nonlocal(amount):
                nonlocal total
                total += amount
                return total

            return mutate_nonlocal

        class Bucket:
            def update(self, amount):
                self.value += amount
                self.items[0] += amount
        """)
    facts = _facts(source)
    global_mutation = facts["pkg.relations.mutate_global"]
    nonlocal_mutation = facts["pkg.relations.outer.mutate_nonlocal"]
    update = facts["pkg.relations.Bucket.update"]

    for relation in (RelationType.READS_STATE, RelationType.WRITES_STATE):
        _assert_edge(
            global_mutation,
            source,
            relation=relation,
            target="global:counter",
            method="global_binding",
            confidence=AnalysisConfidence.EXACT,
            containing="counter += amount",
            token="counter",
        )
        _assert_edge(
            nonlocal_mutation,
            source,
            relation=relation,
            target="nonlocal:total",
            method="nonlocal_binding",
            confidence=AnalysisConfidence.EXACT,
            containing="total += amount",
            token="total",
        )

    for relation, method in (
        (RelationType.READS_STATE, "attribute_read"),
        (RelationType.WRITES_STATE, "attribute_write"),
    ):
        _assert_edge(
            update,
            source,
            relation=relation,
            target="state:self.value",
            method=method,
            confidence=AnalysisConfidence.EXACT,
            containing="self.value += amount",
            token="self.value",
        )
    for relation, method in (
        (RelationType.READS_STATE, "subscript_read"),
        (RelationType.WRITES_STATE, "subscript_write"),
    ):
        _assert_edge(
            update,
            source,
            relation=relation,
            target="state:self.items[]",
            method=method,
            confidence=AnalysisConfidence.EXACT,
            containing="self.items[0] += amount",
            token="self.items[0]",
        )

    shadowed = facts["pkg.relations.shadowed"]
    assert not [
        edge
        for edge in shadowed.edges
        if edge.relation in {RelationType.READS_STATE, RelationType.WRITES_STATE}
        and edge.target_id == "global:counter"
    ]


def test_tuple_catches_and_every_context_manager_keep_exact_spans() -> None:
    source = dedent("""\
        def first():
            pass

        def second():
            pass

        def guarded():
            try:
                with first() as left, second() as right:
                    return left, right
            except (ValueError, TypeError):
                return None
        """)
    facts = _facts(source)
    guarded = facts["pkg.relations.guarded"]

    for name in ("first", "second"):
        _assert_edge(
            guarded,
            source,
            relation=RelationType.CALLS,
            target=facts[f"pkg.relations.{name}"].symbol.stable_id,
            method="context_manager",
            confidence=AnalysisConfidence.EXACT,
            containing="with first() as left, second() as right:",
            token=f"{name}()",
        )
    for exception in ("ValueError", "TypeError"):
        _assert_edge(
            guarded,
            source,
            relation=RelationType.CATCHES,
            target=f"exception:{exception}",
            method="direct_except",
            confidence=AnalysisConfidence.EXACT,
            containing="except (ValueError, TypeError):",
            token=exception,
        )


def test_schema_operations_target_schema_symbols_not_operation_names() -> None:
    source = dedent("""\
        import json
        from dataclasses import asdict, dataclass
        from pydantic import BaseModel
        from typing import TypedDict

        @dataclass
        class Payload:
            value: int

        class Patch(TypedDict):
            value: int

        class Request(BaseModel):
            value: int

        def encode(payload: Payload) -> str:
            return json.dumps(asdict(payload))

        def decode(raw: str) -> Patch:
            return json.loads(raw)

        def parse_request(raw: str) -> Request:
            return Request.model_validate_json(raw)
        """)
    facts = _facts(source)

    _assert_edge(
        facts["pkg.relations.encode"],
        source,
        relation=RelationType.SERIALIZES,
        target=facts["pkg.relations.Payload"].symbol.stable_id,
        method="schema_serialization",
        confidence=AnalysisConfidence.EXACT,
        containing="return json.dumps(asdict(payload))",
        token="json.dumps(asdict(payload))",
    )
    _assert_edge(
        facts["pkg.relations.decode"],
        source,
        relation=RelationType.DESERIALIZES,
        target=facts["pkg.relations.Patch"].symbol.stable_id,
        method="schema_deserialization",
        confidence=AnalysisConfidence.EXACT,
        containing="return json.loads(raw)",
        token="json.loads(raw)",
    )
    request_target = facts["pkg.relations.Request"].symbol.stable_id
    for relation, method in (
        (RelationType.DESERIALIZES, "schema_deserialization"),
        (RelationType.VALIDATES, "schema_validation"),
    ):
        _assert_edge(
            facts["pkg.relations.parse_request"],
            source,
            relation=relation,
            target=request_target,
            method=method,
            confidence=AnalysisConfidence.EXACT,
            containing="return Request.model_validate_json(raw)",
            token="Request.model_validate_json(raw)",
        )


def test_aliased_dynamic_native_plugin_and_runtime_calls_are_never_exact() -> None:
    source = dedent("""\
        import importlib as loader
        import types as runtime_types
        from builtins import __import__ as import_builtin
        from ctypes import CDLL as NativeLoader
        from importlib.metadata import entry_points as discover_plugins

        def aliased_dynamic(name):
            return loader.import_module(name)

        def aliased_builtin(name):
            return import_builtin(name)

        def native(path):
            return NativeLoader(path)

        def plugins():
            return discover_plugins()

        def runtime_type(name):
            return type(name, (), {})

        def runtime_new(name):
            return runtime_types.new_class(name)

        def import_module():
            return None

        def entry_points():
            return ()

        class CDLL:
            pass
        """)
    facts = _facts(source)
    cases = (
        (
            "pkg.relations.aliased_dynamic",
            "lexical:importlib.import_module",
            "return loader.import_module(name)",
            "loader.import_module(name)",
            "dynamic_import",
        ),
        (
            "pkg.relations.aliased_builtin",
            "lexical:builtins.__import__",
            "return import_builtin(name)",
            "import_builtin(name)",
            "dynamic_import",
        ),
        (
            "pkg.relations.native",
            "lexical:ctypes.CDLL",
            "return NativeLoader(path)",
            "NativeLoader(path)",
            "native_boundary",
        ),
        (
            "pkg.relations.plugins",
            "lexical:importlib.metadata.entry_points",
            "return discover_plugins()",
            "discover_plugins()",
            "plugin_discovery",
        ),
        (
            "pkg.relations.runtime_type",
            "lexical:type",
            "return type(name, (), {})",
            "type(name, (), {})",
            "runtime_class_construction",
        ),
        (
            "pkg.relations.runtime_new",
            "lexical:types.new_class",
            "return runtime_types.new_class(name)",
            "runtime_types.new_class(name)",
            "runtime_class_construction",
        ),
    )
    for name, target, containing, token, reason in cases:
        _assert_nonexact_call(
            facts[name],
            source,
            target=target,
            containing=containing,
            token=token,
            reason=reason,
        )
    for name in ("import_module", "entry_points", "CDLL"):
        assert (
            facts[f"pkg.relations.{name}"].symbol.confidence == AnalysisConfidence.EXACT
        )


def test_decorator_metaclass_and_constructed_attribute_uncertainty_is_local() -> None:
    source = dedent("""\
        from builtins import setattr as assign_attribute

        @framework.hook
        def decorated():
            return None

        class Meta(type):
            pass

        class Generated(metaclass=Meta):
            pass

        def constructed_attribute(subject, name, value):
            return assign_attribute(subject, name, value)

        class Target:
            pass

        registry.Target.method = replacement

        def factory():
            class Target:
                pass

            return Target
        """)
    facts = _facts(source)

    decorated = facts["pkg.relations.decorated"]
    generated = facts["pkg.relations.Generated"]
    assert decorated.symbol.confidence in _NONEXACT
    assert "unknown_decorator" in decorated.confidence_reasons
    assert generated.symbol.confidence in _NONEXACT
    assert "metaclass_mutation" in generated.confidence_reasons

    _assert_nonexact_call(
        facts["pkg.relations.constructed_attribute"],
        source,
        target="lexical:builtins.setattr",
        containing="return assign_attribute(subject, name, value)",
        token="assign_attribute(subject, name, value)",
        reason="constructed_attribute",
    )
    for name in ("pkg.relations.Target", "pkg.relations.factory.Target"):
        assert facts[name].symbol.confidence == AnalysisConfidence.EXACT
        assert "monkey_patch" not in facts[name].confidence_reasons
