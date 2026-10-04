"""Separate authored rehearsal, exact parents, balanced losses and resumption."""
from copy import deepcopy
from pathlib import Path
import runpy

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_role_span_rehearsal as runtime
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


def child(parents, data, enabled=True, objective='role_rehearsal'):
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
    decoder = runtime.RoleSpanRehearsalDecoder(cp)
    assert decoder.decode_formal_logic(texts)['rows'] == parent_decoder(parent).decode_formal_logic(texts)['rows']
    cp['model_state'] = {}; assert decoder.checkpoint['model_state'] == parent['model_state']


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('objective', ['base', 'role_rehearsal'])
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
            (.5 if objective == 'role_rehearsal' else 0)*component['role_rehearsal_ce'], abs=1e-6)
        assert all(component[f'aux_{f}_positive_rows'] == component[f'aux_{f}_negative_rows'] == 2
            for f in ('conditions', 'exceptions', 'temporal'))
    assert full['report']['auxiliary_source_exposures'] == 20
    assert full['report']['teacher_state_sha256_before'] == full['report']['teacher_state_sha256_after']
    if not enabled: assert all(v == 0 for v in full['report']['auxiliary_gradient_norm_max'].values())


@pytest.mark.parametrize('enabled', [False, True])
def test_base_really_supervises_same_auxiliary_rows_and_exact_common_gradients(parents, data, enabled):
    base = child(parents, data, enabled, 'base'); target = child(parents, data, enabled)
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
    actual, parts, _ = runtime._loss(torch, model, teacher, batch, aux_batch, base['model_config'], 'base')
    old, _ = facet._loss(torch, model, teacher, batch, base['model_config'], 'facet_retention')
    aux_standard = runtime.span._loss(torch, model, aux_batch)
    expected = old + .25*aux_standard
    assert torch.equal(actual, expected) and parts['weighted_role_rehearsal'] == 0
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


def test_role_loss_matches_independent_formula_and_gradients_only_target_heads():
    output, rows = fake_auxiliary()
    loss, parts = runtime._role_rehearsal_loss(torch, output, rows)
    ce = torch.nn.functional.cross_entropy
    actor = sum(ce(output[k][:, 0], torch.zeros(4, dtype=torch.long)) for k in ('start','end'))/2
    expected = [actor]
    for optional, facet_index in ((1,3), (2,4), (3,5)):
        positive = ce(output['presence'][:2, optional], torch.ones(2, dtype=torch.long))
        negative = ce(output['presence'][2:, optional], torch.zeros(2, dtype=torch.long))
        endpoints = sum(ce(output[k][:2, facet_index], torch.ones(2, dtype=torch.long)) for k in ('start','end'))/2
        expected.append(((positive+negative)/2+endpoints)/2)
    assert torch.allclose(loss, torch.stack(expected).mean(), atol=1e-7, rtol=0)
    loss.backward()
    for key in ('start','end'):
        assert output[key].grad[:, 0].abs().sum() > 0
        assert output[key].grad[:2, 3:].abs().sum() > 0
        assert torch.count_nonzero(output[key].grad[2:, 3:]) == 0
        assert torch.count_nonzero(output[key].grad[:, 1:3]) == 0
    assert output['presence'].grad[:, 1:].abs().sum() > 0
    assert torch.count_nonzero(output['presence'].grad[:, 0]) == 0
    assert output['modality'].grad is None


def test_absent_endpoints_and_padding_have_no_role_loss_influence():
    output, rows = fake_auxiliary(); before, _ = runtime._role_rehearsal_loss(torch, output, rows)
    with torch.no_grad():
        for key in ('start', 'end'): output[key][2:, 3:] *= 100
    after, _ = runtime._role_rehearsal_loss(torch, output, rows)
    assert torch.equal(before, after)
    padded = {k:(torch.cat((v, torch.full((*v.shape[:-1], 4), 1e6)), -1) if k in ('start','end') else v)
        for k,v in output.items()}
    padding_loss, _ = runtime._role_rehearsal_loss(torch, padded, rows)
    assert torch.equal(after, padding_loss)
    rows[0]['labels']['presence'][3] = False
    with pytest.raises(ValueError, match='2present2absent'):
        runtime._role_rehearsal_loss(torch, output, rows)


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
    role, _ = runtime._role_rehearsal_loss(torch, output, rows)
    # Frozen span CE batches records before the supplied forward, so use original parsed rows.
    _, _, auxiliary, _ = runtime._auxiliary_data(data[0], data[1], *data[3:])
    by_id = {r['id']:r for r in auxiliary}
    standard = runtime.span._loss(torch, lambda *_:output, [by_id[i] for i in saved['ids']])
    assert float(role) == parts['role_rehearsal_ce'] and float(standard) == parts['auxiliary_standard_ce']
    assert result['report']['optimizer_trajectory_independently_replayed'] is False


def test_checkpoint_roundtrip_and_inference_state_guard(parents, data, tmp_path):
    cp = child(parents, data); pin = runtime.save_checkpoint(cp, tmp_path/'checkpoint.json')
    assert runtime.load_checkpoint(pin['path'], expected_sha256=pin['sha256']) == cp
    with pytest.raises(FileExistsError): runtime.save_checkpoint(cp, tmp_path/'checkpoint.json')
    with pytest.raises(ValueError, match='hash'): runtime.load_checkpoint(pin['path'], expected_sha256='0'*64)
    decoder = runtime.RoleSpanRehearsalDecoder(cp)
    with torch.no_grad(): next(decoder.model.parameters()).add_(1)
    with pytest.raises(ValueError, match='model state changed'): decoder.decode_formal_logic([data[3][0]['source_text']])
