"""Fail-closed PCPR-012 Datasets typed-outcome canonicalization.

Public load/dataset symbols must not be silent ``None``. Missing optional
dependencies expose a typed Unavailable surface with closed Formal Claim
Algebra (FCA) outcomes. Surface maturity is one of stable, beta,
experimental, simulation_only, or unavailable. Simulation requires explicit
caller selection and is never represented as live.

This module is not release authority: it does not write DuckDB or Quack
state and never emits a closed PCPR release outcome. Live claims require
live evidence. Simulated results are not live.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .outcomes import (
    CLOSED_OUTCOMES,
    DatasetOutcome,
    unavailable_missing_dependency,
)

INTERFACE: Final = "DatasetsTypedOutcomesCanonical@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/typed-outcomes-canonical@1"
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/typed-outcomes-canonical-verdict@1"
)
PCPR_012_TASK_ID: Final = "PCPR-012"
PCPR_012_GOAL_ID: Final = "PCPR-G210"
PCPR_011_TASK_ID: Final = "PCPR-011"
PCPR_010_TASK_ID: Final = "PCPR-010"
PCPR_003_TASK_ID: Final = "PCPR-003"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
PCPR_BOARD_NAMESPACE: Final = "proof-carrying-platform-qualification-and-release-v1"
EVIDENCE_ID: Final = "pcpr/datasets-typed-outcomes-canonical@1"

CANONICAL_CLOSED_OUTCOMES: Final[frozenset[str]] = CLOSED_OUTCOMES
CANONICAL_CLOSED_STATUSES: Final[frozenset[str]] = frozenset(
    outcome.lower() for outcome in CLOSED_OUTCOMES
)

SURFACE_MATURITIES: Final[frozenset[str]] = frozenset(
    {
        "stable",
        "beta",
        "experimental",
        "simulation_only",
        "unavailable",
    }
)

CLOSED_RELEASE_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "release_candidate_qualified",
        "non_promoted_supervisor_unqualified",
        "non_promoted_import_or_false_success",
        "non_promoted_live_storage_gap",
        "non_promoted_live_compute_gap",
        "non_promoted_solver_gap",
        "non_promoted_packaging_gap",
        "non_promoted_dependency_reproducibility",
        "non_promoted_security_failure",
        "non_promoted_interoperability_gap",
        "non_promoted_reference_workflow_failure",
        "non_promoted_unmeasured",
        "non_promoted_operator_gate_required",
    }
)
PROMOTION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "supervisor_promoted",
        "supervisor_non_promoted",
        "rnd_non_promoted",
        "typed_unavailable",
        "typed_blocked",
    }
)
EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "measured",
        "measured_live",
        "measured_hermetic",
        "estimated",
        "simulated",
        "unavailable",
    }
)

INIT_RELPATH: Final = "ipfs_datasets_py/__init__.py"
DATASET_MANAGER_RELPATH: Final = "ipfs_datasets_py/dataset_manager.py"
DATASET_LOADER_RELPATH: Final = (
    "ipfs_datasets_py/core_operations/dataset_loader.py"
)
OUTCOMES_RELPATH: Final = "ipfs_datasets_py/assurance/outcomes.py"

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_012_typed_outcomes.py",
)

SEALED_PATH: Final = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
SEALED_PYTHON: Final = "/usr/bin/python3.12"

UNTYPED_NONE_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "init_module_level_load_dataset_none",
        "init_getattr_load_dataset_none",
        "dataset_manager_load_dataset_none",
        "dataset_loader_hf_load_dataset_none",
        "runtime_public_load_dataset_is_none",
        "runtime_unavailable_load_success",
        "runtime_unavailable_load_represented_as_live",
    }
)

INVENTORIED_PUBLIC_LOAD_SYMBOLS: Final[tuple[str, ...]] = (
    "ipfs_datasets_py/__init__.py::load_dataset",
    "ipfs_datasets_py/__init__.py::IPFSDatasets",
    "ipfs_datasets_py/dataset_manager.py::load_dataset",
    "ipfs_datasets_py/core_operations/dataset_loader.py::hf_load_dataset",
)


class TypedOutcomeError(Exception):
    """Fail-closed PCPR-012 contract error."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def content_identity(value: Any) -> str:
    """CIDv1 DAG-JSON/sha2-256 identity (baguqeera…)."""

    digest = hashlib.sha256(canonical_json_bytes(value)).digest()
    raw = b"\x01\xa9\x02\x12\x20" + digest
    return "b" + base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def discover_datasets_root(start: Path | None = None) -> Path | None:
    here = Path(start or __file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "ipfs_datasets_py").is_dir() and (
            candidate / "pyproject.toml"
        ).is_file():
            return candidate
    return None


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypedOutcomeError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise TypedOutcomeError(f"{name} is not an admitted evidence kind")
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise TypedOutcomeError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _read_source(root: Path, relpath: str) -> str | None:
    path = root / relpath
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_unavailable_surface(value: object) -> bool:
    """True when a public symbol is missing or an Unavailable stand-in."""

    if value is None:
        return True
    return bool(getattr(value, "unavailable", False))


def _explicit_simulation_requested(kwargs: Mapping[str, Any]) -> bool:
    return _truthy(kwargs.get("explicit_simulation")) or _truthy(
        os.environ.get("IPFS_DATASETS_EXPLICIT_SIMULATION")
    )


def unavailable_load_outcome(
    *,
    dependency: str = "datasets",
    message: str | None = None,
    simulated: bool = False,
    details: Mapping[str, Any] | None = None,
) -> DatasetOutcome:
    """Typed load outcome. Missing HuggingFace datasets stays Unavailable."""

    extra = {
        "fallback_success_forbidden": True,
        "surface": "load_dataset",
        "surface_maturity": "simulation_only" if simulated else "unavailable",
        "live": False,
        "simulated": simulated,
        "simulated_represented_as_live": False,
        **dict(details or {}),
    }
    if simulated:
        return DatasetOutcome(
            outcome="Simulated",
            code="explicit_simulation",
            message=message
            or "load_dataset explicit simulation is not a live load",
            operation="load",
            details=extra,
        )
    return unavailable_missing_dependency(
        operation="load",
        dependency=dependency,
        message=message
        or (
            "required dependency 'datasets' is not available for load_dataset; "
            "the public surface is typed Unavailable, not silent None"
        ),
        details=extra,
    )


def unavailable_load_payload(
    *,
    source: object | None = None,
    simulated: bool = False,
    **kwargs: object,
) -> dict[str, Any]:
    """Compatibility dict for a typed load. Never status success or live."""

    outcome = unavailable_load_outcome(
        simulated=simulated,
        details={"source": source, **kwargs} if source is not None else kwargs,
    )
    payload = outcome.to_legacy_compat_dict()
    payload["dataset"] = None
    payload["live"] = False
    payload["simulated"] = bool(simulated)
    payload["simulated_represented_as_live"] = False
    payload["durable_effect"] = False
    payload["surface_maturity"] = (
        "simulation_only" if simulated else "unavailable"
    )
    payload["HAVE_LOAD_DATASET"] = False
    if source is not None:
        payload["source"] = source
    return payload


class LoadDatasetSurface:
    """Canonical public ``load_dataset`` surface.

    Never silent None. Missing HuggingFace datasets is typed Unavailable.
    A bound optional implementation is experimental and is not live hub
    qualification. Explicit simulation is Simulated and never live.
    """

    __slots__ = (
        "implementation",
        "surface_maturity",
        "unavailable",
        "live",
        "ok",
        "status",
        "outcome",
    )

    def __init__(
        self,
        *,
        implementation: object | None = None,
        surface_maturity: str = "unavailable",
    ) -> None:
        if surface_maturity not in SURFACE_MATURITIES:
            raise TypedOutcomeError(
                f"unknown surface maturity: {surface_maturity!r}"
            )
        if implementation is None:
            surface_maturity = "unavailable"
        self.implementation = implementation
        self.surface_maturity = surface_maturity
        self.unavailable = implementation is None or surface_maturity in {
            "unavailable",
            "simulation_only",
        }
        self.live = False
        self.ok = False
        self.status = "unavailable" if implementation is None else "bound"
        self.outcome = "Unavailable" if implementation is None else "Attempted"

    def __bool__(self) -> bool:
        return self.implementation is not None and not self.unavailable

    def __repr__(self) -> str:
        return (
            "LoadDatasetSurface("
            f"maturity={self.surface_maturity!r}, "
            f"unavailable={self.unavailable}, live={self.live})"
        )

    def __call__(self, *args: object, **kwargs: object) -> Any:
        simulated = _explicit_simulation_requested(kwargs)
        if simulated or self.implementation is None:
            source = args[0] if args else kwargs.get("path") or kwargs.get(
                "source"
            )
            return unavailable_load_payload(
                source=source,
                simulated=simulated,
            )
        return self.implementation(*args, **kwargs)


unavailable_load_dataset: Final[LoadDatasetSurface] = LoadDatasetSurface(
    implementation=None,
    surface_maturity="unavailable",
)


def bind_load_dataset_surface(
    implementation: object | None,
    *,
    surface_maturity: str = "experimental",
) -> LoadDatasetSurface:
    """Bind a live optional implementation or return the Unavailable stand-in."""

    if implementation is None or is_unavailable_surface(implementation):
        return unavailable_load_dataset
    if surface_maturity not in SURFACE_MATURITIES:
        raise TypedOutcomeError(
            f"unknown surface maturity: {surface_maturity!r}"
        )
    if surface_maturity == "unavailable":
        return unavailable_load_dataset
    return LoadDatasetSurface(
        implementation=implementation,
        surface_maturity=surface_maturity,
    )


def resolve_load_dataset_surface(
    *,
    minimal_imports: bool = False,
) -> LoadDatasetSurface:
    """Resolve the public load_dataset surface without installing.

    HuggingFace hub I/O is not performed. Importability of the optional
    ``datasets`` package is not live qualification.
    """

    if minimal_imports:
        return unavailable_load_dataset
    try:
        from datasets import load_dataset as _load_dataset  # type: ignore
    except Exception:
        return unavailable_load_dataset
    if _load_dataset is None:
        return unavailable_load_dataset
    return bind_load_dataset_surface(
        _load_dataset,
        surface_maturity="experimental",
    )


@dataclass(frozen=True)
class OutcomeProbe:
    probe_id: str
    present: bool | None
    evidence_kind: str
    live: bool
    simulated_represented_as_live: bool
    reason: str
    details: Mapping[str, Any] = MappingProxyType({})

    def to_mapping(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "present": self.present,
            "evidence_kind": self.evidence_kind,
            "live": self.live,
            "simulated_represented_as_live": self.simulated_represented_as_live,
            "reason": self.reason,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class TypedOutcomesVerdict:
    schema: str
    interface: str
    promotion_status: str
    supervisor_disposition: str
    closed_release_outcome: str | None
    release_claim: bool
    completion_authoritative: bool
    contracts_frozen: bool
    duckdb_or_quack_state_written: bool
    untyped_none_fallback_present: bool
    typed_outcomes_canonical: bool
    simulated_results_represented_as_live: bool
    live_solver_qualified: bool
    live_solver_evidence_kind: str
    live_hub_qualified: bool
    live_hub_evidence_kind: str
    this_task_created_competing_authority: bool
    probes: tuple[OutcomeProbe, ...]
    blockers: tuple[str, ...]
    verdict_cid: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.interface,
            "verdict_cid": self.verdict_cid,
            "promotion_status": self.promotion_status,
            "supervisor_disposition": self.supervisor_disposition,
            "closed_release_outcome": self.closed_release_outcome,
            "release_claim": self.release_claim,
            "completion_authoritative": self.completion_authoritative,
            "contracts_frozen": self.contracts_frozen,
            "duckdb_or_quack_state_written": self.duckdb_or_quack_state_written,
            "untyped_none_fallback_present": self.untyped_none_fallback_present,
            "typed_outcomes_canonical": self.typed_outcomes_canonical,
            "simulated_results_represented_as_live": (
                self.simulated_results_represented_as_live
            ),
            "live_solver_qualified": self.live_solver_qualified,
            "live_solver_evidence_kind": self.live_solver_evidence_kind,
            "live_hub_qualified": self.live_hub_qualified,
            "live_hub_evidence_kind": self.live_hub_evidence_kind,
            "this_task_created_competing_authority": (
                self.this_task_created_competing_authority
            ),
            "blocker_count": len(self.blockers),
            "blockers": list(self.blockers),
            "evidence_kind": "measured",
        }


def _unavailable_file_probe(probe_id: str, relpath: str) -> OutcomeProbe:
    return OutcomeProbe(
        probe_id=probe_id,
        present=None,
        evidence_kind="unavailable",
        live=False,
        simulated_represented_as_live=False,
        reason=f"{relpath} is missing and is not recorded as empty.",
        details={"relpath": relpath},
    )


def _static_none_probe(
    *,
    probe_id: str,
    present: bool,
    relpath: str,
    reason_absent: str,
    reason_present: str,
    extra: Mapping[str, Any] | None = None,
) -> OutcomeProbe:
    return OutcomeProbe(
        probe_id=probe_id,
        present=present,
        evidence_kind="measured",
        live=False,
        simulated_represented_as_live=False,
        reason=reason_absent if not present else reason_present,
        details={"relpath": relpath, **dict(extra or {})},
    )


def _is_none_constant(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _subscript_string_key(node: ast.Subscript) -> str | None:
    sl = node.slice
    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
        return sl.value
    return None


def _is_globals_name_target(target: ast.AST, name: str) -> bool:
    if not isinstance(target, ast.Subscript):
        return False
    if _subscript_string_key(target) != name:
        return False
    value = target.value
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "globals"
    )


def _assigns_name_to_none(source: str, name: str) -> bool:
    """True when ``name = None`` or ``globals()[name] = None`` appears."""

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _is_none_constant(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return True
                if _is_globals_name_target(target, name):
                    return True
        if (
            isinstance(node, ast.AnnAssign)
            and _is_none_constant(node.value)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return True
    return False


def _module_level_assigns_name_to_none(source: str, name: str) -> bool:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and _is_none_constant(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return True
        if (
            isinstance(node, ast.AnnAssign)
            and _is_none_constant(node.value)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return True
    return False


def current_head_static_probes(
    *,
    datasets_root: Path | None = None,
) -> tuple[OutcomeProbe, ...]:
    """Measured current-tree AST/source probes. Missing files stay typed unavailable."""

    root = datasets_root or discover_datasets_root()
    if root is None or not root.is_dir():
        return (
            OutcomeProbe(
                probe_id="datasets_source_tree",
                present=None,
                evidence_kind="unavailable",
                live=False,
                simulated_represented_as_live=False,
                reason=(
                    "Datasets source tree is not present and is not recorded as empty."
                ),
            ),
        )

    probes: list[OutcomeProbe] = []
    init_source = _read_source(root, INIT_RELPATH)
    manager_source = _read_source(root, DATASET_MANAGER_RELPATH)
    loader_source = _read_source(root, DATASET_LOADER_RELPATH)
    outcomes_source = _read_source(root, OUTCOMES_RELPATH)

    if init_source is None:
        probes.append(_unavailable_file_probe("package_init", INIT_RELPATH))
    else:
        module_none = _module_level_assigns_name_to_none(
            init_source, "load_dataset"
        )
        getattr_none = _assigns_name_to_none(init_source, "load_dataset")
        probes.append(
            _static_none_probe(
                probe_id="init_module_level_load_dataset_none",
                present=module_none,
                relpath=INIT_RELPATH,
                reason_absent=(
                    "Package init no longer assigns load_dataset = None at module level."
                ),
                reason_present=(
                    "Package init still assigns load_dataset = None at module level."
                ),
            )
        )
        probes.append(
            _static_none_probe(
                probe_id="init_getattr_load_dataset_none",
                present=getattr_none,
                relpath=INIT_RELPATH,
                reason_absent=(
                    "Package __getattr__ no longer assigns load_dataset to None."
                ),
                reason_present=(
                    "Package __getattr__ still assigns load_dataset to None."
                ),
            )
        )

    if manager_source is None:
        probes.append(
            _unavailable_file_probe("dataset_manager", DATASET_MANAGER_RELPATH)
        )
    else:
        manager_none = _assigns_name_to_none(manager_source, "load_dataset")
        probes.append(
            _static_none_probe(
                probe_id="dataset_manager_load_dataset_none",
                present=manager_none,
                relpath=DATASET_MANAGER_RELPATH,
                reason_absent=(
                    "dataset_manager no longer assigns load_dataset = None."
                ),
                reason_present=(
                    "dataset_manager still assigns load_dataset = None."
                ),
            )
        )

    if loader_source is None:
        probes.append(
            _unavailable_file_probe("dataset_loader", DATASET_LOADER_RELPATH)
        )
    else:
        loader_none = _assigns_name_to_none(loader_source, "hf_load_dataset")
        probes.append(
            _static_none_probe(
                probe_id="dataset_loader_hf_load_dataset_none",
                present=loader_none,
                relpath=DATASET_LOADER_RELPATH,
                reason_absent=(
                    "dataset_loader no longer assigns hf_load_dataset = None."
                ),
                reason_present=(
                    "dataset_loader still assigns hf_load_dataset = None."
                ),
            )
        )

    if outcomes_source is None:
        probes.append(_unavailable_file_probe("outcomes", OUTCOMES_RELPATH))
    else:
        vocabulary_present = all(
            f'"{name}"' in outcomes_source for name in sorted(CLOSED_OUTCOMES)
        )
        probes.append(
            OutcomeProbe(
                probe_id="canonical_closed_outcomes_present",
                present=vocabulary_present,
                evidence_kind="measured",
                live=False,
                simulated_represented_as_live=False,
                reason=(
                    "DatasetsFormalClaimOutcomes@1 closed vocabulary is present."
                    if vocabulary_present
                    else "Closed typed outcome vocabulary is missing from outcomes.py."
                ),
                details={
                    "relpath": OUTCOMES_RELPATH,
                    "closed_outcomes": sorted(CLOSED_OUTCOMES),
                },
            )
        )

    probes.append(
        OutcomeProbe(
            probe_id="live_solver_qualification",
            present=None,
            evidence_kind="unavailable",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "This task does not qualify live solvers. Missing Z3/cvc5/Lean/Coq "
                "evidence stays typed unavailable and is not recorded as False or passing."
            ),
        )
    )
    probes.append(
        OutcomeProbe(
            probe_id="live_hub_qualification",
            present=None,
            evidence_kind="unavailable",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "This task does not qualify live HuggingFace hub loads. Missing "
                "live hub evidence stays typed unavailable and is not recorded as passing."
            ),
        )
    )
    return tuple(probes)


def probe_typed_outcome_runtime() -> dict[str, Any]:
    """Runtime observation of the public load_dataset surface."""

    from ipfs_datasets_py import load_dataset as public_load

    none_public = public_load is None
    payload = (
        unavailable_load_dataset("squad")
        if none_public
        else public_load("squad")
        if is_unavailable_surface(public_load)
        else unavailable_load_dataset("squad")
    )
    if not isinstance(payload, dict):
        payload = {
            "status": "unknown",
            "ok": True,
            "live": True,
            "message": "public load_dataset did not return a mapping",
        }

    simulated = unavailable_load_dataset("squad", explicit_simulation=True)
    if simulated.get("live") is True or simulated.get(
        "simulated_represented_as_live"
    ):
        raise TypedOutcomeError("explicit simulation must not be live")
    if simulated.get("status") == "success" or simulated.get("ok") is True:
        raise TypedOutcomeError(
            "explicit simulation must remain Simulated or Unavailable, never success"
        )

    bound = bind_load_dataset_surface(None)
    if bound is not unavailable_load_dataset:
        raise TypedOutcomeError("None must bind to the Unavailable stand-in")
    if bound is None:
        raise TypedOutcomeError("bound surface must not be silent None")

    return {
        "status": "observed",
        "evidence_kind": "measured",
        "live": False,
        "simulated_represented_as_live": False,
        "public_load_is_none": none_public,
        "public_load_unavailable": is_unavailable_surface(public_load),
        "public_maturity": getattr(public_load, "surface_maturity", None),
        "payload": payload,
        "payload_status": payload.get("status"),
        "payload_ok": bool(payload.get("ok")),
        "payload_live": bool(payload.get("live")),
        "simulated_status": simulated.get("status"),
        "simulated_live": bool(simulated.get("live")),
        "canonical_closed_outcomes": sorted(CANONICAL_CLOSED_OUTCOMES),
        "reason": (
            "Public load_dataset is a typed surface; missing datasets stay "
            "Unavailable and are not silent None, success, or live."
        ),
    }


def current_head_runtime_probes() -> tuple[OutcomeProbe, ...]:
    observation = probe_typed_outcome_runtime()
    public_none = bool(observation["public_load_is_none"])
    success = (
        observation["payload_status"] == "success" or observation["payload_ok"]
    )
    live = bool(observation["payload_live"] or observation["simulated_live"])
    return (
        OutcomeProbe(
            probe_id="runtime_public_load_dataset_is_none",
            present=public_none,
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Runtime public load_dataset is not silent None."
                if not public_none
                else "Runtime public load_dataset is still silent None."
            ),
            details={
                "unavailable": observation["public_load_unavailable"],
                "surface_maturity": observation["public_maturity"],
            },
        ),
        OutcomeProbe(
            probe_id="runtime_unavailable_load_success",
            present=success,
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Unavailable load_dataset does not return status success."
                if not success
                else "Unavailable load_dataset still returns status success."
            ),
            details={"status": observation["payload_status"]},
        ),
        OutcomeProbe(
            probe_id="runtime_unavailable_load_represented_as_live",
            present=live,
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Unavailable and explicit-simulation loads are not represented as live."
                if not live
                else "Unavailable or explicit-simulation load was represented as live."
            ),
            details={
                "payload_live": observation["payload_live"],
                "simulated_status": observation["simulated_status"],
            },
        ),
    )


def qualify_typed_outcomes_canonical(
    probes: Sequence[OutcomeProbe],
) -> TypedOutcomesVerdict:
    if not probes:
        raise TypedOutcomeError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise TypedOutcomeError(
                "live claims require measured_live evidence"
            )
        if probe.simulated_represented_as_live:
            raise TypedOutcomeError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id in {
            "live_solver_qualification",
            "live_hub_qualification",
        }:
            continue
        if probe.probe_id == "canonical_closed_outcomes_present":
            if probe.present is not True:
                blockers.append(probe.probe_id)
            continue
        if probe.present is True and probe.probe_id in UNTYPED_NONE_PROBE_IDS:
            blockers.append(probe.probe_id)
        if probe.present is None and probe.evidence_kind == "unavailable":
            if probe.probe_id == "datasets_source_tree":
                blockers.append(probe.probe_id)

    untyped_present = any(
        p.present is True and p.probe_id in UNTYPED_NONE_PROBE_IDS
        for p in normalized
    )
    vocabulary_ok = any(
        p.probe_id == "canonical_closed_outcomes_present" and p.present is True
        for p in normalized
    )
    typed_canonical = (not untyped_present) and vocabulary_ok
    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_012_TASK_ID,
        "goal_id": PCPR_012_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "untyped_none_fallback_present": untyped_present,
        "typed_outcomes_canonical": typed_canonical,
        "simulated_results_represented_as_live": False,
        "live_solver_qualified": False,
        "live_solver_evidence_kind": "unavailable",
        "live_hub_qualified": False,
        "live_hub_evidence_kind": "unavailable",
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
    }
    return TypedOutcomesVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status=promotion_status,
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        untyped_none_fallback_present=untyped_present,
        typed_outcomes_canonical=typed_canonical,
        simulated_results_represented_as_live=False,
        live_solver_qualified=False,
        live_solver_evidence_kind="unavailable",
        live_hub_qualified=False,
        live_hub_evidence_kind="unavailable",
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
    )


def qualify_current_head_typed_outcomes() -> TypedOutcomesVerdict:
    return qualify_typed_outcomes_canonical(current_head_static_probes())


# Pinned identity of the ordinary current-head static verdict. Drift means
# the default payload changed and the outer receipt must be regenerated.
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeera4urjsjdnc4onh2aanu6xqggndixve77glgrmpgvokorjwwpyc7zq"
)


def pcpr_012_receipt_promotion(
    verdict: TypedOutcomesVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise TypedOutcomeError(
            "typed-outcome canonicalization must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise TypedOutcomeError(
            "typed-outcome canonicalization must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise TypedOutcomeError(
            "typed-outcome canonicalization completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise TypedOutcomeError(
            "typed-outcome canonicalization must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise TypedOutcomeError(
            "promotion_status must not be a closed release outcome"
        )
    return verdict.to_mapping()


__all__ = [
    "CANONICAL_CLOSED_OUTCOMES",
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "EVIDENCE_ID",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "LoadDatasetSurface",
    "OutcomeProbe",
    "PCPR_012_GOAL_ID",
    "PCPR_012_TASK_ID",
    "SCHEMA",
    "SURFACE_MATURITIES",
    "TypedOutcomeError",
    "TypedOutcomesVerdict",
    "bind_load_dataset_surface",
    "content_identity",
    "current_head_runtime_probes",
    "current_head_static_probes",
    "discover_datasets_root",
    "is_unavailable_surface",
    "pcpr_012_receipt_promotion",
    "probe_typed_outcome_runtime",
    "qualify_current_head_typed_outcomes",
    "qualify_typed_outcomes_canonical",
    "resolve_load_dataset_surface",
    "unavailable_load_dataset",
    "unavailable_load_outcome",
    "unavailable_load_payload",
]
