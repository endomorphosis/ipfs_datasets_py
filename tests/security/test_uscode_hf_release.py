"""Security suite for US Code HF release packaging, resources, and cache (USCIR-034).

Acceptance
----------
* Every tamper case fails closed with a typed error **before** unsafe
  parsing or use.
* Fetch traces, errors, and public surfaces never leak secrets or local
  absolute paths.
* Valid packaging fixtures and live dry-run builds remain accepted.

Malicious fixtures stay confined to local fake transports and in-memory
recipes; they are never passed to live Hub mutation surfaces.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.huggingface.release import (
    HuggingFaceReleaseError,
    reject_identity_contamination,
)
from ipfs_datasets_py.processors.legal_data.uscode_hf_release import (
    DEFAULT_CONFIG_NAME,
    LINEAGE_REPORT_PATH,
    MANIFEST_FILENAME,
    QUALITY_REPORT_PATH,
    ReleaseArtifact,
    UscodeHFReleaseBuilder,
    UscodeHFReleaseConfigError,
    UscodeHFReleaseError,
    UscodeHFReleaseIntegrityError,
    UscodeHFReleaseSafetyError,
    UscodeHuggingFaceRelease,
    advertised_viewer_configs,
    assert_configs_schema_coherent,
    build_uscode_hf_release,
    fixture_family_rows,
    fixture_legacy_files,
    load_fixture_dataset_card,
    load_fixture_manifest,
    stage_uscode_hf_release,
    validate_uscode_hf_release,
)
from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    MAX_ROWS_PER_PHYSICAL_SHARD,
    ArtifactPathError,
    MutableReferenceError,
    PhysicalBoundError,
    normalize_relative_artifact_path,
    require_immutable_revision,
    validate_physical_row_count,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ArtifactDescriptor,
    CacheCollisionError,
    CredentialLeakageError,
    DigestDriftError,
    ImmutableHubResolver,
    MappingTransport,
    MutableRevisionError,
    OversizedArtifactError,
    SchemaMismatchError,
    SymlinkRejectedError,
    UnsafePathError,
    build_descriptor_for_bytes,
    safe_relative_path,
    validate_immutable_revision,
)

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "legal_ir"
TAMPER_FIXTURE = FIXTURE_DIR / "uscode_tamper_cases.json"
SECURITY_REPORT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "reports"
    / "uscode_release_security.json"
)
PINNED_REVISION = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
REPO_ID = "justicedao/ipfs_uscode"
JSON_MEDIA = "application/json"

REQUIRED_CATEGORIES = frozenset(
    {
        "traversal_path",
        "absolute_path",
        "symlink",
        "digest_drift",
        "size_drift",
        "row_drift",
        "schema_drift",
        "mutable_revision",
        "decompression_limit",
        "row_limit",
        "cache_poisoning",
        "token_redaction",
        "manifest_lineage_bounds",
    }
)

ERROR_TYPES: dict[str, type[BaseException]] = {
    "ArtifactPathError": ArtifactPathError,
    "CacheCollisionError": CacheCollisionError,
    "CredentialLeakageError": CredentialLeakageError,
    "DigestDriftError": DigestDriftError,
    "HuggingFaceReleaseError": HuggingFaceReleaseError,
    "MutableReferenceError": MutableReferenceError,
    "MutableRevisionError": MutableRevisionError,
    "OversizedArtifactError": OversizedArtifactError,
    "PhysicalBoundError": PhysicalBoundError,
    "SchemaMismatchError": SchemaMismatchError,
    "SymlinkRejectedError": SymlinkRejectedError,
    "UnsafePathError": UnsafePathError,
    "UscodeHFReleaseConfigError": UscodeHFReleaseConfigError,
    "UscodeHFReleaseError": UscodeHFReleaseError,
    "UscodeHFReleaseIntegrityError": UscodeHFReleaseIntegrityError,
    "UscodeHFReleaseSafetyError": UscodeHFReleaseSafetyError,
}

SECRET_MARKERS = (
    "hf_thisIsAFakeTokenValueForLeakTests034",
    "hf_thisIsAFakeTokenValueForLeakTests001",
    "/home/operator/secrets",
    "file:///tmp/uscode-private",
    "sk-live-",
    "Bearer ",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_tamper_fixture() -> dict[str, Any]:
    assert TAMPER_FIXTURE.is_file(), f"missing tamper fixture: {TAMPER_FIXTURE}"
    payload = json.loads(TAMPER_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _cases() -> list[dict[str, Any]]:
    payload = _load_tamper_fixture()
    cases = payload.get("cases")
    assert isinstance(cases, list) and cases
    return [dict(case) for case in cases if isinstance(case, dict)]


def _case_ids() -> list[str]:
    return [str(case["id"]) for case in _cases()]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_valid_release(**kwargs: Any) -> UscodeHuggingFaceRelease:
    return build_uscode_hf_release(
        fixture_family_rows(),
        legacy_files=fixture_legacy_files(),
        dry_run=True,
        **kwargs,
    )


def _resolver(
    tmp_path: Path,
    *,
    files: dict[str, bytes] | None = None,
    fail_paths: dict[str, str] | None = None,
    revision: str = PINNED_REVISION,
    token: str | None = None,
    max_artifact_bytes: int = 64 * 1024 * 1024,
    max_rows_per_artifact: int = MAX_ROWS_PER_PHYSICAL_SHARD,
) -> ImmutableHubResolver:
    return ImmutableHubResolver(
        repo_id=REPO_ID,
        revision=revision,
        cache_dir=tmp_path / "cache",
        transport=MappingTransport(files or {}, fail_paths=fail_paths),
        token=token,
        max_artifact_bytes=max_artifact_bytes,
        max_rows_per_artifact=max_rows_per_artifact,
    )


def _assert_no_secret_leak(surface: Any) -> None:
    if isinstance(surface, (bytes, bytearray)):
        blob = surface.decode("utf-8", errors="replace")
    elif isinstance(surface, str):
        blob = surface
    else:
        blob = json.dumps(surface, default=str, sort_keys=True)
    for marker in SECRET_MARKERS:
        assert marker not in blob, f"secret/local marker leaked: {marker!r}"
    # Absolute operator secret paths and file URIs must not appear.
    assert "/home/operator/" not in blob
    assert "file:///" not in blob
    assert re.search(r"(?i)authorization\s*[:=]", blob) is None


def _stage_release_files(
    release: UscodeHuggingFaceRelease,
) -> dict[str, bytes]:
    return {item.relative_path: item.content for item in release.artifacts}


def _mutate_quality_with_lineage_rows(
    release: UscodeHuggingFaceRelease,
) -> UscodeHuggingFaceRelease:
    """Inject verbose lineage rows into a control-plane quality report."""

    lineage = json.loads(release.artifact(LINEAGE_REPORT_PATH).content.decode("utf-8"))
    quality = json.loads(release.artifact(QUALITY_REPORT_PATH).content.decode("utf-8"))
    quality["rows"] = list(lineage.get("rows") or [])
    tainted: list[ReleaseArtifact] = []
    for art in release.artifacts:
        if art.relative_path == QUALITY_REPORT_PATH:
            body = (json.dumps(quality, sort_keys=True, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
            tainted.append(
                ReleaseArtifact(
                    relative_path=art.relative_path,
                    content=body,
                    media_type=art.media_type,
                    family=art.family,
                    row_count=art.row_count,
                    config_name=art.config_name,
                    schema_id=art.schema_id,
                )
            )
        else:
            tainted.append(art)
    return UscodeHuggingFaceRelease(
        dataset_id=release.dataset_id,
        release_root_cid=release.release_root_cid,
        manifest_digest=release.manifest_digest,
        schema_version=release.schema_version,
        release_profile=release.release_profile,
        source_revision=release.source_revision,
        release_point=release.release_point,
        build_config_cid=release.build_config_cid,
        vector_space_id=release.vector_space_id,
        configs=release.configs,
        artifacts=tuple(tainted),
        dry_run=True,
    )


def _bind_recovery_to_default(
    release: UscodeHuggingFaceRelease,
) -> UscodeHuggingFaceRelease:
    tainted: list[ReleaseArtifact] = []
    for art in release.artifacts:
        if art.relative_path.startswith("recovery/"):
            tainted.append(
                ReleaseArtifact(
                    relative_path=art.relative_path,
                    content=art.content,
                    media_type=art.media_type,
                    family=art.family,
                    row_count=art.row_count,
                    config_name=DEFAULT_CONFIG_NAME,
                    schema_id=art.schema_id,
                    first_key=art.first_key,
                    last_key=art.last_key,
                )
            )
        else:
            tainted.append(art)
    return UscodeHuggingFaceRelease(
        dataset_id=release.dataset_id,
        release_root_cid=release.release_root_cid,
        manifest_digest=release.manifest_digest,
        schema_version=release.schema_version,
        release_profile=release.release_profile,
        source_revision=release.source_revision,
        release_point=release.release_point,
        build_config_cid=release.build_config_cid,
        vector_space_id=release.vector_space_id,
        configs=release.configs,
        artifacts=tuple(tainted),
        dry_run=True,
    )


def _execute_case(case: dict[str, Any], tmp_path: Path) -> None:
    """Drive one tamper recipe against the correct surface."""

    category = case["category"]
    case_id = case["id"]
    expect = case.get("expect_error")
    match = case.get("match")
    operation = case.get("operation")
    error_cls = ERROR_TYPES[expect] if expect else None

    # --- path surfaces (packaging + shared schema) ---
    if category in {"traversal_path", "absolute_path"} and case.get("surface") == "path":
        with pytest.raises(error_cls, match=match):
            normalize_relative_artifact_path(case["relative_path"])
        return

    if category == "traversal_path" and case.get("surface") == "resolver":
        resolver = _resolver(tmp_path / case_id, files={})
        with pytest.raises(error_cls, match=match):
            resolver.resolve(case["relative_path"])
        return

    if category == "absolute_path" and case.get("surface") == "release_config":
        configs = list(advertised_viewer_configs(include_recovery=False))
        bad = configs[0].to_dict()
        bad["data_files"] = [{"split": "train", "path": case["config_path"]}]
        with pytest.raises(error_cls, match=match):
            assert_configs_schema_coherent([bad, *configs[1:]])
        return

    # --- symlink ---
    if category == "symlink":
        if operation == "verify_descriptor_symlink":
            target = tmp_path / case_id / "real.bin"
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = b"payload-bytes"
            target.write_bytes(payload)
            link = tmp_path / case_id / "link.bin"
            link.symlink_to(target)
            descriptor = build_descriptor_for_bytes(case["relative_path"], payload)
            resolver = _resolver(tmp_path / case_id / "cache", files={})
            with pytest.raises(error_cls, match=match):
                resolver.verify_descriptor(link, descriptor)
            return
        resolver = _resolver(
            tmp_path / case_id,
            fail_paths={case["relative_path"]: case["transport_failure"]},
        )
        with pytest.raises(error_cls, match=match):
            resolver.resolve(case["relative_path"])
        return

    # --- digest / size drift ---
    if category in {"digest_drift", "size_drift"}:
        if case.get("surface") == "release_artifact":
            with pytest.raises(error_cls, match=match):
                ReleaseArtifact(
                    relative_path=case["relative_path"],
                    content=str(case["content"]).encode("utf-8"),
                    media_type=JSON_MEDIA,
                    family="report",
                    sha256=case["declared_sha256"],
                )
            return
        if "content_hex" in case:
            content = bytes.fromhex(case["content_hex"])
        else:
            content = str(case.get("content", "")).encode("utf-8")
        resolver = _resolver(
            tmp_path / case_id, files={case["relative_path"]: content}
        )
        with pytest.raises(error_cls, match=match):
            resolver.resolve(case["relative_path"], descriptor=case["descriptor"])
        return

    # --- row drift / limits ---
    if category == "row_drift" and case.get("surface") == "release_artifact":
        with pytest.raises(error_cls, match=match):
            ReleaseArtifact(
                relative_path=case["relative_path"],
                content=str(case["content"]).encode("utf-8"),
                media_type="application/vnd.apache.parquet",
                family=case["family"],
                row_count=int(case["row_count"]),
            )
        return

    if category == "row_drift" and case.get("surface") == "resource":
        with pytest.raises(error_cls, match=match):
            validate_physical_row_count(int(case["row_count"]))
        return

    if category == "row_limit" and "max_rows_per_shard" in case:
        with pytest.raises(error_cls, match=match):
            UscodeHFReleaseBuilder(max_rows_per_shard=int(case["max_rows_per_shard"]))
        return

    if category == "row_limit":
        kwargs: dict[str, Any] = {}
        if "max_rows_per_artifact" in case:
            kwargs["max_rows_per_artifact"] = case["max_rows_per_artifact"]
        resolver = _resolver(tmp_path / case_id, files={}, **kwargs)
        with pytest.raises(error_cls, match=match):
            resolver.resolve(case["relative_path"], descriptor=case["descriptor"])
        return

    # --- schema drift ---
    if category == "schema_drift":
        if operation == "load_manifest":
            content = str(case["content"]).encode("utf-8")
            resolver = _resolver(
                tmp_path / case_id, files={case["relative_path"]: content}
            )
            with pytest.raises(error_cls, match=match):
                resolver.load_manifest(case["relative_path"])
            return
        if operation == "two_defaults":
            configs = advertised_viewer_configs(
                include_legacy=False, include_recovery=False
            )
            twin = configs[0].to_dict()
            twin["config_name"] = "publicus-ir-graphrag/v2-dup"
            with pytest.raises(error_cls, match=match):
                assert_configs_schema_coherent([configs[0], twin])
            return
        if operation == "default_recovery_path":
            configs = list(advertised_viewer_configs(include_recovery=False))
            bad = configs[0].to_dict()
            bad["data_files"] = [{"split": "train", "path": "recovery/**/*.json"}]
            with pytest.raises(error_cls, match=match):
                assert_configs_schema_coherent([bad, *configs[1:]])
            return
        raise AssertionError(f"unhandled schema_drift operation: {operation!r}")

    # --- mutable revision ---
    if category == "mutable_revision":
        if operation == "schema_require":
            with pytest.raises(error_cls, match=match):
                require_immutable_revision(case["revision"])
            return
        if operation == "release_builder":
            with pytest.raises(error_cls, match=match):
                UscodeHFReleaseBuilder(source_revision=case["revision"])
            return
        with pytest.raises(error_cls, match=match):
            validate_immutable_revision(case["revision"])
        return

    # --- decompression / resource bounds ---
    if category == "decompression_limit":
        if "descriptor" in case:
            kwargs = {}
            if "max_artifact_bytes" in case:
                kwargs["max_artifact_bytes"] = case["max_artifact_bytes"]
            resolver = _resolver(tmp_path / case_id, files={}, **kwargs)
            with pytest.raises(error_cls, match=match):
                resolver.resolve(
                    case["relative_path"], descriptor=case["descriptor"]
                )
            return
        content = str(case["content"]).encode("utf-8")
        resolver = _resolver(
            tmp_path / case_id,
            files={case["relative_path"]: content},
            max_artifact_bytes=int(case["max_artifact_bytes"]),
        )
        with pytest.raises(error_cls, match=match):
            resolver.resolve(case["relative_path"])
        return

    # --- cache poisoning ---
    if category == "cache_poisoning":
        path = case["relative_path"]
        content_a = str(case["content_a"]).encode("utf-8")
        content_b = str(case["content_b"]).encode("utf-8")
        cache_root = tmp_path / case_id
        desc_a = build_descriptor_for_bytes(path, content_a)
        desc_b = build_descriptor_for_bytes(path, content_b)
        first = _resolver(cache_root, files={path: content_a})
        first.resolve(path, descriptor=desc_a)
        second = _resolver(cache_root, files={path: content_b})
        with pytest.raises(error_cls, match=match):
            second.resolve(path, descriptor=desc_b)
        return

    # --- token redaction ---
    if category == "token_redaction":
        if operation == "poison_fetch_log":
            from ipfs_datasets_py.retrieval.hf_graphrag.resolver import _FetchRecord

            resolver = _resolver(tmp_path / case_id, files={})
            resolver._fetch_log.append(
                _FetchRecord(
                    relative_path="manifest.json",
                    size_bytes=1,
                    sha256="d" * 64,
                    cache_hit=False,
                    verified=True,
                    duration_ms=0.0,
                    schema_id=case["token_like_schema_id"],
                )
            )
            with pytest.raises(error_cls, match=match):
                resolver.fetch_trace()
            return

        token = case["token"]
        content = str(case["content"]).encode("utf-8")
        descriptor = build_descriptor_for_bytes(case["relative_path"], content)
        resolver = _resolver(
            tmp_path / case_id,
            files={case["relative_path"]: content},
            token=token,
        )
        resolver.resolve(case["relative_path"], descriptor=descriptor)
        trace_text = json.dumps(resolver.fetch_trace(), sort_keys=True)
        repr_text = repr(resolver)
        for absent in case["assert_absent_from_trace"]:
            assert absent not in trace_text
            if absent != "\"token\"":
                assert absent not in repr_text
        assert resolver.token is None
        _assert_no_secret_leak(trace_text)
        _assert_no_secret_leak(repr_text)
        return

    # --- lineage / control-plane bounds ---
    if category == "manifest_lineage_bounds":
        if operation == "control_plane_lineage_rows":
            bad = _mutate_quality_with_lineage_rows(_build_valid_release())
            with pytest.raises(error_cls, match=match):
                validate_uscode_hf_release(bad)
            return
        if operation == "recovery_default_bind":
            bad = _bind_recovery_to_default(_build_valid_release())
            with pytest.raises(error_cls, match=match):
                validate_uscode_hf_release(bad)
            return
        with pytest.raises(error_cls, match=match):
            reject_identity_contamination(case["payload"], label="lineage-tamper")
        return

    raise AssertionError(
        f"unhandled tamper case {case_id!r} category={category!r} surface={case.get('surface')!r}"
    )


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_tamper_fixture_covers_required_categories() -> None:
    payload = _load_tamper_fixture()
    assert payload["schema_version"] == "uscode-tamper-cases/v1"
    assert payload["task_id"] == "USCIR-034"
    assert set(payload["categories"]) == REQUIRED_CATEGORIES
    cases = _cases()
    seen = {case["category"] for case in cases}
    assert REQUIRED_CATEGORIES <= seen
    assert len(cases) >= len(REQUIRED_CATEGORIES)
    for case in cases:
        assert case["id"]
        assert case["category"] in REQUIRED_CATEGORIES
        assert case.get("surface")
        expect = case.get("expect_error")
        if expect is not None:
            assert expect in ERROR_TYPES
        else:
            # Only token-redaction happy-path cases may omit expect_error.
            assert case["category"] == "token_redaction"
            assert case.get("assert_absent_from_trace")


def test_security_report_sealed_and_matches_fixture() -> None:
    assert SECURITY_REPORT.is_file(), f"missing security report: {SECURITY_REPORT}"
    report = json.loads(SECURITY_REPORT.read_text(encoding="utf-8"))
    fixture = _load_tamper_fixture()
    cases = fixture["cases"]

    assert report["task_id"] == "USCIR-034"
    assert report["goal_id"] == "USCIR-G090"
    assert report["schema_version"] == "uscode-release-security/v1"
    assert report["tamper_fixture"] == "tests/fixtures/legal_ir/uscode_tamper_cases.json"
    assert report["case_count"] == len(cases)
    assert set(report["categories"]) == REQUIRED_CATEGORIES

    acc = report["acceptance"]
    assert acc["every_tamper_case_fails_closed"] is True
    assert acc["typed_errors_before_unsafe_parsing_or_use"] is True
    assert acc["no_secret_or_local_absolute_path_leaks"] is True
    assert acc["valid_fixtures_remain_accepted"] is True

    by_category = report["cases_by_category"]
    for category in REQUIRED_CATEGORIES:
        assert by_category[category] >= 1

    # Report itself must not embed secrets or absolute operator paths.
    _assert_no_secret_leak(report)
    rendered = json.dumps(report, sort_keys=True)
    assert "/home/" not in rendered
    assert "file://" not in rendered


# ---------------------------------------------------------------------------
# Drive every tamper case
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_id", _case_ids())
def test_tamper_case_fails_closed(case_id: str, tmp_path: Path) -> None:
    case = next(c for c in _cases() if c["id"] == case_id)
    _execute_case(case, tmp_path)


def test_all_tamper_cases_fail_closed_in_one_pass(tmp_path: Path) -> None:
    """Aggregate driver used by the sealed security report."""

    failures: list[str] = []
    for case in _cases():
        try:
            _execute_case(case, tmp_path / case["id"])
        except Exception as exc:  # noqa: BLE001 - collect all failures
            failures.append(f"{case['id']}: {type(exc).__name__}: {exc}")
    assert not failures, "tamper cases did not all fail closed:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Valid fixtures remain accepted
# ---------------------------------------------------------------------------


def test_valid_fixture_manifest_and_card_remain_accepted() -> None:
    payload = load_fixture_manifest()
    receipt = assert_configs_schema_coherent(payload["configs"])
    assert receipt["schema_coherent"] is True
    assert receipt["default_excludes_recovery"] is True
    acceptance = payload["acceptance"]
    for key, expected in (
        ("default_config_excludes_recovery", True),
        ("all_advertised_configs_schema_coherent", True),
        ("every_artifact_descriptor_bound", True),
        ("verbose_lineage_separate_from_control_plane", True),
        ("legacy_files_not_deleted", True),
    ):
        assert acceptance[key] is expected

    card = load_fixture_dataset_card()
    assert card.startswith("---\n")
    assert DEFAULT_CONFIG_NAME in card
    assert "recovery" in card.lower()
    _assert_no_secret_leak(payload)
    _assert_no_secret_leak(card)


def test_valid_release_build_validates_and_stages(tmp_path: Path) -> None:
    release = _build_valid_release()
    receipt = validate_uscode_hf_release(release)
    assert receipt["valid"] is True
    acc = receipt["acceptance"]
    assert acc["default_config_excludes_recovery"] is True
    assert acc["every_artifact_descriptor_bound"] is True
    assert acc["verbose_lineage_separate_from_control_plane"] is True

    # Lineage is separate and free of absolute local paths.
    lineage = json.loads(release.artifact(LINEAGE_REPORT_PATH).content.decode("utf-8"))
    assert lineage["control_plane"] is False
    assert lineage["separate_from_control_plane"] is True
    rendered_lineage = json.dumps(lineage)
    assert "/home/" not in rendered_lineage
    assert "file://" not in rendered_lineage
    reject_identity_contamination(release.manifest_dict(), label="manifest")
    reject_identity_contamination(
        release.release_metadata_dict(), label="release-metadata"
    )

    staged = stage_uscode_hf_release(
        release,
        tmp_path / "stage",
        dry_run=False,
        preserve_existing=(),
    )
    assert staged.dry_run is False
    assert Path(staged.staged_root).is_dir()
    # Staged root path may be absolute on disk, but public control-plane
    # artifacts must not embed operator home paths or tokens.
    for art in staged.artifacts:
        if art.relative_path.endswith((".json", ".md")):
            _assert_no_secret_leak(art.content)


def test_valid_staged_release_resolves_without_leaks(tmp_path: Path) -> None:
    release = _build_valid_release()
    files = _stage_release_files(release)
    manifest = files[MANIFEST_FILENAME]
    descriptor = build_descriptor_for_bytes(
        MANIFEST_FILENAME,
        manifest,
        schema_id="uscode-sparse-graphrag-release-schema-v2",
    )
    token = "hf_thisIsAFakeTokenValueForLeakTests034"
    resolver = _resolver(
        tmp_path,
        files=files,
        token=token,
        # Release schema versions used by packaging.
        # supported_schemas defaults already include the profile/schema pair.
    )
    # Extend supported schemas for packaging hf_release schema if present.
    object.__setattr__(
        resolver,
        "supported_schemas",
        frozenset(resolver.supported_schemas)
        | {
            "uscode-hf-release/v1",
            "uscode-sparse-graphrag-release-schema-v2",
            "publicus-ir-graphrag/v2",
        },
    )

    artifact = resolver.resolve(MANIFEST_FILENAME, descriptor=descriptor)
    assert artifact.verified is True
    assert artifact.sha256 == descriptor.sha256
    assert not artifact.path.is_symlink()

    loaded = resolver.load_manifest(descriptor=descriptor)
    assert loaded.get("schema_version") or loaded.get("release_profile")
    assert loaded.get("lineage_is_control_plane") is False
    assert loaded.get("default_excludes_recovery") is True

    # Cache hit path must replay identical verified bytes.
    again = resolver.resolve(MANIFEST_FILENAME, descriptor=descriptor)
    assert again.cache_hit is True
    assert again.path.read_bytes() == manifest

    trace = resolver.fetch_trace()
    rendered = json.dumps(trace, sort_keys=True)
    assert token not in rendered
    assert "\"token\"" not in rendered
    assert str(tmp_path) not in rendered
    _assert_no_secret_leak(trace)
    _assert_no_secret_leak(loaded)


def test_safe_relative_path_and_normalize_agree_on_clean_paths() -> None:
    clean = "data/corpus/part-000000.parquet"
    assert normalize_relative_artifact_path(clean) == clean
    assert safe_relative_path(clean).as_posix() == clean


def test_release_errors_are_typed_and_serializable() -> None:
    err = UscodeHFReleaseIntegrityError("digest mismatch demo")
    payload = err.to_dict()
    assert payload["code"] == "uscode_hf_release_integrity"
    assert payload["kind"] == "error"
    assert "digest" in payload["message"]
    _assert_no_secret_leak(payload)


def test_security_report_case_inventory_matches_fixture_ids() -> None:
    report = json.loads(SECURITY_REPORT.read_text(encoding="utf-8"))
    fixture_ids = {case["id"] for case in _cases()}
    report_ids = set(report["case_ids"])
    assert report_ids == fixture_ids
    assert report["error_types_exercised"]
    for name in report["error_types_exercised"]:
        assert name in ERROR_TYPES


# ---------------------------------------------------------------------------
# Resource / decompression boundary smoke (pre-parse)
# ---------------------------------------------------------------------------


def test_oversized_release_row_rejected_before_artifact_use() -> None:
    with pytest.raises(UscodeHFReleaseIntegrityError, match="row_count|physical|bound"):
        ReleaseArtifact(
            relative_path="data/corpus/part-000000.parquet",
            content=b"PAR1-not-parsed",
            media_type="application/vnd.apache.parquet",
            family="corpus",
            row_count=MAX_ROWS_PER_PHYSICAL_SHARD + 1,
        )


def test_mutable_revision_rejected_before_resolver_construction(
    tmp_path: Path,
) -> None:
    with pytest.raises(MutableRevisionError):
        _resolver(tmp_path, revision="main")


def test_symlink_cache_root_components_rejected(tmp_path: Path) -> None:
    """Symlinked artifact paths fail closed during verify (pre-parse)."""

    real = tmp_path / "real-data.bin"
    real.write_bytes(b"x")
    link = tmp_path / "alias.bin"
    link.symlink_to(real)
    desc = ArtifactDescriptor(
        relative_path="data/x.bin",
        size_bytes=1,
        sha256=_sha(b"x"),
    )
    resolver = _resolver(tmp_path / "cache", files={})
    with pytest.raises(SymlinkRejectedError):
        resolver.verify_descriptor(link, desc)
