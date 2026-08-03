"""Unit tests for authorized Patent Center export import (PATLAW-024)."""

from __future__ import annotations

import inspect
import io
import json
import zipfile
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    AuthorityRelation,
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.private_store import (
    PrivateArtifactStore,
    generate_tenant_key,
    sha256_hex,
)
import ipfs_datasets_py.processors.domains.uspto.providers.patent_center_export as pce
from ipfs_datasets_py.processors.domains.uspto.providers.patent_center_export import (
    ALLOWED_CAPABILITIES,
    FORBIDDEN_CAPABILITIES,
    AuthorizationError,
    ExportManifest,
    ExportManifestEntry,
    ForbiddenCapabilityError,
    ImportAuthorization,
    PatentCenterExportProvider,
    PathEscapeError,
    assert_no_scraping_surface,
    assert_zip_members_safe,
    deterministic_artifact_id,
    load_fixture_authorization,
    load_fixture_manifest,
    resolve_under_import_root,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[5] / "fixtures" / "uspto" / "private_import"
)


def _store(tmp_path: Path, tenant: str = "tenant-a") -> PrivateArtifactStore:
    key = generate_tenant_key(tenant)
    return PrivateArtifactStore(tmp_path / "store", key)


def _auth(import_root: Path, tenant: str = "tenant-a") -> ImportAuthorization:
    return load_fixture_authorization(
        FIXTURE_DIR, import_root=import_root, tenant_id=tenant
    )


def test_fixture_layout_exists() -> None:
    assert (FIXTURE_DIR / "export_manifest.json").is_file()
    assert (FIXTURE_DIR / "authorization.json").is_file()
    assert (FIXTURE_DIR / "package" / "original_specification.docx").is_file()
    assert (FIXTURE_DIR / "prohibited" / "credential_blob.txt").is_file()


def test_no_scraping_or_session_surface_in_module_source() -> None:
    source = inspect.getsource(pce)
    for needle in (
        "import selenium",
        "from selenium",
        "import playwright",
        "from playwright",
        "import puppeteer",
        "requests.Session",
        "httpx.Client",
        "urllib.request",
    ):
        assert needle not in source
    assert_no_scraping_surface()
    provider = PatentCenterExportProvider
    for name in (
        "login",
        "scrape",
        "automate_mfa",
        "load_session",
        "read_browser_profile",
        "pay_fee",
        "submit_filing",
    ):
        assert not hasattr(provider, name)


def test_forbidden_capabilities_are_rejected(tmp_path: Path) -> None:
    provider = PatentCenterExportProvider(_store(tmp_path))
    for cap in sorted(FORBIDDEN_CAPABILITIES):
        with pytest.raises(ForbiddenCapabilityError):
            provider.assert_capability_allowed(cap)
    for cap in sorted(ALLOWED_CAPABILITIES):
        provider.assert_capability_allowed(cap)


def test_path_escape_and_symlink_rejected(tmp_path: Path) -> None:
    root = tmp_path / "import_root"
    root.mkdir()
    good = root / "ok.txt"
    good.write_text("hello", encoding="utf-8")
    assert resolve_under_import_root(root, "ok.txt").is_file()
    for bad in ("../ok.txt", "/etc/passwd", "sub/../../ok.txt"):
        with pytest.raises(PathEscapeError):
            resolve_under_import_root(root, bad)
    target = tmp_path / "outside.txt"
    target.write_text("secret", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks not supported")
    with pytest.raises(PathEscapeError):
        resolve_under_import_root(root, "link.txt")


def test_zip_slip_members_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.txt", b"nope")
        zf.writestr("safe/doc.txt", b"ok")
    with pytest.raises(PathEscapeError):
        assert_zip_members_safe(buf.getvalue())
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as zf:
        zf.writestr("safe/doc.txt", b"ok")
    assert_zip_members_safe(buf2.getvalue())


def test_import_authorized_fixture_package(tmp_path: Path) -> None:
    store = _store(tmp_path, "tenant-a")
    provider = PatentCenterExportProvider(store)
    import_root = FIXTURE_DIR
    auth = _auth(import_root, "tenant-a")
    manifest = load_fixture_manifest(FIXTURE_DIR)
    batch = provider.import_export(
        import_root=import_root, manifest=manifest, authorization=auth
    )
    assert batch.rejected_count == 0
    assert batch.imported_count == len(manifest.entries)
    assert batch.skipped_count == 0
    assert batch.source_receipt.endpoint == "local://authorized-patent-center-export"
    assert batch.source_receipt.metadata["authorization_id"] == auth.authorization_id
    receipt_json = json.dumps(batch.source_receipt.to_dict()).lower()
    assert "password" not in receipt_json
    for result in batch.results:
        assert result.status == "imported"
        assert result.sha256
        assert store.has_artifact(result.artifact_id)
        assert result.manifest is not None
        assert "private_cid" not in result.manifest
        plaintext = store.get_bytes(result.artifact_id)
        assert sha256_hex(plaintext) == result.sha256


def test_import_is_idempotent_and_restartable(tmp_path: Path) -> None:
    store = _store(tmp_path, "tenant-a")
    provider = PatentCenterExportProvider(store)
    import_root = FIXTURE_DIR
    auth = _auth(import_root, "tenant-a")
    manifest = load_fixture_manifest(FIXTURE_DIR)
    first = provider.import_export(
        import_root=import_root, manifest=manifest, authorization=auth
    )
    second = provider.import_export(
        import_root=import_root, manifest=manifest, authorization=auth
    )
    assert first.imported_count == len(manifest.entries)
    assert first.skipped_count == 0
    assert second.imported_count == 0
    assert second.skipped_count == len(manifest.entries)
    assert second.rejected_count == 0
    first_ids = {r.relative_path: r.artifact_id for r in first.results}
    second_ids = {r.relative_path: r.artifact_id for r in second.results}
    assert first_ids == second_ids


def test_tenant_mismatch_authorization_rejected(tmp_path: Path) -> None:
    provider = PatentCenterExportProvider(_store(tmp_path, "tenant-a"))
    auth = _auth(FIXTURE_DIR, "other-tenant")
    with pytest.raises(AuthorizationError) as exc:
        provider.import_export(
            import_root=FIXTURE_DIR,
            manifest=load_fixture_manifest(FIXTURE_DIR),
            authorization=auth,
        )
    assert exc.value.code == "tenant_mismatch"


def test_import_root_mismatch_rejected(tmp_path: Path) -> None:
    provider = PatentCenterExportProvider(_store(tmp_path, "tenant-a"))
    other_root = tmp_path / "other_root"
    other_root.mkdir()
    auth = _auth(other_root, "tenant-a")
    with pytest.raises(AuthorizationError) as exc:
        provider.import_export(
            import_root=FIXTURE_DIR,
            manifest=load_fixture_manifest(FIXTURE_DIR),
            authorization=auth,
        )
    assert exc.value.code == "import_root_mismatch"


def test_credential_classification_entry_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path, "tenant-a")
    provider = PatentCenterExportProvider(store)
    root = tmp_path / "root"
    root.mkdir()
    (root / "secret.txt").write_text("not credentials body", encoding="utf-8")
    manifest = ExportManifest(
        schema_version=pce.PATENT_CENTER_EXPORT_SCHEMA_VERSION,
        export_id="syn-export-cred",
        matter_id="matter-x",
        application_number=None,
        entries=(
            ExportManifestEntry(
                relative_path="secret.txt",
                classification=DisclosureClassification.CREDENTIAL_OR_PAYMENT,
                media_type="text/plain",
            ),
        ),
    )
    auth = ImportAuthorization(
        schema_version=pce.PATENT_CENTER_EXPORT_SCHEMA_VERSION,
        authorization_id="authz-cred",
        authorizing_user="practitioner:synthetic",
        tenant_id="tenant-a",
        granted_utc="2026-08-01T12:00:00Z",
        import_root=str(root),
        scope="import_authorized_local_export",
    )
    batch = provider.import_export(
        import_root=root, manifest=manifest, authorization=auth
    )
    assert batch.rejected_count == 1
    assert batch.imported_count == 0
    assert "credential" in (batch.results[0].reason_code or "")


def test_prohibited_content_file_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path, "tenant-a")
    provider = PatentCenterExportProvider(store)
    manifest = ExportManifest(
        schema_version=pce.PATENT_CENTER_EXPORT_SCHEMA_VERSION,
        export_id="syn-export-bad",
        matter_id="matter-x",
        application_number=None,
        entries=(
            ExportManifestEntry(
                relative_path="prohibited/credential_blob.txt",
                classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
                media_type="text/plain",
            ),
            ExportManifestEntry(
                relative_path="prohibited/payment_card_sample.txt",
                classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
                media_type="text/plain",
            ),
        ),
    )
    auth = _auth(FIXTURE_DIR, "tenant-a")
    batch = provider.import_export(
        import_root=FIXTURE_DIR, manifest=manifest, authorization=auth
    )
    assert batch.imported_count == 0
    assert batch.rejected_count == 2


def test_deterministic_artifact_ids() -> None:
    a = deterministic_artifact_id(
        export_id="e1",
        relative_path="a.txt",
        sha256="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    b = deterministic_artifact_id(
        export_id="e1",
        relative_path="b.txt",
        sha256="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    assert a.startswith("pce:")
    assert a != b
    assert a == deterministic_artifact_id(
        export_id="e1",
        relative_path="a.txt",
        sha256="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )


def test_export_manifest_round_trip() -> None:
    manifest = load_fixture_manifest(FIXTURE_DIR)
    restored = ExportManifest.from_dict(manifest.to_dict())
    assert restored.to_dict() == manifest.to_dict()
    assert restored.entries[0].authority_relation is AuthorityRelation.AUTHORITATIVE_ORIGINAL


def test_authorization_rejects_embedded_secrets() -> None:
    with pytest.raises(AuthorizationError):
        ImportAuthorization(
            schema_version=pce.PATENT_CENTER_EXPORT_SCHEMA_VERSION,
            authorization_id="authz-bad",
            authorizing_user="user password=hunter2",
            tenant_id="tenant-a",
            granted_utc="2026-08-01T12:00:00Z",
            import_root="/tmp/x",
            scope="import_authorized_local_export",
        )
