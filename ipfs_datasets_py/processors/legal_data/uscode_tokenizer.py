"""Versioned legal BM25 tokenizer for U.S. Code sparse retrieval (USCIR-013).

This module owns the sealed, locale-independent token stream used by the
``publicus-ir-graphrag/v2`` legal BM25 index. It deliberately does **not**
build postings, field weights, or term-range shards (those are USCIR-014 /
USCIR-015).

Design invariants
-----------------
* Tokenization is deterministic and locale-independent: NFKC + Unicode dash
  folding + ``str.casefold()`` only — never ``locale`` or platform collation.
* Legally meaningful tokens survive as single terms: U.S.C. / C.F.R.
  citations, bare section symbols (``§ 552``), section abbreviations, and
  numeric section identifiers.
* Every emitted token carries half-open character offsets into the
  **normalized** source so score explanations can highlight surface spans.
* Stopword policy is explicit and versioned; stopwords are never applied to
  citation / section-symbol / number tokens.
* Output is bounded by ``max_token_chars`` and ``max_tokens`` so adversarial
  or malformed input cannot explode the inverted index.
* Tokenizer identity is pinned as ``uscode-bm25-tokenizer/v1`` and recorded
  on release manifests.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final, Mapping, Sequence, Union

# ---------------------------------------------------------------------------
# Schema / identity pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uscode-tokenizer-v1"
FIXTURE_SCHEMA_VERSION: Final = "uscode-tokenization-v1"
TASK_ID: Final = "USCIR-013"
GOAL_ID: Final = "USCIR-G040"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"

# Pinned identity recorded on release manifests (uscode_release_schema).
TOKENIZER_ID: Final = "uscode-bm25-tokenizer/v1"
TOKENIZER_VERSION: Final = "v1"
STOPWORD_POLICY_ID: Final = "uscode-legal-stopwords/v1"

# Bounds (fail closed on overflow; never silently explode).
DEFAULT_MAX_TOKEN_CHARS: Final = 128
DEFAULT_MAX_TOKENS: Final = 100_000
MIN_MAX_TOKEN_CHARS: Final = 8
MAX_MAX_TOKEN_CHARS: Final = 1024
MIN_MAX_TOKENS: Final = 1
MAX_MAX_TOKENS: Final = 1_000_000

# Dash / minus characters folded to ASCII hyphen-minus (locale-independent).
_UNICODE_DASH_CHARS: Final = (
    "\u2010",  # hyphen
    "\u2011",  # non-breaking hyphen
    "\u2012",  # figure dash
    "\u2013",  # en dash
    "\u2014",  # em dash
    "\u2015",  # horizontal bar
    "\u2212",  # minus sign
    "\ufe58",  # small em dash
    "\ufe63",  # small hyphen-minus
    "\uff0d",  # fullwidth hyphen-minus
)
_DASH_TRANSLATION: Final = str.maketrans({ch: "-" for ch in _UNICODE_DASH_CHARS})

# Control characters other than TAB/LF/CR are stripped during normalization.
_CONTROL_RE: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE: Final = re.compile(r"[ \t\f\v]+")

# ---------------------------------------------------------------------------
# Protected legal patterns (highest priority first; longest matches preferred)
# ---------------------------------------------------------------------------

# 5 U.S.C. § 552 / 5 USC 552 / 35 U.S.C. § 102(a)(1) / 17 U.S.C. §§ 106-107
_USC_CITATION_RE: Final = re.compile(
    r"(?:"
    r"\d+[a-z]?\s*"
    r"(?:u\.?\s*s\.?\s*c\.?(?:a\.?)?|usc)\s*"
    r"(?:§+|sections?|secs?\.?)?\s*"
    r"[\da-z]+(?:\([a-z0-9]+\))*(?:[.\-][\da-z]+)*(?:\([a-z0-9]+\))*"
    r"(?:\s*-\s*[\da-z]+(?:\([a-z0-9]+\))*)?"
    r")",
    re.IGNORECASE,
)

# 37 C.F.R. § 1.56 / 37 CFR 1.56
_CFR_CITATION_RE: Final = re.compile(
    r"(?:"
    r"\d+\s*"
    r"(?:c\.?\s*f\.?\s*r\.?|cfr)\s*"
    r"(?:§+|sections?|secs?\.?)?\s*"
    r"[\d]+(?:\.[\w-]+)*(?:\([a-z0-9]+\))*"
    r")",
    re.IGNORECASE,
)

# § 552 / §§ 101-103 / § 552(a)(1)
_SECTION_SYMBOL_RE: Final = re.compile(
    r"§+\s*[\da-z]+(?:\([a-z0-9]+\))*(?:[.\-][\da-z]+)*"
    r"(?:\s*-\s*[\da-z]+(?:\([a-z0-9]+\))*)?",
    re.IGNORECASE,
)

# section 552 / sec. 101 / sections 106 and 107 (single number form)
_SECTION_ABBREV_RE: Final = re.compile(
    r"\b(?:sections?|secs?\.?)\s+"
    r"[\da-z]+(?:\([a-z0-9]+\))*(?:[.\-][\da-z]+)*",
    re.IGNORECASE,
)

# Parenthetical statutory markers kept whole: (a), (1), (A), (iv)
_PAREN_MARKER_RE: Final = re.compile(r"\([0-9A-Za-z]{1,6}\)")

# Generic word / number / dotted identifier after protected spans.
_GENERIC_TOKEN_RE: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_./\-]*|[0-9]+(?:\.[0-9]+)*"
)

_PROTECTED_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("citation", _USC_CITATION_RE),
    ("citation", _CFR_CITATION_RE),
    ("section_symbol", _SECTION_SYMBOL_RE),
    ("section_ref", _SECTION_ABBREV_RE),
    ("paren_marker", _PAREN_MARKER_RE),
)

# Explicit, versioned English stopword set for legal BM25. Keep small and
# conservative: never include "section", "title", "act", "code", "law", etc.
DEFAULT_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "such",
        "than",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "this",
        "those",
        "to",
        "was",
        "were",
        "which",
        "who",
        "will",
        "with",
    }
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeTokenizerError(ValueError):
    """Base error for legal BM25 tokenizer failures."""

    code: str = "uscode_tokenizer_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class TokenizerConfigError(UscodeTokenizerError):
    """Raised when tokenizer configuration is invalid."""

    code = "tokenizer_config_error"


class TokenizerBoundError(UscodeTokenizerError):
    """Raised when input exceeds configured token/character bounds."""

    code = "tokenizer_bound_error"


class TokenizationFixtureError(UscodeTokenizerError):
    """Raised when the sealed tokenization fixture is malformed."""

    code = "tokenization_fixture_error"


# ---------------------------------------------------------------------------
# Token kinds / value types
# ---------------------------------------------------------------------------


class TokenKind(str, Enum):
    """Semantic kind of an emitted legal token."""

    CITATION = "citation"
    SECTION_SYMBOL = "section_symbol"
    SECTION_REF = "section_ref"
    PAREN_MARKER = "paren_marker"
    NUMBER = "number"
    WORD = "word"
    STOPWORD = "stopword"

    @classmethod
    def coerce(cls, value: Any) -> "TokenKind":
        if isinstance(value, TokenKind):
            return value
        text = str(value or "").strip().lower()
        for kind in cls:
            if kind.value == text:
                return kind
        raise TokenizerConfigError(f"unknown token kind: {value!r}")


# Kinds that are legally meaningful and never treated as stopwords.
_PROTECTED_KINDS: Final[frozenset[TokenKind]] = frozenset(
    {
        TokenKind.CITATION,
        TokenKind.SECTION_SYMBOL,
        TokenKind.SECTION_REF,
        TokenKind.PAREN_MARKER,
        TokenKind.NUMBER,
    }
)

_KIND_FROM_PATTERN: Final[dict[str, TokenKind]] = {
    "citation": TokenKind.CITATION,
    "section_symbol": TokenKind.SECTION_SYMBOL,
    "section_ref": TokenKind.SECTION_REF,
    "paren_marker": TokenKind.PAREN_MARKER,
}


@dataclass(frozen=True, slots=True)
class LegalToken:
    """One deterministic legal BM25 token with explainable offsets.

    Offsets are half-open ``[char_start, char_end)`` into the **normalized**
    source string returned by :func:`normalize_legal_text`. ``surface`` is the
    exact normalized substring; ``term`` is the canonical index term.
    """

    index: int
    position: int
    term: str
    surface: str
    kind: TokenKind
    char_start: int
    char_end: int
    is_stopword: bool = False
    is_indexable: bool = True

    def __post_init__(self) -> None:
        if self.char_start < 0 or self.char_end < self.char_start:
            raise UscodeTokenizerError(
                f"invalid token offsets: [{self.char_start}, {self.char_end})"
            )
        if not self.term:
            raise UscodeTokenizerError("token term must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "char_end": self.char_end,
            "char_start": self.char_start,
            "index": self.index,
            "is_indexable": self.is_indexable,
            "is_stopword": self.is_stopword,
            "kind": self.kind.value,
            "position": self.position,
            "surface": self.surface,
            "term": self.term,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LegalToken":
        return cls(
            index=int(value["index"]),
            position=int(value["position"]),
            term=str(value["term"]),
            surface=str(value["surface"]),
            kind=TokenKind.coerce(value["kind"]),
            char_start=int(value["char_start"]),
            char_end=int(value["char_end"]),
            is_stopword=bool(value.get("is_stopword", False)),
            is_indexable=bool(value.get("is_indexable", True)),
        )


@dataclass(frozen=True, slots=True)
class TokenizationResult:
    """Full token stream for one text unit."""

    tokenizer_id: str
    normalized_text: str
    tokens: tuple[LegalToken, ...]
    indexable_terms: tuple[str, ...]
    truncated: bool = False

    @property
    def token_count(self) -> int:
        return len(self.tokens)

    @property
    def indexable_count(self) -> int:
        return len(self.indexable_terms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "indexable_count": self.indexable_count,
            "indexable_terms": list(self.indexable_terms),
            "normalized_text": self.normalized_text,
            "token_count": self.token_count,
            "tokenizer_id": self.tokenizer_id,
            "tokens": [t.to_dict() for t in self.tokens],
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class TokenizerConfig:
    """Stable, versioned tokenizer configuration."""

    tokenizer_id: str = TOKENIZER_ID
    tokenizer_version: str = TOKENIZER_VERSION
    stopword_policy_id: str = STOPWORD_POLICY_ID
    max_token_chars: int = DEFAULT_MAX_TOKEN_CHARS
    max_tokens: int = DEFAULT_MAX_TOKENS
    drop_stopwords: bool = True
    stopwords: frozenset[str] = DEFAULT_STOPWORDS

    def __post_init__(self) -> None:
        if not isinstance(self.tokenizer_id, str) or not self.tokenizer_id.strip():
            raise TokenizerConfigError("tokenizer_id must be a non-empty string")
        if self.tokenizer_id != TOKENIZER_ID:
            raise TokenizerConfigError(
                f"unsupported tokenizer_id {self.tokenizer_id!r}; "
                f"only {TOKENIZER_ID!r} is sealed"
            )
        if self.tokenizer_version != TOKENIZER_VERSION:
            raise TokenizerConfigError(
                f"unsupported tokenizer_version {self.tokenizer_version!r}"
            )
        if self.stopword_policy_id != STOPWORD_POLICY_ID:
            raise TokenizerConfigError(
                f"unsupported stopword_policy_id {self.stopword_policy_id!r}"
            )
        if (
            isinstance(self.max_token_chars, bool)
            or not isinstance(self.max_token_chars, int)
            or not MIN_MAX_TOKEN_CHARS <= self.max_token_chars <= MAX_MAX_TOKEN_CHARS
        ):
            raise TokenizerConfigError(
                f"max_token_chars must be in "
                f"[{MIN_MAX_TOKEN_CHARS}, {MAX_MAX_TOKEN_CHARS}]"
            )
        if (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or not MIN_MAX_TOKENS <= self.max_tokens <= MAX_MAX_TOKENS
        ):
            raise TokenizerConfigError(
                f"max_tokens must be in [{MIN_MAX_TOKENS}, {MAX_MAX_TOKENS}]"
            )
        if not isinstance(self.stopwords, (frozenset, set, tuple, list)):
            raise TokenizerConfigError("stopwords must be a set-like collection")
        object.__setattr__(
            self,
            "stopwords",
            frozenset(str(s).casefold() for s in self.stopwords if str(s).strip()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "drop_stopwords": self.drop_stopwords,
            "max_token_chars": self.max_token_chars,
            "max_tokens": self.max_tokens,
            "stopword_policy_id": self.stopword_policy_id,
            "stopword_count": len(self.stopwords),
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_version": self.tokenizer_version,
        }

    @property
    def digest(self) -> str:
        payload = {
            "drop_stopwords": self.drop_stopwords,
            "max_token_chars": self.max_token_chars,
            "max_tokens": self.max_tokens,
            "stopword_policy_id": self.stopword_policy_id,
            "stopwords": sorted(self.stopwords),
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_version": self.tokenizer_version,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def default_tokenizer_config() -> TokenizerConfig:
    """Return the sealed production tokenizer configuration."""

    return TokenizerConfig()


def tokenizer_identity(config: TokenizerConfig | None = None) -> dict[str, Any]:
    """Return the pinned tokenizer identity payload for manifests / explains."""

    cfg = config or default_tokenizer_config()
    return {
        "goal_id": GOAL_ID,
        "release_profile": RELEASE_PROFILE,
        "schema_version": SCHEMA_VERSION,
        "stopword_policy_id": cfg.stopword_policy_id,
        "task_id": TASK_ID,
        "tokenizer_digest": cfg.digest,
        "tokenizer_id": cfg.tokenizer_id,
        "tokenizer_version": cfg.tokenizer_version,
    }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_legal_text(text: str) -> str:
    """NFKC-normalize legal text with locale-independent dash folding.

    Steps (all pure and deterministic):

    1. Reject non-strings and embedded NUL.
    2. NFKC Unicode normalization.
    3. Map Unicode dash/minus code points to ASCII ``-``.
    4. Strip C0/C1 control characters other than TAB/LF/CR.
    5. Collapse horizontal whitespace runs to a single space (preserve
       newlines so line structure remains explainable).

    Case-folding is applied per-token, not here, so surface spans in the
    normalized text retain original casing for explanations.
    """

    if not isinstance(text, str):
        raise UscodeTokenizerError("text must be a string")
    if "\x00" in text:
        raise UscodeTokenizerError("text must not contain NUL")
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.translate(_DASH_TRANSLATION)
    normalized = _CONTROL_RE.sub("", normalized)
    # Normalize exotic newlines to LF, then collapse horizontal whitespace.
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _WS_RE.sub(" ", normalized)
    return normalized


def _casefold_term(text: str) -> str:
    """Locale-independent case folding (never ``str.lower()`` / locale)."""

    return text.casefold()


# ---------------------------------------------------------------------------
# Canonical term forms for protected legal tokens
# ---------------------------------------------------------------------------


def _collapse_internal_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def canonicalize_citation_term(raw: str) -> str:
    """Canonicalize a protected citation / section token for the index.

    Examples (illustrative)::

        "5 U.S.C. § 552"   -> "5_u.s.c._§_552"
        "17 USC 107"       -> "17_u.s.c._107"
        "§ 552(a)"         -> "§_552(a)"
        "section 230"      -> "section_230"
    """

    text = _collapse_internal_ws(raw)
    text = _casefold_term(text)
    # Normalize USC / USCA / CFR abbreviations to a single dotted form.
    # Trailing optional periods are consumed so replacements never double dots.
    text = re.sub(
        r"\bu\s*\.?\s*s\s*\.?\s*c(?:\s*\.?\s*a)?\.?",
        "u.s.c.",
        text,
    )
    text = re.sub(r"\busca?\b", "u.s.c.", text)
    text = re.sub(
        r"\bc\s*\.?\s*f\s*\.?\s*r\.?",
        "c.f.r.",
        text,
    )
    text = re.sub(r"\bcfr\b", "c.f.r.", text)
    # Collapse multi-section symbols and "sec(s)" synonyms to § when used
    # as a section introducer inside a protected span. Keep bare "section"
    # for section_ref tokens (e.g. "section_230").
    text = text.replace("§§", "§")
    text = re.sub(r"\bsecs?\.?\b", "§", text)
    text = re.sub(r"\bsections\b", "§", text)
    # Collapse whitespace around hyphens in ranges.
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _classify_generic(surface: str) -> TokenKind:
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", surface):
        return TokenKind.NUMBER
    if re.fullmatch(r"[0-9]+[a-z](?:[0-9a-z.\-]*)?", surface, re.IGNORECASE):
        # Lettered section tails like 552a, 101a — legally meaningful numbers.
        return TokenKind.NUMBER
    return TokenKind.WORD


def _bound_term(term: str, *, max_token_chars: int) -> str:
    if len(term) <= max_token_chars:
        return term
    return term[:max_token_chars]


# ---------------------------------------------------------------------------
# Core tokenization
# ---------------------------------------------------------------------------


def _find_protected_spans(text: str) -> list[tuple[int, int, TokenKind, str]]:
    """Locate non-overlapping protected legal spans (priority + longest)."""

    candidates: list[tuple[int, int, TokenKind, str]] = []
    for label, pattern in _PROTECTED_PATTERNS:
        kind = _KIND_FROM_PATTERN[label]
        for match in pattern.finditer(text):
            start, end = match.span()
            surface = match.group(0)
            if not surface.strip():
                continue
            candidates.append((start, end, kind, surface))

    # Prefer earlier start, then longer span (greedy legal forms).
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    accepted: list[tuple[int, int, TokenKind, str]] = []
    for start, end, kind, surface in candidates:
        if any(not (end <= s or start >= e) for s, e, _, _ in accepted):
            continue
        accepted.append((start, end, kind, surface))
    accepted.sort(key=lambda item: item[0])
    return accepted


def tokenize_legal_text(
    text: str,
    *,
    config: TokenizerConfig | None = None,
    drop_stopwords: bool | None = None,
) -> TokenizationResult:
    """Tokenize *text* into a versioned legal BM25 token stream.

    Parameters
    ----------
    text:
        Source text (query or document field).
    config:
        Optional sealed configuration; defaults to production pins.
    drop_stopwords:
        Override for ``config.drop_stopwords``. When true, stopword tokens
        are omitted from the stream entirely (typical BM25 indexing). When
        false, they remain with ``kind=stopword`` / ``is_indexable=False``
        so explanations can still point at them.
    """

    cfg = config or default_tokenizer_config()
    if not isinstance(cfg, TokenizerConfig):
        raise TokenizerConfigError("config must be a TokenizerConfig")
    remove_stops = cfg.drop_stopwords if drop_stopwords is None else bool(drop_stopwords)

    if not isinstance(text, str):
        raise UscodeTokenizerError("text must be a string")

    normalized = normalize_legal_text(text)
    if not normalized.strip():
        return TokenizationResult(
            tokenizer_id=cfg.tokenizer_id,
            normalized_text=normalized,
            tokens=(),
            indexable_terms=(),
            truncated=False,
        )

    protected = _find_protected_spans(normalized)
    raw_pieces: list[tuple[int, int, TokenKind, str, bool]] = []
    # (start, end, kind, surface, is_protected)

    cursor = 0
    for start, end, kind, surface in protected:
        if cursor < start:
            gap = normalized[cursor:start]
            for match in _GENERIC_TOKEN_RE.finditer(gap):
                g_start = cursor + match.start()
                g_end = cursor + match.end()
                g_surface = match.group(0)
                raw_pieces.append(
                    (g_start, g_end, _classify_generic(g_surface), g_surface, False)
                )
        raw_pieces.append((start, end, kind, surface, True))
        cursor = end
    if cursor < len(normalized):
        gap = normalized[cursor:]
        for match in _GENERIC_TOKEN_RE.finditer(gap):
            g_start = cursor + match.start()
            g_end = cursor + match.end()
            g_surface = match.group(0)
            raw_pieces.append(
                (g_start, g_end, _classify_generic(g_surface), g_surface, False)
            )

    tokens: list[LegalToken] = []
    indexable_terms: list[str] = []
    truncated = False
    position = 0
    pieces_consumed = 0

    for start, end, kind, surface, is_protected in raw_pieces:
        if is_protected:
            term = canonicalize_citation_term(surface)
        else:
            term = _casefold_term(surface)
            # Sentence punctuation is not part of a BM25 term ("records." -> "records").
            term = term.rstrip(".,;:!?")

        term = _bound_term(term, max_token_chars=cfg.max_token_chars)
        if not term:
            pieces_consumed += 1
            continue

        is_stop = (
            not is_protected
            and kind == TokenKind.WORD
            and term in cfg.stopwords
        )
        if is_stop:
            emit_kind = TokenKind.STOPWORD
            is_indexable = False
        else:
            emit_kind = kind
            is_indexable = True

        if is_stop and remove_stops:
            # Skip entirely for indexing streams; do not count toward bound.
            pieces_consumed += 1
            continue

        if len(tokens) >= cfg.max_tokens:
            truncated = True
            break

        token = LegalToken(
            index=len(tokens),
            position=position if is_indexable else -1,
            term=term,
            surface=surface,
            kind=emit_kind,
            char_start=start,
            char_end=end,
            is_stopword=is_stop,
            is_indexable=is_indexable,
        )
        tokens.append(token)
        if is_indexable:
            indexable_terms.append(term)
            position += 1
        pieces_consumed += 1

    if not truncated and pieces_consumed < len(raw_pieces):
        # Remaining pieces only if we broke on max_tokens.
        truncated = len(tokens) >= cfg.max_tokens

    return TokenizationResult(
        tokenizer_id=cfg.tokenizer_id,
        normalized_text=normalized,
        tokens=tuple(tokens),
        indexable_terms=tuple(indexable_terms),
        truncated=truncated,
    )


def tokenize_uscode(
    text: str,
    *,
    config: TokenizerConfig | None = None,
    drop_stopwords: bool | None = None,
) -> list[LegalToken]:
    """Convenience wrapper returning only the token list."""

    return list(tokenize_legal_text(text, config=config, drop_stopwords=drop_stopwords).tokens)


def tokenize_terms(
    text: str,
    *,
    config: TokenizerConfig | None = None,
) -> list[str]:
    """Return indexable BM25 terms (stopwords dropped; protected forms kept)."""

    return list(
        tokenize_legal_text(text, config=config, drop_stopwords=True).indexable_terms
    )


def term_frequencies(
    text: str,
    *,
    config: TokenizerConfig | None = None,
) -> Counter[str]:
    """Return term frequencies over indexable tokens."""

    return Counter(tokenize_terms(text, config=config))


def legal_tokens_present(text: str, *, config: TokenizerConfig | None = None) -> list[str]:
    """Return protected legal terms that survive tokenization (stable order)."""

    result = tokenize_legal_text(text, config=config, drop_stopwords=False)
    seen: set[str] = set()
    out: list[str] = []
    for token in result.tokens:
        if token.kind in _PROTECTED_KINDS and token.term not in seen:
            seen.add(token.term)
            out.append(token.term)
    return out


def explain_tokens(
    text: str,
    *,
    config: TokenizerConfig | None = None,
    drop_stopwords: bool = False,
) -> list[dict[str, Any]]:
    """Return explain payloads mapping terms back to normalized surface spans."""

    result = tokenize_legal_text(text, config=config, drop_stopwords=drop_stopwords)
    return [
        {
            "char_end": t.char_end,
            "char_start": t.char_start,
            "kind": t.kind.value,
            "position": t.position,
            "surface": t.surface,
            "term": t.term,
            "is_indexable": t.is_indexable,
            "is_stopword": t.is_stopword,
            "span_text": result.normalized_text[t.char_start : t.char_end],
        }
        for t in result.tokens
    ]


def reconstruct_from_tokens(
    tokens: Sequence[LegalToken],
    *,
    separator: str = " ",
) -> str:
    """Join token surfaces for coarse reverse display (not exact source restore).

    Exact reconstruction uses offsets into ``normalized_text``; this helper
    is for explain UIs that only hold the token stream.
    """

    return separator.join(t.surface for t in tokens)


def assert_offsets_recover_surface(result: TokenizationResult) -> None:
    """Fail closed if any token surface does not match its normalized span."""

    text = result.normalized_text
    for token in result.tokens:
        span = text[token.char_start : token.char_end]
        if span != token.surface:
            raise UscodeTokenizerError(
                f"token {token.index} surface {token.surface!r} != "
                f"span {span!r} at [{token.char_start}, {token.char_end})"
            )


# ---------------------------------------------------------------------------
# Sealed fixture (compact recipe)
# ---------------------------------------------------------------------------


def default_tokenization_fixture_path() -> Path:
    """Return the default on-disk path for the sealed tokenization fixture."""

    # ipfs_datasets_py/processors/legal_data/this_file.py → repo root
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / "tests" / "fixtures" / "legal_ir" / "uscode_tokenization.json"


def build_default_tokenization_fixture_payload() -> dict[str, Any]:
    """Compact recipe of deterministic tokenization cases (not bulk goldens)."""

    return {
        "description": (
            "Compact recipe for versioned legal BM25 tokenization. Each case "
            "supplies source text; expected terms/kinds are derived by the "
            "sealed tokenizer or asserted via compact expect rules rather than "
            "bulk per-token golden dumps."
        ),
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "tokenizer_id": TOKENIZER_ID,
        "tokenizer_version": TOKENIZER_VERSION,
        "stopword_policy_id": STOPWORD_POLICY_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "acceptance": {
            "locale_independent": True,
            "bounded": True,
            "stable_across_fixtures": True,
            "reversible_for_explanations": True,
            "distinguishes_legal_numeric_citation_tokens": True,
        },
        "cases": [
            {
                "case_id": "usc-citation-dotted",
                "text": "Public records under 5 U.S.C. § 552 must be disclosed.",
                "expect": {
                    "must_contain_kinds": ["citation"],
                    "must_contain_term_substrings": ["5_u.s.c.", "552"],
                    "must_not_split_citation": True,
                    "reversible_offsets": True,
                    "deterministic": True,
                },
            },
            {
                "case_id": "usc-citation-compact",
                "text": "17 USC 107 fair use factors",
                "expect": {
                    "must_contain_kinds": ["citation"],
                    "must_contain_term_substrings": ["17_u.s.c.", "107"],
                    "must_not_split_citation": True,
                    "reversible_offsets": True,
                },
            },
            {
                "case_id": "section-symbol-and-range",
                "text": "See § 552(a) and §§ 106–107 for related rights.",
                "expect": {
                    "must_contain_kinds": ["section_symbol"],
                    "must_contain_term_substrings": ["§_552(a)", "§_106-107"],
                    "dash_normalized": True,
                    "reversible_offsets": True,
                },
            },
            {
                "case_id": "section-abbrev",
                "text": "Section 230 platform immunity for third-party content",
                "expect": {
                    "must_contain_kinds": ["section_ref"],
                    "must_contain_term_substrings": ["section_230"],
                    "reversible_offsets": True,
                },
            },
            {
                "case_id": "numeric-section-token",
                "text": "Title 42 identifiers include 1983 and 12101a plus section 552a.",
                "expect": {
                    "must_contain_kinds": ["number", "section_ref"],
                    "must_contain_terms": ["1983", "12101a", "section_552a"],
                    "distinguishes_numbers": True,
                    "reversible_offsets": True,
                },
            },
            {
                "case_id": "stopwords-dropped-for-index",
                "text": "The agency shall make available to the public the information.",
                "drop_stopwords": True,
                "expect": {
                    "must_not_contain_terms": ["the", "to"],
                    "must_contain_terms": ["agency", "shall", "make", "available", "public", "information"],
                    "stopwords_absent": True,
                },
            },
            {
                "case_id": "stopwords-kept-for-explain",
                "text": "The agency shall disclose.",
                "drop_stopwords": False,
                "expect": {
                    "must_contain_kinds": ["stopword"],
                    "must_contain_terms": ["the", "agency", "shall", "disclose"],
                    "reversible_offsets": True,
                },
            },
            {
                "case_id": "unicode-controls-and-dashes",
                "text": "Range 1001\u20131003 under 18 U.S.C. \u00a7 1001\u2014note\twith\x07noise",
                "expect": {
                    "dash_normalized": True,
                    "controls_stripped": True,
                    "must_contain_kinds": ["citation"],
                    "reversible_offsets": True,
                    "deterministic": True,
                },
            },
            {
                "case_id": "paren-markers",
                "text": "(a) Each agency shall publish; (1) descriptions; (iv) further detail.",
                "expect": {
                    "must_contain_kinds": ["paren_marker"],
                    "must_contain_terms": ["(a)", "(1)", "(iv)"],
                    "reversible_offsets": True,
                },
            },
            {
                "case_id": "casefold-locale-independent",
                "text": "FREEDOM of Information ACT records under 5 U.S.C. § 552",
                "expect": {
                    "casefold_stable": True,
                    "must_contain_term_substrings": ["freedom", "information", "act", "5_u.s.c."],
                    "locale_independent": True,
                    "deterministic": True,
                },
            },
            {
                "case_id": "bounded-token-stream",
                "text_recipe": {
                    "kind": "repeat_word",
                    "word": "provision ",
                    "repeat": 50,
                },
                "config_overrides": {
                    "max_tokens": 16,
                },
                "expect": {
                    "bounded": True,
                    "max_indexable": 16,
                    "truncated": True,
                },
            },
            {
                "case_id": "empty-and-whitespace",
                "text": "   \n\t  ",
                "expect": {
                    "empty": True,
                    "token_count": 0,
                },
            },
        ],
    }


def expand_case_text(case: Mapping[str, Any]) -> str:
    """Materialize case text from inline ``text`` or a compact ``text_recipe``."""

    if "text" in case and case["text"] is not None:
        return str(case["text"])
    recipe = case.get("text_recipe")
    if not isinstance(recipe, Mapping):
        raise TokenizationFixtureError(
            f"case {case.get('case_id')!r} missing text/text_recipe"
        )
    kind = str(recipe.get("kind") or "")
    if kind == "repeat_word":
        word = str(recipe.get("word") or "")
        repeat = int(recipe.get("repeat") or 0)
        if not word or repeat < 1:
            raise TokenizationFixtureError(
                f"case {case.get('case_id')!r} has invalid repeat_word recipe"
            )
        return word * repeat
    if kind == "repeat_sentence":
        sentence = str(recipe.get("sentence") or "")
        repeat = int(recipe.get("repeat") or 0)
        if not sentence or repeat < 1:
            raise TokenizationFixtureError(
                f"case {case.get('case_id')!r} has invalid repeat_sentence recipe"
            )
        return sentence * repeat
    raise TokenizationFixtureError(
        f"case {case.get('case_id')!r} has unknown text_recipe kind {kind!r}"
    )


def load_tokenization_fixture_payload(path: PathLike | None = None) -> dict[str, Any]:
    """Load and validate the sealed tokenization fixture payload."""

    fixture_path = (
        Path(path) if path is not None else default_tokenization_fixture_path()
    )
    if not fixture_path.is_file():
        raise TokenizationFixtureError(f"fixture not found: {fixture_path}")
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TokenizationFixtureError(
            f"invalid JSON in {fixture_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise TokenizationFixtureError("fixture root must be an object")
    if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise TokenizationFixtureError(
            f"unsupported fixture schema_version: {payload.get('schema_version')!r}"
        )
    if payload.get("tokenizer_id") != TOKENIZER_ID:
        raise TokenizationFixtureError(
            f"fixture tokenizer_id mismatch: {payload.get('tokenizer_id')!r}"
        )
    if not isinstance(payload.get("cases"), list) or not payload["cases"]:
        raise TokenizationFixtureError("fixture must contain a non-empty cases list")
    return payload


def _config_from_case(case: Mapping[str, Any]) -> TokenizerConfig:
    overrides = case.get("config_overrides") or {}
    if overrides and not isinstance(overrides, Mapping):
        raise TokenizationFixtureError(
            f"case {case.get('case_id')!r} config_overrides must be an object"
        )
    kwargs: dict[str, Any] = {}
    if "max_tokens" in overrides:
        kwargs["max_tokens"] = int(overrides["max_tokens"])
    if "max_token_chars" in overrides:
        kwargs["max_token_chars"] = int(overrides["max_token_chars"])
    if "drop_stopwords" in overrides:
        kwargs["drop_stopwords"] = bool(overrides["drop_stopwords"])
    return TokenizerConfig(**kwargs)


def run_fixture_case(case: Mapping[str, Any]) -> TokenizationResult:
    """Execute one sealed fixture case and return the tokenization result."""

    text = expand_case_text(case)
    config = _config_from_case(case)
    drop = case.get("drop_stopwords")
    drop_stopwords = None if drop is None else bool(drop)
    return tokenize_legal_text(text, config=config, drop_stopwords=drop_stopwords)


def assert_case_expectations(
    case: Mapping[str, Any],
    result: TokenizationResult,
) -> None:
    """Validate compact expect rules for a fixture case (fail closed)."""

    expect = case.get("expect") or {}
    if not isinstance(expect, Mapping):
        raise TokenizationFixtureError(
            f"case {case.get('case_id')!r} expect must be an object"
        )
    case_id = case.get("case_id")
    terms = list(result.indexable_terms)
    all_terms = [t.term for t in result.tokens]
    kinds = {t.kind.value for t in result.tokens}

    if expect.get("empty"):
        if result.token_count != 0:
            raise UscodeTokenizerError(
                f"{case_id}: expected empty token stream, got {result.token_count}"
            )

    if "token_count" in expect and int(expect["token_count"]) != result.token_count:
        raise UscodeTokenizerError(
            f"{case_id}: token_count {result.token_count} != {expect['token_count']}"
        )

    for kind in expect.get("must_contain_kinds") or []:
        if str(kind) not in kinds:
            # Indexable-only streams may drop stopwords; protected kinds remain.
            if str(kind) == "stopword" and case.get("drop_stopwords") is not False:
                continue
            raise UscodeTokenizerError(
                f"{case_id}: missing token kind {kind!r}; have {sorted(kinds)}"
            )

    for needle in expect.get("must_contain_term_substrings") or []:
        blob = " ".join(all_terms if all_terms else terms)
        if str(needle).casefold() not in blob.casefold():
            raise UscodeTokenizerError(
                f"{case_id}: missing term substring {needle!r} in {blob!r}"
            )

    for term in expect.get("must_contain_terms") or []:
        target = str(term).casefold()
        pool_cf = {p.casefold() for p in all_terms}
        if target not in pool_cf and not any(target in p for p in pool_cf):
            raise UscodeTokenizerError(
                f"{case_id}: missing term {term!r}; have {all_terms}"
            )

    for term in expect.get("must_not_contain_terms") or []:
        target = str(term).casefold()
        if target in {t.casefold() for t in result.indexable_terms}:
            raise UscodeTokenizerError(
                f"{case_id}: indexable terms unexpectedly contain {term!r}"
            )

    if expect.get("must_not_split_citation"):
        citation_tokens = [t for t in result.tokens if t.kind == TokenKind.CITATION]
        if not citation_tokens:
            raise UscodeTokenizerError(f"{case_id}: expected a citation token")
        # Citation must be a single token (no split into 5 / u.s.c. / 552).
        for token in citation_tokens:
            if "u.s.c" not in token.term and "c.f.r" not in token.term:
                raise UscodeTokenizerError(
                    f"{case_id}: citation token not canonical: {token.term!r}"
                )

    if expect.get("reversible_offsets"):
        assert_offsets_recover_surface(result)

    if expect.get("deterministic"):
        again = run_fixture_case(case)
        if [t.to_dict() for t in again.tokens] != [t.to_dict() for t in result.tokens]:
            raise UscodeTokenizerError(f"{case_id}: non-deterministic tokenization")

    if expect.get("dash_normalized"):
        if "\u2013" in result.normalized_text or "\u2014" in result.normalized_text:
            raise UscodeTokenizerError(f"{case_id}: unicode dashes not normalized")
        if "-" not in result.normalized_text and not any(
            "-" in t.term for t in result.tokens
        ):
            # Some cases may only strip controls; require dash fold when source
            # had a unicode dash (checked by presence of hyphen in terms/text).
            source = expand_case_text(case)
            if any(ch in source for ch in _UNICODE_DASH_CHARS):
                raise UscodeTokenizerError(f"{case_id}: expected ASCII hyphen after dash fold")

    if expect.get("controls_stripped"):
        if "\x07" in result.normalized_text:
            raise UscodeTokenizerError(f"{case_id}: control characters not stripped")

    if expect.get("stopwords_absent"):
        for t in result.tokens:
            if t.is_stopword or t.kind == TokenKind.STOPWORD:
                raise UscodeTokenizerError(
                    f"{case_id}: stopword {t.term!r} present despite drop policy"
                )

    if expect.get("distinguishes_numbers"):
        number_terms = [t.term for t in result.tokens if t.kind == TokenKind.NUMBER]
        if not number_terms:
            raise UscodeTokenizerError(f"{case_id}: expected number tokens")

    if expect.get("casefold_stable"):
        upper = tokenize_legal_text(expand_case_text(case).swapcase())
        if upper.indexable_terms != result.indexable_terms:
            # Allow if original was mixed; compare casefold of source twice.
            a = tokenize_terms(expand_case_text(case))
            b = tokenize_terms(expand_case_text(case).casefold())
            c = tokenize_terms(expand_case_text(case).upper())
            if not (a == b == c):
                raise UscodeTokenizerError(f"{case_id}: casefold not stable")

    if expect.get("locale_independent"):
        # Setting locale must not affect casefold-based tokenization.
        import locale as _locale

        try:
            previous = _locale.setlocale(_locale.LC_ALL)
        except _locale.Error:
            previous = None
        try:
            for candidate in ("C", "C.UTF-8", "POSIX"):
                try:
                    _locale.setlocale(_locale.LC_ALL, candidate)
                except _locale.Error:
                    continue
                other = tokenize_terms(expand_case_text(case))
                if other != list(result.indexable_terms):
                    raise UscodeTokenizerError(
                        f"{case_id}: locale {candidate!r} changed tokens"
                    )
        finally:
            if previous is not None:
                try:
                    _locale.setlocale(_locale.LC_ALL, previous)
                except _locale.Error:
                    pass

    if expect.get("bounded"):
        max_indexable = expect.get("max_indexable")
        if max_indexable is not None and result.indexable_count > int(max_indexable):
            raise UscodeTokenizerError(
                f"{case_id}: indexable_count {result.indexable_count} "
                f"exceeds bound {max_indexable}"
            )
        if expect.get("truncated") and not result.truncated:
            raise UscodeTokenizerError(f"{case_id}: expected truncated=True")

    if expect.get("truncated") is False and result.truncated:
        raise UscodeTokenizerError(f"{case_id}: unexpected truncation")


def run_all_fixture_cases(
    path: PathLike | None = None,
) -> list[tuple[str, TokenizationResult]]:
    """Run every sealed fixture case and enforce expect rules."""

    payload = load_tokenization_fixture_payload(path)
    results: list[tuple[str, TokenizationResult]] = []
    for case in payload["cases"]:
        if not isinstance(case, Mapping):
            raise TokenizationFixtureError("fixture case must be an object")
        case_id = str(case.get("case_id") or "")
        result = run_fixture_case(case)
        assert_case_expectations(case, result)
        results.append((case_id, result))
    return results


def write_default_tokenization_fixture(path: PathLike | None = None) -> Path:
    """Write the sealed compact recipe to disk (UTF-8, stable key order)."""

    p = Path(path) if path is not None else default_tokenization_fixture_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = build_default_tokenization_fixture_payload()
    p.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return p


__all__ = [
    "DEFAULT_MAX_TOKEN_CHARS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_STOPWORDS",
    "FIXTURE_SCHEMA_VERSION",
    "GOAL_ID",
    "RELEASE_PROFILE",
    "SCHEMA_VERSION",
    "STOPWORD_POLICY_ID",
    "TASK_ID",
    "TOKENIZER_ID",
    "TOKENIZER_VERSION",
    "LegalToken",
    "TokenKind",
    "TokenizationFixtureError",
    "TokenizationResult",
    "TokenizerBoundError",
    "TokenizerConfig",
    "TokenizerConfigError",
    "UscodeTokenizerError",
    "assert_case_expectations",
    "assert_offsets_recover_surface",
    "build_default_tokenization_fixture_payload",
    "canonicalize_citation_term",
    "default_tokenization_fixture_path",
    "default_tokenizer_config",
    "expand_case_text",
    "explain_tokens",
    "legal_tokens_present",
    "load_tokenization_fixture_payload",
    "normalize_legal_text",
    "reconstruct_from_tokens",
    "run_all_fixture_cases",
    "run_fixture_case",
    "term_frequencies",
    "tokenize_legal_text",
    "tokenize_terms",
    "tokenize_uscode",
    "tokenizer_identity",
    "write_default_tokenization_fixture",
]
