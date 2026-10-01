"""Independent copy-span curriculum and frozen holdouts for aligned training.

Exact source/semantic duplicate quarantine reuses the existing coverage recipe.
Parent rows remain unchanged in the corpus; a deterministic rehearsal sampler
bounds fitting while retaining every existing compositional training example.
"""
from collections import defaultdict
from copy import deepcopy
from . import rich_grammar as grammar
from . import coverage_curriculum as coverage
from .rich_decoder import sha, wire
from .rich_training import build_pairs

ACTIONS=('save','view','use','reuse','run','create','fetch','show')
SHAPES=('short','long','internal_article','repeated_occurrences','action_noun','leading_extension','quoted_command','numeric_range')


def _object(noun, shape):
    return {
        'short':f'{noun} packet',
        'long':f'{noun} packet beneath amber archival storage racks',
        'internal_article':f'{noun} packet with the bronze dispatch record',
        'repeated_occurrences':f'{noun} packet {noun} packet',
        'action_noun':f'{noun} register with secondary call logs',
        'leading_extension':f'.{noun} {noun} packet beside dense storage blocks',
        'quoted_command':f'`{noun} inspect` with the bronze dispatch record',
        'numeric_range':f'{noun} packet for 3-7 transfer batches',
    }[shape]


def _render(action, obj, form):
    actor='operator' if form==3 else 'unspecified'
    modality=('intended','required','prohibited','intended')[form]
    instruction=(f'{action.capitalize()} {obj}',f'Must {action} the {obj}.',
                 f'Do not {action} the {obj}',f'The operator intends to {action} the {obj}.')[form]
    ast={'kind':'atom','actor':actor,'action':action,'object':obj,'modality':modality}
    if grammar.parse_instruction(instruction)!=ast:raise ValueError('authored span template differs from weak grammar')
    return instruction,ast


def build_alignment_curriculum(parent_corpus, *, forbidden_sources=()):
    parent=coverage._validated_rows(parent_corpus)
    result=deepcopy(parent_corpus)
    banned_sources=set();banned_semantics=set()
    for row in parent:
        banned_sources.update(coverage._source_identities(row))
        banned_semantics.update(coverage._semantic_identities(row['ast']))
    for source in forbidden_sources:
        banned_sources.add(coverage._source_identity(source))
        try:banned_semantics.update(coverage._semantic_identities(grammar.parse_instruction(source)))
        except ValueError:pass
    additions=[];omitted=[]
    for split,nouns in [('test',('mosaic','tundra','saffron','violet','opal','lilac','marble','ivory')),
                        ('train',('ledger','binder','folio'))]:
        for shape_index,shape in enumerate(SHAPES):
            for noun in (nouns if split=='train' else (nouns[shape_index],)):
                for action_index,action in enumerate(ACTIONS):
                    for form in (range(4) if split=='train' else ((shape_index+action_index)%4,)):
                        text,ast=_render(action,_object(noun,shape),form)
                        identity=f'aligned-span-v2:{split}:{shape}:{noun}:{action}:{form}'
                        row={'id':identity,'split':split,'instruction':text,'ast':ast,'provenance':{
                            'kind':'independent_authored_copy_span_curriculum','source_family_id':f'{split}:{shape}:{noun}',
                            'object_shape':shape,'surface_form':form,'semantic_gold':False,
                            'model_predictions_used':False,'evaluation_sentence_derived':False}}
                        if coverage._source_identities(row)&banned_sources or coverage._semantic_identities(ast)&banned_semantics:
                            omitted.append(identity);continue
                        # Aliases within a split are allowed and deduplicated at
                        # pair construction. Cross-split banks have distinct slots.
                        additions.append(row)
    result['samples'].extend(additions)
    result['alignment_curriculum']={'schema':'intent-copy-span-curriculum/v2','parent_sha256':sha(wire(parent_corpus)),
        'new_training_rows':sum(r['split']=='train'for r in additions),'new_test_rows':sum(r['split']=='test'for r in additions),
        'omitted':omitted,'parent_rows_preserved':True,'weak_labels':True,'predictions_used':False}
    return result


def prepare_alignment_training_data(corpus, *, maximum_parent_atoms=1920):
    if type(maximum_parent_atoms)is not int or not 1<=maximum_parent_atoms<=2048:raise ValueError('bounded atom rehearsal required')
    safe=coverage.prepare_coverage_training_data(corpus)
    allowed={s:set(ids)for s,ids in safe['selected_row_ids'].items()}
    groups=defaultdict(list);fixed=[]
    for row in corpus['samples']:
        if row['split']!='train' or row['id']not in allowed['train']:continue
        if row['ast']['kind']!='atom' or row['id'].startswith('aligned-span-v2:'):
            fixed.append(row)
        else:
            key=(row['ast']['modality'],row['provenance'].get('kind'),row['provenance'].get('object_shape','original'))
            groups[key].append(row)
    for rows in groups.values():rows.sort(key=lambda r:sha(('rehearsal-v2:'+r['id']).encode()))
    chosen=[]
    while groups and len(chosen)<maximum_parent_atoms:
        for key in sorted(tuple(groups)):
            chosen.append(groups[key].pop(0))
            if not groups[key]:del groups[key]
            if len(chosen)==maximum_parent_atoms:break
    selected=fixed+chosen
    tune=[r for r in corpus['samples']if r['split']=='validation'and r['id']in allowed['validation']]
    # Validation supplies post-fit diagnostics only; small fixed sample saves
    # evaluation time and never selects weights, curriculum or an epoch.
    tune=sorted(tune,key=lambda r:sha(('tuning-v2:'+r['id']).encode()))[:128]
    holdouts=[r for r in corpus['samples']if r['id'].startswith('aligned-span-v2:test:')]
    return {'schema':'intent-copy-span-training-data/v2','corpus_sha256':sha(wire(corpus)),
        'pairs':{'train':build_pairs(selected),'validation':build_pairs(tune)},
        'selected_train_ids':[r['id']for r in selected],'selected_validation_ids':[r['id']for r in tune],
        'new_holdouts':deepcopy(holdouts),'quarantined':safe['quarantined'],
        'parent_atoms_retained':len(chosen),'parent_compounds_retained':sum(r['ast']['kind']!='atom'for r in fixed),
        'test_used_for_fit_or_selection':False,'fitting_selection_uses_predictions':False}
