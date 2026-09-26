"""Opt-in owner shadow evidence with explicitly synthetic child execution.

The shared fixture changes a native state and writes a full compact checkpoint;
it does not run the daemon, train a model, or establish native learning. These
tests run the real endpoint diff/replay and owner journal/CAS paths. The full
checkpoint remains authoritative; the shadow is only durable diagnostic data.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation as owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_contracts as contracts
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_shadow_evidence as evidence
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_sparse_shadow as shadow
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_operation_journal import DaemonOperationJournalError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import decode_patch, replay_patch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_diff import exact_state_snapshot
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_invocation import (
    journal_for, prepare, setup, _explicit_weight_reference,
)


@pytest.fixture
def shadow_setup(setup):
    setup.shadows = []
    setup.shadow_fault = None

    def verify_shadow(query, native, result):
        launch = contracts.parse_json(contracts.verify(query["launch"]))
        request = contracts.parse_json(contracts.verify(launch["request"]))
        if request.get("sparse_shadow") is not True:
            return
        # Explicit fixture declarations, not evidence of OS enforcement or native execution.
        result.update(schema=contracts.RESULT_SCHEMA, mode="verify",
            binding={"request_sha256": launch["request"]["sha256"], "launch_sha256": query["launch"]["sha256"]},
            network_guard={"socket_denial_verified": True},
            guards={"source_before": True, "source_after": True, "inputs_after": True})
        loaded = contracts.load_full_checkpoint(query["candidate"], compact_only=True)
        result["metric_state_identity"] = loaded.state.state_identity_record(
            metric_lineage=contracts.METRIC_LINEAGE).to_dict()
        output = Path(launch["attempt_directory"]) / "sparse-shadow"
        output.mkdir()
        result["sparse_shadow"] = shadow.write_checkpoint_shadow(
            request["base_artifact"], query["candidate"],
            base_version_id=request["base_version_id"], output_directory=output,
            provenance=evidence.shadow_provenance(request_ref=launch["request"],
                launch_ref=query["launch"], native_result_ref=query["native_result"]))
        setup.shadows.append(deepcopy(result["sparse_shadow"]))
        if setup.shadow_fault:
            setup.shadow_fault(query, request, launch, result)

    setup.child.verify_hook = verify_shadow
    return setup


def _reseal_shadow(value):
    """Pair a forged observation with its saved receipt to test deeper checks."""
    path = Path(value["receipt_ref"]["path"])
    path.write_bytes(contracts.canonical({key: item for key, item in value.items() if key != "receipt_ref"}))
    value["receipt_ref"] = contracts.describe(path)


def _assert_no_completion(case, prepared):
    assert case.registry.get_run("owned-run")["status"] != "completed"
    with journal_for(prepared) as journal:
        assert "complete" not in journal.operations()
        assert journal.get_metadata("quarantine") is not None


def test_default_request_and_completion_omit_shadow_and_never_build_it(shadow_setup):
    prepared = prepare(shadow_setup)
    request = contracts.read_json(prepared["request"]["path"])
    assert request["schema"] == contracts.REQUEST_SCHEMA
    assert "sparse_shadow" not in request
    result = owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    stored = shadow_setup.registry.get_version(result["completion"]["version_id"])["metadata"]["result"]
    assert set(stored["evidence"]) == {
        "launch", "native_result", "owner_verification", "summary_artifact", "log_artifact"}
    assert "sparse_shadow" not in result["owner_verification"]
    assert shadow_setup.shadows == []
    assert not list(shadow_setup.output.glob("attempt-*/sparse-shadow"))


def test_v2_request_is_sealed_and_preparation_retry_does_not_regenerate(shadow_setup):
    prepared = prepare(shadow_setup, sparse_shadow=True)
    request = contracts.parse_json(contracts.verify(prepared["request"]))
    assert request["schema"] == contracts.SHADOW_REQUEST_SCHEMA
    assert request["sparse_shadow"] is True
    assert prepared["binding"]["schema"] == contracts.SHADOW_REQUEST_SCHEMA
    assert shadow_setup.registry.get_run("owned-run")["spec"]["schema"] == contracts.SHADOW_REQUEST_SCHEMA
    assert prepare(shadow_setup, sparse_shadow=True) == prepared
    assert shadow_setup.child.calls == ["describe"]


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_prepare_rejects_non_boolean_opt_in_before_journal_or_child(shadow_setup, value):
    with pytest.raises(contracts.DaemonInvocationError, match="must be a bool"):
        prepare(shadow_setup, sparse_shadow=value)
    assert shadow_setup.child.calls == []
    assert not list(shadow_setup.output.iterdir())


@pytest.mark.parametrize("first", [False, True])
def test_preparation_retry_cannot_change_sealed_shadow_policy(shadow_setup, first):
    prepared = prepare(shadow_setup, sparse_shadow=first)
    before = contracts.verify(prepared["request"])
    with pytest.raises(DaemonOperationJournalError, match="binding"):
        prepare(shadow_setup, sparse_shadow=not first)
    assert contracts.verify(prepared["request"]) == before
    assert shadow_setup.child.calls == ["describe"]
    assert shadow_setup.registry.get_run("owned-run")["status"] == "queued"


@pytest.mark.parametrize("mapped_weights", [False, True])
def test_full_candidate_stays_authoritative_with_exact_durable_shadow_evidence(shadow_setup, mapped_weights):
    weights = _explicit_weight_reference(shadow_setup) if mapped_weights else None
    prepared = prepare(shadow_setup, sparse_shadow=True, arrow_feature_weights=weights)
    head = shadow_setup.registry.resolve_head("english-0", "best")
    request = contracts.parse_json(contracts.verify(prepared["request"]))
    assert request["schema"] == (contracts.WEIGHT_REQUEST_SCHEMA if mapped_weights else contracts.SHADOW_REQUEST_SCHEMA)
    result = owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    version = shadow_setup.registry.get_version(result["completion"]["version_id"])
    stored = version["metadata"]["result"]
    observed = result["owner_verification"]["sparse_shadow"]
    refs = stored["evidence"]
    assert set(refs) == {"launch", "native_result", "owner_verification", "summary_artifact", "log_artifact",
                         "sparse_shadow_patch", "sparse_shadow_receipt"}
    for name in ("sparse_shadow_patch", "sparse_shadow_receipt"):
        assert shadow_setup.registry.verify_artifact(refs[name]) == refs[name]
    persisted = contracts.parse_json(shadow_setup.registry.artifact_path(refs["sparse_shadow_receipt"]).read_bytes())
    assert persisted == {key: value for key, value in observed.items() if key != "receipt_ref"}
    audit = contracts.parse_json(shadow_setup.registry.artifact_path(refs["owner_verification"]).read_bytes())
    assert audit["sparse_shadow"] == observed
    expected_context = {"integration": "owned-daemon-independent-verifier-v1",
                        "request": stored["request_artifact"], "launch": refs["launch"],
                        "native_result": refs["native_result"]}
    patch_bytes = shadow_setup.registry.artifact_path(refs["sparse_shadow_patch"]).read_bytes()
    segment = decode_patch(patch_bytes)
    assert segment.provenance["context"] == expected_context
    assert segment.base_version_id == version["parent_version_id"] == request["base_version_id"]
    assert version["artifact"] == {key: observed["final_artifact"][key] for key in ("sha256", "bytes")}
    assert version["artifact"] != refs["sparse_shadow_patch"]
    final = contracts.load_full_checkpoint({**version["artifact"],
        "path": str(shadow_setup.registry.artifact_path(version["artifact"]))}, compact_only=True).state
    base = contracts.load_full_checkpoint(request["base_artifact"]).state
    replay_patch(base, patch_bytes, expected_base_version_id=request["base_version_id"], expected_sequence=0)
    assert exact_state_snapshot(base) == exact_state_snapshot(final)
    assert contracts.canonical(base.to_dict()) == contracts.canonical(final.to_dict())
    assert observed["checks"]["compact_final_bytes_exact"] is True
    assert observed["full_checkpoint_authoritative"] is True
    assert all(observed[key] is False for key in (
        "registered_base_authority_verified", "optimizer_acceptance_asserted", "intermediate_mutations_replayed",
        "admitted", "promoted", "publication_performed"))
    assert stored["accepted_projection_epochs"] == 1  # Fixture value, not native optimizer evidence.
    assert stored["evaluation_matches_final"] is False
    assert shadow_setup.registry.resolve_head("english-0", "best") == head
    assert not shadow_setup.registry.pending_outbox("huggingface")
    ledger = json.loads(Path(shadow_setup.policy["ledger_path"]).read_bytes())
    assert {row["status"] for row in ledger["reservations"].values()} == {"released"}


@pytest.mark.parametrize("tamper", [
    "replay_check", "authority_claim", "endpoint", "provenance", "revision_type", "revision_bool",
    "component_inventory", "raw_digest", "changed_count", "compact_digest", "patch_ref_path",
])
def test_paired_resealed_shadow_tampering_cannot_complete(shadow_setup, tamper):
    prepared = prepare(shadow_setup, sparse_shadow=True)
    head = shadow_setup.registry.resolve_head("english-0", "best")

    def corrupt(query, request, launch, result):
        value = result["sparse_shadow"]
        if tamper == "replay_check":
            value["checks"]["all_native_components_exact"] = 1  # Equal by ==, but not an exact bool.
        elif tamper == "authority_claim":
            value["registered_base_authority_verified"] = True
        elif tamper == "endpoint":
            value["final_artifact"] = request["base_artifact"]
        elif tamper == "provenance":
            value["provenance"]["context"]["launch"]["sha256"] = "0" * 64
        elif tamper == "revision_type":
            snapshot = value["capture_report"]["result_snapshot"]
            snapshot["state_revision"] = float(snapshot["state_revision"])
        elif tamper == "revision_bool":
            value["capture_report"]["base_snapshot"]["state_revision"] = False
        elif tamper == "component_inventory":
            value["capture_report"]["result_snapshot"]["components"].pop("applied_todo_ids")
        elif tamper == "raw_digest":
            value["capture_report"]["result_snapshot"]["raw_state_sha256"] = "0" * 64
        elif tamper == "changed_count":
            value["capture_report"]["counts"]["changed_component_count"] += 1
        elif tamper == "compact_digest":
            value["regenerated_compact_checkpoint"]["sha256"] = "0" * 64
        elif tamper == "patch_ref_path":
            outside = Path(launch["attempt_directory"]) / "outside-patch.json"
            outside.write_bytes(contracts.verify(value["patch_ref"]))
            value["patch_ref"] = contracts.describe(outside)
        _reseal_shadow(value)

    shadow_setup.shadow_fault = corrupt
    with pytest.raises(contracts.DaemonInvocationError, match="sparse shadow"):
        owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    _assert_no_completion(shadow_setup, prepared)
    assert shadow_setup.registry.resolve_head("english-0", "best") == head


@pytest.mark.parametrize("tamper", ["request_binding", "source_guard"])
def test_shadow_requires_matching_supervised_verifier_binding_and_guards(shadow_setup, tamper):
    prepared = prepare(shadow_setup, sparse_shadow=True)

    def corrupt(query, request, launch, result):
        if tamper == "request_binding":
            result["binding"]["request_sha256"] = "0" * 64
        else:
            result["guards"]["source_after"] = False

    shadow_setup.shadow_fault = corrupt
    with pytest.raises(contracts.DaemonInvocationError, match="sparse shadow"):
        owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    _assert_no_completion(shadow_setup, prepared)


@pytest.mark.parametrize("target", ["patch_ref", "receipt_ref", "returned_receipt"])
def test_shadow_files_and_returned_receipt_must_remain_bound(shadow_setup, target):
    prepared = prepare(shadow_setup, sparse_shadow=True)

    def corrupt(query, request, launch, result):
        value = result["sparse_shadow"]
        if target == "returned_receipt":
            value["timings"]["fixture_changed_return"] = 1
        else:
            Path(value[target]["path"]).write_bytes(b'{"fixture_changed_bytes":true}')

    shadow_setup.shadow_fault = corrupt
    with pytest.raises(contracts.DaemonInvocationError, match="checksum|observed shadow"):
        owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    _assert_no_completion(shadow_setup, prepared)


@pytest.mark.parametrize("mapped_weights", [False, True])
def test_default_rejects_unsolicited_shadow_instead_of_registering_it(shadow_setup, mapped_weights):
    weights = _explicit_weight_reference(shadow_setup) if mapped_weights else None
    prepared = prepare(shadow_setup, arrow_feature_weights=weights)
    shadow_setup.child.verify_hook = lambda query, native, result: result.update(sparse_shadow={})
    with pytest.raises(contracts.DaemonInvocationError, match="without a sealed request"):
        owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    _assert_no_completion(shadow_setup, prepared)


def test_requested_shadow_failure_quarantines_and_never_reexecutes(shadow_setup):
    prepared = prepare(shadow_setup, sparse_shadow=True)
    failure = OSError("synthetic shadow publication failure after endpoint verification")

    def fail(query, request, launch, result):
        raise failure

    shadow_setup.shadow_fault = fail
    with pytest.raises(OSError) as caught:
        owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    assert caught.value is failure
    _assert_no_completion(shadow_setup, prepared)
    before = list(shadow_setup.child.calls)
    with pytest.raises(contracts.DaemonInvocationError, match="quarantine"):
        owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    assert shadow_setup.child.calls == before
    assert len(shadow_setup.shadows) == 1


@pytest.mark.parametrize("name", ["patch.json", "receipt.json"])
def test_staging_uses_original_shadow_descriptor_after_validation(shadow_setup, monkeypatch, name):
    prepared = prepare(shadow_setup, sparse_shadow=True)
    original = evidence.validate_owned_shadow_evidence
    changed = []

    def change_after_validation(value, **kwargs):
        refs = original(value, **kwargs)
        path = Path(kwargs["attempt"]) / "sparse-shadow" / name
        path.write_bytes(b'{"fixture_changed_after_validation":true}')
        changed.append(path)
        return refs

    monkeypatch.setattr(evidence, "validate_owned_shadow_evidence", change_after_validation)
    with pytest.raises((contracts.DaemonInvocationError, RegistryError), match="checksum|digest"):
        owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    assert changed
    _assert_no_completion(shadow_setup, prepared)


def _delete_shadow_evidence(case, result, prepared):
    """Remove both local and CAS copies; historical replay cannot need either."""
    stored = result["evidence"]
    for name in ("sparse_shadow_patch", "sparse_shadow_receipt", "owner_verification"):
        case.registry.artifact_path(stored[name]).unlink()
    for descriptor in case.shadows:
        for name in ("patch_ref", "receipt_ref"):
            Path(descriptor[name]["path"]).unlink()
    Path(prepared["request"]["path"]).unlink()


def test_committed_replay_precedes_deleted_shadow_and_all_new_diagnostic_work(shadow_setup, monkeypatch):
    prepared = prepare(shadow_setup, sparse_shadow=True)
    result = owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    version = shadow_setup.registry.get_version(result["completion"]["version_id"])
    _delete_shadow_evidence(shadow_setup, version["metadata"]["result"], prepared)
    shadow_setup.registry.artifact_path(version["artifact"]).unlink()
    before_calls = list(shadow_setup.child.calls)
    ledger = Path(shadow_setup.policy["ledger_path"]).read_bytes()

    def unexpected(*args, **kwargs):
        pytest.fail("historical completion must resolve before any new shadow work")

    monkeypatch.setattr(evidence, "validate_owned_shadow_evidence", unexpected)
    monkeypatch.setattr(shadow, "write_checkpoint_shadow", unexpected)
    replay = owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    assert replay["completion"] == result["completion"]
    assert replay["historical_retry"] is True
    assert replay["current_artifact_availability_checked"] is False
    assert shadow_setup.child.calls == before_calls
    assert Path(shadow_setup.policy["ledger_path"]).read_bytes() == ledger


def test_lost_complete_response_recovers_after_restart_without_shadow_or_candidate(shadow_setup, monkeypatch):
    prepared = prepare(shadow_setup, sparse_shadow=True)
    complete, resolve = shadow_setup.registry.complete_run, shadow_setup.registry.resolve_operation
    committed = [False]
    failure = OSError("synthetic shadow completion response lost")

    def lost_complete(*args, **kwargs):
        complete(*args, **kwargs)
        committed[0] = True
        raise failure

    def lost_lookup(*args, **kwargs):
        if committed[0]:
            raise OSError("synthetic operation lookup unavailable")
        return resolve(*args, **kwargs)

    monkeypatch.setattr(shadow_setup.registry, "complete_run", lost_complete)
    monkeypatch.setattr(shadow_setup.registry, "resolve_operation", lost_lookup)
    with pytest.raises(OSError) as caught:
        owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    assert caught.value is failure
    with journal_for(prepared) as journal:
        pending = journal.pending()["complete"]
    expected = resolve(pending["operation_id"], "CompleteRun", pending["payload"])
    _delete_shadow_evidence(shadow_setup, pending["payload"]["result"], prepared)
    shadow_setup.registry.artifact_path(pending["payload"]["artifact"]).unlink()
    shadow_setup.registry.close()
    before = list(shadow_setup.child.calls)
    with AutoencoderRegistry(shadow_setup.database, shadow_setup.cas, clock=lambda: shadow_setup.clock[0]) as registry:
        assert registry.owner_generation > pending["payload"]["lease"]["owner_generation"]
        replay = owner.run_owned_daemon_invocation(registry, prepared)
        assert replay["completion"] == expected
        assert replay["historical_retry"] is True
        assert replay["current_artifact_availability_checked"] is False
        assert shadow_setup.child.calls == before
        assert registry.get_run("owned-run")["status"] == "completed"
    with journal_for(prepared) as journal:
        assert journal.pending() == {}
        assert journal.operations()["complete"]["receipt"] == expected


def test_lease_expiry_after_shadow_cannot_complete_or_claim_again(shadow_setup):
    prepared = prepare(shadow_setup, sparse_shadow=True)

    def expire(query, request, launch, result):
        shadow_setup.clock[0] += 1000

    shadow_setup.shadow_fault = expire
    with pytest.raises(RegistryError, match="stale"):
        owner.run_owned_daemon_invocation(shadow_setup.registry, prepared)
    assert len(shadow_setup.shadows) == 1
    assert shadow_setup.registry.get_run("owned-run")["attempt"] == 1
    _assert_no_completion(shadow_setup, prepared)
