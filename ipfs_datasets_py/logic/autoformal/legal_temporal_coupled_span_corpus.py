"""Source-complete authored TRAIN contrasts for generic coupled span scoring.

All concrete action/qualifier anchors in each TRAIN source are reference-side
supervision. Numerical inference receives only the unchanged four-field source
query; it never receives these anchors or a semantic candidate inventory.
Evaluation shares already exposed controlled grammar; this is not legal gold.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
import random
import re
from . import legal_temporal_owner_pointer_corpus as pointer

stability, previous, paired, old = pointer.stability, pointer.previous, pointer.paired, pointer.old
require, wire, sha, digest, file_ref, read_ref, write_new = (
    getattr(pointer, key) for key in ('require', 'wire', 'sha', 'digest', 'file_ref', 'read_ref', 'write_new'))
query, validate_source_query, propose_time_spans, validate_query_inventory = (
    getattr(pointer, key) for key in ('query', 'validate_source_query', 'propose_time_spans', 'validate_query_inventory'))
SOURCE_KEYS, TARGET_KEYS = pointer.SOURCE_KEYS, pointer.TARGET_KEYS
LABELS, TIME_FORMS = old.LABELS, old.TIME_FORMS
SCHEMA = 'authored-temporal-coupled-span-corpus/v1'
ANNOTATION_SCHEMA = 'authored-temporal-coupled-span-annotation/v1'
AUTHORITY = 'authored_exact_anchor_and_other_owner_contrasts_not_independent_legal_gold'
COUNTS = {'training': 3072, 'tuning': 288, 'fresh_lexical': 144, 'fresh_structural': 144}
UNITS = {'fresh_lexical': 12, 'fresh_structural': 12}
SEALED, RETENTION = pointer.SEALED, pointer.RETENTION
STRUCTURAL_FAMILIES = stability.STRUCTURAL_FAMILIES
RELEASE_RULE = 'Current semantic references remain sealed until selection, source-only prediction and independent replay freeze.'
CONTRAST_KEYS = {'id', 'source_sha256', 'proposed_time_span', 'negative_owner_spans'}
OWNER_ROLE_TYPES = {'action': 'norm', 'action_object': 'norm', 'condition_predicate': 'condition',
                    'condition_anchor': 'condition', 'exception_predicate': 'exception', 'exception_anchor': 'exception'}
VOCAB = {
    'fresh_lexical': {'names': ('Indus', 'Lyra', 'Mensa', 'Norma'),
                      'actions': ('attest', 'itemize', 'countersign', 'enumerate'),
                      'objects': ('dispatch compendium', 'duty synopsis', 'routing digest', 'delivery register')},
    'fresh_structural': {'names': ('Octans', 'Pavo', 'Reticulum', 'Vela'),
                         'actions': ('colligate', 'chronicle', 'validate', 'notarize'),
                         'objects': ('procedure synopsis', 'registry compendium', 'filing outline', 'docket digest')},
}
HEADINGS = ('Span study {n}: ', '[Temporal illustration {n}] ', 'Ownership example {n}. — ')
source_row = pointer.source_row
validate_target = pointer.validate_target
validate_training_row = pointer.validate_target


def factors(split, unit, source):
    require(split in UNITS, 'known new evaluation panel required')
    return stability.factors(split, unit, source)


def literal(split, unit, form):
    require(split in UNITS and type(unit) is int and 0 <= unit < 12 and form in TIME_FORMS, 'bounded literal factors required')
    index = list(UNITS).index(split)
    amount, year, day = 151 + 20 * index + unit, 2111 + index, unit + 1
    return {'days': f'within {amount} days of notice', 'hours': f'within {amount} hours of notice',
            'iso_date': f'before {year}-09-{day:02d}', 'month_date': f'before September {day}, {year}'}[form]

def render_source(split, unit, source):
    labels, form, modality, placement, family, layout, enclosure, order, pattern, rotation = factors(split, unit, source)
    case = unit * 5 + source
    identity = 160000 + list(UNITS).index(split) * 1000 + case
    v, timing, w = VOCAB[split], literal(split, unit, form), old.Writer()
    heading = w.add(HEADINGS[case % 3].format(n=identity))
    roles, modals, blocks, queries, owners, norms = [], [], {}, {}, [], []
    norm_slots = [i for i, label in enumerate(labels) if label == 'norm']
    local = {'condition': [], 'exception': []}
    for slot, label in enumerate(labels):
        if label in local:
            local[label].append((slot, label))
    for index, slot in enumerate(i for i, label in enumerate(labels) if label == 'ambiguous'):
        if labels.count('ambiguous') == 1 and 'condition' in labels and 'exception' not in labels:
            owner = 'exception'
        elif labels.count('ambiguous') == 1 and 'exception' in labels and 'condition' not in labels:
            owner = 'condition'
        else:
            owner = ('condition', 'exception')[(case + index) % 2]
        local[owner].append((slot, 'ambiguous'))
    joint = None

    def role(text, kind):
        value = w.add(text)
        roles.append({'role': kind, 'span': deepcopy(value)})
        return value

    def emit_time(slot):
        require(slot not in queries, 'one insertion per proposed occurrence required')
        queries[slot] = w.add(timing)

    def qualifier(owner):
        start = len(w.text)
        wrapped = enclosure == owner + '_only'
        if wrapped:
            w.add('(')
        cue = w.add('if' if owner == 'condition' else 'unless')
        w.add(' ')
        positions = [(j + case + (owner == 'exception')) % 3 for j in range(3)]
        entries = dict(zip(positions, local[owner]))
        for index in range(3):
            if index:
                w.add(' and ' if owner == 'condition' else ' or ')
            slot, label = entries.get(index, (None, None))
            subject = f"the {'application' if owner == 'condition' else 'waiver'} {identity}-{index + 1}"
            predicate = ((' was received' if owner == 'condition' else ' was issued') if label == owner
                         else (' is valid' if owner == 'condition' else ' is active'))
            anchor = role(subject + predicate, owner + '_predicate')
            if slot is not None:
                w.add(' ')
                emit_time(slot)
            owners.append({'owner_type': owner, 'anchor_span': anchor, 'scope_span': None,
                           'cue_span': cue, 'query_slot': slot, 'atom_ordinal': index + 1})
        if wrapped:
            w.add(')')
        blocks[owner] = w.span(start, len(w.text))
        for item in owners:
            if item['owner_type'] == owner:
                item['scope_span'] = deepcopy(blocks[owner])

    def joint_qualifiers():
        nonlocal joint
        require(joint is None, 'qualifiers inserted exactly once')
        start = len(w.text)
        w.add('(')
        qualifier(order[0])
        w.add(', ')
        qualifier(order[1])
        w.add(')')
        joint = w.span(start, len(w.text))

    def norm_block():
        start = len(w.text)
        for index, slot in enumerate(norm_slots or [None]):
            if index:
                w.add('; ')
            begin = len(w.text)
            if slot is not None and placement == 'before_actor':
                emit_time(slot)
                w.add(', ')
            actor = role(f"the {v['names'][case % 4]} bureau {identity}", 'actor')
            w.add(' ')
            if split == 'fresh_structural' and index == 0 and family == STRUCTURAL_FAMILIES[0]:
                joint_qualifiers()
                w.add(' ')
            cue = w.add(paired.MODALS[modality])
            modals.append(deepcopy(cue))
            if slot is not None and placement == 'after_modal':
                w.add(', ')
                emit_time(slot)
                w.add(', ')
            else:
                w.add(' ')
            if split == 'fresh_structural' and index == 0 and family == STRUCTURAL_FAMILIES[1]:
                joint_qualifiers()
                w.add(' ')
            anchor = role(f"{v['actions'][(case + index) % 4]} the {v['objects'][(case + index) % 4]} {identity}-{index + 1}", 'action')
            if slot is not None and placement == 'after_action':
                w.add(', ')
                emit_time(slot)
            norms.append({'owner_type': 'norm', 'anchor_span': anchor, 'scope_span': w.span(begin, len(w.text)),
                          'cue_span': cue, 'actor_span': actor, 'query_slot': slot, 'atom_ordinal': index + 1})
        blocks['norm'] = w.span(start, len(w.text))

    if split == 'fresh_structural':
        norm_block()
    else:
        sequence = layout.split('_')
        for index, block in enumerate(sequence):
            if index:
                w.add(', ' if sequence[index - 1] != 'norm' or block == 'norm' else ' ')
            norm_block() if block == 'norm' else qualifier(block)
    body = w.span(heading['char_end'], len(w.text))
    w.add('.')
    require(set(queries) == set(range(len(labels))), 'all query slots realized')
    proposed = propose_time_spans(w.text)
    require([(s['char_start'], s['char_end']) for s in proposed] ==
            sorted((s['char_start'], s['char_end']) for s in queries.values()), 'complete time proposer mismatch')
    unit_id, source_sha = 'unit-' + digest([SCHEMA, split, unit]), sha(w.text)
    for item in norms + owners:
        item['owner_occurrence_id'] = paired.owner_identity(source_sha, item['owner_type'], item['anchor_span'])
    norm_records = [{'actor_span': x['actor_span'], 'modal_span': x['cue_span'], 'action_span': x['anchor_span'],
                     'time_span': queries[x['query_slot']] if x['query_slot'] is not None else None,
                     'clause_span': x['scope_span']} for x in norms]
    outputs = []
    for slot, label in enumerate(labels):
        if label == 'norm':
            target = next(x for x in norms if x['query_slot'] == slot)
            selected, countermodels = [target], None
        else:
            target = next(x for x in owners if x['query_slot'] == slot)
            selected = norms + [target] if label == 'ambiguous' else [target]
            countermodels = old.ambiguity_countermodels(target['owner_type']) if label == 'ambiguous' else None
        candidates = [{k: deepcopy(x[k]) for k in ('owner_type', 'owner_occurrence_id', 'anchor_span', 'scope_span')} for x in selected]
        if label == 'ambiguous':
            for candidate in candidates:
                if candidate['owner_type'] == 'norm':
                    candidate['scope_span'] = deepcopy(body)
        a = {'schema': ANNOTATION_SCHEMA, 'split': split, 'unit_index': unit, 'source_index': source,
             'unit_id': unit_id, 'cardinality': len(labels), 'unit_pattern': pattern, 'label_rotation': rotation,
             'layout_family': layout, 'structural_family': family, 'enclosure_family': enclosure,
             'norm_time_placement': placement, 'time_form': form, 'modality': modality,
             'heading_span': heading, 'body_span': body, 'time_span': queries[slot],
             'time_cue_span': w.span(queries[slot]['char_start'], queries[slot]['char_start'] + len(timing.split()[0])),
             'source_role_spans': roles, 'modal_spans': modals, 'block_spans': blocks,
             'norm_occurrences': norm_records, 'interposition_span': joint,
             'condition_atom_count': 3, 'exception_atom_count': 3, 'qualifier_order': order,
             'source_occurrence_ordinal': next(i + 1 for i, s in enumerate(proposed) if s['char_start'] == queries[slot]['char_start']),
             'authored_local_owner_type': target['owner_type'], 'local_atom_ordinal': target['atom_ordinal'],
             'same_time_literal_for_all_source_occurrences': True, 'owner_candidates': candidates,
             'attachment_cue_spans': [{'owner_occurrence_id': x['owner_occurrence_id'], 'span': deepcopy(x['cue_span'])} for x in selected],
             'candidate_scope_semantics': 'structural_enclosing_extent_not_semantic_closure',
             'gold_filtered_owner_candidates': True, 'candidate_inventory_usage': 'reference_only_not_inference_inputs',
             'unique_owner_type_asserted': label != 'ambiguous', 'unique_owner_occurrence_asserted': label != 'ambiguous',
             'countermodels': countermodels, 'annotation_authority': AUTHORITY, 'independently_reviewed': False,
             'source_semantics_verified': False, 'legal_gold': False, 'flat_logic_profile_admission': False}
        outputs.append({**query(w.text, {k: queries[slot][k] for k in ('char_start', 'char_end')}),
                        'label': label, 'group_id': 'source-' + source_sha, 'annotation': deepcopy(a)})
    return outputs


def validate_authored_reference(row):
    if row['annotation'].get('schema') == ANNOTATION_SCHEMA:
        a = row['annotation']
        expected = [r for r in render_source(a.get('split'), a.get('unit_index'), a.get('source_index')) if r['id'] == row['id']]
        require(len(expected) == 1 and wire(expected[0]) == wire(row), 'new reference differs from exact insertion provenance')
    else:
        pointer.validate_authored_reference(row)
    return row


def project_reference(row, *, reconstruct=True):
    if reconstruct:
        validate_authored_reference(row)
    return pointer.project_reference(row, reconstruct=False)


target_projection = project_reference


def validate_mapping(targets, references):
    require(type(targets) is list and type(references) is list and len(targets) == len(references), 'complete reference mapping required')
    require(len({r['id'] for r in targets}) == len(targets), 'duplicate pointer query')
    require(wire(targets) == wire([project_reference(r) for r in references]), 'authoritative target mapping differs')
    validate_query_inventory([source_row(r) for r in targets], expected=len(targets))
    return targets


def concrete_owner_anchors(reference):
    """Reference-side complete declared action/predicate anchors, never inference."""
    text, annotation = reference['source_text'], reference['annotation']
    roles = annotation.get('source_role_spans', annotation.get('lexical_spans'))
    require(type(roles) is list and bool(roles), 'explicit complete source role annotations required')
    owners = []
    for item in roles:
        require(type(item) is dict and set(item) == {'role', 'span'}, 'closed authored role record required')
        kind = item['role']
        require(kind == 'actor' or kind in OWNER_ROLE_TYPES, 'unknown authored role')
        span = pointer._exact_span(text, item['span'])
        if kind == 'actor':
            continue
        target = {**source_row(reference), 'label': OWNER_ROLE_TYPES[kind], 'group_id': reference['group_id'],
                  'owner_anchor_span': span}
        validate_target(target)
        owners.append({'owner_type': OWNER_ROLE_TYPES[kind], 'anchor_span': span})
    owners.sort(key=lambda v: (v['anchor_span']['char_start'], v['anchor_span']['char_end'], v['owner_type']))
    coords = [(x['anchor_span']['char_start'], x['anchor_span']['char_end']) for x in owners]
    require(len(coords) == len(set(coords)) and bool(coords), 'distinct concrete owner anchors required')
    require(all(b <= c for (_, b), (c, _) in zip(coords, coords[1:])), 'authored owner anchors overlap')
    require({x['owner_type'] for x in owners} == set(LABELS[:3]), 'complete norm/condition/exception roles required')
    return owners


def build_training_contrasts(targets, references):
    """Derive other-owner negatives from every role in each complete TRAIN source."""
    validate_mapping(targets, references)
    by_source = defaultdict(list)
    for target, reference in zip(targets, references):
        by_source[target['source_sha256']].append((target, reference))
    contrasts, groups = {}, []
    for source_sha, items in sorted(by_source.items()):
        validate_query_inventory([source_row(t) for t, _ in items], expected=len(items))
        owners = concrete_owner_anchors(items[0][1])
        require(all(wire(concrete_owner_anchors(r)) == wire(owners) for _, r in items), 'same-source complete owner inventory differs across queries')
        groups.append({'source_sha256': source_sha, 'query_ids': sorted(t['id'] for t, _ in items)})
        for target, _ in items:
            positive = target['owner_anchor_span']
            negatives = []
            if positive is not None:
                require(sum(o['owner_type'] == target['label'] and wire(o['anchor_span']) == wire(positive) for o in owners) == 1,
                        'positive anchor absent from complete authored role inventory')
                time = target['proposed_time_span']
                negatives = [deepcopy(o['anchor_span']) for o in owners if wire(o['anchor_span']) != wire(positive)
                             and (o['anchor_span']['char_end'] <= time['char_start'] or o['anchor_span']['char_start'] >= time['char_end'])]
                require(bool(negatives), 'concrete query lacks other-owner negative')
            contrasts[target['id']] = {'id': target['id'], 'source_sha256': source_sha,
                                      'proposed_time_span': deepcopy(target['proposed_time_span']),
                                      'negative_owner_spans': negatives}
    require(set(contrasts) == {r['id'] for r in targets}, 'complete contrast query inventory required')
    return contrasts, groups


def validate_training_contrasts(targets, references, contrasts, groups):
    require(type(contrasts) is dict and type(groups) is list, 'contrast map and source groups required')
    expected, expected_groups = build_training_contrasts(targets, references)
    require(wire(contrasts) == wire(expected) and wire(groups) == wire(expected_groups), 'source-bound TRAIN contrast metadata differs')
    return True


def make_panel(split):
    require(split in UNITS, 'known evaluation panel required')
    rows, units = [], []
    for unit in range(12):
        values = [r for source in range(5) for r in render_source(split, unit, source)]
        rows.extend(values)
        units.append({'unit_id': values[0]['annotation']['unit_id'], 'query_ids': sorted(r['id'] for r in values)})
    random.Random(162401 + list(UNITS).index(split)).shuffle(rows)
    validate_panel(rows, units, split)
    return rows, units


def validate_panel(rows, units, split):
    require(split in UNITS, 'known evaluation panel required')
    paired.validate_units(rows, units, split, reconstruct=False)
    require(len(rows) == 144 and len(units) == 12 and len({r['source_sha256'] for r in rows}) == 60, 'evaluation inventory differs')
    for row in rows:
        project_reference(row)
    return rows


def _mapping(rows):
    return {'schema': 'authored-coupled-span-reference-mapping/v1', 'reference_rows': deepcopy(rows),
            'reference_rows_sha256': digest(rows), 'pointer_targets_sha256': digest([project_reference(r) for r in rows]),
            'ambiguous_targets_are_null': True, 'reference_candidates_are_not_inference_inputs': True,
            'independent_legal_gold': False}


def admitted_inputs(prior_manifest_path):
    prior = pointer.load_training_inputs(prior_manifest_path)
    a = prior['manifest']['artifacts']
    base = pointer.admitted_inputs(prior['manifest']['prior_stability_corpus']['path'])
    inherited = read_ref(a['training_mapping'])['reference_rows']
    tuning = read_ref(a['tuning_mapping'])['reference_rows']
    retained = {k: v['reference_rows'] for k, v in read_ref(a['retention_mapping']).items()}
    ledger = read_ref(a['fresh_annotation_ledger'])
    augmentation = {}
    for panel in UNITS:
        rich = ledger['reference_rows'][panel]
        pointer.validate_panel(rich, ledger['units'][panel], panel)
        pointer.validate_mapping(read_ref(a[panel + '_targets']), rich)
        augmentation['admitted_attachment_' + panel] = rich
    training = inherited + augmentation['admitted_attachment_fresh_lexical'] + augmentation['admitted_attachment_fresh_structural']
    require(len(training) == 3072 and len(tuning) == 288 and set(retained) == set(RETENTION), 'fixed admitted inventory differs')
    require(wire([project_reference(r) for r in inherited]) == wire(prior['training']), 'inherited 2784 targets changed')
    require(wire([project_reference(r) for r in tuning]) == wire(prior['tuning']), 'selection tuning changed')
    train_sources = {r['source_sha256'] for r in training}
    require(not train_sources & {r['source_sha256'] for r in tuning}, 'training/selection source overlap')
    require(all(not train_sources & {r['source_sha256'] for r in rows} for rows in retained.values()), 'training/diagnostic source overlap')
    return {'prior': prior, 'training': training, 'tuning': tuning, 'retention': retained,
            'history': {**base['history'], **augmentation}, 'historical_source_packs': base['historical_source_packs']}


def exposure_audit(panels, admitted):
    result = pointer.exposure_audit(panels, admitted)
    return {**result, 'schema': 'authored-coupled-span-exposure/v1',
            'prior_attachment_fresh_explicitly_used_for_training': 288,
            'inherited_training_queries_unchanged': 2784,
            'scope': 'Fresh sources and literals within already exposed controlled grammar; no structural novelty, inference owner inventory, legal gold or blanket historical preservation claim.'}


def producers():
    root = Path(__file__).resolve().parents[3]
    return [file_ref(__file__), file_ref(root / 'scripts/ops/legal_ir/prepare_legal_temporal_coupled_span_corpus.py'), *pointer.producers()]


ARTIFACT_KEYS = pointer.ARTIFACT_KEYS | {'training_contrasts', 'training_source_groups'}


def _fixed_manifest():
    return {'schema': SCHEMA, 'counts': COUNTS, 'labels': list(LABELS), 'retention_panels': list(RETENTION),
            'sealed_artifacts': list(SEALED), 'producer_files': producers(), 'source_query_keys': sorted(SOURCE_KEYS),
            'target_keys': sorted(TARGET_KEYS), 'contrast_keys': sorted(CONTRAST_KEYS),
            'previous_attachment_fresh_admitted_training': 288, 'inherited_training_queries': 2784,
            'selection_panel': 'unchanged_placement_tuning', 'source_only_inference': True,
            'owner_reference_features': False, 'contrast_metadata_training_only': True, 'anchor_length_cap': None,
            'shared_evaluation_grammar': True, 'structural_novelty_claimed': False, 'independent_legal_gold': False,
            'blanket_historical_preservation_claimed': False, 'release_rule': RELEASE_RULE}


def build_corpus(output, prior_manifest_path):
    output = Path(output).resolve()
    require(not output.exists(), 'preserve existing corpus')
    admitted = admitted_inputs(prior_manifest_path)
    panels = {panel: make_panel(panel) for panel in UNITS}
    exposure = exposure_audit(panels, admitted)
    training = [project_reference(r) for r in admitted['training']]
    contrasts, groups = build_training_contrasts(training, admitted['training'])
    output.mkdir(parents=True)
    artifacts = {}
    for panel, (rows, _) in panels.items():
        artifacts[panel + '_sources'] = write_new(output / (panel + '-sources.json'), [source_row(r) for r in rows])
    for key in ('training', 'tuning'):
        rows = admitted[key]
        artifacts[key + '_targets'] = write_new(output / (key + '-targets.json'), [project_reference(r) for r in rows])
        artifacts[key + '_mapping'] = write_new(output / (key + '-mapping.json'), _mapping(rows))
    artifacts['training_contrasts'] = write_new(output / 'training-contrasts.json', contrasts)
    artifacts['training_source_groups'] = write_new(output / 'training-source-groups.json', groups)
    artifacts['retention_targets'] = write_new(output / 'retention-targets.json', {k: [project_reference(r) for r in rows] for k, rows in admitted['retention'].items()})
    artifacts['retention_mapping'] = write_new(output / 'retention-mapping.json', {k: _mapping(rows) for k, rows in admitted['retention'].items()})
    ledger = {'schema': ANNOTATION_SCHEMA, 'reference_rows': {}, 'units': {}, 'shared_grammar': True,
              'independent_legal_gold': False, 'owner_reference_features': False}
    for panel, (rows, units) in panels.items():
        artifacts[panel + '_targets'] = write_new(output / (panel + '-targets.json'), [project_reference(r) for r in rows])
        ledger['reference_rows'][panel], ledger['units'][panel] = rows, units
    artifacts['fresh_annotation_ledger'] = write_new(output / 'fresh-annotation-ledger.json', ledger)
    artifacts['exposure_audit'] = write_new(output / 'exposure-audit.json', exposure)
    manifest = {**_fixed_manifest(), 'artifacts': artifacts, 'prior_attachment_corpus': file_ref(prior_manifest_path),
                'admitted_rich_pool_digests': {k: digest(v) for k, v in admitted['history'].items()}}
    pin = write_new(output / 'manifest.json', manifest)
    return {'manifest': pin, 'counts': COUNTS, 'unique_training_anchors': 2304, 'ambiguous_training_nulls': 768,
            'source_groups': len(groups), 'negative_anchor_count': sum(len(x['negative_owner_spans']) for x in contrasts.values()),
            'source_only_inference': True, 'independent_legal_gold': False}


prepare = build_corpus


def load_training_inputs(manifest_path):
    pin = file_ref(manifest_path); m = read_ref(pin); fixed = _fixed_manifest()
    require(type(m) is dict and set(m) == set(fixed) | {'artifacts', 'prior_attachment_corpus', 'admitted_rich_pool_digests'}, 'closed coupled corpus manifest required')
    for key, value in fixed.items():
        require(wire(m[key]) == wire(value), 'manifest contract differs: ' + key)
    require(type(m['artifacts']) is dict and set(m['artifacts']) == ARTIFACT_KEYS, 'complete corpus artifact inventory required')
    for ref in m['artifacts'].values():
        pointer._validate_ref(ref)
    pointer._validate_ref(m['prior_attachment_corpus'])
    require(len({r['path'] for r in m['artifacts'].values()}) == len(ARTIFACT_KEYS), 'artifact aliases rejected')
    read_ref(m['prior_attachment_corpus'])
    admitted = admitted_inputs(m['prior_attachment_corpus']['path'])
    require(wire(m['admitted_rich_pool_digests']) == wire({k: digest(v) for k, v in admitted['history'].items()}), 'admitted source inventory changed')
    a = m['artifacts']; result = {'manifest': m, 'manifest_ref': pin}
    for key in ('training', 'tuning'):
        rows = read_ref(a[key + '_targets']); validate_mapping(rows, admitted[key])
        require(wire(read_ref(a[key + '_mapping'])) == wire(_mapping(admitted[key])), 'admitted mapping differs')
        result[key] = rows
    contrasts, groups = read_ref(a['training_contrasts']), read_ref(a['training_source_groups'])
    validate_training_contrasts(result['training'], admitted['training'], contrasts, groups)
    result['training_contrasts'], result['source_groups'] = contrasts, groups
    retained = read_ref(a['retention_targets'])
    require(type(retained) is dict and set(retained) == set(RETENTION), 'retention panel omission')
    for key, rows in retained.items():
        validate_mapping(rows, admitted['retention'][key])
    require(wire(read_ref(a['retention_mapping'])) == wire({k: _mapping(v) for k, v in admitted['retention'].items()}), 'retention provenance differs')
    result['retention_targets'] = retained
    result['retention_sources'] = {k: [source_row(r) for r in rows] for k, rows in retained.items()}
    seen = {old.normalized_source(r['source_text']) for rows in admitted['history'].values() for r in rows}
    for source_pin in admitted['historical_source_packs']:
        seen.update(old.normalized_source(r['source_text']) for r in read_ref(source_pin))
    for panel in UNITS:
        rows = read_ref(a[panel + '_sources']); validate_query_inventory(rows, expected=144)
        sources = {old.normalized_source(r['source_text']) for r in rows}
        require(len(sources) == 60 and not sources & seen, 'fresh source overlap or incomplete inventory')
        require(all(len(re.findall(r'\w+|[^\w\s]', r['source_text'], re.UNICODE)) <= 256 for r in rows), 'source exceeds encoder budget')
        seen.update(sources); result[panel + '_sources'] = rows
    return result
