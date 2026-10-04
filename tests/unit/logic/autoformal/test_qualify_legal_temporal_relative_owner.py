"""Source joins, exact occurrence mappings and release-order failure tests."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import pytest

from scripts.ops.legal_ir import qualify_legal_temporal_relative_owner as q
from tests.unit.logic.autoformal.test_legal_temporal_owner_pointer_metrics_v2 import source, prediction
from tests.unit.logic.autoformal.test_legal_temporal_coupled_span_metrics import new_prediction
from tests.unit.logic.autoformal.test_legal_temporal_relative_owner_metrics import relative_prediction


def exact(text,literal,index=0):
    starts=[m.start() for m in q.re.finditer(q.re.escape(literal),text)];a=starts[index]
    return {'char_start':a,'char_end':a+len(literal),'text':literal}


def mapping_fixture(label='norm',repeated=False):
    text='Office shall file before Monday; Office shall record before Monday.'
    s=source(text,'before Monday');s['id']='exact-second-occurrence'
    if repeated:
        span=exact(text,'before Monday',1);s['proposed_time_span']={k:span[k] for k in ('char_start','char_end')}
    body=exact(text,text)
    action=exact(text,'record' if repeated else 'file')
    candidate={'owner_type':'norm','anchor_span':action,'scope_span':body}
    annotation={'unique_owner_occurrence_asserted':label!='ambiguous','owner_candidates':[candidate],
                'countermodels':None,'norm_occurrences':[]}
    for i,verb in enumerate(('file','record')):
        annotation['norm_occurrences'].append({'actor_span':exact(text,'Office',i),'modal_span':exact(text,'shall',i),
            'action_span':exact(text,verb),'time_span':exact(text,'before Monday',i),'clause_span':body})
    if label=='ambiguous':
        annotation['owner_candidates'].append({'owner_type':'condition','anchor_span':exact(text,'Office',1),'scope_span':body})
        annotation['countermodels']={'two_author_stipulated_readings':True}
    rich={**s,'label':label,'group_id':'source-'+s['source_sha256'],'annotation':annotation}
    target={k:rich[k] for k in q.metrics.SOURCE_KEYS|{'label','group_id'}}
    target['owner_anchor_span']=None if label=='ambiguous' else {k:action[k] for k in ('char_start','char_end')}
    return target,rich


def stage_scores():
    return {s:{'count':288,'joint_correct':180+s//100,'selection_nll':2.-s/1000} for s in q.STEPS}


def test_selection_joint_exact_before_nll_and_earliest_ties():
    scores=stage_scores();scores[100]['joint_correct']=200;scores[100]['selection_nll']=4.
    assert q.independent_selection(scores)['selected_steps']==100
    scores[200]=dict(scores[100]);assert q.independent_selection(scores)['selected_steps']==100
    scores[200]['selection_nll']=3.;assert q.independent_selection(scores)['selected_steps']==200


@pytest.mark.parametrize('mutation',[lambda v:v.pop(0),lambda v:v[100].update(count=287),
    lambda v:v[100].update(joint_correct=True),lambda v:v[100].update(joint_correct=289),
    lambda v:v[100].update(selection_nll=float('nan')),lambda v:v[100].update(selection_nll=-1)])
def test_selection_rejects_incomplete_or_ill_typed_rank(mutation):
    values=stage_scores();mutation(values)
    with pytest.raises(ValueError):q.independent_selection(values)


def test_reference_mapping_preserves_repeated_time_action_offset():
    target,rich=mapping_fixture(repeated=True)
    result=q.audit_mapping([target],[rich]);assert result['explicit_norm_time_action_joins']==1
    assert target['owner_anchor_span']['char_start']==rich['source_text'].index('record')


def test_same_type_different_occurrence_is_not_a_valid_reference_mapping():
    target,rich=mapping_fixture(repeated=True)
    first=exact(rich['source_text'],'file');rich['annotation']['owner_candidates'][0]['anchor_span']=first
    target['owner_anchor_span']={k:first[k] for k in ('char_start','char_end')}
    with pytest.raises(ValueError,match='different action occurrence'):q.audit_mapping([target],[rich])


def test_old_owner_alias_and_ambiguity_null_are_preserved():
    target,rich=mapping_fixture('ambiguous')
    for item in rich['annotation']['owner_candidates']:item['owner']=item.pop('owner_type')
    rich['annotation']['unique_owner_asserted']=rich['annotation'].pop('unique_owner_occurrence_asserted')
    result=q.audit_mapping([target],[rich]);assert result['ambiguous_nulls']==1 and result['unique_exact_anchors']==0


@pytest.mark.parametrize('mutation',[lambda t,r:t.update(owner_anchor_span={'char_start':0,'char_end':6}),
    lambda t,r:r['annotation'].update(countermodels=None),
    lambda t,r:r['annotation'].update(unique_owner_occurrence_asserted=True),
    lambda t,r:r['annotation'].update(owner_candidates=r['annotation']['owner_candidates'][:1])])
def test_ambiguity_cannot_be_forced_to_one_source_anchor(mutation):
    target,rich=mapping_fixture('ambiguous');mutation(target,rich)
    with pytest.raises(ValueError):q.audit_mapping([target],[rich])


@pytest.mark.parametrize('mutation',[lambda t,r:t.update(label='condition'),lambda t,r:t.update(group_id='different'),
    lambda t,r:t.update(source_sha256='0'*64),lambda t,r:r['annotation']['owner_candidates'][0]['scope_span'].update(char_end=2,text='Of'),
    lambda t,r:r['annotation']['owner_candidates'][0]['anchor_span'].update(char_start=True),
    lambda t,r:r['annotation']['owner_candidates'].append(deepcopy(r['annotation']['owner_candidates'][0]))])
def test_repaired_reference_mutations_fail_closed(mutation):
    target,rich=mapping_fixture();mutation(target,rich)
    with pytest.raises(ValueError):q.audit_mapping([target],[rich])


def test_utf8_corpus_commitments_do_not_change_ascii_model_digest():
    value={'source':'Duty.— Élan'}
    assert q.corpus_digest(value)==hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    assert q.corpus_digest(value)!=q.digest(value)
    assert q.digest(value)==hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def test_file_pin_detects_same_length_mutation(tmp_path):
    p=tmp_path/'input.json';p.write_text('{"x":1}');pin=q.ref(p);assert q.read(pin)=={'x':1}
    p.write_text('{"x":2}')
    with pytest.raises(ValueError,match='saved bytes'):q.read(pin)


@pytest.mark.parametrize('raw',['{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}'])
def test_duplicate_or_nonfinite_serialized_input_rejected(tmp_path,raw):
    p=tmp_path/'bad.json';p.write_text(raw)
    with pytest.raises(ValueError):q.read(q.ref(p))


def test_true_boolean_byte_count_is_not_integer_pin(tmp_path):
    p=tmp_path/'x';p.write_text('1');pin=q.ref(p);pin['bytes']=True
    with pytest.raises(ValueError):q.read(pin)


def generation_fixture():
    sources=[source()];row=relative_prediction(sources[0]);cp={'path':'/checkpoint','sha256':'a'*64,'bytes':1};sp={'path':'/sources','sha256':'b'*64,'bytes':1}
    value={'schema':'legal-temporal-relative-owner-generation/v1','checkpoint':cp,'decoder_kind':'relative_owner','sources':sp,
        'rows':[row],'encoder_batch_forwards':1,'encoder_source_evaluations':1,'source_only_input':True,
        'reference_anchors_supplied':False,'labels_supplied':False,'pipeline_promotion':False,'statutory_semantics_verified':False}
    return sources,cp,sp,value


def test_generation_retains_full_source_and_validates_pointer_policy():
    sources,cp,sp,value=generation_fixture();assert q.check_generation(value,cp,sp,sources,'relative_owner')==value['rows']


@pytest.mark.parametrize('mutation',[lambda v:v.update(reference_anchors_supplied=True),lambda v:v.update(decoder_kind='parent_coupled'),
    lambda v:v.update(encoder_batch_forwards=True),lambda v:v.update(encoder_source_evaluations=0),
    lambda v:v.update(rows=[]),lambda v:v['rows'][0].update(source_sha256='0'*64),
    lambda v:v['rows'][0].update(valid_span_count=0),lambda v:v.update(extra_reference={'label':'norm'})])
def test_source_generation_contract_tampering_rejected(mutation):
    sources,cp,sp,value=generation_fixture();mutation(value)
    with pytest.raises(ValueError):q.check_generation(value,cp,sp,sources,'relative_owner')


def test_parent_pointer_preserves_exact_coordinate_metrics_without_new_interaction_fields():
    sources,cp,sp,value=generation_fixture();value['decoder_kind']='parent_coupled'
    value['rows']=[new_prediction(sources[0])]
    rows=q.check_generation(value,cp,sp,sources,'parent_coupled')
    assert rows[0]['raw_owner_anchor_span'] is not None and not set(rows[0])&q.metrics.RELATIVE_FIELDS
    value['decoder_kind']='relative_owner'
    with pytest.raises(ValueError):q.check_generation(value,cp,sp,sources,'relative_owner')


def test_replay_jobs_only_fresh_and_real_diagnostics():
    values={p:{'panel':p} for p in ('training','tuning','old_single_fresh','fresh_lexical','fresh_structural','statutory_diagnostics',*q.CALIBRATION_PANELS)}
    assert set(q.replay_jobs(values))=={'fresh_lexical','fresh_structural','statutory_diagnostics',*q.CALIBRATION_PANELS}


def test_source_query_identity_uses_offsets_not_dict_insertion_order():
    first=source();second=deepcopy(first);second['id']='other'
    second['proposed_time_span']={k:second['proposed_time_span'][k] for k in ('char_end','char_start')}
    with pytest.raises(ValueError,match='duplicate'):q.check_source_inventory([first,second])


def test_actual_open_guard_denies_until_explicit_release(tmp_path):
    paths={key:tmp_path/(key+'.json') for key in q.SEALED}
    for p in paths.values():p.write_text('[]')
    m={'artifacts':{k:q.ref(p) for k,p in paths.items()}};guard=q.phase_guard(m)
    with pytest.raises(PermissionError):paths[q.SEALED[0]].read_bytes()
    assert len(guard['premature_read_attempts'])==1 and guard['postrelease_reads']==[]
    guard['premature_read_attempts']=[];q.release_stage(guard,'calibration');assert paths[q.SEALED[0]].read_bytes()==b'[]';assert len(guard['postrelease_reads'])==1


def test_bad_admitted_score_prevents_any_fresh_release(monkeypatch,tmp_path):
    f=tmp_path/'freeze';r=tmp_path/'replay';f.write_text('{}');r.write_text('{}');c=tmp_path/'calibration';c.write_text(json.dumps({'fitting_freeze':{},'training_audit':{}}))
    monkeypatch.setattr(q,'check_training_authorization',lambda *_:{})
    guard={'released':False,'premature_read_attempts':[],'postrelease_reads':[],'released_stages':[]}
    monkeypatch.setattr(q,'load_inputs',lambda _:({}, {},guard))
    monkeypatch.setattr(q,'inventory',lambda *_:({}, {},{},{}))
    monkeypatch.setattr(q,'check_replay',lambda *_:None)
    def fail(*_):raise ValueError('admitted tuning score differs')
    monkeypatch.setattr(q,'score_admitted',fail)
    with pytest.raises(ValueError,match='admitted'):q.score(f,r,c,tmp_path/'output')
    assert guard['released'] is False and guard['postrelease_reads']==[] and not (tmp_path/'output').exists()


def test_reference_mapping_failure_prevents_fresh_release(monkeypatch,tmp_path):
    f=tmp_path/'freeze';r=tmp_path/'replay';f.write_text('{}');r.write_text('{}');c=tmp_path/'calibration';c.write_text(json.dumps({'fitting_freeze':{},'training_audit':{}}))
    monkeypatch.setattr(q,'check_training_authorization',lambda *_:{})
    guard={'released':False,'premature_read_attempts':[],'postrelease_reads':[],'released_stages':[]}
    monkeypatch.setattr(q,'load_inputs',lambda _:({}, {},guard));monkeypatch.setattr(q,'inventory',lambda *_:({}, {},{},{}))
    monkeypatch.setattr(q,'check_replay',lambda *_:None);monkeypatch.setattr(q,'score_admitted',lambda *_:({},{}))
    def fail(*_):raise ValueError('reference mapping differs')
    monkeypatch.setattr(q,'admitted_mapping_audit',fail)
    with pytest.raises(ValueError,match='mapping'):q.score(f,r,c,tmp_path/'output')
    assert guard['released'] is False and guard['postrelease_reads']==[]


def replay_fixture(tmp_path,monkeypatch):
    source_pin=q.write(tmp_path/'sources.json',[source()]);cp=q.write(tmp_path/'checkpoint.json',{})
    generation_pin=q.write(tmp_path/'generation.json',{'rows':[{'id':'q','logits':[0.,1.]}]})
    freeze_pin=q.write(tmp_path/'freeze.json',{});producers=[q.ref(Path(q.__file__))]
    monkeypatch.setattr(q,'producers',lambda:producers)
    freeze={'sources':{'fresh_lexical':source_pin}};sources={'fresh_lexical':q.read(source_pin)}
    jobs={'key':{'generation':generation_pin,'checkpoint':cp,'panel':'fresh_lexical','decoder_kind':'relative_owner'}}
    entry={'generation':generation_pin,'checkpoint':cp,'sources':source_pin,'decoder_kind':'relative_owner',
           'rows':1,'actual_rows_sha256':q.digest(q.read(generation_pin)['rows']),'exact_match':True}
    replay={'schema':q.SCHEMA,'phase':'source_only_replay','generation_freeze':freeze_pin,'producer_files':producers,
            'inventory':{'all_stage_pins':'example'},'all_saved_rows_match':True,'files':{'key':entry},
            'physical_files_replayed':1,'encoder_source_evaluations':1,'encoder_batch_forwards':1,
            'fresh_reference_guard':{'released':False,'premature_read_attempts':[],'released_stages':[]}}
    expected_guard={'sealed_paths':[str(tmp_path/f'sealed-{i}') for i in range(8)],
        'stage_paths':{'calibration':[str(tmp_path/f'sealed-{i}') for i in range(4)],'fresh':[str(tmp_path/f'sealed-{i}') for i in range(4,8)]}}
    replay['fresh_reference_guard'].update(deepcopy(expected_guard),postrelease_reads=[])
    return freeze_pin,replay,{'all_stage_pins':'example'},jobs,freeze,sources,expected_guard


def test_exact_replay_closure_passes_without_new_neural_call(tmp_path,monkeypatch):
    q.check_replay(*replay_fixture(tmp_path,monkeypatch))


@pytest.mark.parametrize('mutation',[lambda r:r['inventory'].update(all_stage_pins='changed'),
    lambda r:r['files']['key'].update(actual_rows_sha256='0'*64),
    lambda r:r['files']['key'].update(decoder_kind='parent_coupled'),lambda r:r.update(encoder_source_evaluations=2),
    lambda r:r.update(producer_files=[]),lambda r:r['fresh_reference_guard'].update(released=True),
    lambda r:r['fresh_reference_guard'].update(premature_read_attempts=['attempt'])])
def test_replay_evidence_mutations_do_not_authorize_release(tmp_path,monkeypatch,mutation):
    args=list(replay_fixture(tmp_path,monkeypatch));mutation(args[1])
    with pytest.raises(ValueError):q.check_replay(*args)


def test_source_group_diagnostics_preserve_repeated_query_dependence():
    first=source();second=deepcopy(first);second['id']='second'
    scored={'rows':[{'id':first['id'],'target':'norm','type_correct':True,'joint_correct':True,'anchor_exact':True,
                     'accepted_joint':True,'accepted_joint_correct':True},
                    {'id':second['id'],'target':'condition','type_correct':True,'joint_correct':False,'anchor_exact':False,
                     'accepted_joint':True,'accepted_joint_correct':False}]}
    result=q.occurrence_diagnostics([first,second],scored)
    assert result['source_groups']==1 and result['multiple_query_sources']==1 and result['all_queries_joint_correct_sources']==0
    assert result['per_reference_class']['condition']['accepted_joint_errors']==1


def contrast_fixture():
    text=('Study. Office shall file before January 1, 2101 if application was received within 3 days of notice '
          'unless waiver was issued before January 2, 2101; Office may record.')
    roles=[{'role':role,'span':exact(text,value,index)} for role,value,index in
           (('actor','Office',0),('action','file',0),('condition_predicate','application was received',0),
            ('exception_predicate','waiver was issued',0),('actor','Office',1),('action','record',0))]
    times=q.runner.corpus.propose_time_spans(text);assert len(times)==3
    anchors={kind:exact(text,value) for kind,value in
             (('norm','file'),('condition','application was received'),('exception','waiver was issued'))}
    targets=[];references=[];contrasts={}
    for index,(label,timing) in enumerate(zip(q.metrics.CLASSES[:3],times)):
        s=source(text,text[timing['char_start']:timing['char_end']]);s['id']=f'fiction-{index}'
        s['proposed_time_span']={k:timing[k] for k in ('char_start','char_end')}
        target={**s,'label':label,'group_id':'source-'+s['source_sha256'],
                'owner_anchor_span':{k:anchors[label][k] for k in ('char_start','char_end')}}
        targets.append(target);references.append({**s,'label':label,'annotation':{'source_role_spans':deepcopy(roles)}})
        contrasts[s['id']]={'id':s['id'],'source_sha256':s['source_sha256'],'proposed_time_span':s['proposed_time_span'],
            'negative_owner_spans':[{k:r['span'][k] for k in ('char_start','char_end')} for r in roles
                                   if label=='norm' and r['role']=='action' and r['span']['char_start']!=anchors[label]['char_start']]}
    groups=[{'source_sha256':targets[0]['source_sha256'],'query_ids':sorted(r['id'] for r in targets)}]
    return targets,references,contrasts,groups


def test_contrasts_include_untimed_other_owners_and_same_type_other_anchor():
    value=q.audit_training_contrasts(*contrast_fixture())
    assert value['queries']==3 and value['source_groups']==1 and value['negative_anchor_spans']==1
    assert value['same_type_other_owner_negatives']==1
    assert value['gold_filtered_candidates_used_to_generate_negatives'] is False


@pytest.mark.parametrize('mutation',[
    lambda t,r,c,g:c[t[0]['id']]['negative_owner_spans'].pop(),
    lambda t,r,c,g:c[t[0]['id']].update(source_sha256='0'*64),
    lambda t,r,c,g:c[t[1]['id']]['negative_owner_spans'].append(t[0]['owner_anchor_span']),
    lambda t,r,c,g:c[t[0]['id']]['negative_owner_spans'].append(t[0]['owner_anchor_span']),
    lambda t,r,c,g:r[1]['annotation']['source_role_spans'].pop(),
    lambda t,r,c,g:g[0]['query_ids'].pop(),
    lambda t,r,c,g:c[t[0]['id']].update(owner_candidates=[]),
    lambda t,r,c,g:r[0]['annotation']['source_role_spans'][1]['span'].update(char_end=2,text='St')])
def test_repaired_contrast_metadata_cannot_remove_or_reassign_supervision(mutation):
    args=list(contrast_fixture());mutation(*args)
    with pytest.raises(ValueError):q.audit_training_contrasts(*args)


def test_missing_occurrence_cannot_claim_complete_source_groups_even_with_repaired_map():
    t,r,c,g=contrast_fixture();removed=t.pop();r.pop();c.pop(removed['id']);g[0]['query_ids'].remove(removed['id'])
    with pytest.raises(ValueError,match='complete source occurrence'):q.audit_training_contrasts(t,r,c,g)


def test_new_wire_cannot_masquerade_as_parent_pointer():
    sources,cp,sp,value=generation_fixture();value['decoder_kind']='parent_coupled'
    with pytest.raises(ValueError,match='wire'):q.check_generation(value,cp,sp,sources,'parent_coupled')


def test_selection_ignores_contrast_and_endpoint_diagnostic_losses():
    values=stage_scores()
    for v in values.values():v.update(joint_correct=190,selection_nll=1.,contrast_ce=0.,endpoint_composite_nll=0.)
    values[0].update(contrast_ce=1e6,endpoint_composite_nll=1e6)
    assert q.independent_selection(values)['selected_steps']==0


def staged_fixture(tmp_path):
    paths={k:tmp_path/(k+'.json') for k in q.SEALED}
    for p in paths.values():p.write_text('[]')
    guard=q.phase_guard({'artifacts':{k:q.ref(p) for k,p in paths.items()}})
    return paths,guard


def test_calibration_release_does_not_open_fresh_reference_paths(tmp_path):
    paths,guard=staged_fixture(tmp_path);q.release_stage(guard,'calibration')
    assert paths[q.CALIBRATION_SEALED[0]].read_bytes()==b'[]'
    assert guard['released_stages']==['calibration'] and guard['released'] is False
    with pytest.raises(PermissionError):paths[q.FRESH_SEALED[0]].read_bytes()
    assert guard['postrelease_reads'][0]['stage']=='calibration'
    with pytest.raises(ValueError):q.release_stage(guard,'fresh')


def test_reference_stage_release_order_is_enforced(tmp_path):
    paths,guard=staged_fixture(tmp_path)
    with pytest.raises(ValueError):q.release_stage(guard,'fresh')
    q.release_stage(guard,'calibration')
    with pytest.raises(ValueError):q.release_stage(guard,'calibration')
    q.release_stage(guard,'fresh');assert paths[q.FRESH_SEALED[0]].read_bytes()==b'[]'
    assert guard['released_stages']==['calibration','fresh'] and guard['released'] is True


def calibration_check_fixture(tmp_path,monkeypatch):
    producers=[q.ref(Path(q.__file__))];monkeypatch.setattr(q,'producers',lambda:producers)
    fake={'path':'/frozen','sha256':'a'*64,'bytes':1}
    expected={'sealed_paths':[str(tmp_path/f'p{i}') for i in range(8)],
              'stage_paths':{'calibration':[str(tmp_path/f'p{i}') for i in range(4)],'fresh':[str(tmp_path/f'p{i}') for i in range(4,8)]}}
    guard={**deepcopy(expected),'released_stages':['calibration'],'released':False,'premature_read_attempts':[],
           'postrelease_reads':[{'stage':'calibration','path':str(tmp_path/'p0')}]}
    authorization={'fitting_freeze':fake,'training_audit':fake,'preparation_freeze':fake,'initial_parity':fake,'training_audit_passed':True}
    record={'schema':q.SCHEMA,'phase':'calibration_freeze','generation_freeze':fake,'replay_freeze':fake,'inventory':{},
            'producer_files':producers,'admitted_selection':{},**authorization,'fresh_reference_guard':guard,
            'current_fresh_reference_files_opened':False,'checkpoint_selection_changed':False,'fresh_results_used':False,
            'calibration_model_forwards':0,'reference_release_after_replay_and_admitted_selection':True}
    return record,fake,fake,{}, {},authorization,expected


def test_calibration_closure_accepts_only_its_separate_reference_release(tmp_path,monkeypatch):
    q.check_calibration(*calibration_check_fixture(tmp_path,monkeypatch))


@pytest.mark.parametrize('mutation',[
    lambda c:c.update(producer_files=[]),lambda c:c.update(fresh_results_used=True),
    lambda c:c.update(checkpoint_selection_changed=True),lambda c:c.update(calibration_model_forwards=1),
    lambda c:c['fresh_reference_guard']['released_stages'].append('fresh'),
    lambda c:c['fresh_reference_guard']['postrelease_reads'].append({'stage':'fresh','path':'/fresh'}),
    lambda c:c['fresh_reference_guard']['stage_paths']['calibration'].append('/wrong-source-path'),
    lambda c:c.update(training_audit={'path':'/changed','sha256':'0'*64,'bytes':1}),
    lambda c:c.update(admitted_selection={'silently_changed':True})])
def test_calibration_freeze_mutations_cannot_authorize_fresh_release(tmp_path,monkeypatch,mutation):
    args=list(calibration_check_fixture(tmp_path,monkeypatch));mutation(args[0])
    with pytest.raises(ValueError):q.check_calibration(*args)


def type_invariance_fixture(tmp_path):
    s=source();parent_row=new_prediction(s);new_row=relative_prediction(s)
    parent=q.write(tmp_path/'parent.json',{'rows':[parent_row]});stage=q.write(tmp_path/'stage.json',{'rows':[new_row]})
    trials={'source_pointer-1730':{'seed':1730,'stages':[{'steps':0,'tuning_generation':stage}]}}
    unique={'parent':{'decoder_kind':'parent_coupled','slot':'parent-1730','panel':'tuning','generation':parent},
            'candidate':{'decoder_kind':'relative_owner','trial':'source_pointer-1730','slot':'source_pointer-1730__selected','panel':'tuning','generation':stage}}
    return trials,unique,parent_row,new_row


def test_frozen_type_projection_ignores_pointer_changes_but_binds_every_type_field(tmp_path):
    trials,unique,_,_=type_invariance_fixture(tmp_path)
    result=q.verify_type_invariance({},trials,unique)
    assert result['all_matching_type_fields_exact'] and result['compared_query_rows']==2


def test_changed_type_logits_fail_even_if_source_and_pointer_payloads_are_unchanged(tmp_path):
    trials,unique,_,row=type_invariance_fixture(tmp_path);row['logits'][0]+=1.
    changed=q.write(tmp_path/'changed.json',{'rows':[row]});trials['source_pointer-1730']['stages'][0]['tuning_generation']=changed
    with pytest.raises(ValueError,match='type outputs'):q.verify_type_invariance({},trials,unique)


def test_changed_empirical_policy_fails_before_any_fresh_release(monkeypatch,tmp_path):
    f=tmp_path/'freeze';r=tmp_path/'replay';c=tmp_path/'calibration';f.write_text('{}');r.write_text('{}')
    c.write_text(json.dumps({'fitting_freeze':{},'training_audit':{},'policies':{'changed':True},'calibration_input_pins':{},'calibration_annotation_audit':{}}))
    guard={'released':False,'released_stages':[],'premature_read_attempts':[],'postrelease_reads':[]}
    monkeypatch.setattr(q,'load_inputs',lambda _:({}, {},guard));monkeypatch.setattr(q,'inventory',lambda *_:({}, {},{},{}))
    monkeypatch.setattr(q,'check_replay',lambda *_:None);monkeypatch.setattr(q,'check_training_authorization',lambda *_:{})
    monkeypatch.setattr(q,'score_admitted',lambda *_:({},{}));monkeypatch.setattr(q,'admitted_mapping_audit',lambda *_:{})
    monkeypatch.setattr(q,'check_calibration',lambda *_:None);monkeypatch.setattr(q,'policy_records',lambda *_:{})
    def release(data,sources,g,stage):
        q.release_stage(g,stage);return {},{},{}
    monkeypatch.setattr(q,'stage_references',release)
    with pytest.raises(ValueError,match='calibration policy'):q.score(f,r,c,tmp_path/'output')
    assert guard['released_stages']==['calibration'] and guard['released'] is False


def training_authorization_fixture(tmp_path):
    config=q.write(tmp_path/'config.json',{});initial=q.write(tmp_path/'initial.json',{})
    producer=q.write(tmp_path/'auditor-source.json',{'immutable':'producer'})
    guard={'released':False,'premature_read_attempts':[]}
    prep=q.write(tmp_path/'preparation.json',{'config':config,'optimizer_updates':0,'fresh_reference_guard':guard,'producer_files':[producer]})
    parity=q.write(tmp_path/'parity.json',{'config':config,'initialization':initial,'encoder_batch_forwards':48,
        'encoder_source_evaluations':2304,'all_inherited_predictions_exact':True,'fresh_reference_guard':guard})
    freeze={'config':config,'initialization':initial};freeze_pin=q.write(tmp_path/'generation.json',freeze)
    fitting=q.write(tmp_path/'fitting.json',{'preparation':prep,'parity':parity,'config':config,'initialization':initial,
        'optimizer_updates_before_freeze':0,'initial_predictions_exact':True,'fresh_reference_attempts':[],
        'neural_batches_before_fitting':48,'neural_query_evaluations_before_fitting':2304,'producer_files':[producer]})
    audit={'schema':'legal-temporal-relative-owner-training-audit/v1','status':'passed','generation':freeze_pin,
        'optimizer_updates':1200,'training_queries':28800,'failures':[],'fresh_reference_attempts':[],'neural_forwards':0,
        'objective_oracle':q.ref(q.metrics.__file__),'producer':producer}
    return freeze_pin,freeze,fitting,audit


def test_training_authorization_binds_generation_preparation_parity_and_oracle(tmp_path):
    f,freeze,fit,audit=training_authorization_fixture(tmp_path)
    result=q.check_training_authorization(f,freeze,fit,q.write(tmp_path/'audit.json',audit))
    assert result['training_audit_passed'] and result['fitting_freeze']==fit


@pytest.mark.parametrize('mutation',[lambda a:a.update(status='failed'),lambda a:a.update(failures=['bad loss']),
    lambda a:a.update(optimizer_updates=1199),lambda a:a.update(fresh_reference_attempts=['calibration']),
    lambda a:a.update(neural_forwards=1),lambda a:a.update(objective_oracle={'path':'/wrong','sha256':'0'*64,'bytes':0})])
def test_failed_or_mismatched_training_receipt_never_authorizes_calibration(tmp_path,mutation):
    f,freeze,fit,audit=training_authorization_fixture(tmp_path);mutation(audit)
    with pytest.raises(ValueError):q.check_training_authorization(f,freeze,fit,q.write(tmp_path/'audit.json',audit))
