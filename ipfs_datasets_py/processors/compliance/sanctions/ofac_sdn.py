"""Bounded, primary-source OFAC SDN XML ingestion.

The parser consumes bytes supplied by an injected downloader.  It does not
perform search, entity resolution, or network access, and those conveniences
must never substitute for the retained OFAC source artifact.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timezone
from typing import Final
from urllib.parse import urlsplit

from ....logic.crypto_ir.compliance.models import (
    ComplianceModelError,
    DesignationRecord,
    DigitalCurrencyIdentifier,
    Jurisdiction,
    SanctionsAuthority,
    SanctionsList,
    SanctionsProgram,
    SanctionsSnapshot,
)
from .snapshot import (
    DiagnosticSeverity,
    ParsedSanctionsSnapshot,
    PublishedHashEvidence,
    SignatureEvidence,
    SnapshotDiagnostic,
    SnapshotSource,
)

OFAC_SANCTIONS_LIST_SERVICE_URL: Final[str] = (
    "https://ofac.treasury.gov/sanctions-list-service"
)
OFAC_SLS_HOST_URL: Final[str] = "https://sanctionslist.ofac.treas.gov/"
OFAC_SDN_XML_URL: Final[str] = (
    "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"
)
OFFICIAL_OFAC_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "ofac.treasury.gov",
        "sanctionslist.ofac.treas.gov",
        "sanctionslistservice.ofac.treas.gov",
    }
)
PARSER_IDENTITY: Final[str] = "ipfs-datasets.ofac-sdn-xml"
PARSER_VERSION: Final[str] = "1.0.0"
SUPPORTED_SCHEMA_ROOT: Final[str] = "sdnList"
DEFAULT_MAX_SOURCE_BYTES: Final[int] = 64 * 1024 * 1024
DEFAULT_MAX_ENTRIES: Final[int] = 100_000
DEFAULT_MAX_TEXT_LENGTH: Final[int] = 16_384

_DIGITAL_CURRENCY_TYPE = re.compile(
    r"^Digital Currency Address\s*-\s*([A-Za-z0-9._-]+)$",
    re.IGNORECASE,
)
_HEX_ADDRESS = re.compile(r"^0x[0-9A-Fa-f]{40}$")
_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_RIPPLE_BASE58 = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"
_MONERO_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{95}(?:[1-9A-HJ-NP-Za-km-z]{11})?$")


class OFACIngestionError(ValueError):
    """Raised for an invalid injected acquisition contract."""


def is_official_ofac_url(url: str) -> bool:
    """Return whether ``url`` is an HTTPS URL on an exact approved OFAC host."""

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in OFFICIAL_OFAC_HOSTS
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
    )


class OFACSDNParser:
    """Parse legacy OFAC SDN XML while retaining the exact downloaded bytes."""

    def __init__(
        self,
        *,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_text_length: int = DEFAULT_MAX_TEXT_LENGTH,
    ) -> None:
        for name, value in (
            ("max_source_bytes", max_source_bytes),
            ("max_entries", max_entries),
            ("max_text_length", max_text_length),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.max_source_bytes = max_source_bytes
        self.max_entries = max_entries
        self.max_text_length = max_text_length

    def acquire(
        self,
        fetcher: Callable[[str, int], bytes],
        *,
        source_url: str = OFAC_SDN_XML_URL,
        retrieved_at: str | datetime,
        published_at: str | datetime | None = None,
        effective_at: str | datetime | None = None,
        transport: str = "injected",
        transport_metadata: Mapping[str, str] | None = None,
        published_hashes: Sequence[PublishedHashEvidence] = (),
        signatures: Sequence[SignatureEvidence] = (),
        previous: ParsedSanctionsSnapshot | None = None,
    ) -> ParsedSanctionsSnapshot:
        """Acquire through a caller-supplied bounded fetch function, then parse.

        ``fetcher`` receives ``(official_url, maximum_bytes)`` and must return
        bytes.  Redirect policy, TLS policy, authentication, and egress remain
        the caller's responsibility and can be bound in ``transport_metadata``.
        """

        if not callable(fetcher):
            raise TypeError("fetcher must be callable")
        if not is_official_ofac_url(source_url):
            raise OFACIngestionError("source_url is not an approved official OFAC URL")
        raw_bytes = fetcher(source_url, self.max_source_bytes)
        if type(raw_bytes) is not bytes:
            raise OFACIngestionError("injected fetcher must return bytes")
        if len(raw_bytes) > self.max_source_bytes:
            raise OFACIngestionError("injected fetch exceeded max_source_bytes")
        return self.parse(
            raw_bytes,
            source_url=source_url,
            retrieved_at=retrieved_at,
            published_at=published_at,
            effective_at=effective_at,
            transport=transport,
            transport_metadata=transport_metadata,
            published_hashes=published_hashes,
            signatures=signatures,
            previous=previous,
        )

    def parse(
        self,
        raw_bytes: bytes,
        *,
        source_url: str,
        retrieved_at: str | datetime,
        published_at: str | datetime | None = None,
        effective_at: str | datetime | None = None,
        transport: str = "offline_fixture",
        transport_metadata: Mapping[str, str] | None = None,
        published_hashes: Sequence[PublishedHashEvidence] = (),
        signatures: Sequence[SignatureEvidence] = (),
        previous: ParsedSanctionsSnapshot | None = None,
    ) -> ParsedSanctionsSnapshot:
        """Import one exact XML artifact and return evidence even on failure."""

        if type(raw_bytes) is not bytes:
            raise TypeError("raw_bytes must be bytes")
        if not raw_bytes:
            raise OFACIngestionError("raw_bytes must not be empty")
        if len(raw_bytes) > self.max_source_bytes:
            raise OFACIngestionError("source exceeds max_source_bytes")

        source = SnapshotSource(
            raw_bytes=raw_bytes,
            source_url=source_url,
            transport=transport,
            retrieved_at=retrieved_at,
            published_at=published_at,
            effective_at=effective_at,
            transport_metadata=transport_metadata or {},
            published_hashes=tuple(published_hashes),
            signatures=tuple(signatures),
        )
        diagnostics: list[SnapshotDiagnostic] = []
        if not is_official_ofac_url(source_url):
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.unofficial_source",
                    "Artifact URL is not an approved official OFAC HTTPS origin",
                )
            )

        upper_source = raw_bytes.upper()
        if b"<!DOCTYPE" in upper_source or b"<!ENTITY" in upper_source:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.unsafe_xml",
                    "DTD and entity declarations are forbidden",
                )
            )
            return self._failed(source, diagnostics)

        try:
            root = ET.fromstring(raw_bytes)
        except ET.ParseError as exc:
            diagnostics.append(
                SnapshotDiagnostic("ofac.malformed_xml", f"Malformed XML: {exc}")
            )
            return self._failed(source, diagnostics)

        schema_identity = _schema_identity(root)
        if _local(root.tag) != SUPPORTED_SCHEMA_ROOT:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.unknown_schema",
                    f"Unsupported OFAC root element: {_local(root.tag)!r}",
                )
            )
            return self._failed(source, diagnostics, schema_identity=schema_identity)

        entries = _children_or_descendants(root, "sdnEntry")
        if len(entries) > self.max_entries:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.entry_limit",
                    "SDN entry count exceeds the configured parser bound",
                )
            )
            return self._failed(source, diagnostics, schema_identity=schema_identity)

        declared_count = self._declared_count(root, diagnostics)
        xml_published = self._published_at(root, diagnostics)
        bound_published = source.published_at or xml_published
        bound_effective = source.effective_at or bound_published
        if bound_published != source.published_at or bound_effective != source.effective_at:
            source = replace(
                source,
                published_at=bound_published,
                effective_at=bound_effective,
            )
        if not bound_published:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.publication_time_missing",
                    "No publication time was supplied or present in OFAC XML",
                )
            )
        if not bound_effective:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.effective_time_missing",
                    "No effective time can be bound to this snapshot",
                )
            )
        if source.published_at and xml_published and source.published_at != xml_published:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.publication_time_mismatch",
                    "Supplied and XML publication times disagree",
                )
            )

        designations: list[DesignationRecord] = []
        program_names: dict[str, str] = {}
        identifier_count = 0
        seen_uids: set[str] = set()
        for position, entry in enumerate(entries, start=1):
            parsed = self._parse_entry(
                entry,
                position=position,
                effective_at=bound_effective,
                diagnostics=diagnostics,
                program_names=program_names,
            )
            if parsed is not None:
                designation, uid = parsed
                if uid in seen_uids:
                    diagnostics.append(
                        SnapshotDiagnostic(
                            "ofac.duplicate_uid",
                            f"Duplicate SDN uid {uid!r}",
                        )
                    )
                    continue
                seen_uids.add(uid)
                designations.append(designation)
                identifier_count += len(designation.identifiers)

        if declared_count is not None and declared_count != len(entries):
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.record_count_mismatch",
                    "OFAC Record_Count does not match XML sdnEntry count",
                )
            )
        if not entries:
            diagnostics.append(
                SnapshotDiagnostic("ofac.empty_list", "OFAC SDN list has no entries")
            )

        snapshot: SanctionsSnapshot | None = None
        if not any(item.severity is DiagnosticSeverity.ERROR for item in diagnostics):
            authority = SanctionsAuthority(
                authority_id="authority:us-ofac",
                name="U.S. Department of the Treasury OFAC",
                jurisdiction=Jurisdiction(code="US", name="United States"),
                source_uri=OFAC_SANCTIONS_LIST_SERVICE_URL,
            )
            programs = tuple(
                SanctionsProgram(
                    program_id=program_id,
                    name=name,
                    authority_id=authority.authority_id,
                )
                for program_id, name in sorted(program_names.items())
            )
            if not programs:
                diagnostics.append(
                    SnapshotDiagnostic(
                        "ofac.programs_missing",
                        "No sanctions programs were present in the SDN entries",
                    )
                )
            else:
                digest_suffix = source.content_sha256.removeprefix("sha256:")[:24]
                snapshot_id = f"snapshot:ofac-sdn:{digest_suffix}"
                try:
                    snapshot = SanctionsSnapshot(
                        snapshot_id=snapshot_id,
                        authority=authority,
                        sanctions_list=SanctionsList(
                            list_id="list:ofac-sdn",
                            name="OFAC Specially Designated Nationals List",
                            authority_id=authority.authority_id,
                        ),
                        programs=programs,
                        jurisdictions=(authority.jurisdiction,),
                        revision=f"revision:{digest_suffix}",
                        published_at=bound_published,
                        effective_at=bound_effective,
                        retrieved_at=source.retrieved_at,
                        content_digest=source.content_sha256,
                        designations=tuple(designations),
                        complete=True,
                        supersedes_snapshot_id=(
                            previous.snapshot.snapshot_id
                            if previous is not None and previous.snapshot is not None
                            else ""
                        ),
                    )
                except ComplianceModelError as exc:
                    diagnostics.append(
                        SnapshotDiagnostic(
                            "ofac.snapshot_model_invalid",
                            f"Parsed snapshot violates the typed evidence contract: {exc}",
                        )
                    )

        return ParsedSanctionsSnapshot(
            source=source,
            parser_identity=PARSER_IDENTITY,
            parser_version=PARSER_VERSION,
            schema_identity=schema_identity,
            snapshot=snapshot,
            declared_entry_count=declared_count,
            parsed_entry_count=len(entries),
            digital_identifier_count=identifier_count,
            diagnostics=tuple(diagnostics),
        )

    def _failed(
        self,
        source: SnapshotSource,
        diagnostics: Sequence[SnapshotDiagnostic],
        *,
        schema_identity: str = "unrecognized",
    ) -> ParsedSanctionsSnapshot:
        return ParsedSanctionsSnapshot(
            source=source,
            parser_identity=PARSER_IDENTITY,
            parser_version=PARSER_VERSION,
            schema_identity=schema_identity,
            snapshot=None,
            declared_entry_count=None,
            parsed_entry_count=0,
            digital_identifier_count=0,
            diagnostics=tuple(diagnostics),
        )

    def _declared_count(
        self, root: ET.Element, diagnostics: list[SnapshotDiagnostic]
    ) -> int | None:
        value = _first_text(root, "Record_Count", "recordCount")
        if not value:
            return None
        try:
            count = int(value)
        except ValueError:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.record_count_invalid",
                    "OFAC Record_Count is not a non-negative integer",
                )
            )
            return None
        if count < 0:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.record_count_invalid",
                    "OFAC Record_Count is not a non-negative integer",
                )
            )
            return None
        return count

    def _published_at(
        self, root: ET.Element, diagnostics: list[SnapshotDiagnostic]
    ) -> str:
        value = _first_text(root, "Publish_Date", "publishDate", "DateOfIssue")
        if not value:
            return ""
        for pattern in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(value, pattern).replace(tzinfo=UTC)
                return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
            except ValueError:
                pass
        try:
            candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return (
                parsed.astimezone(UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
        except ValueError:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.publication_time_invalid",
                    "OFAC publication time is malformed",
                )
            )
            return ""

    def _parse_entry(
        self,
        entry: ET.Element,
        *,
        position: int,
        effective_at: str,
        diagnostics: list[SnapshotDiagnostic],
        program_names: dict[str, str],
    ) -> tuple[DesignationRecord, str] | None:
        uid = _direct_text(entry, "uid")
        if not uid or len(uid) > 128:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.entry_uid_invalid",
                    f"SDN entry {position} has no bounded uid",
                )
            )
            return None
        first_name = _direct_text(entry, "firstName")
        last_name = _direct_text(entry, "lastName")
        primary_name = " ".join(item for item in (first_name, last_name) if item)
        if not primary_name or len(primary_name) > self.max_text_length:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.entry_name_invalid",
                    f"SDN entry {uid!r} has no bounded primary name",
                )
            )
            return None

        program_values = _texts(entry, "program")
        if not program_values:
            diagnostics.append(
                SnapshotDiagnostic(
                    "ofac.entry_program_missing",
                    f"SDN entry {uid!r} has no sanctions program",
                )
            )
            return None
        program_ids: list[str] = []
        for program in program_values:
            if len(program) > 256:
                diagnostics.append(
                    SnapshotDiagnostic(
                        "ofac.program_invalid",
                        f"SDN entry {uid!r} has an oversized program",
                    )
                )
                continue
            program_id = f"program:ofac:{_slug(program)}"
            program_names[program_id] = program
            if program_id not in program_ids:
                program_ids.append(program_id)

        aliases: list[str] = []
        for aka in _descendants(entry, "aka"):
            alias = " ".join(
                item
                for item in (
                    _direct_text(aka, "firstName"),
                    _direct_text(aka, "lastName"),
                )
                if item
            )
            if (
                alias
                and alias != primary_name
                and len(alias) <= self.max_text_length
                and alias not in aliases
            ):
                aliases.append(alias)

        identifiers: list[DigitalCurrencyIdentifier] = []
        seen_keys: set[tuple[str, str, str, str]] = set()
        for identity in _descendants(entry, "id"):
            id_type = _direct_text(identity, "idType")
            match = _DIGITAL_CURRENCY_TYPE.fullmatch(id_type)
            if not match:
                continue
            symbol = match.group(1).upper()
            address = _direct_text(identity, "idNumber")
            identifier = _parse_digital_identifier(
                symbol,
                address,
                entry_uid=uid,
                identifier_uid=_direct_text(identity, "uid"),
                diagnostics=diagnostics,
            )
            if identifier is not None and identifier.comparison_key not in seen_keys:
                seen_keys.add(identifier.comparison_key)
                identifiers.append(identifier)

        if not program_ids:
            return None
        safe_uid = _stable_component(uid)
        return (
            DesignationRecord(
                designation_id=f"designation:ofac-sdn:{safe_uid}",
                party_id=f"party:ofac-sdn:{safe_uid}",
                primary_name=primary_name,
                authority_id="authority:us-ofac",
                program_ids=tuple(program_ids),
                jurisdiction_codes=("US",),
                identifiers=tuple(identifiers),
                aliases=tuple(aliases),
                effective_from=effective_at,
            ),
            uid,
        )


def _parse_digital_identifier(
    symbol: str,
    address: str,
    *,
    entry_uid: str,
    identifier_uid: str,
    diagnostics: list[SnapshotDiagnostic],
) -> DigitalCurrencyIdentifier | None:
    chain: str
    network: str
    canonical: str

    if symbol in {"ETH"}:
        chain, network = "eip155", "ethereum-mainnet"
        if not _HEX_ADDRESS.fullmatch(address):
            return _invalid_identifier(symbol, entry_uid, diagnostics)
        canonical = address.lower()
    elif symbol in {"BTC", "XBT"}:
        chain, network = "bip122", "bitcoin-mainnet"
        if not _valid_bitcoin(address):
            return _invalid_identifier(symbol, entry_uid, diagnostics)
        canonical = address.lower() if address.lower().startswith(("bc1", "bc1m")) else address
    elif symbol == "LTC":
        chain, network = "bip122", "litecoin-mainnet"
        if not _valid_litecoin(address):
            return _invalid_identifier(symbol, entry_uid, diagnostics)
        canonical = address.lower() if address.lower().startswith("ltc1") else address
    elif symbol == "BCH":
        chain, network = "bip122", "bitcoin-cash-mainnet"
        if not _valid_cashaddr(address):
            return _invalid_identifier(symbol, entry_uid, diagnostics)
        canonical = address.lower()
    elif symbol == "XRP":
        chain, network = "xrpl", "xrpl-mainnet"
        if not _valid_base58check(address, _RIPPLE_BASE58, versions={b"\x00"}):
            return _invalid_identifier(symbol, entry_uid, diagnostics)
        canonical = address
    elif symbol == "SOL":
        chain, network = "solana", "solana-mainnet"
        decoded = _decode_base58(address, _BASE58)
        if decoded is None or len(decoded) != 32:
            return _invalid_identifier(symbol, entry_uid, diagnostics)
        canonical = address
    elif symbol == "TRX":
        chain, network = "tron", "tron-mainnet"
        if not _valid_base58check(address, _BASE58, versions={b"\x41"}):
            return _invalid_identifier(symbol, entry_uid, diagnostics)
        canonical = address
    elif symbol == "XMR":
        chain, network = "monero", "monero-mainnet"
        if not _MONERO_RE.fullmatch(address):
            return _invalid_identifier(symbol, entry_uid, diagnostics)
        canonical = address
    else:
        diagnostics.append(
            SnapshotDiagnostic(
                "ofac.currency_network_unsupported",
                f"Digital currency symbol {symbol!r} is not unambiguously chain-qualified",
            )
        )
        return None

    stable_id = _stable_component(
        identifier_uid
        or hashlib.sha256(f"{symbol}\0{canonical}".encode()).hexdigest()[:24]
    )
    return DigitalCurrencyIdentifier(
        identifier_id=f"identifier:ofac-sdn:{_stable_component(entry_uid)}:{stable_id}",
        chain_namespace=chain,
        network=network,
        address=canonical,
        asset_reference=symbol.lower(),
    )


def _invalid_identifier(
    symbol: str,
    entry_uid: str,
    diagnostics: list[SnapshotDiagnostic],
) -> None:
    diagnostics.append(
        SnapshotDiagnostic(
            "ofac.digital_identifier_invalid",
            f"SDN entry {entry_uid!r} contains an invalid {symbol} identifier",
        )
    )
    return None


def _decode_base58(value: str, alphabet: str) -> bytes | None:
    if not value:
        return None
    lookup = {character: index for index, character in enumerate(alphabet)}
    number = 0
    try:
        for character in value:
            number = number * 58 + lookup[character]
    except KeyError:
        return None
    encoded = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    zeros = len(value) - len(value.lstrip(alphabet[0]))
    return b"\x00" * zeros + encoded


def _valid_base58check(
    value: str, alphabet: str, *, versions: set[bytes]
) -> bool:
    decoded = _decode_base58(value, alphabet)
    if decoded is None or len(decoded) < 5:
        return False
    payload, checksum = decoded[:-4], decoded[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return checksum == expected and payload[:1] in versions


def _valid_bitcoin(value: str) -> bool:
    lower = value.lower()
    if lower.startswith(("bc1q", "bc1p")):
        return _valid_bech32(value, "bc")
    return _valid_base58check(value, _BASE58, versions={b"\x00", b"\x05"})


def _valid_litecoin(value: str) -> bool:
    if value.lower().startswith("ltc1"):
        return _valid_bech32(value, "ltc")
    return _valid_base58check(value, _BASE58, versions={b"\x30", b"\x32", b"\x05"})


def _valid_bech32(value: str, expected_hrp: str) -> bool:
    if not 8 <= len(value) <= 90 or (value.lower() != value and value.upper() != value):
        return False
    value = value.lower()
    separator = value.rfind("1")
    if separator < 1 or separator + 7 > len(value):
        return False
    if value[:separator] != expected_hrp:
        return False
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    try:
        data = [charset.index(c) for c in value[separator + 1 :]]
    except ValueError:
        return False
    polymod = _bech32_polymod(_bech32_hrp_expand(expected_hrp) + data)
    return polymod in {1, 0x2BC830A3}


def _bech32_polymod(values: Sequence[int]) -> int:
    generators = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for index, generator in enumerate(generators):
            if (top >> index) & 1:
                checksum ^= generator
    return checksum


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _valid_cashaddr(value: str) -> bool:
    lower = value.lower()
    if value.lower() != value and value.upper() != value:
        return False
    if ":" not in lower:
        lower = "bitcoincash:" + lower
    prefix, payload = lower.rsplit(":", 1)
    if prefix != "bitcoincash" or len(payload) < 8:
        return False
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    try:
        values = [charset.index(c) for c in payload]
    except ValueError:
        return False
    expanded = [ord(c) & 31 for c in prefix] + [0] + values
    return _cashaddr_polymod(expanded) == 0


def _cashaddr_polymod(values: Sequence[int]) -> int:
    generators = (
        0x98F2BC8E61,
        0x79B76D99E2,
        0xF33E5FB3C4,
        0xAE2EABE2A8,
        0x1E4F43E470,
    )
    checksum = 1
    for value in values:
        top = checksum >> 35
        checksum = ((checksum & 0x07FFFFFFFF) << 5) ^ value
        for index, generator in enumerate(generators):
            if (top >> index) & 1:
                checksum ^= generator
    return checksum ^ 1


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _schema_identity(root: ET.Element) -> str:
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag[1:].split("}", 1)[0]
    return f"ofac:{_local(root.tag)}:{namespace or 'no-namespace'}"


def _descendants(element: ET.Element, local_name: str) -> list[ET.Element]:
    return [item for item in element.iter() if _local(item.tag) == local_name]


def _children_or_descendants(
    element: ET.Element, local_name: str
) -> list[ET.Element]:
    direct = [item for item in element if _local(item.tag) == local_name]
    return direct or _descendants(element, local_name)


def _clean_text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def _direct_text(element: ET.Element, local_name: str) -> str:
    for child in element:
        if _local(child.tag) == local_name:
            return _clean_text(child)
    return ""


def _first_text(element: ET.Element, *local_names: str) -> str:
    names = set(local_names)
    for child in element.iter():
        if _local(child.tag) in names:
            value = _clean_text(child)
            if value:
                return value
    return ""


def _texts(element: ET.Element, local_name: str) -> list[str]:
    values: list[str] = []
    for child in element.iter():
        if _local(child.tag) == local_name:
            value = _clean_text(child)
            if value and value not in values:
                values.append(value)
    return values


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-")
    if slug:
        return slug[:160]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _stable_component(value: str) -> str:
    component = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if component:
        return component[:128]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_SOURCE_BYTES",
    "DEFAULT_MAX_TEXT_LENGTH",
    "DigitalCurrencyIdentifier",
    "OFFICIAL_OFAC_HOSTS",
    "OFACIngestionError",
    "OFACSDNParser",
    "OFAC_SANCTIONS_LIST_SERVICE_URL",
    "OFAC_SDN_XML_URL",
    "OFAC_SLS_HOST_URL",
    "PARSER_IDENTITY",
    "PARSER_VERSION",
    "is_official_ofac_url",
]
