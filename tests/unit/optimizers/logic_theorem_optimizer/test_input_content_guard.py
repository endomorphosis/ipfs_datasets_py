"""Portable input-snapshot compatibility, custody and work-avoidance controls.

These controls use no model, scheduler, encoder or CUDA runtime. They establish
content/source behavior, not native performance or execution authority.
"""
import copy
from collections import OrderedDict
from dataclasses import FrozenInstanceError, fields
import importlib.util
import hashlib
import math
from pathlib import Path
import struct
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import checkpoint_content_guard as original
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import input_content_guard as subject


def _value():
    return {"rows": [{"id": "row-§", "latent": [0.25, 0.0, -0.0],
                      "meta": {"count": 1, "flag": True, "optional": None}}],
            "projection_id": "input-projection/v1"}


def _profile_calls(action, codes):
    # Retain code objects and key by identity, since CodeType equality omits
    # distinctions needed for source-bound observation across modules.
    retained = tuple(codes)
    calls = {id(code): 0 for code in retained}
    previous = sys.getprofile()
    def observe(frame, event, arg):
        if event == "call" and id(frame.f_code) in calls:
            calls[id(frame.f_code)] += 1
        if previous is not None:
            previous(frame, event, arg)
    try:
        sys.setprofile(observe)
        result = action()
    finally:
        sys.setprofile(previous)
    return result, calls


def _load_temporary_copy(tmp_path, monkeypatch):
    path = tmp_path / "input_guard_copy.py"
    path.write_bytes(Path(subject.__file__).read_bytes())
    name = "_input_guard_control_copy_" + str(id(tmp_path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module, path


def test_standard_snapshot_is_frozen_and_retains_no_mutable_alias():
    value = _value()
    guard = subject.InputContentGuard(value)
    assert [field.name for field in fields(guard)] == [
        "_reference", "_canonical_bytes", "_use_fast_comparison"]
    assert guard._canonical_bytes is None and guard._use_fast_comparison is True
    assert not hasattr(guard, "sha256") and not hasattr(guard, "__dict__")
    with pytest.raises(FrozenInstanceError):
        guard._reference = None
    with pytest.raises((FrozenInstanceError, TypeError)):
        guard.matches = lambda current: True
    with pytest.raises(FrozenInstanceError):
        guard._reference.fields = ()
    value["rows"][0]["latent"][0] = .5
    assert not guard.matches(value)
    assert guard.matches(_value())


@pytest.mark.parametrize("size", (0, 1, 129, 4096))
def test_flat_float_array_has_one_freeze_call_and_no_canonical_serialization(size):
    vector = [index / 10.0 for index in range(size)]
    raw_code, freeze_code = subject._raw.__code__, subject._freeze.__code__
    guard, calls = _profile_calls(lambda: subject.InputContentGuard(vector),
                                 (raw_code, freeze_code))
    assert calls[id(raw_code)] == 0 and calls[id(freeze_code)] == 1
    accepted, calls = _profile_calls(lambda: guard.matches(vector), (raw_code,))
    assert accepted is True and calls[id(raw_code)] == 0
    assert guard._reference.items == tuple(vector) and guard._reference.atoms is True


def test_nested_standard_snapshot_avoids_raw_constructor_and_repeated_checks():
    value = _value()
    def action():
        guard = subject.InputContentGuard(value)
        guard.check(value)
        guard.check(copy.deepcopy(value))
        return guard
    guard, calls = _profile_calls(action, (subject._raw.__code__,))
    assert calls[id(subject._raw.__code__)] == 0
    assert guard.matches(value)
    descriptor = guard.inference_implementation
    assert descriptor["schema"] == "input-content-guard-implementation/v1"
    assert descriptor["source_sha256"] == subject._SOURCE_AT_IMPORT
    assert descriptor["standard_path_digest_computed"] is False
    assert descriptor["standard_path_canonical_json_serialized"] is False
    assert descriptor["success_or_revision_cached"] is False


@pytest.mark.parametrize("mutation", (
    lambda value: list.__setitem__(value["rows"][0]["latent"], 0, .5),
    lambda value: dict.__setitem__(value["rows"][0]["meta"], "extra", [0.0]),
    lambda value: list.append(value["rows"][0]["latent"], .25),
    lambda value: list.__delitem__(value["rows"][0]["latent"], 1),
    lambda value: dict.__delitem__(value, "projection_id"),
    lambda value: value["rows"][0]["meta"].update(count=1.0),
    lambda value: value["rows"][0]["meta"].update(count=True),
    lambda value: value["rows"][0]["meta"].update(flag=1),
    lambda value: list.__setitem__(value["rows"][0]["latent"], 1, -0.0),
    lambda value: list.__setitem__(value["rows"][0]["latent"], 2, 0.0),
    lambda value: list.__setitem__(value["rows"][0]["latent"], 0, math.nan),
    lambda value: list.__setitem__(value["rows"][0]["latent"], 0, math.inf),
    lambda value: value["rows"][0]["meta"].update(optional=bytearray(b"invalid")),
    lambda value: value["rows"][0]["meta"].update(optional=object()),
))
def test_base_container_writes_and_numeric_mutations_are_detected(mutation):
    value = _value()
    guard, reference = subject.InputContentGuard(value), original.CheckpointContentGuard(value)
    mutation(value)
    assert guard.matches(value) is reference.matches(value) is False
    with pytest.raises(ValueError, match="local input drift"):
        guard.check(value, message="local input drift")


@pytest.mark.parametrize("index", (0, 64, 128))
def test_flat_atom_array_compares_all_positions_and_accepts_restored_equal_values(index):
    value = [number / 10 for number in range(129)]
    guard = subject.InputContentGuard(value)
    original_value = value[index]
    list.__setitem__(value, index, original_value + 1)
    assert not guard.matches(value)
    list.__setitem__(value, index, float(str(original_value)))
    assert guard.matches(value)


@pytest.mark.parametrize("before,after", (
    (1, True), (True, 1), (1, 1.0), (1.0, 1), (0.0, -0.0), (-0.0, 0.0),
))
@pytest.mark.parametrize("wrap", (lambda value: value, lambda value: [value],
                                  lambda value: {"value": ["text", None, value]}))
def test_exact_builtin_types_and_zero_sign_survive_each_snapshot_path(before, after, wrap):
    guard = subject.InputContentGuard(wrap(before))
    assert guard.matches(wrap(after)) is False


def test_float64_mutation_smaller_than_float32_resolution_is_refused():
    before, after = .25, math.nextafter(.25, math.inf)
    assert struct.pack("<f", before) == struct.pack("<f", after)
    guard = subject.InputContentGuard({"latent": [before]})
    assert not guard.matches({"latent": [after]})


@pytest.mark.parametrize("number", (math.nan, math.inf, -math.inf))
@pytest.mark.parametrize("wrap", (lambda value: value, lambda value: [value],
                                  lambda value: {"values": ["text", value]}))
def test_nonfinite_constructor_refusals_match_the_old_guard(number, wrap):
    with pytest.raises(ValueError):
        subject.InputContentGuard(wrap(number))
    with pytest.raises(ValueError):
        original.CheckpointContentGuard(wrap(number))


def test_nonfinite_after_large_integer_overflow_is_still_rejected():
    # The vector finiteness scan reaches an int too large for conversion first.
    with pytest.raises(ValueError):
        subject.InputContentGuard([1 << 2048, math.nan])
    value = [1 << 2048, 1.5]
    assert subject.InputContentGuard(value).matches(value)
    assert original.CheckpointContentGuard(value).matches(value)


def test_integer_decimal_encoder_limit_is_retained_without_whole_tree_json():
    limit = sys.get_int_max_str_digits()
    if limit == 0:
        pytest.skip("interpreter integer conversion limit is disabled")
    value = 10 ** (limit + 1)
    with pytest.raises(ValueError):
        subject.InputContentGuard([value])
    with pytest.raises(ValueError):
        original.CheckpointContentGuard([value])


def test_list_tuple_equivalence_and_dictionary_order_match_original():
    value = _value()
    current = dict(reversed(list(copy.deepcopy(value).items())))
    current["rows"] = tuple(current["rows"])
    current["rows"][0]["latent"] = tuple(current["rows"][0]["latent"])
    guard, reference = subject.InputContentGuard(value), original.CheckpointContentGuard(value)
    assert guard.matches(current) is reference.matches(current) is True
    assert guard.matches(OrderedDict(current)) is reference.matches(OrderedDict(current)) is True


def test_shared_mutable_aliases_are_snapshotted_independently_without_revision_cache():
    leaf = [.25]
    value = {"left": leaf, "right": leaf}
    guard = subject.InputContentGuard(value)
    leaf[0] = .5
    assert not guard.matches(value)
    assert guard.matches({"left": [.25], "right": [.25]})
    leaf[0] = .25
    assert guard.matches(value)
    dict.__setitem__(value, "left", [.5])
    assert not guard.matches(value)


@pytest.mark.parametrize("kind", (dict, list))
def test_circular_constructor_and_current_inputs_refuse(kind):
    value = {} if kind is dict else []
    if kind is dict:
        value["cycle"] = value
    else:
        value.append(value)
    with pytest.raises(ValueError):
        subject.InputContentGuard(value)
    guard = subject.InputContentGuard({"cycle": [None]})
    assert not guard.matches({"cycle": value})


def test_frozen_nodes_are_not_accepted_as_public_json_values():
    value = {"nested": [[.25]], "binding": {"count": 1}}
    guard = subject.InputContentGuard(value)
    assert not guard.matches(guard._reference)
    expected = dict(guard._reference.fields)
    value["nested"][0] = expected["nested"].items[0]
    assert not guard.matches(value)
    value["nested"] = [[.25]]
    value["binding"] = expected["binding"]
    assert not guard.matches(value)


@pytest.mark.parametrize("base", (dict, list, tuple, float, int, str))
def test_json_serializable_subclasses_keep_canonical_fallback(base):
    subclass = type("JsonSubclass", (base,), {})
    values = {dict: {"a": [.25]}, list: [.25], tuple: (.25,),
              float: .25, int: 1, str: "unicode §"}
    value = subclass(values[base])
    guard = subject.InputContentGuard(value)
    reference = original.CheckpointContentGuard(value)
    assert guard._use_fast_comparison is False
    assert guard._reference is None and type(guard._canonical_bytes) is bytes
    assert guard.matches(values[base]) is reference.matches(values[base]) is True
    assert guard.matches(value) is reference.matches(value) is True
    assert guard.matches("different") is reference.matches("different") is False


def test_standard_reference_uses_temporary_canonical_thaw_for_unusual_current():
    class Number(float):
        pass
    guard = subject.InputContentGuard({"value": [.25, -0.0]})
    expected = guard._reference
    assert guard._canonical_bytes is None
    assert guard.matches({"value": [Number(.25), Number(-0.0)]})
    assert not guard.matches({"value": [Number(.5), Number(-0.0)]})
    assert not guard.matches({"value": [Number(.25), Number(0.0)]})
    assert not guard.matches({"value": [Number(math.nan), Number(-0.0)]})
    assert guard._reference is expected and guard._canonical_bytes is None


def test_numeric_key_conversion_and_original_numeric_order_match_old_encoder():
    guard = subject.InputContentGuard({"1": "value"})
    assert guard.matches({1: "value"})
    assert not guard.matches({1: "changed"})
    assert not guard.matches({"1": "value", 1: "value"})
    original_value = {2: "two", 10: "ten"}
    guard = subject.InputContentGuard(original_value)
    assert guard.matches(original_value)
    assert not guard.matches({"2": "two", "10": "ten"})


@pytest.mark.parametrize("value", ({"a": object()}, {None: math.nan},
                                  {2: "numeric", "2": "string"}, bytearray(b"x")))
def test_invalid_or_unsortable_unusual_json_constructor_matches_old_refusal(value):
    with pytest.raises((TypeError, ValueError)):
        subject.InputContentGuard(value)
    with pytest.raises((TypeError, ValueError)):
        original.CheckpointContentGuard(value)


@pytest.mark.parametrize("target", ("_raw", "_freeze", "_matches", "_source_sha256",
                                    "inference_implementation", "_ISFINITE"))
def test_helper_replacement_is_refused_even_for_unchanged_content(monkeypatch, target):
    value = _value()
    guard = subject.InputContentGuard(value)
    monkeypatch.setattr(subject, target, lambda *args, **kwargs: True)
    with pytest.raises(ValueError, match="binding changed"):
        guard.matches(value)
    with pytest.raises(ValueError, match="binding changed"):
        subject.InputContentGuard(value)


@pytest.mark.parametrize("target", ("matches", "check", "__init__", "inference_implementation"))
def test_guard_method_replacement_is_refused_by_independent_verifier(monkeypatch, target):
    guard = subject.InputContentGuard(_value())
    replacement = (property(lambda self: {}) if target == "inference_implementation"
                   else lambda *args, **kwargs: True)
    monkeypatch.setattr(subject.InputContentGuard, target, replacement)
    with pytest.raises(ValueError, match="method binding changed"):
        subject.inference_implementation()
    if target != "matches":
        with pytest.raises(ValueError, match="method binding changed"):
            guard.matches(_value())


def test_function_code_mutation_is_refused_by_identity(monkeypatch):
    guard = subject.InputContentGuard(_value())
    replacement = lambda current, expected: True
    monkeypatch.setattr(subject._matches, "__code__", replacement.__code__)
    with pytest.raises(ValueError, match="function binding changed"):
        guard.matches(_value())


def test_mutated_keyword_defaults_are_refused(monkeypatch):
    guard = subject.InputContentGuard(_value())
    monkeypatch.setitem(subject.InputContentGuard.check.__kwdefaults__, "message", "changed")
    with pytest.raises(ValueError, match="method binding changed"):
        guard.matches(_value())


def test_actual_current_source_bytes_are_checked_each_time(tmp_path, monkeypatch):
    module, path = _load_temporary_copy(tmp_path, monkeypatch)
    guard = module.InputContentGuard(_value())
    assert guard.matches(_value())
    path.write_bytes(path.read_bytes() + b"\n# drift in temporary control source\n")
    with pytest.raises(ValueError, match="source changed since import"):
        guard.matches(_value())
    with pytest.raises(ValueError, match="source changed since import"):
        guard.check(_value())
    with pytest.raises(ValueError, match="source changed since import"):
        module.InputContentGuard(_value())


def test_descriptor_mutation_does_not_change_following_receipts():
    receipt = subject.inference_implementation()
    receipt["source_sha256"] = "0" * 64
    assert subject.inference_implementation()["source_sha256"] == subject._SOURCE_AT_IMPORT


def test_old_checkpoint_source_remains_the_known_frozen_implementation():
    # This guard consumes no checkpoint identity or checkpoint digest property.
    source = Path(original.__file__).read_bytes()
    assert hashlib.sha256(source).hexdigest() == "5461672516b4a60938b036d558192e8db328fdd00d20cda76b7448dea09c706c"
    assert "sha256" not in subject.InputContentGuard.__dict__
