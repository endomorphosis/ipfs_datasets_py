"""Authenticate declared source adjudication without applying source decisions.

The typed response owner regenerates the whole original population once. A
fixed new domain reuses the shared signature verifier and original subjects.
Two separately authorized roles attest one common decision body. Original
variants, disagreements and unavailable contexts remain unchanged.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import corpus_parent_occurrence_adapter as base
from . import corpus_source_review as source
from . import corpus_source_review_responses as responses

PROFILE = "explicit-dual-role-source-adjudication-declarations/v1"
DECLARATION_SCHEMA = "legal-corpus-source-adjudication-declaration/v1"
CLAIM_SCHEMA = "legal-corpus-source-adjudication-signed-claim/v1"
ACTION = "record_source_context_adjudication_declaration/v1"
AUDIENCE = "legal-autoformalization-source-adjudication/v1"
ASSESSMENT_SCHEMA = "legal-corpus-source-adjudication-authority-assessment/v1"
GROUP_SCHEMA = "legal-corpus-source-adjudication-group/v1"
MANIFEST_SCHEMA = "legal-corpus-source-adjudication-manifest/v1"
PAGE_SCHEMA = "legal-corpus-source-adjudication-page/v1"
COMPONENTS = ('manifest', 'pages', 'records')
DEFAULT_LIMITS = {'max_groups': 8192, 'max_declaration_bytes': contracts.MAX_RECORD_BYTES,
    'max_group_bytes': 8 * 1024**2, 'max_batch_bytes': 64 * 1024**2,
    'max_groups_per_page': 64, 'max_pages': 256, 'max_page_bytes': contracts.MAX_RECORD_BYTES,
    'max_collection_bytes': 64 * 1024**2}
FALSE_FLAGS = {**responses.FALSE_FLAGS, 'adjudicated_source_meaning_verified': False,
    'source_selection_applied': False, 'adjudicator_human_independence_verified': False}
COMMON_FIELDS = {'view', *FALSE_FLAGS, *base.UNSELECTED}
DECLARATION_FIELDS = {'profile', 'request_ref', 'subject_ref', 'typed_group_ref',
    'preparation_manifest_sha256', 'typed_response_manifest_sha256', 'queue_ordinal',
    'pending_slot_refs', 'considered_answer_variant_refs', 'declared_at_utc', 'decisions', 'status', *COMMON_FIELDS}
GROUP_FIELDS = {'queue_ordinal', 'request_cid', 'typed_response_group_record', 'declaration_artifact_ref',
    'declaration_record', 'declaration_content_status', 'content_blockers', 'authority_assessment',
    'separation_and_chronology_blockers', 'authority_prerequisites_satisfied_under_selected_trust',
    'deferred_review_slot_ids', 'original_contexts_remain_required_unavailable', *COMMON_FIELDS}
MANIFEST_FIELDS = {'profile', 'limits', 'typed_response_manifest_ref', 'preparation_manifest_sha256',
    'adjudication_registry_sha256', 'adjudication_policy_sha256', 'adjudication_group_pins',
    'evaluation_time_utc', 'producer_pins', 'page_refs', 'counts', 'population_complete', *COMMON_FIELDS}
PAGE_FIELDS = {'page_ordinal', 'first_group_ordinal', 'entries', *COMMON_FIELDS}
GROUP_INPUT_FIELDS = {'request_cid', 'reviews', 'declaration_artifact_id', 'evidence_artifacts',
    'observed_artifact_sha256s', 'observed_pins'}
GROUP_PIN_FIELDS = {'request_cid', 'declaration_artifact_id', 'reviews_sha256', 'evidence_sha256s',
    'observed_artifacts_sha256', 'observed_pins_sha256'}


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
        _fail('closed lower-only source adjudication limits required')
    result = dict(DEFAULT_LIMITS)
    for key, bound in (value or {}).items():
        if key not in result or type(bound) is not int or not 0 < bound <= result[key]:
            _fail('unknown or raised source adjudication limit')
        result[key] = bound
    return result


def _pins():
    result = responses._pins()
    result[str(Path(__file__).resolve())] = _sha(Path(__file__).read_bytes())
    return result


def _unit(request, subject, typed_group, pending_slots, variants):
    checked = []
    for record, schema, fields in ((request, source.REQUEST_SCHEMA, source.REQUEST_FIELDS),
            (subject, source.SUBJECT_SCHEMA, source.SUBJECT_FIELDS),
            (typed_group, responses.GROUP_SCHEMA, responses.FIELDS['records'])):
        checked.append(contracts.validate_record(json.loads(base._plain(record, contracts.MAX_RECORD_BYTES)), schema=schema, fields=fields))
    request, subject, typed_group = checked
    if (subject['review_request_cid'] != request['record_cid'] or subject['graph_sha256'] != _digest(request)
            or typed_group['request_cid'] != request['record_cid']
            or typed_group['queue_ordinal'] != request['queue_ordinal']):
        _fail('exact original adjudication request and subject/group required')
    if type(pending_slots) is not list or len(pending_slots) != source.ACTIVE_SLOT_COUNT:
        _fail('complete nine ordered pending source slots required')
    if type(variants) is not list or len(variants) > 32 * source.ACTIVE_SLOT_COUNT:
        _fail('bounded complete per-request answer variants required')
    slots, rows = [], []
    for values, schema, fields, output in ((pending_slots, responses.ADJUDICATION_SCHEMA,
            responses.FIELDS['adjudication_requests'], slots), (variants, responses.VARIANT_SCHEMA,
            responses.FIELDS['answer_variants'], rows)):
        for value in values:
            output.append(contracts.validate_record(json.loads(base._plain(value, contracts.MAX_RECORD_BYTES)), schema=schema, fields=fields))
    if ([_ref(row) for row in slots] != typed_group['adjudication_refs']
            or [row['slot_id'] for row in slots] != request['context_slot_ids']
            or any(row['request_cid'] != request['record_cid'] or row['queue_ordinal'] != request['queue_ordinal'] for row in [*slots, *rows])):
        _fail('complete original pending-slot population differs')
    expected_variants = [ref for slot in slots for ref in slot['answer_variant_refs']]
    if [_ref(row) for row in rows] != expected_variants:
        _fail('complete ordered considered answer variant population differs')
    return request, subject, typed_group, slots, rows


def record_source_adjudication_declaration(request, subject, typed_group, pending_slots, answer_variants,
        decisions, *, expected_request_sha256, expected_subject_sha256, expected_typed_group_sha256,
        expected_preparation_manifest_sha256, expected_typed_response_manifest_sha256, declared_at_utc, limits=None):
    """Record explicit common choices for signing; authoring authenticates none."""
    bounds = _limits(limits)
    for digest in (expected_request_sha256, expected_subject_sha256, expected_typed_group_sha256,
            expected_preparation_manifest_sha256, expected_typed_response_manifest_sha256):
        contracts.require_sha256(digest, 'independent adjudication input FULL SHA256')
    request, subject, typed_group, slots, variants = _unit(request, subject, typed_group, pending_slots, answer_variants)
    if [_digest(value) for value in (request, subject, typed_group)] != [expected_request_sha256, expected_subject_sha256, expected_typed_group_sha256]:
        _fail('independently pinned adjudication input differs')
    from . import legal_graph_review as auth
    auth._time(declared_at_utc)
    decisions = json.loads(base._plain(decisions, bounds['max_declaration_bytes']))
    if type(decisions) is not list or len(decisions) != source.ACTIVE_SLOT_COUNT:
        _fail('complete ordered nine adjudication choices required')
    by_cid = {row['record_cid']: row for row in variants}
    for choice, slot in zip(decisions, slots, strict=True):
        contracts.require_keys(choice, {'slot_id', 'decision', 'selected_variant_ref', 'rationale', 'evidence_refs'}, 'declared source adjudication choice')
        if choice['slot_id'] != slot['slot_id'] or choice['decision'] not in ('select_existing_variant', 'unresolved'):
            _fail('exact supported original source adjudication choice required')
        contracts.require_text(choice['rationale'], 'adjudication rationale', max_bytes=8192)
        responses._refs(choice['evidence_refs'])
        ref = choice['selected_variant_ref']
        if choice['decision'] == 'unresolved':
            if ref is not None:
                _fail('unresolved adjudication cannot select a variant')
        else:
            if type(ref) is not dict or ref not in slot['answer_variant_refs'] or not choice['evidence_refs']:
                _fail('selected adjudication needs present variant and exact evidence')
            selected = by_cid.get(ref.get('record_cid'))
            if (selected is None or _ref(selected) != ref or selected['slot_id'] != slot['slot_id']
                    or selected['answer']['disposition'] not in ('evidence_declared', 'not_applicable')
                    or not selected['respondents']):
                _fail('unresolved or unavailable answer cannot become a selected adjudication')
    record = _seal(DECLARATION_SCHEMA, profile=PROFILE, request_ref=_ref(request), subject_ref=_ref(subject),
        typed_group_ref=_ref(typed_group), preparation_manifest_sha256=expected_preparation_manifest_sha256,
        typed_response_manifest_sha256=expected_typed_response_manifest_sha256, queue_ordinal=request['queue_ordinal'],
        pending_slot_refs=[_ref(row) for row in slots], considered_answer_variant_refs=[_ref(row) for row in variants],
        declared_at_utc=declared_at_utc, decisions=decisions, status='declared_unauthenticated_source_adjudication')
    base._plain(record, bounds['max_declaration_bytes'])
    return record


def validate_source_adjudication_declaration(record, *args, **kwargs):
    bounds = _limits(kwargs.get('limits'))
    checked = contracts.validate_record(base._load(base._plain(record, bounds['max_declaration_bytes']), bounds['max_declaration_bytes']),
        schema=DECLARATION_SCHEMA, fields=DECLARATION_FIELDS)
    expected = record_source_adjudication_declaration(*args, **kwargs)
    if canonical_dag_json_bytes(checked) != canonical_dag_json_bytes(expected):
        _fail('source adjudication body differs from exact declared inputs')
    return checked


def _groups(groups, pins, preparation, bounds):
    """Complete size-only evidence preflight before the first body hash."""
    if type(groups) is not list or type(pins) is not list or len(groups) != len(preparation['requests']) or len(pins) != len(groups):
        _fail('complete ordered source adjudication groups and pins required')
    total = 0
    for group, pin, request in zip(groups, pins, preparation['requests'], strict=True):
        contracts.require_keys(group, GROUP_INPUT_FIELDS, 'source adjudication group')
        contracts.require_keys(pin, GROUP_PIN_FIELDS, 'independent adjudication group pins')
        if group['request_cid'] != request['record_cid'] or pin['request_cid'] != group['request_cid']:
            _fail('original source adjudication group order differs')
        if type(group['reviews']) is not list or len(group['reviews']) > 32 or type(group['evidence_artifacts']) is not dict or len(group['evidence_artifacts']) > 256:
            _fail('bounded complete adjudication reviews and evidence required')
        identity = group['declaration_artifact_id']
        if pin['declaration_artifact_id'] != identity or (not group['reviews'] and identity is not None) or (group['reviews'] and type(identity) is not str):
            _fail('one common declaration body per supplied adjudication group required')
        raw_total = 0
        for name, body in group['evidence_artifacts'].items():
            contracts.require_text(name, 'adjudication evidence ID', max_bytes=256)
            if type(body) is not bytes:
                _fail('complete immutable adjudication evidence required')
            raw_total += len(body)
        if raw_total > bounds['max_group_bytes']:
            _fail('complete adjudication evidence group exceeds bound before hashing')
        charge = raw_total
        for field in ('reviews', 'observed_artifact_sha256s', 'observed_pins'):
            residual = min(bounds['max_group_bytes'] - charge, bounds['max_batch_bytes'] - total - charge)
            if residual <= 0:
                _fail('complete adjudication JSON and evidence budget exhausted before hashing')
            charge += len(base._plain(group[field], residual))
        total += charge
        if total > bounds['max_batch_bytes']:
            _fail('complete adjudication evidence batch exceeds bound before hashing')
        if identity is not None:
            body = group['evidence_artifacts'].get(identity)
            if type(body) is not bytes or len(body) > bounds['max_declaration_bytes']:
                _fail('complete bounded adjudication declaration required before hashing')
    # Reuse source group detachment for all byte namespaces and original budgets.
    from . import legal_graph_review as auth
    projected, projected_pins = [], []
    identities = []
    for group, pin in zip(groups, pins, strict=True):
        identity = group['declaration_artifact_id']
        if identity is not None:
            auth._id(identity, 'common adjudication declaration ID')
        projected.append({key: value for key, value in group.items() if key != 'declaration_artifact_id'})
        projected_pins.append({key: value for key, value in pin.items() if key != 'declaration_artifact_id'})
        identities.append(identity)
    source_bounds = {**source.DEFAULT_LIMITS, 'max_batch_review_bytes': bounds['max_batch_bytes']}
    detached = source._review_groups(projected, projected_pins, preparation['subjects'], auth, source_bounds)
    charged = 0
    for group, identity in zip(detached, identities, strict=True):
        group['declaration_artifact_id'] = identity
        charge = sum(len(body) for body in group['evidence_artifacts'].values())
        charge += sum(len(base._plain(group[key], bounds['max_group_bytes'])) for key in ('reviews', 'observed_artifact_sha256s', 'observed_pins'))
        if charge > bounds['max_group_bytes']:
            _fail('complete adjudication group JSON and evidence exceeds lowered bound')
        charged += charge
        if charged > bounds['max_batch_bytes']:
            _fail('complete adjudication batch JSON and evidence exceeds lowered bound')
    return detached


def _original_budget(groups, bounds):
    """Charge all original raw bodies and metadata before any owner body hash."""
    total = 0
    for group in groups:
        charge = sum(len(body) for body in group['evidence_artifacts'].values())
        for field in ('reviews', 'observed_artifact_sha256s', 'observed_pins'):
            residual = min(8 * 1024**2 - charge, bounds['max_batch_review_bytes'] - total - charge)
            if residual <= 0:
                _fail('complete original source JSON and evidence budget exhausted before hashing')
            charge += len(base._plain(group[field], residual))
        total += charge
        if total > bounds['max_batch_review_bytes']:
            _fail('complete original source mixed byte budget exceeds bound before hashing')


def _content(group, request, subject, typed_group, slots, variants, preparation_sha, typed_sha, bounds):
    identity = group['declaration_artifact_id']
    if identity is None:
        return None, []
    try:
        raw = group['evidence_artifacts'][identity]
        record = contracts.validate_record(base._load(raw, bounds['max_declaration_bytes']), schema=DECLARATION_SCHEMA, fields=DECLARATION_FIELDS)
        expected = record_source_adjudication_declaration(request, subject, typed_group, slots, variants, record['decisions'],
            expected_request_sha256=_digest(request), expected_subject_sha256=_digest(subject), expected_typed_group_sha256=_digest(typed_group),
            expected_preparation_manifest_sha256=preparation_sha, expected_typed_response_manifest_sha256=typed_sha,
            declared_at_utc=record['declared_at_utc'], limits=bounds)
        if canonical_dag_json_bytes(record) != canonical_dag_json_bytes(expected):
            _fail('adjudication_exact_source_and_considered_population_differs')
        by_cid = {row['record_cid']: row for row in variants}
        obligations, unresolved = [], []
        common_ref = {'artifact_id': identity, 'sha256': _sha(raw)}
        for decision in record['decisions']:
            if decision['decision'] == 'unresolved':
                disposition = 'open'
                unresolved.append(decision['slot_id'])
            else:
                answer = by_cid[decision['selected_variant_ref']['record_cid']]['answer']
                disposition = responses.DISPOSITIONS[answer['disposition']]
            obligations.append({'slot_id': decision['slot_id'], 'disposition': disposition, 'evidence_refs': [common_ref]})
            for ref in decision['evidence_refs']:
                body = group['evidence_artifacts'].get(ref['artifact_id'])
                if ref['artifact_id'] == identity or body is None or _sha(body) != ref['sha256']:
                    _fail('adjudication_evidence_missing_changed_or_self_referential')
        for claim in group['reviews']:
            closure = claim['context_closure']
            if closure['obligations'] != obligations or closure['unresolved'] != unresolved:
                _fail('adjudication_signed_choice_population_or_disposition_differs')
            if closure['status'] == 'declared_complete' and unresolved:
                _fail('unresolved_adjudication_cannot_substantiate_declared_complete')
        return record, []
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        return None, [str(error)[:512] or 'invalid_adjudication_content']


def _pages(entries, bounds):
    pages, refs, pending, start = [], [], [], 0
    def seal(items):
        return _seal(PAGE_SCHEMA, page_ordinal=len(pages), first_group_ordinal=start, entries=items)
    def finish():
        if len(pages) >= bounds['max_pages']:
            _fail('complete source adjudication page population exceeds bound')
        page = seal(pending)
        base._plain(page, bounds['max_page_bytes'])
        pages.append(page)
        refs.append({**_ref(page), 'page_ordinal': len(pages) - 1, 'first_group_ordinal': start, 'entry_count': len(pending)})
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


def assess_source_adjudications(preparation, source_registry, source_policy, source_review_groups, typed_response_report,
        adjudication_registry, adjudication_policy, adjudication_groups, *, expected_typed_response_manifest_sha256,
        expected_adjudication_registry_sha256, expected_adjudication_policy_sha256, expected_adjudication_group_pins,
        typed_response_limits=None, limits=None, **typed_response_inputs):
    """Regenerate typed sources once, then authenticate a fixed adjudication domain."""
    required = {'response_bindings', 'expected_response_bindings_sha256', 'expected_preparation_manifest_sha256',
        'expected_registry_sha256', 'expected_policy_sha256', 'expected_review_group_pins', 'at_time_utc',
        'alignment_corpus_bytes', 'expected_alignment_corpus_pins', 'alignment_replay_inputs',
        'source_report_bytes', 'expected_source_report_pins'}
    if set(typed_response_inputs) not in (required, required | {'source_review_limits'}):
        _fail('closed complete typed source adjudication replay inputs required')
    bounds = _limits(limits)
    response_bounds = responses._limits(typed_response_limits)
    offered = responses._detach(typed_response_report, response_bounds)
    contracts.require_sha256(expected_typed_response_manifest_sha256, 'independent typed response root FULL SHA256')
    if _digest(offered['manifest']) != expected_typed_response_manifest_sha256:
        _fail('independent complete typed response root differs')
    source_bounds = source._limits(typed_response_inputs.get('source_review_limits'))
    detached = source._detach_preparation(preparation, source_bounds)
    if len(detached['requests']) > bounds['max_groups']:
        _fail('complete source adjudication group population exceeds bound')
    source_pins = json.loads(base._plain(typed_response_inputs['expected_review_group_pins'], contracts.MAX_RECORD_BYTES))
    from . import legal_graph_review as auth
    source_trust = []
    for value, pin_field in ((source_registry, 'expected_registry_sha256'), (source_policy, 'expected_policy_sha256')):
        expected = typed_response_inputs[pin_field]
        contracts.require_sha256(expected, 'independent original source trust SHA256')
        raw = base._plain(value, 8 * 1024**2)
        if _sha(raw) != expected:
            _fail('original source trust differs before adjudication')
        source_trust.append(json.loads(raw))
    source_registry, source_policy = source_trust
    responses._bindings(typed_response_inputs['response_bindings'], typed_response_inputs['expected_response_bindings_sha256'],
        detached, source_review_groups, response_bounds, source_bounds, verify_hashes=False)
    _original_budget(source_review_groups, source_bounds)
    original_groups = source._review_groups(source_review_groups, source_pins, detached['subjects'], auth, source_bounds)
    group_pins = json.loads(base._plain(expected_adjudication_group_pins, contracts.MAX_RECORD_BYTES))
    groups = _groups(adjudication_groups, group_pins, detached, bounds)
    selected = []
    for value, expected in ((adjudication_registry, expected_adjudication_registry_sha256), (adjudication_policy, expected_adjudication_policy_sha256)):
        contracts.require_sha256(expected, 'independently selected adjudication trust SHA256')
        raw = base._plain(value, 8 * 1024**2)
        if _sha(raw) != expected:
            _fail('selected adjudication trust differs')
        selected.append(json.loads(raw))
    adjudication_registry, adjudication_policy = selected
    auth._trust(adjudication_registry, adjudication_policy, expected_adjudication_registry_sha256,
        expected_adjudication_policy_sha256, action=ACTION, audience=AUDIENCE)
    evaluation_time = typed_response_inputs['at_time_utc']
    evaluation = auth._time(evaluation_time)
    producer_pins = _pins()
    checked = responses.validate_source_review_responses(offered, detached, source_registry, source_policy, original_groups,
        **typed_response_inputs, limits=typed_response_limits)
    slots_by_cid = {row['record_cid']: row for row in checked['adjudication_requests']}
    variants_by_cid = {row['record_cid']: row for row in checked['answer_variants']}
    original_principals = {claim['principal_id'] for group in original_groups for claim in group['reviews']}
    original_dids = {claim['signer_did'] for group in original_groups for claim in group['reviews']}
    source_keys = {key['key_id']: key for key in source_registry['keys']}
    authority_keys = {key['key_id']: key for key in adjudication_registry['keys']}
    original_public_keys = {source_keys[claim['key_id']]['public_key_hex'] for group in original_groups
        for claim in group['reviews'] if claim['key_id'] in source_keys}
    domain = auth._ReviewDomain(source.SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE, ASSESSMENT_SCHEMA, source._subject, source.ACTIVE_SLOT_COUNT)
    records, entries, retained = [], [], 0
    eligible, body_count, authenticated_count, selected_slots, unresolved_slots = 0, 0, 0, 0, 0
    for ordinal, (request, subject, dependency_manifest, typed_group, original, group, pin) in enumerate(zip(detached['requests'],
            detached['subjects'], detached['dependency_manifests'], checked['records'], original_groups, groups, group_pins, strict=True)):
        slots = [slots_by_cid[ref['record_cid']] for ref in typed_group['adjudication_refs']]
        variants = [variants_by_cid[ref['record_cid']] for slot in slots for ref in slot['answer_variant_refs']]
        record, content_blockers = _content(group, request, subject, typed_group, slots, variants,
            typed_response_inputs['expected_preparation_manifest_sha256'], expected_typed_response_manifest_sha256, bounds)
        assessment = auth._assess_reviews(subject, adjudication_registry, adjudication_policy, group['reviews'], dependency_manifest,
            domain=domain, expected_subject_sha256=_digest(subject), expected_registry_sha256=expected_adjudication_registry_sha256,
            expected_policy_sha256=expected_adjudication_policy_sha256, expected_reviews_sha256=pin['reviews_sha256'],
            expected_manifest_sha256=dependency_manifest['manifest_sha256'], at_time_utc=evaluation_time,
            observed_artifact_sha256s=group['observed_artifact_sha256s'], observed_pins=group['observed_pins'], evidence_artifacts=group['evidence_artifacts'])
        extra = []
        if any(claim['principal_id'] in original_principals for claim in group['reviews']):
            extra.append('adjudicator_is_a_supplied_original_reviewer')
        if any(claim['signer_did'] in original_dids for claim in group['reviews']):
            extra.append('adjudicator_reuses_an_original_reviewer_did')
        if any(authority_keys.get(claim['key_id'], {}).get('public_key_hex') in original_public_keys for claim in group['reviews']):
            extra.append('adjudicator_reuses_an_original_reviewer_public_key')
        if record is not None:
            declared = auth._time(record['declared_at_utc'])
            if declared > evaluation:
                extra.append('adjudication_declared_after_evaluation')
            if any(declared < auth._time(claim['issued_at_utc']) for claim in original['reviews']):
                extra.append('adjudication_predates_original_review')
            if any(auth._time(claim['issued_at_utc']) < declared for claim in group['reviews']):
                extra.append('authority_claim_predates_common_declaration')
        source_assessment = typed_group['raw_source_assessment_record']['assessment']
        if source_assessment['trust_mode'] != 'external_pinned_trust':
            extra.append('original_source_review_production_trust_unavailable')
        source_rows = [row for row in source_assessment['reviews'] if row['status'] == 'authenticated']
        if not any(a['role'] == 'legal_review' and b['role'] == 'formal_review' and a['principal_id'] != b['principal_id']
                   for a in source_rows for b in source_rows):
            extra.append('original_authenticated_distinct_source_roles_missing')
        prerequisites = (record is not None and not content_blockers and not extra
            and assessment['review_prerequisites_satisfied_under_selected_trust'])
        identity = group['declaration_artifact_id']
        artifact_ref = None if identity is None else {'artifact_id': identity, 'sha256': _sha(group['evidence_artifacts'][identity])}
        result = _seal(GROUP_SCHEMA, queue_ordinal=ordinal, request_cid=request['record_cid'],
            typed_response_group_record=typed_group, declaration_artifact_ref=artifact_ref, declaration_record=record,
            declaration_content_status='absent' if identity is None else 'valid_declared_content' if record is not None else 'rejected',
            content_blockers=content_blockers, authority_assessment=assessment, separation_and_chronology_blockers=extra,
            authority_prerequisites_satisfied_under_selected_trust=prerequisites,
            deferred_review_slot_ids=request['deferred_review_slot_ids'], original_contexts_remain_required_unavailable=True)
        raw = base._plain(result, min(contracts.MAX_RECORD_BYTES, bounds['max_collection_bytes'] - retained))
        retained += len(raw) + 1
        records.append(result)
        entries.append({'ordinal': ordinal, 'request_cid': request['record_cid'], 'group_record_ref': _ref(result)})
        eligible += int(prerequisites)
        body_count += int(identity is not None)
        authenticated_count += assessment['authenticated_evidence_count']
        if record is not None:
            selected_slots += sum(choice['decision'] == 'select_existing_variant' for choice in record['decisions'])
            unresolved_slots += sum(choice['decision'] == 'unresolved' for choice in record['decisions'])
        else:
            unresolved_slots += source.ACTIVE_SLOT_COUNT
    pages, page_refs = _pages(entries, bounds)
    manifest = _seal(MANIFEST_SCHEMA, profile=PROFILE, limits=bounds, typed_response_manifest_ref=_ref(checked['manifest']),
        preparation_manifest_sha256=typed_response_inputs['expected_preparation_manifest_sha256'],
        adjudication_registry_sha256=expected_adjudication_registry_sha256, adjudication_policy_sha256=expected_adjudication_policy_sha256,
        adjudication_group_pins=group_pins, evaluation_time_utc=evaluation_time, producer_pins=producer_pins, page_refs=page_refs,
        counts={'groups': len(records), 'pages': len(pages), 'declaration_bodies': body_count,
            'authenticated_authority_claims': authenticated_count, 'complete_declaration_authority_prerequisites_under_selected_trust': eligible,
            'declared_selected_slots': selected_slots, 'unresolved_or_absent_slots': unresolved_slots,
            'deferred_questions': len(records) * 7, 'adjudications_applied': 0, 'source_decisions_applied': 0}, population_complete=True)
    result = {'manifest': manifest, 'pages': pages, 'records': records}
    if source._aggregate_size(result) > bounds['max_collection_bytes']:
        _fail('complete source adjudication collection exceeds bound')
    if _pins() != producer_pins:
        _fail('adjudication or inherited source producers changed during operation')
    return result


def _detach(report, bounds):
    contracts.require_keys(report, COMPONENTS, 'complete source adjudication assessment')
    result, retained = {}, 0
    for key, schema, fields, cap in (('manifest', MANIFEST_SCHEMA, MANIFEST_FIELDS, 1),
            ('pages', PAGE_SCHEMA, PAGE_FIELDS, bounds['max_pages']), ('records', GROUP_SCHEMA, GROUP_FIELDS, bounds['max_groups'])):
        values = [report[key]] if key == 'manifest' else report[key]
        if type(values) is not list or len(values) > cap:
            _fail('complete bounded source adjudication component list required')
        rows = []
        for value in values:
            maximum = bounds['max_page_bytes'] if key == 'pages' else contracts.MAX_RECORD_BYTES
            raw = base._plain(value, min(maximum, bounds['max_collection_bytes'] - retained))
            retained += len(raw) + 1
            rows.append(contracts.validate_record(json.loads(raw), schema=schema, fields=fields))
        result[key] = rows[0] if key == 'manifest' else rows
    if source._aggregate_size(result) > bounds['max_collection_bytes']:
        _fail('complete offered adjudication collection exceeds bound')
    return result


def validate_source_adjudications(report, *args, **kwargs):
    detached = _detach(report, _limits(kwargs.get('limits')))
    expected = assess_source_adjudications(*args, **kwargs)
    source._equal_components(detached, expected)
    if _pins() != expected['manifest']['producer_pins']:
        _fail('source adjudication producer pins changed during final comparison')
    return detached


__all__ = ['record_source_adjudication_declaration', 'validate_source_adjudication_declaration',
    'assess_source_adjudications', 'validate_source_adjudications']
