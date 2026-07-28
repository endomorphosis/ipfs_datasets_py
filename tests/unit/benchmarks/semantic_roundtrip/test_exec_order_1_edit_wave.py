"""PLAT-084 det. compiler edit wave: exec_order_1.

Acceptance bar (same as PLAT-081, with case-specific e2e ceiling):

* Wave cites packet CID(s) and residual catalog provenance.
* exec_order_1 forward/e2e loss ≤ prior residual-catalog baseline (0.05)
  or improved.
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
    _optional_grounding_tokens_for,
    _qualifier_fully_grounded,
    _source_has_domain_condition_cue,
    _source_has_temporal_cue,
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
    / "exec_order_1.json"
)
RESIDUAL_CATALOG_PATH = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "plateau_residual_catalog.json"
)
# Sealed residual-catalog priors for exec_order_1 (PLAT-010).
PRIOR_EXEC_ORDER_FORWARD = 0.05
PRIOR_EXEC_ORDER_E2E = 0.05


def _load_receipt() -> dict[str, object]:
    assert RECEIPT_PATH.is_file(), f"missing edit-wave receipt: {RECEIPT_PATH}"
    payload = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_exec_order_1_forward_loss_clears_prior_residual() -> None:
    cases = {case.case_id: case for case in load_pilot_matrix_cases()}
    case = cases["exec_order_1"]
    l1 = construct_baseline_l1(case)
    comparison = compare_semantic_ir(case.gold_ir, l1)
    forward = float(comparison["semantic_loss"])
    facets = compute_facet_residuals(case.case_id, case.gold_ir, l1)

    assert len(l1.rules) == len(case.gold_ir.rules) == 4
    assert forward <= PRIOR_EXEC_ORDER_FORWARD + 1e-9
    assert forward == pytest.approx(0.0, abs=1e-9)
    assert facets == ()
    # Gold IR is recovered exactly (order-normalized by CanonicalRuleIR).
    assert l1.to_dict() == case.gold_ir.to_dict()
    by_action = {rule.action: rule for rule in l1.rules}
    assert by_action["use"].conditions == ("in_government_communications",)
    assert by_action["implement"].temporal == ("within_90_days",)
    assert by_action["receive"].temporal == ("annually",)
    assert by_action["report"].temporal == ("within_24_hours",)


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


def test_domain_condition_and_compact_hour_projection() -> None:
    """Unit-level projection: domain in_* gate + 24h incident window."""

    assert "24 hour" in _normalize_numeric_surface("within 24h")
    assert "24 hour" in _normalize_numeric_surface("within 24-hrs")
    assert _tokens("within 24h") == ("within", "24", "hour")
    assert _qualifier_fully_grounded(
        "report cybersecurity incidents within 24h",
        "within_24_hours",
    )
    # Leading domain preposition is optional; content tokens still require
    # precision-1.0 grounding.
    assert "in" in _optional_grounding_tokens_for(
        "in_government_communications"
    )
    assert "in" not in _optional_grounding_tokens_for("within_24_hours")
    assert _qualifier_fully_grounded(
        "Chinese-manufactured equipment for government communications",
        "in_government_communications",
    )
    # Wrong numeric window must not ground within_24_hours.
    assert not _qualifier_fully_grounded(
        "report within 72 hours",
        "within_24_hours",
    )
    assert (
        _classify_qualifier_facet("in_government_communications")
        == "conditions"
    )
    assert _classify_qualifier_facet("within_24_hours") == "temporal"
    # Realizer-style "if in …" framing must not steal domain gates into
    # exceptions or temporal.
    assert (
        _classify_qualifier_facet(
            "in_government_communications",
            "shall not use equipment if in government communications",
        )
        == "conditions"
    )
    assert _source_has_temporal_cue("report incidents within 24h")
    assert _source_has_domain_condition_cue(
        "cannot use equipment in any government communications"
    )

    vocabulary = AllowedAtomVocabulary(
        actors=(
            "federal_agencies",
            "federal_employees",
            "government_contractors",
            "private_employees",
            "state_agencies",
        ),
        actions=("audit", "disclose", "implement", "receive", "report", "use"),
        objects=(
            "chinese_manufactured_telecommunications_equipment",
            "classified_information",
            "cybersecurity_incidents",
            "mandatory_cybersecurity_training",
            "personal_devices",
            "zero_trust_cybersecurity_frameworks",
        ),
        qualifiers=(
            "annually",
            "biennially",
            "in_government_communications",
            "within_24_hours",
            "within_72_hours",
            "within_90_days",
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
                "actor": "Agencies",
                "action": (
                    "use Chinese-manufactured telecommunications equipment "
                    "in any government communications"
                ),
                "action_verb": "use",
                "action_object": (
                    "Chinese-manufactured telecommunications equipment"
                ),
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": (
                    "Agencies cannot use Chinese-manufactured "
                    "telecommunications equipment in any government "
                    "communications."
                ),
            }
        ),
        _Norm(
            {
                "modality": "O",
                "norm_type": "obligation",
                "actor": "government contractors",
                "action": "report cybersecurity incidents within 24 hours",
                "action_verb": "report",
                "action_object": "cybersecurity incidents",
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": (
                    "All government contractors are required to report "
                    "cybersecurity incidents within 24 hours."
                ),
            }
        ),
        _Norm(
            {
                "modality": "O",
                "norm_type": "obligation",
                "actor": "Federal agencies",
                "action": (
                    "implement zero-trust cybersecurity frameworks "
                    "within 90 days"
                ),
                "action_verb": "implement",
                "action_object": "zero-trust cybersecurity frameworks",
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": (
                    "Federal agencies must implement zero-trust "
                    "cybersecurity frameworks within 90 days."
                ),
            }
        ),
    ]
    ir, _diagnostics = project_legal_norms_with_diagnostics(
        norms, vocabulary, source_text="exec order excerpt"
    )
    by_action = {rule.action: rule for rule in ir.rules}
    use = by_action["use"]
    assert use.conditions == ("in_government_communications",)
    assert use.temporal == ()
    report = by_action["report"]
    assert report.temporal == ("within_24_hours",)
    assert report.conditions == ()
    implement = by_action["implement"]
    assert implement.temporal == ("within_90_days",)
    # Cross-rule isolation: implement must not inherit the domain gate.
    assert implement.conditions == ()
    # Compact 24h evidence still harvests the closed hour window.
    compact_norms = [
        _Norm(
            {
                "modality": "O",
                "norm_type": "obligation",
                "actor": "government contractors",
                "action": "report cybersecurity incidents within 24h",
                "action_verb": "report",
                "action_object": "cybersecurity incidents",
                "conditions": [],
                "exceptions": [],
                "temporal_constraints": [],
                "source_text": (
                    "Government contractors must report cybersecurity "
                    "incidents within 24h."
                ),
            }
        )
    ]
    compact_ir, _ = project_legal_norms_with_diagnostics(
        compact_norms, vocabulary, source_text="compact hour window"
    )
    assert compact_ir.rules[0].temporal == ("within_24_hours",)


def test_edit_wave_receipt_cites_packet_and_forbids_optional_promotion() -> None:
    receipt = _load_receipt()
    catalog = json.loads(RESIDUAL_CATALOG_PATH.read_text(encoding="utf-8"))

    assert receipt["interface"] == "PlateauEditWaveReceipt@1"
    assert receipt["edit_wave_task_id"] == "PLAT-084"
    assert receipt["case_id"] == "exec_order_1"
    assert receipt["board_namespace"] == "semantic-roundtrip-plateau-break-v1"
    assert receipt["baseline_arm_id"] == BASELINE_ARM_ID
    assert receipt["semantic_authority"] is False
    assert receipt["implementable"] is True
    assert receipt["parallel_lane"] == "plat-det-exec-order"
    assert receipt["evidence_subset"] == "edit-wave exec_order_1"

    packet_cids = receipt["packet_cids"]
    assert isinstance(packet_cids, list) and packet_cids
    assert all(
        isinstance(item, str) and item.startswith("baguqeera")
        for item in packet_cids
    )
    packet_ids = receipt["packet_ids"]
    assert isinstance(packet_ids, list) and packet_ids
    assert any("exec-order" in str(item) for item in packet_ids)

    assert receipt["residual_catalog_cid"] == catalog["catalog_cid"]
    prior = receipt["prior_scores"]
    assert isinstance(prior, dict)
    assert float(prior["exec_order_1_forward_loss"]) == pytest.approx(
        PRIOR_EXEC_ORDER_FORWARD, abs=1e-8
    )
    assert float(prior["exec_order_1_end_to_end_loss"]) == pytest.approx(
        PRIOR_EXEC_ORDER_E2E, abs=1e-8
    )

    post = receipt["post_scores"]
    assert isinstance(post, dict)
    assert float(post["exec_order_1_forward_loss"]) <= float(
        prior["exec_order_1_forward_loss"]
    ) + 1e-9
    assert float(post["exec_order_1_forward_loss"]) == pytest.approx(
        0.0, abs=1e-9
    )
    assert float(post["exec_order_1_end_to_end_loss"]) <= PRIOR_EXEC_ORDER_E2E + 1e-9
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
    assert "compact_hour_window_normalize" in change_ids
    assert "domain_scope_in_on_condition_classify" in change_ids
    assert "optional_domain_preposition_grounding" in change_ids
    for change in changes:
        assert isinstance(change, dict)
        assert change.get("runtime") == "typed_deontic_projection"
        assert change.get("optional_runtime") is False

    residual_paths = receipt["residual_field_paths"]
    assert isinstance(residual_paths, list)
    assert "rules[0].conditions" in residual_paths
    assert "rules[3].temporal" in residual_paths

    predicted = receipt["predicted_files"]
    assert "benchmarks/semantic_roundtrip/constructors/typed_deontic.py" in predicted
    assert any("exec_order_1.json" in str(path) for path in predicted)


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
        c for c in load_pilot_matrix_cases() if c.case_id == "exec_order_1"
    )
    result = constructor.construct(
        ConstructorRequest(case.source_text, case.allowed_atom_vocabulary, {})
    )
    assert result.status is ComponentStatus.SUCCESS
    assert result.canonical_ir is not None
    assert not result.canonical_ir.is_empty
    by_action = {rule.action: rule for rule in result.canonical_ir.rules}
    assert by_action["use"].conditions == ("in_government_communications",)
    assert by_action["report"].temporal == ("within_24_hours",)
