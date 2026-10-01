"""Exact numeric parity against the unchanged trainer, including partial epochs."""
import copy
import hashlib
import importlib.util
import math
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def one_cpu_thread():
    torch=pytest.importorskip("torch")
    previous=torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def modules():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as reference
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula_prepared as prepared
    return reference,prepared


def data(*,seed=1729,batch_size=3):
    reference,_=modules()
    binding=dict(domain="legal_ir",lineage_id="current_legal_v2",dimension=384,
                 runtime_profile="prepared-test/v1",core_sha256="1"*64)
    def row(i):
        vector=[math.sin((i+1)*(j+1)/97.)/20 for j in range(384)]
        rule=dict(modality="F" if i%3==0 else "O",actor="agency" if i%2==0 else "officer",
                  action="submit",object="report",conditions=[],exceptions=["emergency"] if i%3==1 else [],
                  temporal=["within 10 days"] if i%3==1 else [])
        return dict(id=f"row-{i}",source_text=f"Unique diagnostic source {i}.",latent=vector,
                    embedding=[x*.8 for x in vector],canonical_ir={"rules":[rule]})
    training=[row(i) for i in range(7)]
    tuning=[row(i) for i in range(8,10)]
    head=reference.build_checkpoint(binding,training,tuning,seed=seed,batch_size=batch_size,
         hidden_size=8,token_embedding_dim=8,projection_width=2,learning_rate=.005)
    return head,training,tuning


@pytest.mark.parametrize("indices", [[0],[1,0],[6,2,1],[5,3,0,4]])
def test_cached_batch_exact_values_shapes_and_contiguity(indices):
    reference,fast=modules()
    head,training,_=data()
    cache=fast._PreparedRows(training,head["codec"],384)
    actual=cache.batch(indices)
    expected=reference._batch([training[i] for i in indices],head["codec"])
    for left,right in zip(actual,expected):
        assert left.equal(right) and left.dtype==right.dtype and left.shape==right.shape
        assert left.is_contiguous() and right.is_contiguous()
    assert cache.tensor_bytes > 0


@pytest.mark.parametrize("seed,batch_size,steps",[(1729,3,1),(1729,3,8),(1730,6,5)])
def test_complete_checkpoint_losses_gradients_and_predictions_match_reference(seed,batch_size,steps):
    reference,fast=modules()
    head,training,tuning=data(seed=seed,batch_size=batch_size)
    original=copy.deepcopy(head)
    opts=dict(epochs=100,max_optimizer_steps=steps,max_seconds=60)
    expected=reference.train(head,training,tuning,**opts)
    actual=fast.train(head,training,tuning,**opts)
    assert actual["checkpoint"]==expected["checkpoint"]
    for key in ("batch_losses","parameter_evidence","formula_projection_gradient_norm_max",
                "training_before","training_after","tuning","progress","stopped_reason"):
        assert actual["report"][key]==expected["report"][key],key
    assert head==original
    assert actual["report"]["targets_encoded_once"]==len(training)+len(tuning)
    assert actual["report"]["exact_reference_update_rule"] is True
    assert all(actual["report"][name] is False for name in reference.FALSE)
    inference=[{key:row[key] for key in ("id","source_text","latent")} for row in tuning]
    assert reference.infer(actual["checkpoint"],inference)==reference.infer(expected["checkpoint"],inference)


def test_target_encoding_once_per_row_including_metrics(monkeypatch):
    reference,fast=modules()
    head,training,tuning=data()
    # Warm codec metadata; count actual target encoding, not vocabulary checks.
    original=reference.codec_module.encode_target
    calls=[]
    def encoding(codec,target):
        calls.append(target)
        return original(codec,target)
    monkeypatch.setattr(reference.codec_module,"encode_target",encoding)
    fast.train(head,training,tuning,epochs=100,max_optimizer_steps=8,max_seconds=60)
    assert len(calls)==len(training)+len(tuning)


def test_cross_backend_checkpoint_resume_matches_uninterrupted_weights_and_losses(tmp_path):
    reference,fast=modules()
    head,training,tuning=data()
    options=dict(epochs=100,max_seconds=60)
    first=fast.train(head,training,tuning,max_optimizer_steps=4,**options)
    saved=reference.save_checkpoint(first["checkpoint"],tmp_path/"head.json")
    restored=reference.load_checkpoint(saved["path"],expected_sha256=saved["sha256"])
    left=fast.train(restored,training,tuning,max_optimizer_steps=5,**options)
    right=reference.train(first["checkpoint"],training,tuning,max_optimizer_steps=5,**options)
    whole=reference.train(head,training,tuning,max_optimizer_steps=9,**options)
    assert left["checkpoint"]==right["checkpoint"]
    for key in ("model_state","optimizer_state","progress"):
        assert left["checkpoint"][key]==whole["checkpoint"][key]
    assert first["report"]["batch_losses"]+left["report"]["batch_losses"]==whole["report"]["batch_losses"]


def test_zero_deadline_preserves_parameters_and_reports_incomplete_metrics():
    reference,fast=modules()
    head,training,tuning=data()
    result=fast.train(head,training,tuning,epochs=100,max_optimizer_steps=8,max_seconds=0)
    assert result["checkpoint"]["model_state"]==head["model_state"]
    assert result["checkpoint"]["optimizer_state"]==head["optimizer_state"]
    assert result["report"]["optimizer_steps"]==0
    assert result["report"]["stopped_reason"]=="deadline_before_batch"
    assert result["report"]["training_after"]["complete"] is False


@pytest.mark.parametrize("change",["rows","checkpoint"])
def test_borrowed_input_mutation_rejected_before_return(monkeypatch,change):
    reference,fast=modules()
    head,training,tuning=data()
    original=fast._loss
    mutated=False
    def loss(*args,**kwargs):
        nonlocal mutated
        result=original(*args,**kwargs)
        if not mutated:
            mutated=True
            if change=="rows": training[0]["latent"][0]+=.1
            else: head["config"]["learning_rate"]*=.5
        return result
    monkeypatch.setattr(fast,"_loss",loss)
    with pytest.raises(ValueError,match="changed during prepared training"):
        fast.train(head,training,tuning,epochs=100,max_optimizer_steps=1,max_seconds=60)


def test_source_drift_rejected_before_restore(monkeypatch):
    reference,fast=modules()
    head,training,tuning=data()
    monkeypatch.setattr(fast,"_source_identity",lambda:())
    monkeypatch.setattr(fast,"_restore",lambda *args:pytest.fail("restored after producer drift"))
    with pytest.raises(ValueError,match="changed since import"):
        fast.train(head,training,tuning)


def test_nonfinite_rows_or_loss_do_not_return_updated_checkpoint(monkeypatch):
    reference,fast=modules()
    head,training,tuning=data()
    original=copy.deepcopy(head)
    training[0]["latent"][0]=float("nan")
    with pytest.raises(ValueError,match="finite"):
        fast.train(head,training,tuning)
    training[0]["latent"][0]=0.
    head["training_manifest_sha256"]=reference.checkpoint_digest(training)
    import torch
    monkeypatch.setattr(fast,"_loss",lambda *args:(torch.tensor(float("nan")),None,None,0))
    with pytest.raises(ValueError,match="nonfinite evaluation loss"):
        fast.train(head,training,tuning)
    assert head["model_state"]==original["model_state"]


def test_reference_source_is_not_rewritten():
    reference,fast=modules()
    source=Path(reference.__file__)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==reference._IMPLEMENTATION_AT_IMPORT["files"][source.name]
    assert fast._check_sources()["reference_implementation"]==reference._implementation()


def modal_inputs():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2
    path=Path(__file__).with_name("test_modal_joint_formula.py")
    spec=importlib.util.spec_from_file_location("_prepared_modal_samples",path)
    fixtures=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    return current_v2,fixtures._training_rows(current_v2)


def test_public_model_adapter_fresh_resume_parity_and_immutable_configuration():
    reference,fast=modules()
    lineage,(training,tuning,targets,tune_targets)=modal_inputs()
    old_model,new_model=lineage.Autoencoder(compute_device="cpu"),lineage.Autoencoder(compute_device="cpu")
    options=dict(validation_samples=tuning,validation_targets=tune_targets,
                 epochs=5,max_optimizer_steps=3,max_seconds=60,
                 formula_options=dict(batch_size=1,hidden_size=8,token_embedding_dim=8,projection_width=2))
    expected=fast.joint.train(old_model,training,targets,**options)
    observed=fast.train_model(new_model,training,targets,**options)
    assert observed["checkpoint"]==expected["checkpoint"]
    assert fast.joint.infer(new_model,tuning)==fast.joint.infer(old_model,tuning)
    resume=dict(options,formula_options=None,max_optimizer_steps=1)
    assert fast.train_model(new_model,training,targets,**resume)["checkpoint"] == fast.joint.train(old_model,training,targets,**resume)["checkpoint"]
    retained=copy.deepcopy(new_model._joint_formula_checkpoint)
    with pytest.raises(ValueError,match="configuration is immutable"):
        fast.train_model(new_model,training,targets,**dict(resume,formula_options={"learning_rate":.1}))
    assert new_model._joint_formula_checkpoint==retained


@pytest.mark.parametrize("failure",["exception","core_drift"])
def test_model_adapter_does_not_attach_on_training_exception_or_core_drift(monkeypatch,failure):
    reference,fast=modules()
    lineage,(training,tuning,targets,tune_targets)=modal_inputs()
    model=lineage.Autoencoder(compute_device="cpu")
    def broken(*args,**kwargs):
        if failure=="exception": raise ValueError("injected optimizer failure")
        model.initial_embedding_scale+=.1
        return {"checkpoint":args[0],"report":{}}
    monkeypatch.setattr(fast,"train",broken)
    with pytest.raises(ValueError,match="injected|core changed"):
        fast.train_model(model,training,targets,validation_samples=tuning,validation_targets=tune_targets,
                         epochs=1,max_optimizer_steps=1,max_seconds=60)
    assert getattr(model,"_joint_formula_checkpoint",None) is None


def test_model_preparation_deadline_prevents_training_and_attachment(monkeypatch):
    reference,fast=modules()
    lineage,(training,tuning,targets,tune_targets)=modal_inputs()
    model=lineage.Autoencoder(compute_device="cpu")
    clock=[0.]
    monkeypatch.setattr(fast.time,"monotonic",lambda:clock[0])
    original=fast.joint._rows
    def slow_rows(*args,**kwargs):
        result=original(*args,**kwargs)
        clock[0]=2.
        return result
    monkeypatch.setattr(fast.joint,"_rows",slow_rows)
    monkeypatch.setattr(fast,"train",lambda *args,**kwargs:pytest.fail("training began after preparation deadline"))
    with pytest.raises(TimeoutError,match="preparation exhausted"):
        fast.train_model(model,training,targets,validation_samples=tuning,validation_targets=tune_targets,max_seconds=1)
    assert getattr(model,"_joint_formula_checkpoint",None) is None
