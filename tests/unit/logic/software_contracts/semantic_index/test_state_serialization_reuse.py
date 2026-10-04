"""Native graph serialization reuses one detached payload, never its identity."""
from dataclasses import fields, replace
import sys
from types import MappingProxyType

import pytest

from ipfs_datasets_py.logic.software_contracts import content
from ipfs_datasets_py.logic.software_contracts.semantic_index import models
from .test_models import _symbol


def historical(state):
    """The pre-change public serializer, including its custom dispatch order."""
    return {"schema": state.schema, "repository_id": state.repository_id,
        "symbols": [item.to_dict() for item in state.symbols],
        "artifacts": [item.to_dict() for item in state.artifacts],
        "edges": [item.to_dict() for item in state.edges],
        "extractor_name": state.extractor_name, "extractor_version": state.extractor_version,
        "state_cid": state.state_cid}


@pytest.fixture
def state():
    span = models.SourceSpan("pkg/mod.py", 1, 0, 2, 18)
    symbol = _symbol(span=span)
    artifacts = [models.ArtifactRecord("artifact:z", "config", "café/λ.json",
        metadata={"nested": {"items": [1, True, None, "λ"]}}),
        models.ArtifactRecord("artifact:a", "config", "a.json")]
    edges = [models.DependencyEdge(symbol.stable_id, item.artifact_id, "calls", "lexical",
        "conservative", "1", span, {"path": item.path}) for item in artifacts]
    return models.RepositoryState("repo:example", [symbol], artifacts, edges)


def calls_during(call, code):
    calls = []
    previous = sys.getprofile()
    def observe(frame, event, argument):
        if event == "call" and frame.f_code is code:
            calls.append(True)
    sys.setprofile(observe)
    try:
        return call(), len(calls)
    finally:
        sys.setprofile(previous)


def test_native_output_and_cid_match_historical_bytes_with_one_child_traversal(state):
    assert models._state_payload_reusable(state)
    expected, old_calls = calls_during(lambda: historical(state), models.DependencyEdge.to_dict.__code__)
    actual, new_calls = calls_during(state.to_dict, models.DependencyEdge.to_dict.__code__)
    assert old_calls == 4 and new_calls == 2
    assert list(actual) == list(expected)
    assert content.canonical_dag_json_bytes(actual) == content.canonical_dag_json_bytes(expected)
    assert actual["schema"] == models.SEMANTIC_INDEX_SCHEMA
    assert actual["state_cid"] == content.cid_for_structured(state.identity_payload())
    assert "semantic_index_schema" not in actual
    assert models.RepositoryState.from_dict(actual) == state


def test_public_output_is_detached_and_later_calls_hash_current_fields(state):
    first = state.to_dict()
    first["artifacts"][1]["metadata"]["nested"]["items"].append("caller mutation")
    first["symbols"][0]["signature"]["parameters"].append("caller mutation")
    first["edges"].clear()
    assert state.to_dict() == historical(state)
    prior = state.to_dict()["state_cid"]
    object.__setattr__(state, "extractor_version", "changed-current-field")
    assert state.to_dict() == historical(state)
    assert state.to_dict()["state_cid"] != prior
    edge = state.edges[0]
    object.__setattr__(edge, "metadata", MappingProxyType({"current": (1, 2)}))
    assert state.to_dict() == historical(state)
    assert state.to_dict()["state_cid"] != prior


def test_each_serialization_still_hashes_all_current_edge_and_state_bodies(state, monkeypatch):
    from multiformats import multihash
    original = multihash.digest
    bodies = []
    def digest(data, *args, **kwargs):
        bodies.append(bytes(data))
        return original(data, *args, **kwargs)
    monkeypatch.setattr(multihash, "digest", digest)
    first = state.to_dict()
    first_bodies = tuple(bodies)
    assert len(first_bodies) == len(state.edges) + 1
    assert state.to_dict() == first
    assert tuple(bodies) == first_bodies * 2
    object.__setattr__(state, "extractor_name", "fresh-native-input")
    assert state.to_dict()["state_cid"] != first["state_cid"]
    assert bodies[-1] != first_bodies[-1]


@pytest.mark.parametrize("damage", ["edge_identity", "state_identity", "symbol_identity", "duplicate_edge", "duplicate_artifact"])
def test_restore_keeps_full_identity_and_duplicate_refusals(state, damage):
    raw = state.to_dict()
    if damage == "edge_identity":
        raw["edges"][0]["source_id"] = "forged-source"
    elif damage == "state_identity":
        raw["extractor_version"] = "forged-version"
    elif damage == "symbol_identity":
        raw["symbols"][0]["kind"] = "method"
    elif damage == "duplicate_edge":
        raw["edges"].append(raw["edges"][0])
    else:
        raw["artifacts"].append(raw["artifacts"][0])
    with pytest.raises(models.SemanticIndexModelError):
        models.RepositoryState.from_dict(raw)


def test_collection_order_remains_canonical(state):
    permuted = replace(state, artifacts=tuple(reversed(state.artifacts)), edges=tuple(reversed(state.edges)))
    assert permuted.to_dict() == state.to_dict()
    assert [row["artifact_id"] for row in state.to_dict()["artifacts"]] == ["artifact:a", "artifact:z"]


@pytest.mark.parametrize("kind", ["state_cid", "identity_payload"])
def test_state_subclass_preserves_historical_property_and_payload_dispatch(state, kind):
    calls = []
    class CustomState(models.RepositoryState):
        pass
    if kind == "state_cid":
        def identity(self):
            calls.append("custom-state-cid")
            return content.cid_for_structured({"custom": len(calls)})
        CustomState.state_cid = property(identity)
    else:
        def payload(self):
            calls.append("custom-payload")
            value = super(CustomState, self).identity_payload()
            value["custom"] = len(calls)
            return value
        CustomState.identity_payload = payload
    custom = CustomState(**{field.name: getattr(state, field.name) for field in fields(state)})
    assert not models._state_payload_reusable(custom)
    expected = historical(custom); expected_calls = list(calls); calls.clear()
    assert custom.to_dict() == expected
    assert calls == expected_calls


@pytest.mark.parametrize("kind", ["edge", "artifact", "symbol", "span"])
def test_nested_subclass_keeps_historical_two_traversal_behavior(state, kind):
    calls = []
    cls = {"edge": models.DependencyEdge, "artifact": models.ArtifactRecord,
           "symbol": models.SymbolRecord, "span": models.SourceSpan}[kind]
    class Custom(cls):
        def to_dict(self):
            calls.append("custom")
            result = super().to_dict()
            result["custom"] = len(calls)
            return result
    item = {"edge": state.edges[0], "artifact": state.artifacts[0],
            "symbol": state.symbols[0], "span": state.symbols[0].span}[kind]
    custom = Custom(**{field.name: getattr(item, field.name) for field in fields(item)})
    if kind == "edge":
        state = replace(state, edges=(custom, state.edges[1]))
    elif kind == "artifact":
        state = replace(state, artifacts=(custom, state.artifacts[1]))
    elif kind == "symbol":
        state = replace(state, symbols=(custom,))
    else:
        state = replace(state, symbols=(replace(state.symbols[0], span=custom),))
    assert not models._state_payload_reusable(state)
    calls.clear(); expected = historical(state); expected_calls = list(calls); calls.clear()
    assert state.to_dict() == expected
    assert calls == expected_calls == ["custom", "custom"]


@pytest.mark.parametrize("kind", ["state_cid", "identity_payload", "child", "span", "field", "cid", "thaw"])
def test_native_class_and_function_replacements_keep_historical_dispatch(state, monkeypatch, kind):
    calls = []
    if kind == "state_cid":
        original = models.RepositoryState.state_cid.fget
        def replacement(self):
            calls.append(kind); return original(self)
        monkeypatch.setattr(models.RepositoryState, "state_cid", property(replacement))
    elif kind == "identity_payload":
        original = models.RepositoryState.identity_payload
        def replacement(self):
            calls.append(kind); return original(self)
        monkeypatch.setattr(models.RepositoryState, "identity_payload", replacement)
    elif kind in {"child", "span"}:
        owner = models.DependencyEdge if kind == "child" else models.SourceSpan
        original = owner.to_dict
        def replacement(self):
            calls.append(kind); return original(self)
        monkeypatch.setattr(owner, "to_dict", replacement)
    elif kind == "field":
        monkeypatch.setattr(models.ArtifactRecord, "kind", property(lambda self: "custom-field"))
    else:
        name = "cid_for_structured" if kind == "cid" else "_thaw_structured"
        original = getattr(models, name)
        def replacement(value):
            calls.append(kind); return original(value)
        monkeypatch.setattr(models, name, replacement)
    assert not models._state_payload_reusable(state)
    expected = historical(state); expected_calls = list(calls); calls.clear()
    assert state.to_dict() == expected
    assert calls == expected_calls


@pytest.mark.parametrize("kind", ["edges", "metadata", "signature"])
def test_forged_mutable_outer_containers_are_not_reused(state, kind):
    if kind == "edges":
        object.__setattr__(state, "edges", list(state.edges))
    elif kind == "metadata":
        object.__setattr__(state.artifacts[0], "metadata", {"mutable": [1]})
    else:
        object.__setattr__(state.symbols[0], "signature", {"mutable": [1]})
    assert not models._state_payload_reusable(state)
    assert state.to_dict() == historical(state)


def test_forged_invalid_nested_scalar_still_fails_content_validation(state):
    object.__setattr__(state.edges[0], "metadata", MappingProxyType({"bad": float("nan")}))
    for serialize in (state.to_dict, lambda: historical(state)):
        with pytest.raises(content.StructuredIdentityError):
            serialize()


def test_native_manifest_memo_eligibility_survives_new_serialization_anchors():
    from ipfs_datasets_py.logic.software_contracts import codebase_ir
    assert codebase_ir._manifest_producer_key() is not None
