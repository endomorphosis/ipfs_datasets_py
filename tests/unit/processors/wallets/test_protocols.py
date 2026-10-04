"""Contract tests for the dependency-light wallet processor protocols."""

from __future__ import annotations

import asyncio
import inspect
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from ipfs_datasets_py.processors.wallets.errors import (
    DeadlineExceededError,
    InvalidRequestError,
    OperationCancelledError,
    ResourceLimitError,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    CancellationToken,
    Capabilities,
    Capability,
    ChainNormalizer,
    CheckpointStore,
    DatasetSink,
    Exporter,
    FinalityPolicy,
    HttpRequest,
    HttpResponse,
    HttpTransport,
    LedgerProvider,
    OperationContext,
    RecordBatch,
    RequestLimits,
    SecretResolver,
    SecretValue,
    WalletProvider,
)


class FakeCancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


CAPABILITIES = Capabilities(
    provider="fixture",
    chain_namespaces=frozenset({"eip155:1"}),
    features=frozenset(
        {
            Capability.WALLET_HISTORY,
            Capability.LEDGER_RANGE,
            Capability.FINALITY,
            Capability.DATASET_EXPORT,
        }
    ),
)


class FakeProvider:
    capabilities = CAPABILITIES

    async def validate_address(
        self, address: str, *, context: OperationContext
    ) -> object:
        context.check_active()
        return {"canonical": address.lower()}

    async def ledger_head(self, *, context: OperationContext) -> object:
        context.check_active()
        return {"height": 10}

    async def _batches(self, request: BoundedRequest):
        request.context.check_active()
        batch = RecordBatch(({"scope": request.scope},), response_bytes=24)
        batch.enforce(request.context.limits)
        yield batch

    def ingest_wallet(self, request: BoundedRequest):
        return self._batches(request)

    def ingest_ledger(self, request: BoundedRequest):
        return self._batches(request)


class FakeNormalizer:
    capabilities = CAPABILITIES

    def normalize(
        self,
        records: tuple[object, ...],
        *,
        context: OperationContext,
    ) -> tuple[object, ...]:
        context.check_active()
        return records


class FakeCheckpointStore:
    def __init__(self) -> None:
        self.value: object | None = None
        self.revision: str | None = None

    async def load(
        self, scope: str, *, context: OperationContext
    ) -> object | None:
        context.check_active()
        return self.value

    async def compare_and_set(
        self,
        scope: str,
        *,
        expected_revision: str | None,
        checkpoint: object,
        context: OperationContext,
    ) -> bool:
        context.check_active()
        if expected_revision != self.revision:
            return False
        self.value = checkpoint
        self.revision = "next"
        return True


class FakeSink:
    def __init__(self) -> None:
        self.batches: list[RecordBatch] = []
        self.committed = False
        self.aborted = False

    async def write(
        self, batch: RecordBatch, *, context: OperationContext
    ) -> object:
        context.check_active()
        batch.enforce(context.limits)
        self.batches.append(batch)
        return {"count": len(batch.records)}

    async def commit(
        self, manifest: object, *, context: OperationContext
    ) -> object:
        context.check_active()
        self.committed = True
        return manifest

    async def abort(self, *, context: OperationContext) -> None:
        self.aborted = True


class FakeExporter:
    capabilities = CAPABILITIES

    async def export_wallet(
        self, request: BoundedRequest, sink: DatasetSink
    ) -> object:
        batch = RecordBatch(({"record_id": "one"},), response_bytes=12)
        await sink.write(batch, context=request.context)
        return await sink.commit({"complete": True}, context=request.context)


class FakeTransport:
    async def request(
        self, request: HttpRequest, *, context: OperationContext
    ) -> HttpResponse:
        context.check_active()
        body = b"{}"
        if len(body) > request.max_response_bytes:
            raise ResourceLimitError("response exceeded request limit")
        return HttpResponse(200, {"content-type": "application/json"}, body)


class FakeSecretResolver:
    async def resolve(
        self, reference: str, *, context: OperationContext
    ) -> SecretValue:
        context.check_active()
        return SecretValue(b"fixture-secret")


class FakeFinalityPolicy:
    capabilities = CAPABILITIES

    def classify(
        self,
        record: object,
        *,
        head: object,
        context: OperationContext,
    ) -> object:
        context.check_active()
        return "finalized"

    def rewind_position(
        self,
        checkpoint: object,
        *,
        observed_anchor: object,
        context: OperationContext,
    ) -> int | None:
        context.check_active()
        return 8


def test_fake_implementations_satisfy_every_runtime_protocol() -> None:
    provider = FakeProvider()
    assert isinstance(FakeCancellation(), CancellationToken)
    assert isinstance(provider, WalletProvider)
    assert isinstance(provider, LedgerProvider)
    assert isinstance(FakeNormalizer(), ChainNormalizer)
    assert isinstance(FakeCheckpointStore(), CheckpointStore)
    assert isinstance(FakeSink(), DatasetSink)
    assert isinstance(FakeExporter(), Exporter)
    assert isinstance(FakeTransport(), HttpTransport)
    assert isinstance(FakeSecretResolver(), SecretResolver)
    assert isinstance(FakeFinalityPolicy(), FinalityPolicy)


def test_bounded_wallet_and_ledger_streams_are_consumable() -> None:
    async def exercise() -> None:
        context = OperationContext(
            "stream",
            limits=RequestLimits(
                max_items=2,
                max_pages=1,
                max_requests=2,
                max_response_bytes=100,
            ),
        )
        provider = FakeProvider()
        wallet = [
            batch
            async for batch in provider.ingest_wallet(
                BoundedRequest("wallet:0xabc", context)
            )
        ]
        ledger = [
            batch
            async for batch in provider.ingest_ledger(
                BoundedRequest(
                    "ledger:1-10",
                    context,
                    start_position=1,
                    end_position=10,
                )
            )
        ]
        assert len(wallet) == len(ledger) == 1
        assert CAPABILITIES.supports(Capability.WALLET_HISTORY)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_items": 0}, "max_items"),
        ({"max_pages": -1}, "max_pages"),
        ({"max_requests": True}, "max_requests"),
        ({"max_response_bytes": 0}, "max_response_bytes"),
    ],
)
def test_request_limits_require_finite_positive_integers(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidRequestError, match=message):
        RequestLimits(**kwargs)


def test_request_range_and_batch_bounds_are_enforced() -> None:
    context = OperationContext("bounds", RequestLimits(max_items=1))
    with pytest.raises(InvalidRequestError, match="start_position"):
        BoundedRequest(
            "bad-range",
            context,
            start_position=3,
            end_position=2,
        )
    with pytest.raises(ResourceLimitError, match="2 items"):
        RecordBatch((1, 2)).enforce(context.limits)


def test_context_checks_cancellation_and_timezone_aware_deadlines() -> None:
    with pytest.raises(InvalidRequestError, match="timezone-aware"):
        OperationContext("naive", deadline=datetime.now())

    cancelled = OperationContext(
        "cancelled",
        cancellation=FakeCancellation(cancelled=True),
    )
    with pytest.raises(OperationCancelledError, match="cancelled"):
        cancelled.check_active()

    deadline = datetime(2026, 1, 1, tzinfo=timezone.utc)
    expired = OperationContext("expired", deadline=deadline)
    with pytest.raises(DeadlineExceededError, match="deadline"):
        expired.check_active(now=lambda: deadline + timedelta(seconds=1))
    assert expired.remaining_seconds(now=lambda: deadline) == 0


def test_sink_checkpoint_transport_export_and_secret_fakes() -> None:
    async def exercise() -> None:
        context = OperationContext("boundaries")
        store = FakeCheckpointStore()
        assert await store.load("scope", context=context) is None
        assert await store.compare_and_set(
            "scope",
            expected_revision=None,
            checkpoint={"height": 1},
            context=context,
        )
        assert not await store.compare_and_set(
            "scope",
            expected_revision="stale",
            checkpoint={"height": 2},
            context=context,
        )

        sink = FakeSink()
        receipt = await FakeExporter().export_wallet(
            BoundedRequest("wallet", context), sink
        )
        assert receipt == {"complete": True}
        assert sink.committed and len(sink.batches) == 1

        response = await FakeTransport().request(
            HttpRequest("get", "https://fixture.invalid", 8),
            context=context,
        )
        assert response.status == 200

        secret = await FakeSecretResolver().resolve("env:FIXTURE", context=context)
        assert repr(secret) == "SecretValue(<redacted>)"
        assert str(secret) == "<redacted>"
        assert "fixture-secret" not in repr(secret)

    asyncio.run(exercise())


def test_protocol_surface_has_no_transaction_authority() -> None:
    prohibited = {
        "approve",
        "broadcast",
        "build_transaction",
        "send",
        "sign",
        "submit",
    }
    protocols = (
        WalletProvider,
        LedgerProvider,
        ChainNormalizer,
        CheckpointStore,
        DatasetSink,
        Exporter,
        HttpTransport,
        SecretResolver,
        FinalityPolicy,
    )
    methods = {
        name
        for protocol in protocols
        for name, value in vars(protocol).items()
        if inspect.isfunction(value)
    }
    assert methods.isdisjoint(prohibited)


def test_import_is_stdlib_only_and_has_no_network_side_effects() -> None:
    package_root = Path(__file__).resolve().parents[4]
    code = r"""
import json
import socket
import sys

def forbidden(*args, **kwargs):
    raise AssertionError("network access during import")

socket.create_connection = forbidden
import ipfs_datasets_py.processors
import ipfs_datasets_py.processors.wallets.errors
before = set(sys.modules)
import ipfs_datasets_py.processors.wallets.protocols as protocols
loaded = set(sys.modules) - before
optional = sorted(
    name for name in loaded
    if name.split(".", 1)[0] in {"aiohttp", "anyio", "httpx", "numpy", "requests"}
)
print(json.dumps({
    "module": protocols.__name__,
    "optional": optional,
}))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(package_root)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert '"optional": []' in completed.stdout
