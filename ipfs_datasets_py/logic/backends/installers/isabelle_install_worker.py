"""Private archive staging worker for the admitted Isabelle installer.

The controller owns pin authorization, scheduler admission, process limits,
the installation lock, readiness checks, publication and cleanup.  This
worker only downloads verified bytes and extracts them into an existing
private directory.  Its result is extraction metadata, never readiness or
proof evidence.  Run it under ``BoundedToolRunner``; calling ``stage_archive``
directly supplies cooperative I/O deadlines, not a CPU/RSS sandbox.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any
from urllib.parse import urlsplit

from . import isabelle as installer


REQUEST_SCHEMA = "isabelle-archive-staging-request@2"
RESULT_SCHEMA = "isabelle-archive-staging-result@2"
MAX_MESSAGE_BYTES = 32 * 1024
_FIELDS = frozenset(("schema", "version", "platform_key", "artifact_url", "sha256",
                     "cache_path", "staging_dir", "timeout_seconds", "allow_download"))
_PLATFORMS = frozenset(("linux-x86_64", "linux-aarch64", "darwin-x86_64", "darwin-arm64"))


class ArchiveStagingError(ValueError):
    """The staging request or extracted archive failed its closed contract."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _absolute_path(value: Any, name: str) -> Path:
    if type(value) is not str or not value or len(value.encode("utf-8")) > 4096 or "\x00" in value:
        raise ArchiveStagingError(f"{name} must be a bounded absolute path")
    path = Path(value)
    if not path.is_absolute() or str(path) != value or ".." in path.parts or path == path.parent:
        raise ArchiveStagingError(f"{name} must be a normalized absolute path")
    # Paths are controller-owned. Refuse existing symlink ancestors instead of
    # allowing a cache or staging directory to redirect writes elsewhere.
    for current in (path, *path.parents):
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ArchiveStagingError(f"{name} must not contain a symlink")
    return path


def _request(request: dict[str, Any]) -> tuple[dict[str, Any], Path, Path]:
    if type(request) is not dict or set(request) != _FIELDS:
        raise ArchiveStagingError("invalid staging request fields")
    # Freeze the validated scalar-only request before filesystem work.
    request = dict(request)
    if request["schema"] != REQUEST_SCHEMA or type(request["schema"]) is not str:
        raise ArchiveStagingError("invalid staging request schema")
    if type(request["allow_download"]) is not bool:
        raise ArchiveStagingError("allow_download must be an exact boolean")
    if type(request["version"]) is not str or request["version"] != installer.ISABELLE_VERSION:
        raise ArchiveStagingError("unsupported staging version")
    if type(request["platform_key"]) is not str or request["platform_key"] not in _PLATFORMS:
        raise ArchiveStagingError("unsupported staging platform")
    checksum = request["sha256"]
    if type(checksum) is not str or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
        raise ArchiveStagingError("sha256 must be canonical lowercase hexadecimal")
    timeout = request["timeout_seconds"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ArchiveStagingError("timeout_seconds must be finite and within (0, 3600]")
    url = request["artifact_url"]
    if type(url) is not str or not url or len(url.encode("utf-8")) > 8192 or any(ord(c) < 32 for c in url):
        raise ArchiveStagingError("artifact_url must be a bounded URL")
    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https", "file") or parsed.fragment or parsed.username or parsed.password
            or (parsed.scheme in ("http", "https") and not parsed.hostname)
            or (parsed.scheme == "file" and (parsed.netloc not in ("", "localhost") or not parsed.path.startswith("/")))):
        raise ArchiveStagingError("unsupported artifact URL")
    if len(_canonical(request)) > MAX_MESSAGE_BYTES:
        raise ArchiveStagingError("staging request exceeds message cap")
    cache = _absolute_path(request["cache_path"], "cache_path")
    staging = _absolute_path(request["staging_dir"], "staging_dir")
    if cache == staging or staging in cache.parents or cache in staging.parents:
        raise ArchiveStagingError("cache and staging paths must be separate")
    info = staging.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise ArchiveStagingError("staging_dir must be an existing private owner-owned directory")
    with os.scandir(staging) as entries:
        if next(entries, None) is not None:
            raise ArchiveStagingError("staging_dir must be empty")
    return request, cache, staging


def stage_archive(request: dict[str, Any]) -> dict[str, Any]:
    """Stage one controller-selected pin without probing or publishing it.

    Failed staging trees remain owned by the controller. All archive bounds
    are the reviewed installer defaults; requests cannot relax them.
    """
    request, cache, staging = _request(request)
    deadline = installer._operation_deadline(request["timeout_seconds"], None)
    if request["allow_download"]:
        partials = staging / ".download-partials"
        partials.mkdir(mode=0o700)
        if not installer.download_artifact(request["artifact_url"], cache, sha256=request["sha256"],
                                           timeout=request["timeout_seconds"], _deadline=deadline,
                                           _temporary_directory=partials):
            installer._check_running(deadline, None)
            raise ArchiveStagingError("archive download or checksum validation failed")
        # Extraction requires an empty staging directory. A killed download
        # leaves partial files here, never beside the shared external cache.
        partials.rmdir()
    installer._check_running(deadline, None)
    # Re-read through the same cumulative cap: the response binds observed
    # verified bytes, including cache hits, not a caller's declared checksum.
    with installer._open_regular(cache, installer.MAX_DOWNLOAD_BYTES) as handle:
        checksum = installer._bounded_digest(handle, installer.MAX_DOWNLOAD_BYTES, deadline, None)
        size = handle.tell()
    if checksum != request["sha256"]:
        raise ArchiveStagingError("cached archive checksum mismatch or changed after download")
    installer._safe_extract_tar(cache, staging, timeout=request["timeout_seconds"], _deadline=deadline)
    installer._check_running(deadline, None)
    candidate = staging / request["version"]
    info = candidate.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ArchiveStagingError("archive must contain the exact direct version directory")
    with os.scandir(staging) as entries:
        for entry in entries:
            if entry.name != request["version"]:
                raise ArchiveStagingError("archive contains entries outside its version directory")
    installer._check_running(deadline, None)
    return {"schema": RESULT_SCHEMA, "request_sha256": hashlib.sha256(_canonical(request)).hexdigest(),
            "version": request["version"], "platform_key": request["platform_key"], "sha256": checksum,
            "archive_size_bytes": size, "candidate_relative_path": request["version"]}


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ArchiveStagingError("duplicate JSON field")
        result[key] = value
    return result


def _read_request(path: Path) -> dict[str, Any]:
    with installer._open_regular(path, MAX_MESSAGE_BYTES) as handle:
        data = handle.read(MAX_MESSAGE_BYTES + 1)
    if len(data) > MAX_MESSAGE_BYTES:
        raise ArchiveStagingError("staging request exceeds message cap")
    return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ArchiveStagingError("nonfinite JSON number")))


def _write_result(path: Path, result: dict[str, Any]) -> None:
    data = _canonical(result)
    if len(data) > MAX_MESSAGE_BYTES:
        raise ArchiveStagingError("staging result exceeds message cap")
    descriptor, name = tempfile.mkstemp(prefix=".isabelle-staging-result-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: isabelle_install_worker REQUEST.json RESULT.json", file=sys.stderr)
        return 2
    try:
        request_path, result_path = map(Path, args)
        if request_path.absolute() == result_path.absolute():
            raise ArchiveStagingError("request and result paths must differ")
        result = stage_archive(_read_request(request_path))
        _write_result(result_path, result)
    except Exception as exc:
        print(f"Isabelle archive staging failed: {type(exc).__name__}: {str(exc)[:1024]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
