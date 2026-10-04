"""Monotone, source-only tightening of the declared flat-scope surface veto.

V1 evidence is retained verbatim and a V1 deferral can never be promoted. This
version rejects unclassified scope cues, unprotected editorial punctuation, and
nominal-only qualifier atoms. The finite predicate grammar is intentionally
narrow; passing it is not evidence of statutory meaning or independence.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import re

from . import legal_flat_scope_dependencies as base
from . import legal_rule_list_composition as composition

SCHEMA = 'legal-flat-scope-dependency-evidence/v2'
PROFILE = 'declared-local-flat-surface-grammar/v2'
ATOM_GRAMMAR = 'explicit-local-predicate-atoms/v1'

# These are lexical vetoes, not inferred meanings or guessed attachments.
UNCLASSIFIED = (
    ('unclassified_exception_cue', re.compile(r'\bexcept\b(?!\s+(?:when|where)\b)', re.I)),
    ('unclassified_proviso_cue', re.compile(r'\bprovided\b(?!\s+that\b)', re.I)),
    ('unclassified_necessary_condition_cue', re.compile(r'\bonly\s+if\b', re.I)),
    ('unclassified_cross_clause_context', re.compile(r'\b(?:otherwise|in\s+that\s+case|in\s+such\s+(?:case|event)|if\s+so|if\s+not|then\s+and\s+only\s+then)\b', re.I)),
)
HEADING_PATTERNS = tuple(re.compile(p.pattern, p.flags | re.I) for p in base.HEADING_PATTERNS)
WORD = r"[A-Za-z][A-Za-z0-9]*(?:[-'’][A-Za-z0-9]+)*"
SUBJECT = rf'{WORD}(?:\s+{WORD}){{0,11}}'
TIME = r'(?:within\s+\d+(?:\.\d+)?\s+(?:days?|hours?)(?:\s+of\s+publication)?|(?:before|after|by|on)\s+(?:\d{4}-\d{2}-\d{2}|May\s+\d{1,2}(?:,\s*\d{4})?))'
ATOM_RULES = (
    ('copular_state', re.compile(rf'(?P<subject>{SUBJECT})\s+(?:is|are|was|were)\s+(?:not\s+)?(?:active|inactive|valid|invalid|complete|incomplete|open|closed|sealed|unsealed|eligible|ineligible|exempt|pending|available|unavailable|applicable)', re.I)),
    ('passive_event', re.compile(rf'(?P<subject>{SUBJECT})\s+(?:is|are|was|were)\s+(?:not\s+)?(?:received|filed|submitted|approved|recorded|published|delivered)(?:\s+{TIME})?', re.I)),
    ('explicit_event', re.compile(rf'(?P<subject>{SUBJECT})\s+(?:arrives|arrived|expires|expired|occurs|occurred|applies|applied)(?:\s+{TIME})?', re.I)),
)
SUBJECT_RESERVED = re.compile(r'\b(?:and|or|but|nor|if|when|unless|except|provided|otherwise|only|then|is|are|was|were|arrives|arrived|expires|expired|occurs|occurred|applies|applied)\b', re.I)


def digest(value):
    return composition.digest(value)


def _pins():
    return base.producer_pins() | {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_IMPORTED_PINS = _pins()


def producer_pins():
    base._require(_pins() == _IMPORTED_PINS, 'flat dependency v2 source changed since import')
    return dict(_IMPORTED_PINS)


def _editorial_findings(text, base_evidence):
    # Search after quote masking only. A cue word cannot be hidden inside a
    # caption, and an already recognized caption needs no additional veto.
    quoted = [p for p in base_evidence['protected_spans'] if p['kind'] == 'quoted_literal']
    known = [p for p in base_evidence['protected_spans'] if p['kind'] == 'editorial_heading']
    masked = base._mask(text, quoted)
    spans = {}
    for pattern in HEADING_PATTERNS:
        for match in re.finditer('(?=(' + pattern.pattern + '))', masked, pattern.flags):
            start, end = base._trim(text, *match.span(1))
            title = text[start:end]
            if base.MODAL.search(title) or base.QUALIFIER.search(title):
                continue
            if any(p['char_start'] <= start and end <= p['char_end'] for p in known):
                continue
            spans[start, end] = base._node(text, 'unclassified_editorial_punctuation', start, end)
    # Keep the maximal candidate where overlapping starts describe the same
    # explicit marker. Exact offsets remain visible; no new plan is produced.
    return [value for (start, end), value in sorted(spans.items())
            if not any(a <= start and end <= b and (a, b) != (start, end) for a, b in spans)]


def _local_atom_findings(text, base_evidence):
    atoms = []
    for qualifier in base_evidence['qualifier_nodes']:
        if qualifier['attachment_status'] != 'local_declared_atom':
            continue
        start, end = qualifier['atom_span']
        literal = text[start:end]
        rule_id = None
        for name, pattern in ATOM_RULES:
            matched = pattern.fullmatch(literal)
            if matched and not SUBJECT_RESERVED.search(matched['subject']) and not base.MODAL.search(matched['subject']):
                rule_id = name
                break
        atoms.append({'qualifier_id': qualifier['node_id'], 'owner_norm_id': qualifier['owner_norm_id'],
                      'kind': qualifier['kind'], 'char_start': start, 'char_end': end, 'source_text': literal,
                      'grammar': ATOM_GRAMMAR, 'matched_rule': rule_id,
                      'within_declared_atom_grammar': rule_id is not None})
    return atoms


def prepare_flat_scope_dependencies(source, source_plan, *, expected_plan_sha256, profile=PROFILE):
    """Return an offset-bound veto receipt, without approving semantic scope."""
    base._require(profile == PROFILE, 'explicit supported dependency v2 profile required')
    evidence = base.prepare_flat_scope_dependencies(source, source_plan, expected_plan_sha256=expected_plan_sha256)
    text = evidence['source']['source_text']
    quotes = [p for p in evidence['protected_spans'] if p['kind'] == 'quoted_literal']
    masked = base._mask(text, quotes)
    cue_findings = [base._node(text, reason, *match.span()) for reason, pattern in UNCLASSIFIED for match in pattern.finditer(masked)]
    cue_findings.sort(key=lambda item: (item['char_start'], item['char_end'], item['kind']))
    editorial_findings = _editorial_findings(text, evidence)
    atoms = _local_atom_findings(text, evidence)
    new_reasons = sorted({row['kind'] for row in cue_findings + editorial_findings} |
                         ({'local_qualifier_atom_outside_declared_grammar'} if any(not row['within_declared_atom_grammar'] for row in atoms) else set()))
    reasons = sorted(set(evidence['reasons'] + new_reasons))
    result = {key: deepcopy(value) for key, value in evidence.items() if key != 'evidence_sha256'}
    result.update({'schema': SCHEMA, 'profile': PROFILE, 'producer_pins': producer_pins(),
                   'status': 'deferred' if reasons else 'structurally_flat', 'allows_flat_composition': not reasons,
                   'reasons': reasons, 'base_evidence': evidence, 'additional_reasons': new_reasons,
                   'unclassified_cue_findings': cue_findings, 'editorial_findings': editorial_findings,
                   'local_atom_checks': atoms, 'local_atom_grammar': ATOM_GRAMMAR,
                   'v1_deferral_never_promoted': True,
                   'claim': 'Monotone source-only surface veto with finite local predicate grammar; no verified semantic independence or statutory scope.',
                   'coverage_limit': 'Broader predicates, unclassified scope cues, and captions not recognized by V1 defer; quoted content remains opaque.'})
    result['evidence_sha256'] = digest(result)
    return deepcopy(result)


def validate_flat_scope_dependencies(source, source_plan, evidence, *, expected_plan_sha256):
    base._require(type(evidence) is dict, 'closed dependency evidence required')
    expected = prepare_flat_scope_dependencies(source, source_plan, expected_plan_sha256=expected_plan_sha256)
    base._require(composition._wire(evidence) == composition._wire(expected), 'dependency evidence differs from authoritative regeneration')
    return expected
