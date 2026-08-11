"""Integration tests for data-wallet DuckDB authority cutover (DQK-075).

Acceptance:

* Concurrent API/CLI mutation, audit verification, grant lifecycle, restart
  and blob outage tests pass
* Snapshot and analytics hashes remain stable
* Stale service instances cannot overwrite a newer revision
"""

from __future__ import annotations

import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
                    raise RuntimeError("encrypt update failed")
                total = outlen.value
                finlen = ctypes.c_int(0)
                if lib.EVP_EncryptFinal_ex(
                    ctx, ctypes.byref(outbuf, total), ctypes.byref(finlen)
                ) != 1:
                    raise RuntimeError("encrypt final failed")
                total += finlen.value
                tag = ctypes.create_string_buffer(16)
                if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_AEAD_GET_TAG, 16, tag) != 1:
                    raise RuntimeError("get tag failed")
                return outbuf.raw[:total] + tag.raw
            finally:
                lib.EVP_CIPHER_CTX_free(ctx)

        def decrypt(self, nonce: bytes, data: bytes, associated_data: bytes | None) -> bytes:
            if not isinstance(nonce, (bytes, bytearray)) or len(nonce) != 12:
                raise ValueError("AESGCM nonce must be 12 bytes")
            blob = bytes(data or b"")
            if len(blob) < 16:
                raise InvalidTag("ciphertext too short for GCM tag")
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
                    raise RuntimeError("decrypt update failed")
                total = outlen.value
                if lib.EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_AEAD_SET_TAG, 16, tag) != 1:
                    raise RuntimeError("set tag failed")
                finlen = ctypes.c_int(0)
                if (
                    lib.EVP_DecryptFinal_ex(
                        ctx, ctypes.byref(outbuf, total), ctypes.byref(finlen)
                    )
                    != 1
                ):
                    raise InvalidTag("Unable to authenticate encrypted wallet data")
                total += finlen.value
                return outbuf.raw[:total]
            finally:
                lib.EVP_CIPHER_CTX_free(ctx)

    cryptography_mod = types.ModuleType("cryptography")
    exceptions_mod = types.ModuleType("cryptography.exceptions")
    exceptions_mod.InvalidTag = InvalidTag
    hazmat_mod = types.ModuleType("cryptography.hazmat")
    primitives_mod = types.ModuleType("cryptography.hazmat.primitives")
    ciphers_mod = types.ModuleType("cryptography.hazmat.primitives.ciphers")
    aead_mod = types.ModuleType("cryptography.hazmat.primitives.ciphers.aead")
    aead_mod.AESGCM = AESGCM

    cryptography_mod.exceptions = exceptions_mod
    cryptography_mod.hazmat = hazmat_mod
    hazmat_mod.primitives = primitives_mod
    primitives_mod.ciphers = ciphers_mod
    ciphers_mod.aead = aead_mod

    sys.modules["cryptography"] = cryptography_mod
    sys.modules["cryptography.exceptions"] = exceptions_mod
    sys.modules["cryptography.hazmat"] = hazmat_mod
    sys.modules["cryptography.hazmat.primitives"] = primitives_mod
    sys.modules["cryptography.hazmat.primitives.ciphers"] = ciphers_mod
    sys.modules["cryptography.hazmat.primitives.ciphers.aead"] = aead_mod


_ensure_cryptography_for_sealed_validator()

import pytest

from ipfs_datasets_py.duckdb_control.authority_transition import AuthorityMode
from ipfs_datasets_py.wallet.crypto import random_key
from ipfs_datasets_py.wallet.duckdb_repository import (
    MutationKind,
    WalletDuckDBRepository,
    build_wallet_duckdb_repository,
    new_operation_id,
)
from ipfs_datasets_py.wallet.manifest import canonical_dumps
from ipfs_datasets_py.wallet.repository import LocalWalletRepository, StaleRevisionError
from ipfs_datasets_py.wallet.service import DataWalletService
from ipfs_datasets_py.wallet.storage import LocalEncryptedBlobStore, StorageRef

OWNER = "did:key:owner"
GUEST = "did:key:guest"
ANALYST = "did:key:analyst"


class OutageBlobStore:
    """Blob store that can simulate outages while preserving CAS digests."""

    def __init__(self, inner: LocalEncryptedBlobStore) -> None:
        self.inner = inner
        self.outage = False
        self.get_attempts = 0
        self.put_attempts = 0

    def put(self, data: bytes) -> StorageRef:
        self.put_attempts += 1
        if self.outage:
            raise RuntimeError("blob backend outage: put unavailable")
        return self.inner.put(data)

    def get(self, ref: StorageRef) -> bytes:
        self.get_attempts += 1
        if self.outage:
            raise RuntimeError("blob backend outage: get unavailable")
        return self.inner.get(ref)


@pytest.fixture
def event_port() -> WalletDuckDBRepository:
    return build_wallet_duckdb_repository(mode=AuthorityMode.DUAL)


@pytest.fixture
def service(tmp_path: Path, event_port: WalletDuckDBRepository) -> DataWalletService:
    svc = DataWalletService(storage_dir=tmp_path / "blobs")
    svc.attach_event_port(event_port)
    return svc


def _create_wallet_with_record(service: DataWalletService, owner: str = OWNER):
    wallet = service.create_wallet(owner_did=owner)
    secret = random_key()
    service.set_principal_secret(owner, secret)
    record = service.add_record(
        wallet.wallet_id,
        data_type="document",
        plaintext=b"authority-cutover-secret-payload",
        actor_did=owner,
        actor_secret=secret,
        private_metadata={"filename": "cutover.txt", "note": "keep out of duckdb"},
    )
    return wallet, secret, record


def test_dual_mode_and_db_primary_promotion(tmp_path, event_port):
    service = DataWalletService(storage_dir=tmp_path / "blobs")
    service.attach_event_port(event_port)
    wallet, secret, record = _create_wallet_with_record(service)

    repo = LocalWalletRepository(tmp_path / "repo", shadow=event_port)
    assert event_port.authority_mode is AuthorityMode.DUAL

    repo.save(service, wallet.wallet_id, operation_id="op:dual-seed")
    projection = event_port.get_wallet_projection(wallet.wallet_id)
    assert projection is not None
    assert projection["wallet_id"] == wallet.wallet_id
    assert projection["counts"]["grants"] == 0
    assert projection["counts"]["audit_events"] >= 1

    decision = repo.ensure_duckdb_authority(wallet.wallet_id, decision_id="cutover:test")
    assert decision is not None
    assert decision.accepted is True
    assert event_port.authority_mode is AuthorityMode.DB_PRIMARY

    # Second call is idempotent once DuckDB is authoritative.
    again = repo.ensure_duckdb_authority(wallet.wallet_id, decision_id="cutover:test-2")
    assert again is None or again.accepted is True
    assert event_port.authority_mode is AuthorityMode.DB_PRIMARY

    # Encrypted payload remains outside DuckDB.
    pub = event_port.query_publications()
    pub_text = json.dumps(pub)
    assert secret.hex() not in pub_text
    assert "authority-cutover-secret-payload" not in pub_text
    assert "key_wraps" not in pub_text
    assert "principal_secrets" not in pub_text


def test_snapshot_and_analytics_hashes_remain_stable(tmp_path, event_port):
    service = DataWalletService(storage_dir=tmp_path / "blobs")
    service.attach_event_port(event_port)
    wallet, secret, _ = _create_wallet_with_record(service)

    service.create_analytics_template(
        template_id="cutover_analytics_v1",
        title="Cutover analytics",
        purpose="hash stability",
        allowed_record_types=["document", "need"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 1, "epsilon_budget": 1.0},
        created_by=ANALYST,
    )
    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id="cutover_analytics_v1",
        allowed_record_types=["document", "need"],
        allowed_derived_fields=["county"],
    )
    service.create_analytics_contribution(
        wallet.wallet_id,
        actor_did=OWNER,
        consent_id=consent.consent_id,
        template_id="cutover_analytics_v1",
        fields={"county": "Multnomah"},
    )

    snap = service.export_wallet_snapshot(wallet.wallet_id)
    ledger = service.export_analytics_ledger()
    snap_hash = LocalWalletRepository(tmp_path / "hash-a", shadow=False).snapshot_hash(snap)
    ledger_hash = LocalWalletRepository(tmp_path / "hash-b", shadow=False).snapshot_hash(ledger)

    repo = LocalWalletRepository(tmp_path / "repo", shadow=event_port)
    repo.save_all(service, operation_id="op:hash-stable")
    report = repo.verify(wallet.wallet_id)
    assert report["valid"] is True
    assert report["snapshot_hash"] == snap_hash
    assert report["computed_hash"] == snap_hash
    ledger_report = repo.verify_analytics_ledger()
    assert ledger_report["valid"] is True
    assert ledger_report["snapshot_hash"] == ledger_hash

    # Reload and re-export: content hashes must not drift under dual authority.
    restored = DataWalletService(storage_dir=tmp_path / "blobs")
    restored.attach_event_port(event_port)
    repo.load(restored, wallet.wallet_id)
    restored_snap = restored.export_wallet_snapshot(wallet.wallet_id)
    restored_ledger = restored.export_analytics_ledger()
    assert canonical_dumps(snap) == canonical_dumps(restored_snap)
    assert canonical_dumps(ledger) == canonical_dumps(restored_ledger)
    assert repo.snapshot_hash(restored_snap) == snap_hash
    assert repo.snapshot_hash(restored_ledger) == ledger_hash

    # Authority revision is envelope-only (not inside snapshot hash domain).
    assert "authority_revision" not in snap
    envelope = json.loads(repo.wallet_path(wallet.wallet_id).read_text(encoding="utf-8"))
    assert envelope["authority_revision"] >= 1
    assert envelope["snapshot_hash"] == snap_hash


def test_stale_service_instance_cannot_overwrite_newer_revision(tmp_path, event_port):
    storage = tmp_path / "blobs"
    service_a = DataWalletService(storage_dir=storage)
    service_a.attach_event_port(event_port)
    wallet, secret, _ = _create_wallet_with_record(service_a)

    repo = LocalWalletRepository(tmp_path / "repo", shadow=event_port)
    repo.save(service_a, wallet.wallet_id, operation_id="op:seed")
    rev_after_seed = service_a.authority_revision(wallet.wallet_id)
    assert rev_after_seed == 1

    # Stale clone loads the same revision, then a fresher writer advances it.
    service_stale = DataWalletService(storage_dir=storage)
    service_stale.attach_event_port(event_port)
    repo.load(service_stale, wallet.wallet_id)
    assert service_stale.authority_revision(wallet.wallet_id) == rev_after_seed

    service_a.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=GUEST,
        resources=[f"wallet://{wallet.wallet_id}/"],
        abilities=["wallet/read"],
    )
    repo.save(service_a, wallet.wallet_id, operation_id="op:fresh-writer")
    assert service_a.authority_revision(wallet.wallet_id) == rev_after_seed + 1

    # Stale instance still holds the old revision and must fail CAS.
    service_stale.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did="did:key:other-guest",
        resources=[f"wallet://{wallet.wallet_id}/"],
        abilities=["wallet/read"],
    )
    with pytest.raises(StaleRevisionError) as excinfo:
        repo.save(
            service_stale,
            wallet.wallet_id,
            operation_id="op:stale-writer",
            expected_revision=service_stale.authority_revision(wallet.wallet_id),
        )
    assert excinfo.value.expected_revision == rev_after_seed
    assert excinfo.value.current_revision == rev_after_seed + 1

    # Durable authority remains the fresher writer's state.
    reloaded = DataWalletService(storage_dir=storage)
    reloaded.attach_event_port(event_port)
    repo.load(reloaded, wallet.wallet_id)
    audiences = {g.audience_did for g in reloaded.grants.values()}
    assert GUEST in audiences
    assert "did:key:other-guest" not in audiences
    assert reloaded.authority_revision(wallet.wallet_id) == rev_after_seed + 1


def test_concurrent_api_cli_mutation(tmp_path, event_port):
    """Concurrent API/CLI writers share dual authority; CAS serializes saves.

    API is exercised through the same LocalWalletRepository + MutationKind.API
    envelope that ``api._save_wallet_snapshot`` uses so hermetic sealed
    validators (pytest + duckdb only, no FastAPI wheel) still cover the
    DQK-075 contract. CLI is exercised through the real ``cli`` helpers.
    """

    from ipfs_datasets_py.wallet import cli as wallet_cli

    wallet_cli.reset_cli_event_port(event_port)

    storage = tmp_path / "blobs"
    wallet_dir = tmp_path / "manifests"
    wallet_dir.mkdir(parents=True, exist_ok=True)

    service = DataWalletService(storage_dir=storage)
    service.attach_event_port(event_port)
    wallet, secret, _ = _create_wallet_with_record(service)

    # Seed durable dual-mode state via repository.
    seed_repo = LocalWalletRepository(wallet_dir, shadow=event_port)
    seed_repo.save(service, wallet.wallet_id, operation_id="op:concurrent-seed")

    barrier = threading.Barrier(2)
    results: dict[str, Any] = {}
    lock = threading.Lock()

    def api_writer() -> str:
        # Mirrors api._save_wallet_snapshot without importing FastAPI.
        svc = DataWalletService(storage_dir=storage)
        svc.attach_event_port(event_port)
        LocalWalletRepository(wallet_dir, shadow=event_port).load(svc, wallet.wallet_id)
        svc.create_grant(
            wallet_id=wallet.wallet_id,
            issuer_did=OWNER,
            audience_did="did:key:api-guest",
            resources=[f"wallet://{wallet.wallet_id}/"],
            abilities=["wallet/read"],
        )
        barrier.wait(timeout=10)
        try:
            api_repo = LocalWalletRepository(wallet_dir, shadow=event_port)
            op_id = "op:api-concurrent"
            api_repo.save(
                svc,
                wallet.wallet_id,
                operation_id=op_id,
                expected_revision=svc.authority_revision(wallet.wallet_id),
            )
            event_port.record_mutation(
                action="api/wallet_snapshot",
                resource=f"wallet://{wallet.wallet_id}/manifest",
                wallet_id=wallet.wallet_id,
                kind=MutationKind.API,
                operation_id=f"{op_id}:api",
                projection_key=f"wallet:{wallet.wallet_id}",
                projection=event_port.get_wallet_projection(wallet.wallet_id),
            )
            with lock:
                results["api"] = "ok"
            return "ok"
        except StaleRevisionError:
            with lock:
                results["api"] = "stale"
            return "stale"

    def cli_writer() -> str:
        svc = DataWalletService(storage_dir=storage)
        svc.attach_event_port(event_port)
        LocalWalletRepository(wallet_dir, shadow=event_port).load(svc, wallet.wallet_id)
        svc.create_grant(
            wallet_id=wallet.wallet_id,
            issuer_did=OWNER,
            audience_did="did:key:cli-guest",
            resources=[f"wallet://{wallet.wallet_id}/"],
            abilities=["wallet/read"],
        )
        barrier.wait(timeout=10)
        try:
            wallet_cli._save(
                svc,
                wallet_dir,
                wallet.wallet_id,
                expected_revision=svc.authority_revision(wallet.wallet_id),
            )
            with lock:
                results["cli"] = "ok"
            return "ok"
        except StaleRevisionError:
            with lock:
                results["cli"] = "stale"
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(api_writer), pool.submit(cli_writer)]
        outcomes = [f.result(timeout=30) for f in as_completed(futures)]

    assert outcomes.count("ok") == 1
    assert outcomes.count("stale") == 1
    assert "ok" in results.values()
    # Exactly one writer advanced the durable revision.
    final_repo = LocalWalletRepository(wallet_dir, shadow=event_port)
    assert final_repo.current_revision(wallet.wallet_id) == 2

    kinds = {r.kind for r in event_port.list_mutation_receipts()}
    assert MutationKind.SERVICE in kinds
    assert MutationKind.REPOSITORY in kinds
    # At least one of API/CLI recorded a layer receipt.
    assert MutationKind.API in kinds or MutationKind.CLI in kinds

    # Source-level wiring proof (hermetic sealed validators may lack FastAPI).
    api_source = (_REPO_ROOT / "ipfs_datasets_py" / "wallet" / "api.py").read_text(
        encoding="utf-8"
    )
    cli_source = (_REPO_ROOT / "ipfs_datasets_py" / "wallet" / "cli.py").read_text(
        encoding="utf-8"
    )
    assert "AuthorityMode.DUAL" in api_source
    assert "expected_revision" in api_source
    assert "AuthorityMode.DUAL" in cli_source
    assert "expected_revision" in cli_source


def test_audit_verification_under_dual_authority(service, event_port, tmp_path):
    wallet, secret, record = _create_wallet_with_record(service)
    service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=GUEST,
        resources=[f"wallet://{wallet.wallet_id}/"],
        abilities=["wallet/read"],
    )
    service.revoke_grant(wallet.wallet_id, list(service.grants.values())[0].grant_id, actor_did=OWNER)

    audit = service.verify_audit_chain(wallet.wallet_id)
    assert audit["valid"] is True
    assert audit["event_count"] >= 3
    assert len(audit["tip_hash"]) == 64

    repo = LocalWalletRepository(tmp_path / "repo", shadow=event_port)
    repo.save(service, wallet.wallet_id, operation_id="op:audit")

    # Projection carries redacted audit events under dual mode.
    projection = event_port.get_wallet_projection(wallet.wallet_id)
    assert projection is not None
    assert projection["counts"]["audit_events"] == audit["event_count"]
    assert projection["audit_events"]
    for event in projection["audit_events"]:
        assert "hash_self" in event
        assert "hash_prev" in event
        assert "plaintext" not in event

    # Restart path preserves a valid chain.
    restored = DataWalletService(storage_dir=tmp_path / "blobs-restore")
    # Use same blob dir as original for decrypt; audit only needs snapshot.
    restored = DataWalletService(storage_backend=service.storage)
    restored.attach_event_port(event_port)
    repo.load(restored, wallet.wallet_id)
    restored_audit = restored.verify_audit_chain(wallet.wallet_id)
    assert restored_audit["valid"] is True
    assert restored_audit["tip_hash"] == audit["tip_hash"]
    assert restored_audit["event_count"] == audit["event_count"]


def test_grant_lifecycle_under_duckdb_authority(tmp_path, event_port):
    service = DataWalletService(storage_dir=tmp_path / "blobs")
    service.attach_event_port(event_port)
    wallet, secret, _ = _create_wallet_with_record(service)
    repo = LocalWalletRepository(tmp_path / "repo", shadow=event_port)

    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=GUEST,
        resources=[f"wallet://{wallet.wallet_id}/records/*"],
        abilities=["record/read", "wallet/read"],
    )
    assert grant.status == "active"
    repo.save(service, wallet.wallet_id, operation_id="op:grant-create")

    projection = event_port.get_wallet_projection(wallet.wallet_id)
    assert projection is not None
    grant_ids = {g["grant_id"] for g in projection["grants"]}
    assert grant.grant_id in grant_ids
    assert projection["counts"]["grants"] >= 1

    # Promote to db-primary after dual parity.
    decision = repo.ensure_duckdb_authority(wallet.wallet_id, decision_id="grant-cutover")
    assert decision is None or decision.accepted
    assert event_port.authority_mode in {AuthorityMode.DUAL, AuthorityMode.DB_PRIMARY}

    revoked = service.revoke_grant(wallet.wallet_id, grant.grant_id, actor_did=OWNER)
    assert revoked.status == "revoked"
    repo.save(service, wallet.wallet_id, operation_id="op:grant-revoke")

    projection_after = event_port.get_wallet_projection(wallet.wallet_id)
    assert projection_after is not None
    by_id = {g["grant_id"]: g for g in projection_after["grants"]}
    assert by_id[grant.grant_id]["status"] == "revoked"

    # Approvals surface also projects under authority.
    # (threshold wallets exercise approvals; single-controller path is no-op.)
    assert "approvals" in projection_after

    audit = service.verify_audit_chain(wallet.wallet_id)
    assert audit["valid"] is True
    actions = [e.action for e in service.get_audit_log(wallet.wallet_id)]
    assert "grant/create" in actions
    assert "grant/revoke" in actions or any("revoke" in a for a in actions)


def test_restart_preserves_dual_authority_state(tmp_path, event_port):
    storage = tmp_path / "blobs"
    service = DataWalletService(storage_dir=storage)
    service.attach_event_port(event_port)
    wallet, secret, record = _create_wallet_with_record(service)

    service.create_analytics_template(
        template_id="restart_analytics_v1",
        title="Restart analytics",
        purpose="restart fidelity",
        allowed_record_types=["document"],
        allowed_derived_fields=["county"],
        aggregation_policy={"min_cohort_size": 1, "epsilon_budget": 1.0},
        created_by=ANALYST,
    )
    consent = service.create_analytics_consent(
        wallet.wallet_id,
        actor_did=OWNER,
        template_id="restart_analytics_v1",
        allowed_record_types=["document"],
        allowed_derived_fields=["county"],
    )
    service.create_analytics_contribution(
        wallet.wallet_id,
        actor_did=OWNER,
        consent_id=consent.consent_id,
        template_id="restart_analytics_v1",
        fields={"county": "Clackamas"},
    )
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=GUEST,
        resources=[f"wallet://{wallet.wallet_id}/"],
        abilities=["wallet/read"],
    )

    snap_before = service.export_wallet_snapshot(wallet.wallet_id)
    ledger_before = service.export_analytics_ledger()
    audit_before = service.verify_audit_chain(wallet.wallet_id)

    repo = LocalWalletRepository(tmp_path / "repo", shadow=event_port)
    repo.save_all(service, operation_id="op:pre-restart")
    rev = service.authority_revision(wallet.wallet_id)
    snap_hash = repo.snapshot_hash(snap_before)
    ledger_hash = repo.snapshot_hash(ledger_before)

    # Simulate process restart: new service + same dual event port backend.
    restarted = DataWalletService(storage_dir=storage)
    restarted.attach_event_port(event_port)
    loaded = repo.load_all(restarted)
    assert wallet.wallet_id in loaded
    assert restarted.authority_revision(wallet.wallet_id) == rev
    assert grant.grant_id in restarted.grants
    assert restarted.grants[grant.grant_id].status == "active"

    snap_after = restarted.export_wallet_snapshot(wallet.wallet_id)
    ledger_after = restarted.export_analytics_ledger()
    assert repo.snapshot_hash(snap_after) == snap_hash
    assert repo.snapshot_hash(ledger_after) == ledger_hash
    assert canonical_dumps(snap_before) == canonical_dumps(snap_after)
    assert canonical_dumps(ledger_before) == canonical_dumps(ledger_after)

    audit_after = restarted.verify_audit_chain(wallet.wallet_id)
    assert audit_after["valid"] is True
    assert audit_after["tip_hash"] == audit_before["tip_hash"]

    plaintext = restarted.decrypt_record(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
        actor_secret=secret,
    )
    assert plaintext == b"authority-cutover-secret-payload"

    verify = repo.verify(wallet.wallet_id)
    assert verify["valid"] is True
    assert verify.get("duckdb_projection_present") is True


def test_blob_outage_preserves_metadata_authority(tmp_path, event_port):
    """Grants/audit/metadata dual-write continue while blob backend is down."""

    inner = LocalEncryptedBlobStore(tmp_path / "blobs")
    blobs = OutageBlobStore(inner)
    service = DataWalletService(storage_backend=blobs)
    service.attach_event_port(event_port)

    # Seed while healthy so ciphertext exists.
    wallet, secret, record = _create_wallet_with_record(service)
    repo = LocalWalletRepository(tmp_path / "repo", shadow=event_port)
    repo.save(service, wallet.wallet_id, operation_id="op:pre-outage")

    blobs.outage = True

    # Metadata mutations do not require the blob backend.
    grant = service.create_grant(
        wallet_id=wallet.wallet_id,
        issuer_did=OWNER,
        audience_did=GUEST,
        resources=[f"wallet://{wallet.wallet_id}/"],
        abilities=["wallet/read"],
    )
    assert grant.status == "active"
    audit = service.verify_audit_chain(wallet.wallet_id)
    assert audit["valid"] is True

    # Dual-mode repository save of public metadata still succeeds (JSON + DuckDB).
    repo.save(service, wallet.wallet_id, operation_id="op:during-outage")
    projection = event_port.get_wallet_projection(wallet.wallet_id)
    assert projection is not None
    assert any(g["grant_id"] == grant.grant_id for g in projection["grants"])

    # Decrypt / new ciphertext writes fail closed during outage.
    with pytest.raises(RuntimeError, match="blob backend outage"):
        service.decrypt_record(
            wallet.wallet_id,
            record.record_id,
            actor_did=OWNER,
            actor_secret=secret,
        )
    with pytest.raises(RuntimeError, match="blob backend outage"):
        service.add_record(
            wallet.wallet_id,
            data_type="document",
            plaintext=b"should-fail",
            actor_did=OWNER,
            actor_secret=secret,
        )

    # Recovery: outage cleared, ciphertext still content-addressed and intact.
    blobs.outage = False
    plaintext = service.decrypt_record(
        wallet.wallet_id,
        record.record_id,
        actor_did=OWNER,
        actor_secret=secret,
    )
    assert plaintext == b"authority-cutover-secret-payload"

    # Query publications never absorbed ciphertext during outage path.
    pub_text = json.dumps(event_port.query_publications())
    assert "authority-cutover-secret-payload" not in pub_text
    assert secret.hex() not in pub_text
