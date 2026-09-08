#!/usr/bin/env python3
"""Produce read-only evidence for the State Laws optimistic public parent.

This LCR-084 verifier deliberately keeps two revisions separate:

* 42f0546acc7c6cd55627eaf51fb820d5613b9021 is historical sealed evidence.
* 78cba0ed86c3971a7b90620c6df167af8a1a6fb2 is only the optimistic parent
  and rollback target for a corrected publication.

The resulting receipt never accepts the corpus and never authorizes mutation.
It binds mutable main to the expected current parent, verifies raw Git commit
objects and exact ancestry, walks both recursive trees through every page,
checks their exact delta, and independently downloads and hashes the two
changed root blobs at both revisions.  Every request and response is hashed.

The command has no output-file or publication option.  It can observe live
state to stdout, or validate a previously saved receipt.  Tests use the
injected transport and clock seams without contacting Hugging Face.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, Self

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

TASK_ID = "LCR-084"
GOAL_ID = "LCR-G146"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "audit_state_laws_current_public_parent.py@1"
REPORT_SCHEMA = "ipfs_datasets_py/state-laws-current-public-parent-evidence@1"
SCHEMA_VERSION = "1"
RECEIPT_SELF_DIGEST_FIELD = "receipt_sha256"
REPO_ID = "justicedao/ipfs_state_laws"

HISTORICAL_BASELINE_PIN = "42f0546acc7c6cd55627eaf51fb820d5613b9021"
CURRENT_PUBLIC_PARENT_PIN = "78cba0ed86c3971a7b90620c6df167af8a1a6fb2"
HISTORICAL_BASELINE_TREE_OID = "54bc2acf18f1e27ddde070565ffe89854621d2d1"
CURRENT_PUBLIC_PARENT_TREE_OID = "946615aca49847b5d2ee0c6b7da05589e4b4bcd0"

HISTORICAL_FILE_COUNT = 2_116
HISTORICAL_DIRECTORY_COUNT = 762
HISTORICAL_TREE_PATH_COUNT = 2_878
CURRENT_FILE_COUNT = 2_348
CURRENT_DIRECTORY_COUNT = 883
CURRENT_TREE_PATH_COUNT = 3_231
ADDED_FILE_COUNT = 232
ADDED_DIRECTORY_COUNT = 121
ADDED_TREE_PATH_COUNT = 353
DELETED_TREE_PATH_COUNT = 0
MODIFIED_BLOB_PATHS = ("README.md", "manifest.json")

ROOT_BLOB_SHA256: Mapping[str, Mapping[str, str]] = {
    HISTORICAL_BASELINE_PIN: {
        "README.md": "43998f19d35018ca93026e41b05aacc0681855d1ee3f9ee5a2b762b934f947a3",
        "manifest.json": "2303375641aa1adf0972374af4bfdadfd93b915a7640ad20d541c639fb017cb3",
    },
    CURRENT_PUBLIC_PARENT_PIN: {
        "README.md": "c3f4e0b1a83d26f568ae22901a82b671c90e6c2b3d21f7800a2ce98eff8ec80f",
        "manifest.json": "d06d97711614bd2f06c745e684243ea6d37ae90bca03b692eca839523e2a43a3",
    },
}
ROOT_BLOB_GIT_OIDS: Mapping[str, Mapping[str, str]] = {
    HISTORICAL_BASELINE_PIN: {
        "README.md": "957619fe28376aeb696945c80029cdd5f446d5e0",
        "manifest.json": "4318a4217c264ebe27764c2d2ede65c8eaa50981",
    },
    CURRENT_PUBLIC_PARENT_PIN: {
        "README.md": "ce614c9fa8493fe8c1c0e787e2c154c834aa22c7",
        "manifest.json": "5fe9e0366e13951977e5443ce816bb1a71a1142e",
    },
}

MAX_EVIDENCE_AGE_SECONDS = 30 * 60
MAX_FUTURE_SKEW_SECONDS = 0
MAX_HTTP_BODY_BYTES = 64 * 1024 * 1024
MAX_RECEIPT_BYTES = 64 * 1024 * 1024
SCHEMA_RELPATH = Path(
    "data/legal/state_laws_current_public_parent_evidence.schema.json"
)
CANONICAL_RECEIPT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/state_laws_current_public_parent_evidence.json"
)
HUB_API_ROOT = "https://huggingface.co/api"
HUB_DATASET_ROOT = "https://huggingface.co/datasets"
USER_AGENT = "ipfs_datasets_py-LCR-084-read-only"
ALLOWED_HUB_RESPONSE_HOSTS = frozenset(
    {
        "huggingface.co",
        "cdn-lfs.huggingface.co",
        "cdn-lfs-us-1.hf.co",
        "cdn-lfs-eu-1.hf.co",
    }
)

SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
NEXT_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="next"', re.IGNORECASE)


class PublicParentEvidenceError(RuntimeError):
    """Raised whenever current-public-parent evidence cannot fail closed."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_canonical(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PublicParentEvidenceError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _strict_json_loads(body: bytes | str, label: str) -> Any:
    try:
        text = body.decode("utf-8") if isinstance(body, bytes) else body
        return json.loads(text, object_pairs_hook=_strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicParentEvidenceError(f"{label} is not strict JSON") from exc


def git_object_oid(kind: str, body: bytes) -> str:
    if kind not in {"blob", "commit"}:
        raise ValueError(f"unsupported Git object kind: {kind}")
    header = f"{kind} {len(body)}\0".encode("ascii")
    return hashlib.sha1(header + body).hexdigest()


def _system_utc_now() -> datetime:
    return datetime.now(UTC)


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PublicParentEvidenceError("verifier clock returned a naive datetime")
    value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or UTC_RE.fullmatch(value) is None:
        raise PublicParentEvidenceError("observed_at_utc is not strict UTC")
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError as exc:
        raise PublicParentEvidenceError("observed_at_utc is invalid") from exc


def _require_sha1(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA1_RE.fullmatch(value) is None:
        raise PublicParentEvidenceError(f"{label} is not a lowercase Git SHA-1")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise PublicParentEvidenceError(f"{label} is not a lowercase SHA-256")
    return value


def _safe_repo_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PublicParentEvidenceError("tree entry has an invalid path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or value != pure.as_posix():
        raise PublicParentEvidenceError(f"unsafe or non-canonical tree path: {value!r}")
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise PublicParentEvidenceError(f"unsafe tree path: {value!r}")
    return value


@dataclass(frozen=True)
class EvidenceContract:
    """All immutable facts that a receipt must establish."""

    repository: str
    historical_pin: str
    current_parent_pin: str
    historical_tree_oid: str
    current_tree_oid: str
    historical_files: int
    historical_directories: int
    current_files: int
    current_directories: int
    added_files: int
    added_directories: int
    modified_blob_paths: tuple[str, ...]
    root_blob_sha256: Mapping[str, Mapping[str, str]]
    root_blob_git_oids: Mapping[str, Mapping[str, str]]

    @property
    def historical_paths(self) -> int:
        return self.historical_files + self.historical_directories

    @property
    def current_paths(self) -> int:
        return self.current_files + self.current_directories

    @property
    def added_paths(self) -> int:
        return self.added_files + self.added_directories


DEFAULT_CONTRACT = EvidenceContract(
    repository=REPO_ID,
    historical_pin=HISTORICAL_BASELINE_PIN,
    current_parent_pin=CURRENT_PUBLIC_PARENT_PIN,
    historical_tree_oid=HISTORICAL_BASELINE_TREE_OID,
    current_tree_oid=CURRENT_PUBLIC_PARENT_TREE_OID,
    historical_files=HISTORICAL_FILE_COUNT,
    historical_directories=HISTORICAL_DIRECTORY_COUNT,
    current_files=CURRENT_FILE_COUNT,
    current_directories=CURRENT_DIRECTORY_COUNT,
    added_files=ADDED_FILE_COUNT,
    added_directories=ADDED_DIRECTORY_COUNT,
    modified_blob_paths=MODIFIED_BLOB_PATHS,
    root_blob_sha256=ROOT_BLOB_SHA256,
    root_blob_git_oids=ROOT_BLOB_GIT_OIDS,
)


@dataclass(frozen=True)
class EvidenceResponse:
    """Raw response plus public, credential-free request metadata."""

    method: str
    endpoint: str
    status: int
    headers: Mapping[str, str]
    body: bytes


class EvidenceTransport(Protocol):
    """Injected, read-only transport used by the collector."""

    kind: str

    def request(self, method: str, endpoint: str) -> EvidenceResponse:
        """Return an HTTP response without mutating remote state."""

    def commit_object(self, repository: str, revision: str) -> EvidenceResponse:
        """Return the raw content of one Git commit object."""


class LiveHubTransport:
    """Credential-free HTTPS and Git transport for the public dataset."""

    kind = "hub_https_git_read_only"

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._git_dir: Path | None = None
        self._fetched_repository: str | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
        self._temporary = None
        self._git_dir = None
        self._fetched_repository = None

    def request(self, method: str, endpoint: str) -> EvidenceResponse:
        if method.upper() != "GET":
            raise PublicParentEvidenceError("live transport permits GET only")
        parsed = urllib.parse.urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in ALLOWED_HUB_RESPONSE_HOSTS
        ):
            raise PublicParentEvidenceError(f"refusing non-Hub endpoint: {endpoint}")
        request = urllib.request.Request(
            endpoint,
            method="GET",
            headers={"Accept": "application/json,*/*", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                body = response.read(MAX_HTTP_BODY_BYTES + 1)
                status = int(getattr(response, "status", response.getcode()))
                headers = {str(k): str(v) for k, v in response.headers.items()}
                final_url = urllib.parse.urlsplit(response.geturl())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PublicParentEvidenceError(
                f"read-only Hub request failed: {endpoint}"
            ) from exc
        if len(body) > MAX_HTTP_BODY_BYTES:
            raise PublicParentEvidenceError(f"Hub response too large: {endpoint}")
        if (
            final_url.scheme != "https"
            or final_url.hostname not in ALLOWED_HUB_RESPONSE_HOSTS
        ):
            raise PublicParentEvidenceError("Hub response redirected off allowlist")
        return EvidenceResponse(
            method="GET",
            endpoint=endpoint,
            status=status,
            headers=headers,
            body=body,
        )

    def _ensure_git_fetch(self, repository: str) -> None:
        if self._fetched_repository == repository and self._git_dir is not None:
            return
        if repository != REPO_ID:
            raise PublicParentEvidenceError("live Git transport refuses another repo")
        self.close()
        self._temporary = tempfile.TemporaryDirectory(prefix="lcr084-readonly-")
        self._git_dir = Path(self._temporary.name) / "repo.git"
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
        }
        init = subprocess.run(
            ["git", "init", "--bare", str(self._git_dir)],
            check=False,
            capture_output=True,
            env=env,
        )
        if init.returncode != 0:
            raise PublicParentEvidenceError("could not initialize temporary Git store")
        remote = f"{HUB_DATASET_ROOT}/{repository}"
        fetch = subprocess.run(
            [
                "git",
                "-c",
                "credential.helper=",
                f"--git-dir={self._git_dir}",
                "fetch",
                "--no-tags",
                "--depth=2",
                "--filter=blob:none",
                remote,
                "main",
            ],
            check=False,
            capture_output=True,
            env=env,
            timeout=max(60.0, self.timeout_seconds * 4),
        )
        if fetch.returncode != 0:
            self.close()
            raise PublicParentEvidenceError("read-only shallow Git fetch failed")
        self._fetched_repository = repository

    def commit_object(self, repository: str, revision: str) -> EvidenceResponse:
        _require_sha1(revision, "commit revision")
        self._ensure_git_fetch(repository)
        assert self._git_dir is not None
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
        result = subprocess.run(
            [
                "git",
                f"--git-dir={self._git_dir}",
                "cat-file",
                "commit",
                revision,
            ],
            check=False,
            capture_output=True,
            env=env,
            timeout=self.timeout_seconds,
        )
        if result.returncode != 0:
            raise PublicParentEvidenceError(f"Git commit is unavailable: {revision}")
        return EvidenceResponse(
            method="GIT_CAT_FILE",
            endpoint=f"{HUB_DATASET_ROOT}/{repository}.git#commit={revision}",
            status=200,
            headers={"Content-Type": "application/x-git-commit"},
            body=result.stdout,
        )


def _response_record(response: EvidenceResponse) -> dict[str, Any]:
    request_material = {
        "method": response.method.upper(),
        "endpoint": response.endpoint,
        "accept": "public-read-only",
    }
    return {
        **request_material,
        "request_sha256": sha256_canonical(request_material),
        "status": int(response.status),
        "response_bytes": len(response.body),
        "response_sha256": sha256_bytes(response.body),
    }


def _require_success(response: EvidenceResponse, label: str) -> None:
    if response.status != 200:
        raise PublicParentEvidenceError(
            f"{label} returned HTTP/status {response.status}, expected 200"
        )
    if not isinstance(response.body, bytes):
        raise PublicParentEvidenceError(f"{label} body is not bytes")


def _json_body(response: EvidenceResponse, label: str) -> Any:
    _require_success(response, label)
    return _strict_json_loads(response.body, label)


def _require_exact_response(
    response: EvidenceResponse, *, method: str, endpoint: str, label: str
) -> None:
    if response.method.upper() != method or response.endpoint != endpoint:
        raise PublicParentEvidenceError(f"{label} response provenance mismatch")
    _require_success(response, label)


def _parse_commit_object(body: bytes, expected_oid: str) -> dict[str, Any]:
    if git_object_oid("commit", body) != expected_oid:
        raise PublicParentEvidenceError(
            f"raw Git commit object does not hash to {expected_oid}"
        )
    try:
        header_block = body.split(b"\n\n", 1)[0].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicParentEvidenceError("Git commit headers are not UTF-8") from exc
    headers: list[tuple[str, str]] = []
    for line in header_block.splitlines():
        if line.startswith(" ") or not line:
            continue
        name, separator, value = line.partition(" ")
        if not separator:
            raise PublicParentEvidenceError("malformed Git commit header")
        headers.append((name, value))
    trees = [value for name, value in headers if name == "tree"]
    parents = [value for name, value in headers if name == "parent"]
    if len(trees) != 1:
        raise PublicParentEvidenceError("Git commit must contain exactly one tree")
    _require_sha1(trees[0], "commit tree")
    for index, parent in enumerate(parents):
        _require_sha1(parent, f"commit parent {index}")
    return {
        "commit_oid": expected_oid,
        "tree_oid": trees[0],
        "parent_oids": parents,
        "raw_commit_sha256": sha256_bytes(body),
        "raw_commit_bytes": len(body),
    }


def _next_link(headers: Mapping[str, str]) -> str | None:
    link_value = next(
        (str(value) for key, value in headers.items() if key.lower() == "link"),
        "",
    )
    match = NEXT_LINK_RE.search(link_value)
    if match is None:
        return None
    endpoint = match.group(1)
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != "https" or parsed.hostname != "huggingface.co":
        raise PublicParentEvidenceError("tree pagination escaped Hub API")
    return endpoint


def _require_tree_page_endpoint(
    endpoint: str, *, repository: str, revision: str
) -> None:
    parsed = urllib.parse.urlsplit(endpoint)
    expected_path = (
        f"/api/datasets/{urllib.parse.quote(repository, safe='/')}/tree/{revision}"
    )
    if (
        parsed.scheme != "https"
        or parsed.hostname != "huggingface.co"
        or parsed.path != expected_path
    ):
        raise PublicParentEvidenceError(
            "tree pagination changed repository or immutable revision"
        )


def _normalize_tree_entry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise PublicParentEvidenceError("tree page contains a non-object entry")
    path = _safe_repo_path(raw.get("path"))
    entry_type = raw.get("type", raw.get("kind"))
    if entry_type == "directory":
        oid = _require_sha1(raw.get("oid"), f"directory oid for {path}")
        return {"path": path, "kind": "directory", "oid": oid}
    if entry_type != "file":
        raise PublicParentEvidenceError(f"unknown tree entry type at {path}")
    oid = _require_sha1(raw.get("oid"), f"file oid for {path}")
    size = raw.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise PublicParentEvidenceError(f"invalid file size at {path}")
    normalized: dict[str, Any] = {
        "path": path,
        "kind": "file",
        "oid": oid,
        "size": size,
    }
    lfs = raw.get("lfs")
    if lfs is not None:
        if not isinstance(lfs, Mapping):
            raise PublicParentEvidenceError(f"invalid LFS metadata at {path}")
        lfs_oid = str(lfs.get("oid") or lfs.get("sha256") or "")
        lfs_oid = lfs_oid.removeprefix("sha256:")
        normalized["lfs"] = {
            "oid": _require_sha256(lfs_oid, f"LFS oid for {path}"),
            "size": lfs.get("size"),
        }
        if (
            isinstance(normalized["lfs"]["size"], bool)
            or not isinstance(normalized["lfs"]["size"], int)
            or normalized["lfs"]["size"] < 0
        ):
            raise PublicParentEvidenceError(f"invalid LFS size at {path}")
    return normalized


def _validate_tree_closure(entries: Sequence[Mapping[str, Any]]) -> None:
    kinds = {str(entry["path"]): str(entry["kind"]) for entry in entries}
    for path in kinds:
        parent = PurePosixPath(path).parent
        while parent != PurePosixPath("."):
            parent_path = parent.as_posix()
            if kinds.get(parent_path) != "directory":
                raise PublicParentEvidenceError(
                    f"tree lacks directory ancestor {parent_path!r} for {path!r}"
                )
            parent = parent.parent


def _inventory_tree(
    transport: EvidenceTransport,
    *,
    repository: str,
    revision: str,
    request_records: list[dict[str, Any]],
) -> dict[str, Any]:
    quoted_repo = urllib.parse.quote(repository, safe="/")
    endpoint: str | None = (
        f"{HUB_API_ROOT}/datasets/{quoted_repo}/tree/{revision}"
        "?recursive=true&expand=false&limit=1000"
    )
    pages: list[dict[str, Any]] = []
    entries_by_path: dict[str, dict[str, Any]] = {}
    seen_endpoints: set[str] = set()
    while endpoint is not None:
        _require_tree_page_endpoint(endpoint, repository=repository, revision=revision)
        if endpoint in seen_endpoints:
            raise PublicParentEvidenceError("tree pagination loop detected")
        seen_endpoints.add(endpoint)
        response = transport.request("GET", endpoint)
        _require_exact_response(
            response,
            method="GET",
            endpoint=endpoint,
            label=f"tree page for {revision}",
        )
        request_record = _response_record(response)
        request_records.append(request_record)
        payload = _json_body(response, f"tree page for {revision}")
        if not isinstance(payload, list):
            raise PublicParentEvidenceError("tree endpoint did not return a list")
        if not payload:
            raise PublicParentEvidenceError("tree pagination returned an empty page")
        normalized_page: list[dict[str, Any]] = []
        for raw_entry in payload:
            entry = _normalize_tree_entry(raw_entry)
            path = entry["path"]
            if path in entries_by_path:
                raise PublicParentEvidenceError(f"duplicate tree path: {path}")
            entries_by_path[path] = entry
            normalized_page.append(entry)
        following = _next_link(response.headers)
        pages.append(
            {
                "endpoint": endpoint,
                "entry_count": len(normalized_page),
                "paths": [entry["path"] for entry in normalized_page],
                "request_sha256": request_record["request_sha256"],
                "response_sha256": request_record["response_sha256"],
                "entries_sha256": sha256_canonical(normalized_page),
                "has_next": following is not None,
            }
        )
        endpoint = following
    entries = sorted(entries_by_path.values(), key=lambda item: item["path"])
    _validate_tree_closure(entries)
    file_count = sum(entry["kind"] == "file" for entry in entries)
    directory_count = sum(entry["kind"] == "directory" for entry in entries)
    return {
        "revision": revision,
        "page_count": len(pages),
        "pages": pages,
        "path_count": len(entries),
        "file_count": file_count,
        "directory_count": directory_count,
        "entries": entries,
        "entries_sha256": sha256_canonical(entries),
        "pages_sha256": sha256_canonical(pages),
        "pagination_exhausted": True,
    }


def _entry_content_identity(entry: Mapping[str, Any]) -> dict[str, Any]:
    identity = {
        "kind": entry["kind"],
        "oid": entry["oid"],
    }
    if entry["kind"] == "file":
        identity["size"] = entry["size"]
        if "lfs" in entry:
            identity["lfs"] = entry["lfs"]
    return identity


def _compute_delta(
    historical: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    old = {entry["path"]: entry for entry in historical["entries"]}
    new = {entry["path"]: entry for entry in current["entries"]}
    added_paths = sorted(set(new) - set(old))
    deleted_paths = sorted(set(old) - set(new))
    added_entries = [new[path] for path in added_paths]
    modified_blob_paths = sorted(
        path
        for path in set(old) & set(new)
        if old[path]["kind"] == "file"
        and new[path]["kind"] == "file"
        and _entry_content_identity(old[path]) != _entry_content_identity(new[path])
    )
    kind_changed_paths = sorted(
        path for path in set(old) & set(new) if old[path]["kind"] != new[path]["kind"]
    )
    changed_directory_oid_count = sum(
        old[path]["kind"] == "directory"
        and new[path]["kind"] == "directory"
        and old[path]["oid"] != new[path]["oid"]
        for path in set(old) & set(new)
    )
    delta = {
        "added_path_count": len(added_paths),
        "added_file_count": sum(entry["kind"] == "file" for entry in added_entries),
        "added_directory_count": sum(
            entry["kind"] == "directory" for entry in added_entries
        ),
        "added_paths": added_paths,
        "added_paths_sha256": sha256_canonical(added_paths),
        "deleted_path_count": len(deleted_paths),
        "deleted_paths": deleted_paths,
        "deleted_paths_sha256": sha256_canonical(deleted_paths),
        "modified_blob_path_count": len(modified_blob_paths),
        "modified_blob_paths": modified_blob_paths,
        "modified_blob_paths_sha256": sha256_canonical(modified_blob_paths),
        "kind_changed_path_count": len(kind_changed_paths),
        "kind_changed_paths": kind_changed_paths,
        "changed_directory_oid_count": changed_directory_oid_count,
        "preserved_preexisting_blob_count": (
            historical["file_count"]
            - len(modified_blob_paths)
            - sum(old[path]["kind"] == "file" for path in kind_changed_paths)
        ),
    }
    delta["delta_sha256"] = sha256_canonical(delta)
    return delta


def _assert_contract(
    *,
    contract: EvidenceContract,
    historical_commit: Mapping[str, Any],
    current_commit: Mapping[str, Any],
    historical: Mapping[str, Any],
    current: Mapping[str, Any],
    delta: Mapping[str, Any],
) -> None:
    if contract.historical_pin == contract.current_parent_pin:
        raise PublicParentEvidenceError("historical and current pins must be distinct")
    if historical_commit["tree_oid"] != contract.historical_tree_oid:
        raise PublicParentEvidenceError("historical commit tree OID drifted")
    if current_commit["tree_oid"] != contract.current_tree_oid:
        raise PublicParentEvidenceError("current parent commit tree OID drifted")
    if current_commit["parent_oids"] != [contract.historical_pin]:
        raise PublicParentEvidenceError(
            "current public parent is not the direct child of the sealed baseline"
        )
    expected_counts = (
        (historical["file_count"], contract.historical_files, "historical files"),
        (
            historical["directory_count"],
            contract.historical_directories,
            "historical directories",
        ),
        (historical["path_count"], contract.historical_paths, "historical paths"),
        (current["file_count"], contract.current_files, "current files"),
        (
            current["directory_count"],
            contract.current_directories,
            "current directories",
        ),
        (current["path_count"], contract.current_paths, "current paths"),
        (delta["added_file_count"], contract.added_files, "added files"),
        (
            delta["added_directory_count"],
            contract.added_directories,
            "added directories",
        ),
        (delta["added_path_count"], contract.added_paths, "added paths"),
        (delta["deleted_path_count"], 0, "deleted paths"),
        (delta["kind_changed_path_count"], 0, "kind-changed paths"),
    )
    for actual, expected, label in expected_counts:
        if actual != expected:
            raise PublicParentEvidenceError(
                f"{label} drifted: expected {expected}, observed {actual}"
            )
    if delta["modified_blob_paths"] != sorted(contract.modified_blob_paths):
        raise PublicParentEvidenceError("modified root blob set drifted")


def _root_blob_observation(
    transport: EvidenceTransport,
    *,
    contract: EvidenceContract,
    revision: str,
    path: str,
    tree_by_path: Mapping[str, Mapping[str, Any]],
    request_records: list[dict[str, Any]],
) -> dict[str, Any]:
    endpoint = (
        f"{HUB_DATASET_ROOT}/{urllib.parse.quote(contract.repository, safe='/')}"
        f"/resolve/{revision}/{urllib.parse.quote(path, safe='/')}"
    )
    response = transport.request("GET", endpoint)
    _require_exact_response(
        response,
        method="GET",
        endpoint=endpoint,
        label=f"root blob {path} at {revision}",
    )
    request_record = _response_record(response)
    request_records.append(request_record)
    digest = sha256_bytes(response.body)
    expected_digest = contract.root_blob_sha256[revision][path]
    if digest != expected_digest:
        raise PublicParentEvidenceError(
            f"independent SHA-256 mismatch for {path} at {revision}"
        )
    blob_oid = git_object_oid("blob", response.body)
    expected_oid = contract.root_blob_git_oids[revision][path]
    if blob_oid != expected_oid:
        raise PublicParentEvidenceError(
            f"independent Git blob mismatch for {path} at {revision}"
        )
    tree_entry = tree_by_path.get(path)
    if tree_entry is None or tree_entry.get("kind") != "file":
        raise PublicParentEvidenceError(f"root blob is absent from tree: {path}")
    if tree_entry.get("oid") != blob_oid:
        raise PublicParentEvidenceError(
            f"tree API and independently fetched blob disagree for {path}"
        )
    return {
        "revision": revision,
        "path": path,
        "endpoint": endpoint,
        "size": len(response.body),
        "sha256": digest,
        "git_blob_oid": blob_oid,
        "request_sha256": request_record["request_sha256"],
        "response_sha256": request_record["response_sha256"],
    }


def _identity_block(contract: EvidenceContract) -> dict[str, Any]:
    identity = {
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "repository": contract.repository,
        "historical_baseline_pin": contract.historical_pin,
        "current_public_parent_pin": contract.current_parent_pin,
    }
    return {**identity, "identity_sha256": sha256_canonical(identity)}


def _non_acceptance_block() -> dict[str, Any]:
    return {
        "current_corpus_accepted": False,
        "current_corpus_role": "optimistic_parent_and_rollback_only",
        "authorizes_publication": False,
        "authorizes_hub_mutation": False,
        "authorizes_exact_51_candidate": False,
        "blocking_findings": [
            "current Viewer configuration names are invalid or heterogeneous",
            "this receipt proves parent state only, not corrected-corpus validity",
            "a later publication must use independent preflight, CAS, and postflight evidence",
        ],
    }


def collect_evidence(
    transport: EvidenceTransport,
    *,
    verifier_clock: Callable[[], datetime] = _system_utc_now,
    contract: EvidenceContract = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    """Collect an in-memory, non-authorizing parent receipt.

    The clock is called inside the verifier.  Injecting it is intended for
    deterministic tests; the CLI always uses the verifier's system UTC clock.
    """

    observed_at = _format_utc(verifier_clock())
    requests: list[dict[str, Any]] = []

    main_endpoint = (
        f"{HUB_API_ROOT}/datasets/"
        f"{urllib.parse.quote(contract.repository, safe='/')}/revision/main"
    )
    main_response = transport.request("GET", main_endpoint)
    _require_exact_response(
        main_response,
        method="GET",
        endpoint=main_endpoint,
        label="mutable main resolution",
    )
    main_payload = _json_body(main_response, "mutable main resolution")
    requests.append(_response_record(main_response))
    if not isinstance(main_payload, Mapping):
        raise PublicParentEvidenceError("main resolution is not a JSON object")
    if main_payload.get("sha") != contract.current_parent_pin:
        raise PublicParentEvidenceError(
            "mutable main did not resolve to expected parent"
        )

    immutable_endpoint = (
        f"{HUB_API_ROOT}/datasets/"
        f"{urllib.parse.quote(contract.repository, safe='/')}/revision/"
        f"{contract.current_parent_pin}"
    )
    immutable_response = transport.request("GET", immutable_endpoint)
    _require_exact_response(
        immutable_response,
        method="GET",
        endpoint=immutable_endpoint,
        label="immutable current-parent resolution",
    )
    immutable_payload = _json_body(
        immutable_response, "immutable current-parent resolution"
    )
    requests.append(_response_record(immutable_response))
    if (
        not isinstance(immutable_payload, Mapping)
        or immutable_payload.get("sha") != contract.current_parent_pin
    ):
        raise PublicParentEvidenceError("immutable revision did not resolve exactly")

    historical_commit_response = transport.commit_object(
        contract.repository, contract.historical_pin
    )
    _require_exact_response(
        historical_commit_response,
        method="GIT_CAT_FILE",
        endpoint=(
            f"{HUB_DATASET_ROOT}/{contract.repository}.git"
            f"#commit={contract.historical_pin}"
        ),
        label="historical commit object",
    )
    requests.append(_response_record(historical_commit_response))
    historical_commit = _parse_commit_object(
        historical_commit_response.body, contract.historical_pin
    )

    current_commit_response = transport.commit_object(
        contract.repository, contract.current_parent_pin
    )
    _require_exact_response(
        current_commit_response,
        method="GIT_CAT_FILE",
        endpoint=(
            f"{HUB_DATASET_ROOT}/{contract.repository}.git"
            f"#commit={contract.current_parent_pin}"
        ),
        label="current parent commit object",
    )
    requests.append(_response_record(current_commit_response))
    current_commit = _parse_commit_object(
        current_commit_response.body, contract.current_parent_pin
    )

    historical_tree = _inventory_tree(
        transport,
        repository=contract.repository,
        revision=contract.historical_pin,
        request_records=requests,
    )
    current_tree = _inventory_tree(
        transport,
        repository=contract.repository,
        revision=contract.current_parent_pin,
        request_records=requests,
    )
    delta = _compute_delta(historical_tree, current_tree)
    _assert_contract(
        contract=contract,
        historical_commit=historical_commit,
        current_commit=current_commit,
        historical=historical_tree,
        current=current_tree,
        delta=delta,
    )

    tree_maps = {
        contract.historical_pin: {
            entry["path"]: entry for entry in historical_tree["entries"]
        },
        contract.current_parent_pin: {
            entry["path"]: entry for entry in current_tree["entries"]
        },
    }
    root_blobs = [
        _root_blob_observation(
            transport,
            contract=contract,
            revision=revision,
            path=path,
            tree_by_path=tree_maps[revision],
            request_records=requests,
        )
        for revision in (contract.historical_pin, contract.current_parent_pin)
        for path in contract.modified_blob_paths
    ]

    request_set = {
        "count": len(requests),
        "records": requests,
        "records_sha256": sha256_canonical(requests),
    }
    roots = {
        "independently_downloaded": True,
        "count": len(root_blobs),
        "records": root_blobs,
        "records_sha256": sha256_canonical(root_blobs),
    }
    receipt: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "mode": "live" if isinstance(transport, LiveHubTransport) else "scripted",
        "fixture_only": not (
            isinstance(transport, LiveHubTransport)
            and verifier_clock is _system_utc_now
        ),
        "verifier_clock": "system_utc"
        if verifier_clock is _system_utc_now
        else "injected_test_clock",
        "observed_at_utc": observed_at,
        "max_evidence_age_seconds": MAX_EVIDENCE_AGE_SECONDS,
        "identity": _identity_block(contract),
        "pins": {
            "historical_baseline": {
                "revision": contract.historical_pin,
                "role": "sealed_historical_evidence_only",
                "tree_oid": contract.historical_tree_oid,
            },
            "current_public_parent": {
                "revision": contract.current_parent_pin,
                "role": "optimistic_parent_and_rollback_only",
                "tree_oid": contract.current_tree_oid,
            },
            "pins_are_distinct": contract.historical_pin != contract.current_parent_pin,
        },
        "main_resolution": {
            "mutable_revision": "main",
            "resolved_revision": contract.current_parent_pin,
            "endpoint": main_endpoint,
            "request_sha256": requests[0]["request_sha256"],
            "response_sha256": requests[0]["response_sha256"],
            "immutable_endpoint": immutable_endpoint,
            "immutable_request_sha256": requests[1]["request_sha256"],
            "immutable_response_sha256": requests[1]["response_sha256"],
        },
        "commits": {
            "historical_baseline": historical_commit,
            "current_public_parent": current_commit,
            "exact_direct_ancestry": True,
        },
        "inventories": {
            "historical_baseline": historical_tree,
            "current_public_parent": current_tree,
        },
        "delta": delta,
        "root_blobs": roots,
        "requests": request_set,
        "current_corpus_non_acceptance": _non_acceptance_block(),
    }
    receipt[RECEIPT_SELF_DIGEST_FIELD] = sha256_canonical(receipt)
    _validate_against_contract(
        receipt,
        contract=contract,
        now=verifier_clock(),
        require_live=False,
        validate_schema=False,
    )
    return receipt


def _schema_path() -> Path:
    return REPOSITORY_ROOT / SCHEMA_RELPATH


def canonical_receipt_path(repo_root: Path | None = None) -> Path:
    """Return the integration path without creating or modifying it."""

    root = REPOSITORY_ROOT if repo_root is None else Path(repo_root)
    return (root / CANONICAL_RECEIPT_RELPATH).resolve()


def _load_schema() -> Mapping[str, Any]:
    path = _schema_path()
    try:
        payload = _strict_json_loads(path.read_text(encoding="utf-8"), "LCR-084 schema")
    except OSError as exc:
        raise PublicParentEvidenceError("LCR-084 schema is unreadable") from exc
    if not isinstance(payload, Mapping):
        raise PublicParentEvidenceError("LCR-084 schema is not an object")
    return payload


def _validate_json_schema(receipt: Mapping[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise PublicParentEvidenceError(
            "jsonschema is required for canonical evidence validation"
        ) from exc
    validator = jsonschema.Draft202012Validator(_load_schema())
    errors = sorted(validator.iter_errors(receipt), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.path) or "<root>"
        raise PublicParentEvidenceError(
            f"receipt schema violation at {location}: {first.message}"
        )


def _validate_inventory(
    inventory: Mapping[str, Any],
    label: str,
    *,
    repository: str,
    revision: str,
) -> None:
    entries = inventory.get("entries")
    pages = inventory.get("pages")
    if not isinstance(entries, list) or not isinstance(pages, list) or not pages:
        raise PublicParentEvidenceError(f"{label} inventory is incomplete")
    normalized = [_normalize_tree_entry(entry) for entry in entries]
    if normalized != entries:
        raise PublicParentEvidenceError(f"{label} entries are not canonical")
    if entries != sorted(entries, key=lambda item: item["path"]):
        raise PublicParentEvidenceError(f"{label} entries are not sorted")
    if len({entry["path"] for entry in entries}) != len(entries):
        raise PublicParentEvidenceError(f"{label} contains duplicate paths")
    _validate_tree_closure(entries)
    entry_map = {entry["path"]: entry for entry in entries}
    paged_paths: list[str] = []
    seen_endpoints: set[str] = set()
    for page_index, page in enumerate(pages):
        if not isinstance(page, Mapping):
            raise PublicParentEvidenceError(f"{label} page is malformed")
        endpoint = page.get("endpoint")
        if not isinstance(endpoint, str) or endpoint in seen_endpoints:
            raise PublicParentEvidenceError(f"{label} page endpoint is duplicated")
        _require_tree_page_endpoint(endpoint, repository=repository, revision=revision)
        seen_endpoints.add(endpoint)
        paths = page.get("paths")
        if not isinstance(paths, list) or not paths:
            raise PublicParentEvidenceError(f"{label} page paths are missing")
        if len(paths) != len(set(paths)):
            raise PublicParentEvidenceError(f"{label} page repeats a path")
        try:
            page_entries = [entry_map[path] for path in paths]
        except (KeyError, TypeError) as exc:
            raise PublicParentEvidenceError(
                f"{label} page names a path outside the inventory"
            ) from exc
        if page.get("entry_count") != len(paths):
            raise PublicParentEvidenceError(f"{label} page count mismatch")
        if page.get("entries_sha256") != sha256_canonical(page_entries):
            raise PublicParentEvidenceError(f"{label} page entry digest mismatch")
        expected_has_next = page_index < len(pages) - 1
        if page.get("has_next") is not expected_has_next:
            raise PublicParentEvidenceError(f"{label} page chain is inconsistent")
        paged_paths.extend(paths)
    if len(paged_paths) != len(set(paged_paths)) or set(paged_paths) != set(entry_map):
        raise PublicParentEvidenceError(
            f"{label} pages do not exhaust the inventory exactly once"
        )
    if inventory.get("entries_sha256") != sha256_canonical(entries):
        raise PublicParentEvidenceError(f"{label} entries digest mismatch")
    if inventory.get("pages_sha256") != sha256_canonical(pages):
        raise PublicParentEvidenceError(f"{label} pages digest mismatch")
    if inventory.get("pagination_exhausted") is not True:
        raise PublicParentEvidenceError(f"{label} pagination was not exhausted")
    if inventory.get("page_count") != len(pages):
        raise PublicParentEvidenceError(f"{label} page count mismatch")
    if inventory.get("path_count") != len(entries):
        raise PublicParentEvidenceError(f"{label} path count mismatch")
    if inventory.get("file_count") != sum(entry["kind"] == "file" for entry in entries):
        raise PublicParentEvidenceError(f"{label} file count mismatch")
    if inventory.get("directory_count") != sum(
        entry["kind"] == "directory" for entry in entries
    ):
        raise PublicParentEvidenceError(f"{label} directory count mismatch")


def _validate_against_contract(
    receipt: Mapping[str, Any],
    *,
    contract: EvidenceContract,
    now: datetime,
    require_live: bool,
    validate_schema: bool,
) -> None:
    if validate_schema:
        _validate_json_schema(receipt)
    expected_scalars = {
        "schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "max_evidence_age_seconds": MAX_EVIDENCE_AGE_SECONDS,
    }
    for key, expected in expected_scalars.items():
        if receipt.get(key) != expected:
            raise PublicParentEvidenceError(f"receipt {key} mismatch")
    if receipt.get(RECEIPT_SELF_DIGEST_FIELD) != sha256_canonical(
        {
            key: value
            for key, value in receipt.items()
            if key != RECEIPT_SELF_DIGEST_FIELD
        }
    ):
        raise PublicParentEvidenceError("receipt self digest mismatch")
    expected_identity = _identity_block(contract)
    if receipt.get("identity") != expected_identity:
        raise PublicParentEvidenceError("LCR-084 identity binding mismatch")

    observed_at = _parse_utc(receipt.get("observed_at_utc"))
    if now.tzinfo is None or now.utcoffset() is None:
        raise PublicParentEvidenceError("freshness clock is naive")
    age = now.astimezone(UTC) - observed_at
    if age < timedelta(seconds=-MAX_FUTURE_SKEW_SECONDS):
        raise PublicParentEvidenceError("receipt timestamp is in the future")
    if age > timedelta(seconds=MAX_EVIDENCE_AGE_SECONDS):
        raise PublicParentEvidenceError("receipt is stale")
    if require_live and (
        receipt.get("mode") != "live"
        or receipt.get("fixture_only") is not False
        or receipt.get("verifier_clock") != "system_utc"
    ):
        raise PublicParentEvidenceError(
            "canonical receipt is not live verifier evidence"
        )

    pins = receipt.get("pins")
    if not isinstance(pins, Mapping):
        raise PublicParentEvidenceError("pins block is missing")
    expected_pins = {
        "historical_baseline": {
            "revision": contract.historical_pin,
            "role": "sealed_historical_evidence_only",
            "tree_oid": contract.historical_tree_oid,
        },
        "current_public_parent": {
            "revision": contract.current_parent_pin,
            "role": "optimistic_parent_and_rollback_only",
            "tree_oid": contract.current_tree_oid,
        },
        "pins_are_distinct": True,
    }
    if pins != expected_pins:
        raise PublicParentEvidenceError("revision role binding mismatch")

    resolution = receipt.get("main_resolution")
    if (
        not isinstance(resolution, Mapping)
        or resolution.get("mutable_revision") != "main"
        or resolution.get("resolved_revision") != contract.current_parent_pin
    ):
        raise PublicParentEvidenceError("main resolution binding mismatch")

    commits = receipt.get("commits")
    if not isinstance(commits, Mapping):
        raise PublicParentEvidenceError("commit evidence is missing")
    historical_commit = commits.get("historical_baseline")
    current_commit = commits.get("current_public_parent")
    if not isinstance(historical_commit, Mapping) or not isinstance(
        current_commit, Mapping
    ):
        raise PublicParentEvidenceError("commit evidence is malformed")
    if (
        historical_commit.get("commit_oid") != contract.historical_pin
        or historical_commit.get("tree_oid") != contract.historical_tree_oid
        or current_commit.get("commit_oid") != contract.current_parent_pin
        or current_commit.get("tree_oid") != contract.current_tree_oid
        or current_commit.get("parent_oids") != [contract.historical_pin]
        or commits.get("exact_direct_ancestry") is not True
    ):
        raise PublicParentEvidenceError("commit ancestry or tree evidence mismatch")
    for label, commit in (
        ("historical", historical_commit),
        ("current", current_commit),
    ):
        _require_sha256(commit.get("raw_commit_sha256"), f"{label} commit digest")
        if not isinstance(commit.get("raw_commit_bytes"), int):
            raise PublicParentEvidenceError(f"{label} commit size is invalid")

    inventories = receipt.get("inventories")
    if not isinstance(inventories, Mapping):
        raise PublicParentEvidenceError("inventories are missing")
    historical = inventories.get("historical_baseline")
    current = inventories.get("current_public_parent")
    if not isinstance(historical, Mapping) or not isinstance(current, Mapping):
        raise PublicParentEvidenceError("inventories are malformed")
    _validate_inventory(
        historical,
        "historical",
        repository=contract.repository,
        revision=contract.historical_pin,
    )
    _validate_inventory(
        current,
        "current",
        repository=contract.repository,
        revision=contract.current_parent_pin,
    )
    recomputed_delta = _compute_delta(historical, current)
    if receipt.get("delta") != recomputed_delta:
        raise PublicParentEvidenceError("tree delta does not recompute exactly")
    _assert_contract(
        contract=contract,
        historical_commit=historical_commit,
        current_commit=current_commit,
        historical=historical,
        current=current,
        delta=recomputed_delta,
    )

    roots = receipt.get("root_blobs")
    if not isinstance(roots, Mapping) or not isinstance(roots.get("records"), list):
        raise PublicParentEvidenceError("root blob evidence is missing")
    root_records = roots["records"]
    if roots.get("independently_downloaded") is not True:
        raise PublicParentEvidenceError("root blobs were not independently downloaded")
    if roots.get("count") != len(root_records):
        raise PublicParentEvidenceError("root blob count mismatch")
    if roots.get("records_sha256") != sha256_canonical(root_records):
        raise PublicParentEvidenceError("root blob evidence digest mismatch")
    expected_roots = {
        (revision, path): (
            contract.root_blob_sha256[revision][path],
            contract.root_blob_git_oids[revision][path],
        )
        for revision in (contract.historical_pin, contract.current_parent_pin)
        for path in contract.modified_blob_paths
    }
    observed_roots: dict[tuple[str, str], tuple[str, str]] = {}
    for record in root_records:
        if not isinstance(record, Mapping):
            raise PublicParentEvidenceError("root blob record is malformed")
        key = (str(record.get("revision")), str(record.get("path")))
        if key in observed_roots:
            raise PublicParentEvidenceError("duplicate root blob observation")
        observed_roots[key] = (
            str(record.get("sha256")),
            str(record.get("git_blob_oid")),
        )
        if record.get("response_sha256") != record.get("sha256"):
            raise PublicParentEvidenceError("root response hash mismatch")
    if observed_roots != expected_roots:
        raise PublicParentEvidenceError("root blob identities mismatch")

    request_set = receipt.get("requests")
    if not isinstance(request_set, Mapping) or not isinstance(
        request_set.get("records"), list
    ):
        raise PublicParentEvidenceError("request evidence is missing")
    records = request_set["records"]
    if request_set.get("count") != len(records):
        raise PublicParentEvidenceError("request count mismatch")
    if request_set.get("records_sha256") != sha256_canonical(records):
        raise PublicParentEvidenceError("request-set digest mismatch")
    request_index: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            raise PublicParentEvidenceError("request record is malformed")
        request_material = {
            "method": record.get("method"),
            "endpoint": record.get("endpoint"),
            "accept": record.get("accept"),
        }
        if record.get("request_sha256") != sha256_canonical(request_material):
            raise PublicParentEvidenceError("request digest mismatch")
        if record.get("status") != 200:
            raise PublicParentEvidenceError("non-success response in evidence")
        _require_sha256(record.get("response_sha256"), "response digest")
        if (
            isinstance(record.get("response_bytes"), bool)
            or not isinstance(record.get("response_bytes"), int)
            or record["response_bytes"] <= 0
        ):
            raise PublicParentEvidenceError("response byte count is invalid")
        key = (str(record.get("method")), str(record.get("endpoint")))
        if key in request_index:
            raise PublicParentEvidenceError("duplicate request evidence record")
        request_index[key] = record

    referenced_requests: set[tuple[str, str]] = set()

    def bind_request(
        method: str,
        endpoint: Any,
        request_sha256: Any,
        response_sha256: Any,
        label: str,
    ) -> None:
        key = (method, str(endpoint))
        record = request_index.get(key)
        if record is None:
            raise PublicParentEvidenceError(f"{label} request evidence is absent")
        if (
            record.get("request_sha256") != request_sha256
            or record.get("response_sha256") != response_sha256
        ):
            raise PublicParentEvidenceError(f"{label} request/response hash mismatch")
        referenced_requests.add(key)

    bind_request(
        "GET",
        resolution.get("endpoint"),
        resolution.get("request_sha256"),
        resolution.get("response_sha256"),
        "main resolution",
    )
    bind_request(
        "GET",
        resolution.get("immutable_endpoint"),
        resolution.get("immutable_request_sha256"),
        resolution.get("immutable_response_sha256"),
        "immutable resolution",
    )
    for revision, commit, label in (
        (contract.historical_pin, historical_commit, "historical commit"),
        (contract.current_parent_pin, current_commit, "current commit"),
    ):
        endpoint = f"{HUB_DATASET_ROOT}/{contract.repository}.git#commit={revision}"
        record = request_index.get(("GIT_CAT_FILE", endpoint))
        if record is None or record.get("response_sha256") != commit.get(
            "raw_commit_sha256"
        ):
            raise PublicParentEvidenceError(f"{label} response hash mismatch")
        referenced_requests.add(("GIT_CAT_FILE", endpoint))
    for label, inventory in (("historical", historical), ("current", current)):
        for page in inventory["pages"]:
            bind_request(
                "GET",
                page.get("endpoint"),
                page.get("request_sha256"),
                page.get("response_sha256"),
                f"{label} tree page",
            )
    for root in root_records:
        bind_request(
            "GET",
            root.get("endpoint"),
            root.get("request_sha256"),
            root.get("response_sha256"),
            "root blob",
        )
    if referenced_requests != set(request_index):
        raise PublicParentEvidenceError("unreferenced request evidence is present")

    if receipt.get("current_corpus_non_acceptance") != _non_acceptance_block():
        raise PublicParentEvidenceError("current corpus non-acceptance was weakened")


def validate_receipt(
    receipt: Mapping[str, Any],
    *,
    require_live: bool = True,
) -> None:
    """Validate canonical LCR-084 evidence against fixed production constants."""

    _validate_against_contract(
        receipt,
        contract=DEFAULT_CONTRACT,
        now=_system_utc_now(),
        require_live=require_live,
        validate_schema=True,
    )


def load_and_validate_receipt(
    path: Path, *, require_live: bool = True
) -> dict[str, Any]:
    """Read a regular receipt once, parse it strictly, and validate it."""

    try:
        resolved = path.resolve(strict=True)
        if path.is_symlink() or not resolved.is_file():
            raise PublicParentEvidenceError(
                "receipt must be a regular non-symlink file"
            )
        size = resolved.stat().st_size
        if size <= 0 or size > MAX_RECEIPT_BYTES:
            raise PublicParentEvidenceError("receipt size is outside safe bounds")
        raw = resolved.read_bytes()
    except OSError as exc:
        raise PublicParentEvidenceError("could not read receipt") from exc
    if len(raw) != size:
        raise PublicParentEvidenceError("receipt changed while it was read")
    payload = _strict_json_loads(raw, "receipt")
    if not isinstance(payload, dict):
        raise PublicParentEvidenceError("receipt root is not an object")
    validate_receipt(payload, require_live=require_live)
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--observe-live",
        action="store_true",
        help="observe the public Hub read-only and print evidence JSON to stdout",
    )
    mode.add_argument(
        "--check-receipt",
        type=Path,
        metavar="PATH",
        help="validate a saved canonical live receipt without contacting the Hub",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="per-request timeout for read-only live observation",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.check_receipt is not None:
            receipt = load_and_validate_receipt(args.check_receipt)
        else:
            if args.timeout_seconds <= 0:
                raise PublicParentEvidenceError("timeout must be positive")
            with LiveHubTransport(timeout_seconds=args.timeout_seconds) as transport:
                receipt = collect_evidence(transport)
            validate_receipt(receipt)
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    except PublicParentEvidenceError as exc:
        print(f"LCR-084 evidence failed closed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
