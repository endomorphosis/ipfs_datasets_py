"""Metadata-only authored fixtures; no encoder, model training, or proof."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[5]
SPEC=importlib.util.spec_from_file_location("source_curriculum",ROOT/"ipfs_datasets_py/logic/formalization/autoencoder/source_length_curriculum.py")
subject=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(subject)


def sha(text): return hashlib.sha256(text.encode()).hexdigest()


def inputs():
    tokenizer=dict(profile_id="pinned-local-test-profile",sha256="a"*64,encoder_context_tokens=512)
    rows=[]
    for i,(split,count) in enumerate((("train",12),("train",60),("train",130),("validation",90))):
        text="Actor "+str(i)+" shall retain record "+str(i)+"."
        component=dict(id="original-"+str(i),group_id="original-group-"+str(i),split=split,
            source_text=text,source_sha256=sha(text),target_sha256=sha("target"+str(i)),start_char=0,end_char=len(text))
        rows.append(dict(id="row-"+str(i),group_id="composite-"+str(i),split=split,source_text=text,
            source_sha256=sha(text),components=[component],target_ids=[1,3,4,2],codec_sha256="b"*64,
            target_component_ids=[component["id"]],target_status="ready",source_tokens=dict(source_sha256=sha(text),
                tokenizer_sha256=tokenizer["sha256"],tokenizer_profile_id=tokenizer["profile_id"],
                encoder_context_tokens=512,token_count=count,forward_token_count=count,truncated=False,padded=False)))
    return rows,tokenizer


def prepare(rows,tokenizer,**options):
    return subject.prepare_curriculum(rows,tokenizer=tokenizer,output_limit=options.pop("output_limit",64),
        expected_codec_sha256="b"*64,expected_rows_sha256=subject.digest(rows),**options)


def test_cumulative_stages_and_fixed_validation_preserve_all_ready_pairs():
    rows,tokenizer=inputs();original=deepcopy((rows,tokenizer));plan=prepare(rows,tokenizer)
    assert plan["ready"] is True and plan["blocked_row_count"]==0
    assert plan["stages"][0]["training_ids"]==["row-0"]
    assert plan["stages"][1]["status"]=="unchanged"
    assert plan["stages"][2]["training_ids"]==["row-0","row-1"]
    assert plan["stages"][4]["training_ids"]==plan["final_training_ids"]==["row-0","row-1","row-2"]
    assert plan["fixed_all_length_validation_ids"]==["row-3"]
    assert all(not s["training_executed"] and s["epochs_executed"]==0 for s in plan["stages"])
    assert all(plan[k] is False for k in subject.FALSE)
    assert (rows,tokenizer)==original


def test_empty_source_bins_remain_empty_and_not_fake_training_stages():
    rows,tokenizer=inputs();rows=rows[1:];plan=prepare(rows,tokenizer)
    assert [s["status"] for s in plan["stages"][:2]]==["empty","empty"]
    assert plan["stages"][2]["new_training_ids"]==["row-1"]


def test_source_and_target_budgets_are_independent():
    rows,tokenizer=inputs();rows[0]["target_ids"]=[1]+[3]*70+[2]
    blocked=prepare(rows,tokenizer);ready=prepare(rows,tokenizer,output_limit=128)
    assert blocked["rows"][0]["source_tokens"]==ready["rows"][0]["source_tokens"]==12
    assert blocked["rows"][0]["reasons"]==["complete_target_exceeds_output_limit"]
    assert ready["rows"][0]["status"]=="ready" and len(rows[0]["target_ids"])==72
    assert blocked["selected_row_count"]==4 and blocked["ready"] is False


@pytest.mark.parametrize("key,value,reason",[("truncated",True,"source_forward_truncated_or_incomplete"),
    ("forward_token_count",8,"source_forward_truncated_or_incomplete"),("padded",True,"artificial_source_padding_forbidden"),
    ("tokenizer_sha256","f"*64,"source_token_provenance_mismatch"),
    ("source_sha256","f"*64,"source_token_provenance_mismatch"),
    ("encoder_context_tokens",1024,"source_token_provenance_mismatch")])
def test_token_receipt_mismatch_is_explicit_blocker(key,value,reason):
    rows,t=inputs();rows[0]["source_tokens"][key]=value;plan=prepare(rows,t)
    assert reason in plan["rows"][0]["reasons"] and plan["ready"] is False
    assert "row-0" not in plan["final_training_ids"]


def test_missing_receipt_stays_in_denominator():
    rows,t=inputs();rows[0]["source_tokens"]=None;plan=prepare(rows,t)
    assert plan["selected_row_count"]==4 and plan["blocked_row_count"]==1
    assert plan["rows"][0]["reasons"]==["source_token_receipt_missing"]


def test_over_encoder_context_not_solved_by_larger_source_bin_or_output_cap():
    rows,t=inputs();rows[0]["source_tokens"].update(token_count=600,forward_token_count=600)
    plan=prepare(rows,t,source_bins=[16,1024],output_limit=1024)
    assert plan["rows"][0]["reasons"]==["source_exceeds_fixed_encoder_context"]
    assert plan["tokenizer"]["encoder_context_tokens"]==512


def test_above_largest_curriculum_bin_is_preserved_blocked():
    rows,t=inputs();plan=prepare(rows,t,source_bins=[16,32])
    assert plan["selected_row_count"]==4 and plan["blocked_row_count"]==3
    assert all("source_exceeds_largest_curriculum_bin" in r["reasons"] for r in plan["rows"][1:])


@pytest.mark.parametrize("change,reason",[("split","component_split_mismatch"),("text","component_source_mismatch"),
    ("bounds","component_boundary_invalid"),("target","complete_ordered_component_targets_missing")])
def test_original_component_boundary_and_target_coverage_not_inferred(change,reason):
    rows,t=inputs();r=rows[0]
    if change=="split":r["components"][0]["split"]="test"
    elif change=="text":r["components"][0]["source_text"]="altered source"
    elif change=="bounds":r["components"][0]["end_char"]+=1
    else:r["target_component_ids"]=[]
    assert reason in prepare(rows,t)["rows"][0]["reasons"]


def test_adding_unrepresented_connective_between_original_clauses_is_blocked():
    rows,t=inputs();r=rows[0];r["source_text"]="Unless emergency, "+r["source_text"]
    r["source_sha256"]=sha(r["source_text"]);r["source_tokens"]["source_sha256"]=r["source_sha256"]
    r["components"][0]["start_char"]+=18;r["components"][0]["end_char"]+=18
    assert "uncovered_source_text" in prepare(rows,t)["rows"][0]["reasons"]


def test_whitespace_join_preserves_two_complete_component_targets():
    rows,t=inputs();a,b=rows[:2];text=a["source_text"]+"\n\n"+b["source_text"]
    c=deepcopy(b["components"][0]);c["start_char"]+=len(a["source_text"])+2;c["end_char"]+=len(a["source_text"])+2
    a["source_text"]=text;a["source_sha256"]=sha(text);a["source_tokens"]["source_sha256"]=sha(text)
    a["components"].append(c);a["target_component_ids"].append(c["id"])
    assert prepare(rows,t)["rows"][0]["status"]=="ready"


@pytest.mark.parametrize("key",["group_id","source_sha256","id"])
def test_original_component_cross_split_leakage_not_hidden_by_paragraph_groups(key):
    rows,t=inputs();rows[-1]["components"][0][key]=rows[0]["components"][0][key]
    plan=prepare(rows,t)
    assert any("cross_split" in reason for reason in plan["rows"][0]["reasons"])
    assert any("cross_split" in reason for reason in plan["rows"][-1]["reasons"])
    assert plan["ready"] is False


def test_unknown_codec_or_unsupported_target_stays_blocked():
    rows,t=inputs();rows[0]["codec_sha256"]="c"*64;rows[1]["target_status"]="unsupported"
    plan=prepare(rows,t)
    assert "target_codec_mismatch" in plan["rows"][0]["reasons"]
    assert "target_codec_unsupported" in plan["rows"][1]["reasons"]


def test_no_validation_or_no_training_is_not_ready():
    rows,t=inputs()
    assert prepare(rows[:-1],t)["ready"] is False
    assert prepare(rows[-1:],t)["ready"] is False


def test_test_rows_never_enter_training_stages_or_fixed_validation():
    rows,t=inputs();r=rows[-1];r["split"]="test";r["components"][0]["split"]="test"
    plan=prepare(rows,t)
    assert all("row-3" not in s["training_ids"] for s in plan["stages"])
    assert plan["fixed_all_length_validation_ids"]==[]


def test_immutable_rows_and_plan_replay():
    rows,t=inputs();options=dict(tokenizer=t,output_limit=64,expected_codec_sha256="b"*64,expected_rows_sha256=subject.digest(rows))
    plan=subject.prepare_curriculum(rows,**options)
    assert subject.validate_curriculum(plan,rows,**options)==plan
    changed=deepcopy(rows);changed[0]["source_tokens"]["token_count"]=20
    with pytest.raises(ValueError,match="immutable"):subject.prepare_curriculum(changed,**options)
    plan["final_training_ids"]=[]
    with pytest.raises(ValueError,match="differs"):subject.validate_curriculum(plan,rows,**options)


@pytest.mark.parametrize("bins",[[],[True],[32,16],[16,16],[9000]])
def test_bad_source_bins_refused(bins):
    rows,t=inputs()
    with pytest.raises(ValueError):prepare(rows,t,source_bins=bins)


def paragraph_input():
    rows,t=inputs();r=rows[0];c=r["components"][0];rule={"actor":"Actor 0","action":"retain"}
    target={"rules":[rule]};c=deepcopy(c);c["target_sha256"]=subject.digest(target)
    c.update(position=0,char_start=c.pop("start_char"),char_end=c.pop("end_char"),byte_start=0,
        byte_end=len(r["source_text"].encode()),original_metadata={"split":"train"})
    row={**r,"components":[c],"target":target,"target_sha256":subject.digest(target),
        "embedding_result":{"input_id":r["id"],"status":"embedded",
            "tokens":{"input_ids":[101,3,4,102],"attention_mask":[1,1,1,1]},"vector":None}}
    return row,t


def adapt(row,t):
    return subject.paragraph_rows([row],tokenizer_sha256=t["sha256"],tokenizer_profile_id=t["profile_id"],
        encoder_context_tokens=t["encoder_context_tokens"],codec_sha256="b"*64)


def test_paragraph_adapter_joins_actual_fullsource_forward_tokens_without_model_claim():
    row,t=paragraph_input();old=deepcopy(row);converted=adapt(row,t)
    assert converted[0]["source_tokens"]["token_count"]==converted[0]["source_tokens"]["forward_token_count"]==4
    assert converted[0]["components"][0]["source_text"]==row["source_text"]
    assert converted[0]["target_component_ids"]==[row["components"][0]["id"]]
    assert row==old


@pytest.mark.parametrize("field,value",[("position",1),("byte_end",1),("target_sha256","f"*64),
    ("source_sha256","f"*64)])
def test_paragraph_adapter_rejects_altered_original_component(field,value):
    row,t=paragraph_input();row["components"][0][field]=value
    with pytest.raises(ValueError):adapt(row,t)


def test_missing_and_overlimit_actual_encoding_preserved_as_blockers():
    row,t=paragraph_input();row["embedding_result"]=None
    converted=adapt(row,t);assert prepare(converted,t)["rows"][0]["reasons"]==["source_token_receipt_missing"]
    row,t=paragraph_input();row["embedding_result"].update(status="token_limit_exceeded",tokens={"input_ids":[9]*513,"attention_mask":[1]*513})
    converted=adapt(row,t);plan=prepare(converted,t)
    assert converted[0]["source_tokens"]["forward_token_count"]==0
    assert "source_exceeds_fixed_encoder_context" in plan["rows"][0]["reasons"]
    assert plan["selected_row_count"]==1 and plan["blocked_row_count"]==1


def test_paragraph_adapter_rejects_cross_source_embedding_or_padding():
    row,t=paragraph_input();row["embedding_result"]["input_id"]="wrong"
    with pytest.raises(ValueError,match="source ID"):adapt(row,t)
    row,t=paragraph_input();row["embedding_result"]["tokens"]["attention_mask"][-1]=0
    with pytest.raises(ValueError,match="unpadded"):adapt(row,t)


def test_paragraph_adapter_preserves_unicode_source_and_producer_target_hashes():
    import json
    row,t=paragraph_input()
    source="L’agence doit conserver le dossier."
    row.update(source_text=source,source_sha256=sha(source))
    row["target"]["rules"][0]["actor"]="L’agence"
    target_sha=sha(json.dumps(row["target"],sort_keys=True,separators=(",", ":"),
        ensure_ascii=True,allow_nan=False))
    row["target_sha256"]=target_sha
    row["components"][0].update(source_sha256=sha(source),char_end=len(source),
        byte_end=len(source.encode()),target_sha256=target_sha)
    converted=adapt(row,t)
    assert converted[0]["components"][0]["source_text"]==source
    assert converted[0]["components"][0]["target_sha256"]==target_sha
    plan=prepare(converted,t)
    assert plan["ready_row_count"]==1
    assert plan["requires_optimizer_continuity_between_stages"] is True
    assert plan["training_executed"] is False
