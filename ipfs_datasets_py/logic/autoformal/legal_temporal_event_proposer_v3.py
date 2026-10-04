"""Bounded surface event-time proposals; no ownership or formal interpretation.

Unicode code-point offsets always address the unchanged caller-supplied source.
The old lexical proposer is retained. Event complements use declared nominal
and subject-predicate shapes, not an any-keyword match or general English parser.
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

SCHEMA = 'legal-temporal-event-proposals/v3'
PROFILE = 'bounded-event-surface-offsets/v3'
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
# These finite sets have grammatical roles. A matching word alone is never
# sufficient: the entire tokenized complement must fit a declared production.
EVENT_NOUNS = frozenset(('issuance', 'opportunity', 'receipt', 'publication', 'entry',
    'approval', 'execution', 'termination', 'notice', 'occurrence', 'completion',
    'enactment', 'denial', 'discharge', 'delivery', 'expiration', 'expiry',
    'certification', 'filing', 'registration', 'release', 'removal', 'acceptance',
    'hearing', 'audit', 'review', 'testing'))
INTRANSITIVE = frozenset(('arrives', 'arrived', 'expires', 'expired', 'elapses',
    'elapsed', 'concludes', 'concluded', 'ends', 'ended', 'closes', 'closed',
    'occurs', 'occurred', 'ceases', 'ceased', 'terminates', 'terminated'))
TRANSITIVE = frozenset(('provides', 'provided', 'publishes', 'published',
    'receives', 'received', 'issues', 'issued', 'delivers', 'delivered',
    'certifies', 'certified', 'accepts', 'accepted', 'reaches', 'reached',
    'approves', 'approved', 'completes', 'completed', 'releases', 'released',
    'discharges', 'discharged', 'denies', 'denied', 'enacts', 'enacted',
    'executes', 'executed', 'removes', 'removed', 'marks', 'marked',
    'signs', 'signed', 'records', 'recorded'))
PARTICIPLES = frozenset(('provided', 'published', 'received', 'issued',
    'delivered', 'certified', 'accepted', 'reached', 'approved', 'completed',
    'released', 'discharged', 'denied', 'enacted', 'executed', 'removed',
    'marked', 'terminated', 'filed', 'recorded', 'signed', 'entered', 'served'))
STATES = frozenset(('complete', 'final', 'effective', 'available', 'due'))
AUXILIARIES = frozenset(('is', 'are', 'was', 'were', 'has', 'have', 'had',
    'shall', 'must', 'may', 'will', 'would', 'should', 'can', 'could'))
OTHER_FINITE = frozenset(('files', 'acts', 'submits', 'archives', 'keeps',
    'responds', 'reports', 'waits', 'retains', 'transmits', 'applies', 'begins'))
PREDICATE_WORDS = INTRANSITIVE | TRANSITIVE | AUXILIARIES | OTHER_FINITE
DETERMINERS = frozenset(('the', 'a', 'an', 'this', 'that', 'these', 'those',
    'such', 'said', 'its', 'their', 'his', 'her', 'any', 'each'))
MODIFIERS = frozenset(('final', 'written', 'formal', 'official', 'initial',
    'actual', 'full', 'complete', 'lawful', 'timely', 'electronic', 'public',
    'prior', 'subsequent', 'certified'))
ADVERBS = frozenset(('finally', 'formally', 'officially', 'fully', 'duly',
    'actually', 'subsequently', 'already', 'timely'))
PREPOSITIONS = frozenset(('of', 'for', 'from', 'under', 'in', 'on', 'by',
    'to', 'with', 'at', 'as', 'into', 'through', 'between'))
REDUCED_MODIFIERS = frozenset(('implementing', 'governing', 'concerning',
    'specifying', 'describing'))
ABBREVIATIONS = frozenset(('dr', 'mr', 'mrs', 'ms', 'st', 'no', 'sec', 'art',
                          'para', 'fig', 'dept', 'jan', 'feb', 'mar', 'apr', 'jun',
                          'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec'))
GRAMMAR_TOKEN_RE = re.compile(r"\d+(?:\.\d+)+|\w+(?:['’]s|['’])?|[^\w\s]", re.UNICODE)


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


def _grammar_tokens(event):
    """Tokenize the complement; preserve citation/quotation groups as atoms.

    These tokens never supply output coordinates. Offsets always come from the
    original source scanner; no quote contents can masquerade as a predicate.
    """
    quoted, depths, _ = _lex(event)
    result, in_quote = [], False
    for token in GRAMMAR_TOKEN_RE.finditer(event):
        start, word = token.start(), token.group().lower()
        if quoted[start]:
            if not in_quote:
                result.append('@quote')
            in_quote = True
            continue
        in_quote = False
        if depths[start] or word in ')]}':
            continue
        if word in '([{':
            result.append('@group')
        elif word != '.':
            result.append(word)
    return result


def _np(tokens):
    """Bounded noun-phrase surface, with no embedded finite assertion.

    Unrecognized noun spelling is allowed only inside this grammatical slot.
    A second determiner needs an explicit preposition/coordinator; finite and
    negation words cannot be silently swallowed as noun modifiers.
    """
    if not tokens or len(tokens) > 48:
        return False
    if tokens[0] in PREPOSITIONS or tokens[-1] in PREPOSITIONS | {'and', 'or'}:
        return False
    substantive = False
    for i, token in enumerate(tokens):
        if token in (PREDICATE_WORDS - MODIFIERS) | {'not', 'never', 'no', 'unless', 'if',
                                      'after', 'until', 'when', 'while'}:
            return False
        if token in DETERMINERS:
            if i and tokens[i-1] not in PREPOSITIONS | {'and', 'or'}:
                return False
        elif token in PREPOSITIONS | {'and', 'or'}:
            if not i or tokens[i-1] in PREPOSITIONS | {'and', 'or'}:
                return False
        elif token in REDUCED_MODIFIERS:
            return substantive and _np(tokens[i+1:])
        elif token in MODIFIERS:
            # An adjective cannot be a trailing finite-word homograph, e.g.
            # 'approval of the Board certified'. Require a following head.
            following = next((t for t in tokens[i+1:] if t not in MODIFIERS), None)
            if (following is None or following in PREPOSITIONS | DETERMINERS |
                    PREDICATE_WORDS | REDUCED_MODIFIERS | {'and', 'or', '@group'}):
                return False
        elif token in ('@quote', '@group'):
            substantive = substantive or token == '@quote'
        elif re.fullmatch(r"\w+(?:['’]s|['’])?|\d+(?:\.\d+)+", token):
            if token.endswith('ly') and token not in ('assembly', 'family'):
                return False
            substantive = True
        else:
            return False
    return substantive and tokens[-1] not in DETERMINERS


def _minimum_relative(tokens):
    # A bounded relative duration phrase; its scope flag remains unresolved.
    if tokens[:2] not in (['that', 'is'], ['which', 'is']):
        return False
    tail = tokens[2:]
    if tail[:3] == ['not', 'less', 'than']:
        tail = tail[3:]
    elif tail[:2] == ['at', 'least']:
        tail = tail[2:]
    else:
        return False
    return (len(tail) == 2 and tail[0].isdigit() and
            tail[1] in ('day', 'days', 'hour', 'hours', 'month', 'months', 'year', 'years'))


def _nominal(tokens):
    if not tokens:
        return False
    i = 1 if tokens[0] in DETERMINERS else 0
    # An explicit possessive phrase can modify the event noun.
    possessives = [j for j, t in enumerate(tokens) if t.endswith(("'s", '’s', "'", '’'))]
    if possessives:
        j = possessives[0]
        if j > 11 or not _np(tokens[:j+1]):
            return False
        i = j+1
    while i < len(tokens) and tokens[i] in MODIFIERS | {'@quote'}:
        i += 1
    if i >= len(tokens) or tokens[i] not in EVENT_NOUNS:
        return False
    tail = tokens[i+1:]
    if not tail:
        return True
    if tail[0] in ('and', 'or'):
        return _nominal(tail[1:])
    if tail[0] == '@group':
        return _nominal(tokens[:i+1]+tail[1:])
    if tail[0] in REDUCED_MODIFIERS:
        return _np(tail[1:])
    if tail[0] in PREPOSITIONS:
        # Relative duration clauses are admitted only after a complete PP.
        relative = next((j for j, t in enumerate(tail) if t in ('that', 'which')
                         and j+1 < len(tail) and tail[j+1] == 'is'), None)
        if relative is not None:
            return _np(tail[1:relative]) and _minimum_relative(tail[relative:])
        return _np(tail[1:])
    return _minimum_relative(tail)


def _predicate(tokens):
    if not tokens:
        return False
    verb, tail = tokens[0], tokens[1:]
    if verb in ('is', 'are', 'was', 'were', 'has', 'have', 'had', 'shall'):
        active_perfect = False
        if tail[:1] == ['not']:
            tail = tail[1:]
        if verb == 'shall':
            if tail[:2] == ['have', 'been']:
                tail = tail[2:]
            elif tail[:1] == ['be']:
                tail = tail[1:]
            else:
                return False
        elif verb in ('has', 'have', 'had'):
            if tail[:1] == ['been']:
                tail = tail[1:]
            else:
                active_perfect = True
        while tail and tail[0] in ADVERBS:
            tail = tail[1:]
        if not tail or tail[0] not in PARTICIPLES | STATES:
            return False
        # Passive predicates do not permit an arbitrary unmarked object.
        # Marked labels are the one explicit quoted-object construction.
        participle, rest = tail[0], tail[1:]
        if active_perfect:
            return participle in PARTICIPLES and _np(rest)
        return (not rest or rest[0] in PREPOSITIONS and _np(rest[1:]) or
                participle == 'marked' and rest == ['@quote'])
    if verb in INTRANSITIVE:
        return not tail or tail[0] in PREPOSITIONS and _np(tail[1:])
    if verb in TRANSITIVE:
        return _np(tail)
    return False


def _clause(tokens):
    predicate = next((i for i, t in enumerate(tokens) if t in PREDICATE_WORDS), None)
    if predicate is None or predicate == 0 or not _np(tokens[:predicate]):
        return False
    # Only one predicate is allowed, except the declared reduced passive after
    # 'or'. Two complete clauses without a punctuation boundary are deferred:
    # the second might instead be an unpunctuated main clause.
    for i in range(predicate+1, len(tokens)):
        if tokens[i] not in ('and', 'or'):
            continue
        right = tokens[i+1:]
        reduced = (tokens[i] == 'or' and len(right) >= 3 and
                   right[0] in DETERMINERS and right[-1] in PARTICIPLES and
                   _nominal(right[:-1]))
        if _predicate(tokens[predicate:i]) and reduced:
            return True
    return _predicate(tokens[predicate:])


def _event_shape(event):
    tokens = _grammar_tokens(event)
    return _nominal(tokens) or _clause(tokens)


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
        if match.group().lower() == 'shall' and _event_shape(source[start:end]):
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
