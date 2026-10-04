"""Bounded authenticated .NET SDK archives; no executable discovery or probes.

The fixed caller supplies a reviewed URL and SHA-512. Inventories are derived
from those authenticated bytes, not from a mutable installed manifest. File
observations do not guarantee immutability against changes after an audit.
"""
from __future__ import annotations

from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tarfile
import tempfile
from urllib.parse import urlparse
from urllib.request import Request

from . import hyperproperty as hp
from .install_control import current_install_limits, installation_checkpoint, installation_scope
from ..smt.operation_budget import ProofOperationInterrupted

MANIFEST_NAME = ".ipfs-dotnet-sdk.json"
INVENTORY_SCHEMA = "dotnet-sdk-archive-inventory@1"
_COPY_BYTES = 65_536
_METADATA_BYTES = 65_536
_TOTAL_METADATA_BYTES = 8 * 1024**2
_HEADER_DEPTH = 16


def _blocked(reason, message):
    return hp.HyperpropertyInstallBlocked(message, "dotnet_sdk_" + reason)


def _digest_value(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{128}", value) is None:
        raise _blocked("invalid_digest", "SDK archive requires an exact lowercase SHA-512")
    return value


def _path(value):
    try:
        return Path(os.path.abspath(os.fspath(value)))
    except (ValueError, TypeError) as error:
        raise _blocked("unsafe_path", "SDK path is invalid") from error


def _safe_parents(path):
    for parent in path.parents:
        installation_checkpoint("SDK archive parent inspection")
        try:
            details = parent.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(details.st_mode):
            raise _blocked("unsafe_path", "SDK paths must have real directory ancestors")


def _fingerprint(details):
    return tuple(getattr(details, name) for name in
                 ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode"))


@contextmanager
def _regular_file(path, maximum):
    _safe_parents(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        stream = os.fdopen(descriptor, "rb")
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_size > maximum:
            raise _blocked("archive_limit", "SDK input must be a bounded regular file")
        yield stream, details


def _hash_stream(stream, maximum, algorithm):
    value = hashlib.new(algorithm)
    total = 0
    while True:
        installation_checkpoint("SDK file hashing")
        chunk = stream.read(min(_COPY_BYTES, maximum - total + 1))
        installation_checkpoint("after SDK file hash read")
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise _blocked("archive_limit", "SDK file hash exceeds its byte limit")
        value.update(chunk)
    return value.hexdigest(), total


def _authenticate(stream, details, expected, maximum):
    actual, total = _hash_stream(stream, maximum, "sha512")
    if _fingerprint(details) != _fingerprint(os.fstat(stream.fileno())) or total != details.st_size:
        raise _blocked("archive_changed", "SDK archive changed during authentication")
    if actual != expected:
        raise _blocked("archive_digest_mismatch", "SDK archive SHA-512 differs from the reviewed pin")
    installation_checkpoint("after SDK archive authentication")
    stream.seek(0)


def download_sdk_archive(url, destination, expected_sha512):
    """Atomically publish a bounded verified transfer, or reuse verified bytes."""
    expected = _digest_value(expected_sha512)
    if not isinstance(url, str) or not hp._archive_url_allowed(url):
        raise _blocked("archive_url", "SDK archive URL is not permitted")
    destination = _path(destination)
    with installation_scope():
        limits = current_install_limits()
        partial = None
        try:
            installation_checkpoint("before SDK archive cache access")
            _safe_parents(destination)
            try:
                details = destination.lstat()
            except FileNotFoundError:
                details = None
            if details is not None:
                if not stat.S_ISREG(details.st_mode):
                    raise _blocked("unsafe_path", "SDK cache destination must be a regular file")
                if details.st_size <= limits.max_download_bytes:
                    with _regular_file(destination, limits.max_download_bytes) as (stream, before):
                        digest, total = _hash_stream(stream, limits.max_download_bytes, "sha512")
                        if _fingerprint(before) != _fingerprint(os.fstat(stream.fileno())) or total != before.st_size:
                            raise _blocked("archive_changed", "SDK cache changed while hashing")
                        if digest == expected:
                            installation_checkpoint("before verified SDK cache reuse")
                            return destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix="." + destination.name + "-", suffix=".partial", dir=destination.parent)
            partial = Path(temporary)
            with os.fdopen(descriptor, "wb") as output:
                remaining = installation_checkpoint("before SDK archive connection")
                request = Request(url, headers={"User-Agent": "ipfs-datasets-dotnet-sdk/1"})
                with hp.urlopen(request, timeout=min(limits.io_timeout_seconds, remaining)) as response:
                    final_url = getattr(response, "geturl", lambda: url)()
                    if not hp._archive_url_allowed(final_url) or (urlparse(url).scheme == "https" and urlparse(final_url).scheme != "https"):
                        raise _blocked("archive_url", "SDK archive redirect is not permitted")
                    declared = response.headers.get("Content-Length") if hasattr(response, "headers") else None
                    declared = None if declared is None else int(declared)
                    if declared is not None and (declared < 0 or declared > limits.max_download_bytes):
                        raise _blocked("archive_limit", "SDK archive exceeds its compressed byte limit")
                    digest, count = hashlib.sha512(), 0
                    while True:
                        installation_checkpoint("SDK archive download")
                        chunk = response.read(min(_COPY_BYTES, limits.max_download_bytes - count + 1))
                        installation_checkpoint("after SDK archive download read")
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > limits.max_download_bytes:
                            raise _blocked("archive_limit", "SDK archive exceeds its compressed byte limit")
                        digest.update(chunk); output.write(chunk)
                    if declared is not None and count != declared:
                        raise _blocked("archive_transfer", "SDK archive transfer is incomplete")
                    if digest.hexdigest() != expected:
                        raise _blocked("archive_digest_mismatch", "SDK archive SHA-512 differs from the reviewed pin")
                output.flush(); os.fsync(output.fileno())
            _safe_parents(destination)
            if destination.is_symlink() or destination.exists() and not destination.is_file():
                raise _blocked("unsafe_path", "SDK cache destination changed before publication")
            installation_checkpoint("before SDK archive publication")
            partial.replace(destination)
            return destination
        except (hp.HyperpropertyInstallerError, ProofOperationInterrupted):
            raise
        except Exception as error:
            raise _blocked("archive_transfer", "SDK archive transfer failed") from error
        finally:
            if partial is not None:
                partial.unlink(missing_ok=True)


def _name(value, limits, *, directory=False):
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except (AttributeError, UnicodeError) as error:
        raise _blocked("archive_path", "SDK archive path encoding is invalid") from error
    if (not value or size > limits.max_path_bytes or "\\" in value or value.startswith("/")
            or re.match(r"^[A-Za-z]:", value) or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise _blocked("archive_path", "SDK archive path is invalid or too long")
    if value.startswith("./"):
        value = value[2:]
    if directory:
        value = value[:-1] if value.endswith("/") else value
        if value in ("", "."):
            return ""
    parts = value.split("/")
    if len(parts) > limits.max_archive_depth or any(part in ("", ".", "..") for part in parts):
        raise _blocked("archive_path", "SDK archive path escapes or exceeds its depth limit")
    if value == MANIFEST_NAME:
        raise _blocked("archive_path", "SDK archive uses a reserved installer path")
    return value


def _tree_digest(entries):
    encoded = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _inventory(expected_sha512, compressed_bytes, entries):
    return {"schema": INVENTORY_SCHEMA, "archive_sha512": expected_sha512,
            "compressed_bytes": compressed_bytes, "files": sum(row["kind"] == "file" for row in entries.values()),
            "directories": sum(row["kind"] == "dir" for row in entries.values()),
            "bytes": sum(row.get("size", 0) for row in entries.values()),
            "entries": dict(sorted(entries.items())), "tree_sha256": _tree_digest(entries)}


def _remove_owned_tree(destination, directories):
    # Applying archive mode000/0555 must not prevent rollback of our own tree.
    for path in sorted(directories, key=lambda value: len(value.parts)):
        try:
            details = path.lstat()
            if stat.S_ISDIR(details.st_mode):
                path.chmod(stat.S_IMODE(details.st_mode) | stat.S_IRWXU)
        except FileNotFoundError:
            pass
    shutil.rmtree(destination)


def extract_sdk_archive(archive, destination, expected_sha512):
    """Authenticate then extract a gzip SDK distribution into a fresh directory.

    Unlike commit source archives, multiple top-level entries are valid. Only
    regular files and directories are supported; the returned inventory binds
    exact names, permission bits and file bytes. No extracted code is executed.
    """
    expected = _digest_value(expected_sha512)
    archive, destination = _path(archive), _path(destination)
    with installation_scope():
        limits = current_install_limits()
        entries, explicit, directories = {}, set(), {}
        created = False
        try:
            installation_checkpoint("before SDK extraction")
            _safe_parents(destination)
            if destination.exists() or destination.is_symlink():
                raise _blocked("unsafe_path", "SDK extraction requires a fresh owned directory")
            with _regular_file(archive, limits.max_download_bytes) as (source, details):
                _authenticate(source, details, expected, limits.max_download_bytes)
                destination.mkdir(parents=True, mode=0o700, exist_ok=False); created = True
                directories[destination] = 0o700
                count = metadata = header_depth = path_bytes = expanded = 0

                class LimitedTarInfo(tarfile.TarInfo):
                    @classmethod
                    def frombuf(cls, buffer, encoding, errors):
                        # TarFile.next treats malformed later headers like EOF.
                        # Only an actual all-zero terminator may end this SDK.
                        try:
                            return super().frombuf(buffer, encoding, errors)
                        except tarfile.EOFHeaderError:
                            raise
                        except tarfile.HeaderError as error:
                            raise _blocked("archive_header", "SDK archive header is malformed or truncated") from error

                    def _proc_member(self, handle):
                        nonlocal count, metadata, header_depth
                        installation_checkpoint("SDK archive header")
                        count += 1; header_depth += 1
                        try:
                            if count > limits.max_archive_members or header_depth > _HEADER_DEPTH or self.size < 0:
                                raise _blocked("archive_limit", "SDK archive header limit exceeded")
                            extended = self.type in (tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK,
                                tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE)
                            if extended:
                                metadata += self.size
                                if self.size > _METADATA_BYTES or metadata > _TOTAL_METADATA_BYTES:
                                    raise _blocked("archive_limit", "SDK archive metadata limit exceeded")
                            elif self.size > limits.max_member_bytes:
                                raise _blocked("archive_limit", "SDK archive member is too large")
                            result = super()._proc_member(handle)
                            if result is None or result.size < 0 or result.size > limits.max_member_bytes:
                                raise _blocked("archive_limit", "SDK archive member is invalid or too large")
                            return result
                        finally:
                            header_depth -= 1

                    def _proc_sparse(self, *_):
                        raise _blocked("archive_object", "SDK sparse files are unsupported")
                    _proc_gnusparse_00 = _proc_sparse
                    _proc_gnusparse_01 = _proc_sparse
                    _proc_gnusparse_10 = _proc_sparse

                class LimitedReader:
                    def __init__(self, stream, maximum):
                        self.stream, self.maximum, self.count = stream, maximum, 0
                    def read(self, size=-1):
                        installation_checkpoint("SDK archive decompression")
                        size = _COPY_BYTES if size < 0 else min(size, _COPY_BYTES)
                        chunk = self.stream.read(min(size, self.maximum - self.count + 1))
                        installation_checkpoint("after SDK archive decompression read")
                        self.count += len(chunk)
                        if self.count > self.maximum:
                            raise _blocked("archive_limit", "SDK archive stream limit exceeded")
                        return chunk

                def ensure_parents(relative):
                    parts = relative.split("/")
                    for index in range(1, len(parts)):
                        installation_checkpoint("SDK archive parent creation")
                        parent = "/".join(parts[:index]); target = destination / parent
                        if parent in entries:
                            if entries[parent]["kind"] != "dir":
                                raise _blocked("archive_path", "SDK archive writes through a file")
                        else:
                            if len(entries) >= limits.max_archive_members:
                                raise _blocked("archive_limit", "SDK extracted entry limit exceeded")
                            target.mkdir(mode=0o700)
                            entries[parent] = {"kind": "dir", "mode": 0o755}
                            directories[target] = 0o755

                with gzip.GzipFile(fileobj=LimitedReader(source, limits.max_download_bytes), mode="rb") as decompressed:
                    reader = LimitedReader(decompressed, limits.max_extract_bytes + _TOTAL_METADATA_BYTES + limits.max_archive_members * 1024 + _COPY_BYTES)
                    with tarfile.open(fileobj=reader, mode="r|", tarinfo=LimitedTarInfo) as bundle:
                        for member in bundle:
                            installation_checkpoint("SDK archive member")
                            bundle.members.clear()
                            if not (member.isreg() or member.isdir()) or member.issparse():
                                raise _blocked("archive_object", "SDK archive contains an unsupported object")
                            relative = _name(member.name, limits, directory=member.isdir())
                            path_bytes += len(relative.encode("utf-8"))
                            if path_bytes > limits.max_archive_members * limits.max_path_bytes:
                                raise _blocked("archive_limit", "SDK aggregate path bytes exceeded")
                            if relative in explicit:
                                raise _blocked("archive_path", "SDK archive contains duplicate paths")
                            explicit.add(relative)
                            if not relative:
                                if member.size:
                                    raise _blocked("archive_object", "SDK root directory carries data")
                                continue
                            ensure_parents(relative)
                            if relative not in entries and len(entries) >= limits.max_archive_members:
                                raise _blocked("archive_limit", "SDK extracted entry limit exceeded")
                            target, mode = destination / relative, member.mode & 0o777
                            if member.isdir():
                                if member.size or relative in entries and entries[relative]["kind"] != "dir":
                                    raise _blocked("archive_path", "SDK archive directory conflicts with a file")
                                target.mkdir(mode=0o700, exist_ok=True)
                                entries[relative] = {"kind": "dir", "mode": mode}; directories[target] = mode
                            else:
                                if relative in entries:
                                    raise _blocked("archive_path", "SDK archive file conflicts with a directory")
                                expanded += member.size
                                if expanded > limits.max_extract_bytes:
                                    raise _blocked("archive_limit", "SDK expanded bytes exceeded")
                                stream = bundle.extractfile(member)
                                if stream is None:
                                    raise _blocked("archive_object", "SDK archive file has no data")
                                digest, remaining = hashlib.sha256(), member.size
                                with stream, target.open("xb") as output:
                                    while remaining:
                                        installation_checkpoint("SDK archive member copy")
                                        chunk = stream.read(min(_COPY_BYTES, remaining))
                                        installation_checkpoint("after SDK member read")
                                        if not chunk:
                                            raise _blocked("archive_truncated", "SDK archive member is truncated")
                                        output.write(chunk); digest.update(chunk); remaining -= len(chunk)
                                target.chmod(mode)
                                entries[relative] = {"kind": "file", "mode": mode, "size": member.size, "sha256": digest.hexdigest()}
                        if bundle.fileobj.tell() < bundle.offset + 512:
                            raise _blocked("archive_truncated", "SDK archive lacks its tar terminator")
                        trailing = 0
                        while True:
                            block = bundle.fileobj.read(_COPY_BYTES)
                            installation_checkpoint("SDK archive trailer")
                            if not block:
                                break
                            trailing += len(block)
                            if any(block):
                                raise _blocked("archive_trailing_data", "SDK archive has nonzero trailing payload")
                        if trailing < 512:
                            raise _blocked("archive_truncated", "SDK archive lacks its complete tar terminator")
                if _fingerprint(details) != _fingerprint(os.fstat(source.fileno())):
                    raise _blocked("archive_changed", "SDK archive changed during extraction")
                if not any(row["kind"] == "file" for row in entries.values()):
                    raise _blocked("archive_object", "SDK archive contains no files")
                for directory, mode in sorted(directories.items(), key=lambda item: len(item[0].parts), reverse=True):
                    installation_checkpoint("SDK archive directory permissions")
                    directory.chmod(mode)
                installation_checkpoint("before SDK inventory construction")
                result = _inventory(expected, details.st_size, entries)
                installation_checkpoint("before SDK extracted inventory publication")
                return result
        except BaseException as error:
            if created:
                _remove_owned_tree(destination, directories)
            if isinstance(error, (hp.HyperpropertyInstallerError, ProofOperationInterrupted)) or not isinstance(error, Exception):
                raise
            raise _blocked("archive_extraction", "SDK archive extraction failed") from error


def audit_sdk_tree(root, expected_inventory):
    """Compare a tree to a freshly authenticated archive-derived inventory.

    Only the exact root installer manifest is excluded, and only when it is a
    bounded regular file. The caller must never source ``expected_inventory``
    from that mutable manifest. This helper never executes installed files.
    """
    root = _path(root)
    with installation_scope():
        limits = current_install_limits()
        try:
            expected = expected_inventory["entries"]
            if (expected_inventory["schema"] != INVENTORY_SCHEMA or not isinstance(expected, dict)
                    or not 0 < len(expected) <= limits.max_archive_members):
                raise _blocked("inventory_invalid", "SDK inventory is invalid")
            for name, row in expected.items():
                installation_checkpoint("SDK expected inventory validation")
                if not isinstance(row, dict) or row.get("kind") not in ("file", "dir") or _name(name, limits) != name:
                    raise _blocked("inventory_invalid", "SDK inventory entry is invalid")
                keys = {"kind", "mode", "size", "sha256"} if row["kind"] == "file" else {"kind", "mode"}
                if set(row) != keys or type(row["mode"]) is not int or not 0 <= row["mode"] <= 0o777:
                    raise _blocked("inventory_invalid", "SDK inventory entry metadata is invalid")
                if row["kind"] == "file" and (type(row["size"]) is not int or not 0 <= row["size"] <= limits.max_member_bytes
                        or not isinstance(row["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None):
                    raise _blocked("inventory_invalid", "SDK inventory file metadata is invalid")
            if _tree_digest(expected) != expected_inventory["tree_sha256"]:
                raise _blocked("inventory_invalid", "SDK inventory tree digest is inconsistent")
            _safe_parents(root)
            root_details = root.lstat()
            if not stat.S_ISDIR(root_details.st_mode):
                raise _blocked("tree_mismatch", "SDK installation root must be a real directory")
            actual, total, stack = {}, 0, [(root, 0)]
            observed = {root: _fingerprint(root_details)}
            while stack:
                directory, depth = stack.pop()
                installation_checkpoint("SDK installed directory audit")
                _safe_parents(directory)
                if not stat.S_ISDIR(directory.lstat().st_mode):
                    raise _blocked("tree_mismatch", "SDK installed directory changed during audit")
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        installation_checkpoint("SDK installed entry audit")
                        relative = Path(entry.path).relative_to(root).as_posix()
                        details = entry.stat(follow_symlinks=False)
                        observed[Path(entry.path)] = _fingerprint(details)
                        if relative == MANIFEST_NAME:
                            if not stat.S_ISREG(details.st_mode) or details.st_size > _METADATA_BYTES:
                                raise _blocked("tree_mismatch", "SDK installer manifest must be a bounded regular file")
                            continue
                        if len(actual) >= limits.max_archive_members or depth + 1 > limits.max_archive_depth:
                            raise _blocked("archive_limit", "SDK installed layout exceeds its limit")
                        if relative not in expected or _name(relative, limits) != relative:
                            raise _blocked("tree_mismatch", "SDK installation has unexpected entries")
                        mode = stat.S_IMODE(details.st_mode)
                        if stat.S_ISDIR(details.st_mode):
                            actual[relative] = {"kind": "dir", "mode": mode}
                            stack.append((Path(entry.path), depth + 1))
                        elif stat.S_ISREG(details.st_mode):
                            total += details.st_size
                            if total > limits.max_extract_bytes:
                                raise _blocked("archive_limit", "SDK installed bytes exceed their limit")
                            with _regular_file(Path(entry.path), limits.max_member_bytes) as (stream, before):
                                digest, count = _hash_stream(stream, limits.max_member_bytes, "sha256")
                                if _fingerprint(before) != _fingerprint(os.fstat(stream.fileno())) or count != before.st_size:
                                    raise _blocked("tree_mismatch", "SDK installed file changed during audit")
                            if _fingerprint(details) != _fingerprint(Path(entry.path).lstat()):
                                raise _blocked("tree_mismatch", "SDK installed file was replaced during audit")
                            actual[relative] = {"kind": "file", "mode": mode, "size": count, "sha256": digest}
                        else:
                            raise _blocked("tree_mismatch", "SDK installation contains an unsupported object")
                        if actual[relative] != expected[relative]:
                            raise _blocked("tree_mismatch", "SDK installed entry differs from the authenticated archive")
            if actual != expected:
                raise _blocked("tree_mismatch", "SDK installation is missing authenticated archive entries")
            for path, fingerprint in observed.items():
                installation_checkpoint("SDK final installed entry observation")
                if _fingerprint(path.lstat()) != fingerprint:
                    raise _blocked("tree_mismatch", "SDK installation changed during audit")
            result = {"verified": True, "tree_sha256": _tree_digest(actual),
                      "files": sum(row["kind"] == "file" for row in actual.values()),
                      "directories": sum(row["kind"] == "dir" for row in actual.values()), "bytes": total}
            installation_checkpoint("before SDK tree audit publication")
            return result
        except (hp.HyperpropertyInstallerError, ProofOperationInterrupted):
            raise
        except Exception as error:
            raise _blocked("tree_mismatch", "SDK installed tree could not be verified") from error


__all__ = ["download_sdk_archive", "extract_sdk_archive", "audit_sdk_tree"]
