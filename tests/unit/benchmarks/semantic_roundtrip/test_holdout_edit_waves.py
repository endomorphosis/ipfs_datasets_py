"""PLAT2-050 det. compiler edit waves for holdout residuals.

Acceptance bar:

* Edit-wave receipts exist for every sealed holdout case with non-zero residual.
* Each wave cites packet CID(s) and residual catalog provenance.
* Non-zero holdout activation residuals clear (forward loss 0.0).
* Mean forward loss across the five pilots remains 0.0 (non-regression).
* Production path stays typed_deontic + deterministic; no optional runtime
  promotion (spaCy / AE / Leanstral / SyMAI).
* Structural constraints remain declared for the repair path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
    TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE,
    TypedDeonticCanonicalConstructor,
    _map_structured_qualifiers_scored,
    _resolve_conflicting_modality_rules,
    _structured_clause_match_text,
    project_legal_norms_with_diagnostics,
)
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorRequest,
)
from benchmarks.semantic_roundtrip.matrix import load_matrix_cases
from benchmarks.semantic_roundtrip.metrics import compare_semantic_ir
from benchmarks.semantic_roundtrip.residual_catalog import (
    BASELINE_ARM_ID,
    BASELINE_E2E_MEAN,
    compute_facet_residuals,
    construct_baseline_l1,
    load_holdout_residual_catalog,
    load_pilot_matrix_cases,
)
from benchmarks.semantic_roundtrip.structural_admission import (
    DECLARED_STRUCTURAL_CONSTRAINTS,
)


ROOT = Path(__file__).resolve().parents[4]
RECEIPT_DIR = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "holdout_edit_wave_receipts"
)
RESIDUAL_CATALOG_PATH = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "holdout_residual_catalog.json"
)
HOLDOUT_CASES_PATH = (
    ROOT / "tests" / "fixtures" / "semantic_roundtrip" / "holdout_cases.json"
)

# Sealed holdout residual-catalog priors (PLAT2-010 activation subset).
PRIOR_BY_CASE = {
    "low_confidence_object": {
        "forward": 0.1,
        "e2e": 0.1,
        "residual_count": 1,
        "field_paths": ("rules[0].conditions",),
    },
    "contradictory_modality": {
        "forward": 0.5,
        "e2e": 0.5,
        "residual_count": 1,
        "field_paths": ("l1.rules[1]",),
    },
}

NONZERO_HOLDOUT_CASES = tuple(PRIOR_BY_CASE.keys())


def _load_receipt(case_id: str) -> dict[str, object]:
    path = RECEIPT_DIR / f"{case_id}.json"
    assert path.is_file(), f"missing holdout edit-wave receipt: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _holdout_cases() -> dict[str, object]:
    return {case.case_id: case for case in load_matrix_cases(HOLDOUT_CASES_PATH)}


def test_receipts_exist_for_every_sealed_nonzero_holdout_case() -> None:
    catalog = load_holdout_residual_catalog(
        RESIDUAL_CATALOG_PATH, repo_root=ROOT
    )
    nonzero = list(catalog["nonzero_case_ids"])  # type: ignore[arg-type]
    assert set(nonzero) == set(NONZERO_HOLDOUT_CASES)
    for case_id in nonzero:
        receipt = _load_receipt(case_id)
        assert receipt["case_id"] == case_id
        assert receipt["edit_wave_task_id"] == "PLAT2-050"
        assert receipt["interface"] == "PlateauEditWaveReceipt@1"


@pytest.mark.parametrize("case_id", NONZERO_HOLDOUT_CASES)
def test_holdout_case_forward_loss_clears_prior_residual(case_id: str) -> None:
    cases = _holdout_cases()
    case = cases[case_id]
    l1 = construct_baseline_l1(case)
    comparison = compare_semantic_ir(case.gold_ir, l1)
    forward = float(comparison["semantic_loss"])
    facets = compute_facet_residuals(case.case_id, case.gold_ir, l1)
    prior = PRIOR_BY_CASE[case_id]

    assert forward <= prior["forward"] + 1e-9
    assert forward == pytest.approx(0.0, abs=1e-9)
    assert facets == ()
    assert l1.to_dict() == case.gold_ir.to_dict()


def test_low_confidence_object_conditions_empty_object_records() -> None:
    case = _holdout_cases()["low_confidence_object"]
    l1 = construct_baseline_l1(case)
    assert len(l1.rules) == 1
    rule = l1.rules[0]
    assert rule.modality == "O"
    assert rule.actor == "controller"
    assert rule.action == "retain"
    assert rule.object == "records"
    assert rule.conditions == ()
    assert rule.exceptions == ()
    assert rule.temporal == ()


def test_contradictory_modality_single_prohibition_with_exception() -> None:
    case = _holdout_cases()["contradictory_modality"]
    l1 = construct_baseline_l1(case)
    assert len(l1.rules) == 1
    rule = l1.rules[0]
    assert rule.modality == "F"
    assert rule.actor == "processor"
    assert rule.action == "disclose"
    assert rule.object == "personal_data"
    assert rule.exceptions == ("unless_required_by_law",)
    assert rule.conditions == ()


def test_mean_pilot_forward_remains_zero() -> None:
    losses: list[float] = []
    for case in load_pilot_matrix_cases():
        l1 = construct_baseline_l1(case)
        losses.append(
            float(compare_semantic_ir(case.gold_ir, l1)["semantic_loss"])
        )
    mean_forward = sum(losses) / len(losses)
    assert mean_forward <= BASELINE_E2E_MEAN + 1e-9
    assert mean_forward == pytest.approx(0.0, abs=1e-9)
    assert all(loss == pytest.approx(0.0, abs=1e-9) for loss in losses)


def test_structured_condition_mapping_rejects_bare_requested() -> None:
    """Bare 'requested' must not promote if_requested without content marker."""

    vocab = AllowedAtomVocabulary(
        actors=("controller",),
        actions=("retain",),
        objects=("records",),
        qualifiers=("if_requested", "unless_required_by_law"),
    )
    clause = {
        "type": "condition",
        "clause_type": "if",
        "raw_text": "requested",
        "normalized_text": "requested",
        "value": "requested",
    }
    # Content-only match text omits structural clause_type.
    assert _structured_clause_match_text(clause, facet="conditions") == "requested"
    atoms, _conf = _map_structured_qualifiers_scored(
        (clause,), vocab.qualifiers, facet="conditions"
    )
    assert atoms == ()

    # Full content with marker still grounds.
    full = {
        "type": "condition",
        "clause_type": "if",
        "raw_text": "if requested",
        "normalized_text": "if requested",
        "value": "if requested",
    }
    atoms_full, _ = _map_structured_qualifiers_scored(
        (full,), vocab.qualifiers, facet="conditions"
    )
    assert atoms_full == ("if_requested",)


def test_exception_clause_type_prefixes_unless_atoms() -> None:
    vocab = AllowedAtomVocabulary(
        actors=("processor",),
        actions=("disclose",),
        objects=("personal_data",),
        qualifiers=("unless_required_by_law",),
    )
    clause = {
        "type": "exception",
        "clause_type": "unless",
        "raw_text": "required by law",
        "normalized_text": "required by law",
        "value": "required by law",
    }
    text = _structured_clause_match_text(clause, facet="exceptions")
    assert "unless" in text.lower()
    atoms, _ = _map_structured_qualifiers_scored(
        (clause,), vocab.qualifiers, facet="exceptions"
    )
    assert atoms == ("unless_required_by_law",)


def test_resolve_conflicting_modality_prefers_prohibition() -> None:
    obligation = CanonicalRule(
        modality="O",
        actor="processor",
        action="disclose",
        object="personal_data",
        exceptions=("unless_required_by_law",),
    )
    prohibition = CanonicalRule(
        modality="F",
        actor="processor",
        action="disclose",
        object="personal_data",
        exceptions=("unless_required_by_law",),
    )
    resolved = _resolve_conflicting_modality_rules((obligation, prohibition))
    assert len(resolved) == 1
    assert resolved[0].modality == "F"
    assert resolved[0].exceptions == ("unless_required_by_law",)

    # Same-modality pairs are not collapsed.
    same = _resolve_conflicting_modality_rules((obligation, obligation))
    assert len(same) == 2


def test_projection_collapses_of_dual_norms_unit() -> None:
    vocabulary = AllowedAtomVocabulary(
        actors=("controller", "processor"),
        actions=("delete", "retain", "disclose"),
        objects=("records", "personal_data"),
        qualifiers=(
            "after_30_days",
            "if_requested",
            "unless_required_by_law",
            "within_72_hours",
        ),
    )

    class _Norm:
        def __init__(self, data: dict[str, object]) -> None:
            self._data = data

        def to_dict(self) -> dict[str, object]:
            return dict(self._data)

    source = (
        "The processor must disclose personal data and shall not "
        "disclose personal data unless required by law."
    )
    norms = [
        _Norm(
            {
                "modality": "O",
                "norm_type": "obligation",
                "actor": "processor",
                "action": "disclose personal data",
                "action_verb": "disclose",
                "action_object": "personal data",
                "conditions": [],
                "exceptions": [
                    {
                        "type": "exception",
                        "clause_type": "unless",
                        "raw_text": "required by law",
                        "normalized_text": "required by law",
                        "value": "required by law",
                    }
                ],
                "temporal_constraints": [],
                "source_text": source,
                "support_text": "The processor must disclose personal data",
            }
        ),
        _Norm(
            {
                "modality": "F",
                "norm_type": "prohibition",
                "actor": "processor",
                "action": "disclose personal data",
                "action_verb": "disclose",
                "action_object": "personal data",
                "conditions": [],
                "exceptions": [
                    {
                        "type": "exception",
                        "clause_type": "unless",
                        "raw_text": "required by law",
                        "normalized_text": "required by law",
                        "value": "required by law",
                    }
                ],
                "temporal_constraints": [],
                "source_text": source,
                "support_text": "and shall not disclose personal data",
            }
        ),
    ]
    ir, _diagnostics = project_legal_norms_with_diagnostics(
        norms, vocabulary, source_text=source
    )
    assert len(ir.rules) == 1
    rule = ir.rules[0]
    assert rule.modality == "F"
    assert rule.exceptions == ("unless_required_by_law",)


@pytest.mark.parametrize("case_id", NONZERO_HOLDOUT_CASES)
def test_edit_wave_receipt_cites_packet_and_forbids_optional_promotion(
    case_id: str,
) -> None:
    receipt = _load_receipt(case_id)
    catalog = json.loads(RESIDUAL_CATALOG_PATH.read_text(encoding="utf-8"))
    prior_meta = PRIOR_BY_CASE[case_id]

    assert receipt["interface"] == "PlateauEditWaveReceipt@1"
    assert receipt["edit_wave_task_id"] == "PLAT2-050"
    assert receipt["case_id"] == case_id
    assert receipt["board_namespace"] == "semantic-roundtrip-plateau-holdout-v1"
    assert receipt["baseline_arm_id"] == BASELINE_ARM_ID
    assert receipt["semantic_authority"] is False
    assert receipt["implementable"] is True
    assert receipt["parallel_lane"] == "plat2-det-edits"
    assert receipt["evidence_subset"] == f"holdout edit-wave {case_id}"

    packet_cids = receipt["packet_cids"]
    assert isinstance(packet_cids, list) and packet_cids
    assert all(
        isinstance(item, str) and item.startswith("baguqeera")
        for item in packet_cids
    )
    packet_ids = receipt["packet_ids"]
    assert isinstance(packet_ids, list) and packet_ids
    assert any("plat2-050" in str(item) for item in packet_ids)

    assert receipt["residual_catalog_cid"] == catalog["catalog_cid"]
    prior = receipt["prior_scores"]
    assert isinstance(prior, dict)
    assert float(prior[f"{case_id}_forward_loss"]) == pytest.approx(
        prior_meta["forward"], abs=1e-8
    )
    assert float(prior[f"{case_id}_end_to_end_loss"]) == pytest.approx(
        prior_meta["e2e"], abs=1e-8
    )

    post = receipt["post_scores"]
    assert isinstance(post, dict)
    assert float(post[f"{case_id}_forward_loss"]) <= float(
        prior[f"{case_id}_forward_loss"]
    ) + 1e-9
    assert float(post[f"{case_id}_forward_loss"]) == pytest.approx(
        0.0, abs=1e-9
    )
    assert float(post["mean_pilot_forward_loss"]) == pytest.approx(
        0.0, abs=1e-9
    )

    assert receipt["optional_runtimes_promoted"] == []
    assert receipt["production_constructor_identity"] == (
        TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE
    )
    assert receipt["production_runtime_unchanged"] is True
    assert "modal_spacy" not in str(receipt.get("production_composition", ""))
    assert "leanstral" not in str(
        receipt.get("production_composition", "")
    ).lower()

    changes = receipt["deterministic_changes"]
    assert isinstance(changes, list) and changes
    for change in changes:
        assert isinstance(change, dict)
        assert change.get("runtime") == "typed_deontic_projection"
        assert change.get("optional_runtime") is False

    predicted = receipt["predicted_files"]
    assert "benchmarks/semantic_roundtrip/constructors/typed_deontic.py" in predicted
    assert any(case_id in str(path) for path in predicted)


def test_structural_constraint_names_still_declared() -> None:
    declared = set(DECLARED_STRUCTURAL_CONSTRAINTS)
    assert "non_vacuous_candidate" in declared
    assert "rule_cardinality_preserved" in declared
    assert "untriggered_projection_preserved" in declared


def test_constructor_identity_unchanged_and_no_llm_dependency() -> None:
    constructor = TypedDeonticCanonicalConstructor()
    assert constructor.identity == TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE
    source = (
        ROOT / "benchmarks/semantic_roundtrip/constructors/typed_deontic.py"
    ).read_text(encoding="utf-8")
    lowered = source.lower()
    for banned in (
        "openai",
        "anthropic",
        "leanstral",
        "from transformers",
        "import torch",
    ):
        assert banned not in lowered


def test_missing_temporal_remains_zero_residual_control() -> None:
    """Zero-residual holdout activation case stays cleared (no receipt required)."""

    case = _holdout_cases()["missing_temporal"]
    l1 = construct_baseline_l1(case)
    forward = float(compare_semantic_ir(case.gold_ir, l1)["semantic_loss"])
    facets = compute_facet_residuals(case.case_id, case.gold_ir, l1)
    assert forward == pytest.approx(0.0, abs=1e-9)
    assert facets == ()
    assert l1.rules[0].temporal == ("after_30_days",)
