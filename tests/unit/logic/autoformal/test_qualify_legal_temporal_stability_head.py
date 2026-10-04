"""Independent stability replay, source boundaries, selection and release order."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import random

import pytest

from scripts.ops.legal_ir import qualify_legal_temporal_stability_head as q

def sample():
    text = 'Registry shall file within 7 days of notice.'; a=text.index('within'); b=text.index('.')
    source={'id':'query','source_text':text,'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'proposed_time_span':{'char_start':a,'char_end':b}}
    probabilities=q.metric.softmax([4.,0.,0.,0.])
    row={'id':'query','source_sha256':source['source_sha256'],'proposed_time_span':source['proposed_time_span'],
         'time_token_span':q.metric.validate_source(source),'logits':[4.,0.,0.,0.],'probabilities':probabilities,
         'predicted_label':'norm','confidence':probabilities[0],'status':'accepted','owner_type':'norm','reason':None,
         **{k:False for k in q.metric.FALSE_FIELDS}}
    cp={'path':'/checkpoint','bytes':1,'sha256':'a'*64,'schema':q.CHECKPOINT_SCHEMA}
    pin={'path':'/source','bytes':1,'sha256':'b'*64}
    value={'schema':'legal-temporal-owner-type-source-generation/v1','model':{'checkpoint':cp,'decoder_kind':'stability_owner_type','arm':'mixed_occurrences','seed':1730,'steps':200},
           'sources':pin,'class_order':list(q.metric.CLASSES),'threshold':.8,'rows':[row],
           'encoder_batch_forwards':1,'encoder_source_evaluations':1,'source_text_conditioned':True,
           'time_occurrence_conditioned':True,'labels_supplied':False,'source_id_used_as_feature':False,'owner_or_cue_spans_supplied':False,
           **{k:False for k in q.metric.FALSE_FIELDS}}
    return source,row,cp,pin,value


def verify_sample(value, source, cp, pin):
    return q.generation(value,cp,pin,[source],arm='mixed_occurrences',seed=1730,step=200)


def test_full_prediction_wire_and_occurrence_are_verified():
    source,row,cp,pin,value=sample()
    assert verify_sample(value,source,cp,pin)==[row]


@pytest.mark.parametrize('mutation', [
    lambda v:v['model'].update(steps=True), lambda v:v['model'].update(arm='single_replay'),
    lambda v:v.update(labels_supplied=True),lambda v:v.update(time_occurrence_conditioned=False),
    lambda v:v.update(owner_or_cue_spans_supplied=True),lambda v:v.update(source_id_used_as_feature=True),
    lambda v:v.update(encoder_batch_forwards=True),lambda v:v.update(rows=[]),
    lambda v:v['rows'][0]['proposed_time_span'].update(char_start=True),
    lambda v:v['rows'][0].update(owner_occurrence_resolved=True),
])
def test_changed_prediction_metadata_rejected(mutation):
    source,_,cp,pin,value=sample();mutation(value)
    with pytest.raises(ValueError):verify_sample(value,source,cp,pin)


def test_typed_checkpoint_reference_exact_schema_and_bytes(tmp_path):
    path=tmp_path/'checkpoint.json';pin=q.write(path,{'schema':q.CHECKPOINT_SCHEMA})
    typed={**pin,'schema':q.CHECKPOINT_SCHEMA};q.read_producer(typed)
    with pytest.raises(ValueError):q.read_producer({**typed,'bytes':True})
    with pytest.raises(ValueError):q.read_producer({**typed,'schema':'wrong'})
    path.write_text('{"schema":"changed"}')
    with pytest.raises(ValueError):q.read_producer(typed)


def test_checkpoint_metadata_schema_must_equal_file(tmp_path):
    pin=q.write(tmp_path/'checkpoint.json',{'schema':'wrong'})
    with pytest.raises(ValueError):q.read({**pin,'schema':q.CHECKPOINT_SCHEMA})


def test_duplicate_json_keys_and_nonfinite_constants_rejected(tmp_path):
    path=tmp_path/'evidence.json';path.write_text('{"x":1,"x":2}')
    with pytest.raises(ValueError):q.read(q.reference(path))
    path.write_text('{"x":NaN}')
    with pytest.raises(ValueError):q.read(q.reference(path))


def test_existing_evidence_never_overwritten(tmp_path):
    p=tmp_path/'evidence.json';q.write(p,{'x':1})
    with pytest.raises(FileExistsError):q.write(p,{'x':2})
    assert json.loads(p.read_text())=={'x':1}


def test_paired_counts_bind_source_occurrence_and_reference():
    source,row,*_=sample();a=q.metric.score([source],[row],{'query':'norm'})
    assert q.paired_comparison(a,a)['correct_delta']==0
    b=deepcopy(a);b['rows'][0]['target']='condition'
    with pytest.raises(ValueError):q.paired_comparison(a,b)
    b=deepcopy(a);b['rows'][0]['source_sha256']='0'*64
    with pytest.raises(ValueError):q.paired_comparison(a,b)


def test_actual_os_guard_denies_until_explicit_release(tmp_path):
    paths=[tmp_path/f'sealed-{i}.json' for i in range(4)]
    for p in paths:p.write_text('{}')
    manifest={'artifacts':{str(i):q.reference(p) for i,p in enumerate(paths)}}
    state=q.phase_guard(manifest,tuple(manifest['artifacts']))
    with pytest.raises(PermissionError):paths[0].read_text()
    assert state['premature_read_attempts']==[str(paths[0])]
    state['released']=True
    assert paths[1].read_text()=='{}'
    assert state['postrelease_reads']==[str(paths[1])]


def test_bad_admitted_selection_fails_before_any_fresh_open(tmp_path,monkeypatch):
    artifacts={}
    for key in q.runner.SEALED_KEYS:artifacts[key]=q.write(tmp_path/(key+'.json'),{})
    manifest={'artifacts':artifacts};state=q.phase_guard(manifest,q.runner.SEALED_KEYS)
    freeze=q.write(tmp_path/'freeze.json',{});replay=q.write(tmp_path/'replay.json',{})
    monkeypatch.setattr(q,'load_inputs',lambda _:({'manifest':manifest},state))
    monkeypatch.setattr(q,'inventory',lambda *a:({}, {}, {}, {}, {}))
    monkeypatch.setattr(q,'check_replay',lambda *a:None)
    def bad(*a):raise ValueError('independent admitted-tuning selection differs')
    monkeypatch.setattr(q,'score_admitted',bad)
    with pytest.raises(ValueError,match='selection differs'):q.score(freeze['path'],replay['path'],tmp_path/'score.json')
    assert state['released'] is False and state['premature_read_attempts']==state['postrelease_reads']==[]
    assert not (tmp_path/'score.json').exists()


def test_bad_replay_fails_before_admitted_scoring_and_reference_release(tmp_path,monkeypatch):
    artifacts={key:q.write(tmp_path/(key+'.json'),{}) for key in q.runner.SEALED_KEYS}
    manifest={'artifacts':artifacts};state=q.phase_guard(manifest,q.runner.SEALED_KEYS)
    freeze=q.write(tmp_path/'freeze.json',{});replay=q.write(tmp_path/'replay.json',{})
    monkeypatch.setattr(q,'load_inputs',lambda _:({'manifest':manifest},state))
    monkeypatch.setattr(q,'inventory',lambda *a:({}, {}, {}, {}, {}))
    def bad(*a):raise ValueError('replay binding differs')
    monkeypatch.setattr(q,'check_replay',bad)
    monkeypatch.setattr(q,'score_admitted',lambda *a:pytest.fail('admitted scoring preceded replay check'))
    with pytest.raises(ValueError,match='replay binding differs'):q.score(freeze['path'],replay['path'],tmp_path/'score.json')
    assert state['released'] is False and not state['postrelease_reads'] and not state['premature_read_attempts']


def test_parent_physical_metadata_keeps_prior_training_step():
    parent={'decoder_kind':'paired_owner_type','arm':'parent','seed':1730,'additional_steps':0}
    assert q.physical_metadata(parent)=={'decoder_kind':'paired_owner_type','arm':'mixed_occurrences','seed':1730,'step':200}
    alias={**parent,'arm':'mixed_occurrences'}
    assert q.physical_metadata(alias)==q.physical_metadata(parent)


def test_replay_manifest_payload_change_is_rejected(tmp_path,monkeypatch):
    source,row,cp,pin,value=sample();sourcepin=q.write(tmp_path/'sources.json',[source]);value['sources']=sourcepin
    genpin=q.write(tmp_path/'generation.json',value);key='k';slot={'panel':'fresh_lexical','checkpoint':cp,
        'decoder_kind':'stability_owner_type','arm':'mixed_occurrences','seed':1730,'additional_steps':200,'generation':genpin}
    teacherpin={'path':'/teacher','sha256':'c'*64,'bytes':1}
    freeze={'sources':{'fresh_lexical':sourcepin},'independent_teacher_replay':teacherpin,'teacher_cache_freeze':teacherpin}
    freezepin=q.write(tmp_path/'freeze.json',freeze)
    receipt={'key':key,'checkpoint':cp,'decoder_kind':'stability_owner_type','sources':sourcepin,'generation':genpin,
        'rows_sha256':q.digest(value['rows']),'exact_rows':1,'encoder_batch_forwards':1,'encoder_source_evaluations':1}
    replay={'schema':'legal-stability-owner-type-independent-replay/v1','generation_freeze':freezepin,'exact_replay':True,
        'fresh_references_opened':False,'fresh_reference_guard':{'released':False,'premature_read_attempts':[]},
        'producer_files':[],'replays':[receipt],'encoder_batch_forwards':1,'encoder_source_evaluations':1,
        'independent_teacher_replay':teacherpin,'teacher_cache_freeze':teacherpin}
    monkeypatch.setattr(q,'producer_pins',lambda:[])
    args=(freeze,freezepin,replay,{'fresh_lexical':[source]},{key:slot},
        {'physical_fresh_encoder_batch_forwards':1,'physical_fresh_query_rows':1})
    q.check_replay(*args)
    receipt['rows_sha256']='0'*64
    with pytest.raises(ValueError,match='binding differs'):q.check_replay(*args)


def test_admitted_renderer_reference_candidates_are_coordinate_only():
    rows=q.placement_prior.corpus.render_source('tuning',0,1)
    audit=q.reference_candidate_audit(rows)
    assert audit['queries']==len(rows) and audit['used_as_inference_inventory'] is False
    assert audit['owner_occurrence_accuracy_measured'] is False
    changed=deepcopy(rows);changed[0]['annotation']['attachment_cue_spans'][0]['owner_occurrence_id']='wrong'
    with pytest.raises(ValueError,match='join differs'):q.reference_candidate_audit(changed)


def test_independent_body_layout_matches_admitted_renderer_and_rejects_bad_offsets():
    rows=[r for unit in range(4) for source in range(5) for r in q.placement_prior.corpus.render_source('tuning',unit,source)]
    assert all(q.body_layout(r)==q.corpus.body_layout(r) for r in rows)
    changed=deepcopy(rows[0]);changed['annotation']['source_role_spans'][0]['span']['char_start']+=1
    with pytest.raises(ValueError,match='span'):q.body_layout(changed)


@pytest.fixture
def complete_inventory(tmp_path,monkeypatch):
    def save(name,value,schema=None):
        pin=q.write(tmp_path/(name+'.json'),value)
        return {**pin,'schema':schema} if schema else pin
    schema='legal-paired-temporal-owner-type-checkpoint/v1'
    parents={str(seed):save(f'parent-{seed}',{'schema':schema,'model_state':{'w':[seed]},'config':{'arm':'mixed_occurrences','seed':seed}},schema)
             for seed in q.SEEDS}
    config=save('config',{'parents':parents,'corpus_manifest':save('manifest',{})})
    data={'manifest_ref':q.read(config)['corpus_manifest'],'regression_sources':{}}
    teacher_binding={str(seed):{'reference':{'path':'/cache-'+str(seed),'sha256':'f'*64,'bytes':1},
                               'payload_sha256':'e'*64} for seed in q.SEEDS}
    # Teacher provenance has its own complete tests below. This fixture isolates
    # final inventories and must not run any neural or teacher-cache inference.
    monkeypatch.setattr(q,'verify_teacher_replay',lambda *a:teacher_binding)
    sources={}
    for panel,count in q.COUNTS.items():
        values=[]
        for index in range(count):
            text=f'Registry {panel} {index} shall file within 7 days of notice.'
            values.append(q.corpus.query(text,{'char_start':text.index('within'),'char_end':text.index('.')}))
        sources[panel]=save(panel,values)
        if panel in q.ADMITTED:data[panel]=values
        elif panel in q.PANELS[:2]:data[panel+'_sources']=values
        else:data['regression_sources']['single' if panel=='old_single_fresh' else 'multi']=values
    evidence={str(seed):{panel:{'generation':save(f'pgen-{seed}-{panel}',{}),'metrics':{},'gate_counts':{}} for panel in q.ADMITTED} for seed in q.SEEDS}
    parentfreeze=save('parent-freeze',{'parents':parents,'evaluations':evidence,'fresh_references_opened':False,
        'fresh_reference_guard':{'premature_read_attempts':0}})
    models={};trials=[]
    for arm in q.ARMS:
        for seed in q.SEEDS:
            name=f'{arm}-{seed}';parent=q.read(parents[str(seed)])
            cp={'schema':q.CHECKPOINT_SCHEMA,'optimizer_steps':0,'config':{'arm':arm,'seed':seed},
                'model_state':parent['model_state'],'parent':parent,'parent_file_sha256':parents[str(seed)]['sha256'],
                'optimizer_state':{'parameters':{}},'teacher_cache':teacher_binding[str(seed)]}
            models[name]=save('init-'+name,cp,q.CHECKPOINT_SCHEMA)
            parent_candidate={'steps':0,'checkpoint':parents[str(seed)],'decoder_kind':'paired_owner_type'}
            for panel in q.ADMITTED:
                parent_candidate[panel+'_generation']=evidence[str(seed)][panel]['generation']
                parent_candidate[panel+'_metrics']={}
                if panel in q.gates.PANELS:parent_candidate[panel+'_gate_counts']={}
            stages=[{'steps':step,'checkpoint':save(f'{name}-{step}',{'schema':q.CHECKPOINT_SCHEMA,'step':step,'name':name},q.CHECKPOINT_SCHEMA),
                     'training_report':save(f'{name}-report-{step}',{}),'decoder_kind':'stability_owner_type','eligible':False} for step in q.STEPS[1:]]
            for stage in stages:
                for panel in q.evaluated_panels(stage['steps']):
                    stage[panel+'_generation']=save(f"{name}-{stage['steps']}-{panel}",{})
                    stage[panel+'_metrics']={}
            trials.append({'name':name,'arm':arm,'seed':seed,'fresh_references_opened':False,'fresh_reference_guard':{'premature_read_attempts':0},
                'selected_is_pipeline_promotion':False,'parent_checkpoint':parents[str(seed)],'initial_checkpoint':models[name],
                'initial_evaluation':evidence[str(seed)],'parent_candidate':parent_candidate,'stages':stages,
                'selected_steps':0,'selected_checkpoint':parents[str(seed)],'selected_decoder_kind':'paired_owner_type','selected_parent_fallback':True})
    initials=save('initials',{'config':config,'models':models,'parents':parents,'fresh_references_opened':False,
                             'fresh_reference_guard':{'premature_read_attempts':0}})
    selected=save('selection',{'config':config,'initialization_freeze':initials,'parent_evaluations':parentfreeze,
        'fresh_references_opened':False,'no_pipeline_promotion':True,'trials':trials,
        'trial_references':[save('trial-'+t['name'],t) for t in trials]})
    slots=[{'slot':f'parent-{seed}','arm':'parent','seed':seed,'role':'parent','additional_steps':0,
            'checkpoint':parents[str(seed)],'decoder_kind':'paired_owner_type'} for seed in q.SEEDS]
    for t in trials:
        for role in ('selected','final200'):
            slots.append({'slot':t['name']+'__'+role,'arm':t['arm'],'seed':t['seed'],'role':role,
                'additional_steps':0 if role=='selected' else 200,'checkpoint':t['selected_checkpoint'] if role=='selected' else t['stages'][-1]['checkpoint'],
                'decoder_kind':'paired_owner_type' if role=='selected' else 'stability_owner_type'})
    logical=[];physical=[];cache={}
    for slot in slots:
        for panel in q.PANELS:
            key=q.digest({'checkpoint':slot['checkpoint']['sha256'],'sources':sources[panel]['sha256']});executed=key not in cache
            if executed:
                cache[key]=save('gen-'+key,{})
                physical.append({'key':key,'generation':cache[key],'encoder_batch_forwards':q.COUNTS[panel]//48,'encoder_source_evaluations':q.COUNTS[panel]})
            logical.append({**slot,'panel':panel,'generation':cache[key],'generation_key':key,'executed_here':executed})
    freeze={'schema':q.runner.SCHEMA,'all_training_selection_and_generation_complete':True,'fresh_references_opened':False,
        'fresh_reference_guard':{'premature_read_attempts':0},'producer_pins':{},'config':config,'selections':selected,
        'initialization_freeze':initials,'parent_evaluations':parentfreeze,'sources':sources,'logical_generations':logical,'executed_generations':physical,
        'logical_generation_slots':28,'logical_fresh_query_rows':4032,'physical_generation_files':16,'physical_fresh_query_rows':2304,
        'physical_fresh_encoder_batch_forwards':48,'total_optimizer_updates':1200,'training_encoder_batch_forwards':1200,
        'training_encoder_source_evaluations':28800,'admitted_generation_counters':{'encoder_batch_forwards':1076,'encoder_source_evaluations':51648},
        'teacher_preparation_counters':{'encoder_batch_forwards':68,'encoder_source_evaluations':3264}}
    monkeypatch.setattr(q.runner,'producer_pins',lambda:{})
    monkeypatch.setattr(q.runner,'PARENT_SHAS',{seed:parents[str(seed)]['sha256'] for seed in q.SEEDS})
    return freeze,data


def test_full_inventory_preserves_parent_fallback_aliases_and_diagnostics(complete_inventory):
    freeze,data=complete_inventory;_,trials,_,unique,counts=q.inventory(freeze,data)
    assert len(trials)==6 and len(unique)==16 and counts['logical_generation_slots']==28
    assert counts['physical_fresh_query_rows']==2304


@pytest.mark.parametrize('mutation',[
    lambda f:f['logical_generations'].pop(),
    lambda f:f['logical_generations'].append(deepcopy(f['logical_generations'][0])),
    lambda f:f['logical_generations'][8].update(executed_here=True),
    lambda f:f['logical_generations'][8].update(decoder_kind='stability_owner_type'),
    lambda f:f['logical_generations'][0].update(additional_steps=200),
    lambda f:f['logical_generations'][0].update(generation_key='0'*64),
    lambda f:f.update(physical_fresh_query_rows=8064),
    lambda f:f.update(logical_generation_slots=True),
])
def test_inventory_alias_counter_and_metadata_tampering_rejected(complete_inventory,mutation):
    freeze,data=complete_inventory;mutation(freeze)
    with pytest.raises(ValueError):q.inventory(freeze,data)


def test_changed_unselected_checkpoint_bytes_are_rejected(complete_inventory):
    freeze,data=complete_inventory;trials=q.read(freeze['selections'])['trials']
    path=trials[0]['stages'][0]['checkpoint']['path']
    with open(path,'w') as handle:handle.write('{}')
    with pytest.raises(ValueError,match='bytes changed'):q.inventory(freeze,data)



@lru_cache(None)
def fixtures(count=8):
    sources, labels = [], {}
    for index in range(count):
        text = f'Registry {index} shall file within 7 days of notice.'
        source = {'id': f'query-{index:04d}', 'source_text': text,
                  'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
                  'proposed_time_span': {'char_start': text.index('within'), 'char_end': text.index('.')}}
        sources.append(source); labels[source['id']] = q.metric.CLASSES[index % 4]
    return sources, labels


def predictions(count=8, changes=None, strength=5.):
    sources, labels = fixtures(count); rows = []
    for source in sources:
        label, scale = (changes or {}).get(source['id'], (labels[source['id']], strength))
        logits = [0.] * 4; logits[q.metric.CLASSES.index(label)] = scale
        probabilities = q.metric.softmax(logits); confidence = probabilities[q.metric.CLASSES.index(label)]
        accepted = label != 'ambiguous' and confidence >= .8
        rows.append({'id': source['id'], 'source_sha256': source['source_sha256'],
                     'proposed_time_span': deepcopy(source['proposed_time_span']),
                     'time_token_span': q.metric.validate_source(source), 'logits': logits,
                     'probabilities': probabilities, 'predicted_label': label, 'confidence': confidence,
                     'status': 'accepted' if accepted else 'deferred', 'owner_type': label if accepted else None,
                     'reason': None if accepted else ('predicted_ambiguous' if label == 'ambiguous' else 'below_fixed_confidence'),
                     **{key: False for key in q.metric.FALSE_FIELDS}})
    return rows


def scored(count=8, changes=None, strength=5.):
    sources, labels = fixtures(count)
    return q.gates.panel_metrics(sources, predictions(count, changes, strength), labels)


def gates(count=8, changes=None, strength=5.):
    return scored(count, changes, strength)['gate_counts']


@lru_cache(None)
def selection_rows():
    panels = {p: scored(q.COUNTS[p])['metrics'] for p in q.gates.PANELS}
    return {step: deepcopy(panels) for step in q.STEPS}


def production_gate_selection(values):
    return q.gates.select_candidate({step: {panel:q.gates.gate_counts(score) for panel,score in panels.items()}
                                     for step,panels in values.items()})


def test_independent_selection_does_not_dispatch_to_shared_selection(monkeypatch):
    values=deepcopy(selection_rows());expected=production_gate_selection(values)
    monkeypatch.setattr(q.gates,'select_candidate',lambda _:pytest.fail('shared selection called'))
    assert q.independent_selection(values)==expected


@pytest.mark.parametrize('panel',q.gates.RETENTION_PANELS)
def test_independent_class_gate_reconstruction_matches_prospective_contract(panel):
    values=deepcopy(selection_rows());values[50][q.gates.NEW_TUNING]=scored(288,strength=6.)['metrics']
    values[50][panel]=scored(q.COUNTS[panel],changes={'query-0000':('exception',5.)})['metrics']
    actual=q.independent_selection(values)
    assert 50 not in actual['eligible_steps'] and actual==production_gate_selection(values)


def test_independent_gate_blocks_same_class_wrong_id_swap():
    values=deepcopy(selection_rows())
    for step in q.STEPS:values[step]['old_multi_fresh']=scored(96,changes={'query-0000':('exception',5.)})['metrics']
    values[50]['old_multi_fresh']=scored(96,changes={'query-0004':('exception',5.)})['metrics']
    values[50][q.gates.NEW_TUNING]=scored(288,strength=6.)['metrics']
    actual=q.independent_selection(values)
    assert actual==production_gate_selection(values)
    assert actual['eligibility']['50']['panels']['old_multi_fresh']['failures']==['norm:new_accepted_error_ids']


def test_independent_gate_blocks_all_defer_with_unchanged_accuracy():
    values=deepcopy(selection_rows());values[50]['old_multi_fresh']=scored(96,strength=1.)['metrics']
    actual=q.independent_selection(values)
    assert actual==production_gate_selection(values) and 50 not in actual['eligible_steps']


def test_independent_rank_nll_then_earliest_with_full_candidate_zero():
    values=deepcopy(selection_rows())
    for step in (100,200):values[step][q.gates.NEW_TUNING]=scored(288,strength=6.)['metrics']
    actual=q.independent_selection(values)
    assert actual==production_gate_selection(values) and actual['selected_steps']==100


def test_independent_new_tuning_class_floor_has_no_extra_coverage_gate():
    values=deepcopy(selection_rows());values[50][q.gates.NEW_TUNING]=scored(288,strength=1.)['metrics']
    actual=q.independent_selection(values)
    assert actual==production_gate_selection(values) and 50 in actual['eligible_steps']


@pytest.mark.parametrize('change',['missing_panel','extra_fresh','changed_target','changed_source'])
def test_independent_selection_rejects_unbound_panel_or_reference(change):
    values=deepcopy(selection_rows())
    if change=='missing_panel':values[50].pop('old_multi_fresh')
    if change=='extra_fresh':values[50]['fresh_lexical']=values[50][q.gates.NEW_TUNING]
    if change=='changed_target':values[50]['old_multi_fresh']['rows'][0]['target']='condition'
    if change=='changed_source':values[50]['old_multi_fresh']['rows'][0]['source_sha256']='a'*64
    with pytest.raises(ValueError):q.independent_selection(values)


def test_changed_unselected_training_report_bytes_are_rejected(complete_inventory):
    freeze,data=complete_inventory;trials=q.read(freeze['selections'])['trials']
    path=trials[0]['stages'][1]['training_report']['path']
    with open(path,'w') as handle:handle.write('{"changed":true}')
    with pytest.raises(ValueError,match='bytes changed'):q.inventory(freeze,data)


def sampling_pools():
    return ({f'g-{i}':[f'single-{i}-{j}' for j in range(4)] for i in range(8)},
            {f'u-{i}':[f'prior-{i}-{j}' for j in range(12)] for i in range(5)},
            {f'n-{i}':[f'new-{i}-{j}' for j in range(12)] for i in range(5)})


def test_independent_sampler_uses_continuous_three_groups_not_prior_six_prefix():
    singles,old,new=sampling_pools();stream=[]
    for epoch in range(4):
        order=sorted(singles);random.Random(1730+epoch).shuffle(order);stream.extend(order)
    for step in range(8):
        row=q.expected_batch(singles,old,new,seed=1730,step=step,arm='placement_ce')
        assert row['single_group_ids']==stream[3*step:3*step+3]
        assert len(row['query_ids'])==24 and bool(row['placement_unit_ids']) is (step%2==1)


def test_independent_sampler_matches_old_units_on_odd_one_based_steps():
    pools=sampling_pools()
    for step in range(200):
        a=q.expected_batch(*pools,seed=1731,step=step,arm='placement_ce')
        b=q.expected_batch(*pools,seed=1731,step=step,arm='placement_kl')
        c=q.expected_batch(*pools,seed=1731,step=step,arm='placement_head_only')
        assert a==b==c
        if step%2:assert b['prior_paired_unit_ids']==[] and len(b['placement_unit_ids'])==1


def test_independent_sampler_new_stream_uses_half_step_position_and_distinct_salt():
    pools=sampling_pools();stream=[]
    for epoch in range(3):
        names=sorted(pools[2]);random.Random(1730+2000003+epoch).shuffle(names);stream.extend(names)
    for index in range(12):
        row=q.expected_batch(*pools,seed=1730,step=2*index+1,arm='placement_kl')
        assert row['placement_unit_ids']==[stream[index]]


def test_sampler_rejects_duplicate_query_pool_membership():
    pools=sampling_pools();pools[0]['g-1'][0]=pools[0]['g-0'][0]
    with pytest.raises(ValueError):q.expected_batch(*pools,seed=1730,step=0,arm='placement_kl')


def test_multiple_norm_anchors_modals_and_realized_placements_are_verified():
    rows=[r for unit in range(6) for source in range(5) for r in q.placement_prior.corpus.render_source('tuning',unit,source)]
    repeated=next(r for r in rows if len(r['annotation']['modal_spans'])>1)
    assert q.body_layout(repeated).count('[MODAL]')==len(repeated['annotation']['modal_spans'])
    changed=deepcopy(repeated);changed['annotation']['modal_spans'].pop()
    with pytest.raises(ValueError,match='modals'):q.body_layout(changed)
    norm=deepcopy(next(r for r in rows if r['label']=='norm'))
    norm['annotation']['norm_time_placement']='not_realized'
    with pytest.raises(ValueError,match='realized norm'):q.body_layout(norm)


@pytest.mark.parametrize('field,value',[('local_atom_ordinal',99),('source_occurrence_ordinal',99),
                                      ('enclosure_family','joint_qualifiers'),('layout_family','norm')])
def test_annotated_source_order_and_ordinal_claims_are_not_trusted(field,value):
    row=deepcopy(q.placement_prior.corpus.render_source('tuning',0,1)[0]);row['annotation'][field]=value
    with pytest.raises(ValueError):q.body_layout(row)


def test_fictional_joint_enclosure_preserves_offsets_without_current_fresh_renderer():
    options=[r for unit in range(6) for source in range(5) for r in q.placement_prior.corpus.render_source('tuning',unit,source)]
    original=next(r for r in options if r['annotation']['enclosure_family']=='none' and
                  r['annotation']['layout_family']=='norm_condition_exception')
    row=deepcopy(original);text=row['source_text'];a=row['annotation']
    lo=a['block_spans']['condition']['char_start'];hi=a['block_spans']['exception']['char_end']
    changed=text[:lo]+'('+text[lo:hi]+')'+text[hi:]
    body=(a['body_span']['char_start'],a['body_span']['char_end'])
    def relocate(value):
        if type(value) is list:
            for item in value:relocate(item)
        elif type(value) is dict:
            if set(value)=={'char_start','char_end','text'}:
                start,end=value['char_start'],value['char_end']
                after_start=start+sum(position<=start for position in (lo,hi))
                after_end=end+sum(position<end for position in (lo,hi))
                if (start,end)==body:after_end=end+sum(position<=end for position in (lo,hi))
                value.update(char_start=after_start,char_end=after_end,text=changed[after_start:after_end])
            else:
                for child in value.values():relocate(child)
    relocate(a);row['source_text']=changed;row['source_sha256']=hashlib.sha256(changed.encode()).hexdigest()
    row['proposed_time_span']={k:a['time_span'][k] for k in ('char_start','char_end')}
    a['enclosure_family']='joint_qualifiers'
    # Layout validation does not assert label truth; the fixture only proves
    # new exact punctuation offsets survive the independent source mask.
    layout=q.body_layout(row)
    assert '(if ' in layout and 'unless ' in layout and layout.endswith(').')
    a['enclosure_family']='none'
    with pytest.raises(ValueError,match='joint qualifier'):q.body_layout(row)


def test_full_authored_reference_check_occurs_only_after_release(tmp_path,monkeypatch):
    artifacts={key:q.write(tmp_path/(key+'.json'),
               {'units':{'fresh_lexical':[],'fresh_structural':[]}} if key=='fresh_annotation_ledger' else [])
               for key in q.runner.SEALED_KEYS}
    manifest={'artifacts':artifacts};state=q.phase_guard(manifest,q.runner.SEALED_KEYS)
    freeze=q.write(tmp_path/'freeze.json',{});replay=q.write(tmp_path/'replay.json',{})
    monkeypatch.setattr(q,'load_inputs',lambda _:({'manifest':manifest},state))
    monkeypatch.setattr(q,'inventory',lambda *a:({}, {}, {}, {}, {}))
    monkeypatch.setattr(q,'check_replay',lambda *a:None)
    monkeypatch.setattr(q,'score_admitted',lambda *a:([],{},{}))
    def stop(rows,units,panel,*,reconstruct):
        assert state['released'] is True and reconstruct is True
        assert not state['premature_read_attempts']
        raise ValueError('fixture stops after release-only authored validation')
    monkeypatch.setattr(q.corpus,'validate_units',stop)
    with pytest.raises(ValueError,match='fixture stops'):q.score(freeze['path'],replay['path'],tmp_path/'score.json')
    assert state['released'] is True and state['postrelease_reads']


def interposed_fixture(family='actor_joint_modal_action',order=('condition','exception'),placement='before_actor',query_owner='norm'):
    """Author a fictional source locally; never invoke a current fresh renderer."""
    pieces=[];roles=[];modals=[];norms=[];blocks={};times=[]
    def add(text):
        start=sum(map(len,pieces));pieces.append(text)
        return {'char_start':start,'char_end':start+len(text),'text':text}
    def region(start):
        text=''.join(pieces);return {'char_start':start,'char_end':len(text),'text':text[start:]}
    def atom(role,text):
        value=add(text);roles.append({'role':role,'span':value});return value
    heading=add('Fictional review heading. ');body_start=heading['char_end'];joint=None;condition_time=None
    for n in range(2):
        start=sum(map(len,pieces));time=None
        if placement=='before_actor':time=add(f'within {17+n} days of notice');add(' ')
        actor=atom('actor',f'Office {n}');add(' ')
        for part in ('before_modal','after_modal'):
            if part=='after_modal':
                modal=add('shall');modals.append(modal);add(' ')
                if placement=='after_modal':time=add(f'within {17+n} days of notice');add(' ')
            wanted='before_modal' if family=='actor_joint_modal_action' else 'after_modal'
            if n==0 and part==wanted:
                joint_start=sum(map(len,pieces));add('(')
                for oi,owner in enumerate(order):
                    begin=sum(map(len,pieces));add('if ' if owner=='condition' else 'unless ')
                    for i in range(3):
                        atom(owner+'_predicate',f'{owner} permit {i}')
                        add(' was received')
                        if owner=='condition' and i==0: add(' ');condition_time=add('within 71 days of notice')
                        if i<2:add(' and ')
                    blocks[owner]=region(begin)
                    if oi==0:add(', ')
                add(')');joint=region(joint_start);add(' ')
        action=atom('action',f'file report {n}')
        if placement=='after_action':add(' ');time=add(f'within {17+n} days of notice')
        norms.append({'actor_span':actor,'modal_span':modal,'action_span':action,'time_span':time,'clause_span':region(start)})
        times.append(time)
        if n==0:add('; ')
    body=region(body_start);blocks['norm']=deepcopy(body);add('.')
    text=''.join(pieces);chosen=times[0] if query_owner=='norm' else condition_time
    role='action' if query_owner=='norm' else 'condition_predicate'
    anchor=next(r['span'] for r in roles if r['role']==role)
    source=q.corpus.query(text,{k:chosen[k] for k in ('char_start','char_end')})
    annotation={'schema':'authored-temporal-stability-annotation/v1','heading_span':heading,'body_span':body,
        'time_span':chosen,'source_occurrence_ordinal':q.corpus.propose_time_spans(text).index(source['proposed_time_span'])+1,
        'source_role_spans':roles,'modal_spans':modals,'norm_occurrences':norms,'modality':'O',
        'norm_time_placement':placement,'block_spans':blocks,'qualifier_order':list(order),
        'structural_family':family,'enclosure_family':'interposed_joint_qualifiers','layout_family':family,
        'interposition_span':joint,'authored_local_owner_type':query_owner,'local_atom_ordinal':1,
        'owner_candidates':[{'owner_type':query_owner,'anchor_span':anchor}]}
    return {**source,'label':query_owner,'annotation':annotation}


@pytest.mark.parametrize('family',['actor_joint_modal_action','actor_modal_joint_action'])
@pytest.mark.parametrize('order',[('condition','exception'),('exception','condition')])
@pytest.mark.parametrize('placement',['before_actor','after_modal','after_action'])
def test_fictional_interposition_checks_every_repeated_norm(family,order,placement):
    row=interposed_fixture(family,order,placement,query_owner='condition')
    value=q.verify_stability_annotation(row)
    assert value['norm_occurrences']==value['realized_norm_deadlines']==2
    layout=q.body_layout(row)
    assert layout.count('[MODAL]')==2 and layout.count('[TIME]')==3
    assert q.mask_layout(row)==q.corpus.body_layout(row)


@pytest.mark.parametrize('mutation',[
    lambda a:a['norm_occurrences'].pop(),
    lambda a:a['norm_occurrences'][1].update(time_span=a['time_span']),
    lambda a:a['norm_occurrences'][1].update(actor_span=a['norm_occurrences'][0]['actor_span']),
    lambda a:a['norm_occurrences'][0].update(clause_span=a['norm_occurrences'][0]['actor_span']),
    lambda a:a.update(structural_family='actor_modal_joint_action',layout_family='actor_modal_joint_action'),
    lambda a:a.update(interposition_span=a['block_spans']['condition']),
    lambda a:a.update(qualifier_order=['exception','condition']),
    lambda a:a.update(norm_time_placement='after_action'),
    lambda a:a['modal_spans'].pop(),
    lambda a:a.update(source_occurrence_ordinal=True),
])
def test_fictional_interposition_rejects_source_bound_metadata_laundering(mutation):
    row=interposed_fixture(query_owner='condition');mutation(row['annotation'])
    with pytest.raises(ValueError):q.body_layout(row)


def test_generic_history_mask_normalizes_role_aliases_and_derives_old_modals():
    row=interposed_fixture();expected=q.mask_layout(row);changed=deepcopy(row)
    a=changed['annotation'];a.pop('modal_spans')
    a['lexical_spans']=a.pop('source_role_spans')
    aliases={'action':'action_object','condition_predicate':'condition_anchor','exception_predicate':'exception_anchor'}
    for entry in a['lexical_spans']:entry['role']=aliases.get(entry['role'],entry['role'])
    assert q.mask_layout(changed)==expected


@pytest.fixture
def teacher_receipt_bundle(tmp_path,monkeypatch):
    sources,labels=fixtures(1632)
    targets=[{**r,'label':labels[r['id']],'group_id':f'g-{i//4}'} for i,r in enumerate(sources)]
    data={'single_training':targets[:768],'prior_paired_training':targets[768:]}
    parents={};cache_refs={};replays=[]
    monkeypatch.setattr(q.runner.runtime,'producer_pins',lambda:{})
    monkeypatch.setattr(q.teacher_checker,'producer_pins',lambda:[])
    for seed in q.SEEDS:
        parent={'config':{'arm':'mixed_occurrences','seed':seed},'optimizer_steps':200,'model_state':{'head':[float(seed)]}}
        pin=q.write(tmp_path/f'parent-{seed}.json',parent);parents[str(seed)]=pin
        outputs=[{k:r[k] for k in ('id','source_sha256','proposed_time_span','label')}|
                 {'logits':[5. if c==r['label'] else 0. for c in q.metric.CLASSES],'correct':True} for r in targets]
        cache={'schema':'legal-temporal-stability-teacher-cache/v1','implementation':{},'seed':seed,
            'parent_file_sha256':pin['sha256'],'parent_payload_sha256':q.digest(parent),
            'training_manifests':{k:{'sha256':q.digest(v),'count':len(v)} for k,v in data.items()},
            'sources_sha256':q.digest(sources),'class_order':list(q.metric.CLASSES),'batch_size':48,'rows':outputs,
            'teacher_state_before_sha256':q.digest(parent['model_state']),'teacher_state_after_sha256':q.digest(parent['model_state']),
            'teacher_requires_grad':False,'teacher_gradients_absent':True,'encoder_batch_forwards':34,'encoder_source_evaluations':1632,
            'labels_used_only_for_correctness_mask':True,'new_placement_rows_included':False,
            **{k:False for k in q.metric.FALSE_FIELDS}}
        cachepin=q.write(tmp_path/f'cache-{seed}.json',cache);cache_refs[str(seed)]=cachepin
        replays.append({'seed':seed,'parent':pin,'cache':cachepin,'cache_payload_sha256':q.digest(cache),
            'sources_sha256':q.digest(sources),'correct_training_rows_by_class':{c:408 for c in q.metric.CLASSES},
            'model_state_before_sha256':q.digest(parent['model_state']),'model_state_after_sha256':q.digest(parent['model_state']),
            'exact_rows':1632,'logits_and_sources_sha256':q.digest([{k:r[k] for k in ('id','source_sha256','proposed_time_span','logits')} for r in outputs]),
            'encoder_batch_forwards':34,'encoder_source_evaluations':1632})
    config={'parents':parents};configpin=q.write(tmp_path/'config.json',config)
    wrapper={'schema':'legal-temporal-stability-teacher-cache-freeze/v1','config':configpin,'parents':parents,
        'models':cache_refs,'producer_pins':{},'encoder_batch_forwards':68,'encoder_source_evaluations':3264,
        'optimizer_updates':0,'fresh_references_opened':False,'fresh_reference_guard':{'premature_read_attempts':0}}
    wrapperpin=q.write(tmp_path/'teacher-freeze.json',wrapper)
    receipt={'schema':q.teacher_checker.SCHEMA,'config':configpin,'teacher_cache_freeze':wrapperpin,
        'producer_files':[],'teachers':replays,'exact_replay':True,'encoder_batch_forwards':68,'encoder_source_evaluations':3264,
        'optimizer_updates':0,'fresh_references_opened':False,
        'fresh_reference_guard':{'released':False,'premature_read_attempts':[],'postrelease_reads':[]}}
    receiptpin=q.write(tmp_path/'teacher-replay.json',receipt)
    freeze={'config':configpin,'teacher_cache_freeze':wrapperpin,'independent_teacher_replay':receiptpin}
    return freeze,data,config,deepcopy(freeze),deepcopy(freeze),receipt


def test_prefit_teacher_replay_is_revalidated_without_any_neural_call(teacher_receipt_bundle,monkeypatch):
    freeze,data,config,initial,selection,receipt=teacher_receipt_bundle
    monkeypatch.setattr(q.teacher_checker,'replay_cache_logits',lambda *a:pytest.fail('teacher replay repeated'))
    result=q.verify_teacher_replay(freeze,data,config,initial,selection)
    assert set(result)=={'1730','1731'} and all(set(v)=={'reference','payload_sha256'} for v in result.values())


@pytest.mark.parametrize('change',[
    lambda r:r.update(exact_replay=False),
    lambda r:r.update(encoder_batch_forwards=True),
    lambda r:r.update(optimizer_updates=1),
    lambda r:r['fresh_reference_guard'].update(released=True),
    lambda r:r['fresh_reference_guard'].update(postrelease_reads=['/fresh']),
    lambda r:r['teachers'].pop(),
    lambda r:r['teachers'][0].update(logits_and_sources_sha256='0'*64),
    lambda r:r['teachers'][0]['correct_training_rows_by_class'].update(condition=407),
    lambda r:r['teachers'][0].update(model_state_after_sha256='0'*64),
])
def test_teacher_receipt_corruption_rejected_with_repaired_outer_file_pin(teacher_receipt_bundle,tmp_path,change):
    freeze,data,config,initial,selection,receipt=teacher_receipt_bundle;change(receipt)
    repaired=q.write(tmp_path/'changed-teacher-replay.json',receipt)
    for value in (freeze,initial,selection):value['independent_teacher_replay']=repaired
    with pytest.raises(ValueError):q.verify_teacher_replay(freeze,data,config,initial,selection)


def test_teacher_cache_swap_in_initial_lineage_fails(teacher_receipt_bundle):
    freeze,data,config,initial,selection,_=teacher_receipt_bundle
    initial['teacher_cache_freeze']['sha256']='a'*64
    with pytest.raises(ValueError,match='lineage'):q.verify_teacher_replay(freeze,data,config,initial,selection)


def test_reduced_admitted_inventory_keeps_train_only_parent_and_final():
    assert q.evaluated_panels(0)==q.evaluated_panels(200)==q.ADMITTED
    assert q.evaluated_panels(50)==q.evaluated_panels(100)==q.gates.PANELS
    saved=sum(q.COUNTS[p] for p in q.evaluated_panels(0))*2
    saved+=sum(sum(q.COUNTS[p] for p in q.evaluated_panels(step)) for step in (50,100,200))*6
    assert saved==51648
