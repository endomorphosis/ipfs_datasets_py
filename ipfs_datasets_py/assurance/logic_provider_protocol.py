"""Fail-closed PCPR-013 LogicProviderProtocol canonicalization.

``LogicProviderProtocol@2`` is the canonical provider protocol. Free-form
payloads cannot mint executable ``BackendRequest@2`` values. The version-1
adapter is explicit and fail-closed. Advisory v1 data is non-authoritative.
Executable work requires positive finite bounds.

This module is not release authority: it does not write DuckDB or Quack
state and never emits a closed PCPR release outcome. Live claims require
live evidence. Simulated results are not live. Missing solvers stay typed
unavailable.
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

INTERFACE: Final = "DatasetsLogicProviderProtocolCanonical@1"
SCHEMA: Final = "ipfs_datasets_py/assurance/logic-provider-protocol-canonical@1"
VERDICT_SCHEMA: Final = (
    "ipfs_datasets_py/assurance/logic-provider-protocol-canonical-verdict@1"
)
PCPR_013_TASK_ID: Final = "PCPR-013"
PCPR_013_GOAL_ID: Final = "PCPR-G220"
PCPR_012_TASK_ID: Final = "PCPR-012"
PCPR_003_TASK_ID: Final = "PCPR-003"
PCPR_PROGRAM_ID: Final = "proof-carrying-platform-qualification-and-release-v1"
PCPR_BOARD_NAMESPACE: Final = "proof-carrying-platform-qualification-and-release-v1"
EVIDENCE_ID: Final = "pcpr/datasets-logic-provider-protocol-canonical@1"

CANONICAL_PROTOCOL_INTERFACE: Final = "LogicProviderProtocol@2"
CANONICAL_PROTOCOL_VERSION: Final = 2
V1_PROTOCOL_INTERFACE: Final = "LogicProviderProtocol@1"
V1_ADAPTER_INTERFACE: Final = "LogicProviderProtocolV1Adapter@1"
V1_PROTOCOL_VERSION: Final = 1

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

PROVIDER_RELPATH: Final = "ipfs_datasets_py/logic/backends/provider.py"
PROTOCOL_V2_RELPATH: Final = "ipfs_datasets_py/logic/backends/protocol_v2.py"
V1_ADAPTER_RELPATH: Final = "ipfs_datasets_py/logic/backends/protocol_v1_adapter.py"
MANIFEST_RELPATH: Final = "ipfs_datasets_py/logic/platform/manifest.py"

HERMETIC_CANDIDATE_SUITES: Final[tuple[str, ...]] = (
    "tests/unit/test_pcpr_013_logic_provider_protocol.py",
)

SEALED_PATH: Final = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
SEALED_PYTHON: Final = "/usr/bin/python3.12"

REQUIRED_GOOD_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "protocol_v2_version_is_2",
        "protocol_v2_canonical_alias",
        "protocol_v2_canonical_flag",
        "v1_adapter_explicit",
        "v1_not_canonical",
        "manifest_advertises_v2",
        "canonical_alias_is_v2",
        "capability_non_executable",
        "canonical_write_admits_typed_v2",
    }
)
FORBIDDEN_PRESENT_PROBE_IDS: Final[frozenset[str]] = frozenset(
    {
        "freeform_payload_admitted_as_v2",
        "new_write_accepted_v1",
        "v1_payload_minted_backend_request",
        "executable_missing_bounds_admitted",
        "advisory_carries_executable_authority",
        "runtime_unavailable_represented_as_live",
    }
)


class LogicProviderProtocolCanonicalError(Exception):
    """Fail-closed PCPR-013 contract error."""


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
        raise LogicProviderProtocolCanonicalError(
            f"{name} must be a non-empty string"
        )
    return value.strip()


def _kind(value: Any, name: str) -> str:
    kind = _text(value, name)
    if kind not in EVIDENCE_KINDS:
        raise LogicProviderProtocolCanonicalError(
            f"{name} is not an admitted evidence kind"
        )
    return kind


def _reject_closed_release_value(value: Any, name: str) -> None:
    if isinstance(value, str) and value in CLOSED_RELEASE_OUTCOMES:
        raise LogicProviderProtocolCanonicalError(
            f"{name} must not be a closed PCPR release outcome"
        )


def _read_source(root: Path, relpath: str) -> str | None:
    path = root / relpath
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _assign_int_constant(source: str, name: str) -> int | None:
    tree = ast.parse(source)
    for node in tree.body:
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            return value.value
        if (
            isinstance(value, ast.UnaryOp)
            and isinstance(value.op, ast.USub)
            and isinstance(value.operand, ast.Constant)
            and isinstance(value.operand.value, int)
        ):
            return -value.operand.value
    return None


def _assign_bool_constant(source: str, name: str) -> bool | None:
    tree = ast.parse(source)
    for node in tree.body:
        targets: list[ast.AST] = []
        value: ast.AST | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, bool):
            return value.value
    return None


def _assigns_alias(source: str, name: str, expected: str) -> bool:
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            continue
        if isinstance(node.value, ast.Name) and node.value.id == expected:
            return True
    return False


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
class LogicProviderProtocolVerdict:
    schema: str
    interface: str
    promotion_status: str
    supervisor_disposition: str
    closed_release_outcome: str | None
    release_claim: bool
    completion_authoritative: bool
    contracts_frozen: bool
    duckdb_or_quack_state_written: bool
    v1_freeform_executable_present: bool
    logic_provider_protocol_canonical: bool
    simulated_results_represented_as_live: bool
    live_solver_qualified: bool
    live_solver_evidence_kind: str
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
            "v1_freeform_executable_present": self.v1_freeform_executable_present,
            "logic_provider_protocol_canonical": (
                self.logic_provider_protocol_canonical
            ),
            "simulated_results_represented_as_live": (
                self.simulated_results_represented_as_live
            ),
            "live_solver_qualified": self.live_solver_qualified,
            "live_solver_evidence_kind": self.live_solver_evidence_kind,
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


def _static_flag_probe(
    *,
    probe_id: str,
    present: bool,
    relpath: str,
    reason_present: str,
    reason_absent: str,
    extra: Mapping[str, Any] | None = None,
) -> OutcomeProbe:
    return OutcomeProbe(
        probe_id=probe_id,
        present=present,
        evidence_kind="measured",
        live=False,
        simulated_represented_as_live=False,
        reason=reason_present if present else reason_absent,
        details={"relpath": relpath, **dict(extra or {})},
    )


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
    v2_source = _read_source(root, PROTOCOL_V2_RELPATH)
    v1_source = _read_source(root, PROVIDER_RELPATH)
    adapter_source = _read_source(root, V1_ADAPTER_RELPATH)
    manifest_source = _read_source(root, MANIFEST_RELPATH)

    if v2_source is None:
        probes.append(_unavailable_file_probe("protocol_v2", PROTOCOL_V2_RELPATH))
    else:
        version = _assign_int_constant(v2_source, "LOGIC_PROVIDER_PROTOCOL_VERSION")
        canonical = _assign_bool_constant(v2_source, "LOGIC_PROVIDER_PROTOCOL_CANONICAL")
        alias = _assigns_alias(
            v2_source, "LogicProviderProtocol", "LogicProviderProtocolV2"
        )
        probes.append(
            _static_flag_probe(
                probe_id="protocol_v2_version_is_2",
                present=version == CANONICAL_PROTOCOL_VERSION,
                relpath=PROTOCOL_V2_RELPATH,
                reason_present="LogicProviderProtocol@2 protocol_version is 2.",
                reason_absent="LogicProviderProtocol@2 protocol_version is not 2.",
                extra={"version": version},
            )
        )
        probes.append(
            _static_flag_probe(
                probe_id="protocol_v2_canonical_flag",
                present=canonical is True,
                relpath=PROTOCOL_V2_RELPATH,
                reason_present="LogicProviderProtocol@2 is marked canonical.",
                reason_absent="LogicProviderProtocol@2 is not marked canonical.",
                extra={"canonical": canonical},
            )
        )
        probes.append(
            _static_flag_probe(
                probe_id="protocol_v2_canonical_alias",
                present=alias,
                relpath=PROTOCOL_V2_RELPATH,
                reason_present=(
                    "LogicProviderProtocol is an alias of LogicProviderProtocolV2."
                ),
                reason_absent=(
                    "LogicProviderProtocol is not aliased to LogicProviderProtocolV2."
                ),
            )
        )

    if v1_source is None:
        probes.append(_unavailable_file_probe("provider_v1", PROVIDER_RELPATH))
    else:
        version = _assign_int_constant(v1_source, "LOGIC_PROVIDER_PROTOCOL_VERSION")
        canonical = _assign_bool_constant(
            v1_source, "LOGIC_PROVIDER_PROTOCOL_CANONICAL"
        )
        probes.append(
            _static_flag_probe(
                probe_id="v1_not_canonical",
                present=(
                    version == V1_PROTOCOL_VERSION and canonical is False
                ),
                relpath=PROVIDER_RELPATH,
                reason_present=(
                    "LogicProvider@1 remains importable as compatibility-only, "
                    "not canonical."
                ),
                reason_absent=(
                    "LogicProvider@1 is missing the compatibility-only canonical=false "
                    "mark, or is no longer version 1."
                ),
                extra={"version": version, "canonical": canonical},
            )
        )

    if adapter_source is None:
        probes.append(_unavailable_file_probe("v1_adapter", V1_ADAPTER_RELPATH))
    else:
        explicit = (
            f'"{V1_ADAPTER_INTERFACE}"' in adapter_source
            and "admit_new_provider_write" in adapter_source
            and "V1BypassBackendRequestError" in adapter_source
        )
        adapter_canonical = _assign_bool_constant(
            adapter_source, "PROTOCOL_V1_ADAPTER_CANONICAL"
        )
        probes.append(
            _static_flag_probe(
                probe_id="v1_adapter_explicit",
                present=explicit and adapter_canonical is False,
                relpath=V1_ADAPTER_RELPATH,
                reason_present=(
                    "The version-1 adapter is explicit, fail-closed, and not canonical."
                ),
                reason_absent=(
                    "The version-1 adapter is missing, canonical, or not fail-closed."
                ),
                extra={"adapter_canonical": adapter_canonical},
            )
        )

    if manifest_source is None:
        probes.append(_unavailable_file_probe("platform_manifest", MANIFEST_RELPATH))
    else:
        advertises_v2 = (
            f'"{CANONICAL_PROTOCOL_INTERFACE}"' in manifest_source
            or "LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE" in manifest_source
        )
        probes.append(
            _static_flag_probe(
                probe_id="manifest_advertises_v2",
                present=advertises_v2,
                relpath=MANIFEST_RELPATH,
                reason_present=(
                    "LogicPlatformManifest advertises LogicProviderProtocol@2."
                ),
                reason_absent=(
                    "LogicPlatformManifest does not advertise LogicProviderProtocol@2."
                ),
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
    return tuple(probes)


def _v1_envelope(operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "ipfs_datasets_py/logic-provider-request@1",
        "protocol_version": 1,
        "request_id": "req:pcpr-013-v1",
        "operation": operation,
        "payload": dict(payload),
        "network_allowed": False,
    }


def probe_protocol_runtime() -> dict[str, Any]:
    """Hermetic runtime observation of canonical protocol admission.

    No solver, network, installer, or live provider is invoked.
    """

    from ipfs_datasets_py.logic.backends.protocol_v1_adapter import (
        PROTOCOL_V1_ADAPTER_CANONICAL,
        PROTOCOL_V1_ADAPTER_INTERFACE,
        V1AdapterDisposition,
        adapt_v1_provider_request,
        admit_new_provider_write,
    )
    from ipfs_datasets_py.logic.backends.protocol_v2 import (
        LOGIC_PROVIDER_PROTOCOL_CANONICAL,
        LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE,
        LOGIC_PROVIDER_PROTOCOL_VERSION,
        ArbitraryPayloadProtocolError,
        CapabilityRequestV2,
        LogicProviderProtocol,
        LogicProviderProtocolV2,
        MissingExecutableBoundsError,
        ProtocolV2AdmissionError,
        ProtocolV2Error,
        admit_canonical_provider_request,
        admit_provider_request_v2,
    )
    from ipfs_datasets_py.logic.backends.provider import (
        LOGIC_PROVIDER_PROTOCOL_CANONICAL as V1_CANONICAL,
        LOGIC_PROVIDER_PROTOCOL_VERSION as V1_VERSION,
    )
    from ipfs_datasets_py.logic.platform.manifest import (
        DEFAULT_LOGIC_PLATFORM_MANIFEST,
        LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE as MANIFEST_V2_INTERFACE,
    )

    freeform_admitted = False
    freeform_reason = ""
    try:
        admit_provider_request_v2(
            {
                "schema_version": "ipfs_datasets_py/logic-provider-request@1",
                "protocol_version": 1,
                "operation": "prove",
                "payload": {"formula": "P"},
                "request_id": "req:pcpr-013-freeform",
            }
        )
        freeform_admitted = True
        freeform_reason = "v1 generic payload was admitted as LogicProviderProtocol@2"
    except (ArbitraryPayloadProtocolError, ProtocolV2AdmissionError, ProtocolV2Error) as error:
        freeform_reason = str(error)

    new_write_v1_accepted = False
    new_write_reason = ""
    try:
        admit_new_provider_write(_v1_envelope("prove", {"formula": "P"}))
        new_write_v1_accepted = True
        new_write_reason = "new-write gate accepted a v1 generic envelope"
    except (ArbitraryPayloadProtocolError, ProtocolV2AdmissionError, ProtocolV2Error) as error:
        new_write_reason = str(error)

    minted_backend = False
    mint_reason = ""
    bypass = adapt_v1_provider_request(
        _v1_envelope("prove", {"backend_request": {"request_id": "forged"}})
    )
    if (
        bypass.disposition is V1AdapterDisposition.REJECTED
        and bypass.backend_request is None
        and bypass.request_v2 is None
        and not bypass.executable
    ):
        mint_reason = bypass.reason
    else:
        minted_backend = True
        mint_reason = (
            f"v1 payload containing backend_request was {bypass.disposition.value} "
            "instead of rejected without BackendRequest@2"
        )

    advisory_executable = False
    advisory_reason = ""
    advisory = adapt_v1_provider_request(_v1_envelope("prove", {"statement": "P"}))
    if advisory.disposition is V1AdapterDisposition.ADVISORY:
        if (
            advisory.executable
            or advisory.backend_request is not None
            or advisory.request_v2 is not None
        ):
            advisory_executable = True
            advisory_reason = "advisory v1 elevation carried executable authority"
        elif advisory.advisory is None or advisory.advisory.executable:
            advisory_executable = True
            advisory_reason = "advisory retention was marked executable"
        else:
            advisory_reason = (
                "v1 prove without an external BackendRequest@2 stayed advisory"
            )
    else:
        advisory_executable = True
        advisory_reason = (
            f"v1 prove without BackendRequest@2 was {advisory.disposition.value}, "
            "not advisory"
        )

    missing_bounds_admitted = False
    bounds_reason = ""
    try:
        admit_canonical_provider_request(
            {
                "operation": "prove",
                "request_id": "req:pcpr-013-no-bounds",
                "protocol_version": 2,
                "mode": "prove",
                "statement": "P",
            }
        )
        missing_bounds_admitted = True
        bounds_reason = "executable prove was admitted without bounds"
    except (
        MissingExecutableBoundsError,
        ProtocolV2AdmissionError,
        ProtocolV2Error,
    ) as error:
        bounds_reason = str(error)

    capability = CapabilityRequestV2(
        request_id="req:pcpr-013-cap",
        provider_id="pcpr-013",
    )
    admitted_cap = admit_canonical_provider_request(capability)
    canonical_write_ok = admitted_cap.operation.value == "capability"

    alias_is_v2 = LogicProviderProtocol is LogicProviderProtocolV2
    v2_canonical = LOGIC_PROVIDER_PROTOCOL_CANONICAL is True
    v2_version = LOGIC_PROVIDER_PROTOCOL_VERSION == CANONICAL_PROTOCOL_VERSION
    v1_not_canonical = V1_CANONICAL is False and V1_VERSION == V1_PROTOCOL_VERSION
    adapter_not_canonical = PROTOCOL_V1_ADAPTER_CANONICAL is False
    manifest_v2 = (
        DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions.get(
            LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE
        )
        == "2"
        or DEFAULT_LOGIC_PLATFORM_MANIFEST.interface_versions.get(
            MANIFEST_V2_INTERFACE
        )
        == "2"
    )
    operation_v2 = (
        DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions.get("prove") == "2"
        and DEFAULT_LOGIC_PLATFORM_MANIFEST.operation_versions.get("check") == "2"
    )

    represented_as_live = False
    return {
        "status": "observed",
        "evidence_kind": "measured",
        "live": False,
        "simulated_represented_as_live": represented_as_live,
        "freeform_admitted": freeform_admitted,
        "freeform_reason": freeform_reason,
        "new_write_v1_accepted": new_write_v1_accepted,
        "new_write_reason": new_write_reason,
        "minted_backend": minted_backend,
        "mint_reason": mint_reason,
        "advisory_executable": advisory_executable,
        "advisory_reason": advisory_reason,
        "advisory_disposition": advisory.disposition.value,
        "missing_bounds_admitted": missing_bounds_admitted,
        "bounds_reason": bounds_reason,
        "canonical_write_ok": canonical_write_ok,
        "capability_bounds": getattr(admitted_cap, "bounds", None) is not None,
        "capability_backend": getattr(admitted_cap, "backend_request", None)
        is not None,
        "alias_is_v2": alias_is_v2,
        "v2_canonical": v2_canonical,
        "v2_version": v2_version,
        "v1_not_canonical": v1_not_canonical,
        "adapter_not_canonical": adapter_not_canonical,
        "adapter_interface": PROTOCOL_V1_ADAPTER_INTERFACE,
        "canonical_interface": LOGIC_PROVIDER_PROTOCOL_V2_INTERFACE,
        "manifest_v2": manifest_v2,
        "operation_v2": operation_v2,
        "reason": (
            "LogicProviderProtocol@2 is the canonical write path; v1 generics "
            "cannot mint BackendRequest@2; advisory v1 data is non-authoritative."
        ),
    }


def current_head_runtime_probes() -> tuple[OutcomeProbe, ...]:
    observation = probe_protocol_runtime()
    live = bool(observation["live"] or observation["simulated_represented_as_live"])
    return (
        OutcomeProbe(
            probe_id="freeform_payload_admitted_as_v2",
            present=bool(observation["freeform_admitted"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Free-form v1 payloads are not admitted as LogicProviderProtocol@2."
                if not observation["freeform_admitted"]
                else "Free-form v1 payload was admitted as LogicProviderProtocol@2."
            ),
            details={"reason": observation["freeform_reason"]},
        ),
        OutcomeProbe(
            probe_id="new_write_accepted_v1",
            present=bool(observation["new_write_v1_accepted"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "New provider writes reject v1 generic envelopes."
                if not observation["new_write_v1_accepted"]
                else "New provider writes still accept v1 generic envelopes."
            ),
            details={"reason": observation["new_write_reason"]},
        ),
        OutcomeProbe(
            probe_id="v1_payload_minted_backend_request",
            present=bool(observation["minted_backend"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "v1 free-form payloads cannot mint executable BackendRequest@2."
                if not observation["minted_backend"]
                else "v1 free-form payload minted or bypassed BackendRequest@2."
            ),
            details={"reason": observation["mint_reason"]},
        ),
        OutcomeProbe(
            probe_id="executable_missing_bounds_admitted",
            present=bool(observation["missing_bounds_admitted"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Executable LogicProviderProtocol@2 operations require positive finite bounds."
                if not observation["missing_bounds_admitted"]
                else "An executable operation was admitted without bounds."
            ),
            details={"reason": observation["bounds_reason"]},
        ),
        OutcomeProbe(
            probe_id="advisory_carries_executable_authority",
            present=bool(observation["advisory_executable"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Advisory v1 data remains non-authoritative and non-executable."
                if not observation["advisory_executable"]
                else "Advisory v1 data carried executable authority."
            ),
            details={
                "disposition": observation["advisory_disposition"],
                "reason": observation["advisory_reason"],
            },
        ),
        OutcomeProbe(
            probe_id="capability_non_executable",
            present=(
                bool(observation["canonical_write_ok"])
                and not observation["capability_bounds"]
                and not observation["capability_backend"]
            ),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Capability remains a non-executable typed @2 request."
                if observation["canonical_write_ok"]
                and not observation["capability_bounds"]
                else "Capability request was not admitted as a non-executable @2 body."
            ),
        ),
        OutcomeProbe(
            probe_id="canonical_write_admits_typed_v2",
            present=bool(observation["canonical_write_ok"] and observation["manifest_v2"]),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Canonical write admits typed LogicProviderProtocol@2 and the "
                "platform handshake advertises @2."
                if observation["canonical_write_ok"] and observation["manifest_v2"]
                else "Canonical write or handshake advertisement of @2 failed."
            ),
            details={
                "manifest_v2": observation["manifest_v2"],
                "operation_v2": observation["operation_v2"],
            },
        ),
        OutcomeProbe(
            probe_id="canonical_alias_is_v2",
            present=bool(
                observation["alias_is_v2"]
                and observation["v2_canonical"]
                and observation["v2_version"]
                and observation["v1_not_canonical"]
                and observation["adapter_not_canonical"]
            ),
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "LogicProviderProtocol names LogicProviderProtocolV2; v1 and the "
                "v1 adapter remain compatibility-only."
                if observation["alias_is_v2"]
                else "LogicProviderProtocol is not the canonical @2 surface."
            ),
            details={
                "canonical_interface": observation["canonical_interface"],
                "adapter_interface": observation["adapter_interface"],
            },
        ),
        OutcomeProbe(
            probe_id="runtime_unavailable_represented_as_live",
            present=live,
            evidence_kind="measured",
            live=False,
            simulated_represented_as_live=False,
            reason=(
                "Protocol canonicalization probes are not represented as live."
                if not live
                else "Protocol canonicalization was represented as live."
            ),
        ),
    )


def qualify_logic_provider_protocol_canonical(
    probes: Sequence[OutcomeProbe],
) -> LogicProviderProtocolVerdict:
    if not probes:
        raise LogicProviderProtocolCanonicalError("at least one probe is required")
    normalized: list[OutcomeProbe] = []
    blockers: list[str] = []
    for probe in probes:
        kind = _kind(probe.evidence_kind, "evidence_kind")
        if probe.live and kind != "measured_live":
            raise LogicProviderProtocolCanonicalError(
                "live claims require measured_live evidence"
            )
        if probe.simulated_represented_as_live:
            raise LogicProviderProtocolCanonicalError(
                "simulated results must not be represented as live"
            )
        normalized.append(probe)
        if probe.probe_id == "live_solver_qualification":
            continue
        if probe.probe_id in FORBIDDEN_PRESENT_PROBE_IDS and probe.present is True:
            blockers.append(probe.probe_id)
        if probe.probe_id in REQUIRED_GOOD_PROBE_IDS and probe.present is not True:
            blockers.append(probe.probe_id)
        if probe.present is None and probe.evidence_kind == "unavailable":
            if probe.probe_id == "datasets_source_tree":
                blockers.append(probe.probe_id)

    v1_freeform_present = any(
        p.present is True and p.probe_id in FORBIDDEN_PRESENT_PROBE_IDS
        for p in normalized
    )
    canonical = not blockers
    promotion_status = "rnd_non_promoted"
    _reject_closed_release_value(promotion_status, "promotion_status")
    payload = {
        "schema": VERDICT_SCHEMA,
        "interface": INTERFACE,
        "task_id": PCPR_013_TASK_ID,
        "goal_id": PCPR_013_GOAL_ID,
        "promotion_status": promotion_status,
        "supervisor_disposition": "supervisor_non_promoted",
        "closed_release_outcome": None,
        "release_claim": False,
        "completion_authoritative": False,
        "contracts_frozen": False,
        "duckdb_or_quack_state_written": False,
        "v1_freeform_executable_present": v1_freeform_present,
        "logic_provider_protocol_canonical": canonical,
        "simulated_results_represented_as_live": False,
        "live_solver_qualified": False,
        "live_solver_evidence_kind": "unavailable",
        "this_task_created_competing_authority": False,
        "probes": [item.to_mapping() for item in normalized],
        "blockers": list(dict.fromkeys(blockers)),
    }
    return LogicProviderProtocolVerdict(
        schema=VERDICT_SCHEMA,
        interface=INTERFACE,
        promotion_status=promotion_status,
        supervisor_disposition="supervisor_non_promoted",
        closed_release_outcome=None,
        release_claim=False,
        completion_authoritative=False,
        contracts_frozen=False,
        duckdb_or_quack_state_written=False,
        v1_freeform_executable_present=v1_freeform_present,
        logic_provider_protocol_canonical=canonical,
        simulated_results_represented_as_live=False,
        live_solver_qualified=False,
        live_solver_evidence_kind="unavailable",
        this_task_created_competing_authority=False,
        probes=tuple(normalized),
        blockers=tuple(dict.fromkeys(blockers)),
        verdict_cid=content_identity(payload),
    )


def qualify_current_head_logic_provider_protocol() -> LogicProviderProtocolVerdict:
    return qualify_logic_provider_protocol_canonical(current_head_static_probes())


# Pinned identity of the ordinary current-head static verdict. Drift means
# the default payload changed and the outer receipt must be regenerated.
CURRENT_HEAD_NON_PROMOTION_VERDICT_CID: Final = (
    "baguqeerazronp37ld63hphyesw2o3vxhv24e22idzsmzvmd54wwhr5e5ddoq"
)


def pcpr_013_receipt_promotion(
    verdict: LogicProviderProtocolVerdict,
) -> dict[str, Any]:
    if verdict.closed_release_outcome is not None:
        raise LogicProviderProtocolCanonicalError(
            "logic-provider-protocol canonicalization must not mint a closed release outcome"
        )
    if verdict.release_claim:
        raise LogicProviderProtocolCanonicalError(
            "logic-provider-protocol canonicalization must not claim a PCPR release"
        )
    if verdict.completion_authoritative:
        raise LogicProviderProtocolCanonicalError(
            "logic-provider-protocol canonicalization completion is not authoritative"
        )
    if verdict.duckdb_or_quack_state_written:
        raise LogicProviderProtocolCanonicalError(
            "logic-provider-protocol canonicalization must not write DuckDB or Quack state"
        )
    if verdict.promotion_status in CLOSED_RELEASE_OUTCOMES:
        raise LogicProviderProtocolCanonicalError(
            "promotion_status must not be a closed release outcome"
        )
    return verdict.to_mapping()


__all__ = [
    "CANONICAL_PROTOCOL_INTERFACE",
    "CANONICAL_PROTOCOL_VERSION",
    "CLOSED_RELEASE_OUTCOMES",
    "CURRENT_HEAD_NON_PROMOTION_VERDICT_CID",
    "EVIDENCE_ID",
    "HERMETIC_CANDIDATE_SUITES",
    "INTERFACE",
    "LogicProviderProtocolCanonicalError",
    "LogicProviderProtocolVerdict",
    "OutcomeProbe",
    "PCPR_013_GOAL_ID",
    "PCPR_013_TASK_ID",
    "SCHEMA",
    "V1_ADAPTER_INTERFACE",
    "content_identity",
    "current_head_runtime_probes",
    "current_head_static_probes",
    "discover_datasets_root",
    "pcpr_013_receipt_promotion",
    "probe_protocol_runtime",
    "qualify_current_head_logic_provider_protocol",
    "qualify_logic_provider_protocol_canonical",
]
