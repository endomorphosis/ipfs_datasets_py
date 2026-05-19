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
_CONDITION_PREFIXES = ("provided that", "subject to", "if", "when", "before", "upon")
_EXCEPTION_PREFIXES = ("except that", "except as", "unless", "except")
_CONDITIONAL_SCOPE_PHRASES = (
    "any person who",
    "any person that",
    "any individual who",
    "any entity that",
    "whoever",
    "as provided by",
    "except as provided by",
    "in the case of",
    "in the event that",
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
    "subject only to",
    "subject, however, to",
    "subject however to",
    "subject to terms and conditions",
    "subject to such terms and conditions",
    "subject to the terms and conditions",
)
_STATUTORY_SCOPE_REFERENCE_PHRASES = (
    "as provided by",
    "as provided in",
    "in accordance with",
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
    "under paragraph",
    "under subparagraph",
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
        "pending",
        "promptly",
        "quarterly",
        "second",
        "seconds",
        "thereafter",
        "time",
        "times",
        "until",
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
        "day",
        "days",
        "deadline",
        "deadlines",
        "fiscal",
        "hour",
        "hours",
        "month",
        "months",
        "quarter",
        "quarters",
        "weekly",
        "year",
        "years",
        "yearly",
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
    "for any fiscal year",
    "for each fiscal year",
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
    "date of enactment",
    "on the date of enactment",
    "while pending",
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
_TEMPORAL_WITHIN_PHRASE_RE = re.compile(
    rf"^\s+(?:"
    rf"\d{{1,4}}\b|"
    rf"(?:a|an)\s+(?:day|days|month|months|year|years|week|weeks|hour|hours)\b|"
    rf"(?:the\s+)?(?:end|close|beginning|start|deadline|expiration)\b|"
    rf"(?:next|following)\b|"
    rf"{_MONTH_NAME_DATE_PATTERN}\s+\d{{1,2}}(?:,\s*|\s+)\d{{4}}\b"
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
_GENERIC_FRAME_CUE_TERMS = frozenset(
    {
        "administered by",
        "authority",
        "is a",
        "jurisdiction",
        "part of",
    }
)
_GENERIC_FRAME_DEBIASED_LOGIT_BASE = 0.5
_GENERIC_FRAME_CUE_DEBIAS_FACTOR = 0.2
_GENERIC_FRAME_STRUCTURAL_BONUS_DEBIAS_FACTOR = 0.25
_GENERIC_FRAME_PRESENT_CUE_SCOPE_BONUS_FACTOR = 0.35
_GENERIC_FRAME_NORMATIVE_SCOPE_SOFT_CAP = 1.0
_DEONTIC_COMPETING_SCOPE_SOFT_CAP = 3.0
_DEONTIC_STRONG_COMPETING_SCOPE_SOFT_CAP = 2.5
_TEMPORAL_COMPETING_SCOPE_SOFT_CAP = 3.0
_TEMPORAL_STRONG_COMPETING_SCOPE_SOFT_CAP = 2.5
_CONDITIONAL_COMPETING_SCOPE_SOFT_CAP = 3.0
_FRAME_COMPETING_SCOPE_SOFT_CAP = 3.0
_FRAME_STRONG_COMPETING_SCOPE_SOFT_CAP = 2.5
_ALETHIC_COMPETING_SCOPE_SOFT_CAP = 2.0
_GENERIC_FRAME_SCOPE_BACKFILL_WEIGHT = 0.12
_GENERIC_FRAME_STRONG_TEMPORAL_SCOPE_BACKFILL_WEIGHT = 0.35
_COMPETING_SCOPE_BACKFILL_WEIGHT = 0.12
_STRONG_SCOPE_BACKFILL_WEIGHT = 0.26
_DEONTIC_CONDITIONAL_SCOPE_BACKFILL_TRIGGER = 3.0
_TEMPORAL_DEONTIC_SCOPE_BACKFILL_TRIGGER = 3.0
_CONDITIONAL_DEONTIC_SCOPE_BACKFILL_TRIGGER = 2.0
_CONDITIONAL_TEMPORAL_SCOPE_BACKFILL_TRIGGER = 2.0
_CONDITIONAL_DYNAMIC_SCOPE_BACKFILL_TRIGGER = 2.0
_DEONTIC_TEMPORAL_SCOPE_BACKFILL_TRIGGER = 2.5
_DEONTIC_EPISTEMIC_SCOPE_BACKFILL_TRIGGER = 2.0
_DEONTIC_DYNAMIC_SCOPE_BACKFILL_TRIGGER = 2.5
_CONDITIONAL_FRAME_SCOPE_BACKFILL_TRIGGER = 2.0
_FRAME_DEONTIC_SCOPE_BACKFILL_TRIGGER = 0.35
_FRAME_TEMPORAL_SCOPE_BACKFILL_TRIGGER = 0.35
_FRAME_CONDITIONAL_SCOPE_BACKFILL_TRIGGER = 0.35
_FRAME_EPISTEMIC_SCOPE_BACKFILL_TRIGGER = 0.5
_FRAME_ALETHIC_SCOPE_BACKFILL_TRIGGER = 0.5
_FRAME_DYNAMIC_SCOPE_BACKFILL_TRIGGER = 0.5
_ALETHIC_CONDITIONAL_SCOPE_BACKFILL_TRIGGER = 0.5
_ALETHIC_EPISTEMIC_SCOPE_BACKFILL_TRIGGER = 0.5
_ALETHIC_DEONTIC_SCOPE_BACKFILL_TRIGGER = 0.5
_EPISTEMIC_TEMPORAL_SCOPE_BACKFILL_TRIGGER = 0.5
_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_TRIGGER = 0.2
_TEMPORAL_CONDITIONAL_SCOPE_BACKFILL_TRIGGER = 3.0
_TEMPORAL_FRAME_SCOPE_BACKFILL_TRIGGER = 3.0
_TEMPORAL_EPISTEMIC_SCOPE_BACKFILL_TRIGGER = 3.0
_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT = 0.35
_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT = 0.18
_STATUTORY_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT = 0.35
_STATUTORY_FRAME_DEONTIC_SCOPE_BACKFILL_WEIGHT = 0.45
_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO = 0.9
_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_MAX = 0.62
_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX = 0.62
_STATUTORY_GENERIC_FRAME_EPISTEMIC_SCOPE_MAX = 0.45
_STATUTORY_GENERIC_FRAME_STRONG_TEMPORAL_SCOPE_MAX = 0.72
_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO = 0.2
_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX = 0.45
_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO = 0.2
_DEONTIC_COMPETING_SCOPE_BACKFILL_MAX = 0.35
_DYNAMIC_COMPETING_SCOPE_BACKFILL_RATIO = 0.2
_DYNAMIC_COMPETING_SCOPE_BACKFILL_MAX = 0.45
_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX = 0.55
_FRAME_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_WEIGHT = 0.45
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
_DEONTIC_SCOPE_PHRASES = (
    "it is the policy of",
    "it shall be the policy of",
    "is guilty of",
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
    "shall be fined",
    "shall be imprisoned",
    "is prohibited from",
    "is required to",
    "subject to a civil penalty",
    "subject to civil penalties",
    "subject to criminal penalties",
    "subject to imprisonment",
    "under an obligation to",
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
                        if profile.family == ModalLogicFamily.TEMPORAL:
                            lowered_cue = cue.lower()
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
        if _TEMPORAL_BY_PHRASE_RE.match(trailing):
            return True
        if _CALENDAR_DATE_RE.search(trailing):
            return True
        lookahead: List[SpaCyTokenFeature] = []
        for token in tokens:
            if token.start_char >= end_char:
                lookahead.append(token)
                if len(lookahead) >= 4:
                    break
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
        lookahead: List[SpaCyTokenFeature] = []
        for token in tokens:
            if token.end_char <= start_char:
                preceding = token
                continue
            if token.start_char >= end_char:
                lookahead.append(token)
                if len(lookahead) >= 3:
                    break
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
        if not formulas and encoding.normalized_text:
            fallback_formula = self._fallback_parser.fallback_formula(
                document_id=encoding.document_id,
                text=encoding.normalized_text,
                citation=encoding.citation,
                start_index=1,
            )
            if fallback_formula is not None:
                formulas.append(fallback_formula)
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
    if not counts:
        return {}
    resolved_signals: Mapping[str, bool]
    if signals is None:
        resolved_signals = modal_ambiguity_signals(encoding)
    else:
        resolved_signals = signals
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
    if has_generic_frame_debias_context:
        _apply_generic_frame_statutory_competing_scope_backfill(
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
    if not (
        has_deontic_competition
        or has_conditional_competition
        or has_dynamic_competition
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
    temporal_soft_cap = _TEMPORAL_COMPETING_SCOPE_SOFT_CAP
    if has_strong_deontic_competition or has_strong_conditional_competition:
        temporal_soft_cap = min(
            temporal_soft_cap,
            _TEMPORAL_STRONG_COMPETING_SCOPE_SOFT_CAP,
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
    if not (
        has_deontic_competition
        or has_temporal_competition
        or has_frame_competition
    ):
        return
    overflow = conditional_count - _CONDITIONAL_COMPETING_SCOPE_SOFT_CAP
    counts[conditional_family] = (
        _CONDITIONAL_COMPETING_SCOPE_SOFT_CAP + math.log1p(overflow)
    )


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
    if not (
        has_strong_temporal_competition
        or has_strong_conditional_competition
        or has_alethic_competition
        or has_strong_deontic_competition
        or has_strong_epistemic_competition
    ):
        return
    frame_soft_cap = _FRAME_COMPETING_SCOPE_SOFT_CAP
    if (
        has_strong_temporal_competition
        or has_strong_conditional_competition
        or has_strong_deontic_competition
        or has_strong_epistemic_competition
    ):
        frame_soft_cap = min(
            frame_soft_cap,
            _FRAME_STRONG_COMPETING_SCOPE_SOFT_CAP,
        )
    if frame_count <= frame_soft_cap:
        return
    overflow = frame_count - frame_soft_cap
    counts[frame_family] = frame_soft_cap + math.log1p(overflow)


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
        counts[ModalLogicFamily.DEONTIC.value] = max(
            float(counts.get(ModalLogicFamily.DEONTIC.value, 0.0)),
            base_floor,
        )
    if bool(signals.get("has_condition_or_exception_scope")):
        conditional_floor = _scaled_competing_scope_backfill(
            source_count=frame_count,
            ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
            minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
            maximum=_STATUTORY_GENERIC_FRAME_CONDITIONAL_SCOPE_MAX,
        )
        counts[ModalLogicFamily.CONDITIONAL_NORMATIVE.value] = max(
            float(counts.get(ModalLogicFamily.CONDITIONAL_NORMATIVE.value, 0.0)),
            conditional_floor,
        )
    if bool(signals.get("has_temporal_scope")):
        temporal_maximum = _STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_MAX
        if (
            bool(signals.get("has_calendar_date_scope"))
            or bool(signals.get("has_temporal_scope_phrase"))
            or bool(signals.get("has_temporal_within_scope"))
        ):
            temporal_maximum = _STATUTORY_GENERIC_FRAME_STRONG_TEMPORAL_SCOPE_MAX
        temporal_floor = _scaled_competing_scope_backfill(
            source_count=frame_count,
            ratio=_STATUTORY_GENERIC_FRAME_COMPETING_SCOPE_RATIO,
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
    epistemic_family = ModalLogicFamily.EPISTEMIC.value
    alethic_family = ModalLogicFamily.ALETHIC.value
    deontic_count = float(counts.get(deontic_family, 0.0))
    conditional_count = float(counts.get(conditional_family, 0.0))
    temporal_count = float(counts.get(temporal_family, 0.0))
    frame_count = float(counts.get(frame_family, 0.0))
    dynamic_count = float(counts.get(dynamic_family, 0.0))
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
    )
    has_strong_conditional_scope = (
        bool(signals.get("has_exception_clause"))
        or bool(signals.get("has_conditional_scope_phrase"))
        or bool(signals.get("has_conditional_scope_token"))
        or bool(signals.get("has_statutory_scope_reference"))
    )
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
            or frame_count > _COMPETING_SCOPE_BACKFILL_WEIGHT
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
        and deontic_count <= 0.0
        and bool(signals.get("has_deontic_scope"))
    ):
        deontic_backfill = _COMPETING_SCOPE_BACKFILL_WEIGHT
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
        and temporal_count <= 0.0
        and bool(signals.get("has_temporal_scope"))
    ):
        counts[temporal_family] = max(
            float(counts.get(temporal_family, 0.0)),
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
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
        deontic_backfill = _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT
        if (
            bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_deontic_scope_phrase"))
            or bool(signals.get("has_deontic_cue"))
        ):
            deontic_backfill = max(
                deontic_backfill,
                _scaled_competing_scope_backfill(
                    source_count=frame_count,
                    ratio=_DEONTIC_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
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
    if (
        frame_count >= _FRAME_TEMPORAL_SCOPE_BACKFILL_TRIGGER
        and temporal_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_temporal_scope"))
    ):
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
            temporal_backfill = max(
                temporal_backfill,
                _scaled_competing_scope_backfill(
                    source_count=frame_count,
                    ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
                    minimum=_FRAME_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_WEIGHT,
                    maximum=_STRONG_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
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
    if (
        frame_count >= _FRAME_CONDITIONAL_SCOPE_BACKFILL_TRIGGER
        and conditional_count <= _COMPETING_SCOPE_BACKFILL_WEIGHT
        and bool(signals.get("has_condition_or_exception_scope"))
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
            _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
    elif (
        has_moderate_frame_competition
        and conditional_count <= 0.0
        and bool(signals.get("has_condition_or_exception_scope"))
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
        and dynamic_count <= 0.0
        and bool(
            signals.get("has_dynamic_scope")
            or signals.get("has_dynamic_cue")
        )
    ):
        counts[dynamic_family] = max(
            float(counts.get(dynamic_family, 0.0)),
            _FRAME_COMPETING_SCOPE_BACKFILL_WEIGHT,
        )
    if (
        temporal_count >= _TEMPORAL_DEONTIC_SCOPE_BACKFILL_TRIGGER
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
        deontic_backfill = max(
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
            _scaled_competing_scope_backfill(
                source_count=temporal_count,
                ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_DEONTIC_COMPETING_SCOPE_BACKFILL_MAX,
            ),
        )
        if bool(
            signals.get("has_deontic_scope_phrase")
            or signals.get("has_deontic_cue")
        ):
            deontic_backfill = max(
                deontic_backfill,
                _STRONG_SCOPE_BACKFILL_WEIGHT,
            )
        counts[deontic_family] = max(
            float(counts.get(deontic_family, 0.0)),
            deontic_backfill,
        )
    if (
        temporal_count >= _TEMPORAL_CONDITIONAL_SCOPE_BACKFILL_TRIGGER
        and conditional_count <= 0.0
        and bool(signals.get("has_condition_or_exception_scope"))
        and (
            bool(signals.get("has_statutory_scope_reference"))
            or bool(signals.get("has_condition_clause"))
            or bool(signals.get("has_exception_clause"))
            or bool(signals.get("has_conditional_scope_phrase"))
            or bool(signals.get("has_conditional_scope_token"))
        )
    ):
        conditional_backfill = max(
            _COMPETING_SCOPE_BACKFILL_WEIGHT,
            _scaled_competing_scope_backfill(
                source_count=temporal_count,
                ratio=_TEMPORAL_COMPETING_SCOPE_BACKFILL_RATIO,
                minimum=_FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
                maximum=_TEMPORAL_COMPETING_SCOPE_BACKFILL_MAX,
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
        temporal_count >= _TEMPORAL_FRAME_SCOPE_BACKFILL_TRIGGER
        and frame_count <= 0.0
        and (
            bool(signals.get("has_frame_context"))
            or bool(signals.get("has_frame_scope_phrase"))
            or bool(signals.get("has_frame_editorial_scope_phrase"))
            or bool(signals.get("has_statutory_scope_reference"))
        )
    ):
        frame_backfill = _COMPETING_SCOPE_BACKFILL_WEIGHT
        if (
            bool(signals.get("has_frame_scope_phrase"))
            or bool(signals.get("has_frame_editorial_scope_phrase"))
            or bool(signals.get("has_statutory_scope_reference"))
        ):
            frame_backfill = max(
                frame_backfill,
                _FRAME_MODERATE_COMPETING_SCOPE_BACKFILL_WEIGHT,
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


def _is_generic_frame_cue_debias_context(
    encoding: SpaCyLegalEncoding,
    signals: Mapping[str, bool],
) -> bool:
    has_competing_non_frame_scope = (
        bool(signals.get("has_deontic_scope"))
        or bool(signals.get("has_temporal_scope"))
        or bool(signals.get("has_condition_or_exception_scope"))
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
        or bool(signals.get("has_condition_or_exception_scope"))
        or bool(signals.get("has_conditional_scope_phrase"))
        or bool(signals.get("has_conditional_scope_token"))
        or bool(signals.get("has_temporal_scope_phrase"))
        or bool(signals.get("has_temporal_within_scope"))
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
        return False
    return all(cue in _GENERIC_FRAME_CUE_TERMS for cue in frame_cues)


def _has_explicit_conditional_scope(signals: Mapping[str, bool]) -> bool:
    """Return whether conditional scope is explicit beyond bare statutory references."""
    return bool(
        signals.get("has_condition_clause")
        or signals.get("has_exception_clause")
        or signals.get("has_conditional_scope_phrase")
        or signals.get("has_conditional_scope_token")
    )


def _scope_signal_family_logit_boosts(signals: Mapping[str, bool]) -> Dict[str, float]:
    """Return deterministic logit boosts for scope-signaled families without cues."""
    boosts: Dict[str, float] = {}
    explicit_conditional_scope = _has_explicit_conditional_scope(signals)
    has_statutory_frame_context = bool(
        signals.get("has_statutory_scope_reference")
        and (
            signals.get("has_frame_context")
            or signals.get("has_frame_cue")
        )
    )
    if bool(signals.get("has_condition_or_exception_scope")):
        conditional_bonus = 0.9
        if explicit_conditional_scope:
            conditional_bonus += 0.15
        if has_statutory_frame_context:
            conditional_bonus += 0.35
        if (
            (bool(signals.get("has_deontic_scope")) or bool(signals.get("has_deontic_cue")))
            and (
                explicit_conditional_scope
                or bool(signals.get("has_statutory_scope_reference"))
            )
        ):
            conditional_bonus += 0.2
        boosts[ModalLogicFamily.CONDITIONAL_NORMATIVE.value] = conditional_bonus
    if bool(signals.get("has_deontic_scope")):
        deontic_bonus = 0.8
        if bool(signals.get("has_deontic_scope_phrase")):
            deontic_bonus += 0.2
        if has_statutory_frame_context:
            deontic_bonus += 0.4
        if bool(signals.get("has_temporal_scope")):
            deontic_bonus += 0.25
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
        boosts[ModalLogicFamily.DEONTIC.value] = deontic_bonus
    temporal_bonus = 0.0
    has_strong_temporal_scope = bool(
        signals.get("has_calendar_date_scope")
        or signals.get("has_temporal_scope_phrase")
        or signals.get("has_temporal_within_scope")
    )
    if bool(signals.get("has_temporal_scope")):
        temporal_bonus += 1.2
        if bool(signals.get("has_deontic_scope")) or bool(signals.get("has_deontic_cue")):
            temporal_bonus += 0.2
            if has_strong_temporal_scope:
                temporal_bonus += 0.15
                if bool(signals.get("has_deontic_cue")) and not bool(
                    signals.get("has_deontic_scope_phrase")
                ):
                    temporal_bonus += 0.15
    if has_strong_temporal_scope:
        temporal_bonus += 0.3
    if temporal_bonus > 0.0:
        boosts[ModalLogicFamily.TEMPORAL.value] = temporal_bonus
    if bool(signals.get("has_epistemic_scope")):
        epistemic_bonus = (
            0.7
            if bool(signals.get("has_epistemic_scope_phrase"))
            else 0.45
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
    epistemic_scope_phrase = _contains_scope_phrase(
        normalized_text, _EPISTEMIC_SCOPE_PHRASES
    )
    temporal_scope_phrase = _contains_scope_phrase(
        normalized_text, _TEMPORAL_SCOPE_PHRASES
    )
    dynamic_scope_phrase = _contains_scope_phrase(
        normalized_text, _DYNAMIC_SCOPE_PHRASES
    )
    calendar_date_scope = bool(_CALENDAR_DATE_RE.search(normalized_text))
    temporal_within_scope = _has_temporal_within_scope(
        encoding.normalized_text,
        encoding.tokens,
    )
    temporal_scope_token = bool(
        token_terms & _TEMPORAL_STRONG_SCOPE_TOKENS
    )
    alethic_scope = (
        bool(token_terms & _ALETHIC_SCOPE_TOKENS)
        or bool(alethic_scope_phrase)
    )
    temporal_scope = (
        bool(token_terms & (_TEMPORAL_SCOPE_TOKENS - {"within"}))
        or temporal_within_scope
        or temporal_scope_token
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
    dynamic_scope = (
        bool(token_terms & _DYNAMIC_SCOPE_TOKENS)
        or bool(dynamic_scope_phrase)
        or ModalLogicFamily.DYNAMIC.value in cue_families
    )
    frame_scope_phrase = _contains_scope_phrase(
        normalized_text, _FRAME_SCOPE_PHRASES
    )
    frame_editorial_scope_phrase = _contains_scope_phrase(
        normalized_text, _FRAME_EDITORIAL_SCOPE_PHRASES
    )
    frame_context = (
        bool(token_terms & _FRAME_CONTEXT_TOKENS)
        or bool(frame_scope_phrase)
        or bool(frame_editorial_scope_phrase)
    )
    return {
        "has_alethic_cue": ModalLogicFamily.ALETHIC.value in cue_families,
        "has_alethic_scope": alethic_scope or ModalLogicFamily.ALETHIC.value in cue_families,
        "has_alethic_scope_phrase": bool(alethic_scope_phrase),
        "has_condition_clause": condition_clauses,
        "has_conditional_scope_token": conditional_scope_token,
        "has_conditional_scope_phrase": conditional_scope_phrase,
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
        "has_dynamic_cue": ModalLogicFamily.DYNAMIC.value in cue_families,
        "has_dynamic_scope": dynamic_scope,
        "has_dynamic_scope_phrase": bool(dynamic_scope_phrase),
        "has_epistemic_cue": ModalLogicFamily.EPISTEMIC.value in cue_families,
        "has_epistemic_scope": epistemic_scope,
        "has_epistemic_scope_phrase": bool(epistemic_scope_phrase),
        "has_temporal_scope": temporal_scope or ModalLogicFamily.TEMPORAL.value in cue_families,
        "has_temporal_scope_phrase": bool(temporal_scope_phrase),
        "has_temporal_scope_token": temporal_scope_token,
        "has_temporal_within_scope": temporal_within_scope,
        "has_frame_context": frame_context,
        "has_frame_editorial_scope_phrase": bool(frame_editorial_scope_phrase),
        "has_frame_scope_phrase": bool(frame_scope_phrase),
        "has_frame_cue": ModalLogicFamily.FRAME.value in cue_families,
    }


def _frame_logit_bonus(signals: Mapping[str, bool]) -> float:
    """Return deterministic frame-family logit bonus from structural signals."""
    explicit_conditional_scope = _has_explicit_conditional_scope(signals)
    has_editorial_or_direct_frame_signal = bool(
        signals.get("has_frame_scope_phrase")
        or signals.get("has_frame_editorial_scope_phrase")
        or signals.get("has_frame_cue")
    )
    has_non_frame_scope_competition = bool(
        signals.get("has_deontic_scope")
        or signals.get("has_deontic_cue")
        or signals.get("has_temporal_scope")
        or signals.get("has_temporal_scope_phrase")
        or signals.get("has_temporal_within_scope")
        or explicit_conditional_scope
    )
    bonus = 0.0
    if bool(signals.get("has_frame_context")):
        frame_context_bonus = 0.6
        if (
            not has_editorial_or_direct_frame_signal
            and has_non_frame_scope_competition
        ):
            frame_context_bonus = 0.35
        bonus += frame_context_bonus
    if bool(signals.get("has_statutory_scope_reference")):
        statutory_bonus = 0.8
        if (
            not has_editorial_or_direct_frame_signal
            and (
                explicit_conditional_scope
                or bool(signals.get("has_deontic_scope"))
                or bool(signals.get("has_temporal_scope"))
            )
        ):
            statutory_bonus = 0.35
        bonus += statutory_bonus
    if bool(signals.get("has_frame_scope_phrase")):
        bonus += 1.2
    if bool(signals.get("has_frame_editorial_scope_phrase")):
        bonus += 2.2
    if bool(signals.get("has_frame_cue")):
        bonus += 2.5
    return bonus


def _debias_frame_bonus_for_generic_cues(signals: Mapping[str, bool]) -> float:
    """Retain discounted structural frame context while removing generic cue dominance."""
    structural_bonus = 0.0
    if bool(signals.get("has_frame_context")):
        structural_bonus += 0.6
    if bool(signals.get("has_statutory_scope_reference")):
        structural_bonus += 0.8
    if bool(signals.get("has_frame_scope_phrase")):
        structural_bonus += 1.2
    if bool(signals.get("has_frame_editorial_scope_phrase")):
        structural_bonus += 2.2
    if structural_bonus <= 0.0:
        return 0.0
    return structural_bonus * _GENERIC_FRAME_STRUCTURAL_BONUS_DEBIAS_FACTOR


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
