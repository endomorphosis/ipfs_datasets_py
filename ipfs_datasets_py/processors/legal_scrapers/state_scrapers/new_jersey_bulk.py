"""Official New Jersey Permanent Statutes RTF zip parser.

Adapted from Vaquill-AI/open-us-law ``nj_bulk.parse`` / ``ingest_nj_bulk.py``
(Apache-2.0). The daily dump is:

    https://pub.njleg.state.nj.us/Statutes/STATUTES-TEXT.zip  -> STATUTES.RTF

Does not download the archive by default. Operators point ``NEW_JERSEY_BULK_ZIP``
at a local copy.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

from .base_scraper import (
    NormalizedStatute,
    StatuteMetadata,
    current_state_law_run_environment_value,
)

OFFICIAL_ZIP_URL = "https://pub.njleg.state.nj.us/Statutes/STATUTES-TEXT.zip"
RTF_MEMBER = "STATUTES.RTF"
_ZIP_MAGIC = b"PK\x03\x04"
NEW_JERSEY_BULK_INVENTORY_SCHEMA = "new-jersey-statutes-rtf-zip-inventory-v2"


class NewJerseyBulkFrontierError(RuntimeError):
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


def looks_like_zip(path: Path) -> bool:
    try:
        with Path(path).open("rb") as handle:
            magic = handle.read(4)
    except OSError:
        return False
    return magic == _ZIP_MAGIC


def looks_like_zip_bytes(payload: bytes) -> bool:
    """Validate the exact official RTF member before parser admission."""

    body = bytes(payload or b"")
    if len(body) < 22 or not body.startswith(_ZIP_MAGIC):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                return False
            members = [
                name
                for name in names
                if name.rsplit("/", 1)[-1].upper() == RTF_MEMBER
            ]
            if len(members) != 1:
                return False
            info = archive.getinfo(members[0])
            if info.is_dir() or info.file_size <= 0:
                return False
            with archive.open(members[0]) as member_handle:
                prefix = member_handle.read(64).lstrip()
            return prefix.startswith(b"{\\rtf")
    except (OSError, RuntimeError, zipfile.BadZipFile, KeyError):
        return False
SECTION_VIEW = "https://www.njleg.state.nj.us/legislative-activity/statutes"

_CTRL_RE = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?")
_CITATION_TOKEN_RE = re.compile(
    r"^\s*(?P<prefix>C\.)?"
    r"(?P<title>App\.A|\d+[A-Za-z]?):"
    r"(?P<section>[^\s]+)(?:\s+(?P<catchline>.*))?$",
    re.IGNORECASE,
)
_VALID_SECTION_TOKEN_RE = re.compile(
    r"^[0-9][0-9A-Za-z.:\-]*(?:\([0-9A-Za-z]+\))?$"
)
_KNOWN_MISSING_HYPHEN_RE = re.compile(
    r"^\s*52:9H\s+(?P<suffix>3[4-7])\s+(?P<catchline>.+)$",
    re.IGNORECASE,
)
_KNOWN_COLON_TYPO_RE = re.compile(
    r"^\s*9-3A-7\s+(?P<catchline>.+)$",
    re.IGNORECASE,
)
_MISSTYLED_BODY_HEADER_RE = re.compile(
    r"^(?P<body>.+?\bL\.\d{4}[^\n]*?\.)\s+"
    r"(?P<header>(?:C\.)?(?:App\.A|\d+[A-Za-z]?):[^\s]+\s+.+)$",
    re.IGNORECASE | re.DOTALL,
)
_REALLOCATION_NOTICE_RE = re.compile(
    r"(?:\b(?:has\s+been\s+)?reallocated\s+(?:to|as)\b|"
    r"\brelocated\s+to\b)",
    re.IGNORECASE,
)
_BLANK_PLACEHOLDER_BODY_RE = re.compile(
    r"^(?:L\.|P\.L\.)\d{4},\s*c\.?\s*\d+,\s*s\.?\s*\d+\.?$",
    re.IGNORECASE,
)
_SAVED_LAW_QUALIFIER_RE = re.compile(
    r"^(?:(?:\d{4},\s*c\.\s*\d+)|(?:R\.S\.\s*\d+[:\-]\S+))",
    re.IGNORECASE,
)

# These five rows in the retained 2026-08-25 official RTF have a divergent
# printed citation that collides with another substantive row.  Each repair is
# bound to the SHA-256 of the complete extracted header plus body, not merely a
# citation string.  The intended identity is independently proved by the
# immediately surrounding official sequence (.2/.4, .4/.6, .52/.54,
# Title-49 3-88/4-1, and .20/.22 respectively).  Any upstream byte/text change
# falls out of this table and therefore fails closed as an unknown divergence.
_KNOWN_DIVERGENT_VARIANT_IDENTITIES: Mapping[str, Tuple[str, str]] = {
    "75c81cd0aaa485ae26fae8362ad0223e6204f9a969977006764d26b5cf50b458": (
        "18A",
        "33-27.3",
    ),
    "e823e9748b1d570c21c290fb2b5deb856a70d06de4552c6c3d1c7f2804c3995b": (
        "34",
        "15C-10.5",
    ),
    "68453e2399f79528519f5695b5951d60cf3ba306675319156d53a0cdda67020a": (
        "45",
        "15-16.53",
    ),
    "fd6a6105b2ede236da718831b5396b8905b3d45e8d3c974dc3a92ca9fe0c955a": (
        "49",
        "3-89",
    ),
    "3fcee12eee5f6bae62b1fe1ea4e85577fbd19a420b9a9ff0a56277dd4ee5b118": (
        "52",
        "17B-194.21",
    ),
}


@dataclass(frozen=True)
class NjSection:
    title: str
    section: str
    catchline: str
    body: str

    @property
    def chapter(self) -> str:
        return self.section.split("-", 1)[0]

    def citation(self) -> str:
        return f"N.J. Stat. § {self.title}:{self.section}"


@dataclass(frozen=True)
class NjSourceRecord:
    """One style-3 record observed in the official RTF member."""

    ordinal: int
    header: str
    title: str
    section: str
    catchline: str
    body: str
    header_normalization: str = ""

    @property
    def source_record_id(self) -> str:
        if not self.title or not self.section:
            return ""
        return f"{self.title}:{self.section}"

    @property
    def observation_sha256(self) -> str:
        return hashlib.sha256(
            f"{self.header}\n{self.body}".encode("utf-8")
        ).hexdigest()

    @property
    def source_observation_id(self) -> str:
        return f"rtf-style3:{self.ordinal}:{self.observation_sha256}"


@dataclass(frozen=True)
class _ResolvedNjSourceRecord:
    """A statute-bearing RTF record after source-bound identity resolution."""

    record: NjSourceRecord
    source_record_id: str
    title: str
    section: str
    record_kind: str
    identity_reason: str
    base_source_record_id: str


def _rtf_to_text(chunk: str) -> str:
    """Extract plain text from one ``\\pard``-delimited RTF chunk."""

    out: List[str] = []
    index = 0
    n = len(chunk)
    skip_depth = 0
    depth = 0
    while index < n:
        ch = chunk[index]
        if ch == "\\":
            match = _CTRL_RE.match(chunk, index)
            if match:
                word = match.group(1)
                index = match.end()
                if skip_depth:
                    continue
                if word in ("par", "line", "tab", "cell", "row"):
                    out.append(" ")
                elif word == "u":
                    try:
                        cp = int(match.group(2))
                        if cp < 0:
                            cp += 65536
                        out.append(chr(cp))
                    except (TypeError, ValueError):
                        pass
                    if index < n and chunk[index] not in "\\{}":
                        index += 1
                continue
            if chunk[index : index + 2] == "\\'":
                hexs = chunk[index + 2 : index + 4]
                index += 4
                if not skip_depth:
                    try:
                        out.append(bytes([int(hexs, 16)]).decode("cp1252", "replace"))
                    except ValueError:
                        pass
                continue
            nxt = chunk[index + 1] if index + 1 < n else ""
            index += 2
            if not skip_depth and nxt in "{}\\":
                out.append(nxt)
            continue
        if ch == "{":
            depth += 1
            if chunk[index + 1 : index + 3] == "\\*":
                skip_depth = depth
            index += 1
            continue
        if ch == "}":
            if skip_depth and depth == skip_depth:
                skip_depth = 0
            depth -= 1
            index += 1
            continue
        if ch in "\r\n":
            index += 1
            continue
        if not skip_depth:
            out.append(ch)
        index += 1
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def _style_of(chunk: str) -> int:
    match = re.match(r"\s*(?:\\plain)?\s*\\s(\d+)\b", chunk)
    return int(match.group(1)) if match else 0


def _parse_section_header(text: str) -> Optional[Tuple[str, str, str, str]]:
    """Parse only citation shapes proved by the official RTF.

    The narrow special cases correspond to source-authored punctuation errors
    that are surrounded by an unambiguous official sequence.  Arbitrary
    missing colons or spaces are deliberately not guessed.
    """

    spaced = _KNOWN_MISSING_HYPHEN_RE.match(text)
    if spaced:
        return (
            "52",
            f"9H-{spaced.group('suffix')}",
            spaced.group("catchline").strip(),
            "official_header_missing_hyphen",
        )
    colon_typo = _KNOWN_COLON_TYPO_RE.match(text)
    if colon_typo:
        return (
            "9",
            "3A-7",
            colon_typo.group("catchline").strip(),
            "official_header_colon_typo",
        )

    match = _CITATION_TOKEN_RE.match(text)
    if not match:
        return None
    section = str(match.group("section") or "").rstrip(".,")
    if not section or _VALID_SECTION_TOKEN_RE.fullmatch(section) is None:
        return None
    raw_title = str(match.group("title") or "")
    title = "App.A" if raw_title.lower() == "app.a" else raw_title
    normalization = ""
    if match.group("prefix"):
        normalization = "leading_c_citation_marker"
    elif title == "App.A":
        normalization = "appendix_a_title"
    return (
        title,
        section,
        str(match.group("catchline") or "").strip(),
        normalization,
    )


def _split_misstyled_body_and_header(
    text: str,
) -> Optional[Tuple[str, str, Tuple[str, str, str, str]]]:
    """Recover the two exact RTF chunks whose body retained style 3.

    A split is accepted only when a complete legislative-history sentence
    precedes a final, independently parseable citation header.  A style-3 body
    that merely mentions another citation remains unresolved.
    """

    match = _MISSTYLED_BODY_HEADER_RE.match(text)
    if not match:
        return None
    candidate = str(match.group("header") or "").strip()
    parsed = _parse_section_header(candidate)
    if parsed is None:
        return None
    return str(match.group("body") or "").strip(), candidate, parsed


def iter_source_records(rtf: str) -> Iterator[NjSourceRecord]:
    """Yield every style-3 record, including malformed and empty records.

    Exact frontier accounting must observe records that the row parser cannot
    admit.  The older ``iter_sections`` interface is retained below as the
    compatibility projection over records with a parseable citation.
    """

    chunks = rtf.split("\\pard")
    header: Optional[str] = None
    header_ordinal = 0
    sec_title = sec_num = catchline = None
    header_normalization = ""
    body: List[str] = []
    ordinal = 0

    def _flush() -> Optional[NjSourceRecord]:
        if header is None:
            return None
        return NjSourceRecord(
            ordinal=header_ordinal,
            header=header,
            title=sec_title or "",
            section=sec_num or "",
            catchline=catchline or "",
            body="\n".join(body).strip(),
            header_normalization=header_normalization,
        )

    for chunk in chunks:
        style = _style_of(chunk)
        if style == 1:
            continue
        if style == 2:
            flushed = _flush()
            if flushed:
                yield flushed
            header = None
            sec_title = sec_num = catchline = None
            header_normalization = ""
            body = []
            continue
        if style == 3:
            text = _rtf_to_text(chunk)
            ordinal += 1
            # One empty style-3 formatting paragraph precedes the real body of
            # 45:8B-92.  It is not a semantic source record and must neither
            # flush nor steal that body's ownership.
            if not text:
                continue
            parsed = _parse_section_header(text)
            if parsed is None:
                split = _split_misstyled_body_and_header(text)
                if split is not None:
                    prior_body, text, parsed = split
                    if header is not None and prior_body:
                        body.append(prior_body)
            flushed = _flush()
            if flushed:
                yield flushed
            body = []
            header = text
            header_ordinal = ordinal
            if parsed is not None:
                sec_title, sec_num, catchline, header_normalization = parsed
            else:
                sec_title = sec_num = catchline = None
                header_normalization = ""
            continue
        if header is not None:
            text = _rtf_to_text(chunk)
            if text:
                body.append(text)
    flushed = _flush()
    if flushed:
        yield flushed


def iter_sections(rtf: str) -> Iterator[NjSection]:
    """Yield citation-bearing sections from the official RTF member."""

    for record in iter_source_records(rtf):
        if not record.source_record_id:
            continue
        yield NjSection(
            record.title,
            record.section,
            record.catchline,
            record.body,
        )


_INACTIVE_TEXT_RE = re.compile(
    r"^(?P<status>repealed|reserved|expired|transferred|omitted|deleted)"
    r"(?:\s+by\b.*)?[ .;,:()\[\]-]*$",
    re.IGNORECASE,
)


def _inactive_disposition(record: NjSourceRecord) -> str:
    """Classify only explicit whole-field terminal markers.

    This deliberately does not keyword-search substantive law text: active
    provisions commonly discuss laws being repealed or property transferred.
    """

    # A substantive provision may itself have the catchline "Repealed" while
    # its body performs the repeal (54:4-2.52 in the retained official RTF).
    # In that case the law text is still a statute row.  Catchline-only status
    # is terminal only when no body was published; a body may independently be
    # a whole-field terminal marker such as "Repealed by L....".
    values = (record.body,) if record.body.strip() else (record.catchline,)
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip()
        match = _INACTIVE_TEXT_RE.fullmatch(normalized)
        if match:
            status = match.group("status").lower()
            return "repealed" if status in {"repealed", "expired", "deleted"} else "reserved"
    return ""


def _saved_law_variant_qualifier(record: NjSourceRecord) -> str:
    """Return the printed qualifier for Title-18A saved-law source text."""

    if record.title != "18A" or not _SAVED_LAW_QUALIFIER_RE.match(record.catchline):
        return ""
    qualifier = re.split(
        r"\s*\(C\.",
        record.catchline,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return re.sub(r"[^0-9A-Za-z]+", "-", qualifier).strip("-").lower()


def _resolve_source_record(record: NjSourceRecord) -> _ResolvedNjSourceRecord:
    """Resolve only exact, source-proved statute identities.

    Saved-law text is a second substantive source record rather than a copy of
    the modern section summary, so its printed act qualifier is part of the
    identity.  The five source typos below require an exact record fingerprint.
    Unknown divergent variants retain their colliding base identity and are
    rejected later by the inventory scanner.
    """

    base_source_record_id = record.source_record_id
    correction = _KNOWN_DIVERGENT_VARIANT_IDENTITIES.get(
        record.observation_sha256
    )
    if correction is not None:
        title, section = correction
        return _ResolvedNjSourceRecord(
            record=record,
            source_record_id=f"{title}:{section}",
            title=title,
            section=section,
            record_kind="statute",
            identity_reason="source_bound_divergent_header_correction",
            base_source_record_id=base_source_record_id,
        )

    qualifier = _saved_law_variant_qualifier(record)
    if qualifier:
        return _ResolvedNjSourceRecord(
            record=record,
            source_record_id=(
                f"{base_source_record_id}~saved-law~{qualifier}"
            ),
            title=record.title,
            section=record.section,
            record_kind="saved_law_variant",
            identity_reason="printed_saved_law_qualifier",
            base_source_record_id=base_source_record_id,
        )

    return _ResolvedNjSourceRecord(
        record=record,
        source_record_id=base_source_record_id,
        title=record.title,
        section=record.section,
        record_kind=(
            "appendix_a_statute" if record.title == "App.A" else "statute"
        ),
        identity_reason=record.header_normalization,
        base_source_record_id=base_source_record_id,
    )


def _terminal_record_disposition(record: NjSourceRecord) -> str:
    """Classify only bodyless source notices or exact terminal markers."""

    if not record.body.strip() and _REALLOCATION_NOTICE_RE.search(record.header):
        return "reallocation_notice"
    if (
        record.catchline.strip(" .").lower() == "blank"
        and _BLANK_PLACEHOLDER_BODY_RE.fullmatch(
            re.sub(r"\s+", " ", record.body).strip()
        )
    ):
        return "blank_placeholder"
    inactive = _inactive_disposition(record)
    if inactive:
        return f"terminal_{inactive}_notice"
    return ""


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


def _scan_new_jersey_bulk_zip(
    source: Path | bytes,
    *,
    code_name: str,
    max_statutes: Optional[int],
    bundle_provenance: Optional[Mapping[str, Any]],
    emit_rows: bool,
) -> Tuple[List[NormalizedStatute], Dict[str, Any]]:
    if isinstance(source, bytes):
        payload = bytes(source)
        if not looks_like_zip_bytes(payload):
            raise NewJerseyBulkFrontierError(
                "New Jersey bulk ZIP lacks its exact STATUTES.RTF member"
            )
        archive_source: Any = io.BytesIO(payload)
    else:
        path = Path(source)
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"New Jersey bulk zip missing: {path}")
        if not looks_like_zip(path):
            raise NewJerseyBulkFrontierError(
                "New Jersey bulk ZIP has invalid ZIP magic"
            )
        archive_source = path

    limit = None if max_statutes is None else max(0, int(max_statutes))
    statutes: List[NormalizedStatute] = []
    source_observation_ids: List[str] = []
    source_record_ids: List[str] = []
    admitted_source_record_ids: List[str] = []
    excluded_source_record_ids: List[str] = []
    unusable_rows: List[Dict[str, Any]] = []
    identity_resolution_rows: List[Dict[str, Any]] = []
    excluded_reason_counts: Dict[str, int] = {}
    admitted_record_kind_counts: Dict[str, int] = {}
    duplicate_count = 0
    exact_duplicate_count = 0
    divergent_variant_count = 0
    discovered_count = 0
    capped = False

    with zipfile.ZipFile(archive_source) as archive:
        all_names = list(archive.namelist())
        if len(all_names) != len(set(all_names)):
            raise NewJerseyBulkFrontierError(
                "New Jersey bulk ZIP contains duplicate member paths"
            )
        rtf_members = [
            name
            for name in all_names
            if name.rsplit("/", 1)[-1].upper() == RTF_MEMBER
        ]
        if len(rtf_members) != 1:
            raise NewJerseyBulkFrontierError(
                "New Jersey bulk ZIP must contain exactly one STATUTES.RTF member"
            )
        member = rtf_members[0]
        raw_member = archive.read(member)
        if not raw_member.lstrip().startswith(b"{\\rtf"):
            raise NewJerseyBulkFrontierError(
                "New Jersey STATUTES.RTF member has invalid RTF magic"
            )
        member_projection = {
            "byte_size": len(raw_member),
            "content_sha256": hashlib.sha256(raw_member).hexdigest(),
            "path": member,
        }
        rtf = raw_member.decode("cp1252", errors="strict")

        seen_source_ids: Dict[str, str] = {}
        for record in iter_source_records(rtf):
            if limit is not None and len(admitted_source_record_ids) >= limit:
                capped = True
                break
            discovered_count += 1
            source_observation_ids.append(record.source_observation_id)

            terminal = _terminal_record_disposition(record)
            if terminal:
                terminal_id = (
                    record.source_record_id
                    or f"rtf-terminal:{record.observation_sha256}"
                )
                excluded_source_record_ids.append(terminal_id)
                excluded_reason_counts[terminal] = (
                    int(excluded_reason_counts.get(terminal) or 0) + 1
                )
                identity_resolution_rows.append(
                    {
                        "disposition": "excluded",
                        "ordinal": record.ordinal,
                        "reason": terminal,
                        "source_observation_id": record.source_observation_id,
                        "source_record_id": terminal_id,
                    }
                )
                continue

            resolved = _resolve_source_record(record)
            source_record_id = resolved.source_record_id
            if not source_record_id:
                unusable_rows.append(
                    {
                        "disposition": "failed_final",
                        "body_sha256": hashlib.sha256(
                            record.body.encode("utf-8")
                        ).hexdigest(),
                        "header_sha256": hashlib.sha256(
                            record.header.encode("utf-8")
                        ).hexdigest(),
                        "ordinal": record.ordinal,
                        "reason": "malformed_section_header",
                        "source_observation_id": record.source_observation_id,
                        "source_record_id": "",
                    }
                )
                continue
            source_record_ids.append(source_record_id)
            prior_fingerprint = seen_source_ids.get(source_record_id)
            if prior_fingerprint is not None:
                duplicate_count += 1
                if prior_fingerprint == record.observation_sha256:
                    exact_duplicate_count += 1
                    excluded_source_record_ids.append(source_record_id)
                    excluded_reason_counts["exact_duplicate_source_record"] = (
                        int(
                            excluded_reason_counts.get(
                                "exact_duplicate_source_record"
                            )
                            or 0
                        )
                        + 1
                    )
                    identity_resolution_rows.append(
                        {
                            "disposition": "excluded",
                            "ordinal": record.ordinal,
                            "reason": "exact_duplicate_source_record",
                            "source_observation_id": record.source_observation_id,
                            "source_record_id": source_record_id,
                        }
                    )
                else:
                    divergent_variant_count += 1
                    unusable_rows.append(
                        {
                            "disposition": "failed_final",
                            "first_observation_sha256": prior_fingerprint,
                            "observation_sha256": record.observation_sha256,
                            "ordinal": record.ordinal,
                            "reason": "divergent_source_record_variant",
                            "source_observation_id": record.source_observation_id,
                            "source_record_id": source_record_id,
                        }
                    )
                continue
            seen_source_ids[source_record_id] = record.observation_sha256

            if len(record.body.strip()) < 5:
                unusable_rows.append(
                    {
                        "disposition": "failed_final",
                        "ordinal": record.ordinal,
                        "reason": "empty_or_short_body",
                        "source_observation_id": record.source_observation_id,
                        "source_record_id": source_record_id,
                    }
                )
                continue

            if resolved.identity_reason:
                identity_resolution_rows.append(
                    {
                        "base_source_record_id": resolved.base_source_record_id,
                        "disposition": "fetched",
                        "ordinal": record.ordinal,
                        "reason": resolved.identity_reason,
                        "source_observation_id": record.source_observation_id,
                        "source_record_id": source_record_id,
                    }
                )

            admitted_source_record_ids.append(source_record_id)
            admitted_record_kind_counts[resolved.record_kind] = (
                int(admitted_record_kind_counts.get(resolved.record_kind) or 0)
                + 1
            )
            if not emit_rows:
                continue
            section = NjSection(
                resolved.title,
                resolved.section,
                record.catchline,
                record.body,
            )
            source_bundle = _bundle_projection(bundle_provenance)
            structured_data: Dict[str, Any] = {
                "source_kind": "official_new_jersey_statutes_rtf",
                "source_authority_class": "official",
                "discovery_method": "njleg_statutes_text_zip",
                "bulk_host": "pub.njleg.state.nj.us",
                "source_member": dict(member_projection),
                "source_observation_id": record.source_observation_id,
                "source_record_kind": resolved.record_kind,
                "source_record_id": source_record_id,
                "skip_hydrate": True,
            }
            if resolved.base_source_record_id != source_record_id:
                structured_data["base_source_record_id"] = (
                    resolved.base_source_record_id
                )
            if resolved.identity_reason:
                structured_data["source_identity_reason"] = (
                    resolved.identity_reason
                )
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
                    state_code="NJ",
                    state_name="New Jersey",
                    statute_id=f"{code_name} § {source_record_id}",
                    code_name=code_name,
                    title_number=section.title,
                    chapter_number=section.chapter,
                    section_number=source_record_id,
                    section_name=(
                        section.catchline[:200]
                        if section.catchline
                        else f"Section {source_record_id}"
                    ),
                    full_text=section.body,
                    source_url=SECTION_VIEW,
                    official_cite=section.citation(),
                    metadata=StatuteMetadata(),
                    structured_data=structured_data,
                )
            )

    failed_final = sum(
        item.get("disposition") == "failed_final" for item in unusable_rows
    )
    disposition = {
        "discovered": discovered_count,
        "duplicates": duplicate_count,
        "excluded": len(excluded_source_record_ids),
        "failed_final": failed_final,
        "fetched": len(admitted_source_record_ids),
        "quarantined": 0,
    }
    algebra_closed = discovered_count == sum(
        int(disposition[key])
        for key in (
            "excluded",
            "failed_final",
            "fetched",
            "quarantined",
        )
    )
    bundle = _bundle_projection(bundle_provenance)
    bundle_bound = bool(
        int(bundle.get("byte_size") or 0) > 0
        and re.fullmatch(
            r"[a-f0-9]{64}",
            str(bundle.get("content_sha256") or "").strip().lower(),
        )
        and str(bundle.get("official_url") or "").strip() == OFFICIAL_ZIP_URL
    )
    inventory: Dict[str, Any] = {
        "schema_version": NEW_JERSEY_BULK_INVENTORY_SCHEMA,
        "jurisdiction": "NJ",
        "code_name": str(code_name),
        "bundle": bundle,
        "archive_member_count": len(all_names),
        "archive_member_paths": sorted(all_names),
        "archive_member_paths_sha256": _strings_sha256(sorted(all_names)),
        "rtf_member": member_projection,
        "source_observation_count": len(source_observation_ids),
        "source_observation_ids": source_observation_ids,
        "source_observation_ids_sha256": _strings_sha256(
            source_observation_ids
        ),
        "source_record_count": len(source_record_ids),
        "source_record_ids": source_record_ids,
        "source_record_ids_sha256": _strings_sha256(source_record_ids),
        "admitted_source_record_count": len(admitted_source_record_ids),
        "admitted_source_record_ids": admitted_source_record_ids,
        "admitted_source_record_ids_sha256": _strings_sha256(
            admitted_source_record_ids
        ),
        "admitted_canonical_keys": [
            f"urn:state:nj:statute:{code_name} § {source_record_id}"
            for source_record_id in admitted_source_record_ids
        ],
        "excluded_source_record_count": len(excluded_source_record_ids),
        "excluded_source_record_ids": excluded_source_record_ids,
        "excluded_source_record_ids_sha256": _strings_sha256(
            excluded_source_record_ids
        ),
        "admitted_record_kind_counts": dict(
            sorted(admitted_record_kind_counts.items())
        ),
        "excluded_reason_counts": dict(sorted(excluded_reason_counts.items())),
        "duplicate_classification": {
            "divergent_source_record_variants": divergent_variant_count,
            "exact_duplicate_source_records": exact_duplicate_count,
        },
        "identity_resolution_row_count": len(identity_resolution_rows),
        "identity_resolution_rows": identity_resolution_rows,
        "unusable_row_count": failed_final,
        "unusable_rows": unusable_rows,
        "disposition": disposition,
        "boundary_probes": {
            "first_source_record_id": source_record_ids[0]
            if source_record_ids
            else "",
            "last_source_record_id": source_record_ids[-1]
            if source_record_ids
            else "",
            "first_source_observation_id": source_observation_ids[0]
            if source_observation_ids
            else "",
            "last_source_observation_id": source_observation_ids[-1]
            if source_observation_ids
            else "",
            "rtf_member": member,
        },
        "frontier": {
            "algebra_closed": algebra_closed,
            "bundle_bound": bundle_bound,
            "bundle_closed": not capped,
            "capped": capped,
            "closed": bool(
                not capped
                and algebra_closed
                and bundle_bound
                and failed_final == 0
                and divergent_variant_count == 0
                and admitted_source_record_ids
            ),
            "enumerator_closed": not capped,
            "expected_index_units": 1,
            "remaining_bundle_members": [] if not capped else [member],
            "scope_closed": not capped,
            "unvisited_continuation_links": [],
            "visited_index_units": 1 if not capped else 0,
        },
    }
    inventory["inventory_sha256"] = _canonical_json_sha256(inventory)
    return statutes, inventory


def parse_new_jersey_bulk_zip_bytes(
    payload: bytes,
    *,
    code_name: str = "New Jersey Statutes",
    max_statutes: Optional[int] = None,
    bundle_provenance: Optional[Mapping[str, Any]] = None,
    inventory_observer: Optional[Callable[[Mapping[str, Any]], None]] = None,
    fail_on_unusable: bool = False,
) -> List[NormalizedStatute]:
    """Parse retained official ZIP bytes and optionally seal exact inventory."""

    try:
        rows, inventory = _scan_new_jersey_bulk_zip(
            bytes(payload),
            code_name=code_name,
            max_statutes=max_statutes,
            bundle_provenance=bundle_provenance,
            emit_rows=True,
        )
    except NewJerseyBulkFrontierError:
        if fail_on_unusable or inventory_observer is not None:
            raise
        return []
    if inventory_observer is not None:
        inventory_observer(inventory)
    if fail_on_unusable and inventory["frontier"]["closed"] is not True:
        raise NewJerseyBulkFrontierError(
            "New Jersey bulk ZIP has unresolved records or a capped frontier"
        )
    return rows


def parse_new_jersey_bulk_zip(
    zip_path: Path,
    *,
    code_name: str = "New Jersey Statutes",
    max_statutes: Optional[int] = None,
    bundle_provenance: Optional[Mapping[str, Any]] = None,
    inventory_observer: Optional[Callable[[Mapping[str, Any]], None]] = None,
    fail_on_unusable: bool = False,
) -> List[NormalizedStatute]:
    """Parse official STATUTES-TEXT.zip into NormalizedStatute rows."""

    path = Path(zip_path)
    if not path.is_file():
        raise FileNotFoundError(f"New Jersey bulk zip missing: {path}")
    try:
        rows, inventory = _scan_new_jersey_bulk_zip(
            path,
            code_name=code_name,
            max_statutes=max_statutes,
            bundle_provenance=bundle_provenance,
            emit_rows=True,
        )
    except NewJerseyBulkFrontierError:
        if fail_on_unusable or inventory_observer is not None:
            raise
        return []
    if inventory_observer is not None:
        inventory_observer(inventory)
    if fail_on_unusable and inventory["frontier"]["closed"] is not True:
        raise NewJerseyBulkFrontierError(
            "New Jersey bulk ZIP has unresolved records or a capped frontier"
        )
    return rows


def inventory_new_jersey_bulk_zip_bytes(
    payload: bytes,
    *,
    code_name: str = "New Jersey Statutes",
    bundle_provenance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Replay the exact retained ZIP into a non-emitting inventory."""

    _rows, inventory = _scan_new_jersey_bulk_zip(
        bytes(payload),
        code_name=code_name,
        max_statutes=None,
        bundle_provenance=bundle_provenance,
        emit_rows=False,
    )
    return inventory


def configured_bulk_zip_path() -> Optional[Path]:
    raw = current_state_law_run_environment_value("NEW_JERSEY_BULK_ZIP").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
