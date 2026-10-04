"""Synthetic cohort/optimizer controls; no native model or qualification."""
from copy import deepcopy
import hashlib
import json
import re
import time

import pytest

torch = pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization.autoencoder import native4096_balanced_cohort_experiment as subject
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical


@pytest.fixture(autouse=True)
def one_cpu():
    before = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(before)


def codec():
    words=['F','O','P','action','actor','approve','archive','conditions','deliver','examine',
           'exceptions','modality','notary','notice','object','preserve','publish','registrar',
           'rules','secretary','temporal','treasurer','trustee']
    return {'schema':'synthetic-authored-codec/v1',
            'target_vocabulary':['<pad>','<bos>','<eos>']+[json.dumps(w) for w in words]+[',',':','[',']','{','}']}


def target(actor='registrar', action='deliver', modality='O', obj='notice'):
    text=json.dumps({'rules':[dict(action=action,actor=actor,conditions=[],exceptions=[],
        modality=modality,object=obj,temporal=[])]},sort_keys=True,separators=(',',':'))
    vocabulary=codec()['target_vocabulary']
    return [1]+[vocabulary.index(token) for token in re.findall(r'"[^"]*"|[,:{}\[\]]',text)]+[2]


def banks():
    groups={}
    for split,offset in [('train',1),('validation',0)]:
        rows=[]
        for i,actor in enumerate(subject.VALUES['actor']):
            action=subject.VALUES['action'][(i+offset)%5]
            for modality in subject.VALUES['modality']:
                modal={'F':'must not','O':'must','P':'may'}[modality]
                for obj in subject.VALUES['object']:
                    text=f'The {actor} {modal} {action} the {obj}.'
                    rows.append(dict(id=split+':'+hashlib.sha256(text.encode()).hexdigest(),source_text=text,
                        input=[99.]*384,target_ids=target(actor,action,modality,obj)))
        groups[split]=rows
    cache={'dimensions':{'384':{'clause_cache':{name:[{'id':row['id'],'source_text':row['source_text'],'input':[99.]*384} for row in rows]
                                                for name,rows in groups.items()}}}}
    tokens={'rows':[{'source_sha256':hashlib.sha256(row['source_text'].encode()).hexdigest(),'token_count':10}
                    for rows in groups.values() for row in rows]}
    return groups['train'],groups['validation'],cache,tokens


def test_deterministic_original_cohort_balances_fields_and_never_copies_old_vectors():
    args=banks();before=deepcopy(args)
    observed=subject.select_original_cohort(*args,codec())
    shuffled=(list(reversed(args[0])),list(reversed(args[1])),args[2],args[3])
    assert subject.select_original_cohort(*shuffled,codec())==observed
    assert args==before
    assert observed['original_actor_action_pairs_disjoint']
    for name in ['training_labels','development_labels']:
        assert len(observed[name])==12
        assert all(set(row)=={'id','source_text','target_ids'} for row in observed[name])
    for stats in observed['statistics'].values():
        assert stats['count']==12 and set(stats['fields']['modality'].values())=={4}
        assert set(stats['fields']['object'].values())=={6}
        assert all(2<=count<=3 for field in ['actor','action'] for count in stats['fields'][field].values())
    assert observed['development_status']=='previously_exposed_original_development_split'
    assert not observed['admitted'] and not observed['qualified']


@pytest.mark.parametrize('change',['normalized_overlap','id_overlap','duplicate','wrong_membership','missing_tokens',
    'token_boolean','token_overflow','token_duplicate','pair_overlap','bad_target','impossible_balance'])
def test_cohort_rejects_drift_in_original_split_or_token_inventory(change):
    train,dev,cache,tokens=banks()
    if change=='normalized_overlap':dev[0]['source_text']='  '+train[0]['source_text'].upper()+' '
    elif change=='id_overlap':dev[0]['id']=train[0]['id']
    elif change=='duplicate':train.append(deepcopy(train[0]))
    elif change=='wrong_membership':cache['dimensions']['384']['clause_cache']['train'][0]['source_text']='Not in bank.'
    elif change=='missing_tokens':tokens['rows'].pop(0)
    elif change=='token_boolean':tokens['rows'][0]['token_count']=True
    elif change=='token_overflow':tokens['rows'][0]['token_count']=513
    elif change=='token_duplicate':tokens['rows'].append(deepcopy(tokens['rows'][0]))
    elif change=='pair_overlap':
        for row in dev:row['target_ids']=target('registrar','deliver')
    elif change=='bad_target':train[0]['target_ids']=[1,3,2]
    else:
        for row in train:row['target_ids']=target('registrar','deliver','F','notice')
    with pytest.raises((ValueError,KeyError)):
        subject.select_original_cohort(train,dev,cache,tokens,codec())


def donor():
    return numerical._model({'dimension':384},codec(),dict(seed=7,hidden_size=8,token_embedding_dim=8,projection_width=2))


def small_rows():
    return [dict(id='a',source_text='Synthetic A.',input=[1.,0.]+[0.]*4094,target_ids=target(obj='archive')),
            dict(id='b',source_text='Synthetic B.',input=[0.,1.]+[0.]*4094,target_ids=target(obj='notice'))]


def test_development_vectors_and_labels_cannot_change_optimizer_or_train_statistics():
    parent=donor();training=small_rows();dev=deepcopy(training)
    for row in dev:row['id']='dev:'+row['id'];row['source_text']='Dev '+row['source_text']
    altered=deepcopy(dev)
    for row in altered:
        row['input']=[.015625]*4096
        row['target_ids']=target('notary','approve','F','archive')
    outputs=[]
    for values in (dev,altered):
        model=subject.pilot._new_body(parent,vocabulary_size=32)
        outputs.append(subject._fit_arm(model,training,values,vocabulary=codec()['target_vocabulary'],
            arm='joint_source_scaled',steps=3,deadline=time.monotonic()+30))
    assert outputs[0]['normalization']==outputs[1]['normalization']
    assert outputs[0]['final_tensor_sha256']==outputs[1]['final_tensor_sha256']
    assert outputs[0]['updates']==outputs[1]['updates']
    assert outputs[0]['observations'][-1]['development']!=outputs[1]['observations'][-1]['development']


def test_new_cohort_loop_keeps_original_twenty_step_unscaled_math():
    parent=donor();training=small_rows();v=codec()['target_vocabulary']
    original=subject.pilot._new_body(parent,vocabulary_size=32)
    current=subject.pilot._new_body(parent,vocabulary_size=32)
    old=subject.conditioning._fit_arm(original,training,arm='joint_unscaled',steps=20,deadline=time.monotonic()+30)
    new=subject._fit_arm(current,training,training,vocabulary=v,arm='joint_unscaled',steps=20,deadline=time.monotonic()+30)
    assert old['final_tensor_sha256']==new['final_tensor_sha256']
    for control in ['conditioned','zero_source','rotated_source']:
        assert old['observations'][-1][control]['cross_entropy']==new['observations'][-1]['train'][control]['cross_entropy']
        assert old['observations'][-1][control]['predictions']==new['observations'][-1]['train'][control]['predictions']
    assert new['row_presentations']==40 and new['target_token_presentations']==1560


def test_restricted_rule_decode_rejects_duplicate_or_unknown_fields():
    v=codec()['target_vocabulary']
    good=target()[1:-1]
    assert subject._rule(good,v)['modality']=='O'
    text=''.join(v[t] for t in good)
    duplicate=text.replace('"actor":"registrar"','"actor":"registrar","actor":"registrar"')
    encoded=[v.index(t) for t in re.findall(r'"[^"]*"|[,:{}\[\]]',duplicate)]
    with pytest.raises(ValueError,match='duplicate'):subject._rule(encoded,v)
    with pytest.raises(ValueError):subject._rule([3],v)


def test_expired_deadline_preserves_model():
    model=subject.pilot._new_body(donor(),vocabulary_size=32);digest=subject.core.tensor_digest(model)
    with pytest.raises(ValueError,match='deadline'):
        subject._fit_arm(model,small_rows(),small_rows(),vocabulary=codec()['target_vocabulary'],
                         arm='joint_unscaled',deadline=time.monotonic()-1)
    assert subject.core.tensor_digest(model)==digest


def test_saved_native_rows_cannot_authorize_cohort_training():
    with pytest.raises((TypeError,ValueError)):
        subject.train_native_cohort({'rows':small_rows(),'verified':True},donor=donor(),codec=codec(),
                                     training_labels=[],development_labels=[])
