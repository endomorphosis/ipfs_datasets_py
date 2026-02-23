"""Tests: DID Key Manager + Secrets Vault (v13).

Covers:
- DIDKeyManager: generate, persist, load, export_secret_b64, rotate_key,
  mint_delegation (async), verify_delegation (async), mint_self_delegation,
  stub mode when py-ucan absent, singleton factory.
- SecretsVault: set/get/delete/list_names, encrypt+decrypt roundtrip,
  load_into_env (overwrite=False/True), vault file created with 0o600 perms,
  missing vault file → empty vault, info(), singleton factory.
- engine_env: _get_from_vault returns vault value; autoconfigure_engine_env
  pulls OPENAI_API_KEY from vault when env var absent.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ── optional dep guards ────────────────────────────────────────────────────

try:
    import ucan as _ucan_lib  # noqa: F401
    _UCAN_OK = True
except ImportError:
    _UCAN_OK = False

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
    _CRYPTO_OK = True
except ImportError:
    _CRYPTO_OK = False

_skip_no_ucan = pytest.mark.skipif(not _UCAN_OK, reason="py-ucan not installed")
_skip_no_crypto = pytest.mark.skipif(not _CRYPTO_OK, reason="cryptography not installed")
_skip_no_both = pytest.mark.skipif(
    not (_UCAN_OK and _CRYPTO_OK),
    reason="py-ucan and cryptography required",
)

# ── helpers ────────────────────────────────────────────────────────────────

def _tmp_key_file(tmp_path: Path) -> Path:
    return tmp_path / "test_did_key.json"


def _tmp_vault_file(tmp_path: Path) -> Path:
    return tmp_path / "test_secrets_vault.json"


# ══════════════════════════════════════════════════════════════════════════════
# DIDKeyManager
# ══════════════════════════════════════════════════════════════════════════════


class TestDIDKeyManagerGeneration:
    """Key generation and persistence."""

    @_skip_no_ucan
    def test_generates_did_key_string(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        assert mgr.did is not None
        assert mgr.did.startswith("did:key:z6Mk"), f"unexpected DID: {mgr.did}"

    @_skip_no_ucan
    def test_key_file_created_on_disk(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        kf = _tmp_key_file(tmp_path)
        assert not kf.exists()
        DIDKeyManager(key_file=kf)
        assert kf.exists()

    @_skip_no_ucan
    def test_key_file_contains_did_and_version(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        kf = _tmp_key_file(tmp_path)
        mgr = DIDKeyManager(key_file=kf)
        data = json.loads(kf.read_text())
        assert data["version"] == 1
        assert data["did"] == mgr.did
        assert "private_key_base64url" in data
        assert data["algorithm"] == "Ed25519"

    @_skip_no_ucan
    def test_key_file_has_restricted_permissions(self, tmp_path):
        """Key file should be owner-readable only (0o600)."""
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        kf = _tmp_key_file(tmp_path)
        DIDKeyManager(key_file=kf)
        mode = oct(kf.stat().st_mode)[-3:]
        assert mode == "600", f"expected 600, got {mode}"

    @_skip_no_ucan
    def test_reload_produces_same_did(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        kf = _tmp_key_file(tmp_path)
        mgr1 = DIDKeyManager(key_file=kf)
        did1 = mgr1.did
        mgr2 = DIDKeyManager(key_file=kf)
        assert mgr2.did == did1

    @_skip_no_ucan
    def test_export_secret_b64_is_string(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        b64 = mgr.export_secret_b64()
        assert isinstance(b64, str)
        assert len(b64) > 10  # base64url of 32 bytes

    @_skip_no_ucan
    def test_rotate_key_changes_did(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        did1 = mgr.did
        new_did = mgr.rotate_key()
        assert new_did != did1
        assert mgr.did == new_did

    @_skip_no_ucan
    def test_info_dict_has_required_keys(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        info = mgr.info()
        assert "did" in info
        assert "key_file" in info
        assert "ucan_available" in info
        assert info["ucan_available"] is True

    @_skip_no_ucan
    def test_ucan_available_property(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        assert mgr.ucan_available is True

    def test_stub_mode_when_ucan_absent(self, tmp_path):
        """When py-ucan is not installed, DIDKeyManager operates as a stub."""
        import importlib
        import ipfs_datasets_py.mcp_server.did_key_manager as did_mod

        with patch.dict("sys.modules", {"ucan": None}):
            importlib.reload(did_mod)
            mgr = did_mod.DIDKeyManager(key_file=_tmp_key_file(tmp_path))
            assert mgr.did is not None  # returns stub DID
            assert "stub" in mgr.did or mgr.did.startswith("did:")
            assert mgr.ucan_available is False

        # Restore module state: reload AFTER patch.dict context has restored sys.modules
        importlib.reload(did_mod)


class TestDIDKeyManagerDelegation:
    """UCAN delegation minting and verification."""

    @_skip_no_ucan
    def test_mint_delegation_returns_jwt_string(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        import ucan as _ucan

        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        aud_kp = _ucan.EdKeypair.generate()

        token = asyncio.run(mgr.mint_delegation(
            audience_did=aud_kp.did(),
            capabilities=[("secrets://project/", "secrets/read")],
            lifetime_seconds=3600,
        ))
        assert isinstance(token, str)
        assert token.startswith("eyJ")  # JWT header

    @_skip_no_ucan
    def test_mint_self_delegation_issuer_equals_audience(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager

        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        token = asyncio.run(mgr.mint_self_delegation(
            capabilities=[("tools://admin/", "tools/invoke")],
        ))
        assert isinstance(token, str)
        # Decode the JWT payload (middle segment)
        import base64
        parts = token.split(".")
        payload_raw = parts[1] + "=="
        payload = json.loads(base64.urlsafe_b64decode(payload_raw))
        assert payload["iss"] == mgr.did
        assert payload["aud"] == mgr.did

    @_skip_no_ucan
    def test_verify_own_delegation_returns_true(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager

        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        token = asyncio.run(mgr.mint_self_delegation(
            capabilities=[("secrets://project/", "secrets/read")],
        ))
        ok = asyncio.run(mgr.verify_delegation(
            token,
            required_capabilities=[("secrets://project/", "secrets/read")],
        ))
        assert ok is True

    @_skip_no_ucan
    def test_mint_multiple_capabilities(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        import ucan as _ucan

        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        aud_kp = _ucan.EdKeypair.generate()
        token = asyncio.run(mgr.mint_delegation(
            audience_did=aud_kp.did(),
            capabilities=[
                ("secrets://project/openai", "secrets/read"),
                ("tools://admin/", "tools/invoke"),
            ],
            lifetime_seconds=600,
        ))
        assert isinstance(token, str)
        assert len(token) > 100


class TestDIDKeyManagerSingleton:
    @_skip_no_ucan
    def test_get_did_key_manager_returns_same_instance(self, tmp_path):
        from ipfs_datasets_py.mcp_server import did_key_manager as did_mod
        # Reset singleton for test isolation
        did_mod._default_manager = None
        mgr1 = did_mod.get_did_key_manager(key_file=_tmp_key_file(tmp_path))
        mgr2 = did_mod.get_did_key_manager()
        assert mgr1 is mgr2
        did_mod._default_manager = None  # clean up

    @_skip_no_ucan
    def test_get_did_key_manager_new_key_file_resets(self, tmp_path):
        from ipfs_datasets_py.mcp_server import did_key_manager as did_mod
        did_mod._default_manager = None
        kf1 = tmp_path / "key1.json"
        kf2 = tmp_path / "key2.json"
        mgr1 = did_mod.get_did_key_manager(key_file=kf1)
        mgr2 = did_mod.get_did_key_manager(key_file=kf2)
        assert mgr1 is not mgr2
        did_mod._default_manager = None


# ══════════════════════════════════════════════════════════════════════════════
# SecretsVault
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def vault_with_mgr(tmp_path):
    """Return (SecretsVault, DIDKeyManager) using tmp files."""
    if not (_UCAN_OK and _CRYPTO_OK):
        pytest.skip("py-ucan and cryptography required")
    from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
    from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
    mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
    vault = SecretsVault(vault_file=_tmp_vault_file(tmp_path), did_key_manager=mgr)
    return vault, mgr


class TestSecretsVaultCRUD:

    @_skip_no_both
    def test_set_and_get_roundtrip(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        vault.set("OPENAI_API_KEY", "sk-test-12345")
        assert vault.get("OPENAI_API_KEY") == "sk-test-12345"

    @_skip_no_both
    def test_set_writes_vault_file(self, vault_with_mgr, tmp_path):
        vault, _ = vault_with_mgr
        vault.set("ANTHROPIC_KEY", "sk-ant-test")
        assert vault.vault_file.exists()
        raw = json.loads(vault.vault_file.read_text())
        assert "ANTHROPIC_KEY" in raw["secrets"]
        # Value must be encrypted (not plaintext)
        assert raw["secrets"]["ANTHROPIC_KEY"]["ciphertext_b64"] != "sk-ant-test"

    @_skip_no_both
    def test_vault_file_has_restricted_permissions(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        vault.set("SOME_KEY", "val")
        mode = oct(vault.vault_file.stat().st_mode)[-3:]
        assert mode == "600"

    @_skip_no_both
    def test_get_missing_secret_returns_none(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        assert vault.get("NONEXISTENT_KEY") is None

    @_skip_no_both
    def test_contains_operator(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        vault.set("MY_KEY", "my-value")
        assert "MY_KEY" in vault
        assert "OTHER_KEY" not in vault

    @_skip_no_both
    def test_list_names_returns_stored_keys(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        vault.set("K1", "v1")
        vault.set("K2", "v2")
        names = vault.list_names()
        assert "K1" in names
        assert "K2" in names

    @_skip_no_both
    def test_delete_removes_secret(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        vault.set("DEL_KEY", "will-be-removed")
        assert vault.delete("DEL_KEY") is True
        assert vault.get("DEL_KEY") is None

    @_skip_no_both
    def test_delete_nonexistent_returns_false(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        assert vault.delete("GHOST_KEY") is False

    @_skip_no_both
    def test_len_reflects_secret_count(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        assert len(vault) == 0
        vault.set("A", "1")
        vault.set("B", "2")
        assert len(vault) == 2
        vault.delete("A")
        assert len(vault) == 1

    @_skip_no_both
    def test_iter_yields_names(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        vault.set("X", "x")
        vault.set("Y", "y")
        names = list(vault)
        assert set(names) == {"X", "Y"}

    @_skip_no_both
    def test_set_empty_value_raises(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        with pytest.raises(ValueError):
            vault.set("EMPTY", "")

    @_skip_no_both
    def test_multiple_secrets_distinct_ciphertexts(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        vault.set("S1", "same-plaintext")
        vault.set("S2", "same-plaintext")
        raw = json.loads(vault.vault_file.read_text())
        # Different nonces → different ciphertexts
        ct1 = raw["secrets"]["S1"]["ciphertext_b64"]
        ct2 = raw["secrets"]["S2"]["ciphertext_b64"]
        assert ct1 != ct2, "Same plaintext should produce different ciphertexts (random nonces)"


class TestSecretsVaultPersistence:

    @_skip_no_both
    def test_reload_vault_from_disk_decrypts_correctly(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        kf = _tmp_key_file(tmp_path)
        vf = _tmp_vault_file(tmp_path)
        mgr = DIDKeyManager(key_file=kf)
        vault1 = SecretsVault(vault_file=vf, did_key_manager=mgr)
        vault1.set("RELOAD_KEY", "my-secret-value")
        # Create a new vault instance pointing at same files
        mgr2 = DIDKeyManager(key_file=kf)
        vault2 = SecretsVault(vault_file=vf, did_key_manager=mgr2)
        assert vault2.get("RELOAD_KEY") == "my-secret-value"

    @_skip_no_both
    def test_missing_vault_file_gives_empty_vault(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        vf = tmp_path / "nonexistent_vault.json"
        vault = SecretsVault(vault_file=vf, did_key_manager=mgr)
        assert len(vault) == 0

    @_skip_no_both
    def test_vault_did_recorded_in_file(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        kf = _tmp_key_file(tmp_path)
        mgr = DIDKeyManager(key_file=kf)
        vault = SecretsVault(vault_file=_tmp_vault_file(tmp_path), did_key_manager=mgr)
        vault.set("DID_RECORD_KEY", "x")
        raw = json.loads(vault.vault_file.read_text())
        assert raw.get("did") == mgr.did


class TestSecretsVaultEnvIntegration:

    @_skip_no_both
    def test_load_into_env_injects_secret(self, vault_with_mgr, monkeypatch):
        vault, _ = vault_with_mgr
        monkeypatch.delenv("VAULT_TEST_KEY", raising=False)
        vault.set("VAULT_TEST_KEY", "test-secret-value")
        injected = vault.load_into_env()
        assert "VAULT_TEST_KEY" in injected
        assert os.environ.get("VAULT_TEST_KEY") == "test-secret-value"
        monkeypatch.delenv("VAULT_TEST_KEY", raising=False)

    @_skip_no_both
    def test_load_into_env_does_not_overwrite_by_default(self, vault_with_mgr, monkeypatch):
        vault, _ = vault_with_mgr
        monkeypatch.setenv("NO_OVERWRITE_KEY", "original")
        vault.set("NO_OVERWRITE_KEY", "vault-value")
        vault.load_into_env(overwrite=False)
        assert os.environ["NO_OVERWRITE_KEY"] == "original"

    @_skip_no_both
    def test_load_into_env_overwrites_when_requested(self, vault_with_mgr, monkeypatch):
        vault, _ = vault_with_mgr
        monkeypatch.setenv("OVERWRITE_KEY", "original")
        vault.set("OVERWRITE_KEY", "vault-value")
        vault.load_into_env(overwrite=True)
        assert os.environ["OVERWRITE_KEY"] == "vault-value"
        monkeypatch.delenv("OVERWRITE_KEY", raising=False)

    @_skip_no_both
    def test_load_into_env_returns_injected_names(self, vault_with_mgr, monkeypatch):
        vault, _ = vault_with_mgr
        monkeypatch.delenv("INJECTME", raising=False)
        vault.set("INJECTME", "yes")
        result = vault.load_into_env()
        assert "INJECTME" in result
        monkeypatch.delenv("INJECTME", raising=False)


class TestSecretsVaultInfo:

    @_skip_no_both
    def test_info_dict_keys(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        info = vault.info()
        assert "vault_file" in info
        assert "secret_count" in info
        assert "secret_names" in info
        assert "crypto_available" in info
        assert info["crypto_available"] is True

    @_skip_no_both
    def test_repr_contains_vault_file(self, vault_with_mgr):
        vault, _ = vault_with_mgr
        r = repr(vault)
        assert "SecretsVault" in r

    @_skip_no_both
    def test_singleton_factory(self, tmp_path):
        from ipfs_datasets_py.mcp_server import secrets_vault as sv_mod
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        vf = _tmp_vault_file(tmp_path)
        sv_mod._default_vault = None
        v1 = sv_mod.get_secrets_vault(vault_file=vf)
        # Inject a known manager so the vault is fully operational
        v1._mgr = mgr
        v2 = sv_mod.get_secrets_vault()  # same file, should return cached singleton
        assert v1 is v2
        sv_mod._default_vault = None  # clean up


# ══════════════════════════════════════════════════════════════════════════════
# engine_env integration
# ══════════════════════════════════════════════════════════════════════════════


class TestEngineEnvVaultIntegration:

    @_skip_no_both
    def test_get_from_vault_returns_stored_secret(self, tmp_path, monkeypatch):
        """_get_from_vault should delegate to SecretsVault.get()."""
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        import ipfs_datasets_py.mcp_server.secrets_vault as sv_mod
        import ipfs_datasets_py.utils.engine_env as ee_mod

        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        vault = SecretsVault(vault_file=_tmp_vault_file(tmp_path), did_key_manager=mgr)
        vault.set("VAULT_PROBE_KEY", "vault-probe-value")
        sv_mod._default_vault = vault

        value = ee_mod._get_from_vault("VAULT_PROBE_KEY")
        assert value == "vault-probe-value"
        sv_mod._default_vault = None

    @_skip_no_both
    def test_get_from_vault_returns_none_for_missing(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        import ipfs_datasets_py.mcp_server.secrets_vault as sv_mod
        import ipfs_datasets_py.utils.engine_env as ee_mod

        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        vault = SecretsVault(vault_file=_tmp_vault_file(tmp_path), did_key_manager=mgr)
        sv_mod._default_vault = vault

        value = ee_mod._get_from_vault("NONEXISTENT_VAULT_KEY")
        assert value is None
        sv_mod._default_vault = None

    @_skip_no_both
    def test_autoconfigure_reads_openai_key_from_vault(self, tmp_path, monkeypatch):
        """autoconfigure_engine_env should pull OPENAI_API_KEY from vault."""
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        import ipfs_datasets_py.mcp_server.secrets_vault as sv_mod
        import ipfs_datasets_py.utils.engine_env as ee_mod

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_KEY", raising=False)
        monkeypatch.delenv("OPENAI_TOKEN", raising=False)

        mgr = DIDKeyManager(key_file=_tmp_key_file(tmp_path))
        vault = SecretsVault(vault_file=_tmp_vault_file(tmp_path), did_key_manager=mgr)
        vault.set("OPENAI_API_KEY", "sk-vault-test-key-9999")
        sv_mod._default_vault = vault

        changed = ee_mod.autoconfigure_engine_env(allow_keyring=False, allow_vault=True)

        assert os.environ.get("OPENAI_API_KEY") == "sk-vault-test-key-9999"
        assert "OPENAI_API_KEY" in changed

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        sv_mod._default_vault = None

    def test_autoconfigure_vault_disabled_does_not_read_vault(self, tmp_path, monkeypatch):
        """With allow_vault=False, vault should not be consulted."""
        import ipfs_datasets_py.utils.engine_env as ee_mod

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_KEY", raising=False)
        monkeypatch.delenv("OPENAI_TOKEN", raising=False)

        with patch("ipfs_datasets_py.utils.engine_env._get_from_vault") as mock_vault:
            mock_vault.return_value = "should-not-be-used"
            ee_mod.autoconfigure_engine_env(allow_keyring=False, allow_vault=False)
            mock_vault.assert_not_called()

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    @_skip_no_both
    def test_get_from_vault_returns_none_on_import_error(self):
        """_get_from_vault must not raise when secrets_vault is absent."""
        import ipfs_datasets_py.utils.engine_env as ee_mod

        with patch("ipfs_datasets_py.utils.engine_env._get_from_vault") as mock_v:
            mock_v.return_value = None
            result = ee_mod._get_from_vault("ANY_KEY")
            assert result is None
