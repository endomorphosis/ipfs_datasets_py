"""Conditional diagnostics retain abstentions and occurrence-specific coverage."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts.ops.legal_ir import analyze_legal_boundary_conditional_facets as analysis


@pytest.mark.parametrize('expected,predicted,decoded,category,wrong',[
    (['x'],['x'],True,'true_positive',False),(['x'],['y'],True,'true_positive',True),
    (['x'],[],True,'false_negative',False),([],['x'],True,'false_positive',False),
    ([],[],True,'true_negative',False),(['x'],None,False,'abstained_positive',False),
    ([],None,False,'abstained_negative',False)])
def test_presence_wrong_value_and_abstentions_are_distinct(expected,predicted,decoded,category,wrong):
    result=analysis.presence_outcome(expected,predicted,decoded)
    assert result['category']==category and result['present_wrong_value'] is wrong
    assert result['value_exact'] is (decoded and expected==predicted)


def fixture():
    boundary=analysis.runner.boundary
    clause='Agency must retain records.'
    text=clause+' '+clause
    source={'candidate_id':'repeat','source_text':text,'source_sha256':boundary.text_sha(text)}
    tokens=boundary.tokenize(text);ends=[i for i,t in enumerate(tokens) if t['text']=='.']
    plan=boundary.source_plan(source,tokens,ends)
    segmentation={'candidate_id':'repeat','source_sha256':source['source_sha256'],'status':'segmented','reason':None,
        'plan':plan,'boundary_token_indices':ends,'predicted_rule_count':2,'raw_learned_scope_supported':True}
    rule={'modality':'O','actor':'Agency','action':'retain','object':'records','conditions':['approved'],
        'exceptions':[],'temporal':[]}
    gold={**source,'supported':True,'construction':'repeated','clauses':[
        {'char_start':c['char_start'],'char_end':c['char_end'],'rule':deepcopy(rule)} for c in plan['clauses']]}
    preds=[{'source_sha256':c['source_sha256'],'target_access':False,'teacher_forcing':False,
        'status':'decoded','canonical_ir':{'rules':[deepcopy(rule)]},'reason':None} for c in plan['clauses']]
    output={'candidate_id':'repeat','source_sha256':source['source_sha256'],'segmentation_status':'segmented','composition':None,
        'clause_generation':{'rows':preds,'target_access':False,'teacher_forcing':False}}
    return [source],{'rows':[segmentation]},{'rows':[output]},[gold]


def test_exact_segmentation_keeps_clause_abstentions_when_document_composition_failed():
    sources,bounds,outputs,targets=fixture()
    outputs['rows'][0]['clause_generation']['rows'][0].update(status='abstained',canonical_ir=None,reason='copied_spans_overlap')
    records=analysis.document_records(sources,bounds,outputs,targets)
    score=analysis.summarize(records)
    assert score['all_supported_documents']==score['exact_accepted_segmentation_documents']==1
    assert score['conditional_clause_occurrences']==2 and score['conditional_abstained_clauses']==1
    assert score['conditional_canonical_rule_exact']==score['conditional_all_seven_facets_exact']==1
    assert score['presence']['conditions']['abstained_positive']==1
    assert score['presence']['exceptions']['abstained_negative']==1
    assert records[0]['clauses'][0]['source_sha256']==records[0]['clauses'][1]['source_sha256']
    assert records[0]['clauses'][0]['char_start']!=records[0]['clauses'][1]['char_start']
    assert score['exact_segmentation_documents_with_abstained_clauses']==1


def test_wrong_segmentation_stays_in_coverage_but_never_gets_conditional_credit():
    sources,bounds,outputs,targets=fixture()
    boundary=analysis.runner.boundary
    segmentation=bounds['rows'][0];tokens=boundary.tokenize(sources[0]['source_text']);ends=[len(tokens)-1]
    segmentation.update(plan=boundary.source_plan(sources[0],tokens,ends),boundary_token_indices=ends,predicted_rule_count=1)
    records=analysis.document_records(sources,bounds,outputs,targets)
    score=analysis.summarize(records)
    assert score['all_supported_documents']==score['supported_boundary_failure_documents']==1
    assert score['reference_clause_occurrences_all_supported']==2 and score['conditional_clause_occurrences']==0
    assert score['conditional_canonical_rule_exact']==0


@pytest.mark.parametrize('mutation',['source_hash','missing_clause','status','source_plan','target_access'])
def test_conditional_diagnostic_rejects_source_or_report_corruption(mutation):
    sources,bounds,outputs,targets=fixture()
    report=outputs['rows'][0]['clause_generation']
    if mutation=='source_hash':report['rows'][0]['source_sha256']='wrong'
    elif mutation=='missing_clause':report['rows'].pop()
    elif mutation=='status':report['rows'][0]['status']='abstained'
    elif mutation=='source_plan':bounds['rows'][0]['plan']['clauses'][0]['source_text']='wrong'
    else:report['target_access']=True
    with pytest.raises(ValueError):analysis.document_records(sources,bounds,outputs,targets)


def test_missing_qualification_summary_blocks_before_loading_labels(tmp_path,monkeypatch):
    monkeypatch.setattr(analysis.runner,'load_config',lambda *_:pytest.fail('fitting loader called before qualification'))
    with pytest.raises(ValueError,match='qualification summary'):
        analysis.analyze(SimpleNamespace(qualification=str(tmp_path/'missing.json'),output=str(tmp_path/'output.json')))
