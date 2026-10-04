"""Evaluation-only authored ownership transfer; no new training or legal gold.

Source features remain text plus a lexically proposed time interval. Reference
candidates and enclosing spans are annotations, never a semantic closure claim.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
import random
import re

from . import legal_temporal_placement_corpus as previous

paired = previous.previous
old = previous.old
require, wire, sha, digest, file_ref, read_ref, write_new = (
    getattr(previous, k) for k in ('require', 'wire', 'sha', 'digest', 'file_ref', 'read_ref', 'write_new'))
query, validate_source_query, propose_time_spans, validate_query_inventory = (
    getattr(previous, k) for k in ('query', 'validate_source_query', 'propose_time_spans', 'validate_query_inventory'))
SOURCE_KEYS = previous.SOURCE_KEYS
TARGET_KEYS = previous.TARGET_KEYS
LABELS = previous.LABELS
TIME_FORMS = previous.TIME_FORMS
COUNTS = {'fresh_lexical': 144, 'fresh_structural': 144}
UNITS = {k: 12 for k in COUNTS}
SEALED = previous.SEALED
SCHEMA = 'authored-temporal-stability-evaluation/v1'
ANNOTATION_SCHEMA = 'authored-temporal-stability-annotation/v1'
AUTHORITY = previous.AUTHORITY
STRUCTURAL_FAMILIES = ('actor_joint_modal_action', 'actor_modal_joint_action')
RETENTION = (*previous.RETENTION, 'placement_exposed_lexical', 'placement_exposed_structural')
RUNTIME_KEYS = ('single_training', 'prior_paired_training', 'prior_sampling_units', 'placement_training',
                'sampling_units', 'single_tuning', 'prior_paired_tuning', 'placement_tuning')
VOCAB = {
    'fresh_lexical': {'names': ('Basalt', 'Calcite', 'Dolomite', 'Feldspar'),
                      'actions': ('index', 'lodge', 'circulate', 'deposit'),
                      'objects': ('memorandum', 'inventory', 'dispatch', 'account')},
    'fresh_structural': {'names': ('Granite', 'Hematite', 'Jasper', 'Kyanite'),
                         'actions': ('enroll', 'collate', 'route', 'preserve'),
                         'objects': ('register', 'abstract', 'digest', 'transcript')},
}
# Familiar headings deliberately do not manufacture structural novelty.
HEADINGS = previous.HEADINGS['train']
RELEASE_RULE = 'Fresh references remain sealed until selection, generation and independent replay freeze; all earlier released panels are exposed regressions.'


def source_row(row):
    return validate_source_query({k: deepcopy(row[k]) for k in SOURCE_KEYS})


def factors(split, unit, source):
    require(split in UNITS and type(unit) is int and 0 <= unit < 12 and
            type(source) is int and 0 <= source < 5, 'bounded authored factors required')
    labels, form, modality, _, pattern, rotation = paired.factors('fresh_lexical', unit, source)
    placement = previous.PLACEMENTS[unit % 3]
    if split == 'fresh_lexical':
        family = 'matched_placement_layout'
        layout = previous.LAYOUTS[(unit + source) % 6]
        enclosure = ('none', 'condition_only', 'exception_only')[(unit // 3 + source) % 3]
        order = [x for x in layout.split('_') if x != 'norm']
    else:
        family = STRUCTURAL_FAMILIES[unit % 2]
        layout = family
        enclosure = 'interposed_joint_qualifiers'
        order = ['condition', 'exception'] if (unit + source) % 2 == 0 else ['exception', 'condition']
    return labels, form, modality, placement, family, layout, enclosure, order, pattern, rotation


def literal(split, unit, form):
    require(split in UNITS and type(unit) is int and 0 <= unit < 12 and form in TIME_FORMS,
            'bounded time literal factors required')
    index = list(UNITS).index(split)
    amount, year, day = 801 + index * 100 + unit, 2091 + index, unit % 28 + 1
    return {'days': f'within {amount} days of notice', 'hours': f'within {amount} hours of notice',
            'iso_date': f'before {year}-09-{day:02d}',
            'month_date': f'before September {day}, {year}'}[form]


def render_source(split, unit, source):
    labels, form, modality, placement, family, layout, enclosure, order, pattern, rotation = factors(split, unit, source)
    case = unit * 5 + source
    identity = 120000 + list(UNITS).index(split) * 1000 + case
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


def candidate_coordinate_inputs(row):
    return paired.candidate_coordinate_inputs(row)


def make_panel(split):
    require(split in UNITS, 'evaluation split required')
    rows, units = [], []
    for unit in range(12):
        values = [r for source in range(5) for r in render_source(split, unit, source)]
        rows.extend(values)
        units.append({'unit_id': values[0]['annotation']['unit_id'], 'query_ids': sorted(r['id'] for r in values)})
    random.Random(120401 + list(UNITS).index(split)).shuffle(rows)
    return rows, units


def validate_target(row):
    require(type(row) is dict and set(row) == TARGET_KEYS, 'closed stability target required')
    validate_source_query(source_row(row))
    a = row['annotation']
    require(type(a) is dict, 'annotation required')
    expected = render_source(a.get('split'), a.get('unit_index'), a.get('source_index'))
    matches = [r for r in expected if r['id'] == row['id']]
    require(len(matches) == 1 and wire(matches[0]) == wire(row), 'target differs from exact insertion provenance')
    return row


def validate_units(rows, units, split, reconstruct=True):
    require(split in UNITS, 'evaluation-only split required')
    paired.validate_units(rows, units, split, reconstruct=False)
    if reconstruct:
        for row in rows:
            validate_target(row)
    require(Counter(r['annotation']['norm_time_placement'] for r in rows) ==
            Counter({x: 48 for x in previous.PLACEMENTS}), 'placement margins differ')
    if split == 'fresh_structural':
        require(Counter(r['annotation']['structural_family'] for r in rows) ==
                Counter({x: 72 for x in STRUCTURAL_FAMILIES}), 'structural family margins differ')
    return rows


def body_layout(row):
    """Common role mask for all three prior authored ownership corpus schemas."""
    a, text = row['annotation'], row['source_text']
    start = a['heading_span']['char_end']
    aliases = {'action_object': 'action', 'condition_anchor': 'condition_predicate', 'exception_anchor': 'exception_predicate'}
    roles = a.get('source_role_spans', a.get('lexical_spans', []))
    spans = [(x['span']['char_start'], x['span']['char_end'], '[' + aliases.get(x['role'], x['role']) + ']') for x in roles]
    spans += [(x['char_start'], x['char_end'], '[TIME]') for x in propose_time_spans(text)]
    modal_spans = a.get('modal_spans')
    if modal_spans is None:
        modal_spans = [{'char_start': m.start(), 'char_end': m.end()} for m in re.finditer(r'\b(?:shall not|shall|may)\b', text)
                       if m.start() >= start and not any(lo < m.end() and m.start() < hi for lo, hi, _ in spans)]
    require(bool(modal_spans), 'explicit modal outside copied atoms required')
    spans += [(x['char_start'], x['char_end'], '[MODAL]') for x in modal_spans]
    cursor, parts = start, []
    for lo, hi, marker in sorted(spans):
        require(type(lo) is int and type(hi) is int and cursor <= lo < hi <= len(text), 'nonoverlapping source masks required')
        parts.extend((text[cursor:lo], marker))
        cursor = hi
    return ' '.join((''.join(parts) + text[cursor:]).split())


def historical_inputs(prior):
    """All exposed ownership targets plus the previously pinned source-only packs."""
    a = prior['manifest']['artifacts']
    placement_exposed = {name: read_ref(a[split + '_targets']) for name, split in
                         [('placement_exposed_lexical', 'fresh_lexical'), ('placement_exposed_structural', 'fresh_structural')]}
    ledger = read_ref(a['fresh_annotation_ledger'])
    for name, split in [('placement_exposed_lexical', 'fresh_lexical'), ('placement_exposed_structural', 'fresh_structural')]:
        previous.validate_units(placement_exposed[name], ledger['units'][split], split)
    pools = {'single_training': prior['single_training'], 'prior_paired_training': prior['prior_paired_training'],
             'placement_training': prior['placement_training'], 'placement_tuning': prior['placement_tuning'],
             **prior['retention_targets'], **placement_exposed}
    original_manifest = read_ref(prior['legacy']['manifest']['prior_corpus'])
    return pools, original_manifest['historical_source_packs']


def exposure_audit(panels, prior):
    pools, source_pins = historical_inputs(prior)
    sources, literals, groups = set(), set(), set()
    prior_layouts = set()
    pool_summary = {}
    for name, rows in pools.items():
        values = {body_layout(r) for r in rows}
        prior_layouts.update(values)
        sources.update(old.normalized_source(r['source_text']) for r in rows)
        literals.update(r['annotation']['time_span']['text'] for r in rows)
        groups.update(r['group_id'] for r in rows)
        pool_summary[name] = {'queries': len(rows), 'sources': len({r['source_sha256'] for r in rows}),
                              'body_layouts': sorted(values), 'rows_sha256': digest(rows)}
    for pin in source_pins:
        for row in read_ref(pin):
            require(set(row) == {'candidate_id', 'source_text', 'source_sha256'} and row['source_sha256'] == sha(row['source_text']), 'historical source binding differs')
            sources.add(old.normalized_source(row['source_text']))
            literals.update(row['source_text'][x['char_start']:x['char_end']]
                            for x in propose_time_spans(row['source_text']))
    training_layouts = {body_layout(r) for r in pools['placement_training']}
    result, seen_sources, seen_groups, seen_literals, new_layouts = {}, set(), set(), set(), {}
    for split, (rows, units) in panels.items():
        current_sources = {old.normalized_source(r['source_text']) for r in rows}
        current_groups = {r['group_id'] for r in rows}
        current_literals = {r['annotation']['time_span']['text'] for r in rows}
        require(not current_sources & (sources | seen_sources), 'historical/cross-panel source overlap')
        require(not current_groups & (groups | seen_groups), 'historical/cross-panel group overlap')
        require(not current_literals & (literals | seen_literals), 'historical/cross-panel literal overlap')
        seen_sources.update(current_sources); seen_groups.update(current_groups); seen_literals.update(current_literals)
        layouts = [body_layout(r) for r in rows]
        new_layouts[split] = set(layouts)
        result[split] = {'queries': len(rows), 'sources': len(current_sources), 'units': len(units),
            'class_counts': dict(Counter(r['label'] for r in rows)),
            'modality_by_class': {label: dict(Counter(r['annotation']['modality'] for r in rows if r['label'] == label)) for label in LABELS},
            'time_form_by_class': {label: dict(Counter(r['annotation']['time_form'] for r in rows if r['label'] == label)) for label in LABELS},
            'placement_by_class': {label: dict(Counter(r['annotation']['norm_time_placement'] for r in rows if r['label'] == label)) for label in LABELS},
            'structural_family_counts': dict(Counter(r['annotation']['structural_family'] for r in rows)),
            'qualifier_order_counts': dict(Counter('_'.join(r['annotation']['qualifier_order']) for r in rows)),
            'normalized_body_layouts': sorted(set(layouts)), 'matches_prior_body_layout_queries': sum(v in prior_layouts for v in layouts),
            'matches_placement_train_body_layout_queries': sum(v in training_layouts for v in layouts),
            'source_hashes': sorted({r['source_sha256'] for r in rows}), 'time_literals': sorted(current_literals)}
    require(not new_layouts['fresh_structural'] & (prior_layouts | new_layouts['fresh_lexical']), 'structural interposition holdout collapsed')
    require(result['fresh_lexical']['matches_placement_train_body_layout_queries'] == 144, 'lexical control lacks matched training layout')
    return {'schema': 'temporal-stability-exposure/v1', 'panels': result, 'prior_corpus': prior['manifest_ref'],
            'historical_source_packs': source_pins, 'prior_annotated_pools': pool_summary,
            'historical_unique_sources_checked': len(sources), 'prior_normalized_body_layout_count': len(prior_layouts),
            'historical_source_overlap': 0, 'cross_panel_source_overlap': 0, 'cross_panel_group_overlap': 0, 'cross_panel_literal_overlap': 0,
            'prospective_structural_families': list(STRUCTURAL_FAMILIES), 'shared_attachment_grammar': True,
            'norm_placement_metadata_only_realized_on_norm_queries': True, 'independent_legal_gold': False,
            'limits': ['Role-layout novelty covers explicitly pinned authored ownership targets; older source-only packs support source exclusion only.',
                      'Interposed blocks and enclosing owner spans do not certify statutory attachment or semantic closure.',
                      'All previous fresh labels are exposed retention; no training or tuning rows are added.']}


def producers():
    root = Path(__file__).resolve().parents[3]
    return [file_ref(__file__), file_ref(root / 'scripts/ops/legal_ir/prepare_legal_temporal_stability_corpus.py'),
            file_ref(previous.__file__), file_ref(paired.__file__), file_ref(old.__file__)]


def build_corpus(output, prior_manifest_path):
    output = Path(output).resolve()
    require(not output.exists(), 'new corpus output required')
    prior = previous.load_training_inputs(prior_manifest_path)
    panels = {split: make_panel(split) for split in COUNTS}
    for split, (rows, units) in panels.items():
        validate_units(rows, units, split)
    audit = exposure_audit(panels, prior)
    output.mkdir(parents=True)
    artifacts = {}
    for split, (rows, _) in panels.items():
        artifacts[split + '_sources'] = write_new(output / (split + '-sources.json'), [source_row(r) for r in rows])
        artifacts[split + '_targets'] = write_new(output / (split + '-targets.json'), rows)
    artifacts['fresh_annotation_ledger'] = write_new(output / 'fresh-annotation-ledger.json', {
        'schema': 'temporal-stability-reference-ledger/v1', 'candidate_inventory_usage': 'reference_only_not_inference_inputs',
        'units': {split: panel[1] for split, panel in panels.items()},
        'annotations': {split: [{k: r[k] for k in ('id', 'source_sha256', 'group_id', 'label', 'annotation')} for r in panel[0]] for split, panel in panels.items()}})
    artifacts['exposure_audit'] = write_new(output / 'exposure-audit.json', audit)
    manifest = {'schema': SCHEMA, 'counts': COUNTS, 'unit_counts': UNITS, 'labels': list(LABELS),
        'source_query_keys': sorted(SOURCE_KEYS), 'artifacts': artifacts, 'sealed_artifacts': list(SEALED),
        'prior_corpus': prior['manifest_ref'], 'producer_files': producers(), 'retention_panels': list(RETENTION),
        'reused_runtime_inputs': {key: digest(prior[key]) for key in RUNTIME_KEYS}, 'new_training_queries': 0,
        'new_tuning_queries': 0, 'sampling_unit_queries': 12, 'queries_per_class_per_unit': 3,
        'scope': 'authored_owner_type_only', 'gold_filtered_owner_candidates': 'reference_only_not_inference_inputs',
        'source_offsets_supplied': True, 'structural_families': list(STRUCTURAL_FAMILIES),
        'shared_attachment_grammar': True, 'independent_legal_gold': False, 'flat_logic_profile_admission': False,
        'release_rule': RELEASE_RULE}
    return write_new(output / 'manifest.json', manifest)


def load_training_inputs(manifest_path):
    pin = file_ref(manifest_path)
    m = read_ref(pin)
    fixed = {'schema': SCHEMA, 'counts': COUNTS, 'unit_counts': UNITS, 'labels': list(LABELS),
        'source_query_keys': sorted(SOURCE_KEYS), 'sealed_artifacts': list(SEALED), 'producer_files': producers(),
        'retention_panels': list(RETENTION), 'new_training_queries': 0, 'new_tuning_queries': 0,
        'sampling_unit_queries': 12, 'queries_per_class_per_unit': 3, 'scope': 'authored_owner_type_only',
        'gold_filtered_owner_candidates': 'reference_only_not_inference_inputs', 'source_offsets_supplied': True,
        'structural_families': list(STRUCTURAL_FAMILIES), 'shared_attachment_grammar': True,
        'independent_legal_gold': False, 'flat_logic_profile_admission': False, 'release_rule': RELEASE_RULE}
    require(type(m) is dict and set(m) == set(fixed) | {'artifacts', 'prior_corpus', 'reused_runtime_inputs'}, 'closed stability manifest required')
    for key, value in fixed.items():
        require(wire(m[key]) == wire(value), 'manifest contract differs: ' + key)
    keys = {'fresh_lexical_sources', 'fresh_structural_sources', *SEALED}
    require(type(m['artifacts']) is dict and set(m['artifacts']) == keys, 'complete artifact inventory required')
    for ref in m['artifacts'].values():
        require(type(ref) is dict and set(ref) == {'path', 'bytes', 'sha256'} and type(ref['path']) is str and Path(ref['path']).is_absolute()
                and type(ref['sha256']) is str and re.fullmatch('[0-9a-f]{64}', ref['sha256']) and type(ref['bytes']) is int
                and 0 <= ref['bytes'] <= old.MAX_FILE_BYTES, 'closed artifact reference required')
    require(len({r['path'] for r in m['artifacts'].values()}) == len(keys), 'artifact aliases rejected')
    read_ref(m['prior_corpus'])
    prior = previous.load_training_inputs(m['prior_corpus']['path'])
    require(wire(m['reused_runtime_inputs']) == wire({key: digest(prior[key]) for key in RUNTIME_KEYS}), 'runtime inputs changed')
    pools, _ = historical_inputs(prior)
    retention = {key: pools[key] for key in RETENTION}
    result = {**prior, 'manifest': m, 'manifest_ref': pin, 'prior_inputs': prior,
              'retention_targets': retention, 'retention_sources': {k: [source_row(r) for r in rows] for k, rows in retention.items()}}
    seen = {old.normalized_source(r['source_text']) for rows in pools.values() for r in rows}
    for split in COUNTS:
        rows = read_ref(m['artifacts'][split + '_sources'])
        validate_query_inventory(rows, expected=COUNTS[split])
        sources = {old.normalized_source(r['source_text']) for r in rows}
        require(not sources & seen, 'current/historical source overlap')
        seen.update(sources)
        result[split + '_sources'] = rows
    return result
