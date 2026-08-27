"""Official Indiana Code HTML zip parser.

Adapted from Vaquill-AI/open-us-law ``in_bulk`` (Apache-2.0). iga.in.gov
publishes a year-templated HTML zip:

    https://iga.in.gov/ic/{year}/{year}-Indiana-Code-html.zip

The live site geo-fences the zip; this adapter never auto-downloads. Operators
point ``INDIANA_BULK_ZIP`` at a local copy.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

from .base_scraper import (
    NormalizedStatute,
    StatuteMetadata,
    current_state_law_run_environment_value,
)

_STRUCT_DIV = re.compile(
    r"<div\s+class\s*=\s*[\"'](title|article|chapter|section)[\"']"
    r"\s+id\s*=\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_SHORTDESC = re.compile(
    r"<span\s+id\s*=\s*[\"']shortdescription[\"'][^>]*>(.*?)</span>",
    re.DOTALL | re.IGNORECASE,
)
_P_BLOCK = re.compile(r"<p\b[^>]*>(.*?)</p>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_INACTIVE_HEADINGS = {
    "expired": "repealed",
    "renumbered": "reserved",
    "repealed": "repealed",
    "reserved": "reserved",
    "transferred": "reserved",
    "vacated": "repealed",
}


_ZIP_MAGIC = b"PK\x03\x04"
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_OFFICIAL_ZIP_PATH_RE = re.compile(
    r"^/ic/(?P<year>\d{4})/(?P=year)-Indiana-Code(?:-html)?\.zip$",
    re.IGNORECASE,
)
LARGE_FILE_TRANSPORT_RECEIPT_SCHEMA = (
    "state-laws-large-file-transport-receipt-v1"
)
INDIANA_BULK_INVENTORY_SCHEMA = "indiana-code-html-zip-inventory-v1"


class IndianaBulkProvenanceError(ValueError):
    """The configured local ZIP lacks byte-bound official origin evidence."""


class IndianaBulkFrontierError(RuntimeError):
    """The official ZIP cannot prove a closed, lossless section frontier."""


def _canonical_json_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strings_sha256(values: List[str]) -> str:
    return _canonical_json_sha256({"values": list(values)})


def zip_url(year: int | str) -> str:
    token = str(int(year))
    return f"https://iga.in.gov/ic/{token}/{token}-Indiana-Code-html.zip"


def zip_url_candidates(year: int | str) -> List[str]:
    """Current edition then prior year. Never auto-downloads the geo-fenced zip."""

    base = int(year)
    return [zip_url(base), zip_url(base - 1)]


def looks_like_zip(path: Path) -> bool:
    """Reject the geo-fence SPA shell (HTTP 200, ~691 bytes, not ``PK``)."""

    try:
        with Path(path).open("rb") as handle:
            magic = handle.read(4)
    except OSError:
        return False
    return magic == _ZIP_MAGIC


def configured_bulk_zip_receipt_path(zip_path: Path) -> Path:
    """Resolve an explicit or adjacent receipt for an operator-provided ZIP."""

    raw = str(
        current_state_law_run_environment_value("INDIANA_BULK_ZIP_RECEIPT")
        or current_state_law_run_environment_value("INDIANA_CODE_ZIP_RECEIPT")
        or ""
    ).strip()
    if raw:
        return Path(raw).expanduser()
    return Path(f"{Path(zip_path).expanduser()}.receipt.json")


def load_indiana_bulk_transport_receipt(
    zip_path: Path,
    *,
    receipt_path: Optional[Path] = None,
    expected_official_url: Optional[str] = None,
    expected_year: Optional[int | str] = None,
) -> Dict[str, Any]:
    """Validate an official, byte-size-bound Indiana ZIP sidecar.

    The shared multi-fetch ledger performs the streaming SHA-256 comparison
    while retaining the archive.  This preflight rejects originless cache
    files before they can reach the parser and binds the remaining response
    metadata without reading the archive into memory.
    """

    archive_path = Path(zip_path).expanduser()
    if archive_path.is_symlink() or not archive_path.is_file():
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP must be a regular non-symlink file"
        )
    sidecar_path = Path(
        receipt_path
        if receipt_path is not None
        else configured_bulk_zip_receipt_path(archive_path)
    ).expanduser()
    if sidecar_path.is_symlink() or not sidecar_path.is_file():
        raise IndianaBulkProvenanceError(
            f"Indiana bulk ZIP transport receipt is missing: {sidecar_path}"
        )
    try:
        payload = json.loads(
            sidecar_path.read_text(encoding="utf-8", errors="strict")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP transport receipt is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP transport receipt must be a JSON object"
        )
    receipt = dict(payload)
    if receipt.get("schema_version") != LARGE_FILE_TRANSPORT_RECEIPT_SCHEMA:
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP transport receipt has the wrong schema"
        )

    official_url = str(receipt.get("official_url") or "").strip()
    parsed = urlparse(official_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt official_url has an invalid port"
        ) from exc
    match = _OFFICIAL_ZIP_PATH_RE.fullmatch(parsed.path or "")
    official_name = Path(parsed.path).name
    code_year = str(match.group("year")) if match is not None else ""
    local_name_aliases = {official_name.lower()}
    if code_year:
        local_name_aliases.add(
            f"{code_year}-indiana-code-"
            f"{'html' if '-html.zip' in official_name.lower() else 'full'}.zip"
        )
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != "iga.in.gov"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or match is None
        or archive_path.name.lower() not in local_name_aliases
    ):
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt does not identify the configured "
            "official Indiana Code archive"
        )
    if expected_official_url is not None and official_url.rstrip("/") != str(
        expected_official_url
    ).strip().rstrip("/"):
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt official_url differs from the requested archive"
        )
    if expected_year is not None and code_year != str(int(expected_year)):
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt year differs from the requested edition"
        )

    digest = str(receipt.get("content_sha256") or "").strip().lower()
    if _SHA256_RE.fullmatch(digest) is None:
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt content_sha256 must be exact"
        )
    receipt["content_sha256"] = digest

    declared_size = receipt.get("byte_size")
    if isinstance(declared_size, bool):
        declared_size = None
    try:
        expected_size = int(declared_size)
    except (TypeError, ValueError) as exc:
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt byte_size must be an integer"
        ) from exc
    actual_size = archive_path.stat().st_size
    if expected_size <= 0 or expected_size != actual_size:
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt byte_size does not match the local archive"
        )
    receipt["byte_size"] = expected_size

    if receipt.get("response_status") != 200:
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt must record HTTP status 200"
        )
    media_type = str(receipt.get("media_type") or "").strip().lower()
    if media_type.split(";", 1)[0] != "application/zip":
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt must record application/zip"
        )
    receipt["media_type"] = media_type

    retrieved_at = str(receipt.get("retrieved_at") or "").strip()
    try:
        observed = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt retrieved_at must be ISO-8601"
        ) from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt retrieved_at must include a timezone"
        )

    headers = receipt.get("response_headers")
    if headers is not None and not isinstance(headers, Mapping):
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt response_headers must be an object"
        )
    if isinstance(headers, Mapping):
        if headers.get("content-length") not in (None, ""):
            try:
                header_size = int(str(headers["content-length"]).strip())
            except ValueError as exc:
                raise IndianaBulkProvenanceError(
                    "Indiana bulk ZIP receipt Content-Length is invalid"
                ) from exc
            if header_size != expected_size:
                raise IndianaBulkProvenanceError(
                    "Indiana bulk ZIP receipt Content-Length disagrees with byte_size"
                )
        if headers.get("content-type") not in (None, "") and str(
            headers["content-type"]
        ).strip().lower().split(";", 1)[0] != "application/zip":
            raise IndianaBulkProvenanceError(
                "Indiana bulk ZIP receipt Content-Type disagrees with media_type"
            )

    try:
        from ...legal_data.state_laws_source_provenance import (
            verify_state_law_transport_receipt,
        )

        verify_state_law_transport_receipt(
            receipt,
            official_url=official_url,
            content_sha256=digest,
        )
    except Exception as exc:
        raise IndianaBulkProvenanceError(
            "Indiana bulk ZIP receipt lacks a verified direct/archive/cache origin"
        ) from exc
    receipt["code_year"] = code_year
    return receipt


def _text(fragment: str) -> str:
    text = _TAG.sub("", fragment)
    text = html_lib.unescape(text)
    text = text.replace("\xa0", " ").replace("\u2005", " ").replace("\u202f", " ")
    return _WS.sub(" ", text).strip()


def iter_section_blocks(html: str) -> Iterator[Tuple[str, str, List[str], Optional[str]]]:
    """Yield ``(section_id, heading, paragraphs, status)`` from one title HTML file."""

    matches = list(_STRUCT_DIV.finditer(html or ""))
    for index, match in enumerate(matches):
        cls, node_id = match.group(1), match.group(2)
        if cls != "section":
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        block = html[match.start() : end]
        short = _SHORTDESC.search(block)
        heading = _text(short.group(1)) if short else ""
        paragraphs = [_text(item.group(1)) for item in _P_BLOCK.finditer(block) if _text(item.group(1))]
        # Status is a source field, not a keyword search over the law text.
        # Hundreds of active Indiana provisions discuss laws being repealed,
        # transferred property, expired credentials, or reserved parking.
        # Only an explicit whole-heading status may exclude a section.
        normalized_heading = heading.strip().lower().strip(" .:;()[]")
        status = _INACTIVE_HEADINGS.get(normalized_heading)
        yield node_id, heading, paragraphs, status


def _bundle_projection(bundle_provenance: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(bundle_provenance, Mapping):
        return {}
    return {
        "byte_size": int(bundle_provenance.get("byte_size") or 0),
        "content_sha256": str(bundle_provenance.get("content_sha256") or ""),
        "media_type": str(bundle_provenance.get("media_type") or ""),
        "official_url": str(bundle_provenance.get("official_url") or ""),
        "retrieved_at": str(bundle_provenance.get("retrieved_at") or ""),
    }


def _scan_indiana_bulk_zip(
    zip_path: Path,
    *,
    code_name: str,
    max_statutes: Optional[int],
    code_year: str,
    bundle_provenance: Optional[Mapping[str, Any]],
    emit_rows: bool,
) -> Tuple[List[NormalizedStatute], Dict[str, Any]]:
    path = Path(zip_path)
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"Indiana bulk zip missing: {path}")
    if not looks_like_zip(path):
        raise IndianaBulkFrontierError("Indiana bulk ZIP has invalid ZIP magic")
    limit = None if max_statutes is None else max(0, int(max_statutes))
    statutes: List[NormalizedStatute] = []
    source_record_ids: List[str] = []
    admitted_source_record_ids: List[str] = []
    excluded_source_record_ids: List[str] = []
    unusable_rows: List[Dict[str, Any]] = []
    member_inventory: List[Dict[str, Any]] = []
    seen_source_ids: set[str] = set()
    duplicate_count = 0
    capped = False

    with zipfile.ZipFile(path) as archive:
        all_names = list(archive.namelist())
        if len(all_names) != len(set(all_names)):
            raise IndianaBulkFrontierError(
                "Indiana bulk ZIP contains duplicate member paths"
            )
        names = sorted(name for name in all_names if name.lower().endswith(".html"))
        if not names:
            raise IndianaBulkFrontierError(
                "Indiana bulk ZIP contains no title HTML members"
            )
        for name in names:
            if limit is not None and len(statutes) >= limit:
                capped = True
                break
            raw_member = archive.read(name)
            member_digest = hashlib.sha256(raw_member).hexdigest()
            try:
                html = raw_member.decode("utf-8", errors="strict")
            except UnicodeError:
                unusable_rows.append(
                    {
                        "disposition": "failed_final",
                        "member_path": name,
                        "reason": "invalid_utf8_member",
                        "source_record_id": "",
                    }
                )
                member_inventory.append(
                    {
                        "byte_size": len(raw_member),
                        "content_sha256": member_digest,
                        "path": name,
                        "section_count": 0,
                    }
                )
                continue
            member_section_count = 0
            for node_id, heading, paragraphs, status in iter_section_blocks(html):
                if limit is not None and len(statutes) >= limit:
                    capped = True
                    break
                member_section_count += 1
                source_record_id = str(node_id or "").strip()
                if not source_record_id:
                    unusable_rows.append(
                        {
                            "disposition": "failed_final",
                            "member_path": name,
                            "reason": "missing_source_record_id",
                            "source_record_id": "",
                        }
                    )
                    continue
                source_record_ids.append(source_record_id)
                if source_record_id in seen_source_ids:
                    duplicate_count += 1
                    unusable_rows.append(
                        {
                            "disposition": "duplicate",
                            "member_path": name,
                            "reason": "duplicate_source_record_id",
                            "source_record_id": source_record_id,
                        }
                    )
                    continue
                seen_source_ids.add(source_record_id)
                if status:
                    excluded_source_record_ids.append(source_record_id)
                    continue
                body = " ".join(paragraphs).strip()
                if not body:
                    unusable_rows.append(
                        {
                            "disposition": "failed_final",
                            "member_path": name,
                            "reason": "empty_body",
                            "source_record_id": source_record_id,
                        }
                    )
                    continue
                admitted_source_record_ids.append(source_record_id)
                if not emit_rows:
                    continue
                title_num = source_record_id.split("-", 1)[0]
                source_url = (
                    f"https://iga.in.gov/legislative/laws/{code_year}/ic/titles/{title_num}"
                    f"#{source_record_id}"
                )
                source_bundle = _bundle_projection(bundle_provenance)
                structured_data: Dict[str, Any] = {
                    "source_kind": "official_indiana_code_html_zip",
                    "source_authority_class": "official",
                    "discovery_method": "iga_indiana_code_html_zip",
                    "code_year": str(code_year),
                    "source_record_id": source_record_id,
                    "source_member": {
                        "byte_size": len(raw_member),
                        "content_sha256": member_digest,
                        "path": name,
                    },
                    "skip_hydrate": True,
                }
                if source_bundle:
                    structured_data.update(
                        {
                            "content_sha256": str(
                                source_bundle.get("content_sha256") or ""
                            ),
                            "source_bundle": source_bundle,
                        }
                    )
                    receipt = bundle_provenance.get("transport_receipt")
                    if isinstance(receipt, Mapping):
                        structured_data["transport_receipt"] = dict(receipt)
                statutes.append(
                    NormalizedStatute(
                        state_code="IN",
                        state_name="Indiana",
                        statute_id=f"{code_name} § {source_record_id}",
                        code_name=code_name,
                        title_number=title_num,
                        section_number=source_record_id,
                        section_name=(
                            heading[:200]
                            if heading
                            else f"Section {source_record_id}"
                        ),
                        full_text=body,
                        source_url=source_url,
                        official_cite=f"Ind. Code § {source_record_id}",
                        metadata=StatuteMetadata(),
                        structured_data=structured_data,
                    )
                )
            member_inventory.append(
                {
                    "byte_size": len(raw_member),
                    "content_sha256": member_digest,
                    "path": name,
                    "section_count": member_section_count,
                }
            )

    failed_final = sum(
        item.get("disposition") == "failed_final" for item in unusable_rows
    )
    discovered = len(source_record_ids) + sum(
        1 for item in unusable_rows if not item.get("source_record_id")
    )
    inventory: Dict[str, Any] = {
        "schema_version": INDIANA_BULK_INVENTORY_SCHEMA,
        "jurisdiction": "IN",
        "code_name": str(code_name),
        "code_year": str(code_year),
        "bundle": _bundle_projection(bundle_provenance),
        "archive_member_count": len(all_names),
        "archive_member_paths_sha256": _strings_sha256(sorted(all_names)),
        "html_member_count": len(names),
        "visited_html_member_count": len(member_inventory),
        "html_members": member_inventory,
        "source_record_count": len(source_record_ids),
        "source_record_ids": source_record_ids,
        "source_record_ids_sha256": _strings_sha256(source_record_ids),
        "admitted_source_record_count": len(admitted_source_record_ids),
        "admitted_source_record_ids": admitted_source_record_ids,
        "admitted_source_record_ids_sha256": _strings_sha256(
            admitted_source_record_ids
        ),
        "admitted_canonical_keys": [
            f"urn:state:in:statute:{code_name} § {source_record_id}"
            for source_record_id in admitted_source_record_ids
        ],
        "excluded_source_record_count": len(excluded_source_record_ids),
        "excluded_source_record_ids": excluded_source_record_ids,
        "excluded_source_record_ids_sha256": _strings_sha256(
            excluded_source_record_ids
        ),
        "unusable_row_count": failed_final,
        "unusable_rows": unusable_rows,
        "disposition": {
            "discovered": discovered,
            "duplicates": duplicate_count,
            "excluded": len(excluded_source_record_ids),
            "failed_final": failed_final,
            "fetched": len(admitted_source_record_ids),
            "quarantined": 0,
        },
        "boundary_probes": {
            "first_source_record_id": source_record_ids[0]
            if source_record_ids
            else "",
            "last_source_record_id": source_record_ids[-1]
            if source_record_ids
            else "",
            "first_html_member": member_inventory[0]["path"]
            if member_inventory
            else "",
            "last_html_member": member_inventory[-1]["path"]
            if member_inventory
            else "",
        },
        "frontier": {
            "bundle_closed": not capped,
            "capped": capped,
            "closed": not capped and failed_final == 0 and duplicate_count == 0,
            "enumerator_closed": not capped,
            "expected_index_units": len(names),
            "remaining_bundle_members": (
                [] if not capped else names[len(member_inventory) :]
            ),
            "scope_closed": not capped,
            "unvisited_continuation_links": [],
            "visited_index_units": (
                len(names) if not capped else len(member_inventory)
            ),
        },
    }
    inventory["inventory_sha256"] = _canonical_json_sha256(inventory)
    return statutes, inventory


def parse_indiana_bulk_zip(
    zip_path: Path,
    *,
    code_name: str = "Indiana Code",
    max_statutes: Optional[int] = None,
    code_year: str = "2026",
    bundle_provenance: Optional[Mapping[str, Any]] = None,
    inventory_observer: Optional[Callable[[Mapping[str, Any]], None]] = None,
    fail_on_unusable: bool = False,
) -> List[NormalizedStatute]:
    """Parse official Indiana Code HTML zip into NormalizedStatute rows."""

    path = Path(zip_path)
    if not path.is_file():
        raise FileNotFoundError(f"Indiana bulk zip missing: {path}")
    if not looks_like_zip(path):
        if fail_on_unusable or inventory_observer is not None:
            raise IndianaBulkFrontierError(
                "Indiana bulk ZIP has invalid ZIP magic"
            )
        return []
    statutes, inventory = _scan_indiana_bulk_zip(
        path,
        code_name=code_name,
        max_statutes=max_statutes,
        code_year=str(code_year),
        bundle_provenance=bundle_provenance,
        emit_rows=True,
    )
    if inventory_observer is not None:
        inventory_observer(inventory)
    if fail_on_unusable and inventory["frontier"]["closed"] is not True:
        raise IndianaBulkFrontierError(
            "Indiana bulk ZIP has unresolved records or a capped frontier"
        )
    return statutes


def inventory_indiana_bulk_zip(
    zip_path: Path,
    *,
    code_name: str = "Indiana Code",
    code_year: str = "2026",
    bundle_provenance: Mapping[str, Any],
) -> Dict[str, Any]:
    """Replay the exact uncapped ZIP section inventory without emitting rows."""

    _rows, inventory = _scan_indiana_bulk_zip(
        zip_path,
        code_name=code_name,
        max_statutes=None,
        code_year=str(code_year),
        bundle_provenance=bundle_provenance,
        emit_rows=False,
    )
    return inventory


def configured_bulk_zip_path() -> Optional[Path]:
    raw = current_state_law_run_environment_value("INDIANA_BULK_ZIP").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


API_BASE = "https://api.iga.in.gov"
SITE_BASE = "https://iga.in.gov"


def titles_api_url(year: int | str = 2024) -> str:
    return f"{API_BASE}/{int(year)}/ic/titles"


def _payload_list(data, *keys: str) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _number(obj: dict, *keys: str) -> str:
    for key in keys:
        value = obj.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def titles_from_payload(data) -> List[Tuple[str, str]]:
    """``GET /{year}/ic/titles`` rows. No live API call."""

    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for item in _payload_list(data, "titles", "items", "data", "results"):
        if not isinstance(item, dict):
            continue
        number = _number(item, "titleNumber", "number", "title", "id")
        if not number or number in seen:
            continue
        seen.add(number)
        name = str(item.get("name") or item.get("titleName") or item.get("title") or f"Title {number}")
        out.append((number, name))
    return out


def nested_from_payload(data, *, kind: str) -> List[Tuple[str, str]]:
    """Articles/chapters/sections lists from an IGA JSON object."""

    key_map = {
        "article": ("articles", "articleNumber", "article", "articleName"),
        "chapter": ("chapters", "chapterNumber", "chapter", "chapterName"),
        "section": ("sections", "sectionNumber", "section", "sectionName"),
    }
    list_key, number_key, alt_key, name_key = key_map[kind]
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for item in _payload_list(data, list_key, "items", "data"):
        if not isinstance(item, dict):
            continue
        number = _number(item, number_key, "number", alt_key, "id")
        if not number or number in seen:
            continue
        seen.add(number)
        name = str(item.get(name_key) or item.get("name") or item.get(alt_key) or number)
        out.append((number, name))
    return out


def normalize_section(raw: str, title: str, article: str, chapter: str) -> str:
    parts = re.split(r"[-.]", str(raw or "").strip())
    if len(parts) == 4:
        return "-".join(str(int(part)) if part.isdigit() else part for part in parts)
    t = str(int(title)) if str(title).isdigit() else title
    a = str(int(article)) if str(article).isdigit() else article
    c = str(int(chapter)) if str(chapter).isdigit() else chapter
    s = str(int(raw)) if str(raw).isdigit() else str(raw or "").strip()
    return f"{t}-{a}-{c}-{s}"
