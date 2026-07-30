"""Deterministic wallet dataset export (JSONL, Parquet/Arrow, optional CAR).

Exports are data exports, not asset transfers.  A completed export always
produces an :class:`ExportReceipt` wrapping a fully accounted
:class:`~models.ExportManifest` with scope, schema/processor versions,
provider capability, digests/CIDs, counts, positions, finality distribution,
warnings, raw-payload policy, and before/after checkpoints.

JSONL is the interchange baseline; Parquet/Arrow is the analytical baseline.
IPLD/CAR export is optional and only attempted when explicitly requested and
when a CAR writer is injectable—JSONL and Parquet contracts do not depend on
it.

Importing this module performs no network I/O.  Parquet support uses optional
``pyarrow`` only inside export methods.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .canonical import canonical_json, canonical_json_bytes, content_digest
from .errors import ExportError, InvalidRequestError, UnsupportedCapabilityError
from .models import (
    EXPORT_MANIFEST_SCHEMA_VERSION,
    ChainRef,
    ExportManifest,
    ExportPartition,
    ExportStatus,
    Finality,
    LedgerCursor,
    Provenance,
    RawPayloadPolicy,
    ensure_secret_safe,
)
from .protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    DatasetSink,
    OperationContext,
    RecordBatch,
)
from .storage import (
    StreamingDatasetSink,
    record_as_dict,
    record_finality,
    record_sequence,
)


EXPORT_RECEIPT_SCHEMA_VERSION = "wallet-export-receipt-v1"
DEFAULT_PROCESSOR_VERSION = "wallet-exporter@1.0.0"
DEFAULT_NORMALIZED_SCHEMA_MAJOR = 1


class ExportFormat(StrEnum):
    """Supported deterministic export formats."""

    JSONL = "jsonl"
    PARQUET = "parquet"
    ARROW = "arrow"
    CAR = "car"  # optional; requires an injectable CAR writer


def _required_str(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _ensure_export_safe(value: object) -> None:
    try:
        ensure_secret_safe(value)
    except ValueError as exc:
        raise ExportError(str(exc)) from None


@dataclass(frozen=True, slots=True)
class ExportReceipt:
    """Versioned receipt returned by :class:`Exporter` implementations."""

    manifest: ExportManifest
    status: ExportStatus
    output_dir: str
    formats: tuple[str, ...]
    processor_version: str
    normalized_schema_major: int
    provider_capabilities: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    partial: bool = False
    receipt_id: str = field(init=False)
    schema_version: str = field(default=EXPORT_RECEIPT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, ExportManifest):
            raise ExportError("manifest must be an ExportManifest")
        if not isinstance(self.status, ExportStatus):
            raise ExportError("status must be an ExportStatus")
        object.__setattr__(self, "output_dir", _required_str(self.output_dir, "output_dir"))
        object.__setattr__(self, "formats", tuple(self.formats))
        if not self.formats:
            raise ExportError("formats must not be empty")
        for fmt in self.formats:
            _required_str(fmt, "format")
        object.__setattr__(
            self,
            "processor_version",
            _required_str(self.processor_version, "processor_version"),
        )
        _positive_int(self.normalized_schema_major, "normalized_schema_major")
        object.__setattr__(
            self, "provider_capabilities", tuple(self.provider_capabilities)
        )
        object.__setattr__(self, "warnings", tuple(self.warnings))
        _ensure_export_safe(
            {
                "output_dir": self.output_dir,
                "formats": self.formats,
                "processor_version": self.processor_version,
                "provider_capabilities": self.provider_capabilities,
                "warnings": self.warnings,
            }
        )
        object.__setattr__(
            self,
            "receipt_id",
            content_digest(
                {
                    "manifest_id": self.manifest.manifest_id,
                    "status": self.status.value,
                    "formats": list(self.formats),
                    "output_dir": self.output_dir,
                }
            ),
        )
        _ensure_export_safe(self.to_dict())

    @property
    def complete(self) -> bool:
        return self.status is ExportStatus.COMPLETE and not self.partial

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "status": self.status.value,
            "partial": self.partial,
            "output_dir": self.output_dir,
            "formats": list(self.formats),
            "processor_version": self.processor_version,
            "normalized_schema_major": self.normalized_schema_major,
            "provider_capabilities": list(self.provider_capabilities),
            "warnings": list(self.warnings),
            "manifest": self.manifest.to_dict(),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())


def write_jsonl(
    records: Sequence[Mapping[str, Any] | object],
    path: str | Path,
) -> ExportPartition:
    """Write records as deterministic one-JSON-object-per-line UTF-8."""

    lines: list[str] = []
    types: set[str] = set()
    sequences: list[int] = []
    for record in records:
        payload = record_as_dict(record)
        _ensure_export_safe(payload)
        lines.append(canonical_json(payload))
        record_type = payload.get("record_type")
        if isinstance(record_type, str) and record_type:
            types.add(record_type)
        sequence = record_sequence(record)
        if sequence is not None:
            sequences.append(sequence)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
    digest = f"sha256:{__import__('hashlib').sha256(body).hexdigest()}"
    return ExportPartition(
        path=str(path.name),
        format=ExportFormat.JSONL.value,
        record_count=len(lines),
        byte_count=len(body),
        digest=digest,
        record_types=tuple(sorted(types)),
        min_position=min(sequences) if sequences else None,
        max_position=max(sequences) if sequences else None,
    )


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read a deterministic JSONL partition back into dict records."""

    import json

    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return []
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ExportError("JSONL lines must be JSON objects")
        records.append(payload)
    return records


def write_parquet(
    records: Sequence[Mapping[str, Any] | object],
    path: str | Path,
) -> ExportPartition:
    """Write records as a deterministic Parquet table via pyarrow.

    Nested structures are stored as canonical JSON strings so round trips
    preserve exact types and IDs without Arrow schema drift across chains.
    """

    payloads = [record_as_dict(record) for record in records]
    for payload in payloads:
        _ensure_export_safe(payload)
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise UnsupportedCapabilityError(
            "parquet export requires the optional 'pyarrow' dependency"
        ) from exc
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    types: set[str] = set()
    sequences: list[int] = []
    rows = {
        "record_id": [],
        "record_type": [],
        "finality": [],
        "sequence": [],
        "payload_json": [],
    }
    for payload in payloads:
        record_id = str(payload.get("record_id") or "")
        record_type = str(payload.get("record_type") or "")
        finality = str(payload.get("finality") or Finality.UNKNOWN.value)
        position = payload.get("ledger_position") or {}
        sequence = position.get("sequence") if isinstance(position, Mapping) else None
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            sequence = None
        rows["record_id"].append(record_id)
        rows["record_type"].append(record_type)
        rows["finality"].append(finality)
        rows["sequence"].append(sequence)
        rows["payload_json"].append(canonical_json(payload))
        if record_type:
            types.add(record_type)
        if sequence is not None:
            sequences.append(sequence)

    table = pa.table(
        {
            "record_id": pa.array(rows["record_id"], type=pa.string()),
            "record_type": pa.array(rows["record_type"], type=pa.string()),
            "finality": pa.array(rows["finality"], type=pa.string()),
            "sequence": pa.array(rows["sequence"], type=pa.int64()),
            "payload_json": pa.array(rows["payload_json"], type=pa.string()),
        }
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(
        table,
        tmp,
        compression="snappy",
        coerce_timestamps="us",
        use_dictionary=False,
        write_statistics=True,
    )
    tmp.replace(path)
    body = path.read_bytes()
    digest = f"sha256:{__import__('hashlib').sha256(body).hexdigest()}"
    return ExportPartition(
        path=str(path.name),
        format=ExportFormat.PARQUET.value,
        record_count=len(payloads),
        byte_count=len(body),
        digest=digest,
        record_types=tuple(sorted(types)),
        min_position=min(sequences) if sequences else None,
        max_position=max(sequences) if sequences else None,
    )


def read_parquet(path: str | Path) -> list[dict[str, Any]]:
    """Read a Parquet partition back into dict records (exact payload_json)."""

    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedCapabilityError(
            "parquet import requires the optional 'pyarrow' dependency"
        ) from exc
    import json

    table = pq.read_table(path)
    column = table.column("payload_json")
    records: list[dict[str, Any]] = []
    for i in range(len(column)):
        raw = column[i].as_py()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ExportError("parquet payload_json must decode to an object")
        records.append(payload)
    return records


def verify_manifest(manifest: ExportManifest) -> None:
    """Fail closed when a manifest's internal accounting is inconsistent."""

    if not isinstance(manifest, ExportManifest):
        raise ExportError("manifest must be an ExportManifest")
    if sum(part.record_count for part in manifest.partitions) != manifest.record_count:
        raise ExportError("partition record counts must equal record_count")
    if sum(manifest.finality_counts.values()) != manifest.record_count:
        raise ExportError("finality counts must equal record_count")
    if manifest.warning_count != len(manifest.warnings):
        raise ExportError("warning_count must equal the number of warnings")
    for part in manifest.partitions:
        if part.digest is None and part.cid is None:
            raise ExportError("each partition requires a digest or CID")


def build_finality_counts(
    records: Sequence[object],
) -> Mapping[Finality, int]:
    counts: dict[Finality, int] = {}
    for record in records:
        state = record_finality(record)
        counts[state] = counts.get(state, 0) + 1
    return MappingProxyType(counts)


def build_export_manifest(
    *,
    chain: ChainRef,
    provenance: Provenance,
    status: ExportStatus,
    raw_payload_policy: RawPayloadPolicy,
    partitions: Sequence[ExportPartition],
    records: Sequence[object],
    started_at: datetime,
    completed_at: datetime | None = None,
    checkpoint_before: LedgerCursor | None = None,
    checkpoint_after: LedgerCursor | None = None,
    warnings: Sequence[str] = (),
    finality_counts: Mapping[Finality, int] | None = None,
) -> ExportManifest:
    """Construct a fully accounted :class:`ExportManifest` for *records*."""

    completed = completed_at or _utc_now()
    warning_list = tuple(warnings)
    _ensure_export_safe(warning_list)
    counts = (
        MappingProxyType(dict(finality_counts))
        if finality_counts is not None
        else build_finality_counts(records)
    )
    # Empty exports still need a zero-sum finality map.
    if not counts and not records:
        counts = MappingProxyType({})
    record_count = len(records)
    if sum(part.record_count for part in partitions) != record_count:
        # When exporting the same logical rows in multiple formats, only the
        # primary partition set should be passed here. Multi-format exporters
        # call this once per format group or pass an explicit record_count via
        # partitions that already sum correctly.
        raise ExportError(
            "partition record counts must equal the number of exported records"
        )
    return ExportManifest(
        chain=chain,
        provenance=provenance,
        status=status,
        raw_payload_policy=raw_payload_policy,
        partitions=tuple(partitions),
        record_count=record_count,
        warning_count=len(warning_list),
        finality_counts=counts,
        started_at=started_at,
        completed_at=completed,
        checkpoint_before=checkpoint_before,
        checkpoint_after=checkpoint_after,
        warnings=warning_list,
    )


class WalletDatasetExporter:
    """Reference :class:`~protocols.Exporter` for JSONL and Parquet/Arrow.

    Optional CAR export is advertised only when ``enable_car=True`` and a
    ``car_writer`` callable is supplied; otherwise requesting CAR fails with
    :class:`UnsupportedCapabilityError` without affecting JSONL/Parquet.
    """

    def __init__(
        self,
        *,
        chain: ChainRef,
        output_dir: str | Path,
        formats: Sequence[ExportFormat | str] = (ExportFormat.JSONL,),
        processor_version: str = DEFAULT_PROCESSOR_VERSION,
        normalized_schema_major: int = DEFAULT_NORMALIZED_SCHEMA_MAJOR,
        raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.OMITTED,
        provider: str = "wallet-exporter",
        provider_kind: str = "dataset",
        provider_capabilities: Sequence[str] = (),
        enable_car: bool = False,
        car_writer: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        if not isinstance(chain, ChainRef):
            raise InvalidRequestError("chain must be a ChainRef")
        self._chain = chain
        self._output_dir = Path(output_dir)
        normalized_formats: list[ExportFormat] = []
        for fmt in formats:
            normalized_formats.append(
                fmt if isinstance(fmt, ExportFormat) else ExportFormat(str(fmt))
            )
        if not normalized_formats:
            raise InvalidRequestError("formats must not be empty")
        self._formats = tuple(normalized_formats)
        self._processor_version = _required_str(processor_version, "processor_version")
        self._normalized_schema_major = _positive_int(
            normalized_schema_major, "normalized_schema_major"
        )
        if not isinstance(raw_payload_policy, RawPayloadPolicy):
            raise InvalidRequestError("raw_payload_policy must be a RawPayloadPolicy")
        self._raw_payload_policy = raw_payload_policy
        self._provider = _required_str(provider, "provider")
        self._provider_kind = _required_str(provider_kind, "provider_kind")
        self._provider_capabilities = tuple(provider_capabilities)
        _ensure_export_safe(
            {
                "chain": self._chain.to_dict(),
                "output_dir": str(self._output_dir),
                "formats": [fmt.value for fmt in self._formats],
                "processor_version": self._processor_version,
                "provider": self._provider,
                "provider_kind": self._provider_kind,
                "provider_capabilities": self._provider_capabilities,
            }
        )
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._enable_car = bool(enable_car)
        self._car_writer = car_writer
        self._clock = clock or _utc_now
        features = {Capability.DATASET_EXPORT}
        if ExportFormat.JSONL in self._formats:
            features.add(Capability.DATASET_EXPORT)
        self._capabilities = Capabilities(
            provider=self._provider,
            chain_namespaces=frozenset({chain.namespace}),
            features=frozenset(features),
            metadata={
                "formats": [fmt.value for fmt in self._formats],
                "processor_version": self._processor_version,
                "normalized_schema_major": self._normalized_schema_major,
                "car_enabled": self._enable_car and self._car_writer is not None,
            },
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    async def export_records(
        self,
        records: Sequence[object],
        *,
        context: OperationContext,
        scope: str,
        status: ExportStatus = ExportStatus.COMPLETE,
        checkpoint_before: LedgerCursor | None = None,
        checkpoint_after: LedgerCursor | None = None,
        warnings: Sequence[str] = (),
        sink: DatasetSink | None = None,
    ) -> ExportReceipt:
        """Export *records* to the configured formats and return a receipt."""

        context.check_active()
        scope = _required_str(scope, "scope")
        started_at = self._clock()
        if not isinstance(started_at, datetime):
            raise ExportError("clock must return a datetime")

        if sink is not None:
            batch = RecordBatch(tuple(records), response_bytes=0)
            await sink.write(batch, context=context)

        partitions: list[ExportPartition] = []
        written_formats: list[str] = []
        primary_records = list(records)
        export_warnings = list(warnings)
        _ensure_export_safe(export_warnings)
        for record in primary_records:
            _ensure_export_safe(record_as_dict(record))

        # Multi-format exports write the same logical rows once per format.
        # Manifest accounting uses the first format's partition as the record
        # count source; additional formats are listed as sidecar partitions
        # with matching record_count so verify_manifest can check the primary
        # group.  We therefore emit one logical partition group per format but
        # set record_count on the manifest from the row set, not the sum of
        # all formats.
        logical_partitions: list[ExportPartition] = []
        for index, fmt in enumerate(self._formats):
            if fmt is ExportFormat.JSONL:
                part = write_jsonl(
                    primary_records,
                    self._output_dir / f"records-{index:03d}.jsonl",
                )
            elif fmt is ExportFormat.PARQUET:
                part = write_parquet(
                    primary_records,
                    self._output_dir / f"records-{index:03d}.parquet",
                )
            elif fmt is ExportFormat.ARROW:
                # Arrow IPC uses the same column contract as Parquet.
                part = self._write_arrow(
                    primary_records,
                    self._output_dir / f"records-{index:03d}.arrow",
                )
            elif fmt is ExportFormat.CAR:
                part = self._write_car(
                    primary_records,
                    self._output_dir / f"records-{index:03d}.car",
                    context=context,
                )
            else:  # pragma: no cover
                raise UnsupportedCapabilityError(f"unsupported export format: {fmt}")
            partitions.append(part)
            written_formats.append(fmt.value)
            if index == 0:
                logical_partitions.append(part)

        # Manifest partitions: primary format only for record_count identity;
        # attach remaining formats via extensions-equivalent sidecar list in
        # a second partition set when only one format is present, or include
        # all partitions when they share the same record_count and we treat
        # them as alternate encodings of the same set.
        if len(partitions) == 1:
            manifest_partitions: tuple[ExportPartition, ...] = tuple(partitions)
            manifest_record_count = partitions[0].record_count
        else:
            # All formats describe the same logical row set; export the primary
            # partition in the manifest and store alternate encodings as
            # additional partitions with zero contribution by rewriting the
            # primary-only set and recording sidecars in warnings metadata.
            manifest_partitions = (logical_partitions[0],)
            manifest_record_count = logical_partitions[0].record_count
            for sidecar in partitions[1:]:
                export_warnings.append(
                    f"sidecar_format:{sidecar.format}:{sidecar.path}:{sidecar.digest}"
                )

        provenance = Provenance(
            provider=self._provider,
            provider_kind=self._provider_kind,
            request_id=context.request_id,
            scope=scope,
            observed_at=started_at,
        )
        completed_at = self._clock()
        # Rebuild finality from records (not partitions).
        finality = build_finality_counts(primary_records)
        # Empty export: finality_counts may be empty mapping — model requires
        # sum == record_count, which holds for empty.
        if not primary_records:
            finality = MappingProxyType({})

        # When sidecars exist, partition record counts for the manifest use only
        # the primary partition so accounting matches the logical row set.
        try:
            manifest = ExportManifest(
                chain=self._chain,
                provenance=provenance,
                status=status,
                raw_payload_policy=self._raw_payload_policy,
                partitions=manifest_partitions,
                record_count=manifest_record_count,
                warning_count=len(export_warnings),
                finality_counts=finality,
                started_at=started_at,
                completed_at=completed_at,
                checkpoint_before=checkpoint_before,
                checkpoint_after=checkpoint_after,
                warnings=tuple(export_warnings),
            )
        except ValueError as exc:
            raise ExportError(str(exc)) from exc

        verify_manifest(manifest)
        # Persist manifest next to partitions for offline verification.
        manifest_path = self._output_dir / "export-manifest.json"
        manifest_path.write_text(manifest.to_canonical_json() + "\n", encoding="utf-8")
        # Persist full multi-format partition index (including sidecars).
        index_path = self._output_dir / "export-partitions.json"
        index_path.write_bytes(
            canonical_json_bytes(
                {
                    "formats": written_formats,
                    "partitions": [part.to_dict() for part in partitions],
                    "provider_capabilities": list(self._provider_capabilities),
                    "processor_version": self._processor_version,
                    "normalized_schema_major": self._normalized_schema_major,
                    "manifest_schema": EXPORT_MANIFEST_SCHEMA_VERSION,
                }
            )
        )

        if sink is not None:
            await sink.commit(manifest, context=context)

        partial = status is not ExportStatus.COMPLETE
        return ExportReceipt(
            manifest=manifest,
            status=status,
            output_dir=str(self._output_dir),
            formats=tuple(written_formats),
            processor_version=self._processor_version,
            normalized_schema_major=self._normalized_schema_major,
            provider_capabilities=self._provider_capabilities,
            warnings=tuple(export_warnings),
            partial=partial,
        )

    def _write_arrow(
        self,
        records: Sequence[object],
        path: Path,
    ) -> ExportPartition:
        try:
            import pyarrow as pa
            import pyarrow.ipc as ipc
        except ImportError as exc:  # pragma: no cover
            raise UnsupportedCapabilityError(
                "arrow export requires the optional 'pyarrow' dependency"
            ) from exc

        payloads = [record_as_dict(record) for record in records]
        types: set[str] = set()
        sequences: list[int] = []
        record_ids: list[str] = []
        record_types: list[str] = []
        finalities: list[str] = []
        seq_col: list[int | None] = []
        payload_json: list[str] = []
        for payload in payloads:
            rid = str(payload.get("record_id") or "")
            rtype = str(payload.get("record_type") or "")
            finality = str(payload.get("finality") or Finality.UNKNOWN.value)
            position = payload.get("ledger_position") or {}
            sequence = position.get("sequence") if isinstance(position, Mapping) else None
            if not isinstance(sequence, int) or isinstance(sequence, bool):
                sequence = None
            record_ids.append(rid)
            record_types.append(rtype)
            finalities.append(finality)
            seq_col.append(sequence)
            payload_json.append(canonical_json(payload))
            if rtype:
                types.add(rtype)
            if sequence is not None:
                sequences.append(sequence)
        table = pa.table(
            {
                "record_id": pa.array(record_ids, type=pa.string()),
                "record_type": pa.array(record_types, type=pa.string()),
                "finality": pa.array(finalities, type=pa.string()),
                "sequence": pa.array(seq_col, type=pa.int64()),
                "payload_json": pa.array(payload_json, type=pa.string()),
            }
        )
        tmp = path.with_suffix(path.suffix + ".tmp")
        with pa.OSFile(str(tmp), "wb") as sink:
            with ipc.new_file(sink, table.schema) as writer:
                writer.write_table(table)
        tmp.replace(path)
        body = path.read_bytes()
        digest = f"sha256:{__import__('hashlib').sha256(body).hexdigest()}"
        return ExportPartition(
            path=str(path.name),
            format=ExportFormat.ARROW.value,
            record_count=len(payloads),
            byte_count=len(body),
            digest=digest,
            record_types=tuple(sorted(types)),
            min_position=min(sequences) if sequences else None,
            max_position=max(sequences) if sequences else None,
        )

    def _write_car(
        self,
        records: Sequence[object],
        path: Path,
        *,
        context: OperationContext,
    ) -> ExportPartition:
        context.check_active()
        if not self._enable_car or self._car_writer is None:
            raise UnsupportedCapabilityError(
                "IPLD/CAR export is optional and not enabled; "
                "JSONL and Parquet contracts are available without CAR"
            )
        payloads = [record_as_dict(record) for record in records]
        # Injectable writer: callable(path, payloads) -> ExportPartition | dict
        result = self._car_writer(path, payloads)
        if isinstance(result, ExportPartition):
            return result
        if isinstance(result, Mapping):
            return ExportPartition(
                path=str(result.get("path") or path.name),
                format=ExportFormat.CAR.value,
                record_count=int(result.get("record_count", len(payloads))),
                byte_count=int(result.get("byte_count", 0)),
                digest=str(result.get("digest") or content_digest(payloads)),
                cid=result.get("cid"),
                record_types=tuple(result.get("record_types") or ()),
                min_position=result.get("min_position"),
                max_position=result.get("max_position"),
            )
        raise ExportError("car_writer must return ExportPartition or mapping")

    async def export_wallet(
        self,
        request: BoundedRequest,
        sink: DatasetSink,
    ) -> ExportReceipt:
        """Export wallet data already staged in *sink* (or empty if none).

        Callers that stream through the pipeline should prefer
        :meth:`export_records` after ingestion.  This method satisfies the
        :class:`~protocols.Exporter` protocol by committing the sink with a
        manifest derived from its committed rows when the sink is a
        :class:`~storage.StreamingDatasetSink`.
        """

        request.context.check_active()
        if not request.scope.strip():
            raise InvalidRequestError("export scope must not be empty")

        records: list[dict[str, Any]] = []
        if isinstance(sink, StreamingDatasetSink):
            records = list(sink.committed_records())
            if sink.staged_count:
                # Commit staged rows first so export sees a consistent snapshot.
                await sink.commit(None, context=request.context)
                records = list(sink.committed_records())
        elif hasattr(sink, "committed_records"):
            records = list(sink.committed_records())  # type: ignore[attr-defined]

        # Re-export through export_records so partitions and manifest match.
        # Use a null path for the protocol sink commit inside export_records by
        # exporting without double-writing when records already live in sink.
        return await self.export_records(
            records,
            context=request.context,
            scope=request.scope,
            status=ExportStatus.COMPLETE,
            sink=None,
        )


def load_export_manifest(path: str | Path) -> dict[str, Any]:
    """Load a previously written export-manifest.json document."""

    import json

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ExportError("export manifest must be a JSON object")
    _ensure_export_safe(payload)
    return payload


def round_trip_records(
    records: Sequence[object],
    *,
    format: ExportFormat | str = ExportFormat.JSONL,
    directory: str | Path,
) -> list[dict[str, Any]]:
    """Write then read records to prove type/ID preservation for *format*."""

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fmt = format if isinstance(format, ExportFormat) else ExportFormat(str(format))
    if fmt is ExportFormat.JSONL:
        path = directory / "roundtrip.jsonl"
        write_jsonl(records, path)
        return read_jsonl(path)
    if fmt is ExportFormat.PARQUET:
        path = directory / "roundtrip.parquet"
        write_parquet(records, path)
        return read_parquet(path)
    raise UnsupportedCapabilityError(
        f"round-trip is only implemented for jsonl and parquet (got {fmt})"
    )


__all__ = [
    "DEFAULT_NORMALIZED_SCHEMA_MAJOR",
    "DEFAULT_PROCESSOR_VERSION",
    "EXPORT_RECEIPT_SCHEMA_VERSION",
    "ExportFormat",
    "ExportReceipt",
    "WalletDatasetExporter",
    "build_export_manifest",
    "build_finality_counts",
    "load_export_manifest",
    "read_jsonl",
    "read_parquet",
    "round_trip_records",
    "verify_manifest",
    "write_jsonl",
    "write_parquet",
]
