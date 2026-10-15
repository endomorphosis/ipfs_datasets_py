"""Authenticate declared candidate source tuples without adopting governing law.

Exact version/occurrence geometry and caller-declared applicability stay separate
from source authenticity, legal applicability and semantic admission. The full
candidate history is independently regenerated once and retained unchanged.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import corpus_parent_alignment_adapter as alignment
from . import corpus_parent_occurrence_adapter as base
from . import corpus_source as source_records
from . import corpus_source_adjudication as adjudication
from . import corpus_source_application as application
from . import corpus_source_history as history
from . import corpus_source_review as source
from . import corpus_source_review_responses as responses

PROFILE = 'signed-candidate-structured-source-binding-declarations/v1'
DECLARATION_SCHEMA = 'legal-corpus-source-binding-declaration/v1'
CLAIM_SCHEMA = 'legal-corpus-source-binding-signed-claim/v1'
ACTION = 'record_candidate_structured_source_binding/v1'
AUDIENCE = 'legal-autoformalization-candidate-source-bindings/v1'
ASSESSMENT_SCHEMA = 'legal-corpus-source-binding-authority-assessment/v1'
GROUP_SCHEMA = 'legal-corpus-source-binding-group/v1'
MANIFEST_SCHEMA = 'legal-corpus-source-binding-manifest/v1'
PAGE_SCHEMA = 'legal-corpus-source-binding-page/v1'
EFFECT = 'record_exact_declared_version_occurrence_applicability_tuple_only'
HISTORY_COMPONENTS = {key: 'history_' + key for key in history.COMPONENTS}
COMPONENTS = ('manifest', 'pages', 'records', *HISTORY_COMPONENTS.values())
DEFAULT_LIMITS = {**application.DEFAULT_LIMITS, 'max_all_input_bytes': 512 * 1024**2,
    'max_all_input_nodes': 8_000_000, 'max_input_depth': 64,
    'max_all_signed_evidence_bytes': 64 * 1024**2}
FALSE_FLAGS = {**history.FALSE_FLAGS, 'structured_binding_establishes_legal_truth': False,
    'applicability_semantics_verified': False, 'governing_source_adoption_applied': False}
COMMON_FIELDS = {'view', *FALSE_FLAGS, *base.UNSELECTED}
REPLAY_REQUIRED = {'genesis_report', 'genesis_inputs', 'revision_steps', 'genesis_epoch_id',
    'current_epoch_id', 'at_time_utc', 'expected_genesis_manifest_sha256', 'expected_revision_step_pins'}
REPLAY_OPTIONAL = {'limits'}
CHOICE_FIELDS = {'parent_ref', 'comparison_ref', 'document_observation_ref', 'source_version_ref',
    'source_occurrence_ref', 'context_ref', 'declared_region_role', 'applicability'}
APPLICABILITY_FIELDS = {'scope_id', 'jurisdiction_id', 'instrument_id',
    'legal_as_of_civil_date', 'evidence_occurrence_refs'}
REGION_ROLES = ('operative_body', 'editorial_note', 'source_credit', 'unknown')
REF_FIELDS = {'record_cid', 'sha256', 'schema'}
DECLARATION_FIELDS = {'profile', 'binding_effect', 'request_ref', 'subject_ref',
    'current_history_group_ref', 'preparation_manifest_sha256', 'history_manifest_sha256',
    'current_epoch_id', 'queue_ordinal', 'source_review_scope_id', 'selected_answer_variant_refs',
    'choice', 'declared_at_utc', 'rationale', 'evidence_refs', 'status', *COMMON_FIELDS}
GROUP_FIELDS = {'queue_ordinal', 'request_cid', 'original_current_history_group_record',
    'binding_declaration_artifact_ref', 'binding_declaration_record', 'binding_content_status',
    'content_blockers', 'authority_assessment', 'binding_blockers',
    'structured_source_binding_declared_under_selected_profile', 'declared_binding_refs',
    'deferred_review_slot_ids', 'original_contexts_remain_required_unavailable', *COMMON_FIELDS}
MANIFEST_FIELDS = {'profile', 'binding_effect', 'limits', 'history_manifest_ref', 'history_counts',
    'current_epoch_id', 'preparation_manifest_sha256', 'binding_registry_sha256',
    'binding_policy_sha256', 'binding_group_pins', 'evaluation_time_utc', 'producer_pins',
    'page_refs', 'counts', 'population_complete', *COMMON_FIELDS}
PAGE_FIELDS = {'page_ordinal', 'first_group_ordinal', 'entries', *COMMON_FIELDS}
GROUP_INPUT_FIELDS = (application.GROUP_INPUT_FIELDS - {'app_artifact_id'}) | {'binding_artifact_id'}
GROUP_PIN_FIELDS = (application.GROUP_PIN_FIELDS - {'app_artifact_id'}) | {'binding_artifact_id'}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(base._plain(value, contracts.MAX_RECORD_BYTES))


def _ref(value):
    return {'record_cid': value['record_cid'], 'sha256': _digest(value), 'schema': value['schema']}


def _seal(schema, **values):
    payload = {'schema': schema, **values, 'view': 'candidate', **FALSE_FLAGS, **base.UNSELECTED}
    base._plain(payload, contracts.MAX_RECORD_BYTES)
    return contracts.seal_record(payload)


def _pins():
    result = history._pins()
    result[str(Path(__file__).resolve())] = _sha(Path(__file__).read_bytes())
    return result


def _limits(value):
    if value is not None and type(value) is not dict:
        _fail('closed lower-only source binding limits required')
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        if key not in result or type(bound) is not int or not 0 < bound <= result[key]:
            _fail('unknown or raised source binding limit')
        result[key] = bound
    return result


def _reference(value, schema, label):
    contracts.require_keys(value, REF_FIELDS, 'closed ' + label)
    contracts.require_cid(value['record_cid'], label + ' DAG-JSON CID', codecs=('dag-json',))
    contracts.require_sha256(value['sha256'], label + ' FULL canonical SHA256')
    if value['schema'] != schema:
        _fail('fixed ' + label + ' schema required')


def _choice(value, request, bounds):
    value = base._load(base._plain(value, bounds['max_declaration_bytes']), bounds['max_declaration_bytes'])
    contracts.require_keys(value, CHOICE_FIELDS, 'closed explicit candidate source tuple')
    for key, schema in (('parent_ref', base.PARENT_SCHEMA), ('comparison_ref', alignment.OBSERVATION_SCHEMA),
            ('document_observation_ref', alignment.OBSERVATION_SCHEMA), ('source_version_ref', source_records.SOURCE_VERSION_SCHEMA),
            ('source_occurrence_ref', source_records.SOURCE_OCCURRENCE_SCHEMA), ('context_ref', source_records.CONTEXT_DECLARATION_SCHEMA)):
        _reference(value[key], schema, key)
    if (value['parent_ref']['record_cid'] != request['parent_record_cid']
            or value['comparison_ref']['record_cid'] not in request['comparison_record_cids']):
        _fail('binding must preserve the original parent and considered comparison')
    if value['declared_region_role'] not in REGION_ROLES:
        _fail('explicit declared source region role required')
    applicability = value['applicability']
    contracts.require_keys(applicability, APPLICABILITY_FIELDS, 'closed declared applicability scope')
    from . import legal_graph_review as auth
    for key in ('scope_id', 'jurisdiction_id', 'instrument_id'):
        auth._id(applicability[key], 'declared applicability ' + key)
    civil = applicability['legal_as_of_civil_date']
    if civil is not None:
        if type(civil) is not str or re.fullmatch(r'\d{4}-\d{2}-\d{2}', civil) is None:
            _fail('canonical civil date or explicit unknown null required')
        try:
            if date.fromisoformat(civil).isoformat() != civil:
                _fail('canonical civil legal-as-of date required')
        except ValueError as error:
            raise contracts.CorpusContractError('valid declared civil legal-as-of date required') from error
    refs = applicability['evidence_occurrence_refs']
    if type(refs) is not list or not 0 < len(refs) <= 256:
        _fail('bounded explicit applicability evidence occurrences required')
    for ref in refs:
        _reference(ref, source_records.SOURCE_OCCURRENCE_SCHEMA, 'applicability evidence occurrence')
    if len({ref['record_cid'] for ref in refs}) != len(refs):
        _fail('duplicate applicability evidence occurrences')
    return value


def _unit(request, subject, current, epoch_id):
    request = contracts.validate_record(base._load(base._plain(request, contracts.MAX_RECORD_BYTES), contracts.MAX_RECORD_BYTES),
        schema=source.REQUEST_SCHEMA, fields=source.REQUEST_FIELDS)
    subject = contracts.validate_record(base._load(base._plain(subject, contracts.MAX_RECORD_BYTES), contracts.MAX_RECORD_BYTES),
        schema=source.SUBJECT_SCHEMA, fields=source.SUBJECT_FIELDS)
    current = contracts.validate_record(base._load(base._plain(current, contracts.MAX_RECORD_BYTES), contracts.MAX_RECORD_BYTES),
        schema=history.GROUP_SCHEMA, fields=history.GROUP_FIELDS)
    if (current['epoch_id'] != epoch_id or current['request_cid'] != request['record_cid']
            or current['queue_ordinal'] != request['queue_ordinal'] or subject['review_request_cid'] != request['record_cid']
            or subject['graph_sha256'] != _digest(request) or subject['source_binding_sha256'] != request['source_binding_sha256']
            or subject['context_slot_ids'] != request['context_slot_ids']):
        _fail('exact original request subject and current history group required')
    _, _, _, selected = application._unit(request, subject,
        current['snapshot_group_record']['original_adjudication_group_record'])
    if current['current_active_answer_variant_refs'] != selected:
        _fail('complete exact nine current answer references required for binding authoring')
    return request, subject, current, selected


def record_source_binding_declaration(request, subject, current_history_group, choice, *,
        expected_request_sha256, expected_subject_sha256, expected_current_history_group_sha256,
        expected_preparation_manifest_sha256, expected_history_manifest_sha256, current_epoch_id,
        declared_at_utc, rationale, evidence_refs, limits=None):
    """Author structured intent; structural pins do not authenticate a history."""
    bounds = _limits(limits)
    for digest in (expected_request_sha256, expected_subject_sha256, expected_current_history_group_sha256,
            expected_preparation_manifest_sha256, expected_history_manifest_sha256):
        contracts.require_sha256(digest, 'independent binding FULL record/root SHA256')
    from . import legal_graph_review as auth
    auth._id(current_epoch_id, 'explicit current binding epoch ID')
    request, subject, current, selected = _unit(request, subject, current_history_group, current_epoch_id)
    if [_digest(value) for value in (request, subject, current)] != [expected_request_sha256, expected_subject_sha256, expected_current_history_group_sha256]:
        _fail('independently pinned binding request subject or current history differs')
    choice = _choice(choice, request, bounds)
    auth._time(declared_at_utc)
    contracts.require_text(rationale, 'explicit source binding rationale', max_bytes=8192)
    evidence_refs = json.loads(base._plain(evidence_refs, bounds['max_declaration_bytes']))
    responses._refs(evidence_refs)
    if not evidence_refs:
        _fail('explicit exact binding evidence references required')
    record = _seal(DECLARATION_SCHEMA, profile=PROFILE, binding_effect=EFFECT,
        request_ref=_ref(request), subject_ref=_ref(subject), current_history_group_ref=_ref(current),
        preparation_manifest_sha256=expected_preparation_manifest_sha256,
        history_manifest_sha256=expected_history_manifest_sha256, current_epoch_id=current_epoch_id,
        queue_ordinal=request['queue_ordinal'], source_review_scope_id=request['review_scope_id'],
        selected_answer_variant_refs=selected, choice=choice, declared_at_utc=declared_at_utc,
        rationale=rationale, evidence_refs=evidence_refs, status='declared_unauthenticated_candidate_structured_source_binding')
    base._plain(record, bounds['max_declaration_bytes'])
    return record


def validate_source_binding_declaration(record, *args, **kwargs):
    bounds = _limits(kwargs.get('limits'))
    checked = contracts.validate_record(base._load(base._plain(record, bounds['max_declaration_bytes']), bounds['max_declaration_bytes']),
        schema=DECLARATION_SCHEMA, fields=DECLARATION_FIELDS)
    expected = record_source_binding_declaration(*args, **kwargs)
    if canonical_dag_json_bytes(checked) != canonical_dag_json_bytes(expected):
        _fail('source binding declaration differs from exact declared inputs')
    return checked


def _current_inputs(replay):
    if replay['current_epoch_id'] == replay['genesis_epoch_id']:
        return replay['genesis_inputs']
    matches = [step for step in replay['revision_steps'] if step['epoch_id'] == replay['current_epoch_id']]
    if len(matches) != 1:
        _fail('one explicit supplied current history epoch required')
    return matches[0]


def _project(groups, pins):
    result, result_pins = [], []
    for rows, fields, target in ((groups, GROUP_INPUT_FIELDS, result), (pins, GROUP_PIN_FIELDS, result_pins)):
        if type(rows) is not list:
            _fail('complete ordered binding groups and pins required')
        for row in rows:
            contracts.require_keys(row, fields, 'closed binding group or independent pin')
            target.append({('app_artifact_id' if key == 'binding_artifact_id' else key): value for key, value in row.items()})
    return result, result_pins


def _groups(groups, pins, preparation, bounds):
    projected = [{('declaration_artifact_id' if key == 'app_artifact_id' else key): value
        for key, value in row.items()} for row in groups]
    projected_pins = [{('declaration_artifact_id' if key == 'app_artifact_id' else key): value
        for key, value in row.items()} for row in pins]
    detached = adjudication._groups(projected, projected_pins, preparation, bounds)
    for row in detached:
        row['app_artifact_id'] = row.pop('declaration_artifact_id')
    return detached


def _preflight_all(history_report, replay, registry, policy, groups, pins, bounds):
    if type(replay) is not dict or not REPLAY_REQUIRED <= set(replay) or set(replay) - REPLAY_REQUIRED - REPLAY_OPTIONAL:
        _fail('closed complete fixed history replay inputs required')
    detached, _ = history._clone({'history_report': history_report, 'replay': replay,
        'registry': registry, 'policy': policy, 'groups': groups, 'pins': pins}, bounds)
    history_report, replay, registry, policy, groups, pins = (detached[key] for key in
        ('history_report', 'replay', 'registry', 'policy', 'groups', 'pins'))
    history_bounds = history._limits(replay.get('limits'))
    genesis, steps = replay['genesis_inputs'], replay['revision_steps']
    if (type(genesis) is not dict or not history.GENESIS_REQUIRED <= set(genesis)
            or set(genesis) - history.GENESIS_REQUIRED - {'limits'} or type(steps) is not list
            or len(steps) + 1 > history_bounds['max_epochs']):
        _fail('complete bounded fixed genesis and revision inputs required')
    total = history._preflight_epoch(genesis, genesis['application_groups'], genesis['expected_application_group_pins'], application._limits(genesis.get('limits')))
    population = len(genesis['adjudication_replay_inputs']['preparation']['requests'])
    for step in steps:
        if type(step) is not dict or not history.STEP_REQUIRED <= set(step) or set(step) - history.STEP_REQUIRED - {'limits'}:
            _fail('closed complete fixed revision step required')
        projected = history._project(step['revision_groups'], step['expected_revision_group_pins'])
        total += history._preflight_epoch(step, *projected, application._limits(step.get('limits')))
        population += len(step['adjudication_replay_inputs']['preparation']['requests'])
    if total > history_bounds['max_all_signed_evidence_bytes'] or population > history_bounds['max_total_groups']:
        _fail('complete supplied history signed evidence or population exceeds bound')
    current = _current_inputs(replay)
    preparation = current['adjudication_replay_inputs']['preparation']
    if len(preparation['requests']) > bounds['max_groups']:
        _fail('complete current binding population exceeds bound')
    projected = _project(groups, pins)
    application._preflight(*projected, preparation, bounds, application=True)
    total += history._signed_charge(projected[0])
    if total > bounds['max_all_signed_evidence_bytes']:
        _fail('whole history and binding mixed signed evidence exceeds bound before hashing')
    _history_output_budget(history_report, history_bounds)
    revision_pins = replay['expected_revision_step_pins']
    if type(revision_pins) is not list or len(revision_pins) != len(steps):
        _fail('complete bounded revision step pins required')
    for pin in revision_pins:
        contracts.require_keys(pin, history.STEP_PIN_FIELDS, 'closed revision step pin')
    from . import legal_graph_review as auth
    auth._id(replay['genesis_epoch_id'], 'explicit source binding genesis epoch ID')
    auth._id(replay['current_epoch_id'], 'explicit source binding current epoch ID')
    history._epoch_metadata(genesis, steps, replay['genesis_epoch_id'], replay['current_epoch_id'],
        auth._time(replay['at_time_utc']))
    return history_report, replay, registry, policy, projected


def _history_output_budget(report, bounds):
    contracts.require_keys(report, history.COMPONENTS, 'complete offered candidate history')
    retained = 0
    for key, cap in (('manifest', 1), ('pages', bounds['max_pages']), ('records', bounds['max_total_groups']),
            ('epoch_manifests', bounds['max_epochs']), ('epoch_pages', bounds['max_epochs'] * adjudication.DEFAULT_LIMITS['max_pages'])):
        values = [report[key]] if key == 'manifest' else report[key]
        if type(values) is not list or len(values) > cap:
            _fail('complete bounded offered history component required')
        for row in values:
            retained += len(base._plain(row, min(contracts.MAX_RECORD_BYTES, bounds['max_collection_bytes'] - retained))) + 1
    if source._aggregate_size(report) > bounds['max_collection_bytes']:
        _fail('complete offered history exceeds collection bound')


def _catalog(replay):
    """Decode already fully regenerated current source inputs; no original replay."""
    original = replay['alignment_replay_inputs']
    records = [*source._jsonl(original['base_corpus_bytes']['records'], base.DEFAULT_LIMITS['max_records']),
        *source._jsonl(replay['alignment_corpus_bytes']['records'], alignment.DEFAULT_LIMITS['max_records'])]
    by_cid = {record['record_cid']: record for record in records}
    if len(by_cid) != len(records):
        _fail('complete original source catalog has duplicate identities')
    report = base._load(original['alignment_report_bytes'], alignment.DEFAULT_LIMITS['max_alignment_report_bytes'])
    documents = original['document_inputs']
    document_rows = [record for record in records if record['schema'] == alignment.OBSERVATION_SCHEMA and record['kind'] == 'document']
    versions = {}
    for record in document_rows:
        index = record['document_index']
        if type(index) is not int or not 0 <= index < len(documents):
            _fail('exact original document observation index required')
        item, official = documents[index], report['official_documents'][index]
        if official['document_index'] != index:
            _fail('ordered original document catalog differs')
        for origin, field in (('official', 'normalized_source_version_cid'), ('rendered', 'rendered_source_version_cid')):
            cid = record['related_records'][field]
            if cid is None:
                continue
            text = official['view_report']['document']['document_text'] if origin == 'official' else official['rendered_field_view']['text']
            version = by_cid[cid]
            expected = {'version': version, 'text': text, 'raw_bytes': item['raw_bytes'],
                'raw_sha256': item['expected_raw_sha256'], 'extracted_sha256': version['extracted_view']['sha256'],
                'document_cid': record['record_cid']}
            key = (cid, record['record_cid'])
            if key in versions and versions[key] != expected:
                _fail('ambiguous original version document membership')
            versions[key] = expected
    return {'records': by_cid, 'versions': versions}


def _selected(ref, catalog, label):
    value = catalog['records'].get(ref['record_cid'])
    if value is None or _ref(value) != ref:
        _fail('exact existing ' + label + ' absent from replayed original source catalog')
    return value


def _geometry(choice, request, catalog):
    parent = _selected(choice['parent_ref'], catalog, 'parent')
    comparison = _selected(choice['comparison_ref'], catalog, 'comparison')
    document = _selected(choice['document_observation_ref'], catalog, 'document observation')
    if (parent['record_cid'] != request['parent_record_cid'] or comparison['kind'] != 'comparison'
            or document['kind'] != 'document' or comparison['parent_index'] != request['parent_index']
            or comparison['document_index'] != document['document_index']
            or comparison['related_records']['parent_record_cid'] != parent['record_cid']
            or comparison['related_records']['document_record_cid'] != document['record_cid']):
        _fail('binding comparison document or parent membership differs')
    version = _selected(choice['source_version_ref'], catalog, 'comparison source version')
    info = catalog['versions'].get((version['record_cid'], document['record_cid']))
    if info is None or info['document_cid'] != document['record_cid'] or info['raw_bytes'] is None:
        _fail('existing official normalized or rendered version with original bytes required')
    arguments = {'source_version': version, 'expected_raw_sha256': info['raw_sha256'],
        'extracted_text': info['text'], 'expected_extracted_sha256': info['extracted_sha256']}
    source_records.validate_source_version(version, expected_raw_sha256=info['raw_sha256'], extracted_text=info['text'],
        expected_extracted_sha256=info['extracted_sha256'], raw_bytes=info['raw_bytes'])
    occurrence = _selected(choice['source_occurrence_ref'], catalog, 'source occurrence')
    source_records.validate_source_occurrence(occurrence, **arguments)
    context = _selected(choice['context_ref'], catalog, 'occurrence context')
    source_records.validate_context_declaration(context, source_occurrence=occurrence, expected_occurrence_cid=occurrence['record_cid'])
    for ref in choice['applicability']['evidence_occurrence_refs']:
        source_records.validate_source_occurrence(_selected(ref, catalog, 'applicability evidence occurrence'), **arguments)


def _content(group, request, subject, current, variants, catalog, preparation_sha, history_sha, epoch_id, bounds):
    identity = group['app_artifact_id']
    if identity is None:
        return None, []
    try:
        raw = group['evidence_artifacts'][identity]
        record = contracts.validate_record(base._load(raw, bounds['max_declaration_bytes']), schema=DECLARATION_SCHEMA, fields=DECLARATION_FIELDS)
        expected = record_source_binding_declaration(request, subject, current, record['choice'],
            expected_request_sha256=_digest(request), expected_subject_sha256=_digest(subject),
            expected_current_history_group_sha256=_digest(current), expected_preparation_manifest_sha256=preparation_sha,
            expected_history_manifest_sha256=history_sha, current_epoch_id=epoch_id,
            declared_at_utc=record['declared_at_utc'], rationale=record['rationale'], evidence_refs=record['evidence_refs'], limits=bounds)
        if canonical_dag_json_bytes(record) != canonical_dag_json_bytes(expected):
            _fail('binding exact roots current group or nine selected references differ')
        _geometry(record['choice'], request, catalog)
        common = {'artifact_id': identity, 'sha256': _sha(raw)}
        obligations = []
        for slot, ref in zip(request['context_slot_ids'], record['selected_answer_variant_refs'], strict=True):
            variant = variants.get(ref['record_cid'])
            if variant is None or _ref(variant) != ref or variant['slot_id'] != slot or variant['request_cid'] != request['record_cid']:
                _fail('binding exact current selected typed answer differs')
            disposition = responses.DISPOSITIONS[variant['answer']['disposition']]
            if disposition == 'open':
                _fail('unresolved current answer cannot support a candidate binding')
            obligations.append({'slot_id': slot, 'disposition': disposition, 'evidence_refs': [common]})
        for ref in record['evidence_refs']:
            body = group['evidence_artifacts'].get(ref['artifact_id'])
            if ref['artifact_id'] == identity or body is None or _sha(body) != ref['sha256']:
                _fail('binding supporting evidence missing changed or self-referential')
        for claim in group['reviews']:
            closure = claim['context_closure']
            if closure['obligations'] != obligations or closure['unresolved'] or closure['status'] != 'declared_complete':
                _fail('binding requires exact common nine-slot signed declaration')
        return record, []
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        return None, [str(error)[:512] or 'invalid_source_binding_content']


def _pages(entries, bounds):
    pages, refs = [], []
    index = 0
    while index < len(entries):
        chunk = []
        while index + len(chunk) < len(entries) and len(chunk) < bounds['max_groups_per_page']:
            candidate = _seal(PAGE_SCHEMA, page_ordinal=len(pages), first_group_ordinal=index,
                entries=[*chunk, entries[index + len(chunk)]])
            if len(base._plain(candidate, contracts.MAX_RECORD_BYTES)) > bounds['max_page_bytes']:
                break
            chunk.append(entries[index + len(chunk)])
        if not chunk or len(pages) >= bounds['max_pages']:
            _fail('source binding pages exceed lowered bounds')
        page = _seal(PAGE_SCHEMA, page_ordinal=len(pages), first_group_ordinal=index, entries=chunk)
        pages.append(page)
        refs.append({**_ref(page), 'page_ordinal': len(pages) - 1,
            'first_group_ordinal': index, 'entry_count': len(chunk)})
        index += len(chunk)
    return pages, refs


def assess_source_bindings(history_report, history_replay_inputs, binding_registry, binding_policy, binding_groups, *,
        expected_history_manifest_sha256, expected_binding_registry_sha256, expected_binding_policy_sha256,
        expected_binding_group_pins, limits=None):
    """Replay complete history once; authenticate only declared candidate tuples."""
    bounds = _limits(limits)
    for digest in (expected_history_manifest_sha256, expected_binding_registry_sha256, expected_binding_policy_sha256):
        contracts.require_sha256(digest, 'independent source binding history/trust FULL SHA256')
    offered, replay, registry, policy, projected = _preflight_all(history_report, history_replay_inputs,
        binding_registry, binding_policy, binding_groups, expected_binding_group_pins, bounds)
    from . import legal_graph_review as auth
    auth._id(replay['current_epoch_id'], 'current candidate binding epoch ID')
    evaluation = auth._time(replay['at_time_utc'])
    registry = application._trust(registry, expected_binding_registry_sha256)
    policy = application._trust(policy, expected_binding_policy_sha256)
    auth._trust(registry, policy, expected_binding_registry_sha256, expected_binding_policy_sha256, action=ACTION, audience=AUDIENCE)
    if _digest(offered['manifest']) != expected_history_manifest_sha256:
        _fail('independently selected complete candidate history root differs')
    producers = _pins()
    checked = history.validate_source_history(offered, **replay)
    current_inputs = _current_inputs(replay)
    original = current_inputs['adjudication_replay_inputs']
    preparation = original['preparation']
    preparation_sha = original['expected_preparation_manifest_sha256']
    current_groups = [row for row in checked['records'] if row['epoch_id'] == replay['current_epoch_id']]
    if len(current_groups) != len(preparation['requests']):
        _fail('complete current history binding population differs')
    groups = _groups(projected[0], projected[1], preparation, bounds)
    catalog = _catalog(original)
    variants = {row['record_cid']: row for row in original['typed_response_report']['answer_variants']}
    principals, dids, public = history._original_actors([replay['genesis_inputs'], *replay['revision_steps']])
    keys = {row['key_id']: row for row in registry['keys']}
    domain = auth._ReviewDomain(source.SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE, ASSESSMENT_SCHEMA, source._subject, source.ACTIVE_SLOT_COUNT)
    records, entries, retained, active, bodies, authenticated = [], [], 0, 0, 0, 0
    for ordinal, (request, subject, dependency, current, group, pin) in enumerate(zip(preparation['requests'],
            preparation['subjects'], preparation['dependency_manifests'], current_groups, groups, projected[1], strict=True)):
        record, content_blockers = _content(group, request, subject, current, variants, catalog,
            preparation_sha, expected_history_manifest_sha256, replay['current_epoch_id'], bounds)
        assessment = auth._assess_reviews(subject, registry, policy, group['reviews'], dependency, domain=domain,
            expected_subject_sha256=_digest(subject), expected_registry_sha256=expected_binding_registry_sha256,
            expected_policy_sha256=expected_binding_policy_sha256, expected_reviews_sha256=pin['reviews_sha256'],
            expected_manifest_sha256=dependency['manifest_sha256'], at_time_utc=replay['at_time_utc'],
            observed_artifact_sha256s=group['observed_artifact_sha256s'], observed_pins=group['observed_pins'], evidence_artifacts=group['evidence_artifacts'])
        blockers = []
        if not current['current_candidate_refs_eligible_under_selected_history_profile']:
            blockers.append('current_history_candidate_prerequisites_unavailable')
        if any(claim['principal_id'] in principals for claim in group['reviews']):
            blockers.append('binding_actor_is_a_supplied_history_original_reviewer')
        if any(claim['signer_did'] in dids for claim in group['reviews']):
            blockers.append('binding_actor_reuses_a_supplied_history_original_reviewer_did')
        if any(keys.get(claim['key_id'], {}).get('public_key_hex') in public for claim in group['reviews']):
            blockers.append('binding_actor_reuses_a_supplied_history_original_reviewer_public_key')
        if record is not None:
            declared = auth._time(record['declared_at_utc'])
            if declared > evaluation:
                blockers.append('binding_declared_after_evaluation')
            upstream_body = current['snapshot_group_record']['application_declaration_record']
            if declared < auth._time(upstream_body['declared_at_utc']):
                blockers.append('binding_predates_selected_current_snapshot_declaration')
            upstream_claims = current_inputs.get('revision_groups', current_inputs.get('application_groups'))[ordinal]['reviews']
            if any(declared < auth._time(claim['issued_at_utc']) for claim in upstream_claims):
                blockers.append('binding_predates_selected_current_snapshot_claim')
            if any(auth._time(claim['issued_at_utc']) < declared for claim in group['reviews']):
                blockers.append('binding_claim_predates_common_declaration')
            if record['choice']['applicability']['legal_as_of_civil_date'] is None:
                blockers.append('declared_legal_as_of_civil_date_unavailable')
            if record['choice']['declared_region_role'] == 'unknown':
                blockers.append('declared_source_region_role_unavailable')
        eligible = record is not None and not content_blockers and not blockers and assessment['review_prerequisites_satisfied_under_selected_trust']
        identity = group['app_artifact_id']
        raw_ref = None if identity is None else {'artifact_id': identity, 'sha256': _sha(group['evidence_artifacts'][identity])}
        result = _seal(GROUP_SCHEMA, queue_ordinal=ordinal, request_cid=request['record_cid'],
            original_current_history_group_record=current, binding_declaration_artifact_ref=raw_ref,
            binding_declaration_record=record, binding_content_status='absent' if identity is None else 'valid_declared_content' if record is not None else 'rejected',
            content_blockers=content_blockers, authority_assessment=assessment, binding_blockers=blockers,
            structured_source_binding_declared_under_selected_profile=eligible, declared_binding_refs=[_ref(record)] if eligible else [],
            deferred_review_slot_ids=request['deferred_review_slot_ids'], original_contexts_remain_required_unavailable=True)
        retained += len(base._plain(result, min(contracts.MAX_RECORD_BYTES, bounds['max_collection_bytes'] - retained))) + 1
        records.append(result)
        entries.append({'ordinal': ordinal, 'request_cid': request['record_cid'], 'group_record_ref': _ref(result)})
        active += int(eligible)
        bodies += int(identity is not None)
        authenticated += assessment['authenticated_evidence_count']
    pages, page_refs = _pages(entries, bounds)
    manifest = _seal(MANIFEST_SCHEMA, profile=PROFILE, binding_effect=EFFECT, limits=bounds,
        history_manifest_ref=_ref(checked['manifest']), history_counts=checked['manifest']['counts'],
        current_epoch_id=replay['current_epoch_id'], preparation_manifest_sha256=preparation_sha,
        binding_registry_sha256=expected_binding_registry_sha256, binding_policy_sha256=expected_binding_policy_sha256,
        binding_group_pins=[{('binding_artifact_id' if key == 'app_artifact_id' else key): value
            for key, value in pin.items()} for pin in projected[1]],
        evaluation_time_utc=replay['at_time_utc'], producer_pins=producers,
        page_refs=page_refs, counts={'groups': len(records), 'pages': len(pages), 'binding_bodies': bodies,
            'authenticated_binding_claims': authenticated, 'declared_structured_bindings': active,
            'declared_active_answer_slots': active * 9, 'blocked_groups': len(records) - active,
            'blocked_active_slots': (len(records) - active) * 9, 'deferred_questions': len(records) * 7,
            'source_decisions_applied': 0, 'physical_governing_bindings_applied': 0}, population_complete=True)
    report = {'manifest': manifest, 'pages': pages, 'records': records,
        **{target: checked[key] for key, target in HISTORY_COMPONENTS.items()}}
    if source._aggregate_size(report) > bounds['max_collection_bytes'] or _pins() != producers:
        _fail('complete source binding output exceeds bound or producer pins changed')
    return report


def _output_budget(report, bounds):
    contracts.require_keys(report, COMPONENTS, 'complete eight-component binding report')
    retained = 0
    shapes = {'manifest': (1, MANIFEST_SCHEMA, MANIFEST_FIELDS),
        'pages': (bounds['max_pages'], PAGE_SCHEMA, PAGE_FIELDS),
        'records': (bounds['max_groups'], GROUP_SCHEMA, GROUP_FIELDS),
        'history_manifest': (1, history.MANIFEST_SCHEMA, history.MANIFEST_FIELDS),
        'history_pages': (history.DEFAULT_LIMITS['max_pages'], history.PAGE_SCHEMA, history.PAGE_FIELDS),
        'history_records': (history.DEFAULT_LIMITS['max_total_groups'], history.GROUP_SCHEMA, history.GROUP_FIELDS),
        'history_epoch_manifests': (history.DEFAULT_LIMITS['max_epochs'], history.EPOCH_SCHEMA, history.EPOCH_FIELDS),
        'history_epoch_pages': (history.DEFAULT_LIMITS['max_epochs'] * adjudication.DEFAULT_LIMITS['max_pages'], history.EPOCH_PAGE_SCHEMA, history.EPOCH_PAGE_FIELDS)}
    for key, (cap, schema, fields) in shapes.items():
        values = [report[key]] if key in ('manifest', 'history_manifest') else report[key]
        if type(values) is not list or len(values) > cap:
            _fail('complete bounded binding output component required')
        for value in values:
            if fields is not None:
                contracts.require_keys(value, {'schema', 'record_cid', 'cid_scope', *fields}, 'closed binding output record')
                if value['schema'] != schema or value['cid_scope'] != contracts.RECORD_CID_SCOPE:
                    _fail('fixed binding output schema required')
            retained += len(base._plain(value, min(contracts.MAX_RECORD_BYTES, bounds['max_collection_bytes'] - retained))) + 1
    if source._aggregate_size(report) > bounds['max_collection_bytes']:
        _fail('complete offered source binding report exceeds collection bound')


def validate_source_bindings(report, *args, **kwargs):
    bounds = _limits(kwargs.get('limits'))
    _output_budget(report, bounds)
    expected = assess_source_bindings(*args, **kwargs)
    checked = {}
    for key, schema, fields in (('manifest', MANIFEST_SCHEMA, MANIFEST_FIELDS), ('pages', PAGE_SCHEMA, PAGE_FIELDS), ('records', GROUP_SCHEMA, GROUP_FIELDS)):
        values = [report[key]] if key == 'manifest' else report[key]
        rows = [contracts.validate_record(base._load(base._plain(value, contracts.MAX_RECORD_BYTES), contracts.MAX_RECORD_BYTES), schema=schema, fields=fields) for value in values]
        checked[key] = rows[0] if key == 'manifest' else rows
    retained_history = history._detach({key: report[target] for key, target in HISTORY_COMPONENTS.items()}, history.DEFAULT_LIMITS)
    checked.update({target: retained_history[key] for key, target in HISTORY_COMPONENTS.items()})
    for key in COMPONENTS:
        left = [checked[key]] if key.endswith('manifest') else checked[key]
        right = [expected[key]] if key.endswith('manifest') else expected[key]
        if len(left) != len(right) or any(canonical_dag_json_bytes(a) != canonical_dag_json_bytes(b) for a, b in zip(left, right, strict=True)):
            _fail('source binding report differs from complete independent regeneration')
    if _pins() != expected['manifest']['producer_pins']:
        _fail('source binding producers changed during validation')
    return checked


__all__ = ['record_source_binding_declaration', 'validate_source_binding_declaration',
    'assess_source_bindings', 'validate_source_bindings']
