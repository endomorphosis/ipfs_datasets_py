"""Content guards retain canonical JSON identity across mutations and aliases."""
import copy
from collections import OrderedDict
from dataclasses import FrozenInstanceError
import hashlib
import json
import math
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import checkpoint_content_guard as subject


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, ensure_ascii=True).encode()


def _checkpoint():
    return {"binding": {"dimension": 8, "source": "unicode: §"},
            "model_state": {"weight": [[0.25, 0.0, -0.0], [-1.5, 1.0, 2.0]]},
            "progress": {"steps": 1, "trained": True}, "optional": None}


def test_snapshot_and_original_digest_are_immutable_and_unaliased():
    checkpoint = _checkpoint()
    digest = hashlib.sha256(_raw(checkpoint)).hexdigest()
    guard = subject.CheckpointContentGuard(checkpoint, expected_sha256=digest)
    assert guard.sha256 == digest
    assert guard.matches(checkpoint)
    checkpoint["model_state"]["weight"][0][0] = 0.5
    assert guard.matches(checkpoint) is False
    assert guard.matches(_checkpoint())
    assert guard.sha256 == digest
    with pytest.raises(FrozenInstanceError):
        guard._sha256 = "0" * 64
    with pytest.raises(ValueError, match="SHA-256 differs"):
        subject.CheckpointContentGuard(checkpoint, expected_sha256=digest)


@pytest.mark.parametrize("mutation", (
    lambda value: list.__setitem__(value["model_state"]["weight"][0], 0, .5),
    lambda value: dict.__setitem__(value["model_state"], "extra", [0.0]),
    lambda value: list.append(value["model_state"]["weight"][0], 0.25),
    lambda value: list.__delitem__(value["model_state"]["weight"], 1),
    lambda value: dict.__delitem__(value, "optional"),
    lambda value: value["progress"].update(steps=1.0),
    lambda value: value["progress"].update(steps=True),
    lambda value: value["progress"].update(trained=1),
    lambda value: list.__setitem__(value["model_state"]["weight"][0], 1, -0.0),
    lambda value: list.__setitem__(value["model_state"]["weight"][0], 2, 0.0),
    lambda value: list.__setitem__(value["model_state"]["weight"][0], 0, math.nan),
    lambda value: list.__setitem__(value["model_state"]["weight"][0], 0, math.inf),
    lambda value: value.update(optional=bytearray(b"invalid JSON")),
    lambda value: value.update(optional=object()),
))
def test_all_current_content_is_checked_including_base_container_writes(mutation):
    checkpoint = _checkpoint()
    guard = subject.CheckpointContentGuard(checkpoint)
    mutation(checkpoint)
    assert guard.matches(checkpoint) is False
    with pytest.raises(ValueError, match="sidecar drift"):
        guard.check(checkpoint, message="sidecar drift")


def test_dictionary_order_and_list_tuple_changes_preserve_canonical_digest():
    checkpoint = _checkpoint()
    guard = subject.CheckpointContentGuard(checkpoint)
    current = dict(reversed(list(copy.deepcopy(checkpoint).items())))
    current["model_state"]["weight"] = tuple(tuple(row) for row in current["model_state"]["weight"])
    assert _raw(current) == _raw(checkpoint)
    assert guard.matches(current)
    assert guard.matches(OrderedDict(reversed(list(current.items()))))


def test_json_numeric_subclasses_use_the_canonical_encoder_without_weakening_checks():
    class Number(float):
        pass
    guard = subject.CheckpointContentGuard({"value": 0.25})
    assert guard.matches({"value": Number(0.25)})
    assert not guard.matches({"value": Number(0.5)})
    assert not guard.matches({"value": Number(math.nan)})
    subclass_guard = subject.CheckpointContentGuard({"value": Number(0.25)})
    assert subclass_guard.matches({"value": 0.25})


def test_json_key_conversion_is_verified_by_canonical_fallback():
    guard = subject.CheckpointContentGuard({"1": "value"})
    assert guard.matches({1: "value"})
    assert not guard.matches({1: "changed"})
    assert not guard.matches({"1": "value", 1: "value"})


def test_initial_numeric_keys_keep_original_sorted_json_order():
    original = {2: "two", 10: "ten"}
    guard = subject.CheckpointContentGuard(original)
    normalized = {"2": "two", "10": "ten"}
    assert _raw(original) != _raw(normalized)
    assert guard.matches(original)
    assert not guard.matches(normalized)


@pytest.mark.parametrize("value", ({"value": math.nan}, {"value": math.inf}, {"value": object()}))
def test_invalid_initial_json_is_rejected(value):
    with pytest.raises((TypeError, ValueError)):
        subject.CheckpointContentGuard(value)


def test_source_drift_is_rejected_before_any_content_result(monkeypatch):
    checkpoint = _checkpoint()
    guard = subject.CheckpointContentGuard(checkpoint)
    original = Path.read_bytes
    source = Path(subject.__file__)
    def drift(path):
        raw = original(path)
        return raw + b"\n# source drift\n" if path == source else raw
    monkeypatch.setattr(Path, "read_bytes", drift)
    with pytest.raises(ValueError, match="guard source changed"):
        guard.matches(checkpoint)
    with pytest.raises(ValueError, match="guard source changed"):
        guard.check(checkpoint)


def test_cyclic_current_values_cannot_match_an_acyclic_snapshot():
    checkpoint = {"values": [None]}
    guard = subject.CheckpointContentGuard(checkpoint)
    checkpoint["values"][0] = checkpoint
    assert guard.matches(checkpoint) is False


@pytest.mark.parametrize("index", (0, 64, 128))
def test_long_immutable_atom_arrays_check_direct_writes_at_every_position(index):
    checkpoint = {"values": [float(value) / 10 for value in range(129)]}
    guard = subject.CheckpointContentGuard(checkpoint)
    assert guard.matches(checkpoint)
    original = checkpoint["values"][index]
    list.__setitem__(checkpoint["values"], index, original + 1.0)
    assert guard.matches(checkpoint) is False
    list.__setitem__(checkpoint["values"], index, float(str(original)))
    assert guard.matches(checkpoint)


@pytest.mark.parametrize("original,replacement", ((1.0, 1), (1, True),
                                                  (True, 1), (0.0, -0.0),
                                                  (-0.0, 0.0)))
def test_replaced_atom_arrays_preserve_numeric_type_and_zero_sign(original, replacement):
    checkpoint = {"values": ["unchanged", None, original, False]}
    guard = subject.CheckpointContentGuard(checkpoint)
    list.__setitem__(checkpoint["values"], 2, replacement)
    assert _raw(checkpoint) != guard._canonical_bytes
    assert guard.matches(checkpoint) is False


def test_private_frozen_snapshot_nodes_cannot_bypass_json_value_validation():
    checkpoint = {"values": [[0.25]], "binding": {"dimension": 8}}
    guard = subject.CheckpointContentGuard(checkpoint)
    assert guard.matches(guard._reference) is False
    fields = dict(guard._reference.fields)
    checkpoint["values"][0] = fields["values"].items[0]
    assert guard.matches(checkpoint) is False
    checkpoint["values"] = [[0.25]]
    checkpoint["binding"] = fields["binding"]
    assert guard.matches(checkpoint) is False
