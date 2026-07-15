"""Deterministic legal text parser for modal IR scaffolding."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

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
_SEGMENT_RE = re.compile(r"[^.;:\n]+[.;:]?")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")
_CLAUSE_DELIMITER_RE = re.compile(r"[,;:\n.]")
_CONDITION_PREFIXES = ("provided that", "subject to", "only after", "if", "when")
_EXCEPTION_PREFIXES = ("except that", "except as", "unless", "except")
_USCODE_CODIFICATION_HINT_RE = re.compile(
    r"\b(?:transferred|editorially reclassified|codification)\b",
    re.IGNORECASE,
)
_USCODE_DECLARATIVE_STATEMENT_HINT_RE = re.compile(
    r"\b(?:it\s+is\s+the\s+sense\s+of\s+the\s+congress|"
    r"it\s+is\s+the\s+purpose\s+of\s+this\s+(?:chapter|subchapter|title|section)|"
    r"there\s+is\s+established|there\s+are\s+established)\b",
    re.IGNORECASE,
)
_USCODE_EDITORIAL_STATUS_HINT_RE = re.compile(
    r"\b(?:repealed|omitted|reserved|vacant|renumbered|terminated)\b",
    re.IGNORECASE,
)
_USCODE_EDITORIAL_NOTE_CONTEXT_RE = re.compile(
    r"\b(?:editorial\s+notes|historical\s+and\s+revision\s+notes|"
    r"codification|formerly\s+classified|reclassified|renumbered|repealed|"
    r"transferred|statutory\s+notes)\b",
    re.IGNORECASE,
)
_USCODE_LEGISLATIVE_HISTORY_ABBREVIATION_RE = re.compile(
    r"(?:\b(?:act|acts)\b|\bch\.|\bpub\.\s*l\.|\bstat\.|\brelated\s+to\b)",
    re.IGNORECASE,
)
_USCODE_EDITORIAL_PERMISSION_CUES = frozenset({"allowed", "authorized", "permitted"})
_USCODE_EDITORIAL_REQUIRED_CUES = frozenset({"required", "requires", "require"})
_USCODE_EDITORIAL_DEONTIC_HISTORY_CUE_PREFIXES = (
    _USCODE_EDITORIAL_REQUIRED_CUES
    | _USCODE_EDITORIAL_PERMISSION_CUES
    | frozenset({"authorization"})
)
_USCODE_EDITORIAL_HISTORY_CUE_FAMILIES = frozenset(
    {
        ModalLogicFamily.CONDITIONAL_NORMATIVE,
        ModalLogicFamily.DEONTIC,
        ModalLogicFamily.TEMPORAL,
    }
)
_USCODE_REPEALED_HISTORY_PREFIX_RE = re.compile(
    r"\b(?:section|sections?)\s*,?\s*(?:acts?|pub\.?\s*l\.?|ch\.|"
    r"[A-Z][a-z]{2,8}\.\s+\d{1,2},\s+\d{4}|"
    r"\d+\s+stat\.)",
    re.IGNORECASE,
)
_USCODE_SECTION_REF_PREFIX_RE = r"(?:§{1,2}\s*|\bsec(?:tion)?s?\.?\s*)"
_USCODE_OPTIONAL_SECTION_REF_PREFIX_RE = rf"(?:{_USCODE_SECTION_REF_PREFIX_RE})?"
_USCODE_SECTION_PREFIX_SEGMENT_RE = re.compile(
    r"^\s*sec(?:tion)?s?\.?\s*$",
    re.IGNORECASE,
)
_USCODE_SECTION_ID_SEGMENT_RE = re.compile(
    r"^\s*[0-9A-Za-z][0-9A-Za-z.\-\u2010-\u2015]*\b",
    re.IGNORECASE,
)
_USCODE_CITATION_MARKER_RE = re.compile(
    r"\bU\.?\s*S\.?\s*C\.?(?!\w)",
    re.IGNORECASE,
)
_USCODE_GPO_SOURCE_BOILERPLATE_RE = re.compile(
    r"\s+From\s+the\s+U(?:\.?\s*$|\.?\s*S\.?\s+Government\s+Publishing\s+Office\b)",
    re.IGNORECASE,
)
_USCODE_CITATION_SECTION_RE = re.compile(
    rf"\bU\.?\s*S\.?\s*C\.?(?!\w)\s*{_USCODE_OPTIONAL_SECTION_REF_PREFIX_RE}([0-9A-Za-z.\-]+)\b",
    re.IGNORECASE,
)
_USCODE_TRAILING_SECTION_PUNCT_RE = re.compile(r"[.;:]+$")
_USCODE_SECTION_DASH_VARIANT_RE = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]")
_USCODE_SECTION_DASH_PATTERN = r"\s*(?:-|[\u2010\u2011\u2012\u2013\u2014\u2015\u2212])\s*"
_USCODE_SECTION_REF_SUFFIX_RE = r"(?:\b|[.)\-:\u2012\u2013\u2014])"
_USCODE_SECTION_HEADING_SHORT_MAX_TOKENS = 24
_USCODE_SECTION_HEADING_EXTENDED_MAX_TOKENS = 80
_USCODE_SUBSECTION_MARKER_RE = re.compile(
    r"\s+\((?:[a-z]{1,3}|[0-9]{1,3}|[ivxlcdm]{1,6})\)\s+",
    re.IGNORECASE,
)
_USCODE_SUBSECTION_HEADING_RE = re.compile(
    r"(?P<heading>\((?:[a-z]{1,3}|[0-9]{1,3}|[ivxlcdm]{1,6})\)\s+"
    r"[A-Z][A-Za-z0-9' /,&()\-]{1,96}?\s*\.)\s*(?:-|--|[\u2012-\u2015])",
    re.IGNORECASE,
)
_USCODE_SUBSECTION_HEADING_PREFIX_MAX_CHARS = 220
_USCODE_SUBSECTION_HEADING_PREFIX_MAX_TOKENS = 24
_USCODE_SUBSECTION_HEADING_BODY_MIN_TOKENS = 40
_USCODE_HEADING_ONLY_MAX_TOKENS = 12
_USCODE_HEADING_ONLY_EXTENDED_MAX_TOKENS = 18
_USCODE_HEADING_ONLY_MIN_TOKENS = 1
_USCODE_EMBEDDED_HEADING_WINDOW_MAX_CHARS = 260
_USCODE_HEADING_ONLY_VERB_HINT_RE = re.compile(
    r"\b(?:shall|must|may|is|are|was|were|be|been|being|has|have|had|"
    r"will|would|should|can|could|do|does|did)\b",
    re.IGNORECASE,
)
_USCODE_HEADING_ONLY_LEADING_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "any",
        "each",
        "no",
        "that",
        "the",
        "these",
        "this",
        "those",
    }
)
_USCODE_HEADING_ONLY_ARTICLE_ALLOWED_LEAD = "the"
_USCODE_HEADING_ONLY_ARTICLE_BANNED_SECOND_TOKENS = frozenset({"term", "terms"})
_USCODE_HEADING_ONLY_ARTICLE_NOUN_HINTS = frozenset(
    {
        "application",
        "applications",
        "appropriation",
        "appropriations",
        "authority",
        "authorization",
        "authorizations",
        "benefits",
        "compensation",
        "declaration",
        "definitions",
        "duties",
        "expense",
        "expenses",
        "finding",
        "findings",
        "grant",
        "grants",
        "hearing",
        "hearings",
        "institution",
        "institutions",
        "lands",
        "motion",
        "motions",
        "notice",
        "notification",
        "notifications",
        "oath",
        "office",
        "offices",
        "policy",
        "purpose",
        "procedures",
        "proceeding",
        "proceedings",
        "provisions",
        "commission",
        "commissions",
        "condition",
        "conditions",
        "requirements",
        "reservation",
        "reservations",
        "review",
        "rights",
        "use",
        "uses",
        "withdrawal",
        "withdrawals",
    }
)
_USCODE_HEADING_ONLY_EXTENDED_NOUN_HINTS = frozenset(
    {
        *_USCODE_HEADING_ONLY_ARTICLE_NOUN_HINTS,
        "act",
        "acts",
        "administrative",
        "adjudication",
        "adjudications",
        "appeal",
        "appeals",
        "certification",
        "compliance",
        "control",
        "enforcement",
        "implementation",
        "project",
        "projects",
        "procedural",
        "procedure",
        "procedures",
    }
)
_USCODE_HEADING_ONLY_EXTENDED_MIN_SIGNAL_TOKENS = 2
_USCODE_DECLARATIVE_STANDALONE_MAX_TOKENS = 56
_USCODE_DECLARATIVE_STANDALONE_START_RE = re.compile(
    r"^\s*(?:there\s+is\s+established|there\s+are\s+established|"
    r"it\s+is\s+the\s+sense\s+of\s+the\s+congress|"
    r"it\s+is\s+the\s+purpose\s+of\s+this\s+(?:chapter|subchapter|title|section))\b",
    re.IGNORECASE,
)
_USCODE_PROCEDURAL_CLAUSE_KEYWORD_RE = re.compile(
    r"\b(?:administrative|appeal|appeals|hearing|notice|petition|petitions|"
    r"procedure|procedures|review)\b",
    re.IGNORECASE,
)
_USCODE_PROCEDURAL_CLAUSE_VERB_RE = re.compile(
    r"\b(?:appl(?:y|ies)|cover(?:s)?|establish(?:ed|es)|govern(?:ed|s)?|"
    r"include(?:d|s)?|provide(?:d|s)?|remain(?:s)?)\b",
    re.IGNORECASE,
)
_USCODE_PROCEDURAL_CLAUSE_MIN_TOKENS = 6
_USCODE_PROCEDURAL_CLAUSE_MAX_TOKENS = 42
_USCODE_ADMINISTRATIVE_PROCEDURE_RESIDUAL_MAX_TOKENS = 96
_USCODE_ADMINISTRATIVE_PROCEDURE_PHRASE_RE = re.compile(
    r"\b(?:administrative\s+(?:notice|review|hearing|procedure|procedures)|"
    r"administrative\s+(?:proceeding|proceedings|record|records)|"
    r"(?:administrative|public)\s+(?:recommendation|recommendations|"
    r"report|reports|statement|statements)|"
    r"(?:recommendation|recommendations|report|reports|statement|statements)\s+"
    r"(?:for|on|after)\s+(?:administrative|public)\s+(?:review|comment|hearing)|"
    r"notice\s+and\s+hearing|notice\s+of\s+(?:hearing|proceeding|proceedings)|"
    r"opportunity\s+for\s+hearing|public\s+hearing|"
    r"hearing\s+(?:procedure|procedures|requirements|record|records)|"
    r"review\s+(?:procedure|procedures|requirements)|"
    r"appeal\s+(?:procedure|procedures|rights)|"
    r"petition\s+(?:procedure|procedures)|"
    r"(?:public\s+)?notice\s+and\s+(?:opportunity\s+to\s+)?comment|"
    r"opportunity\s+(?:for|to)\s+(?:public\s+)?comment|"
    r"(?:public\s+)?comment\s+period|"
    r"(?:public\s+)?comments?\s+(?:on|concerning|regarding)\s+"
    r"(?:proposed|administrative|agency)\b|"
    r"adjudication\s+(?:procedure|procedures|requirements|record|records)|"
    r"(?:record|records)\s+of\s+(?:hearing|proceeding|proceedings)|"
    r"(?:hearing|proceeding|proceedings)\s+(?:record|records|evidence|testimony))\b",
    re.IGNORECASE,
)
_USCODE_ADMINISTRATIVE_PROCEDURE_SIGNAL_TOKENS = frozenset(
    {
        "administrative",
        "adjudication",
        "adjudications",
        "appeal",
        "appeals",
        "comment",
        "comments",
        "hearing",
        "hearings",
        "investigation",
        "investigations",
        "notice",
        "petition",
        "petitions",
        "proceeding",
        "proceedings",
        "procedure",
        "procedures",
        "recommendation",
        "recommendations",
        "record",
        "records",
        "report",
        "reports",
        "requirements",
        "review",
        "statement",
        "statements",
        "testimony",
    }
)
_USCODE_ADMINISTRATIVE_FRAME_RESIDUAL_MAX_TOKENS = 72
_USCODE_ADMINISTRATIVE_FRAME_CONTEXT_TOKENS = frozenset(
    {
        "administration",
        "administrative",
        "administrator",
        "agency",
        "agencies",
        "board",
        "commission",
        "committee",
        "department",
        "director",
        "federal",
        "officer",
        "officers",
        "secretarial",
        "secretary",
    }
)
_USCODE_ADMINISTRATIVE_FRAME_PROCESS_TOKENS = frozenset(
    {
        "approval",
        "approvals",
        "certification",
        "certifications",
        "consultation",
        "consultations",
        "coordination",
        "determination",
        "determinations",
        "evaluation",
        "evaluations",
        "peer",
        "procedure",
        "procedures",
        "process",
        "processes",
        "record",
        "records",
        "review",
        "reviews",
    }
)
_USCODE_RESIDUAL_SPAN_MIN_TOKENS = 6
_USCODE_RESIDUAL_SPAN_MAX_TOKENS = 120
_USCODE_SHORT_RESIDUAL_HEADING_MIN_TOKENS = 1
_USCODE_SHORT_RESIDUAL_HEADING_MAX_TOKENS = 5
_USCODE_SHORT_RESIDUAL_HEADING_SIGNAL_TOKENS = frozenset(
    {
        "activities",
        "activity",
        "acts",
        "administrative",
        "administration",
        "aid",
        "aids",
        "amendment",
        "amendments",
        "appropriation",
        "appropriations",
        "access",
        "authorization",
        "authorizations",
        "compensation",
        "declaration",
        "database",
        "definition",
        "definitions",
        "element",
        "elements",
        "evaluation",
        "evaluations",
        "expense",
        "expenses",
        "finding",
        "findings",
        "assistance",
        "findings",
        "grant",
        "grants",
        "guidance",
        "hearing",
        "historical",
        "information",
        "notice",
        "notification",
        "notifications",
        "notes",
        "navigation",
        "operation",
        "operations",
        "policy",
        "penalty",
        "penalties",
        "prohibited",
        "program",
        "programs",
        "project",
        "projects",
        "requirement",
        "requirements",
        "provision",
        "provisions",
        "purpose",
        "procedure",
        "procedures",
        "reimbursement",
        "reimbursements",
        "replacement",
        "replacements",
        "restoration",
        "restorations",
        "regulation",
        "regulations",
        "report",
        "reporting",
        "reports",
        "records",
        "report",
        "reports",
        "review",
        "revision",
        "security",
        "use",
        "uses",
        "violation",
        "violations",
    }
)
_USCODE_LONG_RESIDUAL_HEADING_MIN_TOKENS = 6
_USCODE_LONG_RESIDUAL_HEADING_MAX_TOKENS = _USCODE_HEADING_ONLY_EXTENDED_MAX_TOKENS
_USCODE_LONG_RESIDUAL_HEADING_MIN_SIGNAL_TOKENS = 2
_USCODE_SECTION_CATCHLINE_MAX_TOKENS = 28
_USCODE_COMPACT_FRAME_RESIDUAL_MIN_TOKENS = 2
_USCODE_COMPACT_FRAME_RESIDUAL_MAX_TOKENS = 16
_USCODE_COMPACT_FRAME_RESIDUAL_SIGNAL_TOKENS = frozenset(
    {
        "administration",
        "administrative",
        "allowance",
        "allowances",
        "amount",
        "amounts",
        "application",
        "applications",
        "appropriation",
        "appropriations",
        "assistance",
        "authorization",
        "availability",
        "access",
        "benefit",
        "benefits",
        "compensation",
        "determination",
        "determinations",
        "element",
        "elements",
        "duties",
        "employee",
        "employees",
        "expense",
        "expenses",
        "guidance",
        "information",
        "jurisdiction",
        "land",
        "lands",
        "limitation",
        "limitations",
        "payment",
        "payments",
        "proceeding",
        "proceedings",
        "program",
        "programs",
        "recovered",
        "reimbursement",
        "reimbursements",
        "replacement",
        "replacements",
        "reservation",
        "reservations",
        "restoration",
        "restorations",
        "settlement",
        "settlements",
        "subchapter",
        "transfer",
        "transfers",
        "use",
        "uses",
        "withdrawal",
        "withdrawals",
    }
)
_USCODE_ENFORCEMENT_RESIDUAL_MAX_TOKENS = 48
_USCODE_ENFORCEMENT_RESIDUAL_SIGNAL_TOKENS = frozenset(
    {
        "civil",
        "criminal",
        "enforce",
        "enforceable",
        "enforcement",
        "fine",
        "fines",
        "forfeiture",
        "forfeitures",
        "offence",
        "offences",
        "offense",
        "offenses",
        "penalties",
        "penalty",
        "prohibited",
        "prohibition",
        "prohibitions",
        "punishable",
        "punishment",
        "sanction",
        "sanctions",
        "unlawful",
        "violation",
        "violations",
    }
)
_USCODE_ENFORCEMENT_RESIDUAL_CONTEXT_TOKENS = frozenset(
    {
        "act",
        "acts",
        "authority",
        "chapter",
        "code",
        "compliance",
        "control",
        "court",
        "law",
        "liability",
        "order",
        "orders",
        "person",
        "persons",
        "proceeding",
        "proceedings",
        "program",
        "programs",
        "regulation",
        "regulations",
        "rule",
        "rules",
        "section",
        "sections",
        "subchapter",
        "subsection",
        "title",
    }
)
_USCODE_MODAL_HEADING_PREFIX_MAX_TOKENS = 18
_USCODE_MAX_RESIDUAL_SPAN_FORMULAS = 3
_USCODE_RESIDUAL_SPAN_FORMULA_BUDGET_CAP = 16
_USCODE_RESIDUAL_COALESCE_SEGMENT_MAX_TOKENS = 12
_USCODE_RESIDUAL_HEADER_MIN_TOKENS = 10
_USCODE_RESIDUAL_SHORT_HEADER_MIN_TOKENS = 4
_USCODE_RESIDUAL_HEADER_SCOPE_PHRASES = (
    "from the u.s. government publishing office",
    "u.s.c.",
    "united states code",
    "www.gpo.gov",
)
_USCODE_SOURCE_PATH_HEADER_RE = re.compile(
    r"^\s*(?:(?:title|subtitle|chapter|subchapter|part)\s+"
    r"[0-9A-Za-zIVXLCDM.\-]+(?:\b|\s+-)"
    r"(?:\s+[A-Z][A-Z0-9'&,.\-]+)*)+\.?\s*$",
    re.IGNORECASE,
)
_USCODE_SECTION_CATCHLINE_STOP_RE = re.compile(
    r"\s+(?=(?:From\s+the\s+U\.?\s*S\.?\s+Government\s+Publishing\s+Office|"
    r"§+\s*\d|"
    r"\([a-z0-9ivxlcdm]{1,6}\)\s+|"
    r"The\s+(?:Secretary|Foundation|Commission|Administrator|Director|"
    r"consolidated\s+bank)\b|"
    r"Any\s+\w+\b|"
    r"Each\s+\w+\b|"
    r"Whoever\s+\w+\b|"
    r"This\s+section\b|"
    r"Nothing\s+in\s+this\b|"
    r"Notwithstanding\s+\w+\b|"
    r"In\s+the\s+(?:administration|case|event|operation|performance)\b|"
    r"As\s+soon\s+as\b|"
    r"Under\s+such\s+terms\b|"
    r"It\s+is\s+(?:critical|the\s+purpose|the\s+sense)\b|"
    r"There\s+(?:is|are)\s+established\b))",
    re.IGNORECASE,
)
_USCODE_DEFINITION_RESIDUAL_HINT_RE = re.compile(
    r"\b(?:the\s+term\s+[^.;:]{0,160}?\s+(?:means|has\s+the\s+meaning\s+given)|"
    r"terms?\s+[^.;:]{0,160}?\s+(?:mean|means|have\s+the\s+meaning\s+given)|"
    r"has\s+the\s+meaning\s+given\s+that\s+term|"
    r"means\s+[^.;:]{1,120})\b",
    re.IGNORECASE,
)
_USCODE_PURPOSE_RESIDUAL_HINT_RE = re.compile(
    r"\b(?:(?:general\s+)?purpose\s+of|for\s+the\s+purpose\s+of|"
    r"for\s+purposes\s+of|statement\s+of\s+purpose)\b",
    re.IGNORECASE,
)
_USCODE_PURPOSE_RESIDUAL_SIGNAL_TOKENS = frozenset(
    {
        "activities",
        "activity",
        "conduct",
        "coordination",
        "dissemination",
        "education",
        "health",
        "information",
        "institute",
        "institutes",
        "program",
        "programs",
        "purpose",
        "purposes",
        "research",
        "support",
        "training",
    }
)
_USCODE_SAVINGS_EFFECT_RESIDUAL_MAX_TOKENS = 96
_USCODE_SAVINGS_EFFECT_RESIDUAL_HINT_RE = re.compile(
    r"\b(?:"
    r"savings?\s+provisions?|"
    r"effect\s+on\s+(?:other\s+)?law|"
    r"effect\s+of\s+(?:act|chapter|part|section|subchapter|title)|"
    r"nothing\s+in\s+(?:this|the)\s+"
    r"(?:act|chapter|part|section|subchapter|title)\s+"
    r"(?:affects?|alters?|impairs?|limits?|modifies|supersedes)|"
    r"no\s+provision\s+of\s+(?:this|the)\s+"
    r"(?:act|chapter|part|section|subchapter|title)\s+"
    r"(?:affects?|alters?|impairs?|limits?|modifies|supersedes)"
    r")\b",
    re.IGNORECASE,
)
_USCODE_SAVINGS_EFFECT_RESIDUAL_SIGNAL_TOKENS = frozenset(
    {
        "act",
        "agency",
        "authority",
        "chapter",
        "department",
        "law",
        "laws",
        "part",
        "provision",
        "provisions",
        "savings",
        "section",
        "subchapter",
        "title",
    }
)
_USCODE_COST_ANALYSIS_RESIDUAL_RE = re.compile(
    r"\b(?:(?:annual\s+)?cost\s+analys(?:is|es)|analys(?:is|es)\s+of\s+costs?)\b",
    re.IGNORECASE,
)
_USCODE_TRANSFER_FUNCTIONS_RESIDUAL_MAX_TOKENS = 96
_USCODE_TRANSFER_FUNCTIONS_RESIDUAL_RE = re.compile(
    r"\btransfer\s+of\s+functions\b"
    r"(?=[^.;:]{0,360}\b(?:functions?|authority|duties|responsibilities)\b)"
    r"(?=[^.;:]{0,360}\btransferred\b)"
    r"(?=[^.;:]{0,360}\b(?:commission|secretary|department|administration|"
    r"agency|administrator)\b)",
    re.IGNORECASE,
)
_USCODE_RESIDUAL_STATUTORY_FRAGMENT_MAX_TOKENS = 18
_USCODE_RESIDUAL_STATUTORY_FRAGMENT_HINT_RE = re.compile(
    r"\b(?:ch|chapter|pub|stat)\b",
    re.IGNORECASE,
)
_GENERIC_LEGAL_REFERENCE_HINT_RE = re.compile(
    r"\b(?:section|sections|sec|secs|chapter|subchapter|title|subsection|"
    r"paragraph|stat|statutes?|public\s+law|pub\.?\s*l\.?)\b",
    re.IGNORECASE,
)
_USCODE_NOTE_REFERENCE_RESIDUAL_RE = re.compile(
    r"\bset\s+out\s+as\s+a\s+note\s+(?:under|preceding)\s+section\s+\d+\b",
    re.IGNORECASE,
)
_USCODE_REVISION_NOTE_RESIDUAL_RE = re.compile(
    r"\b(?:"
    r"references\s+in\s+text\s+note\s+below|"
    r"so\s+in\s+original|"
    r"words?\s+[^.;:]{0,180}?\s+(?:"
    r"are\s+)?(?:omitted|substituted|inserted|added|struck\s+out)|"
    r"(?:omitted|substituted|inserted|added|struck\s+out)\s+"
    r"(?:as\s+)?(?:unnecessary|for\s+consistency|to\s+eliminate)|"
    r"for\s+consistency\s+in\s+the\s+revised\s+title|"
    r"to\s+eliminate\s+unnecessary\s+words"
    r")\b",
    re.IGNORECASE,
)
_USCODE_EDITORIAL_NOTE_HEADING_RESIDUAL_MAX_TOKENS = 16
_USCODE_EDITORIAL_NOTE_HEADING_RESIDUAL_RE = re.compile(
    r"^\s*(?:editorial\s+notes|historical\s+and\s+revision\s+notes)\b"
    r"(?=.*\b(?:amendments?|codification|effective\s+date|prior\s+provisions?|"
    r"statutory\s+notes?|related\s+subsidiaries)\b)",
    re.IGNORECASE,
)
_USCODE_LEGISLATIVE_HISTORY_RESIDUAL_RE = re.compile(
    r"(?:\b(?:pub\.?\s*l\.?|ch\.|stat\.|act\s+[a-z]+\.?)\b|§\d)"
    r"(?=[^.;:]{0,260}\b(?:"
    r"amended|added|formerly|renumbered|substituted|title|"
    r"stat\.|pub\.?\s*l\.?|ch\.|act\s+[a-z]+\.?"
    r")\b)",
    re.IGNORECASE,
)
_USCODE_LEGISLATIVE_HISTORY_CONTINUATION_RE = re.compile(
    r"^\s*\d+[A-Za-z]?\s*,\s*(?:required|authorized|provided|related)\b",
    re.IGNORECASE,
)
_USCODE_EDITORIAL_NOTE_HEADING_RESIDUAL_MAX_TOKENS = 16
_USCODE_EDITORIAL_NOTE_HEADING_RESIDUAL_RE = re.compile(
    r"^\s*(?:editorial\s+notes?|historical\s+and\s+revision\s+notes?)\s+"
    r"(?:(?:and\s+)?(?:prior\s+provisions?|amendments?|codification|effective\s+date|"
    r"statutory\s+notes?|related\s+subsidiaries)\.?(?:\s+|$)){1,6}\s*$",
    re.IGNORECASE,
)
_MONTH_NAME_TOKENS = frozenset(
    {
        "jan",
        "january",
        "feb",
        "february",
        "mar",
        "march",
        "apr",
        "april",
        "may",
        "jun",
        "june",
        "jul",
        "july",
        "aug",
        "august",
        "sep",
        "sept",
        "september",
        "oct",
        "october",
        "nov",
        "november",
        "dec",
        "december",
    }
)
_MONTH_DAY_RE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)(?:\.)?\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4}|\s+\d{4})?\b",
    re.IGNORECASE,
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
_TEMPORAL_WITHIN_PHRASE_RE = re.compile(
    r"^\s+(?:"
    r"\d{1,4}\b|"
    r"(?:a|an)\s+(?:day|days|month|months|year|years|week|weeks|hour|hours)\b|"
    r"(?:the\s+)?(?:end|close|beginning|start|deadline|expiration)\b|"
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
        "administrator",
        "agency",
        "applicant",
        "article",
        "chapter",
        "clause",
        "code",
        "commissioner",
        "defendant",
        "department",
        "director",
        "division",
        "governor",
        "law",
        "paragraph",
        "part",
        "person",
        "president",
        "public",
        "pub",
        "rule",
        "rules",
        "secretary",
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
    r"act|administrator|agency|article|chapter|clause|code|commissioner|department|"
    r"director|division|governor|law|paragraph|part|president|public\s+law|pub(?:lic)?\.?\s*l\.?|"
    r"rule|rules|secretary|section|sections|statute|subchapter|subparagraph|subpart|"
    r"subsection|subtitle|title"
    r")\b",
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
    r"jurisdiction|limits|meaning|office|paragraph|possession|scope|"
    r"state|states|subchapter|subparagraph|subsection|supervision|territory|"
    r"title|united\s+states"
    r")\b",
    re.IGNORECASE,
)
_TEMPORAL_DURATION_TOKENS = frozenset(
    {
        "day",
        "days",
        "deadline",
        "deadlines",
        "expiration",
        "hour",
        "hours",
        "month",
        "months",
        "period",
        "periods",
        "quarter",
        "quarters",
        "term",
        "terms",
        "time",
        "times",
        "week",
        "weeks",
        "year",
        "years",
    }
)


@dataclass(frozen=True)
class LegalSegment:
    """Normalized legal text segment with source offsets."""

    text: str
    start_char: int
    end_char: int
    role: str = "clause"


@dataclass(frozen=True)
class ModalCueSpan:
    """A registry cue found in text."""

    family: ModalLogicFamily
    profile: ModalParseProfile
    operator: ModalOperatorSpec
    cue: str
    start_char: int
    end_char: int


class LegalModalParser:
    """Small deterministic parser that compiles legal text into modal IR."""

    def __init__(self, registry: ModalRegistry = DEFAULT_MODAL_REGISTRY) -> None:
        self.registry = registry

    def normalize_text(self, text: str) -> str:
        """Normalize whitespace while preserving legal punctuation."""
        return _WHITESPACE_RE.sub(" ", text).strip()

    def segment(self, text: str) -> List[LegalSegment]:
        """Split normalized legal text into deterministic legal segments."""
        normalized = self.normalize_text(text)
        segments: List[LegalSegment] = []
        for match in _SEGMENT_RE.finditer(normalized):
            segment_text = match.group(0).strip()
            if not segment_text:
                continue
            segments.append(
                LegalSegment(
                    text=segment_text,
                    start_char=match.start(),
                    end_char=match.end(),
                    role=self._classify_segment_role(segment_text),
                )
            )
        return self._coalesce_uscode_section_prefix_segments(
            segments,
            normalized_text=normalized,
        )

    def _coalesce_uscode_section_prefix_segments(
        self,
        segments: Sequence[LegalSegment],
        *,
        normalized_text: str,
    ) -> List[LegalSegment]:
        """Join split ``Sec.`` prefixes with the following section-heading span."""
        if len(segments) < 2:
            return list(segments)
        coalesced: List[LegalSegment] = []
        index = 0
        while index < len(segments):
            segment = segments[index]
            if index + 1 >= len(segments):
                coalesced.append(segment)
                index += 1
                continue
            next_segment = segments[index + 1]
            if (
                _USCODE_SECTION_PREFIX_SEGMENT_RE.fullmatch(segment.text)
                and next_segment.start_char <= segment.end_char + 1
                and _USCODE_SECTION_ID_SEGMENT_RE.match(next_segment.text)
            ):
                merged_text = normalized_text[segment.start_char : next_segment.end_char]
                coalesced.append(
                    LegalSegment(
                        text=merged_text,
                        start_char=segment.start_char,
                        end_char=next_segment.end_char,
                        role=self._classify_segment_role(merged_text),
                    )
                )
                index += 2
                continue
            coalesced.append(segment)
            index += 1
        return coalesced

    def extract_cues(self, text: str) -> List[ModalCueSpan]:
        """Extract modal cue spans from text using registry cue terms."""
        normalized = self.normalize_text(text)
        found: List[ModalCueSpan] = []
        for profile in self.registry.all_profiles():
            for operator in profile.operators:
                for cue in operator.cue_terms:
                    pattern = re.compile(rf"(?<!\w){re.escape(cue)}(?!\w)", re.IGNORECASE)
                    for match in pattern.finditer(normalized):
                        if self._is_calendar_month_may_cue(
                            normalized_text=normalized,
                            cue=cue,
                            start_char=match.start(),
                            end_char=match.end(),
                        ):
                            continue
                        lowered_cue = cue.lower()
                        first_cue_token = lowered_cue.split(maxsplit=1)[0]
                        if (
                            profile.family == ModalLogicFamily.DEONTIC
                            and first_cue_token in _USCODE_EDITORIAL_REQUIRED_CUES
                            and self._is_non_deontic_editorial_required_cue(
                                normalized_text=normalized,
                                start_char=match.start(),
                                end_char=match.end(),
                            )
                        ):
                            continue
                        if (
                            profile.family in _USCODE_EDITORIAL_HISTORY_CUE_FAMILIES
                            and self._is_nonoperative_uscode_history_cue(
                                normalized_text=normalized,
                                family=profile.family,
                                cue=cue,
                                start_char=match.start(),
                                end_char=match.end(),
                            )
                        ):
                            continue
                        if (
                            profile.family == ModalLogicFamily.DEONTIC
                            and self._is_non_deontic_editorial_permission_cue(
                                normalized_text=normalized,
                                cue=cue,
                                start_char=match.start(),
                                end_char=match.end(),
                            )
                        ):
                            continue
                        if (
                            profile.family == ModalLogicFamily.CONDITIONAL_NORMATIVE
                            and self._is_non_conditional_purpose_object_cue(
                                normalized_text=normalized,
                                cue=cue,
                                start_char=match.start(),
                                end_char=match.end(),
                            )
                        ):
                            continue
                        found.append(
                            ModalCueSpan(
                                family=profile.family,
                                profile=profile,
                                operator=operator,
                                cue=cue,
                                start_char=match.start(),
                                end_char=match.end(),
                            )
                        )
        return self._prune_contained_cues(found)

    def _prune_contained_cues(
        self,
        cues: Sequence[ModalCueSpan],
    ) -> List[ModalCueSpan]:
        """Prefer prohibition over bare permission for `may not` cue collisions."""
        accepted: List[ModalCueSpan] = []
        for cue in sorted(
            cues,
            key=lambda item: (
                item.start_char,
                -(item.end_char - item.start_char),
                item.end_char,
                item.family.value,
                item.operator.symbol,
                item.cue.lower(),
            ),
        ):
            if any(
                existing.start_char <= cue.start_char
                and cue.end_char <= existing.end_char
                and cue.cue.lower() == "may"
                and existing.cue.lower() == "may not"
                and (
                    existing.start_char,
                    existing.end_char,
                )
                != (
                    cue.start_char,
                    cue.end_char,
                )
                for existing in accepted
            ):
                continue
            accepted.append(cue)
        return sorted(
            accepted,
            key=lambda cue: (
                cue.start_char,
                cue.end_char,
                cue.family.value,
                cue.operator.symbol,
            ),
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

    def _is_non_deontic_editorial_permission_cue(
        self,
        *,
        normalized_text: str,
        cue: str,
        start_char: int,
        end_char: int,
    ) -> bool:
        """Ignore historical-note permission words that describe repealed sections."""
        if cue.lower() not in _USCODE_EDITORIAL_PERMISSION_CUES:
            return False
        trailing = normalized_text[end_char : end_char + 32]
        if re.match(r"^\s+to\s+be\s+appropriated\b", trailing, re.IGNORECASE):
            return False
        context_window = normalized_text[
            max(0, start_char - 160) : min(len(normalized_text), end_char + 96)
        ]
        leading = normalized_text[max(0, start_char - 240) : start_char].lower()
        has_section_history_prefix = bool(
            re.search(r"\bsection\s+[0-9a-z.\-\u2010-\u2015]+\b", leading)
            and _USCODE_LEGISLATIVE_HISTORY_ABBREVIATION_RE.search(leading)
        )
        if (
            not _USCODE_EDITORIAL_NOTE_CONTEXT_RE.search(context_window)
            and not has_section_history_prefix
        ):
            return False
        if has_section_history_prefix:
            return True
        return bool(_USCODE_LEGISLATIVE_HISTORY_ABBREVIATION_RE.search(context_window))

    def _is_non_deontic_editorial_required_cue(
        self,
        *,
        normalized_text: str,
        start_char: int,
        end_char: int,
    ) -> bool:
        """Ignore bare `required` when it describes repealed editorial history."""
        trailing = normalized_text[end_char : end_char + 24]
        if re.match(r"^\s+to\b", trailing, re.IGNORECASE):
            return False
        context_window = normalized_text[
            max(0, start_char - 160) : min(len(normalized_text), end_char + 96)
        ]
        if not _USCODE_EDITORIAL_NOTE_CONTEXT_RE.search(context_window):
            return False
        leading = normalized_text[max(0, start_char - 240) : start_char]
        return bool(
            _USCODE_REPEALED_HISTORY_PREFIX_RE.search(leading)
            or (
                re.search(r"\bsection\s*,?\b", leading, re.IGNORECASE)
                and _USCODE_LEGISLATIVE_HISTORY_ABBREVIATION_RE.search(leading)
            )
        )

    def _is_nonoperative_uscode_history_cue(
        self,
        *,
        normalized_text: str,
        family: ModalLogicFamily,
        cue: str,
        start_char: int,
        end_char: int,
    ) -> bool:
        """Return true for cues inside repealed-section legislative history tails."""
        if family not in _USCODE_EDITORIAL_HISTORY_CUE_FAMILIES:
            return False
        lowered_cue = cue.lower()
        first_cue_token = lowered_cue.split(maxsplit=1)[0]
        if (
            family == ModalLogicFamily.DEONTIC
            and first_cue_token not in _USCODE_EDITORIAL_DEONTIC_HISTORY_CUE_PREFIXES
        ):
            return False
        context_window = normalized_text[
            max(0, start_char - 240) : min(len(normalized_text), end_char + 120)
        ]
        leading = normalized_text[max(0, start_char - 320) : start_char]
        if not (
            _USCODE_EDITORIAL_STATUS_HINT_RE.search(context_window)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(leading)
        ):
            return False
        if not (
            _USCODE_REPEALED_HISTORY_PREFIX_RE.search(leading)
            or (
                re.search(r"\bsection\s*,?\b", leading, re.IGNORECASE)
                and _USCODE_LEGISLATIVE_HISTORY_ABBREVIATION_RE.search(leading)
            )
        ):
            return False
        if family == ModalLogicFamily.TEMPORAL:
            return lowered_cue in {"before", "by", "on", "prior to", "after"}
        if family == ModalLogicFamily.CONDITIONAL_NORMATIVE:
            return lowered_cue in {"with respect to", "pursuant to", "subject to"}
        return True

    def _is_non_conditional_purpose_object_cue(
        self,
        *,
        normalized_text: str,
        cue: str,
        start_char: int,
        end_char: int,
    ) -> bool:
        """Do not treat research-purpose object phrases as legal conditions."""
        if cue.lower() != "with respect to":
            return False
        leading = normalized_text[max(0, start_char - 220) : start_char].lower()
        trailing = normalized_text[
            end_char : min(len(normalized_text), end_char + 96)
        ].lower()
        if not _USCODE_PURPOSE_RESIDUAL_HINT_RE.search(leading):
            return False
        if not (
            re.search(
                r"\b(?:conduct|support|research|training|dissemination|programs?)\b",
                leading,
            )
            or re.search(r"\b(?:research|training|health|environment)\b", trailing)
        ):
            return False
        return True

    def _should_ignore_non_temporal_temporal_cue(
        self,
        *,
        normalized_text: str,
        cue: str,
        start_char: int,
        end_char: int,
    ) -> bool:
        lowered = cue.lower()
        if lowered == "by":
            return not self._is_temporal_deadline_by_cue(
                normalized_text=normalized_text,
                start_char=start_char,
                end_char=end_char,
            )
        if lowered == "within":
            return not self._is_temporal_duration_within_cue(
                normalized_text=normalized_text,
                start_char=start_char,
                end_char=end_char,
            )
        return False

    def _is_temporal_deadline_by_cue(
        self,
        *,
        normalized_text: str,
        start_char: int,
        end_char: int,
    ) -> bool:
        """Treat temporal `by` as a deadline cue only in time-like contexts."""
        trailing = normalized_text[end_char : end_char + 80]
        if re.match(r"^\s+(?:\$+\s*\d|\$?\d[\d,]*\.\d+\b)", trailing):
            return False
        if (
            re.match(r"^\s+(?:pub\.?\s*l\.?|public\s+law)\b", trailing, re.IGNORECASE)
            and _MONTH_DAY_RE.search(trailing)
        ):
            leading = normalized_text[max(0, start_char - 120) : start_char]
            if re.search(
                r"\b(?:amendment|amendments|effective\s+date)\b",
                leading,
                re.IGNORECASE,
            ):
                return False
            return True
        if _NON_TEMPORAL_BY_PHRASE_RE.match(trailing):
            return False
        if _TEMPORAL_BY_PHRASE_RE.match(trailing):
            return True
        if _MONTH_DAY_RE.match(trailing):
            return True
        lookahead = self._lookahead_tokens(trailing, limit=4)
        if not lookahead:
            return False
        first = lookahead[0]
        second = lookahead[1] if len(lookahead) > 1 else ""
        if first in _NON_TEMPORAL_BY_CONTEXT_TOKENS:
            return False
        if (
            first in _NON_TEMPORAL_BY_PREFIX_TOKENS
            and second in _NON_TEMPORAL_BY_CONTEXT_TOKENS
        ):
            return False
        for index, token in enumerate(lookahead):
            if token in _NON_TEMPORAL_BY_CONTEXT_TOKENS:
                return False
            if token in _TEMPORAL_DURATION_TOKENS:
                return True
            if token in _MONTH_NAME_TOKENS:
                return True
            if token.isdigit():
                previous = lookahead[index - 1] if index > 0 else ""
                if previous in _NON_TEMPORAL_BY_CONTEXT_TOKENS:
                    continue
                return True
        return False

    def _is_temporal_duration_within_cue(
        self,
        *,
        normalized_text: str,
        start_char: int,
        end_char: int,
    ) -> bool:
        """Treat temporal `within` as duration/deadline only in time-like contexts."""
        trailing = normalized_text[end_char : end_char + 80]
        if _NON_TEMPORAL_WITHIN_PHRASE_RE.match(trailing):
            return False
        if _TEMPORAL_WITHIN_PHRASE_RE.match(trailing):
            return True
        if _MONTH_DAY_RE.match(trailing):
            return True
        lookahead = self._lookahead_tokens(trailing, limit=4)
        if not lookahead:
            return False
        first = lookahead[0]
        second = lookahead[1] if len(lookahead) > 1 else ""
        if first in _NON_TEMPORAL_WITHIN_CONTEXT_TOKENS:
            return False
        if (
            first in _NON_TEMPORAL_WITHIN_PREFIX_TOKENS
            and second in _NON_TEMPORAL_WITHIN_CONTEXT_TOKENS
        ):
            return False
        for token in lookahead:
            if token in _NON_TEMPORAL_WITHIN_CONTEXT_TOKENS:
                return False
            if token in _TEMPORAL_DURATION_TOKENS:
                return True
            if token in _MONTH_NAME_TOKENS:
                return True
            if token.isdigit():
                return True
        return False

    def _lookahead_tokens(
        self,
        text: str,
        *,
        limit: int,
    ) -> List[str]:
        tokens = [token.lower() for token in _TOKEN_RE.findall(text)]
        if limit < 1:
            return []
        return tokens[:limit]

    def _has_blocking_residual_modal_cues(
        self,
        normalized_text: str,
    ) -> bool:
        for cue in self.extract_cues(normalized_text):
            if (
                cue.family == ModalLogicFamily.TEMPORAL
                and self._should_ignore_non_temporal_temporal_cue(
                    normalized_text=normalized_text,
                    cue=cue.cue,
                    start_char=cue.start_char,
                    end_char=cue.end_char,
                )
            ):
                continue
            return True
        return False

    def parse(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        source: str = "legal_text",
        citation: Optional[str] = None,
    ) -> ModalIRDocument:
        """Parse legal text into canonical modal IR."""
        normalized = self.normalize_text(text)
        resolved_document_id = document_id or self._document_id(normalized)
        segments = self.segment(normalized)
        cues = self._parse_eligible_cues(normalized, citation=citation)
        formulas: List[ModalIRFormula] = []

        for index, cue in enumerate(cues, start=1):
            segment = self._segment_for_cue(segments, cue)
            predicate = self._predicate_from_segment(segment.text, cue.cue)
            conditions, exceptions = self._conditions_and_exceptions_from_segment(
                segment.text
            )
            formulas.append(
                ModalIRFormula(
                    formula_id=f"{resolved_document_id}:f{index:04d}",
                    operator=ModalIROperator(
                        family=cue.family.value,
                        system=cue.profile.system.value,
                        symbol=cue.operator.symbol,
                        label=cue.operator.aliases[0] if cue.operator.aliases else cue.operator.symbol,
                    ),
                    predicate=ModalIRPredicate(
                        name=predicate,
                        arguments=[],
                        role=segment.role,
                    ),
                    provenance=ModalIRProvenance(
                        source_id=resolved_document_id,
                        start_char=segment.start_char,
                        end_char=segment.end_char,
                        citation=citation,
                    ),
                    conditions=conditions,
                    exceptions=exceptions,
                    metadata={
                        "cue": cue.cue,
                        "cue_start_char": cue.start_char,
                        "cue_end_char": cue.end_char,
                    },
                )
            )

        def _prefix_formulas(start_index: int) -> List[ModalIRFormula]:
            return self.modal_heading_prefix_coverage_formulas(
                document_id=resolved_document_id,
                text=normalized,
                citation=citation,
                start_index=start_index,
                segments=segments,
                cues=cues,
            )

        def _catchline_formulas(start_index: int) -> List[ModalIRFormula]:
            return self.uscode_section_catchline_coverage_formulas(
                document_id=resolved_document_id,
                text=normalized,
                citation=citation,
                start_index=start_index,
                covered_spans=[
                    (
                        int(formula.provenance.start_char),
                        int(formula.provenance.end_char),
                    )
                    for formula in formulas
                ],
            )

        def _marker_formulas(start_index: int) -> List[ModalIRFormula]:
            return self.uscode_section_marker_coverage_formulas(
                document_id=resolved_document_id,
                text=normalized,
                citation=citation,
                start_index=start_index,
                covered_spans=[
                    (
                        int(formula.provenance.start_char),
                        int(formula.provenance.end_char),
                    )
                    for formula in formulas
                ],
            )

        def _subsection_heading_formulas(start_index: int) -> List[ModalIRFormula]:
            return self.uscode_subsection_heading_coverage_formulas(
                document_id=resolved_document_id,
                text=normalized,
                citation=citation,
                start_index=start_index,
                covered_spans=[
                    (
                        int(formula.provenance.start_char),
                        int(formula.provenance.end_char),
                    )
                    for formula in formulas
                ],
            )

        fallback_formula = self.fallback_formula(
            document_id=resolved_document_id,
            text=normalized,
            citation=citation,
            start_index=len(formulas) + 1,
            segments=segments,
        )
        if fallback_formula is not None:
            residual_segments = self._segments_excluding_spans(
                segments,
                spans=[
                    (
                        int(fallback_formula.provenance.start_char),
                        int(fallback_formula.provenance.end_char),
                    )
                ],
            )
            residual_formulas = self.residual_span_coverage_formulas(
                document_id=resolved_document_id,
                text=normalized,
                citation=citation,
                start_index=len(formulas) + 1,
                segments=residual_segments,
            )
            formulas.extend(residual_formulas)
            if residual_formulas:
                reindexed_fallback = self.fallback_formula(
                    document_id=resolved_document_id,
                    text=normalized,
                    citation=citation,
                    start_index=len(formulas) + 1,
                    segments=segments,
                )
                if reindexed_fallback is not None:
                    fallback_formula = reindexed_fallback
            formulas.extend(_prefix_formulas(len(formulas) + 2))
            formulas.extend(_subsection_heading_formulas(len(formulas) + 2))
            formulas.extend(_marker_formulas(len(formulas) + 2))
            formulas.extend(_catchline_formulas(len(formulas) + 2))
            formulas.append(fallback_formula)
        elif formulas:
            residual_segments = self._segments_excluding_spans(
                segments,
                spans=[
                    (
                        int(formula.provenance.start_char),
                        int(formula.provenance.end_char),
                    )
                    for formula in formulas
                ],
            )
            residual_fallback_formula = self.fallback_formula(
                document_id=resolved_document_id,
                text=normalized,
                citation=citation,
                start_index=len(formulas) + 1,
                segments=residual_segments,
                allow_modal_cues=True,
            )
            if residual_fallback_formula is not None:
                residual_segments_after_fallback = self._segments_excluding_spans(
                    residual_segments,
                    spans=[
                        (
                            int(residual_fallback_formula.provenance.start_char),
                            int(residual_fallback_formula.provenance.end_char),
                        )
                    ],
                )
                formulas.extend(
                    self.residual_span_coverage_formulas(
                        document_id=resolved_document_id,
                        text=normalized,
                        citation=citation,
                        start_index=len(formulas) + 2,
                        segments=residual_segments_after_fallback,
                    )
                )
                formulas.extend(_prefix_formulas(len(formulas) + 2))
                formulas.extend(_subsection_heading_formulas(len(formulas) + 2))
                formulas.extend(_marker_formulas(len(formulas) + 2))
                formulas.extend(_catchline_formulas(len(formulas) + 2))
                formulas.append(residual_fallback_formula)
            else:
                formulas.extend(
                    self.residual_span_coverage_formulas(
                        document_id=resolved_document_id,
                        text=normalized,
                        citation=citation,
                        start_index=len(formulas) + 1,
                        segments=residual_segments,
                    )
                )
                formulas.extend(_prefix_formulas(len(formulas) + 1))
                formulas.extend(_subsection_heading_formulas(len(formulas) + 1))
                formulas.extend(_marker_formulas(len(formulas) + 1))
                formulas.extend(_catchline_formulas(len(formulas) + 1))

        return ModalIRDocument(
            document_id=resolved_document_id,
            source=source,
            normalized_text=normalized,
            formulas=formulas,
            metadata={
                "citation": citation,
                "deterministic_parser": "legal_modal_parser_v1",
                "segment_count": len(segments),
            },
        )

    def _parse_eligible_cues(
        self,
        normalized_text: str,
        *,
        citation: Optional[str] = None,
    ) -> List[ModalCueSpan]:
        """Return cue spans that are semantically eligible for formula emission."""
        cues: List[ModalCueSpan] = []
        for cue in self.extract_cues(normalized_text):
            if (
                cue.family == ModalLogicFamily.TEMPORAL
                and self._is_non_temporal_editorial_status_heading_cue(
                    normalized_text=normalized_text,
                    start_char=cue.start_char,
                    end_char=cue.end_char,
                    citation=citation,
                )
            ):
                continue
            if (
                cue.family == ModalLogicFamily.TEMPORAL
                and self._is_non_temporal_editorial_note_heading_cue(
                    normalized_text=normalized_text,
                    start_char=cue.start_char,
                    end_char=cue.end_char,
                )
            ):
                continue
            if (
                cue.family == ModalLogicFamily.TEMPORAL
                and self._should_ignore_non_temporal_temporal_cue(
                    normalized_text=normalized_text,
                    cue=cue.cue,
                    start_char=cue.start_char,
                    end_char=cue.end_char,
                )
            ):
                continue
            cues.append(cue)
        return cues

    def _is_non_temporal_editorial_note_heading_cue(
        self,
        *,
        normalized_text: str,
        start_char: int,
        end_char: int,
    ) -> bool:
        """Do not type editorial-note catchlines such as `Prior Provisions` as time."""
        segment = next(
            (
                candidate
                for candidate in self.segment(normalized_text)
                if candidate.start_char <= start_char and end_char <= candidate.end_char
            ),
            LegalSegment(
                text=normalized_text[start_char:end_char],
                start_char=start_char,
                end_char=end_char,
            ),
        )
        tokens = _TOKEN_RE.findall(segment.text.lower())
        return self._is_uscode_editorial_note_heading_residual_candidate(
            segment.text,
            tokens,
        )

    def _is_non_temporal_editorial_status_heading_cue(
        self,
        *,
        normalized_text: str,
        start_char: int,
        end_char: int,
        citation: Optional[str] = None,
    ) -> bool:
        """Treat U.S.C. status headings such as `Repealed.` as frame status, not time."""
        cue_text = normalized_text[start_char:end_char]
        if not _USCODE_EDITORIAL_STATUS_HINT_RE.fullmatch(cue_text.strip()):
            return False

        segments = self.segment(normalized_text)
        for index, segment in enumerate(segments):
            if not (segment.start_char <= start_char and end_char <= segment.end_char):
                continue
            previous_text = segments[index - 1].text if index > 0 else ""
            citation_section = self._citation_section_token(citation)
            if citation_section and self._looks_like_editorial_status_heading(
                segment.text,
                citation_section=citation_section,
                previous_segment_text=previous_text,
            ):
                return True

            normalized_segment = self.normalize_text(segment.text).lower()
            normalized_previous = self.normalize_text(previous_text).lower()
            if not normalized_segment.startswith(
                ("repealed", "omitted", "reserved", "renumbered", "terminated", "vacant")
            ):
                return False
            if normalized_previous.startswith(("§", "§§")):
                return True
            if re.match(rf"^{_USCODE_SECTION_REF_PREFIX_RE}", normalized_previous, re.IGNORECASE):
                return True
            return False
        return False

    def fallback_formula(
        self,
        *,
        document_id: str,
        text: str,
        citation: Optional[str],
        start_index: int = 1,
        segments: Optional[Sequence[LegalSegment]] = None,
        allow_modal_cues: bool = False,
    ) -> Optional[ModalIRFormula]:
        """Return a deterministic fallback formula for known U.S. Code heading forms."""
        normalized = self.normalize_text(text)
        candidate_segments: Sequence[LegalSegment]
        if segments is None:
            candidate_segments = self.segment(normalized)
        else:
            candidate_segments = segments
        fallback_formula = self._uscode_codification_fallback_formula(
            resolved_document_id=document_id,
            normalized_text=normalized,
            citation=citation,
            segments=candidate_segments,
            start_index=start_index,
            allow_modal_cues=allow_modal_cues,
        )
        if fallback_formula is not None:
            return fallback_formula
        fallback_formula = self._uscode_editorial_status_fallback_formula(
            resolved_document_id=document_id,
            normalized_text=normalized,
            citation=citation,
            segments=candidate_segments,
            start_index=start_index,
            allow_modal_cues=allow_modal_cues,
        )
        if fallback_formula is not None:
            return fallback_formula
        fallback_formula = self._uscode_declarative_statement_fallback_formula(
            resolved_document_id=document_id,
            normalized_text=normalized,
            citation=citation,
            segments=candidate_segments,
            start_index=start_index,
            allow_modal_cues=allow_modal_cues,
        )
        if fallback_formula is not None:
            return fallback_formula
        fallback_formula = self._uscode_procedural_clause_fallback_formula(
            resolved_document_id=document_id,
            normalized_text=normalized,
            citation=citation,
            segments=candidate_segments,
            start_index=start_index,
            allow_modal_cues=allow_modal_cues,
        )
        if fallback_formula is not None:
            return fallback_formula
        return self._uscode_section_heading_fallback_formula(
            resolved_document_id=document_id,
            normalized_text=normalized,
            citation=citation,
            segments=candidate_segments,
            start_index=start_index,
            allow_modal_cues=allow_modal_cues,
        )

    def residual_span_coverage_formulas(
        self,
        *,
        document_id: str,
        text: str,
        citation: Optional[str],
        start_index: int = 1,
        segments: Optional[Sequence[LegalSegment]] = None,
        max_formulas: int = _USCODE_MAX_RESIDUAL_SPAN_FORMULAS,
    ) -> List[ModalIRFormula]:
        """Emit bounded frame formulas for uncovered U.S.C. residual spans."""
        normalized = self.normalize_text(text)
        if not normalized.strip():
            return []
        requested_max_formulas = int(max_formulas)
        if requested_max_formulas <= 0:
            return []
        use_uscode_rule = self._is_uscode_citation(citation)
        profile = self.registry.get_profile(ModalLogicFamily.FRAME)
        if not profile.operators:
            return []
        operator = profile.operators[0]
        candidate_segments = (
            list(self.segment(normalized)) if segments is None else list(segments)
        )
        candidate_segments = self._coalesce_short_residual_segments(
            candidate_segments,
            normalized_text=normalized,
        )
        if not candidate_segments:
            return []
        if use_uscode_rule:
            eligible_segments = [
                segment
                for segment in candidate_segments
                if self._is_residual_span_coverage_candidate(segment)
            ]
        else:
            eligible_segments = [
                segment
                for segment in candidate_segments
                if self._is_generic_legal_reference_residual_candidate(segment)
            ]
        if not eligible_segments:
            return []

        # Keep the explicit caller cap when provided, but allow the default U.S.C.
        # residual rule to widen coverage on long editorial/reference tails.
        resolved_max_formulas = max(1, requested_max_formulas)
        if use_uscode_rule and requested_max_formulas == _USCODE_MAX_RESIDUAL_SPAN_FORMULAS:
            resolved_max_formulas = max(
                resolved_max_formulas,
                min(
                    _USCODE_RESIDUAL_SPAN_FORMULA_BUDGET_CAP,
                    len(eligible_segments),
                ),
            )
        if not use_uscode_rule:
            # Keep non-U.S.C. fallback conservative to avoid over-typing broad prose.
            resolved_max_formulas = 1

        formulas: List[ModalIRFormula] = []
        next_index = max(1, int(start_index))
        for segment in eligible_segments[:resolved_max_formulas]:
            coverage_segment = (
                None
                if self._preserve_full_residual_segment(segment)
                else (
                    self._uscode_source_path_header_prefix_segment(segment)
                    or self._residual_paragraph_heading_prefix_segment(segment)
                )
            ) or segment
            formulas.append(
                self._residual_span_coverage_formula(
                    document_id=document_id,
                    citation=citation,
                    segment=coverage_segment,
                    start_index=next_index,
                    operator=operator,
                    profile=profile,
                )
            )
            next_index += 1
        return formulas

    def _preserve_full_residual_segment(self, segment: LegalSegment) -> bool:
        """Keep typed residual definitions intact instead of shrinking to headings."""
        normalized = self.normalize_text(segment.text)
        if not normalized:
            return False
        tokens = _TOKEN_RE.findall(normalized.lower())
        return self._is_uscode_definition_residual_candidate(normalized, tokens)

    def uscode_section_catchline_coverage_formulas(
        self,
        *,
        document_id: str,
        text: str,
        citation: Optional[str],
        start_index: int = 1,
        covered_spans: Sequence[tuple[int, int]] = (),
        max_formulas: int = 2,
    ) -> List[ModalIRFormula]:
        """Emit frame coverage for the coalesced U.S.C. section catchline."""
        if max_formulas <= 0 or not self._is_uscode_citation(citation):
            return []
        normalized = self.normalize_text(text)
        if not normalized.strip():
            return []
        citation_section = self._citation_section_token(citation)
        if not citation_section:
            return []
        profile = self.registry.get_profile(ModalLogicFamily.FRAME)
        if not profile.operators:
            return []
        operator = profile.operators[0]
        formulas: List[ModalIRFormula] = []
        next_index = max(1, int(start_index))
        for segment in self._uscode_section_catchline_segments(
            normalized_text=normalized,
            citation_section=citation_section,
        ):
            if self._is_exactly_covered_span(segment, covered_spans):
                continue
            formulas.append(
                self._residual_span_coverage_formula(
                    document_id=document_id,
                    citation=citation,
                    segment=segment,
                    start_index=next_index,
                    operator=operator,
                    profile=profile,
                    fallback_rule="uscode_section_catchline_coverage_v1",
                )
            )
            next_index += 1
            if len(formulas) >= max_formulas:
                break
        return formulas

    def uscode_section_marker_coverage_formulas(
        self,
        *,
        document_id: str,
        text: str,
        citation: Optional[str],
        start_index: int = 1,
        covered_spans: Sequence[tuple[int, int]] = (),
        max_formulas: int = 4,
    ) -> List[ModalIRFormula]:
        """Emit frame coverage for bare U.S.C. section markers left between spans."""
        if max_formulas <= 0 or not self._is_uscode_citation(citation):
            return []
        normalized = self.normalize_text(text)
        if not normalized.strip():
            return []
        citation_section = self._citation_section_token(citation)
        if not citation_section:
            return []
        profile = self.registry.get_profile(ModalLogicFamily.FRAME)
        if not profile.operators:
            return []
        operator = profile.operators[0]
        formulas: List[ModalIRFormula] = []
        next_index = max(1, int(start_index))
        for segment in self._uscode_section_marker_segments(
            normalized_text=normalized,
            citation_section=citation_section,
        ):
            if self._is_overlapping_covered_span(segment, covered_spans):
                continue
            formulas.append(
                self._residual_span_coverage_formula(
                    document_id=document_id,
                    citation=citation,
                    segment=segment,
                    start_index=next_index,
                    operator=operator,
                    profile=profile,
                    fallback_rule="uscode_section_marker_coverage_v1",
                )
            )
            next_index += 1
            if len(formulas) >= max_formulas:
                break
        return formulas

    def uscode_subsection_heading_coverage_formulas(
        self,
        *,
        document_id: str,
        text: str,
        citation: Optional[str],
        start_index: int = 1,
        covered_spans: Sequence[tuple[int, int]] = (),
        max_formulas: int = 4,
    ) -> List[ModalIRFormula]:
        """Emit frame coverage for short ``(a) Heading .-`` subsection labels."""
        if max_formulas <= 0 or not self._is_uscode_citation(citation):
            return []
        normalized = self.normalize_text(text)
        if not normalized.strip():
            return []
        profile = self.registry.get_profile(ModalLogicFamily.FRAME)
        if not profile.operators:
            return []
        operator = profile.operators[0]
        formulas: List[ModalIRFormula] = []
        next_index = max(1, int(start_index))
        for segment in self._uscode_subsection_heading_segments(normalized):
            if self._is_exactly_covered_span(segment, covered_spans):
                continue
            formulas.append(
                self._residual_span_coverage_formula(
                    document_id=document_id,
                    citation=citation,
                    segment=segment,
                    start_index=next_index,
                    operator=operator,
                    profile=profile,
                    fallback_rule="uscode_subsection_heading_coverage_v1",
                )
            )
            next_index += 1
            if len(formulas) >= max_formulas:
                break
        return formulas

    def modal_heading_prefix_coverage_formulas(
        self,
        *,
        document_id: str,
        text: str,
        citation: Optional[str],
        start_index: int = 1,
        segments: Optional[Sequence[LegalSegment]] = None,
        cues: Optional[Sequence[ModalCueSpan]] = None,
        max_formulas: int = 2,
    ) -> List[ModalIRFormula]:
        """Emit bounded frame formulas for U.S.C. headings before modal cues."""
        if not self._is_uscode_citation(citation):
            return []
        normalized = self.normalize_text(text)
        if not normalized.strip() or max_formulas <= 0:
            return []
        profile = self.registry.get_profile(ModalLogicFamily.FRAME)
        if not profile.operators:
            return []
        operator = profile.operators[0]
        candidate_segments = (
            list(self.segment(normalized)) if segments is None else list(segments)
        )
        candidate_cues = list(self.extract_cues(normalized) if cues is None else cues)
        formulas: List[ModalIRFormula] = []
        next_index = max(1, int(start_index))
        for index, segment in enumerate(candidate_segments):
            prefix = self._modal_heading_prefix_segment(segment, candidate_cues)
            if prefix is None and index + 1 < len(candidate_segments):
                next_segment = candidate_segments[index + 1]
                next_has_cue = any(
                    next_segment.start_char < cue.start_char < next_segment.end_char
                    for cue in candidate_cues
                )
                if (
                    next_has_cue
                    and next_segment.start_char <= segment.end_char + 1
                    and self._is_residual_span_coverage_candidate(segment)
                ):
                    prefix = LegalSegment(
                        text=segment.text,
                        start_char=segment.start_char,
                        end_char=segment.end_char,
                        role="heading",
                    )
            if prefix is None:
                continue
            formulas.append(
                self._residual_span_coverage_formula(
                    document_id=document_id,
                    citation=citation,
                    segment=prefix,
                    start_index=next_index,
                    operator=operator,
                    profile=profile,
                    fallback_rule="uscode_modal_heading_prefix_coverage_v1",
                )
            )
            next_index += 1
            if len(formulas) >= max_formulas:
                break
        return formulas

    def _classify_segment_role(self, text: str) -> str:
        lowered = text.lower()
        if lowered.startswith(("if ", "unless ", "except ", "provided that ", "subject to ")):
            return "condition"
        if " means " in lowered or lowered.startswith("the term "):
            return "definition"
        if any(term in lowered for term in ("penalty", "fine", "sanction", "remedy")):
            return "remedy"
        return "clause"

    def _segment_for_cue(self, segments: Iterable[LegalSegment], cue: ModalCueSpan) -> LegalSegment:
        for segment in segments:
            if segment.start_char <= cue.start_char < segment.end_char:
                return segment
        return LegalSegment(text="", start_char=cue.start_char, end_char=cue.end_char)

    def _predicate_from_segment(self, segment_text: str, cue: str) -> str:
        after_cue = segment_text.lower().split(cue.lower(), 1)[-1]
        tokens = _TOKEN_RE.findall(after_cue)
        if not tokens:
            tokens = _TOKEN_RE.findall(segment_text.lower())
        return "_".join(tokens[:6]) or "unnamed_predicate"

    def _is_residual_span_coverage_candidate(self, segment: LegalSegment) -> bool:
        normalized = self.normalize_text(segment.text)
        if not normalized:
            return False
        lowered = normalized.lower()
        tokens = _TOKEN_RE.findall(lowered)
        token_count = len(tokens)
        if self._is_uscode_legislative_history_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_editorial_note_heading_residual_candidate(
            normalized,
            tokens,
        ):
            return True
        if self._has_blocking_residual_modal_cues(normalized):
            return False
        if self._is_uscode_header_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_source_path_header_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_statutory_fragment_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_editorial_note_heading_residual_candidate(
            normalized,
            tokens,
        ):
            return True
        if self._is_uscode_administrative_procedure_residual_candidate(
            normalized,
            tokens,
        ):
            return True
        if self._is_uscode_administrative_frame_residual_candidate(
            normalized,
            tokens,
        ):
            return True
        if self._is_uscode_enforcement_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_definition_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_purpose_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_savings_effect_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_cost_analysis_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_transfer_functions_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_note_reference_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_revision_note_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_compact_frame_residual_candidate(normalized, tokens):
            return True
        is_short_heading_candidate = self._is_short_residual_heading_coverage_candidate(
            tokens
        )
        if (
            token_count < _USCODE_RESIDUAL_SPAN_MIN_TOKENS
            or token_count > _USCODE_RESIDUAL_SPAN_MAX_TOKENS
        ):
            if not is_short_heading_candidate:
                return False
        if (
            self._looks_like_heading_without_section_reference(normalized)
            and not (
                is_short_heading_candidate
                or self._is_long_residual_heading_coverage_candidate(tokens)
            )
        ):
            return False
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
        ):
            return False
        if (
            _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            and (
                token_count <= _USCODE_HEADING_ONLY_EXTENDED_MAX_TOKENS
                or self._looks_like_heading_without_section_reference(normalized)
            )
        ):
            return False
        return True

    def _is_generic_legal_reference_residual_candidate(
        self,
        segment: LegalSegment,
    ) -> bool:
        normalized = self.normalize_text(segment.text)
        if not normalized:
            return False
        lowered = normalized.lower()
        if self._has_blocking_residual_modal_cues(normalized):
            return False
        tokens = _TOKEN_RE.findall(lowered)
        token_count = len(tokens)
        if token_count < 4 or token_count > 36:
            return False
        if not _GENERIC_LEGAL_REFERENCE_HINT_RE.search(lowered):
            return False
        if not any(character.isdigit() for character in lowered):
            return False
        return True

    def _is_short_residual_heading_coverage_candidate(
        self,
        tokens: Sequence[str],
    ) -> bool:
        token_count = len(tokens)
        if (
            token_count < _USCODE_SHORT_RESIDUAL_HEADING_MIN_TOKENS
            or token_count > _USCODE_SHORT_RESIDUAL_HEADING_MAX_TOKENS
        ):
            return False
        return bool(
            set(tokens) & _USCODE_SHORT_RESIDUAL_HEADING_SIGNAL_TOKENS
        )

    def _is_long_residual_heading_coverage_candidate(
        self,
        tokens: Sequence[str],
    ) -> bool:
        token_count = len(tokens)
        if (
            token_count < _USCODE_LONG_RESIDUAL_HEADING_MIN_TOKENS
            or token_count > _USCODE_LONG_RESIDUAL_HEADING_MAX_TOKENS
        ):
            return False
        signal_count = len(set(tokens) & _USCODE_HEADING_ONLY_EXTENDED_NOUN_HINTS)
        return signal_count >= _USCODE_LONG_RESIDUAL_HEADING_MIN_SIGNAL_TOKENS

    def _is_uscode_compact_frame_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        """Recover compact U.S.C. frame headings that are not procedure-specific."""
        token_count = len(tokens)
        if (
            token_count < _USCODE_COMPACT_FRAME_RESIDUAL_MIN_TOKENS
            or token_count > _USCODE_COMPACT_FRAME_RESIDUAL_MAX_TOKENS
        ):
            return False
        lowered = normalized_segment_text.lower()
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
            or _USCODE_HEADING_ONLY_VERB_HINT_RE.search(lowered)
        ):
            return False
        return bool(set(tokens) & _USCODE_COMPACT_FRAME_RESIDUAL_SIGNAL_TOKENS)

    def _uscode_section_catchline_segments(
        self,
        *,
        normalized_text: str,
        citation_section: str,
    ) -> List[LegalSegment]:
        """Return cited-section catchline spans, preferring the in-body marker."""
        if not citation_section:
            return []
        section_pattern = self._citation_section_pattern(citation_section)
        marker_re = re.compile(
            rf"(?:§+\s*{section_pattern}|"
            rf"\bsec(?:tion)?s?\.?\s+{section_pattern})"
            rf"(?={_USCODE_SECTION_REF_SUFFIX_RE})"
            rf"\s*(?:[.)]|\s*-\s*)?",
            re.IGNORECASE,
        )
        candidates: List[LegalSegment] = []
        for marker in marker_re.finditer(normalized_text):
            candidate_start = marker.end()
            raw_tail = normalized_text[candidate_start : candidate_start + 360]
            if not raw_tail.strip():
                continue
            stop_match = _USCODE_SECTION_CATCHLINE_STOP_RE.search(raw_tail)
            candidate_end = candidate_start + (
                stop_match.start() if stop_match is not None else len(raw_tail)
            )
            raw_candidate = normalized_text[candidate_start:candidate_end]
            leading_offset = len(raw_candidate) - len(raw_candidate.lstrip())
            stripped = raw_candidate.strip()
            stripped = stripped.strip(" .;:\u2014-")
            if not stripped:
                continue
            if stripped.startswith(","):
                continue
            tokens = _TOKEN_RE.findall(stripped.lower())
            if (
                not tokens
                or len(tokens) > _USCODE_SECTION_CATCHLINE_MAX_TOKENS
                or _USCODE_EDITORIAL_STATUS_HINT_RE.search(stripped)
                or _USCODE_CODIFICATION_HINT_RE.search(stripped)
                or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(stripped)
                or _USCODE_HEADING_ONLY_VERB_HINT_RE.search(stripped)
            ):
                continue
            if not (
                self._looks_like_heading_without_section_reference(stripped)
                or self._is_short_residual_heading_coverage_candidate(tokens)
                or self._is_long_residual_heading_coverage_candidate(tokens)
                or self._is_uscode_compact_frame_residual_candidate(stripped, tokens)
                or self._looks_like_punctuated_section_catchline(stripped, tokens)
            ):
                continue
            start_char = candidate_start + leading_offset
            candidates.append(
                LegalSegment(
                    text=stripped,
                    start_char=start_char,
                    end_char=start_char + len(stripped),
                    role="heading",
                )
            )
        deduped: List[LegalSegment] = []
        seen_spans: set[tuple[int, int]] = set()
        for candidate in reversed(candidates):
            span = (candidate.start_char, candidate.end_char)
            if span in seen_spans:
                continue
            seen_spans.add(span)
            deduped.append(candidate)
        return deduped

    def _uscode_subsection_heading_segments(
        self,
        normalized_text: str,
    ) -> List[LegalSegment]:
        """Return compact subsection heading spans without consuming body text."""
        candidates: List[LegalSegment] = []
        seen_spans: set[tuple[int, int]] = set()
        for match in _USCODE_SUBSECTION_HEADING_RE.finditer(normalized_text):
            heading_text = match.group("heading").strip()
            if not heading_text:
                continue
            heading_body = re.sub(
                r"^\((?:[a-z]{1,3}|[0-9]{1,3}|[ivxlcdm]{1,6})\)\s+",
                "",
                heading_text,
                flags=re.IGNORECASE,
            ).strip(" .")
            if not heading_body:
                continue
            if self._has_blocking_residual_modal_cues(heading_body):
                continue
            body_tokens = _TOKEN_RE.findall(heading_body.lower())
            if not (
                self._is_short_residual_heading_coverage_candidate(body_tokens)
                or self._looks_like_heading_without_section_reference(heading_body)
                or heading_body.lower() in {"in general", "general"}
            ):
                continue
            start_char = match.start("heading")
            end_char = match.end("heading")
            span = (start_char, end_char)
            if span in seen_spans:
                continue
            seen_spans.add(span)
            candidates.append(
                LegalSegment(
                    text=heading_text,
                    start_char=start_char,
                    end_char=end_char,
                    role="heading",
                )
            )
        return candidates

    def _uscode_section_marker_segments(
        self,
        *,
        normalized_text: str,
        citation_section: str,
    ) -> List[LegalSegment]:
        """Return compact ``Sec. N -`` and ``§N.`` marker spans for a citation."""
        if not citation_section:
            return []
        section_pattern = self._citation_section_pattern(citation_section)
        marker_re = re.compile(
            rf"(?P<marker>\s*(?:"
            rf"\bsec(?:tion)?s?\.?\s+{section_pattern}\s*(?:[-\u2012\u2013\u2014]\s*)?|"
            rf"§+\s*{section_pattern}\s*[.)]?"
            rf"))(?=\s|$)",
            re.IGNORECASE,
        )
        candidates: List[LegalSegment] = []
        seen_spans: set[tuple[int, int]] = set()
        for marker in marker_re.finditer(normalized_text):
            marker_text = marker.group("marker")
            if not marker_text or not marker_text.strip():
                continue
            start_char = marker.start("marker")
            end_char = marker.end("marker")
            span = (start_char, end_char)
            if span in seen_spans:
                continue
            seen_spans.add(span)
            candidates.append(
                LegalSegment(
                    text=marker_text,
                    start_char=start_char,
                    end_char=end_char,
                    role="section_marker",
                )
            )
        return candidates

    def _is_exactly_covered_span(
        self,
        segment: LegalSegment,
        covered_spans: Sequence[tuple[int, int]],
    ) -> bool:
        return any(
            int(start_char) == segment.start_char and int(end_char) == segment.end_char
            for start_char, end_char in covered_spans
        )

    def _is_overlapping_covered_span(
        self,
        segment: LegalSegment,
        covered_spans: Sequence[tuple[int, int]],
    ) -> bool:
        return any(
            self._spans_overlap(
                segment.start_char,
                segment.end_char,
                start_char,
                end_char,
            )
            for start_char, end_char in covered_spans
        )

    def _modal_heading_prefix_segment(
        self,
        segment: LegalSegment,
        cues: Sequence[ModalCueSpan],
    ) -> Optional[LegalSegment]:
        segment_cues = [
            cue
            for cue in cues
            if segment.start_char < cue.start_char < segment.end_char
        ]
        if not segment_cues:
            return None
        first_cue = min(segment_cues, key=lambda cue: cue.start_char)
        prefix_text = segment.text[: first_cue.start_char - segment.start_char].strip()
        if not prefix_text:
            return None
        section_prefix_match = re.match(
            rf"^\s*(?P<prefix>{_USCODE_SECTION_REF_PREFIX_RE})?"
            rf"(?P<section>[0-9A-Za-z.\-]+){_USCODE_SECTION_REF_SUFFIX_RE}\s*",
            prefix_text,
            flags=re.IGNORECASE,
        )
        if section_prefix_match is not None:
            section_token = section_prefix_match.group("section")
            if (
                section_prefix_match.group("prefix")
                or any(character.isdigit() for character in section_token)
                or "-" in section_token
                or _USCODE_SECTION_DASH_VARIANT_RE.search(section_token)
            ):
                prefix_text = prefix_text[section_prefix_match.end() :]
        prefix_text = prefix_text.strip(" .;:\u2014-")
        subsection_match = re.search(
            r"\((?:[a-z]{1,3}|[0-9]{1,3}|[ivxlcdm]{1,6})\)\s+",
            prefix_text,
            flags=re.IGNORECASE,
        )
        if subsection_match is not None:
            prefix_text = prefix_text[subsection_match.end() :].strip(" .;:\u2014-")
        prefix_text = re.split(
            r"\b(?:not\s+less\s+often\s+than|not\s+later\s+than|"
            r"within\s+\d+|the\s+(?:secretary|commission|administrator)\b)",
            prefix_text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" .;:\u2014-")
        if not prefix_text:
            return None
        if self._has_blocking_residual_modal_cues(prefix_text):
            return None
        tokens = _TOKEN_RE.findall(prefix_text.lower())
        token_count = len(tokens)
        if token_count < 2 or token_count > _USCODE_MODAL_HEADING_PREFIX_MAX_TOKENS:
            return None
        if not (
            self._is_short_residual_heading_coverage_candidate(tokens)
            or self._is_long_residual_heading_coverage_candidate(tokens)
            or self._is_uscode_administrative_procedure_residual_candidate(
                prefix_text,
                tokens,
            )
        ):
            return None
        stripped_segment_start = segment.end_char - len(segment.text)
        prefix_start = stripped_segment_start + segment.text.index(prefix_text)
        return LegalSegment(
            text=prefix_text,
            start_char=prefix_start,
            end_char=prefix_start + len(prefix_text),
            role="heading",
        )

    def _residual_paragraph_heading_prefix_segment(
        self,
        segment: LegalSegment,
    ) -> Optional[LegalSegment]:
        match = re.match(
            r"^\s*(?P<prefix>.{1,120}?\.)\s*(?:\u2014|--|-)",
            segment.text,
        )
        if match is None:
            return None
        prefix_text = match.group("prefix").strip()
        if not prefix_text:
            return None
        if self._has_blocking_residual_modal_cues(prefix_text):
            return None
        tokens = _TOKEN_RE.findall(prefix_text.lower())
        if not (
            self._is_short_residual_heading_coverage_candidate(tokens)
            or self._is_long_residual_heading_coverage_candidate(tokens)
            or self._looks_like_heading_without_section_reference(prefix_text)
        ):
            return None
        prefix_start = segment.start_char + segment.text.index(prefix_text)
        return LegalSegment(
            text=prefix_text,
            start_char=prefix_start,
            end_char=prefix_start + len(prefix_text),
            role="heading",
        )

    def _uscode_source_path_header_prefix_segment(
        self,
        segment: LegalSegment,
    ) -> Optional[LegalSegment]:
        match = re.match(
            r"^\s*(?P<prefix>(?:(?:title|subtitle|chapter|subchapter|part)\s+"
            r"[0-9A-Za-zIVXLCDM.\-]+(?:\s+-)?"
            r"(?:\s+[A-Z][A-Z0-9'&,.\-]+)*?)\.)"
            r"(?=\s+(?:sec(?:tion)?s?\.?|§|from\s+the\s+u\.?\s*s\.?\s+"
            r"government\s+publishing\s+office)\b)",
            segment.text,
            re.IGNORECASE,
        )
        if match is None:
            return None
        prefix_text = match.group("prefix").strip()
        if not prefix_text:
            return None
        if self._has_blocking_residual_modal_cues(prefix_text):
            return None
        tokens = _TOKEN_RE.findall(prefix_text.lower())
        if not self._is_uscode_source_path_header_residual_candidate(
            prefix_text,
            tokens,
        ):
            return None
        prefix_start = segment.start_char + segment.text.index(prefix_text)
        return LegalSegment(
            text=prefix_text,
            start_char=prefix_start,
            end_char=prefix_start + len(prefix_text),
            role="heading",
        )

    def _coalesce_short_residual_segments(
        self,
        segments: Sequence[LegalSegment],
        *,
        normalized_text: str,
    ) -> List[LegalSegment]:
        """Join contiguous short residual fragments split by abbreviation punctuation."""
        if len(segments) < 2:
            return list(segments)
        coalesced: List[LegalSegment] = []
        index = 0
        while index < len(segments):
            segment = segments[index]
            start = index
            end = index + 1
            total_tokens = len(_TOKEN_RE.findall(segment.text.lower()))
            if total_tokens > _USCODE_RESIDUAL_COALESCE_SEGMENT_MAX_TOKENS:
                coalesced.append(segment)
                index += 1
                continue
            while end < len(segments):
                next_segment = segments[end]
                if next_segment.start_char > segments[end - 1].end_char + 1:
                    break
                if re.match(
                    r"^\s*\((?:[a-z]{1,3}|[0-9]{1,3}|[ivxlcdm]{1,6})\)\s+",
                    next_segment.text,
                    re.IGNORECASE,
                ):
                    break
                next_tokens = len(_TOKEN_RE.findall(next_segment.text.lower()))
                if next_tokens > _USCODE_RESIDUAL_COALESCE_SEGMENT_MAX_TOKENS:
                    break
                if (
                    total_tokens + next_tokens
                    > _USCODE_RESIDUAL_SPAN_MAX_TOKENS
                ):
                    break
                if (
                    total_tokens > _USCODE_RESIDUAL_COALESCE_SEGMENT_MAX_TOKENS
                    and next_tokens > _USCODE_RESIDUAL_COALESCE_SEGMENT_MAX_TOKENS
                ):
                    break
                total_tokens += next_tokens
                end += 1
            if end - start <= 1:
                coalesced.append(segment)
                index += 1
                continue
            merged_start = segments[start].start_char
            merged_end = segments[end - 1].end_char
            merged_text = normalized_text[merged_start:merged_end]
            coalesced.append(
                LegalSegment(
                    text=merged_text,
                    start_char=merged_start,
                    end_char=merged_end,
                    role=segments[start].role,
                )
            )
            index = end
        return coalesced

    def _is_uscode_header_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        token_count = len(tokens)
        if token_count > _USCODE_RESIDUAL_SPAN_MAX_TOKENS:
            return False
        lowered = normalized_segment_text.lower()
        has_header_scope = any(
            phrase in lowered for phrase in _USCODE_RESIDUAL_HEADER_SCOPE_PHRASES
        )
        if not has_header_scope:
            return False
        if token_count >= _USCODE_RESIDUAL_HEADER_MIN_TOKENS:
            return True
        if token_count < _USCODE_RESIDUAL_SHORT_HEADER_MIN_TOKENS:
            return False
        if (
            "government publishing office" in lowered
            or "www.gpo.gov" in lowered
        ):
            return True
        return "u.s.c." in lowered or "united states code" in lowered

    def _is_uscode_source_path_header_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        """Recover compact U.S.C. hierarchy prefixes split from section headings."""
        token_count = len(tokens)
        if (
            token_count < 2
            or token_count > _USCODE_RESIDUAL_SPAN_MAX_TOKENS
        ):
            return False
        lowered = normalized_segment_text.lower()
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
            or _USCODE_HEADING_ONLY_VERB_HINT_RE.search(lowered)
        ):
            return False
        return bool(_USCODE_SOURCE_PATH_HEADER_RE.search(normalized_segment_text))

    def _is_uscode_statutory_fragment_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        token_count = len(tokens)
        if token_count < 1:
            return False
        if token_count > _USCODE_RESIDUAL_STATUTORY_FRAGMENT_MAX_TOKENS:
            return False
        lowered = normalized_segment_text.lower()
        if not any(character.isdigit() for character in lowered):
            return False
        if lowered.lstrip().startswith(("§", "§§")):
            return True
        return bool(_USCODE_RESIDUAL_STATUTORY_FRAGMENT_HINT_RE.search(lowered))

    def _is_uscode_editorial_note_heading_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        """Recover compact U.S.C. editorial-note headings without operative cues."""
        token_count = len(tokens)
        if (
            token_count < 2
            or token_count > _USCODE_EDITORIAL_NOTE_HEADING_RESIDUAL_MAX_TOKENS
        ):
            return False
        lowered = normalized_segment_text.lower()
        if (
            _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
            or _USCODE_HEADING_ONLY_VERB_HINT_RE.search(lowered)
        ):
            return False
        return bool(
            _USCODE_EDITORIAL_NOTE_HEADING_RESIDUAL_RE.fullmatch(
                normalized_segment_text
            )
        )

    def _is_uscode_administrative_procedure_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        """Recover procedural frame spans that have no explicit modal cue."""
        token_count = len(tokens)
        if token_count < 2:
            return False
        if token_count > _USCODE_ADMINISTRATIVE_PROCEDURE_RESIDUAL_MAX_TOKENS:
            return False
        lowered = normalized_segment_text.lower()
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
        ):
            return False
        if _USCODE_ADMINISTRATIVE_PROCEDURE_PHRASE_RE.search(lowered):
            return True
        signal_count = len(
            set(tokens) & _USCODE_ADMINISTRATIVE_PROCEDURE_SIGNAL_TOKENS
        )
        return signal_count >= 2 and bool(
            set(tokens)
            & {
                "administrative",
                "adjudication",
                "adjudications",
                "appeal",
                "appeals",
                "comment",
                "comments",
                "hearing",
                "hearings",
                "investigation",
                "investigations",
                "notice",
                "proceeding",
                "proceedings",
                "record",
                "records",
                "review",
            }
        )

    def _is_uscode_administrative_frame_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        """Recover administrative approval/review frame spans without modal cues."""
        token_count = len(tokens)
        if token_count < 2:
            return False
        if token_count > _USCODE_ADMINISTRATIVE_FRAME_RESIDUAL_MAX_TOKENS:
            return False
        lowered = normalized_segment_text.lower()
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
        ):
            return False
        token_set = set(tokens)
        return bool(
            token_set & _USCODE_ADMINISTRATIVE_FRAME_CONTEXT_TOKENS
        ) and bool(token_set & _USCODE_ADMINISTRATIVE_FRAME_PROCESS_TOKENS)

    def _is_uscode_enforcement_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        """Recover criminal/civil enforcement frame spans without explicit modals."""
        token_count = len(tokens)
        if token_count < 1:
            return False
        if token_count > _USCODE_ENFORCEMENT_RESIDUAL_MAX_TOKENS:
            return False
        lowered = normalized_segment_text.lower()
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
        ):
            return False
        token_set = set(tokens)
        signal_count = len(token_set & _USCODE_ENFORCEMENT_RESIDUAL_SIGNAL_TOKENS)
        if signal_count >= 2:
            return True
        if signal_count < 1:
            return False
        if token_count <= _USCODE_COMPACT_FRAME_RESIDUAL_MAX_TOKENS:
            return True
        return bool(token_set & _USCODE_ENFORCEMENT_RESIDUAL_CONTEXT_TOKENS)

    def _is_uscode_definition_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        token_count = len(tokens)
        if token_count < 4 or token_count > _USCODE_RESIDUAL_SPAN_MAX_TOKENS:
            return False
        lowered = normalized_segment_text.lower()
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
        ):
            return False
        if "term" not in set(tokens) and "terms" not in set(tokens):
            return False
        return bool(_USCODE_DEFINITION_RESIDUAL_HINT_RE.search(lowered))

    def _is_uscode_purpose_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        token_count = len(tokens)
        if token_count < 4 or token_count > _USCODE_RESIDUAL_SPAN_MAX_TOKENS:
            return False
        lowered = normalized_segment_text.lower()
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
        ):
            return False
        if not _USCODE_PURPOSE_RESIDUAL_HINT_RE.search(lowered):
            return False
        return bool(set(tokens) & _USCODE_PURPOSE_RESIDUAL_SIGNAL_TOKENS)

    def _is_uscode_savings_effect_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        """Recover non-supersession/savings frame spans without explicit modals."""
        token_count = len(tokens)
        if token_count < 5 or token_count > _USCODE_SAVINGS_EFFECT_RESIDUAL_MAX_TOKENS:
            return False
        lowered = normalized_segment_text.lower()
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
        ):
            return False
        if not _USCODE_SAVINGS_EFFECT_RESIDUAL_HINT_RE.search(lowered):
            return False
        return bool(set(tokens) & _USCODE_SAVINGS_EFFECT_RESIDUAL_SIGNAL_TOKENS)

    def _is_uscode_cost_analysis_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        """Recover compact cost-analysis frame headings without modal cues."""
        token_count = len(tokens)
        if token_count < 2 or token_count > _USCODE_COMPACT_FRAME_RESIDUAL_MAX_TOKENS:
            return False
        lowered = normalized_segment_text.lower()
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
            or _USCODE_HEADING_ONLY_VERB_HINT_RE.search(lowered)
        ):
            return False
        return bool(_USCODE_COST_ANALYSIS_RESIDUAL_RE.search(lowered))

    def _is_uscode_transfer_functions_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        """Recover statutory transfer-of-functions notes without modal cues."""
        token_count = len(tokens)
        if (
            token_count < 8
            or token_count > _USCODE_TRANSFER_FUNCTIONS_RESIDUAL_MAX_TOKENS
        ):
            return False
        lowered = normalized_segment_text.lower()
        if (
            _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
        ):
            return False
        return bool(_USCODE_TRANSFER_FUNCTIONS_RESIDUAL_RE.search(lowered))

    def _is_uscode_note_reference_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        token_count = len(tokens)
        if token_count < 6 or token_count > _USCODE_RESIDUAL_SPAN_MAX_TOKENS:
            return False
        if _USCODE_CODIFICATION_HINT_RE.search(normalized_segment_text):
            return False
        return bool(_USCODE_NOTE_REFERENCE_RESIDUAL_RE.search(normalized_segment_text))

    def _is_uscode_revision_note_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        token_count = len(tokens)
        if token_count < 4 or token_count > _USCODE_RESIDUAL_SPAN_MAX_TOKENS:
            return False
        if _USCODE_CODIFICATION_HINT_RE.search(normalized_segment_text):
            return False
        return bool(_USCODE_REVISION_NOTE_RESIDUAL_RE.search(normalized_segment_text))

    def _is_uscode_editorial_note_heading_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        """Recover compact editorial-note heading spans without treating them as time."""
        token_count = len(tokens)
        if (
            token_count < 2
            or token_count > _USCODE_EDITORIAL_NOTE_HEADING_RESIDUAL_MAX_TOKENS
        ):
            return False
        if any(character.isdigit() for character in normalized_segment_text):
            return False
        return bool(
            _USCODE_EDITORIAL_NOTE_HEADING_RESIDUAL_RE.search(
                normalized_segment_text
            )
        )

    def _is_uscode_legislative_history_residual_candidate(
        self,
        normalized_segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        token_count = len(tokens)
        if token_count < 4 or token_count > _USCODE_RESIDUAL_SPAN_MAX_TOKENS:
            return False
        lowered = normalized_segment_text.lower()
        if not any(character.isdigit() for character in lowered):
            return False
        return bool(
            _USCODE_LEGISLATIVE_HISTORY_RESIDUAL_RE.search(lowered)
            or _USCODE_LEGISLATIVE_HISTORY_CONTINUATION_RE.search(lowered)
        )

    def _residual_span_coverage_formula(
        self,
        *,
        document_id: str,
        citation: Optional[str],
        segment: LegalSegment,
        start_index: int,
        operator: ModalOperatorSpec,
        profile: ModalParseProfile,
        fallback_rule: Optional[str] = None,
    ) -> ModalIRFormula:
        predicate = self._predicate_from_segment(
            segment.text,
            "__uscode_residual_span_fallback__",
        )
        conditions, exceptions = self._conditions_and_exceptions_from_segment(segment.text)
        token_count = len(_TOKEN_RE.findall(segment.text.lower()))
        return ModalIRFormula(
            formula_id=f"{document_id}:f{start_index:04d}",
            operator=ModalIROperator(
                family=profile.family.value,
                system=profile.system.value,
                symbol=operator.symbol,
                label=operator.aliases[0] if operator.aliases else operator.symbol,
            ),
            predicate=ModalIRPredicate(
                name=predicate,
                arguments=[],
                role=segment.role,
            ),
            provenance=ModalIRProvenance(
                source_id=document_id,
                start_char=segment.start_char,
                end_char=segment.end_char,
                citation=citation,
            ),
            conditions=conditions,
            exceptions=exceptions,
            metadata={
                "cue": (
                    "__uscode_residual_span_fallback__"
                    if self._is_uscode_citation(citation)
                    else "__legal_reference_residual_span_fallback__"
                ),
                "fallback_rule": fallback_rule
                or (
                    "uscode_residual_span_coverage_v1"
                    if self._is_uscode_citation(citation)
                    else "legal_reference_residual_span_coverage_v1"
                ),
                "residual_segment_role": segment.role,
                "residual_token_count": token_count,
            },
        )

    def _conditions_and_exceptions_from_segment(
        self,
        segment_text: str,
    ) -> tuple[List[str], List[str]]:
        return (
            self._prefixed_clause_phrases(segment_text, _CONDITION_PREFIXES),
            self._prefixed_clause_phrases(segment_text, _EXCEPTION_PREFIXES),
        )

    def _prefixed_clause_phrases(
        self,
        segment_text: str,
        prefixes: Iterable[str],
    ) -> List[str]:
        normalized = self.normalize_text(segment_text)
        phrases: List[str] = []
        for prefix in sorted(prefixes, key=lambda value: (-len(value), value)):
            pattern = re.compile(rf"(?<!\w){re.escape(prefix)}(?!\w)", re.IGNORECASE)
            for match in pattern.finditer(normalized):
                fragment = normalized[match.start() :]
                fragment = _CLAUSE_DELIMITER_RE.split(fragment, maxsplit=1)[0]
                phrase = self._normalized_clause_phrase(fragment)
                if phrase and phrase not in phrases:
                    phrases.append(phrase)
        return phrases

    def _normalized_clause_phrase(self, text: str) -> str:
        tokens = _TOKEN_RE.findall(text.lower())
        return " ".join(tokens[:18]).strip()

    def _document_id(self, normalized_text: str) -> str:
        digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:16]
        return f"legal-text-{digest}"

    def _segments_excluding_spans(
        self,
        segments: Sequence[LegalSegment],
        *,
        spans: Sequence[tuple[int, int]],
    ) -> List[LegalSegment]:
        if not spans:
            return list(segments)
        normalized_spans = sorted(
            (
                (max(0, int(span_start)), max(0, int(span_end)))
                for span_start, span_end in spans
                if int(span_end) > int(span_start)
            )
        )
        residual_segments: List[LegalSegment] = []
        for segment in segments:
            pieces: List[tuple[int, int]] = [(segment.start_char, segment.end_char)]
            for span_start, span_end in normalized_spans:
                next_pieces: List[tuple[int, int]] = []
                for piece_start, piece_end in pieces:
                    if not self._spans_overlap(
                        piece_start,
                        piece_end,
                        span_start,
                        span_end,
                    ):
                        next_pieces.append((piece_start, piece_end))
                        continue
                    if piece_start < span_start:
                        next_pieces.append((piece_start, min(piece_end, span_start)))
                    if span_end < piece_end:
                        next_pieces.append((max(piece_start, span_end), piece_end))
                pieces = next_pieces
                if not pieces:
                    break
            for piece_start, piece_end in pieces:
                piece_text = segment.text[
                    max(0, piece_start - segment.start_char) : max(
                        0,
                        piece_end - segment.start_char,
                    )
                ]
                if not self.normalize_text(piece_text):
                    continue
                residual_segments.append(
                    LegalSegment(
                        text=piece_text,
                        start_char=piece_start,
                        end_char=piece_end,
                        role=segment.role,
                    )
                )
        return residual_segments

    @staticmethod
    def _spans_overlap(
        left_start: int,
        left_end: int,
        right_start: int,
        right_end: int,
    ) -> bool:
        return max(int(left_start), int(right_start)) < min(int(left_end), int(right_end))

    def _uscode_codification_fallback_formula(
        self,
        *,
        resolved_document_id: str,
        normalized_text: str,
        citation: Optional[str],
        segments: Sequence[LegalSegment],
        start_index: int,
        allow_modal_cues: bool = False,
    ) -> Optional[ModalIRFormula]:
        if not normalized_text.strip():
            return None
        if not self._is_uscode_citation(citation):
            return None
        if not allow_modal_cues and self._parse_eligible_cues(
            normalized_text,
            citation=citation,
        ):
            return None

        candidate_segment: Optional[LegalSegment] = None
        transferred_heading_segment: Optional[LegalSegment] = None
        for segment in segments:
            if not _USCODE_CODIFICATION_HINT_RE.search(segment.text):
                continue
            lowered_segment = segment.text.lower()
            if "reclassified" in lowered_segment or "codification" in lowered_segment:
                candidate_segment = segment
                break
            if transferred_heading_segment is None:
                transferred_heading_segment = segment
        if transferred_heading_segment is not None:
            candidate_segment = transferred_heading_segment
        elif candidate_segment is None:
            candidate_segment = transferred_heading_segment
        elif transferred_heading_segment is not None and (
            re.match(
                rf"^\s*{_USCODE_OPTIONAL_SECTION_REF_PREFIX_RE}[0-9A-Za-z.\-\u2010-\u2015]+"
                rf"{_USCODE_SECTION_REF_SUFFIX_RE}\s*[-\u2012\u2013\u2014]?\s*transferred\b",
                transferred_heading_segment.text,
                re.IGNORECASE,
            )
        ):
            candidate_segment = transferred_heading_segment
        if candidate_segment is None:
            return None
        candidate_segment = self._expanded_uscode_codification_segment(
            candidate_segment=candidate_segment,
            normalized_text=normalized_text,
            segments=segments,
        )

        lowered = candidate_segment.text.lower()
        citation_section = self._citation_section_token(citation)
        has_reclassification_hint = "reclassified" in lowered or "codification" in lowered
        has_transferred_heading_hint = self._looks_like_transferred_section_heading(
            candidate_segment.text,
            citation_section=citation_section,
        )
        has_cross_title_reclassification = self._has_cross_title_reclassification(
            lowered,
            citation=citation,
        )
        transferred_heading_rule_preferred = has_transferred_heading_hint and (
            not has_reclassification_hint
            or (
                not has_cross_title_reclassification
                and (
                    "government publishing office" in lowered
                    or "of this title" in lowered
                    or re.search(r"\bof\s+title\s+\d+\b", lowered) is not None
                )
            )
        )

        if not has_reclassification_hint and not has_transferred_heading_hint:
            return None
        if "section" not in lowered and not has_transferred_heading_hint:
            return None

        profile = self.registry.get_profile(ModalLogicFamily.FRAME)
        if not profile.operators:
            return None
        operator = profile.operators[0]
        predicate = self._predicate_from_segment(
            candidate_segment.text,
            "__uscode_codification_fallback__",
        )
        conditions, exceptions = self._conditions_and_exceptions_from_segment(
            candidate_segment.text
        )
        return ModalIRFormula(
            formula_id=f"{resolved_document_id}:f{start_index:04d}",
            operator=ModalIROperator(
                family=profile.family.value,
                system=profile.system.value,
                symbol=operator.symbol,
                label=operator.aliases[0] if operator.aliases else operator.symbol,
            ),
            predicate=ModalIRPredicate(
                name=predicate,
                arguments=[],
                role="frame",
            ),
            provenance=ModalIRProvenance(
                source_id=resolved_document_id,
                start_char=candidate_segment.start_char,
                end_char=candidate_segment.end_char,
                citation=citation,
            ),
            conditions=conditions,
            exceptions=exceptions,
            metadata={
                "cue": "__uscode_codification_fallback__",
                "fallback_rule": (
                    "uscode_transferred_heading_v1"
                    if transferred_heading_rule_preferred
                    else "uscode_codification_transfer_heading_v1"
                ),
            },
        )

    def _expanded_uscode_codification_segment(
        self,
        *,
        candidate_segment: LegalSegment,
        normalized_text: str,
        segments: Sequence[LegalSegment],
    ) -> LegalSegment:
        """Recover codification note spans split by legal abbreviation periods."""
        candidate_text = self.normalize_text(candidate_segment.text)
        lowered_candidate = candidate_text.lower()
        if not re.search(
            r"\b(?:omitted|transferred)\s+editorial\s+notes\s+codification\b",
            lowered_candidate,
        ):
            return candidate_segment
        if "section" not in lowered_candidate:
            return candidate_segment

        candidate_index: Optional[int] = None
        for index, segment in enumerate(segments):
            if (
                segment.start_char == candidate_segment.start_char
                and segment.end_char == candidate_segment.end_char
            ):
                candidate_index = index
                break
        if candidate_index is None:
            return candidate_segment

        start_char = candidate_segment.start_char
        end_char = candidate_segment.end_char
        for next_segment in segments[candidate_index + 1 :]:
            if next_segment.start_char > end_char + 1:
                break
            tentative_text = self.normalize_text(
                normalized_text[start_char : next_segment.end_char]
            )
            if not tentative_text:
                break
            tentative_tokens = _TOKEN_RE.findall(tentative_text.lower())
            if len(tentative_tokens) > _USCODE_RESIDUAL_SPAN_MAX_TOKENS:
                break
            lowered_tentative = tentative_text.lower()
            if not (
                any(character.isdigit() for character in lowered_tentative)
                or "pub." in lowered_tentative
                or "stat." in lowered_tentative
                or "was omitted" in lowered_tentative
                or "was editorially reclassified" in lowered_tentative
                or "from the code" in lowered_tentative
            ):
                break
            end_char = next_segment.end_char
            if re.search(
                r"\bwas\s+(?:omitted|editorially\s+reclassified|transferred)\b",
                lowered_tentative,
            ) and tentative_text.rstrip().endswith("."):
                break

        if end_char == candidate_segment.end_char:
            return candidate_segment
        expanded_text = normalized_text[start_char:end_char]
        stripped_expanded_text = expanded_text.strip()
        if not stripped_expanded_text:
            return candidate_segment
        lowered_expanded_text = stripped_expanded_text.lower()
        if not (
            "was omitted from the code" in lowered_expanded_text
            or "was editorially reclassified" in lowered_expanded_text
            or "reclassified as section" in lowered_expanded_text
        ):
            return candidate_segment
        leading_offset = len(expanded_text) - len(expanded_text.lstrip())
        return LegalSegment(
            text=stripped_expanded_text,
            start_char=start_char + leading_offset,
            end_char=start_char + leading_offset + len(stripped_expanded_text),
            role=candidate_segment.role,
        )

    def _citation_section_token(self, citation: Optional[str]) -> str:
        if not citation:
            return ""
        match = _USCODE_CITATION_SECTION_RE.search(citation)
        if not match:
            return ""
        token = match.group(1).strip().lower()
        token = _USCODE_TRAILING_SECTION_PUNCT_RE.sub("", token)
        return self._normalized_citation_section_token(token)

    def _citation_title_token(self, citation: Optional[str]) -> str:
        if not citation:
            return ""
        match = re.search(
            r"\b(?P<title>\d+[A-Za-z]*)\s+U\.?\s*S\.?\s*C\.?(?!\w)",
            citation,
            re.IGNORECASE,
        )
        if not match:
            return ""
        return match.group("title").strip().lower()

    def _has_cross_title_reclassification(
        self,
        text: str,
        *,
        citation: Optional[str],
    ) -> bool:
        source_title = self._citation_title_token(citation)
        if not source_title:
            return False
        if "reclassified as section" not in text:
            return False
        for match in re.finditer(r"\bof\s+title\s+(?P<title>\d+[a-z]*)\b", text):
            target_title = match.group("title").strip().lower()
            if target_title and target_title != source_title:
                return True
        return False

    def _normalized_citation_section_token(self, token: str) -> str:
        normalized = _USCODE_SECTION_DASH_VARIANT_RE.sub("-", token.lower())
        return re.sub(r"\s*-\s*", "-", normalized)

    def _citation_section_pattern(self, citation_section: str) -> str:
        escaped = re.escape(self._normalized_citation_section_token(citation_section))
        return escaped.replace(r"\-", _USCODE_SECTION_DASH_PATTERN)

    def _is_uscode_citation(self, citation: Optional[str]) -> bool:
        if not citation:
            return False
        return bool(_USCODE_CITATION_MARKER_RE.search(citation))

    def _contains_citation_section_reference(self, text: str, citation_section: str) -> bool:
        if not citation_section:
            return False
        normalized = self.normalize_text(text).lower()
        section_pattern = self._citation_section_pattern(citation_section)
        if re.search(
            rf"{_USCODE_SECTION_REF_PREFIX_RE}{section_pattern}"
            rf"(?={_USCODE_SECTION_REF_SUFFIX_RE})",
            normalized,
        ):
            return True
        return False

    def _starts_with_citation_section_reference(self, text: str, citation_section: str) -> bool:
        if not citation_section:
            return False
        normalized = self.normalize_text(text).lower()
        section_pattern = self._citation_section_pattern(citation_section)
        return bool(
            re.match(
                rf"^{_USCODE_OPTIONAL_SECTION_REF_PREFIX_RE}{section_pattern}"
                rf"(?={_USCODE_SECTION_REF_SUFFIX_RE})",
                normalized,
            )
        )

    def _embedded_citation_heading_segment(
        self,
        *,
        normalized_text: str,
        citation_section: str,
    ) -> Optional[LegalSegment]:
        """Extract a compact heading window anchored to an in-text section reference."""
        if not citation_section:
            return None

        section_pattern = self._citation_section_pattern(citation_section)
        reference_pattern = re.compile(
            rf"(?<!\w){_USCODE_OPTIONAL_SECTION_REF_PREFIX_RE}{section_pattern}"
            rf"(?={_USCODE_SECTION_REF_SUFFIX_RE})",
            re.IGNORECASE,
        )
        best_segment: Optional[LegalSegment] = None
        best_score: Optional[tuple[int, int, int]] = None

        for match in reference_pattern.finditer(normalized_text):
            start = match.start()
            window_end = min(
                len(normalized_text),
                start + _USCODE_EMBEDDED_HEADING_WINDOW_MAX_CHARS,
            )
            window = normalized_text[start:window_end]
            lowered_window = window.lower()
            cut = len(window)

            for marker in (
                " from the u.s. government publishing office",
                " editorial notes ",
                " historical and revision notes ",
                " amendments ",
            ):
                marker_index = lowered_window.find(marker)
                if marker_index != -1:
                    cut = min(cut, marker_index)

            subsection_match = _USCODE_SUBSECTION_MARKER_RE.search(
                window,
                pos=max(match.end() - start, 0),
            )
            if subsection_match is not None:
                cut = min(cut, subsection_match.start())

            candidate_text = self.normalize_text(window[:cut])
            if not candidate_text:
                continue
            token_count = len(_TOKEN_RE.findall(candidate_text.lower()))
            if token_count < 2 or token_count > _USCODE_SECTION_HEADING_EXTENDED_MAX_TOKENS:
                continue

            has_prefixed_reference = bool(
                re.match(rf"^{_USCODE_SECTION_REF_PREFIX_RE}", candidate_text, re.IGNORECASE)
            )
            score = (0 if has_prefixed_reference else 1, token_count, start)
            if best_score is None or score < best_score:
                best_score = score
                best_segment = LegalSegment(
                    text=candidate_text,
                    start_char=start,
                    end_char=start + len(candidate_text),
                    role="clause",
                )

        return best_segment

    def _uscode_editorial_status_fallback_formula(
        self,
        *,
        resolved_document_id: str,
        normalized_text: str,
        citation: Optional[str],
        segments: Sequence[LegalSegment],
        start_index: int,
        allow_modal_cues: bool = False,
    ) -> Optional[ModalIRFormula]:
        if not normalized_text.strip():
            return None
        if not self._is_uscode_citation(citation):
            return None
        if not allow_modal_cues and self._parse_eligible_cues(
            normalized_text,
            citation=citation,
        ):
            return None

        citation_section = self._citation_section_token(citation)
        if not citation_section:
            return None

        candidate_segment: Optional[LegalSegment] = None
        status_keyword = ""
        for index, segment in enumerate(segments):
            status_match = _USCODE_EDITORIAL_STATUS_HINT_RE.search(segment.text)
            if not status_match:
                continue
            previous_segment_text = segments[index - 1].text if index > 0 else ""
            if not self._looks_like_editorial_status_heading(
                segment.text,
                citation_section=citation_section,
                previous_segment_text=previous_segment_text,
            ):
                continue
            candidate_segment = segment
            status_keyword = status_match.group(0).lower()
            break
        if candidate_segment is None:
            return None

        profile = self.registry.get_profile(ModalLogicFamily.FRAME)
        if not profile.operators:
            return None
        operator = profile.operators[0]
        predicate = self._predicate_from_segment(
            candidate_segment.text,
            "__uscode_editorial_status_fallback__",
        )
        conditions, exceptions = self._conditions_and_exceptions_from_segment(
            candidate_segment.text
        )
        return ModalIRFormula(
            formula_id=f"{resolved_document_id}:f{start_index:04d}",
            operator=ModalIROperator(
                family=profile.family.value,
                system=profile.system.value,
                symbol=operator.symbol,
                label=operator.aliases[0] if operator.aliases else operator.symbol,
            ),
            predicate=ModalIRPredicate(
                name=predicate,
                arguments=[],
                role="frame",
            ),
            provenance=ModalIRProvenance(
                source_id=resolved_document_id,
                start_char=candidate_segment.start_char,
                end_char=candidate_segment.end_char,
                citation=citation,
            ),
            conditions=conditions,
            exceptions=exceptions,
            metadata={
                "cue": "__uscode_editorial_status_fallback__",
                "fallback_rule": "uscode_editorial_status_heading_v1",
                "status_keyword": status_keyword,
            },
        )

    def _uscode_declarative_statement_fallback_formula(
        self,
        *,
        resolved_document_id: str,
        normalized_text: str,
        citation: Optional[str],
        segments: Sequence[LegalSegment],
        start_index: int,
        allow_modal_cues: bool = False,
    ) -> Optional[ModalIRFormula]:
        if not normalized_text.strip():
            return None
        if not self._is_uscode_citation(citation):
            return None
        if not allow_modal_cues and self._parse_eligible_cues(
            normalized_text,
            citation=citation,
        ):
            return None

        citation_section = self._citation_section_token(citation)
        if not citation_section:
            return None
        has_section_reference = self._contains_sec_heading_reference(
            normalized_text,
            citation_section=citation_section,
        )

        candidate_segment: Optional[LegalSegment] = None
        statement_hint = ""
        for index, segment in enumerate(segments):
            lowered = self.normalize_text(segment.text).lower()
            if not _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered):
                continue
            if has_section_reference:
                if not self._segment_or_neighbor_has_citation_section_reference(
                    index=index,
                    segments=segments,
                    citation_section=citation_section,
                ):
                    continue
            elif not self._looks_like_standalone_declarative_segment(segment.text):
                continue
            candidate_segment = segment
            statement_hint = self._uscode_statement_hint(lowered)
            break
        if candidate_segment is None:
            return None

        profile = self.registry.get_profile(ModalLogicFamily.FRAME)
        if not profile.operators:
            return None
        operator = profile.operators[0]
        predicate = self._predicate_from_segment(
            candidate_segment.text,
            "__uscode_declarative_statement_fallback__",
        )
        conditions, exceptions = self._conditions_and_exceptions_from_segment(
            candidate_segment.text
        )
        return ModalIRFormula(
            formula_id=f"{resolved_document_id}:f{start_index:04d}",
            operator=ModalIROperator(
                family=profile.family.value,
                system=profile.system.value,
                symbol=operator.symbol,
                label=operator.aliases[0] if operator.aliases else operator.symbol,
            ),
            predicate=ModalIRPredicate(
                name=predicate,
                arguments=[],
                role="frame",
            ),
            provenance=ModalIRProvenance(
                source_id=resolved_document_id,
                start_char=candidate_segment.start_char,
                end_char=candidate_segment.end_char,
                citation=citation,
            ),
            conditions=conditions,
            exceptions=exceptions,
            metadata={
                "cue": "__uscode_declarative_statement_fallback__",
                "fallback_rule": "uscode_declarative_statement_v1",
                "statement_hint": statement_hint,
            },
        )

    def _uscode_section_heading_fallback_formula(
        self,
        *,
        resolved_document_id: str,
        normalized_text: str,
        citation: Optional[str],
        segments: Sequence[LegalSegment],
        start_index: int,
        allow_modal_cues: bool = False,
    ) -> Optional[ModalIRFormula]:
        """Emit frame IR for compact U.S.C. section-heading lines with no modal cues."""
        if not normalized_text.strip():
            return None
        if not self._is_uscode_citation(citation):
            return None
        if not allow_modal_cues and self._parse_eligible_cues(
            normalized_text,
            citation=citation,
        ):
            return None

        citation_section = self._citation_section_token(citation)
        if not citation_section:
            return None

        candidate_segment: Optional[LegalSegment] = None
        fallback_rule_override: Optional[str] = None
        long_heading_segment: Optional[LegalSegment] = None
        for segment in segments:
            if not self._starts_with_citation_section_reference(
                segment.text,
                citation_section,
            ):
                continue
            token_count = len(_TOKEN_RE.findall(segment.text))
            if token_count <= _USCODE_SECTION_HEADING_SHORT_MAX_TOKENS:
                candidate_segment = segment
                break
            if (
                long_heading_segment is None
                and token_count <= _USCODE_SECTION_HEADING_EXTENDED_MAX_TOKENS
            ):
                long_heading_segment = segment
        if candidate_segment is None:
            candidate_segment = long_heading_segment
        if candidate_segment is None:
            embedded_heading_segment: Optional[LegalSegment] = None
            for segment in segments:
                if not self._contains_citation_section_reference(
                    segment.text,
                    citation_section,
                ):
                    continue
                token_count = len(_TOKEN_RE.findall(segment.text))
                if token_count <= _USCODE_SECTION_HEADING_SHORT_MAX_TOKENS:
                    candidate_segment = segment
                    break
                if (
                    embedded_heading_segment is None
                    and token_count <= _USCODE_SECTION_HEADING_EXTENDED_MAX_TOKENS
                ):
                    embedded_heading_segment = segment
            if candidate_segment is None:
                candidate_segment = embedded_heading_segment
        if candidate_segment is None:
            for segment in segments:
                if self._looks_like_heading_without_section_reference(segment.text):
                    candidate_segment = segment
                    break
        if candidate_segment is None:
            candidate_segment = self._embedded_citation_heading_segment(
                normalized_text=normalized_text,
                citation_section=citation_section,
            )
        if candidate_segment is None:
            candidate_segment = self._subsection_heading_prefix_segment(
                normalized_text=normalized_text,
                citation_section=citation_section,
            )
        if candidate_segment is None:
            candidate_segment = self._coarse_citation_heading_segment(
                normalized_text=normalized_text,
                citation_section=citation_section,
            )
            if candidate_segment is not None:
                fallback_rule_override = "uscode_section_heading_coarse_v1"
        if candidate_segment is None:
            return None
        candidate_segment = self._trim_uscode_gpo_source_boilerplate(
            candidate_segment
        )
        candidate_segment = self._expanded_uscode_leading_citation_heading_segment(
            candidate_segment=candidate_segment,
            normalized_text=normalized_text,
            citation=citation,
        )

        profile = self.registry.get_profile(ModalLogicFamily.FRAME)
        if not profile.operators:
            return None
        operator = profile.operators[0]
        predicate = self._predicate_from_segment(
            candidate_segment.text,
            "__uscode_section_heading_fallback__",
        )
        conditions, exceptions = self._conditions_and_exceptions_from_segment(
            candidate_segment.text
        )
        return ModalIRFormula(
            formula_id=f"{resolved_document_id}:f{start_index:04d}",
            operator=ModalIROperator(
                family=profile.family.value,
                system=profile.system.value,
                symbol=operator.symbol,
                label=operator.aliases[0] if operator.aliases else operator.symbol,
            ),
            predicate=ModalIRPredicate(
                name=predicate,
                arguments=[],
                role="frame",
            ),
            provenance=ModalIRProvenance(
                source_id=resolved_document_id,
                start_char=candidate_segment.start_char,
                end_char=candidate_segment.end_char,
                citation=citation,
            ),
            conditions=conditions,
            exceptions=exceptions,
            metadata={
                "cue": "__uscode_section_heading_fallback__",
                "fallback_rule": fallback_rule_override
                or (
                    "uscode_section_heading_v1"
                    if self._contains_citation_section_reference(
                        candidate_segment.text,
                        citation_section,
                    )
                    or self._starts_with_citation_section_reference(
                        candidate_segment.text,
                        citation_section,
                    )
                    else "uscode_heading_without_section_reference_v1"
                ),
            },
        )

    def _trim_uscode_gpo_source_boilerplate(
        self,
        candidate_segment: LegalSegment,
    ) -> LegalSegment:
        """Keep section headings separate from adjacent GPO source boilerplate."""
        match = _USCODE_GPO_SOURCE_BOILERPLATE_RE.search(candidate_segment.text)
        if match is None or match.start() <= 0:
            return candidate_segment
        trimmed_text = candidate_segment.text[: match.start()].rstrip(
            " \u2012\u2013\u2014\u2015-"
        )
        if not trimmed_text.strip():
            return candidate_segment
        leading_offset = len(trimmed_text) - len(trimmed_text.lstrip())
        trimmed_text = trimmed_text.strip()
        stripped_segment_start = candidate_segment.end_char - len(candidate_segment.text)
        return LegalSegment(
            text=trimmed_text,
            start_char=stripped_segment_start + leading_offset,
            end_char=stripped_segment_start + leading_offset + len(trimmed_text),
            role=candidate_segment.role,
        )

    def _expanded_uscode_leading_citation_heading_segment(
        self,
        *,
        candidate_segment: LegalSegment,
        normalized_text: str,
        citation: Optional[str],
    ) -> LegalSegment:
        """Include an adjacent leading ``N U.S.C. section:`` citation header."""
        if candidate_segment.start_char <= 0:
            return candidate_segment
        citation_section = self._citation_section_token(citation)
        if not citation_section:
            return candidate_segment
        citation_title = self._citation_title_token(citation)
        section_pattern = self._citation_section_pattern(citation_section)
        if citation_title:
            title_pattern = re.escape(citation_title)
        else:
            title_pattern = r"\d+[A-Za-z]*"
        citation_prefix_re = re.compile(
            rf"(?P<header>\b{title_pattern}\s+U\.?\s*S\.?\s*C\.?\s+"
            rf"{section_pattern}\s*[:.)-]?)\s*$",
            re.IGNORECASE,
        )
        window_start = max(0, candidate_segment.start_char - 64)
        window = normalized_text[window_start : candidate_segment.end_char]
        match = citation_prefix_re.search(window)
        if match is None:
            return candidate_segment
        expanded_start = window_start + match.start("header")
        if expanded_start >= candidate_segment.start_char:
            return candidate_segment
        expanded_text = normalized_text[expanded_start : candidate_segment.end_char].strip()
        if not expanded_text:
            return candidate_segment
        leading_offset = len(
            normalized_text[expanded_start : candidate_segment.end_char]
        ) - len(normalized_text[expanded_start : candidate_segment.end_char].lstrip())
        return LegalSegment(
            text=expanded_text,
            start_char=expanded_start + leading_offset,
            end_char=expanded_start + leading_offset + len(expanded_text),
            role=candidate_segment.role,
        )

    def _uscode_procedural_clause_fallback_formula(
        self,
        *,
        resolved_document_id: str,
        normalized_text: str,
        citation: Optional[str],
        segments: Sequence[LegalSegment],
        start_index: int,
        allow_modal_cues: bool = False,
    ) -> Optional[ModalIRFormula]:
        """Recover frame IR from short citation-bound procedural clauses with no modal cues."""
        if not normalized_text.strip():
            return None
        if not self._is_uscode_citation(citation):
            return None
        if not allow_modal_cues and self._parse_eligible_cues(
            normalized_text,
            citation=citation,
        ):
            return None

        candidate_segment: Optional[LegalSegment] = None
        procedural_keyword = ""
        for segment in segments:
            lowered = self.normalize_text(segment.text).lower()
            token_count = len(_TOKEN_RE.findall(lowered))
            if (
                token_count < _USCODE_PROCEDURAL_CLAUSE_MIN_TOKENS
                or token_count > _USCODE_PROCEDURAL_CLAUSE_MAX_TOKENS
            ):
                continue
            if (
                _USCODE_CODIFICATION_HINT_RE.search(lowered)
                or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
                or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
            ):
                continue
            keyword_matches = [
                keyword_match.group(0).lower()
                for keyword_match in _USCODE_PROCEDURAL_CLAUSE_KEYWORD_RE.finditer(lowered)
            ]
            if not keyword_matches:
                continue
            if not _USCODE_PROCEDURAL_CLAUSE_VERB_RE.search(lowered):
                continue
            candidate_segment = segment
            procedural_keyword = next(
                (
                    keyword
                    for keyword in keyword_matches
                    if keyword != "administrative"
                ),
                keyword_matches[0],
            )
            break
        if candidate_segment is None:
            return None

        profile = self.registry.get_profile(ModalLogicFamily.FRAME)
        if not profile.operators:
            return None
        operator = profile.operators[0]
        predicate = self._predicate_from_segment(
            candidate_segment.text,
            "__uscode_procedural_clause_fallback__",
        )
        conditions, exceptions = self._conditions_and_exceptions_from_segment(
            candidate_segment.text
        )
        return ModalIRFormula(
            formula_id=f"{resolved_document_id}:f{start_index:04d}",
            operator=ModalIROperator(
                family=profile.family.value,
                system=profile.system.value,
                symbol=operator.symbol,
                label=operator.aliases[0] if operator.aliases else operator.symbol,
            ),
            predicate=ModalIRPredicate(
                name=predicate,
                arguments=[],
                role="frame",
            ),
            provenance=ModalIRProvenance(
                source_id=resolved_document_id,
                start_char=candidate_segment.start_char,
                end_char=candidate_segment.end_char,
                citation=citation,
            ),
            conditions=conditions,
            exceptions=exceptions,
            metadata={
                "cue": "__uscode_procedural_clause_fallback__",
                "fallback_rule": "uscode_procedural_clause_v1",
                "procedural_keyword": procedural_keyword,
            },
        )

    def _looks_like_transferred_section_heading(
        self,
        segment_text: str,
        *,
        citation_section: str,
    ) -> bool:
        normalized = self.normalize_text(segment_text).lower()
        if "transferred" not in normalized:
            return False
        if normalized.startswith("transferred"):
            return True
        # Accept compact transferred headings that start with a section marker,
        # even when citation tokenization is noisy (e.g., OCR-spaced section ids).
        if normalized.startswith("\u00a7") and len(normalized) <= 240:
            return True
        return self._contains_citation_section_reference(
            normalized,
            citation_section,
        ) or self._starts_with_citation_section_reference(
            normalized,
            citation_section,
        )

    def _looks_like_editorial_status_heading(
        self,
        segment_text: str,
        *,
        citation_section: str,
        previous_segment_text: str = "",
    ) -> bool:
        normalized = self.normalize_text(segment_text).lower()
        if not _USCODE_EDITORIAL_STATUS_HINT_RE.search(normalized):
            return False
        if self._contains_citation_section_reference(normalized, citation_section):
            return True
        if self._starts_with_citation_section_reference(normalized, citation_section):
            return True
        if normalized.startswith("repealed") or normalized.startswith("omitted") or normalized.startswith("reserved"):
            previous = self.normalize_text(previous_segment_text).lower()
            if self._contains_citation_section_reference(previous, citation_section):
                return True
            if self._starts_with_citation_section_reference(previous, citation_section):
                return True
            if len(_TOKEN_RE.findall(normalized)) <= 6:
                return True
        if normalized.startswith("\u00a7") and len(normalized) <= 240:
            return True
        return False

    def _contains_sec_heading_reference(
        self,
        text: str,
        *,
        citation_section: str,
    ) -> bool:
        if not citation_section:
            return False
        return self._contains_citation_section_reference(
            text,
            citation_section,
        )

    def _segment_or_neighbor_has_citation_section_reference(
        self,
        *,
        index: int,
        segments: Sequence[LegalSegment],
        citation_section: str,
    ) -> bool:
        for offset in (-2, -1, 0, 1, 2):
            position = index + offset
            if position < 0 or position >= len(segments):
                continue
            segment_text = segments[position].text
            if self._contains_citation_section_reference(segment_text, citation_section):
                return True
            if self._starts_with_citation_section_reference(segment_text, citation_section):
                return True
        return False

    def _uscode_statement_hint(self, normalized_segment_text: str) -> str:
        lowered = normalized_segment_text.lower()
        if "sense of the congress" in lowered:
            return "sense_of_congress"
        if "purpose of this" in lowered:
            return "purpose_clause"
        if "there is established" in lowered or "there are established" in lowered:
            return "establishment_clause"
        return "declarative_clause"

    def _subsection_heading_prefix_segment(
        self,
        *,
        normalized_text: str,
        citation_section: str,
    ) -> Optional[LegalSegment]:
        """Extract leading heading text before a long ``(a)``-style subsection body."""
        marker = _USCODE_SUBSECTION_MARKER_RE.search(normalized_text)
        if marker is None:
            return None
        if marker.start() > _USCODE_SUBSECTION_HEADING_PREFIX_MAX_CHARS:
            return None

        heading_prefix = self.normalize_text(normalized_text[: marker.start()])
        if not heading_prefix:
            return None
        prefix_tokens = _TOKEN_RE.findall(heading_prefix.lower())
        if (
            len(prefix_tokens) < 2
            or len(prefix_tokens) > _USCODE_SUBSECTION_HEADING_PREFIX_MAX_TOKENS
        ):
            return None
        if _USCODE_HEADING_ONLY_VERB_HINT_RE.search(heading_prefix):
            return None

        if not (
            self._contains_citation_section_reference(heading_prefix, citation_section)
            or self._starts_with_citation_section_reference(
                heading_prefix,
                citation_section,
            )
        ):
            return None

        body_text = self.normalize_text(normalized_text[marker.start() :])
        body_token_count = len(_TOKEN_RE.findall(body_text.lower()))
        if body_token_count < _USCODE_SUBSECTION_HEADING_BODY_MIN_TOKENS:
            return None

        return LegalSegment(
            text=heading_prefix,
            start_char=0,
            end_char=marker.start(),
            role="clause",
        )

    def _looks_like_heading_without_section_reference(self, segment_text: str) -> bool:
        normalized = self.normalize_text(segment_text)
        if not normalized:
            return False
        lowered = normalized.lower()
        tokens = _TOKEN_RE.findall(lowered)
        token_count = len(tokens)
        if token_count < _USCODE_HEADING_ONLY_MIN_TOKENS:
            return False
        if token_count > _USCODE_HEADING_ONLY_MAX_TOKENS and not self._looks_like_extended_heading_without_section_reference(tokens):
            return False
        if _USCODE_HEADING_ONLY_VERB_HINT_RE.search(lowered):
            return False
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
        ):
            return False
        # Permit compact comma/semicolon headings (e.g., "Officers, employees, and attorneys.")
        # but continue rejecting heading-like fragments with stronger clause punctuation.
        if any(punctuation in normalized for punctuation in ":[]{}"):
            return False
        if tokens[0] in _USCODE_HEADING_ONLY_LEADING_STOPWORDS:
            if not self._looks_like_article_prefixed_heading(tokens):
                return False
        return True

    def _looks_like_punctuated_section_catchline(
        self,
        segment_text: str,
        tokens: Sequence[str],
    ) -> bool:
        """Accept compact section catchlines that use semicolon or colon separators."""
        if not tokens:
            return False
        normalized = self.normalize_text(segment_text)
        if not normalized or not any(punctuation in normalized for punctuation in (";", ":")):
            return False
        if normalized.lstrip().startswith(","):
            return False
        if tokens[0] in {"act", "acts", "ch", "pub", "section", "sections", "stat", "title"}:
            return False
        if len(tokens) > _USCODE_SECTION_CATCHLINE_MAX_TOKENS:
            return False
        lowered = normalized.lower()
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
            or _USCODE_HEADING_ONLY_VERB_HINT_RE.search(lowered)
        ):
            return False
        return True

    def _looks_like_extended_heading_without_section_reference(self, tokens: Sequence[str]) -> bool:
        """Allow longer heading-only fragments when they carry strong legal-heading noun signals."""
        token_count = len(tokens)
        if token_count <= _USCODE_HEADING_ONLY_MAX_TOKENS:
            return True
        if token_count > _USCODE_HEADING_ONLY_EXTENDED_MAX_TOKENS:
            return False
        if tokens[0] in _USCODE_HEADING_ONLY_LEADING_STOPWORDS and not self._looks_like_article_prefixed_heading(tokens):
            return False
        signal_count = len(set(tokens) & _USCODE_HEADING_ONLY_EXTENDED_NOUN_HINTS)
        return signal_count >= _USCODE_HEADING_ONLY_EXTENDED_MIN_SIGNAL_TOKENS

    def _looks_like_article_prefixed_heading(self, tokens: Sequence[str]) -> bool:
        """Allow compact article-prefixed heading lines such as `The oath of office`."""
        if not tokens or tokens[0] != _USCODE_HEADING_ONLY_ARTICLE_ALLOWED_LEAD:
            return False
        body_tokens = list(tokens[1:])
        if len(body_tokens) < 2:
            return False
        if (
            body_tokens[0] in _USCODE_HEADING_ONLY_ARTICLE_BANNED_SECOND_TOKENS
            and not self._looks_like_terms_conditions_heading(body_tokens)
        ):
            return False
        token_set = set(body_tokens)
        return bool(token_set & _USCODE_HEADING_ONLY_ARTICLE_NOUN_HINTS)

    def _looks_like_terms_conditions_heading(self, body_tokens: Sequence[str]) -> bool:
        """Allow `The terms and conditions ...` heading lines for citation-bound sections."""
        if len(body_tokens) < 3:
            return False
        return (
            body_tokens[0] == "terms"
            and body_tokens[1] == "and"
            and body_tokens[2] in {"condition", "conditions"}
        )

    def _looks_like_standalone_declarative_segment(self, segment_text: str) -> bool:
        """Accept short `There is established ...` statements even without in-text section refs."""
        normalized = self.normalize_text(segment_text)
        if not normalized:
            return False
        if not _USCODE_DECLARATIVE_STANDALONE_START_RE.search(normalized):
            return False
        token_count = len(_TOKEN_RE.findall(normalized.lower()))
        return token_count <= _USCODE_DECLARATIVE_STANDALONE_MAX_TOKENS

    def _coarse_citation_heading_segment(
        self,
        *,
        normalized_text: str,
        citation_section: str,
    ) -> Optional[LegalSegment]:
        """Recover a compact heading around a citation reference in noisy long lines."""
        if not citation_section:
            return None

        section_pattern = self._citation_section_pattern(citation_section)
        reference_pattern = re.compile(
            rf"(?<!\w){_USCODE_OPTIONAL_SECTION_REF_PREFIX_RE}{section_pattern}"
            rf"(?={_USCODE_SECTION_REF_SUFFIX_RE})",
            re.IGNORECASE,
        )
        match = reference_pattern.search(normalized_text)
        if match is None:
            return None

        start = match.start()
        window_end = min(
            len(normalized_text),
            start + _USCODE_EMBEDDED_HEADING_WINDOW_MAX_CHARS,
        )
        window = normalized_text[start:window_end]
        lowered_window = window.lower()
        cut = len(window)

        for marker in (
            " from the u.s. government publishing office",
            " editorial notes ",
            " historical and revision notes ",
            " amendments ",
        ):
            marker_index = lowered_window.find(marker)
            if marker_index != -1:
                cut = min(cut, marker_index)

        subsection_match = _USCODE_SUBSECTION_MARKER_RE.search(
            window,
            pos=max(match.end() - start, 0),
        )
        if subsection_match is not None:
            cut = min(cut, subsection_match.start())

        candidate_text = self.normalize_text(window[:cut])
        if not candidate_text:
            return None

        token_matches = list(_TOKEN_RE.finditer(candidate_text))
        token_count = len(token_matches)
        if token_count < 2:
            return None
        if token_count > _USCODE_SECTION_HEADING_EXTENDED_MAX_TOKENS:
            cutoff = token_matches[_USCODE_SECTION_HEADING_SHORT_MAX_TOKENS - 1].end()
            candidate_text = self.normalize_text(candidate_text[:cutoff])
        if _USCODE_HEADING_ONLY_VERB_HINT_RE.search(candidate_text):
            procedural_heading_keywords = {
                keyword_match.group(0).lower()
                for keyword_match in _USCODE_PROCEDURAL_CLAUSE_KEYWORD_RE.finditer(
                    candidate_text.lower()
                )
            }
            has_procedural_heading_signature = (
                len(procedural_heading_keywords) >= 2
                and bool(
                    {"appeal", "appeals", "hearing", "notice", "review"}
                    & procedural_heading_keywords
                )
            )
            if not has_procedural_heading_signature:
                return None

        return LegalSegment(
            text=candidate_text,
            start_char=start,
            end_char=start + len(candidate_text),
            role="clause",
        )


__all__ = [
    "LegalModalParser",
    "LegalSegment",
    "ModalCueSpan",
]
