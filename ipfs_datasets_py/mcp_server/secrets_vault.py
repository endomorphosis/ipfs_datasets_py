"""Secrets Vault — DID-key-derived AES-GCM encryption for project secrets.

This module provides :class:`SecretsVault`, which:

1. **Derives** a symmetric AES-256-GCM encryption key from the Ed25519
   private key seed stored in :class:`~ipfs_datasets_py.mcp_server.did_key_manager.DIDKeyManager`
   using HKDF-SHA256.
2. **Encrypts** and **decrypts** named secrets (e.g. ``OPENAI_API_KEY``) to/
   from an on-disk JSON vault file.
3. **Integrates** with :mod:`ipfs_datasets_py.utils.engine_env` so that API
   keys stored in the vault are automatically injected into the process
   environment when :func:`load_env_from_vault` is called.

Vault file format (JSON, path ``~/.ipfs_datasets/secrets_vault.json``)::

    {
      "version": 1,
      "did": "did:key:z6Mk...",
      "secrets": {
        "OPENAI_API_KEY": {
          "nonce_b64": "<base64>",
          "ciphertext_b64": "<base64>"
        },
        ...
      }
    }

Usage example::

    from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault

    vault = SecretsVault()
    vault.set("OPENAI_API_KEY", "sk-proj-...")
    print(vault.get("OPENAI_API_KEY"))   # "sk-proj-..."

    # Inject all vault secrets into os.environ
    vault.load_into_env()

Requirements
------------
``cryptography>=41.0.0``  (standard dep in ``security`` extra)
``py-ucan>=1.0.0``        (``ucan`` extra, for key derivation via
                           :class:`DIDKeyManager`)
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_VAULT_DIR = Path.home() / ".ipfs_datasets"
_DEFAULT_VAULT_FILE = _DEFAULT_VAULT_DIR / "secrets_vault.json"
_VAULT_FILE_ENV = "IPFS_DATASETS_SECRETS_VAULT_FILE"

# HKDF context strings — changing these invalidates existing ciphertexts
_HKDF_SALT = b"ipfs-datasets-secrets-v1"
_HKDF_INFO = b"encryption-key"


# ---------------------------------------------------------------------------
# Optional import guards
# ---------------------------------------------------------------------------

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CRYPTO_AVAILABLE = False

try:
    import ucan as _ucan_lib  # type: ignore[import-not-found]
    _UCAN_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ucan_lib = None  # type: ignore[assignment]
    _UCAN_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _b64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _b64_decode(s: str) -> bytes:
    return base64.b64decode(s)


def _derive_enc_key(private_key_b64url: str) -> bytes:
    """Derive a 32-byte AES-256-GCM key from an Ed25519 private seed.

    Parameters
    ----------
    private_key_b64url:
        Base64url-encoded 32-byte Ed25519 private key seed (the ``d`` field
        from ``EdKeypair.export()``).

    Returns
    -------
    bytes
        32-byte derived encryption key.
    """
    if not _CRYPTO_AVAILABLE:  # pragma: no cover
        raise RuntimeError("cryptography package is required for SecretsVault")
    # The py-ucan base64url seed uses standard base64 with possible padding
    # differences — use urlsafe decoder with added padding
    seed_bytes = base64.urlsafe_b64decode(private_key_b64url + "==")
    kdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    )
    return kdf.derive(seed_bytes)


# ---------------------------------------------------------------------------
# SecretsVault
# ---------------------------------------------------------------------------

class SecretsVault:
    """Encrypt and persist project secrets using a DID-derived AES-GCM key.

    Parameters
    ----------
    vault_file:
        Path to the JSON vault file.  Defaults to
        ``~/.ipfs_datasets/secrets_vault.json``, overridable via
        ``IPFS_DATASETS_SECRETS_VAULT_FILE``.
    did_key_manager:
        An optional :class:`~ipfs_datasets_py.mcp_server.did_key_manager.DIDKeyManager`
        instance.  If *None*, the module-level singleton from
        :func:`~ipfs_datasets_py.mcp_server.did_key_manager.get_did_key_manager`
        is used.
    """

    def __init__(
        self,
        vault_file: Optional[Path] = None,
        *,
        did_key_manager=None,
    ) -> None:
        env_path = os.environ.get(_VAULT_FILE_ENV)
        if vault_file is None:
            self._vault_file = Path(env_path) if env_path else _DEFAULT_VAULT_FILE
        else:
            self._vault_file = Path(vault_file)

        self._mgr = did_key_manager
        self._enc_key: Optional[bytes] = None
        self._data: Dict = {}  # in-memory vault state
        self._load_vault()

    # ------------------------------------------------------------------
    # Key derivation (lazy)
    # ------------------------------------------------------------------

    def _ensure_enc_key(self) -> bytes:
        """Lazily derive and cache the AES encryption key."""
        if self._enc_key is not None:
            return self._enc_key
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography package is required for SecretsVault")

        # Lazy import to avoid circular dep at module level
        if self._mgr is None:
            from .did_key_manager import get_did_key_manager
            self._mgr = get_did_key_manager()

        try:
            seed_b64 = self._mgr.export_secret_b64()
        except Exception as exc:
            raise RuntimeError(
                "Cannot derive encryption key: DIDKeyManager not operational"
            ) from exc

        self._enc_key = _derive_enc_key(seed_b64)
        return self._enc_key

    # ------------------------------------------------------------------
    # Vault persistence
    # ------------------------------------------------------------------

    def _load_vault(self) -> None:
        """Load vault data from disk (if the file exists)."""
        if not self._vault_file.exists():
            self._data = {"version": 1, "did": None, "secrets": {}}
            return
        try:
            raw = self._vault_file.read_text(encoding="utf-8")
            self._data = json.loads(raw)
        except Exception as exc:
            logger.warning("Could not load vault %s: %s — starting fresh", self._vault_file, exc)
            self._data = {"version": 1, "did": None, "secrets": {}}

    def _save_vault(self) -> None:
        """Persist vault data to disk."""
        # Record the DID in the vault for reference
        if self._mgr is not None:
            self._data["did"] = getattr(self._mgr, "did", None)
        self._vault_file.parent.mkdir(parents=True, exist_ok=True)
        self._vault_file.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        try:
            os.chmod(self._vault_file, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # CRUD interface
    # ------------------------------------------------------------------

    def set(self, name: str, value: str) -> None:
        """Encrypt and store a named secret.

        Parameters
        ----------
        name:
            Secret name, e.g. ``"OPENAI_API_KEY"``.
        value:
            Plaintext secret value.  Must not be empty.
        """
        if not value:
            raise ValueError("Secret value must not be empty")
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography package is required for SecretsVault")

        enc_key = self._ensure_enc_key()
        # 12-byte (96-bit) nonce: recommended size for AES-GCM; provides 2^96
        # unique nonces per key — effectively collision-free for any practical
        # number of secrets encrypted under the same derived key.
        nonce = os.urandom(12)
        aes = AESGCM(enc_key)
        ciphertext = aes.encrypt(nonce, value.encode("utf-8"), None)
        secrets = self._data.setdefault("secrets", {})
        secrets[name] = {
            "nonce_b64": _b64_encode(nonce),
            "ciphertext_b64": _b64_encode(ciphertext),
        }
        self._save_vault()

    def get(self, name: str) -> Optional[str]:
        """Decrypt and return a named secret, or *None* if not found.

        Parameters
        ----------
        name:
            Secret name.

        Returns
        -------
        str or None
        """
        if not _CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography package is required for SecretsVault")
        secrets = self._data.get("secrets", {})
        if name not in secrets:
            return None
        entry = secrets[name]
        try:
            enc_key = self._ensure_enc_key()
            nonce = _b64_decode(entry["nonce_b64"])
            ciphertext = _b64_decode(entry["ciphertext_b64"])
            aes = AESGCM(enc_key)
            plaintext = aes.decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception as exc:
            logger.error("Failed to decrypt secret %r: %s", name, exc)
            return None

    def delete(self, name: str) -> bool:
        """Remove a named secret from the vault.

        Returns *True* if the secret existed, *False* otherwise.
        """
        secrets = self._data.get("secrets", {})
        if name in secrets:
            del secrets[name]
            self._save_vault()
            return True
        return False

    def list_names(self) -> List[str]:
        """Return a list of all stored secret names (keys only, no values)."""
        return list(self._data.get("secrets", {}).keys())

    def __contains__(self, name: str) -> bool:
        return name in self._data.get("secrets", {})

    def __iter__(self) -> Iterator[str]:
        return iter(self._data.get("secrets", {}))

    def __len__(self) -> int:
        return len(self._data.get("secrets", {}))

    # ------------------------------------------------------------------
    # OS environment integration
    # ------------------------------------------------------------------

    def load_into_env(self, *, overwrite: bool = False) -> List[str]:
        """Inject all vault secrets into ``os.environ``.

        Parameters
        ----------
        overwrite:
            If *True*, existing environment variables are overwritten.
            Default: *False* (existing values are preserved).

        Returns
        -------
        list[str]
            Names of variables that were successfully injected.
        """
        injected: List[str] = []
        for name in self.list_names():
            if not overwrite and name in os.environ:
                continue
            value = self.get(name)
            if value is not None:
                os.environ[name] = value
                injected.append(name)
                logger.debug("Injected %s from vault into environment", name)
        return injected

    # ------------------------------------------------------------------
    # Info / repr
    # ------------------------------------------------------------------

    @property
    def vault_file(self) -> Path:
        """Path to the on-disk vault file."""
        return self._vault_file

    def info(self) -> dict:
        """Return non-sensitive metadata about the vault."""
        return {
            "vault_file": str(self._vault_file),
            "did": self._data.get("did"),
            "secret_count": len(self),
            "secret_names": self.list_names(),
            "crypto_available": _CRYPTO_AVAILABLE,
            "ucan_available": _UCAN_AVAILABLE,
        }

    def __repr__(self) -> str:
        return (
            f"SecretsVault(vault_file={self._vault_file!r}, "
            f"secrets={self.list_names()!r})"
        )


# ---------------------------------------------------------------------------
# Module-level singleton + convenience function
# ---------------------------------------------------------------------------

_default_vault: Optional[SecretsVault] = None


def get_secrets_vault(vault_file: Optional[Path] = None) -> SecretsVault:
    """Return the process-level singleton :class:`SecretsVault`.

    The vault is created on the first call and cached for subsequent calls.
    Pass *vault_file* to override the location (creates a new singleton).
    """
    global _default_vault
    if _default_vault is None or vault_file is not None:
        _default_vault = SecretsVault(vault_file=vault_file)
    return _default_vault


def load_env_from_vault(*, overwrite: bool = False) -> List[str]:
    """Convenience wrapper: load all vault secrets into the process environment.

    This is intended to be called early in application startup::

        from ipfs_datasets_py.mcp_server.secrets_vault import load_env_from_vault
        load_env_from_vault()

    Returns the list of variable names that were injected.
    """
    return get_secrets_vault().load_into_env(overwrite=overwrite)
