"""DID Key Manager — Ed25519 DID:key generation, persistence, and UCAN delegation minting.

This module provides the :class:`DIDKeyManager` which:

1. **Generates** an Ed25519 ``did:key`` pair and persists the private key to a
   local key-file (``~/.ipfs_datasets/did_key.json`` by default).
2. **Loads** an existing key-file on startup so the DID is stable across
   restarts.
3. **Mints UCAN delegations** — wraps ``py-ucan`` to produce signed
   ``Ucan`` tokens that grant a specific audience specific capabilities.
4. **Verifies** incoming UCAN tokens via ``py-ucan``'s async ``verify``.

Usage example::

    import asyncio
    from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager

    async def main():
        mgr = DIDKeyManager()          # loads or generates key on first call
        print("Our DID:", mgr.did)

        # Grant another agent read-access to secrets for 24 hours
        token = await mgr.mint_delegation(
            audience_did="did:key:z6MktarNT1DkKE...",
            capabilities=[("secrets://project/", "secrets/read")],
            lifetime_seconds=86_400,
        )
        print("Token:", token[:60], "...")

    asyncio.run(main())

Requirements
------------
``py-ucan>=1.0.0``  (install via ``pip install py-ucan``)
``cryptography>=41.0.0``

Both are declared in the ``ucan`` extras group in ``setup.py`` and
``__pyproject.toml``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import guard — py-ucan is an optional dependency
# ---------------------------------------------------------------------------
try:
    import ucan as _ucan_lib  # type: ignore[import-not-found]
    _UCAN_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ucan_lib = None  # type: ignore[assignment]
    _UCAN_AVAILABLE = False

_DEFAULT_KEY_DIR = Path.home() / ".ipfs_datasets"
_DEFAULT_KEY_FILE = _DEFAULT_KEY_DIR / "did_key.json"

# Environment variable that can override the key-file path
_KEY_FILE_ENV = "IPFS_DATASETS_DID_KEY_FILE"


# ---------------------------------------------------------------------------
# DIDKeyManager
# ---------------------------------------------------------------------------

class DIDKeyManager:
    """Manage a persistent Ed25519 DID:key pair and mint UCAN delegations.

    Parameters
    ----------
    key_file:
        Path to the JSON file where the private key is stored.  Defaults to
        ``~/.ipfs_datasets/did_key.json`` (overridable via the
        ``IPFS_DATASETS_DID_KEY_FILE`` environment variable).
    auto_load:
        If *True* (default), the constructor immediately loads (or generates)
        the key-pair so that :attr:`did` is available synchronously.
    """

    def __init__(
        self,
        key_file: Optional[Path] = None,
        *,
        auto_load: bool = True,
    ) -> None:
        env_path = os.environ.get(_KEY_FILE_ENV)
        if key_file is None:
            self._key_file = Path(env_path) if env_path else _DEFAULT_KEY_FILE
        else:
            self._key_file = Path(key_file)

        self._keypair: Optional[Any] = None  # ucan.EdKeypair or None
        self._did: Optional[str] = None

        if auto_load:
            self._load_or_generate_sync()

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def did(self) -> Optional[str]:
        """The ``did:key:...`` string for this manager's key pair."""
        return self._did

    @property
    def key_file(self) -> Path:
        """Path to the on-disk JSON key-store."""
        return self._key_file

    @property
    def ucan_available(self) -> bool:
        """Whether the ``py-ucan`` library was successfully imported."""
        return _UCAN_AVAILABLE and self._keypair is not None

    # ------------------------------------------------------------------
    # Key generation / persistence
    # ------------------------------------------------------------------

    def _load_or_generate_sync(self) -> None:
        """Load the key from disk or generate a new one (synchronous)."""
        if not _UCAN_AVAILABLE:
            logger.warning(
                "py-ucan is not installed — DIDKeyManager is operating in "
                "stub mode.  Install with: pip install py-ucan"
            )
            self._did = "did:key:stub-ucan-not-installed"
            return

        if self._key_file.exists():
            self._load_key()
        else:
            self._generate_and_save()

    def _generate_and_save(self) -> None:
        """Generate a new Ed25519 keypair and persist it."""
        kp = _ucan_lib.EdKeypair.generate()
        priv_model = kp.export()
        # priv_model.d is a base64url-encoded 32-byte private key seed
        data = {
            "version": 1,
            "algorithm": "Ed25519",
            "did": kp.did(),
            "private_key_base64url": priv_model.d,
        }
        self._key_file.parent.mkdir(parents=True, exist_ok=True)
        # Write with restrictive permissions (owner read/write only)
        self._key_file.write_text(json.dumps(data, indent=2))
        try:
            os.chmod(self._key_file, 0o600)
        except OSError:  # Windows or unusual FS
            pass
        self._keypair = kp
        self._did = kp.did()
        logger.info("Generated new DID:key — %s (saved to %s)", self._did, self._key_file)

    def _load_key(self) -> None:
        """Load an existing keypair from the key-file."""
        try:
            data = json.loads(self._key_file.read_text())
            secret_b64 = data["private_key_base64url"]
            kp = _ucan_lib.EdKeypair.from_secret_key(secret_b64)
            self._keypair = kp
            self._did = kp.did()
            logger.debug("Loaded DID:key %s from %s", self._did, self._key_file)
        except Exception as exc:
            logger.error(
                "Failed to load DID key from %s (%s: %s) — regenerating",
                self._key_file, type(exc).__name__, exc,
            )
            self._generate_and_save()

    def export_secret_b64(self) -> str:
        """Return the raw Ed25519 private key seed as a base64url string.

        This string can be used to recreate the keypair with
        ``EdKeypair.from_secret_key()``.  **Never share or commit this value.**
        """
        if not _UCAN_AVAILABLE or self._keypair is None:
            raise RuntimeError("py-ucan is not available — cannot export key")
        return self._keypair.export().d

    def rotate_key(self) -> str:
        """Generate a new keypair and overwrite the key-file.

        Returns the new DID:key string.
        """
        if not _UCAN_AVAILABLE:
            raise RuntimeError("py-ucan is not available — cannot rotate key")
        self._generate_and_save()
        assert self._did is not None
        return self._did

    # ------------------------------------------------------------------
    # UCAN delegation minting
    # ------------------------------------------------------------------

    async def mint_delegation(
        self,
        audience_did: str,
        capabilities: Sequence[Tuple[str, str]],
        lifetime_seconds: int = 3600,
    ) -> str:
        """Mint a signed UCAN delegation token.

        Parameters
        ----------
        audience_did:
            The ``did:key:...`` of the *audience* (the agent receiving the
            delegation).
        capabilities:
            A sequence of ``(resource, ability)`` pairs, e.g.::

                [("secrets://project/", "secrets/read"),
                 ("tools://admin/", "tools/invoke")]

        lifetime_seconds:
            How long (in seconds) the delegation is valid.  Default: 3 600 s
            (one hour).

        Returns
        -------
        str
            A signed JWT-formatted UCAN token string.
        """
        if not _UCAN_AVAILABLE or self._keypair is None:
            raise RuntimeError("py-ucan is not available — cannot mint delegation")

        cap_dicts = [{"with": res, "can": ability} for res, ability in capabilities]
        u = await _ucan_lib.build(
            issuer=self._keypair,
            audience=audience_did,
            capabilities=cap_dicts,
            lifetime_in_seconds=lifetime_seconds,
        )
        return u.encode()

    async def verify_delegation(
        self,
        token: str,
        required_capabilities: Sequence[Tuple[str, str]],
    ) -> bool:
        """Verify a UCAN token against a set of required capabilities.

        The *audience* is always our own DID (i.e. we are checking whether
        *we* hold a valid delegation).

        Parameters
        ----------
        token:
            The encoded UCAN JWT string to verify.
        required_capabilities:
            Sequence of ``(resource, ability)`` pairs that must all be
            satisfied.

        Returns
        -------
        bool
            *True* if the token is valid and covers all required capabilities.
        """
        if not _UCAN_AVAILABLE or self._keypair is None:
            raise RuntimeError("py-ucan is not available — cannot verify delegation")

        req_caps = [
            _ucan_lib.RequiredCapability(
                capability=_ucan_lib.Capability(with_=res, can=ability),
                root_issuer=self._did,
            )
            for res, ability in required_capabilities
        ]
        result = await _ucan_lib.verify(
            token,
            audience=self._did,
            required_capabilities=req_caps,
        )
        return isinstance(result, _ucan_lib.VerifyResultOk)

    # ------------------------------------------------------------------
    # Convenience: mint a "self-delegation" for internal tool access
    # ------------------------------------------------------------------

    async def mint_self_delegation(
        self,
        capabilities: Sequence[Tuple[str, str]],
        lifetime_seconds: int = 86_400,
    ) -> str:
        """Mint a delegation from *self* to *self* (for bootstrapping).

        This is useful when the same process both issues and consumes tokens
        (e.g. for encrypting secrets that only this process can decrypt).
        """
        assert self._did is not None
        return await self.mint_delegation(
            audience_did=self._did,
            capabilities=capabilities,
            lifetime_seconds=lifetime_seconds,
        )

    # ------------------------------------------------------------------
    # Info / repr
    # ------------------------------------------------------------------

    async def sign_delegation_token(
        self,
        token: "Any",  # DelegationToken from ucan_delegation module
        audience_did: Optional[str] = None,
        lifetime_seconds: int = 86_400,
    ) -> str:
        """Sign a stub :class:`~ipfs_datasets_py.mcp_server.ucan_delegation.DelegationToken`
        and return a real UCAN JWT string.

        When ``py-ucan`` is available the returned string is a fully signed
        Ed25519 JWT that can be verified by any UCAN-compliant verifier.
        When ``py-ucan`` is not installed a lightweight base64 JSON stub is
        returned (prefixed with ``"stub:"``); this is only safe for testing.

        Parameters
        ----------
        token:
            A :class:`~ipfs_datasets_py.mcp_server.ucan_delegation.DelegationToken`
            whose ``issuer`` is assumed to be *our* DID (or will be overridden).
        audience_did:
            Override the audience DID.  Defaults to ``token.audience``.
        lifetime_seconds:
            Token lifetime for the signed JWT.  The stub always uses this value
            as well (encoded in the JSON payload).

        Returns
        -------
        str
            A signed UCAN JWT (real when ``py-ucan`` is available) or a stub
            base64 JSON string.
        """
        aud = audience_did or getattr(token, "audience", None) or self._did
        # Build capability list from the stub token
        caps: List[Tuple[str, str]] = [
            (c.resource, c.ability)
            for c in getattr(token, "capabilities", [])
        ]

        if _UCAN_AVAILABLE and self._keypair is not None:
            # Use real py-ucan signing
            return await self.mint_delegation(
                audience_did=aud,
                capabilities=caps,
                lifetime_seconds=lifetime_seconds,
            )

        # Fallback: produce a deterministic stub JWT-like string
        import base64
        import json as _json

        payload = {
            "iss": self._did,
            "aud": aud,
            "caps": [{"with": c[0], "can": c[1]} for c in caps],
            "exp": int(__import__("time").time()) + lifetime_seconds,
            "cid": getattr(token, "cid", "stub"),
        }
        b64 = base64.urlsafe_b64encode(
            _json.dumps(payload, separators=(",", ":")).encode()
        ).rstrip(b"=").decode()
        return f"stub:{b64}"

    async def verify_signed_token(
        self,
        signed_token: str,
        required_capabilities: Optional[Sequence[Tuple[str, str]]] = None,
    ) -> bool:
        """Verify a token returned by :meth:`sign_delegation_token`.

        Returns *True* for real UCAN JWTs (delegated via ``py-ucan``) or for
        stub tokens whose payload is structurally valid.  Capability checking
        is only performed when ``required_capabilities`` is given and
        ``py-ucan`` is available.
        """
        if signed_token.startswith("stub:"):
            # Stub path — just check it decodes
            import base64
            import json as _json
            try:
                b64 = signed_token[5:] + "=="
                _json.loads(base64.urlsafe_b64decode(b64).decode())
                return True
            except Exception:
                return False

        if not _UCAN_AVAILABLE or self._keypair is None:
            return False

        req_caps: List[Any] = []
        if required_capabilities:
            req_caps = [
                _ucan_lib.RequiredCapability(
                    capability=_ucan_lib.Capability(with_=res, can=ability),
                    root_issuer=self._did,
                )
                for res, ability in required_capabilities
            ]
            result = await _ucan_lib.verify(
                signed_token,
                audience=self._did,
                required_capabilities=req_caps,
            )
            return isinstance(result, _ucan_lib.VerifyResultOk)

        # No capability check requested — just parse
        try:
            await _ucan_lib.verify(signed_token, audience=self._did, required_capabilities=[])
            return True
        except Exception:
            return False

    def info(self) -> Dict[str, Any]:
        """Return a dict of public metadata about this key manager."""
        return {
            "did": self._did,
            "key_file": str(self._key_file),
            "ucan_available": self.ucan_available,
        }

    def __repr__(self) -> str:
        return f"DIDKeyManager(did={self._did!r}, key_file={self._key_file!r})"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_manager: Optional[DIDKeyManager] = None


def get_did_key_manager(key_file: Optional[Path] = None) -> DIDKeyManager:
    """Return the process-level singleton :class:`DIDKeyManager`.

    On the first call the manager is initialised (loading or generating the
    key-pair).  Subsequent calls return the cached instance unless *key_file*
    is explicitly provided.

    Parameters
    ----------
    key_file:
        Optional path override.  If provided a **new** manager is created and
        cached (replacing the previous singleton).
    """
    global _default_manager
    if _default_manager is None or key_file is not None:
        _default_manager = DIDKeyManager(key_file=key_file)
    return _default_manager
