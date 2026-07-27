#!/usr/bin/env python3
"""Capture the exact runnable identities for semantic round-trip compositions.

The probe is intentionally conservative:

* it never installs a package or starts, stops, or reconfigures a service;
* the requested full spaCy pipeline cannot fall back to ``spacy.blank``;
* direct Leanstral and SyMAI are different routes to one exact, one-slot model;
* the frozen autoencoder state is opened with read-only operating-system flags;
* cvc5 and Lean are exercised with small, timed, non-corpus smoke programs; and
* every missing or mismatched capability is retained as ``unavailable``.

Importing this module performs no probes.  Run it as a script to refresh the
run-scoped receipt, or use :func:`capture_capability_inventory` from a runner.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib
from importlib import metadata, util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from types import MappingProxyType
from typing import Any, Final
import urllib.error
import urllib.request


REPO_ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT: Final = (
    REPO_ROOT
    / "workspace/benchmarks/semantic-roundtrip-compositions/capabilities.json"
)
SCHEMA_VERSION: Final = (
    "ipfs-datasets.semantic-roundtrip-capability-inventory.v1"
)
INTERFACE_VERSION: Final = "SemanticRoundTripCapabilityInventory@1"
DEFAULT_RUN_ID: Final = "semantic-roundtrip-compositions-2026-07-26"

SPACY_VERSION: Final = "3.8.14"
SPACY_MODEL: Final = "en_core_web_sm"
SPACY_MODEL_DISTRIBUTION: Final = "en-core-web-sm"
SPACY_MODEL_VERSION: Final = "3.8.0"
SPACY_PIPELINE: Final = (
    "tok2vec",
    "tagger",
    "parser",
    "attribute_ruler",
    "lemmatizer",
    "ner",
)
SPACY_REQUIRED_ANNOTATIONS: Final = (
    "DEP",
    "ENT_IOB",
    "LEMMA",
    "POS",
    "SENT_START",
    "TAG",
)
SPACY_SMOKE_TEXT: Final = (
    "Ada Lovelace reviews the blue report in London."
)

LEANSTRAL_ENDPOINT: Final = "http://127.0.0.1:8080/v1"
LEANSTRAL_MODEL: Final = (
    "Frosty40/Leanstral-1.5-119B-A6B-GGUF-NVFP4:NVFP4"
)
LEANSTRAL_PROVIDER: Final = "leanstral_local"
LEANSTRAL_BACKEND: Final = "llama.cpp"
LEANSTRAL_BACKEND_OWNER: Final = "llamacpp"
LEANSTRAL_CAPACITY: Final = 1

SYMAI_VERSION: Final = "1.14.0"
SYMAI_PROVIDER: Final = "ipfs_accelerate_py"
SYMAI_MODEL_ALIAS: Final = "Leanstral-119B"
SYMAI_CONFIG_MODEL: Final = "ipfs:Leanstral-119B"
SYMAI_ENGINE: Final = (
    "ipfs_datasets_py.utils.symai_ipfs_engine."
    "IPFSSyMAINeurosymbolicEngine"
)
SYMAI_ROUTER_MODULE: Final = "ipfs_datasets_py.llm_router"
SYMAI_ROUTE_CONTRACT_VALIDATOR: Final = (
    "ipfs_accelerate_py.llm_router."
    "validate_pinned_symai_request_contract"
)
SYMAI_CANONICAL_SCHEMA_NAME: Final = (
    "semantic_roundtrip_canonical_ir_v1"
)
SYMAI_REALIZATION_SCHEMA_NAME: Final = (
    "semantic_roundtrip_realization_v1"
)

AUTOENCODER_STATE_RELATIVE_PATH: Final = Path(
    "workspace/todo-queues/"
    "legal-ir-daemon-restart12-20260608T075001Z-"
    "best-8h-autoencoder.state.json"
)
AUTOENCODER_STATE_SHA256: Final = (
    "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"
)
AUTOENCODER_STATE_CID: Final = (
    "bafkreiaui3frqwo56twub62vo33ogihozzgoyjukacgfyb5772xzlhgy3u"
)
AUTOENCODER_STATE_SCHEMA: Final = "modal-autoencoder-state-v1"
AUTOENCODER_DECLARED_ARCHITECTURE: Final = "legacy_dense_v1"
AUTOENCODER_EFFECTIVE_ARCHITECTURE: Final = (
    "proof_aware_auxiliary_heads_v2"
)
MAX_AUTOENCODER_STATE_BYTES: Final = 64 * 1024 * 1024

CAPABILITY_IDS: Final = (
    "python",
    "multiformats",
    "spacy_pipeline",
    "autoencoder_state",
    "leanstral_direct",
    "symai_leanstral_route",
    "hammer_cvc5",
    "lean",
)

_RECORD_KEYS: Final = frozenset(
    {
        "id",
        "status",
        "requested_identity",
        "effective_identity",
        "checks",
        "reason",
        "substitute_used",
        "substitute_identity",
    }
)
_INVENTORY_KEYS: Final = frozenset(
    {
        "schema_version",
        "interface_version",
        "run_id",
        "captured_at_utc",
        "probe_policy",
        "bindings",
        "capabilities",
    }
)


class CapabilityProbeError(RuntimeError):
    """Raised when a capability receipt violates the frozen contract."""


def _json_copy(value: Any) -> Any:
    """Return a detached, JSON-safe value and reject non-finite extensions."""

    def thaw(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): thaw(nested) for key, nested in item.items()}
        if isinstance(item, (list, tuple)):
            return [thaw(nested) for nested in item]
        return item

    return json.loads(
        json.dumps(
            thaw(value),
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
        )
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """One requested identity and the exact identity actually observed."""

    id: str
    status: str
    requested_identity: Mapping[str, Any]
    effective_identity: Mapping[str, Any] | None
    checks: Mapping[str, Any]
    reason: str | None = None
    substitute_used: bool = False
    substitute_identity: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.id not in CAPABILITY_IDS:
            raise CapabilityProbeError(f"unknown capability id: {self.id!r}")
        if self.status not in {"available", "unavailable"}:
            raise CapabilityProbeError(
                f"unsupported capability status: {self.status!r}"
            )
        requested = _json_copy(dict(self.requested_identity))
        effective = (
            None
            if self.effective_identity is None
            else _json_copy(dict(self.effective_identity))
        )
        checks = _json_copy(dict(self.checks))
        substitute = (
            None
            if self.substitute_identity is None
            else _json_copy(dict(self.substitute_identity))
        )
        if not requested:
            raise CapabilityProbeError(
                f"{self.id} must retain a requested identity"
            )
        if self.status == "available":
            if not effective:
                raise CapabilityProbeError(
                    f"{self.id} is available without an effective identity"
                )
            if self.reason is not None:
                raise CapabilityProbeError(
                    f"{self.id} is available but has an unavailable reason"
                )
        elif not isinstance(self.reason, str) or not self.reason.strip():
            raise CapabilityProbeError(
                f"{self.id} is unavailable without an explicit reason"
            )
        if self.substitute_used or substitute is not None:
            raise CapabilityProbeError(
                f"{self.id} cannot use or advertise a substitute"
            )
        object.__setattr__(self, "requested_identity", _freeze(requested))
        object.__setattr__(
            self,
            "effective_identity",
            None if effective is None else _freeze(effective),
        )
        object.__setattr__(self, "checks", _freeze(checks))
        object.__setattr__(self, "substitute_identity", None)

    @classmethod
    def available(
        cls,
        capability_id: str,
        requested: Mapping[str, Any],
        effective: Mapping[str, Any],
        checks: Mapping[str, Any],
    ) -> "CapabilityRecord":
        return cls(
            id=capability_id,
            status="available",
            requested_identity=requested,
            effective_identity=effective,
            checks=checks,
        )

    @classmethod
    def unavailable(
        cls,
        capability_id: str,
        requested: Mapping[str, Any],
        *,
        reason: str,
        effective: Mapping[str, Any] | None = None,
        checks: Mapping[str, Any] | None = None,
    ) -> "CapabilityRecord":
        return cls(
            id=capability_id,
            status="unavailable",
            requested_identity=requested,
            effective_identity=effective,
            checks=checks or {},
            reason=reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "requested_identity": _json_copy(self.requested_identity),
            "effective_identity": (
                None
                if self.effective_identity is None
                else _json_copy(self.effective_identity)
            ),
            "checks": _json_copy(self.checks),
            "reason": self.reason,
            "substitute_used": False,
            "substitute_identity": None,
        }

    @classmethod
    def from_dict(cls, value: object) -> "CapabilityRecord":
        if not isinstance(value, Mapping):
            raise CapabilityProbeError("capability record must be an object")
        keys = set(value)
        if keys != _RECORD_KEYS:
            missing = sorted(_RECORD_KEYS - keys)
            unknown = sorted(keys - _RECORD_KEYS)
            raise CapabilityProbeError(
                f"capability record fields differ; missing={missing}, "
                f"unknown={unknown}"
            )
        requested = value["requested_identity"]
        effective = value["effective_identity"]
        checks = value["checks"]
        substitute = value["substitute_identity"]
        if not isinstance(requested, Mapping):
            raise CapabilityProbeError("requested_identity must be an object")
        if effective is not None and not isinstance(effective, Mapping):
            raise CapabilityProbeError(
                "effective_identity must be an object or null"
            )
        if not isinstance(checks, Mapping):
            raise CapabilityProbeError("checks must be an object")
        if substitute is not None and not isinstance(substitute, Mapping):
            raise CapabilityProbeError(
                "substitute_identity must be an object or null"
            )
        return cls(
            id=value["id"],  # type: ignore[arg-type]
            status=value["status"],  # type: ignore[arg-type]
            requested_identity=requested,
            effective_identity=effective,
            checks=checks,
            reason=value["reason"],  # type: ignore[arg-type]
            substitute_used=value["substitute_used"],  # type: ignore[arg-type]
            substitute_identity=substitute,
        )


@dataclass(frozen=True, slots=True)
class CapabilityInventory:
    """Strict run-scoped inventory consumed by composition runners."""

    run_id: str
    captured_at_utc: str
    capabilities: tuple[CapabilityRecord, ...]
    bindings: Mapping[str, Any]
    schema_version: str = SCHEMA_VERSION
    interface_version: str = INTERFACE_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise CapabilityProbeError("unsupported inventory schema")
        if self.interface_version != INTERFACE_VERSION:
            raise CapabilityProbeError("unsupported inventory interface")
        if not self.run_id or len(self.run_id) > 160:
            raise CapabilityProbeError("run_id must be a bounded string")
        try:
            observed = datetime.fromisoformat(
                self.captured_at_utc.replace("Z", "+00:00")
            )
        except (TypeError, ValueError) as exc:
            raise CapabilityProbeError(
                "captured_at_utc must be an ISO-8601 timestamp"
            ) from exc
        if observed.tzinfo is None:
            raise CapabilityProbeError("captured_at_utc must include UTC")
        ids = tuple(record.id for record in self.capabilities)
        if ids != CAPABILITY_IDS:
            raise CapabilityProbeError(
                "inventory must contain every capability exactly once in "
                f"canonical order; observed={ids!r}"
            )
        bindings = _json_copy(dict(self.bindings))
        required_bindings = {
            "direct_leanstral",
            "symai_leanstral",
            "same_effective_model",
            "same_effective_service",
            "shared_model_capacity",
        }
        if set(bindings) != required_bindings:
            raise CapabilityProbeError("inventory bindings are incomplete")
        if bindings["shared_model_capacity"] != 1:
            raise CapabilityProbeError(
                "Leanstral shared model capacity must remain one"
            )
        object.__setattr__(self, "bindings", _freeze(bindings))

    @property
    def by_id(self) -> Mapping[str, CapabilityRecord]:
        return MappingProxyType(
            {record.id: record for record in self.capabilities}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "interface_version": self.interface_version,
            "run_id": self.run_id,
            "captured_at_utc": self.captured_at_utc,
            "probe_policy": {
                "installs_packages": False,
                "starts_services": False,
                "stops_services": False,
                "reconfigures_services": False,
                "allows_substitutes": False,
                "full_spacy_pipeline_required": True,
                "autoencoder_access": "read_only",
                "solver_smokes": "bounded",
                "model_inference_smoke": False,
            },
            "bindings": _json_copy(self.bindings),
            "capabilities": [
                record.to_dict() for record in self.capabilities
            ],
        }

    @classmethod
    def from_dict(cls, value: object) -> "CapabilityInventory":
        if not isinstance(value, Mapping):
            raise CapabilityProbeError("inventory must be an object")
        keys = set(value)
        if keys != _INVENTORY_KEYS:
            raise CapabilityProbeError(
                "inventory fields differ; "
                f"missing={sorted(_INVENTORY_KEYS - keys)}, "
                f"unknown={sorted(keys - _INVENTORY_KEYS)}"
            )
        policy = value["probe_policy"]
        if not isinstance(policy, Mapping):
            raise CapabilityProbeError("probe_policy must be an object")
        expected_policy = {
            "installs_packages": False,
            "starts_services": False,
            "stops_services": False,
            "reconfigures_services": False,
            "allows_substitutes": False,
            "full_spacy_pipeline_required": True,
            "autoencoder_access": "read_only",
            "solver_smokes": "bounded",
            "model_inference_smoke": False,
        }
        if dict(policy) != expected_policy:
            raise CapabilityProbeError("probe_policy differs from frozen policy")
        raw_capabilities = value["capabilities"]
        if not isinstance(raw_capabilities, list):
            raise CapabilityProbeError("capabilities must be an array")
        bindings = value["bindings"]
        if not isinstance(bindings, Mapping):
            raise CapabilityProbeError("bindings must be an object")
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            interface_version=value["interface_version"],  # type: ignore[arg-type]
            run_id=value["run_id"],  # type: ignore[arg-type]
            captured_at_utc=value["captured_at_utc"],  # type: ignore[arg-type]
            capabilities=tuple(
                CapabilityRecord.from_dict(item)
                for item in raw_capabilities
            ),
            bindings=bindings,
        )


@dataclass(frozen=True, slots=True)
class ProbeConfig:
    """Frozen requested identities; override callables, not these identities."""

    repository_root: Path = REPO_ROOT
    autoencoder_state_path: Path = (
        REPO_ROOT / AUTOENCODER_STATE_RELATIVE_PATH
    )
    leanstral_endpoint: str = LEANSTRAL_ENDPOINT
    leanstral_model: str = LEANSTRAL_MODEL
    command_timeout_seconds: float = 5.0
    http_timeout_seconds: float = 3.0
    max_command_output_bytes: int = 16 * 1024
    max_http_response_bytes: int = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Bounded child-process observation."""

    arguments: tuple[str, ...]
    return_code: int | None
    output: bytes
    timed_out: bool
    output_truncated: bool

    def to_check(self) -> dict[str, Any]:
        retained = self.output.decode("utf-8", "replace")
        return {
            "arguments": list(self.arguments),
            "return_code": self.return_code,
            "timed_out": self.timed_out,
            "output_truncated": self.output_truncated,
            "output": " ".join(retained.split()),
            "retained_output_sha256": hashlib.sha256(
                self.output
            ).hexdigest(),
        }


VersionGetter = Callable[[str], str | None]
CommandRunner = Callable[[Sequence[str], bytes | None, float, int], CommandResult]
HttpGetter = Callable[[str, float, int], Any]
StateLoader = Callable[[Mapping[str, Any]], Any]
ModuleFinder = Callable[[str], Any]
RouteContractValidator = Callable[..., Mapping[str, object]]


def _distribution_version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _numeric_version(version: str | None) -> tuple[int, ...] | None:
    if not isinstance(version, str):
        return None
    match = re.match(r"\s*(\d+(?:\.\d+)*)", version)
    if match is None:
        return None
    return tuple(int(item) for item in match.group(1).split("."))


def _module_spec(name: str) -> Any:
    try:
        return util.find_spec(name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None


def _bounded_command(
    arguments: Sequence[str],
    input_bytes: bytes | None,
    timeout_seconds: float,
    max_output_bytes: int,
) -> CommandResult:
    process = subprocess.Popen(
        list(arguments),
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=(os.name != "nt"),
    )
    timed_out = False
    try:
        output, _ = process.communicate(
            input=input_bytes,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        try:
            output, _ = process.communicate(timeout=0.25)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            output, _ = process.communicate()
    truncated = len(output) > max_output_bytes
    return CommandResult(
        arguments=tuple(str(item) for item in arguments),
        return_code=process.returncode,
        output=output[:max_output_bytes],
        timed_out=timed_out,
        output_truncated=truncated,
    )


def _http_json(url: str, timeout_seconds: float, max_bytes: int) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise CapabilityProbeError(f"oversized HTTP response from {url}")
    return json.loads(raw.decode("utf-8"))


def _source_identity(spec: Any) -> dict[str, Any]:
    origin = getattr(spec, "origin", None)
    if not isinstance(origin, str):
        return {"module_present": spec is not None, "source": None}
    path = Path(origin)
    result: dict[str, Any] = {
        "module_present": True,
        "source": str(path),
    }
    try:
        raw = path.read_bytes()
    except OSError:
        return result
    result.update(
        {
            "source_bytes": len(raw),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
        }
    )
    return result


def _requested_python() -> dict[str, Any]:
    return {
        "implementation": "CPython",
        "version": "3.12.x",
        "major_minor": "3.12",
    }


def probe_python() -> CapabilityRecord:
    requested = _requested_python()
    effective = {
        "implementation": platform.python_implementation(),
        "version": platform.python_version(),
        "major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        "executable": str(Path(sys.executable).resolve()),
        "executable_sha256": _file_sha256(Path(sys.executable)),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }
    if (
        effective["implementation"] != requested["implementation"]
        or effective["major_minor"] != requested["major_minor"]
    ):
        return CapabilityRecord.unavailable(
            "python",
            requested,
            effective=effective,
            checks={"identity_match": False},
            reason="effective Python does not match the requested CPython 3.12 runtime",
        )
    return CapabilityRecord.available(
        "python",
        requested,
        effective,
        {"identity_match": True},
    )


def probe_multiformats(
    *,
    version_getter: VersionGetter | None = None,
) -> CapabilityRecord:
    requested = {
        "distribution": "multiformats",
        "version_requirement": ">=0.3.0",
        "cid_version": 1,
        "multibase": "base32",
        "multihash": "sha2-256",
    }
    get_version = version_getter or _distribution_version
    version = get_version("multiformats")
    effective: dict[str, Any] = {
        "distribution": "multiformats",
        "version": version,
    }
    if version is None:
        return CapabilityRecord.unavailable(
            "multiformats",
            requested,
            effective=effective,
            checks={"cid_round_trip": False},
            reason="multiformats distribution is not installed",
        )
    if (_numeric_version(version) or ()) < (0, 3, 0):
        return CapabilityRecord.unavailable(
            "multiformats",
            requested,
            effective=effective,
            checks={"cid_round_trip": False, "version_requirement_met": False},
            reason="multiformats version does not meet the frozen requirement",
        )
    try:
        module = importlib.import_module("multiformats")
        decoded = module.CID.decode(AUTOENCODER_STATE_CID)
        encoded = str(decoded)
    except Exception as exc:
        return CapabilityRecord.unavailable(
            "multiformats",
            requested,
            effective=effective,
            checks={"cid_round_trip": False},
            reason=f"multiformats CID smoke failed: {type(exc).__name__}",
        )
    effective["module"] = "multiformats"
    return CapabilityRecord.available(
        "multiformats",
        requested,
        effective,
        {
            "cid_round_trip": encoded == AUTOENCODER_STATE_CID,
            "smoke_cid": AUTOENCODER_STATE_CID,
            "version_requirement_met": True,
        },
    ) if encoded == AUTOENCODER_STATE_CID else CapabilityRecord.unavailable(
        "multiformats",
        requested,
        effective=effective,
        checks={"cid_round_trip": False, "smoke_cid": AUTOENCODER_STATE_CID},
        reason="multiformats did not preserve the frozen CID identity",
    )


def probe_spacy(
    *,
    version_getter: VersionGetter | None = None,
    importer: Callable[[str], Any] | None = None,
) -> CapabilityRecord:
    requested = {
        "distribution": "spacy",
        "version": SPACY_VERSION,
        "model": SPACY_MODEL,
        "model_distribution": SPACY_MODEL_DISTRIBUTION,
        "model_version": SPACY_MODEL_VERSION,
        "pipeline": list(SPACY_PIPELINE),
        "required_annotations": list(SPACY_REQUIRED_ANNOTATIONS),
        "fallback_allowed": False,
    }
    get_version = version_getter or _distribution_version
    import_module = importer or importlib.import_module
    package_version = get_version("spacy")
    model_version = get_version(SPACY_MODEL_DISTRIBUTION)
    effective: dict[str, Any] = {
        "distribution": "spacy",
        "version": package_version,
        "model": None,
        "model_version": model_version,
        "pipeline": [],
    }
    if package_version is None or model_version is None:
        return CapabilityRecord.unavailable(
            "spacy_pipeline",
            requested,
            effective=effective,
            checks={"loaded_full_pipeline": False, "fallback_used": False},
            reason="requested spaCy package or full model distribution is absent",
        )
    if package_version != SPACY_VERSION or model_version != SPACY_MODEL_VERSION:
        return CapabilityRecord.unavailable(
            "spacy_pipeline",
            requested,
            effective=effective,
            checks={"loaded_full_pipeline": False, "fallback_used": False},
            reason="spaCy package or model version differs from the frozen request",
        )
    try:
        spacy = import_module("spacy")
        nlp = spacy.load(SPACY_MODEL)
        pipeline = tuple(nlp.pipe_names)
        doc = nlp(SPACY_SMOKE_TEXT)
        missing_annotations = [
            name
            for name in SPACY_REQUIRED_ANNOTATIONS
            if not doc.has_annotation(name)
        ]
        language = str(getattr(nlp, "lang", ""))
    except Exception as exc:
        return CapabilityRecord.unavailable(
            "spacy_pipeline",
            requested,
            effective=effective,
            checks={"loaded_full_pipeline": False, "fallback_used": False},
            reason=f"full spaCy pipeline load/smoke failed: {type(exc).__name__}",
        )
    effective.update(
        {
            "model": SPACY_MODEL,
            "pipeline": list(pipeline),
            "language": language,
        }
    )
    checks = {
        "loaded_full_pipeline": pipeline == SPACY_PIPELINE,
        "annotations_present": not missing_annotations,
        "missing_annotations": missing_annotations,
        "fallback_used": False,
        "smoke_text_sha256": hashlib.sha256(
            SPACY_SMOKE_TEXT.encode("utf-8")
        ).hexdigest(),
    }
    if pipeline != SPACY_PIPELINE or missing_annotations or language != "en":
        return CapabilityRecord.unavailable(
            "spacy_pipeline",
            requested,
            effective=effective,
            checks=checks,
            reason="effective spaCy model is not the required full English pipeline",
        )
    return CapabilityRecord.available(
        "spacy_pipeline",
        requested,
        effective,
        checks,
    )


def _default_state_loader(value: Mapping[str, Any]) -> Any:
    module = importlib.import_module(
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
        "modal_autoencoder"
    )
    return module.ModalAutoencoderTrainingState.from_dict(value)


def _read_frozen_state(path: Path) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode):
            raise CapabilityProbeError("autoencoder state is not a regular file")
        if observed.st_size > MAX_AUTOENCODER_STATE_BYTES:
            raise CapabilityProbeError("autoencoder state exceeds the frozen size bound")
        chunks: list[bytes] = []
        remaining = MAX_AUTOENCODER_STATE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) != observed.st_size:
            raise CapabilityProbeError("autoencoder state changed while being read")
        return raw, observed
    finally:
        os.close(descriptor)


def probe_autoencoder_state(
    config: ProbeConfig,
    *,
    state_loader: StateLoader | None = None,
) -> CapabilityRecord:
    requested = {
        "path": AUTOENCODER_STATE_RELATIVE_PATH.as_posix(),
        "sha256": AUTOENCODER_STATE_SHA256,
        "cid": AUTOENCODER_STATE_CID,
        "state_schema_version": AUTOENCODER_STATE_SCHEMA,
        "declared_architecture_version": AUTOENCODER_DECLARED_ARCHITECTURE,
        "effective_architecture_version": AUTOENCODER_EFFECTIVE_ARCHITECTURE,
        "access": "read_only",
    }
    path = config.autoencoder_state_path.resolve()
    effective: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
    }
    if path != (config.repository_root / AUTOENCODER_STATE_RELATIVE_PATH).resolve():
        return CapabilityRecord.unavailable(
            "autoencoder_state",
            requested,
            effective=effective,
            checks={"opened_read_only": False, "substitute_used": False},
            reason="autoencoder state path differs from the frozen requested path",
        )
    try:
        before = path.stat()
        raw, descriptor_stat = _read_frozen_state(path)
        digest = hashlib.sha256(raw).hexdigest()
        from benchmarks.logic_pipeline.content_addressing import cid_for_bytes

        cid = cid_for_bytes(raw)
        effective.update(
            {
                "exists": True,
                "bytes": len(raw),
                "sha256": digest,
                "cid": cid,
            }
        )
        if digest != AUTOENCODER_STATE_SHA256 or cid != AUTOENCODER_STATE_CID:
            return CapabilityRecord.unavailable(
                "autoencoder_state",
                requested,
                effective=effective,
                checks={
                    "opened_read_only": True,
                    "identity_match": False,
                    "substitute_used": False,
                },
                reason="autoencoder state content differs from the frozen identity",
            )
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise CapabilityProbeError("autoencoder state must be a JSON object")
        loader = state_loader or _default_state_loader
        loaded = loader(payload)
        architecture = str(getattr(loaded, "architecture_version", ""))
        after = path.stat()
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        ImportError,
        AttributeError,
        CapabilityProbeError,
    ) as exc:
        return CapabilityRecord.unavailable(
            "autoencoder_state",
            requested,
            effective=effective,
            checks={"opened_read_only": False, "substitute_used": False},
            reason=f"frozen autoencoder state load failed: {type(exc).__name__}",
        )
    unchanged = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    effective.update(
        {
            "state_schema_version": AUTOENCODER_STATE_SCHEMA,
            "declared_architecture_version": str(
                payload.get("architecture_version")
                or AUTOENCODER_DECLARED_ARCHITECTURE
            ),
            "effective_architecture_version": architecture,
            "loader_class": (
                f"{type(loaded).__module__}.{type(loaded).__qualname__}"
            ),
        }
    )
    checks = {
        "opened_read_only": True,
        "open_flags": ["O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW"],
        "descriptor_size_matches": descriptor_stat.st_size == len(raw),
        "identity_match": True,
        "state_unchanged_after_load": unchanged,
        "write_attempted": False,
        "substitute_used": False,
    }
    if architecture != AUTOENCODER_EFFECTIVE_ARCHITECTURE or not unchanged:
        return CapabilityRecord.unavailable(
            "autoencoder_state",
            requested,
            effective=effective,
            checks=checks,
            reason="loaded autoencoder architecture drifted or state changed during load",
        )
    return CapabilityRecord.available(
        "autoencoder_state",
        requested,
        effective,
        checks,
    )


def _leanstral_requested() -> dict[str, Any]:
    return {
        "route": "direct_openai_compatible_http",
        "provider": LEANSTRAL_PROVIDER,
        "endpoint": LEANSTRAL_ENDPOINT,
        "model": LEANSTRAL_MODEL,
        "backend": LEANSTRAL_BACKEND,
        "backend_owner": LEANSTRAL_BACKEND_OWNER,
        "capacity": {
            "model_instances": LEANSTRAL_CAPACITY,
            "parallel_slots": LEANSTRAL_CAPACITY,
        },
    }


def probe_leanstral_direct(
    config: ProbeConfig,
    *,
    http_getter: HttpGetter | None = None,
) -> CapabilityRecord:
    requested = _leanstral_requested()
    get_json = http_getter or _http_json
    effective: dict[str, Any] = {
        "route": "direct_openai_compatible_http",
        "provider": LEANSTRAL_PROVIDER,
        "endpoint": config.leanstral_endpoint,
        "model": None,
    }
    if (
        config.leanstral_endpoint != LEANSTRAL_ENDPOINT
        or config.leanstral_model != LEANSTRAL_MODEL
    ):
        return CapabilityRecord.unavailable(
            "leanstral_direct",
            requested,
            effective=effective,
            checks={"requested_identity_match": False},
            reason="configured Leanstral endpoint/model differs from the frozen request",
        )
    origin = LEANSTRAL_ENDPOINT.removesuffix("/v1")
    try:
        health = get_json(
            origin + "/health",
            config.http_timeout_seconds,
            config.max_http_response_bytes,
        )
        models = get_json(
            LEANSTRAL_ENDPOINT + "/models",
            config.http_timeout_seconds,
            config.max_http_response_bytes,
        )
        props = get_json(
            origin + "/props",
            config.http_timeout_seconds,
            config.max_http_response_bytes,
        )
        if not all(isinstance(item, Mapping) for item in (health, models, props)):
            raise CapabilityProbeError("service probe returned a non-object")
        data = models.get("data")
        if not isinstance(data, list):
            raise CapabilityProbeError("models response has no data array")
        selected = [
            item
            for item in data
            if isinstance(item, Mapping)
            and item.get("id") == LEANSTRAL_MODEL
        ]
        if len(selected) != 1:
            raise CapabilityProbeError("exact Leanstral model is absent or ambiguous")
        model_entry = selected[0]
        generation = props.get("default_generation_settings")
        if not isinstance(generation, Mapping):
            generation = {}
        effective.update(
            {
                "health": str(health.get("status") or "").lower(),
                "model": str(model_entry.get("id")),
                "served_models": [
                    str(item.get("id"))
                    for item in data
                    if isinstance(item, Mapping)
                ],
                "backend": LEANSTRAL_BACKEND,
                "backend_owner": model_entry.get("owned_by"),
                "backend_build": props.get("build_info"),
                "model_alias": props.get("model_alias"),
                "model_path": props.get("model_path"),
                "model_format": props.get("model_ftype"),
                "model_metadata": model_entry.get("meta"),
                "context_size": generation.get("n_ctx"),
                "capacity": {
                    "model_instances": 1,
                    "parallel_slots": props.get("total_slots"),
                },
            }
        )
    except (
        OSError,
        TimeoutError,
        urllib.error.URLError,
        json.JSONDecodeError,
        CapabilityProbeError,
    ) as exc:
        return CapabilityRecord.unavailable(
            "leanstral_direct",
            requested,
            effective=effective,
            checks={
                "health_get": False,
                "models_get": False,
                "props_get": False,
                "model_inference_performed": False,
            },
            reason=f"Leanstral identity probe failed: {type(exc).__name__}",
        )
    checks = {
        "health_get": effective["health"] in {"ok", "healthy"},
        "models_get": effective["model"] == LEANSTRAL_MODEL,
        "props_get": True,
        "backend_match": effective["backend_owner"] == LEANSTRAL_BACKEND_OWNER,
        "one_slot_capacity": (
            effective["capacity"]["parallel_slots"] == LEANSTRAL_CAPACITY
        ),
        "model_inference_performed": False,
    }
    required_checks = (
        checks["health_get"],
        checks["models_get"],
        checks["props_get"],
        checks["backend_match"],
        checks["one_slot_capacity"],
    )
    if not all(required_checks):
        return CapabilityRecord.unavailable(
            "leanstral_direct",
            requested,
            effective=effective,
            checks=checks,
            reason="Leanstral health, model, backend, or one-slot capacity drifted",
        )
    return CapabilityRecord.available(
        "leanstral_direct",
        requested,
        effective,
        checks,
    )


def _load_symai_route_contract_validator() -> RouteContractValidator:
    """Load the canonical router's no-I/O contract boundary."""

    router = importlib.import_module("ipfs_accelerate_py.llm_router")
    validator = getattr(
        router,
        "validate_pinned_symai_request_contract",
        None,
    )
    if not callable(validator):
        raise RuntimeError(
            "canonical router has no pinned SyMAI contract validator"
        )
    return validator


def _symai_route_generation_contracts(
) -> dict[str, dict[str, object]]:
    """Build the exact model-facing contracts used by both SyMAI roles."""

    from benchmarks.semantic_roundtrip.contracts import (
        AllowedAtomVocabulary,
    )
    from benchmarks.semantic_roundtrip.constructors.leanstral import (
        CONSTRUCTOR_MAX_TOKENS,
        _server_schema,
        canonical_ir_schema,
    )
    from benchmarks.semantic_roundtrip.constructors.symai import (
        SyMAIGenerationSettings,
    )
    from benchmarks.semantic_roundtrip.realizers.leanstral import (
        REALIZATION_JSON_SCHEMA,
        REALIZER_MAX_TOKENS,
    )

    # The canonical schema has case-specific enums.  This bounded witness is
    # built by the same production schema function and exercises every schema
    # field while the router validator independently enforces the family bounds.
    vocabulary = AllowedAtomVocabulary(
        actors=("capability_actor_b", "capability_actor_a"),
        actions=("capability_action_b", "capability_action_a"),
        objects=("capability_object_b", "capability_object_a"),
        qualifiers=("capability_qualifier_b", "capability_qualifier_a"),
    )

    def options(
        *,
        schema_name: str,
        schema: Mapping[str, object],
        max_tokens: int,
    ) -> dict[str, object]:
        settings = SyMAIGenerationSettings.for_role(max_tokens)
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": _server_schema(schema),
                },
            },
            "temperature": settings.temperature,
            "seed": settings.seed,
            "max_tokens": settings.max_tokens,
            "stop": list(settings.stop),
            "timeout": settings.timeout_seconds,
            "cache_prompt": settings.cache_prompt,
        }

    return {
        "canonical": options(
            schema_name=SYMAI_CANONICAL_SCHEMA_NAME,
            schema=canonical_ir_schema(vocabulary),
            max_tokens=CONSTRUCTOR_MAX_TOKENS,
        ),
        "realization": options(
            schema_name=SYMAI_REALIZATION_SCHEMA_NAME,
            schema=REALIZATION_JSON_SCHEMA,
            max_tokens=REALIZER_MAX_TOKENS,
        ),
    }


def _normalized_symai_generation_options(
    options: Mapping[str, object],
) -> dict[str, object]:
    normalized = _json_copy(dict(options))
    normalized["temperature"] = float(normalized["temperature"])
    normalized["timeout"] = float(normalized["timeout"])
    normalized["stop"] = list(normalized["stop"])
    return normalized


def _route_contract_mismatch_rejected(
    validator: RouteContractValidator,
    *,
    model_name: object,
    route_binding: object,
    generation_options: object,
) -> bool:
    try:
        validator(
            model_name=model_name,
            route_binding=_json_copy(route_binding),
            generation_options=_json_copy(generation_options),
        )
    except Exception:
        return True
    return False


def probe_symai_leanstral_route(
    direct: CapabilityRecord,
    *,
    version_getter: VersionGetter | None = None,
    module_finder: ModuleFinder | None = None,
    route_contract_validator: RouteContractValidator | None = None,
) -> CapabilityRecord:
    requested = {
        "route": "symai_router",
        "distribution": "symbolicai",
        "version": SYMAI_VERSION,
        "provider": SYMAI_PROVIDER,
        "model_alias": SYMAI_MODEL_ALIAS,
        "symai_config_model": SYMAI_CONFIG_MODEL,
        "engine": SYMAI_ENGINE,
        "router_module": SYMAI_ROUTER_MODULE,
        "route_contract_validator": SYMAI_ROUTE_CONTRACT_VALIDATOR,
        "request_contracts": {
            "canonical": {
                "schema_name": SYMAI_CANONICAL_SCHEMA_NAME,
                "max_tokens": 3072,
            },
            "realization": {
                "schema_name": SYMAI_REALIZATION_SCHEMA_NAME,
                "max_tokens": 1536,
            },
            "temperature": 0,
            "seed": 0,
            "stop": ["<|im_end|>"],
            "timeout_seconds": 120.0,
            "cache_prompt": False,
        },
        "resolved_provider": LEANSTRAL_PROVIDER,
        "resolved_endpoint": LEANSTRAL_ENDPOINT,
        "resolved_model": LEANSTRAL_MODEL,
        "resolved_backend": LEANSTRAL_BACKEND,
        "independent_model": False,
        "shared_capacity": LEANSTRAL_CAPACITY,
    }
    get_version = version_getter or _distribution_version
    find_module = module_finder or _module_spec
    version = get_version("symbolicai")
    engine_spec = find_module(
        "ipfs_datasets_py.utils.symai_ipfs_engine"
    )
    router_spec = find_module(SYMAI_ROUTER_MODULE)
    effective: dict[str, Any] = {
        "route": "symai_router",
        "distribution": "symbolicai",
        "version": version,
        "provider": SYMAI_PROVIDER,
        "model_alias": SYMAI_MODEL_ALIAS,
        "symai_config_model": SYMAI_CONFIG_MODEL,
        "engine": SYMAI_ENGINE,
        "router_module": SYMAI_ROUTER_MODULE,
        "engine_source_identity": _source_identity(engine_spec),
        "router_source_identity": _source_identity(router_spec),
        "route_contract_validator": SYMAI_ROUTE_CONTRACT_VALIDATOR,
        "validated_request_contracts": None,
        "resolved_provider": None,
        "resolved_endpoint": None,
        "resolved_model": None,
        "resolved_backend": None,
        "independent_model": False,
        "shared_capacity": LEANSTRAL_CAPACITY,
    }
    if version != SYMAI_VERSION or engine_spec is None or router_spec is None:
        return CapabilityRecord.unavailable(
            "symai_leanstral_route",
            requested,
            effective=effective,
            checks={
                "symbolicai_version_match": version == SYMAI_VERSION,
                "engine_present": engine_spec is not None,
                "router_present": router_spec is not None,
                "route_contract_validator_present": False,
                "route_contract_validation_passed": False,
                "same_effective_model": False,
                "model_inference_performed": False,
            },
            reason="SyMAI package or frozen IPFS router implementation is unavailable",
        )
    if direct.status != "available" or direct.effective_identity is None:
        return CapabilityRecord.unavailable(
            "symai_leanstral_route",
            requested,
            effective=effective,
            checks={
                "symbolicai_version_match": True,
                "engine_present": True,
                "router_present": True,
                "route_contract_validator_present": False,
                "route_contract_validation_passed": False,
                "same_effective_model": False,
                "model_inference_performed": False,
            },
            reason="SyMAI route cannot bind its required direct Leanstral service",
        )
    effective.update(
        {
            "resolved_provider": LEANSTRAL_PROVIDER,
            "resolved_endpoint": direct.effective_identity["endpoint"],
            "resolved_model": direct.effective_identity["model"],
            "resolved_backend": direct.effective_identity["backend"],
        }
    )
    same_model = (
        effective["resolved_endpoint"] == LEANSTRAL_ENDPOINT
        and effective["resolved_model"] == LEANSTRAL_MODEL
        and effective["resolved_backend"] == LEANSTRAL_BACKEND
    )
    checks = {
        "symbolicai_version_match": True,
        "engine_present": True,
        "router_present": True,
        "route_contract_validator_present": False,
        "canonical_request_contract_accepted": False,
        "canonical_schema_exact_match": False,
        "canonical_settings_exact_match": False,
        "realization_request_contract_accepted": False,
        "realization_schema_exact_match": False,
        "realization_settings_exact_match": False,
        "model_alias_mismatch_rejected": False,
        "route_binding_mismatch_rejected": False,
        "canonical_schema_mismatch_rejected": False,
        "canonical_settings_mismatch_rejected": False,
        "realization_schema_mismatch_rejected": False,
        "realization_settings_mismatch_rejected": False,
        "route_contract_validation_passed": False,
        "same_effective_model": same_model,
        "same_effective_service": same_model,
        "independent_model_started": False,
        "live_model_request_performed": False,
        "model_inference_performed": False,
    }
    if not same_model:
        return CapabilityRecord.unavailable(
            "symai_leanstral_route",
            requested,
            effective=effective,
            checks=checks,
            reason="SyMAI did not resolve to the exact direct Leanstral identity",
        )

    try:
        validator = (
            route_contract_validator
            if route_contract_validator is not None
            else _load_symai_route_contract_validator()
        )
    except Exception:
        return CapabilityRecord.unavailable(
            "symai_leanstral_route",
            requested,
            effective=effective,
            checks=checks,
            reason=(
                "SyMAI side-effect-free route-contract validator is "
                "unavailable"
            ),
        )
    checks["route_contract_validator_present"] = callable(validator)
    if not callable(validator):
        return CapabilityRecord.unavailable(
            "symai_leanstral_route",
            requested,
            effective=effective,
            checks=checks,
            reason=(
                "SyMAI side-effect-free route-contract validator is "
                "unavailable"
            ),
        )

    try:
        contracts = _symai_route_generation_contracts()
    except Exception:
        return CapabilityRecord.unavailable(
            "symai_leanstral_route",
            requested,
            effective=effective,
            checks=checks,
            reason="SyMAI benchmark request contracts could not be constructed",
        )

    route_binding = {
        "resolved_provider_name": LEANSTRAL_PROVIDER,
        "resolved_model_name": LEANSTRAL_MODEL,
        "service_endpoint": LEANSTRAL_ENDPOINT,
        "routing_backend": LEANSTRAL_BACKEND,
    }
    normalized: dict[str, Mapping[str, object] | None] = {}
    for role in ("canonical", "realization"):
        options = contracts[role]
        try:
            result = validator(
                model_name=SYMAI_MODEL_ALIAS,
                route_binding=_json_copy(route_binding),
                generation_options=_json_copy(options),
            )
        except Exception:
            normalized[role] = None
        else:
            normalized[role] = (
                _json_copy(dict(result))
                if isinstance(result, Mapping)
                else None
            )

        expected = _normalized_symai_generation_options(options)
        observed = normalized[role]
        schema_matches = bool(
            observed is not None
            and observed.get("response_format")
            == expected["response_format"]
        )
        settings_matches = bool(
            observed is not None
            and set(observed) == set(expected)
            and all(
                observed.get(key) == value
                for key, value in expected.items()
                if key != "response_format"
            )
        )
        checks[f"{role}_schema_exact_match"] = schema_matches
        checks[f"{role}_settings_exact_match"] = settings_matches
        checks[f"{role}_request_contract_accepted"] = bool(
            schema_matches and settings_matches
        )

    checks["model_alias_mismatch_rejected"] = (
        _route_contract_mismatch_rejected(
            validator,
            model_name=SYMAI_MODEL_ALIAS + "-drifted",
            route_binding=route_binding,
            generation_options=contracts["canonical"],
        )
    )
    drifted_binding = _json_copy(route_binding)
    drifted_binding["routing_backend"] = "drifted"
    checks["route_binding_mismatch_rejected"] = (
        _route_contract_mismatch_rejected(
            validator,
            model_name=SYMAI_MODEL_ALIAS,
            route_binding=drifted_binding,
            generation_options=contracts["canonical"],
        )
    )
    for role in ("canonical", "realization"):
        drifted_schema = _json_copy(contracts[role])
        drifted_schema["response_format"]["json_schema"]["strict"] = False
        checks[f"{role}_schema_mismatch_rejected"] = (
            _route_contract_mismatch_rejected(
                validator,
                model_name=SYMAI_MODEL_ALIAS,
                route_binding=route_binding,
                generation_options=drifted_schema,
            )
        )
        drifted_settings = _json_copy(contracts[role])
        drifted_settings["max_tokens"] += 1
        checks[f"{role}_settings_mismatch_rejected"] = (
            _route_contract_mismatch_rejected(
                validator,
                model_name=SYMAI_MODEL_ALIAS,
                route_binding=route_binding,
                generation_options=drifted_settings,
            )
        )

    contract_checks = (
        "canonical_request_contract_accepted",
        "canonical_schema_exact_match",
        "canonical_settings_exact_match",
        "realization_request_contract_accepted",
        "realization_schema_exact_match",
        "realization_settings_exact_match",
        "model_alias_mismatch_rejected",
        "route_binding_mismatch_rejected",
        "canonical_schema_mismatch_rejected",
        "canonical_settings_mismatch_rejected",
        "realization_schema_mismatch_rejected",
        "realization_settings_mismatch_rejected",
    )
    checks["route_contract_validation_passed"] = all(
        checks[key] is True for key in contract_checks
    )
    effective["validated_request_contracts"] = normalized
    if not checks["route_contract_validation_passed"]:
        failed = [key for key in contract_checks if checks[key] is not True]
        return CapabilityRecord.unavailable(
            "symai_leanstral_route",
            requested,
            effective=effective,
            checks=checks,
            reason=(
                "SyMAI side-effect-free route-contract validation failed: "
                + ", ".join(failed)
            ),
        )
    return CapabilityRecord.available(
        "symai_leanstral_route",
        requested,
        effective,
        checks,
    )


def _file_sha256(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _version_from_output(output: bytes, pattern: str) -> str | None:
    match = re.search(pattern, output.decode("utf-8", "replace"))
    return match.group(1) if match else None


def probe_hammer_cvc5(
    config: ProbeConfig,
    *,
    version_getter: VersionGetter | None = None,
    module_finder: ModuleFinder | None = None,
    command_runner: CommandRunner | None = None,
) -> CapabilityRecord:
    requested = {
        "hammer_distribution": "ipfs-datasets-py",
        "hammer_module": "ipfs_datasets_py.logic.hammers",
        "solver": "cvc5",
        "solver_version_requirement": ">=1.0.0,<2.0.0",
        "smoke_logic": "QF_UF",
        "expected_result": "sat",
        "timeout_seconds": config.command_timeout_seconds,
    }
    get_version = version_getter or _distribution_version
    find_module = module_finder or _module_spec
    run = command_runner or _bounded_command
    hammer_version = get_version("ipfs-datasets-py")
    hammer_spec = find_module("ipfs_datasets_py.logic.hammers")
    executable = shutil.which("cvc5")
    effective: dict[str, Any] = {
        "hammer_distribution": "ipfs-datasets-py",
        "hammer_version": hammer_version,
        "hammer_module": "ipfs_datasets_py.logic.hammers",
        "hammer_source_identity": _source_identity(hammer_spec),
        "solver": "cvc5",
        "solver_path": executable,
    }
    if hammer_spec is None or executable is None:
        return CapabilityRecord.unavailable(
            "hammer_cvc5",
            requested,
            effective=effective,
            checks={"bounded_smoke_passed": False},
            reason="Hammer module or cvc5 executable is unavailable",
        )
    try:
        version_result = run(
            (executable, "--version"),
            None,
            config.command_timeout_seconds,
            config.max_command_output_bytes,
        )
        smoke_input = (
            b"(set-logic QF_UF)\n"
            b"(declare-const p Bool)\n"
            b"(assert (or p (not p)))\n"
            b"(check-sat)\n"
        )
        smoke_result = run(
            (executable, "--lang=smt2", "--tlimit=1000"),
            smoke_input,
            config.command_timeout_seconds,
            config.max_command_output_bytes,
        )
    except OSError as exc:
        return CapabilityRecord.unavailable(
            "hammer_cvc5",
            requested,
            effective=effective,
            checks={"bounded_smoke_passed": False},
            reason=f"cvc5 execution failed: {type(exc).__name__}",
        )
    effective.update(
        {
            "solver_executable_sha256": _file_sha256(Path(executable)),
            "solver_version": _version_from_output(
                version_result.output, r"\bversion\s+([0-9][^\s]*)"
            ),
            "version_probe": version_result.to_check(),
            "smoke": smoke_result.to_check(),
        }
    )
    output = smoke_result.output.decode("utf-8", "replace").strip()
    solver_version = _version_from_output(
        version_result.output, r"\bversion\s+([0-9][^\s]*)"
    )
    solver_version_numbers = _numeric_version(solver_version)
    version_requirement_met = bool(
        solver_version_numbers
        and solver_version_numbers >= (1, 0, 0)
        and solver_version_numbers < (2, 0, 0)
    )
    passed = (
        version_result.return_code == 0
        and not version_result.timed_out
        and version_requirement_met
        and smoke_result.return_code == 0
        and not smoke_result.timed_out
        and not smoke_result.output_truncated
        and output == "sat"
    )
    checks = {
        "bounded_smoke_passed": passed,
        "version_requirement_met": version_requirement_met,
        "smoke_input_sha256": hashlib.sha256(smoke_input).hexdigest(),
        "timeout_seconds": config.command_timeout_seconds,
        "max_retained_output_bytes": config.max_command_output_bytes,
    }
    if not passed:
        return CapabilityRecord.unavailable(
            "hammer_cvc5",
            requested,
            effective=effective,
            checks=checks,
            reason="bounded cvc5 tautology smoke did not return exactly sat",
        )
    return CapabilityRecord.available(
        "hammer_cvc5",
        requested,
        effective,
        checks,
    )


def probe_lean(
    config: ProbeConfig,
    *,
    command_runner: CommandRunner | None = None,
) -> CapabilityRecord:
    requested = {
        "toolchain": "Lean 4",
        "executable": "lean",
        "smoke_theorem": "srt_identity",
        "expected_result": "kernel accepted with empty output",
        "timeout_seconds": config.command_timeout_seconds,
    }
    run = command_runner or _bounded_command
    executable = shutil.which("lean")
    effective: dict[str, Any] = {
        "toolchain": "Lean 4",
        "path": executable,
    }
    if executable is None:
        return CapabilityRecord.unavailable(
            "lean",
            requested,
            effective=effective,
            checks={"bounded_smoke_passed": False},
            reason="Lean executable is unavailable",
        )
    source = (
        "theorem srt_identity (n : Nat) : n = n := by\n"
        "  rfl\n"
    ).encode("utf-8")
    try:
        version_result = run(
            (executable, "--version"),
            None,
            config.command_timeout_seconds,
            config.max_command_output_bytes,
        )
        with tempfile.TemporaryDirectory(
            prefix="srt-lean-capability-"
        ) as temporary:
            smoke_path = Path(temporary) / "Smoke.lean"
            smoke_path.write_bytes(source)
            smoke_result = run(
                (executable, str(smoke_path)),
                None,
                config.command_timeout_seconds,
                config.max_command_output_bytes,
            )
    except OSError as exc:
        return CapabilityRecord.unavailable(
            "lean",
            requested,
            effective=effective,
            checks={"bounded_smoke_passed": False},
            reason=f"Lean execution failed: {type(exc).__name__}",
        )
    effective.update(
        {
            "executable_sha256": _file_sha256(Path(executable)),
            "version": _version_from_output(
                version_result.output, r"Lean \(version\s+([^,\s]+)"
            ),
            "version_probe": version_result.to_check(),
            "smoke": {
                **smoke_result.to_check(),
                "arguments": [executable, "<temporary>/Smoke.lean"],
            },
        }
    )
    passed = (
        version_result.return_code == 0
        and b"Lean (version 4." in version_result.output
        and not version_result.timed_out
        and smoke_result.return_code == 0
        and not smoke_result.timed_out
        and not smoke_result.output_truncated
        and not smoke_result.output.strip()
    )
    checks = {
        "bounded_smoke_passed": passed,
        "smoke_source_sha256": hashlib.sha256(source).hexdigest(),
        "timeout_seconds": config.command_timeout_seconds,
        "max_retained_output_bytes": config.max_command_output_bytes,
    }
    if not passed:
        return CapabilityRecord.unavailable(
            "lean",
            requested,
            effective=effective,
            checks=checks,
            reason="bounded Lean kernel smoke was not accepted cleanly",
        )
    return CapabilityRecord.available(
        "lean",
        requested,
        effective,
        checks,
    )


def _probe_failure(
    capability_id: str,
    requested: Mapping[str, Any],
    exc: BaseException,
) -> CapabilityRecord:
    return CapabilityRecord.unavailable(
        capability_id,
        requested,
        checks={"probe_completed": False},
        reason=f"capability probe raised {type(exc).__name__}",
    )


def _bindings(
    direct: CapabilityRecord,
    symai: CapabilityRecord,
) -> dict[str, Any]:
    direct_identity = (
        None
        if direct.effective_identity is None
        else {
            key: direct.effective_identity.get(key)
            for key in ("route", "provider", "endpoint", "model", "backend")
        }
    )
    symai_identity = (
        None
        if symai.effective_identity is None
        else {
            "route": symai.effective_identity.get("route"),
            "provider": symai.effective_identity.get("provider"),
            "model_alias": symai.effective_identity.get("model_alias"),
            "resolved_provider": symai.effective_identity.get(
                "resolved_provider"
            ),
            "resolved_endpoint": symai.effective_identity.get(
                "resolved_endpoint"
            ),
            "resolved_model": symai.effective_identity.get("resolved_model"),
            "resolved_backend": symai.effective_identity.get(
                "resolved_backend"
            ),
        }
    )
    same = (
        direct.status == "available"
        and symai.status == "available"
        and direct_identity is not None
        and symai_identity is not None
        and direct_identity["provider"] == symai_identity["resolved_provider"]
        and direct_identity["endpoint"] == symai_identity["resolved_endpoint"]
        and direct_identity["model"] == symai_identity["resolved_model"]
        and direct_identity["backend"] == symai_identity["resolved_backend"]
    )
    return {
        "direct_leanstral": direct_identity,
        "symai_leanstral": symai_identity,
        "same_effective_model": same,
        "same_effective_service": same,
        "shared_model_capacity": LEANSTRAL_CAPACITY,
    }


def capture_capability_inventory(
    *,
    run_id: str = DEFAULT_RUN_ID,
    captured_at_utc: str | None = None,
    config: ProbeConfig | None = None,
    probes: Mapping[str, Callable[[], CapabilityRecord]] | None = None,
) -> CapabilityInventory:
    """Probe every identity and retain failures as unavailable records.

    ``probes`` is an all-or-partial injection seam for unit tests and audited
    callers.  A supplied probe must still return the record for its exact key.
    Exceptions never remove records from the inventory.
    """

    active = config or ProbeConfig()
    injected = dict(probes or {})
    records: dict[str, CapabilityRecord] = {}

    def invoke(
        capability_id: str,
        default: Callable[[], CapabilityRecord],
        requested: Mapping[str, Any],
    ) -> CapabilityRecord:
        try:
            record = injected.get(capability_id, default)()
            if record.id != capability_id:
                raise CapabilityProbeError(
                    f"probe for {capability_id} returned {record.id}"
                )
            return record
        except Exception as exc:
            return _probe_failure(capability_id, requested, exc)

    records["python"] = invoke("python", probe_python, _requested_python())
    records["multiformats"] = invoke(
        "multiformats",
        probe_multiformats,
        {
            "distribution": "multiformats",
            "version_requirement": ">=0.3.0",
        },
    )
    records["spacy_pipeline"] = invoke(
        "spacy_pipeline",
        probe_spacy,
        {
            "distribution": "spacy",
            "version": SPACY_VERSION,
            "model": SPACY_MODEL,
            "model_version": SPACY_MODEL_VERSION,
            "pipeline": list(SPACY_PIPELINE),
            "fallback_allowed": False,
        },
    )
    records["autoencoder_state"] = invoke(
        "autoencoder_state",
        lambda: probe_autoencoder_state(active),
        {
            "path": AUTOENCODER_STATE_RELATIVE_PATH.as_posix(),
            "sha256": AUTOENCODER_STATE_SHA256,
            "cid": AUTOENCODER_STATE_CID,
            "access": "read_only",
        },
    )
    records["leanstral_direct"] = invoke(
        "leanstral_direct",
        lambda: probe_leanstral_direct(active),
        _leanstral_requested(),
    )
    records["symai_leanstral_route"] = invoke(
        "symai_leanstral_route",
        lambda: probe_symai_leanstral_route(
            records["leanstral_direct"]
        ),
        {
            "route": "symai_router",
            "distribution": "symbolicai",
            "version": SYMAI_VERSION,
            "resolved_model": LEANSTRAL_MODEL,
            "independent_model": False,
        },
    )
    records["hammer_cvc5"] = invoke(
        "hammer_cvc5",
        lambda: probe_hammer_cvc5(active),
        {
            "hammer_module": "ipfs_datasets_py.logic.hammers",
            "solver": "cvc5",
            "solver_version_requirement": ">=1.0.0,<2.0.0",
        },
    )
    records["lean"] = invoke(
        "lean",
        lambda: probe_lean(active),
        {"toolchain": "Lean 4", "executable": "lean"},
    )
    timestamp = captured_at_utc or (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    direct = records["leanstral_direct"]
    symai = records["symai_leanstral_route"]
    return CapabilityInventory(
        run_id=run_id,
        captured_at_utc=timestamp,
        capabilities=tuple(records[item] for item in CAPABILITY_IDS),
        bindings=_bindings(direct, symai),
    )


def canonical_inventory_json(inventory: CapabilityInventory) -> str:
    return json.dumps(
        inventory.to_dict(),
        allow_nan=False,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ) + "\n"


def write_inventory(
    inventory: CapabilityInventory,
    output: Path = DEFAULT_OUTPUT,
) -> None:
    """Atomically write the one authorized run-scoped receipt."""

    destination = output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = canonical_inventory_json(inventory)
    temporary = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}"
    )
    try:
        temporary.write_text(rendered, encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def load_inventory(path: Path = DEFAULT_OUTPUT) -> CapabilityInventory:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CapabilityProbeError(
            f"cannot read capability inventory: {type(exc).__name__}"
        ) from exc
    return CapabilityInventory.from_dict(value)


def require_available(
    inventory: CapabilityInventory,
    capability_ids: Sequence[str],
) -> None:
    """Fail closed for a requested arm without selecting another capability."""

    unknown = sorted(set(capability_ids) - set(CAPABILITY_IDS))
    if unknown:
        raise CapabilityProbeError(f"unknown required capabilities: {unknown}")
    unavailable = [
        item
        for item in capability_ids
        if inventory.by_id[item].status != "available"
    ]
    if unavailable:
        reasons = "; ".join(
            f"{item}: {inventory.by_id[item].reason}"
            for item in unavailable
        )
        raise CapabilityProbeError(
            "required capabilities are unavailable; no substitutes permitted: "
            + reasons
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Run-scoped capability receipt path.",
    )
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument(
        "--validate",
        type=Path,
        help="Validate an existing receipt without probing or writing.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.validate:
            inventory = load_inventory(args.validate)
        else:
            inventory = capture_capability_inventory(run_id=args.run_id)
            write_inventory(inventory, args.output)
        unavailable = [
            record.id
            for record in inventory.capabilities
            if record.status == "unavailable"
        ]
        sys.stdout.write(canonical_inventory_json(inventory))
        if unavailable:
            print(
                "explicitly unavailable capabilities: "
                + ", ".join(unavailable),
                file=sys.stderr,
            )
        return 0
    except CapabilityProbeError as exc:
        print(f"capability inventory failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
