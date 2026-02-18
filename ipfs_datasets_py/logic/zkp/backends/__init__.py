"""ZKP backend registry and selection.

This package must remain lightweight and import-safe:
- No heavy cryptographic dependencies are imported at module import-time.
- Backends are loaded lazily when requested.

Backends:
- "simulated": current demo-only backend (educational, not cryptographically secure)
- "groth16": production backend placeholder (fails closed until Phase C implementation)

Backend Protocol:
  All backends must implement the ZKBackend protocol with:
  - backend_id: str (backend identifier)
  - generate_proof(theorem, private_axioms, metadata) -> ZKPProof
  - verify_proof(proof) -> bool
"""

from __future__ import annotations

from typing import Protocol, Any, runtime_checkable
import importlib

from .. import ZKPProof
from .. import ZKPError


@runtime_checkable
class ZKBackend(Protocol):
    """
    Protocol that all ZKP backends must implement.
    
    Enables pluggable backends (simulation vs. real cryptography).
    All backends must implement these methods and properties.
    """
    backend_id: str

    def generate_proof(self, theorem: str, private_axioms: list[str], metadata: dict) -> ZKPProof:
        """Generate a ZKP proof for the theorem given private axioms."""
        ...

    def verify_proof(self, proof: ZKPProof) -> bool:
        """Verify a ZKP proof. Must return False, never raise."""
        ...


# Backend registry cache (populated lazily)
_backend_cache: dict[str, ZKBackend] = {}

# Backend metadata for discovery and documentation
_BACKEND_METADATA = {
    "simulated": {
        "description": "Educational simulation (not cryptographically secure)",
        "curve": "simulation",
        "module": "simulated",
        "class_name": "SimulatedBackend",
    },
    "groth16": {
        "description": "Real Groth16 zkSNARK backend (BN254 curve) - Phase C pending",
        "curve": "bn254",
        "module": "groth16",
        "class_name": "Groth16Backend",
    }
}


def get_backend(backend: str = "simulated") -> ZKBackend:
    """
    Retrieve and lazily instantiate a backend by ID.
    
    Args:
        backend: Backend identifier (default: "simulated")
                 Recognized: "", "sim", "simulated", "groth16", "g16"
    
    Returns:
        ZKBackend instance (cached for subsequent calls)
    
    Raises:
        ZKPError: If backend is unknown or required dependencies are missing
    
    Example:
        >>> backend = get_backend("simulated")
        >>> proof = backend.generate_proof("P", ["P"], {})
    """
    # Normalize backend name
    backend_norm = (backend or "").strip().lower()
    
    # Check cache first
    cache_key = backend_norm if backend_norm else "simulated"
    if cache_key in _backend_cache:
        return _backend_cache[cache_key]
    
    # Load simulated backend (always available)
    if backend_norm in {"", "sim", "simulated"}:
        mod = importlib.import_module(f"{__name__}.simulated")
        backend_instance = mod.SimulatedBackend()
        _backend_cache["simulated"] = backend_instance
        return backend_instance

    # Load Groth16 backend (requires py_ecc at minimum)
    if backend_norm in {"groth16", "g16"}:
        try:
            import py_ecc  # Check minimum requirement
        except ImportError as e:
            raise ZKPError(
                f"Groth16 backend requires py_ecc dependency. "
                f"Install with: pip install 'ipfs-datasets-py[groth16]'\n"
                f"Original error: {e}"
            )
        
        # Try to load Groth16 backend
        mod = importlib.import_module(f"{__name__}.groth16")
        try:
            backend_instance = mod.Groth16Backend()
            _backend_cache["groth16"] = backend_instance
            return backend_instance
        except NotImplementedError as e:
            raise ZKPError(
                f"Groth16 backend not yet implemented. "
                f"Phase C implementation pending. "
                f"See PHASE3_GROTH16_STACK_SELECTION.md for roadmap.\n"
                f"Original error: {e}"
            )

    # Unknown backend
    available = ", ".join(f"'{k}'" for k in _BACKEND_METADATA.keys())
    raise ZKPError(
        f"Unknown ZKP backend: {backend!r}. "
        f"Available backends: {available}"
    )


def list_backends() -> dict[str, dict[str, Any]]:
    """
    List metadata for all known backends.
    
    Returns:
        Dictionary mapping backend_id to metadata
    """
    return _BACKEND_METADATA.copy()


def backend_is_available(backend_id: str) -> bool:
    """
    Check if a backend is available and loadable.
    
    Args:
        backend_id: Backend identifier to check
    
    Returns:
        True if backend can be loaded successfully, False otherwise
    """
    try:
        get_backend(backend_id)
        return True
    except ZKPError:
        return False


def clear_backend_cache() -> None:
    """
    Clear the backend cache.
    
    Primarily used for testing. Generally should not be called in production.
    """
    global _backend_cache
    _backend_cache.clear()
