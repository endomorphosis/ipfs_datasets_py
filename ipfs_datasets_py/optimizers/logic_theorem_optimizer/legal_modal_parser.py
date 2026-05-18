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
_USCODE_EDITORIAL_STATUS_HINT_RE = re.compile(
    r"\b(?:repealed|omitted|reserved|vacant|renumbered|terminated)\b",
    re.IGNORECASE,
)
_USCODE_CITATION_SECTION_RE = re.compile(
    r"\bU\.S\.C\.\s*([0-9A-Za-z.\-]+)\b",
    re.IGNORECASE,
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

        fallback_formula = self._uscode_codification_fallback_formula(
            resolved_document_id=resolved_document_id,
            normalized_text=normalized,
            citation=citation,
            segments=segments,
            start_index=len(formulas) + 1,
        )
        if fallback_formula is None:
            fallback_formula = self._uscode_editorial_status_fallback_formula(
                resolved_document_id=resolved_document_id,
                normalized_text=normalized,
                citation=citation,
                segments=segments,
                start_index=len(formulas) + 1,
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
        return match.group(1).strip().lower()

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
        if citation_section:
            if f"\u00a7{citation_section}" in normalized:
                return True
            if f"section {citation_section}" in normalized:
                return True
        return False

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
        if f"\u00a7{citation_section}" in normalized:
            return True
        if f"section {citation_section}" in normalized:
            return True
        if normalized.startswith(f"{citation_section}."):
            return True
        if normalized.startswith(f"{citation_section} "):
            return True
        if normalized.startswith("repealed") or normalized.startswith("omitted") or normalized.startswith("reserved"):
            previous = self.normalize_text(previous_segment_text).lower()
            if f"\u00a7{citation_section}" in previous:
                return True
            if f"section {citation_section}" in previous:
                return True
            if previous.startswith(f"{citation_section}."):
                return True
            if previous.startswith(f"{citation_section} "):
                return True
            if len(_TOKEN_RE.findall(normalized)) <= 6:
                return True
        if normalized.startswith("\u00a7") and len(normalized) <= 240:
            return True
        return False


__all__ = [
    "LegalModalParser",
    "LegalSegment",
    "ModalCueSpan",
]
