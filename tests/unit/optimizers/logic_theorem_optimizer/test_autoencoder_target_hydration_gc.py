"""Private-worker GC deferral preserves target bytes, guards and failure cleanup."""

from __future__ import annotations

import gc
import multiprocessing
import platform
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as bundle_codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import (
    TargetSnapshotConfig, TargetSnapshotError, _encode, _json, build_target_snapshot,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import LegalSample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIRDocument


@pytest.fixture(autouse=True)
def preserve_gc_policy():
    enabled, thresholds, debug = gc.isenabled(), gc.get_threshold(), gc.get_debug()
    callbacks = list(gc.callbacks)
    gc.enable()
    gc.set_debug(0)
    gc.callbacks[:] = []
    try:
        yield
    finally:
        gc.callbacks[:] = callbacks
        gc.set_debug(debug)
        gc.set_threshold(*thresholds)
        (gc.enable if enabled else gc.disable)()


@pytest.fixture
def eligible_worker(monkeypatch):
    # Qualify only the environmental predicates; GC remains the real process GC.
    monkeypatch.setattr(platform, "python_implementation", lambda: "CPython")
    monkeypatch.setattr(multiprocessing, "parent_process", lambda: SimpleNamespace(pid=1234))
    monkeypatch.setattr(multiprocessing, "get_start_method", lambda allow_none=False: "spawn")
    main = threading.main_thread()
    monkeypatch.setattr(threading, "current_thread", lambda: main)
    monkeypatch.setattr(threading, "active_count", lambda: 1)


@pytest.fixture
def target_bundle(tmp_path):
    text = "The agency shall retain records."
    sample = LegalSample(
        sample_id="gc-fixture", source="us_code", title="5", section="gc",
        citation="5 U.S.C. gc", text=text, normalized_text=text,
        embedding_model="mock:gc-fixture", embedding_vector=[0.5, -0.0],
        modal_ir=ModalIRDocument(document_id="gc-fixture", source="us_code", normalized_text=text),
    )
    config = TargetSnapshotConfig(("deontic_norms",), False, 1, {"fixture": "a" * 64})
    document = LegalIRDocument(
        sample.sample_id, text, text, citation=sample.citation,
        views={"deontic.ir": LogicIRView("deontic.ir", {
            "rules": [{"actor": "agency", "amount": -0.0}], "ordered": (2, 1),
        })},
        frame_logic_triples=({"subject": "agency", "predicate": "retains", "object": "records"},),
        metadata={"created_at": "fixed-fixture-time", "nested": {"z": [0.12345678912345678, 1], "a": 2}},
    )
    target = LegalIRTrainingTarget(config.bridge_names, document,
                                   {"legal_ir_multiview_total_loss": 0.25},
                                   {"deontic_norms": {"fixture": 0.125}},
                                   {"deontic.ir": 1.0}, False)
    saved = bundle_codec.write_target_bundle(tmp_path / "fixture.bundle", [(sample, target, None)], config=config)
    with bundle_codec.load_target_bundle(saved["path"], expected_sha256=saved["sha256"], config=config) as bundle:
        yield bundle, [sample], config, target


def test_deferral_preserves_exact_target_and_collects_after_gc_restored(target_bundle, eligible_worker, monkeypatch):
    bundle, members, config, expected = target_bundle
    thresholds = gc.get_threshold()
    decoder, collect = bundle_codec._decode, gc.collect
    events = []

    def decode(raw):
        events.append(("decode", gc.isenabled()))
        return decoder(raw)

    def explicit_collect(generation):
        events.append(("collect", gc.isenabled(), generation))
        return collect(generation)

    monkeypatch.setattr(bundle_codec, "_decode", decode)
    monkeypatch.setattr(gc, "collect", explicit_collect)
    targets, telemetry = worker._hydrate_shared_targets(bundle, members, config, defer_gc=True)
    assert _json(_encode(targets[members[0].sample_id])) == _json(_encode(expected))
    assert targets[members[0].sample_id].document.canonical_hash() == expected.document.canonical_hash()
    assert events == [("decode", False), ("collect", True, 2)]
    assert gc.isenabled() is True
    assert gc.get_threshold() == thresholds
    assert bundle.statistics["closed"] is False
    assert telemetry["policy"] == "defer_during_verified_bundle_hydration_v1"
    assert telemetry["requested"] is telemetry["applied"] is True
    assert telemetry["skip_reason"] is None
    assert telemetry["explicit_collection_performed"] is True
    assert telemetry["gc_enabled_before"] is telemetry["gc_enabled_after"] is True
    assert telemetry["gc_threshold_before"] == telemetry["gc_threshold_after"] == list(thresholds)
    assert telemetry["referenced_uncompressed_bytes"] == bundle.statistics["referenced_uncompressed_target_bytes"]
    assert telemetry["max_referenced_uncompressed_bytes"] == 256 * 1024 * 1024
    assert telemetry["hydrate_seconds"] >= 0
    assert telemetry["collection_seconds"] >= 0
    assert telemetry["total_seconds"] >= telemetry["hydrate_seconds"] + telemetry["collection_seconds"]
    assert len(telemetry["gc_stats_before"]) == len(telemetry["gc_stats_after"]) == len(telemetry["gc_stats_delta"])
    assert telemetry["gc_stats_after"][2]["collections"] >= telemetry["gc_stats_before"][2]["collections"] + 1


@pytest.mark.parametrize("reason", [
    "not_requested", "unsupported_python", "not_spawn_worker", "not_main_thread",
    "other_python_threads", "gc_already_disabled", "gc_debug_enabled", "gc_callbacks_present",
])
def test_ineligible_execution_uses_ordinary_hydration(reason, target_bundle, eligible_worker, monkeypatch):
    bundle, members, config, expected = target_bundle
    requested = reason != "not_requested"
    if reason == "unsupported_python":
        monkeypatch.setattr(platform, "python_implementation", lambda: "PyPy")
    elif reason == "not_spawn_worker":
        monkeypatch.setattr(multiprocessing, "parent_process", lambda: None)
    elif reason == "not_main_thread":
        monkeypatch.setattr(threading, "current_thread", lambda: object())
    elif reason == "other_python_threads":
        monkeypatch.setattr(threading, "active_count", lambda: 2)
    elif reason == "gc_already_disabled":
        gc.disable()
    elif reason == "gc_debug_enabled":
        gc.set_debug(gc.DEBUG_UNCOLLECTABLE)
    elif reason == "gc_callbacks_present":
        gc.callbacks.append(lambda phase, info: None)
    enabled, debug, callbacks, thresholds = gc.isenabled(), gc.get_debug(), list(gc.callbacks), gc.get_threshold()
    decoder = bundle_codec._decode
    states = []

    def decode(raw):
        states.append(gc.isenabled())
        return decoder(raw)

    monkeypatch.setattr(bundle_codec, "_decode", decode)
    monkeypatch.setattr(gc, "collect", lambda *args: pytest.fail("bypass must not force collection"))
    targets, telemetry = worker._hydrate_shared_targets(bundle, members, config, defer_gc=requested)
    assert _json(_encode(targets[members[0].sample_id])) == _json(_encode(expected))
    assert states == [enabled]
    assert gc.isenabled() is enabled
    assert gc.get_debug() == debug and gc.callbacks == callbacks and gc.get_threshold() == thresholds
    assert telemetry["requested"] is requested
    assert telemetry["applied"] is telemetry["explicit_collection_performed"] is False
    assert telemetry["skip_reason"] == reason
    assert telemetry["policy"] == ("defer_during_verified_bundle_hydration_v1" if requested else "default")
    assert telemetry["gc_enabled_before"] is telemetry["gc_enabled_after"] is enabled


@pytest.mark.parametrize("method", ["fork", "forkserver", None])
def test_child_process_without_spawn_bypasses(method, target_bundle, eligible_worker, monkeypatch):
    bundle, members, config, _ = target_bundle
    monkeypatch.setattr(multiprocessing, "get_start_method", lambda allow_none=False: method)
    monkeypatch.setattr(gc, "collect", lambda *args: pytest.fail("non-spawn worker must not collect"))
    _, telemetry = worker._hydrate_shared_targets(bundle, members, config, defer_gc=True)
    assert telemetry["skip_reason"] == "not_spawn_worker"
    assert telemetry["applied"] is False
    assert gc.isenabled() is True


@pytest.mark.parametrize("byte_count, reason", [
    (None, "invalid_expanded_byte_count"), (0, "invalid_expanded_byte_count"),
    (-1, "invalid_expanded_byte_count"), (True, "invalid_expanded_byte_count"),
    (1024.0, "invalid_expanded_byte_count"), ("1024", "invalid_expanded_byte_count"),
    (256 * 1024 * 1024 + 1, "expanded_byte_limit"),
])
def test_invalid_or_large_expansion_bypasses(byte_count, reason, target_bundle, eligible_worker, monkeypatch):
    bundle, members, config, _ = target_bundle
    bundle._statistics["referenced_uncompressed_target_bytes"] = byte_count
    monkeypatch.setattr(gc, "collect", lambda *args: pytest.fail("byte-limit bypass must not collect"))
    _, telemetry = worker._hydrate_shared_targets(bundle, members, config, defer_gc=True)
    assert telemetry["skip_reason"] == reason
    assert telemetry["applied"] is False
    assert gc.isenabled() is True


def test_expansion_cap_is_inclusive(target_bundle, eligible_worker, monkeypatch):
    bundle, members, config, _ = target_bundle
    bundle._statistics["referenced_uncompressed_target_bytes"] = 256 * 1024 * 1024
    collected = []
    monkeypatch.setattr(gc, "collect", lambda generation: collected.append(generation) or 0)
    _, telemetry = worker._hydrate_shared_targets(bundle, members, config, defer_gc=True)
    assert telemetry["applied"] is True
    assert telemetry["referenced_uncompressed_bytes"] == telemetry["max_referenced_uncompressed_bytes"]
    assert collected == [2]


@pytest.mark.parametrize("subclass", [False, True])
def test_custom_snapshot_bypasses_without_observing_statistics(subclass, eligible_worker, monkeypatch):
    marker, members, config = {}, [], object()
    calls = []

    class Custom(bundle_codec.TargetBundle if subclass else object):
        def __init__(self):
            pass

        @property
        def statistics(self):
            pytest.fail("custom snapshot statistics must not be inspected")

        def targets_for(self, samples, *, config):
            calls.append((samples, config, gc.isenabled()))
            return marker

    monkeypatch.setattr(gc, "collect", lambda *args: pytest.fail("custom snapshot must not collect"))
    targets, telemetry = worker._hydrate_shared_targets(Custom(), members, config, defer_gc=True)
    assert targets is marker
    assert calls == [(members, config, True)]
    assert telemetry["skip_reason"] == "unsupported_snapshot"
    assert telemetry["applied"] is False


def test_legacy_json_snapshot_remains_unchanged(target_bundle, eligible_worker, monkeypatch):
    _, members, config, target = target_bundle
    snapshot = build_target_snapshot(members, {members[0].sample_id: target}, config=config)
    monkeypatch.setattr(gc, "collect", lambda *args: pytest.fail("legacy snapshot must not collect"))
    targets, telemetry = worker._hydrate_shared_targets(snapshot, members, config, defer_gc=True)
    assert _json(_encode(targets[members[0].sample_id])) == _json(_encode(target))
    assert telemetry["skip_reason"] == "unsupported_snapshot"


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("error_type", [RuntimeError, TargetSnapshotError, MemoryError, KeyboardInterrupt, SystemExit])
def test_hydration_failure_preserves_exception_and_gc_state(enabled, error_type, target_bundle, eligible_worker, monkeypatch):
    bundle, members, config, _ = target_bundle
    if not enabled:
        gc.disable()
    error = error_type("injected decoder failure")

    def fail(raw):
        assert gc.isenabled() is False
        raise error

    monkeypatch.setattr(bundle_codec, "_decode", fail)
    monkeypatch.setattr(gc, "collect", lambda *args: pytest.fail("failed hydration must not collect"))
    with pytest.raises(error_type) as caught:
        worker._hydrate_shared_targets(bundle, members, config, defer_gc=True)
    assert caught.value is error
    assert gc.isenabled() is enabled
    assert bundle.statistics["closed"] is False


def test_interrupt_during_gc_disable_restores_gc_before_propagating(target_bundle, eligible_worker, monkeypatch):
    bundle, members, config, _ = target_bundle
    error = KeyboardInterrupt("injected interruption after disabling GC")
    disable = gc.disable

    def interrupted_disable():
        disable()
        assert gc.isenabled() is False
        raise error

    monkeypatch.setattr(gc, "disable", interrupted_disable)
    monkeypatch.setattr(bundle_codec, "_decode", lambda raw: pytest.fail("interrupted disable must not hydrate"))
    monkeypatch.setattr(gc, "collect", lambda *args: pytest.fail("interrupted disable must not collect"))
    with pytest.raises(KeyboardInterrupt) as caught:
        worker._hydrate_shared_targets(bundle, members, config, defer_gc=True)
    assert caught.value is error
    assert gc.isenabled() is True
    assert bundle.statistics["closed"] is False


def test_collection_failure_restores_gc_before_propagating(target_bundle, eligible_worker, monkeypatch):
    bundle, members, config, _ = target_bundle
    error = RuntimeError("injected collection failure")

    def fail_collection(generation):
        assert generation == 2 and gc.isenabled() is True
        gc.disable()
        raise error

    monkeypatch.setattr(gc, "collect", fail_collection)
    with pytest.raises(RuntimeError) as caught:
        worker._hydrate_shared_targets(bundle, members, config, defer_gc=True)
    assert caught.value is error
    assert gc.isenabled() is True
    assert bundle.statistics["closed"] is False
