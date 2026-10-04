from copy import deepcopy

import pytest

from scripts.ops.legal_ir import summarize_legal_role_span_rehearsal_experiment_v2 as q


def clause_fixture(count=192, exact=0):
    sources, targets, predictions = [], [], []
    for index in range(count):
        text = f'The unit{index} shall file notice{index}.'
        source = {'id': str(index), 'source_text': text, 'source_sha256': q.boundary.text_sha(text)}
        rule = {'modality': 'OPF'[index % 3], 'actor': f'The unit{index}', 'action': 'file',
                'object': f'notice{index}', 'conditions': ['permit active'] if index & 1 else [],
                'exceptions': ['record sealed'] if index & 2 else [],
                'temporal': ['within 3 days'] if index & 4 else []}
        canonical = {'rules': [rule]}
        target = {'id': str(index), 'source_text': text, 'canonical_ir': canonical}
        prediction = {'source_sha256': source['source_sha256'],
                      'status': 'decoded' if index < exact else 'abstained',
                      'canonical_ir': deepcopy(canonical) if index < exact else None}
        sources.append(source); targets.append(target); predictions.append(prediction)
    return {'rows': predictions}, sources, targets


def measured(count=192, exact=0):
    return q.clause_metrics(*clause_fixture(count, exact))['metrics']


def nested(count):
    return {'count': count, 'fullrule_exact': 0,
            'modality_fullrule': {m: {'count': count // 3, 'exact': 0} for m in 'OPF'},
            **{kind: {label: {'count': count // 2, 'exact': 0} for label in ('present', 'absent')}
               for kind in ('condition_facet', 'temporal_facet', 'condition_fullrule', 'temporal_fullrule')}}


def doc_metrics(supported=4, unsupported=2, exact=(), accepted=()):
    rows = [{'id': f's{i}', 'supported': True, 'joint_exact': i in exact, 'composed': i in exact}
            for i in range(supported)]
    rows += [{'id': f'u{i}', 'supported': False, 'joint_exact': False, 'composed': i in accepted}
             for i in range(unsupported)]
    return q.document_metrics(rows)


def stage_fixture():
    from scripts.ops.legal_ir import run_legal_condition_rehearsal_experiment as historical
    result = {key: 0 for key in historical.metric_keys()}
    result.update(retention_metrics={panel: nested(192) for panel in ('facet', 'temporal')},
                  condition_metrics=nested(96), new_single_metrics=measured(),
                  prior_condition_metrics=measured(),
                  old_atom_oracle_metrics={panel: measured(120) for panel in q.ATOM_PANELS},
                  oracle_document_metrics={panel: doc_metrics(4, 0) for panel in q.GATE_DOCUMENT_PANELS},
                  fixed_document_metrics={panel: {policy: doc_metrics() for policy in q.PRIMARY_BOUNDARIES}
                                          for panel in q.GATE_DOCUMENT_PANELS}, steps=100)
    return result


def test_all_reject_does_not_gain_absent_facet_accuracy():
    value = measured()
    assert value['count'] == 192 and value['decoded'] == value['actor_exact'] == value['fullrule_exact'] == 0
    assert all(cell['exact'] == 0 for facet in value['optional_facet'].values() for cell in facet.values())


def test_actor_swap_and_exception_omission_separate_from_fullrule():
    generation, sources, targets = clause_fixture(12, 12)
    generation['rows'][0]['canonical_ir']['rules'][0]['actor'] = 'different actor'
    generation['rows'][2]['canonical_ir']['rules'][0]['exceptions'] = []
    result = q.clause_metrics(generation, sources, targets)
    assert result['metrics']['fullrule_exact'] == 10
    assert result['metrics']['actor_exact'] == 11
    assert result['metrics']['optional_facet']['exceptions']['present']['exact'] == 5


def test_repeated_text_rule_occurrences_keep_distinct_denominators():
    generation, sources, targets = clause_fixture(2, 2)
    sources[1] = {**sources[0], 'id': '1'}
    targets[1] = {**targets[0], 'id': '1'}
    generation['rows'][1] = deepcopy(generation['rows'][0])
    assert q.clause_metrics(generation, sources, targets)['metrics']['fullrule_exact'] == 2


@pytest.mark.parametrize('mutation', ['drop', 'duplicate', 'source', 'reference_source', 'status', 'abstain_with_rule'])
def test_clause_reference_or_prediction_corruption_rejected(mutation):
    generation, sources, targets = clause_fixture(4, 4)
    if mutation == 'drop': generation['rows'].pop()
    if mutation == 'duplicate': sources[1]['id'] = sources[0]['id']
    if mutation == 'source': generation['rows'][0]['source_sha256'] = 'f' * 64
    if mutation == 'reference_source': targets[0]['source_text'] += ' altered'
    if mutation == 'status': generation['rows'][0]['status'] = 'compiled'
    if mutation == 'abstain_with_rule': generation['rows'][0]['status'] = 'abstained'
    with pytest.raises(ValueError): q.clause_metrics(generation, sources, targets)


def test_guard_count_cancellation_does_not_pass_source_subset_gate():
    parent = doc_metrics(4, 2, exact=(0,), accepted=(0,))
    candidate = doc_metrics(4, 2, exact=(0, 1), accepted=(1,))
    assert len(parent['unsupported_accepted_ids']) == len(candidate['unsupported_accepted_ids'])
    assert not q.retains_documents(candidate, parent)
    assert q.document_churn(candidate, parent)['new_unsupported_accepts'] == ['u1']


def test_supported_source_churn_is_reported_even_when_net_retained():
    parent = doc_metrics(4, 2, exact=(0, 1))
    candidate = doc_metrics(4, 2, exact=(1, 2))
    assert q.retains_documents(candidate, parent)
    assert q.document_churn(candidate, parent) == {
        'supported_wins': ['s2'], 'supported_losses': ['s0'],
        'new_unsupported_accepts': [], 'removed_unsupported_accepts': []}


@pytest.mark.parametrize('mutation', ['count', 'duplicate', 'wrong_partition', 'wrong_exact', 'boolean', 'extra'])
def test_document_gate_metric_corruptions_rejected(mutation):
    value = doc_metrics(4, 2, exact=(0,), accepted=(0,))
    if mutation == 'count': value['count'] -= 1
    if mutation == 'duplicate': value['supported_ids'].append('s0')
    if mutation == 'wrong_partition': value['unsupported_accepted_ids'] = ['s1']
    if mutation == 'wrong_exact': value['joint_exact_ids'] = ['u0']
    if mutation == 'boolean': value['joint_exact'] = True
    if mutation == 'extra': value['compiled'] = True
    with pytest.raises(ValueError): q.validate_document_metrics(value)


def test_unchanged_candidate_not_eligible_without_new_semantic_gain():
    parent = stage_fixture()
    assert not q.eligible(deepcopy(parent), parent)


def test_new_single_gain_with_every_retention_metric_preserved_is_eligible():
    parent = stage_fixture(); candidate = deepcopy(parent)
    candidate['new_single_metrics'] = measured(exact=1)
    assert q.eligible(candidate, parent)


def test_oracle_document_gain_alone_can_qualify_without_claiming_scope_gain():
    parent = stage_fixture(); candidate = deepcopy(parent)
    candidate['oracle_document_metrics']['new'] = doc_metrics(4, 0, exact=(0,))
    assert q.eligible(candidate, parent)


@pytest.mark.parametrize('panel', list(q.GATE_DOCUMENT_PANELS))
def test_any_new_guard_acceptance_blocks_candidate_on_each_panel(panel):
    parent = stage_fixture(); candidate = deepcopy(parent)
    candidate['new_single_metrics'] = measured(exact=1)
    candidate['fixed_document_metrics'][panel]['distill'] = doc_metrics(4, 2, accepted=(0,))
    assert not q.eligible(candidate, parent)


def test_exposed_atom_exception_regression_cannot_hide_behind_new_tune_gain():
    parent = stage_fixture(); candidate = deepcopy(parent)
    parent['old_atom_oracle_metrics']['atom_fresh'] = measured(120, 3)
    candidate['old_atom_oracle_metrics']['atom_fresh'] = measured(120, 3)
    candidate['old_atom_oracle_metrics']['atom_fresh']['optional_facet']['exceptions']['present']['exact'] -= 1
    # Preserve full-rule totals by turning this into an additional independently decoded wrong-rule case.
    parent['old_atom_oracle_metrics']['atom_fresh']['fullrule_exact'] = 2
    parent['old_atom_oracle_metrics']['atom_fresh']['modality_fullrule']['F']['exact'] = 0
    candidate['old_atom_oracle_metrics']['atom_fresh']['fullrule_exact'] = 2
    candidate['old_atom_oracle_metrics']['atom_fresh']['modality_fullrule']['F']['exact'] = 0
    candidate['new_single_metrics'] = measured(exact=1)
    assert not q.eligible(candidate, parent)


def test_legacy_minus_one_tolerance_preserved_but_not_weakened():
    parent = stage_fixture(); candidate = deepcopy(parent)
    parent['tuning_earlier_exact'] = 5
    candidate['tuning_earlier_exact'] = 4
    candidate['new_single_metrics'] = measured(exact=1)
    assert q.eligible(candidate, parent)
    candidate['tuning_earlier_exact'] = 3
    assert not q.eligible(candidate, parent)


def test_stage_rank_is_singles_first_then_oracle_then_fixed_policies():
    parent = stage_fixture(); first = deepcopy(parent); second = deepcopy(parent)
    first['new_single_metrics'] = measured(exact=2)
    second['new_single_metrics'] = measured(exact=1)
    second['oracle_document_metrics']['new'] = doc_metrics(4, 0, exact=(0, 1, 2, 3))
    first['steps'] = 100; second['steps'] = 200
    assert q.select_stage([first, second], parent) is first
    second = deepcopy(first); second['steps'] = 200
    assert q.select_stage([first, second], parent) is first


def loss_fixture(torch, seed=4):
    generator = torch.Generator().manual_seed(seed)
    output = {key: torch.randn(shape, generator=generator, dtype=torch.float64, requires_grad=True)
              for key, shape in {'modality': (4, 3), 'presence': (4, 4, 2),
                                 'start': (4, 6, 10), 'end': (4, 6, 10)}.items()}
    records = []
    for i in range(4):
        present = [True, True, True, i < 2, i % 2 == 0, i in (0, 3)]
        spans = [[0, 1] if flag else [-100, -100] for flag in present]
        records.append({'id': str(i), 'tokens': [{}] * (7 + i),
                        'labels': {'modality': i % 3, 'presence': present, 'spans': spans}})
    return output, records


def test_random_float64_role_oracle_matches_runtime_values_and_gradients():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_role_span_rehearsal as runtime
    for seed in range(50):
        output, records = loss_fixture(torch, seed)
        expected, _ = q.role_loss_oracle(torch, output, records)
        actual, _ = runtime._role_rehearsal_loss(torch, output, records)
        assert torch.allclose(expected, actual, atol=1e-12, rtol=1e-12)
        params = (output['presence'], output['start'], output['end'])
        wanted = torch.autograd.grad(expected, params, retain_graph=True)
        got = torch.autograd.grad(actual, params)
        assert all(torch.allclose(a, b, atol=1e-12, rtol=1e-12) for a, b in zip(wanted, got))


def test_role_oracle_excludes_padding_absent_endpoints_and_unrelated_heads():
    import torch
    output, records = loss_fixture(torch)
    value, _ = q.role_loss_oracle(torch, output, records)
    gradients = torch.autograd.grad(value, (output['modality'], output['presence'], output['start'], output['end']), allow_unused=True)
    assert gradients[0] is None
    assert torch.count_nonzero(gradients[1][:, 0]) == 0  # optional object is outside new auxiliary
    for i, record in enumerate(records):
        for g in gradients[2:]:
            assert torch.count_nonzero(g[i, :, len(record['tokens']):]) == 0
            assert torch.count_nonzero(g[i, 1:3]) == 0  # action/object heads unchanged by auxiliary
            for index in (3, 4, 5):
                if not record['labels']['presence'][index]: assert torch.count_nonzero(g[i, index]) == 0


def test_standard_auxiliary_oracle_matches_frozen_seven_component_loss():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_formula as span
    output, records = loss_fixture(torch)
    for record in records:
        record['latent'] = []
        record['tokens'] = [{'byte_ids': [1]} for _ in record['tokens']]
    expected = q.standard_auxiliary_loss_oracle(torch, output, records)
    actual = span._loss(torch, lambda *_: output, records)
    assert torch.allclose(actual, expected, atol=1e-12, rtol=1e-12)
    wanted = torch.autograd.grad(expected, tuple(output.values()), retain_graph=True)
    got = torch.autograd.grad(actual, tuple(output.values()))
    assert all(torch.allclose(a, b, atol=1e-12, rtol=1e-12) for a, b in zip(wanted, got))


def test_auxiliary_requires_each_optional_facet_balanced():
    import torch
    output, records = loss_fixture(torch)
    records[0]['labels']['presence'][3] = False
    with pytest.raises(ValueError): q.role_loss_oracle(torch, output, records)


def receipt_fixture():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_role_span_rehearsal as runtime
    output, records = loss_fixture(torch)
    _, parts = runtime._role_rehearsal_loss(torch, output, records)
    parts = {key: float(value.detach()) for key, value in parts.items()}
    parts['auxiliary_standard_ce'] = float(q.standard_auxiliary_loss_oracle(torch, output, records).detach())
    receipt = {'optimizer_step': 17, 'ids': [row['id'] for row in records],
               'token_counts': [len(row['tokens']) for row in records],
               'labels': [deepcopy(row['labels']) for row in records],
               'logits': {key: value.detach().tolist() for key, value in output.items()}}
    return receipt, records, parts


def test_auxiliary_receipt_all_values_recomputed_independently():
    receipt, records, parts = receipt_fixture()
    audit = q.verify_auxiliary_receipt(receipt, records, parts, step=17)
    assert audit['rows'] == 4 and audit['maximum_numerical_error'] < 1e-12
    assert audit['logits_generated_by_model_independently_replayed'] is False


@pytest.mark.parametrize('mutation', ['step', 'ids', 'labels', 'tokens', 'shape', 'nan', 'part', 'count'])
def test_auxiliary_receipt_corruption_rejected(mutation):
    receipt, records, parts = receipt_fixture()
    if mutation == 'step': receipt['optimizer_step'] += 1
    if mutation == 'ids': receipt['ids'].reverse()
    if mutation == 'labels': receipt['labels'][0]['spans'][0] = [1, 2]
    if mutation == 'tokens': receipt['token_counts'][0] -= 1
    if mutation == 'shape': receipt['logits']['start'][0][0].pop()
    if mutation == 'nan': receipt['logits']['presence'][0][0][0] = float('nan')
    if mutation == 'part': parts['aux_exceptions_present_endpoint_ce'] += .1
    if mutation == 'count': parts['aux_temporal_negative_rows'] = 3
    with pytest.raises(ValueError): q.verify_auxiliary_receipt(receipt, records, parts, step=17)


def test_auxiliary_blocks_cycle_all144_before_repeating_without_changing_main_schedule():
    pools = {'earlier': [f'e{i}' for i in range(12)], 'historical_new': [f'n{i}' for i in range(18)],
             'positive_pairs': [[f'p{i}a', f'p{i}b'] for i in range(8)],
             'negative_pairs': [[f'n{i}a', f'n{i}b'] for i in range(8)]}
    blocks = [{'block_id': str(i), 'pair_ids': [f'a{i}', f'b{i}']} for i in range(144)]
    rows = [[f'aux{i}-{j}' for j in range(4)] for i in range(144)]
    traces = [q.expected_batch(1730, step, pools, blocks, rows) for step in range(1, 201)]
    assert len({row['auxiliary_block_id'] for row in traces[:144]}) == 144
    assert len({row['auxiliary_block_id'] for row in traces[144:]}) == 56
    for step, row in enumerate(traces, 1):
        actual = {key: deepcopy(row[key]) for key in ('optimizer_step', 'indices_by_pool', 'ids', 'pairs')}
        actual['indices_by_pool'].pop('auxiliary_block')
        assert actual == q.legacy.prior.expected_batch(1730, step, pools)


@pytest.mark.parametrize('count', [1, 48, 96, 192])
def test_variable_document_lowering_keeps_actual_abstention_denominator(count):
    sources = [{'candidate_id': str(i), 'source_text': f'Case {i}.',
                'source_sha256': q.boundary.text_sha(f'Case {i}.')} for i in range(count)]
    rows = [{'candidate_id': source['candidate_id'], 'source_sha256': source['source_sha256'],
             'composition': None, 'status': 'abstained', 'reason': 'unit'} for source in sources]
    result = q.document_selection(rows, sources, toolchain='unused-no-native-call')
    assert result['source_count'] == count and len(result['excluded']) == count and result['rows'] == []
    assert [row['candidate_id'] for row in result['excluded']] == [row['candidate_id'] for row in sources]


def test_document_lowering_cannot_pad_with_duplicate_or_fake_source_ids():
    source = {'candidate_id': 'one', 'source_text': 'Case.', 'source_sha256': q.boundary.text_sha('Case.')}
    row = {'candidate_id': 'one', 'source_sha256': source['source_sha256'], 'composition': None,
           'status': 'abstained', 'reason': 'unit'}
    with pytest.raises(ValueError): q.document_selection([row, row], [source, source], toolchain='unused')


def oracle_fixture():
    body = 'The council shall file notice.'
    text = body + '\n' + body
    doc = {'candidate_id': 'document-unit', 'source_text': text, 'source_sha256': q.boundary.text_sha(text)}
    sources, mapping = [], []
    for index, start in enumerate((0, len(body)+1)):
        end = start + len(body); source_sha = q.boundary.text_sha(body)
        identity = 'oracle-' + q.digest([doc['candidate_id'], index, start, end, source_sha])
        sources.append({'id': identity, 'source_text': body})
        mapping.append({'id': identity, 'document_id': doc['candidate_id'], 'document_source_sha256': doc['source_sha256'],
                        'source_sha256': source_sha, 'char_start': start, 'char_end': end, 'occurrence_index': index})
    plan = q.retained.compose.prepare_source_plan(doc, [{'clause_id': row['id'], 'char_start': row['char_start'],
            'char_end': row['char_end'], 'scope': q.retained.compose.FLAT_SCOPE} for row in mapping])
    return sources, mapping, [doc], {doc['candidate_id']: plan}


def test_supplied_boundary_pack_repeats_are_occurrences_not_deduplicated_rules():
    sources, mapping, documents, plans = oracle_fixture()
    result = q.verify_oracle_sources(sources, mapping, documents, plans)
    assert result['occurrences'] == 2 and result['documents'] == 1
    assert result['oracle_segmentation_and_supported_membership_supplied'] is True
    assert result['learned_boundary_accuracy_claimed'] is result['semantic_reference_access'] is False


@pytest.mark.parametrize('mutation', ['drop', 'offset', 'source', 'doc_hash', 'ordinal', 'opaque_id', 'plan', 'order'])
def test_oracle_source_pack_tampering_rejected_without_gold(mutation):
    sources, mapping, documents, plans = oracle_fixture()
    if mutation == 'drop': sources.pop(); mapping.pop()
    if mutation == 'offset': mapping[0]['char_end'] -= 1
    if mutation == 'source': sources[0]['source_text'] += 'X'
    if mutation == 'doc_hash': mapping[0]['document_source_sha256'] = '0'*64
    if mutation == 'ordinal': mapping[1]['occurrence_index'] = 0
    if mutation == 'opaque_id': mapping[0]['id'] = sources[0]['id'] = 'encoded-supported-label'
    if mutation == 'plan': plans['document-unit']['clauses'][1]['source_text'] = 'invented.'
    if mutation == 'order': mapping.reverse()
    with pytest.raises(ValueError): q.verify_oracle_sources(sources, mapping, documents, plans)


def test_scope_invariance_checks_raw_decisions_even_when_final_guards_reject():
    import math
    text = 'The council shall file notice.'
    source = {'candidate_id': 'unit', 'source_text': text, 'source_sha256': q.boundary.text_sha(text)}
    row = {'candidate_id': 'unit', 'source_sha256': source['source_sha256'], 'scope_logits': [0., 2.],
           'scope_supported_probability': 1/(1+math.exp(-2)), 'raw_learned_scope_supported': True,
           'status': 'abstained', 'reason': 'declared_surface_policy_unsupported_scope'}
    other = deepcopy(row); other['status'] = 'segmented'; other['reason'] = None
    audit = q.verify_scope_invariance({'rows': [row]}, {'rows': [other]}, [source])
    assert audit['scope_training_updates'] == 0 and audit['all_raw_scope_logits_and_decisions_exactly_equal'] is True
    other['scope_logits'] = [0., 3.]
    other['scope_supported_probability'] = 1/(1+math.exp(-3))
    with pytest.raises(ValueError): q.verify_scope_invariance({'rows': [row]}, {'rows': [other]}, [source])


def test_oracle_compilation_is_not_fidelity_and_planned_status_is_not_abstention(monkeypatch):
    rows = [{'candidate_id': identity, 'segmentation_status': 'planned', 'segmentation_learned': False,
             'supplied_oracle_segmentation': True, 'clause_generation': {'rows': []}, 'composition': {'fixture': True}}
            for identity in ('a', 'b')]
    measured = {'rows': [{'id': identity, 'supported': True, 'exact': identity == 'a', 'composed': True,
                         'canonical_rule_list_exact': identity == 'a', 'occurrence_boundaries_exact': True}
                        for identity in ('a', 'b')]}
    monkeypatch.setattr(q.retained, 'score_documents', lambda *_: measured)
    selection = {'rows': [{'candidate': {'candidate_id': identity}} for identity in ('a', 'b')],
                 'excluded': [], 'source_count': 2}
    batches = [{'candidate_ids': ['a', 'b'], 'build_passed': True, 'backend_executed': True}]
    score = q.oracle_document_score({'rows': rows, 'supplied_oracle_segmentation': True},
        [{'candidate_id': identity} for identity in ('a', 'b')], [{'supported': True}, {'supported': True}],
        selection=selection, batches=batches)
    assert score['metrics']['joint_exact'] == 1 and score['builds']['built'] == 2
    assert score['builds']['built_reference_mismatch'] == 1
    assert score['terminal_stages'] == {'built_joint_exact': 1, 'built_reference_mismatch': 1}
    assert score['learned_scope_or_boundary_accuracy_claimed'] is False


def test_auxiliary_receipt_serialized_json_labels_match_runtime_tuple_spans():
    import json
    receipt, records, parts = receipt_fixture()
    for row in records:
        row['labels']['spans'] = [tuple(span) for span in row['labels']['spans']]
    serialized = json.loads(json.dumps(receipt))
    assert q.verify_auxiliary_receipt(serialized, records, parts, step=17)['rows'] == 4
    serialized['labels'][0]['spans'][0][0] += 1
    with pytest.raises(ValueError):
        q.verify_auxiliary_receipt(serialized, records, parts, step=17)
