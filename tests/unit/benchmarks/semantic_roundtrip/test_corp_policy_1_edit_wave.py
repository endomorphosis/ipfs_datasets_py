"""PLAT-083 det. compiler edit wave: corp_policy_1.

Acceptance bar (same as PLAT-081):

* Wave cites packet CID(s) and residual catalog provenance.
* corp_policy_1 forward/e2e loss ≤ prior residual-catalog baseline.
* Mean forward loss across the five pilots is not worse than the sealed
  plateau mean (0.088333333).
* Production path stays typed_deontic + deterministic; no optional runtime
  promotion (spaCy / AE / Leanstral / SyMAI).
* Structural constraints remain enforceable on repair examples.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
    TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE,
    TypedDeonticCanonicalConstructor,
    _qualifier_fully_grounded,
    _token_stem_variants,
    project_legal_norms_with_diagnostics,
)
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    ComponentStatus,
    ConstructorRequest,
)
from benchmarks.semantic_roundtrip.metrics import compare_semantic_ir
from benchmarks.semantic_roundtrip.residual_catalog import (
    BASELINE_ARM_ID,
    BASELINE_E2E_MEAN,
    compute_facet_residuals,
    construct_baseline_l1,
    load_pilot_matrix_cases,
)
from benchmarks.semantic_roundtrip.structural_admission import (
    DECLARED_STRUCTURAL_CONSTRAINTS,
)


ROOT = Path(__file__).resolve().parents[4]
RECEIPT_PATH = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "plateau_edit_wave_receipts"
    / "corp_policy_1.json"
)
RESIDUAL_CATALOG_PATH = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "plateau_residual_catalog.json"
)
PRIOR_CORP_POLICY_FORWARD = 0.1
PRIOR_CORP_POLICY_E2E = 0.1


def _load_receipt() -> dict[str, object]:
    assert RECEIPT_PATH.is_file(), f"missing edit-wave receipt: {RECEIPT_PATH}"
    payload = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_corp_policy_1_forward_loss_clears_prior_residual() -> None:
    cases = {case.case_id: case for case in load_pilot_matrix_cases()}
    case = cases["corp_policy_1"]
    l1 = construct_baseline_l1(case)
    comparison = compare_semantic_ir(case.gold_ir, l1)
    forward = float(comparison["semantic_loss"])
    facets = compute_facet_residuals(case.case_id, case.gold_ir, l1)

    assert len(l1.rules) == len(case.gold_ir.rules) == 4
    assert forward <= PRIOR_CORP_POLICY_FORWARD + 1e-9
    assert forward == pytest.approx(0.0, abs=1e-9)
    assert facets == ()
    # Gold IR is recovered exactly (order-normalized by CanonicalRuleIR).
    assert l1.to_dict() == case.gold_ir.to_dict()
    by_action = {rule.action: rule for rule in l1.rules}
    assert by_action["complete"].temporal == ("annually",)
    assert by_action["accept"].conditions == ("gift_value_over_25",)
    assert by_action["report"].temporal == ("within_10_days_of_discovery",)
    assert by_action["maintain"].temporal == ("at_all_times",)


def test_mean_pilot_forward_not_worse_than_sealed_plateau() -> None:
    losses: list[float] = []
    for case in load_pilot_matrix_cases():
        l1 = construct_baseline_l1(case)
        losses.append(
            float(compare_semantic_ir(case.gold_ir, l1)["semantic_loss"])
        )
    mean_forward = sum(losses) / len(losses)
    assert mean_forward <= BASELINE_E2E_MEAN + 1e-9
    assert mean_forward < 0.05


def test_annual_frequency_stem_and_local_qualifier_harvest() -> None:
    """Unit-level projection: 'annual' evidence grounds atom 'annually'."""

    assert "annual" in _token_stem_variants("annually")
    # Short -ly forms must not collapse (daily → dai would be unusable).
    assert _token_stem_variants("daily") == frozenset({"daily"})
    assert _token_stem_variants("only") == frozenset({"only"})
    evidence = (
        "Managers are required to complete annual ethics training "
        "and certifications"
    )
    assert _qualifier_fully_grounded(evidence, "annually")

    vocabulary = AllowedAtomVocabulary(
        actors=("employees", "managers", "staff"),
        actions=("report", "complete", "accept", "maintain"),
        objects=(
            "conflicts_of_interest_to_ethics_committee",
            "ethics_training_and_certifications",
            "gifts_from_clients_or_vendors",
            "proprietary_information_and_customer_data",
        ),
        qualifiers=(
            "annually",
            "at_all_times",
            "gift_value_over_25",
            "gift_value_over_50",
            "within_10_days_of_discovery",
            "within_5_business_days",
        ),
    )

    class _Norm:
        def __init__(self, data: dict[str, object]) -> None:
            self._data = data

        def to_dict(self) -> dict[str, object]:
            return dict(self._data)

    norms = [
        _Norm(
            {
                "modality": "O",
                "norm_type": "obligation",
                "actor": "Managers",
                "action": "complete annual ethics training and certifications",
                "action_verb": "complete",
                "action_object": "annual ethics training and certifications",
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": (
                    "Managers are required to complete annual ethics "
                    "training and certifications"
                ),
            }
        ),
        _Norm(
            {
                "modality": "F",
                "norm_type": "prohibition",
                "actor": "Employees",
                "action": (
                    "accept gifts valued over $25 from clients or vendors"
                ),
                "action_verb": "accept",
                "action_object": "gifts valued over from clients or vendors",
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": (
                    "Employees cannot accept gifts valued over $25 from "
                    "clients or vendors"
                ),
            }
        ),
    ]
    ir, _diagnostics = project_legal_norms_with_diagnostics(
        norms, vocabulary, source_text="corp policy excerpt"
    )
    by_action = {rule.action: rule for rule in ir.rules}
    complete = by_action["complete"]
    assert complete.actor == "managers"
    assert complete.object == "ethics_training_and_certifications"
    assert complete.temporal == ("annually",)
    accept = by_action["accept"]
    assert accept.conditions == ("gift_value_over_25",)
    assert accept.temporal == ()


def test_edit_wave_receipt_cites_packet_and_forbids_optional_promotion() -> None:
    receipt = _load_receipt()
    catalog = json.loads(RESIDUAL_CATALOG_PATH.read_text(encoding="utf-8"))

    assert receipt["interface"] == "PlateauEditWaveReceipt@1"
    assert receipt["edit_wave_task_id"] == "PLAT-083"
    assert receipt["case_id"] == "corp_policy_1"
    assert receipt["board_namespace"] == "semantic-roundtrip-plateau-break-v1"
    assert receipt["baseline_arm_id"] == BASELINE_ARM_ID
    assert receipt["semantic_authority"] is False
    assert receipt["implementable"] is True
    assert receipt["parallel_lane"] == "plat-det-corp-policy"
    assert receipt["evidence_subset"] == "edit-wave corp_policy_1"

    packet_cids = receipt["packet_cids"]
    assert isinstance(packet_cids, list) and packet_cids
    assert all(
        isinstance(item, str) and item.startswith("baguqeera")
        for item in packet_cids
    )
    packet_ids = receipt["packet_ids"]
    assert isinstance(packet_ids, list) and packet_ids
    assert any("corp-policy" in str(item) for item in packet_ids)

    assert receipt["residual_catalog_cid"] == catalog["catalog_cid"]
    prior = receipt["prior_scores"]
    assert isinstance(prior, dict)
    assert float(prior["corp_policy_1_forward_loss"]) == pytest.approx(
        PRIOR_CORP_POLICY_FORWARD, abs=1e-8
    )
    assert float(prior["corp_policy_1_end_to_end_loss"]) == pytest.approx(
        PRIOR_CORP_POLICY_E2E, abs=1e-8
    )

    post = receipt["post_scores"]
    assert isinstance(post, dict)
    assert float(post["corp_policy_1_forward_loss"]) <= float(
        prior["corp_policy_1_forward_loss"]
    ) + 1e-9
    assert float(post["corp_policy_1_forward_loss"]) == pytest.approx(
        0.0, abs=1e-9
    )
    assert float(post["mean_pilot_forward_loss"]) <= BASELINE_E2E_MEAN + 1e-9

    assert receipt["optional_runtimes_promoted"] == []
    assert receipt["production_constructor_identity"] == (
        TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE
    )
    assert receipt["production_runtime_unchanged"] is True
    assert "modal_spacy" not in str(receipt.get("production_composition", ""))
    assert "leanstral" not in str(receipt.get("production_composition", "")).lower()

    changes = receipt["deterministic_changes"]
    assert isinstance(changes, list) and changes
    change_ids = {change.get("id") for change in changes if isinstance(change, dict)}
    assert "ly_adverb_frequency_stem_variants" in change_ids
    for change in changes:
        assert isinstance(change, dict)
        assert change.get("runtime") == "typed_deontic_projection"
        assert change.get("optional_runtime") is False

    residual_paths = receipt["residual_field_paths"]
    assert isinstance(residual_paths, list)
    assert "rules[2].temporal" in residual_paths
    assert "rules[0].conditions" in residual_paths

    predicted = receipt["predicted_files"]
    assert "benchmarks/semantic_roundtrip/constructors/typed_deontic.py" in predicted
    assert any("corp_policy_1.json" in str(path) for path in predicted)


def test_structural_constraint_names_still_declared() -> None:
    # Repair-path structural gates remain part of the plateau contract even
    # though this wave is a pure constructor projection improvement.
    declared = set(DECLARED_STRUCTURAL_CONSTRAINTS)
    assert "non_vacuous_candidate" in declared
    assert "rule_cardinality_preserved" in declared
    assert "untriggered_projection_preserved" in declared


def test_constructor_identity_unchanged_and_no_llm_dependency() -> None:
    constructor = TypedDeonticCanonicalConstructor()
    assert constructor.identity == TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE
    # Module surface stays deterministic: no teacher runtime hooks on construct.
    source = (
        ROOT / "benchmarks/semantic_roundtrip/constructors/typed_deontic.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    for banned in (
        "openai",
        "anthropic",
        "leanstral",
        "symai",
        "modal_spacy",
        "autoencoder_guided",
    ):
        assert banned not in lowered, banned
    case = next(
        c for c in load_pilot_matrix_cases() if c.case_id == "corp_policy_1"
    )
    result = constructor.construct(
        ConstructorRequest(case.source_text, case.allowed_atom_vocabulary, {})
    )
    assert result.status is ComponentStatus.SUCCESS
    assert result.canonical_ir is not None
    assert not result.canonical_ir.is_empty
    assert any(
        rule.temporal == ("annually",) for rule in result.canonical_ir.rules
    )
