"""Measured execution-boundary tests for the LegalIR hparam scheduler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hparam_execution import (
    DEFAULT_RUNG_BUDGETS,
    FAMILY_METRIC_NAMES,
    FidelityProfile,
    IMMUTABLE_BUDGET_SECONDS,
    METRIC_NAMES,
    SeedRun,
    _aggregate_seed_metrics,
    _paired_delta_estimate,
    _trial_command,
    build_fidelity_profiles,
    build_scheduler_from_baseline,
    extract_rollout_baseline_metrics,
    extract_summary_metrics,
    main,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hparam_scheduler import (
    DEFAULT_REQUIRED_FAMILIES,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    _configured_validation_canary_indices,
    build_uscode_modal_daemon_arg_parser as build_daemon_parser,
)


def _family_row(offset: float = 0.0) -> dict[str, float]:
    return {
        "ir_cross_entropy_loss": 0.8 - offset,
        "ir_cosine_similarity": 0.7 + offset,
        "autoencoder_cross_entropy_loss": 0.9 - offset,
        "autoencoder_cosine_similarity": 0.75 + offset,
        "score": 0.8 + offset,
        "symbolic_validity_success_rate": 1.0,
        "hammer_proof_success_rate": 0.5 + offset,
        "reconstruction_success_rate": 0.8 + offset,
        "uncertainty": 0.1 - offset,
        "source_copy_penalty": 0.0,
        "source_copy_reward_hack_penalty": 0.0,
        "sample_count": 8,
        "metric_coverage": 1.0,
        "observed_metrics": [
            "autoencoder_cosine_similarity",
            "autoencoder_cross_entropy_loss",
            "hammer_proof_success_rate",
            "ir_cosine_similarity",
            "ir_cross_entropy_loss",
            "reconstruction_success_rate",
            "source_copy_penalty",
            "symbolic_validity_success_rate",
        ],
    }


def _summary(offset: float = 0.0) -> dict[str, object]:
    return {
        "best_validation_ce": 0.9 - offset,
        "best_validation_cosine": 0.75 + offset,
        "best_validation_learned_ir_view_ce": 0.8 - offset,
        "best_validation_learned_ir_view_cosine": 0.7 + offset,
        "latest_autoencoder_validation": {
            "cross_entropy_loss": 0.9 - offset,
            "cosine_similarity": 0.75 + offset,
        },
        "latest_learned_ir_validation": {
            "view_cross_entropy_loss": 0.8 - offset,
            "view_cosine_similarity": 0.7 + offset,
        },
        "latest_legal_ir_view_family_validation": {
            "view_family_metrics": {
                family: _family_row(offset) for family in DEFAULT_REQUIRED_FAMILIES
            }
        },
    }


def _baseline_files(tmp_path: Path) -> tuple[dict[str, object], Path, Path]:
    summary = tmp_path / "baseline.summary"
    state = tmp_path / "baseline.state.json"
    summary.write_text(json.dumps(_summary()), encoding="utf-8")
    state.write_text('{"state": true}\n', encoding="utf-8")
    evidence: dict[str, object] = {
        "manifest_sha256": "sha256:" + "1a" * 32,
        "lineage": {
            "code_revision": "a" * 40,
            "configuration_sha256": "sha256:" + "2b" * 32,
            "fixture_sha256": "sha256:" + "3c" * 32,
            "baseline_state_id": "baseline",
            "final_state_revision": "state-final",
        },
    }
    return evidence, summary, state


def test_extract_summary_metrics_uses_learned_ir_and_complete_families() -> None:
    metrics, families = extract_summary_metrics(_summary(0.02))
    assert set(metrics) == set(METRIC_NAMES)
    assert set(families) == set(DEFAULT_REQUIRED_FAMILIES)
    assert set(families["deontic"]) == set(FAMILY_METRIC_NAMES)
    assert metrics["ir_cross_entropy_loss"] == 0.78
    assert metrics["ir_cosine_similarity"] == 0.72
    assert families["deontic"]["round_trip_success_rate"] == pytest.approx(0.82)


def test_scheduler_is_bound_to_measured_baseline_and_exact_budget(tmp_path: Path) -> None:
    evidence, summary, state = _baseline_files(tmp_path)
    scheduler, baseline = build_scheduler_from_baseline(
        evidence=evidence,
        baseline_summary=summary,
        baseline_state=state,
        candidate_count=6,
        seeds_per_candidate=3,
        max_concurrent_trainers=2,
    )
    assert scheduler.config.rung_budgets_seconds == DEFAULT_RUNG_BUDGETS
    assert scheduler.config.planned_resource_seconds == IMMUTABLE_BUDGET_SECONDS
    assert scheduler.config.require_multi_seed_evidence is True
    assert scheduler.config.require_cuda_evidence is True
    assert scheduler.config.baseline.metrics
    assert baseline["summary_sha256"].startswith("sha256:")
    assert all(len(candidate.seeds) == 3 for candidate in scheduler.candidates)


def test_seed_confidence_is_conservative_and_baseline_bound() -> None:
    baseline = {name: 0.5 for name in METRIC_NAMES}
    seeds = [
        {name: 0.5 + (index * 0.01) for name in METRIC_NAMES}
        for index in range(3)
    ]
    aggregate, confidence = _aggregate_seed_metrics(seeds, baseline)
    assert set(aggregate) == set(METRIC_NAMES)
    assert confidence["ir_cosine_similarity"]["confidence_level"] == 0.95
    assert confidence["ir_cosine_similarity"]["candidate_lower_bound"] < 0.5
    assert confidence["ir_cross_entropy_loss"]["candidate_upper_bound"] > 0.5
    assert confidence["ir_cross_entropy_loss"]["baseline_lower_bound"] == 0.5


def test_trial_command_is_cuda_only_seeded_and_warm_started(tmp_path: Path) -> None:
    profile = FidelityProfile(
        rung_index=0,
        name="unit",
        validation_canary_indices=(11, 29, 41),
        train_count=1,
        validation_count=1,
        max_sample_text_chars=600,
    )
    command = _trial_command(
        python=Path("/venv/python"),
        run_id="candidate-r0-s7",
        seed=7,
        params={
            "lr": 0.3,
            "ce": 1.5,
            "rec": 0.7,
            "cos": 0.7,
            "legal": 1.25,
            "hard": 0.6,
            "fam": 0.95,
            "emb": 0.55,
        },
        warm_state=tmp_path / "baseline.state.json",
        fidelity_profile=profile,
    )
    joined = " ".join(command)
    assert "--autoencoder-device cuda" in joined
    assert "--sampling-seed 7" in joined
    assert "--duration-seconds 900" in joined
    assert "--max-cycles 1" in joined
    assert "--train-count 1" in joined
    assert "--validation-count 1" in joined
    assert "--max-sample-text-chars 600" in joined
    assert "--autoencoder-projection-deadband-mode enforce" in joined
    assert "--autoencoder-max-ce-deadband 0.0001" in joined
    assert "--test-every-cycles 0" in joined
    assert "--validation-canary-indices 11,29,41" in joined
    assert "--warm-start-state" in command
    assert "--bridge-loss-adapters modal_frame_logic,deontic_norms" in joined


def test_fidelity_profiles_are_nested_and_finish_on_full_task117_holdout() -> None:
    indices = (10, 20, 30, 40, 50, 60, 70, 80)
    lengths = (2312, 1078, 2218, 2189, 1271, 504, 1642, 516)
    summary = {
        "latest_compiler_ir_validation": {
            "sample_metric_records": [
                {"original_text_length": length} for length in lengths
            ]
        }
    }
    profiles = build_fidelity_profiles(summary, indices)
    assert DEFAULT_RUNG_BUDGETS == (180, 360, 1350)
    assert profiles[0].validation_canary_indices == (60,)
    assert profiles[1].validation_canary_indices == (60, 80)
    assert set(profiles[0].validation_canary_indices) < set(
        profiles[1].validation_canary_indices
    )
    assert profiles[2].validation_canary_indices == indices
    assert profiles[2].max_sample_text_chars == 2500


def test_early_rung_estimate_uses_paired_delta_anchored_to_full_baseline(
    tmp_path: Path,
) -> None:
    baseline_summary = _summary()
    baseline_metrics, baseline_families = extract_summary_metrics(baseline_summary)
    candidate_summary = _summary(0.02)
    candidate_summary["latest_rollout_baseline_snapshot"] = {
        "validation": baseline_summary["latest_autoencoder_validation"],
        "learned_ir_view_validation": baseline_summary[
            "latest_learned_ir_validation"
        ],
        "legal_ir_view_family_validation": baseline_summary[
            "latest_legal_ir_view_family_validation"
        ],
    }
    profile = FidelityProfile(0, "unit", (11,), 1, 1, 600)
    run = SeedRun(
        candidate_id="candidate",
        rung_index=0,
        seed=7,
        run_id="candidate-r0-s7",
        requested_seconds=60,
        returncode=0,
        elapsed_wall_seconds=20.0,
        summary_path=tmp_path / "candidate.summary",
        state_path=tmp_path / "candidate.state.json",
        stdout_path=tmp_path / "candidate.stdout",
        stderr_path=tmp_path / "candidate.stderr",
        summary=candidate_summary,
        expected_validation_canary_indices=(11,),
        fidelity_profile=profile,
    )
    before_metrics, _before_families = extract_rollout_baseline_metrics(
        candidate_summary
    )
    estimated_metrics, estimated_families = _paired_delta_estimate(
        runs=[run],
        baseline_metrics=baseline_metrics,
        baseline_families=baseline_families,
    )
    assert before_metrics == baseline_metrics
    assert estimated_metrics["ir_cross_entropy_loss"] == pytest.approx(0.78)
    assert estimated_metrics["ir_cosine_similarity"] == pytest.approx(0.72)
    assert estimated_families["deontic"]["ir_cross_entropy_loss"] == pytest.approx(
        0.78
    )


def test_dry_run_is_non_promotable_and_creates_no_output(
    tmp_path: Path,
    capsys,
) -> None:
    evidence, summary, state = _baseline_files(tmp_path)
    evidence_path = tmp_path / "smoke.json"
    output = tmp_path / "selection.json"
    work_root = tmp_path / "work"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    result = main(
        [
            "--run-id",
            "unit-search",
            "--repo-root",
            str(tmp_path),
            "--baseline-evidence",
            str(evidence_path),
            "--baseline-summary",
            str(summary),
            "--baseline-state",
            str(state),
            "--output",
            str(output),
            "--work-root",
            str(work_root),
            "--dry-run",
        ]
    )
    printed = json.loads(capsys.readouterr().out)
    assert result == 0
    assert printed["execution"] is False
    assert printed["promotable_evidence"] is False
    assert not output.exists()
    assert not work_root.exists()


def test_validation_canary_indices_are_pinned_separately_from_training_seed() -> None:
    args = build_daemon_parser().parse_args(
        [
            "--run-id",
            "unit",
            "--validation-canary-count",
            "3",
            "--validation-canary-indices",
            "11,29,41",
            "--sampling-seed",
            "999",
        ]
    )
    assert _configured_validation_canary_indices(args) == (11, 29, 41)
    assert args.sampling_seed == "999"
