"""Coverage accounting never substitutes one native family/profile for another."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_coverage_audit as audit
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v2 as native
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR, CanonicalRule


@pytest.fixture
def reports():
    result = {}
    for split in audit.SPLITS:
        document = CanonicalRoundTripIR((CanonicalRule("O", "agency", "publish", split + " notice"),))
        result[split] = [native.prepare_family_training_targets_v2("legal_ir", document=document,
            source_text=f"The agency shall publish the {split} notice.")]
    return result


def _coverage(reports):
    # Synthetic numerical receipt fields exercise accounting only. No model
    # execution or learned reconstruction is represented by these unit rows.
    return {"projections": [{"row": i, "projection_id": target["projection_id"],
        "known_atoms": 3, "unknown_atoms": 2, "has_coverage": True}
        for i, report in enumerate(reports) for target in report["projections"] if target["ready_for_training"]],
        "untrained_projection_ids": []}


def _numerical(reports):
    return {"numerical_training_report": {"domain_id": "legal_ir", "qualified": False,
        "admitted": False, "formalized": False, "training_executed": True,
        "trained_logic_families": ["deontic"],
        "training_reports_sha256": audit._sha(reports["training"]),
        "validation_reports_sha256": audit._sha(reports["tuning"]),
        "training_coverage": _coverage(reports["training"]),
        "validation_coverage": _coverage(reports["tuning"])},
        "numerical_heldout_report": {"domain_id": "legal_ir", "qualified": False,
            "admitted": False, "formalized": False, "coverage": _coverage(reports["heldout"])}}


def _audit(reports, **extra):
    arguments = dict(required_families=["deontic"], required_profiles=[])
    arguments.update(extra)
    return audit.audit_family_training_coverage("legal_ir", training_reports=reports["training"],
        tuning_reports=reports["tuning"], heldout_reports=reports["heldout"], **arguments)


def test_projection_only_cannot_claim_numerical_floor(reports):
    result = _audit(reports)
    assert result["projection_floor_satisfied"] and not result["floor_satisfied"]
    assert result["numerical_training_executed"] is None
    assert len(result["family_inventory"]) == 40
    assert result["required_floor"][0]["missing_numerical_splits"] == list(audit.SPLITS)
    assert all(result[key] is False for key in audit.FALSE)


def test_exact_family_numerical_coverage_preserves_unknown_atoms_and_limitations(reports):
    result = _audit(reports, **_numerical(reports))
    assert result["floor_satisfied"]
    deontic = next(row for row in result["family_inventory"] if row["family_id"] == "deontic")
    assert deontic["splits"]["heldout"]["unknown_atom_count"] == 2
    assert "first_order" in result["requested_families_not_reported_as_trained"]
    assert not result["checkpoint_executed_by_audit"] and not result["source_semantics_verified"]
    assert "no_inference_report_list_digest" in result["heldout_numerical_source_binding"]


def test_absent_requested_families_and_profile_are_explicit_failures(reports):
    result = _audit(reports, required_families=["deontic", "first_order", "dcec", "event_calculus", "propositional"],
        required_profiles=[{"family_id": "tdfol", "profile": "temporal_first_order"}], **_numerical(reports))
    assert not result["floor_satisfied"]
    failed = {(row["family_id"], row["profile"]) for row in result["required_floor"] if not row["floor_satisfied"]}
    assert failed == {("first_order", None), ("dcec", None), ("event_calculus", None),
                      ("propositional", None), ("tdfol", "temporal_first_order")}
    assert len(result["profile_inventory"]) == 1
    assert result["profile_inventory"][0]["splits"]["heldout"]["target_count"] == 0


@pytest.mark.parametrize("families", [["fol"], ["DFOL"], ["TLA+"], ["deontic", "deontic"]])
def test_aliases_and_duplicate_requirements_do_not_satisfy_floor(reports, families):
    with pytest.raises(ValueError, match="canonical required families"):
        _audit(reports, required_families=families)


@pytest.mark.parametrize("profiles", [[{"family_id": "tdfol", "profile": ""}],
    [{"family_id": "tdfol", "profile": "tfol", "alias": True}],
    [{"family_id": "tdfol", "profile": "tfol"}] * 2])
def test_malformed_profile_floor_rejected(reports, profiles):
    with pytest.raises(ValueError):
        _audit(reports, required_profiles=profiles)


def test_nonempty_explicit_floor_required(reports):
    with pytest.raises(ValueError, match="nonempty explicit"):
        _audit(reports, required_families=[])


@pytest.mark.parametrize("minimum", [True, 0, 385])
def test_invalid_minimum_rejected(reports, minimum):
    with pytest.raises(ValueError, match="minimum"):
        _audit(reports, minimum_sources_per_split=minimum)


def test_minimum_support_is_applied_to_every_split(reports):
    result = _audit(reports, minimum_sources_per_split=2, **_numerical(reports))
    assert not result["floor_satisfied"]
    assert result["required_floor"][0]["missing_native_splits"] == list(audit.SPLITS)


def test_source_overlap_rejected_before_numerical_accounting(reports):
    reports["heldout"] = deepcopy(reports["training"])
    with pytest.raises(ValueError, match="overlapping native source"):
        _audit(reports)


def test_same_text_under_different_typed_declaration_cannot_hide_split_overlap(reports):
    original = reports["training"][0]
    source = "The agency shall publish the training notice."
    reports["heldout"] = [native.prepare_family_training_targets_v2("legal_ir",
        document=CanonicalRoundTripIR((CanonicalRule("P", "reviewer", "inspect", "elsewhere"),)), source_text=source)]
    assert reports["heldout"][0]["source_digest"] != original["source_digest"]
    with pytest.raises(ValueError, match="source_sha256"):
        _audit(reports)


def test_current_native_validation_rejects_tampered_complete_inventory(reports):
    report = reports["heldout"][0]
    report["family_inventory"].pop()
    report["report_sha256"] = native.core._sha({key: value for key, value in report.items() if key != "report_sha256"})
    with pytest.raises(ValueError, match="complete canonical family inventory"):
        _audit(reports)


@pytest.mark.parametrize("change", ["digest", "domain", "authority", "training_flag", "invented_family"])
def test_numerical_receipt_must_match_exact_native_training_scope(reports, change):
    values = _numerical(reports)
    receipt = values["numerical_training_report"]
    if change == "digest": receipt["training_reports_sha256"] = "0" * 64
    elif change == "domain": receipt["domain_id"] = "intent_ir"
    elif change == "authority": receipt["qualified"] = True
    elif change == "training_flag": receipt["training_executed"] = 1
    else: receipt["trained_logic_families"] = ["deontic", "dcec"]
    with pytest.raises(ValueError):
        _audit(reports, **values)


@pytest.mark.parametrize("change", ["row", "duplicate", "boolean_count", "mask", "negative", "unseen_conflict"])
def test_numerical_mask_must_identify_actual_ready_target(reports, change):
    values = _numerical(reports)
    coverage = values["numerical_heldout_report"]["coverage"]
    row = coverage["projections"][0]
    if change == "row": row["row"] = 55
    elif change == "duplicate": coverage["projections"].append(deepcopy(row))
    elif change == "boolean_count": row["known_atoms"] = True
    elif change == "mask": row["has_coverage"] = False
    elif change == "negative": row["unknown_atoms"] = -1
    else: coverage["untrained_projection_ids"] = [row["projection_id"]]
    with pytest.raises(ValueError):
        _audit(reports, **values)


def test_missing_trained_family_cannot_pass_despite_covered_receipts(reports):
    values = _numerical(reports)
    values["numerical_training_report"]["trained_logic_families"] = []
    result = _audit(reports, **values)
    assert not result["floor_satisfied"]
    assert "deontic" in result["requested_families_not_reported_as_trained"]


def test_numerical_unseen_projection_and_no_work_cannot_pass(reports):
    values = _numerical(reports)
    coverage = values["numerical_heldout_report"]["coverage"]
    coverage["untrained_projection_ids"] = [coverage["projections"][0]["projection_id"]]
    coverage["projections"] = []
    result = _audit(reports, **values)
    assert not result["floor_satisfied"] and result["untrained_projection_ids"]["heldout"]
    values = _numerical(reports)
    values["numerical_training_report"]["training_executed"] = False
    assert not _audit(reports, **values)["floor_satisfied"]


def test_audit_does_not_retain_or_mutate_caller_data(reports):
    values = _numerical(reports)
    before = deepcopy((reports, values))
    result = _audit(reports, **values)
    result["family_inventory"][0]["splits"]["training"]["frontier_reasons"].append("modified")
    assert (reports, values) == before
    assert _audit(reports, **values)["audit_sha256"] != audit._sha({k: v for k, v in result.items() if k != "audit_sha256"})


def test_total_byte_limit_checked_before_reporting(reports, monkeypatch):
    monkeypatch.setattr(audit, "MAX_TOTAL_BYTES", 5)
    with pytest.raises(ValueError, match="byte bound"):
        _audit(reports)
