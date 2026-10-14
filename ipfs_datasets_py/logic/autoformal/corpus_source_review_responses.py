"""Typed source responses and pending disputes; no decisions or admission.

The fixed source owner alone replays sources and authenticates signed bytes.
This layer checks the answer bytes those claims reference. It preserves raw
authentication blockers, including differing declaration hashes, and compares
only exact typed answers. It accepts no adjudication or governing-source choice.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

from . import corpus_contracts as contracts
from . import corpus_parent_occurrence_adapter as base
from . import corpus_source_review as source

PROFILE = "typed-source-context-response-and-pending-disagreements/v1"
RESPONSE_SCHEMA = "legal-corpus-typed-source-context-response/v1"
RESULT_SCHEMA = "legal-corpus-typed-source-response-result/v1"
VARIANT_SCHEMA = "legal-corpus-source-answer-variant/v1"
ADJUDICATION_SCHEMA = "legal-corpus-pending-source-answer-adjudication/v1"
GROUP_SCHEMA = "legal-corpus-typed-source-response-group/v1"
MANIFEST_SCHEMA = "legal-corpus-typed-source-response-manifest/v1"
PAGE_SCHEMA = "legal-corpus-typed-source-response-page/v1"
COMPONENTS = ("manifest", "pages", "records", "response_results", "answer_variants", "adjudication_requests")
DEFAULT_LIMITS = {"max_response_bytes": contracts.MAX_RECORD_BYTES, "max_binding_bytes": contracts.MAX_RECORD_BYTES,
    "max_responses": 8192, "max_variants": 32768, "max_adjudication_requests": 32768,
    "max_groups": 8192, "max_groups_per_page": 64, "max_pages": 256,
    "max_page_bytes": contracts.MAX_RECORD_BYTES, "max_collection_bytes": 64 * 1024**2}
FALSE_FLAGS = {**source.FALSE_FLAGS, **dict.fromkeys(("typed_source_decisions_applied", "adjudication_accepted",
    "answer_content_establishes_legal_truth", "reviewer_competence_verified", "accepted_view_eligible"), False)}
COMMON_FIELDS = {"view", *FALSE_FLAGS, *base.UNSELECTED}
INPUT_FIELDS = {"review_id", "principal_id", "role", "issued_at_utc", "process_declaration", "exposure_declaration", "answers"}
RESPONSE_FIELDS = {"profile", "request_ref", "subject_ref", "preparation_manifest_sha256", "dependency_manifest_sha256",
    "queue_ordinal", "source_binding_sha256", "questions_sha256", *INPUT_FIELDS,
    "deferred_review_slot_ids", "status", *COMMON_FIELDS}
FIELDS = {
    "manifest": {"profile", "limits", "source_review_limits", "preparation_manifest_sha256", "raw_source_assessment_ref",
        "response_bindings_sha256", "page_refs", "producer_pins", "counts", "population_complete", *COMMON_FIELDS},
    "pages": {"page_ordinal", "first_group_ordinal", "entries", *COMMON_FIELDS},
    "records": {"queue_ordinal", "request_cid", "raw_source_assessment_record", "response_result_refs", "adjudication_refs",
        "deferred_review_slot_ids", "deferred_questions_remain_pending", *COMMON_FIELDS},
    "response_results": {"queue_ordinal", "request_cid", "review_id", "review_sha256", "response_artifact_ref",
        "response_record_ref", "principal_id", "role", "signature_authentication_status", "content_status",
        "content_blockers", "authenticated_typed_content", "typed_answer_declarations_complete", "exposure_status", *COMMON_FIELDS},
    "answer_variants": {"queue_ordinal", "request_cid", "slot_id", "answer", "answer_sha256", "respondents", *COMMON_FIELDS},
    "adjudication_requests": {"queue_ordinal", "request_cid", "slot_id", "category", "kind", "answer_variant_refs",
        "authenticated_respondents", "issues", "exact_answer_comparison", "adjudicator_declaration", "decision", "rationale",
        "evidence_refs", "status", *COMMON_FIELDS},
}
SCHEMAS = dict(zip(COMPONENTS, (MANIFEST_SCHEMA, PAGE_SCHEMA, GROUP_SCHEMA, RESULT_SCHEMA, VARIANT_SCHEMA, ADJUDICATION_SCHEMA), strict=True))
DISPOSITIONS = {"unresolved": "open", "evidence_declared": "resolved_by_evidence", "not_applicable": "not_applicable"}
FINDING_DISPOSITIONS = {"unavailable": "unresolved", "ambiguous": "unresolved",
    "evidence_declared": "evidence_declared", "not_applicable": "not_applicable"}


def _fail(message):
    raise contracts.CorpusContractError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _sha(base._plain(value, contracts.MAX_RECORD_BYTES))


def _ref(value):
    return {"record_cid": value['record_cid'], "sha256": _digest(value), "schema": value['schema']}


def _seal(schema, **values):
    payload = {"schema": schema, **values, "view": "candidate", **FALSE_FLAGS, **base.UNSELECTED}
    base._plain(payload, contracts.MAX_RECORD_BYTES)
    return contracts.seal_record(payload)


def _limits(value):
    if value is not None and type(value) is not dict:
        _fail("closed lower-only typed response limits required")
    bounds = dict(DEFAULT_LIMITS)
    for key, limit in (value or {}).items():
        if key not in bounds or type(limit) is not int or not 0 < limit <= bounds[key]:
            _fail("unknown or raised typed response limit")
        bounds[key] = limit
    return bounds


def _pins():
    pins = source._pins(source._owners())
    pins[str(Path(__file__).resolve())] = _sha(Path(__file__).read_bytes())
    return pins


def _refs(values):
    if type(values) is not list or len(values) > 8:
        _fail("bounded ordered response evidence references required")
    seen = set()
    for value in values:
        contracts.require_keys(value, {"artifact_id", "sha256"}, "typed response evidence reference")
        contracts.require_text(value['artifact_id'], "evidence artifact ID", max_bytes=256)
        # Match the unchanged signed-evidence owner's identity grammar.
        from . import legal_graph_review
        legal_graph_review._id(value['artifact_id'], "typed response evidence ID")
        contracts.require_sha256(value['sha256'], "evidence raw SHA256")
        if value['artifact_id'] in seen:
            _fail("duplicate typed response evidence identity")
        seen.add(value['artifact_id'])
    return values


def _inputs(request, subject, response, expected_request_sha256, expected_subject_sha256,
            expected_preparation_manifest_sha256, bounds):
    contracts.require_sha256(expected_request_sha256, "independent request FULL SHA256")
    contracts.require_sha256(expected_subject_sha256, "independent subject FULL SHA256")
    contracts.require_sha256(expected_preparation_manifest_sha256, "independent preparation FULL SHA256")
    request = contracts.validate_record(json.loads(base._plain(request, contracts.MAX_RECORD_BYTES)),
        schema=source.REQUEST_SCHEMA, fields=source.REQUEST_FIELDS)
    subject = contracts.validate_record(json.loads(base._plain(subject, contracts.MAX_RECORD_BYTES)),
        schema=source.SUBJECT_SCHEMA, fields=source.SUBJECT_FIELDS)
    if _digest(request) != expected_request_sha256 or _digest(subject) != expected_subject_sha256:
        _fail("independently pinned typed response source differs")
    if (subject['review_request_cid'] != request['record_cid'] or subject['graph_id'] != request['record_cid']
            or subject['graph_sha256'] != expected_request_sha256 or subject['ast_sha256'] != request['questions_sha256']
            or subject['source_binding_sha256'] != request['source_binding_sha256']
            or subject['context_slot_ids'] != request['context_slot_ids']
            or subject['deferred_review_slot_ids'] != request['deferred_review_slot_ids']):
        _fail("exact typed source request and subject binding differs")
    questions = source._questions(request['review_unit_id'])
    active = [row for row in questions if row['assessment_scope'] == 'source_context_evidence_declaration']
    if (request['review_questions'] != questions or _digest(questions) != request['questions_sha256']
            or request['context_slot_ids'] != [row['slot_id'] for row in active]):
        _fail("exact original sixteen questions and nine active slots required")
    response = json.loads(base._plain(response, bounds['max_response_bytes']))
    contracts.require_keys(response, INPUT_FIELDS, "typed source response input")
    from . import legal_graph_review as auth
    for field in ('review_id', 'principal_id'):
        auth._id(response[field], "response " + field)
    if response['role'] not in auth.ROLES:
        _fail("explicit legal or formal response role required")
    auth._time(response['issued_at_utc'])
    process = response['process_declaration']
    contracts.require_keys(process, {'identity_evidence_refs', 'independence_evidence_refs', 'process_evidence_refs'}, "reviewer process declaration")
    for values in process.values():
        _refs(values)
    exposure = response['exposure_declaration']
    contracts.require_keys(exposure, {'candidate_interpretations_exposed', 'organizer_source_metadata_exposed', 'other_exposure'}, "actual exposure declaration")
    for field in ('candidate_interpretations_exposed', 'organizer_source_metadata_exposed'):
        if exposure[field] is not None and type(exposure[field]) is not bool:
            _fail("explicit boolean or unknown exposure required")
    if exposure['other_exposure'] is not None:
        contracts.require_text(exposure['other_exposure'], "other exposure", max_bytes=8192)
    answers = response['answers']
    if type(answers) is not list or len(answers) != source.ACTIVE_SLOT_COUNT:
        _fail("complete ordered nine typed source answers required")
    for answer, question in zip(answers, active, strict=True):
        contracts.require_keys(answer, {'slot_id', 'category', 'kind', 'disposition', 'finding', 'rationale', 'evidence_refs'}, "typed source answer")
        if any(answer[field] != question[field] for field in ('slot_id', 'category', 'kind')):
            _fail("typed answer differs from exact ordered original question")
        finding = answer['finding']
        contracts.require_keys(finding, {'status', 'statement'}, "typed answer finding")
        if (type(finding['status']) is not str or type(answer['disposition']) is not str
                or finding['status'] not in FINDING_DISPOSITIONS or answer['disposition'] not in DISPOSITIONS
                or FINDING_DISPOSITIONS[finding['status']] != answer['disposition']):
            _fail("unknown or ambiguous finding cannot be a resolved typed answer")
        contracts.require_text(finding['statement'], "source finding statement", max_bytes=8192)
        contracts.require_text(answer['rationale'], "source answer rationale", max_bytes=8192)
        _refs(answer['evidence_refs'])
        if answer['disposition'] != 'unresolved' and not answer['evidence_refs']:
            _fail("resolved or not-applicable declaration needs exact evidence")
    return request, subject, response


def record_source_review_response(request, subject, response, *, expected_request_sha256,
        expected_subject_sha256, expected_preparation_manifest_sha256, limits=None):
    """Record explicit caller declarations; this authoring step authenticates none."""
    bounds = _limits(limits)
    request, subject, response = _inputs(request, subject, response, expected_request_sha256,
        expected_subject_sha256, expected_preparation_manifest_sha256, bounds)
    result = _seal(RESPONSE_SCHEMA, profile=PROFILE, request_ref=_ref(request), subject_ref=_ref(subject),
        preparation_manifest_sha256=expected_preparation_manifest_sha256,
        dependency_manifest_sha256=subject['dependency_manifest_sha256'], queue_ordinal=request['queue_ordinal'],
        source_binding_sha256=request['source_binding_sha256'], questions_sha256=request['questions_sha256'],
        **response, deferred_review_slot_ids=request['deferred_review_slot_ids'], status='declared_unauthenticated_source_response')
    base._plain(result, bounds['max_response_bytes'])
    return result


def validate_source_review_response(record, request, subject, response, **pins):
    bounds = _limits(pins.get('limits'))
    checked = contracts.validate_record(json.loads(base._plain(record, bounds['max_response_bytes'])),
        schema=RESPONSE_SCHEMA, fields=RESPONSE_FIELDS)
    expected = record_source_review_response(request, subject, response, **pins)
    if canonical_dag_json_bytes(checked) != canonical_dag_json_bytes(expected):
        _fail("typed source response differs from exact declared inputs")
    return checked


def _bindings(values, expected, preparation, groups, bounds, source_bounds, *, verify_hashes):
    contracts.require_sha256(expected, "independent complete response binding SHA256")
    raw = base._plain(values, bounds['max_binding_bytes'])
    if _sha(raw) != expected:
        _fail("complete response binding population differs")
    values = json.loads(raw)
    if type(values) is not list or len(values) != len(preparation['requests']):
        _fail("one complete ordered response binding group per original request required")
    if type(groups) is not list or len(groups) != len(values):
        _fail("complete ordered signed response groups required")
    total, evidence_bytes, pending_hashes = 0, 0, []
    for binding, request, group in zip(values, preparation['requests'], groups, strict=True):
        contracts.require_keys(group, {'request_cid', 'reviews', 'evidence_artifacts', 'observed_artifact_sha256s', 'observed_pins'}, "complete signed response group")
        if (type(group['reviews']) is not list or len(group['reviews']) > 32
                or type(group['evidence_artifacts']) is not dict or len(group['evidence_artifacts']) > 256
                or group['request_cid'] != request['record_cid']):
            _fail("bounded exact signed response group required")
        group_bytes = 0
        for name, body in group['evidence_artifacts'].items():
            contracts.require_text(name, "source evidence ID", max_bytes=256)
            if type(body) is not bytes:
                _fail("complete immutable response group evidence bodies required")
            group_bytes += len(body)
            if group_bytes > 8 * 1024**2:
                _fail("complete source evidence group exceeds bound before hashing")
        evidence_bytes += group_bytes
        if evidence_bytes > source_bounds['max_batch_review_bytes']:
            _fail("complete source evidence batch exceeds bound before hashing")
        contracts.require_keys(binding, {'request_cid', 'responses'}, "typed response binding group")
        entries = binding['responses']
        if binding['request_cid'] != request['record_cid'] or type(entries) is not list or len(entries) != len(group['reviews']):
            _fail("complete exact signed-review response bindings required")
        total += len(entries)
        if total > bounds['max_responses']:
            _fail("complete typed response population exceeds bound")
        artifacts = set()
        for entry, review in zip(entries, group['reviews'], strict=True):
            contracts.require_keys(entry, {'review_id', 'artifact_id', 'raw_sha256'}, "signed response artifact binding")
            contracts.require_text(entry['artifact_id'], "response artifact ID", max_bytes=256)
            contracts.require_sha256(entry['raw_sha256'], "response raw SHA256")
            raw = group['evidence_artifacts'].get(entry['artifact_id'])
            if (type(review) is not dict or entry['review_id'] != review.get('review_id') or entry['artifact_id'] in artifacts
                    or type(raw) is not bytes or len(raw) > bounds['max_response_bytes']):
                _fail("exact distinct bounded response artifact required before hashing")
            pending_hashes.append((raw, entry['raw_sha256']))
            artifacts.add(entry['artifact_id'])
    # All cardinality and raw-body budgets pass before the first body hash.
    if verify_hashes:
        for raw, expected_sha in pending_hashes:
            if _sha(raw) != expected_sha:
                _fail("exact distinct independently pinned response artifact required")
    return values


def _content(entry, raw, review, request, subject, preparation_sha, evidence, bounds):
    try:
        record = contracts.validate_record(base._load(raw, bounds['max_response_bytes']), schema=RESPONSE_SCHEMA, fields=RESPONSE_FIELDS)
        response = {key: record[key] for key in INPUT_FIELDS}
        expected = record_source_review_response(request, subject, response,
            expected_request_sha256=_digest(request), expected_subject_sha256=_digest(subject),
            expected_preparation_manifest_sha256=preparation_sha, limits=bounds)
        if canonical_dag_json_bytes(record) != canonical_dag_json_bytes(expected):
            _fail("typed_response_exact_source_binding_differs")
        if any(record[key] != review[key] for key in ('review_id', 'principal_id', 'role', 'issued_at_utc')):
            _fail("typed_response_signed_reviewer_binding_differs")
        obligations = review['context_closure']['obligations']
        if len(obligations) != source.ACTIVE_SLOT_COUNT:
            _fail("typed_response_signed_obligation_population_differs")
        body_ref = {'artifact_id': entry['artifact_id'], 'sha256': entry['raw_sha256']}
        for answer, obligation in zip(record['answers'], obligations, strict=True):
            if (obligation['slot_id'] != answer['slot_id'] or obligation['evidence_refs'] != [body_ref]
                    or obligation['disposition'] != DISPOSITIONS[answer['disposition']]):
                _fail("typed_answer_signed_disposition_or_body_binding_differs")
        complete = all(answer['disposition'] != 'unresolved' for answer in record['answers'])
        unresolved_slots = [answer['slot_id'] for answer in record['answers'] if answer['disposition'] == 'unresolved']
        if review['context_closure']['unresolved'] != unresolved_slots:
            _fail("typed_unresolved_slot_population_differs_from_signed_declaration")
        if review['context_closure']['status'] == 'declared_complete' and (not complete or review['context_closure']['unresolved']):
            _fail("typed_unresolved_answer_cannot_substantiate_declared_complete")
        refs = [ref for answer in record['answers'] for ref in answer['evidence_refs']]
        refs.extend(ref for values in record['process_declaration'].values() for ref in values)
        for ref in refs:
            body = evidence.get(ref['artifact_id'])
            if ref['artifact_id'] == entry['artifact_id'] or body is None or _sha(body) != ref['sha256']:
                _fail("typed_answer_or_process_evidence_missing_changed_or_self_referential")
        return record, complete, []
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        # Retain rejected response identity/raw hash and the original signed row.
        return None, False, [str(error)[:512] or 'typed_response_content_invalid']


def _pages(entries, bounds):
    pages, refs, pending, start = [], [], [], 0
    def seal(values):
        return _seal(PAGE_SCHEMA, page_ordinal=len(pages), first_group_ordinal=start, entries=values)
    def finish():
        if len(pages) >= bounds['max_pages']:
            _fail("complete typed assessment page population exceeds bound")
        page = seal(pending)
        base._plain(page, bounds['max_page_bytes'])
        pages.append(page)
        refs.append({**_ref(page), 'page_ordinal': len(pages) - 1, 'first_group_ordinal': start, 'entry_count': len(pending)})
    size, retained = len(canonical_dag_json_bytes(seal([]))), 0
    for entry in entries:
        next_size = len(canonical_dag_json_bytes(entry))
        if pending and (len(pending) >= bounds['max_groups_per_page']
                or size + retained + next_size + len(pending) + 32 > bounds['max_page_bytes']):
            finish()
            start, pending, retained = entry['ordinal'], [], 0
            size = len(canonical_dag_json_bytes(seal([])))
        pending.append(entry)
        retained += next_size
    if pending:
        finish()
    return pages, refs


def assess_source_review_responses(preparation, registry, policy, review_groups, *, response_bindings,
        expected_response_bindings_sha256, source_review_limits=None, limits=None, **source_inputs):
    """Replay/authenticate once with the unchanged source owner; inspect all answers."""
    required = {'expected_preparation_manifest_sha256', 'expected_registry_sha256', 'expected_policy_sha256',
        'expected_review_group_pins', 'at_time_utc', 'alignment_corpus_bytes', 'expected_alignment_corpus_pins',
        'alignment_replay_inputs', 'source_report_bytes', 'expected_source_report_pins'}
    contracts.require_keys(source_inputs, required, "fixed complete source assessment inputs")
    bounds, source_bounds = _limits(limits), source._limits(source_review_limits)
    detached = source._detach_preparation(preparation, source_bounds)
    if len(detached['requests']) > bounds['max_groups']:
        _fail("complete typed source request population exceeds bound")
    if len(detached['requests']) * source.ACTIVE_SLOT_COUNT > bounds['max_adjudication_requests']:
        _fail("complete pending adjudication population exceeds bound before source replay")
    preparation_sha = source_inputs['expected_preparation_manifest_sha256']
    contracts.require_sha256(preparation_sha, "independent complete source preparation SHA256")
    if _digest(detached['manifest']) != preparation_sha:
        _fail("independent typed source preparation root differs")
    pin_raw = base._plain(source_inputs['expected_review_group_pins'], contracts.MAX_RECORD_BYTES)
    group_pins = json.loads(pin_raw)
    bindings = _bindings(response_bindings, expected_response_bindings_sha256, detached, review_groups,
        bounds, source_bounds, verify_hashes=False)
    owners = source._owners()
    groups = source._review_groups(review_groups, group_pins, detached['subjects'], owners[3], source_bounds)
    # The detached group must still equal both independent binding populations.
    _bindings(bindings, expected_response_bindings_sha256, detached, groups,
        bounds, source_bounds, verify_hashes=True)
    producer_pins = _pins()
    raw_assessment = source.assess_source_review_groups(detached, registry, policy, groups,
        **source_inputs, limits=source_review_limits)
    result = {key: None if key == 'manifest' else [] for key in COMPONENTS}
    retained, inventory, counters = 0, [], Counter()
    caps = {'records': bounds['max_groups'], 'response_results': bounds['max_responses'],
        'answer_variants': bounds['max_variants'], 'adjudication_requests': bounds['max_adjudication_requests']}
    def retain(group, record):
        nonlocal retained
        if len(result[group]) >= caps[group]:
            _fail("complete typed assessment component population exceeds bound")
        raw = base._plain(record, min(contracts.MAX_RECORD_BYTES, bounds['max_collection_bytes'] - retained))
        retained += len(raw) + 1
        result[group].append(record)
    for ordinal, (request, subject, group, binding, raw_group) in enumerate(zip(detached['requests'], detached['subjects'],
            groups, bindings, raw_assessment['records'], strict=True)):
        responses, admitted_answers = [], []
        for review, entry, raw_row in zip(group['reviews'], binding['responses'], raw_group['assessment']['reviews'], strict=True):
            record, complete, blockers = _content(entry, group['evidence_artifacts'][entry['artifact_id']], review,
                request, subject, preparation_sha, group['evidence_artifacts'], bounds)
            authenticated = raw_row['status'] == 'authenticated' and not blockers
            exposure = 'unknown' if record is None or any(value is None for value in record['exposure_declaration'].values()) else 'declared'
            row = _seal(RESULT_SCHEMA, queue_ordinal=ordinal, request_cid=request['record_cid'], review_id=review['review_id'],
                review_sha256=raw_row['review_sha256'], response_artifact_ref={'artifact_id': entry['artifact_id'], 'sha256': entry['raw_sha256']},
                response_record_ref=None if record is None else _ref(record), principal_id=review['principal_id'], role=review['role'],
                signature_authentication_status=raw_row['status'], content_status='valid_declared_content' if not blockers else 'rejected',
                content_blockers=blockers, authenticated_typed_content=authenticated,
                typed_answer_declarations_complete=complete, exposure_status=exposure)
            retain('response_results', row)
            responses.append(_ref(row))
            counters['responses'] += 1
            counters['authenticated_typed_responses'] += int(authenticated)
            counters['rejected_content_responses'] += int(bool(blockers))
            counters['incomplete_typed_responses'] += int(not complete)
            if authenticated:
                admitted_answers.append((record, row))
        adjudications = []
        active = [q for q in request['review_questions'] if q['assessment_scope'] == 'source_context_evidence_declaration']
        for position, question in enumerate(active):
            buckets = {}
            for response, row in admitted_answers:
                answer = response['answers'][position]
                digest = _digest(answer)
                respondent = {'response_result_ref': _ref(row), 'response_record_ref': _ref(response),
                    'review_id': row['review_id'], 'principal_id': row['principal_id'], 'role': row['role']}
                if digest not in buckets:
                    buckets[digest] = {'answer': answer, 'respondents': []}
                buckets[digest]['respondents'].append(respondent)
            variants, respondents = [], []
            for digest, bucket in buckets.items():
                variant = _seal(VARIANT_SCHEMA, queue_ordinal=ordinal, request_cid=request['record_cid'],
                    slot_id=question['slot_id'], answer=bucket['answer'], answer_sha256=digest, respondents=bucket['respondents'])
                retain('answer_variants', variant)
                variants.append(_ref(variant))
                respondents.extend(bucket['respondents'])
            issues = []
            if not respondents:
                issues.append('no_authenticated_typed_answer')
            if any(bucket['answer']['disposition'] == 'unresolved' for bucket in buckets.values()):
                issues.append('unresolved_typed_answer')
            if len(buckets) > 1:
                issues.append('distinct_exact_answer_variants')
            legal = [row for row in respondents if row['role'] == 'legal_review']
            formal = [row for row in respondents if row['role'] == 'formal_review']
            if not any(a['principal_id'] != b['principal_id'] for a in legal for b in formal):
                issues.append('distinct_legal_and_formal_declared_principals_missing')
            # Even byte-identical answers are declarations, never an adjudication.
            issues.append('separate_adjudication_and_decision_authority_required')
            comparison = 'no_authenticated_answers' if not buckets else 'one_exact_answer_variant' if len(buckets) == 1 else 'different_exact_answer_variants'
            adjudication = _seal(ADJUDICATION_SCHEMA, queue_ordinal=ordinal, request_cid=request['record_cid'],
                **{key: question[key] for key in ('slot_id', 'category', 'kind')}, answer_variant_refs=variants,
                authenticated_respondents=respondents, issues=issues, exact_answer_comparison=comparison,
                adjudicator_declaration={'principal_id': None, 'role': None, 'issued_at_utc': None},
                decision=None, rationale=None, evidence_refs=[], status='pending_adjudication_not_a_decision')
            retain('adjudication_requests', adjudication)
            adjudications.append(_ref(adjudication))
            counters['different_answer_slots'] += int(len(buckets) > 1)
            counters['unresolved_answer_slots'] += int('unresolved_typed_answer' in issues)
            counters['missing_authenticated_answer_slots'] += int(not respondents)
        record = _seal(GROUP_SCHEMA, queue_ordinal=ordinal, request_cid=request['record_cid'],
            raw_source_assessment_record=raw_group, response_result_refs=responses, adjudication_refs=adjudications,
            deferred_review_slot_ids=request['deferred_review_slot_ids'], deferred_questions_remain_pending=True)
        retain('records', record)
        inventory.append({'ordinal': ordinal, 'request_cid': request['record_cid'], 'group_record_ref': _ref(record)})
    result['pages'], page_refs = _pages(inventory, bounds)
    result['manifest'] = _seal(MANIFEST_SCHEMA, profile=PROFILE, limits=bounds, source_review_limits=source_bounds,
        preparation_manifest_sha256=preparation_sha, raw_source_assessment_ref=_ref(raw_assessment['manifest']),
        response_bindings_sha256=expected_response_bindings_sha256, page_refs=page_refs, producer_pins=producer_pins,
        counts={'groups': len(result['records']), 'pages': len(result['pages']), **{key: counters[key] for key in
            ('responses', 'authenticated_typed_responses', 'rejected_content_responses', 'incomplete_typed_responses',
             'different_answer_slots', 'unresolved_answer_slots', 'missing_authenticated_answer_slots')},
            'answer_variants': len(result['answer_variants']), 'pending_adjudication_slots': len(result['adjudication_requests']),
            'deferred_questions': len(result['records']) * 7, 'accepted_adjudications': 0, 'applied_source_decisions': 0},
        population_complete=True)
    if source._aggregate_size(result) > bounds['max_collection_bytes']:
        _fail("complete typed source response assessment exceeds collection byte bound")
    if _pins() != producer_pins:
        _fail("typed or inherited source review producers changed during assessment")
    return result


def _detach(report, bounds):
    contracts.require_keys(report, COMPONENTS, "complete typed source response assessment")
    caps = {'manifest': 1, 'pages': bounds['max_pages'], 'records': bounds['max_groups'],
        'response_results': bounds['max_responses'], 'answer_variants': bounds['max_variants'],
        'adjudication_requests': bounds['max_adjudication_requests']}
    result, retained = {}, 0
    for component in COMPONENTS:
        values = [report[component]] if component == 'manifest' else report[component]
        if type(values) is not list or len(values) > caps[component]:
            _fail("complete bounded typed assessment component list required")
        rows = []
        for value in values:
            maximum = bounds['max_page_bytes'] if component == 'pages' else contracts.MAX_RECORD_BYTES
            raw = base._plain(value, min(maximum, bounds['max_collection_bytes'] - retained))
            retained += len(raw) + 1
            rows.append(contracts.validate_record(json.loads(raw), schema=SCHEMAS[component], fields=FIELDS[component]))
        result[component] = rows[0] if component == 'manifest' else rows
    if source._aggregate_size(result) > bounds['max_collection_bytes']:
        _fail("complete typed response assessment byte bound exceeded")
    return result


def validate_source_review_responses(report, *args, **kwargs):
    """Bound offered output first, then repeat complete source and response assessment."""
    detached = _detach(report, _limits(kwargs.get('limits')))
    expected = assess_source_review_responses(*args, **kwargs)
    source._equal_components(detached, expected)
    if _pins() != expected['manifest']['producer_pins']:
        _fail("typed response producer pins changed during final comparison")
    return detached


__all__ = ['record_source_review_response', 'validate_source_review_response',
           'assess_source_review_responses', 'validate_source_review_responses']
