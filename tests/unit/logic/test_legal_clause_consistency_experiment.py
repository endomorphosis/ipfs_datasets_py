"""Dual-boundary retention, matched pairs, and complete source-only inventories."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from scripts.ops.legal_ir import run_legal_clause_consistency_experiment as runner


def metrics(steps=None):
    value={'tuning_earlier_exact':96,'tuning_temporal_exact':120,'tuning_new_exact':60,
        'tuning_document_parent_exact':60,'tuning_document_expanded_exact':60,
        'tuning_document_parent_unsupported_accepted':0,'tuning_document_expanded_unsupported_accepted':0}
    if steps is not None:value['steps']=steps
    return value


@pytest.mark.parametrize('field',['tuning_earlier_exact','tuning_temporal_exact','tuning_document_parent_exact','tuning_document_expanded_exact'])
def test_every_retention_gate_has_exact_one_error_tolerance(field):
    parent=metrics();stage=metrics(400);stage[field]-=1
    assert runner.eligible(stage,parent)
    stage[field]-=1
    assert not runner.eligible(stage,parent)


@pytest.mark.parametrize('policy',['parent','expanded'])
def test_either_boundary_guard_acceptance_disqualifies_stage(policy):
    stage=metrics(400);stage['tuning_document_'+policy+'_unsupported_accepted']=1
    assert not runner.eligible(stage,metrics())


def test_rank_new_temporal_expanded_parent_earlier_then_earliest():
    parent=metrics();left,right=metrics(400),metrics(800)
    ordered=['tuning_new_exact','tuning_temporal_exact','tuning_document_expanded_exact','tuning_document_parent_exact','tuning_earlier_exact']
    for key in ordered:
        # Equal otherwise; lowering one metric on the earlier stage picks the later.
        left[key]-=1
        assert runner.select_stage([left,right],parent)==right
        left[key]+=1
    assert runner.select_stage([right,left],parent)==left


def test_all_failed_candidates_explicitly_return_none():
    a,b=metrics(400),metrics(800)
    a['tuning_document_expanded_exact']=0;b['tuning_earlier_exact']=0
    assert runner.select_stage([a,b],metrics()) is None


@pytest.mark.parametrize('mutation',['missing','duplicate','bool_count','overflow','negative','bool_step'])
def test_invalid_selection_inventory_rejected(mutation):
    stages=[metrics(400),metrics(800)]
    if mutation=='missing':stages.pop()
    elif mutation=='duplicate':stages[1]['steps']=400
    elif mutation=='bool_count':stages[0]['tuning_new_exact']=True
    elif mutation=='overflow':stages[0]['tuning_document_parent_exact']=73
    elif mutation=='negative':stages[0]['tuning_document_expanded_unsupported_accepted']=-1
    else:stages[0]['steps']=True
    with pytest.raises(ValueError):runner.select_stage(stages,metrics())


def pair_fixture():
    rule={'rules':[{'actor':'Agency','conditions':[]}]}
    rows=[{'id':str(i),'source_text':'surface '+str(i),'canonical_ir':deepcopy(rule),'domain':'new'} for i in range(4)]
    pairs=[{'pair_id':str(i),'case_group':'case'+str(i),'left_id':str(2*i),'right_id':str(2*i+1),
        'canonical_ir_sha256':runner.digest(rule)} for i in range(2)]
    return rows,pairs


def test_pairs_require_identical_complete_canonical_meaning_and_unique_coverage():
    runner.validate_pairs(*pair_fixture(),2)


@pytest.mark.parametrize('mutation',['duplicate_id','same_member','semantic_change','wrong_hash','same_surface','wrong_domain','missing_pair'])
def test_bad_pairs_fail_before_any_fit(mutation):
    rows,pairs=pair_fixture()
    if mutation=='duplicate_id':pairs[1]['pair_id']=pairs[0]['pair_id']
    elif mutation=='same_member':pairs[0]['right_id']=pairs[0]['left_id']
    elif mutation=='semantic_change':rows[1]['canonical_ir']['rules'][0]['conditions']=['approved']
    elif mutation=='wrong_hash':pairs[0]['canonical_ir_sha256']='wrong'
    elif mutation=='same_surface':rows[1]['source_text']=rows[0]['source_text']
    elif mutation=='wrong_domain':rows[1]['domain']='earlier'
    else:pairs.pop()
    with pytest.raises(ValueError):runner.validate_pairs(rows,pairs,2)


def model_fixture():
    parents={(a,s):{'checkpoint':{'path':f'{a}-{s}','sha256':str(s)}} for a in runner.ARCHITECTURES for s in runner.SEEDS}
    trials=[]
    for o in runner.OBJECTIVES:
        for a in runner.ARCHITECTURES:
            for s in runner.SEEDS:
                parent=parents[(a,s)]['checkpoint']
                trials.append({'name':f'{o}_{a}-{s}','arm':f'{o}_{a}','objective':o,'architecture':a,'seed':s,
                    'enabled':a=='grounding','decoder_kind':'mixed','parent':parent,'checkpoint':parent,
                    'selection':'parent_fallback_no_acceptable_replacement','selected_steps':0,'executed_steps':800})
    return trials,parents


def test_fallback_inventory_keeps_all18models_and36paired_boundaries():
    models,pipelines=runner.model_inventory(*model_fixture())
    assert len(models)==len({m['name'] for m in models})==18
    assert len(pipelines)==len({m['name'] for m in pipelines})==36
    assert all(m['enabled'] is (m['architecture']=='grounding') and m['decoder_kind']=='mixed' for m in models)
    for pipeline in pipelines:
        assert pipeline['boundary_head']==('parent' if pipeline['boundary_policy']=='parent' else f"expanded-{pipeline['seed']}")


@pytest.mark.parametrize('mutation',['missing','architecture_flip','wrong_parent','wrong_fallback','wrong_kind'])
def test_model_inventory_rejects_substitution_or_dropped_failed_slots(mutation):
    trials,parents=model_fixture()
    if mutation=='missing':trials.pop()
    elif mutation=='architecture_flip':trials[0]['enabled']=True
    elif mutation=='wrong_parent':trials[0]['parent']={'path':'other'}
    elif mutation=='wrong_fallback':trials[0]['checkpoint']={'path':'other'}
    else:trials[0]['decoder_kind']='consistency'
    with pytest.raises(ValueError):runner.model_inventory(trials,parents)


def test_document_initial_signature_ignores_only_report_provenance_not_logits():
    value={'rows':[{'candidate_id':'x','composition':{'a':1},'clause_generation':{'checkpoint_sha256':'old','rows':[{'logits':[1.,2.]}]}}]}
    changed=deepcopy(value);changed['rows'][0]['clause_generation']['checkpoint_sha256']='new'
    assert runner.document_signature(value)==runner.document_signature(changed)
    changed['rows'][0]['clause_generation']['rows'][0]['logits'][0]=2.
    assert runner.document_signature(value)!=runner.document_signature(changed)


def test_matched_objective_sampler_audit_checks_full_order(monkeypatch):
    trials,_=model_fixture()
    for t in trials:
        t['initial_model_state_sha256']='initial'
        t['stages']=[{'steps':step,'training_report':{'batch_exposures':list(range(step-400,step))}} for step in (400,800)]
    monkeypatch.setattr(runner,'read_ref',lambda x:x)
    assert len(runner.audit_matched_objectives(trials))==6
    trials[-1]['stages'][-1]['training_report']['batch_exposures'][0]=999
    with pytest.raises(ValueError,match='exposure/order'):runner.audit_matched_objectives(trials)


@pytest.fixture
def loader_inputs(tmp_path,monkeypatch):
    from scripts.ops import legal_ir as package
    corpus=SimpleNamespace(load_training_inputs=None)
    monkeypatch.setattr(package,'prepare_legal_clause_consistency_corpus',corpus,raising=False)
    def put(name,value):
        path=tmp_path/name;path.write_text(json.dumps(value));return runner.ref(path)
    def sealed(name):return {'path':str(tmp_path/name),'sha256':'a'*64,'bytes':10}
    def rows(prefix,count,domain='new'):
        return [{'id':f'{prefix}-{i}','source_text':f'{prefix} surface {i}','domain':domain} for i in range(count)]
    def paired(prefix,count):
        data=rows(prefix,count);pairs=[]
        for i in range(0,count,2):
            canonical={'rules':[{'actor':f'{prefix}{i}','conditions':[]}]}
            for row in data[i:i+2]:row['canonical_ir']=deepcopy(canonical)
            pairs.append({'pair_id':f'{prefix}-pair{i}','case_group':f'{prefix}-case{i}',
                'left_id':data[i]['id'],'right_id':data[i+1]['id'],'canonical_ir_sha256':runner.digest(canonical)})
        return data,pairs
    def docs(prefix):
        result=[]
        for i in range(96):
            text=f'{prefix}{i} Authority must retain records.'
            result.append({'candidate_id':f'{prefix}-{i}','source_text':text,'source_sha256':runner.boundary.text_sha(text)})
        return result
    newtrain,trainpairs=paired('newtrain',384);newtune,tunepairs=paired('newtune',96)
    manifest={'artifacts':{'challenge_targets':sealed('fresh-targets.json'),'document_challenge_targets':sealed('freshdoc-targets.json')}}
    loaded={'manifest':manifest,'new_train':newtrain,'training_pairs':trainpairs,'new_tuning':newtune,'tuning_pairs':tunepairs,
        'replay':{'earlier':rows('earliertrain',1152,'earlier'),'prior_new':rows('priortrain',600),'temporal':rows('temporaltrain',600)},
        'tuning':{'earlier':rows('earliertune',96,'earlier'),'prior_new':rows('priortune',96),'temporal':rows('temporaltune',120)},
        'fresh_sources':runner.source_rows(rows('fresh',144)),'fresh_document_sources':docs('freshdoc')}
    corpus.load_training_inputs=lambda _:loaded
    docsources={'document_tuning':docs('doctune'),'prior_boundary_documents':docs('priorboundary'),'exposed_documents':docs('exposed')}
    doctargets=[{**r,'supported':i%4!=3,'repeated_rule_occurrences':False,'construction':'fixture',
        'clauses':[{'char_start':0,'char_end':len(r['source_text']),'rule':{}}] if i%4!=3 else []}
        for i,r in enumerate(docsources['document_tuning'])]
    prior={'plan':put('prior-plan.json',{'producer_pins':{},'config':put('oldconfig.json',{})}),
        'boundary_heads':put('boundaryheads.json',[]),'sources':put('oldsources.json',{
            'tuning_new':docsources['document_tuning'],'fresh_documents':docsources['prior_boundary_documents'],
            'exposed_documents':docsources['exposed_documents']})}
    _,parents=model_fixture()
    monkeypatch.setattr(runner.boundary_run,'load_config',lambda _: {})
    monkeypatch.setattr(runner,'prior_inventory',lambda *_:(parents,{}))
    config={'schema':runner.CONFIG_SCHEMA,'corpus_manifest':put('manifest.json',manifest),
        'prior_boundary_generation':put('prior.json',prior),'study_design':put('design.json',{}),'producer_files':[]}
    for name,count in [('prior_construction',180),('earlier_regression',192),('temporal_regression',180)]:
        source=runner.source_rows(rows(name,count));payload={'challenge':source} if name=='earlier_regression' else source
        config[name+'_sources']=put(name+'-sources.json',payload);config[name+'_targets']=sealed(name+'-targets.json')
    for name,panel in [('document_tuning','document_tuning'),('prior_boundary_document','prior_boundary_documents'),('exposed_document','exposed_documents')]:
        config[name+'_sources']=put(name+'-sources.json',docsources[panel])
        config[name+'_targets']=put('doctuning-targets.json',doctargets) if name=='document_tuning' else sealed(name+'-targets.json')
    path=tmp_path/'config.json';path.write_text(json.dumps(config));return path,loaded


def test_loader_succeeds_with_all_fresh_and_regression_targets_absent(loader_inputs):
    path,_=loader_inputs
    value=runner.load_config(path)
    assert len(value['training'])==2736 and len(value['runtime_pairs'])==192
    assert {key:len(rows) for key,rows in value['sources'].items()}==runner.SINGLE_COUNTS
    assert {key:len(rows) for key,rows in value['document_sources'].items()}==runner.DOCUMENT_COUNTS


def test_loader_rejects_leaked_fresh_single_labels(loader_inputs):
    path,loaded=loader_inputs;loaded['fresh_sources'][0]['canonical_ir']={}
    with pytest.raises(ValueError,match='contains labels'):runner.load_config(path)


def test_loader_rejects_training_and_fresh_source_overlap(loader_inputs):
    path,loaded=loader_inputs;loaded['fresh_sources'][0]=runner.source_rows(loaded['new_train'][:1])[0]
    with pytest.raises(ValueError,match='overlap'):runner.load_config(path)
