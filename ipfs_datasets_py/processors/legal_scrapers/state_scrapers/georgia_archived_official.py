"""Fail-closed acquisition of hash-bound archived official Georgia statutes.

The Georgia General Assembly delegates its public OCGA table of contents to
Lexis.  That table of contents is useful as inventory authority, but its
document routes are access-gated in automated sessions.  This module joins a
*closed, byte-receip-bound* delegated TOC inventory to bodies recovered from
the corresponding historical ``legis.ga.gov`` section locators.

It deliberately does not fetch Lexis document bodies, accept terms, solve a
CAPTCHA, or use a secondary publisher.  Network acquisition is delegated to
the existing :mod:`state_archival_fetch` client (direct, Common Crawl,
Wayback, and archive.is).  A manifest is admissible only when every inventory
section is reconciled, every body byte string matches its SHA-256 receipt, and
the complete Title 1-53 locator frontier is closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
    ARCHIVE_TRANSPORT_KINDS,
    CACHE_TRANSPORT_KINDS,
    StateLawTransportReceiptError,
    canonicalize_state_law_transport_receipt,
)

from .base_scraper import (
    NormalizedStatute,
    current_state_law_run_environment_value,
)
from .georgia_archive import (
    NAV_MARKERS,
    TITLE_NUMBERS,
    official_section_url,
    parse_georgia_archive_html,
    strip_georgia_chrome,
)
from .georgia_lexis import (
    ADVANCE_ORIGIN,
    EXPECTED_TITLE_NUMBERS,
    PUBLIC_CONTAINER_URL,
    PUBLIC_ENTRY_URL,
    GeorgiaLexisDiscoveryResult,
    _dedupe_nodes,
    bootstrap_container_url_matches,
    is_lexis_document_url,
    normalize_section_number,
)

MANIFEST_ENV = "GEORGIA_ARCHIVED_OFFICIAL_MANIFEST"
MANIFEST_SCHEMA = "georgia-archived-official-corpus/v1"
INVENTORY_SCHEMA = "georgia-delegated-toc-section-frontier/v1"
SOURCE_KIND = "hash_bound_archived_official_georgia_code"
INVENTORY_SOURCE_KIND = "official_delegated_georgia_lexis_toc"

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_NODE_ID_RE = re.compile(r"^[A-Z0-9]{2,64}$")
_ARCHIVE_TIMESTAMP_RE = re.compile(r"^\d{14}$")
_NONOPERATIVE_RE = re.compile(
    r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE
)
_SECTION_HEADING_RE = re.compile(
    r"(?m)^(?:(?:O\.C\.G\.A\.|OCGA)\s+)?"
    r"(?:§|&sect;|&#167;)?\s*"
    r"(?P<num>\d{1,2}[A-Za-z]?-\d+[A-Za-z0-9.-]*)\.\s+"
    r"(?P<head>[^\n]+)"
)

_ARCHIVE_TRANSPORTS = ARCHIVE_TRANSPORT_KINDS
_CACHE_TRANSPORTS = CACHE_TRANSPORT_KINDS
_MUTABLE_EDITION_IDENTIFIERS = frozenset({"current", "head", "latest", "main", "master"})
_HEADING_DATE_TOKEN = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4}"
)
_EFFECTIVE_UNTIL_RE = re.compile(
    rf"\bEffective\s+until\s+(?P<date>{_HEADING_DATE_TOKEN})",
    re.IGNORECASE,
)
_EFFECTIVE_FROM_RE = re.compile(
    rf"\[\s*Effective\s+(?!until\b)(?P<date>{_HEADING_DATE_TOKEN})",
    re.IGNORECASE,
)
_LATER_UNTIL_RE = re.compile(
    rf"[,;]?\s+until\s+(?P<date>{_HEADING_DATE_TOKEN})",
    re.IGNORECASE,
)
_REPEALED_EFFECTIVE_RE = re.compile(
    rf"\bRepealed\s+effective\s+(?P<date>{_HEADING_DATE_TOKEN})",
    re.IGNORECASE,
)
_RESERVED_EFFECTIVE_RE = re.compile(
    rf"\[\s*Reserved\s+effective\s+(?P<date>{_HEADING_DATE_TOKEN})",
    re.IGNORECASE,
)


class GeorgiaArchivedOfficialCorpusError(RuntimeError):
    """A purported archived-official corpus cannot prove exact coverage."""

    def __init__(self, reason: str, *, evidence: Mapping[str, Any] | None = None) -> None:
        self.reason = str(reason)
        self.evidence = dict(evidence or {})
        super().__init__(f"Georgia archived-official corpus is invalid: {self.reason}")


@dataclass(frozen=True)
class GeorgiaArchivedOfficialCorpus:
    """Verified statute rows plus their immutable acquisition receipt."""

    statutes: tuple[NormalizedStatute, ...]
    receipt: Mapping[str, Any]
    manifest_path: Path
    manifest_sha256: str


@dataclass(frozen=True)
class _AlignedBodyResult:
    """One parser input returned by the shared state-law page batch seam."""

    url: str
    content: bytes
    fetched_at: str
    transport_receipt: Mapping[str, Any]


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _frontier_sha256(frontier: Mapping[str, Any]) -> str:
    material = {key: value for key, value in frontier.items() if key != "frontier_digest_sha256"}
    return _canonical_sha256(material)


def _is_sha256(value: object) -> bool:
    return bool(_SHA256_RE.fullmatch(str(value or "").strip().lower()))


def _is_aware_timestamp(value: object) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None


def _sequence(value: object, *, field: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise GeorgiaArchivedOfficialCorpusError(f"{field} must be a sequence")
    return list(value)


def _exact_official_section_url(value: object, section_number: str) -> bool:
    candidate = str(value or "").strip()
    parsed = urlparse(candidate)
    try:
        port = parsed.port
    except ValueError:
        return False
    expected = urlparse(official_section_url(section_number))
    return bool(
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").lower() in {"www.legis.ga.gov", "legis.ga.gov"}
        and parsed.username is None
        and parsed.password is None
        and port is None
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        and parsed.path.rstrip("/") == expected.path.rstrip("/")
    )


def _exact_lexis_document_url(value: object) -> bool:
    candidate = str(value or "").strip()
    return bool(
        candidate.startswith(f"{ADVANCE_ORIGIN}/")
        and urljoin(ADVANCE_ORIGIN, candidate) == candidate
        and is_lexis_document_url(candidate)
    )


def _heading_date(match: re.Match[str] | None) -> date | None:
    if match is None:
        return None
    try:
        return datetime.strptime(match.group("date"), "%B %d, %Y").date()
    except (TypeError, ValueError):
        return None


def _heading_temporal_interval(heading: str) -> tuple[date | None, date | None]:
    """Return the source-stated half-open effective interval, when present."""

    text = str(heading or "")
    start = _heading_date(_EFFECTIVE_FROM_RE.search(text))
    end = _heading_date(_EFFECTIVE_UNTIL_RE.search(text))
    if start is not None and end is None:
        end = _heading_date(_LATER_UNTIL_RE.search(text))
    repeal_date = _heading_date(_REPEALED_EFFECTIVE_RE.search(text))
    if repeal_date is not None:
        end = repeal_date
    reserved_date = _heading_date(_RESERVED_EFFECTIVE_RE.search(text))
    if reserved_date is not None:
        start = reserved_date
    return start, end


def _heading_active_on(heading: str, *, as_of: date) -> bool:
    start, end = _heading_temporal_interval(heading)
    return (start is None or start <= as_of) and (end is None or as_of < end)


def _heading_expected_disposition(heading: str, *, as_of: date) -> str:
    text = str(heading or "")
    _start, end = _heading_temporal_interval(text)
    if end is not None and as_of < end and _REPEALED_EFFECTIVE_RE.search(text):
        return "admit"
    return "exclude_nonoperative" if _NONOPERATIVE_RE.search(text) else "admit"


def build_georgia_delegated_inventory(
    discovery: GeorgiaLexisDiscoveryResult,
    *,
    edition_as_of: str,
    edition_identifier: str,
) -> dict[str, Any]:
    """Seal an exhaustive live delegated TOC observation as locator evidence.

    This receipt proves section identities and zero-price document locators;
    it never treats TOC labels or excerpts as statutory bodies.  The separate
    archived-official acquisition below must still reconcile every locator to
    exact official body bytes.
    """

    if not isinstance(discovery, GeorgiaLexisDiscoveryResult):
        raise GeorgiaArchivedOfficialCorpusError(
            "delegated inventory input is not a live discovery result"
        )
    if (
        discovery.status != "official_toc"
        or discovery.delegation_verified is not True
        or not bootstrap_container_url_matches(discovery.final_url)
        or not _is_aware_timestamp(discovery.observed_at)
        or not _is_sha256(discovery.root_rendered_sha256)
    ):
        raise GeorgiaArchivedOfficialCorpusError(
            "delegated TOC root lacks exact live authority evidence"
        )

    nodes = _dedupe_nodes(discovery.nodes)
    if not nodes or any(not node.evidence_verified for node in nodes):
        raise GeorgiaArchivedOfficialCorpusError(
            "delegated TOC contains unverified nodes"
        )
    title_nodes = sorted(
        (
            node
            for node in nodes
            if node.title_number is not None
            and node.level == 1
            and node.node_path == f"/ROOT/{node.node_id}"
        ),
        key=lambda node: int(node.title_number or 0),
    )
    title_numbers = [str(node.title_number) for node in title_nodes]
    if title_numbers != list(EXPECTED_TITLE_NUMBERS):
        raise GeorgiaArchivedOfficialCorpusError(
            "delegated TOC does not contain the exact ordered Title 1-53 frontier"
        )

    expanded = {str(value) for value in discovery.expanded_node_ids}
    required_expansions = {
        node.node_id for node in nodes if node.can_expand or node.has_children
    }
    if (
        not required_expansions
        or expanded != required_expansions
        or any(
            not node.expansion_closed
            for node in nodes
            if node.node_id in required_expansions
        )
    ):
        raise GeorgiaArchivedOfficialCorpusError(
            "delegated TOC expandable-node frontier is not closed"
        )
    node_paths = {node.node_path for node in nodes}
    unresolved = sorted(
        node.node_id
        for node in nodes
        if node.node_id in required_expansions
        and not any(
            candidate.startswith(f"{node.node_path}/")
            and candidate.count("/") == node.node_path.count("/") + 1
            for candidate in node_paths
        )
    )
    if unresolved:
        raise GeorgiaArchivedOfficialCorpusError(
            "delegated TOC has expandable nodes without retained children",
            evidence={"unresolved_expandable_node_ids": unresolved},
        )

    patch_hashes = dict(discovery.patch_response_sha256)
    if set(patch_hashes) != required_expansions or any(
        not _is_sha256(value) for value in patch_hashes.values()
    ):
        raise GeorgiaArchivedOfficialCorpusError(
            "delegated TOC response hashes do not cover every expansion"
        )
    patch_paths = dict(discovery.patch_response_paths)
    if patch_paths and set(patch_paths) != required_expansions:
        raise GeorgiaArchivedOfficialCorpusError(
            "retained TOC response paths do not cover every expansion"
        )

    raw_section_nodes = [node for node in nodes if node.section_number is not None]
    if not raw_section_nodes or any(
        not node.public_document_available for node in raw_section_nodes
    ):
        raise GeorgiaArchivedOfficialCorpusError(
            "delegated TOC section frontier contains a missing or gated locator"
        )
    observed_date = datetime.fromisoformat(discovery.observed_at).date()
    grouped_sections: dict[str, list[Any]] = {}
    for node in raw_section_nodes:
        section = normalize_section_number(node.section_number)
        grouped_sections.setdefault(section, []).append(node)

    by_section: dict[str, Any] = {}
    temporal_exclusions: list[dict[str, Any]] = []
    for section, candidates in grouped_sections.items():
        active = [
            node
            for node in candidates
            if _heading_active_on(node.title, as_of=observed_date)
        ]
        if len(active) > 1:
            raise GeorgiaArchivedOfficialCorpusError(
                f"temporally ambiguous delegated TOC section: {section}",
                evidence={"headings": [node.title for node in active]},
            )
        for node in candidates:
            if node in active:
                continue
            start, end = _heading_temporal_interval(node.title)
            temporal_exclusions.append(
                {
                    "document_url": urljoin(ADVANCE_ORIGIN, node.link_href),
                    "effective_end_exclusive": end.isoformat() if end else None,
                    "effective_start": start.isoformat() if start else None,
                    "evidence_sha256": node.evidence_sha256,
                    "heading": node.title,
                    "node_id": node.node_id,
                    "node_path": node.node_path,
                    "reason": (
                        "not_yet_effective"
                        if start is not None and observed_date < start
                        else "no_longer_effective"
                        if end is not None and observed_date >= end
                        else "alternate_temporal_version"
                    ),
                    "section_number": section,
                }
            )
        if not active:
            continue
        node = active[0]
        parent_id = node.node_path.rstrip("/").split("/")[-2]
        if parent_id not in required_expansions:
            raise GeorgiaArchivedOfficialCorpusError(
                f"section {section} parent was not expansion-verified"
            )
        document_url = urljoin(ADVANCE_ORIGIN, node.link_href)
        if not _exact_lexis_document_url(document_url):
            raise GeorgiaArchivedOfficialCorpusError(
                f"section {section} has an invalid delegated locator"
            )
        by_section[section] = {
            "document_url": document_url,
            "evidence_sha256": node.evidence_sha256,
            "evidence_verified": True,
            "expected_disposition": _heading_expected_disposition(
                node.title,
                as_of=observed_date,
            ),
            "heading": node.title,
            "node_id": node.node_id,
            "node_path": node.node_path,
            "section_number": section,
            "source_authority_class": "official",
        }
    represented_titles = {section.split("-", 1)[0] for section in by_section}
    if represented_titles != set(TITLE_NUMBERS):
        raise GeorgiaArchivedOfficialCorpusError(
            "delegated section locator frontier does not represent every title",
            evidence={
                "represented_titles": sorted(represented_titles, key=int),
            },
        )

    def _section_key(value: str) -> tuple[Any, ...]:
        return tuple(
            int(part) if part.isdigit() else part.lower()
            for part in re.split(r"([0-9]+)", value)
            if part
        )

    sections = [by_section[key] for key in sorted(by_section, key=_section_key)]
    locator_rows = [
        {
            "section_number": row["section_number"],
            "document_url": row["document_url"],
        }
        for row in sections
    ]
    frontier: dict[str, Any] = {
        "closed": True,
        "discovered_section_count": len(sections),
        "discovered_temporal_locator_count": len(raw_section_nodes),
        "expanded_node_ids": sorted(expanded),
        "expected_title_count": len(TITLE_NUMBERS),
        "failed_final": 0,
        "frontier_closed": True,
        "required_expandable_node_ids": sorted(required_expansions),
        "section_locator_digest_sha256": _canonical_sha256(locator_rows),
        "section_locator_frontier_closed": True,
        "sections": sections,
        "structural_document_count": sum(
            bool(node.link_href) and node.section_number is None for node in nodes
        ),
        "title_inventory_closed": True,
        "title_numbers": list(TITLE_NUMBERS),
        "temporal_exclusion_count": len(temporal_exclusions),
        "temporal_exclusions": temporal_exclusions,
        "toc_exhausted": True,
        "unresolved_expandable_node_ids": [],
        "unvisited_continuation_links": [],
    }
    frontier["frontier_digest_sha256"] = _frontier_sha256(frontier)
    inventory: dict[str, Any] = {
        "container_url": discovery.final_url,
        "delegation_verified": True,
        "edition_as_of": str(edition_as_of),
        "edition_identifier": str(edition_identifier),
        "entry_url": PUBLIC_ENTRY_URL,
        "frontier": frontier,
        "jurisdiction": "GA",
        "observed_at": discovery.observed_at,
        "official_source": True,
        "patch_response_sha256": {
            key: patch_hashes[key] for key in sorted(patch_hashes)
        },
        "root_rendered_sha256": discovery.root_rendered_sha256,
        "schema": INVENTORY_SCHEMA,
        "source_authority_class": "official",
        "source_kind": INVENTORY_SOURCE_KIND,
        "verification_result": "verified",
    }
    if discovery.root_rendered_path:
        inventory["root_rendered_path"] = discovery.root_rendered_path
    if patch_paths:
        inventory["patch_response_paths"] = {
            key: patch_paths[key] for key in sorted(patch_paths)
        }
    _validate_inventory(inventory)
    return inventory


def _validate_inventory(inventory: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    if str(inventory.get("schema") or "") != INVENTORY_SCHEMA:
        raise GeorgiaArchivedOfficialCorpusError("inventory schema is missing or unsupported")
    if str(inventory.get("jurisdiction") or "").upper() != "GA":
        raise GeorgiaArchivedOfficialCorpusError("inventory jurisdiction must be GA")
    if inventory.get("official_source") is not True:
        raise GeorgiaArchivedOfficialCorpusError("inventory must explicitly identify an official source")
    if str(inventory.get("source_authority_class") or "").lower() != "official":
        raise GeorgiaArchivedOfficialCorpusError("inventory authority must be official")
    if str(inventory.get("source_kind") or "") != INVENTORY_SOURCE_KIND:
        raise GeorgiaArchivedOfficialCorpusError("inventory is not the delegated Georgia TOC")
    if str(inventory.get("entry_url") or "") != PUBLIC_ENTRY_URL:
        raise GeorgiaArchivedOfficialCorpusError("inventory entry URL is outside the delegated source")
    if not bootstrap_container_url_matches(inventory.get("container_url")):
        raise GeorgiaArchivedOfficialCorpusError("inventory container URL is not exactly scoped")
    if inventory.get("delegation_verified") is not True:
        raise GeorgiaArchivedOfficialCorpusError("inventory delegation is not verified")
    if str(inventory.get("verification_result") or "").lower() != "verified":
        raise GeorgiaArchivedOfficialCorpusError("inventory verification_result must be verified")
    if not _is_aware_timestamp(inventory.get("observed_at")):
        raise GeorgiaArchivedOfficialCorpusError("inventory observed_at must include a timezone")
    edition_as_of = str(inventory.get("edition_as_of") or "").strip()
    try:
        edition_date = date.fromisoformat(edition_as_of)
    except ValueError as exc:
        raise GeorgiaArchivedOfficialCorpusError(
            "inventory edition_as_of must be an exact ISO date"
        ) from exc
    edition_identifier = str(inventory.get("edition_identifier") or "").strip()
    if (
        not edition_identifier
        or edition_identifier.lower() in _MUTABLE_EDITION_IDENTIFIERS
        or edition_identifier.lower().endswith(("/latest", "/current"))
    ):
        raise GeorgiaArchivedOfficialCorpusError("inventory edition identifier must be immutable")
    observed_date = datetime.fromisoformat(str(inventory["observed_at"])).date()
    if edition_date > observed_date:
        raise GeorgiaArchivedOfficialCorpusError("inventory edition is later than its observation")
    if not _is_sha256(inventory.get("root_rendered_sha256")):
        raise GeorgiaArchivedOfficialCorpusError("inventory lacks a root response SHA-256")

    patch_hashes = inventory.get("patch_response_sha256")
    if not isinstance(patch_hashes, Mapping) or not patch_hashes:
        raise GeorgiaArchivedOfficialCorpusError("inventory lacks TOC expansion response hashes")
    if any(not _is_sha256(value) for value in patch_hashes.values()):
        raise GeorgiaArchivedOfficialCorpusError("inventory has an invalid expansion response hash")

    frontier = inventory.get("frontier")
    if not isinstance(frontier, Mapping):
        raise GeorgiaArchivedOfficialCorpusError("inventory frontier is missing")
    required_true = (
        "closed",
        "frontier_closed",
        "section_locator_frontier_closed",
        "title_inventory_closed",
        "toc_exhausted",
    )
    if any(frontier.get(field) is not True for field in required_true):
        raise GeorgiaArchivedOfficialCorpusError("delegated section-locator frontier is not closed")
    if list(frontier.get("unvisited_continuation_links") or []) != []:
        raise GeorgiaArchivedOfficialCorpusError("inventory has unvisited continuation links")
    if list(frontier.get("unresolved_expandable_node_ids") or []) != []:
        raise GeorgiaArchivedOfficialCorpusError("inventory has unresolved expandable nodes")
    if int(frontier.get("failed_final") or 0) != 0:
        raise GeorgiaArchivedOfficialCorpusError("inventory has final failures")
    if str(frontier.get("frontier_digest_sha256") or "").lower() != _frontier_sha256(frontier):
        raise GeorgiaArchivedOfficialCorpusError("inventory frontier digest does not match")

    title_numbers = [str(value) for value in _sequence(frontier.get("title_numbers"), field="title_numbers")]
    if title_numbers != list(TITLE_NUMBERS):
        raise GeorgiaArchivedOfficialCorpusError(
            "inventory must contain the ordered, exact Title 1-53 frontier",
            evidence={"title_numbers": title_numbers},
        )
    if int(frontier.get("expected_title_count") or 0) != len(TITLE_NUMBERS):
        raise GeorgiaArchivedOfficialCorpusError("inventory expected_title_count is not 53")

    required_expansions = {
        str(value) for value in _sequence(
            frontier.get("required_expandable_node_ids"),
            field="required_expandable_node_ids",
        )
    }
    expanded = {
        str(value) for value in _sequence(
            frontier.get("expanded_node_ids"), field="expanded_node_ids"
        )
    }
    if not required_expansions or expanded != required_expansions:
        raise GeorgiaArchivedOfficialCorpusError("TOC expansion frontier is not exactly reconciled")
    if {str(key) for key in patch_hashes} != expanded:
        raise GeorgiaArchivedOfficialCorpusError("TOC response hashes do not cover every expansion")

    raw_sections = _sequence(frontier.get("sections"), field="sections")
    if not raw_sections:
        raise GeorgiaArchivedOfficialCorpusError("inventory section frontier is empty")
    if int(frontier.get("discovered_section_count") or 0) != len(raw_sections):
        raise GeorgiaArchivedOfficialCorpusError("inventory section count does not reconcile")

    response_hashes = {
        str(inventory.get("root_rendered_sha256") or "").lower(),
        *(str(value).lower() for value in patch_hashes.values()),
    }
    sections: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    seen_nodes: set[str] = set()
    represented_titles: set[str] = set()
    for position, raw in enumerate(raw_sections):
        if not isinstance(raw, Mapping):
            raise GeorgiaArchivedOfficialCorpusError(f"sections[{position}] is not an object")
        try:
            section = normalize_section_number(raw.get("section_number"))
        except ValueError as exc:
            raise GeorgiaArchivedOfficialCorpusError(
                f"sections[{position}] has an invalid section number"
            ) from exc
        if section in seen_sections:
            raise GeorgiaArchivedOfficialCorpusError(f"duplicate inventory section: {section}")
        seen_sections.add(section)
        represented_titles.add(section.split("-", 1)[0])

        node_id = str(raw.get("node_id") or "").strip()
        node_path = str(raw.get("node_path") or "").strip()
        if (
            not _NODE_ID_RE.fullmatch(node_id)
            or not node_path.endswith(f"/{node_id}")
            or len(node_path.rstrip("/").split("/")) < 3
            or node_path.rstrip("/").split("/")[-2] not in expanded
        ):
            raise GeorgiaArchivedOfficialCorpusError(f"section {section} has invalid TOC identity")
        if node_id in seen_nodes:
            raise GeorgiaArchivedOfficialCorpusError(f"duplicate inventory node: {node_id}")
        seen_nodes.add(node_id)
        if not _exact_lexis_document_url(raw.get("document_url")):
            raise GeorgiaArchivedOfficialCorpusError(
                f"section {section} locator is not an exact delegated Lexis document URL"
            )
        evidence_sha256 = str(raw.get("evidence_sha256") or "").lower()
        if (
            raw.get("evidence_verified") is not True
            or not _is_sha256(evidence_sha256)
            or evidence_sha256 not in response_hashes
        ):
            raise GeorgiaArchivedOfficialCorpusError(f"section {section} lacks byte evidence")
        if str(raw.get("source_authority_class") or "").lower() != "official":
            raise GeorgiaArchivedOfficialCorpusError(f"section {section} is not official inventory")

        expected_disposition = str(raw.get("expected_disposition") or "admit").strip().lower()
        if expected_disposition not in {"admit", "exclude_nonoperative"}:
            raise GeorgiaArchivedOfficialCorpusError(
                f"section {section} has an unsupported expected disposition"
            )
        heading = str(raw.get("heading") or "").strip()
        if expected_disposition == "exclude_nonoperative" and not _NONOPERATIVE_RE.search(heading):
            raise GeorgiaArchivedOfficialCorpusError(
                f"section {section} nonoperative exclusion is not supported by its TOC heading"
            )
        sections.append(
            {
                **dict(raw),
                "section_number": section,
                "expected_disposition": expected_disposition,
            }
        )

    if represented_titles != set(TITLE_NUMBERS):
        raise GeorgiaArchivedOfficialCorpusError(
            "section locators do not represent every Georgia title",
            evidence={"represented_titles": sorted(represented_titles, key=int)},
        )
    expected_digest = _canonical_sha256(
        [{"section_number": row["section_number"], "document_url": row["document_url"]} for row in sections]
    )
    if str(frontier.get("section_locator_digest_sha256") or "").lower() != expected_digest:
        raise GeorgiaArchivedOfficialCorpusError("section locator frontier digest does not match")
    return tuple(sections)


def _validate_transport_receipt(
    artifact: Mapping[str, Any],
    *,
    official_url: str,
    digest: str,
) -> dict[str, Any]:
    """Return the shared verifier's replayable receipt or fail closed."""

    try:
        return canonicalize_state_law_transport_receipt(
            artifact,
            official_url=official_url,
            content_sha256=digest,
        )
    except StateLawTransportReceiptError as exc:
        detail = exc.detail
        if exc.code == "missing_origin_transport_receipt":
            detail = "durable-cache artifact lacks its original transport receipt"
        raise GeorgiaArchivedOfficialCorpusError(detail) from exc


def _validate_artifact_time(
    artifact: Mapping[str, Any],
    *,
    edition_as_of: str,
    inventory_observed_at: str,
) -> None:
    fetched_at = str(artifact.get("fetched_at") or "").strip()
    if not _is_aware_timestamp(fetched_at):
        raise GeorgiaArchivedOfficialCorpusError("body lacks an acquisition timestamp")
    transport = str(artifact.get("source_transport") or "").strip().lower()
    if transport in _CACHE_TRANSPORTS:
        origin = artifact.get("origin_transport_receipt")
        if not isinstance(origin, Mapping):
            raise GeorgiaArchivedOfficialCorpusError(
                "durable-cache artifact lacks its original transport receipt"
            )
        _validate_artifact_time(
            origin,
            edition_as_of=edition_as_of,
            inventory_observed_at=inventory_observed_at,
        )
        return
    if transport in _ARCHIVE_TRANSPORTS:
        stamp = str(artifact.get("archive_timestamp") or "")
        if not _ARCHIVE_TIMESTAMP_RE.fullmatch(stamp):
            raise GeorgiaArchivedOfficialCorpusError("archive timestamp is not exact")
        try:
            body_date = date.fromisoformat(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}")
        except ValueError as exc:
            raise GeorgiaArchivedOfficialCorpusError("archive timestamp is not a real date") from exc
    else:
        body_date = datetime.fromisoformat(fetched_at).date()
    edition_date = date.fromisoformat(edition_as_of)
    observation_date = datetime.fromisoformat(inventory_observed_at).date()
    if body_date < edition_date or body_date > observation_date:
        raise GeorgiaArchivedOfficialCorpusError(
            "body acquisition time falls outside the sealed edition interval"
        )


def _nonoperative_heading(html: str, section_number: str) -> str:
    text = strip_georgia_chrome(html)
    for match in _SECTION_HEADING_RE.finditer(text):
        if str(match.group("num") or "").strip() == section_number:
            heading = str(match.group("head") or "").strip()
            return heading if _NONOPERATIVE_RE.search(heading) else ""
    return ""


def _looks_like_georgia_statute_payload(payload: bytes) -> bool:
    """Reject the live Angular shell while admitting statutes or tombstones."""

    if not payload:
        return False
    html = payload.decode("utf-8", errors="replace")
    if parse_georgia_archive_html(html, max_statutes=1):
        return True
    text = strip_georgia_chrome(html)
    return any(
        _NONOPERATIVE_RE.search(str(match.group("head") or ""))
        for match in _SECTION_HEADING_RE.finditer(text)
    )


def _safe_artifact_path(manifest_path: Path, relative: object) -> Path:
    token = str(relative or "").strip()
    candidate = Path(token)
    if not token or candidate.is_absolute() or ".." in candidate.parts:
        raise GeorgiaArchivedOfficialCorpusError("artifact path is not a safe relative path")
    root = manifest_path.parent.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise GeorgiaArchivedOfficialCorpusError("artifact path escapes the manifest directory") from exc
    return resolved


def configured_georgia_archived_official_manifest_path() -> Path | None:
    raw = current_state_law_run_environment_value(MANIFEST_ENV).strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def load_georgia_archived_official_corpus(
    manifest_path: str | Path,
    *,
    code_name: str = "Official Code of Georgia Annotated",
) -> GeorgiaArchivedOfficialCorpus:
    """Verify and parse one complete archived-official Georgia corpus manifest."""

    path = Path(manifest_path).expanduser().resolve()
    try:
        manifest_bytes = path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GeorgiaArchivedOfficialCorpusError("manifest is unreadable") from exc
    if not isinstance(manifest, Mapping):
        raise GeorgiaArchivedOfficialCorpusError("manifest root must be an object")
    if str(manifest.get("schema") or "") != MANIFEST_SCHEMA:
        raise GeorgiaArchivedOfficialCorpusError("manifest schema is missing or unsupported")
    if str(manifest.get("jurisdiction") or "").upper() != "GA":
        raise GeorgiaArchivedOfficialCorpusError("manifest jurisdiction must be GA")
    if manifest.get("official_source") is not True:
        raise GeorgiaArchivedOfficialCorpusError("manifest must explicitly bind an official source")
    if str(manifest.get("source_authority_class") or "").lower() != "official":
        raise GeorgiaArchivedOfficialCorpusError("manifest authority must be official")
    if str(manifest.get("source_kind") or "") != SOURCE_KIND:
        raise GeorgiaArchivedOfficialCorpusError("manifest source kind is unsupported")

    inventory = manifest.get("inventory")
    if not isinstance(inventory, Mapping):
        raise GeorgiaArchivedOfficialCorpusError("manifest inventory receipt is missing")
    sections = _validate_inventory(inventory)
    inventory_sha256 = _canonical_sha256(inventory)
    if str(manifest.get("inventory_sha256") or "").lower() != inventory_sha256:
        raise GeorgiaArchivedOfficialCorpusError("manifest inventory SHA-256 does not match")

    frontier = manifest.get("frontier")
    artifacts_raw = _sequence(manifest.get("artifacts"), field="artifacts")
    if not isinstance(frontier, Mapping):
        raise GeorgiaArchivedOfficialCorpusError("manifest frontier receipt is missing")
    if frontier.get("closed") is not True or frontier.get("frontier_closed") is not True:
        raise GeorgiaArchivedOfficialCorpusError("body frontier is not closed")
    if str(manifest.get("verification_result") or "").lower() != "verified":
        raise GeorgiaArchivedOfficialCorpusError("manifest verification_result must be verified")
    if int(frontier.get("failed_final") or 0) != 0 or int(frontier.get("quarantined") or 0) != 0:
        raise GeorgiaArchivedOfficialCorpusError("closed body frontier contains failures")
    if str(frontier.get("frontier_digest_sha256") or "").lower() != _frontier_sha256(frontier):
        raise GeorgiaArchivedOfficialCorpusError("body frontier digest does not match")

    expected_by_section = {row["section_number"]: row for row in sections}
    artifacts_by_section: dict[str, Mapping[str, Any]] = {}
    for position, artifact in enumerate(artifacts_raw):
        if not isinstance(artifact, Mapping):
            raise GeorgiaArchivedOfficialCorpusError(f"artifacts[{position}] is not an object")
        section = str(artifact.get("section_number") or "").strip()
        if section not in expected_by_section:
            raise GeorgiaArchivedOfficialCorpusError(f"unexpected body artifact: {section!r}")
        if section in artifacts_by_section:
            raise GeorgiaArchivedOfficialCorpusError(f"duplicate body artifact: {section}")
        artifacts_by_section[section] = artifact
    if set(artifacts_by_section) != set(expected_by_section):
        raise GeorgiaArchivedOfficialCorpusError(
            "body artifacts do not exactly match the locator frontier",
            evidence={
                "missing": sorted(set(expected_by_section) - set(artifacts_by_section)),
                "extra": sorted(set(artifacts_by_section) - set(expected_by_section)),
            },
        )

    admitted = sum(
        str(row.get("status") or "") == "admitted" for row in artifacts_by_section.values()
    )
    excluded = sum(
        str(row.get("status") or "") == "excluded_nonoperative"
        for row in artifacts_by_section.values()
    )
    discovered = len(sections)
    receipt_counts = {
        "discovered": discovered,
        "fetched": admitted,
        "excluded": excluded,
        "quarantined": 0,
        "failed_final": 0,
        "duplicates": 0,
    }
    if any(int(frontier.get(key) or 0) != value for key, value in receipt_counts.items()):
        raise GeorgiaArchivedOfficialCorpusError("body frontier counts do not reconcile")
    if admitted + excluded != discovered:
        raise GeorgiaArchivedOfficialCorpusError("body frontier dispositions do not reconcile")
    locator_digest = _canonical_sha256(sorted(expected_by_section))
    if str(frontier.get("section_numbers_sha256") or "").lower() != locator_digest:
        raise GeorgiaArchivedOfficialCorpusError("body section frontier digest does not match")

    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    statutes: list[NormalizedStatute] = []
    content_hashes: list[str] = []
    for section, expected in expected_by_section.items():
        artifact = artifacts_by_section[section]
        official_url = str(artifact.get("official_url") or "").strip()
        if not _exact_official_section_url(official_url, section):
            raise GeorgiaArchivedOfficialCorpusError(
                f"section {section} body URL is not an exact official locator"
            )
        artifact_path = _safe_artifact_path(path, artifact.get("path"))
        try:
            content = artifact_path.read_bytes()
        except OSError as exc:
            raise GeorgiaArchivedOfficialCorpusError(
                f"section {section} body artifact is unreadable"
            ) from exc
        digest = hashlib.sha256(content).hexdigest()
        if str(artifact.get("sha256") or "").lower() != digest:
            raise GeorgiaArchivedOfficialCorpusError(f"section {section} body SHA-256 mismatch")
        if int(artifact.get("size_bytes") or -1) != len(content):
            raise GeorgiaArchivedOfficialCorpusError(f"section {section} body size mismatch")
        try:
            _validate_artifact_time(
                artifact,
                edition_as_of=str(inventory["edition_as_of"]),
                inventory_observed_at=str(inventory["observed_at"]),
            )
        except GeorgiaArchivedOfficialCorpusError as exc:
            raise GeorgiaArchivedOfficialCorpusError(
                f"section {section} {exc.reason}"
            ) from exc
        transport_receipt = _validate_transport_receipt(
            artifact,
            official_url=official_url,
            digest=digest,
        )
        content_hashes.append(digest)

        html = content.decode("utf-8", errors="replace")
        status = str(artifact.get("status") or "").strip()
        expected_status = str(expected.get("expected_disposition") or "admit")
        if status == "excluded_nonoperative":
            if expected_status != "exclude_nonoperative" or not _nonoperative_heading(html, section):
                raise GeorgiaArchivedOfficialCorpusError(
                    f"section {section} exclusion is not supported by its archived body"
                )
            continue
        if status != "admitted" or expected_status != "admit":
            raise GeorgiaArchivedOfficialCorpusError(f"section {section} has an invalid disposition")
        parsed = parse_georgia_archive_html(
            html,
            source_url=official_url,
            code_name=code_name,
            max_statutes=None,
        )
        parsed_sections = {str(row.section_number or "") for row in parsed}
        if parsed_sections != {section} or len(parsed) != 1:
            raise GeorgiaArchivedOfficialCorpusError(
                f"section {section} body does not parse as exactly one matching statute",
                evidence={"parsed_sections": sorted(parsed_sections)},
            )
        row = parsed[0]
        lowered = str(row.full_text or "").lower()
        if not row.full_text or any(marker in lowered for marker in NAV_MARKERS):
            raise GeorgiaArchivedOfficialCorpusError(f"section {section} body is contaminated")
        structured = dict(row.structured_data or {})
        structured.update(
            {
                "archive_timestamp": artifact.get("archive_timestamp") or None,
                "archive_url": artifact.get("archive_url") or None,
                "archive_source_url": artifact.get("archive_url") or None,
                "body_sha256": digest,
                "fetch_transport": artifact.get("source_transport"),
                "frontier_closed": True,
                "full_corpus_admissible": True,
                "edition_as_of": inventory.get("edition_as_of"),
                "edition_identifier": inventory.get("edition_identifier"),
                "inventory_sha256": inventory_sha256,
                "inventory_source_url": PUBLIC_CONTAINER_URL,
                "live_official": str(artifact.get("source_transport")) == "direct",
                "manifest_sha256": manifest_sha256,
                "official_source": True,
                "publisher_editorial_excluded": True,
                "source_authority_class": "official",
                "source_kind": SOURCE_KIND,
                "statutory_text_only": True,
                "transport_receipt": transport_receipt,
            }
        )
        row.source_url = official_url
        row.structured_data = structured
        statutes.append(row)

    if sorted(str(row.section_number or "") for row in statutes) != sorted(
        section
        for section, row in expected_by_section.items()
        if row.get("expected_disposition") == "admit"
    ):
        raise GeorgiaArchivedOfficialCorpusError("parsed statute set does not close the body frontier")
    expected_content_hashes = sorted(content_hashes)
    if sorted(str(value) for value in manifest.get("content_hashes") or []) != expected_content_hashes:
        raise GeorgiaArchivedOfficialCorpusError("manifest content hash set does not reconcile")

    receipt = dict(manifest)
    receipt["manifest_sha256"] = manifest_sha256
    return GeorgiaArchivedOfficialCorpus(
        statutes=tuple(statutes),
        receipt=receipt,
        manifest_path=path,
        manifest_sha256=manifest_sha256,
    )


async def acquire_georgia_archived_official_corpus(
    inventory: Mapping[str, Any],
    output_dir: str | Path,
    *,
    fetch_client: Any | None = None,
    page_batch_fetcher: Any | None = None,
    common_crawl_records: Sequence[tuple[str, dict[str, Any]]] = (),
    common_crawl_record_loader: Any | None = None,
    common_crawl_engine: Any | None = None,
    max_concurrency: int = 8,
    prefer_direct: bool = False,
    require_batched_transport: bool = True,
) -> dict[str, Any]:
    """Acquire every official body locator and emit a hash-bound manifest.

    An incomplete run still emits an audit manifest, but its frontier remains
    open and :func:`load_georgia_archived_official_corpus` will reject it.
    """

    if page_batch_fetcher is not None and not callable(page_batch_fetcher):
        raise TypeError("page_batch_fetcher must be callable or None")
    if page_batch_fetcher is not None and fetch_client is not None:
        raise ValueError("page_batch_fetcher and fetch_client are mutually exclusive")
    if page_batch_fetcher is not None and (
        common_crawl_records
        or common_crawl_record_loader is not None
        or common_crawl_engine is not None
    ):
        raise ValueError(
            "page_batch_fetcher owns Common Crawl discovery and retrieval"
        )
    if common_crawl_record_loader is not None and not callable(
        common_crawl_record_loader
    ):
        raise TypeError("common_crawl_record_loader must be callable or None")
    if not isinstance(prefer_direct, bool):
        raise TypeError("prefer_direct must be a boolean")
    if not isinstance(require_batched_transport, bool):
        raise TypeError("require_batched_transport must be a boolean")

    sections = _validate_inventory(inventory)
    inventory_payload = dict(inventory)
    inventory_sha256 = _canonical_sha256(inventory_payload)
    if fetch_client is None and page_batch_fetcher is None:
        from .state_archival_fetch import ArchivalFetchClient

        fetch_client = ArchivalFetchClient(
            request_timeout_seconds=30,
            delay_seconds=0.0,
            content_validator=_looks_like_georgia_statute_payload,
        )

    root = Path(output_dir).expanduser().resolve()
    objects_dir = root / "objects"
    objects_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    official_urls = [official_section_url(row["section_number"]) for row in sections]
    batch_stats: dict[str, Any] = {}
    batch_errors: list[str | None] = [None] * len(sections)
    fetched_results: list[Any | None]
    batch_fetch = getattr(fetch_client, "fetch_many_with_fallback", None)
    if page_batch_fetcher is not None:
        batch = await page_batch_fetcher(
            official_urls,
            timeout_seconds=30,
            content_validator=_looks_like_georgia_statute_payload,
            media_type="text/html",
            max_concurrency=max_concurrency,
            prefer_direct=prefer_direct,
            common_crawl_domain_terms=("www.legis.ga.gov", "legis.ga.gov"),
            common_crawl_url_terms=("/legislation/georgia-code/",),
            common_crawl_mime_terms=("html",),
            wayback_prefix_inventory=True,
        )
        batch_urls = list(getattr(batch, "urls", []) or [])
        batch_payloads = list(getattr(batch, "payloads", []) or [])
        batch_errors = list(getattr(batch, "errors", []) or [])
        batch_receipts = list(getattr(batch, "transport_receipts", []) or [])
        batch_envelopes = list(getattr(batch, "parser_input_envelopes", []) or [])
        if any(
            len(values) != len(sections)
            for values in (
                batch_urls,
                batch_payloads,
                batch_errors,
                batch_receipts,
                batch_envelopes,
            )
        ):
            raise GeorgiaArchivedOfficialCorpusError(
                "shared page multi-fetch result did not align with the section frontier"
            )
        if [str(url).rstrip("/") for url in batch_urls] != [
            url.rstrip("/") for url in official_urls
        ]:
            raise GeorgiaArchivedOfficialCorpusError(
                "shared page multi-fetch changed section locator order or identity"
            )
        fetched_results = []
        for url, content, receipt, envelope in zip(
            batch_urls,
            batch_payloads,
            batch_receipts,
            batch_envelopes,
            strict=True,
        ):
            retrieved_at = getattr(
                getattr(getattr(envelope, "acquisition", None), "receipt", None),
                "retrieved_at",
                "",
            )
            if isinstance(retrieved_at, datetime):
                retrieved_at = retrieved_at.isoformat()
            fetched_results.append(
                _AlignedBodyResult(
                    url=str(url),
                    content=bytes(content or b""),
                    fetched_at=str(retrieved_at or ""),
                    transport_receipt=(
                        dict(receipt) if isinstance(receipt, Mapping) else {}
                    ),
                )
            )
        batch_stats = dict(getattr(batch, "stats", {}) or {})
    elif callable(batch_fetch):
        batch = await batch_fetch(
            official_urls,
            common_crawl_records=common_crawl_records,
            common_crawl_record_loader=common_crawl_record_loader,
            common_crawl_engine=common_crawl_engine,
            max_concurrency=max_concurrency,
            prefer_direct=prefer_direct,
        )
        fetched_results = list(getattr(batch, "results", []) or [])
        batch_errors = list(getattr(batch, "errors", []) or [])
        batch_stats = dict(getattr(batch, "stats", {}) or {})
        if len(fetched_results) != len(sections) or len(batch_errors) != len(sections):
            raise GeorgiaArchivedOfficialCorpusError(
                "archival multi-fetch result did not align with the section frontier"
            )
    else:
        if require_batched_transport:
            raise GeorgiaArchivedOfficialCorpusError(
                "exact body acquisition requires the shared archival multi-fetch transport"
            )
        fetched_results = []
        for official_url in official_urls:
            try:
                fetched_results.append(
                    await fetch_client.fetch_with_fallback(official_url)
                )
            except Exception as exc:  # noqa: BLE001 - aligned failure receipt
                fetched_results.append(None)
                batch_errors[len(fetched_results) - 1] = (
                    f"{type(exc).__name__}: {exc}"
                )
        unique_urls = list(dict.fromkeys(official_urls))
        batch_stats = {
            "common_crawl": {
                "range_fetch_calls": 0,
                "range_fetches_avoided": 0,
                "requested_pages": 0,
            },
            "domains": len(
                {
                    str(urlparse(url).hostname or "").lower()
                    for url in unique_urls
                    if urlparse(url).hostname
                }
            ),
            "duplicate_page_requests_avoided": len(official_urls) - len(unique_urls),
            "fallback_requests": len(unique_urls),
            "legacy_per_page_fallback": True,
            "requested_pages": len(official_urls),
            "unique_pages": len(unique_urls),
        }

    for expected, official_url, result, batch_error in zip(
        sections,
        official_urls,
        fetched_results,
        batch_errors,
    ):
        section = expected["section_number"]
        try:
            if result is None:
                raise RuntimeError(batch_error or "all archival transports missed")
            result_url = str(getattr(result, "url", "") or "").strip()
            if result_url.rstrip("/") != official_url.rstrip("/"):
                raise RuntimeError(
                    "archival multi-fetch response did not match its official locator"
                )
            content = bytes(getattr(result, "content", b"") or b"")
            if not content:
                raise RuntimeError("empty archival response")
            digest = hashlib.sha256(content).hexdigest()
            fetched_at = str(getattr(result, "fetched_at", "") or "")
            retained_receipt = getattr(result, "transport_receipt", None)
            if isinstance(retained_receipt, Mapping) and retained_receipt:
                artifact = dict(retained_receipt)
                artifact.update(
                    {
                        "fetched_at": fetched_at,
                        "official_url": official_url,
                        "section_number": section,
                        "sha256": digest,
                        "size_bytes": len(content),
                    }
                )
                artifact.setdefault("status_code", 200)
            else:
                artifact = {
                    "archive_timestamp": getattr(result, "archive_timestamp", None),
                    "archive_url": getattr(result, "archive_url", None),
                    "fetched_at": fetched_at,
                    "official_url": official_url,
                    "section_number": section,
                    "sha256": digest,
                    "size_bytes": len(content),
                    "source_transport": str(getattr(result, "source", "") or ""),
                }
                for attribute in (
                    "common_crawl_collection",
                    "common_crawl_indexed_url",
                    "common_crawl_warc_filename",
                    "common_crawl_warc_length",
                    "common_crawl_warc_offset",
                    "content_sha256",
                    "status_code",
                ):
                    value = getattr(result, attribute, None)
                    if value is not None:
                        artifact[attribute] = value
            _validate_transport_receipt(artifact, official_url=official_url, digest=digest)
            _validate_artifact_time(
                artifact,
                edition_as_of=str(inventory_payload["edition_as_of"]),
                inventory_observed_at=str(inventory_payload["observed_at"]),
            )
            html = content.decode("utf-8", errors="replace")
            expected_status = expected["expected_disposition"]
            if expected_status == "exclude_nonoperative":
                if not _nonoperative_heading(html, section):
                    raise RuntimeError("archived body does not prove the expected nonoperative status")
                status = "excluded_nonoperative"
            else:
                parsed = parse_georgia_archive_html(
                    html,
                    source_url=official_url,
                    max_statutes=None,
                )
                parsed_sections = {str(row.section_number or "") for row in parsed}
                if parsed_sections != {section} or len(parsed) != 1:
                    raise RuntimeError(
                        "archived body did not parse as exactly one matching statute"
                    )
                status = "admitted"
            object_path = objects_dir / f"{digest}.html"
            if object_path.exists() and object_path.read_bytes() != content:
                raise RuntimeError("content-addressed object collision")
            if not object_path.exists():
                object_path.write_bytes(content)
            artifact.update(
                {
                    "path": object_path.relative_to(root).as_posix(),
                    "status": status,
                }
            )
            artifacts.append(artifact)
        except Exception as exc:  # noqa: BLE001 - each frontier failure needs a receipt row
            artifacts.append(
                {
                    "error": f"{type(exc).__name__}: {exc}",
                    "official_url": official_url,
                    "section_number": section,
                    "status": "failed",
                }
            )

    admitted = sum(row.get("status") == "admitted" for row in artifacts)
    excluded = sum(row.get("status") == "excluded_nonoperative" for row in artifacts)
    failed = sum(row.get("status") == "failed" for row in artifacts)
    discovered = len(sections)
    batch_stats.setdefault("requested_pages", len(official_urls))
    batch_stats.setdefault("unique_pages", len(set(official_urls)))
    batch_stats.setdefault("successful_pages", admitted + excluded)
    batch_stats.setdefault("failed_pages", failed)
    frontier = {
        "closed": failed == 0 and admitted + excluded == discovered,
        "discovered": discovered,
        "duplicates": 0,
        "excluded": excluded,
        "failed_final": failed,
        "fetched": admitted,
        "frontier_closed": failed == 0 and admitted + excluded == discovered,
        "quarantined": 0,
        "section_numbers_sha256": _canonical_sha256(sorted(row["section_number"] for row in sections)),
    }
    frontier["frontier_digest_sha256"] = _frontier_sha256(frontier)
    manifest = {
        "artifacts": artifacts,
        "content_hashes": sorted(
            str(row.get("sha256")) for row in artifacts if _is_sha256(row.get("sha256"))
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "inventory": inventory_payload,
        "inventory_sha256": inventory_sha256,
        "jurisdiction": "GA",
        "official_source": True,
        "schema": MANIFEST_SCHEMA,
        "source_authority_class": "official",
        "source_kind": SOURCE_KIND,
        "transport_batch": batch_stats,
        "verification_result": "verified" if frontier["closed"] else "failed",
        "frontier": frontier,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = root / f"manifest-{stamp}-{inventory_sha256[:16]}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "closed": frontier["closed"],
        "frontier": frontier,
        "manifest": manifest,
        "manifest_path": str(manifest_path),
    }


async def acquire_georgia_archived_official_with_shared_transport(
    inventory: Mapping[str, Any],
    output_dir: str | Path,
    *,
    acquisition_evidence_root: str | Path,
    max_concurrency: int = 8,
    prefer_direct: bool = False,
) -> dict[str, Any]:
    """Run exact Georgia body acquisition through the shared retained seam.

    The attached prospective ledger replays already verified parser inputs on
    restart and retains each newly completed page before the rest of the
    frontier can fail.  The base scraper performs one Common Crawl inventory
    lookup for the outstanding same-domain frontier, while the web-archiving
    client groups exact pointers by WARC object and coalesces nearby ranges.
    This wrapper intentionally owns that transport plan so callers cannot
    accidentally combine it with a second per-page archive path.
    """

    from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
        StateLawMultiFetchAcquisitionLedger,
    )

    from .georgia import GeorgiaScraper

    scraper = GeorgiaScraper("GA", "Georgia")
    ledger = StateLawMultiFetchAcquisitionLedger(
        acquisition_evidence_root,
        jurisdiction="GA",
        parser_name=type(scraper).__name__,
    )
    scraper.attach_state_law_acquisition_ledger(ledger)
    result = await acquire_georgia_archived_official_corpus(
        inventory,
        output_dir,
        page_batch_fetcher=scraper._fetch_page_contents_with_archival_fallback,
        max_concurrency=max_concurrency,
        prefer_direct=prefer_direct,
    )
    result["acquisition_evidence_root"] = str(ledger.jurisdiction_root)
    result["retained_parser_inputs"] = len(ledger.entries)
    return result


__all__ = [
    "INVENTORY_SCHEMA",
    "INVENTORY_SOURCE_KIND",
    "MANIFEST_ENV",
    "MANIFEST_SCHEMA",
    "SOURCE_KIND",
    "GeorgiaArchivedOfficialCorpus",
    "GeorgiaArchivedOfficialCorpusError",
    "acquire_georgia_archived_official_corpus",
    "acquire_georgia_archived_official_with_shared_transport",
    "build_georgia_delegated_inventory",
    "configured_georgia_archived_official_manifest_path",
    "load_georgia_archived_official_corpus",
]
