"""Source-span owner attachment supervision for an authored research pilot.

Legacy references supply training labels only. Numerical input is the unchanged
four-field source query; no owner inventory, cue, scope or length cap is supplied.
New evaluation uses the already exposed controlled grammar, not legal gold or a
claim of new structural transfer. All offsets are Unicode code-point intervals.
"""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import random
import re

from . import legal_temporal_stability_corpus as stability

previous = stability.previous
paired = stability.paired
old = stability.old
require, wire, sha, digest, file_ref, read_ref, write_new = (
    getattr(old, key) for key in ('require', 'wire', 'sha', 'digest', 'file_ref', 'read_ref', 'write_new'))
query, validate_source_query, propose_time_spans, validate_query_inventory = (
    getattr(old, key) for key in ('query', 'validate_source_query', 'propose_time_spans', 'validate_query_inventory'))
SOURCE_KEYS = old.SOURCE_KEYS
TARGET_KEYS = SOURCE_KEYS | {'label', 'group_id', 'owner_anchor_span'}
LABELS, TIME_FORMS = old.LABELS, old.TIME_FORMS
SCHEMA = 'authored-temporal-owner-pointer-corpus/v1'
ANNOTATION_SCHEMA = 'authored-temporal-owner-pointer-annotation/v1'
AUTHORITY = 'authored_exact_anchor_not_independent_legal_gold'
COUNTS = {'training': 2784, 'tuning': 288, 'fresh_lexical': 144, 'fresh_structural': 144}
UNITS = {'fresh_lexical': 12, 'fresh_structural': 12}
SEALED = ('fresh_lexical_targets', 'fresh_structural_targets', 'fresh_annotation_ledger', 'exposure_audit')
STRUCTURAL_FAMILIES = stability.STRUCTURAL_FAMILIES
RETENTION = stability.RETENTION
RELEASE_RULE = 'Current semantic references stay sealed until selection, source-only prediction and independent replay freeze.'
VOCAB = {
    'fresh_lexical': {'names': ('Altair', 'Bellatrix', 'Canopus', 'Deneb'),
                      'actions': ('certify', 'tabulate', 'endorse', 'summarize'),
                      'objects': ('routing account', 'delivery index', 'status digest', 'case inventory')},
    'fresh_structural': {'names': ('Electra', 'Fomalhaut', 'Gemma', 'Hadar'),
                         'actions': ('authenticate', 'annotate', 'compile', 'recapitulate'),
                         'objects': ('service abstract', 'dispatch logbook', 'review summary', 'receipt compendium')},
}
HEADINGS = ('Attachment case {n}: ', '[Timing example {n}] ', 'Research item {n}. — ')


def source_row(row):
    return validate_source_query({key: deepcopy(row[key]) for key in SOURCE_KEYS})


def factors(split, unit, source):
    require(split in UNITS, 'known evaluation panel required')
    return stability.factors('fresh_lexical' if split == 'fresh_lexical' else 'fresh_structural', unit, source)


def literal(split, unit, form):
    require(split in UNITS and type(unit) is int and 0 <= unit < 12 and form in TIME_FORMS, 'bounded literal factors required')
    index = list(UNITS).index(split)
    amount, year, day = 941 + 20 * index + unit, 2101 + index, unit + 1
    return {'days': f'within {amount} days of notice', 'hours': f'within {amount} hours of notice',
            'iso_date': f'before {year}-09-{day:02d}', 'month_date': f'before September {day}, {year}'}[form]

def render_source(split, unit, source):
    labels, form, modality, placement, family, layout, enclosure, order, pattern, rotation = factors(split, unit, source)
    case = unit * 5 + source
    identity = 140000 + list(UNITS).index(split) * 1000 + case
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


def validate_target(row):
    """Validate supervised wire integrity; authoritative meaning is checked separately."""
    require(type(row) is dict and set(row) == TARGET_KEYS, 'closed seven-field pointer target required')
    source_row(row)
    require(type(row['label']) is str and row['label'] in LABELS and
            type(row['group_id']) is str and bool(row['group_id']), 'label and provenance group required')
    tokens = list(re.finditer(r'\w+|[^\w\s]', row['source_text'], re.UNICODE))
    require(0 < len(tokens) <= 256, 'source exceeds frozen encoder token budget')
    value = row['owner_anchor_span']
    if row['label'] == 'ambiguous':
        require(value is None, 'ambiguous target must not select an owner')
    else:
        require(type(value) is dict and set(value) == {'char_start', 'char_end'}, 'closed owner interval required')
        lo, hi = value['char_start'], value['char_end']
        require(type(lo) is int and type(hi) is int and 0 <= lo < hi <= len(row['source_text']), 'integer owner interval required')
        require(lo in {t.start() for t in tokens} and hi in {t.end() for t in tokens}, 'whole owner tokens required')
        time = row['proposed_time_span']
        require(hi <= time['char_start'] or time['char_end'] <= lo, 'owner anchor overlaps queried time')
    return row


def validate_authored_reference(row):
    schema = row['annotation'].get('schema')
    if schema == ANNOTATION_SCHEMA:
        a = row['annotation']
        expected = [x for x in render_source(a.get('split'), a.get('unit_index'), a.get('source_index')) if x['id'] == row['id']]
        require(len(expected) == 1 and wire(expected[0]) == wire(row), 'new reference differs from exact insertion provenance')
    else:
        validators = {m.ANNOTATION_SCHEMA: m.validate_target for m in (old, paired, previous, stability)}
        require(schema in validators, 'unrecognized authored reference schema')
        validators[schema](row)
    return row


def _exact_span(text, value):
    require(type(value) is dict and set(value) == {'char_start', 'char_end', 'text'}, 'closed exact reference span required')
    lo, hi = value['char_start'], value['char_end']
    require(type(lo) is int and type(hi) is int and 0 <= lo < hi <= len(text) and
            type(value['text']) is str and text[lo:hi] == value['text'], 'reference span source binding differs')
    return {'char_start': lo, 'char_end': hi}


def project_reference(row, *, reconstruct=True):
    """Convert exact authored references, never selecting one alternative arbitrarily."""
    if reconstruct:
        validate_authored_reference(row)
    q, a, label = source_row(row), row['annotation'], row['label']
    require(label in LABELS and type(a.get('owner_candidates')) is list, 'explicit reference candidates required')
    candidates = a['owner_candidates']
    uniqueness = a.get('unique_owner_occurrence_asserted', a.get('unique_owner_asserted'))
    require(uniqueness is (label != 'ambiguous'), 'reference must explicitly assert unique or ambiguous ownership')
    identities = []
    for candidate in candidates:
        kind = candidate.get('owner_type', candidate.get('owner'))
        require(kind in LABELS[:3], 'concrete reference owner type required')
        anchor = _exact_span(row['source_text'], candidate['anchor_span'])
        validate_target({**q, 'label': kind, 'group_id': row['group_id'], 'owner_anchor_span': anchor})
        identities.append((kind, anchor['char_start'], anchor['char_end']))
    require(len(set(identities)) == len(identities), 'duplicate reference owner occurrence')
    if label == 'ambiguous':
        require(len(identities) >= 2 and a.get('countermodels') is not None, 'ambiguity requires explicit distinct alternatives and countermodels')
        anchor = None
    else:
        require(len(candidates) == 1 and identities[0][0] == label, 'unique owner requires exactly one matching reference candidate')
        anchor = _exact_span(row['source_text'], candidates[0]['anchor_span'])
        if label == 'norm' and 'norm_occurrences' in a:
            matches = [n for n in a['norm_occurrences'] if n['time_span'] is not None and
                       wire(_exact_span(row['source_text'], n['time_span'])) == wire(q['proposed_time_span'])]
            require(len(matches) == 1, 'norm query must select exactly one explicit time occurrence')
            require(wire(_exact_span(row['source_text'], matches[0]['action_span'])) == wire(anchor), 'repeated norm action differs from reference anchor')
            for key in ('actor_span', 'modal_span', 'clause_span'):
                _exact_span(row['source_text'], matches[0][key])
    return validate_target({**q, 'label': label, 'group_id': row['group_id'], 'owner_anchor_span': anchor})


target_projection = project_reference
validate_training_row = validate_target


def validate_mapping(targets, references):
    require(type(targets) is list and type(references) is list and len(targets) == len(references), 'complete reference mapping required')
    require(len({r['id'] for r in targets}) == len(targets), 'duplicate pointer query')
    expected = [project_reference(row) for row in references]
    require(wire(targets) == wire(expected), 'pointer targets differ from authoritative reference mapping')
    validate_query_inventory([source_row(r) for r in targets], expected=len(targets))
    return targets


def make_panel(split):
    require(split in UNITS, 'known evaluation panel required')
    rows, units = [], []
    for unit in range(12):
        values = [r for source in range(5) for r in render_source(split, unit, source)]
        rows.extend(values)
        units.append({'unit_id': values[0]['annotation']['unit_id'], 'query_ids': sorted(r['id'] for r in values)})
    random.Random(142401 + list(UNITS).index(split)).shuffle(rows)
    validate_panel(rows, units, split)
    return rows, units


def validate_panel(rows, units, split):
    require(split in UNITS, 'known evaluation panel required')
    paired.validate_units(rows, units, split, reconstruct=False)
    require(len(rows) == 144 and len(units) == 12 and len({r['source_sha256'] for r in rows}) == 60, 'evaluation inventory differs')
    require(Counter(r['label'] for r in rows) == Counter({k: 36 for k in LABELS}), 'class margins differ')
    require(Counter(r['annotation']['modality'] for r in rows) == Counter({k: 48 for k in 'OPF'}), 'modality margins differ')
    require(Counter(r['annotation']['time_form'] for r in rows) == Counter({k: 36 for k in TIME_FORMS}), 'time-form margins differ')
    for row in rows:
        project_reference(row)
    return rows


def _mapping(rows):
    return {'schema': 'authored-owner-pointer-reference-mapping/v1',
            'reference_rows': deepcopy(rows), 'reference_rows_sha256': digest(rows),
            'pointer_targets_sha256': digest([project_reference(r) for r in rows]),
            'ambiguous_targets_are_null': True, 'reference_candidates_are_not_inference_inputs': True,
            'independent_legal_gold': False}


def admitted_inputs(prior_manifest_path):
    prior = stability.load_training_inputs(prior_manifest_path)
    history, source_packs = stability.historical_inputs(prior['prior_inputs'])
    augmented = {}
    for split in ('fresh_lexical', 'fresh_structural'):
        rows = read_ref(prior['manifest']['artifacts'][split + '_targets'])
        for row in rows:
            stability.validate_target(row)
        augmented['admitted_stability_' + split] = rows
    train = prior['single_training'] + prior['prior_paired_training'] + prior['placement_training']
    train += augmented['admitted_stability_fresh_lexical'] + augmented['admitted_stability_fresh_structural']
    tuning = prior['placement_tuning']
    retained = prior['retention_targets']
    require(len(train) == 2784 and len(tuning) == 288 and set(retained) == set(RETENTION), 'admitted inventory differs')
    train_sources = {r['source_sha256'] for r in train}
    require(not train_sources & {r['source_sha256'] for r in tuning}, 'training and selection source overlap')
    require(all(not train_sources & {r['source_sha256'] for r in rows} for rows in retained.values()), 'training and diagnostic source overlap')
    return {'prior': prior, 'training': train, 'tuning': tuning, 'retention': retained,
            'history': {**history, **augmented}, 'historical_source_packs': source_packs}


def exposure_audit(panels, admitted):
    history, sources, groups, literals, layouts = {}, set(), set(), set(), set()
    for name, rows in admitted['history'].items():
        masks = {stability.body_layout(r) for r in rows}
        sources.update(old.normalized_source(r['source_text']) for r in rows)
        groups.update(r['group_id'] for r in rows)
        literals.update(r['annotation']['time_span']['text'] for r in rows)
        layouts.update(masks)
        history[name] = {'queries': len(rows), 'sources': len({r['source_sha256'] for r in rows}),
                         'rows_sha256': digest(rows), 'body_layouts': sorted(masks)}
    for pin in admitted['historical_source_packs']:
        for row in read_ref(pin):
            require(row['source_sha256'] == sha(row['source_text']), 'historical source mismatch')
            sources.add(old.normalized_source(row['source_text']))
            literals.update(row['source_text'][t['char_start']:t['char_end']] for t in propose_time_spans(row['source_text']))
    result = {}
    historical_count = len(sources)
    for name, (rows, units) in panels.items():
        current_sources = {old.normalized_source(r['source_text']) for r in rows}
        current_groups = {r['group_id'] for r in rows}
        current_literals = {r['annotation']['time_span']['text'] for r in rows}
        require(not current_sources & sources and not current_groups & groups and not current_literals & literals, 'evaluation source/group/literal exposure overlap')
        masks = [stability.body_layout(r) for r in rows]
        result[name] = {'queries': len(rows), 'sources': len(current_sources), 'units': len(units),
            'class_counts': dict(Counter(r['label'] for r in rows)), 'normalized_body_layouts': sorted(set(masks)),
            'matches_prior_body_layout_queries': sum(m in layouts for m in masks),
            'source_hashes': sorted({r['source_sha256'] for r in rows}), 'time_literals': sorted(current_literals),
            'novel_structure_claimed': False, 'source_overlap': 0}
        sources.update(current_sources); groups.update(current_groups); literals.update(current_literals)
    return {'schema': 'authored-owner-pointer-exposure/v1', 'prior_annotated_pools': history,
            'historical_source_packs': admitted['historical_source_packs'], 'panels': result,
            'historical_unique_sources_checked': historical_count, 'shared_grammar': True,
            'prior_stability_fresh_explicitly_used_for_training': 288, 'independent_legal_gold': False,
            'scope': 'Exact and normalized source exclusion, fresh literals, shared controlled layouts; no legal semantics or structural novelty.'}


def producers():
    root = Path(__file__).resolve().parents[3]
    return [file_ref(__file__), file_ref(root / 'scripts/ops/legal_ir/prepare_legal_temporal_owner_pointer_corpus.py'),
            *[file_ref(m.__file__) for m in (stability, previous, paired, old)]]


ARTIFACT_KEYS = {'training_targets', 'tuning_targets', 'retention_targets', 'training_mapping', 'tuning_mapping',
                 'retention_mapping', 'fresh_lexical_sources', 'fresh_structural_sources', *SEALED}


def _fixed_manifest():
    return {'schema': SCHEMA, 'counts': COUNTS, 'labels': list(LABELS), 'retention_panels': list(RETENTION),
            'sealed_artifacts': list(SEALED), 'producer_files': producers(), 'source_query_keys': sorted(SOURCE_KEYS),
            'target_keys': sorted(TARGET_KEYS), 'previous_stability_fresh_admitted_training': 288,
            'old_training_queries_reused': 2496, 'selection_panel': 'unchanged_placement_tuning',
            'source_only_inference': True, 'owner_reference_features': False, 'anchor_length_cap': None,
            'shared_evaluation_grammar': True, 'structural_novelty_claimed': False, 'independent_legal_gold': False,
            'release_rule': RELEASE_RULE}


def build_corpus(output, prior_manifest_path):
    output = Path(output).resolve()
    require(not output.exists(), 'preserve existing corpus')
    admitted = admitted_inputs(prior_manifest_path)
    panels = {name: make_panel(name) for name in UNITS}
    exposure = exposure_audit(panels, admitted)
    output.mkdir(parents=True)
    artifacts = {}
    # Source packs are written before their sealed reference counterparts.
    for split, (rows, _) in panels.items():
        artifacts[split + '_sources'] = write_new(output / (split + '-sources.json'), [source_row(r) for r in rows])
    for key in ('training', 'tuning'):
        rows = admitted[key]
        targets = [project_reference(r) for r in rows]
        validate_mapping(targets, rows)
        artifacts[key + '_targets'] = write_new(output / (key + '-targets.json'), targets)
        artifacts[key + '_mapping'] = write_new(output / (key + '-mapping.json'), _mapping(rows))
    artifacts['retention_targets'] = write_new(output / 'retention-targets.json',
        {k: [project_reference(r) for r in rows] for k, rows in admitted['retention'].items()})
    artifacts['retention_mapping'] = write_new(output / 'retention-mapping.json',
        {k: _mapping(rows) for k, rows in admitted['retention'].items()})
    ledger = {'schema': ANNOTATION_SCHEMA, 'reference_rows': {}, 'units': {}, 'shared_grammar': True,
              'independent_legal_gold': False, 'owner_reference_features': False}
    for split, (rows, units) in panels.items():
        artifacts[split + '_targets'] = write_new(output / (split + '-targets.json'), [project_reference(r) for r in rows])
        ledger['reference_rows'][split] = rows
        ledger['units'][split] = units
    artifacts['fresh_annotation_ledger'] = write_new(output / 'fresh-annotation-ledger.json', ledger)
    artifacts['exposure_audit'] = write_new(output / 'exposure-audit.json', exposure)
    manifest = {**_fixed_manifest(), 'artifacts': artifacts, 'prior_stability_corpus': file_ref(prior_manifest_path),
                'admitted_rich_pool_digests': {k: digest(v) for k, v in admitted['history'].items()}}
    manifest_ref = write_new(output / 'manifest.json', manifest)
    return {'manifest': manifest_ref, 'counts': COUNTS, 'unique_training_anchors': 2088,
            'ambiguous_training_nulls': 696, 'source_only_inference': True, 'independent_legal_gold': False}


prepare = build_corpus


def _validate_ref(pin):
    require(type(pin) is dict and set(pin) == {'path', 'sha256', 'bytes'} and
            type(pin['path']) is str and Path(pin['path']).is_absolute() and
            type(pin['sha256']) is str and re.fullmatch('[0-9a-f]{64}', pin['sha256']) is not None and
            type(pin['bytes']) is int and 0 <= pin['bytes'] <= old.MAX_FILE_BYTES, 'closed immutable reference required')


def load_training_inputs(manifest_path):
    pin = file_ref(manifest_path)
    m = read_ref(pin)
    fixed = _fixed_manifest()
    require(type(m) is dict and set(m) == set(fixed) | {'artifacts', 'prior_stability_corpus', 'admitted_rich_pool_digests'}, 'closed pointer manifest required')
    for key, value in fixed.items():
        require(wire(m[key]) == wire(value), 'manifest contract differs: ' + key)
    require(type(m['artifacts']) is dict and set(m['artifacts']) == ARTIFACT_KEYS, 'complete pointer artifact inventory required')
    for ref in m['artifacts'].values():
        _validate_ref(ref)
    _validate_ref(m['prior_stability_corpus'])
    require(len({r['path'] for r in m['artifacts'].values()}) == len(ARTIFACT_KEYS), 'artifact aliases rejected')
    read_ref(m['prior_stability_corpus'])
    admitted = admitted_inputs(m['prior_stability_corpus']['path'])
    require(wire(m['admitted_rich_pool_digests']) == wire({k: digest(v) for k, v in admitted['history'].items()}), 'admitted source inventory changed')
    a = m['artifacts']
    result = {'manifest': m, 'manifest_ref': pin}
    for key in ('training', 'tuning'):
        rows = read_ref(a[key + '_targets'])
        validate_mapping(rows, admitted[key])
        require(wire(read_ref(a[key + '_mapping'])) == wire(_mapping(admitted[key])), 'admitted mapping provenance differs')
        result[key] = rows
    retained = read_ref(a['retention_targets'])
    require(type(retained) is dict and set(retained) == set(RETENTION), 'retention panel omission')
    for key, rows in retained.items():
        validate_mapping(rows, admitted['retention'][key])
    require(wire(read_ref(a['retention_mapping'])) == wire({k: _mapping(v) for k, v in admitted['retention'].items()}), 'retention mapping differs')
    result['retention_targets'] = retained
    result['retention_sources'] = {k: [source_row(r) for r in rows] for k, rows in retained.items()}
    seen = {old.normalized_source(r['source_text']) for rows in admitted['history'].values() for r in rows}
    for pack in admitted['historical_source_packs']:
        seen.update(old.normalized_source(r['source_text']) for r in read_ref(pack))
    for split in UNITS:
        rows = read_ref(a[split + '_sources'])
        validate_query_inventory(rows, expected=144)
        values = {old.normalized_source(r['source_text']) for r in rows}
        require(len(values) == 60 and not seen & values, 'fresh sources overlap or source inventory differs')
        require(all(len(re.findall(r'\w+|[^\w\s]', r['source_text'], re.UNICODE)) <= 256 for r in rows), 'fresh source encoder budget exceeded')
        seen.update(values)
        result[split + '_sources'] = rows
    return result
