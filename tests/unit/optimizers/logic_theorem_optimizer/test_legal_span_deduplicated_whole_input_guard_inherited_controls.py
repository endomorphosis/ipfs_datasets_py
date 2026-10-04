"""Complete inherited CG8 controls for the separate inventory-dedup candidate.

This is a new copy of all 212 held CG8 cases, adapted only to the new subject
module/class names. The held test file and original candidate remain unchanged.

The 768D parent progress and Adam moments are authored protocol data; its child
has zero updates. The 4096D fixture is explicitly synthetic and untrained.
Only the root executes CPU/model controls. No native encoder, training, CUDA
performance or production selection is established by these portable cases.
"""
from contextlib import contextmanager
from copy import deepcopy
from collections import UserList, UserDict
import ast
import hashlib
import inspect
from pathlib import Path
import sys
import threading
import time

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_deduplicated_whole_input_guard_device_inference as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dims
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096 as head
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_device_inference as resident
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_device_bitwise_inference as baseline768
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_4096_bitwise_device_inference_v2 as baseline4096
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import input_content_guard as input_guard
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import checkpoint_content_guard as checkpoint_guard
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources

_INPUT_CTOR = input_guard.InputContentGuard.__init__.__code__
_INPUT_FREEZE = input_guard._freeze.__code__
_CP_CTOR = checkpoint_guard.CheckpointContentGuard.__init__.__code__
_RESTORE_CODES = (resident._restore.__code__, baseline4096.inherited._RESTORE_AT_IMPORT.__code__)


@pytest.fixture(scope="module", autouse=True)
def one_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)

def authored_moments(state):
    return {"schema": "adam-default-betas-eps/v1", "parameters": {
        name: {"step": 1, "exp_avg": torch.zeros_like(torch.tensor(value)).tolist(),
               "exp_avg_sq": torch.zeros_like(torch.tensor(value)).tolist()} for name, value in state.items()}}

@pytest.fixture(scope="module", params=[768, 4096])
def checkpoint(request):
    dimension = request.param
    if dimension == 4096:
        examples = [{"id": "authored-zero-fit-cadence4096", "source_text": "Lark must retain books.",
            "latent": [.1] * 4096, "canonical_ir": {"rules": [{"actor": "Lark", "modality": "O",
                "action": "retain", "object": "books", "conditions": [], "exceptions": [], "temporal": []}]}}]
        context = {"dimension": 4096, "representation_id": "synthetic-cadence4096-zero-fit-control",
                   "producer_sha256": "a" * 64, "training_index_sha256": "b" * 64}
        return head.build_synthetic_fixture(examples, context_contract=context, hidden_size=8,
            embedding_dim=4, projection_width=4, batch_size=1, seed=1729)
    base_config = span._config(latent_dimension=0, latent_enabled=False, learning_rate=.003,
        batch_size=1, seed=1729, hidden_size=8, embedding_dim=4, projection_width=4, residual_scale=.25)
    base = resident._fresh_model(torch, base_config)
    base_state = {name: value.detach().tolist() for name, value in base.state_dict().items()}
    parent = {"schema": span.SCHEMA, "lineage_id": span.LINEAGE_ID, "config": base_config,
        "implementation": span._implementation(), "training_manifest_sha256": "a" * 64,
        "training_count": 1, "tuning_manifest_sha256": "b" * 64, "tuning_count": 0,
        "model_state": base_state, "optimizer_state": authored_moments(base_state),
        "progress": {"epochs_completed": 1, "row_cursor": 0, "optimizer_steps": 1},
        "parent_checkpoint_sha256": "c" * 64, **span.FALSE}
    config = dims._config(latent_dimension=768, latent_enabled=True, learning_rate=.003,
        batch_size=1, seed=1729, hidden_size=8, embedding_dim=4, projection_width=4, residual_scale=.25)
    model = resident._fresh_model(torch, config)
    state = {name: value.detach().tolist() for name, value in model.state_dict().items()}
    state.update(deepcopy(base_state))
    context = {"dimension": 768, "representation_id": "synthetic-cadence768-zero-fit-control",
               "producer_sha256": "d" * 64, "training_index_sha256": "e" * 64}
    return {"schema": dims.SCHEMA, "lineage_id": dims.LINEAGE_ID,
        "implementation": dims._implementation(), "initialization": deepcopy(dims._INITIALIZATION),
        "config": config, "context_contract": context, "context_contract_sha256": span.checkpoint_digest(context),
        "source_parent_checkpoint": parent, "source_parent_checkpoint_sha256": span.checkpoint_digest(parent),
        "source_parent_optimizer_steps": 1, "initial_source_model_sha256": span.checkpoint_digest(dims._source_state(state)),
        "initial_model_state_sha256": span.checkpoint_digest(state), "training_manifest_sha256": "f" * 64,
        "training_count": 1, "tuning_manifest_sha256": "a" * 64, "tuning_count": 0, "model_state": state,
        "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, **span.FALSE}

@pytest.fixture
def scheduler(tmp_path):
    return resources.GlobalResourceScheduler(resources.ResourceSchedulerConfig(state_path=tmp_path / "state.json",
        total_cpu_slots=3, total_memory_mb=8192, total_gpu_memory_mb=2048, total_unified_memory_mb=8192,
        lane_reservations={}, auto_renew_leases=False,
        resource_pressure_sampler=lambda: {"gpu_telemetry_available": True, "cuda_available": False,
            "gpu_device_count": 0, "gpu_memory_percent": 0.}))

def dimension(checkpoint):
    return checkpoint["config"]["latent_dimension"]

def inputs(checkpoint, count=2):
    return (["Lark must retain the café records."] * count,
            [[.1 + index / 100] * dimension(checkpoint) for index in range(count)])


def api(cp, *, baseline=False):
    if dimension(cp) == 768:
        return baseline768.DeviceBitwiseDimensionalSpanSession if baseline else subject.DeduplicatedWholeInputDeviceDimensionalSpanSession
    return baseline4096.BitwiseDeviceLeanstral4096SpanSession if baseline else subject.DeduplicatedWholeInputDeviceLeanstral4096SpanSession


def open_cpu(cp, scheduler, monkeypatch, *, optimized=True, baseline=False, **kwargs):
    if optimized:
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    options = {"synthetic_unreceipted": True} if dimension(cp) == 4096 else {}
    return api(cp, baseline=baseline)(cp, expected_checkpoint_sha256=span.checkpoint_digest(cp),
        scheduler=scheduler, optimized=optimized, **options, **kwargs)


@contextmanager
def observe(session=None, *, cancellation=None):
    previous = sys.getprofile()
    forward = session._model.forward.__func__.__code__ if session is not None else None
    poll_codes = (resident.DeviceDimensionalSpanSession._poll.__code__,
                  baseline4096.inherited.DeviceLeanstral4096SpanSession._poll.__code__)
    counts = dict.fromkeys(("forward", "poll", "restores", "outer_checkpoint_guard", "other_checkpoint_guards",
                           "input_guards", "input_freeze"), 0)
    def callback(frame, event, arg):
        if event == "call":
            code = frame.f_code
            if code is forward:
                counts["forward"] += 1
            if any(code is expected for expected in poll_codes):
                counts["poll"] += 1
            if any(code is expected for expected in _RESTORE_CODES):
                counts["restores"] += 1
            if code is _INPUT_CTOR:
                counts["input_guards"] += 1
            if code is _INPUT_FREEZE:
                counts["input_freeze"] += 1
            if code is _CP_CTOR:
                value = frame.f_locals.get("checkpoint")
                outer = type(value) is dict and set(value) == {"texts", "vectors", "receipts", "receipt_pins"}
                counts["outer_checkpoint_guard" if outer else "other_checkpoint_guards"] += 1
        elif event == "return" and frame.f_code is _INPUT_CTOR and cancellation is not None:
            if cancellation.guard is None:
                cancellation.guard = frame.f_locals["self"]
        if previous is not None:
            previous(frame, event, arg)
    try:
        sys.setprofile(callback)
        yield counts
    finally:
        sys.setprofile(previous)


def guarded_logits(session, texts, vectors):
    start = len(session._observations)
    with session._operation():
        session._check()
        try:
            records = [{"tokens": span.tokenize_source(text), "latent": vector} for text, vector in zip(texts, vectors)]
            with torch.inference_mode():
                values = session._model(*span._batch(session._tensor_factory, records), enabled=True)
            session._synchronize()
            session._check()
            return {name: value.detach().cpu().clone() for name, value in values.items()}
        finally:
            session._synchronize()
            del session._observations[start:]


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("ablation", ["none", "zero", "rotate", "disabled"])
def test_complete_cpu_rows_four_logits_inputs_checkpoint_rng_and_profiles_match_held_parent(checkpoint, scheduler, monkeypatch, optimized, ablation):
    texts, vectors = inputs(checkpoint)
    before, rng = span._raw(checkpoint), torch.get_rng_state().clone()
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=optimized, baseline=True) as baseline:
        expected = baseline.infer(texts, vectors, latent_ablation=ablation)
        expected_logits = guarded_logits(baseline, texts, vectors)
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=optimized) as owner:
        actual = owner.infer(texts, vectors, latent_ablation=ablation)
        actual_logits = guarded_logits(owner, texts, vectors)
        for name in ("rows", "actual_forward_batches", "input_receipts", "schema", "checkpoint_sha256", "latent_ablation"):
            assert actual[name] == expected[name]
        assert set(actual_logits) == set(expected_logits) == {"modality", "presence", "start", "end"}
        assert all(torch.equal(actual_logits[name], expected_logits[name]) for name in actual_logits)
        assert actual["input_dimension"] == dimension(checkpoint) and actual["cuda_executed"] is False
        assert all(actual[name] is False for name in span.FALSE)
        profile = actual["execution_profile"]
        candidate = subject.PROFILE_768 if dimension(checkpoint) == 768 else subject.PROFILE_4096
        assert profile["whole_input_guard_profile_id"] == profile["session_profile_id"] == candidate
        assert profile["whole_input_guard_inherited_profile_id"] == expected["execution_profile"]["profile_id"]
        assert profile["profile_id"] == (candidate if optimized else expected["execution_profile"]["profile_id"])
        current = profile["whole_input_guard_currentness"]
        assert current["guard_object_and_immutable_snapshot_identities_checked"] is True
        assert current["nested_reference_wrapper_field_identities_checked"] is True
        assert current["fast_comparison"] is True and current["atom_array_scalar_reference_nodes_traversed"] is False
        assert "whole_input_guard_currentness" not in owner.describe()
        assert owner.checkpoint == checkpoint and torch.equal(rng, torch.get_rng_state())
    assert span._raw(checkpoint) == before and scheduler.active_leases() == []


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("count", [1, 16, 32])
def test_only_one_outer_constructor_changes_and_every_parent_poll_row_cache_and_result_guard_remains(checkpoint, scheduler, monkeypatch, optimized, count):
    texts, vectors = inputs(checkpoint, count)
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=optimized, baseline=True) as baseline:
        with observe(baseline) as old:
            baseline.infer(texts, vectors)
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=optimized) as owner:
        with observe(owner) as current:
            owner.infer(texts, vectors)
        assert current["poll"] == old["poll"] == (4 + 2 * count if optimized else 2 + 2 * count)
        assert current["forward"] == old["forward"] == (1 if optimized else count)
        assert old["outer_checkpoint_guard"] == current["input_guards"] == 1
        assert current["outer_checkpoint_guard"] == old["input_guards"] == 0
        assert current["other_checkpoint_guards"] == old["other_checkpoint_guards"]
        assert current["restores"] == old["restores"] == 0
        assert current["input_freeze"] == count + 5


class Mutation:
    def __init__(self, owner, texts, vectors, *, phase, action):
        self.owner, self.texts, self.vectors = owner, texts, vectors
        self.phase, self.action, self.guard, self.triggered = phase, action, None, False
        self.restore = lambda: None

    def is_set(self):
        if self.guard is not None and not self.triggered and (self.phase == "entry" or bool(self.owner._observations)):
            self.triggered = True
            self.action(self)
        return False

    def current(self):
        return {"texts": list(self.texts), "vectors": [span._vector(row, len(row)) for row in self.vectors],
                "receipts": None, "receipt_pins": None}


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("phase", ["entry", "after_forward"])
@pytest.mark.parametrize("fault", ["root_equal", "root_paired", "canonical", "fast", "all_fields_paired",
    "nested_items_paired", "nested_fields_paired", "nested_keys_equal", "nested_atoms"])
def test_guard_and_nested_immutable_wrapper_identity_tampering_cannot_bless_paired_caller_changes(checkpoint, scheduler, monkeypatch, optimized, phase, fault):
    texts, vectors = inputs(checkpoint, 1)
    def action(cancel):
        guard = cancel.guard
        saved = guard._reference, guard._canonical_bytes, guard._use_fast_comparison
        if fault.startswith("nested_"):
            root = guard._reference
            vector = dict(root.fields)["vectors"].items[0]
            field, target = ("items", vector) if fault == "nested_items_paired" else ("fields", root) if fault == "nested_fields_paired" else ("keys", root) if fault == "nested_keys_equal" else ("atoms", vector)
            initial = getattr(target, field)
            cancel.restore = lambda: object.__setattr__(target, field, initial)
            if fault in ("nested_items_paired", "nested_fields_paired"):
                cancel.vectors[0][0] += .25
                other = input_guard.InputContentGuard(cancel.current())
                replacement = dict(other._reference.fields)["vectors"].items[0].items if field == "items" else other._reference.fields
            elif field == "keys":
                replacement = frozenset(list(initial))
            else:
                replacement = not initial
            assert replacement is not initial
            object.__setattr__(target, field, replacement)
            if fault in ("nested_items_paired", "nested_fields_paired"):
                assert guard.matches(cancel.current()) is True
        else:
            def restore():
                for name, value in zip(("_reference", "_canonical_bytes", "_use_fast_comparison"), saved):
                    object.__setattr__(guard, name, value)
            cancel.restore = restore
            if fault in ("root_paired", "all_fields_paired"):
                cancel.vectors[0][0] += .25
            other = input_guard.InputContentGuard(cancel.current())
            if fault in ("root_equal", "root_paired"):
                object.__setattr__(guard, "_reference", other._reference)
            elif fault == "canonical":
                object.__setattr__(guard, "_canonical_bytes", b"{}")
            elif fault == "fast":
                object.__setattr__(guard, "_use_fast_comparison", False)
            else:
                for name in ("_reference", "_canonical_bytes", "_use_fast_comparison"):
                    object.__setattr__(guard, name, getattr(other, name))
                assert guard.matches(cancel.current()) is True
    cancel = Mutation(None, texts, vectors, phase=phase, action=action)
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=optimized, cancel_event=cancel) as owner:
        cancel.owner = owner
        try:
            with observe(owner, cancellation=cancel) as counts:
                with pytest.raises(ValueError, match="whole-input independent local guard or immutable snapshot changed"):
                    owner.infer(texts, vectors)
            assert cancel.triggered and (counts["forward"] > 0 if phase == "after_forward" else True)
            assert not owner._active and not owner._observations
        finally:
            cancel.restore()
        owner.describe()


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("fault", ["finite", "signed_zero", "text", "nan"])
def test_actual_caller_alias_changes_after_forward_refuse_with_original_message(checkpoint, scheduler, monkeypatch, optimized, fault):
    texts, vectors = inputs(checkpoint, 1)
    if fault == "signed_zero":
        vectors[0][0] = 0.
    def action(cancel):
        if fault == "text":
            texts[0] += " extra café clause"
        else:
            vectors[0][0] = .75 if fault == "finite" else -0. if fault == "signed_zero" else float("nan")
    cancel = Mutation(None, texts, vectors, phase="after_forward", action=action)
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=optimized, cancel_event=cancel) as owner:
        cancel.owner = owner
        with observe(owner, cancellation=cancel) as counts:
            with pytest.raises(ValueError):
                owner.infer(texts, vectors)
        assert cancel.triggered and counts["forward"] > 0 and not owner._active and not owner._observations


@pytest.mark.parametrize("fault", ["source_hash", "helper_class", "helper_matches", "helper_check", "helper_defaults",
    "helper_function", "source_checker", "owner_checker", "decode_namespace", "decode_code", "wrapped_method_code",
    "base_constructor", "profile", "private_decision"])
@pytest.mark.parametrize("phase", ["constructor", "after_forward"])
def test_live_source_callable_code_default_class_namespace_and_owner_dispatch_changes_refuse(checkpoint, scheduler, monkeypatch, fault, phase):
    def mutate(owner=None):
        foreign = lambda *args, **kwargs: None
        decode = subject._DECODE_768 if dimension(checkpoint) == 768 else subject._DECODE_4096
        if fault == "source_hash": monkeypatch.setattr(subject, "_HASH", foreign)
        elif fault == "helper_class": monkeypatch.setattr(input_guard, "InputContentGuard", object)
        elif fault == "helper_matches": monkeypatch.setattr(input_guard.InputContentGuard, "matches", foreign)
        elif fault == "helper_check": monkeypatch.setattr(input_guard.InputContentGuard, "check", foreign)
        elif fault == "helper_defaults": monkeypatch.setattr(input_guard.InputContentGuard.check, "__kwdefaults__", {"message": "changed"})
        elif fault == "helper_function": monkeypatch.setattr(input_guard, "_matches", foreign)
        elif fault == "source_checker": monkeypatch.setattr(subject, "_check_bindings", foreign)
        elif fault == "owner_checker": monkeypatch.setattr(subject, "_check_owner", foreign)
        elif fault == "decode_namespace": monkeypatch.setitem(decode.__globals__, "_INPUT_GUARD", object)
        elif fault == "decode_code": monkeypatch.setattr(decode, "__code__", foreign.__code__)
        elif fault == "wrapped_method_code":
            method = api(checkpoint).decode_formal_logic.__wrapped__
            monkeypatch.setattr(method, "__code__", method.__code__.replace(co_consts=method.__code__.co_consts + (None,)))
        elif fault == "base_constructor":
            base = subject._BASE_768 if dimension(checkpoint) == 768 else subject._BASE_4096
            monkeypatch.setattr(base, "__init__", foreign)
        elif fault == "profile": monkeypatch.setattr(subject, "PROFILE_4096", "changed/v1")
        elif owner is None: monkeypatch.setattr(api(checkpoint), "_decision", foreign)
        else: monkeypatch.setattr(owner, "_decision", foreign)
    if phase == "constructor":
        mutate()
        with observe() as counts:
            with pytest.raises(ValueError, match="changed"):
                open_cpu(checkpoint, scheduler, monkeypatch)
        assert counts["restores"] == 0 and scheduler.active_leases() == []
        return
    texts, vectors = inputs(checkpoint, 1)
    cancel = Mutation(None, texts, vectors, phase="after_forward", action=lambda event: mutate(event.owner))
    with open_cpu(checkpoint, scheduler, monkeypatch, cancel_event=cancel) as owner:
        cancel.owner = owner
        with observe(owner, cancellation=cancel) as counts:
            with pytest.raises(ValueError, match="changed"):
                owner.infer(texts, vectors)
        assert cancel.triggered and counts["forward"] == 1 and not owner._active and not owner._observations


@pytest.mark.parametrize("fault", ["paired_finite", "paired_signed_zero", "checkpoint", "gradient", "hook", "policy"])
def test_full_original_checkpoint_tensor_byte_anchor_hook_and_policy_refusals_are_preserved(checkpoint, scheduler, monkeypatch, fault):
    with open_cpu(checkpoint, scheduler, monkeypatch) as owner:
        parameter, reference = owner._model.latent_up.bias, owner._reference["latent_up.bias"]
        saved, ref = parameter.detach().clone(), reference.clone()
        old_checkpoint, old_optimized, handle = deepcopy(owner._checkpoint), owner._optimized, None
        try:
            if fault.startswith("paired_"):
                parameter.data.view(torch.int32)[0] = reference.data.view(torch.int32)[0] = 1065353216 if fault == "paired_finite" else -2147483648
            elif fault == "checkpoint": owner._checkpoint["context_contract"]["representation_id"] += "-changed"
            elif fault == "gradient": parameter.grad = torch.zeros_like(parameter)
            elif fault == "hook": handle = owner._model.register_forward_hook(lambda *args: None)
            else: owner._optimized = False
            with pytest.raises(ValueError): owner.infer(*inputs(checkpoint))
            assert not owner._active and not owner._observations
        finally:
            parameter.data.copy_(saved); reference.data.copy_(ref); parameter.grad = None
            owner._checkpoint.clear(); owner._checkpoint.update(old_checkpoint); owner._optimized = old_optimized
            if handle is not None: handle.remove()


@pytest.mark.parametrize("source", ["external", "child", "deadline"])
def test_original_cancellation_deadline_and_owned_close_remain_usable(checkpoint, scheduler, monkeypatch, source):
    event = threading.Event()
    with open_cpu(checkpoint, scheduler, monkeypatch, cancel_event=event) as owner:
        if source == "external": event.set()
        elif source == "child": owner._lease.cancel()
        else: owner._deadline = time.monotonic() - 1
        with pytest.raises((RuntimeError, TimeoutError)): owner.infer(*inputs(checkpoint))
    assert scheduler.active_leases() == []


def test_cpu_opt_out_never_queries_cuda_or_constructs_optimizer_or_fits(checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("CPU opt-out attempted CUDA, optimizer or fitting")
    monkeypatch.setattr(torch.cuda, "is_available", forbidden)
    monkeypatch.setattr(torch.cuda, "current_device", forbidden)
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    monkeypatch.setattr(span, "train_decoder", forbidden)
    monkeypatch.setattr(dims, "train_decoder", forbidden)
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=False) as owner:
        assert owner.infer(*inputs(checkpoint))["training_executed"] is False


def test_subclass_dispatch_refuses_before_checkpoint_restore_or_lease_admission(checkpoint, scheduler, monkeypatch):
    class Foreign(api(checkpoint)):
        pass
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    options = {"synthetic_unreceipted": True} if dimension(checkpoint) == 4096 else {}
    with observe() as counts:
        with pytest.raises(ValueError, match="exact whole-input span owner required"):
            Foreign(checkpoint, expected_checkpoint_sha256=span.checkpoint_digest(checkpoint), scheduler=scheduler, **options)
    assert counts["restores"] == 0 and scheduler.active_leases() == []


def test_plain_result_mutation_after_its_independent_content_guard_is_refused(checkpoint, scheduler, monkeypatch):
    class Mutating:
        owner, triggered = None, False
        def is_set(self):
            frame = sys._getframe(1)
            try:
                for _ in range(6):
                    if frame is None:
                        break
                    if (self.owner is not None and frame.f_locals.get("self") is self.owner
                            and "result_guard" in frame.f_locals and "result" in frame.f_locals
                            and not self.triggered):
                        frame.f_locals["result"]["rows"][0]["status"] = "authored-changed"
                        self.triggered = True
                    frame = frame.f_back
            finally:
                del frame
            return False
    cancel = Mutating()
    with open_cpu(checkpoint, scheduler, monkeypatch, cancel_event=cancel) as owner:
        cancel.owner = owner
        with pytest.raises(ValueError, match="checkpoint content changed"):
            owner.infer(*inputs(checkpoint))
        assert cancel.triggered and not owner._active and not owner._observations


@pytest.mark.parametrize("expected,current,accepted", [
    (1, 1., False), (1, True, False), (0., -0., False), (-0., 0., False),
    ([1., 2.], (1., 2.), True), ({"a": [1.]}, {"a": (1.,)}, True),
    ({"a": 1, "b": 2}, {"b": 2, "a": 1}, True), ([1.], [float("nan")], False),
    ([1.], [float("inf")], False), ([1.], [2.], False),
])
def test_local_snapshot_preserves_exact_scalar_signed_zero_finite_and_container_semantics(expected, current, accepted):
    guard = input_guard.InputContentGuard(expected)
    snapshot = subject._snapshot(guard)
    subject._check_snapshot(guard, snapshot)
    assert guard.matches(current) is accepted
    subject._check_snapshot(guard, snapshot)


@pytest.mark.parametrize("value", [{1: "fallback"}, UserList([1., 2.]), UserDict({"a": 1})])
def test_canonical_fallback_behavior_retains_separate_snapshot_custody(value):
    try:
        guard = input_guard.InputContentGuard(value)
    except TypeError:
        with pytest.raises(TypeError): checkpoint_guard.CheckpointContentGuard(value)
        return
    old = checkpoint_guard.CheckpointContentGuard(value)
    snapshot = subject._snapshot(guard)
    assert guard._use_fast_comparison is False and snapshot[4] == ()
    assert guard.matches(deepcopy(value)) is old.matches(deepcopy(value)) is True
    subject._check_snapshot(guard, snapshot)
    wire = guard._canonical_bytes
    try:
        object.__setattr__(guard, "_canonical_bytes", bytes(bytearray(wire)))
        with pytest.raises(ValueError, match="immutable snapshot changed"): subject._check_snapshot(guard, snapshot)
    finally: object.__setattr__(guard, "_canonical_bytes", wire)


def test_reference_snapshot_traverses_only_wrappers_and_inherits_numeric_poll_cache_cleanup_methods(checkpoint, scheduler, monkeypatch):
    value = {"texts": ["café"], "vectors": [[.25] * dimension(checkpoint)], "receipts": None, "receipt_pins": None}
    guard = input_guard.InputContentGuard(value)
    snapshot = subject._snapshot(guard)
    assert len(snapshot[4]) == 4  # root, texts array, vectors array, one flat vector array.
    assert sum(len(entry[2]) for entry in snapshot[4] if entry[1] is input_guard._Array) == dimension(checkpoint) + 2
    for cls, base in ((subject.DeduplicatedWholeInputDeviceDimensionalSpanSession, baseline768.DeviceBitwiseDimensionalSpanSession),
                      (subject.DeduplicatedWholeInputDeviceLeanstral4096SpanSession, baseline4096.BitwiseDeviceLeanstral4096SpanSession)):
        for name in ("_poll", "_check", "_decision", "_reference_byte_plan", "_reference_state_bytes", "_check_reference_anchor",
                     "_admit_batch_memory", "_operation", "_synchronize", "close"):
            assert getattr(cls, name) is getattr(base, name)
        assert inspect.signature(cls).parameters["optimized"].default is True


def test_bound_decode_ast_inventory_preserves_three_original_sources_and_only_closed_substitution_counts():
    description = subject.inference_implementation()
    entries = description["source_bound_decode_adaptations"]
    assert len(entries) == 3
    for entry in entries:
        module = next(item for item, _ in subject._SOURCE_PINS if item.__name__.endswith(entry["source_role"]))
        raw = Path(module.__file__).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["source_sha256"]
        tree = ast.parse(raw)
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == entry["class"])
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == entry["method"])
        assert hashlib.sha256(ast.dump(method, include_attributes=False).encode()).hexdigest() == entry["original_method_ast_sha256"]
        assert entry["closed_ast_substitution_counts"] == {"outer_input_constructor": 1, "final_input_comparison": 1,
            "public_input_profile": 1, "resident_opt_out": int(entry["source_role"] == "legal_span_device_batch_inference")}
    assert "whole_input_guard_currentness" not in description
    for name in ("source_verification_success_cached", "boundary_consolidation_performed", "cached_row_input_substitution_performed",
        "lease_cadence_substitution_performed", "existing_selected_route_changed", "performance_qualified",
        "native_leanstral_outputs_qualified", "trained4096_qualification_established", "production_qualified",
        "proof_authority", "execution_attestation", "atom_array_scalar_snapshot_traversal_performed"):
        assert description[name] is False
