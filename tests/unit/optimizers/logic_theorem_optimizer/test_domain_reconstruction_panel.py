"""Partition provenance and actual native development targets for all domains."""
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel


@pytest.mark.parametrize("domain", panel.DOMAINS)
def test_pairs_variants_and_complete_sources_do_not_leak(domain):
    partitions = {split: panel.rows(domain, split) for split in ("train", "validation", "test")}
    assert [len(partitions[s]) for s in partitions] == [24, 8, 8]
    groups = {split: {row["group_id"] for row in rows} for split, rows in partitions.items()}
    assert not groups["train"] & groups["validation"]
    assert not groups["train"] & groups["test"]
    assert not groups["validation"] & groups["test"]
    for split, rows in partitions.items():
        for group in groups[split]:
            assert {row["variant"] for row in rows if row["group_id"] == group} == {0, 1}
    assert len({row["source_id"] for rows in partitions.values() for row in rows}) == 40
    assert {row["actor"] for row in partitions["train"]} == set(range(4))
    assert {row["action"] for row in partitions["train"]} == set(range(5))


@pytest.mark.parametrize("domain", panel.DOMAINS)
def test_actual_development_targets_inventory_all_families_without_authority(domain):
    from ipfs_datasets_py.logic.formalization.autoencoder.family_training_v2 import prepare_family_training_targets_v2, validate_family_training_report_v2
    inputs = panel.source_inputs(panel.rows(domain, "train")[0])
    report = prepare_family_training_targets_v2(domain, **inputs)
    assert validate_family_training_report_v2(report, **inputs) == report
    assert len(report["family_inventory"]) == 40
    ready = {row["logic_family"] for row in report["projections"] if row["ready_for_training"]}
    expected = {"intent_ir": {"deontic", "dcec", "tdfol", "first_order", "frame_logic"},
        "security_ir": {"program", "temporal", "transition_system", "hyperproperty", "separation_logic"},
        "ui_ux_ir": {"dcec", "tdfol", "frame_logic", "event_calculus", "temporal", "transition_system"},
        "legal_ir": {"deontic", "frame_logic", "tdfol"}}
    assert ready >= expected[domain]
    assert not report["all_requested_families_available"]
    assert not report["source_semantics_verified"]
    assert report["provider_calls"] == report["external_backend_calls"] == 0


def test_preparation_never_builds_other_partitions(monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v2
    observed = []
    monkeypatch.setattr(panel, "source_inputs", lambda row: observed.append(row) or {})
    monkeypatch.setattr(family_training_v2, "prepare_family_training_targets_v2", lambda domain, **kw: domain)
    assert len(panel.prepare_partition("legal_ir", "train")) == 24
    assert {row["split"] for row in observed} == {"train"}


def test_source_specification_cannot_be_silently_changed():
    row = panel.rows("legal_ir", "train")[0]
    row["variant"] = 9
    with pytest.raises(ValueError, match="exact authored"):
        panel.source_inputs(row)


def test_manifest_returns_owned_values():
    before = panel.digest(panel.manifest())
    panel.manifest()["rows"][0]["actor"] = 9
    assert before == panel.digest(panel.manifest())
