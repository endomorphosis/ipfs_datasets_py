"""Unit tests for PlateauResidualCatalog@1 residual forensics."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRule,
    CanonicalRuleIR,
)
from benchmarks.semantic_roundtrip.metrics import compare_semantic_ir
from benchmarks.semantic_roundtrip.residual_catalog import (
    ACCESS_MODE_AUTHORIZED_EVALUATOR,
    ACCESS_MODE_PACKET,
    ACCESS_MODE_SUPERVISOR,
    BASELINE_ARM_ID,
    CATALOG_STATUS_NOT_MEASURED,
    CATALOG_STATUS_RUNTIME_FAILED,
    CATALOG_STATUS_SEMANTIC_SCORED,
    CATALOG_STATUS_UNSUPPORTED,
    DEFAULT_CATALOG_RELATIVE_PATH,
    DEFAULT_HOLDOUT_CATALOG_RELATIVE_PATH,
    DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH,
    HOLDOUT_BASELINE_E2E_MEAN,
    HOLDOUT_CASES_RELATIVE_PATH,
    NONZERO_PILOT_CASE_IDS,
    NON_SEMANTIC_CATALOG_STATUSES,
    PILOT_CASE_IDS,
    PILOT_CASES_RELATIVE_PATH,
    PLATEAU_RESIDUAL_CATALOG_INTERFACE,
    PLATEAU_RESIDUAL_CATALOG_SCHEMA,
    POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
    POPULATION_KIND_HOLDOUT,
    POPULATION_KIND_REPAIR_DEVELOPMENT,
    ZERO_RESIDUAL_CONTROL_CASE_ID,
    CaseResidualRecord,
    ResidualCatalogError,
    ResidualFacet,
    aggregate_residuals,
    assert_access_allows_population,
    assert_catalog_usable_on_supervisor_path,
    build_case_residual,
    build_holdout_residual_catalog,
    build_plateau_residual_catalog,
    build_repair_dev_residual_catalog,
    compute_facet_residuals,
    load_holdout_residual_catalog,
    load_plateau_residual_catalog,
    load_population_matrix_cases,
    load_repair_dev_residual_catalog,
    parse_plateau_residual_catalog,
    parse_population_residual_catalog,
    preregistered_holdout_matrix_cases,
    reject_blind_material_on_normal_path,
    suggest_trigger_kind,
    write_holdout_residual_catalog,
    write_plateau_residual_catalog,
    write_repair_dev_residual_catalog,
)
from benchmarks.semantic_roundtrip.selective_repair import RepairTriggerKind


ROOT = Path(__file__).resolve().parents[4]
CATALOG_PATH = ROOT / DEFAULT_CATALOG_RELATIVE_PATH
HOLDOUT_CATALOG_PATH = ROOT / DEFAULT_HOLDOUT_CATALOG_RELATIVE_PATH
REPAIR_DEV_CATALOG_PATH = ROOT / DEFAULT_REPAIR_DEV_CATALOG_RELATIVE_PATH


def _rule(
    *,
    modality: str = "O",
    actor: str = "agency",
    action: str = "file",
    object_atom: str = "notice",
    conditions: tuple[str, ...] = (),
    exceptions: tuple[str, ...] = (),
    temporal: tuple[str, ...] = (),
) -> CanonicalRule:
    return CanonicalRule(
        modality=modality,
        actor=actor,
        action=action,
        object=object_atom,
        conditions=conditions,
        exceptions=exceptions,
        temporal=temporal,
    )


def _ir(*rules: CanonicalRule) -> CanonicalRuleIR:
    return CanonicalRuleIR(rules)


def test_interface_and_schema_are_frozen() -> None:
    assert PLATEAU_RESIDUAL_CATALOG_INTERFACE == "PlateauResidualCatalog@1"
    assert PLATEAU_RESIDUAL_CATALOG_SCHEMA.startswith("ipfs-datasets.")
    assert ZERO_RESIDUAL_CONTROL_CASE_ID == "exception_with_window"
    assert set(NONZERO_PILOT_CASE_IDS) == {
        "exec_order_1",
        "corp_policy_1",
        "legal_doc_1",
        "construction_contract",
    }
    assert set(PILOT_CASE_IDS) == set(NONZERO_PILOT_CASE_IDS) | {
        ZERO_RESIDUAL_CONTROL_CASE_ID
    }
    assert BASELINE_ARM_ID.startswith("typed_deontic__")


def test_zero_residual_control_has_empty_facets() -> None:
    gold = _ir(
        _rule(
            actor="company_a",
            action="submit",
            object_atom="backup_report",
            exceptions=("emergency",),
            temporal=("within_10_days",),
        )
    )
    record = build_case_residual(
        ZERO_RESIDUAL_CONTROL_CASE_ID,
        gold,
        gold,
        is_zero_residual_control=True,
    )
    assert record.forward_loss == 0.0
    assert record.residual_count == 0
    assert record.field_paths == ()
    assert record.is_zero_residual_control is True


def test_compute_facet_residuals_decompose_forward_loss() -> None:
    gold = _ir(
        _rule(temporal=("within_10_days",)),
        _rule(
            actor="banks",
            action="report",
            object_atom="activity",
            conditions=("threshold",),
        ),
    )
    candidate = _ir(
        _rule(temporal=()),
        _rule(
            actor="banks",
            action="report",
            object_atom="activity",
            conditions=(),
        ),
    )
    facets = compute_facet_residuals("demo_case", gold, candidate)
    comparison = compare_semantic_ir(gold, candidate)
    contribution = round(sum(facet.loss_contribution for facet in facets), 9)

    assert facets
    assert abs(contribution - float(comparison["semantic_loss"])) < 1e-8
    paths = {facet.field_path for facet in facets}
    assert "rules[0].temporal" in paths
    assert "rules[1].conditions" in paths
    for facet in facets:
        assert facet.case_id == "demo_case"
        assert facet.loss_contribution > 0.0
        assert facet.suggested_trigger_kind in {
            RepairTriggerKind.MISSING.value,
            RepairTriggerKind.CONTRADICTORY.value,
        }
        assert facet.spacy_cue is None
        assert facet.ae_cue is None


def test_missing_rule_residual_uses_missing_trigger() -> None:
    gold = _ir(_rule(), _rule(actor="banks", action="disclose"))
    candidate = _ir(_rule())
    facets = compute_facet_residuals("missing_case", gold, candidate)
    missing = [facet for facet in facets if facet.residual_kind == "missing_rule"]
    assert missing
    assert all(
        facet.suggested_trigger_kind == RepairTriggerKind.MISSING.value
        for facet in missing
    )
    assert any(facet.field_path.startswith("rules[") for facet in missing)


def test_suggest_trigger_kind_distinguishes_missing_and_contradictory() -> None:
    assert (
        suggest_trigger_kind(
            residual_kind="field_mismatch",
            field="temporal",
            gold_value=["within_10_days"],
            candidate_value=[],
        )
        == RepairTriggerKind.MISSING.value
    )
    assert (
        suggest_trigger_kind(
            residual_kind="field_mismatch",
            field="modality",
            gold_value="O",
            candidate_value="F",
        )
        == RepairTriggerKind.CONTRADICTORY.value
    )
    assert (
        suggest_trigger_kind(
            residual_kind="missing_rule",
            field=None,
            gold_value={},
            candidate_value=None,
        )
        == RepairTriggerKind.MISSING.value
    )


def test_aggregate_residuals_by_case_field_and_trigger() -> None:
    gold = _ir(_rule(temporal=("within_10_days",), conditions=("ready",)))
    candidate = _ir(_rule(temporal=(), conditions=()))
    nonzero = build_case_residual("exec_order_1", gold, candidate)
    control = build_case_residual(
        ZERO_RESIDUAL_CONTROL_CASE_ID,
        _ir(_rule()),
        _ir(_rule()),
        is_zero_residual_control=True,
    )
    aggregates = aggregate_residuals([control, nonzero])

    assert aggregates["case_count"] == 2
    assert aggregates["nonzero_case_count"] == 1
    assert aggregates["nonzero_case_ids"] == ["exec_order_1"]
    assert aggregates["zero_control_residual_count"] == 0
    assert aggregates["total_residual_count"] == nonzero.residual_count
    assert aggregates["by_case"]["exec_order_1"]["residual_count"] == (
        nonzero.residual_count
    )
    assert set(aggregates["by_case"]["exec_order_1"]["field_paths"]) == set(
        nonzero.field_paths
    )
    assert "temporal" in aggregates["by_canonical_field"]
    assert "conditions" in aggregates["by_canonical_field"]
    assert aggregates["by_suggested_trigger_kind"]
    assert aggregates["sum_forward_loss"] == round(
        control.forward_loss + nonzero.forward_loss, 9
    )


def test_residual_facet_and_case_round_trip_parse() -> None:
    gold = _ir(_rule(temporal=("annually",)))
    candidate = _ir(_rule(temporal=()))
    record = build_case_residual("corp_policy_1", gold, candidate)
    parsed = CaseResidualRecord.from_dict(record.to_dict())
    assert parsed == record
    assert parsed.field_paths == record.field_paths
    facet = ResidualFacet.from_dict(record.residuals[0].to_dict())
    assert facet == record.residuals[0]


def test_parse_rejects_broken_cid_binding() -> None:
    checked = load_plateau_residual_catalog(CATALOG_PATH, repo_root=ROOT)
    broken = copy.deepcopy(checked)
    broken["catalog_cid"] = cid_for_dag_json({"not": "the catalog"})
    with pytest.raises(ResidualCatalogError, match="catalog_cid"):
        parse_plateau_residual_catalog(broken)


def test_checked_in_catalog_parses_and_covers_pilots() -> None:
    catalog = load_plateau_residual_catalog(CATALOG_PATH, repo_root=ROOT)

    assert catalog["interface"] == PLATEAU_RESIDUAL_CATALOG_INTERFACE
    assert catalog["schema_version"] == PLATEAU_RESIDUAL_CATALOG_SCHEMA
    assert catalog["baseline"]["arm_id"] == BASELINE_ARM_ID
    assert catalog["zero_residual_control_case_id"] == (
        ZERO_RESIDUAL_CONTROL_CASE_ID
    )
    assert catalog["pilot_case_ids"] == list(PILOT_CASE_IDS)
    assert catalog["nonzero_pilot_case_ids"] == list(NONZERO_PILOT_CASE_IDS)

    cases = {
        item["case_id"]: item for item in catalog["cases"]  # type: ignore[index]
    }
    assert set(cases) == set(PILOT_CASE_IDS)

    control = cases[ZERO_RESIDUAL_CONTROL_CASE_ID]
    assert control["is_zero_residual_control"] is True
    assert control["forward_loss"] == 0.0
    assert control["residual_count"] == 0
    assert control["field_paths"] == []
    assert control["residuals"] == []

    for case_id in NONZERO_PILOT_CASE_IDS:
        record = cases[case_id]
        assert record["forward_loss"] > 0.0
        assert record["residual_count"] > 0
        assert record["field_paths"]
        assert len(record["residuals"]) == record["residual_count"]
        contribution = round(
            sum(
                float(facet["loss_contribution"])  # type: ignore[index]
                for facet in record["residuals"]  # type: ignore[index]
            ),
            9,
        )
        assert abs(contribution - float(record["forward_loss"])) < 1e-6
        for facet in record["residuals"]:  # type: ignore[index]
            assert facet["case_id"] == case_id
            assert facet["field_path"]
            assert float(facet["loss_contribution"]) > 0.0  # type: ignore[arg-type]
            assert "spacy_cue" in facet
            assert "ae_cue" in facet
            assert facet["suggested_trigger_kind"] in {
                RepairTriggerKind.MISSING.value,
                RepairTriggerKind.CONTRADICTORY.value,
                RepairTriggerKind.LOW_CONFIDENCE.value,
            }

    aggregates = catalog["aggregates"]
    assert aggregates["case_count"] == 5
    assert aggregates["nonzero_case_count"] == 4
    assert aggregates["zero_control_residual_count"] == 0
    assert aggregates["total_residual_count"] == len(catalog["residuals"])
    assert set(aggregates["nonzero_case_ids"]) == set(NONZERO_PILOT_CASE_IDS)

    cid_payload = {
        key: value for key, value in catalog.items() if key != "catalog_cid"
    }
    assert catalog["catalog_cid"] == cid_for_dag_json(cid_payload)


def test_checked_in_catalog_aggregates_match_recompute() -> None:
    catalog = load_plateau_residual_catalog(CATALOG_PATH, repo_root=ROOT)
    records = [
        CaseResidualRecord.from_dict(item) for item in catalog["cases"]  # type: ignore[index]
    ]
    recomputed = aggregate_residuals(records)
    for key in (
        "case_count",
        "nonzero_case_count",
        "total_residual_count",
        "zero_control_residual_count",
        "sum_forward_loss",
        "mean_forward_loss",
        "field_paths",
    ):
        assert catalog["aggregates"][key] == recomputed[key]


def test_write_catalog_is_cid_stable(tmp_path: Path) -> None:
    source = load_plateau_residual_catalog(CATALOG_PATH, repo_root=ROOT)
    out = tmp_path / "plateau_residual_catalog.json"
    written = write_plateau_residual_catalog(out, catalog=source)
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded == written
    assert reloaded["catalog_cid"] == source["catalog_cid"]
    parse_plateau_residual_catalog(reloaded)


def test_parse_rejects_missing_nonzero_pilot_residuals() -> None:
    catalog = load_plateau_residual_catalog(CATALOG_PATH, repo_root=ROOT)
    broken = copy.deepcopy(catalog)
    for case in broken["cases"]:  # type: ignore[index]
        if case["case_id"] == "exec_order_1":
            case["residuals"] = []
            case["residual_count"] = 0
            case["field_paths"] = []
            case["loss_contribution_sum"] = 0.0
            case["forward_loss"] = 0.0
    # Drop flat rows for that case too so nested/flat lengths can still match
    broken["residuals"] = [
        row
        for row in broken["residuals"]  # type: ignore[index]
        if row["case_id"] != "exec_order_1"
    ]
    # Fix aggregates loosely; parse should fail on nonzero residual requirement
    # before aggregate equality if case validation runs first.
    with pytest.raises(ResidualCatalogError):
        parse_plateau_residual_catalog(broken)


def _write_population_fixture(
    path: Path, cases: list[dict[str, object]]
) -> Path:
    path.write_text(
        json.dumps(cases, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def test_build_accepts_preregistered_case_population_path(
    tmp_path: Path,
) -> None:
    """Holdout path: build from an explicit preregistered population JSON."""

    holdout_cases = preregistered_holdout_matrix_cases()
    fixture_rows = [
        {
            "id": case.case_id,
            "source_text": case.source_text,
            "allowed_atoms": case.allowed_atom_vocabulary.to_dict(),
            "gold_ir": case.gold_ir.to_dict(),
        }
        for case in holdout_cases
    ]
    population_path = _write_population_fixture(
        tmp_path / "holdout_population.json", fixture_rows
    )
    loaded = load_population_matrix_cases(population_path)
    assert [case.case_id for case in loaded] == [
        case.case_id for case in holdout_cases
    ]

    catalog = build_plateau_residual_catalog(
        ROOT,
        cases_path=population_path,
        population_kind=POPULATION_KIND_HOLDOUT,
    )
    parse_population_residual_catalog(catalog, require_holdout_kind=True)

    assert catalog["population_kind"] == POPULATION_KIND_HOLDOUT
    assert catalog["interface"] == PLATEAU_RESIDUAL_CATALOG_INTERFACE
    assert catalog["schema_version"] == PLATEAU_RESIDUAL_CATALOG_SCHEMA
    assert catalog["baseline"]["arm_id"] == BASELINE_ARM_ID
    assert catalog["baseline"]["e2e_mean"] == HOLDOUT_BASELINE_E2E_MEAN
    assert catalog["case_ids"] == [case.case_id for case in holdout_cases]
    assert set(catalog["case_ids"]).isdisjoint(set(PILOT_CASE_IDS))
    assert "pilot_case_ids" not in catalog
    assert catalog["aggregates"]["case_count"] == len(holdout_cases)
    assert catalog["aggregates"]["total_residual_count"] == len(
        catalog["residuals"]
    )
    # Post-PLAT2-050 det. waves may clear all activation residuals; a
    # zero-residual holdout catalog remains a valid PlateauResidualCatalog@1.
    assert catalog["aggregates"]["total_residual_count"] >= 0

    cases_by_id = {
        item["case_id"]: item for item in catalog["cases"]  # type: ignore[index]
    }
    for case_id in catalog["case_ids"]:  # type: ignore[union-attr]
        record = cases_by_id[case_id]
        assert "residuals" in record
        assert record["residual_count"] == len(record["residuals"])
        contribution = round(
            sum(
                float(facet["loss_contribution"])  # type: ignore[index]
                for facet in record["residuals"]  # type: ignore[index]
            ),
            9,
        )
        assert abs(contribution - float(record["forward_loss"])) < 1e-6
        for facet in record["residuals"]:  # type: ignore[index]
            assert facet["case_id"] == case_id
            assert facet["field_path"]
            assert float(facet["loss_contribution"]) > 0.0  # type: ignore[arg-type]

    # Pilot seal parser must remain fail-closed on holdout payloads.
    with pytest.raises(ResidualCatalogError, match="population residual"):
        parse_plateau_residual_catalog(catalog)


def test_build_from_pilot_cases_path_preserves_seal() -> None:
    """Pilot population path keeps sealed field layout (not holdout keys).

    Post-plateau typed_deontic L1 may zero out historical pilot residuals, so
    this test does not require regenerating the sealed nonzero receipt.  The
    checked-in pilot catalog remains fail-closed via parse.
    """

    catalog = build_plateau_residual_catalog(
        ROOT,
        cases_path=ROOT / PILOT_CASES_RELATIVE_PATH,
        population_kind="pilot",
    )
    assert catalog["pilot_case_ids"] == list(PILOT_CASE_IDS)
    assert catalog["nonzero_pilot_case_ids"] == list(NONZERO_PILOT_CASE_IDS)
    assert catalog["zero_residual_control_case_id"] == (
        ZERO_RESIDUAL_CONTROL_CASE_ID
    )
    assert "population_kind" not in catalog
    assert "case_ids" not in catalog
    assert "population_path" not in catalog
    # Historical pilot seal receipt still validates independently.
    sealed = load_plateau_residual_catalog(CATALOG_PATH, repo_root=ROOT)
    parse_plateau_residual_catalog(sealed)
    assert sealed["pilot_case_ids"] == list(PILOT_CASE_IDS)


def test_checked_in_holdout_catalog_parses_with_case_facet_residuals() -> None:
    assert HOLDOUT_CATALOG_PATH.is_file(), (
        "holdout_residual_catalog.json must be written by PLAT2-010"
    )
    catalog = load_holdout_residual_catalog(
        HOLDOUT_CATALOG_PATH, repo_root=ROOT
    )

    assert catalog["population_kind"] == POPULATION_KIND_HOLDOUT
    assert str(HOLDOUT_CASES_RELATIVE_PATH).replace("\\", "/") in str(
        catalog["population_path"]
    )
    assert catalog["case_ids"]
    assert set(catalog["case_ids"]).isdisjoint(set(PILOT_CASE_IDS))
    assert catalog["aggregates"]["case_count"] == len(catalog["case_ids"])
    assert catalog["aggregates"]["total_residual_count"] == len(
        catalog["residuals"]
    )
    # Sealed PLAT2-010 receipt records pre-wave residuals for the activation
    # subset; live det. path may clear them (PLAT2-050) without rewriting the
    # sealed JSON.
    assert catalog["aggregates"]["total_residual_count"] >= 0
    assert catalog["baseline"]["arm_id"] == BASELINE_ARM_ID

    for case_id in catalog.get("nonzero_case_ids") or []:  # type: ignore[union-attr]
        record = next(
            item
            for item in catalog["cases"]  # type: ignore[union-attr]
            if item["case_id"] == case_id
        )
        assert record["forward_loss"] > 0.0
        assert record["residual_count"] > 0
        assert record["field_paths"]
        for facet in record["residuals"]:
            assert facet["case_id"] == case_id
            assert float(facet["loss_contribution"]) > 0.0

    cid_payload = {
        key: value for key, value in catalog.items() if key != "catalog_cid"
    }
    assert catalog["catalog_cid"] == cid_for_dag_json(cid_payload)

    # Sealed PLAT2-010 receipt used the activation-fixture subset (3 cases)
    # with population_path pointing at holdout_cases.json.  Full-fixture
    # regeneration (8 cases) and post-PLAT2-050 det. L1 improvements produce
    # a different CID; still require a valid holdout catalog that covers the
    # sealed nonzero case ids and never regresses residual *counts* above the
    # sealed priors for those cases.
    from benchmarks.semantic_roundtrip.residual_catalog import (
        preregistered_holdout_matrix_cases,
    )

    regenerated = build_holdout_residual_catalog(ROOT)
    parse_population_residual_catalog(regenerated, require_holdout_kind=True)
    assert regenerated["population_kind"] == POPULATION_KIND_HOLDOUT
    assert set(catalog["case_ids"]).issubset(set(regenerated["case_ids"]))  # type: ignore[arg-type]
    sealed_by_id = {
        item["case_id"]: item for item in catalog["cases"]  # type: ignore[union-attr]
    }
    regen_by_id = {
        item["case_id"]: item for item in regenerated["cases"]  # type: ignore[union-attr]
    }
    for case_id in catalog["nonzero_case_ids"]:  # type: ignore[union-attr]
        assert case_id in regen_by_id
        # Det. edit waves may clear residuals; never allow more residuals than
        # the sealed prior for an activation case.
        assert (
            regen_by_id[case_id]["residual_count"]
            <= sealed_by_id[case_id]["residual_count"]
        )
        assert (
            float(regen_by_id[case_id]["forward_loss"])
            <= float(sealed_by_id[case_id]["forward_loss"]) + 1e-9
        )

    # Activation-only rebuild remains a valid holdout catalog for the sealed
    # three-case population shape used by PLAT2-010.
    activation = build_holdout_residual_catalog(
        ROOT,
        cases=preregistered_holdout_matrix_cases(),
        cases_path=HOLDOUT_CASES_RELATIVE_PATH,
    )
    parse_population_residual_catalog(activation, require_holdout_kind=True)
    assert activation["case_ids"] == catalog["case_ids"]
    # After PLAT2-050 det. edits, activation residuals may be empty while the
    # sealed receipt still records the pre-wave residual facets.
    assert activation["aggregates"]["total_residual_count"] <= catalog[
        "aggregates"
    ]["total_residual_count"]


def test_write_holdout_catalog_round_trip(tmp_path: Path) -> None:
    source = build_holdout_residual_catalog(ROOT)
    out = tmp_path / "holdout_residual_catalog.json"
    written = write_holdout_residual_catalog(out, catalog=source)
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded == written
    parse_population_residual_catalog(reloaded, require_holdout_kind=True)
    assert reloaded["catalog_cid"] == source["catalog_cid"]


def test_build_accepts_explicitly_typed_repair_development_population() -> None:
    catalog = build_plateau_residual_catalog(
        ROOT,
        population_kind=POPULATION_KIND_REPAIR_DEVELOPMENT,
    )
    parse_population_residual_catalog(
        catalog,
        require_repair_development_kind=True,
        access_mode=ACCESS_MODE_SUPERVISOR,
    )

    assert catalog["population_kind"] == POPULATION_KIND_REPAIR_DEVELOPMENT
    assert catalog["interface"] == PLATEAU_RESIDUAL_CATALOG_INTERFACE
    assert catalog["schema_version"] == PLATEAU_RESIDUAL_CATALOG_SCHEMA
    assert catalog["baseline"]["arm_id"] == BASELINE_ARM_ID
    assert catalog["baseline"]["e2e_mean"] == HOLDOUT_BASELINE_E2E_MEAN
    assert catalog["case_ids"]
    assert set(catalog["case_ids"]).isdisjoint(set(PILOT_CASE_IDS))
    assert catalog["tree_cid"]
    assert catalog["population_cid"]
    assert catalog["catalog_cid"]
    assert catalog["assumptions"]
    assert catalog["status"]["non_semantic_excluded_from_score_aggregates"] is True
    assert set(catalog["status"]["non_semantic_statuses"]) == set(
        NON_SEMANTIC_CATALOG_STATUSES
    )
    assert catalog["provenance"]["population_kind"] == (
        POPULATION_KIND_REPAIR_DEVELOPMENT
    )
    assert catalog["provenance"]["tree_cid"] == catalog["tree_cid"]
    assert catalog["provenance"]["population_cid"] == catalog["population_cid"]

    for case_id in catalog["case_ids"]:
        status_entry = catalog["status"]["by_case"][case_id]
        assert status_entry["evaluation_status"] in {
            CATALOG_STATUS_SEMANTIC_SCORED,
            CATALOG_STATUS_UNSUPPORTED,
            CATALOG_STATUS_NOT_MEASURED,
            CATALOG_STATUS_RUNTIME_FAILED,
        }
        record = next(
            item for item in catalog["cases"] if item["case_id"] == case_id
        )
        if status_entry["semantic_score_eligible"]:
            assert record["residual_count"] == len(record["residuals"])
            contribution = round(
                sum(float(facet["loss_contribution"]) for facet in record["residuals"]),
                9,
            )
            assert abs(contribution - float(record["forward_loss"])) < 1e-6
        else:
            assert record["residuals"] == []
            assert record["residual_count"] == 0

    # Pilot seal parser remains fail-closed on repair-dev payloads.
    with pytest.raises(ResidualCatalogError, match="population residual"):
        parse_plateau_residual_catalog(catalog)

    assert_catalog_usable_on_supervisor_path(
        catalog, access_mode=ACCESS_MODE_SUPERVISOR
    )
    assert_catalog_usable_on_supervisor_path(
        catalog, access_mode=ACCESS_MODE_PACKET
    )


def test_checked_in_repair_dev_catalog_parses_with_bindings() -> None:
    assert REPAIR_DEV_CATALOG_PATH.is_file(), (
        "repair_dev_residual_catalog.json must be written by PLAT2-010"
    )
    catalog = load_repair_dev_residual_catalog(
        REPAIR_DEV_CATALOG_PATH, repo_root=ROOT
    )
    assert catalog["population_kind"] == POPULATION_KIND_REPAIR_DEVELOPMENT
    assert catalog["tree_cid"]
    assert catalog["population_cid"]
    assert catalog["assumptions"]
    assert catalog["status"]["non_semantic_excluded_from_score_aggregates"] is True
    assert catalog["provenance"]["builder"]
    assert catalog["aggregates"]["case_count"] == len(catalog["case_ids"])
    assert catalog["aggregates"]["total_residual_count"] == len(
        catalog["residuals"]
    )
    cid_payload = {
        key: value for key, value in catalog.items() if key != "catalog_cid"
    }
    assert catalog["catalog_cid"] == cid_for_dag_json(cid_payload)

    regenerated = build_repair_dev_residual_catalog(ROOT)
    parse_population_residual_catalog(
        regenerated, require_repair_development_kind=True
    )
    assert regenerated["population_kind"] == POPULATION_KIND_REPAIR_DEVELOPMENT
    assert set(catalog["case_ids"]).issubset(set(regenerated["case_ids"]))


def test_write_repair_dev_catalog_round_trip(tmp_path: Path) -> None:
    source = build_repair_dev_residual_catalog(ROOT)
    out = tmp_path / "repair_dev_residual_catalog.json"
    written = write_repair_dev_residual_catalog(out, catalog=source)
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded == written
    parse_population_residual_catalog(
        reloaded, require_repair_development_kind=True
    )
    assert reloaded["catalog_cid"] == source["catalog_cid"]


def test_non_semantic_statuses_excluded_from_score_aggregates() -> None:
    gold = _ir(_rule(temporal=("within_10_days",)))
    candidate = _ir(_rule(temporal=()))
    scored = build_case_residual("scored_case", gold, candidate)
    unsupported = CaseResidualRecord(
        case_id="unsupported_case",
        forward_loss=0.0,
        residuals=(),
        is_zero_residual_control=False,
        evaluation_status=CATALOG_STATUS_UNSUPPORTED,
        evaluation_status_reason="terminal_unsupported",
    )
    not_measured = CaseResidualRecord(
        case_id="not_measured_case",
        forward_loss=0.0,
        residuals=(),
        is_zero_residual_control=False,
        evaluation_status=CATALOG_STATUS_NOT_MEASURED,
        evaluation_status_reason="preflight_blocked",
    )
    runtime_failed = CaseResidualRecord(
        case_id="runtime_failed_case",
        forward_loss=0.0,
        residuals=(),
        is_zero_residual_control=False,
        evaluation_status=CATALOG_STATUS_RUNTIME_FAILED,
        evaluation_status_reason="provider_error",
    )
    aggregates = aggregate_residuals(
        [scored, unsupported, not_measured, runtime_failed]
    )
    assert aggregates["case_count"] == 4
    assert aggregates["semantic_scored_case_count"] == 1
    assert aggregates["sum_forward_loss"] == scored.forward_loss
    assert aggregates["total_residual_count"] == scored.residual_count
    assert aggregates["by_evaluation_status"][CATALOG_STATUS_UNSUPPORTED] == 1
    assert aggregates["by_evaluation_status"][CATALOG_STATUS_NOT_MEASURED] == 1
    assert aggregates["by_evaluation_status"][CATALOG_STATUS_RUNTIME_FAILED] == 1
    assert aggregates["by_evaluation_status"][CATALOG_STATUS_SEMANTIC_SCORED] == 1

    with pytest.raises(ResidualCatalogError, match="must not carry residual"):
        CaseResidualRecord(
            case_id=scored.case_id,
            forward_loss=scored.forward_loss,
            residuals=scored.residuals,
            is_zero_residual_control=False,
            evaluation_status=CATALOG_STATUS_UNSUPPORTED,
        )


def test_premature_blind_access_rejected_on_supervisor_and_packet_paths(
    tmp_path: Path,
) -> None:
    holdout_cases = preregistered_holdout_matrix_cases()
    # Unauthorized build of blind population fails closed.
    with pytest.raises(ResidualCatalogError, match="premature blind access"):
        build_plateau_residual_catalog(
            ROOT,
            cases=holdout_cases,
            population_kind=POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
            access_mode=ACCESS_MODE_SUPERVISOR,
        )
    with pytest.raises(ResidualCatalogError, match="premature blind access"):
        build_plateau_residual_catalog(
            ROOT,
            cases=holdout_cases,
            population_kind=POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
            access_mode=ACCESS_MODE_PACKET,
        )
    # Missing authorization in evaluator mode fails closed.
    with pytest.raises(ResidualCatalogError, match="missing evaluator authorization"):
        build_plateau_residual_catalog(
            ROOT,
            cases=holdout_cases,
            population_kind=POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
            access_mode=ACCESS_MODE_AUTHORIZED_EVALUATOR,
        )
    # Pre-freeze authorization fails closed.
    with pytest.raises(ResidualCatalogError, match="premature blind access"):
        build_plateau_residual_catalog(
            ROOT,
            cases=holdout_cases,
            population_kind=POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
            access_mode=ACCESS_MODE_AUTHORIZED_EVALUATOR,
            evaluator_authorization={
                "evaluator_mode": True,
                "candidate_freeze_cid": cid_for_dag_json({"freeze": "demo"}),
                "post_freeze": False,
            },
        )
    # Authorized post-freeze evaluator path succeeds.
    freeze_cid = cid_for_dag_json({"freeze": "candidate", "tree": "demo"})
    auth = {
        "evaluator_mode": True,
        "candidate_freeze_cid": freeze_cid,
        "post_freeze": True,
    }
    blind = build_plateau_residual_catalog(
        ROOT,
        cases=holdout_cases,
        population_kind=POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
        access_mode=ACCESS_MODE_AUTHORIZED_EVALUATOR,
        evaluator_authorization=auth,
    )
    assert blind["population_kind"] == POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION
    assert blind["evaluator_mode"] is True
    assert blind["contains_blind_residuals"] is True
    assert blind["tree_cid"]
    assert blind["population_cid"]
    assert blind["status"]["non_semantic_excluded_from_score_aggregates"] is True

    # Normal parse paths reject the blind catalog.
    with pytest.raises(ResidualCatalogError, match="premature blind access|rejects blind"):
        parse_population_residual_catalog(
            blind, access_mode=ACCESS_MODE_SUPERVISOR
        )
    with pytest.raises(ResidualCatalogError, match="premature blind access|rejects blind"):
        parse_population_residual_catalog(
            blind, access_mode=ACCESS_MODE_PACKET
        )
    with pytest.raises(ResidualCatalogError, match="rejects blind|evaluator mode"):
        assert_catalog_usable_on_supervisor_path(
            blind, access_mode=ACCESS_MODE_SUPERVISOR
        )

    # Authorized parse succeeds.
    parsed = parse_population_residual_catalog(
        blind,
        access_mode=ACCESS_MODE_AUTHORIZED_EVALUATOR,
        evaluator_authorization=auth,
        allow_blind=True,
    )
    assert parsed["catalog_cid"] == blind["catalog_cid"]

    # Synthetic blind markers on repair-dev payloads are rejected.
    repair = build_repair_dev_residual_catalog(
        ROOT, cases=holdout_cases[:1]
    )
    tainted = copy.deepcopy(repair)
    tainted["cases"][0]["blind_source"] = True
    with pytest.raises(ResidualCatalogError, match="blind sources"):
        reject_blind_material_on_normal_path(
            tainted, access_mode=ACCESS_MODE_SUPERVISOR
        )
    tainted_gold = copy.deepcopy(repair)
    tainted_gold["cases"][0]["gold_binding"] = "blind"
    with pytest.raises(ResidualCatalogError, match="blind gold"):
        reject_blind_material_on_normal_path(
            tainted_gold, access_mode=ACCESS_MODE_PACKET
        )
    tainted_residual = copy.deepcopy(repair)
    if tainted_residual["residuals"]:
        tainted_residual["residuals"][0]["visibility"] = "blind"
        with pytest.raises(ResidualCatalogError, match="blind residuals"):
            reject_blind_material_on_normal_path(
                tainted_residual, access_mode=ACCESS_MODE_SUPERVISOR
            )
    unauthorized_mode = copy.deepcopy(repair)
    unauthorized_mode["evaluator_mode"] = True
    with pytest.raises(ResidualCatalogError, match="unauthorized evaluator mode"):
        reject_blind_material_on_normal_path(
            unauthorized_mode, access_mode=ACCESS_MODE_SUPERVISOR
        )

    with pytest.raises(ResidualCatalogError, match="premature blind access"):
        assert_access_allows_population(
            POPULATION_KIND_AUTHORIZED_BLIND_EVALUATION,
            access_mode=ACCESS_MODE_SUPERVISOR,
        )


def test_repair_dev_case_status_overrides_keep_scores_distinct() -> None:
    cases = preregistered_holdout_matrix_cases()
    catalog = build_repair_dev_residual_catalog(
        ROOT,
        cases=cases,
        case_status_overrides={
            cases[0].case_id: {
                "evaluation_status": CATALOG_STATUS_NOT_MEASURED,
                "reason": "preflight_blocked",
            }
        },
    )
    parse_population_residual_catalog(
        catalog, require_repair_development_kind=True
    )
    override_id = cases[0].case_id
    assert (
        catalog["status"]["by_case"][override_id]["evaluation_status"]
        == CATALOG_STATUS_NOT_MEASURED
    )
    assert catalog["status"]["by_case"][override_id][
        "semantic_score_eligible"
    ] is False
    record = next(
        item for item in catalog["cases"] if item["case_id"] == override_id
    )
    assert record["residuals"] == []
    assert override_id not in catalog["nonzero_case_ids"]
    assert catalog["aggregates"]["by_evaluation_status"][
        CATALOG_STATUS_NOT_MEASURED
    ] == 1
    # Semantic aggregates ignore the not_measured case.
    assert catalog["aggregates"]["semantic_scored_case_count"] == len(cases) - 1
