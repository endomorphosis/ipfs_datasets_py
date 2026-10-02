"""Train-only continuation curriculum for the bounded rich Intent codec."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path
import random

from . import rich_grammar as grammar
from .rich_decoder import wire, sha, register_rich_intent_checkpoint


def add_training_leaf_views(corpus):
    """Add exact atomic child slices from existing training compounds only.

    No punctuation or connective is synthesized. Existing rows, including
    validation/test rows, remain unchanged. Held-out identities are consulted
    only to quarantine collisions; none supplies an added example or target.
    Both source-token and semantic identities fence off held-out parent/leaf
    aliases. This is weak grammar supervision, not model-generated labeling.
    """
    from .compositional_decoder import _source_parts
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_copy import tokenize

    if type(corpus) is not dict or type(corpus.get('samples')) is not list:
        raise ValueError('rich paired corpus required')
    result = deepcopy(corpus)
    original = corpus['samples']
    if any(type(row) is not dict or type(row.get('id')) is not str for row in original):
        raise ValueError('source-bound rich samples require string identities')
    if len({row['id'] for row in original}) != len(original):
        raise ValueError('duplicate rich source identity')
    parent_digest = sha(wire(corpus))
    existing, heldout_inputs, heldout_semantics = {}, set(), set()

    def source_key(text):
        return tuple(tokenize(grammar.model_input(text)))

    def semantic_key(ast):
        return grammar.ast_to_sequence(ast)

    def leaves(row):
        ast = row['ast']
        if ast['kind'] not in {'and', 'or', 'then', 'if'}:
            return []
        parts = _source_parts(row['instruction'], ast['kind'])
        if ''.join(part['text'] for part in parts) != row['instruction']:
            raise ValueError('leaf source partition differs from parent')
        expected = [ast['body']] if ast['kind'] == 'if' else [ast['left'], ast['right']]
        children = [part for part in parts if not part['role'].startswith('symbolic_')]
        if len(children) != len(expected):
            raise ValueError('leaf source count differs from parent AST')
        output = []
        for part, expected_ast in zip(children, expected):
            child_ast = grammar.parse_instruction(part['text'])
            if child_ast.get('kind') != 'atom' or child_ast != expected_ast:
                raise ValueError('exact source leaf differs from parent atomic meaning')
            output.append((part, child_ast))
        return output

    for row in original:
        if row.get('split') not in {'train', 'validation', 'test'}:
            raise ValueError('explicit rich corpus partition required')
        ast = grammar.validate_ast(row['ast'])
        if grammar.parse_instruction(row['instruction']) != ast:
            raise ValueError('existing rich label differs from its exact source')
        key, target = source_key(row['instruction']), semantic_key(ast)
        if key in existing and existing[key] != target:
            raise ValueError('conflicting tokenized rich labels')
        existing[key] = target
        if row['split'] != 'train':
            heldout_inputs.add(key)
            heldout_semantics.add(target)
            for part, child in leaves(row):
                heldout_inputs.add(source_key(part['text']))
                heldout_semantics.add(semantic_key(child))

    added, omitted = [], []
    candidates = 0
    for row in original:
        if row['split'] != 'train':
            continue
        for part, child in leaves(row):
            candidates += 1
            key, target = source_key(part['text']), semantic_key(child)
            reason = None
            if key in heldout_inputs or target in heldout_semantics:
                reason = 'heldout_source_or_semantic_collision'
            elif key in existing:
                if existing[key] != target:
                    raise ValueError('training leaf conflicts with an existing tokenized label')
                reason = 'duplicate_existing_or_added_training_view'
            if reason is not None:
                omitted.append({'parent_id': row['id'], 'role': part['role'],
                    'start_char': part['start_char'], 'end_char': part['end_char'], 'reason': reason})
                continue
            identity = {'parent_corpus_sha256': parent_digest, 'parent_id': row['id'],
                        'source_span': part}
            added.append({'id': 'training-leaf:' + sha(wire(identity)), 'split': 'train',
                'instruction': part['text'], 'ast': deepcopy(child),
                'provenance': {'kind': 'exact_training_source_leaf_view',
                    'parent_id': row['id'], 'parent_split': 'train',
                    'parent_instruction': row['instruction'],
                    'parent_instruction_sha256': sha(row['instruction'].encode()),
                    'parent_ast_sha256': sha(wire(row['ast'])),
                    'source_span': deepcopy(part), 'parent_provenance': deepcopy(row['provenance']),
                    'label_rule': 'exact_train_child_source_parse_matches_parent_ast/v1',
                    'synthetic_punctuation': False, 'model_predictions_used': False,
                    'semantic_gold': False}})
            existing[key] = target
    result['samples'].extend(added)
    result['split_counts'] = dict(Counter(row['split'] for row in result['samples']))
    result['kind_counts'] = dict(Counter(row['ast']['kind'] for row in result['samples']))
    result['training_leaf_views'] = {'schema': 'intent-training-source-leaf-views/v1',
        'parent_corpus_sha256': parent_digest, 'original_rows': len(original),
        'candidate_train_leaves': candidates, 'added_train_leaves': len(added),
        'omitted': omitted, 'omitted_counts': dict(Counter(row['reason'] for row in omitted)),
        'original_rows_preserved': True, 'heldout_rows_added_or_modified': False,
        'heldout_used_only_for_collision_quarantine': True, 'predictions_used': False,
        'source_text_normalized_or_punctuated': False,
        'producer_sha256': sha(Path(__file__).read_bytes())}
    return result


def build_rich_intent_corpus(parent_corpus, *, examples_per_kind=80, maximum_parent_train_atoms=256):
    """Retain compatible old partitions, add authored disjoint lexical groups.

    The sample labels are weak controlled-grammar labels, not semantic gold.
    No current benchmark failures or validation source text enter training.
    """
    if type(examples_per_kind) is not int or not 8 <= examples_per_kind <= 256:
        raise ValueError('bounded rich curriculum size required')
    if type(maximum_parent_train_atoms) is not int or not 1 <= maximum_parent_train_atoms <= 4096:
        raise ValueError('bounded inherited atom rehearsal size required')
    rows, omitted, retained_train = [], Counter(), 0
    for old in sorted(parent_corpus['samples'],key=lambda r:sha(r['id'].encode())):
        try:
            ast=grammar.parse_instruction(old['instruction'])
            if ast!={'kind':'atom',**old['frame']}:
                raise ValueError('prior labels differ from declared rich grammar')
        except ValueError as exc:
            omitted[str(exc)]+=1
            continue
        if old['split']=='train':
            if retained_train>=maximum_parent_train_atoms:
                omitted['bounded_parent_atom_rehearsal']+=1
                continue
            retained_train+=1
        rows.append({'id':old['id'],'split':old['split'],'instruction':old['instruction'],'ast':ast,
                     'provenance':{'kind':'inherited_compatible_sample','original':old['provenance']}})
    actions=['read','write','validate','update','inspect','check','list','find','view','show',
             'evaluate','reuse','use','pin','register','save','load','configure','generate','remove']
    nouns=['cache','input','report','schema','index','configuration','metadata','payload','result','logs',
           'document','file','buffer','request','response','record','policy','dataset','checkpoint','output']
    for split,count,bank in [('train',examples_per_kind,'sample'),('validation',max(8,examples_per_kind//8),'heldout'),
                              ('test',max(8,examples_per_kind//8),'reserved')]:
        for kind in ('atom','and','or','then','if'):
            for i in range(count):
                rng=random.Random(f'rich-v1:{split}:{kind}:{i}')
                actor=rng.choice(['agent','maintainer','system','operator'])
                action=rng.choice(actions)
                noun=rng.choice(nouns) if split=='train' else bank+str(i)
                object_=rng.choice([noun,f'{noun} data',f'{noun} metadata report',f'`src/{noun}.py`',
                                    f'API {noun}',f'{noun} configuration file'])
                left={'kind':'atom','actor':actor,'action':action,'object':object_,
                      'modality':rng.choice(list(grammar.MODALS))}
                right={'kind':'atom','actor':actor,'action':rng.choice(actions),
                       'object':rng.choice(nouns) if split=='train' else f'{bank}{i} result',
                       'modality':rng.choice(list(grammar.MODALS))}
                if kind=='atom':
                    ast=left
                    if i%2==0:
                        ast={**left,'actor':'unspecified'}
                elif kind=='if':
                    ast={'kind':'if','guard':{'subject':rng.choice(nouns) if split=='train' else f'{bank}{i} cache',
                         'property':rng.choice(['ready','valid','available','empty']),
                         'negated':bool(rng.getrandbits(1))},'body':left}
                else:ast={'kind':kind,'left':left,'right':right}
                text=grammar.ast_to_text(ast)
                if kind=='atom' and ast['actor']=='unspecified':
                    prefixes={'intended':'','required':'must ','prohibited':'do not ','permitted':'may ','recommended':'should '}
                    text=prefixes[ast['modality']]+ast['action']+' '+ast['object']+'.'
                    text=text[0].upper()+text[1:]
                assert grammar.parse_instruction(text)==ast
                rows.append({'id':f'authored-rich:{split}:{kind}:{i}','split':split,
                    'instruction':text,'ast':ast,'provenance':{'kind':'authored_rich_grammar_control',
                    'lexical_group':f'{split}:{bank}:{i}','semantic_gold':False}})
    return {'schema':'intent-rich-continuation-corpus/v1','samples':rows,
        'split_counts':dict(Counter(r['split'] for r in rows)),
        'kind_counts':dict(Counter(r['ast']['kind'] for r in rows)),
        'omitted_parent_rows':dict(omitted),'parent_corpus_sha256':sha(wire(parent_corpus)),
        'parent_train_rehearsal_limit':maximum_parent_train_atoms,
        'test_used_for_training_or_selection':False,'current_rejected_examples_added_to_training':False,
        'supervision':'inherited weak samples and authored bounded grammar controls',
        'source_semantics_verified':False}


def build_pairs(rows):
    """Deduplicate inverse targets without leaking aliases across partitions."""
    result, seen = [], {}
    for row in rows:
        ast=grammar.validate_ast(row['ast'])
        for direction,source,target in (
            ('encode',grammar.model_input(row['instruction']),grammar.ast_to_sequence(ast)),
            ('decode',grammar.ast_to_sequence(ast),grammar.ast_to_text(ast))):
            key=(direction,source)
            if key in seen:
                if seen[key]!=target:raise ValueError('conflicting rich training labels')
                continue
            seen[key]=target
            result.append({'id':row['id']+':'+direction,'direction':direction,'source':source,'target':target})
    return result


def train_rich_intent(corpus, *, parent_backend_descriptor, output, epochs=100, max_seconds=180,
                      copy_dropout=0.35, learning_rate=0.002):
    from ....optimizers.logic_theorem_optimizer.autoencoder_paired_copy_continuation import train_paired_copy_continuation
    output=Path(output).absolute()
    output.mkdir(parents=True,exist_ok=False)
    (output/'corpus.json').write_bytes(wire(corpus))
    train=build_pairs([r for r in corpus['samples'] if r['split']=='train'])
    tune=build_pairs([r for r in corpus['samples'] if r['split']=='validation'])
    # Original corpora can contain wording aliases with identical inverse IR;
    # quarantine overlaps from tuning, never move them into training.
    train_identities={(r['direction'],r['source']) for r in train}
    excluded=[r for r in tune if (r['direction'],r['source']) in train_identities]
    tune=[r for r in tune if (r['direction'],r['source']) not in train_identities]
    child=train_paired_copy_continuation(train,tune,parent_descriptor=parent_backend_descriptor,
        output_dir=output/'model',epochs=epochs,max_seconds=max_seconds,copy_dropout=copy_dropout,
        learning_rate=learning_rate)
    descriptor=register_rich_intent_checkpoint(child,output=output,corpus_sha256=sha(wire(corpus)))
    (output/'descriptor.json').write_bytes(wire(descriptor))
    receipt={'schema':'intent-rich-continuation-training/v1','checkpoint':descriptor,'backend':child,
        'parent_backend':parent_backend_descriptor,'corpus_sha256':sha(wire(corpus)),
        'training_pair_count':len(train),'validation_pair_count':len(tune),
        'excluded_tuning_overlaps':[r['id'] for r in excluded],
        'test_used_for_training_or_selection':False,'source_semantics_verified':False,'published':False}
    (output/'training-receipt.json').write_bytes(wire(receipt))
    return receipt
