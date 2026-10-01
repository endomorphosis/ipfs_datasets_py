"""Legal/UI qualifier integration preserves source joins and complete loss gates.

Dependency-double tests exercise gate accounting only. They are explicitly not
Lake execution evidence; real compiler checks live in helper and release tests.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v6 as previous
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v7 as native
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v4 as old_gate
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as gate
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v4 as old_policy
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v5 as policy
from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authored_semantic_projection_panel as authored
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authored_legal_ui_qualifier_panel as rich_panel
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as fixtures
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v5 as trainer


INPUT_KEYS = {"legal_ir": "legal_qualifier_inputs", "ui_ux_ir": "ui_confirmation_inputs"}
REPLACED = {"legal_ir": {"legal-ir/modal-family/deontic/v3", "legal-ir/modal-family/temporal/v3"},
    "ui_ux_ir": {"ui_ux_ir:tdfol"}}


def envelope(row, source, schema, formulas):
    return {"schema": schema, "source_ref": source.to_dict(),
        "original_projection_id": row["projection_id"], "original_source_digest": row["source_digest"],
        "original_payload_sha256": native.core._sha(row["payload"]),
        "declaration_scope": "caller_supplied_interpretation_not_source_translation", "formulas": formulas}


def declaration(domain, row, source):
    values = []
    for index, formula in enumerate(row["payload"]["formulas"]):
        common = {"formula_index": index, "original_formula_sha256": native.core._sha(formula)}
        if domain == "legal_ir":
            values.append({**common, "kind": "activation_guarded_legal_rule",
                "activation_scope": "all_conditions_at_evaluation_origin", "conditions": [],
                "temporal": {"source_index": 0, "source_text": "within 10 days",
                    "temporal_kind": "within_duration", "quantity": 10, "unit": "day",
                    "time_domain": "discrete_nat", "origin": "caller_supplied_evaluation_time",
                    "lower_inclusive": True, "upper_inclusive": True},
                "exception_scope": "activation_time_waiver", "exceptions": []})
        elif " before " not in formula["proposition"]:
            values.append({**common, "kind": "atomic_UI_norm"})
        else:
            action = formula["proposition"].split("(", 1)[1].split(")", 1)[0]
            values.append({**common, "kind": "UI_request_token_confirmation_policy", "action_id": action,
                "policy": "every_invocation_has_valid_confirmation" if formula["operator"] == "obligation"
                    else "unconfirmed_invocation", "event_order": "strict_sequence_position",
                "time_domain": "discrete_nat_ticks", "clock_order": "nondecreasing", "max_age_ticks": 5,
                "freshness_upper_inclusive": True, "correlation": "action_request_token",
                "cancellation": "since_latest_confirmation",
                "consumption": "every_prior_invocation_consumes_token",
                "trace_scope": "finite_observed_prefix", "unobserved_future": "unknown"})
    kind = native.LegalQualifierInterpretation if domain == "legal_ir" else native.UIConfirmationInterpretation
    schema = "legal-qualifier-interpretation/v1" if domain == "legal_ir" else "ui-confirmation-interpretation/v1"
    return kind.from_dict(envelope(row, source, schema, values))


def inputs(domain, *, formulas=True, index=0, ui_risk=None, ui_confirmation=None):
    result = fixtures.source_inputs(fixtures.rows(domain, "train")[index])
    if ui_risk is not None:
        result["ui_training_row"]["bindings"][0]["risk_class"] = ui_risk
    if ui_confirmation is not None:
        result["ui_training_row"]["bindings"][0]["confirmation_class"] = ui_confirmation
    source = previous.supplemental_source_ref(domain, **result)
    if formulas:
        result["formula_inputs"] = [NativeFormulaEvidence(name, text, source) for name, text in authored.FORMULAS.items()]
    original = previous.prepare_family_training_targets_v6(domain, **result)
    result[INPUT_KEYS[domain]] = [declaration(domain, row, source) for row in original["projections"]
                                if row["projection_id"] in REPLACED[domain]]
    return result


def prepare(domain, **kwargs):
    source = inputs(domain, **kwargs)
    return source, native.prepare_family_training_targets_v7(domain, **source)


def rehash(report):
    for row in report["projections"]:
        row["target_sha256"] = native.core._sha({k: v for k, v in row.items() if k != "target_sha256"})
    report["report_sha256"] = native.core._sha({k: v for k, v in report.items() if k != "report_sha256"})


def reviews(report):
    emitted = {row["logic_family"] for row in report["projections"]}
    return [{"family_id": family, "source_digest": report["source_digest"], "disposition": "inapplicable",
        "reason": "This closed authored integration fixture supplies no model for this family.",
        "evidence_refs": ["unit-fixture:explicit-model-scope"]}
        for family in policy.domain_projection_policy(report["domain_id"])["family_inventory"] if family not in emitted]


@pytest.mark.parametrize("domain", fixtures.DOMAINS)
def test_absent_qualifier_inputs_preserve_prior_targets_and_fixed_catalog_floor(domain):
    source = fixtures.source_inputs(fixtures.rows(domain, "train")[0])
    old = previous.prepare_family_training_targets_v6(domain, **source)
    report = native.prepare_family_training_targets_v7(domain, **source)
    logical = lambda value: [{k: v for k, v in row.items() if k not in {"source_digest", "target_sha256"}}
                             for row in value["projections"]]
    assert logical(report) == logical(old)
    assert report["legal_qualifier_inputs"] == report["ui_confirmation_inputs"] == []
    assert report["superseded_v7_qualifier_observations"] == []
    assert len(report["family_inventory"]) == len(report["requested_families"]) == 40
    assert policy.domain_projection_policy(domain)["minimum_batch_floor"] == old_policy.domain_projection_policy(domain)["minimum_batch_floor"]
    native.validate_family_training_report_v7(report, **source)


@pytest.mark.parametrize("domain", INPUT_KEYS)
def test_qualified_replacements_archive_exact_original_and_keep_all_other_targets(domain):
    source, report = prepare(domain)
    baseline = previous.prepare_family_training_targets_v6(domain, **{k: v for k, v in source.items() if k != INPUT_KEYS[domain]})
    old = {row["projection_id"]: row for row in baseline["projections"]}
    active = {row["projection_id"]: row for row in report["projections"]}
    archive = {row["projection_id"]: row for row in report["superseded_v7_qualifier_observations"]}
    assert set(archive) == REPLACED[domain]
    assert not REPLACED[domain].intersection(active)
    assert len(active) == len(old)
    for identity, row in old.items():
        retained = archive[identity] if identity in archive else active[identity]
        assert retained["payload"] == row["payload"]
        if identity in archive:
            assert retained["active_for_training"] is False
            assert retained["replacement_projection_id"] in active
    prepared = gate.prepare_native_family_lean(report, source_inputs=source)
    assert {row["projection_id"] for row in prepared["per_projection"]} == set(active)
    assert all(row["semantic_lowering_supported"] for row in prepared["per_projection"])
    replacements = {row["replacement_projection_id"] for row in archive.values()}
    assert all(row["lowering"]["capability_floor_eligible"] is False
               for row in prepared["per_projection"] if row["projection_id"] in replacements)
    assert prepared["backend_executed"] is False
    assert report["source_text_to_native_formula_inference"] is report["structural_readiness_is_qualification"] is False


@pytest.mark.parametrize("domain", INPUT_KEYS)
def test_gate_cannot_borrow_embedded_declarations_when_original_inputs_omit_them(domain):
    source, report = prepare(domain)
    del source[INPUT_KEYS[domain]]
    with pytest.raises(ValueError):
        gate.prepare_native_family_lean(report, source_inputs=source)


@pytest.mark.parametrize("domain", INPUT_KEYS)
def test_qualifier_input_cannot_be_reused_against_foreign_source(domain):
    source = inputs(domain)
    foreign = inputs(domain, index=2)
    foreign[INPUT_KEYS[domain]] = source[INPUT_KEYS[domain]]
    with pytest.raises(ValueError):
        native.prepare_family_training_targets_v7(domain, **foreign)


@pytest.mark.parametrize("domain", INPUT_KEYS)
@pytest.mark.parametrize("part", ["active_payload", "archive_payload", "embedded_declaration", "base_digest"])
def test_rehashed_tamper_cannot_bypass_exact_source_and_qualifier_replay(domain, part):
    source, report = prepare(domain)
    archived = report["superseded_v7_qualifier_observations"][0]
    if part == "active_payload":
        row = next(row for row in report["projections"] if row["projection_id"] == archived["replacement_projection_id"])
        row["payload"]["unreviewed_extra"] = "tampered"
    elif part == "archive_payload":
        archived["payload"]["formulas"][0]["unreviewed_extra"] = "tampered"
    elif part == "embedded_declaration":
        report[INPUT_KEYS[domain]][0]["formulas"][0]["original_formula_sha256"] = "c" * 64
    else:
        report["v6_source_digest"] = "c" * 64
    rehash(report)
    with pytest.raises(ValueError):
        gate.prepare_native_family_lean(report, source_inputs=source)


@pytest.mark.parametrize("domain", INPUT_KEYS)
@pytest.mark.parametrize("mutation", ["mutable", "duplicate", "wrong_domain"])
def test_mutable_duplicate_or_wrong_domain_declarations_fail_closed(domain, mutation):
    source = inputs(domain)
    key = INPUT_KEYS[domain]
    if mutation == "mutable":
        source[key] = [source[key][0].to_dict()]
    elif mutation == "duplicate":
        source[key].append(source[key][0])
    else:
        domain = "security_ir"
    with pytest.raises(ValueError):
        native.prepare_family_training_targets_v7(domain, **source)


@pytest.mark.parametrize("domain", INPUT_KEYS)
def test_legacy_and_new_interpretations_cannot_replace_same_original_twice(domain):
    case = authored.prepare_case(domain, 0)
    case["source_inputs"][INPUT_KEYS[domain]] = inputs(domain)[INPUT_KEYS[domain]]
    with pytest.raises(ValueError, match="conflicting replacements"):
        native.prepare_family_training_targets_v7(domain, **case["source_inputs"])


@pytest.mark.parametrize("risk,confirmation", [
    ("high", "double_confirm"), ("high", "consent"), ("destructive", "confirm"), ("low", "none")])
def test_flattened_ui_formulas_cannot_hide_unmodeled_native_confirmation_class(risk, confirmation):
    # Rebind the declaration to the changed source: a stale digest must not be
    # the reason that an unsupported policy is rejected.
    source = inputs("ui_ux_ir", ui_risk=risk, ui_confirmation=confirmation)
    with pytest.raises(ValueError, match="confirmation|binding|risk"):
        native.prepare_family_training_targets_v7("ui_ux_ir", **source)


def test_paired_ui_norms_cannot_assign_different_freshness_to_same_confirmation():
    source = inputs("ui_ux_ir")
    value = source["ui_confirmation_inputs"][0].to_dict()
    policy_rows = [row for row in value["formulas"] if row["kind"] == "UI_request_token_confirmation_policy"]
    policy_rows[1]["max_age_ticks"] = policy_rows[0]["max_age_ticks"] + 1
    source["ui_confirmation_inputs"] = [native.UIConfirmationInterpretation.from_dict(value)]
    with pytest.raises(ValueError, match="conflict|consistent"):
        native.prepare_family_training_targets_v7("ui_ux_ir", **source)


@pytest.mark.parametrize("field", ["conditions", "exceptions"])
def test_legal_partitions_cannot_assign_conflicting_meanings_to_same_source_literal(field):
    case = rich_panel.prepare_case("legal_ir", 0)
    source = case["source_inputs"]
    value = source["legal_qualifier_inputs"][1].to_dict()
    binding = value["formulas"][0][field][0]
    binding["expression"] = {"op": "not", "operand": binding["expression"]}
    source["legal_qualifier_inputs"][1] = native.LegalQualifierInterpretation.from_dict(value)
    with pytest.raises(ValueError, match="conflict|consistent"):
        native.prepare_family_training_targets_v7("legal_ir", **source)


def test_partial_legal_coverage_keeps_uninterpreted_partition_active_and_blocking():
    source = inputs("legal_ir")
    source["legal_qualifier_inputs"] = source["legal_qualifier_inputs"][:1]
    report = native.prepare_family_training_targets_v7("legal_ir", **source)
    prepared = gate.prepare_native_family_lean(report, source_inputs=source)
    remaining = [row for row in prepared["per_projection"] if row["projection_id"] in REPLACED["legal_ir"]]
    assert len(remaining) == 1
    assert remaining[0]["semantic_lowering_supported"] is False
    assert any(row["projection_id"] == remaining[0]["projection_id"] for row in report["projections"])
    with pytest.raises(ValueError, match="blocked native projection"):
        trainer._reports([report], atoms=lambda payload: ["explicit-control-test-feature"])


@pytest.mark.parametrize("domain", INPUT_KEYS)
@pytest.mark.parametrize("index", [0, 1, 2])
def test_richer_authored_panels_preserve_all_formula_inputs_and_do_not_claim_fidelity(domain, index):
    case = rich_panel.prepare_case(domain, index)
    report = case["report"]
    prepared = gate.prepare_native_family_lean(report, source_inputs=case["source_inputs"])
    assert len(report["family_inventory"]) == len(report["requested_families"]) == 40
    assert len(report["formula_inputs"]) == 8
    assert all(row["semantic_lowering_supported"] for row in prepared["per_projection"])
    assert case["fixture"]["source_semantics_verified"] is case["fixture"]["heldout"] is False
    assert case["fixture"]["qualified"] is case["fixture"]["admitted"] is False


@pytest.mark.parametrize("domain", INPUT_KEYS)
def test_new_targets_all_participate_in_projection_loss_coverage(domain):
    _, report = prepare(domain)
    rows = trainer._reports([report], atoms=lambda payload: ["explicit-control-test-feature"])
    assert set(rows[0]) == {row["projection_id"] for row in report["projections"]}
    coverage = {"untrained_projection_ids": [], "projections": [
        {"row": 0, "projection_id": name, "has_coverage": True} for name in rows[0]]}
    metrics = {"projections": {name: {"rows": 1} for name in rows[0]}}
    result = trainer._loss_coverage(rows, coverage, metrics)
    assert result["projection_occurrences"] == len(report["projections"])
    new_id = report["superseded_v7_qualifier_observations"][0]["replacement_projection_id"]
    del metrics["projections"][new_id]
    with pytest.raises(ValueError, match="loss metrics omit"):
        trainer._loss_coverage(rows, coverage, metrics)
    coverage["projections"] = [row for row in coverage["projections"] if row["projection_id"] != new_id]
    with pytest.raises(ValueError, match="every emitted projection"):
        trainer._loss_coverage(rows, coverage)


@pytest.fixture
def backend_double(monkeypatch, tmp_path):
    class RuntimeDouble:
        def run(self, request):
            output = "Lean version 4.30.0\n" if request.argv[-1] == "--version" else "unit_dependency_double_no_native_execution\n"
            return SimpleNamespace(ok=True, stdout=output, stderr="", output_truncated=False,
                workspace_limit_exceeded=False, returncode=0, timed_out=False)
    path = tmp_path / "unit-only-tool"
    path.write_text("Only hashed: imported RuntimeDouble never executes this file.\n")
    path.chmod(0o700)
    monkeypatch.setattr(gate, "BoundedToolRunner", RuntimeDouble)
    return str(path)


def test_old_handles_and_saved_receipts_are_not_current_live_evidence(backend_double):
    source, report = prepare("legal_ir")
    current = gate.build_native_family_lake(report, source_inputs=source, lake_executable=backend_double)
    for value in (old_gate.NativeFamilyLakeExecution(), gate.NativeFamilyLakeExecution(), current.to_dict()):
        with pytest.raises(ValueError, match="live issued"):
            gate.verify_native_family_lake(value, report)
    for value in (old_policy.ProjectionValidationObservation(b"{}"), {"strict_training_allowed": True}):
        with pytest.raises(ValueError, match="live validation observations"):
            trainer._panel([value], "legal_ir")


def test_qualified_legal_targets_cannot_substitute_for_named_formula_floor(backend_double, tmp_path):
    source, report = prepare("legal_ir", formulas=False)
    handle = gate.build_native_family_lake(report, source_inputs=source, lake_executable=backend_double)
    observation = policy.validate_projection_report(report, lake_execution=handle, applicability_review=reviews(report))
    result = policy.evaluate_projection_training_batch([observation], domain_id="legal_ir", target_reports=[report])
    assert result["all_source_projection_gates_passed"]
    assert not result["strict_training_allowed"]
    assert all(not row["satisfied"] for row in result["required_floor"])
    with pytest.raises(policy.ProjectionValidationError):
        trainer.train_validated_family_projection_autoencoder([observation], [observation],
            domain_id="legal_ir", output_dir=tmp_path / "never-trained")
    assert not (tmp_path / "never-trained").exists()
