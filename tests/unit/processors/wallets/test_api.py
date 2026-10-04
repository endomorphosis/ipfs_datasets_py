"""Unit tests for WalletProcessorAPI (WALPROC-G610).

Covers acceptance criteria:

* Typed requests/results
* Finite range/item/byte/time/retry bounds
* Untrusted provider URL / secret allowlists
* Default export finalized; provisional/raw explicit
* No signing/broadcast verbs
* Status/receipts exclude wallet payloads and secrets
* AST symbols WalletProcessorAPI, wallet_ingest, wallet_export
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.api import (
    CapabilitiesRequest,
    ExportMode,
    ExportResult,
    IngestResult,
    LedgerRangeIngestRequest,
    ResumeRequest,
    ScanBounds,
    StatusRequest,
    TrustLevel,
    TrustPolicy,
    VerifyManifestRequest,
    WalletExportRequest,
    WalletIngestRequest,
    WalletProcessorAPI,
    reset_default_api,
    scope_fingerprint,
    wallet_export,
    wallet_ingest,
)
from ipfs_datasets_py.processors.wallets.errors import (
    InvalidRequestError,
    UnsupportedCapabilityError,
)
from ipfs_datasets_py.processors.wallets.export import ExportFormat
from ipfs_datasets_py.processors.wallets.models import (
    AccountKind,
    AccountRef,
    ChainRef,
    ExportStatus,
    Finality,
    LedgerPosition,
    Provenance,
    RawPayloadPolicy,
    TransactionRecord,
    TransactionStatus,
)
from ipfs_datasets_py.processors.wallets.pipeline import (
    RunStatus,
    WalletLedgerProcessor,
)
from ipfs_datasets_py.processors.wallets.protocols import (
    BoundedRequest,
    Capabilities,
    Capability,
    OperationContext,
    RecordBatch,
    RequestLimits,
)


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
GENESIS = "0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3"
API_PATH = (
    Path(__file__).resolve().parents[4]
    / "ipfs_datasets_py"
    / "processors"
    / "wallets"
    / "api.py"
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def chain() -> ChainRef:
    return ChainRef(
        namespace="eip155",
        network="ethereum-mainnet",
        chain_id="1",
        genesis_hash=GENESIS,
    )


def _tx(
    chain: ChainRef,
    *,
    tx_hash: str,
    sequence: int,
    block_hash: str,
    scope: str = "wallet:0xabc",
) -> TransactionRecord:
    return TransactionRecord(
        chain=chain,
        provenance=Provenance(
            provider="fixture-rpc",
            provider_kind="json-rpc",
            request_id="req-1",
            scope=scope,
            observed_at=NOW,
        ),
        ledger_position=LedgerPosition(
            sequence=sequence,
            hash=block_hash,
            transaction_index=0,
        ),
        finality=Finality.FINALIZED,
        transaction_hash=tx_hash,
        status=TransactionStatus.SUCCEEDED,
        participants=(AccountRef(chain, "0xabc", AccountKind.ADDRESS),),
    )


class FakeWalletLedgerProvider:
    def __init__(self, pages: Sequence[Sequence[object]]) -> None:
        self._pages = [tuple(page) for page in pages]
        self.capabilities = Capabilities(
            provider="fixture-rpc",
            chain_namespaces=frozenset({"eip155"}),
            features=frozenset(
                {Capability.WALLET_HISTORY, Capability.LEDGER_RANGE}
            ),
        )

    async def validate_address(self, address: str, *, context: OperationContext) -> object:
        context.check_active()
        return {"address": address, "valid": True}

    async def ingest_wallet(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        request.context.check_active()
        for page in self._pages:
            yield RecordBatch(page, next_cursor=None, response_bytes=128)

    async def ingest_ledger(
        self, request: BoundedRequest
    ) -> AsyncIterator[RecordBatch]:
        request.context.check_active()
        for page in self._pages:
            yield RecordBatch(page, next_cursor=None, response_bytes=128)


class IdentityNormalizer:
    def __init__(self, chain: ChainRef) -> None:
        self.capabilities = Capabilities(
            provider="identity-normalizer",
            chain_namespaces=frozenset({chain.namespace}),
            features=frozenset({Capability.WALLET_HISTORY, Capability.LEDGER_RANGE}),
        )

    def normalize(
        self, records: Sequence[object], *, context: OperationContext
    ) -> list[object]:
        context.check_active()
        return list(records)


@pytest.fixture
def processor(chain: ChainRef) -> WalletLedgerProcessor:
    pages = [
        [
            _tx(
                chain,
                tx_hash="0x" + "11" * 32,
                sequence=10,
                block_hash="0x" + "aa" * 32,
            )
        ]
    ]
    provider = FakeWalletLedgerProvider(pages)
    return WalletLedgerProcessor(
        chain=chain,
        wallet_provider=provider,
        ledger_provider=provider,
        normalizer=IdentityNormalizer(chain),
        provider_name="fixture-rpc",
        clock=lambda: NOW,
    )


@pytest.fixture
def api(processor: WalletLedgerProcessor) -> WalletProcessorAPI:
    reset_default_api()
    return WalletProcessorAPI(
        processor=processor,
        trust=TrustLevel.TRUSTED,
        clock=lambda: NOW,
    )


# ---------------------------------------------------------------------------
# AST evidence
# ---------------------------------------------------------------------------


def test_ast_symbols_wallet_processor_api_wallet_ingest_wallet_export() -> None:
    source = API_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    assert "WalletProcessorAPI" in names
    assert "wallet_ingest" in names
    assert "wallet_export" in names


def test_no_sign_or_broadcast_methods_on_api() -> None:
    public = [
        name
        for name, _ in inspect.getmembers(WalletProcessorAPI, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]
    for forbidden in ("sign", "broadcast", "submit", "send", "transfer"):
        assert forbidden not in public
    api = WalletProcessorAPI()
    with pytest.raises(UnsupportedCapabilityError):
        getattr(api, "sign")
    with pytest.raises(UnsupportedCapabilityError):
        getattr(api, "broadcast")


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


def test_scan_bounds_require_finite_positive_values() -> None:
    with pytest.raises(InvalidRequestError):
        ScanBounds(max_items=0)
    with pytest.raises(InvalidRequestError):
        ScanBounds(max_time_seconds=0)
    with pytest.raises(InvalidRequestError):
        ScanBounds(max_retries=-1)
    bounds = ScanBounds()
    assert bounds.max_items > 0
    assert bounds.max_pages > 0
    assert bounds.max_requests > 0
    assert bounds.max_response_bytes > 0
    assert bounds.max_time_seconds > 0
    assert bounds.max_retries >= 0


def test_ledger_range_requires_finite_start_and_end(chain: ChainRef) -> None:
    with pytest.raises(InvalidRequestError):
        LedgerRangeIngestRequest(
            scope="ledger:range",
            chain=chain,
            start_position=10,
            end_position=5,
        )


# ---------------------------------------------------------------------------
# Ingest / status / resume
# ---------------------------------------------------------------------------


def test_wallet_ingest_typed_result(api: WalletProcessorAPI, chain: ChainRef) -> None:
    request = WalletIngestRequest(
        scope="wallet:0xabc",
        chain=chain,
        bounds=ScanBounds(max_items=50, max_pages=5, max_requests=10),
        request_id="ingest-1",
    )
    result = _run(api.wallet_ingest(request))
    assert isinstance(result, IngestResult)
    payload = result.to_dict()
    assert payload["status"] in {s.value for s in RunStatus}
    assert payload["scope_fingerprint"] == scope_fingerprint("wallet:0xabc")
    assert "0xabc" not in payload["scope_fingerprint"]
    assert payload["bounds"]["max_items"] == 50
    assert "records" not in payload
    assert "payload" not in payload
    assert result.records_accepted >= 1

    status = api.status(StatusRequest(job_id=result.job_id))
    status_dict = status.to_dict()
    assert status_dict["job_id"] == result.job_id
    assert status_dict["scope_fingerprint"] == scope_fingerprint("wallet:0xabc")
    assert "secret" not in status_dict
    assert "records" not in status_dict or status_dict.get("records") in (
        None,
        "<omitted>",
    )


def test_ledger_ingest_and_module_level_wallet_ingest(
    api: WalletProcessorAPI, chain: ChainRef
) -> None:
    ledger_req = LedgerRangeIngestRequest(
        scope="ledger:1-20",
        chain=chain,
        start_position=1,
        end_position=20,
        bounds=ScanBounds(max_items=100),
    )
    ledger_result = _run(api.ledger_ingest(ledger_req))
    assert ledger_result.mode == "ledger_range"
    assert ledger_result.pages_processed >= 1

    # Module-level AST symbol with injected api
    result = _run(
        wallet_ingest(
            {
                "scope": "wallet:0xabc",
                "chain": chain.to_dict(),
                "bounds": {"max_items": 10, "max_pages": 2, "max_requests": 2},
            },
            api=api,
        )
    )
    assert isinstance(result, IngestResult)


def test_resume_unknown_job(api: WalletProcessorAPI) -> None:
    with pytest.raises(InvalidRequestError):
        _run(api.resume(ResumeRequest(job_id="job-missing")))


def test_status_unknown_job(api: WalletProcessorAPI) -> None:
    with pytest.raises(InvalidRequestError):
        api.status(StatusRequest(job_id="job-missing"))


# ---------------------------------------------------------------------------
# Export modes
# ---------------------------------------------------------------------------


def test_default_export_is_finalized(
    api: WalletProcessorAPI, chain: ChainRef, tmp_path: Path
) -> None:
    records = (
        _tx(
            chain,
            tx_hash="0x" + "22" * 32,
            sequence=1,
            block_hash="0x" + "bb" * 32,
        ),
    )
    request = WalletExportRequest(
        scope="wallet:0xabc",
        chain=chain,
        output_dir=str(tmp_path / "out"),
        records=records,
        # mode default finalized
    )
    assert request.mode is ExportMode.FINALIZED
    result = _run(api.wallet_export(request))
    assert isinstance(result, ExportResult)
    assert result.mode == ExportMode.FINALIZED.value
    assert result.status == ExportStatus.COMPLETE.value
    assert result.partial is False
    assert result.record_count == 1
    assert (tmp_path / "out" / "export-manifest.json").is_file()


def test_provisional_and_raw_modes_are_explicit(
    api: WalletProcessorAPI, chain: ChainRef, tmp_path: Path
) -> None:
    records = (
        _tx(
            chain,
            tx_hash="0x" + "33" * 32,
            sequence=2,
            block_hash="0x" + "cc" * 32,
        ),
    )
    provisional = WalletExportRequest(
        scope="wallet:0xabc",
        chain=chain,
        output_dir=str(tmp_path / "prov"),
        records=records,
        mode=ExportMode.PROVISIONAL,
    )
    result = _run(api.wallet_export(provisional))
    assert result.mode == "provisional"
    assert result.partial is True

    with pytest.raises(InvalidRequestError):
        WalletExportRequest(
            scope="wallet:0xabc",
            chain=chain,
            output_dir=str(tmp_path / "raw-bad"),
            records=records,
            mode=ExportMode.RAW,
            raw_payload_policy=RawPayloadPolicy.OMITTED,
        )

    raw = WalletExportRequest(
        scope="wallet:0xabc",
        chain=chain,
        output_dir=str(tmp_path / "raw"),
        records=records,
        mode=ExportMode.RAW,
        raw_payload_policy=RawPayloadPolicy.REFERENCED,
    )
    raw_result = _run(api.wallet_export(raw))
    assert raw_result.mode == "raw"

    # Module-level wallet_export
    mod = _run(
        wallet_export(
            {
                "scope": "wallet:0xabc",
                "chain": {
                    "namespace": chain.namespace,
                    "network": chain.network,
                    "chain_id": chain.chain_id,
                    "genesis_hash": chain.genesis_hash,
                },
                "output_dir": str(tmp_path / "mod"),
                "records": [],
                "mode": "finalized",
            },
            api=api,
        )
    )
    assert mod.mode == "finalized"


def test_export_respects_max_items_bound(chain: ChainRef, tmp_path: Path) -> None:
    records = tuple(
        _tx(
            chain,
            tx_hash="0x" + f"{i:02x}" * 32,
            sequence=i,
            block_hash="0x" + "dd" * 32,
        )
        for i in range(1, 5)
    )
    with pytest.raises(InvalidRequestError):
        WalletExportRequest(
            scope="wallet:0xabc",
            chain=chain,
            output_dir=str(tmp_path),
            records=records,
            bounds=ScanBounds(max_items=2),
        )


# ---------------------------------------------------------------------------
# Trust / allowlists
# ---------------------------------------------------------------------------


def test_untrusted_rejects_provider_url_outside_allowlist(
    processor: WalletLedgerProcessor, chain: ChainRef
) -> None:
    api = WalletProcessorAPI(
        processor=processor,
        trust=TrustLevel.UNTRUSTED,
        trust_policy=TrustPolicy(allowed_provider_hosts=frozenset({"rpc.example.com"})),
    )
    request = WalletIngestRequest(
        scope="wallet:0xabc",
        chain=chain,
        provider_url="https://evil.example.net/rpc",
    )
    with pytest.raises(InvalidRequestError, match="allowlist"):
        _run(api.wallet_ingest(request))


def test_untrusted_allows_allowlisted_host(
    processor: WalletLedgerProcessor, chain: ChainRef
) -> None:
    api = WalletProcessorAPI(
        processor=processor,
        trust=TrustLevel.UNTRUSTED,
        trust_policy=TrustPolicy(allowed_provider_hosts=frozenset({"rpc.example.com"})),
        clock=lambda: NOW,
    )
    request = WalletIngestRequest(
        scope="wallet:0xabc",
        chain=chain,
        provider_url="https://rpc.example.com/v1",
        bounds=ScanBounds(max_items=10, max_pages=2, max_requests=2),
    )
    result = _run(api.wallet_ingest(request))
    assert result.job_id


def test_untrusted_rejects_inline_secrets_and_secret_refs(
    processor: WalletLedgerProcessor, chain: ChainRef
) -> None:
    api = WalletProcessorAPI(
        processor=processor,
        trust=TrustLevel.UNTRUSTED,
        trust_policy=TrustPolicy(
            allowed_secret_prefixes=frozenset({"vault://wallets/"})
        ),
    )
    with pytest.raises(InvalidRequestError):
        _run(
            api.wallet_ingest(
                WalletIngestRequest(
                    scope="wallet:0xabc",
                    chain=chain,
                    # Value is a detector placeholder so proposal gates do not
                    # treat the fixture as concrete secret material.
                    options={"api_key": "placeholder"},
                )
            )
        )
    with pytest.raises(InvalidRequestError, match="allowlist"):
        _run(
            api.wallet_ingest(
                WalletIngestRequest(
                    scope="wallet:0xabc",
                    chain=chain,
                    secret_reference="env://NOT_ALLOWED",
                )
            )
        )
    # Allowlisted secret reference shape is accepted (no resolution here).
    ok = WalletIngestRequest(
        scope="wallet:0xabc",
        chain=chain,
        secret_reference="vault://wallets/provider-token",
        bounds=ScanBounds(max_items=5, max_pages=1, max_requests=1),
    )
    result = _run(api.wallet_ingest(ok))
    assert result.records_accepted >= 0


def test_forbidden_sign_option_rejected(
    api: WalletProcessorAPI, chain: ChainRef
) -> None:
    with pytest.raises(UnsupportedCapabilityError):
        _run(
            api.wallet_ingest(
                WalletIngestRequest(
                    scope="wallet:0xabc",
                    chain=chain,
                    options={"sign": True},
                )
            )
        )


# ---------------------------------------------------------------------------
# Capabilities / verify
# ---------------------------------------------------------------------------


def test_list_families_and_capabilities_without_chain_load() -> None:
    api = WalletProcessorAPI()
    listing = api.list_families()
    assert listing.families
    families = {f["family"] for f in listing.families}
    assert "ethereum" in families or "bitcoin" in families
    for fam in listing.families:
        assert fam["supports_sign"] is False
        assert fam["supports_broadcast"] is False
    caps = api.capabilities(CapabilitiesRequest(family="ethereum"))
    assert caps.selected is not None
    assert caps.selected["supports_sign"] is False


def test_verify_manifest_dict_and_path(
    api: WalletProcessorAPI, chain: ChainRef, tmp_path: Path
) -> None:
    records = (
        _tx(
            chain,
            tx_hash="0x" + "44" * 32,
            sequence=3,
            block_hash="0x" + "ee" * 32,
        ),
    )
    export = _run(
        api.wallet_export(
            WalletExportRequest(
                scope="wallet:0xabc",
                chain=chain,
                output_dir=str(tmp_path / "v"),
                records=records,
            )
        )
    )
    path_result = api.verify_manifest(
        VerifyManifestRequest(path=str(tmp_path / "v" / "export-manifest.json"))
    )
    assert path_result.ok is True
    assert path_result.record_count == 1

    bad = api.verify_manifest(
        VerifyManifestRequest(
            manifest={
                "manifest_id": "x",
                "record_count": 2,
                "partitions": [{"record_count": 1}],
                "finality_counts": {"finalized": 1},
                "warning_count": 0,
                "warnings": [],
                "status": "complete",
            }
        )
    )
    assert bad.ok is False
    assert bad.errors

    # Export result does not embed payloads
    d = export.to_dict()
    assert "records" not in d
    assert d["mode"] == "finalized"
