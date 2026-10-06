"""Pure prospective fixtures; no encoders, checkpoints, parsers, or proofs."""
from collections import Counter
from copy import deepcopy
import json

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import prospective_normative_development as subject


def bank(offsets, prefix, codec):
    b = subject.base
    rows = []
    for offset in offsets:
        for index, actor in enumerate(b.ACTORS):
            action = b.ACTIONS[(index+offset) % 5]
            for obj in b.OBJECTS:
                for modality in b.MODALITIES:
                    target = dict(rules=[dict(actor=actor, action=action, object=obj,
                        modality=modality, conditions=[], exceptions=[], temporal=[])])
                    for style in range(2):
                        modal = ({"O":"must", "P":"may", "F":"must not"} if style == 0
                            else {"O":"is required to", "P":"is allowed to", "F":"is forbidden to"})[modality]
                        rows.append(dict(id=prefix+":"+str(len(rows)),
                            source_text=f"The {actor} {modal} {action} the {obj}.",
                            target_ids=b._encode(target, codec)))
    return rows


def inputs():
    codec = dict(schema="typed-json-lexical/v1", target_vocabulary=list(subject.base.VOCABULARY))
    train = bank(range(3), "synthetic-train", codec)
    validation = bank([3], "synthetic-validation", codec)
    prior = {name: [dict(id="fixture:"+name, source_text="Unused literal inventory "+name+".")]
        for name in subject.REQUIRED_PRIOR_DATASETS}
    prior["original_train_bank"] = [{k:r[k] for k in ("id", "source_text")} for r in train]
    prior["raw_validation"] = [{k:r[k] for k in ("id", "source_text")} for r in validation]
    return dict(training_bank=train, validation_bank=validation,
        prior_sources_by_dataset=prior, codec=codec, sealed_recipe_sha256="a"*64,
        validate_rule=lambda value: dict(valid=True, canonical_ir=value))


def test_complete_separate_sources_references_and_previously_exposed_provenance():
    args = inputs(); before = deepcopy(args); result = subject.build(**args)
    assert args == before
    rows, refs, receipt = (result[k] for k in ("source_rows", "references", "receipt"))
    assert len(rows) == len(refs) == 60
    assert Counter(r['template'] for r in refs) == dict.fromkeys(subject.TEMPLATES, 30)
    assert Counter(r['target']['rules'][0]['modality'] for r in refs) == {"O":20,"P":20,"F":20}
    for row, ref in zip(rows, refs):
        assert set(row) == {"id", "source_text"}
        assert row == {k:ref[k] for k in row}
        assert ref['split'] == subject.ROLE and ref['clause_count'] == 1
        assert ref['label_provenance'] == 'authored_development'
        assert ref['original_meanings_previously_exposed'] is True
        assert all(ref[k] is False for k in subject.FALSE)
        rule = ref['target']['rules'][0]
        assert row['source_text'] == subject.sentence(ref['template'], rule)
        assert json.loads(''.join(subject.base.VOCABULARY[i] for i in ref['target_ids'][1:-1])) == ref['target']
        assert ref['target_sha256'] == subject.digest(ref['target'])
        assert ref['target_ids_sha256'] == subject.digest(ref['target_ids'])
        d = ref['derivations'][0]
        assert d['rule_sha256'] == subject.digest(rule)
        assert len(d['original_validation_sources']) == 2
        assert all(x['id'].startswith('synthetic-validation:') for x in d['original_validation_sources'])
    assert receipt['source_rows_sha256'] == subject.digest(rows)
    assert receipt['references_sha256'] == subject.digest(refs)
    assert receipt['actor_action_disjointness_checked'] is True
    assert not set(map(tuple, receipt['validation_actor_action_groups'])).intersection(
        map(tuple, receipt['original_train_actor_action_groups']))
    assert all(receipt[k] is False for k in subject.FALSE)
    assert receipt['lifecycle_seal_verified'] is False
    assert receipt['receipt_sha256'] == subject.digest({k:v for k,v in receipt.items() if k != 'receipt_sha256'})


@pytest.mark.parametrize('dataset', subject.REQUIRED_PRIOR_DATASETS)
def test_every_declared_source_inventory_is_required(dataset):
    args = inputs(); del args['prior_sources_by_dataset'][dataset]
    with pytest.raises(ValueError, match='all declared prior'): subject.build(**args)


@pytest.mark.parametrize('normalized', [False, True])
@pytest.mark.parametrize('dataset', subject.REQUIRED_PRIOR_DATASETS)
def test_every_exclusion_checks_whole_inventory_without_filtering(dataset, normalized):
    args = inputs(); first = subject.build(**args)['source_rows'][0]
    text = first['source_text']
    if normalized: text = text.swapcase().replace(' ', '\t  ')
    args['prior_sources_by_dataset'][dataset].append(dict(id='collision', source_text=text))
    with pytest.raises(ValueError, match='wording overlaps prior'): subject.build(**args)


def test_clause_inside_prior_paragraph_is_also_excluded():
    args = inputs(); text = subject.build(**args)['source_rows'][0]['source_text']
    args['prior_sources_by_dataset']['composition64'].append(
        dict(id='compound-collision', source_text='Other source.\n\n'+text+'\n\nThird source.'))
    with pytest.raises(ValueError, match='wording overlaps prior'): subject.build(**args)


@pytest.mark.parametrize('role', ['validation_bank', 'training_bank'])
@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'boolean_token', 'unknown_token',
    'extra_input', 'missing_rule_field', 'noncanonical', 'non_single', 'nonempty_qualifier'])
def test_invalid_original_bank_never_pruned_or_repaired(role, mutation):
    args = inputs(); rows = args[role]
    if mutation == 'missing': rows.pop()
    elif mutation == 'duplicate': rows[1] = deepcopy(rows[0])
    elif mutation == 'boolean_token': rows[0]['target_ids'][0] = True
    elif mutation == 'unknown_token': rows[0]['target_ids'][3] = 32
    elif mutation == 'extra_input': rows[0]['input'] = [0.0]*384
    else:
        target = json.loads(''.join(subject.base.VOCABULARY[i] for i in rows[0]['target_ids'][1:-1]))
        if mutation == 'missing_rule_field': del target['rules'][0]['temporal']
        elif mutation == 'non_single': target['rules'] *= 2
        elif mutation == 'nonempty_qualifier': target['rules'][0]['conditions'] = ['notice']
        if mutation == 'noncanonical':
            target['rules'][0] = dict(reversed(list(target['rules'][0].items())))
            wire = json.dumps(target, sort_keys=False, separators=(',', ':'))
            rows[0]['target_ids'] = [1]+[subject.base.VOCABULARY.index(t) for t in subject.base._TOKEN.findall(wire)]+[2]
        else: rows[0]['target_ids'] = subject.base._encode(target, args['codec'])
    with pytest.raises((ValueError, json.JSONDecodeError)): subject.build(**args)


def test_actor_action_group_overlap_refuses_balanced_full_validation_bank():
    args = inputs(); args['validation_bank'] = bank([0], 'overlap-validation', args['codec'])
    args['prior_sources_by_dataset']['raw_validation'] = [{k:r[k] for k in ('id','source_text')}
        for r in args['validation_bank']]
    with pytest.raises(ValueError, match='actor/action groups overlap'): subject.build(**args)


@pytest.mark.parametrize('role', ['validation_bank', 'training_bank'])
def test_same_identity_in_declared_prior_cannot_hide_different_literal(role):
    args = inputs(); name = 'raw_validation' if role == 'validation_bank' else 'original_train_bank'
    args['prior_sources_by_dataset'][name][0]['source_text'] = 'Different prior literal.'
    with pytest.raises(ValueError, match='identity/text absent'): subject.build(**args)


@pytest.mark.parametrize('mutation', ['codec', 'validator_false', 'validator_mutates', 'bad_seal'])
def test_codec_validator_and_external_seal_are_required(mutation):
    args = inputs()
    if mutation == 'codec': args['codec']['target_vocabulary'].pop()
    elif mutation == 'validator_false': args['validate_rule'] = lambda value: dict(valid=False)
    elif mutation == 'validator_mutates':
        def mutate(value):
            value['rules'][0]['modality'] = 'P'
            return dict(valid=True, canonical_ir=value)
        args['validate_rule'] = mutate
    else: args['sealed_recipe_sha256'] = 'unsealed'
    with pytest.raises(ValueError): subject.build(**args)


@pytest.mark.parametrize('field', ['conditions', 'exceptions', 'temporal'])
def test_public_renderer_refuses_qualifiers(field):
    rule = dict(actor='registrar', action='approve', object='notice', modality='O',
        conditions=[], exceptions=[], temporal=[])
    rule[field] = ['notice']
    with pytest.raises(ValueError, match='cannot drop a qualifier'): subject.sentence(subject.TEMPLATES[0], rule)


def test_recipe_is_a_copy_and_build_is_deterministic_without_global_rng_change():
    import random
    expected = subject.recipe(); changed = subject.recipe()
    changed['template_text'][subject.TEMPLATES[0]]['O'] = 'mutated'
    assert subject.recipe() == expected
    state = random.getstate()
    assert subject.build(**inputs()) == subject.build(**inputs())
    assert random.getstate() == state
