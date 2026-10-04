"""Independent arithmetic and source joins for owner-type head diagnostics.

No training runtime is imported. A confident owner type remains a proposal:
neither the exact owner occurrence nor statutory meaning is certified here.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
import re

CLASSES = ('norm', 'condition', 'exception', 'ambiguous')
THRESHOLD = .8
PROBABILITY_TOLERANCE = 2e-7
SOURCE_KEYS = {'id', 'source_text', 'source_sha256', 'proposed_time_span'}
FALSE_FIELDS = {'statutory_semantics_verified', 'owner_occurrence_resolved',
                'latent_input_enabled', 'pipeline_promotion', 'existing_gates_changed'}
PREDICTION_KEYS = {'id', 'source_sha256', 'proposed_time_span', 'time_token_span',
    'logits', 'probabilities', 'predicted_label', 'confidence', 'status', 'owner_type',
    'reason'} | FALSE_FIELDS


def require(ok, message):
    if not ok:
        raise ValueError(message)


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def validate_source(source):
    require(type(source) is dict and set(source) == SOURCE_KEYS, 'closed four-field source query required')
    text = source['source_text']
    require(type(text) is str and 0 < len(text.encode()) <= 40000, 'bounded source text required')
    require(type(source['id']) is str and 0 < len(source['id']) <= 256, 'bounded query ID required')
    require(type(source['source_sha256']) is str and source['source_sha256'] == hashlib.sha256(text.encode()).hexdigest(),
            'source text/hash differs')
    span = source['proposed_time_span']
    require(type(span) is dict and set(span) == {'char_start', 'char_end'}, 'closed occurrence span required')
    a, b = span['char_start'], span['char_end']
    require(type(a) is int and type(b) is int and 0 <= a < b <= len(text), 'exact integer occurrence bounds required')
    tokens = list(re.finditer(r'\w+|[^\w\s]', text, re.UNICODE))
    require(0 < len(tokens) <= 256 and all(len(t.group().encode()) <= 2048 for t in tokens),
            'source token/byte bounds exceeded; no truncation')
    starts = {t.start(): i for i, t in enumerate(tokens)}
    ends = {t.end(): i for i, t in enumerate(tokens)}
    require(a in starts and b in ends, 'time occurrence does not align with source tokens')
    return [starts[a], ends[b]]


def softmax(logits):
    require(type(logits) is list and len(logits) == 4 and
            all(type(v) in (int, float) and math.isfinite(v) and abs(v) <= 1e6 for v in logits),
            'four bounded finite logits required')
    maximum = max(logits)
    values = [math.exp(x - maximum) for x in logits]
    total = math.fsum(values)
    return [x / total for x in values]


def checked_prediction(source, row):
    token_span = validate_source(source)
    require(type(row) is dict and set(row) == PREDICTION_KEYS, 'closed prediction row required')
    require(row['id'] == source['id'] and row['source_sha256'] == source['source_sha256'] and
            wire(row['proposed_time_span']) == wire(source['proposed_time_span']), 'prediction/source query differs')
    require(wire(row['time_token_span']) == wire(token_span), 'predicted token occurrence differs')
    expected = softmax(row['logits'])
    probabilities = row['probabilities']
    require(type(probabilities) is list and len(probabilities) == 4 and
            all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in probabilities),
            'four finite probabilities required')
    error = max(abs(p-q) for p, q in zip(probabilities, expected))
    require(error <= PROBABILITY_TOLERANCE and abs(math.fsum(probabilities)-1) <= 4*PROBABILITY_TOLERANCE,
            'probabilities differ from independent softmax')
    index = max(range(4), key=lambda i: row['logits'][i])
    label = CLASSES[index]
    confidence = probabilities[index]
    require(type(row['confidence']) in (int, float) and math.isfinite(row['confidence']) and
            row['confidence'] == confidence, 'confidence differs from reported probability')
    # Decisions use the recorded model probability; metrics use stable float64
    # reconstruction. The bounded difference is exposed, not silently repaired.
    accepted = label != 'ambiguous' and confidence >= THRESHOLD
    reason = None if accepted else ('predicted_ambiguous' if label == 'ambiguous' else 'below_fixed_confidence')
    require(row['predicted_label'] == label and row['status'] == ('accepted' if accepted else 'deferred') and
            row['owner_type'] == (label if accepted else None) and row['reason'] == reason,
            'recorded owner decision differs from fixed policy')
    require(all(row[key] is False for key in FALSE_FIELDS), 'owner type cannot certify authority or deployment')
    return {'probabilities': expected, 'prediction': index, 'label': label, 'confidence': confidence,
            'accepted': accepted, 'probability_roundoff': error}


def joined(sources, predictions, labels):
    require(type(sources) is list and 1 <= len(sources) <= 4096 and type(predictions) is list,
            'bounded complete source/prediction list required')
    require(type(labels) is dict and all(type(k) is str and v in CLASSES for k, v in labels.items()),
            'source-bound four-class reference labels required')
    by_source = {s['id']: s for s in sources}
    by_prediction = {r['id']: r for r in predictions}
    require(len(by_source) == len(sources) == len(predictions) == len(by_prediction) == len(labels) and
            set(by_source) == set(by_prediction) == set(labels), 'complete unique query inventory required')
    occurrences = set()
    for source in sources:
        result = checked_prediction(source, by_prediction[source['id']])
        occurrence = (source['source_sha256'], source['proposed_time_span']['char_start'],
                      source['proposed_time_span']['char_end'])
        require(occurrence not in occurrences, 'duplicate source occurrence')
        occurrences.add(occurrence)
        yield source, by_prediction[source['id']], CLASSES.index(labels[source['id']]), result


def score(sources, predictions, labels):
    matrix = [[0]*4 for _ in range(4)]
    rows, losses, briers, bins, roundoff = [], [], [], [[] for _ in range(10)], []
    for source, raw, target, result in joined(sources, predictions, labels):
        predicted = result['prediction']; probabilities = result['probabilities']
        matrix[target][predicted] += 1
        logits = raw['logits']; maximum = max(logits)
        losses.append(maximum + math.log(math.fsum(math.exp(v-maximum) for v in logits)) - logits[target])
        briers.append(math.fsum((p-int(i == target))**2 for i, p in enumerate(probabilities)))
        confidence = probabilities[predicted]
        bins[min(9, int(confidence*10))].append((confidence, predicted == target))
        roundoff.append(result['probability_roundoff'])
        rows.append({'id': source['id'], 'source_sha256': source['source_sha256'],
            'proposed_time_span': source['proposed_time_span'], 'target': CLASSES[target],
            'predicted': CLASSES[predicted], 'correct': predicted == target,
            'accepted_type_proposal': result['accepted'],
            'accepted_type_error': result['accepted'] and predicted != target,
            'ambiguous_confidently_resolved': result['accepted'] and CLASSES[target] == 'ambiguous'})
    count = len(rows); per_class = {}
    for i, name in enumerate(CLASSES):
        tp = matrix[i][i]; support = sum(matrix[i]); predicted_count = sum(row[i] for row in matrix)
        precision = tp/predicted_count if predicted_count else 0.
        recall = tp/support if support else 0.
        f1 = 2*tp/(support+predicted_count) if support+predicted_count else 0.
        per_class[name] = {'support': support, 'predicted': predicted_count, 'correct': tp,
                           'precision': precision, 'recall': recall, 'f1': f1}
    accepted = sum(r['accepted_type_proposal'] for r in rows)
    errors = sum(r['accepted_type_error'] for r in rows)
    ece = math.fsum(abs(math.fsum(p for p, _ in bucket)/len(bucket) -
                          sum(y for _, y in bucket)/len(bucket))*len(bucket)/count
                    for bucket in bins if bucket)
    return {'count': count, 'correct': sum(r['correct'] for r in rows),
        'accuracy': sum(r['correct'] for r in rows)/count,
        'class_order': list(CLASSES), 'confusion_target_rows_prediction_columns': matrix,
        'per_class': per_class, 'macro_f1': math.fsum(v['f1'] for v in per_class.values())/4,
        'mean_nll': math.fsum(losses)/count, 'multiclass_brier_sum': math.fsum(briers)/count,
        'ece_10_equal_width_bins': ece, 'threshold': THRESHOLD,
        'accepted_type_proposals': accepted, 'accepted_type_errors': errors,
        'type_proposal_coverage': accepted/count, 'selective_type_error_rate': errors/accepted if accepted else None,
        'ambiguous_queries': per_class['ambiguous']['support'],
        'ambiguous_confidently_resolved': sum(r['ambiguous_confidently_resolved'] for r in rows),
        'max_float32_probability_roundoff': max(roundoff), 'rows': rows,
        'owner_occurrence_resolved': False, 'source_semantics_verified': False,
        'attachment_or_formula_acceptance_measured': False}


def occurrence_diagnostics(sources, predictions, labels, *, require_query_invariance=False):
    groups = defaultdict(list)
    for source, raw, target, result in joined(sources, predictions, labels):
        groups[source['source_sha256']].append((source, raw, target, result))
    rows = []
    for source_sha, group in sorted(groups.items()):
        if len(group) < 2:
            continue
        baseline = group[0][1]['logits']
        difference = max(abs(v-baseline[i]) for _, raw, _, _ in group for i, v in enumerate(raw['logits']))
        if require_query_invariance:
            require(difference <= 1e-6, 'query-agnostic baseline changed for the same source')
        labels_differ = len({item[2] for item in group}) > 1
        predictions_differ = len({item[3]['prediction'] for item in group}) > 1
        rows.append({'source_sha256': source_sha, 'query_ids': [item[0]['id'] for item in group],
            'query_count': len(group), 'max_absolute_logit_difference': difference,
            'reference_types_differ': labels_differ, 'predicted_types_differ': predictions_differ,
            'all_types_correct': all(item[2] == item[3]['prediction'] for item in group)})
    return {'repeated_source_groups': len(rows), 'groups': rows,
        'all_types_correct_groups': sum(r['all_types_correct'] for r in rows),
        'distinct_predicted_type_groups': sum(r['predicted_types_differ'] for r in rows),
        'query_agnostic_invariance_required': require_query_invariance,
        'owner_occurrence_resolution_measured': False}
