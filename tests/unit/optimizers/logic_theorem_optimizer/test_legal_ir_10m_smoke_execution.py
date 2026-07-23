"""Execution-receipt tests for PORTAL-LIR-HAMMER-117."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.ops.legal_ir.verify_legal_ir_run_evidence import (
    REQUIRED_FAMILIES,
    REQUIRED_METRIC_BRIDGE_ADAPTERS,
    REQUIRED_QUALITY_METRICS,
    SCHEMA_VERSION,
    _family_quality_pair,
    _strict_contract_evidence,
    _strict_hammer_runtime_canary,
    _strict_metric_evidence,
    manifest_sha256,
    verify_evidence,
    write_evidence,
)


ROOT = Path(__file__).resolve().parents[4]
RUNNER = ROOT / "scripts/ops/legal_ir/run_legal_ir_10m_smoke.sh"
CANONICAL_RUNNER = ROOT / "scripts/ops/legal_ir/run_hammer_leanstral_smoke.sh"
VERIFIER = ROOT / "scripts/ops/legal_ir/verify_legal_ir_run_evidence.py"
COMMITTED_EVIDENCE = (
    ROOT
    / "docs/implementation/reports/evidence/legal_ir_10_minute_integrated_smoke.json"
)
SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
SHA_D = "sha256:" + "d" * 64
EXPECTED_HARD_GUARDRAILS = (
    "compiler_ir_cosine,structural_validity,source_copy_penalty,"
    "source_copy_reward_hack_penalty,hammer_proof_success_rate,"
    "hammer_reconstruction_success_rate,symbolic_validity_success_rate"
)


def _qualities() -> dict[str, object]:
    values = {
        "ir_cross_entropy_loss": 0.31,
        "ir_cosine_similarity": 0.81,
        "autoencoder_cross_entropy_loss": 0.29,
        "autoencoder_cosine_similarity": 0.84,
        "semantic_equivalence": 0.91,
        "proof_success_rate": 0.72,
        "reconstruction_success_rate": 0.70,
        "provenance": 0.98,
        "round_trip": 0.94,
        "uncertainty": 0.10,
        "holdout": 0.88,
        "source_copy_penalty": 0.04,
    }
    return {
        family: {
            "sample_count": 8,
            "baseline_sample_count": 8,
            "candidate_sample_count": 8,
            "baseline_metric_coverage": 1.0,
            "candidate_metric_coverage": 1.0,
            "baseline_observed_metrics": [
                "ir_cosine_similarity",
                "ir_cross_entropy_loss",
            ],
            "candidate_observed_metrics": [
                "ir_cosine_similarity",
                "ir_cross_entropy_loss",
            ],
            "guardrail_passed": True,
            "baseline": dict(values),
            "candidate": dict(values),
        }
        for family in REQUIRED_FAMILIES
    }


def complete_evidence() -> dict[str, object]:
    configuration = {
        "active_duration_seconds": 600,
        "canonical_runner_budget_seconds": 610,
        "paired_cycle_completion_grace_seconds": 240,
        "paired_codex_queue_grace_seconds": 0,
        "paired_shutdown_poll_cushion_seconds": 120,
        "autoencoder_device": "cuda:0",
        "codex_apply_mode": "patch_only",
        "fixture_seed": "PORTAL-LIR-HAMMER-117-fixed-smoke-v1",
        "max_codex_todos": 8,
        "validation_canary_count": 8,
    }
    configuration_digest = manifest_sha256(configuration)
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "PORTAL-LIR-HAMMER-117",
        "run_id": "legal-ir-smoke-unit",
        "stage": "ten_minute_smoke",
        "dry_run": False,
        "simulated": False,
        "fixture_replay": False,
        "complete": True,
        "decision": "passed",
        "timing": {
            "started_at": "2026-07-22T00:00:00+00:00",
            "ended_at": "2026-07-22T00:10:20+00:00",
            "generated_at": "2026-07-22T00:10:21+00:00",
            "wall_seconds": 620.0,
            "active_seconds": 600.0,
            "startup_seconds": 20.0,
            "downtime_seconds": 0.0,
            "active_intervals": [
                {
                    "started_at": "2026-07-22T00:00:20+00:00",
                    "ended_at": "2026-07-22T00:10:20+00:00",
                    "active_seconds": 600.0,
                }
            ],
        },
        "lineage": {
            "run_id": "legal-ir-smoke-unit",
            "stage": "ten_minute_smoke",
            "code_revision": "1" * 40,
            "source_tree_sha256": SHA_A,
            "baseline_state_id": "baseline-unit",
            "baseline_state_revision": "state-100",
            "baseline_state_sha256": SHA_B,
            "final_state_revision": "state-102",
            "final_state_sha256": SHA_C,
            "fixture_id": "fixed-smoke-v1",
            "fixture_sha256": SHA_D,
            "configuration_id": "task-117-selected-v1",
            "configuration_sha256": configuration_digest,
            "holdout_id": "fixed-canary-v1",
            "holdout_sha256": SHA_A,
        },
        "selected_configuration": configuration,
        "fixed_fixture": {
            "fixture_id": "fixed-smoke-v1",
            "sha256": SHA_D,
            "immutable": True,
            "replay": False,
        },
        "progress": {
            "warm_cycles_completed": 2,
            "sample_count_start": 100,
            "sample_count_end": 108,
            "state_revision_start": "state-100",
            "state_revision_end": "state-102",
            "resume_count": 0,
            "resumes": [],
        },
        "model_context": {
            "model_id": "Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4",
            "model_sha256": SHA_B,
            "context_size": 2048,
            "context_fingerprint": "leanstral-context-unit",
            "service_generation": "generation-unit",
            "device": "cuda:0",
        },
        "services": {
            "cuda_autoencoder": {
                "backend": "torch_cuda",
                "device": "cuda:0",
                "cpu_fallback": False,
                "simulated": False,
                "forward_count": 2,
                "loss_count": 2,
                "backward_count": 2,
                "optimizer_step_count": 2,
            },
            "leanstral": {
                "healthy": True,
                "persistent": True,
                "device": "cuda:0",
                "cpu_fallback": False,
                "generation": "generation-unit",
                "model_id": "Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4",
                "context_fingerprint": "leanstral-context-unit",
                "model_load_count": 1,
                "preflight_count": 1,
                "request_count": 3,
                "reuse_count": 2,
                "healthy_cuda_service_reused": True,
                "queue_seconds": 1.0,
                "inference_seconds": 40.0,
                "verification_seconds": 3.0,
                "restart_seconds": 0.0,
            },
            "hammer": {
                "healthy": True,
                "backend_available": True,
                "evidence_kind": "runtime_canary",
                "winner_backends": ["z3_python"],
                "checker_routes": ["lean"],
                "obligation_count": 1,
                "backend_attempt_count": 1,
                "proof_attempt_count": 1,
                "proved_count": 1,
                "reconstruction_count": 1,
                "trusted_guidance_count": 1,
                "legal_obligation_count": 16,
                "legal_proof_attempt_count": 16,
                "legal_proved_count": 8,
                "legal_reconstruction_count": 4,
                "legal_trusted_guidance_count": 4,
                "fatal_failure_count": 0,
            },
            "contract_validation": {
                "coverage": 1.0,
                "failure_count": 0,
                "failure_counts": {
                    "cross_view_mismatches": 0,
                    "decompiler_preservation_failures": 0,
                    "missing_required_fields": 0,
                    "provenance_policy_failures": 0,
                    "validation_errors": 0,
                },
                "family_gap_count": 0,
            },
            "metric_evaluation": {
                "evaluated_count": 16,
                "failure_count": 0,
                "sample_count": 16,
                "sample_timeout_count": 0,
                "timeout_fallback_count": 0,
            },
            "codex": {
                "run_id": "legal-ir-smoke-unit",
                "fixture_sha256": SHA_D,
                "todo_count": 1,
                "max_todos": 8,
                "invocation_count": 1,
                "focused_validation_count": 1,
                "accepted_merge_count": 0,
                "safe_rejection_count": 1,
                "transient_failure_count": 0,
                "transient_requeue_count": 0,
                "queue_bytes_peak": 4096,
                "max_queue_bytes": 65536,
                "dispositions": [
                    {
                        "status": "safe_rejection",
                        "reason_code": "focused_validation_failed",
                        "focused_validation": True,
                        "todo_sha256": SHA_A,
                        "validation_sha256": SHA_B,
                    }
                ],
            },
            "watchdog": {
                "healthy": True,
                "status": "exited_cleanly",
                "heartbeat_count": 120,
                "max_heartbeat_gap_seconds": 6,
                "progress_heartbeat_count": 20,
                "max_progress_gap_seconds": 45,
                "missed_heartbeat_count": 0,
                "fatal_event_count": 0,
                "children_launched": 5,
                "children_reaped": 5,
                "orphaned_child_count": 0,
                "concurrent_writer_count": 0,
                "managed_children": [
                    {
                        "name": name,
                        "status": "exited",
                        "exit_code": 0,
                        "orphaned": False,
                    }
                    for name in (
                        "paired-supervisor",
                        "cuda-autoencoder",
                        "leanstral-worker",
                        "codex-worker",
                        "artifact-writer",
                    )
                ],
            },
        },
        "quality_families": _qualities(),
        "telemetry": {
            "stage_timings_seconds": {
                "cuda_training": 280.0,
                "snapshot_evaluation": 80.0,
                "hammer": 20.0,
                "leanstral": 160.0,
                "codex": 35.0,
                "focused_validation": 15.0,
                "persistence": 10.0,
            },
            "queue_timings_seconds": {
                "snapshot_queue_seconds": 2.0,
                "hammer_queue_seconds": 1.0,
                "leanstral_queue_seconds": 1.0,
                "codex_queue_seconds": 2.0,
                "persistence_queue_seconds": 1.0,
            },
            "queue_depth_peak": 8,
            "queue_depth_limit": 512,
        },
        "artifacts": {
            name: {
                "id": name + "-unit",
                "bytes": 1024,
                "max_bytes": 16 * 1024 * 1024,
                "sha256": SHA_C,
                "durable": True,
            }
            for name in (
                "autoencoder_summary",
                "paired_summary",
                "training_log",
                "checkpoint",
                "leanstral_service",
                "gate_decision",
            )
        },
    }
    payload["manifest_sha256"] = manifest_sha256(payload)
    return payload


def test_complete_receipt_passes() -> None:
    result = verify_evidence(
        complete_evidence(),
        now=datetime(2026, 7, 22, 0, 11, tzinfo=timezone.utc),
    )
    assert result.accepted, result.failures
    assert result.metrics["active_seconds"] == 600.0


def test_bounded_codex_retries_do_not_inflate_unique_todo_count() -> None:
    payload = complete_evidence()
    payload["services"]["codex"].update(
        todo_count=2,
        invocation_count=4,
        focused_validation_count=2,
        safe_rejection_count=2,
    )
    payload["services"]["codex"]["dispositions"][0]["count"] = 2
    payload["manifest_sha256"] = manifest_sha256(payload)
    result = verify_evidence(
        payload,
        now=datetime(2026, 7, 22, 0, 11, tzinfo=timezone.utc),
    )
    assert result.accepted, result.failures


@pytest.mark.parametrize(
    ("mutation", "failure"),
    [
        (lambda p: p.update(dry_run=True), "authenticity:dry_run"),
        (lambda p: p["timing"].update(active_seconds=599.99), "timing:insufficient_active_seconds"),
        (lambda p: p["progress"].update(warm_cycles_completed=1), "progress:fewer_than_two_warm_cycles"),
        (lambda p: p["progress"].update(sample_count_end=100), "progress:samples_not_advanced"),
        (lambda p: p["services"]["cuda_autoencoder"].update(cpu_fallback=True), "service:autoencoder:fallback_or_simulated"),
        (lambda p: p["services"]["leanstral"].update(model_load_count=2), "service:leanstral:weights_reloaded"),
        (lambda p: p["services"]["hammer"].update(reconstruction_count=0), "service:hammer:reconstruction_count"),
        (lambda p: p["services"]["hammer"].update(proved_count=0), "service:hammer:proved_count"),
        (lambda p: p["services"]["hammer"].update(trusted_guidance_count=0), "service:hammer:trusted_guidance_count"),
        (lambda p: p["services"]["hammer"].update(evidence_kind="legal_quality"), "service:hammer:evidence_kind"),
        (lambda p: p["services"]["hammer"].update(winner_backends=[]), "service:hammer:winner_backend"),
        (lambda p: p["services"]["hammer"].update(checker_routes=[]), "service:hammer:checker_route"),
        (lambda p: p["services"]["hammer"].update(legal_obligation_count=0), "service:hammer:legal_obligation_count"),
        (lambda p: p["services"]["hammer"].update(legal_proof_attempt_count=0), "service:hammer:legal_proof_attempt_count"),
        (lambda p: p["services"]["contract_validation"].update(coverage=0.0), "service:contract:coverage"),
        (lambda p: p["services"]["contract_validation"].update(failure_count=1), "service:contract:failure_count"),
        (lambda p: p["services"]["metric_evaluation"].update(sample_timeout_count=1), "service:metrics:sample_timeout_count"),
        (lambda p: p["services"]["codex"].update(safe_rejection_count=0), "service:codex:no_safe_terminal_path"),
        (lambda p: p["services"]["watchdog"].update(orphaned_child_count=1), "service:watchdog:orphaned_child_count"),
        (lambda p: p["services"]["watchdog"].update(max_progress_gap_seconds=361), "service:watchdog:progress_gap"),
        (lambda p: p["services"]["cuda_autoencoder"].update(loss_count=3), "service:autoencoder:operation_count_mismatch"),
        (lambda p: p["services"]["leanstral"].update(reuse_count=4), "service:leanstral:reuse_count_incoherent"),
        (lambda p: p["services"]["hammer"].update(reconstruction_count=17), "service:hammer:counter_progression"),
        (lambda p: p["quality_families"]["tdfol"].update(candidate_sample_count=0), "quality:tdfol:candidate_sample_coverage"),
        (lambda p: p["quality_families"]["cec"].update(candidate_observed_metrics=[]), "quality:cec:candidate_observed_metrics"),
    ],
)
def test_fail_closed_runtime_mutations(mutation, failure: str) -> None:
    payload = complete_evidence()
    mutation(payload)
    payload["manifest_sha256"] = manifest_sha256(payload)
    result = verify_evidence(payload, now=datetime(2026, 7, 22, 0, 11, tzinfo=timezone.utc))
    assert not result.accepted
    assert failure in result.failures


def test_each_family_metric_is_finite_and_non_regressing() -> None:
    for family in REQUIRED_FAMILIES:
        for metric in REQUIRED_QUALITY_METRICS:
            payload = complete_evidence()
            payload["quality_families"][family]["candidate"][metric] = float("nan")
            payload["manifest_sha256"] = manifest_sha256(payload)
            result = verify_evidence(payload, now=datetime(2026, 7, 22, 0, 11, tzinfo=timezone.utc))
            assert f"quality:{family}:{metric}:nonfinite_or_missing" in result.failures


def test_legacy_family_builder_does_not_borrow_global_sample_coverage() -> None:
    row = {
        "ir_cross_entropy_loss": 0.4,
        "ir_cosine_similarity": 0.8,
        "metric_coverage": 0.25,
        "observed_metrics": ["ir_cross_entropy_loss", "ir_cosine_similarity"],
        "sample_count": 0,
    }
    validation = {
        "cross_entropy_loss": 0.5,
        "cosine_similarity": 0.7,
        "sample_count": 8,
    }
    with pytest.raises(ValueError, match="family sample coverage"):
        _family_quality_pair(
            row,
            row,
            baseline_validation=validation,
            candidate_validation=validation,
            provenance_score=1.0,
            uncertainty_error=0.0,
        )


def test_legacy_metric_builder_rejects_numeric_failures_and_timeouts() -> None:
    adapters = {
        name: {"metric_failures": 0, "sample_count": 2}
        for name in REQUIRED_METRIC_BRIDGE_ADAPTERS
    }
    block = {
        "evaluated_count": 2,
        "metric_failures": 0,
        "sample_count": 2,
        "sample_timeouts": 0,
        "skipped_sample_count": 0,
        "timeout_fallback_count": 0,
    }
    auto = {
        "active_cycle_metric_bridge_adapters": sorted(REQUIRED_METRIC_BRIDGE_ADAPTERS),
        "bridge_metric_failures": 0,
        "latest_compiler_ir_validation": dict(block),
        "latest_compiler_ir_guided_validation": dict(block),
        "latest_logic_bridge_validation": {"adapters": adapters},
        "metric_failures": 0,
    }
    assert _strict_metric_evidence(auto)["sample_count"] == 4
    auto["metric_failures"] = 1
    with pytest.raises(ValueError, match="failures, timeouts"):
        _strict_metric_evidence(auto)
    auto["metric_failures"] = 0
    auto["latest_compiler_ir_validation"]["sample_timeouts"] = 1
    with pytest.raises(ValueError, match="failures, timeouts"):
        _strict_metric_evidence(auto)


def test_legacy_contract_builder_rejects_nested_failures() -> None:
    failure_counts = {
        "cross_view_mismatches": 0,
        "decompiler_preservation_failures": 0,
        "missing_required_fields": 0,
        "provenance_policy_failures": 0,
        "validation_errors": 0,
    }
    hammer = {
        "contract_projection_failure_count": 0,
        "legal_ir_contract_coverage": 1.0,
        "legal_ir_contract_failure_counts": failure_counts,
        "legal_ir_contract_view_family_gaps": [],
        "hammer_guidance_artifacts": [{"validation_errors": 1}],
    }
    with pytest.raises(ValueError, match="artifact reported"):
        _strict_contract_evidence({}, hammer)

    hammer["hammer_guidance_artifacts"] = []
    hammer["legal_ir_contract_view_family_gaps"] = {"cec": 1}
    with pytest.raises(ValueError, match="view-family gaps"):
        _strict_contract_evidence({}, hammer)


def test_runtime_canary_is_separate_from_legal_quality_counters() -> None:
    hammer = {
        "runtime_canary": {
            "checker_routes": ["lean"],
            "proved_count": 1,
            "reconstruction_count": 1,
            "schema_version": "legal-ir-hammer-runtime-canary-v1",
            "status": "passed",
            "trusted_count": 1,
            "winner_backends": ["z3_python"],
        },
        "hammer_metrics": {
            "hammer_proved_count": 0,
            "hammer_reconstruction_success_count": 0,
            "trusted_hammer_guidance_count": 0,
        },
    }

    assert _strict_hammer_runtime_canary(hammer)["proved_count"] == 1
    hammer["runtime_canary"]["winner_backends"] = ["cvc5"]
    with pytest.raises(ValueError, match="native Python Z3"):
        _strict_hammer_runtime_canary(hammer)


def test_manifest_digest_and_lineage_are_recomputed() -> None:
    payload = complete_evidence()
    payload["services"]["cuda_autoencoder"]["optimizer_step_count"] = 99
    result = verify_evidence(payload, now=datetime(2026, 7, 22, 0, 11, tzinfo=timezone.utc))
    assert "content_address:manifest_digest_mismatch" in result.failures

    payload = complete_evidence()
    payload["selected_configuration"]["max_codex_todos"] = 9
    payload["manifest_sha256"] = manifest_sha256(payload)
    result = verify_evidence(payload, now=datetime(2026, 7, 22, 0, 11, tzinfo=timezone.utc))
    assert "lineage:configuration_digest_mismatch" in result.failures


def test_atomic_writer_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"
    write_evidence(output, complete_evidence())
    assert json.loads(output.read_text())["manifest_sha256"] == manifest_sha256(json.loads(output.read_text()))
    with pytest.raises(FileExistsError):
        write_evidence(output, complete_evidence())


def test_cli_rejects_incomplete_evidence(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": SCHEMA_VERSION}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(VERIFIER), "--evidence", str(path), "--stage", "ten_minute_smoke", "--minimum-active-seconds", "600"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert "rejected" in result.stderr


def test_runner_contract_is_real_immutable_and_non_promotable_when_dry_run(tmp_path: Path) -> None:
    syntax = subprocess.run(["bash", "-n", str(RUNNER)], cwd=ROOT, check=False)
    assert syntax.returncode == 0
    env = dict(os.environ, DURATION_SECONDS="599")
    rejected = subprocess.run([str(RUNNER), "--dry-run"], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    assert rejected.returncode == 2
    assert "immutable" in rejected.stderr

    dry = subprocess.run([str(RUNNER), "--dry-run", "--run-id", "unit-dry-run"], cwd=ROOT, text=True, capture_output=True, check=False)
    assert dry.returncode == 0
    assert "execution=false" in dry.stdout
    assert "promotable_evidence=false" in dry.stdout
    assert "minimum_active_seconds=600" in dry.stdout
    assert "--autoencoder-metric-bridge-max-sample-text-chars 600" in dry.stdout
    assert "--paired-codex-queue-grace-seconds 360" in dry.stdout


def test_canonical_runner_extracts_one_guardrail_contract_from_noisy_stdout(tmp_path: Path) -> None:
    fake_python = tmp_path / "python-with-notices"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' 'dependency initialization notice' "
        f"'{EXPECTED_HARD_GUARDRAILS}' 'service availability notice'\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = dict(os.environ, PYTHON_BIN=str(fake_python), DURATION_SECONDS="600", MAX_CYCLES="0")

    result = subprocess.run(
        [str(CANONICAL_RUNNER), "--dry-run", "--run-id", "unit-noisy-guardrails"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"gate_metrics={EXPECTED_HARD_GUARDRAILS}" in result.stdout
    smoke_command = next(line for line in result.stdout.splitlines() if line.startswith("smoke_command="))
    assert EXPECTED_HARD_GUARDRAILS.replace(",", r"\,") in smoke_command
    assert "dependency initialization notice" not in smoke_command
    assert "service availability notice" not in smoke_command


def test_canonical_runner_rejects_ambiguous_guardrail_contract(tmp_path: Path) -> None:
    fake_python = tmp_path / "python-with-ambiguous-contract"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' '{EXPECTED_HARD_GUARDRAILS}' '{EXPECTED_HARD_GUARDRAILS}'\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = dict(os.environ, PYTHON_BIN=str(fake_python), DURATION_SECONDS="600", MAX_CYCLES="0")

    result = subprocess.run(
        [str(CANONICAL_RUNNER), "--dry-run", "--run-id", "unit-ambiguous-guardrails"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "exactly one canonical" in result.stderr


def test_committed_execution_receipt_verifies() -> None:
    assert COMMITTED_EVIDENCE.is_file()
    payload = json.loads(COMMITTED_EVIDENCE.read_text(encoding="utf-8"))
    result = verify_evidence(payload, evidence_path=COMMITTED_EVIDENCE)
    assert result.accepted, result.failures
