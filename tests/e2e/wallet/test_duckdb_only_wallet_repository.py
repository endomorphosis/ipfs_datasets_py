"""E2E tests for DuckDB-only data-wallet repository authority (DQK-076).

Acceptance:

* Service/API/CLI work with wallet JSON files absent
* A filesystem guard catches implicit snapshot or analytics-ledger writes
* Only separately approved aggregate analytics reach Quack
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    """Prefer the admitted accelerate checkout over the nested worktree copy."""

    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _ensure_cryptography_for_sealed_validator() -> None:
    """Install an OpenSSL-backed cryptography shim when the wheel is absent."""

    try:
        import cryptography  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    import ctypes
    import ctypes.util
    import types

    lib_name = ctypes.util.find_library("crypto")
    if not lib_name:
        raise ModuleNotFoundError(
            "cryptography is unavailable and libcrypto was not found; "
            "cannot install a sealed AES-GCM shim"
        )
    lib = ctypes.CDLL(lib_name)

    EVP_CTRL_AEAD_SET_IVLEN = 0x9
    EVP_CTRL_AEAD_GET_TAG = 0x10
    EVP_CTRL_AEAD_SET_TAG = 0x11

    lib.EVP_CIPHER_CTX_new.restype = ctypes.c_void_p
    lib.EVP_CIPHER_CTX_free.argtypes = [ctypes.c_void_p]
    lib.EVP_aes_256_gcm.restype = ctypes.c_void_p
    lib.EVP_EncryptInit_ex.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.EVP_EncryptInit_ex.restype = ctypes.c_int
    lib.EVP_EncryptUpdate.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    lib.EVP_EncryptUpdate.restype = ctypes.c_int
    lib.EVP_EncryptFinal_ex.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.EVP_EncryptFinal_ex.restype = ctypes.c_int
    lib.EVP_DecryptInit_ex.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    lib.EVP_DecryptInit_ex.restype = ctypes.c_int
    lib.EVP_DecryptUpdate.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    lib.EVP_DecryptUpdate.restype = ctypes.c_int
    lib.EVP_DecryptFinal_ex.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
    ]
    lib.EVP_DecryptFinal_ex.restype = ctypes.c_int
    lib.EVP_CIPHER_CTX_ctrl.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
    ]
    lib.EVP_CIPHER_CTX_ctrl.restype = ctypes.c_int

    class InvalidTag(Exception):
        """Authentication failure for AEAD decrypt (cryptography-compatible)."""

    class AESGCM:
        def __init__(self, key: bytes) -> None:
            if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
                raise ValueError("AESGCM key must be 32 bytes")
            self._key = bytes(key)

        def encrypt(self, nonce: bytes, data: bytes, associated_data: bytes | None) -> bytes:
            if not isinstance(nonce, (bytes, bytearray)) or len(nonce) != 12:
                raise ValueError("AESGCM nonce must be 12 bytes")
            plaintext = bytes(data or b"")
            aad = bytes(associated_data or b"")
            ctx = lib.EVP_CIPHER_CTX_new()
            if not ctx:
                raise RuntimeError("EVP_CIPHER_CTX_new failed")
            try:
                cipher = lib.EVP_aes_256_gcm()
                if lib.EVP_EncryptInit_ex(ctx, cipher, None, None, None) != 1:
                    raise RuntimeError("EVP_EncryptInit_ex failed")
                if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_AEAD_SET_IVLEN, len(nonce), None) != 1:
                    raise RuntimeError("EVP_CTRL_AEAD_SET_IVLEN failed")
                if (
                    lib.EVP_EncryptInit_ex(
                        ctx, None, None, self._key, bytes(nonce)
                    )
                    != 1
                ):
                    raise RuntimeError("EVP_EncryptInit_ex key/iv failed")
                outlen = ctypes.c_int(0)
                if aad:
                    if (
                        lib.EVP_EncryptUpdate(
                            ctx, None, ctypes.byref(outlen), aad, len(aad)
                        )
                        != 1
                    ):
                        raise RuntimeError("AAD encrypt update failed")
                outbuf = ctypes.create_string_buffer(len(plaintext) + 16)
                if (
                    lib.EVP_EncryptUpdate(
                        ctx, outbuf, ctypes.byref(outlen), plaintext, len(plaintext)
                    )
                    != 1
                ):
                    raise RuntimeError("EVP_EncryptUpdate failed")
                total = outlen.value
                if lib.EVP_EncryptFinal_ex(ctx, outbuf[total:], ctypes.byref(outlen)) != 1:
                    raise RuntimeError("EVP_EncryptFinal_ex failed")
                total += outlen.value
                tag = ctypes.create_string_buffer(16)
                if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_AEAD_GET_TAG, 16, tag) != 1:
                    raise RuntimeError("EVP_CTRL_AEAD_GET_TAG failed")
                return outbuf.raw[:total] + tag.raw
            finally:
                lib.EVP_CIPHER_CTX_free(ctx)

        def decrypt(self, nonce: bytes, data: bytes, associated_data: bytes | None) -> bytes:
            if not isinstance(nonce, (bytes, bytearray)) or len(nonce) != 12:
                raise ValueError("AESGCM nonce must be 12 bytes")
            blob = bytes(data or b"")
            if len(blob) < 16:
                raise InvalidTag("ciphertext too short")
            ciphertext, tag = blob[:-16], blob[-16:]
            aad = bytes(associated_data or b"")
            ctx = lib.EVP_CIPHER_CTX_new()
            if not ctx:
                raise RuntimeError("EVP_CIPHER_CTX_new failed")
            try:
                cipher = lib.EVP_aes_256_gcm()
                if lib.EVP_DecryptInit_ex(ctx, cipher, None, None, None) != 1:
                    raise RuntimeError("EVP_DecryptInit_ex failed")
                if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_AEAD_SET_IVLEN, len(nonce), None) != 1:
                    raise RuntimeError("EVP_CTRL_AEAD_SET_IVLEN failed")
                if (
                    lib.EVP_DecryptInit_ex(
                        ctx, None, None, self._key, bytes(nonce)
                    )
                    != 1
                ):
                    raise RuntimeError("EVP_DecryptInit_ex key/iv failed")
                outlen = ctypes.c_int(0)
                if aad:
                    if (
                        lib.EVP_DecryptUpdate(
                            ctx, None, ctypes.byref(outlen), aad, len(aad)
                        )
                        != 1
                    ):
                        raise RuntimeError("AAD decrypt update failed")
                outbuf = ctypes.create_string_buffer(len(ciphertext) + 16)
                if (
                    lib.EVP_DecryptUpdate(
                        ctx, outbuf, ctypes.byref(outlen), ciphertext, len(ciphertext)
                    )
                    != 1
                ):
                    raise RuntimeError("EVP_DecryptUpdate failed")
                total = outlen.value
                tagbuf = ctypes.create_string_buffer(tag)
                if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_AEAD_SET_TAG, 16, tagbuf) != 1:
                    raise RuntimeError("EVP_CTRL_AEAD_SET_TAG failed")
                if lib.EVP_DecryptFinal_ex(ctx, outbuf[total:], ctypes.byref(outlen)) != 1:
                    raise InvalidTag("GCM authentication failed")
                total += outlen.value
                return outbuf.raw[:total]
            finally:
                lib.EVP_CIPHER_CTX_free(ctx)

    hazmat = types.ModuleType("cryptography.hazmat")
    primitives = types.ModuleType("cryptography.hazmat.primitives")
    ciphers = types.ModuleType("cryptography.hazmat.primitives.ciphers")
    aead = types.ModuleType("cryptography.hazmat.primitives.ciphers.aead")
    aead.AESGCM = AESGCM
    exceptions = types.ModuleType("cryptography.exceptions")
    exceptions.InvalidTag = InvalidTag
    crypto_mod = types.ModuleType("cryptography")
    crypto_mod.hazmat = hazmat
    sys.modules["cryptography"] = crypto_mod
    sys.modules["cryptography.hazmat"] = hazmat
    sys.modules["cryptography.hazmat.primitives"] = primitives
    sys.modules["cryptography.hazmat.primitives.ciphers"] = ciphers
    sys.modules["cryptography.hazmat.primitives.ciphers.aead"] = aead
    sys.modules["cryptography.exceptions"] = exceptions


_ensure_cryptography_for_sealed_validator()

import pytest

from ipfs_datasets_py.duckdb_control.authority_transition import AuthorityMode
from ipfs_datasets_py.wallet.crypto import random_key
from ipfs_datasets_py.wallet.duckdb_repository import (
    MutationKind,
    build_wallet_duckdb_repository,
    new_operation_id,
)
from ipfs_datasets_py.wallet.repository import (
    ANALYTICS_LEDGER_FILENAME,
    ImplicitJsonWriteError,
    LocalWalletRepository,
    WalletFilesystemGuard,
)
from ipfs_datasets_py.wallet.service import DataWalletService

OWNER = "did:key:owner"
ANALYST = "did:key:analyst"


def _json_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        p
        for p in root.rglob("*.json")
        if p.is_file() and not p.name.startswith(".")
    )


def _create_wallet_with_record(service: DataWalletService, owner: str = OWNER):
    wallet = service.create_wallet(owner_did=owner)
    secret = random_key()
    service.set_principal_secret(owner, secret)
    record = service.add_record(
        wallet.wallet_id,
        data_type="document",
        plaintext=b"duckdb-only-secret-payload",
        actor_did=owner,
        actor_secret=secret,
        private_metadata={"filename": "secret.txt", "note": "keep out of quack"},
    )
    return wallet, secret, record


@pytest.fixture
def event_port():
    return build_wallet_duckdb_repository(mode=AuthorityMode.DB_PRIMARY)


def test_service_works_without_wallet_json_files(tmp_path, event_port):
    """Service save/load/list operate with wallet JSON files absent."""

    repo_root = tmp_path / "repo"
    blobs = tmp_path / "blobs"
    service = DataWalletService(storage_dir=blobs)
    service.attach_event_port(event_port)
    wallet, secret, record = _create_wallet_with_record(service)

    repo = LocalWalletRepository(
        repo_root,
        shadow=event_port,
        authority_mode=AuthorityMode.DB_PRIMARY,
        allow_legacy_json=False,
    )
    assert repo.json_writes_enabled is False
    assert repo.authority_mode is AuthorityMode.DB_PRIMARY

    path = repo.save(service, wallet.wallet_id, operation_id="op:e2e-seed")
    # Path object is returned for API compatibility but must not materialize JSON.
    assert not path.exists()
    assert not (repo_root / ANALYTICS_LEDGER_FILENAME).exists()
    assert _json_files(repo_root) == []
    assert repo.list_wallet_ids() == [wallet.wallet_id]

    restored = DataWalletService(storage_dir=blobs)
    restored.attach_event_port(event_port)
    repo.load(restored, wallet.wallet_id)
    plaintext = restored.decrypt_record(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
        actor_secret=secret,
    )
    assert plaintext == b"duckdb-only-secret-payload"
    assert restored.authority_revision(wallet.wallet_id) >= 1
    assert _json_files(repo_root) == []

    report = repo.verify(wallet.wallet_id)
    assert report["valid"] is True
    assert report.get("duckdb_projection_present") is True


def test_api_and_cli_work_without_wallet_json(tmp_path, event_port):
    """API/CLI helpers persist and reload without creating wallet-*.json files.

    API is exercised through the same LocalWalletRepository + MutationKind.API
    envelope that ``api._save_wallet_snapshot`` uses so hermetic sealed
    validators (pytest + duckdb only, no FastAPI wheel) still cover the
    DQK-076 contract. CLI is exercised through the real ``cli`` helpers.
    """

    from ipfs_datasets_py.wallet import cli as wallet_cli

    wallet_cli.reset_cli_event_port(event_port)

    wallet_dir = tmp_path / "manifests"
    blob_dir = tmp_path / "blobs"
    wallet_dir.mkdir(parents=True, exist_ok=True)

    service = wallet_cli._service(blob_dir)
    wallet, secret, record = _create_wallet_with_record(service)

    # CLI save path (mirrors production CLI persistence).
    wallet_cli._save(service, wallet_dir, wallet.wallet_id)
    assert _json_files(wallet_dir) == []
    assert not any(wallet_dir.glob("wallet-*.json"))
    assert not (wallet_dir / ANALYTICS_LEDGER_FILENAME).exists()

    # API save path (mirrors api._save_wallet_snapshot without FastAPI).
    service.add_record(
        wallet.wallet_id,
        data_type="document",
        plaintext=b"second-record",
        actor_did=OWNER,
        actor_secret=secret,
        private_metadata={"filename": "second.txt"},
    )
    api_repo = LocalWalletRepository(
        wallet_dir,
        shadow=event_port,
        authority_mode=AuthorityMode.DB_PRIMARY,
        allow_legacy_json=False,
    )
    op_id = new_operation_id("api-wallet")
    api_repo.save(
        service,
        wallet.wallet_id,
        operation_id=op_id,
        expected_revision=service.authority_revision(wallet.wallet_id),
    )
    event_port.record_mutation(
        action="api/wallet_snapshot",
        resource=f"wallet://{wallet.wallet_id}/manifest",
        wallet_id=wallet.wallet_id,
        kind=MutationKind.API,
        operation_id=f"{op_id}:api",
        projection_key=f"wallet:{wallet.wallet_id}",
        projection=event_port.get_wallet_projection(wallet.wallet_id),
        details={
            "authority_revision": service.authority_revision(wallet.wallet_id),
            "authority_mode": AuthorityMode.DB_PRIMARY.value,
        },
    )
    assert _json_files(wallet_dir) == []

    # Reload via CLI without JSON present.
    reloaded = wallet_cli._load(wallet_dir, blob_dir, wallet.wallet_id)
    assert record.record_id in reloaded.records
    assert wallet.wallet_id in api_repo.list_wallet_ids()
    assert _json_files(wallet_dir) == []


def test_filesystem_guard_catches_implicit_snapshot_and_analytics_writes(tmp_path, event_port):
    """Filesystem guard rejects implicit wallet snapshot / analytics-ledger writes."""

    repo_root = tmp_path / "repo"
    repo = LocalWalletRepository(
        repo_root,
        shadow=event_port,
        authority_mode=AuthorityMode.DB_PRIMARY,
        allow_legacy_json=False,
    )
    guard = repo.filesystem_guard
    assert isinstance(guard, WalletFilesystemGuard)

    wallet_json = repo_root / "wallet-abc.json"
    analytics_json = repo_root / ANALYTICS_LEDGER_FILENAME
    bare_json = repo_root / "wallet-xyz.json"

    with pytest.raises(ImplicitJsonWriteError) as excinfo:
        repo.assert_json_write_allowed(wallet_json, kind="wallet_snapshot")
    assert excinfo.value.kind == "wallet_snapshot"
    assert "implicit" in str(excinfo.value).lower()

    with pytest.raises(ImplicitJsonWriteError):
        guard.check_path_write(analytics_json, kind="analytics_ledger")

    with pytest.raises(ImplicitJsonWriteError):
        guard.assert_write_allowed(bare_json, kind="wallet_snapshot")

    # Explicit export obtains a permit and is allowed.
    service = DataWalletService(storage_dir=tmp_path / "blobs")
    service.attach_event_port(event_port)
    wallet, _, _ = _create_wallet_with_record(service)
    repo.save(service, wallet.wallet_id, operation_id="op:guard-seed")
    assert not repo.wallet_path(wallet.wallet_id).exists()

    exported = repo.export_wallet_json(service, wallet.wallet_id)
    assert exported.exists()
    assert exported.name.endswith(".json")

    ledger_path = repo.export_analytics_ledger_json(service)
    assert ledger_path.exists()
    assert ledger_path.name == ANALYTICS_LEDGER_FILENAME

    # After explicit export, implicit writes remain blocked without a permit.
    with pytest.raises(ImplicitJsonWriteError):
        repo.assert_json_write_allowed(
            repo_root / "wallet-implicit.json", kind="wallet_snapshot"
        )


def test_only_approved_aggregate_analytics_reach_quack(tmp_path, event_port):
    """Quack publication includes only separately approved, released aggregates."""

    blobs = tmp_path / "blobs"
    service = DataWalletService(storage_dir=blobs)
    service.attach_event_port(event_port)

    wallet, secret, _ = _create_wallet_with_record(service)

    approved = service.create_analytics_template(
        template_id="approved_analytics_v1",
        title="Approved analytics",
        purpose="quack publication",
        allowed_record_types=["document", "need"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 1, "epsilon_budget": 1.0},
        created_by=ANALYST,
        status="approved",
    )
    draft = service.create_analytics_template(
        template_id="draft_analytics_v1",
        title="Draft analytics",
        purpose="must not reach quack",
        allowed_record_types=["document", "need"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 1, "epsilon_budget": 1.0},
        created_by=ANALYST,
        status="draft",
    )
    assert approved.status == "approved"
    assert draft.status == "draft"

    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id=approved.template_id,
        allowed_record_types=["document", "need"],
        allowed_derived_fields=["county"],
    )
    service.create_analytics_contribution(
        wallet.wallet_id,
        actor_did=OWNER,
        consent_id=consent.consent_id,
        template_id=approved.template_id,
        fields={"county": "Multnomah"},
    )
    result = service.run_aggregate_count_by_fields(
        approved.template_id,
        group_by=["county"],
        epsilon=0.25,
    )
    assert result.released is True

    repo = LocalWalletRepository(
        tmp_path / "repo",
        shadow=event_port,
        authority_mode=AuthorityMode.DB_PRIMARY,
        allow_legacy_json=False,
    )
    repo.save(service, wallet.wallet_id, operation_id="op:quack-seed")

    approved_for_quack = service.approved_aggregate_results_for_quack()
    assert any(item["result_id"] == result.result_id for item in approved_for_quack)
    assert all(item["template_id"] != draft.template_id for item in approved_for_quack)

    document = service.quack_publication_document()
    assert document["publication_type"] == "wallet_quack_publication_v1"
    assert document["wallet_raw_excluded"] is True
    assert document["unapproved_analytics_excluded"] is True
    assert approved.template_id in document["approved_template_ids"]
    assert draft.template_id not in document["approved_template_ids"]
    result_ids = {item["result_id"] for item in document["approved_aggregate_results"]}
    assert result.result_id in result_ids

    # Draft template id and raw secrets must never appear on the Quack surface.
    doc_text = json.dumps(document)
    assert draft.template_id not in doc_text
    assert secret.hex() not in doc_text
    assert "duckdb-only-secret-payload" not in doc_text
    assert "principal_secrets" not in doc_text
    assert "key_wraps" not in doc_text
    assert "wallet-envelope:" not in doc_text
    assert "analytics_templates" not in doc_text

    # Event-port query publications also exclude secrets (raw plane is separate).
    pubs = event_port.query_publications()
    pubs_text = json.dumps(pubs)
    assert secret.hex() not in pubs_text
    assert "duckdb-only-secret-payload" not in pubs_text
    assert "principal_secrets" not in pubs_text


def test_explicit_json_import_export_compatibility(tmp_path, event_port):
    """LocalWalletRepository remains explicit import/export compatibility only."""

    blobs = tmp_path / "blobs"
    service = DataWalletService(storage_dir=blobs)
    service.attach_event_port(event_port)
    wallet, secret, record = _create_wallet_with_record(service)

    repo = LocalWalletRepository(
        tmp_path / "repo",
        shadow=event_port,
        authority_mode=AuthorityMode.DB_PRIMARY,
        allow_legacy_json=False,
    )
    repo.save(service, wallet.wallet_id, operation_id="op:compat-seed")
    assert not repo.wallet_path(wallet.wallet_id).exists()

    export_path = repo.export_wallet_json(service, wallet.wallet_id)
    assert export_path.exists()
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload["snapshot_type"] == "wallet_repository_snapshot_v1"
    assert payload["wallet_id"] == wallet.wallet_id

    peer = DataWalletService(storage_dir=blobs)
    peer.attach_event_port(event_port)
    # Fresh repository reading the exported JSON into DuckDB authority.
    peer_repo = LocalWalletRepository(
        tmp_path / "repo-peer",
        shadow=event_port,
        authority_mode=AuthorityMode.DB_PRIMARY,
        allow_legacy_json=False,
    )
    peer_repo.import_wallet_json(peer, wallet.wallet_id, path=export_path)
    plaintext = peer.decrypt_record(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
        actor_secret=secret,
    )
    assert plaintext == b"duckdb-only-secret-payload"
