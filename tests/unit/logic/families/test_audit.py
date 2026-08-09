"""Contract tests for LogicFamilyAudit@1 family-label audit tooling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.families.audit import (
    AUDIT_INTERFACE,
    AUDIT_SCHEMA_VERSION,
    DEFAULT_AUDIT_ROOTS,
    DriftSeverity,
    FamilyLabelKind,
    assert_never_semantic_family,
    audit_family_labels,
    baseline_audit_dict,
    catalog_observations,
    classify_label,
    collect_observations,
    default_baseline_report_path,
    ensure_baseline_report,
    load_audit_report,
    render_audit_report,
    write_audit_report,
)
from ipfs_datasets_py.logic.families.registry import DEFAULT_REGISTRY


def test_classify_canonical_family_and_alias() -> None:
    canonical = classify_label("first_order")
    assert canonical.kind is FamilyLabelKind.CANONICAL_FAMILY
    assert canonical.canonical_family_id == "first_order"
    assert canonical.is_semantic_family is True

    alias = classify_label("fol")
    assert alias.kind is FamilyLabelKind.ALIAS
    assert alias.canonical_family_id == "first_order"
    assert alias.is_semantic_family is True

    # Registry aliases normalize to the family id when they already match it
    # (e.g. "Horn/CHC" -> horn_chc); non-identical aliases stay typed as alias.
    chc = classify_label("CHC")
    assert chc.kind is FamilyLabelKind.ALIAS
    assert chc.canonical_family_id == "horn_chc"
    assert classify_label("Horn/CHC").kind is FamilyLabelKind.CANONICAL_FAMILY


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("safety", FamilyLabelKind.PROPERTY),
        ("liveness", FamilyLabelKind.PROPERTY),
        ("noninterference", FamilyLabelKind.PROPERTY),
        ("verification_condition", FamilyLabelKind.VIEW),
        ("security_verification_condition", FamilyLabelKind.VIEW),
        ("vc", FamilyLabelKind.VIEW),
        ("graph_projection", FamilyLabelKind.VIEW),
        ("intention_deontic", FamilyLabelKind.VIEW),
        ("smt", FamilyLabelKind.NOTATION),
        ("smtlib2", FamilyLabelKind.NOTATION),
        ("pv", FamilyLabelKind.NOTATION),
        ("spthy", FamilyLabelKind.NOTATION),
        ("tla_plus", FamilyLabelKind.PROFILE),
        ("hyperltl", FamilyLabelKind.PROFILE),
        ("first_order_temporal", FamilyLabelKind.PROFILE),
        ("z3", FamilyLabelKind.PROVIDER),
        ("lean", FamilyLabelKind.PROVIDER),
        ("rocq", FamilyLabelKind.PROVIDER),
        ("isabelle", FamilyLabelKind.PROVIDER),
        ("proverif", FamilyLabelKind.PROVIDER),
        ("tamarin", FamilyLabelKind.PROVIDER),
        ("temporal-monitor", FamilyLabelKind.PROVIDER),
        ("runtime", FamilyLabelKind.LANE),
        ("software_verification", FamilyLabelKind.LANE),
        ("checked_proof", FamilyLabelKind.EVIDENCE_KIND),
    ],
)
def test_non_family_labels_never_become_semantic_families(
    label: str, kind: FamilyLabelKind
) -> None:
    classification = assert_never_semantic_family(label)
    assert classification.kind is kind
    assert classification.is_semantic_family is False


def test_unknown_label_is_preserved_with_unknown_disposition() -> None:
    classification = classify_label("totally_unregistered_family_xyz")
    assert classification.kind is FamilyLabelKind.UNKNOWN
    assert classification.is_semantic_family is False
    assert classification.severity is DriftSeverity.WARNING


def test_collect_observations_covers_configured_roots_without_imports() -> None:
    observations = collect_observations(roots=DEFAULT_AUDIT_ROOTS)
    assert observations
    roots_seen = {item.root for item in observations}
    assert "catalog" in roots_seen
    assert "logic/backends" in roots_seen or any(
        "backends" in item.source for item in observations
    )
    labels = {item.label for item in observations}
    # Catalog always contributes plan migration labels; scans add live drift.
    assert {"smt", "software_verification", "safety", "lean"} <= labels


def test_audit_report_is_deterministic_and_reports_drift() -> None:
    first = audit_family_labels(scan_roots=True)
    second = audit_family_labels(scan_roots=True)
    assert first.to_dict() == second.to_dict()
    assert first.interface == AUDIT_INTERFACE
    assert first.schema_version == AUDIT_SCHEMA_VERSION
    assert set(first.canonical_family_ids) == set(DEFAULT_REGISTRY.families)
    assert first.summary["drift_count"] == len(first.drift)
    assert first.summary["semantic_family_misuse_count"] == 0
    assert first.summary["semantic_family_misuses"] == []

    kinds = {row["kind"] for row in first.drift}
    assert {"provider", "notation", "property", "view", "lane"} & kinds
    by_label = {row["observed"]: row for row in first.drift}
    for forbidden in ("safety", "liveness", "z3", "lean", "verification_condition"):
        assert forbidden in by_label
        assert by_label[forbidden]["kind"] != FamilyLabelKind.CANONICAL_FAMILY.value


def test_render_and_write_baseline_report(tmp_path: Path) -> None:
    report = audit_family_labels(
        observations=catalog_observations(),
        scan_roots=False,
    )
    rendered = render_audit_report(report)
    payload = json.loads(rendered)
    assert payload["interface"] == AUDIT_INTERFACE
    assert payload["schema_version"] == AUDIT_SCHEMA_VERSION
    assert "classifications" in payload
    assert "drift" in payload

    target = tmp_path / "family_label_audit.json"
    written = write_audit_report(report, target)
    assert written == target
    loaded = load_audit_report(target)
    assert loaded == payload

    baseline_target = tmp_path / "configured_root_family_label_audit.json"
    ensured = ensure_baseline_report(baseline_target)
    assert ensured == baseline_target
    assert load_audit_report(ensured) == baseline_audit_dict()


def test_checked_in_baseline_report_is_valid_and_current() -> None:
    path = default_baseline_report_path()
    original_bytes = path.read_bytes()
    live = baseline_audit_dict()
    on_disk = load_audit_report(path)

    assert path == default_baseline_report_path()
    assert on_disk["interface"] == AUDIT_INTERFACE
    assert on_disk["schema_version"] == AUDIT_SCHEMA_VERSION
    assert on_disk["report_version"] == live["report_version"]
    assert on_disk["canonical_family_ids"] == sorted(DEFAULT_REGISTRY.families)
    assert on_disk["roots"] == list(DEFAULT_AUDIT_ROOTS)
    assert on_disk["summary"]["scanned_roots"] == list(DEFAULT_AUDIT_ROOTS)
    assert on_disk["summary"]["observation_count"] > len(catalog_observations())
    assert on_disk["summary"]["semantic_family_misuse_count"] == 0
    observed_roots = {item["root"] for item in on_disk["observations"]}
    assert set(DEFAULT_AUDIT_ROOTS) <= observed_roots
    assert on_disk["classifications"] == live["classifications"]
    assert on_disk["drift"] == live["drift"]
    assert on_disk == live
    assert path.read_bytes() == original_bytes

    disk_by_observed = {
        item["observed"]: item for item in on_disk["classifications"]
    }
    drift_by_observed = {item["observed"]: item for item in on_disk["drift"]}
    assert "logic/backends/z3/compiler.py" in drift_by_observed[
        "first_order_temporal"
    ]["sources"]
    assert "logic/security_ir/formalization_adapter.py" in drift_by_observed[
        "security_verification_condition"
    ]["sources"]
    assert "logic/security_ir/solidity_cpt_top10/evaluation.py" in (
        drift_by_observed["family:corrupt"]["sources"]
    )
    for label in (
        "safety",
        "liveness",
        "z3",
        "lean",
        "verification_condition",
        "graph_projection",
        "runtime",
        "smt",
        "proverif",
        "noninterference",
        "security_verification_condition",
        "safety_liveness",
        "first_order_temporal",
        "pv",
        "spthy",
        "temporal-monitor",
    ):
        assert disk_by_observed[label]["is_semantic_family"] is False
        assert disk_by_observed[label]["kind"] != FamilyLabelKind.CANONICAL_FAMILY.value
        assert classify_label(label).is_semantic_family is False


def test_registry_fragments_and_properties_classify_as_non_family() -> None:
    assert classify_label("linear_time").kind is FamilyLabelKind.PROFILE
    assert classify_label("heap").kind is FamilyLabelKind.PROFILE
    property_label = classify_label("authorization")
    # authorization is both a property and a canonical family id; family wins.
    assert property_label.kind is FamilyLabelKind.CANONICAL_FAMILY
    assert classify_label("data_race_freedom").kind is FamilyLabelKind.PROPERTY


def test_catalog_audit_reports_known_drift_without_root_scan() -> None:
    report = audit_family_labels(
        scan_roots=False,
        observations=catalog_observations(),
    )
    assert report.summary["semantic_family_misuse_count"] == 0
    observed = {item.observed for item in report.classifications}
    assert "first_order" in observed
    assert "smt" in observed
    assert "z3" in observed
    kinds = {item.kind for item in report.classifications}
    assert FamilyLabelKind.CANONICAL_FAMILY in kinds
    assert FamilyLabelKind.PROVIDER in kinds
    assert FamilyLabelKind.NOTATION in kinds
