"""Fail-closed PCPR-011 Datasets false-success fallback removal.

Fallback and stub surfaces must not return status success without a real
download, upload, or transport effect. Closed statuses include unavailable,
unsupported, denied, rejected, simulated, attempted, observed, verified,
failed, and compensated. Simulation requires explicit caller selection.

This module is not release authority: it does not write DuckDB or Quack
state and never emits a closed PCPR release outcome. Live claims require
live evidence. Simulated results are not live.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

INTERFACE: Final = "DatasetsFalseSuccessFallbackRemoval@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/false-success-fallback-removal@1"
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/false-success-fallback-removal-verdict@1"
)
PCPR_011_TASK_ID: Final = "PCPR-011"
PCPR_011_GOAL_ID: Final = "PCPR-G210"
PCPR_010_TASK_ID: Final = "PCPR-010"
PCPR_003_TASK_ID: Final = "PCPR-003"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
PCPR_BOARD_NAMESPACE: Final = "proof-carrying-platform-qualification-and-release-v1"
EVIDENCE_ID: Final = "pcpr/datasets-false-success-fallback-removal@1"

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
CLOSED_NON_SUCCESS_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "unavailable",
        "unsupported",
        "denied",
        "rejected",
        "simulated",
        "attempted",
        "failed",
        "compensated",
    }
)

INIT_RELPATH: Final = "ipfs_datasets_py/__init__.py"
LIBP2P_KIT_RELPATH: Final = "ipfs_datasets_py/p2p_networking/libp2p_kit.py"
LIBP2P_STUB_RELPATH: Final = "ipfs_datasets_py/p2p_networking/libp2p_kit_stub.py"
OUTCOMES_RELPATH: Final = "ipfs_datasets_py/assurance/outcomes.py"

SUCCESS_NEEDLE: Final = '"status": "success"'
STUB_SUCCESS_MESSAGE: Final = "Stub implementation"
FALLBACK_CLASS: Final = "_FallbackIPFSDatasets"
EFFECT_METHODS: Final[frozenset[str]] = frozenset(
    {"download_dataset", "upload_dataset", "create_distributed_dataset"}
)

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_011_false_success_fallbacks.py",
)

SEALED_PATH: Final = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
SEALED_PYTHON: Final = "/usr/bin/python3.12"

FALSE_SUCCESS_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "fallback_download_status_success",
        "fallback_upload_status_success",
        "fallback_class_status_success_literal",
        "libp2p_kit_status_success",
        "libp2p_kit_stub_status_success",
        "libp2p_kit_stub_implementation_success",
        "libp2p_stub_file_stub_implementation_success",
        "runtime_fallback_download_success",
        "runtime_fallback_upload_success",
        "runtime_libp2p_create_success",
        "runtime_libp2p_stub_create_success",
        "runtime_explicit_simulation_represented_as_live",
    }
)


class FalseSuccessFallbackError(Exception):
    """Fail-closed PCPR-011 contract error."""


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
        raise FalseSuccessFallbackError(f"{name} must be a non-empty string")
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise FalseSuccessFallbackError(f"{name} is not an admitted evidence kind")
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise FalseSuccessFallbackError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _read_source(root: Path, relpath: str) -> str | None:
    path = root / relpath
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _class_segment(source: str, class_name: str) -> str | None:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                return segment
            lines = source.splitlines()
            end = node.end_lineno or node.lineno
            return "\n".join(lines[node.lineno - 1 : end])
    return None


def _method_returns_status_success(
    source: str,
    class_name: str,
    method_name: str,
) -> bool | None:
    tree = ast.parse(source)
    class_node: ast.ClassDef | None = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            class_node = node
            break
    if class_node is None:
        return None
    method_node: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for item in class_node.body:
        if (
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == method_name
        ):
            method_node = item
            break
    if method_node is None:
        return None
    for child in ast.walk(method_node):
        if not isinstance(child, ast.Dict):
            continue
        mapping: dict[Any, Any] = {}
        for key, value in zip(child.keys, child.values):
            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
                mapping[key.value] = value.value
        if mapping.get("status") == "success":
            return True
    segment = ast.get_source_segment(source, method_node)
    if segment is None:
        lines = source.splitlines()
        end = method_node.end_lineno or method_node.lineno
        segment = "\n".join(lines[method_node.lineno - 1 : end])
    return SUCCESS_NEEDLE in segment


def _file_pairs_stub_message_with_success(source: str) -> bool:
    if STUB_SUCCESS_MESSAGE not in source or SUCCESS_NEEDLE not in source:
        return False
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        mapping: dict[Any, Any] = {}
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
                mapping[key.value] = value.value
        if (
            mapping.get("status") == "success"
            and STUB_SUCCESS_MESSAGE in str(mapping.get("message") or "")
        ):
            return True
    return False


@dataclass(frozen=True)
class FallbackProbe:
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
class FalseSuccessFallbackVerdict:
    schema: str
    interface: str
    promotion_status: str
    supervisor_disposition: str
    closed_release_outcome: str | None
    release_claim: bool
    completion_authoritative: bool
    contracts_frozen: bool
    duckdb_or_quack_state_written: bool
    false_success_fallback_present: bool
    simulated_results_represented_as_live: bool
    live_solver_qualified: bool
    live_solver_evidence_kind: str
    live_transport_qualified: bool
    live_transport_evidence_kind: str
    this_task_created_competing_authority: bool
    probes: tuple[FallbackProbe, ...]
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
            "false_success_fallback_present": self.false_success_fallback_present,
            "simulated_results_represented_as_live": (
                self.simulated_results_represented_as_live
            ),
            "live_solver_qualified": self.live_solver_qualified,
            "live_solver_evidence_kind": self.live_solver_evidence_kind,
            "live_transport_qualified": self.live_transport_qualified,
            "live_transport_evidence_kind": self.live_transport_evidence_kind,
            "this_task_created_competing_authority": (
                self.this_task_created_competing_authority
            ),
            "blocker_count": len(self.blockers),
            "blockers": list(self.blockers),
            "evidence_kind": "measured",
        }


def _unavailable_file_probe(probe_id: str, relpath: str) -> FallbackProbe:
    return FallbackProbe(
        probe_id=probe_id,
        present=None,
        evidence_kind="unavailable",
        live=False,
        simulated_represented_as_live=False,
        reason=f"{relpath} is missing and is not recorded as empty.",
        details={"relpath": relpath},
    )


def _static_success_probe(
    *,
    probe_id: str,
    present: bool,
    relpath: str,
    reason_absent: str,
    reason_present: str,
    extra: Mapping[str, Any] | None = None,
) -> FallbackProbe:
    return FallbackProbe(
        probe_id=probe_id,
        present=present,
        evidence_kind="measured",
        live=False,
        simulated_represented_as_live=False,
        reason=reason_absent if not present else reason_present,
        details={"relpath": relpath, **dict(extra or {})},
    )


def current_head_static_probes(
    *,
    datasets_root: Path | None = None,
) -> tuple[FallbackProbe, ...]:
    """Measured current-tree AST/source probes. Missing files stay typed unavailable."""

    root = datasets_root or discover_datasets_root()
    if root is None or not root.is_dir():
        return (
            FallbackProbe(
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

    probes: list[FallbackProbe] = []
    init_source = _read_source(root, INIT_RELPATH)
    kit_source = _read_source(root, LIBP2P_KIT_RELPATH)
    stub_source = _read_source(root, LIBP2P_STUB_RELPATH)

    if init_source is None:
        probes.append(_unavailable_file_probe("package_init", INIT_RELPATH))
    else:
        download_success = _method_returns_status_success(
            init_source, FALLBACK_CLASS, "download_dataset"
        )
        upload_success = _method_returns_status_success(
            init_source, FALLBACK_CLASS, "upload_dataset"
        )
        class_segment = _class_segment(init_source, FALLBACK_CLASS)
        class_literal = (
            SUCCESS_NEEDLE in class_segment if class_segment is not None else None
        )
        if download_success is None:
            probes.append(
                FallbackProbe(
                    probe_id="fallback_download_status_success",
                    present=None,
                    evidence_kind="unavailable",
                    live=False,
                    simulated_represented_as_live=False,
                    reason=(
                        f"{FALLBACK_CLASS}.download_dataset is missing and is not "
                        "recorded as empty."
                    ),
                    details={"relpath": INIT_RELPATH},
                )
            )
        else:
            probes.append(
                _static_success_probe(
                    probe_id="fallback_download_status_success",
                    present=bool(download_success),
                    relpath=INIT_RELPATH,
                    reason_absent=(
                        "_FallbackIPFSDatasets.download_dataset does not return "
                        "status success."
                    ),
                    reason_present=(
                        "_FallbackIPFSDatasets.download_dataset still returns "
                        "status success without a real download."
                    ),
                    extra={"method": "download_dataset"},
                )
            )
        if upload_success is None:
            probes.append(
                FallbackProbe(
                    probe_id="fallback_upload_status_success",
                    present=None,
                    evidence_kind="unavailable",
                    live=False,
                    simulated_represented_as_live=False,
                    reason=(
                        f"{FALLBACK_CLASS}.upload_dataset is missing and is not "
                        "recorded as empty."
                    ),
                    details={"relpath": INIT_RELPATH},
                )
            )
        else:
            probes.append(
                _static_success_probe(
                    probe_id="fallback_upload_status_success",
                    present=bool(upload_success),
                    relpath=INIT_RELPATH,
                    reason_absent=(
                        "_FallbackIPFSDatasets.upload_dataset does not return "
                        "status success."
                    ),
                    reason_present=(
                        "_FallbackIPFSDatasets.upload_dataset still returns "
                        "status success without a real upload."
                    ),
                    extra={"method": "upload_dataset"},
                )
            )
        if class_literal is None:
            probes.append(
                FallbackProbe(
                    probe_id="fallback_class_status_success_literal",
                    present=None,
                    evidence_kind="unavailable",
                    live=False,
                    simulated_represented_as_live=False,
                    reason=(
                        f"{FALLBACK_CLASS} is missing and is not recorded as empty."
                    ),
                    details={"relpath": INIT_RELPATH},
                )
            )
        else:
            probes.append(
                _static_success_probe(
                    probe_id="fallback_class_status_success_literal",
                    present=bool(class_literal),
                    relpath=INIT_RELPATH,
                    reason_absent=(
                        "_FallbackIPFSDatasets source does not contain a "
                        "status-success literal."
                    ),
                    reason_present=(
                        "_FallbackIPFSDatasets source still contains a "
                        "status-success literal."
                    ),
                )
            )

    if kit_source is None:
        probes.append(_unavailable_file_probe("libp2p_kit", LIBP2P_KIT_RELPATH))
    else:
        kit_method = _method_returns_status_success(
            kit_source, "DistributedDatasetManager", "create_distributed_dataset"
        )
        kit_pair = _file_pairs_stub_message_with_success(kit_source)
        if kit_method is None:
            probes.append(
                FallbackProbe(
                    probe_id="libp2p_kit_status_success",
                    present=None,
                    evidence_kind="unavailable",
                    live=False,
                    simulated_represented_as_live=False,
                    reason=(
                        "DistributedDatasetManager.create_distributed_dataset is "
                        "missing and is not recorded as empty."
                    ),
                    details={"relpath": LIBP2P_KIT_RELPATH},
                )
            )
        else:
            probes.append(
                _static_success_probe(
                    probe_id="libp2p_kit_status_success",
                    present=bool(kit_method),
                    relpath=LIBP2P_KIT_RELPATH,
                    reason_absent=(
                        "libp2p_kit.create_distributed_dataset does not return "
                        "status success."
                    ),
                    reason_present=(
                        "libp2p_kit.create_distributed_dataset still returns "
                        "status success without a real transport effect."
                    ),
                )
            )
        probes.append(
            _static_success_probe(
                probe_id="libp2p_kit_stub_implementation_success",
                present=kit_pair,
                relpath=LIBP2P_KIT_RELPATH,
                reason_absent=(
                    "libp2p_kit no longer pairs Stub implementation with status success."
                ),
                reason_present=(
                    "libp2p_kit still returns Stub implementation with status success."
                ),
            )
        )

    if stub_source is None:
        probes.append(
            _unavailable_file_probe("libp2p_kit_stub", LIBP2P_STUB_RELPATH)
        )
    else:
        stub_method = _method_returns_status_success(
            stub_source, "DistributedDatasetManager", "create_distributed_dataset"
        )
        stub_pair = _file_pairs_stub_message_with_success(stub_source)
        if stub_method is None:
            probes.append(
                FallbackProbe(
                    probe_id="libp2p_kit_stub_status_success",
                    present=None,
                    evidence_kind="unavailable",
                    live=False,
                    simulated_represented_as_live=False,
                    reason=(
                        "libp2p_kit_stub.create_distributed_dataset is missing "
                        "and is not recorded as empty."
                    ),
                    details={"relpath": LIBP2P_STUB_RELPATH},
                )
            )
        else:
            probes.append(
                _static_success_probe(
                    probe_id="libp2p_kit_stub_status_success",
                    present=bool(stub_method),
                    relpath=LIBP2P_STUB_RELPATH,
                    reason_absent=(
                        "libp2p_kit_stub.create_distributed_dataset does not "
                        "return status success."
                    ),
                    reason_present=(
                        "libp2p_kit_stub.create_distributed_dataset still returns "
                        "status success without a real transport effect."
                    ),
                )
            )
        probes.append(
            _static_success_probe(
                probe_id="libp2p_stub_file_stub_implementation_success",
                present=stub_pair,
                relpath=LIBP2P_STUB_RELPATH,
                reason_absent=(
                    "libp2p_kit_stub no longer pairs Stub implementation with "
                    "status success."
                ),
                reason_present=(
                    "libp2p_kit_stub still returns Stub implementation with "
                    "status success."
                ),
            )
        )

    probes.append(
        FallbackProbe(
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
        FallbackProbe(
            probe_id="live_transport_qualification",
            present=None,
            evidence_kind="unavailable",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "This task does not qualify live libp2p or IPFS transport. Missing "
                "live backends stay typed unavailable and are not recorded as passing."
            ),
        )
    )
    return tuple(probes)


def _assert_non_success_payload(
    payload: Mapping[str, Any],
    *,
    allow_simulated: bool = False,
) -> dict[str, Any]:
    status = str(payload.get("status") or "").strip().lower()
    outcome = str(payload.get("outcome") or "")
    ok = payload.get("ok")
    live = payload.get("live")
    simulated = bool(payload.get("simulated"))
    represented_as_live = bool(payload.get("simulated_represented_as_live"))
    if status == "success" or ok is True:
        raise FalseSuccessFallbackError(
            "fallback payload still claims success without a real effect"
        )
    if status not in CLOSED_NON_SUCCESS_STATUSES and outcome.lower() not in {
        item.capitalize() if item != "unavailable" else "Unavailable"
        for item in CLOSED_NON_SUCCESS_STATUSES
    }:
        if status not in {"unavailable", "simulated"}:
            raise FalseSuccessFallbackError(
                f"fallback payload status {status!r} is not a closed non-success status"
            )
    if represented_as_live:
        raise FalseSuccessFallbackError(
            "simulated results must not be represented as live"
        )
    if live is True:
        raise FalseSuccessFallbackError("fallback payload must not claim live evidence")
    if simulated and not allow_simulated:
        raise FalseSuccessFallbackError(
            "simulation requires explicit caller selection"
        )
    return dict(payload)


def probe_fallback_runtime() -> dict[str, Any]:
    """In-process runtime observation of inventoried fallback surfaces."""

    from ipfs_datasets_py import _FallbackIPFSDatasets
    from ipfs_datasets_py.p2p_networking import libp2p_kit, libp2p_kit_stub

    fallback = _FallbackIPFSDatasets()
    download = fallback.download_dataset("example")
    upload = fallback.upload_dataset("example")
    kit = libp2p_kit.DistributedDatasetManager()
    kit_create = kit.create_distributed_dataset("example")
    stub = libp2p_kit_stub.DistributedDatasetManager()
    stub_create = stub.create_distributed_dataset("example")
    simulated_download = fallback.download_dataset(
        "example", explicit_simulation=True
    )
    simulated_kit = libp2p_kit.DistributedDatasetManager(
        explicit_simulation=True
    ).create_distributed_dataset("example")

    download = _assert_non_success_payload(download)
    upload = _assert_non_success_payload(upload)
    kit_create = _assert_non_success_payload(kit_create)
    stub_create = _assert_non_success_payload(stub_create)
    simulated_download = _assert_non_success_payload(
        simulated_download, allow_simulated=True
    )
    simulated_kit = _assert_non_success_payload(
        simulated_kit, allow_simulated=True
    )
    if simulated_download.get("status") not in {"simulated", "unavailable"}:
        raise FalseSuccessFallbackError(
            "explicit simulation must remain Simulated or Unavailable, never success"
        )
    if simulated_download.get("live") is True:
        raise FalseSuccessFallbackError("explicit simulation must not be live")
    if simulated_kit.get("status") != "simulated":
        raise FalseSuccessFallbackError(
            "explicit libp2p simulation must return Simulated, never success"
        )
    if simulated_kit.get("simulated_represented_as_live"):
        raise FalseSuccessFallbackError(
            "explicit simulation must not be represented as live"
        )

    return {
        "status": "observed",
        "evidence_kind": "measured",
        "live": False,
        "simulated_represented_as_live": False,
        "fallback_status": fallback.status,
        "download": download,
        "upload": upload,
        "libp2p_kit_create": kit_create,
        "libp2p_stub_create": stub_create,
        "explicit_simulation_download": simulated_download,
        "explicit_simulation_libp2p": simulated_kit,
        "download_success": download.get("status") == "success",
        "upload_success": upload.get("status") == "success",
        "libp2p_success": kit_create.get("status") == "success",
        "libp2p_stub_success": stub_create.get("status") == "success",
        "explicit_simulation_live": bool(
            simulated_download.get("live") or simulated_kit.get("live")
        ),
        "reason": (
            "Inventoried fallbacks return typed unavailable or explicit simulated "
            "outcomes; none return status success or live."
        ),
    }


def current_head_runtime_probes() -> tuple[FallbackProbe, ...]:
    observation = probe_fallback_runtime()
    return (
        FallbackProbe(
            probe_id="runtime_fallback_download_success",
            present=bool(observation["download_success"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Runtime fallback download returns typed unavailable, not success."
                if not observation["download_success"]
                else "Runtime fallback download still returns status success."
            ),
            details={"status": observation["download"].get("status")},
        ),
        FallbackProbe(
            probe_id="runtime_fallback_upload_success",
            present=bool(observation["upload_success"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Runtime fallback upload returns typed unavailable, not success."
                if not observation["upload_success"]
                else "Runtime fallback upload still returns status success."
            ),
            details={"status": observation["upload"].get("status")},
        ),
        FallbackProbe(
            probe_id="runtime_libp2p_create_success",
            present=bool(observation["libp2p_success"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Runtime libp2p_kit create returns typed unavailable, not success."
                if not observation["libp2p_success"]
                else "Runtime libp2p_kit create still returns status success."
            ),
            details={"status": observation["libp2p_kit_create"].get("status")},
        ),
        FallbackProbe(
            probe_id="runtime_libp2p_stub_create_success",
            present=bool(observation["libp2p_stub_success"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Runtime libp2p_kit_stub create returns typed unavailable, not success."
                if not observation["libp2p_stub_success"]
                else "Runtime libp2p_kit_stub create still returns status success."
            ),
            details={"status": observation["libp2p_stub_create"].get("status")},
        ),
        FallbackProbe(
            probe_id="runtime_explicit_simulation_represented_as_live",
            present=bool(observation["explicit_simulation_live"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Explicit simulation is labeled Simulated and is not represented as live."
                if not observation["explicit_simulation_live"]
                else "Explicit simulation was represented as live."
            ),
            details={
                "download_status": observation["explicit_simulation_download"].get(
                    "status"
                ),
                "libp2p_status": observation["explicit_simulation_libp2p"].get(
                    "status"
                ),
            },
        ),
    )


def qualify_false_success_fallback_removal(
    probes: Sequence[FallbackProbe],
) -> FalseSuccessFallbackVerdict:
    if not probes:
        raise FalseSuccessFallbackError("at least one probe is required")
    normalized: list[FallbackProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise FalseSuccessFallbackError(
                "live claims require measured_live evidence"
            )
        if probe.simulated_represented_as_live:
            raise FalseSuccessFallbackError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id in {
            "live_solver_qualification",
            "live_transport_qualification",
        }:
            continue
        if probe.present is True and probe.probe_id in FALSE_SUCCESS_PROBE_IDS:
            blockers.append(probe.probe_id)
        if probe.present is None and probe.evidence_kind == "unavailable":
            if probe.probe_id == "datasets_source_tree":
                blockers.append(probe.probe_id)

    false_success_present = any(
        p.present is True and p.probe_id in FALSE_SUCCESS_PROBE_IDS
        for p in normalized
    )
    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_011_TASK_ID,
        "goal_id": PCPR_011_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "false_success_fallback_present": false_success_present,
        "simulated_results_represented_as_live": False,
        "live_solver_qualified": False,
        "live_solver_evidence_kind": "unavailable",
        "live_transport_qualified": False,
        "live_transport_evidence_kind": "unavailable",
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
    }
    return FalseSuccessFallbackVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status=promotion_status,
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        false_success_fallback_present=false_success_present,
        simulated_results_represented_as_live=False,
        live_solver_qualified=False,
        live_solver_evidence_kind="unavailable",
        live_transport_qualified=False,
        live_transport_evidence_kind="unavailable",
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
    )


def qualify_current_head_false_success_fallbacks() -> FalseSuccessFallbackVerdict:
    return qualify_false_success_fallback_removal(current_head_static_probes())


# Pinned identity of the ordinary current-head static verdict. Drift means
# the default payload changed and the outer receipt must be regenerated.
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeerad6iwavifwwgrmh5utyxjt37gomi2xfbof5khgzslmhbzoisqkzaa"
)


def pcpr_011_receipt_promotion(
    verdict: FalseSuccessFallbackVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise FalseSuccessFallbackError(
            "false-success fallback removal must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise FalseSuccessFallbackError(
            "false-success fallback removal must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise FalseSuccessFallbackError(
            "false-success fallback removal completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise FalseSuccessFallbackError(
            "false-success fallback removal must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise FalseSuccessFallbackError(
            "promotion_status must not be a closed release outcome"
        )
    return verdict.to_mapping()


__all__ = [
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "EVIDENCE_ID",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "FallbackProbe",
    "FalseSuccessFallbackError",
    "FalseSuccessFallbackVerdict",
    "PCPR_011_GOAL_ID",
    "PCPR_011_TASK_ID",
    "SCHEMA",
    "content_identity",
    "current_head_runtime_probes",
    "current_head_static_probes",
    "discover_datasets_root",
    "pcpr_011_receipt_promotion",
    "probe_fallback_runtime",
    "qualify_current_head_false_success_fallbacks",
    "qualify_false_success_fallback_removal",
]
