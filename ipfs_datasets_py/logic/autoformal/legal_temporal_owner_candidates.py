"""Integrity contract for supplied temporal-owner candidates, not ownership.

This module validates coordinates in one exact source query. It neither finds
candidates in text nor selects a correct owner. In particular, reference-only
candidate lists must not be supplied to a learned pointer at inference time.
All intervals are half-open Unicode code-point offsets.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import legal_temporal_ownership_metrics as metric

SCHEMA = 'legal-temporal-owner-candidates/v1'
PROFILE = 'caller-supplied-source-bound-owner-occurrences/v1'
MAX_CANDIDATES = 16
TYPES = ('norm', 'condition', 'exception')
SPAN_KEYS = {'char_start', 'char_end', 'text'}
CANDIDATE_KEYS = {'owner_type', 'anchor_span', 'scope_span', 'cue_span'}
FALSE = {
    'source_semantics_verified': False,
    'independently_reviewed': False,
    'independent_legal_gold': False,
    'owner_occurrence_resolved': False,
    'unique_owner_asserted': False,
    'candidate_inventory_complete': False,
    'candidate_inventory_proposed_from_source': False,
    'training_executed': False,
    'model_inference_executed': False,
    'pipeline_promotion': False,
    'formula_acceptance_authorized': False,
}
require = metric.require


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def producer_pins():
    return {str(Path(m.__file__).resolve()): hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
            for m in (metric, __import__(__name__, fromlist=['_']))}


def _span(text, value, starts, ends):
    require(type(value) is dict and set(value) == SPAN_KEYS, 'closed source span required')
    a, b = value['char_start'], value['char_end']
    require(type(a) is int and type(b) is int and 0 <= a < b <= len(text), 'bounded integer source span required')
    require(a in starts and b in ends, 'span must preserve whole source tokens')
    require(type(value['text']) is str and text[a:b] == value['text'], 'span text differs from exact source occurrence')
    return a, b


def prepare_owner_candidates(query, candidates):
    """Bind caller-supplied candidates without evaluating attachment meaning."""
    metric.validate_source(query)
    require(type(candidates) is list and 1 <= len(candidates) <= MAX_CANDIDATES,
            'one to sixteen supplied candidates required')
    text = query['source_text']
    tokens = list(re.finditer(r'\w+|[^\w\s]', text, re.UNICODE))
    starts, ends = {t.start() for t in tokens}, {t.end() for t in tokens}
    time = query['proposed_time_span']; result = []; seen = set()
    for item in candidates:
        require(type(item) is dict and set(item) == CANDIDATE_KEYS and
                type(item['owner_type']) is str and item['owner_type'] in TYPES,
                'closed candidate with concrete declared owner type required')
        anchor = _span(text, item['anchor_span'], starts, ends)
        scope = _span(text, item['scope_span'], starts, ends)
        cue = _span(text, item['cue_span'], starts, ends)
        require(all(scope[0] <= a < b <= scope[1] for a, b in
                    (anchor, cue, (time['char_start'], time['char_end']))),
                'declared scope must contain its anchor, cue and queried time')
        require(anchor[1] <= cue[0] or cue[1] <= anchor[0], 'anchor and cue must be distinct occurrences')
        require(all(b <= time['char_start'] or time['char_end'] <= a for a, b in (anchor, cue)),
                'owner anchor and cue cannot be the queried time')
        identity = {'source_sha256': query['source_sha256'], **deepcopy(item)}
        candidate_id = 'owner-' + digest(identity)
        require(candidate_id not in seen, 'duplicate owner occurrence candidate')
        seen.add(candidate_id)
        result.append({'candidate_id': candidate_id, **deepcopy(item)})
    report = {'schema': SCHEMA, 'profile': PROFILE, 'query': deepcopy(query),
              'query_sha256': digest(query), 'candidates': result,
              'candidate_input_sha256': digest(candidates),
              'caller_supplied_candidates': True,
              'candidate_origin': 'caller_supplied_unreviewed',
              'coordinate_integrity_verified': True,
              'candidate_types_are_caller_declarations': True,
              'candidate_ids_bind_source_occurrences': True,
              'query_id_is_not_a_model_feature': True,
              'selected_candidate_id': None,
              'selection_policy': 'no_owner_selection_performed',
              'scope': 'Exact supplied source coordinates only; candidate completeness, attachment, legal meaning and authority remain unverified.',
              'producer_pins': producer_pins(), **FALSE}
    report['report_sha256'] = digest(report)
    return report


def validate_owner_candidates(report, *, query, candidates):
    """Require exact regeneration from separately supplied authoritative inputs."""
    require(type(report) is dict and wire(report) == wire(prepare_owner_candidates(query, candidates)),
            'owner-candidate report differs from authoritative request')
    return True
