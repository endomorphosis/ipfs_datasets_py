"""Executable contract for the frozen semantic round-trip composition protocol."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_PATH = (
    REPO_ROOT
    / "docs"
    / "benchmarks"
    / "semantic_roundtrip_composition_protocol.md"
)
INTERFACE = "SemanticRoundTripCompositionProtocol@1"


def _load_protocol() -> tuple[str, dict[str, Any]]:
    text = PROTOCOL_PATH.read_text(encoding="utf-8")
    matches = re.findall(r"```json\s*\n(.*?)\n```", text, flags=re.DOTALL)
    assert len(matches) == 1, "protocol must have one normative JSON block"
    contract = json.loads(matches[0])
    assert isinstance(contract, dict)
    return text, contract


def _primary_loss(
    scheduled: dict[str, list[float | None]],
    *,
    failure_loss: float,
) -> float:
    """Apply the frozen per-case-first aggregation to example records."""

    case_means = []
    for repeat_losses in scheduled.values():
        retained = [
            failure_loss if value is None else value
            for value in repeat_losses
        ]
        case_means.append(sum(retained) / len(retained))
    return sum(case_means) / len(case_means)


def test_protocol_is_frozen_and_defines_the_complete_crossed_experiment() -> None:
    text, protocol = _load_protocol()

    assert protocol["interface"] == INTERFACE
    assert protocol["status"] == "frozen"
    experiment = protocol["experiment"]
    assert experiment["path"] == [
        "t0_source",
        "constructor",
        "l1_canonical_ir",
        "realizer",
        "t1_reconstruction",
        "same_constructor",
        "l2_canonical_ir",
    ]
    assert (
        experiment["matrix"]
        == "all_preregistered_capability_compatible_constructor_realizer_pairs"
    )
    assert experiment["exclusion_timing"] == "before_case_execution"
    assert (
        experiment["exclusion_basis"]
        == "declared_interface_or_capability_only"
    )
    assert experiment["coordinate"] == [
        "case",
        "repeat",
        "constructor",
        "realizer",
    ]
    assert experiment["same_cases_and_repeat_count_for_all_eligible_pairs"]
    assert experiment["minimum_repeats_when_any_component_is_stochastic"] >= 3
    normalized_text = " ".join(text.split())
    assert (
        "A result that deviates from this protocol is a new experiment"
        in normalized_text
    )


def test_protocol_freezes_canonical_ir_and_weighted_semantic_score() -> None:
    _, protocol = _load_protocol()

    canonical = protocol["canonical_ir"]
    assert canonical["top_level_keys"] == ["rules"]
    assert canonical["modalities"] == ["O", "P", "F"]
    assert canonical["rule_fields"] == [
        "modality",
        "actor",
        "action",
        "object",
        "conditions",
        "exceptions",
        "temporal",
    ]
    assert canonical["list_fields"] == [
        "conditions",
        "exceptions",
        "temporal",
    ]

    score = protocol["semantic_score"]
    assert score["assignment"] == (
        "exact_maximum_weight_one_to_one_bipartite"
    )
    assert score["denominator"] == "max_reference_candidate_rule_count_or_one"
    assert score["scalar_facet_similarity"] == "exact_equality"
    assert score["list_facet_similarity"] == "set_jaccard"
    assert score["weights"] == {
        "modality": 0.25,
        "actor": 0.15,
        "action": 0.20,
        "object": 0.10,
        "conditions": 0.10,
        "exceptions": 0.10,
        "temporal": 0.10,
    }
    assert sum(score["weights"].values()) == 1.0


def test_realizer_boundary_excludes_source_gold_and_native_records() -> None:
    text, protocol = _load_protocol()

    boundary = protocol["information_boundary"]
    assert boundary["constructor_inputs"] == [
        "source_text",
        "allowed_atom_vocabulary",
        "frozen_constructor_config",
    ]
    assert boundary["realizer_inputs"] == [
        "l1_canonical_ir",
        "allowed_atom_vocabulary",
        "frozen_realizer_config",
    ]
    assert boundary["second_constructor_inputs"] == [
        "t1_reconstruction",
        "allowed_atom_vocabulary",
        "same_frozen_constructor_config",
    ]
    forbidden = set(boundary["realizer_forbidden"])
    assert {
        "source_text_or_excerpt",
        "gold_ir_or_gold_rule_count",
        "native_constructor_record_or_parse",
        "hidden_case_fields",
        "source_bearing_cache_or_metadata",
        "prior_reconstruction_or_outcome",
    } <= forbidden
    assert (
        boundary["only_allowed_gold_derived_execution_input"]
        == "frozen_allowed_atom_vocabulary"
    )
    assert boundary[
        "gold_ir_available_only_after_terminal_outcome_for_scoring_and_gates"
    ]
    assert boundary["fresh_second_constructor_call_namespace"]
    assert "same implementation identity, version" in text


def test_budgets_are_preregistered_and_never_derived_from_gold() -> None:
    _, protocol = _load_protocol()

    budgets = protocol["budgets"]
    assert budgets["frozen_before_execution"]
    assert budgets["gold_derived_budgets_forbidden"]
    assert set(budgets["forbidden_budget_inputs"]) == {
        "gold_ir",
        "gold_rule_count",
        "gold_content",
        "validator_output",
        "observed_semantic_outcome",
    }
    assert budgets["same_public_budget_rule_for_every_arm"]


def test_primary_loss_failures_and_per_case_first_aggregation_are_frozen() -> None:
    _, protocol = _load_protocol()

    loss = protocol["loss"]
    assert loss["primary"] == "one_minus_semantic_score_gold_ir_vs_l2"
    assert loss["forward_diagnostic"] == (
        "one_minus_semantic_score_gold_ir_vs_l1"
    )
    assert loss["cycle_diagnostic"] == (
        "one_minus_semantic_score_l1_vs_l2"
    )
    assert loss["terminal_failure_loss"] == 1.0
    assert set(loss["failure_outcomes"]) == {
        "timeout",
        "exception",
        "retry_exhausted",
        "post_schedule_capability_unavailable",
        "missing_output",
        "invalid_output",
        "empty_l1",
        "blank_t1",
        "empty_l2",
    }
    assert loss["successful_only_primary_summary_forbidden"]

    aggregation = protocol["aggregation"]
    assert aggregation == {
        "repeat_within_case": "arithmetic_mean_over_all_scheduled_repeats",
        "case_across_corpus": (
            "unweighted_arithmetic_mean_over_all_frozen_cases"
        ),
        "order": "per_case_first",
        "rule_count_weighting_forbidden": True,
        "failed_repeat_dropping_forbidden": True,
        "applies_to": [
            "primary",
            "forward_diagnostic",
            "cycle_diagnostic",
        ],
    }

    # This deliberately differs from a pooled successful-only mean and proves
    # that a failed repeat remains in its case's denominator at loss one.
    example = {
        "short_case": [0.0, None],
        "long_case": [0.2, 0.4],
    }
    assert _primary_loss(
        example, failure_loss=loss["terminal_failure_loss"]
    ) == 0.4


def test_selection_requires_coverage_polarity_and_copy_gates() -> None:
    _, protocol = _load_protocol()

    gates = protocol["gates"]
    assert gates["all_required_for_selection"]
    assert gates["full_coverage"] == {
        "scope": "every_scheduled_case_repeat_coordinate",
        "requires": [
            "terminal_success",
            "nonempty_schema_valid_l1",
            "nonblank_t1",
            "nonempty_schema_valid_l2",
        ],
    }
    assert gates["polarity_preservation"] == {
        "comparison": "gold_ir_vs_l2_maximum_weight_assignment",
        "requirement": "all_assigned_rule_modalities_equal",
    }
    assert gates["source_copy_exclusion"] == {
        "exact_normalized_copy_forbidden": True,
        "ngram_width_tokens": 8,
        "shared_source_ngram_precision_must_be_below": 0.8,
    }

    selection = protocol["selection"]
    assert selection == {
        "eligible_only_if_all_gates_pass": True,
        "criterion": "minimum_primary_loss",
        "exact_numeric_ties": "co_winners",
        "no_eligible_compositions": "select_none",
        "latency_resources_and_proofs_are_separate_axes": True,
    }


def test_model_envelope_and_stochastic_order_are_fair() -> None:
    _, protocol = _load_protocol()

    model = protocol["model_fairness"]
    assert model["same_physical_service_is_not_independent_evidence"]
    assert set(model["identical_frozen_fields"]) == {
        "endpoint_backend_identity",
        "model_tokenizer_identity",
        "context_size",
        "decoding_parameters",
        "per_repeat_seed_policy",
        "output_token_limit",
        "role_supported_grammar_schema_mode",
        "stop_conditions",
        "timeout",
        "retry_policy",
        "concurrency",
        "cache_mode",
    }
    assert model["prompt_templates_and_content_ids_frozen_before_execution"]

    order = protocol["order"]
    assert order["planned_before_outcomes"]
    assert order["algorithm"] == (
        "seeded_outcome_independent_counterbalanced_blocks"
    )
    assert order["scope"] == (
        "eligible_stochastic_compositions_within_case_repeat_blocks"
    )
    assert order["maximum_ordinal_position_count_imbalance"] == 1
    assert order["record_planned_and_observed_order"]
    assert order["shared_one_slot_model_execution"] == "serial"
    assert order["outcome_adaptive_scheduling_forbidden"]
    assert order["cross_coordinate_output_reuse_forbidden"]


def test_proof_validation_is_post_hoc_and_never_semantic_authority() -> None:
    text, protocol = _load_protocol()

    proof = protocol["proof_validation"]
    assert proof["phase"] == (
        "post_hoc_after_artifact_and_semantic_score_binding"
    )
    assert proof["role"] == "annotation_only"
    assert proof["nonvacuous_inputs_required"]
    assert proof["semantic_fidelity_authority"] is False
    assert (
        proof["may_change_semantic_score_loss_denominator_gates_or_selection"]
        is False
    )
    assert (
        proof["may_generate_repair_choose_rerank_retry_or_reject_candidate"]
        is False
    )
    assert proof["validator_failure_remains_visible"]
    assert "Empty/empty identity is vacuous" in text
    assert "does not prove that either IR is faithful to `T0` or gold IR" in text
