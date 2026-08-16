"""Security suite for Open US Law Dataset/Bucket resolution (OUL-033).

Acceptance
----------
* Mutable pointers, traversal, prefix escape, digest drift, and cache
  poisoning fail closed before bytes are trusted.
* Fetch traces, errors, and public surfaces never leak credentials or
  absolute local paths.
* Bucket queries cannot read raw-root objects or ``LATEST.json``.
* Unauthorized Dataset/Bucket identities are refused before transport use.

Malicious fixtures stay confined to local fake transports.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_resolver import (
    AUTHORIZED_BUCKET_ID,
    AUTHORIZED_DATASET_REPO_ID,
    DEFAULT_MANIFEST_NAME,
    BucketPrefixError,
    CacheCollisionError,
    CredentialLeakageError,
    DescriptorRequiredError,
    DigestDriftError,
    MappingTransport,
    MutablePointerError,
    OpenUsLawResolver,
    OpenUsLawResolverError,
    PrefixConfinedTransport,
    ResolverLimits,
    RouteJustification,
    SymlinkRejectedError,
    UnauthorizedTargetError,
    UnsafePathError,
    prefix_bucket_files,
    reject_mutable_pointer,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    RELEASE_PROFILE,
    digest_mapping,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ArtifactDescriptor,
    OversizedArtifactError,
    TransportError,
    build_descriptor_for_bytes,
)


PINNED_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
FAKE_TOKEN = "hf_thisIsAFakeTokenValueForLeakTests033"
OPERATOR_HOME = "/home/operator/secrets/open-us-law.token"
CORPUS_PATH = "data/corpus/part-000000.parquet"
SECRET_MARKERS = (
    FAKE_TOKEN,
    OPERATOR_HOME,
    "file:///tmp/open-us-law-private",
    "sk-live-",
    "Bearer ",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _assert_no_secret_leak(surface: object) -> None:
    if isinstance(surface, (bytes, bytearray)):
        blob = surface.decode("utf-8", errors="replace")
    elif isinstance(surface, str):
        blob = surface
    else:
        blob = json.dumps(surface, default=str, sort_keys=True)
    for marker in SECRET_MARKERS:
        assert marker not in blob, f"secret/local marker leaked: {marker!r}"
    assert "/home/operator/" not in blob
    assert "file:///" not in blob
    assert re.search(r"(?i)authorization\s*[:=]", blob) is None


def _sealed_manifest(
    *,
    artifacts: list[dict[str, object]] | None = None,
    **extra: object,
) -> tuple[dict[str, object], bytes, str]:
    body: dict[str, object] = {
        "artifacts": list(artifacts or []),
        "primary_key": "entry_cid",
        "release_profile": RELEASE_PROFILE,
        "schema_version": RELEASE_PROFILE,
    }
    body.update(extra)
    digest = digest_mapping(body)
    body["manifest_digest"] = digest
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return body, raw, digest


def _dataset(
    tmp_path: Path,
    files: dict[str, bytes],
    *,
    fail_paths: dict[str, str] | None = None,
    token: str | None = None,
    limits: ResolverLimits | None = None,
) -> OpenUsLawResolver:
    return OpenUsLawResolver.for_dataset(
        PINNED_REVISION,
        artifact_transport=MappingTransport(files, fail_paths=fail_paths),
        cache_dir=tmp_path / "cache",
        token=token,
        limits=limits,
    )


def _bucket(
    tmp_path: Path,
    files: dict[str, bytes],
    digest: str,
    *,
    fail_paths: dict[str, str] | None = None,
    token: str | None = None,
) -> OpenUsLawResolver:
    prefixed = prefix_bucket_files(digest, files)
    fail_prefixed = (
        prefix_bucket_files(digest, {key: b"" for key in fail_paths})  # type: ignore[misc]
        if fail_paths
        else None
    )
    mapped_fail = None
    if fail_paths is not None:
        mapped_fail = {
            f"releases/{digest}/{key}" if not key.startswith("releases/") else key: reason
            for key, reason in fail_paths.items()
        }
        del fail_prefixed
    return OpenUsLawResolver.for_bucket(
        digest,
        artifact_transport=MappingTransport(prefixed, fail_paths=mapped_fail),
        cache_dir=tmp_path / "cache",
        token=token,
    )


def _corpus_route(path: str = CORPUS_PATH) -> RouteJustification:
    return RouteJustification(family="corpus", reason="hydrate_hit", relative_path=path)


# ---------------------------------------------------------------------------
# Mutable pointer / identity attacks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pin",
    [
        "main",
        "latest",
        "HEAD",
        "master",
        "refs/heads/main",
        "LATEST.json",
        "releases/latest/",
        "https://huggingface.co/datasets/justicedao/open-us-law-sparse-graphrag/resolve/main/manifest.json",
    ],
)
def test_mutable_dataset_pins_never_construct(pin: str, tmp_path: Path) -> None:
    with pytest.raises(MutablePointerError):
        reject_mutable_pointer(pin)
    with pytest.raises(MutablePointerError):
        OpenUsLawResolver.for_dataset(
            pin,
            artifact_transport=MappingTransport({}),
            cache_dir=tmp_path / pin.replace("/", "_"),
        )


@pytest.mark.parametrize(
    "prefix",
    [
        "LATEST.json",
        "latest",
        "releases/latest/",
        "releases/latest/manifest.json",
        "releases/main/manifest.json",
        "../releases/ab" + "cd" * 31 + "/",
    ],
)
def test_mutable_or_escaped_bucket_pins_never_construct(prefix: str, tmp_path: Path) -> None:
    with pytest.raises((MutablePointerError, BucketPrefixError, UnsafePathError, OpenUsLawResolverError)):
        OpenUsLawResolver.for_bucket(
            bucket_prefix=prefix,
            artifact_transport=MappingTransport({}),
            cache_dir=tmp_path / "cache",
        )


def test_unauthorized_repo_and_bucket_fail_before_transport(tmp_path: Path) -> None:
    class _Boom:
        def fetch(self, **kwargs: object) -> Path:
            raise AssertionError("transport must not run for unauthorized targets")

    with pytest.raises(UnauthorizedTargetError):
        OpenUsLawResolver(
            transport="dataset",
            revision=PINNED_REVISION,
            dataset_repo_id="evil/exfil",
            artifact_transport=_Boom(),  # type: ignore[arg-type]
            cache_dir=tmp_path / "cache",
        )
    with pytest.raises(UnauthorizedTargetError):
        OpenUsLawResolver(
            transport="bucket",
            manifest_sha256="ab" * 32,
            bucket_id="evil/bucket",
            artifact_transport=_Boom(),  # type: ignore[arg-type]
            cache_dir=tmp_path / "cache",
        )


# ---------------------------------------------------------------------------
# Traversal, prefix escape, raw root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative_path",
    [
        "../secrets/token",
        "../../etc/passwd",
        "/etc/passwd",
        "~/.ssh/id_rsa",
        "data/../../../LATEST.json",
        "data\\..\\secret",
        "//server/share/file",
    ],
)
def test_traversal_paths_fail_closed(relative_path: str, tmp_path: Path) -> None:
    _body, manifest, _digest = _sealed_manifest()
    resolver = _dataset(tmp_path, {DEFAULT_MANIFEST_NAME: manifest})
    with pytest.raises((UnsafePathError, MutablePointerError, OpenUsLawResolverError)):
        resolver.resolve(
            relative_path,
            route={
                "family": "corpus",
                "reason": "hydrate_hit",
                "relative_path": relative_path,
            },
        )


def test_bucket_prefix_confinement_rejects_raw_root_and_pointer(tmp_path: Path) -> None:
    _body, manifest, digest = _sealed_manifest()
    inner = MappingTransport(
        {
            **prefix_bucket_files(digest, {DEFAULT_MANIFEST_NAME: manifest}),
            "LATEST.json": b'{"manifest_sha256":"tamper"}',
            "raw-root.parquet": b"legacy-raw",
        }
    )
    confined = PrefixConfinedTransport(inner, prefix=f"releases/{digest}/")
    with pytest.raises((MutablePointerError, UnsafePathError)):
        confined.remote_path("LATEST.json")
    with pytest.raises((UnsafePathError, MutablePointerError)):
        confined.remote_path("raw-root.parquet")
    foreign = f"releases/{'00' * 32}/manifest.json"
    with pytest.raises(BucketPrefixError):
        confined.remote_path(foreign)
    assert confined.remote_path(DEFAULT_MANIFEST_NAME) == f"releases/{digest}/manifest.json"


def test_bucket_resolver_refuses_latest_pointer_fetch(tmp_path: Path) -> None:
    _body, manifest, digest = _sealed_manifest()
    resolver = _bucket(tmp_path, {DEFAULT_MANIFEST_NAME: manifest}, digest)
    with pytest.raises(MutablePointerError):
        resolver.resolve(
            "LATEST.json",
            route={"family": "control_plane", "reason": "manifest", "relative_path": "LATEST.json"},
        )


# ---------------------------------------------------------------------------
# Drift, symlink, oversized, cache poisoning
# ---------------------------------------------------------------------------


def test_size_and_digest_drift_fail_closed(tmp_path: Path) -> None:
    honest = b"PAR1-honest-corpus"
    forged = b"PAR1-forged-corpus-bytes"
    artifacts = [
        build_descriptor_for_bytes(CORPUS_PATH, honest, row_count=1).to_dict()
    ]
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset(
        tmp_path, {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: forged}
    )
    resolver.load_manifest()
    with pytest.raises(DigestDriftError):
        resolver.resolve(CORPUS_PATH, route=_corpus_route())


def test_symlink_transport_fails_closed(tmp_path: Path) -> None:
    honest = b"PAR1-honest-corpus"
    artifacts = [
        build_descriptor_for_bytes(CORPUS_PATH, honest, row_count=1).to_dict()
    ]
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest},
        fail_paths={CORPUS_PATH: "symlink"},
    )
    resolver.load_manifest()
    with pytest.raises(SymlinkRejectedError):
        resolver.resolve(CORPUS_PATH, route=_corpus_route())


def test_oversized_descriptor_fails_closed_before_fetch(tmp_path: Path) -> None:
    payload = b"x" * 64
    artifacts = [
        build_descriptor_for_bytes(CORPUS_PATH, payload, row_count=1).to_dict()
    ]
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: payload},
        limits=ResolverLimits(max_artifact_bytes=16, max_bytes=1024, max_shards=8),
    )
    with pytest.raises(OversizedArtifactError):
        resolver.load_manifest()


def test_cache_alias_collision_fails_closed(tmp_path: Path) -> None:
    first = b"PAR1-first-payload"
    second = b"PAR1-second-payload-different"
    artifacts = [
        build_descriptor_for_bytes(CORPUS_PATH, first, row_count=1).to_dict()
    ]
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset(
        tmp_path, {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: first}
    )
    resolver.load_manifest()
    resolver.resolve(CORPUS_PATH, route=_corpus_route())

    # Plant a colliding alias that points at different content.
    alias = resolver._cache.alias_path(identity=resolver.identity, relative_path=CORPUS_PATH)
    planted = json.loads(alias.read_text(encoding="utf-8"))
    planted["sha256"] = _sha(second)
    alias.write_text(json.dumps(planted), encoding="utf-8")
    with pytest.raises(CacheCollisionError):
        resolver.resolve(CORPUS_PATH, route=_corpus_route())


def test_bucket_missing_descriptor_cannot_skip_verification(tmp_path: Path) -> None:
    payload = b"PAR1-unlisted-shard"
    _body, manifest, digest = _sealed_manifest()
    resolver = _bucket(
        tmp_path,
        {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: payload},
        digest,
    )
    resolver.load_manifest()
    with pytest.raises(DescriptorRequiredError):
        resolver.resolve(CORPUS_PATH, route=_corpus_route())


def test_bucket_manifest_field_swap_fails_closed(tmp_path: Path) -> None:
    _body, manifest, digest = _sealed_manifest()
    tampered = json.loads(manifest.decode("utf-8"))
    tampered["manifest_digest"] = "00" * 32
    raw = json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    resolver = _bucket(tmp_path, {DEFAULT_MANIFEST_NAME: raw}, digest)
    with pytest.raises(DigestDriftError, match="manifest_digest"):
        resolver.load_manifest()


# ---------------------------------------------------------------------------
# Credential / path redaction
# ---------------------------------------------------------------------------


def test_fetch_trace_and_repr_never_leak_token_or_absolute_paths(tmp_path: Path) -> None:
    _body, manifest, _digest = _sealed_manifest()
    resolver = _dataset(
        tmp_path, {DEFAULT_MANIFEST_NAME: manifest}, token=FAKE_TOKEN
    )
    resolver.load_manifest()
    trace = resolver.fetch_trace()
    _assert_no_secret_leak(trace)
    _assert_no_secret_leak(repr(resolver))
    rendered = json.dumps(trace)
    assert FAKE_TOKEN not in rendered
    assert str(tmp_path) not in rendered
    assert "token" not in rendered
    assert AUTHORIZED_DATASET_REPO_ID in rendered


def test_route_metadata_rejects_credential_fields(tmp_path: Path) -> None:
    _body, manifest, _digest = _sealed_manifest()
    resolver = _dataset(tmp_path, {DEFAULT_MANIFEST_NAME: manifest})
    with pytest.raises(CredentialLeakageError):
        resolver.resolve(
            DEFAULT_MANIFEST_NAME,
            route=RouteJustification(
                family="control_plane",
                reason="manifest",
                relative_path=DEFAULT_MANIFEST_NAME,
                metadata={"hf_token": FAKE_TOKEN},
            ),
        )


def test_transport_error_redacts_token_like_text(tmp_path: Path) -> None:
    class _Leaky:
        def fetch(self, **kwargs: object) -> Path:
            raise RuntimeError(f"upstream denied Authorization: Bearer {FAKE_TOKEN}")

    _body, manifest, digest = _sealed_manifest()
    resolver = OpenUsLawResolver.for_bucket(
        digest,
        artifact_transport=_Leaky(),  # type: ignore[arg-type]
        cache_dir=tmp_path / "cache",
        token=FAKE_TOKEN,
    )
    with pytest.raises((OpenUsLawResolverError, TransportError)) as excinfo:
        resolver.load_manifest()
    _assert_no_secret_leak(str(excinfo.value))
    assert FAKE_TOKEN not in str(excinfo.value)


def test_publication_gate_surfaces_are_secret_free(tmp_path: Path) -> None:
    _body, manifest, digest = _sealed_manifest()
    resolver = _bucket(
        tmp_path, {DEFAULT_MANIFEST_NAME: manifest}, digest, token=FAKE_TOKEN
    )
    resolver.load_manifest()
    trace = resolver.fetch_trace()
    _assert_no_secret_leak(trace)
    assert trace["publication_gate"]["network_mutation_permitted"] is False
    assert trace["bucket_id"] == AUTHORIZED_BUCKET_ID
    assert "HF_TOKEN" not in json.dumps(trace)


def test_descriptor_path_mismatch_is_not_confused_with_success(tmp_path: Path) -> None:
    payload = b"PAR1-corpus"
    artifacts = [
        build_descriptor_for_bytes(CORPUS_PATH, payload, row_count=1).to_dict()
    ]
    _body, manifest, _digest = _sealed_manifest(artifacts=artifacts)
    resolver = _dataset(
        tmp_path, {DEFAULT_MANIFEST_NAME: manifest, CORPUS_PATH: payload}
    )
    resolver.load_manifest()
    wrong = ArtifactDescriptor.from_mapping(
        {**artifacts[0], "relative_path": "data/corpus/other.parquet"}
    )
    with pytest.raises(UnsafePathError):
        resolver.resolve(CORPUS_PATH, route=_corpus_route(), descriptor=wrong)
