"""No-fit CPU controls for the independently anchored native768 session.

The reused saved-state fixture has synthetic positive step counts and moments;
it supplies no training or embedding evidence. No encoder or CUDA is executed.
"""
import ast
from copy import deepcopy
from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dims
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_device_inference as resident
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_device_batch_inference as batched
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_device_bitwise_inference as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import owned_tensor_bitwise_guard as bitwise_guard

_fixture_spec = importlib.util.spec_from_file_location("_native768_anchored_bitwise_protocol_fixture",
    Path(__file__).with_name("test_legal_span_device_inference.py"))
if _fixture_spec is None or _fixture_spec.loader is None:
    raise RuntimeError("native768 synthetic saved-state fixture unavailable")
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
checkpoint, scheduler, one_thread = (_fixture_module.checkpoint, _fixture_module.scheduler,
                                     _fixture_module.one_thread)
cpu_reference = _fixture_module.cpu_reference


def inputs():
    return (["Lark must retain books.", "Wren may publish the new records next Tuesday.",
             "Finch must not destroy files unless a court grants leave."],
            [[.1] * 768, [.2] * 768, [.3] * 768])


def open_cpu(cp, scheduler, monkeypatch, *, optimized=True, **kwargs):
    if optimized:
        monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    return subject.DeviceBitwiseDimensionalSpanSession(cp,
        expected_checkpoint_sha256=span.checkpoint_digest(cp), optimized=optimized,
        scheduler=scheduler, **kwargs)


@pytest.fixture
def contextual_checkpoint(checkpoint):
    cp = deepcopy(checkpoint)
    cp["model_state"]["latent_up.weight"] = torch.full((16, 4), .04, dtype=torch.float32).tolist()
    cp["model_state"]["latent_up.bias"] = torch.full((16,), .03, dtype=torch.float32).tolist()
    return cp


@pytest.mark.parametrize("ablation", ["none", "zero", "rotate", "disabled"])
def test_default_batched_cpu_decisions_match_unchanged_original(contextual_checkpoint, scheduler, monkeypatch, ablation):
    texts, vectors = inputs()
    before, rng = span._raw(contextual_checkpoint), torch.get_rng_state().clone()
    with open_cpu(contextual_checkpoint, scheduler, monkeypatch) as session:
        actual = session.infer(texts, vectors, latent_ablation=ablation)
        with batched.DeviceBatchedDimensionalSpanSession(contextual_checkpoint,
                expected_checkpoint_sha256=span.checkpoint_digest(contextual_checkpoint),
                optimized=True, scheduler=scheduler) as original:
            expected = original.infer(texts, vectors, latent_ablation=ablation)
        assert actual["rows"] == expected["rows"]
        assert actual["actual_forward_batches"] == expected["actual_forward_batches"]
        assert actual["schema"] == subject.SCHEMA == batched.SCHEMA
        assert actual["input_dimension"] == session._model.latent_down.in_features == 768
        profile = actual["execution_profile"]
        assert profile["profile_id"] == profile["session_profile_id"] == subject.PROFILE
        assert profile["inherited_profile_id"] == batched.PROFILE
        assert profile["owned_tensor_currentness"]["schema"] == bitwise_guard.SCHEMA
        assert profile["owned_tensor_currentness"]["mode"] == "cpu_reference_checks"
        assert profile["reference_byte_currentness"]["device_to_cpu_reference_transfers"] == 0
        assert profile["reference_byte_currentness"]["origin"] == "independently_restored_validated_cpu_checkpoint_model_before_upload"
        assert not profile["boundary_consolidation_performed"]
        assert not profile["native_bitwise_session_cuda_qualified"]
        assert not actual["input_receipts"]["native_encoder_inputs_authenticated"]
        assert all(actual[name] is False for name in span.FALSE)
        assert session.checkpoint == contextual_checkpoint
        assert torch.equal(rng, torch.get_rng_state())
    assert span._raw(contextual_checkpoint) == before and scheduler.active_leases() == []


def test_cpu_opt_out_preserves_exact_singletons_and_never_queries_cuda(checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("CPU opt-out touched CUDA or global seeding")
    monkeypatch.setattr(torch.cuda, "is_available", forbidden)
    monkeypatch.setattr(torch.cuda, "current_device", forbidden)
    monkeypatch.setattr(torch.cuda, "manual_seed_all", forbidden)
    monkeypatch.setattr(torch, "manual_seed", forbidden)
    texts, vectors = inputs()
    with open_cpu(checkpoint, scheduler, monkeypatch, optimized=False) as session:
        actual = session.infer(texts, vectors)
        assert actual["rows"] == cpu_reference(checkpoint, texts, vectors)
        assert not actual["numerical_batching"] and len(actual["actual_forward_batches"]) == 3
        assert actual["execution_profile"]["profile_id"] == batched.PROFILE
        assert actual["execution_profile"]["session_profile_id"] == subject.PROFILE
        assert actual["execution_profile"]["owned_tensor_guard_path"] == "numeric_reference_checks"


def test_anchor_is_complete_cpu_checkpoint_bytes_before_private_upload(checkpoint, scheduler, monkeypatch):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        restored = resident._restore(torch, deepcopy(checkpoint))
        expected = torch.cat([value.detach().reshape(-1).view(torch.uint8)
                              for _, value in sorted(restored.state_dict().items())]).numpy().tobytes()
        assert session._reference_anchor.payload == expected
        assert type(session._reference_anchor.payload) is bytes
        assert session._reference_anchor.checkpoint_sha256 == span.checkpoint_digest(checkpoint)
        assert session.describe()["reference_byte_currentness"]["reference_bytes"] == len(expected)


@pytest.mark.parametrize("fault", ["weight", "reference", "paired_finite", "paired_signed_zero", "reference_alias",
    "anchor", "anchor_payload", "pointer", "checkpoint", "training", "gradient", "hook", "decoder", "lease", "policy"])
def test_model_reference_alias_and_all_original_custody_mutations_refuse(checkpoint, scheduler, monkeypatch, fault):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        parameter = session._model.latent_up.bias
        initial, original_reference = parameter.detach().clone(), session._reference["latent_up.bias"]
        retained = original_reference.clone()
        original_anchor, original_payload = session._reference_anchor, session._reference_anchor.payload
        original_pointer, original_checkpoint = session._pointers["latent_up.bias"], deepcopy(session._checkpoint)
        original_decoder, original_memory, original_optimized = session._decoder.model, session._lease.memory_mb, session._optimized
        handle = None
        try:
            if fault == "weight":
                parameter.data[0] = .125
            elif fault == "reference":
                original_reference.data[0] = .125
            elif fault == "paired_finite":
                parameter.data[0] = original_reference.data[0] = .125
            elif fault == "paired_signed_zero":
                assert parameter[0] == 0 and not bool(torch.signbit(parameter[0]))
                parameter.data[0] = original_reference.data[0] = -.0
            elif fault == "reference_alias":
                session._reference["latent_up.bias"] = parameter.detach()
            elif fault == "anchor":
                session._reference_anchor = replace(original_anchor)
            elif fault == "anchor_payload":
                replacement = bytes(bytearray(original_payload))
                assert replacement == original_payload and replacement is not original_payload
                object.__setattr__(original_anchor, "payload", replacement)
            elif fault == "pointer":
                session._pointers["latent_up.bias"] += 4
            elif fault == "checkpoint":
                session._checkpoint["config"]["seed"] += 1
            elif fault == "training":
                session._model.train()
            elif fault == "gradient":
                parameter.grad = torch.zeros_like(parameter)
            elif fault == "hook":
                handle = session._model.register_forward_hook(lambda *_: None)
            elif fault == "decoder":
                session._decoder.model = None
            elif fault == "lease":
                session._lease.memory_mb += 1
            else:
                session._optimized = False
            with pytest.raises(ValueError):
                session.infer(*inputs())
            assert session._observations == [] and not session._active
        finally:
            parameter.data.copy_(initial)
            original_reference.data.copy_(retained)
            session._reference["latent_up.bias"] = original_reference
            session._reference_anchor = original_anchor
            object.__setattr__(original_anchor, "payload", original_payload)
            session._pointers["latent_up.bias"] = original_pointer
            session._checkpoint.clear()
            session._checkpoint.update(original_checkpoint)
            session._decoder.model, session._lease.memory_mb, session._optimized = original_decoder, original_memory, original_optimized
            parameter.grad = None
            session._model.eval()
            if handle is not None:
                handle.remove()


@pytest.mark.parametrize("mutation", ["finite", "signed_zero"])
def test_paired_mutation_in_post_forward_callback_is_refused_at_original_boundary(checkpoint, scheduler, monkeypatch, mutation):
    class MutatingCancellation:
        session, changed = None, False
        def is_set(self):
            if self.session is not None and self.session._observations and not self.changed:
                self.session._model.latent_up.bias.data[0] = .125 if mutation == "finite" else -.0
                self.session._reference["latent_up.bias"].data[0] = .125 if mutation == "finite" else -.0
                self.changed = True
            return False
    cancellation = MutatingCancellation()
    with open_cpu(checkpoint, scheduler, monkeypatch, cancel_event=cancellation) as session:
        parameter = session._model.latent_up.bias
        initial, retained = parameter.detach().clone(), session._reference["latent_up.bias"].clone()
        cancellation.session = session
        try:
            with pytest.raises(ValueError, match="reference bytes changed from admitted checkpoint"):
                session.infer(*inputs())
            assert cancellation.changed and session._observations == [] and not session._active
        finally:
            parameter.data.copy_(initial)
            session._reference["latent_up.bias"].data.copy_(retained)


@pytest.mark.parametrize("fault", ["integer", "noncontiguous", "lazy_negative", "host_budget", "gpu_budget"])
def test_anchor_metadata_and_reservations_refuse_before_views_or_concatenation(checkpoint, scheduler, monkeypatch, fault):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        original_memory, original_gpu, original_device = session._lease.memory_mb, session._lease.gpu_memory_mb, session._device
        state = {"weight": torch.ones(8, dtype=torch.float32)}
        if fault == "integer":
            state["weight"] = torch.ones(8, dtype=torch.int64)
        elif fault == "noncontiguous":
            state["weight"] = torch.ones(16)[::2]
        elif fault == "lazy_negative":
            state["weight"] = torch._neg_view(state["weight"])
        elif fault == "host_budget":
            session._lease.memory_mb = 1
        else:
            session._lease.gpu_memory_mb = 1
            session._device = "cuda:0"
        def forbidden(*args, **kwargs):
            raise AssertionError("anchor allocated before complete admission")
        monkeypatch.setattr(torch, "cat", forbidden)
        try:
            with pytest.raises(ValueError):
                session._reference_byte_plan(state, expected_device="cpu")
        finally:
            session._lease.memory_mb, session._lease.gpu_memory_mb, session._device = original_memory, original_gpu, original_device


def test_over_budget_complete_request_refuses_before_padded_allocation(checkpoint, scheduler, monkeypatch):
    text = "a" * 2048 + " x" * 255
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        def forbidden(*args, **kwargs):
            raise AssertionError("padded source allocated before budget admission")
        # Preserve bound source/function identities: instrument the private
        # factory instance's tensor method, not retained producer globals.
        monkeypatch.setattr(session._tensor_factory, "tensor", forbidden)
        with pytest.raises(ValueError, match="reserved host memory"):
            session.infer([text] * 128, [[.1] * 768 for _ in range(128)])
        assert session._observations == []


@pytest.mark.parametrize("fault", ["own_source", "resident_method", "batch_method", "restore", "device_model",
    "batch_memory", "bitwise_function", "bitwise_source", "checkpoint_dependency"])
def test_public_entries_bind_original_methods_helpers_and_current_sources(checkpoint, scheduler, monkeypatch, fault):
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        if fault == "own_source":
            monkeypatch.setattr(subject, "_source_sha256", lambda: "0" * 64)
        elif fault == "resident_method":
            monkeypatch.setattr(resident.DeviceDimensionalSpanSession, "_pure_check", lambda self: None)
        elif fault == "batch_method":
            monkeypatch.setattr(batched.DeviceBatchedDimensionalSpanSession, "_description", lambda self: {})
        elif fault == "restore":
            monkeypatch.setattr(resident, "_restore", lambda *_: None)
        elif fault == "device_model":
            monkeypatch.setattr(resident, "_device_model", lambda *_: None)
        elif fault == "batch_memory":
            monkeypatch.setattr(batched, "_batch_memory_bound", lambda *_a, **_k: {})
        elif fault == "bitwise_function":
            monkeypatch.setattr(bitwise_guard, "check_owned_tensor_bytes", lambda *_a, **_k: {})
        elif fault == "bitwise_source":
            monkeypatch.setattr(bitwise_guard, "_source_sha256", lambda: "0" * 64)
        else:
            monkeypatch.setattr(dims, "_implementation", lambda: {})
        with pytest.raises(ValueError, match="changed"):
            session.infer(*inputs())
        assert session._observations == [] and not session._active


def test_inference_builds_no_optimizer_and_performs_no_fit(checkpoint, scheduler, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("inference attempted optimizer construction or fitting")
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    monkeypatch.setattr(span, "train_decoder", forbidden)
    monkeypatch.setattr(dims, "train_decoder", forbidden)
    before = span._raw(checkpoint)
    with open_cpu(checkpoint, scheduler, monkeypatch) as session:
        assert not session.infer(*inputs())["training_executed"]
    assert span._raw(checkpoint) == before


def test_closed_session_drops_anchor_and_own_lease(checkpoint, scheduler, monkeypatch):
    session = open_cpu(checkpoint, scheduler, monkeypatch)
    session.close()
    assert session._reference_anchor is session._reference_anchor_identity is session._reference_payload_identity is None
    assert session._lease.released and scheduler.active_leases() == []
    session.close()


def _method(path, name, class_name=None):
    tree = ast.parse(Path(path).read_text())
    return next(item for cls in tree.body if isinstance(cls, ast.ClassDef)
                and (class_name is None or cls.name == class_name)
                for item in cls.body if isinstance(item, ast.FunctionDef) and item.name == name)


class _Normalize(ast.NodeTransformer):
    def visit_Attribute(self, node):
        node = self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id == "resident":
            return ast.Name(id=node.attr, ctx=node.ctx)
        return node

    def visit_Name(self, node):
        substitutions = {"_RESIDENT_IMPLEMENTATION_AT_IMPORT": "_implementation",
                         "_RESTORE_AT_IMPORT": "_restore", "_DEVICE_MODEL_AT_IMPORT": "_device_model"}
        node.id = substitutions.get(node.id, node.id)
        return node


def _assignment_targets(statement):
    if not isinstance(statement, ast.Assign):
        return set()
    result = set()
    for target in statement.targets:
        for node in ast.walk(target):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                result.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
                result.add(node.attr)
    return result


def test_copied_constructor_retains_original_body_order_except_declared_anchor_admission():
    original = _method(resident.__file__, "__init__", "DeviceDimensionalSpanSession")
    candidate = _method(subject.__file__, "__init__", "DeviceBitwiseDimensionalSpanSession")
    additions = {"_reference_anchor", "_reference_anchor_identity", "_reference_payload_identity",
                 "_reference_anchor_sha256", "_policy_guard", "_lease_identity", "_lease_guard",
                 "native_state", "layout", "reference_bytes", "payload"}

    class RemoveAdditions(ast.NodeTransformer):
        def visit_Assign(self, node):
            return None if _assignment_targets(node) & additions else self.generic_visit(node)

        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call):
                if isinstance(node.value.func, ast.Name) and node.value.func.id == "_check_bindings":
                    return None
                if any(isinstance(argument, ast.Constant) and argument.value ==
                       "native768 checkpoint exceeds reserved restoration host memory estimate"
                       for argument in node.value.args):
                    return None
            return self.generic_visit(node)

    candidate = _Normalize().visit(RemoveAdditions().visit(candidate))
    assert ast.dump(original, include_attributes=False) == ast.dump(candidate, include_attributes=False)


def test_copied_guard_retains_every_original_noncomparison_clause_and_order():
    original, candidate = _method(resident.__file__, "_pure_check"), _method(subject.__file__, "_pure_check")

    class NormalizeComparisons(ast.NodeTransformer):
        def visit_Assign(self, node):
            if _assignment_targets(node) & {"_reference_anchor_receipt", "_value_guard_receipt"}:
                return None
            node = self.generic_visit(node)
            if _assignment_targets(node) == {"state"} and isinstance(node.value, ast.Call):
                if isinstance(node.value.func, ast.Name) and node.value.func.id == "dict":
                    node.value = node.value.args[0]
            return node

        def visit_BoolOp(self, node):
            node = self.generic_visit(node)
            node.values = [value for value in node.values if not (
                isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                and isinstance(value.func.value, ast.Name) and value.func.value.id == "torch"
                and value.func.attr == "equal")]
            return node

        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Name) and func.id == "_check_bindings":
                    return None
                if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute)
                        and func.value.attr in ("_policy_guard", "_lease_guard")):
                    return None
                if any(isinstance(argument, ast.Constant) and argument.value ==
                       "private native768 resource lease binding changed" for argument in node.value.args):
                    return None
            return self.generic_visit(node)

    original = NormalizeComparisons().visit(original)
    candidate = _Normalize().visit(NormalizeComparisons().visit(candidate))
    assert ast.dump(original, include_attributes=False) == ast.dump(candidate, include_attributes=False)
