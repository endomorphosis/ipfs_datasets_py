"""ZKP backend registry.

This package must remain lightweight and import-safe:
- No heavy cryptographic dependencies are imported at module import-time.
- Backends are loaded lazily when requested.

Backends:
- "simulated": current demo-only backend
- "groth16": production backend placeholder (fails closed until implemented)
"""

from __future__ import annotations

from typing import Protocol
import importlib

from .. import ZKPProof
from .. import ZKPError


class ZKBackend(Protocol):
    backend_id: str

    def generate_proof(self, theorem: str, private_axioms: list[str], metadata: dict) -> ZKPProof: ...

    def verify_proof(self, proof: ZKPProof) -> bool: ...


def get_backend(backend: str) -> ZKBackend:
    backend_norm = (backend or "").strip().lower()
    if backend_norm in {"", "sim", "simulated"}:
        mod = importlib.import_module(f"{__name__}.simulated")
        return mod.SimulatedBackend()

    if backend_norm in {"groth16", "g16"}:
        mod = importlib.import_module(f"{__name__}.groth16")
        return mod.Groth16Backend()

    raise ZKPError(f"Unknown ZKP backend: {backend!r}")
