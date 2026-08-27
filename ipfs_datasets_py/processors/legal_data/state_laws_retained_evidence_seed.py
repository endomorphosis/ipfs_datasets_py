"""Verified, zero-network seeding of a fresh state-law evidence generation.

Some strict corpus repairs must replace stale archive observations without
discarding thousands of valid direct-current parser inputs.  This module
copies no authority claims and performs no acquisition.  It first loads and
reverifies the source :class:`StateLawMultiFetchAcquisitionLedger`, selects a
bounded set of already-authorizing parser inputs by exact transport and URL,
deduplicates identical request identities, and stages their immutable files in
a fresh jurisdiction root.  Content objects are hard-linked when possible and
byte-copied only across filesystems.

The destination is published by one directory rename only after a second
ledger instance has replayed every staged receipt and body.  A migration
receipt records what was reused, but that receipt is diagnostic: parser
admission remains authorized solely by the original byte-bound fetch files.
"""

from __future__ import annotations

import errno
import hashlib
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
    unique_content_object_count: int
    hardlinked_file_count: int
    copied_file_count: int
    selected_projection_sha256: str
    migration_receipt_path: str
    migration_receipt_sha256: str
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
    unique_content_object_count: int
    hardlinked_file_count: int
    copied_file_count: int
    rebound_parser_input_count: int
    selected_projection_sha256: str
    migration_receipt_path: str
    migration_receipt_sha256: str
    network_io_performed: bool = False
    schema_version: str = "state-laws-retained-evidence-union-v1"

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


def _select_entries(
    ledger: StateLawMultiFetchAcquisitionLedger,
    *,
    allowed_source_transports: Sequence[str],
    include_urls: Iterable[str] | None,
) -> tuple[list[RetainedStateLawParserInput], int, tuple[str, ...]]:
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

    selected: list[RetainedStateLawParserInput] = []
    for identity in sorted(grouped, key=lambda item: (item[0], item[1])):
        observations = grouped[identity]
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
) -> RetainedEvidenceSeedReport:
    """Seed one fresh evidence generation from verified retained inputs.

    No destination jurisdiction directory may already exist.  The function
    performs no network I/O and does not copy frontier/completion receipts;
    those must be regenerated by a complete first parse and retained replay.
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

    source_ledger = StateLawMultiFetchAcquisitionLedger(
        source,
        jurisdiction=code,
        parser_name=parser,
    )
    selected, duplicate_count, requested_urls = _select_entries(
        source_ledger,
        allowed_source_transports=allowed_source_transports,
        include_urls=include_urls,
    )
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
            "schema_version": SCHEMA_VERSION,
            "selected_parser_input_count": len(selected),
            "selected_projection": projection,
            "selected_projection_sha256": projection_sha256,
            "source_root": str(source),
            "unique_content_object_count": len(unique_bodies),
        }
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
        allowed_source_transports=tuple(
            sorted({str(value).strip() for value in allowed_source_transports})
        ),
        requested_url_count=len(requested_urls),
        selected_parser_input_count=len(selected),
        duplicate_request_observations_avoided=duplicate_count,
        unique_content_object_count=len(unique_bodies),
        hardlinked_file_count=hardlinked,
        copied_file_count=copied,
        selected_projection_sha256=projection_sha256,
        migration_receipt_path=str(migration_path),
        migration_receipt_sha256=migration_receipt_sha256,
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
        )
        selected, local_duplicates, requested_urls = _select_entries(
            source_ledger,
            allowed_source_transports=source.allowed_source_transports,
            include_urls=(source.include_urls if source.include_urls else None),
        )
        duplicate_count += local_duplicates
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
            "schema_version": "state-laws-retained-evidence-union-v1",
            "selected_parser_input_count": len(selected_union),
            "selected_projection": projection,
            "selected_projection_sha256": projection_sha256,
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
        unique_content_object_count=len(unique_bodies),
        hardlinked_file_count=hardlinked,
        copied_file_count=copied,
        rebound_parser_input_count=rebound,
        selected_projection_sha256=projection_sha256,
        migration_receipt_path=str(migration_path),
        migration_receipt_sha256=migration_receipt_sha256,
    )


__all__ = [
    "SCHEMA_VERSION",
    "RetainedEvidenceSeedReport",
    "RetainedEvidenceSeedSource",
    "RetainedEvidenceUnionReport",
    "StateLawsRetainedEvidenceSeedError",
    "seed_retained_evidence_generation",
    "seed_retained_evidence_union",
]
