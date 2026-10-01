"""Intent native targets and shared facade preserve heads, history and splits."""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import intent_family_training_v2 as api
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_family_training_prepared as common
from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar as grammar
from .test_domain_family_training_v2 import _rows as other_rows


def row(identity, split, text):
    return dict(source_id=identity, group_id="group:"+identity, split=split,
                inputs={"document": grammar.parse_instruction(text), "source_text": text})


def rows():
    return ([row("one", "train", "Save ledger."), row("two", "train", "View report.")],
            [row("three", "validation", "Save report."), row("four", "validation", "View ledger.")],
            [row("five", "test", "Run ledger.")])


def fit(path, **kwargs):
    training, tuning, _ = rows()
    return api.train_intent_family_autoencoder_v2(training, tuning, output_dir=path,
        epochs=2, latent_width=2, minibatch_size=1, max_seconds=60, **kwargs)


@pytest.mark.parametrize("backend", ["v2", "prepared"])
def test_actual_intent_native_train_reload_infer_and_domain_specific_heads(tmp_path, backend):
    result = fit(tmp_path / backend, numerical_backend=backend)
    report = result["report"]
    assert report["status"] == "complete", report["family_error"]
    assert report["family_training_report"]["optimizer_steps"] > 0
    assert report["family_training_report"]["trained_logic_families"]
    assert api._read(result["descriptor"]) == report
    before = Path(report["family_descriptor"]["path"]).read_bytes()
    inference = api.infer_intent_family_autoencoder_v2(result["descriptor"], rows()[2])
    assert inference["domain_id"] == "intent_ir" and inference["training_steps"] == 0
    assert len(inference["native_inference"]["latent"]) == 1
    assert before == Path(report["family_descriptor"]["path"]).read_bytes()
    for key in api.FALSE:
        assert report[key] is inference[key] is False
    assert report["source_stage"] == "not_requested"
    assert not report["source_model_reinitialized"]


@pytest.mark.parametrize("domain", ["security_ir", "ui_ux_ir", "legal_ir"])
def test_common_facade_preserves_other_native_domain_owners(tmp_path, domain):
    training, tuning, test = other_rows(domain)
    result = common.train_domain_family_autoencoder(domain, training, tuning,
        output_dir=tmp_path/domain, numerical_backend="prepared", epochs=1, latent_width=2, max_seconds=60)
    assert result["report"]["status"] == "complete", result["report"]["family_error"]
    assert common.load_domain_family_recipe(result["descriptor"]) == result["report"]
    inferred = common.infer_domain_family_autoencoder(result["descriptor"], test)
    assert inferred["domain_id"] == domain and not inferred["source_training_executed"]
    with pytest.raises(ValueError, match="domain checkpoint identity"):
        api.infer_intent_family_autoencoder_v2(result["descriptor"], rows()[2])


@pytest.mark.parametrize("kind", ["group", "content", "tokenized", "complete_ast", "test_role"])
def test_split_aliases_fail_before_optimizer_and_output(tmp_path, monkeypatch, kind):
    training, tuning, _ = rows()
    if kind == "group":
        tuning[0]["group_id"] = training[0]["group_id"]
    elif kind == "content":
        tuning[0]["inputs"] = deepcopy(training[0]["inputs"])
    elif kind == "tokenized":
        tuning[0]["inputs"]["source_text"] = "Save   ledger."
        tuning[0]["inputs"]["document"] = grammar.parse_instruction("Save   ledger.")
    elif kind == "complete_ast":
        training[0] = row("one", "train", "Do not save ledger.")
        tuning[0] = row("three", "validation", "Never save ledger.")
    else:
        training[0]["split"] = "test"
    monkeypatch.setattr(api.numerical, "train_family_projection_autoencoder_v2",
                        lambda *a, **kw: pytest.fail("unsafe split reached fitting"))
    with pytest.raises(ValueError, match="leakage|test/canary"):
        api.train_intent_family_autoencoder_v2(training, tuning, output_dir=tmp_path/"bad")
    assert not (tmp_path/"bad").exists()


def test_known_atoms_can_recur_in_distinct_compounds_without_being_aliases():
    training = [row("and", "train", "Save ledger and view report.")]
    tuning = [row("then", "validation", "Save ledger then view report.")]
    train = api.prepare_intent_family_rows_v2(training)
    validation = api.prepare_intent_family_rows_v2(tuning, role="validation")
    api.common._exclude(train["inventory"], validation["inventory"])
    assert train["inventory"]["complete_semantic_targets"] != validation["inventory"]["complete_semantic_targets"]


def test_native_source_mismatch_and_unknown_inputs_fail_closed(tmp_path):
    training, tuning, _ = rows()
    training[0]["inputs"]["document"]["action"] = "publish"
    with pytest.raises(ValueError, match="complete source agreement"):
        api.train_intent_family_autoencoder_v2(training, tuning, output_dir=tmp_path/"bad")
    assert not (tmp_path/"bad").exists()
    training, _, _ = rows()
    training[0]["inputs"]["made_up_family"] = "verified"
    with pytest.raises(ValueError, match="input fields differ"):
        api.prepare_intent_family_rows_v2(training)


def test_actual_continuation_preserves_fixed_tuning_history_and_parent_bytes(tmp_path):
    parent = fit(tmp_path/"parent")
    assert parent["report"]["status"] == "complete"
    parent_path = Path(parent["report"]["family_descriptor"]["path"])
    before = parent_path.read_bytes()
    child = fit(tmp_path/"child", parent_descriptor=parent["descriptor"])
    assert child["report"]["status"] == "complete", child["report"]["family_error"]
    assert child["report"]["family_training_report"]["initialization"] == "complete_parent_structural_head"
    assert child["report"]["training_history"] == parent["report"]["training_history"]
    assert parent_path.read_bytes() == before
    training, tuning, _ = rows()
    tuning[0] = row("changed", "validation", "Fetch report.")
    with pytest.raises(ValueError, match="fixed Intent validation panel"):
        api.train_intent_family_autoencoder_v2(training, tuning, output_dir=tmp_path/"changed",
                                               parent_descriptor=parent["descriptor"])
    with pytest.raises(ValueError, match="numerical backend differs"):
        fit(tmp_path/"backend", parent_descriptor=parent["descriptor"], numerical_backend="prepared")


def test_partial_failure_keeps_target_evidence_and_no_source_stage(tmp_path, monkeypatch):
    def fail(*a, **kw):
        raise RuntimeError("controlled numerical failure")
    monkeypatch.setattr(api.numerical, "train_family_projection_autoencoder_v2", fail)
    result = fit(tmp_path/"failed")
    report = result["report"]
    assert report["status"] == "partial" and report["family_descriptor"] is None
    assert report["family_error"] == {"type": "RuntimeError", "message": "controlled numerical failure"}
    assert api._read(result["descriptor"]) == report
    assert (tmp_path/"failed/targets.json").exists()
    with pytest.raises(ValueError, match="complete Intent native family stage"):
        api.infer_intent_family_autoencoder_v2(result["descriptor"], rows()[2])


def test_checkpoint_or_target_drift_rejected(tmp_path):
    result = fit(tmp_path/"saved")
    path = tmp_path/"saved/targets.json"
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValueError, match="target artifact drift"):
        api._read(result["descriptor"])


def test_import_time_producer_guard_prevents_stale_code_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_identity", lambda path: ())
    with pytest.raises(ValueError, match="producer changed since import"):
        fit(tmp_path/"source_changed")
    assert not (tmp_path/"source_changed").exists()


def test_unknown_backend_and_source_stage_settings_are_never_silently_ignored(tmp_path):
    with pytest.raises(ValueError, match="supported numerical_backend"):
        fit(tmp_path/"unknown", numerical_backend="cuda")
    training, tuning, _ = other_rows("security_ir")
    with pytest.raises(ValueError, match="unknown numerical family setting"):
        common.train_domain_family_autoencoder("security_ir", training, tuning,
            output_dir=tmp_path/"source", source_samples=[])
    assert not (tmp_path/"source").exists()


def test_existing_output_is_never_overwritten(tmp_path):
    existing = tmp_path / "retained"
    existing.mkdir()
    marker = existing / "evidence.json"
    marker.write_text("retained")
    with pytest.raises(ValueError, match="fresh canonical Intent output"):
        fit(existing)
    assert marker.read_text() == "retained"
