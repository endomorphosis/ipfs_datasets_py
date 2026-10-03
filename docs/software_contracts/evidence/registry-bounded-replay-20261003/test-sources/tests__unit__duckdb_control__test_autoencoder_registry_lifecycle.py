"""Versioned terminal controls preserve the existing native registry schema."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from ipfs_datasets_py.duckdb_control.autoencoder_registry import (
    AutoencoderRegistry, RegistryError, RUN_LIFECYCLE_SCHEMA, RUN_TERMINAL_SCHEMA,
)


@pytest.fixture
def current(tmp_path):
    clock = [100.]
    registry = AutoencoderRegistry(tmp_path / "models.duckdb", tmp_path / "artifacts",
        clock=lambda: clock[0], promotion_validator=lambda version, evaluation: True)
    source = tmp_path / "parent.json"
    source.write_text('{"fixture":"parent"}')
    artifact = registry.stage_artifact(source)
    registry.register_variant("variant", "variant", {"fixture": True})
    parent = registry.register_version("parent", "variant", artifact)["version_id"]
    registry.initialize_head("head", "variant", "main", parent)
    head = registry.resolve_head("variant", "main")
    policy = dict(schema=RUN_LIFECYCLE_SCHEMA, max_attempts=1, wall_time_seconds=60.,
        memory_bytes=1024**3, max_input_bytes=32*1024**2, max_samples=128,
        optimizer_steps=0, head_refits=1, max_checkpoint_bytes=32*1024**2, expected_head=head)
    registry.create_run("create", "run", "variant", parent, {"fixture": "native owner boundary only"})
    registry.configure_run_lifecycle("run", policy)
    yield SimpleNamespace(registry=registry, clock=clock, parent=parent, artifact=artifact,
                          head=head, policy=policy, root=tmp_path)
    registry.close()


@pytest.mark.parametrize("terminal", ["cancelled", "superseded"])
def test_terminal_state_revokes_worker_and_cannot_revive(current, terminal):
    r = current.registry
    lease = r.claim_run("claim", "run", "worker", 60)["lease"]
    reply = r.terminate_run("stop", "run", terminal=terminal, expected_attempt=lease["attempt"],
                           expected_fence=lease["fence"], reason="qualification")
    assert reply["terminal_schema"] == RUN_TERMINAL_SCHEMA
    run = r.get_run("run")
    assert run["status"] == terminal and run["lease"] is None and run["fence"] == lease["fence"] + 1
    assert run["result"]["retryable"] is run["result"]["publishable"] is False
    for action in (
        lambda: r.claim_run("reclaim", "run", "other", 60),
        lambda: r.renew_lease("renew", lease, 30),
        lambda: r.complete_run("complete", lease, current.artifact, {"admitted": False}),
        lambda: r.fail_run("fail", lease, {"admitted": False}),
    ):
        with pytest.raises(RegistryError):
            action()
    assert r.get_run_completion("run") is None and r.get_run("run") == run


def test_terminal_lost_reply_is_idempotent_after_restart(current):
    r = current.registry
    arguments = dict(terminal="cancelled", expected_attempt=0, expected_fence=0, reason="lost reply")
    first = r.terminate_run("terminal-lost-reply", "run", **arguments)
    terminal = r.get_run("run")
    r.close()
    with AutoencoderRegistry(current.root / "models.duckdb", current.root / "artifacts") as restarted:
        assert restarted.terminate_run("terminal-lost-reply", "run", **arguments) == first
        assert restarted.get_run("run") == terminal
        assert restarted.get_run_lifecycle("run") == current.policy


def test_fence_cas_and_superseding_run_binding(current):
    r = current.registry
    r.create_run("successor", "next", "variant", current.parent, {})
    lease = r.claim_run("claim", "run", "worker", 60)["lease"]
    with pytest.raises(RegistryError, match="compare-and-swap"):
        r.terminate_run("stale-stop", "run", terminal="superseded", expected_attempt=0,
                       expected_fence=0, reason="changed source", successor_run_id="next")
    r.terminate_run("supersede", "run", terminal="superseded", expected_attempt=lease["attempt"],
                   expected_fence=lease["fence"], reason="changed source", successor_run_id="next")
    assert r.get_run("run")["result"]["successor_run_id"] == "next"


def test_native_claim_enforces_retry_and_lease_budgets(current):
    r = current.registry
    with pytest.raises(RegistryError, match="wall-time budget"):
        r.claim_run("too-long", "run", "worker", 71)
    lease = r.claim_run("first", "run", "worker", 60)["lease"]
    r.fail_run("failure", lease, {"admitted": False})
    with pytest.raises(RegistryError, match="attempt budget"):
        r.claim_run("second", "run", "worker2", 60)


def test_completed_history_and_lost_reply_remain_compatible(current):
    r = current.registry
    lease = r.claim_run("claim", "run", "worker", 60)["lease"]
    first = r.complete_run("complete", lease, current.artifact, {"admitted": False})
    assert r.complete_run("complete", lease, current.artifact, {"admitted": False}) == first
    assert r.get_run_completion("run")["candidate_version"]["version_id"] == first["version_id"]
    with pytest.raises(RegistryError, match="completed or terminal"):
        r.terminate_run("late-cancel", "run", terminal="cancelled", expected_attempt=lease["attempt"],
                       expected_fence=lease["fence"], reason="too late")
    assert r.get_run("run")["status"] == "completed"


def test_changed_head_blocks_candidate_completion_atomically(current):
    r = current.registry
    lease = r.claim_run("claim", "run", "worker", 60)["lease"]
    alternate = r.register_version("alternate", "variant", current.artifact,
                                   metadata={"fixture": "same parent bytes"})["version_id"]
    r.promote_head("change-head", "variant", "main", alternate,
        expected_version_id=current.parent, expected_generation=1,
        evaluation={"candidate_version_id": alternate, "protocol_id": "unit-policy"})
    with pytest.raises(RegistryError, match="parent head changed"):
        r.complete_run("stale-completion", lease, current.artifact, {"admitted": False})
    assert r.get_run_completion("run") is None and r.get_run("run")["status"] == "running"


def test_checkpoint_budget_prevents_completion(current):
    r = current.registry
    r.create_run("create-small", "small", "variant", current.parent, {})
    r.configure_run_lifecycle("small", dict(current.policy, max_checkpoint_bytes=1))
    lease = r.claim_run("claim-small", "small", "worker", 60)["lease"]
    with pytest.raises(RegistryError, match="checkpoint budget"):
        r.complete_run("complete-large", lease, current.artifact, {"admitted": False})
    assert r.get_run_completion("small") is None


@pytest.mark.parametrize("operation", ["promotion", "publication"])
def test_terminal_producer_cannot_publish_registered_stale_artifact(current, operation):
    r = current.registry
    version = r.register_version("stale-version", "variant", current.artifact,
        metadata={"producer_run": "run"}, parent_version_id=current.parent)["version_id"]
    r.terminate_run("cancel", "run", terminal="cancelled", expected_attempt=0,
                    expected_fence=0, reason="cancelled before result")
    with pytest.raises(RegistryError, match="terminal producer"):
        if operation == "promotion":
            r.promote_head("promote", "variant", "main", version, current.parent, 1,
                          {"candidate_version_id": version, "protocol_id": "unit-policy"})
        else:
            r.enqueue_publication("publish", version, current.artifact)
    assert r.resolve_head("variant", "main") == current.head
    assert r.pending_outbox("huggingface") == []


def test_terminal_check_occurs_after_promotion_review_inside_commit(current):
    r = current.registry
    version = r.register_version("stale-version", "variant", current.artifact,
        metadata={"producer_run": "run"}, parent_version_id=current.parent)["version_id"]
    def policy(candidate, evaluation):
        r.terminate_run("cancel-during-policy", "run", terminal="cancelled", expected_attempt=0,
                        expected_fence=0, reason="race during review")
        return True
    r._promotion_validator = policy
    with pytest.raises(RegistryError, match="terminal producer"):
        r.promote_head("promote", "variant", "main", version, current.parent, 1,
                      {"candidate_version_id": version, "protocol_id": "unit-policy"})
    assert r.resolve_head("variant", "main") == current.head


def test_legacy_failed_retry_is_unchanged_and_terminal_requires_opt_in(current):
    r = current.registry
    r.create_run("legacy", "legacy", "variant", current.parent, {})
    assert r.get_run_lifecycle("legacy") is None
    with pytest.raises(RegistryError, match="not opted"):
        r.terminate_run("legacy-cancel", "legacy", terminal="cancelled", expected_attempt=0,
                        expected_fence=0, reason="not configured")
    first = r.claim_run("legacy-first", "legacy", "worker", 600)["lease"]
    r.fail_run("legacy-fail", first, {"admitted": False})
    second = r.claim_run("legacy-retry", "legacy", "worker", 600)["lease"]
    assert second["attempt"] == first["attempt"] + 1


@pytest.mark.parametrize("field,value", [
    ("max_attempts", 0), ("max_attempts", 4), ("wall_time_seconds", True),
    ("wall_time_seconds", 601), ("memory_bytes", 1), ("max_input_bytes", 0),
    ("max_samples", 129), ("optimizer_steps", 1), ("head_refits", 2),
    ("max_checkpoint_bytes", 0), ("schema", "unversioned"),
])
def test_closed_supported_budget_policy(current, field, value):
    damaged = deepcopy(current.policy)
    damaged[field] = value
    with pytest.raises(RegistryError):
        current.registry.configure_run_lifecycle("run", damaged)


def test_policy_is_immutable_and_precedes_claim(current):
    r = current.registry
    with pytest.raises(RegistryError):
        r.configure_run_lifecycle("run", dict(current.policy, max_attempts=2))
    r.create_run("late-create", "late", "variant", current.parent, {})
    r.claim_run("late-claim", "late", "worker", 60)
    with pytest.raises(RegistryError, match="before the first claim"):
        r.configure_run_lifecycle("late", current.policy)
