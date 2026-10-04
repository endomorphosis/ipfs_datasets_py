"""Synthetic preparation checks; never load encoder or archived teacher weights."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import dimension_source_inputs as subject
from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_768_complete as complete
from ipfs_datasets_py.logic.formalization.autoencoder import legal_native_conditioning as historical


def unit(dimension, index):
    return [float(i == index) for i in range(dimension)]


def fixture(tmp_path, mutate_report=None):
    texts = ["Agency α files.", "Officer retains.", "Board delivers.", "Clerk reviews."]
    cache = [dict(id=f"c{i}", source_text=text, input=unit(384,i)) for i,text in enumerate(texts)]
    rows = {
        "train":[dict(id="t1",source_text=texts[0],input=unit(384,10)),
            dict(id="t2",source_text="\n\n".join(texts[:2]),input=unit(384,11))],
        "validation":[dict(id="v1",source_text=texts[2],input=unit(384,12)),
            dict(id="v2",source_text="\n\n".join(texts[2:]),input=unit(384,13))],
    }
    contexts={split:subject.clauses.build_source_contexts(
        [{k:row[k] for k in ("id","source_text")} for row in group],cache) for split,group in rows.items()}
    assets=dict(status="available",profile_id=complete.PROFILE_ID,manifest_sha256="a"*64,
        model_directory="/synthetic/model",code_directory="/synthetic/code",files=[])
    receipts=[]
    for i,text in enumerate(texts):
        tokens=[1,i+4,2]
        receipts.append(dict(schema=complete.reference.RECEIPT_SCHEMA,id=f"old-{i}",
            source_sha256=subject._text_sha(text),profile_id=complete.PROFILE_ID,dimension=768,
            embedding=unit(768,i+1),asset_manifest_sha256="a"*64,truncated=False,normalized=True,
            token_count_including_special_tokens=len(tokens),token_input_sha256=complete.reference._digest(tokens)))
    report=dict(schema=complete.SCHEMA,status="completed",profile_id=complete.PROFILE_ID,
        model_inference_executed=True,runtime_compatibility_verified=True,download_executed=False,
        training_executed=False,proof_authority=False,assets=assets,implementation=complete._implementation(),
        execution_profile=dict(device="cpu",dtype="float32",pooling="cls",normalization="l2",
            padding_side="right",max_tokens_including_special_tokens=8192),
        receipt_count=len(receipts),receipts=receipts)
    if mutate_report:mutate_report(report)
    path=tmp_path/"native.json";path.write_text(json.dumps(report))
    return rows,contexts,path,hashlib.sha256(path.read_bytes()).hexdigest()


def plan(tmp_path):
    rows,contexts,path,sha=fixture(tmp_path)
    return subject.plan_sources(rows,contexts,path,expected_native_report_sha256=sha)


class Tokenizer:
    padding_side="right"
    def __init__(self, *, overlong=False, corrupt_padding=False):
        self.overlong=overlong;self.corrupt_padding=corrupt_padding;self.encoded=[]
    def encode(self,text,*,add_special_tokens,truncation):
        assert add_special_tokens is True and truncation is False
        self.encoded.append(text)
        return [1]+([4]*511 if self.overlong else [4+ord(c)%50 for c in text])+[2]
    def pad(self,rows,*,padding,return_tensors):
        assert padding is True and return_tensors=="pt"
        width=max(len(row["input_ids"]) for row in rows)
        result={key:torch.tensor([row[key]+[0]*(width-len(row[key])) for row in rows],dtype=torch.long)
            for key in ("input_ids","attention_mask")}
        if self.corrupt_padding:result["input_ids"][0,0]+=1
        return result


class Encoder:
    training=False
    config=SimpleNamespace(vocab_size=100)
    def __init__(self,calls,role="complete"):
        self.calls=calls;self.role=role
        if role=="complete":self.new=Encoder(calls,"encoder")
    def __call__(self,**inputs):
        self.calls.append(self.role)
        ids=inputs["input_ids"]; hidden=torch.zeros((*ids.shape,768),dtype=torch.float32)
        # A source-dependent fake vector, used only for interface tests.
        for i,row in enumerate(ids):
            hidden[i,:,100+int(row.sum())%500]=1.
        return SimpleNamespace(last_hidden_state=hidden)


def install_backend(monkeypatch, prepared, *, tokenizer=None, mutate_assets=False):
    calls=[];tokenizer=tokenizer or Tokenizer();model=Encoder(calls)
    assets=deepcopy(prepared["native768_assets"])
    if mutate_assets:assets["manifest_sha256"]="b"*64
    monkeypatch.setattr(complete.reference._PROFILE,"inspect_local_assets",lambda *args,**kwargs:deepcopy(assets))
    monkeypatch.setattr(complete,"_load_backend",lambda admitted:(torch,tokenizer,model,{"synthetic":True}))
    monkeypatch.setattr(subject.importlib.metadata,"version",lambda name:"synthetic-test")
    return calls,tokenizer,model


def produce(prepared):
    return subject.produce_missing768(prepared,manifest_path="/synthetic/manifest.json",
        expected_manifest_sha256="a"*64,model_directory="/synthetic/model",code_directory="/synthetic/code",batch_size=2)


def install_historical(monkeypatch):
    calls=[]
    def feature(sources,*,backend):
        assert backend=="historical_blank_en"
        assert all(set(row)=={"id","source_text"} for row in sources)
        calls.append(deepcopy(sources))
        return dict(schema=historical.SCHEMA,synthetic_rows=[dict(id=row["id"],
            source_sha256=subject._text_sha(row["source_text"]),vector=unit(8,i)) for i,row in enumerate(sources)])
    def stage(bundle,*,stage,sources):
        assert stage==historical.HISTORICAL_STAGE
        assert [row["id"] for row in bundle["synthetic_rows"]]==[row["id"] for row in sources]
        return deepcopy(bundle["synthetic_rows"])
    monkeypatch.setattr(historical,"historical_features",feature)
    monkeypatch.setattr(historical,"stage_rows",stage)
    return calls


def test_plan_is_source_only_deduplicates_and_preserves_two_native384_views(tmp_path):
    rows,contexts,path,sha=fixture(tmp_path);before=deepcopy((rows,contexts))
    result=subject.plan_sources(rows,contexts,path,expected_native_report_sha256=sha)
    assert (rows,contexts)==before
    assert result["unique_sources"]==6 and result["cached768_sources"]==4 and result["missing768_sources"]==2
    assert result["paragraph_counts"]==result["clause_counts"]=={"train":2,"validation":2}
    assert result["historical_native768_profile_token_limit"]==8192
    assert result["cache_admission_token_limit"]==512 and result["cached_profile_relabelled"] is False
    assert result["paragraph_rows384"]["train"][0]["input"] != result["clause_cache384"]["train"][0]["input"]
    assert all(set(row)=={"id","source_text"} for row in result["source_rows"])
    assert subject._plan(result)==result["source_rows"]
    result["paragraph_rows384"]["train"][0]["input"][10]=9
    assert (rows,contexts)==before


@pytest.mark.parametrize("mutation",["profile","implementation","dimension","token_limit","bool_tokens","truncated",
    "unnormalized","nan","receipt_count","duplicate","ambiguous","asset","execution","authority"])
def test_cached_report_refuses_wrong_or_incomplete_profile(tmp_path,mutation):
    def mutate(report):
        r=report["receipts"][0]
        if mutation=="profile":report["profile_id"]="other"
        elif mutation=="implementation":report["implementation"]["complete_loader"]="b"*64
        elif mutation=="dimension":r["dimension"]=384
        elif mutation=="token_limit":r["token_count_including_special_tokens"]=513
        elif mutation=="bool_tokens":r["token_count_including_special_tokens"]=True
        elif mutation=="truncated":r["truncated"]=True
        elif mutation=="unnormalized":r["embedding"][1]=2.
        elif mutation=="nan":r["embedding"][0]=float("nan")
        elif mutation=="receipt_count":report["receipt_count"]+=1
        elif mutation=="duplicate":report["receipts"][1]["id"]=r["id"]
        elif mutation=="ambiguous":report["receipts"][1]["source_sha256"]=r["source_sha256"]
        elif mutation=="asset":r["asset_manifest_sha256"]="b"*64
        elif mutation=="execution":report["execution_profile"]["max_tokens_including_special_tokens"]=512
        else:report["proof_authority"]=True
    rows,contexts,path,sha=fixture(tmp_path,mutate)
    with pytest.raises(ValueError):subject.plan_sources(rows,contexts,path,expected_native_report_sha256=sha)


@pytest.mark.parametrize("kind",["hash","symlink","contents"])
def test_native_report_file_authentication(tmp_path,kind):
    rows,contexts,path,sha=fixture(tmp_path)
    if kind=="hash":sha="a"*64
    elif kind=="symlink":link=tmp_path/"link.json";link.symlink_to(path);path=link
    else:path.write_text(path.read_text()+" ")
    with pytest.raises(ValueError):subject.plan_sources(rows,contexts,path,expected_native_report_sha256=sha)


@pytest.mark.parametrize("kind",["paragraph_target","source_split","malformed_context","nonnormalized","wrong_dimension"])
def test_source_plan_rejects_targets_overlap_and_corruption(tmp_path,kind):
    rows,contexts,path,sha=fixture(tmp_path)
    if kind=="paragraph_target":rows["train"][0]["target_ids"]=[1]
    elif kind=="source_split":rows["validation"][0]["source_text"]=rows["train"][0]["source_text"]
    elif kind=="malformed_context":contexts["train"]["t1"]["target_count"]=1
    elif kind=="nonnormalized":rows["train"][0]["input"][10]=2.
    else:rows["train"][0]["input"]=unit(8,0)
    with pytest.raises(ValueError):subject.plan_sources(rows,contexts,path,expected_native_report_sha256=sha)


@pytest.mark.parametrize("kind",["digest","source","cached","count","relabel"])
def test_self_consistent_plan_corruption_still_rejected(tmp_path,kind):
    prepared=plan(tmp_path)
    if kind=="digest":prepared["plan_sha256"]="a"*64
    else:
        if kind=="source":prepared["source_rows"][0]["source_text"]+="x"
        elif kind=="cached":next(iter(prepared["cached768"].values()))["embedding"]=unit(768,700)
        elif kind=="count":prepared["unique_sources"]+=1
        else:prepared["cached_profile_relabelled"]=True
        prepared["plan_sha256"]=subject.core.digest({k:v for k,v in prepared.items() if k!="plan_sha256"})
    with pytest.raises(ValueError):subject._plan(prepared)


def test_historical8_uses_exact_preserved_source_producer_not_teacher(tmp_path,monkeypatch):
    prepared=plan(tmp_path);calls=install_historical(monkeypatch)
    report=subject.produce_historical8(prepared)
    assert calls==[prepared["source_rows"]]
    assert len(report["validated_rows"])==6
    assert report["legacy_sparse_reconstruction_used"] is report["teacher_checkpoint_loaded"] is False
    assert report["neural_semantic_embeddings"] is False


def test_guarded_missing768_full_source_probe_and_each_batch(tmp_path,monkeypatch):
    prepared=plan(tmp_path);calls,tokenizer,_=install_backend(monkeypatch,prepared)
    report=produce(prepared)
    assert tokenizer.encoded==[row["source_text"] for row in prepared["missing768_rows"]]
    assert calls==["complete","encoder","complete"]
    assert report["forward_validation"]["forward_count"]==3
    assert report["forward_validation"]["sample_forward_observations"]==4
    assert report["experiment_token_limit"]==512 and report["historical_profile_token_limit"]==8192
    assert report["native_profile_id"]==complete.PROFILE_ID and ":tokens8192:" in report["native_profile_id"]
    assert report["cached_profile_relabelled"] is False
    assert all(report[name] is False for name in subject.FALSE)
    assert report["forward_validation"]==subject.validate_forward_observations(report)


def test_513_tokens_rejected_before_any_forward(tmp_path,monkeypatch):
    prepared=plan(tmp_path);calls,_,_=install_backend(monkeypatch,prepared,tokenizer=Tokenizer(overlong=True))
    with pytest.raises(ValueError,match="512-token"):produce(prepared)
    assert calls==[]


def test_exactly512_tokens_admitted_without_context_change(tmp_path,monkeypatch):
    prepared=plan(tmp_path)
    class ExactTokenizer(Tokenizer):
        def encode(self,text,*,add_special_tokens,truncation):
            assert add_special_tokens is True and truncation is False
            return [1]+[4]*510+[2]
    calls,_,model=install_backend(monkeypatch,prepared,tokenizer=ExactTokenizer())
    result=produce(prepared)
    assert result["forward_validation"]["maximum_forward_width"]==512
    assert calls==["complete","encoder","complete"]
    assert vars(model.config)=={"vocab_size":100}


def test_forward_overrun_is_rejected_after_the_actual_call(monkeypatch):
    rows=[dict(id="source:"+subject._text_sha("Text"),source_text="Text")]
    tokens=[dict(input_ids=[1,4,2],attention_mask=[1,1,1])];events=[];calls=[]
    clock=iter([20.,22.])
    monkeypatch.setattr(subject.time,"monotonic",lambda:next(clock))
    guard,_,_=subject._guarded_model(torch,Encoder(calls),tokens,rows,1,21.,events)
    inputs={key:torch.tensor([value],dtype=torch.long) for key,value in tokens[0].items()}
    with pytest.raises(TimeoutError):guard(**inputs)
    assert events==[] and calls==["complete"]


def test_actual_probe_token_corruption_rejected_before_any_forward(tmp_path,monkeypatch):
    prepared=plan(tmp_path);calls,_,_=install_backend(monkeypatch,prepared,tokenizer=Tokenizer(corrupt_padding=True))
    with pytest.raises(ValueError,match="tokens differ"):produce(prepared)
    assert calls==[]


def test_changed_local_assets_rejected_before_backend(tmp_path,monkeypatch):
    prepared=plan(tmp_path);calls,_,_=install_backend(monkeypatch,prepared,mutate_assets=True)
    with pytest.raises(ValueError,match="assets differ"):produce(prepared)
    assert calls==[]


@pytest.mark.parametrize("kind",["wrongpath","dtype","device_shape","mask","tokens","extra","expired"])
def test_forward_proxy_fail_closed(kind):
    rows=[dict(id="source:"+subject._text_sha("Text"),source_text="Text")]
    tokens=[dict(input_ids=[1,4,2],attention_mask=[1,1,1])];calls=[];events=[]
    model=Encoder(calls);deadline=time.monotonic()+60
    if kind=="expired":deadline=0
    guard,_,_=subject._guarded_model(torch,model,tokens,rows,1,deadline,events)
    inputs={key:torch.tensor([row],dtype=torch.long) for key,row in tokens[0].items()}
    if kind=="wrongpath":guard=guard.new
    elif kind=="dtype":inputs["input_ids"]=inputs["input_ids"].float()
    elif kind=="device_shape":inputs["input_ids"]=inputs["input_ids"][:,:2]
    elif kind=="mask":inputs["attention_mask"][0,0]=0
    elif kind=="tokens":inputs["input_ids"][0,1]=5
    elif kind=="extra":inputs["labels"]=torch.tensor([0])
    with pytest.raises((ValueError,TimeoutError)):guard(**inputs)
    assert calls==events==[] and model.training is False


@pytest.mark.parametrize("kind",["missing","role","tokens","mask","source","tokenhash","width","assertion","bool_token"])
def test_saved_forward_observations_independently_rechecked(tmp_path,monkeypatch,kind):
    prepared=plan(tmp_path);install_backend(monkeypatch,prepared);report=produce(prepared)
    if kind=="missing":report["forward_observations"].pop()
    else:
        e=report["forward_observations"][0]
        if kind=="role":e["path"]="encoder"
        elif kind=="tokens":e["input_ids"][0][0]+=1
        elif kind=="mask":e["attention_mask"][0][0]=0
        elif kind=="source":e["sources"][0]["source_sha256"]="a"*64
        elif kind=="tokenhash":e["sources"][0]["token_input_sha256"]="a"*64
        elif kind=="width":e["padded_width"]+=1
        elif kind=="assertion":e["actual_forward_checked"]=False
        else:e["input_ids"][0][0]=True
    with pytest.raises(ValueError):subject.validate_forward_observations(report)


def test_three_dimension_assembly_keeps_rows_source_only_and_exact_profiles(tmp_path,monkeypatch):
    prepared=plan(tmp_path);install_backend(monkeypatch,prepared);install_historical(monkeypatch)
    report8=subject.produce_historical8(prepared);report768=produce(prepared)
    result=subject.assemble_inputs(prepared,report8,report768)
    assert result["complete"] is True and set(result["dimensions"])=={"8","384","768"}
    assert result["inputs_sha256"]==subject.core.digest({k:v for k,v in result.items() if k!="inputs_sha256"})
    for name,lane in result["dimensions"].items():
        assert lane["representation"]["dimension"]==int(name)
        assert len(lane["train"])==len(lane["validation"])==2
        assert all(set(row)=={"id","source_text","input"} for split in ("train","validation") for row in lane[split])
        assert all(len(row["input"])==int(name) for split in ("train","validation") for row in lane[split])
    assert result["dimensions"]["384"]["train"]==prepared["paragraph_rows384"]["train"]
    assert result["dimensions"]["384"]["clause_cache"]==prepared["clause_cache384"]
    assert result["dimensions"]["8"]["representation"]["semantic_embedding"] is False
    assert result["targets_attached"] is False and all(result[name] is False for name in subject.FALSE)


@pytest.mark.parametrize("kind",["forward","receipt_source","receipt_schema","receipt_token","profile","producer","assertion","vector","historical"])
def test_assembly_rejects_mutated_production_evidence(tmp_path,monkeypatch,kind):
    prepared=plan(tmp_path);install_backend(monkeypatch,prepared);install_historical(monkeypatch)
    report8=subject.produce_historical8(prepared);report768=produce(prepared)
    if kind=="forward":report768["forward_observations"][0]["input_ids"][0][0]+=1
    elif kind=="receipt_source":report768["receipts"][0]["source_sha256"]="a"*64
    elif kind=="receipt_schema":report768["receipts"][0]["schema"]="other"
    elif kind=="receipt_token":report768["receipts"][0]["token_input_sha256"]="a"*64
    elif kind=="profile":report768["native_profile_id"]="other"
    elif kind=="producer":report768["implementation"]["complete_loader"]="a"*64
    elif kind=="assertion":report768["all_actual_forward_tokens_checked"]=False
    elif kind=="vector":report768["receipts"][0]["embedding"]=[0.]*768
    else:report8["validated_rows"][0]["source_sha256"]="a"*64
    with pytest.raises(ValueError):subject.assemble_inputs(prepared,report8,report768)
