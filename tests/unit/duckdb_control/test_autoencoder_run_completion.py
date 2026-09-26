"""Offline durable-completion lookup tests with isolated DuckDB registries.

Checkpoint bytes and optimizer results are synthetic. These tests exercise
registry linkage, never native training, artifact semantics or Lean admission.
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes


def _json(value):
    return canonical_json_bytes(value).decode("utf-8")


@pytest.fixture
def registry(tmp_path):
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as owner:
        yield owner


def _stage(registry, tmp_path, name):
    source = tmp_path / f"{name}.json"
    source.write_bytes(_json({"synthetic_state": name}).encode("utf-8"))
    return registry.stage_artifact(source)


def _seed(registry, tmp_path):
    registry.register_variant("variant", "english", {"source_languages": ["en"], "fixture": True})
    base = registry.register_version("base", "english", _stage(registry, tmp_path, "base"))
    registry.initialize_head("head", "english", "main", base["version_id"])
    registry.create_run("create", "run-1", "english", base["version_id"], {"synthetic_job": True})
    return base


def _complete(registry, tmp_path):
    base = _seed(registry, tmp_path)
    lease = registry.claim_run("claim", "run-1", "worker-1", lease_seconds=10)["lease"]
    candidate = _stage(registry, tmp_path, "candidate")
    result = {"admitted": False, "execution_mode": "injected_test",
              "optimizer_accepted_epochs": 0, "legal_ir_target_count": 0}
    receipt = registry.complete_run("complete", lease, candidate, result)
    return {"base": base, "lease": lease, "candidate": candidate, "result": result, "receipt": receipt}


def _sql(registry, statement, parameters=()):
    with registry._transaction() as connection:
        connection.execute(statement, list(parameters))


def _set_receipt(registry, receipt):
    _sql(registry, "UPDATE autoencoder_control.operations SET receipt=? WHERE operation_id=?",
         [_json(receipt), "complete"])


def _snapshot(registry):
    with registry._transaction() as connection:
        names = connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='autoencoder_control' ORDER BY table_name"
        ).fetchall()
        return {name: sorted(connection.execute(f"SELECT * FROM autoencoder_control.{name}").fetchall(), key=repr)
                for (name,) in names}


def test_completed_lookup_returns_exact_run_receipt_and_candidate(registry, tmp_path):
    completed = _complete(registry, tmp_path)
    resolved = registry.get_run_completion("run-1")
    assert resolved == {
        "run": registry.get_run("run-1"),
        "completion_receipt": completed["receipt"],
        "candidate_version": registry.get_version(completed["receipt"]["version_id"]),
    }
    assert resolved["candidate_version"]["artifact"] == completed["candidate"]
    assert resolved["candidate_version"]["parent_version_id"] == completed["base"]["version_id"]
    assert resolved["run"]["result"]["optimizer_accepted_epochs"] == 0
    assert resolved["completion_receipt"]["admitted"] is False
    assert resolved["completion_receipt"]["promoted"] is False


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_noncompleted_status_cannot_be_overridden_by_result_flags(registry, tmp_path, status):
    _seed(registry, tmp_path)
    if status != "queued":
        lease = registry.claim_run("claim", "run-1", "worker-1")["lease"]
        if status == "failed":
            registry.fail_run("fail", lease, {"admitted": False, "failure": "synthetic"})
    _sql(registry, "UPDATE autoencoder_control.runs SET result=? WHERE run_id=?",
         [_json({"admitted": False, "status": "completed", "optimizer_accepted_epochs": 9,
                 "legal_ir_target_count": 100, "source_campaign_verified": True}), "run-1"])
    assert registry.get_run_completion("run-1") is None
    assert registry.get_run("run-1")["status"] == status


def test_unknown_run_raises(registry):
    with pytest.raises(RegistryError, match="unknown run"):
        registry.get_run_completion("unknown")


@pytest.mark.parametrize("run_id", ["run-1' OR TRUE --", "", None])
def test_lookup_requires_a_bounded_run_identifier(registry, run_id):
    with pytest.raises(RegistryError, match="run_id"):
        registry.get_run_completion(run_id)


def test_response_loss_resolves_after_restart_with_expired_previous_owner_lease(tmp_path, monkeypatch):
    now = [1_800_000_000.0]
    database, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts, clock=lambda: now[0]) as owner:
        original = owner.complete_run
        receipts = []

        def lose_response(*args, **kwargs):
            receipts.append(original(*args, **kwargs))
            raise OSError("synthetic response loss after commit")

        monkeypatch.setattr(owner, "complete_run", lose_response)
        with pytest.raises(OSError, match="response loss"):
            _complete(owner, tmp_path)
        expected = owner.get_run_completion("run-1")
        assert expected["completion_receipt"] == receipts[0]
        previous_generation = owner.owner_generation
    now[0] += 10_000
    with AutoencoderRegistry(database, artifacts, clock=lambda: now[0]) as reopened:
        assert reopened.owner_generation > previous_generation
        assert expected["run"]["lease"]["expires_at"] < now[0]
        assert reopened.get_run_completion("run-1") == expected
        assert reopened.get_run("run-1")["attempt"] == 1
        assert reopened.resolve_head("english", "main")["version_id"] == expected["run"]["base_version_id"]


def test_retry_completion_uses_final_attempt_and_exact_run(registry, tmp_path):
    base = _seed(registry, tmp_path)
    first = registry.claim_run("first-claim", "run-1", "worker-1")["lease"]
    registry.fail_run("first-failure", first, {"admitted": False, "failure": "synthetic"})
    second = registry.claim_run("second-claim", "run-1", "worker-2")["lease"]
    renewed = registry.renew_lease("renew", second)["lease"]
    candidate = _stage(registry, tmp_path, "candidate")
    result = {"admitted": False, "execution_mode": "injected_test"}
    receipt = registry.complete_run("complete-retry", renewed, candidate, result)
    registry.create_run("create-other", "run-2", "english", base["version_id"], {"synthetic_job": True})
    other_lease = registry.claim_run("claim-other", "run-2", "worker-3")["lease"]
    other = registry.complete_run("complete-other", other_lease, candidate, result)
    resolved = registry.get_run_completion("run-1")
    assert resolved["completion_receipt"] == receipt
    assert resolved["run"]["lease"] == renewed
    assert resolved["candidate_version"]["metadata"]["attempt"] == 2
    assert resolved["candidate_version"]["version_id"] != other["version_id"]
    assert registry.get_run_completion("run-2")["completion_receipt"] == other


def test_lookup_is_read_only_and_does_not_check_artifacts(registry, tmp_path, monkeypatch):
    completed = _complete(registry, tmp_path)
    before = _snapshot(registry)
    monkeypatch.setattr(registry, "verify_artifact", lambda *args: pytest.fail("history lookup must not read CAS"))
    first = registry.get_run_completion("run-1")
    assert registry.get_run_completion("run-1") == first
    assert _snapshot(registry) == before
    assert registry.resolve_head("english", "main")["version_id"] == completed["base"]["version_id"]
    assert registry.pending_outbox("huggingface") == []


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_valid_history_is_not_current_artifact_availability(registry, tmp_path, damage):
    completed = _complete(registry, tmp_path)
    expected = registry.get_run_completion("run-1")
    path = registry.artifact_path(completed["candidate"])
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"different synthetic bytes")
    assert registry.get_run_completion("run-1") == expected
    with pytest.raises(RegistryError):
        registry.verify_artifact(expected["candidate_version"]["artifact"])


def test_registered_producer_metadata_without_completion_has_no_authority(registry, tmp_path):
    base = _seed(registry, tmp_path)
    registry.claim_run("claim", "run-1", "worker-1")
    result = {"admitted": False, "optimizer_accepted_epochs": 7}
    registry.register_version("fake-candidate", "english", _stage(registry, tmp_path, "fake"),
                              {"producer_run": "run-1", "attempt": 1, "result": result},
                              parent_version_id=base["version_id"])
    assert registry.get_run_completion("run-1") is None
    _sql(registry, "UPDATE autoencoder_control.runs SET status='completed', result=? WHERE run_id=?",
         [_json(result), "run-1"])
    with pytest.raises(RegistryError, match="exactly one completion receipt"):
        registry.get_run_completion("run-1")


@pytest.mark.parametrize("damage", ["missing", "duplicate", "malformed"])
def test_missing_ambiguous_or_malformed_completion_is_rejected(registry, tmp_path, damage):
    completed = _complete(registry, tmp_path)
    if damage == "missing":
        _sql(registry, "DELETE FROM autoencoder_control.operations WHERE operation_id=?", ["complete"])
    elif damage == "duplicate":
        receipt = {**completed["receipt"], "operation_id": "second-complete"}
        _sql(registry, "INSERT INTO autoencoder_control.operations VALUES (?, ?, ?)",
             ["second-complete", "0" * 64, _json(receipt)])
    else:
        _sql(registry, "UPDATE autoencoder_control.operations SET receipt=? WHERE operation_id=?",
             ["{invalid-json", "complete"])
    with pytest.raises(RegistryError, match="exactly one completion receipt"):
        registry.get_run_completion("run-1")


@pytest.mark.parametrize(("field", "value"), [
    ("schema", "different-schema"), ("operation_id", "another-operation"),
    ("command", "RegisterVersion"), ("run_id", "another-run"),
    ("status", "running"), ("admitted", 0), ("promoted", 0),
    ("version_id", "sha256:" + "0" * 64), ("event_id", "sha256:" + "0" * 64),
    ("unexpected", "field"),
])
def test_completion_receipt_fields_are_bound(registry, tmp_path, field, value):
    completed = _complete(registry, tmp_path)
    _set_receipt(registry, {**completed["receipt"], field: value})
    with pytest.raises(RegistryError):
        registry.get_run_completion("run-1")


@pytest.mark.parametrize(("field", "value"), [
    ("producer_run", "another-run"), ("attempt", 2),
    ("result", {"admitted": False, "optimizer_accepted_epochs": 8}),
    ("unexpected", "field"),
])
def test_version_metadata_must_match_complete_run(registry, tmp_path, field, value):
    completed = _complete(registry, tmp_path)
    version_id = completed["receipt"]["version_id"]
    metadata = registry.get_version(version_id)["metadata"]
    _sql(registry, "UPDATE autoencoder_control.versions SET metadata=? WHERE version_id=?",
         [_json({**metadata, field: value}), version_id])
    with pytest.raises(RegistryError, match="candidate metadata"):
        registry.get_run_completion("run-1")


@pytest.mark.parametrize("damage", ["missing", "variant", "parent", "artifact", "identity"])
def test_candidate_identity_and_lineage_are_checked(registry, tmp_path, damage):
    completed = _complete(registry, tmp_path)
    version_id = completed["receipt"]["version_id"]
    if damage == "missing":
        _sql(registry, "DELETE FROM autoencoder_control.versions WHERE version_id=?", [version_id])
    elif damage == "variant":
        _sql(registry, "UPDATE autoencoder_control.versions SET variant_id=? WHERE version_id=?",
             ["another-variant", version_id])
    elif damage == "parent":
        _sql(registry, "UPDATE autoencoder_control.versions SET parent_version_id=? WHERE version_id=?",
             ["another-parent", version_id])
    elif damage == "artifact":
        changed = {**completed["candidate"], "sha256": "0" * 64}
        _sql(registry, "UPDATE autoencoder_control.versions SET artifact=? WHERE version_id=?", [_json(changed), version_id])
    else:
        wrong_id = "sha256:" + "0" * 64
        _sql(registry, "UPDATE autoencoder_control.versions SET version_id=? WHERE version_id=?", [wrong_id, version_id])
        _set_receipt(registry, {**completed["receipt"], "version_id": wrong_id})
    with pytest.raises(RegistryError):
        registry.get_run_completion("run-1")


def test_original_operation_payload_digest_is_required(registry, tmp_path):
    _complete(registry, tmp_path)
    _sql(registry, "UPDATE autoencoder_control.operations SET payload_digest=? WHERE operation_id=?",
         ["0" * 64, "complete"])
    with pytest.raises(RegistryError, match="payload digest"):
        registry.get_run_completion("run-1")


@pytest.mark.parametrize(("field", "value"), [
    ("run_id", "another-run"), ("attempt", 2), ("fence", 2),
    ("worker_id", "another-worker"), ("owner_generation", 999),
    ("expires_at", 1.0), ("attempt", True), ("expires_at", True),
])
def test_retained_terminal_lease_is_exactly_bound(registry, tmp_path, field, value):
    completed = _complete(registry, tmp_path)
    changed = {**completed["lease"], field: value}
    _sql(registry, "UPDATE autoencoder_control.runs SET lease=? WHERE run_id=?", [_json(changed), "run-1"])
    with pytest.raises(RegistryError):
        registry.get_run_completion("run-1")


@pytest.mark.parametrize("damage", ["lease_missing", "attempt", "fence", "result", "result_missing"])
def test_run_record_cannot_diverge_from_committed_completion(registry, tmp_path, damage):
    _complete(registry, tmp_path)
    if damage == "lease_missing":
        _sql(registry, "UPDATE autoencoder_control.runs SET lease=NULL WHERE run_id=?", ["run-1"])
    elif damage == "attempt":
        _sql(registry, "UPDATE autoencoder_control.runs SET attempt=2 WHERE run_id=?", ["run-1"])
    elif damage == "fence":
        _sql(registry, "UPDATE autoencoder_control.runs SET fence=2 WHERE run_id=?", ["run-1"])
    elif damage == "result":
        _sql(registry, "UPDATE autoencoder_control.runs SET result=? WHERE run_id=?",
             [_json({"admitted": False, "optimizer_accepted_epochs": 10}), "run-1"])
    else:
        _sql(registry, "UPDATE autoencoder_control.runs SET result=NULL WHERE run_id=?", ["run-1"])
    with pytest.raises(RegistryError):
        registry.get_run_completion("run-1")


@pytest.mark.parametrize("damage", ["missing", "kind", "run", "version", "extra", "malformed"])
def test_durable_event_must_match_the_completion(registry, tmp_path, damage):
    completed = _complete(registry, tmp_path)
    event_id = completed["receipt"]["event_id"]
    if damage == "missing":
        _sql(registry, "DELETE FROM autoencoder_control.events WHERE event_id=?", [event_id])
    elif damage == "kind":
        _sql(registry, "UPDATE autoencoder_control.events SET kind=? WHERE event_id=?", ["version_registered", event_id])
    else:
        payload = {"run_id": "run-1", "version_id": completed["receipt"]["version_id"]}
        if damage == "run":
            payload["run_id"] = "another-run"
        elif damage == "version":
            payload["version_id"] = completed["base"]["version_id"]
        elif damage == "extra":
            payload["extra"] = True
        encoded = "{invalid-json" if damage == "malformed" else _json(payload)
        _sql(registry, "UPDATE autoencoder_control.events SET event_data=? WHERE event_id=?", [encoded, event_id])
    with pytest.raises(RegistryError):
        registry.get_run_completion("run-1")


def test_lookup_returns_detached_values(registry, tmp_path):
    _complete(registry, tmp_path)
    expected = registry.get_run_completion("run-1")
    mutated = registry.get_run_completion("run-1")
    mutated["candidate_version"]["metadata"]["result"]["optimizer_accepted_epochs"] = 99
    mutated["run"]["result"]["admitted"] = True
    mutated["completion_receipt"]["promoted"] = True
    assert registry.get_run_completion("run-1") == expected
