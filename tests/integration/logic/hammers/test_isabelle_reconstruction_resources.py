"""Resource/identity failure boundaries at the public Isabelle reconstructor.

Synthetic operation receipts exercise adapter joins only; actual runtime,
pressure admission and native cancellation are qualified by the owner suite.
"""
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.hammers.corpus import compute_content_digest
from ipfs_datasets_py.logic.hammers.models import ITPKind
from ipfs_datasets_py.logic.hammers.reconstruction import ReconstructionEvidence, ReconstructionInputError
from ipfs_datasets_py.logic.hammers.reconstructors import isabelle as adapter
from tests.integration.logic.hammers.test_reconstruction import (
    ISABELLE_SOURCE, completed_isabelle_operation, make_candidate, make_goal_snapshot,
    make_policy, make_request,
)


def inputs(**policy):
    return dict(request=make_request(itp=ITPKind.ISABELLE,
                    theorem_id="hammer_recon_isabelle_goal", policy=make_policy(**policy)),
                candidate=make_candidate(), native_source=ISABELLE_SOURCE,
                goal_snapshot=make_goal_snapshot(itp=ITPKind.ISABELLE,
                    theorem_id="hammer_recon_isabelle_goal", hypotheses=[], imports=["Main"]))


def install_fake(monkeypatch, **changes):
    calls = []
    def invoke(**kwargs):
        calls.append(kwargs)
        return completed_isabelle_operation(**kwargs, **changes)
    monkeypatch.setattr(adapter, "run_isabelle_operation", invoke)
    return calls


def test_one_operation_covers_preparation_check_and_tightest_policy(monkeypatch):
    calls = install_fake(monkeypatch)
    parent, cancellation = object(), object()
    reconstructor = adapter.IsabelleReconstructor(timeout=90, executable="/test/selected-isabelle",
        auto_install=True, memory_mb=2048, parent_lease=parent, cancellation=cancellation)
    monkeypatch.setattr(reconstructor, "capability", lambda: pytest.fail("separate capability probe"))
    record, evidence, lock = reconstructor.reconstruct(
        **inputs(timeout_seconds=15, cpu_seconds=7, memory_mb=1536, network_allowed=True), timeout=80)
    assert record.kernel_accepted is True
    assert len(calls) == 1
    call = calls[0]
    assert call["mode"] == "check" and call["timeout_seconds"] == 15 and call["cpu_seconds"] == 7
    assert call["memory_mb"] == 1536 and call["auto_install"] is True
    assert call["parent_lease"] is parent and call["scheduler"] is None and call["cancellation"] is cancellation
    assert call["executable"] == "/test/selected-isabelle" and call["install_root"] is None
    assert call["source"] == evidence.checked_source
    assert evidence.wall_time_seconds == .05  # whole operation, not just .01 kernel time
    assert evidence.execution["grants_proof_authority"] is False


def test_scheduler_and_managed_root_forwarded_without_parent_or_executable(monkeypatch):
    calls = install_fake(monkeypatch)
    scheduler = object()
    adapter.IsabelleReconstructor(scheduler=scheduler, install_root="/test/distribution").reconstruct(**inputs())
    assert calls[0]["scheduler"] is scheduler and calls[0]["parent_lease"] is None
    assert calls[0]["install_root"] == "/test/distribution" and calls[0]["executable"] is None


def test_request_network_policy_controls_opt_in_installation(monkeypatch):
    calls = install_fake(monkeypatch)
    adapter.IsabelleReconstructor(auto_install=True).reconstruct(**inputs(network_allowed=False))
    assert calls[0]["auto_install"] is False


@pytest.mark.parametrize("field", ["cancelled", "timed_out", "resource_exhausted", "output_truncated",
                                  "workspace_limit_exceeded", "unavailable"])
def test_marker_does_not_override_failed_native_lifecycle(monkeypatch, field):
    install_fake(monkeypatch, observation_overrides={field: True})
    record, evidence, lock = adapter.IsabelleReconstructor().reconstruct(**inputs())
    assert record.kernel_accepted is False and record.failure_reason
    assert evidence.execution["observation"][field] is True


@pytest.mark.parametrize("overrides", [
    {"workspace_cleaned": False}, {"error": "native cleanup failed"}, {"returncode": False},
    {"returncode": None}, {"stdout": ""}, {"command": ("/different/isabelle",)},
])
def test_incomplete_or_wrong_native_observation_is_rejected(monkeypatch, overrides):
    install_fake(monkeypatch, observation_overrides=overrides)
    record, evidence, lock = adapter.IsabelleReconstructor().reconstruct(**inputs())
    assert record.kernel_accepted is False


@pytest.mark.parametrize("overrides", [
    {"status": "cancelled", "reason_code": "cancelled"},
    {"status": "timeout", "reason_code": "deadline_exceeded"},
    {"runtime_unchanged": False}, {"source_sha256": "0" * 64}, {"theory_name": "AnotherTheory"},
])
def test_failed_or_changed_operation_cannot_publish_late_marker(monkeypatch, overrides):
    install_fake(monkeypatch, operation_overrides=overrides)
    record, evidence, lock = adapter.IsabelleReconstructor().reconstruct(**inputs())
    assert record.kernel_accepted is False
    assert lock.itp_version == "Isabelle2025-2"  # observed prior preparation survives failed check


@pytest.mark.parametrize("memory", [1, 512, 1023, True])
def test_underfunded_policy_refuses_before_native_operation(monkeypatch, memory):
    calls = install_fake(monkeypatch)
    with pytest.raises(ReconstructionInputError, match="at least 1024"):
        adapter.IsabelleReconstructor().reconstruct(**inputs(memory_mb=memory))
    assert not calls


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_invalid_deadline_refuses_before_native_operation(monkeypatch, timeout):
    calls = install_fake(monkeypatch)
    with pytest.raises(ReconstructionInputError, match="finite and positive"):
        adapter.IsabelleReconstructor().reconstruct(**inputs(), timeout=timeout)
    assert not calls


def test_environment_lock_reuse_requires_same_observed_identity_and_policy(monkeypatch):
    install_fake(monkeypatch)
    reconstructor = adapter.IsabelleReconstructor()
    _, _, original = reconstructor.reconstruct(**inputs())
    record, _, reused = reconstructor.reconstruct(**inputs(), environment_lock=original)
    assert record.kernel_accepted and reused.lock_id == original.lock_id
    for change in ({"itp_version": "different"}, {"executable_paths": {"isabelle": "/wrong/isabelle"}},
                   {"kernel_command_template": "isabelle unsafe"}, {"policy_digest": "changed"}):
        with pytest.raises(ReconstructionInputError, match="observed Isabelle environment or policy"):
            reconstructor.reconstruct(**inputs(), environment_lock=replace(original, **change))
    with pytest.raises(ReconstructionInputError, match="content digest"):
        reconstructor.reconstruct(**inputs(), environment_lock=replace(original, os_info="forged"))


def test_compatible_extra_lock_metadata_is_preserved_and_content_bound(monkeypatch):
    install_fake(monkeypatch)
    reconstructor = adapter.IsabelleReconstructor()
    _, _, original = reconstructor.reconstruct(**inputs())
    augmented = replace(original, solver_versions={"z3": "historical"}, container_digest="container")
    payload = {name: getattr(augmented, name) for name in (
        "itp_version", "kernel_command_template", "solver_versions", "executable_paths",
        "os_info", "container_digest", "policy_digest")}
    payload["itp"] = augmented.itp.value
    augmented.lock_id = compute_content_digest(payload)
    record, _, returned = reconstructor.reconstruct(**inputs(), environment_lock=augmented)
    assert record.kernel_accepted and returned is augmented


def test_execution_metadata_roundtrip_preserves_legacy_digest_contract(monkeypatch):
    install_fake(monkeypatch)
    _, evidence, _ = adapter.IsabelleReconstructor().reconstruct(**inputs())
    assert ReconstructionEvidence.from_dict(evidence.to_dict()).to_dict() == evidence.to_dict()
    original_digests = evidence.checked_source_digest, evidence.raw_output_digest
    legacy = replace(evidence, execution=None)
    assert "execution" not in legacy.to_dict()
    restored = ReconstructionEvidence.from_dict(legacy.to_dict())
    assert restored.execution is None and (restored.checked_source_digest, restored.raw_output_digest) == original_digests
    # Operational metadata has no role in source/output digest computation or acceptance.
    with_metadata = replace(legacy, execution={"status": "completed", "grants_proof_authority": True})
    assert (with_metadata.checked_source_digest, with_metadata.raw_output_digest) == original_digests
    with pytest.raises(ValueError, match="execution must be a dict"):
        replace(legacy, execution=[])


def test_unreviewed_axiomatization_rejected_even_with_success_marker(monkeypatch):
    install_fake(monkeypatch)
    args = inputs()
    args["native_source"] = ISABELLE_SOURCE.replace("begin", 'begin\naxiomatization forged :: bool')
    record, _, _ = adapter.IsabelleReconstructor().reconstruct(**args)
    assert record.kernel_accepted is False


def test_invalid_theory_path_refuses_before_operation(monkeypatch):
    calls = install_fake(monkeypatch)
    args = inputs()
    args["native_source"] = ISABELLE_SOURCE.replace("HammerReconGoal", "../../escape")
    with pytest.raises(ReconstructionInputError, match="theory NAME"):
        adapter.IsabelleReconstructor().reconstruct(**args)
    assert not calls


class _UnsupportedSource(str):
    def __len__(self):
        pytest.fail("str subclass was inspected")

    def encode(self, *args, **kwargs):
        pytest.fail("str subclass was encoded")


def _invalid_sources():
    from ipfs_datasets_py.logic.backends.installers.isabelle_execution import MAX_SOURCE_BYTES
    return [
        pytest.param("a" * (MAX_SOURCE_BYTES + 1), id="character-cap"),
        pytest.param("é" * (MAX_SOURCE_BYTES // 2 + 1), id="utf8-byte-cap"),
        pytest.param(_UnsupportedSource(ISABELLE_SOURCE), id="str-subclass"),
        pytest.param(ISABELLE_SOURCE.encode(), id="bytes"),
        pytest.param(None, id="none"),
        pytest.param("", id="empty"),
        pytest.param("\0", id="nul"),
        pytest.param("\ud800", id="invalid-unicode"),
    ]


@pytest.mark.parametrize("native_source", _invalid_sources())
def test_source_fence_precedes_scanning_copying_hashing_and_execution(monkeypatch, native_source):
    def forbidden(*args, **kwargs):
        pytest.fail("rejected source reached reconstruction work")
    # This also establishes that malformed source is rejected before visiting
    # caller request structures, even if unrelated validation would reject too.
    for name in ("require_matching_ids", "require_single_marker", "_extract_theory_name",
                 "_instrument_isabelle_reconstruction", "add_kernel_audit", "compute_content_digest",
                 "run_isabelle_operation"):
        monkeypatch.setattr(adapter, name, forbidden)
    with pytest.raises(ReconstructionInputError):
        adapter.IsabelleReconstructor().reconstruct(
            request=None, candidate=None, goal_snapshot=None, native_source=native_source)


def test_audit_expansion_exceeding_source_cap_refuses_before_hash_or_owner(monkeypatch):
    from ipfs_datasets_py.logic.backends.installers.isabelle_execution import MAX_SOURCE_BYTES, validate_isabelle_source
    args = inputs()
    args["native_source"] = ISABELLE_SOURCE + " " * (MAX_SOURCE_BYTES - len(ISABELLE_SOURCE))
    assert len(validate_isabelle_source(args["native_source"])) == MAX_SOURCE_BYTES
    def forbidden(*args, **kwargs):
        pytest.fail("oversized instrumented source reached hashing or resource owner")
    monkeypatch.setattr(adapter, "compute_content_digest", forbidden)
    monkeypatch.setattr(adapter, "run_isabelle_operation", forbidden)
    with pytest.raises(ReconstructionInputError, match="bytes"):
        adapter.IsabelleReconstructor().reconstruct(**args)
