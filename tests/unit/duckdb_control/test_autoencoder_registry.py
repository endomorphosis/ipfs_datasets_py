"""Durable autoencoder registry tests using isolated, real DuckDB files.

Synthetic checkpoint bytes exercise storage contracts only. They do not assert
model quality, bridge execution, or Lean admission.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import (
    AutoencoderRegistry,
    RegistryError,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def variant(language: str = "en") -> dict:
    return {
        "source_languages": [language],
        "target_logic": "typed_deontic",
        "architecture": "modal_autoencoder",
        "parameter_schema": "legacy-json@1",
    }


def run_spec() -> dict:
    return {
        "bridge_names": [
            "modal_frame_logic",
            "deontic_norms",
            "fol_tdfol",
            "cec_dcec",
            "external_prover_router",
        ],
        "legal_ir_evaluate_provers": False,
        "legal_ir_parallel_workers": 1,
        "use_sample_memory": False,
        "temperature": 0,
        "sample_count": 3,
    }


def staged(registry: AutoencoderRegistry, tmp_path: Path, name: str = "base") -> dict:
    source = tmp_path / f"{name}.json"
    source.write_bytes(json.dumps({"synthetic_state": name}).encode())
    return registry.stage_artifact(source)


def seed(registry: AutoencoderRegistry, tmp_path: Path, name: str = "english") -> dict:
    registry.register_variant(f"variant-{name}", name, variant())
    return registry.register_version(
        f"version-{name}", name, staged(registry, tmp_path, name), metadata={"fixture": True}
    )


def create_claimed_run(registry: AutoencoderRegistry, tmp_path: Path) -> tuple[dict, dict]:
    version = seed(registry, tmp_path)
    registry.create_run("create-run", "run-1", "english", version["version_id"], run_spec())
    claimed = registry.claim_run("claim-run", "run-1", "worker-1", lease_seconds=10)
    return version, claimed["lease"]


def child(script: str, *arguments: object) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["IPFS_DATASETS_PY_MINIMAL_IMPORTS"] = "1"
    env["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
    return subprocess.run(
        [sys.executable, "-c", script, *map(str, arguments)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_memory_database_is_not_a_durable_registry(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        AutoencoderRegistry(":memory:", tmp_path / "artifacts")


def test_artifacts_are_content_addressed_independent_of_source(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    original = b'{"synthetic_state":"original"}'
    source.write_bytes(original)
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        first = registry.stage_artifact(source)
        second = registry.stage_artifact(source, expected_sha256=hashlib.sha256(original).hexdigest())
        assert first == second
        assert first["sha256"] == hashlib.sha256(original).hexdigest()
        assert first["bytes"] == len(original)
        source.write_bytes(b"changed source")
        registry.register_variant("variant", "english", variant())
        receipt = registry.register_version("register", "english", first)
        assert registry.get_version(receipt["version_id"])["artifact"] == first
        assert any(p.read_bytes() == original for p in (tmp_path / "artifacts").rglob("*") if p.is_file())


def test_stage_rejects_mismatched_expected_hash(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b"synthetic")
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        with pytest.raises(RegistryError):
            registry.stage_artifact(source, expected_sha256="0" * 64)


@pytest.mark.parametrize("field,value", [("sha256", "0" * 64), ("bytes", 999999)])
def test_version_registration_checks_artifact_integrity(tmp_path: Path, field: str, value: object) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        registry.register_variant("variant", "english", variant())
        artifact = staged(registry, tmp_path)
        with pytest.raises(RegistryError):
            registry.register_version("bad-register", "english", {**artifact, field: value})


def test_corrupted_staged_bytes_cannot_be_registered(tmp_path: Path) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        registry.register_variant("variant", "english", variant())
        artifact = staged(registry, tmp_path)
        stored = next(
            p for p in (tmp_path / "artifacts").rglob("*")
            if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == artifact["sha256"]
        )
        stored.chmod(0o600)
        stored.write_bytes(b"corrupt staged checkpoint")
        with pytest.raises(RegistryError):
            registry.register_version("corrupt-register", "english", artifact)


def test_idempotency_survives_reopen_and_rejects_payload_changes(tmp_path: Path) -> None:
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts) as registry:
        expected = registry.register_variant("same-operation", "english", variant())
        assert registry.register_variant("same-operation", "english", variant()) == expected
    with AutoencoderRegistry(db, artifacts) as registry:
        assert registry.register_variant("same-operation", "english", variant()) == expected
        assert registry.get_variant("english") == {"variant_id": "english", "manifest": variant()}
        with pytest.raises(RegistryError):
            registry.register_variant("same-operation", "english", variant("fr"))
        with pytest.raises(RegistryError):
            registry.register_variant("different-operation", "english", variant("fr"))


def test_reopen_cannot_silently_switch_artifact_stores(tmp_path: Path) -> None:
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts) as registry:
        expected = seed(registry, tmp_path)
    with pytest.raises(RegistryError):
        AutoencoderRegistry(db, tmp_path / "different-artifacts")
    with AutoencoderRegistry(db, artifacts) as registry:
        assert registry.get_version(expected["version_id"])["version_id"] == expected["version_id"]


@pytest.mark.parametrize("change", [
    "DROP TABLE autoencoder_control.operations",
    "DROP SCHEMA autoencoder_control CASCADE",
    "ALTER TABLE autoencoder_control.events ADD COLUMN foreign_column INTEGER",
    "ALTER TABLE autoencoder_control.meta DROP COLUMN catalog_hash",
    "CREATE TABLE main.foreign_records (value INTEGER)",
])
def test_reopen_rejects_missing_changed_or_foreign_tables(tmp_path: Path, change: str) -> None:
    import duckdb

    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts):
        pass
    with duckdb.connect(str(db), config={"autoinstall_known_extensions": "false", "autoload_known_extensions": "false"}) as connection:
        connection.execute(change)
    with pytest.raises(RegistryError):
        AutoencoderRegistry(db, artifacts)


def test_operation_id_cannot_be_reused_for_a_different_command(tmp_path: Path) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        registry.register_variant("same-operation", "english", variant())
        with pytest.raises(RegistryError):
            registry.register_version("same-operation", "english", staged(registry, tmp_path))


def test_operation_resolution_is_readonly_exact_and_persistent(tmp_path: Path) -> None:
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    payload = {"variant_id": "english", "manifest": variant()}
    with AutoencoderRegistry(db, artifacts) as registry:
        assert registry.resolve_operation("register", "RegisterVariant", payload) is None
        expected = registry.register_variant("register", "english", variant())
        assert registry.resolve_operation("register", "RegisterVariant", payload) == expected
        with pytest.raises(RegistryError):
            registry.resolve_operation("register", "RegisterVariant", {**payload, "variant_id": "other"})
        with pytest.raises(RegistryError):
            registry.resolve_operation("register", "CreateRun", payload)
        assert registry.resolve_operation("never-executed", "RegisterVariant", payload) is None
    with AutoencoderRegistry(db, artifacts) as registry:
        assert registry.resolve_operation("register", "RegisterVariant", payload) == expected
        assert registry.resolve_operation("never-executed", "RegisterVariant", payload) is None


def test_two_language_variants_keep_distinct_versions_and_run_bases(tmp_path: Path) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        english = seed(registry, tmp_path)
        registry.register_variant("variant-french", "french", variant("fr"))
        french = registry.register_version("version-french", "french", staged(registry, tmp_path, "french"))
        registry.create_run("run-en", "run-en", "english", english["version_id"], run_spec())
        registry.create_run("run-fr", "run-fr", "french", french["version_id"], run_spec())
        assert english["version_id"] != french["version_id"]
        assert registry.get_run("run-en")["base_version_id"] == english["version_id"]
        assert registry.get_run("run-fr")["base_version_id"] == french["version_id"]
        with pytest.raises(RegistryError):
            registry.create_run("wrong-base", "wrong-base", "french", english["version_id"], run_spec())


def test_live_lease_blocks_a_second_claim_then_expiry_fences_old_worker(tmp_path: Path) -> None:
    clock = Clock()
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts", clock=clock) as registry:
        _, lease = create_claimed_run(registry, tmp_path)
        with pytest.raises(RegistryError):
            registry.claim_run("claim-busy", "run-1", "worker-2", lease_seconds=10)
        clock.now += 11
        replacement = registry.claim_run("claim-new", "run-1", "worker-2", lease_seconds=10)["lease"]
        assert replacement["fence"] > lease["fence"]
        assert replacement["attempt"] > lease["attempt"]
        with pytest.raises(RegistryError):
            registry.renew_lease("renew-stale", lease, lease_seconds=10)
        with pytest.raises(RegistryError):
            registry.complete_run("complete-stale", lease, staged(registry, tmp_path, "stale"), {"admitted": False})


def test_expired_lease_rejects_completion_even_without_a_replacement(tmp_path: Path) -> None:
    clock = Clock()
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts", clock=clock) as registry:
        _, lease = create_claimed_run(registry, tmp_path)
        clock.now += 11
        with pytest.raises(RegistryError):
            registry.complete_run("complete-expired", lease, staged(registry, tmp_path, "expired"), {"admitted": False})


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf")])
def test_nonpositive_or_nonfinite_lease_duration_is_rejected(tmp_path: Path, duration: float) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        version = seed(registry, tmp_path)
        registry.create_run("create-run", "run-1", "english", version["version_id"], run_spec())
        with pytest.raises(RegistryError):
            registry.claim_run("bad-duration", "run-1", "worker", lease_seconds=duration)


def test_restart_fences_old_lease_without_waiting_for_expiry(tmp_path: Path) -> None:
    clock = Clock()
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts, clock=clock) as registry:
        _, old = create_claimed_run(registry, tmp_path)
    with AutoencoderRegistry(db, artifacts, clock=clock) as registry:
        with pytest.raises(RegistryError):
            registry.renew_lease("renew-after-restart", old, lease_seconds=10)
        current = registry.claim_run("claim-after-restart", "run-1", "worker-2", lease_seconds=10)["lease"]
        assert current["owner_generation"] > old["owner_generation"]
        assert current["fence"] > old["fence"]


def test_completed_candidate_is_idempotent_and_does_not_select_head(tmp_path: Path) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        base, lease = create_claimed_run(registry, tmp_path)
        artifact = staged(registry, tmp_path, "candidate")
        result = {"admitted": False, "optimizer_step": {"accepted": True}, "legal_ir_target_count": 3}
        candidate = registry.complete_run("complete", lease, artifact, result)
        assert registry.complete_run("complete", lease, artifact, result) == candidate
        version = registry.get_version(candidate["version_id"])
        assert version["parent_version_id"] == base["version_id"]
        assert registry.get_run("run-1")["status"] == "completed"
        assert registry.resolve_head("english", "main") is None
        assert registry.pending_outbox("huggingface") == []
        with pytest.raises(RegistryError):
            registry.complete_run("complete", lease, artifact, {**result, "legal_ir_target_count": 0})


def test_database_completion_cannot_claim_lean_admission(tmp_path: Path) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        _, lease = create_claimed_run(registry, tmp_path)
        with pytest.raises(RegistryError):
            registry.complete_run("false-admit", lease, staged(registry, tmp_path, "candidate"), {"admitted": True})
        assert registry.get_run("run-1")["status"] == "running"


def test_failed_run_is_durable_idempotent_and_releases_attempt_lease(tmp_path: Path) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        _, lease = create_claimed_run(registry, tmp_path)
        result = {"admitted": False, "error": "synthetic worker interruption"}
        failed = registry.fail_run("fail-run", lease, result)
        assert registry.fail_run("fail-run", lease, result) == failed
        state = registry.get_run("run-1")
        assert state["status"] == "failed"
        assert state["lease"] is None
        assert registry.resolve_head("english", "main") is None
        replacement = registry.claim_run("retry-run", "run-1", "worker-2")["lease"]
        assert replacement["attempt"] > lease["attempt"]
        with pytest.raises(RegistryError):
            registry.fail_run("fail-old-attempt", lease, result)


def test_promotion_requires_owner_policy_even_with_positive_metrics(tmp_path: Path) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        base = seed(registry, tmp_path)
        registry.initialize_head("initialize", "english", "main", base["version_id"])
        candidate = registry.register_version("candidate", "english", staged(registry, tmp_path, "candidate"), parent_version_id=base["version_id"])
        evidence = {"candidate_version_id": candidate["version_id"], "protocol_id": "synthetic-storage-test", "ir_cosine_similarity": 1.0}
        with pytest.raises(RegistryError):
            registry.promote_head("promote", "english", "main", candidate["version_id"], base["version_id"], 1, evidence)
        assert registry.resolve_head("english", "main")["version_id"] == base["version_id"]
        with pytest.raises(RegistryError):
            registry.initialize_head("bootstrap-candidate", "english", "candidate-branch", candidate["version_id"])


def test_head_compare_and_swap_fences_competing_evaluated_candidates(tmp_path: Path) -> None:
    # This callback qualifies storage fixtures only, never model quality.
    def fixture_validator(version: dict, evaluation: dict) -> bool:
        return evaluation.get("protocol_id") == "synthetic-storage-test" and evaluation.get("candidate_version_id") == version["version_id"]

    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts, promotion_validator=fixture_validator) as registry:
        base = seed(registry, tmp_path)
        registry.initialize_head("initialize", "english", "main", base["version_id"])
        candidates = [
            registry.register_version(name, "english", staged(registry, tmp_path, name), parent_version_id=base["version_id"])
            for name in ("candidate-a", "candidate-b")
        ]
        first, second = (item["version_id"] for item in candidates)
        first_evidence = {"candidate_version_id": first, "protocol_id": "synthetic-storage-test"}
        receipt = registry.promote_head("promote-first", "english", "main", first, base["version_id"], 1, first_evidence)
        assert receipt["generation"] == 2
        assert registry.promote_head("promote-first", "english", "main", first, base["version_id"], 1, first_evidence) == receipt
        with pytest.raises(RegistryError):
            registry.promote_head("promote-stale", "english", "main", second, base["version_id"], 1, {"candidate_version_id": second, "protocol_id": "synthetic-storage-test"})
        with pytest.raises(RegistryError):
            registry.promote_head("wrong-evidence", "english", "main", second, first, 2, first_evidence)
        assert registry.resolve_head("english", "main")["version_id"] == first
    with AutoencoderRegistry(db, artifacts) as registry:
        assert registry.resolve_head("english", "main")["version_id"] == first
        # Historical exact retries resolve without reinstalling the current
        # evaluation policy; a new operation still cannot promote anything.
        assert registry.promote_head("promote-first", "english", "main", first, base["version_id"], 1, first_evidence) == receipt
        with pytest.raises(RegistryError):
            registry.promote_head("new-promote", "english", "main", second, first, 2, {"candidate_version_id": second, "protocol_id": "synthetic-storage-test"})


def test_artifact_operation_retries_return_history_without_claiming_current_availability(tmp_path: Path) -> None:
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts) as registry:
        _, lease = create_claimed_run(registry, tmp_path)
        artifact = staged(registry, tmp_path, "candidate")
        result = {"admitted": False}
        complete = registry.complete_run("complete", lease, artifact, result)
        plan = staged(registry, tmp_path, "plan")
        publication = registry.enqueue_publication("publish", complete["version_id"], plan)
        registered = registry.register_version("register-again", "english", artifact)
        registry.artifact_path(artifact).unlink()
        registry.artifact_path(plan).unlink()
    with AutoencoderRegistry(db, artifacts) as registry:
        assert registry.complete_run("complete", lease, artifact, result) == complete
        assert registry.register_version("register-again", "english", artifact) == registered
        assert registry.enqueue_publication("publish", complete["version_id"], plan) == publication
        with pytest.raises(RegistryError):
            registry.register_version("new-register", "english", artifact)
        with pytest.raises(RegistryError):
            registry.enqueue_publication("new-publish", complete["version_id"], plan)
        with pytest.raises(RegistryError):
            registry.verify_artifact(artifact)


def test_publication_outbox_is_explicit_and_ack_does_not_drain_lake(tmp_path: Path) -> None:
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts) as registry:
        version = seed(registry, tmp_path)
        lake_before = registry.pending_outbox("ducklake")
        assert lake_before
        assert registry.pending_outbox("huggingface") == []
        registry.enqueue_publication("publish-plan", version["version_id"], staged(registry, tmp_path, "publication-plan"))
        deliveries = registry.claim_outbox("claim-publish", "huggingface", "publisher", limit=1)["deliveries"]
        assert len(deliveries) == 1
        delivery = deliveries[0]
        receipt = {"status": "packaged_locally", "uploaded": False}
        acknowledged = registry.ack_outbox("ack-publish", delivery["event_id"], "huggingface", receipt, delivery["lease"])
        assert registry.ack_outbox("ack-publish", delivery["event_id"], "huggingface", receipt, delivery["lease"]) == acknowledged
        assert registry.pending_outbox("huggingface") == []
        assert registry.pending_outbox("ducklake") == lake_before
    with AutoencoderRegistry(db, artifacts) as registry:
        assert registry.pending_outbox("huggingface") == []
        assert registry.pending_outbox("ducklake") == lake_before


def test_expired_outbox_claim_cannot_ack_replacement_delivery(tmp_path: Path) -> None:
    clock = Clock()
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts", clock=clock) as registry:
        seed(registry, tmp_path)
        old = registry.claim_outbox("claim-first", "ducklake", "lake-1", lease_seconds=10, limit=1)["deliveries"][0]
        clock.now += 11
        replacement = registry.claim_outbox("claim-second", "ducklake", "lake-2", lease_seconds=10, limit=1)["deliveries"][0]
        assert replacement["event_id"] == old["event_id"]
        assert replacement["lease"]["fence"] > old["lease"]["fence"]
        with pytest.raises(RegistryError):
            registry.ack_outbox("ack-stale", old["event_id"], "ducklake", {"materialized": True}, old["lease"])


def test_outbox_claim_skips_live_leases_before_applying_limit(tmp_path: Path) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        seed(registry, tmp_path, "english")
        seed(registry, tmp_path, "second")
        first = registry.claim_outbox("claim-first", "ducklake", "lake-1", limit=1)["deliveries"]
        second = registry.claim_outbox("claim-second", "ducklake", "lake-2", limit=1)["deliveries"]
        assert len(first) == len(second) == 1
        assert first[0]["event_id"] != second[0]["event_id"]
        assert registry.claim_outbox("claim-empty", "ducklake", "lake-3", limit=1)["deliveries"] == []


def test_committed_version_survives_a_fresh_python_interpreter(tmp_path: Path) -> None:
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts) as registry:
        expected = seed(registry, tmp_path)
    result = child(
        """import json, sys
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
with AutoencoderRegistry(sys.argv[1], sys.argv[2]) as registry:
    print(json.dumps(registry.get_version(sys.argv[3])))
""",
        db, artifacts, expected["version_id"],
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["version_id"] == expected["version_id"]


def test_second_process_cannot_open_live_owner_database(tmp_path: Path) -> None:
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts):
        result = child(
            """import sys
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
try:
    with AutoencoderRegistry(sys.argv[1], sys.argv[2]):
        pass
except RegistryError:
    print('owner-refused')
else:
    raise SystemExit('second owner unexpectedly acquired database')
""",
            db, artifacts,
        )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "owner-refused"


def test_committed_records_survive_abrupt_owner_process_exit(tmp_path: Path) -> None:
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    source = tmp_path / "synthetic.json"
    source.write_bytes(b'{"synthetic_state":"crash-recovery"}')
    result = child(
        """import json, os, sys
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
registry = AutoencoderRegistry(sys.argv[1], sys.argv[2])
registry.register_variant('register-variant', 'english', {'source_languages': ['en']})
artifact = registry.stage_artifact(sys.argv[3])
receipt = registry.register_version('register-version', 'english', artifact)
print(json.dumps(receipt), flush=True)
os._exit(0)
""",
        db, artifacts, source,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout.splitlines()[-1])
    with AutoencoderRegistry(db, artifacts) as registry:
        version = registry.get_version(receipt["version_id"])
        assert version["artifact"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert registry.register_version("register-version", "english", version["artifact"]) == receipt


def test_exact_outbox_lookup_retains_payload_timestamp_and_ack_after_restart(tmp_path: Path) -> None:
    clock = Clock()
    clock.now += 0.125
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts, clock=clock) as registry:
        version = seed(registry, tmp_path)
        event_id = version["event_id"]
        pending = registry.get_outbox_event("ducklake", event_id)
        assert set(pending) == {"event_id", "consumer", "kind", "payload", "created_at", "status", "lease", "receipt"}
        assert pending == {
            "event_id": event_id, "consumer": "ducklake", "kind": "version_registered",
            "payload": {"version_id": version["version_id"]},
            "created_at": clock.now, "status": "pending", "lease": None, "receipt": None,
        }
        pending["payload"]["version_id"] = "caller-mutated"
        assert registry.get_outbox_event("ducklake", event_id)["payload"]["version_id"] == version["version_id"]
        delivery = registry.claim_outbox_event("claim-exact", event_id, "ducklake", "mirror")["delivery"]
        receipt = {"commit": "local-fixture", "nested": {"events": [event_id]}}
        registry.ack_outbox("ack-exact", event_id, "ducklake", receipt, delivery["lease"])
        acknowledged = registry.get_outbox_event("ducklake", event_id)
        assert acknowledged["status"] == "acknowledged"
        assert acknowledged["receipt"] == receipt
        assert acknowledged["lease"] == delivery["lease"]
        assert registry.pending_outbox("ducklake") == []
        detached = registry.get_outbox_event("ducklake", event_id)
        detached["receipt"]["nested"]["events"].clear()
        detached["lease"]["worker_id"] = "caller-mutated"
        assert registry.get_outbox_event("ducklake", event_id) == acknowledged
    with AutoencoderRegistry(db, artifacts, clock=clock) as registry:
        assert registry.get_outbox_event("ducklake", event_id) == acknowledged


def test_failed_event_lookup_does_not_enrich_from_later_run_attempt(tmp_path: Path) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        _, first_lease = create_claimed_run(registry, tmp_path)
        failed = registry.fail_run("fail-first", first_lease, {"admitted": False, "error": "first attempt"})
        original = registry.get_outbox_event("ducklake", failed["event_id"])
        assert original["kind"] == "run_failed"
        assert original["payload"] == {"run_id": "run-1", "attempt": 1}
        second = registry.claim_run("claim-retry", "run-1", "worker-2")["lease"]
        registry.complete_run("complete-retry", second, staged(registry, tmp_path, "candidate"), {"admitted": False, "new_result": True})
        assert registry.get_run("run-1")["attempt"] == 2
        assert registry.get_run("run-1")["status"] == "completed"
        assert registry.get_outbox_event("ducklake", failed["event_id"]) == original


@pytest.mark.parametrize("bad", [None, True, 1, [], {}, "", "0" * 64, "sha256:" + "A" * 64, "sha256:" + "0" * 63, "sha256:" + "0" * 65, "sha256:" + "0" * 64 + "\n"])
def test_exact_outbox_methods_reject_malformed_event_ids(tmp_path: Path, bad: object) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        with pytest.raises(RegistryError, match="event_id"):
            registry.get_outbox_event("ducklake", bad)
        with pytest.raises(RegistryError, match="event_id"):
            registry.claim_outbox_event("claim-bad", bad, "ducklake", "mirror")
        with pytest.raises(RegistryError, match="event_id"):
            registry.renew_outbox("renew-bad", bad, "ducklake", {})


@pytest.mark.parametrize("consumer", [None, True, [], {}, "", "other", "DuckLake"])
def test_exact_outbox_methods_reject_unknown_consumer(tmp_path: Path, consumer: object) -> None:
    event_id = "sha256:" + "0" * 64
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        with pytest.raises(RegistryError, match="consumer"):
            registry.get_outbox_event(consumer, event_id)
        with pytest.raises(RegistryError, match="consumer"):
            registry.claim_outbox_event("claim-bad", event_id, consumer, "mirror")
        with pytest.raises(RegistryError, match="consumer"):
            registry.renew_outbox("renew-bad", event_id, consumer, {})


def test_exact_outbox_methods_reject_unknown_event_consumer_pair(tmp_path: Path) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        version = seed(registry, tmp_path)
        for event_id, consumer in ((version["event_id"], "huggingface"), ("sha256:" + "0" * 64, "ducklake")):
            with pytest.raises(RegistryError, match="unknown outbox event"):
                registry.get_outbox_event(consumer, event_id)
            with pytest.raises(RegistryError, match="unknown outbox event"):
                registry.claim_outbox_event("claim-unknown", event_id, consumer, "mirror")
            with pytest.raises(RegistryError, match="not leased"):
                registry.renew_outbox("renew-unknown", event_id, consumer, {})


def test_outbox_renewal_retains_fence_and_rejects_previous_lease(tmp_path: Path) -> None:
    clock = Clock()
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts", clock=clock) as registry:
        event_id = seed(registry, tmp_path)["event_id"]
        old = registry.claim_outbox_event("claim", event_id, "ducklake", "mirror", 10)["delivery"]["lease"]
        clock.now += 3
        renewed = registry.renew_outbox("renew", event_id, "ducklake", old, 20)
        assert set(renewed) == {"schema", "operation_id", "command", "admitted", "lease"}
        assert renewed["command"] == "RenewOutbox"
        assert renewed["admitted"] is False
        assert renewed["lease"] == {**old, "expires_at": clock.now + 20}
        assert registry.get_outbox_event("ducklake", event_id)["lease"] == renewed["lease"]
        with pytest.raises(RegistryError, match="stale"):
            registry.renew_outbox("renew-stale", event_id, "ducklake", old, 20)
        with pytest.raises(RegistryError, match="stale"):
            registry.ack_outbox("ack-stale", event_id, "ducklake", {}, old)
        registry.ack_outbox("ack", event_id, "ducklake", {"commit": "synthetic"}, renewed["lease"])
        assert registry.renew_outbox("renew", event_id, "ducklake", old, 20) == renewed
        with pytest.raises(RegistryError, match="not leased"):
            registry.renew_outbox("renew-after-ack", event_id, "ducklake", renewed["lease"])
        with pytest.raises(RegistryError, match="different payload"):
            registry.renew_outbox("renew", event_id, "ducklake", old, 21)


@pytest.mark.parametrize("seconds", [0, -1, True, "10", None, float("nan"), float("inf"), 86401])
def test_targeted_outbox_lease_bounds_leave_delivery_unchanged(tmp_path: Path, seconds: object) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        event_id = seed(registry, tmp_path)["event_id"]
        before = registry.get_outbox_event("ducklake", event_id)
        with pytest.raises(RegistryError):
            registry.claim_outbox_event("claim-bad", event_id, "ducklake", "mirror", seconds)
        assert registry.get_outbox_event("ducklake", event_id) == before
        lease = registry.claim_outbox_event("claim", event_id, "ducklake", "mirror")["delivery"]["lease"]
        before = registry.get_outbox_event("ducklake", event_id)
        with pytest.raises(RegistryError):
            registry.renew_outbox("renew-bad", event_id, "ducklake", lease, seconds)
        assert registry.get_outbox_event("ducklake", event_id) == before


def test_targeted_outbox_claim_rejects_invalid_worker_without_leasing(tmp_path: Path) -> None:
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts") as registry:
        event_id = seed(registry, tmp_path)["event_id"]
        for worker in (None, True, [], "", "invalid worker", "x" * 257):
            with pytest.raises(RegistryError, match="worker_id"):
                registry.claim_outbox_event("bad-worker", event_id, "ducklake", worker)
        assert registry.get_outbox_event("ducklake", event_id)["status"] == "pending"


def test_outbox_renewal_rejects_pending_expired_replaced_and_foreign_lease(tmp_path: Path) -> None:
    clock = Clock()
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts", clock=clock) as registry:
        first = seed(registry, tmp_path)["event_id"]
        second = seed(registry, tmp_path, "second")["event_id"]
        with pytest.raises(RegistryError, match="not leased"):
            registry.renew_outbox("renew-pending", first, "ducklake", {})
        lease = registry.claim_outbox_event("claim-first", first, "ducklake", "mirror", 10)["delivery"]["lease"]
        other = registry.claim_outbox_event("claim-second", second, "ducklake", "mirror", 10)["delivery"]["lease"]
        with pytest.raises(RegistryError, match="stale"):
            registry.renew_outbox("renew-foreign", second, "ducklake", lease)
        with pytest.raises(RegistryError, match="already leased"):
            registry.claim_outbox_event("claim-live", first, "ducklake", "another")
        clock.now += 10  # Equality at expiry is no longer a live lease.
        with pytest.raises(RegistryError, match="stale"):
            registry.renew_outbox("renew-expired", first, "ducklake", lease)
        replaced = registry.claim_outbox_event("claim-replacement", first, "ducklake", "another")["delivery"]["lease"]
        assert replaced["fence"] == lease["fence"] + 1
        with pytest.raises(RegistryError, match="stale"):
            registry.renew_outbox("renew-replaced", first, "ducklake", lease)
        assert registry.get_outbox_event("ducklake", second)["lease"] == other


def test_outbox_lost_claim_and_renew_responses_replay_across_owner_restart(tmp_path: Path) -> None:
    clock = Clock()
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts, clock=clock) as registry:
        event_id = seed(registry, tmp_path)["event_id"]
        claim_payload = {"event_id": event_id, "consumer": "ducklake", "worker_id": "mirror", "lease_seconds": 10}
        with pytest.raises(ConnectionError, match="lost after commit"):
            registry.claim_outbox_event("claim", **claim_payload)
            raise ConnectionError("lost after commit")
        claim = registry.resolve_operation("claim", "ClaimOutboxEvent", claim_payload)
        assert registry.claim_outbox_event("claim", **claim_payload) == claim
        clock.now += 1
        renew_payload = {"event_id": event_id, "consumer": "ducklake", "lease": claim["delivery"]["lease"], "lease_seconds": 20}
        with pytest.raises(ConnectionError, match="lost after commit"):
            registry.renew_outbox("renew", **renew_payload)
            raise ConnectionError("lost after commit")
        renewed = registry.resolve_operation("renew", "RenewOutbox", renew_payload)
        persisted = registry.get_outbox_event("ducklake", event_id)
    with AutoencoderRegistry(db, artifacts, clock=clock) as registry:
        assert registry.claim_outbox_event("claim", **claim_payload) == claim
        assert registry.renew_outbox("renew", **renew_payload) == renewed
        assert registry.resolve_operation("renew", "RenewOutbox", renew_payload) == renewed
        assert registry.get_outbox_event("ducklake", event_id) == persisted
        with pytest.raises(RegistryError, match="stale"):
            registry.renew_outbox("renew-restarted", event_id, "ducklake", renewed["lease"])
        with pytest.raises(RegistryError, match="stale"):
            registry.ack_outbox("ack-restarted", event_id, "ducklake", {}, renewed["lease"])
        current = registry.claim_outbox_event("claim-restarted", event_id, "ducklake", "mirror")["delivery"]
        assert current["lease"]["fence"] == renewed["lease"]["fence"] + 1
        assert current["lease"]["owner_generation"] == registry.owner_generation
        with pytest.raises(RegistryError, match="different payload"):
            registry.claim_outbox_event("claim", **{**claim_payload, "worker_id": "other"})
        registry.ack_outbox("ack-current", event_id, "ducklake", {"commit": "fixture"}, current["lease"])


def test_targeted_reclaim_after_partial_ack_does_not_lease_new_batch_members(tmp_path: Path) -> None:
    db, artifacts = tmp_path / "control.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(db, artifacts) as registry:
        seed(registry, tmp_path, "first")
        seed(registry, tmp_path, "second")
        batch = registry.claim_outbox("batch", "ducklake", "mirror", limit=2)["deliveries"]
        acknowledged, remaining = batch
        ack_receipt = {"batch": "fixed-batch", "commit": "synthetic"}
        ack = registry.ack_outbox("ack-first", acknowledged["event_id"], "ducklake", ack_receipt, acknowledged["lease"])
        unrelated = seed(registry, tmp_path, "new-event")["event_id"]
        before_unrelated = registry.get_outbox_event("ducklake", unrelated)
    with AutoencoderRegistry(db, artifacts) as registry:
        assert registry.ack_outbox("ack-first", acknowledged["event_id"], "ducklake", ack_receipt, acknowledged["lease"]) == ack
        with pytest.raises(RegistryError, match="acknowledged"):
            registry.claim_outbox_event("claim-acknowledged", acknowledged["event_id"], "ducklake", "mirror")
        recovered = registry.claim_outbox_event("claim-remaining", remaining["event_id"], "ducklake", "mirror")["delivery"]
        assert recovered["event_id"] == remaining["event_id"]
        assert recovered["payload"] == remaining["payload"]
        assert recovered["kind"] == remaining["kind"]
        assert recovered["lease"]["fence"] == remaining["lease"]["fence"] + 1
        assert registry.get_outbox_event("ducklake", unrelated) == before_unrelated
        registry.ack_outbox("ack-remaining", recovered["event_id"], "ducklake", ack_receipt, recovered["lease"])
        assert [item["event_id"] for item in registry.pending_outbox("ducklake")] == [unrelated]
