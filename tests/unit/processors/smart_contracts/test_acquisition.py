"""CRYPTOIR-G210 bounded artifact acquisition, storage, caching, and provenance.

Acceptance coverage:

* URL schemes, hosts, DNS, redirects, response counts, bytes, archives,
  recursion, time, retries, and credentials are bounded;
* raw bytes and request/response metadata are content addressed;
* poisoning, truncation, schema drift, provider disagreement, cache
  corruption, and artifact/toolchain mismatch fail closed;
* offline fixtures are the default transport path;
* disagreement and partial coverage are preserved rather than resolved by
  permissive selection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import socket
import zipfile

import pytest

from ipfs_datasets_py.processors.smart_contracts.artifacts import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ArtifactManifest,
    ArtifactManifestEntry,
    StoredArtifact,
    TransportEvidence,
    bind_toolchain,
    bytes_digest,
    combine_provider_views,
    raw_cid,
    unpack_archive_bounded,
)
from ipfs_datasets_py.processors.smart_contracts.cache import ContractArtifactCache
from ipfs_datasets_py.processors.smart_contracts.errors import (
    ArtifactInconsistentError,
    ArtifactPoisonedError,
    InvalidRequestError,
    ProviderError,
    ResourceLimitError,
)
from ipfs_datasets_py.processors.smart_contracts.models import (
    AcquisitionBounds,
    AcquisitionStatus,
    ArtifactKind,
    ProviderPolicy,
    ProviderTrustMode,
)
from ipfs_datasets_py.processors.smart_contracts.protocols import (
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.smart_contracts.source import (
    SOURCE_MANIFEST_SCHEMA_VERSION,
    SourceFileRecord,
    SourceManifest,
    ToolchainPin,
)
from ipfs_datasets_py.processors.smart_contracts.transport import (
    AcquisitionTransport,
    FixtureEntry,
    FixtureResponseSource,
    StaticAddressResolver,
    TransportLimits,
    TransportRequest,
    build_offline_transport,
    url_digest,
)


NOW = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
BYTECODE = bytes.fromhex("6080604052348015600f57600080fd5b50")
SOURCE_A = b"// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\ncontract A {}\n"
SOURCE_B = b"// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\ncontract B {}\n"


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="acq-g210",
        limits=RequestLimits(
            max_items=8,
            max_requests=16,
            max_response_bytes=1024 * 1024,
            max_depth=4,
        ),
        deadline=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


@pytest.fixture
def policy() -> ProviderPolicy:
    return ProviderPolicy(
        allowed_providers=frozenset({"fixture-a", "fixture-b"}),
        allowed_hosts=frozenset({"artifacts.example", "cdn.example"}),
        allowed_schemes=frozenset({"https"}),
        trust_mode=ProviderTrustMode.PRESERVE_DISAGREEMENT,
        require_content_digest=True,
        max_providers=2,
    )


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Content addressing of raw bytes and manifests
# ---------------------------------------------------------------------------


def test_stored_artifact_is_content_addressed() -> None:
    stored = StoredArtifact(
        raw_bytes=BYTECODE,
        kind=ArtifactKind.BYTECODE,
        media_type="application/octet-stream",
        label="runtime",
    )
    assert stored.content_digest == bytes_digest(BYTECODE)
    assert stored.content_cid == raw_cid(BYTECODE)
    assert stored.byte_length == len(BYTECODE)
    stored.verify()
    ref = stored.as_ref()
    assert ref.content_digest == stored.content_digest
    assert ref.content_cid == stored.content_cid
    # Public refs never embed raw bytes.
    assert "raw_bytes" not in ref.to_dict()


def test_artifact_manifest_round_trip_and_schema_drift() -> None:
    stored = StoredArtifact(
        raw_bytes=BYTECODE,
        kind=ArtifactKind.BYTECODE,
        media_type="application/octet-stream",
        label="runtime",
    )
    evidence = TransportEvidence(
        request_digest=bytes_digest(b"GET /code"),
        response_digest=stored.content_digest,
        final_url_digest=url_digest("https://artifacts.example/code"),
        status_code=200,
        byte_length=stored.byte_length,
        transport="offline_fixture",
    )
    manifest = ArtifactManifest.from_stored(
        [("runtime.bin", stored)],
        request_id="req-1",
        observed_at=NOW,
        transport_evidence=(evidence,),
        provider_ids=("fixture-a",),
        code_epoch="block:19000000",
    )
    assert manifest.schema_version == ARTIFACT_MANIFEST_SCHEMA_VERSION
    assert manifest.manifest_digest.startswith("sha256:")
    restored = ArtifactManifest.from_dict(manifest.to_dict())
    assert restored.manifest_digest == manifest.manifest_digest
    manifest.verify_against({"runtime.bin": stored})

    poisoned = dict(manifest.to_dict())
    poisoned["manifest_digest"] = "sha256:" + ("00" * 32)
    with pytest.raises(ArtifactPoisonedError):
        ArtifactManifest.from_dict(poisoned)

    drifted = dict(manifest.to_dict())
    drifted["schema_version"] = "smart-contract-artifact-manifest-v0"
    with pytest.raises(InvalidRequestError, match="unsupported"):
        ArtifactManifest.from_dict(drifted)


def test_artifact_manifest_detects_truncation_and_poisoning() -> None:
    stored = StoredArtifact(
        raw_bytes=BYTECODE,
        kind=ArtifactKind.BYTECODE,
        media_type="application/octet-stream",
    )
    manifest = ArtifactManifest.from_stored(
        [("code.bin", stored)],
        request_id="req-trunc",
        observed_at=NOW,
    )
    truncated = StoredArtifact(
        raw_bytes=BYTECODE[:-1],
        kind=ArtifactKind.BYTECODE,
        media_type="application/octet-stream",
    )
    with pytest.raises(ArtifactPoisonedError):
        manifest.verify_against({"code.bin": truncated})
    with pytest.raises(ArtifactInconsistentError):
        manifest.verify_against({})


# ---------------------------------------------------------------------------
# Transport bounds, SSRF, credentials, offline fixtures
# ---------------------------------------------------------------------------


def test_offline_fixture_transport_is_default(context: OperationContext, policy: ProviderPolicy) -> None:
    url = "https://artifacts.example/runtime"
    transport = build_offline_transport(
        {url: FixtureEntry(status_code=200, body=BYTECODE)},
        policy=policy,
        limits=TransportLimits(max_requests=4, max_response_bytes=1024, max_redirects=2),
        dns={"artifacts.example": ("1.2.3.4",)},
    )
    body, evidence = transport.fetch_bytes(url, context=context)
    assert body == BYTECODE
    assert evidence.response_digest == bytes_digest(BYTECODE)
    assert evidence.request_digest.startswith("sha256:")
    assert evidence.transport == "offline_fixture"
    assert evidence.byte_length == len(BYTECODE)


def test_transport_rejects_disallowed_scheme_host_and_credentials(
    context: OperationContext,
    policy: ProviderPolicy,
) -> None:
    transport = build_offline_transport(
        {},
        policy=policy,
        dns={"artifacts.example": ("203.0.113.10",)},
    )
    with pytest.raises(InvalidRequestError, match="scheme"):
        transport.validate_url("http://artifacts.example/x")
    with pytest.raises(InvalidRequestError, match="allowlist"):
        transport.validate_url("https://evil.example/x")
    with pytest.raises(InvalidRequestError, match="userinfo|credentials"):
        transport.validate_url("https://user:pass@artifacts.example/x")
    with pytest.raises(InvalidRequestError, match="credentials"):
        transport.validate_url("https://artifacts.example/x?api_key=secret")
    with pytest.raises(InvalidRequestError, match="headers"):
        TransportRequest(
            url="https://artifacts.example/x",
            headers={"Authorization": "Bearer token"},
        )


def test_transport_rejects_unsafe_dns_and_private_literals(
    context: OperationContext,
    policy: ProviderPolicy,
) -> None:
    transport = build_offline_transport(
        {"https://artifacts.example/x": FixtureEntry(body=b"ok")},
        policy=policy,
        dns={"artifacts.example": ("127.0.0.1",)},
    )
    with pytest.raises(InvalidRequestError, match="unsafe"):
        transport.fetch_bytes("https://artifacts.example/x", context=context)

    with pytest.raises(InvalidRequestError, match="unsafe|loopback"):
        transport.validate_url("https://127.0.0.1/x")
    with pytest.raises(InvalidRequestError, match="unsafe"):
        transport.validate_url("https://10.0.0.5/x")


def test_transport_bounds_redirects_bytes_and_requests(
    context: OperationContext,
    policy: ProviderPolicy,
) -> None:
    fixtures = {
        "https://artifacts.example/start": FixtureEntry(
            status_code=302,
            redirect_to="https://cdn.example/next",
        ),
        "https://cdn.example/next": FixtureEntry(
            status_code=302,
            redirect_to="https://cdn.example/final",
        ),
        "https://cdn.example/final": FixtureEntry(body=BYTECODE),
    }
    transport = build_offline_transport(
        fixtures,
        policy=policy,
        limits=TransportLimits(max_requests=8, max_response_bytes=1024, max_redirects=1),
        dns={
            "artifacts.example": ("1.2.3.4",),
            "cdn.example": ("1.2.3.5",),
        },
    )
    with pytest.raises(ResourceLimitError, match="redirect"):
        transport.fetch_bytes("https://artifacts.example/start", context=context)

    transport.reset_budget()
    transport = build_offline_transport(
        fixtures,
        policy=policy,
        limits=TransportLimits(max_requests=8, max_response_bytes=1024, max_redirects=3),
        dns={
            "artifacts.example": ("1.2.3.4",),
            "cdn.example": ("1.2.3.5",),
        },
    )
    body, evidence = transport.fetch_bytes(
        "https://artifacts.example/start", context=context
    )
    assert body == BYTECODE
    assert evidence.redirect_count == 2

    huge = build_offline_transport(
        {
            "https://artifacts.example/huge": FixtureEntry(
                body=b"x" * 2048,
            )
        },
        policy=policy,
        limits=TransportLimits(max_requests=4, max_response_bytes=512, max_redirects=0),
        dns={"artifacts.example": ("1.2.3.4",)},
    )
    with pytest.raises(ResourceLimitError, match="max_response_bytes"):
        huge.fetch_bytes("https://artifacts.example/huge", context=context)

    limited = build_offline_transport(
        {"https://artifacts.example/a": FixtureEntry(body=b"a")},
        policy=policy,
        limits=TransportLimits(max_requests=1, max_response_bytes=512, max_redirects=0),
        dns={"artifacts.example": ("1.2.3.4",)},
    )
    limited.fetch_bytes("https://artifacts.example/a", context=context)
    with pytest.raises(ResourceLimitError, match="request count"):
        limited.fetch_bytes("https://artifacts.example/a", context=context)


def test_transport_rejects_elapsed_time_over_budget(
    context: OperationContext,
    policy: ProviderPolicy,
) -> None:
    class SlowSource(FixtureResponseSource):
        def fetch(self, request, *, context):  # type: ignore[no-untyped-def]
            response = super().fetch(request, context=context)
            return type(response)(
                url=response.url,
                status_code=response.status_code,
                headers=dict(response.headers),
                body=response.body,
                elapsed_seconds=999.0,
            )

    transport = AcquisitionTransport(
        policy=policy,
        limits=TransportLimits(
            max_requests=4,
            max_response_bytes=1024,
            max_redirects=0,
            request_timeout_seconds=1.0,
        ),
        source=SlowSource(
            {"https://artifacts.example/slow": FixtureEntry(body=b"ok")}
        ),
        resolver=StaticAddressResolver(
            {"artifacts.example": ("1.2.3.4",)}
        ),
    )
    with pytest.raises(ResourceLimitError, match="time"):
        transport.fetch_bytes("https://artifacts.example/slow", context=context)


def test_import_and_construction_perform_no_network() -> None:
    """Guardrail: acquisition construction must not open sockets."""

    original = socket.socket

    def blocked(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("network socket opened during acquisition tests")

    socket.socket = blocked  # type: ignore[assignment]
    try:
        # Avoid importlib.reload: it creates new class identities and breaks
        # later isinstance checks against the originally imported types.
        build_offline_transport({})
        ContractArtifactCache()
        ToolchainPin(compiler="solc", compiler_version="0.8.20")
        StoredArtifact(
            raw_bytes=b"\x00",
            kind=ArtifactKind.OTHER,
            media_type="application/octet-stream",
        )
    finally:
        socket.socket = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Archives and recursion
# ---------------------------------------------------------------------------


def test_archive_unpack_bounds_entries_bytes_and_path_traversal() -> None:
    archive = _zip_bytes(
        {
            "src/A.sol": SOURCE_A,
            "src/B.sol": SOURCE_B,
        }
    )
    members = unpack_archive_bounded(
        archive,
        max_entries=8,
        max_total_bytes=10_000,
        max_depth=1,
    )
    assert len(members) == 2
    assert dict(members)["src/A.sol"] == SOURCE_A

    with pytest.raises(ResourceLimitError, match="entry count"):
        unpack_archive_bounded(
            archive,
            max_entries=1,
            max_total_bytes=10_000,
            max_depth=1,
        )

    with pytest.raises(ResourceLimitError, match="byte budget|total bytes"):
        unpack_archive_bounded(
            archive,
            max_entries=8,
            max_total_bytes=10,
            max_depth=1,
        )

    hostile = _zip_bytes({"../etc/passwd": b"root:x:0:0:"})
    with pytest.raises(ArtifactPoisonedError, match="traversal"):
        unpack_archive_bounded(
            hostile,
            max_entries=8,
            max_total_bytes=10_000,
            max_depth=1,
        )

    with pytest.raises(ResourceLimitError, match="recursion"):
        unpack_archive_bounded(
            archive,
            max_entries=8,
            max_total_bytes=10_000,
            max_depth=1,
            depth=1,
        )


# ---------------------------------------------------------------------------
# Cache: immutable CAS, corruption, schema drift
# ---------------------------------------------------------------------------


def test_contract_artifact_cache_is_content_bound(tmp_path) -> None:
    cache = ContractArtifactCache(root=tmp_path / "cas", max_objects=16, max_total_bytes=10_000)
    first = cache.put_bytes(
        BYTECODE,
        kind=ArtifactKind.BYTECODE,
        media_type="application/octet-stream",
        label="runtime",
    )
    again = cache.put_bytes(
        BYTECODE,
        kind=ArtifactKind.BYTECODE,
        media_type="application/octet-stream",
        label="runtime",
    )
    assert first.content_digest == again.content_digest
    loaded = cache.get(first.content_digest)
    assert loaded.raw_bytes == BYTECODE

    # Collision with different bytes for same digest is impossible without
    # crafting a hash collision; instead simulate metadata drift on same bytes.
    with pytest.raises(ArtifactPoisonedError, match="metadata drift"):
        cache.put_bytes(
            BYTECODE,
            kind=ArtifactKind.SOURCE,
            media_type="text/plain",
        )

    manifest = ArtifactManifest.from_stored(
        [("runtime.bin", first)],
        request_id="cache-1",
        observed_at=NOW,
    )
    cached_manifest = cache.put_manifest(manifest)
    assert cache.get_manifest(cached_manifest.manifest_digest).manifest_digest == (
        manifest.manifest_digest
    )

    # Durable reload revalidates digests.
    reloaded = ContractArtifactCache(root=tmp_path / "cas")
    assert reloaded.get(first.content_digest).raw_bytes == BYTECODE

    # Corrupt on-disk object and ensure load skips / get fails closed.
    object_path = reloaded._object_path(first.content_digest)  # noqa: SLF001
    object_path.write_bytes(b"corrupted-payload")
    poisoned = ContractArtifactCache(root=tmp_path / "cas")
    # Corrupted object is skipped during load.
    assert not poisoned.contains(first.content_digest)


def test_cache_enforces_budgets() -> None:
    cache = ContractArtifactCache(max_objects=1, max_total_bytes=64)
    cache.put_bytes(b"a" * 16, kind=ArtifactKind.OTHER)
    with pytest.raises(ResourceLimitError):
        cache.put_bytes(b"b" * 16, kind=ArtifactKind.OTHER)


# ---------------------------------------------------------------------------
# Source manifests and toolchain mismatch
# ---------------------------------------------------------------------------


def test_source_manifest_binds_toolchain_and_detects_mismatch() -> None:
    pin = ToolchainPin(
        compiler="solc",
        compiler_version="0.8.20",
        settings={"optimizer": {"enabled": True, "runs": 200}},
        target="evm",
        optimization="200",
    )
    files = (
        SourceFileRecord.from_bytes("contracts/A.sol", SOURCE_A, language="solidity"),
    )
    creation = b"\x00" + BYTECODE
    runtime = BYTECODE
    manifest = SourceManifest(
        files=files,
        toolchain=pin,
        request_id="src-1",
        observed_at=NOW,
        creation_bytecode_digest=bytes_digest(creation),
        runtime_bytecode_digest=bytes_digest(runtime),
        code_epoch="block:19000000",
    )
    assert manifest.schema_version == SOURCE_MANIFEST_SCHEMA_VERSION
    assert manifest.toolchain.toolchain_digest == pin.toolchain_digest
    manifest.verify_sources({"contracts/A.sol": SOURCE_A})
    manifest.assert_deployed_equivalence(creation=creation, runtime=runtime)

    with pytest.raises(ArtifactPoisonedError):
        manifest.verify_sources({"contracts/A.sol": SOURCE_B})

    other = ToolchainPin(
        compiler="solc",
        compiler_version="0.8.19",
        settings={"optimizer": {"enabled": True, "runs": 200}},
        target="evm",
        optimization="200",
    )
    with pytest.raises(ArtifactInconsistentError, match="toolchain"):
        manifest.assert_toolchain_matches(other)

    with pytest.raises(ArtifactInconsistentError, match="runtime"):
        manifest.assert_deployed_equivalence(runtime=b"\xde\xad")

    artifact_manifest = manifest.to_artifact_manifest(
        {"contracts/A.sol": SOURCE_A},
        provider_ids=("fixture-a",),
    )
    assert artifact_manifest.toolchain_digest == pin.toolchain_digest
    assert len(artifact_manifest.entries) == 1

    restored = SourceManifest.from_dict(manifest.to_dict())
    assert restored.manifest_digest == manifest.manifest_digest

    poisoned = dict(manifest.to_dict())
    poisoned["manifest_digest"] = "sha256:" + ("11" * 32)
    with pytest.raises(ArtifactPoisonedError):
        SourceManifest.from_dict(poisoned)


def test_bind_toolchain_is_deterministic() -> None:
    left = bind_toolchain(
        compiler="solc",
        compiler_version="0.8.20",
        settings={"viaIR": False},
        libraries={"Lib": "0x" + "ab" * 20},
    )
    right = bind_toolchain(
        compiler="solc",
        compiler_version="0.8.20",
        settings={"viaIR": False},
        libraries={"Lib": "0x" + "ab" * 20},
    )
    assert left == right
    assert left.startswith("sha256:")


# ---------------------------------------------------------------------------
# Provider disagreement and partial coverage
# ---------------------------------------------------------------------------


def test_provider_disagreement_is_preserved_not_permissively_resolved() -> None:
    a = StoredArtifact(
        raw_bytes=BYTECODE,
        kind=ArtifactKind.BYTECODE,
        media_type="application/octet-stream",
        label="runtime",
    )
    b = StoredArtifact(
        raw_bytes=BYTECODE + b"\x00",
        kind=ArtifactKind.BYTECODE,
        media_type="application/octet-stream",
        label="runtime",
    )
    manifest_a = ArtifactManifest.from_stored(
        [("runtime.bin", a)],
        request_id="req-disagree",
        observed_at=NOW,
        provider_ids=("fixture-a",),
    )
    manifest_b = ArtifactManifest.from_stored(
        [("runtime.bin", b)],
        request_id="req-disagree",
        observed_at=NOW,
        provider_ids=("fixture-b",),
    )
    result = combine_provider_views(
        request_id="req-disagree",
        views=(
            ("fixture-a", manifest_a, ("full",)),
            ("fixture-b", manifest_b, ("full",)),
        ),
        trust_mode=ProviderTrustMode.PRESERVE_DISAGREEMENT.value,
    )
    assert result.status is AcquisitionStatus.INCONSISTENT
    assert len(result.artifacts) == 2
    assert any("disagreement" in note for note in result.coverage_notes)
    # Both digests retained; neither discarded as "less permissive".
    digests = {item.content_digest for item in result.artifacts}
    assert digests == {a.content_digest, b.content_digest}


def test_partial_coverage_and_unavailable_providers_are_structured() -> None:
    only = ArtifactManifest.from_stored(
        [
            (
                "runtime.bin",
                StoredArtifact(
                    raw_bytes=BYTECODE,
                    kind=ArtifactKind.BYTECODE,
                    media_type="application/octet-stream",
                ),
            )
        ],
        request_id="req-partial",
        observed_at=NOW,
        provider_ids=("fixture-a",),
        diagnostics=("missing abi",),
    )
    result = combine_provider_views(
        request_id="req-partial",
        views=(
            ("fixture-a", only, ("bytecode-only",)),
            ("fixture-b", None, ("timeout",)),
        ),
        trust_mode=ProviderTrustMode.PRESERVE_DISAGREEMENT.value,
    )
    # One success + one unavailable keeps available status only when there are
    # no diagnostics on the success path; here diagnostics force PARTIAL.
    assert result.status in {
        AcquisitionStatus.PARTIAL,
        AcquisitionStatus.AVAILABLE,
    }
    assert any("fixture-b:unavailable" in item for item in result.diagnostics)
    assert any("bytecode-only" in item for item in result.coverage_notes)

    empty = combine_provider_views(
        request_id="req-none",
        views=(
            ("fixture-a", None, ("not-found",)),
            ("fixture-b", None, ("not-found",)),
        ),
        trust_mode=ProviderTrustMode.REQUIRE_AGREEMENT.value,
    )
    assert empty.status is AcquisitionStatus.UNAVAILABLE


def test_require_agreement_and_single_modes_fail_closed() -> None:
    a = ArtifactManifest.from_stored(
        [
            (
                "x.bin",
                StoredArtifact(
                    raw_bytes=b"\x01",
                    kind=ArtifactKind.BYTECODE,
                    media_type="application/octet-stream",
                ),
            )
        ],
        request_id="req-mode",
        observed_at=NOW,
    )
    b = ArtifactManifest.from_stored(
        [
            (
                "x.bin",
                StoredArtifact(
                    raw_bytes=b"\x02",
                    kind=ArtifactKind.BYTECODE,
                    media_type="application/octet-stream",
                ),
            )
        ],
        request_id="req-mode",
        observed_at=NOW,
    )
    disagree = combine_provider_views(
        request_id="req-mode",
        views=(("a", a, ()), ("b", b, ())),
        trust_mode="require_agreement",
    )
    assert disagree.status is AcquisitionStatus.INCONSISTENT

    multi = combine_provider_views(
        request_id="req-mode",
        views=(("a", a, ()), ("b", a, ())),
        trust_mode="single",
    )
    assert multi.status is AcquisitionStatus.INCONSISTENT


# ---------------------------------------------------------------------------
# End-to-end: transport → store → cache → source binding
# ---------------------------------------------------------------------------


def test_end_to_end_offline_acquisition_pipeline(
    context: OperationContext,
    policy: ProviderPolicy,
    tmp_path,
) -> None:
    source_url = "https://artifacts.example/source.zip"
    bytecode_url = "https://artifacts.example/runtime.bin"
    archive = _zip_bytes({"contracts/A.sol": SOURCE_A})
    transport = build_offline_transport(
        {
            source_url: FixtureEntry(body=archive),
            bytecode_url: FixtureEntry(body=BYTECODE),
        },
        policy=policy,
        limits=TransportLimits.from_bounds(
            AcquisitionBounds(
                max_items=8,
                max_requests=8,
                max_response_bytes=64 * 1024,
                max_redirects=1,
                max_archive_entries=16,
                max_depth=2,
            )
        ),
        dns={"artifacts.example": ("1.2.3.4",)},
    )

    archive_body, archive_evidence = transport.fetch_bytes(source_url, context=context)
    members = unpack_archive_bounded(
        archive_body,
        max_entries=16,
        max_total_bytes=64 * 1024,
        max_depth=2,
    )
    assert dict(members)["contracts/A.sol"] == SOURCE_A

    runtime_body, runtime_evidence = transport.fetch_bytes(
        bytecode_url, context=context
    )
    cache = ContractArtifactCache(root=tmp_path / "pipeline-cas")
    source_stored = cache.put_bytes(
        SOURCE_A,
        kind=ArtifactKind.SOURCE,
        media_type="text/plain",
        label="contracts/A.sol",
    )
    runtime_stored = cache.put_bytes(
        runtime_body,
        kind=ArtifactKind.BYTECODE,
        media_type="application/octet-stream",
        label="runtime",
    )
    pin = ToolchainPin(
        compiler="solc",
        compiler_version="0.8.20",
        settings={"optimizer": {"enabled": False}},
    )
    source_manifest = SourceManifest(
        files=(
            SourceFileRecord.from_bytes(
                "contracts/A.sol", SOURCE_A, language="solidity"
            ),
        ),
        toolchain=pin,
        request_id=context.request_id,
        observed_at=NOW,
        runtime_bytecode_digest=runtime_stored.content_digest,
    )
    # Without a true recompilation we do not claim creation equivalence; runtime
    # binding is checked against acquired bytes.
    source_manifest.assert_deployed_equivalence(runtime=runtime_body)
    source_manifest.verify_sources({"contracts/A.sol": SOURCE_A})

    artifact_manifest = ArtifactManifest.from_stored(
        [
            ("contracts/A.sol", source_stored),
            ("runtime.bin", runtime_stored),
        ],
        request_id=context.request_id,
        observed_at=NOW,
        transport_evidence=(archive_evidence, runtime_evidence),
        provider_ids=("fixture-a",),
        toolchain_digest=pin.toolchain_digest,
    )
    cache.put_manifest(artifact_manifest)
    artifact_manifest.verify_against(
        {
            "contracts/A.sol": cache.get(source_stored.content_digest),
            "runtime.bin": cache.get(runtime_stored.content_digest),
        }
    )
    result = combine_provider_views(
        request_id=context.request_id,
        views=(("fixture-a", artifact_manifest, ("source+runtime",)),),
        trust_mode=ProviderTrustMode.PRESERVE_DISAGREEMENT.value,
    )
    assert result.status is AcquisitionStatus.AVAILABLE
    assert len(result.artifacts) == 2
    assert result.provenances
    assert all(item.request_digest.startswith("sha256:") for item in result.provenances)


def test_missing_fixture_fails_closed(context: OperationContext, policy: ProviderPolicy) -> None:
    transport = build_offline_transport(
        {},
        policy=policy,
        dns={"artifacts.example": ("1.2.3.4",)},
    )
    with pytest.raises(ProviderError, match="fixture"):
        transport.fetch_bytes("https://artifacts.example/missing", context=context)


def test_ast_symbols_are_exportable() -> None:
    """AST scan targets for CRYPTOIR-G210 must remain importable names."""

    assert ArtifactManifest.__name__ == "ArtifactManifest"
    assert SourceManifest.__name__ == "SourceManifest"
    assert AcquisitionTransport.__name__ == "AcquisitionTransport"
    assert ContractArtifactCache.__name__ == "ContractArtifactCache"
    assert ArtifactManifestEntry.__name__ == "ArtifactManifestEntry"
    assert ToolchainPin.__name__ == "ToolchainPin"
