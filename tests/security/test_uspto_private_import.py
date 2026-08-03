"""Security tests: private USPTO import boundary (PATLAW-024).

Proves:
- no Patent Center scraping/MFA/session surface exists
- credentials and payment-card material are rejected
- wrong tenant/key cannot read content
- import is restartable/idempotent without rewriting ciphertext
- private artifact/text/CID never leaves authorized storage
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)
from ipfs_datasets_py.processors.domains.uspto.privacy import (
    ContentKind,
    PrivacyBoundaryError,
    PublicSink,
)
from ipfs_datasets_py.processors.domains.uspto.private_store import (
    AESGCMEncryptionBackend,
    DecryptionFailedError,
    PrivateArtifactStore,
    PrivateStoreError,
    ProhibitedContentError,
    TenantKeyMaterial,
    detect_prohibited_content,
    generate_tenant_key,
    make_private_cid,
    sha256_hex,
)
import ipfs_datasets_py.processors.domains.uspto.providers.patent_center_export as pce_mod
from ipfs_datasets_py.processors.domains.uspto.providers.patent_center_export import (
    FORBIDDEN_CAPABILITIES,
    PatentCenterExportProvider,
    load_fixture_authorization,
    load_fixture_manifest,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "uspto" / "private_import"
)
PRIVATE_TEXT_CANARY = "CONFIDENTIAL unpublished claim language canary-text-9f3a"


def _provider(
    tmp_path: Path, tenant: str = "tenant-a"
) -> tuple[PatentCenterExportProvider, PrivateArtifactStore, TenantKeyMaterial]:
    key = generate_tenant_key(tenant)
    tenant_key = TenantKeyMaterial(tenant_id=tenant, key_bytes=key.key_bytes)
    store = PrivateArtifactStore(tmp_path / f"store-{tenant}", tenant_key)
    return PatentCenterExportProvider(store), store, tenant_key


def test_module_has_no_scraping_mfa_session_code() -> None:
    source = inspect.getsource(pce_mod)
    for needle in (
        "import selenium",
        "from selenium",
        "import playwright",
        "from playwright",
        "webdriver.Chrome",
        "authenticate_session",
        "load_cookies(",
    ):
        assert needle not in source
    assert "scrape_authenticated_patent_center" in FORBIDDEN_CAPABILITIES
    for cap in (
        "bypass_mfa",
        "store_credentials_or_cookies",
        "read_browser_profile_or_session_storage",
    ):
        assert cap in FORBIDDEN_CAPABILITIES
    for name in ("login", "scrape"):
        assert not hasattr(PatentCenterExportProvider, name)


def test_forbidden_capability_surface(tmp_path: Path) -> None:
    provider, _, _ = _provider(tmp_path)
    for cap in sorted(FORBIDDEN_CAPABILITIES):
        with pytest.raises(Exception):
            provider.assert_capability_allowed(cap)
    with pytest.raises(Exception):
        provider.assert_capability_allowed("automate_mfa")


def test_credentials_and_payment_card_material_rejected(tmp_path: Path) -> None:
    provider, store, _ = _provider(tmp_path, "tenant-a")
    auth = load_fixture_authorization(
        FIXTURE_DIR, import_root=FIXTURE_DIR, tenant_id="tenant-a"
    )
    from ipfs_datasets_py.processors.domains.uspto.providers.patent_center_export import (
        ExportManifest,
        ExportManifestEntry,
        PATENT_CENTER_EXPORT_SCHEMA_VERSION,
    )

    manifest = ExportManifest(
        schema_version=PATENT_CENTER_EXPORT_SCHEMA_VERSION,
        export_id="syn-security-reject",
        matter_id="matter-sec",
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
    batch = provider.import_export(
        import_root=FIXTURE_DIR, manifest=manifest, authorization=auth
    )
    assert batch.imported_count == 0
    assert batch.rejected_count == 2
    assert store.list_artifact_ids() == ()

    with pytest.raises(ProhibitedContentError):
        store.put_bytes(
            (FIXTURE_DIR / "prohibited" / "credential_blob.txt").read_bytes(),
            artifact_id="bad-1",
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        )
    with pytest.raises(ProhibitedContentError):
        store.put_bytes(
            (FIXTURE_DIR / "prohibited" / "payment_card_sample.txt").read_bytes(),
            artifact_id="bad-2",
            classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        )
    with pytest.raises(ProhibitedContentError):
        store.put_bytes(
            b"innocent",
            artifact_id="bad-3",
            classification=DisclosureClassification.CREDENTIAL_OR_PAYMENT,
        )
    assert (
        detect_prohibited_content(b"CREDIT_CARD_NUMBER=4111111111111111\n") is not None
    )


def test_wrong_tenant_and_wrong_key_cannot_read(tmp_path: Path) -> None:
    key_a = generate_tenant_key("tenant-a")
    key_b = generate_tenant_key("tenant-b")
    assert key_a.key_bytes != key_b.key_bytes
    root = tmp_path / "shared-root"
    store_a = PrivateArtifactStore(root, key_a)
    plaintext = b"SYNTHETIC private office action body " + PRIVATE_TEXT_CANARY.encode()
    manifest, created = store_a.put_bytes(
        plaintext,
        artifact_id="art-tenant-a-1",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
        media_type="application/pdf",
    )
    assert created is True
    assert store_a.get_bytes("art-tenant-a-1") == plaintext

    store_b = PrivateArtifactStore(root, key_b)
    assert store_b.has_artifact("art-tenant-a-1") is False
    with pytest.raises(PrivateStoreError) as not_found:
        store_b.get_bytes("art-tenant-a-1")
    assert not_found.value.code == "not_found"

    wrong_key = TenantKeyMaterial(
        tenant_id="tenant-a",
        key_bytes=b"\x11" * 32,
        key_id=key_a.key_id,
    )
    store_wrong = PrivateArtifactStore(root, wrong_key)
    with pytest.raises(DecryptionFailedError):
        store_wrong.get_bytes("art-tenant-a-1")
    ct = store_a.ciphertext_bytes_for_tests("art-tenant-a-1")
    assert PRIVATE_TEXT_CANARY.encode() not in ct
    assert plaintext not in ct
    assert manifest.private_cid is not None
    assert manifest.encryption_namespace is not None
    assert manifest.public_cid is None


def test_import_restartable_idempotent_no_duplicate_ciphertext(tmp_path: Path) -> None:
    provider, store, _ = _provider(tmp_path, "tenant-a")
    auth = load_fixture_authorization(
        FIXTURE_DIR, import_root=FIXTURE_DIR, tenant_id="tenant-a"
    )
    manifest = load_fixture_manifest(FIXTURE_DIR)
    first = provider.import_export(
        import_root=FIXTURE_DIR, manifest=manifest, authorization=auth
    )
    r = first.results[0]
    ct_before = store.ciphertext_bytes_for_tests(r.artifact_id)
    second = provider.import_export(
        import_root=FIXTURE_DIR, manifest=manifest, authorization=auth
    )
    assert first.imported_count == len(manifest.entries)
    assert second.skipped_count == len(manifest.entries)
    assert second.imported_count == 0
    ct_after = store.ciphertext_bytes_for_tests(r.artifact_id)
    assert ct_before == ct_after
    assert sha256_hex(ct_before) == sha256_hex(ct_after)


def test_private_artifact_text_cid_never_leave_authorized_storage(
    tmp_path: Path,
) -> None:
    provider, store, _ = _provider(tmp_path, "tenant-a")
    auth = load_fixture_authorization(
        FIXTURE_DIR, import_root=FIXTURE_DIR, tenant_id="tenant-a"
    )
    batch = provider.import_export(
        import_root=FIXTURE_DIR,
        manifest=load_fixture_manifest(FIXTURE_DIR),
        authorization=auth,
    )
    assert batch.rejected_count == 0
    batch_json = json.dumps(batch.to_dict())
    assert PRIVATE_TEXT_CANARY not in batch_json
    assert "private_cid" not in batch_json
    assert "bafy" not in batch_json and "bafk" not in batch_json

    for result in batch.results:
        assert result.manifest is not None
        assert "private_cid" not in result.manifest
        full = store.get_manifest(result.artifact_id)
        assert full.private_cid is not None
        assert full.is_private or full.is_quarantined
        for sink in PublicSink:
            with pytest.raises(PrivacyBoundaryError):
                store.export_to_public_sink(
                    result.artifact_id, sink, ContentKind.DOCUMENT_BYTES
                )
            with pytest.raises(PrivacyBoundaryError):
                store.export_to_public_sink(
                    result.artifact_id, sink, ContentKind.CONTENT_IDENTIFIER
                )
            with pytest.raises(PrivacyBoundaryError):
                store.export_to_public_sink(
                    result.artifact_id, sink, ContentKind.EXTRACTED_TEXT
                )
        audit = store.audit_safe_summary(result.artifact_id)
        assert audit.get("text") is None or "text" not in audit
        assert audit.get("digest") == full.sha256
        assert audit.get("redacted") is True
        assert "private_cid" not in audit


def test_on_disk_layout_is_ciphertext_only(tmp_path: Path) -> None:
    store_root = tmp_path / "store"
    key = generate_tenant_key("tenant-a")
    store = PrivateArtifactStore(store_root, key)
    body = b"%PDF-SYNTHETIC-PRIVATE-" + PRIVATE_TEXT_CANARY.encode()
    store.put_bytes(
        body,
        artifact_id="disk-1",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    for path in store_root.rglob("*"):
        if path.is_file():
            raw = path.read_bytes()
            assert PRIVATE_TEXT_CANARY.encode() not in raw
            assert body not in raw


def test_private_cid_is_deterministic_and_not_public_pin_handle() -> None:
    d = "abababababababababababababababababababababababababababababababab"
    cid1 = make_private_cid(d)
    cid2 = make_private_cid(d)
    assert cid1 == cid2
    assert cid1.startswith("b")
    assert len(cid1) >= 59


def test_encryption_backend_pluggable(tmp_path: Path) -> None:
    backend = AESGCMEncryptionBackend()
    key = generate_tenant_key("tenant-a")
    store = PrivateArtifactStore(tmp_path / "s", key, backend=backend)
    store.put_bytes(
        b"hello-private",
        artifact_id="x1",
        classification=DisclosureClassification.CONFIDENTIAL_APPLICATION,
    )
    assert store.get_bytes("x1") == b"hello-private"
    assert store.encryption_suite == "AES-256-GCM"


def test_provider_doc_states_import_only_policy() -> None:
    doc = (pce_mod.__doc__ or "").lower()
    assert "import" in doc
    assert "does **not**" in (pce_mod.__doc__ or "") or "does not" in doc
    assert "scrape" in doc
    assert "mfa" in doc
