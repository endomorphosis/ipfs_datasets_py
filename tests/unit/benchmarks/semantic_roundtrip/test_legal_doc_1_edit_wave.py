"""PLAT-081 det. compiler edit wave: legal_doc_1.

Acceptance bar:

* Wave cites packet CID(s) and residual catalog provenance.
* legal_doc_1 forward/e2e loss ≤ prior residual-catalog baseline.
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
    _classify_qualifier_facet,
    _normalize_numeric_surface,
    _qualifier_fully_grounded,
    _tokens,
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
    / "legal_doc_1.json"
)
RESIDUAL_CATALOG_PATH = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "plateau_residual_catalog.json"
)
# Sealed residual-catalog priors for legal_doc_1 (PLAT-010).
PRIOR_LEGAL_DOC_FORWARD = 0.133333332
PRIOR_LEGAL_DOC_E2E = 0.15


def _load_receipt() -> dict[str, object]:
    assert RECEIPT_PATH.is_file(), f"missing edit-wave receipt: {RECEIPT_PATH}"
    payload = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_legal_doc_1_forward_loss_clears_prior_residual() -> None:
    cases = {case.case_id: case for case in load_pilot_matrix_cases()}
    case = cases["legal_doc_1"]
    l1 = construct_baseline_l1(case)
    comparison = compare_semantic_ir(case.gold_ir, l1)
    forward = float(comparison["semantic_loss"])
    facets = compute_facet_residuals(case.case_id, case.gold_ir, l1)

    assert len(l1.rules) == len(case.gold_ir.rules) == 3
    assert forward <= PRIOR_LEGAL_DOC_FORWARD + 1e-9
    assert forward == pytest.approx(0.0, abs=1e-9)
    assert facets == ()
    # Gold IR is recovered exactly (order-normalized by CanonicalRuleIR).
    assert l1.to_dict() == case.gold_ir.to_dict()
    by_action = {rule.action: rule for rule in l1.rules}
    assert by_action["disclose"].conditions == ()
    assert by_action["disclose"].exceptions == (
        "explicit_consent",
        "required_by_law_enforcement_agencies",
    )
    assert by_action["report"].temporal == ("within_30_days_of_detection",)
    assert by_action["maintain"].conditions == (
        "transaction_amount_exceeds_10000",
    )
    assert by_action["maintain"].temporal == ("for_five_years",)


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


def test_currency_amount_and_exception_context_projection() -> None:
    """Unit-level projection: $10,000 amount gate + without/except carve-outs."""

    assert "10000" in _tokens("exceeding $10,000 for five years")
    assert _normalize_numeric_surface("$10,000") == "10000"
    maintain_evidence = (
        "All financial institutions must maintain records of all "
        "transactions exceeding $10,000 for a period of five years"
    )
    assert _qualifier_fully_grounded(
        maintain_evidence, "transaction_amount_exceeds_10000"
    )
    assert _qualifier_fully_grounded(maintain_evidence, "for_five_years")

    disclose_evidence = (
        "banks cannot disclose customer information to third parties "
        "without explicit consent, except when required by law "
        "enforcement agencies"
    )
    assert (
        _classify_qualifier_facet("explicit_consent", disclose_evidence)
        == "exceptions"
    )
    assert (
        _classify_qualifier_facet(
            "required_by_law_enforcement_agencies", disclose_evidence
        )
        == "exceptions"
    )
    # Pure temporal stays temporal under surrounding exception wording.
    assert (
        _classify_qualifier_facet(
            "within_30_days_of_detection",
            "report within 30 days of detection except weekends",
        )
        == "temporal"
    )

    vocabulary = AllowedAtomVocabulary(
        actors=(
            "banks",
            "credit_unions",
            "financial_institutions",
            "law_enforcement_agencies",
        ),
        actions=("audit", "delete", "disclose", "maintain", "report"),
        objects=(
            "account_balances",
            "customer_information_to_third_parties",
            "suspicious_activities_to_financial_crimes_enforcement_network",
            "tax_returns",
            "transaction_records",
        ),
        qualifiers=(
            "explicit_consent",
            "for_five_years",
            "required_by_law_enforcement_agencies",
            "transaction_amount_exceeds_10000",
            "with_customer_notice",
            "within_10_days_of_detection",
            "within_30_days_of_detection",
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
                "modality": "F",
                "norm_type": "prohibition",
                "actor": "Banks",
                "action": (
                    "disclose customer information to third parties "
                    "without explicit consent"
                ),
                "action_verb": "disclose",
                "action_object": "customer information to third parties",
                "conditions": [],
                "exceptions": [
                    {"text": "explicit consent"},
                    {"text": "required by law enforcement agencies"},
                ],
                "temporal_constraints": [],
                "source_text": (
                    "However, banks cannot disclose customer information "
                    "to third parties without explicit consent, except when "
                    "required by law enforcement agencies."
                ),
            }
        ),
        _Norm(
            {
                "modality": "O",
                "norm_type": "obligation",
                "actor": "financial institutions",
                "action": (
                    "maintain records of all transactions exceeding $10,000 "
                    "for a period of five years"
                ),
                "action_verb": "maintain",
                "action_object": "records of all transactions",
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": (
                    "All financial institutions must maintain records of "
                    "all transactions exceeding $10,000 for a period of "
                    "five years."
                ),
            }
        ),
        _Norm(
            {
                "modality": "O",
                "norm_type": "obligation",
                "actor": "Banks",
                "action": (
                    "report suspicious activities to the Financial Crimes "
                    "Enforcement Network within 30 days of detection"
                ),
                "action_verb": "report",
                "action_object": (
                    "suspicious activities to the Financial Crimes "
                    "Enforcement Network"
                ),
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": (
                    "Banks are required to report suspicious activities to "
                    "the Financial Crimes Enforcement Network within 30 "
                    "days of detection."
                ),
            }
        ),
    ]
    ir, _diagnostics = project_legal_norms_with_diagnostics(
        norms, vocabulary, source_text="legal doc excerpt"
    )
    by_action = {rule.action: rule for rule in ir.rules}
    disclose = by_action["disclose"]
    assert disclose.conditions == ()
    assert disclose.exceptions == (
        "explicit_consent",
        "required_by_law_enforcement_agencies",
    )
    maintain = by_action["maintain"]
    assert maintain.conditions == ("transaction_amount_exceeds_10000",)
    assert maintain.temporal == ("for_five_years",)
    report = by_action["report"]
    assert report.temporal == ("within_30_days_of_detection",)
    # Cross-rule isolation: report must not inherit maintain amount gate.
    assert report.conditions == ()


def test_edit_wave_receipt_cites_packet_and_forbids_optional_promotion() -> None:
    receipt = _load_receipt()
    catalog = json.loads(RESIDUAL_CATALOG_PATH.read_text(encoding="utf-8"))

    assert receipt["interface"] == "PlateauEditWaveReceipt@1"
    assert receipt["edit_wave_task_id"] == "PLAT-081"
    assert receipt["case_id"] == "legal_doc_1"
    assert receipt["board_namespace"] == "semantic-roundtrip-plateau-break-v1"
    assert receipt["baseline_arm_id"] == BASELINE_ARM_ID
    assert receipt["semantic_authority"] is False
    assert receipt["implementable"] is True
    assert receipt["parallel_lane"] == "plat-det-legal-doc"
    assert receipt["evidence_subset"] == "edit-wave legal_doc_1"

    packet_cids = receipt["packet_cids"]
    assert isinstance(packet_cids, list) and packet_cids
    assert all(
        isinstance(item, str) and item.startswith("baguqeera")
        for item in packet_cids
    )
    packet_ids = receipt["packet_ids"]
    assert isinstance(packet_ids, list) and packet_ids
    assert any("legal-doc" in str(item) for item in packet_ids)

    assert receipt["residual_catalog_cid"] == catalog["catalog_cid"]
    prior = receipt["prior_scores"]
    assert isinstance(prior, dict)
    assert float(prior["legal_doc_1_forward_loss"]) == pytest.approx(
        PRIOR_LEGAL_DOC_FORWARD, abs=1e-8
    )
    assert float(prior["legal_doc_1_end_to_end_loss"]) == pytest.approx(
        PRIOR_LEGAL_DOC_E2E, abs=1e-8
    )

    post = receipt["post_scores"]
    assert isinstance(post, dict)
    assert float(post["legal_doc_1_forward_loss"]) <= float(
        prior["legal_doc_1_forward_loss"]
    ) + 1e-9
    assert float(post["legal_doc_1_forward_loss"]) == pytest.approx(
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
    change_ids = {
        change.get("id") for change in changes if isinstance(change, dict)
    }
    assert "currency_thousands_numeric_normalize" in change_ids
    assert "exception_context_without_except_reclassify" in change_ids
    for change in changes:
        assert isinstance(change, dict)
        assert change.get("runtime") == "typed_deontic_projection"
        assert change.get("optional_runtime") is False

    residual_paths = receipt["residual_field_paths"]
    assert isinstance(residual_paths, list)
    assert "rules[0].conditions" in residual_paths
    assert "rules[2].conditions" in residual_paths

    predicted = receipt["predicted_files"]
    assert "benchmarks/semantic_roundtrip/constructors/typed_deontic.py" in predicted
    assert any("legal_doc_1.json" in str(path) for path in predicted)


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
        c for c in load_pilot_matrix_cases() if c.case_id == "legal_doc_1"
    )
    result = constructor.construct(
        ConstructorRequest(case.source_text, case.allowed_atom_vocabulary, {})
    )
    assert result.status is ComponentStatus.SUCCESS
    assert result.canonical_ir is not None
    assert not result.canonical_ir.is_empty
    by_action = {rule.action: rule for rule in result.canonical_ir.rules}
    assert by_action["maintain"].conditions == (
        "transaction_amount_exceeds_10000",
    )
    assert by_action["disclose"].exceptions == (
        "explicit_consent",
        "required_by_law_enforcement_agencies",
    )
