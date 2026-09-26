"""Private reduction contracts; these fixtures are not native qualification."""
from dataclasses import FrozenInstanceError
import struct
import weakref

import pytest

from ipfs_datasets_py.logic.bridge import multiview, types as bridge_types
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import _autoencoder_prepared_targets as prepared
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_snapshot as codec


def native_targets():
    view = bridge_types.LogicIRView(
        name="deontic_norms.deontic_graph", format="deontic-graph-v1", source_component="deontic.graph",
        payload={"metadata": {"created_at": "2026-09-25T00:00:00+00:00", "last_updated": "2026-09-25T00:00:01+00:00"},
                 "nodes": {"a": {"label": "agency"}}},
    )
    document = bridge_types.LegalIRDocument(
        document_id="sample", source_text="The agency shall retain records.",
        normalized_text="The agency shall retain records.", views={view.name: view},
        frame_logic_triples=({"subject": "sample", "predicate": "actor", "object": "agency"},),
    )
    target = multiview.LegalIRTrainingTarget(
        bridge_names=["deontic_norms"], document=document,
        losses={"legal_ir_multiview_total_loss": 0.25, "negative_zero": -0.0, "integer": 2},
        adapter_losses={"deontic_norms": {"loss": 0.25}},
        view_distribution={"positive": 1.0, "negative": -0.5, "zero": 0.0}, accepted=False,
    )
    return {"sample": target}


def test_native_values_exact_hashes_order_and_independent_immutable_storage():
    original = native_targets()
    original_hash = original["sample"].document.canonical_hash()
    reduced, observation = prepared._prepare_native_targets(original)
    assert reduced is not original and observation["applied"] is True
    assert observation["skip_reason"] is None
    assert observation["original_target_count"] == observation["prepared_target_count"] == 1
    assert observation["preparation_seconds"] >= observation["hash_seconds"] >= 0
    target = reduced["sample"]
    assert type(target) is prepared._PreparedNativeTarget
    assert target.document.canonical_hash() == original_hash
    assert target.document.document_id == "sample"
    assert target.document.version == original["sample"].document.version
    assert target.bridge_names == ("deontic_norms",) and target.accepted is False
    assert target.total_loss == original["sample"].total_loss
    assert dict(target.losses) == original["sample"].losses
    assert list(target.losses) == list(original["sample"].losses)
    assert target.view_distribution == original["sample"].view_distribution
    assert struct.pack("!d", target.losses["negative_zero"]) == struct.pack("!d", -0.0)
    assert type(target.losses["integer"]) is int
    assert not hasattr(target.document, "views") and not hasattr(target.document, "source_text")
    with pytest.raises(TypeError):
        reduced["another"] = target
    with pytest.raises(TypeError):
        target.losses["integer"] = 3
    with pytest.raises(TypeError):
        target.adapter_losses["deontic_norms"]["loss"] = 3
    with pytest.raises(FrozenInstanceError):
        target.accepted = True
    # Deliberate snapshot isolation is restricted to worker-owned objects.
    original["sample"].losses["integer"] = 7
    original["sample"].adapter_losses["deontic_norms"]["loss"] = 8
    original["sample"].document.views["deontic_norms.deontic_graph"].payload["metadata"]["last_updated"] = "later"
    assert target.losses["integer"] == 2 and target.adapter_losses["deontic_norms"]["loss"] == 0.25
    assert target.document.canonical_hash() == original_hash
    assert original["sample"].document.canonical_hash() != original_hash


def test_prepared_values_do_not_retain_original_graphs():
    originals = native_targets()
    target_ref = weakref.ref(originals["sample"])
    document_ref = weakref.ref(originals["sample"].document)
    view_ref = weakref.ref(originals["sample"].document.views["deontic_norms.deontic_graph"])
    reduced, result = prepared._prepare_native_targets(originals)
    assert result["applied"]
    del originals
    assert target_ref() is document_ref() is view_ref() is None
    assert reduced["sample"].document.canonical_hash()


def test_capsules_are_not_snapshot_codec_objects():
    reduced, result = prepared._prepare_native_targets(native_targets())
    assert result["applied"]
    with pytest.raises(codec.TargetSnapshotError, match="unsupported target object type"):
        codec._encode(reduced["sample"])


class Hostile:
    def __getattribute__(self, name):
        raise AssertionError("unsupported object must not be inspected")


class HostileDict(dict):
    def __len__(self):
        raise AssertionError("custom mapping must not be inspected")

    def items(self):
        raise AssertionError("custom mapping must not be inspected")


@pytest.mark.parametrize("value", [None, [], (), HostileDict(), {}])
def test_unsupported_or_empty_mapping_returns_identical_object(value):
    result, observation = prepared._prepare_native_targets(value)
    assert result is value and not observation["applied"]
    assert observation["skip_reason"] == "non_native_or_empty_target_mapping"


def test_mixed_targets_are_all_or_none_before_any_capsule_is_built(monkeypatch):
    original = native_targets()
    original["custom"] = Hostile()
    def forbidden(*args, **kwargs):
        raise AssertionError("a mixed batch must not construct an earlier native capsule")
    monkeypatch.setattr(prepared, "_PreparedNativeTarget", forbidden)
    result, observation = prepared._prepare_native_targets(original)
    assert result is original and not observation["applied"]
    assert observation["prepared_target_count"] == 0
    assert observation["skip_reason"] == "non_native_target_or_fields"


@pytest.mark.parametrize("which,attribute", [
    ("target", "grammar_validation"), ("target", "legal_ir_grammar_validation"),
    ("target", "candidate_ir"), ("target", "to_dict"),
    ("document", "canonical_hash"), ("document", "to_dict"), ("view", "to_dict"),
])
def test_extra_instance_fields_preserve_originals(which, attribute):
    original = native_targets()
    target = original["sample"]
    value = {"target": target, "document": target.document,
             "view": target.document.views["deontic_norms.deontic_graph"]}[which]
    object.__setattr__(value, attribute, Hostile())
    result, observation = prepared._prepare_native_targets(original)
    assert result is original and not observation["applied"]


@pytest.mark.parametrize("cls,name", [
    (multiview.LegalIRTrainingTarget, "to_dict"),
    (multiview.LegalIRTrainingTarget, "grammar_validation"),
    (multiview.LegalIRTrainingTarget, "candidate_ir"),
    (bridge_types.LegalIRDocument, "canonical_hash"),
    (bridge_types.LegalIRDocument, "to_dict"),
    (bridge_types.LegalIRDocument, "to_json"),
    (bridge_types.LogicIRView, "to_dict"),
])
def test_changed_class_methods_or_grammar_properties_fall_back_without_invocation(monkeypatch, cls, name):
    original = native_targets()
    def forbidden(*args):
        raise AssertionError("custom class property or method must not be invoked")
    monkeypatch.setattr(cls, name, property(forbidden), raising=False)
    result, observation = prepared._prepare_native_targets(original)
    assert result is original and observation["skip_reason"] == "native_class_contract_changed"


@pytest.mark.parametrize("module,name", [
    (multiview, "_NATIVE_LEGAL_IR_TRAINING_TARGET_TO_DICT"),
    (multiview, "LegalIRTrainingTarget"),
    (bridge_types, "LegalIRDocument"),
    (bridge_types, "LogicIRView"),
])
def test_deleted_native_identity_falls_back(monkeypatch, module, name):
    original = native_targets()
    monkeypatch.delattr(module, name)
    result, observation = prepared._prepare_native_targets(original)
    assert result is original and observation["skip_reason"] == "native_class_contract_changed"


@pytest.mark.parametrize("value", [HostileDict(), {"x": True}, {"x": float("nan")}, {"x": float("inf")},
                                   {"x": 10 ** 400}, {1: 1.0}])
def test_non_native_or_nonfinite_numeric_mappings_fall_back(value):
    original = native_targets()
    object.__setattr__(original["sample"], "losses", value)
    result, observation = prepared._prepare_native_targets(original)
    assert result is original and observation["skip_reason"] == "non_native_numeric_mappings"


def test_changed_function_code_falls_back(monkeypatch):
    original = native_targets()
    def altered(self):
        raise AssertionError("changed native function must not be called")
    monkeypatch.setattr(bridge_types.LegalIRDocument.canonical_hash, "__code__", altered.__code__)
    result, observation = prepared._prepare_native_targets(original)
    assert result is original and observation["skip_reason"] == "native_class_contract_changed"


def test_hash_failure_is_not_silently_converted_to_eligibility_fallback(monkeypatch):
    original = native_targets()
    failure = RuntimeError("synthetic hash dependency failure")
    def fail(*args, **kwargs):
        raise failure
    # Local method identity checks intentionally do not attest arbitrary globals.
    monkeypatch.setattr(bridge_types, "_stable_json", fail)
    with pytest.raises(RuntimeError) as raised:
        prepared._prepare_native_targets(original)
    assert raised.value is failure
