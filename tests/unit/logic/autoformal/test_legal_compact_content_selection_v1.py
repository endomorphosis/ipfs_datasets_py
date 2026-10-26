"""Authored full-vector selection controls, not numerical model predictions.

Retained A/B literals are copied by AST-only inspection of the qualified token
suite. Their engineering context is independently committed, not authenticated
for held-out inference. No historical fixture imports occur at test runtime.
"""
from copy import deepcopy
import hashlib
import inspect
import json
import math
import re
import sys

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_selection_v1 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1 as tokens


CONTENT_RAW = {'A': b'{"schema":"legal-relational-compact-content/v1","tree":["forall",0,["forall",1,["forall",2,["implies",["extension","P",["or",["predicate",0,[["variable",0],["variable",1]]],["predicate",1,[["variable",0],["variable",1]]]]],["predicate",2,[["variable",2],["variable",0]]]]]]]}', 'B': b'{"schema":"legal-relational-compact-content/v1","tree":["forall",0,["forall",1,["forall",2,["extension","P",["implies",["or",["predicate",0,[["variable",0],["variable",1]]],["predicate",1,[["variable",0],["variable",1]]]],["predicate",2,[["variable",2],["variable",0]]]]]]]]}'}
CONTEXT_RAW = b'{"argument_roles":[{"roles":["recipient","duties"],"symbol":"Assign"},{"roles":["recipient","duties"],"symbol":"Transfer"},{"roles":["approver","recipient"],"symbol":"Approve"}],"schema":"legal-relational-compact-context/v1","signature":{"family":{"interface":"LogicIdentityNamespaces@1","namespace":"family","schema_version":"logic-identity-namespaces/v1","value":"tdfol","version":"1.0.0"},"features":[],"interface":"LogicSignature@1","metadata":{},"profile":{"interface":"LogicIdentityNamespaces@1","namespace":"profile","schema_version":"logic-identity-namespaces/v1","value":"tdfol_default","version":"1.0.0"},"schema_version":"syntax-logic-signature/v1","sorts":[{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"symbols":[{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Assign","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Transfer","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"},{"domain":[{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"},{"arguments":[],"kind":"atomic","name":"Object","schema_version":"syntax-logic-sort/v1"}],"kind":"predicate","metadata":{},"name":"Approve","range":{"arguments":[],"kind":"bool","name":"Bool","schema_version":"syntax-logic-sort/v1"},"schema_version":"syntax-symbol-declaration/v1"}]}}'

CONTEXT_SHA = "64c9e1574f5c344936cea743adbfda6004d6f5f81b153df10ad25d9f6a9c87af"
CONTENT_SHA = {
    "A": "719ce8351155bf64f096997dada4e493b401c1ae1b816cda47cbb07e4ab81427",
    "B": "61d5c35821044d0a1d73a750378002a025e01143dc1cf935e86520f644f33485",
}
LEXICAL = re.compile(r'"(?:[^"\\]|\\.)*"|0|[1-9][0-9]*|[{}\[\],:]')


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw): return hashlib.sha256(raw).hexdigest()


def ctx(): return json.loads(CONTEXT_RAW)


def content(label="A"): return json.loads(CONTENT_RAW[label])


@pytest.fixture(scope="module")
def codec(): return tokens.build_compact_content_token_codec_v1()


def codec_sha(codec): return tokens.compact_content_token_codec_sha256(codec)


def ids_for(value, codec, *, eos=True):
    raw=wire(value).decode("utf-8"); lexical=LEXICAL.findall(raw)
    assert "".join(lexical)==raw
    lookup={value:index for index,value in enumerate(codec["vocabulary"])}
    return [1, *(lookup[value] for value in lexical), *([2] if eos else [])]


def prefix(prefix_ids, context, codec):
    raw=wire(context)
    return tokens.compact_content_allowed_token_ids_v1(prefix_ids, raw,
        expected_context_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha(codec))


def select(logits, prefix_ids, context, codec):
    raw=wire(context)
    return subject.select_compact_content_token_v1(logits,prefix_ids,raw,
        expected_context_sha256=sha(raw),codec=codec,expected_codec_sha256=codec_sha(codec))


def scores(value=-10): return [value for _ in range(537)]


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"]==0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"]==0
    assert report["logits_origin_verified"] is False
    assert report["head_compatibility_qualified"] is False
    upstream=report["prefix_report"]
    assert all(value is False for value in upstream["authority"].values())
    assert upstream["training_mask"]==upstream["evaluation_gold_mask"]==0
    assert upstream["local_prefix_only"] is True and upstream["global_completability_proven"] is False


@pytest.mark.parametrize("label", ["A", "B"])
def test_selection_actual_prefixes_full_public_mask_with_authored_PAD_bias_retains_all_scores(label,codec):
    """Programmed target-next scores are an exposed fixture, not a model."""
    assert sha(CONTENT_RAW[label])==CONTENT_SHA[label] and sha(CONTEXT_RAW)==CONTEXT_SHA
    target=ids_for(content(label),codec)
    assert len(target)==101 and codec["vocabulary_size"]==537
    for position in range(len(target)):
        offered=target[:position];desired=target[position]
        logits=scores();logits[0]=100;logits[desired]=99.0
        before=deepcopy((logits,offered,codec))
        report=select(logits,offered,ctx(),codec)
        assert report["prefix_report"]==prefix(offered,ctx(),codec)
        assert report["status"]=="selected" and report["reason"] is None
        assert report["offered_prefix_ids"]==offered
        assert report["next_prefix_ids"]==offered+[desired]
        assert report["raw_argmax_token_id"]==0 and report["raw_argmax_score"]==100
        assert report["selected_token_id"]==desired and report["selected_score"]==99.0
        assert type(report["selected_score"]) is float
        assert report["selection_performed"] is True
        assert report["selection_overrode_raw_argmax"] is True and report["tokens_appended"]==1
        assert report["logits"]==logits and len(report["logits"])==537
        assert report["logits_sha256"]==sha(wire(logits))
        assert report["tie_breaker"]=="lowest_token_id"
        assert (logits,offered,codec)==before
        no_authority(report)


def test_selection_api_accepts_no_expected_target_sidecar_or_model():
    assert set(inspect.signature(subject.select_compact_content_token_v1).parameters)=={
        "logits","prefix_ids","context_raw","expected_context_sha256","codec","expected_codec_sha256"}


def test_selection_allowed_raw_argmax_is_retained_without_override(codec):
    offered=ids_for(content(),codec)[:1]
    desired=prefix(offered,ctx(),codec)["allowed_token_ids"][0]
    logits=scores();logits[desired]=50
    report=select(logits,offered,ctx(),codec)
    assert report["raw_argmax_token_id"]==report["selected_token_id"]==desired
    assert report["raw_argmax_score"]==report["selected_score"]==50
    assert report["selection_overrode_raw_argmax"] is False
    assert report["next_prefix_ids"]==offered+[desired]
    no_authority(report)


def test_selection_global_and_allowed_score_ties_choose_lowest_integer_id(codec):
    #Stop immediately before an actual variable index, with3active binders.
    lexical=LEXICAL.findall(CONTENT_RAW["A"].decode())
    offset=lexical.index('"variable"')+2
    lookup={value:index for index,value in enumerate(codec["vocabulary"])}
    offered=[1,*(lookup[value] for value in lexical[:offset])]
    allowed=prefix(offered,ctx(),codec)["allowed_token_ids"]
    assert allowed==sorted([lookup["0"],lookup["1"],lookup["2"]])
    logits=scores(0)
    report=select(logits,offered,ctx(),codec)
    assert report["raw_argmax_token_id"]==0
    assert report["selected_token_id"]==min(allowed)
    assert report["selected_token_id"] in allowed
    assert report["selection_overrode_raw_argmax"] is True


def test_selection_empty_prefix_BOS_and_explicit_scored_EOS_are_steps_not_intake_repairs(codec):
    for offered,desired in [([],1),(ids_for(content(),codec)[:-1],2)]:
        logits=scores();logits[0]=10;logits[desired]=9
        report=select(logits,offered,ctx(),codec)
        assert report["selected_token_id"]==desired
        assert report["next_prefix_ids"]==offered+[desired]
        assert report["tokens_appended"]==1 and report["selection_performed"] is True
        assert report["logits"]==logits


def test_selection_complete_vector_hash_retains_mixed_types_and_negative_zero(codec):
    offered=[1];desired=prefix(offered,ctx(),codec)["allowed_token_ids"][0]
    logits=scores(-3);logits[0]=-0.0;logits[desired]=-0.0;logits[5]=0.0
    report=select(logits,offered,ctx(),codec)
    assert report["logits_sha256"]==sha(wire(logits))
    assert all(type(left) is type(right) for left,right in zip(report["logits"],logits))
    assert math.copysign(1.0,report["logits"][0])==-1.0
    assert math.copysign(1.0,report["logits"][5])==1.0
    assert math.copysign(1.0,report["raw_argmax_score"])==-1.0
    assert math.copysign(1.0,report["selected_score"])==-1.0
    changed=list(logits);changed[0]=0.0
    assert sha(wire(changed))!=report["logits_sha256"]


@pytest.mark.parametrize("value", [sys.float_info.max,-sys.float_info.max,(1<<53)-1,-((1<<53)-1)])
def test_selection_finite_float_extremes_and_safe_integer_boundary_are_admitted_without_tensor_cast(value,codec):
    logits=scores();logits[0]=value
    report=select(logits,[1],ctx(),codec)
    assert report["logits"][0]==value and type(report["logits"][0]) is type(value)
    assert report["logits_sha256"]==sha(wire(logits))
    no_authority(report)


def unary_context():
    context=ctx();symbol=deepcopy(context["signature"]["symbols"][0])
    symbol["name"]="Eligible";symbol["domain"]=symbol["domain"][:1]
    context["signature"]["symbols"]=[symbol]
    context["argument_roles"]=[{"symbol":"Eligible","roles":["subject"]}]
    return context


def balanced(rows):
    while len(rows)>1:
        grouped=[["and",rows[i],rows[i+1]] for i in range(0,len(rows)-1,2)]
        if len(rows)%2:grouped.append(rows[-1])
        rows=grouped
    return rows[0]


def unfinishable_limit_prefix(codec):
    body=balanced([["predicate",0,[["variable",0]]] for _ in range(27)])
    value={"schema":tokens.CONTENT_SCHEMA,
        "tree":["forall",0,["exists",1,["not",["not",["not",body]]]]]}
    ids=ids_for(value,codec,eos=False)
    assert len(ids)==514
    return ids[:512]


@pytest.mark.parametrize("case", ["complete","rejected","interior_PAD","local_dead_end","budget_exhausted"])
def test_selection_no_allowed_tokens_preserves_prefix_and_scores_without_selection_or_repair(case,codec):
    context=ctx()
    if case=="complete":offered=ids_for(content(),codec)
    elif case=="rejected":offered=[1,-1]
    elif case=="interior_PAD":offered=[1,0]
    elif case=="budget_exhausted":context=unary_context();offered=unfinishable_limit_prefix(codec)
    else:
        value={"schema":tokens.CONTENT_SCHEMA,
            "tree":["forall",0,["predicate",0,[["variable",0],["variable",0]]]]}
        offered=ids_for(value,codec,eos=False)[:-1]
    upstream=prefix(offered,context,codec)
    assert upstream["allowed_token_ids"]==[]
    assert upstream["status"]==("complete" if case=="complete" else "budget_exhausted" if case=="budget_exhausted" else "rejected")
    logits=scores();logits[2]=100
    report=select(logits,offered,context,codec)
    assert report["status"]=="no_selection"
    assert report["reason"]==(upstream["reason"] if upstream["reason"] is not None else upstream["status"])
    assert report["prefix_status"]==upstream["status"]
    assert report["prefix_report"]==upstream
    assert report["selected_token_id"] is None and report["selected_score"] is None
    assert report["selection_performed"] is False and report["selection_overrode_raw_argmax"] is False
    assert report["tokens_appended"]==0
    assert report["next_prefix_ids"]==report["offered_prefix_ids"]==offered
    assert report["raw_argmax_token_id"]==2 and report["raw_argmax_score"]==100
    assert report["logits"]==logits and report["logits_sha256"]==sha(wire(logits))
    no_authority(report)


class ScalarFloat(float): pass
class ScalarInt(int): pass
class VectorList(list): pass
class ArrayProtocol:
    def __len__(self):raise AssertionError("array-like length must not be coerced")
    def __array__(self,*args,**kwargs):raise AssertionError("array conversion must not run")
    def tolist(self):raise AssertionError("tolist conversion must not run")
class ScalarProtocol:
    def __float__(self):raise AssertionError("scalar conversion must not run")


@pytest.mark.parametrize("kind", ["none","tuple","short","long","list_subclass","array_protocol"])
def test_selection_score_vector_requires_exact_full_plain_list_without_array_conversion(kind,codec):
    value={"none":None,"tuple":tuple(scores()),"short":scores()[:-1],"long":scores()+[0],
           "list_subclass":VectorList(scores()),"array_protocol":ArrayProtocol()}[kind]
    with pytest.raises(ValueError):select(value,[1],ctx(),codec)


@pytest.mark.parametrize("kind", ["bool","nan","positive_inf","negative_inf","float_overflow","unsafe_integer","unsafe_negative_integer","large_integer","string","none","float_subclass","int_subclass","scalar_protocol"])
def test_selection_every_score_even_masked_PAD_requires_exact_finite_safe_numeric_value(kind,codec):
    bad={"bool":True,"nan":float("nan"),"positive_inf":float("inf"),"negative_inf":-float("inf"),
         "float_overflow":float("1e999"),"unsafe_integer":1<<53,"unsafe_negative_integer":-(1<<53),
         "large_integer":1<<200,"string":"1.0","none":None,"float_subclass":ScalarFloat(1),
         "int_subclass":ScalarInt(1),"scalar_protocol":ScalarProtocol()}[kind]
    logits=scores();logits[0]=bad
    with pytest.raises(ValueError):select(logits,[1],ctx(),codec)
    #A completed prefix also cannot waive the whole-vector admission contract.
    with pytest.raises(ValueError):select(logits,ids_for(content(),codec),ctx(),codec)


@pytest.mark.parametrize("offered", [None,(),[True],[1.0],[1<<63],[1]*513])
def test_selection_prefix_api_shape_and_total_bound_errors_propagate(offered,codec):
    with pytest.raises(ValueError):select(scores(),offered,ctx(),codec)


@pytest.mark.parametrize("damage", ["context_pin","codec_pin","codec_table","context_schema","context_profile","context_extra"])
def test_selection_context_codec_or_source_contract_failure_is_not_no_selection(damage,codec):
    context=ctx();fixed=deepcopy(codec);expected_context=CONTEXT_SHA;expected_codec=codec_sha(codec)
    if damage=="context_pin":expected_context="0"*64
    elif damage=="codec_pin":expected_codec="0"*64
    elif damage=="codec_table":
        fixed["vocabulary"][3:5]=reversed(fixed["vocabulary"][3:5]);expected_codec=sha(wire(fixed))
    elif damage=="context_schema":context["schema"]+="-changed";expected_context=sha(wire(context))
    elif damage=="context_profile":context["signature"]["profile"]["value"]="unsupported";expected_context=sha(wire(context))
    else:context["source_binding"]={"accepted":True};expected_context=sha(wire(context))
    with pytest.raises(ValueError):
        subject.select_compact_content_token_v1(scores(),[1,-1],wire(context),
            expected_context_sha256=expected_context,codec=fixed,expected_codec_sha256=expected_codec)


def test_selection_changed_valid_role_context_stays_authored_and_hash_bound(codec):
    context=ctx();context["argument_roles"].reverse()
    logits=scores();offered=[1]
    report=select(logits,offered,context,codec)
    assert report["prefix_report"]==prefix(offered,context,codec)
    assert report["context_raw_sha256"]==sha(wire(context))!=CONTEXT_SHA
    no_authority(report)


def test_selection_returned_populations_are_detached_from_caller_and_from_fresh_reports(codec):
    logits=scores();offered=[1];fixed=deepcopy(codec)
    before=deepcopy((logits,offered,fixed))
    report=select(logits,offered,ctx(),fixed);original=deepcopy(report)
    report["logits"][0]=999;report["next_prefix_ids"].append(0)
    report["prefix_report"]["allowed_token_ids"].clear();report["authority"]["accepted"]=True
    assert (logits,offered,fixed)==before
    assert select(logits,offered,ctx(),fixed)==original


@pytest.mark.parametrize("error_type", [ValueError,RuntimeError,KeyboardInterrupt])
def test_selection_new_selector_loader_failure_propagates_without_substituting_upstream_owner(error_type,codec,monkeypatch):
    failure=error_type("authored selector loader failure")
    def unavailable():raise failure
    #Only the NEWselector loader seam changes. Public upstream prefix and
    #content owners are not patched or replaced.
    monkeypatch.setattr(subject,"_owner",unavailable)
    with pytest.raises(error_type) as raised:select(scores(),[1],ctx(),codec)
    assert raised.value is failure


@pytest.mark.parametrize("pin", ["_SELF_SHA","_OWNER_SHA"])
def test_selection_new_selector_real_source_pin_failure_propagates_even_for_rejected_prefix(pin,codec,monkeypatch):
    monkeypatch.setattr(subject,pin,"0"*64)
    with pytest.raises(ValueError):select(scores(),[1,-1],ctx(),codec)


@pytest.mark.parametrize("changed", ["logits","prefix","codec"])
def test_selection_caller_mutation_during_final_report_serialization_is_detected_by_input_fence(changed,codec,monkeypatch):
    logits=scores();offered=[1];fixed=deepcopy(codec)
    detach=subject._detach;seen=[]
    def changing_detach(value,maximum):
        result=detach(value,maximum)
        if type(value) is dict and value.get("schema")=="legal-compact-content-token-selection/v1":
            seen.append(True)
            if changed=="logits":logits[0]=100
            elif changed=="prefix":offered.append(0)
            else:fixed["max_sequence_tokens"]=511
        return result
    #Labelled NEWselector report-serialization/input-fence seam, not an
    #authoritative grammar or semantic-validation substitution.
    monkeypatch.setattr(subject,"_detach",changing_detach)
    with pytest.raises(ValueError):select(logits,offered,ctx(),fixed)
    assert len(seen)==1


def test_selection_final_report_serialization_precedes_actual_selector_source_closeout(codec,monkeypatch):
    detach=subject._detach;seen=[]
    def changing_detach(value,maximum):
        result=detach(value,maximum)
        if type(value) is dict and value.get("schema")=="legal-compact-content-token-selection/v1":
            seen.append(True);monkeypatch.setattr(subject,"_SELF_SHA","0"*64)
        return result
    monkeypatch.setattr(subject,"_detach",changing_detach)
    with pytest.raises(ValueError):select(scores(),[1],ctx(),codec)
    assert len(seen)==1



def test_selection_cumulative_input_alias_budget_refuses_before_any_complete_serialization(codec,monkeypatch):
    fixed=deepcopy(codec);fixed["extra_aliases"]=["x"*16384]*80
    expected=codec_sha(codec)
    def forbidden_dumps(*args,**kwargs):
        raise AssertionError("complete serialization preceded cumulative byte admission")
    #Labelled NEWselector ordinary-input admission seam; no upstream public
    #prefix call is replaced. The added repeatedstrings exceed1MiB aggregate.
    monkeypatch.setattr(subject.json,"dumps",forbidden_dumps)
    with pytest.raises(ValueError,match="before serialization"):
        subject.select_compact_content_token_v1(scores(),[1],CONTEXT_RAW,
            expected_context_sha256=CONTEXT_SHA,codec=fixed,expected_codec_sha256=expected)


def test_selection_pure_ordinary_JSON_escape_float_cycle_depth_and_item_bounds():
    value={"float":-0.0,"escape":'\\"\n\t\x01',"unicode":"é漢🙂"}
    assert subject._wire(value,len(wire(value)))==wire(value)
    with pytest.raises(ValueError):subject._wire(value,len(wire(value))-1)
    cyclic=[];cyclic.append(cyclic)
    with pytest.raises(ValueError):subject._wire(cyclic,4096)
    nested=None
    for _ in range(98):nested=[nested]
    with pytest.raises(ValueError):subject._wire(nested,4096)
    with pytest.raises(ValueError):subject._wire([None]*100001,2*1024*1024)


@pytest.mark.parametrize("error_type",[ValueError,RuntimeError,KeyboardInterrupt])
def test_selection_first_operation_error_is_preserved_if_closing_source_fence_also_fails(error_type,codec,monkeypatch):
    failure=error_type("authored first operation error")
    def unavailable():
        monkeypatch.setattr(subject,"_SELF_SHA","0"*64)
        raise failure
    #Only NEWselector loader/source metadata changes. Upstream remainsgenuine.
    monkeypatch.setattr(subject,"_owner",unavailable)
    with pytest.raises(error_type) as raised:select(scores(),[1],ctx(),codec)
    assert raised.value is failure
    assert any("closing selector" in note for note in getattr(failure,"__notes__",[]))


def test_selection_oversize_raw_context_is_whole_input_refusal_even_for_no_selection_prefix(codec):
    raw=CONTEXT_RAW+b" "*(subject.MAX_CONTEXT_BYTES+1-len(CONTEXT_RAW))
    with pytest.raises(ValueError):
        subject.select_compact_content_token_v1(scores(),[1,-1],raw,
            expected_context_sha256=sha(raw),codec=codec,expected_codec_sha256=codec_sha(codec))
