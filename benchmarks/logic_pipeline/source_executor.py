"""Tracked production executor for one HSSL-G240 causal-runtime job.

The public orchestration layer deliberately launches a fixed repository
entrypoint with no outcome-bearing command-line arguments.  This module is
that entrypoint.  It accepts one private, canonical, pre-execution request,
reconstructs all typed inputs, selects a handler from a closed versioned
registry, invokes :func:`execute_causal_runtime_case_v2`, and exclusively
writes the resulting canonical evidence.

Requests may contain reviewed source text and proof context, so only their CID
is public.  Paths, source text, proof obligations, adapter configuration, and
environment values remain in the private process boundary.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, replace
from enum import Enum
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from types import MappingProxyType
from typing import Callable, Final, Mapping, Self

from .ablation import AblationPlan, ScheduledCase, _execute_job
from .adapters import (
    LEANSTRAL_MEASURED_MAX_NEW_TOKENS,
    SYMAI_EVIDENCE_SCHEMA_V2,
    StageAdapter,
    StageOutput,
)
from .capabilities import (
    CapabilityInventory,
    CapabilityKind,
    CapabilityStatus,
    ResourcePolicy,
    ResourceScheduler,
)
from .cache_measurement import (
    symai_backend_identity,
    symai_semantic_payload,
    symai_semantic_payload_sha256,
)
from .causal_runtime import (
    CausalRuntimeEvidenceV2,
    CompilerReferenceExposureV2,
    execute_causal_runtime_case_v2,
    validate_causal_runtime_evidence_v2,
)
from .content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from .contracts import (
    CAUSAL_PROOF_PROTOCOL_V2_CID,
    SEMANTIC_PROTOCOL_V2_CID,
    CaseResultRecord,
    FailureCode,
    Split,
    StageName,
    StageRecord,
    StageStatus,
)
from .namespace_provenance import G240JobNamespacePlanV2
from .runtime import (
    NativeKernelRunner,
    build_live_runtime,
    prepare_symai_runtime_configuration,
    resolve_symai_runtime_provider_model,
)
from .source_bound_import import import_source_bound_ipfs_accelerate
from .source_bootstrap_contract import (
    G240_TRACKED_SOURCE_BOOTSTRAP_COMMAND_V2,
    G240BootstrapConfinementReceiptV2,
    G240BootstrapContractError,
    g240_bootstrap_git_observation_cid,
    validate_g240_bootstrap_confinement_receipt_v2,
)
from .variants import get_causal_proof_variant_profile


G240_EXECUTION_REQUEST_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "source-runtime-execution-request.v2"
)
G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "synthetic-test-runtime-execution-request.v2"
)
G240_LIVE_ADAPTER_FACTORY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "live-runtime-adapter-factory.v2"
)
G240_SYNTHETIC_ADAPTER_FACTORY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "synthetic-inert-adapter-factory.v2"
)
G240_LIVE_ADAPTER_FACTORY_ID_V2: Final = "hssl-live-runtime-v2"
G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2: Final = (
    "hssl-synthetic-inert-runtime-v2"
)
G240_EXECUTION_REQUEST_FILE_V2: Final = "execution-request.json"
G240_RUNTIME_PREFLIGHT_FILE_V2: Final = "runtime-import-preflight.json"
G240_TRACKED_SOURCE_EXECUTOR_MODULE_V2: Final = (
    "benchmarks.logic_pipeline.source_bootstrap"
)
G240_TRACKED_SOURCE_EXECUTOR_COMMAND_V2: Final = (
    G240_TRACKED_SOURCE_BOOTSTRAP_COMMAND_V2
)
_G240_SYNTHETIC_TEST_ENVIRONMENT_KEY_V2: Final = (
    "HSSL_G240_TEST_ONLY_SYNTHETIC_REQUEST_CID"
)


class _G240SyntheticTestCapabilityV2:
    """In-process capability used only by synthetic subprocess tests."""


_G240_SYNTHETIC_TEST_CAPABILITY_V2: Final = (
    _G240SyntheticTestCapabilityV2()
)


class _G240BootstrapStage2CapabilityV2:
    """In-process authority issued only by the tracked stage-one bootstrap."""


_G240_BOOTSTRAP_STAGE2_CAPABILITY_V2: Final = (
    _G240BootstrapStage2CapabilityV2()
)

_EXECUTION_MODES: Final = frozenset({"source", "replay"})
_FRONTEND_STAGES: Final = frozenset(
    {StageName.COMPILER, StageName.SPACY, StageName.SYMAI}
)
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_PYTHON_MODULE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z"
)
_HEX_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_REQUEST_BYTES: Final = 64 * 1024 * 1024
_G240_RUNTIME_PREFLIGHT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "runtime-import-preflight.v2"
)
_G240_PHYSICAL_CACHE_ENTRY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "physical-stage-cache-entry.v2"
)
_G240_CACHE_ENTRY_PREFIX: Final = "entry-"
_G240_CACHE_ENTRY_SUFFIX: Final = ".json"
_MAX_CACHE_ENTRY_BYTES: Final = 8 * 1024 * 1024


class G240SourceExecutorError(ValueError):
    """Raised when a private request or execution boundary fails closed."""


class _G240DiskCache(MutableMapping[str, object]):
    """Canonical CID-addressed cache rooted in one physical stage namespace."""

    def __init__(self, root: Path) -> None:
        self._root = _private_real_directory(
            Path(root), "G240 physical stage cache"
        )

    @staticmethod
    def _key(value: object) -> str:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 512
            or "\0" in value
        ):
            raise G240SourceExecutorError(
                "G240 physical cache key must be a bounded nonempty string"
            )
        return value

    def _entry_path(self, key: str) -> Path:
        address = cid_for_dag_json(
            {
                "schema": _G240_PHYSICAL_CACHE_ENTRY_SCHEMA_V2,
                "cache_key": self._key(key),
            }
        )
        return (
            self._root
            / f"{_G240_CACHE_ENTRY_PREFIX}{address}"
            f"{_G240_CACHE_ENTRY_SUFFIX}"
        )

    def _read_entry(self, path: Path) -> tuple[str, object]:
        try:
            metadata = path.lstat()
            resolved = path.resolve(strict=True)
            payload = path.read_bytes()
        except OSError as exc:
            raise G240SourceExecutorError(
                "cannot read G240 physical cache entry"
            ) from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or not resolved.is_relative_to(self._root)
            or not payload
            or len(payload) > _MAX_CACHE_ENTRY_BYTES
        ):
            raise G240SourceExecutorError(
                "G240 physical cache entry is not a bounded private file"
            )
        try:
            text_value = payload.decode("utf-8")
            decoded = json.loads(
                text_value,
                object_pairs_hook=_reject_duplicate_pairs,
            )
            entry = _mapping(decoded, "G240 physical cache entry")
            _exact(
                entry,
                {"schema", "cache_key", "value"},
                "G240 physical cache entry",
            )
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, G240SourceExecutorError):
                raise
            raise G240SourceExecutorError(
                "G240 physical cache entry is not strict JSON"
            ) from exc
        key = self._key(entry["cache_key"])
        if (
            entry["schema"] != _G240_PHYSICAL_CACHE_ENTRY_SCHEMA_V2
            or path != self._entry_path(key)
            or payload
            != canonical_dag_json_bytes(_plain(entry)) + b"\n"
        ):
            raise G240SourceExecutorError(
                "G240 physical cache entry differs from its CID address"
            )
        return key, entry["value"]

    def __getitem__(self, key: str) -> object:
        path = self._entry_path(key)
        if not path.exists():
            raise KeyError(key)
        observed_key, value = self._read_entry(path)
        if observed_key != key:
            raise G240SourceExecutorError(
                "G240 physical cache lookup returned a foreign key"
            )
        return value

    def __setitem__(self, key: str, value: object) -> None:
        safe_key = self._key(key)
        entry = {
            "schema": _G240_PHYSICAL_CACHE_ENTRY_SCHEMA_V2,
            "cache_key": safe_key,
            "value": _plain(value),
        }
        path = self._entry_path(safe_key)
        payload = canonical_dag_json_bytes(entry) + b"\n"
        if len(payload) > _MAX_CACHE_ENTRY_BYTES:
            raise G240SourceExecutorError(
                "G240 physical cache entry exceeds its size bound"
            )
        if path.exists():
            observed_key, observed_value = self._read_entry(path)
            if (
                observed_key != safe_key
                or _plain(observed_value) != entry["value"]
            ):
                raise G240SourceExecutorError(
                    "G240 physical cache entry cannot be overwritten"
                )
            return
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise G240SourceExecutorError(
                "cannot exclusively create G240 physical cache entry"
            ) from exc

    def __delitem__(self, key: str) -> None:
        path = self._entry_path(key)
        if not path.exists():
            raise KeyError(key)
        observed_key, _value = self._read_entry(path)
        if observed_key != key:
            raise G240SourceExecutorError(
                "G240 physical cache deletion resolved a foreign key"
            )
        try:
            path.unlink()
        except OSError as exc:
            raise G240SourceExecutorError(
                "cannot invalidate G240 physical cache entry"
            ) from exc

    def __iter__(self) -> Iterator[str]:
        for path in sorted(
            self._root.glob(
                f"{_G240_CACHE_ENTRY_PREFIX}*"
                f"{_G240_CACHE_ENTRY_SUFFIX}"
            )
        ):
            key, _value = self._read_entry(path)
            yield key

    def __len__(self) -> int:
        return sum(1 for _key in self)


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise G240SourceExecutorError(
                "G240 executor DAG-JSON objects require string keys"
            )
        return {str(key): _plain(member) for key, member in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(member) for member in value]
    if value is None or type(value) in {str, bool, int, float}:
        if isinstance(value, float) and not math.isfinite(value):
            raise G240SourceExecutorError(
                "G240 executor JSON numbers must be finite"
            )
        return value
    raise G240SourceExecutorError(
        f"G240 executor value is not DAG-JSON: {type(value).__name__}"
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise G240SourceExecutorError(
            f"{field} must be an object with string keys"
        )
    return value


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise G240SourceExecutorError(
            f"{field} fields changed: "
            f"missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _cid(value: object, field: str, *, codec: str = "dag-json") -> str:
    try:
        return validate_cid(value, codecs=(codec,))
    except (TypeError, ValueError) as exc:
        raise G240SourceExecutorError(
            f"{field} must be a canonical {codec} CID"
        ) from exc


def _safe_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_ID.fullmatch(value)
        or value in {".", ".."}
    ):
        raise G240SourceExecutorError(
            f"{field} must be a safe nonempty identifier"
        )
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise G240SourceExecutorError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _commit(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HEX_COMMIT.fullmatch(value):
        raise G240SourceExecutorError(
            f"{field} must be a full lowercase Git object ID"
        )
    return value


def _bounded_seconds(
    value: object,
    field: str,
    *,
    maximum: float,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 < float(value) <= maximum
    ):
        raise G240SourceExecutorError(
            f"{field} must be finite, positive, and at most {maximum:g}"
        )
    return float(value)


def _plan_cid(plan: AblationPlan) -> str:
    return cid_for_dag_json(_plain(plan.to_dict()))


def _job_cid(job: ScheduledCase) -> str:
    return cid_for_dag_json(_plain(job.to_dict()))


def _semantic_result_cid(result: CaseResultRecord) -> str:
    return cid_for_dag_json(_plain(result.to_dict()))


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise G240SourceExecutorError(
                f"duplicate JSON key in G240 executor input: {key}"
            )
        result[key] = value
    return result


def _runtime_environment_artifacts(
    value: object,
) -> Mapping[str, Mapping[str, str]]:
    raw = _mapping(value, "runtime_environment_artifacts")
    artifacts: dict[str, Mapping[str, str]] = {}
    for label in sorted(raw):
        safe_label = _safe_id(label, "runtime environment artifact label")
        descriptor = _mapping(
            raw[label], f"runtime_environment_artifacts.{safe_label}"
        )
        _exact(
            descriptor,
            {"path", "payload_cid"},
            f"runtime_environment_artifacts.{safe_label}",
        )
        path_value = descriptor["path"]
        if (
            not isinstance(path_value, str)
            or not Path(path_value).is_absolute()
        ):
            raise G240SourceExecutorError(
                "runtime environment artifact paths must be absolute"
            )
        artifacts[safe_label] = MappingProxyType(
            {
                "path": path_value,
                "payload_cid": _cid(
                    descriptor["payload_cid"],
                    (
                        "runtime_environment_artifacts."
                        f"{safe_label}.payload_cid"
                    ),
                    codec="raw",
                ),
            }
        )
    return MappingProxyType(artifacts)


def _validate_live_factory_configuration(
    value: Mapping[str, object],
    *,
    source_run_id: str,
    environment_sha256: str,
) -> Mapping[str, object]:
    _exact(
        value,
        {
            "schema",
            "capability_inventory",
            "capability_inventory_cid",
            "kernel_timeout_seconds",
            "leanstral_timeout_seconds",
            "leanstral_max_new_tokens",
        },
        "live adapter factory configuration",
    )
    if value["schema"] != G240_LIVE_ADAPTER_FACTORY_SCHEMA_V2:
        raise G240SourceExecutorError(
            "unsupported live adapter factory schema"
        )
    try:
        inventory = CapabilityInventory.from_dict(
            value["capability_inventory"]
        )
    except (TypeError, ValueError) as exc:
        raise G240SourceExecutorError(
            "live adapter capability inventory failed typed replay"
        ) from exc
    if (
        inventory.cid
        != _cid(
            value["capability_inventory_cid"],
            "capability_inventory_cid",
        )
        or inventory.sha256 != environment_sha256
        or inventory.run_id != source_run_id
    ):
        raise G240SourceExecutorError(
            "live adapter inventory differs from the source run/environment"
        )
    kernel_timeout = _bounded_seconds(
        value["kernel_timeout_seconds"],
        "kernel_timeout_seconds",
        maximum=300.0,
    )
    leanstral_timeout = _bounded_seconds(
        value["leanstral_timeout_seconds"],
        "leanstral_timeout_seconds",
        maximum=300.0,
    )
    tokens = value["leanstral_max_new_tokens"]
    if (
        isinstance(tokens, bool)
        or not isinstance(tokens, int)
        or not 0 < tokens <= LEANSTRAL_MEASURED_MAX_NEW_TOKENS
    ):
        raise G240SourceExecutorError(
            "leanstral_max_new_tokens must be from 1 to "
            f"{LEANSTRAL_MEASURED_MAX_NEW_TOKENS}"
        )
    return MappingProxyType(
        {
            "schema": value["schema"],
            "capability_inventory": inventory.to_dict(),
            "capability_inventory_cid": inventory.cid,
            "kernel_timeout_seconds": kernel_timeout,
            "leanstral_timeout_seconds": leanstral_timeout,
            "leanstral_max_new_tokens": tokens,
        }
    )


def _validate_synthetic_factory_configuration(
    value: Mapping[str, object],
) -> Mapping[str, object]:
    _exact(
        value,
        {"schema", "behavior"},
        "synthetic adapter factory configuration",
    )
    if (
        value["schema"] != G240_SYNTHETIC_ADAPTER_FACTORY_SCHEMA_V2
        or value["behavior"] != "inert-proof-backends"
    ):
        raise G240SourceExecutorError(
            "unsupported synthetic adapter factory configuration"
        )
    return MappingProxyType(
        {
            "schema": value["schema"],
            "behavior": value["behavior"],
        }
    )


def _validate_adapter_configuration(
    factory_id: str,
    value: object,
    *,
    source_run_id: str,
    environment_sha256: str,
) -> Mapping[str, object]:
    config = _mapping(value, "adapter_configuration")
    if factory_id == G240_LIVE_ADAPTER_FACTORY_ID_V2:
        return _validate_live_factory_configuration(
            config,
            source_run_id=source_run_id,
            environment_sha256=environment_sha256,
        )
    if factory_id == G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2:
        return _validate_synthetic_factory_configuration(config)
    raise G240SourceExecutorError(
        "adapter_factory_id is absent from the closed G240 registry"
    )


@dataclass(frozen=True, slots=True)
class G240ExecutionRequestV2:
    """Private pre-execution inputs for one tracked G240 invocation."""

    execution_mode: str
    execution_run_id: str
    source_run_id: str
    source_commit: str
    policy_cid: str
    runtime_orchestration_policy_cid: str
    plan: Mapping[str, object]
    plan_cid: str
    job: Mapping[str, object]
    job_cid: str
    coordinate_cid: str
    process_namespace_cid: str
    state_namespace_cid: str
    output_namespace_cid: str
    cache_namespace_cids: Mapping[str, str]
    environment_cid: str
    environment_sha256: str
    interpreter_identity_cid: str | None
    git_executable_cid: str | None
    runtime_environment_artifacts: Mapping[
        str, Mapping[str, str]
    ]
    semantic_result: Mapping[str, object] | None
    semantic_result_cid: str | None
    compiler_exposure: Mapping[str, object] | None
    compiler_exposure_cid: str | None
    source_text: str
    source_cid: str
    proof_context: Mapping[str, object]
    proof_context_cid: str
    adapter_factory_id: str
    adapter_configuration: Mapping[str, object]
    adapter_configuration_cid: str
    source_execution_request_cid: str | None
    source_runtime_evidence_cid: str | None
    holdout_permitted: bool
    schema: str = G240_EXECUTION_REQUEST_SCHEMA_V2
    request_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema not in {
            G240_EXECUTION_REQUEST_SCHEMA_V2,
            G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2,
        }:
            raise G240SourceExecutorError(
                "unsupported G240 execution request schema"
            )
        if self.execution_mode not in _EXECUTION_MODES:
            raise G240SourceExecutorError(
                "G240 execution mode must be source or replay"
            )
        execution_run_id = _safe_id(
            self.execution_run_id, "execution_run_id"
        )
        source_run_id = _safe_id(self.source_run_id, "source_run_id")
        source_commit = _commit(self.source_commit, "source_commit")
        object.__setattr__(self, "execution_run_id", execution_run_id)
        object.__setattr__(self, "source_run_id", source_run_id)
        object.__setattr__(self, "source_commit", source_commit)
        for field in (
            "policy_cid",
            "runtime_orchestration_policy_cid",
            "plan_cid",
            "job_cid",
            "coordinate_cid",
            "process_namespace_cid",
            "state_namespace_cid",
            "output_namespace_cid",
            "environment_cid",
            "proof_context_cid",
            "adapter_configuration_cid",
        ):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        if self.interpreter_identity_cid is not None:
            object.__setattr__(
                self,
                "interpreter_identity_cid",
                _cid(
                    self.interpreter_identity_cid,
                    "interpreter_identity_cid",
                ),
            )
        if self.git_executable_cid is not None:
            object.__setattr__(
                self,
                "git_executable_cid",
                _cid(
                    self.git_executable_cid,
                    "git_executable_cid",
                    codec="raw",
                ),
            )
        object.__setattr__(
            self,
            "source_cid",
            _cid(self.source_cid, "source_cid", codec="raw"),
        )
        environment_sha256 = _sha256(
            self.environment_sha256, "environment_sha256"
        )
        object.__setattr__(
            self, "environment_sha256", environment_sha256
        )
        if type(self.holdout_permitted) is not bool or self.holdout_permitted:
            raise G240SourceExecutorError(
                "G240 source/replay execution may not authorize holdout"
            )
        if self.execution_mode == "source":
            if (
                execution_run_id != source_run_id
                or self.source_execution_request_cid is not None
                or self.source_runtime_evidence_cid is not None
            ):
                raise G240SourceExecutorError(
                    "source execution must use its source run and no parent "
                    "execution request/runtime evidence"
                )
        else:
            if execution_run_id == source_run_id:
                raise G240SourceExecutorError(
                    "replay execution requires a fresh run id"
                )
            object.__setattr__(
                self,
                "source_execution_request_cid",
                _cid(
                    self.source_execution_request_cid,
                    "source_execution_request_cid",
                ),
            )
            object.__setattr__(
                self,
                "source_runtime_evidence_cid",
                _cid(
                    self.source_runtime_evidence_cid,
                    "source_runtime_evidence_cid",
                ),
            )
        try:
            plan = AblationPlan.from_dict(self.plan)
            job = ScheduledCase.from_dict(self.job)
        except (TypeError, ValueError) as exc:
            raise G240SourceExecutorError(
                "G240 execution request typed inputs failed replay"
            ) from exc
        if (
            _plan_cid(plan) != self.plan_cid
            or _job_cid(job) != self.job_cid
            or job not in plan.jobs
            or plan.run_id != source_run_id
            or plan.environment_sha256 != environment_sha256
            or plan.split is Split.HOLDOUT
        ):
            raise G240SourceExecutorError(
                "G240 request plan/job/source/environment join changed"
            )
        source_text = self.source_text
        if (
            not isinstance(source_text, str)
            or not source_text.strip()
            or not isinstance(job.input_data, Mapping)
            or job.input_data.get("text") != source_text
            or cid_for_bytes(source_text.encode("utf-8"))
            != self.source_cid
        ):
            raise G240SourceExecutorError(
                "G240 request source bytes differ from the scheduled job"
            )
        factory_id = _safe_id(
            self.adapter_factory_id, "adapter_factory_id"
        )
        synthetic_test_request = (
            self.schema
            == G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2
        )
        if synthetic_test_request != (
            factory_id == G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2
        ):
            raise G240SourceExecutorError(
                "synthetic adapters require the distinct test-only request "
                "schema and live adapters forbid it"
            )
        artifacts = _runtime_environment_artifacts(
            self.runtime_environment_artifacts
        )
        if synthetic_test_request:
            if (
                self.interpreter_identity_cid is not None
                or self.git_executable_cid is not None
                or artifacts
            ):
                raise G240SourceExecutorError(
                    "synthetic requests may not claim a production runtime "
                    "environment"
                )
        elif (
            self.interpreter_identity_cid is None
            or self.git_executable_cid is None
            or not artifacts
        ):
            raise G240SourceExecutorError(
                "production requests require pinned interpreter, Git, and "
                "runtime lock/receipt artifacts"
            )
        expected_frontend_present = (
            self.semantic_result is not None
            or self.semantic_result_cid is not None
            or self.compiler_exposure is not None
            or self.compiler_exposure_cid is not None
        )
        # Production source outcomes must be unknown at freeze time.  A
        # production replay is post-outcome and therefore binds exact expected
        # source-executed frontend/exposure values.  Synthetic fixtures live
        # only in their distinct test request schema.
        frontend_expected = (
            self.execution_mode == "replay"
            or synthetic_test_request
        )
        if expected_frontend_present != frontend_expected:
            raise G240SourceExecutorError(
                "production source requests must omit precomputed frontend "
                "outcomes; replay/test requests must bind them"
            )
        semantic_result: CaseResultRecord | None = None
        compiler_exposure: CompilerReferenceExposureV2 | None = None
        if frontend_expected:
            try:
                semantic_result = CaseResultRecord.from_dict(
                    _mapping(self.semantic_result, "semantic_result")
                )
                compiler_exposure = CompilerReferenceExposureV2.from_dict(
                    _mapping(
                        self.compiler_exposure,
                        "compiler_exposure",
                    )
                )
            except (TypeError, ValueError) as exc:
                raise G240SourceExecutorError(
                    "expected frontend/exposure failed typed replay"
                ) from exc
            semantic_cid = _cid(
                self.semantic_result_cid,
                "semantic_result_cid",
            )
            exposure_cid = _cid(
                self.compiler_exposure_cid,
                "compiler_exposure_cid",
            )
            if (
                semantic_result.run_id != execution_run_id
                or semantic_result.case_id != job.case_id
                or semantic_result.case_manifest_sha256
                != plan.case_manifest_sha256
                or semantic_result.variant_id != job.variant_id
                or semantic_result.split is not plan.split
                or semantic_result.cache_mode is not job.cache_mode
                or _semantic_result_cid(semantic_result) != semantic_cid
                or not semantic_result.stages
                or any(
                    stage.stage not in _FRONTEND_STAGES
                    for stage in semantic_result.stages
                )
                or {
                    stage.provenance.environment_sha256
                    for stage in semantic_result.stages
                }
                != {environment_sha256}
            ):
                raise G240SourceExecutorError(
                    "expected semantic result differs from the exact "
                    "execution coordinate"
                )
            compiler_record = next(
                (
                    stage
                    for stage in semantic_result.stages
                    if stage.stage is StageName.COMPILER
                ),
                None,
            )
            if (
                compiler_record is None
                or compiler_exposure.receipt_cid != exposure_cid
                or compiler_exposure.source_cid != self.source_cid
                or compiler_exposure.compiler_record.run_id
                != execution_run_id
                or compiler_exposure.compiler_record.case_id
                != semantic_result.case_id
                or compiler_exposure.compiler_record.cache_mode
                is not semantic_result.cache_mode
                or compiler_exposure.compiler_record.split
                is not semantic_result.split
                or (
                    compiler_exposure.compiler_record
                    .case_manifest_sha256
                    != semantic_result.case_manifest_sha256
                )
                or (
                    compiler_exposure.compiler_record.provenance
                    .environment_sha256
                    != compiler_record.provenance.environment_sha256
                )
                or (
                    compiler_exposure.compiler_record.provenance.input_sha256
                    != compiler_record.provenance.input_sha256
                )
            ):
                raise G240SourceExecutorError(
                    "shared A0 compiler exposure differs from the exact "
                    "semantic case/cache/source coordinate"
                )
            object.__setattr__(
                self, "semantic_result_cid", semantic_cid
            )
            object.__setattr__(
                self, "compiler_exposure_cid", exposure_cid
            )
        proof_context = _mapping(self.proof_context, "proof_context")
        if cid_for_dag_json(_plain(proof_context)) != self.proof_context_cid:
            raise G240SourceExecutorError(
                "reviewed proof-context CID changed"
            )
        config = _validate_adapter_configuration(
            factory_id,
            self.adapter_configuration,
            source_run_id=source_run_id,
            environment_sha256=environment_sha256,
        )
        if (
            cid_for_dag_json(_plain(config))
            != self.adapter_configuration_cid
        ):
            raise G240SourceExecutorError(
                "adapter factory configuration CID changed"
            )
        cache_values = _mapping(
            self.cache_namespace_cids, "cache_namespace_cids"
        )
        caches = {
            _safe_id(stage, "cache stage"): _cid(
                value, f"cache_namespace_cids.{stage}"
            )
            for stage, value in cache_values.items()
        }
        expected_stages = {
            stage.value
            for stage in get_causal_proof_variant_profile(
                job.variant_id
            ).effective_stages
        }
        if set(caches) != expected_stages:
            raise G240SourceExecutorError(
                "G240 request cache namespace population differs from the "
                "runtime route"
            )
        object.__setattr__(
            self, "plan", MappingProxyType(plan.to_dict())
        )
        object.__setattr__(
            self, "job", MappingProxyType(job.to_dict())
        )
        object.__setattr__(
            self,
            "semantic_result",
            (
                None
                if semantic_result is None
                else MappingProxyType(semantic_result.to_dict())
            ),
        )
        object.__setattr__(
            self,
            "compiler_exposure",
            (
                None
                if compiler_exposure is None
                else MappingProxyType(compiler_exposure.to_dict())
            ),
        )
        object.__setattr__(
            self,
            "proof_context",
            MappingProxyType(dict(_plain(proof_context))),
        )
        object.__setattr__(self, "adapter_factory_id", factory_id)
        object.__setattr__(
            self, "adapter_configuration", config
        )
        object.__setattr__(
            self,
            "cache_namespace_cids",
            MappingProxyType(caches),
        )
        object.__setattr__(
            self,
            "runtime_environment_artifacts",
            artifacts,
        )
        expected_request = cid_for_dag_json(self.identity_payload())
        if self.request_cid is None:
            object.__setattr__(self, "request_cid", expected_request)
        elif _cid(self.request_cid, "request_cid") != expected_request:
            raise G240SourceExecutorError(
                "G240 execution request CID changed"
            )

    @property
    def typed_plan(self) -> AblationPlan:
        return AblationPlan.from_dict(self.plan)

    @property
    def typed_job(self) -> ScheduledCase:
        return ScheduledCase.from_dict(self.job)

    @property
    def typed_semantic_result(self) -> CaseResultRecord:
        if self.semantic_result is None:
            raise G240SourceExecutorError(
                "production source request has no precomputed semantic result"
            )
        return CaseResultRecord.from_dict(self.semantic_result)

    @property
    def typed_compiler_exposure(self) -> CompilerReferenceExposureV2:
        if self.compiler_exposure is None:
            raise G240SourceExecutorError(
                "production source request has no precomputed compiler "
                "exposure"
            )
        return CompilerReferenceExposureV2.from_dict(
            self.compiler_exposure
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            field: _plain(getattr(self, field))
            for field in self.__dataclass_fields__
            if field != "request_cid"
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "request_cid": self.request_cid,
        }

    @classmethod
    def create(
        cls,
        *,
        execution_mode: str,
        execution_run_id: str,
        source_run_id: str,
        source_commit: str,
        policy_cid: str,
        runtime_orchestration_policy_cid: str,
        plan: AblationPlan,
        job: ScheduledCase,
        coordinate: G240JobNamespacePlanV2,
        environment_cid: str,
        environment_sha256: str,
        source_text: str,
        proof_context: Mapping[str, object],
        adapter_factory_id: str,
        adapter_configuration: Mapping[str, object],
        semantic_result: CaseResultRecord | None = None,
        compiler_exposure: CompilerReferenceExposureV2 | None = None,
        interpreter_identity_cid: str | None = None,
        git_executable_cid: str | None = None,
        runtime_environment_artifacts: (
            Mapping[str, Mapping[str, str]] | None
        ) = None,
        source_execution_request_cid: str | None = None,
        source_runtime_evidence_cid: str | None = None,
        _test_only_synthetic_capability: object | None = None,
    ) -> Self:
        if not isinstance(coordinate, G240JobNamespacePlanV2):
            raise G240SourceExecutorError(
                "G240 execution request requires a typed namespace coordinate"
            )
        synthetic = (
            adapter_factory_id
            == G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2
        )
        if (
            synthetic
            and _test_only_synthetic_capability
            is not _G240_SYNTHETIC_TEST_CAPABILITY_V2
        ):
            raise G240SourceExecutorError(
                "synthetic request creation requires the private test-only "
                "capability"
            )
        if (
            not synthetic
            and _test_only_synthetic_capability is not None
        ):
            raise G240SourceExecutorError(
                "test-only capability cannot create a live request"
            )
        if execution_mode == "source" and not synthetic and (
            semantic_result is not None or compiler_exposure is not None
        ):
            raise G240SourceExecutorError(
                "production source requests must not precompute frontend "
                "outcomes"
            )
        if (
            (execution_mode == "replay" or synthetic)
            and (
                not isinstance(semantic_result, CaseResultRecord)
                or not isinstance(
                    compiler_exposure,
                    CompilerReferenceExposureV2,
                )
            )
        ):
            raise G240SourceExecutorError(
                "replay/test requests require exact frontend outcomes"
            )
        return cls(
            execution_mode=execution_mode,
            execution_run_id=execution_run_id,
            source_run_id=source_run_id,
            source_commit=source_commit,
            policy_cid=policy_cid,
            runtime_orchestration_policy_cid=(
                runtime_orchestration_policy_cid
            ),
            plan=plan.to_dict(),
            plan_cid=_plan_cid(plan),
            job=job.to_dict(),
            job_cid=_job_cid(job),
            coordinate_cid=str(coordinate.coordinate_cid),
            process_namespace_cid=coordinate.process_namespace_cid,
            state_namespace_cid=coordinate.state_namespace_cid,
            output_namespace_cid=coordinate.output_namespace_cid,
            cache_namespace_cids=dict(
                coordinate.cache_namespace_cids
            ),
            environment_cid=environment_cid,
            environment_sha256=environment_sha256,
            interpreter_identity_cid=interpreter_identity_cid,
            git_executable_cid=git_executable_cid,
            runtime_environment_artifacts=(
                {}
                if runtime_environment_artifacts is None
                else runtime_environment_artifacts
            ),
            semantic_result=(
                None
                if semantic_result is None
                else semantic_result.to_dict()
            ),
            semantic_result_cid=(
                None
                if semantic_result is None
                else _semantic_result_cid(semantic_result)
            ),
            compiler_exposure=(
                None
                if compiler_exposure is None
                else compiler_exposure.to_dict()
            ),
            compiler_exposure_cid=(
                None
                if compiler_exposure is None
                else compiler_exposure.receipt_cid
            ),
            source_text=source_text,
            source_cid=cid_for_bytes(source_text.encode("utf-8")),
            proof_context=dict(proof_context),
            proof_context_cid=cid_for_dag_json(
                _plain(proof_context)
            ),
            adapter_factory_id=adapter_factory_id,
            adapter_configuration=dict(adapter_configuration),
            adapter_configuration_cid=cid_for_dag_json(
                _plain(adapter_configuration)
            ),
            source_execution_request_cid=(
                source_execution_request_cid
            ),
            source_runtime_evidence_cid=source_runtime_evidence_cid,
            holdout_permitted=False,
            schema=(
                G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2
                if synthetic
                else G240_EXECUTION_REQUEST_SCHEMA_V2
            ),
        )

    @classmethod
    def create_replay(
        cls,
        source_request: object,
        *,
        replay_run_id: str,
        replay_process_namespace_cid: str,
        replay_state_namespace_cid: str,
        replay_output_namespace_cid: str,
        replay_cache_namespace_cids: Mapping[str, str],
        source_runtime_evidence: object,
        _test_only_synthetic_capability: object | None = None,
    ) -> Self:
        """Freeze post-source replay inputs without accepting a callable."""

        source = validate_g240_execution_request_v2(source_request)
        if source.execution_mode != "source":
            raise G240SourceExecutorError(
                "a replay request must derive from a source execution request"
            )
        synthetic = (
            source.schema
            == G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2
        )
        if (
            synthetic
            and _test_only_synthetic_capability
            is not _G240_SYNTHETIC_TEST_CAPABILITY_V2
        ):
            raise G240SourceExecutorError(
                "synthetic replay request requires the private test-only "
                "capability"
            )
        if (
            not synthetic
            and _test_only_synthetic_capability is not None
        ):
            raise G240SourceExecutorError(
                "test-only capability cannot create a live replay request"
            )
        source_runtime = validate_g240_runtime_for_execution_request_v2(
            source_runtime_evidence,
            source,
        )
        replay_frontend: list[StageRecord] = []
        for stage in source_runtime.semantic_frontend:
            provenance = replace(
                stage.provenance,
                upstream_stage_digests=tuple(
                    previous.digest
                    for previous in replay_frontend
                ),
            )
            replay_frontend.append(
                replace(
                    stage,
                    run_id=replay_run_id,
                    provenance=provenance,
                )
            )
        semantic_result = CaseResultRecord.from_stages(
            tuple(replay_frontend)
        )
        compiler_exposure = (
            CompilerReferenceExposureV2.from_compiler_record(
                replace(
                    source_runtime.compiler_exposure.compiler_record,
                    run_id=replay_run_id,
                ),
                source_text=source_runtime.source_text,
            )
        )
        return cls(
            execution_mode="replay",
            execution_run_id=replay_run_id,
            source_run_id=source.source_run_id,
            source_commit=source.source_commit,
            policy_cid=source.policy_cid,
            runtime_orchestration_policy_cid=(
                source.runtime_orchestration_policy_cid
            ),
            plan=source.plan,
            plan_cid=source.plan_cid,
            job=source.job,
            job_cid=source.job_cid,
            coordinate_cid=source.coordinate_cid,
            process_namespace_cid=replay_process_namespace_cid,
            state_namespace_cid=replay_state_namespace_cid,
            output_namespace_cid=replay_output_namespace_cid,
            cache_namespace_cids=dict(replay_cache_namespace_cids),
            environment_cid=source.environment_cid,
            environment_sha256=source.environment_sha256,
            interpreter_identity_cid=source.interpreter_identity_cid,
            git_executable_cid=source.git_executable_cid,
            runtime_environment_artifacts=(
                source.runtime_environment_artifacts
            ),
            semantic_result=semantic_result.to_dict(),
            semantic_result_cid=_semantic_result_cid(semantic_result),
            compiler_exposure=compiler_exposure.to_dict(),
            compiler_exposure_cid=compiler_exposure.receipt_cid,
            source_text=source.source_text,
            source_cid=source.source_cid,
            proof_context=source.proof_context,
            proof_context_cid=source.proof_context_cid,
            adapter_factory_id=source.adapter_factory_id,
            adapter_configuration=source.adapter_configuration,
            adapter_configuration_cid=source.adapter_configuration_cid,
            source_execution_request_cid=str(source.request_cid),
            source_runtime_evidence_cid=source_runtime.receipt_cid,
            holdout_permitted=False,
            schema=source.schema,
        )

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G240 execution request")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G240 execution request",
        )
        return cls(
            **{
                **data,
                "plan": _mapping(data["plan"], "plan"),
                "job": _mapping(data["job"], "job"),
                "cache_namespace_cids": _mapping(
                    data["cache_namespace_cids"],
                    "cache_namespace_cids",
                ),
                "runtime_environment_artifacts": _mapping(
                    data["runtime_environment_artifacts"],
                    "runtime_environment_artifacts",
                ),
                "semantic_result": (
                    None
                    if data["semantic_result"] is None
                    else _mapping(
                        data["semantic_result"], "semantic_result"
                    )
                ),
                "compiler_exposure": (
                    None
                    if data["compiler_exposure"] is None
                    else _mapping(
                        data["compiler_exposure"],
                        "compiler_exposure",
                    )
                ),
                "proof_context": _mapping(
                    data["proof_context"], "proof_context"
                ),
                "adapter_configuration": _mapping(
                    data["adapter_configuration"],
                    "adapter_configuration",
                ),
            }
        )  # type: ignore[arg-type]


def build_g240_live_adapter_configuration_v2(
    inventory: CapabilityInventory,
    *,
    kernel_timeout_seconds: float = 30.0,
    leanstral_timeout_seconds: float = 120.0,
    leanstral_max_new_tokens: int = (
        LEANSTRAL_MEASURED_MAX_NEW_TOKENS
    ),
) -> Mapping[str, object]:
    """Freeze the only production adapter factory's complete configuration."""

    if not isinstance(inventory, CapabilityInventory):
        raise G240SourceExecutorError(
            "live adapter configuration requires CapabilityInventory"
        )
    value = {
        "schema": G240_LIVE_ADAPTER_FACTORY_SCHEMA_V2,
        "capability_inventory": inventory.to_dict(),
        "capability_inventory_cid": inventory.cid,
        "kernel_timeout_seconds": kernel_timeout_seconds,
        "leanstral_timeout_seconds": leanstral_timeout_seconds,
        "leanstral_max_new_tokens": leanstral_max_new_tokens,
    }
    return _validate_live_factory_configuration(
        value,
        source_run_id=inventory.run_id,
        environment_sha256=inventory.sha256,
    )


def build_g240_synthetic_adapter_configuration_v2(
) -> Mapping[str, object]:
    """Return the fixed inert adapter set used only by synthetic tests."""

    return _validate_synthetic_factory_configuration(
        {
            "schema": G240_SYNTHETIC_ADAPTER_FACTORY_SCHEMA_V2,
            "behavior": "inert-proof-backends",
        }
    )


@dataclass(frozen=True, slots=True)
class _G240AdapterBundleV2:
    """Private split between source-executed frontends and proof adapters."""

    proof_adapters: Mapping[StageName, StageAdapter]
    frontend_routes: (
        Mapping[str, Mapping[StageName, StageAdapter]] | None
    )


AdapterFactory = Callable[
    [G240ExecutionRequestV2, Path],
    _G240AdapterBundleV2,
]


def _live_adapter_factory(
    request: G240ExecutionRequestV2,
    state_directory: Path,
) -> _G240AdapterBundleV2:
    config = _validate_live_factory_configuration(
        request.adapter_configuration,
        source_run_id=request.source_run_id,
        environment_sha256=request.environment_sha256,
    )
    inventory = CapabilityInventory.from_dict(
        config["capability_inventory"]
    )
    cache_paths = _environment_mapping("HSSL_G240_CACHE_ROOTS_JSON")
    stage_caches: dict[StageName, MutableMapping[str, object]] = {}
    symai_cache_path = cache_paths.get(StageName.SYMAI.value)
    if symai_cache_path is not None:
        stage_caches[StageName.SYMAI] = _G240DiskCache(
            Path(symai_cache_path)
        )
    runtime = build_live_runtime(
        inventory,
        # ``_execute_job(..., semantic_protocol_cid=...)`` validates the
        # complete frozen plan's frontend adapter population before invoking
        # the selected job.  Build every frozen route here; only the paired A0
        # and selected candidate are invoked below.
        variant_ids=request.typed_plan.variant_ids,
        state_directory=state_directory,
        kernel_timeout_seconds=float(
            config["kernel_timeout_seconds"]
        ),
        leanstral_timeout_seconds=float(
            config["leanstral_timeout_seconds"]
        ),
        leanstral_max_new_tokens=int(
            config["leanstral_max_new_tokens"]
        ),
        semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
        causal_proof_protocol_cid=CAUSAL_PROOF_PROTOCOL_V2_CID,
        stage_caches=stage_caches,
    )
    route = runtime.adapters[request.typed_job.variant_id]
    profile = get_causal_proof_variant_profile(
        request.typed_job.variant_id
    )
    proof_stages = (*profile.optional_order, StageName.KERNEL)
    return _G240AdapterBundleV2(
        proof_adapters=MappingProxyType(
            {stage: route[stage] for stage in proof_stages}
        ),
        frontend_routes=runtime.adapters,
    )


def _synthetic_adapter_factory(
    request: G240ExecutionRequestV2,
    _state_directory: Path,
) -> _G240AdapterBundleV2:
    _validate_synthetic_factory_configuration(
        request.adapter_configuration
    )
    profile = get_causal_proof_variant_profile(
        request.typed_job.variant_id
    )
    stages = (*profile.optional_order, StageName.KERNEL)
    kernel = NativeKernelRunner(
        "/bin/true",
        request.environment_sha256,
        _state_directory / "synthetic-native-kernel",
        timeout_seconds=1.0,
    )

    def failed_optional(stage: StageName) -> StageAdapter:
        if stage is StageName.HAMMER:
            output = StageOutput(
                status=StageStatus.FAILED,
                failure_code=FailureCode.PREMISE_SELECTION_MISS,
                failure_detail="synthetic premise-selection miss",
            )
        else:
            output = StageOutput(
                data={"safe_failure_class": "timed_out"},
                status=StageStatus.FAILED,
                failure_code=(
                    FailureCode
                    .LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
                ),
                failure_detail="synthetic model timeout",
            )
        return StageAdapter(
            stage,
            handler=lambda _request, value=output: value,
        )

    return _G240AdapterBundleV2(
        proof_adapters=MappingProxyType(
            {
                stage: (
                    StageAdapter(stage, handler=kernel)
                    if stage is StageName.KERNEL
                    else failed_optional(stage)
                )
                for stage in stages
            }
        ),
        # Synthetic fixtures are deliberately incapable of exercising the
        # production frontend.  The parent runner admits this branch only
        # under its private test capability.
        frontend_routes=None,
    )


def _source_execute_frontend_v2(
    request: G240ExecutionRequestV2,
    bundle: _G240AdapterBundleV2,
) -> tuple[CaseResultRecord, CompilerReferenceExposureV2]:
    """Execute candidate+A0 frontends, except for explicit test fixtures."""

    if bundle.frontend_routes is None:
        return (
            request.typed_semantic_result,
            request.typed_compiler_exposure,
        )
    plan = request.typed_plan
    execution_plan = (
        plan
        if plan.run_id == request.execution_run_id
        else replace(plan, run_id=request.execution_run_id)
    )
    job = request.typed_job
    reference_jobs = tuple(
        candidate
        for candidate in execution_plan.jobs
        if (
            candidate.case_id == job.case_id
            and candidate.cache_mode is job.cache_mode
            and candidate.variant_id == "A0"
        )
    )
    if len(reference_jobs) != 1:
        raise G240SourceExecutorError(
            "production frontend execution requires one exact paired A0 "
            "reference job"
        )
    scheduler = ResourceScheduler(
        ResourcePolicy.from_resource_limits(execution_plan.limits)
    )
    reference_result = _execute_job(
        execution_plan,
        reference_jobs[0],
        bundle.frontend_routes,
        scheduler,
        semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
    )
    candidate_result = (
        reference_result
        if job.variant_id == "A0"
        else _execute_job(
            execution_plan,
            job,
            bundle.frontend_routes,
            scheduler,
            semantic_protocol_cid=SEMANTIC_PROTOCOL_V2_CID,
        )
    )
    semantic_result = CaseResultRecord.from_stages(
        tuple(
            stage
            for stage in candidate_result.stages
            if stage.stage in _FRONTEND_STAGES
        )
    )
    compiler_records = tuple(
        stage
        for stage in reference_result.stages
        if stage.stage is StageName.COMPILER
    )
    if len(compiler_records) != 1:
        raise G240SourceExecutorError(
            "source-executed A0 reference lacks one compiler record"
        )
    try:
        exposure = CompilerReferenceExposureV2.from_compiler_record(
            compiler_records[0],
            source_text=request.source_text,
        )
    except (TypeError, ValueError) as exc:
        raise G240SourceExecutorError(
            "source-executed A0 compiler exposure is invalid"
        ) from exc
    return semantic_result, exposure


_ADAPTER_FACTORIES: Final[Mapping[str, AdapterFactory]] = (
    MappingProxyType(
        {
            G240_LIVE_ADAPTER_FACTORY_ID_V2: _live_adapter_factory,
            G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2: (
                _synthetic_adapter_factory
            ),
        }
    )
)


def validate_g240_execution_request_v2(
    value: object,
) -> G240ExecutionRequestV2:
    """Typed-replay a private execution request and all of its CIDs."""

    try:
        request = (
            value
            if isinstance(value, G240ExecutionRequestV2)
            else G240ExecutionRequestV2.from_dict(value)
        )
    except (TypeError, ValueError) as exc:
        raise G240SourceExecutorError(
            "G240 execution request failed typed replay"
        ) from exc
    return G240ExecutionRequestV2.from_dict(request.to_dict())


def validate_g240_production_execution_request_v2(
    value: object,
) -> G240ExecutionRequestV2:
    """Reject the distinct synthetic-test schema at production gates."""

    request = validate_g240_execution_request_v2(value)
    if (
        request.schema != G240_EXECUTION_REQUEST_SCHEMA_V2
        or request.adapter_factory_id != G240_LIVE_ADAPTER_FACTORY_ID_V2
    ):
        raise G240SourceExecutorError(
            "G240 production validation rejects test-only synthetic "
            "execution"
        )
    return request


def _g240_replay_stage_semantic_projection_v2(
    stage: StageRecord,
    *,
    expected_plan_digest: str,
) -> Mapping[str, object]:
    """Return the stable semantic fields re-execution must reproduce.

    A production replay intentionally has a fresh run id and measurements.
    The ablation-plan digest in ``StageProvenance.source`` is also run-local
    because the replay plan is rebased onto that fresh run id.  Its source
    marker and job identity remain comparison authority.
    """

    provenance = stage.provenance
    source = provenance.source
    if (
        len(source) != 4
        or source[1] != "ablation_plan"
        or source[2] != expected_plan_digest
    ):
        raise G240SourceExecutorError(
            "G240 replay stage has an unsupported provenance source route"
        )
    stable_data = stage.data
    stable_output_sha256 = stage.output_sha256
    stable_effective_identity = provenance.effective_identity
    stable_route_identity: Mapping[str, object] | None = None
    if stage.stage is StageName.SYMAI:
        stable_data = symai_semantic_payload(stage)
        stable_output_sha256 = symai_semantic_payload_sha256(stage)
        stable_effective_identity = symai_backend_identity(stage)
        stable_route_identity = _g240_symai_route_projection_v2(stage)
    projection = {
        "schema": stage.schema,
        "protocol_sha256": stage.protocol_sha256,
        "case_id": stage.case_id,
        "case_manifest_sha256": stage.case_manifest_sha256,
        "variant_id": stage.variant_id,
        "split": stage.split.value,
        "cache_mode": stage.cache_mode.value,
        "stage": stage.stage.value,
        "adapter_version": stage.adapter_version,
        "status": stage.status.value,
        "provenance": {
            "schema": provenance.schema,
            "adapter_id": provenance.adapter_id,
            "adapter_version": provenance.adapter_version,
            "adapter_source": source[0],
            "source_marker": source[1],
            "source_job_id": source[3],
            "requested_identity": provenance.requested_identity,
            "effective_identity": stable_effective_identity,
            "input_sha256": provenance.input_sha256,
            "environment_sha256": provenance.environment_sha256,
        },
        "data": stable_data,
        "output_sha256": stable_output_sha256,
        "failure_code": (
            None
            if stage.failure_code is None
            else stage.failure_code.value
        ),
        "failure_detail": stage.failure_detail,
        "kernel_accepted": stage.kernel_accepted,
        "kernel_receipt_sha256": stage.kernel_receipt_sha256,
    }
    if stable_route_identity is not None:
        projection["symai_route_identity"] = stable_route_identity
    return MappingProxyType(_plain(projection))  # type: ignore[arg-type]


def _g240_symai_route_projection_v2(
    stage: StageRecord,
) -> Mapping[str, object] | None:
    """Retain stable existing-router identity outside cache evidence.

    The bounded adapter metadata has exactly three operational fields:
    ``cache``, ``cache_key``, and ``cached_backend``.  Every other retained
    metadata claim is semantic route identity.  ``repair_failure_class`` is
    intentionally absent because it describes a run-local retry/repair
    attempt and is compared by the separate resource/reliability receipts.
    """

    if not isinstance(stage.data, Mapping):
        return None
    raw_provenance = stage.data.get("backend_provenance")
    if raw_provenance is None:
        if (
            stage.status is StageStatus.SUCCESS
            and stage.data.get("schema") == SYMAI_EVIDENCE_SCHEMA_V2
        ):
            raise G240SourceExecutorError(
                "G240 successful SyMAI semantic evidence lacks stable "
                "backend provenance"
            )
        return None
    provenance = _mapping(
        raw_provenance, "SyMAI replay backend provenance"
    )
    metadata = _mapping(
        provenance.get("router_metadata"),
        "SyMAI replay router metadata",
    )
    stable_router_metadata = {
        key: metadata[key]
        for key in (
            "backend",
            "effective_model_name",
            "effective_provider_name",
            "format",
            "model",
            "provider",
            "resolved_model_name",
            "resolved_provider_name",
            "router_provider",
            "routing_backend",
            "service_endpoint",
        )
        if key in metadata
    }
    projection = {
        "engine": provenance.get("engine"),
        "router": provenance.get("router"),
        "requested_provider": provenance.get("requested_provider"),
        "effective_provider": provenance.get("effective_provider"),
        "requested_model": provenance.get("requested_model"),
        "effective_model": provenance.get("effective_model"),
        "resolved_provider": metadata.get("resolved_provider_name"),
        "resolved_model": metadata.get("resolved_model_name"),
        "service_endpoint": metadata.get("service_endpoint"),
        "routing_backend": metadata.get("routing_backend"),
        "router_metadata": stable_router_metadata,
        "dry_run": provenance.get("dry_run"),
        "starts_model_server": provenance.get("starts_model_server"),
        "reuses_existing_model_service": provenance.get(
            "reuses_existing_model_service"
        ),
    }
    for field in (
        "engine",
        "router",
        "requested_provider",
        "effective_provider",
        "requested_model",
        "effective_model",
    ):
        if (
            not isinstance(projection[field], str)
            or not str(projection[field]).strip()
        ):
            raise G240SourceExecutorError(
                f"G240 SyMAI replay route lacks stable {field}"
            )
    for field in (
        "dry_run",
        "starts_model_server",
        "reuses_existing_model_service",
    ):
        if type(projection[field]) is not bool:
            raise G240SourceExecutorError(
                f"G240 SyMAI replay route lacks stable {field}"
            )
    if projection["dry_run"] is False:
        for field in (
            "resolved_provider",
            "resolved_model",
            "service_endpoint",
            "routing_backend",
        ):
            if (
                not isinstance(projection[field], str)
                or not str(projection[field]).strip()
            ):
                raise G240SourceExecutorError(
                    f"G240 SyMAI replay route lacks stable {field}"
                )
    return MappingProxyType(_plain(projection))  # type: ignore[arg-type]


def _g240_replay_compiler_semantic_projection_v2(
    exposure: CompilerReferenceExposureV2,
    *,
    expected_plan_digest: str,
) -> Mapping[str, object]:
    """Allowlist stable compiler semantics and content identities."""

    data = exposure.to_dict()
    projection = {
        "schema": exposure.schema,
        "semantic_protocol_cid": exposure.semantic_protocol_cid,
        "causal_proof_protocol_cid": (
            exposure.causal_proof_protocol_cid
        ),
        "source_cid": exposure.source_cid,
        "case_id": exposure.compiler_record.case_id,
        "cache_mode": exposure.compiler_record.cache_mode.value,
        "environment_sha256": (
            exposure.compiler_record.provenance.environment_sha256
        ),
        "compiler_invoked": data["compiler_invoked"],
        "candidate_state": data["candidate_state"],
        "compiler_record": _g240_replay_stage_semantic_projection_v2(
            exposure.compiler_record,
            expected_plan_digest=expected_plan_digest,
        ),
        "compiler_artifact": data["compiler_artifact"],
        "compiler_artifact_cid": data["compiler_artifact_cid"],
        "compiler_artifact_sha256": data[
            "compiler_artifact_sha256"
        ],
        "compiler_candidate": data["compiler_candidate"],
    }
    return MappingProxyType(_plain(projection))  # type: ignore[arg-type]


def validate_g240_runtime_for_execution_request_v2(
    value: object,
    request: object,
) -> CausalRuntimeEvidenceV2:
    """Join emitted evidence to every pre-execution semantic coordinate."""

    restored_request = validate_g240_execution_request_v2(request)
    try:
        runtime = (
            value
            if isinstance(value, CausalRuntimeEvidenceV2)
            else validate_causal_runtime_evidence_v2(value)
        )
        runtime = validate_causal_runtime_evidence_v2(runtime.to_dict())
    except (TypeError, ValueError) as exc:
        raise G240SourceExecutorError(
            "G240 executor emitted invalid causal runtime evidence"
        ) from exc
    result = runtime.case_result
    stage_environments = {
        stage.provenance.environment_sha256
        for stage in (*runtime.semantic_frontend, *result.stages)
    }
    source_plan = restored_request.typed_plan
    execution_plan = (
        source_plan
        if source_plan.run_id == restored_request.execution_run_id
        else replace(
            source_plan,
            run_id=restored_request.execution_run_id,
        )
    )
    if (
        restored_request.execution_mode == "replay"
        and restored_request.schema
        == G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2
    ):
        expected_frontend_changed = (
            runtime.compiler_exposure
            != restored_request.typed_compiler_exposure
            or tuple(runtime.semantic_frontend)
            != tuple(restored_request.typed_semantic_result.stages)
        )
    elif restored_request.execution_mode == "replay":
        expected_frontend_changed = (
            _g240_replay_compiler_semantic_projection_v2(
                runtime.compiler_exposure,
                expected_plan_digest=execution_plan.digest,
            )
            != _g240_replay_compiler_semantic_projection_v2(
                restored_request.typed_compiler_exposure,
                expected_plan_digest=source_plan.digest,
            )
            or tuple(
                _g240_replay_stage_semantic_projection_v2(
                    stage,
                    expected_plan_digest=execution_plan.digest,
                )
                for stage in runtime.semantic_frontend
            )
            != tuple(
                _g240_replay_stage_semantic_projection_v2(
                    stage,
                    expected_plan_digest=source_plan.digest,
                )
                for stage in restored_request.typed_semantic_result.stages
            )
        )
    else:
        expected_frontend_changed = (
            restored_request.schema
            == G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2
            and (
            runtime.compiler_exposure.compiler_record
            != restored_request.typed_compiler_exposure.compiler_record
            or tuple(runtime.semantic_frontend)
            != tuple(restored_request.typed_semantic_result.stages)
            )
        )
    mismatches = tuple(
        name
        for name, changed in (
            (
                "run_id",
                result.run_id
                != restored_request.execution_run_id,
            ),
            (
                "case_id",
                result.case_id != restored_request.typed_job.case_id,
            ),
            (
                "case_manifest",
                result.case_manifest_sha256
                != restored_request.typed_plan.case_manifest_sha256,
            ),
            (
                "variant",
                result.variant_id
                != restored_request.typed_job.variant_id,
            ),
            (
                "split",
                result.split is not restored_request.typed_plan.split,
            ),
            (
                "cache_mode",
                result.cache_mode
                is not restored_request.typed_job.cache_mode,
            ),
            (
                "source",
                runtime.source_text != restored_request.source_text,
            ),
            (
                "proof_context",
                runtime.proof_context_cid
                != restored_request.proof_context_cid,
            ),
            ("semantic_frontend", expected_frontend_changed),
            (
                "environment",
                stage_environments
                != {restored_request.environment_sha256},
            ),
        )
        if changed
    )
    if mismatches:
        raise G240SourceExecutorError(
            "G240 runtime evidence differs from its pre-execution request: "
            + ", ".join(mismatches)
        )
    return runtime


def _private_real_directory(path: Path, field: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
    except OSError as exc:
        raise G240SourceExecutorError(
            f"cannot inspect {field}"
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise G240SourceExecutorError(
            f"{field} must be a private real directory"
        )
    return resolved


def _private_regular_file(
    path: Path,
    *,
    parent: Path,
    field: str,
) -> bytes:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
        raw = path.read_bytes()
    except OSError as exc:
        raise G240SourceExecutorError(
            f"cannot read {field}"
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or not resolved.is_relative_to(parent)
        or not raw
        or len(raw) > _MAX_REQUEST_BYTES
    ):
        raise G240SourceExecutorError(
            f"{field} is not a bounded private regular file"
        )
    return raw


def _canonical_request_from_path(
    request_path: Path,
    *,
    state_directory: Path,
) -> tuple[G240ExecutionRequestV2, bytes]:
    raw = _private_regular_file(
        request_path,
        parent=state_directory,
        field="G240 execution request",
    )
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
        )
        request = validate_g240_execution_request_v2(value)
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, G240SourceExecutorError):
            raise
        raise G240SourceExecutorError(
            "G240 execution request is not strict JSON"
        ) from exc
    if (
        not text.endswith("\n")
        or text.endswith("\n\n")
        or raw != canonical_dag_json_bytes(request.to_dict()) + b"\n"
    ):
        raise G240SourceExecutorError(
            "G240 execution request is not canonical newline DAG-JSON"
        )
    return request, raw


def _environment_value(name: str) -> str:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value or "\0" in value:
        raise G240SourceExecutorError(
            f"required G240 environment value is absent: {name}"
        )
    return value


def _environment_mapping(name: str) -> Mapping[str, str]:
    value = _environment_value(name)
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise G240SourceExecutorError(
            f"{name} is not strict JSON"
        ) from exc
    mapping = _mapping(decoded, name)
    if any(
        not isinstance(key, str)
        or not isinstance(member, str)
        or not key
        or not member
        for key, member in mapping.items()
    ):
        raise G240SourceExecutorError(
            f"{name} must map nonempty strings to nonempty strings"
        )
    return MappingProxyType(dict(mapping))  # type: ignore[arg-type]


def _bootstrap_receipt_from_environment(
) -> G240BootstrapConfinementReceiptV2:
    raw = _environment_value("HSSL_G240_BOOTSTRAP_RECEIPT_JSON")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_pairs,
        )
        receipt = validate_g240_bootstrap_confinement_receipt_v2(value)
    except (
        json.JSONDecodeError,
        G240BootstrapContractError,
        TypeError,
        ValueError,
    ) as exc:
        raise G240SourceExecutorError(
            "G240 executor lacks a valid stage-one bootstrap receipt"
        ) from exc
    if (
        raw.encode("utf-8")
        != canonical_dag_json_bytes(receipt.to_dict())
    ):
        raise G240SourceExecutorError(
            "G240 stage-one bootstrap receipt is not canonical DAG-JSON"
        )
    source_commit = _environment_value(
        "HSSL_G240_BOOTSTRAP_SOURCE_COMMIT"
    )
    try:
        expected_source_observation = (
            g240_bootstrap_git_observation_cid(
                _commit(source_commit, "bootstrap source commit"),
                role="source",
            )
        )
    except (G240BootstrapContractError, TypeError, ValueError) as exc:
        raise G240SourceExecutorError(
            "G240 bootstrap source observation is invalid"
        ) from exc
    if (
        receipt.source_commit_observation_cid
        != expected_source_observation
    ):
        raise G240SourceExecutorError(
            "G240 bootstrap source observation changed before stage two"
        )
    package_path = os.environ.get(
        "HSSL_G240_SOURCE_BOUND_IPFS_ACCELERATE_PACKAGE_PATH"
    )
    gitlink_commit = os.environ.get(
        "HSSL_G240_SOURCE_BOUND_IPFS_ACCELERATE_GITLINK_COMMIT"
    )
    if (package_path is None) != (gitlink_commit is None):
        raise G240SourceExecutorError(
            "G240 bootstrap source-bound Git observation is partial"
        )
    if gitlink_commit is None:
        if receipt.source_bound_gitlink_observation_cid is not None:
            raise G240SourceExecutorError(
                "G240 bootstrap omitted its source-bound Git authority"
            )
    else:
        try:
            expected_gitlink_observation = (
                g240_bootstrap_git_observation_cid(
                    _commit(
                        gitlink_commit,
                        "bootstrap source-bound gitlink commit",
                    ),
                    role="ipfs-accelerate-gitlink",
                )
            )
        except (
            G240BootstrapContractError,
            TypeError,
            ValueError,
        ) as exc:
            raise G240SourceExecutorError(
                "G240 bootstrap source-bound Git observation is invalid"
            ) from exc
        if (
            receipt.source_bound_gitlink_observation_cid
            != expected_gitlink_observation
            or not isinstance(package_path, str)
            or not Path(package_path).is_absolute()
        ):
            raise G240SourceExecutorError(
                "G240 bootstrap source-bound Git observation changed"
            )
    return receipt


def _authenticated_regular_payload(
    path: Path,
    *,
    expected_cid: str,
    field: str,
) -> bytes:
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
        payload = path.read_bytes()
    except OSError as exc:
        raise G240SourceExecutorError(
            f"cannot authenticate {field}"
        ) from exc
    if (
        not path.is_absolute()
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or resolved != path
        or not payload
        or cid_for_bytes(payload) != expected_cid
    ):
        raise G240SourceExecutorError(
            f"{field} differs from its pinned raw CID"
        )
    return payload


def _required_runtime_imports(
    inventory: CapabilityInventory,
) -> tuple[str, ...]:
    available = {
        kind
        for kind, record in inventory.by_kind.items()
        if record.status is CapabilityStatus.AVAILABLE
    }
    modules = {
        "benchmarks.logic_pipeline",
        "ipfs_datasets_py.logic.modal.codec",
    }
    if CapabilityKind.SPACY_PIPELINE in available:
        requested_model = inventory.by_kind[
            CapabilityKind.SPACY_PIPELINE
        ].identity.get("requested_model")
        if (
            not isinstance(requested_model, str)
            or not _PYTHON_MODULE.fullmatch(requested_model)
        ):
            raise G240SourceExecutorError(
                "available spaCy pipeline lacks an importable model identity"
            )
        modules.update(
            {
                "spacy",
                requested_model,
                (
                    "ipfs_datasets_py.optimizers.logic_theorem_optimizer."
                    "spacy_modal_codec"
                ),
            }
        )
    if {
        CapabilityKind.SYMAI,
        CapabilityKind.LLM_ROUTER,
        CapabilityKind.LEANSTRAL_SERVICE,
    }.issubset(available):
        modules.update(
            {
                "symai",
                "ipfs_datasets_py.llm_router",
                "ipfs_datasets_py.utils.symai_ipfs_engine",
            }
        )
    if CapabilityKind.HAMMER in available:
        modules.add("ipfs_datasets_py.logic.hammers")
    return tuple(sorted(modules))


def _symai_runtime_model(
    inventory: CapabilityInventory,
) -> str | None:
    available = {
        kind
        for kind, record in inventory.by_kind.items()
        if record.status is CapabilityStatus.AVAILABLE
    }
    if not {
        CapabilityKind.SYMAI,
        CapabilityKind.LLM_ROUTER,
        CapabilityKind.LEANSTRAL_SERVICE,
    }.issubset(available):
        return None
    _provider, model = resolve_symai_runtime_provider_model(inventory)
    return model


def _runtime_import_preflight(
    request: G240ExecutionRequestV2,
    state_directory: Path,
    bootstrap_receipt: G240BootstrapConfinementReceiptV2,
) -> Mapping[str, object]:
    if request.adapter_factory_id != G240_LIVE_ADAPTER_FACTORY_ID_V2:
        return MappingProxyType(
            {
                "schema": _G240_RUNTIME_PREFLIGHT_SCHEMA_V2,
                "request_cid": request.request_cid,
                "bootstrap_confinement_receipt": (
                    bootstrap_receipt.to_dict()
                ),
                "landlock_policy_cid": None,
                "landlock_receipt_cid": None,
                "interpreter_identity_cid": None,
                "git_executable_cid": None,
                "runtime_environment_artifact_cids": {},
                "symai_configuration_cid": None,
                "symai_configuration_relative_path": None,
                "imports": {},
                "synthetic_test_only": True,
            }
        )
    for label, descriptor in (
        request.runtime_environment_artifacts.items()
    ):
        _authenticated_regular_payload(
            Path(descriptor["path"]),
            expected_cid=descriptor["payload_cid"],
            field=f"G240 runtime environment artifact {label}",
        )
    landlock_policy = bootstrap_receipt.typed_landlock_policy
    landlock_receipt = bootstrap_receipt.typed_landlock_receipt
    if landlock_policy is None or landlock_receipt is None:
        raise G240SourceExecutorError(
            "production runtime preflight lacks applied Landlock evidence"
        )
    inventory = CapabilityInventory.from_dict(
        request.adapter_configuration["capability_inventory"]
    )
    symai_configuration_cid: str | None = None
    symai_configuration_relative_path: str | None = None
    symai_model = _symai_runtime_model(inventory)
    if symai_model is not None:
        symai_configuration_relative_path = (
            f"{inventory.run_id}/symai-runtime/"
            ".symai/symai.config.json"
        )
        try:
            symai_configuration_cid = (
                prepare_symai_runtime_configuration(
                    state_directory
                    / inventory.run_id
                    / "symai-runtime",
                    model=symai_model,
                    import_package=True,
                )
            )
        except (Exception, SystemExit) as exc:
            raise G240SourceExecutorError(
                "required state-scoped SyMAI configuration/import failed"
            ) from exc
    imports: dict[str, Mapping[str, object]] = {}
    imported_modules: dict[str, object] = {}
    if (
        inventory.by_kind[CapabilityKind.LEANSTRAL_SERVICE].status
        is CapabilityStatus.AVAILABLE
    ):
        module_name = (
            "ipfs_accelerate_py.agent_supervisor."
            "leanstral_proof_provider"
        )
        try:
            imported_modules[module_name] = (
                import_source_bound_ipfs_accelerate(module_name)
            )
        except (Exception, SystemExit) as exc:
            raise G240SourceExecutorError(
                "required source-bound Leanstral provider import failed"
            ) from exc
    module_names = tuple(
        sorted(
            {
                *_required_runtime_imports(inventory),
                *imported_modules,
            }
        )
    )
    for module_name in module_names:
        try:
            module = imported_modules.get(module_name)
            if module is None:
                module = importlib.import_module(module_name)
            raw_path = getattr(module, "__file__", None)
            version = getattr(module, "__version__", None)
        except (Exception, SystemExit) as exc:
            raise G240SourceExecutorError(
                f"required runtime import failed: {module_name}"
            ) from exc
        if not isinstance(raw_path, str):
            raise G240SourceExecutorError(
                f"required runtime import lacks source bytes: {module_name}"
            )
        module_path = Path(raw_path)
        try:
            payload = module_path.read_bytes()
        except OSError as exc:
            raise G240SourceExecutorError(
                f"cannot authenticate runtime import: {module_name}"
            ) from exc
        if not payload:
            raise G240SourceExecutorError(
                f"runtime import is empty: {module_name}"
            )
        imports[module_name] = MappingProxyType(
            {
                "module_file_cid": cid_for_bytes(payload),
                "version": (
                    None
                    if version is None
                    else str(version)[:128]
                ),
            }
        )
    return MappingProxyType(
        {
            "schema": _G240_RUNTIME_PREFLIGHT_SCHEMA_V2,
            "request_cid": request.request_cid,
            "bootstrap_confinement_receipt": (
                bootstrap_receipt.to_dict()
            ),
            "landlock_policy_cid": landlock_policy.policy_cid,
            "landlock_receipt_cid": landlock_receipt.receipt_cid,
            "interpreter_identity_cid": (
                request.interpreter_identity_cid
            ),
            "git_executable_cid": request.git_executable_cid,
            "runtime_environment_artifact_cids": {
                label: descriptor["payload_cid"]
                for label, descriptor in (
                    request.runtime_environment_artifacts.items()
                )
            },
            "symai_configuration_cid": symai_configuration_cid,
            "symai_configuration_relative_path": (
                symai_configuration_relative_path
            ),
            "imports": imports,
            "synthetic_test_only": False,
        }
    )


def _write_exclusive_canonical_evidence(
    path: Path,
    runtime: CausalRuntimeEvidenceV2,
    *,
    output_directory: Path,
) -> None:
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(output_directory) or path.exists():
        raise G240SourceExecutorError(
            "G240 evidence path escaped or already exists"
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(
                canonical_dag_json_bytes(runtime.to_dict()) + b"\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise G240SourceExecutorError(
            "cannot exclusively write G240 runtime evidence"
        ) from exc


def _write_exclusive_canonical_value(
    path: Path,
    value: object,
    *,
    parent: Path,
    field: str,
) -> bytes:
    resolved = path.resolve(strict=False)
    payload = canonical_dag_json_bytes(_plain(value)) + b"\n"
    if not resolved.is_relative_to(parent) or path.exists():
        raise G240SourceExecutorError(
            f"{field} path escaped or already exists"
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise G240SourceExecutorError(
            f"cannot exclusively write {field}"
        ) from exc
    return payload


def execute_g240_request_from_environment_v2(
    *,
    _bootstrap_capability: object | None = None,
) -> CausalRuntimeEvidenceV2:
    """Execute the exact private request named by the reserved environment."""

    if _bootstrap_capability is not _G240_BOOTSTRAP_STAGE2_CAPABILITY_V2:
        raise G240SourceExecutorError(
            "G240 source executor must be entered by the tracked bootstrap"
        )
    bootstrap_receipt = _bootstrap_receipt_from_environment()
    state_directory = _private_real_directory(
        Path(_environment_value("HSSL_G240_STATE_DIR")),
        "G240 state directory",
    )
    output_directory = _private_real_directory(
        Path(_environment_value("HSSL_G240_OUTPUT_DIR")),
        "G240 output directory",
    )
    request_path = Path(
        _environment_value("HSSL_G240_EXECUTION_REQUEST_PATH")
    )
    evidence_path = Path(_environment_value("HSSL_G240_EVIDENCE_PATH"))
    request, _request_payload = _canonical_request_from_path(
        request_path,
        state_directory=state_directory,
    )
    expected_request_cid = _cid(
        _environment_value("HSSL_G240_EXECUTION_REQUEST_CID"),
        "HSSL_G240_EXECUTION_REQUEST_CID",
    )
    git_executable_cid = _cid(
        _environment_value("HSSL_G240_GIT_EXECUTABLE_CID"),
        "HSSL_G240_GIT_EXECUTABLE_CID",
        codec="raw",
    )
    cache_paths = _environment_mapping("HSSL_G240_CACHE_ROOTS_JSON")
    cache_cids = _environment_mapping(
        "HSSL_G240_CACHE_NAMESPACE_CIDS_JSON"
    )
    for stage, path_value in cache_paths.items():
        _private_real_directory(
            Path(path_value), f"G240 {stage} cache directory"
        )
    environment_joins = {
        "HSSL_G240_RUN_ID": request.execution_run_id,
        "HSSL_G240_PLAN_CID": request.plan_cid,
        "HSSL_G240_JOB_ID": request.typed_job.job_id,
        "HSSL_G240_COORDINATE_CID": request.coordinate_cid,
        "HSSL_G240_PROCESS_NAMESPACE_CID": (
            request.process_namespace_cid
        ),
        "HSSL_G240_STATE_NAMESPACE_CID": request.state_namespace_cid,
        "HSSL_G240_OUTPUT_NAMESPACE_CID": (
            request.output_namespace_cid
        ),
        "HSSL_G240_ENVIRONMENT_CID": request.environment_cid,
        "HSSL_G240_ENVIRONMENT_SHA256": request.environment_sha256,
    }
    mismatches = sorted(
        name
        for name, expected in environment_joins.items()
        if _environment_value(name) != expected
    )
    if (
        mismatches
        or request.request_cid != expected_request_cid
        or dict(cache_cids) != dict(request.cache_namespace_cids)
        or set(cache_paths) != set(request.cache_namespace_cids)
        or (
            request.adapter_factory_id
            == G240_LIVE_ADAPTER_FACTORY_ID_V2
            and request.git_executable_cid != git_executable_cid
        )
        or _environment_value("HSSL_G240_BOOTSTRAP_SOURCE_COMMIT")
        != request.source_commit
        or bootstrap_receipt.synthetic_test_only
        is not (
            request.adapter_factory_id
            == G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2
        )
    ):
        raise G240SourceExecutorError(
            "G240 launch environment differs from its pre-frozen request"
            + (f": {', '.join(mismatches)}" if mismatches else "")
        )
    factory = _ADAPTER_FACTORIES.get(request.adapter_factory_id)
    if factory is None:  # pragma: no cover - request constructor guards this
        raise G240SourceExecutorError(
            "G240 adapter factory is not registered"
        )
    if request.adapter_factory_id == G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2:
        if (
            os.environ.get(
                _G240_SYNTHETIC_TEST_ENVIRONMENT_KEY_V2
            )
            != request.request_cid
        ):
            raise G240SourceExecutorError(
                "synthetic G240 adapters require the explicit private "
                "test-only execution capability"
            )
    elif _G240_SYNTHETIC_TEST_ENVIRONMENT_KEY_V2 in os.environ:
        raise G240SourceExecutorError(
            "test-only synthetic authority cannot accompany a live adapter"
        )
    preflight = _runtime_import_preflight(
        request,
        state_directory,
        bootstrap_receipt,
    )
    _write_exclusive_canonical_value(
        state_directory / G240_RUNTIME_PREFLIGHT_FILE_V2,
        preflight,
        parent=state_directory,
        field="G240 runtime import preflight",
    )
    bundle = factory(request, state_directory)
    semantic_result, compiler_exposure = _source_execute_frontend_v2(
        request,
        bundle,
    )
    runtime = execute_causal_runtime_case_v2(
        semantic_result,
        request.source_text,
        request.proof_context,
        compiler_exposure,
        bundle.proof_adapters,
    )
    runtime = validate_g240_runtime_for_execution_request_v2(
        runtime, request
    )
    _write_exclusive_canonical_evidence(
        evidence_path,
        runtime,
        output_directory=output_directory,
    )
    return runtime


def main(*, _bootstrap_capability: object | None = None) -> int:
    """Run the repository-pinned executor without accepting caller argv."""

    if _bootstrap_capability is not _G240_BOOTSTRAP_STAGE2_CAPABILITY_V2:
        raise G240SourceExecutorError(
            "G240 source executor must be entered by the tracked bootstrap"
        )
    if len(sys.argv) != 1:
        raise G240SourceExecutorError(
            "G240 source executor accepts no command-line arguments"
        )
    execute_g240_request_from_environment_v2(
        _bootstrap_capability=_bootstrap_capability
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by subprocess tests
    raise SystemExit(main())


__all__ = [
    "G240_EXECUTION_REQUEST_FILE_V2",
    "G240_EXECUTION_REQUEST_SCHEMA_V2",
    "G240_LIVE_ADAPTER_FACTORY_ID_V2",
    "G240_LIVE_ADAPTER_FACTORY_SCHEMA_V2",
    "G240_RUNTIME_PREFLIGHT_FILE_V2",
    "G240_SYNTHETIC_TEST_EXECUTION_REQUEST_SCHEMA_V2",
    "G240_TRACKED_SOURCE_EXECUTOR_COMMAND_V2",
    "G240_TRACKED_SOURCE_EXECUTOR_MODULE_V2",
    "G240ExecutionRequestV2",
    "G240SourceExecutorError",
    "build_g240_live_adapter_configuration_v2",
    "execute_g240_request_from_environment_v2",
    "validate_g240_execution_request_v2",
    "validate_g240_production_execution_request_v2",
    "validate_g240_runtime_for_execution_request_v2",
]
