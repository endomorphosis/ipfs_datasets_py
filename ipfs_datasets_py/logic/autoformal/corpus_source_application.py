"""Activate signed candidate source-answer snapshots without legal admission.

The fixed genesis profile copies nine exact adjudicated answer references. A
separate signing domain authorizes this narrow effect. Original source records,
competing answers and all semantic/training/Lean authority remain unchanged.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import corpus_parent_occurrence_adapter as base
from . import corpus_source_adjudication as adjudication
from . import corpus_source_review as source
from . import corpus_source_review_responses as responses

PROFILE = 'signed-genesis-candidate-source-answer-snapshot/v1'
DECLARATION_SCHEMA = 'legal-corpus-source-application-declaration/v1'
CLAIM_SCHEMA = 'legal-corpus-source-application-signed-claim/v1'
ACTION = 'activate_candidate_source_answer_snapshot/v1'
AUDIENCE = 'legal-autoformalization-candidate-source-application/v1'
ASSESSMENT_SCHEMA = 'legal-corpus-source-application-authority-assessment/v1'
GROUP_SCHEMA = 'legal-corpus-source-application-group/v1'
MANIFEST_SCHEMA = 'legal-corpus-source-application-manifest/v1'
PAGE_SCHEMA = 'legal-corpus-source-application-page/v1'
EFFECT = 'copy_exact_declared_answer_variant_references_only'
USE_SCOPE = 'candidate_source_context_answers'
COMPONENTS = ('manifest', 'pages', 'records')
DEFAULT_LIMITS = dict(adjudication.DEFAULT_LIMITS)
FALSE_FLAGS = {**adjudication.FALSE_FLAGS, 'physical_governing_bindings_applied': False,
    'historical_predecessor_qualified': False, 'snapshot_name_uniqueness_verified': False}
COMMON_FIELDS = {'view', *FALSE_FLAGS, *base.UNSELECTED}
DESCRIPTOR_FIELDS = {'snapshot_id', 'use_scope', 'generation', 'previous_snapshot_manifest_ref'}
DECLARATION_FIELDS = {'profile', 'activation_effect', 'snapshot_descriptor', 'request_ref', 'subject_ref',
    'adjudication_group_ref', 'preparation_manifest_sha256', 'typed_response_manifest_sha256',
    'adjudication_manifest_sha256', 'queue_ordinal', 'source_review_scope_id', 'selected_answer_variant_refs',
    'declared_at_utc', 'rationale', 'evidence_refs', 'status', *COMMON_FIELDS}
GROUP_FIELDS = {'queue_ordinal', 'request_cid', 'original_adjudication_group_record',
    'application_declaration_artifact_ref', 'application_declaration_record', 'application_content_status',
    'content_blockers', 'authority_assessment', 'application_blockers',
    'source_answer_snapshot_activated_under_selected_profile', 'activated_answer_variant_refs',
    'deferred_review_slot_ids', 'original_contexts_remain_required_unavailable', *COMMON_FIELDS}
MANIFEST_FIELDS = {'profile', 'activation_effect', 'snapshot_descriptor', 'limits',
    'adjudication_manifest_ref', 'preparation_manifest_sha256', 'typed_response_manifest_sha256',
    'application_registry_sha256', 'application_policy_sha256', 'application_group_pins',
    'evaluation_time_utc', 'producer_pins', 'page_refs', 'counts', 'population_complete', *COMMON_FIELDS}
PAGE_FIELDS = {'page_ordinal', 'first_group_ordinal', 'entries', *COMMON_FIELDS}
GROUP_INPUT_FIELDS = (adjudication.GROUP_INPUT_FIELDS - {'declaration_artifact_id'}) | {'app_artifact_id'}
GROUP_PIN_FIELDS = (adjudication.GROUP_PIN_FIELDS - {'declaration_artifact_id'}) | {'app_artifact_id'}
REPLAY_REQUIRED = {'preparation', 'source_registry', 'source_policy', 'source_review_groups',
    'typed_response_report', 'adjudication_registry', 'adjudication_policy', 'adjudication_groups',
    'expected_typed_response_manifest_sha256', 'expected_adjudication_registry_sha256',
    'expected_adjudication_policy_sha256', 'expected_adjudication_group_pins', 'response_bindings',
    'expected_response_bindings_sha256', 'expected_preparation_manifest_sha256', 'expected_registry_sha256',
    'expected_policy_sha256', 'expected_review_group_pins', 'at_time_utc', 'alignment_corpus_bytes',
    'expected_alignment_corpus_pins', 'alignment_replay_inputs', 'source_report_bytes', 'expected_source_report_pins'}
REPLAY_OPTIONAL = {'source_review_limits', 'typed_response_limits', 'limits'}


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


def _limits(value):
    if value is not None and type(value) is not dict:
        _fail('closed lower-only source application limits required')
    bounds = dict(DEFAULT_LIMITS)
    for key, limit in (value or {}).items():
        if key not in bounds or type(limit) is not int or not 0 < limit <= bounds[key]:
            _fail('unknown or raised source application limit')
        bounds[key] = limit
    return bounds


def _pins():
    result = adjudication._pins()
    result[str(Path(__file__).resolve())] = _sha(Path(__file__).read_bytes())
    return result


def _descriptor(value):
    value = base._load(base._plain(value, contracts.MAX_RECORD_BYTES), contracts.MAX_RECORD_BYTES)
    contracts.require_keys(value, DESCRIPTOR_FIELDS, 'closed genesis candidate snapshot descriptor')
    from . import legal_graph_review as auth
    auth._id(value['snapshot_id'], 'explicit candidate snapshot identity')
    if (value['use_scope'] != USE_SCOPE or type(value['generation']) is not int or value['generation'] != 1
            or value['previous_snapshot_manifest_ref'] is not None):
        _fail('only generation one with no predecessor and fixed candidate answer use is supported')
    return value


def _unit(request, subject, group):
    rows = []
    for value, schema, fields in ((request, source.REQUEST_SCHEMA, source.REQUEST_FIELDS),
            (subject, source.SUBJECT_SCHEMA, source.SUBJECT_FIELDS),
            (group, adjudication.GROUP_SCHEMA, adjudication.GROUP_FIELDS)):
        rows.append(contracts.validate_record(base._load(base._plain(value, contracts.MAX_RECORD_BYTES),
            contracts.MAX_RECORD_BYTES), schema=schema, fields=fields))
    request, subject, group = rows
    if (subject['review_request_cid'] != request['record_cid'] or subject['graph_sha256'] != _digest(request)
            or group['request_cid'] != request['record_cid'] or group['queue_ordinal'] != request['queue_ordinal']):
        _fail('exact original source application request and subject/group required')
    declaration = group['declaration_record']
    if declaration is None or group['declaration_content_status'] != 'valid_declared_content':
        _fail('a complete valid-content adjudication declaration is required for application authoring')
    declaration = contracts.validate_record(declaration, schema=adjudication.DECLARATION_SCHEMA,
        fields=adjudication.DECLARATION_FIELDS)
    choices = declaration['decisions']
    if type(choices) is not list or len(choices) != source.ACTIVE_SLOT_COUNT:
        _fail('complete nine selected adjudication choices required')
    for choice in choices:
        contracts.require_keys(choice, {'slot_id','decision','selected_variant_ref','rationale','evidence_refs'}, 'exact selected adjudication choice')
    if ([row.get('slot_id') for row in choices] != request['context_slot_ids']
            or any(row.get('decision') != 'select_existing_variant' or type(row.get('selected_variant_ref')) is not dict for row in choices)):
        _fail('all nine existing adjudicated variants must be explicitly selected; no partial activation')
    for choice in choices:
        ref = choice['selected_variant_ref']
        contracts.require_keys(ref, {'record_cid','sha256','schema'}, 'complete selected typed variant reference')
        contracts.require_cid(ref['record_cid'], 'selected typed variant DAG-JSON CID', codecs=('dag-json',))
        contracts.require_sha256(ref['sha256'], 'selected typed variant FULL canonical SHA256')
        if ref['schema'] != responses.VARIANT_SCHEMA:
            _fail('exact typed answer variant schema required')
    refs = [row['selected_variant_ref'] for row in choices]
    considered = declaration['considered_answer_variant_refs']
    if (type(considered) is not list or len(considered) > 32 * source.ACTIVE_SLOT_COUNT
            or any(ref not in considered for ref in refs)
            or len({ref['record_cid'] for ref in refs}) != source.ACTIVE_SLOT_COUNT):
        _fail('nine distinct exact selected refs from the declared considered population required')
    return request, subject, group, refs


def record_source_application_declaration(request, subject, adjudication_group, descriptor, *,
        expected_request_sha256, expected_subject_sha256, expected_adjudication_group_sha256,
        expected_preparation_manifest_sha256, expected_typed_response_manifest_sha256,
        expected_adjudication_manifest_sha256, declared_at_utc, rationale, evidence_refs, limits=None):
    """Author a body for separate application signatures; authenticates no input."""
    bounds = _limits(limits)
    for pin in (expected_request_sha256, expected_subject_sha256, expected_adjudication_group_sha256,
            expected_preparation_manifest_sha256, expected_typed_response_manifest_sha256, expected_adjudication_manifest_sha256):
        contracts.require_sha256(pin, 'independent application FULL record/root SHA256')
    descriptor = _descriptor(descriptor)
    request, subject, group, refs = _unit(request, subject, adjudication_group)
    if [_digest(value) for value in (request, subject, group)] != [expected_request_sha256, expected_subject_sha256, expected_adjudication_group_sha256]:
        _fail('independent application request/subject/adjudication group differs')
    declaration = group['declaration_record']
    if (declaration['request_ref'] != _ref(request) or declaration['subject_ref'] != _ref(subject)
            or declaration['preparation_manifest_sha256'] != expected_preparation_manifest_sha256
            or declaration['typed_response_manifest_sha256'] != expected_typed_response_manifest_sha256):
        _fail('application declaration must preserve exact adjudication source roots')
    from . import legal_graph_review as auth
    auth._time(declared_at_utc)
    contracts.require_text(rationale, 'explicit application rationale', max_bytes=8192)
    evidence_refs = json.loads(base._plain(evidence_refs, bounds['max_declaration_bytes']))
    responses._refs(evidence_refs)
    if not evidence_refs:
        _fail('explicit application needs exact supporting evidence references')
    record = _seal(DECLARATION_SCHEMA, profile=PROFILE, activation_effect=EFFECT, snapshot_descriptor=descriptor,
        request_ref=_ref(request), subject_ref=_ref(subject), adjudication_group_ref=_ref(group),
        preparation_manifest_sha256=expected_preparation_manifest_sha256,
        typed_response_manifest_sha256=expected_typed_response_manifest_sha256,
        adjudication_manifest_sha256=expected_adjudication_manifest_sha256,
        queue_ordinal=request['queue_ordinal'], source_review_scope_id=request['review_scope_id'],
        selected_answer_variant_refs=refs, declared_at_utc=declared_at_utc, rationale=rationale,
        evidence_refs=evidence_refs, status='declared_unauthenticated_candidate_source_application')
    base._plain(record, bounds['max_declaration_bytes'])
    return record


def validate_source_application_declaration(record, *args, **kwargs):
    bounds = _limits(kwargs.get('limits'))
    checked = contracts.validate_record(base._load(base._plain(record, bounds['max_declaration_bytes']), bounds['max_declaration_bytes']),
        schema=DECLARATION_SCHEMA, fields=DECLARATION_FIELDS)
    expected = record_source_application_declaration(*args, **kwargs)
    if canonical_dag_json_bytes(checked) != canonical_dag_json_bytes(expected):
        _fail('source application body differs from exact declared inputs')
    return checked


def _preflight(groups, pins, preparation, bounds, *, application):
    """Size-only complete mixed/raw budget pass; hashes no indexed body."""
    fields = GROUP_INPUT_FIELDS if application else adjudication.GROUP_INPUT_FIELDS
    pin_fields = GROUP_PIN_FIELDS if application else adjudication.GROUP_PIN_FIELDS
    id_field = 'app_artifact_id' if application else 'declaration_artifact_id'
    if type(groups) is not list or type(pins) is not list or len(groups) != len(preparation['requests']) or len(pins) != len(groups):
        _fail('complete ordered application and adjudication input groups required')
    total = 0
    for group, pin, request in zip(groups, pins, preparation['requests'], strict=True):
        contracts.require_keys(group, fields, 'complete bounded signed input group')
        contracts.require_keys(pin, pin_fields, 'independent complete signed input group pin')
        identity = group[id_field]
        if (group['request_cid'] != request['record_cid'] or pin['request_cid'] != group['request_cid']
                or pin[id_field] != identity or type(group['reviews']) is not list or len(group['reviews']) > 32
                or type(group['evidence_artifacts']) is not dict or len(group['evidence_artifacts']) > 256
                or (not group['reviews'] and identity is not None) or (group['reviews'] and type(identity) is not str)):
            _fail('exact ordered bounded input group and common body required')
        charge = 0
        for name, body in group['evidence_artifacts'].items():
            contracts.require_text(name, 'retained input artifact identity', max_bytes=256)
            if type(body) is not bytes:
                _fail('complete immutable signed evidence bytes required')
            charge += len(body)
        if charge > bounds['max_group_bytes']:
            _fail('complete signed evidence group exceeds bound before hashing')
        for key in ('reviews', 'observed_artifact_sha256s', 'observed_pins'):
            residual = min(bounds['max_group_bytes'] - charge, bounds['max_batch_bytes'] - total - charge)
            if residual <= 0:
                _fail('complete mixed signed evidence budget exhausted before hashing')
            charge += len(base._plain(group[key], residual))
        total += charge
        if total > bounds['max_batch_bytes']:
            _fail('complete signed evidence batch exceeds bound before hashing')
        if identity is not None:
            body = group['evidence_artifacts'].get(identity)
            if type(body) is not bytes or len(body) > bounds['max_declaration_bytes']:
                _fail('complete bounded common declaration bytes required before hashing')


def _trust(value, expected):
    contracts.require_sha256(expected, 'independently selected trust FULL canonical SHA256')
    raw = base._plain(value, 8 * 1024**2)
    if _sha(raw) != expected:
        _fail('independently selected trust differs')
    return base._load(raw, 8 * 1024**2)


def _replay_inputs(values, offered, app_groups, app_pins, bounds):
    if type(values) is not dict or not REPLAY_REQUIRED <= set(values) or set(values) - REPLAY_REQUIRED - REPLAY_OPTIONAL:
        _fail('closed complete adjudication replay input object required')
    result = dict(values)
    adj_bounds = adjudication._limits(result.get('limits'))
    response_bounds = responses._limits(result.get('typed_response_limits'))
    source_bounds = source._limits(result.get('source_review_limits'))
    preparation = source._detach_preparation(result['preparation'], source_bounds)
    if len(preparation['requests']) > bounds['max_groups']:
        _fail('complete original application population exceeds bound')
    result['preparation'] = preparation
    for field, pin in (('source_registry','expected_registry_sha256'), ('source_policy','expected_policy_sha256'),
            ('adjudication_registry','expected_adjudication_registry_sha256'), ('adjudication_policy','expected_adjudication_policy_sha256')):
        result[field] = _trust(result[field], result[pin])
    result['typed_response_report'] = responses._detach(result['typed_response_report'], response_bounds)
    for name in ('expected_review_group_pins', 'expected_adjudication_group_pins'):
        result[name] = json.loads(base._plain(result[name], contracts.MAX_RECORD_BYTES))
    # Every inherited and application evidence population is size-checked first.
    responses._bindings(result['response_bindings'], result['expected_response_bindings_sha256'], preparation,
        result['source_review_groups'], response_bounds, source_bounds, verify_hashes=False)
    adjudication._original_budget(result['source_review_groups'], source_bounds)
    _preflight(result['adjudication_groups'], result['expected_adjudication_group_pins'], preparation, adj_bounds, application=False)
    _preflight(app_groups, app_pins, preparation, bounds, application=True)
    from . import legal_graph_review as auth
    result['source_review_groups'] = source._review_groups(result['source_review_groups'], result['expected_review_group_pins'],
        preparation['subjects'], auth, source_bounds)
    result['adjudication_groups'] = adjudication._groups(result['adjudication_groups'], result['expected_adjudication_group_pins'], preparation, adj_bounds)
    projected = [{('declaration_artifact_id' if key == 'app_artifact_id' else key): value for key, value in row.items()} for row in app_groups]
    projected_pins = [{('declaration_artifact_id' if key == 'app_artifact_id' else key): value for key, value in row.items()} for row in app_pins]
    detached_groups = adjudication._groups(projected, projected_pins, preparation, bounds)
    for row in detached_groups:
        row['app_artifact_id'] = row.pop('declaration_artifact_id')
    if offered['manifest']['preparation_manifest_sha256'] != result['expected_preparation_manifest_sha256']:
        _fail('application original source preparation root differs')
    return result, detached_groups


def _content(group, request, subject, adjudicated, descriptor, preparation_sha, typed_sha, adjudication_sha, variants, bounds):
    identity = group['app_artifact_id']
    if identity is None:
        return None, []
    try:
        raw = group['evidence_artifacts'][identity]
        record = contracts.validate_record(base._load(raw, bounds['max_declaration_bytes']), schema=DECLARATION_SCHEMA, fields=DECLARATION_FIELDS)
        expected = record_source_application_declaration(request, subject, adjudicated, descriptor,
            expected_request_sha256=_digest(request), expected_subject_sha256=_digest(subject),
            expected_adjudication_group_sha256=_digest(adjudicated), expected_preparation_manifest_sha256=preparation_sha,
            expected_typed_response_manifest_sha256=typed_sha, expected_adjudication_manifest_sha256=adjudication_sha,
            declared_at_utc=record['declared_at_utc'], rationale=record['rationale'], evidence_refs=record['evidence_refs'], limits=bounds)
        if canonical_dag_json_bytes(record) != canonical_dag_json_bytes(expected):
            _fail('application_exact_source_snapshot_and_selected_population_differs')
        common_ref = {'artifact_id': identity, 'sha256': _sha(raw)}
        obligations = []
        for slot, ref in zip(request['context_slot_ids'], record['selected_answer_variant_refs'], strict=True):
            variant = variants[ref['record_cid']]
            if _ref(variant) != ref or variant['slot_id'] != slot or variant['request_cid'] != request['record_cid']:
                _fail('application_selected_exact_typed_variant_differs')
            disposition = responses.DISPOSITIONS[variant['answer']['disposition']]
            if disposition == 'open':
                _fail('open_answer_cannot_activate_candidate_snapshot')
            obligations.append({'slot_id':slot, 'disposition':disposition, 'evidence_refs':[common_ref]})
        for ref in record['evidence_refs']:
            body = group['evidence_artifacts'].get(ref['artifact_id'])
            if ref['artifact_id'] == identity or body is None or _sha(body) != ref['sha256']:
                _fail('application_evidence_missing_changed_or_self_referential')
        for claim in group['reviews']:
            closure = claim['context_closure']
            if closure['obligations'] != obligations or closure['unresolved'] or closure['status'] != 'declared_complete':
                _fail('application_needs_exact_complete_signed_nine_slot_activation')
        return record, []
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        return None, [str(error)[:512] or 'invalid_application_content']


def _pages(entries, bounds):
    pages, refs, pending, start = [], [], [], 0
    def seal(items):
        return _seal(PAGE_SCHEMA, page_ordinal=len(pages), first_group_ordinal=start, entries=items)
    def finish():
        if len(pages) >= bounds['max_pages']:
            _fail('complete application page population exceeds bound')
        page = seal(pending)
        base._plain(page, bounds['max_page_bytes'])
        pages.append(page)
        refs.append({**_ref(page), 'page_ordinal':len(pages)-1, 'first_group_ordinal':start, 'entry_count':len(pending)})
    size, retained = len(canonical_dag_json_bytes(seal([]))), 0
    for entry in entries:
        next_size = len(canonical_dag_json_bytes(entry))
        if pending and (len(pending) >= bounds['max_groups_per_page'] or size + retained + next_size + len(pending) + 32 > bounds['max_page_bytes']):
            finish()
            start, pending, retained = entry['ordinal'], [], 0
            size = len(canonical_dag_json_bytes(seal([])))
        pending.append(entry)
        retained += next_size
    if pending:
        finish()
    return pages, refs


def assess_source_applications(adjudication_report, application_registry, application_policy, application_groups,
        descriptor, *, expected_adjudication_manifest_sha256, expected_application_registry_sha256,
        expected_application_policy_sha256, expected_application_group_pins, adjudication_replay_inputs, limits=None):
    """Revalidate the fixed whole upstream population, then assess genesis activation."""
    bounds = _limits(limits)
    descriptor = _descriptor(descriptor)
    if type(adjudication_replay_inputs) is not dict:
        _fail('closed complete adjudication replay input object required')
    offered = adjudication._detach(adjudication_report, adjudication._limits(adjudication_replay_inputs.get('limits')))
    contracts.require_sha256(expected_adjudication_manifest_sha256, 'independent complete adjudication root FULL SHA256')
    if _digest(offered['manifest']) != expected_adjudication_manifest_sha256:
        _fail('independent complete adjudication root differs')
    app_pins = json.loads(base._plain(expected_application_group_pins, contracts.MAX_RECORD_BYTES))
    registry = _trust(application_registry, expected_application_registry_sha256)
    policy = _trust(application_policy, expected_application_policy_sha256)
    from . import legal_graph_review as auth
    auth._trust(registry, policy, expected_application_registry_sha256, expected_application_policy_sha256, action=ACTION, audience=AUDIENCE)
    replay, groups = _replay_inputs(adjudication_replay_inputs, offered, application_groups, app_pins, bounds)
    producer_pins = _pins()
    checked = adjudication.validate_source_adjudications(offered, **replay)
    preparation = replay['preparation']
    evaluation_time = replay['at_time_utc']
    evaluation = auth._time(evaluation_time)
    variants = {row['record_cid']:row for row in replay['typed_response_report']['answer_variants']}
    originals = replay['source_review_groups']
    original_principals = {claim['principal_id'] for group in originals for claim in group['reviews']}
    original_dids = {claim['signer_did'] for group in originals for claim in group['reviews']}
    source_keys = {key['key_id']:key for key in replay['source_registry']['keys']}
    original_public_keys = {source_keys[claim['key_id']]['public_key_hex'] for group in originals for claim in group['reviews'] if claim['key_id'] in source_keys}
    app_keys = {key['key_id']:key for key in registry['keys']}
    domain = auth._ReviewDomain(source.SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE, ASSESSMENT_SCHEMA, source._subject, source.ACTIVE_SLOT_COUNT)
    records, entries, retained, active, bodies, authenticated = [], [], 0, 0, 0, 0
    for ordinal, (request, subject, dependency, upstream, original_adjudication, group, pin) in enumerate(zip(
            preparation['requests'], preparation['subjects'], preparation['dependency_manifests'], checked['records'],
            replay['adjudication_groups'], groups, app_pins, strict=True)):
        record, content_blockers = _content(group, request, subject, upstream, descriptor,
            replay['expected_preparation_manifest_sha256'], replay['expected_typed_response_manifest_sha256'],
            expected_adjudication_manifest_sha256, variants, bounds)
        assessment = auth._assess_reviews(subject, registry, policy, group['reviews'], dependency, domain=domain,
            expected_subject_sha256=_digest(subject), expected_registry_sha256=expected_application_registry_sha256,
            expected_policy_sha256=expected_application_policy_sha256, expected_reviews_sha256=pin['reviews_sha256'],
            expected_manifest_sha256=dependency['manifest_sha256'], at_time_utc=evaluation_time,
            observed_artifact_sha256s=group['observed_artifact_sha256s'], observed_pins=group['observed_pins'], evidence_artifacts=group['evidence_artifacts'])
        blockers = []
        if not upstream['authority_prerequisites_satisfied_under_selected_trust']:
            blockers.append('current_original_and_adjudication_authority_prerequisites_unavailable')
        if any(claim['principal_id'] in original_principals for claim in group['reviews']):
            blockers.append('application_authority_is_a_supplied_original_reviewer')
        if any(claim['signer_did'] in original_dids for claim in group['reviews']):
            blockers.append('application_authority_reuses_an_original_reviewer_did')
        if any(app_keys.get(claim['key_id'], {}).get('public_key_hex') in original_public_keys for claim in group['reviews']):
            blockers.append('application_authority_reuses_an_original_reviewer_public_key')
        if record is not None:
            declared = auth._time(record['declared_at_utc'])
            if declared > evaluation:
                blockers.append('application_declared_after_evaluation')
            if declared < auth._time(upstream['declaration_record']['declared_at_utc']) or any(declared < auth._time(claim['issued_at_utc']) for claim in original_adjudication['reviews']):
                blockers.append('application_predates_adjudication')
            if any(auth._time(claim['issued_at_utc']) < declared for claim in group['reviews']):
                blockers.append('application_authority_claim_predates_common_declaration')
        eligible = (record is not None and not content_blockers and not blockers
            and assessment['review_prerequisites_satisfied_under_selected_trust'])
        identity = group['app_artifact_id']
        artifact_ref = None if identity is None else {'artifact_id':identity, 'sha256':_sha(group['evidence_artifacts'][identity])}
        result = _seal(GROUP_SCHEMA, queue_ordinal=ordinal, request_cid=request['record_cid'],
            original_adjudication_group_record=upstream, application_declaration_artifact_ref=artifact_ref,
            application_declaration_record=record, application_content_status='absent' if identity is None else 'valid_declared_content' if record is not None else 'rejected',
            content_blockers=content_blockers, authority_assessment=assessment, application_blockers=blockers,
            source_answer_snapshot_activated_under_selected_profile=eligible,
            activated_answer_variant_refs=record['selected_answer_variant_refs'] if eligible else [],
            deferred_review_slot_ids=request['deferred_review_slot_ids'], original_contexts_remain_required_unavailable=True)
        retained += len(base._plain(result, min(contracts.MAX_RECORD_BYTES, bounds['max_collection_bytes'] - retained))) + 1
        records.append(result)
        entries.append({'ordinal':ordinal, 'request_cid':request['record_cid'], 'group_record_ref':_ref(result)})
        active += int(eligible)
        bodies += int(identity is not None)
        authenticated += assessment['authenticated_evidence_count']
    pages, page_refs = _pages(entries, bounds)
    manifest = _seal(MANIFEST_SCHEMA, profile=PROFILE, activation_effect=EFFECT, snapshot_descriptor=descriptor, limits=bounds,
        adjudication_manifest_ref=_ref(checked['manifest']), preparation_manifest_sha256=replay['expected_preparation_manifest_sha256'],
        typed_response_manifest_sha256=replay['expected_typed_response_manifest_sha256'],
        application_registry_sha256=expected_application_registry_sha256, application_policy_sha256=expected_application_policy_sha256,
        application_group_pins=app_pins, evaluation_time_utc=evaluation_time, producer_pins=producer_pins, page_refs=page_refs,
        counts={'groups':len(records), 'pages':len(pages), 'application_bodies':bodies, 'authenticated_application_claims':authenticated,
            'activated_candidate_answer_snapshots':active, 'activated_answer_slots':active * source.ACTIVE_SLOT_COUNT,
            'blocked_groups':len(records)-active, 'blocked_active_slots':(len(records)-active) * source.ACTIVE_SLOT_COUNT,
            'deferred_questions':len(records)*7, 'source_decisions_applied':0, 'physical_governing_bindings_applied':0}, population_complete=True)
    report = {'manifest':manifest, 'pages':pages, 'records':records}
    if source._aggregate_size(report) > bounds['max_collection_bytes']:
        _fail('complete source application output exceeds bound')
    if _pins() != producer_pins:
        _fail('application or inherited producers changed during operation')
    return report


def _detach(report, bounds):
    contracts.require_keys(report, COMPONENTS, 'complete source application report')
    result, retained = {}, 0
    for key, schema, fields, cap in (('manifest',MANIFEST_SCHEMA,MANIFEST_FIELDS,1),
            ('pages',PAGE_SCHEMA,PAGE_FIELDS,bounds['max_pages']), ('records',GROUP_SCHEMA,GROUP_FIELDS,bounds['max_groups'])):
        values = [report[key]] if key == 'manifest' else report[key]
        if type(values) is not list or len(values) > cap:
            _fail('complete bounded source application component required')
        rows = []
        for value in values:
            maximum = bounds['max_page_bytes'] if key == 'pages' else contracts.MAX_RECORD_BYTES
            raw = base._plain(value, min(maximum, bounds['max_collection_bytes'] - retained))
            retained += len(raw) + 1
            rows.append(contracts.validate_record(base._load(raw, maximum), schema=schema, fields=fields))
        result[key] = rows[0] if key == 'manifest' else rows
    if source._aggregate_size(result) > bounds['max_collection_bytes']:
        _fail('complete offered source application collection exceeds bound')
    return result


def validate_source_applications(report, *args, **kwargs):
    detached = _detach(report, _limits(kwargs.get('limits')))
    expected = assess_source_applications(*args, **kwargs)
    source._equal_components(detached, expected)
    if _pins() != expected['manifest']['producer_pins']:
        _fail('application producers changed during final comparison')
    return detached


__all__ = ['record_source_application_declaration', 'validate_source_application_declaration',
    'assess_source_applications', 'validate_source_applications']
