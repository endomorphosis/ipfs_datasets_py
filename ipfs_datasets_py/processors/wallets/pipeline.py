"""Bounded wallet-centric and ledger-range streaming ingestion pipelines.

:class:`WalletLedgerProcessor` orchestrates provider pages, pure
normalization, transactional sink writes, and hash-anchored checkpoint CAS.
It never accumulates whole history in memory: each page is normalized,
deduplicated, staged, and released before the next page is fetched.

Partial or cancelled runs produce :class:`PartialRunReceipt` values without
advancing the durable checkpoint.  Successful batches commit the sink first,
then compare-and-set the checkpoint (sink-before-CAS invariant).

Importing this module performs no network I/O.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .checkpoints import (
    CheckpointCommitCoordinator,
    CheckpointIdentity,
    CheckpointRecord,
    HashAnchor,
    InMemoryCheckpointStore,
    SinkCommitReceipt as CheckpointSinkReceipt,
    build_checkpoint,
    new_revision,
    validate_resume,
)
from .errors import (
    DatasetSinkError,
    ExportError,
    InvalidRequestError,
    OperationCancelledError,
    ResourceLimitError,
    UnsupportedCapabilityError,
)
from .export import (
    DEFAULT_NORMALIZED_SCHEMA_MAJOR,
    DEFAULT_PROCESSOR_VERSION,
    ExportFormat,
    ExportReceipt,
    WalletDatasetExporter,
)
from .models import (
    ChainRef,
    ExportStatus,
    LedgerRecord,
    RawPayloadPolicy,
)
from .protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    ChainNormalizer,
    DatasetSink,
    LedgerProvider,
    OperationContext,
    RecordBatch,
    WalletProvider,
)
from .storage import (
    BatchWriteReceipt,
    InMemoryRawPayloadStore,
    RawPayloadEncryptor,
    RawPayloadStore,
    SinkCommitReceipt,
    StreamingDatasetSink,
)


PIPELINE_RECEIPT_SCHEMA_VERSION = "wallet-pipeline-receipt-v1"


class IngestMode(StrEnum):
    WALLET = "wallet"
    LEDGER_RANGE = "ledger_range"


class RunStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


def _required_str(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    return value


def _non_negative_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def assert_finite_scope(request: BoundedRequest, *, mode: IngestMode) -> None:
    """Reject unbounded scans before any provider I/O.

    Wallet-centric scans require a non-empty scope string (address/account set
    identity). Ledger-range scans additionally require an explicit finite range
    (both start and end positions, or a finite ``max_items`` limit already on
    the operation context—range endpoints are mandatory for ledger mode).
    """

    _required_str(request.scope, "scope")
    if mode is IngestMode.LEDGER_RANGE:
        if request.start_position is None or request.end_position is None:
            raise InvalidRequestError(
                "ledger-range scans require explicit start_position and "
                "end_position (finite scope)"
            )
        if request.start_position > request.end_position:
            raise InvalidRequestError(
                "start_position must not be greater than end_position"
            )
    # All modes inherit hard page/item/request ceilings from OperationContext.
    limits = request.context.limits
    if limits.max_pages < 1 or limits.max_items < 1 or limits.max_requests < 1:
        raise InvalidRequestError("operation limits must be finite and positive")


@dataclass(frozen=True, slots=True)
class PageOutcome:
    """One streamed page after normalization and sink staging."""

    page_index: int
    native_count: int
    normalized_count: int
    write_receipt: BatchWriteReceipt | None
    next_cursor: str | None
    anchor: HashAnchor | None


@dataclass(frozen=True, slots=True)
class PartialRunReceipt:
    """Receipt for a partial, cancelled, or failed pipeline run.

    Durable checkpoints are intentionally **not** advanced when this receipt
    is produced after cancellation or failure before sink commit.
    """

    status: RunStatus
    mode: IngestMode
    scope: str
    pages_processed: int
    records_accepted: int
    records_duplicate: int
    checkpoint_advanced: bool
    checkpoint_before: CheckpointRecord | None
    checkpoint_after: CheckpointRecord | None
    warnings: tuple[str, ...] = ()
    error: str | None = None
    schema_version: str = field(default=PIPELINE_RECEIPT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.status, RunStatus):
            raise InvalidRequestError("status must be a RunStatus")
        if not isinstance(self.mode, IngestMode):
            raise InvalidRequestError("mode must be an IngestMode")
        object.__setattr__(self, "scope", _required_str(self.scope, "scope"))
        _non_negative_int(self.pages_processed, "pages_processed")
        _non_negative_int(self.records_accepted, "records_accepted")
        _non_negative_int(self.records_duplicate, "records_duplicate")
        object.__setattr__(self, "warnings", tuple(self.warnings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "mode": self.mode.value,
            "scope": self.scope,
            "pages_processed": self.pages_processed,
            "records_accepted": self.records_accepted,
            "records_duplicate": self.records_duplicate,
            "checkpoint_advanced": self.checkpoint_advanced,
            "checkpoint_before": (
                self.checkpoint_before.to_dict() if self.checkpoint_before else None
            ),
            "checkpoint_after": (
                self.checkpoint_after.to_dict() if self.checkpoint_after else None
            ),
            "warnings": list(self.warnings),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class PipelineRunReceipt:
    """Successful or partial completion of a streaming ingest run."""

    status: RunStatus
    mode: IngestMode
    scope: str
    pages_processed: int
    records_accepted: int
    records_duplicate: int
    out_of_order_count: int
    sink_commit: SinkCommitReceipt | None
    checkpoint_before: CheckpointRecord | None
    checkpoint_after: CheckpointRecord | None
    export_receipt: ExportReceipt | None = None
    warnings: tuple[str, ...] = ()
    page_outcomes: tuple[PageOutcome, ...] = ()
    schema_version: str = field(default=PIPELINE_RECEIPT_SCHEMA_VERSION, init=False)

    @property
    def checkpoint_advanced(self) -> bool:
        return (
            self.checkpoint_after is not None
            and (
                self.checkpoint_before is None
                or self.checkpoint_after.revision != self.checkpoint_before.revision
            )
        )

    def to_partial(self, *, error: str | None = None) -> PartialRunReceipt:
        status = self.status
        if status is RunStatus.COMPLETE and error:
            status = RunStatus.FAILED
        return PartialRunReceipt(
            status=status if status is not RunStatus.COMPLETE else RunStatus.PARTIAL,
            mode=self.mode,
            scope=self.scope,
            pages_processed=self.pages_processed,
            records_accepted=self.records_accepted,
            records_duplicate=self.records_duplicate,
            checkpoint_advanced=self.checkpoint_advanced,
            checkpoint_before=self.checkpoint_before,
            checkpoint_after=self.checkpoint_after,
            warnings=self.warnings,
            error=error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "mode": self.mode.value,
            "scope": self.scope,
            "pages_processed": self.pages_processed,
            "records_accepted": self.records_accepted,
            "records_duplicate": self.records_duplicate,
            "out_of_order_count": self.out_of_order_count,
            "checkpoint_advanced": self.checkpoint_advanced,
            "sink_commit": self.sink_commit.to_dict() if self.sink_commit else None,
            "checkpoint_before": (
                self.checkpoint_before.to_dict() if self.checkpoint_before else None
            ),
            "checkpoint_after": (
                self.checkpoint_after.to_dict() if self.checkpoint_after else None
            ),
            "export_receipt_id": (
                self.export_receipt.receipt_id if self.export_receipt else None
            ),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class IngestPlan:
    """Resolved plan for one bounded pipeline invocation."""

    mode: IngestMode
    identity: CheckpointIdentity
    request: BoundedRequest
    observed_anchor: HashAnchor | None = None
    export_formats: tuple[ExportFormat, ...] = ()
    store_raw_payloads: bool = False
    safety_depth: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.mode, IngestMode):
            raise InvalidRequestError("mode must be an IngestMode")
        if not isinstance(self.identity, CheckpointIdentity):
            raise InvalidRequestError("identity must be a CheckpointIdentity")
        if not isinstance(self.request, BoundedRequest):
            raise InvalidRequestError("request must be a BoundedRequest")
        _non_negative_int(self.safety_depth, "safety_depth")
        object.__setattr__(self, "export_formats", tuple(self.export_formats))


class WalletLedgerProcessor:
    """Streaming wallet and ledger-range processor with sink/checkpoint coupling.

    Dependencies are injected: provider, normalizer, sink factory, checkpoint
    store, optional raw-payload store, and optional exporter.  The processor
    itself performs no ambient network or filesystem discovery on import.
    """

    def __init__(
        self,
        *,
        chain: ChainRef,
        wallet_provider: WalletProvider | None = None,
        ledger_provider: LedgerProvider | None = None,
        normalizer: ChainNormalizer,
        checkpoint_store: InMemoryCheckpointStore | None = None,
        raw_payload_store: RawPayloadStore | None = None,
        raw_payload_encryptor: RawPayloadEncryptor | None = None,
        provider_name: str = "wallet-ledger-processor",
        normalizer_version: str = DEFAULT_PROCESSOR_VERSION,
        normalized_schema_major: int = DEFAULT_NORMALIZED_SCHEMA_MAJOR,
        raw_payload_policy: RawPayloadPolicy = RawPayloadPolicy.OMITTED,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(chain, ChainRef):
            raise InvalidRequestError("chain must be a ChainRef")
        if wallet_provider is None and ledger_provider is None:
            raise InvalidRequestError(
                "at least one of wallet_provider or ledger_provider is required"
            )
        self._chain = chain
        self._wallet_provider = wallet_provider
        self._ledger_provider = ledger_provider
        self._normalizer = normalizer
        # Use explicit None checks: InMemory* stores implement __len__ and are
        # falsy when empty, which would incorrectly replace injected instances.
        self._checkpoint_store = (
            checkpoint_store
            if checkpoint_store is not None
            else InMemoryCheckpointStore()
        )
        self._coordinator = CheckpointCommitCoordinator(self._checkpoint_store)
        if not isinstance(raw_payload_policy, RawPayloadPolicy):
            raise InvalidRequestError("raw_payload_policy must be a RawPayloadPolicy")
        self._raw_payload_policy = raw_payload_policy
        self._raw_payload_encryptor = raw_payload_encryptor

        # Fail closed: encrypted custody is unusable without an encryptor on the
        # processor or an injected store that already carries one.
        store_encryptor = getattr(raw_payload_store, "encryptor", None)
        effective_encryptor = raw_payload_encryptor or store_encryptor
        if (
            raw_payload_policy is RawPayloadPolicy.SEPARATELY_ENCRYPTED
            and effective_encryptor is None
        ):
            raise InvalidRequestError(
                "separately_encrypted raw payload policy requires an injected encryptor"
            )

        if raw_payload_store is not None:
            self._raw_payload_store = raw_payload_store
        else:
            # Default store is only usable for explicit retention policies; OMITTED
            # keeps a inert REFERENCED-capable store that is never written unless
            # the caller opts in via store_raw_payloads + non-omitted policy.
            store_policy = (
                RawPayloadPolicy.REFERENCED
                if raw_payload_policy is RawPayloadPolicy.OMITTED
                else raw_payload_policy
            )
            self._raw_payload_store = InMemoryRawPayloadStore(
                policy=store_policy,
                encryptor=effective_encryptor,
            )
        self._provider_name = _required_str(provider_name, "provider_name")
        self._normalizer_version = _required_str(
            normalizer_version, "normalizer_version"
        )
        if (
            isinstance(normalized_schema_major, bool)
            or not isinstance(normalized_schema_major, int)
            or normalized_schema_major <= 0
        ):
            raise InvalidRequestError("normalized_schema_major must be a positive integer")
        self._normalized_schema_major = normalized_schema_major
        self._clock = clock or _utc_now

        features = {Capability.DATASET_EXPORT}
        if wallet_provider is not None:
            features.add(Capability.WALLET_HISTORY)
        if ledger_provider is not None:
            features.add(Capability.LEDGER_RANGE)
        if raw_payload_policy is not RawPayloadPolicy.OMITTED:
            features.add(Capability.RAW_PAYLOADS)
        self._capabilities = Capabilities(
            provider=self._provider_name,
            chain_namespaces=frozenset({chain.namespace}),
            features=frozenset(features),
            metadata={
                "normalizer_version": self._normalizer_version,
                "normalized_schema_major": self._normalized_schema_major,
                "raw_payload_policy": self._raw_payload_policy.value,
            },
        )

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    @property
    def chain(self) -> ChainRef:
        return self._chain

    @property
    def checkpoint_store(self) -> InMemoryCheckpointStore:
        return self._checkpoint_store

    def identity_for(self, scope: str) -> CheckpointIdentity:
        return CheckpointIdentity(
            chain=self._chain,
            provider=self._provider_name,
            scope=scope,
            normalized_schema_major=self._normalized_schema_major,
            normalizer_version=self._normalizer_version,
        )

    async def ingest_wallet(
        self,
        request: BoundedRequest,
        *,
        sink: StreamingDatasetSink | None = None,
        observed_anchor: HashAnchor | None = None,
        export_formats: Sequence[ExportFormat | str] = (),
        export_dir: str | None = None,
        store_raw_payloads: bool = False,
        safety_depth: int = 0,
    ) -> PipelineRunReceipt:
        """Run a bounded wallet-centric streaming ingest."""

        if self._wallet_provider is None:
            raise UnsupportedCapabilityError("wallet_provider is not configured")
        assert_finite_scope(request, mode=IngestMode.WALLET)
        plan = IngestPlan(
            mode=IngestMode.WALLET,
            identity=self.identity_for(request.scope),
            request=request,
            observed_anchor=observed_anchor,
            export_formats=tuple(
                f if isinstance(f, ExportFormat) else ExportFormat(str(f))
                for f in export_formats
            ),
            store_raw_payloads=store_raw_payloads,
            safety_depth=safety_depth,
        )
        return await self._run(plan, sink=sink, export_dir=export_dir)

    async def ingest_ledger(
        self,
        request: BoundedRequest,
        *,
        sink: StreamingDatasetSink | None = None,
        observed_anchor: HashAnchor | None = None,
        export_formats: Sequence[ExportFormat | str] = (),
        export_dir: str | None = None,
        store_raw_payloads: bool = False,
        safety_depth: int = 0,
    ) -> PipelineRunReceipt:
        """Run a bounded ledger-range streaming ingest."""

        if self._ledger_provider is None:
            raise UnsupportedCapabilityError("ledger_provider is not configured")
        assert_finite_scope(request, mode=IngestMode.LEDGER_RANGE)
        plan = IngestPlan(
            mode=IngestMode.LEDGER_RANGE,
            identity=self.identity_for(request.scope),
            request=request,
            observed_anchor=observed_anchor,
            export_formats=tuple(
                f if isinstance(f, ExportFormat) else ExportFormat(str(f))
                for f in export_formats
            ),
            store_raw_payloads=store_raw_payloads,
            safety_depth=safety_depth,
        )
        return await self._run(plan, sink=sink, export_dir=export_dir)

    def _page_stream(self, plan: IngestPlan) -> AsyncIterator[RecordBatch]:
        if plan.mode is IngestMode.WALLET:
            assert self._wallet_provider is not None
            return self._wallet_provider.ingest_wallet(plan.request)
        assert self._ledger_provider is not None
        return self._ledger_provider.ingest_ledger(plan.request)

    async def _run(
        self,
        plan: IngestPlan,
        *,
        sink: StreamingDatasetSink | None,
        export_dir: str | None,
    ) -> PipelineRunReceipt:
        context = plan.request.context
        context.check_active()
        identity = plan.identity
        own_sink = sink is None
        active_sink = sink or StreamingDatasetSink(
            scope=plan.request.scope,
            output_dir=export_dir,
            raw_payload_policy=self._raw_payload_policy,
        )

        checkpoint_before = await self._checkpoint_store.load(
            identity.key, context=context
        )
        if checkpoint_before is not None and plan.observed_anchor is not None:
            validate_resume(
                checkpoint_before,
                observed_anchor=plan.observed_anchor,
                identity=identity,
            )

        warnings: list[str] = []
        page_outcomes: list[PageOutcome] = []
        pages = 0
        accepted = 0
        duplicates = 0
        out_of_order = 0
        last_anchor: HashAnchor | None = (
            checkpoint_before.anchor if checkpoint_before is not None else None
        )
        last_cursor: str | None = (
            checkpoint_before.continuation_token
            if checkpoint_before is not None
            else plan.request.cursor
        )
        # Track only the current page's normalized records for streaming;
        # never retain the full history beyond the sink's staged/committed set.
        run_status = RunStatus.COMPLETE
        error_text: str | None = None
        sink_commit: SinkCommitReceipt | None = None
        checkpoint_after: CheckpointRecord | None = checkpoint_before
        export_receipt: ExportReceipt | None = None

        try:
            async for batch in self._page_stream(plan):
                context.check_active()
                if pages >= context.limits.max_pages:
                    raise ResourceLimitError(
                        f"page limit {context.limits.max_pages} exceeded"
                    )
                if not isinstance(batch, RecordBatch):
                    raise InvalidRequestError("provider must yield RecordBatch values")
                batch.enforce(context.limits)

                # Optional raw payload capture (content-addressed, custody-bounded).
                # Retention is omitted by default; explicit non-omitted policy plus
                # store_raw_payloads is required.  Store bounds raise
                # ResourceLimitError before any store mutation.
                if plan.store_raw_payloads and self._raw_payload_policy is not (
                    RawPayloadPolicy.OMITTED
                ):
                    if (
                        self._raw_payload_policy
                        is RawPayloadPolicy.SEPARATELY_ENCRYPTED
                        and self._raw_payload_encryptor is None
                        and getattr(self._raw_payload_store, "encryptor", None)
                        is None
                    ):
                        raise InvalidRequestError(
                            "separately_encrypted raw payload policy requires "
                            "an injected encryptor"
                        )
                    raw_body = canonical_native_batch(batch)
                    await self._raw_payload_store.put(
                        raw_body,
                        media_type="application/json",
                        context=context,
                    )

                normalized = self._normalizer.normalize(
                    batch.records, context=context
                )
                # Stream-normalize: only this page's records enter the sink.
                normalized_tuple = tuple(normalized)
                if len(normalized_tuple) > context.limits.max_items:
                    raise ResourceLimitError(
                        "normalized batch exceeds max_items limit"
                    )

                # Infer page anchor from the last record with a sequence+hash.
                page_anchor = extract_batch_anchor(normalized_tuple) or last_anchor

                write_receipt = await active_sink.write(
                    RecordBatch(
                        normalized_tuple,
                        next_cursor=batch.next_cursor,
                        response_bytes=batch.response_bytes,
                    ),
                    context=context,
                )
                accepted += write_receipt.accepted_count
                duplicates += write_receipt.duplicate_count
                out_of_order += write_receipt.out_of_order_count
                page_outcomes.append(
                    PageOutcome(
                        page_index=pages,
                        native_count=len(batch.records),
                        normalized_count=len(normalized_tuple),
                        write_receipt=write_receipt,
                        next_cursor=batch.next_cursor,
                        anchor=page_anchor,
                    )
                )
                pages += 1
                if page_anchor is not None:
                    last_anchor = page_anchor
                last_cursor = batch.next_cursor
                if batch.next_cursor is None:
                    break

            # Successful stream drain: commit sink then CAS checkpoint.
            context.check_active()
            if active_sink.staged_count or active_sink.committed_count:
                sink_commit = await active_sink.commit(None, context=context)
            else:
                # Empty successful scan still needs a commit receipt only when
                # we intend to write a checkpoint anchor.
                sink_commit = await active_sink.commit(None, context=context)

            if last_anchor is None and plan.observed_anchor is not None:
                last_anchor = plan.observed_anchor

            if last_anchor is not None and sink_commit is not None:
                expected_revision = (
                    None
                    if checkpoint_before is None
                    else checkpoint_before.revision
                )
                prior_history = (
                    checkpoint_before.history if checkpoint_before is not None else ()
                )
                candidate = build_checkpoint(
                    identity,
                    sequence=last_anchor.sequence,
                    block_hash=last_anchor.block_hash,
                    revision=new_revision(),
                    safety_depth=plan.safety_depth,
                    continuation_token=last_cursor,
                    sink_commit_id=sink_commit.commit_id,
                    prior_history=prior_history,
                )
                self._coordinator.note_sink_commit(
                    CheckpointSinkReceipt(
                        commit_id=sink_commit.commit_id,
                        scope_key=identity.key,
                        record_count=sink_commit.record_count,
                        content_digest=sink_commit.content_digest,
                    )
                )
                accepted_cas = await self._coordinator.compare_and_set_after_commit(
                    identity,
                    expected_revision=expected_revision,
                    checkpoint=candidate,
                    context=context,
                    require_commit=True,
                )
                if not accepted_cas:
                    warnings.append("checkpoint_cas_conflict")
                    run_status = RunStatus.PARTIAL
                    checkpoint_after = await self._checkpoint_store.load(
                        identity.key, context=context
                    )
                else:
                    checkpoint_after = candidate
            elif last_anchor is None:
                warnings.append("no_hash_anchor_checkpoint_not_advanced")
                # Partial receipt semantics: data may be committed to the sink
                # but durable resume position stays unchanged without an anchor.
                run_status = (
                    RunStatus.PARTIAL
                    if active_sink.committed_count
                    else RunStatus.COMPLETE
                )
                checkpoint_after = checkpoint_before

            if plan.export_formats:
                if export_dir is None:
                    raise InvalidRequestError(
                        "export_dir is required when export_formats is set"
                    )
                exporter = WalletDatasetExporter(
                    chain=self._chain,
                    output_dir=export_dir,
                    formats=plan.export_formats,
                    processor_version=self._normalizer_version,
                    normalized_schema_major=self._normalized_schema_major,
                    raw_payload_policy=self._raw_payload_policy,
                    provider=self._provider_name,
                    provider_kind="pipeline",
                    provider_capabilities=tuple(
                        sorted(cap.value for cap in self._capabilities.features)
                    ),
                    clock=self._clock,
                )
                cursor_before = (
                    checkpoint_before.to_cursor()
                    if checkpoint_before is not None
                    else None
                )
                cursor_after = (
                    checkpoint_after.to_cursor()
                    if checkpoint_after is not None
                    else None
                )
                export_status = (
                    ExportStatus.COMPLETE
                    if run_status is RunStatus.COMPLETE
                    else ExportStatus.PARTIAL
                )
                export_receipt = await exporter.export_records(
                    active_sink.committed_records(),
                    context=context,
                    scope=plan.request.scope,
                    status=export_status,
                    checkpoint_before=cursor_before,
                    checkpoint_after=cursor_after,
                    warnings=tuple(warnings),
                    sink=None,
                )

        except OperationCancelledError as exc:
            run_status = RunStatus.CANCELLED
            error_text = str(exc)
            warnings.append("cancelled")
            await active_sink.abort(context=context)
            # Checkpoint intentionally not advanced.
            checkpoint_after = checkpoint_before
            sink_commit = None
        except Exception as exc:
            if isinstance(
                exc,
                (
                    InvalidRequestError,
                    ResourceLimitError,
                    UnsupportedCapabilityError,
                    DatasetSinkError,
                    ExportError,
                ),
            ):
                run_status = RunStatus.FAILED
                error_text = str(exc)
                warnings.append(f"failed:{type(exc).__name__}")
                try:
                    await active_sink.abort(context=context)
                except Exception:
                    pass
                checkpoint_after = checkpoint_before
                sink_commit = None
                # Re-raise request errors so callers can distinguish programming
                # mistakes from partial operational receipts.  Cancellation and
                # mid-run failures return a receipt instead.
                if isinstance(exc, InvalidRequestError) and pages == 0:
                    raise
            else:
                raise

        if run_status is RunStatus.CANCELLED or (
            run_status is RunStatus.FAILED and pages > 0
        ):
            # Return a run receipt that reports checkpoint_advanced=False.
            return PipelineRunReceipt(
                status=run_status,
                mode=plan.mode,
                scope=plan.request.scope,
                pages_processed=pages,
                records_accepted=accepted,
                records_duplicate=duplicates,
                out_of_order_count=out_of_order,
                sink_commit=sink_commit,
                checkpoint_before=checkpoint_before,
                checkpoint_after=checkpoint_after,
                export_receipt=export_receipt,
                warnings=tuple(warnings),
                page_outcomes=tuple(page_outcomes),
            )

        if error_text and run_status is RunStatus.FAILED and pages == 0:
            # Already re-raised above for InvalidRequestError; other early
            # failures surface as receipts.
            pass

        # Silence unused own_sink flag for linters when caller provided sink.
        _ = own_sink

        return PipelineRunReceipt(
            status=run_status,
            mode=plan.mode,
            scope=plan.request.scope,
            pages_processed=pages,
            records_accepted=accepted,
            records_duplicate=duplicates,
            out_of_order_count=out_of_order,
            sink_commit=sink_commit,
            checkpoint_before=checkpoint_before,
            checkpoint_after=checkpoint_after,
            export_receipt=export_receipt,
            warnings=tuple(warnings),
            page_outcomes=tuple(page_outcomes),
        )

    async def export_wallet(
        self,
        request: BoundedRequest,
        sink: DatasetSink,
        *,
        formats: Sequence[ExportFormat | str] = (ExportFormat.JSONL,),
        output_dir: str,
    ) -> ExportReceipt:
        """Export already-ingested sink data through :class:`WalletDatasetExporter`."""

        exporter = WalletDatasetExporter(
            chain=self._chain,
            output_dir=output_dir,
            formats=formats,
            processor_version=self._normalizer_version,
            normalized_schema_major=self._normalized_schema_major,
            raw_payload_policy=self._raw_payload_policy,
            provider=self._provider_name,
            provider_kind="pipeline",
            provider_capabilities=tuple(
                sorted(cap.value for cap in self._capabilities.features)
            ),
            clock=self._clock,
        )
        return await exporter.export_wallet(request, sink)


def canonical_native_batch(batch: RecordBatch) -> bytes:
    """Serialize a provider batch for raw-payload content addressing."""

    from .canonical import canonical_json_bytes

    payload = []
    for record in batch.records:
        if hasattr(record, "to_dict") and callable(record.to_dict):
            payload.append(record.to_dict())
        elif isinstance(record, Mapping):
            payload.append(dict(record))
        else:
            payload.append({"repr": repr(record)})
    return canonical_json_bytes(payload)


def extract_batch_anchor(records: Sequence[object]) -> HashAnchor | None:
    """Pick the highest-sequence hash-anchored position from *records*."""

    best: HashAnchor | None = None
    for record in records:
        sequence: int | None = None
        block_hash: str | None = None
        if isinstance(record, LedgerRecord):
            sequence = record.ledger_position.sequence
            block_hash = record.ledger_position.hash
        elif isinstance(record, Mapping):
            position = record.get("ledger_position") or {}
            if isinstance(position, Mapping):
                raw_seq = position.get("sequence")
                raw_hash = position.get("hash")
                sequence = raw_seq if isinstance(raw_seq, int) and not isinstance(raw_seq, bool) else None
                block_hash = raw_hash if isinstance(raw_hash, str) else None
        else:
            position = getattr(record, "ledger_position", None)
            sequence = getattr(position, "sequence", None)
            block_hash = getattr(position, "hash", None)
        if sequence is None or not block_hash:
            continue
        candidate = HashAnchor(sequence=sequence, block_hash=block_hash)
        if best is None or candidate.sequence >= best.sequence:
            best = candidate
    return best


__all__ = [
    "PIPELINE_RECEIPT_SCHEMA_VERSION",
    "IngestMode",
    "IngestPlan",
    "PageOutcome",
    "PartialRunReceipt",
    "PipelineRunReceipt",
    "RunStatus",
    "WalletLedgerProcessor",
    "assert_finite_scope",
    "canonical_native_batch",
    "extract_batch_anchor",
]
