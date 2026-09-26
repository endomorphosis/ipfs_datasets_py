"""Bounded offline selected-campaign packages preserving original artifact bytes.

These are evidence packages, not executable campaign imports or model releases.
No registry, publication, credentials, network, model or training API is called.
Original absolute locators remain historical data; reopening resolves bare
content descriptors exclusively inside the exact package namespace.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Callable, Mapping

from .publisher import _open_absolute_path_nofollow_components

SCHEMA_VERSION = "autoencoder-selected-campaign-package-v1"
REPORT_SCHEMA_VERSION = "autoencoder-selected-campaign-package-report-v1"
COVERAGE_SCOPE = "selected_campaign_page"
MANIFEST_NAME = "campaign-package.json"
_HASH = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1024 * 1024
_INPUT_FIELDS = ("generation_artifact", "plan_artifact", "variant_record", "version_records", "run_records")
_MANIFEST_FIELDS = {"schema_version", "coverage_scope", *_INPUT_FIELDS,
    "artifacts", "coverage", "limits", "qualification"}


class CampaignPackageError(ValueError):
    """The requested package, namespace, closure or current bytes are invalid."""


@dataclass(frozen=True)
class CampaignPackageLimits:
    """Caller limits may tighten, but never increase, the format's ceilings."""

    max_control_bytes: int = 4 * 1024**2
    max_blobs: int = 4096
    max_blob_bytes: int = 256 * 1024**2
    max_total_bytes: int = 512 * 1024**2
    max_directories: int = 257
    max_namespace_entries: int = 4354
    max_path_depth: int = 3
    max_path_bytes: int = 128

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or not 1 <= value <= field.default:
                raise CampaignPackageError(f"invalid package limit: {field.name}")


def _package_errors(operation):
    @wraps(operation)
    def guarded(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except CampaignPackageError:
            raise
        except (ValueError, TypeError, KeyError, OSError, RecursionError) as exc:
            raise CampaignPackageError("campaign package validation failed: " + str(exc)) from exc
    return guarded


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CampaignPackageError(message)


def _limits(value: CampaignPackageLimits) -> CampaignPackageLimits:
    _require(type(value) is CampaignPackageLimits, "actual package limits required")
    # Reconstruct to reject a frozen instance changed through object.__setattr__.
    return CampaignPackageLimits(**asdict(value))


def _canonical(value: Any, maximum: int) -> bytes:
    chunks, size = [], 0
    try:
        encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("utf-8")
            size += len(encoded)
            _require(size <= maximum, "control JSON exceeds its byte bound")
            chunks.append(encoded)
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise CampaignPackageError("package control must be bounded finite JSON") from exc
    return b"".join(chunks)


def _parse(raw: bytes) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate control JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise CampaignPackageError("nonfinite control JSON constant")

    try:
        result = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CampaignPackageError("invalid package control JSON") from exc
    _require(type(result) is dict, "package control must be an object")
    return result


def _clone(value: Any, maximum: int) -> Any:
    return json.loads(_canonical(value, maximum))


def _same(left: Any, right: Any, maximum: int) -> bool:
    return _canonical(left, maximum) == _canonical(right, maximum)


def _ref(value: Any, limits: CampaignPackageLimits) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == {"sha256", "bytes"}, "bare artifact descriptor required")
    _require(type(value["sha256"]) is str and _HASH.fullmatch(value["sha256"]) is not None
        and type(value["bytes"]) is int and 0 <= value["bytes"] <= limits.max_blob_bytes,
        "artifact descriptor exceeds package bounds")
    return dict(value)


def _relative(value: str, limits: CampaignPackageLimits) -> str:
    _require(type(value) is str and 0 < len(value.encode("utf-8")) <= limits.max_path_bytes
        and "\\" not in value and "\x00" not in value
        and len(value.split("/")) <= limits.max_path_depth
        and all(part not in {"", ".", ".."} for part in value.split("/")), "unsafe package relative path")
    return value


def _blob_name(ref: Mapping[str, Any]) -> str:
    return "blobs/" + ref["sha256"][:2] + "/" + ref["sha256"]


def _absolute(value: str | Path, *, resolver: bool = False) -> Path:
    try:
        candidate = Path(value)
        if resolver:
            _require(candidate.is_absolute() and str(candidate) == os.path.abspath(candidate),
                "resolver must return an absolute normalized path")
        return Path(os.path.abspath(candidate))
    except (TypeError, ValueError, OSError) as exc:
        raise CampaignPackageError("invalid local package path") from exc


def _directory(path: Path) -> int:
    try:
        _, fd = _open_absolute_path_nofollow_components(path, label="campaign package directory", require_directory=True)
        return fd
    except (ValueError, OSError) as exc:
        raise CampaignPackageError("package directory contains an alias or cannot be opened") from exc


def _regular(path: Path) -> int:
    # The existing component-safe primitive is used for directories. A separate
    # nonblocking final open makes a malicious FIFO fail instead of blocking.
    parent_fd = _directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent_fd)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise CampaignPackageError("package artifact is not a regular file")
        return fd
    except OSError as exc:
        raise CampaignPackageError("package artifact cannot be opened without aliases") from exc
    finally:
        os.close(parent_fd)


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _current_file(path: Path, info: os.stat_result) -> None:
    fd = _regular(path)
    try:
        _require(_identity(os.fstat(fd)) == _identity(info), "artifact pathname changed while reading")
    finally:
        os.close(fd)


def _hash_file(path: Path, ref: Mapping[str, Any]) -> None:
    fd = _regular(path)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        _require(before.st_size == ref["bytes"], "artifact byte count differs")
        digest, size = hashlib.sha256(), 0
        while chunk := source.read(min(_CHUNK, ref["bytes"] - size + 1)):
            size += len(chunk)
            _require(size <= ref["bytes"], "artifact grew while hashing")
            digest.update(chunk)
        after = os.fstat(source.fileno())
        _require(_identity(before) == _identity(after), "artifact changed while hashing")
    _require(size == ref["bytes"] and digest.hexdigest() == ref["sha256"], "artifact digest differs")
    _current_file(path, after)


def _read_control(path: Path, maximum: int) -> bytes:
    fd = _regular(path)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        _require(0 < before.st_size <= maximum, "package control exceeds byte bound")
        raw = source.read(maximum + 1)
        after = os.fstat(source.fileno())
        _require(len(raw) == before.st_size and _identity(before) == _identity(after), "package control changed while reading")
    _current_file(path, after)
    return raw


def _namespace(root: Path, limits: CampaignPackageLimits) -> dict[str, tuple[int, ...]]:
    """Bound names/stat only, including empty directories, before payload reads."""
    root_fd = _directory(root)
    found: dict[str, tuple[int, ...]] = {}
    directory_count = file_count = payload_bytes = 0
    root_identity = _identity(os.fstat(root_fd))

    def visit(fd: int, prefix: tuple[str, ...]) -> None:
        nonlocal directory_count, file_count, payload_bytes
        before = os.fstat(fd)
        with os.scandir(fd) as entries:
            for entry in entries:
                _require(len(found) < limits.max_namespace_entries, "package namespace entry limit exceeded")
                parts = (*prefix, entry.name)
                name = _relative("/".join(parts), limits)
                info = entry.stat(follow_symlinks=False)
                _require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode), "package namespace contains aliases or special files")
                found[name] = _identity(info)
                if stat.S_ISDIR(info.st_mode):
                    directory_count += 1
                    _require(directory_count <= limits.max_directories, "package directory limit exceeded")
                    child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                    try:
                        _require(_identity(os.fstat(child)) == _identity(info), "directory changed during traversal")
                        visit(child, parts)
                    finally:
                        os.close(child)
                else:
                    file_count += 1
                    _require(file_count <= limits.max_blobs + 1, "package file limit exceeded")
                    if name == MANIFEST_NAME:
                        _require(0 < info.st_size <= limits.max_control_bytes, "package control exceeds byte bound")
                    else:
                        _require(info.st_size <= limits.max_blob_bytes, "package blob exceeds byte bound")
                        payload_bytes += info.st_size
                        _require(payload_bytes <= limits.max_total_bytes, "package payload exceeds aggregate byte bound")
        _require(_identity(os.fstat(fd)) == _identity(before), "directory changed during traversal")

    try:
        visit(root_fd, ())
        _require(_identity(os.fstat(root_fd)) == root_identity, "package root changed during traversal")
        current = _directory(root)
        try:
            _require(_identity(os.fstat(current)) == root_identity, "package root pathname changed during traversal")
        finally:
            os.close(current)
    except OSError as exc:
        raise CampaignPackageError("package namespace changed or cannot be traversed") from exc
    finally:
        os.close(root_fd)
    return found


def _artifacts(value: Any, limits: CampaignPackageLimits) -> list[dict[str, Any]]:
    _require(type(value) is list and 1 <= len(value) <= limits.max_blobs, "invalid typed artifact inventory")
    previous, total, result = None, 0, []
    for item in value:
        _require(type(item) is dict and set(item) == {"sha256", "bytes", "roles"}, "invalid typed artifact fields")
        ref = _ref({name: item[name] for name in ("sha256", "bytes")}, limits)
        _require(previous is None or previous < ref["sha256"], "typed artifacts must be distinct and SHA sorted")
        previous = ref["sha256"]
        roles = item["roles"]
        _require(type(roles) is list and 1 <= len(roles) <= limits.max_blobs
            and all(type(role) is str and 0 < len(role.encode("utf-8")) <= 1024 for role in roles)
            and roles == sorted(set(roles)), "typed dependency roles must be distinct bounded sorted strings")
        total += ref["bytes"]
        _require(total <= limits.max_total_bytes, "typed closure exceeds aggregate package bytes")
        result.append({**ref, "roles": list(roles)})
    return result


def _expected_namespace(artifacts: list[dict[str, Any]], limits: CampaignPackageLimits) -> tuple[set[str], set[str]]:
    files = {MANIFEST_NAME}
    directories = {"blobs"}
    for ref in artifacts:
        files.add(_relative(_blob_name(ref), limits))
        directories.add("blobs/" + ref["sha256"][:2])
    for name in files | directories:
        _relative(name, limits)
    _require(len(files) + len(directories) <= limits.max_namespace_entries
        and len(directories) <= limits.max_directories, "derived package namespace exceeds limits")
    return files, directories


def _require_namespace(found, artifacts, limits):
    files, directories = _expected_namespace(artifacts, limits)
    actual_files = {name for name, info in found.items() if stat.S_ISREG(info[2])}
    actual_directories = {name for name, info in found.items() if stat.S_ISDIR(info[2])}
    _require(actual_files == files and actual_directories == directories, "package contains missing or extraneous files/directories")
    for ref in artifacts:
        _require(found[_blob_name(ref)][3] == ref["bytes"], "package blob stat size differs")


class _CapturedResolver:
    """One-operation locator capture; never resolves original job path fields."""

    def __init__(self, resolver: Callable, limits: CampaignPackageLimits, allowed=None):
        _require(callable(resolver), "artifact resolver is required")
        self.resolver, self.limits, self.allowed = resolver, limits, allowed
        self.refs: dict[str, dict[str, Any]] = {}
        self.paths: dict[str, Path] = {}
        self.total = 0

    def __call__(self, value):
        ref = _ref(value, self.limits)
        digest = ref["sha256"]
        if self.allowed is not None:
            _require(self.allowed.get(digest) == ref, "resolver request is outside the exact package inventory")
        if digest in self.refs:
            _require(self.refs[digest] == ref, "one digest has inconsistent artifact sizes")
            return self.paths[digest]
        _require(len(self.refs) < self.limits.max_blobs and self.total + ref["bytes"] <= self.limits.max_total_bytes,
            "resolved artifact closure exceeds package bounds")
        # Capture once. Do not open/hash here: the typed adapter owns role-before-
        # selected-read ordering. It verifies payloads through these locators.
        path = _absolute(self.resolver(dict(ref)), resolver=True)
        self.refs[digest], self.paths[digest] = ref, path
        self.total += ref["bytes"]
        return path

    def exact_closure(self, artifacts):
        expected = {row["sha256"]: {key: row[key] for key in ("sha256", "bytes")} for row in artifacts}
        _require(self.refs == expected, "typed resolver reads differ from derived artifact closure")

    def verify_current(self):
        for digest in sorted(self.refs):
            _hash_file(self.paths[digest], self.refs[digest])


def _inspect(inputs, resolver: _CapturedResolver, limits: CampaignPackageLimits):
    from ..optimizers.logic_theorem_optimizer.autoencoder_campaign_package_inputs import inspect_campaign_inputs

    result = inspect_campaign_inputs(inputs["generation_artifact"], inputs["plan_artifact"],
        variant_record=inputs["variant_record"], version_records=inputs["version_records"],
        run_records=inputs["run_records"], artifact_resolver=resolver,
        max_blob_bytes=limits.max_blob_bytes, max_total_bytes=limits.max_total_bytes, max_blobs=limits.max_blobs)
    _require(type(result) is dict and set(result) == {"artifacts", "coverage", "qualification"}, "invalid typed inspection result")
    result = _clone(result, limits.max_control_bytes)
    result["artifacts"] = _artifacts(result["artifacts"], limits)
    _require(type(result["coverage"]) is dict and type(result["qualification"]) is dict, "invalid typed inspection coverage")
    resolver.exact_closure(result["artifacts"])
    return result


def _manifest(inputs, inspection, limits):
    return {"schema_version": SCHEMA_VERSION, "coverage_scope": COVERAGE_SCOPE,
        **inputs, **inspection, "limits": asdict(limits)}


def _decode_manifest(raw: bytes, caller_limits: CampaignPackageLimits):
    manifest = _parse(raw)
    _require(set(manifest) == _MANIFEST_FIELDS and manifest["schema_version"] == SCHEMA_VERSION
        and manifest["coverage_scope"] == COVERAGE_SCOPE, "unsupported or unclosed campaign package manifest")
    declared = manifest["limits"]
    _require(type(declared) is dict and set(declared) == set(asdict(caller_limits)), "invalid package limit fields")
    declared_limits = CampaignPackageLimits(**declared)
    effective = CampaignPackageLimits(**{name: min(value, getattr(caller_limits, name)) for name, value in declared.items()})
    _require(len(raw) <= effective.max_control_bytes and _canonical(manifest, effective.max_control_bytes) == raw,
        "package manifest must be canonical and within limits")
    artifacts = _artifacts(manifest["artifacts"], effective)
    _expected_namespace(artifacts, effective)
    return manifest, effective, declared_limits


def _report(root: Path, raw: bytes, manifest: Mapping[str, Any]) -> dict[str, Any]:
    digest = hashlib.sha256(raw).hexdigest()
    payload = sum(ref["bytes"] for ref in manifest["artifacts"])
    return {"schema_version": REPORT_SCHEMA_VERSION, "package_root": str(root),
        "package_id": "sha256:" + digest,
        "package_manifest_artifact": {"sha256": digest, "bytes": len(raw)},
        "coverage_scope": COVERAGE_SCOPE, "blob_count": len(manifest["artifacts"]),
        "payload_bytes": payload, "package_bytes": payload + len(raw),
        "limits": _clone(manifest["limits"], 4096),
        "coverage": _clone(manifest["coverage"], 4 * 1024**2),
        "qualification": _clone(manifest["qualification"], 4 * 1024**2)}


def _new_root(path: Path) -> int:
    parent_fd = _directory(path.parent)
    try:
        os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)
        fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return fd
    except OSError as exc:
        raise CampaignPackageError("package destination must be fresh and exclusive") from exc
    finally:
        os.close(parent_fd)


def _root_current(path: Path, root_fd: int) -> None:
    current = _directory(path)
    try:
        _require(_identity(os.fstat(current)) == _identity(os.fstat(root_fd)), "destination root pathname changed")
    finally:
        os.close(current)


def _directory_at(root_fd: int, parts: tuple[str, ...]) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=current)
                os.fsync(current)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=current)
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def _copy_blob(source: Path, ref: Mapping[str, Any], root_fd: int) -> None:
    parent_fd = _directory_at(root_fd, ("blobs", ref["sha256"][:2]))
    try:
        source_fd = _regular(source)
        with os.fdopen(source_fd, "rb") as input_stream:
            before = os.fstat(input_stream.fileno())
            _require(before.st_size == ref["bytes"], "source blob differs before copy")
            output_fd = os.open(ref["sha256"], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=parent_fd)
            with os.fdopen(output_fd, "wb") as output:
                digest, size = hashlib.sha256(), 0
                while chunk := input_stream.read(min(_CHUNK, ref["bytes"] - size + 1)):
                    size += len(chunk)
                    _require(size <= ref["bytes"], "source blob grew during copy")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            after = os.fstat(input_stream.fileno())
            _require(_identity(before) == _identity(after) and size == ref["bytes"]
                and digest.hexdigest() == ref["sha256"], "source blob changed during copy")
        _current_file(source, after)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _write_manifest(root_fd: int, raw: bytes) -> None:
    fd = os.open(MANIFEST_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600, dir_fd=root_fd)
    with os.fdopen(fd, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    os.fsync(root_fd)


@_package_errors
def build_campaign_package(generation_artifact, plan_artifact, destination, *,
        variant_record, version_records, run_records, artifact_resolver,
        limits: CampaignPackageLimits = CampaignPackageLimits()) -> dict[str, Any]:
    """Build a fresh selected-page evidence package through the typed walker.

    The destination is created only after all typed inputs and bounds pass.
    A failed/interrupted destination is retained and is never adopted,
    overwritten or recursively removed by a retry. This function performs no registry write.
    """
    limits = _limits(limits)
    inputs = _clone({"generation_artifact": generation_artifact, "plan_artifact": plan_artifact,
        "variant_record": variant_record, "version_records": version_records, "run_records": run_records}, limits.max_control_bytes)
    captured = _CapturedResolver(artifact_resolver, limits)
    inspection = _inspect(inputs, captured, limits)
    manifest = _manifest(inputs, inspection, limits)
    raw = _canonical(manifest, limits.max_control_bytes)
    _expected_namespace(inspection["artifacts"], limits)
    captured.verify_current()
    root = _absolute(destination)
    root_fd = _new_root(root)
    try:
        for ref in inspection["artifacts"]:
            _root_current(root, root_fd)
            _copy_blob(captured.paths[ref["sha256"]], ref, root_fd)
        captured.verify_current()
        _root_current(root, root_fd)
        _write_manifest(root_fd, raw)
        _root_current(root, root_fd)
    finally:
        os.close(root_fd)
    report = verify_campaign_package(root, expected_manifest_sha256=hashlib.sha256(raw).hexdigest(), limits=limits)
    captured.verify_current()
    return report


@_package_errors
def verify_campaign_package(root, *, expected_manifest_sha256: str,
        limits: CampaignPackageLimits = CampaignPackageLimits()) -> dict[str, Any]:
    """Independently reopen original bytes using only exact package blob paths.

    Names/stat are bounded first. Typed job metadata authorizes both roles
    before selected payload reads; generic full-file hashes follow that phase.
    This validates transport and framing, not checkpoint semantic replay.
    """
    limits = _limits(limits)
    _require(type(expected_manifest_sha256) is str and _HASH.fullmatch(expected_manifest_sha256) is not None,
        "an exact expected package manifest SHA-256 is required")
    root = _absolute(root)
    before = _namespace(root, limits)
    raw = _read_control(root / MANIFEST_NAME, limits.max_control_bytes)
    _require(hashlib.sha256(raw).hexdigest() == expected_manifest_sha256, "package manifest digest differs")
    manifest, effective, _ = _decode_manifest(raw, limits)
    _require_namespace(before, manifest["artifacts"], effective)
    allowed = {ref["sha256"]: {key: ref[key] for key in ("sha256", "bytes")} for ref in manifest["artifacts"]}
    captured = _CapturedResolver(lambda ref: root / _blob_name(ref), effective, allowed)
    inputs = {name: manifest[name] for name in _INPUT_FIELDS}
    inspection = _inspect(inputs, captured, effective)
    _require(_same({name: manifest[name] for name in ("artifacts", "coverage", "qualification")},
        inspection, effective.max_control_bytes), "package manifest differs from derived typed closure")
    captured.verify_current()
    _require(_read_control(root / MANIFEST_NAME, effective.max_control_bytes) == raw, "package manifest changed during verification")
    _require(_namespace(root, effective) == before, "package namespace changed during verification")
    return _report(root, raw, manifest)


@_package_errors
def restore_campaign_package(root, destination, *, expected_manifest_sha256: str,
        limits: CampaignPackageLimits = CampaignPackageLimits()) -> dict[str, Any]:
    """Stream a verified package into a fresh directory and independently reopen.

    Original locators and identities are never rewritten. Restored evidence
    grants no execution authority and creates no runs, leases, heads or outbox.
    """
    limits = _limits(limits)
    root = _absolute(root)
    verify_campaign_package(root, expected_manifest_sha256=expected_manifest_sha256, limits=limits)
    before = _namespace(root, limits)
    raw = _read_control(root / MANIFEST_NAME, limits.max_control_bytes)
    _require(hashlib.sha256(raw).hexdigest() == expected_manifest_sha256, "source package changed before restore")
    manifest, effective, _ = _decode_manifest(raw, limits)
    _require_namespace(before, manifest["artifacts"], effective)
    destination = _absolute(destination)
    _require(not destination.is_relative_to(root), "restore destination must be outside the source package")
    destination_fd = _new_root(destination)
    try:
        for ref in manifest["artifacts"]:
            _root_current(destination, destination_fd)
            _copy_blob(root / _blob_name(ref), ref, destination_fd)
        _require(_read_control(root / MANIFEST_NAME, effective.max_control_bytes) == raw,
            "source package manifest changed during restore")
        _require(_namespace(root, effective) == before, "source package namespace changed during restore")
        for ref in manifest["artifacts"]:
            _hash_file(root / _blob_name(ref), ref)
        _root_current(destination, destination_fd)
        _write_manifest(destination_fd, raw)
        _root_current(destination, destination_fd)
    finally:
        os.close(destination_fd)
    result = verify_campaign_package(destination, expected_manifest_sha256=expected_manifest_sha256, limits=limits)
    # Final source guards also cover mutation during restored semantic reopening.
    _require(_read_control(root / MANIFEST_NAME, effective.max_control_bytes) == raw
        and _namespace(root, effective) == before, "source package changed before restore completed")
    for ref in manifest["artifacts"]:
        _hash_file(root / _blob_name(ref), ref)
    return result


__all__ = ["CampaignPackageError", "CampaignPackageLimits", "build_campaign_package",
    "verify_campaign_package", "restore_campaign_package"]
