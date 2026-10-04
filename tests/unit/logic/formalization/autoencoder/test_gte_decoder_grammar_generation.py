from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import random
import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import gte_decoder_grammar_generation as subject

FIELDS = subject.FIELDS


def codec(head):
    if head == "primary384":
        vocabulary = sorted(set(['{', '}', '[', ']', ',', ':'] +
            [json.dumps(v) for v in (*FIELDS, 'rules', 'O', 'P', 'F', 'Agency', 'retain', 'records', 'A', 'B', 'C', 'D', 'E')]))
    else:
        values = {"modality": ['O', 'P', 'F'], "actor": ['Agency'], "action": ['retain'], "object": ['records'],
                  "conditions": ['A', 'B', 'C', 'D', 'E'], "exceptions": ['A', 'B'], "temporal": ['A', 'B']}
        vocabulary = [json.dumps(["field", f], separators=(',', ':')) for f in FIELDS]
        vocabulary += [json.dumps(["end", f], separators=(',', ':')) for f in subject.QUALIFIERS]
        vocabulary += [json.dumps(["atom", f, value], separators=(',', ':')) for f in FIELDS for value in values[f]]
    return {"target_vocabulary": ['<pad>', '<bos>', '<eos>', *vocabulary]}


@pytest.mark.parametrize("head", ["primary384", "legacy8"])
def test_random_permitted_paths_terminate_and_decode_strictly(head):
    inherited = codec(head)
    grammar = subject.Grammar(inherited, head)
    for seed in range(40):
        rng = random.Random(seed)
        cap = grammar.minimum_remaining(grammar.initial) + seed % 25
        state, ids = grammar.initial, [1]
        for step in range(cap):
            choices = grammar.allowed(state, cap - step)
            assert choices and not {0, 1} & choices.keys()
            token = rng.choice(sorted(choices))
            ids.append(token);state = choices[token]
            if token == 2:break
        assert ids[-1] == 2 and len(ids) <= cap + 1
        ir = subject.codec_module._decode(ids, inherited['target_vocabulary'], head)
        assert subject.codec_module._encode(ir, inherited['target_vocabulary'], head) == ids
        for values in (ir['rules'][0][f] for f in subject.QUALIFIERS):
            assert values == sorted(set(values)) and len(values) <= 4


@pytest.mark.parametrize("head", ["primary384", "legacy8"])
def test_duplicate_or_descending_qualifiers_not_allowed(head):
    grammar = subject.Grammar(codec(head), head)
    index = next(i for i,item in enumerate(grammar.plan) if item[0] in ('array', 'legacy_array'))
    state = (index, 'need_value' if head == 'primary384' else 'legacy_values', ('B',))
    choices = grammar.transitions(state)
    values = grammar.plan[index][1]
    assert all(values[t] > 'B' for t in choices if t in values)


def test_json_lexemes_are_not_restricted_to_training_field_inventory():
    grammar = subject.Grammar(codec('primary384'), 'primary384')
    action = next(item for item in grammar.plan if item[0] == 'scalar')
    assert 'Agency' in action[1].values() and 'modality' in action[1].values()


def test_noncanonical_string_alias_rejected_before_generation():
    inherited = codec('primary384')
    inherited['target_vocabulary'].append('"\\u004f"')
    with pytest.raises(ValueError, match='noncanonical'):
        subject.Grammar(inherited, 'primary384')


@pytest.mark.parametrize("head", ["primary384", "legacy8"])
def test_invalid_prefix_cannot_sneak_pad_or_eos_past_grammar(head):
    grammar = subject.Grammar(codec(head), head)
    for prefix in ([1, 0], [1, 1], [1, 2]):
        with pytest.raises(ValueError, match='prefix violates'):
            grammar.state_after(prefix)


def fixture_module():
    path = Path(__file__).with_name('test_gte_decoder_source_generation.py')
    spec = importlib.util.spec_from_file_location('grammar_real_decoder_fixture', path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def real_models(tmp_path_factory):
    module = fixture_module()
    previous = module.torch.get_num_threads()
    module.torch.set_num_threads(1)
    yield module, module.replay_fixture.inputs.__wrapped__(tmp_path_factory)
    module.torch.set_num_threads(previous)


@pytest.mark.parametrize('variant,head', [('donor384','primary384'),('legacy8','legacy8'),
                                        ('student768','primary384'),('student768','legacy8')])
def test_real_models_forced_to_invalid_raw_eos_emit_complete_canonical_output(real_models, variant, head):
    module, fixture = real_models
    model = module.model_for(fixture, variant)
    module.constant_output(model, variant, head, 2)
    args = module.arguments(fixture, variant, head, max_new_tokens=128)
    inherited = fixture['initialization']['primary' if head=='primary384' else 'legacy8']['codec']
    receipt = subject.generate_source_only(model, **args, codec=inherited)
    assert receipt['terminated'] and receipt['raw_argmax_overrides'] > 0
    assert receipt['generated_ids'] != [1, 2]
    assert subject.inspect_source_only_generation(receipt, inherited)['syntax_valid']
    assert subject.generate_source_only(model, **args, codec=inherited) == receipt
    changed = deepcopy(receipt)
    changed['steps'][0]['allowed_token_ids'] = [0, 1, 2]
    with pytest.raises(ValueError, match='schema-mask'):
        subject.inspect_source_only_generation(changed, inherited)
    with pytest.raises(ValueError, match='fixed budget'):
        subject.generate_source_only(model, **{**args, 'max_new_tokens': 2}, codec=inherited)
    for key,value in [('qualified', True), ('effective_max_new_tokens', float(receipt['effective_max_new_tokens']))]:
        changed = deepcopy(receipt); changed[key] = value
        with pytest.raises(ValueError):
            subject.inspect_source_only_generation(changed, inherited)
    changed = deepcopy(receipt); changed['steps'][0]['step'] = True
    with pytest.raises(ValueError, match='strictly typed'):
        subject.inspect_source_only_generation(changed, inherited)
