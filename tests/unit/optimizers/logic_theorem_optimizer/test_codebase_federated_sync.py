"""Closed source/model/work bindings and a qualified, optional sync seam."""
from dataclasses import dataclass, replace
import copy
import hashlib
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_federated_sync as module
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import (
    ClientSpec, FederatedRound, ParameterSpec,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_sync import (
    GradientBackendCapabilities, GradientBackendUnavailable, GradientReduction, GradientReductionRequest,
    TrainingMode, TrainingSyncController, TrainingSyncError,
)
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured


@pytest.fixture
def round_spec():
    return FederatedRound("round-a", "codebase-variant-a", "codebase-lineage-a", 8,
        module.CODEBASE_ARCHITECTURE, module.CODEBASE_RUNTIME_PROFILE, "a" * 64, "b" * 64, "c" * 64,
        (ParameterSpec("encoder.weight", (3, 8), "float64"), ParameterSpec("encoder.bias", (8,), "float64"),
         ParameterSpec("decoder.weight", (8, 3), "float64"), ParameterSpec("decoder.bias", (3,), "float64")),
        (ClientSpec("client-b", 3, "e" * 64), ClientSpec("client-a", 2, "d" * 64)), max_local_steps=2)


@pytest.fixture
def source_head():
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    snapshot = cid_for_structured({"snapshot": "source"})
    return CodebaseHead("repository:test", 1, cid_for_structured({"manifest": "source"}), snapshot,
                        f"rev:repository:test:snapshot:{snapshot}", cid_for_structured({"receipt": "source"}))


@pytest.fixture
def work(round_spec, source_head):
    return module.bind_codebase_federated_work(round_spec, base_version_id="sha256:" + "f" * 64,
        source_head=source_head, client_id="client-a", local_target_sha256="d" * 64,
        sample_count=2, attempt=1, fence=2)


def test_closed_work_replays_round_membership_source_and_detached_identity(work, round_spec, source_head):
    value = work.to_dict()
    assert value["round"] == round_spec.manifest
    assert value["round_sha256"] == round_spec.round_sha256
    assert value["model_id"] == round_spec.model_id and value["lineage_id"] == round_spec.lineage_id
    assert value["source_head"] == source_head.to_dict()
    assert value["base_version_id"] == "sha256:" + "f" * 64
    assert value["client_id"] == "client-a" and value["sample_count"] == 2
    assert value["attempt"] == 1 and value["fence"] == 2
    assert all(flag is False for flag in value["authority"].values())
    assert module.CodebaseFederatedWorkBinding.from_dict(value, expected_sha256=work.sha256).canonical_bytes == work.canonical_bytes
    assert work.validate_round(round_spec).manifest == round_spec.manifest
    value["round"]["clients"][0]["sample_count"] = 99
    value["source_head"]["generation"] = 99
    assert work.to_dict()["source_head"]["generation"] == 1
    assert work.to_dict()["round"]["clients"][0]["sample_count"] == 2


@pytest.mark.parametrize("field,value", [
    ("round_sha256", "0" * 64), ("model_id", "another-model"), ("lineage_id", "another-lineage"),
    ("base_sha256", "0" * 64), ("local_target_sha256", "0" * 64), ("sample_count", 3),
    ("sample_count", True), ("client_id", "absent"), ("attempt", 0), ("attempt", True),
    ("fence", 0), ("fence", True), ("fence", 2**63), ("base_version_id", " padded "),
    ("base_version_id", ""), ("profile", "another-profile"), ("schema", "old-schema"),
])
def test_work_fields_do_not_override_native_bindings(work, field, value):
    payload = work.to_dict()
    payload[field] = value
    with pytest.raises(module.CodebaseFederatedSyncError):
        module.CodebaseFederatedWorkBinding.from_dict(payload)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(extra="unsupported"),
    lambda p: p["authority"].update(proof_authority=True),
    lambda p: p["authority"].update(completion_authority=0),
    lambda p: p["round"].update(qualified=True),
    lambda p: p["round"]["parameters"][0].update(dtype="float32"),
    lambda p: p["round"]["parameters"][0].update(shape=[4]),
    lambda p: p["round"]["clients"].reverse(),
    lambda p: p["round"]["clients"][0].update(local_data_sha256="0" * 64),
    lambda p: p["source_head"].update(ast_revision_id="different"),
    lambda p: p["source_head"].update(source_runtime_semantics_verified=True),
])
def test_closed_native_round_and_source_payloads_reject_tampering(work, mutation):
    payload = work.to_dict()
    mutation(payload)
    with pytest.raises(module.CodebaseFederatedSyncError):
        module.CodebaseFederatedWorkBinding.from_dict(payload)


def test_source_head_and_lease_changes_require_new_work_identity(work):
    # A structurally valid declaration is an inert claim. The transport/owner
    # pins the exact work hash and independently verifies its payload preimage.
    for field, value in (("fence", 3), ("attempt", 2), ("base_version_id", "another-version")):
        payload = work.to_dict()
        payload[field] = value
        assert module.CodebaseFederatedWorkBinding.from_dict(payload).sha256 != work.sha256
        with pytest.raises(module.CodebaseFederatedSyncError, match="expected SHA"):
            module.CodebaseFederatedWorkBinding.from_dict(payload, expected_sha256=work.sha256)
    payload = work.to_dict()
    payload["source_head"]["generation"] = 2
    assert module.CodebaseFederatedWorkBinding.from_dict(payload).sha256 != work.sha256
    with pytest.raises(module.CodebaseFederatedSyncError, match="expected SHA"):
        module.CodebaseFederatedWorkBinding.from_dict(payload, expected_sha256=work.sha256)


def test_canonical_bytes_are_immutable_and_rechecked(work):
    with pytest.raises(module.CodebaseFederatedSyncError, match="canonical"):
        module.CodebaseFederatedWorkBinding(json.dumps(work.to_dict(), indent=2).encode())
    with pytest.raises(module.CodebaseFederatedSyncError, match="immutable"):
        module.CodebaseFederatedWorkBinding(bytearray(work.canonical_bytes))
    with pytest.raises(Exception):
        work.canonical_bytes = b"{}"
    copied = module.CodebaseFederatedWorkBinding(work.canonical_bytes)
    object.__setattr__(copied, "canonical_bytes", b"{}")
    with pytest.raises(module.CodebaseFederatedSyncError):
        module.derive_codebase_sync_binding(copied)


@pytest.mark.parametrize("changes", [
    {"architecture": "legal-only"}, {"runtime_profile": "codebase_feature_v1"}, {"dimension": 384},
    {"parameters": (ParameterSpec("encoder.weight", (3, 8), "float32"), ParameterSpec("encoder.bias", (8,), "float32"),
        ParameterSpec("decoder.weight", (8, 3), "float32"), ParameterSpec("decoder.bias", (3,), "float32"))},
    {"parameters": (ParameterSpec("encoder.weight", (3, 7), "float64"), ParameterSpec("encoder.bias", (8,), "float64"),
        ParameterSpec("decoder.weight", (8, 3), "float64"), ParameterSpec("decoder.bias", (3,), "float64"))},
])
def test_other_profile_or_layout_cannot_enter_codebase_boundary(round_spec, source_head, changes):
    changed = replace(round_spec, **changes)
    with pytest.raises(module.CodebaseFederatedSyncError):
        module.bind_codebase_federated_work(changed, base_version_id="version", source_head=source_head,
            client_id="client-a", local_target_sha256="d" * 64, sample_count=2, attempt=1, fence=1)


def test_native_sync_binding_and_buckets_match_exact_round_layout(work, round_spec):
    binding = module.derive_codebase_sync_binding(work, membership_epoch=3)
    assert binding.base_sha256 == round_spec.base_sha256 and binding.layout_sha256 == round_spec.layout_sha256
    assert binding.participant_ids == ("client-a", "client-b") and binding.world_size == 2
    assert binding.membership_epoch == 3
    assert binding.round_id.endswith(round_spec.round_sha256)
    buckets = module.derive_codebase_gradient_buckets(work)
    assert [(b.bucket_id, b.shape, b.dtype) for b in buckets] == [(p.name, p.shape, p.dtype) for p in round_spec.parameters]
    with pytest.raises(module.CodebaseFederatedSyncError):
        module.derive_codebase_sync_binding(work, membership_epoch=True)
    with pytest.raises(module.CodebaseFederatedSyncError):
        work.validate_round(replace(round_spec, round_id="another"))


def test_peer_work_attempts_share_only_same_exact_sync_round(work, round_spec, source_head):
    peer = module.bind_codebase_federated_work(round_spec, base_version_id=work.to_dict()["base_version_id"],
        source_head=source_head, client_id="client-b", local_target_sha256="e" * 64, sample_count=3, attempt=5, fence=9)
    assert work.sha256 != peer.sha256
    assert module.derive_codebase_sync_binding(peer) == module.derive_codebase_sync_binding(work)
    assert peer.to_dict()["attempt"] == 5 and peer.to_dict()["fence"] == 9


@dataclass
class Tensor:
    shape: tuple[int, ...]
    dtype: str = "float64"


class QualifiedTestBackend:
    def __init__(self, dtype="float64"):
        self.calls = []
        self.dtype = dtype

    def capabilities(self):
        return GradientBackendCapabilities("test-only-qualified", (GradientReduction.MEAN,), (self.dtype,), True, True)

    def join(self, binding, participant_id):
        self.calls.append(("join", binding, participant_id))

    def reduce_gradients(self, request, gradients):
        self.calls.append(("reduce", request, gradients))
        return gradients

    def barrier(self, binding, participant_id, operation_id, deadline):
        self.calls.append(("barrier", binding, participant_id, operation_id, deadline))

    def abort(self, binding, reason):
        self.calls.append(("abort", binding, reason))

    def close(self, binding):
        self.calls.append(("close", binding))


def test_federation_is_default_and_performs_no_collective_or_fallback(work):
    controller = module.create_codebase_sync_controller(work)
    assert type(controller) is TrainingSyncController
    assert controller.mode is TrainingMode.FEDERATED
    assert controller.supported_modes == (TrainingMode.FEDERATED,)
    with pytest.raises(GradientBackendUnavailable):
        controller.join(module.derive_codebase_sync_binding(work), "client-a")
    controller.close()


@pytest.mark.parametrize("options", [
    {}, {"backend": QualifiedTestBackend()}, {"verify_backend": lambda *_: True},
    {"backend": QualifiedTestBackend(), "verify_backend": lambda *_: False},
    {"backend": QualifiedTestBackend(), "verify_backend": lambda *_: 1},
    {"backend": QualifiedTestBackend("float32"), "verify_backend": lambda *_: True},
])
def test_gradient_mode_requires_independent_float64_backend_qualification(work, options):
    with pytest.raises(GradientBackendUnavailable):
        module.create_codebase_sync_controller(work, mode=TrainingMode.GRADIENT_SYNCHRONIZED, **options)


def test_explicit_qualified_backend_seam_forwards_tensors_directly(work):
    backend = QualifiedTestBackend()
    controller = module.create_codebase_sync_controller(work, mode=TrainingMode.GRADIENT_SYNCHRONIZED,
        backend=backend, verify_backend=lambda selected, capabilities: selected is backend, clock=lambda: 100.)
    assert backend.calls == []  # Construction only qualifies; no join occurs.
    binding = module.derive_codebase_sync_binding(work)
    bucket = module.derive_codebase_gradient_buckets(work)[0]
    controller.join(binding, work.to_dict()["client_id"])
    tensor = Tensor(bucket.shape)
    request = GradientReductionRequest(binding, "client-a", 0, bucket, GradientReduction.MEAN, 1., 120., "gradient-0")
    assert controller.reduce_gradients(request, tensor) is tensor
    assert backend.calls[-1][2] is tensor
    controller.barrier(binding, operation_id="barrier-0", deadline_unix_s=120.)
    controller.close()
    assert [call[0] for call in backend.calls] == ["join", "reduce", "barrier", "close"]
    assert all(flag is False for flag in work.to_dict()["authority"].values())


def test_unsupported_mode_or_accidental_backend_in_federation_is_rejected(work):
    with pytest.raises(TrainingSyncError):
        module.create_codebase_sync_controller(work, mode="federated")
    with pytest.raises(TrainingSyncError):
        module.create_codebase_sync_controller(work, backend=QualifiedTestBackend())


def reference(raw):
    return module.CodebaseArtifactReference(hashlib.sha256(raw).hexdigest(), cid_for_bytes(raw), len(raw))


def test_artifact_task_uses_existing_route_with_only_committed_file_references(round_spec, source_head):
    base = reference(b"base checkpoint binary")
    local = reference(b"source-local payload bytes")
    spec = replace(round_spec, base_sha256=base.sha256,
        clients=(ClientSpec("client-a", 2, local.sha256), ClientSpec("client-b", 3, "e" * 64)))
    round_ref = reference(json.dumps(spec.manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())
    work = module.bind_codebase_federated_work(spec, base_version_id="version", source_head=source_head,
        client_id="client-a", local_target_sha256=local.sha256, sample_count=2, attempt=1, fence=1)
    value = module.make_codebase_federated_task(work, round_artifact=round_ref,
        base_artifact=base, local_payload_artifact=local)
    assert value["route"]["tool_name"] == "p2p_taskqueue_submit"
    assert value["route"]["implementation"].endswith("native_p2p_tools.p2p_taskqueue_submit")
    assert value["route"]["client"].endswith("p2p_tasks.client.submit_task_with_info")
    assert value["payload"]["work_sha256"] == work.sha256
    assert value["payload"]["artifacts"]["base_checkpoint"] == base.to_dict()
    assert value["network_executed"] is False and value["worker_dispatch_qualified"] is False
    assert value["gradient_backend_qualified"] is False
    assert all(flag is False for flag in value["authority"].values())
    assert "parameters" not in value["payload"]["artifacts"]
    assert "values" not in json.dumps(value["payload"]["artifacts"])
    with pytest.raises(module.CodebaseFederatedSyncError, match="bound base"):
        module.make_codebase_federated_task(work, round_artifact=round_ref,
            base_artifact=reference(b"another base"), local_payload_artifact=local)


def test_artifact_references_reject_digest_cid_size_and_field_mismatches():
    good = reference(b"artifact")
    assert module.CodebaseArtifactReference.from_dict(good.to_dict()).to_dict() == good.to_dict()
    for change in ({"sha256": "0" * 64}, {"cidv1": cid_for_structured({"a": 1})},
                   {"bytes": True}, {"bytes": 0}, {"bytes": 512 * 1024 * 1024 + 1}, {"inline_tensor": [1.]}):
        value = {**good.to_dict(), **change}
        with pytest.raises(module.CodebaseFederatedSyncError):
            module.CodebaseArtifactReference.from_dict(value)
