"""Fresh canonical CID reads without changing observable dynamic-view behavior.

These tests use actual producer records and CID/source admission. Counting and
stateful subclasses are explicit regression fixtures, not admitted source views.
No target code, provider, network, storage owner or prover is executed.
"""

from __future__ import annotations

import ast
from dataclasses import fields, replace

import pytest
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import (
    stable_symbol_id,
    symbol_version_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    ArtifactRecord,
    DependencyEdge,
    RepositoryState,
    SourceSpan,
    SymbolRecord,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.source import (
    SourceAdmissionError,
    SourceBindingMismatchError,
    SourceCorruptError,
    SourceWrongStateError,
    read_required_source,
    source_slice,
)

REPOSITORY = "repo:state-read-regression"


def source_fixture():
    raw = b"def add(value):\n    return value + 1\n"
    node = ast.parse(raw.decode()).body[0]
    signature = {"parameters": [], "return": None}
    stable = stable_symbol_id(REPOSITORY, "python", "pkg/mod.py", "pkg.add", "function", "pkg")
    version = symbol_version_cid(stable, node, signature, (), {})
    span = SourceSpan("pkg/mod.py", node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)
    symbol = SymbolRecord(
        stable_id=stable,
        version_cid=version,
        repository_id=REPOSITORY,
        language="python",
        module_path="pkg/mod.py",
        qualified_name="pkg.add",
        kind="function",
        namespace="pkg",
        source_cid=cid_for_bytes(raw),
        span=span,
        signature=signature,
        normalized_ast=node,
    )
    artifact = ArtifactRecord("artifact:module", "python_source", "pkg/mod.py", symbol.source_cid)
    edge = DependencyEdge(stable, "external:dependency", "calls", "authored-source-regression", "exact", "1", span)
    state = RepositoryState(REPOSITORY, symbols=(symbol,), artifacts=(artifact,), edges=(edge,))
    return state, symbol, raw


def clone_as(record_type, record):
    return record_type(**{field.name: getattr(record, field.name) for field in fields(record)})


def count_state_computations(monkeypatch):
    getter = RepositoryState.state_cid.fget
    reads = []

    def counted(instance):
        reads.append(instance)
        return getter(instance)

    monkeypatch.setattr(RepositoryState, "state_cid", property(counted))
    return reads


class BlobReader:
    def __init__(self, cid, raw, *, second=None):
        self.cid, self.raw, self.second = cid, raw, second
        self.calls = []

    def __call__(self, cid):
        self.calls.append(cid)
        assert cid == self.cid
        if len(self.calls) == 2 and self.second is not None:
            return self.second
        return self.raw


class SequenceView:
    """Authored observable property; does not claim an immutable producer lease."""

    def __init__(self, state, values):
        self.symbols = state.symbols
        self.values = values
        self.gets = 0

    @property
    def state_cid(self):
        value = self.values[min(self.gets, len(self.values) - 1)]
        self.gets += 1
        if isinstance(value, BaseException):
            raise value
        return value


@pytest.mark.parametrize("spans", ["both_exact", "symbol_none", "edge_none", "both_none"])
def test_exact_native_state_computes_once_and_reads_both_source_bytes(monkeypatch, spans):
    state, symbol, raw = source_fixture()
    if spans in {"symbol_none", "both_none"}:
        symbol = replace(symbol, span=None)
        state = replace(state, symbols=(symbol,))
    if spans in {"edge_none", "both_none"}:
        state = replace(state, edges=(replace(state.edges[0], span=None),))
    expected = state.state_cid
    computations = count_state_computations(monkeypatch)
    reader = BlobReader(symbol.source_cid, raw)
    result = read_required_source(
        state, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader,
    )
    assert computations == [state]
    assert reader.calls == [symbol.source_cid, symbol.source_cid]
    assert result.source_bytes == raw
    assert result.producer_state_cid == expected
    assert result.span_bytes == raw[result.evidence.start_offset:result.evidence.end_offset]


def test_exact_native_state_with_empty_optional_record_sets_still_computes_once(monkeypatch):
    state, symbol, raw = source_fixture()
    state = replace(state, artifacts=(), edges=())
    expected = state.state_cid
    computations = count_state_computations(monkeypatch)
    reader = BlobReader(symbol.source_cid, raw)
    result = read_required_source(state, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert computations == [state]
    assert result.source_bytes == raw and reader.calls == [symbol.source_cid] * 2


def test_each_native_call_freshly_recomputes_without_a_cached_cid(monkeypatch):
    state, symbol, raw = source_fixture()
    expected = state.state_cid
    computations = count_state_computations(monkeypatch)
    reader = BlobReader(symbol.source_cid, raw)
    first = read_required_source(state, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    second = read_required_source(state, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert first.evidence == second.evidence
    assert computations == [state, state]
    assert reader.calls == [symbol.source_cid] * 4


def test_wrong_native_state_still_refuses_before_reading_source(monkeypatch):
    state, symbol, raw = source_fixture()
    computations = count_state_computations(monkeypatch)
    reader = BlobReader(symbol.source_cid, raw)
    with pytest.raises(SourceWrongStateError) as error:
        read_required_source(
            state, symbol.stable_id, expected_producer_state_cid=cid_for_bytes(b"foreign-state"),
            read_source_blob=reader,
        )
    assert computations == [state]
    assert reader.calls == [] and error.value.requires_rescan is True


@pytest.mark.parametrize("nested", ["symbol", "artifact", "edge", "symbol_span", "edge_span"])
def test_nested_subclasses_retain_two_observable_cid_computations(monkeypatch, nested):
    state, symbol, raw = source_fixture()

    class SymbolSubclass(SymbolRecord):
        pass

    class ArtifactSubclass(ArtifactRecord):
        pass

    class EdgeSubclass(DependencyEdge):
        pass

    class SpanSubclass(SourceSpan):
        pass

    if nested == "symbol":
        state = replace(state, symbols=(clone_as(SymbolSubclass, symbol),))
    elif nested == "artifact":
        state = replace(state, artifacts=(clone_as(ArtifactSubclass, state.artifacts[0]),))
    elif nested == "edge":
        state = replace(state, edges=(clone_as(EdgeSubclass, state.edges[0]),))
    elif nested == "symbol_span":
        state = replace(state, symbols=(replace(symbol, span=clone_as(SpanSubclass, symbol.span)),))
    else:
        state = replace(state, edges=(replace(state.edges[0], span=clone_as(SpanSubclass, state.edges[0].span)),))
    expected = state.state_cid
    computations = count_state_computations(monkeypatch)
    reader = BlobReader(symbol.source_cid, raw)
    result = read_required_source(state, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert computations == [state, state]
    assert reader.calls == [symbol.source_cid] * 2
    assert result.source_bytes == raw


def test_outer_subclass_retains_two_observable_cid_computations(monkeypatch):
    state, symbol, raw = source_fixture()

    class StateSubclass(RepositoryState):
        pass

    state = clone_as(StateSubclass, state)
    expected = state.state_cid
    computations = count_state_computations(monkeypatch)
    reader = BlobReader(symbol.source_cid, raw)
    result = read_required_source(state, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert computations == [state, state]
    assert result.source_bytes == raw and len(reader.calls) == 2


@pytest.mark.parametrize("starts_expected", [False, True])
def test_outer_subclass_dynamic_property_retains_its_second_value(starts_expected):
    state, symbol, raw = source_fixture()
    expected = state.state_cid
    foreign = cid_for_bytes(b"foreign-outer-subclass")
    values = (expected, foreign) if starts_expected else (foreign, expected)
    reads = []

    class DynamicState(RepositoryState):
        @property
        def state_cid(self):
            value = values[min(len(reads), len(values) - 1)]
            reads.append(value)
            return value

    state = clone_as(DynamicState, state)
    reader = BlobReader(symbol.source_cid, raw)
    if starts_expected:
        with pytest.raises(SourceWrongStateError):
            read_required_source(state, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
        assert reader.calls == []
    else:
        result = read_required_source(state, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
        assert result.source_bytes == raw and len(reader.calls) == 2
    assert reads == list(values)


@pytest.mark.parametrize("nested", ["symbol", "artifact", "edge", "symbol_span", "edge_span"])
def test_dynamic_nested_serialization_cannot_skip_historical_wrong_state_refusal(monkeypatch, nested):
    state, symbol, raw = source_fixture()
    phase = {"reads": 0}

    def stateful_metadata(value):
        if phase["reads"] >= 2:
            value["metadata"]["authored_dynamic_view"] = "foreign-after-presence-probe"
        return value

    class DynamicSymbol(SymbolRecord):
        def to_dict(self):
            return stateful_metadata(super().to_dict())

    class DynamicArtifact(ArtifactRecord):
        def to_dict(self):
            return stateful_metadata(super().to_dict())

    class DynamicEdge(DependencyEdge):
        def to_dict(self):
            return stateful_metadata(super().to_dict())

    class DynamicSpan(SourceSpan):
        def to_dict(self):
            value = super().to_dict()
            if phase["reads"] >= 2:
                value["end_column"] += 1
            return value

    if nested == "symbol":
        state = replace(state, symbols=(clone_as(DynamicSymbol, symbol),))
    elif nested == "artifact":
        state = replace(state, artifacts=(clone_as(DynamicArtifact, state.artifacts[0]),))
    elif nested == "edge":
        state = replace(state, edges=(clone_as(DynamicEdge, state.edges[0]),))
    elif nested == "symbol_span":
        state = replace(state, symbols=(replace(symbol, span=clone_as(DynamicSpan, symbol.span)),))
    else:
        state = replace(state, edges=(replace(state.edges[0], span=clone_as(DynamicSpan, state.edges[0].span)),))
    expected = state.state_cid
    getter = RepositoryState.state_cid.fget

    def changing(instance):
        phase["reads"] += 1
        return getter(instance)

    monkeypatch.setattr(RepositoryState, "state_cid", property(changing))
    reader = BlobReader(symbol.source_cid, raw)
    with pytest.raises(SourceWrongStateError):
        read_required_source(state, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert phase["reads"] == 2 and reader.calls == []


@pytest.mark.parametrize("sequence, succeeds", [
    ("stable", True), ("expected_then_foreign", False), ("foreign_then_expected", True),
])
def test_generic_view_preserves_which_descriptor_read_is_authoritative(sequence, succeeds):
    state, symbol, raw = source_fixture()
    expected = state.state_cid
    foreign = cid_for_bytes(b"foreign-producer")
    values = {
        "stable": (expected,), "expected_then_foreign": (expected, foreign),
        "foreign_then_expected": (foreign, expected),
    }[sequence]
    view = SequenceView(state, values)
    reader = BlobReader(symbol.source_cid, raw)
    if succeeds:
        result = read_required_source(view, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
        assert result.source_bytes == raw and reader.calls == [symbol.source_cid] * 2
    else:
        with pytest.raises(SourceWrongStateError):
            read_required_source(view, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
        assert reader.calls == []
    assert view.gets == 2


@pytest.mark.parametrize("sequence, exception, accesses", [
    ((AttributeError("missing property"),), SourceWrongStateError, 1),
    (("expected", AttributeError("removed during second access")), AttributeError, 2),
    ((RuntimeError("getter unavailable"),), RuntimeError, 1),
])
def test_generic_descriptor_exception_behavior_is_unchanged(sequence, exception, accesses):
    state, symbol, raw = source_fixture()
    expected = state.state_cid
    values = tuple(expected if value == "expected" else value for value in sequence)
    view = SequenceView(state, values)
    reader = BlobReader(symbol.source_cid, raw)
    with pytest.raises(exception):
        read_required_source(view, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert view.gets == accesses and reader.calls == []


def test_callable_selected_on_second_access_is_invoked_once():
    state, symbol, raw = source_fixture()
    expected = state.state_cid
    called = []

    def unused_presence_probe():
        called.append("probe")
        return cid_for_bytes(b"foreign-callable-result")

    def actual():
        called.append("actual")
        return expected

    view = SequenceView(state, (unused_presence_probe, actual))
    reader = BlobReader(symbol.source_cid, raw)
    result = read_required_source(view, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert called == ["actual"] and view.gets == 2
    assert result.source_bytes == raw and reader.calls == [symbol.source_cid] * 2


@pytest.mark.parametrize("exception", [AttributeError, RuntimeError])
def test_callable_execution_exceptions_are_not_reclassified(exception):
    state, symbol, raw = source_fixture()
    calls = []

    def unavailable():
        calls.append("actual")
        raise exception("callable state identity unavailable")

    view = SequenceView(state, (unavailable,))
    reader = BlobReader(symbol.source_cid, raw)
    with pytest.raises(exception):
        read_required_source(view, symbol.stable_id, expected_producer_state_cid=state.state_cid, read_source_blob=reader)
    assert view.gets == 2 and calls == ["actual"] and reader.calls == []


def test_string_subclass_cid_is_not_silently_coerced():
    state, symbol, raw = source_fixture()
    expected = state.state_cid

    class StringSubclass(str):
        pass

    view = SequenceView(state, (StringSubclass(expected),))
    reader = BlobReader(symbol.source_cid, raw)
    with pytest.raises(SourceWrongStateError):
        read_required_source(view, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert view.gets == 2 and reader.calls == []


@pytest.mark.parametrize("value", [None, "", False, 1, b"not-a-string", "invalid-cid"])
@pytest.mark.parametrize("callable_value", [False, True])
def test_missing_or_invalid_actual_cid_still_refuses_before_source(value, callable_value):
    state, symbol, raw = source_fixture()
    expected = state.state_cid
    calls = []

    def actual():
        calls.append("call")
        return value

    view = SequenceView(state, (actual if callable_value else value,))
    reader = BlobReader(symbol.source_cid, raw)
    with pytest.raises(SourceWrongStateError) as error:
        read_required_source(view, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert error.value.requires_rescan is True
    assert view.gets == 2 and reader.calls == []
    assert calls == (["call"] if callable_value else [])


def test_absent_state_cid_refuses_without_source_or_symbol_access():
    class NoStateCid:
        @property
        def symbols(self):
            raise AssertionError("missing state must refuse before resolving symbols")

    reader = BlobReader("unused", b"unused")
    with pytest.raises(SourceWrongStateError):
        read_required_source(
            NoStateCid(), cid_for_bytes(b"symbol"),
            expected_producer_state_cid=cid_for_bytes(b"expected"), read_source_blob=reader,
        )
    assert reader.calls == []


@pytest.mark.parametrize("expected", [None, "", False, "invalid-cid"])
def test_invalid_expected_state_never_reads_actual_descriptor(expected):
    state, symbol, raw = source_fixture()
    view = SequenceView(state, (AssertionError("must not inspect actual state"),))
    reader = BlobReader(symbol.source_cid, raw)
    with pytest.raises(SourceAdmissionError):
        read_required_source(view, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert view.gets == 0 and reader.calls == []


@pytest.mark.parametrize("index_kind", ["native", "generic"])
def test_corrupt_source_still_reverifies_first_blob_without_a_second_read(index_kind):
    state, symbol, raw = source_fixture()
    expected = state.state_cid
    index = state if index_kind == "native" else SequenceView(state, (expected,))
    reader = BlobReader(symbol.source_cid, raw + b"# corrupt\n")
    with pytest.raises(SourceCorruptError):
        read_required_source(index, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert reader.calls == [symbol.source_cid]


@pytest.mark.parametrize("index_kind", ["native", "generic"])
def test_source_toctou_still_reads_twice_and_rejects_changed_second_bytes(index_kind):
    state, symbol, raw = source_fixture()
    expected = state.state_cid
    index = state if index_kind == "native" else SequenceView(state, (expected,))
    reader = BlobReader(symbol.source_cid, raw, second=raw + b"# changed after first read\n")
    with pytest.raises(SourceBindingMismatchError) as error:
        read_required_source(index, symbol.stable_id, expected_producer_state_cid=expected, read_source_blob=reader)
    assert "TOCTOU" in str(error.value)
    assert reader.calls == [symbol.source_cid] * 2


def test_generic_source_slice_does_not_materialize_bytes():
    state, symbol, _ = source_fixture()
    expected = state.state_cid
    view = SequenceView(state, (expected,))
    reference = source_slice(view, symbol.stable_id, expected_producer_state_cid=expected)
    assert reference.producer_state_cid == expected and reference.source_cid == symbol.source_cid
    assert view.gets == 2
