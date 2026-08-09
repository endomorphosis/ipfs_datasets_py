#!/usr/bin/env python3
"""Run the DuckDB supervisor bridge tests in a separate sealed toolchain.

The supervisor runtime deliberately contains only DuckDB.  This module keeps
pytest and its pure-Python dependencies in verified wheel archives outside that
runtime, starts the admitted base CPython with ``-I -B -S``, and gives the test
process an exact ``sys.path``.  Repository and artifact identities are checked
both before and after pytest so a successful receipt cannot cover a moving
checkout.

The file intentionally depends on the Python standard library only.  It is
loaded again inside the sealed child rather than imported from an ambient
environment.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import platform
import re
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ipfs_datasets_py/duckdb-quack-validation-receipt@1"
CACHE_SCHEMA = "ipfs_datasets_py/duckdb-quack-validator-wheel-cache@1"
SUPPORTED_PYTHON = (3, 12)
SUPPORTED_SYSTEM = "Linux"
SUPPORTED_MACHINES = frozenset({"aarch64", "x86_64"})
MAX_WHEEL_MEMBERS = 20_000
MAX_WHEEL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
DEFAULT_STDOUT_LIMIT = 1 * 1024 * 1024
DEFAULT_STDERR_LIMIT = 1 * 1024 * 1024
DEFAULT_COMBINED_LIMIT = 1536 * 1024
DEFAULT_TIMEOUT_SECONDS = 900.0

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
DEFAULT_LOCK = REPO_ROOT / "requirements/duckdb-quack-validator.lock"
DEFAULT_ACCELERATE_ROOT = REPO_ROOT / "ipfs_accelerate_py"
DEFAULT_RUNTIME_ROOT = Path(
    os.environ.get(
        "IPFS_DATASETS_DQK_ENV_ROOT",
        str(REPO_ROOT.parents[1] / ".venvs/ipfs-datasets-duckdb-quack"),
    )
).absolute()
DEFAULT_VALIDATOR_ROOT = Path(
    os.environ.get(
        "IPFS_DATASETS_DQK_VALIDATOR_ROOT",
        str(DEFAULT_RUNTIME_ROOT.parent / "ipfs-datasets-duckdb-quack-validator"),
    )
).absolute()
DEFAULT_BASE_PYTHON = Path(
    os.environ.get("IPFS_DATASETS_DQK_BASE_PYTHON", "/usr/bin/python3.12")
).absolute()
GIT_EXECUTABLE = Path("/usr/bin/git")

EXPECTED_VERSIONS = {
    "duckdb": "1.5.5",
    "iniconfig": "2.3.0",
    "packaging": "26.2",
    "pluggy": "1.6.0",
    "pygments": "2.19.2",
    "pytest": "9.0.3",
}
VALIDATOR_PACKAGES = ("iniconfig", "packaging", "pluggy", "pygments", "pytest")
VALIDATOR_IMPORT_ORDER = ("iniconfig", "packaging", "pluggy", "pygments", "pytest")
DEFAULT_TESTS = (
    "test/api/test_agent_supervisor_implementation_daemon_runner.py",
    "test/api/test_agent_supervisor_task_source_e2e.py",
    "test/api/test_agent_supervisor_duckdb_task_source.py",
    "test/api/test_agent_supervisor_duckdb_completion_evidence.py",
    "test/api/test_agent_supervisor_duckdb_retry_reset.py",
    "test/api/test_agent_supervisor_duckdb_merge_evidence_e2e.py",
)


@dataclass(frozen=True)
class ArtifactSource:
    package: str
    filename: str
    sha256: str
    url: str


PURE_SOURCES = {
    "pytest": ArtifactSource(
        "pytest",
        "pytest-9.0.3-py3-none-any.whl",
        "2c5efc453d45394fdd706ade797c0a81091eccd1d6e4bccfcd476e2b8e0ab5d9",
        "https://files.pythonhosted.org/packages/d4/24/"
        "a372aaf5c9b7208e7112038812994107bc65a84cd00e0354a88c2c77a617/"
        "pytest-9.0.3-py3-none-any.whl",
    ),
    "iniconfig": ArtifactSource(
        "iniconfig",
        "iniconfig-2.3.0-py3-none-any.whl",
        "f631c04d2c48c52b84d0d0549c99ff3859c98df65b3101406327ecc7d53fbf12",
        "https://files.pythonhosted.org/packages/cb/b1/"
        "3846dd7f199d53cb17f49cba7e651e9ce294d8497c8c150530ed11865bb8/"
        "iniconfig-2.3.0-py3-none-any.whl",
    ),
    "packaging": ArtifactSource(
        "packaging",
        "packaging-26.2-py3-none-any.whl",
        "5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e",
        "https://files.pythonhosted.org/packages/df/b2/"
        "87e62e8c3e2f4b32e5fe99e0b86d576da1312593b39f47d8ceef365e95ed/"
        "packaging-26.2-py3-none-any.whl",
    ),
    "pluggy": ArtifactSource(
        "pluggy",
        "pluggy-1.6.0-py3-none-any.whl",
        "e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746",
        "https://files.pythonhosted.org/packages/54/20/"
        "4d324d65cc6d9205fabedc306948156824eb9f0ee1633355a8f7ec5c66bf/"
        "pluggy-1.6.0-py3-none-any.whl",
    ),
    "pygments": ArtifactSource(
        "pygments",
        "pygments-2.19.2-py3-none-any.whl",
        "86540386c03d588bb81d44bc3928634ff26449851e99741617ecb9037ee5ec0b",
        "https://files.pythonhosted.org/packages/c7/21/"
        "705964c7812476f378728bdf590ca4b771ec72385c533964653c68e86bdc/"
        "pygments-2.19.2-py3-none-any.whl",
    ),
}
DUCKDB_SOURCES = {
    "aarch64": ArtifactSource(
        "duckdb",
        "duckdb-1.5.5-cp312-cp312-manylinux_2_26_aarch64."
        "manylinux_2_28_aarch64.whl",
        "f316eae2323d9a851883fdf2dee91c1f9efe251ab33e14a2272f82a913422ed6",
        "https://files.pythonhosted.org/packages/ea/a9/"
        "5f1f09da421d8e930e0b063d11c1b3f90363f40ede74438cd188afdd13a2/"
        "duckdb-1.5.5-cp312-cp312-manylinux_2_26_aarch64."
        "manylinux_2_28_aarch64.whl",
    ),
    "x86_64": ArtifactSource(
        "duckdb",
        "duckdb-1.5.5-cp312-cp312-manylinux_2_26_x86_64."
        "manylinux_2_28_x86_64.whl",
        "7a6d2d11859d82a936ebdcb30ce3d8a1cbb3e990bff05c12abb9b54c44fa7bd1",
        "https://files.pythonhosted.org/packages/4f/98/"
        "6549769f158126fa64fd6c1ac2eb59a18282146c939867a3eb31b7c1db07/"
        "duckdb-1.5.5-cp312-cp312-manylinux_2_26_x86_64."
        "manylinux_2_28_x86_64.whl",
    ),
}


@dataclass(frozen=True)
class LockedPackage:
    name: str
    version: str
    hashes: frozenset[str]


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _strict_relative(value: str, *, noun: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise RuntimeError(f"{noun} is not a portable relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"{noun} is not a portable relative path")
    return path


def _regular_file(path: Path, *, noun: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"{noun} is unavailable: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError(f"{noun} must be a regular non-symlink file: {path}")
    return metadata


def parse_lock(path: Path) -> dict[str, LockedPackage]:
    """Parse the deliberately small require-hashes lock grammar."""

    _regular_file(path, noun="validator lock")
    try:
        physical = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except OSError as exc:
        raise RuntimeError("validator lock is unreadable") from exc
    logical: list[str] = []
    pending = ""
    for raw in physical:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1].rstrip() + " "
            continue
        logical.append(pending + stripped)
        pending = ""
    if pending:
        raise RuntimeError("validator lock has an unterminated continuation")

    result: dict[str, LockedPackage] = {}
    for line in logical:
        tokens = shlex.split(line, comments=False, posix=True)
        if not tokens:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", tokens[0])
        if match is None:
            raise RuntimeError("validator lock contains a non-exact requirement")
        name = _normalized_name(match.group(1))
        version = match.group(2)
        hashes: set[str] = set()
        for token in tokens[1:]:
            hash_match = re.fullmatch(r"--hash=sha256:([0-9a-f]{64})", token)
            if hash_match is None:
                raise RuntimeError("validator lock contains an unsupported option")
            hashes.add("sha256:" + hash_match.group(1))
        if not hashes or name in result:
            raise RuntimeError("validator lock has missing or duplicate hashes")
        result[name] = LockedPackage(name, version, frozenset(hashes))
    if set(result) != set(EXPECTED_VERSIONS):
        raise RuntimeError("validator lock package set is not exact")
    for name, version in EXPECTED_VERSIONS.items():
        if result[name].version != version:
            raise RuntimeError(f"validator lock version mismatch for {name}")
    if any(len(result[name].hashes) != 1 for name in VALIDATOR_PACKAGES):
        raise RuntimeError("each pure validator package must pin exactly one wheel")
    if len(result["duckdb"].hashes) != len(SUPPORTED_MACHINES):
        raise RuntimeError("DuckDB must pin one CPython wheel per supported machine")
    return result


def _record_hash(raw: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()


def verify_wheel(
    path: Path,
    *,
    package: str,
    version: str,
    allowed_hashes: Iterable[str],
    required_tags: Iterable[str],
) -> dict[str, Any]:
    """Verify a wheel archive, including every RECORD member binding."""

    metadata = _regular_file(path, noun=f"{package} wheel")
    if metadata.st_size <= 0:
        raise RuntimeError(f"{package} wheel is empty")
    archive_sha256 = _sha256_file(path)
    allowed = frozenset(str(item) for item in allowed_hashes)
    if archive_sha256 not in allowed:
        raise RuntimeError(f"{package} wheel hash is not admitted by the lock")

    normalized = package.replace("-", "_")
    dist_info = f"{normalized}-{version}.dist-info"
    record_name = f"{dist_info}/RECORD"
    wheel_name = f"{dist_info}/WHEEL"
    metadata_name = f"{dist_info}/METADATA"
    member_rows: list[dict[str, Any]] = []
    member_bytes: dict[str, bytes] = {}
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"{package} wheel is not a valid zip archive") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_WHEEL_MEMBERS:
            raise RuntimeError(f"{package} wheel member count is unsafe")
        if archive.testzip() is not None:
            raise RuntimeError(f"{package} wheel has a corrupt member")
        total = 0
        seen: set[str] = set()
        for info in infos:
            relative = _strict_relative(info.filename.rstrip("/"), noun="wheel member")
            name = relative.as_posix()
            if name in seen:
                raise RuntimeError(f"{package} wheel has a duplicate member")
            seen.add(name)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode) or info.flag_bits & 0x1:
                raise RuntimeError(f"{package} wheel has a link or encrypted member")
            if info.is_dir():
                continue
            total += info.file_size
            if total > MAX_WHEEL_UNCOMPRESSED_BYTES:
                raise RuntimeError(f"{package} wheel expands beyond its bound")
            raw = archive.read(info)
            if len(raw) != info.file_size:
                raise RuntimeError(f"{package} wheel member read was incomplete")
            member_bytes[name] = raw
            member_rows.append(
                {"path": name, "sha256": _sha256_bytes(raw), "size": len(raw)}
            )
        for required in (record_name, wheel_name, metadata_name):
            if required not in member_bytes:
                raise RuntimeError(f"{package} wheel omits {required}")

    message = BytesParser().parsebytes(member_bytes[metadata_name])
    if (
        _normalized_name(str(message.get("Name") or "")) != package
        or str(message.get("Version") or "") != version
    ):
        raise RuntimeError(f"{package} wheel METADATA identity mismatch")
    wheel_text = member_bytes[wheel_name].decode("utf-8", errors="strict")
    tags = sorted(
        line.partition(":")[2].strip()
        for line in wheel_text.splitlines()
        if line.startswith("Tag:")
    )
    required_tag_set = frozenset(required_tags)
    if not tags or not required_tag_set.intersection(tags):
        raise RuntimeError(f"{package} wheel tags are not admitted: {tags}")

    try:
        rows = list(
            csv.reader(io.StringIO(member_bytes[record_name].decode("utf-8", "strict")))
        )
    except (csv.Error, UnicodeError) as exc:
        raise RuntimeError(f"{package} wheel RECORD is invalid") from exc
    record_paths: set[str] = set()
    for row in rows:
        if len(row) != 3:
            raise RuntimeError(f"{package} wheel RECORD row shape is invalid")
        name = _strict_relative(row[0], noun="RECORD member").as_posix()
        if name in record_paths or name not in member_bytes:
            raise RuntimeError(f"{package} wheel RECORD path is missing or duplicated")
        record_paths.add(name)
        raw = member_bytes[name]
        if name == record_name:
            if row[1] or row[2]:
                raise RuntimeError(f"{package} wheel RECORD self-row must be unhashed")
            continue
        if row[1] != "sha256=" + _record_hash(raw) or row[2] != str(len(raw)):
            raise RuntimeError(f"{package} wheel RECORD digest or size mismatch")
    if record_paths != set(member_bytes):
        raise RuntimeError(f"{package} wheel RECORD does not enumerate every member")

    member_rows.sort(key=lambda item: str(item["path"]))
    return {
        "package": package,
        "version": version,
        "path": str(path.absolute()),
        "archive_sha256": archive_sha256,
        "archive_size": metadata.st_size,
        "record_sha256": _sha256_bytes(member_bytes[record_name]),
        "member_manifest_sha256": _sha256_bytes(
            _canonical_json(member_rows).encode("utf-8")
        ),
        "member_count": len(member_rows),
        "tags": tags,
        "members": member_rows,
    }


def _host_machine() -> str:
    machine = platform.machine()
    if platform.system() != SUPPORTED_SYSTEM or machine not in SUPPORTED_MACHINES:
        raise RuntimeError("validator supports only CPython 3.12 Linux aarch64/x86_64")
    return machine


def verify_validator_cache(
    validator_root: Path,
    lock: Mapping[str, LockedPackage],
    *,
    machine: str,
) -> tuple[list[Path], list[dict[str, Any]]]:
    wheel_root = validator_root / "wheels"
    try:
        root_metadata = wheel_root.lstat()
    except OSError as exc:
        raise RuntimeError("validator wheel cache is unavailable") from exc
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise RuntimeError("validator wheel cache must be a non-symlink directory")
    expected = {PURE_SOURCES[name].filename for name in VALIDATOR_PACKAGES}
    actual = {item.name for item in wheel_root.iterdir()}
    if actual != expected:
        raise RuntimeError("validator wheel cache file set is not exact")
    paths: list[Path] = []
    evidence: list[dict[str, Any]] = []
    for name in VALIDATOR_IMPORT_ORDER:
        source = PURE_SOURCES[name]
        path = wheel_root / source.filename
        paths.append(path)
        evidence.append(
            verify_wheel(
                path,
                package=name,
                version=EXPECTED_VERSIONS[name],
                allowed_hashes=lock[name].hashes,
                required_tags=("py3-none-any",),
            )
        )
    return paths, evidence


def _installed_record_evidence(
    site_root: Path,
    *,
    archive: Mapping[str, Any],
) -> dict[str, Any]:
    dist_info = site_root / "duckdb-1.5.5.dist-info"
    record_path = dist_info / "RECORD"
    _regular_file(record_path, noun="installed DuckDB RECORD")
    try:
        rows = list(csv.reader(io.StringIO(record_path.read_text(encoding="utf-8"))))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise RuntimeError("installed DuckDB RECORD is invalid") from exc
    verified: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if len(row) != 3:
            raise RuntimeError("installed DuckDB RECORD row shape is invalid")
        relative = _strict_relative(row[0], noun="installed RECORD member")
        name = relative.as_posix()
        if name in seen:
            raise RuntimeError("installed DuckDB RECORD has a duplicate path")
        seen.add(name)
        candidate = site_root.joinpath(*relative.parts)
        _regular_file(candidate, noun="installed DuckDB member")
        raw = candidate.read_bytes()
        if name == "duckdb-1.5.5.dist-info/RECORD":
            if row[1] or row[2]:
                raise RuntimeError("installed DuckDB RECORD self-row must be unhashed")
        elif row[1] != "sha256=" + _record_hash(raw) or row[2] != str(len(raw)):
            raise RuntimeError("installed DuckDB RECORD digest or size mismatch")
        verified.append({"path": name, "sha256": _sha256_bytes(raw), "size": len(raw)})

    actual: set[str] = set()
    for candidate in site_root.rglob("*"):
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeError("DuckDB runtime site contains a symlink")
        if stat.S_ISREG(metadata.st_mode):
            actual.add(candidate.relative_to(site_root).as_posix())
        elif not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeError("DuckDB runtime site contains a special file")
    if actual != seen:
        raise RuntimeError("DuckDB runtime site is not exactly its installed RECORD")
    dist_infos = sorted(item.name for item in site_root.glob("*.dist-info"))
    if dist_infos != ["duckdb-1.5.5.dist-info"]:
        raise RuntimeError("DuckDB runtime contains a foreign distribution")

    archive_members = {
        str(item["path"]): item for item in archive.get("members") or ()
    }
    installed_members = {str(item["path"]): item for item in verified}
    for name, item in archive_members.items():
        if name.endswith(".dist-info/RECORD"):
            continue
        installed = installed_members.get(name)
        if installed is None or installed["sha256"] != item["sha256"]:
            raise RuntimeError("installed DuckDB bytes differ from the admitted wheel")
    extras = set(installed_members) - set(archive_members)
    allowed_extras = {
        "duckdb-1.5.5.dist-info/INSTALLER",
        "duckdb-1.5.5.dist-info/REQUESTED",
        "duckdb-1.5.5.dist-info/direct_url.json",
    }
    if not extras.issubset(allowed_extras):
        raise RuntimeError("installed DuckDB has foreign files outside its wheel")
    installer = site_root / "duckdb-1.5.5.dist-info/INSTALLER"
    if installer.exists() and installer.read_bytes() != b"pip\n":
        raise RuntimeError("installed DuckDB has a foreign installer marker")
    requested = site_root / "duckdb-1.5.5.dist-info/REQUESTED"
    if requested.exists() and requested.read_bytes() not in {b"", b"\n"}:
        raise RuntimeError("installed DuckDB REQUESTED marker is malformed")
    direct_url = site_root / "duckdb-1.5.5.dist-info/direct_url.json"
    if direct_url.exists():
        try:
            payload = json.loads(direct_url.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("DuckDB direct_url evidence is invalid") from exc
        archive_info = payload.get("archive_info") if isinstance(payload, dict) else None
        expected = str(archive["archive_sha256"]).removeprefix("sha256:")
        if not isinstance(archive_info, dict) or archive_info.get("hash") != f"sha256={expected}":
            raise RuntimeError("DuckDB direct_url does not bind the admitted wheel")

    native = sorted(site_root.glob("_duckdb.cpython-312-*.so"))
    if len(native) != 1 or native[0].read_bytes()[:4] != b"\x7fELF":
        raise RuntimeError("DuckDB native CPython 3.12 ELF module is missing")
    verified.sort(key=lambda item: str(item["path"]))
    return {
        "site_root": str(site_root.absolute()),
        "record_path": str(record_path.absolute()),
        "record_sha256": _sha256_file(record_path),
        "installed_manifest_sha256": _sha256_bytes(
            _canonical_json(verified).encode("utf-8")
        ),
        "installed_file_count": len(verified),
        "native_module_path": str(native[0].absolute()),
        "native_module_sha256": _sha256_file(native[0]),
    }


def verify_duckdb_runtime(
    runtime_root: Path,
    lock: Mapping[str, LockedPackage],
    *,
    machine: str,
) -> tuple[Path, dict[str, Any]]:
    runtime_root = runtime_root.absolute()
    site_root = runtime_root / "lib/python3.12/site-packages"
    try:
        metadata = site_root.lstat()
    except OSError as exc:
        raise RuntimeError("DuckDB runtime site-packages is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RuntimeError("DuckDB runtime site-packages is not a real directory")
    source = DUCKDB_SOURCES[machine]
    archive_path = runtime_root / "bootstrap-artifacts" / source.filename
    archive = verify_wheel(
        archive_path,
        package="duckdb",
        version=EXPECTED_VERSIONS["duckdb"],
        allowed_hashes=lock["duckdb"].hashes,
        required_tags=(
            f"cp312-cp312-manylinux_2_26_{machine}",
            f"cp312-cp312-manylinux_2_28_{machine}",
        ),
    )
    installed = _installed_record_evidence(site_root, archive=archive)
    archive = {key: value for key, value in archive.items() if key != "members"}
    return site_root, {"archive": archive, "installed": installed}


def _git(root: Path, *arguments: str, binary: bool = False) -> bytes | str:
    _regular_file(GIT_EXECUTABLE, noun="git executable")
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("GIT_") and key not in {"GIT_CONFIG_NOSYSTEM"}:
            environment.pop(key)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = "/dev/null"
    result = subprocess.run(
        [str(GIT_EXECUTABLE), *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        text=not binary,
        check=False,
    )
    if result.returncode:
        stderr = result.stderr if isinstance(result.stderr, str) else result.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"git {' '.join(arguments)} failed: {stderr.strip()}")
    return result.stdout


def repository_snapshot(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    status = str(_git(root, "status", "--porcelain=v1", "--untracked-files=all"))
    if status:
        raise RuntimeError(f"repository is not clean: {root}")
    branch = str(_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")).strip()
    return {
        "root": str(root),
        "head": str(_git(root, "rev-parse", "--verify", "HEAD")).strip(),
        "tree": str(_git(root, "rev-parse", "--verify", "HEAD^{tree}")).strip(),
        "branch": branch,
        "clean": True,
    }


def _artifact_binding(root: Path, path: Path, *, repository_role: str) -> dict[str, Any]:
    root = root.resolve(strict=True)
    path = path.resolve(strict=True)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise RuntimeError("validation artifact escapes its repository") from exc
    _strict_relative(relative, noun="validation artifact")
    metadata = _regular_file(path, noun="validation artifact")
    blob = _git(root, "show", f"HEAD:{relative}", binary=True)
    mode_line = str(_git(root, "ls-tree", "HEAD", "--", relative)).strip()
    if not mode_line or " blob " not in mode_line:
        raise RuntimeError("validation artifact is not a tracked HEAD blob")
    blob_sha = _sha256_bytes(bytes(blob))
    working_sha = _sha256_file(path)
    if blob_sha != working_sha:
        raise RuntimeError("validation artifact differs from its HEAD blob")
    return {
        "repository_role": repository_role,
        "path": relative,
        "git_mode": mode_line.split()[0],
        "blob_sha256": blob_sha,
        "working_sha256": working_sha,
        "size": metadata.st_size,
    }


def _repository_evidence(
    parent_root: Path,
    accelerate_root: Path,
    lock_path: Path,
    tests: Sequence[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    parent = repository_snapshot(parent_root)
    accelerator = repository_snapshot(accelerate_root)
    try:
        relative_accelerator = accelerate_root.resolve().relative_to(parent_root.resolve()).as_posix()
    except ValueError as exc:
        raise RuntimeError("accelerator checkout is not inside the parent checkout") from exc
    gitlink = str(_git(parent_root, "rev-parse", f"HEAD:{relative_accelerator}")).strip()
    if gitlink != accelerator["head"]:
        raise RuntimeError("parent HEAD gitlink does not match the accelerator checkout")
    parent["accelerator_path"] = relative_accelerator
    parent["accelerator_gitlink"] = gitlink

    artifacts = [
        _artifact_binding(parent_root, SCRIPT_PATH, repository_role="parent"),
        _artifact_binding(parent_root, lock_path, repository_role="parent"),
    ]
    for value in tests:
        relative = _strict_relative(value, noun="validation test")
        if relative.suffix != ".py" or relative.parts[:2] != ("test", "api"):
            raise RuntimeError("validation tests must be Python files below test/api")
        artifacts.append(
            _artifact_binding(
                accelerate_root,
                accelerate_root.joinpath(*relative.parts),
                repository_role="accelerator",
            )
        )
    artifacts.sort(key=lambda item: (str(item["repository_role"]), str(item["path"])))
    return {"parent": parent, "accelerator": accelerator}, artifacts


def _base_probe(base_python: Path) -> dict[str, Any]:
    resolved = base_python.resolve(strict=True)
    metadata = _regular_file(resolved, noun="base Python")
    if metadata.st_uid != 0 or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError("base Python must be root-owned and immutable")
    source = (
        "import json,platform,sys,sysconfig;"
        "print(json.dumps({'implementation':sys.implementation.name,"
        "'version':list(sys.version_info[:3]),'executable':sys.executable,"
        "'prefix':sys.prefix,'base_prefix':sys.base_prefix,"
        "'stdlib':sysconfig.get_path('stdlib'),'machine':platform.machine(),"
        "'system':platform.system(),"
        "'flags':{'isolated':bool(sys.flags.isolated),'no_site':bool(sys.flags.no_site),"
        "'no_user_site':bool(sys.flags.no_user_site),'safe_path':bool(sys.flags.safe_path),"
        "'dont_write_bytecode':bool(sys.flags.dont_write_bytecode)}}))"
    )
    result = subprocess.run(
        [str(resolved), "-I", "-B", "-S", "-c", source],
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("base Python sealed probe failed")
    try:
        probe = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("base Python sealed probe returned invalid JSON") from exc
    expected_flags = {
        "isolated": True,
        "no_site": True,
        "no_user_site": True,
        "safe_path": True,
        "dont_write_bytecode": True,
    }
    if (
        probe.get("implementation") != "cpython"
        or tuple(probe.get("version", ())[:2]) != SUPPORTED_PYTHON
        or probe.get("system") != SUPPORTED_SYSTEM
        or probe.get("machine") not in SUPPORTED_MACHINES
        or probe.get("flags") != expected_flags
        or Path(str(probe.get("executable") or "")).resolve() != resolved
    ):
        raise RuntimeError("base Python is outside the admitted CPython 3.12 host profile")
    stdlib = Path(str(probe["stdlib"])).resolve(strict=True)
    stdlib_metadata = stdlib.lstat()
    if (
        not stat.S_ISDIR(stdlib_metadata.st_mode)
        or stdlib_metadata.st_uid != 0
        or stdlib_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise RuntimeError("base stdlib root is not immutable")
    rows: list[dict[str, Any]] = []
    for candidate in sorted(stdlib.rglob("*"), key=lambda item: item.as_posix()):
        item_metadata = candidate.lstat()
        relative = candidate.relative_to(stdlib).as_posix()
        if stat.S_ISDIR(item_metadata.st_mode):
            continue
        if stat.S_ISLNK(item_metadata.st_mode):
            target = candidate.resolve(strict=True)
            target_metadata = _regular_file(target, noun="stdlib symlink target")
            if target_metadata.st_uid != 0 or target_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise RuntimeError("stdlib symlink target is mutable")
            rows.append(
                {
                    "path": relative,
                    "kind": "symlink",
                    "target": os.readlink(candidate),
                    "resolved": str(target),
                    "sha256": _sha256_file(target),
                }
            )
        elif stat.S_ISREG(item_metadata.st_mode):
            if item_metadata.st_uid != 0 or item_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise RuntimeError("stdlib contains a mutable file")
            rows.append(
                {
                    "path": relative,
                    "kind": "file",
                    "sha256": _sha256_file(candidate),
                    "size": item_metadata.st_size,
                }
            )
        else:
            raise RuntimeError("stdlib contains a special file")
    zip_path = stdlib.parent / "python312.zip"
    paths = [str(zip_path), str(stdlib), str(stdlib / "lib-dynload")]
    probe.update(
        {
            "executable": str(resolved),
            "executable_sha256": _sha256_file(resolved),
            "stdlib": str(stdlib),
            "stdlib_paths": paths,
            "stdlib_manifest_sha256": _sha256_bytes(
                _canonical_json(rows).encode("utf-8")
            ),
            "stdlib_manifest_file_count": len(rows),
            "stdlib_zip_present": zip_path.is_file(),
            "stdlib_zip_sha256": _sha256_file(zip_path) if zip_path.is_file() else "",
        }
    )
    return probe


def _sealed_environment(wrapper_bin: Path) -> dict[str, str]:
    return {
        "IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON": str(
            (wrapper_bin / "python").absolute()
        ),
        "IPFS_ACCEL_IMPORT_EAGER": "0",
        "IPFS_ACCEL_SKIP_CORE": "1",
        "PATH": os.pathsep.join((str(wrapper_bin), "/usr/bin", "/bin")),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def _sanitize_environment(environment: Mapping[str, str], wrapper_bin: Path) -> dict[str, str]:
    blocked_prefixes = ("PYTHON", "PYTEST", "LD_", "COV_CORE_", "COVERAGE_")
    blocked_names = {
        "CONDA_PREFIX",
        "DD_TRACE_ENABLED",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "VIRTUAL_ENV",
    }
    result = {
        key: value
        for key, value in environment.items()
        if not key.startswith(blocked_prefixes) and key not in blocked_names
    }
    result.update(_sealed_environment(wrapper_bin))
    result.setdefault("LANG", "C.UTF-8")
    result.setdefault("LC_ALL", "C.UTF-8")
    return result


def _subprocess_dispatch_source(config: Mapping[str, Any]) -> str:
    sys_path = [str(item) for item in config["sys_path"]]
    environment = _sealed_environment(Path(str(config["wrapper_bin"])))
    return "\n".join(
        (
            "import os,runpy,sys",
            f"sys.path[:] = {sys_path!r}",
            "for _name in tuple(os.environ):",
            "    if (_name.startswith(('PYTHON','PYTEST','LD_','COV_CORE_','COVERAGE_')) "
            "or _name in {'CONDA_PREFIX','DD_TRACE_ENABLED','GIT_DIR','GIT_WORK_TREE','VIRTUAL_ENV'}):",
            "        os.environ.pop(_name,None)",
            f"os.environ.update({environment!r})",
            "args=list(sys.argv[1:])",
            "while args and args[0] in {'-B','-S','-I','-E'}: args.pop(0)",
            "if len(args)>=2 and args[0]=='-m' and args[1]=='pytest':",
            f"    policy=runpy.run_path({str(SCRIPT_PATH)!r})",
            "    import pytest",
            f"    plugins=policy['_sealed_pytest_plugins']({dict(config)!r})",
            "    raise SystemExit(pytest.main(args[2:],plugins=plugins))",
            "if len(args)>=2 and args[0]=='-c':",
            "    source=args[1]",
            "    allowed=(source.startswith('from multiprocessing.spawn import spawn_main; spawn_main(') "
            "or source.startswith('from multiprocessing.resource_tracker import main;main('))",
            "    if not allowed: raise SystemExit('sealed validator Python rejected -c source')",
            "    sys.argv=['-c',*args[2:]]",
            "    exec(compile(source,'<string>','exec'),{'__name__':'__main__','__file__':'<string>'})",
            "    raise SystemExit(0)",
            "raise SystemExit('sealed validator Python accepts only pytest and multiprocessing dispatch')",
        )
    )


def _write_subprocess_wrapper(
    validator_root: Path,
    base_python: Path,
    config: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    bin_root = validator_root / "bin"
    bin_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    wrapper = bin_root / "python"
    source = _subprocess_dispatch_source(config)
    content = (
        "#!/bin/sh\n"
        "set -eu\n"
        "unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE PYTEST_ADDOPTS "
        "PYTEST_PLUGINS LD_PRELOAD LD_LIBRARY_PATH LD_AUDIT || true\n"
        f"exec {shlex.quote(str(base_python))} -I -B -S -c "
        f"{shlex.quote(source)} \"$@\"\n"
    ).encode("utf-8")
    if wrapper.exists():
        _regular_file(wrapper, noun="validator subprocess wrapper")
        if wrapper.read_bytes() != content:
            raise RuntimeError("existing validator subprocess wrapper has foreign bytes")
    else:
        descriptor = os.open(
            wrapper,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o500,
        )
        try:
            os.write(descriptor, content)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    os.chmod(wrapper, 0o500)
    return wrapper, {
        "path": str(wrapper.absolute()),
        "sha256": _sha256_file(wrapper),
        "dispatch_source_sha256": _sha256_bytes(source.encode("utf-8")),
    }


SEALED_SOURCE = "\n".join(
    (
        "import json,os,runpy,sys",
        "config=json.loads(sys.argv[2])",
        "sys.path[:]=config['sys_path']",
        "for name in tuple(os.environ):",
        "    if (name.startswith(('PYTHON','PYTEST','LD_','COV_CORE_','COVERAGE_')) "
        "or name in {'CONDA_PREFIX','DD_TRACE_ENABLED','GIT_DIR','GIT_WORK_TREE','VIRTUAL_ENV'}):",
        "        os.environ.pop(name,None)",
        "os.environ.update(config['sealed_environment'])",
        "policy=runpy.run_path(sys.argv[1])",
        "raise SystemExit(policy['_sealed_worker'](config))",
    )
)


def _sealed_worker(config: Mapping[str, Any]) -> int:
    """Entry point executed only by the ``-I -B -S`` validation child."""

    import importlib
    import importlib.metadata
    import importlib.util
    import multiprocessing

    expected_flags = {
        "isolated": True,
        "no_site": True,
        "no_user_site": True,
        "safe_path": True,
        "dont_write_bytecode": True,
    }
    actual_flags = {
        "isolated": bool(sys.flags.isolated),
        "no_site": bool(sys.flags.no_site),
        "no_user_site": bool(sys.flags.no_user_site),
        "safe_path": bool(sys.flags.safe_path),
        "dont_write_bytecode": bool(sys.flags.dont_write_bytecode),
    }
    if actual_flags != expected_flags or list(sys.path) != list(config["sys_path"]):
        raise RuntimeError("sealed validator interpreter contract is not exact")
    if os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1":
        raise RuntimeError("pytest plugin autoload is not disabled")
    forbidden = [
        name
        for name in os.environ
        if name in {"PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS"}
        or name.startswith("LD_")
    ]
    if forbidden:
        raise RuntimeError(f"sealed validator inherited injection variables: {forbidden}")

    distributions: dict[str, str] = {}
    for distribution in importlib.metadata.distributions(path=list(config["distribution_paths"])):
        name = _normalized_name(str(distribution.metadata.get("Name") or ""))
        if name in distributions:
            raise RuntimeError("sealed validator sees a duplicate distribution")
        distributions[name] = str(distribution.version)
    if distributions != dict(config["expected_versions"]):
        raise RuntimeError(f"sealed validator distribution set is foreign: {distributions}")

    pytest = importlib.import_module("pytest")
    pytest_origin = str(Path(str(pytest.__file__)).absolute())
    if not any(pytest_origin.startswith(str(Path(path).absolute()) + os.sep) for path in config["wheel_paths"]):
        raise RuntimeError("pytest did not load from a verified validator wheel")
    duckdb = importlib.import_module("duckdb")
    duckdb_origin = Path(str(duckdb.__file__)).resolve(strict=True)
    try:
        duckdb_origin.relative_to(Path(str(config["runtime_site"])).resolve(strict=True))
    except ValueError as exc:
        raise RuntimeError("DuckDB did not load from the sealed runtime") from exc
    if str(getattr(duckdb, "__version__", "")) != EXPECTED_VERSIONS["duckdb"]:
        raise RuntimeError("loaded DuckDB version is not exact")
    accelerate_spec = importlib.util.find_spec("ipfs_accelerate_py")
    origins = [] if accelerate_spec is None else list(accelerate_spec.submodule_search_locations or ())
    if accelerate_spec is not None and accelerate_spec.origin:
        origins.append(accelerate_spec.origin)
    accelerate_root = Path(str(config["accelerate_root"])).resolve(strict=True)
    if not origins or any(
        not Path(str(origin)).resolve(strict=True).is_relative_to(accelerate_root)
        for origin in origins
    ):
        raise RuntimeError("accelerator package does not resolve from the bound checkout")

    multiprocessing.set_executable(str(config["subprocess_wrapper"]))
    return int(
        pytest.main(
            list(config["pytest_args"]),
            plugins=_sealed_pytest_plugins(config),
        )
    )


class _SealedValidationPlugin:
    """Install the nested launcher after collection has fixed package names."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self._config = dict(config)

    def pytest_collection_finish(self, session: object) -> None:
        del session
        _install_accelerator_validation_adapter(self._config)


def _sealed_pytest_plugins(config: Mapping[str, Any]) -> list[object]:
    return [_SealedValidationPlugin(config)]


def _install_accelerator_validation_adapter(config: Mapping[str, Any]) -> None:
    """Route reviewed nested Python validations through the sealed wrapper.

    The accelerator's validation runtime normally accepts only an immutable
    system interpreter.  This validator has independently hash-checked its
    user-owned wrapper before execution and checks it again afterward, so the
    in-process adapter admits that one exact path without weakening any other
    validation-runtime toolchain check.
    """

    import importlib

    module = importlib.import_module(
        "ipfs_accelerate_py.agent_supervisor.validation_runtime"
    )
    module_path = Path(str(module.__file__)).resolve(strict=True)
    accelerate_root = Path(str(config["accelerate_root"])).resolve(strict=True)
    try:
        module_path.relative_to(accelerate_root)
    except ValueError as exc:
        raise RuntimeError("validation-runtime adapter resolved from a foreign checkout") from exc
    wrapper = Path(str(config["subprocess_wrapper"])).resolve(strict=True)
    _regular_file(wrapper, noun="sealed nested-validation wrapper")
    expected_sha256 = str(config.get("subprocess_wrapper_sha256") or "")
    actual_sha256 = _sha256_file(wrapper)
    if expected_sha256 and actual_sha256 != expected_sha256:
        raise RuntimeError("sealed nested-validation wrapper hash changed")
    configured = os.environ.get("IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON", "")
    if configured != str(wrapper):
        raise RuntimeError("nested-validation Python is not the sealed wrapper")
    current = module.validation_python_executable
    if getattr(current, "__dqk_sealed_validator_adapter__", False):
        return
    original_identity = module._file_identity

    def validation_python_executable(
        environment: Mapping[str, object] | None = None,
    ) -> str:
        source = os.environ if environment is None else environment
        requested = str(
            source.get("IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON") or ""
        )
        if requested and requested != str(wrapper):
            raise module.ValidationRuntimeError(
                "nested validation Python lost its validator binding"
            )
        if os.environ.get("IPFS_ACCELERATE_AGENT_VALIDATION_PYTHON") != str(
            wrapper
        ):
            raise module.ValidationRuntimeError(
                "nested validation process lost its validator binding"
            )
        return str(wrapper)

    validation_python_executable.__dqk_sealed_validator_adapter__ = True

    def file_identity(path: Path) -> dict[str, object]:
        try:
            selected = Path(path).resolve(strict=True)
        except OSError:
            selected = Path(path)
        if selected != wrapper:
            return original_identity(path)
        metadata = _regular_file(wrapper, noun="sealed nested-validation wrapper")
        return {
            "path": str(wrapper),
            "sha256": actual_sha256.removeprefix("sha256:"),
            "size": metadata.st_size,
            "mode": stat.S_IMODE(metadata.st_mode),
        }

    file_identity.__dqk_sealed_validator_adapter__ = True
    module.validation_python_executable = validation_python_executable
    module._file_identity = file_identity


def _run_bounded(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    stdout_limit: int,
    stderr_limit: int,
    combined_limit: int,
) -> tuple[int, bytes, bytes]:
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    started = time.monotonic()
    violation = ""
    try:
        while selector.get_map():
            if time.monotonic() - started > timeout_seconds:
                violation = "validation subprocess exceeded its timeout"
                break
            for key, _mask in selector.select(timeout=0.1):
                chunk = os.read(key.fileobj.fileno(), 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffers[str(key.data)].extend(chunk)
                if len(buffers["stdout"]) > stdout_limit:
                    violation = "validation stdout exceeded its byte bound"
                elif len(buffers["stderr"]) > stderr_limit:
                    violation = "validation stderr exceeded its byte bound"
                elif len(buffers["stdout"]) + len(buffers["stderr"]) > combined_limit:
                    violation = "validation combined output exceeded its byte bound"
                if violation:
                    break
            if violation:
                break
        if violation:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=10)
    finally:
        selector.close()
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)
    if violation:
        raise RuntimeError(violation)
    return process.returncode, bytes(buffers["stdout"]), bytes(buffers["stderr"])


def _atomic_receipt(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.absolute()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if path.exists():
        _regular_file(path, noun="validation receipt")
        if path.read_bytes() != encoded:
            raise RuntimeError("validation receipt path already contains different bytes")
        return
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def run_validation(
    *,
    parent_root: Path,
    accelerate_root: Path,
    runtime_root: Path,
    validator_root: Path,
    base_python: Path,
    lock_path: Path,
    tests: Sequence[str],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    stdout_limit: int = DEFAULT_STDOUT_LIMIT,
    stderr_limit: int = DEFAULT_STDERR_LIMIT,
    combined_limit: int = DEFAULT_COMBINED_LIMIT,
) -> dict[str, Any]:
    lock = parse_lock(lock_path)
    machine = _host_machine()
    base = _base_probe(base_python)
    repository_before, artifacts = _repository_evidence(
        parent_root, accelerate_root, lock_path, tests
    )
    wheel_paths, wheels = verify_validator_cache(
        validator_root, lock, machine=machine
    )
    runtime_site, duckdb = verify_duckdb_runtime(runtime_root, lock, machine=machine)
    sys_path = [
        *[str(item) for item in base["stdlib_paths"]],
        *[str(item.absolute()) for item in wheel_paths],
        str(runtime_site.absolute()),
        str(accelerate_root.resolve(strict=True)),
    ]
    wrapper_config: dict[str, Any] = {
        "accelerate_root": str(accelerate_root.resolve(strict=True)),
        "subprocess_wrapper": str((validator_root / "bin/python").absolute()),
        "sys_path": sys_path,
        "wrapper_bin": str((validator_root / "bin").absolute()),
    }
    wrapper, wrapper_evidence = _write_subprocess_wrapper(
        validator_root, Path(str(base["executable"])), wrapper_config
    )
    pytest_args = [
        "-q",
        "-p",
        "no:cacheprovider",
        "--color=no",
        "-c",
        "/dev/null",
        f"--rootdir={accelerate_root.resolve(strict=True)}",
        f"--confcutdir={accelerate_root.resolve(strict=True) / 'test/api'}",
        *tests,
    ]
    config: dict[str, Any] = {
        "accelerate_root": str(accelerate_root.resolve(strict=True)),
        "distribution_paths": [
            *[str(item.absolute()) for item in wheel_paths],
            str(runtime_site.absolute()),
        ],
        "expected_versions": dict(sorted(EXPECTED_VERSIONS.items())),
        "pytest_args": pytest_args,
        "runtime_site": str(runtime_site.absolute()),
        "sealed_environment": _sealed_environment(validator_root / "bin"),
        "subprocess_wrapper": str(wrapper.absolute()),
        "subprocess_wrapper_sha256": wrapper_evidence["sha256"],
        "sys_path": sys_path,
        "wheel_paths": [str(item.absolute()) for item in wheel_paths],
    }
    config_json = _canonical_json(config)
    actual_argv = [
        str(base["executable"]),
        "-I",
        "-B",
        "-S",
        "-c",
        SEALED_SOURCE,
        str(SCRIPT_PATH),
        config_json,
    ]
    canonical_invocation = {
        "argv": [
            str(base["executable"]),
            "-I",
            "-B",
            "-S",
            "-c",
            f"<sealed-source:{_sha256_bytes(SEALED_SOURCE.encode('utf-8'))}>",
            str(SCRIPT_PATH),
            f"<config:{_sha256_bytes(config_json.encode('utf-8'))}>",
        ],
        "cwd": str(accelerate_root.resolve(strict=True)),
        "pytest_args": pytest_args,
    }
    environment = _sanitize_environment(os.environ, validator_root / "bin")
    returncode, stdout, stderr = _run_bounded(
        actual_argv,
        cwd=accelerate_root,
        environment=environment,
        timeout_seconds=timeout_seconds,
        stdout_limit=stdout_limit,
        stderr_limit=stderr_limit,
        combined_limit=combined_limit,
    )
    repository_after, artifacts_after = _repository_evidence(
        parent_root, accelerate_root, lock_path, tests
    )
    if repository_after != repository_before or artifacts_after != artifacts:
        raise RuntimeError("repository or validation artifact changed during validation")
    wheel_paths_after, wheels_after = verify_validator_cache(
        validator_root, lock, machine=machine
    )
    runtime_site_after, duckdb_after = verify_duckdb_runtime(
        runtime_root, lock, machine=machine
    )
    if (
        wheel_paths_after != wheel_paths
        or wheels_after != wheels
        or runtime_site_after != runtime_site
        or duckdb_after != duckdb
        or _sha256_file(wrapper) != wrapper_evidence["sha256"]
    ):
        raise RuntimeError("validation runtime or wheel artifact changed during validation")
    if returncode:
        tail = (stdout + stderr).decode("utf-8", "replace").splitlines()[-40:]
        raise RuntimeError("sealed pytest validation failed: " + "\n".join(tail))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "base_python": base,
        "canonical_invocation": canonical_invocation,
        "duckdb_runtime": duckdb,
        "lock": {
            "path": str(lock_path.resolve(strict=True)),
            "sha256": _sha256_file(lock_path),
            "packages": {
                name: {"version": item.version, "hashes": sorted(item.hashes)}
                for name, item in sorted(lock.items())
            },
        },
        "output": {
            "returncode": returncode,
            "stdout_bytes": len(stdout),
            "stdout_sha256": _sha256_bytes(stdout),
            "stderr_bytes": len(stderr),
            "stderr_sha256": _sha256_bytes(stderr),
            "bounds": {
                "stdout": stdout_limit,
                "stderr": stderr_limit,
                "combined": combined_limit,
                "timeout_seconds": timeout_seconds,
            },
        },
        "repository_after": repository_after,
        "repository_before": repository_before,
        "subprocess_wrapper": wrapper_evidence,
        "validation_artifacts": artifacts,
        "validator_wheels": [
            {key: value for key, value in item.items() if key != "members"}
            for item in wheels
        ],
    }
    payload["receipt_id"] = _sha256_bytes(_canonical_json(payload).encode("utf-8"))
    return payload


def provision_cache(
    validator_root: Path,
    lock_path: Path,
    *,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    lock = parse_lock(lock_path)
    machine = _host_machine()
    for source in PURE_SOURCES.values():
        if "sha256:" + source.sha256 not in lock[source.package].hashes:
            raise RuntimeError("checked-in artifact URL/hash differs from the lock")
    validator_root = validator_root.absolute()
    wheel_root = validator_root / "wheels"
    wheel_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in VALIDATOR_PACKAGES:
        source = PURE_SOURCES[name]
        target = wheel_root / source.filename
        if target.exists():
            _regular_file(target, noun=f"cached {name} wheel")
            if _sha256_file(target) != "sha256:" + source.sha256:
                raise RuntimeError(f"existing cached {name} wheel has foreign bytes")
            continue
        request = urllib.request.Request(source.url, headers={"User-Agent": "dqk-validator/1"})
        descriptor, temporary = tempfile.mkstemp(prefix=f".{source.filename}.", dir=wheel_root)
        digest = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(
                request, timeout=timeout_seconds
            ) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_WHEEL_UNCOMPRESSED_BYTES:
                        raise RuntimeError(f"downloaded {name} wheel exceeded its bound")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != source.sha256:
                raise RuntimeError(f"downloaded {name} wheel hash mismatch")
            os.chmod(temporary, 0o400)
            os.replace(temporary, target)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    paths, evidence = verify_validator_cache(validator_root, lock, machine=machine)
    payload: dict[str, Any] = {
        "schema": CACHE_SCHEMA,
        "validator_root": str(validator_root),
        "lock_path": str(lock_path.resolve(strict=True)),
        "lock_sha256": _sha256_file(lock_path),
        "wheel_paths": [str(item) for item in paths],
        "wheels": [{key: value for key, value in item.items() if key != "members"} for item in evidence],
    }
    payload["receipt_id"] = _sha256_bytes(_canonical_json(payload).encode("utf-8"))
    _atomic_receipt(validator_root / "wheel-cache-receipt.json", payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    provision = commands.add_parser("provision", help="download and verify pure validator wheels")
    provision.add_argument("--validator-root", type=Path, default=DEFAULT_VALIDATOR_ROOT)
    provision.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    provision.add_argument("--timeout-seconds", type=float, default=120.0)

    run = commands.add_parser("run", help="run sealed pytest and emit a content-bound receipt")
    run.add_argument("--parent-root", type=Path, default=REPO_ROOT)
    run.add_argument("--accelerate-root", type=Path, default=DEFAULT_ACCELERATE_ROOT)
    run.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    run.add_argument("--validator-root", type=Path, default=DEFAULT_VALIDATOR_ROOT)
    run.add_argument("--base-python", type=Path, default=DEFAULT_BASE_PYTHON)
    run.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    run.add_argument("--test", action="append", dest="tests")
    run.add_argument("--receipt", type=Path)
    run.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    run.add_argument("--stdout-limit", type=int, default=DEFAULT_STDOUT_LIMIT)
    run.add_argument("--stderr-limit", type=int, default=DEFAULT_STDERR_LIMIT)
    run.add_argument("--combined-limit", type=int, default=DEFAULT_COMBINED_LIMIT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "provision":
            payload = provision_cache(
                args.validator_root,
                args.lock,
                timeout_seconds=args.timeout_seconds,
            )
        else:
            tests = tuple(args.tests or DEFAULT_TESTS)
            if (
                args.timeout_seconds <= 0
                or args.stdout_limit <= 0
                or args.stderr_limit <= 0
                or args.combined_limit <= 0
                or args.combined_limit > args.stdout_limit + args.stderr_limit
            ):
                raise RuntimeError("validation timeout/output bounds are invalid")
            payload = run_validation(
                parent_root=args.parent_root,
                accelerate_root=args.accelerate_root,
                runtime_root=args.runtime_root,
                validator_root=args.validator_root,
                base_python=args.base_python,
                lock_path=args.lock,
                tests=tests,
                timeout_seconds=args.timeout_seconds,
                stdout_limit=args.stdout_limit,
                stderr_limit=args.stderr_limit,
                combined_limit=args.combined_limit,
            )
            if args.receipt is not None:
                _atomic_receipt(args.receipt, payload)
        print(_canonical_json(payload))
        return 0
    except Exception as exc:
        print(
            _canonical_json(
                {
                    "schema": "ipfs_datasets_py/duckdb-quack-validator-error@1",
                    "error": type(exc).__name__,
                    "detail": str(exc),
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
