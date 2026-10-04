#!/usr/bin/env python3
"""Author condition/time retention checks, with no additions to fitting data.

Labels stipulate controlled meanings. They are not reviewed statutory gold.
Old challenges are exposed retention data; only this study's new references are
sealed. Surface grammar is shared intentionally and measured in an exposure audit.
"""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import prepare_legal_temporal_presence_corpus as previous

prior, mixed, construction = previous.prior, previous.mixed, previous.construction
require, sha, file_ref, read_ref, verify_ref, write_new = (
    getattr(previous, k) for k in ('require', 'sha', 'file_ref', 'read_ref', 'verify_ref', 'write_new'))
SCHEMA = 'authored-legal-condition-rehearsal-corpus/v1'
FIELDS, SOURCE_KEYS, SEALED = previous.FIELDS, previous.SOURCE_KEYS, previous.SEALED
COUNTS = {'tuning': 96, 'fresh': 192, 'document_tuning': 96, 'document_fresh': 96}
FAMILIES = ('condition_postmodal', 'condition_trailing', 'condition_front', 'condition_actor_infix')
PREFIXES = {'tuning': 'Silverbirch', 'fresh': 'Copperbirch',
            'document_tuning': 'Amberbirch', 'document_fresh': 'Cobaltbirch'}
TRIGGERS, TRIGGER_MEANINGS = previous.TRIGGERS, previous.TRIGGER_MEANINGS
GUARDS = previous.GUARDS
DEFAULT_PRIOR = prior.ARTIFACTS / 'legal-decoder-temporal-presence-20261003/corpus-01/manifest.json'
DEFAULT_CONFIG = prior.ARTIFACTS / 'legal-decoder-temporal-presence-20261003/experiment-config.json'


def validate_row(row):
    require(type(row) is dict and set(row) == set(mixed.ROW_KEYS), 'closed coordinate row required')
    require(row['domain'] == 'new' and row['trigger_supervised'] is True, 'authored domain/trigger required')
    text = row['source_text']
    require(row['id'].startswith('condition-rehearsal-') and row['id'].endswith('-' + sha(text.encode())[:24]),
            'identity must bind exact source')
    # Pure historical validator is reused with a temporary identity, never a
    # mutation of its globals or of the input row.
    previous.validate_row({**row, 'id': 'temporal-presence-validation-' + sha(text.encode())[:24]})
    return row


def condition_metadata(row):
    span = row['facet_spans']['conditions']
    position, cue = 'absent', None
    if span:
        prefix = row['source_text'][:span[0]].rstrip().casefold()
        cue = next((c for c in ('provided that', 'when', 'if') if prefix.endswith(c)), None)
        require(cue is not None, 'authored condition cue missing')
        start = span[0]
        position = ('before_actor' if start < row['facet_spans']['actor'][0] else
            'between_actor_and_modal' if start < row['trigger_span'][0] else
            'between_modal_and_action' if start < row['facet_spans']['action'][0] else 'after_object')
    return {'condition_present': bool(span), 'condition_placement': position, 'condition_cue': cue,
            **previous.temporal_metadata(row)}


def render(panel, family_index, modality_index, mask, side, ordinal=None):
    require(panel in COUNTS and family_index in range(4) and modality_index in range(3)
            and mask in range(8) and side in (0, 1), 'bounded authored coordinates required')
    ordinal = (family_index * 3 + modality_index) * 8 + mask if ordinal is None else ordinal
    name = PREFIXES[panel] + f'{ordinal:03d}'
    number = 19 + ordinal % 71
    kind = (family_index + modality_index + (mask & 3)) % 4
    temporal = (f'within {number} hours' if kind == 0 else f'within {number} days' if kind == 1
                else f'before {2053 + list(PREFIXES).index(panel)}-03-{1 + ordinal % 28:02d}')
    opaque = bool(mask & 1) and not mask & 4 and (family_index + modality_index) % 2 == 0
    values = {'actor': f'the {name} {previous.ROLE_NOUNS[ordinal % 4]}',
        'action': previous.VERBS[(ordinal // 3 + family_index) % 8],
        'object': f'the {name.lower()} filing packet',
        'conditions': (f'the {name.lower()} application was received within {number} days of publication'
                       if opaque else f'the {name.lower()} permit is active'),
        'exceptions': f'the {name.lower()} exemption is active', 'temporal': temporal}
    present = {f for bit, f in enumerate(FIELDS[3:]) if mask & (1 << bit)}
    modal = ('O', 'P', 'F')[modality_index]
    ccue = ('when', 'if', 'provided that')[(family_index + modality_index + side) % 3]
    if panel.startswith('document_') and ccue == 'provided that': ccue = 'when'
    ecue = previous.EXCEPTION_CUES[(family_index + mask + side) % 3]
    writer, editorial = prior.CoordinateWriter(), []
    def add(s): writer.add(s)
    def field(f): writer.add(values[f], f)
    def qualifier(f):
        if f in ('conditions', 'exceptions'):
            cue = ccue if f == 'conditions' else ecue
            if not writer.text: cue = cue.capitalize()
            add(cue + ' ')
        field(f)
    if panel.startswith('document_') and ordinal % 4 == 0:
        text = ('Filing duty.— ', 'Record duty [1]. ')[side]
        editorial.append({'start_char': 0, 'end_char': len(text), 'source_text': text,
                          'author_stipulated_role': 'nonoperative_editorial_context'})
        add(text)
    # Side zero stresses fronted deadlines paired with each condition placement.
    # Side one changes both condition and temporal placement while keeping meaning.
    cpositions = (2, 3, 0, 1)
    cpos = cpositions[family_index] if side == 0 else cpositions[(family_index + 1) % 4]
    tpos = 0 if side == 0 else (1 if family_index % 2 else 3)
    epos = 3 if side == 0 else 2
    positions = {f: p for f, p in (('conditions', cpos), ('exceptions', epos), ('temporal', tpos))}
    def at(position):
        return [f for f in ('temporal', 'conditions', 'exceptions') if f in present and positions[f] == position]
    for f in at(0): qualifier(f); add(', ')
    field('actor')
    for f in at(1): add(', '); qualifier(f); add(',')
    add(' '); writer.add(TRIGGERS[modal][side], 'trigger')
    for f in at(2): add(', '); qualifier(f); add(',')
    add(' '); field('action'); add(' '); field('object')
    for f in at(3): add(' '); qualifier(f)
    add('.')
    rule = {'modality': modal, **{f: values[f] for f in FIELDS[:3]},
            **{f: [values[f]] if f in present else [] for f in FIELDS[3:]}}
    row = validate_row({'id': f'condition-rehearsal-{panel}-' + sha(writer.text.encode())[:24],
        'source_text': writer.text, 'canonical_ir': {'rules': [rule]},
        'trigger_span': writer.spans['trigger'], 'facet_spans': {f: writer.spans.get(f) for f in FIELDS},
        'domain': 'new', 'trigger_supervised': True})
    group = f'condition-rehearsal-{panel}-case-{ordinal:03d}'
    annotation = {'id': row['id'], 'source_sha256': sha(writer.text.encode()), 'panel': panel,
        'case_group': group, 'meaning_group': group, 'family': FAMILIES[family_index], 'side': side,
        'facet_spans': row['facet_spans'], 'trigger_span': row['trigger_span'], 'presence_mask': mask,
        'editorial_context': editorial, 'role_masked_layout': previous.role_layout(row),
        'annotation_authority': 'authored_controlled_example_not_statutory_gold', **condition_metadata(row)}
    return row, annotation


def make_panel(panel):
    require(panel in ('tuning', 'fresh'), 'single panel required')
    rows, pairs, annotations = [], [], []
    for family in range(2 if panel == 'tuning' else 4):
        for modality in range(3):
            for mask in range(8):
                pair = [render(panel, family, modality, mask, side) for side in (0, 1)]
                rows.extend(x[0] for x in pair); annotations.extend(x[1] for x in pair)
                pairs.append({'pair_id': pair[0][1]['case_group'], 'case_group': pair[0][1]['case_group'],
                    'left_id': pair[0][0]['id'], 'right_id': pair[1][0]['id'],
                    'canonical_ir_sha256': sha(prior.canonical_bytes(pair[0][0]['canonical_ir']))})
    previous.validate_pairs(rows, pairs, COUNTS[panel] // 2)
    return rows, annotations, pairs


def authored_document(panel, ordinal):
    require(panel in ('document_tuning', 'document_fresh') and ordinal in range(96), 'bounded document required')
    supported = ordinal < 72
    count = 1 + ordinal // 24 if supported else 2
    rendered = [render(panel, (ordinal + i) % 4, (ordinal + i) % 3, (ordinal + i * 3) % 8,
                       (ordinal // 4 + i) % 2, ordinal * 3 + i) for i in range(count)]
    repeated = supported and ordinal in (*range(24, 30), *range(48, 54))
    if repeated: rendered[-1] = deepcopy(rendered[0])
    chunks, clauses, coords, cursor = [], [], [], 0
    for i, (local, annotation) in enumerate(rendered):
        text = local['source_text']; gap = ('\n' if ordinal % 2 == 0 else ' ') if i else ''
        if i < count - 1 and ordinal % 3 == 0: text = text[:-1] + ';'
        cursor += len(gap); chunks.append(gap + text)
        clauses.append({'char_start': cursor, 'char_end': cursor + len(text), 'rule': local['canonical_ir']['rules'][0]})
        coords.append({'clause_index': i, 'char_start': cursor, 'char_end': cursor + len(text),
            'facet_spans': {f: [x + cursor for x in span] if span else None for f, span in local['facet_spans'].items()},
            'trigger_span': [x + cursor for x in local['trigger_span']], 'family': annotation['family'],
            'presence_mask': annotation['presence_mask'], 'side': annotation['side'],
            'meaning_group': annotation['meaning_group'], **condition_metadata(local),
            'editorial_context': [{**n, 'start_char': n['start_char'] + cursor, 'end_char': n['end_char'] + cursor}
                                  for n in annotation['editorial_context']]})
        cursor += len(text)
    text, reason = ''.join(chunks), None
    if not supported:
        reason = GUARDS[(ordinal - 72) % 3]
        first, second = [r[0]['source_text'] for r in rendered]
        text = ('Both following rules share the same condition: ' + first + ' ' + second
                if reason == 'shared_condition_prefix' else first[:-1] + ' and publish the retained archive.'
                if reason == 'coordinated_action' else first[:-1] + ' unless ' + second)
        clauses, coords, repeated = [], [], False
    row = {'candidate_id': f'condition-rehearsal-{panel}-{ordinal:03d}', 'source_text': text,
        'source_sha256': sha(text.encode()), 'supported': supported,
        'construction': FAMILIES[ordinal % 4] if supported else 'unsupported/' + reason,
        'repeated_rule_occurrences': repeated, 'clauses': clauses, 'unsupported_reason': reason,
        'label_origin': 'new_authored_restricted_flat_profile_not_legal_authority'}
    annotation = {'candidate_id': row['candidate_id'], 'source_sha256': row['source_sha256'], 'panel': panel,
        'case_group': f'condition-rehearsal-{panel}-case-{ordinal:03d}', 'supported': supported,
        'guard': reason, 'clause_coordinates': coords, 'clause_occurrences': len(clauses),
        'unique_rules': len({sha(prior.canonical_bytes(c['rule'])) for c in clauses})}
    validate_document(row, annotation)
    return row, annotation


document_source = previous.document_source
document_clause_rows = previous.document_clause_rows


def validate_document(row, annotation=None):
    construction.validate_document(row)
    if annotation is None: return
    require(annotation['candidate_id'] == row['candidate_id'] and annotation['source_sha256'] == row['source_sha256']
            and annotation['supported'] == row['supported'] and annotation['guard'] == row['unsupported_reason'],
            'document annotation source binding differs')
    require(len(row['clauses']) == len(annotation['clause_coordinates']) == annotation['clause_occurrences'], 'occurrences differ')
    unique = len({sha(prior.canonical_bytes(c['rule'])) for c in row['clauses']})
    require(unique == annotation['unique_rules'] and row['repeated_rule_occurrences'] == (unique < len(row['clauses'])),
            'repeated occurrences differ')
    for index, (local, coords, clause) in enumerate(zip(document_clause_rows([row], [annotation]), annotation['clause_coordinates'], row['clauses'], strict=True)):
        validate_row(local)
        require(coords['clause_index'] == index and all(coords[k] == clause[k] for k in ('char_start', 'char_end')), 'document coordinates differ')
        require(all(coords[k] == value for k, value in condition_metadata(local).items()), 'condition/time annotation differs')


def make_panels():
    panels, pairs = {}, {}
    ledger = {'schema': 'authored-condition-rehearsal-annotations/v1', 'single_rows': [], 'document_rows': []}
    for panel in ('tuning', 'fresh'):
        panels[panel], annotations, pairs[panel] = make_panel(panel); ledger['single_rows'].extend(annotations)
    for panel in ('document_tuning', 'document_fresh'):
        values = [authored_document(panel, i) for i in range(96)]
        panels[panel] = [x[0] for x in values]; ledger['document_rows'].extend(x[1] for x in values)
    validate_panels(panels, pairs, ledger)
    return panels, pairs, ledger


def validate_panels(panels, pairs, ledger):
    require({k: len(v) for k, v in panels.items()} == COUNTS, 'panel counts differ')
    singles = {a['id']: a for a in ledger['single_rows']}
    docs = {a['candidate_id']: a for a in ledger['document_rows']}
    require(len(singles) == len(ledger['single_rows']) == 288 and len(docs) == len(ledger['document_rows']) == 192,
            'annotation coverage differs')
    seen_sources, seen_meanings, seen_cases = set(), set(), set()
    for panel, rows in panels.items():
        local_sources, local_meanings = set(), set()
        if panel in ('tuning', 'fresh'):
            previous.validate_pairs(rows, pairs[panel], COUNTS[panel] // 2)
            counts = Counter((r['canonical_ir']['rules'][0]['modality'],
                sum(1 << bit for bit, f in enumerate(FIELDS[3:]) if r['canonical_ir']['rules'][0][f])) for r in rows)
            require(counts == {(m, mask): len(rows) // 24 for m in 'OPF' for mask in range(8)}, 'modality/mask balance differs')
            for r in rows:
                validate_row(r); a = singles[r['id']]
                require(a['panel'] == panel and a['source_sha256'] == sha(r['source_text'].encode())
                    and a['facet_spans'] == r['facet_spans'] and a['trigger_span'] == r['trigger_span'], 'annotation binding differs')
                require(all(a[k] == value for k, value in condition_metadata(r).items()), 'condition/time metadata differs')
                require(a['presence_mask'] == sum(1 << bit for bit, f in enumerate(FIELDS[3:]) if r['canonical_ir']['rules'][0][f])
                        and a['role_masked_layout'] == previous.role_layout(r), 'mask/layout differs')
                local_sources.add(prior.normalized_source(r['source_text']))
                local_meanings.add(sha(prior.canonical_bytes(r['canonical_ir'])))
            for pair in pairs[panel]:
                left, right = singles[pair['left_id']], singles[pair['right_id']]
                require(left['case_group'] == right['case_group'] == pair['case_group'] == pair['pair_id']
                    and left['meaning_group'] == right['meaning_group'] == pair['pair_id']
                    and (left['side'], right['side']) == (0, 1), 'pair annotation lineage differs')
            cases = {p['case_group'] for p in pairs[panel]}
        else:
            require(Counter(r['supported'] for r in rows) == {True: 72, False: 24}, 'support balance differs')
            require(Counter(len(r['clauses']) for r in rows if r['supported']) == {1: 24, 2: 24, 3: 24}, 'rule counts differ')
            require(Counter(r['unsupported_reason'] for r in rows if not r['supported']) == {g: 8 for g in GUARDS}, 'guards differ')
            require(sum(r['repeated_rule_occurrences'] for r in rows) == 12, 'repeated rule cases differ')
            for r in rows:
                validate_document(r, docs[r['candidate_id']])
                require(docs[r['candidate_id']]['panel'] == panel, 'document annotation panel differs')
                local_sources.add(prior.normalized_source(r['source_text']))
                for c in r['clauses']:
                    local_sources.add(prior.normalized_source(r['source_text'][c['char_start']:c['char_end']]))
                    local_meanings.add(sha(prior.canonical_bytes({'rules': [c['rule']]})))
            cases = {docs[r['candidate_id']]['case_group'] for r in rows}
        require(not (local_sources & seen_sources or local_meanings & seen_meanings or cases & seen_cases), 'cross-panel overlap')
        seen_sources |= local_sources; seen_meanings |= local_meanings; seen_cases |= cases
    return {'source_overlap': 0, 'meaning_overlap': 0, 'case_overlap': 0,
            'unique_sources_including_document_clauses': len(seen_sources), 'case_groups': len(seen_cases),
            'grammar_shared': True, 'statutory_gold': False, 'added_fitting_rows': 0}


def historical_inputs(prior_manifest_path):
    manifest = json.loads(Path(prior_manifest_path).read_bytes())
    _, pools, excluded, refs, source_refs, real_count = previous.historical_inputs(manifest['inputs']['prior_corpus']['path'])
    for name, key in (('temporal_presence_train', 'new_training'), ('temporal_presence_tuning', 'new_tuning'), ('temporal_presence_exposed', 'challenge_targets')):
        require(name not in pools and name not in refs, 'historical pool name collision')
        pools[name] = read_ref(manifest['artifacts'][key]); refs[name] = {'reference': manifest['artifacts'][key], 'representation': 'annotated_single'}
    for name, key in (('temporal_presence_document_tuning', 'document_tuning_targets'), ('temporal_presence_document_exposed', 'document_challenge_targets')):
        require(name not in pools and name not in refs, 'historical document pool name collision')
        rows = read_ref(manifest['artifacts'][key]); excluded.update(r['source_text'] for r in rows)
        pools[name] = construction.document_clauses_for_audit(rows)
        refs[name] = {'reference': manifest['artifacts'][key], 'representation': 'document_clauses'}
    for rows in pools.values(): excluded.update(r['source_text'] for r in rows)
    return manifest, pools, excluded, refs, source_refs, real_count


def freeze(output, prior_manifest_path=DEFAULT_PRIOR, prior_config_path=DEFAULT_CONFIG):
    output = Path(output).resolve(); require(not output.exists(), 'output already exists')
    config = json.loads(Path(prior_config_path).read_bytes())
    require(config['corpus_manifest'] == file_ref(prior_manifest_path), 'prior config/corpus differs')
    old, known, excluded, pool_refs, source_refs, real_count = historical_inputs(prior_manifest_path)
    panels, pairs, ledger = make_panels(); audit = validate_panels(panels, pairs, ledger)
    checked = [r['source_text'] for rows in panels.values() for r in rows]
    checked += [r['source_text'][c['char_start']:c['char_end']] for p in ('document_tuning', 'document_fresh') for r in panels[p] for c in r['clauses']]
    require(not {prior.normalized_source(s) for s in checked} & {prior.normalized_source(s) for s in excluded}, 'historical source overlap')
    historical_meanings = {sha(prior.canonical_bytes(r['canonical_ir'])) for rows in known.values() for r in rows if 'canonical_ir' in r}
    for item in pool_refs.values():
        if item['representation'] == 'document_clauses':
            historical_meanings.update(sha(prior.canonical_bytes({'rules': [c['rule']]}))
                for r in read_ref(item['reference']) for c in r['clauses'])
    new_meanings = {sha(prior.canonical_bytes(r['canonical_ir'])) for p in ('tuning', 'fresh') for r in panels[p]}
    new_meanings |= {sha(prior.canonical_bytes({'rules': [c['rule']]})) for p in ('document_tuning', 'document_fresh') for r in panels[p] for c in r['clauses']}
    require(not historical_meanings & new_meanings, 'historical canonical meaning overlap')
    output.mkdir(parents=True, exist_ok=False)
    artifacts = {
        'new_tuning': write_new(output / 'new-tuning.json', panels['tuning']),
        'tuning_pairs': write_new(output / 'tuning-pairs.json', pairs['tuning']),
        'challenge_sources': write_new(output / 'challenge-sources.json', [{k: r[k] for k in ('id', 'source_text')} for r in panels['fresh']]),
        'challenge_targets': write_new(output / 'challenge-targets.sealed.json', panels['fresh']),
        'challenge_pairs': write_new(output / 'challenge-pairs.sealed.json', pairs['fresh']),
        'document_tuning_sources': write_new(output / 'document-tuning-sources.json', [document_source(r) for r in panels['document_tuning']]),
        'document_tuning_targets': write_new(output / 'document-tuning-targets.json', panels['document_tuning']),
        'document_challenge_sources': write_new(output / 'document-challenge-sources.json', [document_source(r) for r in panels['document_fresh']]),
        'document_challenge_targets': write_new(output / 'document-challenge-targets.sealed.json', panels['document_fresh']),
        'annotation_ledger': write_new(output / 'annotation-ledger.sealed.json', ledger)}
    known['condition_tuning'] = panels['tuning']; pool_refs['condition_tuning'] = {'reference': artifacts['new_tuning'], 'representation': 'annotated_single'}
    known['condition_document_tuning'] = document_clause_rows(panels['document_tuning'], ledger['document_rows'])
    pool_refs['condition_document_tuning'] = {'reference': artifacts['document_tuning_targets'], 'representation': 'document_clauses'}
    layouts = {name: {previous.role_layout(r) for r in rows} for name, rows in known.items()}
    evidence = {}
    for name, rows in (('single_rows', panels['fresh']), ('document_clause_rows', document_clause_rows(panels['document_fresh'], ledger['document_rows']))):
        evidence[name] = [{'id': r['id'], 'source_sha256': sha(r['source_text'].encode()),
            'role_masked_layout': previous.role_layout(r),
            'matching_pools': sorted(n for n, values in layouts.items() if previous.role_layout(r) in values),
            'layout_status': 'matched_local_layout' if any(previous.role_layout(r) in v for v in layouts.values()) else 'unmatched_local_combination'} for r in rows]
    artifacts['exposure_audit'] = write_new(output / 'exposure-audit.sealed.json', {
        'schema': 'authored-condition-rehearsal-exposure/v1', **evidence, 'known_pool_references': pool_refs,
        'known_pool_counts': {k: len(v) for k, v in known.items()}, 'known_role_masked_layouts': {k: sorted(v) for k, v in layouts.items()},
        'prior_source_inputs': source_refs, 'real_exposed_views': real_count, 'new_overlap_count': 0,
        'historical_meaning_overlap': 0, 'split_audit': audit,
        'claim': 'Entity/source/meaning-disjoint controlled cases; shared grammar and measured layout exposure; no universal novelty or statutory fidelity claim.'})
    plan = write_new(output / 'plan.json', {'schema': SCHEMA, 'counts': COUNTS, 'added_fitting_rows': 0,
        'label_origin': 'author stipulated controlled examples, not statutory gold', 'may_not_means': 'prohibition by stipulation',
        'condition_scope': 'whole opaque applicability predicate at evaluation origin',
        'temporal_scope': 'action deadline only when separately annotated; condition-owned timing remains opaque',
        'document_profile': 'independent flat rules only; nested normative exceptions/shared conditions/coordination unsupported',
        'provided_that': 'single clause only; excluded from supported docs due frozen boundary surface policy',
        'split_audit': audit, 'fresh_targets_sealed_until_generation_and_build_freeze': True})
    return write_new(output / 'manifest.json', {'schema': SCHEMA, 'frozen_before_training': True,
        'generator': file_ref(__file__), 'dependencies': {'previous': file_ref(previous.__file__)},
        'inputs': {'prior_corpus': file_ref(prior_manifest_path), 'prior_config': file_ref(prior_config_path)},
        'plan': plan, 'artifacts': artifacts, 'counts': COUNTS, 'split_audit': audit, 'sealed_artifacts': list(SEALED),
        'source_semantics_verified': False, 'training_qualified_as_statutory_gold': False, 'training_performed': False})


def load_training_inputs(manifest_path):
    """Read tuning and source-only challenges; never open fresh references."""
    manifest = json.loads(Path(manifest_path).read_bytes())
    require(manifest.get('schema') == SCHEMA and manifest.get('frozen_before_training') is True, 'frozen corpus required')
    require(manifest.get('counts') == COUNTS and manifest.get('sealed_artifacts') == list(SEALED), 'counts/seals differ')
    verify_ref(manifest['generator'])
    for r in list(manifest['dependencies'].values()) + list(manifest['inputs'].values()): verify_ref(r)
    a = manifest['artifacts']
    tuning, pairs = read_ref(a['new_tuning']), read_ref(a['tuning_pairs'])
    previous.validate_pairs(tuning, pairs, 48)
    for r in tuning: validate_row(r)
    docs, ds = read_ref(a['document_tuning_targets']), read_ref(a['document_tuning_sources'])
    fresh, fd = read_ref(a['challenge_sources']), read_ref(a['document_challenge_sources'])
    require(len(tuning) == len(docs) == len(ds) == len(fd) == 96 and len(fresh) == 192, 'bounded denominators required')
    require(all(set(r) == {'id', 'source_text'} and r['id'] == 'condition-rehearsal-fresh-' + sha(r['source_text'].encode())[:24] for r in fresh), 'closed source-only rows required')
    require(all(set(r) == SOURCE_KEYS and r['source_sha256'] == sha(r['source_text'].encode()) for r in ds + fd), 'document source binding differs')
    require(ds == [document_source(r) for r in docs], 'document tuning source/target differs')
    for r in docs: validate_document(r)
    allrows = tuning + docs + fresh + fd
    require(len({r.get('id', r.get('candidate_id')) for r in allrows}) == len(allrows)
        and len({prior.normalized_source(r['source_text']) for r in allrows}) == len(allrows), 'source/identity overlap')
    return {'manifest': manifest, 'new_tuning': tuning, 'tuning_pairs': pairs, 'document_tuning': docs,
            'fresh_sources': fresh, 'fresh_document_sources': fd}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True); parser.add_argument('--prior-manifest', default=str(DEFAULT_PRIOR))
    parser.add_argument('--prior-config', default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    print(json.dumps(freeze(args.output, args.prior_manifest, args.prior_config), sort_keys=True))
