"""Bounded Georgia OCGA discovery on the state-designated Lexis site.

The Georgia General Assembly links its ``Georgia Code`` navigation item to the
free Lexis public-access container.  The container states that it is made
available by the Georgia Code Revision Commission on behalf of the General
Assembly and maintained by LexisNexis.  Its TOC service exposes the complete
53-title inventory and zero-price section document locators.

This module is deliberately not part of the default Georgia scrape path:

* live access requires ``GEORGIA_LEXIS_PUBLIC_ACCESS_ENABLE=1``;
* discovery is bounded and never clicks an agreement or CAPTCHA control;
* sign-in, CAPTCHA, robot-validation, bootstrap, and partial TOC responses fail
  closed;
* TOC locators are inventory evidence, not statute bodies; and
* statute-body admission is disabled until a separate live document receipt
  authenticates the exact response bytes and transport metadata.

The live document route currently presents Lexis robot validation in automated
sessions.  Archive or recovery copies must not be relabelled as live official
material by this adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from .base_scraper import NormalizedStatute

ENABLE_ENV = "GEORGIA_LEXIS_PUBLIC_ACCESS_ENABLE"
HEADLESS_ENV = "GEORGIA_LEXIS_PUBLIC_ACCESS_HEADLESS"
OFFICIAL_GGA_REFERRER = "https://www.legis.ga.gov/"
PUBLIC_ENTRY_URL = "https://www.lexisnexis.com/hottopics/gacode/"
ADVANCE_ORIGIN = "https://advance.lexis.com"
PUBLIC_CONTAINER_CONFIG = (
    "00JAAzZDgzNzU2ZC05MDA0LTRmMDItYjkzMS0xOGY3MjE3OWNlODIK"
    "AFBvZENhdGFsb2fcIFfJnJ2IC8XZi1AYM4Ne"
)
PUBLIC_CONTAINER_URL = f"{ADVANCE_ORIGIN}/container?config={PUBLIC_CONTAINER_CONFIG}"

# Values exposed by the live Georgia public-access container on 2026-08-24.
# They are kept together so drift is observable and testable.
TOC_POD_ID = "6gf59kk"
TOC_ENDPOINT_PATH = f"/r/tocprovider/{TOC_POD_ID}/toc/{TOC_POD_ID}"
TOC_ROOT_ID = TOC_POD_ID
TOC_URN_PATH = "/shared/tableofcontents/urn:contentItem:63RH-PW33-CH1B-T4TR-00008-00"
TOC_SEARCH_CONFIG = (
    "00JABlN2Q2OTIwYi1kMjQwLTQxMWEtOWM1YS00MzUwY2MzYjQ5ZTAK"
    "AFBvZENhdGFsb2eiEwC2ZWq2J6k0Uwbdk8jZ"
)
TOC_SEARCH_MFID = "1000516"
TOC_SEARCH_FILTER = "MTA5MTIwMw"

EXPECTED_TITLE_NUMBERS: tuple[str, ...] = tuple(str(number) for number in range(1, 54))
MAX_LIVE_EXPANSIONS = 24
MAX_DOCUMENT_LINKS = 100

OFFICIAL_DELEGATED_METADATA: dict[str, Any] = {
    "source_kind": "official_delegated_georgia_lexis_public_access",
    "source_authority_class": "official",
    "official_delegated_publisher": "LexisNexis",
    "official_delegating_authority": (
        "Georgia Code Revision Commission on behalf of the Georgia General Assembly"
    ),
    "full_corpus_admissible": False,
}

_NODE_ID_RE = re.compile(r"^[A-Z0-9]{2,64}$")
_TITLE_RE = re.compile(r"^TITLE\s+(?P<number>\d{1,3})\b", re.IGNORECASE)
_CHAPTER_RE = re.compile(r"^CHAPTER\s+(?P<number>[0-9A-Za-z.-]+)\b", re.IGNORECASE)
_SECTION_COMPONENT = r"[0-9]+[A-Za-z]?(?:\.[0-9A-Za-z]+)*"
_SECTION_NUMBER = rf"[1-9]\d?[A-Za-z]?-{_SECTION_COMPONENT}-{_SECTION_COMPONENT}"
_SECTION_INPUT_RE = re.compile(rf"^{_SECTION_NUMBER}$")
_SECTION_HEADING_RE = re.compile(
    rf"(?im)^\s*(?:(?:O\.?C\.?G\.?A\.?|Ga\.?\s+Code\s+Ann\.?)\s*)?"
    rf"(?:§\s*)?(?P<number>{_SECTION_NUMBER})"
    r"(?:\.\s+|\s+[\-–—:]\s+)(?P<heading>[^\n]{1,240})\s*$"
)
_DOCUMENT_PATH_RE = re.compile(
    r"^/shared/document/statutes-legislation/urn:contentItem:[A-Za-z0-9:-]+$",
    re.IGNORECASE,
)
_DELEGATION_RE = re.compile(
    r"Georgia\s+Code\s+Revision\s+Commission.*?"
    r"on\s+behalf\s+of\s+the\s+Georgia\s+General\s+Assembly.*?LexisNexis",
    re.IGNORECASE | re.DOTALL,
)
_CAPTCHA_RE = re.compile(
    r"human\s+verification|confirm\s+you\s+are\s+human|complete\s+the\s+security\s+check|"
    r"captcha(?:\s+validation)?|aws-amzn-waf",
    re.IGNORECASE,
)
_ROBOT_RE = re.compile(r"robot\s*validation|robotvalidation", re.IGNORECASE)
_SIGN_IN_RE = re.compile(
    r"sign\s+in\s+to\s+continue|sign\s+in\s*\|\s*lexisnexis|signin\.lexisnexis\.com",
    re.IGNORECASE,
)
_BOOTSTRAP_RE = re.compile(
    r"LNDOMENV|Browser redirect to the intended destination", re.IGNORECASE
)
_CONSENT_RE = re.compile(
    r"\bI\s+Agree\b.*?(?:terms|conditions)|(?:terms|conditions).*?\bI\s+Agree\b",
    re.IGNORECASE | re.DOTALL,
)
_SEARCH_RESULT_RE = re.compile(
    r"data-id=[\"']sr\d+[\"']|data-action=[\"']publichitsteaser[\"']|"
    r"\bResults\s+for\s*:",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

# Raw HTML/JSON parsers intentionally produce unverified value objects.  Only
# this module's live, source-scoped browser path attaches this process-local
# capability after validating the final URL and response structure.  A caller
# cannot make a directly constructed or fixture-parsed object authoritative by
# setting a public boolean field.
_LIVE_EVIDENCE_CAPABILITY = object()


@dataclass(frozen=True)
class GeorgiaLexisTocNode:
    """Normalized node from the Lexis TOC JSON or rendered DOM."""

    node_id: str
    title: str
    level: int | None
    node_path: str
    can_expand: bool
    can_open: bool
    has_children: bool
    expanded: bool
    populated: bool
    link_href: str
    subscribed: bool | None
    purchase_required: bool | None
    list_price: float | None
    net_price: float | None
    pricing_present: bool = False
    currency_code: str = ""
    usage_type_code: str = ""
    document_status: str = ""
    expansion_closed: bool = False
    evidence_source_url: str = ""
    evidence_observed_at: str = ""
    evidence_sha256: str = ""
    _evidence_capability: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def title_number(self) -> str | None:
        match = _TITLE_RE.match(self.title.strip())
        return str(int(match.group("number"))) if match else None

    @property
    def chapter_number(self) -> str | None:
        match = _CHAPTER_RE.match(self.title.strip())
        return match.group("number") if match else None

    @property
    def section_number(self) -> str | None:
        match = re.match(
            rf"^(?P<number>{_SECTION_NUMBER})(?:\.|\s|$)", self.title.strip()
        )
        return match.group("number") if match else None

    @property
    def public_document_available(self) -> bool:
        return bool(
            self.link_href
            and is_lexis_document_url(self.link_href)
            and self.subscribed is True
            and self.pricing_present
            and self.purchase_required is False
            and self.list_price == 0
            and self.net_price == 0
            and self.currency_code.upper() == "USD"
            and self.usage_type_code.lower() == "subscription"
            and self.document_status.lower() == "available"
        )

    @property
    def evidence_verified(self) -> bool:
        return bool(
            self._evidence_capability is _LIVE_EVIDENCE_CAPABILITY
            and bootstrap_container_url_matches(self.evidence_source_url)
            and _observed_at_valid(self.evidence_observed_at)
            and _SHA256_RE.fullmatch(self.evidence_sha256)
            and _toc_node_shape_valid(self)
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("_evidence_capability", None)
        value.update(
            {
                "title_number": self.title_number,
                "chapter_number": self.chapter_number,
                "section_number": self.section_number,
                "public_document_available": self.public_document_available,
                "evidence_verified": self.evidence_verified,
                "source_authority_class": "official"
                if self.evidence_verified
                else "unverified",
                "full_corpus_admissible": False,
            }
        )
        return value


@dataclass(frozen=True)
class GeorgiaLexisDiscoveryResult:
    """Bounded live-discovery result; never a full-corpus admission receipt."""

    status: str
    final_url: str
    delegation_verified: bool
    nodes: tuple[GeorgiaLexisTocNode, ...]
    expanded_node_ids: tuple[str, ...]
    diagnostics: tuple[str, ...]
    observed_at: str = ""
    root_rendered_sha256: str = ""
    patch_response_sha256: tuple[tuple[str, str], ...] = ()

    @property
    def frontier(self) -> dict[str, Any]:
        return georgia_lexis_frontier(
            self.nodes,
            expanded_node_ids=self.expanded_node_ids,
            delegation_verified=self.delegation_verified,
        )

    def to_dict(self) -> dict[str, Any]:
        authority_verified = bool(
            self.status == "official_toc"
            and self.delegation_verified
            and bootstrap_container_url_matches(self.final_url)
            and self.nodes
            and all(node.evidence_verified for node in self.nodes)
        )
        return {
            "status": self.status,
            "entry_url": PUBLIC_ENTRY_URL,
            "bootstrap_url": PUBLIC_CONTAINER_URL,
            "final_url": self.final_url,
            "observed_at": self.observed_at,
            "root_rendered_sha256": self.root_rendered_sha256,
            "patch_response_sha256": dict(self.patch_response_sha256),
            "delegation_verified": self.delegation_verified,
            "nodes": [node.to_dict() for node in self.nodes],
            "expanded_node_ids": list(self.expanded_node_ids),
            "diagnostics": list(self.diagnostics),
            "frontier": self.frontier,
            **_authority_metadata(authority_verified),
        }


@dataclass(frozen=True)
class GeorgiaLexisSearchHit:
    """One public TOC-search hit; its excerpt is never a statute body."""

    position: int
    document_urn: str
    title: str
    citation: str
    hierarchy: str
    excerpt: str
    truncated: bool
    evidence_source_url: str = ""
    evidence_observed_at: str = ""
    evidence_sha256: str = ""
    _evidence_capability: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def section_number(self) -> str | None:
        match = re.match(
            rf"^(?P<number>{_SECTION_NUMBER})(?:\.|\s|$)", self.title.strip()
        )
        return match.group("number") if match else None

    @property
    def document_url(self) -> str:
        path = f"/shared/document/statutes-legislation/{self.document_urn}"
        return urljoin(ADVANCE_ORIGIN, path) if is_lexis_document_url(path) else ""

    @property
    def evidence_verified(self) -> bool:
        return bool(
            self._evidence_capability is _LIVE_EVIDENCE_CAPABILITY
            and self.section_number
            and section_search_url_matches(
                self.evidence_source_url, self.section_number
            )
            and _observed_at_valid(self.evidence_observed_at)
            and _SHA256_RE.fullmatch(self.evidence_sha256)
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("_evidence_capability", None)
        return {
            **value,
            "section_number": self.section_number,
            "document_url": self.document_url,
            "source_kind": (
                "official_delegated_georgia_lexis_toc_search_excerpt"
                if self.evidence_verified
                else "unverified_georgia_lexis_toc_search_excerpt"
            ),
            "source_authority_class": "official"
            if self.evidence_verified
            else "unverified",
            "official_delegated_publisher": "LexisNexis",
            "evidence_verified": self.evidence_verified,
            "body_admissible": False,
            "full_corpus_admissible": False,
        }


@dataclass(frozen=True)
class GeorgiaLexisSearchResult:
    """One bounded live TOC search; excerpts are locator evidence only."""

    status: str
    section_number: str
    search_url: str
    final_url: str
    delegation_verified: bool
    hits: tuple[GeorgiaLexisSearchHit, ...]
    diagnostics: tuple[str, ...]
    observed_at: str = ""
    bootstrap_rendered_sha256: str = ""
    search_rendered_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        authority_verified = bool(
            self.status == "toc_search_excerpt"
            and self.delegation_verified
            and section_search_url_matches(self.search_url, self.section_number)
            and section_search_url_matches(self.final_url, self.section_number)
            and self.hits
            and all(hit.evidence_verified for hit in self.hits)
        )
        return {
            "status": self.status,
            "section_number": self.section_number,
            "entry_url": PUBLIC_ENTRY_URL,
            "bootstrap_url": PUBLIC_CONTAINER_URL,
            "search_url": self.search_url,
            "final_url": self.final_url,
            "delegation_verified": self.delegation_verified,
            "hits": [hit.to_dict() for hit in self.hits],
            "diagnostics": list(self.diagnostics),
            "observed_at": self.observed_at,
            "bootstrap_rendered_sha256": self.bootstrap_rendered_sha256,
            "search_rendered_sha256": self.search_rendered_sha256,
            "evidence_scope": "toc_search_truncated_excerpt",
            "body_admissible": False,
            **_authority_metadata(authority_verified),
        }


def _env_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _authority_metadata(verified: bool) -> dict[str, Any]:
    if verified:
        return dict(OFFICIAL_DELEGATED_METADATA)
    return {
        "source_kind": "unverified_georgia_lexis_public_access",
        "source_authority_class": "unverified",
        "intended_delegated_publisher": "LexisNexis",
        "full_corpus_admissible": False,
    }


def _observed_at_valid(value: object) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None


def _exact_advance_origin(parsed: Any) -> bool:
    try:
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "advance.lexis.com"
        and parsed.username is None
        and parsed.password is None
        and port is None
        and parsed.netloc.lower() == "advance.lexis.com"
    )


def _query_exact_with_session_extras(
    query: Mapping[str, list[str]],
    expected: Mapping[str, list[str]],
) -> bool:
    allowed = set(expected) | {"crid", "prid"}
    if not set(query).issubset(allowed):
        return False
    if any(query.get(key) != value for key, value in expected.items()):
        return False
    return all(
        len(query.get(key, [])) == 1
        and bool(re.fullmatch(r"[A-Za-z0-9-]{1,128}", query[key][0]))
        for key in set(query) - set(expected)
    )


def bootstrap_container_url_matches(url: object) -> bool:
    """Require the exact public-access container, allowing only session IDs."""

    parsed = urlparse(str(url or ""))
    if not (
        _exact_advance_origin(parsed)
        and parsed.path == "/container"
        and not parsed.params
        and not parsed.fragment
    ):
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    return _query_exact_with_session_extras(
        query,
        {"config": [PUBLIC_CONTAINER_CONFIG]},
    )


def georgia_lexis_enabled() -> bool:
    """Return whether the operator explicitly enabled live Lexis access."""

    return _env_enabled(ENABLE_ENV, default=False)


def normalize_section_number(value: object) -> str:
    section = str(value or "").strip().replace("§", "").strip()
    if not _SECTION_INPUT_RE.fullmatch(section):
        raise ValueError(f"invalid Georgia section number: {value!r}")
    title = int(section.split("-", 1)[0])
    if title not in range(1, 54):
        raise ValueError(f"Georgia title is outside 1-53: {value!r}")
    return section


def build_section_search_url(section_number: object) -> str:
    """Build the public OCGA TOC-search URL for one validated section."""

    section = normalize_section_number(section_number)
    query = urlencode(
        {
            "config": TOC_SEARCH_CONFIG,
            "pdcontextvalue": "statutes-legislation",
            "pdfilterstring": TOC_SEARCH_FILTER,
            "pdmfid": TOC_SEARCH_MFID,
            "pdsearchdisplaytext": "Official Code of Georgia Annotated",
            "pdsearchterms": "",
            "pdtocfullpath": TOC_URN_PATH,
            "pdtocsearchoption": "docsonly",
            "pdtocsearchterm": section,
            "pdtypeofsearch": "TOCSearchDoc",
        }
    )
    return f"{ADVANCE_ORIGIN}/container?{query}"


def toc_expand_request(node_id: object) -> tuple[str, dict[str, Any]]:
    """Return the same-origin Lexis TOC PATCH endpoint and bounded payload."""

    normalized = str(node_id or "").strip()
    if not _NODE_ID_RE.fullmatch(normalized):
        raise ValueError(f"invalid Lexis TOC node id: {node_id!r}")
    return (
        urljoin(ADVANCE_ORIGIN, TOC_ENDPOINT_PATH),
        {
            "id": TOC_ROOT_ID,
            "props": {
                "action": "expand",
                "items": [{"fieldName": "nodeId", "value": normalized}],
            },
        },
    )


def classify_lexis_page(text_or_html: str, *, final_url: str = "") -> str:
    """Classify the rendered page before any body is trusted."""

    body = str(text_or_html or "")
    host = (urlparse(str(final_url or "")).hostname or "").lower()
    if _ROBOT_RE.search(body):
        return "blocked_robot_validation"
    if _CAPTCHA_RE.search(body):
        return "blocked_captcha"
    if host == "signin.lexisnexis.com" or _SIGN_IN_RE.search(body):
        return "blocked_sign_in"
    if _CONSENT_RE.search(body):
        return "consent_required"
    if _BOOTSTRAP_RE.search(body):
        return "session_bootstrap"
    if _SEARCH_RESULT_RE.search(body):
        return "toc_search_excerpt"
    if _DELEGATION_RE.search(body) and re.search(
        r"Official\s+Code\s+of\s+Georgia\s+Annotated", body, re.IGNORECASE
    ):
        return (
            "official_toc"
            if bootstrap_container_url_matches(final_url)
            else "unexpected_source"
        )
    if _SECTION_HEADING_RE.search(body):
        return "statute_document"
    return "unexpected"


def delegation_banner_present(text_or_html: str) -> bool:
    return bool(_DELEGATION_RE.search(str(text_or_html or "")))


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _as_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _toc_node_shape_valid(node: GeorgiaLexisTocNode) -> bool:
    if not _NODE_ID_RE.fullmatch(node.node_id):
        return False
    parts = [part for part in node.node_path.split("/") if part]
    if (
        len(parts) < 2
        or parts[0] != "ROOT"
        or parts[-1] != node.node_id
        or any(not _NODE_ID_RE.fullmatch(part) for part in parts[1:])
        or node.level != len(parts) - 1
    ):
        return False
    if node.title_number is not None and node.level != 1:
        return False
    if node.chapter_number is not None and not (
        node.level == 2 or ((node.level or 0) >= 3 and bool(node.link_href))
    ):
        return False
    if node.section_number is not None and (node.level or 0) < 3:
        return False
    return not node.link_href or is_lexis_document_url(node.link_href)


def _bind_live_toc_nodes(
    nodes: Iterable[GeorgiaLexisTocNode],
    *,
    source_url: str,
    observed_at: str,
    receipt_sha256: str,
) -> list[GeorgiaLexisTocNode]:
    """Attach non-forgeable-in-normal-use provenance after live validation."""

    if not (
        bootstrap_container_url_matches(source_url)
        and _observed_at_valid(observed_at)
        and _SHA256_RE.fullmatch(str(receipt_sha256 or ""))
    ):
        return []
    bound: list[GeorgiaLexisTocNode] = []
    for node in nodes:
        if not _toc_node_shape_valid(node):
            continue
        verified_node = replace(
            node,
            evidence_source_url=source_url,
            evidence_observed_at=observed_at,
            evidence_sha256=receipt_sha256,
        )
        object.__setattr__(
            verified_node,
            "_evidence_capability",
            _LIVE_EVIDENCE_CAPABILITY,
        )
        bound.append(verified_node)
    return bound


def _mark_live_expansion_closed(
    node: GeorgiaLexisTocNode,
) -> GeorgiaLexisTocNode | None:
    if not node.evidence_verified or not (node.can_expand or node.has_children):
        return None
    closed = replace(node, expansion_closed=True)
    object.__setattr__(closed, "_evidence_capability", _LIVE_EVIDENCE_CAPABILITY)
    return closed


def _node_from_mapping(value: Mapping[str, Any]) -> GeorgiaLexisTocNode | None:
    props = value.get("props")
    if not isinstance(props, Mapping):
        return None
    title = str(props.get("linktemplatetitle") or props.get("title") or "").strip()
    node_id = str(value.get("id") or props.get("nodeid") or "").strip()
    if not node_id or not title:
        return None
    if not any(
        key in props
        for key in ("nodepath", "canexpand", "canopen", "linkhref", "haschildren")
    ):
        return None
    data = value.get("data") if isinstance(value.get("data"), Mapping) else {}
    pricing = (
        props.get("tocpricing") if isinstance(props.get("tocpricing"), Mapping) else {}
    )
    node = GeorgiaLexisTocNode(
        node_id=node_id,
        title=title,
        level=_as_int(props.get("level")),
        node_path=str(props.get("nodepath") or ""),
        can_expand=_as_bool(props.get("canexpand")),
        can_open=_as_bool(props.get("canopen")),
        has_children=_as_bool(props.get("haschildren")),
        expanded=_as_bool(data.get("expanded")),
        populated=_as_bool(data.get("populated")),
        link_href=str(props.get("linkhref") or "").strip(),
        subscribed=_as_optional_bool(props.get("subscribed")),
        purchase_required=_as_optional_bool(pricing.get("purchaserequired")),
        list_price=_as_float(pricing.get("listprice")),
        net_price=_as_float(pricing.get("netprice")),
        pricing_present=bool(pricing),
        currency_code=str(pricing.get("currencycode") or ""),
        usage_type_code=str(pricing.get("usagetypecode") or ""),
        document_status=str(pricing.get("documentstatus") or ""),
    )
    return node if _toc_node_shape_valid(node) else None


def _parse_toc_expansion_payload(
    payload: object,
    *,
    parent: GeorgiaLexisTocNode,
) -> tuple[list[GeorgiaLexisTocNode], str]:
    """Validate one complete direct-child collection for an expanded node."""

    if not parent.evidence_verified or not (parent.can_expand or parent.has_children):
        return [], "parent is not a verified expandable TOC node"
    if not isinstance(payload, Mapping):
        return [], "TOC expansion payload was not an object"
    props = payload.get("props")
    if isinstance(props, Mapping) and props.get("error"):
        return [], "TOC expansion payload contained an error"
    collections = payload.get("collections")
    container = (
        collections.get("toccontainer") if isinstance(collections, Mapping) else None
    )
    nested = container.get("collections") if isinstance(container, Mapping) else None
    raw_nodes = nested.get("tocnodes") if isinstance(nested, Mapping) else None
    if not isinstance(raw_nodes, Sequence) or isinstance(
        raw_nodes, (str, bytes, bytearray)
    ):
        return [], "TOC expansion payload lacked the exact tocnodes collection"
    if not raw_nodes:
        return [], "TOC expansion returned an empty child collection"

    expected_level = (parent.level or 0) + 1
    expected_prefix = f"{parent.node_path}/"
    children: list[GeorgiaLexisTocNode] = []
    seen: set[str] = set()
    for raw in raw_nodes:
        if not isinstance(raw, Mapping):
            return [], "TOC expansion contained a non-object child"
        child = _node_from_mapping(raw)
        if child is None:
            return [], "TOC expansion contained a malformed child"
        if (
            child.node_id in seen
            or child.level != expected_level
            or child.node_path != f"{expected_prefix}{child.node_id}"
        ):
            return (
                [],
                "TOC expansion child was duplicate or outside the requested branch",
            )
        seen.add(child.node_id)
        children.append(child)
    return children, ""


def parse_toc_payload(payload: object) -> list[GeorgiaLexisTocNode]:
    """Recursively normalize TOC nodes from root or expansion JSON."""

    out: list[GeorgiaLexisTocNode] = []
    seen: set[str] = set()

    def _walk(value: object) -> None:
        if isinstance(value, Mapping):
            node = _node_from_mapping(value)
            if node is not None and node.node_id not in seen:
                seen.add(node.node_id)
                out.append(node)
            for child in value.values():
                _walk(child)
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for child in value:
                _walk(child)

    _walk(payload)
    return out


def parse_toc_dom_rows(rows: Iterable[Mapping[str, Any]]) -> list[GeorgiaLexisTocNode]:
    """Normalize attributes captured from rendered ``li.js-node`` elements."""

    out: list[GeorgiaLexisTocNode] = []
    seen: set[str] = set()
    for row in rows:
        node_id = str(row.get("nodeid") or row.get("data-nodeid") or "").strip()
        title = str(row.get("title") or row.get("data-title") or "").strip()
        if not node_id or not title or node_id in seen:
            continue
        node = GeorgiaLexisTocNode(
            node_id=node_id,
            title=title,
            level=_as_int(row.get("level") or row.get("data-level")),
            node_path=str(row.get("nodepath") or row.get("data-nodepath") or ""),
            can_expand=_as_bool(row.get("canexpand") or row.get("data-canexpand")),
            can_open=_as_bool(row.get("canopen") or row.get("data-canopen")),
            has_children=_as_bool(
                row.get("haschildren") or row.get("data-haschildren")
            ),
            expanded=_as_bool(row.get("expanded") or row.get("aria-expanded")),
            populated=_as_bool(row.get("populated") or row.get("data-populated")),
            link_href=str(
                row.get("docfullpath")
                or row.get("data-docfullpath")
                or row.get("linkhref")
                or ""
            ).strip(),
            subscribed=_as_optional_bool(
                row.get("subscribed") or row.get("data-subscribed")
            ),
            purchase_required=_as_optional_bool(
                row.get("purchaserequired") or row.get("data-purchaserequired")
            ),
            list_price=_as_float(row.get("listprice") or row.get("data-listprice")),
            net_price=_as_float(row.get("netprice") or row.get("data-netprice")),
            pricing_present=all(
                key in row
                for key in (
                    "listprice",
                    "netprice",
                    "purchaserequired",
                )
            )
            or all(
                key in row
                for key in (
                    "data-listprice",
                    "data-netprice",
                    "data-purchaserequired",
                )
            ),
            currency_code=str(
                row.get("currencycode") or row.get("data-currencycode") or ""
            ),
            usage_type_code=str(
                row.get("usagetypecode") or row.get("data-usagetypecode") or ""
            ),
            document_status=str(
                row.get("documentstatus") or row.get("data-documentstatus") or ""
            ),
        )
        if not _toc_node_shape_valid(node):
            continue
        seen.add(node_id)
        out.append(node)
    return out


def _dedupe_nodes(nodes: Iterable[GeorgiaLexisTocNode]) -> list[GeorgiaLexisTocNode]:
    by_id: dict[str, GeorgiaLexisTocNode] = {}
    for node in nodes:
        if not _toc_node_shape_valid(node):
            continue
        previous = by_id.get(node.node_id)
        previous_score = (
            int(previous.evidence_verified) * 8
            + int(previous.expansion_closed) * 4
            + int(bool(previous.link_href)) * 2
            + int(previous.populated)
            if previous is not None
            else -1
        )
        node_score = (
            int(node.evidence_verified) * 8
            + int(node.expansion_closed) * 4
            + int(bool(node.link_href)) * 2
            + int(node.populated)
        )
        if previous is None or node_score > previous_score:
            by_id[node.node_id] = node
    return sorted(
        by_id.values(),
        key=lambda item: (
            item.level if item.level is not None else 999,
            item.node_path,
            item.node_id,
        ),
    )


def is_lexis_document_url(value: object) -> bool:
    parsed = urlparse(urljoin(ADVANCE_ORIGIN, str(value or "").strip()))
    return bool(
        _exact_advance_origin(parsed)
        and not parsed.query
        and not parsed.params
        and not parsed.fragment
        and _DOCUMENT_PATH_RE.fullmatch(parsed.path or "")
    )


def document_urls_from_nodes(
    nodes: Iterable[GeorgiaLexisTocNode], *, limit: int = MAX_DOCUMENT_LINKS
) -> list[str]:
    limit_n = max(1, min(int(limit), MAX_DOCUMENT_LINKS))
    out: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        if not (
            node.evidence_verified
            and node.section_number is not None
            and node.public_document_available
            and is_lexis_document_url(node.link_href)
        ):
            continue
        url = urljoin(ADVANCE_ORIGIN, node.link_href)
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= limit_n:
            break
    return out


def parse_toc_search_results(
    html: str,
    *,
    expected_section: object = "",
    source_url: str = "",
    limit: int = 25,
) -> list[GeorgiaLexisSearchHit]:
    """Parse exactly scoped search locators as unverified smoke evidence.

    This pure parser cannot establish live provenance.  Its hits remain
    unverified and therefore cannot authorize statute-body admission.
    """

    if not expected_section:
        return []
    try:
        wanted = normalize_section_number(expected_section)
    except ValueError:
        return []
    if not section_search_url_matches(source_url, wanted):
        return []
    if classify_lexis_page(html, final_url=source_url) != "toc_search_excerpt":
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    limit_n = max(1, min(int(limit), MAX_DOCUMENT_LINKS))
    hits: list[GeorgiaLexisSearchHit] = []
    seen: set[str] = set()
    for position, row in enumerate(soup.select("li[data-id^='sr']"), start=1):
        document_input = row.select_one("input[data-docid]")
        document_urn = str(
            document_input.get("data-docid") if document_input is not None else ""
        ).strip()
        if not re.fullmatch(r"urn:contentItem:[A-Za-z0-9:-]+", document_urn):
            continue
        if document_urn in seen:
            continue
        title_node = row.select_one("h2.doc-title") or row.select_one(
            "[data-action='title']"
        )
        title = _WS_RE.sub(
            " ", title_node.get_text(" ", strip=True) if title_node is not None else ""
        ).strip()
        metadata = [
            _WS_RE.sub(" ", node.get_text(" ", strip=True)).strip()
            for node in row.select(".metadata span")
        ]
        citation = next((value for value in metadata if "O.C.G.A." in value), "")
        article = row.select_one("article")
        paragraphs = (
            [
                _WS_RE.sub(" ", node.get_text(" ", strip=True)).strip()
                for node in article.select("p")
            ]
            if article is not None
            else []
        )
        hierarchy = paragraphs[0] if paragraphs else ""
        excerpt = next(
            (
                value
                for value in paragraphs[1:]
                if value and not value.startswith("...") and not value.startswith("…")
            ),
            paragraphs[1] if len(paragraphs) > 1 else "",
        )
        hit = GeorgiaLexisSearchHit(
            position=position,
            document_urn=document_urn,
            title=title,
            citation=citation,
            hierarchy=hierarchy,
            excerpt=excerpt,
            truncated=bool(re.search(r"(?:\.\.\.|…)\s*$", excerpt)),
        )
        if wanted and hit.section_number != wanted:
            continue
        if not any(
            re.search(
                r"Official\s+Code\s+of\s+Georgia\s+Annotated", value, re.IGNORECASE
            )
            for value in metadata
        ):
            continue
        if not re.search(
            rf"O\.?C\.?G\.?A\.?\s*§?\s*{re.escape(wanted)}\b",
            citation,
            re.IGNORECASE,
        ):
            continue
        title_number = wanted.split("-", 1)[0]
        if not re.search(
            rf"\bTITLE\s+{re.escape(title_number)}\b", hierarchy, re.IGNORECASE
        ):
            continue
        if not hit.document_url:
            continue
        seen.add(document_urn)
        hits.append(hit)
        if len(hits) >= limit_n:
            break
    return hits


def georgia_lexis_frontier(
    nodes: Iterable[GeorgiaLexisTocNode],
    *,
    expanded_node_ids: Iterable[str] = (),
    delegation_verified: bool = False,
) -> dict[str, Any]:
    """Report title-inventory closure separately from body/frontier closure."""

    normalized = _dedupe_nodes(nodes)
    title_nodes = [
        node
        for node in normalized
        if node.title_number
        and node.level == 1
        and node.node_path == f"/ROOT/{node.node_id}"
    ]
    title_numbers = [str(node.title_number) for node in title_nodes]
    counts = {number: title_numbers.count(number) for number in set(title_numbers)}
    expected = set(EXPECTED_TITLE_NUMBERS)
    discovered = set(title_numbers)
    expansion_receipts = {
        node.node_id
        for node in normalized
        if node.evidence_verified and node.expansion_closed
    }
    expanded = {str(value) for value in expanded_node_ids} & expansion_receipts
    unresolved = sorted(
        node.node_id
        for node in normalized
        if (node.can_expand or node.has_children) and node.node_id not in expanded
    )
    document_urls = document_urls_from_nodes(normalized)
    title_inventory_closed = bool(
        delegation_verified
        and discovered == expected
        and all(count == 1 for count in counts.values())
        and all(node.evidence_verified for node in title_nodes)
    )
    return {
        "method": "official_delegated_lexis_toc",
        "expected_title_count": len(EXPECTED_TITLE_NUMBERS),
        "discovered_title_count": len(title_numbers),
        "verified_title_count": sum(node.evidence_verified for node in title_nodes),
        "discovered_title_numbers": sorted(discovered, key=int),
        "missing_title_numbers": sorted(expected - discovered, key=int),
        "extra_title_numbers": sorted(discovered - expected, key=int),
        "duplicate_title_numbers": sorted(
            (number for number, count in counts.items() if count > 1), key=int
        ),
        "delegation_verified": bool(delegation_verified),
        "title_inventory_closed": title_inventory_closed,
        "expanded_node_ids": sorted(expanded),
        "unresolved_expandable_node_ids": unresolved,
        "discovered_document_count": len(document_urls),
        "document_body_count": 0,
        "body_frontier_closed": False,
        "frontier_closed": False,
        "full_corpus_admissible": False,
    }


def parse_georgia_lexis_document_html(
    html: str,
    *,
    source_url: str,
    expected_section: object,
    discovery_evidence: GeorgiaLexisTocNode | GeorgiaLexisSearchHit | None = None,
    code_name: str = "Official Code of Georgia Annotated",
) -> NormalizedStatute | None:
    """Refuse body admission without a live, byte-bound transport receipt.

    TOC nodes and search hits authenticate only document locators. They do not
    authenticate caller-supplied HTML, its final response URL, HTTP status,
    content type, observation time, or byte hash. The public document route is
    currently blocked by Lexis robot validation in automated sessions, and this
    adapter deliberately has no document-fetch or bypass path. Keep returning
    ``None`` until a separate process-bound live document receipt exists.
    """

    return None


async def discover_live_georgia_lexis_toc(
    *,
    expand_node_ids: Sequence[str] = (),
    timeout_ms: int = 60000,
) -> GeorgiaLexisDiscoveryResult:
    """Discover a bounded live TOC branch with an ephemeral browser session.

    The function never clicks consent, CAPTCHA, sign-in, or document links.
    Explicit node expansion uses the public container's same-origin TOC
    service and is capped at :data:`MAX_LIVE_EXPANSIONS`.
    """

    observed_at = datetime.now(UTC).isoformat()
    if not georgia_lexis_enabled():
        return GeorgiaLexisDiscoveryResult(
            status="disabled",
            final_url="",
            delegation_verified=False,
            nodes=(),
            expanded_node_ids=(),
            diagnostics=(f"set {ENABLE_ENV}=1 to enable bounded live discovery",),
            observed_at=observed_at,
        )
    requested = [str(value or "").strip() for value in expand_node_ids]
    if len(requested) > MAX_LIVE_EXPANSIONS:
        raise ValueError(
            f"Georgia Lexis expansion limit is {MAX_LIVE_EXPANSIONS}, got {len(requested)}"
        )
    for node_id in requested:
        if not _NODE_ID_RE.fullmatch(node_id):
            raise ValueError(f"invalid Lexis TOC node id: {node_id!r}")

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError as exc:
        return GeorgiaLexisDiscoveryResult(
            status="unavailable",
            final_url="",
            delegation_verified=False,
            nodes=(),
            expanded_node_ids=(),
            diagnostics=(f"playwright unavailable: {exc}",),
            observed_at=observed_at,
        )

    nodes: list[GeorgiaLexisTocNode] = []
    expanded: list[str] = []
    diagnostics: list[str] = []
    final_url = ""
    delegation_verified = False
    status = "unavailable"
    root_rendered_sha256 = ""
    patch_response_sha256: list[tuple[str, str]] = []
    timeout = max(5000, min(int(timeout_ms), 120000))
    user_agent = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=_env_enabled(HEADLESS_ENV, default=True),
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                context = await browser.new_context(
                    user_agent=user_agent, locale="en-US"
                )
                page = await context.new_page()
                await page.goto(
                    PUBLIC_CONTAINER_URL,
                    wait_until="domcontentloaded",
                    timeout=timeout,
                    referer=OFFICIAL_GGA_REFERRER,
                )
                try:
                    await page.wait_for_selector(
                        "li.js-node", timeout=min(timeout, 20000)
                    )
                except PlaywrightTimeoutError:
                    diagnostics.append(
                        "TOC nodes did not render before the bounded timeout"
                    )
                final_url = str(page.url or "")
                body_text = str(await page.locator("body").inner_text() or "")
                page_html = str(await page.content() or "")
                root_rendered_sha256 = hashlib.sha256(
                    page_html.encode("utf-8")
                ).hexdigest()
                status = classify_lexis_page(body_text, final_url=final_url)
                if status == "unexpected":
                    status = classify_lexis_page(page_html, final_url=final_url)
                source_scoped = bootstrap_container_url_matches(final_url)
                banner_verified = delegation_banner_present(body_text)
                delegation_verified = bool(source_scoped and banner_verified)
                if not source_scoped:
                    status = "unexpected_source"
                    diagnostics.append(
                        "live page left the exact Georgia public-access container"
                    )
                if status != "official_toc" or not delegation_verified:
                    diagnostics.append(f"live page classified as {status}")
                    return GeorgiaLexisDiscoveryResult(
                        status=status,
                        final_url=final_url,
                        delegation_verified=delegation_verified,
                        nodes=(),
                        expanded_node_ids=(),
                        diagnostics=tuple(diagnostics),
                        observed_at=observed_at,
                        root_rendered_sha256=root_rendered_sha256,
                    )

                dom_rows = await page.evaluate(
                    """
                    () => Array.from(document.querySelectorAll('li.js-node')).map(el => ({
                      nodeid: el.getAttribute('data-nodeid') || '',
                      nodepath: el.getAttribute('data-nodepath') || '',
                      level: el.getAttribute('data-level') || '',
                      title: el.getAttribute('data-title') || '',
                      canexpand: el.getAttribute('data-canexpand') || '',
                      canopen: el.getAttribute('data-canopen') || '',
                      haschildren: el.getAttribute('data-haschildren') || '',
                      populated: el.getAttribute('data-populated') || '',
                      docfullpath: el.getAttribute('data-docfullpath') || '',
                      subscribed: el.getAttribute('data-subscribed') || '',
                      expanded: el.getAttribute('aria-expanded') || ''
                    }))
                    """
                )
                root_nodes = parse_toc_dom_rows(dom_rows or [])
                bound_root_nodes = _bind_live_toc_nodes(
                    root_nodes,
                    source_url=final_url,
                    observed_at=observed_at,
                    receipt_sha256=root_rendered_sha256,
                )
                if (
                    not isinstance(dom_rows, Sequence)
                    or isinstance(dom_rows, (str, bytes, bytearray))
                    or not bound_root_nodes
                    or len(root_nodes) != len(dom_rows)
                    or len(bound_root_nodes) != len(root_nodes)
                ):
                    diagnostics.append(
                        "rendered TOC nodes failed source or shape validation"
                    )
                    status = "invalid_toc"
                    return GeorgiaLexisDiscoveryResult(
                        status=status,
                        final_url=final_url,
                        delegation_verified=delegation_verified,
                        nodes=(),
                        expanded_node_ids=(),
                        diagnostics=tuple(diagnostics),
                        observed_at=observed_at,
                        root_rendered_sha256=root_rendered_sha256,
                    )
                nodes.extend(bound_root_nodes)
                known_nodes = {node.node_id: node for node in nodes}

                for node_id in requested:
                    parent = known_nodes.get(node_id)
                    if parent is None:
                        diagnostics.append(f"refused unknown TOC node id {node_id}")
                        status = "partial_toc"
                        break
                    endpoint, patch_body = toc_expand_request(node_id)
                    result = await page.evaluate(
                        """
                        async ({endpoint, patchBody}) => {
                          const headers = {
                            'Accept': 'application/json, text/javascript, */*; q=0.01',
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                          };
                          const requestId = new URL(window.location.href).searchParams.get('crid');
                          if (requestId) headers['X-LN-CurrentRequestId'] = requestId;
                          const response = await fetch(endpoint, {
                            method: 'PATCH',
                            credentials: 'same-origin',
                            headers,
                            body: JSON.stringify(patchBody)
                          });
                          return {
                            status: response.status,
                            contentType: response.headers.get('content-type') || '',
                            text: await response.text()
                          };
                        }
                        """,
                        {"endpoint": endpoint, "patchBody": patch_body},
                    )
                    if not isinstance(result, Mapping):
                        diagnostics.append(
                            f"TOC expansion {node_id} returned no receipt"
                        )
                        status = "partial_toc"
                        break
                    if int(result.get("status") or 0) != 200:
                        diagnostics.append(
                            f"TOC expansion {node_id} returned HTTP {result.get('status')}"
                        )
                        status = "partial_toc"
                        break
                    content_type = str(result.get("contentType") or "").lower()
                    if "json" not in content_type:
                        diagnostics.append(f"TOC expansion {node_id} was not JSON")
                        status = "partial_toc"
                        break
                    response_text = str(result.get("text") or "")
                    response_sha256 = hashlib.sha256(
                        response_text.encode("utf-8")
                    ).hexdigest()
                    patch_response_sha256.append((node_id, response_sha256))
                    try:
                        payload = json.loads(response_text)
                    except (TypeError, ValueError):
                        diagnostics.append(f"TOC expansion {node_id} had invalid JSON")
                        status = "partial_toc"
                        break
                    child_nodes, expansion_error = _parse_toc_expansion_payload(
                        payload,
                        parent=parent,
                    )
                    if expansion_error:
                        diagnostics.append(
                            f"TOC expansion {node_id}: {expansion_error}"
                        )
                        status = "partial_toc"
                        break
                    bound_child_nodes = _bind_live_toc_nodes(
                        child_nodes,
                        source_url=final_url,
                        observed_at=observed_at,
                        receipt_sha256=response_sha256,
                    )
                    closed_parent = _mark_live_expansion_closed(parent)
                    if closed_parent is None or len(bound_child_nodes) != len(
                        child_nodes
                    ):
                        diagnostics.append(
                            f"TOC expansion {node_id} failed provenance binding"
                        )
                        status = "partial_toc"
                        break
                    nodes = [
                        closed_parent if node.node_id == node_id else node
                        for node in nodes
                    ]
                    known_nodes[node_id] = closed_parent
                    nodes.extend(bound_child_nodes)
                    expanded.append(node_id)
                    known_nodes.update(
                        {node.node_id: node for node in bound_child_nodes}
                    )
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 - network/browser boundary must fail closed
        diagnostics.append(f"live discovery failed: {type(exc).__name__}: {exc}")
        status = "unavailable"

    return GeorgiaLexisDiscoveryResult(
        status=status,
        final_url=final_url,
        delegation_verified=delegation_verified,
        nodes=tuple(_dedupe_nodes(nodes)),
        expanded_node_ids=tuple(expanded),
        diagnostics=tuple(diagnostics),
        observed_at=observed_at,
        root_rendered_sha256=root_rendered_sha256,
        patch_response_sha256=tuple(patch_response_sha256),
    )


def section_search_url_matches(url: str, section_number: object) -> bool:
    """Validate that a URL targets only the requested official OCGA TOC."""

    try:
        section = normalize_section_number(section_number)
    except ValueError:
        return False
    parsed = urlparse(str(url or ""))
    if not (
        _exact_advance_origin(parsed)
        and parsed.path == "/container"
        and not parsed.params
        and not parsed.fragment
    ):
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    expected = parse_qs(
        urlparse(build_section_search_url(section)).query,
        keep_blank_values=True,
    )
    return _query_exact_with_session_extras(query, expected)
