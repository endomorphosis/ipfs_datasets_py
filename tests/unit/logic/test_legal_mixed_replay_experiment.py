"""Retention selection, source inventories and sealed-target I/O boundaries."""
import json

import pytest

from scripts.ops.legal_ir import run_legal_mixed_replay_experiment as runner


def stage(steps, earlier, newer):
    return {"steps": steps, "tuning_earlier_exact": earlier, "tuning_new_exact": newer}


def test_gate_rejects_better_new_score_when_retention_fails():
    a, b = stage(400, 95, 60), stage(800, 94, 90)
    assert runner.select_retained_stage([a, b], 96) == a


def test_gate_boundary_admits_one_lost_row_but_not_two():
    assert runner.select_retained_stage([stage(400, 95, 1)], 96) is not None
    assert runner.select_retained_stage([stage(400, 94, 96)], 96) is None


def test_selection_orders_new_then_old_then_earliest():
    a, b = stage(400, 96, 60), stage(800, 95, 61)
    assert runner.select_retained_stage([a, b], 96) == b
    b["tuning_new_exact"] = 60
    assert runner.select_retained_stage([a, b], 96) == a
    b["tuning_earlier_exact"] = 96
    assert runner.select_retained_stage([b, a], 96) == a


def test_complete_gate_failure_falls_back_without_ranking_failed_stages():
    assert runner.select_retained_stage([stage(400, 70, 96), stage(800, 93, 95)], 96) is None


@pytest.mark.parametrize("stages,parent", [([],96),([stage(400,97,10)],96),([stage(400,95,-1)],96),
    ([stage(400,95,10),stage(400,95,11)],96),([stage(400,95,10)],True),([stage(-1,95,10)],96)])
def test_selection_rejects_invalid_or_duplicate_counts(stages, parent):
    with pytest.raises(ValueError):
        runner.select_retained_stage(stages, parent)


def test_sealed_metadata_validation_does_not_open_a_file(tmp_path):
    reference = {"path":str(tmp_path / "sealed-missing.json"),"sha256":"f"*64,"bytes":100}
    runner.target_metadata(reference)
    assert not (tmp_path / "sealed-missing.json").exists()
    with pytest.raises(ValueError):
        runner.target_metadata({**reference,"sha256":"z"*64})


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    from scripts.ops.legal_ir import prepare_legal_mixed_replay_corpus as corpus
    def rows(prefix, count, domain=None):
        return [{"id":f"{prefix}-{i}","source_text":f"{prefix} source {i}", **({"domain":domain} if domain else {})}
                for i in range(count)]
    def put(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return runner.ref(path)
    def sealed(name):
        return {"path":str(tmp_path/name),"sha256":"e"*64,"bytes":10}
    train=rows("train-old",1152,"earlier")+rows("train-new",600,"new")
    earlier,newer,fresh=rows("tune-old",96,"earlier"),rows("tune-new",96,"new"),rows("fresh",144)
    manifest={"artifacts":{"challenge_targets":sealed("fresh-targets.json")}}
    parent_ref=sealed("parent.json")
    cfg={"schema":"legal-mixed-replay-run-config/v1","corpus_manifest":put("manifest.json",manifest),
        "parent_heads":put("parents.json",[{"arm":"source_only","seed":s,"checkpoint":parent_ref} for s in runner.SEEDS]),
        "earlier_regression_sources":put("old-sources.json",{"challenge":rows("reg-old",192)}),
        "exposed_regression_sources":put("exposed-sources.json",rows("reg-new",150)),
        "earlier_regression_targets":sealed("old-targets.json"),"exposed_regression_targets":sealed("new-targets.json"),
        "prior_replay_design":put("prior-design.json",{}),"producer_files":[]}
    path=tmp_path/"config.json"
    path.write_text(json.dumps(cfg))
    monkeypatch.setattr(corpus,"load_training_inputs",lambda _: (manifest,train,earlier,newer,fresh))
    return path,cfg,train,earlier,newer,fresh


def test_loader_keeps_tuning_domains_separate_and_never_reads_targets(inputs):
    path,cfg,*_ = inputs
    actual=runner.load_config(path)
    assert [len(actual["sources"][p]) for p in runner.NORMAL_PANELS]==[96,96,144,192,150]
    assert len(actual["training"])==1752
    assert set(actual["tuning"])=={"earlier","new"}
    assert all(set(r)=={"id","source_text","source_sha256"} for rows in actual["sources"].values() for r in rows)
    # None of the three sealed target files exists: any attempted read fails.
    assert actual["manifest"]["artifacts"]["challenge_targets"]["bytes"]==10


def test_loader_rejects_training_evaluation_source_overlap(inputs):
    path,cfg,train,earlier,newer,fresh=inputs
    fresh[0]["source_text"]=train[0]["source_text"]
    with pytest.raises(ValueError,match="overlap"):
        runner.load_config(path)


def test_loader_rejects_challenge_reference_fields(inputs):
    path,cfg,train,earlier,newer,fresh=inputs
    fresh[0]["canonical_ir"]={}
    with pytest.raises(ValueError,match="contain targets"):
        runner.load_config(path)


def test_loader_rejects_domain_relabelling(inputs):
    path,cfg,train,earlier,newer,fresh=inputs
    train[0]["domain"]="new"
    with pytest.raises(ValueError,match="training inventory"):
        runner.load_config(path)


def test_loader_rejects_duplicate_parent_seed(inputs):
    path,cfg,*_=inputs
    heads=runner.read_ref(cfg["parent_heads"])
    heads[0]["seed"]=heads[1]["seed"]
    parent_path=cfg["parent_heads"]["path"]
    from pathlib import Path
    Path(parent_path).write_text(json.dumps(heads))
    cfg["parent_heads"]=runner.ref(parent_path)
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match="unique original parent"):
        runner.load_config(path)
