"""Capture observations preserve current actor-aware behavior and expose failures."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import gc
import importlib
import json
from types import ModuleType, SimpleNamespace
import sys
import weakref

import pytest

from ipfs_datasets_py.logic.autoformal import ontology_capture as capture
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_ontology_observation as observation


# Exact original functions from ontology_capture.py SHA256
# 730deb53ac0e2c63d97c1b9fef0d971de917c7feea3953d2054995fdcf54d773.
# Kept outside the package so the reference cannot silently adopt new hooks.
_HISTORICAL = '''
def triples_from_sample(sample: Any) -> list[dict[str, str]]:
    """Frame-logic triples already extracted into the sample. No second parse."""

    modal_ir = getattr(sample, "modal_ir", None)
    frame = getattr(modal_ir, "frame_logic", None)
    raw = []
    if frame is not None and hasattr(frame, "to_triples"):
        try:
            raw = list(frame.to_triples() or [])
        except (TypeError, ValueError, AttributeError):
            raw = []
    triples: list[dict[str, str]] = []
    for item in raw:
        triple = _triple(item)
        if triple is None or triple["predicate"] not in _ONTOLOGY_PREDICATES:
            continue
        triples.append(triple)
        if len(triples) >= 32:
            break
    if triples or modal_ir is None:
        return triples
    try:
        from ipfs_datasets_py.logic.modal.codec import modal_ir_to_flogic_triples

        raw = list(modal_ir_to_flogic_triples(modal_ir) or [])
    except (ImportError, OSError, TypeError, ValueError, AttributeError):
        return []
    for item in raw:
        triple = _triple(item)
        if triple is None or triple["predicate"] not in _ONTOLOGY_PREDICATES:
            continue
        triples.append(triple)
        if len(triples) >= 32:
            break
    return triples


def capture_samples(samples: Sequence[Any]) -> list[dict[str, Any]]:
    from ipfs_datasets_py.logic.autoformal.recipient_reference import recipient_surface_from_sentence

    records = []
    for sample in samples:
        text = str(getattr(sample, "text", "") or "")
        record = ontology_record(
            sample_id=str(getattr(sample, "sample_id", "") or ""),
            text=text,
            triples=triples_from_sample(sample),
        )
        if text and not record["recipient"]["surface"]:
            try:
                surface = recipient_surface_from_sentence(text)
            except (ImportError, OSError, TypeError, ValueError):
                surface = ""
            if surface:
                record["recipient"] = recipient_reference(surface)
        if text and not record["procedure"]["procedure_id"]:
            try:
                from ipfs_datasets_py.logic.autoformal.procedure_slot import procedure_from_sentence

                record["procedure"] = procedure_from_sentence(text)
            except (ImportError, OSError, TypeError, ValueError):
                pass
        records.append(record)
    return records
'''


def _historical():
    namespace = dict(vars(capture))
    exec(compile(_HISTORICAL, "frozen_pre_observer_capture.py", "exec"), namespace)
    return namespace["capture_samples"]


# Actor-aware capture v1, frozen from ontology_capture.py SHA256
# d40e1cffe9e7d127b58eb8fe32829c7fd38c2f92723b705f1c730d4d7ae36b9f,
# with observation hooks removed. The earlier literal and its digest above
# remain the pre-actor historical reference, not the current expected contract.
# triples_from_sample still uses that earlier uninstrumented implementation.
_ACTOR_AWARE_UNINSTRUMENTED_V1 = '''
def capture_samples(samples: Sequence[Any]) -> list[dict[str, Any]]:
    from ipfs_datasets_py.logic.autoformal.recipient_reference import recipient_surface_from_sentence

    records = []
    for sample in samples:
        text = str(getattr(sample, "text", "") or "")
        record = ontology_record(
            sample_id=str(getattr(sample, "sample_id", "") or ""),
            text=text,
            triples=triples_from_sample(sample),
        )
        if text and not record["recipient"]["surface"]:
            try:
                surface = recipient_surface_from_sentence(text)
            except (ImportError, OSError, TypeError, ValueError):
                surface = ""
            if surface:
                record["recipient"] = recipient_reference(surface)
        if text:
            try:
                from ipfs_datasets_py.logic.autoformal.embedded_actor import actor_triples, clause_actors

                actors = clause_actors(text)
            except (ImportError, OSError, TypeError, ValueError):
                actors = []
            record["actors"] = [
                {"surface": actor["surface"], "role": actor["role"], "admitted": False}
                for actor in actors
            ]
            for triple in actor_triples(record["sample_id"], actors):
                if len(record["triples"]) >= 32:
                    break
                if triple not in record["triples"]:
                    record["triples"].append(triple)
        if text and not record["procedure"]["procedure_id"]:
            try:
                from ipfs_datasets_py.logic.autoformal.procedure_slot import procedure_from_sentence

                record["procedure"] = procedure_from_sentence(text)
            except (ImportError, OSError, TypeError, ValueError):
                pass
        records.append(record)
    return records
'''


def _current_uninstrumented():
    namespace = dict(vars(capture))
    exec(compile(_HISTORICAL, "frozen_pre_observer_capture.py", "exec"), namespace)
    exec(compile(_ACTOR_AWARE_UNINSTRUMENTED_V1,
                 "frozen_actor_aware_uninstrumented_v1.py", "exec"), namespace)
    return namespace["capture_samples"]


def _serialized(records):
    return json.dumps(records, ensure_ascii=True, separators=(",", ":"))


def _sample(sample_id="same-id", *, frame=None):
    if frame is None:
        frame = SimpleNamespace(to_triples=lambda: [
            {"subject": "notice", "predicate": "type", "object": "document"},
        ])
    return SimpleNamespace(sample_id=sample_id, text="The agency shall notify the clerk.",
                           modal_ir=SimpleNamespace(frame_logic=frame))


@pytest.fixture
def dependencies(monkeypatch):
    recipient = importlib.import_module("ipfs_datasets_py.logic.autoformal.recipient_reference")
    procedure = importlib.import_module("ipfs_datasets_py.logic.autoformal.procedure_slot")
    monkeypatch.setattr(recipient, "recipient_surface_from_sentence", lambda text: "the clerk")
    monkeypatch.setattr(procedure, "procedure_from_sentence", lambda text: {
        "events": ["notice", "hearing"], "procedure_id": "notice->hearing",
        "surface": "notice -> hearing", "admitted": False,
    })
    codec = ModuleType("ipfs_datasets_py.logic.modal.codec")
    codec.modal_ir_to_flogic_triples = lambda ir: [
        {"subject": "fallback", "predicate": "type", "object": "document"},
    ]
    monkeypatch.setitem(sys.modules, codec.__name__, codec)
    return recipient, procedure, codec


def test_exact_serialized_capture_parity_and_duplicate_order(dependencies):
    samples = [_sample(), _sample(), _sample("third")]
    expected_records = _current_uninstrumented()(samples)
    expected = _serialized(expected_records)
    assert _serialized(capture.capture_samples(samples)) == expected
    with observation.observe_ontology_captures(producer_identity={"kind": "fixture"}) as observer:
        actual = capture.capture_samples(samples)
    assert _serialized(actual) == expected
    for record, historical in zip(actual, _historical()(samples)):
        assert "actors" not in historical
        assert record["actors"] == [{"surface": "agency", "role": "duty", "admitted": False}]
        assert record["triples"] == [
            {"subject": "notice", "predicate": "type", "object": "document"},
            {"subject": "agency", "predicate": "role", "object": "duty"},
            {"subject": record["sample_id"], "predicate": "actor", "object": "agency"},
        ]
        assert historical["triples"] == record["triples"][:1]
        assert record["admitted"] is False
    snapshot = observer.to_dict()
    assert snapshot["reuse_qualified"] is False
    assert snapshot["observations_complete"] is True
    assert snapshot["context_closed"] is True
    assert [r["sample_id"] for r in snapshot["records"]] == ["same-id", "same-id", "third"]
    assert [r["ordinal"] for r in snapshot["records"]] == [0, 1, 2]
    assert all(r["outcome"] == "returned_without_observed_error" for r in snapshot["records"])
    assert snapshot["captures"][0]["returned_record_count"] == 3
    assert snapshot["stage_totals"]["procedure"]["calls"] == 3
    assert snapshot["stage_totals"]["actors"]["calls"] == 3
    assert "transitive" in snapshot["observations_scope"]


def test_absent_observer_never_reads_clock_and_preserves_getter_order(monkeypatch, dependencies):
    calls = []

    class Sample:
        @property
        def text(self):
            calls.append("text")
            return "clause"

        @property
        def sample_id(self):
            calls.append("sample_id")
            return "id"

        @property
        def modal_ir(self):
            calls.append("modal_ir")
            return _sample().modal_ir

    expected = _current_uninstrumented()([Sample()])
    original_calls = list(calls)
    calls.clear()
    monkeypatch.setattr(observation.time, "perf_counter", lambda: pytest.fail("inactive observer clock"))
    assert capture.capture_samples([Sample()]) == expected
    assert calls == original_calls


@pytest.mark.parametrize("stage", ["frame_triples", "fallback_projection", "recipient", "actors", "procedure"])
def test_suppressed_failure_is_observed_and_next_call_recovers(stage, dependencies, monkeypatch):
    recipient, procedure, codec = dependencies
    error = ValueError("message must not be retained")

    def fail(*args):
        raise error

    sample = _sample()
    if stage == "frame_triples":
        sample.modal_ir.frame_logic.to_triples = fail
        restore = lambda: setattr(sample.modal_ir.frame_logic, "to_triples", lambda: [])
    elif stage == "fallback_projection":
        sample.modal_ir.frame_logic.to_triples = lambda: []
        original = codec.modal_ir_to_flogic_triples
        monkeypatch.setattr(codec, "modal_ir_to_flogic_triples", fail)
        restore = lambda: setattr(codec, "modal_ir_to_flogic_triples", original)
    elif stage == "actors":
        module = importlib.import_module("ipfs_datasets_py.logic.autoformal.embedded_actor")
        original = module.clause_actors
        monkeypatch.setattr(module, "clause_actors", fail)
        restore = lambda: setattr(module, "clause_actors", original)
    else:
        module, name = ((recipient, "recipient_surface_from_sentence") if stage == "recipient"
                        else (procedure, "procedure_from_sentence"))
        original = getattr(module, name)
        monkeypatch.setattr(module, name, fail)
        restore = lambda: setattr(module, name, original)
    expected = _current_uninstrumented()([sample])
    assert _serialized(capture.capture_samples([sample])) == _serialized(expected)
    with observation.observe_ontology_captures() as observer:
        assert _serialized(capture.capture_samples([sample])) == _serialized(expected)
        restore()
        assert _serialized(capture.capture_samples([sample])) == _serialized(_current_uninstrumented()([sample]))
    snapshot = observer.to_dict()
    assert snapshot["records"][0]["outcome"] == "returned_with_observed_error"
    assert snapshot["records"][1]["outcome"] == "returned_without_observed_error"
    assert any(e["stage"] == stage and e["exception_type"] == "builtins.ValueError"
               and e["disposition"] == "suppressed" for e in snapshot["errors"])
    assert "message must not be retained" not in json.dumps(snapshot)
    assert snapshot["reuse_qualified"] is False


def test_actor_triples_preserve_existing_duplicates_and_append_order(dependencies):
    role = {"subject": "agency", "predicate": "role", "object": "duty"}
    sort = {"subject": "notice", "predicate": "type", "object": "document"}
    initial = [role, role, sort]
    sample = _sample(frame=SimpleNamespace(to_triples=lambda: initial))
    expected = _current_uninstrumented()([sample])
    assert expected[0]["triples"] == initial + [
        {"subject": "same-id", "predicate": "actor", "object": "agency"},
    ]
    assert _serialized(capture.capture_samples([sample])) == _serialized(expected)
    with observation.observe_ontology_captures():
        assert _serialized(capture.capture_samples([sample])) == _serialized(expected)


@pytest.mark.parametrize("initial_count, appended_predicates", [
    (30, ("role", "actor")), (31, ("role",)), (32, ()),
])
def test_actor_triples_respect_record_cap(initial_count, appended_predicates, dependencies):
    initial = [
        {"subject": f"item-{i}", "predicate": "type", "object": "document"}
        for i in range(initial_count)
    ]
    additions = {
        "role": {"subject": "agency", "predicate": "role", "object": "duty"},
        "actor": {"subject": "same-id", "predicate": "actor", "object": "agency"},
    }
    sample = _sample(frame=SimpleNamespace(to_triples=lambda: initial))
    expected = _current_uninstrumented()([sample])
    assert expected[0]["triples"] == initial + [additions[name] for name in appended_predicates]
    assert len(expected[0]["triples"]) == 32
    assert expected[0]["actors"] == [{"surface": "agency", "role": "duty", "admitted": False}]
    assert _serialized(capture.capture_samples([sample])) == _serialized(expected)
    with observation.observe_ontology_captures():
        assert _serialized(capture.capture_samples([sample])) == _serialized(expected)


@pytest.mark.parametrize("exception", [ValueError("actor projection"), RuntimeError("actor projection")])
def test_actor_projection_exception_identity_and_observation(exception, dependencies, monkeypatch):
    actors = importlib.import_module("ipfs_datasets_py.logic.autoformal.embedded_actor")

    def fail(*args):
        raise exception

    monkeypatch.setattr(actors, "actor_triples", fail)
    sample = _sample()
    with pytest.raises(type(exception)) as reference:
        _current_uninstrumented()([sample])
    with pytest.raises(type(exception)) as unobserved:
        capture.capture_samples([sample])
    with observation.observe_ontology_captures() as observer:
        with pytest.raises(type(exception)) as observed:
            capture.capture_samples([sample])
    assert reference.value is unobserved.value is observed.value is exception
    snapshot = observer.to_dict()
    assert snapshot["records"][0]["outcome"] == "aborted"
    assert snapshot["captures"][0]["returned_record_count"] is None
    assert any(error["stage"] == "actors" and error["disposition"] == "escaped"
               and error["exception_type"] == f"builtins.{type(exception).__name__}"
               for error in snapshot["errors"])
    assert snapshot["reuse_qualified"] is False


@pytest.mark.parametrize("exception", [RuntimeError("uncaught"), KeyboardInterrupt("interrupt")])
def test_uncaught_exception_identity_is_preserved(exception, dependencies):
    def fail():
        raise exception

    sample = _sample(frame=SimpleNamespace(to_triples=fail))
    with pytest.raises(type(exception)) as original:
        _current_uninstrumented()([sample])
    with observation.observe_ontology_captures() as observer:
        with pytest.raises(type(exception)) as actual:
            capture.capture_samples([sample])
    assert original.value is actual.value is exception
    assert observer.to_dict()["records"][0]["outcome"] == "aborted"
    assert observer.to_dict()["captures"][0]["outcome"] == "aborted"


def test_batch_abort_retains_emitted_count_without_claiming_return(dependencies):
    error = TypeError("second sample")

    class Broken:
        @property
        def text(self):
            raise error

    with observation.observe_ontology_captures() as observer:
        with pytest.raises(TypeError) as caught:
            capture.capture_samples([_sample("first"), Broken()])
    assert caught.value is error
    batch = observer.to_dict()["captures"][0]
    assert batch["outcome"] == "aborted"
    assert batch["started_record_count"] == 2
    assert batch["emitted_record_count"] == batch["discarded_record_count"] == 1
    assert batch["returned_record_count"] is None


def test_bound_overflow_is_visible_without_changing_results(dependencies):
    samples = [_sample("a"), _sample("b"), _sample("c")]
    expected = _current_uninstrumented()(samples)
    with observation.observe_ontology_captures(max_batches=1, max_records=1,
                                               max_stages=1, max_errors=1) as observer:
        assert capture.capture_samples(samples) == expected
        assert capture.capture_samples(samples) == expected
    snapshot = observer.to_dict()
    assert snapshot["observations_complete"] is False
    assert len(snapshot["records"]) == len(snapshot["stages"]) == len(snapshot["captures"]) == 1
    assert snapshot["counters"]["records_dropped"] == 5


def test_snapshots_detach_and_do_not_retain_samples(dependencies):
    class Sample:
        pass

    sample = Sample()
    sample.__dict__.update(vars(_sample()))
    reference = weakref.ref(sample)
    identity = {"labels": ["initial"]}
    with observation.observe_ontology_captures(producer_identity=identity) as observer:
        records = capture.capture_samples([sample])
    records[0]["triples"].clear()
    identity["labels"].append("changed")
    first = observer.to_dict()
    first["records"][0]["sample_id"] = "changed"
    first["producer_identity"]["labels"].clear()
    del sample
    gc.collect()
    assert reference() is None
    assert observer.to_dict()["records"][0]["sample_id"] == "same-id"
    assert observer.to_dict()["producer_identity"] == {"labels": ["initial"]}


def test_nested_context_restores_after_exception(dependencies):
    with observation.observe_ontology_captures() as outer:
        capture.capture_samples([_sample("before")])
        with pytest.raises(RuntimeError):
            with observation.observe_ontology_captures() as inner:
                capture.capture_samples([_sample("inner")])
                raise RuntimeError("caller")
        capture.capture_samples([_sample("after")])
    assert [r["sample_id"] for r in outer.to_dict()["records"]] == ["before", "after"]
    assert [r["sample_id"] for r in inner.to_dict()["records"]] == ["inner"]
    assert observation.observation_active() is False


def test_independent_thread_and_task_contexts(dependencies):
    def run(name):
        with observation.observe_ontology_captures() as observer:
            capture.capture_samples([_sample(name)])
        return [r["sample_id"] for r in observer.to_dict()["records"]]

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(run, ["thread-a", "thread-b"])) == [["thread-a"], ["thread-b"]]

    async def task(name):
        with observation.observe_ontology_captures() as observer:
            await asyncio.sleep(0)
            capture.capture_samples([_sample(name)])
        return [r["sample_id"] for r in observer.to_dict()["records"]]

    async def tasks():
        return await asyncio.gather(task("task-a"), task("task-b"))

    assert asyncio.run(tasks()) == [["task-a"], ["task-b"]]


def test_observer_clock_failure_does_not_change_capture(dependencies, monkeypatch):
    expected = _current_uninstrumented()([_sample()])

    def fail():
        raise ValueError("broken diagnostic clock")

    monkeypatch.setattr(observation.time, "perf_counter", fail)
    with observation.observe_ontology_captures() as observer:
        assert capture.capture_samples([_sample()]) == expected
    assert observer.to_dict()["observations_complete"] is False
    assert observer.to_dict()["counters"]["instrumentation_errors"] > 0
