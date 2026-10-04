"""Independent release ordering, metric, parent selection and alias contracts."""
from copy import deepcopy
import hashlib
import json

import pytest

from scripts.ops.legal_ir import qualify_legal_paired_ownership_head as q


def selection_scores():
    return {step: {'single_tuning': {'count':144, 'correct':144, 'accepted_type_errors':0, 'macro_f1':1., 'mean_nll':.05},
                   'paired_tuning': {'count':288, 'correct':200, 'accepted_type_errors':8, 'macro_f1':.7, 'mean_nll':.6}}
            for step in q.STEPS}


def test_parent_included_and_tie_prefers_no_updates():
    assert q.independent_selection(selection_scores())['selected_steps'] == 0


def test_new_tuning_rank_and_old_tuning_error_retention_are_independent():
    scores = selection_scores(); scores[50]['paired_tuning']['macro_f1'] = .9
    scores[100]['paired_tuning']['macro_f1'] = .99; scores[100]['single_tuning']['correct'] = 143
    scores[200]['paired_tuning']['macro_f1'] = 1.; scores[200]['single_tuning'].update(correct=143,accepted_type_errors=1)
    result = q.independent_selection(scores)
    assert result['selected_steps'] == 50 and result['eligible_steps'] == [0,50]


def test_nll_then_earliest_stage_tiebreak_and_no_coverage_gate():
    scores = selection_scores()
    for step in (100,200):
        scores[step]['paired_tuning'].update(mean_nll=.5, accepted_type_proposals=0)
    assert q.independent_selection(scores)['selected_steps'] == 100
    assert q.independent_selection(scores)['coverage_gate_applied'] is False


@pytest.mark.parametrize('mutation', [
    lambda s:s.pop(0), lambda s:s.pop(200), lambda s:s.update({True:s[50]}),
    lambda s:s[0]['single_tuning'].update(count=True),
    lambda s:s[50]['single_tuning'].update(correct=145),
    lambda s:s[50]['single_tuning'].update(accepted_type_errors=True),
    lambda s:s[50]['paired_tuning'].update(macro_f1=float('nan')),
    lambda s:s[50]['paired_tuning'].update(macro_f1=2.),
    lambda s:s[50]['paired_tuning'].update(mean_nll=-1.),
])
def test_invalid_selection_counts_rejected(mutation):
    scores = selection_scores(); mutation(scores)
    with pytest.raises(ValueError):q.independent_selection(scores)


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
    value={'schema':'legal-temporal-owner-type-source-generation/v1','model':{'checkpoint':cp,'decoder_kind':'paired_owner_type','arm':'mixed_occurrences','seed':1730,'steps':200},
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


def test_error_retention_rejects_while_accuracy_retained():
    scores=selection_scores()
    for step in q.STEPS:scores[step]['single_tuning']['correct']=143
    scores[50]['paired_tuning']['macro_f1']=.99
    scores[50]['single_tuning']['accepted_type_errors']=1
    assert q.independent_selection(scores)['selected_steps']==0


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
    parent={'decoder_kind':'old_owner_type','arm':'parent','seed':1730,'additional_steps':0}
    assert q.physical_metadata(parent)=={'decoder_kind':'old_owner_type','arm':'finetune_occurrence','seed':1730,'step':200}
    alias={**parent,'arm':'mixed_occurrences'}
    assert q.physical_metadata(alias)==q.physical_metadata(parent)


def test_replay_manifest_payload_change_is_rejected(tmp_path,monkeypatch):
    source,row,cp,pin,value=sample();sourcepin=q.write(tmp_path/'sources.json',[source]);value['sources']=sourcepin
    genpin=q.write(tmp_path/'generation.json',value);key='k';slot={'panel':'fresh_lexical','checkpoint':cp,
        'decoder_kind':'paired_owner_type','arm':'mixed_occurrences','seed':1730,'additional_steps':200,'generation':genpin}
    freeze={'sources':{'fresh_lexical':sourcepin}};freezepin=q.write(tmp_path/'freeze.json',freeze)
    receipt={'key':key,'checkpoint':cp,'decoder_kind':'paired_owner_type','sources':sourcepin,'generation':genpin,
        'rows_sha256':q.digest(value['rows']),'exact_rows':1,'encoder_batch_forwards':1,'encoder_source_evaluations':1}
    replay={'schema':'legal-paired-owner-type-independent-replay/v1','generation_freeze':freezepin,'exact_replay':True,
        'fresh_references_opened':False,'fresh_reference_guard':{'released':False,'premature_read_attempts':[]},
        'producer_files':[],'replays':[receipt],'encoder_batch_forwards':1,'encoder_source_evaluations':1}
    monkeypatch.setattr(q,'producer_pins',lambda:[])
    args=(freeze,freezepin,replay,{'fresh_lexical':[source]},{key:slot},
        {'physical_fresh_encoder_batch_forwards':1,'physical_fresh_query_rows':1})
    q.check_replay(*args)
    receipt['rows_sha256']='0'*64
    with pytest.raises(ValueError,match='binding differs'):q.check_replay(*args)


def test_admitted_renderer_reference_candidates_are_coordinate_only():
    rows=q.corpus.render_source('tuning',0,1)
    audit=q.reference_candidate_audit(rows)
    assert audit['queries']==len(rows) and audit['used_as_inference_inventory'] is False
    assert audit['owner_occurrence_accuracy_measured'] is False
    changed=deepcopy(rows);changed[0]['annotation']['attachment_cue_spans'][0]['owner_occurrence_id']='wrong'
    with pytest.raises(ValueError,match='join differs'):q.reference_candidate_audit(changed)


def test_independent_body_layout_matches_admitted_renderer_and_rejects_bad_offsets():
    rows=[r for unit in range(4) for source in range(5) for r in q.corpus.render_source('tuning',unit,source)]
    assert all(q.body_layout(r)==q.corpus.body_layout(r) for r in rows)
    changed=deepcopy(rows[0]);changed['annotation']['source_role_spans'][0]['span']['char_start']+=1
    with pytest.raises(ValueError,match='span differs'):q.body_layout(changed)


@pytest.fixture
def complete_inventory(tmp_path,monkeypatch):
    def save(name,value,schema=None):
        pin=q.write(tmp_path/(name+'.json'),value)
        return {**pin,'schema':schema} if schema else pin
    schema='legal-temporal-owner-type-checkpoint/v1'
    parents={str(seed):save(f'parent-{seed}',{'schema':schema,'model_state':{'w':[seed]},'config':{'arm':'finetune_occurrence','seed':seed}},schema)
             for seed in q.SEEDS}
    config=save('config',{'parents':parents,'corpus_manifest':save('manifest',{})})
    data={'manifest_ref':q.read(config)['corpus_manifest'],'regression_sources':{}}
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
    evidence={str(seed):{panel:{'generation':save(f'pgen-{seed}-{panel}',{}),'metrics':{}} for panel in q.ADMITTED} for seed in q.SEEDS}
    parentfreeze=save('parent-freeze',{'parents':parents,'evaluations':evidence,'fresh_references_opened':False,
        'fresh_reference_guard':{'premature_read_attempts':0}})
    models={};trials=[]
    for arm in q.ARMS:
        for seed in q.SEEDS:
            name=f'{arm}-{seed}';parent=q.read(parents[str(seed)])
            cp={'schema':q.CHECKPOINT_SCHEMA,'optimizer_steps':0,'config':{'arm':arm,'seed':seed},
                'model_state':parent['model_state'],'parent':parent,'parent_file_sha256':parents[str(seed)]['sha256'],
                'optimizer_state':{'parameters':{}}}
            models[name]=save('init-'+name,cp,q.CHECKPOINT_SCHEMA)
            parent_candidate={'steps':0,'checkpoint':parents[str(seed)],'decoder_kind':'old_owner_type'}
            for panel in q.ADMITTED:
                parent_candidate[panel+'_generation']=evidence[str(seed)][panel]['generation']
                parent_candidate[panel+'_metrics']={}
            stages=[{'steps':step,'checkpoint':save(f'{name}-{step}',{'schema':q.CHECKPOINT_SCHEMA,'step':step,'name':name},q.CHECKPOINT_SCHEMA),
                     'training_report':save(f'{name}-report-{step}',{}),'decoder_kind':'paired_owner_type','eligible':False} for step in q.STEPS[1:]]
            trials.append({'name':name,'arm':arm,'seed':seed,'fresh_references_opened':False,'fresh_reference_guard':{'premature_read_attempts':0},
                'selected_is_pipeline_promotion':False,'parent_checkpoint':parents[str(seed)],'initial_checkpoint':models[name],
                'initial_evaluation':evidence[str(seed)],'parent_candidate':parent_candidate,'stages':stages,
                'selected_steps':0,'selected_checkpoint':parents[str(seed)],'selected_decoder_kind':'old_owner_type','selected_parent_fallback':True})
    initials=save('initials',{'config':config,'models':models,'parents':parents,'fresh_references_opened':False,
                             'fresh_reference_guard':{'premature_read_attempts':0}})
    selected=save('selection',{'config':config,'initialization_freeze':initials,'parent_evaluations':parentfreeze,
        'fresh_references_opened':False,'no_pipeline_promotion':True,'trials':trials,
        'trial_references':[save('trial-'+t['name'],t) for t in trials]})
    slots=[{'slot':f'parent-{seed}','arm':'parent','seed':seed,'role':'parent','additional_steps':0,
            'checkpoint':parents[str(seed)],'decoder_kind':'old_owner_type'} for seed in q.SEEDS]
    for t in trials:
        for role in ('selected','final200'):
            slots.append({'slot':t['name']+'__'+role,'arm':t['arm'],'seed':t['seed'],'role':role,
                'additional_steps':0 if role=='selected' else 200,'checkpoint':t['selected_checkpoint'] if role=='selected' else t['stages'][-1]['checkpoint'],
                'decoder_kind':'old_owner_type' if role=='selected' else 'paired_owner_type'})
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
        'logical_generation_slots':56,'logical_fresh_query_rows':8064,'physical_generation_files':32,'physical_fresh_query_rows':4608,
        'physical_fresh_encoder_batch_forwards':96,'total_optimizer_updates':1200,'training_encoder_batch_forwards':1200,
        'training_encoder_source_evaluations':28800,'admitted_generation_counters':{'encoder_batch_forwards':860,'encoder_source_evaluations':41280}}
    monkeypatch.setattr(q.runner,'producer_pins',lambda:{})
    monkeypatch.setattr(q.runner,'PARENT_SHAS',{seed:parents[str(seed)]['sha256'] for seed in q.SEEDS})
    return freeze,data


def test_full_inventory_preserves_parent_fallback_aliases_and_diagnostics(complete_inventory):
    freeze,data=complete_inventory;_,trials,_,unique,counts=q.inventory(freeze,data)
    assert len(trials)==6 and len(unique)==32 and counts['logical_generation_slots']==56
    assert counts['physical_fresh_query_rows']==4608


@pytest.mark.parametrize('mutation',[
    lambda f:f['logical_generations'].pop(),
    lambda f:f['logical_generations'].append(deepcopy(f['logical_generations'][0])),
    lambda f:f['logical_generations'][8].update(executed_here=True),
    lambda f:f['logical_generations'][8].update(decoder_kind='paired_owner_type'),
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
