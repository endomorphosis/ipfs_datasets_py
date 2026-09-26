"""Offline, deterministic private exact-resume autoencoder release packages.

The original checkpoint bytes are retained without tensor conversion, key
sanitization or sample-memory removal. This module builds an existing
PublicationPlan for review; it never constructs an approval, opens credentials,
contacts Hugging Face, enqueues publication or promotes an inference pointer.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
from typing import Any, Mapping, Sequence

from ..duckdb_control.autoencoder_registry import SCHEMA as REGISTRY_SCHEMA
from ..duckdb_control.contracts import canonical_json_bytes, content_identity
from .publication_profile import HuggingFacePublicationProfile
from .publisher import (
    HuggingFaceReleasePublisher,
    PublicationFilePlan,
    PublicationPlan,
    estimate_publication_cost,
    _open_absolute_path_nofollow_components,
    _read_regular_file_nofollow_components,
    _reject_secrets,
)


PROFILE = "exact_resume_private"
SCHEMA = "autoencoder-exact-resume-private-release/v1"
PACKAGE_SCHEMA = "autoencoder-private-local-package/v1"
COMPACT_SCHEMA = "autoencoder-exact-resume-private-release/v2"
COMPACT_PACKAGE_SCHEMA = "autoencoder-private-local-package/v2"
# Matches the owned daemon's bounded full-checkpoint input contract. This is
# a package input bound, not a promise about Python allocator peak memory.
MAX_COMPACT_CHECKPOINT_BYTES = 256 * 1024 * 1024
_HASH = re.compile(r"^[0-9a-f]{64}$")
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


class AutoencoderReleaseError(ValueError):
    """Unsafe, incomplete or unsupported exact-resume package request."""


@dataclass(frozen=True)
class PrivateResumeRelease:
    package_root: Path
    release_root: Path
    profile: HuggingFacePublicationProfile
    publication_plan: PublicationPlan
    package_manifest_sha256: str


def _json(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _descriptor(path: Path, relative: str, *, maximum_bytes: int | None = None) -> dict[str, Any]:
    _, descriptor = _open_absolute_path_nofollow_components(
        path, label="package artifact", require_directory=False
    )
    size, digest = 0, hashlib.sha256()
    with os.fdopen(descriptor, "rb") as handle:
        if maximum_bytes is not None and os.fstat(handle.fileno()).st_size > maximum_bytes:
            raise AutoencoderReleaseError("package artifact exceeds its sealed byte bound")
        while block := handle.read(1024 * 1024):
            size += len(block)
            if maximum_bytes is not None and size > maximum_bytes:
                raise AutoencoderReleaseError("package artifact grew beyond its sealed byte bound")
            digest.update(block)
    return {"path": relative, "size_bytes": size, "sha256": digest.hexdigest()}


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _copy_exact(source: Path, destination: Path, expected: Mapping[str, Any]) -> None:
    _, descriptor = _open_absolute_path_nofollow_components(
        source, label="checkpoint", require_directory=False
    )
    digest, size = hashlib.sha256(), 0
    with os.fdopen(descriptor, "rb") as stream, destination.open("xb") as output:
        if os.fstat(stream.fileno()).st_size != expected["bytes"]:
            raise AutoencoderReleaseError("checkpoint bytes differ from the immutable version artifact")
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > expected["bytes"]:
                raise AutoencoderReleaseError("checkpoint grew beyond the immutable version artifact")
            output.write(block)
            digest.update(block)
        output.flush()
        os.fsync(output.fileno())
    if size != expected["bytes"] or digest.hexdigest() != expected["sha256"]:
        raise AutoencoderReleaseError("checkpoint bytes differ from the immutable version artifact")
    observed = _descriptor(source, "state.json")
    if observed["size_bytes"] != size or observed["sha256"] != digest.hexdigest():
        raise AutoencoderReleaseError("source checkpoint changed during packaging")


def _nonfinite(value: str) -> Any:
    raise AutoencoderReleaseError(f"non-finite JSON value is not supported: {value}")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise AutoencoderReleaseError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _frozen_json_file(path: Path) -> tuple[bytes, str]:
    _, descriptor = _open_absolute_path_nofollow_components(
        path, label="evaluation receipt", require_directory=False
    )
    with os.fdopen(descriptor, "rb") as handle:
        payload = handle.read(4 * 1024 * 1024 + 1)
    if len(payload) > 4 * 1024 * 1024:
        raise AutoencoderReleaseError("evaluation receipt exceeds 4 MiB")
    parsed = json.loads(payload, parse_constant=_nonfinite, object_pairs_hook=_unique_keys)
    if not isinstance(parsed, dict):
        raise AutoencoderReleaseError("evaluation receipt must be a JSON object")
    _reject_secrets(parsed, label="evaluation receipt")
    return payload, hashlib.sha256(payload).hexdigest()


def private_resume_publication_profile(
    repo_id: str, *, checkpoint_format: str = "legacy_json",
) -> HuggingFacePublicationProfile:
    if not isinstance(repo_id, str) or not _REPO.fullmatch(repo_id) or ".." in repo_id:
        raise AutoencoderReleaseError("repo_id must be an explicit namespace/model identifier")
    if checkpoint_format not in {"legacy_json", "modal_autoencoder_compact"}:
        raise AutoencoderReleaseError("unsupported private checkpoint format")
    profile = HuggingFacePublicationProfile(
        profile_id="legal-autoencoder-exact-resume-private",
        program_id="legal-autoencoder", goal_id="legal-autoencoder-versioned-training",
        plan_schema_version="legal-autoencoder-hf-publication-plan/v1",
        receipt_schema_version="legal-autoencoder-hf-publication-receipt/v1",
        repository_id=repo_id, repository_type="model",
        release_prefix_template="releases/{release_id}",
        pointer_path="runtime/autoencoder-release-pointer.json",
        canonical_release_schema=SCHEMA,
        commit_message="autoencoder: append immutable private exact-resume release",
        metadata={"required_repository_private": True, "checkpoint_profile": PROFILE},
    )
    if checkpoint_format == "legacy_json":
        return profile
    return replace(
        profile, profile_id="legal-autoencoder-exact-resume-private-compact",
        # PublicationPlan/receipt framing is unchanged; only the release's
        # checkpoint contract advances to v2. Shared profile rules stay intact.
        canonical_release_schema=COMPACT_SCHEMA,
        metadata={**profile.metadata, "checkpoint_format": checkpoint_format},
    )


def _compact_checkpoint_description(
    source: Path, expected: Mapping[str, Any], supplied_identity: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate native compact bytes without converting the original artifact.

    Legacy JSON retains its historical v1 validation and packaging behavior.
    Compact v2 deliberately accepts only the canonical full float64 writer
    format used by the owner, including exact re-encoding of its metadata.
    """
    from ..optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as codec

    _, descriptor = _open_absolute_path_nofollow_components(
        source, label="checkpoint", require_directory=False,
    )
    with os.fdopen(descriptor, "rb") as handle:
        prefix = handle.read(len(codec.CHECKPOINT_MAGIC))
    if prefix == codec.DELTA_MAGIC:
        raise AutoencoderReleaseError("checkpoint deltas require verified full materialization and registration")
    if prefix != codec.CHECKPOINT_MAGIC:
        return None
    if expected["bytes"] > MAX_COMPACT_CHECKPOINT_BYTES:
        raise AutoencoderReleaseError("compact checkpoint exceeds the 256 MiB package input bound")
    raw = _read_regular_file_nofollow_components(
        source, label="compact checkpoint", maximum_bytes=MAX_COMPACT_CHECKPOINT_BYTES,
    )
    if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise AutoencoderReleaseError("checkpoint bytes differ from the immutable version artifact")
    try:
        loaded = codec.deserialize_checkpoint(raw)
        manifest = loaded.manifest
        if manifest.kind != "full" or manifest.float_precision != "float64":
            raise AutoencoderReleaseError("compact resume packages require a full float64 checkpoint")
        rebuilt = codec.serialize_checkpoint(
            loaded.state, float_precision="float64", metric_lineage=manifest.metric_lineage,
            metadata=manifest.metadata,
        )
        if rebuilt != raw:
            raise AutoencoderReleaseError("compact checkpoint is not an exact canonical native full checkpoint")
        logical = loaded.state.state_identity_record().to_dict()
        metric = loaded.state.state_identity_record(metric_lineage=manifest.metric_lineage).to_dict()
        if supplied_identity is not None and canonical_json_bytes(supplied_identity) != canonical_json_bytes(logical):
            raise AutoencoderReleaseError("supplied state identity differs from the native compact checkpoint")
        from ..optimizers.logic_theorem_optimizer import modal_autoencoder as native_state
        from ..optimizers.logic_theorem_optimizer import modal_autoencoder_state_version as native_identity
        sources = {}
        for module in (codec, native_state, native_identity):
            sources[module.__name__] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        return {
            "format": "modal_autoencoder_compact", "path": "state.compact",
            "schema_version": manifest.schema_version, "state_schema_version": manifest.state_schema_version,
            "float_precision": manifest.float_precision, "revision": manifest.revision,
            "validation": "native_full_float64_exact_canonical_roundtrip",
            "logical_state_identity": logical, "metric_state_identity": metric,
            "metric_lineage": manifest.metric_lineage,
            "loader": {"module": codec.__name__, "callable": "load_checkpoint",
                       "kwargs": {"recover": False, "allow_json": False}},
            "source_provenance": {"scope": "descriptive_files_not_runtime_attestation", "sha256": sources},
        }
    except AutoencoderReleaseError:
        raise
    except (codec.ModalAutoencoderCheckpointError, ValueError, TypeError, OverflowError, KeyError) as exc:
        raise AutoencoderReleaseError("invalid native full compact checkpoint") from exc


def _version_record(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "version_id", "variant_id", "parent_version_id", "artifact", "metadata"
    }:
        raise AutoencoderReleaseError("complete immutable registry version record required")
    record = json.loads(canonical_json_bytes(value))
    artifact = record["artifact"]
    if not isinstance(artifact, dict) or set(artifact) != {"sha256", "bytes"}:
        raise AutoencoderReleaseError("artifact requires exactly sha256 and bytes")
    if not isinstance(artifact["sha256"], str) or not _HASH.fullmatch(artifact["sha256"]):
        raise AutoencoderReleaseError("invalid artifact SHA-256")
    if type(artifact["bytes"]) is not int or artifact["bytes"] <= 0:
        raise AutoencoderReleaseError("artifact byte count must be positive")
    expected = content_identity({"schema": REGISTRY_SCHEMA, **{
        key: record[key] for key in ("variant_id", "artifact", "metadata", "parent_version_id")
    }})
    if record["version_id"] != expected:
        raise AutoencoderReleaseError("registry version identity does not match its immutable record")
    _reject_secrets(record, label="registry version")
    return record


def _model_card(languages: list[str], receipt_count: int, version: Mapping[str, Any]) -> bytes:
    language_yaml = "".join(f"  - {json.dumps(language)}\n" for language in languages)
    front_matter = "---\n"
    if languages:
        front_matter += "language:\n" + language_yaml
    front_matter += "tags:\n  - legal-autoformalization\n  - autoencoder\n  - exact-resume\n---\n\n"
    language_text = ", ".join(languages) if languages else "not declared"
    return (front_matter + "# Private exact-resume legal autoencoder\n\n"
        f"Registry version: `{version['version_id']}`.\n\n"
        "This archive preserves the complete original checkpoint, including source-like feature keys, "
        "metadata and any sample memory. It is an exact-resume artifact for the original loader; "
        "it is not a Transformers-compatible model or a validated inference export.\n\n"
        f"Declared source languages: {language_text}. These declarations do not establish language quality.\n\n"
        f"Frozen evaluation receipts included: {receipt_count}. "
        + ("No evaluation evidence was supplied. " if not receipt_count else "These are supplied records, not independently revalidated scores. ")
        + "Packaging establishes neither held-out generalization nor formal correctness.\n\n"
        "Only `lake build <Lib>` admits Lean. A compilation, reconstruction score, bridge target, "
        "database row or this package is not an admit. The US Constitution is not formalized.\n\n"
        "Repository visibility must be independently verified as private before publication. "
        "Source-data and model licensing were not established by this packaging step; no license is granted here.\n"
    ).encode()


def build_private_resume_release(
    version_record: Mapping[str, Any],
    artifact_path: str | Path,
    destination: str | Path,
    *,
    repo_id: str,
    variant_manifest: Mapping[str, Any],
    state_identity: Mapping[str, Any] | None = None,
    evaluation_receipts: Sequence[str | Path] = (),
    private: bool = True,
    checkpoint_profile: str = PROFILE,
    audited_parent_commit: str = "",
) -> PrivateResumeRelease:
    """Create a fresh private directory and concrete offline publication plan.

    The root README is a local Hub-card proposal. The existing publisher admits
    only immutable release-prefix operations, so installing the Hub-root card
    remains a separate reviewed bootstrap/CAS action. Remote privacy and parent
    identity are not inferred from this offline package.
    """
    if private is not True or checkpoint_profile != PROFILE:
        raise AutoencoderReleaseError("only exact_resume_private is supported; public/inference exports require parity qualification")
    profile = private_resume_publication_profile(repo_id)
    version = _version_record(version_record)
    if not isinstance(variant_manifest, Mapping):
        raise AutoencoderReleaseError("variant_manifest must be an object")
    variant = json.loads(canonical_json_bytes(variant_manifest))
    _reject_secrets(variant, label="variant manifest")
    languages = variant.get("source_languages", [])
    if not isinstance(languages, list) or any(not isinstance(v, str) or not _LANGUAGE.fullmatch(v) for v in languages):
        raise AutoencoderReleaseError("source_languages must be a list of language codes")
    if "source_language" in variant:
        singular = variant["source_language"]
        if not isinstance(singular, str) or not _LANGUAGE.fullmatch(singular):
            raise AutoencoderReleaseError("source_language must be a language code")
        if "source_languages" in variant and set(languages) != {singular}:
            raise AutoencoderReleaseError("source_language and source_languages declarations contradict")
        languages = [singular]
    languages = sorted(set(languages))
    logical_identity = None if state_identity is None else json.loads(canonical_json_bytes(state_identity))
    if logical_identity is not None and not isinstance(logical_identity, dict):
        raise AutoencoderReleaseError("state_identity must be an object")
    _reject_secrets(logical_identity, label="logical state identity")
    frozen = {}
    for path in evaluation_receipts:
        payload, digest = _frozen_json_file(Path(path))
        frozen[digest] = payload
    checkpoint_description = _compact_checkpoint_description(Path(artifact_path), version["artifact"], logical_identity)
    release_schema, package_schema, checkpoint_file = SCHEMA, PACKAGE_SCHEMA, "state.json"
    if checkpoint_description is not None:
        release_schema, package_schema = COMPACT_SCHEMA, COMPACT_PACKAGE_SCHEMA
        checkpoint_file = checkpoint_description["path"]
        logical_identity = checkpoint_description["logical_state_identity"]
        profile = private_resume_publication_profile(repo_id, checkpoint_format=checkpoint_description["format"])
    identities = {
        "checkpoint_file_sha256": version["artifact"]["sha256"],
        "registry_version_id": version["version_id"],
        "logical_state_identity": logical_identity,
        "logical_state_identity_status": "not_supplied" if logical_identity is None else "caller_supplied_not_recomputed",
        "huggingface_commit_sha": None,
    }
    identity_material = {
        "schema_version": release_schema, "checkpoint_profile": PROFILE,
        "version": version, "variant_manifest": variant, "identities": identities,
        "evaluation_receipt_sha256": sorted(frozen),
    }
    if checkpoint_description is not None:
        identities["logical_state_identity_status"] = "native_compact_recomputed"
        identities["metric_state_identity"] = checkpoint_description["metric_state_identity"]
        identity_material["checkpoint"] = checkpoint_description
    release_id = "sha256-" + hashlib.sha256(canonical_json_bytes(identity_material)).hexdigest()
    root = Path(os.path.abspath(os.fspath(Path(destination).expanduser())))
    _, parent_fd = _open_absolute_path_nofollow_components(root.parent, label="package parent", require_directory=True)
    os.close(parent_fd)
    root.mkdir(mode=0o700, exist_ok=False)
    try:
        release_root = root / "releases" / release_id
        release_root.mkdir(mode=0o700, parents=True)
        _copy_exact(Path(artifact_path), release_root / checkpoint_file, version["artifact"])
        if checkpoint_description is None:
            with (release_root / checkpoint_file).open("rb") as handle:
                checkpoint = json.load(handle, parse_constant=_nonfinite)
                if not isinstance(checkpoint, dict):
                    raise AutoencoderReleaseError("original checkpoint must be a JSON object")
                from ..optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import SCHEMA as SPARSE_CHECKPOINT_SCHEMA
                if checkpoint.get("schema") == SPARSE_CHECKPOINT_SCHEMA:
                    raise AutoencoderReleaseError(
                        "sparse checkpoint manifests require verified full materialization and registration before exact-resume packaging"
                    )
            del checkpoint
        config = {
            "schema_version": "autoencoder-private-resume-config/v1", "checkpoint_profile": PROFILE,
            "checkpoint_file": checkpoint_file, "original_loader_required": True,
            "tensor_migration_performed": False, "key_sanitization_performed": False,
            "sample_memory_removed": False, "variant_manifest": variant,
            "parameter_schema_status": "preserved_original_not_migrated", "admitted": False,
        }
        if checkpoint_description is not None:
            config.update(schema_version="autoencoder-private-resume-config/v2", checkpoint=checkpoint_description)
        _write(release_root / "config.json", _json(config))
        _write(release_root / "provenance.json", _json(identity_material))
        for digest, payload in sorted(frozen.items()):
            _write(release_root / "evaluations" / f"{digest}.json", payload)
        card = _model_card(languages, len(frozen), version)
        if checkpoint_description is not None:
            card += (
                "\nCheckpoint format: native full float64 compact checkpoint (`state.compact`). "
                "Restore with `ipfs_datasets_py.optimizers.logic_theorem_optimizer."
                "modal_autoencoder_checkpoint.load_checkpoint(path, recover=False, allow_json=False)`. "
                "This is binary data, not JSON. The full checkpoint is self-contained; no Arrow sidecar "
                "is required to resume. Original bytes, operational revision and native identities were "
                "verified locally. Listed source hashes describe validation files; they are not runtime attestation.\n"
            ).encode()
        _write(root / "README.md", card)
        _write(release_root / "README.md", card)
        release_files = sorted(path for path in release_root.rglob("*") if path.is_file())
        manifest = {
            "schema_version": release_schema, "release_id": release_id,
            "checkpoint_profile": PROFILE, "required_repository_private": True,
            "identities": identities, "admitted": False, "constitution_formalized": False,
            "evaluation_status": "supplied_not_revalidated" if frozen else "not_supplied",
            "files": [_descriptor(path, path.relative_to(release_root).as_posix()) for path in release_files],
        }
        if checkpoint_description is not None:
            manifest["checkpoint"] = checkpoint_description
        _write(release_root / "release-manifest.json", _json(manifest))
        manifest_entry = _descriptor(release_root / "release-manifest.json", "release-manifest.json")
        publisher = HuggingFaceReleasePublisher(profile=profile, api=None)
        plan = publisher.plan_dry_run(
            {**manifest, "release_sha256": manifest_entry["sha256"], "files": [*manifest["files"], manifest_entry]},
            local_root=release_root, audited_parent_commit=audited_parent_commit,
        )
        plan = replace(plan, metadata={**plan.metadata,
            "checkpoint_profile": PROFILE, "required_repository_private": True,
            "remote_privacy_verified": False, "remote_inventory_checked": False,
            "autoencoder_release_manifest_included": True,
            "root_model_card_publication": "separate_reviewed_bootstrap_or_cas_required",
            "approval_status": "exact_plan_human_approval_required", "upload_ready": False,
            "cost_rates_status": "publisher_defaults_are_illustrative_not_a_huggingface_quote",
            "admitted": False,
        })
        if checkpoint_description is not None:
            plan = replace(plan, metadata={**plan.metadata, "checkpoint_format": checkpoint_description["format"],
                                          "checkpoint_file": checkpoint_file, "checkpoint_schema_version": checkpoint_description["schema_version"]})
        _write(root / "publication-plan.json", _json(plan.to_dict()))
        package_files = sorted(path for path in root.rglob("*") if path.is_file())
        closure = {
            "schema_version": package_schema, "release_id": release_id,
            "release_root": release_root.relative_to(root).as_posix(),
            "required_repository_private": True, "admitted": False,
            "publication_plan_digest": plan.plan_digest,
            "files": [_descriptor(path, path.relative_to(root).as_posix()) for path in package_files],
        }
        _write(root / "package-manifest.json", _json(closure))
        manifest_sha = _descriptor(root / "package-manifest.json", "package-manifest.json")["sha256"]
        verify_release_package(root, expected_manifest_sha256=manifest_sha)
        return PrivateResumeRelease(root, release_root, profile, plan, manifest_sha)
    except BaseException:
        shutil.rmtree(root)
        raise


def _bounded_package_paths(root: str | Path) -> tuple[Path, ...]:
    """Inventory at most 256 regular files/directories without following aliases.

    Directory enumeration is incremental. Bounds include empty directories and
    the manifest itself, so neither special entries nor a broad empty tree can
    hide behind the bounded manifest file list. Returned paths are not leases;
    consumers must still open files without aliases and verify sealed bytes.
    """
    root = Path(root)
    _, root_fd = _open_absolute_path_nofollow_components(root, label="release package", require_directory=True)
    paths: list[Path] = []

    def visit(directory_fd: int, parents: tuple[str, ...]) -> None:
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                if len(paths) >= 256:
                    raise AutoencoderReleaseError("package namespace exceeds 256 entries")
                parts = (*parents, entry.name)
                if len(parts) > 8 or len("/".join(parts).encode("utf-8")) > 1024:
                    raise AutoencoderReleaseError("package namespace exceeds path depth or byte bound")
                info = entry.stat(follow_symlinks=False)
                if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    raise AutoencoderReleaseError("package namespace contains alias or special file")
                paths.append(root.joinpath(*parts))
                if stat.S_ISDIR(info.st_mode):
                    child_fd = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    try:
                        opened = os.fstat(child_fd)
                        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                            raise AutoencoderReleaseError("package directory changed during traversal")
                        visit(child_fd, parts)
                    finally:
                        os.close(child_fd)
    try:
        visit(root_fd, ())
    finally:
        os.close(root_fd)
    return tuple(paths)


def verify_release_package(root: str | Path, *, expected_manifest_sha256: str | None = None,
                           _namespace_paths: tuple[Path, ...] | None = None) -> Mapping[str, Any]:
    """Verify complete local closure without following aliases or trusting paths."""
    root = Path(root)
    _, root_fd = _open_absolute_path_nofollow_components(root, label="release package", require_directory=True)
    os.close(root_fd)
    manifest_path = root / "package-manifest.json"
    manifest_bytes = _read_regular_file_nofollow_components(
        manifest_path, label="package manifest", maximum_bytes=4 * 1024 * 1024
    )
    if expected_manifest_sha256 is not None and hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
        raise AutoencoderReleaseError("package manifest SHA-256 mismatch")
    manifest = json.loads(manifest_bytes, parse_constant=_nonfinite, object_pairs_hook=_unique_keys)
    if not isinstance(manifest, dict) or manifest.get("schema_version") not in {PACKAGE_SCHEMA, COMPACT_PACKAGE_SCHEMA} or manifest.get("required_repository_private") is not True:
        raise AutoencoderReleaseError("unsupported or non-private package manifest")
    if not isinstance(manifest.get("files"), list):
        raise AutoencoderReleaseError("package manifest requires a file list")
    seen = set()
    for entry in manifest.get("files", []):
        if not isinstance(entry, dict):
            raise AutoencoderReleaseError("invalid package file descriptor")
        name = entry.get("path")
        if not isinstance(name, str) or "\\" in name or "\x00" in name:
            raise AutoencoderReleaseError("unsafe manifest path")
        path = PurePosixPath(name)
        if path.is_absolute() or any(piece in {"", ".", ".."} for piece in name.split("/")) or name == "package-manifest.json":
            raise AutoencoderReleaseError("unsafe manifest path")
        if name in seen:
            raise AutoencoderReleaseError("duplicate manifest path")
        seen.add(name)
        if type(entry.get("size_bytes")) is not int or entry["size_bytes"] < 0:
            raise AutoencoderReleaseError("invalid package artifact byte count")
        observed = _descriptor(root.joinpath(*path.parts), name, maximum_bytes=entry["size_bytes"])
        if observed != entry:
            raise AutoencoderReleaseError(f"package file differs from manifest: {name}")
    actual = set()
    for path in root.rglob("*") if _namespace_paths is None else _namespace_paths:
        if path.is_symlink():
            raise AutoencoderReleaseError("package closure contains a symlink")
        if path.is_file() and path != manifest_path:
            actual.add(path.relative_to(root).as_posix())
    if actual != seen or not seen:
        raise AutoencoderReleaseError("package manifest does not describe the exact file closure")
    return manifest


def _package_json(path: Path, *, maximum_bytes: int = 4 * 1024 * 1024,
                  reject_secrets: bool = True) -> dict[str, Any]:
    raw = _read_regular_file_nofollow_components(path, label="package JSON", maximum_bytes=maximum_bytes)
    value = json.loads(raw, parse_constant=_nonfinite, object_pairs_hook=_unique_keys)
    if type(value) is not dict:
        raise AutoencoderReleaseError("package JSON must be an object")
    if reject_secrets:
        _reject_secrets(value, label="package JSON")
    return value


def _require_package_equal(actual: Any, expected: Any, label: str) -> None:
    # Canonical bytes distinguish booleans from integers and retain float bits
    # such as negative zero; ordinary Python container equality does not.
    if canonical_json_bytes(actual) != canonical_json_bytes(expected):
        raise AutoencoderReleaseError(f"package {label} differs from its sealed binding")


def load_private_resume_release(
    root: str | Path, *, expected_manifest_sha256: str,
    expected_version_record: Mapping[str, Any], expected_variant_manifest: Mapping[str, Any],
) -> PrivateResumeRelease:
    """Reopen verified original package bytes without regenerating a release.

    The caller supplies the owner-selected immutable version, variant and outer
    manifest digest. Descriptive historical source hashes remain descriptive;
    current native validation checks compact state semantics and exact bytes.
    No approval, visibility verification, upload or evaluation is performed.
    """
    if type(expected_manifest_sha256) is not str or not _HASH.fullmatch(expected_manifest_sha256):
        raise AutoencoderReleaseError("expected package manifest SHA-256 is required")
    version = _version_record(expected_version_record)
    if not isinstance(expected_variant_manifest, Mapping):
        raise AutoencoderReleaseError("expected variant manifest must be an object")
    variant = json.loads(canonical_json_bytes(expected_variant_manifest))
    root = Path(os.path.abspath(os.fspath(Path(root).expanduser())))
    try:
        namespace = _bounded_package_paths(root)
        initial = _package_json(root / "package-manifest.json", maximum_bytes=1024 * 1024)
        entries = initial.get("files")
        if type(entries) is not list or not 1 <= len(entries) <= 128:
            raise AutoencoderReleaseError("package file count exceeds bounded restore contract")
        if any(type(row) is not dict or type(row.get("size_bytes")) is not int
               or not 0 <= row["size_bytes"] <= MAX_COMPACT_CHECKPOINT_BYTES for row in entries):
            raise AutoencoderReleaseError("package file exceeds bounded restore contract")
        if sum(row["size_bytes"] for row in entries) > 512 * 1024 * 1024:
            raise AutoencoderReleaseError("package closure exceeds 512 MiB restore bound")
        closure = verify_release_package(root, expected_manifest_sha256=expected_manifest_sha256,
                                         _namespace_paths=namespace)
        compact = closure["schema_version"] == COMPACT_PACKAGE_SCHEMA
        schema = COMPACT_SCHEMA if compact else SCHEMA
        release_id = closure.get("release_id")
        if type(release_id) is not str or not release_id.startswith("sha256-") or not _HASH.fullmatch(release_id[7:]):
            raise AutoencoderReleaseError("invalid package release identity")
        prefix = "releases/" + release_id
        release_root = root / prefix
        _require_package_equal(closure.get("release_root"), prefix, "release root")
        provenance = _package_json(release_root / "provenance.json")
        manifest = _package_json(release_root / "release-manifest.json")
        config = _package_json(release_root / "config.json")
        raw_plan = _package_json(root / "publication-plan.json")
        _require_package_equal(provenance.get("version"), version, "registry version")
        _require_package_equal(provenance.get("variant_manifest"), variant, "variant manifest")
        evaluation_hashes = provenance.get("evaluation_receipt_sha256")
        if (type(evaluation_hashes) is not list or any(type(value) is not str or not _HASH.fullmatch(value) for value in evaluation_hashes)
                or evaluation_hashes != sorted(set(evaluation_hashes))):
            raise AutoencoderReleaseError("invalid package evaluation closure")
        for digest in evaluation_hashes:
            _, observed = _frozen_json_file(release_root / "evaluations" / (digest + ".json"))
            if observed != digest:
                raise AutoencoderReleaseError("package evaluation receipt hash differs")
        identities = provenance.get("identities")
        if type(identities) is not dict:
            raise AutoencoderReleaseError("package identities must be an object")
        logical = identities.get("logical_state_identity")
        if logical is not None and type(logical) is not dict:
            raise AutoencoderReleaseError("package logical identity must be an object")
        checkpoint_file = "state.compact" if compact else "state.json"
        artifact = _descriptor(release_root / checkpoint_file, checkpoint_file)
        _require_package_equal({"sha256": artifact["sha256"], "bytes": artifact["size_bytes"]}, version["artifact"], "checkpoint artifact")
        expected_identities = {
            "checkpoint_file_sha256": version["artifact"]["sha256"], "registry_version_id": version["version_id"],
            "logical_state_identity": logical,
            "logical_state_identity_status": "not_supplied" if logical is None else "caller_supplied_not_recomputed",
            "huggingface_commit_sha": None,
        }
        expected_provenance = {"schema_version": schema, "checkpoint_profile": PROFILE, "version": version,
                               "variant_manifest": variant, "identities": expected_identities,
                               "evaluation_receipt_sha256": evaluation_hashes}
        expected_config = {
            "schema_version": "autoencoder-private-resume-config/v2" if compact else "autoencoder-private-resume-config/v1",
            "checkpoint_profile": PROFILE, "checkpoint_file": checkpoint_file, "original_loader_required": True,
            "tensor_migration_performed": False, "key_sanitization_performed": False, "sample_memory_removed": False,
            "variant_manifest": variant, "parameter_schema_status": "preserved_original_not_migrated", "admitted": False,
        }
        checkpoint = None
        if compact:
            if type(logical) is not dict:
                raise AutoencoderReleaseError("compact package requires its native logical identity")
            checkpoint = provenance.get("checkpoint")
            current = _compact_checkpoint_description(release_root / checkpoint_file, version["artifact"], logical)
            if type(checkpoint) is not dict or current is None:
                raise AutoencoderReleaseError("package compact checkpoint description is missing")
            historical = checkpoint.get("source_provenance")
            source_names = set(current["source_provenance"]["sha256"])
            if (type(historical) is not dict or set(historical) != {"scope", "sha256"}
                    or historical["scope"] != "descriptive_files_not_runtime_attestation"
                    or type(historical["sha256"]) is not dict or set(historical["sha256"]) != source_names
                    or any(type(value) is not str or not _HASH.fullmatch(value) for value in historical["sha256"].values())):
                raise AutoencoderReleaseError("invalid historical checkpoint source provenance")
            _require_package_equal(checkpoint, {**current, "source_provenance": historical}, "native compact description")
            expected_identities.update(logical_state_identity_status="native_compact_recomputed",
                                       metric_state_identity=current["metric_state_identity"])
            expected_provenance["checkpoint"] = checkpoint
            expected_config["checkpoint"] = checkpoint
        else:
            # Preserve the original JSON profile; it does not claim native
            # recomputation of caller-supplied logical identity.
            legacy = _package_json(release_root / checkpoint_file, maximum_bytes=version["artifact"]["bytes"], reject_secrets=False)
            from ..optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import SCHEMA as SPARSE_CHECKPOINT_SCHEMA
            if legacy.get("schema") == SPARSE_CHECKPOINT_SCHEMA:
                raise AutoencoderReleaseError("sparse checkpoints require verified full materialization")
        _require_package_equal(provenance, expected_provenance, "provenance")
        _require_package_equal(config, expected_config, "configuration")
        if release_id != "sha256-" + hashlib.sha256(canonical_json_bytes(provenance)).hexdigest():
            raise AutoencoderReleaseError("package release identity differs from provenance")
        release_names = sorted(["README.md", "config.json", "provenance.json", checkpoint_file,
                                *("evaluations/" + digest + ".json" for digest in evaluation_hashes)])
        release_files = [_descriptor(release_root / name, name) for name in release_names]
        expected_manifest = {
            "schema_version": schema, "release_id": release_id, "checkpoint_profile": PROFILE,
            "required_repository_private": True, "identities": expected_identities,
            "admitted": False, "constitution_formalized": False,
            "evaluation_status": "supplied_not_revalidated" if evaluation_hashes else "not_supplied",
            "files": release_files,
        }
        if compact:
            expected_manifest["checkpoint"] = checkpoint
        _require_package_equal(manifest, expected_manifest, "release manifest")
        _require_package_equal(_descriptor(root / "README.md", "README.md"),
                               _descriptor(release_root / "README.md", "README.md"), "model card copies")
        profile = private_resume_publication_profile(raw_plan.get("repository_id"),
            checkpoint_format="modal_autoencoder_compact" if compact else "legacy_json")
        plan_fields = {field.name for field in fields(PublicationPlan)}
        # The constructor recomputes the digest; to_dict verifies redundant
        # totals/flags and rejects unknown or silently normalized fields.
        plan = PublicationPlan(**{key: (tuple(PublicationFilePlan(**row) for row in value) if key == "operations"
                                  else tuple(value) if key in {"existing_remote_paths", "skipped_exact_matches", "prohibited_operations"} else value)
                                  for key, value in raw_plan.items() if key in plan_fields})
        _require_package_equal(plan.to_dict(), raw_plan, "publication plan roundtrip")
        all_release_files = sorted([*release_files, _descriptor(release_root / "release-manifest.json", "release-manifest.json")], key=lambda row: row["path"])
        expected_operations = [{"relative_path": row["path"], "remote_path": prefix + "/" + row["path"],
                                "size_bytes": row["size_bytes"], "sha256": row["sha256"], "operation": "add"}
                               for row in all_release_files]
        _require_package_equal([row.to_dict() for row in plan.operations], expected_operations, "publication operations")
        metadata = {"canonical_release_manifest_included": False, "canonical_release_manifest_sha256": "",
                    "dry_run_diff_and_cost_receipt": True, "goal_id": profile.goal_id, "never_skip_by_basename": True,
                    "never_delete_or_rewrite_legacy": True, "profile_id": profile.profile_id, "program_id": profile.program_id,
                    "checkpoint_profile": PROFILE, "required_repository_private": True, "remote_privacy_verified": False,
                    "remote_inventory_checked": False, "autoencoder_release_manifest_included": True,
                    "root_model_card_publication": "separate_reviewed_bootstrap_or_cas_required",
                    "approval_status": "exact_plan_human_approval_required", "upload_ready": False,
                    "cost_rates_status": "publisher_defaults_are_illustrative_not_a_huggingface_quote", "admitted": False}
        if compact:
            metadata.update(checkpoint_format=checkpoint["format"], checkpoint_file=checkpoint_file,
                            checkpoint_schema_version=checkpoint["schema_version"])
        _require_package_equal(plan.metadata, metadata, "publication authority metadata")
        _require_package_equal([plan.schema_version, plan.repository_type, plan.release_id, plan.release_prefix,
                               plan.release_sha256, plan.target_revision, list(plan.existing_remote_paths),
                               list(plan.skipped_exact_matches), list(plan.prohibited_operations)],
                              [profile.plan_schema_version, "model", release_id, prefix,
                               _descriptor(release_root / "release-manifest.json", "release-manifest.json")["sha256"],
                               "main", [], [], sorted(profile.prohibited_operations)], "publication profile")
        rates = [plan.cost_receipt[name] for name in ("transfer_rate_usd_per_gib", "storage_rate_usd_per_gib_month")]
        if any(type(rate) not in {int, float} or not math.isfinite(rate) or rate < 0 for rate in rates):
            raise AutoencoderReleaseError("invalid sealed publication cost rates")
        total = sum(row["size_bytes"] for row in all_release_files)
        _require_package_equal(plan.cost_receipt, estimate_publication_cost(upload_bytes=total, retained_release_bytes=total,
            transfer_rate_usd_per_gib=rates[0], storage_rate_usd_per_gib_month=rates[1]), "publication costs")
        package_names = sorted(["README.md", "publication-plan.json", *(prefix + "/" + row["path"] for row in all_release_files)])
        _require_package_equal(closure, {"schema_version": COMPACT_PACKAGE_SCHEMA if compact else PACKAGE_SCHEMA,
            "release_id": release_id, "release_root": prefix, "required_repository_private": True, "admitted": False,
            "publication_plan_digest": plan.plan_digest, "files": [_descriptor(root / name, name) for name in package_names]},
            "outer manifest")
        verify_release_package(root, expected_manifest_sha256=expected_manifest_sha256,
                               _namespace_paths=_bounded_package_paths(root))
        return PrivateResumeRelease(root, release_root, profile, plan, expected_manifest_sha256)
    except AutoencoderReleaseError:
        raise
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise AutoencoderReleaseError("invalid sealed private resume package") from exc
