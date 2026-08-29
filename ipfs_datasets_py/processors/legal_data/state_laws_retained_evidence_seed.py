"""Verified, zero-network seeding of a fresh state-law evidence generation.

Some strict corpus repairs must replace stale archive observations without
discarding thousands of valid direct-current parser inputs.  This module
copies no authority claims and performs no acquisition.  It first loads and
reverifies the source :class:`StateLawMultiFetchAcquisitionLedger`.  Fetch
files whose declared source transport is outside the caller's allowed set are
skipped without replay or network, so a mixed historical ledger can still
yield a direct-only projection when Wayback or other disallowed receipts no
longer verify.  It then selects a bounded set of already-authorizing parser
inputs by exact transport and URL, deduplicates identical request identities,
and stages their immutable files in a fresh jurisdiction root.  Content
objects are hard-linked when possible and byte-copied only across
filesystems.  Skipped disallowed transports are never copied into the
destination root.

The destination is published by one directory rename only after a second
ledger instance has replayed every staged receipt and body.  A migration
receipt records what was reused, but that receipt is diagnostic: parser
admission remains authorized solely by the original byte-bound fetch files.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import urldefrag

from ipfs_datasets_py.processors.legal_data.patent_authority_contracts_v2 import (
    canonical_json_bytes,
)
from ipfs_datasets_py.processors.legal_data.state_laws_legacy_v2_adapter import (
    file_sha256,
)
from ipfs_datasets_py.processors.legal_data.state_laws_multifetch_acquisition import (
    RetainedStateLawParserInput,
    StateLawMultiFetchAcquisitionLedger,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    validate_jurisdiction,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import atomic_write_bytes

SCHEMA_VERSION: Final = "state-laws-retained-evidence-seed-v1"
TRANSPORT_UNSTABLE_EXCLUSION_SCHEMA_VERSION: Final = (
    "state-laws-retained-evidence-seed-v2"
)
PHASE_BOUND_SEED_SCHEMA_VERSION: Final = (
    "state-laws-retained-evidence-phase-bound-seed-v1"
)
UNION_SCHEMA_VERSION: Final = "state-laws-retained-evidence-union-v1"
_SELECTION_RECEIPT_SCHEMA_VERSIONS: Final = frozenset(
    {
        SCHEMA_VERSION,
        TRANSPORT_UNSTABLE_EXCLUSION_SCHEMA_VERSION,
        UNION_SCHEMA_VERSION,
    }
)
_PROJECTION_FIELDS: Final = frozenset(
    {
        "content_sha256",
        "official_url",
        "receipt_sha256",
        "request_sha256",
        "source_transport",
    }
)


class StateLawsRetainedEvidenceSeedError(ValueError):
    """A retained evidence generation cannot be seeded safely."""


@dataclass(frozen=True, slots=True)
class RetainedEvidenceSeedReport:
    """Integrity result for one atomically seeded jurisdiction ledger."""

    jurisdiction: str
    parser_name: str
    source_root: str
    destination_root: str
    allowed_source_transports: tuple[str, ...]
    requested_url_count: int
    selected_parser_input_count: int
    duplicate_request_observations_avoided: int
    skipped_disallowed_transport_count: int
    unique_content_object_count: int
    hardlinked_file_count: int
    copied_file_count: int
    selected_projection_sha256: str
    migration_receipt_path: str
    migration_receipt_sha256: str
    excluded_transport_unstable_receipt_count: int = 0
    excluded_transport_unstable_receipt_sha256s: tuple[str, ...] = ()
    network_io_performed: bool = False
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RetainedEvidenceSeedSource:
    """One explicitly bounded source ledger in a multi-source seed."""

    source_root: str | Path
    parser_name: str
    allowed_source_transports: tuple[str, ...]
    include_urls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetainedEvidenceUnionReport:
    """Integrity result for one atomic, zero-network evidence union."""

    jurisdiction: str
    parser_name: str
    source_roots: tuple[str, ...]
    source_parser_names: tuple[str, ...]
    destination_root: str
    selected_parser_input_count: int
    duplicate_request_observations_avoided: int
    skipped_disallowed_transport_count: int
    unique_content_object_count: int
    hardlinked_file_count: int
    copied_file_count: int
    rebound_parser_input_count: int
    selected_projection_sha256: str
    migration_receipt_path: str
    migration_receipt_sha256: str
    network_io_performed: bool = False
    schema_version: str = UNION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _UnionSelection:
    entry: RetainedStateLawParserInput
    source_root: Path
    source_parser_name: str


def _canonical_url(value: object) -> str:
    url = urldefrag(str(value or "").strip())[0]
    if not url:
        raise StateLawsRetainedEvidenceSeedError(
            "retained evidence URL must be non-empty"
        )
    return url


def _transport_name(entry: RetainedStateLawParserInput) -> str:
    return str(entry.transport_receipt.get("source_transport") or "").strip()


def _request_identity(
    entry: RetainedStateLawParserInput,
) -> tuple[str, bytes]:
    return (
        _canonical_url(entry.receipt.endpoint),
        canonical_json_bytes(entry.receipt.sanitized_request),
    )


def _normalized_allowed_transports(
    allowed_source_transports: Sequence[str],
) -> tuple[str, ...]:
    transports = tuple(
        sorted(
            {
                str(value or "").strip()
                for value in allowed_source_transports
                if str(value or "").strip()
            }
        )
    )
    if not transports:
        raise StateLawsRetainedEvidenceSeedError(
            "at least one source transport must be allowed"
        )
    return transports


def _select_entries(
    ledger: StateLawMultiFetchAcquisitionLedger,
    *,
    allowed_source_transports: Sequence[str],
    include_urls: Iterable[str] | None,
    phase_bound_receipt_sha256s: Sequence[str] = (),
) -> tuple[list[RetainedStateLawParserInput], int, tuple[str, ...]]:
    transports = _normalized_allowed_transports(allowed_source_transports)

    bound_receipt_ids: set[str] = set()
    for raw_digest in phase_bound_receipt_sha256s:
        digest = str(raw_digest or "").strip().lower()
        if (
            raw_digest != digest
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise StateLawsRetainedEvidenceSeedError(
                "phase-bound receipt identity must be a canonical SHA-256"
            )
        if digest in bound_receipt_ids:
            raise StateLawsRetainedEvidenceSeedError(
                "phase-bound receipt identities must be unique"
            )
        bound_receipt_ids.add(digest)

    requested_urls = (
        tuple(sorted({_canonical_url(value) for value in include_urls}))
        if include_urls is not None
        else ()
    )
    requested_set = set(requested_urls)
    candidates = [
        entry
        for entry in ledger.entries
        if _transport_name(entry) in transports
        and (
            not requested_set
            or _canonical_url(entry.receipt.endpoint) in requested_set
        )
    ]
    if requested_set:
        observed = {
            _canonical_url(entry.receipt.endpoint) for entry in candidates
        }
        missing = sorted(requested_set - observed)
        if missing:
            raise StateLawsRetainedEvidenceSeedError(
                "requested retained URLs are absent from the allowed transport "
                f"projection: {missing[:3]}"
            )
    if not candidates:
        raise StateLawsRetainedEvidenceSeedError(
            "retained evidence selection is empty"
        )

    grouped: dict[
        tuple[str, bytes],
        list[RetainedStateLawParserInput],
    ] = {}
    for entry in candidates:
        grouped.setdefault(_request_identity(entry), []).append(entry)

    candidates_by_receipt = {
        entry.receipt.receipt_sha256: entry for entry in candidates
    }
    if len(candidates_by_receipt) != len(candidates):
        raise StateLawsRetainedEvidenceSeedError(
            "allowed retained evidence repeats one receipt identity"
        )
    missing_bound_receipts = sorted(bound_receipt_ids - set(candidates_by_receipt))
    if missing_bound_receipts:
        raise StateLawsRetainedEvidenceSeedError(
            "phase-bound receipt is absent from the allowed transport projection: "
            f"{missing_bound_receipts[0]}"
        )

    selected: list[RetainedStateLawParserInput] = []
    for identity in sorted(grouped, key=lambda item: (item[0], item[1])):
        observations = grouped[identity]
        observation_ids = {
            entry.receipt.receipt_sha256 for entry in observations
        }
        bound_observation_ids = observation_ids & bound_receipt_ids
        if bound_observation_ids:
            if bound_observation_ids != observation_ids:
                raise StateLawsRetainedEvidenceSeedError(
                    "phase-bound plan does not bind every retained observation for "
                    f"one exact request: {identity[0]}"
                )
            selected.extend(
                entry
                for entry in observations
                if entry.receipt.receipt_sha256 in bound_observation_ids
            )
            continue
        content_digests = {
            str(entry.receipt.content.sha256)
            for entry in observations
            if entry.receipt.content is not None
        }
        if len(content_digests) != 1:
            raise StateLawsRetainedEvidenceSeedError(
                "allowed retained observations disagree for one exact request: "
                f"{identity[0]}"
            )
        chosen = min(
            observations,
            key=lambda item: item.receipt.receipt_sha256,
        )
        selected.append(chosen)

    selected.sort(
        key=lambda item: (
            _canonical_url(item.receipt.endpoint),
            hashlib.sha256(
                canonical_json_bytes(item.receipt.sanitized_request)
            ).hexdigest(),
            item.receipt.receipt_sha256,
        )
    )
    return selected, len(candidates) - len(selected), requested_urls


def _selected_projection(
    entries: Sequence[RetainedStateLawParserInput],
) -> list[dict[str, Any]]:
    projection = [
        {
            "content_sha256": str(entry.receipt.content.sha256),
            "official_url": _canonical_url(entry.receipt.endpoint),
            "receipt_sha256": entry.receipt.receipt_sha256,
            "request_sha256": hashlib.sha256(
                canonical_json_bytes(entry.receipt.sanitized_request)
            ).hexdigest(),
            "source_transport": _transport_name(entry),
        }
        for entry in entries
    ]
    projection.sort(
        key=lambda item: (
            item["official_url"],
            item["request_sha256"],
            item["receipt_sha256"],
        )
    )
    return projection


def _validated_sha256(value: object, *, field_name: str) -> str:
    digest = str(value or "").strip()
    if (
        not isinstance(value, str)
        or value != digest
        or len(digest) != 64
        or digest != digest.lower()
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise StateLawsRetainedEvidenceSeedError(
            f"source selection receipt has an invalid {field_name}"
        )
    return digest


def _load_source_selection_projection(
    selection_receipt: str | Path,
    *,
    source: Path,
    jurisdiction: str,
    parser_name: str,
    allowed_source_transports: Sequence[str],
) -> tuple[list[dict[str, Any]], Path, str]:
    """Load and verify one prior migration's exact retained projection."""

    unresolved = Path(selection_receipt).expanduser()
    if unresolved.is_symlink() or not unresolved.is_file():
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt must be a regular non-symlink file"
        )
    resolved = unresolved.resolve()
    source_jurisdiction = (source / jurisdiction).resolve()
    try:
        resolved.relative_to(source_jurisdiction)
    except ValueError as exc:
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt must be contained within the source "
            "jurisdiction evidence root"
        ) from exc

    receipt_bytes = resolved.read_bytes()
    receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    if resolved.name != f"{receipt_sha256}.json":
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt filename failed SHA-256 fixity verification"
        )
    try:
        payload = json.loads(receipt_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt must be a JSON object"
        )
    if canonical_json_bytes(payload) != receipt_bytes:
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt is not canonical JSON"
        )
    if payload.get("schema_version") not in _SELECTION_RECEIPT_SCHEMA_VERSIONS:
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt has an unsupported schema_version"
        )
    if payload.get("jurisdiction") != jurisdiction:
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt jurisdiction does not match the source ledger"
        )
    if payload.get("parser_name") != parser_name:
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt parser_name does not match the source ledger"
        )
    if payload.get("authorizes_parser_admission") is not False:
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt must be diagnostic-only"
        )
    if payload.get("network_io_performed") is not False:
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt must attest zero network I/O"
        )

    raw_projection = payload.get("selected_projection")
    if not isinstance(raw_projection, list) or not raw_projection:
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt has no selected_projection"
        )
    selected_count = payload.get("selected_parser_input_count")
    if type(selected_count) is not int or selected_count != len(raw_projection):
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt selected_parser_input_count is inconsistent"
        )

    transports = set(_normalized_allowed_transports(allowed_source_transports))
    projection: list[dict[str, Any]] = []
    receipt_ids: set[str] = set()
    request_ids: set[tuple[str, str]] = set()
    for raw_row in raw_projection:
        if not isinstance(raw_row, dict) or set(raw_row) != _PROJECTION_FIELDS:
            raise StateLawsRetainedEvidenceSeedError(
                "source selection receipt has an invalid selected_projection row"
            )
        official_url = _canonical_url(raw_row.get("official_url"))
        if raw_row.get("official_url") != official_url:
            raise StateLawsRetainedEvidenceSeedError(
                "source selection receipt official_url is not canonical"
            )
        source_transport = str(raw_row.get("source_transport") or "").strip()
        if (
            not source_transport
            or raw_row.get("source_transport") != source_transport
            or source_transport not in transports
        ):
            raise StateLawsRetainedEvidenceSeedError(
                "source selection receipt names a disallowed source_transport"
            )
        row = {
            "content_sha256": _validated_sha256(
                raw_row.get("content_sha256"), field_name="content_sha256"
            ),
            "official_url": official_url,
            "receipt_sha256": _validated_sha256(
                raw_row.get("receipt_sha256"), field_name="receipt_sha256"
            ),
            "request_sha256": _validated_sha256(
                raw_row.get("request_sha256"), field_name="request_sha256"
            ),
            "source_transport": source_transport,
        }
        if row["receipt_sha256"] in receipt_ids:
            raise StateLawsRetainedEvidenceSeedError(
                "source selection receipt repeats one receipt_sha256"
            )
        request_id = (row["official_url"], row["request_sha256"])
        if request_id in request_ids:
            raise StateLawsRetainedEvidenceSeedError(
                "source selection receipt ambiguously pins one exact request twice"
            )
        receipt_ids.add(row["receipt_sha256"])
        request_ids.add(request_id)
        projection.append(row)

    ordered_projection = sorted(
        projection,
        key=lambda item: (
            item["official_url"],
            item["request_sha256"],
            item["receipt_sha256"],
        ),
    )
    if projection != ordered_projection:
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt selected_projection is not canonical"
        )
    projection_sha256 = hashlib.sha256(
        canonical_json_bytes(projection)
    ).hexdigest()
    declared_projection_sha256 = _validated_sha256(
        payload.get("selected_projection_sha256"),
        field_name="selected_projection_sha256",
    )
    if declared_projection_sha256 != projection_sha256:
        raise StateLawsRetainedEvidenceSeedError(
            "source selection receipt selected_projection failed SHA-256 verification"
        )
    return projection, resolved, receipt_sha256


def _select_entries_from_pinned_projection(
    ledger: StateLawMultiFetchAcquisitionLedger,
    *,
    projection: Sequence[Mapping[str, Any]],
) -> list[RetainedStateLawParserInput]:
    """Resolve every pinned receipt to one exact, fully replayed ledger entry."""

    entries_by_receipt: dict[str, list[RetainedStateLawParserInput]] = {}
    for entry in ledger.entries:
        entries_by_receipt.setdefault(entry.receipt.receipt_sha256, []).append(entry)

    selected: list[RetainedStateLawParserInput] = []
    for row in projection:
        receipt_sha256 = str(row["receipt_sha256"])
        matches = entries_by_receipt.get(receipt_sha256, [])
        if not matches:
            raise StateLawsRetainedEvidenceSeedError(
                "source selection receipt pins a receipt absent from the fully "
                f"verified source ledger: {receipt_sha256}"
            )
        if len(matches) != 1:
            raise StateLawsRetainedEvidenceSeedError(
                "source selection receipt does not resolve uniquely in the source "
                f"ledger: {receipt_sha256}"
            )
        entry = matches[0]
        if _selected_projection((entry,))[0] != dict(row):
            raise StateLawsRetainedEvidenceSeedError(
                "source selection receipt does not exactly match its retained "
                f"ledger entry: {receipt_sha256}"
            )
        selected.append(entry)
    return selected


def _link_or_copy(source: Path, destination: Path) -> str:
    if source.is_symlink() or not source.is_file():
        raise StateLawsRetainedEvidenceSeedError(
            f"retained evidence source is not a regular file: {source}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination, follow_symlinks=False)
        mode = "hardlink"
    except OSError as exc:
        if exc.errno not in {
            errno.EACCES,
            errno.EMLINK,
            errno.ENOTSUP,
            errno.EPERM,
            errno.EXDEV,
        }:
            raise
        shutil.copyfile(source, destination, follow_symlinks=False)
        mode = "copy"
    if destination.is_symlink() or not destination.is_file():
        raise StateLawsRetainedEvidenceSeedError(
            "seeded evidence target is not a regular file"
        )
    if file_sha256(source) != file_sha256(destination):
        raise StateLawsRetainedEvidenceSeedError(
            "seeded evidence target failed byte-for-byte verification"
        )
    return mode


def seed_retained_evidence_generation(
    *,
    source_root: str | Path,
    destination_root: str | Path,
    jurisdiction: str,
    parser_name: str,
    allowed_source_transports: Sequence[str] = ("direct",),
    include_urls: Iterable[str] | None = None,
    exclude_transport_unstable_receipt_sha256s: Sequence[str] = (),
    source_selection_receipt: str | Path | None = None,
    phase_bound_receipt_sha256s: Sequence[str] = (),
) -> RetainedEvidenceSeedReport:
    """Seed one fresh evidence generation from verified retained inputs.

    No destination jurisdiction directory may already exist.  The function
    performs no network I/O and does not copy frontier/completion receipts;
    those must be regenerated by a complete first parse and retained replay.
    Disallowed source transports, including unverifiable Wayback receipts, are
    skipped at source load and never published into the destination root.
    A caller may additionally name a fixity-valid historical receipt whose
    official URL alone has transport-invalid syntax.  That narrow exclusion is
    accepted only after envelope/body replay and is recorded under the v2
    migration schema so the repaired URL must be reacquired prospectively.
    Alternatively, ``source_selection_receipt`` may pin the exact projection
    from a prior in-root v1/v2 seed or union migration.  This permits a later
    conflicting observation to remain in the source ledger without silently
    changing the fresh generation's previously selected inputs.

    ``phase_bound_receipt_sha256s`` is reserved for a caller that has already
    validated one immutable two-phase live closure plan.  Every observation
    sharing a bound exact request identity must be named, so this opt-in seam
    cannot turn an unbound or partially bound conflict into parser evidence.
    The default selection remains fail-closed for different bodies returned
    by one exact request.
    """

    code = validate_jurisdiction(jurisdiction)
    parser = str(parser_name or "").strip()
    if not parser:
        raise StateLawsRetainedEvidenceSeedError(
            "parser_name must be non-empty"
        )
    unresolved_source = Path(source_root).expanduser()
    unresolved_destination = Path(destination_root).expanduser()
    if unresolved_source.is_symlink() or unresolved_destination.is_symlink():
        raise StateLawsRetainedEvidenceSeedError(
            "source and destination evidence roots must not be symlinks"
        )
    source = unresolved_source.resolve()
    destination = unresolved_destination.resolve()
    if source == destination:
        raise StateLawsRetainedEvidenceSeedError(
            "source and destination evidence roots must differ"
        )
    destination_jurisdiction = destination / code
    if destination_jurisdiction.exists() or destination_jurisdiction.is_symlink():
        raise StateLawsRetainedEvidenceSeedError(
            "destination jurisdiction evidence root must be absent"
        )

    transports = _normalized_allowed_transports(allowed_source_transports)
    if source_selection_receipt is not None and include_urls is not None:
        raise StateLawsRetainedEvidenceSeedError(
            "source_selection_receipt cannot be combined with include_urls"
        )
    if (
        source_selection_receipt is not None
        and exclude_transport_unstable_receipt_sha256s
    ):
        raise StateLawsRetainedEvidenceSeedError(
            "source_selection_receipt cannot be combined with transport-unstable "
            "receipt exclusions"
        )
    if phase_bound_receipt_sha256s and (
        include_urls is not None
        or source_selection_receipt is not None
        or exclude_transport_unstable_receipt_sha256s
    ):
        raise StateLawsRetainedEvidenceSeedError(
            "phase-bound receipt selection cannot be combined with URL, prior "
            "selection-receipt, or transport-unstable filters"
        )
    source_ledger = StateLawMultiFetchAcquisitionLedger(
        source,
        jurisdiction=code,
        parser_name=parser,
        allowed_source_transports=transports,
        excluded_transport_unstable_receipt_sha256s=(
            exclude_transport_unstable_receipt_sha256s
        ),
    )
    excluded_transport_unstable_receipts = (
        source_ledger.excluded_transport_unstable_receipts
    )
    pinned_receipt_path: Path | None = None
    pinned_receipt_sha256 = ""
    if source_selection_receipt is None:
        selected, duplicate_count, requested_urls = _select_entries(
            source_ledger,
            allowed_source_transports=transports,
            include_urls=include_urls,
            phase_bound_receipt_sha256s=phase_bound_receipt_sha256s,
        )
    else:
        pinned_projection, pinned_receipt_path, pinned_receipt_sha256 = (
            _load_source_selection_projection(
                source_selection_receipt,
                source=source,
                jurisdiction=code,
                parser_name=parser,
                allowed_source_transports=transports,
            )
        )
        selected = _select_entries_from_pinned_projection(
            source_ledger,
            projection=pinned_projection,
        )
        duplicate_count = len(source_ledger.entries) - len(selected)
        requested_urls = ()
    skipped_disallowed = source_ledger.skipped_disallowed_transport_count
    projection = _selected_projection(selected)
    projection_sha256 = hashlib.sha256(
        canonical_json_bytes(projection)
    ).hexdigest()
    unique_bodies = {
        str(entry.receipt.content.sha256): entry.body_path
        for entry in selected
        if entry.receipt.content is not None
    }
    if len(unique_bodies) == 0:
        raise StateLawsRetainedEvidenceSeedError(
            "selected retained inputs have no content-addressed bodies"
        )

    destination.mkdir(parents=True, exist_ok=True)
    hardlinked = 0
    copied = 0
    migration_receipt_sha256 = ""
    migration_receipt_relative = ""
    with tempfile.TemporaryDirectory(
        dir=destination,
        prefix=f".{code.lower()}-retained-seed-",
    ) as temporary_name:
        temporary_root = Path(temporary_name)
        staged_ledger = StateLawMultiFetchAcquisitionLedger(
            temporary_root,
            jurisdiction=code,
            parser_name=parser,
            load_existing=False,
        )
        for digest, body_path in sorted(unique_bodies.items()):
            if body_path.name != f"{digest}.bin":
                raise StateLawsRetainedEvidenceSeedError(
                    "source content object filename changed from its digest"
                )
            mode = _link_or_copy(
                body_path,
                staged_ledger.objects_dir / body_path.name,
            )
            hardlinked += mode == "hardlink"
            copied += mode == "copy"
        for entry in selected:
            mode = _link_or_copy(
                entry.evidence_path,
                staged_ledger.fetches_dir / entry.evidence_path.name,
            )
            hardlinked += mode == "hardlink"
            copied += mode == "copy"

        verified_staged = StateLawMultiFetchAcquisitionLedger(
            temporary_root,
            jurisdiction=code,
            parser_name=parser,
        )
        staged_projection = _selected_projection(verified_staged.entries)
        if staged_projection != projection:
            raise StateLawsRetainedEvidenceSeedError(
                "staged evidence projection differs after retained replay"
            )

        migration_schema = SCHEMA_VERSION
        if excluded_transport_unstable_receipts:
            migration_schema = TRANSPORT_UNSTABLE_EXCLUSION_SCHEMA_VERSION
        elif phase_bound_receipt_sha256s:
            migration_schema = PHASE_BOUND_SEED_SCHEMA_VERSION
        migration = {
            "allowed_source_transports": sorted(
                {str(value).strip() for value in allowed_source_transports}
            ),
            "authorizes_parser_admission": False,
            "destination_root": str(destination),
            "duplicate_request_observations_avoided": duplicate_count,
            "jurisdiction": code,
            "network_io_performed": False,
            "parser_name": parser,
            "requested_urls": list(requested_urls),
            "schema_version": migration_schema,
            "selected_parser_input_count": len(selected),
            "selected_projection": projection,
            "selected_projection_sha256": projection_sha256,
            "skipped_disallowed_transport_count": skipped_disallowed,
            "source_root": str(source),
            "unique_content_object_count": len(unique_bodies),
        }
        if excluded_transport_unstable_receipts:
            migration["excluded_transport_unstable_receipts"] = list(
                excluded_transport_unstable_receipts
            )
        if phase_bound_receipt_sha256s:
            migration["phase_bound_receipt_sha256s"] = sorted(
                {str(value) for value in phase_bound_receipt_sha256s}
            )
        if pinned_receipt_path is not None:
            migration["source_selection_receipt_path"] = str(
                pinned_receipt_path
            )
            migration["source_selection_receipt_sha256"] = (
                pinned_receipt_sha256
            )
        migration_bytes = canonical_json_bytes(migration)
        migration_receipt_sha256 = hashlib.sha256(migration_bytes).hexdigest()
        migration_receipt_relative = (
            f"migrations/{migration_receipt_sha256}.json"
        )
        atomic_write_bytes(
            staged_ledger.jurisdiction_root / migration_receipt_relative,
            migration_bytes,
        )

        os.replace(staged_ledger.jurisdiction_root, destination_jurisdiction)

    final_ledger = StateLawMultiFetchAcquisitionLedger(
        destination,
        jurisdiction=code,
        parser_name=parser,
    )
    if _selected_projection(final_ledger.entries) != projection:
        raise StateLawsRetainedEvidenceSeedError(
            "published evidence projection differs after retained replay"
        )
    migration_path = destination_jurisdiction / migration_receipt_relative
    if (
        migration_path.is_symlink()
        or not migration_path.is_file()
        or file_sha256(migration_path) != migration_receipt_sha256
    ):
        raise StateLawsRetainedEvidenceSeedError(
            "published evidence migration receipt failed fixity verification"
        )

    return RetainedEvidenceSeedReport(
        jurisdiction=code,
        parser_name=parser,
        source_root=str(source),
        destination_root=str(destination),
        allowed_source_transports=transports,
        requested_url_count=len(requested_urls),
        selected_parser_input_count=len(selected),
        duplicate_request_observations_avoided=duplicate_count,
        skipped_disallowed_transport_count=skipped_disallowed,
        unique_content_object_count=len(unique_bodies),
        hardlinked_file_count=hardlinked,
        copied_file_count=copied,
        selected_projection_sha256=projection_sha256,
        migration_receipt_path=str(migration_path),
        migration_receipt_sha256=migration_receipt_sha256,
        excluded_transport_unstable_receipt_count=len(
            excluded_transport_unstable_receipts
        ),
        excluded_transport_unstable_receipt_sha256s=tuple(
            row["receipt_sha256"]
            for row in excluded_transport_unstable_receipts
        ),
        schema_version=(
            TRANSPORT_UNSTABLE_EXCLUSION_SCHEMA_VERSION
            if excluded_transport_unstable_receipts
            else (
                PHASE_BOUND_SEED_SCHEMA_VERSION
                if phase_bound_receipt_sha256s
                else SCHEMA_VERSION
            )
        ),
    )


def seed_retained_evidence_union(
    *,
    sources: Sequence[RetainedEvidenceSeedSource | Mapping[str, Any]],
    destination_root: str | Path,
    jurisdiction: str,
    parser_name: str,
) -> RetainedEvidenceUnionReport:
    """Atomically union exact retained inputs from explicitly bounded ledgers.

    Source parser envelopes may differ.  Each selected input is therefore
    re-admitted under ``parser_name`` from its already verified body and
    transport receipt.  Re-admission is accepted only when it reproduces the
    original acquisition receipt SHA-256 exactly; otherwise the entire staged
    generation is discarded.  This permits a narrowly selected proof parser
    input to join a scraper ledger without weakening request/content identity.
    """

    code = validate_jurisdiction(jurisdiction)
    destination_parser = str(parser_name or "").strip()
    if not destination_parser:
        raise StateLawsRetainedEvidenceSeedError(
            "parser_name must be non-empty"
        )
    if not isinstance(sources, Sequence) or isinstance(
        sources, (str, bytes, bytearray)
    ) or not sources:
        raise StateLawsRetainedEvidenceSeedError(
            "multi-source retained evidence seed requires at least one source"
        )

    normalized_sources: list[RetainedEvidenceSeedSource] = []
    for raw_source in sources:
        if isinstance(raw_source, RetainedEvidenceSeedSource):
            source = raw_source
        elif isinstance(raw_source, Mapping):
            source = RetainedEvidenceSeedSource(
                source_root=str(raw_source.get("source_root") or ""),
                parser_name=str(raw_source.get("parser_name") or ""),
                allowed_source_transports=tuple(
                    str(value or "").strip()
                    for value in list(
                        raw_source.get("allowed_source_transports") or []
                    )
                    if str(value or "").strip()
                ),
                include_urls=tuple(
                    str(value or "").strip()
                    for value in list(raw_source.get("include_urls") or [])
                    if str(value or "").strip()
                ),
            )
        else:
            raise StateLawsRetainedEvidenceSeedError(
                "multi-source retained evidence source must be a specification"
            )
        source_parser = str(source.parser_name or "").strip()
        if not source_parser:
            raise StateLawsRetainedEvidenceSeedError(
                "every retained evidence source requires its exact parser_name"
            )
        transports = tuple(
            sorted(
                {
                    str(value or "").strip()
                    for value in source.allowed_source_transports
                    if str(value or "").strip()
                }
            )
        )
        if not transports:
            raise StateLawsRetainedEvidenceSeedError(
                "every retained evidence source requires an allowed transport"
            )
        normalized_sources.append(
            RetainedEvidenceSeedSource(
                source_root=source.source_root,
                parser_name=source_parser,
                allowed_source_transports=transports,
                include_urls=tuple(
                    sorted({_canonical_url(value) for value in source.include_urls})
                ),
            )
        )

    unresolved_destination = Path(destination_root).expanduser()
    if unresolved_destination.is_symlink():
        raise StateLawsRetainedEvidenceSeedError(
            "destination evidence root must not be a symlink"
        )
    destination = unresolved_destination.resolve()
    destination_jurisdiction = destination / code
    if destination_jurisdiction.exists() or destination_jurisdiction.is_symlink():
        raise StateLawsRetainedEvidenceSeedError(
            "destination jurisdiction evidence root must be absent"
        )

    selections: list[_UnionSelection] = []
    duplicate_count = 0
    skipped_disallowed = 0
    source_roots: list[Path] = []
    source_projection_rows: list[dict[str, Any]] = []
    for source in normalized_sources:
        if not str(source.source_root or "").strip():
            raise StateLawsRetainedEvidenceSeedError(
                "every retained evidence source requires source_root"
            )
        unresolved_source = Path(source.source_root).expanduser()
        if unresolved_source.is_symlink():
            raise StateLawsRetainedEvidenceSeedError(
                "source evidence root must not be a symlink"
            )
        resolved_source = unresolved_source.resolve()
        if resolved_source == destination:
            raise StateLawsRetainedEvidenceSeedError(
                "source and destination evidence roots must differ"
            )
        source_roots.append(resolved_source)
        source_ledger = StateLawMultiFetchAcquisitionLedger(
            resolved_source,
            jurisdiction=code,
            parser_name=source.parser_name,
            allowed_source_transports=source.allowed_source_transports,
        )
        selected, local_duplicates, requested_urls = _select_entries(
            source_ledger,
            allowed_source_transports=source.allowed_source_transports,
            include_urls=(source.include_urls if source.include_urls else None),
        )
        duplicate_count += local_duplicates
        skipped_disallowed += source_ledger.skipped_disallowed_transport_count
        for entry in selected:
            selections.append(
                _UnionSelection(
                    entry=entry,
                    source_root=resolved_source,
                    source_parser_name=source.parser_name,
                )
            )
        source_projection_rows.append(
            {
                "allowed_source_transports": list(
                    source.allowed_source_transports
                ),
                "parser_name": source.parser_name,
                "requested_urls": list(requested_urls),
                "selected_parser_input_count": len(selected),
                "source_root": str(resolved_source),
            }
        )

    grouped: dict[tuple[str, bytes], list[_UnionSelection]] = {}
    for selection in selections:
        grouped.setdefault(_request_identity(selection.entry), []).append(selection)
    selected_union: list[_UnionSelection] = []
    for identity in sorted(grouped, key=lambda item: (item[0], item[1])):
        observations = grouped[identity]
        digests = {
            str(item.entry.receipt.content.sha256)
            for item in observations
            if item.entry.receipt.content is not None
        }
        if len(digests) != 1:
            raise StateLawsRetainedEvidenceSeedError(
                "multi-source retained observations disagree for one exact request: "
                f"{identity[0]}"
            )
        chosen = min(
            observations,
            key=lambda item: (
                str(item.source_root),
                item.source_parser_name,
                item.entry.receipt.receipt_sha256,
            ),
        )
        duplicate_count += len(observations) - 1
        selected_union.append(chosen)

    selected_union.sort(
        key=lambda item: (
            _canonical_url(item.entry.receipt.endpoint),
            hashlib.sha256(
                canonical_json_bytes(item.entry.receipt.sanitized_request)
            ).hexdigest(),
            item.entry.receipt.receipt_sha256,
        )
    )
    entries = [item.entry for item in selected_union]
    projection = _selected_projection(entries)
    projection_sha256 = hashlib.sha256(
        canonical_json_bytes(projection)
    ).hexdigest()
    unique_bodies = {
        str(item.entry.receipt.content.sha256): item.entry.body_path
        for item in selected_union
        if item.entry.receipt.content is not None
    }
    if not unique_bodies:
        raise StateLawsRetainedEvidenceSeedError(
            "multi-source retained evidence selection is empty"
        )

    destination.mkdir(parents=True, exist_ok=True)
    hardlinked = 0
    copied = 0
    rebound = 0
    migration_receipt_sha256 = ""
    migration_receipt_relative = ""
    with tempfile.TemporaryDirectory(
        dir=destination,
        prefix=f".{code.lower()}-retained-union-",
    ) as temporary_name:
        temporary_root = Path(temporary_name)
        staged_ledger = StateLawMultiFetchAcquisitionLedger(
            temporary_root,
            jurisdiction=code,
            parser_name=destination_parser,
            load_existing=False,
        )
        for digest, body_path in sorted(unique_bodies.items()):
            if body_path.name != f"{digest}.bin":
                raise StateLawsRetainedEvidenceSeedError(
                    "source content object filename changed from its digest"
                )
            mode = _link_or_copy(
                body_path,
                staged_ledger.objects_dir / body_path.name,
            )
            hardlinked += mode == "hardlink"
            copied += mode == "copy"

        rebound_rows: list[dict[str, Any]] = []
        for selection in selected_union:
            entry = selection.entry
            receipt = entry.receipt
            body = entry.body_path.read_bytes()
            rebound_entry = staged_ledger.retain_parser_input(
                official_url=receipt.endpoint,
                body=body,
                transport_receipt=entry.transport_receipt,
                retrieved_at=receipt.retrieved_at,
                response_status=receipt.response_status,
                media_type=receipt.media_type,
                sanitized_request=receipt.sanitized_request,
                pagination=receipt.pagination,
                network_used=False,
                outcome_kind=receipt.outcome_kind,
            )
            if rebound_entry.receipt.receipt_sha256 != receipt.receipt_sha256:
                raise StateLawsRetainedEvidenceSeedError(
                    "parser rebinding changed an acquisition receipt identity: "
                    f"{receipt.endpoint}"
                )
            rebound += 1
            rebound_rows.append(
                {
                    "content_sha256": str(receipt.content.sha256),
                    "destination_parser_name": destination_parser,
                    "official_url": receipt.endpoint,
                    "receipt_sha256": receipt.receipt_sha256,
                    "source_evidence_sha256": file_sha256(entry.evidence_path),
                    "source_parser_name": selection.source_parser_name,
                    "source_root": str(selection.source_root),
                }
            )

        verified_staged = StateLawMultiFetchAcquisitionLedger(
            temporary_root,
            jurisdiction=code,
            parser_name=destination_parser,
        )
        if _selected_projection(verified_staged.entries) != projection:
            raise StateLawsRetainedEvidenceSeedError(
                "staged multi-source projection differs after retained replay"
            )
        migration = {
            "authorizes_parser_admission": False,
            "destination_root": str(destination),
            "duplicate_request_observations_avoided": duplicate_count,
            "jurisdiction": code,
            "network_io_performed": False,
            "parser_name": destination_parser,
            "rebound_parser_inputs": rebound_rows,
            "schema_version": UNION_SCHEMA_VERSION,
            "selected_parser_input_count": len(selected_union),
            "selected_projection": projection,
            "selected_projection_sha256": projection_sha256,
            "skipped_disallowed_transport_count": skipped_disallowed,
            "sources": source_projection_rows,
            "unique_content_object_count": len(unique_bodies),
        }
        migration_bytes = canonical_json_bytes(migration)
        migration_receipt_sha256 = hashlib.sha256(migration_bytes).hexdigest()
        migration_receipt_relative = f"migrations/{migration_receipt_sha256}.json"
        atomic_write_bytes(
            staged_ledger.jurisdiction_root / migration_receipt_relative,
            migration_bytes,
        )
        os.replace(staged_ledger.jurisdiction_root, destination_jurisdiction)

    final_ledger = StateLawMultiFetchAcquisitionLedger(
        destination,
        jurisdiction=code,
        parser_name=destination_parser,
    )
    if _selected_projection(final_ledger.entries) != projection:
        raise StateLawsRetainedEvidenceSeedError(
            "published multi-source projection differs after retained replay"
        )
    migration_path = destination_jurisdiction / migration_receipt_relative
    if (
        migration_path.is_symlink()
        or not migration_path.is_file()
        or file_sha256(migration_path) != migration_receipt_sha256
    ):
        raise StateLawsRetainedEvidenceSeedError(
            "published multi-source migration receipt failed fixity verification"
        )
    return RetainedEvidenceUnionReport(
        jurisdiction=code,
        parser_name=destination_parser,
        source_roots=tuple(str(path) for path in source_roots),
        source_parser_names=tuple(
            source.parser_name for source in normalized_sources
        ),
        destination_root=str(destination),
        selected_parser_input_count=len(selected_union),
        duplicate_request_observations_avoided=duplicate_count,
        skipped_disallowed_transport_count=skipped_disallowed,
        unique_content_object_count=len(unique_bodies),
        hardlinked_file_count=hardlinked,
        copied_file_count=copied,
        rebound_parser_input_count=rebound,
        selected_projection_sha256=projection_sha256,
        migration_receipt_path=str(migration_path),
        migration_receipt_sha256=migration_receipt_sha256,
    )


__all__ = [
    "PHASE_BOUND_SEED_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "TRANSPORT_UNSTABLE_EXCLUSION_SCHEMA_VERSION",
    "RetainedEvidenceSeedReport",
    "RetainedEvidenceSeedSource",
    "RetainedEvidenceUnionReport",
    "StateLawsRetainedEvidenceSeedError",
    "seed_retained_evidence_generation",
    "seed_retained_evidence_union",
]
