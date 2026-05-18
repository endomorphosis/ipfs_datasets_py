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
_USCODE_CITATION_SECTION_RE = re.compile(
    r"\bU\.S\.C\.\s*([0-9A-Za-z.\-]+)\b",
    re.IGNORECASE,
)
_USCODE_TRAILING_SECTION_PUNCT_RE = re.compile(r"[.;:]+$")
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
            formulas.append(fallback_formula)

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
        )
        if fallback_formula is not None:
            return fallback_formula
        fallback_formula = self._uscode_editorial_status_fallback_formula(
            resolved_document_id=document_id,
            normalized_text=normalized,
            citation=citation,
            segments=candidate_segments,
            start_index=start_index,
        )
        if fallback_formula is not None:
            return fallback_formula
        fallback_formula = self._uscode_declarative_statement_fallback_formula(
            resolved_document_id=document_id,
            normalized_text=normalized,
            citation=citation,
            segments=candidate_segments,
            start_index=start_index,
        )
        if fallback_formula is not None:
            return fallback_formula
        return self._uscode_section_heading_fallback_formula(
            resolved_document_id=document_id,
            normalized_text=normalized,
            citation=citation,
            segments=candidate_segments,
            start_index=start_index,
        )

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

    def _uscode_codification_fallback_formula(
        self,
        *,
        resolved_document_id: str,
        normalized_text: str,
        citation: Optional[str],
        segments: Sequence[LegalSegment],
        start_index: int,
    ) -> Optional[ModalIRFormula]:
        if not normalized_text.strip():
            return None
        if citation is None or "u.s.c." not in citation.lower():
            return None
        if self.extract_cues(normalized_text):
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
        return _USCODE_TRAILING_SECTION_PUNCT_RE.sub("", token)

    def _contains_citation_section_reference(self, text: str, citation_section: str) -> bool:
        if not citation_section:
            return False
        normalized = self.normalize_text(text).lower()
        section_pattern = re.escape(citation_section)
        if re.search(
            rf"§\s*{section_pattern}(?={_USCODE_SECTION_REF_SUFFIX_RE})",
            normalized,
        ):
            return True
        if re.search(
            rf"\bsection\s+{section_pattern}(?={_USCODE_SECTION_REF_SUFFIX_RE})",
            normalized,
        ):
            return True
        if re.search(
            rf"\bsec\.?\s*{section_pattern}(?={_USCODE_SECTION_REF_SUFFIX_RE})",
            normalized,
        ):
            return True
        return False

    def _starts_with_citation_section_reference(self, text: str, citation_section: str) -> bool:
        if not citation_section:
            return False
        normalized = self.normalize_text(text).lower()
        section_pattern = re.escape(citation_section)
        return bool(
            re.match(
                rf"^(?:§\s*|sec\.?\s*|section\s+)?{section_pattern}"
                rf"(?={_USCODE_SECTION_REF_SUFFIX_RE})",
                normalized,
            )
        )

    def _uscode_editorial_status_fallback_formula(
        self,
        *,
        resolved_document_id: str,
        normalized_text: str,
        citation: Optional[str],
        segments: Sequence[LegalSegment],
        start_index: int,
    ) -> Optional[ModalIRFormula]:
        if not normalized_text.strip():
            return None
        if citation is None or "u.s.c." not in citation.lower():
            return None
        if self.extract_cues(normalized_text):
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
    ) -> Optional[ModalIRFormula]:
        if not normalized_text.strip():
            return None
        if citation is None or "u.s.c." not in citation.lower():
            return None
        if self.extract_cues(normalized_text):
            return None

        citation_section = self._citation_section_token(citation)
        if not citation_section:
            return None
        if not self._contains_sec_heading_reference(
            normalized_text,
            citation_section=citation_section,
        ):
            return None

        candidate_segment: Optional[LegalSegment] = None
        statement_hint = ""
        for index, segment in enumerate(segments):
            lowered = self.normalize_text(segment.text).lower()
            if not _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered):
                continue
            if not self._segment_or_neighbor_has_citation_section_reference(
                index=index,
                segments=segments,
                citation_section=citation_section,
            ):
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
    ) -> Optional[ModalIRFormula]:
        """Emit frame IR for compact U.S.C. section-heading lines with no modal cues."""
        if not normalized_text.strip():
            return None
        if citation is None or "u.s.c." not in citation.lower():
            return None
        if self.extract_cues(normalized_text):
            return None

        citation_section = self._citation_section_token(citation)
        if not citation_section:
            return None

        candidate_segment: Optional[LegalSegment] = None
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
            candidate_segment = self._subsection_heading_prefix_segment(
                normalized_text=normalized_text,
                citation_section=citation_section,
            )
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
                "fallback_rule": (
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
        if len(tokens) < 2 or len(tokens) > _USCODE_HEADING_ONLY_MAX_TOKENS:
            return False
        if _USCODE_HEADING_ONLY_VERB_HINT_RE.search(lowered):
            return False
        if (
            _USCODE_CODIFICATION_HINT_RE.search(lowered)
            or _USCODE_EDITORIAL_STATUS_HINT_RE.search(lowered)
            or _USCODE_DECLARATIVE_STATEMENT_HINT_RE.search(lowered)
        ):
            return False
        if any(punctuation in normalized for punctuation in ",:;()[]{}"):
            return False
        if tokens[0] in _USCODE_HEADING_ONLY_LEADING_STOPWORDS:
            return False
        return True


__all__ = [
    "LegalModalParser",
    "LegalSegment",
    "ModalCueSpan",
]
