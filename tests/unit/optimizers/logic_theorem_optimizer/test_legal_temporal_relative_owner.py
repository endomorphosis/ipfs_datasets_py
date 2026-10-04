"""Source geometry, frozen type parity, norm-only gradients and exact resume."""
from copy import deepcopy
import hashlib
import math
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
import pytest
import torch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_relative_owner as own


def query(text, index=0):
    needle = 'within 10 days'; points = [i for i in range(len(text)) if text.startswith(needle, i)]; a = points[index]
    return {'id': hashlib.sha256((text+':'+str(a)).encode()).hexdigest(), 'source_text': text,
        'source_sha256': hashlib.sha256(text.encode()).hexdigest(), 'proposed_time_span': {'char_start': a, 'char_end': a+len(needle)}}


def singles(prefix, count=6):
    return [{**query(f'{prefix}{g} {label} Registry shall file within 10 days.'), 'label': label, 'group_id': f'{prefix}-{g}'}
            for g in range(count) for label in own.CLASSES]


def multiples(prefix):
    rows, ids = [], []
    for group, labels in enumerate([(0, 0), (1, 1), (2, 2), (3, 3, 0), (3, 1, 2)]):
        text = '; '.join(f'{prefix}_{group}_{i} Registry files within 10 days' for i in range(len(labels)))+'.'
        for i, label in enumerate(labels):
            row = {**query(text, i), 'label': own.CLASSES[label], 'group_id': f'{prefix}-{group}'}
            ids.append(row['id']); rows.append(row)
    return rows, [{'unit_id': prefix, 'query_ids': ids}]


def targets(prefix, count=6):
    rows, contrasts = [], {}
    for group in range(count):
        for label in own.CLASSES:
            text = f'{prefix}{group} {label}: Board archives notice; Registry shall file within 10 days.'
            row = {**query(text), 'label': label, 'group_id': f'{prefix}-{group}'}
            a = text.index('Registry'); b = text.index('Board')
            row['owner_anchor_span'] = None if label == 'ambiguous' else {'char_start': a, 'char_end': a+len('Registry shall file')}
            rows.append(row); contrasts[row['id']] = {'id': row['id'], 'source_sha256': row['source_sha256'],
                'proposed_time_span': row['proposed_time_span'], 'negative_owner_spans':
                [{'char_start': b, 'char_end': b+len('Board archives notice')}] if label == 'norm' else []}
    return rows, contrasts


@pytest.fixture(scope='module')
def setup():
    # Synthetic inherited checkpoints exercise contracts; these are not fits/evidence.
    patch = pytest.MonkeyPatch(); earlier = own.parent.parent.previous.previous
    patch.setattr(earlier.parent_runtime, 'validate_checkpoint', lambda _: None)
    cfg = {'seed': 1730, 'hidden_size': 32, 'embedding_dim': 16, 'latent_dimension': 0, 'trigger_enabled': True}
    base = earlier.mixed._model(torch, cfg)
    source = {'model_config': cfg, 'model_state': {k: v.detach().tolist() for k, v in base.state_dict().items()}}
    old_train, old_tune = singles('old'), singles('old-tune', 2)
    first = earlier.build_checkpoint(source, old_train, old_tune, arm='finetune_occurrence', seed=1730, parent_file_sha256='1'*64)
    first, _ = earlier.train(first, old_train, old_tune, additional_steps=1); first['optimizer_steps'] = 200
    for value in first['optimizer_state']['parameters'].values(): value['step'] = 200
    paired, units = multiples('paired'); paired_tune, _ = multiples('paired-tune')
    second = own.parent.parent.previous.build_checkpoint(first, old_train, paired, units, old_tune, paired_tune,
        arm='mixed_occurrences', seed=1730, parent_file_sha256='2'*64)
    second, _ = own.parent.parent.previous.train(second, old_train, paired, units, old_tune, paired_tune, additional_steps=1)
    second['optimizer_steps'] = 200; second['cumulative_owner_head_updates'] = 400
    for value in second['optimizer_state']['parameters'].values(): value['step'] = 200
    train, contrasts = targets('current'); tune, _ = targets('current-tune', 2)
    pointer = own.parent.parent.build_checkpoint(second, train, tune, arm='finetune_encoder', seed=1730, parent_file_sha256='3'*64)
    pointer, _ = own.parent.parent.train(pointer, train, tune, additional_steps=1)
    pointer['optimizer_steps'] = 300; pointer['cumulative_owner_head_updates'] = 700
    for value in pointer['optimizer_state']['parameters'].values(): value['step'] = 300
    warm = own.parent.build_checkpoint(pointer, train, tune, contrasts, arm='joint_span', seed=1730, parent_file_sha256='4'*64)
    warm, _ = own.parent.train(warm, train, tune, contrasts, additional_steps=1)
    warm['optimizer_steps'] = 200; warm['cumulative_owner_head_updates'] = 900
    for value in warm['optimizer_state']['parameters'].values(): value['step'] = 200
    yield warm, train, tune, contrasts
    patch.undo()


def cp(setup, arm='relative_norm_contrast'):
    return own.build_checkpoint(*setup, arm=arm, seed=1730, parent_file_sha256='5'*64)


def test_zero_residual_initial_arrays_and_full_parent_wire_parity(setup):
    checkpoints = [cp(setup, arm) for arm in own.ARMS]
    assert all(c['model_state'] == checkpoints[0]['model_state'] for c in checkpoints)
    assert all(c['optimizer_state']['parameters'] == {} for c in checkpoints)
    assert all(checkpoints[0]['model_state'][k] == v for k, v in setup[0]['model_state'].items())
    sources = own.source_queries(setup[1][:4])
    original = own.parent.CoupledTemporalOwnerPointer(setup[0]).predict_many(sources)
    for c in checkpoints:
        rows = own.RelativeTemporalOwnerPointer(c).predict_many(sources)
        assert [{k: r[k] for k in original[0]} for r in rows] == original
        assert all(all(v == 0. for v in r[key]) for r in rows for key in ('relative_start_logits','relative_end_logits'))
    assert checkpoints[0]['parent_owner_head_updates'] == checkpoints[0]['cumulative_owner_head_updates'] == 900


@pytest.mark.parametrize('arm,count', [('source_pointer',25746), ('relative_position',25988), ('relative_norm_contrast',25988)])
def test_exact_resume_trainability_and_type_outputs_unchanged(setup, arm, count):
    initial = cp(setup, arm); args = setup[1:]
    first, r1 = own.train(initial, *args, additional_steps=1)
    split, r2 = own.train(first, *args, additional_steps=1)
    whole, report = own.train(initial, *args, additional_steps=2)
    assert split['model_state'] == whole['model_state'] and split['optimizer_state'] == whole['optimizer_state']
    assert r1['trace']+r2['trace'] == report['trace']
    assert sum(report['trainable_parameters'].values()) == count
    assert report['encoder_batch_forwards'] == 2 and report['encoder_source_evaluations'] == 48
    for name, value in initial['model_state'].items():
        if name.startswith(('source.', 'head.')) or arm == 'source_pointer' and name.startswith('position_head.'):
            assert whole['model_state'][name] == value
    assert whole['model_state']['pointer_start.0.weight'] != initial['model_state']['pointer_start.0.weight']
    assert whole['model_state']['interaction_start.weight'] != initial['model_state']['interaction_start.weight']
    source = own.source_queries(setup[1][:4])
    prior = own.parent.CoupledTemporalOwnerPointer(setup[0]).predict_many(source)
    after = own.RelativeTemporalOwnerPointer(whole).predict_many(source)
    keys = ('logits','probabilities','predicted_label','confidence','status','owner_type','reason')
    assert [{k:r[k] for k in keys} for r in prior] == [{k:r[k] for k in keys} for r in after]
    if arm != 'source_pointer':
        assert whole['model_state']['position_head.2.weight'] != initial['model_state']['position_head.2.weight']
        assert whole['model_state']['position_head.0.weight'] != initial['model_state']['position_head.0.weight']


def test_geometry_exact_boundaries_capped_counts_and_inside_zero():
    texts = ['A',';', ';',';', ';',';', '.', '!', '?', ',', ':', 'within','10','days','B',';','C']
    record = {'tokens':[{'text':t} for t in texts], 'time_tokens':(11,13)}
    features = own.relative_features(record); d=16
    assert features[0] == [-11/d,-13/d,11/d,1.,0.,0.,1.,.75,.25,.25,0.,0.]
    assert features[1][6] == 1.  # four semicolons remain strictly between.
    assert features[5][6] == 0.  # current semicolon is excluded from the count.
    assert features[12][:6] == [1/d,-1/d,0.,0.,0.,1.]
    assert features[14][6:10] == [0.,0.,0.,0.]
    assert features[16][6] == .25 and features[15][-2:] == [1.,1.]
    assert len(features) == len(texts) and all(len(v)==12 for v in features)


def test_geometry_uses_source_query_only_and_repeated_occurrences_differ():
    text='Board shall file within 10 days; Registry shall archive within 10 days.'
    left,right=[own._query(query(text,i)) for i in (0,1)]
    changed={**left,'label':3,'owner_tokens':(0,2),'negative_owner_tokens':[(3,5)],'group_id':'secret'}
    changed['query']={**changed['query'],'id':'unrelated'}
    assert own.relative_features(left)==own.relative_features(changed)
    assert own.relative_features(left)!=own.relative_features(right)


def test_unicode_punctuation_and_single_token_geometry():
    r={'tokens':[{'text':'—'},{'text':'é'},{'text':'1'},{'text':'.'}],'time_tokens':(1,2)}
    f=own.relative_features(r)
    assert f[0][-2:]==[1.,0.] and f[1][-2:]==[0.,0.] and f[3][-2:]==[1.,0.]
    assert own.relative_features({'tokens':[{'text':'May'}],'time_tokens':(0,0)})==[[0.,0.,0.,0.,0.,1.,0.,0.,0.,0.,0.,0.]]


def oracle(logits, starts, ends, left, right, records, arm):
    typ, joint, contrast = [], [], []
    for k,r in enumerate(records):
        typ.append(torch.logsumexp(logits[k],0)-logits[k,r['label']])
        if r['label']==3:continue
        n=len(r['tokens']);qa,qb=r['time_tokens'];a,b=r['owner_tokens']
        def score(i,j):return starts[k,i]+ends[k,j]+sum(left[k,i,d]*right[k,j,d] for d in range(8))/math.sqrt(8)
        gold=score(a,b)
        pairs=[score(i,j) for i in range(n) for j in range(i,n) if j<qa or i>qb]
        joint.append(torch.logsumexp(torch.stack(pairs),0)-gold)
        if r['negative_owner_tokens']:
            assert r['label']==0
            contrast.append(torch.logsumexp(torch.stack([gold,*[score(i,j) for i,j in r['negative_owner_tokens']]]),0)-gold)
    zero=starts[0,0]*0+ends[0,0]*0+left[0,0,0]*0+right[0,0,0]*0
    tc=torch.stack(typ).mean(); jc=torch.stack(joint).mean() if joint else zero
    cc=torch.stack(contrast).mean() if contrast else zero
    return tc+.5*jc+(.25*cc if arm=='relative_norm_contrast' else 0),jc,cc


@pytest.mark.parametrize('arm',own.ARMS)
def test_independent_joint_norm_contrast_values_gradients_and_masks(arm):
    rows,contrasts=targets('oracle',1); records=own._contrasts(rows,own._records(rows),contrasts)
    n=max(len(r['tokens']) for r in records)+2; rng=torch.Generator().manual_seed(29)
    for scale in (.1,1.,10.):
        arrays=[(torch.randn(*shape,generator=rng,dtype=torch.float64)*scale).requires_grad_()
                for shape in ((4,4),(4,n),(4,n),(4,n,8),(4,n,8))]
        actual,parts=own.objective(torch,*arrays,records,arm);expected,joint,contrast=oracle(*arrays,records,arm)
        assert torch.allclose(actual,expected,atol=1e-11,rtol=1e-11)
        assert abs(parts['joint_ce']-float(joint.detach()))<1e-11 and abs(parts['contrast_ce']-float(contrast.detach()))<1e-11
        ga=torch.autograd.grad(actual,arrays,retain_graph=True);ge=torch.autograd.grad(expected,arrays)
        assert all(torch.allclose(a,b,atol=1e-11,rtol=1e-11) for a,b in zip(ga,ge))
        assert parts['contrast_count']==1 and parts['norm_count']==1 and parts['contrast_negative_counts']==[1,0,0,0]
        for g in ga[1:]:
            assert torch.count_nonzero(g[3])==0 and torch.count_nonzero(g[:,-2:])==0
            for i,r in enumerate(records):
                a,b=r['time_tokens'];assert torch.count_nonzero(g[i,a:b+1])==0


def test_empty_norm_negative_set_and_ambiguous_zero_pointer_gradients():
    rows,c=targets('empty',1)
    for v in c.values():v['negative_owner_spans']=[]
    records=own._contrasts(rows,own._records(rows),c);n=len(records[0]['tokens'])
    arrays=[torch.randn(*shape,dtype=torch.float64,requires_grad=True) for shape in ((4,4),(4,n),(4,n),(4,n,8),(4,n,8))]
    a,parts=own.objective(torch,*arrays,records,'relative_norm_contrast');b,_=own.objective(torch,*arrays,records,'source_pointer')
    assert a==b and parts['contrast_count']==parts['contrast_ce']==0
    ambiguous=[records[3]]*4
    a,p=own.objective(torch,*arrays,ambiguous,'relative_norm_contrast')
    gradients=torch.autograd.grad(a,arrays)
    assert p['joint_ce']==p['contrast_ce']==0
    assert all(torch.count_nonzero(g)==0 for g in gradients[1:])


def test_first_relative_layer_gradient_and_frozen_graph(setup):
    c=cp(setup);_,model,_=own._restore(c);records,_=own._splits(*setup[1:])
    batch=[records[i] for i in own.batch_indices(records,1730,0)]
    loss,_=own.objective(torch,*model(batch),batch,'relative_norm_contrast');loss.backward()
    assert torch.count_nonzero(model.position_head[2].weight.grad)>0
    assert torch.count_nonzero(model.position_head[0].weight.grad)==0
    assert all(p.grad is None for name,p in model.named_parameters() if name.startswith(('source.','head.')))


def test_trace_base_plus_residual_exact_float32_and_source_binding(setup):
    _,report=own.train(cp(setup),*setup[1:],additional_steps=2)
    for trace in report['trace']:
        for end in ('start','end'):
            for base,residual,final in zip(trace[f'base_pointer_{end}_logits'],trace[f'relative_{end}_logits'],trace[f'pointer_{end}_logits']):
                assert (torch.tensor(base)+torch.tensor(residual)).tolist()==final
        assert trace['relative_enabled'] is True and trace['interaction_enabled'] is True
        assert trace['objective_components']['norm_count']==6
        assert all(not neg for label,neg in zip(trace['labels'],trace['negative_owner_token_spans']) if label!=0)


@pytest.mark.parametrize('label', ['condition','exception','ambiguous'])
def test_non_norm_contrasts_rejected(label):
    rows,c=targets('bad',1);r=next(r for r in rows if r['label']==label)
    c[r['id']]['negative_owner_spans']=deepcopy(c[rows[0]['id']]['negative_owner_spans'])
    with pytest.raises(ValueError,match='only norm'):own._contrasts(rows,own._records(rows),c)


@pytest.mark.parametrize('mutation', ['id','source','query','missing','extra','gold','overlap','duplicate','unaligned','bool'])
def test_invalid_norm_source_bound_negative_rejected(mutation):
    rows,c=targets('bad',1);r=rows[0];item=c[r['id']];value=item['negative_owner_spans'][0]
    if mutation=='id':item['id']='other'
    elif mutation=='source':item['source_sha256']='0'*64
    elif mutation=='query':item['proposed_time_span']={**item['proposed_time_span'],'char_start':0}
    elif mutation=='missing':c.pop(r['id'])
    elif mutation=='extra':item['label']='norm'
    elif mutation=='gold':item['negative_owner_spans']=[r['owner_anchor_span']]
    elif mutation=='overlap':item['negative_owner_spans']=[r['proposed_time_span']]
    elif mutation=='duplicate':item['negative_owner_spans'].append(deepcopy(value))
    elif mutation=='unaligned':value['char_start']+=1
    elif mutation=='bool':value['char_start']=True
    with pytest.raises(ValueError):own._contrasts(rows,own._records(rows),c)


@pytest.mark.parametrize('kind',['source','head','position','config_float','config_bool','parent','moments'])
def test_checkpoint_mutations_rejected(setup,kind):
    c=cp(setup,'source_pointer')
    if kind in ('source','head','position'):
        key={'source':'source.encoder.weight_ih_l0','head':'head.0.weight','position':'position_head.0.weight'}[kind]
        c['model_state'][key][0][0]+=.1
        c['initial_state_sha256']=own.digest(c['model_state'])
    elif kind=='config_float':c['config']['max_steps']=200.0
    elif kind=='config_bool':c['config']['relative_enabled']=0
    elif kind=='parent':c['parent_payload_sha256']='a'*64
    else:c['optimizer_state']['parameters']={'fake':{}}
    with pytest.raises(ValueError):own._restore(c)


def test_posttraining_frozen_weight_mutation_rejected(setup):
    c,_=own.train(cp(setup),*setup[1:],additional_steps=1)
    c['model_state']['head.0.weight'][0][0]+=.1
    with pytest.raises(ValueError,match='frozen'):own._restore(c)


def test_inference_rejects_labels_and_ignores_id(setup):
    decoder=own.RelativeTemporalOwnerPointer(cp(setup));sources=own.source_queries(setup[1][:4])
    a=decoder.predict_many(sources);changed=deepcopy(sources)
    for r in changed:r['id']='different-'+r['id']
    b=decoder.predict_many(changed)
    assert [{k:v for k,v in r.items() if k!='id'} for r in a]==[{k:v for k,v in r.items() if k!='id'} for r in b]
    with pytest.raises(ValueError):decoder.predict_many([{**sources[0],'label':'norm'}])


def test_file_roundtrip_and_manifest_change_rejected(setup,tmp_path):
    c=cp(setup);pin=own.save_checkpoint(c,tmp_path/'checkpoint.json')
    assert own.load_checkpoint(pin['path'],expected_sha256=pin['sha256'])==c
    with pytest.raises(ValueError):own.load_checkpoint(pin['path'],expected_sha256='0'*64)
    contrasts=deepcopy(setup[3]);contrasts[setup[1][0]['id']]['negative_owner_spans']=[]
    with pytest.raises(ValueError,match='manifests'):own.train(c,setup[1],setup[2],contrasts,additional_steps=0)
