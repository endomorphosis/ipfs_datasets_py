"""Separate authored rehearsal, exact parents, balanced losses and resumption."""
from copy import deepcopy
from pathlib import Path
import runpy

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_timing_ownership as runtime
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as facet
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_temporal_presence as temporal

H = runpy.run_path(str(Path(__file__).with_name('test_legal_span_temporal_presence.py')))


@pytest.fixture(scope='module', autouse=True)
def threads():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def auxiliary_inventory(prefix='aux'):
    rows, pairs, blocks = [], [], []
    for block_index in range(4):
        pair_ids = []
        modality = ('O', 'P', 'F')[block_index % 3]
        cue = {'O':'must', 'P':'may', 'F':'must not'}[modality]
        for mask in (block_index, 7-block_index):
            case = f'{prefix}{block_index}m{mask}'
            rule = {'actor':f'the {case} Records Office', 'action':'file', 'object':f'the {case} report',
                'modality':modality, 'conditions':[f'the {case} permit exists'] if mask & 1 else [],
                'exceptions':[f'the {case} waiver applies'] if mask & 2 else [],
                'temporal':['within 17 hours'] if mask & 4 else []}
            canonical = {'rules':[rule]}
            ids = []
            for headed in (False, True):
                text = ''; facets = {f:None for f in runtime.span.SPAN_FIELDS}
                def add(value):
                    nonlocal text
                    start = len(text); text += value
                    return [start, len(text)]
                for field, marker in (('conditions','If '), ('exceptions','Unless '), ('temporal','')):
                    if rule[field]:
                        add(marker); facets[field] = add(rule[field][0]); add(', ')
                if headed: add(f'({block_index+1}) Filing duty: ')
                facets['actor'] = add(rule['actor']); add(' '); trigger = add(cue); add(' ')
                facets['action'] = add(rule['action']); add(' '); facets['object'] = add(rule['object']); add('.')
                identity = f'{case}-{int(headed)}'; ids.append(identity)
                rows.append({'id':identity, 'source_text':text, 'canonical_ir':deepcopy(canonical),
                    'trigger_span':trigger, 'facet_spans':facets, 'domain':'new', 'trigger_supervised':True})
            pair_id = 'pair-'+case; pair_ids.append(pair_id)
            pairs.append({'pair_id':pair_id, 'case_group':case, 'left_id':ids[0], 'right_id':ids[1],
                'canonical_ir_sha256':runtime.checkpoint_digest(canonical)})
        blocks.append({'block_id':f'{prefix}-block-{block_index}', 'pair_ids':pair_ids})
    return rows, pairs, blocks


@pytest.fixture(scope='module')
def data():
    rows, pairs = H['rows_and_pairs']('role-fit')
    return (rows, [], pairs, *auxiliary_inventory())


@pytest.fixture(scope='module')
def parents():
    originals = H['parents'].__wrapped__()
    rows, pairs = H['rows_and_pairs']('role-parent')
    updated = temporal.train_decoder(temporal.build_checkpoint(originals[True], rows, [], pairs,
        objective='base', seed=1729), rows, [], pairs, max_steps=2, max_seconds=30)['checkpoint']
    return {False:('facet_retention', originals[False]), True:('temporal_presence', updated)}


def child(parents, data, enabled=True, objective='ownership'):
    kind, parent = parents[enabled]
    return runtime.build_checkpoint(parent, *data, parent_kind=kind, objective=objective, seed=1729)


@pytest.mark.parametrize('enabled', [False, True])
def test_exact_heterogeneous_parent_state_inference_and_fresh_adam(parents, data, enabled):
    kind, parent = parents[enabled]; cp = child(parents, data, enabled)
    assert cp['model_state'] == parent['model_state'] and cp['optimizer_state']['parameters'] == {}
    assert cp['frozen_parent_kind'] == kind and cp['frozen_parent_checkpoint'] == parent
    assert cp['training_count'] == len(data[0]) and cp['auxiliary_count'] == 16
    assert cp['training_config']['learning_rate'] == .00025 and runtime.optimizer_steps(cp) == 0
    texts = [r['source_text'] for r in data[3][:4]]
    parent_decoder = facet.FacetRetentionDecoder if kind == 'facet_retention' else temporal.TemporalPresenceDecoder
    decoder = runtime.TimingOwnershipDecoder(cp)
    assert decoder.decode_formal_logic(texts)['rows'] == parent_decoder(parent).decode_formal_logic(texts)['rows']
    cp['model_state'] = {}; assert decoder.checkpoint['model_state'] == parent['model_state']


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('objective', ['common', 'ownership'])
def test_exact_resume_states_moments_losses_auxiliary_logits_and_schedules(parents, data, enabled, objective):
    cp = child(parents, data, enabled, objective)
    full = runtime.train_decoder(cp, *data, max_steps=5, max_seconds=30)
    first = runtime.train_decoder(cp, *data, max_steps=2, max_seconds=30)
    resumed = runtime.train_decoder(first['checkpoint'], *data, max_steps=3, max_seconds=30)
    for key in ('model_state', 'optimizer_state', 'progress'):
        assert full['checkpoint'][key] == resumed['checkpoint'][key]
    for key in ('batch_losses', 'batch_loss_components', 'batch_exposures', 'auxiliary_loss_receipts'):
        assert full['report'][key] == first['report'][key] + resumed['report'][key]
    for component in full['report']['batch_loss_components']:
        assert component['weighted_auxiliary_standard_ce'] == pytest.approx(.25*component['auxiliary_standard_ce'])
        assert component['total'] == pytest.approx(component['common_objective'] +
            (.25 if objective == 'ownership' else 0)*component['timing_ownership_nll'], abs=1e-6)
        assert all(component[f'ownership_{f}_present_rows'] == component[f'ownership_{f}_absent_rows'] == 2
            for f in ('conditions', 'temporal'))
    assert full['report']['auxiliary_source_exposures'] == 20
    assert full['report']['teacher_state_sha256_before'] == full['report']['teacher_state_sha256_after']
    if not enabled: assert all(v == 0 for v in full['report']['auxiliary_gradient_norm_max'].values())


@pytest.mark.parametrize('enabled', [False, True])
def test_base_really_supervises_same_auxiliary_rows_and_exact_common_gradients(parents, data, enabled):
    base = child(parents, data, enabled, 'common'); target = child(parents, data, enabled)
    a = runtime.train_decoder(base, *data, max_steps=1, max_seconds=30)
    b = runtime.train_decoder(target, *data, max_steps=1, max_seconds=30)
    assert a['report']['batch_exposures'] == b['report']['batch_exposures']
    assert a['report']['auxiliary_loss_receipts'] == b['report']['auxiliary_loss_receipts']
    assert base['model_state'] == target['model_state']
    records, _, auxiliary, _ = runtime._auxiliary_data(data[0], data[1], *data[3:])
    trace = a['report']['batch_exposures'][0]
    main = {r['id']:r for r in records}; aux = {r['id']:r for r in auxiliary}
    batch = [main[i] for i in trace['ids']]; aux_batch = [aux[i] for i in trace['auxiliary_ids']]
    _, model, _ = runtime._restore(base)
    kind, parent = parents[enabled]; _, teacher, _ = runtime._parent_runtime(kind)._restore(parent)
    actual, parts, _ = runtime._loss(torch, model, teacher, batch, aux_batch, base['model_config'], 'common')
    old, _ = facet._loss(torch, model, teacher, batch, base['model_config'], 'facet_retention')
    aux_standard = runtime.span._loss(torch, model, aux_batch)
    expected = old + .25*aux_standard
    assert torch.equal(actual, expected) and parts['weighted_ownership'] == 0
    actual_grad = torch.autograd.grad(actual, tuple(model.parameters()), retain_graph=True)
    expected_grad = torch.autograd.grad(expected, tuple(model.parameters()), retain_graph=True)
    old_grad = torch.autograd.grad(old, tuple(model.parameters()))
    assert all(torch.equal(x, y) for x, y in zip(actual_grad, expected_grad))
    assert any(not torch.equal(x, y) for x, y in zip(actual_grad, old_grad))


def test_main_sampler_is_unchanged_and_all_auxiliary_blocks_cycle(data):
    pools = runtime._pairs_and_pools(data[0], data[2]); counts = {k:len(v) for k,v in pools.items()}
    progress = runtime._progress(counts, 144, 1730); old = temporal._progress(counts, 1730); seen = []
    for step in range(200):
        chosen, progress = runtime.next_batch_indices(progress, counts, 144, 1730)
        old_chosen, old = temporal.next_batch_indices(old, counts, 1730)
        assert {k:v for k,v in chosen.items() if k != 'auxiliary_block'} == old_chosen
        assert progress == runtime._progress(counts, 144, 1730, step+1)
        seen.extend(chosen['auxiliary_block'])
    assert len(seen) == 200 and set(seen[:144]) == set(range(144))


def fake_auxiliary():
    output = H['HELPERS']['fake_output'](4)
    _, _, record = H['HELPERS']['teacher_fixture']()
    rows = [deepcopy(record) for _ in range(4)]
    for i, row in enumerate(rows):
        for f in range(3, 6):
            present = i < 2
            row['labels']['presence'][f] = present
            row['labels']['spans'][f] = (1, 1) if present else (-100, -100)
    return output, rows


def enumerated_logs(start, end, presence):
    choices=[(i,j) for i in range(len(start)) for j in range(i,len(start))]
    scores=torch.stack([start[i]+end[j] for i,j in choices])
    normalizer=torch.logsumexp(scores,0); lp=presence.log_softmax(-1)
    yes=[];no=[]
    for t in range(len(start)):
        inside=torch.stack([scores[k] for k,(i,j) in enumerate(choices) if i<=t<=j])
        outside=[scores[k] for k,(i,j) in enumerate(choices) if not i<=t<=j]
        yes.append(lp[1]+torch.logsumexp(inside,0)-normalizer)
        no.append(torch.logsumexp(torch.stack([lp[0]]+([lp[1]+torch.logsumexp(torch.stack(outside),0)-normalizer] if outside else [])),0))
    return torch.stack(yes),torch.stack(no)


@pytest.mark.parametrize('length',[1,2,3,7])
@pytest.mark.parametrize('scale',[.1,1.,100.,1000.])
def test_log_ownership_values_and_gradients_match_enumerated_spans(length,scale):
    generator=torch.Generator().manual_seed(44+length)
    values=[(torch.randn(n,dtype=torch.float64,generator=generator)*scale).requires_grad_() for n in (length,length,2)]
    actual=runtime._token_ownership_log_probabilities(torch,*values)
    wanted=enumerated_logs(*values)
    for a,b in zip(actual,wanted):assert torch.allclose(a,b,atol=2e-12,rtol=1e-12)
    a=sum(x.sum() for x in actual);b=sum(x.sum() for x in wanted)
    ag=torch.autograd.grad(a,values,retain_graph=True);bg=torch.autograd.grad(b,values)
    assert torch.isfinite(a) and all(torch.isfinite(g).all() for g in ag)
    assert all(torch.allclose(x,y,atol=2e-11,rtol=1e-11) for x,y in zip(ag,bg))
    assert torch.allclose(actual[0].exp()+actual[1].exp(),torch.ones(length,dtype=torch.float64),atol=1e-12,rtol=1e-12)


def independent_loss(output,records):
    facets=[]
    for field in ('conditions','temporal'):
        facet=runtime.span.SPAN_FIELDS.index(field);optional=runtime.span.OPTIONAL_FIELDS.index(field)
        rows={False:[],True:[]}
        for index,r in enumerate(records):
            count=len(r['tokens']);present=bool(r['labels']['presence'][facet]);bounds=r['labels']['spans'][facet]
            yes,no=enumerated_logs(output['start'][index,facet,:count],output['end'][index,facet,:count],output['presence'][index,optional])
            inside=[t for t in range(count) if present and bounds[0]<=t<=bounds[1]]
            outside=[t for t in range(count) if t not in inside]
            means=[]
            if inside:means.append(-yes[inside].mean())
            if outside:means.append(-no[outside].mean())
            rows[present].append(torch.stack(means).mean())
        facets.append((torch.stack(rows[True]).mean()+torch.stack(rows[False]).mean())/2)
    return torch.stack(facets).mean()


def test_balanced_loss_formula_gradients_padding_and_only_CT_heads():
    output,rows=fake_auxiliary()
    output={k:v.detach().double().requires_grad_() for k,v in output.items()}
    actual,parts=runtime._timing_ownership_loss(torch,output,rows);expected=independent_loss(output,rows)
    assert torch.allclose(actual,expected,atol=1e-12,rtol=1e-12)
    tensors=[output[k] for k in ('start','end','presence')]
    ag=torch.autograd.grad(actual,tensors,retain_graph=True);eg=torch.autograd.grad(expected,tensors)
    assert all(torch.allclose(a,b,atol=1e-12,rtol=1e-12) for a,b in zip(ag,eg))
    for gradient in ag[:2]:
        assert gradient[:,[3,5]].abs().sum()>0
        assert gradient[2:,[3,5]].abs().sum()>0 # Absent spans cannot evade via a location shift.
        assert torch.count_nonzero(gradient[:,[0,1,2,4]])==0
    assert torch.count_nonzero(ag[2][:,[0,2]])==0
    padded={k:(torch.cat((v,torch.full((*v.shape[:-1],4),1e6,dtype=v.dtype)),-1) if k in ('start','end') else v) for k,v in output.items()}
    assert torch.equal(actual,runtime._timing_ownership_loss(torch,padded,rows)[0])
    assert output['modality'].grad is None
    for field in ('conditions','temporal'):
        assert parts[f'ownership_{field}_present_rows']==parts[f'ownership_{field}_absent_rows']==2


def test_full_source_owned_group_and_single_token_groups_are_finite():
    output,rows=fake_auxiliary()
    for row in rows:
        row['tokens']=row['tokens'][:1]
        for facet in (3,5):
            if row['labels']['presence'][facet]:row['labels']['spans'][facet]=(0,0)
    loss,parts=runtime._timing_ownership_loss(torch,output,rows)
    assert torch.isfinite(loss)
    loss.backward()
    assert all(torch.isfinite(output[k].grad).all() for k in ('presence','start','end'))
    assert parts['ownership_conditions_token_groups']==4


def test_condition_only_deadline_only_both_neither_supervise_exact_masks():
    output,rows=fake_auxiliary()
    for i,row in enumerate(rows):
        for facet,bit in ((3,1),(5,2)):
            row['labels']['presence'][facet]=bool(i&bit)
            row['labels']['spans'][facet]=(1,1) if i&bit else (-100,-100)
    masks=runtime._ownership_masks(rows)
    assert [(any(m['conditions']),any(m['temporal'])) for m in masks]==[(False,False),(True,False),(False,True),(True,True)]
    loss,_=runtime._timing_ownership_loss(torch,output,rows)
    assert torch.allclose(loss,independent_loss(output,rows),atol=1e-6)
    rows[0]['labels']['presence'][3]=True;rows[0]['labels']['spans'][3]=(0,0)
    with pytest.raises(ValueError,match='2present2absent'):runtime._timing_ownership_loss(torch,output,rows)


@pytest.mark.parametrize('mutation', ['pair_hash','pair_meaning','pair_id','missing_pair','block_reuse','missing_block',
    'noncomplement','modality','aux_domain','span_offset','main_overlap','tune_overlap','too_many','empty'])
def test_separate_auxiliary_inventory_mutations_fail_closed(data, mutation):
    main, tune, pairs, aux, ap, blocks = deepcopy(data)
    if mutation == 'pair_hash': ap[0]['canonical_ir_sha256'] = '0'*64
    elif mutation == 'pair_meaning': aux[1]['canonical_ir']['rules'][0]['modality'] = 'P'
    elif mutation == 'pair_id': ap[1]['pair_id'] = ap[0]['pair_id']
    elif mutation == 'missing_pair': ap.pop()
    elif mutation == 'block_reuse': blocks[1]['pair_ids'] = blocks[0]['pair_ids']
    elif mutation == 'missing_block': blocks.pop()
    elif mutation == 'noncomplement': blocks[0]['pair_ids'][1], blocks[1]['pair_ids'][0] = blocks[1]['pair_ids'][0], blocks[0]['pair_ids'][1]
    elif mutation == 'modality':
        for row in aux[:2]: row['canonical_ir']['rules'][0]['modality'] = 'P'
        ap[0]['canonical_ir_sha256'] = runtime.checkpoint_digest(aux[0]['canonical_ir'])
    elif mutation == 'aux_domain': aux[0]['domain'] = 'earlier'; aux[0]['trigger_supervised'] = False; aux[0]['trigger_span'] = None
    elif mutation == 'span_offset': aux[0]['facet_spans']['actor'][0] += 1
    elif mutation == 'main_overlap': aux[0] = deepcopy(main[0])
    elif mutation == 'tune_overlap': tune = [deepcopy(aux[0])]
    elif mutation == 'too_many': aux *= 65
    else: aux = []
    with pytest.raises(ValueError): runtime._auxiliary_data(main, tune, aux, ap, blocks)


def test_inventory_cap_is_separate_without_changing_frozen_main_limit(data):
    assert runtime.MAX_AUXILIARY_EXAMPLES == 1024 and runtime.span.MAX_EXAMPLES == 4096
    _, _, auxiliary, blocks = runtime._auxiliary_data(data[0], data[1], *data[3:])
    assert len(auxiliary) == 16 and len(blocks) == 4 and len(data[0]) == 26


def test_full_main_cap_and_separate_auxiliary_inventory_are_both_enforced(data):
    main = []
    for index in range(4097):
        row = deepcopy(data[0][index % len(data[0])])
        row['id'] += f'-capacity-{index}'
        # The suffix is deliberately outside copied spans; existing offsets remain exact.
        row['source_text'] += f' Capacity example {index}.'
        main.append(row)
    parsed, _, auxiliary, _ = runtime._auxiliary_data(main[:4096], [], *data[3:])
    assert len(parsed) == 4096 and len(auxiliary) == 16
    with pytest.raises(ValueError, match='bounded annotated'):
        runtime._auxiliary_data(main, [], *data[3:])


@pytest.mark.parametrize('mutation', ['kind','parent_hash','model_config','initial','progress','aux_count',
    'aux_hash','weight','trained_hash','nan_weight','negative_moment'])
def test_checkpoint_mutations_reject_invalid_lineage_config_progress_or_tensors(parents, data, mutation):
    cp = child(parents, data)
    if mutation in ('trained_hash','negative_moment'):
        cp = runtime.train_decoder(cp, *data, max_steps=1, max_seconds=30)['checkpoint']
    if mutation == 'kind': cp['frozen_parent_kind'] = 'facet_retention'
    elif mutation == 'parent_hash': cp['frozen_parent_checkpoint_sha256'] = '0'*64
    elif mutation == 'model_config': cp['model_config']['trigger_enabled'] = False
    elif mutation == 'initial': cp['initial_model_state_sha256'] = '0'*64
    elif mutation == 'progress': cp['progress']['auxiliary_blocks']['row_cursor'] = 1
    elif mutation == 'aux_count': cp['auxiliary_count'] = 1028
    elif mutation == 'aux_hash': cp['auxiliary_manifest_sha256'] = False
    elif mutation == 'weight': cp['training_config']['auxiliary_standard_ce_weight'] = 0
    elif mutation == 'trained_hash': cp['parent_checkpoint_sha256'] = None
    elif mutation == 'nan_weight': cp['model_state']['presence.bias'][0] = float('nan')
    else: cp['optimizer_state']['parameters']['presence.bias']['exp_avg_sq'][0] = -1
    with pytest.raises(ValueError): runtime.validate_checkpoint(cp)


def test_resume_binds_auxiliary_order_and_explicit_budgets(parents, data):
    cp = child(parents, data)
    for index in (3,4,5):
        changed = deepcopy(data); changed[index].reverse()
        with pytest.raises(ValueError, match='manifest'): runtime.train_decoder(cp, *changed, max_steps=1)
    with pytest.raises(ValueError, match='max_steps'): runtime.train_decoder(cp, *data, max_steps=201)
    zero = runtime.train_decoder(cp, *data, max_steps=0)
    assert zero['checkpoint'] == cp and not zero['report']['training_executed']
    stopped = runtime.train_decoder(cp, *data, max_steps=1, max_seconds=0)
    assert stopped['checkpoint'] == cp and stopped['report']['stopped_reason'] == 'deadline_before_batch'


def test_repaired_auxiliary_counts_cannot_resume_against_different_inventory(parents, data):
    cp = child(parents, data)
    cp.update(auxiliary_count=20, auxiliary_pair_count=10, auxiliary_block_count=5)
    cp['progress'] = runtime._progress(cp['pool_counts'], 5, 1729)
    with pytest.raises(ValueError, match='auxiliary counts'):
        runtime.train_decoder(cp, *data, max_steps=1)


def test_auxiliary_receipts_reconstruct_both_losses_from_saved_logits(parents, data):
    result = runtime.train_decoder(child(parents, data), *data, max_steps=1, max_seconds=30)
    saved = result['report']['auxiliary_loss_receipts'][0]
    parts = result['report']['batch_loss_components'][0]
    output = {k:torch.tensor(v, dtype=torch.float32) for k,v in saved['logits'].items()}
    rows = [{'id':i, 'tokens':[None]*n, 'labels':labels} for i,n,labels in
        zip(saved['ids'], saved['token_counts'], saved['labels'], strict=True)]
    role, _ = runtime._timing_ownership_loss(torch, output, rows)
    # Frozen span CE batches records before the supplied forward, so use original parsed rows.
    _, _, auxiliary, _ = runtime._auxiliary_data(data[0], data[1], *data[3:])
    by_id = {r['id']:r for r in auxiliary}
    standard = runtime.span._loss(torch, lambda *_:output, [by_id[i] for i in saved['ids']])
    assert saved['ownership_masks'] == runtime._ownership_masks(rows)
    assert saved['ownership_masks_sha256'] == runtime.checkpoint_digest(saved['ownership_masks'])
    assert float(role) == parts['timing_ownership_nll'] and float(standard) == parts['auxiliary_standard_ce']
    assert result['report']['optimizer_trajectory_independently_replayed'] is False


def test_checkpoint_roundtrip_and_inference_state_guard(parents, data, tmp_path):
    cp = child(parents, data); pin = runtime.save_checkpoint(cp, tmp_path/'checkpoint.json')
    assert runtime.load_checkpoint(pin['path'], expected_sha256=pin['sha256']) == cp
    with pytest.raises(FileExistsError): runtime.save_checkpoint(cp, tmp_path/'checkpoint.json')
    with pytest.raises(ValueError, match='hash'): runtime.load_checkpoint(pin['path'], expected_sha256='0'*64)
    decoder = runtime.TimingOwnershipDecoder(cp)
    with torch.no_grad(): next(decoder.model.parameters()).add_(1)
    with pytest.raises(ValueError, match='model state changed'): decoder.decode_formal_logic([data[3][0]['source_text']])
