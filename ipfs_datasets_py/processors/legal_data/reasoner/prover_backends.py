from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Dict, List, Protocol, runtime_checkable


PROVER_ENVELOPE_SCHEMA_VERSION = "1.0"


@dataclass
class ProverResult:
    backend: str
    status: str
    theorem: str
    assumptions: List[str]
    certificate: Dict[str, Any]


@runtime_checkable
class ProverBackend(Protocol):
    """Backend interface for theorem proving integrations."""

    backend_id: str

    def prove(self, theorem: str, assumptions: List[str]) -> ProverResult:
        ...


class ProverBackendRegistry:
    """Registry for theorem prover backends keyed by backend ID."""

    def __init__(self) -> None:
        self._backends: Dict[str, ProverBackend] = {}

    def register(self, backend: ProverBackend) -> None:
        backend_id = str(getattr(backend, "backend_id", "") or "").strip().lower()
        if not backend_id:
            raise ValueError("backend_id is required")
        self._backends[backend_id] = backend

    def unregister(self, backend_id: str) -> None:
        key = str(backend_id or "").strip().lower()
        self._backends.pop(key, None)

    def get(self, backend_id: str) -> ProverBackend:
        key = str(backend_id or "").strip().lower()
        if key not in self._backends:
            raise KeyError(f"Unknown prover backend: {backend_id}")
        return self._backends[key]

    def list_backends(self) -> List[str]:
        return sorted(self._backends.keys())


class SMTStyleProverAdapter:
    """SMT-style prover backend adapter scaffold."""

    backend_id = "smt_style"

    def __init__(self, *, solver_name: str = "z3") -> None:
        self.solver_name = solver_name

    def prove(self, theorem: str, assumptions: List[str]) -> ProverResult:
        return ProverResult(
            backend=self.backend_id,
            status="unknown",
            theorem=str(theorem),
            assumptions=list(assumptions),
            certificate={
                "format": "smt-certificate-v1",
                "backend": self.backend_id,
                "solver": self.solver_name,
                "theorem_hash_hint": hashlib.sha1(str(theorem).encode("utf-8")).hexdigest()[:12],
            },
        )


class FirstOrderProverAdapter:
    """First-order prover backend adapter scaffold."""

    backend_id = "first_order"

    def __init__(self, *, prover_name: str = "eprover") -> None:
        self.prover_name = prover_name

    def prove(self, theorem: str, assumptions: List[str]) -> ProverResult:
        return ProverResult(
            backend=self.backend_id,
            status="unknown",
            theorem=str(theorem),
            assumptions=list(assumptions),
            certificate={
                "format": "first-order-certificate-v1",
                "backend": self.backend_id,
                "prover": self.prover_name,
                "assumption_count": len(assumptions),
            },
        )


class MockSMTBackend(SMTStyleProverAdapter):
    """Back-compat alias used by existing tests and scripts."""

    backend_id = "mock_smt"

    def __init__(self) -> None:
        super().__init__(solver_name="mock-z3")


class MockFOLBackend(FirstOrderProverAdapter):
    """Back-compat alias used by existing tests and scripts."""

    backend_id = "mock_fol"

    def __init__(self) -> None:
        super().__init__(prover_name="mock-eprover")


def create_default_prover_registry() -> ProverBackendRegistry:
    registry = ProverBackendRegistry()
    registry.register(SMTStyleProverAdapter())
    registry.register(FirstOrderProverAdapter())
    registry.register(MockSMTBackend())
    registry.register(MockFOLBackend())
    return registry


def normalize_prover_result(result: ProverResult) -> Dict[str, Any]:
    """Normalize backend-specific prover output into a stable envelope."""
    payload = {
        "backend": str(result.backend),
        "status": str(result.status),
        "theorem": str(result.theorem),
        "assumptions": [str(a) for a in list(result.assumptions or [])],
        "certificate": dict(result.certificate or {}),
    }
    normalized_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    certificate_id = "cert_" + normalized_hash[:12]

    return {
        "schema_version": PROVER_ENVELOPE_SCHEMA_VERSION,
        "backend": payload["backend"],
        "status": payload["status"],
        "theorem": payload["theorem"],
        "assumptions": payload["assumptions"],
        "certificate": {
            "certificate_id": certificate_id,
            "format": str(payload["certificate"].get("format") or "unknown"),
            "normalized_hash": normalized_hash,
            "payload": payload["certificate"],
        },
    }
