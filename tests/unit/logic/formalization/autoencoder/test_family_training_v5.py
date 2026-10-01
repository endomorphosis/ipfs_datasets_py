"""V5 explicit source interpretations and version-isolated live validation.

External Lake is explicitly doubled in two control tests. These receipts are
not published as proof; native lowering, source replay and hash joins stay real.
The actual emitter and release matrix exercise the installed native toolchain.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v4 as previous
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v5 as native
from ipfs_datasets_py.logic.formalization.autoencoder import native_qualified_lean as qualified
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v2 as old_gate
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v3 as gate
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v3 as policy
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel


def fixture(domain="legal_ir", index=0):
    inputs = panel.source_inputs(panel.rows(domain, "train")[index])
    base = previous.prepare_family_training_targets_v4(domain, **inputs)
    source = native.supplemental_source_ref(domain, **inputs)
    evidence = []
    for row in base["projections"]:
        if row["profile"] not in {"modal_ir_deontic_structural", "modal_ir_temporal_structural", "ui-tdfol-compilation/v1"}:
            continue
        declarations = []
        for index, formula in enumerate(row["payload"]["formulas"]):
            declaration = {"formula_index": index, "original_formula_sha256": qualified.digest(formula)}
            if domain == "legal_ir":
                declaration.update(kind="bounded_temporal_qualification", temporal={"source_text": "within 10 days",
                    "temporal_kind": "within_duration", "quantity": 10, "unit": "day", "time_domain": "discrete_nat",
                    "origin": "caller_supplied_evaluation_time", "lower_inclusive": True, "upper_inclusive": True},
                    exception_scope="activation_time_waiver", exceptions=[])
            elif " before " in formula["proposition"]:
                action = formula["proposition"].split("(", 1)[1].split(")", 1)[0]
                declaration.update(kind="UI_confirmation_policy", action_id=action,
                    policy="every_invocation_has_strict_prior_confirmation" if formula["operator"] == "obligation" else "unconfirmed_invocation",
                    time_domain="discrete_nat", window_origin="caller_supplied_evaluation_time", strict_before=True,
                    correlation="action_id_only", freshness_modeled=False, token_consumption_modeled=False,
                    cancellation_modeled=False)
            else:
                declaration["kind"] = "atomic_UI_norm"
            declarations.append(declaration)
        value = {"schema": qualified.EVIDENCE_SCHEMA, "source_ref": source.to_dict(),
            "original_projection_id": row["projection_id"], "original_source_digest": row["source_digest"],
            "original_payload_sha256": qualified.digest(row["payload"]),
            "declaration_scope": "caller_supplied_interpretation_not_source_translation", "formulas": declarations}
        evidence.append(qualified.ExplicitProjectionInterpretation.from_dict(value))
    assert evidence
    return inputs, base, tuple(evidence)


def prepared(domain="legal_ir", index=0):
    inputs, base, evidence = fixture(domain, index)
    inputs = dict(inputs, qualified_inputs=evidence)
    return inputs, base, native.prepare_family_training_targets_v5(domain, **inputs)


def rehash(report):
    for row in report["projections"]:
        row["target_sha256"] = native.core._sha({k: v for k, v in row.items() if k != "target_sha256"})
    report["report_sha256"] = native.core._sha({k: v for k, v in report.items() if k != "report_sha256"})


@pytest.mark.parametrize("domain", ["legal_ir", "ui_ux_ir"])
def test_no_declaration_leaves_the_original_opaque_projection_blocked(domain):
    inputs, _, declarations = fixture(domain)
    report = native.prepare_family_training_targets_v5(domain, **inputs)
    expected = {item.to_dict()["original_projection_id"] for item in declarations}
    receipt = gate.prepare_native_family_lean(report, source_inputs=inputs)
    rows = [row for row in receipt["per_projection"] if row["projection_id"] in expected]
    assert rows and all(row["semantic_lowering_supported"] is False for row in rows)
    assert not report["explicit_interpretation_inputs"] and not report["superseded_qualified_observations"]
    assert not receipt["backend_executed"]


@pytest.mark.parametrize("domain", ["legal_ir", "ui_ux_ir"])
def test_explicit_records_archive_and_replace_only_exact_matches(domain):
    inputs, base, report = prepared(domain)
    archived = report["superseded_qualified_observations"]
    expected = {item.to_dict()["original_projection_id"] for item in inputs["qualified_inputs"]}
    assert {row["projection_id"] for row in archived} == expected
    original_by_id = {row["projection_id"]: row for row in base["projections"]}
    by_id = {row["projection_id"]: row for row in report["projections"]}
    assert not expected.intersection(by_id)
    for row in archived:
        assert row["payload"] == original_by_id[row["projection_id"]]["payload"]
        assert row["active_for_training"] is False
        replacement = by_id[row["replacement_projection_id"]]
        assert replacement["payload"]["original"]["payload"] == row["payload"]
        assert replacement["payload"]["source_semantics_verified"] is False
    for identity, row in original_by_id.items():
        if identity not in expected:
            assert by_id[identity]["payload"] == row["payload"]
            assert by_id[identity]["ready_for_training"] == row["ready_for_training"]
    assert len(report["family_inventory"]) == len(base["family_inventory"]) == 40
    assert {row["family_id"] for row in report["family_inventory"]} == set(report["requested_families"])
    receipt = gate.prepare_native_family_lean(report, source_inputs=inputs)
    rows = [row for row in receipt["per_projection"] if row["projection_id"].endswith("/explicit-interpretation/v1")]
    assert len(rows) == len(expected)
    assert all(row["semantic_lowering_supported"] and row["lowering"]["capability_floor_eligible"] is False for row in rows)
    assert not receipt["backend_executed"]


@pytest.mark.parametrize("domain", ["legal_ir", "ui_ux_ir"])
def test_replay_never_borrows_embedded_declarations(domain):
    inputs, _, report = prepared(domain)
    without_declarations = {key: value for key, value in inputs.items() if key != "qualified_inputs"}
    with pytest.raises(ValueError, match="exact source and interpretation replay"):
        gate.prepare_native_family_lean(report, source_inputs=without_declarations)
    with pytest.raises(ValueError):
        gate.prepare_native_family_lean(report, source_inputs={})


def test_partial_declaration_preserves_unmapped_blocker_and_changes_identity():
    inputs, _, declarations = fixture()
    default = native.prepare_family_training_targets_v5("legal_ir", **inputs)
    partial = native.prepare_family_training_targets_v5("legal_ir", qualified_inputs=declarations[:1], **inputs)
    complete = native.prepare_family_training_targets_v5("legal_ir", qualified_inputs=declarations, **inputs)
    assert len({r["report_sha256"] for r in (default, partial, complete)}) == 3
    assert len({r["source_digest"] for r in (default, partial, complete)}) == 3
    unmatched = declarations[1].to_dict()["original_projection_id"]
    assert next(row for row in partial["projections"] if row["projection_id"] == unmatched)["ready_for_training"] is False


@pytest.mark.parametrize("mutation", ["duplicate", "stale_source_digest", "foreign_projection", "wrong_payload_digest", "source_ref_digest"])
def test_duplicate_stale_foreign_and_tampered_declarations_fail_closed(mutation):
    inputs, _, declarations = fixture()
    values = list(declarations)
    if mutation == "duplicate":
        values.append(values[0])
    else:
        value = values[0].to_dict()
        if mutation == "stale_source_digest": value["original_source_digest"] = "c" * 64
        elif mutation == "foreign_projection": value["original_projection_id"] = "ui_ux_ir:tdfol"
        elif mutation == "wrong_payload_digest": value["original_payload_sha256"] = "c" * 64
        else: value["source_ref"]["content_sha256"] = "c" * 64
        values[0] = qualified.ExplicitProjectionInterpretation.from_dict(value)
    with pytest.raises(ValueError):
        native.prepare_family_training_targets_v5("legal_ir", qualified_inputs=values, **inputs)


def test_other_actual_source_cannot_reuse_an_original_interpretation():
    _, _, declarations = fixture(index=0)
    other, _, _ = fixture(index=1)
    with pytest.raises(ValueError):
        native.prepare_family_training_targets_v5("legal_ir", qualified_inputs=declarations, **other)


@pytest.mark.parametrize("part", ["active_payload", "archive_payload", "embedded_evidence"])
def test_coherently_rehashed_report_tamper_still_fails_actual_source_replay(part):
    inputs, _, report = prepared()
    if part == "active_payload":
        row = next(row for row in report["projections"] if row["projection_id"].endswith("explicit-interpretation/v1"))
        row["payload"]["interpretation"]["formulas"][0]["temporal"]["quantity"] = 20
        row["payload"]["interpretation_sha256"] = qualified.digest(row["payload"]["interpretation"])
    elif part == "archive_payload":
        report["superseded_qualified_observations"][0]["payload"]["formulas"][0]["predicate"]["name"] = "tampered"
    else:
        report["explicit_interpretation_inputs"][0]["formulas"][0]["temporal"]["quantity"] = 20
    rehash(report)
    with pytest.raises(ValueError):
        gate.prepare_native_family_lean(report, source_inputs=inputs)


@pytest.fixture
def backend_double(monkeypatch, tmp_path):
    """Replace imported I/O dependency, never change pinned issuer functions."""
    class RuntimeDouble:
        def run(self, request):
            stdout = "Lean version 4.30.0\n" if request.argv[-1] == "--version" else "unit_dependency_double_no_native_execution\n"
            return SimpleNamespace(ok=True, stdout=stdout, stderr="", output_truncated=False,
                workspace_limit_exceeded=False, returncode=0, timed_out=False)
    tool = tmp_path / "unit-only-tool"
    tool.write_text("This file is only hashed. RuntimeDouble never executes it.\n")
    tool.chmod(0o700)
    monkeypatch.setattr(gate, "BoundedToolRunner", RuntimeDouble)
    monkeypatch.setattr(old_gate, "BoundedToolRunner", RuntimeDouble)
    return str(tool)


def test_live_gate_versions_and_archive_handles_are_isolated(backend_double):
    inputs, base, report = prepared()
    current = gate.build_native_family_lake(report, source_inputs=inputs, lake_executable=backend_double)
    old_inputs = {key: value for key, value in inputs.items() if key != "qualified_inputs"}
    old = old_gate.build_native_family_lake(base, source_inputs=old_inputs, lake_executable=backend_double)
    for value in (old, old.to_dict(), current.to_dict(), gate.NativeFamilyLakeExecution()):
        with pytest.raises(ValueError, match="live issued"):
            gate.verify_native_family_lake(value, report)
    with pytest.raises(ValueError, match="live issued"):
        old_gate.verify_native_family_lake(current, base)
    receipt = gate.verify_native_family_lake(current, report)
    assert "unit_dependency_double_no_native_execution" in receipt["execution"]["stdout"]


def test_successful_lowering_cannot_bypass_the_fixed_named_family_floor(backend_double):
    inputs, _, report = prepared()
    handle = gate.build_native_family_lake(report, source_inputs=inputs, lake_executable=backend_double)
    present = {row["logic_family"] for row in report["projections"]}
    reviews = [{"family_id": name, "source_digest": report["source_digest"], "disposition": "inapplicable",
        "reason": "Authored source does not declare this family; this review cannot waive the fixed floor.",
        "evidence_refs": ["unit-test:authored-declaration"]}
        for name in policy.domain_projection_policy("legal_ir")["family_inventory"] if name not in present]
    observation = policy.validate_projection_report(report, lake_execution=handle, applicability_review=reviews)
    rows = [r for r in observation.to_dict()["projection_observations"] if r["projection_id"].endswith("explicit-interpretation/v1")]
    assert rows and all(row["validated"] and row["capability_floor_eligible"] is False for row in rows)
    with pytest.raises(policy.ProjectionValidationError):
        policy.require_projection_training_batch([observation], domain_id="legal_ir", target_reports=[report])
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v3 as trainer
    with pytest.raises(policy.ProjectionValidationError):
        trainer._panel([observation], "legal_ir")
    with pytest.raises(ValueError, match="issued live"):
        trainer._panel([policy.ProjectionValidationObservation(observation._bytes)], "legal_ir")
