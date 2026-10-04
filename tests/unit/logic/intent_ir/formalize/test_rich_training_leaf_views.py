"""Raw training-only composition leaves preserve source and held-out fences."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar as grammar
from ipfs_datasets_py.logic.intent_ir.formalize.rich_training import add_training_leaf_views, build_pairs


def row(identity, text, split='train'):
    return {'id': identity, 'instruction': text, 'split': split,
            'ast': grammar.parse_instruction(text), 'provenance': {'kind': 'authored_fixture'}}


def corpus(rows):
    return {'schema': 'intent-rich-continuation-corpus/v1', 'samples': rows,
            'metadata': {'unchanged': ['original']}}


@pytest.mark.parametrize('source,expected', [
    ('agent must read API data and operator may save `src/cache.py`.',
     ['agent must read API data', 'operator may save `src/cache.py`.']),
    ('agent must read cache or operator may save report.',
     ['agent must read cache', 'operator may save report.']),
    ('agent must read cache then operator may save report.',
     ['agent must read cache', 'operator may save report.']),
    ('agent must read cache and then operator may save report.',
     ['agent must read cache', 'operator may save report.']),
    ('if cache is not ready, agent must read report.', ['agent must read report.']),
    ('  agent must read cache  and   operator may save report. ',
     ['  agent must read cache', 'operator may save report. ']),
])
def test_exact_child_slices_never_gain_punctuation_or_normalization(source, expected):
    original = corpus([row('parent', source)])
    before = deepcopy(original)
    result = add_training_leaf_views(original)
    assert original == before
    assert result['samples'][:1] == original['samples']
    added = result['samples'][1:]
    assert [r['instruction'] for r in added] == expected
    for r in added:
        provenance = r['provenance']
        span = provenance['source_span']
        assert r['instruction'] == source[span['start_char']:span['end_char']]
        assert r['instruction'].encode() == source.encode()[span['start_byte']:span['end_byte']]
        assert r['ast'] == grammar.parse_instruction(r['instruction'])
        assert provenance['parent_id'] == 'parent'
        assert provenance['parent_instruction'] == source
        assert provenance['synthetic_punctuation'] is False
        assert provenance['model_predictions_used'] is False
        assert r['split'] == provenance['parent_split'] == 'train'
    result['samples'][0]['provenance']['kind'] = 'changed'
    assert original == before


def test_heldout_rows_and_their_atomic_views_never_supply_training_examples():
    train = row('train', 'agent must read cache and operator may save report.')
    validation = row('validation', 'agent must read cache.', 'validation')
    test = row('test', 'operator may save report then agent should check heldoutdata.', 'test')
    original = corpus([train, validation, test])
    result = add_training_leaf_views(original)
    assert result['samples'] == original['samples']
    evidence = result['training_leaf_views']
    assert evidence['candidate_train_leaves'] == 2
    assert evidence['added_train_leaves'] == 0
    assert evidence['omitted_counts'] == {'heldout_source_or_semantic_collision': 2}
    assert not evidence['heldout_rows_added_or_modified']


def test_duplicate_views_are_not_oversampled_and_existing_rows_remain():
    original = corpus([
        row('atom', 'agent must read cache'),
        row('first', 'agent must read cache and operator may save report.'),
        row('second', 'agent must read cache or operator may save report.'),
    ])
    result = add_training_leaf_views(original)
    assert result['samples'][:3] == original['samples']
    assert len(result['samples']) == 4
    assert result['samples'][-1]['instruction'] == 'operator may save report.'
    assert result['training_leaf_views']['omitted_counts'] == {'duplicate_existing_or_added_training_view': 3}
    pairs = build_pairs(result['samples'])
    identities = {(p['direction'], p['source']) for p in pairs}
    assert len(identities) == len(pairs)
    assert add_training_leaf_views(result)['samples'] == result['samples']


def test_heldout_lexical_case_and_path_content_do_not_enter_added_rows():
    original = corpus([
        row('train', 'if cache is ready, agent must read API data.'),
        row('test', 'if reserved is ready, operator should validate `heldout/Secret.py`.', 'test'),
        row('val', 'system must inspect ForbiddenHeldoutLabel.', 'validation'),
    ])
    result = add_training_leaf_views(original)
    assert result['samples'][:3] == original['samples']
    assert len(result['samples']) == 4
    leaf = result['samples'][-1]
    assert leaf['instruction'] == 'agent must read API data.'
    assert leaf['provenance']['parent_id'] == 'train'
    assert 'heldout' not in str(leaf).lower()
    assert 'ForbiddenHeldoutLabel' not in str(leaf)


@pytest.mark.parametrize('mutation', ['duplicate_id', 'wrong_parent_label', 'unknown_split'])
def test_conflicting_parent_contracts_rejected_without_mutation(mutation):
    original = corpus([row('first', 'agent must read cache and operator may save report.')])
    if mutation == 'duplicate_id':
        original['samples'].append(deepcopy(original['samples'][0]))
    elif mutation == 'wrong_parent_label':
        original['samples'][0]['ast']['left']['modality'] = 'prohibited'
    else:
        original['samples'][0]['split'] = 'unspecified'
    before = deepcopy(original)
    with pytest.raises(ValueError):
        add_training_leaf_views(original)
    assert original == before
