"""Original-campaign gateway dispatch without listeners or worker execution."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_campaign_control import OwnedCampaignControl
from ipfs_datasets_py.duckdb_control.autoencoder_quack import (
    CAMPAIGN_COMMANDS, MAX_CAMPAIGN_REQUEST_BYTES, RegistryQuackGateway,
    RegistryTransportError, WorkerScope, _envelope,
)
from ipfs_datasets_py.duckdb_control.autoencoder_quack_wire import decode_reply, make_reply
from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_training_request as codec
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_owned_training import (
    case, no_execution, _prepare_owned,
)


@pytest.fixture
def campaign(case, monkeypatch):
    handle = _prepare_owned(case)
    reference = handle["request_artifact"]
    control = OwnedCampaignControl(case.registry, worker_id="campaign-owner",
        prepared_campaigns={reference["sha256"]: handle})
    monkeypatch.setattr(control, "execute_pending", lambda **_: pytest.fail("gateway must not drain work"))
    gateway = RegistryQuackGateway(case.registry, WorkerScope(control.worker_id, control.run_ids),
        enable_prototype=True, campaign_control=control)
    try:
        yield SimpleNamespace(case=case, control=control, gateway=gateway, reference=reference)
    finally:
        control.close()


def _wire(campaign, command="SubmitCampaignTraining", operation="submit-once", **extra):
    return _envelope(command, {"request_artifact": deepcopy(campaign.reference), **extra}, operation)


def _unchanged_execution(case):
    return {"runs": [case.registry.get_run(spec.run_id) for spec in case.specs],
            "versions": [case.registry.get_version(spec.base_version_id) for spec in case.specs],
            "outbox": case.registry.pending_outbox("huggingface")}


def test_campaign_gateway_submits_reads_resolves_without_execution_or_qualification(campaign):
    before = _unchanged_execution(campaign.case)
    request = _wire(campaign)
    submitted = campaign.gateway.dispatch(request)
    assert submitted == campaign.gateway.dispatch(request)
    assert submitted["status"] == "accepted"
    resolution = campaign.gateway.dispatch(_wire(campaign, "ResolveCampaignTraining"))
    assert resolution["receipt"] == submitted and resolution["resolution"] == "committed"
    observed = campaign.gateway.dispatch(_wire(campaign, "ReadCampaignTraining", "read"))
    assert observed == campaign.control.read(campaign.reference)
    assert observed["admitted"] is False
    assert decode_reply(canonical_json_bytes(make_reply(request, result=submitted)), request) == submitted
    status = campaign.gateway.status()
    assert status["command_profile"] == "campaign_training"
    assert status["execution_in_gateway_pump"] is status["runtime_qualified"] is status["admitted"] is False
    assert status["started"] is False
    assert _unchanged_execution(campaign.case) == before
    assert all(not __import__("os").path.lexists(spec.output_directory) for spec in campaign.case.specs)


@pytest.mark.parametrize("command,payload", [
    ("ClaimRun", {"run_id": "unselected"}), ("RenewLease", {"lease": {}}),
    ("CompleteRun", {"lease": {}, "artifact": {}, "result": {}}),
    ("ReadRun", {"run_id": "unselected"}), ("ReadVersion", {"version_id": "unselected"}),
    ("SubmitOwnedInvocation", {}), ("ReadOwnedInvocation", {}), ("ResolveOwnedInvocation", {}),
])
def test_campaign_profile_cannot_use_other_command_profiles(campaign, command, payload):
    before = _unchanged_execution(campaign.case)
    with pytest.raises(RegistryTransportError, match="campaign training control profile"):
        campaign.gateway.dispatch(_envelope(command, payload, "other-profile"))
    assert _unchanged_execution(campaign.case) == before


@pytest.mark.parametrize("field", ["run_id", "path", "argv", "prepared", "training_config",
    "resource_policy", "execution_policy", "max_workers", "max_new_batches", "worker_id", "lease", "result"])
def test_campaign_payload_rejects_remote_execution_fields(campaign, field):
    with pytest.raises(RegistryTransportError, match="closed command schema"):
        campaign.gateway.dispatch(_wire(campaign, **{field: "forbidden"}))


@pytest.mark.parametrize("reference", [None, [], {}, {"sha256": "a" * 64},
    {"sha256": "A" * 64, "bytes": 1}, {"sha256": "a" * 64, "bytes": True},
    {"sha256": "a" * 64, "bytes": 1.0}, {"sha256": "a" * 64, "bytes": 0},
    {"sha256": "a" * 64, "bytes": -1}, {"sha256": "a" * 64, "bytes": 4 * 1024 * 1024 + 1},
    {"sha256": "a" * 64, "bytes": 1, "path": "/not-remotely-selectable"}])
def test_campaign_reference_is_closed_and_strictly_bounded(campaign, reference):
    request = _wire(campaign)
    request["payload"]["request_artifact"] = reference
    with pytest.raises(RegistryTransportError, match="bounded immutable descriptor"):
        campaign.gateway.dispatch(request)
    assert MAX_CAMPAIGN_REQUEST_BYTES == codec.MAX_REQUEST_BYTES


@pytest.mark.parametrize("command", sorted(CAMPAIGN_COMMANDS))
def test_campaign_gateway_rejects_unassigned_request(campaign, command):
    request = _wire(campaign, command)
    request["payload"]["request_artifact"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        campaign.gateway.dispatch(request)


@pytest.mark.parametrize("mismatch", ["worker", "run_union", "owner", "duck_type", "subclass", "daemon_slot", "both"])
def test_campaign_constructor_requires_exact_controller_owner_and_scope(campaign, mismatch):
    control = campaign.control
    registry = campaign.case.registry
    scope = WorkerScope(control.worker_id, control.run_ids)
    kwargs = {"campaign_control": control}
    if mismatch == "worker":
        scope = WorkerScope("other-worker", control.run_ids)
    elif mismatch == "run_union":
        scope = WorkerScope(control.worker_id, frozenset({next(iter(control.run_ids))}))
    elif mismatch == "owner":
        # A second registry object must not be accepted as the same live owner.
        registry = object.__new__(type(registry))
    elif mismatch == "duck_type":
        kwargs["campaign_control"] = SimpleNamespace(registry=registry, worker_id=scope.worker_id, run_ids=scope.run_ids)
    elif mismatch == "subclass":
        class Derived(OwnedCampaignControl):
            pass
        kwargs["campaign_control"] = object.__new__(Derived)
    elif mismatch == "daemon_slot":
        kwargs = {"owned_control": control}
    else:
        kwargs["owned_control"] = object()
    with pytest.raises(RegistryTransportError):
        RegistryQuackGateway(registry, scope, enable_prototype=True, **kwargs)


@pytest.mark.parametrize("command", sorted(CAMPAIGN_COMMANDS))
def test_generic_profile_cannot_dispatch_campaign_commands(campaign, command):
    control = campaign.control
    generic = RegistryQuackGateway(campaign.case.registry, WorkerScope(control.worker_id, control.run_ids),
        enable_prototype=True)
    with pytest.raises(RegistryTransportError, match="explicit owner control profile"):
        generic.dispatch(_wire(campaign, command))
    assert generic.status()["command_profile"] == "generic_worker"


@pytest.mark.parametrize("command", sorted(CAMPAIGN_COMMANDS))
def test_existing_daemon_profile_rejects_campaign_commands_before_controller_access(campaign, command, monkeypatch):
    from ipfs_datasets_py.duckdb_control.autoencoder_owned_control import OwnedInvocationControl, REQUEST_SCHEMA
    spec = campaign.case.specs[0]
    # Constructor-only descriptor fixture, never opened as a daemon request,
    # prepared, submitted or executed. This checks profile isolation only.
    handle = {"request": {**campaign.reference,
                          "path": str(campaign.case.registry.artifact_path(campaign.reference))},
              "journal_path": str(Path(campaign.case.output) / "unused-daemon-journal.json"),
              "binding": {"schema": REQUEST_SCHEMA, "run_id": spec.run_id,
                          "variant_id": campaign.case.registry.get_run(spec.run_id)["variant_id"],
                          "base_version_id": spec.base_version_id}}
    with OwnedInvocationControl(campaign.case.registry, worker_id="daemon-fixture", prepared_invocations={spec.run_id: handle}) as daemon:
        for name in ("submit", "read", "resolve", "execute_pending"):
            monkeypatch.setattr(daemon, name, lambda *_args, **_kwargs: pytest.fail("wrong profile reached controller"))
        gateway = RegistryQuackGateway(campaign.case.registry, WorkerScope(daemon.worker_id, daemon.run_ids),
            enable_prototype=True, owned_control=daemon)
        with pytest.raises(RegistryTransportError, match="owned invocation control profile"):
            gateway.dispatch(_wire(campaign, command))
        assert gateway.status()["command_profile"] == "owned_invocation"


@pytest.mark.parametrize("command", ["ClaimRun", "RenewLease", "CompleteRun"])
def test_generic_gateway_cannot_mutate_original_v8_campaign_runs(campaign, command):
    control = campaign.control
    gateway = RegistryQuackGateway(campaign.case.registry, WorkerScope(control.worker_id, control.run_ids),
        enable_prototype=True)
    before = _unchanged_execution(campaign.case)
    for spec in campaign.case.specs:
        assert spec.schema_version == "autoencoder-training-job-v8"
        payload = {"run_id": spec.run_id} if command == "ClaimRun" else {
            "lease": {"run_id": spec.run_id, "worker_id": control.worker_id}}
        if command == "CompleteRun":
            payload.update(artifact={}, result={})
        with pytest.raises(RegistryTransportError, match="owner-verified run"):
            gateway.dispatch(_envelope(command, payload, "generic-bypass"))
    assert _unchanged_execution(campaign.case) == before
