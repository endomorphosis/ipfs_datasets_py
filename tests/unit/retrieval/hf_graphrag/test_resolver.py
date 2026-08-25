"""Unit tests for the hardened immutable Hugging Face GraphRAG resolver (USCIR-010).

Acceptance: mutable revisions, traversal paths, symlinks, digest drift,
oversized artifacts, schema mismatch, cache collision, and credential leakage
fail closed. Tests use a fake Hub transport only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    DEFAULT_MAX_ROWS_PER_ARTIFACT,
    DEFAULT_SUPPORTED_RELEASE_SCHEMAS,
    ArtifactDescriptor,
    CacheCollisionError,
    CredentialLeakageError,
    DigestDriftError,
    ImmutableHubResolver,
    MappingTransport,
    MutableRevisionError,
    OversizedArtifactError,
    ResolverError,
    SchemaMismatchError,
    SymlinkRejectedError,
    UnsafePathError,
    build_descriptor_for_bytes,
    load_malicious_manifest_cases,
    normalize_sha256,
    raw_sha256_cid,
    safe_relative_path,
    validate_immutable_revision,
    validate_repo_id,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "hf_graphrag"
    / "malicious_manifests.json"
)

PINNED_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
REPO_ID = "justicedao/ipfs_uscode"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolver(
    tmp_path: Path,
    *,
    files: dict[str, bytes] | None = None,
    fail_paths: dict[str, str] | None = None,
    revision: str = PINNED_REVISION,
    token: str | None = None,
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
    max_rows_per_artifact: int = DEFAULT_MAX_ROWS_PER_ARTIFACT,
    require_descriptor: bool = False,
) -> ImmutableHubResolver:
    transport = MappingTransport(files or {}, fail_paths=fail_paths)
    return ImmutableHubResolver(
        repo_id=REPO_ID,
        revision=revision,
        cache_dir=tmp_path / "cache",
        transport=transport,
        token=token,
        max_artifact_bytes=max_artifact_bytes,
        max_rows_per_artifact=max_rows_per_artifact,
        require_descriptor=require_descriptor,
    )


def _good_manifest_bytes() -> bytes:
    return json.dumps(
        {
            "primary_key": "entry_cid",
            "schema_version": "publicus-ir-graphrag/v2",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_malicious_manifests_fixture_covers_all_fail_closed_categories() -> None:
    assert FIXTURE_PATH.is_file()
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "hf-graphrag-malicious-manifests/v1"
    required = {
        "mutable_revision",
        "traversal_path",
        "symlink",
        "digest_drift",
        "oversized_artifact",
        "schema_mismatch",
        "cache_collision",
        "credential_leakage",
    }
    assert set(payload["categories"]) == required
    cases = load_malicious_manifest_cases(FIXTURE_PATH)
    seen = {case["category"] for case in cases}
    assert required <= seen
    assert len(cases) >= len(required)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_resolve_verifies_descriptor_and_records_safe_fetch_trace(
    tmp_path: Path,
) -> None:
    content = _good_manifest_bytes()
    descriptor = build_descriptor_for_bytes(
        "manifest.json",
        content,
        schema_id="publicus-ir-graphrag/v2",
    )
    resolver = _resolver(tmp_path, files={"manifest.json": content})

    artifact = resolver.resolve("manifest.json", descriptor=descriptor)
    assert artifact.cache_hit is False
    assert artifact.verified is True
    assert artifact.sha256 == descriptor.sha256
    assert artifact.size_bytes == len(content)
    assert artifact.path.is_file()
    assert not artifact.path.is_symlink()

    # Second resolve is a revision-scoped cache hit.
    again = resolver.resolve("manifest.json", descriptor=descriptor)
    assert again.cache_hit is True
    assert again.sha256 == descriptor.sha256

    manifest = resolver.load_manifest(descriptor=descriptor)
    assert manifest["schema_version"] == "publicus-ir-graphrag/v2"

    trace = resolver.fetch_trace()
    assert trace["repo_id"] == REPO_ID
    assert trace["revision"] == PINNED_REVISION
    assert trace["file_count"] >= 2
    assert trace["cache_hits"] >= 1
    assert trace["verification_state"] == "verified"
    assert all(item["verified"] for item in trace["files"])
    rendered = json.dumps(trace)
    assert "\"token\"" not in rendered
    assert "authorization" not in rendered.lower()
    # Absolute cache paths must not appear in the public trace.
    assert str(tmp_path) not in rendered


def test_build_descriptor_includes_matching_cid() -> None:
    content = b"hello-graphrag"
    descriptor = build_descriptor_for_bytes("data/corpus/part-000000.parquet", content)
    assert descriptor.cid == raw_sha256_cid(bytes.fromhex(descriptor.sha256))
    assert descriptor.size_bytes == len(content)


# ---------------------------------------------------------------------------
# Mutable revisions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "revision",
    [
        "main",
        "latest",
        "HEAD",
        "master",
        "refs/heads/main",
        "75cfc5982dc3a6808614",
        "https://huggingface.co/datasets/x/y/resolve/main/manifest.json",
    ],
)
def test_mutable_revisions_fail_closed(revision: str, tmp_path: Path) -> None:
    with pytest.raises(MutableRevisionError, match="immutable"):
        _resolver(tmp_path, revision=revision)


def test_validate_immutable_revision_accepts_40_hex() -> None:
    assert validate_immutable_revision(PINNED_REVISION) == PINNED_REVISION
    assert (
        validate_immutable_revision(PINNED_REVISION.upper()) == PINNED_REVISION
    )


# ---------------------------------------------------------------------------
# Traversal paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "relative_path",
    [
        "../secrets/token",
        "/etc/passwd",
        "~/.ssh/id_rsa",
        "data\\..\\secret",
        "data/./corpus.parquet",
        "//server/share/file",
        "data//double",
        "",
        "foo/../../etc/passwd",
    ],
)
def test_traversal_paths_fail_closed(relative_path: str) -> None:
    with pytest.raises((UnsafePathError, ResolverError)):
        safe_relative_path(relative_path)


def test_resolver_rejects_traversal_on_resolve(tmp_path: Path) -> None:
    resolver = _resolver(tmp_path, files={})
    with pytest.raises(UnsafePathError):
        resolver.resolve("../escape.parquet")


# ---------------------------------------------------------------------------
# Symlinks
# ---------------------------------------------------------------------------


def test_symlink_transport_failure_fails_closed(tmp_path: Path) -> None:
    resolver = _resolver(
        tmp_path,
        files={},
        fail_paths={"data/corpus/part-000000.parquet": "symlink"},
    )
    with pytest.raises(SymlinkRejectedError, match="symlink"):
        resolver.resolve("data/corpus/part-000000.parquet")


def test_verify_descriptor_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "real.bin"
    target.write_bytes(b"payload")
    link = tmp_path / "link.bin"
    link.symlink_to(target)
    descriptor = build_descriptor_for_bytes("link.bin", b"payload")
    resolver = _resolver(tmp_path, files={})
    with pytest.raises(SymlinkRejectedError):
        resolver.verify_descriptor(link, descriptor)


# ---------------------------------------------------------------------------
# Digest drift
# ---------------------------------------------------------------------------


def test_digest_drift_fails_closed(tmp_path: Path) -> None:
    content = b"actual-bytes"
    bad = ArtifactDescriptor(
        relative_path="manifest.json",
        size_bytes=len(content),
        sha256="a" * 64,
    )
    resolver = _resolver(tmp_path, files={"manifest.json": content})
    with pytest.raises(DigestDriftError, match="digest|size"):
        resolver.resolve("manifest.json", descriptor=bad)


def test_size_mismatch_fails_closed(tmp_path: Path) -> None:
    content = b"PAR1"
    bad = ArtifactDescriptor(
        relative_path="indexes/corpus_chunks.parquet",
        size_bytes=999,
        sha256=_sha(content),
    )
    resolver = _resolver(
        tmp_path, files={"indexes/corpus_chunks.parquet": content}
    )
    with pytest.raises(DigestDriftError):
        resolver.resolve("indexes/corpus_chunks.parquet", descriptor=bad)


def test_cid_mismatch_fails_closed(tmp_path: Path) -> None:
    content = b"cid-check"
    digest = _sha(content)
    wrong_cid = raw_sha256_cid(bytes.fromhex("11" * 32))
    with pytest.raises(DigestDriftError):
        ArtifactDescriptor(
            relative_path="data/x.parquet",
            size_bytes=len(content),
            sha256=digest,
            cid=wrong_cid,
        )


# ---------------------------------------------------------------------------
# Oversized artifacts
# ---------------------------------------------------------------------------


def test_oversized_descriptor_rejected_before_fetch(tmp_path: Path) -> None:
    descriptor = ArtifactDescriptor(
        relative_path="data/vectors/part-000000.parquet",
        size_bytes=2048,
        sha256="b" * 64,
        row_count=1,
    )
    resolver = _resolver(
        tmp_path,
        files={"data/vectors/part-000000.parquet": b"x" * 10},
        max_artifact_bytes=1024,
    )
    with pytest.raises(OversizedArtifactError, match="max_artifact_bytes"):
        resolver.resolve(
            "data/vectors/part-000000.parquet", descriptor=descriptor
        )


def test_oversized_row_count_fails_closed(tmp_path: Path) -> None:
    descriptor = ArtifactDescriptor(
        relative_path="data/corpus/part-000001.parquet",
        size_bytes=16,
        sha256="c" * 64,
        row_count=4097,
    )
    resolver = _resolver(tmp_path, files={}, max_rows_per_artifact=4096)
    with pytest.raises(OversizedArtifactError, match="row_count"):
        resolver.resolve(
            "data/corpus/part-000001.parquet", descriptor=descriptor
        )


def test_fetched_bytes_exceeding_budget_fail_closed(tmp_path: Path) -> None:
    content = b"x" * 100
    resolver = _resolver(
        tmp_path,
        files={"data/big.bin": content},
        max_artifact_bytes=50,
    )
    with pytest.raises(OversizedArtifactError):
        resolver.resolve("data/big.bin")


# ---------------------------------------------------------------------------
# Schema mismatch
# ---------------------------------------------------------------------------


def test_unknown_manifest_schema_fails_closed(tmp_path: Path) -> None:
    content = json.dumps(
        {"schema_version": "evil-release/v0", "primary_key": "entry_cid"}
    ).encode("utf-8")
    resolver = _resolver(tmp_path, files={"manifest.json": content})
    with pytest.raises(SchemaMismatchError, match="unsupported release schema"):
        resolver.load_manifest()


def test_missing_manifest_schema_fails_closed(tmp_path: Path) -> None:
    content = json.dumps({"primary_key": "entry_cid"}).encode("utf-8")
    resolver = _resolver(tmp_path, files={"manifest.json": content})
    with pytest.raises(SchemaMismatchError, match="schema_version"):
        resolver.load_manifest()


def test_wrong_primary_key_fails_closed(tmp_path: Path) -> None:
    content = json.dumps(
        {
            "schema_version": "publicus-ir-graphrag/v2",
            "primary_key": "row-N",
        }
    ).encode("utf-8")
    resolver = _resolver(tmp_path, files={"manifest.json": content})
    with pytest.raises(SchemaMismatchError, match="primary_key"):
        resolver.load_manifest()


def test_descriptor_missing_digest_fails_closed() -> None:
    with pytest.raises(DigestDriftError):
        ArtifactDescriptor(
            relative_path="data/bm25/postings/part-000000.parquet",
            size_bytes=32,
            sha256="",
        )


def test_supported_schemas_constant_includes_v2_profile() -> None:
    assert "publicus-ir-graphrag/v2" in DEFAULT_SUPPORTED_RELEASE_SCHEMAS


# ---------------------------------------------------------------------------
# Cache collision
# ---------------------------------------------------------------------------


def test_cache_collision_on_alias_digest_mismatch(tmp_path: Path) -> None:
    path = "indexes/bm25_keyword_shards.parquet"
    content_a = b"alpha-bytes-for-shard-a"
    content_b = b"beta-bytes-for-shard-b-different"
    desc_a = build_descriptor_for_bytes(path, content_a)
    desc_b = build_descriptor_for_bytes(path, content_b)

    resolver_a = _resolver(tmp_path, files={path: content_a})
    first = resolver_a.resolve(path, descriptor=desc_a)
    assert first.cache_hit is False

    # Same cache root + revision + path, different content/descriptor.
    resolver_b = _resolver(tmp_path, files={path: content_b})
    with pytest.raises(CacheCollisionError, match="collision|alias"):
        resolver_b.resolve(path, descriptor=desc_b)


def test_cache_hit_replays_identical_bytes(tmp_path: Path) -> None:
    path = "indexes/vector_chunks.parquet"
    content = b"stable-vector-index"
    descriptor = build_descriptor_for_bytes(path, content)
    resolver = _resolver(tmp_path, files={path: content})
    first = resolver.resolve(path, descriptor=descriptor)
    second = resolver.resolve(path, descriptor=descriptor)
    assert second.cache_hit is True
    assert first.path.read_bytes() == second.path.read_bytes() == content


# ---------------------------------------------------------------------------
# Credential leakage
# ---------------------------------------------------------------------------


def test_credentials_never_appear_in_trace_or_repr(tmp_path: Path) -> None:
    token = "hf_thisIsAFakeTokenValueForLeakTests001"
    content = _good_manifest_bytes()
    descriptor = build_descriptor_for_bytes("manifest.json", content)
    resolver = _resolver(
        tmp_path,
        files={"manifest.json": content},
        token=token,
    )
    resolver.resolve("manifest.json", descriptor=descriptor)
    resolver.load_manifest(descriptor=descriptor)

    trace = resolver.fetch_trace()
    rendered_trace = json.dumps(trace, sort_keys=True)
    rendered_repr = repr(resolver)
    assert token not in rendered_trace
    assert token not in rendered_repr
    assert "hf_" not in rendered_trace
    assert "\"token\"" not in rendered_trace
    # Public attribute is cleared; private storage only.
    assert resolver.token is None
    assert "token=" not in rendered_repr


def test_fetch_trace_rejects_credential_fields(tmp_path: Path) -> None:
    from ipfs_datasets_py.retrieval.hf_graphrag.resolver import _FetchRecord

    resolver = _resolver(tmp_path, files={})
    # Poison the internal log with a token-like schema_id; public surface fails closed.
    resolver._fetch_log.append(
        _FetchRecord(
            relative_path="manifest.json",
            size_bytes=1,
            sha256="d" * 64,
            cache_hit=False,
            verified=True,
            duration_ms=0.0,
            schema_id="hf_thisIsAFakeTokenValueForLeakTests001",
        )
    )
    with pytest.raises(CredentialLeakageError):
        resolver.fetch_trace()


# ---------------------------------------------------------------------------
# Drive malicious fixture end-to-end
# ---------------------------------------------------------------------------


def test_malicious_fixture_cases_fail_closed(tmp_path: Path) -> None:
    cases = load_malicious_manifest_cases(FIXTURE_PATH)
    error_types = {
        "MutableRevisionError": MutableRevisionError,
        "UnsafePathError": UnsafePathError,
        "SymlinkRejectedError": SymlinkRejectedError,
        "DigestDriftError": DigestDriftError,
        "OversizedArtifactError": OversizedArtifactError,
        "SchemaMismatchError": SchemaMismatchError,
        "CacheCollisionError": CacheCollisionError,
        "CredentialLeakageError": CredentialLeakageError,
    }

    for case in cases:
        category = case["category"]
        case_id = case["id"]
        expect = case.get("expect_error")
        match = case.get("match")

        if category == "mutable_revision":
            with pytest.raises(error_types[expect], match=match):
                validate_immutable_revision(case["revision"])
            continue

        if category == "traversal_path":
            with pytest.raises((UnsafePathError, ResolverError), match=match):
                safe_relative_path(case["relative_path"])
            continue

        if category == "symlink":
            resolver = _resolver(
                tmp_path / case_id,
                fail_paths={case["relative_path"]: case["transport_failure"]},
            )
            with pytest.raises(error_types[expect], match=match):
                resolver.resolve(case["relative_path"])
            continue

        if category == "digest_drift":
            if "content_hex" in case:
                content = bytes.fromhex(case["content_hex"])
            else:
                content = str(case.get("content", "")).encode("utf-8")
            files = {case["relative_path"]: content}
            resolver = _resolver(tmp_path / case_id, files=files)
            with pytest.raises(error_types[expect], match=match):
                resolver.resolve(
                    case["relative_path"], descriptor=case["descriptor"]
                )
            continue

        if category == "oversized_artifact":
            kwargs = {}
            if "max_artifact_bytes" in case:
                kwargs["max_artifact_bytes"] = case["max_artifact_bytes"]
            if "max_rows_per_artifact" in case:
                kwargs["max_rows_per_artifact"] = case["max_rows_per_artifact"]
            resolver = _resolver(tmp_path / case_id, files={}, **kwargs)
            with pytest.raises(error_types[expect], match=match):
                resolver.resolve(
                    case["relative_path"], descriptor=case["descriptor"]
                )
            continue

        if category == "schema_mismatch":
            if case.get("operation") == "load_manifest":
                content = str(case["content"]).encode("utf-8")
                resolver = _resolver(
                    tmp_path / case_id,
                    files={case["relative_path"]: content},
                )
                with pytest.raises(error_types[expect], match=match):
                    resolver.load_manifest(case["relative_path"])
            else:
                with pytest.raises(error_types[expect], match=match):
                    ArtifactDescriptor.from_mapping(case["descriptor"])
            continue

        if category == "cache_collision":
            path = case["relative_path"]
            content_a = str(case["content_a"]).encode("utf-8")
            content_b = str(case["content_b"]).encode("utf-8")
            cache_root = tmp_path / case_id
            desc_a = build_descriptor_for_bytes(path, content_a)
            desc_b = build_descriptor_for_bytes(path, content_b)
            first = _resolver(cache_root, files={path: content_a})
            first.resolve(path, descriptor=desc_a)
            second = _resolver(cache_root, files={path: content_b})
            with pytest.raises(error_types[expect], match=match):
                second.resolve(path, descriptor=desc_b)
            continue

        if category == "credential_leakage":
            token = case["token"]
            content = str(case["content"]).encode("utf-8")
            descriptor = build_descriptor_for_bytes(
                case["relative_path"], content
            )
            resolver = _resolver(
                tmp_path / case_id,
                files={case["relative_path"]: content},
                token=token,
            )
            resolver.resolve(case["relative_path"], descriptor=descriptor)
            trace_text = json.dumps(resolver.fetch_trace())
            repr_text = repr(resolver)
            for absent in case["assert_absent_from_trace"]:
                if absent == "token":
                    # Field name may appear in prose-free traces only as a
                    # key; ensure no credential *value* or token field leaks.
                    assert token not in trace_text
                    assert "\"token\"" not in trace_text
                else:
                    assert absent not in trace_text
                    assert absent not in repr_text
            continue

        raise AssertionError(f"unhandled malicious fixture category: {category}")


# ---------------------------------------------------------------------------
# Misc safety
# ---------------------------------------------------------------------------


def test_repo_id_validation() -> None:
    assert validate_repo_id(REPO_ID) == REPO_ID
    with pytest.raises(ResolverError):
        validate_repo_id("not a repo")
    with pytest.raises(UnsafePathError):
        validate_repo_id("../evil/name")


def test_normalize_sha256_prefix() -> None:
    digest = "a" * 64
    assert normalize_sha256(f"sha256:{digest}") == digest
    with pytest.raises(DigestDriftError):
        normalize_sha256("not-a-digest")


def test_require_descriptor_mode(tmp_path: Path) -> None:
    content = b"needs-descriptor"
    resolver = _resolver(
        tmp_path,
        files={"data/x.parquet": content},
        require_descriptor=True,
    )
    with pytest.raises(SchemaMismatchError, match="descriptor is required"):
        resolver.resolve("data/x.parquet")
    descriptor = build_descriptor_for_bytes("data/x.parquet", content)
    resolved = resolver.resolve("data/x.parquet", descriptor=descriptor)
    assert resolved.sha256 == descriptor.sha256


def test_transport_error_does_not_echo_token(tmp_path: Path) -> None:
    token = "hf_secretTransportTokenValue999"
    resolver = _resolver(
        tmp_path,
        files={},
        fail_paths={"missing.json": "error"},
        token=token,
    )
    with pytest.raises(ResolverError) as exc_info:
        resolver.resolve("missing.json")
    assert token not in str(exc_info.value)
