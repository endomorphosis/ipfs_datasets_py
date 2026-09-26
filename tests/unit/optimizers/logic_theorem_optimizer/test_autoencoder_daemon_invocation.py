"""Owned coordination with real registries and explicit synthetic child results.

The fixture child writes and independently loads a real compact checkpoint. It
does not run the daemon, native bridges, an optimizer, or a model, and is never
native qualification evidence. Resource admission uses a test-local scheduler.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation as owner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_contracts as contracts
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_corpus_inputs as inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_operation_journal import (
    DurableDaemonOperationJournal, DaemonOperationJournalError,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import serialize_checkpoint
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig


_inputs_fixture = runpy.run_path(str(Path(__file__).with_name("test_autoencoder_daemon_corpus_inputs.py")))


class SyntheticChild:
    """Explicit unit-only subprocess-boundary injection with actual file codecs."""

    def __init__(self):
        self.calls = []
        self.cycles = 1
        self.failure_mode = None
        self.execute_hook = None
        self.verify_hook = None

    def __call__(self, mode, query, output, *, cwd, environment, reservation,
                 timeout_seconds, heartbeat=lambda: None):
        self.calls.append(mode)
        reservation.check_usage(cwd)
        heartbeat()
        value = contracts.read_json(query)
        if mode == self.failure_mode:
            raise contracts.DaemonInvocationError(f"synthetic {mode} failure")
        if mode == "describe":
            base = contracts.load_full_checkpoint(value["base_artifact"])
            argv = value["daemon_argv"]
            result = {
                "success": True,
                "effective_arguments": {"run_id": argv[argv.index("--run-id") + 1],
                                        "autoencoder_corpus_input": value["input_snapshot"]["path"],
                                        "autoencoder_corpus_input_sha256": value["input_snapshot"]["sha256"],
                                        "autoencoder_corpus_input_bytes": value["input_snapshot"]["bytes"],
                                        "synthetic_fixture": True},
                "base_identity": base.state.state_identity_record().to_dict(),
                "producer_identity": {"schema": "synthetic-fixture-only", "code_sha256": {}},
            }
        elif mode == "execute":
            launch = value
            request = contracts.read_json(launch["request"]["path"])
            state = contracts.load_full_checkpoint(request["base_artifact"]).state
            state.feature_embedding_weights["synthetic-owner-test"] = [0.25, -0.0]
            state.applied_todo_ids.append("synthetic-accepted-update")
            candidate = cwd / "synthetic-final.compact"
            candidate.write_bytes(serialize_checkpoint(state, metadata={
                "fixture": True, "run_id": request["run_id"],
                "input_descriptor": request["input_snapshot"],
            }))
            result = {"schema": contracts.RESULT_SCHEMA, "success": True,
                      "synthetic_fixture": True, "completed_cycles": self.cycles,
                      "final_checkpoint": contracts.describe(candidate),
                      "summary_artifact": contracts.write_new(cwd / "synthetic-summary.json", {
                          "synthetic_fixture": True, "completed_cycles": self.cycles}),
                      "log_artifact": contracts.write_new(cwd / "synthetic-events.json", {
                          "synthetic_fixture": True, "event": "fixture_finished"})}
            if self.execute_hook:
                self.execute_hook(launch, request, result)
        elif mode == "verify":
            native = contracts.read_json(value["native_result"]["path"])
            if native["completed_cycles"] != 1:
                raise contracts.DaemonInvocationError("synthetic verifier rejects zero completed cycles")
            for name in ("summary_artifact", "log_artifact"):
                diagnostic = contracts.parse_json(contracts.verify(native[name]))
                assert diagnostic["synthetic_fixture"] is True
            loaded = contracts.load_full_checkpoint(value["candidate"], compact_only=True)
            assert "synthetic-accepted-update" in loaded.state.applied_todo_ids
            assert loaded.state.feature_embedding_weights["synthetic-owner-test"] == [0.25, -0.0]
            result = {"success": True, "synthetic_fixture": True,
                      "state_identity": loaded.state.state_identity_record().to_dict(),
                      "evaluation_matches_final": False, "accepted_projection_epochs": 1}
            if self.verify_hook:
                self.verify_hook(value, native, result)
        else:
            raise AssertionError(f"unexpected fixture mode {mode}")
        if mode in {"describe", "verify"}:
            settings = value if mode == "describe" else contracts.read_json(
                contracts.read_json(value["launch"]["path"])["request"]["path"])
            if "arrow_feature_weights" in settings:
                # Real sidecar/base verification around an explicitly synthetic
                # child boundary; this is not native runner evidence.
                from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_weight_session import VerifiedDaemonWeightSession
                base = contracts.load_full_checkpoint(settings["base_artifact"])
                session = VerifiedDaemonWeightSession(settings["arrow_feature_weights"],
                    base_artifact=settings["base_artifact"],
                    base_identity=base.state.state_identity_record().to_dict())
                try:
                    session.verify_base_state(base.state)
                    session.verify_boundary("synthetic_owner_fixture")
                finally:
                    session.close()
                result["arrow_feature_weights"] = session.summary()
        contracts.write_new(output, result)
        return result


@pytest.fixture
def setup(tmp_path, monkeypatch):
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(
        total_cpu_slots=4, total_memory_mb=8192, total_child_process_slots=4,
        lane_reservations={}, state_path=tmp_path / "scheduler.json", auto_renew_leases=False))
    monkeypatch.setattr(resources, "get_global_resource_scheduler", lambda: scheduler)
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    output = campaign / "owned-invocation"
    output.mkdir()
    database, cas = campaign / "registry.duckdb", campaign / "cas"
    clock = [1_800_000_000.0]
    registry = AutoencoderRegistry(database, cas, clock=lambda: clock[0])
    spec = _inputs_fixture["_prepare"](registry, campaign)
    exported = inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="export-inputs")
    policy = {"ledger_path": str(tmp_path / "disk-ledger.json"), "roots": [str(campaign)],
              "storage_bytes": 16 * 1024 * 1024, "memory_mb": 512, "cpu_slots": 1}
    child = SyntheticChild()
    monkeypatch.setattr(owner, "_child", child)
    arguments = ["--run-id", "owned-run", "--max-cycles", "1"]
    values = SimpleNamespace(registry=registry, spec=spec, exported=exported, output=output,
                             policy=policy, child=child, argv=arguments, clock=clock,
                             database=database, cas=cas, campaign=campaign)
    try:
        yield values
    finally:
        registry.close()


def prepare(setup, **changes):
    values = {"run_id": "owned-run", "variant_id": "english-0", "base_version_id": setup.spec.base_version_id,
              "input_snapshot": setup.exported["descriptor"], "daemon_argv": setup.argv,
              "output_directory": setup.output, "resource_policy": setup.policy}
    values.update(changes)
    return owner.prepare_daemon_invocation(setup.registry, **values)


def journal_for(prepared):
    return DurableDaemonOperationJournal(prepared["journal_path"], prepared["binding"])


def test_preparation_is_input_bound_distinct_unleased_run_and_idempotent(setup):
    initial_head = setup.registry.resolve_head("english-0", "best")
    anchor_before = setup.registry.get_run(setup.spec.run_id)
    prepared = prepare(setup)
    request = contracts.read_json(prepared["request"]["path"])
    assert request["input_snapshot"] == setup.exported["descriptor"]
    assert request["base_artifact"]["sha256"] == setup.spec.base_checkpoint.sha256
    assert request["base_version_id"] == setup.spec.base_version_id
    assert setup.registry.get_run("owned-run")["status"] == "queued"
    assert setup.registry.get_run("owned-run")["lease"] is None
    assert setup.registry.get_run(setup.spec.run_id) == anchor_before
    assert prepare(setup) == prepared
    assert setup.child.calls == ["describe"]
    assert setup.registry.resolve_head("english-0", "best") == initial_head


def test_preparation_recovers_sealed_request_before_create_intent_exists(setup, monkeypatch):
    original = DurableDaemonOperationJournal.invoke
    failure = OSError("synthetic interruption before create intent")

    def interrupt(self, registry, slot, command, payload):
        if command == "CreateRun":
            raise failure
        return original(self, registry, slot, command, payload)

    monkeypatch.setattr(DurableDaemonOperationJournal, "invoke", interrupt)
    with pytest.raises(OSError) as caught:
        prepare(setup)
    assert caught.value is failure
    binding = {"schema": contracts.REQUEST_SCHEMA, "run_id": "owned-run", "variant_id": "english-0",
               "base_version_id": setup.spec.base_version_id}
    with DurableDaemonOperationJournal(setup.output / "owner-operations.json", binding) as journal:
        saved = journal.get_metadata("prepared")
        assert saved is not None
        assert journal.operations() == {}
    with pytest.raises(RegistryError, match="unknown run"):
        setup.registry.get_run("owned-run")
    monkeypatch.setattr(DurableDaemonOperationJournal, "invoke", original)
    assert prepare(setup) == saved
    assert setup.child.calls == ["describe"]
    assert setup.registry.get_run("owned-run")["status"] == "queued"


def test_complete_full_compact_synthetic_candidate_without_head_or_publication(setup):
    prepared = prepare(setup)
    initial_head = setup.registry.resolve_head("english-0", "best")
    result = owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert result["admitted"] is False
    assert result["historical_retry"] is False
    completion = result["completion"]
    assert completion["status"] == "completed" and completion["promoted"] is False
    version = setup.registry.get_version(completion["version_id"])
    assert version["parent_version_id"] == setup.spec.base_version_id
    stored = version["metadata"]["result"]
    assert stored["admitted"] is False
    assert stored["publication_performed"] is False
    assert stored["evaluation_matches_final"] is False
    assert stored["accepted_projection_epochs"] == 1  # explicitly synthetic
    assert set(stored["evidence"]) == {
        "launch", "native_result", "owner_verification", "summary_artifact", "log_artifact"}
    for name in ("summary_artifact", "log_artifact"):
        artifact = stored["evidence"][name]
        assert setup.registry.verify_artifact(artifact) == artifact
        assert json.loads(setup.registry.artifact_path(artifact).read_bytes())["synthetic_fixture"] is True
    loaded = contracts.load_full_checkpoint({**version["artifact"],
        "path": str(setup.registry.artifact_path(version["artifact"]))}, compact_only=True)
    assert "synthetic-accepted-update" in loaded.state.applied_todo_ids
    assert setup.registry.resolve_head("english-0", "best") == initial_head
    assert not setup.registry.pending_outbox("huggingface")
    with journal_for(prepared) as journal:
        operations = journal.operations()
        assert operations["complete"]["command"] == "CompleteRun"
        assert operations["complete"]["payload"]["result"]["admitted"] is False
        assert journal.pending() == {}
    rows = json.loads(Path(setup.policy["ledger_path"]).read_bytes())["reservations"]
    assert {row["status"] for row in rows.values()} == {"released"}


def test_committed_completion_replay_precedes_current_artifact_availability(setup):
    prepared = prepare(setup)
    result = owner.run_owned_daemon_invocation(setup.registry, prepared)
    version = setup.registry.get_version(result["completion"]["version_id"])
    setup.registry.artifact_path(version["artifact"]).unlink()
    Path(prepared["request"]["path"]).unlink()
    before_calls = list(setup.child.calls)
    replay = owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert replay["completion"] == result["completion"]
    assert replay["historical_retry"] is True
    assert replay["current_artifact_availability_checked"] is False
    assert setup.child.calls == before_calls


def test_ambiguous_completion_recovers_after_owner_restart_without_candidate_or_request(setup, monkeypatch):
    prepared = prepare(setup)
    complete = setup.registry.complete_run
    resolve = setup.registry.resolve_operation
    committed = [False]
    failure = OSError("synthetic completion response lost")

    def lost_complete(*args, **kwargs):
        complete(*args, **kwargs)
        committed[0] = True
        raise failure

    def lost_lookup(*args, **kwargs):
        if committed[0]:
            raise OSError("synthetic ledger lookup unavailable")
        return resolve(*args, **kwargs)

    monkeypatch.setattr(setup.registry, "complete_run", lost_complete)
    monkeypatch.setattr(setup.registry, "resolve_operation", lost_lookup)
    with pytest.raises(OSError) as caught:
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert caught.value is failure
    with journal_for(prepared) as journal:
        pending = journal.pending()["complete"]
        lease = pending["payload"]["lease"]
    expected = resolve(pending["operation_id"], "CompleteRun", pending["payload"])
    candidate = pending["payload"]["artifact"]
    setup.registry.artifact_path(candidate).unlink()
    Path(prepared["request"]["path"]).unlink()
    setup.registry.close()
    before_calls = list(setup.child.calls)
    with AutoencoderRegistry(setup.database, setup.cas, clock=lambda: setup.clock[0]) as registry:
        assert registry.owner_generation > lease["owner_generation"]
        replay = owner.run_owned_daemon_invocation(registry, prepared)
        assert replay["completion"] == expected
        assert replay["historical_retry"] is True
        assert setup.child.calls == before_calls
        assert registry.get_run("owned-run")["status"] == "completed"


def test_completion_receipt_write_failure_preserves_primary_and_recovers_history(setup, monkeypatch):
    prepared = prepare(setup)
    original = DurableDaemonOperationJournal._persist
    failure = OSError("synthetic final receipt fsync failure")

    def fail_receipt(self, data):
        operation = data["operations"].get("complete")
        if operation is not None and operation["receipt"] is not None:
            self._poisoned = True  # Same failure state as the real atomic writer.
            raise failure
        return original(self, data)

    monkeypatch.setattr(DurableDaemonOperationJournal, "_persist", fail_receipt)
    with pytest.raises(OSError) as caught:
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert caught.value is failure
    assert setup.registry.get_run("owned-run")["status"] == "completed"
    monkeypatch.setattr(DurableDaemonOperationJournal, "_persist", original)
    with journal_for(prepared) as journal:
        assert "complete" in journal.pending()
    before = list(setup.child.calls)
    recovered = owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert recovered["historical_retry"] is True
    assert recovered["completion"]["status"] == "completed"
    assert setup.child.calls == before


@pytest.mark.parametrize("method", ["prepare", "run"])
def test_missing_journal_cannot_create_new_authority_for_existing_invocation(setup, method):
    prepared = prepare(setup)
    Path(prepared["journal_path"]).unlink()
    before_calls = list(setup.child.calls)
    before_run = setup.registry.get_run("owned-run")
    with pytest.raises((contracts.DaemonInvocationError, DaemonOperationJournalError, FileNotFoundError)):
        prepare(setup) if method == "prepare" else owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert not Path(prepared["journal_path"]).exists()
    assert setup.registry.get_run("owned-run") == before_run
    assert setup.child.calls == before_calls


@pytest.mark.parametrize("field", ["request", "binding", "extra", "journal_path"])
def test_prepared_handle_changes_reject_before_claim(setup, field):
    prepared = prepare(setup)
    changed = deepcopy(prepared)
    if field == "request":
        changed["request"]["sha256"] = "0" * 64
    elif field == "binding":
        changed["binding"]["run_id"] = "other-run"
    elif field == "extra":
        changed["extra"] = True
    else:
        changed["journal_path"] = str(setup.output / "missing-journal.json")
    with pytest.raises((contracts.DaemonInvocationError, DaemonOperationJournalError, FileNotFoundError)):
        owner.run_owned_daemon_invocation(setup.registry, changed)
    assert setup.registry.get_run("owned-run")["status"] == "queued"
    assert setup.child.calls == ["describe"]


@pytest.mark.parametrize("field", ["run_id", "variant_id", "base_version_id", "input_snapshot", "daemon_argv", "resource_policy"])
def test_preparation_retry_cannot_change_registered_identity_or_settings(setup, field):
    prepared = prepare(setup)
    if field == "input_snapshot":
        value = {**setup.exported["descriptor"], "sha256": "0" * 64}
    elif field == "daemon_argv":
        value = [*setup.argv, "--synthetic-change"]
    elif field == "resource_policy":
        value = {**setup.policy, "memory_mb": 1024}
    else:
        value = "changed-" + field
    with pytest.raises((contracts.DaemonInvocationError, DaemonOperationJournalError)):
        prepare(setup, **{field: value})
    assert setup.registry.get_run("owned-run")["status"] == "queued"
    assert setup.child.calls == ["describe"]
    assert Path(prepared["request"]["path"]).is_file()


@pytest.mark.parametrize("kind", ["modified-bytes", "unregistered-canonical-request"])
def test_request_bytes_and_registered_spec_are_both_required(setup, kind):
    prepared = prepare(setup)
    path = Path(prepared["request"]["path"])
    if kind == "modified-bytes":
        path.write_bytes(path.read_bytes() + b" ")
    else:
        request = contracts.read_json(path)
        request["producer_identity"]["changed"] = True
        alternate = setup.output / "alternate-request.json"
        contracts.write_new(alternate, request)
        staged = setup.registry.stage_artifact(alternate)
        prepared["request"] = {**staged, "path": str(setup.registry.artifact_path(staged))}
        # A caller can alter its local bookkeeping; that cannot alter registry spec.
        with journal_for(prepared) as journal:
            journal.set_metadata("prepared", prepared)
    with pytest.raises(contracts.DaemonInvocationError):
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert setup.registry.get_run("owned-run")["status"] == "queued"
    assert setup.child.calls == ["describe"]


@pytest.mark.parametrize("staleness", ["expired", "new-owner-generation", "different-fence"])
def test_resolved_claim_must_be_current_before_any_child_launch(setup, staleness):
    prepared = prepare(setup)
    with journal_for(prepared) as journal:
        old_lease = journal.invoke(setup.registry, "claim", "ClaimRun", {
            "run_id": "owned-run", "worker_id": "native-daemon-owner", "lease_seconds": 300,
        })["lease"]
        assert journal.get_metadata("attempt") is None
    active_registry = setup.registry
    if staleness == "expired":
        setup.clock[0] = old_lease["expires_at"] + 1
    elif staleness == "new-owner-generation":
        setup.registry.close()
        active_registry = AutoencoderRegistry(setup.database, setup.cas, clock=lambda: setup.clock[0])
    else:
        setup.clock[0] = old_lease["expires_at"] + 1
        newer = active_registry.claim_run("competing-claim", "owned-run", "different-worker", 300)["lease"]
        assert newer["fence"] > old_lease["fence"]
    try:
        with pytest.raises((contracts.DaemonInvocationError, RegistryError)):
            owner.run_owned_daemon_invocation(active_registry, prepared)
        assert setup.child.calls == ["describe"]
        with journal_for(prepared) as journal:
            assert journal.get_metadata("attempt") is None
        assert not list(setup.output.glob("attempt-*"))
    finally:
        if active_registry is not setup.registry:
            active_registry.close()


@pytest.mark.parametrize("failure", ["execute", "verify", "no-cycle"])
def test_failed_or_incomplete_synthetic_candidate_never_completes(setup, failure):
    prepared = prepare(setup)
    initial_head = setup.registry.resolve_head("english-0", "best")
    if failure == "no-cycle":
        setup.child.cycles = 0
    else:
        setup.child.failure_mode = failure
    with pytest.raises(contracts.DaemonInvocationError):
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert setup.registry.get_run("owned-run")["status"] != "completed"
    assert setup.registry.resolve_head("english-0", "best") == initial_head
    with journal_for(prepared) as journal:
        assert "complete" not in journal.operations()
        assert journal.get_metadata("attempt") is not None
        assert journal.get_metadata("quarantine") is not None
    before = list(setup.child.calls)
    with pytest.raises(contracts.DaemonInvocationError, match="quarantine"):
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert setup.child.calls == before
    rows = json.loads(Path(setup.policy["ledger_path"]).read_bytes())["reservations"]
    assert "retained" in {row["status"] for row in rows.values()}


def test_candidate_corruption_before_independent_verification_cannot_complete(setup):
    prepared = prepare(setup)

    def corrupt(launch, request, result):
        candidate = Path(result["final_checkpoint"]["path"])
        candidate.write_bytes(b"corrupted final candidate")

    setup.child.execute_hook = corrupt
    with pytest.raises(contracts.DaemonInvocationError, match="checksum"):
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert setup.child.calls == ["describe", "execute"]
    assert setup.registry.get_run("owned-run")["status"] != "completed"


@pytest.mark.parametrize("name", ["summary_artifact", "log_artifact"])
def test_missing_required_diagnostic_cannot_complete(setup, name):
    prepared = prepare(setup)

    def omit(launch, request, result):
        del result[name]

    setup.child.execute_hook = omit
    with pytest.raises((KeyError, contracts.DaemonInvocationError)):
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    with journal_for(prepared) as journal:
        assert "complete" not in journal.operations()
    assert setup.registry.get_run("owned-run")["status"] != "completed"


@pytest.mark.parametrize("name", ["summary_artifact", "log_artifact"])
@pytest.mark.parametrize("mutation", ["corrupt-after-verification", "outside-attempt"])
def test_diagnostic_bytes_and_attempt_ownership_rechecked_before_completion(setup, name, mutation):
    prepared = prepare(setup)
    if mutation == "corrupt-after-verification":
        def change(query, native, result):
            Path(native[name]["path"]).write_bytes(b"changed after independent verification")
        setup.child.verify_hook = change
    else:
        def change(launch, request, result):
            outside = setup.output / ("outside-" + name + ".json")
            outside.write_bytes(Path(result[name]["path"]).read_bytes())
            result[name] = contracts.describe(outside)
        setup.child.execute_hook = change
    with pytest.raises(contracts.DaemonInvocationError, match="checksum|escaped"):
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    with journal_for(prepared) as journal:
        assert "complete" not in journal.operations()
    assert setup.registry.get_run("owned-run")["status"] != "completed"


@pytest.mark.parametrize("name", ["synthetic-summary.json", "launch.json"])
def test_evidence_staging_keeps_original_verified_descriptor(setup, monkeypatch, name):
    prepared = prepare(setup)
    original = owner.verify
    changed = []

    def change_after_last_diagnostic_check(reference, *args, **kwargs):
        raw = original(reference, *args, **kwargs)
        if Path(reference["path"]).name == "synthetic-events.json" and not changed:
            path = Path(reference["path"]).parent / name
            path.write_bytes(b'{"persistent_change_after_verification":true}')
            changed.append(path)
        return raw

    monkeypatch.setattr(owner, "verify", change_after_last_diagnostic_check)
    with pytest.raises((contracts.DaemonInvocationError, RegistryError), match="checksum|digest"):
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert changed
    with journal_for(prepared) as journal:
        assert "complete" not in journal.operations()
    assert setup.registry.get_run("owned-run")["status"] != "completed"


@pytest.mark.parametrize("mode", ["execute", "verify"])
def test_first_result_descriptor_must_match_observed_child_result(setup, monkeypatch, mode):
    prepared = prepare(setup)
    child = setup.child

    def change_result_file(actual_mode, query, output, **kwargs):
        observed = child(actual_mode, query, output, **kwargs)
        if actual_mode == mode:
            changed = deepcopy(observed)
            if mode == "execute":
                changed["completed_cycles"] = 0
            else:
                changed["accepted_projection_epochs"] = 2
            output.write_bytes(contracts.canonical(changed))
        return observed

    monkeypatch.setattr(owner, "_child", change_result_file)
    with pytest.raises(contracts.DaemonInvocationError, match="changed after supervised"):
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    with journal_for(prepared) as journal:
        assert "complete" not in journal.operations()
    assert setup.registry.get_run("owned-run")["status"] != "completed"


@pytest.mark.parametrize("observed,saved", [(True, 1), (False, 0), (1, 1.0), (-0.0, 0.0)])
def test_first_result_descriptor_preserves_json_scalar_types_and_signed_zero(tmp_path, observed, saved):
    path = tmp_path / "result.json"
    contracts.write_new(path, {"success": True, "nested": {"value": saved}})
    with pytest.raises(contracts.DaemonInvocationError, match="changed after supervised"):
        owner._result_reference(path, {"success": True, "nested": {"value": observed}})


def test_lease_loss_after_execution_never_claims_again_or_completes(setup):
    prepared = prepare(setup)

    def expire(launch, request, result):
        setup.clock[0] = launch["lease"]["expires_at"] + 1

    setup.child.execute_hook = expire
    with pytest.raises(RegistryError, match="stale"):
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert setup.registry.get_run("owned-run")["attempt"] == 1
    with journal_for(prepared) as journal:
        assert "complete" not in journal.operations()
        assert journal.pending()
    assert setup.child.calls == ["describe", "execute"]


@pytest.mark.parametrize("name,value", [("lease_seconds", True), ("lease_seconds", 0),
                                         ("timeout_seconds", float("nan")), ("timeout_seconds", 90000)])
def test_invalid_invocation_bounds_do_not_claim_or_launch(setup, name, value):
    prepared = prepare(setup)
    with pytest.raises(contracts.DaemonInvocationError):
        owner.run_owned_daemon_invocation(setup.registry, prepared, **{name: value})
    assert setup.registry.get_run("owned-run")["lease"] is None
    assert setup.child.calls == ["describe"]


def _explicit_weight_reference(case, *, wrong_rows=False):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import build_feature_embedding_weights_ipc
    version = case.registry.get_version(case.spec.base_version_id)
    base = {**version['artifact'], 'path': str(case.registry.artifact_path(version['artifact']))}
    state = contracts.load_full_checkpoint(base).state
    if wrong_rows:
        state.feature_embedding_weights['not-in-authoritative-base'] = [1.0]
    path = case.campaign / 'explicit-sidecar.arrow'
    build_feature_embedding_weights_ipc(state, path, base_checkpoint_sha256=base['sha256'])
    return contracts.describe(path, contracts.MAX_ARROW_FEATURE_WEIGHT_BYTES)


@pytest.mark.parametrize('shadow', [False, True])
def test_explicit_weight_preparation_stages_current_base_sidecar_in_closed_v3(setup, shadow):
    ref = _explicit_weight_reference(setup)
    prepared = prepare(setup, arrow_feature_weights=ref, sparse_shadow=shadow)
    request = contracts.read_json(prepared['request']['path'])
    assert request['schema'] == contracts.WEIGHT_REQUEST_SCHEMA
    assert request['sparse_shadow'] is shadow
    assert request['arrow_feature_weights'] == {
        'path': str(setup.registry.artifact_path({k: ref[k] for k in ('sha256', 'bytes')})),
        'sha256': ref['sha256'], 'bytes': ref['bytes']}
    assert request['arrow_feature_weights']['path'] != ref['path']
    assert contracts.verify(request['arrow_feature_weights']) == Path(ref['path']).read_bytes()
    assert setup.registry.get_run('owned-run')['status'] == 'queued'
    assert setup.registry.get_run('owned-run')['lease'] is None
    assert prepare(setup, arrow_feature_weights=ref, sparse_shadow=shadow) == prepared
    assert setup.child.calls == ['describe']
    with pytest.raises(contracts.DaemonInvocationError, match='retry changed'):
        prepare(setup, arrow_feature_weights=ref, sparse_shadow=not shadow)


@pytest.mark.parametrize('fault', ['bytes', 'base_rows'])
def test_weight_preparation_must_verify_before_creating_execution_run(setup, fault):
    ref = _explicit_weight_reference(setup, wrong_rows=fault == 'base_rows')
    if fault == 'bytes':
        Path(ref['path']).write_bytes(b'changed bytes')
    with pytest.raises(ValueError):
        prepare(setup, arrow_feature_weights=ref)
    with pytest.raises(RegistryError, match='unknown run'):
        setup.registry.get_run('owned-run')
    assert 'execute' not in setup.child.calls


def test_preparation_retry_cannot_replace_or_remove_sealed_weight_policy(setup):
    ref = _explicit_weight_reference(setup)
    prepared = prepare(setup, arrow_feature_weights=ref)
    with pytest.raises(contracts.DaemonInvocationError, match='retry changed'):
        prepare(setup, arrow_feature_weights={**ref, 'sha256': 'f' * 64})
    with pytest.raises(DaemonOperationJournalError):
        prepare(setup)
    duplicate = setup.campaign / 'same-sidecar-bytes.arrow'
    duplicate.write_bytes(Path(ref['path']).read_bytes())
    assert prepare(setup, arrow_feature_weights=contracts.describe(duplicate)) == prepared
    assert setup.child.calls == ['describe']


def test_v3_completion_replay_precedes_deleted_sidecar_request_and_candidate(setup):
    ref = _explicit_weight_reference(setup)
    prepared = prepare(setup, arrow_feature_weights=ref)
    request = contracts.read_json(prepared['request']['path'])
    head = setup.registry.resolve_head('english-0', 'best')
    result = owner.run_owned_daemon_invocation(setup.registry, prepared)
    version = setup.registry.get_version(result['completion']['version_id'])
    assert set(version['metadata']['result']['evidence']) == {
        'launch', 'native_result', 'owner_verification', 'summary_artifact', 'log_artifact'}
    assert result['owner_verification']['arrow_feature_weights']['base_verified'] is True
    assert result['owner_verification']['arrow_feature_weights']['closed'] is True
    Path(request['arrow_feature_weights']['path']).unlink()
    Path(prepared['request']['path']).unlink()
    setup.registry.artifact_path(version['artifact']).unlink()
    previous = list(setup.child.calls)
    replay = owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert replay['completion'] == result['completion'] and replay['historical_retry'] is True
    assert replay['current_artifact_availability_checked'] is False
    assert setup.child.calls == previous
    assert setup.registry.resolve_head('english-0', 'best') == head


def test_owner_rejects_verifier_without_exact_closed_weight_result(setup, monkeypatch):
    ref = _explicit_weight_reference(setup)
    prepared = prepare(setup, arrow_feature_weights=ref)
    original = setup.child
    def incomplete(mode, query, output, **kwargs):
        result = original(mode, query, output, **kwargs)
        if mode == 'verify':
            result['arrow_feature_weights']['provenance']['artifact']['bytes'] = float(ref['bytes'])
            Path(output).write_bytes(contracts.canonical(result))
        return result
    monkeypatch.setattr(owner, '_child', incomplete)
    with pytest.raises(contracts.DaemonInvocationError, match='feature-weight validation'):
        owner.run_owned_daemon_invocation(setup.registry, prepared)
    assert setup.registry.get_run('owned-run')['status'] == 'failed'
    with journal_for(prepared) as journal:
        assert 'complete' not in journal.operations()


@pytest.mark.parametrize('value', [False, True, {}, [], 0])
def test_weight_option_requires_an_explicit_descriptor_not_truthiness(setup, value):
    with pytest.raises(contracts.DaemonInvocationError):
        prepare(setup, arrow_feature_weights=value)
    assert setup.child.calls == []
