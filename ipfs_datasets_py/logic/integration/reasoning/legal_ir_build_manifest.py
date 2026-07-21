"""Reproducible build manifests for LegalIR compiler outputs.

The build manifest is the compiler-ops envelope around pass-manager replay
records.  It records only deterministic data: source/content digests, compiler
commit, schema versions, pass graph, model/export bindings, proof tool versions,
runtime configuration, cache digests, output digests, and a replay command that
can be persisted in build artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final

from .legal_ir_pass_manager import (
    LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION,
    LEGAL_IR_PASS_REPLAY_SCHEMA_VERSION,
    LegalIRPassManager,
    LegalIRPassRun,
)
from .legal_ir_schema_evolution import (
    LEGAL_IR_SCHEMA_EVOLUTION_REGISTRY_VERSION,
    LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION,
    known_legal_ir_schema_versions,
)


LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION: Final = "legal-ir-build-manifest-v1"
DEFAULT_LEGAL_IR_BUILD_MANIFEST_PATH: Final = "legal-ir-build-manifest.json"
LEGAL_IR_BUILD_REPLAY_MODULE: Final = (
    "ipfs_datasets_py.logic.integration.reasoning.legal_ir_build_manifest"
)


class LegalIRBuildManifestError(ValueError):
    """Raised when a LegalIR build manifest is malformed or not reproducible."""


class LegalIRBuildDiagnosticSeverity(str, Enum):
    """Validation severity for build manifest diagnostics."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class LegalIRBuildDiagnostic:
    """One deterministic build-manifest diagnostic."""

    code: str
    message: str
    field_path: str = ""
    severity: str = LegalIRBuildDiagnosticSeverity.ERROR.value
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def error(self) -> bool:
        return str(self.severity or "").lower() == LegalIRBuildDiagnosticSeverity.ERROR.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field_path": self.field_path,
            "message": self.message,
            "metadata": _json_ready(self.metadata),
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRBuildDiagnostic":
        return cls(
            code=str(data.get("code") or ""),
            message=str(data.get("message") or ""),
            field_path=str(data.get("field_path") or ""),
            severity=str(data.get("severity") or LegalIRBuildDiagnosticSeverity.ERROR.value),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRBuildDigest:
    """Digest-bound source, cache, model/export, or output artifact."""

    artifact_id: str
    sha256: str
    role: str
    byte_length: int = 0
    path: str = ""
    media_type: str = ""
    schema_version: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        digest = _normalize_sha256(self.sha256)
        if not digest:
            raise LegalIRBuildManifestError(f"{self.role or 'artifact'} digest is missing")
        if not self.artifact_id:
            raise LegalIRBuildManifestError(f"{self.role or 'artifact'} id is missing")
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "byte_length", max(0, int(self.byte_length or 0)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "byte_length": int(self.byte_length),
            "media_type": self.media_type,
            "metadata": _json_ready(self.metadata),
            "path": self.path,
            "role": self.role,
            "schema_version": self.schema_version,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, default_role: str = "") -> "LegalIRBuildDigest":
        return cls(
            artifact_id=str(
                data.get("artifact_id")
                or data.get("source_id")
                or data.get("cache_id")
                or data.get("output_id")
                or data.get("id")
                or ""
            ),
            sha256=str(data.get("sha256") or data.get("digest") or data.get("content_sha256") or ""),
            role=str(data.get("role") or default_role or "artifact"),
            byte_length=int(data.get("byte_length") or data.get("size") or 0),
            path=str(data.get("path") or ""),
            media_type=str(data.get("media_type") or data.get("content_type") or ""),
            schema_version=str(data.get("schema_version") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRBuildManifestValidationResult:
    """Validation result for a persisted LegalIR build manifest."""

    build_id: str
    diagnostics: tuple[LegalIRBuildDiagnostic, ...] = ()
    schema_version: str = LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION

    @property
    def valid(self) -> bool:
        return not any(diagnostic.error for diagnostic in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_id": self.build_id,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "schema_version": self.schema_version,
            "valid": self.valid,
        }


@dataclass(frozen=True)
class LegalIRBuildManifest:
    """Deterministic manifest binding one LegalIR compiler build."""

    build_id: str
    compiler_commit: str
    source_digests: tuple[LegalIRBuildDigest, ...]
    schema_versions: Mapping[str, Any]
    pass_graph: Mapping[str, Any]
    model_export_ids: tuple[Mapping[str, Any], ...] = ()
    proof_tool_versions: tuple[Mapping[str, Any], ...] = ()
    runtime_configuration: Mapping[str, Any] = field(default_factory=dict)
    cache_digests: tuple[LegalIRBuildDigest, ...] = ()
    output_digests: tuple[LegalIRBuildDigest, ...] = ()
    input_digest: str = ""
    output_digest: str = ""
    pass_replay_digest: str = ""
    deterministic_replay_command: tuple[str, ...] = ()
    replay_command: str = ""
    diagnostics: tuple[LegalIRBuildDiagnostic, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_digests",
            tuple(_digest_entry(item, role="source") for item in self.source_digests),
        )
        object.__setattr__(
            self,
            "cache_digests",
            tuple(_digest_entry(item, role="cache") for item in self.cache_digests),
        )
        object.__setattr__(
            self,
            "output_digests",
            tuple(_digest_entry(item, role="output") for item in self.output_digests),
        )
        object.__setattr__(
            self,
            "model_export_ids",
            tuple(_json_ready(item) for item in self.model_export_ids),
        )
        object.__setattr__(
            self,
            "proof_tool_versions",
            tuple(_json_ready(item) for item in self.proof_tool_versions),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                item
                if isinstance(item, LegalIRBuildDiagnostic)
                else LegalIRBuildDiagnostic.from_dict(_mapping(item))
                for item in self.diagnostics
            ),
        )

    @property
    def source_digest(self) -> str:
        """Aggregate digest of all source inputs."""

        return _stable_hash([item.to_dict() for item in self.source_digests])

    @property
    def cache_digest(self) -> str:
        """Aggregate digest of cache inputs used by the build."""

        return _stable_hash([item.to_dict() for item in self.cache_digests])

    @property
    def manifest_id(self) -> str:
        """Stable identifier equivalent to the persisted build id."""

        return self.build_id

    def comparable_dict(self) -> dict[str, Any]:
        """Return the manifest payload used for reproducibility comparisons."""

        return self.to_dict(include_manifest_sha256=False)

    def to_dict(self, *, include_manifest_sha256: bool = True) -> dict[str, Any]:
        payload = {
            "build_id": self.build_id,
            "cache_digest": self.cache_digest,
            "cache_digests": [item.to_dict() for item in self.cache_digests],
            "compiler_commit": self.compiler_commit,
            "deterministic": True,
            "deterministic_replay_command": list(self.deterministic_replay_command),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "input_digest": self.input_digest,
            "metadata": _json_ready(self.metadata),
            "model_export_ids": list(self.model_export_ids),
            "output_digest": self.output_digest,
            "output_digests": [item.to_dict() for item in self.output_digests],
            "pass_graph": _json_ready(self.pass_graph),
            "pass_replay_digest": self.pass_replay_digest,
            "proof_tool_versions": list(self.proof_tool_versions),
            "replay_command": self.replay_command,
            "runtime_configuration": _json_ready(self.runtime_configuration),
            "schema_version": self.schema_version,
            "schema_versions": _json_ready(self.schema_versions),
            "source_digest": self.source_digest,
            "source_digests": [item.to_dict() for item in self.source_digests],
        }
        if include_manifest_sha256:
            payload["manifest_sha256"] = self.manifest_sha256()
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRBuildManifest":
        return cls(
            build_id=str(data.get("build_id") or data.get("manifest_id") or ""),
            compiler_commit=str(data.get("compiler_commit") or ""),
            source_digests=tuple(
                LegalIRBuildDigest.from_dict(_mapping(item), default_role="source")
                for item in _sequence(data.get("source_digests"))
            ),
            schema_versions=_mapping(data.get("schema_versions")),
            pass_graph=_mapping(data.get("pass_graph")),
            model_export_ids=tuple(_mapping(item) for item in _sequence(data.get("model_export_ids"))),
            proof_tool_versions=tuple(
                _mapping(item) for item in _sequence(data.get("proof_tool_versions"))
            ),
            runtime_configuration=_mapping(data.get("runtime_configuration")),
            cache_digests=tuple(
                LegalIRBuildDigest.from_dict(_mapping(item), default_role="cache")
                for item in _sequence(data.get("cache_digests"))
            ),
            output_digests=tuple(
                LegalIRBuildDigest.from_dict(_mapping(item), default_role="output")
                for item in _sequence(data.get("output_digests"))
            ),
            input_digest=str(data.get("input_digest") or ""),
            output_digest=str(data.get("output_digest") or ""),
            pass_replay_digest=str(data.get("pass_replay_digest") or ""),
            deterministic_replay_command=tuple(
                str(item) for item in _sequence(data.get("deterministic_replay_command"))
            ),
            replay_command=str(data.get("replay_command") or ""),
            diagnostics=tuple(
                LegalIRBuildDiagnostic.from_dict(_mapping(item))
                for item in _sequence(data.get("diagnostics"))
            ),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(data.get("schema_version") or LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION),
        )

    def canonical_json(self, *, include_manifest_sha256: bool = False) -> str:
        """Return deterministic compact JSON for signing and cache keys."""

        return _stable_json(self.to_dict(include_manifest_sha256=include_manifest_sha256))

    def manifest_sha256(self) -> str:
        """Return SHA-256 over the deterministic manifest payload."""

        return _stable_hash(self.to_dict(include_manifest_sha256=False))

    def validate(self) -> LegalIRBuildManifestValidationResult:
        return validate_legal_ir_build_manifest(self)


def build_legal_ir_build_manifest(
    *,
    sources: Mapping[str, Any] | Sequence[Any],
    compiler_commit: str = "",
    pass_run: LegalIRPassRun | Mapping[str, Any] | None = None,
    passes: Sequence[Any] | None = None,
    model_exports: Mapping[str, Any] | Sequence[Any] | None = None,
    proof_tools: Mapping[str, Any] | Sequence[Any] | None = None,
    runtime_config: Mapping[str, Any] | None = None,
    caches: Mapping[str, Any] | Sequence[Any] | None = None,
    outputs: Mapping[str, Any] | Sequence[Any] | None = None,
    manifest_path: str = DEFAULT_LEGAL_IR_BUILD_MANIFEST_PATH,
    repo_root: str | Path | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRBuildManifest:
    """Build a reproducible LegalIR compiler manifest from build inputs."""

    source_digests = _artifact_digests(sources, role="source")
    cache_digests = _artifact_digests(caches or (), role="cache")
    output_digests = _artifact_digests(outputs or (), role="output")
    pass_run_payload = pass_run.to_dict() if isinstance(pass_run, LegalIRPassRun) else _mapping(pass_run)
    pass_final_digest = str(pass_run_payload.get("final_digest") or "")
    pass_replay_digest = str(pass_run_payload.get("replay_digest") or "")
    if not output_digests and pass_final_digest:
        output_digests = (
            LegalIRBuildDigest(
                artifact_id="legal-ir-pass-output-state",
                role="output",
                sha256=pass_final_digest,
                metadata={"source": "pass_run.final_digest"},
            ),
        )

    pass_graph = _pass_graph(passes)
    schema_versions = _schema_versions(
        sources=source_digests,
        caches=cache_digests,
        outputs=output_digests,
        model_exports=model_exports,
        pass_graph=pass_graph,
    )
    normalized_model_exports = _model_export_bindings(model_exports)
    normalized_proof_tools = _proof_tool_bindings(proof_tools)
    normalized_runtime = _runtime_configuration(runtime_config)
    commit = compiler_commit or _detect_git_commit(repo_root)
    input_digest = _stable_hash(
        {
            "cache_digests": [item.to_dict() for item in cache_digests],
            "model_export_ids": normalized_model_exports,
            "pass_graph_sha256": pass_graph.get("pass_graph_sha256"),
            "proof_tool_versions": normalized_proof_tools,
            "runtime_configuration": normalized_runtime,
            "source_digests": [item.to_dict() for item in source_digests],
        }
    )
    output_digest = _stable_hash(
        {
            "output_digests": [item.to_dict() for item in output_digests],
            "pass_final_digest": pass_final_digest,
        }
    )
    build_core_digest = _stable_hash(
        {
            "compiler_commit": commit,
            "input_digest": input_digest,
            "output_digest": output_digest,
            "pass_replay_digest": pass_replay_digest,
            "schema_versions": schema_versions,
        }
    )
    build_id = f"legal-ir-build-{build_core_digest[:16]}"
    replay_argv = _replay_command(
        manifest_path=manifest_path,
        expected_output_digest=output_digest,
    )
    manifest = LegalIRBuildManifest(
        build_id=build_id,
        compiler_commit=commit,
        source_digests=source_digests,
        schema_versions=schema_versions,
        pass_graph=pass_graph,
        model_export_ids=tuple(normalized_model_exports),
        proof_tool_versions=tuple(normalized_proof_tools),
        runtime_configuration=normalized_runtime,
        cache_digests=cache_digests,
        output_digests=output_digests,
        input_digest=input_digest,
        output_digest=output_digest,
        pass_replay_digest=pass_replay_digest,
        deterministic_replay_command=replay_argv,
        replay_command=" ".join(replay_argv),
        metadata=dict(metadata or {}),
    )
    validation = manifest.validate()
    if not validation.valid:
        raise LegalIRBuildManifestError(_format_diagnostics(validation.diagnostics))
    return manifest


def legal_ir_build_manifest(
    *,
    sources: Mapping[str, Any] | Sequence[Any],
    compiler_commit: str = "",
    pass_run: LegalIRPassRun | Mapping[str, Any] | None = None,
    passes: Sequence[Any] | None = None,
    model_exports: Mapping[str, Any] | Sequence[Any] | None = None,
    proof_tools: Mapping[str, Any] | Sequence[Any] | None = None,
    runtime_config: Mapping[str, Any] | None = None,
    caches: Mapping[str, Any] | Sequence[Any] | None = None,
    outputs: Mapping[str, Any] | Sequence[Any] | None = None,
    manifest_path: str = DEFAULT_LEGAL_IR_BUILD_MANIFEST_PATH,
    repo_root: str | Path | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a JSON-ready reproducible build manifest."""

    return build_legal_ir_build_manifest(
        sources=sources,
        compiler_commit=compiler_commit,
        pass_run=pass_run,
        passes=passes,
        model_exports=model_exports,
        proof_tools=proof_tools,
        runtime_config=runtime_config,
        caches=caches,
        outputs=outputs,
        manifest_path=manifest_path,
        repo_root=repo_root,
        metadata=metadata,
    ).to_dict()


def validate_legal_ir_build_manifest(
    manifest: LegalIRBuildManifest | Mapping[str, Any],
) -> LegalIRBuildManifestValidationResult:
    """Validate that a manifest has the fields required for deterministic replay."""

    value = manifest if isinstance(manifest, LegalIRBuildManifest) else LegalIRBuildManifest.from_dict(manifest)
    diagnostics: list[LegalIRBuildDiagnostic] = []
    if value.schema_version != LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION:
        diagnostics.append(
            _diagnostic(
                "unsupported_schema_version",
                "Build manifest schema_version is not supported.",
                "schema_version",
            )
        )
    if not value.build_id:
        diagnostics.append(_diagnostic("build_id_missing", "Build id is required.", "build_id"))
    if not value.compiler_commit:
        diagnostics.append(
            _diagnostic(
                "compiler_commit_missing",
                "Compiler commit is required for reproducible LegalIR builds.",
                "compiler_commit",
            )
        )
    if not value.source_digests:
        diagnostics.append(
            _diagnostic(
                "source_digests_missing",
                "At least one source digest is required.",
                "source_digests",
            )
        )
    for index, source in enumerate(value.source_digests):
        diagnostics.extend(_validate_digest(source, f"source_digests.{index}"))
    for index, cache in enumerate(value.cache_digests):
        diagnostics.extend(_validate_digest(cache, f"cache_digests.{index}"))
    for index, output in enumerate(value.output_digests):
        diagnostics.extend(_validate_digest(output, f"output_digests.{index}"))
    required_schema_keys = {
        "build_manifest",
        "pass_manager",
        "pass_replay",
        "schema_evolution",
        "schema_registry",
    }
    missing_schema = sorted(required_schema_keys - set(value.schema_versions))
    for key in missing_schema:
        diagnostics.append(
            _diagnostic(
                "schema_version_binding_missing",
                f"Required schema binding {key!r} is missing.",
                f"schema_versions.{key}",
            )
        )
    if not value.pass_graph.get("ordered_pass_ids"):
        diagnostics.append(
            _diagnostic(
                "pass_graph_missing",
                "Pass graph must include ordered_pass_ids.",
                "pass_graph.ordered_pass_ids",
            )
        )
    if value.pass_graph.get("valid") is False:
        diagnostics.append(
            _diagnostic(
                "pass_graph_invalid",
                "Pass graph validation reported invalid pass metadata.",
                "pass_graph.valid",
            )
        )
    if not value.input_digest or not _SHA256_HEX(value.input_digest):
        diagnostics.append(
            _diagnostic(
                "input_digest_invalid",
                "Input digest must be a SHA-256 hex digest.",
                "input_digest",
            )
        )
    if not value.output_digest or not _SHA256_HEX(value.output_digest):
        diagnostics.append(
            _diagnostic(
                "output_digest_invalid",
                "Output digest must be a SHA-256 hex digest.",
                "output_digest",
            )
        )
    if value.pass_replay_digest and not _SHA256_HEX(value.pass_replay_digest):
        diagnostics.append(
            _diagnostic(
                "pass_replay_digest_invalid",
                "Pass replay digest must be a SHA-256 hex digest when present.",
                "pass_replay_digest",
            )
        )
    if not value.deterministic_replay_command or not value.replay_command:
        diagnostics.append(
            _diagnostic(
                "replay_command_missing",
                "Deterministic replay command is required.",
                "deterministic_replay_command",
            )
        )
    expected_sha = value.to_dict(include_manifest_sha256=True).get("manifest_sha256")
    if expected_sha and not _SHA256_HEX(str(expected_sha)):
        diagnostics.append(
            _diagnostic(
                "manifest_sha256_invalid",
                "Manifest SHA-256 must be a hex digest.",
                "manifest_sha256",
            )
        )
    return LegalIRBuildManifestValidationResult(
        build_id=value.build_id,
        diagnostics=tuple(_dedupe_diagnostics((*value.diagnostics, *diagnostics))),
    )


def assert_legal_ir_build_manifest_valid(
    manifest: LegalIRBuildManifest | Mapping[str, Any],
) -> LegalIRBuildManifestValidationResult:
    """Validate a build manifest and raise on error diagnostics."""

    result = validate_legal_ir_build_manifest(manifest)
    if not result.valid:
        raise LegalIRBuildManifestError(_format_diagnostics(result.diagnostics))
    return result


def legal_ir_build_manifests_equivalent(
    left: LegalIRBuildManifest | Mapping[str, Any],
    right: LegalIRBuildManifest | Mapping[str, Any],
) -> bool:
    """Return true when two manifests bind equivalent inputs and outputs."""

    left_manifest = left if isinstance(left, LegalIRBuildManifest) else LegalIRBuildManifest.from_dict(left)
    right_manifest = right if isinstance(right, LegalIRBuildManifest) else LegalIRBuildManifest.from_dict(right)
    return left_manifest.comparable_dict() == right_manifest.comparable_dict()


def assert_legal_ir_build_reproducible(
    expected: LegalIRBuildManifest | Mapping[str, Any],
    actual: LegalIRBuildManifest | Mapping[str, Any],
) -> LegalIRBuildManifestValidationResult:
    """Raise when two LegalIR build manifests are not byte-for-byte equivalent."""

    expected_manifest = (
        expected if isinstance(expected, LegalIRBuildManifest) else LegalIRBuildManifest.from_dict(expected)
    )
    actual_manifest = actual if isinstance(actual, LegalIRBuildManifest) else LegalIRBuildManifest.from_dict(actual)
    assert_legal_ir_build_manifest_valid(expected_manifest)
    result = assert_legal_ir_build_manifest_valid(actual_manifest)
    if expected_manifest.comparable_dict() != actual_manifest.comparable_dict():
        raise LegalIRBuildManifestError(
            (
                "LegalIR build manifest mismatch: "
                f"expected {expected_manifest.manifest_sha256()}, "
                f"got {actual_manifest.manifest_sha256()}"
            )
        )
    return result


def save_legal_ir_build_manifest(
    manifest: LegalIRBuildManifest,
    path: str | Path,
) -> Path:
    """Write a manifest as deterministic pretty JSON."""

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out_path


def load_legal_ir_build_manifest(
    path: str | Path,
    *,
    validate: bool = True,
) -> LegalIRBuildManifest:
    """Load a persisted build manifest and optionally validate it."""

    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise LegalIRBuildManifestError(f"LegalIR build manifest does not exist: {manifest_path}")
    manifest = LegalIRBuildManifest.from_dict(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    expected = json.loads(manifest_path.read_text(encoding="utf-8")).get("manifest_sha256")
    if expected and expected != manifest.manifest_sha256():
        raise LegalIRBuildManifestError(
            f"LegalIR build manifest digest mismatch: expected {expected}, got {manifest.manifest_sha256()}"
        )
    if validate:
        assert_legal_ir_build_manifest_valid(manifest)
    return manifest


def verify_legal_ir_build_manifest(
    path: str | Path,
    *,
    expected_output_digest: str = "",
) -> LegalIRBuildManifestValidationResult:
    """Load and validate a manifest, checking the expected output digest if given."""

    manifest = load_legal_ir_build_manifest(path, validate=True)
    if expected_output_digest:
        expected = _normalize_sha256(expected_output_digest)
        if manifest.output_digest != expected:
            raise LegalIRBuildManifestError(
                (
                    "LegalIR build output digest mismatch: "
                    f"expected {expected}, got {manifest.output_digest}"
                )
            )
    return manifest.validate()


def _artifact_digests(
    artifacts: Mapping[str, Any] | Sequence[Any],
    *,
    role: str,
) -> tuple[LegalIRBuildDigest, ...]:
    entries: list[LegalIRBuildDigest] = []
    for key, value in _iter_artifacts(artifacts):
        entries.append(_artifact_digest(value, role=role, fallback_id=key))
    return tuple(
        sorted(
            _unique_digest_entries(entries),
            key=lambda item: (item.role, item.artifact_id, item.path, item.sha256),
        )
    )


def _artifact_digest(value: Any, *, role: str, fallback_id: str = "") -> LegalIRBuildDigest:
    if isinstance(value, LegalIRBuildDigest):
        return value
    if isinstance(value, Path):
        return _path_digest(value, role=role, artifact_id=fallback_id)
    if isinstance(value, (bytes, bytearray)):
        payload = bytes(value)
        digest = hashlib.sha256(payload).hexdigest()
        return LegalIRBuildDigest(
            artifact_id=fallback_id or f"{role}:{digest[:16]}",
            sha256=digest,
            byte_length=len(payload),
            role=role,
        )
    if isinstance(value, str):
        path = Path(value)
        if _looks_like_existing_path(path):
            return _path_digest(path, role=role, artifact_id=fallback_id)
        payload = value.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        return LegalIRBuildDigest(
            artifact_id=fallback_id or f"{role}:{digest[:16]}",
            sha256=digest,
            byte_length=len(payload),
            role=role,
            media_type="text/plain",
        )
    data = _mapping(value)
    if data:
        artifact_id = str(
            data.get("artifact_id")
            or data.get("source_id")
            or data.get("document_id")
            or data.get("cache_id")
            or data.get("output_id")
            or data.get("export_id")
            or data.get("model_id")
            or data.get("id")
            or fallback_id
            or ""
        )
        path_text = str(data.get("path") or "")
        if not data.get("sha256") and path_text and _looks_like_existing_path(Path(path_text)):
            path_digest = _path_digest(Path(path_text), role=str(data.get("role") or role), artifact_id=artifact_id)
            metadata = {**dict(data.get("metadata") or {}), **dict(path_digest.metadata)}
            return LegalIRBuildDigest(
                artifact_id=path_digest.artifact_id,
                role=path_digest.role,
                sha256=path_digest.sha256,
                byte_length=path_digest.byte_length,
                path=path_digest.path,
                media_type=str(data.get("media_type") or path_digest.media_type),
                schema_version=str(data.get("schema_version") or path_digest.schema_version),
                metadata=metadata,
            )
        payload, byte_length, media_type = _payload_bytes(data)
        digest = _normalize_sha256(
            str(
                data.get("sha256")
                or data.get("digest")
                or data.get("content_sha256")
                or data.get("source_sha256")
                or data.get("artifact_sha256")
                or ""
            )
        ) or hashlib.sha256(payload).hexdigest()
        return LegalIRBuildDigest(
            artifact_id=artifact_id or f"{role}:{digest[:16]}",
            sha256=digest,
            byte_length=int(data.get("byte_length") or data.get("size") or byte_length),
            path=path_text,
            media_type=str(data.get("media_type") or data.get("content_type") or media_type),
            role=str(data.get("role") or role),
            schema_version=str(data.get("schema_version") or ""),
            metadata=dict(data.get("metadata") or {}),
        )
    payload = _stable_json(value).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return LegalIRBuildDigest(
        artifact_id=fallback_id or f"{role}:{digest[:16]}",
        sha256=digest,
        byte_length=len(payload),
        role=role,
        media_type="application/json",
    )


def _path_digest(path: Path, *, role: str, artifact_id: str = "") -> LegalIRBuildDigest:
    resolved = path.resolve()
    if resolved.is_dir():
        digest, byte_length = _sha256_directory(resolved)
        media_type = "inode/directory"
    elif resolved.is_file():
        payload = resolved.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        byte_length = len(payload)
        media_type = "application/octet-stream"
    else:
        raise LegalIRBuildManifestError(f"artifact path does not exist: {path}")
    return LegalIRBuildDigest(
        artifact_id=artifact_id or resolved.name or f"{role}:{digest[:16]}",
        sha256=digest,
        byte_length=byte_length,
        path=str(resolved),
        role=role,
        media_type=media_type,
    )


def _payload_bytes(data: Mapping[str, Any]) -> tuple[bytes, int, str]:
    for key, media_type in (
        ("bytes", "application/octet-stream"),
        ("content_bytes", "application/octet-stream"),
    ):
        value = data.get(key)
        if isinstance(value, (bytes, bytearray)):
            payload = bytes(value)
            return payload, len(payload), media_type
    for key in ("text", "content", "source_text", "raw_document", "normalized_document"):
        if key in data:
            payload = str(data.get(key) or "").encode("utf-8")
            return payload, len(payload), "text/plain"
    digest_payload = {
        key: value
        for key, value in data.items()
        if key
        not in {
            "artifact_id",
            "byte_length",
            "cache_id",
            "content_sha256",
            "digest",
            "document_id",
            "id",
            "media_type",
            "metadata",
            "output_id",
            "path",
            "role",
            "sha256",
            "source_id",
            "source_sha256",
        }
    }
    payload = _stable_json(digest_payload or data).encode("utf-8")
    return payload, len(payload), "application/json"


def _pass_graph(passes: Sequence[Any] | None) -> dict[str, Any]:
    manifest = LegalIRPassManager(passes).manifest()
    nodes: list[dict[str, Any]] = []
    for item in manifest.get("passes", []):
        pass_payload = _mapping(item)
        nodes.append(
            {
                "declared_inputs": list(pass_payload.get("declared_inputs") or []),
                "declared_outputs": list(pass_payload.get("declared_outputs") or []),
                "deterministic": bool(pass_payload.get("deterministic", True)),
                "hammer_obligation_ids": [
                    str(_mapping(obligation).get("obligation_id") or "")
                    for obligation in pass_payload.get("hammer_obligations") or []
                    if str(_mapping(obligation).get("obligation_id") or "")
                ],
                "kind": str(pass_payload.get("kind") or ""),
                "order": int(pass_payload.get("order") or 0),
                "pass_id": str(pass_payload.get("pass_id") or ""),
                "schema_migration_ids": [
                    str(_mapping(migration).get("migration_id") or "")
                    for migration in pass_payload.get("schema_migrations") or []
                    if str(_mapping(migration).get("migration_id") or "")
                ],
            }
        )
    pass_ids = {node["pass_id"] for node in nodes}
    edges: list[dict[str, str]] = []
    for item in manifest.get("passes", []):
        pass_payload = _mapping(item)
        target = str(pass_payload.get("pass_id") or "")
        for dependency in pass_payload.get("depends_on") or []:
            dep = str(dependency)
            if dep in pass_ids:
                edges.append({"from": dep, "kind": "declared_dependency", "to": target})
        for source in pass_payload.get("declared_inputs") or []:
            for candidate in manifest.get("passes", []):
                candidate_payload = _mapping(candidate)
                producer = str(candidate_payload.get("pass_id") or "")
                if producer == target:
                    continue
                if source in (candidate_payload.get("declared_outputs") or []):
                    edges.append({"from": producer, "kind": f"data:{source}", "to": target})
    graph = {
        "edges": sorted(edges, key=lambda item: (item["from"], item["to"], item["kind"])),
        "nodes": sorted(nodes, key=lambda item: (item["order"], item["pass_id"])),
        "ordered_pass_ids": list(manifest.get("ordered_pass_ids") or []),
        "schema_version": manifest.get("schema_version", LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION),
        "valid": bool(manifest.get("valid")),
    }
    graph["pass_graph_sha256"] = _stable_hash(graph)
    return graph


def _schema_versions(
    *,
    sources: Sequence[LegalIRBuildDigest],
    caches: Sequence[LegalIRBuildDigest],
    outputs: Sequence[LegalIRBuildDigest],
    model_exports: Mapping[str, Any] | Sequence[Any] | None,
    pass_graph: Mapping[str, Any],
) -> dict[str, Any]:
    artifact_versions = {
        item.schema_version
        for item in (*sources, *caches, *outputs)
        if item.schema_version
    }
    for _, value in _iter_artifacts(model_exports or ()):
        schema = str(_mapping(value).get("schema_version") or "")
        if schema:
            artifact_versions.add(schema)
    return {
        "artifact_schema_versions": sorted(artifact_versions),
        "build_manifest": LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION,
        "known_schema_versions": sorted(known_legal_ir_schema_versions()),
        "pass_graph": pass_graph.get("schema_version", LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION),
        "pass_manager": LEGAL_IR_PASS_MANAGER_SCHEMA_VERSION,
        "pass_replay": LEGAL_IR_PASS_REPLAY_SCHEMA_VERSION,
        "schema_evolution": LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION,
        "schema_registry": LEGAL_IR_SCHEMA_EVOLUTION_REGISTRY_VERSION,
    }


def _model_export_bindings(
    model_exports: Mapping[str, Any] | Sequence[Any] | None,
) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for key, value in _iter_artifacts(model_exports or ()):
        data = _mapping(value)
        if data:
            digest = _normalize_sha256(
                str(data.get("sha256") or data.get("export_sha256") or data.get("model_sha256") or "")
            )
            if not digest:
                digest = _artifact_digest(data, role="model_export", fallback_id=key).sha256
            bindings.append(
                {
                    "artifact_id": str(
                        data.get("artifact_id")
                        or data.get("export_id")
                        or data.get("model_id")
                        or data.get("id")
                        or key
                    ),
                    "export_id": str(data.get("export_id") or ""),
                    "model_id": str(data.get("model_id") or ""),
                    "schema_version": str(data.get("schema_version") or ""),
                    "sha256": digest,
                    "type": str(data.get("type") or data.get("kind") or "model_export"),
                }
            )
        else:
            digest_entry = _artifact_digest(value, role="model_export", fallback_id=key)
            bindings.append(
                {
                    "artifact_id": digest_entry.artifact_id,
                    "export_id": key if key else "",
                    "model_id": "",
                    "schema_version": digest_entry.schema_version,
                    "sha256": digest_entry.sha256,
                    "type": "model_export",
                }
            )
    return sorted(bindings, key=lambda item: (item["type"], item["model_id"], item["export_id"], item["artifact_id"]))


def _proof_tool_bindings(proof_tools: Mapping[str, Any] | Sequence[Any] | None) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for key, value in _iter_artifacts(proof_tools or ()):
        data = _mapping(value)
        if data:
            path = str(data.get("path") or data.get("binary_path") or "")
            digest = _normalize_sha256(str(data.get("sha256") or data.get("binary_sha256") or ""))
            if path and not digest and _looks_like_existing_path(Path(path)):
                digest = _path_digest(Path(path), role="proof_tool", artifact_id=key).sha256
            bindings.append(
                {
                    "path": path,
                    "sha256": digest,
                    "tool": str(data.get("tool") or data.get("name") or key),
                    "version": str(data.get("version") or ""),
                }
            )
        else:
            bindings.append(
                {
                    "path": "",
                    "sha256": "",
                    "tool": str(key),
                    "version": str(value),
                }
            )
    return sorted(bindings, key=lambda item: (item["tool"], item["version"], item["path"]))


def _runtime_configuration(runtime_config: Mapping[str, Any] | None) -> dict[str, Any]:
    runtime = {
        "implementation": platform.python_implementation(),
        "platform": sys.platform,
        "python_version": platform.python_version(),
    }
    runtime.update(dict(runtime_config or {}))
    return _json_ready(runtime)


def _replay_command(*, manifest_path: str, expected_output_digest: str) -> tuple[str, ...]:
    return (
        "python",
        "-m",
        LEGAL_IR_BUILD_REPLAY_MODULE,
        "verify",
        "--manifest",
        manifest_path,
        "--expected-output-digest",
        expected_output_digest,
    )


def _iter_artifacts(artifacts: Mapping[str, Any] | Sequence[Any]) -> list[tuple[str, Any]]:
    if artifacts is None:
        return []
    if isinstance(artifacts, Mapping):
        result: list[tuple[str, Any]] = []
        for key, value in sorted(artifacts.items(), key=lambda item: str(item[0])):
            if isinstance(value, Mapping):
                data = dict(value)
                data.setdefault("artifact_id", str(key))
                result.append((str(key), data))
            else:
                result.append((str(key), value))
        return result
    if isinstance(artifacts, Sequence) and not isinstance(artifacts, (bytes, bytearray, str)):
        return [("", item) for item in artifacts]
    return [("", artifacts)]


def _digest_entry(value: LegalIRBuildDigest | Mapping[str, Any], *, role: str) -> LegalIRBuildDigest:
    if isinstance(value, LegalIRBuildDigest):
        return value
    return LegalIRBuildDigest.from_dict(_mapping(value), default_role=role)


def _unique_digest_entries(entries: Sequence[LegalIRBuildDigest]) -> tuple[LegalIRBuildDigest, ...]:
    seen: set[tuple[str, str, str]] = set()
    result: list[LegalIRBuildDigest] = []
    for entry in entries:
        key = (entry.role, entry.artifact_id, entry.sha256)
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return tuple(result)


def _validate_digest(entry: LegalIRBuildDigest, field_path: str) -> tuple[LegalIRBuildDiagnostic, ...]:
    diagnostics: list[LegalIRBuildDiagnostic] = []
    if not entry.artifact_id:
        diagnostics.append(_diagnostic("artifact_id_missing", "Artifact id is required.", f"{field_path}.artifact_id"))
    if not _SHA256_HEX(entry.sha256):
        diagnostics.append(
            _diagnostic(
                "artifact_sha256_invalid",
                "Artifact sha256 must be a SHA-256 hex digest.",
                f"{field_path}.sha256",
            )
        )
    if entry.byte_length < 0:
        diagnostics.append(
            _diagnostic(
                "artifact_byte_length_invalid",
                "Artifact byte_length must be non-negative.",
                f"{field_path}.byte_length",
            )
        )
    return tuple(diagnostics)


def _sha256_directory(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        if any(part in {".git", "__pycache__"} for part in file_path.relative_to(path).parts):
            continue
        payload = file_path.read_bytes()
        relative = file_path.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        total += len(payload)
    return digest.hexdigest(), total


def _detect_git_commit(repo_root: str | Path | None) -> str:
    root = Path(repo_root or os.getcwd())
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _looks_like_existing_path(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _normalize_sha256(value: str) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    return text if _SHA256_HEX(text) else ""


def _SHA256_HEX(value: str) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _diagnostic(
    code: str,
    message: str,
    field_path: str = "",
    *,
    severity: str = LegalIRBuildDiagnosticSeverity.ERROR.value,
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRBuildDiagnostic:
    return LegalIRBuildDiagnostic(
        code=code,
        message=message,
        field_path=field_path,
        severity=severity,
        metadata=dict(metadata or {}),
    )


def _format_diagnostics(diagnostics: Sequence[LegalIRBuildDiagnostic]) -> str:
    return "; ".join(
        f"{diagnostic.code}:{diagnostic.field_path or '-'}"
        for diagnostic in diagnostics
        if diagnostic.error
    ) or "LegalIR build manifest validation failed"


def _dedupe_diagnostics(
    diagnostics: Sequence[LegalIRBuildDiagnostic],
) -> tuple[LegalIRBuildDiagnostic, ...]:
    seen: set[tuple[str, str, str]] = set()
    result: list[LegalIRBuildDiagnostic] = []
    for diagnostic in diagnostics:
        key = (diagnostic.code, diagnostic.field_path, diagnostic.message)
        if key in seen:
            continue
        seen.add(key)
        result.append(diagnostic)
    return tuple(result)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    return [value]


def _stable_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    if hasattr(value, "__dict__"):
        return _json_ready(vars(value))
    return str(value)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify LegalIR build manifests.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify", help="Validate a persisted build manifest.")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--expected-output-digest", default="")
    args = parser.parse_args(argv)
    if args.command == "verify":
        verify_legal_ir_build_manifest(
            args.manifest,
            expected_output_digest=args.expected_output_digest,
        )
        return 0
    return 2


__all__ = [
    "DEFAULT_LEGAL_IR_BUILD_MANIFEST_PATH",
    "LEGAL_IR_BUILD_MANIFEST_SCHEMA_VERSION",
    "LEGAL_IR_BUILD_REPLAY_MODULE",
    "LegalIRBuildDiagnostic",
    "LegalIRBuildDiagnosticSeverity",
    "LegalIRBuildDigest",
    "LegalIRBuildManifest",
    "LegalIRBuildManifestError",
    "LegalIRBuildManifestValidationResult",
    "assert_legal_ir_build_manifest_valid",
    "assert_legal_ir_build_reproducible",
    "build_legal_ir_build_manifest",
    "legal_ir_build_manifest",
    "legal_ir_build_manifests_equivalent",
    "load_legal_ir_build_manifest",
    "save_legal_ir_build_manifest",
    "validate_legal_ir_build_manifest",
    "verify_legal_ir_build_manifest",
]


if __name__ == "__main__":
    raise SystemExit(_main())
