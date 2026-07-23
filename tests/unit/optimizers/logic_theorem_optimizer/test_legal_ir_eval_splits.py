from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
    CANARY_SPLIT,
    CODEX_TODO_PROJECTION_OPERATION,
    EXTERNAL_TEST_SPLIT,
    HOLDOUT_SPLIT,
    HPARAM_SELECTION_OPERATION,
    JURISDICTION_SPLIT,
    REPRESENTATION_PROMOTION_OPERATION,
    STATUTE_FAMILY_SPLIT,
    TEMPORAL_SPLIT,
    TRAINING_OPERATION,
    TRAIN_SPLIT,
    VALIDATION_SPLIT,
    LegalIREvalSplitConfig,
    LegalIRSplitExample,
    LegalIRSplitLeakageError,
    LegalIRSplitManifest,
    LegalIRSplitPolicyError,
    build_legal_ir_eval_splits,
    require_codex_todo_projection_split,
    require_hparam_selection_split,
    require_legal_ir_split_guard,
    require_representation_promotion_split,
    require_training_split,
    split_guard_blocks_operation,
    validate_legal_ir_eval_splits,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hparam_scheduler import (
    HParamSearchConfig,
    LegalIRHParamScheduler,
    SharedBaseline,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner import (
    compiler_guidance_promotion_gate,
    hammer_failure_projection_todos,
)
ROOT = Path(__file__).resolve().parents[4]


def _load_rollout_gate_module():
    module_name = "legal_ir_eval_splits_rollout_gate_under_test"
    module_path = ROOT / "scripts" / "ops" / "legal_ir" / "hammer_leanstral_rollout_gate.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - repository invariant
        raise ImportError(f"cannot load rollout gate from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_rollout_module = _load_rollout_gate_module()
LEGAL_IR_REPRESENTATION_METRICS = _rollout_module.LEGAL_IR_REPRESENTATION_METRICS
LEGAL_IR_VIEW_FAMILIES = _rollout_module.LEGAL_IR_VIEW_FAMILIES
RolloutGateConfig = _rollout_module.RolloutGateConfig
rollout_gate = _rollout_module.rollout_gate


def _sample(
    sample_id: str,
    *,
    citation: str,
    text: str,
    family: str = "privacy",
    jurisdiction: str = "us-federal",
    source: str = "us_code",
    source_document_id: str = "doc-a",
    start: int = 0,
    end: int = 40,
    amendment_group: str = "",
    effective_date: str = "2024-01-01",
) -> dict[str, object]:
    return {
        "amendment_group": amendment_group,
        "citation": citation,
        "effective_date": effective_date,
        "jurisdiction": jurisdiction,
        "sample_id": sample_id,
        "source": source,
        "source_document_id": source_document_id,
        "span_end": end,
        "span_start": start,
        "statute_family": family,
        "text": text,
    }


def _config() -> LegalIREvalSplitConfig:
    return LegalIREvalSplitConfig(
        seed="unit",
        train_ratio=0.70,
        validation_ratio=0.10,
        canary_ratio=0.10,
        holdout_ratio=0.10,
        statute_family_ratio=0.0,
        jurisdiction_ratio=0.0,
        temporal_ratio=0.0,
        statute_family_holdout_values=("tax",),
        jurisdiction_holdout_values=("oregon",),
        temporal_holdout_after="2025-01-01",
    )


def _corpus() -> list[dict[str, object]]:
    return [
        _sample(
            "train-a",
            citation="1 U.S.C. 1",
            text="A person shall file a report within 30 days.",
            start=0,
            end=50,
        ),
        _sample(
            "near-a",
            citation="2 U.S.C. 2",
            text="The agency shall publish a public notice within 30 days.",
            start=100,
            end=160,
        ),
        _sample(
            "near-b",
            citation="2 U.S.C. 2(a)",
            text="The agency shall publish public notice within thirty days.",
            start=170,
            end=230,
        ),
        _sample(
            "family-a",
            citation="26 U.S.C. 61",
            text="Gross income means all income from whatever source derived.",
            family="tax",
            source_document_id="tax-doc",
            start=0,
            end=50,
        ),
        _sample(
            "jurisdiction-a",
            citation="ORS 192.311",
            text="A public body shall disclose public records unless exempt.",
            family="records",
            jurisdiction="oregon",
            source_document_id="or-doc",
            start=0,
            end=50,
        ),
        _sample(
            "temporal-a",
            citation="5 U.S.C. 552",
            text="The amendment is effective after January 1 2026.",
            effective_date="2026-02-01",
            source_document_id="new-doc",
            start=0,
            end=50,
        ),
        _sample(
            "external-a",
            citation="Model Rule 1.1",
            text="A lawyer shall provide competent representation.",
            source="external",
            source_document_id="external-doc",
            start=0,
            end=50,
        ),
    ]


def test_builds_deterministic_leakage_resistant_partitions() -> None:
    first = build_legal_ir_eval_splits(_corpus(), _config())
    second = build_legal_ir_eval_splits(list(reversed(_corpus())), _config())

    assert first.digest == second.digest
    assert set(first.samples_by_split) >= {
        TRAIN_SPLIT,
        VALIDATION_SPLIT,
        CANARY_SPLIT,
        HOLDOUT_SPLIT,
        STATUTE_FAMILY_SPLIT,
        JURISDICTION_SPLIT,
        TEMPORAL_SPLIT,
        EXTERNAL_TEST_SPLIT,
    }
    assert first.assignments["family-a"] == STATUTE_FAMILY_SPLIT
    assert first.assignments["jurisdiction-a"] == JURISDICTION_SPLIT
    assert first.assignments["temporal-a"] == TEMPORAL_SPLIT
    assert first.assignments["external-a"] == EXTERNAL_TEST_SPLIT
    assert first.assignments["near-a"] == first.assignments["near-b"]
    assert first.guard_result().passed is True


def test_manifest_validation_detects_content_citation_and_near_duplicate_leakage() -> None:
    samples = [
        _sample(
            "train-copy",
            citation="5 U.S.C. 552(a)",
            text="An agency shall make records promptly available.",
            start=0,
            end=40,
        ),
        _sample(
            "holdout-copy",
            citation="5 U.S.C. 552(a)(1)",
            text="An agency shall make records promptly available.",
            start=80,
            end=120,
        ),
        _sample(
            "canary-near",
            citation="8 U.S.C. 1",
            text="The Secretary shall publish public notice within 30 days.",
            start=200,
            end=260,
        ),
        _sample(
            "train-near",
            citation="9 U.S.C. 1",
            text="The Secretary shall publish a public notice within thirty days.",
            start=300,
            end=360,
        ),
    ]
    manifest = build_legal_ir_eval_splits(
        samples,
        LegalIREvalSplitConfig(
            seed="leakage",
            train_ratio=1.0,
            validation_ratio=0.0,
            canary_ratio=0.0,
            holdout_ratio=0.0,
            statute_family_ratio=0.0,
            jurisdiction_ratio=0.0,
            temporal_ratio=0.0,
            near_duplicate_jaccard_threshold=0.70,
        ),
    )
    payload = manifest.to_dict(include_digest=False)
    payload["assignments"] = {
        **payload["assignments"],
        "holdout-copy": HOLDOUT_SPLIT,
        "canary-near": CANARY_SPLIT,
    }

    result = validate_legal_ir_eval_splits(payload)

    assert result.passed is False
    assert {violation.kind for violation in result.violations} >= {
        "content",
        "citation_cluster",
        "near_duplicate",
    }
    assert set(result.blocked_operations) == {
        TRAINING_OPERATION,
        HPARAM_SELECTION_OPERATION,
        REPRESENTATION_PROMOTION_OPERATION,
        CODEX_TODO_PROJECTION_OPERATION,
    }
    with pytest.raises(LegalIRSplitLeakageError):
        require_legal_ir_split_guard(payload, operation=TRAINING_OPERATION)

    compact = {
        "schema_version": "legal-ir-eval-splits-v1",
        "config_digest": "unit",
        "examples": [
            LegalIRSplitExample.from_sample(samples[0]).to_dict(),
        ],
        "samples_by_split": {
            TRAIN_SPLIT: ["train-copy"],
            HOLDOUT_SPLIT: ["train-copy"],
        },
    }
    compact_result = validate_legal_ir_eval_splits(compact)
    assert compact_result.passed is False
    assert any(
        violation.kind == "example" and violation.key == "train-copy"
        for violation in compact_result.violations
    )


def test_manifest_validation_detects_source_span_and_amendment_leakage() -> None:
    examples = [
        LegalIRSplitExample.from_sample(
            _sample(
                "train-span",
                citation="1 U.S.C. 10",
                text="A covered entity shall retain the form.",
                source_document_id="doc-span",
                start=10,
                end=80,
                amendment_group="amd-1",
            )
        ),
        LegalIRSplitExample.from_sample(
            _sample(
                "holdout-span",
                citation="1 U.S.C. 11",
                text="The covered entity shall retain the form for inspection.",
                source_document_id="doc-span",
                start=60,
                end=120,
                amendment_group="amd-1",
            )
        ),
    ]
    manifest = LegalIRSplitManifest(
        examples=tuple(examples),
        assignments={"train-span": TRAIN_SPLIT, "holdout-span": HOLDOUT_SPLIT},
        config_digest="unit",
    )

    result = manifest.guard_result()

    assert result.passed is False
    assert {violation.kind for violation in result.violations} >= {
        "source_span",
        "amendment",
    }


def test_operation_authorizers_reject_protected_examples_for_wrong_use() -> None:
    manifest = LegalIRSplitManifest(
        examples=tuple(LegalIRSplitExample.from_sample(item) for item in _corpus()[:3]),
        assignments={
            "train-a": TRAIN_SPLIT,
            "near-a": VALIDATION_SPLIT,
            "near-b": CANARY_SPLIT,
        },
        config_digest="unit",
    )
    # This manifest intentionally leaks the near-duplicate cluster, so any use
    # is blocked before operation-specific membership is considered.
    with pytest.raises(LegalIRSplitLeakageError):
        require_training_split(manifest, [{"sample_id": "train-a"}])

    clean = LegalIRSplitManifest(
        examples=tuple(LegalIRSplitExample.from_sample(item) for item in _corpus()[:3]),
        assignments={
            "train-a": TRAIN_SPLIT,
            "near-a": VALIDATION_SPLIT,
            "near-b": VALIDATION_SPLIT,
        },
        config_digest="unit",
    )
    assert require_training_split(clean, [{"sample_id": "train-a"}]).passed is True
    assert require_hparam_selection_split(clean, [{"sample_id": "near-a"}]).passed is True
    with pytest.raises(LegalIRSplitPolicyError):
        require_training_split(clean, [{"sample_id": "near-a"}])
    with pytest.raises(LegalIRSplitPolicyError):
        require_representation_promotion_split(clean, [{"sample_id": "near-a"}])
    with pytest.raises(LegalIRSplitPolicyError):
        require_codex_todo_projection_split(clean, [{"sample_id": "missing"}])


def _failed_guard() -> dict[str, object]:
    return {
        "blocked_operations": [
            TRAINING_OPERATION,
            HPARAM_SELECTION_OPERATION,
            REPRESENTATION_PROMOTION_OPERATION,
            CODEX_TODO_PROJECTION_OPERATION,
        ],
        "passed": False,
        "violations": [
            {
                "kind": "citation_cluster",
                "key": "usc:5:552",
                "protected_splits": [HOLDOUT_SPLIT],
                "sample_ids_by_split": {
                    TRAIN_SPLIT: ["train-copy"],
                    HOLDOUT_SPLIT: ["holdout-copy"],
                },
                "splits": [TRAIN_SPLIT, HOLDOUT_SPLIT],
            }
        ],
    }


def test_hparam_scheduler_refuses_baseline_with_failed_split_guard() -> None:
    baseline = SharedBaseline(
        baseline_id="baseline",
        revision="rev",
        dataset_digest="sha256:" + "1" * 64,
        metric_lineage_id="lineage",
        split_guard=_failed_guard(),
    )

    with pytest.raises(ValueError, match="LegalIR split guard blocks hparam selection"):
        LegalIRHParamScheduler(HParamSearchConfig(baseline=baseline))


def _promotion_payload() -> dict[str, object]:
    metrics = {
        "ir_cross_entropy_loss": 0.20,
        "ir_cosine_similarity": 0.80,
        "autoencoder_cross_entropy_loss": 0.30,
        "autoencoder_cosine_similarity": 0.70,
        "symbolic_validity_success_rate": 0.90,
        "hammer_proof_success_rate": 0.80,
        "reconstruction_success_rate": 0.70,
        "source_copy_penalty": 0.10,
    }
    family_metrics = {
        family: {
            "baseline": dict(metrics),
            "candidate": dict(metrics),
            "deltas": {metric: 0.0 for metric in LEGAL_IR_REPRESENTATION_METRICS},
            "guardrails_passed": True,
            "regressions": [],
        }
        for family in LEGAL_IR_VIEW_FAMILIES
    }
    return {
        "schema_version": "legal-ir-learned-guidance-promotion-v1",
        "status": "promoted",
        "promoted": True,
        "promotion_allowed": True,
        "promotion_id": "promotion",
        "block_reasons": [],
        "compiler_commit": "compiler",
        "learned_export_id": "export",
        "source_export_id": "export",
        "learned_export_sha256": "a" * 64,
        "learned_export": {
            "export_id": "export",
            "sample_memory_included": False,
            "schema_version": "legal-ir-stable-autoencoder-feature-export-v1",
            "sha256": "a" * 64,
        },
        "activation_state": {"active": True, "activation_allowed": True},
        "fixed_canary_binding": {
            "canary_id": "canary",
            "evidence_id": "evidence",
            "fixed_sample_set": True,
        },
        "rollback_metadata": {
            "activation_allowed": True,
            "activation_key": "promotion",
            "canary_evidence_id": "evidence",
            "rollback_id": "rollback",
            "schema_version": "legal-ir-learned-guidance-rollback-v1",
            "source_export_id": "export",
        },
        "canary_evidence": {
            "canary_id": "canary",
            "evidence_id": "evidence",
            "fixed_sample_set": True,
            "guardrails_passed": True,
            "missing_guardrail_evidence": [],
            "metric_regressions": [],
            "source_copy_regressions": [],
            "symbolic_validity_regressions": [],
            "family_metrics": family_metrics,
        },
        "todo_generation_productivity": {
            "baseline": {"seeded": 1, "deduped": 1},
            "candidate": {"seeded": 1, "deduped": 1},
        },
        "legal_ir_split_guard": _failed_guard(),
    }


def test_rollout_and_compiler_promotion_gates_consume_split_guard() -> None:
    summary = {
        "cycles": 2,
        "status": "succeeded",
        "latest_validation_ce_delta": 0.0,
        "latest_validation_cosine_delta": 0.0,
        "compiler_ir_validation_last_delta": {
            "compiler_ir_cross_entropy_loss": 0.0,
            "compiler_ir_cosine_similarity": 0.0,
        },
        "latest_compiler_ir_source_copy_reward_hack_penalty": 0.01,
        "latest_daemon_hammer_guidance": {
            "status": "completed",
            "runtime_failure_count": 0,
            "obligation_failure_count": 0,
            "hammer_metrics": {"hammer_backend_unavailable_ratio": 0.0},
        },
        "program_synthesis_seeded": 1,
        "program_synthesis_completed": 1,
        "latest_legal_ir_learned_guidance_promotion": _promotion_payload(),
    }

    result = rollout_gate(
        summary,
        RolloutGateConfig(
            require_representation_promotion=True,
            require_successful_representation_promotion=True,
        ),
    )

    assert result.accepted is False
    assert "representation_split_guard_blocked" in result.failures

    canary = {
        "applied_count": 2,
        "quality_gate": "pass",
        "legal_ir_split_guard": _failed_guard(),
    }
    gate = compiler_guidance_promotion_gate(canary)
    assert gate["promotion_allowed"] is False
    assert gate["promotion_block_reason"] == "split_guard_blocked"


def test_codex_projection_drops_guidance_that_crosses_protected_split() -> None:
    guidance = [
        {
            "backend_statuses": {"z3": "failed"},
            "failure_reason": "hammer_unproved",
            "goal_name": f"obl-{index}",
            "goal_statement_hash": f"statement-{index}",
            "guidance_id": f"obl-{index}",
            "legal_ir_split_guard": _failed_guard(),
            "legal_ir_view": "deontic.ir",
            "logic_family": "deontic",
            "metadata": {
                "citation": "5 U.S.C. 552",
                "sample_id": f"sample-{index}",
            },
            "obligation_id": f"obl-{index}",
            "proof_obligation_ids": [f"obl-{index}"],
            "proved": False,
            "rejection_reasons": ["hammer_unproved"],
            "schema_version": "legal-ir-hammer-guidance-v1",
            "source": "hammer_verified_guidance",
            "target_component": "deontic.ir",
            "trusted": False,
        }
        for index in range(2)
    ]

    assert hammer_failure_projection_todos(guidance) == []
    assert split_guard_blocks_operation(
        {"legal_ir_split_guard": _failed_guard()},
        CODEX_TODO_PROJECTION_OPERATION,
    )
