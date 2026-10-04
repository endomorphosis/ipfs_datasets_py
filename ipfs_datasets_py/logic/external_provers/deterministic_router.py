"""Capability-based deterministic prover route selection.

This module plans a bounded route; it does not install or execute a backend.
Availability therefore remains explicit and testable at the caller boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any


DETERMINISTIC_PROVER_ROUTE_SCHEMA_VERSION = "legal-ir-prover-route-v1"

_KNOWN_BACKENDS = (
    "z3",
    "cvc5",
    "vampire",
    "eprover",
    "lean",
    "coq",
    "native",
    "native_syntactic",
)
_ALIASES = {
    "e": "eprover",
    "e-prover": "eprover",
    "e_prover": "eprover",
    "native-syntactic": "native_syntactic",
    "proofassistant_lean": "lean",
    "smt_z3": "z3",
}
_FAMILY_ALIASES = {
    "cec": "event_calculus",
    "dcec": "event_calculus",
    "deontic_ir": "deontic",
    "fol": "first_order",
    "first-order": "first_order",
    "modal_logic": "modal",
    "proof_translation": "first_order",
    "smtlib": "smt",
    "tdfol": "temporal",
}
_PRIORITY = {
    "arithmetic": ("z3", "cvc5", "lean", "native"),
    "deontic": ("native", "vampire", "eprover", "z3", "cvc5", "lean"),
    "event_calculus": ("native", "vampire", "eprover", "z3", "lean"),
    "first_order": ("vampire", "eprover", "cvc5", "z3", "native", "lean"),
    "modal": ("native", "vampire", "eprover", "lean", "z3"),
    "propositional": ("z3", "cvc5", "native", "lean"),
    "smt": ("z3", "cvc5", "lean", "native"),
    "temporal": ("native", "vampire", "eprover", "cvc5", "z3", "lean"),
}


def select_deterministic_prover_route(
    formula_family: str = "first_order",
    available_backends: Sequence[str] | Mapping[str, Any] | None = None,
    *,
    preferred_backends: Sequence[str] = (),
    obligation_id: str = "",
    input_formula_id: str = "",
    provenance_id: str = "",
    require_reconstruction: bool = False,
    max_backends: int = 4,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Return a stable, bounded backend route and pre-execution receipt.

    ``available_backends`` may be a sequence of names or a name-to-status
    mapping; false, unavailable, disabled, and failed mapping entries are
    excluded.  ``None`` means that the complete known capability catalogue is
    eligible, whereas an explicit empty sequence produces an unavailable route.
    """

    family = _canonical_family(formula_family)
    available = _available_names(available_backends)
    preferred = _unique_backend_names(preferred_backends)
    capability_order = _PRIORITY.get(family, _PRIORITY["first_order"])
    candidates = [
        backend
        for backend in (*preferred, *capability_order, "native_syntactic")
        if backend in available
    ]
    bounded_max = min(8, max(1, int(max_backends)))
    route = _unique_backend_names(candidates)[:bounded_max]
    if require_reconstruction:
        route = _ensure_reconstruction_backend(route, available, bounded_max)
    timeout = max(0.01, min(300.0, float(timeout_seconds)))
    provenance_ids = [str(provenance_id).strip()] if str(provenance_id).strip() else []
    backend_status = {backend: "selected" for backend in route}
    reconstruction_backend = next(
        (backend for backend in route if backend in {"lean", "coq", "native"}),
        "",
    )
    reconstruction_status = (
        "planned"
        if require_reconstruction and reconstruction_backend
        else "unavailable"
        if require_reconstruction
        else "not_requested"
    )
    identity = {
        "backend_route": route,
        "formula_family": family,
        "input_formula_id": str(input_formula_id or ""),
        "obligation_id": str(obligation_id or ""),
        "provenance_ids": provenance_ids,
        "reconstruction_status": reconstruction_status,
    }
    return {
        "backend_route": route,
        "backend_status": backend_status,
        "formula_family": family,
        "input_formula_id": str(input_formula_id or ""),
        "max_backends": bounded_max,
        "obligation_id": str(obligation_id or ""),
        "provenance_ids": provenance_ids,
        "reconstruction_backend": reconstruction_backend,
        "reconstruction_status": reconstruction_status,
        "route_id": f"prover-route:{_digest(identity)[:24]}",
        "route_status": "planned" if route else "unavailable",
        "schema_version": DETERMINISTIC_PROVER_ROUTE_SCHEMA_VERSION,
        "strategy": "bounded_sequential",
        "timeout_policy": "bounded_per_backend",
        "timeout_seconds": timeout,
    }


def _canonical_family(value: Any) -> str:
    family = str(value or "first_order").strip().lower().replace(" ", "_")
    return _FAMILY_ALIASES.get(family, family)


def _available_names(value: Sequence[str] | Mapping[str, Any] | None) -> list[str]:
    if value is None:
        return list(_KNOWN_BACKENDS)
    if isinstance(value, Mapping):
        enabled: list[str] = []
        for name, status in value.items():
            normalized_status = str(status or "").strip().lower()
            if status is False or normalized_status in {
                "disabled",
                "failed",
                "false",
                "missing",
                "unavailable",
                "0",
            }:
                continue
            enabled.append(str(name))
        return _unique_backend_names(enabled)
    if isinstance(value, (str, bytes)):
        return _unique_backend_names([str(value)])
    return _unique_backend_names(value)


def _unique_backend_names(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        name = str(value or "").strip().lower()
        name = _ALIASES.get(name, name)
        if name in _KNOWN_BACKENDS and name not in result:
            result.append(name)
    return result


def _ensure_reconstruction_backend(
    route: list[str],
    available: Sequence[str],
    limit: int,
) -> list[str]:
    if any(backend in {"lean", "coq", "native"} for backend in route):
        return route
    backend = next(
        (name for name in ("lean", "coq", "native") if name in available),
        "",
    )
    if not backend:
        return route
    if len(route) < limit:
        return [*route, backend]
    return [*route[:-1], backend]


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "DETERMINISTIC_PROVER_ROUTE_SCHEMA_VERSION",
    "select_deterministic_prover_route",
]
