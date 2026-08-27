"""Dataset-neutral legal graph algorithms shared by legal corpora.

This module owns only mechanics whose semantics are common to Open US Law and
the state-law corpus.  Dataset vocabulary and identity choices stay explicit
in immutable bindings supplied by the two public adapter modules.  In
particular, the adapters retain their distinct graph CID namespaces, ontology
versions, public-law node names, jurisdiction labels, and legal-ID builders.

The core performs no I/O and authorizes no release or publication.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Optional

AUTHORIZES_PUBLICATION = False
AUTHORIZES_RELEASE = False
AUTHORIZES_HUB_UPLOAD = False
PERFORMS_NETWORK_IO = False


def require_non_empty_str(
    value: Any,
    name: str,
    *,
    error_type: type[Exception],
    maximum: int = 4096,
) -> str:
    """Validate the shared non-empty string contract with adapter errors."""

    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise error_type(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise error_type(f"{name} exceeds max length {maximum}")
    return text


def optional_str(
    value: Any,
    name: str = "value",
    *,
    error_type: type[Exception],
    maximum: int = 4096,
) -> Optional[str]:
    if value is None or value == "":
        return None
    return require_non_empty_str(
        value,
        name,
        error_type=error_type,
        maximum=maximum,
    )


def require_non_negative_int(
    value: Any,
    name: str,
    *,
    error_type: type[Exception],
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise error_type(f"{name} must be an integer")
    if value < 0:
        raise error_type(f"{name} must be >= 0")
    return value


def sha256_cid(
    payload: Mapping[str, Any],
    *,
    digest_mapping: Callable[[Mapping[str, Any]], str],
) -> str:
    """Return the common deterministic ``sha256:<hex>`` content address."""

    return f"sha256:{digest_mapping(dict(payload))}"


def coerce_graph_enum(
    enum_type: type,
    value: Any,
    *,
    aliases: Mapping[str, Any],
    error_type: type[Exception],
    label: str,
    uppercase: bool = False,
    replace_spaces: bool = True,
) -> Any:
    """Coerce a graph vocabulary value without owning dataset vocabulary."""

    if isinstance(value, enum_type):
        return value
    text = str(value or "").strip()
    text = text.upper() if uppercase else text.lower()
    text = text.replace("-", "_")
    if replace_spaces:
        text = text.replace(" ", "_")
    if text in aliases:
        return aliases[text]
    for item in enum_type:
        name = item.name if uppercase else item.name.lower()
        if item.value == text or name == text:
            return item
    raise error_type(f"unsupported {label}: {value!r}")


# ---------------------------------------------------------------------------
# Shared source-span record mechanics
# ---------------------------------------------------------------------------


def validate_source_span_record(self: Any) -> None:
    graph_error = self._graph_error_type
    span_error = self._source_span_error_type
    start = require_non_negative_int(self.start, "start", error_type=graph_error)
    end = require_non_negative_int(self.end, "end", error_type=graph_error)
    if end < start:
        raise span_error(f"span end {end} must be >= start {start}")
    text = self.text if isinstance(self.text, str) else ""
    if "\x00" in text:
        raise span_error("span text must not contain NUL")
    if len(text) != end - start:
        raise span_error(
            f"span text length {len(text)} must equal end-start ({end - start})"
        )
    object.__setattr__(self, "start", start)
    object.__setattr__(self, "end", end)
    object.__setattr__(self, "text", text)
    if self.source_cid is not None:
        object.__setattr__(
            self,
            "source_cid",
            require_non_empty_str(
                self.source_cid,
                "source_cid",
                error_type=graph_error,
                maximum=256,
            ),
        )
    if self.entry_cid is not None:
        object.__setattr__(
            self,
            "entry_cid",
            require_non_empty_str(
                self.entry_cid,
                "entry_cid",
                error_type=graph_error,
                maximum=256,
            ),
        )
    object.__setattr__(
        self,
        "field",
        require_non_empty_str(
            self.field or "text",
            "field",
            error_type=graph_error,
            maximum=64,
        ),
    )


def bind_source_span(self: Any, source_text: str) -> Any:
    span_error = self._source_span_error_type
    if not isinstance(source_text, str):
        raise span_error("source_text must be a string")
    if self.end > len(source_text):
        raise span_error(
            f"span end {self.end} exceeds source length {len(source_text)}"
        )
    excerpt = source_text[self.start : self.end]
    if excerpt != self.text:
        raise span_error(
            "span text does not match source_text[start:end]; "
            f"expected {excerpt!r}, got {self.text!r}"
        )
    return self


def source_span_to_dict(self: Any) -> dict[str, Any]:
    return {
        "end": self.end,
        "entry_cid": self.entry_cid,
        "field": self.field,
        "source_cid": self.source_cid,
        "start": self.start,
        "text": self.text,
    }


def source_span_from_mapping(cls: type, value: Mapping[str, Any]) -> Any:
    if not isinstance(value, Mapping):
        raise cls._source_span_error_type("source span must be a mapping")
    return cls(
        start=int(value.get("start", 0)),
        end=int(value.get("end", 0)),
        text=str(value.get("text") or ""),
        source_cid=value.get("source_cid"),
        entry_cid=value.get("entry_cid"),
        field=str(value.get("field") or "text"),
    )


def source_span_from_occurrence(
    cls: type,
    source_text: str,
    mention: str,
    *,
    source_cid: Optional[str] = None,
    entry_cid: Optional[str] = None,
    field: str = "text",
    start_hint: Optional[int] = None,
) -> Any:
    span_error = cls._source_span_error_type
    if not isinstance(source_text, str):
        raise span_error("source_text must be a string")
    if not isinstance(mention, str) or not mention:
        raise span_error("mention must be a non-empty string")
    if start_hint is not None:
        start = int(start_hint)
        end = start + len(mention)
        if source_text[start:end] != mention:
            raise span_error(f"mention {mention!r} not found at start_hint={start}")
    else:
        start = source_text.find(mention)
        if start < 0:
            raise span_error(f"mention {mention!r} not found in source_text")
        end = start + len(mention)
    return cls(
        start=start,
        end=end,
        text=mention,
        source_cid=source_cid,
        entry_cid=entry_cid,
        field=field,
    ).bind_to_source(source_text)


# ---------------------------------------------------------------------------
# Shared ontology mechanics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LegalGraphOntologyBindings:
    version: str
    node_type: type
    edge_type: type
    edge_class: type
    legal_edge_types: frozenset[Any]
    similarity_edge_types: frozenset[Any]
    required_coverage_node_types: tuple[str, ...]
    default_edge_class: Mapping[Any, Any]
    direction_allowed: Callable[[Any, Any, Any], bool]
    assert_disjoint: Callable[[], None]
    ontology_error_type: type[Exception]
    collision_error_type: type[Exception]


def assert_legal_similarity_disjoint(
    *,
    edge_type: type,
    edge_class: type,
    legal_edge_types: frozenset[Any],
    similarity_edge_types: frozenset[Any],
    default_edge_class: Mapping[Any, Any],
    ontology_error_type: type[Exception],
    collision_error_type: type[Exception],
) -> None:
    """Fail closed when an adapter's legal and similarity vocabularies collide."""

    overlap = legal_edge_types & similarity_edge_types
    if overlap:
        names = sorted(item.value for item in overlap)
        raise collision_error_type(
            f"legal and similarity edge types must be disjoint; overlap={names}"
        )
    for item in edge_type:
        if item not in legal_edge_types and item not in similarity_edge_types:
            raise ontology_error_type(
                f"edge type {item.value} is neither legal nor similarity"
            )
    for item, category in default_edge_class.items():
        if item in similarity_edge_types and category is not edge_class.SIMILARITY:
            raise collision_error_type(
                f"similarity edge {item.value} must use class similarity"
            )
        if item in legal_edge_types and category is edge_class.SIMILARITY:
            raise collision_error_type(
                f"legal edge {item.value} must not use class similarity"
            )


def validate_graph_ontology(self: Any) -> None:
    bindings: LegalGraphOntologyBindings = self._ontology_bindings
    if self.version != bindings.version:
        raise bindings.ontology_error_type(
            f"unsupported ontology version: {self.version!r}; "
            f"expected {bindings.version!r}"
        )
    expected_nodes = tuple(item.value for item in bindings.node_type)
    expected_edges = tuple(item.value for item in bindings.edge_type)
    if self.node_types != expected_nodes:
        raise bindings.ontology_error_type(
            "node_types must exactly match the versioned vocabulary"
        )
    if self.edge_types != expected_edges:
        raise bindings.ontology_error_type(
            "edge_types must exactly match the versioned vocabulary"
        )
    bindings.assert_disjoint()
    legal_set = set(self.legal_edge_types)
    similarity_set = set(self.similarity_edge_types)
    if legal_set & similarity_set:
        raise bindings.collision_error_type(
            "ontology legal_edge_types and similarity_edge_types overlap"
        )
    missing = [
        name
        for name in bindings.required_coverage_node_types
        if name not in expected_nodes
    ]
    if missing:
        raise bindings.ontology_error_type(
            f"ontology is missing required coverage node types: {missing}"
        )


def graph_ontology_edge_class_for(self: Any, edge_type: Any) -> Any:
    bindings: LegalGraphOntologyBindings = self._ontology_bindings
    edge = bindings.edge_type.coerce(edge_type)
    raw = self.edge_class_by_type.get(edge.value)
    if raw is None:
        raise bindings.ontology_error_type(f"no edge class for {edge.value}")
    return bindings.edge_class.coerce(raw)


def graph_ontology_is_legal_edge(self: Any, edge_type: Any) -> bool:
    bindings: LegalGraphOntologyBindings = self._ontology_bindings
    return bindings.edge_type.coerce(edge_type) in bindings.legal_edge_types


def graph_ontology_is_similarity_edge(self: Any, edge_type: Any) -> bool:
    bindings: LegalGraphOntologyBindings = self._ontology_bindings
    return bindings.edge_type.coerce(edge_type) in bindings.similarity_edge_types


def validate_graph_ontology_edge(
    self: Any,
    edge_type: Any,
    source_type: Any,
    target_type: Any,
    *,
    edge_class: Any = None,
) -> Any:
    bindings: LegalGraphOntologyBindings = self._ontology_bindings
    edge = bindings.edge_type.coerce(edge_type)
    source = bindings.node_type.coerce(source_type)
    target = bindings.node_type.coerce(target_type)
    expected = self.edge_class_for(edge)
    if edge_class is not None:
        provided = bindings.edge_class.coerce(edge_class)
        if provided is not expected:
            raise bindings.ontology_error_type(
                f"{edge.value} must be classified as {expected.value}, "
                f"got {provided.value}"
            )
        category = provided
    else:
        category = expected

    similarity_class = bindings.edge_class.SIMILARITY
    if edge in bindings.similarity_edge_types and category is not similarity_class:
        raise bindings.collision_error_type(
            f"similarity edge {edge.value} cannot use class {category.value}"
        )
    if edge in bindings.legal_edge_types and category is similarity_class:
        raise bindings.collision_error_type(
            f"legal edge {edge.value} cannot use class similarity"
        )
    if not bindings.direction_allowed(edge, source, target):
        raise bindings.ontology_error_type(
            f"{edge.value} does not permit {source.value} -> {target.value}"
        )
    return category


def graph_ontology_to_dict(self: Any) -> dict[str, Any]:
    return {
        "edge_class_by_type": dict(self.edge_class_by_type),
        "edge_types": list(self.edge_types),
        "legal_edge_types": list(self.legal_edge_types),
        "node_types": list(self.node_types),
        "required_coverage_node_types": list(self.required_coverage_node_types),
        "similarity_edge_types": list(self.similarity_edge_types),
        "version": self.version,
    }


def legal_edge_direction_allowed(
    edge: Any,
    source: Any,
    target: Any,
    *,
    node_type: type,
    edge_type: type,
    section_like: frozenset[Any],
    similarity_edge_types: frozenset[Any],
    act_node_type: Any,
    edition_edge_types: frozenset[Any],
) -> bool:
    """Common direction contract with explicit dataset vocabulary seams."""

    if edge is edge_type.CONTAINS:
        allowed = {
            (node_type.JURISDICTION, node_type.CODE),
            (node_type.CODE, node_type.TITLE),
            (node_type.CODE, node_type.CHAPTER),
            (node_type.CODE, node_type.SECTION),
            (node_type.TITLE, node_type.CHAPTER),
            (node_type.TITLE, node_type.SECTION),
            (node_type.CHAPTER, node_type.SECTION),
            (node_type.SECTION, node_type.SUBSECTION),
        }
        return (source, target) in allowed
    if edge is edge_type.CITES:
        return source in section_like and target in section_like
    if edge is edge_type.CITES_UNRESOLVED:
        return source in section_like and target is node_type.UNRESOLVED_CITATION
    if edge is edge_type.HAS_CITATION:
        return source in section_like and target is node_type.CITATION
    if edge in {edge_type.AMENDS, edge_type.REPEALS, edge_type.TRANSFERS}:
        return source in section_like | {node_type.AMENDMENT, act_node_type} and (
            target in section_like
        )
    if edge is edge_type.HAS_AMENDMENT:
        return source in section_like and target is node_type.AMENDMENT
    if edge is edge_type.HAS_SOURCE:
        return source in section_like and target is node_type.SOURCE
    if edge in edition_edge_types:
        return source in {
            node_type.JURISDICTION,
            node_type.CODE,
            node_type.TITLE,
            node_type.CHAPTER,
            node_type.SECTION,
            node_type.SUBSECTION,
        } and target is node_type.EDITION
    if edge is edge_type.HAS_PROVENANCE:
        return source in section_like and target is node_type.PROVENANCE
    if edge is edge_type.DERIVED_FROM:
        return source in section_like and target in {
            act_node_type,
            node_type.SOURCE,
            node_type.PROVENANCE,
        }
    if edge is edge_type.CODIFIES:
        return source is act_node_type and target in section_like
    if edge in similarity_edge_types:
        return source in section_like and target in section_like
    return False


# ---------------------------------------------------------------------------
# Shared citation extraction / resolution
# ---------------------------------------------------------------------------


USC_CITATION_RE = re.compile(
    r"""
    (?P<mention>
        (?P<title>\d+[A-Za-z]?)\s*
        U\.?\s*S\.?\s*C\.?(?:A\.?)?\s*
        (?:§+\s*|sec(?:tion)?\.?\s*)?
        (?P<section>\d+[A-Za-z0-9\-]*(?:\.[A-Za-z0-9\-]+)*(?:\([a-zA-Z0-9]+\))*)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

PUBLIC_LAW_RE = re.compile(
    r"""
    (?P<mention>
        (?:Pub(?:lic)?\.?\s*L(?:aw)?\.?|P\.?\s*L\.?)\s*
        (?:No\.?\s*)?
        (?P<congress>\d+)\s*[-–—]\s*(?P<number>\d+)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

SHORT_CODE_RE = re.compile(
    r"""
    (?P<mention>
        (?P<code>
            ORS|RCW|NRS|CRS|ARS|C\.R\.S\.|A\.R\.S\.|USC|
            D\.C\.\s*Code|DC\s+Code
        )
        \s+
        (?:§+\s*)?
        (?P<section>\d+[A-Za-z0-9.\-]*(?:\([a-zA-Z0-9]+\))*)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

BLUEBOOK_RE = re.compile(
    r"""
    (?P<mention>
        (?P<prefix>
            Cal\.|Calif\.|California|
            N\.Y\.|NY|New\s+York|
            Or\.|Ore\.|Oregon|
            Tex\.|Texas|
            Wash\.|Washington|
            D\.C\.|DC
        )
        \s+
        (?P<code>
            Penal\s+Code|Penal\s+Law|Rev\.\s*Stat\.|Rev\.\s*Code|
            Revised\s+Statutes|Revised\s+Code|Code
        )
        \s*
        (?:§+\s*)
        (?P<section>\d+[A-Za-z0-9.\-]*(?:\([a-zA-Z0-9]+\))*)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

INTERNAL_SECTION_RE = re.compile(
    r"(?P<mention>§+\s*(?P<section>\d+[A-Za-z0-9.\-]*(?:\([a-zA-Z0-9]+\))*))"
)

CITATION_CODE_ALIASES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "ors": ("OR", "ors"),
        "or rev stat": ("OR", "ors"),
        "or. rev. stat": ("OR", "ors"),
        "ore rev stat": ("OR", "ors"),
        "oregon revised statutes": ("OR", "ors"),
        "or. revised statutes": ("OR", "ors"),
        "rcw": ("WA", "rcw"),
        "wash rev code": ("WA", "rcw"),
        "wash. rev. code": ("WA", "rcw"),
        "washington revised code": ("WA", "rcw"),
        "cal penal code": ("CA", "penal-code"),
        "cal. penal code": ("CA", "penal-code"),
        "calif penal code": ("CA", "penal-code"),
        "california penal code": ("CA", "penal-code"),
        "n.y. penal law": ("NY", "penal-law"),
        "ny penal law": ("NY", "penal-law"),
        "new york penal law": ("NY", "penal-law"),
        "d.c. code": ("DC", "code"),
        "dc code": ("DC", "code"),
        "usc": ("US", "usc"),
        "u.s.c": ("US", "usc"),
        "u.s.c.a": ("US", "usc"),
        "united states code": ("US", "usc"),
    }
)


def citation_alias_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = normalized.replace("§", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s+\.", ".", normalized)
    return normalized.strip(" .")


def lookup_citation_locator(
    code_text: str,
    *,
    prefix: Optional[str] = None,
    aliases: Mapping[str, tuple[str, str]] = CITATION_CODE_ALIASES,
) -> Optional[tuple[str, str]]:
    candidates = [code_text]
    if prefix:
        candidates.append(f"{prefix} {code_text}")
    for raw in candidates:
        key = citation_alias_key(raw)
        if key in aliases:
            return aliases[key]
        dotted = key.replace(" ", "")
        for alias, locator in aliases.items():
            if alias.replace(" ", "") == dotted or alias.replace(".", "") == key.replace(
                ".", ""
            ):
                return locator
    return None


def validate_citation_mention_record(self: Any) -> None:
    graph_error = self._graph_error_type
    citation_error = self._citation_error_type
    object.__setattr__(
        self,
        "kind",
        require_non_empty_str(
            self.kind,
            "kind",
            error_type=graph_error,
            maximum=64,
        ),
    )
    object.__setattr__(
        self,
        "mention_text",
        require_non_empty_str(
            self.mention_text,
            "mention_text",
            error_type=graph_error,
            maximum=512,
        ),
    )
    object.__setattr__(
        self,
        "start",
        require_non_negative_int(self.start, "start", error_type=graph_error),
    )
    object.__setattr__(
        self,
        "end",
        require_non_negative_int(self.end, "end", error_type=graph_error),
    )
    if self.end < self.start:
        raise citation_error("citation end must be >= start")
    object.__setattr__(
        self,
        "parser_version",
        require_non_empty_str(
            self.parser_version,
            "parser_version",
            error_type=graph_error,
            maximum=128,
        ),
    )


def citation_mention_to_dict(self: Any) -> dict[str, Any]:
    return {
        "code_family": self.code_family,
        "congress": self.congress,
        "end": self.end,
        "jurisdiction_code": self.jurisdiction_code,
        "kind": self.kind,
        "mention_text": self.mention_text,
        "number": self.number,
        "parser_version": self.parser_version,
        "section": self.section,
        "start": self.start,
        "title": self.title,
    }


def resolved_citation_to_dict(self: Any) -> dict[str, Any]:
    return {
        "mention": self.mention.to_dict(),
        "resolution_status": self.resolution_status.value,
        "span": self.span.to_dict(),
        "target_legal_id": self.target_legal_id,
        "target_node_key": self.target_node_key,
        "target_public_law_id": self.target_public_law_id,
    }


def drop_contained_mentions(mentions: list[Any]) -> list[Any]:
    kept: list[Any] = []
    for candidate in sorted(
        mentions,
        key=lambda item: (item.start, -(item.end - item.start)),
    ):
        contained = False
        for existing in kept:
            if existing.start <= candidate.start and candidate.end <= existing.end:
                if (existing.start, existing.end) != (candidate.start, candidate.end):
                    contained = True
                    break
                if existing.kind != "internal" and candidate.kind == "internal":
                    contained = True
                    break
        if not contained:
            kept.append(candidate)
    kept.sort(key=lambda item: (item.start, item.end, item.kind))
    return kept


def _normalized_extracted_section(
    value: Optional[str],
    normalize_section_token: Callable[[Any], str],
) -> Optional[str]:
    if not value:
        return None
    try:
        return normalize_section_token(value)
    except Exception:
        return value.strip()


def extract_citation_mentions(
    text: str,
    *,
    mention_type: type,
    parser_version: str,
    normalize_section_token: Callable[[Any], str],
    citation_error_type: type[Exception],
    default_jurisdiction: Optional[str] = None,
    default_code_family: Optional[str] = None,
) -> list[Any]:
    """Extract the shared citation grammar into adapter record types."""

    if not isinstance(text, str):
        raise citation_error_type("text must be a string")
    mentions: list[Any] = []

    for match in USC_CITATION_RE.finditer(text):
        mentions.append(
            mention_type(
                kind="usc",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                jurisdiction_code="US",
                code_family="usc",
                title=match.group("title"),
                section=_normalized_extracted_section(
                    match.group("section"), normalize_section_token
                ),
                parser_version=parser_version,
            )
        )

    for match in PUBLIC_LAW_RE.finditer(text):
        mentions.append(
            mention_type(
                kind="public_law",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                congress=str(int(match.group("congress"))),
                number=str(int(match.group("number"))),
                parser_version=parser_version,
            )
        )

    for match in SHORT_CODE_RE.finditer(text):
        locator = lookup_citation_locator(match.group("code"))
        jurisdiction, family = locator if locator else (None, None)
        mentions.append(
            mention_type(
                kind="state_code",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                jurisdiction_code=jurisdiction,
                code_family=family,
                section=_normalized_extracted_section(
                    match.group("section"), normalize_section_token
                ),
                parser_version=parser_version,
            )
        )

    for match in BLUEBOOK_RE.finditer(text):
        locator = lookup_citation_locator(
            match.group("code"),
            prefix=match.group("prefix"),
        )
        jurisdiction, family = locator if locator else (None, None)
        mentions.append(
            mention_type(
                kind="bluebook",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                jurisdiction_code=jurisdiction,
                code_family=family,
                section=_normalized_extracted_section(
                    match.group("section"), normalize_section_token
                ),
                parser_version=parser_version,
            )
        )

    for match in INTERNAL_SECTION_RE.finditer(text):
        mentions.append(
            mention_type(
                kind="internal",
                mention_text=match.group("mention"),
                start=match.start(),
                end=match.end(),
                jurisdiction_code=default_jurisdiction,
                code_family=default_code_family,
                section=_normalized_extracted_section(
                    match.group("section"), normalize_section_token
                ),
                parser_version=parser_version,
            )
        )

    return drop_contained_mentions(mentions)


def unresolved_citation_node_key(
    mention: Any,
    *,
    content_sha256: Callable[[Any], str],
) -> str:
    digest = content_sha256(mention.mention_text)[:16]
    jurisdiction = mention.jurisdiction_code or "?"
    family = mention.code_family or "?"
    section = mention.section or "?"
    return f"unresolved:{mention.kind}:{jurisdiction}:{family}:{section}:{digest}"


@dataclass(frozen=True)
class CitationResolverBindings:
    extract_mentions: Callable[..., list[Any]]
    source_span_type: type
    resolved_citation_type: type
    resolution_status: type
    public_law_node_key: Callable[[str], str]
    resolve_usc_candidates: Callable[[Any, set[str]], Sequence[str]]
    section_or_subsection_key: Callable[[str], str]
    unresolved_node_key: Callable[[Any], str]


def resolve_citations(
    text: str,
    *,
    bindings: CitationResolverBindings,
    known_legal_ids: Iterable[str] | None = None,
    locator_index: Mapping[tuple[str, str, str], Sequence[str]] | None = None,
    source_cid: Optional[str] = None,
    entry_cid: Optional[str] = None,
    default_jurisdiction: Optional[str] = None,
    default_code_family: Optional[str] = None,
    host_legal_id: Optional[str] = None,
    host_section: Optional[str] = None,
) -> list[Any]:
    """Resolve shared citation cases while delegating dataset identity seams."""

    known = {str(item) for item in (known_legal_ids or []) if item}
    locators = locator_index or {}
    resolved: list[Any] = []
    status_type = bindings.resolution_status
    for mention in bindings.extract_mentions(
        text,
        default_jurisdiction=default_jurisdiction,
        default_code_family=default_code_family,
    ):
        span = bindings.source_span_type(
            start=mention.start,
            end=mention.end,
            text=text[mention.start : mention.end],
            source_cid=source_cid,
            entry_cid=entry_cid,
            field="text",
        ).bind_to_source(text)

        if mention.kind == "public_law":
            if mention.congress and mention.number:
                public_law_id = (
                    f"pl:us:{int(mention.congress)}:{int(mention.number)}"
                )
                resolved.append(
                    bindings.resolved_citation_type(
                        mention=mention,
                        resolution_status=status_type.RESOLVED,
                        span=span,
                        target_public_law_id=public_law_id,
                        target_node_key=bindings.public_law_node_key(public_law_id),
                    )
                )
            continue

        if mention.kind == "internal" and host_section and mention.section == host_section:
            continue

        jurisdiction = mention.jurisdiction_code or default_jurisdiction
        family = mention.code_family or default_code_family
        section = mention.section
        matches: list[str] = []
        if jurisdiction and family and section:
            matches = list(locators.get((jurisdiction, family, section), ()))
        if not matches and mention.kind == "usc" and mention.title and mention.section:
            matches = list(bindings.resolve_usc_candidates(mention, known))

        unique: list[str] = []
        seen: set[str] = set()
        for item in matches:
            if item in known and item not in seen:
                unique.append(item)
                seen.add(item)
        if host_legal_id and unique and all(item == host_legal_id for item in unique):
            continue
        unique = [item for item in unique if item != host_legal_id]

        if len(unique) == 1:
            target = unique[0]
            resolved.append(
                bindings.resolved_citation_type(
                    mention=mention,
                    resolution_status=status_type.RESOLVED,
                    span=span,
                    target_legal_id=target,
                    target_node_key=bindings.section_or_subsection_key(target),
                )
            )
        else:
            status = status_type.AMBIGUOUS if len(unique) > 1 else status_type.UNRESOLVED
            resolved.append(
                bindings.resolved_citation_type(
                    mention=mention,
                    resolution_status=(
                        status
                        if status is status_type.AMBIGUOUS
                        else status_type.UNRESOLVED
                    ),
                    span=span,
                    target_legal_id=None,
                    target_node_key=bindings.unresolved_node_key(mention),
                )
            )
    return resolved


# ---------------------------------------------------------------------------
# Shared graph node/edge identity mechanics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphRecordBindings:
    node_type: type
    edge_type: type
    edge_class: type
    resolution_status: type
    source_span_type: type
    legal_edge_types: frozenset[Any]
    similarity_edge_types: frozenset[Any]
    span_required_edge_types: frozenset[Any]
    non_authoritative_authority: str
    node_identity_kind: str
    edge_identity_kind: str
    sha256_cid: Callable[[Mapping[str, Any]], str]
    graph_error_type: type[Exception]
    projection_error_type: type[Exception]
    source_span_error_type: type[Exception]
    citation_error_type: type[Exception]
    collision_error_type: type[Exception]


@dataclass(frozen=True)
class GraphProjectionBindings:
    """Dataset bindings required by deterministic projection normalization."""

    record_bindings: GraphRecordBindings
    required_coverage_node_types: tuple[str, ...]
    require_non_negative_int: Callable[[Any, str], int]


def validate_graph_node_record(self: Any) -> None:
    bindings: GraphRecordBindings = self._record_bindings
    node_type = bindings.node_type.coerce(self.node_type)
    object.__setattr__(self, "node_type", node_type)
    key = require_non_empty_str(
        self.node_key,
        "node_key",
        error_type=bindings.graph_error_type,
        maximum=768,
    )
    object.__setattr__(self, "node_key", key)
    object.__setattr__(
        self,
        "label",
        require_non_empty_str(
            self.label,
            "label",
            error_type=bindings.graph_error_type,
            maximum=1024,
        ),
    )
    if self.legal_id is not None:
        object.__setattr__(
            self,
            "legal_id",
            require_non_empty_str(
                self.legal_id,
                "legal_id",
                error_type=bindings.graph_error_type,
                maximum=768,
            ),
        )
        if node_type is bindings.node_type.UNRESOLVED_CITATION:
            raise bindings.citation_error_type(
                "unresolved citation nodes must not carry an invented legal_id"
            )
    if self.entry_cid is not None:
        object.__setattr__(
            self,
            "entry_cid",
            require_non_empty_str(
                self.entry_cid,
                "entry_cid",
                error_type=bindings.graph_error_type,
                maximum=256,
            ),
        )
    if not isinstance(self.payload, Mapping):
        raise bindings.projection_error_type("node payload must be a mapping")
    payload = dict(self.payload)
    object.__setattr__(self, "payload", MappingProxyType(payload))
    object.__setattr__(
        self,
        "ontology_version",
        require_non_empty_str(
            self.ontology_version,
            "ontology_version",
            error_type=bindings.graph_error_type,
        ),
    )
    object.__setattr__(
        self,
        "schema_version",
        require_non_empty_str(
            self.schema_version,
            "schema_version",
            error_type=bindings.graph_error_type,
        ),
    )
    identity = {
        "entry_cid": self.entry_cid,
        "label": self.label,
        "legal_id": self.legal_id,
        "node_key": self.node_key,
        "node_type": self.node_type.value,
        "ontology_version": self.ontology_version,
        "payload": payload,
        "schema_version": self.schema_version,
    }
    cid = self.node_cid or bindings.sha256_cid(
        {"kind": bindings.node_identity_kind, **identity}
    )
    object.__setattr__(self, "node_cid", cid)


def graph_node_to_dict(self: Any) -> dict[str, Any]:
    return {
        "entry_cid": self.entry_cid,
        "label": self.label,
        "legal_id": self.legal_id,
        "node_cid": self.node_cid,
        "node_key": self.node_key,
        "node_type": self.node_type.value,
        "ontology_version": self.ontology_version,
        "payload": dict(self.payload),
        "schema_version": self.schema_version,
    }


def validate_graph_edge_record(self: Any) -> None:
    bindings: GraphRecordBindings = self._record_bindings
    edge_type = bindings.edge_type.coerce(self.edge_type)
    edge_class = bindings.edge_class.coerce(self.edge_class)
    object.__setattr__(self, "edge_type", edge_type)
    object.__setattr__(self, "edge_class", edge_class)

    similarity_class = bindings.edge_class.SIMILARITY
    if edge_type in bindings.similarity_edge_types and edge_class is not similarity_class:
        raise bindings.collision_error_type(
            f"{edge_type.value} must use edge_class=similarity"
        )
    if edge_type in bindings.legal_edge_types and edge_class is similarity_class:
        raise bindings.collision_error_type(
            f"{edge_type.value} is a legal edge and cannot use similarity class"
        )
    if edge_type in bindings.similarity_edge_types:
        authority = None
        if isinstance(self.payload, Mapping):
            authority = self.payload.get("authority")
        if authority not in {None, bindings.non_authoritative_authority}:
            raise bindings.collision_error_type(
                f"{edge_type.value} cannot claim legal authority={authority!r}"
            )

    object.__setattr__(
        self,
        "source_node_cid",
        require_non_empty_str(
            self.source_node_cid,
            "source_node_cid",
            error_type=bindings.graph_error_type,
            maximum=256,
        ),
    )
    object.__setattr__(
        self,
        "target_node_cid",
        require_non_empty_str(
            self.target_node_cid,
            "target_node_cid",
            error_type=bindings.graph_error_type,
            maximum=256,
        ),
    )
    if self.source_span is not None and not isinstance(
        self.source_span, bindings.source_span_type
    ):
        raise bindings.source_span_error_type("source_span must be a SourceSpan")
    if edge_type in bindings.span_required_edge_types and self.source_span is None:
        raise bindings.source_span_error_type(
            f"{edge_type.value} requires a bound source_span"
        )
    if self.resolution_status is not None:
        object.__setattr__(
            self,
            "resolution_status",
            bindings.resolution_status.coerce(self.resolution_status),
        )
    if edge_type is bindings.edge_type.CITES_UNRESOLVED:
        if self.resolution_status not in {
            bindings.resolution_status.UNRESOLVED,
            bindings.resolution_status.AMBIGUOUS,
        }:
            raise bindings.citation_error_type(
                "CITES_UNRESOLVED requires unresolved or ambiguous status"
            )
    if self.weight is not None:
        if isinstance(self.weight, bool) or not isinstance(self.weight, (int, float)):
            raise bindings.projection_error_type("weight must be a number")
        object.__setattr__(self, "weight", float(self.weight))
    if not isinstance(self.payload, Mapping):
        raise bindings.projection_error_type("edge payload must be a mapping")
    payload = dict(self.payload)
    if edge_type in bindings.similarity_edge_types:
        payload.setdefault("authority", bindings.non_authoritative_authority)
        if payload.get("authority") != bindings.non_authoritative_authority:
            raise bindings.collision_error_type(
                f"{edge_type.value} payload.authority must be "
                f"{bindings.non_authoritative_authority}"
            )
    object.__setattr__(self, "payload", MappingProxyType(payload))
    object.__setattr__(
        self,
        "ontology_version",
        require_non_empty_str(
            self.ontology_version,
            "ontology_version",
            error_type=bindings.graph_error_type,
        ),
    )
    object.__setattr__(
        self,
        "schema_version",
        require_non_empty_str(
            self.schema_version,
            "schema_version",
            error_type=bindings.graph_error_type,
        ),
    )
    identity = {
        "edge_class": self.edge_class.value,
        "edge_type": self.edge_type.value,
        "ontology_version": self.ontology_version,
        "payload": payload,
        "resolution_status": (
            self.resolution_status.value if self.resolution_status else None
        ),
        "schema_version": self.schema_version,
        "source_node_cid": self.source_node_cid,
        "source_span": self.source_span.to_dict() if self.source_span else None,
        "target_node_cid": self.target_node_cid,
        "weight": self.weight,
    }
    cid = self.edge_cid or bindings.sha256_cid(
        {"kind": bindings.edge_identity_kind, **identity}
    )
    object.__setattr__(self, "edge_cid", cid)


def graph_edge_is_legal(self: Any) -> bool:
    return self.edge_type in self._record_bindings.legal_edge_types


def graph_edge_is_similarity(self: Any) -> bool:
    return self.edge_type in self._record_bindings.similarity_edge_types


def graph_edge_to_dict(self: Any) -> dict[str, Any]:
    return {
        "edge_cid": self.edge_cid,
        "edge_class": self.edge_class.value,
        "edge_type": self.edge_type.value,
        "ontology_version": self.ontology_version,
        "payload": dict(self.payload),
        "resolution_status": (
            self.resolution_status.value if self.resolution_status else None
        ),
        "schema_version": self.schema_version,
        "source_node_cid": self.source_node_cid,
        "source_span": self.source_span.to_dict() if self.source_span else None,
        "target_node_cid": self.target_node_cid,
        "weight": self.weight,
    }


# ---------------------------------------------------------------------------
# Shared graph projection normalization and inspection
# ---------------------------------------------------------------------------


def validate_graph_projection(self: Any) -> None:
    bindings: GraphProjectionBindings = self._projection_bindings
    records = bindings.record_bindings
    nodes = tuple(
        sorted(
            self.nodes,
            key=lambda item: (item.node_type.value, item.node_key, item.node_cid),
        )
    )
    edges = tuple(
        sorted(
            self.edges,
            key=lambda item: (
                item.edge_type.value,
                item.source_node_cid,
                item.target_node_cid,
                item.edge_cid,
            ),
        )
    )
    if len({item.node_cid for item in nodes}) != len(nodes):
        raise records.projection_error_type("duplicate node_cid in projection")
    if len({item.edge_cid for item in edges}) != len(edges):
        raise records.projection_error_type("duplicate edge_cid in projection")
    node_cids = {item.node_cid for item in nodes}
    for edge in edges:
        if (
            edge.source_node_cid not in node_cids
            or edge.target_node_cid not in node_cids
        ):
            raise records.projection_error_type(
                f"dangling edge {edge.edge_cid}: missing endpoint"
            )
    legal_count = sum(1 for item in edges if item.is_legal)
    similarity_count = sum(1 for item in edges if item.is_similarity)
    unresolved_count = sum(
        1
        for item in edges
        if item.edge_type is records.edge_type.CITES_UNRESOLVED
        or item.resolution_status
        in {
            records.resolution_status.UNRESOLVED,
            records.resolution_status.AMBIGUOUS,
        }
    )
    object.__setattr__(self, "nodes", nodes)
    object.__setattr__(self, "edges", edges)
    object.__setattr__(self, "legal_edge_count", legal_count)
    object.__setattr__(self, "similarity_edge_count", similarity_count)
    object.__setattr__(self, "unresolved_count", unresolved_count)
    object.__setattr__(
        self,
        "skipped_row_count",
        bindings.require_non_negative_int(
            self.skipped_row_count,
            "skipped_row_count",
        ),
    )
    root = {
        "citation_parser_version": self.citation_parser_version,
        "edge_cids": [item.edge_cid for item in edges],
        "node_cids": [item.node_cid for item in nodes],
        "ontology_version": self.ontology_version,
        "schema_version": self.schema_version,
        "skipped_row_count": self.skipped_row_count,
    }
    object.__setattr__(
        self,
        "graph_cid",
        self.graph_cid or records.sha256_cid(root),
    )


def graph_projection_node_by_key(self: Any) -> dict[str, Any]:
    return {item.node_key: item for item in self.nodes}


def graph_projection_node_by_cid(self: Any) -> dict[str, Any]:
    return {item.node_cid: item for item in self.nodes}


def graph_projection_legal_edges(self: Any) -> tuple[Any, ...]:
    return tuple(item for item in self.edges if item.is_legal)


def graph_projection_similarity_edges(self: Any) -> tuple[Any, ...]:
    return tuple(item for item in self.edges if item.is_similarity)


def graph_projection_coverage_node_types(self: Any) -> set[str]:
    return {item.node_type.value for item in self.nodes}


def graph_projection_missing_coverage_node_types(self: Any) -> list[str]:
    bindings: GraphProjectionBindings = self._projection_bindings
    present = self.coverage_node_types()
    return [
        name
        for name in bindings.required_coverage_node_types
        if name not in present
    ]


def assert_graph_projection_semantics_disjoint(self: Any) -> None:
    records = self._projection_bindings.record_bindings
    for edge in self.edges:
        if edge.is_legal and edge.is_similarity:
            raise records.collision_error_type(
                f"edge {edge.edge_cid} is both legal and similarity"
            )
        if edge.is_legal and edge.edge_class is records.edge_class.SIMILARITY:
            raise records.collision_error_type(
                f"legal edge {edge.edge_type.value} classified as similarity"
            )
        if edge.is_similarity and edge.edge_class is not records.edge_class.SIMILARITY:
            raise records.collision_error_type(
                f"similarity edge {edge.edge_type.value} not classified as similarity"
            )
        if (
            edge.is_similarity
            and edge.payload.get("authority")
            != records.non_authoritative_authority
        ):
            raise records.collision_error_type(
                f"similarity edge {edge.edge_type.value} missing "
                "non-authoritative label"
            )


def assert_graph_projection_coverage(self: Any) -> None:
    missing = self.missing_coverage_node_types()
    if missing:
        raise self._projection_bindings.record_bindings.projection_error_type(
            "projection is missing required coverage node types: "
            f"{missing}"
        )


def graph_projection_to_dict(self: Any) -> dict[str, Any]:
    return {
        "citation_parser_version": self.citation_parser_version,
        "edges": [item.to_dict() for item in self.edges],
        "graph_cid": self.graph_cid,
        "legal_edge_count": self.legal_edge_count,
        "nodes": [item.to_dict() for item in self.nodes],
        "ontology_version": self.ontology_version,
        "schema_version": self.schema_version,
        "similarity_edge_count": self.similarity_edge_count,
        "skipped_row_count": self.skipped_row_count,
        "unresolved_count": self.unresolved_count,
    }


# ---------------------------------------------------------------------------
# Shared structure, citation, and amendment projection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LegalGraphProjectorBindings:
    node_type: type
    edge_type: type
    resolution_status: type
    source_span_type: type
    node_factory: type
    edge_factory: type
    jurisdiction_names: Mapping[str, str]
    public_law_node_type: Any
    public_law_key_prefix: str
    version_edge_type: Any
    canonical_json_dumps: Callable[[Any], str]
    content_sha256: Callable[[Any], str]
    strip_subsection_qualifier: Callable[[str], str]
    section_or_subsection_key: Callable[[str], str]
    unresolved_node_key: Callable[[Any], str]
    resolve_citations: Callable[..., list[Any]]
    projection_error_type: type[Exception]


class LegalGraphProjectorCore:
    """Shared production projection algorithms with explicit identity seams."""

    _projector_bindings: LegalGraphProjectorBindings

    def _project_structure(
        self,
        nodes: MutableMapping[str, Any],
        edges: list[Any],
        row: Any,
    ) -> None:
        bindings = self._projector_bindings
        node_type = bindings.node_type
        edge_type = bindings.edge_type
        jurisdiction_key = f"jurisdiction:{row.jurisdiction_code}"
        jurisdiction_label = bindings.jurisdiction_names.get(
            row.jurisdiction_code, row.jurisdiction_code
        )
        self._ensure_node(
            nodes,
            node_type=node_type.JURISDICTION,
            node_key=jurisdiction_key,
            label=jurisdiction_label,
            payload={
                "jurisdiction_code": row.jurisdiction_code,
                "jurisdiction_name": jurisdiction_label,
            },
        )

        code_key = f"code:{row.jurisdiction_code}:{row.code_family}"
        self._ensure_node(
            nodes,
            node_type=node_type.CODE,
            node_key=code_key,
            label=f"{row.jurisdiction_code} {row.code_family}",
            payload={
                "code_family": row.code_family,
                "jurisdiction_code": row.jurisdiction_code,
            },
        )
        edges.append(self._edge(edge_type.CONTAINS, nodes[jurisdiction_key], nodes[code_key]))

        parent_key = code_key
        if row.title:
            title_key = f"title:{row.jurisdiction_code}:{row.code_family}:{row.title}"
            self._ensure_node(
                nodes,
                node_type=node_type.TITLE,
                node_key=title_key,
                label=f"Title {row.title}",
                payload={
                    "code_family": row.code_family,
                    "jurisdiction_code": row.jurisdiction_code,
                    "title": row.title,
                },
            )
            edges.append(self._edge(edge_type.CONTAINS, nodes[parent_key], nodes[title_key]))
            parent_key = title_key

        if row.chapter:
            chapter_key = (
                f"chapter:{row.jurisdiction_code}:{row.code_family}:"
                f"{row.title or '_'}:{row.chapter}"
            )
            self._ensure_node(
                nodes,
                node_type=node_type.CHAPTER,
                node_key=chapter_key,
                label=f"Chapter {row.chapter}",
                payload={
                    "chapter": row.chapter,
                    "code_family": row.code_family,
                    "jurisdiction_code": row.jurisdiction_code,
                    "title": row.title,
                },
            )
            edges.append(
                self._edge(edge_type.CONTAINS, nodes[parent_key], nodes[chapter_key])
            )
            parent_key = chapter_key

        section_legal_id = bindings.strip_subsection_qualifier(row.legal_id)
        section_key = f"section:{section_legal_id}"
        self._ensure_node(
            nodes,
            node_type=node_type.SECTION,
            node_key=section_key,
            label=row.heading or section_legal_id,
            legal_id=section_legal_id,
            entry_cid=row.entry_cid if not row.subsection else None,
            payload={
                "chapter": row.chapter,
                "code_family": row.code_family,
                "configuration": row.configuration,
                "jurisdiction_code": row.jurisdiction_code,
                "section": row.section,
                "title": row.title,
            },
        )
        edges.append(self._edge(edge_type.CONTAINS, nodes[parent_key], nodes[section_key]))

        leaf_key = section_key
        if row.subsection:
            subsection_key = f"subsection:{row.legal_id}"
            self._ensure_node(
                nodes,
                node_type=node_type.SUBSECTION,
                node_key=subsection_key,
                label=f"{row.heading or row.section}({row.subsection})",
                legal_id=row.legal_id,
                entry_cid=row.entry_cid,
                payload={
                    "chapter": row.chapter,
                    "code_family": row.code_family,
                    "configuration": row.configuration,
                    "jurisdiction_code": row.jurisdiction_code,
                    "section": row.section,
                    "subsection": row.subsection,
                    "title": row.title,
                },
            )
            edges.append(
                self._edge(
                    edge_type.CONTAINS,
                    nodes[section_key],
                    nodes[subsection_key],
                )
            )
            leaf_key = subsection_key

        if row.source_cid:
            source_key = f"source:{row.source_cid}"
            self._ensure_node(
                nodes,
                node_type=node_type.SOURCE,
                node_key=source_key,
                label=row.official_source_url or row.source_cid,
                payload={
                    "official_source_url": row.official_source_url,
                    "source_cid": row.source_cid,
                },
            )
            edges.append(
                self._edge(edge_type.HAS_SOURCE, nodes[leaf_key], nodes[source_key])
            )

        edition_key = f"edition:{row.edition}"
        self._ensure_node(
            nodes,
            node_type=node_type.EDITION,
            node_key=edition_key,
            label=row.edition,
            payload={"edition": row.edition},
        )
        edges.append(
            self._edge(edge_type.HAS_EDITION, nodes[leaf_key], nodes[edition_key])
        )
        if bindings.version_edge_type is not None:
            edges.append(
                self._edge(
                    bindings.version_edge_type,
                    nodes[leaf_key],
                    nodes[edition_key],
                )
            )

        provenance_digest = bindings.content_sha256(
            bindings.canonical_json_dumps(
                {
                    "acquisition_receipt_cid": row.acquisition_receipt_cid,
                    "entry_cid": row.entry_cid,
                    "observed_at": row.observed_at,
                    "rights_receipt_cid": row.rights_receipt_cid,
                    "source_cid": row.source_cid,
                }
            )
        )
        provenance_key = f"provenance:{provenance_digest}"
        self._ensure_node(
            nodes,
            node_type=node_type.PROVENANCE,
            node_key=provenance_key,
            label=row.acquisition_receipt_cid or row.entry_cid,
            payload={
                "acquisition_receipt_cid": row.acquisition_receipt_cid,
                "entry_cid": row.entry_cid,
                "observed_at": row.observed_at,
                "rights_receipt_cid": row.rights_receipt_cid,
                "source_cid": row.source_cid,
            },
        )
        edges.append(
            self._edge(
                edge_type.HAS_PROVENANCE,
                nodes[leaf_key],
                nodes[provenance_key],
            )
        )

    def _project_citations(
        self,
        nodes: MutableMapping[str, Any],
        edges: list[Any],
        row: Any,
        *,
        known_legal_ids: set[str],
        locator_index: Mapping[tuple[str, str, str], Sequence[str]],
    ) -> None:
        bindings = self._projector_bindings
        node_type = bindings.node_type
        edge_type = bindings.edge_type
        resolution = bindings.resolution_status
        leaf_key = (
            f"subsection:{row.legal_id}"
            if row.subsection
            else f"section:{bindings.strip_subsection_qualifier(row.legal_id)}"
        )
        source_node = nodes[leaf_key]
        citations = bindings.resolve_citations(
            row.text,
            known_legal_ids=known_legal_ids,
            locator_index=locator_index,
            source_cid=row.source_cid,
            entry_cid=row.entry_cid,
            default_jurisdiction=row.jurisdiction_code,
            default_code_family=row.code_family,
            host_legal_id=row.legal_id,
            host_section=row.section,
        )
        for citation in citations:
            if citation.mention.kind == "public_law":
                public_law_id = citation.target_public_law_id
                if not public_law_id:
                    continue
                public_law_key = f"{bindings.public_law_key_prefix}:{public_law_id}"
                self._ensure_node(
                    nodes,
                    node_type=bindings.public_law_node_type,
                    node_key=public_law_key,
                    label=citation.mention.mention_text,
                    payload={
                        "congress": citation.mention.congress,
                        "number": citation.mention.number,
                        "public_law_id": public_law_id,
                    },
                )
                edges.append(
                    self._edge(
                        edge_type.CODIFIES,
                        nodes[public_law_key],
                        source_node,
                        source_span=citation.span,
                        resolution_status=resolution.RESOLVED,
                        payload={
                            "mention": citation.mention.mention_text,
                            "parser_version": citation.mention.parser_version,
                        },
                    )
                )
                edges.append(
                    self._edge(
                        edge_type.DERIVED_FROM,
                        source_node,
                        nodes[public_law_key],
                        source_span=citation.span,
                        payload={
                            "mention": citation.mention.mention_text,
                            "parser_version": citation.mention.parser_version,
                        },
                    )
                )
                continue

            if citation.resolution_status is resolution.RESOLVED and citation.target_legal_id:
                target_key = citation.target_node_key or bindings.section_or_subsection_key(
                    citation.target_legal_id
                )
                if target_key not in nodes:
                    target_key = f"section:{citation.target_legal_id}"
                if target_key not in nodes:
                    continue
                citation_key = "citation:" + bindings.content_sha256(
                    bindings.canonical_json_dumps(
                        {
                            "end": citation.span.end,
                            "mention": citation.mention.mention_text,
                            "source": row.legal_id,
                            "start": citation.span.start,
                            "target": citation.target_legal_id,
                        }
                    )
                )[:32]
                self._ensure_node(
                    nodes,
                    node_type=node_type.CITATION,
                    node_key=citation_key,
                    label=citation.mention.mention_text,
                    payload={
                        "mention_text": citation.mention.mention_text,
                        "parser_version": citation.mention.parser_version,
                        "resolution_status": resolution.RESOLVED.value,
                        "target_legal_id": citation.target_legal_id,
                    },
                )
                edges.append(
                    self._edge(
                        edge_type.HAS_CITATION,
                        source_node,
                        nodes[citation_key],
                        source_span=citation.span,
                        resolution_status=resolution.RESOLVED,
                        payload={
                            "mention": citation.mention.mention_text,
                            "parser_version": citation.mention.parser_version,
                        },
                    )
                )
                edges.append(
                    self._edge(
                        edge_type.CITES,
                        source_node,
                        nodes[target_key],
                        source_span=citation.span,
                        resolution_status=resolution.RESOLVED,
                        payload={
                            "mention": citation.mention.mention_text,
                            "parser_version": citation.mention.parser_version,
                        },
                    )
                )
            else:
                unresolved_key = citation.target_node_key or bindings.unresolved_node_key(
                    citation.mention
                )
                self._ensure_node(
                    nodes,
                    node_type=node_type.UNRESOLVED_CITATION,
                    node_key=unresolved_key,
                    label=citation.mention.mention_text,
                    payload={
                        "code_family": citation.mention.code_family,
                        "jurisdiction_code": citation.mention.jurisdiction_code,
                        "mention_text": citation.mention.mention_text,
                        "parser_version": citation.mention.parser_version,
                        "resolution_status": resolution.UNRESOLVED.value,
                        "section": citation.mention.section,
                        "title": citation.mention.title,
                    },
                )
                edges.append(
                    self._edge(
                        edge_type.CITES_UNRESOLVED,
                        source_node,
                        nodes[unresolved_key],
                        source_span=citation.span,
                        resolution_status=(
                            citation.resolution_status
                            if citation.resolution_status is not resolution.RESOLVED
                            else resolution.UNRESOLVED
                        ),
                        payload={
                            "mention": citation.mention.mention_text,
                            "parser_version": citation.mention.parser_version,
                            "resolution_status": (
                                citation.resolution_status.value
                                if citation.resolution_status
                                else resolution.UNRESOLVED.value
                            ),
                        },
                    )
                )

        for raw in row.cites:
            target = self._coerce_target_legal_id(raw, row=row)
            if not target or target == row.legal_id:
                continue
            target_key = bindings.section_or_subsection_key(target)
            if target_key not in nodes:
                target_key = f"section:{target}"
            if target_key not in nodes:
                continue
            span = self._synthetic_field_span(row, field_name="cites", mention=str(raw))
            edges.append(
                self._edge(
                    edge_type.CITES,
                    source_node,
                    nodes[target_key],
                    source_span=span,
                    resolution_status=resolution.RESOLVED,
                    payload={"origin": "explicit_field", "target": target},
                )
            )

        for public_law_raw in row.public_laws:
            public_law_id = self._normalize_public_law_id(public_law_raw)
            public_law_key = f"{bindings.public_law_key_prefix}:{public_law_id}"
            self._ensure_node(
                nodes,
                node_type=bindings.public_law_node_type,
                node_key=public_law_key,
                label=str(public_law_raw),
                payload={"public_law_id": public_law_id},
            )
            span = self._synthetic_field_span(
                row,
                field_name="public_laws",
                mention=str(public_law_raw),
            )
            edges.append(
                self._edge(
                    edge_type.CODIFIES,
                    nodes[public_law_key],
                    source_node,
                    source_span=span,
                    payload={
                        "origin": "explicit_field",
                        "public_law_id": public_law_id,
                    },
                )
            )

    def _project_amendments(
        self,
        nodes: MutableMapping[str, Any],
        edges: list[Any],
        row: Any,
    ) -> None:
        bindings = self._projector_bindings
        node_type = bindings.node_type
        edge_type = bindings.edge_type
        resolution = bindings.resolution_status
        leaf_key = (
            f"subsection:{row.legal_id}"
            if row.subsection
            else f"section:{bindings.strip_subsection_qualifier(row.legal_id)}"
        )
        source_node = nodes[leaf_key]
        for target_raw, projected_edge_type in (
            *((item, edge_type.AMENDS) for item in row.amends),
            *((item, edge_type.REPEALS) for item in row.repeals),
            *((item, edge_type.TRANSFERS) for item in row.transfers),
        ):
            target = self._coerce_target_legal_id(target_raw, row=row)
            if not target:
                continue
            target_key = bindings.section_or_subsection_key(target)
            if target_key not in nodes:
                target_key = f"section:{target}"
            if target_key not in nodes:
                self._ensure_node(
                    nodes,
                    node_type=node_type.SECTION,
                    node_key=target_key,
                    label=target,
                    legal_id=target,
                    payload={"placeholder": True, "target": target},
                )
            span = self._synthetic_field_span(
                row,
                field_name=projected_edge_type.value.lower(),
                mention=str(target_raw),
            )
            if projected_edge_type is edge_type.AMENDS:
                amendment_key = f"amendment:{row.legal_id}:{target}"
                self._ensure_node(
                    nodes,
                    node_type=node_type.AMENDMENT,
                    node_key=amendment_key,
                    label=f"{row.legal_id} amends {target}",
                    payload={
                        "source_legal_id": row.legal_id,
                        "target_legal_id": target,
                    },
                )
                edges.append(
                    self._edge(
                        edge_type.HAS_AMENDMENT,
                        source_node,
                        nodes[amendment_key],
                        source_span=span,
                        resolution_status=resolution.RESOLVED,
                        payload={"origin": "explicit_field", "target": target},
                    )
                )
                edges.append(
                    self._edge(
                        edge_type.AMENDS,
                        nodes[amendment_key],
                        nodes[target_key],
                        source_span=span,
                        resolution_status=resolution.RESOLVED,
                        payload={"origin": "explicit_field", "target": target},
                    )
                )
            edges.append(
                self._edge(
                    projected_edge_type,
                    source_node,
                    nodes[target_key],
                    source_span=span,
                    resolution_status=resolution.RESOLVED,
                    payload={"origin": "explicit_field", "target": target},
                )
            )

    def _ensure_node(
        self,
        nodes: MutableMapping[str, Any],
        *,
        node_type: Any,
        node_key: str,
        label: str,
        legal_id: Optional[str] = None,
        entry_cid: Optional[str] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        existing = nodes.get(node_key)
        if existing is not None:
            return existing
        node = self._projector_bindings.node_factory(
            node_type=node_type,
            node_key=node_key,
            label=label,
            legal_id=legal_id,
            entry_cid=entry_cid,
            payload=dict(payload or {}),
        )
        nodes[node_key] = node
        return node

    def _edge(
        self,
        edge_type: Any,
        source: Any,
        target: Any,
        *,
        source_span: Any = None,
        resolution_status: Any = None,
        weight: Optional[float] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        edge_class = self.ontology.validate_edge(
            edge_type,
            source.node_type,
            target.node_type,
        )
        return self._projector_bindings.edge_factory(
            edge_type=edge_type,
            source_node_cid=source.node_cid,
            target_node_cid=target.node_cid,
            edge_class=edge_class,
            source_span=source_span,
            resolution_status=resolution_status,
            weight=weight,
            payload=dict(payload or {}),
        )

    def _normalize_public_law_id(self, value: str) -> str:
        text = str(value).strip()
        if text.startswith("pl:us:"):
            return text
        match = re.search(r"(\d+)\s*[-–—]\s*(\d+)", text)
        if match:
            return f"pl:us:{int(match.group(1))}:{int(match.group(2))}"
        raise self._projector_bindings.projection_error_type(
            f"cannot normalize public law id: {value!r}"
        )

    def _synthetic_field_span(
        self,
        row: Any,
        *,
        field_name: str,
        mention: str,
    ) -> Any:
        source_span_type = self._projector_bindings.source_span_type
        if mention and mention in row.text:
            return source_span_type.from_occurrence(
                row.text,
                mention,
                source_cid=row.source_cid,
                entry_cid=row.entry_cid,
                field="text",
            )
        virtual = mention
        return source_span_type(
            start=0,
            end=len(virtual),
            text=virtual,
            source_cid=row.source_cid,
            entry_cid=row.entry_cid,
            field=field_name,
        )


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "AUTHORIZES_RELEASE",
    "CITATION_CODE_ALIASES",
    "PERFORMS_NETWORK_IO",
    "CitationResolverBindings",
    "GraphProjectionBindings",
    "GraphRecordBindings",
    "LegalGraphOntologyBindings",
    "LegalGraphProjectorBindings",
    "LegalGraphProjectorCore",
    "assert_graph_projection_coverage",
    "assert_graph_projection_semantics_disjoint",
    "assert_legal_similarity_disjoint",
    "bind_source_span",
    "citation_alias_key",
    "citation_mention_to_dict",
    "coerce_graph_enum",
    "drop_contained_mentions",
    "extract_citation_mentions",
    "graph_edge_is_legal",
    "graph_edge_is_similarity",
    "graph_edge_to_dict",
    "graph_node_to_dict",
    "graph_ontology_edge_class_for",
    "graph_ontology_is_legal_edge",
    "graph_ontology_is_similarity_edge",
    "graph_ontology_to_dict",
    "graph_projection_coverage_node_types",
    "graph_projection_legal_edges",
    "graph_projection_missing_coverage_node_types",
    "graph_projection_node_by_cid",
    "graph_projection_node_by_key",
    "graph_projection_similarity_edges",
    "graph_projection_to_dict",
    "legal_edge_direction_allowed",
    "lookup_citation_locator",
    "optional_str",
    "require_non_empty_str",
    "require_non_negative_int",
    "resolve_citations",
    "resolved_citation_to_dict",
    "sha256_cid",
    "source_span_from_mapping",
    "source_span_from_occurrence",
    "source_span_to_dict",
    "unresolved_citation_node_key",
    "validate_citation_mention_record",
    "validate_graph_edge_record",
    "validate_graph_node_record",
    "validate_graph_ontology",
    "validate_graph_ontology_edge",
    "validate_graph_projection",
    "validate_source_span_record",
]
