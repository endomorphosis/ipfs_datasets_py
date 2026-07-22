"""Tests for daemon-cycle hammer guidance integration."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    uscode_modal_daemon_runner as runner,
)


def _args(tmp_path: Path, **overrides: object) -> Namespace:
    values = {
        "daemon_hammer_guidance_cache_enabled": True,
        "daemon_hammer_guidance_enabled": True,
        "daemon_hammer_guidance_learning_rate": 0.05,
        "daemon_hammer_guidance_max_obligations_per_sample": 2,
        "daemon_hammer_guidance_max_premises": 16,
        "daemon_hammer_guidance_max_samples_per_cycle": 1,
        "daemon_hammer_guidance_max_training_items": 16,
        "daemon_hammer_guidance_output_dir": str(tmp_path / "hammer-guidance"),
        "daemon_hammer_guidance_parallel_workers": 1,
        "daemon_hammer_guidance_timeout_seconds": 0.01,
        "daemon_hammer_guidance_train_autoencoder": True,
        "daemon_hammer_guidance_train_missing_samples": False,
        "daemon_hammer_guidance_trusted_requires_reconstruction": False,
        "daemon_hammer_guidance_verify_reconstruction": False,
        "leanstral_direct_guidance_path": "",
        "run_id": "daemon-hammer-test",
    }
    values.update(overrides)
    return Namespace(**values)


def _trusted_hammer_artifact(sample_id: str, guidance_id: str = "hammer-guidance-1") -> dict:
    return {
        "backend_statuses": {"z3": "proved"},
        "guidance_id": guidance_id,
        "legal_ir_view": "deontic.ir",
        "logic_family": "deontic",
        "metadata": {
            "obligation_kind": "deontic_polarity",
            "sample_id": sample_id,
        },
        "obligation_id": guidance_id,
        "premise_views": ["deontic.ir"],
        "proof_checked": True,
        "proof_obligation_ids": [guidance_id],
        "proved": True,
        "reconstruction_status": "verified",
        "schema_version": "legal-ir-hammer-guidance-v1",
        "selected_premises": ["premise.deontic_must_implies_obligation"],
        "source": "hammer_verified_guidance",
        "target_component": "deontic.ir",
        "target_metrics": ["hammer_proof_success_rate"],
        "trusted": True,
        "winner_backend": "z3",
    }


def _patch_contract_projection_and_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def project(_args: Namespace, sample: object):
        sample_id = runner._daemon_hammer_sample_id(sample)
        return (
            {
                "citation": runner._daemon_hammer_sample_citation(sample),
                "legal_ir_views": {},
                "modal_ir": getattr(sample, "modal_ir", None),
                "sample_id": sample_id,
                "text": getattr(sample, "text", ""),
            },
            {
                "adapter_count": 5,
                "bridge_failures": {},
                "contract_view_counts": {},
                "document_hash": "contract-projection-unit",
            },
        )

    monkeypatch.setattr(runner, "_daemon_hammer_contract_sample", project)
    monkeypatch.setattr(
        runner,
        "_daemon_hammer_runtime_canary",
        lambda _config: {
            "checker_routes": ["lean"],
            "proved_count": 1,
            "reconstruction_count": 1,
            "schema_version": "legal-ir-hammer-runtime-canary-v1",
            "status": "passed",
            "trusted_count": 1,
            "winner_backends": ["z3_python"],
        },
    )


def test_daemon_hammer_cycle_persists_guidance_and_updates_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_contract_projection_and_canary(monkeypatch)
    sample = build_us_code_sample(
        title="5",
        section="552",
        text="The agency shall provide notice unless an exception applies.",
    )

    obligation_limits: list[int | None] = []
    generate_obligations = runner.generate_legal_ir_proof_obligations

    def bounded_obligations(sample_arg: object, *, max_obligations: int | None = None):
        obligation_limits.append(max_obligations)
        return generate_obligations(sample_arg, max_obligations=max_obligations)

    def fake_run_legal_ir_hammer(*args: object, **kwargs: object) -> dict:
        assert kwargs["config"].max_obligations == 2
        return {
            "artifacts": [_trusted_hammer_artifact(sample.sample_id)],
            "metadata": {"backend_health": {"available_routes": ["z3"]}},
            "obligation_count": len(kwargs["obligations"]),
            "premise_count": 4,
            "proved_count": 1,
            "schema_version": "legal-ir-hammer-report-v1",
            "trusted_count": 1,
        }

    monkeypatch.setattr(
        runner,
        "generate_legal_ir_proof_obligations",
        bounded_obligations,
    )
    monkeypatch.setattr(runner, "run_legal_ir_hammer", fake_run_legal_ir_hammer)

    report = runner.run_daemon_hammer_guidance_cycle(
        args=_args(tmp_path),
        root=tmp_path,
        cycle=1,
        samples=[sample],
        autoencoder=AdaptiveModalAutoencoder(),
        samples_by_id={sample.sample_id: sample},
    )

    artifact_path = Path(report["output_path"])
    assert report["status"] == "completed"
    assert report["hammer_artifact_count"] == 1
    assert report["hammer_metrics"]["hammer_proof_success_rate"] == 1.0
    assert report["hammer_metrics"]["hammer_reconstruction_success_rate"] == 1.0
    assert report["trusted_hammer_guidance_count"] == 1
    assert obligation_limits == [2]
    assert artifact_path.is_file()
    persisted = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == runner.DAEMON_HAMMER_GUIDANCE_CYCLE_SCHEMA_VERSION
    assert persisted["sample_ids"] == [sample.sample_id]

    summary: dict[str, object] = {}
    runner.update_daemon_hammer_guidance_summary(
        summary,
        report,
        projection={"projection_sources": [{"hammer_failure_projection": {"seeded_count": 3}}]},
    )
    assert summary["hammer_proof_success_rate"] == 1.0
    assert summary["hammer_reconstruction_success_rate"] == 1.0
    assert summary["leanstral_hammer_candidate_count"] == 0
    assert summary["trusted_hammer_guidance_count"] == 1
    assert summary["hammer_projected_todo_count"] == 3
    assert summary["hammer_runtime_canary_passed"] is True
    compact = summary["latest_daemon_hammer_guidance"]
    assert compact["hammer_report_count"] == 1
    assert compact["omitted_hammer_guidance_artifact_count"] == 1
    assert compact["summary_payload_compacted"] is True
    assert "hammer_guidance_artifacts" not in compact
    assert "hammer_reports" not in compact


def test_daemon_hammer_cycle_reuses_cache_and_counts_leanstral_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_contract_projection_and_canary(monkeypatch)
    sample = build_us_code_sample(
        title="5",
        section="553",
        text="The agency may issue a rule after notice.",
    )
    leanstral_path = tmp_path / "leanstral-guidance.json"
    leanstral_path.write_text(
        json.dumps(
            {
                "leanstral_guidance": {
                    "drafted_logic_candidates": [
                        {
                            "candidate": "permission(agency, issue_rule)",
                            "compiler_surface": "deontic.ir",
                            "guidance_only": True,
                            "logic_family": "deontic",
                            "proof_obligation_id": "obl-leanstral",
                        }
                    ],
                    "guidance_id": "leanstral-draft-1",
                    "sample_id": sample.sample_id,
                    "source": "leanstral_shadow_proof",
                    "target_component": "deontic.ir",
                    "trusted": True,
                }
            }
        ),
        encoding="utf-8",
    )

    calls = {"count": 0}

    def fake_run_legal_ir_hammer(*args: object, **kwargs: object) -> dict:
        calls["count"] += 1
        return {
            "artifacts": [_trusted_hammer_artifact(sample.sample_id, "hammer-cache")],
            "obligation_count": len(kwargs["obligations"]),
            "premise_count": 4,
            "proved_count": 1,
            "schema_version": "legal-ir-hammer-report-v1",
            "trusted_count": 1,
        }

    monkeypatch.setattr(runner, "run_legal_ir_hammer", fake_run_legal_ir_hammer)
    args = _args(tmp_path)
    first = runner.run_daemon_hammer_guidance_cycle(
        args=args,
        root=tmp_path,
        cycle=2,
        samples=[sample],
        artifact_paths=[leanstral_path],
    )
    second = runner.run_daemon_hammer_guidance_cycle(
        args=args,
        root=tmp_path,
        cycle=2,
        samples=[sample],
        artifact_paths=[leanstral_path],
    )

    assert calls["count"] == 1
    assert first["leanstral_hammer_candidate_count"] == 1
    assert second["status"] == "cache_hit"
    assert second["cache_hit"] is True
    assert second["leanstral_hammer_candidate_count"] == 1


def test_daemon_hammer_cycle_skips_cleanly_without_samples(tmp_path: Path) -> None:
    report = runner.run_daemon_hammer_guidance_cycle(
        args=_args(tmp_path),
        root=tmp_path,
        cycle=3,
        samples=[],
    )

    assert report["status"] == "skipped_no_samples"
    assert report["artifact_paths"] == []
    assert report["hammer_metrics"]["hammer_artifact_count"] == 0
