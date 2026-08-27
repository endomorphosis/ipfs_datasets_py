"""Fail-closed adapter from refresh-state-law artifacts to the v2 schema.

The historical ``refresh_state_laws_corpus.py`` command emits newline-delimited
JSON-LD and CID-keyed Parquet files.  Those files are useful acquisition
artifacts, but they are not, by themselves, evidence that a full official
source frontier was closed.  This module provides the deliberately narrow
bridge a live release driver needs:

* stream either refresh JSON-LD or Parquet without fabricating statute text;
* normalize real rows into :class:`~state_laws_release_schema.CorpusRecord`;
* normalize a live acquisition receipt into
  :class:`~state_laws_release_schema.SourceReceiptRecord`;
* admit only rows covered by a verified, input-hash-bound, full-frontier
  official receipt and the sealed LCR-002 source catalog;
* admit byte-receipted web-archive transport of cataloged official locators;
* quarantine secondary sources and generic/unbound recovery, archive, cache,
  or unverified markers;
* reject empty, placeholder, fixture, example, and malformed records; and
* expose a deterministic, input/configuration-bound resume checkpoint.

No network or publication I/O occurs here.  A caller must durably write an
event before advancing its checkpoint; replay is deterministic and therefore
safe for an idempotent ``entry_cid`` keyed writer.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import quote, urldefrag, urlparse

from ipfs_datasets_py.processors.legal_data.canonical_legal_corpora import (
    get_canonical_legal_corpus,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    evaluate_jurisdiction_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus import (
    assess_text_quality,
)
from ipfs_datasets_py.processors.legal_data.state_laws_identity import (
    LegalIdentity,
    parse_legal_id,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    SCHEMA_VERSION as STATE_LAWS_RELEASE_SCHEMA_VERSION,
    AdmissionStatus,
    CorpusRecord,
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
    canonical_json_dumps,
    content_sha256,
    normalize_sha256,
    validate_digest,
    validate_jurisdiction,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    AdmissionRequest,
    OfficialSourceCatalog,
    evaluate_admission,
    get_official_source_catalog,
    is_secondary_host,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
    ARCHIVE_TRANSPORT_KINDS,
    CACHE_TRANSPORT_KINDS,
    StateLawTransportReceiptError,
    VerifiedStateLawTransport,
    verify_state_law_transport_receipt,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import file_digest

ADAPTER_SCHEMA_VERSION = "state-laws-legacy-v2-adapter-v1"
CHECKPOINT_SCHEMA_VERSION = "state-laws-legacy-v2-adapter-checkpoint-v1"
DEFAULT_PARSER_VERSION = "state-laws-legacy-v2-adapter/1"
COLLISION_STRATEGY_VERSION = "canonical-source-identity-collision-granule-v1"
# Length is not a validity rule for enacted law.  Some operative provisions
# are genuinely short; structural/fixture/source checks below own admission.
DEFAULT_MIN_TEXT_CHARS = 1
EXPLICIT_RELATION_FIELDS = (
    "public_laws",
    "cites",
    "amends",
    "repeals",
    "transfers",
)

_CORPUS = get_canonical_legal_corpus("state_laws")
_SHA256_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_FIXTURE_TEXT_RE = re.compile(
    r"\bofficial statutes section\b.*\bshall apply to every person subject to "
    r"this title\b.*\bmay not treat this text as a summary or placeholder\b",
    re.IGNORECASE | re.DOTALL,
)
_FIXTURE_IDENTITY_RE = re.compile(
    r"\b(?:fixture(?:[_ -](?:only|row|statute|text))?|synthetic(?:[_ -](?:row|statute|text))?|"
    r"sample statute text|example statute|lorem ipsum|placeholder text)\b",
    re.IGNORECASE,
)
_FIXTURE_BODY_RE = re.compile(
    r"\b(?:fixture (?:row|statute|text)|synthetic (?:row|statute|text)|"
    r"sample statute text|example statute|lorem ipsum|placeholder text)\b",
    re.IGNORECASE,
)
_ARCHIVE_HOSTS = frozenset(
    {
        "web.archive.org",
        "archive.org",
        "data.commoncrawl.org",
        "index.commoncrawl.org",
        "r.jina.ai",
    }
)
_RESERVED_EXAMPLE_HOSTS = frozenset(
    {
        "example.com",
        "example.net",
        "example.org",
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
    }
)
_RECOVERY_VALUE_RE = re.compile(
    r"(?:^|[_ /-])(?:archive|archived|archival|wayback|common[_ -]?crawl|"
    r"web[_ -]?(?:archive|archiving)|"
    r"recovery|recovered|cache|cached|insecure[_ -]?tls|direct[_ -]?insecure|"
    r"r[_ -]?jina)(?:$|[_ /-])",
    re.IGNORECASE,
)
_UNVERIFIED_VALUE_RE = re.compile(
    r"(?:^|[_ /-])(?:unverified|verification[_ -]?missing|hash[_ -]?missing|"
    r"checksum[_ -]?missing)(?:$|[_ /-])",
    re.IGNORECASE,
)


class LegacyStateLawsAdapterError(ValueError):
    """Base error raised by the legacy-to-v2 adapter."""


class LegacyInputError(LegacyStateLawsAdapterError):
    """The refresh artifact is missing, ambiguous, or unsupported."""


class LegacyReceiptError(LegacyStateLawsAdapterError):
    """The acquisition receipt cannot be represented by the v2 schema."""


class CheckpointMismatchError(LegacyStateLawsAdapterError):
    """A resume checkpoint belongs to different input or adapter settings."""


class AdaptationDisposition(str, Enum):
    """Disposition assigned to one legacy source row."""

    ADMITTED = "admitted"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


def _json_safe(value: Any) -> Any:
    """Return a deterministic JSON-compatible projection without local objects."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


def file_sha256(path: str | Path) -> str:
    """Return the shared artifact-layer SHA-256 in legacy hex form."""

    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise LegacyInputError(f"legacy state-law input is not a file: {target}")
    _, digest = file_digest(target)
    return digest.hex()


def legacy_input_row_count(path: str | Path) -> int:
    """Return the physical source-row count used for receipt reconciliation."""

    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise LegacyInputError(f"legacy state-law input is not a file: {target}")
    if target.suffix.lower() == ".jsonld":
        with target.open("r", encoding="utf-8", errors="strict") as handle:
            return sum(1 for line in handle if line.strip())
    if target.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - dependency-specific
            raise LegacyInputError("pyarrow is required to inspect refresh Parquet") from exc
        return int(pq.ParquetFile(target).metadata.num_rows)
    raise LegacyInputError(f"unsupported refresh input format: {target.suffix}")


def _legacy_input_bytes_metadata(path: Path, serialized: bytes) -> tuple[str, int]:
    """Derive the immutable adapter identity from one captured byte string."""

    digest = hashlib.sha256(serialized).hexdigest()
    suffix = path.suffix.lower()
    if suffix == ".jsonld":
        try:
            text = serialized.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise LegacyInputError(
                f"legacy state-law JSON-LD is not valid UTF-8: {path}"
            ) from exc
        return digest, sum(1 for line in text.splitlines() if line.strip())
    if suffix == ".parquet":
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - dependency-specific
            raise LegacyInputError(
                "pyarrow is required to inspect refresh Parquet"
            ) from exc
        try:
            rows = int(pq.ParquetFile(pa.BufferReader(serialized)).metadata.num_rows)
        except Exception as exc:
            raise LegacyInputError(f"invalid refresh Parquet bytes: {path}") from exc
        return digest, rows
    raise LegacyInputError(f"unsupported refresh input format: {path.suffix}")


def resolve_refresh_state_input(
    output_root: str | Path,
    jurisdiction: str,
    *,
    prefer: str = "parquet",
) -> Path:
    """Resolve one standard refresh output without accepting a combined shard.

    ``output_root`` may be the refresh root, its JSON-LD directory, its Parquet
    directory, or an explicit state file.  Per-state Parquet is preferred by
    default because it preserves the legacy CID column.
    """

    code = validate_jurisdiction(jurisdiction)
    root = Path(output_root).expanduser().resolve()
    if root.is_file():
        expected = f"STATE-{code}"
        if not root.name.upper().startswith(expected):
            raise LegacyInputError(
                f"input filename {root.name!r} does not identify jurisdiction {code}"
            )
        if root.suffix.lower() not in {".jsonld", ".parquet"}:
            raise LegacyInputError(f"unsupported refresh input format: {root.suffix}")
        return root
    if not root.is_dir():
        raise LegacyInputError(f"refresh output root does not exist: {root}")

    parquet_name = _CORPUS.state_parquet_filename(code)
    jsonld_name = f"STATE-{code}.jsonld"
    candidates = {
        "parquet": (
            root / _CORPUS.parquet_dir_name / parquet_name,
            root / parquet_name,
        ),
        "jsonld": (
            root / _CORPUS.jsonld_dir_name / jsonld_name,
            root / jsonld_name,
        ),
    }
    order = ("parquet", "jsonld") if prefer == "parquet" else ("jsonld", "parquet")
    if prefer not in candidates:
        raise LegacyInputError("prefer must be 'parquet' or 'jsonld'")
    for kind in order:
        for candidate in candidates[kind]:
            if candidate.is_file():
                return candidate.resolve()
    raise LegacyInputError(
        f"no per-state JSON-LD or Parquet refresh artifact found for {code} under {root}"
    )


def _first_text(mapping: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _as_non_negative_int(value: Any, name: str) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise LegacyReceiptError(f"{name} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise LegacyReceiptError(f"{name} must be a non-negative integer") from exc
    if number < 0:
        raise LegacyReceiptError(f"{name} must be a non-negative integer")
    return number


def _sequence_of_text(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _acquisition_path_ids(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    value = receipt.get("acquisition_path_ids")
    if value in (None, ""):
        value = receipt.get("acquisition_path_id")
    if value in (None, "") and isinstance(receipt.get("payload"), Mapping):
        payload = receipt["payload"]
        value = payload.get("acquisition_path_ids") or payload.get("acquisition_path_id")
    return tuple(dict.fromkeys(_sequence_of_text(value)))


def _host(url: str) -> str:
    return (urlparse(str(url or "")).hostname or "").strip(".").lower()


def _is_archive_host(host: str) -> bool:
    return any(host == item or host.endswith("." + item) for item in _ARCHIVE_HOSTS)


def _is_example_host(host: str) -> bool:
    return any(host == item or host.endswith("." + item) for item in _RESERVED_EXAMPLE_HOSTS)


def _valid_http_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)


def _looks_like_transport_receipt(value: Mapping[str, Any]) -> bool:
    return bool(
        _first_text(
            value,
            (
                "source_transport",
                "transport_kind",
                "fetch_transport",
                "acquisition_transport",
                "kind",
                "provider",
            ),
        )
        and _first_text(
            value,
            (
                "content_sha256",
                "sha256",
                "body_sha256",
                "raw_sha256",
                "content_digest",
            ),
        )
        and _first_text(
            value,
            ("official_url", "official_source_url", "requested_url", "source_url"),
        )
    )


def _transport_receipt_candidates(mapping: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return only explicit, Georgia-shaped official-byte receipt objects."""

    candidates: list[Mapping[str, Any]] = []
    containers = [mapping]
    for key in (
        "payload",
        "provenance",
        "acquisition",
        "fetch",
        "structured_data",
        "structuredData",
    ):
        nested = mapping.get(key)
        if isinstance(nested, Mapping):
            containers.append(nested)

    for container in containers:
        for key in (
            "transport_receipts",
            "web_archiving_transport_receipts",
            "artifacts",
        ):
            values = container.get(key)
            if isinstance(values, Sequence) and not isinstance(
                values, (str, bytes, bytearray)
            ):
                candidates.extend(
                    item
                    for item in values
                    if isinstance(item, Mapping)
                    and (key != "artifacts" or _looks_like_transport_receipt(item))
                )
        for key in (
            "transport_receipt",
            "web_archiving_transport_receipt",
            "transport",
        ):
            candidate = container.get(key)
            if isinstance(candidate, Mapping) and (
                key != "transport" or _looks_like_transport_receipt(candidate)
            ):
                candidates.append(candidate)

    unique: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        signature = canonical_json_dumps(_json_safe(candidate))
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(candidate)
    return tuple(unique)


def _verify_transport_receipts(
    mapping: Mapping[str, Any],
) -> tuple[tuple[VerifiedStateLawTransport, ...], tuple[str, ...], bool]:
    candidates = _transport_receipt_candidates(mapping)
    verified: list[VerifiedStateLawTransport] = []
    errors: list[str] = []
    for position, candidate in enumerate(candidates):
        try:
            # This adapter is the explicit migration boundary for already
            # retained/on-disk evidence.  Fresh acquisition and publication
            # callers use the verifier's strict default instead.
            verified.append(
                verify_state_law_transport_receipt(
                    candidate,
                    allow_legacy_retained=True,
                )
            )
        except StateLawTransportReceiptError as exc:
            errors.append(f"transport_receipt[{position}]:{exc.code}")
    unique: list[VerifiedStateLawTransport] = []
    seen: set[tuple[Any, ...]] = set()
    for item in verified:
        signature = (
            item.official_url.rstrip("/"),
            item.content_sha256,
            item.transport_chain,
            item.archive_url,
            item.archive_timestamp,
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(item)
    return tuple(unique), tuple(dict.fromkeys(errors)), bool(candidates)


def _truthy_recovery_is_covered(
    key: str,
    verified: Sequence[VerifiedStateLawTransport],
) -> bool:
    if not verified:
        return False
    if key == "cache_hit":
        return any(item.cache_depth for item in verified)
    if key == "direct_insecure_tls":
        return False
    if key == "insecure_tls":
        return any("common_crawl_insecure_tls" in item.transport_chain for item in verified)
    return any(item.is_archival for item in verified)


def _recovery_value_is_covered(
    value: str,
    verified: Sequence[VerifiedStateLawTransport],
) -> bool:
    if not verified:
        return False
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if _UNVERIFIED_VALUE_RE.search(normalized):
        return False
    if "direct_insecure_tls" in normalized:
        return False
    if "insecure_tls" in normalized:
        return any("common_crawl_insecure_tls" in item.transport_chain for item in verified)
    if "cache" in normalized:
        return any(item.cache_depth for item in verified)
    provider_kinds = {kind for item in verified for kind in item.transport_chain}
    if normalized in provider_kinds:
        return True
    for provider in ARCHIVE_TRANSPORT_KINDS | CACHE_TRANSPORT_KINDS:
        if provider in normalized:
            return provider in provider_kinds
    # Aggregate labels (for example ``archived_https`` or
    # ``hash_bound_archived_official``) are covered only by an exact verified
    # archival receipt; the label by itself remains a quarantine marker.
    return any(item.is_archival for item in verified)


def _archive_url_is_covered(
    value: str,
    verified: Sequence[VerifiedStateLawTransport],
) -> bool:
    target = value.strip().rstrip("/")
    return bool(
        target
        and any(
            item.archive_url and item.archive_url.rstrip("/") == target
            for item in verified
        )
    )


def _provenance_markers(
    mapping: Mapping[str, Any],
    *,
    source_url: str = "",
    verified_transports: Sequence[VerifiedStateLawTransport] = (),
) -> tuple[str, ...]:
    """Find explicit recovery/unverified signals without scanning statute text."""

    markers: list[str] = []
    host = _host(source_url)
    if _is_archive_host(host):
        markers.append(f"archive_host:{host}")

    truthy_recovery_fields = (
        "is_recovery",
        "recovery",
        "archive_fallback",
        "archived",
        "cache_hit",
        "insecure_tls",
        "direct_insecure_tls",
    )
    string_fields = (
        "source_kind",
        "source_type",
        "kind",
        "provider",
        "transport",
        "transport_kind",
        "acquisition_transport",
        "fetch_transport",
        "fallback_source",
        "recovery_source",
        "provenance_status",
    )
    url_fields = ("archive_source_url", "archivedAt", "archive_url", "transport_url")
    mappings = [mapping]
    for key in (
        "provenance",
        "acquisition",
        "fetch",
        "transport",
        "transport_receipt",
        "web_archiving_transport_receipt",
        "payload",
        "structured_data",
        "structuredData",
    ):
        nested = mapping.get(key)
        if isinstance(nested, Mapping):
            mappings.append(nested)

    for item in mappings:
        for key in truthy_recovery_fields:
            if item.get(key) is True and not _truthy_recovery_is_covered(
                key, verified_transports
            ):
                markers.append(key)
        if (
            item.get("tls_verify") is False or item.get("verify_tls") is False
        ) and not _truthy_recovery_is_covered("insecure_tls", verified_transports):
            markers.append("insecure_tls")
        for key in string_fields:
            value = str(item.get(key) or "").strip().lower()
            if (
                value
                and _RECOVERY_VALUE_RE.search(value)
                and not _recovery_value_is_covered(value, verified_transports)
            ):
                markers.append(f"{key}:{value}")
            if value and _UNVERIFIED_VALUE_RE.search(value):
                markers.append(f"{key}:unverified")
        verification = str(item.get("verification_result") or "").strip().lower()
        if verification and verification != VerificationResult.VERIFIED.value:
            markers.append(f"verification_result:{verification}")
        for key in url_fields:
            value = str(item.get(key) or "").strip()
            if value and not _archive_url_is_covered(value, verified_transports):
                markers.append(key)
    return tuple(dict.fromkeys(markers))


def _receipt_mapping(value: Mapping[str, Any] | SourceReceiptRecord) -> dict[str, Any]:
    if isinstance(value, SourceReceiptRecord):
        result = value.to_dict()
        # Payload contains the adapter qualification fields on round-trip.
        if isinstance(value.payload, Mapping):
            for key, item in value.payload.items():
                result.setdefault(str(key), item)
        return result
    if not isinstance(value, Mapping):
        raise LegacyReceiptError("source receipt must be a mapping or SourceReceiptRecord")
    return dict(value)


def _receipt_counts(receipt: Mapping[str, Any]) -> dict[str, int]:
    block = receipt.get("disposition")
    if not isinstance(block, Mapping):
        block = receipt
    return {
        name: _as_non_negative_int(block.get(name), name)
        for name in ("discovered", "fetched", "excluded", "quarantined", "failed_final", "duplicates")
    }


def _claimed_frontier_closed(receipt: Mapping[str, Any]) -> bool:
    frontier = receipt.get("frontier")
    if isinstance(frontier, Mapping):
        return frontier.get("closed") is True and frontier.get("enumerator_closed", True) is True
    return receipt.get("frontier_closed") is True


def _reported_hash(receipt: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = receipt.get(key)
        if value not in (None, ""):
            try:
                return normalize_sha256(str(value), name=key)
            except Exception as exc:
                raise LegacyReceiptError(f"{key} is not a valid SHA-256 digest") from exc
    return None


@dataclass(frozen=True, slots=True)
class NormalizedSourceReceipt:
    """Canonical receipt plus the adapter's fail-closed admission decision."""

    record: SourceReceiptRecord
    admission_eligible: bool
    qualification_reasons: tuple[str, ...]
    acquisition_path_ids: tuple[str, ...]
    input_sha256: str
    input_row_count: int
    expected_row_count: int | None
    legacy_receipt_sha256: str
    verified_transport_receipts: tuple[VerifiedStateLawTransport, ...] = ()
    requires_verified_transport_binding: bool = False


def _reverify_normalized_source_receipt(
    receipt: SourceReceiptRecord,
    *,
    input_path: str | Path,
    jurisdiction: str,
    release_point: str,
    relative_path: str | None,
    catalog: OfficialSourceCatalog | None,
    input_bytes: bytes | None = None,
) -> NormalizedSourceReceipt:
    """Reverify a current typed receipt without treating it as legacy input.

    A serialized :class:`SourceReceiptRecord` is the output of this adapter's
    normalizer.  Feeding that output back through the legacy mapping path loses
    the qualification fields nested in ``payload`` and, more importantly,
    evaluates the wrong receipt contract.  This path keeps the typed record
    intact while independently re-reading the canonical artifact and replaying
    every admission check that remains material at the adapter boundary.
    """

    code = validate_jurisdiction(jurisdiction)
    if receipt.jurisdiction != code:
        raise LegacyReceiptError(
            f"receipt jurisdiction {receipt.jurisdiction!r} does not match "
            f"input jurisdiction {code!r}"
        )

    target = Path(input_path).expanduser().resolve()
    if input_bytes is None:
        input_digest = file_sha256(target)
        input_rows = legacy_input_row_count(target)
    else:
        input_digest, input_rows = _legacy_input_bytes_metadata(target, input_bytes)
    payload = receipt.payload
    reasons: list[str] = []

    if receipt.release_point != str(release_point or "").strip():
        reasons.append("receipt_release_point_mismatch")
    if relative_path is not None and receipt.relative_path != relative_path:
        reasons.append("receipt_relative_path_mismatch")
    if payload.get("adapter_schema_version") != ADAPTER_SCHEMA_VERSION:
        reasons.append("receipt_normalized_adapter_schema_mismatch")
    if receipt.schema_version != STATE_LAWS_RELEASE_SCHEMA_VERSION:
        reasons.append("receipt_normalized_release_schema_mismatch")
    if receipt.source_authority_class is not SourceAuthorityClass.OFFICIAL:
        reasons.append(
            f"receipt_authority_not_official:{receipt.source_authority_class.value}"
        )
    if receipt.verification_result is not VerificationResult.VERIFIED:
        reasons.append(f"receipt_not_verified:{receipt.verification_result.value}")
    if payload.get("reported_source_authority_class") != SourceAuthorityClass.OFFICIAL.value:
        reasons.append("receipt_reported_authority_not_official")
    if payload.get("reported_verification_result") != VerificationResult.VERIFIED.value:
        reasons.append("receipt_reported_verification_not_verified")
    if not receipt.frontier_closed:
        reasons.append("receipt_frontier_not_closed")
    if receipt.failed_final:
        reasons.append("receipt_failed_final_nonzero")

    if input_digest not in receipt.content_hashes:
        reasons.append("receipt_input_sha256_missing_from_content_hashes")
    if receipt.official_source_url not in receipt.start_urls:
        reasons.append("receipt_official_source_url_missing_from_start_urls")

    def _payload_digest(key: str) -> str | None:
        value = payload.get(key)
        if value in (None, ""):
            reasons.append(f"receipt_missing_{key}")
            return None
        try:
            return normalize_sha256(str(value), name=key)
        except Exception:
            reasons.append(f"receipt_invalid_{key}")
            return None

    adapter_input_digest = _payload_digest("adapter_input_sha256")
    if adapter_input_digest is not None and adapter_input_digest != input_digest:
        reasons.append("receipt_adapter_input_sha256_mismatch")
    reported_input_digest = _payload_digest("reported_input_sha256")
    if reported_input_digest is not None and reported_input_digest != input_digest:
        reasons.append("receipt_reported_input_sha256_mismatch")
    reported_source_checksum_value = payload.get("reported_source_checksum")
    if reported_source_checksum_value not in (None, ""):
        try:
            reported_source_checksum = normalize_sha256(
                str(reported_source_checksum_value),
                name="reported_source_checksum",
            )
        except Exception:
            reasons.append("receipt_invalid_reported_source_checksum")
        else:
            if reported_source_checksum != receipt.source_checksum:
                reasons.append("receipt_reported_source_checksum_mismatch")
    elif receipt.source_checksum != input_digest:
        reasons.append("receipt_fallback_source_checksum_mismatch")

    def _payload_count(key: str) -> int | None:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            reasons.append(f"receipt_invalid_{key}")
            return None
        return value

    adapter_input_rows = _payload_count("adapter_input_row_count")
    expected_row_count = _payload_count("reported_canonical_row_count")
    if adapter_input_rows is not None and adapter_input_rows != input_rows:
        reasons.append(
            f"receipt_adapter_input_row_count_mismatch:{adapter_input_rows}!={input_rows}"
        )
    if expected_row_count is not None and expected_row_count != input_rows:
        reasons.append(
            f"receipt_canonical_row_count_mismatch:{expected_row_count}!={input_rows}"
        )
    if expected_row_count is not None and receipt.fetched != expected_row_count:
        reasons.append(
            f"receipt_fetched_row_count_mismatch:{receipt.fetched}!={expected_row_count}"
        )

    if payload.get("admission_eligible") is not True:
        reasons.append("receipt_normalized_not_admission_eligible")
    qualification_claim = payload.get("qualification_reasons")
    if not isinstance(qualification_claim, Sequence) or isinstance(
        qualification_claim, (str, bytes, bytearray)
    ):
        reasons.append("receipt_invalid_qualification_reasons")
    else:
        reasons.extend(
            f"receipt_normalized_qualification:{str(item).strip()}"
            for item in qualification_claim
            if str(item).strip()
        )

    paths = _acquisition_path_ids(receipt.to_dict())
    source_policy_admitted = False
    if not paths:
        reasons.append("receipt_missing_acquisition_path_ids")
    else:
        try:
            decision = evaluate_admission(
                AdmissionRequest(
                    postal_code=code,
                    acquisition_path_ids=paths,
                    release_point=release_point,
                    source_url=receipt.official_source_url,
                ),
                catalog=catalog or get_official_source_catalog(),
            )
            if decision.admitted:
                source_policy_admitted = True
            else:
                reasons.append("receipt_source_policy_not_admitted")
        except ValueError as exc:
            reasons.append(f"receipt_source_policy:{type(exc).__name__}")

    record_mapping = receipt.to_dict()
    verified_transports, raw_transport_errors, had_transport_receipts = (
        _verify_transport_receipts(record_mapping)
    )
    transport_errors = list(raw_transport_errors)
    for item in verified_transports:
        if item.content_sha256 not in receipt.content_hashes:
            transport_errors.append(
                "transport_receipt:content_sha256_not_in_receipt_hashes"
            )
    transport_errors = list(dict.fromkeys(transport_errors))
    reasons.extend(f"receipt_transport:{item}" for item in transport_errors)

    declared_verified = payload.get("verified_transport_receipts")
    verified_projection = [item.to_dict() for item in verified_transports]
    if not isinstance(declared_verified, Sequence) or isinstance(
        declared_verified, (str, bytes, bytearray)
    ):
        reasons.append("receipt_invalid_verified_transport_receipts")
    elif _json_safe(list(declared_verified)) != _json_safe(verified_projection):
        reasons.append("receipt_verified_transport_receipts_mismatch")

    stored_transport_errors = payload.get("transport_receipt_errors")
    if not isinstance(stored_transport_errors, Sequence) or isinstance(
        stored_transport_errors, (str, bytes, bytearray)
    ):
        reasons.append("receipt_invalid_transport_receipt_errors")
    elif any(str(item).strip() for item in stored_transport_errors):
        reasons.append("receipt_stored_transport_receipt_errors_nonempty")

    transport_reverified = bool(
        had_transport_receipts and verified_transports and not transport_errors
    )
    claimed_transport_trusted = payload.get("verified_transport_receipts_trusted")
    if not isinstance(claimed_transport_trusted, bool):
        reasons.append("receipt_invalid_verified_transport_receipts_trusted")
    elif claimed_transport_trusted != transport_reverified:
        reasons.append("receipt_verified_transport_trust_mismatch")

    trusted_transports = verified_transports if transport_reverified else ()
    transport_markers = _provenance_markers(
        record_mapping,
        source_url=receipt.official_source_url,
        verified_transports=trusted_transports,
    )
    if transport_markers:
        reasons.extend(f"receipt_transport:{item}" for item in transport_markers)
    stored_transport_markers = payload.get("transport_markers")
    if not isinstance(stored_transport_markers, Sequence) or isinstance(
        stored_transport_markers, (str, bytes, bytearray)
    ):
        reasons.append("receipt_invalid_transport_markers")
    elif tuple(str(item) for item in stored_transport_markers) != transport_markers:
        reasons.append("receipt_transport_markers_mismatch")

    requires_transport_binding = payload.get("requires_verified_transport_binding")
    if not isinstance(requires_transport_binding, bool):
        reasons.append("receipt_invalid_requires_verified_transport_binding")
        requires_transport_binding = False
    expected_transport_binding = bool(
        transport_reverified
        and any(item.is_archival or item.cache_depth for item in verified_transports)
    )
    if requires_transport_binding != expected_transport_binding:
        reasons.append("receipt_transport_binding_requirement_mismatch")

    legacy_digest = _payload_digest("legacy_receipt_sha256")
    if legacy_digest is None:
        legacy_digest = content_sha256(canonical_json_dumps(record_mapping))

    # Keep the typed record immutable and identical on a valid round trip.  The
    # qualification result below is newly derived from the current artifact,
    # catalog, release pin, and retained transport evidence.
    qualification = tuple(dict.fromkeys(reasons))
    return NormalizedSourceReceipt(
        record=receipt,
        admission_eligible=not qualification and source_policy_admitted,
        qualification_reasons=qualification,
        acquisition_path_ids=paths,
        input_sha256=input_digest,
        input_row_count=input_rows,
        expected_row_count=expected_row_count,
        legacy_receipt_sha256=legacy_digest,
        verified_transport_receipts=verified_transports,
        requires_verified_transport_binding=bool(requires_transport_binding),
    )


def normalize_source_receipt(
    receipt: Mapping[str, Any] | SourceReceiptRecord,
    *,
    input_path: str | Path,
    jurisdiction: str,
    release_point: str,
    relative_path: str | None = None,
    catalog: OfficialSourceCatalog | None = None,
    input_bytes: bytes | None = None,
) -> NormalizedSourceReceipt:
    """Normalize and qualify one full-frontier acquisition receipt.

    Admission requires an explicit ``verification_result=verified`` and an
    explicit input binding (``adapter_input_sha256``, ``artifact_sha256``,
    ``input_sha256``, or a matching ``source_checksum``).  Missing evidence is
    represented as an unverified receipt and quarantines rows; it is never
    upgraded from a plausible URL.  Archive/cache transport is eligible only
    when a provider-specific receipt binds the exact official locator and body
    SHA-256, that digest is included in this closed receipt, and each adapted
    row repeats the matching digest.
    """

    if isinstance(receipt, SourceReceiptRecord):
        return _reverify_normalized_source_receipt(
            receipt,
            input_path=input_path,
            jurisdiction=jurisdiction,
            release_point=release_point,
            relative_path=relative_path,
            catalog=catalog,
            input_bytes=input_bytes,
        )

    raw = _receipt_mapping(receipt)
    code = validate_jurisdiction(jurisdiction)
    raw_code = str(raw.get("jurisdiction") or "").strip().upper()
    if raw_code and raw_code != code:
        raise LegacyReceiptError(
            f"receipt jurisdiction {raw_code!r} does not match input jurisdiction {code!r}"
        )
    target = Path(input_path).expanduser().resolve()
    if input_bytes is None:
        input_digest = file_sha256(target)
        input_rows = legacy_input_row_count(target)
    else:
        input_digest, input_rows = _legacy_input_bytes_metadata(target, input_bytes)
    safe_raw = _json_safe(raw)
    raw_digest = content_sha256(canonical_json_dumps(safe_raw))
    reasons: list[str] = []

    completeness_payload = raw.get("completeness_receipt")
    if not isinstance(completeness_payload, Mapping):
        completeness_payload = raw
    verdict = evaluate_jurisdiction_receipt(
        completeness_payload,
        case_id=f"legacy_v2_adapter_{code.lower()}",
    )
    if not verdict.complete:
        reasons.extend(f"receipt_gate:{kind}" for kind in verdict.kinds)

    source_url = _first_text(
        raw,
        ("official_source_url", "source_url", "entry_url", "start_url"),
    )
    start_urls = _sequence_of_text(raw.get("start_urls"))
    if not source_url and start_urls:
        source_url = start_urls[0]
    if not _valid_http_url(source_url):
        raise LegacyReceiptError("receipt requires an explicit absolute official_source_url")
    if source_url not in start_urls:
        start_urls = (source_url, *start_urls)

    observation_time = _first_text(
        raw,
        ("observation_time", "observed_at", "acquisition_time", "scraped_at"),
    )
    if not observation_time:
        raise LegacyReceiptError("receipt requires an explicit observation/acquisition time")

    counts = _receipt_counts(raw)
    reported_row_count_value = raw.get("canonical_row_count", raw.get("row_count"))
    if reported_row_count_value in (None, ""):
        expected_row_count = None
        reasons.append("receipt_missing_canonical_row_count")
    else:
        expected_row_count = _as_non_negative_int(
            reported_row_count_value,
            "canonical_row_count",
        )
        if expected_row_count != input_rows:
            reasons.append(
                f"receipt_canonical_row_count_mismatch:{expected_row_count}!={input_rows}"
            )
    claimed_closed = _claimed_frontier_closed(raw)
    frontier_closed = claimed_closed and counts["failed_final"] == 0
    if claimed_closed and not frontier_closed:
        reasons.append("receipt_frontier_claim_conflicts_with_failed_final")

    reported_authority = str(
        raw.get("source_authority_class") or raw.get("authority_class") or ""
    ).strip().lower()
    if reported_authority == SourceAuthorityClass.OFFICIAL.value:
        canonical_authority = SourceAuthorityClass.OFFICIAL
    elif reported_authority == SourceAuthorityClass.EXCEPTION.value:
        canonical_authority = SourceAuthorityClass.EXCEPTION
    else:
        # SourceReceiptRecord rejects SECONDARY.  UNKNOWN preserves a
        # non-publication receipt while the reported value remains in payload.
        canonical_authority = SourceAuthorityClass.UNKNOWN
    if raw.get("official_source") is not True:
        reasons.append("receipt_missing_explicit_official_source")
    if canonical_authority is not SourceAuthorityClass.OFFICIAL:
        reasons.append(f"receipt_authority_not_official:{reported_authority or 'missing'}")

    source_checksum = _reported_hash(raw, ("source_checksum", "content_digest"))
    bound_input = _reported_hash(
        raw,
        ("adapter_input_sha256", "artifact_sha256", "input_sha256", "canonical_artifact_sha256"),
    )
    if bound_input is None:
        bound_input = source_checksum
    input_bound = bound_input is not None and bound_input == input_digest
    if bound_input is None:
        reasons.append("receipt_missing_input_sha256_binding")
    elif not input_bound:
        reasons.append("receipt_input_sha256_mismatch")

    reported_verification = str(raw.get("verification_result") or "").strip().lower()
    if reported_verification == VerificationResult.VERIFIED.value and input_bound:
        canonical_verification = VerificationResult.VERIFIED
    elif reported_verification == VerificationResult.VERIFIED.value and not input_bound or reported_verification == VerificationResult.CONFLICT.value:
        canonical_verification = VerificationResult.CONFLICT
    elif reported_verification == VerificationResult.FAILED.value:
        canonical_verification = VerificationResult.FAILED
    elif reported_verification == VerificationResult.MISSING.value:
        canonical_verification = VerificationResult.MISSING
    else:
        canonical_verification = VerificationResult.UNVERIFIED
    if canonical_verification is not VerificationResult.VERIFIED:
        reasons.append(f"receipt_not_verified:{canonical_verification.value}")

    paths = _acquisition_path_ids(raw)
    source_policy_admitted = False
    if not paths:
        reasons.append("receipt_missing_acquisition_path_ids")
    else:
        try:
            decision = evaluate_admission(
                AdmissionRequest(
                    postal_code=code,
                    acquisition_path_ids=paths,
                    release_point=release_point,
                    source_url=source_url,
                ),
                catalog=catalog or get_official_source_catalog(),
            )
            if not decision.admitted:
                reasons.append("receipt_source_policy_not_admitted")
            else:
                source_policy_admitted = True
        except ValueError as exc:
            reasons.append(f"receipt_source_policy:{type(exc).__name__}")

    content_hash_values: list[str] = []
    for key in ("content_hashes", "response_hashes"):
        for item in _sequence_of_text(raw.get(key)):
            try:
                content_hash_values.append(normalize_sha256(item, name=key))
            except Exception as exc:
                raise LegacyReceiptError(f"{key} contains an invalid SHA-256 digest") from exc
    declared_content_hashes = frozenset(content_hash_values)

    (
        verified_transports,
        raw_transport_receipt_errors,
        had_transport_receipts,
    ) = _verify_transport_receipts(raw)
    transport_receipt_errors = list(raw_transport_receipt_errors)
    for item in verified_transports:
        if item.content_sha256 not in declared_content_hashes:
            transport_receipt_errors.append(
                "transport_receipt:content_sha256_not_in_receipt_hashes"
            )
    transport_receipt_errors = list(dict.fromkeys(transport_receipt_errors))
    reasons.extend(f"receipt_transport:{item}" for item in transport_receipt_errors)
    transport_evidence_trusted = bool(
        had_transport_receipts
        and verified_transports
        and not transport_receipt_errors
        and frontier_closed
        and input_bound
        and canonical_verification is VerificationResult.VERIFIED
        and raw.get("official_source") is True
        and canonical_authority is SourceAuthorityClass.OFFICIAL
        and source_policy_admitted
    )
    trusted_transports = verified_transports if transport_evidence_trusted else ()
    transport_markers = _provenance_markers(
        raw,
        source_url=source_url,
        verified_transports=trusted_transports,
    )
    if transport_markers:
        reasons.extend(f"receipt_transport:{marker}" for marker in transport_markers)
    requires_verified_transport_binding = bool(
        transport_evidence_trusted
        and any(item.is_archival or item.cache_depth for item in verified_transports)
    )

    content_hash_values.append(input_digest)
    content_hashes = tuple(dict.fromkeys(content_hash_values))

    record_checksum = source_checksum or input_digest
    receipt_id = _first_text(raw, ("receipt_id", "acquisition_receipt_id"))
    if not receipt_id:
        receipt_id = f"scrape-{code.lower()}-{raw_digest[:20]}"
    receipt_relpath = relative_path or _first_text(raw, ("relative_path",))
    if not receipt_relpath:
        receipt_relpath = f"receipts/scrape/{code.lower()}.json"

    qualification = tuple(dict.fromkeys(reasons))
    payload = {
        "adapter_schema_version": ADAPTER_SCHEMA_VERSION,
        "adapter_input_sha256": input_digest,
        "adapter_input_row_count": input_rows,
        "acquisition_path_ids": list(paths),
        "admission_eligible": not qualification,
        "qualification_reasons": list(qualification),
        "legacy_receipt_sha256": raw_digest,
        "reported_input_sha256": bound_input,
        "reported_canonical_row_count": expected_row_count,
        "reported_source_authority_class": reported_authority or None,
        "reported_source_checksum": source_checksum,
        "reported_verification_result": reported_verification or None,
        "requires_verified_transport_binding": requires_verified_transport_binding,
        "transport_receipt_errors": list(transport_receipt_errors),
        "transport_receipts": [
            _json_safe(candidate) for candidate in _transport_receipt_candidates(raw)
        ],
        "verified_transport_receipts": [item.to_dict() for item in verified_transports],
        "verified_transport_receipts_trusted": transport_evidence_trusted,
        "transport_markers": list(transport_markers),
    }
    try:
        canonical = SourceReceiptRecord(
            receipt_id=receipt_id,
            jurisdiction=code,
            official_source_url=source_url,
            release_point=release_point,
            observation_time=observation_time,
            source_authority_class=canonical_authority,
            source_checksum=record_checksum,
            verification_result=canonical_verification,
            discovered=counts["discovered"],
            fetched=counts["fetched"],
            excluded=counts["excluded"],
            quarantined=counts["quarantined"],
            failed_final=counts["failed_final"],
            frontier_closed=frontier_closed,
            relative_path=receipt_relpath,
            duplicates=counts["duplicates"],
            source_software_version=_first_text(
                raw, ("source_software_version", "scraper_version", "parser_version")
            )
            or None,
            start_urls=start_urls,
            content_hashes=content_hashes,
            payload=payload,
        )
    except Exception as exc:
        raise LegacyReceiptError(f"receipt failed v2 normalization: {exc}") from exc
    return NormalizedSourceReceipt(
        record=canonical,
        admission_eligible=not qualification,
        qualification_reasons=qualification,
        acquisition_path_ids=paths,
        input_sha256=input_digest,
        input_row_count=input_rows,
        expected_row_count=expected_row_count,
        legacy_receipt_sha256=raw_digest,
        verified_transport_receipts=verified_transports,
        requires_verified_transport_binding=requires_verified_transport_binding,
    )


def _parse_jsonld_cell(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _merge_legacy_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Merge a legacy Parquet row with its embedded JSON-LD projection."""

    nested = _parse_jsonld_cell(row.get("jsonld"))
    merged = dict(nested)
    for key, value in row.items():
        if key == "jsonld":
            continue
        if value not in (None, "") or key not in merged:
            merged[key] = value
    return merged


def _explicit_relation_arrays(row: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Retain explicit source relation arrays without projecting ontology.

    Refresh JSON-LD stores public-law evidence below ``citations`` while
    forward-compatible producers may put any supported relation directly on
    the JSON-LD or ``structured_data`` object.  Mirrored values are collapsed
    once, in source order; values within each source array retain their order.
    The graph projector remains the sole owner of target normalization and
    edge semantics.
    """

    containers: list[Mapping[str, Any]] = [row]
    for container_key in ("structured_data", "structuredData"):
        nested = row.get(container_key)
        if isinstance(nested, Mapping):
            containers.append(nested)
            jsonld = nested.get("jsonld")
            if isinstance(jsonld, Mapping):
                containers.append(jsonld)
            elif isinstance(jsonld, str):
                parsed = _parse_jsonld_cell(jsonld)
                if parsed:
                    containers.append(parsed)

    result: dict[str, tuple[str, ...]] = {}
    for field_name in EXPLICIT_RELATION_FIELDS:
        retained: list[str] = []
        seen: set[str] = set()
        candidates: list[Any] = []
        for container in containers:
            if field_name in container:
                candidates.append(container[field_name])
            citations = container.get("citations")
            if field_name == "cites" and isinstance(citations, (list, tuple)):
                candidates.append(citations)
            elif isinstance(citations, Mapping) and field_name in citations:
                candidates.append(citations[field_name])

        for candidate in candidates:
            if candidate in (None, ""):
                continue
            if not isinstance(candidate, (list, tuple)):
                raise LegacyInputError(
                    f"explicit relation {field_name!r} must be an array of strings"
                )
            normalized: list[str] = []
            for position, item in enumerate(candidate):
                if not isinstance(item, str) or not item.strip() or "\x00" in item:
                    raise LegacyInputError(
                        f"explicit relation {field_name}[{position}] must be a non-empty string"
                    )
                normalized.append(item.strip())
            # Preserve ordering and repetition inside one explicit array.  A
            # later mirrored representation contributes only evidence not
            # already present in an earlier representation.
            previously_seen = frozenset(seen)
            retained.extend(item for item in normalized if item not in previously_seen)
            seen.update(normalized)
        result[field_name] = tuple(retained)
    return result


def _legacy_rows_from_bytes(
    path: Path,
    serialized: bytes,
    *,
    start_index: int = 0,
) -> Iterator[tuple[int, Mapping[str, Any]]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonld":
        source_index = 0
        try:
            text = serialized.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise LegacyInputError(
                f"legacy state-law JSON-LD is not valid UTF-8: {path}"
            ) from exc
        with io.StringIO(text) as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                current = source_index
                source_index += 1
                if current < start_index:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    yield current, {
                        "_adapter_parse_error": f"invalid_json_line:{line_number}:{exc.msg}"
                    }
                    continue
                if not isinstance(payload, Mapping):
                    yield current, {"_adapter_parse_error": f"non_object_json_line:{line_number}"}
                    continue
                yield current, dict(payload)
        return
    if suffix == ".parquet":
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - dependency-specific
            raise LegacyInputError("pyarrow is required to adapt refresh Parquet") from exc
        try:
            parquet = pq.ParquetFile(pa.BufferReader(serialized))
        except Exception as exc:
            raise LegacyInputError(f"invalid refresh Parquet bytes: {path}") from exc
        source_index = 0
        for batch in parquet.iter_batches(batch_size=4096):
            for row in batch.to_pylist():
                current = source_index
                source_index += 1
                if current < start_index:
                    continue
                if not isinstance(row, Mapping):
                    yield current, {"_adapter_parse_error": "non_mapping_parquet_row"}
                else:
                    yield current, dict(row)
        return
    raise LegacyInputError(f"unsupported refresh input format: {path.suffix}")


def _legacy_rows(
    path: Path,
    *,
    start_index: int = 0,
) -> Iterator[tuple[int, Mapping[str, Any]]]:
    try:
        serialized = path.read_bytes()
    except OSError as exc:
        raise LegacyInputError(f"cannot read legacy state-law input: {path}") from exc
    yield from _legacy_rows_from_bytes(
        path,
        serialized,
        start_index=start_index,
    )


def _fixture_reasons(row: Mapping[str, Any], *, input_path: Path, text: str, source_url: str) -> tuple[str, ...]:
    reasons: list[str] = []
    if "fixtures" in {part.lower() for part in input_path.parts}:
        reasons.append("fixture_input_path")
    if row.get("_empty") is True:
        reasons.append("empty_sentinel_row")
    for flag in ("fixture", "fixture_only", "synthetic", "sample", "example"):
        if row.get(flag) is True:
            reasons.append(f"explicit_{flag}_flag")
    identifier_probe = " ".join(
        str(row.get(key) or "")
        for key in ("@id", "source_id", "identifier", "legal_id", "kind")
    )
    if _FIXTURE_IDENTITY_RE.search(identifier_probe):
        reasons.append("fixture_or_example_identity")
    if _FIXTURE_TEXT_RE.search(text) or _FIXTURE_BODY_RE.search(text[:2048]):
        reasons.append("fixture_placeholder_or_example_text")
    host = _host(source_url)
    if _is_example_host(host) or host.endswith(".invalid"):
        reasons.append(f"reserved_example_source_host:{host}")
    return tuple(dict.fromkeys(reasons))


def _row_source_url(row: Mapping[str, Any]) -> str:
    return _first_text(row, ("official_source_url", "sourceUrl", "source_url", "url", "sameAs"))


def _row_text(row: Mapping[str, Any]) -> str:
    text = _first_text(row, ("text", "articleBody", "full_text", "body"))
    if not text:
        return ""
    return unicodedata.normalize("NFC", text).replace("\x00", "").strip()


def _chapter_value(row: Mapping[str, Any]) -> str | None:
    value = row.get("chapter")
    if isinstance(value, Mapping):
        # Refresh JSON-LD sometimes stores an inferred code-name label in the
        # chapter object.  It is not a legal hierarchy component.
        value = value.get("chapter_number") or value.get("chapterNumber")
    value = row.get("chapterNumber") or row.get("chapter_number") or value
    text = str(value or "").strip()
    return text or None


def _title_value(row: Mapping[str, Any]) -> str | None:
    value = row.get("titleNumber") or row.get("title_number")
    if not value and isinstance(row.get("isPartOf"), Mapping):
        # ``isPartOf.identifier`` frequently contains a title-specific token,
        # but it is not consistently typed.  Do not guess from it.
        value = None
    text = str(value or "").strip()
    return text or None


def _section_value(row: Mapping[str, Any]) -> str:
    return _first_text(
        row,
        ("section", "sectionNumber", "section_number", "identifier", "legislationIdentifier"),
    )


def _source_granule_value(row: Mapping[str, Any]) -> str | None:
    """Return an explicit, delimiter-safe stable source-unit qualifier.

    A printed citation is not always a unique source identity.  Official bulk
    exports can contain concurrent conditional, future-effective, repealed,
    and superseded records at the same section.  When the producer preserves
    its stable ``source_record_id``, bind that source unit into ``legal_id`` as
    a reversible granule instead of collapsing the distinct records.  Rows
    without an explicit source-unit identity keep the prior citation-only ID.
    """

    containers: list[Mapping[str, Any]] = [row]
    for key in ("provenance", "structured_data", "structuredData"):
        nested = row.get(key)
        if isinstance(nested, Mapping):
            containers.append(nested)

    for key in ("granule", "granule_id"):
        for container in containers:
            value = _first_text(container, (key,))
            if value:
                return value
    for container in containers:
        source_record_id = _first_text(container, ("source_record_id",))
        if source_record_id:
            return "source-record:" + quote(source_record_id, safe="._-")
    return None


def _canonical_source_identity(
    row: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    """Return one exact canonical row identity and any ambiguity reason.

    Refresh JSON-LD stores the canonical source-record identity as ``@id``;
    refresh Parquet mirrors that value into ``source_id`` while retaining the
    JSON-LD object.  A collision qualifier may use that evidence only when all
    present mirrors agree exactly.  Singleton rows do not consume this result,
    preserving their historical identity contract.
    """

    containers: list[Mapping[str, Any]] = [row]
    for key in ("provenance", "structured_data", "structuredData"):
        nested = row.get(key)
        if isinstance(nested, Mapping):
            containers.append(nested)

    values: list[str] = []
    malformed = False
    for container in containers:
        for key in ("source_id", "@id"):
            value = container.get(key)
            if value in (None, ""):
                continue
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                malformed = True
                continue
            values.append(value.strip())
    unique = tuple(dict.fromkeys(values))
    if malformed:
        return None, "malformed_canonical_source_identity"
    if len(unique) > 1:
        return None, "conflicting_canonical_source_identities"
    if not unique:
        return None, "missing_canonical_source_identity"
    return unique[0], None


def _identity_for_row(
    row: Mapping[str, Any],
    *,
    jurisdiction: str,
    code_family: str,
) -> LegalIdentity:
    explicit = str(row.get("legal_id") or "").strip()
    if explicit:
        identity = parse_legal_id(explicit)
        if identity.jurisdiction != jurisdiction or identity.code_family != code_family:
            raise LegacyInputError("explicit legal_id conflicts with jurisdiction/code family")
        return identity
    return LegalIdentity(
        jurisdiction=jurisdiction,
        code_family=code_family,
        section=_section_value(row),
        title=_title_value(row),
        chapter=_chapter_value(row),
        subsection=row.get("subsection"),
        granule=_source_granule_value(row),
        edition=row.get("edition") or row.get("edition_as_of"),
    )


@dataclass(frozen=True, slots=True)
class _CollisionCandidate:
    source_index: int
    identity: LegalIdentity
    explicit_legal_id: bool
    canonical_source_identity: str | None
    canonical_source_identity_error: str | None


@dataclass(frozen=True, slots=True)
class _CollisionPlan:
    by_source_index: Mapping[int, str]
    sha256: str
    group_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "by_source_index",
            MappingProxyType(dict(self.by_source_index)),
        )


def _collision_candidate(
    row: Mapping[str, Any],
    *,
    source_index: int,
    input_path: Path,
    jurisdiction: str,
    code_family: str,
    min_text_chars: int,
) -> _CollisionCandidate | None:
    """Project only rows that reach normal identity adaptation.

    Parse errors and ordinary malformed/fixture rows remain on the adapter's
    existing per-row rejection path instead of turning a separate valid row
    with the same citation into a constructor-level collision error.
    """

    merged = _merge_legacy_row(row)
    if str(merged.get("_adapter_parse_error") or "").strip():
        return None
    raw_code = str(
        merged.get("jurisdiction")
        or merged.get("stateCode")
        or merged.get("state_code")
        or ""
    ).strip().upper()
    if raw_code and raw_code != jurisdiction:
        return None

    text = _row_text(merged)
    source_url = _row_source_url(merged)
    if _fixture_reasons(
        merged,
        input_path=input_path,
        text=text,
        source_url=source_url,
    ):
        return None
    if not text or assess_text_quality(
        text,
        min_usable_chars=min_text_chars,
    ).contaminated:
        return None
    if not _valid_http_url(source_url) or _is_example_host(_host(source_url)):
        return None
    if not _section_value(merged):
        return None
    try:
        _explicit_relation_arrays(merged)
        identity = _identity_for_row(
            merged,
            jurisdiction=jurisdiction,
            code_family=code_family,
        )
        # Invalid explicit provenance hashes are rejected by ``adapt_row``;
        # do not let them participate in a corpus-level collision decision.
        explicit_checksum = _row_provenance_value(
            merged,
            (
                "body_sha256",
                "content_sha256",
                "raw_sha256",
                "content_digest",
                "source_checksum",
            ),
        )
        if explicit_checksum:
            normalize_sha256(explicit_checksum, name="row source checksum")
    except ValueError:
        return None
    source_identity, source_identity_error = _canonical_source_identity(merged)
    return _CollisionCandidate(
        source_index=source_index,
        identity=identity,
        explicit_legal_id=bool(str(merged.get("legal_id") or "").strip()),
        canonical_source_identity=source_identity,
        canonical_source_identity_error=source_identity_error,
    )


def _build_collision_plan(
    input_path: Path,
    *,
    jurisdiction: str,
    code_family: str,
    min_text_chars: int,
    input_bytes: bytes | None = None,
) -> _CollisionPlan:
    """Build an order-independent, collision-only source granule plan."""

    groups: dict[str, list[_CollisionCandidate]] = {}
    source_identity_counts: dict[str, int] = {}
    rows = (
        _legacy_rows(input_path)
        if input_bytes is None
        else _legacy_rows_from_bytes(input_path, input_bytes)
    )
    for source_index, row in rows:
        candidate = _collision_candidate(
            row,
            source_index=source_index,
            input_path=input_path,
            jurisdiction=jurisdiction,
            code_family=code_family,
            min_text_chars=min_text_chars,
        )
        if candidate is None:
            continue
        groups.setdefault(candidate.identity.legal_id, []).append(candidate)
        if candidate.canonical_source_identity is not None:
            source_identity_counts[candidate.canonical_source_identity] = (
                source_identity_counts.get(candidate.canonical_source_identity, 0) + 1
            )

    by_source_index: dict[int, str] = {}
    digest_groups: list[dict[str, Any]] = []
    collision_group_count = 0
    for base_legal_id in sorted(groups):
        members = groups[base_legal_id]
        if len(members) < 2:
            continue
        collision_group_count += 1
        source_indexes = tuple(sorted(member.source_index for member in members))
        if any(member.explicit_legal_id for member in members):
            raise LegacyInputError(
                "canonical legal_id collision contains an explicit legal_id; "
                f"refusing to alter it: legal_id={base_legal_id!r} "
                f"source_indexes={source_indexes!r}"
            )
        if any(member.identity.granule is not None for member in members):
            raise LegacyInputError(
                "canonical legal_id collision persists after an explicit source granule; "
                f"legal_id={base_legal_id!r} source_indexes={source_indexes!r}"
            )
        identity_errors = tuple(
            sorted(
                {
                    member.canonical_source_identity_error
                    for member in members
                    if member.canonical_source_identity_error
                }
            )
        )
        if identity_errors:
            raise LegacyInputError(
                "canonical legal_id collision lacks unambiguous source identity: "
                f"legal_id={base_legal_id!r} errors={identity_errors!r} "
                f"source_indexes={source_indexes!r}"
            )
        source_identities = tuple(
            member.canonical_source_identity for member in members
        )
        if any(identity is None for identity in source_identities):
            raise LegacyInputError(
                "canonical legal_id collision lacks source identity: "
                f"legal_id={base_legal_id!r} source_indexes={source_indexes!r}"
            )
        if len(set(source_identities)) != len(source_identities) or any(
            source_identity_counts.get(str(identity), 0) != 1
            for identity in source_identities
        ):
            raise LegacyInputError(
                "canonical legal_id collision contains a repeated, non-global source identity: "
                f"legal_id={base_legal_id!r} source_indexes={source_indexes!r}"
            )

        digest_members: list[dict[str, str]] = []
        planned_legal_ids: set[str] = set()
        for member in members:
            source_identity = str(member.canonical_source_identity)
            granule = "source-record:" + quote(source_identity, safe="._-")
            planned_identity = replace(member.identity, granule=granule)
            if planned_identity.legal_id in planned_legal_ids:
                raise LegacyInputError(
                    "canonical source identities did not produce unique legal IDs: "
                    f"legal_id={base_legal_id!r}"
                )
            planned_legal_ids.add(planned_identity.legal_id)
            by_source_index[member.source_index] = granule
            digest_members.append(
                {
                    "canonical_source_identity": source_identity,
                    "granule": granule,
                }
            )
        digest_groups.append(
            {
                "base_legal_id": base_legal_id,
                "members": sorted(
                    digest_members,
                    key=lambda item: (
                        item["canonical_source_identity"],
                        item["granule"],
                    ),
                ),
            }
        )

    digest_payload = {
        "collision_groups": digest_groups,
        "strategy_version": COLLISION_STRATEGY_VERSION,
    }
    return _CollisionPlan(
        by_source_index=by_source_index,
        sha256=content_sha256(canonical_json_dumps(digest_payload)),
        group_count=collision_group_count,
    )


def _row_provenance_value(row: Mapping[str, Any], keys: Sequence[str]) -> str:
    containers = [row]
    for container_key in ("structured_data", "structuredData", "provenance"):
        nested = row.get(container_key)
        if isinstance(nested, Mapping):
            containers.append(nested)
    for key in keys:
        for container in containers:
            value = _first_text(container, (key,))
            if value:
                return value
    return ""


def _legacy_hashes(row: Mapping[str, Any]) -> Mapping[str, str]:
    hashes: dict[str, str] = {}
    for key in (
        "ipfs_cid",
        "entry_cid",
        "source_cid",
        "source_checksum",
        "content_sha256",
        "body_sha256",
        "raw_sha256",
        "content_digest",
    ):
        value = (
            str(row.get(key) or "").strip()
            if key.endswith("cid")
            else _row_provenance_value(row, (key,))
        )
        if not value:
            continue
        if key.endswith("cid"):
            try:
                hashes[key] = validate_digest(value, name=key)
            except ValueError:
                hashes[key] = value
        elif _SHA256_RE.fullmatch(value):
            hashes[key] = normalize_sha256(value, name=key)
        else:
            hashes[key] = value
    return MappingProxyType(hashes)


def _source_evidence_checksum(
    *,
    identity: LegalIdentity,
    source_url: str,
    text: str,
    row: Mapping[str, Any],
) -> str:
    explicit = _row_provenance_value(
        row,
        ("body_sha256", "content_sha256", "raw_sha256", "content_digest", "source_checksum"),
    )
    if explicit:
        try:
            return normalize_sha256(explicit, name="row source checksum")
        except Exception as exc:
            raise LegacyInputError("row contains an invalid source/provenance SHA-256") from exc
    evidence = {
        "jurisdiction": identity.jurisdiction,
        "legal_id": identity.legal_id,
        "name": _first_text(row, ("sectionName", "name", "section_name")) or None,
        "source_url": source_url,
        "text": text,
    }
    return content_sha256(canonical_json_dumps(evidence))


def _declared_row_transport_sha256(row: Mapping[str, Any]) -> str:
    value = _row_provenance_value(
        row,
        (
            "body_sha256",
            "content_sha256",
            "raw_sha256",
            "content_digest",
            "source_checksum",
        ),
    )
    if not value:
        return ""
    try:
        return normalize_sha256(value, name="row transport SHA-256")
    except ValueError:
        return ""


def _matching_row_transports(
    row: Mapping[str, Any],
    *,
    source_url: str,
    transports: Sequence[VerifiedStateLawTransport],
) -> tuple[VerifiedStateLawTransport, ...]:
    digest = _declared_row_transport_sha256(row)
    if not digest:
        return ()
    # A fragment identifies a provision inside the already-fetched official
    # representation; it is not sent in the HTTP request.  Ignore fragments
    # only, while retaining exact scheme/authority/path/query matching.
    locator = urldefrag(source_url.strip()).url.rstrip("/")
    return tuple(
        item
        for item in transports
        if urldefrag(item.official_url.strip()).url.rstrip("/") == locator
        and item.content_sha256 == digest
    )


def _source_cid(row: Mapping[str, Any], *, evidence_checksum: str) -> str:
    for key in ("source_cid", "ipfs_cid"):
        value = str(row.get(key) or "").strip()
        if value:
            try:
                return validate_digest(value, name=key)
            except ValueError:
                # Preserve the malformed legacy value in event lineage, but do
                # not let it become a durable v2 key.
                continue
    return f"sha256:{evidence_checksum}"


@dataclass(frozen=True, slots=True)
class AdaptedCorpusEvent:
    """One deterministic adapter outcome."""

    source_index: int
    disposition: AdaptationDisposition
    reasons: tuple[str, ...]
    record: CorpusRecord | None = None
    source_evidence_sha256: str | None = None
    legacy_hashes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_index < 0:
            raise LegacyStateLawsAdapterError("source_index must be non-negative")
        if self.disposition is AdaptationDisposition.REJECTED and self.record is not None:
            raise LegacyStateLawsAdapterError("rejected event must not carry a CorpusRecord")
        if self.disposition is not AdaptationDisposition.REJECTED and self.record is None:
            raise LegacyStateLawsAdapterError("admitted/quarantined event requires a CorpusRecord")
        object.__setattr__(self, "legacy_hashes", MappingProxyType(dict(self.legacy_hashes)))


@dataclass(frozen=True, slots=True)
class AdapterCheckpoint:
    """Resume cursor bound to exact input bytes and adapter configuration."""

    input_sha256: str
    configuration_sha256: str
    jurisdiction: str
    next_source_index: int = 0
    admitted_count: int = 0
    quarantined_count: int = 0
    rejected_count: int = 0
    last_entry_cid: str | None = None
    complete: bool = False
    schema_version: str = CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_sha256", normalize_sha256(self.input_sha256, name="input_sha256"))
        object.__setattr__(
            self,
            "configuration_sha256",
            normalize_sha256(self.configuration_sha256, name="configuration_sha256"),
        )
        object.__setattr__(self, "jurisdiction", validate_jurisdiction(self.jurisdiction))
        for name in (
            "next_source_index",
            "admitted_count",
            "quarantined_count",
            "rejected_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise LegacyStateLawsAdapterError(f"{name} must be a non-negative integer")
        if self.schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise LegacyStateLawsAdapterError(
                f"checkpoint schema must be {CHECKPOINT_SCHEMA_VERSION!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_count": self.admitted_count,
            "complete": self.complete,
            "configuration_sha256": self.configuration_sha256,
            "input_sha256": self.input_sha256,
            "jurisdiction": self.jurisdiction,
            "last_entry_cid": self.last_entry_cid,
            "next_source_index": self.next_source_index,
            "quarantined_count": self.quarantined_count,
            "rejected_count": self.rejected_count,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AdapterCheckpoint:
        if not isinstance(value, Mapping):
            raise LegacyStateLawsAdapterError("checkpoint must be a mapping")
        return cls(
            input_sha256=str(value.get("input_sha256") or ""),
            configuration_sha256=str(value.get("configuration_sha256") or ""),
            jurisdiction=str(value.get("jurisdiction") or ""),
            next_source_index=value.get("next_source_index", 0),
            admitted_count=value.get("admitted_count", 0),
            quarantined_count=value.get("quarantined_count", 0),
            rejected_count=value.get("rejected_count", 0),
            last_entry_cid=value.get("last_entry_cid"),
            complete=value.get("complete", False),
            schema_version=str(value.get("schema_version") or ""),
        )

    @classmethod
    def load(cls, path: str | Path) -> AdapterCheckpoint:
        target = Path(path)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LegacyStateLawsAdapterError(f"cannot load adapter checkpoint: {target}") from exc
        return cls.from_mapping(payload)

    def save(self, path: str | Path) -> None:
        """Atomically persist this operational checkpoint."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        body = canonical_json_dumps(self.to_dict()) + "\n"
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)

    def advance(self, event: AdaptedCorpusEvent) -> AdapterCheckpoint:
        """Advance only after the caller has durably handled ``event``."""

        if self.complete:
            raise LegacyStateLawsAdapterError("cannot advance a complete checkpoint")
        if event.source_index != self.next_source_index:
            raise CheckpointMismatchError(
                f"expected source_index={self.next_source_index}, got {event.source_index}"
            )
        admitted = self.admitted_count + (event.disposition is AdaptationDisposition.ADMITTED)
        quarantined = self.quarantined_count + (
            event.disposition is AdaptationDisposition.QUARANTINED
        )
        rejected = self.rejected_count + (event.disposition is AdaptationDisposition.REJECTED)
        last_cid = event.record.entry_cid if event.record is not None else self.last_entry_cid
        return replace(
            self,
            next_source_index=self.next_source_index + 1,
            admitted_count=int(admitted),
            quarantined_count=int(quarantined),
            rejected_count=int(rejected),
            last_entry_cid=last_cid,
        )

    def mark_complete(self) -> AdapterCheckpoint:
        return replace(self, complete=True)


class LegacyStateLawsV2Adapter:
    """Stream one jurisdiction's refresh artifact into v2 corpus records."""

    def __init__(
        self,
        *,
        input_path: str | Path,
        jurisdiction: str,
        release_point: str,
        source_receipt: Mapping[str, Any] | SourceReceiptRecord,
        min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
        parser_version: str = DEFAULT_PARSER_VERSION,
        catalog: OfficialSourceCatalog | None = None,
        receipt_relative_path: str | None = None,
    ) -> None:
        self.jurisdiction = validate_jurisdiction(jurisdiction)
        self.input_path = resolve_refresh_state_input(input_path, self.jurisdiction)
        if self.input_path.is_symlink() or not self.input_path.is_file():
            raise LegacyInputError(
                f"legacy state-law input must be a regular non-symlink file: "
                f"{self.input_path}"
            )
        try:
            input_bytes = self.input_path.read_bytes()
        except OSError as exc:
            raise LegacyInputError(
                f"cannot capture legacy state-law input bytes: {self.input_path}"
            ) from exc
        (
            self._input_snapshot_sha256,
            self._input_snapshot_row_count,
        ) = _legacy_input_bytes_metadata(self.input_path, input_bytes)
        self._input_snapshot_size_bytes = len(input_bytes)
        if isinstance(min_text_chars, bool) or int(min_text_chars) <= 0:
            raise LegacyStateLawsAdapterError("min_text_chars must be a positive integer")
        self.min_text_chars = int(min_text_chars)
        self.parser_version = str(parser_version or "").strip()
        if not self.parser_version:
            raise LegacyStateLawsAdapterError("parser_version must be non-empty")
        self.release_point = str(release_point or "").strip()
        if not self.release_point:
            raise LegacyStateLawsAdapterError("release_point must be an exact non-empty pin")
        self.catalog = catalog or get_official_source_catalog()
        self.catalog_record = self.catalog.get(self.jurisdiction)
        if len(self.catalog_record.code_families) != 1:
            raise LegacyStateLawsAdapterError(
                f"{self.jurisdiction} must have exactly one canonical code family for legacy adaptation"
            )
        self.code_family = self.catalog_record.code_families[0].code_family_id
        self.source_receipt = normalize_source_receipt(
            source_receipt,
            input_path=self.input_path,
            jurisdiction=self.jurisdiction,
            release_point=self.release_point,
            relative_path=receipt_relative_path,
            catalog=self.catalog,
            input_bytes=input_bytes,
        )
        collision_plan = _build_collision_plan(
            self.input_path,
            jurisdiction=self.jurisdiction,
            code_family=self.code_family,
            min_text_chars=self.min_text_chars,
            input_bytes=input_bytes,
        )
        self._collision_granules = collision_plan.by_source_index
        self.collision_plan_sha256 = collision_plan.sha256
        self.collision_group_count = collision_plan.group_count
        self.collision_row_count = len(collision_plan.by_source_index)
        self.collision_strategy_version = COLLISION_STRATEGY_VERSION
        config = {
            "adapter_schema_version": ADAPTER_SCHEMA_VERSION,
            "collision_plan_sha256": self.collision_plan_sha256,
            "collision_strategy_version": self.collision_strategy_version,
            "input_sha256": self.source_receipt.input_sha256,
            "jurisdiction": self.jurisdiction,
            "min_text_chars": self.min_text_chars,
            "parser_version": self.parser_version,
            "release_point": self.release_point,
            "source_receipt": self.source_receipt.record.to_dict(),
        }
        self.configuration_sha256 = content_sha256(canonical_json_dumps(config))

    def _assert_input_path_unchanged(self) -> None:
        """Reject any durable path swap without retaining canonical bytes."""

        if self.input_path.is_symlink() or not self.input_path.is_file():
            raise LegacyInputError(
                f"legacy state-law input path changed after adapter preflight: "
                f"{self.input_path}"
            )
        try:
            size, digest = file_digest(self.input_path)
        except (OSError, TypeError, ValueError) as exc:
            raise LegacyInputError(
                f"cannot reverify legacy state-law input: {self.input_path}"
            ) from exc
        if (
            size != self._input_snapshot_size_bytes
            or digest.hex() != self._input_snapshot_sha256
        ):
            raise LegacyInputError(
                "legacy state-law input bytes changed after adapter preflight: "
                f"{self.input_path}"
            )

    def _iteration_input_bytes(self) -> bytes:
        """Capture and verify only this jurisdiction's streaming snapshot."""

        if self.input_path.is_symlink() or not self.input_path.is_file():
            raise LegacyInputError(
                f"legacy state-law input path changed after adapter preflight: "
                f"{self.input_path}"
            )
        try:
            current = self.input_path.read_bytes()
        except OSError as exc:
            raise LegacyInputError(
                f"cannot capture legacy state-law iteration input: {self.input_path}"
            ) from exc
        if (
            len(current) != self._input_snapshot_size_bytes
            or hashlib.sha256(current).hexdigest() != self._input_snapshot_sha256
        ):
            raise LegacyInputError(
                "legacy state-law input bytes changed after adapter preflight: "
                f"{self.input_path}"
            )
        return current

    def new_checkpoint(self) -> AdapterCheckpoint:
        return AdapterCheckpoint(
            input_sha256=self.source_receipt.input_sha256,
            configuration_sha256=self.configuration_sha256,
            jurisdiction=self.jurisdiction,
        )

    def validate_checkpoint(self, checkpoint: AdapterCheckpoint) -> None:
        mismatches: list[str] = []
        if checkpoint.jurisdiction != self.jurisdiction:
            mismatches.append("jurisdiction")
        if checkpoint.input_sha256 != self.source_receipt.input_sha256:
            mismatches.append("input_sha256")
        if checkpoint.configuration_sha256 != self.configuration_sha256:
            mismatches.append("configuration_sha256")
        if mismatches:
            raise CheckpointMismatchError(
                f"checkpoint does not match adapter: {', '.join(mismatches)}"
            )

    def finalize_checkpoint(self, checkpoint: AdapterCheckpoint) -> AdapterCheckpoint:
        """Close a fully consumed candidate only after count/disposition parity.

        A publication-capable receipt must produce exactly its declared
        canonical row count with no rejected or quarantined rows.  A receipt
        that was already ineligible may finish as a quarantine/recovery import,
        but it can never contain admitted rows.
        """

        self._assert_input_path_unchanged()
        self.validate_checkpoint(checkpoint)
        if checkpoint.complete:
            return checkpoint
        expected_physical = self.source_receipt.input_row_count
        if checkpoint.next_source_index != expected_physical:
            raise LegacyInputError(
                "cannot finalize partially consumed adapter input: "
                f"cursor={checkpoint.next_source_index} rows={expected_physical}"
            )
        if self.source_receipt.admission_eligible:
            expected_admitted = self.source_receipt.expected_row_count
            if expected_admitted is None:
                raise LegacyInputError("eligible receipt lacks canonical row count")
            if (
                checkpoint.admitted_count != expected_admitted
                or checkpoint.quarantined_count != 0
                or checkpoint.rejected_count != 0
            ):
                raise LegacyInputError(
                    "eligible receipt does not reconcile with adapter outcomes: "
                    f"expected_admitted={expected_admitted} "
                    f"admitted={checkpoint.admitted_count} "
                    f"quarantined={checkpoint.quarantined_count} "
                    f"rejected={checkpoint.rejected_count}"
                )
        elif checkpoint.admitted_count != 0:
            raise LegacyInputError(
                "ineligible receipt produced admitted rows; refusing checkpoint closure"
            )
        return checkpoint.mark_complete()

    def _reject(
        self,
        source_index: int,
        row: Mapping[str, Any],
        reasons: Sequence[str],
    ) -> AdaptedCorpusEvent:
        return AdaptedCorpusEvent(
            source_index=source_index,
            disposition=AdaptationDisposition.REJECTED,
            reasons=tuple(dict.fromkeys(str(item) for item in reasons if str(item))),
            record=None,
            legacy_hashes=_legacy_hashes(row),
        )

    def adapt_row(self, row: Mapping[str, Any], *, source_index: int) -> AdaptedCorpusEvent:
        """Normalize one row; invalid data is a rejected event, never fabricated."""

        if not isinstance(row, Mapping):
            return self._reject(source_index, {}, ("source_row_not_mapping",))
        merged = _merge_legacy_row(row)
        parse_error = str(merged.get("_adapter_parse_error") or "").strip()
        if parse_error:
            return self._reject(source_index, merged, (parse_error,))

        raw_code = str(
            merged.get("jurisdiction") or merged.get("stateCode") or merged.get("state_code") or ""
        ).strip().upper()
        if raw_code and raw_code != self.jurisdiction:
            return self._reject(
                source_index,
                merged,
                (f"jurisdiction_mismatch:{raw_code}",),
            )

        text = _row_text(merged)
        source_url = _row_source_url(merged)
        fixture_reasons = _fixture_reasons(
            merged,
            input_path=self.input_path,
            text=text,
            source_url=source_url,
        )
        if fixture_reasons:
            return self._reject(source_index, merged, fixture_reasons)
        if not text:
            return self._reject(source_index, merged, ("empty_statute_body",))
        quality = assess_text_quality(text, min_usable_chars=self.min_text_chars)
        if quality.contaminated:
            return self._reject(
                source_index,
                merged,
                tuple(f"text_quality:{reason}" for reason in quality.reasons),
            )
        if not _valid_http_url(source_url):
            return self._reject(source_index, merged, ("missing_or_invalid_source_url",))
        if _is_example_host(_host(source_url)):
            return self._reject(source_index, merged, ("reserved_example_source_url",))
        if not _section_value(merged):
            return self._reject(source_index, merged, ("missing_section_identifier",))

        try:
            explicit_relations = _explicit_relation_arrays(merged)
        except LegacyInputError as exc:
            return self._reject(
                source_index,
                merged,
                (f"explicit_relation_invalid:{exc}",),
            )

        try:
            identity = _identity_for_row(
                merged,
                jurisdiction=self.jurisdiction,
                code_family=self.code_family,
            )
            planned_granule = self._collision_granules.get(source_index)
            if planned_granule is not None:
                if (
                    str(merged.get("legal_id") or "").strip()
                    or identity.granule is not None
                ):
                    raise LegacyInputError(
                        "collision plan attempted to alter an explicit legal identity"
                    )
                identity = replace(identity, granule=planned_granule)
            evidence_checksum = _source_evidence_checksum(
                identity=identity,
                source_url=source_url,
                text=text,
                row=merged,
            )
            source_cid = _source_cid(merged, evidence_checksum=evidence_checksum)
        except ValueError as exc:
            return self._reject(
                source_index,
                merged,
                (f"identity_or_hash_invalid:{type(exc).__name__}",),
            )

        quarantine: list[str] = list(self.source_receipt.qualification_reasons)
        trusted_receipt_transports = (
            self.source_receipt.verified_transport_receipts
            if self.source_receipt.admission_eligible
            else ()
        )
        (
            row_verified_transports,
            row_transport_receipt_errors,
            had_row_transport_receipt,
        ) = _verify_transport_receipts(merged)
        row_transport_receipt_errors = list(row_transport_receipt_errors)
        receipt_content_hashes = frozenset(self.source_receipt.record.content_hashes)
        for item in row_verified_transports:
            if item.content_sha256 not in receipt_content_hashes:
                row_transport_receipt_errors.append(
                    "transport_receipt:content_sha256_not_in_source_receipt_hashes"
                )
        row_transport_receipt_errors = list(dict.fromkeys(row_transport_receipt_errors))
        quarantine.extend(
            f"row_transport:{item}" for item in row_transport_receipt_errors
        )
        trusted_row_transports = (
            row_verified_transports
            if self.source_receipt.admission_eligible
            and had_row_transport_receipt
            and not row_transport_receipt_errors
            else ()
        )
        trusted_transports = tuple(
            dict.fromkeys((*trusted_receipt_transports, *trusted_row_transports))
        )
        matching_transports = _matching_row_transports(
            merged,
            source_url=source_url,
            transports=trusted_transports,
        )
        if (
            self.source_receipt.requires_verified_transport_binding
            and not matching_transports
        ):
            quarantine.append("row_transport:missing_verified_official_byte_binding")
        row_markers = _provenance_markers(
            merged,
            source_url=source_url,
            verified_transports=matching_transports,
        )
        quarantine.extend(f"row_transport:{marker}" for marker in row_markers)
        authority = _row_provenance_value(
            merged, ("source_authority_class", "authority_class")
        ).lower()
        if authority and authority != SourceAuthorityClass.OFFICIAL.value:
            quarantine.append(f"row_authority_not_official:{authority}")
        host = _host(source_url)
        if is_secondary_host(host):
            quarantine.append(f"secondary_source_host:{host}")
        try:
            decision = evaluate_admission(
                AdmissionRequest(
                    postal_code=self.jurisdiction,
                    acquisition_path_ids=self.source_receipt.acquisition_path_ids,
                    release_point=self.release_point,
                    source_url=source_url,
                ),
                catalog=self.catalog,
            )
            if not decision.admitted:
                quarantine.append("row_source_policy_not_admitted")
        except ValueError as exc:
            quarantine.append(f"row_source_policy:{type(exc).__name__}")

        is_admitted = not quarantine and self.source_receipt.admission_eligible
        if is_admitted:
            status = AdmissionStatus.ADMITTED
            reason = "verified full-frontier official refresh artifact normalized by legacy v2 adapter"
            source_authority = SourceAuthorityClass.OFFICIAL
            verification = VerificationResult.VERIFIED
            disposition = AdaptationDisposition.ADMITTED
        else:
            status = AdmissionStatus.QUARANTINED
            quarantine = list(dict.fromkeys(quarantine or ["receipt_not_admission_eligible"]))
            reason = "quarantined by legacy v2 adapter: " + "; ".join(quarantine)
            source_authority = (
                SourceAuthorityClass.SECONDARY
                if is_secondary_host(host)
                else SourceAuthorityClass.UNKNOWN
            )
            verification = (
                VerificationResult.CONFLICT
                if self.source_receipt.record.verification_result is VerificationResult.CONFLICT
                else VerificationResult.UNVERIFIED
            )
            disposition = AdaptationDisposition.QUARANTINED

        entry_material = {
            "legal_id": identity.legal_id,
            "source_checksum": evidence_checksum,
            "source_cid": source_cid,
            "source_url": source_url,
            "text": text,
        }
        if any(explicit_relations.values()):
            entry_material["explicit_relations"] = {
                name: list(explicit_relations[name])
                for name in EXPLICIT_RELATION_FIELDS
                if explicit_relations[name]
            }
        entry_cid = f"sha256:{content_sha256(canonical_json_dumps(entry_material))}"
        row_parser_version = _first_text(merged, ("parser_version", "scraper_version"))
        parser_version = row_parser_version or self.parser_version
        acquisition_time = self.source_receipt.record.observation_time
        try:
            record = CorpusRecord(
                entry_cid=entry_cid,
                legal_id=identity.legal_id,
                source_cid=source_cid,
                jurisdiction=self.jurisdiction,
                code_family=self.code_family,
                section=identity.section,
                admission_status=status,
                admission_reason=reason,
                release_point=self.release_point,
                source_checksum=evidence_checksum,
                verification_result=verification,
                acquisition_time=acquisition_time,
                official_source_url=source_url,
                acquisition_receipt_id=self.source_receipt.record.receipt_id,
                parser_version=parser_version,
                text=text,
                title=identity.title,
                chapter=identity.chapter,
                subsection=identity.subsection,
                document_index=source_index,
                source_authority_class=source_authority,
                edition_as_of=identity.edition,
                effective_date=_first_text(merged, ("effective_date", "dateEffective")) or None,
                observed_at=acquisition_time,
                parent_path=identity.path,
                public_laws=explicit_relations["public_laws"],
                cites=explicit_relations["cites"],
                amends=explicit_relations["amends"],
                repeals=explicit_relations["repeals"],
                transfers=explicit_relations["transfers"],
            )
        except ValueError as exc:
            return self._reject(
                source_index,
                merged,
                (f"v2_schema_rejected:{type(exc).__name__}",),
            )
        return AdaptedCorpusEvent(
            source_index=source_index,
            disposition=disposition,
            reasons=() if is_admitted else tuple(quarantine),
            record=record,
            source_evidence_sha256=evidence_checksum,
            legacy_hashes=_legacy_hashes(merged),
        )

    def iter_events(
        self,
        *,
        checkpoint: AdapterCheckpoint | None = None,
    ) -> Iterator[AdaptedCorpusEvent]:
        """Stream events from the beginning or from a validated checkpoint."""

        input_bytes = self._iteration_input_bytes()
        start_index = 0
        if checkpoint is not None:
            self.validate_checkpoint(checkpoint)
            if checkpoint.complete:
                return
            start_index = checkpoint.next_source_index
        for source_index, row in _legacy_rows_from_bytes(
            self.input_path,
            input_bytes,
            start_index=start_index,
        ):
            yield self.adapt_row(row, source_index=source_index)
        self._assert_input_path_unchanged()


__all__ = [
    "ADAPTER_SCHEMA_VERSION",
    "CHECKPOINT_SCHEMA_VERSION",
    "COLLISION_STRATEGY_VERSION",
    "DEFAULT_MIN_TEXT_CHARS",
    "DEFAULT_PARSER_VERSION",
    "AdaptationDisposition",
    "AdaptedCorpusEvent",
    "AdapterCheckpoint",
    "CheckpointMismatchError",
    "LegacyInputError",
    "LegacyReceiptError",
    "LegacyStateLawsAdapterError",
    "LegacyStateLawsV2Adapter",
    "NormalizedSourceReceipt",
    "file_sha256",
    "legacy_input_row_count",
    "normalize_source_receipt",
    "resolve_refresh_state_input",
]
