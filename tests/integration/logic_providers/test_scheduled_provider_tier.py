"""Pinned process-backed provider validation tier (LFP2-045).

Interface: ``ScheduledProviderTier@1``

Acceptance (fail-closed):

* Hermetic fixture evidence and scheduled process-backed evidence are
  separate lanes; hermetic success never substitutes for a live binary.
* Metadata-only and mock records never establish executable capability.
* Real pinned binaries run when available; otherwise a typed unavailable
  availability receipt is emitted.
* Every process-backed probe records exact command, environment, tool, and
  output digests/identities with secrets redacted.

Evidence subset: provider subprocess pinned binary environment availability
receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import pytest

from ipfs_datasets_py.logic.backends.evidence_v2 import ExecutionRecordKind
from ipfs_datasets_py.logic.backends.process import (
    REDACTION,
    BoundedToolRunner,
    ToolRunLimits,
    ToolRunRequest,
    ToolRuntime,
)
from ipfs_datasets_py.logic.backends.toolchains import (
    VERIFICATION_TOOLCHAIN_REGISTRY_VERSION,
    default_registry,
    get_toolchain,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    canonical_json_bytes,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SCHEDULED_PROVIDER_TIERS_INTERFACE: Final = "ScheduledProviderTier@1"
SCHEDULED_PROVIDER_TIERS_SCHEMA: Final = "scheduled-provider-tiers/v1"
PINNED_PROCESS_AVAILABILITY_RECEIPT_INTERFACE: Final = (
    "PinnedProcessAvailabilityReceipt@1"
)
PINNED_PROCESS_AVAILABILITY_RECEIPT_SCHEMA: Final = (
    "pinned-process-availability-receipt/v1"
)

SCHEDULED_PROVIDER_TIER_TASK_ID: Final = "LFP2-045"
SCHEDULED_PROVIDER_TIER_GOAL_ID: Final = "LFP2-G080"
SCHEDULED_PROVIDER_TIER_MODULE_VERSION: Final = "1.0.0"

MANIFEST_PATH: Final = Path(__file__).resolve().parent / "manifest.json"

# Authoritative validation PATH (fail-closed). Matches the sealed validation
# environment contract; provider-side ambient PATH is never trusted here.
_VALIDATION_PATH: Final = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"

_SENSITIVE_ENV = re.compile(
    r"(?:^|_)(?:api_?key|access_?key|authorization|credential|passwd|password|"
    r"private_?key|secret|session|token)(?:$|_)",
    re.IGNORECASE,
)

_REQUIRED_IDENTITY_FIELDS: Final = (
    "command_digest",
    "environment_digest",
    "tool_digest",
    "output_digest",
)

_EXECUTABLE_CLAIM_KINDS: Final = frozenset(
    {
        "process_execution",
        "solver_authority",
        "kernel_authority",
        "protocol_authority",
        "monitor_authority",
    }
)


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class EvidenceLane(StrEnum):
    """Evidence lanes kept strictly separate."""

    HERMETIC = "hermetic"
    SCHEDULED_PROCESS = "scheduled_process"


class TierRecordKind(StrEnum):
    """Record kinds admitted by ScheduledProviderTier@1."""

    LIVE_PROCESS = "live_process"
    PINNED_BINARY = "pinned_binary"
    HERMETIC_FIXTURE = "hermetic_fixture"
    METADATA_ONLY = "metadata_only"
    MOCK = "mock"
    UNAVAILABLE = "unavailable"


class AvailabilityDisposition(StrEnum):
    """Typed availability outcomes for process-backed probes."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    PROBED = "probed"
    NOT_PROCESS_BACKED = "not_process_backed"
    REJECTED = "rejected"


# Record kinds that may never establish executable capability.
_NON_EXECUTABLE_RECORD_KINDS: Final = frozenset(
    {
        TierRecordKind.METADATA_ONLY,
        TierRecordKind.MOCK,
        TierRecordKind.HERMETIC_FIXTURE,
        TierRecordKind.UNAVAILABLE,
    }
)

# Process-backed kinds that may claim executable capability only when a real
# subprocess ran and identities are bound.
_PROCESS_EXECUTABLE_RECORD_KINDS: Final = frozenset(
    {
        TierRecordKind.LIVE_PROCESS,
        TierRecordKind.PINNED_BINARY,
    }
)


class ScheduledProviderTierError(ValueError):
    """Raised when the scheduled provider tier contract is violated."""


class ExecutableCapabilityError(ScheduledProviderTierError):
    """Raised when a non-executable record claims executable capability."""


# ---------------------------------------------------------------------------
# Digest / redaction helpers
# ---------------------------------------------------------------------------


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest_of_mapping(payload: Mapping[str, Any]) -> str:
    return content_sha256(canonical_json_bytes(dict(payload)))


def _redact_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Return a sorted, secret-safe environment view for digesting."""

    redacted: dict[str, str] = {}
    for key in sorted(environment):
        value = environment[key]
        if _SENSITIVE_ENV.search(key):
            redacted[key] = REDACTION
        else:
            redacted[key] = value
    return redacted


def _file_digest(path: str) -> str:
    """Digest executable bytes when readable; otherwise digest the path text."""

    try:
        data = Path(path).read_bytes()
    except OSError:
        return _sha256_text(f"path:{path}")
    return _sha256_bytes(data)


def _command_digest(command: Sequence[str]) -> str:
    return hashlib.sha256(b"\0".join(part.encode("utf-8") for part in command)).hexdigest()


def _environment_digest(environment: Mapping[str, str]) -> str:
    return _digest_of_mapping(_redact_environment(environment))


def _output_digest(*, stdout: str, stderr: str, returncode: int | None) -> str:
    return _digest_of_mapping(
        {
            "returncode": returncode,
            "stderr": stderr,
            "stdout": stdout,
        }
    )


def establishes_executable_capability(
    *,
    record_kind: TierRecordKind | str,
    execution_claimed: bool,
    claim_kind: str = "process_execution",
) -> bool:
    """Return whether a record may establish executable capability.

    Metadata-only, mock, hermetic fixture, and unavailable receipts never
    establish executable capability — even when ``execution_claimed`` is set.
    """

    kind = (
        record_kind
        if isinstance(record_kind, TierRecordKind)
        else TierRecordKind(str(record_kind))
    )
    if claim_kind not in _EXECUTABLE_CLAIM_KINDS:
        return False
    if kind in _NON_EXECUTABLE_RECORD_KINDS:
        return False
    if kind not in _PROCESS_EXECUTABLE_RECORD_KINDS:
        return False
    return bool(execution_claimed)


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PinnedProcessAvailabilityReceipt:
    """Provider subprocess pinned-binary environment availability receipt.

    Interface: ``PinnedProcessAvailabilityReceipt@1``.

    Records exact command / environment / tool / output identities without
    secrets.  ``executable_capability`` is true only for live process or
    pinned-binary records that actually ran a subprocess.
    """

    receipt_id: str
    provider_id: str
    lane: EvidenceLane | str
    record_kind: TierRecordKind | str
    disposition: AvailabilityDisposition | str
    command: tuple[str, ...]
    command_digest: str
    environment_digest: str
    tool_digest: str
    output_digest: str
    executable_path: str = ""
    tool_id: str = ""
    toolchain_provider_id: str = ""
    pin_version: str = ""
    pin_sha256: str = ""
    returncode: int | None = None
    available: bool = False
    execution_claimed: bool = False
    executable_capability: bool = False
    reason: str = ""
    secrets_redacted: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    content_digest: str = ""
    schema_version: str = PINNED_PROCESS_AVAILABILITY_RECEIPT_SCHEMA
    interface: str = PINNED_PROCESS_AVAILABILITY_RECEIPT_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.receipt_id, str) or not self.receipt_id.strip():
            raise ScheduledProviderTierError("receipt_id must be a non-empty string")
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ScheduledProviderTierError("provider_id must be a non-empty string")

        lane = (
            self.lane
            if isinstance(self.lane, EvidenceLane)
            else EvidenceLane(str(self.lane))
        )
        object.__setattr__(self, "lane", lane)

        kind = (
            self.record_kind
            if isinstance(self.record_kind, TierRecordKind)
            else TierRecordKind(str(self.record_kind))
        )
        object.__setattr__(self, "record_kind", kind)

        disposition = (
            self.disposition
            if isinstance(self.disposition, AvailabilityDisposition)
            else AvailabilityDisposition(str(self.disposition))
        )
        object.__setattr__(self, "disposition", disposition)

        command = tuple(str(part) for part in self.command)
        object.__setattr__(self, "command", command)

        for field_name in _REQUIRED_IDENTITY_FIELDS:
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ScheduledProviderTierError(
                    f"{field_name} must be a lowercase 64-hex digest"
                )

        if not isinstance(self.available, bool):
            raise ScheduledProviderTierError("available must be a boolean")
        if not isinstance(self.execution_claimed, bool):
            raise ScheduledProviderTierError("execution_claimed must be a boolean")
        if not isinstance(self.executable_capability, bool):
            raise ScheduledProviderTierError(
                "executable_capability must be a boolean"
            )
        if not isinstance(self.secrets_redacted, bool) or not self.secrets_redacted:
            raise ScheduledProviderTierError(
                "secrets_redacted must be true; receipts never retain secrets"
            )

        # Fail-closed: metadata-only / mock / hermetic / unavailable cannot
        # establish executable capability.
        computed = establishes_executable_capability(
            record_kind=kind,
            execution_claimed=self.execution_claimed,
        )
        if self.executable_capability and not computed:
            raise ExecutableCapabilityError(
                f"record_kind {kind.value!r} cannot establish executable "
                "capability; metadata-only and mock never satisfy the "
                "process-backed executable claim"
            )
        if self.execution_claimed and kind in _NON_EXECUTABLE_RECORD_KINDS:
            raise ExecutableCapabilityError(
                f"record_kind {kind.value!r} cannot claim execution"
            )
        if self.executable_capability != computed:
            # Keep the flag honest even if a caller under-claimed.
            object.__setattr__(self, "executable_capability", computed)

        # Identity binding: executable claims require a real command.
        if self.executable_capability:
            if not command:
                raise ExecutableCapabilityError(
                    "executable capability requires a non-empty command"
                )
            if not self.available:
                raise ExecutableCapabilityError(
                    "executable capability requires available=true"
                )
            if lane is not EvidenceLane.SCHEDULED_PROCESS:
                raise ExecutableCapabilityError(
                    "executable capability is restricted to the scheduled "
                    "process lane"
                )

        metadata = MappingProxyType(dict(self.metadata))
        object.__setattr__(self, "metadata", metadata)

        if self.schema_version != PINNED_PROCESS_AVAILABILITY_RECEIPT_SCHEMA:
            raise ScheduledProviderTierError(
                f"unsupported receipt schema_version {self.schema_version!r}"
            )
        if self.interface != PINNED_PROCESS_AVAILABILITY_RECEIPT_INTERFACE:
            raise ScheduledProviderTierError(
                f"unsupported receipt interface {self.interface!r}"
            )

        content = _digest_of_mapping(self._identity_payload())
        if self.content_digest:
            if self.content_digest != content:
                raise ScheduledProviderTierError(
                    "content_digest does not match receipt identity"
                )
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "command": list(self.command),
            "command_digest": self.command_digest,
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, AvailabilityDisposition)
                else str(self.disposition)
            ),
            "environment_digest": self.environment_digest,
            "executable_capability": self.executable_capability,
            "executable_path": self.executable_path,
            "execution_claimed": self.execution_claimed,
            "interface": self.interface,
            "lane": (
                self.lane.value if isinstance(self.lane, EvidenceLane) else str(self.lane)
            ),
            "output_digest": self.output_digest,
            "pin_sha256": self.pin_sha256,
            "pin_version": self.pin_version,
            "provider_id": self.provider_id,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "record_kind": (
                self.record_kind.value
                if isinstance(self.record_kind, TierRecordKind)
                else str(self.record_kind)
            ),
            "returncode": self.returncode,
            "schema_version": self.schema_version,
            "secrets_redacted": self.secrets_redacted,
            "tool_digest": self.tool_digest,
            "tool_id": self.tool_id,
            "toolchain_provider_id": self.toolchain_provider_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["metadata"] = dict(self.metadata)
        return payload


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_scheduled_provider_manifest(
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Load and validate ``ScheduledProviderTier@1`` manifest JSON."""

    manifest_path = Path(path) if path is not None else MANIFEST_PATH
    raw = manifest_path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ScheduledProviderTierError("manifest root must be an object")
    if payload.get("interface") != SCHEDULED_PROVIDER_TIERS_INTERFACE:
        raise ScheduledProviderTierError(
            f"manifest interface must be {SCHEDULED_PROVIDER_TIERS_INTERFACE}"
        )
    if payload.get("schema_version") != SCHEDULED_PROVIDER_TIERS_SCHEMA:
        raise ScheduledProviderTierError(
            f"manifest schema_version must be {SCHEDULED_PROVIDER_TIERS_SCHEMA}"
        )
    if payload.get("task_id") != SCHEDULED_PROVIDER_TIER_TASK_ID:
        raise ScheduledProviderTierError(
            f"manifest task_id must be {SCHEDULED_PROVIDER_TIER_TASK_ID}"
        )
    lanes = payload.get("evidence_lanes")
    if not isinstance(lanes, dict):
        raise ScheduledProviderTierError("evidence_lanes must be an object")
    for required in ("hermetic", "scheduled_process"):
        if required not in lanes:
            raise ScheduledProviderTierError(
                f"evidence_lanes requires {required!r}"
            )
    providers = payload.get("providers")
    if not isinstance(providers, list) or not providers:
        raise ScheduledProviderTierError("providers must be a non-empty list")
    ids: set[str] = set()
    for entry in providers:
        if not isinstance(entry, dict):
            raise ScheduledProviderTierError("provider entry must be an object")
        provider_id = entry.get("provider_id")
        if not isinstance(provider_id, str) or not provider_id:
            raise ScheduledProviderTierError("provider_id is required")
        if provider_id in ids:
            raise ScheduledProviderTierError(
                f"duplicate provider_id {provider_id!r}"
            )
        ids.add(provider_id)
        if "process_backed" not in entry or not isinstance(
            entry["process_backed"], bool
        ):
            raise ScheduledProviderTierError(
                f"provider {provider_id!r} requires boolean process_backed"
            )
        if "scheduled" not in entry or not isinstance(entry["scheduled"], bool):
            raise ScheduledProviderTierError(
                f"provider {provider_id!r} requires boolean scheduled"
            )
        if entry["process_backed"] and entry["scheduled"]:
            candidates = entry.get("executable_candidates")
            if not isinstance(candidates, list) or not candidates:
                raise ScheduledProviderTierError(
                    f"scheduled process-backed provider {provider_id!r} "
                    "requires executable_candidates"
                )
    acceptance = payload.get("acceptance")
    if not isinstance(acceptance, dict):
        raise ScheduledProviderTierError("acceptance must be an object")
    forbidden = acceptance.get("executable_capability_forbidden_for")
    if not isinstance(forbidden, list) or not {
        "metadata_only",
        "mock",
    }.issubset(set(forbidden)):
        raise ScheduledProviderTierError(
            "acceptance must forbid metadata_only and mock for executable "
            "capability"
        )
    required_fields = acceptance.get("required_identity_fields")
    if not isinstance(required_fields, list) or not set(
        _REQUIRED_IDENTITY_FIELDS
    ).issubset(set(required_fields)):
        raise ScheduledProviderTierError(
            "acceptance must require command/environment/tool/output digests"
        )
    return payload


def scheduled_providers(
    manifest: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    data = manifest if manifest is not None else load_scheduled_provider_manifest()
    return tuple(
        entry
        for entry in data["providers"]
        if entry.get("scheduled") is True and entry.get("process_backed") is True
    )


def hermetic_providers(
    manifest: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    data = manifest if manifest is not None else load_scheduled_provider_manifest()
    return tuple(entry for entry in data["providers"])


# ---------------------------------------------------------------------------
# Process-backed probe harness
# ---------------------------------------------------------------------------


def _validation_environment(
    extra: Mapping[str, str] | None = None,
    *,
    secrets: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the sealed validation environment used for probes."""

    env = {
        "PATH": _VALIDATION_PATH,
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    if secrets:
        # Secrets may be injected for redaction tests only.
        env.update({str(k): str(v) for k, v in secrets.items()})
    return env


def _pin_metadata(toolchain_provider_id: str) -> tuple[str, str, str]:
    """Return (tool_id, pin_version, pin_sha256) from the toolchain registry."""

    try:
        descriptor = get_toolchain(toolchain_provider_id)
    except Exception:  # noqa: BLE001 — missing descriptor is not fatal here
        return toolchain_provider_id, "", ""
    if not descriptor.pins:
        return descriptor.provider_id, "", ""
    pin = descriptor.pins[0]
    return pin.tool_id, pin.version, pin.sha256


def _resolve_executable(
    candidates: Sequence[str],
    *,
    search_path: str,
) -> tuple[str, str]:
    """Return (requested_name, absolute_path) or ("", "") when missing."""

    for name in candidates:
        found = shutil.which(name, path=search_path)
        if found:
            return name, str(Path(found).resolve())
    return "", ""


def probe_scheduled_provider(
    entry: Mapping[str, Any],
    *,
    runner: BoundedToolRunner | None = None,
    environment: Mapping[str, str] | None = None,
    secrets: Sequence[str] = (),
    force_unavailable: bool = False,
) -> PinnedProcessAvailabilityReceipt:
    """Probe one scheduled process-backed provider and emit a typed receipt.

    When the binary is present, runs the configured probe argv through the
    shared ``BoundedToolRunner`` lifecycle and binds command/environment/tool/
    output digests with secrets redacted.  When absent, emits a typed
    unavailable receipt that never establishes executable capability.
    """

    provider_id = str(entry["provider_id"])
    toolchain_provider_id = str(
        entry.get("toolchain_provider_id") or provider_id
    )
    candidates = tuple(str(item) for item in entry.get("executable_candidates", ()))
    env = dict(environment or _validation_environment())
    search_path = env.get("PATH", _VALIDATION_PATH)
    tool_id, pin_version, pin_sha256 = _pin_metadata(toolchain_provider_id)

    requested, executable_path = ("", "")
    if not force_unavailable:
        requested, executable_path = _resolve_executable(
            candidates, search_path=search_path
        )

    empty_cmd_digest = _command_digest(())
    empty_env_digest = _environment_digest(env)
    empty_tool_digest = _sha256_text("tool:unavailable")
    empty_output_digest = _output_digest(stdout="", stderr="", returncode=None)

    if not executable_path:
        return PinnedProcessAvailabilityReceipt(
            receipt_id=f"receipt:unavailable:{provider_id}",
            provider_id=provider_id,
            lane=EvidenceLane.SCHEDULED_PROCESS,
            record_kind=TierRecordKind.UNAVAILABLE,
            disposition=AvailabilityDisposition.UNAVAILABLE,
            command=(),
            command_digest=empty_cmd_digest,
            environment_digest=empty_env_digest,
            tool_digest=empty_tool_digest,
            output_digest=empty_output_digest,
            executable_path="",
            tool_id=tool_id,
            toolchain_provider_id=toolchain_provider_id,
            pin_version=pin_version,
            pin_sha256=pin_sha256,
            returncode=None,
            available=False,
            execution_claimed=False,
            executable_capability=False,
            reason=f"pinned executable unavailable for {provider_id}",
            secrets_redacted=True,
            metadata={
                "candidates": list(candidates),
                "search_path": search_path,
            },
        )

    template = entry.get("probe_argv_template") or ["{executable}", "--version"]
    argv = tuple(
        part.replace("{executable}", executable_path) for part in template
    )
    secret_values = tuple(secrets)
    tool_digest = _file_digest(executable_path)
    if pin_sha256:
        # Prefer reviewed pin identity when present; still bind path digest.
        tool_digest = _digest_of_mapping(
            {
                "executable_path": executable_path,
                "path_digest": tool_digest,
                "pin_sha256": pin_sha256,
                "pin_version": pin_version,
                "tool_id": tool_id,
            }
        )
    else:
        tool_digest = _digest_of_mapping(
            {
                "executable_path": executable_path,
                "path_digest": tool_digest,
                "tool_id": tool_id,
            }
        )

    active_runner = runner or BoundedToolRunner(
        base_environment={"PATH": search_path, "LANG": "C", "LC_ALL": "C"},
    )
    result = active_runner.run(
        ToolRunRequest(
            argv=argv,
            runtime=ToolRuntime.NATIVE,
            limits=ToolRunLimits(timeout_seconds=15.0, max_output_bytes=65_536),
            environment=env,
            secrets=secret_values,
        )
    )

    # Prefer the runner's already-redacted command identity.
    recorded_command = tuple(result.command) if result.command else argv
    # Belt-and-suspenders: never retain raw secret values in recorded argv.
    if secret_values:
        recorded_command = tuple(
            REDACTION if part in secret_values else part for part in recorded_command
        )
    out_digest = _output_digest(
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
    )
    # Unavailable from the runner (e.g. race) still yields a typed receipt.
    if result.unavailable:
        return PinnedProcessAvailabilityReceipt(
            receipt_id=f"receipt:unavailable:{provider_id}",
            provider_id=provider_id,
            lane=EvidenceLane.SCHEDULED_PROCESS,
            record_kind=TierRecordKind.UNAVAILABLE,
            disposition=AvailabilityDisposition.UNAVAILABLE,
            command=recorded_command,
            command_digest=_command_digest(recorded_command),
            environment_digest=_environment_digest(env),
            tool_digest=tool_digest,
            output_digest=out_digest,
            executable_path=executable_path,
            tool_id=tool_id,
            toolchain_provider_id=toolchain_provider_id,
            pin_version=pin_version,
            pin_sha256=pin_sha256,
            returncode=result.returncode,
            available=False,
            execution_claimed=False,
            executable_capability=False,
            reason=result.error or f"{provider_id} process reported unavailable",
            secrets_redacted=True,
        )

    return PinnedProcessAvailabilityReceipt(
        receipt_id=f"receipt:process:{provider_id}",
        provider_id=provider_id,
        lane=EvidenceLane.SCHEDULED_PROCESS,
        record_kind=TierRecordKind.PINNED_BINARY,
        disposition=AvailabilityDisposition.PROBED,
        command=recorded_command,
        command_digest=_command_digest(recorded_command),
        environment_digest=_environment_digest(env),
        tool_digest=tool_digest,
        output_digest=out_digest,
        executable_path=executable_path,
        tool_id=tool_id,
        toolchain_provider_id=toolchain_provider_id,
        pin_version=pin_version,
        pin_sha256=pin_sha256,
        returncode=result.returncode,
        available=True,
        execution_claimed=True,
        executable_capability=True,
        reason=f"probed {requested} at {executable_path}",
        secrets_redacted=True,
        metadata={
            "elapsed_seconds": result.elapsed_seconds,
            "requested_executable": requested,
            "timed_out": result.timed_out,
        },
    )


def run_scheduled_provider_tier(
    *,
    manifest: Mapping[str, Any] | None = None,
    runner: BoundedToolRunner | None = None,
) -> tuple[PinnedProcessAvailabilityReceipt, ...]:
    """Probe every scheduled process-backed provider declared in the manifest."""

    data = manifest if manifest is not None else load_scheduled_provider_manifest()
    receipts: list[PinnedProcessAvailabilityReceipt] = []
    for entry in scheduled_providers(data):
        receipts.append(probe_scheduled_provider(entry, runner=runner))
    return tuple(receipts)


def hermetic_fixture_receipt(provider_id: str) -> PinnedProcessAvailabilityReceipt:
    """Construct a hermetic-lane fixture receipt (never executable capability)."""

    empty = _command_digest(())
    env_digest = _environment_digest({"PATH": _VALIDATION_PATH})
    return PinnedProcessAvailabilityReceipt(
        receipt_id=f"receipt:hermetic:{provider_id}",
        provider_id=provider_id,
        lane=EvidenceLane.HERMETIC,
        record_kind=TierRecordKind.HERMETIC_FIXTURE,
        disposition=AvailabilityDisposition.NOT_PROCESS_BACKED,
        command=(),
        command_digest=empty,
        environment_digest=env_digest,
        tool_digest=_sha256_text("tool:hermetic-fixture"),
        output_digest=_output_digest(
            stdout="fixture", stderr="", returncode=0
        ),
        available=False,
        execution_claimed=False,
        executable_capability=False,
        reason="hermetic fixture evidence only",
        secrets_redacted=True,
    )


def metadata_only_receipt(provider_id: str) -> PinnedProcessAvailabilityReceipt:
    empty = _command_digest(())
    env_digest = _environment_digest({})
    return PinnedProcessAvailabilityReceipt(
        receipt_id=f"receipt:metadata:{provider_id}",
        provider_id=provider_id,
        lane=EvidenceLane.SCHEDULED_PROCESS,
        record_kind=TierRecordKind.METADATA_ONLY,
        disposition=AvailabilityDisposition.REJECTED,
        command=(),
        command_digest=empty,
        environment_digest=env_digest,
        tool_digest=_sha256_text("tool:metadata-only"),
        output_digest=_output_digest(stdout="", stderr="", returncode=None),
        available=False,
        execution_claimed=False,
        executable_capability=False,
        reason="metadata-only cannot establish executable capability",
        secrets_redacted=True,
    )


def mock_receipt(provider_id: str) -> PinnedProcessAvailabilityReceipt:
    empty = _command_digest(())
    env_digest = _environment_digest({})
    return PinnedProcessAvailabilityReceipt(
        receipt_id=f"receipt:mock:{provider_id}",
        provider_id=provider_id,
        lane=EvidenceLane.SCHEDULED_PROCESS,
        record_kind=TierRecordKind.MOCK,
        disposition=AvailabilityDisposition.REJECTED,
        command=(),
        command_digest=empty,
        environment_digest=env_digest,
        tool_digest=_sha256_text("tool:mock"),
        output_digest=_output_digest(
            stdout="mock-sat", stderr="", returncode=0
        ),
        available=False,
        execution_claimed=False,
        executable_capability=False,
        reason="mock cannot establish executable capability",
        secrets_redacted=True,
    )


# ---------------------------------------------------------------------------
# Tests: interface / manifest
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    assert SCHEDULED_PROVIDER_TIERS_INTERFACE == "ScheduledProviderTier@1"
    assert (
        PINNED_PROCESS_AVAILABILITY_RECEIPT_INTERFACE
        == "PinnedProcessAvailabilityReceipt@1"
    )
    assert SCHEDULED_PROVIDER_TIER_TASK_ID == "LFP2-045"
    assert SCHEDULED_PROVIDER_TIER_GOAL_ID == "LFP2-G080"
    assert SCHEDULED_PROVIDER_TIER_MODULE_VERSION
    assert (
        VERIFICATION_TOOLCHAIN_REGISTRY_VERSION
        == "VerificationToolchainRegistry@1"
    )


def test_manifest_loads_and_separates_lanes() -> None:
    manifest = load_scheduled_provider_manifest()
    assert manifest["interface"] == SCHEDULED_PROVIDER_TIERS_INTERFACE
    hermetic = manifest["evidence_lanes"]["hermetic"]
    scheduled = manifest["evidence_lanes"]["scheduled_process"]
    assert hermetic["lane_id"] == EvidenceLane.HERMETIC.value
    assert scheduled["lane_id"] == EvidenceLane.SCHEDULED_PROCESS.value
    assert hermetic["may_claim_executable_capability"] is False
    assert scheduled["may_claim_executable_capability"] is True
    assert "hermetic_fixture" in hermetic["record_kinds"]
    assert "pinned_binary" in scheduled["record_kinds"]
    assert "unavailable" in scheduled["record_kinds"]
    assert "metadata_only" not in scheduled["record_kinds"]
    assert "mock" not in scheduled["record_kinds"]


def test_manifest_covers_provider_wave_dependencies() -> None:
    manifest = load_scheduled_provider_manifest()
    task_ids = {entry["task_id"] for entry in manifest["providers"]}
    expected = {
        "LFP2-028",
        "LFP2-029",
        "LFP2-030",
        "LFP2-031",
        "LFP2-032",
        "LFP2-033",
        "LFP2-034",
        "LFP2-035",
        "LFP2-036",
    }
    assert expected <= task_ids
    scheduled = scheduled_providers(manifest)
    assert scheduled, "at least one process-backed scheduled provider required"
    for entry in scheduled:
        assert entry["process_backed"] is True
        assert entry["executable_candidates"]


def test_manifest_toolchain_contracts_align_with_registry() -> None:
    """Every scheduled provider publishes a toolchain contract (precondition)."""

    registry = default_registry()
    known = {item.provider_id for item in registry.descriptors}
    for entry in scheduled_providers():
        toolchain_id = entry["toolchain_provider_id"]
        assert toolchain_id in known, (
            f"{entry['provider_id']} missing toolchain contract {toolchain_id}"
        )
        descriptor = get_toolchain(toolchain_id)
        # Process-backed scheduled providers must declare executable candidates
        # that are a subset of (or equal to) the toolchain inventory.
        if descriptor.executable_candidates:
            declared = set(entry["executable_candidates"])
            inventory = set(descriptor.executable_candidates)
            assert declared & inventory, (
                f"{entry['provider_id']} candidates {sorted(declared)} must "
                f"intersect toolchain inventory {sorted(inventory)}"
            )


# ---------------------------------------------------------------------------
# Tests: fail-closed executable capability
# ---------------------------------------------------------------------------


def test_metadata_only_never_establishes_executable_capability() -> None:
    receipt = metadata_only_receipt("z3")
    assert receipt.executable_capability is False
    assert receipt.execution_claimed is False
    assert receipt.record_kind is TierRecordKind.METADATA_ONLY
    assert establishes_executable_capability(
        record_kind=TierRecordKind.METADATA_ONLY,
        execution_claimed=True,
    ) is False
    with pytest.raises(ExecutableCapabilityError):
        PinnedProcessAvailabilityReceipt(
            receipt_id="receipt:bad:metadata",
            provider_id="z3",
            lane=EvidenceLane.SCHEDULED_PROCESS,
            record_kind=TierRecordKind.METADATA_ONLY,
            disposition=AvailabilityDisposition.REJECTED,
            command=("/usr/bin/z3", "--version"),
            command_digest=_command_digest(("/usr/bin/z3", "--version")),
            environment_digest=_environment_digest({"PATH": _VALIDATION_PATH}),
            tool_digest=_sha256_text("tool:z3"),
            output_digest=_output_digest(stdout="sat", stderr="", returncode=0),
            available=True,
            execution_claimed=True,
            executable_capability=True,
            reason="attacker metadata claim",
            secrets_redacted=True,
        )


def test_mock_never_establishes_executable_capability() -> None:
    receipt = mock_receipt("vampire")
    assert receipt.executable_capability is False
    assert establishes_executable_capability(
        record_kind=TierRecordKind.MOCK,
        execution_claimed=True,
        claim_kind="solver_authority",
    ) is False
    with pytest.raises(ExecutableCapabilityError):
        PinnedProcessAvailabilityReceipt(
            receipt_id="receipt:bad:mock",
            provider_id="vampire",
            lane=EvidenceLane.SCHEDULED_PROCESS,
            record_kind=TierRecordKind.MOCK,
            disposition=AvailabilityDisposition.REJECTED,
            command=("vampire", "--version"),
            command_digest=_command_digest(("vampire", "--version")),
            environment_digest=_environment_digest({"PATH": _VALIDATION_PATH}),
            tool_digest=_sha256_text("tool:vampire"),
            output_digest=_output_digest(
                stdout="Theorem", stderr="", returncode=0
            ),
            available=True,
            execution_claimed=True,
            executable_capability=True,
            reason="attacker mock claim",
            secrets_redacted=True,
        )


def test_hermetic_fixture_never_establishes_executable_capability() -> None:
    receipt = hermetic_fixture_receipt("cvc5")
    assert receipt.lane is EvidenceLane.HERMETIC
    assert receipt.executable_capability is False
    assert establishes_executable_capability(
        record_kind=TierRecordKind.HERMETIC_FIXTURE,
        execution_claimed=True,
    ) is False


def test_unavailable_receipt_never_establishes_executable_capability() -> None:
    entry = {
        "provider_id": "definitely-missing-solver-xyz",
        "toolchain_provider_id": "z3",
        "executable_candidates": ["definitely-missing-solver-xyz"],
        "probe_argv_template": ["{executable}", "--version"],
    }
    receipt = probe_scheduled_provider(entry, force_unavailable=True)
    assert receipt.disposition is AvailabilityDisposition.UNAVAILABLE
    assert receipt.available is False
    assert receipt.executable_capability is False
    assert receipt.execution_claimed is False
    assert receipt.record_kind is TierRecordKind.UNAVAILABLE
    for field_name in _REQUIRED_IDENTITY_FIELDS:
        value = getattr(receipt, field_name)
        assert isinstance(value, str) and len(value) == 64


def test_evidence_v2_record_kinds_align() -> None:
    """Cross-check with ProviderExecutionReceipt@2 executable kinds."""

    assert ExecutionRecordKind.METADATA_ONLY.value == "metadata_only"
    assert ExecutionRecordKind.MOCK.value == "mock"
    assert ExecutionRecordKind.LIVE.value == "live"
    assert ExecutionRecordKind.PINNED_TOOL.value == "pinned_tool"
    assert ExecutionRecordKind.HERMETIC_FIXTURE.value == "hermetic_fixture"
    # Hermetic may be an executable *fixture* kind on ProviderExecutionReceipt@2,
    # but still cannot satisfy *scheduled process-backed* executable capability.
    assert establishes_executable_capability(
        record_kind=TierRecordKind.HERMETIC_FIXTURE,
        execution_claimed=True,
    ) is False
    assert establishes_executable_capability(
        record_kind=TierRecordKind.METADATA_ONLY,
        execution_claimed=True,
    ) is False
    assert establishes_executable_capability(
        record_kind=TierRecordKind.MOCK,
        execution_claimed=True,
    ) is False


# ---------------------------------------------------------------------------
# Tests: process probe + identity recording
# ---------------------------------------------------------------------------


def test_scheduled_tier_probes_all_providers_with_typed_receipts() -> None:
    receipts = run_scheduled_provider_tier()
    assert receipts
    by_provider = {item.provider_id: item for item in receipts}
    for entry in scheduled_providers():
        receipt = by_provider[entry["provider_id"]]
        assert receipt.lane is EvidenceLane.SCHEDULED_PROCESS
        assert receipt.secrets_redacted is True
        for field_name in _REQUIRED_IDENTITY_FIELDS:
            digest = getattr(receipt, field_name)
            assert re.fullmatch(r"[0-9a-f]{64}", digest), field_name
        if receipt.available:
            assert receipt.record_kind is TierRecordKind.PINNED_BINARY
            assert receipt.executable_capability is True
            assert receipt.execution_claimed is True
            assert receipt.command
            assert receipt.executable_path
        else:
            assert receipt.record_kind is TierRecordKind.UNAVAILABLE
            assert receipt.executable_capability is False
            assert receipt.execution_claimed is False


def test_real_process_records_identities_without_secrets(tmp_path: Path) -> None:
    """Exercise a real subprocess (always-present /usr/bin/true) for digests."""

    true_path = shutil.which("true", path=_VALIDATION_PATH)
    if true_path is None:
        # Authoritative validation PATH must include /usr/bin; fail closed.
        pytest.fail("validation PATH lacks `true`; sealed environment broken")

    secret = "super-secret-token-value-42"
    env = _validation_environment(
        secrets={
            "API_KEY": secret,
            "PROVIDER_TOKEN": secret,
            "SAFE_FLAG": "1",
        }
    )
    # Synthetic scheduled entry that uses a real host binary solely to prove
    # identity recording; it does not claim any solver authority.
    entry = {
        "provider_id": "identity-probe-true",
        "toolchain_provider_id": "z3",
        "executable_candidates": ["true"],
        "probe_argv_template": [
            "{executable}",
            "--api-key",
            secret,
            f"--token={secret}",
        ],
    }
    runner = BoundedToolRunner(
        workspace_root=tmp_path / "runs",
        base_environment={"PATH": _VALIDATION_PATH, "LANG": "C", "LC_ALL": "C"},
    )
    receipt = probe_scheduled_provider(
        entry,
        runner=runner,
        environment=env,
        secrets=(secret,),
    )
    assert receipt.available is True
    assert receipt.executable_capability is True
    assert receipt.record_kind is TierRecordKind.PINNED_BINARY
    # Secrets never appear in recorded command or digests payload.
    wire = json.dumps(receipt.to_dict())
    assert secret not in wire
    assert REDACTION in " ".join(receipt.command) or all(
        secret not in part for part in receipt.command
    )
    # Environment digest is stable and secret-safe.
    again = _environment_digest(env)
    assert receipt.environment_digest == again
    # Tool and output identities are bound.
    assert receipt.tool_digest
    assert receipt.output_digest
    assert receipt.command_digest == _command_digest(receipt.command)
    assert receipt.returncode == 0


def test_environment_digest_redacts_sensitive_keys() -> None:
    plain = _validation_environment()
    with_secret = dict(plain)
    with_secret["OPENAI_API_KEY"] = "sk-live-should-never-appear"
    with_secret["session_token"] = "sess-xyz"
    digest_a = _environment_digest(with_secret)
    digest_b = _environment_digest(
        {
            **plain,
            "OPENAI_API_KEY": "different-secret",
            "session_token": "other-sess",
        }
    )
    # After redaction, secret values do not affect the digest.
    assert digest_a == digest_b
    # Non-secret changes do affect the digest.
    plain2 = dict(plain)
    plain2["SAFE_FLAG"] = "changed"
    assert _environment_digest(plain2) != _environment_digest(plain)


def test_hermetic_and_scheduled_evidence_remain_separate() -> None:
    hermetic = hermetic_fixture_receipt("z3")
    entry = {
        "provider_id": "z3",
        "toolchain_provider_id": "z3",
        "executable_candidates": ["z3"],
        "probe_argv_template": ["{executable}", "--version"],
    }
    scheduled = probe_scheduled_provider(entry)
    assert hermetic.lane is EvidenceLane.HERMETIC
    assert scheduled.lane is EvidenceLane.SCHEDULED_PROCESS
    assert hermetic.record_kind is TierRecordKind.HERMETIC_FIXTURE
    assert hermetic.executable_capability is False
    # Even if hermetic "succeeds", it cannot stand in for scheduled capability.
    if not scheduled.available:
        assert scheduled.executable_capability is False
    else:
        assert scheduled.executable_capability is True
    assert hermetic.content_digest != scheduled.content_digest


def test_receipt_wire_shape_and_round_trip_identity() -> None:
    receipt = metadata_only_receipt("proverif")
    wire = receipt.to_dict()
    assert wire["interface"] == PINNED_PROCESS_AVAILABILITY_RECEIPT_INTERFACE
    assert wire["schema_version"] == PINNED_PROCESS_AVAILABILITY_RECEIPT_SCHEMA
    for field_name in _REQUIRED_IDENTITY_FIELDS:
        assert field_name in wire
    restored = PinnedProcessAvailabilityReceipt(
        receipt_id=wire["receipt_id"],
        provider_id=wire["provider_id"],
        lane=wire["lane"],
        record_kind=wire["record_kind"],
        disposition=wire["disposition"],
        command=tuple(wire["command"]),
        command_digest=wire["command_digest"],
        environment_digest=wire["environment_digest"],
        tool_digest=wire["tool_digest"],
        output_digest=wire["output_digest"],
        executable_path=wire["executable_path"],
        tool_id=wire["tool_id"],
        toolchain_provider_id=wire["toolchain_provider_id"],
        pin_version=wire["pin_version"],
        pin_sha256=wire["pin_sha256"],
        returncode=wire["returncode"],
        available=wire["available"],
        execution_claimed=wire["execution_claimed"],
        executable_capability=wire["executable_capability"],
        reason=wire["reason"],
        secrets_redacted=wire["secrets_redacted"],
        metadata=wire["metadata"],
        content_digest=wire["content_digest"],
    )
    assert restored.content_digest == receipt.content_digest


def test_manifest_path_is_declared_output() -> None:
    assert MANIFEST_PATH.is_file()
    assert MANIFEST_PATH.name == "manifest.json"
    # Ensure the test module path matches the declared output layout.
    assert Path(__file__).name == "test_scheduled_provider_tier.py"
