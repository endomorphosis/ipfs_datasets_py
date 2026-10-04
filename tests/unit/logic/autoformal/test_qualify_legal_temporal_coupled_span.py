"""Source joins, exact occurrence mappings and release-order failure tests."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import pytest

from scripts.ops.legal_ir import qualify_legal_temporal_coupled_span as q
from tests.unit.logic.autoformal.test_legal_temporal_owner_pointer_metrics_v2 import source, prediction
from tests.unit.logic.autoformal.test_legal_temporal_coupled_span_metrics import new_prediction


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
    sources=[source()];row=new_prediction(sources[0]);cp={'path':'/checkpoint','sha256':'a'*64,'bytes':1};sp={'path':'/sources','sha256':'b'*64,'bytes':1}
    value={'schema':'legal-temporal-coupled-span-generation/v1','checkpoint':cp,'decoder_kind':'coupled_span','sources':sp,
        'rows':[row],'encoder_batch_forwards':1,'encoder_source_evaluations':1,'source_only_input':True,
        'reference_anchors_supplied':False,'labels_supplied':False,'pipeline_promotion':False,'statutory_semantics_verified':False}
    return sources,cp,sp,value


def test_generation_retains_full_source_and_validates_pointer_policy():
    sources,cp,sp,value=generation_fixture();assert q.check_generation(value,cp,sp,sources,'coupled_span')==value['rows']


@pytest.mark.parametrize('mutation',[lambda v:v.update(reference_anchors_supplied=True),lambda v:v.update(decoder_kind='parent_pointer'),
    lambda v:v.update(encoder_batch_forwards=True),lambda v:v.update(encoder_source_evaluations=0),
    lambda v:v.update(rows=[]),lambda v:v['rows'][0].update(source_sha256='0'*64),
    lambda v:v['rows'][0].update(valid_span_count=0),lambda v:v.update(extra_reference={'label':'norm'})])
def test_source_generation_contract_tampering_rejected(mutation):
    sources,cp,sp,value=generation_fixture();mutation(value)
    with pytest.raises(ValueError):q.check_generation(value,cp,sp,sources,'coupled_span')


def test_parent_pointer_preserves_exact_coordinate_metrics_without_new_interaction_fields():
    sources,cp,sp,value=generation_fixture();value['decoder_kind']='parent_pointer'
    value['rows']=[prediction(sources[0])]
    rows=q.check_generation(value,cp,sp,sources,'parent_pointer')
    assert rows[0]['raw_owner_anchor_span'] is not None and not set(rows[0])&q.metrics.EXTRA_FIELDS
    value['decoder_kind']='coupled_span'
    with pytest.raises(ValueError):q.check_generation(value,cp,sp,sources,'coupled_span')


def test_replay_jobs_only_fresh_and_real_diagnostics():
    values={p:{'panel':p} for p in ('training','tuning','old_single_fresh','fresh_lexical','fresh_structural','statutory_diagnostics')}
    assert set(q.replay_jobs(values))=={'fresh_lexical','fresh_structural','statutory_diagnostics'}


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
    guard['released']=True;assert paths[q.SEALED[0]].read_bytes()==b'[]';assert len(guard['postrelease_reads'])==1


def test_bad_admitted_score_prevents_any_fresh_release(monkeypatch,tmp_path):
    f=tmp_path/'freeze';r=tmp_path/'replay';f.write_text('{}');r.write_text('{}')
    guard={'released':False,'premature_read_attempts':[],'postrelease_reads':[]}
    monkeypatch.setattr(q,'load_inputs',lambda _:({}, {},guard))
    monkeypatch.setattr(q,'inventory',lambda *_:({}, {},{},{}))
    monkeypatch.setattr(q,'check_replay',lambda *_:None)
    def fail(*_):raise ValueError('admitted tuning score differs')
    monkeypatch.setattr(q,'score_admitted',fail)
    with pytest.raises(ValueError,match='admitted'):q.score(f,r,tmp_path/'output')
    assert guard['released'] is False and guard['postrelease_reads']==[] and not (tmp_path/'output').exists()


def test_reference_mapping_failure_prevents_fresh_release(monkeypatch,tmp_path):
    f=tmp_path/'freeze';r=tmp_path/'replay';f.write_text('{}');r.write_text('{}')
    guard={'released':False,'premature_read_attempts':[],'postrelease_reads':[]}
    monkeypatch.setattr(q,'load_inputs',lambda _:({}, {},guard));monkeypatch.setattr(q,'inventory',lambda *_:({}, {},{},{}))
    monkeypatch.setattr(q,'check_replay',lambda *_:None);monkeypatch.setattr(q,'score_admitted',lambda *_:({},{}))
    def fail(*_):raise ValueError('reference mapping differs')
    monkeypatch.setattr(q,'admitted_mapping_audit',fail)
    with pytest.raises(ValueError,match='mapping'):q.score(f,r,tmp_path/'output')
    assert guard['released'] is False and guard['postrelease_reads']==[]


def replay_fixture(tmp_path,monkeypatch):
    source_pin=q.write(tmp_path/'sources.json',[source()]);cp=q.write(tmp_path/'checkpoint.json',{})
    generation_pin=q.write(tmp_path/'generation.json',{'rows':[{'id':'q','logits':[0.,1.]}]})
    freeze_pin=q.write(tmp_path/'freeze.json',{});producers=[q.ref(Path(q.__file__))]
    monkeypatch.setattr(q,'producers',lambda:producers)
    freeze={'sources':{'fresh_lexical':source_pin}};sources={'fresh_lexical':q.read(source_pin)}
    jobs={'key':{'generation':generation_pin,'checkpoint':cp,'panel':'fresh_lexical','decoder_kind':'coupled_span'}}
    entry={'generation':generation_pin,'checkpoint':cp,'sources':source_pin,'decoder_kind':'coupled_span',
           'rows':1,'actual_rows_sha256':q.digest(q.read(generation_pin)['rows']),'exact_match':True}
    replay={'schema':q.SCHEMA,'phase':'source_only_replay','generation_freeze':freeze_pin,'producer_files':producers,
            'inventory':{'all_stage_pins':'example'},'all_saved_rows_match':True,'files':{'key':entry},
            'physical_files_replayed':1,'encoder_source_evaluations':1,'encoder_batch_forwards':1,
            'fresh_reference_guard':{'released':False,'premature_read_attempts':[]}}
    return freeze_pin,replay,{'all_stage_pins':'example'},jobs,freeze,sources


def test_exact_replay_closure_passes_without_new_neural_call(tmp_path,monkeypatch):
    q.check_replay(*replay_fixture(tmp_path,monkeypatch))


@pytest.mark.parametrize('mutation',[lambda r:r['inventory'].update(all_stage_pins='changed'),
    lambda r:r['files']['key'].update(actual_rows_sha256='0'*64),
    lambda r:r['files']['key'].update(decoder_kind='parent_pointer'),lambda r:r.update(encoder_source_evaluations=2),
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
                                   if r['role']!='actor' and r['span']['char_start']!=anchors[label]['char_start']]}
    groups=[{'source_sha256':targets[0]['source_sha256'],'query_ids':sorted(r['id'] for r in targets)}]
    return targets,references,contrasts,groups


def test_contrasts_include_untimed_other_owners_and_same_type_other_anchor():
    value=q.audit_training_contrasts(*contrast_fixture())
    assert value['queries']==3 and value['source_groups']==1 and value['negative_anchor_spans']==9
    assert value['same_type_other_owner_negatives']==1
    assert value['gold_filtered_candidates_used_to_generate_negatives'] is False


@pytest.mark.parametrize('mutation',[
    lambda t,r,c,g:c[t[0]['id']]['negative_owner_spans'].pop(),
    lambda t,r,c,g:c[t[0]['id']].update(source_sha256='0'*64),
    lambda t,r,c,g:c[t[0]['id']]['negative_owner_spans'].reverse(),
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
    sources,cp,sp,value=generation_fixture();value['decoder_kind']='parent_pointer'
    with pytest.raises(ValueError,match='wire'):q.check_generation(value,cp,sp,sources,'parent_pointer')


def test_selection_ignores_contrast_and_endpoint_diagnostic_losses():
    values=stage_scores()
    for v in values.values():v.update(joint_correct=190,selection_nll=1.,contrast_ce=0.,endpoint_composite_nll=0.)
    values[0].update(contrast_ce=1e6,endpoint_composite_nll=1e6)
    assert q.independent_selection(values)['selected_steps']==0
