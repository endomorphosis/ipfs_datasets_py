"""Tests for learned-to-deterministic LegalIR rule distillation."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_rule_distillation import (
    LEGAL_IR_RULE_CANDIDATE_SCHEMA_VERSION,
    LEGAL_IR_RULE_DISTILLATION_SCHEMA_VERSION,
    LEGAL_IR_RULE_DISTILLATION_TODO_SCHEMA_VERSION,
    LegalIRRuleDistillationConfig,
    distill_legal_ir_rule_candidates,
    legal_ir_rule_distillation,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_view_contracts import (
    legal_ir_view_contract,
)


def _patterns(*, family: str = "deontic") -> list[dict]:
    return [
        {
            "confidence": 0.92,
            "family": family,
            "feature": f"modal-family:{family}",
            "pattern_id": f"{family}-family",
            "pattern_kind": "family",
            "stable": True,
            "support_count": 12,
            "support_ratio": 0.8,
        },
        {
            "confidence": 0.88,
            "family": family,
            "feature": f"semantic-slot:modal-operator:{family}:obligation",
            "pattern_id": f"{family}-slot",
            "pattern_kind": "semantic_slot",
            "stable": True,
            "support_count": 11,
            "support_ratio": 0.75,
        },
        {
            "confidence": 0.84,
            "family": family,
            "feature": f"proof-head:trusted-outcome:{family}:proved",
            "pattern_id": f"{family}-proof-head",
            "pattern_kind": "proof_head",
            "stable": True,
            "support_count": 10,
            "support_ratio": 0.7,
        },
        {
            "confidence": 0.9,
            "family": family,
            "feature": f"legal-ir-view:{family}:operator-preserved",
            "pattern_id": f"{family}-view",
            "pattern_kind": "legal_ir_view",
            "stable": True,
            "support_count": 12,
            "support_ratio": 0.8,
        },
    ]


def _counterfactuals(family: str = "deontic") -> dict:
    return {
        family: [
            {
                "case_id": f"{family}-counterfactual",
                "expected": "candidate no longer matches",
                "family": family,
                "held_out": True,
                "intervention": "invert the categorical modal operator",
                "observed": "candidate no longer matches",
                "passed": True,
            }
        ]
    }


def _mutations(family: str = "deontic") -> dict:
    return {
        family: [
            {
                "case_id": f"{family}-mutation",
                "detected": True,
                "family": family,
                "mutation": "invert_modality",
                "observed_detection": "rule rejected mutated structure",
                "verified": True,
            }
        ]
    }


def _attribution(
    family: str = "deontic", *, improvement: float = 0.04
) -> dict:
    return {
        family: {
            "attribution_id": f"{family}-heldout-attribution",
            "compiler_metric": "compiler_ir_cosine_similarity",
            "confidence": 0.9,
            "fixed_sample_set": True,
            "heldout_evaluated": True,
            "heldout_sample_count": 7,
            "holdout_id": "frozen-holdout-2026-07",
            "holdout_isolated": True,
            "predicted_compiler_improvement": improvement,
            "source_copy_guard_passed": True,
        }
    }


def test_distills_all_stable_pattern_kinds_into_deterministic_bounded_rule() -> None:
    first = distill_legal_ir_rule_candidates(
        _patterns(),
        family_attribution=_attribution(),
        counterfactuals=_counterfactuals(),
        mutation_evidence=_mutations(),
        previous_distillation_id="lir-rule-distillation-previous",
    )
    second = distill_legal_ir_rule_candidates(
        list(reversed(_patterns())),
        family_attribution=_attribution(),
        counterfactuals=_counterfactuals(),
        mutation_evidence=_mutations(),
        previous_distillation_id="lir-rule-distillation-previous",
    )

    assert first.status == "distilled"
    assert first.bounded is True
    assert first.distillation_id == second.distillation_id
    assert first.candidates[0].candidate_id == second.candidates[0].candidate_id
    assert len(first.candidates) == 1
    assert len(first.codex_todos) == 1

    candidate = first.candidates[0]
    payload = candidate.to_dict()
    assert payload["schema_version"] == LEGAL_IR_RULE_CANDIDATE_SCHEMA_VERSION
    assert payload["target_kind"] == "compiler"
    assert payload["contract_id"] == "legal-ir-view/deontic/v1"
    assert {item["pattern_kind"] for item in payload["patterns"]} == {
        "family",
        "semantic_slot",
        "proof_head",
        "legal_ir_view",
    }
    assert payload["deterministic_rule"]["deterministic"] is True
    assert payload["deterministic_rule"]["on_no_match"] == "no_op"
    assert payload["counterfactuals"][0]["passed"] is True
    assert payload["mutation_evidence"][0]["passed"] is True
    assert payload["owned_paths"]
    assert all(path.startswith("ipfs_datasets_py/") for path in payload["owned_paths"])
    assert payload["rollback_metadata"]["restore_mode"] == (
        "candidate_registry_snapshot"
    )
    assert payload["rollback_metadata"]["previous_distillation_id"] == (
        "lir-rule-distillation-previous"
    )

    todo = first.codex_todos[0].to_dict()
    assert todo["schema_version"] == LEGAL_IR_RULE_DISTILLATION_TODO_SCHEMA_VERSION
    assert todo["candidate_id"] == candidate.candidate_id
    assert todo["owned_paths"] == payload["owned_paths"]
    assert todo["evidence"]["heldout_compiler_improvement_predicted"] is True
    assert todo["metadata"]["allowed_paths"] == todo["owned_paths"]


def test_decompiler_patterns_resolve_only_to_decompiler_owned_paths() -> None:
    result = distill_legal_ir_rule_candidates(
        _patterns(family="decompiler"),
        family_attribution=_attribution("decompiler"),
        counterfactuals=_counterfactuals("decompiler"),
        mutation_evidence=_mutations("decompiler"),
    )

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.target_kind == "decompiler"
    assert candidate.contract_id == "legal-ir-view/decompiler/v1"
    assert candidate.target_component == "modal.ir_decompiler"
    assert candidate.owned_paths
    contract = legal_ir_view_contract("modal.ir_decompiler")
    canonical_paths = {
        path for lane in contract.repair_lanes for path in lane.allowed_paths
    }
    assert set(candidate.owned_paths) <= canonical_paths


def test_rejects_sample_memory_source_copy_and_unowned_paths_without_leakage() -> None:
    unsafe = [
        {
            **_patterns()[0],
            "feature": "sample-memory:secret-sample",
            "pattern_id": "sample-memory",
        },
        {
            **_patterns()[1],
            "feature": "source-copy:verbatim-private-text",
            "pattern_id": "source-copy",
        },
        {
            **_patterns()[2],
            "owned_paths": ["outside/repository_owner.py"],
            "pattern_id": "unowned-path",
        },
        {
            **_patterns()[3],
            "pattern_id": "flagged-memory",
            "sample_memory_used": True,
        },
    ]

    result = distill_legal_ir_rule_candidates(
        unsafe,
        family_attribution=_attribution(),
        counterfactuals=_counterfactuals(),
        mutation_evidence=_mutations(),
    )

    assert result.candidates == ()
    reasons = {item["reason"] for item in result.rejected_patterns}
    assert "sample_memory_or_source_copy_feature" in reasons
    assert "path_outside_canonical_ownership" in reasons
    serialized = json.dumps(result.to_dict(), sort_keys=True)
    assert "secret-sample" not in serialized
    assert "verbatim-private-text" not in serialized

    unsafe_export = distill_legal_ir_rule_candidates(
        {
            "export_id": "unsafe-export",
            "sample_memory_included": True,
            "stable_features": _patterns(),
        },
        counterfactuals=_counterfactuals(),
        mutation_evidence=_mutations(),
    )
    assert unsafe_export.candidates == ()
    assert {item["reason"] for item in unsafe_export.rejected_patterns} == {
        "sample_memory_or_source_copy_feature"
    }


def test_codex_todo_requires_positive_per_family_heldout_attribution() -> None:
    common = {
        "counterfactuals": _counterfactuals(),
        "mutation_evidence": _mutations(),
    }
    missing = distill_legal_ir_rule_candidates(_patterns(), **common)
    aggregate = distill_legal_ir_rule_candidates(
        _patterns(),
        family_attribution={
            "compiler_metric": "compiler_ir_cosine_similarity",
            "heldout_evaluated": True,
            "heldout_sample_count": 8,
            "predicted_improvement": 0.5,
        },
        **common,
    )
    regressing = distill_legal_ir_rule_candidates(
        _patterns(), family_attribution=_attribution(improvement=-0.01), **common
    )
    improving = distill_legal_ir_rule_candidates(
        _patterns(), family_attribution=_attribution(improvement=0.01), **common
    )

    for result in (missing, aggregate, regressing):
        assert len(result.candidates) == 1
        assert result.codex_todos == ()
        assert "no_per_family_heldout_compiler_improvement" in result.block_reasons
    assert len(improving.codex_todos) == 1


def test_accepts_promoted_guidance_records_that_retain_ratio_only_support() -> None:
    promoted_guidance = {
        "promotion_id": "lir-guidance-promotion-test",
        "records": [
            {
                "confidence": 0.91,
                "contract_id": "legal-ir-view/deontic/v1",
                "guidance_id": "lir-guidance-test",
                "guidance_kind": "compiler",
                "repair_lane_records": [
                    {
                        "allowed_paths": [
                            "ipfs_datasets_py/logic/deontic/ir.py",
                            "ipfs_datasets_py/logic/deontic/converter.py",
                        ],
                        "lane_id": "deontic.norm_semantics",
                    }
                ],
                "stable_features": [
                    {
                        "feature": "compiler-contract:force-polarity:obligation",
                        "feature_group": "compiler_contract",
                        "feature_id": "ratio-only-feature",
                        "stable": True,
                        "support_ratio": 0.875,
                        "weight": 0.9,
                    }
                ],
                "view_family": "deontic",
            }
        ],
    }

    result = distill_legal_ir_rule_candidates(
        promoted_guidance,
        family_attributions=_attribution(),
        counterfactual_evidence=_counterfactuals(),
        mutation_evidence=_mutations(),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].support_count == result.config.min_support
    assert result.candidates[0].support_ratio == 0.875
    assert len(result.codex_todos) == 1


def test_missing_or_failed_counterfactual_and_mutation_evidence_blocks_rules() -> None:
    failed_counterfactual = _counterfactuals()
    failed_counterfactual["deontic"][0]["passed"] = False
    failed_mutation = _mutations()
    failed_mutation["deontic"][0]["detected"] = False

    no_counterfactual = distill_legal_ir_rule_candidates(
        _patterns(), mutation_evidence=_mutations()
    )
    bad_counterfactual = distill_legal_ir_rule_candidates(
        _patterns(),
        counterfactuals=failed_counterfactual,
        mutation_evidence=_mutations(),
    )
    bad_mutation = distill_legal_ir_rule_candidates(
        _patterns(),
        counterfactuals=_counterfactuals(),
        mutation_evidence=failed_mutation,
    )

    assert {item["reason"] for item in no_counterfactual.rejected_patterns} == {
        "counterfactual_evidence_missing"
    }
    assert {item["reason"] for item in bad_counterfactual.rejected_patterns} == {
        "counterfactual_evidence_failed"
    }
    assert {item["reason"] for item in bad_mutation.rejected_patterns} == {
        "mutation_evidence_failed"
    }


def test_limits_are_hard_bounded_and_dictionary_api_is_json_ready() -> None:
    patterns = [
        {
            **_patterns()[0],
            "feature": f"modal-family:deontic:variant-{index}",
            "pattern_id": f"pattern-{index}",
        }
        for index in range(20)
    ]
    payload = legal_ir_rule_distillation(
        patterns,
        family_attribution=_attribution(),
        counterfactuals={
            "deontic": [
                {
                    "case_id": f"cf-{index}",
                    "expected": "not matched",
                    "intervention": f"change categorical slot {index}",
                    "observed": "not matched",
                    "passed": True,
                }
                for index in range(20)
            ]
        },
        mutation_evidence={
            "deontic": [
                {"case_id": f"mutation-{index}", "killed": True, "mutation": f"m{index}"}
                for index in range(20)
            ]
        },
        config=LegalIRRuleDistillationConfig(
            max_patterns_per_candidate=3,
            max_counterfactuals_per_candidate=2,
            max_mutations_per_candidate=2,
        ),
    )

    assert payload["schema_version"] == LEGAL_IR_RULE_DISTILLATION_SCHEMA_VERSION
    assert payload["bounded"] is True
    assert len(payload["rule_candidates"][0]["patterns"]) == 3
    assert len(payload["rule_candidates"][0]["counterfactuals"]) == 2
    assert len(payload["rule_candidates"][0]["mutation_evidence"]) == 2
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
