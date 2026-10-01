"""Fast orchestration/guard tests; doubles never establish neural or Lake fidelity."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/compare_formula_training_augmentation.py"
    spec = importlib.util.spec_from_file_location("augmentation_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(runner):
    return {"optimizer_steps": runner.STEPS, "stopped_reason": "optimizer_step_budget",
            "training_after": {"complete": True,"token_cross_entropy": .1,"reconstruction_mse": .01},
            "tuning": {"complete": True,"token_cross_entropy": .2,"reconstruction_mse": .02},
            "parameter_evidence": {g:{"parameter_update_l2":1.} for g in ("projection","decoder")}}


def test_source_fixture_and_partition_guard_exclude_all_evaluation_sources(runner):
    fixture=runner.source_fixture()
    assert len(fixture["rows"]) == 54
    assert [len(runner.partition_rows(fixture,p)) for p in runner.PARTITIONS] == [24,24,6]
    assert all(r["split"] != "sealed_evaluation" for r in fixture["rows"])
    originals={r["id"]:r for r in runner.partition_rows(fixture,"original_training")}
    assert {r["parent_id"] for r in runner.partition_rows(fixture,"added_wording")} == set(originals)
    with pytest.raises(RuntimeError,match="development partitions"):
        runner.partition_rows(fixture,"sealed_evaluation")


@pytest.mark.parametrize("field", ["rules","temporal_records","candidate"])
def test_paraphrase_requires_parent_rule_and_typed_temporal_equality(runner,field):
    parent={"candidate":True,"compiler":{"rules":[{"modality":"O"}],
            "temporal_records":[{"temporal_kind":"within_duration","quantity":10}]}}
    variant=copy.deepcopy(parent)
    runner.require_equivalent_labels(parent,variant)
    if field == "candidate":
        variant[field]=False
    else:
        variant["compiler"][field]=[]
    with pytest.raises(RuntimeError,match="screening|differs"):
        runner.require_equivalent_labels(parent,variant)


@pytest.mark.parametrize("mutation", ["steps","deadline","partial","nan","infinity","zero_update"])
def test_completed_training_rejects_incomplete_deadline_nonfinite_or_zero_work(runner,mutation):
    report=_report(runner)
    if mutation == "steps": report["optimizer_steps"]-=1
    if mutation == "deadline": report["stopped_reason"]="deadline_before_batch"
    if mutation == "partial": report["tuning"]["complete"]=False
    if mutation == "nan": report["training_after"]["token_cross_entropy"]=float("nan")
    if mutation == "infinity": report["parameter_evidence"]["projection"]["parameter_update_l2"]=float("inf")
    if mutation == "zero_update": report["parameter_evidence"]["decoder"]["parameter_update_l2"]=0
    with pytest.raises(RuntimeError): runner.require_completed_training(report)


@pytest.mark.parametrize("key", ["model_state","codec","binding","config"])
def test_paired_initialization_requires_each_control(runner,key):
    expected={key:key for key in ("model_state","codec","binding","config")}
    candidate=dict(expected,**{key:"different"})
    with pytest.raises(RuntimeError,match="initial"):
        runner.require_initial_pair(expected,candidate)


@pytest.mark.parametrize("changed", ["source","plan","profile"])
def test_plan_guard_rejects_producer_plan_or_conditioning_drift(runner,tmp_path,monkeypatch,changed):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_training_profiles import get_training_profile
    fixture={"rows":[]}
    monkeypatch.setattr(runner,"source_fixture",lambda:fixture)
    monkeypatch.setattr(runner,"sources",lambda:{"producer":"same" if changed != "source" else "changed"})
    plan={"source_hashes":{"producer":"same"},"seeds":list(runner.SEEDS),"arms":list(runner.ARMS),
          "optimizer_steps_per_arm":runner.STEPS,"max_seconds_per_arm":runner.MAX_SECONDS,
          "profile":get_training_profile("raw_gain10_v1"),
          "source_fixture":runner.write(tmp_path/"source-fixture.json",fixture)}
    if changed == "profile": plan["profile"]["core_options"]["initial_embedding_scale"] = .02
    pin=runner.write(tmp_path/"plan.json",plan)["sha256"]
    if changed == "plan": (tmp_path/"plan.json").write_text("{}")
    with pytest.raises(RuntimeError,match="changed"):
        runner.plan_guard(tmp_path,plan,pin)


@pytest.mark.parametrize("changed", ["receipt","artifact"])
def test_preparation_guard_detects_drift_between_arms(runner,tmp_path,monkeypatch,changed):
    monkeypatch.setattr(runner,"plan_guard",lambda *args:None)
    ref=runner.write(tmp_path/"targets-original_training.json",[{"id":"train"}])
    prepared={"plan_sha256":"fixed","files":{"original_training":ref}}
    pin=runner.write(tmp_path/"prepared.json",prepared)["sha256"]
    (tmp_path/("prepared.json" if changed == "receipt" else "targets-original_training.json")).write_text("{}")
    with pytest.raises(RuntimeError,match="changed"):
        runner.data_guard(tmp_path,{},prepared,pin)


def test_changed_embedding_receipt_rejected_before_sample_rebuild(runner,tmp_path,monkeypatch):
    fixture=runner.write(tmp_path/"source-fixture.json",{"rows":[]})
    runner.write(tmp_path/"plan.json",{"source_fixture":fixture})
    production=runner.write(tmp_path/"embedding-production.json",{})
    runner.write(tmp_path/"prepared.json",{"plan_sha256":"fixed","files":{"embedding_production":production}})
    (tmp_path/"embedding-production.json").write_text("changed")
    monkeypatch.setattr(runner,"plan_guard",lambda *args:None)
    monkeypatch.setattr(runner,"native_samples",lambda *args:pytest.fail("rebuilt unverified embedding inputs"))
    with pytest.raises(RuntimeError,match="artifact changed"):
        runner.prepared_inputs(tmp_path)


@pytest.mark.parametrize("lake_complete",[True,False])
def test_six_arm_workflow_retains_all_outputs_and_uses_fixed_original_scored_heads(runner,tmp_path,monkeypatch,lake_complete):
    torch=pytest.importorskip("torch")
    previous_threads=torch.get_num_threads()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        autoencoder_runtime_registry as runtimes,autoencoder_decoded_schema as schemas,
        formula_generation_metrics as metrics,modal_joint_formula as joint,modal_latent_formula as learning)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_training_profiles import get_training_profile
    fixture=runner.source_fixture()
    samples={r["id"]:SimpleNamespace(sample_id=r["id"],text=r["text"]) for r in fixture["rows"]}
    targets={part:[{"id":row["id"]} for row in runner.partition_rows(fixture,part)] for part in runner.PARTITIONS}
    plan={"profile":get_training_profile("raw_gain10_v1")}
    prepared={"plan_sha256":"fixed"}
    runner.write(tmp_path/"prepared.json",prepared)
    monkeypatch.setattr(runner,"prepared_inputs",lambda directory:(plan,prepared,fixture,samples,targets))
    monkeypatch.setattr(runner,"data_guard",lambda *args:None)
    monkeypatch.setattr(joint,"_core_binding",lambda model:{"core":"fixed"})
    monkeypatch.setattr(joint,"_rows",lambda model,values,labels:[v.sample_id for v in values])
    monkeypatch.setattr(learning,"build_checkpoint",lambda binding,train,tune,**options:{
        "binding":binding,"config":options,"codec":{"tokens":"same"},"model_state":{"seed":options["seed"]},
        "progress":{"optimizer_steps":0},"training_ids":train})
    fitted=[]
    class Runtime:
        def __init__(self,checkpoint=None):
            self.checkpoint=copy.deepcopy(checkpoint)
            self.model=SimpleNamespace(state=SimpleNamespace(to_dict=lambda:{}),
                attach_formula_checkpoint=self.attach,save_formula_checkpoint=lambda path:runner.write(path,self.checkpoint))
        def attach(self,checkpoint): self.checkpoint=copy.deepcopy(checkpoint)
        def infer(self,values):
            assert all("sealed" not in v.sample_id for v in values)
            return {"checkpoint_sha256":learning.checkpoint_digest(self.checkpoint),
                    "rows":[{"id":v.sample_id} for v in values]}
        def train(self,values,**kwargs):
            assert [v.sample_id for v in values] == self.checkpoint["training_ids"]
            assert [v["id"] for v in kwargs["formula_targets"]] == self.checkpoint["training_ids"]
            steps=kwargs["max_optimizer_steps"]
            fitted.append((self.checkpoint["config"]["seed"],len(values),steps))
            self.checkpoint["progress"]["optimizer_steps"]+=steps
            report=dict(_report(runner),optimizer_steps=steps,checkpoint_sha256=learning.checkpoint_digest(self.checkpoint))
            return {"checkpoint":copy.deepcopy(self.checkpoint),"report":report}
    def opening(*args,**kwargs):
        checkpoint=json.loads(Path(kwargs["formula_checkpoint"]).read_text()) if "formula_checkpoint" in kwargs else None
        return Runtime(checkpoint)
    monkeypatch.setattr(runtimes,"open_runtime",opening)
    monkeypatch.setattr(metrics,"compare_free_running_formulas",lambda outputs,targets,**kwargs:{
        "valid_evaluation":True,"operational_complete":True,"exact_reconstruction":{"matched":len(targets)}})
    schema_calls=[]
    def observing(runtime,values,**kwargs):
        assert runtime.checkpoint["progress"]["optimizer_steps"] == runner.STEPS
        schema_calls.append((runtime.checkpoint["config"]["seed"],[v.sample_id for v in values]))
        return {"checkpoint_sha256":learning.checkpoint_digest(runtime.checkpoint),
                "schema_checks_complete":lake_complete,"lake_build_count":4,"schema_pass_count":4 if lake_complete else 3}
    monkeypatch.setattr(schemas,"validate_decoded_outputs",observing)
    try:
        if lake_complete: runner.train(tmp_path)
        else:
            with pytest.raises(RuntimeError,match="schema execution incomplete"): runner.train(tmp_path)
    finally:
        torch.set_num_threads(previous_threads)
    report=json.loads((tmp_path/"report.json").read_text())
    assert report["operational_ok"] is lake_complete
    assert all(report[key] is False for key in runner.FALSE)
    assert [(seed,count) for seed,count,steps in fitted if steps == 1000] == [(s,n) for s in runner.SEEDS for n in (24,48)]
    assert len(schema_calls) == 2 and schema_calls[0] == schema_calls[1]
    assert schema_calls[0][0] == 1729
    for seed in runner.SEEDS:
        for arm in runner.ARMS:
            observed=report["results"][str(seed)][arm]
            assert observed["sample_counts"] == {"original_training":24,"added_wording":24,"tuning":6,
                                                 "all_fit":24 if arm == "original24" else 48}
            assert observed["row_presentations"] == 6000
            assert observed["reload_prediction_exact"] and observed["resume_checkpoint_exact"]
            assert Path(observed["head"]["path"]).is_file()
            assert Path(observed["resume_probe_head"]["path"]).is_file()
    assert not list(tmp_path.glob("*sealed*"))
