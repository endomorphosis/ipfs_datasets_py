"""Independent exact-coordinate metrics for proposed temporal-owner pointers.

The syntactic inventory contains every ordered whole-token span disjoint from
the supplied time occurrence. It is not a semantic inventory of legal owners.
Reference anchors are authored targets and never numerical inference inputs.
"""
from __future__ import annotations

from collections import Counter
import math
import re

from . import legal_temporal_ownership_metrics as types

CLASSES = types.CLASSES
SOURCE_KEYS = types.SOURCE_KEYS
THRESHOLD = .8
SPAN_PROBABILITY_TOLERANCE = 2e-10
SPAN_KEYS = {'char_start', 'char_end'}
TARGET_KEYS = {'label', 'owner_anchor_span'}
POINTER_FIELDS = {'pointer_start_logits', 'pointer_end_logits', 'raw_owner_token_span',
    'raw_owner_anchor_span', 'span_confidence', 'valid_span_count', 'joint_status',
    'joint_reason', 'proposed_owner_anchor_span'}
PREDICTION_KEYS = types.PREDICTION_KEYS | POINTER_FIELDS
require, wire = types.require, types.wire


def source_tokens(source):
    time = types.validate_source(source)
    tokens = list(re.finditer(r'\w+|[^\w\s]', source['source_text'], re.UNICODE))
    return tokens, time


def valid_token_intervals(source):
    """Exhaustive bounded syntactic candidates, inclusive token endpoints."""
    tokens, (a, b) = source_tokens(source)
    return [(i, j) for lo, hi in ((0, a), (b + 1, len(tokens)))
            for i in range(lo, hi) for j in range(i, hi)]


def anchor_tokens(source, anchor):
    tokens, time = source_tokens(source)
    require(type(anchor) is dict and set(anchor) == SPAN_KEYS and
            all(type(anchor[k]) is int for k in SPAN_KEYS), 'closed integer owner anchor required')
    starts = {t.start(): i for i, t in enumerate(tokens)}
    ends = {t.end(): i for i, t in enumerate(tokens)}
    a, b = anchor['char_start'], anchor['char_end']
    require(0 <= a < b <= len(source['source_text']) and a in starts and b in ends,
            'owner anchor must preserve exact whole source tokens')
    i, j = starts[a], ends[b]
    require(j < time[0] or i > time[1], 'owner anchor cannot overlap the queried time')
    return [i, j]


def validate_target(source, target):
    types.validate_source(source)
    require(type(target) is dict and set(target) == TARGET_KEYS and
            type(target['label']) is str and target['label'] in CLASSES,
            'closed source-bound owner reference required')
    if target['label'] == 'ambiguous':
        require(target['owner_anchor_span'] is None, 'ambiguous reference cannot select one owner')
        return None
    require(target['owner_anchor_span'] is not None, 'determinate reference requires exact owner anchor')
    return anchor_tokens(source, target['owner_anchor_span'])


def _logits(values, count):
    require(type(values) is list and len(values) == count and
            all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 1e6 for v in values),
            'finite bounded full-source endpoint logits required')


def span_distribution(source, start_logits, end_logits):
    """Independent float64 ordered-pair normalization; no runtime import.

    Prefix sums compute the partition in O(tokens), independently of the
    runtime's exhaustive pair enumeration. Tests compare both definitions.
    """
    tokens, (a, b) = source_tokens(source); n = len(tokens)
    _logits(start_logits, n); _logits(end_logits, n)
    regions = [(0, a), (b + 1, n)]
    count = sum((hi - lo) * (hi - lo + 1) // 2 for lo, hi in regions)
    if count == 0:
        return {'valid_span_count': 0, 'raw_owner_token_span': None,
                'raw_owner_anchor_span': None, 'span_confidence': None}
    terms = []; best_pair = None; best_score = None
    for lo, hi in regions:
        if lo == hi: continue
        prefix_log = None; best_start = lo
        for j in range(lo, hi):
            if prefix_log is None: prefix_log = start_logits[j]
            else:
                upper, lower = max(prefix_log, start_logits[j]), min(prefix_log, start_logits[j])
                prefix_log = upper + math.log1p(math.exp(lower - upper))
            terms.append(prefix_log + end_logits[j])
            if start_logits[j] > start_logits[best_start]: best_start = j
            pair = (best_start, j); score = start_logits[best_start] + end_logits[j]
            if best_score is None or score > best_score or score == best_score and pair < best_pair:
                best_pair, best_score = pair, score
    scale = max(terms)
    partition = math.fsum(math.exp(term - scale) for term in terms)
    require(partition > 0 and math.isfinite(partition), 'finite nonempty span partition required')
    probability = math.exp(best_score - scale) / partition
    require(0 < probability <= 1 + 1e-12, 'invalid normalized span probability')
    i, j = best_pair
    return {'valid_span_count': count, 'raw_owner_token_span': [i, j],
            'raw_owner_anchor_span': {'char_start': tokens[i].start(), 'char_end': tokens[j].end()},
            'span_confidence': min(1., probability)}


def checked_prediction(source, row):
    require(type(row) is dict and set(row) == PREDICTION_KEYS, 'closed owner-pointer prediction required')
    type_row = {k: row[k] for k in types.PREDICTION_KEYS}
    type_result = types.checked_prediction(source, type_row)
    pointer = span_distribution(source, row['pointer_start_logits'], row['pointer_end_logits'])
    for key in ('valid_span_count', 'raw_owner_token_span', 'raw_owner_anchor_span'):
        require(wire(row[key]) == wire(pointer[key]), 'raw pointer inventory/argmax/source span differs')
    if pointer['span_confidence'] is None:
        require(row['span_confidence'] is None, 'empty pointer inventory cannot have confidence')
        roundoff = 0.
    else:
        p = row['span_confidence']
        require(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1,
                'finite normalized span confidence required')
        roundoff = abs(p - pointer['span_confidence'])
        require(roundoff <= SPAN_PROBABILITY_TOLERANCE, 'joint span probability differs from independent partition')
    reason = ('predicted_ambiguous' if type_result['label'] == 'ambiguous' else
              'no_valid_owner_span' if pointer['valid_span_count'] == 0 else
              'below_fixed_type_confidence' if row['confidence'] < THRESHOLD else
              'below_fixed_span_confidence' if row['span_confidence'] < THRESHOLD else None)
    accepted = reason is None
    require(row['joint_status'] == ('accepted' if accepted else 'deferred') and row['joint_reason'] == reason and
            wire(row['proposed_owner_anchor_span']) == wire(pointer['raw_owner_anchor_span'] if accepted else None),
            'joint decision differs from fixed type/span confidence policy')
    return {'type': type_result, 'pointer': pointer, 'accepted_joint': accepted,
            'span_probability_roundoff': roundoff}


def _endpoint_nll(logits, valid, target):
    require(target in valid and bool(valid), 'reference endpoint missing from syntactic inventory')
    maximum = max(logits[i] for i in valid)
    return maximum - logits[target] + math.log(math.fsum(math.exp(logits[i] - maximum) for i in valid))


def score(sources, predictions, targets):
    require(type(sources) is list and 1 <= len(sources) <= 4096 and type(predictions) is list and type(targets) is dict,
            'bounded complete owner evaluation required')
    by_source = {r['id']: r for r in sources}; by_prediction = {r['id']: r for r in predictions}
    require(len(by_source) == len(sources) == len(by_prediction) == len(predictions) == len(targets) and
            set(by_source) == set(by_prediction) == set(targets), 'complete unique owner query join required')
    rows = []; starts = []; ends = []; observed = set(); counts = Counter(); max_span_error = 0.
    for source in sources:
        query_id = source['id']; target = targets[query_id]; prediction = by_prediction[query_id]
        reference_tokens = validate_target(source, target); result = checked_prediction(source, prediction)
        identity = (source['source_sha256'], source['proposed_time_span']['char_start'], source['proposed_time_span']['char_end'])
        require(identity not in observed, 'duplicate source/time occurrence'); observed.add(identity)
        ambiguous = target['label'] == 'ambiguous'; type_correct = result['type']['label'] == target['label']
        anchor_exact = None if ambiguous else wire(prediction['raw_owner_anchor_span']) == wire(target['owner_anchor_span'])
        joint_correct = type_correct if ambiguous else type_correct and anchor_exact
        accepted = result['accepted_joint']; accepted_correct = accepted and not ambiguous and joint_correct
        counts.update({'ambiguous_queries': ambiguous, 'unique_owner_queries': not ambiguous,
            'type_correct': type_correct, 'anchor_exact': anchor_exact is True, 'joint_correct': joint_correct,
            'unique_joint_correct': not ambiguous and joint_correct, 'ambiguous_type_correct': ambiguous and type_correct,
            'ambiguous_deferred': ambiguous and not accepted, 'accepted_joint': accepted,
            'accepted_joint_correct': accepted_correct, 'accepted_joint_errors': accepted and not accepted_correct,
            'ambiguous_joint_acceptances': ambiguous and accepted,
            'accepted_wrong_anchor_same_type': accepted and not ambiguous and type_correct and not anchor_exact,
            'determinate_deferred': not ambiguous and not accepted,
            'syntactic_reference_span_covered': not ambiguous})
        if not ambiguous:
            tokens, (a, b) = source_tokens(source); valid = [i for i in range(len(tokens)) if i < a or i > b]
            starts.append(_endpoint_nll(prediction['pointer_start_logits'], valid, reference_tokens[0]))
            ends.append(_endpoint_nll(prediction['pointer_end_logits'], valid, reference_tokens[1]))
        max_span_error = max(max_span_error, result['span_probability_roundoff'])
        rows.append({'id': query_id, 'source_sha256': source['source_sha256'],
            'proposed_time_span': source['proposed_time_span'], 'target': target['label'],
            'target_owner_anchor_span': target['owner_anchor_span'], 'predicted_label': result['type']['label'],
            'raw_owner_anchor_span': prediction['raw_owner_anchor_span'],
            'proposed_owner_anchor_span': prediction['proposed_owner_anchor_span'],
            'type_correct': type_correct, 'anchor_exact': anchor_exact, 'joint_correct': joint_correct,
            'accepted_joint': accepted, 'accepted_joint_correct': accepted_correct,
            'joint_reason': prediction['joint_reason'], 'type_confidence': prediction['confidence'],
            'span_confidence': prediction['span_confidence'], 'valid_span_count': prediction['valid_span_count']})
    type_metrics = types.score(sources, [{k: p[k] for k in types.PREDICTION_KEYS} for p in predictions],
                              {k: v['label'] for k, v in targets.items()})
    mean_start = math.fsum(starts) / len(starts) if starts else 0.
    mean_end = math.fsum(ends) / len(ends) if ends else 0.
    return {'count': len(rows), **dict(counts), 'joint_accuracy': counts['joint_correct'] / len(rows),
        'joint_coverage': counts['accepted_joint'] / len(rows),
        'selective_joint_error_rate': counts['accepted_joint_errors'] / counts['accepted_joint'] if counts['accepted_joint'] else None,
        'mean_type_nll': type_metrics['mean_nll'], 'mean_start_nll_unique': mean_start,
        'mean_end_nll_unique': mean_end, 'composite_nll': type_metrics['mean_nll'] + .5 * (mean_start + mean_end),
        'type_metrics': {k: v for k, v in type_metrics.items() if k != 'rows'},
        'max_span_probability_roundoff': max_span_error, 'type_threshold': THRESHOLD, 'span_threshold': THRESHOLD,
        'candidate_scope': 'all ordered query-disjoint token spans; no semantic owner inventory claim',
        'owner_anchor_exact_match_measured': True, 'independent_legal_gold': False,
        'statutory_semantics_verified': False, 'formula_acceptance_authorized': False,
        'pipeline_promotion': False, 'rows': rows}
