from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_family_complete_training as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel
from ipfs_datasets_py.logic.formalization.autoencoder import complete_training as public


def rows(domain, split):
    return [{**{key: row[key] for key in ("source_id", "group_id", "split")},
             "inputs": panel.source_inputs(row)} for row in panel.rows(domain, split)[:2]]


@pytest.mark.parametrize("domain,count", [("intent_ir", 15), ("security_ir", 9), ("ui_ux_ir", 8), ("legal_ir", 6)])
def test_actual_domain_routes_are_explicit(domain, count):
    assert len(subject.native_family_ids(domain)) == count
    assert "temporal" in subject.native_family_ids(domain)


def test_complete_recipe_reconstructs_native_targets_and_rejects_artifact_drift(tmp_path):
    training, tuning = rows("legal_ir", "train"), rows("legal_ir", "validation")
    result = public.train_native_families("legal_ir", training, tuning,
        output_dir=tmp_path / "fit", required_families=("deontic", "tdfol", "frame_logic"))
    assert result["numerical_report"]["training_atoms_pruned"] == 0
    report = public.reconstruct_native_families(result["descriptor"], tuning)
    assert report["training_steps"] == 0 and report["formulas_generated"] is False
    target = Path(result["descriptor"]["path"]).parent / "targets.json"
    target.write_text("{}")
    with pytest.raises(ValueError, match="native targets changed"):
        subject.load_domain_complete_family_recipe(result["descriptor"])


def test_group_overlap_rejected_before_output_or_optimization(tmp_path, monkeypatch):
    training, tuning = rows("legal_ir", "train"), rows("legal_ir", "validation")
    tuning[0]["group_id"] = training[0]["group_id"]
    def forbidden(*args, **kwargs):
        pytest.fail("optimization happened before source split checks")
    monkeypatch.setattr(subject.numerical, "train_complete_family_autoencoder", forbidden)
    with pytest.raises(ValueError, match="groups leakage"):
        subject.train_domain_complete_family_autoencoder("legal_ir", training, tuning, output_dir=tmp_path / "fit")
    assert not (tmp_path / "fit").exists()


@pytest.mark.parametrize("split", ["test", "canary"])
def test_holdouts_cannot_be_relabelled_as_tuning_role(tmp_path, split):
    tuning = rows("legal_ir", "validation")
    tuning[0]["split"] = split
    with pytest.raises(ValueError, match="test/canary"):
        subject.train_domain_complete_family_autoencoder("legal_ir", rows("legal_ir", "train"), tuning,
                                                        output_dir=tmp_path / "fit")


def test_missing_native_models_fail_complete_family_policy(tmp_path):
    with pytest.raises(ValueError, match="required family"):
        subject.train_domain_complete_family_autoencoder("legal_ir", rows("legal_ir", "train"),
            rows("legal_ir", "validation"), output_dir=tmp_path / "fit", require_all_native_families=True)
    assert not (tmp_path / "fit").exists()


def test_specialized_catalog_entry_is_not_automatically_a_domain_target(tmp_path):
    with pytest.raises(ValueError, match="no native domain route"):
        subject.train_domain_complete_family_autoencoder("legal_ir", [], [], output_dir=tmp_path / "fit",
                                                         required_families=("cryptographic_protocol",))


@pytest.fixture(scope="module")
def complete_panel():
    import importlib.util
    path = Path(__file__).resolve().parents[3] / "fixtures/logic/complete_family_panel_v1/full_family_panel.py"
    spec = importlib.util.spec_from_file_location("complete_family_facade_test_panel", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def complete_rows(fixture, domain, split):
    return [{**{key: row[key] for key in ("source_id", "group_id", "split")},
             "inputs": fixture.source_inputs(row)} for row in fixture.base.rows(domain, split)[:2]]


@pytest.mark.parametrize("domain", panel.DOMAINS)
def test_public_api_trains_every_native_domain_route(tmp_path, complete_panel, domain):
    train, tuning = [complete_rows(complete_panel, domain, split) for split in ("train", "validation")]
    result = public.train_native_families(domain, train, tuning,
        output_dir=tmp_path / domain, require_all_native_families=True)
    assert set(result["numerical_report"]["trained_logic_families"]) == set(subject.native_family_ids(domain))
    assert result["numerical_report"]["training_atoms_pruned"] == 0
    assert result["report"]["source_semantics_verified"] is False
    inference = public.reconstruct_native_families(result["descriptor"], tuning)
    assert set(inference["families"]) == set(subject.native_family_ids(domain))


def test_typed_intent_document_cannot_rebind_unrelated_source(tmp_path, complete_panel):
    train = complete_rows(complete_panel, "intent_ir", "train")
    train[0]["inputs"]["source_text"] += " Unrelated replacement."
    with pytest.raises(ValueError, match="exact supplied text"):
        public.train_native_families("intent_ir", train, complete_rows(complete_panel, "intent_ir", "validation"),
                                    output_dir=tmp_path / "fit", require_all_native_families=True)
    assert not (tmp_path / "fit").exists()
