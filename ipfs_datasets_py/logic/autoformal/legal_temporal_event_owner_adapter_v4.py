"""Pure boundary-to-owner diagnostic adapter; never a legal formula admission.

The proposer authenticates its source-only surface analysis by regeneration.
This adapter validates query coordinates, bounded model inputs, saved prediction
arithmetic and a supplied policy. A caller must separately pin checkpoint and
policy provenance and, when claimed, execute/replay the unchanged decoder.
No model, formula emitter, family router or prover is imported or called here.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from . import legal_temporal_event_proposer_v4 as proposer
from . import legal_temporal_relative_owner_metrics as metrics

SCHEMA = 'legal-temporal-event-owner-adapter/v4'
MAX_SOURCE_BYTES = 40_000
MAX_SOURCE_TOKENS = 256
MAX_TOKEN_BYTES = 2_048
MAX_BATCH_QUERIES = 64
_EVENT_FAMILIES = {'not_later_than_after', 'after_event', 'until_event',
                   'within_event', 'minimum_after_event'}
_FALSE = {
    'formula_admission': False,
    'source_semantics_verified': False,
    'owner_occurrence_resolved': False,
    'event_occurrences_attested': False,
    'temporal_origin_resolved': False,
    'scope_resolved': False,
    'model_execution_verified': False,
    'model_policy_provenance_authenticated': False,
    'gold_accuracy_available': False,
    'backend_executed': False,
    'pipeline_promotion': False,
    'existing_gates_changed': False,
}
require = metrics.require


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _copy(value):
    return json.loads(_wire(value))


def producer_pins():
    modules = (proposer, metrics, metrics.previous, metrics.previous.previous, metrics.types)
    return {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in modules} | {
                str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            } | proposer.producer_pins()


def _formula_gate(proposal):
    """Profile limits only; do not convert a surface event into a clock origin."""
    family = proposal['family']
    require(family in _EVENT_FAMILIES | {'legacy_lexical'}, 'unknown surface proposal family')
    reasons = ['owner_prediction_is_diagnostic_only', 'explicit_clock_and_scope_not_supplied']
    if family in _EVENT_FAMILIES:
        if family == 'minimum_after_event':
            require(proposal['semantic_flags']['minimum_duration_scope_unresolved'] is True,
                    'minimum duration meaning cannot be silently resolved')
        profile = 'event_relative_temporal_translation_unavailable'
        reasons += ['event_origin_unresolved', profile]
    else:
        literal = proposal['query']['source_text'][proposal['query']['proposed_time_span']['char_start']:
                                                   proposal['query']['proposed_time_span']['char_end']]
        if re.fullmatch(r'before [0-9]{4}-[0-9]{2}-[0-9]{2}', literal):
            profile = 'calendar_literal_requires_caller_interpretation'
        elif literal.startswith('before '):
            profile = 'noncanonical_calendar_literal_requires_explicit_translation'
        elif re.fullmatch(r'within [1-9][0-9]* (?:days|hours) of notice', literal):
            profile = 'notice_relative_duration_requires_explicit_translation'
            reasons.append('event_origin_unresolved')
        else:
            profile = 'legacy_lexical_requires_explicit_translation'
        reasons.append(profile)
    if proposal['status'] != 'surface_candidate':
        reasons.append('temporal_boundary_deferred')
    return {'status': 'deferred', 'formula_admission': False,
            'representation_profile_hint': profile, 'reason_codes': reasons,
            'event_span_is_surface_text_only': True}


def _source_coordinates(query, text, tokens):
    """Validate exact coordinates even when the full source exceeds model bounds."""
    require(type(query) is dict and set(query) == metrics.SOURCE_KEYS, 'closed source-only query required')
    require(query['source_text'] == text and query['source_sha256'] == hashlib.sha256(text.encode()).hexdigest(),
            'complete source identity differs')
    require(type(query['id']) is str and 0 < len(query['id']) <= 256, 'bounded occurrence ID required')
    interval = query['proposed_time_span']
    require(type(interval) is dict and set(interval) == {'char_start', 'char_end'}, 'closed time coordinates required')
    a, b = interval['char_start'], interval['char_end']
    require(type(a) is int and type(b) is int and 0 <= a < b <= len(text), 'exact time bounds required')
    require(a in {t.start() for t in tokens} and b in {t.end() for t in tokens}, 'time occurrence is not token aligned')


def plan_batch(proposal_receipt):
    """Plan complete source-only owner diagnostics, retaining every exclusion.

    The older corpus TIME_RE is intentionally not an admission rule here.
    Missing/ambiguous boundaries are proposer exclusions; a model-sized source
    is additionally required. No substring truncation or event-anchor inference
    is performed.
    """
    require(type(proposal_receipt) is dict and type(proposal_receipt.get('source_text')) is str,
            'complete proposer receipt required')
    text = proposal_receipt['source_text']
    proposer.validate_result(text, proposal_receipt)
    tokens = list(re.finditer(r'\w+|[^\w\s]', text, re.UNICODE))
    source_bytes = len(text.encode())
    budget_reasons = []
    if source_bytes > MAX_SOURCE_BYTES:
        budget_reasons.append('source_byte_budget_exceeded')
    if not tokens or len(tokens) > MAX_SOURCE_TOKENS:
        budget_reasons.append('source_token_budget_exceeded')
    if any(len(t.group().encode()) > MAX_TOKEN_BYTES for t in tokens):
        budget_reasons.append('source_token_byte_budget_exceeded')
    queries, excluded, eligibility = [], [], []
    seen_ids, seen_spans = set(), set()
    for index, proposal in enumerate(proposal_receipt['proposals']):
        query = proposal['query']
        _source_coordinates(query, text, tokens)
        occurrence = (query['proposed_time_span']['char_start'], query['proposed_time_span']['char_end'])
        require(query['id'] not in seen_ids and occurrence not in seen_spans, 'duplicate proposed source occurrence')
        seen_ids.add(query['id']); seen_spans.add(occurrence)
        require(proposal['status'] in ('surface_candidate', 'deferred'), 'closed boundary status required')
        reasons = ([] if proposal['status'] == 'surface_candidate' else ['temporal_boundary_deferred']) + budget_reasons
        entry = {'proposal_index': index, 'query_id': query['id'], 'family': proposal['family'],
                 'boundary_status': proposal['status'], 'model_eligible': not reasons,
                 'exclusion_reasons': reasons, 'boundary_reason_codes': _copy(proposal['reason_codes']),
                 'formula_gate': _formula_gate(proposal)}
        eligibility.append(entry)
        if reasons:
            excluded.append(_copy(entry))
        else:
            metrics.types.validate_source(query)
            queries.append(_copy(query))
    return {'schema': SCHEMA, 'phase': 'plan', 'source_text': text,
            'source_sha256': proposal_receipt['source_sha256'],
            'proposal_receipt_sha256': digest(proposal_receipt),
            'queries': queries, 'excluded': excluded, 'eligibility': eligibility,
            'issues': _copy(proposal_receipt['issues']),
            'budgets': {'source_bytes': source_bytes, 'source_tokens': len(tokens),
                        'maximum_source_bytes': MAX_SOURCE_BYTES, 'maximum_source_tokens': MAX_SOURCE_TOKENS,
                        'maximum_token_bytes': MAX_TOKEN_BYTES, 'maximum_batch_queries': MAX_BATCH_QUERIES,
                        'proposed_queries': len(eligibility), 'eligible_queries': len(queries),
                        'excluded_queries': len(excluded), 'issue_count': len(proposal_receipt['issues']),
                        'required_model_batches': math.ceil(len(queries) / MAX_BATCH_QUERIES),
                        'model_source_budget_met': not budget_reasons, 'source_truncated': False},
            'producer_pins': producer_pins(), 'authority': dict(_FALSE), 'formula_admission': False}


def assess_batch(proposal_receipt, predictions=None, policy=None):
    """Check saved outputs and a caller-bound policy without a neural call.

    An accepted coordinate proposal never authorizes a temporal formula. The
    policy is structurally validated here; its checkpoint/receipt provenance
    must be authenticated by the caller's frozen execution manifest.
    """
    plan = plan_batch(proposal_receipt)
    if policy is not None:
        metrics.validate_policy(policy)
    if predictions is None:
        return {'schema': SCHEMA, 'phase': 'assessment', 'status': 'not_executed', 'plan': plan,
                'policy': _copy(policy), 'predictions_sha256': None, 'rows': [],
                'counts': {'eligible_queries': len(plan['queries']), 'assessed_queries': 0,
                           'fixed_owner_accepted': 0, 'calibrated_owner_accepted': 0, 'formula_admitted': 0},
                'model_forwards_executed_by_adapter': 0, 'producer_pins': producer_pins(),
                'authority': dict(_FALSE), 'formula_admission': False}
    require(type(predictions) is list, 'complete saved prediction list required')
    require(policy is not None, 'explicit frozen caller-bound policy required')
    by_query = {q['id']: q for q in plan['queries']}
    require(all(type(p) is dict and type(p.get('id')) is str for p in predictions), 'closed saved prediction rows required')
    by_prediction = {p['id']: p for p in predictions}
    require(len(predictions) == len(by_prediction) == len(by_query) and set(by_prediction) == set(by_query),
            'complete unique eligible prediction inventory required')
    evidence = {p['query_id']: p for p in plan['eligibility']}
    rows = []
    for query in plan['queries']:
        prediction = by_prediction[query['id']]
        metrics.checked_prediction(query, prediction)
        fixed = prediction['joint_status'] == 'accepted'
        calibrated = metrics.acceptance({**prediction, 'type_confidence': prediction['confidence']}, policy)
        require(not calibrated or fixed, 'calibrated acceptance cannot exceed fixed acceptance')
        reason = (None if calibrated else 'calibration_accept_none' if policy['mode'] == 'accept_none' else
                  prediction['joint_reason'] if not fixed else 'below_calibrated_span_confidence')
        proposal = proposal_receipt['proposals'][evidence[query['id']]['proposal_index']]
        rows.append({'query_id': query['id'], 'source_sha256': query['source_sha256'],
                     'proposed_time_span': _copy(query['proposed_time_span']), 'family': proposal['family'],
                     'cue_span': _copy(proposal['cue_span']), 'event_span': _copy(proposal['event_span']),
                     'boundary_status': proposal['status'], 'boundary_semantic_flags': _copy(proposal['semantic_flags']),
                     'prediction_sha256': digest(prediction), 'predicted_owner_type': prediction['predicted_label'],
                     'raw_owner_anchor_span': _copy(prediction['raw_owner_anchor_span']),
                     'type_confidence': prediction['confidence'], 'span_confidence': prediction['span_confidence'],
                     'fixed_owner_accepted': fixed, 'fixed_owner_reason': prediction['joint_reason'],
                     'calibrated_owner_accepted': calibrated, 'calibrated_owner_reason': reason,
                     'formula_gate': _formula_gate(proposal), 'formula_admission': False,
                     'gold_accuracy_available': False})
    return {'schema': SCHEMA, 'phase': 'assessment', 'status': 'saved_predictions_checked', 'plan': plan,
            'policy': _copy(policy), 'predictions_sha256': digest(predictions), 'rows': rows,
            'counts': {'eligible_queries': len(plan['queries']), 'assessed_queries': len(rows),
                       'fixed_owner_accepted': sum(r['fixed_owner_accepted'] for r in rows),
                       'calibrated_owner_accepted': sum(r['calibrated_owner_accepted'] for r in rows),
                       'formula_admitted': 0},
            'model_forwards_executed_by_adapter': 0, 'producer_pins': producer_pins(),
            'authority': dict(_FALSE), 'formula_admission': False}
