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
    BASELINE_ARM_ID,
    DEFAULT_CATALOG_RELATIVE_PATH,
    NONZERO_PILOT_CASE_IDS,
    PILOT_CASE_IDS,
    PLATEAU_RESIDUAL_CATALOG_INTERFACE,
    PLATEAU_RESIDUAL_CATALOG_SCHEMA,
    ZERO_RESIDUAL_CONTROL_CASE_ID,
    CaseResidualRecord,
    ResidualCatalogError,
    ResidualFacet,
    aggregate_residuals,
    build_case_residual,
    compute_facet_residuals,
    load_plateau_residual_catalog,
    parse_plateau_residual_catalog,
    suggest_trigger_kind,
    write_plateau_residual_catalog,
)
from benchmarks.semantic_roundtrip.selective_repair import RepairTriggerKind


ROOT = Path(__file__).resolve().parents[4]
CATALOG_PATH = ROOT / DEFAULT_CATALOG_RELATIVE_PATH


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
