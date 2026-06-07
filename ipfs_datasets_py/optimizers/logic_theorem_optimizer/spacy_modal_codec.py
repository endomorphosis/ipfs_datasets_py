"""spaCy-based legal modal encoder, IR compiler, and vector decoder."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .legal_modal_parser import LegalModalParser
from .legal_samples import LegalSample
from .modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)
from .modal_registry import (
    DEFAULT_MODAL_REGISTRY,
    ModalLogicFamily,
    ModalOperatorSpec,
    ModalParseProfile,
    ModalRegistry,
)

_WHITESPACE_RE = re.compile(r"\s+")
_CLAUSE_DELIMITER_RE = re.compile(r"[,;:\n.]")
_CLAUSE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")
_CONDITION_PREFIXES = (
    "provided that",
    "provided, that",
    "provided , that",
    "subject to",
    "if",
    "when",
    "before",
    "upon",
)
_EXCEPTION_PREFIXES = ("except that", "except as", "unless", "except")
_CONDITIONAL_SCOPE_PHRASES = (
    "any person who",
    "any person that",
    "any individual who",
    "any entity that",
    "whoever",
    "as provided by",
    "as provided in",
    "as provided under",
    "as otherwise provided by",
    "as otherwise provided in",
    "as otherwise provided under",
    "except as provided by",
    "in the case of",
    "in the event that",
    "provided, that",
    "provided , that",
    "does not affect",
    "notwithstanding",
    "for purposes of",
    "for the purposes of",
    "with respect to",
    "to the extent provided",
    "except to the extent",
    "except as otherwise provided",
    "under terms and conditions",
    "under such terms and conditions",
    "on such terms and conditions",
    "upon terms and conditions",
    "upon such terms and conditions",
    "after notice and hearing",
    "after notice and opportunity for hearing",
    "subject only to",
    "subject, however, to",
    "subject however to",
    "subject to terms and conditions",
    "subject to such terms and conditions",
    "subject to the terms and conditions",
    "subject to subsection",
    "subject to subsections",
    "subject to section",
    "subject to paragraph",
    "subject to paragraphs",
    "subject to subparagraph",
    "subject to subparagraphs",
    "subject to chapter",
    "subject to this section",
    "subject to this chapter",
    "subject to this title",
    "insofar as",
    "insofar as practicable",
)
_PURPOSE_SCOPE_PHRASES = (
    "for purposes of",
    "for the purposes of",
)
_STATUTORY_SCOPE_REFERENCE_PHRASES = (
    "as provided by",
    "as provided in",
    "in accordance with",
    "of this chapter",
    "of this division",
    "of this paragraph",
    "of this part",
    "of this section",
    "of this subchapter",
    "of this subparagraph",
    "of this subpart",
    "of this subsection",
    "of this subtitle",
    "of this title",
    "pursuant to",
    "under section",
    "under this chapter",
    "under this division",
    "under this part",
    "under this section",
    "under this subchapter",
    "under this subpart",
    "under this subtitle",
    "under this title",
    "under subsection",
    "under subsections",
    "under paragraph",
    "under paragraphs",
    "under subparagraph",
    "under subparagraphs",
    "under subparts",
)
_CONDITIONAL_SCOPE_TOKENS = frozenset(
    {
        "notwithstanding",
        "pursuant",
    }
)
_ALETHIC_SCOPE_TOKENS = frozenset(
    {
        "cannot",
        "impossible",
        "necessary",
        "necessarily",
        "possible",
        "unable",
    }
)
_ALETHIC_SCOPE_PHRASES = (
    "impossible to",
    "it is impossible",
    "it is necessary",
    "it is possible",
    "necessary to",
    "not possible",
    "unable to",
)
_NON_ALETHIC_POSSIBLE_SCOPE_PREFIXES = (
    "as far as",
    "to the extent",
)
_TEMPORAL_SCOPE_TOKENS = frozenset(
    {
        "after",
        "annual",
        "annually",
        "date",
        "dates",
        "calendar",
        "before",
        "daily",
        "day",
        "deadline",
        "during",
        "effective",
        "expiration",
        "expire",
        "expires",
        "expiring",
        "fiscal",
        "hour",
        "hours",
        "immediately",
        "later",
        "minute",
        "minutes",
        "month",
        "monthly",
        "monday",
        "pending",
        "promptly",
        "quarterly",
        "second",
        "seconds",
        "sunday",
        "thursday",
        "thereafter",
        "tuesday",
        "time",
        "times",
        "until",
        "wednesday",
        "week",
        "weekly",
        "within",
        "year",
        "yearly",
    }
)
_TEMPORAL_STRONG_SCOPE_TOKENS = frozenset(
    {
        "annual",
        "annually",
        "dated",
        "effective",
        "enacted",
        "enactment",
        "day",
        "days",
        "deadline",
        "deadlines",
        "expire",
        "expired",
        "expires",
        "expiration",
        "fiscal",
        "hour",
        "hours",
        "midnight",
        "month",
        "months",
        "monday",
        "noon",
        "quarter",
        "quarters",
        "sunday",
        "term",
        "terms",
        "thursday",
        "tuesday",
        "weekly",
        "wednesday",
        "year",
        "years",
        "yearly",
    }
)
_TEMPORAL_STATUS_SCOPE_TOKENS = frozenset(
    {
        "abolished",
        "effective",
        "enacted",
        "enactment",
        "extend",
        "extended",
        "extends",
        "extension",
        "extensions",
        "expire",
        "expired",
        "expires",
        "expiration",
        "repeal",
        "repealed",
        "repealing",
        "repeals",
        "sunset",
        "sunsets",
        "terminated",
        "terminating",
        "termination",
    }
)
_TEMPORAL_SCOPE_PHRASES = (
    "at any time",
    "at such time",
    "at such times",
    "at such times as",
    "at the time",
    "as soon as practicable",
    "beginning on or after",
    "calendar year",
    "during the pendency of",
    "during the period",
    "effective date",
    "effective on",
    "effective on first day",
    "expiration of",
    "for calendar years",
    "for any fiscal year",
    "for each fiscal year",
    "for each succeeding fiscal year",
    "for each subsequent fiscal year",
    "for each calendar year",
    "for each of fiscal years",
    "for each year thereafter",
    "for fiscal years",
    "for the first fiscal year",
    "for the subsequent fiscal year",
    "for that fiscal year",
    "from time to time",
    "for the period beginning",
    "fiscal year",
    "from and after",
    "no earlier than",
    "no later than",
    "not earlier than",
    "not later than",
    "on or after",
    "period beginning on",
    "period ending on",
    "is extended",
    "are extended",
    "extended over",
    "extended to",
    "until expended",
    "available until expended",
    "remain available until expended",
    "date of enactment",
    "on the date of enactment",
    "while pending",
)
_TEMPORAL_EXPENDED_SCOPE_PHRASES = (
    "until expended",
    "available until expended",
    "remain available until expended",
)
_TEMPORAL_FISCAL_SCOPE_PHRASES = (
    "for any fiscal year",
    "for each fiscal year",
    "for each succeeding fiscal year",
    "for each subsequent fiscal year",
    "for each of fiscal years",
    "for fiscal years",
    "for the first fiscal year",
    "for the subsequent fiscal year",
    "for that fiscal year",
    "fiscal year",
)
_TEMPORAL_DEADLINE_CUE_TERMS = frozenset(
    {
        "by",
        "within",
        "no later than",
        "not later than",
    }
)
_EPISTEMIC_SCOPE_TOKENS = frozenset(
    {
        "aware",
        "deem",
        "deemed",
        "deeming",
        "deems",
        "determine",
        "determined",
        "determines",
        "determination",
        "determinations",
        "find",
        "finding",
        "findings",
        "finds",
        "found",
        "knowledge",
        "known",
        "knowingly",
    }
)
_EPISTEMIC_SCOPE_PHRASES = (
    "are deemed",
    "deemed to",
    "deems necessary",
    "finding that",
    "findings that",
    "has reason to believe",
    "has reason to know",
    "is deemed",
    "knowledge of",
    "reason to believe",
    "reasonably believe",
    "reasonably believes",
    "reasonably believed",
    "reasonably believing",
)
_DYNAMIC_SCOPE_TOKENS = frozenset(
    {
        "enforce",
        "enforced",
        "enforcement",
        "enforces",
        "enforcing",
        "file",
        "filed",
        "files",
        "filing",
        "serve",
        "served",
        "serves",
        "service",
        "serving",
        "terminate",
        "terminated",
        "terminates",
        "terminating",
        "termination",
        "transfer",
        "transferred",
        "transferring",
        "transfers",
    }
)
_DYNAMIC_SCOPE_PHRASES = (
    "after filing",
    "after service",
    "after transfer",
    "transferred to and vested in",
    "upon filing",
    "upon service",
    "upon transfer",
)
_MONTH_NAME_DATE_PATTERN = (
    r"(?:jan(?:uary)?\.?|feb(?:ruary)?\.?|mar(?:ch)?\.?|apr(?:il)?\.?|"
    r"may\.?|jun(?:e)?\.?|jul(?:y)?\.?|aug(?:ust)?\.?|sep(?:t(?:ember)?)?\.?|"
    r"oct(?:ober)?\.?|nov(?:ember)?\.?|dec(?:ember)?\.?)"
)
_CALENDAR_DATE_RE = re.compile(
    rf"\b{_MONTH_NAME_DATE_PATTERN}\s+\d{{1,2}}(?:,\s*|\s+)\d{{4}}\b",
    re.IGNORECASE,
)
_MONTH_DAY_RE = re.compile(
    rf"\b{_MONTH_NAME_DATE_PATTERN}\s+\d{{1,2}}(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_SECTION_DEFINED_SCOPE_RE = re.compile(
    r"\b(?:sec\.|section|§)\s*[0-9A-Za-z().-]+[^.\n]{0,100}\bdefined\b",
    re.IGNORECASE,
)
_VACANT_SECTION_STATUS_RE = re.compile(
    r"(?:\bsec(?:tion)?s?\.?\s+[a-z0-9_.-]+\s*[-.]?\s*|\[\s*§?\s*[a-z0-9_.-]+\s*\.\s*)"
    r"vacant\b|\bvacant\s*\]",
    re.IGNORECASE,
)
_MONTH_NAME_TOKENS = frozenset(
    {
        "jan",
        "jan.",
        "january",
        "january.",
        "feb",
        "feb.",
        "february",
        "february.",
        "mar",
        "mar.",
        "march",
        "march.",
        "apr",
        "apr.",
        "april",
        "april.",
        "may",
        "may.",
        "jun",
        "jun.",
        "june",
        "june.",
        "jul",
        "jul.",
        "july",
        "july.",
        "aug",
        "aug.",
        "august",
        "august.",
        "sep",
        "sep.",
        "sept",
        "sept.",
        "september",
        "september.",
        "oct",
        "oct.",
        "october",
        "october.",
        "nov",
        "nov.",
        "november",
        "november.",
        "dec",
        "dec.",
        "december",
        "december.",
    }
)
_MAY_MONTH_TOKENS = frozenset({"may", "may."})
_TEMPORAL_BY_CONTEXT_TOKENS = frozenset(
    {
        "date",
        "dates",
        "deadline",
        "deadlines",
        "expiration",
        "period",
        "periods",
        "quarter",
        "quarters",
        "term",
        "terms",
        "today",
        "tomorrow",
        "yesterday",
    }
)
_TEMPORAL_BY_PHRASE_RE = re.compile(
    r"^\s+(?:"
    r"\d{1,4}\b|"
    r"(?:the\s+)?(?:end|close|beginning|start|deadline|expiration)\b|"
    r"(?:no|not)\s+later\s+than\b|"
    r"(?:next|following)\b"
    r")",
    re.IGNORECASE,
)
_NON_TEMPORAL_BY_PREFIX_TOKENS = frozenset(
    {
        "the",
        "this",
        "that",
        "these",
        "those",
        "such",
    }
)
_NON_TEMPORAL_BY_CONTEXT_TOKENS = frozenset(
    {
        "act",
        "article",
        "chapter",
        "clause",
        "code",
        "division",
        "paragraph",
        "part",
        "rule",
        "rules",
        "section",
        "sections",
        "statute",
        "subchapter",
        "subparagraph",
        "subpart",
        "subsection",
        "subtitle",
        "title",
    }
)
_NON_TEMPORAL_BY_PHRASE_RE = re.compile(
    r"^\s+(?:(?:the|this|that|these|those|such)\s+)?(?:"
    r"act|article|chapter|clause|code|division|paragraph|part|rule|rules|section|sections|"
    r"statute|subchapter|subparagraph|subpart|subsection|subtitle|title"
    r")\b",
    re.IGNORECASE,
)
_TEMPORAL_WITHIN_PHRASE_RE = re.compile(
    rf"^\s+(?:"
    rf"\d{{1,4}}\b|"
    rf"(?:a|an)\s+(?:day|days|month|months|year|years|week|weeks|hour|hours)\b|"
    rf"(?:the\s+)?(?:end|close|beginning|start|deadline|expiration)\b|"
    rf"(?:next|following)\b|"
    rf"{_MONTH_NAME_DATE_PATTERN}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,\s*\d{{4}}|\s+\d{{4}})?"
    rf")",
    re.IGNORECASE,
)
_NON_TEMPORAL_WITHIN_PREFIX_TOKENS = frozenset(
    {
        "the",
        "this",
        "that",
        "these",
        "those",
        "such",
        "its",
        "their",
        "our",
    }
)
_NON_TEMPORAL_WITHIN_CONTEXT_TOKENS = frozenset(
    {
        "agency",
        "authority",
        "boundaries",
        "chapter",
        "control",
        "custody",
        "department",
        "district",
        "jurisdiction",
        "limits",
        "meaning",
        "office",
        "paragraph",
        "possession",
        "scope",
        "section",
        "state",
        "states",
        "subchapter",
        "subparagraph",
        "subsection",
        "supervision",
        "territory",
        "title",
        "united",
    }
)
_NON_TEMPORAL_WITHIN_PHRASE_RE = re.compile(
    r"^\s+(?:the\s+)?(?:"
    r"agency|authority|boundaries|chapter|control|custody|department|district|"
    r"jurisdiction|limits|meaning|office|paragraph|possession|scope|section|"
    r"state|states|subchapter|subparagraph|subsection|supervision|territory|"
    r"title|united\s+states"
    r")\b",
    re.IGNORECASE,
)
_NON_TEMPORAL_FOLLOWING_PREFIX_TOKENS = frozenset(
    {"the", "these", "those", "such"}
)
_NON_TEMPORAL_AFTER_PREFIX_TOKENS = frozenset(
    {"the", "this", "that", "these", "those", "such"}
)
_NON_TEMPORAL_AFTER_CONTEXT_TOKENS = frozenset(
    {
        "application",
        "applications",
        "article",
        "chapter",
        "clause",
        "codification",
        "division",
        "editorial",
        "hearing",
        "note",
        "notice",
        "notes",
        "paragraph",
        "part",
        "provision",
        "provisions",
        "reclassification",
        "renumbering",
        "revision",
        "section",
        "subchapter",
        "subclause",
        "subparagraph",
        "subpart",
        "subsection",
        "subtitle",
        "title",
    }
)
_NON_TEMPORAL_AFTER_PHRASE_RE = re.compile(
    r"^\s+(?:the\s+)?(?:"
    r"application|applications|article|chapter|clause|codification|division|editorial|hearing|note|notice|notes|paragraph|"
    r"part|provision|provisions|reclassification|renumbering|revision|section|"
    r"subchapter|subclause|subparagraph|subpart|subsection|subtitle|title"
    r")\b",
    re.IGNORECASE,
)
_NON_TEMPORAL_PROCEDURAL_AFTER_CUES = frozenset(
    {
        "after notice and hearing",
        "after notice and opportunity for hearing",
    }
)
_FRAME_CONTEXT_TOKENS = frozenset(
    {
        "administrator",
        "agency",
        "attorney",
        "authority",
        "board",
        "bureau",
        "classified",
        "classification",
        "codification",
        "commission",
        "committee",
        "committees",
        "congress",
        "court",
        "department",
        "director",
        "editorial",
        "former",
        "formerly",
        "historical",
        "house",
        "intelligence",
        "judge",
        "jurisdiction",
        "justice",
        "officer",
        "omitted",
        "reclassified",
        "repealed",
        "representatives",
        "renumbered",
        "revision",
        "reserved",
        "senate",
        "secretary",
        "terminated",
        "transferred",
        "vacant",
    }
)
_FRAME_SCOPE_PHRASES = (
    "codification section",
    "editorial notes",
    "editorially reclassified",
    "former section",
    "formerly classified",
    "historical and revision notes",
    "prior to editorial reclassification",
    "prior to editorial reclassification and renumbering",
    "reclassified as section",
    "renumbered",
    "repealed",
    "reserved",
    "transferred",
    "transferred to section",
    "was formerly classified",
)
_FRAME_STRUCTURAL_AUTHORITY_SCOPE_PHRASES = (
    "authority of executive agencies",
    "authority to",
    "exclusive authority to",
    "have jurisdiction to",
    "have power to",
    "legislative authority to",
    "powers of authorities",
    "powers of such authority",
    "shall have jurisdiction to",
    "shall have power to",
    "authorized and directed to",
    "authorized and empowered",
    "is authorized and directed to",
    "is authorized and empowered",
)
_FRAME_EDITORIAL_SCOPE_PHRASES = (
    "codification section",
    "editorial notes",
    "historical and revision notes",
    "formerly classified",
    "was formerly classified",
    "prior to editorial reclassification",
    "prior to editorial reclassification and renumbering",
    "reclassified as section",
    "transferred to section",
)
_FRAME_PROCEDURAL_SCOPE_PHRASES = (
    "administrative notice and hearing",
    "administrative notice and hearing procedures",
    "notice and hearing procedures",
    "notice and hearing requirements",
    "administrative review procedures",
)
_GENERIC_FRAME_CUE_TERMS = frozenset(
    {
        "administered by",
        "authority",
        "authority of",
        "authority under",
        "board of directors",
        "class of licensed facilities",
        "corporation",
        "director or officer",
        "does not apply",
        "is a",
        "jurisdiction",
        "licensed facility",
        "mechanisms to evaluate",
        "part of",
        "this chapter applies",
    }
)
_STATUTORY_STRUCTURAL_FRAME_CUE_TERMS = frozenset(
    {
        "authority of",
        "authority under",
        "board of directors",
        "class of licensed facilities",
        "corporation",
        "director or officer",
        "does not apply",
        "licensed facility",
        "mechanisms to evaluate",
        "this chapter applies",
    }
)
_STATUTORY_STRUCTURAL_FRAME_CUE_WEIGHT = 0.5
_STATUTORY_STRUCTURAL_FRAME_CUE_MAX = 3.0
_GENERIC_FRAME_DEBIASED_LOGIT_BASE = 0.5
_GENERIC_FRAME_CUE_DEBIAS_FACTOR = 0.2
_GENERIC_FRAME_STRUCTURAL_BONUS_DEBIAS_FACTOR = 0.25
_GENERIC_FRAME_PRESENT_CUE_SCOPE_BONUS_FACTOR = 0.35
_GENERIC_FRAME_NORMATIVE_SCOPE_SOFT_CAP = 1.0
_DEONTIC_COMPETING_SCOPE_SOFT_CAP = 3.0
_DEONTIC_STRONG_COMPETING_SCOPE_SOFT_CAP = 2.5
_TEMPORAL_COMPETING_SCOPE_SOFT_CAP = 3.0
_TEMPORAL_STRONG_COMPETING_SCOPE_SOFT_CAP = 2.5
_TEMPORAL_MULTI_COMPETING_SCOPE_SOFT_CAP = 2.25
_CONDITIONAL_COMPETING_SCOPE_SOFT_CAP = 3.0
_CONDITIONAL_STRONG_DEONTIC_COMPETING_SCOPE_SOFT_CAP = 2.0
_CONDITIONAL_STRONG_EPISTEMIC_COMPETING_SCOPE_SOFT_CAP = 2.1
_FRAME_COMPETING_SCOPE_SOFT_CAP = 3.0
_FRAME_STRONG_COMPETING_SCOPE_SOFT_CAP = 2.5
_DYNAMIC_COMPETING_SCOPE_SOFT_CAP = 2.5
_DYNAMIC_STRONG_COMPETING_SCOPE_SOFT_CAP = 2.0
_ALETHIC_COMPETING_SCOPE_SOFT_CAP = 2.0
_GENERIC_FRAME_SCOPE_BACKFILL_WEIGHT = 0.12
_GENERIC_FRAME_STRONG_TEMPORAL_SCOPE_BACKFILL_WEIGHT = 0.35
_COMPETING_SCOPE_BACKFILL_WEIGHT = 0.12
_STRONG_SCOPE_BACKFILL_WEIGHT = 0.26
_DEONTIC_CONDITIONAL_SCOPE_BACKFILL_TRIGGER = 3.0
_TEMPORAL_DEONTIC_SCOPE_BACKFILL_TRIGGER = 2.5
_CONDITIONAL_DEONTIC_SCOPE_BACKFILL_TRIGGER = 2.0
_CONDITIONAL_TEMPORAL_SCOPE_BACKFILL_TRIGGER = 2.0
_CONDITIONAL_DYNAMIC_SCOPE_BACKFILL_TRIGGER = 2.0
_DEONTIC_TEMPORAL_SCOPE_BACKFILL_TRIGGER = 2.5
_DEONTIC_EPISTEMIC_SCOPE_BACKFILL_TRIGGER = 2.0
_DEONTIC_DYNAMIC_SCOPE_BACKFILL_TRIGGER = 2.5
_DYNAMIC_TEMPORAL_SCOPE_BACKFILL_TRIGGER = 1.0
_CONDITIONAL_FRAME_SCOPE_BACKFILL_TRIGGER = 2.0
_FRAME_DEONTIC_SCOPE_BACKFILL_TRIGGER = 0.35
_FRAME_TEMPORAL_SCOPE_BACKFILL_TRIGGER = 0.35
_FRAME_CONDITIONAL_SCOPE_BACKFILL_TRIGGER = 0.35
_FRAME_EPISTEMIC_SCOPE_BACKFILL_TRIGGER = 0.5
_FRAME_ALETHIC_SCOPE_BACKFILL_TRIGGER = 0.35
_FRAME_DYNAMIC_SCOPE_BACKFILL_TRIGGER = 0.5
_ALETHIC_CONDITIONAL_SCOPE_BACKFILL_TRIGGER = 0.5
_ALETHIC_EPISTEMIC_SCOPE_BACKFILL_TRIGGER = 0.5
_ALETHIC_DEONTIC_SCOPE_BACKFILL_TRIGGER = 0.5
_EPISTEMIC_TEMPORAL_SCOPE_BACKFILL_TRIGGER = 0.5
_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_TRIGGER = 0.2
_TEMPORAL_CONDITIONAL_SCOPE_BACKFILL_TRIGGER = 2.5
_TEMPORAL_FRAME_SCOPE_BACKFILL_TRIGGER = 3.0
_TEMPORAL_EPISTEMIC_SCOPE_BACKFILL_TRIGGER = 3.0
_TEMPORAL_ALETHIC_SCOPE_BACKFILL_TRIGGER = 3.0
_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT = 0.35
_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT = 0.18
_STATUTORY_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT = 0.35
_STATUTORY_FRAME_DEONTIC_SCOPE_BACKFILL_WEIGHT = 0.45
_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO = 0.9
_STATUTORY_GENERIC_FRAME_STRONG_COMPETING_SCOPE_RATIO = 1.05
_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_MAX = 0.62
_STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX = 0.78
_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX = 0.62
_STATUTORY_GENERIC_FRAME_EPISTEMIC_SCOPE_MAX = 0.45
_STATUTORY_GENERIC_FRAME_STRONG_TEMPORAL_SCOPE_MAX = 0.72
_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO = 0.25
_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX = 0.62
_TEMPORAL_TO_FRAME_STRONG_SCOPE_BACKFILL_MAX = 0.62
_TEMPORAL_TO_DEONTIC_STRONG_SCOPE_BACKFILL_MAX = 1.0
_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO = 0.2
_DEONTIC_COMPETING_SCOPE_BACKFILL_MAX = 0.45
_DYNAMIC_COMPETING_SCOPE_BACKFILL_RATIO = 0.2
_DYNAMIC_COMPETING_SCOPE_BACKFILL_MAX = 0.45
_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX = 0.72
_FRAME_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_WEIGHT = 0.45
_LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT = 1.0
_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO = 0.45
_FRAME_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX = 1.25
_FRAME_TO_TEMPORAL_SCOPE_REINFORCEMENT_MAX = 1.35
_FRAME_TO_CONDITIONAL_SCOPE_REINFORCEMENT_MAX = 1.35
_TEMPORAL_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX = 1.35
_EPISTEMIC_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX = 1.35
_TEMPORAL_TO_CONDITIONAL_SCOPE_REINFORCEMENT_MAX = 1.35
_TEMPORAL_TO_FRAME_SCOPE_REINFORCEMENT_MAX = 1.25
_TEMPORAL_TO_EPISTEMIC_SCOPE_REINFORCEMENT_MAX = 1.2
_TEMPORAL_TO_ALETHIC_SCOPE_REINFORCEMENT_MAX = 1.2
_TEMPORAL_EPISTEMIC_SCOPE_REINFORCEMENT_TRIGGER = 2.0
_TEMPORAL_ALETHIC_SCOPE_REINFORCEMENT_TRIGGER = 2.0
_DEONTIC_SCOPE_PHRASE_REINFORCEMENT = 0.35
_TEMPORAL_SCOPE_PHRASE_REINFORCEMENT = 0.35
_DEONTIC_SCOPE_TOKENS = frozenset(
    {
        "allow",
        "allowed",
        "authorize",
        "authorized",
        "compliance",
        "comply",
        "duty",
        "duties",
        "fine",
        "fined",
        "fines",
        "imprison",
        "imprisoned",
        "imprisonment",
        "liabilities",
        "liable",
        "liability",
        "mandatory",
        "noncompliance",
        "obligation",
        "obligations",
        "offense",
        "offenses",
        "penalty",
        "penalties",
        "permit",
        "permitted",
        "prohibition",
        "prohibitions",
        "prohibited",
        "require",
        "required",
        "requires",
        "requirement",
        "requirements",
        "shall",
        "unlawful",
        "violate",
        "violated",
        "violation",
        "violations",
    }
)
_DEONTIC_REQUIRED_ONLY_SCOPE_TOKENS = frozenset(
    {
        "require",
        "required",
        "requires",
        "requirement",
        "requirements",
    }
)
_NON_DEONTIC_REQUIRED_CONTEXT_RE = re.compile(
    r"\b(?:codification|editorial|historical|reclassified|renumbered|repealed|transferred|formerly)\b",
    re.IGNORECASE,
)
_DEONTIC_SCOPE_PHRASES = (
    "authorization of appropriations",
    "authorized to be appropriated",
    "are authorized to be appropriated",
    "is authorized to be appropriated",
    "there are authorized to be appropriated",
    "it is the policy of",
    "it shall be the policy of",
    "is guilty of",
    "is entitled to",
    "has a duty to",
    "have a duty to",
    "duty of",
    "liability for",
    "powers and duties",
    "powers or duties",
    "prohibition of",
    "prohibition on",
    "requirement that",
    "requirements for",
    "is liable for",
    "shall issue",
    "shall be entitled to",
    "shall be fined",
    "shall be imprisoned",
    "shall continue in office",
    "shall continue in said office",
    "shall continue in such office",
    "is prohibited from",
    "is required to",
    "subject to a civil penalty",
    "subject to civil penalties",
    "subject to criminal penalties",
    "subject to imprisonment",
    "under an obligation to",
)
_DEONTIC_APPROPRIATIONS_SCOPE_PHRASES = (
    "authorization of appropriations",
    "authorized to be appropriated",
    "are authorized to be appropriated",
    "is authorized to be appropriated",
    "there are authorized to be appropriated",
)
_DEONTIC_AUTHORIZATION_SCOPE_PHRASES = (
    "there is authorized to be appropriated",
    "is authorized to be appropriated",
    "are authorized to be appropriated",
    "authorized to be appropriated",
)
_DEONTIC_CORPORATE_POWERS_SCOPE_PHRASES = (
    "powers the corporation may",
    "the corporation may",
)
_DEONTIC_REPORT_DUTY_SCOPE_PHRASES = (
    "shall submit",
    "report shall be submitted",
)
_DEONTIC_CITATION_AUTHORITY_SCOPE_PHRASES = (
    "may be cited",
)


@dataclass(frozen=True)
class SpaCyTokenFeature:
    """Stable token-level features extracted from a spaCy `Doc`."""

    text: str
    lemma: str
    lower: str
    pos: str
    dep: str
    start_char: int
    end_char: int
    is_stop: bool = False
    is_alpha: bool = False

    def normalized(self) -> str:
        return self.lemma or self.lower or self.text.lower()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dep": self.dep,
            "end_char": self.end_char,
            "is_alpha": self.is_alpha,
            "is_stop": self.is_stop,
            "lemma": self.lemma,
            "lower": self.lower,
            "pos": self.pos,
            "start_char": self.start_char,
            "text": self.text,
        }


@dataclass(frozen=True)
class SpaCySentenceFeature:
    """Sentence span features independent of a live spaCy object."""

    text: str
    start_char: int
    end_char: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "end_char": self.end_char,
            "start_char": self.start_char,
            "text": self.text,
        }


@dataclass(frozen=True)
class SpaCyModalCueFeature:
    """One modal cue matched in encoded text."""

    family: str
    system: str
    symbol: str
    label: str
    cue: str
    start_char: int
    end_char: int
    token_indices: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cue": self.cue,
            "end_char": self.end_char,
            "family": self.family,
            "label": self.label,
            "start_char": self.start_char,
            "symbol": self.symbol,
            "system": self.system,
            "token_indices": list(self.token_indices),
        }


@dataclass(frozen=True)
class SpaCyLegalEncoding:
    """Serializable spaCy-derived intermediate encoding for one legal text."""

    document_id: str
    text: str
    normalized_text: str
    tokens: List[SpaCyTokenFeature]
    sentences: List[SpaCySentenceFeature]
    cues: List[SpaCyModalCueFeature]
    citation: Optional[str] = None
    source: str = "legal_text"
    model_name: str = ""
    used_fallback_model: bool = False

    def modal_family_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for cue in self.cues:
            counts[cue.family] = counts.get(cue.family, 0) + 1
        return dict(sorted(counts.items()))

    def ranked_modal_families(self) -> List[Dict[str, float]]:
        """Return cue-count ranking with stable ordering and share ratios."""
        return ranked_modal_families(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "citation": self.citation,
            "cues": [cue.to_dict() for cue in self.cues],
            "document_id": self.document_id,
            "modal_family_counts": self.modal_family_counts(),
            "model_name": self.model_name,
            "normalized_text": self.normalized_text,
            "sentences": [sentence.to_dict() for sentence in self.sentences],
            "source": self.source,
            "text": self.text,
            "tokens": [token.to_dict() for token in self.tokens],
            "used_fallback_model": self.used_fallback_model,
        }


class SpaCyLegalEncoder:
    """Encode legal text using spaCy tokens plus deterministic modal cues."""

    def __init__(
        self,
        *,
        model_name: str = "en_core_web_sm",
        registry: ModalRegistry = DEFAULT_MODAL_REGISTRY,
    ) -> None:
        self.model_name = model_name
        self.registry = registry
        self.nlp, self.used_fallback_model = self._load_nlp(model_name)

    def encode(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "legal_text",
    ) -> SpaCyLegalEncoding:
        normalized = _normalize(text)
        resolved_document_id = document_id or _document_id(normalized)
        doc = self.nlp(normalized)
        tokens = [
            SpaCyTokenFeature(
                text=token.text,
                lemma=(token.lemma_ or token.lower_).lower(),
                lower=token.lower_,
                pos=token.pos_,
                dep=token.dep_,
                start_char=token.idx,
                end_char=token.idx + len(token.text),
                is_stop=bool(token.is_stop),
                is_alpha=bool(token.is_alpha),
            )
            for token in doc
        ]
        sentences = [
            SpaCySentenceFeature(
                text=sent.text,
                start_char=sent.start_char,
                end_char=sent.end_char,
            )
            for sent in doc.sents
        ]
        if not sentences and normalized:
            sentences = [SpaCySentenceFeature(text=normalized, start_char=0, end_char=len(normalized))]
        return SpaCyLegalEncoding(
            document_id=resolved_document_id,
            text=text,
            normalized_text=normalized,
            tokens=tokens,
            sentences=sentences,
            cues=self._extract_cues(normalized, tokens),
            citation=citation,
            source=source,
            model_name=self.model_name,
            used_fallback_model=self.used_fallback_model,
        )

    def _extract_cues(
        self,
        normalized: str,
        tokens: Sequence[SpaCyTokenFeature],
    ) -> List[SpaCyModalCueFeature]:
        found: Dict[tuple[int, int, str, str], SpaCyModalCueFeature] = {}
        token_spans = [(index, token.start_char, token.end_char) for index, token in enumerate(tokens)]
        for profile in self.registry.all_profiles():
            for operator in profile.operators:
                for cue in sorted(operator.cue_terms, key=lambda value: (-len(value), value)):
                    pattern = re.compile(rf"(?<!\w){re.escape(cue)}(?!\w)", re.IGNORECASE)
                    for match in pattern.finditer(normalized):
                        if self._is_calendar_month_may_cue(
                            normalized_text=normalized,
                            cue=cue,
                            start_char=match.start(),
                            end_char=match.end(),
                        ):
                            continue
                        if (
                            profile.family == ModalLogicFamily.ALETHIC
                            and cue.lower() == "possible"
                            and self._is_non_alethic_possible_cue(
                                normalized_text=normalized,
                                start_char=match.start(),
                            )
                        ):
                            continue
                        if (
                            profile.family == ModalLogicFamily.DEONTIC
                            and cue.lower() == "required"
                            and self._is_non_deontic_required_cue(
                                normalized_text=normalized,
                                start_char=match.start(),
                                end_char=match.end(),
                            )
                        ):
                            continue
                        if profile.family == ModalLogicFamily.TEMPORAL:
                            lowered_cue = cue.lower()
                            if lowered_cue in _NON_TEMPORAL_PROCEDURAL_AFTER_CUES:
                                continue
                            if (
                                lowered_cue == "by"
                                and not self._is_temporal_deadline_by_cue(
                                    normalized_text=normalized,
                                    tokens=tokens,
                                    start_char=match.start(),
                                    end_char=match.end(),
                                )
                            ):
                                continue
                            if (
                                lowered_cue == "within"
                                and not self._is_temporal_duration_within_cue(
                                    normalized_text=normalized,
                                    tokens=tokens,
                                    start_char=match.start(),
                                    end_char=match.end(),
                                )
                            ):
                                continue
                            if (
                                lowered_cue == "following"
                                and self._is_non_temporal_following_cue(
                                    normalized_text=normalized,
                                    tokens=tokens,
                                    start_char=match.start(),
                                    end_char=match.end(),
                                )
                            ):
                                continue
                            if (
                                lowered_cue == "after"
                                and not self._is_temporal_sequence_after_cue(
                                    normalized_text=normalized,
                                    tokens=tokens,
                                    start_char=match.start(),
                                    end_char=match.end(),
                                )
                            ):
                                continue
                        token_indices = [
                            index
                            for index, start, end in token_spans
                            if start < match.end() and end > match.start()
                        ]
                        key = (match.start(), match.end(), profile.family.value, operator.symbol)
                        found[key] = self._cue_feature(
                            profile,
                            operator,
                            cue,
                            match.start(),
                            match.end(),
                            token_indices,
                        )
        return sorted(
            found.values(),
            key=lambda cue: (cue.start_char, cue.end_char, cue.family, cue.symbol, cue.cue),
        )

    def _is_calendar_month_may_cue(
        self,
        *,
        normalized_text: str,
        cue: str,
        start_char: int,
        end_char: int,
    ) -> bool:
        """Treat `May 13, 2002` date literals as temporal context, not deontic permission."""
        if cue.lower() != "may":
            return False
        if start_char > 0 and normalized_text[start_char - 1].isalnum():
            return False
        trailing = normalized_text[end_char:]
        return bool(re.match(r"^\s+\d{1,2}(?:,\s*|\s+)\d{4}\b", trailing))

    def _is_non_alethic_possible_cue(
        self,
        *,
        normalized_text: str,
        start_char: int,
    ) -> bool:
        """Treat qualified effort phrases as deontic scope, not alethic possibility."""
        leading_window = normalized_text[max(0, start_char - 48) : start_char].lower()
        for prefix in _NON_ALETHIC_POSSIBLE_SCOPE_PREFIXES:
            if re.search(rf"{re.escape(prefix)}\s+$", leading_window):
                return True
        return False

    def _is_non_deontic_required_cue(
        self,
        *,
        normalized_text: str,
        start_char: int,
        end_char: int,
    ) -> bool:
        """Treat bare `required` as non-deontic in editorial/status contexts."""
        trailing = normalized_text[end_char : end_char + 24]
        if re.match(r"^\s+to\b", trailing, re.IGNORECASE):
            return False
        context_window = normalized_text[
            max(0, start_char - 96) : min(len(normalized_text), end_char + 96)
        ].lower()
        if _contains_scope_phrase(context_window, _FRAME_EDITORIAL_SCOPE_PHRASES):
            return True
        return bool(_NON_DEONTIC_REQUIRED_CONTEXT_RE.search(context_window))

    def _is_temporal_deadline_by_cue(
        self,
        *,
        normalized_text: str,
        tokens: Sequence[SpaCyTokenFeature],
        start_char: int,
        end_char: int,
    ) -> bool:
        """Treat temporal `by` as a deadline cue only when local context is time-like."""
        trailing = normalized_text[end_char : end_char + 64]
        if _NON_TEMPORAL_BY_PHRASE_RE.match(trailing):
            return False
        if _TEMPORAL_BY_PHRASE_RE.match(trailing):
            return True
        # Only treat immediate month/date literals as deadline context.
        # This avoids citation-tail false positives like "(Pub. L. ..., Aug. 3, 1977)".
        if _CALENDAR_DATE_RE.match(trailing):
            return True
        if _MONTH_DAY_RE.match(trailing):
            return True
        lookahead = _lookahead_tokens(tokens, end_char, limit=4)
        if not lookahead:
            return False
        first = lookahead[0].normalized().lower()
        second = lookahead[1].normalized().lower() if len(lookahead) > 1 else ""
        if first in _NON_TEMPORAL_BY_CONTEXT_TOKENS:
            return False
        if (
            first in _NON_TEMPORAL_BY_PREFIX_TOKENS
            and second in _NON_TEMPORAL_BY_CONTEXT_TOKENS
        ):
            return False
        for index, token in enumerate(lookahead):
            normalized = token.normalized().lower()
            if normalized in _NON_TEMPORAL_BY_CONTEXT_TOKENS:
                return False
            if normalized in _TEMPORAL_SCOPE_TOKENS:
                return True
            if normalized in _TEMPORAL_BY_CONTEXT_TOKENS:
                return True
            if normalized in _MONTH_NAME_TOKENS:
                if normalized in _MAY_MONTH_TOKENS:
                    if index + 1 >= len(lookahead):
                        continue
                    next_token = lookahead[index + 1]
                    next_normalized = next_token.normalized().lower()
                    if (
                        re.fullmatch(r"\d{1,2}(?:st|nd|rd|th)?", next_normalized)
                        or re.fullmatch(r"\d{4}", next_normalized)
                    ):
                        return True
                    continue
                return True
            if re.fullmatch(r"\d{1,4}", token.text):
                previous = (
                    lookahead[index - 1].normalized().lower()
                    if index > 0
                    else ""
                )
                if previous in _NON_TEMPORAL_BY_CONTEXT_TOKENS:
                    continue
                return True
        return False

    def _is_temporal_duration_within_cue(
        self,
        *,
        normalized_text: str,
        tokens: Sequence[SpaCyTokenFeature],
        start_char: int,
        end_char: int,
    ) -> bool:
        """Treat temporal `within` as a deadline cue only when local context is time-like."""
        return _is_temporal_duration_within_context(
            normalized_text=normalized_text,
            tokens=tokens,
            start_char=start_char,
            end_char=end_char,
        )

    def _is_non_temporal_following_cue(
        self,
        *,
        normalized_text: str,
        tokens: Sequence[SpaCyTokenFeature],
        start_char: int,
        end_char: int,
    ) -> bool:
        """Treat list-introducing `the following` as non-temporal context."""
        preceding: Optional[SpaCyTokenFeature] = None
        lookahead = _lookahead_tokens(tokens, end_char, limit=3)
        for token in tokens:
            if token.end_char <= start_char:
                preceding = token
                continue
            break
        if lookahead:
            first = lookahead[0].normalized().lower()
            second = lookahead[1].normalized().lower() if len(lookahead) > 1 else ""
            if first in _NON_TEMPORAL_WITHIN_CONTEXT_TOKENS:
                return True
            if (
                first in _NON_TEMPORAL_WITHIN_PREFIX_TOKENS
                and second in _NON_TEMPORAL_WITHIN_CONTEXT_TOKENS
            ):
                return True
        if preceding is None:
            return False
        preceding_normalized = preceding.normalized().lower()
        if preceding_normalized not in _NON_TEMPORAL_FOLLOWING_PREFIX_TOKENS:
            return False
        if lookahead:
            next_token = lookahead[0]
            next_normalized = next_token.normalized().lower()
            if (
                next_normalized in _TEMPORAL_SCOPE_TOKENS
                or next_normalized in _MONTH_NAME_TOKENS
                or re.fullmatch(r"\d{1,4}", next_token.text)
            ):
                return False
        trailing = normalized_text[end_char : end_char + 48]
        if re.match(r"^\s*[:;,(\[]", trailing):
            return True
        if re.match(
            r"^\s+(?:is|are|shall|must|may|include|includes|apply|applies|as)\b",
            trailing,
            re.IGNORECASE,
        ):
            return True
        return False

    def _is_temporal_sequence_after_cue(
        self,
        *,
        normalized_text: str,
        tokens: Sequence[SpaCyTokenFeature],
        start_char: int,
        end_char: int,
    ) -> bool:
        """Treat `after` as temporal only when local context is time-like."""
        trailing = normalized_text[end_char : end_char + 80]
        if _CALENDAR_DATE_RE.search(trailing):
            return True
        if _MONTH_DAY_RE.search(trailing):
            return True
        lookahead = _lookahead_tokens(tokens, end_char, limit=4)
        for token in lookahead:
            normalized = token.normalized().lower()
            if normalized in _TEMPORAL_BY_CONTEXT_TOKENS:
                return True
            if normalized in _MONTH_NAME_TOKENS:
                return True
            if normalized in (_TEMPORAL_SCOPE_TOKENS - {"after"}):
                return True
            if re.fullmatch(r"\d{1,4}", token.text):
                return True
        if not lookahead:
            return False
        first = lookahead[0].normalized().lower()
        second = lookahead[1].normalized().lower() if len(lookahead) > 1 else ""
        if first in _NON_TEMPORAL_AFTER_CONTEXT_TOKENS:
            return False
        if (
            first in _NON_TEMPORAL_AFTER_PREFIX_TOKENS
            and second in _NON_TEMPORAL_AFTER_CONTEXT_TOKENS
        ):
            return False
        if _NON_TEMPORAL_AFTER_PHRASE_RE.match(trailing):
            return False
        return True

    def _cue_feature(
        self,
        profile: ModalParseProfile,
        operator: ModalOperatorSpec,
        cue: str,
        start_char: int,
        end_char: int,
        token_indices: Sequence[int],
    ) -> SpaCyModalCueFeature:
        return SpaCyModalCueFeature(
            family=profile.family.value,
            system=profile.system.value,
            symbol=operator.symbol,
            label=operator.aliases[0] if operator.aliases else operator.symbol,
            cue=cue,
            start_char=start_char,
            end_char=end_char,
            token_indices=list(token_indices),
        )

    def _load_nlp(self, model_name: str):
        try:
            import spacy
        except ImportError as exc:  # pragma: no cover - dependency is present in supported envs
            raise RuntimeError("spaCy is required for SpaCyLegalEncoder") from exc
        try:
            nlp = spacy.load(model_name)
            used_fallback = False
        except OSError:
            nlp = spacy.blank("en")
            used_fallback = True
        if "sentencizer" not in nlp.pipe_names:
            nlp.add_pipe("sentencizer")
        return nlp, used_fallback


class SpaCyModalIRCompiler:
    """Compile spaCy legal encodings into canonical modal IR documents."""

    def __init__(self, *, parser: Optional[LegalModalParser] = None) -> None:
        self._fallback_parser = parser or LegalModalParser()

    def compile(self, encoding: SpaCyLegalEncoding) -> ModalIRDocument:
        formulas: List[ModalIRFormula] = []
        for index, cue in enumerate(encoding.cues, start=1):
            sentence = _sentence_for_cue(encoding.sentences, cue)
            tokens = _tokens_for_span(encoding.tokens, sentence.start_char, sentence.end_char)
            predicate = _predicate_from_tokens(tokens, cue)
            conditions, exceptions = _conditions_and_exceptions_from_sentence(
                sentence.text
            )
            formulas.append(
                ModalIRFormula(
                    formula_id=f"{encoding.document_id}:spacy:f{index:04d}",
                    operator=ModalIROperator(
                        family=cue.family,
                        system=cue.system,
                        symbol=cue.symbol,
                        label=cue.label,
                    ),
                    predicate=predicate,
                    provenance=ModalIRProvenance(
                        source_id=encoding.document_id,
                        start_char=sentence.start_char,
                        end_char=sentence.end_char,
                        citation=encoding.citation,
                    ),
                    conditions=conditions,
                    exceptions=exceptions,
                    metadata={
                        "cue": cue.cue,
                        "cue_start_char": cue.start_char,
                        "cue_end_char": cue.end_char,
                        "encoder": "spacy_modal_codec_v1",
                    },
                )
            )
        if encoding.normalized_text:
            def _prefix_formulas(start_index: int) -> List[ModalIRFormula]:
                return self._fallback_parser.modal_heading_prefix_coverage_formulas(
                    document_id=encoding.document_id,
                    text=encoding.normalized_text,
                    citation=encoding.citation,
                    start_index=start_index,
                )

            if not formulas:
                fallback_allow_modal_cues = False
                fallback_formula = self._fallback_parser.fallback_formula(
                    document_id=encoding.document_id,
                    text=encoding.normalized_text,
                    citation=encoding.citation,
                    start_index=1,
                )
                if fallback_formula is None:
                    fallback_allow_modal_cues = True
                    fallback_formula = self._fallback_parser.fallback_formula(
                        document_id=encoding.document_id,
                        text=encoding.normalized_text,
                        citation=encoding.citation,
                        start_index=1,
                        allow_modal_cues=True,
                    )
                if fallback_formula is not None:
                    segments = self._fallback_parser.segment(encoding.normalized_text)
                    residual_segments = self._fallback_parser._segments_excluding_spans(
                        segments,
                        spans=[
                            (
                                int(fallback_formula.provenance.start_char),
                                int(fallback_formula.provenance.end_char),
                            )
                        ],
                    )
                    residual_formulas = self._fallback_parser.residual_span_coverage_formulas(
                        document_id=encoding.document_id,
                        text=encoding.normalized_text,
                        citation=encoding.citation,
                        start_index=1,
                        segments=residual_segments,
                    )
                    formulas.extend(residual_formulas)
                    if residual_formulas:
                        reindexed_fallback = self._fallback_parser.fallback_formula(
                            document_id=encoding.document_id,
                            text=encoding.normalized_text,
                            citation=encoding.citation,
                            start_index=len(formulas) + 1,
                            segments=segments,
                            allow_modal_cues=fallback_allow_modal_cues,
                        )
                        if reindexed_fallback is not None:
                            fallback_formula = reindexed_fallback
                    formulas.extend(_prefix_formulas(len(formulas) + 1))
                    formulas.append(fallback_formula)
                else:
                    formulas.extend(
                        self._fallback_parser.residual_span_coverage_formulas(
                            document_id=encoding.document_id,
                            text=encoding.normalized_text,
                            citation=encoding.citation,
                            start_index=1,
                        )
                    )
            else:
                segments = self._fallback_parser.segment(encoding.normalized_text)
                residual_segments = self._fallback_parser._segments_excluding_spans(
                    segments,
                    spans=[
                        (
                            int(formula.provenance.start_char),
                            int(formula.provenance.end_char),
                        )
                        for formula in formulas
                    ],
                )
                residual_fallback_formula = self._fallback_parser.fallback_formula(
                    document_id=encoding.document_id,
                    text=encoding.normalized_text,
                    citation=encoding.citation,
                    start_index=len(formulas) + 1,
                    segments=residual_segments,
                    allow_modal_cues=True,
                )
                if residual_fallback_formula is not None:
                    residual_segments_after_fallback = self._fallback_parser._segments_excluding_spans(
                        residual_segments,
                        spans=[
                            (
                                int(residual_fallback_formula.provenance.start_char),
                                int(residual_fallback_formula.provenance.end_char),
                            )
                        ],
                    )
                    formulas.extend(
                        self._fallback_parser.residual_span_coverage_formulas(
                            document_id=encoding.document_id,
                            text=encoding.normalized_text,
                            citation=encoding.citation,
                            start_index=len(formulas) + 2,
                            segments=residual_segments_after_fallback,
                        )
                    )
                    formulas.extend(_prefix_formulas(len(formulas) + 1))
                    formulas.append(residual_fallback_formula)
                else:
                    formulas.extend(
                        self._fallback_parser.residual_span_coverage_formulas(
                            document_id=encoding.document_id,
                            text=encoding.normalized_text,
                            citation=encoding.citation,
                            start_index=len(formulas) + 1,
                            segments=residual_segments,
                        )
                    )
                    formulas.extend(_prefix_formulas(len(formulas) + 1))
        return ModalIRDocument(
            document_id=encoding.document_id,
            source=encoding.source,
            normalized_text=encoding.normalized_text,
            formulas=formulas,
            metadata={
                "citation": encoding.citation,
                "deterministic_parser": "spacy_modal_codec_v1",
                "llm_call_count": 0,
                "model_name": encoding.model_name,
                "sentence_count": len(encoding.sentences),
                "token_count": len(encoding.tokens),
                "used_fallback_model": encoding.used_fallback_model,
            },
        )


class SpaCyModalDecoder:
    """Decode spaCy/IR features into deterministic embedding-like vectors."""

    def decode_embedding(self, encoding: SpaCyLegalEncoding, *, dimensions: int = 8) -> List[float]:
        if dimensions < 1:
            raise ValueError("dimensions must be >= 1")
        vector = [0.0 for _ in range(dimensions)]
        for feature in self._feature_stream(encoding):
            slot, value = _feature_hash(feature, dimensions)
            vector[slot] += value
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [round(value / norm, 6) for value in vector]

    def family_logits(
        self,
        encoding: SpaCyLegalEncoding,
        *,
        modal_families: Sequence[str],
    ) -> Dict[str, float]:
        logits = {family: -0.25 for family in modal_families}
        signals = modal_ambiguity_signals(encoding)
        generic_frame_debias_context = _is_generic_frame_cue_debias_context(
            encoding,
            signals,
        )
        raw_counts = encoding.modal_family_counts()
        weighted_counts = _weighted_modal_family_counts(
            encoding,
            signals=signals,
        )
        for family, count in weighted_counts.items():
            if family in logits:
                base_logit = 2.0
                if (
                    family == ModalLogicFamily.FRAME.value
                    and generic_frame_debias_context
                ):
                    base_logit = _GENERIC_FRAME_DEBIASED_LOGIT_BASE
                logits[family] = float(base_logit) + float(count)
        scope_boosts = _scope_signal_family_logit_boosts(signals)
        for family, bonus in scope_boosts.items():
            if family not in logits:
                continue
            if float(raw_counts.get(family, 0.0)) > 0.0:
                if generic_frame_debias_context:
                    logits[family] = float(logits[family]) + (
                        float(bonus) * _GENERIC_FRAME_PRESENT_CUE_SCOPE_BONUS_FACTOR
                    )
                continue
            logits[family] = max(float(logits[family]), 0.25) + float(bonus)
        frame_bonus = _frame_logit_bonus(signals)
        if generic_frame_debias_context:
            frame_bonus = _debias_frame_bonus_for_generic_cues(signals)
        if ModalLogicFamily.FRAME.value in logits and frame_bonus > 0.0:
            logits[ModalLogicFamily.FRAME.value] = (
                max(logits[ModalLogicFamily.FRAME.value], 0.5) + frame_bonus
            )
        if (
            ModalLogicFamily.DEONTIC.value in logits
            and 0.0
            < float(raw_counts.get(ModalLogicFamily.DEONTIC.value, 0.0))
            <= 2.0
            and bool(signals.get("has_deontic_cue"))
            and bool(
                signals.get("has_calendar_date_scope")
                or signals.get("has_temporal_status_scope")
                or signals.get("has_temporal_scope_token")
            )
            and not bool(
                signals.get("has_temporal_cue")
                or (
                    signals.get("has_temporal_scope_phrase")
                    and not signals.get("has_temporal_status_scope")
                )
                or signals.get("has_temporal_within_scope")
                or signals.get("has_temporal_deadline_cue")
            )
            and not bool(signals.get("has_statutory_scope_reference"))
        ):
            logits[ModalLogicFamily.DEONTIC.value] = (
                float(logits[ModalLogicFamily.DEONTIC.value]) + 0.55
            )
        if (
            ModalLogicFamily.TEMPORAL.value in logits
            and bool(signals.get("has_temporal_fiscal_scope_phrase"))
            and bool(signals.get("has_frame_editorial_scope_phrase"))
            and bool(signals.get("has_statutory_scope_reference"))
            and not bool(
                signals.get("has_deontic_scope")
                or signals.get("has_deontic_cue")
            )
            and not _has_explicit_conditional_scope(signals)
        ):
            logits[ModalLogicFamily.TEMPORAL.value] = (
                float(logits[ModalLogicFamily.TEMPORAL.value]) + 0.4
            )
        if not raw_counts and ModalLogicFamily.HYBRID.value in logits:
            if frame_bonus <= 0.0:
                logits[ModalLogicFamily.HYBRID.value] = 1.0
        return logits

    def _feature_stream(self, encoding: SpaCyLegalEncoding) -> Iterable[str]:
        yield f"doclen:{len(encoding.tokens)}"
        for token in encoding.tokens:
            if token.is_alpha and not token.is_stop:
                yield f"lemma:{token.normalized()}"
            if token.pos:
                yield f"pos:{token.pos}"
            if token.dep:
                yield f"dep:{token.dep}"
        for cue in encoding.cues:
            yield f"cue:{cue.family}:{cue.symbol}:{cue.cue.lower()}"
        for family, count in encoding.modal_family_counts().items():
            yield f"family:{family}:{count}"


class SpaCyModalCodec:
    """Convenience facade for encoder -> IR -> vector workflows."""

    def __init__(
        self,
        *,
        encoder: Optional[SpaCyLegalEncoder] = None,
        compiler: Optional[SpaCyModalIRCompiler] = None,
        decoder: Optional[SpaCyModalDecoder] = None,
    ) -> None:
        self.encoder = encoder or SpaCyLegalEncoder()
        self.compiler = compiler or SpaCyModalIRCompiler()
        self.decoder = decoder or SpaCyModalDecoder()

    def encode_sample(self, sample: LegalSample) -> SpaCyLegalEncoding:
        return self.encoder.encode(
            sample.text,
            document_id=sample.sample_id,
            citation=sample.citation,
            source=sample.source,
        )

    def compile_sample_ir(self, sample: LegalSample) -> ModalIRDocument:
        return self.compiler.compile(self.encode_sample(sample))

    def decode_sample_embedding(self, sample: LegalSample, *, dimensions: int) -> List[float]:
        return self.decoder.decode_embedding(self.encode_sample(sample), dimensions=dimensions)

    def family_logits_for_sample(
        self,
        sample: LegalSample,
        *,
        modal_families: Sequence[str],
    ) -> Dict[str, float]:
        return self.decoder.family_logits(
            self.encode_sample(sample),
            modal_families=modal_families,
        )

    def feature_keys_for_sample(self, sample: LegalSample) -> List[str]:
        """Return text-derived features that can receive generalizable SGD updates."""
        encoding = self.encode_sample(sample)
        return _unique_preserve_order(self.decoder._feature_stream(encoding))


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _document_id(normalized: str) -> str:
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"spacy-legal-text-{digest}"


def _feature_hash(feature: str, dimensions: int) -> tuple[int, float]:
    digest = hashlib.sha256(feature.encode("utf-8")).digest()
    slot = int.from_bytes(digest[:4], "big") % dimensions
    sign = 1.0 if digest[4] % 2 == 0 else -1.0
    magnitude = 0.5 + (digest[5] / 255.0)
    return slot, sign * magnitude


def _is_temporal_duration_within_context(
    *,
    normalized_text: str,
    tokens: Sequence[SpaCyTokenFeature],
    start_char: int,
    end_char: int,
) -> bool:
    trailing = normalized_text[end_char : end_char + 80]
    if _TEMPORAL_WITHIN_PHRASE_RE.match(trailing):
        return True
    lookahead = _lookahead_tokens(tokens, end_char, limit=4)
    for token in lookahead:
        normalized = token.normalized().lower()
        if normalized in _TEMPORAL_SCOPE_TOKENS:
            return True
        if normalized in _TEMPORAL_BY_CONTEXT_TOKENS:
            return True
        if normalized in _MONTH_NAME_TOKENS:
            return True
        if re.fullmatch(r"\d{1,4}", token.text):
            return True
    if not lookahead:
        return False
    first = lookahead[0].normalized().lower()
    second = lookahead[1].normalized().lower() if len(lookahead) > 1 else ""
    if (
        first in _NON_TEMPORAL_WITHIN_PREFIX_TOKENS
        and second in _NON_TEMPORAL_WITHIN_CONTEXT_TOKENS
    ):
        return False
    if first in _NON_TEMPORAL_WITHIN_CONTEXT_TOKENS:
        return False
    if _NON_TEMPORAL_WITHIN_PHRASE_RE.match(trailing):
        return False
    return False


def _has_temporal_within_scope(
    normalized_text: str,
    tokens: Sequence[SpaCyTokenFeature],
) -> bool:
    return any(
        token.normalized().lower() == "within"
        and _is_temporal_duration_within_context(
            normalized_text=normalized_text,
            tokens=tokens,
            start_char=token.start_char,
            end_char=token.end_char,
        )
        for token in tokens
    )


def _lookahead_tokens(
    tokens: Sequence[SpaCyTokenFeature],
    end_char: int,
    *,
    limit: int,
) -> List[SpaCyTokenFeature]:
    lookahead: List[SpaCyTokenFeature] = []
    for token in tokens:
        if token.start_char >= end_char:
            lookahead.append(token)
            if len(lookahead) >= limit:
                break
    return lookahead


def ranked_modal_families(encoding: SpaCyLegalEncoding) -> List[Dict[str, float]]:
    """Rank modal families by deterministic cue count and normalized share."""
    counts = encoding.modal_family_counts()
    weighted_counts = _weighted_modal_family_counts(encoding)
    total = sum(float(value) for value in weighted_counts.values())
    if total <= 0:
        return []
    ranking: List[Dict[str, float]] = []
    for family in sorted(
        weighted_counts,
        key=lambda item: (
            -float(weighted_counts.get(item, 0.0)),
            item,
        ),
    ):
        share_raw = float(weighted_counts.get(family, 0.0)) / float(total)
        ranking.append(
            {
                "family": family,
                "count": int(counts.get(family, 0)),
                "share_raw": share_raw,
                "share": round(share_raw, 6),
            }
        )
    return ranking


def _weighted_modal_family_counts(
    encoding: SpaCyLegalEncoding,
    *,
    signals: Optional[Mapping[str, bool]] = None,
) -> Dict[str, float]:
    counts = _overlap_aware_modal_family_counts(encoding)
    resolved_signals: Mapping[str, bool]
    if signals is None:
        resolved_signals = modal_ambiguity_signals(encoding)
    else:
        resolved_signals = signals
    if not counts:
        if bool(resolved_signals.get("has_vacant_section_scope")):
            counts = {ModalLogicFamily.FRAME.value: 1.2}
        else:
            return {}
    has_generic_frame_debias_context = _is_generic_frame_cue_debias_context(
        encoding,
        resolved_signals,
    )
    if has_generic_frame_debias_context:
        frame_family = ModalLogicFamily.FRAME.value
        if frame_family in counts:
            counts[frame_family] *= _GENERIC_FRAME_CUE_DEBIAS_FACTOR
        _apply_generic_frame_normative_scope_soft_cap(
            counts,
            resolved_signals,
        )
        _apply_statutory_structural_frame_cue_reinforcement(
            counts,
            encoding,
            resolved_signals,
        )
        _apply_generic_frame_scope_backfill(
            counts,
            resolved_signals,
        )
    _apply_deontic_competing_scope_soft_cap(
        counts,
        resolved_signals,
    )
    _apply_temporal_competing_scope_soft_cap(
        counts,
        resolved_signals,
    )
    _apply_conditional_competing_scope_soft_cap(
        counts,
        resolved_signals,
    )
    _apply_frame_competing_scope_soft_cap(
        counts,
        resolved_signals,
    )
    _apply_dynamic_competing_scope_soft_cap(
        counts,
        resolved_signals,
    )
    _apply_alethic_competing_scope_soft_cap(
        counts,
        resolved_signals,
    )
    _apply_competing_scope_backfill(
        counts,
        resolved_signals,
    )
    _apply_statutory_reference_frame_scope_backfill(
        counts,
        resolved_signals,
    )
    _apply_vacant_section_frame_scope_backfill(
        counts,
        resolved_signals,
    )
    if has_generic_frame_debias_context:
        _apply_generic_frame_statutory_competing_scope_backfill(
            counts,
            resolved_signals,
        )
    _apply_directional_modal_family_pair_backfill(
        counts,
        resolved_signals,
    )
    _apply_refined_modal_family_cue_pair_balance(
        counts,
        resolved_signals,
    )
    _apply_competing_deontic_temporal_scope_phrase_reinforcement(
        counts,
        resolved_signals,
    )
    return counts


def _overlap_aware_modal_family_counts(
    encoding: SpaCyLegalEncoding,
) -> Dict[str, float]:
    """Count family cues while collapsing nested same-family cue spans."""
    spans_by_family: Dict[str, List[tuple[int, int]]] = {}
    for cue in encoding.cues:
        start = int(cue.start_char)
        end = int(cue.end_char)
        if start < 0 or end <= start:
            continue
        spans_by_family.setdefault(cue.family, []).append((start, end))

    counts: Dict[str, float] = {}
    for family, spans in spans_by_family.items():
        if not spans:
            continue
        unique_spans = sorted(set(spans))
        effective_spans: List[tuple[int, int]] = []
        for start, end in unique_spans:
            span_len = end - start
            covered_by_larger_span = False
            for other_start, other_end in unique_spans:
                if other_start == start and other_end == end:
                    continue
                other_len = other_end - other_start
                if (
                    other_start <= start
                    and other_end >= end
                    and other_len > span_len
                ):
                    covered_by_larger_span = True
                    break
            if not covered_by_larger_span:
                effective_spans.append((start, end))
        counts[family] = float(len(effective_spans))
    return counts


def _apply_generic_frame_normative_scope_soft_cap(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Limit repeated generic frame cues when competing scope evidence is present."""
    frame_family = ModalLogicFamily.FRAME.value
    frame_count = float(counts.get(frame_family, 0.0))
    if frame_count <= _GENERIC_FRAME_NORMATIVE_SCOPE_SOFT_CAP:
        return
    has_competing_scope = (
        bool(signals.get("has_deontic_scope"))
        or bool(signals.get("has_condition_or_exception_scope"))
        or bool(signals.get("has_temporal_scope"))
        or bool(signals.get("has_epistemic_scope"))
    )
    if not has_competing_scope:
        return
    counts[frame_family] = _GENERIC_FRAME_NORMATIVE_SCOPE_SOFT_CAP


def _apply_statutory_structural_frame_cue_reinforcement(
    counts: Dict[str, float],
    encoding: SpaCyLegalEncoding,
    signals: Mapping[str, bool],
) -> None:
    """Restore bounded frame evidence for explicit statutory structure cues."""
    if (
        bool(signals.get("has_conditional_scope_token"))
        and bool(signals.get("has_statutory_scope_reference"))
        and not bool(signals.get("has_deontic_cue"))
    ):
        return
    structural_cue_count = 0
    for cue in encoding.cues:
        if (
            cue.family == ModalLogicFamily.FRAME.value
            and cue.cue.lower() in _STATUTORY_STRUCTURAL_FRAME_CUE_TERMS
        ):
            structural_cue_count += 1
    if structural_cue_count <= 0:
        return
    frame_family = ModalLogicFamily.FRAME.value
    reinforcement = min(
        float(structural_cue_count) * _STATUTORY_STRUCTURAL_FRAME_CUE_WEIGHT,
        _STATUTORY_STRUCTURAL_FRAME_CUE_MAX,
    )
    counts[frame_family] = float(counts.get(frame_family, 0.0)) + reinforcement


def _apply_deontic_competing_scope_soft_cap(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Prevent repeated deontic cues from overwhelming competing family evidence."""
    deontic_family = ModalLogicFamily.DEONTIC.value
    deontic_count = float(counts.get(deontic_family, 0.0))
    if deontic_count <= _DEONTIC_COMPETING_SCOPE_SOFT_CAP:
        return
    has_temporal_competition = (
        bool(signals.get("has_temporal_scope"))
        or float(counts.get(ModalLogicFamily.TEMPORAL.value, 0.0)) > 0.0
    )
    has_frame_competition = (
        bool(signals.get("has_frame_context"))
        or bool(signals.get("has_frame_scope_phrase"))
        or bool(signals.get("has_frame_editorial_scope_phrase"))
        or bool(signals.get("has_statutory_scope_reference"))
        or float(counts.get(ModalLogicFamily.FRAME.value, 0.0)) > 0.0
    )
    has_conditional_competition = (
        bool(signals.get("has_condition_or_exception_scope"))
        or float(counts.get(ModalLogicFamily.CONDITIONAL_NORMATIVE.value, 0.0)) > 0.0
    )
    has_epistemic_competition = (
        bool(signals.get("has_epistemic_scope"))
        or bool(signals.get("has_epistemic_cue"))
        or float(counts.get(ModalLogicFamily.EPISTEMIC.value, 0.0)) > 0.0
    )
    has_dynamic_competition = (
        bool(signals.get("has_dynamic_scope"))
        or bool(signals.get("has_dynamic_cue"))
        or float(counts.get(ModalLogicFamily.DYNAMIC.value, 0.0)) > 0.0
    )
    if not (
        has_temporal_competition
        or has_frame_competition
        or has_conditional_competition
        or has_epistemic_competition
        or has_dynamic_competition
    ):
        return
    deontic_soft_cap = _DEONTIC_COMPETING_SCOPE_SOFT_CAP
    has_strong_temporal_competition = (
        has_temporal_competition
        and (
            bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
            or bool(signals.get("has_temporal_within_scope"))
            or (
                bool(signals.get("has_temporal_scope_token"))
                and bool(signals.get("has_temporal_cue"))
            )
        )
    )
    has_strong_dynamic_competition = (
        has_dynamic_competition
        and (
            bool(signals.get("has_dynamic_scope_phrase"))
            or bool(signals.get("has_dynamic_cue"))
        )
    )
    if has_strong_temporal_competition or has_strong_dynamic_competition:
        deontic_soft_cap = min(
            deontic_soft_cap,
            _DEONTIC_STRONG_COMPETING_SCOPE_SOFT_CAP,
        )
    if deontic_count <= deontic_soft_cap:
        return
    overflow = deontic_count - deontic_soft_cap
    counts[deontic_family] = deontic_soft_cap + math.log1p(overflow)


def _apply_temporal_competing_scope_soft_cap(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Prevent repeated temporal cues from overwhelming competing family evidence."""
    temporal_family = ModalLogicFamily.TEMPORAL.value
    temporal_count = float(counts.get(temporal_family, 0.0))
    if temporal_count <= _TEMPORAL_COMPETING_SCOPE_SOFT_CAP:
        return
    has_deontic_competition = (
        bool(signals.get("has_deontic_scope"))
        or float(counts.get(ModalLogicFamily.DEONTIC.value, 0.0)) > 0.0
    )
    has_conditional_competition = (
        bool(signals.get("has_condition_or_exception_scope"))
        or float(counts.get(ModalLogicFamily.CONDITIONAL_NORMATIVE.value, 0.0)) > 0.0
    )
    has_dynamic_competition = (
        bool(signals.get("has_dynamic_scope"))
        or bool(signals.get("has_dynamic_cue"))
        or float(counts.get(ModalLogicFamily.DYNAMIC.value, 0.0)) > 0.0
    )
    has_frame_competition = (
        bool(signals.get("has_frame_context"))
        or bool(signals.get("has_frame_scope_phrase"))
        or bool(signals.get("has_frame_editorial_scope_phrase"))
        or bool(signals.get("has_statutory_scope_reference"))
        or float(counts.get(ModalLogicFamily.FRAME.value, 0.0)) > 0.0
    )
    if not (
        has_deontic_competition
        or has_conditional_competition
        or has_dynamic_competition
        or has_frame_competition
    ):
        return
    has_strong_deontic_competition = (
        has_deontic_competition
        and (
            bool(signals.get("has_deontic_scope_phrase"))
            or bool(signals.get("has_deontic_cue"))
        )
    )
    has_strong_conditional_competition = (
        has_conditional_competition
        and (
            bool(signals.get("has_condition_clause"))
            or bool(signals.get("has_exception_clause"))
            or bool(signals.get("has_conditional_scope_phrase"))
            or bool(signals.get("has_conditional_scope_token"))
            or bool(signals.get("has_statutory_scope_reference"))
        )
    )
    has_strong_frame_competition = (
        has_frame_competition
        and (
            bool(signals.get("has_frame_scope_phrase"))
            or bool(signals.get("has_frame_editorial_scope_phrase"))
            or bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_frame_cue"))
        )
    )
    temporal_soft_cap = _TEMPORAL_COMPETING_SCOPE_SOFT_CAP
    if (
        has_strong_deontic_competition
        or has_strong_conditional_competition
        or has_strong_frame_competition
    ):
        temporal_soft_cap = min(
            temporal_soft_cap,
            _TEMPORAL_STRONG_COMPETING_SCOPE_SOFT_CAP,
        )
    strong_competing_family_count = sum(
        1
        for signal_active in (
            has_strong_deontic_competition,
            has_strong_conditional_competition,
            has_strong_frame_competition,
        )
        if signal_active
    )
    if strong_competing_family_count >= 2:
        temporal_soft_cap = min(
            temporal_soft_cap,
            _TEMPORAL_MULTI_COMPETING_SCOPE_SOFT_CAP,
        )
    if temporal_count <= temporal_soft_cap:
        return
    overflow = temporal_count - temporal_soft_cap
    counts[temporal_family] = temporal_soft_cap + math.log1p(overflow)


def _apply_conditional_competing_scope_soft_cap(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Prevent repeated conditional cues from overwhelming competing family evidence."""
    conditional_family = ModalLogicFamily.CONDITIONAL_NORMATIVE.value
    conditional_count = float(counts.get(conditional_family, 0.0))
    if conditional_count <= _CONDITIONAL_COMPETING_SCOPE_SOFT_CAP:
        return
    has_deontic_competition = (
        bool(signals.get("has_deontic_scope"))
        or float(counts.get(ModalLogicFamily.DEONTIC.value, 0.0)) > 0.0
    )
    has_temporal_competition = (
        bool(signals.get("has_temporal_scope"))
        or float(counts.get(ModalLogicFamily.TEMPORAL.value, 0.0)) > 0.0
    )
    has_frame_competition = (
        bool(signals.get("has_frame_context"))
        or bool(signals.get("has_frame_scope_phrase"))
        or bool(signals.get("has_frame_editorial_scope_phrase"))
        or bool(signals.get("has_statutory_scope_reference"))
        or float(counts.get(ModalLogicFamily.FRAME.value, 0.0)) > 0.0
    )
    has_epistemic_competition = (
        bool(signals.get("has_epistemic_scope"))
        or bool(signals.get("has_epistemic_cue"))
        or float(counts.get(ModalLogicFamily.EPISTEMIC.value, 0.0)) > 0.0
    )
    if not (
        has_deontic_competition
        or has_temporal_competition
        or has_frame_competition
        or has_epistemic_competition
    ):
        return
    explicit_conditional_scope = _has_explicit_conditional_scope(signals)
    has_strong_deontic_competition = (
        has_deontic_competition
        and (
            bool(signals.get("has_deontic_scope_phrase"))
            or bool(signals.get("has_deontic_cue"))
        )
    )
    has_strong_epistemic_competition = (
        has_epistemic_competition
        and (
            bool(signals.get("has_epistemic_scope_phrase"))
            or bool(signals.get("has_epistemic_cue"))
        )
    )
    conditional_soft_cap = _CONDITIONAL_COMPETING_SCOPE_SOFT_CAP
    if (
        not explicit_conditional_scope
        and has_strong_deontic_competition
    ):
        conditional_soft_cap = min(
            conditional_soft_cap,
            _CONDITIONAL_STRONG_DEONTIC_COMPETING_SCOPE_SOFT_CAP,
        )
    if (
        not explicit_conditional_scope
        and has_strong_epistemic_competition
    ):
        conditional_soft_cap = min(
            conditional_soft_cap,
            _CONDITIONAL_STRONG_EPISTEMIC_COMPETING_SCOPE_SOFT_CAP,
        )
    if conditional_count <= conditional_soft_cap:
        return
    overflow = conditional_count - conditional_soft_cap
    counts[conditional_family] = conditional_soft_cap + math.log1p(overflow)


def _apply_frame_competing_scope_soft_cap(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Prevent dense frame cues from overwhelming strong non-frame scope evidence."""
    frame_family = ModalLogicFamily.FRAME.value
    frame_count = float(counts.get(frame_family, 0.0))
    if frame_count <= _FRAME_COMPETING_SCOPE_SOFT_CAP:
        return
    has_temporal_competition = (
        bool(signals.get("has_temporal_scope"))
        or float(counts.get(ModalLogicFamily.TEMPORAL.value, 0.0)) > 0.0
    )
    has_strong_temporal_competition = (
        has_temporal_competition
        and (
            bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
            or bool(signals.get("has_temporal_within_scope"))
            or (
                bool(signals.get("has_temporal_scope_token"))
                and bool(signals.get("has_temporal_cue"))
            )
        )
    )
    has_conditional_competition = (
        bool(signals.get("has_condition_or_exception_scope"))
        or float(counts.get(ModalLogicFamily.CONDITIONAL_NORMATIVE.value, 0.0)) > 0.0
    )
    has_strong_conditional_competition = (
        has_conditional_competition
        and (
            bool(signals.get("has_condition_clause"))
            or bool(signals.get("has_exception_clause"))
            or bool(signals.get("has_conditional_scope_phrase"))
            or bool(signals.get("has_conditional_scope_token"))
        )
    )
    has_alethic_competition = (
        bool(signals.get("has_alethic_scope"))
        or bool(signals.get("has_alethic_cue"))
        or float(counts.get(ModalLogicFamily.ALETHIC.value, 0.0)) > 0.0
    )
    has_deontic_competition = (
        bool(signals.get("has_deontic_scope"))
        or bool(signals.get("has_deontic_cue"))
        or float(counts.get(ModalLogicFamily.DEONTIC.value, 0.0)) > 0.0
    )
    has_strong_deontic_competition = (
        has_deontic_competition
        and (
            bool(signals.get("has_deontic_cue"))
            or bool(signals.get("has_deontic_scope_phrase"))
        )
    )
    has_epistemic_competition = (
        bool(signals.get("has_epistemic_scope"))
        or bool(signals.get("has_epistemic_cue"))
        or float(counts.get(ModalLogicFamily.EPISTEMIC.value, 0.0)) > 0.0
    )
    has_strong_epistemic_competition = (
        has_epistemic_competition
        and (
            bool(signals.get("has_epistemic_cue"))
            or bool(signals.get("has_epistemic_scope_phrase"))
        )
    )
    has_dynamic_competition = (
        bool(signals.get("has_dynamic_scope"))
        or bool(signals.get("has_dynamic_cue"))
        or float(counts.get(ModalLogicFamily.DYNAMIC.value, 0.0)) > 0.0
    )
    has_strong_dynamic_competition = (
        has_dynamic_competition
        and (
            bool(signals.get("has_dynamic_cue"))
            or bool(signals.get("has_dynamic_scope_phrase"))
        )
    )
    if not (
        has_strong_temporal_competition
        or has_strong_conditional_competition
        or has_alethic_competition
        or has_strong_deontic_competition
        or has_strong_epistemic_competition
        or has_strong_dynamic_competition
    ):
        return
    frame_soft_cap = _FRAME_COMPETING_SCOPE_SOFT_CAP
    if (
        has_strong_temporal_competition
        or has_strong_conditional_competition
        or has_strong_deontic_competition
        or has_strong_epistemic_competition
        or has_strong_dynamic_competition
    ):
        frame_soft_cap = min(
            frame_soft_cap,
            _FRAME_STRONG_COMPETING_SCOPE_SOFT_CAP,
        )
    if frame_count <= frame_soft_cap:
        return
    overflow = frame_count - frame_soft_cap
    counts[frame_family] = frame_soft_cap + math.log1p(overflow)


def _apply_dynamic_competing_scope_soft_cap(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Prevent repeated dynamic cues from overwhelming temporal/deontic scope."""
    dynamic_family = ModalLogicFamily.DYNAMIC.value
    dynamic_count = float(counts.get(dynamic_family, 0.0))
    if dynamic_count <= _DYNAMIC_COMPETING_SCOPE_SOFT_CAP:
        return
    has_temporal_competition = (
        bool(signals.get("has_temporal_scope"))
        or float(counts.get(ModalLogicFamily.TEMPORAL.value, 0.0)) > 0.0
    )
    has_deontic_competition = (
        bool(signals.get("has_deontic_scope"))
        or bool(signals.get("has_deontic_cue"))
        or float(counts.get(ModalLogicFamily.DEONTIC.value, 0.0)) > 0.0
    )
    has_conditional_competition = (
        bool(signals.get("has_condition_or_exception_scope"))
        or float(counts.get(ModalLogicFamily.CONDITIONAL_NORMATIVE.value, 0.0)) > 0.0
    )
    has_frame_competition = (
        bool(signals.get("has_frame_context"))
        or bool(signals.get("has_frame_scope_phrase"))
        or bool(signals.get("has_frame_editorial_scope_phrase"))
        or bool(signals.get("has_statutory_scope_reference"))
        or float(counts.get(ModalLogicFamily.FRAME.value, 0.0)) > 0.0
    )
    if not (
        has_temporal_competition
        or has_deontic_competition
        or has_conditional_competition
        or has_frame_competition
    ):
        return
    has_strong_temporal_competition = (
        has_temporal_competition
        and (
            bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
            or bool(signals.get("has_temporal_within_scope"))
            or bool(signals.get("has_temporal_scope_token"))
        )
    )
    has_strong_frame_competition = (
        has_frame_competition
        and (
            bool(signals.get("has_frame_scope_phrase"))
            or bool(signals.get("has_frame_editorial_scope_phrase"))
            or bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_frame_cue"))
        )
    )
    dynamic_soft_cap = _DYNAMIC_COMPETING_SCOPE_SOFT_CAP
    if has_strong_temporal_competition or has_strong_frame_competition:
        dynamic_soft_cap = min(
            dynamic_soft_cap,
            _DYNAMIC_STRONG_COMPETING_SCOPE_SOFT_CAP,
        )
    if dynamic_count <= dynamic_soft_cap:
        return
    overflow = dynamic_count - dynamic_soft_cap
    counts[dynamic_family] = dynamic_soft_cap + math.log1p(overflow)


def _apply_alethic_competing_scope_soft_cap(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Prevent repeated alethic cues from masking legal-force and scope families."""
    alethic_family = ModalLogicFamily.ALETHIC.value
    alethic_count = float(counts.get(alethic_family, 0.0))
    if alethic_count <= _ALETHIC_COMPETING_SCOPE_SOFT_CAP:
        return
    has_deontic_competition = (
        bool(signals.get("has_deontic_scope"))
        or bool(signals.get("has_deontic_cue"))
        or float(counts.get(ModalLogicFamily.DEONTIC.value, 0.0)) > 0.0
    )
    has_conditional_competition = (
        bool(signals.get("has_condition_or_exception_scope"))
        or float(counts.get(ModalLogicFamily.CONDITIONAL_NORMATIVE.value, 0.0)) > 0.0
    )
    has_frame_competition = (
        bool(signals.get("has_frame_context"))
        or bool(signals.get("has_frame_scope_phrase"))
        or bool(signals.get("has_statutory_scope_reference"))
        or float(counts.get(ModalLogicFamily.FRAME.value, 0.0)) > 0.0
    )
    has_temporal_competition = (
        bool(signals.get("has_temporal_scope"))
        or float(counts.get(ModalLogicFamily.TEMPORAL.value, 0.0)) > 0.0
    )
    has_epistemic_competition = (
        bool(signals.get("has_epistemic_scope"))
        or bool(signals.get("has_epistemic_cue"))
        or float(counts.get(ModalLogicFamily.EPISTEMIC.value, 0.0)) > 0.0
    )
    if not (
        has_deontic_competition
        or has_conditional_competition
        or has_frame_competition
        or has_temporal_competition
        or has_epistemic_competition
    ):
        return
    overflow = alethic_count - _ALETHIC_COMPETING_SCOPE_SOFT_CAP
    counts[alethic_family] = _ALETHIC_COMPETING_SCOPE_SOFT_CAP + math.log1p(overflow)


def _apply_generic_frame_scope_backfill(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Backfill small non-frame evidence for generic frame-only cue clusters."""
    frame_family = ModalLogicFamily.FRAME.value
    frame_count = float(counts.get(frame_family, 0.0))
    if frame_count <= 0.0:
        return
    non_frame_total = sum(
        float(value)
        for family, value in counts.items()
        if family != frame_family and float(value) > 0.0
    )
    if non_frame_total > 0.0:
        return
    if bool(signals.get("has_temporal_scope")):
        temporal_backfill = _GENERIC_FRAME_SCOPE_BACKFILL_WEIGHT
        if (
            bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
            or bool(signals.get("has_temporal_within_scope"))
        ):
            temporal_backfill = _GENERIC_FRAME_STRONG_TEMPORAL_SCOPE_BACKFILL_WEIGHT
        counts[ModalLogicFamily.TEMPORAL.value] = max(
            float(counts.get(ModalLogicFamily.TEMPORAL.value, 0.0)),
            temporal_backfill,
        )
    if bool(signals.get("has_condition_or_exception_scope")):
        counts[ModalLogicFamily.CONDITIONAL_NORMATIVE.value] = max(
            float(counts.get(ModalLogicFamily.CONDITIONAL_NORMATIVE.value, 0.0)),
            _GENERIC_FRAME_SCOPE_BACKFILL_WEIGHT,
        )
    if bool(signals.get("has_deontic_scope")):
        counts[ModalLogicFamily.DEONTIC.value] = max(
            float(counts.get(ModalLogicFamily.DEONTIC.value, 0.0)),
            _GENERIC_FRAME_SCOPE_BACKFILL_WEIGHT,
        )
    if bool(signals.get("has_epistemic_scope")):
        counts[ModalLogicFamily.EPISTEMIC.value] = max(
            float(counts.get(ModalLogicFamily.EPISTEMIC.value, 0.0)),
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
    if bool(signals.get("has_alethic_scope")):
        counts[ModalLogicFamily.ALETHIC.value] = max(
            float(counts.get(ModalLogicFamily.ALETHIC.value, 0.0)),
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
    if bool(signals.get("has_dynamic_scope")):
        counts[ModalLogicFamily.DYNAMIC.value] = max(
            float(counts.get(ModalLogicFamily.DYNAMIC.value, 0.0)),
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
        )


def _scaled_competing_scope_backfill(
    *,
    source_count: float,
    ratio: float,
    minimum: float,
    maximum: float,
) -> float:
    """Scale competing backfill with the dominant-family signal strength."""
    return min(
        float(maximum),
        max(float(minimum), float(source_count) * float(ratio)),
    )


def _apply_generic_frame_statutory_competing_scope_backfill(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Backfill non-frame scope evidence in statutory generic-frame contexts."""
    if not bool(signals.get("has_statutory_scope_reference")):
        return
    frame_family = ModalLogicFamily.FRAME.value
    frame_count = float(counts.get(frame_family, 0.0))
    if frame_count <= 0.0:
        return
    base_floor = _scaled_competing_scope_backfill(
        source_count=frame_count,
        ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
        minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
        maximum=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_MAX,
    )
    if bool(signals.get("has_deontic_scope")):
        deontic_floor = base_floor
        has_explicit_deontic_scope = bool(
            signals.get("has_deontic_scope_phrase")
            or signals.get("has_deontic_cue")
        )
        has_structural_deontic_scope = bool(
            signals.get("has_deontic_scope")
            and signals.get("has_statutory_scope_reference")
        )
        deontic_maximum = _STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_MAX
        if has_explicit_deontic_scope:
            deontic_maximum = _STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX
            deontic_floor = _scaled_competing_scope_backfill(
                source_count=frame_count,
                ratio=_STATUTORY_GENERIC_FRAME_STRONG_COMPETING_SCOPE_RATIO,
                minimum=base_floor,
                maximum=deontic_maximum,
            )
        if (
            has_structural_deontic_scope
            and bool(signals.get("has_condition_or_exception_scope"))
            and not has_explicit_deontic_scope
        ):
            deontic_floor = max(
                deontic_floor,
                min(frame_count, _STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX),
            )
        counts[ModalLogicFamily.DEONTIC.value] = max(
            float(counts.get(ModalLogicFamily.DEONTIC.value, 0.0)),
            deontic_floor,
        )
    has_explicit_conditional_scope = _has_explicit_conditional_scope(signals)
    if bool(signals.get("has_condition_or_exception_scope")) and (
        has_explicit_conditional_scope
        or float(counts.get(ModalLogicFamily.CONDITIONAL_NORMATIVE.value, 0.0)) > 0.0
    ):
        conditional_ratio = _STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO
        conditional_minimum = _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        if has_explicit_conditional_scope:
            conditional_ratio = _STATUTORY_GENERIC_FRAME_STRONG_COMPETING_SCOPE_RATIO
            conditional_minimum = base_floor
        conditional_floor = _scaled_competing_scope_backfill(
            source_count=frame_count,
            ratio=conditional_ratio,
            minimum=conditional_minimum,
            maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
        )
        counts[ModalLogicFamily.CONDITIONAL_NORMATIVE.value] = max(
            float(counts.get(ModalLogicFamily.CONDITIONAL_NORMATIVE.value, 0.0)),
            conditional_floor,
        )
    if bool(signals.get("has_temporal_scope")):
        temporal_maximum = _STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_MAX
        temporal_ratio = _STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO
        if (
            bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
            or bool(signals.get("has_temporal_within_scope"))
        ):
            temporal_maximum = _STATUTORY_GENERIC_FRAME_STRONG_TEMPORAL_SCOPE_MAX
            temporal_ratio = _STATUTORY_GENERIC_FRAME_STRONG_COMPETING_SCOPE_RATIO
        temporal_floor = _scaled_competing_scope_backfill(
            source_count=frame_count,
            ratio=temporal_ratio,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=temporal_maximum,
        )
        counts[ModalLogicFamily.TEMPORAL.value] = max(
            float(counts.get(ModalLogicFamily.TEMPORAL.value, 0.0)),
            temporal_floor,
        )
    if bool(
        signals.get("has_epistemic_scope")
        or signals.get("has_epistemic_cue")
    ):
        epistemic_floor = _scaled_competing_scope_backfill(
            source_count=frame_count,
            ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_EPISTEMIC_SCOPE_MAX,
        )
        counts[ModalLogicFamily.EPISTEMIC.value] = max(
            float(counts.get(ModalLogicFamily.EPISTEMIC.value, 0.0)),
            epistemic_floor,
        )


def _apply_competing_scope_backfill(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Inject small competing-family support in dense scope-heavy clauses."""
    deontic_family = ModalLogicFamily.DEONTIC.value
    conditional_family = ModalLogicFamily.CONDITIONAL_NORMATIVE.value
    temporal_family = ModalLogicFamily.TEMPORAL.value
    frame_family = ModalLogicFamily.FRAME.value
    dynamic_family = ModalLogicFamily.DYNAMIC.value
    doxastic_family = ModalLogicFamily.DOXASTIC.value
    epistemic_family = ModalLogicFamily.EPISTEMIC.value
    alethic_family = ModalLogicFamily.ALETHIC.value
    deontic_count = float(counts.get(deontic_family, 0.0))
    conditional_count = float(counts.get(conditional_family, 0.0))
    temporal_count = float(counts.get(temporal_family, 0.0))
    frame_count = float(counts.get(frame_family, 0.0))
    dynamic_count = float(counts.get(dynamic_family, 0.0))
    doxastic_count = float(counts.get(doxastic_family, 0.0))
    epistemic_count = float(counts.get(epistemic_family, 0.0))
    alethic_count = float(counts.get(alethic_family, 0.0))
    has_moderate_frame_competition = (
        frame_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_TRIGGER
    )
    has_frame_scope_signal = (
        bool(signals.get("has_frame_context"))
        or bool(signals.get("has_frame_scope_phrase"))
        or bool(signals.get("has_frame_editorial_scope_phrase"))
        or bool(signals.get("has_statutory_scope_reference"))
        or bool(signals.get("has_frame_cue"))
    )
    has_strong_temporal_scope = (
        bool(signals.get("has_calendar_date_scope"))
        or bool(signals.get("has_temporal_scope_phrase"))
        or bool(signals.get("has_temporal_within_scope"))
        or (
            bool(signals.get("has_temporal_scope_token"))
            and (
                bool(signals.get("has_statutory_scope_reference"))
                or bool(signals.get("has_temporal_cue"))
            )
        )
    )
    has_strong_conditional_scope = (
        bool(signals.get("has_exception_clause"))
        or bool(signals.get("has_conditional_scope_phrase"))
        or bool(signals.get("has_conditional_scope_token"))
        or bool(signals.get("has_statutory_scope_reference"))
    )
    has_explicit_conditional_scope = _has_explicit_conditional_scope(signals)
    if (
        deontic_count >= _DEONTIC_CONDITIONAL_SCOPE_BACKFILL_TRIGGER
        and conditional_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_condition_or_exception_scope"))
    ):
        conditional_backfill = _COMPETING_SCOPE_BACKFILL_WEIGHT
        if (
            bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_conditional_scope_phrase"))
            or bool(signals.get("has_conditional_scope_token"))
            or bool(signals.get("has_condition_clause"))
            or bool(signals.get("has_exception_clause"))
        ):
            conditional_backfill = max(
                conditional_backfill,
                _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        if (
            bool(signals.get("has_condition_clause"))
            or bool(signals.get("has_exception_clause"))
        ):
            conditional_backfill = max(
                conditional_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        conditional_backfill = max(
            conditional_backfill,
            _scaled_competing_scope_backfill(
                source_count=deontic_count,
                ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
            ),
        )
        counts[conditional_family] = max(
            float(counts.get(conditional_family, 0.0)),
            conditional_backfill,
        )
    if (
        conditional_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and has_strong_conditional_scope
        and (
            deontic_count > _COMPETING_SCOPE_BACKFILL_WEIGHT
            or (
                frame_count > _COMPETING_SCOPE_BACKFILL_WEIGHT
                and has_explicit_conditional_scope
            )
        )
    ):
        conditional_backfill = _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        if bool(signals.get("has_exception_clause")):
            conditional_backfill = max(
                conditional_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[conditional_family] = max(
            float(counts.get(conditional_family, 0.0)),
            conditional_backfill,
        )
    if (
        conditional_count >= _CONDITIONAL_FRAME_SCOPE_BACKFILL_TRIGGER
        and frame_count <= 0.0
        and bool(signals.get("has_statutory_scope_reference"))
    ):
        counts[frame_family] = max(
            float(counts.get(frame_family, 0.0)),
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
    if (
        conditional_count >= _CONDITIONAL_DEONTIC_SCOPE_BACKFILL_TRIGGER
        and deontic_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_deontic_scope"))
    ):
        deontic_backfill = _COMPETING_SCOPE_BACKFILL_WEIGHT
        if bool(
            signals.get("has_deontic_scope_phrase")
            or signals.get("has_deontic_cue")
        ):
            deontic_backfill = max(
                deontic_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        if bool(
            signals.get("has_statutory_scope_reference")
            or signals.get("has_deontic_scope_phrase")
            or signals.get("has_deontic_cue")
        ):
            deontic_backfill = max(
                deontic_backfill,
                _scaled_competing_scope_backfill(
                    source_count=conditional_count,
                    ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=_DEONTIC_COMPETING_SCOPE_BACKFILL_MAX,
                ),
            )
        counts[deontic_family] = max(
            float(counts.get(deontic_family, 0.0)),
            deontic_backfill,
        )
    if (
        alethic_count >= _ALETHIC_CONDITIONAL_SCOPE_BACKFILL_TRIGGER
        and conditional_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_condition_or_exception_scope"))
        and (
            bool(signals.get("has_condition_clause"))
            or bool(signals.get("has_exception_clause"))
            or bool(signals.get("has_conditional_scope_phrase"))
            or bool(signals.get("has_conditional_scope_token"))
            or bool(signals.get("has_statutory_scope_reference"))
        )
    ):
        conditional_backfill = _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        if bool(signals.get("has_exception_clause")):
            conditional_backfill = max(
                conditional_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[conditional_family] = max(
            float(counts.get(conditional_family, 0.0)),
            conditional_backfill,
        )
    if (
        alethic_count >= _ALETHIC_EPISTEMIC_SCOPE_BACKFILL_TRIGGER
        and epistemic_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(
            signals.get("has_epistemic_scope")
            or signals.get("has_epistemic_cue")
        )
    ):
        epistemic_backfill = _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        if bool(signals.get("has_epistemic_scope_phrase")):
            epistemic_backfill = max(
                epistemic_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        epistemic_backfill = max(
            epistemic_backfill,
            _scaled_competing_scope_backfill(
                source_count=alethic_count,
                ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_STATUTORY_GENERIC_FRAME_EPISTEMIC_SCOPE_MAX,
            ),
        )
        counts[epistemic_family] = max(
            float(counts.get(epistemic_family, 0.0)),
            epistemic_backfill,
        )
    if (
        alethic_count >= _ALETHIC_DEONTIC_SCOPE_BACKFILL_TRIGGER
        and deontic_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
    ):
        deontic_backfill = _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        if bool(signals.get("has_deontic_scope_phrase")):
            deontic_backfill = max(
                deontic_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[deontic_family] = max(
            float(counts.get(deontic_family, 0.0)),
            deontic_backfill,
        )
    if (
        alethic_count >= _ALETHIC_DEONTIC_SCOPE_BACKFILL_TRIGGER
        and frame_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and has_frame_scope_signal
    ):
        frame_backfill = _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        if (
            bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_frame_scope_phrase"))
            or bool(signals.get("has_frame_editorial_scope_phrase"))
        ):
            frame_backfill = max(
                frame_backfill,
                _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        frame_backfill = max(
            frame_backfill,
            _scaled_competing_scope_backfill(
                source_count=alethic_count,
                ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_DEONTIC_COMPETING_SCOPE_BACKFILL_MAX,
            ),
        )
        counts[frame_family] = max(
            float(counts.get(frame_family, 0.0)),
            frame_backfill,
        )
    if (
        conditional_count >= _CONDITIONAL_TEMPORAL_SCOPE_BACKFILL_TRIGGER
        and temporal_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_temporal_scope"))
    ):
        temporal_backfill = _COMPETING_SCOPE_BACKFILL_WEIGHT
        if has_strong_temporal_scope:
            temporal_backfill = max(
                temporal_backfill,
                _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
            if bool(
                signals.get("has_statutory_scope_reference")
                or signals.get("has_condition_clause")
                or signals.get("has_exception_clause")
            ):
                temporal_backfill = max(
                    temporal_backfill,
                    _scaled_competing_scope_backfill(
                        source_count=conditional_count,
                        ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
                        minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
                        maximum=_STATUTORY_GENERIC_FRAME_STRONG_TEMPORAL_SCOPE_MAX,
                    ),
                )
        counts[temporal_family] = max(
            float(counts.get(temporal_family, 0.0)),
            temporal_backfill,
        )
    elif (
        conditional_count > _COMPETING_SCOPE_BACKFILL_WEIGHT
        and temporal_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and has_strong_temporal_scope
        and bool(signals.get("has_statutory_scope_reference"))
    ):
        temporal_backfill = _scaled_competing_scope_backfill(
            source_count=conditional_count,
            ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
            minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_STRONG_TEMPORAL_SCOPE_MAX,
        )
        counts[temporal_family] = max(
            float(counts.get(temporal_family, 0.0)),
            temporal_backfill,
        )
    if (
        (
            conditional_count >= _CONDITIONAL_DYNAMIC_SCOPE_BACKFILL_TRIGGER
            or (
                conditional_count > 0.0
                and bool(signals.get("has_dynamic_scope_phrase"))
            )
        )
        and dynamic_count <= 0.0
        and bool(signals.get("has_dynamic_scope"))
        and (
            bool(signals.get("has_dynamic_scope_phrase"))
            or bool(signals.get("has_condition_or_exception_scope"))
        )
    ):
        counts[dynamic_family] = max(
            float(counts.get(dynamic_family, 0.0)),
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
    if (
        deontic_count >= _DEONTIC_TEMPORAL_SCOPE_BACKFILL_TRIGGER
        and temporal_count <= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_temporal_scope"))
    ):
        temporal_backfill = max(
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
            _scaled_competing_scope_backfill(
                source_count=deontic_count,
                ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
            ),
        )
        if (
            bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
            or bool(signals.get("has_temporal_within_scope"))
        ):
            temporal_backfill = max(
                temporal_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
            if bool(
                signals.get("has_deontic_cue")
                or signals.get("has_deontic_scope_phrase")
            ):
                temporal_backfill = max(
                    temporal_backfill,
                    _FRAME_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_WEIGHT,
                )
        counts[temporal_family] = max(
            float(counts.get(temporal_family, 0.0)),
            temporal_backfill,
        )
    if (
        deontic_count >= _DEONTIC_EPISTEMIC_SCOPE_BACKFILL_TRIGGER
        and epistemic_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(
            signals.get("has_epistemic_scope")
            or signals.get("has_epistemic_cue")
        )
    ):
        epistemic_backfill = max(
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
            _scaled_competing_scope_backfill(
                source_count=deontic_count,
                ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_STATUTORY_GENERIC_FRAME_EPISTEMIC_SCOPE_MAX,
            ),
        )
        if bool(signals.get("has_epistemic_scope_phrase")):
            epistemic_backfill = max(
                epistemic_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[epistemic_family] = max(
            float(counts.get(epistemic_family, 0.0)),
            epistemic_backfill,
        )
    if (
        doxastic_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and epistemic_count <= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(
            signals.get("has_epistemic_scope")
            or signals.get("has_epistemic_cue")
        )
    ):
        epistemic_backfill = _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        if bool(signals.get("has_epistemic_scope_phrase")):
            epistemic_backfill = max(
                epistemic_backfill,
                _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        epistemic_backfill = max(
            epistemic_backfill,
            _scaled_competing_scope_backfill(
                source_count=doxastic_count,
                ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_STATUTORY_GENERIC_FRAME_EPISTEMIC_SCOPE_MAX,
            ),
        )
        counts[epistemic_family] = max(
            float(counts.get(epistemic_family, 0.0)),
            epistemic_backfill,
        )
    if (
        temporal_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and has_strong_temporal_scope
        and (
            deontic_count > _COMPETING_SCOPE_BACKFILL_WEIGHT
            or frame_count > _COMPETING_SCOPE_BACKFILL_WEIGHT
            or conditional_count > _COMPETING_SCOPE_BACKFILL_WEIGHT
            or epistemic_count > _COMPETING_SCOPE_BACKFILL_WEIGHT
        )
    ):
        temporal_backfill = _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        if (
            bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
        ):
            temporal_backfill = max(
                temporal_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[temporal_family] = max(
            float(counts.get(temporal_family, 0.0)),
            temporal_backfill,
        )
    if (
        epistemic_count >= _EPISTEMIC_TEMPORAL_SCOPE_BACKFILL_TRIGGER
        and temporal_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_temporal_scope"))
    ):
        temporal_backfill = _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        if (
            bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
            or bool(signals.get("has_temporal_scope_token"))
            or bool(signals.get("has_temporal_within_scope"))
        ):
            temporal_backfill = max(
                temporal_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[temporal_family] = max(
            float(counts.get(temporal_family, 0.0)),
            temporal_backfill,
        )
    if (
        deontic_count >= _DEONTIC_DYNAMIC_SCOPE_BACKFILL_TRIGGER
        and frame_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and has_frame_scope_signal
    ):
        frame_backfill = _COMPETING_SCOPE_BACKFILL_WEIGHT
        if (
            bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_frame_scope_phrase"))
            or bool(signals.get("has_frame_editorial_scope_phrase"))
        ):
            frame_backfill = max(
                frame_backfill,
                _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        counts[frame_family] = max(
            float(counts.get(frame_family, 0.0)),
            frame_backfill,
        )
    if (
        deontic_count >= _DEONTIC_DYNAMIC_SCOPE_BACKFILL_TRIGGER
        and dynamic_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_dynamic_scope"))
        and (
            bool(signals.get("has_dynamic_scope_phrase"))
            or bool(signals.get("has_deontic_scope"))
            or bool(signals.get("has_deontic_scope_phrase"))
        )
    ):
        dynamic_backfill = max(
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
            _scaled_competing_scope_backfill(
                source_count=deontic_count,
                ratio=_DYNAMIC_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_DYNAMIC_COMPETING_SCOPE_BACKFILL_MAX,
            ),
        )
        if bool(signals.get("has_dynamic_scope_phrase")):
            dynamic_backfill = max(
                dynamic_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[dynamic_family] = max(
            float(counts.get(dynamic_family, 0.0)),
            dynamic_backfill,
        )
    if (
        frame_count >= _FRAME_DEONTIC_SCOPE_BACKFILL_TRIGGER
        and deontic_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_deontic_scope"))
    ):
        has_explicit_deontic_scope = bool(
            signals.get("has_deontic_scope_phrase")
            or signals.get("has_deontic_cue")
        )
        deontic_backfill = _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        if (
            bool(signals.get("has_statutory_scope_reference"))
            or has_explicit_deontic_scope
        ):
            deontic_backfill_max = _TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX
            if has_explicit_deontic_scope:
                deontic_backfill_max = _FRAME_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX
            deontic_backfill = max(
                deontic_backfill,
                _scaled_competing_scope_backfill(
                    source_count=frame_count,
                    ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=deontic_backfill_max,
                ),
            )
        counts[deontic_family] = max(
            float(counts.get(deontic_family, 0.0)),
            deontic_backfill,
        )
    elif (
        has_moderate_frame_competition
        and deontic_count <= 0.0
        and bool(signals.get("has_deontic_scope"))
    ):
        counts[deontic_family] = max(
            float(counts.get(deontic_family, 0.0)),
            _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
    elif (
        frame_count >= _FRAME_DEONTIC_SCOPE_BACKFILL_TRIGGER
        and _COMPETING_SCOPE_BACKFILL_WEIGHT < deontic_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
        and bool(
            signals.get("has_statutory_scope_reference")
            or signals.get("has_deontic_scope_phrase")
            or signals.get("has_deontic_cue")
        )
    ):
        deontic_backfill = max(
            float(deontic_count),
            _scaled_competing_scope_backfill(
                source_count=frame_count,
                ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=1.0,
                maximum=_FRAME_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX,
            ),
        )
        counts[deontic_family] = max(
            float(counts.get(deontic_family, 0.0)),
            deontic_backfill,
        )
    if (
        frame_count >= _FRAME_TEMPORAL_SCOPE_BACKFILL_TRIGGER
        and temporal_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_temporal_scope"))
    ):
        temporal_backfill_max = _STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX
        temporal_backfill = _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        if (
            bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
            or bool(signals.get("has_temporal_within_scope"))
        ):
            temporal_backfill = max(
                temporal_backfill,
                _FRAME_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        if (
            has_strong_temporal_scope
            and (
                bool(signals.get("has_statutory_scope_reference"))
                or bool(signals.get("has_frame_scope_phrase"))
                or bool(signals.get("has_frame_editorial_scope_phrase"))
            )
        ):
            temporal_backfill_max = _FRAME_TO_TEMPORAL_SCOPE_REINFORCEMENT_MAX
            temporal_backfill = max(
                temporal_backfill,
                _scaled_competing_scope_backfill(
                    source_count=frame_count,
                    ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_FRAME_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=temporal_backfill_max,
                ),
            )
        counts[temporal_family] = max(
            float(counts.get(temporal_family, 0.0)),
            temporal_backfill,
        )
    elif (
        has_moderate_frame_competition
        and temporal_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_temporal_scope"))
    ):
        temporal_backfill = _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        if (
            bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
            or bool(signals.get("has_temporal_within_scope"))
        ):
            temporal_backfill = max(
                temporal_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[temporal_family] = max(
            float(counts.get(temporal_family, 0.0)),
            temporal_backfill,
        )
    elif (
        frame_count >= _FRAME_TEMPORAL_SCOPE_BACKFILL_TRIGGER
        and _COMPETING_SCOPE_BACKFILL_WEIGHT < temporal_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and bool(signals.get("has_temporal_scope"))
        and has_strong_temporal_scope
    ):
        temporal_backfill = max(
            float(temporal_count),
            _scaled_competing_scope_backfill(
                source_count=frame_count,
                ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=1.0,
                maximum=_FRAME_TO_TEMPORAL_SCOPE_REINFORCEMENT_MAX,
            ),
        )
        counts[temporal_family] = max(
            float(counts.get(temporal_family, 0.0)),
            temporal_backfill,
        )
    if (
        frame_count >= _FRAME_CONDITIONAL_SCOPE_BACKFILL_TRIGGER
        and conditional_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_condition_or_exception_scope"))
        and (
            has_explicit_conditional_scope
            or conditional_count > 0.0
        )
        and (
            bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_conditional_scope_phrase"))
            or bool(signals.get("has_conditional_scope_token"))
            or bool(signals.get("has_condition_clause"))
            or bool(signals.get("has_exception_clause"))
        )
    ):
        conditional_backfill = _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        if has_strong_conditional_scope:
            conditional_backfill = max(
                conditional_backfill,
                _scaled_competing_scope_backfill(
                    source_count=frame_count,
                    ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
                    minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
                ),
            )
        counts[conditional_family] = max(
            float(counts.get(conditional_family, 0.0)),
            conditional_backfill,
        )
    elif (
        has_moderate_frame_competition
        and conditional_count <= 0.0
        and bool(signals.get("has_condition_or_exception_scope"))
        and has_explicit_conditional_scope
        and (
            bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_conditional_scope_phrase"))
            or bool(signals.get("has_conditional_scope_token"))
            or bool(signals.get("has_condition_clause"))
            or bool(signals.get("has_exception_clause"))
        )
    ):
        counts[conditional_family] = max(
            float(counts.get(conditional_family, 0.0)),
            _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
    elif (
        frame_count >= _FRAME_CONDITIONAL_SCOPE_BACKFILL_TRIGGER
        and _COMPETING_SCOPE_BACKFILL_WEIGHT < conditional_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and has_strong_conditional_scope
        and bool(signals.get("has_condition_or_exception_scope"))
    ):
        conditional_backfill = max(
            float(conditional_count),
            _scaled_competing_scope_backfill(
                source_count=frame_count,
                ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=1.0,
                maximum=_FRAME_TO_CONDITIONAL_SCOPE_REINFORCEMENT_MAX,
            ),
        )
        counts[conditional_family] = max(
            float(counts.get(conditional_family, 0.0)),
            conditional_backfill,
        )
    if (
        frame_count >= _FRAME_EPISTEMIC_SCOPE_BACKFILL_TRIGGER
        and epistemic_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(
            signals.get("has_epistemic_scope")
            or signals.get("has_epistemic_cue")
        )
    ):
        epistemic_backfill = _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        if not bool(
            signals.get("has_epistemic_scope_phrase")
            or signals.get("has_epistemic_cue")
        ):
            epistemic_backfill = _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        counts[epistemic_family] = max(
            float(counts.get(epistemic_family, 0.0)),
            epistemic_backfill,
        )
    elif (
        has_moderate_frame_competition
        and epistemic_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(
            signals.get("has_epistemic_scope")
            or signals.get("has_epistemic_cue")
        )
    ):
        counts[epistemic_family] = max(
            float(counts.get(epistemic_family, 0.0)),
            _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
    if (
        frame_count >= _FRAME_ALETHIC_SCOPE_BACKFILL_TRIGGER
        and alethic_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(
            signals.get("has_alethic_scope")
            or signals.get("has_alethic_cue")
        )
    ):
        counts[alethic_family] = max(
            float(counts.get(alethic_family, 0.0)),
            _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
    if (
        frame_count >= _FRAME_DYNAMIC_SCOPE_BACKFILL_TRIGGER
        and dynamic_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(
            signals.get("has_dynamic_scope")
            or signals.get("has_dynamic_cue")
        )
    ):
        dynamic_backfill = _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        if bool(
            signals.get("has_dynamic_scope_phrase")
            or signals.get("has_dynamic_cue")
        ):
            dynamic_backfill = max(
                dynamic_backfill,
                _scaled_competing_scope_backfill(
                    source_count=frame_count,
                    ratio=_DYNAMIC_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=_DYNAMIC_COMPETING_SCOPE_BACKFILL_MAX,
                ),
            )
        counts[dynamic_family] = max(
            float(counts.get(dynamic_family, 0.0)),
            dynamic_backfill,
        )
    if (
        dynamic_count >= _DYNAMIC_TEMPORAL_SCOPE_BACKFILL_TRIGGER
        and temporal_count <= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_temporal_scope"))
    ):
        temporal_backfill = _COMPETING_SCOPE_BACKFILL_WEIGHT
        if bool(
            signals.get("has_calendar_date_scope")
            or signals.get("has_temporal_scope_phrase")
            or signals.get("has_temporal_within_scope")
            or signals.get("has_temporal_scope_token")
        ):
            temporal_backfill = max(
                temporal_backfill,
                _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        temporal_backfill = max(
            temporal_backfill,
            _scaled_competing_scope_backfill(
                source_count=dynamic_count,
                ratio=_DYNAMIC_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
            ),
        )
        counts[temporal_family] = max(
            float(counts.get(temporal_family, 0.0)),
            temporal_backfill,
        )
    if (
        temporal_count >= (
            _TEMPORAL_DEONTIC_SCOPE_BACKFILL_TRIGGER
            if not (
                has_strong_temporal_scope
                and bool(signals.get("has_deontic_cue"))
                and not bool(signals.get("has_statutory_scope_reference"))
            )
            else (_TEMPORAL_DEONTIC_SCOPE_BACKFILL_TRIGGER - 0.5)
        )
        and deontic_count <= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
        and (
            bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_deontic_scope_phrase"))
            or bool(signals.get("has_deontic_cue"))
        )
    ):
        has_explicit_deontic_scope = bool(
            signals.get("has_deontic_scope_phrase")
            or signals.get("has_deontic_cue")
        )
        deontic_backfill_max = _DEONTIC_COMPETING_SCOPE_BACKFILL_MAX
        if has_explicit_deontic_scope:
            deontic_backfill_max = _TEMPORAL_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX
        deontic_backfill = max(
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
            _scaled_competing_scope_backfill(
                source_count=temporal_count,
                ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=deontic_backfill_max,
            ),
        )
        if has_explicit_deontic_scope:
            deontic_backfill = max(
                deontic_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[deontic_family] = max(
            float(counts.get(deontic_family, 0.0)),
            deontic_backfill,
        )
    if (
        temporal_count >= (
            _TEMPORAL_DEONTIC_SCOPE_BACKFILL_TRIGGER
            if not (
                has_strong_temporal_scope
                and bool(signals.get("has_deontic_cue"))
                and not bool(signals.get("has_statutory_scope_reference"))
            )
            else (_TEMPORAL_DEONTIC_SCOPE_BACKFILL_TRIGGER - 0.5)
        )
        and _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT < deontic_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
        and bool(
            signals.get("has_statutory_scope_reference")
            or signals.get("has_deontic_scope_phrase")
            or signals.get("has_deontic_cue")
        )
    ):
        reinforcement_minimum = 1.0
        if bool(
            signals.get("has_deontic_scope_phrase")
            or signals.get("has_deontic_cue")
        ) and has_strong_temporal_scope:
            reinforcement_minimum = 1.15
        deontic_backfill = max(
            float(deontic_count),
            _scaled_competing_scope_backfill(
                source_count=temporal_count,
                ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=reinforcement_minimum,
                maximum=_TEMPORAL_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX,
            ),
        )
        counts[deontic_family] = max(
            float(counts.get(deontic_family, 0.0)),
            deontic_backfill,
        )
    if (
        temporal_count >= _TEMPORAL_CONDITIONAL_SCOPE_BACKFILL_TRIGGER
        and conditional_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_condition_or_exception_scope"))
        and (
            bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_condition_clause"))
            or bool(signals.get("has_exception_clause"))
            or bool(signals.get("has_conditional_scope_phrase"))
            or bool(signals.get("has_conditional_scope_token"))
        )
    ):
        has_explicit_conditional_scope = bool(
            signals.get("has_condition_clause")
            or signals.get("has_exception_clause")
            or signals.get("has_conditional_scope_phrase")
            or signals.get("has_conditional_scope_token")
        )
        conditional_backfill_max = _TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX
        if has_explicit_conditional_scope:
            conditional_backfill_max = _TEMPORAL_TO_CONDITIONAL_SCOPE_REINFORCEMENT_MAX
        conditional_backfill = max(
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
            _scaled_competing_scope_backfill(
                source_count=temporal_count,
                ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=conditional_backfill_max,
            ),
        )
        if bool(
            signals.get("has_condition_clause")
            or signals.get("has_exception_clause")
        ):
            conditional_backfill = max(
                conditional_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[conditional_family] = max(
            float(counts.get(conditional_family, 0.0)),
            conditional_backfill,
        )
    if (
        temporal_count >= _TEMPORAL_CONDITIONAL_SCOPE_BACKFILL_TRIGGER
        and _COMPETING_SCOPE_BACKFILL_WEIGHT < conditional_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and has_strong_conditional_scope
        and bool(signals.get("has_condition_or_exception_scope"))
    ):
        conditional_backfill = max(
            float(conditional_count),
            _scaled_competing_scope_backfill(
                source_count=temporal_count,
                ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=1.0,
                maximum=_TEMPORAL_TO_CONDITIONAL_SCOPE_REINFORCEMENT_MAX,
            ),
        )
        counts[conditional_family] = max(
            float(counts.get(conditional_family, 0.0)),
            conditional_backfill,
        )
    if (
        temporal_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and conditional_count < temporal_count
        and has_strong_conditional_scope
        and bool(signals.get("has_condition_or_exception_scope"))
        and (
            bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_deontic_scope"))
            or bool(signals.get("has_deontic_cue"))
        )
    ):
        conditional_backfill = max(
            float(conditional_count),
            _scaled_competing_scope_backfill(
                source_count=temporal_count,
                ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
            ),
        )
        if bool(signals.get("has_statutory_scope_reference")):
            conditional_backfill = max(
                conditional_backfill,
                _scaled_competing_scope_backfill(
                    source_count=temporal_count,
                    ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
                    maximum=_TEMPORAL_TO_CONDITIONAL_SCOPE_REINFORCEMENT_MAX,
                ),
            )
        counts[conditional_family] = max(
            float(counts.get(conditional_family, 0.0)),
            conditional_backfill,
        )
    if (
        temporal_count >= _TEMPORAL_EPISTEMIC_SCOPE_BACKFILL_TRIGGER
        and epistemic_count <= 0.0
        and bool(
            signals.get("has_epistemic_scope")
            or signals.get("has_epistemic_cue")
        )
    ):
        counts[epistemic_family] = max(
            float(counts.get(epistemic_family, 0.0)),
            _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
    if (
        temporal_count >= _TEMPORAL_EPISTEMIC_SCOPE_REINFORCEMENT_TRIGGER
        and 0.0 < epistemic_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and bool(
            signals.get("has_epistemic_scope")
            or signals.get("has_epistemic_cue")
        )
        and bool(
            signals.get("has_epistemic_scope_phrase")
            or signals.get("has_epistemic_cue")
        )
    ):
        epistemic_backfill = max(
            float(epistemic_count),
            _scaled_competing_scope_backfill(
                source_count=temporal_count,
                ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=1.0,
                maximum=_TEMPORAL_TO_EPISTEMIC_SCOPE_REINFORCEMENT_MAX,
            ),
        )
        counts[epistemic_family] = max(
            float(counts.get(epistemic_family, 0.0)),
            epistemic_backfill,
        )
    if (
        temporal_count >= _TEMPORAL_ALETHIC_SCOPE_BACKFILL_TRIGGER
        and alethic_count <= 0.0
        and bool(
            signals.get("has_alethic_scope")
            or signals.get("has_alethic_cue")
        )
    ):
        counts[alethic_family] = max(
            float(counts.get(alethic_family, 0.0)),
            _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        alethic_count = float(counts.get(alethic_family, 0.0))
    if (
        temporal_count >= _TEMPORAL_ALETHIC_SCOPE_REINFORCEMENT_TRIGGER
        and alethic_count <= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_alethic_scope_phrase"))
    ):
        counts[alethic_family] = max(
            float(counts.get(alethic_family, 0.0)),
            _scaled_competing_scope_backfill(
                source_count=temporal_count,
                ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_TEMPORAL_TO_ALETHIC_SCOPE_REINFORCEMENT_MAX,
            ),
        )
        alethic_count = float(counts.get(alethic_family, 0.0))
    if (
        temporal_count >= _TEMPORAL_ALETHIC_SCOPE_REINFORCEMENT_TRIGGER
        and 0.0 < alethic_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and bool(
            signals.get("has_alethic_scope")
            or signals.get("has_alethic_cue")
        )
        and bool(
            signals.get("has_alethic_scope_phrase")
            or signals.get("has_alethic_cue")
        )
    ):
        alethic_backfill = max(
            float(alethic_count),
            _scaled_competing_scope_backfill(
                source_count=temporal_count,
                ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=1.0,
                maximum=_TEMPORAL_TO_ALETHIC_SCOPE_REINFORCEMENT_MAX,
            ),
        )
        counts[alethic_family] = max(
            float(counts.get(alethic_family, 0.0)),
            alethic_backfill,
        )
    if (
        temporal_count >= _TEMPORAL_FRAME_SCOPE_BACKFILL_TRIGGER
        and frame_count <= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_TRIGGER
        and (
            bool(signals.get("has_frame_context"))
            or bool(signals.get("has_frame_scope_phrase"))
            or bool(signals.get("has_frame_editorial_scope_phrase"))
            or bool(signals.get("has_statutory_scope_reference"))
        )
    ):
        has_explicit_frame_scope = bool(
            signals.get("has_frame_scope_phrase")
            or signals.get("has_frame_editorial_scope_phrase")
            or signals.get("has_statutory_scope_reference")
        )
        frame_backfill_max = _TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX
        if has_explicit_frame_scope:
            frame_backfill_max = _TEMPORAL_TO_FRAME_SCOPE_REINFORCEMENT_MAX
        frame_backfill = max(
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
            _scaled_competing_scope_backfill(
                source_count=temporal_count,
                ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=frame_backfill_max,
            ),
        )
        if (
            bool(signals.get("has_frame_scope_phrase"))
            or bool(signals.get("has_frame_editorial_scope_phrase"))
            or bool(signals.get("has_statutory_scope_reference"))
        ):
            frame_backfill = max(
                frame_backfill,
                _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        counts[frame_family] = max(
            float(counts.get(frame_family, 0.0)),
            frame_backfill,
        )


def _apply_statutory_reference_frame_scope_backfill(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Backfill frame-family support for statutory-reference scope conflicts."""
    if not bool(signals.get("has_statutory_scope_reference")):
        return
    has_frame_signal = (
        bool(signals.get("has_frame_context"))
        or bool(signals.get("has_frame_scope_phrase"))
        or bool(signals.get("has_frame_editorial_scope_phrase"))
    )
    if not has_frame_signal:
        return
    frame_family = ModalLogicFamily.FRAME.value
    frame_count = float(counts.get(frame_family, 0.0))
    conditional_family = ModalLogicFamily.CONDITIONAL_NORMATIVE.value
    deontic_family = ModalLogicFamily.DEONTIC.value
    conditional_count = float(counts.get(conditional_family, 0.0))
    deontic_count = float(counts.get(deontic_family, 0.0))
    if (
        conditional_count > 0.0
        and not bool(signals.get("has_condition_clause"))
        and not bool(signals.get("has_exception_clause"))
    ):
        counts[frame_family] = max(
            frame_count,
            _STATUTORY_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        frame_count = float(counts.get(frame_family, 0.0))
    if (
        deontic_count > 0.0
        and not bool(signals.get("has_deontic_scope_phrase"))
    ):
        deontic_competing_floor = _STATUTORY_FRAME_DEONTIC_SCOPE_BACKFILL_WEIGHT
        if bool(signals.get("has_deontic_cue")):
            deontic_competing_floor = _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        counts[frame_family] = max(
            frame_count,
            deontic_competing_floor,
        )


def _apply_vacant_section_frame_scope_backfill(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Treat vacant section headings as frame/status scope, not operative timing."""
    if not bool(signals.get("has_vacant_section_scope")):
        return
    frame_family = ModalLogicFamily.FRAME.value
    counts[frame_family] = max(
        float(counts.get(frame_family, 0.0)),
        1.2,
    )


def _apply_directional_modal_family_pair_backfill(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Top up directional family-pair evidence in statutory mixed-scope clauses."""
    frame_family = ModalLogicFamily.FRAME.value
    deontic_family = ModalLogicFamily.DEONTIC.value
    temporal_family = ModalLogicFamily.TEMPORAL.value
    conditional_family = ModalLogicFamily.CONDITIONAL_NORMATIVE.value
    epistemic_family = ModalLogicFamily.EPISTEMIC.value

    has_strong_temporal_scope = _has_strong_temporal_scope_signal(signals)
    has_temporal_fiscal_scope_phrase = bool(
        signals.get("has_temporal_fiscal_scope_phrase")
    )
    has_deontic_authorization_scope_phrase = bool(
        signals.get("has_deontic_authorization_scope_phrase")
    )
    has_non_deadline_temporal_scope = bool(
        signals.get("has_temporal_scope")
        and not signals.get("has_temporal_deadline_cue")
        and not signals.get("has_temporal_within_scope")
    )
    has_statutory_scope_reference = bool(
        signals.get("has_statutory_scope_reference")
    )
    has_direct_frame_scope_signal = bool(
        signals.get("has_frame_context")
        or signals.get("has_frame_scope_phrase")
        or signals.get("has_frame_editorial_scope_phrase")
        or signals.get("has_frame_structural_authority_scope_phrase")
        or signals.get("has_frame_cue")
    )
    # Treat statutory cross-references as weak frame scope in this directional
    # pass so mixed temporal/deontic/conditional clauses retain frame evidence.
    has_frame_scope_signal = bool(
        has_direct_frame_scope_signal
        or has_statutory_scope_reference
    )
    has_editorial_frame_scope = bool(
        signals.get("has_frame_editorial_scope_phrase")
    )
    has_structural_authority_frame_scope = bool(
        signals.get("has_frame_structural_authority_scope_phrase")
    )
    has_explicit_conditional_scope = bool(
        signals.get("has_condition_clause")
        or signals.get("has_exception_clause")
        or signals.get("has_conditional_scope_phrase")
        or signals.get("has_conditional_scope_token")
    )
    has_explicit_deontic_scope = bool(
        signals.get("has_deontic_scope_phrase")
        or signals.get("has_deontic_cue")
    )
    has_structural_conditional_scope = bool(
        signals.get("has_condition_or_exception_scope")
        and has_statutory_scope_reference
    )
    has_structural_deontic_scope = bool(
        signals.get("has_deontic_scope")
        and has_statutory_scope_reference
    )
    has_temporal_cue_scope = bool(
        signals.get("has_temporal_cue")
        and (
            has_statutory_scope_reference
            or has_frame_scope_signal
        )
    )
    has_epistemic_scope_signal = bool(
        signals.get("has_epistemic_scope")
        or signals.get("has_epistemic_cue")
    )
    has_strong_epistemic_scope = bool(
        signals.get("has_epistemic_scope_phrase")
        or signals.get("has_epistemic_cue")
    )
    has_epistemic_scope = bool(
        signals.get("has_epistemic_scope")
        or signals.get("has_epistemic_cue")
    )
    has_fiscal_authorization_temporal_deontic_competition = bool(
        has_temporal_fiscal_scope_phrase
        and has_deontic_authorization_scope_phrase
        and has_non_deadline_temporal_scope
    )

    frame_count = float(counts.get(frame_family, 0.0))
    deontic_count = float(counts.get(deontic_family, 0.0))
    temporal_count = float(counts.get(temporal_family, 0.0))
    conditional_count = float(counts.get(conditional_family, 0.0))
    epistemic_count = float(counts.get(epistemic_family, 0.0))
    has_conditional_temporal_competing_context = (
        has_statutory_scope_reference
        or has_editorial_frame_scope
        or has_frame_scope_signal
        or (
            has_explicit_conditional_scope
            and has_strong_temporal_scope
        )
    )

    # conditional_normative -> temporal
    if (
        conditional_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and temporal_count < conditional_count
        and bool(signals.get("has_temporal_scope"))
        and (has_strong_temporal_scope or has_temporal_cue_scope)
        and (
            has_statutory_scope_reference
            or has_editorial_frame_scope
            or has_frame_scope_signal
            or (has_explicit_conditional_scope and has_strong_temporal_scope)
        )
        and has_conditional_temporal_competing_context
    ):
        temporal_top_up = _scaled_competing_scope_backfill(
            source_count=conditional_count,
            ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
        )
        counts[temporal_family] = max(temporal_count, temporal_top_up)
        temporal_count = float(counts.get(temporal_family, 0.0))

    # conditional_normative -> epistemic
    if (
        conditional_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and epistemic_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and epistemic_count < conditional_count
        and has_epistemic_scope_signal
        and (
            has_explicit_conditional_scope
            or has_structural_conditional_scope
            or has_statutory_scope_reference
            or has_frame_scope_signal
        )
    ):
        epistemic_top_up = _scaled_competing_scope_backfill(
            source_count=conditional_count,
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_EPISTEMIC_SCOPE_MAX,
        )
        if has_strong_epistemic_scope and (
            has_statutory_scope_reference
            or has_explicit_conditional_scope
        ):
            epistemic_top_up = max(
                epistemic_top_up,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[epistemic_family] = max(epistemic_count, epistemic_top_up)
        epistemic_count = float(counts.get(epistemic_family, 0.0))

    # conditional_normative -> frame
    if (
        conditional_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and frame_count <= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and frame_count < conditional_count
        and bool(signals.get("has_condition_or_exception_scope"))
        and has_frame_scope_signal
        and has_statutory_scope_reference
        and (
            has_explicit_conditional_scope
            or has_editorial_frame_scope
        )
    ):
        frame_top_up = _scaled_competing_scope_backfill(
            source_count=conditional_count,
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_MAX,
        )
        if bool(
            signals.get("has_frame_scope_phrase")
            or has_editorial_frame_scope
        ):
            frame_top_up = max(
                frame_top_up,
                _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        counts[frame_family] = max(frame_count, frame_top_up)
        frame_count = float(counts.get(frame_family, 0.0))

    # conditional_normative -> deontic
    if (
        conditional_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and deontic_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and deontic_count < conditional_count
        and bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
        and (
            has_explicit_conditional_scope
            or has_structural_conditional_scope
        )
        and (
            has_explicit_deontic_scope
            or has_structural_deontic_scope
        )
        and (
            has_statutory_scope_reference
            or has_frame_scope_signal
        )
    ):
        deontic_top_up_max = (
            _STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX
            if has_statutory_scope_reference
            else _DEONTIC_COMPETING_SCOPE_BACKFILL_MAX
        )
        deontic_top_up = _scaled_competing_scope_backfill(
            source_count=max(conditional_count, frame_count),
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=deontic_top_up_max,
        )
        if has_explicit_conditional_scope and has_explicit_deontic_scope:
            deontic_top_up = max(
                deontic_top_up,
                _scaled_competing_scope_backfill(
                    source_count=max(conditional_count, frame_count),
                    ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
                    maximum=_FRAME_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX,
                ),
            )
            deontic_top_up = max(
                deontic_top_up,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[deontic_family] = max(deontic_count, deontic_top_up)
        deontic_count = float(counts.get(deontic_family, 0.0))

    # temporal -> deontic
    if (
        temporal_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and deontic_count <= _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        and deontic_count < temporal_count
        and bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
        and (has_explicit_deontic_scope or has_structural_deontic_scope)
        and (
            has_statutory_scope_reference
            or has_frame_scope_signal
            or has_fiscal_authorization_temporal_deontic_competition
        )
    ):
        deontic_top_up_max = (
            _DEONTIC_COMPETING_SCOPE_BACKFILL_MAX
            if has_explicit_deontic_scope
            else _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        )
        if has_fiscal_authorization_temporal_deontic_competition:
            deontic_top_up_max = max(
                deontic_top_up_max,
                _TEMPORAL_TO_DEONTIC_STRONG_SCOPE_BACKFILL_MAX,
            )
        if (
            has_strong_temporal_scope
            and has_explicit_deontic_scope
            and (
                has_statutory_scope_reference
                or has_frame_scope_signal
                or has_fiscal_authorization_temporal_deontic_competition
            )
        ):
            deontic_top_up_max = max(
                deontic_top_up_max,
                _TEMPORAL_TO_DEONTIC_STRONG_SCOPE_BACKFILL_MAX,
            )
        deontic_top_up = _scaled_competing_scope_backfill(
            source_count=temporal_count,
            ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=deontic_top_up_max,
        )
        if has_strong_temporal_scope and has_explicit_deontic_scope:
            deontic_top_up = max(
                deontic_top_up,
                _scaled_competing_scope_backfill(
                    source_count=temporal_count,
                    ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=_TEMPORAL_TO_DEONTIC_STRONG_SCOPE_BACKFILL_MAX,
                ),
            )
            deontic_top_up = max(
                deontic_top_up,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        elif has_strong_temporal_scope and has_structural_deontic_scope:
            deontic_top_up = max(
                deontic_top_up,
                _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        counts[deontic_family] = max(deontic_count, deontic_top_up)
        deontic_count = float(counts.get(deontic_family, 0.0))

    # temporal -> conditional_normative
    if (
        temporal_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and conditional_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and conditional_count < temporal_count
        and bool(signals.get("has_condition_or_exception_scope"))
        and (
            has_explicit_conditional_scope
            or has_structural_conditional_scope
        )
        and (
            has_statutory_scope_reference
            or has_frame_scope_signal
        )
    ):
        conditional_maximum = (
            _STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX
            if has_statutory_scope_reference
            else _TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX
        )
        conditional_top_up = _scaled_competing_scope_backfill(
            source_count=temporal_count,
            ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=conditional_maximum,
        )
        if has_strong_temporal_scope and has_structural_conditional_scope:
            conditional_top_up = max(
                conditional_top_up,
                _scaled_competing_scope_backfill(
                    source_count=max(temporal_count, frame_count),
                    ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
                    minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
                    maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
                ),
            )
        if has_structural_conditional_scope and has_statutory_scope_reference:
            conditional_top_up = max(
                conditional_top_up,
                _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        counts[conditional_family] = max(conditional_count, conditional_top_up)
        conditional_count = float(counts.get(conditional_family, 0.0))

    # temporal -> deontic (reinforced statutory structural scope)
    if (
        temporal_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and deontic_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and deontic_count < temporal_count
        and bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
        and (has_explicit_deontic_scope or has_structural_deontic_scope)
        and (
            has_statutory_scope_reference
            or has_frame_scope_signal
            or has_fiscal_authorization_temporal_deontic_competition
        )
    ):
        deontic_top_up_max = (
            _DEONTIC_COMPETING_SCOPE_BACKFILL_MAX
            if has_explicit_deontic_scope
            else _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        )
        if (
            has_fiscal_authorization_temporal_deontic_competition
            and has_explicit_deontic_scope
        ):
            deontic_top_up_max = max(
                deontic_top_up_max,
                _TEMPORAL_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX,
            )
        if (
            has_strong_temporal_scope
            and has_explicit_deontic_scope
            and (
                has_statutory_scope_reference
                or has_frame_scope_signal
                or has_fiscal_authorization_temporal_deontic_competition
            )
        ):
            deontic_top_up_max = max(
                deontic_top_up_max,
                _TEMPORAL_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX,
            )
        deontic_top_up = _scaled_competing_scope_backfill(
            source_count=temporal_count,
            ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=deontic_top_up_max,
        )
        if has_strong_temporal_scope and has_structural_deontic_scope:
            deontic_top_up = max(
                deontic_top_up,
                _scaled_competing_scope_backfill(
                    source_count=max(temporal_count, frame_count),
                    ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
                    minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
                    maximum=(
                        _TEMPORAL_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX
                        if has_explicit_deontic_scope
                        else _STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX
                    ),
                ),
            )
        if (
            has_fiscal_authorization_temporal_deontic_competition
            and has_explicit_deontic_scope
        ):
            deontic_top_up = max(
                deontic_top_up,
                _scaled_competing_scope_backfill(
                    source_count=max(temporal_count, frame_count),
                    ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
                    minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
                    maximum=_TEMPORAL_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX,
                ),
            )
        if has_strong_temporal_scope and has_explicit_deontic_scope:
            deontic_top_up = max(
                deontic_top_up,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[deontic_family] = max(deontic_count, deontic_top_up)
        deontic_count = float(counts.get(deontic_family, 0.0))

    # epistemic -> deontic
    if (
        epistemic_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and deontic_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and deontic_count < epistemic_count
        and has_epistemic_scope
        and bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
        and has_explicit_deontic_scope
        and (
            has_statutory_scope_reference
            or has_frame_scope_signal
        )
    ):
        deontic_top_up = _scaled_competing_scope_backfill(
            source_count=epistemic_count,
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_DEONTIC_COMPETING_SCOPE_BACKFILL_MAX,
        )
        if has_statutory_scope_reference:
            deontic_top_up = max(
                deontic_top_up,
                _scaled_competing_scope_backfill(
                    source_count=max(epistemic_count, frame_count),
                    ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
                    maximum=_EPISTEMIC_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX,
                ),
            )
        counts[deontic_family] = max(deontic_count, deontic_top_up)
        deontic_count = float(counts.get(deontic_family, 0.0))

    # deontic -> conditional_normative
    if (
        deontic_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and conditional_count < deontic_count
        and bool(signals.get("has_condition_or_exception_scope"))
        and (
            has_explicit_conditional_scope
            or has_statutory_scope_reference
        )
        and (
            has_statutory_scope_reference
            or has_frame_scope_signal
        )
    ):
        conditional_top_up = _scaled_competing_scope_backfill(
            source_count=deontic_count,
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
        )
        if has_explicit_conditional_scope and has_explicit_deontic_scope:
            conditional_top_up = max(
                conditional_top_up,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[conditional_family] = max(conditional_count, conditional_top_up)
        conditional_count = float(counts.get(conditional_family, 0.0))

    # conditional_normative -> deontic
    if (
        conditional_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and deontic_count < conditional_count
        and bool(signals.get("has_deontic_scope") or signals.get("has_deontic_cue"))
        and (has_explicit_deontic_scope or has_structural_deontic_scope)
        and (has_statutory_scope_reference or has_frame_scope_signal)
    ):
        deontic_top_up_max = _DEONTIC_COMPETING_SCOPE_BACKFILL_MAX
        if has_explicit_deontic_scope and has_statutory_scope_reference:
            deontic_top_up_max = max(
                deontic_top_up_max,
                _STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX,
            )
        deontic_top_up = _scaled_competing_scope_backfill(
            source_count=conditional_count,
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=deontic_top_up_max,
        )
        if has_explicit_deontic_scope and has_explicit_conditional_scope:
            deontic_top_up = max(
                deontic_top_up,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[deontic_family] = max(deontic_count, deontic_top_up)
        deontic_count = float(counts.get(deontic_family, 0.0))
    # deontic -> temporal
    if (
        deontic_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and temporal_count <= _LOW_COMPETING_SCOPE_REINFORCEMENT_LIMIT
        and temporal_count < deontic_count
        and bool(signals.get("has_temporal_scope"))
        and (
            has_strong_temporal_scope
            or has_temporal_cue_scope
        )
        and (
            has_statutory_scope_reference
            or has_frame_scope_signal
            or has_explicit_deontic_scope
        )
    ):
        temporal_top_up = _scaled_competing_scope_backfill(
            source_count=max(deontic_count, frame_count),
            ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=(
                _STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX
                if has_strong_temporal_scope
                else _TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX
            ),
        )
        if has_strong_temporal_scope and (
            has_explicit_deontic_scope
            or has_structural_deontic_scope
        ):
            temporal_top_up = max(
                temporal_top_up,
                _scaled_competing_scope_backfill(
                    source_count=max(deontic_count, frame_count),
                    ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
                    maximum=_FRAME_TO_TEMPORAL_SCOPE_REINFORCEMENT_MAX,
                ),
            )
        counts[temporal_family] = max(temporal_count, temporal_top_up)
        temporal_count = float(counts.get(temporal_family, 0.0))

    # temporal -> frame
    if (
        temporal_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and frame_count < temporal_count
        and bool(signals.get("has_temporal_scope"))
        and (has_strong_temporal_scope or has_temporal_cue_scope)
        and has_frame_scope_signal
        and (
            has_statutory_scope_reference
            or has_editorial_frame_scope
            or bool(signals.get("has_frame_scope_phrase"))
        )
    ):
        frame_top_up = _scaled_competing_scope_backfill(
            source_count=temporal_count,
            ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        if (
            has_strong_temporal_scope
            and has_statutory_scope_reference
            and (
                has_editorial_frame_scope
                or bool(signals.get("has_frame_scope_phrase"))
            )
        ):
            frame_top_up = max(
                frame_top_up,
                _scaled_competing_scope_backfill(
                    source_count=temporal_count,
                    ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=_TEMPORAL_TO_FRAME_STRONG_SCOPE_BACKFILL_MAX,
                ),
            )
        elif (
            has_strong_temporal_scope
            and has_statutory_scope_reference
            and bool(signals.get("has_frame_context"))
            and not has_editorial_frame_scope
        ):
            frame_top_up = max(
                frame_top_up,
                _scaled_competing_scope_backfill(
                    source_count=temporal_count,
                    ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
                ),
            )
        if bool(
            signals.get("has_frame_scope_phrase")
            or has_editorial_frame_scope
        ):
            frame_top_up = max(
                frame_top_up,
                _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        elif (
            has_statutory_scope_reference
            and bool(signals.get("has_frame_context"))
        ):
            frame_top_up = max(
                frame_top_up,
                _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        counts[frame_family] = max(frame_count, frame_top_up)
        frame_count = float(counts.get(frame_family, 0.0))

    # frame -> conditional_normative
    if (
        frame_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_TRIGGER
        and conditional_count < frame_count
        and bool(signals.get("has_condition_or_exception_scope"))
        and (
            has_explicit_conditional_scope
            or conditional_count > 0.0
        )
        and has_frame_scope_signal
        and has_statutory_scope_reference
        and (
            not has_editorial_frame_scope
            or has_explicit_conditional_scope
        )
    ):
        conditional_top_up = _scaled_competing_scope_backfill(
            source_count=frame_count,
            ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
        )
        if bool(
            (
                signals.get("has_deontic_scope")
                or signals.get("has_deontic_cue")
            )
            and has_explicit_conditional_scope
        ):
            conditional_top_up = max(
                conditional_top_up,
                _scaled_competing_scope_backfill(
                    source_count=frame_count,
                    ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
                    maximum=_FRAME_TO_CONDITIONAL_SCOPE_REINFORCEMENT_MAX,
                ),
            )
        counts[conditional_family] = max(conditional_count, conditional_top_up)
        conditional_count = float(counts.get(conditional_family, 0.0))

    # frame -> deontic
    if (
        frame_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_TRIGGER
        and deontic_count < frame_count
        and bool(signals.get("has_deontic_scope"))
        and has_frame_scope_signal
        and has_statutory_scope_reference
        and (
            not has_editorial_frame_scope
            or has_explicit_deontic_scope
        )
    ):
        deontic_top_up = _scaled_competing_scope_backfill(
            source_count=frame_count,
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
        )
        if has_explicit_deontic_scope:
            deontic_top_up = max(
                deontic_top_up,
                _scaled_competing_scope_backfill(
                    source_count=frame_count,
                    ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
                    maximum=_FRAME_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX,
                ),
            )
            deontic_top_up = max(
                deontic_top_up,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[deontic_family] = max(deontic_count, deontic_top_up)
        deontic_count = float(counts.get(deontic_family, 0.0))

    # frame -> temporal
    if (
        frame_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_TRIGGER
        and temporal_count < frame_count
        and bool(signals.get("has_temporal_scope"))
        and has_strong_temporal_scope
        and has_frame_scope_signal
        and has_statutory_scope_reference
        and (
            not has_editorial_frame_scope
            or bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
            or bool(signals.get("has_temporal_within_scope"))
        )
    ):
        temporal_top_up = _scaled_competing_scope_backfill(
            source_count=frame_count,
            ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
        )
        if bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        ):
            temporal_top_up = max(
                temporal_top_up,
                _scaled_competing_scope_backfill(
                    source_count=frame_count,
                    ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
                    maximum=_FRAME_TO_TEMPORAL_SCOPE_REINFORCEMENT_MAX,
                ),
            )
        counts[temporal_family] = max(temporal_count, temporal_top_up)
        temporal_count = float(counts.get(temporal_family, 0.0))

    # frame -> temporal (weak temporal scope under statutory deontic competition)
    if (
        frame_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_TRIGGER
        and temporal_count < frame_count
        and bool(signals.get("has_temporal_scope"))
        and not has_strong_temporal_scope
        and bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
        and has_frame_scope_signal
        and has_statutory_scope_reference
        and not has_editorial_frame_scope
    ):
        temporal_top_up = _scaled_competing_scope_backfill(
            source_count=frame_count,
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
        )
        counts[temporal_family] = max(temporal_count, temporal_top_up)
        temporal_count = float(counts.get(temporal_family, 0.0))

    # deontic -> temporal
    if (
        deontic_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and temporal_count < deontic_count
        and bool(signals.get("has_temporal_scope"))
        and has_strong_temporal_scope
        and (has_statutory_scope_reference or has_frame_scope_signal)
    ):
        temporal_top_up = _scaled_competing_scope_backfill(
            source_count=deontic_count,
            ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
        )
        if has_explicit_deontic_scope and has_statutory_scope_reference:
            temporal_top_up = max(
                temporal_top_up,
                _scaled_competing_scope_backfill(
                    source_count=deontic_count,
                    ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
                    minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=_FRAME_TO_TEMPORAL_SCOPE_REINFORCEMENT_MAX,
                ),
            )
        counts[temporal_family] = max(temporal_count, temporal_top_up)
        temporal_count = float(counts.get(temporal_family, 0.0))

    # deontic -> frame
    if (
        deontic_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and frame_count < deontic_count
        and has_direct_frame_scope_signal
        and (
            has_statutory_scope_reference
            or has_editorial_frame_scope
            or has_structural_authority_frame_scope
        )
    ):
        frame_top_up = _scaled_competing_scope_backfill(
            source_count=deontic_count,
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[frame_family] = max(frame_count, frame_top_up)

    # deontic -> frame (statutory cross-reference fallback without frame lexemes)
    if (
        deontic_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and frame_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and frame_count < deontic_count
        and not has_direct_frame_scope_signal
        and has_statutory_scope_reference
        and (
            has_explicit_deontic_scope
            or has_structural_deontic_scope
        )
    ):
        frame_top_up = _scaled_competing_scope_backfill(
            source_count=deontic_count,
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=(
                _STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX
                if has_explicit_deontic_scope
                else _STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_MAX
            ),
        )
        if has_explicit_deontic_scope:
            frame_top_up = max(
                frame_top_up,
                _scaled_competing_scope_backfill(
                    source_count=deontic_count,
                    ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=_STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX,
                ),
            )
        counts[frame_family] = max(frame_count, frame_top_up)
        frame_count = float(counts.get(frame_family, 0.0))


def _apply_refined_modal_family_cue_pair_balance(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Balance near-neighbor family cues for known deontic/temporal/conditional drift."""
    deontic_family = ModalLogicFamily.DEONTIC.value
    temporal_family = ModalLogicFamily.TEMPORAL.value
    conditional_family = ModalLogicFamily.CONDITIONAL_NORMATIVE.value
    frame_family = ModalLogicFamily.FRAME.value
    epistemic_family = ModalLogicFamily.EPISTEMIC.value
    alethic_family = ModalLogicFamily.ALETHIC.value

    deontic_count = float(counts.get(deontic_family, 0.0))
    temporal_count = float(counts.get(temporal_family, 0.0))
    conditional_count = float(counts.get(conditional_family, 0.0))
    frame_count = float(counts.get(frame_family, 0.0))
    epistemic_count = float(counts.get(epistemic_family, 0.0))
    alethic_count = float(counts.get(alethic_family, 0.0))

    has_deontic_scope = bool(
        signals.get("has_deontic_scope")
        or signals.get("has_deontic_cue")
    )
    has_deontic_cue = bool(signals.get("has_deontic_cue"))
    has_explicit_deontic_scope = bool(
        signals.get("has_deontic_scope_phrase")
        or signals.get("has_deontic_cue")
    )
    has_deontic_appropriations_scope_phrase = bool(
        signals.get("has_deontic_appropriations_scope_phrase")
    )
    has_deontic_corporate_powers_scope_phrase = bool(
        signals.get("has_deontic_corporate_powers_scope_phrase")
    )
    has_deontic_report_duty_scope_phrase = bool(
        signals.get("has_deontic_report_duty_scope_phrase")
    )
    has_deontic_citation_authority_scope_phrase = bool(
        signals.get("has_deontic_citation_authority_scope_phrase")
    )
    has_phrase_only_deontic_scope = bool(
        has_deontic_scope
        and not bool(signals.get("has_deontic_scope_phrase"))
    )
    has_temporal_scope = bool(signals.get("has_temporal_scope"))
    has_strong_temporal_scope = _has_strong_temporal_scope_signal(signals)
    has_temporal_deadline_scope = bool(
        signals.get("has_temporal_deadline_cue")
        or signals.get("has_temporal_within_scope")
        or signals.get("has_calendar_date_scope")
    )
    has_definition_scope = bool(signals.get("has_definition_scope"))
    has_editorial_frame_context = bool(
        signals.get("has_frame_editorial_scope_phrase")
    )
    has_structural_conditional_scope = bool(
        signals.get("has_condition_or_exception_scope")
    )
    has_conditional_clause_scope = bool(
        signals.get("has_condition_clause")
        or signals.get("has_exception_clause")
    )
    has_conditional_scope_token = bool(signals.get("has_conditional_scope_token"))
    has_conditional_scope_phrase = bool(signals.get("has_conditional_scope_phrase"))
    has_purpose_scope_phrase = bool(signals.get("has_purpose_scope_phrase"))
    has_explicit_conditional_scope = _has_explicit_conditional_scope(signals)
    has_statutory_scope_reference = bool(
        signals.get("has_statutory_scope_reference")
    )
    has_temporal_status_scope = bool(signals.get("has_temporal_status_scope"))
    has_calendar_date_scope = bool(signals.get("has_calendar_date_scope"))
    has_epistemic_scope = bool(
        signals.get("has_epistemic_scope")
        or signals.get("has_epistemic_cue")
    )
    has_strong_epistemic_scope = bool(
        signals.get("has_epistemic_scope_phrase")
        or signals.get("has_epistemic_cue")
    )
    has_direct_frame_scope_context = bool(
        signals.get("has_frame_context")
        or signals.get("has_frame_scope_phrase")
        or signals.get("has_frame_editorial_scope_phrase")
        or signals.get("has_frame_cue")
    )
    has_frame_scope_context = bool(
        has_direct_frame_scope_context
        or has_statutory_scope_reference
    )
    has_structural_authority_frame_scope = bool(
        signals.get("has_frame_structural_authority_scope_phrase")
    )
    has_phrase_only_conditional_scope = bool(
        has_structural_conditional_scope
        and has_conditional_scope_phrase
        and not has_conditional_clause_scope
        and not has_conditional_scope_token
    )
    has_non_clause_structural_conditional_scope = bool(
        has_structural_conditional_scope
        and not has_conditional_clause_scope
        and not has_conditional_scope_token
    )

    # frame -> deontic / temporal / conditional_normative:
    # U.S.C. headers and statutory cross-references often contribute generic
    # frame evidence.  When the same passage has explicit non-frame modal
    # scope, keep the typed cue family close enough to contest frame instead of
    # letting structural scaffolding dominate the family distribution.
    has_generic_statutory_frame_scope = bool(
        frame_count > 0.0
        and has_frame_scope_context
        and has_statutory_scope_reference
        and not has_editorial_frame_context
        and not has_definition_scope
        and not has_structural_authority_frame_scope
    )
    if has_generic_statutory_frame_scope:
        strongest_non_frame = max(
            deontic_count,
            temporal_count,
            conditional_count,
            epistemic_count,
            alethic_count,
        )
        if (
            frame_count > deontic_count
            and has_deontic_scope
            and has_explicit_deontic_scope
        ):
            deontic_floor = _scaled_competing_scope_backfill(
                source_count=frame_count,
                ratio=0.94,
                minimum=max(
                    deontic_count,
                    _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
                ),
                maximum=max(
                    frame_count,
                    _STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX,
                ),
            )
            counts[deontic_family] = max(deontic_count, deontic_floor)
            deontic_count = float(counts.get(deontic_family, 0.0))
        if (
            frame_count > temporal_count
            and has_temporal_scope
            and (
                has_strong_temporal_scope
                or has_temporal_deadline_scope
                or has_temporal_status_scope
                or has_calendar_date_scope
            )
        ):
            temporal_floor = _scaled_competing_scope_backfill(
                source_count=frame_count,
                ratio=0.92,
                minimum=max(
                    temporal_count,
                    _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                ),
                maximum=max(
                    frame_count,
                    _STATUTORY_GENERIC_FRAME_STRONG_TEMPORAL_SCOPE_MAX,
                ),
            )
            counts[temporal_family] = max(temporal_count, temporal_floor)
            temporal_count = float(counts.get(temporal_family, 0.0))
        if (
            frame_count > conditional_count
            and has_structural_conditional_scope
            and (
                has_explicit_conditional_scope
                or has_conditional_scope_phrase
                or has_conditional_clause_scope
            )
        ):
            conditional_floor = _scaled_competing_scope_backfill(
                source_count=frame_count,
                ratio=0.9,
                minimum=max(
                    conditional_count,
                    _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                ),
                maximum=max(
                    frame_count,
                    _STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
                ),
            )
            counts[conditional_family] = max(
                conditional_count,
                conditional_floor,
            )
            conditional_count = float(counts.get(conditional_family, 0.0))
        strongest_non_frame = max(
            strongest_non_frame,
            deontic_count,
            temporal_count,
            conditional_count,
        )
        if strongest_non_frame > 0.0 and frame_count > strongest_non_frame:
            frame_cap = (
                strongest_non_frame
                + _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
            )
            if frame_count > frame_cap:
                counts[frame_family] = frame_cap + (
                    0.2 * math.log1p(frame_count - frame_cap)
                )
                frame_count = float(counts.get(frame_family, 0.0))

    # frame -> deontic:
    # corporate-charter powers sections are often packed with frame terms
    # ("corporation", "purposes", title headers), but "the corporation may"
    # carries operative permission.
    if (
        frame_count > deontic_count
        and has_deontic_corporate_powers_scope_phrase
        and has_deontic_cue
        and has_frame_scope_context
    ):
        deontic_floor = _scaled_competing_scope_backfill(
            source_count=frame_count,
            ratio=1.0,
            minimum=max(deontic_count, _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT),
            maximum=max(frame_count, _FRAME_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX),
        )
        counts[deontic_family] = max(deontic_count, deontic_floor)
        deontic_count = float(counts.get(deontic_family, 0.0))

    # temporal -> deontic:
    # annual-report provisions use temporal fiscal-year scope to describe the
    # timing of a mandatory submission.  Preserve the typed duty cue when it is
    # otherwise only a rounding margin below temporal evidence.
    if (
        temporal_count >= deontic_count
        and has_deontic_report_duty_scope_phrase
        and has_deontic_cue
        and has_temporal_scope
        and bool(signals.get("has_temporal_fiscal_scope_phrase"))
    ):
        counts[deontic_family] = max(
            deontic_count,
            temporal_count + 0.01,
        )
        deontic_count = float(counts.get(deontic_family, 0.0))

    # deontic -> deontic:
    # short-title provisions and amendment notes repeat conditional/date
    # scaffolding; "may be cited" remains a permission cue and should not be
    # washed out by those surrounding note clauses.
    if (
        has_deontic_citation_authority_scope_phrase
        and has_deontic_cue
        and deontic_count > 0.0
    ):
        deontic_floor = max(
            deontic_count,
            max(conditional_count, temporal_count)
            + _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[deontic_family] = deontic_floor
        deontic_count = float(counts.get(deontic_family, 0.0))

    # temporal -> deontic:
    # repeal-style statutory notes can surface dense date/status tokens that
    # over-index temporal cues despite operative deontic language.
    if (
        temporal_count > deontic_count
        and has_temporal_scope
        and has_temporal_status_scope
        and has_calendar_date_scope
        and has_deontic_scope
        and has_statutory_scope_reference
        and has_frame_scope_context
        and not has_editorial_frame_context
        and not has_conditional_clause_scope
    ):
        deontic_floor = max(
            _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            min(
                temporal_count * 0.72,
                temporal_count - _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            ),
        )
        counts[deontic_family] = max(
            deontic_count,
            deontic_floor,
        )
        deontic_count = float(counts.get(deontic_family, 0.0))

    # deontic -> conditional_normative:
    # explicit statutory conditional clauses in editorial scaffolding should not
    # be flattened by repeated generic deontic verbs.
    if (
        deontic_count > conditional_count
        and has_deontic_scope
        and has_structural_conditional_scope
        and has_explicit_conditional_scope
        and has_conditional_clause_scope
        and has_statutory_scope_reference
        and has_editorial_frame_context
    ):
        deontic_cap = conditional_count + _COMPETING_SCOPE_BACKFILL_WEIGHT
        if deontic_count > deontic_cap:
            deontic_overflow = deontic_count - deontic_cap
            counts[deontic_family] = deontic_cap + (
                0.2 * math.log1p(deontic_overflow)
            )
            deontic_count = float(counts.get(deontic_family, 0.0))
        conditional_floor = max(
            conditional_count,
            deontic_count - _COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[conditional_family] = max(
            conditional_count,
            conditional_floor,
        )
        conditional_count = float(counts.get(conditional_family, 0.0))

    # deontic -> frame:
    # statutory historical summaries with explicit condition clauses can encode
    # structural frame context that should remain visible under deontic pressure.
    if (
        deontic_count > frame_count
        and has_deontic_scope
        and has_frame_scope_context
        and has_statutory_scope_reference
        and has_conditional_clause_scope
        and has_temporal_status_scope
    ):
        frame_floor = _scaled_competing_scope_backfill(
            source_count=max(conditional_count, temporal_count, deontic_count),
            ratio=0.38,
            minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=(
                _TEMPORAL_TO_FRAME_SCOPE_REINFORCEMENT_MAX
                if bool(signals.get("has_frame_cue"))
                else _STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX
            ),
        )
        counts[frame_family] = max(
            frame_count,
            frame_floor,
        )
        frame_count = float(counts.get(frame_family, 0.0))

    # deontic -> temporal / frame:
    # statutory structural conditionals often carry generic deontic lexemes
    # ("shall", "required") plus temporal/frame context; cap deontic overflow
    # so competing temporal/frame evidence remains visible.
    if (
        deontic_count > 0.0
        and has_phrase_only_deontic_scope
        and has_structural_conditional_scope
        and has_statutory_scope_reference
        and has_temporal_scope
        and has_frame_scope_context
        and temporal_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and conditional_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
    ):
        competing_scope_anchor = max(
            temporal_count,
            frame_count,
            conditional_count,
            _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        deontic_scope_cap = (
            competing_scope_anchor + _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        )
        if deontic_count > deontic_scope_cap:
            deontic_overflow = deontic_count - deontic_scope_cap
            counts[deontic_family] = deontic_scope_cap + (
                0.3 * math.log1p(deontic_overflow)
            )
            deontic_count = float(counts.get(deontic_family, 0.0))
    # deontic -> temporal / frame:
    # editorial statutory sections with dense temporal/status and conditional
    # scaffolding can accumulate many generic deontic verbs; cap that overflow
    # so temporal/frame evidence stays visible.
    if (
        deontic_count > 0.0
        and has_structural_conditional_scope
        and has_statutory_scope_reference
        and has_temporal_scope
        and has_frame_scope_context
        and has_editorial_frame_context
        and bool(signals.get("has_temporal_status_scope"))
        and temporal_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and conditional_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
    ):
        competing_scope_anchor = max(
            temporal_count,
            frame_count,
            conditional_count,
            _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        deontic_scope_cap = competing_scope_anchor + _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        if deontic_count > deontic_scope_cap:
            deontic_overflow = deontic_count - deontic_scope_cap
            counts[deontic_family] = deontic_scope_cap + (
                0.25 * math.log1p(deontic_overflow)
            )
            deontic_count = float(counts.get(deontic_family, 0.0))
    # conditional_normative -> deontic:
    # qualifier-style conditional scaffolding (for example, "subject to ..." or
    # "for purposes of ...") should not flatten explicit deontic force to a tie.
    if (
        conditional_count > 0.0
        and has_structural_conditional_scope
        and has_conditional_scope_phrase
        and has_deontic_scope
        and has_explicit_deontic_scope
        and not has_temporal_scope
    ):
        deontic_increment = _scaled_competing_scope_backfill(
            source_count=conditional_count,
            ratio=0.2,
            minimum=0.0,
            maximum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[deontic_family] = max(
            deontic_count,
            deontic_count + deontic_increment,
        )
        deontic_count = float(counts.get(deontic_family, 0.0))

    # conditional_normative -> deontic:
    # clause-level "if/unless" scaffolding can overindex conditional cues in
    # operative obligations; preserve explicit deontic force in that pattern.
    if (
        conditional_count >= deontic_count
        and has_conditional_clause_scope
        and not has_conditional_scope_phrase
        and has_deontic_scope
        and has_explicit_deontic_scope
        and not has_temporal_scope
    ):
        deontic_increment = _scaled_competing_scope_backfill(
            source_count=conditional_count,
            ratio=0.18,
            minimum=0.0,
            maximum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[deontic_family] = max(
            deontic_count,
            deontic_count + deontic_increment,
        )
        deontic_count = float(counts.get(deontic_family, 0.0))

    # deontic -> temporal / conditional_normative:
    # preserve competing scope evidence when obligation terms and temporal/conditional
    # lexemes co-occur in the same clause.
    if (
        deontic_count > 0.0
        and has_temporal_scope
        and has_strong_temporal_scope
        and has_structural_conditional_scope
        and has_explicit_conditional_scope
    ):
        temporal_floor = _scaled_competing_scope_backfill(
            source_count=deontic_count,
            ratio=0.28,
            minimum=_STRONG_SCOPE_BACKFILL_WEIGHT,
            maximum=_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
        )
        counts[temporal_family] = max(
            temporal_count,
            temporal_floor,
        )
        temporal_count = float(counts.get(temporal_family, 0.0))
        if (
            bool(signals.get("has_temporal_deadline_cue"))
            and has_conditional_clause_scope
            and not has_conditional_scope_phrase
        ):
            temporal_increment = _scaled_competing_scope_backfill(
                source_count=max(deontic_count, conditional_count),
                ratio=0.16,
                minimum=0.0,
                maximum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
            counts[temporal_family] = max(
                temporal_count,
                temporal_count + temporal_increment,
            )
            temporal_count = float(counts.get(temporal_family, 0.0))

        conditional_floor = _scaled_competing_scope_backfill(
            source_count=deontic_count,
            ratio=0.22,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
        )
        counts[conditional_family] = max(
            conditional_count,
            conditional_floor,
        )
        conditional_count = float(counts.get(conditional_family, 0.0))

    # deontic -> temporal:
    # statutory purpose definitions can mix deontic verbs with strong temporal
    # status/effective-date context; keep temporal evidence visible there.
    if (
        deontic_count > temporal_count
        and has_deontic_scope
        and has_explicit_deontic_scope
        and has_temporal_scope
        and has_strong_temporal_scope
        and has_structural_conditional_scope
        and has_purpose_scope_phrase
        and has_statutory_scope_reference
        and (
            has_editorial_frame_context
            or bool(signals.get("has_temporal_status_scope"))
            or bool(signals.get("has_calendar_date_scope"))
        )
    ):
        temporal_increment = _scaled_competing_scope_backfill(
            source_count=max(deontic_count, conditional_count),
            ratio=0.14,
            minimum=0.0,
            maximum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[temporal_family] = max(
            temporal_count,
            temporal_count + temporal_increment,
        )
        temporal_count = float(counts.get(temporal_family, 0.0))

    # deontic -> temporal:
    # fee and appropriations clauses can repeat operative "shall/may" language
    # while fiscal-year or until-expended terms carry the typed temporal scope.
    if (
        deontic_count > temporal_count
        and has_deontic_scope
        and has_temporal_scope
        and has_statutory_scope_reference
        and has_structural_conditional_scope
        and (
            bool(signals.get("has_temporal_fiscal_scope_phrase"))
            or bool(signals.get("has_temporal_expended_scope_phrase"))
        )
        and not has_temporal_deadline_scope
    ):
        temporal_increment = _scaled_competing_scope_backfill(
            source_count=max(deontic_count, conditional_count, 1.0),
            ratio=0.1,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
        )
        counts[temporal_family] = max(
            temporal_count,
            temporal_count + temporal_increment,
        )
        temporal_count = float(counts.get(temporal_family, 0.0))

    # deontic -> conditional_normative:
    # phrase-only statutory scope (e.g., "with respect to") should still register a
    # conditional runner-up when deontic cues dominate.
    if (
        deontic_count > 0.0
        and has_phrase_only_conditional_scope
        and has_statutory_scope_reference
        and not (
            has_purpose_scope_phrase
            and has_explicit_deontic_scope
            and not has_temporal_scope
        )
    ):
        conditional_floor = _scaled_competing_scope_backfill(
            source_count=deontic_count,
            ratio=0.2,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
        )
        counts[conditional_family] = max(
            conditional_count,
            conditional_floor,
        )
        conditional_count = float(counts.get(conditional_family, 0.0))

    # deontic -> conditional_normative:
    # structural statutory cross-references without explicit if/unless clauses still
    # encode conditional scoping, so keep a conditional runner-up visible.
    if (
        deontic_count > 0.0
        and deontic_count >= conditional_count
        and has_structural_conditional_scope
        and has_statutory_scope_reference
        and not has_explicit_conditional_scope
        and (
            has_frame_scope_context
            or has_temporal_scope
            or has_purpose_scope_phrase
        )
    ):
        conditional_floor = _scaled_competing_scope_backfill(
            source_count=max(deontic_count, temporal_count, frame_count),
            ratio=0.22,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
        )
        counts[conditional_family] = max(
            conditional_count,
            conditional_floor,
        )
        conditional_count = float(counts.get(conditional_family, 0.0))

    # deontic -> frame:
    # statutory purpose/reference qualifiers can carry structural frame semantics
    # alongside operative deontic force; preserve frame evidence in that mix.
    if (
        deontic_count > frame_count
        and has_deontic_scope
        and has_explicit_deontic_scope
        and has_frame_scope_context
        and has_statutory_scope_reference
        and has_purpose_scope_phrase
        and has_non_clause_structural_conditional_scope
        and conditional_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
    ):
        frame_floor = _scaled_competing_scope_backfill(
            source_count=max(deontic_count, conditional_count),
            ratio=0.24,
            minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX,
        )
        counts[frame_family] = max(
            frame_count,
            frame_floor,
        )
        frame_count = float(counts.get(frame_family, 0.0))

    # temporal -> deontic:
    # phrase-only structural qualifiers (e.g., "with respect to") often carry
    # operative deontic force even when temporal deadlines are present.
    if (
        temporal_count > deontic_count
        and has_temporal_scope
        and has_phrase_only_conditional_scope
        and has_explicit_deontic_scope
    ):
        deontic_floor = _scaled_competing_scope_backfill(
            source_count=temporal_count,
            ratio=0.24,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX,
        )
        deontic_increment = _scaled_competing_scope_backfill(
            source_count=temporal_count,
            ratio=0.1,
            minimum=0.0,
            maximum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[deontic_family] = max(
            deontic_count,
            deontic_floor,
            deontic_count + deontic_increment,
        )
        deontic_count = float(counts.get(deontic_family, 0.0))

    # temporal -> deontic:
    # appropriations-authorization clauses frequently include fiscal-year temporal
    # qualifiers while still encoding deontic force through authorization.
    if (
        has_deontic_appropriations_scope_phrase
        and has_temporal_scope
        and temporal_count > 0.0
    ):
        deontic_floor = _scaled_competing_scope_backfill(
            source_count=max(temporal_count, frame_count, conditional_count, 1.0),
            ratio=0.28,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX,
        )
        counts[deontic_family] = max(
            deontic_count,
            deontic_floor,
        )
        deontic_count = float(counts.get(deontic_family, 0.0))
        if temporal_count > deontic_count and not has_temporal_deadline_scope:
            temporal_cap = max(
                deontic_count + _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
            if temporal_count > temporal_cap:
                temporal_overflow = temporal_count - temporal_cap
                counts[temporal_family] = temporal_cap + (
                    0.2 * math.log1p(temporal_overflow)
                )
                temporal_count = float(counts.get(temporal_family, 0.0))

    # temporal -> epistemic:
    # temporal-heavy statutory clauses can still encode epistemic predicates
    # ("determines", "finds", "deemed"), so preserve runner-up epistemic signal.
    if (
        temporal_count > epistemic_count
        and temporal_count >= _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT
        and has_temporal_scope
        and has_epistemic_scope
        and (
            has_statutory_scope_reference
            or bool(signals.get("has_frame_scope_phrase"))
            or bool(signals.get("has_frame_editorial_scope_phrase"))
            or bool(signals.get("has_frame_cue"))
            or has_structural_conditional_scope
        )
    ):
        epistemic_floor = _scaled_competing_scope_backfill(
            source_count=max(temporal_count, deontic_count),
            ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_TEMPORAL_TO_EPISTEMIC_SCOPE_REINFORCEMENT_MAX,
        )
        if has_strong_epistemic_scope:
            epistemic_floor = max(
                epistemic_floor,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        if (
            bool(signals.get("has_deontic_cue"))
            and not bool(signals.get("has_deontic_scope_phrase"))
        ):
            epistemic_floor = max(
                epistemic_floor,
                _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            )
        counts[epistemic_family] = max(
            epistemic_count,
            epistemic_floor,
        )
        epistemic_count = float(counts.get(epistemic_family, 0.0))

    # temporal -> alethic:
    # section-heading definition clauses can carry temporal boilerplate while
    # still encoding definitional/alethic force; preserve the alethic runner-up.
    if (
        temporal_count > alethic_count
        and has_temporal_scope
        and has_definition_scope
        and not has_explicit_deontic_scope
    ):
        alethic_floor = _scaled_competing_scope_backfill(
            source_count=max(temporal_count, frame_count),
            ratio=0.24,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[alethic_family] = max(
            alethic_count,
            alethic_floor,
        )
        alethic_count = float(counts.get(alethic_family, 0.0))
    if (
        temporal_count > alethic_count
        and temporal_count >= _TEMPORAL_ALETHIC_SCOPE_REINFORCEMENT_TRIGGER
        and has_temporal_scope
        and bool(signals.get("has_alethic_scope_phrase"))
    ):
        alethic_floor = _scaled_competing_scope_backfill(
            source_count=temporal_count,
            ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_TEMPORAL_TO_ALETHIC_SCOPE_REINFORCEMENT_MAX,
        )
        counts[alethic_family] = max(
            alethic_count,
            alethic_floor,
        )
        alethic_count = float(counts.get(alethic_family, 0.0))

    # temporal -> frame:
    # delegation/authority clauses with statutory conditions can be primarily
    # structural frame semantics despite nearby temporal qualifiers.
    if (
        temporal_count > frame_count
        and has_temporal_scope
        and has_frame_scope_context
        and has_statutory_scope_reference
        and has_explicit_deontic_scope
        and not has_temporal_deadline_scope
    ):
        frame_floor = _scaled_competing_scope_backfill(
            source_count=max(temporal_count, deontic_count),
            ratio=0.24,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_MAX,
        )
        counts[frame_family] = max(
            frame_count,
            frame_floor,
        )
        frame_count = float(counts.get(frame_family, 0.0))

    # temporal -> frame:
    # removal/jurisdiction and status-note sections often collect date and
    # status cues in editorial text while the typed semantics are the court or
    # statutory frame that scopes the operative rule.
    if (
        temporal_count > frame_count
        and frame_count > 0.0
        and has_temporal_scope
        and has_frame_scope_context
        and has_direct_frame_scope_context
        and (
            has_editorial_frame_context
            or has_structural_authority_frame_scope
        )
        and (
            has_statutory_scope_reference
            or has_structural_conditional_scope
            or has_deontic_scope
        )
    ):
        frame_floor = _scaled_competing_scope_backfill(
            source_count=max(temporal_count, deontic_count, conditional_count, 1.0),
            ratio=0.32,
            minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_TEMPORAL_TO_FRAME_SCOPE_REINFORCEMENT_MAX,
        )
        counts[frame_family] = max(frame_count, frame_floor)
        frame_count = float(counts.get(frame_family, 0.0))

    # temporal -> deontic:
    # prevent status/date-only temporal context from masking clear deontic force.
    temporal_status_only_scope = bool(
        has_temporal_scope
        and signals.get("has_temporal_status_scope")
        and not (
            signals.get("has_calendar_date_scope")
            or signals.get("has_temporal_scope_phrase")
            or signals.get("has_temporal_within_scope")
            or signals.get("has_temporal_scope_token")
        )
    )
    if (
        temporal_count > 0.0
        and has_deontic_scope
        and temporal_status_only_scope
    ):
        deontic_maximum = (
            _DEONTIC_COMPETING_SCOPE_BACKFILL_MAX
            if not has_explicit_deontic_scope
            else _STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX
        )
        deontic_floor = _scaled_competing_scope_backfill(
            source_count=temporal_count,
            ratio=0.22,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=deontic_maximum,
        )
        counts[deontic_family] = max(
            deontic_count,
            deontic_floor,
        )
        deontic_count = float(counts.get(deontic_family, 0.0))

    # temporal -> deontic / conditional_normative:
    # statutory status-style scaffolding can over-index temporal/frame signals
    # while still carrying operative deontic force and conditional qualifiers.
    if (
        temporal_count > 0.0
        and has_temporal_scope
        and has_temporal_status_scope
        and has_statutory_scope_reference
        and has_frame_scope_context
        and has_deontic_scope
        and has_explicit_deontic_scope
        and not has_temporal_deadline_scope
    ):
        deontic_floor = _scaled_competing_scope_backfill(
            source_count=max(temporal_count, frame_count, conditional_count, 1.0),
            ratio=0.26,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX,
        )
        counts[deontic_family] = max(deontic_count, deontic_floor)
        deontic_count = float(counts.get(deontic_family, 0.0))
        deontic_increment = _scaled_competing_scope_backfill(
            source_count=max(temporal_count, frame_count, conditional_count, 1.0),
            ratio=0.12,
            minimum=0.0,
            maximum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[deontic_family] = max(
            deontic_count,
            deontic_count + deontic_increment,
        )
        deontic_count = float(counts.get(deontic_family, 0.0))

        conditional_floor = _scaled_competing_scope_backfill(
            source_count=max(temporal_count, deontic_count, 1.0),
            ratio=0.22,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
        )
        counts[conditional_family] = max(conditional_count, conditional_floor)
        conditional_count = float(counts.get(conditional_family, 0.0))

    # temporal/frame -> deontic:
    # effective-date and amendment scaffolding can make temporal/frame context
    # dominate sections whose live rule is approval, prohibition, or required
    # reporting. Raise deontic support without erasing the competing scope.
    if (
        temporal_count > deontic_count
        and has_deontic_scope
        and has_temporal_scope
        and has_temporal_status_scope
        and has_frame_scope_context
        and frame_count > 0.0
        and (
            has_statutory_scope_reference
            or has_editorial_frame_context
            or has_calendar_date_scope
        )
    ):
        deontic_floor = _scaled_competing_scope_backfill(
            source_count=max(temporal_count, frame_count, conditional_count, 1.0),
            ratio=0.36,
            minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_TEMPORAL_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX,
        )
        counts[deontic_family] = max(deontic_count, deontic_floor)
        deontic_count = float(counts.get(deontic_family, 0.0))
        deontic_increment = _scaled_competing_scope_backfill(
            source_count=max(temporal_count, frame_count, conditional_count, 1.0),
            ratio=0.12,
            minimum=0.0,
            maximum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[deontic_family] = max(
            deontic_count,
            deontic_count + deontic_increment,
        )
        deontic_count = float(counts.get(deontic_family, 0.0))

    # frame -> deontic:
    # generic frame-heavy statutory context should not suppress explicit
    # deontic force when temporal status qualifiers are also present.
    if (
        frame_count > deontic_count
        and has_frame_scope_context
        and has_statutory_scope_reference
        and has_deontic_scope
        and has_explicit_deontic_scope
        and has_temporal_status_scope
        and not has_editorial_frame_context
    ):
        deontic_floor = _scaled_competing_scope_backfill(
            source_count=max(frame_count, temporal_count, 1.0),
            ratio=0.25,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX,
        )
        counts[deontic_family] = max(deontic_count, deontic_floor)
        deontic_count = float(counts.get(deontic_family, 0.0))

    # frame -> deontic / temporal:
    # generic structural frame cues in statutory references often describe the
    # venue for an operative rule.  Preserve explicit deontic and temporal
    # target evidence even when the frame cue count is dominant.
    if (
        frame_count > 0.0
        and has_frame_scope_context
        and (
            has_statutory_scope_reference
            or has_structural_authority_frame_scope
            or has_editorial_frame_context
        )
    ):
        if (
            frame_count > deontic_count
            and has_deontic_scope
            and has_explicit_deontic_scope
        ):
            deontic_floor = _scaled_competing_scope_backfill(
                source_count=max(frame_count, temporal_count, conditional_count, 1.0),
                ratio=0.32,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_FRAME_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX,
            )
            counts[deontic_family] = max(deontic_count, deontic_floor)
            deontic_count = float(counts.get(deontic_family, 0.0))
        if (
            frame_count > temporal_count
            and has_temporal_scope
            and has_strong_temporal_scope
        ):
            temporal_floor = _scaled_competing_scope_backfill(
                source_count=max(frame_count, deontic_count, conditional_count, 1.0),
                ratio=0.3,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_FRAME_TO_TEMPORAL_SCOPE_REINFORCEMENT_MAX,
            )
            counts[temporal_family] = max(temporal_count, temporal_floor)
            temporal_count = float(counts.get(temporal_family, 0.0))

    # frame -> conditional_normative:
    # membership/status provisions often describe institutional frame context,
    # but "in the event", "upon review", and similar clause scaffolding carry
    # the typed conditional force. Keep that conditional family above generic
    # frame evidence when both are present.
    if (
        frame_count > 0.0
        and has_frame_scope_context
        and has_structural_conditional_scope
        and has_explicit_conditional_scope
        and (
            has_statutory_scope_reference
            or has_temporal_status_scope
            or has_calendar_date_scope
        )
    ):
        conditional_floor = _scaled_competing_scope_backfill(
            source_count=max(frame_count, deontic_count, temporal_count, 1.0),
            ratio=0.4,
            minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
        )
        counts[conditional_family] = max(conditional_count, conditional_floor)
        conditional_count = float(counts.get(conditional_family, 0.0))

    # conditional_normative -> temporal:
    # when statutory structural conditionals only carry weak temporal cue tokens,
    # preserve temporal evidence so conditional scaffolding does not dominate.
    if (
        conditional_count > 0.0
        and has_structural_conditional_scope
        and not has_explicit_conditional_scope
        and has_temporal_scope
        and bool(signals.get("has_temporal_cue"))
        and has_deontic_scope
        and has_statutory_scope_reference
    ):
        temporal_increment = _scaled_competing_scope_backfill(
            source_count=max(deontic_count, conditional_count),
            ratio=0.3,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
        )
        counts[temporal_family] = temporal_count + min(
            _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            temporal_increment,
        )
        temporal_count = float(counts.get(temporal_family, 0.0))

    # temporal -> conditional_normative / deontic:
    # year/date/status metadata in statutory text can dominate the family counts
    # while the legal force is carried by conditional cross-references or
    # obligation phrases.  Keep those target families visible for ambiguity
    # selection instead of treating temporal evidence as exclusive.
    if (
        temporal_count > 0.0
        and has_temporal_scope
        and (
            has_statutory_scope_reference
            or has_frame_scope_context
            or has_temporal_status_scope
            or has_calendar_date_scope
        )
    ):
        if (
            temporal_count > conditional_count
            and has_structural_conditional_scope
            and (
                has_explicit_conditional_scope
                or has_statutory_scope_reference
                or has_purpose_scope_phrase
            )
        ):
            conditional_floor = _scaled_competing_scope_backfill(
                source_count=max(temporal_count, deontic_count, frame_count, 1.0),
                ratio=0.3,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_TEMPORAL_TO_CONDITIONAL_SCOPE_REINFORCEMENT_MAX,
            )
            counts[conditional_family] = max(conditional_count, conditional_floor)
            conditional_count = float(counts.get(conditional_family, 0.0))
        if (
            temporal_count > deontic_count
            and has_deontic_scope
            and (
                has_explicit_deontic_scope
                or has_temporal_status_scope
                or has_calendar_date_scope
                or has_direct_frame_scope_context
                or has_structural_authority_frame_scope
            )
            and (
                has_direct_frame_scope_context
                or has_temporal_status_scope
                or has_calendar_date_scope
                or has_structural_authority_frame_scope
            )
        ):
            deontic_floor = _scaled_competing_scope_backfill(
                source_count=max(temporal_count, conditional_count, frame_count, 1.0),
                ratio=0.3,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_TEMPORAL_TO_DEONTIC_SCOPE_REINFORCEMENT_MAX,
            )
            counts[deontic_family] = max(deontic_count, deontic_floor)
            deontic_count = float(counts.get(deontic_family, 0.0))

    # temporal -> deontic:
    # damp non-deadline temporal pressure when explicit deontic force co-occurs.
    if (
        temporal_count > deontic_count
        and has_temporal_scope
        and has_deontic_scope
        and has_explicit_deontic_scope
        and has_statutory_scope_reference
        and not has_temporal_deadline_scope
        and not has_explicit_conditional_scope
        and not (
            has_structural_conditional_scope
            and bool(signals.get("has_temporal_cue"))
        )
    ):
        temporal_cap = max(
            deontic_count,
            _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        if temporal_count > temporal_cap:
            temporal_overflow = temporal_count - temporal_cap
            counts[temporal_family] = temporal_cap + (
                0.25 * math.log1p(temporal_overflow)
            )
            temporal_count = float(counts.get(temporal_family, 0.0))

    # temporal -> deontic:
    # editorial effective-date boilerplate can overinflate temporal weight in
    # statutory notes even when deontic force governs the operative clause.
    if (
        temporal_count > deontic_count
        and has_temporal_scope
        and has_deontic_scope
        and has_statutory_scope_reference
        and has_editorial_frame_context
        and not bool(signals.get("has_deontic_scope_phrase"))
        and not has_explicit_conditional_scope
    ):
        editorial_temporal_cap = max(
            deontic_count + _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        if temporal_count > editorial_temporal_cap:
            temporal_overflow = temporal_count - editorial_temporal_cap
            counts[temporal_family] = editorial_temporal_cap + (
                0.2 * math.log1p(temporal_overflow)
            )
            temporal_count = float(counts.get(temporal_family, 0.0))

    # conditional_normative -> deontic / temporal:
    # statutory-reference conditionals without explicit "if/unless" clauses are often
    # mixed-scope scaffolding, so keep competing deontic and temporal evidence visible.
    if (
        conditional_count > 0.0
        and has_structural_conditional_scope
        and (
            not has_explicit_conditional_scope
            or has_non_clause_structural_conditional_scope
        )
    ):
        if has_deontic_scope and conditional_count >= deontic_count:
            deontic_maximum = (
                _DEONTIC_COMPETING_SCOPE_BACKFILL_MAX
                if not has_statutory_scope_reference
                else _STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX
            )
            deontic_floor = _scaled_competing_scope_backfill(
                source_count=conditional_count,
                ratio=0.24,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=deontic_maximum,
            )
            counts[deontic_family] = max(
                float(counts.get(deontic_family, 0.0)),
                deontic_floor,
            )
            deontic_count = float(counts.get(deontic_family, 0.0))
        if (
            has_temporal_scope
            and has_strong_temporal_scope
            and conditional_count >= temporal_count
        ):
            temporal_floor = _scaled_competing_scope_backfill(
                source_count=conditional_count,
                ratio=0.24,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
            )
            counts[temporal_family] = max(
                float(counts.get(temporal_family, 0.0)),
                temporal_floor,
            )
            temporal_count = float(counts.get(temporal_family, 0.0))
        if has_frame_scope_context and conditional_count >= frame_count:
            frame_floor = _scaled_competing_scope_backfill(
                source_count=conditional_count,
                ratio=0.24,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
            )
            counts[frame_family] = max(
                frame_count,
                frame_floor,
            )
            frame_count = float(counts.get(frame_family, 0.0))

            if (
                has_statutory_scope_reference
                and not has_deontic_scope
                and not has_temporal_scope
                and conditional_count > frame_count
            ):
                conditional_cap = max(
                    frame_count,
                    _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                )
                conditional_overflow = conditional_count - conditional_cap
                counts[conditional_family] = conditional_cap + (
                    0.2 * math.log1p(conditional_overflow)
                )

    # conditional_normative -> deontic:
    # explicit statutory conditional clauses can encode operative deontic force;
    # preserve deontic evidence when structural conditionals dominate counts.
    if (
        conditional_count > deontic_count
        and has_deontic_scope
        and has_explicit_conditional_scope
        and has_statutory_scope_reference
    ):
        deontic_increment = _scaled_competing_scope_backfill(
            source_count=conditional_count,
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=0.0,
            maximum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[deontic_family] = deontic_count + min(
            _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            deontic_increment,
        )

    deontic_count = float(counts.get(deontic_family, 0.0))
    temporal_count = float(counts.get(temporal_family, 0.0))
    conditional_count = float(counts.get(conditional_family, 0.0))
    frame_count = float(counts.get(frame_family, 0.0))

    # deontic -> temporal:
    # when temporal status/date context is explicit and conditional structure is
    # only statutory-reference scaffolding, preserve temporal runner-up evidence.
    if (
        deontic_count > temporal_count
        and has_statutory_scope_reference
        and has_temporal_scope
        and has_strong_temporal_scope
        and bool(signals.get("has_deontic_cue"))
        and not bool(signals.get("has_deontic_scope_phrase"))
        and not has_explicit_conditional_scope
    ):
        temporal_increment = _scaled_competing_scope_backfill(
            source_count=deontic_count,
            ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=0.0,
            maximum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        counts[temporal_family] = max(
            temporal_count,
            temporal_count + temporal_increment,
        )
        temporal_count = float(counts.get(temporal_family, 0.0))

    # deontic / temporal / conditional_normative -> frame:
    # in statutory structural-authority clauses ("shall have jurisdiction/power",
    # "authority of ..."), generic non-frame cues can swamp frame semantics.
    if (
        frame_count > 0.0
        and has_frame_scope_context
        and has_statutory_scope_reference
        and has_structural_authority_frame_scope
        and (
            deontic_count > frame_count
            or temporal_count > frame_count
            or conditional_count > frame_count
        )
    ):
        frame_floor = _scaled_competing_scope_backfill(
            source_count=max(
                frame_count,
                deontic_count,
                temporal_count,
                conditional_count,
            ),
            ratio=_REINFORCED_COMPETING_SCOPE_BACKFILL_RATIO,
            minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_TEMPORAL_TO_FRAME_SCOPE_REINFORCEMENT_MAX,
        )
        counts[frame_family] = max(
            frame_count,
            frame_floor,
        )
        frame_count = float(counts.get(frame_family, 0.0))

    # frame -> deontic / conditional_normative:
    # repeated generic frame cues ("authority", "jurisdiction", corporate
    # structure) can dominate statutory clauses that still contain operative
    # deontic force under conditional scope. Keep the typed normative evidence
    # competitive instead of letting structural frame context become the only
    # high-probability family.
    if (
        frame_count > max(deontic_count, conditional_count)
        and has_frame_scope_context
        and has_statutory_scope_reference
        and has_deontic_scope
        and has_structural_conditional_scope
        and (
            has_explicit_deontic_scope
            or has_conditional_scope_phrase
            or has_conditional_clause_scope
        )
    ):
        normative_anchor = max(
            deontic_count,
            conditional_count,
            _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        deontic_floor = _scaled_competing_scope_backfill(
            source_count=max(frame_count, normative_anchor),
            ratio=0.42,
            minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_DEONTIC_SCOPE_MAX,
        )
        conditional_floor = _scaled_competing_scope_backfill(
            source_count=max(frame_count, normative_anchor),
            ratio=0.38,
            minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
        )
        counts[deontic_family] = max(deontic_count, deontic_floor)
        counts[conditional_family] = max(conditional_count, conditional_floor)
        deontic_count = float(counts.get(deontic_family, 0.0))
        conditional_count = float(counts.get(conditional_family, 0.0))

        frame_cap = max(
            max(deontic_count, conditional_count)
            + _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
        if frame_count > frame_cap:
            frame_overflow = frame_count - frame_cap
            counts[frame_family] = frame_cap + (0.2 * math.log1p(frame_overflow))


def _apply_competing_deontic_temporal_scope_phrase_reinforcement(
    counts: Dict[str, float],
    signals: Mapping[str, bool],
) -> None:
    """Prefer phrase-grounded deontic/temporal signals in direct family competition."""
    deontic_family = ModalLogicFamily.DEONTIC.value
    temporal_family = ModalLogicFamily.TEMPORAL.value
    deontic_count = float(counts.get(deontic_family, 0.0))
    temporal_count = float(counts.get(temporal_family, 0.0))
    if deontic_count <= 0.0 or temporal_count <= 0.0:
        return
    has_temporal_scope = bool(signals.get("has_temporal_scope"))
    has_deontic_scope = bool(
        signals.get("has_deontic_scope")
        or signals.get("has_deontic_cue")
    )
    if not (has_temporal_scope and has_deontic_scope):
        return
    has_strong_temporal_scope = _has_strong_temporal_scope_signal(signals)
    has_deontic_scope_phrase = bool(signals.get("has_deontic_scope_phrase"))
    has_deontic_authorization_scope_phrase = bool(
        signals.get("has_deontic_authorization_scope_phrase")
    )
    has_deontic_report_duty_scope_phrase = bool(
        signals.get("has_deontic_report_duty_scope_phrase")
    )
    has_temporal_fiscal_scope_phrase = bool(
        signals.get("has_temporal_fiscal_scope_phrase")
    )
    has_temporal_deadline_cue = bool(signals.get("has_temporal_deadline_cue"))
    has_temporal_expended_scope_phrase = bool(
        signals.get("has_temporal_expended_scope_phrase")
    )
    if has_deontic_scope_phrase and not has_strong_temporal_scope:
        counts[deontic_family] = deontic_count + _DEONTIC_SCOPE_PHRASE_REINFORCEMENT
        deontic_count = float(counts.get(deontic_family, 0.0))
    if (
        has_deontic_authorization_scope_phrase
        and has_temporal_fiscal_scope_phrase
        and not has_temporal_deadline_cue
    ):
        counts[deontic_family] = deontic_count + _DEONTIC_SCOPE_PHRASE_REINFORCEMENT
        deontic_count = float(counts.get(deontic_family, 0.0))
    if (
        has_deontic_report_duty_scope_phrase
        and has_temporal_fiscal_scope_phrase
        and not has_temporal_deadline_cue
        and temporal_count >= deontic_count
    ):
        counts[deontic_family] = temporal_count + 0.01
        deontic_count = float(counts.get(deontic_family, 0.0))
    if has_temporal_expended_scope_phrase:
        counts[temporal_family] = temporal_count + _TEMPORAL_SCOPE_PHRASE_REINFORCEMENT


def _is_generic_frame_cue_debias_context(
    encoding: SpaCyLegalEncoding,
    signals: Mapping[str, bool],
) -> bool:
    explicit_conditional_scope = _has_explicit_conditional_scope(signals)
    has_competing_non_frame_scope = (
        bool(signals.get("has_deontic_scope"))
        or bool(signals.get("has_temporal_scope"))
        or explicit_conditional_scope
        or bool(signals.get("has_epistemic_scope"))
        or bool(signals.get("has_epistemic_cue"))
        or bool(signals.get("has_alethic_scope"))
        or bool(signals.get("has_alethic_cue"))
        or bool(signals.get("has_dynamic_scope"))
        or bool(signals.get("has_dynamic_cue"))
    )
    if not has_competing_non_frame_scope:
        return False
    has_compelling_non_frame_scope = (
        bool(signals.get("has_deontic_cue"))
        or bool(signals.get("has_deontic_scope_phrase"))
        or explicit_conditional_scope
        or bool(signals.get("has_conditional_scope_phrase"))
        or bool(signals.get("has_conditional_scope_token"))
        or bool(signals.get("has_temporal_scope_phrase"))
        or bool(signals.get("has_temporal_within_scope"))
        or bool(signals.get("has_temporal_status_scope"))
        or bool(signals.get("has_calendar_date_scope"))
        or (
            bool(signals.get("has_temporal_scope_token"))
            and (
                bool(signals.get("has_statutory_scope_reference"))
                or bool(signals.get("has_condition_or_exception_scope"))
                or bool(signals.get("has_deontic_scope"))
            )
        )
        or bool(signals.get("has_epistemic_scope_phrase"))
        or bool(signals.get("has_alethic_scope_phrase"))
        or bool(signals.get("has_dynamic_scope_phrase"))
    )
    if bool(signals.get("has_frame_scope_phrase")) and not has_compelling_non_frame_scope:
        return False
    if (
        bool(signals.get("has_frame_editorial_scope_phrase"))
        and not has_compelling_non_frame_scope
    ):
        return False
    frame_cues = [
        str(cue.cue).strip().lower()
        for cue in encoding.cues
        if cue.family == ModalLogicFamily.FRAME.value
    ]
    if not frame_cues:
        return bool(
            (
                signals.get("has_frame_scope_phrase")
                or signals.get("has_frame_editorial_scope_phrase")
            )
            and has_compelling_non_frame_scope
        )
    return all(cue in _GENERIC_FRAME_CUE_TERMS for cue in frame_cues)


def _has_explicit_conditional_scope(signals: Mapping[str, bool]) -> bool:
    """Return whether conditional scope is explicit beyond bare statutory references."""
    return bool(
        signals.get("has_condition_clause")
        or signals.get("has_exception_clause")
        or signals.get("has_conditional_scope_phrase")
        or signals.get("has_conditional_scope_token")
    )


def _has_strong_temporal_scope_signal(signals: Mapping[str, bool]) -> bool:
    """Return whether temporal scope has strong date/deadline-style evidence."""
    return bool(
        signals.get("has_calendar_date_scope")
        or signals.get("has_temporal_scope_phrase")
        or signals.get("has_temporal_within_scope")
        or signals.get("has_temporal_status_scope")
        or (
            bool(signals.get("has_temporal_scope_token"))
            and bool(signals.get("has_statutory_scope_reference"))
        )
    )


def _scope_signal_family_logit_boosts(signals: Mapping[str, bool]) -> Dict[str, float]:
    """Return deterministic logit boosts for scope-signaled families without cues."""
    boosts: Dict[str, float] = {}
    explicit_conditional_scope = _has_explicit_conditional_scope(signals)
    has_strong_temporal_scope = _has_strong_temporal_scope_signal(signals)
    has_non_status_temporal_phrase = bool(
        signals.get("has_temporal_scope_phrase")
        and not signals.get("has_temporal_status_scope")
    )
    has_explicit_temporal_scope = bool(
        signals.get("has_temporal_cue")
        or has_non_status_temporal_phrase
        or signals.get("has_temporal_within_scope")
        or signals.get("has_temporal_deadline_cue")
    )
    has_structural_temporal_scope = bool(
        signals.get("has_calendar_date_scope")
        or signals.get("has_temporal_status_scope")
        or signals.get("has_temporal_scope_token")
    )
    has_frame_context_signal = bool(
        signals.get("has_frame_context")
        or signals.get("has_frame_cue")
    )
    has_editorial_frame_context = bool(
        signals.get("has_frame_editorial_scope_phrase")
    )
    has_procedural_frame_context = bool(
        signals.get("has_frame_procedural_scope_phrase")
    )
    has_statutory_frame_context = bool(
        signals.get("has_statutory_scope_reference")
        and (
            signals.get("has_frame_context")
            or signals.get("has_frame_cue")
        )
    )
    has_structural_scope_context = bool(
        has_frame_context_signal
        or has_editorial_frame_context
        or has_statutory_frame_context
    )
    has_strong_temporal_scope = bool(
        signals.get("has_calendar_date_scope")
        or signals.get("has_temporal_scope_phrase")
        or signals.get("has_temporal_within_scope")
        or signals.get("has_temporal_status_scope")
        or (
            bool(signals.get("has_temporal_scope_token"))
            and (
                bool(signals.get("has_statutory_scope_reference"))
                or bool(signals.get("has_temporal_cue"))
            )
        )
    )
    if bool(signals.get("has_condition_or_exception_scope")):
        conditional_bonus = 0.9
        if explicit_conditional_scope:
            conditional_bonus += 0.15
        if (
            has_frame_context_signal
            and explicit_conditional_scope
            and not has_statutory_frame_context
        ):
            conditional_bonus += 0.1
        if has_statutory_frame_context:
            conditional_bonus += 0.35
            if (
                explicit_conditional_scope
                and not bool(
                    signals.get("has_deontic_scope")
                    or signals.get("has_deontic_cue")
                )
            ):
                conditional_bonus += 0.1
            if (
                explicit_conditional_scope
                and bool(signals.get("has_temporal_scope"))
            ):
                conditional_bonus += 0.15
        if (
            (bool(signals.get("has_deontic_scope")) or bool(signals.get("has_deontic_cue")))
            and (
                explicit_conditional_scope
                or bool(signals.get("has_statutory_scope_reference"))
            )
        ):
            conditional_bonus += 0.2
        if explicit_conditional_scope and bool(signals.get("has_temporal_scope")):
            conditional_bonus += 0.1
            if has_strong_temporal_scope:
                conditional_bonus += 0.05
        if (
            not explicit_conditional_scope
            and bool(signals.get("has_statutory_scope_reference"))
            and bool(signals.get("has_deontic_cue"))
            and not bool(signals.get("has_temporal_cue"))
        ):
            conditional_bonus = max(0.0, conditional_bonus - 0.2)
        boosts[ModalLogicFamily.CONDITIONAL_NORMATIVE.value] = conditional_bonus
    if bool(signals.get("has_deontic_scope")):
        deontic_bonus = 0.8
        if bool(signals.get("has_deontic_scope_phrase")):
            deontic_bonus += 0.2
        if (
            has_frame_context_signal
            and not has_statutory_frame_context
            and bool(
                signals.get("has_deontic_scope_phrase")
                or signals.get("has_deontic_cue")
            )
        ):
            deontic_bonus += 0.15
        if has_statutory_frame_context:
            deontic_bonus += 0.4
        if has_procedural_frame_context and bool(
            signals.get("has_deontic_scope_phrase")
            or signals.get("has_deontic_cue")
        ):
            deontic_bonus += 0.15
        if (
            bool(signals.get("has_condition_or_exception_scope"))
            and bool(
                signals.get("has_deontic_scope_phrase")
                or signals.get("has_deontic_cue")
            )
        ):
            deontic_bonus += 0.1
            if explicit_conditional_scope:
                deontic_bonus += 0.15
        if bool(signals.get("has_temporal_scope")):
            deontic_bonus += 0.35
            if not has_strong_temporal_scope and bool(
                signals.get("has_deontic_scope_phrase")
                or signals.get("has_deontic_cue")
            ):
                deontic_bonus += 0.15
            if bool(signals.get("has_deontic_cue")) and not bool(
                signals.get("has_deontic_scope_phrase")
            ):
                deontic_bonus += 0.1
            if bool(
                signals.get("has_deontic_scope_phrase")
                or signals.get("has_deontic_cue")
            ) and has_strong_temporal_scope:
                deontic_bonus += 0.15
        if has_statutory_frame_context and bool(
            signals.get("has_deontic_scope_phrase")
            or signals.get("has_deontic_cue")
        ):
            deontic_bonus += 0.15
        has_alethic_competition = bool(
            signals.get("has_alethic_scope")
            or signals.get("has_alethic_cue")
        )
        if has_alethic_competition:
            deontic_bonus += 0.35
            if (
                bool(signals.get("has_deontic_scope_phrase"))
                or bool(signals.get("has_deontic_cue"))
            ):
                deontic_bonus += 0.2
        if (
            bool(signals.get("has_purpose_scope_phrase"))
            and bool(
                signals.get("has_deontic_scope_phrase")
                or signals.get("has_deontic_cue")
            )
            and not bool(signals.get("has_temporal_scope"))
        ):
            deontic_bonus += 0.1
        if (
            bool(signals.get("has_deontic_cue"))
            and has_structural_temporal_scope
            and not has_explicit_temporal_scope
            and has_structural_scope_context
        ):
            deontic_bonus += 0.2
            if not bool(signals.get("has_statutory_scope_reference")):
                deontic_bonus += 0.45
        boosts[ModalLogicFamily.DEONTIC.value] = deontic_bonus
    temporal_bonus = 0.0
    if bool(signals.get("has_temporal_scope")):
        temporal_bonus += 1.2
        if (
            not has_strong_temporal_scope
            and (
                has_statutory_frame_context
                or bool(signals.get("has_deontic_scope"))
                or bool(signals.get("has_deontic_cue"))
                or explicit_conditional_scope
            )
        ):
            temporal_bonus = max(0.0, temporal_bonus - 0.35)
        if bool(signals.get("has_deontic_scope")) or bool(signals.get("has_deontic_cue")):
            temporal_bonus += 0.2
            if has_strong_temporal_scope:
                temporal_bonus += 0.15
                if bool(signals.get("has_deontic_cue")) and not bool(
                    signals.get("has_deontic_scope_phrase")
                ) and not bool(signals.get("has_statutory_scope_reference")):
                    temporal_bonus += 0.15
        if bool(signals.get("has_condition_or_exception_scope")) and has_strong_temporal_scope:
            temporal_bonus += 0.15
        if (
            has_statutory_frame_context
            and has_strong_temporal_scope
            and not has_editorial_frame_context
        ):
            temporal_bonus += 0.2
        if (
            has_frame_context_signal
            and has_strong_temporal_scope
            and not has_editorial_frame_context
        ):
            temporal_bonus += 0.2
    if (
        temporal_bonus > 0.0
        and has_structural_temporal_scope
        and not has_explicit_temporal_scope
        and bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
        and has_structural_scope_context
    ):
        temporal_noise_penalty = 0.65
        if has_editorial_frame_context:
            temporal_noise_penalty = max(temporal_noise_penalty, 1.0)
        if has_statutory_frame_context and bool(signals.get("has_deontic_cue")):
            temporal_noise_penalty = max(temporal_noise_penalty, 1.15)
        temporal_bonus = max(
            0.0,
            temporal_bonus - temporal_noise_penalty,
        )
    if (
        temporal_bonus > 0.0
        and bool(signals.get("has_temporal_status_scope"))
        and not has_explicit_temporal_scope
        and bool(signals.get("has_frame_scope_phrase"))
        and not bool(signals.get("has_statutory_scope_reference"))
        and not bool(signals.get("has_temporal_scope_phrase"))
    ):
        temporal_bonus = max(0.0, temporal_bonus - 0.55)
    if (
        temporal_bonus > 0.0
        and has_editorial_frame_context
        and not bool(signals.get("has_temporal_status_scope"))
        and not bool(signals.get("has_calendar_date_scope"))
        and not bool(
            signals.get("has_temporal_scope_phrase")
            or signals.get("has_temporal_within_scope")
        )
    ):
        temporal_bonus = max(0.0, temporal_bonus - 0.35)
    if has_strong_temporal_scope:
        temporal_bonus += 0.3
    if (
        temporal_bonus > 0.0
        and bool(signals.get("has_temporal_fiscal_scope_phrase"))
        and has_editorial_frame_context
        and bool(signals.get("has_statutory_scope_reference"))
        and not bool(
            signals.get("has_deontic_scope")
            or signals.get("has_deontic_cue")
        )
        and not explicit_conditional_scope
    ):
        temporal_bonus += 0.4
    if temporal_bonus > 0.0:
        boosts[ModalLogicFamily.TEMPORAL.value] = temporal_bonus
    if bool(signals.get("has_epistemic_scope")):
        epistemic_bonus = (
            0.7
            if bool(signals.get("has_epistemic_scope_phrase"))
            else 0.45
        )
        if has_frame_context_signal:
            epistemic_bonus += (
                0.15
                if bool(
                    signals.get("has_epistemic_scope_phrase")
                    or signals.get("has_epistemic_cue")
                )
                else 0.1
            )
        boosts[ModalLogicFamily.EPISTEMIC.value] = epistemic_bonus
    if bool(signals.get("has_alethic_scope")):
        alethic_bonus = (
            0.7
            if bool(signals.get("has_alethic_scope_phrase"))
            else 0.45
        )
        boosts[ModalLogicFamily.ALETHIC.value] = alethic_bonus
    dynamic_bonus = 0.0
    if bool(signals.get("has_dynamic_scope_phrase")):
        dynamic_bonus += 1.0
        if bool(signals.get("has_deontic_scope")) or bool(signals.get("has_deontic_cue")):
            dynamic_bonus += 0.25
    elif bool(signals.get("has_dynamic_scope")) and not (
        bool(signals.get("has_frame_scope_phrase"))
        or bool(signals.get("has_frame_editorial_scope_phrase"))
    ):
        dynamic_bonus += 0.7
        if bool(signals.get("has_deontic_scope")) or bool(signals.get("has_deontic_cue")):
            dynamic_bonus += 0.2
    if dynamic_bonus > 0.0:
        boosts[ModalLogicFamily.DYNAMIC.value] = dynamic_bonus
    return boosts


def modal_ambiguity_signals(encoding: SpaCyLegalEncoding) -> Dict[str, bool]:
    """Return deterministic lexical/contextual flags used by ambiguity policy."""
    condition_clauses = False
    exception_clauses = False
    for sentence in encoding.sentences:
        if _prefixed_clause_phrases(sentence.text, _CONDITION_PREFIXES):
            condition_clauses = True
        if _prefixed_clause_phrases(sentence.text, _EXCEPTION_PREFIXES):
            exception_clauses = True
        if condition_clauses and exception_clauses:
            break
    token_terms = {
        token.normalized()
        for token in encoding.tokens
        if token.is_alpha
    }
    normalized_text = encoding.normalized_text.lower()
    cue_families = {cue.family for cue in encoding.cues}
    conditional_scope_phrase = _contains_scope_phrase(
        normalized_text, _CONDITIONAL_SCOPE_PHRASES
    )
    purpose_scope_phrase = _contains_scope_phrase(
        normalized_text, _PURPOSE_SCOPE_PHRASES
    )
    statutory_scope_reference = _contains_scope_phrase(
        normalized_text, _STATUTORY_SCOPE_REFERENCE_PHRASES
    )
    conditional_scope_token = bool(token_terms & _CONDITIONAL_SCOPE_TOKENS)
    alethic_scope_phrase = _contains_scope_phrase(
        normalized_text, _ALETHIC_SCOPE_PHRASES
    )
    deontic_scope_phrase = _contains_scope_phrase(
        normalized_text, _DEONTIC_SCOPE_PHRASES
    )
    deontic_appropriations_scope_phrase = _contains_scope_phrase(
        normalized_text, _DEONTIC_APPROPRIATIONS_SCOPE_PHRASES
    )
    deontic_authorization_scope_phrase = _contains_scope_phrase(
        normalized_text, _DEONTIC_AUTHORIZATION_SCOPE_PHRASES
    )
    deontic_corporate_powers_scope_phrase = _contains_scope_phrase(
        normalized_text, _DEONTIC_CORPORATE_POWERS_SCOPE_PHRASES
    )
    deontic_report_duty_scope_phrase = _contains_scope_phrase(
        normalized_text, _DEONTIC_REPORT_DUTY_SCOPE_PHRASES
    )
    deontic_citation_authority_scope_phrase = _contains_scope_phrase(
        normalized_text, _DEONTIC_CITATION_AUTHORITY_SCOPE_PHRASES
    )
    epistemic_scope_phrase = _contains_scope_phrase(
        normalized_text, _EPISTEMIC_SCOPE_PHRASES
    )
    temporal_scope_phrase = _contains_scope_phrase(
        normalized_text, _TEMPORAL_SCOPE_PHRASES
    )
    temporal_fiscal_scope_phrase = _contains_scope_phrase(
        normalized_text, _TEMPORAL_FISCAL_SCOPE_PHRASES
    )
    temporal_expended_scope_phrase = _contains_scope_phrase(
        normalized_text, _TEMPORAL_EXPENDED_SCOPE_PHRASES
    )
    temporal_deadline_cue = any(
        cue.family == ModalLogicFamily.TEMPORAL.value
        and cue.cue.lower() in _TEMPORAL_DEADLINE_CUE_TERMS
        for cue in encoding.cues
    )
    dynamic_scope_phrase = _contains_scope_phrase(
        normalized_text, _DYNAMIC_SCOPE_PHRASES
    )
    calendar_date_scope = bool(
        _CALENDAR_DATE_RE.search(normalized_text)
        or _MONTH_DAY_RE.search(normalized_text)
    )
    temporal_within_scope = _has_temporal_within_scope(
        encoding.normalized_text,
        encoding.tokens,
    )
    temporal_scope_token = bool(
        token_terms & _TEMPORAL_STRONG_SCOPE_TOKENS
    )
    temporal_status_scope_token = bool(
        token_terms & _TEMPORAL_STATUS_SCOPE_TOKENS
    )
    section_defined_scope = bool(
        _SECTION_DEFINED_SCOPE_RE.search(encoding.normalized_text)
    )
    vacant_section_scope = bool(
        _VACANT_SECTION_STATUS_RE.search(encoding.normalized_text)
    )
    alethic_scope = (
        bool(token_terms & _ALETHIC_SCOPE_TOKENS)
        or bool(alethic_scope_phrase)
        or section_defined_scope
    )
    temporal_scope = (
        bool(token_terms & (_TEMPORAL_SCOPE_TOKENS - {"within", "after"}))
        or temporal_within_scope
        or temporal_scope_token
        or temporal_status_scope_token
        or bool(temporal_scope_phrase)
        or calendar_date_scope
    )
    deontic_scope = (
        bool(token_terms & _DEONTIC_SCOPE_TOKENS)
        or bool(deontic_scope_phrase)
        or ModalLogicFamily.DEONTIC.value in cue_families
    )
    epistemic_scope = (
        bool(token_terms & _EPISTEMIC_SCOPE_TOKENS)
        or bool(epistemic_scope_phrase)
        or ModalLogicFamily.EPISTEMIC.value in cue_families
    )
    doxastic_scope = ModalLogicFamily.DOXASTIC.value in cue_families
    dynamic_scope = (
        bool(token_terms & _DYNAMIC_SCOPE_TOKENS)
        or bool(dynamic_scope_phrase)
        or ModalLogicFamily.DYNAMIC.value in cue_families
    )
    frame_scope_phrase = _contains_scope_phrase(
        normalized_text, _FRAME_SCOPE_PHRASES
    )
    frame_structural_authority_scope_phrase = _contains_scope_phrase(
        normalized_text, _FRAME_STRUCTURAL_AUTHORITY_SCOPE_PHRASES
    )
    frame_procedural_scope_phrase = _contains_scope_phrase(
        normalized_text, _FRAME_PROCEDURAL_SCOPE_PHRASES
    )
    frame_editorial_scope_phrase = _contains_scope_phrase(
        normalized_text, _FRAME_EDITORIAL_SCOPE_PHRASES
    )
    frame_context = (
        bool(token_terms & _FRAME_CONTEXT_TOKENS)
        or bool(frame_scope_phrase)
        or vacant_section_scope
        or bool(frame_structural_authority_scope_phrase)
        or bool(frame_procedural_scope_phrase)
        or bool(frame_editorial_scope_phrase)
    )
    statutory_status_frame_scope = bool(
        frame_context
        and (
            statutory_scope_reference
            or temporal_status_scope_token
            or vacant_section_scope
            or frame_editorial_scope_phrase
            or frame_scope_phrase
        )
        and (
            temporal_status_scope_token
            or vacant_section_scope
            or frame_editorial_scope_phrase
            or frame_scope_phrase
        )
    )
    deontic_scope_terms = token_terms & _DEONTIC_SCOPE_TOKENS
    has_required_only_deontic_scope = bool(deontic_scope_terms) and deontic_scope_terms.issubset(
        _DEONTIC_REQUIRED_ONLY_SCOPE_TOKENS
    )
    if (
        deontic_scope
        and has_required_only_deontic_scope
        and temporal_status_scope_token
        and frame_context
        and not bool(deontic_scope_phrase)
        and ModalLogicFamily.DEONTIC.value not in cue_families
    ):
        deontic_scope = False
    return {
        "has_alethic_cue": ModalLogicFamily.ALETHIC.value in cue_families,
        "has_alethic_scope": alethic_scope or ModalLogicFamily.ALETHIC.value in cue_families,
        "has_alethic_scope_phrase": bool(alethic_scope_phrase),
        "has_definition_scope": section_defined_scope,
        "has_vacant_section_scope": vacant_section_scope,
        "has_condition_clause": condition_clauses,
        "has_conditional_scope_token": conditional_scope_token,
        "has_conditional_scope_phrase": conditional_scope_phrase,
        "has_purpose_scope_phrase": purpose_scope_phrase,
        "has_statutory_scope_reference": statutory_scope_reference,
        "has_exception_clause": exception_clauses,
        "has_condition_or_exception_scope": (
            condition_clauses
            or exception_clauses
            or conditional_scope_phrase
            or statutory_scope_reference
            or conditional_scope_token
        ),
        "has_calendar_date_scope": calendar_date_scope,
        "has_deontic_cue": ModalLogicFamily.DEONTIC.value in cue_families,
        "has_deontic_scope": deontic_scope,
        "has_deontic_scope_phrase": bool(deontic_scope_phrase),
        "has_deontic_appropriations_scope_phrase": bool(
            deontic_appropriations_scope_phrase
        ),
        "has_deontic_authorization_scope_phrase": bool(
            deontic_authorization_scope_phrase
        ),
        "has_deontic_corporate_powers_scope_phrase": bool(
            deontic_corporate_powers_scope_phrase
        ),
        "has_deontic_report_duty_scope_phrase": bool(
            deontic_report_duty_scope_phrase
        ),
        "has_deontic_citation_authority_scope_phrase": bool(
            deontic_citation_authority_scope_phrase
        ),
        "has_doxastic_cue": ModalLogicFamily.DOXASTIC.value in cue_families,
        "has_doxastic_scope": doxastic_scope,
        "has_dynamic_cue": ModalLogicFamily.DYNAMIC.value in cue_families,
        "has_dynamic_scope": dynamic_scope,
        "has_dynamic_scope_phrase": bool(dynamic_scope_phrase),
        "has_epistemic_cue": ModalLogicFamily.EPISTEMIC.value in cue_families,
        "has_epistemic_scope": epistemic_scope,
        "has_epistemic_scope_phrase": bool(epistemic_scope_phrase),
        "has_temporal_scope": temporal_scope or ModalLogicFamily.TEMPORAL.value in cue_families,
        "has_temporal_cue": ModalLogicFamily.TEMPORAL.value in cue_families,
        "has_temporal_scope_phrase": bool(temporal_scope_phrase),
        "has_temporal_fiscal_scope_phrase": bool(temporal_fiscal_scope_phrase),
        "has_temporal_deadline_cue": temporal_deadline_cue,
        "has_temporal_expended_scope_phrase": bool(temporal_expended_scope_phrase),
        "has_temporal_scope_token": temporal_scope_token,
        "has_temporal_status_scope": temporal_status_scope_token,
        "has_temporal_within_scope": temporal_within_scope,
        "has_frame_context": frame_context,
        "has_frame_editorial_scope_phrase": bool(frame_editorial_scope_phrase),
        "has_frame_procedural_scope_phrase": bool(frame_procedural_scope_phrase),
        "has_frame_scope_phrase": bool(frame_scope_phrase),
        "has_frame_structural_authority_scope_phrase": bool(
            frame_structural_authority_scope_phrase
        ),
        "has_statutory_status_frame_scope": statutory_status_frame_scope,
        "has_frame_cue": ModalLogicFamily.FRAME.value in cue_families,
    }


def _frame_logit_bonus(signals: Mapping[str, bool]) -> float:
    """Return deterministic frame-family logit bonus from structural signals."""
    explicit_conditional_scope = _has_explicit_conditional_scope(signals)
    has_strong_temporal_scope = _has_strong_temporal_scope_signal(signals)
    has_procedural_frame_signal = bool(
        signals.get("has_frame_procedural_scope_phrase")
    )
    has_editorial_or_direct_frame_signal = bool(
        signals.get("has_frame_scope_phrase")
        or signals.get("has_frame_editorial_scope_phrase")
        or has_procedural_frame_signal
        or signals.get("has_frame_cue")
    )
    has_non_frame_scope_competition = bool(
        signals.get("has_deontic_scope")
        or signals.get("has_deontic_cue")
        or signals.get("has_temporal_scope")
        or signals.get("has_temporal_scope_phrase")
        or signals.get("has_temporal_within_scope")
        or signals.get("has_dynamic_scope")
        or signals.get("has_dynamic_cue")
        or explicit_conditional_scope
    )
    bonus = 0.0
    if bool(signals.get("has_frame_context")):
        frame_context_bonus = 0.6
        if (
            not has_editorial_or_direct_frame_signal
            and has_non_frame_scope_competition
        ):
            frame_context_bonus = 0.2
        bonus += frame_context_bonus
    if bool(signals.get("has_statutory_scope_reference")):
        statutory_bonus = 0.8
        if (
            not has_editorial_or_direct_frame_signal
            and (
                explicit_conditional_scope
                or bool(signals.get("has_deontic_scope"))
                or (
                    bool(signals.get("has_temporal_scope"))
                    and has_strong_temporal_scope
                )
                or bool(signals.get("has_dynamic_scope"))
                or bool(signals.get("has_dynamic_cue"))
            )
        ):
            statutory_bonus = 0.2
        elif (
            not has_editorial_or_direct_frame_signal
            and bool(signals.get("has_temporal_scope"))
        ):
            statutory_bonus = 0.35
        bonus += statutory_bonus
    if has_procedural_frame_signal:
        bonus += 0.8
    if bool(signals.get("has_frame_scope_phrase")):
        bonus += 1.2
    if bool(signals.get("has_frame_editorial_scope_phrase")):
        bonus += 2.2
    if bool(signals.get("has_frame_cue")):
        frame_cue_bonus = 2.5
        if (
            bool(signals.get("has_temporal_scope"))
            and bool(signals.get("has_temporal_cue"))
            and not bool(signals.get("has_frame_editorial_scope_phrase"))
            and not bool(signals.get("has_statutory_scope_reference"))
            and not explicit_conditional_scope
            and not bool(signals.get("has_deontic_scope"))
        ):
            frame_cue_bonus = 1.5
        bonus += frame_cue_bonus
    if (
        bool(signals.get("has_frame_cue"))
        and bool(signals.get("has_frame_editorial_scope_phrase"))
        and bool(signals.get("has_frame_scope_phrase"))
        and bool(signals.get("has_condition_or_exception_scope"))
        and _has_explicit_conditional_scope(signals)
        and bool(signals.get("has_temporal_status_scope"))
        and bool(signals.get("has_statutory_scope_reference"))
        and not bool(signals.get("has_temporal_deadline_cue"))
    ):
        bonus += 1.9
    if (
        bool(signals.get("has_deontic_scope"))
        and bool(signals.get("has_condition_or_exception_scope"))
        and _has_explicit_conditional_scope(signals)
        and bool(signals.get("has_statutory_scope_reference"))
        and has_editorial_or_direct_frame_signal
    ):
        reinforced_frame_bonus = 1.2
        if bool(signals.get("has_frame_scope_phrase")):
            reinforced_frame_bonus += 0.5
        if bool(signals.get("has_frame_editorial_scope_phrase")):
            reinforced_frame_bonus += 0.5
        if bool(signals.get("has_temporal_scope")):
            reinforced_frame_bonus += 0.3
        bonus += reinforced_frame_bonus
    return bonus


def _debias_frame_bonus_for_generic_cues(signals: Mapping[str, bool]) -> float:
    """Retain discounted structural frame context while removing generic cue dominance."""
    structural_bonus = 0.0
    if bool(signals.get("has_frame_context")):
        structural_bonus += 0.6
    if bool(signals.get("has_statutory_scope_reference")):
        structural_bonus += 0.8
    if bool(signals.get("has_frame_procedural_scope_phrase")):
        structural_bonus += 0.8
    if bool(signals.get("has_frame_scope_phrase")):
        structural_bonus += 1.2
    if bool(signals.get("has_frame_editorial_scope_phrase")):
        structural_bonus += 2.2
    if structural_bonus <= 0.0:
        return 0.0
    debiased_bonus = structural_bonus * _GENERIC_FRAME_STRUCTURAL_BONUS_DEBIAS_FACTOR
    if (
        bool(signals.get("has_deontic_scope"))
        and bool(signals.get("has_condition_or_exception_scope"))
        and _has_explicit_conditional_scope(signals)
        and bool(signals.get("has_statutory_scope_reference"))
        and bool(
            signals.get("has_frame_scope_phrase")
            or signals.get("has_frame_editorial_scope_phrase")
            or signals.get("has_frame_cue")
        )
    ):
        reinforced_bonus = 1.4
        if bool(signals.get("has_temporal_scope")):
            reinforced_bonus += 0.3
        debiased_bonus += reinforced_bonus
    if (
        bool(signals.get("has_frame_cue"))
        and bool(signals.get("has_frame_editorial_scope_phrase"))
        and bool(signals.get("has_frame_scope_phrase"))
        and bool(signals.get("has_condition_or_exception_scope"))
        and _has_explicit_conditional_scope(signals)
        and bool(signals.get("has_temporal_status_scope"))
        and bool(signals.get("has_statutory_scope_reference"))
        and not bool(signals.get("has_temporal_deadline_cue"))
    ):
        debiased_bonus += 1.9
    return debiased_bonus


def _contains_scope_phrase(text: str, phrases: Sequence[str]) -> bool:
    for phrase in phrases:
        if re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text):
            return True
    return False


def _unique_preserve_order(features: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for feature in features:
        if feature in seen:
            continue
        seen.add(feature)
        result.append(feature)
    return result


def _sentence_for_cue(
    sentences: Sequence[SpaCySentenceFeature],
    cue: SpaCyModalCueFeature,
) -> SpaCySentenceFeature:
    for sentence in sentences:
        if sentence.start_char <= cue.start_char < sentence.end_char:
            return sentence
    return SpaCySentenceFeature(text="", start_char=cue.start_char, end_char=cue.end_char)


def _tokens_for_span(
    tokens: Sequence[SpaCyTokenFeature],
    start_char: int,
    end_char: int,
) -> List[SpaCyTokenFeature]:
    return [
        token
        for token in tokens
        if token.start_char < end_char and token.end_char > start_char
    ]


def _predicate_from_tokens(
    tokens: Sequence[SpaCyTokenFeature],
    cue: SpaCyModalCueFeature,
) -> ModalIRPredicate:
    after_cue = [
        token.normalized()
        for token in tokens
        if token.start_char >= cue.end_char and token.is_alpha and not token.is_stop
    ]
    before_cue = [
        token.normalized()
        for token in tokens
        if token.end_char <= cue.start_char and token.is_alpha and not token.is_stop
    ]
    predicate_terms = after_cue[:6] or before_cue[-6:] or [cue.label]
    arguments = []
    if before_cue:
        arguments.append(f"actor:{'_'.join(before_cue[-4:])}")
    if after_cue:
        arguments.append(f"scope:{'_'.join(after_cue[:4])}")
    return ModalIRPredicate(
        name="_".join(predicate_terms),
        arguments=arguments,
        role=_role_for_cue(cue),
    )


def _role_for_cue(cue: SpaCyModalCueFeature) -> str:
    if cue.family == ModalLogicFamily.CONDITIONAL_NORMATIVE.value:
        return "condition"
    if cue.family == ModalLogicFamily.TEMPORAL.value:
        return "temporal_scope"
    if cue.family == ModalLogicFamily.FRAME.value:
        return "frame"
    return "clause"


def _conditions_and_exceptions_from_sentence(sentence_text: str) -> tuple[List[str], List[str]]:
    return (
        _prefixed_clause_phrases(sentence_text, _CONDITION_PREFIXES),
        _prefixed_clause_phrases(sentence_text, _EXCEPTION_PREFIXES),
    )


def _prefixed_clause_phrases(segment_text: str, prefixes: Sequence[str]) -> List[str]:
    normalized = _normalize(segment_text)
    phrases: List[str] = []
    for prefix in sorted(prefixes, key=lambda value: (-len(value), value)):
        pattern = re.compile(rf"(?<!\w){re.escape(prefix)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(normalized):
            fragment = normalized[match.start() :]
            fragment = _CLAUSE_DELIMITER_RE.split(fragment, maxsplit=1)[0]
            phrase = _normalized_clause_phrase(fragment)
            if phrase and phrase not in phrases:
                phrases.append(phrase)
    return phrases


def _normalized_clause_phrase(text: str) -> str:
    tokens = _CLAUSE_TOKEN_RE.findall(text.lower())
    return " ".join(tokens[:18]).strip()


__all__ = [
    "modal_ambiguity_signals",
    "SpaCyLegalEncoder",
    "SpaCyLegalEncoding",
    "SpaCyModalCodec",
    "SpaCyModalCueFeature",
    "SpaCyModalDecoder",
    "SpaCyModalIRCompiler",
    "SpaCySentenceFeature",
    "SpaCyTokenFeature",
    "ranked_modal_families",
]
