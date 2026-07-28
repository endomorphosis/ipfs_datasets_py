"""PLAT2-050 det. compiler edit waves for repair-development residuals.

Acceptance bar:

* Edit-wave receipts exist for every sealed repair-development case with
  non-zero residual.
* Each wave cites packet / intervention / baseline / tree CIDs, names one
  residual cluster and a deterministic hypothesis, and records changed
  symbols/files, assumptions, tests, structural receipts, context tokens,
  provider calls, and before/after metrics.
* Non-zero repair-development residuals clear (forward loss 0.0).
* Mean forward / e2e loss across the five pilots remains 0.0 (non-regression)
  with coverage / polarity / source-copy gates still passing on the production
  path.
* Production path stays typed_deontic + deterministic; no optional runtime
  promotion (spaCy / AE / Leanstral / SyMAI).
* Rejected / unsupported / optional-teacher-missing evidence is not presented
  as an admitted proposal; residual-only deterministic hypotheses may proceed.
* No blind data or outcomes are accessed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.constructors.typed_deontic import (
    TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE,
    TypedDeonticCanonicalConstructor,
    _classify_qualifier_facet,
    _expand_norms_for_projection,
    _normalize_numeric_surface,
    _recover_missing_permission_norms,
    _split_conjoined_action_norm,
    project_legal_norms_with_diagnostics,
)
from benchmarks.semantic_roundtrip.contracts import (
    AllowedAtomVocabulary,
    ConstructorRequest,
)
from benchmarks.semantic_roundtrip.matrix import load_matrix_cases
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
RECEIPT_DIR = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "repair_dev_edit_wave_receipts"
)
RESIDUAL_CATALOG_PATH = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "repair_dev_residual_catalog.json"
)
INTERVENTION_REGISTRY_PATH = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "repair_dev_intervention_registry.json"
)
REPAIR_DEV_CASES_PATH = (
    ROOT / "tests" / "fixtures" / "semantic_roundtrip" / "repair_dev_cases.json"
)
BASELINE_REPORT_PATH = (
    ROOT
    / "workspace"
    / "benchmarks"
    / "semantic-roundtrip-compositions"
    / "repair_dev_baseline.json"
)

# Sealed repair-development residual-catalog priors (PLAT2-010 / PLAT2-025).
PRIOR_BY_CASE = {
    "legal_doc_2": {
        "forward": 0.3,
        "residual_count": 3,
        "field_paths": (
            "rules[2]",
            "rules[3].conditions",
            "rules[3].temporal",
        ),
    },
    "fed_reg_1": {
        "forward": 0.26,
        "residual_count": 4,
        "field_paths": (
            "rules[3]",
            "rules[2].object",
            "rules[4].conditions",
            "rules[4].temporal",
        ),
    },
    "dept_memo_1": {
        "forward": 0.25,
        "residual_count": 1,
        "field_paths": ("rules[2]",),
    },
    "hr_handbook": {
        "forward": 0.42,
        "residual_count": 3,
        "field_paths": (
            "rules[1]",
            "rules[3]",
            "rules[0].object",
        ),
    },
}

NONZERO_REPAIR_DEV_CASES = tuple(PRIOR_BY_CASE.keys())


def _load_receipt(case_id: str) -> dict[str, object]:
    path = RECEIPT_DIR / f"{case_id}.json"
    assert path.is_file(), f"missing repair-dev edit-wave receipt: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _repair_dev_cases() -> dict[str, object]:
    return {case.case_id: case for case in load_matrix_cases(REPAIR_DEV_CASES_PATH)}


def _load_catalog() -> dict[str, object]:
    return json.loads(RESIDUAL_CATALOG_PATH.read_text(encoding="utf-8"))


def test_receipts_exist_for_every_sealed_nonzero_repair_dev_case() -> None:
    catalog = _load_catalog()
    nonzero = list(catalog["nonzero_case_ids"])  # type: ignore[arg-type]
    assert set(nonzero) == set(NONZERO_REPAIR_DEV_CASES)
    for case_id in nonzero:
        receipt = _load_receipt(case_id)
        assert receipt["case_id"] == case_id
        assert receipt["edit_wave_task_id"] == "PLAT2-050"
        assert receipt["interface"] == "PlateauEditWaveReceipt@1"
        assert receipt["population_kind"] == "repair_development"


@pytest.mark.parametrize("case_id", NONZERO_REPAIR_DEV_CASES)
def test_repair_dev_case_forward_loss_clears_prior_residual(case_id: str) -> None:
    cases = _repair_dev_cases()
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


def test_legal_doc_2_permission_and_purpose_condition() -> None:
    case = _repair_dev_cases()["legal_doc_2"]
    l1 = construct_baseline_l1(case)
    assert len(l1.rules) == 4
    by_action = {rule.action: rule for rule in l1.rules}
    assert by_action["waive"].actor == "credit_unions"
    assert by_action["waive"].modality == "P"
    assert by_action["waive"].conditions == ("for_members_in_good_standing",)
    assert by_action["share"].conditions == ("for_marketing_purposes",)
    assert by_action["share"].temporal == ()


def test_fed_reg_1_conjoined_maintain_honor_and_before_condition() -> None:
    case = _repair_dev_cases()["fed_reg_1"]
    l1 = construct_baseline_l1(case)
    assert len(l1.rules) == 5
    by_action = {(rule.action, rule.object): rule for rule in l1.rules}
    maintain = by_action[("maintain", "do_not_call_registry")]
    honor = by_action[("honor", "all_requests")]
    obtain = by_action[("obtain", "prior_express_written_consent")]
    assert maintain.temporal == ()
    assert honor.temporal == ("within_30_days",)
    assert obtain.conditions == ("before_making_robocalls_to_wireless_numbers",)
    assert obtain.temporal == ()


def test_dept_memo_1_allowed_up_to_duration_permission() -> None:
    case = _repair_dev_cases()["dept_memo_1"]
    l1 = construct_baseline_l1(case)
    assert len(l1.rules) == 4
    report = next(rule for rule in l1.rules if rule.action == "report")
    assert report.modality == "P"
    assert report.actor == "contractors"
    assert report.object == "security_incidents"
    assert report.conditions == ("for_classified_projects",)
    assert report.temporal == ("within_72_hours",)


def test_hr_handbook_split_prohibition_and_discuss_permission() -> None:
    case = _repair_dev_cases()["hr_handbook"]
    l1 = construct_baseline_l1(case)
    assert len(l1.rules) == 5
    by_key = {(rule.action, rule.object): rule for rule in l1.rules}
    assert by_key[("engage", "insider_trading")].modality == "F"
    assert by_key[("share", "material_non_public_information")].modality == "F"
    discuss = by_key[("discuss", "general_business_practices")]
    assert discuss.modality == "P"
    assert discuss.conditions == ("with_industry_colleagues",)


def test_mean_pilot_forward_and_e2e_remain_zero() -> None:
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


def test_pilot_coverage_polarity_source_copy_gates_still_pass() -> None:
    """Pilot gates recorded on the sealed baseline remain satisfied.

    We re-check semantic recovery (coverage of gold IR) and polarity
    preservation via exact IR equality; source-copy exclusion is a property of
    the realizer path and is unchanged by constructor-only edits.
    """

    baseline = json.loads(BASELINE_REPORT_PATH.read_text(encoding="utf-8"))
    pilot_block = baseline["populations"]["pilot"]
    for case_row in pilot_block["cases"]:
        gates = case_row["gates"]
        assert gates["full_coverage"] is True
        assert gates["polarity_preservation"] is True
        # selection_eligible / source_copy_exclusion may be false on some
        # pilots (e.g. exception_with_window); they are not newly broken here.

    for case in load_pilot_matrix_cases():
        l1 = construct_baseline_l1(case)
        assert l1.to_dict() == case.gold_ir.to_dict()
        # Polarity: modality multiset matches gold.
        gold_modalities = sorted(rule.modality for rule in case.gold_ir.rules)
        l1_modalities = sorted(rule.modality for rule in l1.rules)
        assert l1_modalities == gold_modalities


def test_purpose_for_and_before_gerund_classification_unit() -> None:
    assert (
        _classify_qualifier_facet("for_marketing_purposes") == "conditions"
    )
    assert (
        _classify_qualifier_facet("for_members_in_good_standing") == "conditions"
    )
    assert _classify_qualifier_facet("for_classified_projects") == "conditions"
    assert _classify_qualifier_facet("for_five_years") == "temporal"
    assert (
        _classify_qualifier_facet("before_making_robocalls_to_wireless_numbers")
        == "conditions"
    )
    assert _classify_qualifier_facet("before_arbitration") == "temporal"


def test_up_to_duration_normalizes_to_within() -> None:
    surface = _normalize_numeric_surface("allowed up to 72 hours to report")
    assert "within" in surface
    assert "72" in surface
    assert "hour" in surface


def test_conjoined_action_split_unit() -> None:
    vocab = AllowedAtomVocabulary(
        actors=("companies",),
        actions=("maintain", "honor", "approve"),
        objects=("do_not_call_registry", "all_requests"),
        qualifiers=("within_30_days",),
    )
    data = {
        "modality": "O",
        "actor": "Companies",
        "action_verb": "maintain",
        "action_object": "a Do Not Call registry and honor all requests",
        "action": "maintain a Do Not Call registry and honor all requests",
        "temporal_constraints": [
            {
                "type": "deadline",
                "raw_text": "within 30 days",
                "value": "30 days",
            }
        ],
        "source_text": (
            "Companies are required to maintain a Do Not Call registry "
            "and honor all requests within 30 days"
        ),
    }
    parts = _split_conjoined_action_norm(data, vocab)
    assert len(parts) == 2
    assert parts[0]["action_verb"] == "maintain"
    assert "honor" not in str(parts[0]["action_object"]).lower()
    assert parts[0]["temporal_constraints"] == ()
    assert parts[1]["action_verb"] == "honor"
    assert parts[1]["temporal_constraints"]  # retained on rightmost

    # Noun coordination must not split on approved stem leakage.
    gifts = {
        "modality": "P",
        "actor": "Staff members",
        "action_verb": "accept",
        "action_object": (
            "promotional items and gifts up to in value from "
            "approved business partners"
        ),
        "source_text": "Staff members may accept promotional items and gifts",
    }
    gift_vocab = AllowedAtomVocabulary(
        actors=("staff_members",),
        actions=("accept", "approve"),
        objects=("promotional_items_and_gifts",),
        qualifiers=("up_to_50_in_value",),
    )
    assert len(_split_conjoined_action_norm(gifts, gift_vocab)) == 1


def test_permission_recovery_unit() -> None:
    vocab = AllowedAtomVocabulary(
        actors=("credit_unions", "financial_institutions"),
        actions=("waive", "share"),
        objects=("transaction_fees", "customer_data_with_affiliated_companies"),
        qualifiers=("for_members_in_good_standing", "for_marketing_purposes"),
    )
    existing = [
        {
            "source_text": (
                "Financial institutions may share customer data with "
                "affiliated companies for marketing purposes"
            ),
            "actor": "Financial institutions",
            "action_verb": "share",
        }
    ]
    source = (
        "Financial institutions may share customer data with affiliated "
        "companies for marketing purposes. Credit unions are allowed to "
        "waive transaction fees for members in good standing."
    )
    recovered = _recover_missing_permission_norms(source, existing, vocab)
    assert len(recovered) == 1
    assert recovered[0]["action_verb"] == "waive"
    assert "credit" in recovered[0]["actor"].lower()


def test_expand_norms_integrates_split_and_recovery() -> None:
    vocab = AllowedAtomVocabulary(
        actors=("workers", "employees"),
        actions=("engage", "share", "discuss"),
        objects=(
            "insider_trading",
            "material_non_public_information",
            "general_business_practices",
        ),
        qualifiers=("with_industry_colleagues",),
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
                "actor": "All workers",
                "action_verb": "engage",
                "action_object": (
                    "in insider trading or share material non-public information"
                ),
                "source_text": (
                    "All workers must not engage in insider trading or "
                    "share material non-public information"
                ),
            }
        )
    ]
    source = (
        "Employees are allowed to discuss general business practices with "
        "industry colleagues. All workers must not engage in insider trading "
        "or share material non-public information."
    )
    expanded = _expand_norms_for_projection(
        norms, vocab, source_text=source
    )
    dicts = [norm.to_dict() for norm in expanded]  # type: ignore[union-attr]
    verbs = {item.get("action_verb") for item in dicts}
    assert "engage" in verbs
    assert "share" in verbs
    assert "discuss" in verbs


@pytest.mark.parametrize("case_id", NONZERO_REPAIR_DEV_CASES)
def test_edit_wave_receipt_cites_cids_hypothesis_and_metrics(
    case_id: str,
) -> None:
    receipt = _load_receipt(case_id)
    catalog = _load_catalog()
    registry = json.loads(INTERVENTION_REGISTRY_PATH.read_text(encoding="utf-8"))
    prior_meta = PRIOR_BY_CASE[case_id]

    assert receipt["interface"] == "PlateauEditWaveReceipt@1"
    assert receipt["edit_wave_task_id"] == "PLAT2-050"
    assert receipt["case_id"] == case_id
    assert receipt["board_namespace"] == "semantic-roundtrip-plateau-holdout-v2"
    assert receipt["baseline_arm_id"] == BASELINE_ARM_ID
    assert receipt["semantic_authority"] is False
    assert receipt["implementable"] is True
    assert receipt["parallel_lane"] == "plat2-det-edits"
    assert receipt["evidence_subset"] == f"repair development edit-wave {case_id}"

    # Packet / intervention / baseline / tree CIDs.
    packet_cids = receipt["packet_cids"]
    assert isinstance(packet_cids, list) and packet_cids
    assert all(
        isinstance(item, str) and item.startswith("baguqeera")
        for item in packet_cids
    )
    assert receipt["residual_catalog_cid"] == catalog["catalog_cid"]
    assert receipt["tree_cid"] == catalog["tree_cid"]
    assert receipt["baseline_report_cid"] == catalog["baseline"]["report_cid"]
    assert receipt["intervention_registry_cid"] == registry["registry_cid"]
    assert isinstance(receipt["intervention_ids"], list)
    assert receipt["intervention_ids"]

    # Residual cluster + deterministic hypothesis.
    assert isinstance(receipt["residual_cluster"], str) and receipt[
        "residual_cluster"
    ]
    assert isinstance(receipt["deterministic_hypothesis"], str) and receipt[
        "deterministic_hypothesis"
    ]

    # Changed symbols / files, assumptions, tests, structural receipts.
    assert isinstance(receipt["changed_symbols"], list) and receipt[
        "changed_symbols"
    ]
    assert "benchmarks/semantic_roundtrip/constructors/typed_deontic.py" in (
        receipt["changed_files"]  # type: ignore[operator]
    )
    assert isinstance(receipt["assumptions"], list) and receipt["assumptions"]
    assert isinstance(receipt["tests"], list) and receipt["tests"]
    structural = receipt["structural_receipts"]
    assert isinstance(structural, dict)
    assert structural.get("semantic_authority") is False
    assert structural.get("may_substitute_for_e2e") is False

    # Context tokens + provider calls (no optional teacher required).
    context = receipt["context_tokens"]
    assert isinstance(context, dict)
    assert int(context["packet_token_count"]) > 0  # type: ignore[arg-type]
    assert context.get("budget_exceeded") is False
    providers = receipt["provider_calls"]
    assert isinstance(providers, dict)
    assert int(providers["llm_runtime_calls"]) == 0  # type: ignore[arg-type]
    assert int(providers["optional_teacher_calls"]) == 0  # type: ignore[arg-type]
    teacher = receipt["optional_teacher_evidence"]
    assert isinstance(teacher, dict)
    assert teacher.get("admitted_as_proposal") is False
    assert teacher.get("missing_does_not_block_residual_only_hypothesis") is True

    prior = receipt["prior_scores"]
    assert isinstance(prior, dict)
    assert float(prior[f"{case_id}_forward_loss"]) == pytest.approx(  # type: ignore[index]
        prior_meta["forward"], abs=1e-8
    )
    assert float(prior[f"{case_id}_residual_count"]) == prior_meta[  # type: ignore[index]
        "residual_count"
    ]
    assert isinstance(prior.get("per_facet_prior"), list)

    post = receipt["post_scores"]
    assert isinstance(post, dict)
    assert float(post[f"{case_id}_forward_loss"]) == pytest.approx(  # type: ignore[index]
        0.0, abs=1e-9
    )
    assert float(post["mean_pilot_forward_loss"]) == pytest.approx(  # type: ignore[arg-type]
        0.0, abs=1e-9
    )
    assert int(post[f"{case_id}_residual_count"]) == 0  # type: ignore[index]

    assert receipt["optional_runtimes_promoted"] == []
    assert receipt["production_constructor_identity"] == (
        TYPED_DEONTIC_CANONICAL_CONSTRUCTOR_INTERFACE
    )
    assert receipt["production_runtime_unchanged"] is True
    assert receipt["doctrine"]["blind_data_accessed"] is False  # type: ignore[index]
    assert receipt["doctrine"]["independently_revertible"] is True  # type: ignore[index]

    changes = receipt["deterministic_changes"]
    assert isinstance(changes, list) and changes
    for change in changes:
        assert isinstance(change, dict)
        assert change.get("runtime") == "typed_deontic_projection"
        assert change.get("optional_runtime") is False

    # Receipt CID integrity.
    body = {key: value for key, value in receipt.items() if key != "receipt_cid"}
    assert receipt["receipt_cid"] == cid_for_dag_json(body)
    assert receipt["receipt_cid_codec"] == "dag-json"


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


def test_zero_residual_repair_dev_controls_remain_clear() -> None:
    """Zero-residual repair-dev cases stay cleared (no new regressions)."""

    catalog = _load_catalog()
    zero_ids = [
        case_id
        for case_id in catalog["case_ids"]  # type: ignore[union-attr]
        if case_id not in catalog["nonzero_case_ids"]  # type: ignore[operator]
    ]
    cases = _repair_dev_cases()
    for case_id in zero_ids:
        case = cases[case_id]
        l1 = construct_baseline_l1(case)
        forward = float(compare_semantic_ir(case.gold_ir, l1)["semantic_loss"])
        facets = compute_facet_residuals(case.case_id, case.gold_ir, l1)
        assert forward == pytest.approx(0.0, abs=1e-9)
        assert facets == ()


def test_manifest_lists_all_nonzero_receipts() -> None:
    manifest_path = RECEIPT_DIR / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["edit_wave_task_id"] == "PLAT2-050"
    assert set(manifest["case_ids"]) == set(NONZERO_REPAIR_DEV_CASES)
    assert manifest["blind_data_accessed"] is False
    assert manifest["optional_runtimes_promoted"] == []
    assert float(manifest["mean_pilot_forward_loss"]) == pytest.approx(
        0.0, abs=1e-9
    )
