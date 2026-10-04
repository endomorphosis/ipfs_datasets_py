"""Synthetic TRAIN-mixture provenance/sampling; no native encoder or proof."""
from collections import Counter
from copy import deepcopy
import json
import math
import random
import time

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import contextual_training_mixture as subject
from .test_authored_training_paraphrases import inputs as authored_inputs


def seal(payload):
    payload['payload_sha256'] = subject.digest({k:v for k,v in payload.items() if k != 'payload_sha256'})
    return payload


def fixture(monkeypatch, dimension=384):
    args = authored_inputs(); bank=args['training_bank']; codec=args['codec']
    texts={}
    def vector(text):
        if text not in texts:
            angle=(len(texts)+1)*.003
            texts[text]=[math.cos(angle),math.sin(angle)]+[0.]*(dimension-2)
        return list(texts[text])
    def split(name):
        rows,refs,cache=[],[],[]; cursor=0
        for count in (1,2,4,8):
            for ordinal in range(12):
                members=bank[cursor:cursor+count];cursor+=count
                pieces=[row['source_text'] if name=='train' else 'Evaluation wording '+str(cursor)+' '+row['source_text'] for row in members]
                text='\n\n'.join(pieces); identity=name+':'+str(len(rows))
                target={'rules':[json.loads(''.join(codec['target_vocabulary'][i] for i in row['target_ids'][1:-1]))['rules'][0] for row in members]}
                refs.append(dict(id=identity,source_text=text,target=target,clause_count=count))
                rows.append(dict(id=identity,source_text=text,input=vector(text),target_ids=subject.authored.base._encode(target,codec)))
                for text in pieces:
                    cache.append(dict(id=name+'-clause:'+str(len(cache)),source_text=text,input=vector(text)))
        contexts=subject.context.build_source_contexts(subject._source_rows(rows),cache)
        return rows,refs,contexts
    train,train_refs,train_ctx=split('train'); dev,dev_refs,dev_ctx=split('development')
    prior={name:[dict(id=name+':0',source_text=name+' distinct evaluation sentence.')] for name in subject.EVALUATION_DATASETS}
    prior.update(paragraph_train=subject._source_rows(train),paragraph_validation=subject._source_rows(dev),
        raw_train=subject._source_rows(bank),original_train_bank=subject._source_rows(bank))
    corpus=subject.authored.build(**dict(args,prior_sources_by_dataset=prior))
    plan=subject.producer.source_plan(corpus['source_rows'],expected_source_rows_sha256=corpus['receipt']['source_rows_sha256'],sealed_recipe_sha256='a'*64)
    observed=[dict(id=r['id'],source_sha256=subject.authored.base.text_sha(r['source_text']),vector=vector(r['source_text'])) for r in plan['shape_plan']['source_inputs']]
    production=dict(dimension=dimension,production_sha256='b'*64,vectors=observed)
    vectors={r['source_sha256']:r['vector'] for r in observed}
    new_rows=[dict(r,input=vectors[subject.authored.base.text_sha(r['source_text'])]) for r in corpus['source_rows']]
    cache=[]
    for row in corpus['source_rows']:
        for text in row['source_text'].split('\n\n'):
            key=subject.authored.base.text_sha(text);cache.append(dict(id='clause:'+key,source_text=text,input=vectors[key]))
    ctx=subject.context.build_source_contexts(corpus['source_rows'],cache)
    prepared=dict(schema='training-paraphrase-source-inputs/v1',complete=True,role='train_augmentation',dimension=dimension,
        rows=new_rows,clause_cache=cache,source_contexts=ctx,production_sha256='b'*64,source_plan_sha256=plan['plan_sha256'],
        targets_attached=False,preprocessing_fitted=False,qualified=False,admitted=False,checkpoint_promoted=False)
    prepared['inputs_sha256']=subject.digest(prepared)
    # Native producer behavior is tested by its own suite. These are explicitly
    # synthetic vectors; this test verifies the consumer invokes its validator.
    calls=[]
    def validate(p,r):
        assert p==plan and r==production
        calls.append(1);return dimension
    monkeypatch.setattr(subject.producer,'validate_report',validate)
    mixture=seal(dict(policy='half_paraphrases',training_bank=bank,prior_sources_by_dataset=prior,corpus=corpus,
        source_plan=plan,source_inputs=prepared,production_report=production,
        evaluation_vectors_by_dataset={name:[] for name in subject.EVALUATION_DATASETS}))
    kwargs=dict(training_references=train_refs,validation_references=dev_refs,
        source_contexts={'train':train_ctx,'validation':dev_ctx},codec=codec,validate_rule=args['validate_rule'],mixture=mixture)
    return train,dev,kwargs,calls


def prepare(train,dev,kwargs):return subject.prepare(train,dev,**kwargs,deadline=time.monotonic()+30)


@pytest.mark.parametrize('dimension',[384,768])
def test_complete_train_only_union_preserves_caller_and_reports_missing_vectors(monkeypatch,dimension):
    train,dev,kw,calls=fixture(monkeypatch,dimension);before=deepcopy((train,dev,kw));rng=random.getstate()
    selector=prepare(train,dev,kw); receipt=selector.snapshot()
    assert calls==[1] and (train,dev,kw)==before and random.getstate()==rng
    assert len(selector.effective_rows)==len(selector.effective_references)==len(selector.effective_contexts)==96
    assert receipt['original_rows_sha256']==subject.digest(train) and not receipt['preprocessing_refitted']
    assert set(receipt['evaluation_coverage'])==set(subject.EVALUATION_DATASETS)
    assert all(not r['vector_coverage_complete'] and r['source_exclusion_complete'] for r in receipt['evaluation_coverage'].values())
    copied=selector.effective_rows;copied[0]['input'][0]=9
    assert selector.effective_rows[0]==train[0]


def test_native_production_validation_is_mandatory(monkeypatch):
    train,dev,kw,_=fixture(monkeypatch)
    monkeypatch.setattr(subject.producer,'validate_report',lambda *a:(_ for _ in ()).throw(ValueError('native report refused')))
    with pytest.raises(ValueError,match='native report refused'):prepare(train,dev,kw)


@pytest.mark.parametrize('mutation',['digest','bank_label','derived_label','reference_text','missing_evaluation','missing_vectors',
    'paragraph_vector','clause_vector','context','authority','native_binding','foreign_vector_text','evaluation_vector_overlap','evaluation_source_overlap'])
def test_provenance_and_evaluation_injection_refused_even_with_envelope_resealed(monkeypatch,mutation):
    train,dev,kw,_=fixture(monkeypatch);m=kw['mixture']
    if mutation=='digest':m['payload_sha256']='0'*64
    elif mutation=='bank_label':m['training_bank'][0]['target_ids']=deepcopy(m['training_bank'][6]['target_ids'])
    elif mutation=='derived_label':
        rule=m['corpus']['references'][0]['target']['rules'][0]
        rule['modality']='O' if rule['modality']!='O' else 'P'
    elif mutation=='reference_text':m['corpus']['references'][0]['source_text']='wrong'
    elif mutation=='missing_evaluation':m['prior_sources_by_dataset'].pop('raw_test')
    elif mutation=='missing_vectors':m['evaluation_vectors_by_dataset'].pop('raw_canary')
    elif mutation=='paragraph_vector':m['source_inputs']['rows'][0]['input']=list(dev[0]['input'])
    elif mutation=='clause_vector':m['source_inputs']['clause_cache'][0]['input']=list(dev[0]['input'])
    elif mutation=='context':m['source_inputs']['source_contexts'].clear()
    elif mutation=='authority':m['source_inputs']['qualified']=True
    elif mutation=='native_binding':m['source_inputs']['production_sha256']='c'*64
    elif mutation in ('foreign_vector_text','evaluation_vector_overlap'):
        m['evaluation_vectors_by_dataset']['raw_test']=[dict(id='probe',source_text='foreign' if mutation=='foreign_vector_text' else m['prior_sources_by_dataset']['raw_test'][0]['source_text'],input=list(train[0]['input']))]
    else:m['prior_sources_by_dataset']['raw_test'].append(subject._source_rows(train)[0])
    if mutation in ('paragraph_vector','clause_vector','context','authority','native_binding'):
        item=m['source_inputs'];item['inputs_sha256']=subject.digest({k:v for k,v in item.items() if k!='inputs_sha256'})
    if mutation!='digest':seal(m)
    with pytest.raises((ValueError,AssertionError)):prepare(train,dev,kw)


def test_per_parent_alternation_and_exact_full_work_budget(monkeypatch):
    train,dev,kw,_=fixture(monkeypatch);s=prepare(train,dev,kw);before=random.getstate();commits=[]
    # Historical stage sizes12/26/36/48, ten epochs each. Pure schedule only.
    for size in (12,26,36,48):
        for epoch in range(10):
            current=list(train[:size]);random.Random(1729+epoch+size).shuffle(current)
            for offset in range(0,size,8):
                part=s.select(current[offset:offset+8],deadline=time.monotonic()+30)
                r=s.record_commit(len(commits));commits.append(r)
                assert len({row['id'] for row in part})==len(part)
                assert all(row['target_ids'] for row in part)
    end=s.snapshot()
    assert random.getstate()==before and end['committed_updates']==170
    assert end['committed_rows']==1220 and end['committed_replacements']==610
    assert sum(r['target_token_presentations'] for r in commits)==112920
    assert sum(r['source_value_presentations'] for r in commits)==12800
    assert sum(end['committed_template_presentations'].values())==1220
    assert sum(end['committed_modality_clause_presentations'].values())==3200
    assert all(n%2==0 for n in end['parent_occurrences'].values())


def test_identity_original_policy_and_aborted_draw_accounting(monkeypatch):
    train,dev,kw,_=fixture(monkeypatch);kw['mixture']['policy']='original_only';seal(kw['mixture']);s=prepare(train,dev,kw)
    for step in range(2):
        assert s.select(train[:8],deadline=time.monotonic()+30)==train[:8]
        s.record_commit(step)
    s.select(train[:8],deadline=time.monotonic()+30)
    end=s.snapshot();assert end['draw_rows']==24 and end['committed_rows']==16 and end['committed_replacements']==0
    assert end['uncommitted_draw'] is not None
    with pytest.raises(ValueError,match='uncommitted'):s.select(train[:8],deadline=time.monotonic()+30)


def test_expiry_and_invalid_requests_do_not_advance_sampler(monkeypatch):
    train,dev,kw,_=fixture(monkeypatch);s=prepare(train,dev,kw);before=s.snapshot()
    with pytest.raises(TimeoutError):s.select(train[:8],deadline=time.monotonic()-1)
    with pytest.raises(ValueError):s.select([train[0],train[0]],deadline=time.monotonic()+30)
    with pytest.raises(ValueError):s.select(dev[:8],deadline=time.monotonic()+30)
    assert s.snapshot()==before
    with pytest.raises(TimeoutError):subject.prepare(train,dev,**kw,deadline=time.monotonic()-1)


def test_valid_observed_evaluation_vectors_have_honest_partial_coverage(monkeypatch):
    train,dev,kw,_=fixture(monkeypatch)
    kw['mixture']['evaluation_vectors_by_dataset']['paragraph_validation']=[{k:r[k] for k in ('id','source_text','input')} for r in dev]
    seal(kw['mixture']);report=prepare(train,dev,kw).snapshot()['evaluation_coverage']['paragraph_validation']
    assert report['observed_vector_rows']==report['observed_source_strings']==48
    assert report['missing_vector_source_strings']>0 and not report['vector_coverage_complete']
