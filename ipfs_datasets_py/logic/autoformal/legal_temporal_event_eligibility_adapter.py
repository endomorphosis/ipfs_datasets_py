"""Guarded source-envelope eligibility diagnostics; never legal admission.

The raw v4 receipt remains immutable and is authenticated by frozen source pins
and regeneration. Classifier scores can override only the sole event-shape
reason. Caller manifests authenticate actual checkpoint and policy provenance;
this pure adapter validates their exact wire binding but executes no model.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

from . import legal_temporal_event_proposer_v4 as proposer

SCHEMA = 'legal-temporal-event-eligibility-adapter/v1'
POLICY_SCHEMA = 'legal-temporal-event-eligibility-policy/v1'
PREDICTION_SCHEMA = 'legal-temporal-event-eligibility-prediction/v1'
CLASS_ORDER = ['defer_surface', 'eligible_surface']
THRESHOLDS = (0.8, 0.85, 0.9, 0.95, 0.975, 0.99)
SELECTION_RULE = 'zero-error-support-floor/v1'
MAX_TOKEN_BYTES = 2048
NESTED_GUARD = 'ambiguous_nested_conflict_component'
FROZEN_PROPOSER_SHA256 = '4f2a6b9640a8b244ff5da67e38ba4424e21acbd33c93e06ba50fab4502440866'
FROZEN_LEGACY_SHA256 = '248bad63a3bdc8d09c875bcc725e703e30fdb558db3c2d767e147eac42b50d40'
AUTHORITY = dict.fromkeys(('formula_admission', 'legal_semantics_verified', 'owner_assigned',
    'event_origin_resolved', 'scope_resolved', 'pipeline_promotion',
    'model_execution_verified', 'model_policy_provenance_authenticated'), False)
PREDICTION_AUTHORITY = dict.fromkeys(('legal_semantics_verified', 'owner_assigned',
    'formal_formula_admitted', 'latent_input_enabled', 'pipeline_promotion'), False)
SELF_INITIAL = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(wire(value).encode()).hexdigest()


def copy(value):
    return json.loads(wire(value))


def _sha(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def producer_pins():
    pins = proposer.producer_pins()
    require(pins == {str(Path(proposer.__file__).resolve()): FROZEN_PROPOSER_SHA256,
                     str(Path(proposer.legacy.__file__).resolve()): FROZEN_LEGACY_SHA256},
            'frozen v4 producer closure changed')
    current = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    require(current == SELF_INITIAL, 'eligibility adapter producer changed')
    return pins | {str(Path(__file__).resolve()): current}


def _xy(query):
    s = query['proposed_time_span']
    return s['char_start'], s['char_end']


def _conflicts(proposals, source_sha256):
    """Only explicit nested ambiguity seeds create source conflict edges.

    Each seed connects every overlapping proposal. Connected components retain
    exact member spans; a distinct punctuation-cut occurrence does not overlap.
    """
    seeds = [i for i, p in enumerate(proposals)
             if 'ambiguous_nested_temporal_boundary' in p['reason_codes']]
    neighbors = {i: set() for i in seeds}
    for i in seeds:
        a, b = _xy(proposals[i]['query'])
        for j, p in enumerate(proposals):
            c, d = _xy(p['query'])
            if max(a, c) < min(b, d):
                neighbors.setdefault(i, set()).add(j)
                neighbors.setdefault(j, set()).add(i)
    components, seen = [], set()
    for start in sorted(neighbors):
        if start in seen:
            continue
        pending, members = [start], set()
        while pending:
            i = pending.pop()
            if i in members:
                continue
            members.add(i); pending.extend(neighbors[i] - members)
        seen |= members
        indices = sorted(members)
        ids = [proposals[i]['query']['id'] for i in indices]
        components.append({'id': 'conflict-'+digest([source_sha256, ids]),
            'query_ids': ids, 'root_query_ids': [proposals[i]['query']['id'] for i in indices if i in seeds],
            'envelope_spans': [copy(proposals[i]['query']['proposed_time_span']) for i in indices if i in seeds]})
    return components


def plan(source_text, raw_v4_receipt):
    """Return all raw proposals plus immutable source conflict guards."""
    pins = producer_pins()
    proposer.validate_result(source_text, raw_v4_receipt)
    tokens = list(proposer.TOKEN_RE.finditer(source_text))
    _, _, delimiter_errors = proposer._lex(source_text)
    source_blocks = list(delimiter_errors)
    if len(tokens) > proposer.MAX_SOURCE_TOKENS:
        source_blocks.append('source_token_budget_exceeded')
    if any(len(t.group().encode()) > MAX_TOKEN_BYTES for t in tokens):
        source_blocks.append('source_token_byte_budget_exceeded')
    source_blocks = sorted(set(source_blocks))
    components = _conflicts(raw_v4_receipt['proposals'], raw_v4_receipt['source_sha256'])
    conflicted = {qid for c in components for qid in c['query_ids']}
    inventory = []
    for p in raw_v4_receipt['proposals']:
        hard = source_blocks + [r for r in p['reason_codes'] if r != 'unsupported_event_shape']
        if p['query']['id'] in conflicted:
            hard.append(NESTED_GUARD)
        hard = sorted(set(hard))
        baseline = p['status'] == 'surface_candidate' and not hard
        override = p['status'] == 'deferred' and p['reason_codes'] == ['unsupported_event_shape'] and not hard
        inventory.append({**copy(p), 'baseline_eligible': baseline,
                          'overridable': override, 'hard_block_reasons': hard})
    return {'schema': SCHEMA, 'phase': 'plan', 'source_text': source_text,
            'source_sha256': raw_v4_receipt['source_sha256'],
            'raw_receipt_sha256': digest(raw_v4_receipt), 'inventory': inventory,
            'conflict_components': components, 'source_hard_block_reasons': source_blocks,
            'issues': copy(raw_v4_receipt['issues']), 'producer_pins': pins,
            'authority': dict(AUTHORITY), 'formula_admission': False}


def validate_policy(policy):
    require(type(policy) is dict and set(policy) == {'schema','checkpoint_sha256','mode','threshold',
        'calibration_sha256','selection_rule'}, 'closed boundary eligibility policy required')
    require(policy['schema'] == POLICY_SCHEMA and policy['selection_rule'] == SELECTION_RULE,
            'boundary policy schema/rule differs')
    require(_sha(policy['checkpoint_sha256']) and _sha(policy['calibration_sha256']), 'policy SHA binding required')
    require((policy['mode'] == 'accept_none' and policy['threshold'] is None) or
            (policy['mode'] == 'threshold' and type(policy['threshold']) in (int,float)
             and policy['threshold'] in THRESHOLDS), 'declared boundary threshold or accept_none required')
    return policy


def checked_prediction(query, prediction, checkpoint_sha256):
    keys = {'schema','query','checkpoint_sha256','class_order','logits','probabilities',
            'predicted_label','confidence','authority','formula_admission'}
    require(type(prediction) is dict and set(prediction) == keys, 'closed eligibility prediction required')
    require(prediction['schema'] == PREDICTION_SCHEMA and _sha(checkpoint_sha256) and
            prediction['checkpoint_sha256'] == checkpoint_sha256, 'prediction checkpoint binding differs')
    require(wire(prediction['query']) == wire(query), 'prediction exact query join differs')
    require(prediction['class_order'] == CLASS_ORDER, 'binary class ordering differs')
    logits, probabilities = prediction['logits'], prediction['probabilities']
    for values in (logits, probabilities):
        require(type(values) is list and len(values) == 2 and
                all(type(x) in (float,int) and math.isfinite(x) for x in values), 'two finite numeric scores required')
    require(all(0 <= x <= 1 for x in probabilities) and abs(sum(probabilities)-1) <= 1e-6,
            'normalized class probabilities required')
    maximum = max(logits); exponentials = [math.exp(x-maximum) for x in logits]
    expected = [x/sum(exponentials) for x in exponentials]
    require(all(abs(a-b) <= 1e-6 for a,b in zip(expected,probabilities)), 'probabilities differ from logits')
    index = 0 if logits[0] >= logits[1] else 1
    require(prediction['predicted_label'] == CLASS_ORDER[index], 'predicted class differs from first-tie argmax')
    require(type(prediction['confidence']) in (int,float) and math.isfinite(prediction['confidence']) and
            abs(prediction['confidence']-probabilities[index]) <= 1e-6, 'prediction confidence differs')
    require(prediction['authority'] == PREDICTION_AUTHORITY and
            all(x is False for x in prediction['authority'].values()) and prediction['formula_admission'] is False,
            'eligibility prediction authority escalation')
    return prediction


def assess(source_text, raw_v4_receipt, predictions=None, policy=None):
    """Apply a caller-frozen boundary policy; retain raw scores before masking.

    Supplying neither predictions nor policy executes the conflict-guard-only
    arm. With predictions, every raw candidate must have one exact bound row.
    Accept-none suppresses learned overrides only, not guarded baseline queries.
    """
    planned = plan(source_text, raw_v4_receipt)
    require((predictions is None) == (policy is None), 'predictions and policy must be supplied together')
    mapping = {}
    if predictions is not None:
        validate_policy(policy)
        require(type(predictions) is list and all(type(p) is dict and type(p.get('query')) is dict and
            type(p['query'].get('id')) is str for p in predictions), 'complete prediction list required')
        mapping = {p['query']['id']:p for p in predictions}
        expected = {p['query']['id']:p['query'] for p in planned['inventory']}
        require(len(predictions) == len(mapping) == len(expected) and set(mapping) == set(expected),
                'complete unique raw-candidate prediction inventory required')
        for qid, q in expected.items():
            checked_prediction(q, mapping[qid], policy['checkpoint_sha256'])
    rows, queries = [], []
    for item in planned['inventory']:
        prediction = mapping.get(item['query']['id'])
        probability = None if prediction is None else prediction['probabilities'][1]
        override = bool(item['overridable'] and prediction is not None and policy['mode'] == 'threshold'
                        and probability >= policy['threshold'])
        eligible = item['baseline_eligible'] or override
        reason = ('hard_source_guard' if item['hard_block_reasons'] else
                  'guarded_v4_baseline' if item['baseline_eligible'] else
                  'learned_event_shape_override' if override else
                  'no_learned_override' if prediction is None else
                  'policy_accept_none' if policy['mode'] == 'accept_none' else
                  'below_boundary_threshold' if item['overridable'] else 'nonoverridable_raw_reason')
        row = {**copy(item), 'prediction_sha256': None if prediction is None else digest(prediction),
               'eligible_probability': probability, 'learned_override': override,
               'eligible': eligible, 'decision_reason': reason, 'formula_admission': False}
        rows.append(row)
        if eligible:
            queries.append(copy(item['query']))
    raw_baseline = sum(i['status']=='surface_candidate' for i in planned['inventory'])
    guarded_baseline = sum(i['baseline_eligible'] for i in planned['inventory'])
    return {'schema': SCHEMA, 'phase': 'assessment', 'source_text': source_text,
            'source_sha256': planned['source_sha256'], 'raw_receipt_sha256': planned['raw_receipt_sha256'],
            'plan_sha256': digest(planned), 'checkpoint_sha256': None if policy is None else policy['checkpoint_sha256'],
            'policy': copy(policy), 'policy_sha256': None if policy is None else digest(policy),
            'predictions_sha256': None if predictions is None else digest(predictions),
            'rows': rows, 'queries': queries, 'conflict_components': copy(planned['conflict_components']),
            'counts': {'raw_candidates':len(rows),'raw_baseline_eligible':raw_baseline,
                       'guarded_baseline_eligible':guarded_baseline,
                       'baseline_blocked':raw_baseline-guarded_baseline,
                       'overridable_candidates':sum(i['overridable'] for i in planned['inventory']),
                       'learned_overrides':sum(r['learned_override'] for r in rows),
                       'eligible_queries':len(queries),'formula_admitted':0},
            'producer_pins':producer_pins(),'model_calls_by_adapter':0,
            'authority':dict(AUTHORITY),'formula_admission':False}
