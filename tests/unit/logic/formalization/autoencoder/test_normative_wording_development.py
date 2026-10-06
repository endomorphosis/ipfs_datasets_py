"""Durable source/reference barrier and complete60-row endpoint controls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

P = Path(__file__).resolve().parents[5]
spec = importlib.util.spec_from_file_location('_normative_development_tests',
    P/'scripts/ops/autoencoder/evaluate_normative_wording_development.py')
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def fixture(tmp_path):
    rows = [dict(id=f'synthetic:{i}',source_text=f'Synthetic source {i}.',input=[float(i)]) for i in range(60)]
    codec = {'target_vocabulary':['PAD','BOS','EOS','{','}']+[str(i) for i in range(27)]}
    lanes = {d:dict(fresh_rows=deepcopy(rows),fresh_contexts={'synthetic':'context'},
        donor=dict(codec=codec,input_transform={'synthetic':'original'})) for d in (384,768)}
    runs,records,manifest = {},[],{'inputs':{},'development_recipe_seal':'a'*64}
    for dimension in (384,768):
        for arm in subject.ARMS:
            states = {r:dict(tensor_sha256=digest([dimension,arm,r]),path='synthetic') for r in subject.ROLES}
            runs[dimension,arm] = dict(states=states)
            for role in subject.ROLES:
                panel = dict(complete=True,model_tensor_sha256=states[role]['tensor_sha256'],
                    source_rows_sha256=digest(rows),source_contexts_sha256=digest(lanes[dimension]['fresh_contexts']),
                    predictions=[dict(id=r['id'],token_ids=[]) for r in rows],generation_reference_access=False,
                    greedy_passes_per_row=1,generation_temperature=0,max_target_tokens=512)
                path = tmp_path/f'{dimension}-{arm}-{role}.json'
                trace = dict(schema='generated-contextual-scalar-trace/v1',complete=True,sample_count=60,
                    dimension=dimension,model_tensor_sha256=states[role]['tensor_sha256'],
                    source_rows_sha256=digest(rows),source_contexts_sha256=digest(lanes[dimension]['fresh_contexts']),
                    codec_sha256=digest(codec),input_transform_sha256=digest(lanes[dimension]['donor']['input_transform']),
                    vocabulary_size=32,generation_temperature=0,max_target_tokens=512,batch_size=8,
                    predictions=deepcopy(panel['predictions']),source_only=True,full_vocabulary_retained=True,
                    decomposition_exact=True,caller_state_preserved=True,hooks_removed=True,
                    complete_rollout_before_reference_scoring=True,
                    **{k:False for k in ('reference_count_access','reference_prefix_access',
                        'reference_documents_passed_to_model','inventory_access','source_context_target_access',
                        'syntax_mask','forced_closure','model_copied',*subject.TRACE_FALSE_FLAGS)},
                    extra_model_passes=0,source_head_extra_evaluations=0,optimizer_steps=0)
                trace['trace_sha256'] = digest(trace)
                trace_path = tmp_path/f'{dimension}-{arm}-{role}-trace.json'
                trace_path.write_text(json.dumps(trace))
                panel['same_pass_scalar_trace_sha256'] = trace['trace_sha256']
                path.write_text(json.dumps(panel))
                records.append(dict(dimension=dimension,arm=arm,role=role,state_ref=states[role],
                    predictions_ref=dict(path=str(path),sha256=subject.sha(path)),prediction_fsynced=True,
                    source_head_trace_ref=dict(path=str(trace_path),sha256=subject.sha(trace_path)),
                    source_head_trace_fsynced=True))
    refs = [dict(id=r['id'],source_text=r['source_text'],source_sha256=hashlib.sha256(r['source_text'].encode()).hexdigest(),
        split='prospective_authored_development',clause_count=1,template='fixed',target={},
        target_sha256=digest({}),target_ids=[1,3,4,2],target_ids_sha256=digest([1,3,4,2])) for r in rows]
    receipt = dict(complete=True,schema='prospective-normative-development/v1',references_sha256=digest(refs),
        source_rows_sha256=digest([{k:r[k] for k in ('id','source_text')} for r in rows]),codec_sha256=digest(codec),
        sealed_recipe_sha256='a'*64,actor_action_disjointness_checked=True,actor_action_group_overlap=0,
        original_meanings_previously_exposed=True,training_allowed=False,selection_allowed=False,
        independent_human_review_authenticated=False,source_semantics_verified=False,admitted=False,qualified=False)
    receipt['receipt_sha256'] = digest(receipt)
    for name,value in [('references',refs),('development_receipt',receipt)]:
        path = tmp_path/(name+'.json')
        path.write_text(json.dumps(value))
        manifest[name] = str(path)
        manifest['inputs'][str(path)] = subject.sha(path)
    return manifest,records,runs,lanes,codec,refs


@pytest.mark.parametrize('key,value',[('dimensions',[384]),('roles',['selected']),('panel_count',4),
    ('samples_per_panel',48),('temperature',1),('context_tokens',1024),('output_tokens',1024),
    ('vocabulary_size',3),('used_for_selection',True),('fresh_holdout',True),
    ('predictions_fsynced_before_reference_load',False),('all_predictions_before_reference_load',False),
    ('training_executed',True),('encoder_executed',True),('independent_semantic_holdout',True),
    ('source_head_trace_same_greedy_pass',False),('extra_source_head_evaluations',8),
    ('unvisited_source_sites_counted_correct',True),('source_head_and_formula_join_after_reference_barrier',False)])
def test_fixed_postfit_recipe_refuses_shortcuts(key,value):
    plan = deepcopy(subject.FIXED)
    subject.validate_plan(plan)
    plan[key] = value
    with pytest.raises(ValueError,match='recipe differs'):subject.validate_plan(plan)


def test_all_eight60_row_panels_allow_references(tmp_path):
    manifest,records,runs,lanes,codec,refs = fixture(tmp_path)
    actual,receipt = subject.load_references(manifest,records,runs,lanes,codec,digest)
    assert actual == refs
    adapted = subject.scoring_references(actual,receipt)
    assert adapted[0]['components'] == [dict(slot=0,training_pair_seen=False)]
    assert 'components' not in actual[0]


@pytest.mark.parametrize('mutation',['missing','duplicate','file','state','source','contexts','ids',
    'labels','temperature','repeat','partial','fsync','trace_fsync','trace_file','trace_labels',
    'trace_extra_forward','trace_logits_mask','trace_pred','trace_missing','trace_source'])
def test_any_bad_panel_fails_before_reference_parse(tmp_path,monkeypatch,mutation):
    manifest,records,runs,lanes,codec,_ = fixture(tmp_path)
    if mutation == 'missing':records.pop()
    elif mutation == 'duplicate':records[-1] = deepcopy(records[0])
    elif mutation == 'state':records[0]['state_ref'] = dict(records[0]['state_ref'],tensor_sha256='wrong')
    elif mutation == 'fsync':records[0]['prediction_fsynced'] = False
    elif mutation == 'trace_fsync':records[0]['source_head_trace_fsynced'] = False
    elif mutation.startswith('trace_'):
        record = records[0]
        path = Path(record['source_head_trace_ref']['path'])
        value = json.loads(path.read_bytes())
        if mutation == 'trace_file':path.write_text('{}')
        else:
            if mutation == 'trace_labels':value['reference_prefix_access'] = True
            elif mutation == 'trace_extra_forward':value['source_head_extra_evaluations'] = 1
            elif mutation == 'trace_logits_mask':value['syntax_mask'] = True
            elif mutation == 'trace_pred':value['predictions'][0]['token_ids'] = [4]
            elif mutation == 'trace_missing':value['sample_count'] = 59
            else:value['source_rows_sha256'] = 'wrong'
            value['trace_sha256'] = digest({k:v for k,v in value.items() if k != 'trace_sha256'})
            path.write_text(json.dumps(value))
            record['source_head_trace_ref']['sha256'] = subject.sha(path)
    else:
        record = records[0]
        path = Path(record['predictions_ref']['path'])
        value = json.loads(path.read_bytes())
        if mutation == 'file':path.write_text('{}')
        else:
            key = {'source':'source_rows_sha256','contexts':'source_contexts_sha256',
                'labels':'generation_reference_access','temperature':'generation_temperature',
                'repeat':'greedy_passes_per_row','partial':'complete'}.get(mutation)
            if mutation == 'ids':value['predictions'].pop()
            else:value[key] = {'labels':True,'temperature':1,'repeat':2,'partial':False}.get(mutation,'wrong')
            path.write_text(json.dumps(value))
            record['predictions_ref']['sha256'] = subject.sha(path)
    monkeypatch.setattr(subject,'bound',lambda *args:pytest.fail('reference opened before full durable barrier'))
    with pytest.raises(ValueError):subject.load_references(manifest,records,runs,lanes,codec,digest)


@pytest.mark.parametrize('mutation',['target','source','train','semantic','seal','disjoint'])
def test_changed_reference_provenance_is_refused(tmp_path,mutation):
    manifest,records,runs,lanes,codec,_ = fixture(tmp_path)
    path = Path(manifest['references' if mutation in ('target','source') else 'development_receipt'])
    value = json.loads(path.read_bytes())
    if mutation == 'target':value[0]['target_ids_sha256'] = 'wrong'
    elif mutation == 'source':value[0]['source_text'] = 'wrong'
    else:
        key = {'train':'training_allowed','semantic':'source_semantics_verified','seal':'sealed_recipe_sha256',
            'disjoint':'actor_action_group_overlap'}[mutation]
        value[key] = {'train':True,'semantic':True,'seal':'b'*64,'disjoint':1}[mutation]
        value['receipt_sha256'] = digest({k:v for k,v in value.items() if k != 'receipt_sha256'})
    path.write_text(json.dumps(value))
    manifest['inputs'][str(path)] = subject.sha(path)
    with pytest.raises(ValueError):subject.load_references(manifest,records,runs,lanes,codec,digest)


def test_durable_save_uses_file_and_parent_fsync(tmp_path,monkeypatch):
    observed = []
    monkeypatch.setattr(subject.os,'fsync',lambda fd:observed.append(fd))
    path = tmp_path/'prediction.json'
    def save(path,value):
        path.write_text(json.dumps(value))
        return dict(path=str(path),sha256=subject.sha(path))
    ref = subject.durable_save(save,path,{'complete':True})
    assert len(observed) == 2 and ref['sha256'] == subject.sha(path)


def test_grouping_cannot_claim_seen_status_without_checked_receipt():
    with pytest.raises(ValueError):subject.scoring_references([],
        dict(actor_action_group_overlap=1,actor_action_disjointness_checked=True))


def join_fixture():
    refs = [dict(id='row:'+str(i),source_sha256='a'*64,target={'rules':[]}) for i in range(60)]
    events,unvisited,formula = [],[],[]
    for index,ref in enumerate(refs):
        facets = {}
        for field in ('actor','action','modality','object'):
            facets[field] = {'correct':int(index != 0)}
            if index == 1 and field == 'modality':
                unvisited.append(dict(id=ref['id'],slot=0,field=field))
            else:
                event = dict(id=ref['id'],slot=0,field=field,target_token_id=3,actual_next_token_id=3,
                    position=4,source={'argmax_token_id':3 if index != 2 else 4},
                    recurrent={'argmax_token_id':3},combined={'argmax_token_id':3})
                events.append(event)
        formula.append(dict(id=ref['id'],by_facet=facets,generated_ir={'rules':[]},
            counts=dict(ordered_exact=int(index != 0),syntax_valid=1)))
    return dict(complete=True,events=events,unvisited_reference_sites=unvisited),dict(rows=formula),refs


def test_full60_paired_modality_counts_preserve_unvisited_and_join_formulas():
    scalar,fidelity,refs = join_fixture()
    value = subject.join_source_heads_and_formula(scalar,fidelity,refs)
    modality = value['per_field']['modality']
    assert modality == dict(reference_rows=60,visited=59,unvisited=1,source_correct=58,source_incorrect=1,
        source_correct_formula_wrong=1,source_wrong_formula_correct=1)
    assert value['rows'][1]['fields']['modality']['source_correct'] is None
    assert value['rows'][1]['source_head_rule_complete'] is False
    assert value['rows'][1]['source_head_all_four_fields_correct'] is None
    assert value['rows'][1]['fields']['modality']['status'] == 'unvisited'
    assert value['rows'][0]['formula_ordered_exact'] is False
    assert value['unvisited_counted_correct'] is False


@pytest.mark.parametrize('mutation',['duplicate','foreign','missing_unvisited','reference_order','partial'])
def test_paired_join_refuses_ambiguous_or_missing_evidence(mutation):
    scalar,fidelity,refs = join_fixture()
    if mutation == 'duplicate':scalar['events'].append(deepcopy(scalar['events'][0]))
    elif mutation == 'foreign':scalar['events'][0]['id'] = 'foreign'
    elif mutation == 'missing_unvisited':scalar['unvisited_reference_sites'].clear()
    elif mutation == 'reference_order':refs.reverse()
    else:fidelity['rows'].pop()
    with pytest.raises(ValueError):subject.join_source_heads_and_formula(scalar,fidelity,refs)


def test_prediction_envelope_reuses_trace_without_a_second_forward():
    trace = dict(complete=True,predictions=[{'id':'row'}],model_tensor_sha256='tensor',
        source_rows_sha256='sources',source_contexts_sha256='contexts',elapsed_seconds=.1,trace_sha256='trace')
    panel = subject.prediction_from_trace(trace)
    assert panel['predictions'] is trace['predictions']
    assert panel['same_pass_scalar_trace_sha256'] == 'trace' and panel['greedy_passes_per_row'] == 1
    assert panel['reconstructed_input_mse_measured'] is False
