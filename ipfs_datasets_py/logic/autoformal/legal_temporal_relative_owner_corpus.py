"""Authored other-norm TRAIN contrasts with separately sealed calibration and test references.

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
from . import legal_temporal_coupled_span_corpus as coupled
pointer = coupled.pointer

stability, previous, paired, old = pointer.stability, pointer.previous, pointer.paired, pointer.old
require, wire, sha, digest, file_ref, read_ref, write_new = (
    getattr(pointer, key) for key in ('require', 'wire', 'sha', 'digest', 'file_ref', 'read_ref', 'write_new'))
query, validate_source_query, propose_time_spans, validate_query_inventory = (
    getattr(pointer, key) for key in ('query', 'validate_source_query', 'propose_time_spans', 'validate_query_inventory'))
SOURCE_KEYS, TARGET_KEYS = pointer.SOURCE_KEYS, pointer.TARGET_KEYS
LABELS, TIME_FORMS = old.LABELS, old.TIME_FORMS
SCHEMA = 'authored-temporal-relative-owner-corpus/v1'
ANNOTATION_SCHEMA = 'authored-temporal-relative-owner-annotation/v1'
AUTHORITY = 'authored_exact_anchor_and_other_norm_contrasts_not_independent_legal_gold'
CALIBRATION_PANELS = ('calibration_lexical', 'calibration_structural')
FRESH_PANELS = ('fresh_lexical', 'fresh_structural')
UNITS = {k: 12 for k in (*CALIBRATION_PANELS, *FRESH_PANELS)}
COUNTS = {'training': 3360, 'tuning': 288, **{k: 144 for k in UNITS}}
CALIBRATION_SEALED = ('calibration_lexical_targets', 'calibration_structural_targets', 'calibration_annotation_ledger', 'calibration_exposure_audit')
FRESH_SEALED = tuple(pointer.SEALED)
SEALED, RETENTION = CALIBRATION_SEALED + FRESH_SEALED, pointer.RETENTION
STRUCTURAL_FAMILIES = stability.STRUCTURAL_FAMILIES
RELEASE_RULE = 'Calibration references open only after training/tuning selection and prediction/replay freeze; fresh references open only after the fixed calibration policy freezes and explicit release.'
CONTRAST_KEYS = {'id', 'source_sha256', 'proposed_time_span', 'negative_owner_spans'}
OWNER_ROLE_TYPES = {'action': 'norm', 'action_object': 'norm', 'condition_predicate': 'condition',
                    'condition_anchor': 'condition', 'exception_predicate': 'exception', 'exception_anchor': 'exception'}
VOCAB = {
    'calibration_lexical': {'names': ('Calvermere', 'Dornwick', 'Eskenhall', 'Fenbray'),
        'actions': ('tabulate', 'crosslist', 'register', 'catalogue'),
        'objects': ('calibration folio', 'custody worksheet', 'routing schedule', 'attestation digest')},
    'calibration_structural': {'names': ('Glenvar', 'Harthwick', 'Ivermere', 'Jorhaven'),
        'actions': ('itemize', 'endorse', 'inventory', 'transcribe'),
        'objects': ('validation folio', 'dispatch worksheet', 'custody schedule', 'entry digest')},
    'fresh_lexical': {'names': ('Kelverton', 'Lorhaven', 'Mornwick', 'Norbridge'),
        'actions': ('attest', 'enumerate', 'countersign', 'collate'),
        'objects': ('attachment folio', 'depository worksheet', 'arrival schedule', 'certification digest')},
    'fresh_structural': {'names': ('Ostermere', 'Penwick', 'Quorhaven', 'Ravenholt'),
        'actions': ('annotate', 'index', 'record', 'notarize'),
        'objects': ('relative folio', 'consignment worksheet', 'lodgment schedule', 'registration digest')},
}
HEADINGS = ('Relative owner illustration {n}: ', '[Attachment study {n}] ', 'Timing assignment {n}. — ')

source_row = pointer.source_row
validate_target = pointer.validate_target
validate_training_row = pointer.validate_target


def factors(split, unit, source):
    require(split in UNITS, 'known new evaluation panel required')
    return stability.factors('fresh_structural' if split.endswith('_structural') else 'fresh_lexical', unit, source)


def literal(split, unit, form):
    require(split in UNITS and type(unit) is int and 0 <= unit < 12 and form in TIME_FORMS, 'bounded literal factors required')
    index = list(UNITS).index(split)
    amount, year, day = 231 + 20 * index + unit, 2121 + index, unit + 1
    return {'days': f'within {amount} days of notice', 'hours': f'within {amount} hours of notice',
            'iso_date': f'before {year}-09-{day:02d}', 'month_date': f'before September {day}, {year}'}[form]

def render_source(split, unit, source):
    labels, form, modality, placement, family, layout, enclosure, order, pattern, rotation = factors(split, unit, source)
    case = unit * 5 + source
    identity = 180000 + list(UNITS).index(split) * 1000 + case
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
            if split.endswith('_structural') and index == 0 and family == STRUCTURAL_FAMILIES[0]:
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
            if split.endswith('_structural') and index == 0 and family == STRUCTURAL_FAMILIES[1]:
                joint_qualifiers()
                w.add(' ')
            anchor = role(f"{v['actions'][(case + index) % 4]} the {v['objects'][(case + index) % 4]} {identity}-{index + 1}", 'action')
            if slot is not None and placement == 'after_action':
                w.add(', ')
                emit_time(slot)
            norms.append({'owner_type': 'norm', 'anchor_span': anchor, 'scope_span': w.span(begin, len(w.text)),
                          'cue_span': cue, 'actor_span': actor, 'query_slot': slot, 'atom_ordinal': index + 1})
        blocks['norm'] = w.span(start, len(w.text))

    if split.endswith('_structural'):
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
        coupled.validate_authored_reference(row)
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


def build_other_norm_contrasts(targets, references):
    """Derive other-norm action negatives only for norm targets in complete TRAIN sources."""
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
            if target['label'] == 'norm':
                require(sum(o['owner_type'] == target['label'] and wire(o['anchor_span']) == wire(positive) for o in owners) == 1,
                        'positive anchor absent from complete authored role inventory')
                time = target['proposed_time_span']
                negatives = [deepcopy(o['anchor_span']) for o in owners if o['owner_type'] == 'norm' and wire(o['anchor_span']) != wire(positive)
                             and (o['anchor_span']['char_end'] <= time['char_start'] or o['anchor_span']['char_start'] >= time['char_end'])]
            contrasts[target['id']] = {'id': target['id'], 'source_sha256': source_sha,
                                      'proposed_time_span': deepcopy(target['proposed_time_span']),
                                      'negative_owner_spans': negatives}
    require(set(contrasts) == {r['id'] for r in targets}, 'complete contrast query inventory required')
    return contrasts, groups


def validate_other_norm_contrasts(targets, references, contrasts, groups):
    require(type(contrasts) is dict and type(groups) is list, 'contrast map and source groups required')
    expected, expected_groups = build_other_norm_contrasts(targets, references)
    require(wire(contrasts) == wire(expected) and wire(groups) == wire(expected_groups), 'source-bound TRAIN contrast metadata differs')
    return True


def make_panel(split):
    require(split in UNITS, 'known evaluation panel required')
    rows, units = [], []
    for unit in range(12):
        values = [r for source in range(5) for r in render_source(split, unit, source)]
        rows.extend(values)
        units.append({'unit_id': values[0]['annotation']['unit_id'], 'query_ids': sorted(r['id'] for r in values)})
    random.Random(182401 + list(UNITS).index(split)).shuffle(rows)
    validate_panel(rows, units, split)
    return rows, units


def validate_panel(rows, units, split):
    require(split in UNITS and type(rows) is list and type(units) is list, 'known complete evaluation panel required')
    require(len(rows) == 144 and len(units) == 12 and len({r['source_sha256'] for r in rows}) == 60, 'evaluation inventory differs')
    lookup = {r['id']: r for r in rows}; require(len(lookup) == len(rows), 'duplicate query identity')
    seen, seen_sources, unit_ids = set(), set(), set()
    for unit in units:
        require(type(unit) is dict and set(unit) == {'unit_id', 'query_ids'} and type(unit['query_ids']) is list
                and len(unit['query_ids']) == len(set(unit['query_ids'])) == 12
                and unit['query_ids'] == sorted(unit['query_ids']) and set(unit['query_ids']) <= set(lookup)
                and unit['unit_id'] not in unit_ids and not seen.intersection(unit['query_ids']), 'closed complete unit required')
        selected = [lookup[k] for k in unit['query_ids']]; grouped = defaultdict(list)
        for row in selected:
            require(row['annotation']['unit_id'] == unit['unit_id'] and row['annotation']['split'] == split, 'unit source join differs')
            grouped[row['source_sha256']].append(row)
        require(Counter(len(v) for v in grouped.values()) == Counter({2: 3, 3: 2}) and not seen_sources.intersection(grouped), 'source-complete pair/triple units required')
        require(Counter(r['label'] for r in selected) == Counter({k: 3 for k in LABELS}) and
                len({r['annotation']['time_span']['text'] for r in selected}) == 1, 'matched balanced class/time unit required')
        for values in grouped.values(): validate_query_inventory([source_row(r) for r in values], expected=len(values))
        seen.update(unit['query_ids']); seen_sources.update(grouped); unit_ids.add(unit['unit_id'])
    require(seen == set(lookup), 'unassigned source query')
    require(Counter(r['annotation']['modality'] for r in rows) == Counter({k: 48 for k in 'OPF'}), 'modality balance differs')
    require(Counter(r['annotation']['time_form'] for r in rows) == Counter({k: 36 for k in TIME_FORMS}), 'time-form balance differs')
    for row in rows: project_reference(row)
    return rows


def _mapping(rows):
    return {'schema': 'authored-relative-owner-reference-mapping/v1', 'reference_rows': deepcopy(rows),
            'reference_rows_sha256': digest(rows), 'pointer_targets_sha256': digest([project_reference(r) for r in rows]),
            'ambiguous_targets_are_null': True, 'reference_candidates_are_not_inference_inputs': True,
            'independent_legal_gold': False}


def admitted_inputs(prior_manifest_path):
    prior = coupled.load_training_inputs(prior_manifest_path)
    a = prior['manifest']['artifacts']
    base = coupled.admitted_inputs(prior['manifest']['prior_attachment_corpus']['path'])
    inherited = read_ref(a['training_mapping'])['reference_rows']
    tuning = read_ref(a['tuning_mapping'])['reference_rows']
    retained = {k: v['reference_rows'] for k, v in read_ref(a['retention_mapping']).items()}
    ledger = read_ref(a['fresh_annotation_ledger']); augmentation = {}
    for panel in FRESH_PANELS:
        rich = ledger['reference_rows'][panel]
        coupled.validate_panel(rich, ledger['units'][panel], panel)
        coupled.validate_mapping(read_ref(a[panel + '_targets']), rich)
        augmentation['admitted_coupled_' + panel] = rich
    training = inherited + augmentation['admitted_coupled_fresh_lexical'] + augmentation['admitted_coupled_fresh_structural']
    require(len(training) == 3360 and len(tuning) == 288 and set(retained) == set(RETENTION), 'fixed admitted inventory differs')
    require(wire([project_reference(r) for r in inherited]) == wire(prior['training']), 'inherited 3072 targets changed')
    require(wire([project_reference(r) for r in tuning]) == wire(prior['tuning']), 'selection tuning changed')
    train_sources = {r['source_sha256'] for r in training}
    require(not train_sources & {r['source_sha256'] for r in tuning}, 'training/selection source overlap')
    require(all(not train_sources & {r['source_sha256'] for r in rows} for rows in retained.values()), 'training/retention source overlap')
    return {'prior': prior, 'training': training, 'tuning': tuning, 'retention': retained,
            'history': {**base['history'], **augmentation}, 'historical_source_packs': base['historical_source_packs']}


def exposure_audit(panels, admitted):
    result = pointer.exposure_audit(panels, admitted)
    historical_texts = [r['source_text'].casefold() for rows in admitted['history'].values() for r in rows]
    for pin in admitted['historical_source_packs']:
        historical_texts.extend(r['source_text'].casefold() for r in read_ref(pin))
    names = []
    for panel, (rows, _) in panels.items():
        declared = VOCAB[panel]['names']
        require(all(not any(re.search(r'\b' + re.escape(name.casefold()) + r'\b', text) for text in historical_texts)
                    for name in declared), 'new entity namespace occurs in historical sources')
        require(all(any(name in row['source_text'] for name in declared) for row in rows), 'new entity namespace not realized')
        names.extend(declared)
    require(len(names) == len(set(names)), 'entity namespaces cross new panels')
    return {**result, 'schema': 'authored-relative-owner-exposure/v1',
            'prior_attachment_fresh_explicitly_used_for_training': 288,
            'prior_coupled_fresh_explicitly_used_for_training': 288,
            'inherited_training_queries_unchanged': 3072,
            'entity_namespaces': {k: list(VOCAB[k]['names']) for k in panels},
            'calibration_and_fresh_labels_separately_sealed': True,
            'scope': 'Source/literal/entity/group exclusion within shared controlled grammar; no independently established statutory ownership.'}


def producers():
    root = Path(__file__).resolve().parents[3]
    return [file_ref(__file__), file_ref(root / 'scripts/ops/legal_ir/prepare_legal_temporal_relative_owner_corpus.py'), *coupled.producers()]


ARTIFACT_KEYS = ((coupled.ARTIFACT_KEYS - {'training_contrasts'}) |
                 {'training_other_norm_contrasts', *CALIBRATION_SEALED, *(k + '_sources' for k in CALIBRATION_PANELS)})


def _fixed_manifest():
    return {'schema': SCHEMA, 'counts': COUNTS, 'labels': list(LABELS), 'retention_panels': list(RETENTION),
            'sealed_artifacts': list(SEALED), 'calibration_sealed_artifacts': list(CALIBRATION_SEALED),
            'fresh_sealed_artifacts': list(FRESH_SEALED), 'producer_files': producers(),
            'source_query_keys': sorted(SOURCE_KEYS), 'target_keys': sorted(TARGET_KEYS), 'contrast_keys': sorted(CONTRAST_KEYS),
            'previous_coupled_fresh_admitted_training': 288, 'inherited_training_queries': 3072,
            'selection_panel': 'unchanged_placement_tuning', 'source_only_inference': True,
            'calibration_used_for_fitting': False, 'calibration_used_for_checkpoint_selection': False,
            'owner_reference_features': False, 'contrast_metadata_training_only': True,
            'contrast_supervised_label': 'norm', 'non_norm_contrasts_empty': True, 'anchor_length_cap': None,
            'shared_evaluation_grammar': True, 'structural_novelty_claimed': False, 'independent_legal_gold': False,
            'blanket_historical_preservation_claimed': False, 'release_rule': RELEASE_RULE}


def build_corpus(output, prior_manifest_path):
    output = Path(output).resolve(); require(not output.exists(), 'preserve existing corpus')
    admitted = admitted_inputs(prior_manifest_path)
    panels = {panel: make_panel(panel) for panel in UNITS}
    exposure = exposure_audit(panels, admitted)
    training = [project_reference(r) for r in admitted['training']]
    contrasts, groups = build_other_norm_contrasts(training, admitted['training'])
    output.mkdir(parents=True); artifacts = {}
    for panel, (rows, _) in panels.items():
        artifacts[panel + '_sources'] = write_new(output / (panel + '-sources.json'), [source_row(r) for r in rows])
    for key in ('training', 'tuning'):
        rows = admitted[key]
        artifacts[key + '_targets'] = write_new(output / (key + '-targets.json'), [project_reference(r) for r in rows])
        artifacts[key + '_mapping'] = write_new(output / (key + '-mapping.json'), _mapping(rows))
    artifacts['training_other_norm_contrasts'] = write_new(output / 'training-other-norm-contrasts.json', contrasts)
    artifacts['training_source_groups'] = write_new(output / 'training-source-groups.json', groups)
    artifacts['retention_targets'] = write_new(output / 'retention-targets.json', {k: [project_reference(r) for r in rows] for k, rows in admitted['retention'].items()})
    artifacts['retention_mapping'] = write_new(output / 'retention-mapping.json', {k: _mapping(rows) for k, rows in admitted['retention'].items()})
    source_refs = {panel: artifacts[panel + '_sources'] for panel in UNITS}
    for stage, panel_names in (('calibration', CALIBRATION_PANELS), ('fresh', FRESH_PANELS)):
        ledger = {'schema': ANNOTATION_SCHEMA, 'stage': stage, 'reference_rows': {}, 'units': {},
                  'shared_grammar': True, 'independent_legal_gold': False, 'owner_reference_features': False}
        for panel in panel_names:
            rows, units = panels[panel]
            artifacts[panel + '_targets'] = write_new(output / (panel + '-targets.json'), [project_reference(r) for r in rows])
            ledger['reference_rows'][panel], ledger['units'][panel] = rows, units
        artifacts[stage + '_annotation_ledger'] = write_new(output / (stage + '-annotation-ledger.json'), ledger)
        staged_exposure = {**exposure, 'stage': stage, 'panels': {k: exposure['panels'][k] for k in panel_names},
                           'entity_namespaces': {k: exposure['entity_namespaces'][k] for k in panel_names},
                           'all_new_source_packs': source_refs, 'new_panel_sources_mutually_disjoint': True}
        key = 'calibration_exposure_audit' if stage == 'calibration' else 'exposure_audit'
        artifacts[key] = write_new(output / (stage + '-exposure-audit.json'), staged_exposure)
    manifest = {**_fixed_manifest(), 'artifacts': artifacts, 'prior_coupled_corpus': file_ref(prior_manifest_path),
                'admitted_rich_pool_digests': {k: digest(v) for k, v in admitted['history'].items()}}
    pin = write_new(output / 'manifest.json', manifest)
    return {'manifest': pin, 'counts': COUNTS, 'unique_training_anchors': 2520, 'ambiguous_training_nulls': 840,
            'source_groups': len(groups), 'other_norm_negative_count': sum(len(x['negative_owner_spans']) for x in contrasts.values()),
            'norm_queries_with_negative': sum(bool(x['negative_owner_spans']) for x in contrasts.values()),
            'source_only_inference': True, 'independent_legal_gold': False}


prepare = build_corpus


def _read_manifest(manifest_path):
    pin = file_ref(manifest_path); m = read_ref(pin); fixed = _fixed_manifest()
    require(type(m) is dict and set(m) == set(fixed) | {'artifacts', 'prior_coupled_corpus', 'admitted_rich_pool_digests'}, 'closed relative-owner corpus manifest required')
    for key, value in fixed.items():
        require(wire(m[key]) == wire(value), 'manifest contract differs: ' + key)
    require(type(m['artifacts']) is dict and set(m['artifacts']) == ARTIFACT_KEYS, 'complete corpus artifact inventory required')
    for ref in m['artifacts'].values(): pointer._validate_ref(ref)
    pointer._validate_ref(m['prior_coupled_corpus'])
    require(len({r['path'] for r in m['artifacts'].values()}) == len(ARTIFACT_KEYS), 'artifact aliases rejected')
    return pin, m


def load_training_inputs(manifest_path):
    """Open admitted TRAIN/tune/history and source-only packs; never eight current semantic artifacts."""
    pin, m = _read_manifest(manifest_path)
    read_ref(m['prior_coupled_corpus']); admitted = admitted_inputs(m['prior_coupled_corpus']['path'])
    require(wire(m['admitted_rich_pool_digests']) == wire({k: digest(v) for k, v in admitted['history'].items()}), 'admitted inventory changed')
    a = m['artifacts']; result = {'manifest': m, 'manifest_ref': pin}
    for key in ('training', 'tuning'):
        rows = read_ref(a[key + '_targets']); validate_mapping(rows, admitted[key])
        require(wire(read_ref(a[key + '_mapping'])) == wire(_mapping(admitted[key])), 'admitted mapping differs')
        result[key] = rows
    contrasts, groups = read_ref(a['training_other_norm_contrasts']), read_ref(a['training_source_groups'])
    validate_other_norm_contrasts(result['training'], admitted['training'], contrasts, groups)
    result['training_other_norm_contrasts'], result['source_groups'] = contrasts, groups
    retained = read_ref(a['retention_targets'])
    require(type(retained) is dict and set(retained) == set(RETENTION), 'retention panel omission')
    for key, rows in retained.items(): validate_mapping(rows, admitted['retention'][key])
    require(wire(read_ref(a['retention_mapping'])) == wire({k: _mapping(v) for k, v in admitted['retention'].items()}), 'retention provenance differs')
    result['retention_targets'] = retained
    result['retention_sources'] = {k: [source_row(r) for r in rows] for k, rows in retained.items()}
    seen = {old.normalized_source(r['source_text']) for rows in admitted['history'].values() for r in rows}
    seen_ids = {r['id'] for rows in admitted['history'].values() for r in rows}
    times = {r['annotation']['time_span']['text'] for rows in admitted['history'].values() for r in rows}
    for source_pin in admitted['historical_source_packs']:
        for row in read_ref(source_pin):
            identity = row.get('id', row.get('candidate_id'))
            require(type(identity) is str and identity, 'historical source identity missing')
            seen.add(old.normalized_source(row['source_text'])); seen_ids.add(identity)
            times.update(row['source_text'][s['char_start']:s['char_end']] for s in propose_time_spans(row['source_text']))
    for panel in UNITS:
        rows = read_ref(a[panel + '_sources']); validate_query_inventory(rows, expected=144)
        texts = {old.normalized_source(r['source_text']) for r in rows}; ids = {r['id'] for r in rows}
        literals = {r['source_text'][r['proposed_time_span']['char_start']:r['proposed_time_span']['char_end']] for r in rows}
        require(len(texts) == 60 and not texts & seen and not ids & seen_ids and not literals & times, 'new source/query/literal overlap or incomplete inventory')
        require(all(len(re.findall(r'\w+|[^\w\s]', r['source_text'], re.UNICODE)) <= 256 for r in rows), 'source exceeds encoder budget')
        seen.update(texts); seen_ids.update(ids); times.update(literals); result[panel + '_sources'] = rows
    return result


def validate_stage_references(targets, ledger, *, stage):
    """Pure postrelease validation; does not decide whether references may be opened."""
    names = CALIBRATION_PANELS if stage == 'calibration' else FRESH_PANELS if stage == 'fresh' else ()
    require(bool(names) and type(targets) is dict and set(targets) == set(names), 'complete declared stage targets required')
    require(type(ledger) is dict and set(ledger) == {'schema', 'stage', 'reference_rows', 'units', 'shared_grammar',
            'independent_legal_gold', 'owner_reference_features'} and ledger['schema'] == ANNOTATION_SCHEMA
            and ledger['stage'] == stage and ledger['shared_grammar'] is True and ledger['independent_legal_gold'] is False
            and ledger['owner_reference_features'] is False, 'closed stage reference ledger required')
    require(set(ledger['reference_rows']) == set(ledger['units']) == set(names), 'cross-stage reference ledger leakage')
    for panel in names:
        validate_panel(ledger['reference_rows'][panel], ledger['units'][panel], panel)
        validate_mapping(targets[panel], ledger['reference_rows'][panel])
    return True
