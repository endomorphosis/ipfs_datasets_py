"""Bounded surface event-time proposals; no ownership or formal interpretation.

Unicode code-point offsets always address the unchanged caller-supplied source.
The old lexical proposer is retained. New event complements use an explicit
lexical profile and punctuation boundaries, not a general English parser.
Anaphora, event identity, nested scope and inequality direction remain unresolved
even when a surface interval is eligible for owner diagnostics. Source IDs,
labels, owner candidates and formulas are never inputs to this module.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from . import legal_temporal_ownership_corpus as legacy

SCHEMA = 'legal-temporal-event-proposals/v2'
PROFILE = 'bounded-event-surface-offsets/v2'
MAX_SOURCE_CHARACTERS = 4096
MAX_SOURCE_BYTES = 40000
MAX_SOURCE_TOKENS = 256
FAMILIES = ('legacy_lexical', 'not_later_than_after', 'after_event', 'until_event')
STATUSES = ('surface_candidate', 'deferred')
REASONS = ('quoted_cue_mention', 'quoted_time_mention', 'unbalanced_delimiters',
           'unterminated_quotation', 'missing_event_complement',
           'unsupported_event_shape', 'ambiguous_unpunctuated_clause_boundary',
           'ambiguous_nested_temporal_boundary', 'source_token_budget_exceeded',
           'invalid_calendar_literal')
SEMANTIC_KEYS = ('event_reference_unresolved', 'event_anaphora_unresolved',
                 'minimum_duration_scope_unresolved', 'nested_temporal_scope_unresolved',
                 'temporal_direction_unresolved')
AUTHORITY = {'legal_semantics_verified': False, 'owner_assigned': False,
             'formal_formula_admitted': False}
TOKEN_RE = re.compile(r'\w+|[^\w\s]', re.UNICODE)
CUE_RE = re.compile(r'(?<!\w)(?P<deadline>not\s+later\s+than\s+[1-9]\d{0,2}\s+'
                    r'(?:days?|hours?|months?|years?)\s+after)|(?<!\w)(?P<after>after)(?!\w)|'
                    r'(?<!\w)(?P<until>until)(?!\w)', re.IGNORECASE)
MINIMUM_RE = re.compile(r'\b(?:not\s+less\s+than|at\s+least)\s+\d+\s+'
                        r'(?:days?|hours?|months?|years?)\b', re.IGNORECASE)
ANAPHORA_RE = re.compile(r'\b(?:such|said|aforementioned|thereof|thereto)\b|^(?:this|that|these|those)\b', re.IGNORECASE)
# This is an intentionally finite lexical proposal profile, not event semantics.
EVENT_WORDS = frozenset(('issuance', 'opportunity', 'receipt', 'publication', 'entry',
    'approval', 'execution', 'termination', 'notice', 'occurrence', 'completion',
    'enactment', 'denial', 'discharge', 'delivery', 'expiration', 'expiry',
    'provides', 'provided', 'publishes', 'published', 'receives', 'received',
    'issues', 'issued', 'delivers', 'delivered', 'arrives', 'arrived',
    'expires', 'expired', 'elapses', 'elapsed', 'discharged', 'denied',
    'approved', 'completed', 'terminated', 'enacted', 'executed'))
ABBREVIATIONS = frozenset(('dr', 'mr', 'mrs', 'ms', 'st', 'no', 'sec', 'art',
                          'para', 'fig', 'jan', 'feb', 'mar', 'apr', 'jun',
                          'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def _pins():
    return {str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest()
            for p in (__file__, legacy.__file__)}


_INITIAL_PINS = _pins()


def producer_pins():
    require(_pins() == _INITIAL_PINS, 'event proposer producer changed')
    return dict(_INITIAL_PINS)


def _span(start, end):
    return {'char_start': start, 'char_end': end}


def _lex(source):
    """Mark quote interiors and bracket depth without normalizing source bytes."""
    quoted, depths = [False] * len(source), [0] * len(source)
    stack, quote, errors = [], None, []
    pairs = {'(': ')', '[': ']', '{': '}'}
    quotes = {'"': '"', "'": "'", '“': '”', '‘': '’'}
    for i, char in enumerate(source):
        depths[i] = len(stack)
        apostrophe = (char in ("'", '’') and i > 0 and i+1 < len(source)
                      and source[i-1].isalnum() and source[i+1].isalnum())
        if quote is None and char in ("'", '’') and i > 0 and source[i-1].lower() == 's':
            apostrophe = apostrophe or i+1 == len(source) or source[i+1].isspace()
        if quote:
            quoted[i] = True
            if char == quote and not apostrophe and (i == 0 or source[i-1] != '\\'):
                quote = None
            continue
        if char in quotes and not apostrophe:
            quote = quotes[char]
            quoted[i] = True
        elif char in pairs:
            stack.append(pairs[char])
        elif char in ')]}':
            if stack and stack[-1] == char:
                stack.pop()
            else:
                errors.append('unbalanced_delimiters')
    if stack:
        errors.append('unbalanced_delimiters')
    if quote:
        errors.append('unterminated_quotation')
    return quoted, depths, sorted(set(errors))


def _sentence_period(source, index):
    if index > 0 and index+1 < len(source) and source[index-1].isdigit() and source[index+1].isdigit():
        return False
    match = re.search(r'([A-Za-z]+)$', source[:index])
    word = match.group(1) if match else ''
    if word.lower() in ABBREVIATIONS:
        return False
    # Initials and punctuated citations (U.S.C.) are not sentence cuts here.
    if len(word) == 1 and word.isupper():
        return False
    return True


def _end(source, start, quoted, depths):
    baseline = depths[start] if start < len(source) else 0
    for i in range(start, len(source)):
        if quoted[i]:
            continue
        if depths[i] < baseline or source[i] in ')]}' and depths[i] == baseline:
            return i
        if depths[i] != baseline:
            continue
        char = source[i]
        if char in ',;!?' or char == '.' and _sentence_period(source, i) or char in '\n\r':
            return i
    return len(source)


def _event_shape(event):
    words = re.findall(r'\w+', event.lower(), re.UNICODE)
    return bool(words and any(word in EVENT_WORDS for word in words[:12]))


def _independent_modal(source, start, end, quoted, depths):
    """Recognize only explicitly allowed subordinate perfect/passive modals.

    A further finite modal could start an unpunctuated main clause; do not guess
    where its subject begins. This is a deferral, not an inferred attachment.
    """
    baseline = depths[start] if start < len(source) else 0
    for match in re.finditer(r'\b(?:shall|must|may)\b', source[start:end], re.IGNORECASE):
        a, b = start+match.start(), start+match.end()
        if quoted[a] or depths[a] != baseline:
            continue
        tail = source[b:end]
        if re.match(r'\s+(?:have\s+been|be)\s+(?:finally\s+)?'
                    r'(?:discharged|denied|approved|completed|terminated|enacted|executed)\b', tail, re.IGNORECASE):
            continue
        return True
    return False


def _semantic(event, nested):
    return {'event_reference_unresolved': True,
            'event_anaphora_unresolved': bool(ANAPHORA_RE.search(event)),
            'minimum_duration_scope_unresolved': bool(MINIMUM_RE.search(event)),
            'nested_temporal_scope_unresolved': nested,
            'temporal_direction_unresolved': True}


def propose(source_text):
    """Return surface evidence only; status describes interval eligibility.

    Bounded but anaphoric/minimum-duration complements may be candidates, while
    their semantic flags remain unresolved. Unsupported/ambiguous boundaries
    are deferred. No candidate is a legal temporal operator or an owner anchor.
    """
    require(type(source_text) is str and 0 < len(source_text) <= MAX_SOURCE_CHARACTERS,
            'source must contain 1..4096 Unicode characters; truncation forbidden')
    require(len(source_text.encode('utf8')) <= MAX_SOURCE_BYTES, 'source UTF8 byte budget exceeded')
    quoted, depths, errors = _lex(source_text)
    tokens = list(TOKEN_RE.finditer(source_text))
    proposals, issues = [], []
    budget_reasons = ['source_token_budget_exceeded'] if len(tokens) > MAX_SOURCE_TOKENS else []
    if budget_reasons:
        issues.append({'cue_span': None, 'reason_codes': list(budget_reasons)})
    starts, ends = {t.start() for t in tokens}, {t.end() for t in tokens}
    for match in legacy.TIME_RE.finditer(source_text):
        a, b = match.span()
        interval = _span(a, b)
        legacy_cue = _span(a, a+len(match.group().split()[0]))
        try:
            # Validate each literal with the frozen calendar logic independently;
            # one malformed date must not erase other valid occurrences.
            legacy.propose_time_spans(match.group())
        except ValueError:
            issues.append({'cue_span': legacy_cue, 'reason_codes': ['invalid_calendar_literal']})
            continue
        reasons = budget_reasons + (['quoted_time_mention'] if quoted[a] else [])
        proposals.append({'query': legacy.query(source_text, interval), 'family': 'legacy_lexical',
            'cue_span': legacy_cue, 'event_span': None,
            'status': 'deferred' if reasons else 'surface_candidate', 'reason_codes': reasons,
            'semantic_flags': dict.fromkeys(SEMANTIC_KEYS, False)})
    cues = list(CUE_RE.finditer(source_text))
    for cue in cues:
        a, cue_end = cue.span()
        cue_span = _span(a, a+re.match(r'not\s+later\s+than', cue.group(), re.IGNORECASE).end()) if cue.lastgroup == 'deadline' else _span(a, cue_end)
        if quoted[a]:
            issues.append({'cue_span': cue_span, 'reason_codes': ['quoted_cue_mention']})
            continue
        begin = cue_end
        while begin < len(source_text) and source_text[begin].isspace():
            begin += 1
        end = _end(source_text, begin, quoted, depths)
        while end > begin and source_text[end-1].isspace():
            end -= 1
        if begin >= end or not re.search(r'\w', source_text[begin:end]):
            issues.append({'cue_span': cue_span, 'reason_codes': ['missing_event_complement']})
            continue
        event = source_text[begin:end]
        reasons = list(errors) + budget_reasons
        if not _event_shape(event):
            reasons.append('unsupported_event_shape')
        if _independent_modal(source_text, begin, end, quoted, depths):
            reasons.append('ambiguous_unpunctuated_clause_boundary')
        nested = any(begin <= c.start() < end and not quoted[c.start()] for c in cues)
        if nested:
            # Several temporal cues without an intervening declared cut can
            # support multiple envelopes; retain evidence but do not pick.
            reasons.append('ambiguous_nested_temporal_boundary')
        require(a in starts and end in ends, 'proposed event interval is not token aligned')
        family = ('not_later_than_after' if cue.lastgroup == 'deadline' else
                  'after_event' if cue.lastgroup == 'after' else 'until_event')
        reasons = sorted(set(reasons))
        proposals.append({'query': legacy.query(source_text, _span(a, end)), 'family': family,
            'cue_span': cue_span, 'event_span': _span(begin, end),
            'status': 'deferred' if reasons else 'surface_candidate', 'reason_codes': reasons,
            'semantic_flags': _semantic(event, nested)})
    proposals.sort(key=lambda p: (p['query']['proposed_time_span']['char_start'],
                                 p['query']['proposed_time_span']['char_end'], p['family']))
    require(len({p['query']['id'] for p in proposals}) == len(proposals), 'duplicate temporal occurrence')
    return {'schema': SCHEMA, 'profile': PROFILE, 'source_text': source_text,
            'source_sha256': hashlib.sha256(source_text.encode()).hexdigest(),
            'proposals': proposals, 'issues': issues, 'producer_pins': producer_pins(),
            'authority': dict(AUTHORITY)}


def validate_result(source_text, receipt):
    """Regenerate from authoritative source; no repaired-hash/status shortcuts."""
    require(type(receipt) is dict and _wire(receipt) == _wire(propose(source_text)),
            'event proposal receipt differs from authoritative regeneration')
    return receipt


def source_queries(source_text, receipt):
    """Project eligible surface candidates to the unchanged four-field wire."""
    validate_result(source_text, receipt)
    return [dict(p['query'], proposed_time_span=dict(p['query']['proposed_time_span']))
            for p in receipt['proposals'] if p['status'] == 'surface_candidate']
