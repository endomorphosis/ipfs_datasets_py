"""CRYPTOIR-G780 tests for bounded formal-learning runs and receipts."""

from __future__ import annotations

import math

import pytest
from ipfs_datasets_py.logic.security_ir.solidity_cpt_top10.training import (
    CANDIDATE_AUTHORITY,
    BackendCheckpoint,
    BackendRunResult,
    CheckpointManifest,
    DeterministicTinyOfflineBackend,
    FormalTrainingReceipt,
    FormalTrainingRequest,
    FormalTrainingRunner,
    HardwareProfile,
    TrainingAuthorityError,
    TrainingAuthorityGrant,
    TrainingBackendUnavailable,
    TrainingBudgets,
    TrainingCancelled,
    TrainingContractError,
    TrainingCorrupt,
    TrainingDiverged,
    TrainingIntegrityError,
    TrainingMode,
    TrainingOutputPolicy,
    TrainingPartial,
    TrainingStale,
    TrainingStatus,
    TrainingTimedOut,
    build_offline_fixture_request,
    verify_training_receipt,
)


def _request(
    mode: TrainingMode = TrainingMode.DRY_RUN,
    **updates,
) -> FormalTrainingRequest:
    value = build_offline_fixture_request(mode=mode).to_dict()
    value.pop("request_id")
    value.update(updates)
    return FormalTrainingRequest.from_dict(value)


def test_request_binds_every_acceptance_critical_input_and_rehashes() -> None:
    request = build_offline_fixture_request()
    wire = request.to_dict()

    assert {
        "source_cid",
        "graph_cid",
        "index_cid",
        "partition_cid",
        "license_cid",
        "training_data_cid",
        "base_model_id",
        "base_model_revision",
        "tokenizer_id",
        "tokenizer_revision",
        "objective",
        "feature_schema",
        "target_schema",
        "hyperparameters",
        "seed",
        "backend_id",
        "backend_capability",
        "hardware",
        "budgets",
        "output_policy",
        "mode",
        "request_id",
    } <= set(wire)
    assert {
        "max_input_bytes",
        "max_input_tokens",
        "max_steps",
        "timeout_ms",
        "max_memory_bytes",
        "max_checkpoints",
        "max_checkpoint_bytes",
        "max_total_checkpoint_bytes",
    } == set(wire["budgets"])
    assert FormalTrainingRequest.from_dict(wire).request_id == request.request_id

    tampered = dict(wire)
    tampered["seed"] = 99
    with pytest.raises(TrainingIntegrityError, match="request_id"):
        FormalTrainingRequest.from_dict(tampered)

    extended = dict(wire)
    extended["unreviewed_extension"] = True
    with pytest.raises(TrainingIntegrityError, match="unknown fields"):
        FormalTrainingRequest.from_dict(extended)


@pytest.mark.parametrize("field", ["base_model_revision", "tokenizer_revision"])
@pytest.mark.parametrize("floating", ["main", "latest", "HEAD"])
def test_request_rejects_floating_model_or_tokenizer_revisions(field: str, floating: str) -> None:
    with pytest.raises(TrainingContractError, match="exact revision"):
        _request(**{field: floating})


def test_dry_run_is_default_and_never_invokes_backend() -> None:
    class ExplodingBackend:
        backend_id = DeterministicTinyOfflineBackend.backend_id
        capability = DeterministicTinyOfflineBackend.capability

        def run(self, request, records):  # pragma: no cover - must not run
            raise AssertionError("dry-run invoked backend")

    request = build_offline_fixture_request()
    receipt = FormalTrainingRunner(ExplodingBackend()).run(request, ({"feature": "local"},))

    assert request.mode is TrainingMode.DRY_RUN
    assert receipt.status is TrainingStatus.DRY_RUN
    assert receipt.checkpoints == ()
    assert receipt.proof_authority is False
    assert receipt.transaction_authority is False
    assert receipt.learned_output_authority == CANDIDATE_AUTHORITY


def test_tiny_offline_checkpoint_and_terminal_receipt_reproduce() -> None:
    request = build_offline_fixture_request(mode=TrainingMode.TINY_OFFLINE)
    records = ({"feature": "local", "token_count": 3},)

    first = FormalTrainingRunner(DeterministicTinyOfflineBackend()).run(request, records)
    second = FormalTrainingRunner(DeterministicTinyOfflineBackend()).run(request, records)

    assert first.status is TrainingStatus.SUCCEEDED
    assert first.receipt_id == second.receipt_id
    assert first.to_dict() == second.to_dict()
    assert len(first.checkpoints) == 1
    manifest = first.checkpoints[0]
    assert manifest.learned_output_authority == CANDIDATE_AUTHORITY
    assert manifest.proof_authority is False
    assert manifest.transaction_authority is False
    assert CheckpointManifest.from_dict(manifest.to_dict()) == manifest
    assert FormalTrainingReceipt.from_dict(first.to_dict()) == first

    # Recreate the deterministic fixture bytes and verify all nested hashes.
    result = DeterministicTinyOfflineBackend().run(request, records)
    payload = result.checkpoints[0].payload
    verified = verify_training_receipt(
        request,
        first.to_dict(),
        checkpoint_payloads={manifest.checkpoint_id: payload},
    )
    assert verified.receipt_id == first.receipt_id

    with pytest.raises(TrainingCorrupt, match="SHA-256"):
        verify_training_receipt(
            request,
            first,
            checkpoint_payloads={manifest.payload_cid: bytes([payload[0] ^ 1]) + payload[1:]},
        )


def test_receipt_and_manifest_authority_cannot_be_widened() -> None:
    request = build_offline_fixture_request(mode=TrainingMode.TINY_OFFLINE)
    receipt = FormalTrainingRunner(DeterministicTinyOfflineBackend()).run(request)

    manifest = receipt.checkpoints[0].to_dict()
    manifest["proof_authority"] = True
    manifest.pop("checkpoint_id")
    with pytest.raises(TrainingAuthorityError, match="candidate-only"):
        CheckpointManifest.from_dict(manifest)

    wire = receipt.to_dict()
    wire["learned_output_authority"] = "proof"
    wire.pop("receipt_id")
    with pytest.raises(TrainingAuthorityError, match="candidate-only"):
        FormalTrainingReceipt.from_dict(wire)


def test_gated_side_effects_and_gpu_need_separate_authority() -> None:
    output = TrainingOutputPolicy(
        model_download=True,
        external_tracking=True,
        checkpoint_upload=True,
        publication=True,
    )
    hardware = HardwareProfile(
        profile_id="gpu-production-v1",
        accelerator="gpu",
        full_gpu_execution=True,
        network_access=True,
    )
    with pytest.raises(TrainingAuthorityError, match="separate operator"):
        _request(
            mode=TrainingMode.AUTHORIZED_OFFLINE.value,
            output_policy=output.to_dict(),
            hardware=hardware.to_dict(),
        )

    fixture = build_offline_fixture_request()
    authority = TrainingAuthorityGrant(
        approval_id="operator-review-17",
        authority_cid=fixture.source_cid,
        permitted_actions=(
            "model_download",
            "external_tracking",
            "full_gpu_execution",
            "checkpoint_upload",
            "publication",
        ),
    )
    authorized = _request(
        mode=TrainingMode.AUTHORIZED_OFFLINE.value,
        output_policy=output.to_dict(),
        hardware=hardware.to_dict(),
        authority_grant=authority.to_dict(),
    )
    assert authorized.authority_grant == authority
    assert authorized.output_policy.learned_output_authority == "candidate"


def test_dry_and_tiny_modes_remain_cpu_local_even_with_authority() -> None:
    fixture = build_offline_fixture_request()
    authority = TrainingAuthorityGrant(
        approval_id="operator-review-18",
        authority_cid=fixture.source_cid,
        permitted_actions=("full_gpu_execution",),
    )
    hardware = HardwareProfile(
        profile_id="gpu-v1",
        accelerator="gpu",
        full_gpu_execution=True,
    )
    with pytest.raises(TrainingAuthorityError, match="CPU-only"):
        _request(
            mode=TrainingMode.TINY_OFFLINE.value,
            hardware=hardware.to_dict(),
            authority_grant=authority.to_dict(),
        )


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (TrainingBackendUnavailable(), TrainingStatus.UNAVAILABLE),
        (TrainingTimedOut(), TrainingStatus.TIMED_OUT),
        (TrainingCancelled(), TrainingStatus.CANCELLED),
        (TrainingPartial(), TrainingStatus.PARTIAL),
        (TrainingDiverged(), TrainingStatus.DIVERGENT),
        (TrainingStale(), TrainingStatus.STALE),
        (TrainingCorrupt(), TrainingStatus.CORRUPT),
    ],
)
def test_backend_failure_states_remain_explicit(exception, expected) -> None:
    class FailingBackend:
        backend_id = DeterministicTinyOfflineBackend.backend_id
        capability = DeterministicTinyOfflineBackend.capability

        def run(self, request, records):
            raise exception

    receipt = FormalTrainingRunner(FailingBackend()).run(build_offline_fixture_request(mode=TrainingMode.TINY_OFFLINE))
    assert receipt.status is expected
    assert receipt.successful is False


def test_missing_or_mismatched_backend_is_unavailable() -> None:
    request = build_offline_fixture_request(mode=TrainingMode.TINY_OFFLINE)
    assert FormalTrainingRunner().run(request).status is TrainingStatus.UNAVAILABLE

    class WrongBackend:
        backend_id = "wrong"
        capability = "wrong"

    receipt = FormalTrainingRunner(WrongBackend()).run(request)
    assert receipt.status is TrainingStatus.UNAVAILABLE
    assert receipt.diagnostics == ("backend_or_capability_mismatch",)


def test_cancellation_is_checked_without_starting_backend() -> None:
    request = build_offline_fixture_request(mode=TrainingMode.TINY_OFFLINE)
    receipt = FormalTrainingRunner(DeterministicTinyOfflineBackend()).run(request, cancelled=lambda: True)
    assert receipt.status is TrainingStatus.CANCELLED
    assert receipt.checkpoints == ()


def test_input_and_backend_resource_overruns_are_partial_or_timeout() -> None:
    budgets = TrainingBudgets(
        max_input_bytes=16,
        max_input_tokens=4,
        max_steps=1,
        timeout_ms=1,
        max_memory_bytes=16,
        max_checkpoints=1,
        max_checkpoint_bytes=16,
        max_total_checkpoint_bytes=16,
    )
    request = _request(mode=TrainingMode.TINY_OFFLINE.value, budgets=budgets.to_dict())
    input_receipt = FormalTrainingRunner(DeterministicTinyOfflineBackend()).run(
        request, ({"value": "well over sixteen bytes"},)
    )
    assert input_receipt.status is TrainingStatus.PARTIAL

    class TimeoutBackend:
        backend_id = DeterministicTinyOfflineBackend.backend_id
        capability = DeterministicTinyOfflineBackend.capability

        def run(self, request, records):
            return BackendRunResult(
                status=TrainingStatus.SUCCEEDED,
                checkpoints=(BackendCheckpoint(b"ok", step=1, state_schema="fixture/v1"),),
                runtime_ms=2,
                output_model_cid="",
            )

    timeout_receipt = FormalTrainingRunner(TimeoutBackend()).run(request)
    assert timeout_receipt.status is TrainingStatus.TIMED_OUT


def test_corrupt_stale_and_divergent_checkpoint_results_fail_closed() -> None:
    request = build_offline_fixture_request(mode=TrainingMode.TINY_OFFLINE)

    class CorruptBackend:
        backend_id = DeterministicTinyOfflineBackend.backend_id
        capability = DeterministicTinyOfflineBackend.capability

        def run(self, request, records):
            return BackendRunResult(
                status=TrainingStatus.SUCCEEDED,
                checkpoints=(
                    BackendCheckpoint(
                        b"state",
                        step=1,
                        state_schema="fixture/v1",
                        expected_sha256="0" * 64,
                    ),
                ),
            )

    assert FormalTrainingRunner(CorruptBackend()).run(request).status is TrainingStatus.CORRUPT

    class StaleBackend(CorruptBackend):
        def run(self, request, records):
            return BackendRunResult(
                status=TrainingStatus.SUCCEEDED,
                checkpoints=(
                    BackendCheckpoint(
                        b"state",
                        step=1,
                        state_schema="fixture/v1",
                        request_id=build_offline_fixture_request().request_id,
                    ),
                ),
            )

    assert FormalTrainingRunner(StaleBackend()).run(request).status is TrainingStatus.STALE

    with pytest.raises(TrainingDiverged, match="non-finite"):
        BackendRunResult(status=TrainingStatus.DIVERGENT, metrics={"loss": math.inf})


def test_evaluation_only_records_never_enter_training() -> None:
    request = build_offline_fixture_request()
    with pytest.raises(TrainingAuthorityError, match="evaluation_only"):
        FormalTrainingRunner().run(
            request,
            (
                {
                    "stream": "evaluation_only",
                    "candidate_authority": "candidate",
                },
            ),
        )


def test_receipt_rejects_request_and_checkpoint_lineage_drift() -> None:
    request = build_offline_fixture_request(mode=TrainingMode.TINY_OFFLINE)
    receipt = FormalTrainingRunner(DeterministicTinyOfflineBackend()).run(request)
    other = _request(
        mode=TrainingMode.TINY_OFFLINE.value,
        seed=123,
    )
    with pytest.raises(TrainingStale, match="different training request"):
        verify_training_receipt(other, receipt)

    wire = receipt.to_dict()
    checkpoint = dict(wire["checkpoints"][0])
    checkpoint["request_id"] = other.request_id
    checkpoint.pop("checkpoint_id")
    wire["checkpoints"] = [checkpoint]
    wire.pop("receipt_id")
    with pytest.raises(TrainingStale, match="different request"):
        FormalTrainingReceipt.from_dict(wire)
