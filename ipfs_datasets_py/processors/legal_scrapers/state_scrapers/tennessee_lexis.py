"""Strict parser contract for Tennessee's delegated Lexis Code source.

This module contains only pure, source-derived parsing and request-identity
logic.  Network, cache, WARC, Wayback, retention, and publication closure stay
in the existing shared scraper infrastructure.  In particular, a Lexis TOC
``PATCH`` response is replayable only when the exact method and request-body
digest are present in the prospective acquisition ledger; it must never be
substituted with an archived ``GET`` response.

The current 2026-08-26 diagnostic observation is recorded below as a drift
sentinel, not as reusable evidence.  Raw authority, hierarchy, and body bytes
remain necessary before any Tennessee corpus can be published.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

ADVANCE_ORIGIN = "https://advance.lexis.com"
PUBLIC_ENTRY_URL = "https://www.lexisnexis.com/hottopics/tncode"
PUBLIC_CONTAINER_CONFIG = (
    "014CJAA5ZGVhZjA3NS02MmMzLTRlZWQtOGJjNC00YzQ1MmZlNzc2YWYK"
    "AFBvZENhdGFsb2e9zYpNUjTRaIWVfyrur9ud"
)
PUBLIC_CONTAINER_URL = f"{ADVANCE_ORIGIN}/container?config={PUBLIC_CONTAINER_CONFIG}"
TOC_ROOT_ID = "6gf5kkk"
TOC_ENDPOINT_PATH = f"/r/tocprovider/{TOC_ROOT_ID}/toc/{TOC_ROOT_ID}"
TOC_ENDPOINT_URL = f"{ADVANCE_ORIGIN}{TOC_ENDPOINT_PATH}"
GENERAL_ASSEMBLY_PUBLICATIONS_URL = (
    "https://wapp.capitol.tn.gov/apps/WebPublications/"
)
NONSTATUTORY_ROOT_LABEL = "Volume 13 Tables"
MAX_EXHAUSTIVE_TOC_LEVEL = 12

# Diagnostic-only measurements from the bounded 2026-08-26 observation.
# They intentionally do not authorize a parser input or output row.
OBSERVED_SOURCE_ROOT_COUNT = 72
OBSERVED_TITLE_ROOT_COUNT = 71
OBSERVED_EXPANDABLE_TITLE_COUNT = 69
OBSERVED_DIRECT_TITLE_DOCUMENT_COUNT = 2
OBSERVED_SUBTREE_RESPONSE_COUNT = 69
OBSERVED_DESCENDANT_NODE_COUNT = 40_193
OBSERVED_DESCENDANT_CONTAINER_COUNT = 4_149
OBSERVED_DESCENDANT_DOCUMENT_COUNT = 36_044
OBSERVED_DOCUMENT_COUNT = 36_046
OBSERVED_ALL_STATUTORY_NODE_COUNT = 40_264
OBSERVED_CATALOG_TERMINAL_COUNT = 1_359
OBSERVED_CATALOG_TERMINAL_COUNTS: Mapping[str, int] = {
    "expired": 16,
    "obsolete": 9,
    "repealed": 720,
    "reserved": 561,
    "transferred": 53,
}
OBSERVED_CITATION_LABEL_COUNT = 35_359
OBSERVED_UNIQUE_CITATION_LABEL_COUNT = 35_159
OBSERVED_REPEATED_CITATION_IDENTITY_COUNT = 182
OBSERVED_LEVEL_COUNTS: Mapping[str, int] = {
    "L1": 2,
    "L2": 1_119,
    "L3": 9_618,
    "L4": 25_299,
    "L5": 4_157,
}
OBSERVED_STRICT_REUSABLE_INPUT_COUNT = 0
OBSERVED_AUTHORITY_CATALOG_RESIDUAL_COUNT = 72
OBSERVED_BODY_RESIDUAL_COUNT = 36_046
OBSERVED_TOTAL_RESIDUAL_COUNT = 36_118

OBSERVED_ROOT_MEMBERSHIP_SHA256 = (
    "88135a531583ec0784f72ab7ec436e282f61da93df58e0c86b98f65983620566"
)
OBSERVED_ALL_NODE_MEMBERSHIP_SHA256 = (
    "ea80e34aff88bc2d289494ff1ab67c2d53193d1b5f086000510b7cafa31d8826"
)
OBSERVED_DOCUMENT_MEMBERSHIP_SHA256 = (
    "8bfc62cda73e7529b30f5848d7cb9128c341d6c0f8910c6ed08dc0beb58d7286"
)
OBSERVED_ORDERED_CONTENT_PATH_SHA256 = (
    "af6b3962a8eedc12d5f76d98608deee37c8398b30236829b504986c42234599b"
)
OBSERVED_SUBTREE_MANIFEST_SHA256 = (
    "29570e7e953a0b80ba32a9245c94b05cbb0076e1c4283eb59e88853b90ccd40a"
)

_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DOCUMENT_PATH_RE = re.compile(
    r"^/shared/document/statutes-legislation/"
    r"urn:contentItem:[A-Za-z0-9:-]+$",
    re.IGNORECASE,
)
_CONTENT_ITEM_RE = re.compile(
    r"/urn:contentItem:(?P<item>[A-Za-z0-9:-]+)$",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(
    r"^TITLE\s+(?P<number>\d{1,2})(?:\s*[.\-\u2013\u2014:]\s*|\s+)"
    r"(?P<label>.+?)\s*$",
    re.IGNORECASE,
)
_SECTION_COMPONENT_PATTERN = r"[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*"
_SECTION_NUMBER_PATTERN = (
    rf"[1-9]\d?-{_SECTION_COMPONENT_PATTERN}-{_SECTION_COMPONENT_PATTERN}"
)
_SECTION_RE = re.compile(
    rf"(?<![0-9A-Za-z.-])(?P<number>{_SECTION_NUMBER_PATTERN})"
    r"(?![0-9A-Za-z.-])",
    re.IGNORECASE,
)
_PRIMARY_SECTION_RE = re.compile(
    rf"^(?:(?:Tenn(?:essee)?\.?\s+Code(?:\s+Ann\.?)?|TCA)\s*)?"
    rf"(?:\u00a7\s*)?(?P<number>{_SECTION_NUMBER_PATTERN})"
    r"(?:\s*[.\-\u2013\u2014:]\s*|\s+|$)",
    re.IGNORECASE,
)
_CATALOG_TERMINAL_RE = re.compile(
    r"(?:^|[.\-\u2013\u2014:\s])"
    r"[\[(]?\s*(?P<kind>repealed|reserved|transferred|expired|obsolete)"
    r"\b[^\]\)]{0,100}[\])]?\s*[.]?\s*$",
    re.IGNORECASE,
)
_BODY_TERMINAL_RE = re.compile(
    r"^[\[(]?\s*(?P<kind>repealed|reserved|transferred|expired|obsolete)\b",
    re.IGNORECASE,
)
_BLOCKED_PAGE_RE = re.compile(
    r"robot\s*validation|robotvalidation|captcha|confirm\s+you\s+are\s+human|"
    r"complete\s+the\s+security\s+check|signin\.lexisnexis\.com|"
    r"sign\s+in\s+to\s+continue|browser\s+redirect\s+to\s+the\s+intended\s+"
    r"destination|\bI\s+Agree\b.*?(?:terms|conditions)|"
    r"(?:terms|conditions).*?\bI\s+Agree\b|\bResults\s+for\s*:",
    re.IGNORECASE | re.DOTALL,
)
_WS_RE = re.compile(r"\s+")
_EDITORIAL_HEADING_RE = re.compile(
    r"^(?:annotations?|case\s+notes?|notes?\s+to\s+decisions?|"
    r"research\s+references?|law\s+reviews?|treatises?|practice\s+aids?|"
    r"cross\s+references?|editor(?:'s|ial)?\s+notes?)\s*[:.]?$",
    re.IGNORECASE,
)
_TEMPORAL_MARKER_RE = re.compile(
    r"\b(?:effective\s+(?:until|through|on|from|upon)|expires?\s+(?:on\s+)?|"
    r"contingent\s+upon|if\s+and\s+when)\b[^\n.]{0,180}",
    re.IGNORECASE,
)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(value: object) -> str:
    """Hash one stable semantic projection."""

    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _clean(value: object) -> str:
    return _WS_RE.sub(" ", str(value or "").replace("\xa0", " ")).strip()


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _mapping_lower(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key).casefold(): item for key, item in value.items()}


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


def container_url_matches(value: object) -> bool:
    """Require the exact public Tennessee container plus optional session IDs."""

    parsed = urlparse(str(value or ""))
    if not (
        _exact_advance_origin(parsed)
        and parsed.path == "/container"
        and not parsed.params
        and not parsed.fragment
    ):
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    if query.get("config") != [PUBLIC_CONTAINER_CONFIG]:
        return False
    if not set(query).issubset({"config", "crid", "prid"}):
        return False
    return all(
        len(query.get(key, [])) == 1
        and bool(re.fullmatch(r"[A-Za-z0-9-]{1,128}", query[key][0]))
        for key in set(query) - {"config"}
    )


def is_document_path(value: object) -> bool:
    """Return whether *value* is an exact public statute content-item path."""

    text = str(value or "").strip()
    parsed = urlparse(urljoin(ADVANCE_ORIGIN, text))
    return bool(
        _exact_advance_origin(parsed)
        and not parsed.query
        and not parsed.params
        and not parsed.fragment
        and _DOCUMENT_PATH_RE.fullmatch(parsed.path or "")
    )


def document_url(value: object) -> str:
    """Return the canonical HTTPS page URL for one validated content item."""

    if not is_document_path(value):
        raise ValueError(f"invalid Tennessee Lexis document path: {value!r}")
    return urljoin(ADVANCE_ORIGIN, str(value).strip())


def content_item_id(value: object) -> str:
    parsed = urlparse(urljoin(ADVANCE_ORIGIN, str(value or "").strip()))
    match = _CONTENT_ITEM_RE.search(parsed.path or "")
    return str(match.group("item") or "") if match else ""


def catalog_terminal_disposition(value: object) -> str:
    """Classify only an explicit terminal status at the end of a TOC label."""

    match = _CATALOG_TERMINAL_RE.search(_clean(value))
    return str(match.group("kind") or "").casefold() if match else ""


@dataclass(frozen=True)
class TennesseeLexisNode:
    """One source-ordered Tennessee Lexis TOC node."""

    node_id: str
    title: str
    level: int
    node_path: str
    can_expand: bool
    can_open: bool
    has_children: bool
    link_href: str = ""
    open_to_levels: tuple[int, ...] = ()

    @property
    def title_number(self) -> str | None:
        match = _TITLE_RE.match(_clean(self.title))
        return str(int(match.group("number"))) if match else None

    @property
    def title_label(self) -> str:
        match = _TITLE_RE.match(_clean(self.title))
        return _clean(match.group("label")) if match else ""

    @property
    def section_number(self) -> str | None:
        title = _clean(self.title)
        match = _PRIMARY_SECTION_RE.match(title)
        if match is None or re.match(
            r"\s+(?:through|to)\b",
            title[match.end("number") :],
            re.IGNORECASE,
        ):
            return None
        return str(match.group("number"))

    @property
    def is_document_locator(self) -> bool:
        return bool(self.link_href and is_document_path(self.link_href))

    @property
    def content_item_id(self) -> str:
        return content_item_id(self.link_href)

    @property
    def terminal_disposition(self) -> str:
        return catalog_terminal_disposition(self.title)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.update(
            {
                "content_item_id": self.content_item_id,
                "is_document_locator": self.is_document_locator,
                "section_number": self.section_number,
                "terminal_disposition": self.terminal_disposition,
                "title_label": self.title_label,
                "title_number": self.title_number,
            }
        )
        return value


def _node_shape_error(node: TennesseeLexisNode) -> str:
    if not _NODE_ID_RE.fullmatch(node.node_id):
        return "invalid node id"
    parts = [part for part in node.node_path.split("/") if part]
    if (
        not node.title
        or len(parts) < 2
        or parts[0] != "ROOT"
        or parts[-1] != node.node_id
        or node.level != len(parts) - 1
        or any(not _NODE_ID_RE.fullmatch(part) for part in parts[1:])
    ):
        return "node level/path/title mismatch"
    if node.link_href and not is_document_path(node.link_href):
        return "node exposed a nonstatutory or unsafe document path"
    if node.link_href and (node.can_expand or node.has_children):
        return "document node also claimed expandable children"
    if node.open_to_levels and any(
        level < 2 or level > MAX_EXHAUSTIVE_TOC_LEVEL
        for level in node.open_to_levels
    ):
        return "node advertised an invalid open-to level"
    if tuple(sorted(set(node.open_to_levels))) != node.open_to_levels:
        return "node advertised missing or duplicate open-to levels"
    return ""


def _node_from_mapping(value: Mapping[str, Any]) -> TennesseeLexisNode | None:
    props_raw = value.get("props")
    if not isinstance(props_raw, Mapping):
        return None
    props = _mapping_lower(props_raw)
    raw = _mapping_lower(value)
    if not any(
        key in props
        for key in (
            "nodeid",
            "nodepath",
            "level",
            "linktemplatetitle",
            "title",
            "canexpand",
            "canopen",
            "haschildren",
            "linkhref",
            "docfullpath",
        )
    ):
        return None
    node_id = _clean(raw.get("id") or props.get("nodeid"))
    title = _clean(props.get("linktemplatetitle") or props.get("title"))
    levels_raw = props.get("targetlevels") or ()
    if isinstance(levels_raw, Sequence) and not isinstance(
        levels_raw, (str, bytes, bytearray)
    ):
        levels = tuple(
            sorted(
                {
                    level
                    for item in levels_raw
                    if (level := _as_int(item)) is not None
                }
            )
        )
    else:
        levels = ()
    node = TennesseeLexisNode(
        node_id=node_id,
        title=title,
        level=_as_int(props.get("level")) or 0,
        node_path=_clean(props.get("nodepath")),
        can_expand=_as_bool(props.get("canexpand")),
        can_open=_as_bool(props.get("canopen")),
        has_children=_as_bool(props.get("haschildren")),
        link_href=_clean(props.get("linkhref") or props.get("docfullpath")),
        open_to_levels=levels,
    )
    return node if not _node_shape_error(node) else None


def parse_root_dom_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_titles: Sequence[tuple[str, str]],
) -> tuple[list[TennesseeLexisNode], TennesseeLexisNode]:
    """Validate exact source-ordered Title 1-71 roots and the tables root."""

    parsed: list[TennesseeLexisNode] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for row_value in rows:
        row = _mapping_lower(row_value)
        raw_levels = row.get("targetlevels") or ()
        if not isinstance(raw_levels, Sequence) or isinstance(
            raw_levels, (str, bytes, bytearray)
        ):
            raw_levels = ()
        levels: list[int] = []
        for item in raw_levels:
            level = _as_int(item)
            if level is None:
                raise ValueError("Tennessee root advertised a non-integer open-to level")
            levels.append(level)
        link_href = _clean(
            row.get("docfullpath")
            or row.get("data-docfullpath")
            or row.get("linkhref")
            or row.get("href")
        )
        node = TennesseeLexisNode(
            node_id=_clean(row.get("nodeid") or row.get("data-nodeid")),
            title=_clean(row.get("title") or row.get("data-title")),
            level=_as_int(row.get("level") or row.get("data-level")) or 0,
            node_path=_clean(row.get("nodepath") or row.get("data-nodepath")),
            can_expand=_as_bool(
                row.get("canexpand") or row.get("data-canexpand")
            ),
            can_open=_as_bool(row.get("canopen") or row.get("data-canopen")),
            has_children=_as_bool(
                row.get("haschildren") or row.get("data-haschildren")
            ),
            link_href=link_href,
            open_to_levels=tuple(sorted(set(levels))),
        )
        error = _node_shape_error(node)
        if (
            error
            or node.level != 1
            or node.node_path != f"/ROOT/{node.node_id}"
            or node.node_id in seen_ids
            or node.node_path in seen_paths
            or len(levels) != len(set(levels))
        ):
            raise ValueError(
                "Tennessee rendered root contains a malformed or duplicate node: "
                f"{node.node_id or '<missing>'} ({error or 'root mismatch'})"
            )
        seen_ids.add(node.node_id)
        seen_paths.add(node.node_path)
        parsed.append(node)

    tables = [
        node for node in parsed if _clean(node.title).casefold() == NONSTATUTORY_ROOT_LABEL.casefold()
    ]
    statutory = [node for node in parsed if node not in tables]
    expected = [(str(int(number)), _clean(label)) for number, label in expected_titles]
    if len(parsed) != len(expected) + 1 or len(tables) != 1:
        raise ValueError(
            "Tennessee root must contain exactly 71 statutory titles and one tables root"
        )
    observed_numbers = [node.title_number for node in statutory]
    if observed_numbers != [number for number, _label in expected]:
        raise ValueError("Tennessee title roots changed source order or membership")
    for node, (number, expected_label) in zip(statutory, expected, strict=True):
        if _clean(node.title_label).casefold() != expected_label.casefold():
            raise ValueError(
                f"Tennessee Title {number} label drifted: {node.title_label!r}"
            )
        direct_reserved = number in {"19", "51"}
        if direct_reserved:
            if not (
                node.title_label == "[Reserved]"
                and node.is_document_locator
                and node.can_open
                and not node.can_expand
                and not node.has_children
                and not node.open_to_levels
            ):
                raise ValueError(
                    f"Tennessee Title {number} is not the exact direct reserved document"
                )
        elif not (
            (node.can_expand or node.has_children)
            and not node.link_href
            and node.open_to_levels
        ):
            raise ValueError(
                f"Tennessee Title {number} omitted its complete open-to contract"
            )
    return statutory, tables[0]


def parse_root_html(
    html: str,
    *,
    expected_titles: Sequence[tuple[str, str]],
) -> tuple[list[TennesseeLexisNode], TennesseeLexisNode]:
    """Extract and validate rendered ``li.js-node`` root attributes."""

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - production dependency
        raise RuntimeError("BeautifulSoup is required for Tennessee Lexis parsing") from exc
    source = str(html or "")
    if _BLOCKED_PAGE_RE.search(source):
        raise ValueError("Tennessee container returned an access or bootstrap shell")
    soup = BeautifulSoup(source, "html.parser")
    rows: list[dict[str, Any]] = []
    for element in soup.select("li.js-node"):
        header = element.select_one(":scope > .js-node-header") or element
        anchor = header.find("a", href=True)
        rows.append(
            {
                "nodeid": element.get("data-nodeid") or "",
                "nodepath": element.get("data-nodepath") or "",
                "level": element.get("data-level") or "",
                "title": element.get("data-title") or "",
                "canexpand": element.get("data-canexpand") or "",
                "canopen": element.get("data-canopen") or "",
                "haschildren": element.get("data-haschildren") or "",
                "docfullpath": (
                    element.get("data-docfullpath")
                    or (anchor.get("href") if anchor is not None else "")
                    or ""
                ),
                "targetlevels": [
                    item.get("data-targetlevel") or ""
                    for item in header.select('[data-command="open-to"]')
                ],
            }
        )
    if not rows:
        raise ValueError("Tennessee container exposed no rendered TOC roots")
    return parse_root_dom_rows(rows, expected_titles=expected_titles)


def toc_open_to_request(
    node_id: object,
    *,
    target_level: object,
) -> tuple[str, dict[str, Any]]:
    """Build one complete-title Lexis TOC request, never a node loop."""

    normalized = _clean(node_id)
    if not _NODE_ID_RE.fullmatch(normalized):
        raise ValueError(f"invalid Tennessee Lexis node id: {node_id!r}")
    level = _as_int(target_level)
    if level is None or level < 2 or level > MAX_EXHAUSTIVE_TOC_LEVEL:
        raise ValueError(
            f"target_level must be between 2 and {MAX_EXHAUSTIVE_TOC_LEVEL}"
        )
    return (
        TOC_ENDPOINT_URL,
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
    node: TennesseeLexisNode,
) -> tuple[str, bytes, dict[str, Any]]:
    """Bind a title's maximum advertised level to exact PATCH bytes."""

    if not (
        node.level == 1
        and node.title_number
        and (node.can_expand or node.has_children)
        and node.open_to_levels
    ):
        raise ValueError("Tennessee TOC PATCH requires an expandable title root")
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


def _is_node_shaped_mapping(value: Mapping[str, Any]) -> bool:
    props = value.get("props")
    if not isinstance(props, Mapping):
        return False
    lowered = _mapping_lower(props)
    return any(
        key in lowered
        for key in (
            "nodeid",
            "nodepath",
            "level",
            "linktemplatetitle",
            "title",
            "canexpand",
            "canopen",
            "haschildren",
            "linkhref",
            "docfullpath",
        )
    )


def parse_title_subtree_payload(
    payload: object,
    *,
    parent: TennesseeLexisNode,
    target_level: int,
) -> tuple[list[TennesseeLexisNode], tuple[str, ...], str]:
    """Validate one deepest-level response as an exact title subtree."""

    if not (
        parent.level == 1
        and parent.title_number
        and (parent.can_expand or parent.has_children)
        and parent.node_path == f"/ROOT/{parent.node_id}"
    ):
        return [], (), "parent is not an expandable Tennessee title root"
    if (
        isinstance(target_level, bool)
        or not isinstance(target_level, int)
        or target_level < 2
        or target_level > MAX_EXHAUSTIVE_TOC_LEVEL
        or target_level != max(parent.open_to_levels or (0,))
    ):
        return [], (), "target level is not the source-advertised maximum"
    if not isinstance(payload, Mapping):
        return [], (), "TOC response is not a JSON object"
    props = payload.get("props")
    if isinstance(props, Mapping) and props.get("error"):
        return [], (), "TOC response contains a source error"

    nodes: list[TennesseeLexisNode] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    malformed = False

    def _walk(value: object) -> None:
        nonlocal malformed
        if isinstance(value, Mapping):
            if _is_node_shaped_mapping(value):
                node = _node_from_mapping(value)
                if (
                    node is None
                    or node.node_id in seen_ids
                    or node.node_path in seen_paths
                ):
                    malformed = True
                else:
                    seen_ids.add(node.node_id)
                    seen_paths.add(node.node_path)
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
        return [], (), "subtree contains no TOC descendants"

    prefix = f"{parent.node_path}/"
    paths = {parent.node_path, *(node.node_path for node in nodes)}
    document_paths: list[str] = []
    for node in nodes:
        immediate_parent = node.node_path.rsplit("/", 1)[0]
        if (
            not node.node_path.startswith(prefix)
            or node.level <= 1
            or node.level > target_level
            or immediate_parent not in paths
        ):
            return [], (), "subtree contains a node outside its exact title hierarchy"
        if node.section_number and node.section_number.split("-", 1)[0] != parent.title_number:
            return [], (), "subtree citation crossed its requested title"
        if node.is_document_locator:
            document_paths.append(node.link_href)
        elif not (node.can_expand or node.has_children):
            return [], (), "subtree contains an untyped non-document terminal leaf"

    expandable = [
        node for node in (parent, *nodes) if node.can_expand or node.has_children
    ]
    for node in expandable:
        if not any(
            candidate.level == node.level + 1
            and candidate.node_path.rsplit("/", 1)[0] == node.node_path
            for candidate in nodes
        ):
            return [], (), f"expandable node {node.node_id} has no direct child"
    if len(document_paths) != len(set(document_paths)):
        return [], (), "subtree repeats a content-item path"
    return nodes, tuple(node.node_id for node in expandable), ""


def derive_exact_metadata_frontier(
    title_roots: Sequence[TennesseeLexisNode],
    *,
    subtrees_by_root_id: Mapping[str, Sequence[TennesseeLexisNode]],
) -> dict[str, Any]:
    """Derive exact source-order algebra without deduplicating citations."""

    roots = list(title_roots)
    expandable = [node for node in roots if node.can_expand or node.has_children]
    if set(subtrees_by_root_id) != {node.node_id for node in expandable}:
        raise ValueError("Tennessee subtree responses do not align with expandable roots")

    all_nodes: list[TennesseeLexisNode] = []
    documents: list[TennesseeLexisNode] = []
    descendants: list[TennesseeLexisNode] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for root in roots:
        branch = list(subtrees_by_root_id.get(root.node_id, ()))
        for node in (root, *branch):
            if node.node_id in seen_ids or node.node_path in seen_paths:
                raise ValueError("Tennessee frontier repeats a semantic node")
            seen_ids.add(node.node_id)
            seen_paths.add(node.node_path)
            all_nodes.append(node)
        descendants.extend(branch)
        documents.extend(node for node in (root, *branch) if node.is_document_locator)

    paths = [node.link_href for node in documents]
    if len(paths) != len(set(paths)):
        raise ValueError("Tennessee frontier repeats a content-item path")
    containers = [node for node in descendants if not node.is_document_locator]
    citations = [node.section_number for node in documents if node.section_number]
    citation_counts: dict[str, int] = {}
    for citation in citations:
        key = str(citation).casefold()
        citation_counts[key] = citation_counts.get(key, 0) + 1
    repeated_citations = sorted(
        key for key, count in citation_counts.items() if count > 1
    )
    terminals: dict[str, int] = {}
    for node in documents:
        disposition = node.terminal_disposition
        if disposition:
            terminals[disposition] = terminals.get(disposition, 0) + 1
    levels: dict[str, int] = {}
    for node in [*descendants, *[root for root in roots if root.is_document_locator]]:
        key = f"L{node.level}"
        levels[key] = levels.get(key, 0) + 1

    node_projection = [
        [node.node_id, node.node_path, node.level, node.title, node.link_href]
        for node in all_nodes
    ]
    document_projection = [
        [node.node_id, node.node_path, node.level, node.title, node.link_href]
        for node in documents
    ]
    root_projection = [
        [node.node_id, node.node_path, node.level, node.title, node.link_href]
        for node in roots
    ]
    return {
        "schema_version": "tennessee-lexis-metadata-frontier-v1",
        "all_node_count": len(all_nodes),
        "all_node_semantic_sha256": canonical_digest(node_projection),
        "catalog_terminal_count": sum(terminals.values()),
        "catalog_terminal_counts": dict(sorted(terminals.items())),
        "citation_label_count": len(citations),
        "descendant_container_count": len(containers),
        "descendant_document_count": sum(
            node.is_document_locator for node in descendants
        ),
        "descendant_node_count": len(descendants),
        "direct_title_document_count": sum(node.is_document_locator for node in roots),
        "document_count": len(documents),
        "document_membership_sha256": canonical_digest(document_projection),
        "document_nodes": documents,
        "expandable_title_count": len(expandable),
        "level_counts": dict(sorted(levels.items())),
        "ordered_content_path_sha256": canonical_digest(paths),
        "ordered_node_path_sha256": canonical_digest(
            [node.node_path for node in all_nodes]
        ),
        "repeated_citation_identities": repeated_citations,
        "repeated_citation_identity_count": len(repeated_citations),
        "subtree_response_count": len(subtrees_by_root_id),
        "title_root_membership_sha256": canonical_digest(root_projection),
        "title_root_count": len(roots),
        "unique_citation_label_count": len(citation_counts),
    }


def observed_metadata_drift(frontier: Mapping[str, Any]) -> dict[str, Any]:
    """Compare a retained source-derived frontier with the diagnostic baseline."""

    expected = {
        "all_node_count": OBSERVED_ALL_STATUTORY_NODE_COUNT,
        "catalog_terminal_count": OBSERVED_CATALOG_TERMINAL_COUNT,
        "citation_label_count": OBSERVED_CITATION_LABEL_COUNT,
        "descendant_container_count": OBSERVED_DESCENDANT_CONTAINER_COUNT,
        "descendant_document_count": OBSERVED_DESCENDANT_DOCUMENT_COUNT,
        "descendant_node_count": OBSERVED_DESCENDANT_NODE_COUNT,
        "direct_title_document_count": OBSERVED_DIRECT_TITLE_DOCUMENT_COUNT,
        "document_count": OBSERVED_DOCUMENT_COUNT,
        "expandable_title_count": OBSERVED_EXPANDABLE_TITLE_COUNT,
        "repeated_citation_identity_count": OBSERVED_REPEATED_CITATION_IDENTITY_COUNT,
        "subtree_response_count": OBSERVED_SUBTREE_RESPONSE_COUNT,
        "title_root_count": OBSERVED_TITLE_ROOT_COUNT,
        "unique_citation_label_count": OBSERVED_UNIQUE_CITATION_LABEL_COUNT,
    }
    differences = {
        key: {"expected": value, "observed": int(frontier.get(key) or 0)}
        for key, value in expected.items()
        if int(frontier.get(key) or 0) != value
    }
    expected_terminals = dict(OBSERVED_CATALOG_TERMINAL_COUNTS)
    observed_terminals = dict(frontier.get("catalog_terminal_counts") or {})
    if observed_terminals != expected_terminals:
        differences["catalog_terminal_counts"] = {
            "expected": expected_terminals,
            "observed": observed_terminals,
        }
    observed_levels = dict(frontier.get("level_counts") or {})
    if observed_levels != dict(OBSERVED_LEVEL_COUNTS):
        differences["level_counts"] = {
            "expected": dict(OBSERVED_LEVEL_COUNTS),
            "observed": observed_levels,
        }
    return differences


def general_assembly_delegation_present(html: str) -> bool:
    """Require the state page's exact Tennessee Code publisher link."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return False
    soup = BeautifulSoup(str(html or ""), "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = urljoin(GENERAL_ASSEMBLY_PUBLICATIONS_URL, str(anchor.get("href") or ""))
        label = _clean(anchor.get_text(" "))
        if href.rstrip("/") == PUBLIC_ENTRY_URL.rstrip("/") and re.search(
            r"\bTennessee\s+Code\b", label, re.IGNORECASE
        ):
            return True
    return False


def publisher_container_delegation_present(html: str) -> bool:
    """Require the publisher entry response to name the exact container."""

    text = str(html or "")
    return bool(
        PUBLIC_CONTAINER_CONFIG in text
        and re.search(r"advance\.lexis\.com(?:/|&(?:#x2F;|sol;))container", text, re.IGNORECASE)
    )


def valid_document_payload(payload: bytes) -> bool:
    """Reject empty and known access/search/bootstrap shells before retention."""

    if not payload:
        return False
    sample = bytes(payload[:100_000]).decode("utf-8", errors="replace")
    return _BLOCKED_PAGE_RE.search(sample) is None and bool(
        re.search(r"<html\b|<main\b|<article\b|data-document-content", sample, re.IGNORECASE)
    )


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


def _chapter_number(section_number: str) -> str:
    parts = section_number.split("-")
    return parts[1] if len(parts) >= 3 else ""


def parse_tennessee_lexis_document_html(
    html: str,
    *,
    source_url: str,
    node: TennesseeLexisNode,
    source_order: int,
    code_name: str = "Tennessee Code Annotated",
) -> tuple[list[NormalizedStatute], dict[str, Any]]:
    """Classify one exact content item as operative, terminal, or residual."""

    residuals: list[dict[str, Any]] = []
    terminals: list[dict[str, Any]] = []
    statutes: list[NormalizedStatute] = []
    canonical_url = document_url(node.link_href) if node.is_document_locator else ""
    if not canonical_url or source_url != canonical_url:
        residuals.append(
            {
                "reason": "document_url_does_not_match_catalog_content_item",
                "source_url": source_url,
            }
        )
    elif _BLOCKED_PAGE_RE.search(str(html or "")):
        residuals.append({"reason": "lexis_access_or_search_shell", "source_url": source_url})
    else:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover - production dependency
            raise RuntimeError("BeautifulSoup is required for Tennessee Lexis parsing") from exc
        soup = BeautifulSoup(str(html or ""), "html.parser")
        for tag in soup(
            ["script", "style", "nav", "header", "footer", "noscript", "form", "button", "aside"]
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
            residuals.append({"reason": "document_content_container_missing", "source_url": source_url})
        else:
            _remove_editorial_sections(content)
            lines = [
                _clean(line)
                for line in content.get_text("\n", strip=True).splitlines()
                if _clean(line)
            ]
            text = "\n".join(lines)
            expected_section = node.section_number or ""
            primary_match = next(
                (
                    match
                    for line in lines[:12]
                    if (match := _PRIMARY_SECTION_RE.match(line))
                ),
                None,
            )
            primary_section = str(primary_match.group("number") or "") if primary_match else ""
            if expected_section and primary_section != expected_section:
                residuals.append(
                    {
                        "catalog_section_number": expected_section,
                        "document_primary_section_number": primary_section,
                        "reason": "catalog_document_section_identity_mismatch",
                    }
                )
            else:
                catalog_terminal = node.terminal_disposition
                nonidentity_lines = [
                    line
                    for line in lines
                    if not expected_section or expected_section not in line
                ]
                terminal_match = next(
                    (
                        match
                        for line in nonidentity_lines[:8]
                        if (match := _BODY_TERMINAL_RE.match(_clean(line)))
                    ),
                    None,
                )
                body_terminal = (
                    str(terminal_match.group("kind") or "").casefold()
                    if terminal_match
                    else ""
                )
                if catalog_terminal and body_terminal == catalog_terminal:
                    terminals.append(
                        {
                            "catalog_node_id": node.node_id,
                            "content_item_id": node.content_item_id,
                            "disposition": catalog_terminal,
                            "section_number": expected_section,
                            "source_order": int(source_order),
                            "source_url": source_url,
                        }
                    )
                elif catalog_terminal and not body_terminal:
                    residuals.append(
                        {
                            "catalog_disposition": catalog_terminal,
                            "reason": "catalog_terminal_not_confirmed_by_document_body",
                            "source_url": source_url,
                        }
                    )
                elif body_terminal:
                    residuals.append(
                        {
                            "body_disposition": body_terminal,
                            "reason": "uncataloged_terminal_body_requires_reconciliation",
                            "source_url": source_url,
                        }
                    )
                elif not expected_section:
                    residuals.append(
                        {
                            "reason": "unclassified_document_without_section_identity",
                            "source_url": source_url,
                        }
                    )
                elif not text:
                    residuals.append({"reason": "empty_unclassified_document", "source_url": source_url})
                else:
                    content_id = node.content_item_id
                    canonical_key = (
                        f"tn:{expected_section.casefold()}:content-{content_id.casefold()}"
                    )
                    caption = _clean(node.title)
                    caption = _PRIMARY_SECTION_RE.sub("", caption, count=1).strip(" .-\u2013\u2014:")
                    temporal_markers = [
                        _clean(match.group(0))
                        for match in _TEMPORAL_MARKER_RE.finditer(text)
                    ]
                    statutes.append(
                        NormalizedStatute(
                            state_code="TN",
                            state_name="Tennessee",
                            statute_id=f"{code_name} \u00a7 {expected_section} [content {content_id}]",
                            code_name=code_name,
                            title_number=expected_section.split("-", 1)[0],
                            chapter_number=_chapter_number(expected_section),
                            section_number=expected_section,
                            section_name=(caption or f"Section {expected_section}")[:200],
                            full_text=text,
                            source_url=source_url,
                            official_cite=f"Tenn. Code Ann. \u00a7 {expected_section}",
                            metadata=StatuteMetadata(),
                            structured_data={
                                "canonical_section_key": canonical_key,
                                "catalog_node_id": node.node_id,
                                "catalog_node_path": node.node_path,
                                "content_item_id": content_id,
                                "discovery_method": "strict_delegated_lexis_content_item",
                                "skip_hydrate": True,
                                "source_authority_class": "official",
                                "source_kind": "official_delegated_tennessee_lexis_code",
                                "source_order": int(source_order),
                                "source_temporal_markers": temporal_markers,
                                "strict_source_closure": True,
                            },
                        )
                    )

    report = {
        "candidate_leaves": 1,
        "closed": bool(
            len(statutes) + len(terminals) == 1 and not residuals
        ),
        "content_item_id": node.content_item_id,
        "operative_sections": len(statutes),
        "parser_residuals": residuals,
        "section_number": node.section_number or "",
        "source_order": int(source_order),
        "source_url": source_url,
        "terminal_dispositions": terminals,
        "terminal_sections": len(terminals),
    }
    return statutes, report


def unresolved_temporal_variant_groups(
    rows: Sequence[NormalizedStatute],
) -> list[dict[str, Any]]:
    """Return repeated citations whose current temporal member is unproved.

    Distinct Lexis content-item paths are intentionally preserved.  A shared
    citation does not itself prove which version is current, so this helper
    reports the complete source-ordered group instead of selecting or
    deduplicating a row from catalog position or text similarity.
    """

    by_citation: dict[str, list[NormalizedStatute]] = {}
    for row in rows:
        citation = str(row.section_number or "").strip().casefold()
        if citation:
            by_citation.setdefault(citation, []).append(row)
    residuals: list[dict[str, Any]] = []
    for citation, variants in by_citation.items():
        if len(variants) < 2:
            continue
        residuals.append(
            {
                "candidate_count": len(variants),
                "candidates": [
                    {
                        "canonical_section_key": str(
                            (row.structured_data or {}).get("canonical_section_key")
                            or ""
                        ),
                        "content_item_id": str(
                            (row.structured_data or {}).get("content_item_id") or ""
                        ),
                        "source_order": int(
                            (row.structured_data or {}).get("source_order") or 0
                        ),
                        "source_temporal_markers": list(
                            (row.structured_data or {}).get(
                                "source_temporal_markers"
                            )
                            or []
                        ),
                        "source_url": row.source_url,
                    }
                    for row in variants
                ],
                "reason": "repeated_citation_requires_source_bound_temporal_reconciliation",
                "section_number": citation,
            }
        )
    return residuals


def grouped_get_acquisition_contract(urls: Sequence[str]) -> dict[str, Any]:
    """Describe one ordered same-domain GET wave using the shared batch path."""

    requested = list(urls)
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("Tennessee GET wave must contain unique source URLs")
    domains = {(urlparse(url).hostname or "").lower() for url in requested}
    if "" in domains or len(domains) != 1:
        raise ValueError("Tennessee GET wave must contain exactly one source domain")
    return {
        "schema_version": "tennessee-lexis-grouped-get-contract-v1",
        "coalesce_compatible_warc_ranges": True,
        "common_crawl_inventory_query_upper_bound": 1,
        "group_warc_ranges_by_warc_filename": True,
        "per_page_archive_inventory_loop": False,
        "request_url_count": len(requested),
        "request_urls": requested,
        "retry_residual_urls_only": True,
        "source_domain": next(iter(domains)),
        "source_order_preserved": True,
        "wayback_prefix_inventory": True,
    }


__all__ = [
    "ADVANCE_ORIGIN",
    "GENERAL_ASSEMBLY_PUBLICATIONS_URL",
    "NONSTATUTORY_ROOT_LABEL",
    "OBSERVED_ALL_NODE_MEMBERSHIP_SHA256",
    "OBSERVED_ALL_STATUTORY_NODE_COUNT",
    "OBSERVED_AUTHORITY_CATALOG_RESIDUAL_COUNT",
    "OBSERVED_BODY_RESIDUAL_COUNT",
    "OBSERVED_DOCUMENT_COUNT",
    "OBSERVED_DOCUMENT_MEMBERSHIP_SHA256",
    "OBSERVED_ORDERED_CONTENT_PATH_SHA256",
    "OBSERVED_ROOT_MEMBERSHIP_SHA256",
    "OBSERVED_STRICT_REUSABLE_INPUT_COUNT",
    "OBSERVED_SUBTREE_MANIFEST_SHA256",
    "OBSERVED_TOTAL_RESIDUAL_COUNT",
    "PUBLIC_CONTAINER_CONFIG",
    "PUBLIC_CONTAINER_URL",
    "PUBLIC_ENTRY_URL",
    "TOC_ENDPOINT_PATH",
    "TOC_ENDPOINT_URL",
    "TOC_ROOT_ID",
    "TennesseeLexisNode",
    "canonical_digest",
    "canonical_toc_patch_request",
    "catalog_terminal_disposition",
    "container_url_matches",
    "content_item_id",
    "derive_exact_metadata_frontier",
    "document_url",
    "general_assembly_delegation_present",
    "grouped_get_acquisition_contract",
    "is_document_path",
    "observed_metadata_drift",
    "parse_root_dom_rows",
    "parse_root_html",
    "parse_tennessee_lexis_document_html",
    "parse_title_subtree_payload",
    "publisher_container_delegation_present",
    "toc_open_to_request",
    "unresolved_temporal_variant_groups",
    "valid_document_payload",
]
