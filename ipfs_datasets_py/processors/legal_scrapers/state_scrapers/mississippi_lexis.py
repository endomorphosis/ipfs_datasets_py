"""Mississippi Code inventory from the legislature-designated Lexis portal.

The Mississippi Legislature and Secretary of State direct readers to the
LexisNexis free-public-access edition of the unannotated Mississippi Code.
This module inventories that source-native table of contents.  It deliberately
does not open document links, accept terms, solve access controls, or promote
TOC labels to statute bodies.

The public-law boundary is explicit: enacted section text, captions, section
numbers, and legislative histories may be retained; publisher annotations,
case notes, arrangement, presentation, and other editorial material may not.
Future body recovery must submit the complete same-domain locator set through
one plural archival-aware acquisition wave.  A per-document Common Crawl or
WARC inventory loop is outside this contract.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from .base_scraper import (
    NormalizedStatute,
    StatuteMetadata,
    current_state_law_run_environment_value,
)

ENABLE_ENV = "MISSISSIPPI_LEXIS_PUBLIC_ACCESS_ENABLE"
OFFICIAL_LEGISLATURE_ENTRY_URL = "https://www.legislature.ms.gov/"
OFFICIAL_LEGISLATURE_HELP_URL = "https://www.legislature.ms.gov/help/"
OFFICIAL_SECRETARY_OF_STATE_URL = (
    "https://www.sos.ms.gov/publications-external-affairs/mississippi-law"
)
PUBLIC_ENTRY_URL = "http://www.lexisnexis.com/hottopics/mscode/"
ADVANCE_ORIGIN = "https://advance.lexis.com"
PUBLIC_CONTAINER_CONFIG = (
    "00JAAzNzhjOTYxNC0wZjRkLTQzNzAtYjJlYS1jNjExZWYxZGFhMGYK"
    "AFBvZENhdGFsb2cMlW40w5iIH7toHnTBIEP0"
)
PUBLIC_CONTAINER_URL = f"{ADVANCE_ORIGIN}/container?config={PUBLIC_CONTAINER_CONFIG}"

# Values exposed by the public container on 2026-08-26.  The ``crid`` and
# ``prid`` query parameters added during navigation are request-local and are
# not part of the source identity.
TOC_POD_ID = "6gf5kkk"
TOC_ENDPOINT_PATH = f"/r/tocprovider/{TOC_POD_ID}/toc/{TOC_POD_ID}"
TOC_ROOT_ID = TOC_POD_ID
TOC_URN_PATH = (
    "/shared/tableofcontents/"
    "urn:contentItem:8S5T-PM12-D6RV-H00W-00008-00"
)
TOC_SOURCE_ID = "urn:contentItem:csi:1091205"
TOC_SEARCH_FILTER = "MTA5MTIwNQ"
TOC_DOCUMENT_CONFIG = (
    "00JABhZDIzMTViZS04NjcxLTQ1MDItOTllOS03MDg0ZTQxYzU4ZTQK"
    "AFBvZENhdGFsb2f8inKxYiqNVSihJeNKRlUp"
)
TOC_RESULTS_CONFIG = (
    "0146JABiODViNTc0Yy01MGJlLTRjYTQtOWNhMy04MzAzODZhY2M2MzcK"
    "AFBvZENhdGFsb2fv1hcZRCKiV89wcvA448We"
)
TOC_SEARCH_MFID = "1000516"

EXPECTED_TITLE_NAMES: Mapping[int, str] = {
    1: "Laws and Statutes",
    3: "State Sovereignty, Jurisdiction and Holidays",
    5: "Legislative Department",
    7: "Executive Department",
    9: "Courts",
    11: "Civil Practice and Procedure",
    13: "Evidence, Process and Juries",
    15: "Limitation of Actions",
    17: "Local Government; Provisions Common to Counties and Municipalities",
    19: "Counties and County Officers",
    21: "Municipalities",
    23: "Elections",
    25: "Public Officers and Employees; Public Records",
    27: "Taxation and Finance",
    29: "Public Lands, Buildings and Property",
    31: "Public Business, Bonds and Obligations",
    33: "Military Affairs",
    35: "War Veterans and Pensions",
    37: "Education",
    39: "Libraries, Arts, Archives and History",
    41: "Public Health",
    43: "Public Welfare",
    45: "Public Safety and Good Order",
    47: "Prisons and Prisoners; Probation and Parole",
    49: "Conservation and Ecology",
    51: "Waters, Water Resources, Water Districts, Drainage and Flood Control",
    53: "Oil, Gas and Other Minerals",
    55: "Parks and Recreation",
    57: "Planning, Research and Development",
    59: "Ports, Harbors, Landings and Watercraft",
    61: "Aviation",
    63: "Motor Vehicles and Traffic Regulations",
    65: "Highways, Bridges and Ferries",
    67: "Alcoholic Beverages",
    69: "Agriculture, Horticulture, and Animals",
    71: "Labor and Industry",
    73: "Professions and Vocations",
    75: "Regulation of Trade, Commerce and Investments",
    77: "Public Utilities and Carriers",
    79: "Corporations, Associations, and Partnerships",
    81: "Banks and Financial Institutions",
    83: "Insurance",
    85: "Debtor-Creditor Relationship",
    87: "Contracts and Contractual Relations",
    89: "Real and Personal Property",
    91: "Trusts and Estates",
    93: "Domestic Relations",
    95: "Torts",
    97: "Crimes",
    99: "Criminal Procedure",
}
EXPECTED_TITLE_NUMBERS = tuple(str(number) for number in EXPECTED_TITLE_NAMES)
RECENT_LEGISLATION_ROOT_LABEL = (
    "Mississippi New Sections Added by Recent Legislation"
)
# AAB..AAZ contains 25 roots and ABA..ABZ contains the remaining 26.
EXPECTED_ROOT_NODE_IDS = tuple(
    [f"AA{letter}" for letter in "BCDEFGHIJKLMNOPQRSTUVWXYZ"]
    + [f"AB{letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
)
EXPECTED_ROOT_COUNT = 1 + len(EXPECTED_TITLE_NUMBERS)
MAX_EXHAUSTIVE_TOC_LEVEL = 12
DEFAULT_RETRIES = 3

# These are hashes from an independent 2026-08-26 diagnostic projection.  They
# are recorded for the audit report only, not used as evergreen acceptance
# constants and not asserted to use :func:`canonical_node_digest`'s encoding.
OBSERVED_2026_08_26_ROOT_SEMANTIC_SHA256 = (
    "82a629e6d95259133d09478cef31c980f017f14def4c0206cc9f2b120d512d08"
)
OBSERVED_2026_08_26_ALL_NODE_SEMANTIC_SHA256 = (
    "ae9b9b34b903ac3c73fcd4aab4324c55995324026ca36988f07eb044285e5a4e"
)
OBSERVED_2026_08_26_MAIN_DOCUMENT_SEMANTIC_SHA256 = (
    "243e41985164f1c4cc00782c107c5f9ea8914355a842595869cb250dc5b9d0d3"
)
OBSERVED_DESCENDANT_NODE_COUNT = 33_600
OBSERVED_CURRENT_SECTION_CANDIDATE_COUNT = 30_270
OBSERVED_CURRENT_COLLECTION_COUNT = 3
OBSERVED_UNTYPED_CURRENT_COUNT = 3
OBSERVED_RECENT_LEGISLATION_LOCATOR_COUNT = 15
OBSERVED_FUTURE_EFFECTIVENESS_COUNT = 80
OBSERVED_FUTURE_PLACEHOLDER_COUNT = 2
OBSERVED_EDITORIAL_STRUCTURE_COUNT = 59
OBSERVED_REPEATED_SECTION_IDENTITY_COUNT = 158
OBSERVED_EXTRA_VARIANT_LOCATOR_COUNT = 177

_NODE_ID_RE = re.compile(r"^[A-Z0-9]{2,128}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_TITLE_RE = re.compile(r"^TITLE\s+(?P<number>\d{1,3})\b", re.IGNORECASE)
_SECTION_NUMBER_PATTERN = (
    r"\d{1,3}-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*-"
    r"[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*"
)
_SECTION_RE = re.compile(
    rf"^\s*§+\s*(?P<number>{_SECTION_NUMBER_PATTERN})(?:\.|\s|$)",
    re.IGNORECASE,
)
_ADDED_SECTION_RE = re.compile(
    rf"\bMiss\.\s+Code\s+Ann\.\s+§\s*(?P<number>{_SECTION_NUMBER_PATTERN})\b",
    re.IGNORECASE,
)
_SECTION_COLLECTION_RE = re.compile(r"^\s*§§\s+", re.IGNORECASE)
_STRUCTURAL_LABEL_RE = re.compile(
    r"^\s*(?:Appendix|Article|Chapter|In General|Junior College Commission|"
    r"Municipal Fire Protection Fund|Part|Regional Initiatives Program|"
    r"Subarticle|Subchapter|Subtitle|Transfer of Functions)\b",
    re.IGNORECASE,
)
_DOCUMENT_PATH_RE = re.compile(
    r"^/shared/document/(?P<family>statutes-legislation|fe)/"
    r"urn:contentItem:[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}-[A-Z0-9]{5}-[A-Z0-9]{2}$",
    re.IGNORECASE,
)
_PLACEHOLDER_DOCUMENT_PATHS = frozenset({"/shared/document/fe/"})
_DELEGATION_RE = re.compile(
    r"Mississippi\s+Code\s+Of\s+1972\s+Unannotated\s*-\s*"
    r"Free\s+Public\s+Access.*?maintained\s+by\s+LexisNexis",
    re.IGNORECASE | re.DOTALL,
)
_BLOCKED_RE = re.compile(
    r"robot\s*validation|robotvalidation|captcha|confirm\s+you\s+are\s+human|"
    r"complete\s+the\s+security\s+check|signin\.lexisnexis\.com|"
    r"sign\s+in\s+to\s+continue|browser\s+redirect\s+to\s+the\s+intended\s+"
    r"destination|\bI\s+Agree\b.*?(?:terms|conditions)|"
    r"(?:terms|conditions).*?\bI\s+Agree\b|\bResults\s+for\s*:",
    re.IGNORECASE | re.DOTALL,
)
_WS_RE = re.compile(r"\s+")
_CONTENT_ITEM_RE = re.compile(
    r"/urn:contentItem:(?P<item>[A-Za-z0-9:-]+)$",
    re.IGNORECASE,
)
_PRIMARY_BODY_SECTION_RE = re.compile(
    rf"^(?:(?:Miss(?:issippi)?\.?\s+Code(?:\s+Ann\.?)?)\s*)?"
    rf"(?:§+\s*)?(?P<number>{_SECTION_NUMBER_PATTERN})"
    r"(?:\s*[.\-\u2013\u2014:]\s*|\s+|$)",
    re.IGNORECASE,
)
_BODY_TERMINAL_RE = re.compile(
    r"^[\[(]?\s*(?P<kind>repealed|reserved|transferred|expired|obsolete)\b",
    re.IGNORECASE,
)
_CATALOG_TERMINAL_RE = re.compile(
    r"(?:^|[.\-\u2013\u2014:\s])[\[(]?\s*"
    r"(?P<kind>repealed|reserved|transferred|expired|obsolete)\b"
    r"[^\])]{0,100}[\])]?\s*[.]?\s*$",
    re.IGNORECASE,
)
_EDITORIAL_HEADING_RE = re.compile(
    r"^(?:annotations?|case\s+notes?|notes?\s+to\s+decisions?|"
    r"research\s+references?|law\s+reviews?|treatises?|practice\s+aids?|"
    r"cross\s+references?|editor(?:'s|ial)?\s+notes?)\s*[:.]?$",
    re.IGNORECASE,
)
_TEMPORAL_MARKER_RE = re.compile(
    r"\b(?:effective\s+(?:until|through|on|from|upon)?|"
    r"repealed\s+effective|expires?\s+(?:on\s+)?|"
    r"contingent\s+upon|if\s+and\s+when)\b[^\n.;]{0,180}",
    re.IGNORECASE,
)
_MONTH_DATE_RE = re.compile(
    r"\b(?P<month>January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s*,\s*(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_LIVE_EVIDENCE_CAPABILITY = object()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(value: object) -> str:
    """Hash one stable Mississippi source/request projection."""

    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _clean(value: object) -> str:
    return _WS_RE.sub(" ", str(value or "").replace("\xa0", " ")).strip()


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _as_optional_bool(value: object) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    return None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def enabled() -> bool:
    """Return whether a live, metadata-only inventory was explicitly enabled."""

    return current_state_law_run_environment_value(ENABLE_ENV).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def container_url_matches(value: str) -> bool:
    """Require the exact public container and only its ephemeral request IDs."""

    try:
        parsed = urlparse(str(value or ""))
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "advance.lexis.com"
        or parsed.path != "/container"
        or parsed.params
        or parsed.fragment
        or parsed.username
        or parsed.password
        or parsed.port is not None
    ):
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    if query.get("config") != [PUBLIC_CONTAINER_CONFIG]:
        return False
    if not set(query).issubset({"config", "crid", "prid"}):
        return False
    return all(
        len(query[key]) == 1 and bool(_REQUEST_ID_RE.fullmatch(query[key][0]))
        for key in ("crid", "prid")
        if key in query
    )


def document_path_family(value: object) -> str:
    """Return ``current`` or ``future`` for one exact Lexis document path."""

    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return ""
    if parsed.params or parsed.query or parsed.fragment:
        return ""
    if parsed.scheme or parsed.netloc:
        if parsed.scheme != "https" or parsed.netloc.lower() != "advance.lexis.com":
            return ""
    match = _DOCUMENT_PATH_RE.fullmatch(parsed.path or "")
    if match is None:
        return ""
    return "future" if match.group("family").lower() == "fe" else "current"


def is_document_path(value: object) -> bool:
    return bool(document_path_family(value))


def _is_allowed_link_href(value: object) -> bool:
    normalized = str(value or "").strip()
    return not normalized or is_document_path(normalized) or normalized in _PLACEHOLDER_DOCUMENT_PATHS


@dataclass(frozen=True)
class MississippiLexisNode:
    """One normalized node from the delegated Mississippi TOC."""

    node_id: str
    title: str
    level: int
    node_path: str
    can_expand: bool
    can_open: bool
    has_children: bool
    link_href: str = ""
    open_to_levels: tuple[int, ...] = ()
    subscribed: bool | None = None
    purchase_required: bool | None = None
    list_price: float | None = None
    net_price: float | None = None
    pricing_present: bool = False
    currency_code: str = ""
    usage_type_code: str = ""
    document_status: str = ""
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
        if match is None:
            return None
        number = str(int(match.group("number")))
        return number if number in EXPECTED_TITLE_NUMBERS else None

    @property
    def is_recent_legislation_root(self) -> bool:
        return bool(
            self.level == 1
            and self.node_id == EXPECTED_ROOT_NODE_IDS[0]
            and " ".join(self.title.split()).casefold()
            == RECENT_LEGISLATION_ROOT_LABEL.casefold()
        )

    @property
    def is_recent_legislation_member(self) -> bool:
        return self.node_path.startswith(f"/ROOT/{EXPECTED_ROOT_NODE_IDS[0]}/")

    @property
    def section_number(self) -> str | None:
        match = _SECTION_RE.search(self.title)
        if match is None and self.is_recent_legislation_member:
            match = _ADDED_SECTION_RE.search(self.title)
        if match is None:
            return None
        number = str(match.group("number"))
        title_number = number.split("-", 1)[0]
        return number if title_number in EXPECTED_TITLE_NUMBERS else None

    @property
    def document_family(self) -> str:
        return document_path_family(self.link_href)

    @property
    def is_document_locator(self) -> bool:
        # The full content-item path is the locator identity.  Lexis currently
        # emits a small number of such paths with inconsistent ``canopen`` or
        # pricing flags; those flags may affect live UI access but must not
        # silently remove members from the exact recovery frontier.
        return bool(self.document_family)

    @property
    def evidence_verified(self) -> bool:
        try:
            observed = datetime.fromisoformat(self.evidence_observed_at)
        except ValueError:
            observed = None
        return bool(
            self._evidence_capability is _LIVE_EVIDENCE_CAPABILITY
            and container_url_matches(self.evidence_source_url)
            and observed is not None
            and observed.tzinfo is not None
            and observed.utcoffset() is not None
            and _SHA256_RE.fullmatch(self.evidence_sha256)
            and _node_shape_valid(self)
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("_evidence_capability", None)
        value.update(
            {
                "title_number": self.title_number,
                "section_number": self.section_number,
                "document_family": self.document_family,
                "is_document_locator": self.is_document_locator,
                "is_recent_legislation_root": self.is_recent_legislation_root,
                "is_recent_legislation_member": self.is_recent_legislation_member,
                "evidence_verified": self.evidence_verified,
                "full_corpus_admissible": False,
            }
        )
        return value


def _node_shape_valid(node: MississippiLexisNode) -> bool:
    return bool(
        _NODE_ID_RE.fullmatch(node.node_id)
        and node.level >= 1
        and node.node_path.startswith("/ROOT/")
        and node.node_path.endswith(f"/{node.node_id}")
        and _is_allowed_link_href(node.link_href)
        and all(2 <= level <= MAX_EXHAUSTIVE_TOC_LEVEL for level in node.open_to_levels)
        and tuple(sorted(set(node.open_to_levels))) == node.open_to_levels
        and (
            node.title.strip()
            or node.link_href in _PLACEHOLDER_DOCUMENT_PATHS
            or (
                node.can_open
                and not node.can_expand
                and not node.has_children
                and is_document_path(node.link_href)
            )
        )
    )


def node_from_mapping(value: Mapping[str, Any]) -> MississippiLexisNode | None:
    """Normalize one exact Lexis TOC mapping without authorizing it."""

    props = value.get("props")
    if not isinstance(props, Mapping):
        return None
    top_id = str(value.get("id") or "").strip()
    props_id = str(props.get("nodeid") or "").strip()
    if top_id and props_id and top_id != props_id:
        return None
    node_id = top_id or props_id
    level = _as_int(props.get("level"))
    pricing = props.get("tocpricing")
    pricing_map = pricing if isinstance(pricing, Mapping) else {}
    raw_levels = props.get("targetlevels") or ()
    if isinstance(raw_levels, Sequence) and not isinstance(
        raw_levels, (str, bytes, bytearray)
    ):
        parsed_levels = tuple(
            sorted(
                {
                    level
                    for item in raw_levels
                    if (level := _as_int(item)) is not None
                }
            )
        )
    else:
        parsed_levels = ()
    node = MississippiLexisNode(
        node_id=node_id,
        title=str(
            props.get("linktemplatetitle") or props.get("title") or ""
        ).strip(),
        level=level or 0,
        node_path=str(props.get("nodepath") or "").strip(),
        can_expand=_as_bool(props.get("canexpand")),
        can_open=_as_bool(props.get("canopen")),
        has_children=_as_bool(props.get("haschildren")),
        link_href=str(props.get("linkhref") or "").strip(),
        open_to_levels=parsed_levels,
        subscribed=_as_optional_bool(props.get("subscribed")),
        purchase_required=_as_optional_bool(pricing_map.get("purchaserequired")),
        list_price=_as_float(pricing_map.get("listprice")),
        net_price=_as_float(pricing_map.get("netprice")),
        pricing_present=bool(pricing_map),
        currency_code=str(pricing_map.get("currencycode") or ""),
        usage_type_code=str(pricing_map.get("usagetypecode") or ""),
        document_status=str(pricing_map.get("documentstatus") or ""),
    )
    if not _node_shape_valid(node):
        return None
    if not any(
        key in props for key in ("canexpand", "canopen", "haschildren", "linkhref")
    ):
        return None
    return node


def parse_root_dom_rows(
    rows: Iterable[Mapping[str, Any]],
) -> list[MississippiLexisNode]:
    """Normalize the exact rendered recent-law plus 50-title roots."""

    nodes: list[MississippiLexisNode] = []
    seen: set[str] = set()
    for row in rows:
        raw_levels = row.get("targetlevels") or ()
        if not isinstance(raw_levels, Sequence) or isinstance(
            raw_levels, (str, bytes, bytearray)
        ):
            raw_levels = ()
        levels: list[int] = []
        for item in raw_levels:
            level = _as_int(item)
            if level is None:
                continue
            levels.append(level)
        node = MississippiLexisNode(
            node_id=str(row.get("nodeid") or "").strip(),
            title=str(row.get("title") or "").strip(),
            level=_as_int(row.get("level")) or 0,
            node_path=str(row.get("nodepath") or "").strip(),
            can_expand=_as_bool(row.get("canexpand")),
            can_open=_as_bool(row.get("canopen")),
            has_children=_as_bool(row.get("haschildren")),
            open_to_levels=tuple(sorted(set(levels))),
        )
        if (
            node.node_id in seen
            or not _node_shape_valid(node)
            or node.level != 1
            or len(levels) != len(set(levels))
        ):
            continue
        seen.add(node.node_id)
        nodes.append(node)
    return nodes


def root_membership_error(nodes: Sequence[MississippiLexisNode]) -> str:
    """Return the exact root-membership defect, or an empty string."""

    if len(nodes) != EXPECTED_ROOT_COUNT:
        return f"expected {EXPECTED_ROOT_COUNT} root nodes; received {len(nodes)}"
    if tuple(node.node_id for node in nodes) != EXPECTED_ROOT_NODE_IDS:
        return "root node IDs or source order changed from AAB..ABZ"
    if not nodes[0].is_recent_legislation_root:
        return "AAB is not the recent-legislation root"
    title_numbers = tuple(node.title_number for node in nodes[1:])
    if title_numbers != EXPECTED_TITLE_NUMBERS:
        return "title roots are not the exact ordered odd-numbered Titles 1..99"
    if not all(node.can_expand or node.has_children for node in nodes):
        return "one or more source roots are not expandable"
    return ""


def toc_open_to_request(
    node_id: object,
    *,
    target_level: object,
) -> tuple[str, dict[str, Any]]:
    """Build one source-native complete-subtree request for a root."""

    normalized = str(node_id or "").strip()
    if normalized not in EXPECTED_ROOT_NODE_IDS:
        raise ValueError(f"invalid Mississippi root node id: {normalized!r}")
    if isinstance(target_level, bool):
        raise ValueError("target_level must be an integer")
    level = _as_int(target_level)
    if level is None or not 2 <= level <= MAX_EXHAUSTIVE_TOC_LEVEL:
        raise ValueError(
            f"target_level must be between 2 and {MAX_EXHAUSTIVE_TOC_LEVEL}"
        )
    return (
        f"{ADVANCE_ORIGIN}{TOC_ENDPOINT_PATH}",
        {
            "id": TOC_ROOT_ID,
            "props": {
                "action": "open-to",
                "items": [
                    {"fieldName": "nodeId", "value": normalized},
                    {"fieldName": "targetLevel", "value": level},
                ],
            },
        },
    )


def canonical_toc_patch_request(
    node: MississippiLexisNode,
) -> tuple[str, bytes, dict[str, Any]]:
    """Bind one source root's maximum advertised level to exact PATCH bytes."""

    if not (
        node.level == 1
        and node.node_id in EXPECTED_ROOT_NODE_IDS
        and (node.can_expand or node.has_children)
        and node.open_to_levels
    ):
        raise ValueError("Mississippi TOC PATCH requires an expandable source root")
    endpoint, body = toc_open_to_request(
        node.node_id,
        target_level=max(node.open_to_levels),
    )
    request_body = _canonical_json_bytes(body)
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/json",
    }
    sanitized_request = {
        "headers": headers,
        "method": "PATCH",
        "request_body_length": len(request_body),
        "request_body_sha256": hashlib.sha256(request_body).hexdigest(),
        "url": endpoint,
    }
    return endpoint, request_body, sanitized_request


def parse_title_subtree_payload(
    payload: object,
    *,
    parent: MississippiLexisNode,
    target_level: int,
) -> tuple[list[MississippiLexisNode], tuple[str, ...], str]:
    """Validate every member and parent edge in one deepest-level response."""

    if parent.level != 1 or parent.node_id not in EXPECTED_ROOT_NODE_IDS:
        return [], (), "parent is not an exact Mississippi source root"
    if not (parent.can_expand or parent.has_children):
        return [], (), "parent is not expandable"
    if (
        isinstance(target_level, bool)
        or not isinstance(target_level, int)
        or not 2 <= target_level <= MAX_EXHAUSTIVE_TOC_LEVEL
    ):
        return [], (), "target level is outside the supported TOC range"
    if not isinstance(payload, Mapping):
        return [], (), "payload is not an object"
    props = payload.get("props")
    if isinstance(props, Mapping) and props.get("error"):
        return [], (), "payload contains an error"

    nodes: list[MississippiLexisNode] = []
    seen_by_id: dict[str, MississippiLexisNode] = {}
    seen_path_ids: dict[str, str] = {}
    malformed = False

    def _walk(value: object) -> None:
        nonlocal malformed
        if isinstance(value, Mapping):
            raw_props = value.get("props")
            node_shaped = bool(
                isinstance(raw_props, Mapping)
                and any(
                    key in raw_props
                    for key in (
                        "nodeid",
                        "nodepath",
                        "level",
                        "linktemplatetitle",
                        "canexpand",
                        "canopen",
                        "haschildren",
                        "linkhref",
                    )
                )
            )
            if node_shaped:
                node = node_from_mapping(value)
                if node is None:
                    malformed = True
                else:
                    prior_node = seen_by_id.get(node.node_id)
                    prior_path_id = seen_path_ids.get(node.node_path)
                    if prior_node is not None or prior_path_id is not None:
                        # Lexis may serialize the identical node-shaped object
                        # in more than one response collection.  Exact repeats
                        # are one member; conflicting reuse remains fatal.
                        if prior_node != node or prior_path_id != node.node_id:
                            malformed = True
                    else:
                        seen_by_id[node.node_id] = node
                        seen_path_ids[node.node_path] = node.node_id
                        nodes.append(node)
            for child in value.values():
                _walk(child)
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for child in value:
                _walk(child)

    _walk(payload)
    if malformed:
        return [], (), "subtree contains a malformed or duplicate TOC node"
    if not nodes:
        return [], (), "subtree contains no TOC nodes"

    prefix = f"{parent.node_path}/"
    branch_paths = {parent.node_path, *(node.node_path for node in nodes)}
    for node in nodes:
        path_parts = [part for part in node.node_path.split("/") if part]
        immediate_parent_path = "/" + "/".join(path_parts[:-1])
        if (
            not node.node_path.startswith(prefix)
            or node.level <= 1
            or node.level > target_level
            or node.level != len(path_parts) - 1
            or immediate_parent_path not in branch_paths
        ):
            return [], (), "subtree contains a node outside its exact hierarchy"
        if (
            parent.title_number
            and node.section_number
            and node.section_number.split("-", 1)[0] != parent.title_number
        ):
            return [], (), "statute citation crossed the requested title boundary"

    expandable = [
        node for node in (parent, *nodes) if node.can_expand or node.has_children
    ]
    for node in expandable:
        child_level = node.level + 1
        if not any(
            candidate.level == child_level
            and candidate.node_path.rsplit("/", 1)[0] == node.node_path
            for candidate in nodes
        ):
            return [], (), f"expandable node {node.node_id} has no direct child"

    full_hrefs = [node.link_href for node in nodes if node.is_document_locator]
    if len(full_hrefs) != len(set(full_hrefs)):
        return [], (), "subtree reuses a full official document locator"
    return nodes, tuple(node.node_id for node in expandable), ""


def _bind_live_nodes(
    nodes: Iterable[MississippiLexisNode],
    *,
    source_url: str,
    observed_at: str,
    receipt_sha256: str,
) -> list[MississippiLexisNode]:
    try:
        observed = datetime.fromisoformat(observed_at)
    except ValueError:
        observed = None
    if not (
        container_url_matches(source_url)
        and observed is not None
        and observed.tzinfo is not None
        and observed.utcoffset() is not None
        and _SHA256_RE.fullmatch(receipt_sha256)
    ):
        return []
    bound: list[MississippiLexisNode] = []
    for node in nodes:
        if not _node_shape_valid(node):
            return []
        verified = replace(
            node,
            evidence_source_url=source_url,
            evidence_observed_at=observed_at,
            evidence_sha256=receipt_sha256,
        )
        object.__setattr__(verified, "_evidence_capability", _LIVE_EVIDENCE_CAPABILITY)
        if not verified.evidence_verified:
            return []
        bound.append(verified)
    return bound


def canonical_node_digest(nodes: Iterable[MississippiLexisNode]) -> str:
    """Hash the stable source projection, excluding session-local evidence."""

    projection = [
        [
            node.node_id,
            node.node_path,
            node.level,
            node.title,
            node.link_href,
            list(node.open_to_levels),
        ]
        for node in sorted(nodes, key=lambda item: item.node_path)
    ]
    payload = json.dumps(
        projection,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def document_disposition(node: MississippiLexisNode) -> str:
    """Classify a TOC document without treating its label as statute text."""

    if node.link_href in _PLACEHOLDER_DOCUMENT_PATHS:
        return "future_structural_placeholder"
    if not node.is_document_locator:
        return "not_document"
    if node.is_recent_legislation_member:
        return "recent_legislation_identity_residual"
    if node.document_family == "future":
        return "future_effectiveness_excluded"
    if node.section_number:
        return "current_section_candidate"
    if _SECTION_COLLECTION_RE.match(node.title):
        return "current_section_collection_candidate"
    if _STRUCTURAL_LABEL_RE.match(node.title):
        return "publisher_editorial_structure_excluded"
    return "untyped_current_document_residual"


def document_page_url(node: MississippiLexisNode) -> str:
    """Build the stable public locator for one live-verified TOC document."""

    if not node.evidence_verified or not node.is_document_locator:
        raise ValueError("Mississippi Lexis document locator is not live-verified")
    query = urlencode(
        (
            ("pdmfid", TOC_SEARCH_MFID),
            ("config", TOC_DOCUMENT_CONFIG),
            ("pddocfullpath", node.link_href),
        )
    )
    return f"{ADVANCE_ORIGIN}/documentpage/?{query}"


def content_item_id(value: object) -> str:
    """Return the exact Lexis content-item identity from a validated path."""

    parsed = urlparse(str(value or "").strip())
    match = _CONTENT_ITEM_RE.search(parsed.path or "")
    return str(match.group("item") or "") if match else ""


def legislature_delegation_present(html: str) -> bool:
    """Require the Legislature page's exact Mississippi Code publisher link."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return False
    source = str(html or "")
    if _BLOCKED_RE.search(source):
        return False
    soup = BeautifulSoup(source, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = urljoin(
            OFFICIAL_LEGISLATURE_ENTRY_URL,
            str(anchor.get("href") or "").strip(),
        )
        if href.rstrip("/") == PUBLIC_ENTRY_URL.rstrip("/") and re.search(
            r"\bMississippi\s+Code\b",
            _clean(anchor.get_text(" ")),
            re.IGNORECASE,
        ):
            return True
    return False


def publisher_container_delegation_present(html: str) -> bool:
    """Require the publisher entry response to name the exact container."""

    source = str(html or "")
    return bool(
        not _BLOCKED_RE.search(source)
        and PUBLIC_CONTAINER_CONFIG in source
        and re.search(
            r"advance\.lexis\.com(?:/|&(?:#x2F;|sol;))container",
            source,
            re.IGNORECASE,
        )
    )


def valid_authority_payload(payload: bytes) -> bool:
    """Reject empty authority responses and access-control shells."""

    if not payload:
        return False
    sample = bytes(payload[:200_000]).decode("utf-8", errors="replace")
    return bool(re.search(r"<html\b|<!doctype\s+html", sample, re.IGNORECASE)) and not (
        _BLOCKED_RE.search(sample)
    )


def valid_document_payload(payload: bytes) -> bool:
    """Reject empty and known access/search/bootstrap shells before retention."""

    if not payload:
        return False
    sample = bytes(payload[:200_000]).decode("utf-8", errors="replace")
    return _BLOCKED_RE.search(sample) is None and bool(
        re.search(
            r"<html\b|<main\b|<article\b|data-document-content|"
            r"data-section-number",
            sample,
            re.IGNORECASE,
        )
    )


def canonical_rendered_root_request() -> dict[str, Any]:
    """Return the stable browser GET identity used for root retention/replay."""

    return {
        "method": "GET",
        "rendered_by": "playwright",
        "url": PUBLIC_CONTAINER_URL,
        "wait_until": "domcontentloaded",
    }


def parse_root_html(html: str) -> list[MississippiLexisNode]:
    """Extract and strictly validate the rendered 51-root Lexis hierarchy."""

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - production dependency
        raise RuntimeError("BeautifulSoup is required for Mississippi Lexis parsing") from exc
    source = str(html or "")
    if _BLOCKED_RE.search(source):
        raise ValueError("Mississippi container returned an access or bootstrap shell")
    soup = BeautifulSoup(source, "html.parser")
    if not _DELEGATION_RE.search(_clean(soup.get_text(" "))):
        raise ValueError("Mississippi container omitted its free-public-access delegation")
    rows: list[dict[str, Any]] = []
    for element in soup.select('li.js-node[data-level="1"]'):
        header = element.find(class_="js-node-header", recursive=False) or element
        rows.append(
            {
                "nodeid": element.get("data-nodeid") or "",
                "nodepath": element.get("data-nodepath") or "",
                "level": element.get("data-level") or "",
                "title": element.get("data-title") or "",
                "canexpand": element.get("data-canexpand") or "",
                "canopen": element.get("data-canopen") or "",
                "haschildren": element.get("data-haschildren") or "",
                "targetlevels": [
                    item.get("data-targetlevel") or ""
                    for item in header.select('[data-command="open-to"]')
                ],
            }
        )
    roots = parse_root_dom_rows(rows)
    error = root_membership_error(roots)
    if error:
        raise ValueError(f"Mississippi rendered root membership changed: {error}")
    if any(not node.open_to_levels for node in roots):
        raise ValueError("Mississippi rendered root omitted a complete open-to contract")
    for node, number in zip(roots[1:], EXPECTED_TITLE_NUMBERS, strict=True):
        label = re.sub(
            rf"^TITLE\s+0*{re.escape(number)}\b[\s.\-\u2013\u2014:]*",
            "",
            _clean(node.title),
            count=1,
            flags=re.IGNORECASE,
        )
        if label.casefold() != _clean(EXPECTED_TITLE_NAMES[int(number)]).casefold():
            raise ValueError(f"Mississippi Title {number} label drifted: {label!r}")
    return roots


def grouped_get_acquisition_contract(urls: Sequence[str]) -> dict[str, Any]:
    """Describe one ordered, same-domain plural GET wave."""

    requested = [str(url or "").strip() for url in urls]
    if not requested or any(not url for url in requested):
        raise ValueError("Mississippi GET wave must contain non-empty source URLs")
    if len(requested) != len(set(requested)):
        raise ValueError("Mississippi GET wave repeated a source URL")
    domains = {(urlparse(url).hostname or "").lower() for url in requested}
    if "" in domains or len(domains) != 1:
        raise ValueError("Mississippi GET wave must contain exactly one source domain")
    return {
        "schema_version": "mississippi-lexis-grouped-get-contract-v1",
        "source_domain": domains.pop(),
        "request_url_count": len(requested),
        "request_urls_sha256": canonical_digest(requested),
        "common_crawl_inventory_query_upper_bound": 1,
        "wayback_prefix_inventory": True,
        "group_warc_ranges_by_warc_filename": True,
        "coalesce_compatible_warc_ranges": True,
        "per_page_archive_inventory_loop": False,
        "retry_residual_urls_only": True,
    }


def _remove_editorial_sections(soup: Any) -> None:
    for selector in (
        ".case-notes",
        ".notes-to-decisions",
        ".research-references",
        ".editorial-notes",
        "[data-component='case-notes']",
        "[data-component='notes-to-decisions']",
        "[data-component='research-references']",
    ):
        for node in soup.select(selector):
            node.decompose()
    for heading in list(soup.find_all(re.compile(r"^h[1-6]$"))):
        if not _EDITORIAL_HEADING_RE.fullmatch(_clean(heading.get_text(" "))):
            continue
        level = int(str(heading.name)[1:])
        cursor = heading.next_sibling
        while cursor is not None:
            following = cursor.next_sibling
            name = str(getattr(cursor, "name", "") or "")
            if re.fullmatch(r"h[1-6]", name) and int(name[1:]) <= level:
                break
            extract = getattr(cursor, "extract", None)
            if callable(extract):
                extract()
            cursor = following
        heading.decompose()


def _section_number_from_body_value(value: object) -> str:
    match = _PRIMARY_BODY_SECTION_RE.match(_clean(value))
    if match is None:
        return ""
    number = str(match.group("number") or "")
    return number if number.split("-", 1)[0] in EXPECTED_TITLE_NUMBERS else ""


def _chapter_number(section_number: str) -> str:
    parts = section_number.split("-")
    return parts[1] if len(parts) >= 3 else ""


def _catalog_terminal_disposition(value: object) -> str:
    match = _CATALOG_TERMINAL_RE.search(_clean(value))
    return str(match.group("kind") or "").casefold() if match else ""


def _document_segments(content: Any, *, expected_section: str) -> tuple[list[tuple[str, Any]], str]:
    scoped = list(content.select("[data-section-number]"))
    if scoped:
        segments: list[tuple[str, Any]] = []
        seen: set[str] = set()
        for element in scoped:
            number = _section_number_from_body_value(
                element.get("data-section-number") or ""
            )
            if not number or number in seen:
                return [], "document contains a malformed or duplicate section boundary"
            seen.add(number)
            segments.append((number, element))
        if expected_section and (
            len(segments) != 1 or segments[0][0] != expected_section
        ):
            return [], "catalog document section identity does not match body boundaries"
        return segments, ""

    lines = [
        _clean(line)
        for line in content.get_text("\n", strip=True).splitlines()
        if _clean(line)
    ]
    identities: list[str] = []
    for line in lines:
        number = _section_number_from_body_value(line)
        if number and number not in identities:
            identities.append(number)
    if expected_section:
        if not identities or identities[0] != expected_section:
            return [], "catalog document section identity does not match body"
        if len(identities) != 1:
            return [], "single-section catalog document contains multiple body identities"
        return [(expected_section, content)], ""
    if len(identities) == 1:
        return [(identities[0], content)], ""
    if len(identities) > 1:
        return [], "multi-section document lacks source-bound section containers"
    return [], "document body did not establish a Mississippi section identity"


def parse_mississippi_lexis_document_html(
    html: str,
    *,
    source_url: str,
    node: MississippiLexisNode,
    source_order: int,
    code_name: str = "Mississippi Code",
) -> tuple[list[NormalizedStatute], dict[str, Any]]:
    """Classify one retained content item as operative, terminal, or residual."""

    residuals: list[dict[str, Any]] = []
    terminals: list[dict[str, Any]] = []
    statutes: list[NormalizedStatute] = []
    canonical_url = document_page_url(node) if node.evidence_verified else ""
    item_id = content_item_id(node.link_href)
    if not canonical_url or source_url != canonical_url or not item_id:
        residuals.append(
            {
                "reason": "document_url_does_not_match_catalog_content_item",
                "source_url": source_url,
            }
        )
    elif _BLOCKED_RE.search(str(html or "")):
        residuals.append(
            {"reason": "lexis_access_or_search_shell", "source_url": source_url}
        )
    else:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover - production dependency
            raise RuntimeError("BeautifulSoup is required for Mississippi Lexis parsing") from exc
        soup = BeautifulSoup(str(html or ""), "html.parser")
        for tag in soup(
            [
                "script",
                "style",
                "nav",
                "header",
                "footer",
                "noscript",
                "form",
                "button",
                "aside",
            ]
        ):
            tag.decompose()
        content = (
            soup.select_one("[data-document-content]")
            or soup.select_one("#document-content")
            or soup.select_one(".document-content")
            or soup.find("main")
            or soup.find("article")
        )
        if content is None:
            residuals.append(
                {
                    "reason": "document_content_container_missing",
                    "source_url": source_url,
                }
            )
        else:
            _remove_editorial_sections(content)
            segments, segment_error = _document_segments(
                content,
                expected_section=node.section_number or "",
            )
            if segment_error:
                residuals.append(
                    {"reason": segment_error, "source_url": source_url}
                )
            for member_order, (section_number, segment) in enumerate(segments):
                lines = [
                    _clean(line)
                    for line in segment.get_text("\n", strip=True).splitlines()
                    if _clean(line)
                ]
                text = "\n".join(lines)
                nonidentity_lines = [
                    line for line in lines if section_number not in line
                ]
                terminal_match = next(
                    (
                        match
                        for line in nonidentity_lines[:8]
                        if (match := _BODY_TERMINAL_RE.match(line))
                    ),
                    None,
                )
                body_terminal = (
                    str(terminal_match.group("kind") or "").casefold()
                    if terminal_match
                    else ""
                )
                catalog_terminal = _catalog_terminal_disposition(node.title)
                if body_terminal:
                    if catalog_terminal and body_terminal != catalog_terminal:
                        residuals.append(
                            {
                                "body_disposition": body_terminal,
                                "catalog_disposition": catalog_terminal,
                                "reason": "catalog_and_body_terminal_dispositions_conflict",
                                "source_url": source_url,
                            }
                        )
                        continue
                    terminals.append(
                        {
                            "catalog_node_id": node.node_id,
                            "content_item_id": item_id,
                            "disposition": body_terminal,
                            "section_number": section_number,
                            "source_order": int(source_order),
                            "source_url": source_url,
                        }
                    )
                    continue
                if catalog_terminal:
                    residuals.append(
                        {
                            "catalog_disposition": catalog_terminal,
                            "reason": "catalog_terminal_not_confirmed_by_document_body",
                            "source_url": source_url,
                        }
                    )
                    continue
                if not text:
                    residuals.append(
                        {"reason": "empty_unclassified_document", "source_url": source_url}
                    )
                    continue
                caption = _clean(node.title)
                caption = re.sub(
                    rf"^\s*§+\s*{re.escape(section_number)}\s*[.\-\u2013\u2014:]*\s*",
                    "",
                    caption,
                    count=1,
                    flags=re.IGNORECASE,
                ).strip(" .-\u2013\u2014:")
                marker_source = "\n".join([node.title, *lines[:20]])
                temporal_markers = list(
                    dict.fromkeys(
                        _clean(match.group(0))
                        for match in _TEMPORAL_MARKER_RE.finditer(marker_source)
                    )
                )
                canonical_key = (
                    f"ms:{section_number.casefold()}:content-{item_id.casefold()}"
                )
                statutes.append(
                    NormalizedStatute(
                        state_code="MS",
                        state_name="Mississippi",
                        statute_id=(
                            f"{code_name} § {section_number} [content {item_id}]"
                        ),
                        code_name=code_name,
                        title_number=section_number.split("-", 1)[0],
                        chapter_number=_chapter_number(section_number),
                        section_number=section_number,
                        section_name=(caption or f"Section {section_number}")[:200],
                        full_text=text,
                        source_url=source_url,
                        official_cite=f"Miss. Code Ann. § {section_number}",
                        metadata=StatuteMetadata(),
                        structured_data={
                            "canonical_section_key": canonical_key,
                            "catalog_node_id": node.node_id,
                            "catalog_node_path": node.node_path,
                            "content_item_id": item_id,
                            "discovery_method": "strict_delegated_lexis_content_item",
                            "document_member_order": member_order,
                            "skip_hydrate": True,
                            "source_authority_class": "official",
                            "source_kind": "official_delegated_mississippi_lexis_code",
                            "source_order": int(source_order),
                            "source_temporal_markers": temporal_markers,
                            "strict_source_closure": True,
                        },
                    )
                )

    report = {
        "closed": bool(statutes or terminals) and not residuals,
        "content_item_id": item_id,
        "operative_sections": len(statutes),
        "parser_residuals": residuals,
        "section_numbers": [str(row.section_number or "") for row in statutes]
        + [str(row.get("section_number") or "") for row in terminals],
        "source_order": int(source_order),
        "source_url": source_url,
        "terminal_dispositions": terminals,
        "terminal_sections": len(terminals),
    }
    return statutes, report


def _marker_date(value: str) -> date | None:
    match = _MONTH_DATE_RE.search(value)
    if match is None:
        return None
    try:
        month = {
            name.casefold(): number
            for number, name in enumerate(
                (
                    "January",
                    "February",
                    "March",
                    "April",
                    "May",
                    "June",
                    "July",
                    "August",
                    "September",
                    "October",
                    "November",
                    "December",
                ),
                start=1,
            )
        }[str(match.group("month")).casefold()]
        return date(
            int(match.group("year")),
            month,
            int(match.group("day")),
        )
    except (KeyError, ValueError):
        return None


def _temporal_marker_state(markers: Sequence[str], observed: date) -> str:
    constraints: list[bool] = []
    for marker in markers:
        boundary = _marker_date(str(marker))
        if boundary is None:
            continue
        lowered = _clean(marker).casefold()
        if "effective until" in lowered or "repealed effective" in lowered or re.search(
            r"\bexpires?\b", lowered
        ):
            constraints.append(observed < boundary)
        elif "effective through" in lowered:
            constraints.append(observed <= boundary)
        elif "effective" in lowered:
            constraints.append(observed >= boundary)
    if not constraints:
        return "unknown"
    return "active" if all(constraints) else "inactive"


def reconcile_temporal_variants(
    rows: Sequence[NormalizedStatute],
    *,
    observed_at: str,
) -> tuple[list[NormalizedStatute], list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve only duplicate citations whose retained temporal proof is complete."""

    try:
        observed_value = datetime.fromisoformat(str(observed_at or ""))
    except ValueError as exc:
        raise ValueError("Mississippi temporal reconciliation requires an ISO observation") from exc
    if observed_value.tzinfo is None or observed_value.utcoffset() is None:
        raise ValueError("Mississippi temporal reconciliation requires a zoned observation")
    observed = observed_value.date()
    by_citation: dict[str, list[NormalizedStatute]] = {}
    for row in rows:
        citation = str(row.section_number or "").strip().casefold()
        if citation:
            by_citation.setdefault(citation, []).append(row)
    excluded_ids: set[int] = set()
    exclusions: list[dict[str, Any]] = []
    residuals: list[dict[str, Any]] = []
    for citation, variants in by_citation.items():
        if len(variants) < 2:
            continue
        candidates: list[dict[str, Any]] = []
        active: list[NormalizedStatute] = []
        complete = True
        for row in variants:
            markers = list(
                (row.structured_data or {}).get("source_temporal_markers") or []
            )
            state = _temporal_marker_state(markers, observed)
            complete = complete and state != "unknown"
            if state == "active":
                active.append(row)
            candidates.append(
                {
                    "canonical_section_key": str(
                        (row.structured_data or {}).get("canonical_section_key") or ""
                    ),
                    "content_item_id": str(
                        (row.structured_data or {}).get("content_item_id") or ""
                    ),
                    "source_order": int(
                        (row.structured_data or {}).get("source_order") or 0
                    ),
                    "source_temporal_markers": markers,
                    "source_url": row.source_url,
                    "temporal_state": state,
                }
            )
        if complete and len(active) == 1:
            winner = active[0]
            for row, candidate in zip(variants, candidates, strict=True):
                if row is winner:
                    continue
                excluded_ids.add(id(row))
                exclusions.append(
                    {
                        **candidate,
                        "disposition": "superseded_temporal_variant",
                        "section_number": citation,
                    }
                )
            continue
        residuals.append(
            {
                "candidate_count": len(variants),
                "candidates": candidates,
                "reason": "repeated_citation_requires_source_bound_temporal_reconciliation",
                "section_number": citation,
            }
        )
    kept = [row for row in rows if id(row) not in excluded_ids]
    return kept, exclusions, residuals


def grouped_body_acquisition_contract(
    nodes: Iterable[MississippiLexisNode],
) -> dict[str, Any]:
    """Derive exact future body inputs and their mandatory archive grouping.

    Every current section variant, section collection, recent-legislation
    identity, and untyped current document remains a body-acquisition target.
    Duplicate citations and documents without a catalog identity also remain
    explicit residuals until their exact bodies support reconciliation.
    """

    node_list = tuple(nodes)
    if not node_list or not all(node.evidence_verified for node in node_list):
        raise ValueError("body contract requires a live-verified inventory")

    candidates: list[MississippiLexisNode] = []
    body_targets: list[MississippiLexisNode] = []
    residuals: list[dict[str, str]] = []
    exclusions: list[dict[str, str]] = []
    for node in sorted(node_list, key=lambda item: item.node_path):
        disposition = document_disposition(node)
        row = {
            "node_id": node.node_id,
            "node_path": node.node_path,
            "label": node.title,
            "link_href": node.link_href,
            "disposition": disposition,
        }
        if disposition in {
            "current_section_candidate",
            "current_section_collection_candidate",
        }:
            candidates.append(node)
            body_targets.append(node)
        elif disposition in {
            "recent_legislation_identity_residual",
            "untyped_current_document_residual",
        }:
            body_targets.append(node)
            residuals.append(row)
        elif disposition != "not_document":
            exclusions.append(row)

    by_section: dict[str, list[MississippiLexisNode]] = {}
    for node in candidates:
        if node.section_number:
            by_section.setdefault(node.section_number, []).append(node)
    duplicate_ids = {
        section for section, variants in by_section.items() if len(variants) > 1
    }
    reusable = [
        node
        for node in candidates
        if not node.section_number or node.section_number not in duplicate_ids
    ]
    for section in sorted(duplicate_ids):
        for node in by_section[section]:
            residuals.append(
                {
                    "node_id": node.node_id,
                    "node_path": node.node_path,
                    "label": node.title,
                    "link_href": node.link_href,
                    "disposition": "duplicate_current_citation_requires_body_reconciliation",
                }
            )

    request_urls = tuple(document_page_url(node) for node in body_targets)
    if len(request_urls) != len(set(request_urls)):
        raise ValueError("future body request membership contains duplicate URLs")
    if any((urlparse(url).hostname or "").lower() != "advance.lexis.com" for url in request_urls):
        raise ValueError("future body request membership crossed source domains")
    return {
        "schema_version": "mississippi-lexis-body-acquisition-contract-v1",
        "source_domain": "advance.lexis.com",
        "request_urls": list(request_urls),
        "request_url_count": len(request_urls),
        "reusable_candidate_node_count": len(reusable),
        "residuals": residuals,
        "residual_count": len(residuals),
        "exclusions": exclusions,
        "exclusion_count": len(exclusions),
        "common_crawl_inventory_query_upper_bound": 1,
        "wayback_prefix_inventory": True,
        "group_warc_ranges_by_warc_filename": True,
        "per_page_archive_inventory_loop": False,
        "retry_residual_urls_only": True,
        "full_corpus_admissible": False,
    }


def derive_exact_metadata_frontier(
    roots: Sequence[MississippiLexisNode],
    *,
    subtrees_by_root_id: Mapping[str, Sequence[MississippiLexisNode]],
) -> dict[str, Any]:
    """Close one retained root/PATCH hierarchy and derive its body membership."""

    root_error = root_membership_error(roots)
    if root_error:
        raise ValueError(f"Mississippi source roots did not close: {root_error}")
    if tuple(subtrees_by_root_id) != EXPECTED_ROOT_NODE_IDS:
        raise ValueError("Mississippi subtree responses changed root order or membership")
    if not all(node.evidence_verified for node in roots):
        raise ValueError("Mississippi source roots lack retained evidence binding")

    all_nodes: list[MississippiLexisNode] = list(roots)
    descendants: list[MississippiLexisNode] = []
    seen_ids = {node.node_id for node in roots}
    seen_paths = {node.node_path for node in roots}
    seen_hrefs: set[str] = set()
    for root in roots:
        members = list(subtrees_by_root_id.get(root.node_id) or ())
        if not members or not all(node.evidence_verified for node in members):
            raise ValueError(
                f"Mississippi root {root.node_id} lacks a retained complete subtree"
            )
        for node in members:
            if node.node_id in seen_ids or node.node_path in seen_paths:
                raise ValueError("Mississippi hierarchy reused a node identity or path")
            if node.link_href and node.link_href in seen_hrefs:
                raise ValueError("Mississippi hierarchy reused a document locator")
            seen_ids.add(node.node_id)
            seen_paths.add(node.node_path)
            if node.link_href:
                seen_hrefs.add(node.link_href)
        descendants.extend(members)
        all_nodes.extend(members)

    catalog_nodes = [
        node for node in descendants if document_disposition(node) != "not_document"
    ]
    document_locators = [node for node in catalog_nodes if node.is_document_locator]
    dispositions: dict[str, int] = {}
    for node in descendants:
        disposition = document_disposition(node)
        if disposition != "not_document":
            dispositions[disposition] = dispositions.get(disposition, 0) + 1
    contract = grouped_body_acquisition_contract(catalog_nodes)
    body_dispositions = {
        "current_section_candidate",
        "current_section_collection_candidate",
        "recent_legislation_identity_residual",
        "untyped_current_document_residual",
    }
    document_nodes = [
        node
        for node in sorted(catalog_nodes, key=lambda item: item.node_path)
        if document_disposition(node) in body_dispositions
    ]
    current_section_nodes = [
        node
        for node in document_nodes
        if document_disposition(node) == "current_section_candidate"
    ]
    citation_counts: dict[str, int] = {}
    for node in current_section_nodes:
        if node.section_number:
            citation_counts[node.section_number] = (
                citation_counts.get(node.section_number, 0) + 1
            )
    repeated = {
        citation: count for citation, count in citation_counts.items() if count > 1
    }
    return {
        "all_node_count": len(all_nodes),
        "all_node_semantic_sha256": canonical_node_digest(all_nodes),
        "body_request_count": int(contract["request_url_count"]),
        "body_request_url_sha256": canonical_digest(contract["request_urls"]),
        "catalog_exclusion_count": int(contract["exclusion_count"]),
        "descendant_node_count": len(descendants),
        "document_like_node_count": len(catalog_nodes),
        "document_locator_count": len(document_locators),
        "document_nodes": document_nodes,
        "document_disposition_counts": dict(sorted(dispositions.items())),
        "extra_variant_locator_count": sum(count - 1 for count in repeated.values()),
        "repeated_section_identity_count": len(repeated),
        "root_count": len(roots),
        "root_semantic_sha256": canonical_node_digest(roots),
        "subtree_response_count": len(subtrees_by_root_id),
    }


def observed_metadata_drift(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Compare one retained hierarchy with the reviewed diagnostic algebra."""

    dispositions = dict(metadata.get("document_disposition_counts") or {})
    expected = {
        "descendant_node_count": OBSERVED_DESCENDANT_NODE_COUNT,
        "current_section_candidate": OBSERVED_CURRENT_SECTION_CANDIDATE_COUNT,
        "current_section_collection_candidate": OBSERVED_CURRENT_COLLECTION_COUNT,
        "untyped_current_document_residual": OBSERVED_UNTYPED_CURRENT_COUNT,
        "recent_legislation_identity_residual": (
            OBSERVED_RECENT_LEGISLATION_LOCATOR_COUNT
        ),
        "future_effectiveness_excluded": OBSERVED_FUTURE_EFFECTIVENESS_COUNT,
        "future_structural_placeholder": OBSERVED_FUTURE_PLACEHOLDER_COUNT,
        "publisher_editorial_structure_excluded": (
            OBSERVED_EDITORIAL_STRUCTURE_COUNT
        ),
        "repeated_section_identity_count": OBSERVED_REPEATED_SECTION_IDENTITY_COUNT,
        "extra_variant_locator_count": OBSERVED_EXTRA_VARIANT_LOCATOR_COUNT,
    }
    observed = {
        "descendant_node_count": int(metadata.get("descendant_node_count") or 0),
        "current_section_candidate": dispositions.get(
            "current_section_candidate", 0
        ),
        "current_section_collection_candidate": dispositions.get(
            "current_section_collection_candidate", 0
        ),
        "untyped_current_document_residual": dispositions.get(
            "untyped_current_document_residual", 0
        ),
        "recent_legislation_identity_residual": dispositions.get(
            "recent_legislation_identity_residual", 0
        ),
        "future_effectiveness_excluded": dispositions.get(
            "future_effectiveness_excluded", 0
        ),
        "future_structural_placeholder": dispositions.get(
            "future_structural_placeholder", 0
        ),
        "publisher_editorial_structure_excluded": dispositions.get(
            "publisher_editorial_structure_excluded", 0
        ),
        "repeated_section_identity_count": int(
            metadata.get("repeated_section_identity_count") or 0
        ),
        "extra_variant_locator_count": int(
            metadata.get("extra_variant_locator_count") or 0
        ),
    }
    return {
        key: {"expected": expected_value, "observed": observed[key]}
        for key, expected_value in expected.items()
        if observed[key] != expected_value
    }


@dataclass(frozen=True)
class MississippiLexisInventory:
    """One metadata-only, nonauthorizing delegated-source inventory."""

    status: str
    final_url: str
    observed_at: str
    delegation_verified: bool
    nodes: tuple[MississippiLexisNode, ...]
    expanded_root_ids: tuple[str, ...]
    diagnostics: tuple[str, ...]
    root_rendered_sha256: str = ""
    subtree_response_sha256: tuple[tuple[str, str], ...] = ()
    root_rendered_path: str = ""
    subtree_response_paths: tuple[tuple[str, str], ...] = ()

    @property
    def roots(self) -> tuple[MississippiLexisNode, ...]:
        return tuple(node for node in self.nodes if node.level == 1)

    @property
    def frontier(self) -> dict[str, Any]:
        roots = self.roots
        root_error = root_membership_error(roots)
        documents = [node for node in self.nodes if node.is_document_locator]
        main_documents = [
            node for node in documents if not node.is_recent_legislation_member
        ]
        recent_documents = [
            node for node in documents if node.is_recent_legislation_member
        ]
        dispositions: dict[str, int] = {}
        for node in self.nodes:
            disposition = document_disposition(node)
            if disposition == "not_document":
                continue
            dispositions[disposition] = dispositions.get(disposition, 0) + 1
        section_nodes = [node for node in main_documents if node.section_number]
        sections: dict[str, int] = {}
        for node in section_nodes:
            key = str(node.section_number)
            sections[key] = sections.get(key, 0) + 1
        duplicate_sections = sorted(
            (key for key, count in sections.items() if count > 1),
            key=lambda value: tuple(
                int(part) if part.isdigit() else part.casefold()
                for part in re.split(r"([0-9]+)", value)
                if part
            ),
        )
        current_candidates = [
            node
            for node in main_documents
            if document_disposition(node)
            in {
                "current_section_candidate",
                "current_section_collection_candidate",
            }
        ]
        current_section_counts: dict[str, int] = {}
        for node in current_candidates:
            if node.section_number:
                key = str(node.section_number)
                current_section_counts[key] = current_section_counts.get(key, 0) + 1
        duplicate_current_sections = {
            key for key, count in current_section_counts.items() if count > 1
        }
        duplicate_current_locator_count = sum(
            count
            for key, count in current_section_counts.items()
            if key in duplicate_current_sections
        )
        reusable_body_candidate_count = (
            len(current_candidates) - duplicate_current_locator_count
        )
        response_hashes = dict(self.subtree_response_sha256)
        response_paths = dict(self.subtree_response_paths)
        receipt_membership_valid = bool(
            tuple(self.expanded_root_ids) == EXPECTED_ROOT_NODE_IDS
            and set(response_hashes) == set(EXPECTED_ROOT_NODE_IDS)
            and all(_SHA256_RE.fullmatch(value) for value in response_hashes.values())
            and (
                not response_paths
                or set(response_paths) == set(EXPECTED_ROOT_NODE_IDS)
            )
        )
        toc_closed = bool(
            self.status == "complete"
            and self.delegation_verified
            and container_url_matches(self.final_url)
            and not root_error
            and receipt_membership_valid
            and len(self.nodes) > len(roots)
            and all(node.evidence_verified for node in self.nodes)
            and not self.diagnostics
        )
        return {
            "method": "official_delegated_mississippi_lexis_toc_open_to",
            "source_legal_as_of_semantics": (
                "current unannotated code observed at inventory time; "
                "future-effectiveness locators excluded; effective-date variants "
                "require source-body reconciliation"
            ),
            "observed_at": self.observed_at,
            "expected_root_count": EXPECTED_ROOT_COUNT,
            "root_count": len(roots),
            "root_membership_error": root_error,
            "expected_title_count": len(EXPECTED_TITLE_NUMBERS),
            "title_count": sum(node.title_number is not None for node in roots),
            "recent_legislation_root_count": sum(
                node.is_recent_legislation_root for node in roots
            ),
            "subtree_request_count": len(self.subtree_response_sha256),
            "subtree_request_membership_valid": receipt_membership_valid,
            "verified_node_count": sum(node.evidence_verified for node in self.nodes),
            "node_count": len(self.nodes),
            "descendant_node_count": len(self.nodes) - len(roots),
            "document_locator_count": len(documents),
            "main_code_document_locator_count": len(main_documents),
            "recent_legislation_document_locator_count": len(recent_documents),
            "current_path_document_locator_count": sum(
                node.document_family == "current" for node in main_documents
            ),
            "future_path_document_locator_count": sum(
                node.document_family == "future" for node in main_documents
            ),
            "individually_labeled_section_locator_count": len(section_nodes),
            "unique_section_identity_count": len(sections),
            "duplicate_section_identity_count": len(duplicate_sections),
            "extra_section_variant_locator_count": sum(
                count - 1 for count in sections.values() if count > 1
            ),
            "duplicate_section_identities": duplicate_sections,
            "document_disposition_counts": dict(sorted(dispositions.items())),
            "current_body_candidate_locator_count": len(current_candidates),
            "duplicate_current_citation_identity_count": len(
                duplicate_current_sections
            ),
            "duplicate_current_citation_locator_count": (
                duplicate_current_locator_count
            ),
            "reusable_body_candidate_locator_count": (
                reusable_body_candidate_count
            ),
            "body_identity_residual_locator_count": (
                duplicate_current_locator_count + len(recent_documents)
                + dispositions.get("untyped_current_document_residual", 0)
            ),
            "body_excluded_document_like_node_count": (
                dispositions.get("future_effectiveness_excluded", 0)
                + dispositions.get("future_structural_placeholder", 0)
                + dispositions.get("publisher_editorial_structure_excluded", 0)
            ),
            "root_semantic_sha256": canonical_node_digest(roots),
            "all_node_semantic_sha256": canonical_node_digest(self.nodes),
            "main_document_semantic_sha256": canonical_node_digest(main_documents),
            "toc_frontier_closed": toc_closed,
            "document_body_count": 0,
            "body_frontier_closed": False,
            "frontier_closed": False,
            "full_corpus_admissible": False,
        }

    def to_dict(self) -> dict[str, Any]:
        authority_verified = bool(
            self.delegation_verified
            and container_url_matches(self.final_url)
            and self.nodes
            and all(node.evidence_verified for node in self.nodes)
        )
        return {
            "schema_version": "mississippi-lexis-inventory-v1",
            "status": self.status,
            "final_url": self.final_url,
            "observed_at": self.observed_at,
            "delegation_verified": self.delegation_verified,
            "nodes": [node.to_dict() for node in self.nodes],
            "expanded_root_ids": list(self.expanded_root_ids),
            "diagnostics": list(self.diagnostics),
            "root_rendered_sha256": self.root_rendered_sha256,
            "root_rendered_path": self.root_rendered_path,
            "subtree_response_sha256": [
                list(item) for item in self.subtree_response_sha256
            ],
            "subtree_response_paths": [
                list(item) for item in self.subtree_response_paths
            ],
            "frontier": self.frontier,
            "official_legislature_entry_url": OFFICIAL_LEGISLATURE_ENTRY_URL,
            "official_legislature_help_url": OFFICIAL_LEGISLATURE_HELP_URL,
            "official_secretary_of_state_url": OFFICIAL_SECRETARY_OF_STATE_URL,
            "public_entry_url": PUBLIC_ENTRY_URL,
            "public_container_url": PUBLIC_CONTAINER_URL,
            "toc_urn_path": TOC_URN_PATH,
            "toc_source_id": TOC_SOURCE_ID,
            "source_authority_class": "official" if authority_verified else "unverified",
            "rights_scope": {
                "included": [
                    "enacted statutory section text",
                    "statutory captions and section numbers",
                    "legislative histories",
                ],
                "excluded": [
                    "publisher annotations",
                    "case notes",
                    "editorial arrangement and presentation",
                ],
            },
        }

    def write(self, output_path: str | Path) -> Path:
        path = Path(output_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path


def _failed_inventory(status: str, diagnostic: str) -> MississippiLexisInventory:
    return MississippiLexisInventory(
        status=status,
        final_url="",
        observed_at=datetime.now(UTC).isoformat(),
        delegation_verified=False,
        nodes=(),
        expanded_root_ids=(),
        diagnostics=(diagnostic,),
    )


def _retain_live_evidence_path(
    evidence_dir: Path | None,
    *,
    relative: str,
    payload: bytes,
) -> str:
    if evidence_dir is None:
        return ""
    target = (evidence_dir / relative).resolve()
    target.relative_to(evidence_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != payload:
            raise RuntimeError(f"retained Mississippi evidence collision: {target}")
    else:
        target.write_bytes(payload)
    return target.relative_to(evidence_dir).as_posix()


async def _live_toc_patch(
    page: Any,
    *,
    endpoint: str,
    patch_body: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    raw = await page.evaluate(
        """
        async ({endpoint, patchBody}) => {
          const headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
          };
          const requestId = new URL(location.href).searchParams.get('crid');
          if (requestId) headers['X-LN-CurrentRequestId'] = requestId;
          const response = await fetch(endpoint, {
            method: 'PATCH', credentials: 'same-origin', headers,
            body: JSON.stringify(patchBody)
          });
          return {
            status: response.status,
            contentType: response.headers.get('content-type') || '',
            text: await response.text()
          };
        }
        """,
        {"endpoint": endpoint, "patchBody": dict(patch_body)},
    )
    return raw if isinstance(raw, Mapping) else None


async def _live_toc_patch_with_retries(
    page: Any,
    *,
    endpoint: str,
    patch_body: Mapping[str, Any],
    retry_count: int,
) -> tuple[Mapping[str, Any] | None, str]:
    result: Mapping[str, Any] | None = None
    last_error = ""
    for attempt in range(retry_count):
        result = await _live_toc_patch(
            page,
            endpoint=endpoint,
            patch_body=patch_body,
        )
        if (
            result is not None
            and int(result.get("status") or 0) == 200
            and "json" in str(result.get("contentType") or "").lower()
        ):
            return result, ""
        last_error = f"HTTP {result.get('status') if result else 'missing'}"
        if result is not None and int(result.get("status") or 0) == 200:
            last_error += " with non-JSON content type"
        await asyncio.sleep(min(1.0, 0.15 * (attempt + 1)))
    return result, last_error


async def discover_live_inventory(
    *,
    retries: int = DEFAULT_RETRIES,
    request_delay_seconds: float = 0.05,
    timeout_ms: int = 60_000,
    require_enabled: bool = True,
    evidence_dir: str | Path | None = None,
    retain_parser_input: Callable[..., None] | None = None,
) -> MississippiLexisInventory:
    """Fetch only the exact rendered root and 51 complete TOC subtrees."""

    if require_enabled and not enabled():
        return _failed_inventory(
            "disabled", f"set {ENABLE_ENV}=1 to enable live inventory"
        )
    retry_count = max(1, min(int(retries), 5))
    delay = max(0.0, min(float(request_delay_seconds), 2.0))
    timeout = max(5_000, min(int(timeout_ms), 120_000))
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        return _failed_inventory("unavailable", f"playwright unavailable: {exc}")

    observed_at = datetime.now(UTC).isoformat()
    diagnostics: list[str] = []
    nodes_by_id: dict[str, MississippiLexisNode] = {}
    expanded_roots: list[str] = []
    response_hashes: list[tuple[str, str]] = []
    response_paths: list[tuple[str, str]] = []
    final_url = ""
    root_hash = ""
    root_path = ""
    delegation_verified = False
    status = "unavailable"
    evidence_root = (
        Path(evidence_dir).expanduser().resolve()
        if evidence_dir is not None
        else None
    )
    if evidence_root is not None:
        evidence_root.mkdir(parents=True, exist_ok=True)

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    locale="en-US",
                )
                page = await context.new_page()
                navigation = await page.goto(
                    PUBLIC_CONTAINER_URL,
                    wait_until="domcontentloaded",
                    timeout=timeout,
                    referer=OFFICIAL_LEGISLATURE_ENTRY_URL,
                )
                await page.wait_for_selector("li.js-node", timeout=min(timeout, 30_000))
                final_url = str(page.url or "")
                body_text = str(await page.locator("body").inner_text() or "")
                html = str(await page.content() or "")
                root_bytes = html.encode("utf-8")
                root_hash = hashlib.sha256(root_bytes).hexdigest()
                response_status = int(getattr(navigation, "status", 0) or 0)
                if response_status != 200:
                    raise RuntimeError(
                        "Mississippi rendered root returned HTTP "
                        f"{response_status or 'unknown'}"
                    )
                if retain_parser_input is not None:
                    retain_parser_input(
                        body=root_bytes,
                        media_type="text/html",
                        observed_at=observed_at,
                        official_url=PUBLIC_CONTAINER_URL,
                        response_status=response_status,
                        sanitized_request=canonical_rendered_root_request(),
                    )
                root_path = _retain_live_evidence_path(
                    evidence_root,
                    relative=f"root-rendered-{root_hash}.html",
                    payload=root_bytes,
                )
                delegation_verified = bool(
                    container_url_matches(final_url)
                    and _DELEGATION_RE.search(body_text)
                    and not _BLOCKED_RE.search(body_text)
                )
                if not delegation_verified:
                    diagnostics.append(
                        "exact free-public-access container banner was not verified"
                    )
                    status = "invalid_source"
                else:
                    dom_rows = await page.evaluate(
                        """
                        () => Array.from(
                          document.querySelectorAll('li.js-node[data-level="1"]')
                        ).map(el => ({
                          nodeid: el.getAttribute('data-nodeid') || '',
                          nodepath: el.getAttribute('data-nodepath') || '',
                          level: el.getAttribute('data-level') || '',
                          title: el.getAttribute('data-title') || '',
                          canexpand: el.getAttribute('data-canexpand') || '',
                          canopen: el.getAttribute('data-canopen') || '',
                          haschildren: el.getAttribute('data-haschildren') || '',
                          targetlevels: Array.from(
                            el.querySelectorAll(
                              ':scope > .js-node-header [data-command="open-to"]'
                            )
                          ).map(item => item.getAttribute('data-targetlevel') || '')
                        }))
                        """
                    )
                    root_nodes = parse_root_dom_rows(
                        dom_rows
                        if isinstance(dom_rows, Sequence)
                        and not isinstance(dom_rows, (str, bytes, bytearray))
                        else ()
                    )
                    membership_error = root_membership_error(root_nodes)
                    bound_roots = _bind_live_nodes(
                        root_nodes,
                        source_url=final_url,
                        observed_at=observed_at,
                        receipt_sha256=root_hash,
                    )
                    if membership_error or len(bound_roots) != EXPECTED_ROOT_COUNT:
                        diagnostics.append(
                            membership_error or "live root evidence binding failed"
                        )
                        status = "partial_toc"
                    else:
                        target_levels: dict[str, int] = {}
                        for row in dom_rows:
                            node_id = str(row.get("nodeid") or "").strip()
                            raw_levels = row.get("targetlevels")
                            if not isinstance(raw_levels, Sequence) or isinstance(
                                raw_levels, (str, bytes, bytearray)
                            ):
                                diagnostics.append(
                                    f"root {node_id} omitted open-to levels"
                                )
                                break
                            levels = [_as_int(value) for value in raw_levels]
                            if (
                                not levels
                                or any(
                                    level is None
                                    or not 2 <= level <= MAX_EXHAUSTIVE_TOC_LEVEL
                                    for level in levels
                                )
                                or len(levels) != len(set(levels))
                            ):
                                diagnostics.append(
                                    f"root {node_id} exposed invalid open-to levels"
                                )
                                break
                            target_levels[node_id] = max(
                                level for level in levels if level is not None
                            )
                        if not diagnostics and set(target_levels) != set(
                            EXPECTED_ROOT_NODE_IDS
                        ):
                            diagnostics.append(
                                "open-to request membership did not align with AAB..ABZ"
                            )
                        nodes_by_id.update(
                            {node.node_id: node for node in bound_roots}
                        )
                        for parent in bound_roots:
                            if diagnostics:
                                break
                            target_level = target_levels[parent.node_id]
                            endpoint, patch_body = toc_open_to_request(
                                parent.node_id,
                                target_level=target_level,
                            )
                            (
                                canonical_endpoint,
                                request_body,
                                sanitized_request,
                            ) = (
                                canonical_toc_patch_request(parent)
                            )
                            if (
                                canonical_endpoint != endpoint
                                or _canonical_json_bytes(patch_body) != request_body
                                or max(parent.open_to_levels) != target_level
                            ):
                                diagnostics.append(
                                    f"root {parent.node_id} target-level identity drifted"
                                )
                                break
                            result, request_error = await _live_toc_patch_with_retries(
                                page,
                                endpoint=endpoint,
                                patch_body=patch_body,
                                retry_count=retry_count,
                            )
                            if request_error or result is None:
                                diagnostics.append(
                                    f"root open-to {parent.node_id} failed: "
                                    f"{request_error or 'missing response'}"
                                )
                                break
                            response_text = str(result.get("text") or "")
                            response_bytes = response_text.encode("utf-8")
                            response_hash = hashlib.sha256(response_bytes).hexdigest()
                            if retain_parser_input is not None:
                                retain_parser_input(
                                    body=response_bytes,
                                    media_type="application/json",
                                    observed_at=observed_at,
                                    official_url=endpoint,
                                    response_status=int(result.get("status") or 0),
                                    sanitized_request=sanitized_request,
                                )
                            retained_path = _retain_live_evidence_path(
                                evidence_root,
                                relative=(
                                    "root-open-to/"
                                    f"{parent.node_id}-level-{target_level}-"
                                    f"{response_hash}.json"
                                ),
                                payload=response_bytes,
                            )
                            try:
                                payload = json.loads(response_text)
                            except json.JSONDecodeError:
                                diagnostics.append(
                                    f"root open-to {parent.node_id} returned invalid JSON"
                                )
                                break
                            descendants, _closed_ids, parse_error = (
                                parse_title_subtree_payload(
                                    payload,
                                    parent=parent,
                                    target_level=target_level,
                                )
                            )
                            if parse_error:
                                diagnostics.append(
                                    f"root open-to {parent.node_id}: {parse_error}"
                                )
                                break
                            bound_descendants = _bind_live_nodes(
                                descendants,
                                source_url=final_url,
                                observed_at=observed_at,
                                receipt_sha256=response_hash,
                            )
                            if len(bound_descendants) != len(descendants):
                                diagnostics.append(
                                    f"root open-to {parent.node_id}: evidence binding failed"
                                )
                                break
                            if set(nodes_by_id).intersection(
                                node.node_id for node in bound_descendants
                            ):
                                diagnostics.append(
                                    f"root open-to {parent.node_id}: node ID crossed roots"
                                )
                                break
                            nodes_by_id.update(
                                {node.node_id: node for node in bound_descendants}
                            )
                            expanded_roots.append(parent.node_id)
                            response_hashes.append((parent.node_id, response_hash))
                            if retained_path:
                                response_paths.append((parent.node_id, retained_path))
                            if delay:
                                await asyncio.sleep(delay)
                        status = "complete" if not diagnostics else "partial_toc"
            finally:
                await browser.close()
    except Exception as exc:  # noqa: BLE001 - browser/network boundary is fail closed
        diagnostics.append(f"live inventory failed: {type(exc).__name__}: {exc}")
        status = "unavailable"

    ordered = tuple(
        sorted(nodes_by_id.values(), key=lambda node: (node.level, node.node_path))
    )
    return MississippiLexisInventory(
        status=status,
        final_url=final_url,
        observed_at=observed_at,
        delegation_verified=delegation_verified,
        nodes=ordered,
        expanded_root_ids=tuple(expanded_roots),
        diagnostics=tuple(diagnostics),
        root_rendered_sha256=root_hash,
        subtree_response_sha256=tuple(response_hashes),
        root_rendered_path=root_path,
        subtree_response_paths=tuple(response_paths),
    )
