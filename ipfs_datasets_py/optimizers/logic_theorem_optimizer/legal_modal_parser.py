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
_CONDITION_PREFIXES = ("provided that", "subject to", "if", "when")
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
_USCODE_SECTION_REF_PREFIX_RE = r"(?:§{1,2}\s*|\bsec(?:tion)?s?\.?\s*)"
_USCODE_OPTIONAL_SECTION_REF_PREFIX_RE = rf"(?:{_USCODE_SECTION_REF_PREFIX_RE})?"
_USCODE_CITATION_MARKER_RE = re.compile(
    r"\bU\.?\s*S\.?\s*C\.?(?!\w)",
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
        "authority",
        "benefits",
        "declaration",
        "definitions",
        "duties",
        "hearing",
        "hearings",
        "lands",
        "motion",
        "motions",
        "notice",
        "oath",
        "office",
        "offices",
        "policy",
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
        "withdrawal",
        "withdrawals",
    }
)
_USCODE_HEADING_ONLY_EXTENDED_NOUN_HINTS = frozenset(
    {
        *_USCODE_HEADING_ONLY_ARTICLE_NOUN_HINTS,
        "administrative",
        "adjudication",
        "adjudications",
        "appeal",
        "appeals",
        "certification",
        "compliance",
        "enforcement",
        "implementation",
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
_USCODE_RESIDUAL_SPAN_MIN_TOKENS = 6
_USCODE_RESIDUAL_SPAN_MAX_TOKENS = 120
_USCODE_SHORT_RESIDUAL_HEADING_MIN_TOKENS = 1
_USCODE_SHORT_RESIDUAL_HEADING_MAX_TOKENS = 5
_USCODE_SHORT_RESIDUAL_HEADING_SIGNAL_TOKENS = frozenset(
    {
        "activities",
        "activity",
        "administrative",
        "amendment",
        "amendments",
        "hearing",
        "historical",
        "notice",
        "notes",
        "provision",
        "provisions",
        "procedure",
        "procedures",
        "records",
        "review",
        "revision",
    }
)
_USCODE_LONG_RESIDUAL_HEADING_MIN_TOKENS = 6
_USCODE_LONG_RESIDUAL_HEADING_MAX_TOKENS = _USCODE_HEADING_ONLY_EXTENDED_MAX_TOKENS
_USCODE_LONG_RESIDUAL_HEADING_MIN_SIGNAL_TOKENS = 2
_USCODE_MAX_RESIDUAL_SPAN_FORMULAS = 3
_USCODE_RESIDUAL_SPAN_FORMULA_BUDGET_CAP = 7
_USCODE_RESIDUAL_COALESCE_SEGMENT_MAX_TOKENS = 12
_USCODE_RESIDUAL_HEADER_MIN_TOKENS = 10
_USCODE_RESIDUAL_HEADER_SCOPE_PHRASES = (
    "from the u.s. government publishing office",
    "u.s.c.",
    "united states code",
    "www.gpo.gov",
)
_USCODE_RESIDUAL_STATUTORY_FRAGMENT_MAX_TOKENS = 10
_USCODE_RESIDUAL_STATUTORY_FRAGMENT_HINT_RE = re.compile(
    r"\b(?:ch|chapter|pub|stat)\b",
    re.IGNORECASE,
)
_GENERIC_LEGAL_REFERENCE_HINT_RE = re.compile(
    r"\b(?:section|sections|sec|secs|chapter|subchapter|title|subsection|"
    r"paragraph|stat|statutes?|public\s+law|pub\.?\s*l\.?)\b",
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
        "article",
        "chapter",
        "clause",
        "code",
        "commissioner",
        "department",
        "director",
        "division",
        "governor",
        "law",
        "paragraph",
        "part",
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
        return segments

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
        return sorted(found, key=lambda cue: (cue.start_char, cue.end_char, cue.family.value, cue.operator.symbol))

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
        if _NON_TEMPORAL_BY_PHRASE_RE.match(trailing):
            return False
        if _TEMPORAL_BY_PHRASE_RE.match(trailing):
            return True
        if _MONTH_DAY_RE.search(trailing):
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
        if _MONTH_DAY_RE.search(trailing):
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
        cues = self.extract_cues(normalized)
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
            formulas.append(
                self._residual_span_coverage_formula(
                    document_id=document_id,
                    citation=citation,
                    segment=segment,
                    start_index=next_index,
                    operator=operator,
                    profile=profile,
                )
            )
            next_index += 1
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
        if self._has_blocking_residual_modal_cues(normalized):
            return False
        if self._is_uscode_header_residual_candidate(normalized, tokens):
            return True
        if self._is_uscode_statutory_fragment_residual_candidate(normalized, tokens):
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
        if token_count < _USCODE_RESIDUAL_HEADER_MIN_TOKENS:
            return False
        if token_count > _USCODE_RESIDUAL_SPAN_MAX_TOKENS:
            return False
        lowered = normalized_segment_text.lower()
        return any(
            phrase in lowered for phrase in _USCODE_RESIDUAL_HEADER_SCOPE_PHRASES
        )

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
        return bool(_USCODE_RESIDUAL_STATUTORY_FRAGMENT_HINT_RE.search(lowered))

    def _residual_span_coverage_formula(
        self,
        *,
        document_id: str,
        citation: Optional[str],
        segment: LegalSegment,
        start_index: int,
        operator: ModalOperatorSpec,
        profile: ModalParseProfile,
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
                "fallback_rule": (
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
        return [
            segment
            for segment in segments
            if not any(
                self._spans_overlap(
                    segment.start_char,
                    segment.end_char,
                    span_start,
                    span_end,
                )
                for span_start, span_end in spans
            )
        ]

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
        if not allow_modal_cues and self.extract_cues(normalized_text):
            return None

        candidate_segment: Optional[LegalSegment] = None
        for segment in segments:
            if _USCODE_CODIFICATION_HINT_RE.search(segment.text):
                candidate_segment = segment
                break
        if candidate_segment is None:
            return None

        lowered = candidate_segment.text.lower()
        citation_section = self._citation_section_token(citation)
        has_reclassification_hint = "reclassified" in lowered or "codification" in lowered
        has_transferred_heading_hint = self._looks_like_transferred_section_heading(
            candidate_segment.text,
            citation_section=citation_section,
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
                    "uscode_codification_transfer_heading_v1"
                    if has_reclassification_hint
                    else "uscode_transferred_heading_v1"
                ),
            },
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
        if not allow_modal_cues and self.extract_cues(normalized_text):
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
        if not allow_modal_cues and self.extract_cues(normalized_text):
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
        if not allow_modal_cues and self.extract_cues(normalized_text):
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
        if not allow_modal_cues and self.extract_cues(normalized_text):
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
