"""Pinned, read-only contract for the upstream CVEfixes source snapshot.

The upstream Parquet files and every value read from them are untrusted input.
This module deliberately performs no network access, accepts no credentials,
and does not execute, import, render as a prompt, or otherwise interpret source
text as instructions.  Callers provide observed snapshot metadata for exact
verification and pass individual decoded Parquet rows through
``adapt_cvefixes_row`` before using them.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence


CVEFIXES_DATASET_ID: Final = "hitoshura25/cvefixes"
CVEFIXES_REVISION: Final = "d4f5c4ea65329d9ccbb8a3b3149e5d06eda5edb2"
CVEFIXES_CONFIG_NAME: Final = "default"
CVEFIXES_SPLIT: Final = "train"
CVEFIXES_ROW_COUNT: Final = 12_987

# Column order is part of the reviewed Parquet contract, not merely a set
# membership check.
CVEFIXES_COLUMN_TYPES: Final[tuple[tuple[str, str], ...]] = (
    ("cve_id", "string"),
    ("hash", "string"),
    ("repo_url", "string"),
    ("cve_description", "string"),
    ("cvss2_base_score", "float64"),
    ("cvss3_base_score", "float64"),
    ("published_date", "string"),
    ("severity", "string"),
    ("cwe_id", "string"),
    ("cwe_name", "string"),
    ("cwe_description", "string"),
    ("commit_message", "string"),
    ("commit_date", "string"),
    ("version_tag", "string"),
    ("repo_total_files", "int64"),
    ("repo_total_commits", "int64"),
    ("file_paths", "list<string>"),
    ("language", "string"),
    ("diff_stats", "string"),
    ("diff_with_context", "string"),
    ("vulnerable_code", "string"),
    ("fixed_code", "string"),
    ("security_keywords", "list<string>"),
)
CVEFIXES_COLUMNS: Final[tuple[str, ...]] = tuple(
    name for name, _ in CVEFIXES_COLUMN_TYPES
)

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CVE_ID_RE = re.compile(r"^CVE-[0-9]{4}-[0-9]{4,}$")
_GIT_HASH_RE = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_DESCRIPTION_AST_NODES: Final = (
    ast.Expression,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Constant,
    ast.Load,
)


class SourceSnapshotError(ValueError):
    """Base error for a malformed or unverified CVEfixes source."""


class SourceSnapshotVerificationError(SourceSnapshotError):
    """Raised when observed snapshot evidence differs from the pin."""


class CVEfixesRowError(SourceSnapshotError):
    """Raised when an untrusted source row is malformed or exceeds a bound."""


@dataclass(frozen=True, slots=True)
class SourceShard:
    """Expected identity and shape of one immutable Parquet shard."""

    path: str
    sha256: str
    size_bytes: int
    row_count: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, str)
            or not self.path.startswith("data/")
            or not self.path.endswith(".parquet")
            or "\\" in self.path
            or ".." in Path(self.path).parts
        ):
            raise SourceSnapshotError("shard path must be a safe data/*.parquet path")
        if (
            not isinstance(self.sha256, str)
            or not _SHA256_RE.fullmatch(self.sha256)
        ):
            raise SourceSnapshotError("shard sha256 must be lowercase hexadecimal")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise SourceSnapshotError("shard size_bytes must be a positive integer")
        if type(self.row_count) is not int or self.row_count <= 0:
            raise SourceSnapshotError("shard row_count must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceShard":
        _require_exact_keys(
            value,
            {"path", "row_count", "sha256", "size_bytes"},
            "source shard",
            SourceSnapshotVerificationError,
        )
        return cls(
            path=value["path"],
            sha256=value["sha256"],
            size_bytes=value["size_bytes"],
            row_count=value["row_count"],
        )


CVEFIXES_SHARDS: Final[tuple[SourceShard, ...]] = (
    SourceShard(
        path="data/train-00000-of-00003.parquet",
        sha256="2e25e84e85e1560d41acacbfc7eb359349f5417bc9bf31318cdf0c4aafccb7d1",
        size_bytes=211_599_861,
        row_count=4_329,
    ),
    SourceShard(
        path="data/train-00001-of-00003.parquet",
        sha256="3a4251f39955f95c232b4aea98daa59bbe0c7b5e27c9189c1b09f64b960a35d7",
        size_bytes=428_366_432,
        row_count=4_329,
    ),
    SourceShard(
        path="data/train-00002-of-00003.parquet",
        sha256="55488d569ac978ea077be643233355f43458d636d04ad3ae1cb973895b02a3ac",
        size_bytes=580_353_186,
        row_count=4_329,
    ),
)


@dataclass(frozen=True, slots=True)
class SourceSnapshotObservation:
    """Untrusted metadata observed by a separate downloader or Hub client."""

    dataset_id: str
    revision: str
    config_name: str
    split: str
    row_count: int
    columns: tuple[tuple[str, str], ...]
    shards: tuple[SourceShard, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceSnapshotObservation":
        _require_exact_keys(
            value,
            {
                "dataset_id",
                "revision",
                "config_name",
                "split",
                "row_count",
                "columns",
                "shards",
            },
            "source observation",
            SourceSnapshotVerificationError,
        )
        raw_columns = value["columns"]
        if not isinstance(raw_columns, Mapping):
            raise SourceSnapshotVerificationError(
                "source observation columns must be an ordered mapping"
            )
        columns: list[tuple[str, str]] = []
        for name, column_type in raw_columns.items():
            if not isinstance(name, str) or not isinstance(column_type, str):
                raise SourceSnapshotVerificationError(
                    "source observation column names and types must be strings"
                )
            columns.append((name, column_type))
        raw_shards = value["shards"]
        if (
            isinstance(raw_shards, (str, bytes, bytearray))
            or not isinstance(raw_shards, Sequence)
        ):
            raise SourceSnapshotVerificationError(
                "source observation shards must be a sequence"
            )
        return cls(
            dataset_id=value["dataset_id"],
            revision=value["revision"],
            config_name=value["config_name"],
            split=value["split"],
            row_count=value["row_count"],
            columns=tuple(columns),
            shards=tuple(
                SourceShard.from_dict(_require_mapping(item, "source shard"))
                for item in raw_shards
            ),
        )

    def __post_init__(self) -> None:
        for label, value in (
            ("dataset_id", self.dataset_id),
            ("revision", self.revision),
            ("config_name", self.config_name),
            ("split", self.split),
        ):
            if not isinstance(value, str) or not value:
                raise SourceSnapshotVerificationError(f"{label} must not be empty")
        if not _SHA1_RE.fullmatch(self.revision):
            raise SourceSnapshotVerificationError(
                "revision must be an immutable lowercase commit hash"
            )
        if type(self.row_count) is not int or self.row_count < 0:
            raise SourceSnapshotVerificationError(
                "row_count must be a non-negative integer"
            )


@dataclass(frozen=True, slots=True)
class SourceSnapshotVerification:
    """Receipt proving equality with this module's reviewed offline pin."""

    profile_sha256: str
    shard_count: int
    row_count: int
    verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_sha256": self.profile_sha256,
            "row_count": self.row_count,
            "shard_count": self.shard_count,
            "verified": self.verified,
        }


@dataclass(frozen=True, slots=True)
class CVEfixesSourceProfile:
    """Immutable source profile; it contains no mutable refs or secrets."""

    dataset_id: str = CVEFIXES_DATASET_ID
    revision: str = CVEFIXES_REVISION
    config_name: str = CVEFIXES_CONFIG_NAME
    split: str = CVEFIXES_SPLIT
    row_count: int = CVEFIXES_ROW_COUNT
    columns: tuple[tuple[str, str], ...] = CVEFIXES_COLUMN_TYPES
    shards: tuple[SourceShard, ...] = CVEFIXES_SHARDS

    def __post_init__(self) -> None:
        if self.dataset_id != CVEFIXES_DATASET_ID:
            raise SourceSnapshotError("CVEfixes dataset_id differs from reviewed pin")
        if self.revision != CVEFIXES_REVISION:
            raise SourceSnapshotError("CVEfixes revision differs from reviewed pin")
        if not _SHA1_RE.fullmatch(self.revision):
            raise SourceSnapshotError("CVEfixes revision is not an immutable commit")
        if self.config_name != CVEFIXES_CONFIG_NAME or self.split != CVEFIXES_SPLIT:
            raise SourceSnapshotError("CVEfixes config or split differs from reviewed pin")
        if self.row_count != CVEFIXES_ROW_COUNT:
            raise SourceSnapshotError("CVEfixes row count differs from reviewed pin")
        if self.columns != CVEFIXES_COLUMN_TYPES:
            raise SourceSnapshotError("CVEfixes column contract differs from reviewed pin")
        if self.shards != CVEFIXES_SHARDS:
            raise SourceSnapshotError("CVEfixes shard contract differs from reviewed pin")
        if sum(shard.row_count for shard in self.shards) != self.row_count:
            raise SourceSnapshotError("CVEfixes shard row counts do not sum to row_count")
        if len({shard.path for shard in self.shards}) != len(self.shards):
            raise SourceSnapshotError("CVEfixes shard paths must be unique")

    def to_dict(self) -> dict[str, Any]:
        """Return public pin material only; credentials are never consulted."""

        return {
            "columns": {name: column_type for name, column_type in self.columns},
            "config_name": self.config_name,
            "dataset_id": self.dataset_id,
            "revision": self.revision,
            "row_count": self.row_count,
            "shards": [shard.to_dict() for shard in self.shards],
            "split": self.split,
        }

    @property
    def sha256(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def verify(
        self,
        observation: SourceSnapshotObservation | Mapping[str, Any],
    ) -> SourceSnapshotVerification:
        """Fail closed unless all observed pin, schema, and shard facts match."""

        if isinstance(observation, Mapping):
            observation = SourceSnapshotObservation.from_dict(observation)
        if not isinstance(observation, SourceSnapshotObservation):
            raise SourceSnapshotVerificationError(
                "observation must be SourceSnapshotObservation or a mapping"
            )
        mismatches: list[str] = []
        for field in ("dataset_id", "revision", "config_name", "split", "row_count"):
            if getattr(observation, field) != getattr(self, field):
                mismatches.append(field)
        if observation.columns != self.columns:
            mismatches.append("columns")
        if observation.shards != self.shards:
            mismatches.append("shards")
        if sum(shard.row_count for shard in observation.shards) != observation.row_count:
            mismatches.append("shard row count total")
        if mismatches:
            raise SourceSnapshotVerificationError(
                "source snapshot verification failed: " + ", ".join(mismatches)
            )
        return SourceSnapshotVerification(
            profile_sha256=self.sha256,
            shard_count=len(self.shards),
            row_count=self.row_count,
        )

    def verify_local_shards(self, root: str | Path) -> SourceSnapshotVerification:
        """Verify the byte size and SHA-256 of all pinned local shard files."""

        root_path = Path(root).expanduser().resolve()
        if not root_path.is_dir():
            raise SourceSnapshotVerificationError(
                f"source shard root is not a directory: {root_path}"
            )
        for shard in self.shards:
            verify_shard_file(root_path / shard.path, shard)
        return SourceSnapshotVerification(
            profile_sha256=self.sha256,
            shard_count=len(self.shards),
            row_count=self.row_count,
        )


PINNED_CVEFIXES_SOURCE: Final = CVEfixesSourceProfile()


def verify_source_snapshot(
    observation: SourceSnapshotObservation | Mapping[str, Any],
) -> SourceSnapshotVerification:
    """Verify metadata against :data:`PINNED_CVEFIXES_SOURCE`."""

    return PINNED_CVEFIXES_SOURCE.verify(observation)


def verify_shard_file(path: str | Path, shard: SourceShard) -> None:
    """Verify one local file against an explicit immutable shard descriptor."""

    file_path = Path(path)
    if file_path.is_symlink() or not file_path.is_file():
        raise SourceSnapshotVerificationError(
            f"source shard is missing, not regular, or a symlink: {file_path}"
        )
    size_bytes = file_path.stat().st_size
    if size_bytes != shard.size_bytes:
        raise SourceSnapshotVerificationError(
            f"{shard.path}: size mismatch ({size_bytes} != {shard.size_bytes})"
        )
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != shard.sha256:
        raise SourceSnapshotVerificationError(f"{shard.path}: sha256 mismatch")


@dataclass(frozen=True, slots=True)
class CVEfixesRowBounds:
    """Explicit resource limits applied before parsing untrusted row content."""

    max_description_chars: int = 65_536
    max_metadata_chars: int = 1_048_576
    max_body_chars: int = 67_108_864
    max_total_text_chars: int = 201_326_592
    max_description_entries: int = 32
    max_description_ast_nodes: int = 512
    max_file_paths: int = 16_384
    max_path_chars: int = 4_096
    max_security_keywords: int = 128
    max_keyword_chars: int = 1_024

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_ROW_BOUNDS: Final = CVEfixesRowBounds()


@dataclass(frozen=True, slots=True)
class CVEfixesDescription:
    """One inert localized CVE description."""

    language: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"lang": self.language, "value": self.value}


@dataclass(frozen=True, slots=True)
class CVEfixesSourceRow:
    """Validated, immutable representation of one pinned source row."""

    row_index: int
    cve_id: str
    hash: str
    repo_url: str
    cve_description: tuple[CVEfixesDescription, ...]
    cvss2_base_score: float | None
    cvss3_base_score: float | None
    published_date: str | None
    severity: str | None
    cwe_id: str | None
    cwe_name: str | None
    cwe_description: str | None
    commit_message: str | None
    commit_date: str | None
    version_tag: str | None
    repo_total_files: int | None
    repo_total_commits: int | None
    file_paths: tuple[str, ...]
    language: str | None
    diff_stats: str | None
    diff_with_context: str | None
    vulnerable_code: str | None
    fixed_code: str | None
    security_keywords: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return inert normalized values, never authentication material."""

        return {
            "commit_date": self.commit_date,
            "commit_message": self.commit_message,
            "cve_description": [
                description.to_dict() for description in self.cve_description
            ],
            "cve_id": self.cve_id,
            "cvss2_base_score": self.cvss2_base_score,
            "cvss3_base_score": self.cvss3_base_score,
            "cwe_description": self.cwe_description,
            "cwe_id": self.cwe_id,
            "cwe_name": self.cwe_name,
            "diff_stats": self.diff_stats,
            "diff_with_context": self.diff_with_context,
            "file_paths": list(self.file_paths),
            "fixed_code": self.fixed_code,
            "hash": self.hash,
            "language": self.language,
            "published_date": self.published_date,
            "repo_total_commits": self.repo_total_commits,
            "repo_total_files": self.repo_total_files,
            "repo_url": self.repo_url,
            "row_index": self.row_index,
            "security_keywords": list(self.security_keywords),
            "severity": self.severity,
            "version_tag": self.version_tag,
            "vulnerable_code": self.vulnerable_code,
        }


class CVEfixesRowAdapter:
    """Strict adapter from an untrusted 23-column mapping to inert values."""

    def __init__(self, bounds: CVEfixesRowBounds = DEFAULT_ROW_BOUNDS) -> None:
        if not isinstance(bounds, CVEfixesRowBounds):
            raise TypeError("bounds must be CVEfixesRowBounds")
        self._bounds = bounds

    @property
    def bounds(self) -> CVEfixesRowBounds:
        return self._bounds

    def adapt(self, row: Mapping[str, Any], *, row_index: int) -> CVEfixesSourceRow:
        if not isinstance(row, Mapping):
            raise CVEfixesRowError("source row must be a mapping")
        _require_exact_keys(row, set(CVEFIXES_COLUMNS), "source row", CVEfixesRowError)
        if (
            type(row_index) is not int
            or row_index < 0
            or row_index >= CVEFIXES_ROW_COUNT
        ):
            raise CVEfixesRowError(
                f"row_index must be between 0 and {CVEFIXES_ROW_COUNT - 1}"
            )

        cve_id = _required_text(row["cve_id"], "cve_id", 64)
        if not _CVE_ID_RE.fullmatch(cve_id):
            raise CVEfixesRowError("cve_id is malformed")
        commit_hash = _required_text(row["hash"], "hash", 40)
        if not _GIT_HASH_RE.fullmatch(commit_hash):
            raise CVEfixesRowError("hash must be a 40-character lowercase git hash")
        repo_url = _required_text(row["repo_url"], "repo_url", 4_096)
        if not (
            repo_url.startswith("https://github.com/")
            or repo_url.startswith("http://github.com/")
        ):
            raise CVEfixesRowError("repo_url must identify a GitHub repository")

        metadata_fields = {
            name: _optional_text(
                row[name], name, self._bounds.max_metadata_chars
            )
            for name in (
                "published_date",
                "severity",
                "cwe_id",
                "cwe_name",
                "cwe_description",
                "commit_message",
                "commit_date",
                "version_tag",
                "language",
                "diff_stats",
            )
        }
        body_fields = {
            name: _optional_text(row[name], name, self._bounds.max_body_chars)
            for name in ("diff_with_context", "vulnerable_code", "fixed_code")
        }
        file_paths = _bounded_string_sequence(
            row["file_paths"],
            "file_paths",
            max_items=self._bounds.max_file_paths,
            max_item_chars=self._bounds.max_path_chars,
        )
        security_keywords = _bounded_string_sequence(
            row["security_keywords"],
            "security_keywords",
            max_items=self._bounds.max_security_keywords,
            max_item_chars=self._bounds.max_keyword_chars,
        )
        descriptions = _parse_descriptions(
            row["cve_description"], bounds=self._bounds
        )
        text_size = (
            len(cve_id)
            + len(commit_hash)
            + len(repo_url)
            + sum(len(value or "") for value in metadata_fields.values())
            + sum(len(value or "") for value in body_fields.values())
            + sum(len(value) for value in file_paths)
            + sum(len(value) for value in security_keywords)
            + sum(
                len(value.language) + len(value.value) for value in descriptions
            )
        )
        if text_size > self._bounds.max_total_text_chars:
            raise CVEfixesRowError("source row exceeds max_total_text_chars")

        return CVEfixesSourceRow(
            row_index=row_index,
            cve_id=cve_id,
            hash=commit_hash,
            repo_url=repo_url,
            cve_description=descriptions,
            cvss2_base_score=_optional_score(
                row["cvss2_base_score"], "cvss2_base_score"
            ),
            cvss3_base_score=_optional_score(
                row["cvss3_base_score"], "cvss3_base_score"
            ),
            repo_total_files=_optional_nonnegative_int(
                row["repo_total_files"], "repo_total_files"
            ),
            repo_total_commits=_optional_nonnegative_int(
                row["repo_total_commits"], "repo_total_commits"
            ),
            file_paths=file_paths,
            security_keywords=security_keywords,
            **metadata_fields,
            **body_fields,
        )


DEFAULT_ROW_ADAPTER: Final = CVEfixesRowAdapter()


def adapt_cvefixes_row(
    row: Mapping[str, Any],
    *,
    row_index: int,
    bounds: CVEfixesRowBounds = DEFAULT_ROW_BOUNDS,
) -> CVEfixesSourceRow:
    """Adapt one row without executing or mutating any source value."""

    return CVEfixesRowAdapter(bounds).adapt(row, row_index=row_index)


def _parse_descriptions(
    value: Any,
    *,
    bounds: CVEfixesRowBounds,
) -> tuple[CVEfixesDescription, ...]:
    if value is None or value == "":
        return ()
    if not isinstance(value, str):
        raise CVEfixesRowError("cve_description must be serialized text or null")
    if len(value) > bounds.max_description_chars:
        raise CVEfixesRowError("cve_description exceeds max_description_chars")
    try:
        parsed: Any = json.loads(value)
    except (json.JSONDecodeError, MemoryError, RecursionError):
        try:
            tree = ast.parse(value, mode="eval")
        except (SyntaxError, ValueError, MemoryError) as exc:
            raise CVEfixesRowError("cve_description is malformed") from exc
        nodes = list(ast.walk(tree))
        if len(nodes) > bounds.max_description_ast_nodes or any(
            not isinstance(node, _ALLOWED_DESCRIPTION_AST_NODES) for node in nodes
        ):
            raise CVEfixesRowError(
                "cve_description contains unsupported literal syntax"
            )
        try:
            parsed = ast.literal_eval(tree)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError) as exc:
            raise CVEfixesRowError("cve_description is malformed") from exc
    if not isinstance(parsed, (list, tuple)):
        raise CVEfixesRowError("cve_description must decode to a list")
    if len(parsed) > bounds.max_description_entries:
        raise CVEfixesRowError("cve_description has too many entries")
    descriptions: list[CVEfixesDescription] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, Mapping) or set(item) != {"lang", "value"}:
            raise CVEfixesRowError(
                f"cve_description[{index}] must contain exactly lang and value"
            )
        language = _required_text(item["lang"], f"cve_description[{index}].lang", 32)
        text = _required_text(
            item["value"],
            f"cve_description[{index}].value",
            bounds.max_description_chars,
        )
        descriptions.append(CVEfixesDescription(language=language, value=text))
    return tuple(descriptions)


def _required_text(value: Any, label: str, max_chars: int) -> str:
    if not isinstance(value, str) or not value:
        raise CVEfixesRowError(f"{label} must be non-empty text")
    if "\x00" in value:
        raise CVEfixesRowError(f"{label} must not contain NUL")
    if len(value) > max_chars:
        raise CVEfixesRowError(f"{label} exceeds its character bound")
    return value


def _optional_text(value: Any, label: str, max_chars: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CVEfixesRowError(f"{label} must be text or null")
    if "\x00" in value:
        raise CVEfixesRowError(f"{label} must not contain NUL")
    if len(value) > max_chars:
        raise CVEfixesRowError(f"{label} exceeds its character bound")
    return value


def _bounded_string_sequence(
    value: Any,
    label: str,
    *,
    max_items: int,
    max_item_chars: int,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise CVEfixesRowError(f"{label} must be a list of strings or null")
    if len(value) > max_items:
        raise CVEfixesRowError(f"{label} has too many entries")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_required_text(item, f"{label}[{index}]", max_item_chars))
    return tuple(result)


def _optional_score(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CVEfixesRowError(f"{label} must be numeric or null")
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 10.0:
        raise CVEfixesRowError(f"{label} must be finite and between 0 and 10")
    return score


def _optional_nonnegative_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise CVEfixesRowError(f"{label} must be a non-negative integer or null")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
    error_type: type[ValueError],
) -> None:
    if not isinstance(value, Mapping):
        raise error_type(f"{label} must be a mapping")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual, key=str)
        unexpected = sorted(actual - expected, key=str)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(str(item) for item in missing))
        if unexpected:
            details.append(
                "unexpected=" + ",".join(str(item) for item in unexpected)
            )
        raise error_type(f"{label} schema drift: {'; '.join(details)}")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceSnapshotVerificationError(f"{label} must be a mapping")
    return value


# A read-only view is useful to consumers that need name-based type lookup
# without exposing mutable shared state.
CVEFIXES_COLUMN_TYPE_MAP: Final[Mapping[str, str]] = MappingProxyType(
    dict(CVEFIXES_COLUMN_TYPES)
)


__all__ = [
    "CVEFIXES_COLUMNS",
    "CVEFIXES_COLUMN_TYPES",
    "CVEFIXES_COLUMN_TYPE_MAP",
    "CVEFIXES_CONFIG_NAME",
    "CVEFIXES_DATASET_ID",
    "CVEFIXES_REVISION",
    "CVEFIXES_ROW_COUNT",
    "CVEFIXES_SHARDS",
    "CVEFIXES_SPLIT",
    "CVEfixesDescription",
    "CVEfixesRowAdapter",
    "CVEfixesRowBounds",
    "CVEfixesRowError",
    "CVEfixesSourceProfile",
    "CVEfixesSourceRow",
    "DEFAULT_ROW_ADAPTER",
    "DEFAULT_ROW_BOUNDS",
    "PINNED_CVEFIXES_SOURCE",
    "SourceShard",
    "SourceSnapshotError",
    "SourceSnapshotObservation",
    "SourceSnapshotVerification",
    "SourceSnapshotVerificationError",
    "adapt_cvefixes_row",
    "verify_shard_file",
    "verify_source_snapshot",
]
