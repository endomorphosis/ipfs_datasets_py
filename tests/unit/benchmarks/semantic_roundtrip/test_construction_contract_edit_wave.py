"""PLAT-082 det. compiler edit wave: construction_contract.

Acceptance bar (same as PLAT-081):

* Wave cites packet CID(s) and residual catalog provenance.
* construction_contract forward/e2e loss ≤ prior residual-catalog baseline.
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
    project_legal_norms_with_diagnostics,
)
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRuleIR,
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
    / "construction_contract.json"
)
RESIDUAL_CATALOG_PATH = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "plateau_residual_catalog.json"
)
PRIOR_CONSTRUCTION_FORWARD = 0.141666664
PRIOR_CONSTRUCTION_E2E = 0.141666667


def _load_receipt() -> dict[str, object]:
    assert RECEIPT_PATH.is_file(), f"missing edit-wave receipt: {RECEIPT_PATH}"
    payload = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_construction_contract_forward_loss_clears_prior_residual() -> None:
    cases = {case.case_id: case for case in load_pilot_matrix_cases()}
    case = cases["construction_contract"]
    l1 = construct_baseline_l1(case)
    comparison = compare_semantic_ir(case.gold_ir, l1)
    forward = float(comparison["semantic_loss"])
    facets = compute_facet_residuals(case.case_id, case.gold_ir, l1)

    assert len(l1.rules) == len(case.gold_ir.rules) == 12
    assert forward <= PRIOR_CONSTRUCTION_FORWARD + 1e-9
    assert forward == pytest.approx(0.0, abs=1e-9)
    assert facets == ()
    # Gold IR is recovered exactly (order-normalized by CanonicalRuleIR).
    assert l1.to_dict() == case.gold_ir.to_dict()


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


def test_passive_dispute_resolution_and_qualifier_harvest() -> None:
    """Unit-level projection: passive 'shall be resolved' + local harvest."""

    vocabulary = AllowedAtomVocabulary(
        actors=(
            "contractor",
            "client",
            "either_party",
            "parties",
            "architect",
            "subcontractor",
        ),
        actions=(
            "complete",
            "ensure",
            "maintain",
            "pay",
            "withhold",
            "inspect",
            "use",
            "subcontract",
            "terminate",
            "resolve",
            "attempt",
            "disclose",
            "demolish",
        ),
        objects=(
            "all_construction_work",
            "work_compliance_with_city_building_codes_and_standards",
            "comprehensive_insurance_coverage",
            "contractor",
            "payment",
            "work",
            "materials_not_meeting_specification_requirements",
            "agreement",
            "work_in_progress",
            "disputes_through_binding_arbitration_in_springfield_illinois",
            "mediation",
            "project_blueprints",
            "performance_bond",
        ),
        qualifiers=(
            "by_december_31_2024",
            "within_30_days_of_completion",
            "work_does_not_meet_specifications",
            "at_any_time",
            "with_24_hours_advance_notice",
            "prior_written_approval",
            "with_30_days_written_notice",
            "upon_termination_notice",
            "before_arbitration",
            "within_14_days",
            "after_final_inspection",
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
                "actor": "All disputes",
                "action": (
                    "be resolved through binding arbitration in "
                    "Springfield, Illinois"
                ),
                "action_verb": "be",
                "action_object": (
                    "resolved through binding arbitration in "
                    "Springfield Illinois"
                ),
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": (
                    "All disputes shall be resolved through binding "
                    "arbitration in Springfield, Illinois"
                ),
            }
        ),
        _Norm(
            {
                "modality": "P",
                "norm_type": "permission",
                "actor": "Client",
                "action": (
                    "inspect the work at any time with 24 hours advance notice"
                ),
                "action_verb": "inspect",
                "action_object": (
                    "the work at any time with hours advance notice"
                ),
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": (
                    "The Client may inspect the work at any time with "
                    "24 hours advance notice"
                ),
            }
        ),
    ]
    ir, _diagnostics = project_legal_norms_with_diagnostics(
        norms, vocabulary, source_text="construction excerpt"
    )
    by_action = {rule.action: rule for rule in ir.rules}
    assert "resolve" in by_action
    resolve = by_action["resolve"]
    assert resolve.actor == "parties"
    assert (
        resolve.object
        == "disputes_through_binding_arbitration_in_springfield_illinois"
    )
    inspect = by_action["inspect"]
    assert inspect.object == "work"
    assert inspect.conditions == ("with_24_hours_advance_notice",)
    assert inspect.temporal == ("at_any_time",)


def test_edit_wave_receipt_cites_packet_and_forbids_optional_promotion() -> None:
    receipt = _load_receipt()
    catalog = json.loads(RESIDUAL_CATALOG_PATH.read_text(encoding="utf-8"))

    assert receipt["interface"] == "PlateauEditWaveReceipt@1"
    assert receipt["edit_wave_task_id"] == "PLAT-082"
    assert receipt["case_id"] == "construction_contract"
    assert receipt["board_namespace"] == "semantic-roundtrip-plateau-break-v1"
    assert receipt["baseline_arm_id"] == BASELINE_ARM_ID
    assert receipt["semantic_authority"] is False
    assert receipt["implementable"] is True

    packet_cids = receipt["packet_cids"]
    assert isinstance(packet_cids, list) and packet_cids
    assert all(isinstance(item, str) and item.startswith("baguqeera") for item in packet_cids)

    assert receipt["residual_catalog_cid"] == catalog["catalog_cid"]
    prior = receipt["prior_scores"]
    assert isinstance(prior, dict)
    assert float(prior["construction_contract_forward_loss"]) == pytest.approx(
        PRIOR_CONSTRUCTION_FORWARD, abs=1e-8
    )
    assert float(prior["construction_contract_end_to_end_loss"]) == pytest.approx(
        PRIOR_CONSTRUCTION_E2E, abs=1e-8
    )

    post = receipt["post_scores"]
    assert isinstance(post, dict)
    assert float(post["construction_contract_forward_loss"]) <= float(
        prior["construction_contract_forward_loss"]
    ) + 1e-9
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
    for change in changes:
        assert isinstance(change, dict)
        assert change.get("runtime") == "typed_deontic_projection"
        assert change.get("optional_runtime") is False

    predicted = receipt["predicted_files"]
    assert "benchmarks/semantic_roundtrip/constructors/typed_deontic.py" in predicted
    assert any("construction_contract.json" in str(path) for path in predicted)


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
        c
        for c in load_pilot_matrix_cases()
        if c.case_id == "construction_contract"
    )
    result = constructor.construct(
        ConstructorRequest(case.source_text, case.allowed_atom_vocabulary, {})
    )
    assert result.status is ComponentStatus.SUCCESS
    assert result.canonical_ir is not None
    assert not result.canonical_ir.is_empty
