"""Cluster resampling and post-qualification access contracts, using fake data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from scripts.ops.legal_ir import analyze_legal_clause_consistency as a


def rows(*,cases=36,variants=4,correct=True):
    return [{'id':f'case-{c}-variant-{v}','seed':s,'case_group':f'case-{c}','family':f'family-{v}',
             'exact':correct(c,v,s) if callable(correct) else correct}
            for s in a.SEEDS for c in range(cases) for v in range(variants)]


def fixture_membership():
    sources=[];single=[];docs=[];document=[]
    for case in range(36):
        for variant in range(4):
            identity=f's-{case}-{variant}';text='synthetic source '+identity;digest=hashlib.sha256(text.encode()).hexdigest()
            sources.append({'id':identity,'source_text':text,'source_sha256':digest})
            single.append({'id':identity,'panel':'fresh','source_sha256':digest,'case_group':f'case-{case}','family':f'family-{variant}'})
    for case in range(96):
        identity=f'd-{case}';text='synthetic document '+identity;digest=hashlib.sha256(text.encode()).hexdigest()
        docs.append({'candidate_id':identity,'source_text':text,'source_sha256':digest})
        document.append({'candidate_id':identity,'panel':'document','source_sha256':digest,'case_group':f'doc-case-{case}',
                         'family':f'family-{case%4}','supported':case<72})
    ledger={'schema':'legal-clause-consistency-annotations/v1','single_rows':single,'document_rows':document}
    return ledger,sources,docs,[f'family-{i}' for i in range(4)]


def fake_inventory():
    models=[];pipelines=[];details={'single':{},'document':{}}
    for objective in a.POLICIES:
        for architecture in a.ARCHITECTURES:
            for seed in a.SEEDS:
                name=f'{objective}_{architecture}-{seed}'
                m={'name':name,'objective':objective,'architecture':architecture,'seed':seed,'checkpoint':{'hash':name},'selected_steps':0,'selection':'test'}
                models.append(m);details['single'][name]={}
                for boundary in a.BOUNDARIES:
                    p={**m,'name':name+'__'+boundary,'source_model_name':name,'boundary_policy':boundary,
                       'boundary_checkpoint':{'hash':boundary+str(seed)}}
                    pipelines.append(p);details['document'][p['name']]={}
    frozen={'models':models,'pipelines':pipelines}
    return frozen,{'models':models,'pipelines':pipelines},details


def test_identical_predictions_have_zero_delta_interval():
    r=rows();x=a.compare(r,r,expected_cases=36,slots_per_case=12)
    assert x['count']==432 and x['case_groups']==36 and x['slots_per_case_group']==12
    assert x['left_exact']==x['right_exact']==x['ties']==432
    assert x['case_group_bootstrap_95_percentile']==[0.,0.]
    assert x['bootstrap_replicates']==2000 and x['bootstrap_seed']==6831
    assert not x['bootstrap_resamples_seeds']


def test_all_wins_and_seed_specific_reference_denominators():
    x=a.compare(rows(),rows(correct=False),expected_cases=36,slots_per_case=12)
    assert x['left_only_correct']==x['delta_correct']==432 and x['right_only_correct']==0
    assert x['exact_rate_difference']==1 and x['case_group_bootstrap_95_percentile']==[1.,1.]
    assert all(v['count']==v['left_exact']==v['delta_correct']==144 for v in x['seed_specific'].values())


def test_document_clusters_keep_all_fixed_seeds_together():
    r=rows(cases=72,variants=1)
    x=a.compare(r,rows(cases=72,variants=1,correct=False),expected_cases=72,slots_per_case=3)
    assert x['count']==216 and x['case_groups']==72 and x['slots_per_case_group']==3
    assert all(v['count']==72 for v in x['seed_specific'].values())


def test_mixed_wins_losses_and_ties_reconcile():
    left=rows(correct=lambda c,v,s:c%3==0);right=rows(correct=lambda c,v,s:c%3==1)
    x=a.compare(left,right,expected_cases=36,slots_per_case=12)
    assert x['left_only_correct']==x['right_only_correct']==144
    assert x['both_wrong']==144 and x['ties']==144 and x['delta_correct']==0
    assert x['case_group_bootstrap_95_percentile'][0]<0<x['case_group_bootstrap_95_percentile'][1]


def test_case_cluster_interval_and_counts_are_deterministic():
    left=rows(correct=lambda c,v,s:c%4==0 or v==2);right=rows(correct=lambda c,v,s:c%5==0)
    assert a.compare(left,right,expected_cases=36,slots_per_case=12)==a.compare(left,right,expected_cases=36,slots_per_case=12)

@pytest.mark.parametrize('mutation',['duplicate','group','seed','boolean','missing'])
def test_invalid_paired_slots_refused(mutation):
    left=rows();right=rows()
    if mutation=='duplicate':left[-1]=deepcopy(left[0])
    elif mutation=='group':left[0]['case_group']='different'
    elif mutation=='seed':left=[r for r in left if r['seed']!=1731]
    elif mutation=='boolean':left[0]['exact']=1
    else:left.pop();right.pop()
    with pytest.raises(ValueError):a.compare(left,right,expected_cases=36,slots_per_case=12)


def test_all_four_fidelity_counts_case_seed_slots():
    r=rows(correct=lambda c,v,s:v<c%5)
    t=a.totals(r,single=True)
    assert t['four_variant_case_seed_slots']==108 and t['independent_authored_case_groups']==36
    assert sum(t['number_of_exact_variants_histogram'].values())==108
    assert t['all_four_variants_exact']==21


def test_membership_uses_complete_disjoint_case_groups():
    ledger,s,d,f=fixture_membership();sm,dm=a.memberships(ledger,s,d,f)
    assert len(sm)==144 and len(dm)==96

@pytest.mark.parametrize('mutation',['source_hash','duplicate_family','shared_case','support'])
def test_membership_corruption_refused(mutation):
    ledger,s,d,f=fixture_membership()
    if mutation=='source_hash':ledger['single_rows'][0]['source_sha256']='0'*64
    elif mutation=='duplicate_family':ledger['single_rows'][1]['family']=ledger['single_rows'][0]['family']
    elif mutation=='shared_case':ledger['document_rows'][0]['case_group']='case-0'
    else:ledger['document_rows'][0]['supported']=False
    with pytest.raises(ValueError):a.memberships(ledger,s,d,f)


def test_document_reference_comparison_includes_supported_abstentions():
    ledger,s,d,f=fixture_membership();_,membership=a.memberships(ledger,s,d,f)
    scored=[{'id':i,'joint_exact':False,'supported':v['supported']} for i,v in membership.items()]
    result=a.reference_rows(scored,membership,1729,document=True)
    assert len(result)==72 and sum(r['exact'] for r in result)==0


def test_document_reference_support_must_match_ledger():
    ledger,s,d,f=fixture_membership();_,membership=a.memberships(ledger,s,d,f)
    scored=[{'id':i,'joint_exact':False,'supported':v['supported']} for i,v in membership.items()];scored[0]['supported']=False
    with pytest.raises(ValueError,match='support differs'):a.reference_rows(scored,membership,1729,document=True)


def test_fixed_boundary_and_model_inventory_are_checked():
    frozen,summary,details=fake_inventory();models,pipelines=a.verify_inventory(frozen,summary,details)
    assert len(models)==18 and len(pipelines)==36
    frozen['pipelines'][0]['boundary_checkpoint']={'hash':'changed'}
    with pytest.raises(ValueError,match='identical boundary'):a.verify_inventory(frozen,summary,details)


def test_no_qualification_means_no_artifact_reads(tmp_path,monkeypatch):
    def forbidden(*args):raise AssertionError('artifact read before qualification gate')
    monkeypatch.setattr(a,'read_ref',forbidden)
    with pytest.raises(ValueError,match='completed qualification'):a.qualified_inputs(tmp_path,tmp_path)


def test_failed_postbuild_gate_precedes_any_label_read(tmp_path,monkeypatch):
    (tmp_path/'summary.json').write_text(json.dumps({'schema':'legal-clause-consistency-independent-qualification/v1',
        'fresh_target_and_regression_references_opened_after_replay_and_build_freezes':False}))
    (tmp_path/'builds-frozen.json').write_text('{}');old=a.read_ref;opened=[]
    def tracked(reference):opened.append(Path(reference['path']).name);return old(reference)
    monkeypatch.setattr(a,'read_ref',tracked)
    with pytest.raises(ValueError,match='post-build'):a.qualified_inputs(tmp_path,tmp_path)
    assert opened==['summary.json']


def test_analysis_never_overwrites_existing_report(tmp_path):
    p=tmp_path/'report.json';p.write_text('preserve')
    with pytest.raises(ValueError,match='already exists'):a.analyze(tmp_path,tmp_path,p)
    assert p.read_text()=='preserve'


def test_complete_analysis_uses_qualifier_fidelity_counts(tmp_path,monkeypatch):
    frozen,summary,details=fake_inventory();ledger,s,d,f=fixture_membership()
    sm,dm=a.memberships(ledger,s,d,f)
    for model in frozen['models']:
        exact=model['objective']!='parent'
        details['single'][model['name']]['fresh']={'rows':[{'id':i,'exact':exact} for i in sm],
                                                 'count':144,'exact':144 if exact else 0}
    for p in frozen['pipelines']:
        exact=p['objective']!='parent'
        details['document'][p['name']]['fresh_documents']={
            'rows':[{'id':i,'joint_exact':exact and v['supported'],'supported':v['supported']} for i,v in dm.items()],
            'metrics':{'count':96,'supported':72,'unsupported':24,'exact':72 if exact else 0,'unsupported_accepted':0}}
    artifact=tmp_path/'pinned.json';artifact.write_text('{}');reference=a.ref(artifact)
    summary['details']=reference
    inputs={'summary':summary,'summary_ref':reference,'frozen':frozen,'frozen_ref':reference,'build_ref':reference,
        'manifest':{'fresh_families':f},'ledger':ledger,'ledger_ref':reference,'details':details,'sources':s,'document_sources':d}
    monkeypatch.setattr(a,'qualified_inputs',lambda *_:inputs)
    out=tmp_path/'analysis.json';r=a.analyze(tmp_path,tmp_path,out);value=a.read_ref(r)
    assert len(value['paired_case_group_comparisons'])==18
    assert len(value['models'])==18 and len(value['pipelines'])==36
    for comparison in value['paired_case_group_comparisons']:
        assert comparison['left_exact']==comparison['count']
        if comparison['right_policy']=='parent':assert comparison['exact_rate_difference']==1
        else:assert comparison['exact_rate_difference']==0
    assert not value['inference_executed'] and not value['outputs_or_selections_changed']
