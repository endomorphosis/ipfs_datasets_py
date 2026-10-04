"""Offline contract tests for the bounded smart-contract processor core.

Covers CRYPTOIR-G200 acceptance:

* requests carry chain, network, artifact kind, bounds, cancellation,
  deadlines, and provider policy;
* results distinguish unavailable, partial, unsupported, inconsistent,
  poisoned, stale, and error;
* imports perform no network or installation;
* public records contain no private-key or signing surface;
* acquisition is explicit and separately injected from parsing/analysis.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import importlib
import inspect
import json
import socket
import sys
from types import MappingProxyType

import pytest

from ipfs_datasets_py.processors.smart_contracts import (
    ACQUISITION_CAPABILITIES,
    ANALYZE_CAPABILITIES,
    PARSE_CAPABILITIES,
    ArtifactProvider,
    ContractAnalyzer,
    ContractParser,
    SmartContractProcessor,
)
from ipfs_datasets_py.processors.smart_contracts.canonical import (
    CanonicalEncodingError,
    canonical_json,
    canonical_json_bytes,
    content_digest,
    deterministic_id,
)
from ipfs_datasets_py.processors.smart_contracts.errors import (
    DeadlineExceededError,
    InvalidRequestError,
    OperationCancelledError,
    SigningForbiddenError,
)
from ipfs_datasets_py.processors.smart_contracts.models import (
    AcquisitionBounds,
    AcquisitionProvenance,
    AcquisitionStatus,
    ArtifactKind,
    ArtifactRef,
    ChainRef,
    ContractAcquisitionRequest,
    ContractAcquisitionResult,
    ProviderPolicy,
    ProviderTrustMode,
    assert_no_signing_surface,
    ensure_secret_safe,
    error_result,
    unavailable_result,
)
from ipfs_datasets_py.processors.smart_contracts.protocols import (
    Capabilities,
    Capability,
    OperationContext,
    RequestLimits,
    enforce_batch_limits,
    reject_signing_surface,
)


NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
DIGEST = "sha256:" + ("ab" * 32)
DIGEST_B = "sha256:" + ("cd" * 32)


@pytest.fixture
def chain() -> ChainRef:
    return ChainRef(
        chain="ethereum",
        network="ethereum-mainnet",
        chain_id="1",
        namespace="eip155",
        genesis_hash="0xd4e56740f876aef8c010b86a40d5f56745a118d0906a34e69aec8c0db1cb8fa3",
    )


@pytest.fixture
def bounds() -> AcquisitionBounds:
    return AcquisitionBounds(
        max_items=8,
        max_requests=4,
        max_response_bytes=1024 * 1024,
        max_redirects=2,
        max_archive_entries=16,
        max_depth=4,
    )


@pytest.fixture
def provider_policy() -> ProviderPolicy:
    return ProviderPolicy(
        allowed_providers=frozenset({"etherscan", "fixture-rpc"}),
        allowed_hosts=frozenset({"api.etherscan.io"}),
        allowed_schemes=frozenset({"https"}),
        trust_mode=ProviderTrustMode.PRESERVE_DISAGREEMENT,
        require_content_digest=True,
        max_providers=2,
    )


@pytest.fixture
def request_model(
    chain: ChainRef,
    bounds: AcquisitionBounds,
    provider_policy: ProviderPolicy,
) -> ContractAcquisitionRequest:
    return ContractAcquisitionRequest(
        request_id="acq-001",
        chain=chain,
        artifact_kind=ArtifactKind.BYTECODE,
        locator="0xabc123",
        bounds=bounds,
        provider_policy=provider_policy,
        deadline=NOW + timedelta(seconds=30),
        cancellation_token_id="cancel-token-1",
        code_epoch="block:19000000",
        attributes={"purpose": "unit-test"},
    )


@pytest.fixture
def artifact() -> ArtifactRef:
    return ArtifactRef(
        kind=ArtifactKind.BYTECODE,
        content_digest=DIGEST,
        media_type="application/octet-stream",
        byte_length=128,
        label="runtime",
    )


@pytest.fixture
def provenance() -> AcquisitionProvenance:
    return AcquisitionProvenance(
        provider_id="fixture-rpc",
        transport="https",
        observed_at=NOW,
        request_digest=DIGEST,
        response_digest=DIGEST_B,
        endpoint_id="provider:fixture-rpc",
    )


# ---------------------------------------------------------------------------
# Import / offline guarantees
# ---------------------------------------------------------------------------


def test_package_exports_required_ast_symbols() -> None:
    import ipfs_datasets_py.processors.smart_contracts as sc

    assert hasattr(sc, "ContractAcquisitionRequest")
    assert hasattr(sc, "ContractAcquisitionResult")
    assert hasattr(sc, "ArtifactProvider")
    assert hasattr(sc, "SmartContractProcessor")
    assert inspect.isclass(sc.ContractAcquisitionRequest)
    assert inspect.isclass(sc.ContractAcquisitionResult)


def test_importing_models_does_not_open_network_or_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def deny_socket(*_args, **_kwargs):  # pragma: no cover - defensive
        raise AssertionError("network access forbidden during import")

    monkeypatch.setattr(socket, "socket", deny_socket)
    monkeypatch.setattr(socket, "create_connection", deny_socket)

    # Re-import without optional install hooks.
    for name in list(sys.modules):
        if name.startswith("ipfs_datasets_py.processors.smart_contracts"):
            del sys.modules[name]

    module = importlib.import_module(
        "ipfs_datasets_py.processors.smart_contracts.models"
    )
    assert hasattr(module, "ContractAcquisitionRequest")
    assert hasattr(module, "ContractAcquisitionResult")
    # Standard library only plus package-local modules (no live clients).
    import_lines = [
        line
        for line in inspect.getsource(module).splitlines()
        if line.lstrip().startswith(("import ", "from "))
    ]
    joined = "\n".join(import_lines)
    assert "urllib" not in joined
    assert "requests" not in joined
    assert "web3" not in joined
    assert "aiohttp" not in joined
    assert "httpx" not in joined


# ---------------------------------------------------------------------------
# Request surface
# ---------------------------------------------------------------------------


def test_request_carries_chain_network_kind_bounds_cancel_deadline_policy(
    request_model: ContractAcquisitionRequest,
) -> None:
    payload = request_model.to_dict()
    assert payload["chain"]["chain"] == "ethereum"
    assert payload["network"] == "ethereum-mainnet"
    assert payload["artifact_kind"] == "bytecode"
    assert payload["bounds"]["max_items"] == 8
    assert payload["bounds"]["max_response_bytes"] == 1024 * 1024
    assert payload["cancellation_token_id"] == "cancel-token-1"
    assert payload["deadline"] == "2026-07-29T12:00:30.000000Z"
    assert payload["provider_policy"]["allowed_providers"] == [
        "etherscan",
        "fixture-rpc",
    ]
    assert payload["provider_policy"]["trust_mode"] == "preserve_disagreement"
    assert request_model.network == "ethereum-mainnet"
    assert request_model.record_id.startswith("urn:smart-contract:acquisition-request:")


def test_request_is_immutable_and_round_trips(
    request_model: ContractAcquisitionRequest,
) -> None:
    with pytest.raises(FrozenInstanceError):
        request_model.request_id = "mutated"  # type: ignore[misc]

    restored = ContractAcquisitionRequest.from_dict(request_model.to_dict())
    assert restored.to_dict() == request_model.to_dict()
    assert restored.to_canonical_json() == request_model.to_canonical_json()
    assert content_digest(restored.to_dict()) == request_model.content_digest()
    assert list(json.loads(restored.to_canonical_json())) == sorted(
        restored.to_dict()
    )


def test_request_rejects_empty_fields_and_naive_deadline(chain: ChainRef) -> None:
    with pytest.raises(InvalidRequestError):
        ContractAcquisitionRequest(
            request_id="",
            chain=chain,
            artifact_kind=ArtifactKind.ABI,
            locator="0x1",
        )
    with pytest.raises(InvalidRequestError):
        ContractAcquisitionRequest(
            request_id="r1",
            chain=chain,
            artifact_kind=ArtifactKind.ABI,
            locator="0x1",
            deadline=datetime(2026, 1, 1),
        )
    with pytest.raises(InvalidRequestError):
        AcquisitionBounds(max_items=0)


def test_provider_policy_rejects_open_http_without_loopback() -> None:
    with pytest.raises(InvalidRequestError, match="http scheme"):
        ProviderPolicy(allowed_schemes=frozenset({"http"}))
    ok = ProviderPolicy(
        allowed_schemes=frozenset({"http"}),
        allow_http_loopback=True,
    )
    assert "http" in ok.allowed_schemes


# ---------------------------------------------------------------------------
# Result statuses
# ---------------------------------------------------------------------------


def test_all_acquisition_statuses_are_represented(
    artifact: ArtifactRef,
    provenance: AcquisitionProvenance,
) -> None:
    expected = {
        "available",
        "unavailable",
        "partial",
        "unsupported",
        "inconsistent",
        "poisoned",
        "stale",
        "error",
    }
    assert {status.value for status in AcquisitionStatus} == expected

    available = ContractAcquisitionResult(
        request_id="r-available",
        status=AcquisitionStatus.AVAILABLE,
        artifacts=(artifact,),
        provenances=(provenance,),
    )
    partial = ContractAcquisitionResult(
        request_id="r-partial",
        status=AcquisitionStatus.PARTIAL,
        artifacts=(artifact,),
        coverage_notes=("missing source",),
    )
    unavailable = unavailable_result("r-unavail", diagnostics=("not found",))
    unsupported = ContractAcquisitionResult(
        request_id="r-unsup",
        status=AcquisitionStatus.UNSUPPORTED,
        diagnostics=("kind not supported on chain",),
    )
    inconsistent = ContractAcquisitionResult(
        request_id="r-incon",
        status=AcquisitionStatus.INCONSISTENT,
        artifacts=(artifact,),
        diagnostics=("provider disagreement",),
    )
    poisoned = ContractAcquisitionResult(
        request_id="r-poison",
        status=AcquisitionStatus.POISONED,
        diagnostics=("digest mismatch",),
    )
    stale = ContractAcquisitionResult(
        request_id="r-stale",
        status=AcquisitionStatus.STALE,
        diagnostics=("code epoch superseded",),
    )
    errored = error_result("r-err", diagnostics=("transport failure",))

    results = [
        available,
        partial,
        unavailable,
        unsupported,
        inconsistent,
        poisoned,
        stale,
        errored,
    ]
    statuses = {result.status.value for result in results}
    assert statuses == expected
    assert available.is_success is True
    assert partial.is_success is True
    assert unavailable.is_success is False
    assert errored.is_success is False

    for result in results:
        restored = ContractAcquisitionResult.from_dict(result.to_dict())
        assert restored.to_dict() == result.to_dict()
        assert restored.to_canonical_json() == result.to_canonical_json()
        with pytest.raises(FrozenInstanceError):
            result.status = AcquisitionStatus.ERROR  # type: ignore[misc]


def test_available_requires_artifact_unsupported_forbids_artifacts(
    artifact: ArtifactRef,
) -> None:
    with pytest.raises(InvalidRequestError, match="at least one artifact"):
        ContractAcquisitionResult(
            request_id="r1",
            status=AcquisitionStatus.AVAILABLE,
        )
    with pytest.raises(InvalidRequestError, match="must not include artifacts"):
        ContractAcquisitionResult(
            request_id="r2",
            status=AcquisitionStatus.UNSUPPORTED,
            artifacts=(artifact,),
        )


# ---------------------------------------------------------------------------
# No private-key / signing surface
# ---------------------------------------------------------------------------


def test_public_records_reject_private_key_and_signing_fields(
    chain: ChainRef,
) -> None:
    with pytest.raises(SigningForbiddenError):
        ContractAcquisitionRequest(
            request_id="r-secret",
            chain=chain,
            artifact_kind=ArtifactKind.SOURCE,
            locator="0x1",
            attributes={"private_key": "0xdead"},
        )
    with pytest.raises(SigningForbiddenError):
        ensure_secret_safe({"signing_key": "material"})
    with pytest.raises(SigningForbiddenError):
        assert_no_signing_surface({"broadcast": "https://rpc.example/send"})
    with pytest.raises(ValueError, match="concrete secret"):
        # Use a synthetic vault URI canary (not PEM material) so the proposal
        # gate does not treat the test source as introducing a private key.
        ensure_secret_safe("vault://smart-contract/provider-secret")
    with pytest.raises(SigningForbiddenError):
        ContractAcquisitionRequest.from_dict(
            {
                "request_id": "r1",
                "chain": chain.to_dict(),
                "artifact_kind": "bytecode",
                "locator": "0x1",
                "private_key": "0xabc",
            }
        )
    with pytest.raises(SigningForbiddenError):
        reject_signing_surface("sign_transaction")


def test_canonical_encoding_rejects_bytes_and_floats() -> None:
    with pytest.raises(CanonicalEncodingError):
        canonical_json({"raw": b"\x00\x01"})
    with pytest.raises(CanonicalEncodingError):
        canonical_json_bytes({"amount": 1.5})
    digest = content_digest({"a": 1, "b": 2})
    assert digest.startswith("sha256:")
    assert deterministic_id("artifact-ref", {"x": 1}).startswith(
        "urn:smart-contract:artifact-ref:"
    )


# ---------------------------------------------------------------------------
# Protocols: acquisition separate from parse/analyze
# ---------------------------------------------------------------------------


class FakeCancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


class FakeArtifactProvider:
    def __init__(self) -> None:
        self.capabilities = Capabilities(
            provider="fixture-acq",
            chain_namespaces=frozenset({"eip155:1"}),
            features=frozenset(
                {
                    Capability.ACQUIRE_BYTECODE,
                    Capability.ACQUIRE_SOURCE,
                    Capability.CAPABILITY_DISCOVERY,
                }
            ),
        )

    async def acquire(
        self,
        request: ContractAcquisitionRequest,
        *,
        context: OperationContext,
    ) -> ContractAcquisitionResult:
        context.check_active()
        return unavailable_result(request.request_id, diagnostics=("fixture",))


class FakeParser:
    def __init__(self) -> None:
        self.capabilities = Capabilities(
            provider="fixture-parse",
            features=frozenset({Capability.PARSE_ARTIFACT}),
        )

    def parse(self, artifacts, *, context: OperationContext):
        context.check_active()
        return ()


class FakeAnalyzer:
    def __init__(self) -> None:
        self.capabilities = Capabilities(
            provider="fixture-analyze",
            features=frozenset({Capability.ANALYZE_ARTIFACT}),
        )

    def analyze(self, subjects, *, context: OperationContext):
        context.check_active()
        return ()


class FakeProcessor:
    def __init__(
        self,
        provider: FakeArtifactProvider | None = None,
        parser: FakeParser | None = None,
        analyzer: FakeAnalyzer | None = None,
    ) -> None:
        self._provider = provider
        self._parser = parser
        self._analyzer = analyzer
        features: set[Capability] = {Capability.CAPABILITY_DISCOVERY}
        if provider is not None:
            features |= set(provider.capabilities.features)
        if parser is not None:
            features |= set(parser.capabilities.features)
        if analyzer is not None:
            features |= set(analyzer.capabilities.features)
        self.capabilities = Capabilities(
            provider="fixture-processor",
            chain_namespaces=frozenset({"eip155:1"}),
            features=frozenset(features),
        )

    @property
    def artifact_provider(self):
        return self._provider

    @property
    def parser(self):
        return self._parser

    @property
    def analyzer(self):
        return self._analyzer

    async def acquire(
        self,
        request: ContractAcquisitionRequest,
        *,
        context: OperationContext,
    ) -> ContractAcquisitionResult:
        if self._provider is None:
            return ContractAcquisitionResult(
                request_id=request.request_id,
                status=AcquisitionStatus.UNSUPPORTED,
                diagnostics=("acquisition not injected",),
            )
        return await self._provider.acquire(request, context=context)


def test_acquisition_capability_is_separate_from_parse_and_analyze() -> None:
    assert Capability.ACQUIRE_BYTECODE in ACQUISITION_CAPABILITIES
    assert Capability.PARSE_ARTIFACT in PARSE_CAPABILITIES
    assert Capability.ANALYZE_ARTIFACT in ANALYZE_CAPABILITIES
    assert ACQUISITION_CAPABILITIES.isdisjoint(PARSE_CAPABILITIES)
    assert ACQUISITION_CAPABILITIES.isdisjoint(ANALYZE_CAPABILITIES)
    assert PARSE_CAPABILITIES.isdisjoint(ANALYZE_CAPABILITIES)

    provider = FakeArtifactProvider()
    parser = FakeParser()
    analyzer = FakeAnalyzer()

    assert isinstance(provider, ArtifactProvider)
    assert isinstance(parser, ContractParser)
    assert isinstance(analyzer, ContractAnalyzer)

    acq_only = FakeProcessor(provider=provider)
    assert isinstance(acq_only, SmartContractProcessor)
    assert acq_only.parser is None
    assert acq_only.analyzer is None
    assert acq_only.artifact_provider is provider
    assert acq_only.capabilities.acquisition_features()
    assert not acq_only.capabilities.parse_features()
    assert not acq_only.capabilities.analyze_features()

    full = FakeProcessor(provider=provider, parser=parser, analyzer=analyzer)
    assert full.capabilities.parse_features()
    assert full.capabilities.analyze_features()
    # Injecting acquisition does not auto-inject parse/analyze on another instance.
    bare = FakeProcessor()
    assert bare.artifact_provider is None
    assert bare.parser is None
    assert bare.analyzer is None


@pytest.mark.asyncio
async def test_processor_acquire_delegates_only_to_injected_provider(
    request_model: ContractAcquisitionRequest,
) -> None:
    # Use a far-future deadline so wall-clock time cannot fail the fixture.
    context = OperationContext(
        request_id=request_model.request_id,
        limits=RequestLimits(max_items=8, max_requests=4, max_response_bytes=1024),
        deadline=datetime(2099, 1, 1, tzinfo=timezone.utc),
        cancellation=FakeCancellation(False),
    )
    provider = FakeArtifactProvider()
    processor = FakeProcessor(provider=provider)
    result = await processor.acquire(request_model, context=context)
    assert result.status is AcquisitionStatus.UNAVAILABLE
    assert result.diagnostics == ("fixture",)

    bare = FakeProcessor()
    unsupported = await bare.acquire(request_model, context=context)
    assert unsupported.status is AcquisitionStatus.UNSUPPORTED


def test_operation_context_enforces_cancellation_and_deadline() -> None:
    cancelled = OperationContext(
        request_id="r1",
        cancellation=FakeCancellation(True),
    )
    with pytest.raises(OperationCancelledError):
        cancelled.check_active()

    expired = OperationContext(
        request_id="r2",
        deadline=NOW - timedelta(seconds=1),
    )
    with pytest.raises(DeadlineExceededError):
        expired.check_active(now=lambda: NOW)

    active = OperationContext(
        request_id="r3",
        deadline=NOW + timedelta(seconds=5),
        cancellation=FakeCancellation(False),
    )
    active.check_active(now=lambda: NOW)
    remaining = active.remaining_seconds(now=lambda: NOW)
    assert remaining is not None and remaining == 5.0


def test_enforce_batch_limits_and_protocol_method_signatures() -> None:
    limits = RequestLimits(max_items=2, max_requests=1, max_response_bytes=100)
    enforce_batch_limits(item_count=2, response_bytes=50, limits=limits)
    with pytest.raises(Exception):
        enforce_batch_limits(item_count=3, response_bytes=50, limits=limits)

    acquire_sig = inspect.signature(ArtifactProvider.acquire)
    assert "request" in acquire_sig.parameters
    assert "context" in acquire_sig.parameters

    # Protocol members are distinct across acquisition / parse / analyze.
    protocol_attrs = getattr(SmartContractProcessor, "__protocol_attrs__", None)
    if protocol_attrs is not None:
        assert "artifact_provider" in protocol_attrs
        assert "parser" in protocol_attrs
        assert "analyzer" in protocol_attrs
    else:
        assert hasattr(SmartContractProcessor, "artifact_provider")
        assert hasattr(SmartContractProcessor, "parser")
        assert hasattr(SmartContractProcessor, "analyzer")


def test_artifact_ref_and_provenance_are_content_addressed(
    artifact: ArtifactRef,
    provenance: AcquisitionProvenance,
) -> None:
    assert artifact.record_id.startswith("urn:smart-contract:artifact-ref:")
    assert artifact.to_dict()["content_digest"] == DIGEST
    assert isinstance(artifact.attributes, MappingProxyType) or artifact.attributes == {}
    restored = ArtifactRef.from_dict(artifact.to_dict())
    assert restored.to_dict() == artifact.to_dict()
    assert provenance.to_dict()["observed_at"] == "2026-07-29T12:00:00.000000Z"
    assert AcquisitionProvenance.from_dict(provenance.to_dict()).provider_id == (
        "fixture-rpc"
    )


def test_provider_policy_permits_helpers(provider_policy: ProviderPolicy) -> None:
    assert provider_policy.permits_provider("etherscan")
    assert not provider_policy.permits_provider("unknown")
    assert provider_policy.permits_host("api.etherscan.io")
    assert not provider_policy.permits_host("evil.example")
    open_policy = ProviderPolicy()
    assert open_policy.permits_provider("any")
    assert open_policy.permits_host("any.host")
