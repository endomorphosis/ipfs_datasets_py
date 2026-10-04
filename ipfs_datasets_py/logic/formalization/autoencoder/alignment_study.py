"""Preparation and evidence boundaries for the exposed alignment study.

This is an experiment adapter over the existing model/family owners, not a
model registry or a qualification gate. Preparation never fits weights or
opens a sealed test corpus. The optional baseline consumes cached development
vectors and the current deterministic compiler only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import stat
import sys
from pathlib import Path
from typing import Any

CONFIG_SCHEMA = "alignment-study-config/v1"
MANIFEST_SCHEMA = "alignment-study-manifest/v1"
MAX_CONFIG_BYTES = 262_144
MAX_PROVENANCE_BYTES = 2_000_000
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CONFIG_FIELDS = {
    "schema", "study_id", "scope", "evaluation_role", "protected_protocols",
    "corpus", "retrieval", "arms", "resource_policy",
}
_SOURCE_FILES = (
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_study.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_inventory.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_capabilities.py",
    "ipfs_datasets_py/logic/formalization/autoencoder/alignment_baseline.py",
    "scripts/ops/legal_ir/prepare_alignment_study.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py",
    "ipfs_datasets_py/logic/deontic/converter.py",
    "ipfs_datasets_py/logic/deontic/formula_builder.py",
    "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py",
    "ipfs_datasets_py/logic/autoformal/tree_pin.py",
)


class AlignmentStudyError(ValueError):
    """Input identity, evaluation role, or resource boundary is invalid."""


def _executing_repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _verify_loaded_source_origins(repository: Path) -> None:
    """Bind loaded listed modules to the same tree whose bytes are recorded."""
    for relative in _SOURCE_FILES:
        if not relative.startswith("ipfs_datasets_py/") or not relative.endswith(".py"):
            continue
        name = relative[:-3].replace("/", ".")
        module = sys.modules.get(name)
        if module is None:
            continue
        origin = getattr(module, "__file__", None)
        if origin is None or Path(origin).resolve() != repository / relative:
            raise AlignmentStudyError(f"loaded study dependency comes from another tree: {name}")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise AlignmentStudyError(f"duplicate JSON key: {name}")
        result[name] = value
    return result


def _reject_constant(value: str) -> None:
    raise AlignmentStudyError(f"nonfinite JSON constant: {value}")


def _bounded_bytes(path: Path, limit: int) -> bytes:
    if type(limit) is not int or limit < 1:
        raise AlignmentStudyError("byte limit must be a positive integer")
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise AlignmentStudyError(f"regular bounded file required: {path}")
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise AlignmentStudyError(f"file exceeds byte limit: {path}")
    except OSError as exc:
        raise AlignmentStudyError(f"input unavailable: {path}: {exc.strerror}") from exc
    return raw


def _workspace_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise AlignmentStudyError("nonempty relative workspace path required")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise AlignmentStudyError("input paths must remain inside the workspace")
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise AlignmentStudyError(f"symlink input is not admitted: {relative}")
    return current


def _validate_binding(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise AlignmentStudyError("file binding requires path and sha256")
    if not isinstance(value["path"], str) or not value["path"].strip():
        raise AlignmentStudyError("file binding path must be nonempty")
    if not isinstance(value["sha256"], str) or not _DIGEST.fullmatch(value["sha256"]):
        raise AlignmentStudyError("file binding requires a lowercase SHA256")


def _observed_binding(root: Path, binding: dict[str, Any]) -> dict[str, Any]:
    _validate_binding(binding)
    path = _workspace_path(root, binding["path"])
    raw = _bounded_bytes(path, MAX_PROVENANCE_BYTES)
    observed = hashlib.sha256(raw).hexdigest()
    if observed != binding["sha256"]:
        raise AlignmentStudyError(f"input digest mismatch: {binding['path']}")
    return {**binding, "bytes": len(raw), "digest_verified": True}


def validate_alignment_config(value: Any) -> dict[str, Any]:
    """Validate the development-only scope without opening any corpus."""
    if not isinstance(value, dict) or set(value) != _CONFIG_FIELDS:
        raise AlignmentStudyError("unexpected alignment configuration fields")
    if value["schema"] != CONFIG_SCHEMA:
        raise AlignmentStudyError("unsupported alignment configuration schema")
    if not isinstance(value["study_id"], str) or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", value["study_id"]):
        raise AlignmentStudyError("invalid study identifier")
    if (value["scope"] != "inventory_and_exposed_development_baseline"
            or value["evaluation_role"] != "exposed_development"):
        raise AlignmentStudyError("only exposed development is admitted")
    protocols = value["protected_protocols"]
    if not isinstance(protocols, list) or not 1 <= len(protocols) <= 16:
        raise AlignmentStudyError("protected protocol bindings required")
    for binding in protocols:
        _validate_binding(binding)
    corpus = value["corpus"]
    if not isinstance(corpus, dict):
        raise AlignmentStudyError("corpus configuration must be an object")
    required = {"train", "development", "dimension", "vector_space_id", "target_origin",
                "evaluation_role", "domain_id", "max_rows", "max_file_bytes", "provenance",
                "encoder_execution_authenticated", "independent_source_review_available"}
    if set(corpus) != required:
        raise AlignmentStudyError("unexpected corpus configuration fields")
    for split in ("train", "development"):
        _validate_binding(corpus[split])
    if corpus["train"]["path"] == corpus["development"]["path"]:
        raise AlignmentStudyError("training and development files must be distinct")
    if corpus["domain_id"] != "legal_ir" or corpus["dimension"] != 384:
        raise AlignmentStudyError("initial baseline requires legal_ir 384D inputs")
    if corpus["evaluation_role"] != "exposed_development":
        raise AlignmentStudyError("sealed or final-test corpus is forbidden")
    if corpus["target_origin"] != "synthetic_authored_unreviewed":
        raise AlignmentStudyError("initial authored development target origin required")
    if (corpus["encoder_execution_authenticated"] is not False
            or corpus["independent_source_review_available"] is not False):
        raise AlignmentStudyError("configuration cannot assert independent authentication")
    if not isinstance(corpus["vector_space_id"], str) or not corpus["vector_space_id"].strip():
        raise AlignmentStudyError("explicit vector-space identity required")
    for name, ceiling in (("max_rows", 5000), ("max_file_bytes", 16_000_000)):
        if type(corpus[name]) is not int or not 1 <= corpus[name] <= ceiling:
            raise AlignmentStudyError(f"invalid {name} resource limit")
    provenance = corpus["provenance"]
    if not isinstance(provenance, list) or not 1 <= len(provenance) <= 16:
        raise AlignmentStudyError("corpus provenance bindings required")
    for binding in provenance:
        _validate_binding(binding)
    retrieval = value["retrieval"]
    if not isinstance(retrieval, dict) or set(retrieval) != {"top_k", "kind"}:
        raise AlignmentStudyError("unexpected retrieval fields")
    if retrieval["kind"] != "source_to_source_demonstrations":
        raise AlignmentStudyError("cached source vectors do not establish formal embeddings")
    if type(retrieval["top_k"]) is not int or not 1 <= retrieval["top_k"] <= 50:
        raise AlignmentStudyError("top_k must be an integer from 1 to 50")
    arms = value["arms"]
    if not isinstance(arms, list) or not 2 <= len(arms) <= 32:
        raise AlignmentStudyError("explicit experiment arms required")
    ids: set[str] = set()
    for arm in arms:
        if not isinstance(arm, dict) or set(arm) != {"id", "description", "status"}:
            raise AlignmentStudyError("invalid experiment arm")
        if not isinstance(arm["id"], str) or not arm["id"] or arm["id"] in ids:
            raise AlignmentStudyError("experiment arm IDs must be unique")
        if arm["status"] != "planned" or not isinstance(arm["description"], str):
            raise AlignmentStudyError("configurations declare planned arms only")
        ids.add(arm["id"])
    if not {"B0", "B1"}.issubset(ids):
        raise AlignmentStudyError("B0 and B1 baselines must be declared")
    policy = value["resource_policy"]
    if not isinstance(policy, dict) or set(policy) != {
        "model_loads", "provider_calls", "prover_calls", "optimizer_steps",
        "max_baseline_seconds", "cpu_threads",
    }:
        raise AlignmentStudyError("explicit resource policy required")
    for name in ("model_loads", "provider_calls", "prover_calls", "optimizer_steps"):
        if type(policy[name]) is not int or policy[name] != 0:
            raise AlignmentStudyError("initial study admits no model/prover/training calls")
    seconds = policy["max_baseline_seconds"]
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 120:
        raise AlignmentStudyError("baseline deadline must be at most 120 seconds")
    if type(policy["cpu_threads"]) is not int or policy["cpu_threads"] != 1:
        raise AlignmentStudyError("initial study uses one CPU thread")
    # Return detached ordinary JSON, rejecting nonfinite values everywhere.
    return json.loads(_canonical_bytes(value))


def load_alignment_config(path: str | Path, *, expected_sha256: str | None = None
                          ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read a bounded strict JSON configuration and bind its exact bytes."""
    source = Path(path)
    raw = _bounded_bytes(source, MAX_CONFIG_BYTES)
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None:
        if not _DIGEST.fullmatch(expected_sha256) or expected_sha256 != digest:
            raise AlignmentStudyError("configuration digest mismatch")
    try:
        value = json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AlignmentStudyError("configuration must be strict UTF-8 JSON") from exc
    config = validate_alignment_config(value)
    return config, {"path": str(source.resolve()), "sha256": digest,
                    "bytes": len(raw), "digest_verified": True}


def prepare_alignment_study(config_path: str | Path, repository_root: str | Path,
                            workspace_root: str | Path, *, baseline: bool = False,
                            expected_config_sha256: str | None = None) -> dict[str, Any]:
    """Collect inventory and optionally measure the exposed B0/B1 baseline."""
    repository = Path(repository_root).resolve()
    if repository != _executing_repository_root():
        raise AlignmentStudyError("repository root must match the executing study package")
    workspace = Path(workspace_root).resolve()
    config, config_binding = load_alignment_config(
        config_path, expected_sha256=expected_config_sha256)
    protocols = [_observed_binding(workspace, item) for item in config["protected_protocols"]]
    provenance = [_observed_binding(workspace, item) for item in config["corpus"]["provenance"]]

    # Optional integrations are deliberately imported after admission checks.
    from .alignment_capabilities import describe_alignment_capabilities
    from .alignment_inventory import describe_alignment_assets

    assets = describe_alignment_assets(repository, workspace)
    capabilities = describe_alignment_capabilities(repository, workspace)
    source_bindings = []
    for relative in _SOURCE_FILES:
        source = _workspace_path(repository, relative)
        raw = _bounded_bytes(source, MAX_PROVENANCE_BYTES)
        source_bindings.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest(),
                                "bytes": len(raw), "digest_verified": True})
    baseline_report = None
    if baseline:
        from .alignment_baseline import run_alignment_baseline

        baseline_report = run_alignment_baseline(config, repository, workspace)
    _verify_loaded_source_origins(repository)
    # Reject concurrent source/provenance drift as well as protocol changes.
    for binding in source_bindings:
        raw = _bounded_bytes(_workspace_path(repository, binding["path"]), MAX_PROVENANCE_BYTES)
        if hashlib.sha256(raw).hexdigest() != binding["sha256"]:
            raise AlignmentStudyError(f"study source changed during execution: {binding['path']}")
    for binding in config["corpus"]["provenance"]:
        _observed_binding(workspace, binding)
    for binding in config["protected_protocols"]:
        _observed_binding(workspace, binding)
    payload = {
        "schema": MANIFEST_SCHEMA,
        "study_id": config["study_id"],
        "evaluation_role": config["evaluation_role"],
        "stage": "development_baseline" if baseline else "inventory_preparation",
        "configuration": config,
        "configuration_binding": config_binding,
        "protected_protocol_bindings": protocols,
        "corpus_provenance_bindings": provenance,
        "source_bindings": source_bindings,
        "dependency_binding_scope": "listed_study_and_core_source_files_only",
        "complete_dependency_manifest": False,
        "assets": assets,
        "capabilities": capabilities,
        "baseline": baseline_report,
        "arm_execution": [
            {"id": arm["id"],
             "status": ("development_diagnostic_completed" if baseline_report["status"] == "completed"
                        else "development_diagnostic_partial")
             if baseline_report is not None and arm["id"] in {"B0", "B1"} else "unrun",
             "qualified": False}
            for arm in config["arms"]
        ],
        "primary_evaluation": {
            "independently_adjudicated_source_fidelity": {
                "status": "unavailable", "value": None,
                "reason": "synthetic authored targets have no independent review attestation",
            },
            "native_checker_accepted_useful_proof_coverage": {
                "status": "unrun", "value": None,
                "reason": "this bounded study executes no prover or proof model",
            },
        },
        "qualified": False,
        "production_admitted": False,
        "training_performed": False,
        "sealed_final_test_accessed": False,
    }
    payload["manifest_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def write_alignment_manifest(output_directory: str | Path, manifest: dict[str, Any]) -> Path:
    """Publish to a fresh directory and refuse replacing prior evidence."""
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise AlignmentStudyError("alignment manifest schema required")
    digest = manifest.get("manifest_sha256")
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if digest != hashlib.sha256(_canonical_bytes(payload)).hexdigest():
        raise AlignmentStudyError("alignment manifest digest mismatch")
    output = Path(output_directory)
    if output.exists() or output.is_symlink():
        raise AlignmentStudyError("refusing to overwrite an existing output directory")
    output.mkdir(parents=True, exist_ok=False)
    path = output / "manifest.json"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    persisted = json.loads(_bounded_bytes(path, 32_000_000))
    if persisted != manifest:
        raise AlignmentStudyError("persisted alignment manifest differs from its source")
    return path


__all__ = ["AlignmentStudyError", "load_alignment_config", "prepare_alignment_study",
           "validate_alignment_config", "write_alignment_manifest"]
