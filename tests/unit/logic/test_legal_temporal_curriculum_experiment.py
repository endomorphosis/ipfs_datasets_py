"""Retention selection, source inventories and sealed-target I/O boundaries."""
import json

import pytest

from scripts.ops.legal_ir import run_legal_temporal_curriculum_experiment as runner


def stage(steps, earlier, newer, temporal=50):
    return {"steps": steps, "tuning_earlier_exact": earlier, "tuning_prior_new_exact": newer, "tuning_temporal_exact": temporal}


def test_gate_rejects_better_new_score_when_retention_fails():
    a, b = stage(400, 95, 60), stage(800, 94, 90)
    assert runner.select_retained_stage([a, b], 96) == a


def test_gate_boundary_admits_one_lost_row_but_not_two():
    assert runner.select_retained_stage([stage(400, 95, 1)], 96) is not None
    assert runner.select_retained_stage([stage(400, 94, 96)], 96) is None


def test_selection_orders_new_then_old_then_earliest():
    a, b = stage(400, 96, 60), stage(800, 95, 61)
    assert runner.select_retained_stage([a, b], 96) == b
    b["tuning_prior_new_exact"] = 60
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
    from types import SimpleNamespace
    from scripts.ops import legal_ir as package
    # The runner boundary is exercised with a controlled loader. Sealed target
    # files deliberately do not exist, so any target I/O fails this fixture.
    corpus = SimpleNamespace(load_training_inputs=None)
    monkeypatch.setattr(package, "prepare_legal_temporal_curriculum", corpus, raising=False)
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
    earlier,newer,temporal,fresh=rows("tune-old",96,"earlier"),rows("tune-new",96,"new"),rows("tune-temporal",120,"new"),rows("fresh",180)
    training={"baseline":train,"temporal_augmented":train+rows("temporal-fit",600,"new")}
    manifest={"artifacts":{"challenge_targets":sealed("fresh-targets.json")}}
    parent_ref=sealed("parent.json")
    cfg={"schema":"legal-temporal-curriculum-run-config/v1","corpus_manifest":put("manifest.json",manifest),
        "parent_heads":put("parents.json",[{"arm":"source_only","seed":s,"checkpoint":parent_ref} for s in runner.SEEDS]),
        "earlier_regression_sources":put("old-sources.json",{"challenge":rows("reg-old",192)}),
        "exposed_regression_sources":put("exposed-sources.json",rows("reg-new",150)),
        "earlier_regression_targets":sealed("old-targets.json"),"exposed_regression_targets":sealed("new-targets.json"),
        "mixed_regression_sources":put("mixed-sources.json",rows("reg-mixed",144)),
        "mixed_regression_targets":sealed("mixed-targets.json"),
        "baseline_reference_heads":put("baseline-heads.json",[{"name":f"mixed_{architecture}-{seed}",
            "seed":seed,"parent":parent_ref,"stages":[{"steps":steps,"checkpoint":parent_ref} for steps in (400,800)]}
            for architecture in ("continuation","grounding") for seed in runner.SEEDS]),
        "prior_curriculum_design":put("prior-design.json",{}),"producer_files":[]}
    path=tmp_path/"config.json"
    path.write_text(json.dumps(cfg))
    monkeypatch.setattr(corpus,"load_training_inputs",lambda _: {"manifest":manifest,"training":training,
        "tuning":{"earlier":earlier,"prior_new":newer,"temporal":temporal},"fresh_sources":fresh})
    return path,cfg,train,earlier,newer,fresh


def test_loader_keeps_tuning_domains_separate_and_never_reads_targets(inputs):
    path,cfg,*_ = inputs
    actual=runner.load_config(path)
    assert [len(actual["sources"][p]) for p in runner.NORMAL_PANELS]==[96,96,120,180,192,150,144]
    assert len(actual["training"]["baseline"])==1752
    assert len(actual["training"]["temporal_augmented"])==2352
    assert set(actual["tuning"])=={"earlier","prior_new","temporal"}
    assert all(set(r)=={"id","source_text","source_sha256"} for rows in actual["sources"].values() for r in rows)
    # None of the four sealed target files exists: any attempted read fails.
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


def test_temporal_score_precedes_prior_new_score_then_earlier_and_step():
    earlier = stage(400, 96, 96, 49)
    temporal = stage(800, 95, 0, 50)
    assert runner.select_retained_stage([earlier, temporal], 96) == temporal
    temporal["tuning_temporal_exact"] = 49
    assert runner.select_retained_stage([earlier, temporal], 96) == earlier
    temporal["tuning_prior_new_exact"] = 96
    assert runner.select_retained_stage([earlier, temporal], 96) == earlier
    temporal["tuning_earlier_exact"] = 96
    assert runner.select_retained_stage([temporal, earlier], 96) == earlier


@pytest.mark.parametrize("bad", [-1, 121, True, 1.5])
def test_temporal_score_requires_integer_count_with_correct_denominator(bad):
    with pytest.raises(ValueError, match="valid tuning"):
        runner.select_retained_stage([stage(400, 96, 96, bad)], 96)


def test_gate_does_not_admit_high_temporal_score_when_earlier_retention_fails():
    assert runner.select_retained_stage([stage(400, 94, 96, 120)], 96) is None


def test_arm_inventory_is_full_architecture_by_curriculum_factorial():
    assert len(runner.ARMS) == 4
    assert {(value["curriculum"], value["architecture"]) for value in runner.ARMS.values()} == {
        (curriculum, architecture) for curriculum in ("baseline", "temporal_augmented")
        for architecture in ("continuation", "grounding")}
    assert all(value["enabled"] is (value["architecture"] == "grounding") for value in runner.ARMS.values())


def numerical_checkpoint():
    return {"source_parent_checkpoint_sha256": "parent", "config": {"loss": "unchanged"},
        "training_manifest_sha256": "fit-data", "model_state": {"a": [0.5]},
        "optimizer_state": {"moments": [0.25]}, "progress": {"optimizer_steps": 800}, "tuning_manifest_sha256": "prior"}


def test_baseline_numerical_reproduction_allows_only_metadata_differences():
    from copy import deepcopy
    before = numerical_checkpoint()
    after = deepcopy(before)
    after["tuning_manifest_sha256"] = "expanded-tuning"
    verified = runner.verify_baseline_reproduction(after, before)
    assert verified["model_state_exact"] and verified["optimizer_moments_exact"] and verified["sampler_progress_exact"]
    assert verified["target_access"] is False


@pytest.mark.parametrize("field", ["model_state", "optimizer_state", "progress", "config",
    "source_parent_checkpoint_sha256", "training_manifest_sha256"])
def test_baseline_reproduction_rejects_numerical_or_fit_lineage_changes(field):
    from copy import deepcopy
    before = numerical_checkpoint()
    after = deepcopy(before)
    after[field] = "changed"
    with pytest.raises(ValueError, match="baseline"):
        runner.verify_baseline_reproduction(after, before)
