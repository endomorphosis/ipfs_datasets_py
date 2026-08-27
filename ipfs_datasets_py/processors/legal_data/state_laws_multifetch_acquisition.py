"""Prospective multi-fetch acquisition evidence for state-law parsers.

One state corpus is normally assembled from many official HTTP responses.  A
single-response receipt therefore cannot truthfully prove the canonical
JSON-LD artifact.  This module keeps those identities separate while reusing
the existing legal-acquisition contracts:

* every response admitted to a parser is wrapped by
  :class:`AcquisitionReceipt`, :class:`AcquisitionOutcome`, and
  :class:`ParserInputEnvelope`;
* exact response bodies are retained in a content-addressed object store;
* direct/archive/cache provenance is verified by the shared state transport
  verifier (a cache entry is unusable without its original transport receipt);
* a closed jurisdiction receipt hashes retained request and response *ledgers*,
  rather than pretending that one response body equals the whole corpus; and
* the aggregate separately binds the exact canonical JSON-LD SHA-256 and row
  count before passing the shared byte, frontier, completeness, and source
  receipt normalizers.

This is a projection/retention seam, not a downloader or parser.  It performs
no network I/O and cannot reconstruct evidence that an older checkpoint did
not retain.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urldefrag, urlparse

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    ByteVerification,
    FrontierVerification,
    verify_receipt_bytes,
    verify_receipt_frontier,
)
from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    AcquisitionOutcome,
    AcquisitionOutcomeKind,
    AcquisitionReceipt,
    ContentAddress,
    ParserInputEnvelope,
    canonical_json_bytes,
    content_address_bytes,
    content_address_mapping,
)
from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (
    evaluate_jurisdiction_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    NormalizedSourceReceipt,
    file_sha256,
    legacy_input_row_count,
    normalize_source_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    validate_jurisdiction,
)
from ipfs_datasets_py.processors.legal_data.state_laws_run_seal import (
    PENDING_NORMALIZED_RECEIPT_SUFFIX,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_policy import (
    OfficialSourceCatalog,
)
from ipfs_datasets_py.processors.legal_data.state_laws_source_provenance import (
    VerifiedStateLawTransport,
    canonicalize_state_law_transport_receipt,
    verify_state_law_transport_receipt,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import atomic_write_bytes

SCHEMA_VERSION: Final = "state-laws-multifetch-acquisition-v1"
REQUEST_LEDGER_SCHEMA: Final = "state-laws-multifetch-request-ledger-v1"
RESPONSE_LEDGER_SCHEMA: Final = "state-laws-multifetch-response-ledger-v1"
FRONTIER_AGGREGATE_SCHEMA: Final = "state-laws-multifetch-frontier-aggregate-v1"
CLOSURE_INPUT_SCHEMA: Final = "state-laws-multifetch-closure-input-v1"
CLOSURE_INPUT_FILENAME: Final = "source-frontier-closure-input.json"
CLOSURE_INPUTS_DIRNAME: Final = "closure-inputs"
CANONICAL_OUTPUT_PROJECTION_SCHEMA: Final = (
    "state-laws-canonical-output-projection-v1"
)

# Explicit fences: historical materialization/checkpoint claims do not become
# source evidence merely because this module can hash their output bytes.
AUTHORIZES_LEGACY_CHECKPOINTS: Final = False
AUTHORIZES_REMATERIALIZATION_RECEIPTS: Final = False
REQUIRES_PROSPECTIVE_PARSER_INPUT_RECEIPTS: Final = True


class StateLawMultiFetchAcquisitionError(ValueError):
    """A parser input or jurisdiction aggregate lacks exact retained proof."""


class StateLawRetainedReplayOnlyError(StateLawMultiFetchAcquisitionError):
    """A retained-replay-only run cannot satisfy an exact parser request."""


@dataclass(frozen=True, slots=True)
class RetainedStateLawParserInput:
    """One parser-admitted body and its immutable on-disk evidence."""

    envelope: ParserInputEnvelope
    transport: VerifiedStateLawTransport
    transport_receipt: Mapping[str, Any]
    body_path: Path
    evidence_path: Path

    @property
    def receipt(self) -> AcquisitionReceipt:
        return self.envelope.acquisition.receipt

    def to_ledger_dict(self, *, jurisdiction_root: Path) -> dict[str, Any]:
        return {
            "acquisition_receipt_cid": self.receipt.receipt_cid,
            "acquisition_receipt_sha256": self.receipt.receipt_sha256,
            "body_relative_path": self.body_path.relative_to(
                jurisdiction_root
            ).as_posix(),
            "content": self.receipt.content.to_dict()
            if self.receipt.content is not None
            else None,
            "endpoint": self.receipt.endpoint,
            "outcome_kind": self.envelope.acquisition.kind.value,
            "response_status": self.receipt.response_status,
            "transport_receipt": dict(self.transport_receipt),
        }


@dataclass(frozen=True, slots=True)
class ClosedStateLawMultiFetchFrontier:
    """Verified jurisdiction aggregate bound to one canonical JSON-LD file."""

    receipt: Mapping[str, Any]
    normalized_source_receipt: NormalizedSourceReceipt
    byte_verification: ByteVerification
    frontier_verification: FrontierVerification
    receipt_path: Path
    normalized_receipt_path: Path
    request_ledger_path: Path
    response_ledger_path: Path


def _utc_now() -> datetime:
    # Preserve event precision so two same-body fetches in one second do not
    # collapse to a single acquisition-receipt identity.
    return datetime.now(UTC)


def _json_mapping_copy(value: Mapping[str, Any], *, name: str) -> dict[str, Any]:
    """Return a deterministic JSON-safe copy or reject opaque local objects."""

    if not isinstance(value, Mapping):
        raise StateLawMultiFetchAcquisitionError(f"{name} must be a mapping")
    try:
        projected = json.loads(canonical_json_bytes(value).decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StateLawMultiFetchAcquisitionError(
            f"{name} must contain only deterministic JSON values"
        ) from exc
    if not isinstance(projected, dict):
        raise StateLawMultiFetchAcquisitionError(f"{name} must be a JSON object")
    return projected


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError) as exc:
        raise StateLawMultiFetchAcquisitionError(
            "retained evidence path escaped its jurisdiction root"
        ) from exc


def _resolve_retained_path(root: Path, relative: object, *, name: str) -> Path:
    raw = str(relative or "").strip()
    if not raw or Path(raw).is_absolute():
        raise StateLawMultiFetchAcquisitionError(
            f"{name} must be a non-empty relative retained-evidence path"
        )
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise StateLawMultiFetchAcquisitionError(
            f"{name} escaped its jurisdiction root"
        ) from exc
    if candidate.is_symlink():
        raise StateLawMultiFetchAcquisitionError(f"{name} must not be a symlink")
    return candidate


def _content_address_file(path: Path) -> ContentAddress:
    """Content-address a regular file without materializing it in memory."""

    target = Path(path)
    if target.is_symlink() or not target.is_file():
        raise StateLawMultiFetchAcquisitionError(
            "file-backed parser input must be a regular non-symlink file"
        )
    digest = hashlib.sha256()
    byte_size = 0
    try:
        with target.open("rb") as handle:
            while True:
                block = handle.read(8 * 1024 * 1024)
                if not block:
                    break
                digest.update(block)
                byte_size += len(block)
    except OSError as exc:
        raise StateLawMultiFetchAcquisitionError(
            "file-backed parser input could not be hashed"
        ) from exc
    sha256 = digest.hexdigest()
    return ContentAddress(
        sha256=sha256,
        cid=f"sha256:{sha256}",
        byte_size=byte_size,
    )


def _frontier_material(value: Mapping[str, Any], *, name: str) -> dict[str, Any]:
    material = _json_mapping_copy(value, name=name)
    material.pop("frontier_digest_sha256", None)
    return material


def _reported_int(value: object, *, name: str) -> int:
    if isinstance(value, bool):
        raise StateLawMultiFetchAcquisitionError(f"{name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise StateLawMultiFetchAcquisitionError(
            f"{name} must be an integer"
        ) from exc
    if result < 0:
        raise StateLawMultiFetchAcquisitionError(f"{name} must be non-negative")
    return result


def _canonical_output_projection_from_keys(
    canonical_keys: Sequence[str],
    *,
    jurisdiction: str,
) -> dict[str, Any]:
    code = validate_jurisdiction(jurisdiction)
    keys = [str(item).strip() for item in canonical_keys]
    if not keys or any(not item for item in keys):
        raise StateLawMultiFetchAcquisitionError(
            "canonical output projection requires non-empty identities"
        )
    if len(keys) != len(set(keys)):
        raise StateLawMultiFetchAcquisitionError(
            "canonical output identities must be unique"
        )
    keys_address = content_address_mapping(
        {
            "canonical_keys": keys,
            "jurisdiction": code,
        }
    )
    return {
        "canonical_keys": keys,
        "canonical_keys_sha256": keys_address.sha256,
        "canonical_row_count": len(keys),
        "jurisdiction": code,
        "schema_version": CANONICAL_OUTPUT_PROJECTION_SCHEMA,
    }


def _jsonld_identity(payload: Mapping[str, Any]) -> str:
    for key in (
        "@id",
        "identifier",
        "legislationIdentifier",
        "sectionNumber",
        "source_id",
        "sourceUrl",
        "url",
        "sameAs",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalized_row_jsonld_identity(row: Mapping[str, Any]) -> str:
    for container_name in ("structured_data", "structuredData"):
        structured = row.get(container_name)
        if not isinstance(structured, Mapping):
            continue
        payload = structured.get("jsonld")
        if isinstance(payload, Mapping):
            identity = _jsonld_identity(payload)
            if identity:
                return identity
    identity = _jsonld_identity(row)
    if identity:
        return identity
    return str(row.get("statute_id") or "").strip()


def build_canonical_state_law_output_projection(
    rows: Sequence[Mapping[str, Any] | Any],
    *,
    jurisdiction: str,
) -> dict[str, Any]:
    """Bind a full run to its exact final normalized row identities.

    This projection is deliberately downstream of hydration and quality
    filtering.  It says nothing about whether the official source frontier is
    complete; that remains the job of the independently observed completion
    receipt and replay.  In particular, catalog/title counts are never
    accepted as substitutes for the final section identities below.
    """

    code = validate_jurisdiction(jurisdiction)
    canonical_keys: list[str] = []
    for position, value in enumerate(rows):
        if isinstance(value, Mapping):
            row = value
        elif hasattr(value, "to_dict"):
            projected = value.to_dict()
            row = projected if isinstance(projected, Mapping) else {}
        else:
            row = {}
        row_code = str(
            row.get("state_code") or row.get("stateCode") or code
        ).strip().upper()
        if row_code != code:
            raise StateLawMultiFetchAcquisitionError(
                f"canonical output row {position} belongs to {row_code!r}, not {code!r}"
            )
        key = _normalized_row_jsonld_identity(row)
        if not key:
            raise StateLawMultiFetchAcquisitionError(
                f"canonical output row {position} lacks a JSON-LD identity"
            )
        canonical_keys.append(key)
    return _canonical_output_projection_from_keys(
        canonical_keys,
        jurisdiction=code,
    )


def build_canonical_state_law_jsonld_output_projection(
    path: str | Path,
    *,
    jurisdiction: str,
) -> dict[str, Any]:
    """Replay the exact identities emitted by the canonical JSON-LD writer."""

    code = validate_jurisdiction(jurisdiction)
    target = Path(path).expanduser()
    if target.is_symlink():
        raise StateLawMultiFetchAcquisitionError(
            "canonical JSON-LD projection input must not be a symlink"
        )
    target = target.resolve()
    keys: list[str] = []
    try:
        with target.open("r", encoding="utf-8", errors="strict") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, Mapping):
                    raise StateLawMultiFetchAcquisitionError(
                        f"canonical JSON-LD line {line_number} is not an object"
                    )
                row_code = str(payload.get("stateCode") or "").strip().upper()
                if row_code and row_code != code:
                    raise StateLawMultiFetchAcquisitionError(
                        f"canonical JSON-LD line {line_number} belongs to {row_code!r}, not {code!r}"
                    )
                identity = _jsonld_identity(payload)
                if not identity:
                    raise StateLawMultiFetchAcquisitionError(
                        f"canonical JSON-LD line {line_number} lacks a stable identity"
                    )
                keys.append(identity)
    except StateLawMultiFetchAcquisitionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StateLawMultiFetchAcquisitionError(
            "canonical JSON-LD cannot be replayed for output identity"
        ) from exc
    return _canonical_output_projection_from_keys(keys, jurisdiction=code)


def _validate_canonical_output_projection(
    value: Mapping[str, Any],
    *,
    jurisdiction: str,
) -> dict[str, Any]:
    projected = _json_mapping_copy(value, name="canonical_output_projection")
    code = validate_jurisdiction(jurisdiction)
    if projected.get("schema_version") != CANONICAL_OUTPUT_PROJECTION_SCHEMA:
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_projection has the wrong schema"
        )
    if str(projected.get("jurisdiction") or "").strip().upper() != code:
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_projection jurisdiction does not match the ledger"
        )
    raw_keys = projected.get("canonical_keys")
    if not isinstance(raw_keys, Sequence) or isinstance(
        raw_keys, (str, bytes, bytearray)
    ):
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_projection canonical_keys must be a sequence"
        )
    keys = [str(item).strip() for item in raw_keys]
    if not keys or any(not item for item in keys):
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_projection requires non-empty canonical_keys"
        )
    if len(keys) != len(set(keys)):
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_projection canonical_keys must be unique"
        )
    row_count = _reported_int(
        projected.get("canonical_row_count"),
        name="canonical_output_projection canonical_row_count",
    )
    if row_count != len(keys):
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_projection row count does not match canonical_keys"
        )
    expected_digest = content_address_mapping(
        {"canonical_keys": keys, "jurisdiction": code}
    ).sha256
    if str(projected.get("canonical_keys_sha256") or "").strip().lower() != expected_digest:
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_projection canonical_keys digest does not replay"
        )
    return {
        "canonical_keys": keys,
        "canonical_keys_sha256": expected_digest,
        "canonical_row_count": row_count,
        "jurisdiction": code,
        "schema_version": CANONICAL_OUTPUT_PROJECTION_SCHEMA,
    }


def _compact_canonical_output_binding(
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "canonical_keys_sha256": str(projection["canonical_keys_sha256"]),
        "canonical_row_count": int(projection["canonical_row_count"]),
        "jurisdiction": str(projection["jurisdiction"]),
        "schema_version": CANONICAL_OUTPUT_PROJECTION_SCHEMA,
    }


def _validate_compact_canonical_output_binding(
    value: Mapping[str, Any],
    *,
    jurisdiction: str,
) -> dict[str, Any]:
    binding = _json_mapping_copy(value, name="canonical_output_binding")
    code = validate_jurisdiction(jurisdiction)
    if binding.get("schema_version") != CANONICAL_OUTPUT_PROJECTION_SCHEMA:
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_binding has the wrong schema"
        )
    if str(binding.get("jurisdiction") or "").strip().upper() != code:
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_binding jurisdiction does not match the ledger"
        )
    row_count = _reported_int(
        binding.get("canonical_row_count"),
        name="canonical_output_binding canonical_row_count",
    )
    if row_count <= 0:
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_binding row count must be positive"
        )
    digest = str(binding.get("canonical_keys_sha256") or "").strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_binding canonical_keys_sha256 must be exact"
        )
    if "canonical_keys" in binding:
        raise StateLawMultiFetchAcquisitionError(
            "canonical_output_binding must not duplicate the completion key list"
        )
    return {
        "canonical_keys_sha256": digest,
        "canonical_row_count": row_count,
        "jurisdiction": code,
        "schema_version": CANONICAL_OUTPUT_PROJECTION_SCHEMA,
    }


def _validate_completion_output_binding(
    completion: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> None:
    expected_count = int(projection["canonical_row_count"])
    reported_count = _reported_int(
        completion.get("canonical_row_count", completion.get("row_count")),
        name="completion receipt canonical_row_count",
    )
    if reported_count != expected_count:
        raise StateLawMultiFetchAcquisitionError(
            "completion receipt row count does not match the final canonical output projection"
        )
    disposition = completion.get("disposition")
    if not isinstance(disposition, Mapping):
        raise StateLawMultiFetchAcquisitionError(
            "completion receipt lacks disposition reconciliation"
        )
    fetched = _reported_int(
        disposition.get("fetched"),
        name="completion receipt disposition.fetched",
    )
    if fetched != expected_count:
        raise StateLawMultiFetchAcquisitionError(
            "completion receipt disposition.fetched does not match final canonical rows"
        )
    index_keys = completion.get("index_keys")
    if not isinstance(index_keys, Mapping):
        raise StateLawMultiFetchAcquisitionError(
            "completion receipt lacks index_keys parity evidence"
        )
    expected_keys = list(projection["canonical_keys"])

    def _key_list(name: str) -> list[str]:
        raw = index_keys.get(name)
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
            raise StateLawMultiFetchAcquisitionError(
                f"completion receipt index_keys.{name} must be a sequence"
            )
        keys = [str(item).strip() for item in raw]
        if any(not item for item in keys) or len(keys) != len(set(keys)):
            raise StateLawMultiFetchAcquisitionError(
                f"completion receipt index_keys.{name} must contain unique identities"
            )
        return keys

    if _key_list("canonical_keys") != expected_keys:
        raise StateLawMultiFetchAcquisitionError(
            "completion receipt canonical_keys do not match final canonical rows"
        )
    if _key_list("derived_keys") != expected_keys:
        raise StateLawMultiFetchAcquisitionError(
            "completion receipt derived_keys do not match final canonical rows"
        )
    if _key_list("stale_keys"):
        raise StateLawMultiFetchAcquisitionError(
            "completion receipt contains stale derived keys"
        )
    if index_keys.get("parity_ok") is not True:
        raise StateLawMultiFetchAcquisitionError(
            "completion receipt index key parity is not explicitly true"
        )


class StateLawMultiFetchAcquisitionLedger:
    """Content-address and retain every response admitted to a state parser.

    The ledger is deliberately opt-in.  Attaching it to
    ``BaseStateScraper`` makes the shared fetch path fail closed if a response
    lacks exact direct/archive/cache origin evidence.  Existing immutable
    entries are replayed on construction, which allows safe process restart
    without accepting old unbound page-cache metadata.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        jurisdiction: str,
        parser_name: str,
        load_existing: bool = True,
        retained_replay_only: bool = False,
    ) -> None:
        if not isinstance(retained_replay_only, bool):
            raise TypeError("retained_replay_only must be a boolean")
        self.jurisdiction = validate_jurisdiction(jurisdiction)
        self.parser_name = str(parser_name or "").strip()
        if not self.parser_name:
            raise StateLawMultiFetchAcquisitionError(
                "parser_name must be a non-empty string"
            )
        unresolved_root = Path(root).expanduser()
        if unresolved_root.is_symlink():
            raise StateLawMultiFetchAcquisitionError(
                "acquisition ledger root must not be a symlink"
            )
        self.root = unresolved_root.resolve()
        self.jurisdiction_root = self.root / self.jurisdiction
        if self.jurisdiction_root.is_symlink():
            raise StateLawMultiFetchAcquisitionError(
                "jurisdiction acquisition root must not be a symlink"
            )
        self.objects_dir = self.jurisdiction_root / "objects"
        self.fetches_dir = self.jurisdiction_root / "fetches"
        self.ledgers_dir = self.jurisdiction_root / "ledgers"
        self.frontiers_dir = self.jurisdiction_root / "frontiers"
        for directory in (
            self.objects_dir,
            self.fetches_dir,
            self.ledgers_dir,
            self.frontiers_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
            if directory.is_symlink():
                raise StateLawMultiFetchAcquisitionError(
                    "acquisition evidence directories must not be symlinks"
                )
        self._lock = threading.RLock()
        self._entries: dict[str, RetainedStateLawParserInput] = {}
        self._request_index: dict[tuple[str, bytes], list[str]] = {}
        self.retained_replay_only = retained_replay_only
        if load_existing:
            self._load_existing_entries()

    @property
    def entries(self) -> tuple[RetainedStateLawParserInput, ...]:
        """Return immutable entries in deterministic receipt order."""

        with self._lock:
            return tuple(self._entries[key] for key in sorted(self._entries))

    @staticmethod
    def _retained_request_identity(
        *,
        official_url: str,
        sanitized_request: Mapping[str, Any],
    ) -> tuple[str, bytes]:
        endpoint = urldefrag(str(official_url or "").strip())[0]
        if not endpoint:
            raise StateLawMultiFetchAcquisitionError(
                "retained parser-input replay requires an official URL"
            )
        request_payload = _json_mapping_copy(
            sanitized_request,
            name="sanitized_request",
        )
        return endpoint, canonical_json_bytes(request_payload)

    def _index_retained_entry_locked(
        self,
        receipt_sha: str,
        retained: RetainedStateLawParserInput,
    ) -> None:
        receipt = retained.receipt
        identity = self._retained_request_identity(
            official_url=receipt.endpoint,
            sanitized_request=receipt.sanitized_request,
        )
        receipt_ids = self._request_index.setdefault(identity, [])
        if receipt_sha not in receipt_ids:
            receipt_ids.append(receipt_sha)
            receipt_ids.sort()

    def _matching_retained_parser_inputs(
        self,
        *,
        official_url: str,
        sanitized_request: Mapping[str, Any],
    ) -> list[RetainedStateLawParserInput]:
        identity = self._retained_request_identity(
            official_url=official_url,
            sanitized_request=sanitized_request,
        )
        with self._lock:
            receipt_ids = tuple(self._request_index.get(identity, ()))
            return [self._entries[receipt_sha] for receipt_sha in receipt_ids]

    @staticmethod
    def _verify_retained_byte_replay(
        matches: Sequence[RetainedStateLawParserInput],
    ) -> RetainedStateLawParserInput:
        content_digests = {
            str(item.receipt.content.sha256)
            for item in matches
            if item.receipt.content is not None
        }
        if len(content_digests) != 1:
            raise StateLawMultiFetchAcquisitionError(
                "retained parser-input replay is ambiguous for this request"
            )
        retained = matches[0]
        if retained.body_path.is_symlink() or not retained.body_path.is_file():
            raise StateLawMultiFetchAcquisitionError(
                "retained parser-input replay body is not a regular file"
            )
        body = retained.body_path.read_bytes()
        expected = retained.receipt.content
        if expected is None or content_address_bytes(body) != expected:
            raise StateLawMultiFetchAcquisitionError(
                "retained parser-input replay body failed fixity verification"
            )
        if retained.envelope.body is None:
            raise StateLawMultiFetchAcquisitionError(
                "file-backed parser inputs cannot be replayed through the byte adapter"
            )
        if bytes(retained.envelope.body) != body:
            raise StateLawMultiFetchAcquisitionError(
                "retained parser-input envelope no longer matches its object"
            )
        return retained

    @property
    def closure_input_path(self) -> Path:
        """Return the legacy singleton frontier-projection path.

        New producers use content-addressed paths beneath
        :attr:`closure_inputs_dir`.  The singleton remains available only for
        explicit replay of previously retained evidence.
        """

        return self.jurisdiction_root / CLOSURE_INPUT_FILENAME

    @property
    def closure_inputs_dir(self) -> Path:
        """Return the directory for immutable content-addressed projections."""

        return self.frontiers_dir / CLOSURE_INPUTS_DIRNAME

    def resolve_frontier_closure_projection_path(
        self,
        value: str | Path,
        *,
        allow_legacy_singleton: bool = False,
    ) -> Path:
        """Resolve one explicit, confined, immutable closure-input path.

        Content-addressed projections must live directly beneath
        :attr:`closure_inputs_dir` and their filename must reproduce the
        retained bytes.  The historical singleton is accepted only when the
        caller deliberately opts in; no directory scan or latest-file choice
        can authorize a projection.
        """

        raw = Path(value).expanduser()
        if self.jurisdiction_root.is_symlink() or self.frontiers_dir.is_symlink():
            raise StateLawMultiFetchAcquisitionError(
                "frontier closure input must not traverse a symlink"
            )
        candidate = raw if raw.is_absolute() else self.jurisdiction_root / raw
        lexical_root = self.jurisdiction_root.absolute()
        lexical_candidate = candidate.absolute()
        try:
            relative = lexical_candidate.relative_to(lexical_root)
        except ValueError as exc:
            raise StateLawMultiFetchAcquisitionError(
                "frontier closure input escaped its jurisdiction root"
            ) from exc
        cursor = lexical_root
        for component in relative.parts:
            cursor = cursor / component
            if cursor.is_symlink():
                raise StateLawMultiFetchAcquisitionError(
                    "frontier closure input must not traverse a symlink"
                )
        resolved = lexical_candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.jurisdiction_root.resolve())
        except ValueError as exc:
            raise StateLawMultiFetchAcquisitionError(
                "frontier closure input escaped its jurisdiction root"
            ) from exc

        legacy = self.closure_input_path.resolve(strict=False)
        if resolved == legacy:
            if not allow_legacy_singleton:
                raise StateLawMultiFetchAcquisitionError(
                    "legacy singleton closure input requires explicit opt-in"
                )
        else:
            expected_parent = self.closure_inputs_dir.resolve(strict=False)
            stem = resolved.stem.lower()
            if (
                resolved.parent != expected_parent
                or resolved.suffix != ".json"
                or len(stem) != 64
                or any(character not in "0123456789abcdef" for character in stem)
            ):
                raise StateLawMultiFetchAcquisitionError(
                    "frontier closure input is not a content-addressed projection"
                )

        if not resolved.is_file():
            raise StateLawMultiFetchAcquisitionError(
                "frontier closure input must be a regular file"
            )
        if resolved != legacy:
            try:
                retained_digest = file_sha256(resolved)
            except (OSError, ValueError) as exc:
                raise StateLawMultiFetchAcquisitionError(
                    "frontier closure input cannot be read"
                ) from exc
            if retained_digest != resolved.stem.lower():
                raise StateLawMultiFetchAcquisitionError(
                    "frontier closure input filename does not match retained bytes"
                )
        return resolved

    def _load_frontier_closure_projection(self, source: Path) -> dict[str, Any]:
        """Read and reverify the exact projection bytes selected by a caller."""

        if source.is_symlink() or not source.is_file():
            raise StateLawMultiFetchAcquisitionError(
                "frontier closure input must remain a regular non-symlink file"
            )
        try:
            with source.open("rb") as handle:
                raw = handle.read()
        except OSError as exc:
            raise StateLawMultiFetchAcquisitionError(
                "frontier closure input cannot be read"
            ) from exc
        if (
            source != self.closure_input_path.resolve(strict=False)
            and hashlib.sha256(raw).hexdigest() != source.stem.lower()
        ):
            raise StateLawMultiFetchAcquisitionError(
                "frontier closure input filename does not match retained bytes"
            )
        try:
            projected = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise StateLawMultiFetchAcquisitionError(
                "frontier closure input is not deterministic UTF-8 JSON"
            ) from exc
        if not isinstance(projected, Mapping):
            raise StateLawMultiFetchAcquisitionError(
                "frontier closure input file must contain a JSON object"
            )
        return dict(projected)

    def replay_retained_parser_input(
        self,
        *,
        official_url: str,
        sanitized_request: Mapping[str, Any],
    ) -> RetainedStateLawParserInput | None:
        """Return an exact retained response for one canonical request.

        This is a restart/reprocessing seam, not a new acquisition.  Matching
        uses the complete sanitized request contract (including a POST body
        digest when present) plus the receipt endpoint.  Multiple observations
        of the same request may be reused only when they bind the same response
        bytes; a changed response is ambiguous and therefore fails closed.
        The retained object is re-read and content-addressed on every replay so
        mutation after ledger construction cannot reach a parser.
        """

        matches = self._matching_retained_parser_inputs(
            official_url=official_url,
            sanitized_request=sanitized_request,
        )
        if not matches:
            if self.retained_replay_only:
                endpoint = urldefrag(str(official_url or "").strip())[0]
                raise StateLawRetainedReplayOnlyError(
                    "retained-replay-only ledger miss for exact parser request: "
                    f"{endpoint}"
                )
            return None
        return self._verify_retained_byte_replay(matches)

    def replay_retained_parser_inputs(
        self,
        *,
        requests: Sequence[tuple[str, Mapping[str, Any]]],
    ) -> tuple[RetainedStateLawParserInput, ...]:
        """Replay exact byte-backed inputs in request order without rescanning.

        The request index is maintained as entries are loaded or retained, so
        resolving ``m`` requests is O(m) after the ledger's one O(n) load.
        Full sanitized-request bytes and defragmented receipt endpoints remain
        the identity; same-request observations with different response bytes
        fail closed.  Every selected body is re-read and content-addressed
        before return.  This method performs no network I/O.
        """

        if not isinstance(requests, Sequence) or isinstance(
            requests,
            (str, bytes, bytearray),
        ):
            raise StateLawMultiFetchAcquisitionError(
                "retained parser-input plural replay requests must be a sequence"
            )
        normalized: list[tuple[str, Mapping[str, Any]]] = []
        for position, request in enumerate(requests):
            if (
                not isinstance(request, tuple)
                or len(request) != 2
                or not isinstance(request[1], Mapping)
            ):
                raise StateLawMultiFetchAcquisitionError(
                    "retained parser-input plural replay request "
                    f"{position} must be an (official_url, sanitized_request) tuple"
                )
            official_url = str(request[0] or "").strip()
            sanitized = _json_mapping_copy(
                request[1],
                name=f"requests[{position}].sanitized_request",
            )
            # Validate identity before any body is selected.
            self._retained_request_identity(
                official_url=official_url,
                sanitized_request=sanitized,
            )
            normalized.append((official_url, sanitized))

        replayed: list[RetainedStateLawParserInput] = []
        verified_by_identity: dict[tuple[str, bytes], RetainedStateLawParserInput] = {}
        for official_url, sanitized in normalized:
            identity = self._retained_request_identity(
                official_url=official_url,
                sanitized_request=sanitized,
            )
            retained = verified_by_identity.get(identity)
            if retained is None:
                matches = self._matching_retained_parser_inputs(
                    official_url=official_url,
                    sanitized_request=sanitized,
                )
                if not matches:
                    error_type = (
                        StateLawRetainedReplayOnlyError
                        if self.retained_replay_only
                        else StateLawMultiFetchAcquisitionError
                    )
                    raise error_type(
                        "retained parser-input plural replay is missing request: "
                        f"{official_url}"
                    )
                retained = self._verify_retained_byte_replay(matches)
                verified_by_identity[identity] = retained
            replayed.append(retained)
        return tuple(replayed)

    def replay_retained_parser_input_file(
        self,
        *,
        official_url: str,
        sanitized_request: Mapping[str, Any],
    ) -> RetainedStateLawParserInput | None:
        """Replay one exact file-backed input without materializing its bytes.

        Matching is identical to the ordinary byte replay seam, but only
        entries created by :meth:`retain_parser_input_file` participate. Every
        matching immutable object is re-hashed with the streaming file content
        address helper. Multiple observations are reusable only when they bind
        one response digest; request mismatch returns ``None``.
        """

        endpoint = urldefrag(str(official_url or "").strip())[0]
        if not endpoint:
            raise StateLawMultiFetchAcquisitionError(
                "file-backed parser-input replay requires an official URL"
            )
        request_payload = _json_mapping_copy(
            sanitized_request,
            name="sanitized_request",
        )
        request_bytes = canonical_json_bytes(request_payload)
        matches: list[RetainedStateLawParserInput] = []
        with self._lock:
            for receipt_sha in sorted(self._entries):
                retained = self._entries[receipt_sha]
                receipt = retained.receipt
                if receipt.metadata.get("file_backed_parser_input") is not True:
                    continue
                if urldefrag(str(receipt.endpoint or "").strip())[0] != endpoint:
                    continue
                if canonical_json_bytes(receipt.sanitized_request) != request_bytes:
                    continue
                if retained.envelope.body is not None:
                    raise StateLawMultiFetchAcquisitionError(
                        "file-backed parser-input replay found an in-memory envelope"
                    )
                matches.append(retained)

        if not matches:
            if self.retained_replay_only:
                raise StateLawRetainedReplayOnlyError(
                    "retained-replay-only ledger miss for exact file-backed "
                    f"parser request: {endpoint}"
                )
            return None
        content_digests = {
            str(item.receipt.content.sha256)
            for item in matches
            if item.receipt.content is not None
        }
        if len(content_digests) != 1:
            raise StateLawMultiFetchAcquisitionError(
                "file-backed parser-input replay is ambiguous for this request"
            )
        for retained in matches:
            expected = retained.receipt.content
            if expected is None or _content_address_file(retained.body_path) != expected:
                raise StateLawMultiFetchAcquisitionError(
                    "retained file-backed parser-input failed fixity replay"
                )
        return matches[0]

    def refresh_existing_entries(self) -> int:
        """Load immutable receipts retained by another live ledger instance.

        Retry workers intentionally construct independent ledger objects.  A
        ledger's initial in-memory view can therefore become stale while an
        older or newer worker is still retaining parser inputs.  Fetch files
        are immutable and atomically published, so refreshing only previously
        unseen receipt identities is both safe and sufficient.

        Returns the number of newly visible retained parser inputs.
        """

        with self._lock:
            previous_count = len(self._entries)
            self._load_existing_entries()
            return len(self._entries) - previous_count

    def _load_existing_entries(self) -> None:
        with self._lock:
            evidence_paths = sorted(self.fetches_dir.glob("*.json"))
        for evidence_path in evidence_paths:
            with self._lock:
                if evidence_path.stem in self._entries:
                    continue
            if evidence_path.is_symlink() or not evidence_path.is_file():
                raise StateLawMultiFetchAcquisitionError(
                    "retained fetch evidence must be regular non-symlink files"
                )
            try:
                payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StateLawMultiFetchAcquisitionError(
                    f"cannot replay retained fetch evidence {evidence_path.name}"
                ) from exc
            if not isinstance(payload, Mapping) or payload.get("schema_version") != SCHEMA_VERSION:
                raise StateLawMultiFetchAcquisitionError(
                    f"retained fetch evidence {evidence_path.name} has the wrong schema"
                )
            if str(payload.get("jurisdiction") or "").strip().upper() != self.jurisdiction:
                raise StateLawMultiFetchAcquisitionError(
                    f"retained fetch evidence {evidence_path.name} changed jurisdiction"
                )
            body_path = _resolve_retained_path(
                self.jurisdiction_root,
                payload.get("body_relative_path"),
                name="body_relative_path",
            )
            if not body_path.is_file():
                raise StateLawMultiFetchAcquisitionError(
                    f"retained response body is missing for {evidence_path.name}"
                )
            envelope_raw = payload.get("parser_input_envelope")
            if not isinstance(envelope_raw, Mapping):
                raise StateLawMultiFetchAcquisitionError(
                    f"retained parser envelope is missing for {evidence_path.name}"
                )
            file_backed = payload.get("body_storage") == "file_backed"
            try:
                if file_backed:
                    address = _content_address_file(body_path)
                    acquisition_raw = envelope_raw.get("acquisition")
                    receipt_raw = (
                        acquisition_raw.get("receipt")
                        if isinstance(acquisition_raw, Mapping)
                        else None
                    )
                    content_raw = (
                        receipt_raw.get("content")
                        if isinstance(receipt_raw, Mapping)
                        else None
                    )
                    expected = (
                        ContentAddress.from_dict(content_raw)
                        if isinstance(content_raw, Mapping)
                        else None
                    )
                    if expected is None or address != expected:
                        raise StateLawMultiFetchAcquisitionError(
                            f"file-backed parser body changed for {evidence_path.name}"
                        )
                    envelope = ParserInputEnvelope.from_dict(envelope_raw, body=None)
                else:
                    body = body_path.read_bytes()
                    envelope = ParserInputEnvelope.from_dict(envelope_raw, body=body)
            except Exception as exc:
                raise StateLawMultiFetchAcquisitionError(
                    f"retained parser envelope failed replay for {evidence_path.name}"
                ) from exc
            if envelope.parser_name != self.parser_name:
                raise StateLawMultiFetchAcquisitionError(
                    f"retained parser envelope belongs to {envelope.parser_name!r}, "
                    f"not {self.parser_name!r}"
                )
            transport_raw = payload.get("transport_receipt")
            if not isinstance(transport_raw, Mapping):
                raise StateLawMultiFetchAcquisitionError(
                    f"retained transport receipt is missing for {evidence_path.name}"
                )
            content = envelope.content_address
            if content is None:
                raise StateLawMultiFetchAcquisitionError(
                    f"retained parser envelope lacks content for {evidence_path.name}"
                )
            canonical_transport = canonicalize_state_law_transport_receipt(
                transport_raw,
                official_url=envelope.acquisition.receipt.endpoint,
                content_sha256=content.sha256,
            )
            verified = verify_state_law_transport_receipt(canonical_transport)
            receipt_sha = envelope.acquisition.receipt.receipt_sha256
            if evidence_path.stem != receipt_sha:
                raise StateLawMultiFetchAcquisitionError(
                    f"retained fetch filename does not match receipt {receipt_sha}"
                )
            with self._lock:
                retained = RetainedStateLawParserInput(
                    envelope=envelope,
                    transport=verified,
                    transport_receipt=canonical_transport,
                    body_path=body_path,
                    evidence_path=evidence_path,
                )
                self._entries[receipt_sha] = retained
                self._index_retained_entry_locked(receipt_sha, retained)

    def retain_parser_input(
        self,
        *,
        official_url: str,
        body: bytes,
        transport_receipt: Mapping[str, Any],
        retrieved_at: datetime | str | None = None,
        response_status: int = 200,
        media_type: str | None = None,
        sanitized_request: Mapping[str, Any] | None = None,
        pagination: Mapping[str, Any] | None = None,
        network_used: bool | None = None,
        outcome_kind: AcquisitionOutcomeKind | str | None = None,
    ) -> RetainedStateLawParserInput:
        """Retain one exact response before returning its bytes to a parser."""

        raw_body = bytes(body)
        if not raw_body:
            raise StateLawMultiFetchAcquisitionError(
                "an empty response is not a parser-admissible state-law input"
            )
        content = content_address_bytes(raw_body)
        try:
            canonical_transport = canonicalize_state_law_transport_receipt(
                transport_receipt,
                official_url=official_url,
                content_sha256=content.sha256,
            )
            verified_transport = verify_state_law_transport_receipt(
                canonical_transport,
                official_url=official_url,
                content_sha256=content.sha256,
            )
        except Exception as exc:
            raise StateLawMultiFetchAcquisitionError(
                "parser input lacks a verified direct/archive/cache origin receipt"
            ) from exc

        if outcome_kind is None:
            resolved_kind = (
                AcquisitionOutcomeKind.UNCHANGED
                if verified_transport.cache_depth
                else AcquisitionOutcomeKind.FETCHED
            )
        else:
            try:
                resolved_kind = AcquisitionOutcomeKind(outcome_kind)
            except (TypeError, ValueError) as exc:
                raise StateLawMultiFetchAcquisitionError(
                    "outcome_kind must be a parser-admissible acquisition kind"
                ) from exc
        request_payload = (
            _json_mapping_copy(sanitized_request, name="sanitized_request")
            if sanitized_request is not None
            else {"method": "GET", "url": verified_transport.official_url}
        )
        pagination_payload = (
            _json_mapping_copy(pagination, name="pagination")
            if pagination is not None
            else {}
        )
        body_path = self.objects_dir / f"{content.sha256}.bin"
        body_relative_path = _relative_path(self.jurisdiction_root, body_path)
        receipt = AcquisitionReceipt(
            endpoint=verified_transport.official_url,
            retrieved_at=retrieved_at or _utc_now(),
            outcome_kind=resolved_kind,
            response_status=int(response_status),
            sanitized_request=request_payload,
            content=content,
            media_type=media_type,
            declared_content_length=len(raw_body),
            cache_hit=bool(verified_transport.cache_depth),
            pagination=pagination_payload,
            metadata={
                "jurisdiction": self.jurisdiction,
                "retained_body_relative_path": body_relative_path,
                "schema_version": SCHEMA_VERSION,
                "transport_receipt": canonical_transport,
            },
        )
        outcome = AcquisitionOutcome(
            kind=resolved_kind,
            receipt=receipt,
            body=raw_body,
            network_used=(
                not bool(verified_transport.cache_depth)
                if network_used is None
                else bool(network_used)
            ),
        )
        envelope = ParserInputEnvelope.admit(
            outcome,
            parser_name=self.parser_name,
            metadata={
                "jurisdiction": self.jurisdiction,
                "schema_version": SCHEMA_VERSION,
                "transport_chain": list(verified_transport.transport_chain),
            },
        )
        evidence_path = self.fetches_dir / f"{receipt.receipt_sha256}.json"
        evidence_payload = {
            "authorizes_parser_admission": True,
            "body_relative_path": body_relative_path,
            "jurisdiction": self.jurisdiction,
            "parser_input_envelope": envelope.to_dict(),
            "schema_version": SCHEMA_VERSION,
            "transport_receipt": canonical_transport,
        }
        evidence_bytes = canonical_json_bytes(evidence_payload)

        with self._lock:
            if body_path.exists():
                if body_path.is_symlink() or not body_path.is_file():
                    raise StateLawMultiFetchAcquisitionError(
                        "content-addressed response object is not a regular file"
                    )
                existing = body_path.read_bytes()
                if content_address_bytes(existing) != content:
                    raise StateLawMultiFetchAcquisitionError(
                        "content-addressed response object failed fixity replay"
                    )
            else:
                atomic_write_bytes(body_path, raw_body)

            if evidence_path.exists():
                if evidence_path.is_symlink() or evidence_path.read_bytes() != evidence_bytes:
                    raise StateLawMultiFetchAcquisitionError(
                        "immutable parser-input evidence conflicts with retained bytes"
                    )
            else:
                atomic_write_bytes(evidence_path, evidence_bytes)

            retained = RetainedStateLawParserInput(
                envelope=envelope,
                transport=verified_transport,
                transport_receipt=canonical_transport,
                body_path=body_path,
                evidence_path=evidence_path,
            )
            self._entries[receipt.receipt_sha256] = retained
            self._index_retained_entry_locked(receipt.receipt_sha256, retained)
            return retained

    def retain_parser_input_file(
        self,
        *,
        official_url: str,
        source_path: str | Path,
        transport_receipt: Mapping[str, Any],
        retrieved_at: datetime | str | None = None,
        response_status: int = 200,
        media_type: str | None = None,
        sanitized_request: Mapping[str, Any] | None = None,
    ) -> RetainedStateLawParserInput:
        """Retain a large, pre-fetched parser input with bounded memory.

        The source file must already have a verifiable direct/archive/cache
        origin receipt.  It is streamed into the immutable evidence store and
        represented as an unchanged cached body; parsers may then bind every
        derived row to this one bundle digest without duplicating the bundle
        per member or loading it wholesale into RAM.
        """

        source = Path(source_path).expanduser()
        if source.is_symlink():
            raise StateLawMultiFetchAcquisitionError(
                "file-backed parser input source must not be a symlink"
            )
        source = source.resolve()
        content = _content_address_file(source)
        try:
            canonical_transport = canonicalize_state_law_transport_receipt(
                transport_receipt,
                official_url=official_url,
                content_sha256=content.sha256,
            )
            verified_transport = verify_state_law_transport_receipt(
                canonical_transport,
                official_url=official_url,
                content_sha256=content.sha256,
            )
        except Exception as exc:
            raise StateLawMultiFetchAcquisitionError(
                "file-backed parser input lacks a verified origin receipt"
            ) from exc

        request_payload = (
            _json_mapping_copy(sanitized_request, name="sanitized_request")
            if sanitized_request is not None
            else {"method": "GET", "url": verified_transport.official_url}
        )
        body_path = self.objects_dir / f"{content.sha256}.bin"
        body_relative_path = _relative_path(self.jurisdiction_root, body_path)
        receipt = AcquisitionReceipt(
            endpoint=verified_transport.official_url,
            retrieved_at=retrieved_at or _utc_now(),
            outcome_kind=AcquisitionOutcomeKind.UNCHANGED,
            response_status=int(response_status),
            sanitized_request=request_payload,
            content=content,
            media_type=media_type,
            declared_content_length=content.byte_size,
            cache_hit=True,
            metadata={
                "file_backed_parser_input": True,
                "jurisdiction": self.jurisdiction,
                "retained_body_relative_path": body_relative_path,
                "schema_version": SCHEMA_VERSION,
                "transport_receipt": canonical_transport,
            },
        )
        outcome = AcquisitionOutcome(
            kind=AcquisitionOutcomeKind.UNCHANGED,
            receipt=receipt,
            body=None,
            network_used=False,
        )
        envelope = ParserInputEnvelope.admit(
            outcome,
            parser_name=self.parser_name,
            metadata={
                "file_backed_parser_input": True,
                "jurisdiction": self.jurisdiction,
                "schema_version": SCHEMA_VERSION,
                "transport_chain": list(verified_transport.transport_chain),
            },
        )
        evidence_path = self.fetches_dir / f"{receipt.receipt_sha256}.json"
        evidence_payload = {
            "authorizes_parser_admission": True,
            "body_relative_path": body_relative_path,
            "body_storage": "file_backed",
            "jurisdiction": self.jurisdiction,
            "parser_input_envelope": envelope.to_dict(),
            "schema_version": SCHEMA_VERSION,
            "transport_receipt": canonical_transport,
        }
        evidence_bytes = canonical_json_bytes(evidence_payload)

        with self._lock:
            if body_path.exists():
                if _content_address_file(body_path) != content:
                    raise StateLawMultiFetchAcquisitionError(
                        "content-addressed file-backed object failed fixity replay"
                    )
            else:
                temporary_name = ""
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=self.objects_dir,
                        prefix=f".{content.sha256}.",
                        suffix=".tmp",
                        delete=False,
                    ) as temporary:
                        temporary_name = temporary.name
                        with source.open("rb") as source_handle:
                            shutil.copyfileobj(
                                source_handle,
                                temporary,
                                length=8 * 1024 * 1024,
                            )
                        temporary.flush()
                        os.fsync(temporary.fileno())
                    temporary_path = Path(temporary_name)
                    if _content_address_file(temporary_path) != content:
                        raise StateLawMultiFetchAcquisitionError(
                            "file-backed parser input changed while being retained"
                        )
                    os.replace(temporary_path, body_path)
                    temporary_name = ""
                finally:
                    if temporary_name:
                        Path(temporary_name).unlink(missing_ok=True)

            if evidence_path.exists():
                if evidence_path.is_symlink() or evidence_path.read_bytes() != evidence_bytes:
                    raise StateLawMultiFetchAcquisitionError(
                        "immutable file-backed parser evidence conflicts with retained bytes"
                    )
            else:
                atomic_write_bytes(evidence_path, evidence_bytes)

            retained = RetainedStateLawParserInput(
                envelope=envelope,
                transport=verified_transport,
                transport_receipt=canonical_transport,
                body_path=body_path,
                evidence_path=evidence_path,
            )
            self._entries[receipt.receipt_sha256] = retained
            self._index_retained_entry_locked(receipt.receipt_sha256, retained)
            return retained

    @staticmethod
    def _coverage_url(value: object) -> str:
        url = str(value or "").strip()
        if not url:
            return ""
        return urldefrag(url)[0].rstrip("/")

    @staticmethod
    def _row_source_url(row: Mapping[str, Any]) -> str:
        for key in ("sourceUrl", "source_url", "url", "sameAs"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _row_source_digest(row: Mapping[str, Any]) -> str:
        containers: list[Mapping[str, Any]] = [row]
        for key in (
            "provenance",
            "structured_data",
            "structuredData",
            "transport_receipt",
            "web_archiving_transport_receipt",
        ):
            nested = row.get(key)
            if isinstance(nested, Mapping):
                containers.append(nested)
        for container in containers:
            for key in (
                "body_sha256",
                "content_sha256",
                "raw_sha256",
                "content_digest",
                "source_checksum",
            ):
                value = str(container.get(key) or "").strip().lower()
                value = value.removeprefix("sha256:")
                if len(value) == 64 and all(char in "0123456789abcdef" for char in value):
                    return value
        return ""

    def audit_parser_output_coverage(
        self,
        rows: Sequence[Mapping[str, Any] | Any],
    ) -> dict[str, Any]:
        """Reconcile output source units against retained parser inputs.

        URL equality covers ordinary HTML section pages.  A bulk XML/PDF/API
        parser may instead repeat the exact retained bundle body SHA-256 on
        every derived row.  Rows having neither binding are reported as
        bypasses and cannot close an aggregate.
        """

        entries = self.entries
        retained_urls = {
            self._coverage_url(item.receipt.endpoint) for item in entries
        }
        retained_hashes = {
            item.receipt.content.sha256
            for item in entries
            if item.receipt.content is not None
        }
        uncovered: list[dict[str, Any]] = []
        covered_by_url = 0
        covered_by_digest = 0
        for position, value in enumerate(rows):
            if isinstance(value, Mapping):
                row = value
            elif hasattr(value, "to_dict"):
                projected = value.to_dict()
                row = projected if isinstance(projected, Mapping) else {}
            else:
                row = {}
            source_url = self._row_source_url(row)
            source_digest = self._row_source_digest(row)
            if source_url and self._coverage_url(source_url) in retained_urls:
                covered_by_url += 1
                continue
            if source_digest and source_digest in retained_hashes:
                covered_by_digest += 1
                continue
            identity = ""
            for key in (
                "@id",
                "legal_id",
                "identifier",
                "statute_id",
                "sectionNumber",
                "section_number",
            ):
                candidate = str(row.get(key) or "").strip()
                if candidate:
                    identity = candidate
                    break
            uncovered.append(
                {
                    "identity": identity or f"row:{position}",
                    "position": position,
                    "source_digest": source_digest or None,
                    "source_url": source_url or None,
                }
            )
        uncovered_address = content_address_mapping(
            {
                "jurisdiction": self.jurisdiction,
                "uncovered_units": uncovered,
            }
        )
        return {
            "complete": bool(rows) and not uncovered and bool(entries),
            "covered_by_content_digest": covered_by_digest,
            "covered_by_official_url": covered_by_url,
            "covered_row_count": covered_by_url + covered_by_digest,
            "jurisdiction": self.jurisdiction,
            "output_row_count": len(rows),
            "retained_acquisition_receipt_sha256s": [
                item.receipt.receipt_sha256 for item in entries
            ],
            "retained_parser_input_count": len(entries),
            "schema_version": SCHEMA_VERSION,
            "uncovered_unit_count": len(uncovered),
            "uncovered_units": uncovered[:100],
            "uncovered_units_sha256": uncovered_address.sha256,
        }

    def audit_canonical_jsonld_coverage(
        self,
        path: str | Path,
    ) -> dict[str, Any]:
        """Stream an exact JSON-LD artifact into the parser-input parity gate."""

        target = Path(path).expanduser()
        if target.is_symlink():
            raise StateLawMultiFetchAcquisitionError(
                "canonical JSON-LD coverage input must not be a symlink"
            )
        target = target.resolve()
        rows: list[Mapping[str, Any]] = []
        try:
            with target.open("r", encoding="utf-8", errors="strict") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    if not isinstance(payload, Mapping):
                        raise StateLawMultiFetchAcquisitionError(
                            f"canonical JSON-LD line {line_number} is not an object"
                        )
                    rows.append(payload)
        except StateLawMultiFetchAcquisitionError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StateLawMultiFetchAcquisitionError(
                "canonical JSON-LD cannot be replayed for parser-input coverage"
            ) from exc
        return self.audit_parser_output_coverage(rows)

    def retain_frontier_closure_projection(
        self,
        completion_receipt: Mapping[str, Any],
        *,
        replayed_frontier: Mapping[str, Any],
        canonical_output_projection: Mapping[str, Any] | None = None,
        release_point: str,
        official_source_url: str,
        acquisition_path_ids: Sequence[str],
        observation_time: str,
        source_software_version: str,
        relative_path: str | None = None,
        legacy_singleton: bool = False,
    ) -> Path:
        """Persist an enumerator-supplied receipt plus independent replay.

        This is the fail-closed handoff API for existing state enumerators.  It
        does not perform or synthesize a second traversal.  The caller must
        supply the separately observed ``replayed_frontier``; equality with the
        first frontier is checked before the immutable projection is retained.
        Final byte/frontier/completeness/source normalization still occurs only
        after canonical JSON-LD materialization.
        """

        completion = _json_mapping_copy(
            completion_receipt,
            name="completion_receipt",
        )
        replayed = _json_mapping_copy(
            replayed_frontier,
            name="replayed_frontier",
        )
        raw_code = str(
            completion.get("jurisdiction")
            or completion.get("jurisdiction_code")
            or ""
        ).strip().upper()
        if raw_code != self.jurisdiction:
            raise StateLawMultiFetchAcquisitionError(
                "completion receipt jurisdiction does not match the ledger"
            )
        first = completion.get("frontier")
        if not isinstance(first, Mapping):
            raise StateLawMultiFetchAcquisitionError(
                "completion receipt lacks a source frontier"
            )
        if canonical_json_bytes(
            _frontier_material(first, name="completion_receipt.frontier")
        ) != canonical_json_bytes(
            _frontier_material(replayed, name="replayed_frontier")
        ):
            raise StateLawMultiFetchAcquisitionError(
                "enumerator and independently replayed source frontiers differ"
            )
        if completion.get("official_source") is not True or str(
            completion.get("source_authority_class") or ""
        ).strip().lower() != "official":
            raise StateLawMultiFetchAcquisitionError(
                "closure projection requires an official-source completion receipt"
            )
        if str(completion.get("status") or "").strip().lower() != "success":
            raise StateLawMultiFetchAcquisitionError(
                "closure projection requires a successful completion receipt"
            )
        if str(completion.get("mode") or "").strip().lower() not in {
            "full",
            "uncapped",
        }:
            raise StateLawMultiFetchAcquisitionError(
                "closure projection requires an uncapped/full completion receipt"
            )
        output_projection: dict[str, Any] | None = None
        if canonical_output_projection is not None:
            output_projection = _validate_canonical_output_projection(
                canonical_output_projection,
                jurisdiction=self.jurisdiction,
            )
            _validate_completion_output_binding(completion, output_projection)
        parsed_source = urlparse(str(official_source_url or "").strip())
        if parsed_source.scheme.lower() not in {"http", "https"} or not parsed_source.hostname:
            raise StateLawMultiFetchAcquisitionError(
                "official_source_url must be an absolute HTTP(S) URL"
            )
        path_ids = [str(item).strip() for item in acquisition_path_ids if str(item).strip()]
        if not path_ids:
            raise StateLawMultiFetchAcquisitionError(
                "acquisition_path_ids must name an official-source catalog path"
            )
        if not str(release_point or "").strip():
            raise StateLawMultiFetchAcquisitionError("release_point must be explicit")
        if not str(observation_time or "").strip():
            raise StateLawMultiFetchAcquisitionError("observation_time must be explicit")
        if not str(source_software_version or "").strip():
            raise StateLawMultiFetchAcquisitionError(
                "source_software_version must be explicit"
            )
        projection = {
            "acquisition_path_ids": path_ids,
            "completion_receipt": completion,
            "observation_time": str(observation_time).strip(),
            "official_source_url": str(official_source_url).strip(),
            "release_point": str(release_point).strip(),
            "replayed_frontier": replayed,
            "schema_version": CLOSURE_INPUT_SCHEMA,
            "source_software_version": str(source_software_version).strip(),
        }
        if output_projection is not None:
            # The completion receipt already owns the canonical/derived key
            # lists required by the completeness oracle.  Retain only the
            # count/digest binding here so a large jurisdiction does not write
            # a third copy of every statute identity.
            projection["canonical_output_binding"] = (
                _compact_canonical_output_binding(output_projection)
            )
        if relative_path:
            projection["relative_path"] = str(relative_path).strip()
        payload = canonical_json_bytes(projection)
        if legacy_singleton:
            target = self.closure_input_path
        else:
            if self.closure_inputs_dir.is_symlink():
                raise StateLawMultiFetchAcquisitionError(
                    "content-addressed closure-input directory must not be a symlink"
                )
            self.closure_inputs_dir.mkdir(parents=True, exist_ok=True)
            if self.closure_inputs_dir.is_symlink():
                raise StateLawMultiFetchAcquisitionError(
                    "content-addressed closure-input directory must not be a symlink"
                )
            target = self.closure_inputs_dir / (
                f"{hashlib.sha256(payload).hexdigest()}.json"
            )
        with self._lock:
            if target.exists():
                if (
                    target.is_symlink()
                    or not target.is_file()
                    or target.read_bytes() != payload
                ):
                    raise StateLawMultiFetchAcquisitionError(
                        "immutable frontier closure projection conflicts with retained evidence"
                    )
            else:
                atomic_write_bytes(target, payload)
        return target

    def verify_retained_frontier_closure_projection(
        self,
        expected_output_projection: Mapping[str, Any],
        *,
        closure_input_path: str | Path | None = None,
        allow_legacy_singleton: bool = False,
    ) -> dict[str, Any]:
        """Replay the retained closure input against the runner's final rows."""

        expected = _validate_canonical_output_projection(
            expected_output_projection,
            jurisdiction=self.jurisdiction,
        )
        if closure_input_path is None:
            if not allow_legacy_singleton:
                raise StateLawMultiFetchAcquisitionError(
                    "frontier closure verification requires an explicit projection path"
                )
            closure_input_path = self.closure_input_path
        try:
            source = self.resolve_frontier_closure_projection_path(
                closure_input_path,
                allow_legacy_singleton=allow_legacy_singleton,
            )
        except StateLawMultiFetchAcquisitionError:
            raise
        except (OSError, ValueError) as exc:
            raise StateLawMultiFetchAcquisitionError(
                "frontier producer did not retain the immutable closure input"
            ) from exc
        retained = self._load_frontier_closure_projection(source)
        actual_raw = retained.get("canonical_output_binding")
        if not isinstance(actual_raw, Mapping):
            raise StateLawMultiFetchAcquisitionError(
                "retained frontier closure lacks the final canonical output binding"
            )
        actual = _validate_compact_canonical_output_binding(
            actual_raw,
            jurisdiction=self.jurisdiction,
        )
        expected_binding = _compact_canonical_output_binding(expected)
        if canonical_json_bytes(actual) != canonical_json_bytes(expected_binding):
            raise StateLawMultiFetchAcquisitionError(
                "retained frontier closure projection does not match final canonical rows"
            )
        completion = retained.get("completion_receipt")
        if not isinstance(completion, Mapping):
            raise StateLawMultiFetchAcquisitionError(
                "retained frontier closure lacks a completion receipt"
            )
        _validate_completion_output_binding(completion, expected)
        return actual

    def close_from_projection(
        self,
        closure_input: Mapping[str, Any],
        *,
        canonical_jsonld_path: str | Path,
        catalog: OfficialSourceCatalog | None = None,
        defer_normalized_receipt: bool = False,
    ) -> ClosedStateLawMultiFetchFrontier:
        """Close from a small projection of existing receipt/frontier contracts.

        The projection is intentionally not a new acquisition claim.  It only
        carries an already-produced completion receipt, the independently
        replayed frontier, and the normalizer fields required by
        :meth:`close_jurisdiction_frontier`.  The strict refresh runner can
        therefore consume a prospectively written closure input without
        copying a crawler or fabricating a frontier after parsing.
        """

        projected = _json_mapping_copy(closure_input, name="closure_input")
        schema = str(projected.get("schema_version") or "").strip()
        if schema and schema != CLOSURE_INPUT_SCHEMA:
            raise StateLawMultiFetchAcquisitionError(
                f"closure_input schema must be {CLOSURE_INPUT_SCHEMA!r}"
            )
        completion = projected.get("completion_receipt")
        replayed = projected.get("replayed_frontier")
        if not isinstance(completion, Mapping):
            raise StateLawMultiFetchAcquisitionError(
                "closure_input must contain completion_receipt"
            )
        if not isinstance(replayed, Mapping):
            raise StateLawMultiFetchAcquisitionError(
                "closure_input must contain an independently replayed_frontier"
            )
        actual_output = build_canonical_state_law_jsonld_output_projection(
            canonical_jsonld_path,
            jurisdiction=self.jurisdiction,
        )
        raw_binding = projected.get("canonical_output_binding")
        if raw_binding is not None:
            if not isinstance(raw_binding, Mapping):
                raise StateLawMultiFetchAcquisitionError(
                    "closure_input canonical_output_binding must be an object"
                )
            retained_binding = _validate_compact_canonical_output_binding(
                raw_binding,
                jurisdiction=self.jurisdiction,
            )
            if canonical_json_bytes(retained_binding) != canonical_json_bytes(
                _compact_canonical_output_binding(actual_output)
            ):
                raise StateLawMultiFetchAcquisitionError(
                    "canonical JSON-LD identities differ from the retained output binding"
                )
        _validate_completion_output_binding(completion, actual_output)

        def _value(name: str, default: object = "") -> object:
            value = projected.get(name)
            if value not in (None, "", []):
                return value
            return completion.get(name, default)

        path_ids_raw = _value("acquisition_path_ids", [])
        if not isinstance(path_ids_raw, Sequence) or isinstance(
            path_ids_raw, (str, bytes, bytearray)
        ):
            raise StateLawMultiFetchAcquisitionError(
                "closure_input acquisition_path_ids must be a sequence"
            )
        return self.close_jurisdiction_frontier(
            completion,
            replayed_frontier=replayed,
            canonical_jsonld_path=canonical_jsonld_path,
            release_point=str(_value("release_point") or ""),
            official_source_url=str(_value("official_source_url") or ""),
            acquisition_path_ids=[str(item) for item in path_ids_raw],
            observation_time=str(_value("observation_time") or ""),
            source_software_version=str(_value("source_software_version") or ""),
            relative_path=(
                str(_value("relative_path") or "").strip() or None
            ),
            catalog=catalog,
            defer_normalized_receipt=defer_normalized_receipt,
        )

    def close_from_projection_file(
        self,
        closure_input_path: str | Path,
        *,
        canonical_jsonld_path: str | Path,
        catalog: OfficialSourceCatalog | None = None,
        allow_legacy_singleton: bool = False,
        defer_normalized_receipt: bool = False,
    ) -> ClosedStateLawMultiFetchFrontier:
        """Replay and consume one non-symlink closure projection file."""

        source = self.resolve_frontier_closure_projection_path(
            closure_input_path,
            allow_legacy_singleton=allow_legacy_singleton,
        )
        projected = self._load_frontier_closure_projection(source)
        return self.close_from_projection(
            projected,
            canonical_jsonld_path=canonical_jsonld_path,
            catalog=catalog,
            defer_normalized_receipt=defer_normalized_receipt,
        )

    def close_jurisdiction_frontier(
        self,
        completion_receipt: Mapping[str, Any],
        *,
        replayed_frontier: Mapping[str, Any],
        canonical_jsonld_path: str | Path,
        release_point: str,
        official_source_url: str,
        acquisition_path_ids: Sequence[str],
        observation_time: str,
        source_software_version: str,
        relative_path: str | None = None,
        catalog: OfficialSourceCatalog | None = None,
        defer_normalized_receipt: bool = False,
    ) -> ClosedStateLawMultiFetchFrontier:
        """Close and qualify one exact multi-response jurisdiction aggregate.

        ``completion_receipt`` remains responsible for the source-enumerator
        proof (dispositions, boundary probes, canonical keys, and absence of
        caps).  ``replayed_frontier`` must be a separately supplied second
        traversal projection.  This method binds that shared completeness
        proof to retained parser inputs and to one exact canonical artifact.
        """

        if not self.entries:
            raise StateLawMultiFetchAcquisitionError(
                "cannot close a jurisdiction frontier without parser-input receipts"
            )
        source = Path(canonical_jsonld_path).expanduser()
        if source.is_symlink():
            raise StateLawMultiFetchAcquisitionError(
                "canonical_jsonld_path must be a regular non-symlink file"
            )
        source = source.resolve()
        if not source.is_file() or source.suffix.lower() != ".jsonld":
            raise StateLawMultiFetchAcquisitionError(
                "canonical_jsonld_path must be an existing JSON-LD file"
            )
        source_bytes = source.read_bytes()
        canonical_sha256 = file_sha256(source)
        canonical_rows = legacy_input_row_count(source)
        if canonical_rows <= 0:
            raise StateLawMultiFetchAcquisitionError(
                "canonical JSON-LD must contain at least one row"
            )
        parser_input_coverage = self.audit_canonical_jsonld_coverage(source)
        if not parser_input_coverage["complete"]:
            sample = parser_input_coverage.get("uncovered_units") or []
            raise StateLawMultiFetchAcquisitionError(
                "canonical source units bypassed the retained parser-input ledger: "
                f"uncovered={parser_input_coverage['uncovered_unit_count']} "
                f"sample={sample[:3]}"
            )

        candidate = _json_mapping_copy(
            completion_receipt,
            name="completion_receipt",
        )
        canonical_output = build_canonical_state_law_jsonld_output_projection(
            source,
            jurisdiction=self.jurisdiction,
        )
        raw_code = str(
            candidate.get("jurisdiction")
            or candidate.get("jurisdiction_code")
            or ""
        ).strip().upper()
        if raw_code != self.jurisdiction:
            raise StateLawMultiFetchAcquisitionError(
                "completion receipt jurisdiction does not match the acquisition ledger"
            )
        if candidate.get("official_source") is not True:
            raise StateLawMultiFetchAcquisitionError(
                "completion receipt must already declare an official source"
            )
        authority = str(candidate.get("source_authority_class") or "").strip().lower()
        if authority != "official":
            raise StateLawMultiFetchAcquisitionError(
                "completion receipt must already declare official source authority"
            )
        if str(candidate.get("status") or "").strip().lower() != "success":
            raise StateLawMultiFetchAcquisitionError(
                "only a successful full-corpus completion receipt may be closed"
            )
        if str(candidate.get("mode") or "").strip().lower() not in {"full", "uncapped"}:
            raise StateLawMultiFetchAcquisitionError(
                "multi-fetch closure requires an explicit full/uncapped receipt"
            )
        reported_rows = _reported_int(
            candidate.get("canonical_row_count", candidate.get("row_count")),
            name="completion receipt row_count",
        )
        if reported_rows != canonical_rows:
            raise StateLawMultiFetchAcquisitionError(
                "completion receipt row count does not match canonical JSON-LD: "
                f"receipt={reported_rows} artifact={canonical_rows}"
            )
        _validate_completion_output_binding(candidate, canonical_output)
        for key in (
            "adapter_input_sha256",
            "artifact_sha256",
            "input_sha256",
            "canonical_artifact_sha256",
        ):
            value = str(candidate.get(key) or "").strip().lower().removeprefix(
                "sha256:"
            )
            if value and value != canonical_sha256:
                raise StateLawMultiFetchAcquisitionError(
                    f"completion receipt {key} conflicts with canonical JSON-LD"
                )

        first_frontier = candidate.get("frontier")
        if not isinstance(first_frontier, Mapping):
            raise StateLawMultiFetchAcquisitionError(
                "completion receipt lacks a source frontier"
            )
        first_material = _frontier_material(
            first_frontier,
            name="completion_receipt.frontier",
        )
        replay_material = _frontier_material(
            replayed_frontier,
            name="replayed_frontier",
        )
        if canonical_json_bytes(first_material) != canonical_json_bytes(replay_material):
            raise StateLawMultiFetchAcquisitionError(
                "first and replayed source frontiers differ"
            )
        frontier_digest = content_address_mapping(
            {
                "jurisdiction": self.jurisdiction,
                "source_frontier": first_material,
            }
        ).sha256
        projected_frontier = dict(first_material)
        projected_frontier["frontier_digest_sha256"] = frontier_digest
        candidate["frontier"] = projected_frontier

        entries = self.entries
        request_rows: list[dict[str, Any]] = []
        response_rows: list[dict[str, Any]] = []
        transport_receipts: list[dict[str, Any]] = []
        seen_transports: set[bytes] = set()
        response_hashes: list[str] = []
        for item in entries:
            receipt = item.receipt
            request_rows.append(
                {
                    "acquisition_receipt_sha256": receipt.receipt_sha256,
                    "endpoint": receipt.endpoint,
                    "sanitized_request": dict(receipt.sanitized_request),
                }
            )
            response_rows.append(item.to_ledger_dict(jurisdiction_root=self.jurisdiction_root))
            if receipt.content is not None:
                response_hashes.append(receipt.content.sha256)
            transport_payload = dict(item.transport_receipt)
            transport_key = canonical_json_bytes(transport_payload)
            if transport_key not in seen_transports:
                seen_transports.add(transport_key)
                transport_receipts.append(transport_payload)

        request_ledger = {
            "jurisdiction": self.jurisdiction,
            "requests": request_rows,
            "schema_version": REQUEST_LEDGER_SCHEMA,
        }
        response_ledger = {
            "jurisdiction": self.jurisdiction,
            "responses": response_rows,
            "schema_version": RESPONSE_LEDGER_SCHEMA,
        }
        request_bytes = canonical_json_bytes(request_ledger)
        response_bytes = canonical_json_bytes(response_ledger)
        request_address = content_address_bytes(request_bytes)
        response_address = content_address_bytes(response_bytes)
        request_ledger_path = (
            self.ledgers_dir / f"requests-{request_address.sha256}.json"
        )
        response_ledger_path = (
            self.ledgers_dir / f"responses-{response_address.sha256}.json"
        )

        replay = candidate.get("replay")
        replay_payload = dict(replay) if isinstance(replay, Mapping) else {}
        replay_payload.update(
            {
                "admitted_body_sha256": canonical_sha256,
                "closed": True,
                "first_frontier_digest": frontier_digest,
                "frontier_digest_sha256": frontier_digest,
                "request_sha256": request_address.sha256,
                "response_sha256": response_address.sha256,
                "second_frontier_digest": frontier_digest,
            }
        )
        candidate.update(
            {
                "acquisition_path_ids": [
                    str(item).strip()
                    for item in acquisition_path_ids
                    if str(item).strip()
                ],
                "adapter_input_sha256": canonical_sha256,
                "artifact_sha256": canonical_sha256,
                "canonical_artifact_sha256": canonical_sha256,
                "canonical_row_count": canonical_rows,
                "content_hashes": list(
                    dict.fromkeys(
                        [
                            *response_hashes,
                            request_address.sha256,
                            response_address.sha256,
                            canonical_sha256,
                        ]
                    )
                ),
                "frontier_aggregate": {
                    "canonical_jsonld": {
                        "row_count": canonical_rows,
                        "sha256": canonical_sha256,
                    },
                    "parser_input_count": len(entries),
                    "request_ledger": request_address.to_dict(),
                    "request_ledger_relative_path": _relative_path(
                        self.jurisdiction_root,
                        request_ledger_path,
                    ),
                    "response_ledger": response_address.to_dict(),
                    "response_ledger_relative_path": _relative_path(
                        self.jurisdiction_root,
                        response_ledger_path,
                    ),
                    "schema_version": FRONTIER_AGGREGATE_SCHEMA,
                    "single_response_claims_entire_corpus": False,
                },
                "hashes": {
                    "admitted_body_sha256": canonical_sha256,
                    "request_sha256": request_address.sha256,
                    "response_sha256": response_address.sha256,
                },
                "input_sha256": canonical_sha256,
                "observation_time": str(observation_time or "").strip(),
                "official_source_url": str(official_source_url or "").strip(),
                "receipt_id": str(candidate.get("receipt_id") or "").strip()
                or f"scrape-{self.jurisdiction.lower()}-{canonical_sha256[:20]}",
                "release_point": str(release_point or "").strip(),
                "replay": replay_payload,
                "row_count": canonical_rows,
                "parser_input_coverage": parser_input_coverage,
                "source_checksum": canonical_sha256,
                "source_software_version": str(source_software_version or "").strip(),
                "transport": {
                    "fixture": False,
                    "kind": "multi_fetch_ledger",
                    "synthetic": False,
                },
                "transport_receipts": transport_receipts,
                "verification_result": "verified",
            }
        )
        parsed_source = urlparse(str(official_source_url or "").strip())
        if parsed_source.scheme.lower() not in {"http", "https"} or not parsed_source.hostname:
            raise StateLawMultiFetchAcquisitionError(
                "official_source_url must be an absolute HTTP(S) URL"
            )
        candidate["source_domain"] = parsed_source.hostname.lower()
        start_urls = [
            str(item).strip()
            for item in candidate.get("start_urls", [])
            if str(item).strip()
        ] if isinstance(candidate.get("start_urls"), Sequence) and not isinstance(
            candidate.get("start_urls"), (str, bytes, bytearray)
        ) else []
        if str(official_source_url).strip() not in start_urls:
            start_urls.insert(0, str(official_source_url).strip())
        candidate["start_urls"] = start_urls
        if not candidate["acquisition_path_ids"]:
            raise StateLawMultiFetchAcquisitionError(
                "acquisition_path_ids must name the cataloged official path"
            )
        if not candidate["observation_time"]:
            raise StateLawMultiFetchAcquisitionError(
                "observation_time must be explicit"
            )
        if not candidate["source_software_version"]:
            raise StateLawMultiFetchAcquisitionError(
                "source_software_version must be explicit"
            )

        byte_verification = verify_receipt_bytes(
            candidate,
            request_bytes=request_bytes,
            response_bytes=response_bytes,
            body_bytes=source_bytes,
        )
        if not byte_verification.ok or not byte_verification.raw_bytes_checked:
            raise StateLawMultiFetchAcquisitionError(
                "shared acquisition byte verifier rejected the multi-fetch aggregate: "
                f"{byte_verification.detail}"
            )
        frontier_verification = verify_receipt_frontier(candidate)
        if not frontier_verification.ok:
            raise StateLawMultiFetchAcquisitionError(
                "shared acquisition frontier verifier rejected the aggregate: "
                f"{frontier_verification.detail}"
            )
        completeness = evaluate_jurisdiction_receipt(
            candidate,
            case_id=f"prospective-multifetch-{self.jurisdiction.lower()}",
        )
        if not completeness.complete:
            raise StateLawMultiFetchAcquisitionError(
                "state-law completeness oracle rejected the aggregate: "
                + ",".join(completeness.kinds)
            )
        normalized = normalize_source_receipt(
            candidate,
            input_path=source,
            jurisdiction=self.jurisdiction,
            release_point=release_point,
            relative_path=relative_path,
            catalog=catalog,
        )
        if not normalized.admission_eligible or normalized.qualification_reasons:
            raise StateLawMultiFetchAcquisitionError(
                "canonical source-receipt normalizer rejected the aggregate: "
                + ",".join(normalized.qualification_reasons)
            )

        candidate_bytes = canonical_json_bytes(candidate)
        candidate_address = content_address_bytes(candidate_bytes)
        receipt_path = self.frontiers_dir / f"{candidate_address.sha256}.json"
        normalized_receipt_path = self.frontiers_dir / (
            f"{candidate_address.sha256}{PENDING_NORMALIZED_RECEIPT_SUFFIX}"
            if defer_normalized_receipt
            else f"{candidate_address.sha256}.normalized.json"
        )
        with self._lock:
            atomic_write_bytes(request_ledger_path, request_bytes)
            atomic_write_bytes(response_ledger_path, response_bytes)
            atomic_write_bytes(receipt_path, candidate_bytes)
            atomic_write_bytes(
                normalized_receipt_path,
                canonical_json_bytes(normalized.record.to_dict()),
            )

        return ClosedStateLawMultiFetchFrontier(
            receipt=candidate,
            normalized_source_receipt=normalized,
            byte_verification=byte_verification,
            frontier_verification=frontier_verification,
            receipt_path=receipt_path,
            normalized_receipt_path=normalized_receipt_path,
            request_ledger_path=request_ledger_path,
            response_ledger_path=response_ledger_path,
        )


__all__ = [
    "AUTHORIZES_LEGACY_CHECKPOINTS",
    "AUTHORIZES_REMATERIALIZATION_RECEIPTS",
    "CANONICAL_OUTPUT_PROJECTION_SCHEMA",
    "CLOSURE_INPUTS_DIRNAME",
    "CLOSURE_INPUT_FILENAME",
    "CLOSURE_INPUT_SCHEMA",
    "FRONTIER_AGGREGATE_SCHEMA",
    "REQUEST_LEDGER_SCHEMA",
    "REQUIRES_PROSPECTIVE_PARSER_INPUT_RECEIPTS",
    "RESPONSE_LEDGER_SCHEMA",
    "SCHEMA_VERSION",
    "ClosedStateLawMultiFetchFrontier",
    "RetainedStateLawParserInput",
    "StateLawMultiFetchAcquisitionError",
    "StateLawMultiFetchAcquisitionLedger",
    "StateLawRetainedReplayOnlyError",
    "build_canonical_state_law_jsonld_output_projection",
    "build_canonical_state_law_output_projection",
]
