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
    "in the case of",
    "in the event that",
    "notwithstanding",
    "for purposes of",
    "for the purposes of",
    "with respect to",
    "to the extent provided",
    "except to the extent",
    "except as otherwise provided",
)
_STATUTORY_SCOPE_REFERENCE_PHRASES = (
    "as provided in",
    "in accordance with",
    "pursuant to",
    "under section",
    "under this chapter",
    "under this section",
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
        "calendar",
        "before",
        "daily",
        "day",
        "deadline",
        "effective",
        "fiscal",
        "immediately",
        "later",
        "month",
        "monthly",
        "promptly",
        "quarterly",
        "thereafter",
        "until",
        "week",
        "weekly",
        "within",
        "year",
        "yearly",
    }
)
_TEMPORAL_SCOPE_PHRASES = (
    "as soon as practicable",
    "calendar year",
    "effective date",
    "effective on",
    "for any fiscal year",
    "for each fiscal year",
    "for that fiscal year",
    "for the period beginning",
    "fiscal year",
    "no earlier than",
    "no later than",
    "not earlier than",
    "not later than",
    "period beginning on",
    "period ending on",
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
_CALENDAR_DATE_RE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+\d{1,2}(?:,\s*|\s+)\d{4}\b",
    re.IGNORECASE,
)
_FRAME_CONTEXT_TOKENS = frozenset(
    {
        "administrator",
        "agency",
        "attorney",
        "authority",
        "board",
        "bureau",
        "commission",
        "court",
        "department",
        "director",
        "intelligence",
        "judge",
        "jurisdiction",
        "justice",
        "officer",
        "omitted",
        "reclassified",
        "repealed",
        "renumbered",
        "reserved",
        "secretary",
        "terminated",
        "transferred",
        "vacant",
    }
)
_FRAME_SCOPE_PHRASES = (
    "editorially reclassified",
    "renumbered",
    "repealed",
    "reserved",
    "transferred",
)
_DEONTIC_SCOPE_TOKENS = frozenset(
    {
        "duty",
        "duties",
        "liabilities",
        "liable",
        "liability",
        "mandatory",
        "obligation",
        "obligations",
        "prohibition",
        "prohibitions",
        "prohibited",
        "requirement",
        "requirements",
        "unlawful",
    }
)
_DEONTIC_SCOPE_PHRASES = (
    "has a duty to",
    "have a duty to",
    "liability for",
    "prohibition of",
    "prohibition on",
    "requirement that",
    "requirements for",
    "is liable for",
    "is prohibited from",
    "is required to",
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
        counts = encoding.modal_family_counts()
        for family, count in counts.items():
            if family in logits:
                logits[family] = 2.0 + float(count)
        if not counts and ModalLogicFamily.HYBRID.value in logits:
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


def ranked_modal_families(encoding: SpaCyLegalEncoding) -> List[Dict[str, float]]:
    """Rank modal families by deterministic cue count and normalized share."""
    counts = encoding.modal_family_counts()
    total = sum(counts.values())
    if total <= 0:
        return []
    ranking: List[Dict[str, float]] = []
    for family, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        ranking.append(
            {
                "family": family,
                "count": int(count),
                "share": round(float(count) / float(total), 6),
            }
        )
    return ranking


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
    temporal_scope_phrase = _contains_scope_phrase(
        normalized_text, _TEMPORAL_SCOPE_PHRASES
    )
    dynamic_scope_phrase = _contains_scope_phrase(
        normalized_text, _DYNAMIC_SCOPE_PHRASES
    )
    calendar_date_scope = bool(_CALENDAR_DATE_RE.search(normalized_text))
    alethic_scope = (
        bool(token_terms & _ALETHIC_SCOPE_TOKENS)
        or bool(alethic_scope_phrase)
    )
    temporal_scope = (
        bool(token_terms & _TEMPORAL_SCOPE_TOKENS)
        or bool(temporal_scope_phrase)
        or calendar_date_scope
    )
    deontic_scope = (
        bool(token_terms & _DEONTIC_SCOPE_TOKENS)
        or bool(deontic_scope_phrase)
        or ModalLogicFamily.DEONTIC.value in cue_families
    )
    dynamic_scope = (
        bool(token_terms & _DYNAMIC_SCOPE_TOKENS)
        or bool(dynamic_scope_phrase)
        or ModalLogicFamily.DYNAMIC.value in cue_families
    )
    frame_scope_phrase = _contains_scope_phrase(
        normalized_text, _FRAME_SCOPE_PHRASES
    )
    frame_context = bool(token_terms & _FRAME_CONTEXT_TOKENS) or bool(frame_scope_phrase)
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
        "has_temporal_scope": temporal_scope or ModalLogicFamily.TEMPORAL.value in cue_families,
        "has_temporal_scope_phrase": bool(temporal_scope_phrase),
        "has_frame_context": frame_context,
        "has_frame_scope_phrase": bool(frame_scope_phrase),
        "has_frame_cue": ModalLogicFamily.FRAME.value in cue_families,
    }


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
