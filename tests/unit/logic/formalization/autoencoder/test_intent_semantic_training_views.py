"""Source-bound native Intent semantics, real rule parsers and real Lean checks."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v4 as previous
from ipfs_datasets_py.logic.formalization.autoencoder import intent_semantic_training_views as api
from ipfs_datasets_py.logic.formalization.autoencoder import native_intent_semantic_lean as emit
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as old
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake as lake
from ipfs_datasets_py.logic.intent_ir.schema import (IntentIRDocument, IntentKind, IntentStatement,
    StatementKind, IntentModality, IntentAction, SourceRef)


def document(modality="required", assumption=False, contract=False, actors=1, role="goal"):
    ref = SourceRef("source", "urn:authored:intent-semantic", "authored", "v1", content_sha256="b" * 64)
    statements = [IntentStatement("goal", StatementKind(role), IntentModality(modality),
        "Officer publishes report.", ("source",), "publish", ("officer", "report"))]
    if role != "goal":
        statements.append(IntentStatement("requiredgoal", StatementKind.GOAL, IntentModality.REQUIRED,
            "Officer publishes report.", ("source",), "publish", ("officer", "report")))
    if assumption:
        statements.append(IntentStatement("assumption", StatementKind.ASSUMPTION, IntentModality.ASSERTED,
            "Report exists.", ("source",), "exists", ("report",)))
    if contract:
        statements.extend([IntentStatement("pre", StatementKind.PRECONDITION, IntentModality.ASSERTED,
            "Report exists.", ("source",), "exists", ("report",)),
            IntentStatement("post", StatementKind.EFFECT, IntentModality.ASSERTED,
            "Report published.", ("source",), "published", ("report",))])
    actions = tuple(IntentAction("action:"+str(i), "officer", "publish", ("report",), ("source",),
        precondition_ids=("pre",) if contract else (), effect_ids=("post",) if contract else ()) for i in range(actors))
    return IntentIRDocument("intent:semantic", "Authored native semantic intent", IntentKind.PROCEDURE if actions else IntentKind.DECLARATIVE,
        (ref,), tuple(statements), actions, (), (actions[0].action_id,) if actions else (),
        (actions[-1].action_id,) if actions else ())


def transformed(**kwargs):
    inputs={"document":document(**kwargs)}
    original=previous.prepare_family_training_targets_v4("intent_ir", **inputs)
    return original, api.transform(original, inputs)


def qualified_document(index=0):
    """Closed authored O+I+FO+nonvacuous contract fixture; no source truth claim."""
    base=document(assumption=True,contract=True)
    intended=IntentStatement("intendedgoal",StatementKind.GOAL,IntentModality.ASSERTED,
        "Officer intends to publish report.",("source",),"publish",("officer","report"))
    ref=replace(base.sources[0],source_id="authored:"+str(index),
        content_sha256=hashlib.sha256(("authored native Intent fixture "+str(index)).encode()).hexdigest())
    return replace(base,document_id="intent:qualified:"+str(index),sources=(ref,),
        statements=(*base.statements,intended))


def test_full_floor_fixture_has_O_I_FO_and_retained_nonvacuous_contract():
    inputs={"document":qualified_document()}
    original=previous.prepare_family_training_targets_v4("intent_ir",**inputs)
    result=api.transform(original,inputs)
    assert not result["intent_semantic_replacement_accounting"]["blocked"]
    for family in ("first_order","deontic","intention_agency","datalog","horn_chc"):
        _,details=emit.emit_projection(target(result,family),report=result)
        assert details["capability_floor_eligible"]
    contract=next(p for p in result["projections"] if p["projection_id"]=="intent-route/action-hoare/v1")
    _,details=api.old.emit_projection(contract,report=result)
    assert details["capability_floor_eligible"]


def target(report, family):
    return next(p for p in report["projections"] if p["projection_id"]==api.PREFIX+family+"/v1")


@pytest.mark.parametrize("modality,operator,family",[("required","O","deontic"),("permitted","P","deontic"),
    ("prohibited","F","deontic"),("asserted","I","intention_agency"),("intended","I","intention_agency")])
def test_goals_remain_native_modal_formulas_never_ordinary_world_facts(modality,operator,family):
    original, result=transformed(modality=modality)
    assert not any(p["projection_id"]==api.PREFIX+"first_order/v1" for p in result["projections"])
    p=target(result,family); source,details=emit.emit_projection(p,report=result)
    assert details["operators"]==[operator]
    assert ('deontic:'+operator in source) if family=="deontic" else ('i.cognitive "I" (i.agent "officer")' in source)
    assert not details["goals_asserted_true"]
    assert len(result["superseded_intent_observations"])==3
    assert [r for r in original["projections"] if r["projection_id"] in api.REPLACED]==[
        {k:v for k,v in r.items() if k not in ("active_for_training","superseded_reason")}
        for r in result["superseded_intent_observations"]]


def test_asserted_assumption_is_distinct_first_order_formula():
    _,result=transformed(assumption=True)
    p=target(result,"first_order"); source,details=emit.emit_projection(p,report=result)
    assert 'i.atom "exists" [(i.constant "report")]' in source
    assert details["operators"]==["predicate"]
    assert [r["statement_id"] for r in p["payload"]["records"]]==["assumption"]


@pytest.mark.parametrize("family",["datalog","horn_chc"])
@pytest.mark.parametrize("assumption",[False,True])
def test_rule_program_exact_native_readback_and_semantic_formula_bindings(family,assumption):
    _,result=transformed(assumption=assumption)
    p=target(result,family); program=p["payload"]["rule_program"]
    assert len(program["native_chc"]["clauses"])==1+assumption
    assert not program["native_chc"]["loss_receipts"]
    assert not program["facts_asserted_true"] and not program["least_fixed_point_executed"]
    source,details=emit.emit_projection(p,report=result)
    assert 'programSatisfaction' in source and 'deontic:O' in source
    assert details["capability_floor_eligible"] is assumption
    assert 'intent_field' not in program["source"] and 'intent_kind' not in program["source"]


def test_complete_record_accounting_including_contract_preconditions_and_actions():
    _,result=transformed(assumption=True,contract=True)
    accounted=result["intent_semantic_replacement_accounting"]
    assert {r["statement_id"] for r in accounted["statement_accounting"]}=={"goal","assumption","pre","post"}
    for r in accounted["statement_accounting"]:
        if r["statement_id"] in ("pre","post"):
            assert r["replacement_projection_ids"]==["intent-route/action-hoare/v1"]
    assert accounted["action_accounting"][0]["replacement_projection_ids"]==["intent-route/action-hoare/v1"]
    assert not accounted["observed_events"]
    assert len(target(result,"datalog")["payload"]["records"])==2


@pytest.mark.parametrize("kwargs",[{"modality":"recommended"},{"modality":"intended","actors":0},
    {"modality":"asserted","actors":2},{"role":"verification","modality":"asserted"}])
def test_unknown_force_actor_or_role_stays_active_and_blocks_ground_views(kwargs):
    _,result=transformed(**kwargs)
    assert target(result,"unhandled")["ready_for_training"] is False
    assert result["intent_semantic_replacement_accounting"]["blocked"]
    for family in ("datalog","horn_chc"):
        p=target(result,family)
        assert not p["ready_for_training"]
        with pytest.raises((ValueError,old.UnsupportedNativeLean)):
            emit.emit_projection(p,report=result)


@pytest.mark.parametrize("change",["operator","actor","arguments","rule_source","native_chc","record_omitted","fake_event"])
def test_semantic_or_native_rule_tampering_fails_source_replay(change):
    _,result=transformed(assumption=True)
    p=target(result,"datalog");payload=p["payload"]
    if change=="operator":payload["records"][-1]["operator"]="predicate"
    elif change=="actor":payload["records"][-1]["actor"]="forged"
    elif change=="arguments":payload["records"][-1]["body"]["arguments"].reverse()
    elif change=="rule_source":payload["rule_program"]["source"]+='observed("publish").\n'
    elif change=="native_chc":payload["rule_program"]["native_chc"]["clauses"].pop()
    elif change=="record_omitted":payload["records"].pop()
    else:payload["semantic_source"]["observed_events"]=["publish"]
    with pytest.raises((ValueError,old.UnsupportedNativeLean)):
        emit.emit_projection(p,report=result)


def test_foreign_source_and_producer_drift_are_rejected(monkeypatch):
    inputs={"document":document()}
    original=previous.prepare_family_training_targets_v4("intent_ir",**inputs)
    with pytest.raises(ValueError,match="replay"):
        api.transform(original,{"document":document(modality="permitted")})
    monkeypatch.setitem(api._PINS,api.__name__,"0"*64)
    with pytest.raises(ValueError,match="producer drift"):
        api.semantic_document(inputs["document"])


def test_narrowed_first_order_request_cannot_hide_actual_modal_family():
    inputs={"document":document()}
    original=previous.prepare_family_training_targets_v4("intent_ir",requested_families=["first_order"],**inputs)
    with pytest.raises(ValueError,match="actual families"):
        api.transform(original,inputs)


def test_original_rich_atomic_panel_uses_exact_existing_native_owner():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel
    inputs=panel.source_inputs(panel.rows("intent_ir","train")[0])
    assert inputs["document"]["kind"]=="atom"
    original=previous.prepare_family_training_targets_v4("intent_ir",**inputs)
    result=api.transform(original,inputs)
    expected=api.rich_logic.project_rich_intent_logic(inputs["document"],instruction=inputs["source_text"])["native_intent_ir"]
    assert result["intent_semantic_replacement_accounting"]["native_document"]==expected
    assert not result["intent_semantic_replacement_accounting"]["blocked"]
    for family in ("deontic","datalog","horn_chc"):
        emit.emit_projection(target(result,family),report=result)
    with pytest.raises(ValueError):
        api.transform(original,{**inputs,"source_text":"An unrelated instruction."})


def test_explicit_full_request_replay_is_same_and_changed_request_is_rejected():
    inputs={"document":qualified_document()}
    original=previous.prepare_family_training_targets_v4("intent_ir",**inputs)
    expected=api.transform(original,inputs)
    assert api.transform(original,{**inputs,"requested_families":original["requested_families"]})==expected
    with pytest.raises(ValueError,match="family request differs"):
        api.transform(original,{**inputs,"requested_families":["first_order"]})


def test_rich_nonatom_without_old_mixed_rows_is_unchanged():
    text="officer must publish report and officer must archive report."
    inputs={"document":api.rich_grammar.parse_instruction(text),"source_text":text}
    assert inputs["document"]["kind"]!="atom"
    original=previous.prepare_family_training_targets_v4("intent_ir",**inputs)
    assert not any(p["projection_id"] in api.REPLACED for p in original["projections"])
    assert api.transform(original,inputs)==original


def test_real_lake_checks_all_semantics_and_rejects_goal_compliance_inference():
    executable=Path('/home/barberb/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lake')
    if not executable.is_file():pytest.skip('installed native Lake unavailable')
    parts=[]
    for index,(modality,assumption) in enumerate([('required',False),('permitted',True),('prohibited',False),('asserted',False)]):
        _,result=transformed(modality=modality,assumption=assumption)
        for p in result['projections']:
            if p['projection_id'].startswith(api.PREFIX):
                source,_=emit.emit_projection(p,report=result)
                namespace='Case'+str(len(parts))
                parts.append('namespace '+namespace+'\n'+source+'\nend '+namespace)
    _,result=transformed()
    norm,_=emit.emit_projection(target(result,'deontic'),report=result)
    counter='''def counterModel : Interpretation Unit Unit where
  agent := fun _ => ()
  cognitive := fun _ _ _ _ => True
  constant := fun _ => ()
  function := fun _ _ => ()
  atom := fun _ _ _ => False
  modal := fun _ _ _ _ _ => True
  frame := fun _ _ _ => False
  frameScalar := fun _ _ => ()
  member := fun _ _ => False
  subclass := fun _ _ => False
example : formula_0 counterModel 0 := by trivial
example : ¬ counterModel.atom "publish" [(), ()] 0 := by simp [counterModel]
'''
    good='namespace IntentIR\n'+old.PRELUDE+'\n'+'\n'.join(parts)+'\n'+norm+'\n'+counter+'\nend IntentIR\n'
    outcome=lake._execute(good,'IntentIR',str(executable),30)
    assert outcome['status']=='passed',outcome
    false_proof='example : counterModel.atom "publish" [(), ()] 0 := by exact (show formula_0 counterModel 0 from by trivial)\n'
    bad=good.replace('end IntentIR\n',false_proof+'end IntentIR\n')
    outcome=lake._execute(bad,'IntentIR',str(executable),30)
    assert outcome['backend_executed'] and outcome['status']=='failed' and not outcome['timed_out'],outcome
    assert 'type mismatch' in outcome['stdout'].lower() or 'type mismatch' in outcome['stderr'].lower()
