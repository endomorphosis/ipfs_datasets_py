from ipfs_datasets_py.logic.intent_ir.formalize import alignment_curriculum as c,coverage_curriculum as coverage,rich_grammar as g


def parent():
    return {'samples':[{'id':'prior:'+s,'split':s,'instruction':'Save '+n,'ast':g.parse_instruction('Save '+n),'provenance':{}}for s,n in [('train','aqua report'),('validation','copper report'),('test','olive report')]]}


def test_independent_labels_parent_preserved_and_heldout_banks_disjoint():
    original=parent();result=c.build_alignment_curriculum(original)
    assert result['samples'][:3]==original['samples']
    assert result['alignment_curriculum']['new_training_rows']==768 and result['alignment_curriculum']['new_test_rows']==64
    prepared=c.prepare_alignment_training_data(result)
    assert len(prepared['new_holdouts'])==64
    train=[r for r in result['samples']if r['id']in prepared['selected_train_ids']]
    train_semantics=set().union(*(coverage._semantic_identities(r['ast'])for r in train))
    train_sources=set().union(*(coverage._source_identities(r)for r in train))
    for row in prepared['new_holdouts']:
        assert g.parse_instruction(row['instruction'])==row['ast']
        assert not coverage._semantic_identities(row['ast'])&train_semantics
        assert not coverage._source_identities(row)&train_sources
    assert {r['provenance']['object_shape']for r in prepared['new_holdouts']}==set(c.SHAPES)


def test_prior_semantic_alias_is_quarantined_even_with_surface_change():
    original=parent();row={'id':'deny','split':'test','instruction':'Save the ledger packet.',
        'ast':g.parse_instruction('Save the ledger packet.'),'provenance':{}}
    original['samples'].append(row)
    result=c.build_alignment_curriculum(original)
    assert result['alignment_curriculum']['omitted']
    assert not any(r['id'].startswith('aligned-span-v2:train:')and r['ast']==row['ast']for r in result['samples'])


def test_explicit_regression_exclusion_never_becomes_fitting_content():
    denied='Must view the binder packet.'
    result=c.build_alignment_curriculum(parent(),forbidden_sources=[denied])
    assert not any(r['instruction']==denied for r in result['samples'])
    prepared=c.prepare_alignment_training_data(result)
    assert all(p['source']!=g.model_input(denied)for p in prepared['pairs']['train'])
