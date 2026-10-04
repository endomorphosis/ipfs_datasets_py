"""Prospective authored temporal-attachment examples, not statutory meaning gold.

A source query supplies a time interval from the complete lexical proposer.
Unique owners are author stipulations within this controlled grammar. Copular,
unpunctuated qualifier tails keep two candidate attachments and no unique owner.
All coordinates are Unicode code-point intervals in the exact stored source.
"""
from __future__ import annotations

import calendar
from collections import Counter
from copy import deepcopy
from datetime import date
import hashlib
import itertools
import json
from pathlib import Path
import random
import re

SCHEMA = 'authored-temporal-ownership-corpus/v1'
ANNOTATION_SCHEMA = 'authored-temporal-ownership-annotation/v1'
LABELS = ('norm', 'condition', 'exception', 'ambiguous')
TIME_FORMS = ('days', 'hours', 'iso_date', 'month_date')
COUNTS = {'train': 768, 'tuning': 144, 'fresh': 192, 'multi_fresh': 96}
GROUP_COUNTS = {'train': 192, 'tuning': 36, 'fresh': 48, 'multi_fresh': 48}
SOURCE_KEYS = {'id', 'source_text', 'source_sha256', 'proposed_time_span'}
TARGET_KEYS = SOURCE_KEYS | {'label', 'group_id', 'annotation'}
SPAN_KEYS = {'char_start', 'char_end', 'text'}
SEALED = ('fresh_targets', 'multi_fresh_targets', 'fresh_annotation_ledger', 'exposure_audit')
AUTHORITY = 'prospectively_authored_controlled_attachment_not_independent_legal_gold'
RELEASE_RULE = 'Fresh targets, ledger and exposure audit remain sealed until training selection and source-only generation freeze.'
FAMILIES = ('fronted_deadline', 'modal_interposed_deadline', 'postobject_deadline')
MODALS = {'O': 'shall', 'P': 'may', 'F': 'shall not'}
LEXICONS = {
    'train': {'actors': ('Alder', 'Birch', 'Cedar', 'Dogwood'),
              'actions': ('file', 'archive', 'register', 'record'),
              'objects': ('application packet', 'license ledger', 'permit record', 'notice register')},
    'tuning': {'actors': ('Elm', 'Fir', 'Ginkgo', 'Hazel'),
               'actions': ('submit', 'deliver', 'catalog', 'log'),
               'objects': ('review bundle', 'request dossier', 'approval form', 'service certificate')},
    'fresh': {'actors': ('Juniper', 'Larch', 'Maple', 'Oak'),
              'actions': ('transmit', 'dispatch', 'retain', 'present'),
              'objects': ('appeal folio', 'inspection schedule', 'registration brief', 'compliance return')},
    'multi_fresh': {'actors': ('Pine', 'Quince', 'Rowan', 'Spruce'),
                    'actions': ('publish', 'forward', 'store', 'issue'),
                    'objects': ('audit chart', 'assessment sheet', 'authorization journal', 'clearance statement')},
}
STYLES = {
    'train': ('Section {n}. Duties.— ', '[Rule {n}] ', 'Rule {n}: '),
    'tuning': ('ARTICLE {n} — ', '(Provision {n}) ', 'Duty {n}. '),
    'fresh': ('§ {n}(b) [Operation]. ', 'Subpart {n} :: ', '{{{n}}} Performance / '),
    'multi_fresh': ('Part {n} / Attachments: ', '({n})(ii)— ', 'Schedule [{n}]: '),
}
_MONTHS = '|'.join(calendar.month_name[1:])
TIME_RE = re.compile(r'(?<!\w)(?:within [1-9]\d{0,2} (?:days|hours) of notice|'
                     r'before \d{4}-\d{2}-\d{2}|before (?:' + _MONTHS + r') [1-9]\d?, \d{4})(?!\w)')
MAX_SOURCE_CHARS = 4096
MAX_FILE_BYTES = 64 * 1024**2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def digest(value):
    return sha(wire(value))


def file_ref(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}


def read_ref(ref):
    require(type(ref) is dict and set(ref) == {'path', 'sha256', 'bytes'}, 'closed file reference required')
    require(type(ref['bytes']) is int and 0 <= ref['bytes'] <= MAX_FILE_BYTES, 'bounded integer file size required')
    path = Path(ref['path']); require(path.is_absolute(), 'absolute file reference required')
    raw = path.read_bytes()
    require(len(raw) == ref['bytes'] and sha(raw) == ref['sha256'], 'file reference changed')
    return strict_json(raw)


def strict_json(raw):
    require(len(raw) <= MAX_FILE_BYTES, 'JSON byte limit exceeded')
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'duplicate JSON key'); out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write_new(path, value):
    path = Path(path)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n')
    return file_ref(path)


def propose_time_spans(source_text):
    """Enumerate every supported lexical occurrence without attachment decisions."""
    require(type(source_text) is str and 0 < len(source_text) <= MAX_SOURCE_CHARS, 'bounded source text required')
    spans = []
    for match in TIME_RE.finditer(source_text):
        text = match.group()
        if text.startswith('before '):
            body = text[7:]
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', body):
                date.fromisoformat(body)
            else:
                month, day, year = body.replace(',', '').split()
                date(int(year), list(calendar.month_name).index(month), int(day))
        spans.append({'char_start': match.start(), 'char_end': match.end()})
    return spans


def query(source_text, interval):
    source_sha = sha(source_text)
    return {'id': 'occ-' + digest([source_sha, interval['char_start'], interval['char_end']]),
            'source_text': source_text, 'source_sha256': source_sha,
            'proposed_time_span': deepcopy(interval)}


def validate_source_query(row):
    require(type(row) is dict and set(row) == SOURCE_KEYS, 'closed four-field source query required')
    text = row['source_text']; require(type(text) is str and 0 < len(text) <= MAX_SOURCE_CHARS, 'bounded source text required')
    interval = row['proposed_time_span']
    require(type(interval) is dict and set(interval) == {'char_start', 'char_end'}, 'closed time interval required')
    start, end = interval['char_start'], interval['char_end']
    require(type(start) is int and type(end) is int and 0 <= start < end <= len(text), 'integer time interval required')
    require(interval in propose_time_spans(text), 'proposed interval must be one complete lexical time occurrence')
    require(row['source_sha256'] == sha(text) and row['id'] == query(text, interval)['id'], 'source/occurrence identity changed')
    return row


def source_row(target):
    return validate_source_query({key: deepcopy(target[key]) for key in SOURCE_KEYS})


class Writer:
    def __init__(self):
        self.text = ''

    def add(self, text):
        start = len(self.text); self.text += text
        return {'char_start': start, 'char_end': len(self.text), 'text': text}

    def span(self, start, end):
        return {'char_start': start, 'char_end': end, 'text': self.text[start:end]}


def time_literal(split, case, form):
    amount = 11 + case % 17
    year = 2041 + list(LEXICONS).index(split)
    day = 1 + case % 28
    return {'days': f'within {amount} days of notice',
            'hours': f'within {amount} hours of notice',
            'iso_date': f'before {year}-09-{day:02d}',
            'month_date': f'before September {day}, {year}'}[form]


def ambiguity_countermodels(qualifier_owner):
    require(qualifier_owner in ('condition', 'exception'), 'qualifier alternative required')
    return {
        'authority': 'illustrative_attachment_countermodels_not_legal_truth',
        'candidate_readings': [
            {'owner': 'norm', 'time_test_applies_to': 'action_event'},
            {'owner': qualifier_owner, 'time_test_applies_to': 'qualifier_event_or_state'}],
        'abstract_assumptions': ['Time values are abstract relative ticks; origin0 and cutoff1 are stipulated.',
                                 'The tested relation is origin<=event<cutoff; this is not a full norm or compliance model.'],
        'worlds': [
            {'action_time': 0, 'qualifier_time': 2, 'origin': 0, 'cutoff': 1,
             'norm_attachment_time_test': True, 'qualifier_attachment_time_test': False},
            {'action_time': 2, 'qualifier_time': 0, 'origin': 0, 'cutoff': 1,
             'norm_attachment_time_test': False, 'qualifier_attachment_time_test': True}],
        'unique_owner_asserted': False, 'legal_truth_verified': False,
    }


def _render_source(split, case, owners, group_kind):
    """Assign every interval at insertion time; never relabel legacy text."""
    require(split in LEXICONS and type(case) is int and 0 <= case < GROUP_COUNTS[split], 'known bounded case required')
    require(group_kind in ('single', 'multi') and owners and len(set(owners)) == len(owners)
            and set(owners) <= set(LABELS), 'known distinct owner queries required')
    lexical = LEXICONS[split]; form = TIME_FORMS[case % 4]
    modality = 'OPF'[(case // 4) % 3] if group_kind == 'single' else 'OPF'[(case // 8 + case % 4 + (case // 4) % 2) % 3]
    family = FAMILIES[case % 3]; family_index = FAMILIES.index(family)
    style_index = (case // 4 + case % 4) % 3
    actor = f"the {lexical['actors'][case % 4]} registry {case + 1000}"
    action_object = f"{lexical['actions'][case % 4]} the {lexical['objects'][case % 4]} {case + 1000}"
    condition_subject = f"the {lexical['actors'][(case + 1) % 4].lower()} application {case + 1000}"
    exception_subject = f"the {lexical['actors'][(case + 2) % 4].lower()} waiver {case + 1000}"
    condition_event = condition_subject + (' was received' if case % 2 == 0 else ' was recorded')
    exception_event = exception_subject + (' was issued' if case % 2 == 0 else ' was registered')
    condition_state, exception_state = condition_subject + ' is valid', exception_subject + ' is active'
    ambiguous_owner = ('exception' if 'condition' in owners else 'condition' if 'exception' in owners
                       else ('condition', 'exception')[case % 2])
    timed_qualifiers = {owner for owner in owners if owner in ('condition', 'exception')}
    if 'ambiguous' in owners:
        require(ambiguous_owner not in timed_qualifiers, 'ambiguous and definite owner require different qualifier anchors')
    w = Writer(); heading = w.add(STYLES[split][style_index].format(n=case + 1))
    body_start = len(w.text); spans = {}; cues = {}; time_spans = {}
    literal = time_literal(split, case, form)

    def emit_time(owner):
        require(owner not in time_spans, 'one time per queried owner required')
        time_spans[owner] = w.add(literal)

    if 'norm' in owners and family_index == 0:
        emit_time('norm'); w.add(', ')
    spans['actor'] = w.add(actor); w.add(' ')
    cues['norm'] = w.add(MODALS[modality])
    if 'norm' in owners and family_index == 1:
        w.add(', '); emit_time('norm'); w.add(',')
    w.add(' '); spans['action_object'] = w.add(action_object)
    if 'norm' in owners and family_index == 2:
        w.add(', '); emit_time('norm'); w.add(',')
    for owner in ('condition', 'exception'):
        w.add(' ')
        start = len(w.text); cues[owner] = w.add('if' if owner == 'condition' else 'unless'); w.add(' ')
        timed = owner in timed_qualifiers
        is_ambiguous = 'ambiguous' in owners and owner == ambiguous_owner
        text = (condition_event if owner == 'condition' else exception_event) if timed else (condition_state if owner == 'condition' else exception_state)
        spans[owner + '_anchor'] = w.add(text)
        if timed or is_ambiguous:
            w.add(' '); emit_time(owner if timed else 'ambiguous')
        spans[owner + '_scope'] = w.span(start, len(w.text))
        # Explicit receipt predicates supply authored qualifier attachment; no
        # missing comma is converted into a norm-owned training label.
    body_end = len(w.text); w.add('.')
    body = w.span(body_start, body_end)
    group_id = 'group-' + digest([SCHEMA, split, group_kind, case])
    results = []
    for label in owners:
        time_span = time_spans[label]
        interval = {key: time_span[key] for key in ('char_start', 'char_end')}
        candidates = ('norm', ambiguous_owner) if label == 'ambiguous' else (label,)
        owner_candidates = []
        for owner in candidates:
            owner_candidates.append({'owner': owner,
                'anchor_span': deepcopy(spans['action_object'] if owner == 'norm' else spans[owner + '_anchor']),
                'scope_span': deepcopy(body if owner == 'norm' else spans[owner + '_scope'])})
        annotation = {'schema': ANNOTATION_SCHEMA, 'split': split, 'case_index': case,
            'source_kind': group_kind, 'construction_family': family, 'section_style_index': style_index,
            'modality': modality, 'time_form': form, 'heading_span': heading,
            'time_span': deepcopy(time_span),
            'time_cue_span': w.span(time_span['char_start'], time_span['char_start'] + len(literal.split()[0])),
            'attachment_cue_spans': [{'owner': owner, 'span': deepcopy(cues[owner])} for owner in candidates],
            'owner_candidates': owner_candidates,
            'lexical_spans': [{'role': role, 'span': deepcopy(spans[role])}
                              for role in ('actor', 'action_object', 'condition_anchor', 'exception_anchor')],
            'unique_owner_asserted': label != 'ambiguous',
            'countermodels': ambiguity_countermodels(ambiguous_owner) if label == 'ambiguous' else None,
            'annotation_authority': AUTHORITY, 'independently_reviewed': False,
            'source_semantics_verified': False, 'legal_gold': False}
        row = {**query(w.text, interval), 'label': label, 'group_id': group_id, 'annotation': annotation}
        validate_source_query(source_row(row)); results.append(row)
    require(sorted(time_spans.values(), key=lambda s:s['char_start']) == [w.span(x['char_start'], x['char_end']) for x in propose_time_spans(w.text)],
            'insertion annotations must cover every proposed time occurrence')
    return results


def make_group(split, case):
    require(split in GROUP_COUNTS and type(case) is int and 0 <= case < GROUP_COUNTS[split], 'known split/case required')
    if split == 'multi_fresh':
        pair = tuple(itertools.combinations(LABELS, 2))[case // 8]
        rows = _render_source(split, case, pair, 'multi')
    else:
        rows = [row for label in LABELS for row in _render_source(split, case, (label,), 'single')]
    return deepcopy(rows)


def validate_target(row):
    require(type(row) is dict and set(row) == TARGET_KEYS, 'closed target schema required')
    validate_source_query(source_row(row))
    require(row['label'] in LABELS and type(row['annotation']) is dict, 'known ownership target required')
    annotation = row['annotation']; split = annotation.get('split'); case = annotation.get('case_index')
    require(split in GROUP_COUNTS and type(case) is int and 0 <= case < GROUP_COUNTS[split], 'exact authored factor provenance required')
    expected = [target for target in make_group(split, case) if target['id'] == row['id']]
    require(len(expected) == 1 and wire(expected[0]) == wire(row), 'target differs from source-bound insertion provenance')
    return row


def group_record(rows):
    return {'group_id': rows[0]['group_id'], 'query_ids': sorted(row['id'] for row in rows),
            'source_kind': rows[0]['annotation']['source_kind']}


def make_panel(split):
    groups = [make_group(split, case) for case in range(GROUP_COUNTS[split])]
    rows = [row for group in groups for row in group]
    random.Random(741903 + list(COUNTS).index(split)).shuffle(rows)
    return rows, [group_record(group) for group in groups]


def validate_panel(rows, groups, split, *, reconstruct=True):
    require(type(rows) is list and type(groups) is list and len(rows) == COUNTS[split]
            and len(groups) == GROUP_COUNTS[split], 'complete panel inventory required')
    ids = [row['id'] for row in rows]
    require(len(set(ids)) == len(ids), 'duplicate source-occurrence query')
    require(Counter(row['label'] for row in rows) == Counter({label: len(rows)//4 for label in LABELS}), 'ownership class counts differ')
    require(len({group['group_id'] for group in groups}) == len(groups), 'duplicate group')
    lookup = {row['id']: row for row in rows}; seen = set()
    for group in groups:
        require(type(group) is dict and set(group) == {'group_id', 'query_ids', 'source_kind'}, 'closed group required')
        query_ids = group['query_ids']
        require(type(query_ids) is list and len(query_ids) == (2 if split == 'multi_fresh' else 4)
                and len(set(query_ids)) == len(query_ids) and query_ids == sorted(query_ids)
                and set(query_ids) <= set(lookup) and not seen.intersection(query_ids), 'complete unique group membership required')
        selected = [lookup[item] for item in query_ids]
        require(all(row['group_id'] == group['group_id'] and row['annotation']['split'] == split
                    and row['annotation']['source_kind'] == group['source_kind'] for row in selected), 'group provenance differs')
        if split != 'multi_fresh':
            require(Counter(row['label'] for row in selected) == Counter(LABELS), 'one ownership class per quartet required')
        else:
            require(len({row['source_sha256'] for row in selected}) == 1 and len({row['label'] for row in selected}) == 2,
                    'multi group must query two owners in one source')
        require(len({row['annotation']['time_span']['text'] for row in selected}) == 1, 'matched group time lexeme differs')
        seen.update(query_ids)
    require(seen == set(ids), 'unassigned query')
    for row in rows:
        if reconstruct: validate_target(row)
        else: validate_source_query(source_row(row))
    validate_query_inventory([source_row(row) for row in rows], expected=len(rows))
    return rows


def validate_query_inventory(rows, *, expected=None):
    require(type(rows) is list and (expected is None or len(rows) == expected), 'source query inventory differs')
    ids = set(); by_source = {}
    for row in rows:
        validate_source_query(row); require(row['id'] not in ids, 'duplicate occurrence ID'); ids.add(row['id'])
        key = row['source_sha256']; by_source.setdefault(key, {'text':row['source_text'], 'spans':[]})
        require(by_source[key]['text'] == row['source_text'], 'source digest collision')
        by_source[key]['spans'].append(row['proposed_time_span'])
    for source in by_source.values():
        require(sorted(source['spans'], key=lambda span:span['char_start']) == propose_time_spans(source['text']),
                'source pack omits or duplicates a proposed time occurrence')
    return rows


def normalized_source(text):
    return ' '.join(text.casefold().split())


def layout(row):
    a = row['annotation']; replacements = [(item['span']['char_start'], item['span']['char_end'], '['+item['role']+']') for item in a['lexical_spans']]
    replacements += [(span['char_start'], span['char_end'], '[TIME]') for span in propose_time_spans(row['source_text'])]
    text = row['source_text']
    for start, end, marker in sorted(replacements, reverse=True): text = text[:start] + marker + text[end:]
    # Headings retain punctuation/word order; only section-number identity is removed.
    return re.sub(r'\d+', '#', text)


def exposure_audit(panels, historical_source_packs):
    histories = set(); historical_refs = []
    for path in historical_source_packs:
        ref = file_ref(path); rows = read_ref(ref); require(type(rows) is list, 'source-only history list required')
        for row in rows:
            require(type(row) is dict and set(row) == {'candidate_id','source_sha256','source_text'}, 'history must be closed source-only rows')
            require(sha(row['source_text']) == row['source_sha256'], 'historical source hash mismatch')
            histories.add(normalized_source(row['source_text']))
        historical_refs.append(ref)
    seen = {}; layouts = {}; result = {}
    for split, (rows, groups) in panels.items():
        sources = {normalized_source(row['source_text']) for row in rows}
        require(not sources.intersection(histories), 'new source duplicates an exposed source')
        require(not any(sources.intersection(old) for old in seen.values()), 'source crosses prospective split')
        seen[split] = sources; layouts[split] = {layout(row) for row in rows}
        result[split] = {'queries': len(rows), 'source_documents': len(sources), 'groups': len(groups),
            'labels': dict(Counter(row['label'] for row in rows)),
            'time_forms_by_label': {label: dict(Counter(row['annotation']['time_form'] for row in rows if row['label']==label)) for label in LABELS},
            'modalities_by_label': {label: dict(Counter(row['annotation']['modality'] for row in rows if row['label']==label)) for label in LABELS},
            'source_sha256': sorted({row['source_sha256'] for row in rows}),
            'role_masked_layouts': sorted(layouts[split]),
            'matches_train_layout': sum(layout(row) in layouts.get('train',set()) for row in rows)}
    return {'schema': 'authored-temporal-ownership-exposure/v1', 'panels': result,
        'historical_source_packs': historical_refs, 'historical_unique_sources_checked': len(histories),
        'historical_source_overlap': 0, 'prospective_source_overlap': 0,
        'lexical_inventories': deepcopy(LEXICONS), 'section_styles': deepcopy(STYLES),
        'shared_attachment_grammar': True, 'held_apart_factors': ['case entities','selected content vocabulary','section-style renderers'],
        'novel_statutory_semantics_claimed': False,
        'limitations': ['Exact role-masked layouts retain heading words and punctuation; this is not a universal unseen-grammar claim.',
                       'Historical exclusions cover only the explicitly pinned source packs, not every historical artifact.',
                       'Multi-occurrence sources are a separate new-composition diagnostic, not an independently reviewed legal benchmark.']}


def producer_refs():
    root = Path(__file__).resolve().parents[3]
    return [file_ref(Path(__file__)), file_ref(root/'scripts/ops/legal_ir/prepare_legal_temporal_ownership_corpus.py')]


def build_corpus(output, historical_source_packs=()):
    output = Path(output).resolve(); require(not output.exists(), 'new corpus directory required')
    panels = {split: make_panel(split) for split in COUNTS}
    for split, (rows, groups) in panels.items(): validate_panel(rows, groups, split)
    exposure = exposure_audit(panels, historical_source_packs)
    output.mkdir(parents=True)
    artifacts = {}
    for split in ('train','tuning'):
        rows, groups = panels[split]
        artifacts[split+'_targets'] = write_new(output/(split+'-targets.json'), rows)
        artifacts[split+'_groups'] = write_new(output/(split+'-groups.json'), groups)
    for split in ('fresh','multi_fresh'):
        rows, groups = panels[split]
        artifacts[split+'_sources'] = write_new(output/(split.replace('_','-')+'-sources.json'), [source_row(row) for row in rows])
        artifacts[split+'_targets'] = write_new(output/(split.replace('_','-')+'-targets.json'), rows)
    artifacts['fresh_annotation_ledger'] = write_new(output/'fresh-annotation-ledger.json', {
        'schema':'authored-temporal-ownership-reference-ledger/v1',
        'groups':{split:panels[split][1] for split in ('fresh','multi_fresh')},
        'annotations':{split:[{'id':row['id'],'source_sha256':row['source_sha256'],'group_id':row['group_id'],
                              'label':row['label'],'annotation':row['annotation']} for row in panels[split][0]] for split in ('fresh','multi_fresh')}})
    artifacts['exposure_audit'] = write_new(output/'exposure-audit.json', exposure)
    manifest = {'schema': SCHEMA, 'counts': COUNTS, 'group_counts': GROUP_COUNTS,
        'labels':list(LABELS), 'artifacts': artifacts, 'sealed_artifacts':list(SEALED),
        'producer_files':producer_refs(), 'historical_source_packs':exposure['historical_source_packs'],
        'source_query_keys':sorted(SOURCE_KEYS), 'group_ids_used_as_model_features':False,
        'owner_spans_used_as_model_features':False, 'proposed_time_spans_supplied':True,
        'proposer_enumerates_all_supported_occurrences':True, 'training_labels_authority':AUTHORITY,
        'independent_legal_gold':False, 'shared_attachment_grammar':True, 'all_logic_families_validated':False,
        'reference_release_rule':RELEASE_RULE}
    return write_new(output/'manifest.json', manifest)


def load_training_inputs(manifest_path):
    manifest_ref = file_ref(manifest_path); manifest = read_ref(manifest_ref)
    expected_keys = {'schema','counts','group_counts','labels','artifacts','sealed_artifacts','producer_files',
        'historical_source_packs','source_query_keys','group_ids_used_as_model_features','owner_spans_used_as_model_features',
        'proposed_time_spans_supplied','proposer_enumerates_all_supported_occurrences','training_labels_authority',
        'independent_legal_gold','shared_attachment_grammar','all_logic_families_validated','reference_release_rule'}
    require(type(manifest) is dict and set(manifest)==expected_keys and manifest['schema']==SCHEMA, 'closed manifest schema required')
    require(wire(manifest['counts'])==wire(COUNTS) and wire(manifest['group_counts'])==wire(GROUP_COUNTS)
            and manifest['labels']==list(LABELS) and manifest['sealed_artifacts']==list(SEALED), 'manifest counts/taxonomy changed')
    require(wire(manifest['producer_files'])==wire(producer_refs()), 'producer pins changed')
    require(manifest['source_query_keys']==sorted(SOURCE_KEYS) and manifest['group_ids_used_as_model_features'] is False
            and manifest['owner_spans_used_as_model_features'] is False and manifest['independent_legal_gold'] is False
            and manifest['all_logic_families_validated'] is False and manifest['proposed_time_spans_supplied'] is True
            and manifest['proposer_enumerates_all_supported_occurrences'] is True
            and manifest['shared_attachment_grammar'] is True and manifest['training_labels_authority']==AUTHORITY
            and manifest['reference_release_rule']==RELEASE_RULE,
            'manifest authority/input-scope flags changed')
    expected_artifacts = {'train_targets','train_groups','tuning_targets','tuning_groups','fresh_sources','multi_fresh_sources',*SEALED}
    require(type(manifest['artifacts']) is dict and set(manifest['artifacts'])==expected_artifacts, 'artifact inventory differs')
    for ref in manifest['artifacts'].values():
        require(type(ref) is dict and set(ref)=={'path','sha256','bytes'} and type(ref['bytes']) is int
                and 0 <= ref['bytes'] <= MAX_FILE_BYTES and type(ref['path']) is str and Path(ref['path']).is_absolute()
                and type(ref['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}',ref['sha256']) is not None, 'closed artifact reference required')
    require(len({ref['path'] for ref in manifest['artifacts'].values()}) == len(expected_artifacts), 'artifact paths must be distinct')
    artifacts = manifest['artifacts']; loaded = {'manifest':manifest, 'manifest_ref':manifest_ref}
    admitted_sources = set()
    for split in ('train','tuning'):
        rows = read_ref(artifacts[split+'_targets']); groups = read_ref(artifacts[split+'_groups'])
        validate_panel(rows,groups,split)
        sources = {normalized_source(row['source_text']) for row in rows}
        require(not sources.intersection(admitted_sources),'admitted split source overlap')
        admitted_sources.update(sources); loaded[split]=rows; loaded[split+'_groups']=groups
    for split in ('fresh','multi_fresh'):
        sources = read_ref(artifacts[split+'_sources']); validate_query_inventory(sources,expected=COUNTS[split])
        values = {normalized_source(row['source_text']) for row in sources}
        require(not values.intersection(admitted_sources),'source-only evaluation overlaps admitted or another evaluation split')
        admitted_sources.update(values); loaded[split+'_sources']=sources
    return loaded
