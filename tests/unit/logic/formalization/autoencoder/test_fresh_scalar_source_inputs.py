"""Source-only preparation contracts using explicit non-model producer doubles."""
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import fresh_scalar_source_inputs as subject
from ipfs_datasets_py.logic.formalization.autoencoder import dimension_source_inputs as bounded
from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_768_complete as complete
from .test_authored_scalar_holdout import inputs


def plan():
    rows = subject.authored.build_holdout(**inputs())["source_rows"]
    return subject.source_plan(rows, expected_source_rows_sha256=subject.digest(rows), sealed_comparison_sha256="a"*64)


def config(dimension):
    return {8:{}, 384:dict(snapshot_path="/fixture/snapshot"), 768:dict(manifest_path="/fixture/manifest",
        expected_manifest_sha256="b"*64, model_directory="/fixture/model", code_directory="/fixture/code")}[dimension]


def fake_payload(source_plan, dimension):
    """Diagnostic vectors only; never passed to any real embedding producer."""
    return dict(vectors=[dict(id=r["id"], source_sha256=subject.authored.text_sha(r["source_text"]),
        vector=[1.]+[0.]*(dimension-1), token_count=None if dimension==8 else 2,
        token_input_sha256=None if dimension==8 else subject.digest([101,102])) for r in source_plan["source_inputs"]],
        native_production={"diagnostic_test_double":True}, producer_files=subject._pins(),source_artifact=None,
        representation=dict(kind="explicit_test_double",dimension=dimension))


def fake_reports(monkeypatch, source_plan):
    monkeypatch.setattr(subject,"_validate_native_binding",lambda *a:None)
    result = {}
    for dimension in (8,384,768):
        monkeypatch.setattr(subject,"_produce"+str(dimension),lambda p,*a,d=dimension:fake_payload(p,d))
        result[str(dimension)] = subject.produce_width(source_plan,dimension=dimension,asset_config=config(dimension),
            source_artifact_directory=Path("/unused-test-path") if dimension==384 else None)
    return result


def resign(report):
    report["production_sha256"] = subject.digest({k:v for k,v in report.items() if k!="production_sha256"})
    return report


def test_source_only_plan_exact_alias_coverage_and_unmodified_inputs():
    source_plan = plan()
    assert source_plan["unique_sources"] == 216 and len(source_plan["source_aliases"]) == 228
    assert len(source_plan["source_rows"]) == 48
    assert all(set(row)=={"id","source_text"} for row in source_plan["source_inputs"])
    lookup={row["id"]:row["source_text"] for row in source_plan["source_inputs"]}
    paragraphs={row["id"]:row["source_text"] for row in source_plan["source_rows"]}
    for alias in source_plan["source_aliases"]:
        text=paragraphs[alias["paragraph_id"]]
        if alias["role"]=="clause":text=text.split("\n\n")[alias["slot"]]
        assert lookup[alias["source_id"]]==text
        assert alias["source_sha256"]==subject.authored.text_sha(text)
    assert source_plan["plan_sha256"]==subject.digest({k:v for k,v in source_plan.items() if k!="plan_sha256"})
    assert all(source_plan[k] is False for k in subject.FALSE)


@pytest.mark.parametrize("key",["target","target_ids","expected_count","reference","template_family","embedding"])
def test_source_plan_rejects_labels_even_with_matching_caller_hash(key):
    source_plan=plan();rows=source_plan["source_rows"];rows[0][key]="poison"
    with pytest.raises(ValueError,match="closed"):
        subject.source_plan(rows,expected_source_rows_sha256=subject.digest(rows),sealed_comparison_sha256="a"*64)


@pytest.mark.parametrize("change",["source","alias","count","authority"])
def test_rehashed_malformed_plan_is_not_accepted(change,monkeypatch):
    source_plan=plan()
    if change=="source":source_plan["source_inputs"][0]["source_text"]+=" changed"
    elif change=="alias":source_plan["source_aliases"][0]["source_id"]="foreign"
    elif change=="count":source_plan["unique_sources"]=215
    else:source_plan["admitted"]=True
    source_plan["plan_sha256"]=subject.digest({k:v for k,v in source_plan.items() if k!="plan_sha256"})
    monkeypatch.setattr(subject,"_produce8",lambda *a:pytest.fail("producer reached"))
    with pytest.raises(ValueError,match="plan or aliases"):
        subject.produce_width(source_plan,dimension=8,asset_config={})


@pytest.mark.parametrize("dimension",[8,384,768])
def test_dispatch_preserves_plan_and_uses_explicit_width_and_path(monkeypatch,dimension):
    source_plan=plan();before=deepcopy(source_plan);calls=[]
    def produce(p,assets,directory,batch,deadline):
        calls.append((p,assets,directory,batch,deadline));return fake_payload(p,dimension)
    monkeypatch.setattr(subject,"_produce"+str(dimension),produce)
    monkeypatch.setattr(subject,"_validate_native_binding",lambda *a:None)
    path=Path("/source-artifacts") if dimension==384 else None
    report=subject.produce_width(source_plan,dimension=dimension,asset_config=config(dimension),source_artifact_directory=path)
    assert source_plan==before and len(calls)==1
    assert calls[0][0]==source_plan and calls[0][3]==4 and calls[0][2]==path
    assert report["encoder_executed"] is (dimension!=8) and all(report[k] is False for k in subject.FALSE)


@pytest.mark.parametrize("field,value",[("dimension",True),("dimension",7),("batch_size",True),("batch_size",16),
    ("max_seconds",True),("max_seconds",0),("max_seconds",601),("max_seconds",float("nan"))])
def test_invalid_runtime_policy_blocks_before_producer(monkeypatch,field,value):
    source_plan=plan();args=dict(dimension=8,asset_config={});args[field]=value
    monkeypatch.setattr(subject,"_produce8",lambda *a:pytest.fail("producer reached"))
    with pytest.raises(ValueError):subject.produce_width(source_plan,**args)


def test_missing_and_extra_asset_keys_fail_without_fallback(monkeypatch):
    source_plan=plan();monkeypatch.setattr(subject,"_produce768",lambda *a:pytest.fail("producer reached"))
    for assets in ({},dict(config(768),download=True),dict(config(768),model_directory="relative")):
        with pytest.raises(ValueError):subject.produce_width(source_plan,dimension=768,asset_config=assets)


def test_post_producer_deadline_discards_result(monkeypatch):
    source_plan=plan();clock=[0.]
    monkeypatch.setattr(subject.time,"monotonic",lambda:clock[0])
    def late(p,*args):clock[0]=601.;return fake_payload(p,8)
    monkeypatch.setattr(subject,"_produce8",late)
    with pytest.raises(TimeoutError):subject.produce_width(source_plan,dimension=8,asset_config={})


def test_assemble_reconstructs_source_clauses_without_fitting_or_labels(monkeypatch):
    source_plan=plan();reports=fake_reports(monkeypatch,source_plan);before=deepcopy(reports)
    result=subject.assemble(source_plan,reports)
    assert reports==before and all(result[k] is False for k in subject.FALSE)
    for dimension,lane in result["dimensions"].items():
        assert len(lane["rows"])==48 and len(lane["clause_cache"])==180
        assert all(set(row)=={"id","source_text","input"} and len(row["input"])==int(dimension) for row in lane["rows"])
        for row in lane["rows"]:
            context=lane["source_contexts"][row["id"]]
            assert [s["source_text"] for s in context["segments"]]==row["source_text"].split("\n\n")
            assert context["source_sha256"]==subject.authored.text_sha(row["source_text"])
    assert result["inputs_sha256"]==subject.digest({k:v for k,v in result.items() if k!="inputs_sha256"})
    assert not any("transform" in lane or "normalization" in lane for lane in result["dimensions"].values())


@pytest.mark.parametrize("change",["NaN","bool","dimension","nonunit","source","tokens","order","flag"])
def test_bad_saved_vectors_or_identity_are_rejected_even_when_rehashed(monkeypatch,change):
    source_plan=plan();reports=fake_reports(monkeypatch,source_plan);report=reports["384"];row=report["vectors"][0]
    if change=="NaN":row["vector"][0]=float("nan")
    elif change=="bool":row["vector"][0]=True
    elif change=="dimension":row["vector"].pop()
    elif change=="nonunit":row["vector"][0]=2.
    elif change=="source":row["source_sha256"]="f"*64
    elif change=="tokens":row["token_count"]=513
    elif change=="order":report["vectors"][0],report["vectors"][1]=report["vectors"][1],report["vectors"][0]
    else:report["transforms_fitted"]=True
    if change=="NaN":
        with pytest.raises(ValueError):subject.assemble(source_plan,reports)
    else:
        resign(report)
        with pytest.raises(ValueError):subject.assemble(source_plan,reports)


def test_native768_refuses_513_tokens_before_first_forward(monkeypatch):
    source_plan=plan();calls=[]
    assets=dict(status="available")
    monkeypatch.setattr(complete.reference._PROFILE,"inspect_local_assets",lambda *a,**k:assets)
    monkeypatch.setattr(complete,"_load_backend",lambda *a:(SimpleNamespace(get_num_threads=lambda:1),
        SimpleNamespace(padding_side="right"),SimpleNamespace(config=SimpleNamespace(vocab_size=200)),{}))
    monkeypatch.setattr(complete.reference,"_tokenize",lambda *a:[dict(input_ids=list(range(513)),attention_mask=[1]*513)])
    monkeypatch.setattr(complete,"_verify_dense_path",lambda *a:calls.append("forward"))
    with pytest.raises(ValueError,match="before any native768 forward"):
        subject._produce768(source_plan,config(768),None,4,subject.time.monotonic()+30)
    assert not calls


def test_source_artifact_uses_exact_byte_spans_and_never_replaces_existing_directory(tmp_path):
    source_plan=plan()
    class Artifact:
        def __init__(self,sha,bytes_):self.sha256=sha;self.bytes=bytes_
    class Span:
        def __init__(self,artifact,kind,release,id_,language,citation,start,end):
            self.artifact=artifact;self.source_kind=kind;self.byte_start=start;self.byte_end=end;self.citation=citation
    class Input:
        def __init__(self,span,title,section,text,citation):self.source=span;self.text=text
    corpus=SimpleNamespace(SourceArtifact=Artifact,SourceSpan=Span);codec=SimpleNamespace(EmbeddingInput=Input)
    rows,path,ref=subject._source_artifact(source_plan,tmp_path/"new",codec,corpus)
    raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==ref["sha256"] and len(raw)==ref["bytes"]
    for row,source in zip(rows,source_plan["source_inputs"]):
        assert raw[row.source.byte_start:row.source.byte_end].decode()==source["source_text"]==row.text
        assert row.source.source_kind=="diagnostic"
    with pytest.raises(ValueError,match="fresh absolute"):
        subject._source_artifact(source_plan,tmp_path/"new",codec,corpus)
