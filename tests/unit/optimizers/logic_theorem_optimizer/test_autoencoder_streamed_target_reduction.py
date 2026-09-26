"""Synthetic full-target lifetime/parity checks; no native training qualification."""
from __future__ import annotations

import gc
import json
import multiprocessing
from pathlib import Path
import platform
import struct
import threading
from types import MappingProxyType, SimpleNamespace
import weakref

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import _autoencoder_prepared_targets as reduced
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as bundle_codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import (
    RichLegalIRTarget, TargetSnapshotConfig, TargetSnapshotError, _encode, _json,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import LegalSample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIRDocument


@pytest.fixture(autouse=True)
def no_native_or_model_work(monkeypatch):
    import socket
    import subprocess
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal

    def forbidden(*args, **kwargs):
        raise AssertionError("streaming fixture must not start native/model/network work")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(modal.AdaptiveModalAutoencoder, "train_generalizable_projection", forbidden)
    monkeypatch.setattr(modal.AdaptiveModalAutoencoder, "evaluate", forbidden)


@pytest.fixture
def isolated_gc(monkeypatch):
    enabled, thresholds, debug = gc.isenabled(), gc.get_threshold(), gc.get_debug()
    callbacks = list(gc.callbacks)
    gc.enable()
    gc.set_debug(0)
    gc.callbacks[:] = []
    monkeypatch.setattr(platform, "python_implementation", lambda: "CPython")
    monkeypatch.setattr(multiprocessing, "parent_process", lambda: SimpleNamespace(pid=1))
    monkeypatch.setattr(multiprocessing, "get_start_method", lambda allow_none=False: "spawn")
    main = threading.main_thread()
    monkeypatch.setattr(threading, "current_thread", lambda: main)
    monkeypatch.setattr(threading, "active_count", lambda: 1)
    try:
        yield
    finally:
        gc.callbacks[:] = callbacks
        gc.set_debug(debug)
        gc.set_threshold(*thresholds)
        (gc.enable if enabled else gc.disable)()


@pytest.fixture
def make_bundle(tmp_path):
    def make(*, rich_index=None, count=3):
        config = TargetSnapshotConfig(("deontic_norms",), False, 1, {"synthetic": "a" * 64})
        samples, targets = [], {}
        for index in range(count):
            sample_id, text = f"stream-{index}", f"The agency shall retain record {index}."
            sample = LegalSample(
                sample_id, "us_code", "5", str(index), f"5 U.S.C. {index}", text, text,
                "mock:streamed-target", [0.5, -0.0], ModalIRDocument(sample_id, "us_code", text))
            document = LegalIRDocument(
                sample_id, text, text, source="us_code", citation=sample.citation,
                views={"deontic.ir": LogicIRView("deontic.ir", {"ordered": (2, 1), "zero": -0.0})},
                metadata={"created_at": "fixed-synthetic-time", "order": {"z": index, "a": 2}})
            target = LegalIRTrainingTarget(
                config.bridge_names, document,
                {"legal_ir_multiview_total_loss": 0.25, "integer": index, "zero": -0.0},
                {"deontic_norms": {"loss": 0.125}}, {"deontic.ir": 1.0}, False)
            if index == rich_index:
                target = RichLegalIRTarget({**vars(target), "candidate_ir": {
                    "family": "deontic", "rules": [{"modality": "invalid", "subject": "agency", "action": "retain"}]}})
            samples.append(sample)
            targets[sample_id] = target
        descriptor = bundle_codec.write_target_bundle(
            tmp_path / f"targets-{count}-{rich_index}.bundle",
            [(sample, targets[sample.sample_id], "ready") for sample in samples], config=config)
        return descriptor, samples, config, targets
    return make


def _open(descriptor, config):
    return bundle_codec.load_target_bundle(
        descriptor["path"], expected_sha256=descriptor["sha256"], config=config)


def _run(bundle, samples, config, *, deferred=False, prepare=None):
    return worker._stream_reduced_shared_targets(
        bundle, samples, config, defer_gc=deferred,
        prepare=prepare or reduced._prepare_native_targets)


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 0, 1), (1,)])
@pytest.mark.parametrize("deferred", [False, True])
def test_streamed_capsules_equal_full_reduction_and_payload(make_bundle, isolated_gc, order, deferred):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import _legal_ir_target_payload

    descriptor, samples, config, originals = make_bundle()
    samples = [samples[index] for index in order]
    raw_before = Path(descriptor["path"]).read_bytes()
    with _open(descriptor, config) as bundle:
        full = bundle.targets_for(samples, config=config)
        expected, previous = reduced._prepare_native_targets(full)
        before_count = bundle.statistics["decompressed_shards"]
        actual, gc_result, telemetry = _run(bundle, samples, config, deferred=deferred)
        assert actual == expected and previous["applied"] is telemetry["applied"] is True
        assert list(actual) == [sample.sample_id for sample in samples]
        assert type(actual) is MappingProxyType
        assert _legal_ir_target_payload(samples, legal_ir_targets=actual) == _legal_ir_target_payload(samples, legal_ir_targets=full)
        assert bundle.statistics["decompressed_shards"] - before_count == 2 * len(samples)
        stream = telemetry["streaming"]
        assert stream["decoded_target_count"] == 2 * len(samples)
        assert stream["validation_pass_targets"] == stream["conversion_pass_targets"] == len(samples)
        assert not stream["fallback_full_hydration"]
        assert stream["native_performance_qualified"] is stream["validation_authority"] is False
        assert gc_result["streamed_operation_count"] == len(samples) + 1
        assert gc_result["explicit_collection_count"] == (len(samples) + 1 if deferred else 0)
        assert gc_result["total_seconds"] == pytest.approx(stream["validation_pass_seconds"] + stream["conversion_hydration_seconds"])
        assert stream["total_seconds"] >= gc_result["total_seconds"]
        for sample_id, target in actual.items():
            assert target.document.canonical_hash() == originals[sample_id].document.canonical_hash()
            assert struct.pack("!d", target.losses["zero"]) == struct.pack("!d", -0.0)
            with pytest.raises(TypeError):
                target.losses["integer"] = 9
    assert Path(descriptor["path"]).read_bytes() == raw_before


def test_streaming_releases_each_graph_before_next_decode(make_bundle, isolated_gc, monkeypatch, record_property):
    descriptor, samples, config, _ = make_bundle()
    decoder, references, maximum = bundle_codec._decode, [], [0]

    def observe(raw):
        target = decoder(raw)
        references.append(weakref.ref(target))
        maximum[0] = max(maximum[0], sum(ref() is not None for ref in references))
        return target

    monkeypatch.setattr(bundle_codec, "_decode", observe)
    with _open(descriptor, config) as bundle:
        actual, gc_result, result = _run(bundle, samples, config)
        record_property("streaming_synthetic_observation", json.dumps({
            "scope": "synthetic fixture; structural lifetime only, no RSS/native speed qualification",
            "max_live_decoded_targets": maximum[0], "reduction": result, "gc": gc_result,
        }, sort_keys=True))
        assert result["applied"] and len(actual) == 3
        assert len(references) == 6 and maximum == [1]
        assert all(ref() is None for ref in references)
        references.clear()
        maximum[0] = 0
        full = bundle.targets_for(samples, config=config)
        assert maximum == [3] and all(ref() is not None for ref in references)
        del full
        assert all(ref() is None for ref in references)


@pytest.mark.parametrize("rich_index", [0, 2])
def test_ineligible_full_fallback_never_converts_earlier_native_targets(make_bundle, isolated_gc, monkeypatch, rich_index):
    descriptor, samples, config, _ = make_bundle(rich_index=rich_index)
    calls = []
    original = reduced._prepare_native_targets

    def prepare(targets):
        calls.append(targets)
        result = original(targets)
        assert result[0] is targets
        return result

    with _open(descriptor, config) as bundle:
        expected = bundle.targets_for(samples, config=config)
        before = bundle.statistics["decompressed_shards"]
        actual, _, result = _run(bundle, samples, config, prepare=prepare)
        assert len(calls) == 1 and actual is calls[0]
        assert [_json(_encode(value)) for value in actual.values()] == [_json(_encode(value)) for value in expected.values()]
        assert type(actual[samples[rich_index].sample_id]) is RichLegalIRTarget
        assert result["applied"] is False and result["prepared_target_count"] == 0
        assert result["streaming"]["fallback_full_hydration"] is True
        assert result["streaming"]["conversion_pass_targets"] == 0
        assert result["streaming"]["fallback_hydrated_targets"] == 3
        assert bundle.statistics["decompressed_shards"] - before == 6


@pytest.mark.parametrize("rich_index", [None, 0])
@pytest.mark.parametrize("deferred", [False, True])
def test_late_decode_error_precedes_any_reducer_error(make_bundle, isolated_gc, monkeypatch, rich_index, deferred):
    descriptor, samples, config, _ = make_bundle(rich_index=rich_index)
    decoder, calls = bundle_codec._decode, []
    failure = TargetSnapshotError("synthetic invalid final selected target")

    def decode(raw):
        calls.append("decode")
        if len(calls) == 3:
            raise failure
        return decoder(raw)

    def fail_reduce(targets):
        pytest.fail("no reduction may run before complete first-pass validation")

    monkeypatch.setattr(bundle_codec, "_decode", decode)
    with _open(descriptor, config) as bundle, pytest.raises(TargetSnapshotError) as raised:
        _run(bundle, samples, config, deferred=deferred, prepare=fail_reduce)
    assert raised.value is failure and calls == ["decode"] * 3
    assert gc.isenabled()


@pytest.mark.parametrize("deferred", [False, True])
def test_reducer_error_propagates_after_all_validation_and_gc_restoration(make_bundle, isolated_gc, deferred):
    descriptor, samples, config, _ = make_bundle()
    failure, calls = RuntimeError("synthetic reducer hash failure"), []
    with _open(descriptor, config) as bundle:
        def fail_reduce(targets):
            calls.append((bundle.statistics["decompressed_shards"], gc.isenabled()))
            raise failure
        with pytest.raises(RuntimeError) as raised:
            _run(bundle, samples, config, deferred=deferred, prepare=fail_reduce)
        assert raised.value is failure
        assert calls == [(4, True)] and gc.isenabled()
        assert bundle.statistics["closed"] is False


def test_hashing_stays_outside_deferred_gc_and_collections_are_counted(make_bundle, isolated_gc, monkeypatch):
    descriptor, samples, config, _ = make_bundle()
    states, collections = [], []
    original, collect = reduced._prepare_native_targets, gc.collect

    def prepare(targets):
        states.append(gc.isenabled())
        return original(targets)

    def collecting(generation):
        collections.append((generation, gc.isenabled()))
        return collect(generation)

    monkeypatch.setattr(gc, "collect", collecting)
    with _open(descriptor, config) as bundle:
        _, telemetry, _ = _run(bundle, samples, config, deferred=True, prepare=prepare)
    assert states == [True] * 3 and collections == [(2, True)] * 4
    assert telemetry["explicit_collection_count"] == 4


def test_original_disabled_gc_remains_disabled_without_forced_collection(make_bundle, isolated_gc, monkeypatch):
    descriptor, samples, config, _ = make_bundle()
    monkeypatch.setattr(gc, "collect", lambda *args: pytest.fail("disabled GC must not force collection"))
    gc.disable()
    with _open(descriptor, config) as bundle:
        _, telemetry, result = _run(bundle, samples, config, deferred=True)
    assert result["applied"] and not gc.isenabled()
    assert telemetry["applied"] is False
    assert telemetry["streamed_skip_reasons"] == ["gc_already_disabled"] * 4


@pytest.mark.parametrize("when", ["between_passes", "conversion", "final_exhaustion"])
def test_artifact_mutation_prevents_returning_capsules(make_bundle, isolated_gc, monkeypatch, when):
    descriptor, samples, config, _ = make_bundle()
    original, calls = reduced._native_classes_unchanged, []

    def changed():
        calls.append(None)
        if len(calls) == {"between_passes": 1, "conversion": 2, "final_exhaustion": 4}[when]:
            with Path(descriptor["path"]).open("ab") as handle:
                handle.write(b"corruption")
        return original()

    monkeypatch.setattr(reduced, "_native_classes_unchanged", changed)
    with _open(descriptor, config) as bundle, pytest.raises(TargetSnapshotError, match="changed"):
        _run(bundle, samples, config)


def test_late_reducer_ineligibility_discards_all_capsules_then_full_fallback(make_bundle, isolated_gc):
    descriptor, samples, config, _ = make_bundle()
    original, calls = reduced._prepare_native_targets, []

    def prepare(targets):
        calls.append(len(targets))
        if len(calls) == 2:
            return targets, {"applied": False, "skip_reason": "synthetic_runtime_drift",
                             "original_target_count": 1, "prepared_target_count": 0,
                             "preparation_seconds": 0.0, "hash_seconds": 0.0}
        if len(targets) == 3:
            # The complete fallback result is authoritative for this helper;
            # keep full objects exactly as an ineligible native contract does.
            return targets, {"applied": False, "skip_reason": "synthetic_runtime_drift",
                             "original_target_count": 3, "prepared_target_count": 0,
                             "preparation_seconds": 0.0, "hash_seconds": 0.0}
        return original(targets)

    with _open(descriptor, config) as bundle:
        actual, _, telemetry = _run(bundle, samples, config, prepare=prepare)
        assert calls == [1, 1, 3]
        assert all(type(target) is LegalIRTrainingTarget for target in actual.values())
        assert not telemetry["applied"] and telemetry["streaming"]["fallback_full_hydration"]
        assert telemetry["streaming"]["decoded_target_count"] == 8


@pytest.mark.parametrize("reason", ["injected_trainer", "unsupported_snapshot", "not_spawn_worker", "not_main_thread", "other_python_threads"])
def test_original_worker_reduction_environment_guards_remain(reason, make_bundle, isolated_gc, monkeypatch):
    descriptor, _, config, _ = make_bundle()
    with _open(descriptor, config) as bundle:
        snapshot, trainer = bundle, None
        if reason == "injected_trainer":
            trainer = object()
        elif reason == "unsupported_snapshot":
            snapshot = object()
        elif reason == "not_spawn_worker":
            monkeypatch.setattr(multiprocessing, "parent_process", lambda: None)
        elif reason == "not_main_thread":
            monkeypatch.setattr(threading, "current_thread", lambda: object())
        else:
            monkeypatch.setattr(threading, "active_count", lambda: 2)
        assert worker._target_reduction_skip_reason(snapshot, trainer) == reason


def test_changed_native_class_contract_uses_identical_full_fallback(make_bundle, isolated_gc, monkeypatch):
    descriptor, samples, config, _ = make_bundle()

    def forbidden(self):
        pytest.fail("ineligible class serializer must not be invoked")

    monkeypatch.setattr(LegalIRTrainingTarget, "to_dict", forbidden)
    with _open(descriptor, config) as bundle:
        actual, _, result = _run(bundle, samples, config)
        assert all(type(target) is LegalIRTrainingTarget for target in actual.values())
        assert result["applied"] is False
        assert result["skip_reason"] == "native_class_contract_changed"
        assert result["streaming"]["fallback_full_hydration"]
        assert result["streaming"]["conversion_pass_targets"] == 0
        assert bundle.statistics["decompressed_shards"] == 6
