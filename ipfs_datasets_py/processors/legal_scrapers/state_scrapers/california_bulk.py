"""Official California bulk CAML export (downloads.leginfo.legislature.ca.gov).

Adapted from Vaquill-AI/open-us-law ``ca_bulk`` (Apache-2.0). The HTML
LegInfo app publishes ``Disallow: /``; the downloads host is the sanctioned
database dump and is official, not a secondary mirror.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set, Tuple
from urllib.parse import quote, urlparse

from .base_scraper import (
    NormalizedStatute,
    current_state_law_run_environment_value,
)

OFFICIAL_DOWNLOADS_HOST = "downloads.leginfo.legislature.ca.gov"
LARGE_FILE_TRANSPORT_RECEIPT_SCHEMA = (
    "state-laws-large-file-transport-receipt-v1"
)
CALIFORNIA_BULK_INVENTORY_SCHEMA = (
    "california-pubinfo-law-section-inventory-v1"
)
OFFICIAL_SECTION_URL = (
    "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml"
    "?lawCode={code}&sectionNum={section}"
)
OFFICIAL_CONSTITUTION_URL = (
    "https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml"
    "?lawCode=CONS&article={article}"
)

# LAW_SECTION_TBL columns, as declared by the official ``capublic.sql``.
# ``op_statues`` is the spelling used by the source schema.
LAW_SECTION_COLUMNS = (
    "id",
    "law_code",
    "section_num",
    "op_statues",
    "op_chapter",
    "op_section",
    "effective_date",
    "law_section_version_id",
    "division",
    "title",
    "part",
    "chapter",
    "article",
    "history",
    "content_xml",
    "active_flg",
    "trans_uid",
    "trans_update",
)
S_RECORD_ID, S_CODE, S_SECT, S_ARTICLE, S_LOB = 0, 1, 2, 12, 14

_WS = re.compile(r"\s+")
_BLANKS = re.compile(r"\n{3,}")
_CONS_SECTION_PREFIX = re.compile(r"^(?:SECTION|SEC\.)\s*", re.IGNORECASE)
_KNOWN_CAML = {
    "[document]",
    "caml:content",
    "content",
    "p",
    "h1",
    "br",
    "span",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
    "col",
    "colgroup",
    "caml:fraction",
    "caml:numerator",
    "caml:denominator",
    "b",
    "i",
    "u",
    "sub",
    "sup",
    "em",
    "strong",
    "caml:tipin",
    "caml:labelledfield",
}
_PARA = {"p", "h1", "table"}
_ROW = {"tr"}
_CELL = {"td", "th"}


_ZIP_MAGIC = b"PK\x03\x04"
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_PUBINFO_ZIP_RE = re.compile(r"^pubinfo_\d{4}\.zip$", re.IGNORECASE)


class CaliforniaBulkProvenanceError(ValueError):
    """The configured official bulk archive lacks exact origin evidence."""


class CaliforniaBulkFrontierError(RuntimeError):
    """The official table inventory contains unresolved source records."""

    def __init__(
        self,
        message: str,
        *,
        inventory: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.inventory = dict(inventory) if isinstance(inventory, Mapping) else {}
        super().__init__(message)


def _canonical_json_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def session_zip_url(session: str) -> str:
    """Official pubinfo zip for one two-year legislative session."""

    year = str(session or "").strip() or "2025"
    return f"https://{OFFICIAL_DOWNLOADS_HOST}/pubinfo_{year}.zip"


def session_zip_url_candidates(session: str) -> List[str]:
    """Current two-year session then prior. Never auto-downloads the ~1.1GB zip."""

    try:
        year = int(str(session or "").strip() or "2025")
    except ValueError:
        year = 2025
    return [session_zip_url(str(year)), session_zip_url(str(year - 2))]


def looks_like_zip(path: Path) -> bool:
    try:
        with Path(path).open("rb") as handle:
            magic = handle.read(4)
    except OSError:
        return False
    return magic == _ZIP_MAGIC


def bulk_zip_table_names(zip_path: Path) -> List[str]:
    """Local zip namelist of ``*_TBL.dat`` members. Never range-fetches the remote zip."""

    path = Path(zip_path)
    if not path.is_file() or not looks_like_zip(path):
        return []
    with zipfile.ZipFile(path) as archive:
        return sorted(
            name
            for name in archive.namelist()
            if name.upper().endswith("_TBL.DAT") or name.upper().endswith("_TBL.TXT")
        )


def configured_bulk_zip_receipt_path(zip_path: Path) -> Path:
    """Resolve an explicit or adjacent transport receipt for one local ZIP."""

    raw = current_state_law_run_environment_value(
        "CALIFORNIA_BULK_ZIP_RECEIPT"
    ).strip()
    if raw:
        return Path(raw).expanduser()
    return Path(f"{Path(zip_path).expanduser()}.receipt.json")


def load_california_bulk_transport_receipt(
    zip_path: Path,
    *,
    receipt_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load and structurally validate a byte-bound official ZIP receipt.

    SHA-256 fixity is deliberately completed by
    ``StateLawMultiFetchAcquisitionLedger.retain_parser_input_file`` while it
    streams the archive into immutable evidence.  This preflight validates
    the sidecar's source identity, size, media type, status, and observation
    time without loading or hashing the large file a second time.
    """

    archive_path = Path(zip_path).expanduser()
    if archive_path.is_symlink() or not archive_path.is_file():
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP must be a regular non-symlink file"
        )
    sidecar_path = Path(
        receipt_path
        if receipt_path is not None
        else configured_bulk_zip_receipt_path(archive_path)
    ).expanduser()
    if sidecar_path.is_symlink() or not sidecar_path.is_file():
        raise CaliforniaBulkProvenanceError(
            f"California bulk ZIP transport receipt is missing: {sidecar_path}"
        )
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP transport receipt is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP transport receipt must be a JSON object"
        )
    receipt = dict(payload)
    if receipt.get("schema_version") != LARGE_FILE_TRANSPORT_RECEIPT_SCHEMA:
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP transport receipt has the wrong schema"
        )

    official_url = str(receipt.get("official_url") or "").strip()
    parsed = urlparse(official_url)
    official_name = Path(parsed.path).name
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != OFFICIAL_DOWNLOADS_HOST
        or parsed.username is not None
        or parsed.password is not None
        or not _PUBINFO_ZIP_RE.fullmatch(official_name)
        or official_name.lower() != archive_path.name.lower()
    ):
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP receipt does not identify the configured "
            "official pubinfo archive"
        )

    digest = str(receipt.get("content_sha256") or "").strip().lower()
    if _SHA256_RE.fullmatch(digest) is None:
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP receipt content_sha256 must be exact"
        )
    receipt["content_sha256"] = digest

    declared_size = receipt.get("byte_size")
    if isinstance(declared_size, bool):
        declared_size = None
    try:
        expected_size = int(declared_size)
    except (TypeError, ValueError) as exc:
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP receipt byte_size must be an integer"
        ) from exc
    actual_size = archive_path.stat().st_size
    if expected_size <= 0 or expected_size != actual_size:
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP receipt byte_size does not match the local archive"
        )
    receipt["byte_size"] = expected_size

    if receipt.get("response_status") != 200:
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP receipt must record HTTP status 200"
        )
    media_type = str(receipt.get("media_type") or "").strip().lower()
    if media_type.split(";", 1)[0] != "application/zip":
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP receipt must record application/zip"
        )
    receipt["media_type"] = media_type

    retrieved_at = str(receipt.get("retrieved_at") or "").strip()
    try:
        observed = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP receipt retrieved_at must be ISO-8601"
        ) from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP receipt retrieved_at must include a timezone"
        )

    headers = receipt.get("response_headers")
    if headers is not None and not isinstance(headers, Mapping):
        raise CaliforniaBulkProvenanceError(
            "California bulk ZIP receipt response_headers must be an object"
        )
    if isinstance(headers, Mapping) and headers.get("content-length") not in (None, ""):
        try:
            header_size = int(str(headers["content-length"]).strip())
        except ValueError as exc:
            raise CaliforniaBulkProvenanceError(
                "California bulk ZIP receipt Content-Length is invalid"
            ) from exc
        if header_size != expected_size:
            raise CaliforniaBulkProvenanceError(
                "California bulk ZIP receipt Content-Length disagrees with byte_size"
            )
    return receipt


def _member_provenance(
    archive: zipfile.ZipFile,
    member_path: str,
    raw_bytes: bytes,
) -> Dict[str, Any]:
    info = archive.getinfo(member_path)
    return {
        "byte_size": len(raw_bytes),
        "compressed_byte_size": int(info.compress_size),
        "content_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "crc32": f"{int(info.CRC):08x}",
        "path": member_path,
    }


def unquote_field(value: str) -> Optional[str]:
    text = str(value or "").strip()
    if text.startswith("`") and text.endswith("`") and len(text) >= 2:
        text = text[1:-1]
    if text in {"", "NULL"}:
        return None
    return text


def caml_to_text(xml: str) -> Tuple[str, Set[str]]:
    """Convert one CAML section body to plain text.

    Fractions become ``4/5`` (not ``45``). Tables keep row/cell text. Unknown
    tags keep inner text and are reported.
    """

    if not xml or not str(xml).strip():
        return "", set()
    try:
        from bs4 import BeautifulSoup
        from bs4.element import NavigableString, Tag
    except ImportError:
        return str(xml), set()

    soup = BeautifulSoup(xml, "html.parser")
    unknown = {
        tag.name.lower()
        for tag in soup.find_all(True)
        if tag.name and tag.name.lower() not in _KNOWN_CAML
    }

    def _walk(node: Any) -> str:
        if isinstance(node, NavigableString):
            return _WS.sub(" ", str(node))
        if not isinstance(node, Tag):
            return ""
        name = str(node.name or "").lower()
        if name == "br":
            return "\n"
        if name == "span":
            classes = node.get("class") or []
            if any("enspace" in str(item).lower() for item in classes) or not node.get_text(
                strip=True
            ):
                return " "
            return "".join(_walk(child) for child in node.children)
        if name == "caml:fraction":
            num = node.find("caml:numerator")
            den = node.find("caml:denominator")
            if num is not None and den is not None:
                frac = f"{num.get_text(strip=True)}/{den.get_text(strip=True)}"
                prev = node.previous_sibling
                if isinstance(prev, NavigableString) and prev.rstrip()[-1:].isdigit():
                    frac = " " + frac
                return frac
            return "".join(_walk(child) for child in node.children)
        inner = "".join(_walk(child) for child in node.children)
        if name in _CELL:
            return inner.strip() + " "
        if name in _ROW:
            return "\n" + inner.strip()
        if name in _PARA:
            return "\n\n" + inner + "\n\n"
        return inner

    text = _walk(soup)
    lines = [line.strip() for line in text.split("\n")]
    text = _BLANKS.sub("\n\n", "\n".join(lines)).strip()
    return text, unknown


def _iter_section_rows(table_text: str) -> Iterable[List[str]]:
    for line in table_text.splitlines():
        if not line.strip():
            continue
        yield line.split("\t")


def parse_california_bulk_zip_codes(
    zip_path: Path,
    *,
    code_types: Iterable[str],
    max_statutes: Optional[int] = None,
    code_names: Optional[Mapping[str, str]] = None,
    bundle_provenance: Optional[Mapping[str, Any]] = None,
    inventory_observer: Optional[Callable[[Mapping[str, Any]], None]] = None,
    inventory_only: bool = False,
    fail_on_unusable: bool = False,
) -> Dict[str, List[NormalizedStatute]]:
    """Parse requested code families in one pass over ``LAW_SECTION_TBL.dat``.

    ``max_statutes`` is applied independently to each requested family.  The
    returned mapping includes every non-empty requested code, even when the
    archive contains no admissible rows for it.  An ``inventory_observer``
    requests an exhaustive table/body pass and receives one deterministic
    inventory before any rows are returned to the caller. ``inventory_only``
    performs that same pass without allocating normalized statute rows.
    """

    wanted_codes: List[str] = []
    seen_codes: Set[str] = set()
    for raw_code in code_types:
        code = str(raw_code or "").strip().upper()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        wanted_codes.append(code)
    if not wanted_codes:
        return {}

    normalized_names = {
        str(code or "").strip().upper(): str(name or "").strip()
        for code, name in dict(code_names or {}).items()
        if str(code or "").strip()
    }
    limit = None if max_statutes is None else max(0, int(max_statutes))
    retained_bundle = (
        dict(bundle_provenance)
        if isinstance(bundle_provenance, Mapping)
        else {}
    )
    exhaustive_inventory = inventory_observer is not None or bool(inventory_only)
    if fail_on_unusable and inventory_observer is None:
        raise ValueError("fail_on_unusable requires an inventory_observer")
    bundle_digest = str(
        retained_bundle.get("content_sha256") or ""
    ).strip().lower()
    bundle_receipt = retained_bundle.get("transport_receipt")
    if retained_bundle and (
        _SHA256_RE.fullmatch(bundle_digest) is None
        or not isinstance(bundle_receipt, Mapping)
    ):
        raise CaliforniaBulkProvenanceError(
            "retained California bundle provenance is incomplete"
        )
    if exhaustive_inventory and not retained_bundle:
        raise CaliforniaBulkProvenanceError(
            "an exact California table inventory requires retained bundle provenance"
        )
    bundle_receipt_payload = (
        dict(bundle_receipt) if isinstance(bundle_receipt, Mapping) else {}
    )
    source_bundle = {
        key: retained_bundle[key]
        for key in (
            "byte_size",
            "content_sha256",
            "media_type",
            "official_url",
            "retrieved_at",
        )
        if retained_bundle.get(key) not in (None, "")
    }
    statutes_by_code: Dict[str, List[NormalizedStatute]] = {
        code: [] for code in wanted_codes
    }
    path = Path(zip_path)
    if not path.is_file():
        raise FileNotFoundError(f"California bulk zip missing: {path}")
    if not looks_like_zip(path):
        raise CaliforniaBulkFrontierError(
            "California bulk ZIP is not a readable ZIP archive"
        )

    with zipfile.ZipFile(path) as archive:
        archive_names = archive.namelist()
        names = set(archive_names)
        table_name = next(
            (
                name
                for name in archive_names
                if name.upper().endswith("LAW_SECTION_TBL.DAT")
            ),
            None,
        )
        if table_name is None:
            raise CaliforniaBulkFrontierError(
                "California bulk ZIP lacks LAW_SECTION_TBL.dat"
            )
        del archive_names

        # Read the table exactly once, group its lightweight LOB references,
        # and retain exact raw-row hashes for boundary probes. The old
        # one-code API performed this pass 30 times during a full crawl.
        table_bytes = archive.read(table_name)
        table_member = _member_provenance(archive, table_name, table_bytes)
        table_lines = table_bytes.splitlines()
        del table_bytes
        references_by_code: Dict[
            str, List[Tuple[int, str, Dict[str, Optional[str]]]]
        ] = {
            code: [] for code in wanted_codes
        }
        full_code_frontier = set(wanted_codes) == set(CA_CODES)
        table_row_count = 0
        blank_line_count = 0
        first_table_row_sha256 = ""
        last_table_row_sha256 = ""
        source_record_ids: List[str] = []
        admitted_source_record_ids: List[str] = []
        seen_source_record_ids: Set[str] = set()
        unusable_rows: List[Dict[str, Any]] = []
        duplicate_source_record_count = 0
        code_family_counts: Dict[str, Dict[str, int]] = {
            code: {
                "admitted": 0,
                "excluded": 0,
                "failed_final": 0,
                "observed": 0,
                "quarantined": 0,
            }
            for code in wanted_codes
        }

        def _counts_for(code: str) -> Dict[str, int]:
            key = str(code or "").strip().upper() or "__MALFORMED__"
            return code_family_counts.setdefault(
                key,
                {
                    "admitted": 0,
                    "excluded": 0,
                    "failed_final": 0,
                    "observed": 0,
                    "quarantined": 0,
                },
            )

        def _unusable(
            *,
            table_row_number: int,
            table_row_sha256: str,
            source_record_id: str,
            code: str,
            reason: str,
            disposition: str = "failed_final",
            body_member_path: str = "",
        ) -> None:
            if disposition not in {"excluded", "failed_final", "quarantined"}:
                raise ValueError("invalid California inventory disposition")
            _counts_for(code)[disposition] += 1
            unusable_rows.append(
                {
                    "body_member_path": body_member_path or None,
                    "code_family": code or None,
                    "disposition": disposition,
                    "reason": reason,
                    "source_record_id": source_record_id or None,
                    "table_row_number": int(table_row_number),
                    "table_row_sha256": table_row_sha256,
                }
            )

        for physical_line_number, raw_line in enumerate(table_lines, start=1):
            if not raw_line.strip():
                blank_line_count += 1
                continue
            table_row_count += 1
            raw_row_sha256 = hashlib.sha256(raw_line).hexdigest()
            if not first_table_row_sha256:
                first_table_row_sha256 = raw_row_sha256
            last_table_row_sha256 = raw_row_sha256
            row = raw_line.decode("utf-8", errors="replace").split("\t")
            partial_source_id = unquote_field(row[0]) if row else None
            partial_code = (
                (unquote_field(row[1]) or "").upper() if len(row) > 1 else ""
            )
            if partial_source_id:
                source_record_ids.append(partial_source_id)
            _counts_for(partial_code)["observed"] += 1
            if len(row) < len(LAW_SECTION_COLUMNS):
                _unusable(
                    table_row_number=physical_line_number,
                    table_row_sha256=raw_row_sha256,
                    source_record_id=partial_source_id or "",
                    code=partial_code,
                    reason="malformed_table_row",
                )
                continue
            source_metadata = {
                column_name: unquote_field(row[column_index])
                for column_index, column_name in enumerate(LAW_SECTION_COLUMNS)
            }
            source_record_id = source_metadata["id"] or ""
            code = (source_metadata["law_code"] or "").upper()
            printed_section = source_metadata["section_num"] or ""
            section = printed_section.rstrip(".")
            lob = source_metadata["content_xml"] or ""
            if not source_record_id:
                _unusable(
                    table_row_number=physical_line_number,
                    table_row_sha256=raw_row_sha256,
                    source_record_id="",
                    code=code,
                    reason="missing_source_record_id",
                    body_member_path=lob,
                )
                continue
            if source_record_id in seen_source_record_ids:
                duplicate_source_record_count += 1
                _unusable(
                    table_row_number=physical_line_number,
                    table_row_sha256=raw_row_sha256,
                    source_record_id=source_record_id,
                    code=code,
                    reason="duplicate_source_record_id",
                    body_member_path=lob,
                )
                continue
            seen_source_record_ids.add(source_record_id)
            if code not in seen_codes:
                _unusable(
                    table_row_number=physical_line_number,
                    table_row_sha256=raw_row_sha256,
                    source_record_id=source_record_id,
                    code=code,
                    reason=(
                        "unexpected_code_family"
                        if full_code_frontier
                        else "out_of_scope_code_family"
                    ),
                    disposition=("failed_final" if full_code_frontier else "excluded"),
                    body_member_path=lob,
                )
                continue
            if not section:
                _unusable(
                    table_row_number=physical_line_number,
                    table_row_sha256=raw_row_sha256,
                    source_record_id=source_record_id,
                    code=code,
                    reason="missing_printed_section",
                    body_member_path=lob,
                )
                continue
            if not lob:
                _unusable(
                    table_row_number=physical_line_number,
                    table_row_sha256=raw_row_sha256,
                    source_record_id=source_record_id,
                    code=code,
                    reason="missing_body_member_locator",
                )
                continue
            if lob not in names:
                _unusable(
                    table_row_number=physical_line_number,
                    table_row_sha256=raw_row_sha256,
                    source_record_id=source_record_id,
                    code=code,
                    reason="missing_body_member",
                    body_member_path=lob,
                )
                continue
            references_by_code[code].append(
                (physical_line_number, raw_row_sha256, source_metadata)
            )
        del table_lines

        for code in wanted_codes:
            statutes = statutes_by_code[code]
            code_name = normalized_names.get(code) or "California Code"
            for (
                table_row_number,
                raw_row_sha256,
                source_metadata,
            ) in references_by_code[code]:
                emit_row = not inventory_only and (
                    limit is None or len(statutes) < limit
                )
                if not exhaustive_inventory and not emit_row:
                    break
                source_record_id = source_metadata["id"] or ""
                printed_section = source_metadata["section_num"] or ""
                article = source_metadata["article"] or ""
                lob = source_metadata["content_xml"] or ""
                try:
                    caml_bytes = archive.read(lob)
                except Exception:
                    _unusable(
                        table_row_number=table_row_number,
                        table_row_sha256=raw_row_sha256,
                        source_record_id=source_record_id,
                        code=code,
                        reason="unreadable_body_member",
                        body_member_path=lob,
                    )
                    continue
                body_member = _member_provenance(archive, lob, caml_bytes)
                caml = caml_bytes.decode("utf-8", errors="replace")
                del caml_bytes
                text, unknown_tags = caml_to_text(caml)
                # California includes concise but complete provisions (for
                # example HSC 4746: "It may issue bonds.").  Length is not a
                # completeness signal; only a body with no normalized text is
                # unusable at this layer.  Placeholder screening remains the
                # shared normalization/admission layer's responsibility.
                if not text.strip():
                    _unusable(
                        table_row_number=table_row_number,
                        table_row_sha256=raw_row_sha256,
                        source_record_id=source_record_id,
                        code=code,
                        reason="empty_body",
                        body_member_path=lob,
                    )
                    continue
                admitted_source_record_ids.append(source_record_id)
                _counts_for(code)["admitted"] += 1
                if not emit_row:
                    continue
                section = printed_section.rstrip(".")
                if code == "CONS" and article:
                    printed_token = _CONS_SECTION_PREFIX.sub("", section).strip()
                    section_token = printed_token or section
                    section_number = f"{article} § {section_token}"
                    section_name = f"Article {article}, Section {section_token}"
                    official_cite = f"Cal. Const. art. {article}, § {section_token}"
                    source_url = OFFICIAL_CONSTITUTION_URL.format(
                        article=quote(article, safe=""),
                    )
                else:
                    section_number = section
                    section_name = f"Section {section}"
                    official_cite = f"Cal. {code} § {section}"
                    source_url = OFFICIAL_SECTION_URL.format(
                        code=code,
                        section=f"{section}.",
                    )
                # The official section label is not a unique identity: the
                # table deliberately carries concurrent conditional,
                # future-effective, repealed, and superseded records sharing
                # one printed cite.  Column 0 is the official stable key.
                statute_id = f"CA:{source_record_id}"
                structured_data: Dict[str, Any] = {
                    "source_kind": "official_california_bulk_caml",
                    "source_authority_class": "official",
                    "discovery_method": "leginfo_pubinfo_zip",
                    "bulk_host": OFFICIAL_DOWNLOADS_HOST,
                    "law_code": code,
                    "source_record_id": source_record_id,
                    "printed_section": printed_section,
                    "printed_cite": f"{code} {printed_section}",
                    "constitution_article": (
                        article if code == "CONS" and article else None
                    ),
                    "law_section_table": source_metadata,
                    "source_table_row_number": table_row_number,
                    "source_table_member": dict(table_member),
                    "source_body_member": body_member,
                    "unknown_caml_tags": sorted(unknown_tags),
                    "skip_hydrate": True,
                }
                if retained_bundle:
                    structured_data.update(
                        {
                            "content_sha256": bundle_digest,
                            "source_bundle": dict(source_bundle),
                            "transport_receipt": dict(bundle_receipt_payload),
                        }
                    )
                statutes.append(
                    NormalizedStatute(
                        state_code="CA",
                        state_name="California",
                        statute_id=statute_id,
                        code_name=code_name,
                        section_number=section_number,
                        section_name=section_name,
                        full_text=text,
                        source_url=source_url,
                        official_cite=official_cite,
                        structured_data=structured_data,
                    )
                )
            references_by_code[code] = []

        if exhaustive_inventory:
            unusable_rows.sort(
                key=lambda item: (
                    int(item["table_row_number"]),
                    str(item.get("reason") or ""),
                )
            )
            disposition_counts = {
                "discovered": int(table_row_count),
                "duplicates": int(duplicate_source_record_count),
                "excluded": sum(
                    row["disposition"] == "excluded" for row in unusable_rows
                ),
                "failed_final": sum(
                    row["disposition"] == "failed_final" for row in unusable_rows
                ),
                "fetched": len(admitted_source_record_ids),
                "quarantined": sum(
                    row["disposition"] == "quarantined" for row in unusable_rows
                ),
            }
            accounted = sum(
                int(disposition_counts[key])
                for key in ("excluded", "failed_final", "fetched", "quarantined")
            )
            blocking_count = int(disposition_counts["failed_final"]) + int(
                disposition_counts["quarantined"]
            )
            source_ids_material = {
                "jurisdiction": "CA",
                "source_record_ids": source_record_ids,
            }
            admitted_ids_material = {
                "admitted_source_record_ids": admitted_source_record_ids,
                "jurisdiction": "CA",
            }
            frontier_closed = bool(
                full_code_frontier
                and blocking_count == 0
                and accounted == table_row_count
                and len(admitted_source_record_ids) == len(source_record_ids)
                and len(source_record_ids) == len(set(source_record_ids))
            )
            inventory: Dict[str, Any] = {
                "boundary_probes": {
                    "first_admitted_source_record_id": (
                        admitted_source_record_ids[0]
                        if admitted_source_record_ids
                        else None
                    ),
                    "first_source_record_id": (
                        source_record_ids[0] if source_record_ids else None
                    ),
                    "first_table_row_sha256": first_table_row_sha256 or None,
                    "last_admitted_source_record_id": (
                        admitted_source_record_ids[-1]
                        if admitted_source_record_ids
                        else None
                    ),
                    "last_source_record_id": (
                        source_record_ids[-1] if source_record_ids else None
                    ),
                    "last_table_row_sha256": last_table_row_sha256 or None,
                },
                "bundle": dict(source_bundle),
                "code_family_counts": {
                    key: dict(code_family_counts[key])
                    for key in sorted(code_family_counts)
                },
                "disposition": disposition_counts,
                "frontier": {
                    "bundle_closed": True,
                    "closed": frontier_closed,
                    "enumerator_closed": True,
                    "expected_index_units": int(table_row_count),
                    "scope_closed": bool(full_code_frontier),
                    "unvisited_continuation_links": [],
                    "visited_index_units": int(table_row_count),
                },
                "jurisdiction": "CA",
                "schema_version": CALIFORNIA_BULK_INVENTORY_SCHEMA,
                "scope_code_families": list(wanted_codes),
                "source_record_count": len(source_record_ids),
                "source_record_ids": list(source_record_ids),
                "source_record_ids_sha256": _canonical_json_sha256(
                    source_ids_material
                ),
                "admitted_source_record_count": len(admitted_source_record_ids),
                "admitted_source_record_ids_sha256": _canonical_json_sha256(
                    admitted_ids_material
                ),
                "table_blank_line_count": int(blank_line_count),
                "table_member": dict(table_member),
                "table_row_count": int(table_row_count),
                "unique_source_record_count": len(set(source_record_ids)),
                "unusable_row_count": len(unusable_rows),
                "unusable_rows": unusable_rows,
            }
            inventory["inventory_sha256"] = _canonical_json_sha256(inventory)
            if inventory_observer is not None:
                inventory_observer(inventory)
            if fail_on_unusable and not frontier_closed:
                raise CaliforniaBulkFrontierError(
                    "California LAW_SECTION_TBL frontier has unresolved records: "
                    f"blocking={blocking_count} unusable={len(unusable_rows)} "
                    f"accounted={accounted}/{table_row_count}",
                    inventory=inventory,
                )

    return statutes_by_code


def inventory_california_bulk_zip(
    zip_path: Path,
    *,
    bundle_provenance: Mapping[str, Any],
) -> Dict[str, Any]:
    """Independently reopen and inventory the complete official source table."""

    captured: List[Dict[str, Any]] = []

    def _capture(inventory: Mapping[str, Any]) -> None:
        captured.append(dict(inventory))

    parse_california_bulk_zip_codes(
        zip_path,
        code_types=CA_CODES,
        max_statutes=0,
        code_names={},
        bundle_provenance=bundle_provenance,
        inventory_observer=_capture,
        inventory_only=True,
        fail_on_unusable=False,
    )
    if len(captured) != 1:
        raise CaliforniaBulkFrontierError(
            "California bulk inventory did not produce exactly one observation"
        )
    return captured[0]


def parse_california_bulk_zip(
    zip_path: Path,
    *,
    code_type: str,
    max_statutes: Optional[int] = None,
    code_name: str = "California Code",
    bundle_provenance: Optional[Mapping[str, Any]] = None,
) -> List[NormalizedStatute]:
    """Parse one code family via the shared multi-code implementation."""

    wanted = str(code_type or "").strip().upper()
    if not wanted:
        return []
    parse_kwargs: Dict[str, Any] = {
        "code_types": (wanted,),
        "max_statutes": max_statutes,
        "code_names": {wanted: code_name},
    }
    if bundle_provenance is not None:
        parse_kwargs["bundle_provenance"] = bundle_provenance
    return parse_california_bulk_zip_codes(
        zip_path,
        **parse_kwargs,
    ).get(wanted, [])


def configured_bulk_zip_path() -> Optional[Path]:
    raw = current_state_law_run_environment_value("CALIFORNIA_BULK_ZIP").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


LEGINFO = "https://leginfo.legislature.ca.gov"
CA_CODES = (
    "BPC", "CIV", "CCP", "COM", "CORP", "EDC", "ELEC", "EVID", "FAM", "FIN",
    "FGC", "FAC", "GOV", "HNC", "HSC", "INS", "LAB", "MVC", "PEN", "PROB",
    "PCC", "PRC", "PUC", "RTC", "SHC", "UIC", "VEH", "WAT", "WIC",
    "CONS",
)
_TOC_CODE_RE = re.compile(r"tocCode=([A-Z]+)", re.IGNORECASE)


def expand_url(code: str) -> str:
    token = str(code or "").strip().upper()
    return f"{LEGINFO}/faces/codedisplayexpand.xhtml?tocCode={token}"


def display_section_url(code: str, section: str) -> str:
    return OFFICIAL_SECTION_URL.format(code=str(code or "").upper(), section=section)


def toc_code_links(html: str, *, base_url: str = LEGINFO) -> List[Tuple[str, str]]:
    """``tocCode=PEN`` rows from ``codes.xhtml`` / expand pages."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        match = _TOC_CODE_RE.search(href)
        if not match:
            continue
        code = match.group(1).upper()
        if code not in CA_CODES or code in seen:
            continue
        seen.add(code)
        out.append((code, urljoin(base_url.rstrip("/") + "/", href)))
    return out


def manylaw_section_numbers(html: str) -> List[str]:
    """Section numbers from ``#manylawsections`` displayText pages."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    container = soup.find(id="manylawsections") or soup
    out: List[str] = []
    seen: set[str] = set()
    for anchor in container.find_all("a"):
        number = _WS.sub(" ", (anchor.get_text(" ") or "").replace("\xa0", " ")).strip().rstrip(".")
        if not number or number.lower() in seen:
            continue
        if not re.match(r"^[0-9][0-9A-Za-z.\-]*$", number):
            continue
        seen.add(number.lower())
        out.append(number)
    return out
