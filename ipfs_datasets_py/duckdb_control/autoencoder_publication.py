"""Durable, offline selected-version packaging and HF publication intents.

The owner freezes complete private packages into CAS before enqueueing a small
intent. Offline restoration never acknowledges that intent, uploads files,
constructs an approval, promotes a head, or supplies proof/quality evidence.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import uuid

from .autoencoder_registry import AutoencoderRegistry, SCHEMA as REGISTRY_SCHEMA, _artifact, _token
from .contracts import canonical_json_bytes, content_identity
from ..huggingface.autoencoder_release import (
    build_private_resume_release, load_private_resume_release,
    private_resume_publication_profile, _bounded_package_paths, _nonfinite, _unique_keys,
)
from ..huggingface.publisher import (
    _open_absolute_path_nofollow_components, _reject_secrets, _commit_sha,
)

SCHEMA = "autoencoder-private-publication-preparation-v1"
JOURNAL_SCHEMA = "autoencoder-private-publication-journal-v1"
ENVELOPE_SCHEMA = "autoencoder-private-publication-envelope-v1"
MAX_CONTROL_BYTES = 4 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 256 * 1024 * 1024
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
MAX_FILES = 128
MAX_EVALUATIONS = 16
METADATA_ALLOWANCE_BYTES = 8 * 1024 * 1024


class AutoencoderPublicationError(ValueError):
    """An offline package or its durable owner binding cannot be verified."""


def _copy(value):
    return json.loads(canonical_json_bytes(value))


def _same(left, right):
    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _owner(registry):
    if type(registry) is not AutoencoderRegistry:
        raise AutoencoderPublicationError("publication preparation requires the actual registry owner")
    return {"database_path": str(registry.database_path), "artifact_root": str(registry.artifact_root)}


def _canonical_path(value):
    path = Path(os.path.abspath(os.fspath(value)))
    if path != path.resolve():
        raise AutoencoderPublicationError("publication path must not contain aliases")
    _, fd = _open_absolute_path_nofollow_components(path.parent, label="publication parent", require_directory=True)
    os.close(fd)
    return path


def _relative(value):
    if (type(value) is not str or not 0 < len(value.encode()) <= 1024 or "\\" in value or "\x00" in value
            or PurePosixPath(value).is_absolute() or len(value.split("/")) > 8
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise AutoencoderPublicationError("unsafe package-relative path")
    return value


def _fsync_directory(path):
    _, fd = _open_absolute_path_nofollow_components(path, label="publication directory", require_directory=True)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _save(path, value):
    raw = canonical_json_bytes(value) + b"\n"
    if len(raw) > MAX_CONTROL_BYTES:
        raise AutoencoderPublicationError("publication control record exceeds byte bound")
    temporary = path.with_name(".publication-" + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path, *, maximum=MAX_CONTROL_BYTES):
    _, fd = _open_absolute_path_nofollow_components(path, label="publication record", require_directory=False)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= maximum:
            raise AutoencoderPublicationError("publication record is not a bounded regular file")
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise AutoencoderPublicationError("publication record exceeds byte bound")
    value = json.loads(raw, parse_constant=_nonfinite, object_pairs_hook=_unique_keys)
    if type(value) is not dict or canonical_json_bytes(value) + b"\n" != raw:
        raise AutoencoderPublicationError("publication record is not a canonical object")
    return value


def _file_ref(path):
    _, fd = _open_absolute_path_nofollow_components(path, label="package file", require_directory=False)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_PACKAGE_BYTES:
            raise AutoencoderPublicationError("package file is not a bounded regular file")
        digest, size = hashlib.sha256(), 0
        while block := stream.read(1024 * 1024):
            size += len(block)
            if size > info.st_size:
                raise AutoencoderPublicationError("package file changed while hashing")
            digest.update(block)
    if size != info.st_size:
        raise AutoencoderPublicationError("package file changed while hashing")
    return {"sha256": digest.hexdigest(), "bytes": size}


def _evaluations(values):
    if type(values) not in (tuple, list) or len(values) > MAX_EVALUATIONS:
        raise AutoencoderPublicationError("at most sixteen evaluation artifacts are supported")
    result = [_artifact(value) for value in values]
    if any(item["bytes"] > MAX_CONTROL_BYTES for item in result):
        raise AutoencoderPublicationError("evaluation artifact exceeds 4 MiB")
    result.sort(key=lambda item: item["sha256"])
    if len({item["sha256"] for item in result}) != len(result):
        raise AutoencoderPublicationError("duplicate evaluation artifact")
    return result


@contextmanager
def _journal(directory, binding):
    directory = _canonical_path(directory)
    directory.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(directory / "owner.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise AutoencoderPublicationError("publication lock must be a private regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AutoencoderPublicationError("publication directory already has an owner") from exc
        path = directory / "preparation.json"
        if path.exists():
            data = _read(path)
            if (set(data) != {"schema", "binding", "version", "variant", "bundle_ref", "result"}
                    or data["schema"] != JOURNAL_SCHEMA or not _same(data["binding"], binding)):
                raise AutoencoderPublicationError("publication journal binding differs")
        else:
            if {item.name for item in directory.iterdir()} != {"owner.lock"}:
                raise AutoencoderPublicationError("nonempty directory has no publication journal")
            data = {"schema": JOURNAL_SCHEMA, "binding": _copy(binding), "version": None,
                    "variant": None, "bundle_ref": None, "result": None}
            _save(path, data)
        yield directory, path, data
    finally:
        os.close(fd)


def _selected(registry, version_id):
    version = registry.get_version(version_id)
    variant = registry.get_variant(version["variant_id"])
    return version, variant


def _package_files(package, budget, manifest_ref):
    # Strong reopening validates the file closure; this enumeration additionally
    # bounds the copied namespace, including otherwise unlisted empty directories.
    files, count, total = [], 0, 0
    for path in _bounded_package_paths(package):
        count += 1
        if count > MAX_FILES * 2 or path.is_symlink():
            raise AutoencoderPublicationError("package namespace exceeds bounds or contains aliases")
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise AutoencoderPublicationError("package closure contains a non-regular file")
        name = _relative(path.relative_to(package).as_posix())
        descriptor = _file_ref(path)
        total += descriptor["bytes"]
        if len(files) >= MAX_FILES or total > budget:
            raise AutoencoderPublicationError("package closure exceeds count or byte bound")
        files.append({"path": name, "artifact": descriptor})
    files.sort(key=lambda row: row["path"])
    manifest_path = package / "package-manifest.json"
    manifest = _read(manifest_path, maximum=1024 * 1024)
    raw = canonical_json_bytes(manifest) + b"\n"
    if not _same({"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}, manifest_ref):
        raise AutoencoderPublicationError("package manifest changed after verification")
    expected = [{"path": _relative(row["path"]),
                 "artifact": {"sha256": row["sha256"], "bytes": row["size_bytes"]}}
                for row in manifest["files"]]
    expected.append({"path": "package-manifest.json", "artifact": manifest_ref})
    expected.sort(key=lambda row: row["path"])
    if not _same(files, expected):
        raise AutoencoderPublicationError("package inventory differs from verified manifest closure")
    return files


def _require_selected_package(release, request, files):
    plan = release.publication_plan
    if plan.repository_id != request["repo_id"] or plan.audited_parent_commit != request["audited_parent_commit"]:
        raise AutoencoderPublicationError("package destination or parent differs from frozen request")
    prefix = release.release_root.relative_to(release.package_root).as_posix() + "/evaluations/"
    observed = sorted([entry["artifact"] for entry in files if entry["path"].startswith(prefix)],
                      key=lambda item: item["sha256"])
    if not _same(observed, request["evaluation_artifacts"]):
        raise AutoencoderPublicationError("package evaluations differ from frozen request")


def _require_bundle_package(release, bundle):
    plan = release.publication_plan
    if (plan.plan_digest != bundle["publication_plan_digest"] or plan.release_id != bundle["release_id"]
            or release.release_root.relative_to(release.package_root).as_posix() != bundle["release_root"]):
        raise AutoencoderPublicationError("package differs from its frozen publication plan")
    files = _package_files(release.package_root, bundle["max_package_bytes"], bundle["package_manifest"])
    if not _same(files, bundle["files"]):
        raise AutoencoderPublicationError("package differs from frozen envelope inventory")
    _require_selected_package(release, {"repo_id": bundle["repository_id"],
        "audited_parent_commit": bundle["audited_parent_commit"],
        "evaluation_artifacts": bundle["evaluation_artifacts"]}, files)


def _load_bundle(registry, descriptor, *, version_id):
    descriptor = _artifact(descriptor)
    if descriptor["bytes"] > MAX_CONTROL_BYTES:
        raise AutoencoderPublicationError("publication envelope exceeds byte bound")
    registry.verify_artifact(descriptor)
    value = _read(registry.artifact_path(descriptor))
    raw = canonical_json_bytes(value) + b"\n"
    if not _same({"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}, descriptor):
        raise AutoencoderPublicationError("parsed publication envelope differs from CAS descriptor")
    fields = {"schema", "owner", "version", "variant", "repository_id", "required_repository_private",
              "audited_parent_commit", "evaluation_artifacts", "package_manifest", "publication_plan_digest",
              "release_id", "release_root", "files", "max_package_bytes", "uploaded", "admitted"}
    if (set(value) != fields or value["schema"] != ENVELOPE_SCHEMA
            or not _same(value["owner"], _owner(registry))
            or value["required_repository_private"] is not True
            or value["uploaded"] is not False or value["admitted"] is not False):
        raise AutoencoderPublicationError("publication envelope binding or shape differs")
    version, variant = _selected(registry, version_id)
    if not _same(value["version"], version) or not _same(value["variant"], variant):
        raise AutoencoderPublicationError("publication envelope differs from selected immutable records")
    if version["artifact"]["bytes"] > MAX_CHECKPOINT_BYTES:
        raise AutoencoderPublicationError("checkpoint exceeds the 256 MiB package input bound")
    budget = value["max_package_bytes"]
    if type(budget) is not int or not 1 <= budget <= MAX_PACKAGE_BYTES:
        raise AutoencoderPublicationError("invalid package byte bound")
    files = value["files"]
    if type(files) is not list or not 1 <= len(files) <= MAX_FILES:
        raise AutoencoderPublicationError("invalid package file inventory")
    previous, total, by_name = None, 0, {}
    for item in files:
        if type(item) is not dict or set(item) != {"path", "artifact"}:
            raise AutoencoderPublicationError("invalid package file descriptor")
        name, artifact = _relative(item["path"]), _artifact(item["artifact"])
        if artifact["bytes"] > MAX_CHECKPOINT_BYTES:
            raise AutoencoderPublicationError("package file exceeds the restore byte bound")
        if previous is not None and name <= previous:
            raise AutoencoderPublicationError("package paths must be distinct and sorted")
        previous = name
        total += artifact["bytes"]
        by_name[name] = artifact
    if total > budget or not _same(by_name.get("package-manifest.json"), value["package_manifest"]):
        raise AutoencoderPublicationError("package manifest or aggregate byte bound differs")
    if not _same(_evaluations(value["evaluation_artifacts"]), value["evaluation_artifacts"]):
        raise AutoencoderPublicationError("noncanonical evaluation inventory")
    _relative(value["release_root"])
    private_resume_publication_profile(value["repository_id"])
    if value["audited_parent_commit"]:
        _commit_sha(value["audited_parent_commit"], label="audited_parent_commit")
    return value


def _copy_cas_file(registry, descriptor, target):
    source = registry.artifact_path(descriptor)
    _, fd = _open_absolute_path_nofollow_components(source, label="CAS package file", require_directory=False)
    digest, size = hashlib.sha256(), 0
    with os.fdopen(fd, "rb") as incoming:
        if os.fstat(incoming.fileno()).st_size != descriptor["bytes"]:
            raise AutoencoderPublicationError("CAS package file size differs")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(target_fd, "wb") as outgoing:
            while block := incoming.read(1024 * 1024):
                size += len(block)
                if size > descriptor["bytes"]:
                    raise AutoencoderPublicationError("CAS package file grew during copy")
                outgoing.write(block)
                digest.update(block)
            outgoing.flush()
            os.fsync(outgoing.fileno())
    if size != descriptor["bytes"] or digest.hexdigest() != descriptor["sha256"]:
        raise AutoencoderPublicationError("CAS package file digest differs")


def _restore(registry, bundle, destination):
    destination = _canonical_path(destination)
    destination.mkdir(mode=0o700, exist_ok=False)
    for item in bundle["files"]:
        _copy_cas_file(registry, item["artifact"], destination / item["path"])
    release = load_private_resume_release(destination,
        expected_manifest_sha256=bundle["package_manifest"]["sha256"],
        expected_version_record=bundle["version"], expected_variant_manifest=bundle["variant"]["manifest"])
    _require_bundle_package(release, bundle)
    for path in sorted((path for path in _bounded_package_paths(destination) if path.is_dir()),
                       key=lambda path: len(path.parts), reverse=True):
        _fsync_directory(path)
    _fsync_directory(destination)
    _fsync_directory(destination.parent)
    return release


def restore_autoencoder_publication(registry, *, event_id, destination):
    """Restore a fresh exact local package; never claim/ack/upload the intent.

    An incomplete destination remains visible on failure and is never silently
    overwritten. The package manifest is not a completion assertion: only a
    successful full verification and directory fsync returns a release handle.
    """
    _owner(registry)
    event = registry.get_outbox_event("huggingface", event_id)
    if (event["kind"] != "publication_requested"
            or set(event["payload"]) != {"version_id", "plan_artifact"}):
        raise AutoencoderPublicationError("event is not an exact publication request")
    payload = event["payload"]
    bundle = _load_bundle(registry, payload["plan_artifact"], version_id=payload["version_id"])
    return _restore(registry, bundle, destination)


def _queued_result(operation_id, version_id, descriptor, receipt):
    if (type(receipt) is not dict or set(receipt) != {"schema", "operation_id", "command", "admitted", "event_id", "uploaded"}
            or receipt["schema"] != REGISTRY_SCHEMA
            or receipt["operation_id"] != operation_id or receipt["command"] != "EnqueuePublication"
            or receipt["event_id"] != content_identity({"operation_id": operation_id,
                "kind": "publication_requested", "consumer": "huggingface"})
            or receipt["admitted"] is not False or receipt["uploaded"] is not False):
        raise AutoencoderPublicationError("enqueue receipt differs from the frozen operation")
    return {"schema": SCHEMA, "status": "queued", "version_id": version_id,
            "plan_artifact": descriptor, "event_id": receipt["event_id"],
            "operation_receipt": receipt, "uploaded": False, "admitted": False}


def prepare_autoencoder_publication(registry, *, operation_id, version_id, repo_id,
                                    output_directory, evaluation_artifacts=(),
                                    audited_parent_commit="", max_package_bytes=MAX_PACKAGE_BYTES):
    """Freeze, CAS-stage and enqueue one explicit version, entirely offline.

    Same-directory retries bind exactly the original request. If enqueue already
    committed, return its historical receipt even if artifacts later disappear;
    that is not a current restoration/availability claim. Partial packages are
    retained and rejected, not overwritten or rebuilt against a different head.
    Closure limits are local bounds, not an RSS/global disk quota; the invoking
    scheduler must reserve package, CAS, staging and restore space separately.
    """
    owner = _owner(registry)
    _token(operation_id, "operation_id")
    _token(version_id, "version_id")
    private_resume_publication_profile(repo_id)
    if type(max_package_bytes) is not int or not 1 <= max_package_bytes <= MAX_PACKAGE_BYTES:
        raise AutoencoderPublicationError("package byte bound must be within 512 MiB")
    if audited_parent_commit:
        _commit_sha(audited_parent_commit, label="audited_parent_commit")
    request = {"operation_id": operation_id, "version_id": version_id, "repo_id": repo_id,
               "audited_parent_commit": audited_parent_commit,
               "evaluation_artifacts": _evaluations(evaluation_artifacts), "max_package_bytes": max_package_bytes}
    _reject_secrets(request, label="publication request")
    with _journal(output_directory, {"owner": owner, "request": request}) as (directory, path, journal):
        descriptor = journal["bundle_ref"]
        if descriptor is not None:
            descriptor = _artifact(descriptor)
            payload = {"version_id": version_id, "plan_artifact": descriptor}
            old = registry.resolve_operation(operation_id, "EnqueuePublication", payload)
            if old is not None:
                result = _queued_result(operation_id, version_id, descriptor, old)
                if journal["result"] is not None and not _same(journal["result"], result):
                    raise AutoencoderPublicationError("recorded result differs from durable enqueue receipt")
                journal["result"] = result
                _save(path, journal)
                return _copy(result)
        if journal["result"] is not None:
            raise AutoencoderPublicationError("recorded result has no durable enqueue operation")
        version, variant = _selected(registry, version_id)
        if journal["version"] is None and journal["variant"] is None:
            journal["version"], journal["variant"] = version, variant
            _save(path, journal)
        elif not _same(journal["version"], version) or not _same(journal["variant"], variant):
            raise AutoencoderPublicationError("journal differs from selected immutable version or variant")
        package = directory / "package"
        if descriptor is None:
            minimum = version["artifact"]["bytes"] + sum(item["bytes"] for item in request["evaluation_artifacts"])
            if version["artifact"]["bytes"] > MAX_CHECKPOINT_BYTES or minimum + METADATA_ALLOWANCE_BYTES > max_package_bytes:
                raise AutoencoderPublicationError("insufficient package byte allowance before build")
            registry.verify_artifact(version["artifact"])
            for item in request["evaluation_artifacts"]:
                registry.verify_artifact(item)
            if not package.exists():
                release = build_private_resume_release(version, registry.artifact_path(version["artifact"]), package,
                    repo_id=repo_id, variant_manifest=variant["manifest"],
                    evaluation_receipts=[registry.artifact_path(item) for item in request["evaluation_artifacts"]],
                    audited_parent_commit=audited_parent_commit)
                manifest_ref = _file_ref(package / "package-manifest.json")
            else:
                manifest_ref = _file_ref(package / "package-manifest.json")
            release = load_private_resume_release(package, expected_manifest_sha256=manifest_ref["sha256"],
                expected_version_record=version, expected_variant_manifest=variant["manifest"])
            files = _package_files(package, max_package_bytes, manifest_ref)
            _require_selected_package(release, request, files)
            for entry in files:
                staged = registry.stage_artifact(package / entry["path"], expected_sha256=entry["artifact"]["sha256"])
                if not _same(staged, entry["artifact"]):
                    raise AutoencoderPublicationError("staged package file differs from verified closure")
            bundle = {"schema": ENVELOPE_SCHEMA, "owner": owner, "version": version, "variant": variant,
                "repository_id": repo_id, "required_repository_private": True,
                "audited_parent_commit": audited_parent_commit, "evaluation_artifacts": request["evaluation_artifacts"],
                "package_manifest": manifest_ref, "publication_plan_digest": release.publication_plan.plan_digest,
                "release_id": release.publication_plan.release_id,
                "release_root": release.release_root.relative_to(package).as_posix(),
                "files": files, "max_package_bytes": max_package_bytes, "uploaded": False, "admitted": False}
            release = load_private_resume_release(package, expected_manifest_sha256=manifest_ref["sha256"],
                expected_version_record=version, expected_variant_manifest=variant["manifest"])
            _require_bundle_package(release, bundle)
            envelope_path = directory / "publication-envelope.json"
            envelope_bytes = canonical_json_bytes(bundle) + b"\n"
            envelope_ref = {"sha256": hashlib.sha256(envelope_bytes).hexdigest(), "bytes": len(envelope_bytes)}
            _save(envelope_path, bundle)
            descriptor = registry.stage_artifact(envelope_path, expected_sha256=envelope_ref["sha256"])
            if not _same(descriptor, envelope_ref):
                raise AutoencoderPublicationError("staged envelope differs from frozen content")
            journal["bundle_ref"] = descriptor
            _save(path, journal)  # Exact operation payload is durable before send.
        else:
            bundle = _load_bundle(registry, descriptor, version_id=version_id)
            if (bundle["repository_id"] != repo_id or bundle["audited_parent_commit"] != audited_parent_commit
                    or not _same(bundle["evaluation_artifacts"], request["evaluation_artifacts"])
                    or bundle["max_package_bytes"] != max_package_bytes):
                raise AutoencoderPublicationError("frozen envelope differs from request")
            if not package.exists():
                _restore(registry, bundle, package)
            else:
                release = load_private_resume_release(package, expected_manifest_sha256=bundle["package_manifest"]["sha256"],
                    expected_version_record=version, expected_variant_manifest=variant["manifest"])
                _require_bundle_package(release, bundle)
            for entry in bundle["files"]:
                registry.verify_artifact(entry["artifact"])
        payload = {"version_id": version_id, "plan_artifact": descriptor}
        try:
            receipt = registry.enqueue_publication(operation_id, version_id, descriptor)
        except Exception:
            receipt = registry.resolve_operation(operation_id, "EnqueuePublication", payload)
            if receipt is None:
                raise
        result = _queued_result(operation_id, version_id, descriptor, receipt)
        journal["result"] = result
        _save(path, journal)
        return _copy(result)
