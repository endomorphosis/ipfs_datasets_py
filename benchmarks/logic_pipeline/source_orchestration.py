"""Live, source-recomputed execution authority for HSSL-G240.

``namespace_provenance`` freezes the logical namespace preimages used by a
benchmark run.  This module supplies the missing operating-system boundary:
it validates a clean detached checkout, materializes private physical
namespaces, launches exactly one scheduled job in a bounded process group,
and accepts only canonical ``CausalRuntimeEvidenceV2`` bytes.

Public records contain CIDs and benchmark coordinate identifiers only.
Filesystem paths, command arguments, process output, and caller-provided
environment values remain in a deliberately non-serializable validation
bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
from types import MappingProxyType
from typing import Final, Mapping, Self, Sequence

from .ablation import AblationPlan, ScheduledCase
from .capabilities import (
    BoundedProcessResult,
    CapabilityInventory,
    WorktreeSafetyReceipt,
    run_bounded_process_group,
)
from .causal_runtime import (
    CausalRuntimeEvidenceV2,
    validate_causal_runtime_evidence_v2,
)
from .content_addressing import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_dag_json,
    validate_cid,
)
from .namespace_provenance import (
    G240JobNamespacePlanV2,
    G240NamespacePolicyV2,
    G240RuntimeNamespaceEvidenceSetV2,
    G240RuntimeNamespaceReceiptV2,
    RuntimeNamespaceProvenanceError,
    g240_cache_namespace_set_cid,
    g240_recursive_gitlinks_cid,
    g240_worktree_safety_projection_cid,
    validate_g240_runtime_namespace_evidence_set_v2,
    validate_g240_runtime_namespace_receipt_v2,
)
from .runtime import symai_runtime_configuration_cid
from .runtime_confinement import (
    G240LandlockConfinementError,
    G240LandlockPolicyV1,
    G240LandlockPrivatePolicySourcesV1,
    G240LandlockReceiptV1,
    build_g240_landlock_policy_v1,
    validate_g240_landlock_receipt_v1,
)
from .source_bootstrap_contract import (
    G240_APPROVED_TCP_DESTINATION_PORTS_V2,
    G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2,
    G240BootstrapConfinementReceiptV2,
    G240BootstrapContractError,
    g240_bootstrap_git_observation_cid,
    g240_private_landlock_policy_payload_v2,
    validate_g240_bootstrap_confinement_receipt_v2,
)
from .source_executor import (
    G240_EXECUTION_REQUEST_FILE_V2,
    G240_RUNTIME_PREFLIGHT_FILE_V2,
    G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2,
    G240_TRACKED_SOURCE_EXECUTOR_COMMAND_V2,
    G240ExecutionRequestV2,
    G240SourceExecutorError,
    _G240_SYNTHETIC_TEST_CAPABILITY_V2,
    _G240_SYNTHETIC_TEST_ENVIRONMENT_KEY_V2,
    _symai_runtime_model,
    validate_g240_execution_request_v2,
    validate_g240_runtime_for_execution_request_v2,
)


G240_SOURCE_COMMAND_PROJECTION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "source-runtime-command-projection.v2"
)
G240_SOURCE_EXECUTOR_CONTRACT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "source-runtime-executor-contract.v2"
)
G240_SOURCE_RUNTIME_ENVIRONMENT_PROJECTION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "source-runtime-environment-projection.v2"
)
G240_SOURCE_PHYSICAL_NAMESPACE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "source-runtime-physical-namespace.v2"
)
G240_SOURCE_CACHE_MARKER_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "source-runtime-cache-marker.v2"
)
G240_SOURCE_ORCHESTRATION_RECEIPT_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "source-runtime-orchestration-receipt.v2"
)
G240_SOURCE_ORCHESTRATION_EVIDENCE_SET_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "source-runtime-orchestration-evidence-set.v2"
)
G240_GIT_COMMIT_IDENTITY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.git-commit-identity.v2"
)
G240_INTERPRETER_IDENTITY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "python-interpreter-identity.v2"
)

_CACHE_MARKER_NAME: Final = ".g240-cache-namespace.json"
_EVIDENCE_NAME: Final = "causal-runtime-evidence.json"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_HEX_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PYTHON_MODULE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z"
)
_PYTHON_MODULE_ARTIFACT_PREFIX: Final = "python-module."
_ENTRYPOINT_KINDS: Final = frozenset(
    {"python-module", "repository-script", "installed-cli"}
)
_INLINE_EXECUTION_ARGUMENTS: Final = frozenset(
    {"-c", "-e", "--eval", "--execute"}
)
_RESERVED_ENVIRONMENT: Final = frozenset(
    {
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_COUNT",
        "GIT_OPTIONAL_LOCKS",
        "GIT_TERMINAL_PROMPT",
        "LC_ALL",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "HSSL_G240_RUN_ID",
        "HSSL_G240_PLAN_CID",
        "HSSL_G240_JOB_ID",
        "HSSL_G240_COORDINATE_CID",
        "HSSL_G240_PROCESS_NAMESPACE_CID",
        "HSSL_G240_STATE_DIR",
        "HSSL_G240_STATE_NAMESPACE_CID",
        "HSSL_G240_OUTPUT_DIR",
        "HSSL_G240_OUTPUT_NAMESPACE_CID",
        "HSSL_G240_EVIDENCE_PATH",
        "HSSL_G240_EXECUTION_REQUEST_PATH",
        "HSSL_G240_EXECUTION_REQUEST_CID",
        "HSSL_G240_ENVIRONMENT_CID",
        "HSSL_G240_ENVIRONMENT_SHA256",
        "HSSL_G240_CACHE_ROOTS_JSON",
        "HSSL_G240_CACHE_NAMESPACE_CIDS_JSON",
        "HSSL_G240_GIT_EXECUTABLE_PATH",
        "HSSL_G240_GIT_EXECUTABLE_CID",
        "HSSL_G240_CONFINEMENT_PROFILE_CID",
        "HSSL_G240_LANDLOCK_RECEIPT_FD",
        "HSSL_G240_EXPECTED_SOURCE_COMMIT",
        "HSSL_G240_BOOTSTRAP_RECEIPT_JSON",
        "HSSL_G240_BOOTSTRAP_SOURCE_COMMIT",
        "HSSL_G240_SOURCE_BOUND_IPFS_ACCELERATE_PACKAGE_PATH",
        "HSSL_G240_SOURCE_BOUND_IPFS_ACCELERATE_GITLINK_COMMIT",
    }
)


class SourceRuntimeOrchestrationError(ValueError):
    """Raised when live G240 source execution cannot be authenticated."""


def HSSLEV2405D72() -> str:
    """Return AST-verifiable evidence for the bounded G240 implementation."""

    return (
        "fail-closed source-bound runtime namespaces, confined execution, "
        "and detached replay"
    )


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise SourceRuntimeOrchestrationError(
                "G240 source DAG-JSON objects require string keys"
            )
        return {
            str(key): _plain(member)
            for key, member in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_plain(member) for member in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise SourceRuntimeOrchestrationError(
        "G240 source value is not DAG-JSON: "
        f"{type(value).__name__}"
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise SourceRuntimeOrchestrationError(
            f"{field} must be an object with string keys"
        )
    return value


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise SourceRuntimeOrchestrationError(
            f"{field} fields changed: "
            f"missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _cid(value: object, field: str) -> str:
    try:
        return validate_cid(value)
    except (TypeError, ValueError) as exc:
        raise SourceRuntimeOrchestrationError(
            f"{field} must be a canonical CIDv1/base32/sha2-256 value"
        ) from exc


def _safe_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_ID.fullmatch(value)
        or value in {".", ".."}
    ):
        raise SourceRuntimeOrchestrationError(
            f"{field} must be a safe nonempty identifier"
        )
    return value


def _plan_cid(plan: AblationPlan) -> str:
    if not isinstance(plan, AblationPlan):
        raise SourceRuntimeOrchestrationError(
            "G240 source execution requires a typed AblationPlan"
        )
    return cid_for_dag_json(_plain(plan.to_dict()))


def g240_source_git_commit_cid(commit: str) -> str:
    """Address a Git object ID without treating its bare digest as a CID."""

    if not isinstance(commit, str) or not _HEX_COMMIT.fullmatch(commit):
        raise SourceRuntimeOrchestrationError(
            "source commit must be a full lowercase Git object ID"
        )
    return cid_for_dag_json(
        {
            "schema": G240_GIT_COMMIT_IDENTITY_SCHEMA_V2,
            "object_format": "sha1" if len(commit) == 40 else "sha256",
            "object_type": "commit",
            "oid": commit,
        }
    )


def _command_cid(command: Sequence[str]) -> str:
    arguments = tuple(command)
    if not arguments or any(
        not isinstance(item, str) or not item or "\0" in item
        for item in arguments
    ):
        raise SourceRuntimeOrchestrationError(
            "source command must be nonempty NUL-free argv strings"
        )
    return cid_for_dag_json(
        {
            "schema": G240_SOURCE_COMMAND_PROJECTION_SCHEMA_V2,
            "argv": list(arguments),
        }
    )


_INTERPRETER_PROBE = (
    "import json,site,sys;"
    "print(json.dumps({"
    "'implementation':sys.implementation.name,"
    "'cache_tag':sys.implementation.cache_tag,"
    "'hexversion':sys.hexversion,"
    "'version':list(sys.version_info),"
    "'prefix':sys.prefix,"
    "'base_prefix':sys.base_prefix,"
    "'site_packages':site.getsitepackages()"
    "},sort_keys=True,separators=(',',':')))"
)


def _interpreter_identity_v2(
    executable_path: str | Path | None = None,
) -> tuple[Path, str]:
    """Resolve and content-address one exact Python runtime environment."""

    try:
        requested = Path(
            sys.executable if executable_path is None else executable_path
        )
        if not requested.is_absolute():
            raise OSError("interpreter path is not absolute")
        launcher = requested.parent.resolve(strict=True) / requested.name
        launcher_metadata = launcher.lstat()
        executable = launcher.resolve(strict=True)
        metadata = executable.lstat()
        payload = executable.read_bytes()
        launcher_target = (
            os.readlink(launcher)
            if stat.S_ISLNK(launcher_metadata.st_mode)
            else None
        )
    except OSError as exc:
        raise SourceRuntimeOrchestrationError(
            "cannot authenticate the current Python interpreter"
        ) from exc
    if (
        not launcher.is_absolute()
        or not (
            stat.S_ISLNK(launcher_metadata.st_mode)
            or stat.S_ISREG(launcher_metadata.st_mode)
        )
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not payload
    ):
        raise SourceRuntimeOrchestrationError(
            "current Python interpreter is not an immutable regular "
            "executable"
        )
    try:
        probe = subprocess.run(
            [launcher.as_posix(), "-I", "-c", _INTERPRETER_PROBE],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            env={
                "PATH": os.defpath,
                "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "PYTHONSAFEPATH": "1",
            },
        )
        runtime = json.loads(probe.stdout)
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        raise SourceRuntimeOrchestrationError(
            "cannot probe the pinned Python runtime environment"
        ) from exc
    if (
        not isinstance(runtime, Mapping)
        or set(runtime)
        != {
            "implementation",
            "cache_tag",
            "hexversion",
            "version",
            "prefix",
            "base_prefix",
            "site_packages",
        }
        or not isinstance(runtime["prefix"], str)
        or not Path(runtime["prefix"]).is_absolute()
        or not isinstance(runtime["base_prefix"], str)
        or not Path(runtime["base_prefix"]).is_absolute()
        or not isinstance(runtime["site_packages"], list)
        or not all(
            isinstance(value, str) and Path(value).is_absolute()
            for value in runtime["site_packages"]
        )
    ):
        raise SourceRuntimeOrchestrationError(
            "pinned Python runtime probe returned an invalid identity"
        )
    identity = {
        "schema": G240_INTERPRETER_IDENTITY_SCHEMA_V2,
        "launcher_path": launcher.as_posix(),
        "launcher_kind": (
            "symlink"
            if stat.S_ISLNK(launcher_metadata.st_mode)
            else "regular"
        ),
        "launcher_symlink_target": launcher_target,
        "resolved_executable_path": executable.as_posix(),
        "executable_cid": cid_for_bytes(payload),
        "runtime": _plain(runtime),
    }
    return launcher, cid_for_dag_json(identity)


def _git_executable_identity_v2(
    executable_path: str | Path | None = None,
) -> tuple[Path, str]:
    """Resolve and content-address the Git binary used by G240."""

    candidate = (
        shutil.which("git", path=os.defpath)
        if executable_path is None
        else str(executable_path)
    )
    if not candidate:
        raise SourceRuntimeOrchestrationError(
            "cannot resolve a pinned Git executable"
        )
    try:
        requested = Path(candidate)
        if not requested.is_absolute():
            raise OSError("Git path is not absolute")
        executable = requested.resolve(strict=True)
        metadata = executable.lstat()
        payload = executable.read_bytes()
    except OSError as exc:
        raise SourceRuntimeOrchestrationError(
            "cannot authenticate the pinned Git executable"
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not payload
    ):
        raise SourceRuntimeOrchestrationError(
            "pinned Git executable is not an immutable regular file"
        )
    return executable, cid_for_bytes(payload)


def _g240_launch_arguments(
    contract: "G240SourceExecutorContractV2",
) -> tuple[str, ...]:
    """Translate the public path-free command into one verified executable."""

    executable, interpreter_cid = _interpreter_identity_v2(
        contract.interpreter_path
    )
    if contract.interpreter_identity_cid != interpreter_cid:
        raise SourceRuntimeOrchestrationError(
            "pinned Python interpreter differs from the frozen executor "
            "identity"
        )
    return (
        executable.as_posix(),
        *contract.command_template[1:],
    )


def _normalize_command_template(
    command_template: Sequence[str],
    *,
    entrypoint_kind: str,
) -> tuple[str, ...]:
    command = tuple(command_template)
    _command_cid(command)
    if entrypoint_kind not in _ENTRYPOINT_KINDS:
        raise SourceRuntimeOrchestrationError(
            "unsupported G240 source executor entrypoint kind"
        )
    if (
        not _SAFE_ID.fullmatch(command[0])
        or command[0] in {".", ".."}
        or any(
            item in _INLINE_EXECUTION_ARGUMENTS
            for item in command[1:]
        )
    ):
        raise SourceRuntimeOrchestrationError(
            "source executor must use a path-free non-inline executable"
        )
    if entrypoint_kind == "python-module":
        if (
            len(command) != 3
            or command[1] != "-m"
            or not _PYTHON_MODULE.fullmatch(command[2])
        ):
            raise SourceRuntimeOrchestrationError(
                "python-module executor must be '<python> -m <module>'"
            )
    elif entrypoint_kind == "repository-script":
        if len(command) != 2:
            raise SourceRuntimeOrchestrationError(
                "repository-script executor accepts no argv payload"
            )
        path = Path(command[1])
        if (
            path.is_absolute()
            or path.as_posix() != command[1]
            or ".." in path.parts
            or path.suffix != ".py"
            or any(part in {"", "."} for part in path.parts)
        ):
            raise SourceRuntimeOrchestrationError(
                "repository executor must be a normalized relative .py path"
            )
    elif len(command) != 1:
        raise SourceRuntimeOrchestrationError(
            "installed-cli executor accepts no argv payload"
        )
    return command


def _runtime_environment_artifacts(
    value: Mapping[str, object] | None,
    *,
    paths_are_inputs: bool,
) -> Mapping[str, Mapping[str, str]]:
    """Validate exact lock/receipt files used by the pinned interpreter."""

    raw = {} if value is None else _mapping(
        value, "runtime_environment_artifacts"
    )
    artifacts: dict[str, Mapping[str, str]] = {}
    for label in sorted(raw):
        _safe_id(label, "runtime environment artifact label")
        if label.startswith(_PYTHON_MODULE_ARTIFACT_PREFIX):
            module_name = label.removeprefix(
                _PYTHON_MODULE_ARTIFACT_PREFIX
            )
            if not _PYTHON_MODULE.fullmatch(module_name):
                raise SourceRuntimeOrchestrationError(
                    "Python-module runtime artifact label must end in a "
                    "canonical import name"
                )
        member = raw[label]
        if paths_are_inputs:
            try:
                path = Path(member)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise SourceRuntimeOrchestrationError(
                    "runtime environment artifact paths are invalid"
                ) from exc
            expected_cid: str | None = None
        else:
            descriptor = _mapping(
                member, f"runtime_environment_artifacts.{label}"
            )
            _exact(
                descriptor,
                {"path", "payload_cid"},
                f"runtime_environment_artifacts.{label}",
            )
            try:
                path = Path(descriptor["path"])  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise SourceRuntimeOrchestrationError(
                    "runtime environment artifact path is invalid"
                ) from exc
            expected_cid = _cid(
                descriptor["payload_cid"],
                f"runtime_environment_artifacts.{label}.payload_cid",
            )
        if not path.is_absolute():
            raise SourceRuntimeOrchestrationError(
                "runtime environment artifact paths must be absolute"
            )
        try:
            metadata = path.lstat()
            resolved = path.resolve(strict=True)
            payload = path.read_bytes()
        except OSError as exc:
            raise SourceRuntimeOrchestrationError(
                "cannot authenticate runtime environment artifact"
            ) from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or not payload
        ):
            raise SourceRuntimeOrchestrationError(
                "runtime environment artifacts must be immutable regular files"
            )
        observed_cid = cid_for_bytes(payload)
        if expected_cid is not None and expected_cid != observed_cid:
            raise SourceRuntimeOrchestrationError(
                "runtime environment artifact bytes changed"
            )
        artifacts[label] = MappingProxyType(
            {
                "path": resolved.as_posix(),
                "payload_cid": observed_cid,
            }
        )
    return MappingProxyType(artifacts)


@dataclass(frozen=True, slots=True)
class G240SourceExecutorContractV2:
    """Frozen path-safe source executor selected before any outcome."""

    entrypoint_kind: str
    command_template: tuple[str, ...]
    command_template_cid: str
    environment_cid: str
    environment_sha256: str
    interpreter_path: str
    interpreter_identity_cid: str
    git_executable_path: str
    git_executable_cid: str
    runtime_environment_artifacts: Mapping[
        str, Mapping[str, str]
    ]
    executor_identity_cid: str
    confinement_profile_cid: str
    shell: bool
    new_process_session: bool
    close_fds_required: bool
    production_landlock_required: bool
    canonical_runtime_evidence_required: bool
    holdout_permitted: bool
    schema: str = G240_SOURCE_EXECUTOR_CONTRACT_SCHEMA_V2
    contract_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G240_SOURCE_EXECUTOR_CONTRACT_SCHEMA_V2:
            raise SourceRuntimeOrchestrationError(
                "unsupported G240 source executor-contract schema"
            )
        command = _normalize_command_template(
            self.command_template,
            entrypoint_kind=self.entrypoint_kind,
        )
        object.__setattr__(self, "command_template", command)
        expected_command = _command_cid(command)
        if (
            _cid(self.command_template_cid, "command_template_cid")
            != expected_command
        ):
            raise SourceRuntimeOrchestrationError(
                "source command-template CID changed"
            )
        object.__setattr__(
            self,
            "command_template_cid",
            expected_command,
        )
        for field in (
            "environment_cid",
            "interpreter_identity_cid",
            "git_executable_cid",
            "executor_identity_cid",
            "confinement_profile_cid",
        ):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        interpreter, interpreter_cid = _interpreter_identity_v2(
            self.interpreter_path
        )
        if interpreter_cid != self.interpreter_identity_cid:
            raise SourceRuntimeOrchestrationError(
                "pinned Python interpreter identity changed"
            )
        object.__setattr__(
            self, "interpreter_path", interpreter.as_posix()
        )
        git_executable, git_cid = _git_executable_identity_v2(
            self.git_executable_path
        )
        if git_cid != self.git_executable_cid:
            raise SourceRuntimeOrchestrationError(
                "pinned Git executable identity changed"
            )
        object.__setattr__(
            self, "git_executable_path", git_executable.as_posix()
        )
        object.__setattr__(
            self,
            "runtime_environment_artifacts",
            _runtime_environment_artifacts(
                self.runtime_environment_artifacts,
                paths_are_inputs=False,
            ),
        )
        if (
            self.confinement_profile_cid
            != G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
        ):
            raise SourceRuntimeOrchestrationError(
                "source executor confinement profile changed"
            )
        if (
            not isinstance(self.environment_sha256, str)
            or not _SHA256.fullmatch(self.environment_sha256)
        ):
            raise SourceRuntimeOrchestrationError(
                "source executor environment SHA-256 must be pinned"
            )
        for field in (
            "shell",
            "new_process_session",
            "close_fds_required",
            "production_landlock_required",
            "canonical_runtime_evidence_required",
            "holdout_permitted",
        ):
            if type(getattr(self, field)) is not bool:
                raise SourceRuntimeOrchestrationError(
                    f"{field} must be boolean"
                )
        if (
            self.shell
            or not self.new_process_session
            or not self.close_fds_required
            or not self.production_landlock_required
            or not self.canonical_runtime_evidence_required
            or self.holdout_permitted
        ):
            raise SourceRuntimeOrchestrationError(
                "source executor must be shell-free, session-isolated, "
                "canonical, and non-holdout"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.contract_cid is None:
            object.__setattr__(self, "contract_cid", expected)
        elif _cid(self.contract_cid, "contract_cid") != expected:
            raise SourceRuntimeOrchestrationError(
                "source executor-contract CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "entrypoint_kind": self.entrypoint_kind,
            "command_template": list(self.command_template),
            "command_template_cid": self.command_template_cid,
            "environment_cid": self.environment_cid,
            "environment_sha256": self.environment_sha256,
            "interpreter_path": self.interpreter_path,
            "interpreter_identity_cid": self.interpreter_identity_cid,
            "git_executable_path": self.git_executable_path,
            "git_executable_cid": self.git_executable_cid,
            "runtime_environment_artifacts": {
                label: dict(descriptor)
                for label, descriptor in (
                    self.runtime_environment_artifacts.items()
                )
            },
            "executor_identity_cid": self.executor_identity_cid,
            "confinement_profile_cid": self.confinement_profile_cid,
            "shell": self.shell,
            "new_process_session": self.new_process_session,
            "close_fds_required": self.close_fds_required,
            "production_landlock_required": (
                self.production_landlock_required
            ),
            "canonical_runtime_evidence_required": (
                self.canonical_runtime_evidence_required
            ),
            "holdout_permitted": self.holdout_permitted,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "contract_cid": self.contract_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G240 source executor contract")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G240 source executor contract",
        )
        raw_command = data["command_template"]
        if not isinstance(raw_command, list):
            raise SourceRuntimeOrchestrationError(
                "source command template must be an array"
            )
        return cls(
            **{
                **data,
                "command_template": tuple(raw_command),
                "runtime_environment_artifacts": _mapping(
                    data["runtime_environment_artifacts"],
                    "runtime_environment_artifacts",
                ),
            }
        )  # type: ignore[arg-type]


def build_g240_source_executor_contract_v2(
    command_template: Sequence[str],
    *,
    entrypoint_kind: str,
    environment_cid: str,
    environment_sha256: str,
    executor_identity_cid: str,
    interpreter_path: str | Path | None = None,
    git_executable_path: str | Path | None = None,
    runtime_environment_artifacts: (
        Mapping[str, str | Path] | None
    ) = None,
) -> G240SourceExecutorContractV2:
    """Freeze an exact non-inline executor before the namespace policy."""

    # Migrate callers from the pre-confinement direct executor spelling.  The
    # resulting frozen contract always names the tracked direct-script
    # bootstrap, so no accepted launch can retain the old authority boundary.
    if (
        tuple(command_template)
        == (
            "python",
            "-m",
            "benchmarks.logic_pipeline.source_executor",
        )
        and entrypoint_kind == "python-module"
    ):
        command_template = G240_TRACKED_SOURCE_EXECUTOR_COMMAND_V2
        entrypoint_kind = "repository-script"
    command = _normalize_command_template(
        command_template,
        entrypoint_kind=entrypoint_kind,
    )
    interpreter, interpreter_identity_cid = (
        _interpreter_identity_v2(interpreter_path)
    )
    git_executable, git_executable_cid = (
        _git_executable_identity_v2(git_executable_path)
    )
    artifacts = _runtime_environment_artifacts(
        runtime_environment_artifacts,  # type: ignore[arg-type]
        paths_are_inputs=True,
    )
    return G240SourceExecutorContractV2(
        entrypoint_kind=entrypoint_kind,
        command_template=command,
        command_template_cid=_command_cid(command),
        environment_cid=environment_cid,
        environment_sha256=environment_sha256,
        interpreter_path=interpreter.as_posix(),
        interpreter_identity_cid=interpreter_identity_cid,
        git_executable_path=git_executable.as_posix(),
        git_executable_cid=git_executable_cid,
        runtime_environment_artifacts=artifacts,
        executor_identity_cid=executor_identity_cid,
        confinement_profile_cid=(
            G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
        ),
        shell=False,
        new_process_session=True,
        close_fds_required=True,
        production_landlock_required=True,
        canonical_runtime_evidence_required=True,
        holdout_permitted=False,
    )


def _paths_overlap(left: Path, right: Path) -> bool:
    return (
        left == right
        or left in right.parents
        or right in left.parents
    )


def _validate_private_directory(path: Path, field: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SourceRuntimeOrchestrationError(
            f"cannot inspect {field}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise SourceRuntimeOrchestrationError(
            f"{field} must be a real directory"
        )
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise SourceRuntimeOrchestrationError(
            f"{field} must be private to the executing user"
        )


def _validate_regular_private_file(path: Path, field: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SourceRuntimeOrchestrationError(
            f"cannot inspect {field}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SourceRuntimeOrchestrationError(
            f"{field} must be a regular non-symlink file"
        )


def _validate_namespace_root(
    namespace_root: str | Path,
    worktree: WorktreeSafetyReceipt,
) -> Path:
    try:
        requested = Path(namespace_root)
    except (TypeError, ValueError) as exc:
        raise SourceRuntimeOrchestrationError(
            "namespace_root must be a filesystem path"
        ) from exc
    if not requested.is_absolute():
        raise SourceRuntimeOrchestrationError(
            "namespace_root must be absolute"
        )
    resolved = requested.resolve(strict=False)
    state_root = worktree.state_root.resolve()
    source = worktree.source_checkout.resolve()
    git_common = worktree.source_git_common_dir.resolve()
    checkout = worktree.worktree_root.resolve()
    if (
        resolved == state_root
        or not resolved.is_relative_to(state_root)
        or _paths_overlap(resolved, source)
        or _paths_overlap(resolved, git_common)
        or _paths_overlap(resolved, checkout)
    ):
        raise SourceRuntimeOrchestrationError(
            "namespace_root must be a dedicated path below the run state "
            "root and outside every Git checkout"
        )
    current = state_root
    _validate_private_directory(current, "worktree state root")
    for part in resolved.relative_to(state_root).parts:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SourceRuntimeOrchestrationError(
                "cannot inspect namespace_root components"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise SourceRuntimeOrchestrationError(
                "namespace_root must not cross symlinks"
            )
        if not stat.S_ISDIR(metadata.st_mode):
            raise SourceRuntimeOrchestrationError(
                "namespace_root components must be directories"
            )
    return resolved


def _ensure_private_directory(path: Path) -> bool:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        _validate_private_directory(path, "physical namespace directory")
        return False
    except OSError as exc:
        raise SourceRuntimeOrchestrationError(
            "cannot create physical namespace directory"
        ) from exc
    _validate_private_directory(path, "physical namespace directory")
    return True


def _ensure_private_parents(root: Path, path: Path) -> None:
    if not path.is_relative_to(root):
        raise SourceRuntimeOrchestrationError(
            "physical namespace escaped namespace_root"
        )
    current = root
    if not current.exists():
        parent = current.parent
        _validate_private_directory(
            parent, "physical namespace parent"
        )
        _ensure_private_directory(current)
    else:
        _validate_private_directory(current, "namespace_root")
    for part in path.relative_to(root).parts:
        current /= part
        _ensure_private_directory(current)


def _create_exclusive_private_directory(path: Path) -> None:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError as exc:
        raise SourceRuntimeOrchestrationError(
            "one-shot physical namespace already exists"
        ) from exc
    except OSError as exc:
        raise SourceRuntimeOrchestrationError(
            "cannot create one-shot physical namespace"
        ) from exc
    _validate_private_directory(path, "one-shot physical namespace")


def _reject_duplicate_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceRuntimeOrchestrationError(
                f"duplicate JSON key: {key}"
            )
        result[key] = value
    return result


def _read_canonical_json(path: Path, field: str) -> tuple[object, bytes]:
    _validate_regular_private_file(path, field)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SourceRuntimeOrchestrationError(
            f"cannot read {field}"
        ) from exc
    if not raw or len(raw) > 64 * 1024 * 1024:
        raise SourceRuntimeOrchestrationError(
            f"{field} size is outside the safe bound"
        )
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, SourceRuntimeOrchestrationError):
            raise
        raise SourceRuntimeOrchestrationError(
            f"{field} is not strict UTF-8 JSON"
        ) from exc
    if (
        not text.endswith("\n")
        or text.endswith("\n\n")
        or raw != canonical_dag_json_bytes(_plain(value)) + b"\n"
    ):
        raise SourceRuntimeOrchestrationError(
            f"{field} is not canonical newline DAG-JSON"
        )
    return value, raw


def _write_exclusive_canonical(path: Path, value: object) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise SourceRuntimeOrchestrationError(
            "cannot create cache namespace marker exclusively"
        ) from exc
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_dag_json_bytes(_plain(value)) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        raise


def _cache_marker_payload(
    *,
    policy: G240NamespacePolicyV2,
    coordinate: G240JobNamespacePlanV2,
    stage: str,
) -> dict[str, object]:
    return {
        "schema": G240_SOURCE_CACHE_MARKER_SCHEMA_V2,
        "policy_cid": policy.policy_cid,
        "run_id": policy.run_id,
        "plan_cid": coordinate.plan_cid,
        "split": coordinate.split,
        "variant_id": coordinate.variant_id,
        "cache_mode": coordinate.cache_mode,
        "stage": stage,
        "cache_namespace_cid": coordinate.cache_namespace_cids[stage],
    }


@dataclass(frozen=True, slots=True)
class _PhysicalNamespaces:
    root: Path
    state: Path
    output: Path
    evidence: Path
    execution_request: Path
    runtime_preflight: Path
    caches: Mapping[str, Path]
    cache_marker_cids: Mapping[str, str]
    cache_created_exclusive: Mapping[str, bool]


def _physical_namespace_paths(
    *,
    namespace_root: Path,
    policy: G240NamespacePolicyV2,
    coordinate: G240JobNamespacePlanV2,
) -> tuple[Path, Path, Mapping[str, Path]]:
    policy_root = namespace_root / str(policy.policy_cid)
    state = (
        policy_root
        / "state"
        / coordinate.state_namespace_cid
    )
    output = (
        policy_root
        / "output"
        / coordinate.output_namespace_cid
    )
    caches = MappingProxyType(
        {
            stage: (
                policy_root
                / "cache"
                / stage
                / coordinate.cache_namespace_cids[stage]
            )
            for stage in coordinate.stages
        }
    )
    return state, output, caches


def _materialize_physical_namespaces(
    *,
    namespace_root: Path,
    policy: G240NamespacePolicyV2,
    coordinate: G240JobNamespacePlanV2,
) -> _PhysicalNamespaces:
    state, output, caches = _physical_namespace_paths(
        namespace_root=namespace_root,
        policy=policy,
        coordinate=coordinate,
    )
    policy_root = namespace_root / str(policy.policy_cid)
    _ensure_private_parents(namespace_root, policy_root / "state")
    _ensure_private_parents(namespace_root, policy_root / "output")
    _ensure_private_parents(namespace_root, policy_root / "cache")
    _create_exclusive_private_directory(state)
    _create_exclusive_private_directory(output)
    cache_markers: dict[str, str] = {}
    created: dict[str, bool] = {}
    for stage, cache_path in caches.items():
        _ensure_private_parents(namespace_root, cache_path.parent)
        was_created = _ensure_private_directory(cache_path)
        marker = _cache_marker_payload(
            policy=policy,
            coordinate=coordinate,
            stage=stage,
        )
        marker_path = cache_path / _CACHE_MARKER_NAME
        if was_created:
            _write_exclusive_canonical(marker_path, marker)
        observed, _raw = _read_canonical_json(
            marker_path,
            f"{stage} cache namespace marker",
        )
        if _plain(observed) != _plain(marker):
            raise SourceRuntimeOrchestrationError(
                "physical cache namespace marker differs from policy"
            )
        cache_markers[stage] = cid_for_dag_json(marker)
        created[stage] = was_created
    return _PhysicalNamespaces(
        root=namespace_root,
        state=state,
        output=output,
        evidence=output / _EVIDENCE_NAME,
        execution_request=state / G240_EXECUTION_REQUEST_FILE_V2,
        runtime_preflight=state / G240_RUNTIME_PREFLIGHT_FILE_V2,
        caches=MappingProxyType(dict(caches)),
        cache_marker_cids=MappingProxyType(cache_markers),
        cache_created_exclusive=MappingProxyType(created),
    )


def _coerce_policy_coordinate(
    policy: object,
    plan: AblationPlan,
    job: ScheduledCase,
) -> tuple[
    G240NamespacePolicyV2,
    str,
    G240JobNamespacePlanV2,
]:
    if not isinstance(plan, AblationPlan) or not isinstance(
        job, ScheduledCase
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 source execution requires typed plan and job values"
        )
    if job not in plan.jobs:
        raise SourceRuntimeOrchestrationError(
            "scheduled job is not an exact member of the plan"
        )
    try:
        restored = (
            policy
            if isinstance(policy, G240NamespacePolicyV2)
            else G240NamespacePolicyV2.from_dict(policy)
        )
    except (RuntimeNamespaceProvenanceError, TypeError, ValueError) as exc:
        raise SourceRuntimeOrchestrationError(
            "G240 source namespace policy failed typed replay"
        ) from exc
    plan_cid = _plan_cid(plan)
    try:
        coordinate = restored.job_map[(plan_cid, job.job_id)]
        rebuilt = G240JobNamespacePlanV2.create(
            context_cid=restored.context_cid,
            plan_cid=plan_cid,
            plan=plan,
            job=job,
        )
    except (
        KeyError,
        RuntimeNamespaceProvenanceError,
        TypeError,
        ValueError,
    ) as exc:
        raise SourceRuntimeOrchestrationError(
            "G240 policy does not contain the exact scheduled coordinate"
        ) from exc
    if (
        _plain(coordinate.to_dict()) != _plain(rebuilt.to_dict())
        or restored.run_id != plan.run_id
        or plan.environment_sha256 is None
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 source coordinate differs from its plan preimage"
        )
    return restored, plan_cid, coordinate


def _validate_live_worktree(
    worktree: object,
    policy: G240NamespacePolicyV2,
) -> WorktreeSafetyReceipt:
    try:
        from .capabilities import _source_snapshot
        from .source_reconciliation import (
            _capture_benchmark_bounded_gitlinks,
            _validate_live_detached_source,
            _worktree_status,
        )

        receipt = (
            worktree
            if isinstance(worktree, WorktreeSafetyReceipt)
            else WorktreeSafetyReceipt.from_dict(worktree)
        )
        gitlinks = _capture_benchmark_bounded_gitlinks(
            receipt.worktree_root,
            receipt.worktree_commit,
        )
        _validate_live_detached_source(
            receipt.worktree_root,
            commit=receipt.worktree_commit,
            gitlinks=gitlinks,
        )
        active_source = _source_snapshot(
            receipt.source_checkout,
            sanitized_environment=True,
        )
        dirty = _worktree_status(
            receipt.worktree_root,
            ignore_submodules=False,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise SourceRuntimeOrchestrationError(
            "G240 source worktree is not live, clean, and detached"
        ) from exc
    top_level = {
        item.path: item.commit
        for item in gitlinks
        if item.depth == 1
    }
    if (
        dirty
        or receipt.run_id != policy.run_id
        or receipt.base_commit != receipt.worktree_commit
        or g240_source_git_commit_cid(receipt.worktree_commit)
        != policy.source_commit_cid
        or g240_recursive_gitlinks_cid(gitlinks)
        != policy.recursive_gitlinks_cid
        or dict(receipt.submodule_commits) != top_level
        or active_source
        != (
            receipt.source_head,
            receipt.source_branch,
            receipt.source_status_sha256,
        )
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 live source/Gitlink projection differs from policy"
        )
    return WorktreeSafetyReceipt.from_dict(receipt.to_dict())


def _tracked_entrypoint_bytes(
    worktree: WorktreeSafetyReceipt,
    relative_path: str,
    *,
    git_executable_path: str,
    git_executable_cid: str,
) -> bytes:
    path = worktree.worktree_root / relative_path
    try:
        metadata = path.lstat()
        resolved = path.resolve()
    except OSError as exc:
        raise SourceRuntimeOrchestrationError(
            "source executor entrypoint is missing"
        ) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or not resolved.is_relative_to(worktree.worktree_root)
    ):
        raise SourceRuntimeOrchestrationError(
            "source executor entrypoint must be a regular worktree file"
        )
    git_executable, observed_git_cid = _git_executable_identity_v2(
        git_executable_path
    )
    if observed_git_cid != git_executable_cid:
        raise SourceRuntimeOrchestrationError(
            "pinned Git executable changed before source validation"
        )
    try:
        result = subprocess.run(
            [
                git_executable.as_posix(),
                "--no-pager",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-C",
                str(worktree.worktree_root),
                "show",
                f"{worktree.worktree_commit}:{relative_path}",
            ],
            check=True,
            capture_output=True,
            timeout=20,
            env={
                "PATH": os.defpath,
                "GIT_CONFIG_COUNT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
        observed = path.read_bytes()
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceRuntimeOrchestrationError(
            "source executor entrypoint is not pinned by the commit"
        ) from exc
    if result.stdout != observed:
        raise SourceRuntimeOrchestrationError(
            "source executor bytes differ from the pinned Git object"
        )
    return observed


def _coerce_source_executor_contract(
    value: object,
    *,
    policy: G240NamespacePolicyV2,
    plan: AblationPlan,
    worktree: WorktreeSafetyReceipt,
) -> G240SourceExecutorContractV2:
    try:
        contract = (
            value
            if isinstance(value, G240SourceExecutorContractV2)
            else G240SourceExecutorContractV2.from_dict(value)
        )
    except (TypeError, ValueError) as exc:
        raise SourceRuntimeOrchestrationError(
            "source executor contract failed typed replay"
        ) from exc
    if (
        contract.contract_cid
        != policy.runtime_orchestration_policy_cid
        or contract.environment_cid != policy.environment_cid
        or contract.environment_sha256 != plan.environment_sha256
    ):
        raise SourceRuntimeOrchestrationError(
            "source executor contract differs from the frozen namespace "
            "or launch environment"
        )
    if (
        contract.entrypoint_kind != "repository-script"
        or contract.command_template
        != G240_TRACKED_SOURCE_EXECUTOR_COMMAND_V2
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 source launch requires the tracked production G240 "
            "source executor"
        )
    _g240_launch_arguments(contract)
    _tracked_entrypoint_bytes(
        worktree,
        contract.command_template[1],
        git_executable_path=contract.git_executable_path,
        git_executable_cid=contract.git_executable_cid,
    )
    return G240SourceExecutorContractV2.from_dict(contract.to_dict())


def _coerce_source_execution_request(
    value: object,
    *,
    policy: G240NamespacePolicyV2,
    plan: AblationPlan,
    job: ScheduledCase,
    coordinate: G240JobNamespacePlanV2,
    worktree: WorktreeSafetyReceipt,
    contract: G240SourceExecutorContractV2,
) -> G240ExecutionRequestV2:
    """Join a private request to every already-frozen launch preimage."""

    try:
        request = validate_g240_execution_request_v2(value)
    except (G240SourceExecutorError, TypeError, ValueError) as exc:
        raise SourceRuntimeOrchestrationError(
            "G240 source execution request failed typed replay"
        ) from exc
    live_request = (
        request.adapter_factory_id
        != G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2
    )
    if (
        request.execution_mode != "source"
        or request.execution_run_id != policy.run_id
        or request.source_run_id != policy.run_id
        or request.source_commit != worktree.worktree_commit
        or g240_source_git_commit_cid(request.source_commit)
        != policy.source_commit_cid
        or request.policy_cid != policy.policy_cid
        or request.runtime_orchestration_policy_cid
        != contract.contract_cid
        or request.plan_cid != _plan_cid(plan)
        or request.typed_plan != plan
        or request.typed_job != job
        or request.coordinate_cid != coordinate.coordinate_cid
        or request.process_namespace_cid
        != coordinate.process_namespace_cid
        or request.state_namespace_cid
        != coordinate.state_namespace_cid
        or request.output_namespace_cid
        != coordinate.output_namespace_cid
        or dict(request.cache_namespace_cids)
        != dict(coordinate.cache_namespace_cids)
        or request.environment_cid != contract.environment_cid
        or request.environment_sha256
        != contract.environment_sha256
        or (
            live_request
            and (
                request.interpreter_identity_cid
                != contract.interpreter_identity_cid
                or request.git_executable_cid
                != contract.git_executable_cid
                or _plain(request.runtime_environment_artifacts)
                != _plain(contract.runtime_environment_artifacts)
            )
        )
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 source execution request differs from its frozen "
            "plan/job/environment/namespace/contract"
        )
    return G240ExecutionRequestV2.from_dict(request.to_dict())


def _runtime_environment_projection_cid(
    environment_sha256: str,
) -> str:
    if (
        not isinstance(environment_sha256, str)
        or not _SHA256.fullmatch(environment_sha256)
    ):
        raise SourceRuntimeOrchestrationError(
            "runtime environment projection requires a SHA-256 identity"
        )
    return cid_for_dag_json(
        {
            "schema": (
                G240_SOURCE_RUNTIME_ENVIRONMENT_PROJECTION_SCHEMA_V2
            ),
            "legacy_environment_sha256": environment_sha256,
        }
    )


def _validate_runtime_coordinate(
    runtime: CausalRuntimeEvidenceV2,
    *,
    plan: AblationPlan,
    job: ScheduledCase,
    launch_environment_sha256: str,
) -> None:
    result = runtime.case_result
    source_input = (
        job.input_data.get("text")
        if isinstance(job.input_data, Mapping)
        else None
    )
    environments = {
        stage.provenance.environment_sha256
        for stage in (*runtime.semantic_frontend, *result.stages)
    }
    if (
        result.run_id != plan.run_id
        or result.case_id != job.case.case_id
        or result.case_manifest_sha256
        != plan.case_manifest_sha256
        or result.variant_id != job.variant_id
        or result.split is not plan.split
        or result.cache_mode is not job.cache_mode
        or launch_environment_sha256 != plan.environment_sha256
        or environments != {launch_environment_sha256}
        or (
            isinstance(source_input, str)
            and runtime.source_text != source_input
        )
    ):
        raise SourceRuntimeOrchestrationError(
            "runtime evidence differs from the scheduled coordinate"
        )


def _physical_projection_cid(
    *,
    coordinate: G240JobNamespacePlanV2,
    cache_marker_cids: Mapping[str, str],
) -> str:
    markers = {
        _safe_id(stage, "cache marker stage"): _cid(
            marker, f"cache_marker_cids.{stage}"
        )
        for stage, marker in cache_marker_cids.items()
    }
    if set(markers) != set(coordinate.stages):
        raise SourceRuntimeOrchestrationError(
            "physical cache marker population is incomplete"
        )
    return cid_for_dag_json(
        {
            "schema": G240_SOURCE_PHYSICAL_NAMESPACE_SCHEMA_V2,
            "process_namespace_cid": (
                coordinate.process_namespace_cid
            ),
            "state_namespace_cid": coordinate.state_namespace_cid,
            "output_namespace_cid": coordinate.output_namespace_cid,
            "cache_namespace_cids": dict(
                coordinate.cache_namespace_cids
            ),
            "cache_marker_cids": {
                stage: markers[stage]
                for stage in coordinate.stages
            },
            "directory_policy": (
                "private-real-exclusive-state-output-"
                "exclusive-or-exact-reuse-cache"
            ),
        }
    )


def _validate_runtime_preflight(
    value: object,
    *,
    request: G240ExecutionRequestV2,
    contract: G240SourceExecutorContractV2,
    landlock_sources: G240LandlockPrivatePolicySourcesV1 | None = None,
    landlock_receipt: G240LandlockReceiptV1 | None = None,
    expected_gitlink_commit: str | None = None,
) -> tuple[str, G240BootstrapConfinementReceiptV2]:
    data = _mapping(value, "G240 runtime import preflight")
    _exact(
        data,
        {
            "schema",
            "request_cid",
            "bootstrap_confinement_receipt",
            "landlock_policy_cid",
            "landlock_receipt_cid",
            "interpreter_identity_cid",
            "git_executable_cid",
            "runtime_environment_artifact_cids",
            "symai_configuration_cid",
            "symai_configuration_relative_path",
            "imports",
            "synthetic_test_only",
        },
        "G240 runtime import preflight",
    )
    if data["schema"] != (
        "ipfs-datasets.logic-pipeline-benchmark."
        "runtime-import-preflight.v2"
    ):
        raise SourceRuntimeOrchestrationError(
            "unsupported G240 runtime preflight schema"
        )
    synthetic = (
        request.adapter_factory_id
        == G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2
    )
    try:
        bootstrap_receipt = (
            validate_g240_bootstrap_confinement_receipt_v2(
                data["bootstrap_confinement_receipt"],
                expected_policy=(
                    None
                    if landlock_sources is None
                    else landlock_sources.policy
                ),
                synthetic_test_only=synthetic,
            )
        )
        expected_source_observation = (
            g240_bootstrap_git_observation_cid(
                request.source_commit,
                role="source",
            )
        )
        expected_gitlink_observation = (
            None
            if expected_gitlink_commit is None
            else g240_bootstrap_git_observation_cid(
                expected_gitlink_commit,
                role="ipfs-accelerate-gitlink",
            )
        )
    except (
        G240BootstrapContractError,
        TypeError,
        ValueError,
    ) as exc:
        raise SourceRuntimeOrchestrationError(
            "runtime preflight bootstrap receipt is invalid"
        ) from exc
    artifacts = _mapping(
        data["runtime_environment_artifact_cids"],
        "runtime preflight artifact CIDs",
    )
    expected_artifacts = {
        label: descriptor["payload_cid"]
        for label, descriptor in (
            contract.runtime_environment_artifacts.items()
        )
    }
    imports = _mapping(data["imports"], "runtime preflight imports")
    expected_symai_configuration_cid: str | None = None
    expected_symai_configuration_relative_path: str | None = None
    if not synthetic:
        try:
            inventory = CapabilityInventory.from_dict(
                request.adapter_configuration[
                    "capability_inventory"
                ]
            )
            symai_model = _symai_runtime_model(inventory)
            if symai_model is not None:
                expected_symai_configuration_cid = (
                    symai_runtime_configuration_cid(symai_model)
                )
                expected_symai_configuration_relative_path = (
                    f"{inventory.run_id}/symai-runtime/"
                    ".symai/symai.config.json"
                )
        except (TypeError, ValueError) as exc:
            raise SourceRuntimeOrchestrationError(
                "runtime preflight SyMAI identity is invalid"
            ) from exc
    for module_name, raw in imports.items():
        if (
            not isinstance(module_name, str)
            or not module_name
            or "\0" in module_name
        ):
            raise SourceRuntimeOrchestrationError(
                "runtime preflight import name is invalid"
            )
        descriptor = _mapping(
            raw, f"runtime preflight import {module_name}"
        )
        _exact(
            descriptor,
            {"module_file_cid", "version"},
            f"runtime preflight import {module_name}",
        )
        _cid(
            descriptor["module_file_cid"],
            f"runtime preflight import {module_name} CID",
        )
        if descriptor["version"] is not None and not isinstance(
            descriptor["version"], str
        ):
            raise SourceRuntimeOrchestrationError(
                "runtime preflight module version is invalid"
            )
    for label, artifact_cid in artifacts.items():
        if not label.startswith(_PYTHON_MODULE_ARTIFACT_PREFIX):
            continue
        module_name = label.removeprefix(
            _PYTHON_MODULE_ARTIFACT_PREFIX
        )
        imported = imports.get(module_name)
        if (
            not isinstance(imported, Mapping)
            or imported.get("module_file_cid") != artifact_cid
        ):
            raise SourceRuntimeOrchestrationError(
                "runtime preflight Python-module artifact/import join "
                "changed"
            )
    if (
        data["request_cid"] != request.request_cid
        or data["synthetic_test_only"] is not synthetic
        or (
            synthetic
            and (
                data["landlock_policy_cid"] is not None
                or data["landlock_receipt_cid"] is not None
                or landlock_sources is not None
                or landlock_receipt is not None
                or data["interpreter_identity_cid"] is not None
                or data["git_executable_cid"] is not None
                or artifacts
                or data["symai_configuration_cid"] is not None
                or data["symai_configuration_relative_path"] is not None
                or imports
            )
        )
        or (
            not synthetic
            and (
                landlock_sources is None
                or landlock_receipt is None
                or data["landlock_policy_cid"]
                != landlock_sources.policy.policy_cid
                or data["landlock_receipt_cid"]
                != landlock_receipt.receipt_cid
                or bootstrap_receipt.typed_landlock_receipt
                != landlock_receipt
                or data["interpreter_identity_cid"]
                != contract.interpreter_identity_cid
                or data["git_executable_cid"]
                != contract.git_executable_cid
                or dict(artifacts) != expected_artifacts
                or data["symai_configuration_cid"]
                != expected_symai_configuration_cid
                or data["symai_configuration_relative_path"]
                != expected_symai_configuration_relative_path
                or not imports
            )
        )
        or bootstrap_receipt.source_commit_observation_cid
        != expected_source_observation
        or bootstrap_receipt.source_bound_gitlink_observation_cid
        != expected_gitlink_observation
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 runtime preflight differs from its pinned environment"
        )
    return cid_for_dag_json(_plain(data)), bootstrap_receipt


@dataclass(frozen=True, slots=True)
class G240SourceOrchestrationReceiptV2:
    """Path-free proof of one actually launched G240 source job."""

    policy_cid: str
    runtime_orchestration_policy_cid: str
    plan_cid: str
    coordinate_cid: str
    job_id: str
    runtime_namespace_receipt_cid: str
    runtime_evidence_cid: str
    source_commit_cid: str
    recursive_gitlinks_cid: str
    launch_environment_cid: str
    runtime_environment_projection_cid: str
    worktree_safety_projection_cid: str
    process_namespace_cid: str
    state_namespace_cid: str
    output_namespace_cid: str
    cache_namespace_set_cid: str
    cache_marker_cids: Mapping[str, str]
    cache_namespace_created_exclusive: Mapping[str, bool]
    physical_namespace_projection_cid: str
    command_cid: str
    interpreter_identity_cid: str
    confinement_profile_cid: str
    execution_request_cid: str
    runtime_preflight_cid: str
    landlock_policy_cid: str | None
    landlock_receipt_cid: str | None
    landlock_receipt_payload_cid: str | None
    evidence_payload_cid: str
    executor_identity_cid: str
    namespace_observer_identity_cid: str
    orchestration_observer_identity_cid: str
    state_namespace_created_exclusive: bool
    output_namespace_created_exclusive: bool
    cache_namespaces_private: bool
    process_group_started: bool
    process_group_reaped: bool
    active_process_count_after_reap: int
    worktree_clean_before: bool
    worktree_clean_after: bool
    evidence_canonical: bool
    synthetic_test_only: bool
    complete: bool
    holdout_accessed: bool
    schema: str = G240_SOURCE_ORCHESTRATION_RECEIPT_SCHEMA_V2
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G240_SOURCE_ORCHESTRATION_RECEIPT_SCHEMA_V2:
            raise SourceRuntimeOrchestrationError(
                "unsupported G240 source orchestration schema"
            )
        for field in (
            "policy_cid",
            "runtime_orchestration_policy_cid",
            "plan_cid",
            "coordinate_cid",
            "runtime_namespace_receipt_cid",
            "runtime_evidence_cid",
            "source_commit_cid",
            "recursive_gitlinks_cid",
            "launch_environment_cid",
            "runtime_environment_projection_cid",
            "worktree_safety_projection_cid",
            "process_namespace_cid",
            "state_namespace_cid",
            "output_namespace_cid",
            "cache_namespace_set_cid",
            "physical_namespace_projection_cid",
            "command_cid",
            "interpreter_identity_cid",
            "confinement_profile_cid",
            "execution_request_cid",
            "runtime_preflight_cid",
            "evidence_payload_cid",
            "executor_identity_cid",
            "namespace_observer_identity_cid",
            "orchestration_observer_identity_cid",
        ):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        for field in (
            "landlock_policy_cid",
            "landlock_receipt_cid",
            "landlock_receipt_payload_cid",
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _cid(value, field))
        object.__setattr__(self, "job_id", _safe_id(self.job_id, "job_id"))
        marker_values = _mapping(
            self.cache_marker_cids, "cache_marker_cids"
        )
        created_values = _mapping(
            self.cache_namespace_created_exclusive,
            "cache_namespace_created_exclusive",
        )
        if set(marker_values) != set(created_values) or not marker_values:
            raise SourceRuntimeOrchestrationError(
                "cache marker and creation observations differ"
            )
        markers: dict[str, str] = {}
        created: dict[str, bool] = {}
        for stage in sorted(marker_values):
            _safe_id(stage, "cache stage")
            markers[stage] = _cid(
                marker_values[stage],
                f"cache_marker_cids.{stage}",
            )
            observed = created_values[stage]
            if type(observed) is not bool:
                raise SourceRuntimeOrchestrationError(
                    "cache creation observations must be booleans"
                )
            created[stage] = observed
        object.__setattr__(
            self,
            "cache_marker_cids",
            MappingProxyType(markers),
        )
        object.__setattr__(
            self,
            "cache_namespace_created_exclusive",
            MappingProxyType(created),
        )
        for field in (
            "state_namespace_created_exclusive",
            "output_namespace_created_exclusive",
            "cache_namespaces_private",
            "process_group_started",
            "process_group_reaped",
            "worktree_clean_before",
            "worktree_clean_after",
            "evidence_canonical",
            "synthetic_test_only",
            "complete",
            "holdout_accessed",
        ):
            if type(getattr(self, field)) is not bool:
                raise SourceRuntimeOrchestrationError(
                    f"{field} must be an observed boolean"
                )
        if (
            self.confinement_profile_cid
            != G240_BOOTSTRAP_CONFINEMENT_PROFILE_CID_V2
            or (
                self.synthetic_test_only
                and any(
                    value is not None
                    for value in (
                        self.landlock_policy_cid,
                        self.landlock_receipt_cid,
                        self.landlock_receipt_payload_cid,
                    )
                )
            )
            or (
                not self.synthetic_test_only
                and any(
                    value is None
                    for value in (
                        self.landlock_policy_cid,
                        self.landlock_receipt_cid,
                        self.landlock_receipt_payload_cid,
                    )
                )
            )
        ):
            raise SourceRuntimeOrchestrationError(
                "G240 source confinement evidence is incomplete"
            )
        if (
            type(self.active_process_count_after_reap) is not int
            or self.active_process_count_after_reap < 0
        ):
            raise SourceRuntimeOrchestrationError(
                "active_process_count_after_reap must be nonnegative"
            )
        authorities = {
            self.executor_identity_cid,
            self.namespace_observer_identity_cid,
            self.orchestration_observer_identity_cid,
        }
        if len(authorities) != 3:
            raise SourceRuntimeOrchestrationError(
                "G240 source execution authorities must be independent"
            )
        if not all(
            (
                self.state_namespace_created_exclusive,
                self.output_namespace_created_exclusive,
                self.cache_namespaces_private,
                self.process_group_started,
                self.process_group_reaped,
                self.active_process_count_after_reap == 0,
                self.worktree_clean_before,
                self.worktree_clean_after,
                self.evidence_canonical,
                self.complete,
                not self.holdout_accessed,
            )
        ):
            raise SourceRuntimeOrchestrationError(
                "G240 source orchestration is incomplete"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.receipt_cid is None:
            object.__setattr__(self, "receipt_cid", expected)
        elif _cid(self.receipt_cid, "receipt_cid") != expected:
            raise SourceRuntimeOrchestrationError(
                "G240 source orchestration receipt CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            name: (
                dict(value)
                if isinstance(
                    value,
                    Mapping,
                )
                else value
            )
            for name, value in (
                (field, getattr(self, field))
                for field in self.__dataclass_fields__
                if field != "receipt_cid"
            )
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "receipt_cid": self.receipt_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G240 source orchestration receipt")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G240 source orchestration receipt",
        )
        return cls(
            **{
                **data,
                "cache_marker_cids": _mapping(
                    data["cache_marker_cids"],
                    "cache_marker_cids",
                ),
                "cache_namespace_created_exclusive": _mapping(
                    data["cache_namespace_created_exclusive"],
                    "cache_namespace_created_exclusive",
                ),
            }
        )  # type: ignore[arg-type]


def _inspect_physical_namespaces(
    *,
    namespace_root: Path,
    policy: G240NamespacePolicyV2,
    coordinate: G240JobNamespacePlanV2,
) -> tuple[Mapping[str, str], Mapping[str, bool]]:
    state, output, caches = _physical_namespace_paths(
        namespace_root=namespace_root,
        policy=policy,
        coordinate=coordinate,
    )
    _validate_private_directory(state, "source state namespace")
    _validate_private_directory(output, "source output namespace")
    markers: dict[str, str] = {}
    for stage, cache_path in caches.items():
        _validate_private_directory(
            cache_path, f"{stage} physical cache namespace"
        )
        expected = _cache_marker_payload(
            policy=policy,
            coordinate=coordinate,
            stage=stage,
        )
        observed, _raw = _read_canonical_json(
            cache_path / _CACHE_MARKER_NAME,
            f"{stage} physical cache marker",
        )
        if _plain(observed) != _plain(expected):
            raise SourceRuntimeOrchestrationError(
                "physical cache marker differs from source policy"
            )
        markers[stage] = cid_for_dag_json(expected)
    return MappingProxyType(markers), MappingProxyType(
        {stage: False for stage in coordinate.stages}
    )


_G240_SOURCE_PROCESS_CAPABILITY_V2: Final = object()


@dataclass(frozen=True, slots=True)
class _G240SourceProcessObservationV2:
    """Unserialized witness issued only around an actual bounded launch."""

    result: BoundedProcessResult
    interpreter_identity_cid: str
    process_group_started: bool
    active_process_count_after_reap: int
    _capability: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._capability is not _G240_SOURCE_PROCESS_CAPABILITY_V2
            or not isinstance(self.result, BoundedProcessResult)
            or self.process_group_started is not True
            or self.active_process_count_after_reap != 0
        ):
            raise SourceRuntimeOrchestrationError(
                "G240 source process observation lacks live-run authority"
            )
        object.__setattr__(
            self,
            "interpreter_identity_cid",
            _cid(
                self.interpreter_identity_cid,
                "interpreter_identity_cid",
            ),
        )


_G240_LANDLOCK_TRANSPORT_CAPABILITY_V2: Final = object()
_G240_MAX_LANDLOCK_RECEIPT_BYTES: Final = 64 * 1024


@dataclass(frozen=True, slots=True)
class _G240LandlockTransportObservationV2:
    """Private proof joining one receipt pipe to one actual child process."""

    process_observation: _G240SourceProcessObservationV2
    policy_sources: G240LandlockPrivatePolicySourcesV1
    receipt: G240LandlockReceiptV1
    receipt_payload: bytes
    close_fds: bool
    passed_descriptor_count: int
    one_shot_atomic_frame: bool
    _capability: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._capability
            is not _G240_LANDLOCK_TRANSPORT_CAPABILITY_V2
            or not isinstance(
                self.process_observation,
                _G240SourceProcessObservationV2,
            )
            or not isinstance(
                self.policy_sources,
                G240LandlockPrivatePolicySourcesV1,
            )
            or not isinstance(self.receipt, G240LandlockReceiptV1)
            or not isinstance(self.receipt_payload, bytes)
            or self.close_fds is not True
            or self.passed_descriptor_count != 1
            or self.one_shot_atomic_frame is not True
        ):
            raise SourceRuntimeOrchestrationError(
                "G240 Landlock transport lacks live pipe/process authority"
            )
        expected = validate_g240_landlock_receipt_v1(
            self.receipt,
            expected_policy=self.policy_sources.policy,
        )
        if self.receipt_payload != (
            canonical_dag_json_bytes(expected.to_dict()) + b"\n"
        ):
            raise SourceRuntimeOrchestrationError(
                "G240 Landlock pipe bytes differ from the typed receipt"
            )


def _read_g240_landlock_receipt_pipe(
    descriptor: int,
    *,
    expected_policy: G240LandlockPolicyV1,
) -> tuple[G240LandlockReceiptV1, bytes]:
    payload = bytearray()
    try:
        while True:
            chunk = os.read(descriptor, 4096)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > _G240_MAX_LANDLOCK_RECEIPT_BYTES:
                raise SourceRuntimeOrchestrationError(
                    "G240 Landlock receipt pipe exceeded its bound"
                )
    except OSError as exc:
        raise SourceRuntimeOrchestrationError(
            "cannot read the G240 Landlock receipt pipe"
        ) from exc
    finally:
        os.close(descriptor)
    raw = bytes(payload)
    if (
        not raw
        or not raw.endswith(b"\n")
        or raw.endswith(b"\n\n")
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 Landlock receipt pipe framing is invalid"
        )
    try:
        decoded = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
        )
        receipt = validate_g240_landlock_receipt_v1(
            decoded,
            expected_policy=expected_policy,
        )
    except (
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        G240LandlockConfinementError,
    ) as exc:
        raise SourceRuntimeOrchestrationError(
            "G240 Landlock receipt pipe failed typed replay"
        ) from exc
    if raw != canonical_dag_json_bytes(receipt.to_dict()) + b"\n":
        raise SourceRuntimeOrchestrationError(
            "G240 Landlock receipt pipe is not canonical newline DAG-JSON"
        )
    return receipt, raw


def _observe_g240_source_process_v2(
    result: BoundedProcessResult,
    contract: G240SourceExecutorContractV2,
) -> _G240SourceProcessObservationV2:
    """Issue a private witness only after the bounded runner returns."""

    expected_arguments = _g240_launch_arguments(contract)
    if (
        not isinstance(result, BoundedProcessResult)
        or result.arguments != expected_arguments
        or result.returncode != 0
        or result.timed_out
        or not result.process_group_reaped
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 source process did not complete and reap successfully"
        )
    return _G240SourceProcessObservationV2(
        result=result,
        interpreter_identity_cid=contract.interpreter_identity_cid,
        process_group_started=True,
        active_process_count_after_reap=0,
        _capability=_G240_SOURCE_PROCESS_CAPABILITY_V2,
    )


def _build_g240_source_orchestration_receipt_v2(
    *,
    policy: G240NamespacePolicyV2,
    plan: AblationPlan,
    job: ScheduledCase,
    worktree_safety_receipt: WorktreeSafetyReceipt,
    namespace_root: str | Path,
    runtime_evidence: CausalRuntimeEvidenceV2,
    runtime_namespace_receipt: G240RuntimeNamespaceReceiptV2,
    executor_contract: G240SourceExecutorContractV2,
    execution_request: G240ExecutionRequestV2,
    execution_request_payload: bytes,
    runtime_preflight_payload: bytes,
    evidence_payload: bytes,
    process_observation: _G240SourceProcessObservationV2,
    landlock_transport_observation: (
        _G240LandlockTransportObservationV2 | None
    ),
    orchestration_observer_identity_cid: str,
    cache_namespace_created_exclusive: (
        Mapping[str, bool] | None
    ) = None,
) -> G240SourceOrchestrationReceiptV2:
    """Recompute a public receipt from exact live execution sources."""

    restored, plan_cid, coordinate = _coerce_policy_coordinate(
        policy, plan, job
    )
    worktree = _validate_live_worktree(
        worktree_safety_receipt, restored
    )
    contract = _coerce_source_executor_contract(
        executor_contract,
        policy=restored,
        plan=plan,
        worktree=worktree,
    )
    request = _coerce_source_execution_request(
        execution_request,
        policy=restored,
        plan=plan,
        job=job,
        coordinate=coordinate,
        worktree=worktree,
        contract=contract,
    )
    root = _validate_namespace_root(namespace_root, worktree)
    if not isinstance(execution_request_payload, bytes):
        raise SourceRuntimeOrchestrationError(
            "G240 execution request payload must be exact bytes"
        )
    expected_request_payload = (
        canonical_dag_json_bytes(request.to_dict()) + b"\n"
    )
    if execution_request_payload != expected_request_payload:
        raise SourceRuntimeOrchestrationError(
            "G240 execution request bytes are not exact canonical JSON"
        )
    observed_request, observed_request_payload = _read_canonical_json(
        _physical_namespace_paths(
            namespace_root=root,
            policy=restored,
            coordinate=coordinate,
        )[0]
        / G240_EXECUTION_REQUEST_FILE_V2,
        "G240 private execution request",
    )
    try:
        observed_typed_request = validate_g240_execution_request_v2(
            observed_request
        )
    except (G240SourceExecutorError, TypeError, ValueError) as exc:
        raise SourceRuntimeOrchestrationError(
            "G240 persisted execution request failed typed replay"
        ) from exc
    if (
        observed_request_payload != execution_request_payload
        or observed_typed_request != request
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 persisted execution request differs from launch input"
        )
    observed_preflight, observed_preflight_payload = _read_canonical_json(
        _physical_namespace_paths(
            namespace_root=root,
            policy=restored,
            coordinate=coordinate,
        )[0]
        / G240_RUNTIME_PREFLIGHT_FILE_V2,
        "G240 runtime import preflight",
    )
    if (
        not isinstance(runtime_preflight_payload, bytes)
        or observed_preflight_payload != runtime_preflight_payload
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 runtime preflight bytes differ from the child output"
        )
    synthetic = (
        request.adapter_factory_id
        == G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2
    )
    if synthetic:
        if landlock_transport_observation is not None:
            raise SourceRuntimeOrchestrationError(
                "synthetic G240 execution may not claim Landlock transport"
            )
        landlock_sources = None
        landlock_receipt = None
        landlock_payload = None
    else:
        transport = landlock_transport_observation
        if (
            not isinstance(
                transport,
                _G240LandlockTransportObservationV2,
            )
            or transport._capability
            is not _G240_LANDLOCK_TRANSPORT_CAPABILITY_V2
            or transport.process_observation is not process_observation
        ):
            raise SourceRuntimeOrchestrationError(
                "production G240 receipt lacks its live Landlock transport"
            )
        landlock_sources = transport.policy_sources
        landlock_receipt = transport.receipt
        landlock_payload = transport.receipt_payload
    runtime_preflight_cid, _bootstrap_receipt = (
        _validate_runtime_preflight(
        observed_preflight,
        request=request,
        contract=contract,
        landlock_sources=landlock_sources,
        landlock_receipt=landlock_receipt,
        expected_gitlink_commit=worktree.submodule_commits.get(
            "ipfs_accelerate_py"
        ),
        )
    )
    try:
        runtime = validate_causal_runtime_evidence_v2(
            runtime_evidence.to_dict()
        )
        namespace_receipt = (
            validate_g240_runtime_namespace_receipt_v2(
                runtime_namespace_receipt,
                policy=restored,
                plan=plan,
                job=job,
                evidence=runtime,
            )
        )
    except (
        RuntimeNamespaceProvenanceError,
        TypeError,
        ValueError,
    ) as exc:
        raise SourceRuntimeOrchestrationError(
            "G240 runtime namespace sources failed replay"
        ) from exc
    _validate_runtime_coordinate(
        runtime,
        plan=plan,
        job=job,
        launch_environment_sha256=contract.environment_sha256,
    )
    if not isinstance(evidence_payload, bytes):
        raise SourceRuntimeOrchestrationError(
            "G240 source evidence payload must be exact bytes"
        )
    expected_payload = (
        canonical_dag_json_bytes(_plain(runtime.to_dict())) + b"\n"
    )
    if evidence_payload != expected_payload:
        raise SourceRuntimeOrchestrationError(
            "G240 source evidence bytes are not exact canonical runtime JSON"
        )
    if (
        not isinstance(
            process_observation,
            _G240SourceProcessObservationV2,
        )
        or process_observation._capability
        is not _G240_SOURCE_PROCESS_CAPABILITY_V2
        or process_observation.interpreter_identity_cid
        != contract.interpreter_identity_cid
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 source receipt requires a privately observed live process"
        )
    process_result = process_observation.result
    _observe_g240_source_process_v2(process_result, contract)
    marker_cids, default_created = _inspect_physical_namespaces(
        namespace_root=root,
        policy=restored,
        coordinate=coordinate,
    )
    created = (
        default_created
        if cache_namespace_created_exclusive is None
        else cache_namespace_created_exclusive
    )
    if set(created) != set(coordinate.stages) or any(
        type(value) is not bool for value in created.values()
    ):
        raise SourceRuntimeOrchestrationError(
            "cache creation observations are incomplete"
        )
    observer = _cid(
        orchestration_observer_identity_cid,
        "orchestration_observer_identity_cid",
    )
    if (
        namespace_receipt.executor_identity_cid
        != contract.executor_identity_cid
        or restored.namespace_authority_cid in {
            namespace_receipt.executor_identity_cid,
            namespace_receipt.observer_identity_cid,
        }
        or observer in {
            restored.namespace_authority_cid,
            namespace_receipt.executor_identity_cid,
            namespace_receipt.observer_identity_cid,
        }
    ):
        raise SourceRuntimeOrchestrationError(
            "G240 policy/executor/observer authorities must be independent"
        )
    if (
        namespace_receipt.policy_cid != restored.policy_cid
        or namespace_receipt.plan_cid != plan_cid
        or namespace_receipt.coordinate_cid
        != coordinate.coordinate_cid
        or namespace_receipt.process_namespace_cid
        != coordinate.process_namespace_cid
        or namespace_receipt.state_namespace_cid
        != coordinate.state_namespace_cid
        or namespace_receipt.output_namespace_cid
        != coordinate.output_namespace_cid
        or dict(namespace_receipt.cache_namespace_cids)
        != dict(coordinate.cache_namespace_cids)
    ):
        raise SourceRuntimeOrchestrationError(
            "runtime namespace receipt differs from executed coordinate"
        )
    return G240SourceOrchestrationReceiptV2(
        policy_cid=str(restored.policy_cid),
        runtime_orchestration_policy_cid=str(contract.contract_cid),
        plan_cid=plan_cid,
        coordinate_cid=str(coordinate.coordinate_cid),
        job_id=job.job_id,
        runtime_namespace_receipt_cid=str(
            namespace_receipt.receipt_cid
        ),
        runtime_evidence_cid=runtime.receipt_cid,
        source_commit_cid=restored.source_commit_cid,
        recursive_gitlinks_cid=restored.recursive_gitlinks_cid,
        launch_environment_cid=contract.environment_cid,
        runtime_environment_projection_cid=(
            _runtime_environment_projection_cid(
                contract.environment_sha256
            )
        ),
        worktree_safety_projection_cid=(
            g240_worktree_safety_projection_cid(worktree)
        ),
        process_namespace_cid=coordinate.process_namespace_cid,
        state_namespace_cid=coordinate.state_namespace_cid,
        output_namespace_cid=coordinate.output_namespace_cid,
        cache_namespace_set_cid=g240_cache_namespace_set_cid(
            coordinate.cache_namespace_cids
        ),
        cache_marker_cids=marker_cids,
        cache_namespace_created_exclusive=created,
        physical_namespace_projection_cid=(
            _physical_projection_cid(
                coordinate=coordinate,
                cache_marker_cids=marker_cids,
            )
        ),
        command_cid=contract.command_template_cid,
        interpreter_identity_cid=contract.interpreter_identity_cid,
        confinement_profile_cid=contract.confinement_profile_cid,
        execution_request_cid=str(request.request_cid),
        runtime_preflight_cid=runtime_preflight_cid,
        landlock_policy_cid=(
            None
            if landlock_sources is None
            else str(landlock_sources.policy.policy_cid)
        ),
        landlock_receipt_cid=(
            None
            if landlock_receipt is None
            else str(landlock_receipt.receipt_cid)
        ),
        landlock_receipt_payload_cid=(
            None
            if landlock_payload is None
            else cid_for_bytes(landlock_payload)
        ),
        evidence_payload_cid=cid_for_bytes(evidence_payload),
        executor_identity_cid=namespace_receipt.executor_identity_cid,
        namespace_observer_identity_cid=(
            namespace_receipt.observer_identity_cid
        ),
        orchestration_observer_identity_cid=observer,
        state_namespace_created_exclusive=True,
        output_namespace_created_exclusive=True,
        cache_namespaces_private=True,
        process_group_started=process_observation.process_group_started,
        process_group_reaped=process_result.process_group_reaped,
        active_process_count_after_reap=(
            process_observation.active_process_count_after_reap
        ),
        worktree_clean_before=True,
        worktree_clean_after=True,
        evidence_canonical=True,
        synthetic_test_only=synthetic,
        complete=True,
        holdout_accessed=False,
    )


@dataclass(frozen=True, slots=True)
class G240PrivateSourceValidationSourcesV2:
    """Non-serializable live inputs for one source orchestration receipt."""

    policy: object
    plan: AblationPlan
    job: ScheduledCase
    worktree_safety_receipt: object
    namespace_root: Path
    runtime_evidence: CausalRuntimeEvidenceV2
    runtime_namespace_receipt: object
    executor_contract: object
    execution_request: object
    orchestration_receipt: object
    execution_request_payload: bytes
    runtime_preflight_payload: bytes
    evidence_payload: bytes
    process_result: BoundedProcessResult
    process_observation: _G240SourceProcessObservationV2
    landlock_transport_observation: (
        _G240LandlockTransportObservationV2 | None
    )
    cache_namespace_created_exclusive: Mapping[str, bool]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.execution_request_payload, bytes)
            or not isinstance(self.runtime_preflight_payload, bytes)
            or not isinstance(self.evidence_payload, bytes)
            or not isinstance(
                self.process_observation,
                _G240SourceProcessObservationV2,
            )
            or self.process_observation._capability
            is not _G240_SOURCE_PROCESS_CAPABILITY_V2
            or self.process_observation.result is not self.process_result
            or (
                self.landlock_transport_observation is not None
                and (
                    not isinstance(
                        self.landlock_transport_observation,
                        _G240LandlockTransportObservationV2,
                    )
                    or (
                        self.landlock_transport_observation
                        .process_observation
                        is not self.process_observation
                    )
                )
            )
        ):
            raise SourceRuntimeOrchestrationError(
                "private source inputs lack exact bytes or live process "
                "authority"
            )
        object.__setattr__(self, "namespace_root", Path(self.namespace_root))
        object.__setattr__(
            self,
            "cache_namespace_created_exclusive",
            MappingProxyType(
                dict(self.cache_namespace_created_exclusive)
            ),
        )


def validate_g240_private_source_sources_v2(
    value: G240PrivateSourceValidationSourcesV2,
) -> tuple[
    G240NamespacePolicyV2,
    G240RuntimeNamespaceReceiptV2,
    G240SourceOrchestrationReceiptV2,
]:
    """Source-recompute a public receipt from live Git/OS/private inputs."""

    if not isinstance(value, G240PrivateSourceValidationSourcesV2):
        raise SourceRuntimeOrchestrationError(
            "G240 source validation requires private live sources"
        )
    restored, _plan_cid_value, _coordinate = _coerce_policy_coordinate(
        value.policy,
        value.plan,
        value.job,
    )
    try:
        namespace_receipt = (
            value.runtime_namespace_receipt
            if isinstance(
                value.runtime_namespace_receipt,
                G240RuntimeNamespaceReceiptV2,
            )
            else G240RuntimeNamespaceReceiptV2.from_dict(
                value.runtime_namespace_receipt
            )
        )
        receipt = (
            value.orchestration_receipt
            if isinstance(
                value.orchestration_receipt,
                G240SourceOrchestrationReceiptV2,
            )
            else G240SourceOrchestrationReceiptV2.from_dict(
                value.orchestration_receipt
            )
        )
    except (TypeError, ValueError) as exc:
        raise SourceRuntimeOrchestrationError(
            "G240 source receipts failed typed replay"
        ) from exc
    rebuilt = _build_g240_source_orchestration_receipt_v2(
        policy=restored,
        plan=value.plan,
        job=value.job,
        worktree_safety_receipt=value.worktree_safety_receipt,
        namespace_root=value.namespace_root,
        runtime_evidence=value.runtime_evidence,
        runtime_namespace_receipt=namespace_receipt,
        executor_contract=value.executor_contract,
        execution_request=value.execution_request,
        execution_request_payload=value.execution_request_payload,
        runtime_preflight_payload=value.runtime_preflight_payload,
        evidence_payload=value.evidence_payload,
        process_observation=value.process_observation,
        landlock_transport_observation=(
            value.landlock_transport_observation
        ),
        orchestration_observer_identity_cid=(
            receipt.orchestration_observer_identity_cid
        ),
        cache_namespace_created_exclusive=(
            value.cache_namespace_created_exclusive
        ),
    )
    if _plain(receipt.to_dict()) != _plain(rebuilt.to_dict()):
        raise SourceRuntimeOrchestrationError(
            "G240 source orchestration receipt did not source-recompute"
        )
    return restored, namespace_receipt, rebuilt


@dataclass(frozen=True, slots=True)
class G240SourceExecutionResultV2:
    """Private return value from one live source job."""

    runtime_evidence: CausalRuntimeEvidenceV2
    runtime_namespace_receipt: G240RuntimeNamespaceReceiptV2
    orchestration_receipt: G240SourceOrchestrationReceiptV2
    validation_sources: G240PrivateSourceValidationSourcesV2
    process_result: BoundedProcessResult


def _validate_environment(
    environment: Mapping[str, str] | None,
) -> dict[str, str]:
    extra = {} if environment is None else dict(environment)
    if any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or "\0" in key
        or "\0" in value
        for key, value in extra.items()
    ):
        raise SourceRuntimeOrchestrationError(
            "source environment must contain NUL-free strings"
        )
    reserved = sorted(
        key
        for key in extra
        if key in _RESERVED_ENVIRONMENT
        or key == "PATH"
        or key.startswith("HSSL_G240_")
        or key.startswith("PYTHON")
        or key.startswith("GIT_")
        or key.startswith("LD_")
        or key.startswith("DYLD_")
        or key in {"VIRTUAL_ENV", "CONDA_PREFIX"}
        or key
        in {
            "BASH_ENV",
            "CDPATH",
            "ENV",
            "GCONV_PATH",
            "HOME",
            "IFS",
            "LOCPATH",
            "NLSPATH",
            "SHELLOPTS",
        }
    )
    if reserved:
        raise SourceRuntimeOrchestrationError(
            "caller may not override reserved G240 environment keys: "
            + ", ".join(reserved)
        )
    if extra:
        raise SourceRuntimeOrchestrationError(
            "caller-supplied G240 environment is not content-bound: "
            + ", ".join(sorted(extra))
        )
    return extra


_G240_LANDLOCK_RUNTIME_PROBE = (
    "import json,site,sys,sysconfig;"
    "print(json.dumps({"
    "'prefix':sys.prefix,"
    "'base_prefix':sys.base_prefix,"
    "'stdlib':sysconfig.get_path('stdlib'),"
    "'platstdlib':sysconfig.get_path('platstdlib'),"
    "'site_packages':site.getsitepackages()"
    "},sort_keys=True,separators=(',',':')))"
)


def _g240_landlock_regular_or_directory(
    value: str | Path,
) -> Path | None:
    requested = Path(value)
    if not requested.is_absolute():
        return None
    lexical = Path(os.path.abspath(os.fspath(requested)))
    if lexical != requested:
        return None
    try:
        metadata = lexical.lstat()
        path = lexical.resolve(strict=True)
    except OSError:
        return None
    if (
        path == Path("/")
        or path != lexical
        or stat.S_ISLNK(metadata.st_mode)
        or not (
            stat.S_ISREG(metadata.st_mode)
            or stat.S_ISDIR(metadata.st_mode)
        )
    ):
        return None
    return path


def _g240_pinned_git_output(
    git_executable: Path,
    repository: Path,
    *arguments: str,
) -> bytes:
    """Run one read-only Git query with caller and repository config disabled."""

    try:
        completed = subprocess.run(
            [
                git_executable.as_posix(),
                "--no-replace-objects",
                "--no-pager",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.excludesFile=/dev/null",
                "-C",
                repository.as_posix(),
                *arguments,
            ],
            check=True,
            capture_output=True,
            timeout=20,
            stdin=subprocess.DEVNULL,
            env={
                "PATH": os.defpath,
                "GIT_CONFIG_COUNT": "0",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceRuntimeOrchestrationError(
            "cannot enumerate the frozen G240 source tree"
        ) from exc
    return completed.stdout


def _g240_parse_git_tree_entries(
    raw: bytes,
) -> tuple[tuple[str, str, str, bytes], ...]:
    entries: list[tuple[str, str, str, bytes]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        parts = metadata.split()
        if (
            not separator
            or len(parts) != 3
            or parts[0]
            not in {b"100644", b"100755", b"120000", b"160000"}
            or parts[1] not in {b"blob", b"commit"}
            or not raw_path
        ):
            raise SourceRuntimeOrchestrationError(
                "Git returned a malformed G240 source-tree entry"
            )
        try:
            mode = parts[0].decode("ascii")
            kind = parts[1].decode("ascii")
            object_id = parts[2].decode("ascii")
            logical = PurePosixPath(
                raw_path.decode("utf-8", errors="surrogateescape")
            )
        except UnicodeError as exc:
            raise SourceRuntimeOrchestrationError(
                "Git returned an undecodable G240 source-tree entry"
            ) from exc
        if (
            not _HEX_COMMIT.fullmatch(object_id)
            or logical.is_absolute()
            or ".." in logical.parts
            or "." in logical.parts
            or os.fsencode(logical.as_posix()) != raw_path
        ):
            raise SourceRuntimeOrchestrationError(
                "Git returned an unsafe G240 source-tree entry"
            )
        entries.append((mode, kind, object_id, raw_path))
    return tuple(entries)


def _g240_live_git_blob_oid(
    path: Path,
    metadata: os.stat_result,
    expected_oid: str,
) -> str:
    """Hash one no-follow descriptor using Git's raw blob preimage."""

    algorithm = (
        hashlib.sha1() if len(expected_oid) == 40 else hashlib.sha256()
    )
    algorithm.update(f"blob {metadata.st_size}\0".encode("ascii"))
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mode,
            )
            != (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mode,
            )
        ):
            return ""
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            algorithm.update(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mode,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mode,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            return ""
        observed_oid = algorithm.hexdigest()
        live = path.lstat()
        if (
            live.st_dev,
            live.st_ino,
            live.st_size,
            live.st_mode,
            live.st_mtime_ns,
            live.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mode,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            return ""
        return observed_oid
    except OSError:
        return ""
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _g240_relative_path_within(
    path: PurePosixPath,
    roots: frozenset[PurePosixPath],
) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _g240_authenticated_tree_files(
    *,
    repository: Path,
    commit: str,
    git_executable: Path,
    source_roots: Sequence[str],
    python_roots: Sequence[str] = (),
    tool_roots: Sequence[str] = (),
    exact_files: Sequence[str] = (),
) -> tuple[Path, ...]:
    """Select reviewed paths from a commit tree and authenticate live blobs."""

    if not _HEX_COMMIT.fullmatch(commit):
        raise SourceRuntimeOrchestrationError(
            "G240 reviewed source commit is invalid"
        )
    source = frozenset(PurePosixPath(value) for value in source_roots)
    python = frozenset(PurePosixPath(value) for value in python_roots)
    tools = frozenset(PurePosixPath(value) for value in tool_roots)
    exact = frozenset(PurePosixPath(value) for value in exact_files)
    pathspecs = tuple(
        sorted(
            {
                *(item.as_posix() for item in source),
                *(item.as_posix() for item in python),
                *(item.as_posix() for item in tools),
                *(item.as_posix() for item in exact),
            }
        )
    )
    tree = _g240_pinned_git_output(
        git_executable,
        repository,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        commit,
        "--",
        *pathspecs,
    )
    collected: set[Path] = set()
    for mode, kind, object_id, raw_path in _g240_parse_git_tree_entries(
        tree
    ):
        relative = PurePosixPath(
            raw_path.decode("utf-8", errors="surrogateescape")
        )
        selected = (
            relative in exact
            or _g240_relative_path_within(relative, tools)
            or (
                _g240_relative_path_within(relative, source)
                and relative.suffix.casefold() in {".py", ".so"}
            )
            or (
                _g240_relative_path_within(relative, python)
                and relative.suffix.casefold() == ".py"
            )
        )
        if not selected:
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise SourceRuntimeOrchestrationError(
                "reviewed G240 source is not a tracked regular Git blob"
            )
        path = repository / os.fsdecode(raw_path)
        try:
            metadata = path.lstat()
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise SourceRuntimeOrchestrationError(
                "reviewed G240 tracked source is missing"
            ) from exc
        if (
            resolved != path
            or not path.is_relative_to(repository)
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            raise SourceRuntimeOrchestrationError(
                "reviewed G240 tracked source is not one canonical regular "
                "file"
            )
        if (
            stat.S_IMODE(metadata.st_mode) & 0o022
            or bool(metadata.st_mode & 0o111) != (mode == "100755")
        ):
            raise SourceRuntimeOrchestrationError(
                "reviewed G240 tracked source mode differs from Git"
            )
        if (
            _g240_live_git_blob_oid(path, metadata, object_id)
            != object_id
        ):
            raise SourceRuntimeOrchestrationError(
                "reviewed G240 tracked source bytes differ from Git"
            )
        collected.add(path)
    return tuple(sorted(collected, key=Path.as_posix))


def _g240_landlock_source_files(
    worktree: WorktreeSafetyReceipt,
    *,
    git_executable_path: str,
    git_executable_cid: str,
) -> tuple[Path, ...]:
    """Authenticate reviewed code against frozen outer and submodule trees."""

    if not isinstance(worktree, WorktreeSafetyReceipt):
        raise SourceRuntimeOrchestrationError(
            "reviewed G240 sources require a typed worktree receipt"
        )
    git_executable, observed_git_cid = _git_executable_identity_v2(
        git_executable_path
    )
    if observed_git_cid != git_executable_cid:
        raise SourceRuntimeOrchestrationError(
            "pinned Git executable changed before source enumeration"
        )
    root = worktree.worktree_root
    collected = set(
        _g240_authenticated_tree_files(
            repository=root,
            commit=worktree.worktree_commit,
            git_executable=git_executable,
            source_roots=(
                "benchmarks/logic_pipeline",
                "ipfs_datasets_py/logic",
                "ipfs_datasets_py/optimizers/logic_theorem_optimizer",
                "ipfs_datasets_py/optimizers/common",
                "ipfs_datasets_py/knowledge_graphs/extraction",
            ),
            python_roots=("spacy", "en_core_web_sm"),
            tool_roots=("test-bin",),
            exact_files=(
                "benchmarks/__init__.py",
                "ipfs_datasets_py/__init__.py",
                "ipfs_datasets_py/logic/__init__.py",
                "ipfs_datasets_py/optimizers/__init__.py",
                "ipfs_datasets_py/knowledge_graphs/__init__.py",
                "ipfs_datasets_py/llm_router.py",
                "ipfs_datasets_py/router_deps.py",
                "ipfs_datasets_py/utils/__init__.py",
                "ipfs_datasets_py/utils/symai_ipfs_engine.py",
            ),
        )
    )
    submodule_commit = worktree.submodule_commits.get(
        "ipfs_accelerate_py"
    )
    if submodule_commit is not None:
        submodule = root / "ipfs_accelerate_py"
        try:
            metadata = submodule.lstat()
            resolved = submodule.resolve(strict=True)
        except OSError as exc:
            raise SourceRuntimeOrchestrationError(
                "pinned ipfs_accelerate_py submodule is not initialized"
            ) from exc
        if (
            resolved != submodule
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or _g240_pinned_git_output(
                git_executable,
                submodule,
                "rev-parse",
                "--show-toplevel",
            ).decode("utf-8").strip()
            != submodule.as_posix()
            or _g240_pinned_git_output(
                git_executable,
                submodule,
                "rev-parse",
                "--verify",
                "HEAD^{commit}",
            ).decode("ascii").strip()
            != submodule_commit
        ):
            raise SourceRuntimeOrchestrationError(
                "initialized ipfs_accelerate_py differs from its Gitlink"
            )
        collected.update(
            _g240_authenticated_tree_files(
                repository=submodule,
                commit=submodule_commit,
                git_executable=git_executable,
                source_roots=("ipfs_accelerate_py/agent_supervisor",),
                exact_files=("ipfs_accelerate_py/__init__.py",),
            )
        )
    if not collected:
        raise SourceRuntimeOrchestrationError(
            "reviewed G240 tracked-source allowlist is empty"
        )
    return tuple(sorted(collected, key=Path.as_posix))


def _g240_inventory_tool_paths(
    request: G240ExecutionRequestV2,
) -> tuple[Path, ...]:
    if request.adapter_factory_id == G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2:
        return ()
    inventory = CapabilityInventory.from_dict(
        request.adapter_configuration["capability_inventory"]
    )
    paths: set[Path] = set()

    def visit(value: object, key: str | None = None) -> None:
        if isinstance(value, Mapping):
            for child_key, member in value.items():
                visit(member, str(child_key))
            return
        if isinstance(value, (tuple, list)):
            for member in value:
                visit(member, key)
            return
        if (
            isinstance(value, str)
            and key is not None
            and (
                key == "path"
                or key.endswith("_path")
                or key == "executable"
            )
            and Path(value).is_absolute()
        ):
            observed = _g240_landlock_regular_or_directory(value)
            requested = Path(value)
            if (
                observed is None
                and (requested.exists() or requested.is_symlink())
            ):
                raise SourceRuntimeOrchestrationError(
                    "G240 inventory tool path is not one canonical physical "
                    "file"
                )
            if observed is not None and observed.is_file():
                paths.add(observed)

    visit(inventory.to_dict())
    # A script tool's kernel-selected interpreter is a separate executable.
    for tool in tuple(paths):
        try:
            first_line = tool.read_bytes()[:256].splitlines()[0]
        except (OSError, IndexError):
            continue
        if first_line.startswith(b"#!"):
            interpreter = first_line[2:].strip().split(maxsplit=1)[0]
            try:
                decoded = interpreter.decode("utf-8")
            except UnicodeError:
                continue
            observed = _g240_landlock_regular_or_directory(decoded)
            if observed is not None and observed.is_file():
                paths.add(observed)
    return tuple(sorted(paths, key=Path.as_posix))


def _g240_path_within(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def _g240_protected_path_component(value: str) -> bool:
    normalized = value.casefold()
    stem = Path(normalized).stem
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", stem)
        if token
    }
    protected_tokens = {
        "fixture",
        "fixtures",
        "corpus",
        "corpora",
        "manifest",
        "manifests",
        "holdout",
        "holdouts",
    }
    return bool(
        tokens & protected_tokens
        or stem in {"performance_snapshots", "agent_supervisor"}
    )


def _g240_validate_dynamic_read_path(
    path: Path,
    *,
    worktree: WorktreeSafetyReceipt,
    reviewed_worktree_files: frozenset[Path],
    field: str,
) -> Path:
    """Reject dynamic grants into Git, benchmark data, or sensitive roots."""

    if path != path.resolve(strict=True) or not path.is_file():
        raise SourceRuntimeOrchestrationError(
            f"{field} must be one canonical physical regular file"
        )
    worktree_root = worktree.worktree_root
    source_root = worktree.source_checkout
    forbidden_roots = (
        worktree.source_git_common_dir,
        worktree_root / ".git",
        source_root / ".git",
        worktree_root / "tests" / "fixtures",
        worktree_root / "docs" / "performance_snapshots",
        worktree_root / "data" / "agent_supervisor",
        source_root / "tests" / "fixtures",
        source_root / "docs" / "performance_snapshots",
        source_root / "data" / "agent_supervisor",
        Path("/proc"),
        Path("/sys"),
        Path("/dev"),
        Path("/etc"),
        Path("/root"),
    )
    protected_component = any(
        part.casefold() in {".git", ".ssh", ".gnupg"}
        or _g240_protected_path_component(part)
        for part in path.parts
    )
    if (
        protected_component
        or any(
            _g240_path_within(path, root)
            for root in forbidden_roots
        )
        or _g240_path_within(path, source_root)
        or (
            _g240_path_within(path, worktree_root)
            and path not in reviewed_worktree_files
        )
    ):
        raise SourceRuntimeOrchestrationError(
            f"{field} targets a forbidden Git, protected-data, or sensitive "
            "path"
        )
    return path


def _g240_runtime_read_only_paths(
    *,
    worktree: WorktreeSafetyReceipt,
    contract: G240SourceExecutorContractV2,
    request: G240ExecutionRequestV2,
) -> tuple[Path, ...]:
    """Build the reviewed code/runtime allowlist without Git or corpus roots."""

    try:
        probe = subprocess.run(
            [
                contract.interpreter_path,
                "-I",
                "-c",
                _G240_LANDLOCK_RUNTIME_PROBE,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
            close_fds=True,
            env={
                "PATH": os.defpath,
                "LC_ALL": "C",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "PYTHONSAFEPATH": "1",
            },
        )
        runtime = _mapping(
            json.loads(probe.stdout),
            "G240 Landlock interpreter runtime",
        )
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise SourceRuntimeOrchestrationError(
            "cannot derive the pinned interpreter Landlock roots"
        ) from exc
    if set(runtime) != {
        "prefix",
        "base_prefix",
        "stdlib",
        "platstdlib",
        "site_packages",
    } or not isinstance(runtime["site_packages"], list):
        raise SourceRuntimeOrchestrationError(
            "pinned interpreter Landlock probe changed"
        )
    reviewed_worktree_files = frozenset(
        _g240_landlock_source_files(
            worktree,
            git_executable_path=contract.git_executable_path,
            git_executable_cid=contract.git_executable_cid,
        )
    )
    candidates: set[Path] = set(reviewed_worktree_files)
    for tool_path in _g240_inventory_tool_paths(request):
        candidates.add(
            _g240_validate_dynamic_read_path(
                tool_path,
                worktree=worktree,
                reviewed_worktree_files=reviewed_worktree_files,
                field="G240 capability-inventory tool",
            )
        )
    for descriptor in contract.runtime_environment_artifacts.values():
        observed = _g240_landlock_regular_or_directory(
            descriptor["path"]
        )
        if observed is None or not observed.is_file():
            raise SourceRuntimeOrchestrationError(
                "G240 runtime artifact is not one canonical physical file"
            )
        candidates.add(
            _g240_validate_dynamic_read_path(
                observed,
                worktree=worktree,
                reviewed_worktree_files=reviewed_worktree_files,
                field="G240 runtime artifact",
            )
        )
    for value in (
        Path(contract.interpreter_path).resolve(strict=True),
        runtime["stdlib"],
        runtime["platstdlib"],
        *runtime["site_packages"],
        "/usr/lib",
        "/usr/lib64",
        "/lib",
        "/lib64",
        "/usr/share/locale",
        "/etc/ssl/certs",
        "/etc/hosts",
        "/etc/resolv.conf",
        "/etc/nsswitch.conf",
        "/etc/ld.so.cache",
    ):
        observed = _g240_landlock_regular_or_directory(value)
        if observed is not None:
            candidates.add(observed)
    if not candidates:
        raise SourceRuntimeOrchestrationError(
            "G240 production Landlock read-only allowlist is empty"
        )
    forbidden_roots = {
        worktree.worktree_root,
        worktree.source_git_common_dir,
        worktree.source_checkout,
    }
    if any(path in forbidden_roots for path in candidates):
        raise SourceRuntimeOrchestrationError(
            "G240 Landlock may not grant a source or Git root"
        )
    return tuple(sorted(candidates, key=Path.as_posix))


def _g240_landlock_sources_for_job(
    *,
    worktree: WorktreeSafetyReceipt,
    contract: G240SourceExecutorContractV2,
    request: G240ExecutionRequestV2,
    state_path: Path,
    output_path: Path,
    cache_paths: Sequence[Path],
) -> G240LandlockPrivatePolicySourcesV1:
    """Create the strict per-job production policy after directories exist."""

    return build_g240_landlock_policy_v1(
        read_only_paths=_g240_runtime_read_only_paths(
            worktree=worktree,
            contract=contract,
            request=request,
        ),
        state_path=state_path,
        output_path=output_path,
        cache_paths=tuple(cache_paths),
        approved_tcp_ports=G240_APPROVED_TCP_DESTINATION_PORTS_V2,
    )


def run_g240_source_job_v2(
    *,
    policy: G240NamespacePolicyV2,
    plan: AblationPlan,
    job: ScheduledCase,
    worktree_safety_receipt: WorktreeSafetyReceipt,
    namespace_root: str | Path,
    executor_contract: G240SourceExecutorContractV2,
    execution_request: G240ExecutionRequestV2,
    namespace_observer_identity_cid: str,
    orchestration_observer_identity_cid: str,
    timeout_seconds: float,
    cancellation_grace_seconds: float = 2.0,
    environment: Mapping[str, str] | None = None,
    _test_only_synthetic_capability: object | None = None,
) -> G240SourceExecutionResultV2:
    """Execute one exact source job and emit source-recomputed G240 proof."""

    restored, _plan_cid_value, coordinate = _coerce_policy_coordinate(
        policy, plan, job
    )
    extra_environment = _validate_environment(environment)
    worktree = _validate_live_worktree(
        worktree_safety_receipt, restored
    )
    contract = _coerce_source_executor_contract(
        executor_contract,
        policy=restored,
        plan=plan,
        worktree=worktree,
    )
    request = _coerce_source_execution_request(
        execution_request,
        policy=restored,
        plan=plan,
        job=job,
        coordinate=coordinate,
        worktree=worktree,
        contract=contract,
    )
    synthetic = (
        request.adapter_factory_id
        == G240_SYNTHETIC_ADAPTER_FACTORY_ID_V2
    )
    if (
        synthetic
        and _test_only_synthetic_capability
        is not _G240_SYNTHETIC_TEST_CAPABILITY_V2
    ):
        raise SourceRuntimeOrchestrationError(
            "synthetic G240 execution requires the private test-only "
            "capability"
        )
    if (
        not synthetic
        and _test_only_synthetic_capability is not None
    ):
        raise SourceRuntimeOrchestrationError(
            "test-only synthetic capability cannot authorize live execution"
        )
    arguments = _g240_launch_arguments(contract)
    root = _validate_namespace_root(namespace_root, worktree)
    # Every logical and physical namespace is derived before the first write.
    _physical_namespace_paths(
        namespace_root=root,
        policy=restored,
        coordinate=coordinate,
    )
    physical = _materialize_physical_namespaces(
        namespace_root=root,
        policy=restored,
        coordinate=coordinate,
    )
    _write_exclusive_canonical(
        physical.execution_request,
        request.to_dict(),
    )
    _observed_request, execution_request_payload = _read_canonical_json(
        physical.execution_request,
        "G240 private execution request",
    )
    landlock_sources = (
        None
        if synthetic
        else _g240_landlock_sources_for_job(
            worktree=worktree,
            contract=contract,
            request=request,
            state_path=physical.state,
            output_path=physical.output,
            cache_paths=tuple(physical.caches.values()),
        )
    )
    private_policy_input = (
        None
        if landlock_sources is None
        else canonical_dag_json_bytes(
            g240_private_landlock_policy_payload_v2(
                landlock_sources
            )
        )
        + b"\n"
    )
    receipt_read_descriptor: int | None = None
    receipt_write_descriptor: int | None = None
    cache_paths = {
        stage: physical.caches[stage].as_posix()
        for stage in coordinate.stages
    }
    process_environment = {
        "PATH": os.defpath,
        "PYTHONPATH": worktree.worktree_root.as_posix(),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        **extra_environment,
        "HSSL_G240_RUN_ID": restored.run_id,
        "HSSL_G240_PLAN_CID": coordinate.plan_cid,
        "HSSL_G240_JOB_ID": coordinate.job_id,
        "HSSL_G240_COORDINATE_CID": str(
            coordinate.coordinate_cid
        ),
        "HSSL_G240_PROCESS_NAMESPACE_CID": (
            coordinate.process_namespace_cid
        ),
        "HSSL_G240_STATE_DIR": physical.state.as_posix(),
        "HSSL_G240_STATE_NAMESPACE_CID": (
            coordinate.state_namespace_cid
        ),
        "HSSL_G240_OUTPUT_DIR": physical.output.as_posix(),
        "HSSL_G240_OUTPUT_NAMESPACE_CID": (
            coordinate.output_namespace_cid
        ),
        "HSSL_G240_EVIDENCE_PATH": physical.evidence.as_posix(),
        "HSSL_G240_EXECUTION_REQUEST_PATH": (
            physical.execution_request.as_posix()
        ),
        "HSSL_G240_EXECUTION_REQUEST_CID": str(request.request_cid),
        "HSSL_G240_ENVIRONMENT_CID": contract.environment_cid,
        "HSSL_G240_ENVIRONMENT_SHA256": (
            contract.environment_sha256
        ),
        "HSSL_G240_CACHE_ROOTS_JSON": (
            canonical_dag_json_bytes(cache_paths).decode("utf-8")
        ),
        "HSSL_G240_CACHE_NAMESPACE_CIDS_JSON": (
            canonical_dag_json_bytes(
                dict(coordinate.cache_namespace_cids)
            ).decode("utf-8")
        ),
        "HSSL_G240_GIT_EXECUTABLE_PATH": (
            contract.git_executable_path
        ),
        "HSSL_G240_GIT_EXECUTABLE_CID": (
            contract.git_executable_cid
        ),
        "HSSL_G240_CONFINEMENT_PROFILE_CID": (
            contract.confinement_profile_cid
        ),
        "HSSL_G240_EXPECTED_SOURCE_COMMIT": request.source_commit,
    }
    landlock_receipt: G240LandlockReceiptV1 | None = None
    landlock_receipt_payload: bytes | None = None
    landlock_transport_observation: (
        _G240LandlockTransportObservationV2 | None
    ) = None
    try:
        if synthetic:
            process_environment[
                _G240_SYNTHETIC_TEST_ENVIRONMENT_KEY_V2
            ] = str(request.request_cid)
        else:
            try:
                (
                    receipt_read_descriptor,
                    receipt_write_descriptor,
                ) = os.pipe2(os.O_CLOEXEC)
            except OSError as exc:
                raise SourceRuntimeOrchestrationError(
                    "cannot create the dedicated G240 Landlock receipt pipe"
                ) from exc
            process_environment["HSSL_G240_LANDLOCK_RECEIPT_FD"] = str(
                receipt_write_descriptor
            )
        try:
            process = run_bounded_process_group(
                arguments,
                timeout_seconds=timeout_seconds,
                cancellation_grace_seconds=cancellation_grace_seconds,
                cwd=worktree.worktree_root,
                env=process_environment,
                input_bytes=private_policy_input,
                pass_fds=(
                    ()
                    if receipt_write_descriptor is None
                    else (receipt_write_descriptor,)
                ),
            )
        finally:
            if receipt_write_descriptor is not None:
                os.close(receipt_write_descriptor)
                receipt_write_descriptor = None
        if (
            process.returncode != 0
            or process.timed_out
            or not process.process_group_reaped
        ):
            raise SourceRuntimeOrchestrationError(
                "G240 source command failed its bounded process contract: "
                f"{process.termination_reason}"
            )
        process_observation = _observe_g240_source_process_v2(
            process,
            contract,
        )
        if landlock_sources is not None:
            assert receipt_read_descriptor is not None
            owned_read_descriptor = receipt_read_descriptor
            receipt_read_descriptor = None
            (
                landlock_receipt,
                landlock_receipt_payload,
            ) = _read_g240_landlock_receipt_pipe(
                owned_read_descriptor,
                expected_policy=landlock_sources.policy,
            )
            landlock_transport_observation = (
                _G240LandlockTransportObservationV2(
                    process_observation=process_observation,
                    policy_sources=landlock_sources,
                    receipt=landlock_receipt,
                    receipt_payload=landlock_receipt_payload,
                    close_fds=True,
                    passed_descriptor_count=1,
                    one_shot_atomic_frame=True,
                    _capability=(
                        _G240_LANDLOCK_TRANSPORT_CAPABILITY_V2
                    ),
                )
            )
        elif receipt_read_descriptor is not None:
            raise SourceRuntimeOrchestrationError(
                "synthetic G240 execution unexpectedly created a receipt pipe"
            )
    finally:
        if receipt_write_descriptor is not None:
            os.close(receipt_write_descriptor)
        if receipt_read_descriptor is not None:
            os.close(receipt_read_descriptor)
    preflight_value, runtime_preflight_payload = _read_canonical_json(
        physical.runtime_preflight,
        "G240 runtime import preflight",
    )
    _runtime_preflight_cid, _bootstrap_receipt = (
        _validate_runtime_preflight(
        preflight_value,
        request=request,
        contract=contract,
        landlock_sources=landlock_sources,
        landlock_receipt=landlock_receipt,
        expected_gitlink_commit=worktree.submodule_commits.get(
            "ipfs_accelerate_py"
        ),
        )
    )
    value, payload = _read_canonical_json(
        physical.evidence,
        "G240 source runtime evidence",
    )
    try:
        runtime = validate_causal_runtime_evidence_v2(value)
    except (TypeError, ValueError) as exc:
        raise SourceRuntimeOrchestrationError(
            "G240 source command emitted invalid causal runtime evidence"
        ) from exc
    _validate_runtime_coordinate(
        runtime,
        plan=plan,
        job=job,
        launch_environment_sha256=contract.environment_sha256,
    )
    try:
        runtime = validate_g240_runtime_for_execution_request_v2(
            runtime, request
        )
    except (G240SourceExecutorError, TypeError, ValueError) as exc:
        raise SourceRuntimeOrchestrationError(
            "G240 source runtime differs from its execution request"
        ) from exc
    try:
        namespace_receipt = G240RuntimeNamespaceReceiptV2.create(
            policy=restored,
            plan=plan,
            job=job,
            evidence=runtime,
            executor_identity_cid=contract.executor_identity_cid,
            observer_identity_cid=namespace_observer_identity_cid,
            process_group_started=True,
            process_group_reaped=process.process_group_reaped,
            active_process_count_after_reap=0,
            state_namespace_created_exclusive=True,
            state_namespace_finalized=True,
            output_namespace_created_exclusive=True,
            output_namespace_finalized=True,
            cache_namespaces_mounted=True,
            holdout_accessed=False,
        )
    except (
        RuntimeNamespaceProvenanceError,
        TypeError,
        ValueError,
    ) as exc:
        raise SourceRuntimeOrchestrationError(
            "G240 source runtime namespace receipt failed"
        ) from exc
    # Revalidate Git after the process so a command cannot dirty its source.
    _validate_live_worktree(worktree, restored)
    orchestration = _build_g240_source_orchestration_receipt_v2(
        policy=restored,
        plan=plan,
        job=job,
        worktree_safety_receipt=worktree,
        namespace_root=root,
        runtime_evidence=runtime,
        runtime_namespace_receipt=namespace_receipt,
        executor_contract=contract,
        execution_request=request,
        execution_request_payload=execution_request_payload,
        runtime_preflight_payload=runtime_preflight_payload,
        evidence_payload=payload,
        process_observation=process_observation,
        landlock_transport_observation=(
            landlock_transport_observation
        ),
        orchestration_observer_identity_cid=(
            orchestration_observer_identity_cid
        ),
        cache_namespace_created_exclusive=(
            physical.cache_created_exclusive
        ),
    )
    sources = G240PrivateSourceValidationSourcesV2(
        policy=restored,
        plan=plan,
        job=job,
        worktree_safety_receipt=worktree,
        namespace_root=root,
        runtime_evidence=runtime,
        runtime_namespace_receipt=namespace_receipt,
        executor_contract=contract,
        execution_request=request,
        orchestration_receipt=orchestration,
        execution_request_payload=execution_request_payload,
        runtime_preflight_payload=runtime_preflight_payload,
        evidence_payload=payload,
        process_result=process,
        process_observation=process_observation,
        landlock_transport_observation=(
            landlock_transport_observation
        ),
        cache_namespace_created_exclusive=(
            physical.cache_created_exclusive
        ),
    )
    validate_g240_private_source_sources_v2(sources)
    return G240SourceExecutionResultV2(
        runtime_evidence=runtime,
        runtime_namespace_receipt=namespace_receipt,
        orchestration_receipt=orchestration,
        validation_sources=sources,
        process_result=process,
    )


@dataclass(frozen=True, slots=True)
class G240SourceOrchestrationEvidenceSetV2:
    """Complete path-free source orchestration receipts for G211."""

    policy_cid: str
    runtime_namespace_evidence_set_cid: str
    plan_cids: tuple[str, ...]
    receipts: tuple[G240SourceOrchestrationReceiptV2, ...]
    validator_identity_cid: str
    complete: bool
    holdout_included: bool
    schema: str = G240_SOURCE_ORCHESTRATION_EVIDENCE_SET_SCHEMA_V2
    evidence_set_cid: str | None = None

    def __post_init__(self) -> None:
        if (
            self.schema
            != G240_SOURCE_ORCHESTRATION_EVIDENCE_SET_SCHEMA_V2
        ):
            raise SourceRuntimeOrchestrationError(
                "unsupported G240 source evidence-set schema"
            )
        object.__setattr__(
            self, "policy_cid", _cid(self.policy_cid, "policy_cid")
        )
        object.__setattr__(
            self,
            "runtime_namespace_evidence_set_cid",
            _cid(
                self.runtime_namespace_evidence_set_cid,
                "runtime_namespace_evidence_set_cid",
            ),
        )
        plans = tuple(_cid(value, "plan_cid") for value in self.plan_cids)
        if (
            not plans
            or plans != tuple(sorted(plans))
            or len(plans) != len(set(plans))
        ):
            raise SourceRuntimeOrchestrationError(
                "source orchestration plan CIDs must be sorted and unique"
            )
        object.__setattr__(self, "plan_cids", plans)
        receipts = tuple(
            item
            if isinstance(item, G240SourceOrchestrationReceiptV2)
            else G240SourceOrchestrationReceiptV2.from_dict(item)
            for item in self.receipts
        )
        order = tuple(
            (item.plan_cid, item.job_id) for item in receipts
        )
        if (
            not receipts
            or order != tuple(sorted(order))
            or len(order) != len(set(order))
            or any(
                item.policy_cid != self.policy_cid
                or item.plan_cid not in plans
                for item in receipts
            )
        ):
            raise SourceRuntimeOrchestrationError(
                "source orchestration receipts are incomplete or foreign"
            )
        object.__setattr__(self, "receipts", receipts)
        validator = _cid(
            self.validator_identity_cid, "validator_identity_cid"
        )
        object.__setattr__(self, "validator_identity_cid", validator)
        authorities = {
            validator,
            *(
                receipt.executor_identity_cid
                for receipt in receipts
            ),
            *(
                receipt.namespace_observer_identity_cid
                for receipt in receipts
            ),
            *(
                receipt.orchestration_observer_identity_cid
                for receipt in receipts
            ),
        }
        expected_count = (
            1
            + len(
                {
                    receipt.executor_identity_cid
                    for receipt in receipts
                }
            )
            + len(
                {
                    receipt.namespace_observer_identity_cid
                    for receipt in receipts
                }
            )
            + len(
                {
                    receipt.orchestration_observer_identity_cid
                    for receipt in receipts
                }
            )
        )
        if len(authorities) != expected_count:
            raise SourceRuntimeOrchestrationError(
                "source executor/observer/validator authorities overlap"
            )
        if self.complete is not True or self.holdout_included is not False:
            raise SourceRuntimeOrchestrationError(
                "source orchestration evidence must be complete/non-holdout"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.evidence_set_cid is None:
            object.__setattr__(self, "evidence_set_cid", expected)
        elif _cid(self.evidence_set_cid, "evidence_set_cid") != expected:
            raise SourceRuntimeOrchestrationError(
                "source orchestration evidence-set CID changed"
            )

    @property
    def receipt_map(
        self,
    ) -> Mapping[tuple[str, str], G240SourceOrchestrationReceiptV2]:
        return MappingProxyType(
            {
                (item.plan_cid, item.job_id): item
                for item in self.receipts
            }
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "policy_cid": self.policy_cid,
            "runtime_namespace_evidence_set_cid": (
                self.runtime_namespace_evidence_set_cid
            ),
            "plan_cids": list(self.plan_cids),
            "receipts": [item.to_dict() for item in self.receipts],
            "validator_identity_cid": self.validator_identity_cid,
            "complete": self.complete,
            "holdout_included": self.holdout_included,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "evidence_set_cid": self.evidence_set_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(
            value, "G240 source orchestration evidence set"
        )
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G240 source orchestration evidence set",
        )
        raw_plans = data["plan_cids"]
        raw_receipts = data["receipts"]
        if not isinstance(raw_plans, list) or not isinstance(
            raw_receipts, list
        ):
            raise SourceRuntimeOrchestrationError(
                "source orchestration plan/receipt fields must be arrays"
            )
        return cls(
            **{
                **data,
                "plan_cids": tuple(raw_plans),
                "receipts": tuple(
                    G240SourceOrchestrationReceiptV2.from_dict(item)
                    for item in raw_receipts
                ),
            }
        )  # type: ignore[arg-type]


def build_g240_source_orchestration_evidence_set_v2(
    runtime_namespace_evidence_set: G240RuntimeNamespaceEvidenceSetV2,
    validation_sources: Sequence[
        G240PrivateSourceValidationSourcesV2
    ],
    *,
    validator_identity_cid: str,
) -> G240SourceOrchestrationEvidenceSetV2:
    """Validate every live source execution and require full G240 coverage."""

    sources = tuple(validation_sources)
    if not sources:
        raise SourceRuntimeOrchestrationError(
            "source orchestration validation sources must not be empty"
        )
    plans: dict[str, AblationPlan] = {}
    evidence: dict[tuple[str, str], CausalRuntimeEvidenceV2] = {}
    rebuilt_receipts: list[G240SourceOrchestrationReceiptV2] = []
    restored_policy: G240NamespacePolicyV2 | None = None
    for source in sources:
        policy, _namespace_receipt, orchestration = (
            validate_g240_private_source_sources_v2(source)
        )
        if (
            restored_policy is not None
            and policy.to_dict() != restored_policy.to_dict()
        ):
            raise SourceRuntimeOrchestrationError(
                "source orchestration sources use different policies"
            )
        restored_policy = policy
        plan_cid = _plan_cid(source.plan)
        existing = plans.setdefault(plan_cid, source.plan)
        if existing != source.plan:
            raise SourceRuntimeOrchestrationError(
                "source orchestration plan CID collision"
            )
        key = (plan_cid, source.job.job_id)
        if key in evidence:
            raise SourceRuntimeOrchestrationError(
                "duplicate source orchestration coordinate"
            )
        evidence[key] = source.runtime_evidence
        rebuilt_receipts.append(orchestration)
    assert restored_policy is not None
    try:
        namespace_set = (
            runtime_namespace_evidence_set
            if isinstance(
                runtime_namespace_evidence_set,
                G240RuntimeNamespaceEvidenceSetV2,
            )
            else G240RuntimeNamespaceEvidenceSetV2.from_dict(
                runtime_namespace_evidence_set
            )
        )
        namespace_set = validate_g240_runtime_namespace_evidence_set_v2(
            namespace_set,
            plans=tuple(plans[key] for key in sorted(plans)),
            evidence_by_plan_and_job=evidence,
        )
    except (
        RuntimeNamespaceProvenanceError,
        TypeError,
        ValueError,
    ) as exc:
        raise SourceRuntimeOrchestrationError(
            "runtime namespace evidence set failed source replay"
        ) from exc
    expected_keys = set(namespace_set.receipt_map)
    actual_keys = {
        (item.plan_cid, item.job_id)
        for item in rebuilt_receipts
    }
    if (
        namespace_set.policy.to_dict() != restored_policy.to_dict()
        or actual_keys != expected_keys
    ):
        raise SourceRuntimeOrchestrationError(
            "source orchestration population differs from G240 runtime "
            "namespace evidence"
        )
    return G240SourceOrchestrationEvidenceSetV2(
        policy_cid=str(restored_policy.policy_cid),
        runtime_namespace_evidence_set_cid=str(
            namespace_set.evidence_set_cid
        ),
        plan_cids=tuple(sorted(plans)),
        receipts=tuple(
            sorted(
                rebuilt_receipts,
                key=lambda item: (item.plan_cid, item.job_id),
            )
        ),
        validator_identity_cid=validator_identity_cid,
        complete=True,
        holdout_included=False,
    )


def validate_g240_source_orchestration_evidence_set_v2(
    value: object,
    *,
    runtime_namespace_evidence_set: G240RuntimeNamespaceEvidenceSetV2,
    validation_sources: Sequence[
        G240PrivateSourceValidationSourcesV2
    ],
) -> G240SourceOrchestrationEvidenceSetV2:
    """Rebuild a source orchestration evidence set from private sources."""

    receipt = (
        value
        if isinstance(value, G240SourceOrchestrationEvidenceSetV2)
        else G240SourceOrchestrationEvidenceSetV2.from_dict(value)
    )
    rebuilt = build_g240_source_orchestration_evidence_set_v2(
        runtime_namespace_evidence_set,
        validation_sources,
        validator_identity_cid=receipt.validator_identity_cid,
    )
    if _plain(receipt.to_dict()) != _plain(rebuilt.to_dict()):
        raise SourceRuntimeOrchestrationError(
            "source orchestration evidence set did not source-recompute"
        )
    return rebuilt


__all__ = [
    "G240_GIT_COMMIT_IDENTITY_SCHEMA_V2",
    "G240_INTERPRETER_IDENTITY_SCHEMA_V2",
    "G240_SOURCE_CACHE_MARKER_SCHEMA_V2",
    "G240_SOURCE_COMMAND_PROJECTION_SCHEMA_V2",
    "G240_SOURCE_EXECUTOR_CONTRACT_SCHEMA_V2",
    "G240_SOURCE_ORCHESTRATION_EVIDENCE_SET_SCHEMA_V2",
    "G240_SOURCE_ORCHESTRATION_RECEIPT_SCHEMA_V2",
    "G240_SOURCE_PHYSICAL_NAMESPACE_SCHEMA_V2",
    "G240_SOURCE_RUNTIME_ENVIRONMENT_PROJECTION_SCHEMA_V2",
    "G240PrivateSourceValidationSourcesV2",
    "G240SourceExecutorContractV2",
    "G240SourceExecutionResultV2",
    "G240SourceOrchestrationEvidenceSetV2",
    "G240SourceOrchestrationReceiptV2",
    "HSSLEV2405D72",
    "SourceRuntimeOrchestrationError",
    "build_g240_source_orchestration_evidence_set_v2",
    "build_g240_source_executor_contract_v2",
    "g240_source_git_commit_cid",
    "run_g240_source_job_v2",
    "validate_g240_private_source_sources_v2",
    "validate_g240_source_orchestration_evidence_set_v2",
]
