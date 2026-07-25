"""Safe, deterministic reader for SkillCenter SQLite bundles.

Bundles are untrusted external artifacts.  This adapter opens them read-only
and immutable, disables extension loading, validates the expected tables and
columns, applies record-size bounds, and yields data records.  It never treats
``skill_md`` content as instructions and never executes commands found in it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import quote

from multiformats import CID

from ...ir_core.identity import identity_preimage
from ...profile_g import validate_cid
from ..schema import ReviewStatus, SourceRef
from ....utils.cid_utils import cid_for_bytes


DEFAULT_SKILLCENTER_DATASET_ID = "Tommysha/skillcenter-bundles"
SKILLCENTER_BUNDLE_SCHEMA_VERSION = "skillcenter-sqlite-bundle/v1"
SKILLCENTER_ENTRY_IDENTITY_SCHEMA_VERSION = "skillcenter-entry-identity/v1"
SKILLCENTER_ENTRY_IDENTITY_DOMAIN = "intent-ir.skillcenter-entry"
DEFAULT_MAX_TEXT_CHARS = 1_000_000
DEFAULT_BATCH_SIZE = 256
MAX_BATCH_SIZE = 1_000
_SQLITE_HEADER = b"SQLite format 3\x00"
_MUTABLE_REVISION_NAMES = {
    "head",
    "latest",
    "main",
    "master",
    "refs/heads/main",
    "refs/heads/master",
}
_METADATA_SCALAR_RE = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):[ \t]*(?P<value>.*)$",
    re.MULTILINE,
)

_REQUIRED_COLUMNS = {
    "bundle_meta": {"key", "value"},
    "skills_index": {
        "skill_id",
        "domain",
        "profile",
        "source_type",
        "source_url",
        "title",
        "overall_score",
        "skill_kind",
        "language",
        "source_id",
        "primary_source_id",
    },
    "skills_content": {"skill_id", "metadata_yaml", "skill_md", "library_md"},
}


class SkillCenterBundleSchemaError(ValueError):
    """Raised when a bundle is missing or violates the expected SQLite shape."""


class SkillCenterRecordError(ValueError):
    """Raised when a SkillCenter row is malformed or exceeds safety bounds."""


@dataclass(frozen=True, slots=True)
class SkillCenterEntryIdentity:
    """Multiformats identity for one container-independent skill entry."""

    cid: str
    cid_bytes: bytes
    multihash_bytes: bytes
    sha256: str
    identity_schema_version: str = SKILLCENTER_ENTRY_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        try:
            decoded = CID.decode(self.cid)
        except (TypeError, ValueError) as exc:
            raise SkillCenterRecordError("entry identity CID is malformed") from exc
        if (
            decoded.version != 1
            or decoded.codec.name != "raw"
            or decoded.hashfun.name != "sha2-256"
            or bytes(decoded) != self.cid_bytes
            or bytes(decoded.digest) != self.multihash_bytes
            or decoded.raw_digest.hex() != self.sha256
        ):
            raise SkillCenterRecordError(
                "entry identity does not use CIDv1/raw/sha2-256 consistently"
            )
        if self.identity_schema_version != SKILLCENTER_ENTRY_IDENTITY_SCHEMA_VERSION:
            raise SkillCenterRecordError(
                "entry identity schema version is unsupported"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "cid": self.cid,
            "identity_schema_version": self.identity_schema_version,
            "multicodec": "raw",
            "multihash": "sha2-256",
            "multibase": "base32",
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class SkillCenterBundleManifest:
    """Immutable identity and declared metadata for one local bundle."""

    dataset_id: str
    dataset_revision: str
    repository_file: str
    local_sha256: str
    size_bytes: int
    bundle_type: str
    bundle_version: str
    created_at: str
    total_skills: int
    schema_version: str = SKILLCENTER_BUNDLE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_type": self.bundle_type,
            "bundle_version": self.bundle_version,
            "created_at": self.created_at,
            "dataset_id": self.dataset_id,
            "dataset_revision": self.dataset_revision,
            "local_sha256": self.local_sha256,
            "repository_file": self.repository_file,
            "schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "total_skills": self.total_skills,
        }


@dataclass(frozen=True, slots=True)
class SkillCenterSkillRecord:
    """One bounded row joined from ``skills_index`` and ``skills_content``."""

    skill_id: str
    domain: str
    profile: str
    source_type: str
    source_url: str
    title: str
    overall_score: float | None
    skill_kind: str
    language: str
    source_id: str
    primary_source_id: str
    metadata_yaml: str
    skill_md: str
    library_md: str
    dataset_id: str
    dataset_revision: str
    repository_file: str
    bundle_sha256: str

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.skill_md.encode("utf-8")).hexdigest()

    def intrinsic_payload(self) -> dict[str, Any]:
        """Return the canonical entry payload without container provenance.

        Dataset revisions and bundle filenames deliberately stay outside this
        payload. Repackaging an unchanged skill therefore preserves its
        primary key, while any intrinsic metadata or body change produces a
        new CID.
        """

        return {
            "domain": self.domain,
            "language": self.language,
            "library_md": self.library_md,
            "metadata_yaml": self.metadata_yaml,
            "overall_score": self.overall_score,
            "primary_source_id": self.primary_source_id,
            "profile": self.profile,
            "skill_id": self.skill_id,
            "skill_kind": self.skill_kind,
            "skill_md": self.skill_md,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "title": self.title,
        }

    @property
    def entry_identity(self) -> SkillCenterEntryIdentity:
        """Return the canonical CIDv1 primary-key identity for this entry."""

        preimage = identity_preimage(
            self.intrinsic_payload(),
            domain=SKILLCENTER_ENTRY_IDENTITY_DOMAIN,
            schema_version=SKILLCENTER_ENTRY_IDENTITY_SCHEMA_VERSION,
        )
        cid_text = validate_cid(
            cid_for_bytes(
                preimage,
                base="base32",
                codec="raw",
                mh_type="sha2-256",
                version=1,
            ),
            path="/entry_cid",
        )
        cid = CID.decode(cid_text)
        return SkillCenterEntryIdentity(
            cid=str(cid),
            cid_bytes=bytes(cid),
            multihash_bytes=bytes(cid.digest),
            sha256=cid.raw_digest.hex(),
        )

    @property
    def entry_cid(self) -> str:
        """Return the canonical CID used as the corpus-wide primary key."""

        return self.entry_identity.cid

    @property
    def content_cid(self) -> str:
        """Return a raw CIDv1 for the exact UTF-8 ``skill_md`` bytes."""

        return validate_cid(
            cid_for_bytes(
                self.skill_md.encode("utf-8"),
                base="base32",
                codec="raw",
                mh_type="sha2-256",
                version=1,
            ),
            path="/content_cid",
        )

    @property
    def license_expression(self) -> str:
        return (
            _metadata_scalar(self.metadata_yaml, "license_spdx")
            or _metadata_scalar(self.metadata_yaml, "license")
        )

    @property
    def license_risk(self) -> str:
        return _metadata_scalar(self.metadata_yaml, "license_risk")

    def to_source_ref(
        self,
        *,
        review_status: ReviewStatus = ReviewStatus.UNREVIEWED,
        content_cid: str = "",
    ) -> SourceRef:
        """Return the provenance reference used by normalized Intent IR."""

        encoded_file = quote(self.repository_file, safe="/")
        encoded_skill_id = quote(self.skill_id, safe="")
        container_uri = (
            f"hf://datasets/{self.dataset_id}@{self.dataset_revision}/"
            f"{encoded_file}#{encoded_skill_id}"
        )
        reference_material = (
            f"{self.dataset_id}@{self.dataset_revision}/"
            f"{self.repository_file}#{self.skill_id}:{self.content_sha256}"
        )
        reference_digest = hashlib.sha256(
            reference_material.encode("utf-8")
        ).hexdigest()
        return SourceRef(
            ref_id=f"skillcenter:{reference_digest}",
            source_uri=self.source_url or container_uri,
            source_id=self.primary_source_id or self.source_id or self.skill_id,
            source_revision=self.dataset_revision,
            content_sha256=self.content_sha256,
            container_uri=container_uri,
            container_sha256=self.bundle_sha256,
            content_cid=content_cid or self.content_cid,
            license_expression=self.license_expression,
            review_status=review_status,
        )


class SkillCenterBundleReader:
    """Bounded read-only iterator over one pinned SkillCenter bundle."""

    def __init__(
        self,
        path: str | Path,
        *,
        dataset_revision: str,
        repository_file: str | None = None,
        dataset_id: str = DEFAULT_SKILLCENTER_DATASET_ID,
        max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
        allow_declared_count_mismatch: bool = False,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.dataset_revision = str(dataset_revision or "").strip()
        self.repository_file = str(repository_file or self.path.name).strip()
        self.dataset_id = str(dataset_id or "").strip()
        self.max_text_chars = int(max_text_chars)
        self.allow_declared_count_mismatch = bool(
            allow_declared_count_mismatch
        )
        self.declared_total_skills: int | None = None
        self._manifest: SkillCenterBundleManifest | None = None
        if not self.dataset_revision:
            raise ValueError("dataset_revision is required; mutable 'main' is unsafe")
        if self.dataset_revision.lower() in _MUTABLE_REVISION_NAMES:
            raise ValueError(
                "dataset_revision must be an immutable commit, not a mutable ref"
            )
        if not self.dataset_id or not self.repository_file:
            raise ValueError("dataset_id and repository_file are required")
        if self.max_text_chars < 1:
            raise ValueError("max_text_chars must be positive")

    def inspect(self) -> SkillCenterBundleManifest:
        """Validate the bundle and return its pinned deterministic manifest."""

        if self._manifest is not None:
            return self._manifest
        self._validate_file_header()
        with closing(self._connect()) as connection:
            self._validate_schema(connection)
            metadata = {
                str(row["key"]): str(row["value"] or "")
                for row in connection.execute(
                    "SELECT key, value FROM bundle_meta ORDER BY key"
                )
            }
            total_skills = _positive_or_zero_int(
                metadata.get("total_skills"), "bundle_meta.total_skills"
            )
            index_rows = int(
                connection.execute("SELECT COUNT(*) FROM skills_index").fetchone()[0]
            )
            content_rows = int(
                connection.execute("SELECT COUNT(*) FROM skills_content").fetchone()[0]
            )
            joined_rows = int(
                connection.execute(
                    "SELECT COUNT(*) FROM skills_index AS i "
                    "INNER JOIN skills_content AS c ON c.skill_id = i.skill_id"
                ).fetchone()[0]
            )
            self.declared_total_skills = total_skills
            if len({index_rows, content_rows, joined_rows}) != 1:
                raise SkillCenterBundleSchemaError(
                    "SkillCenter row counts disagree: "
                    f"declared={total_skills}, index={index_rows}, "
                    f"content={content_rows}, joined={joined_rows}"
                )
            if (
                total_skills != index_rows
                and not self.allow_declared_count_mismatch
            ):
                raise SkillCenterBundleSchemaError(
                    "SkillCenter row counts disagree: "
                    f"declared={total_skills}, index={index_rows}, "
                    f"content={content_rows}, joined={joined_rows}"
                )
        self._manifest = SkillCenterBundleManifest(
            dataset_id=self.dataset_id,
            dataset_revision=self.dataset_revision,
            repository_file=self.repository_file,
            local_sha256=_file_sha256(self.path),
            size_bytes=self.path.stat().st_size,
            bundle_type=metadata.get("bundle_type", ""),
            bundle_version=metadata.get("version", ""),
            created_at=metadata.get("created_at", ""),
            total_skills=index_rows,
        )
        return self._manifest

    def iter_records(
        self,
        *,
        limit: int | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        start_after: str = "",
        domain: str | None = None,
        minimum_score: float | None = None,
    ) -> Iterator[SkillCenterSkillRecord]:
        """Yield deterministic rows in ``skill_id`` order using keyset paging."""

        if limit is not None and (isinstance(limit, bool) or int(limit) < 0):
            raise ValueError("limit must be a non-negative integer or None")
        batch_size = int(batch_size)
        if not 1 <= batch_size <= MAX_BATCH_SIZE:
            raise ValueError(
                f"batch_size must be between 1 and {MAX_BATCH_SIZE}"
            )
        manifest = self.inspect()
        remaining = None if limit is None else int(limit)
        last_skill_id = str(start_after or "")
        with closing(self._connect()) as connection:
            while remaining is None or remaining > 0:
                fetch_size = (
                    batch_size if remaining is None else min(batch_size, remaining)
                )
                where = ["i.skill_id > ?"]
                parameters: list[Any] = [last_skill_id]
                if domain is not None:
                    where.append("i.domain = ?")
                    parameters.append(str(domain))
                if minimum_score is not None:
                    if not math.isfinite(float(minimum_score)):
                        raise ValueError("minimum_score must be finite")
                    where.append("i.overall_score >= ?")
                    parameters.append(float(minimum_score))
                parameters.append(fetch_size)
                rows = connection.execute(
                    """
                    SELECT
                        i.skill_id, i.domain, i.profile, i.source_type,
                        i.source_url, i.title, i.overall_score, i.skill_kind,
                        i.language, i.source_id, i.primary_source_id,
                        c.metadata_yaml, c.skill_md, c.library_md
                    FROM skills_index AS i
                    INNER JOIN skills_content AS c ON c.skill_id = i.skill_id
                    WHERE """
                    + " AND ".join(where)
                    + " ORDER BY i.skill_id LIMIT ?",
                    parameters,
                ).fetchall()
                if not rows:
                    return
                for row in rows:
                    record = self._record_from_row(row, manifest)
                    yield record
                    last_skill_id = record.skill_id
                    if remaining is not None:
                        remaining -= 1
                        if remaining <= 0:
                            return

    def _record_from_row(
        self,
        row: Mapping[str, Any],
        manifest: SkillCenterBundleManifest,
    ) -> SkillCenterSkillRecord:
        values = {
            name: str(row[name] or "")
            for name in (
                "skill_id",
                "domain",
                "profile",
                "source_type",
                "source_url",
                "title",
                "skill_kind",
                "language",
                "source_id",
                "primary_source_id",
                "metadata_yaml",
                "skill_md",
                "library_md",
            )
        }
        for name in ("skill_id", "title", "skill_md"):
            if not values[name].strip():
                raise SkillCenterRecordError(f"{name} must not be empty")
        for name in ("metadata_yaml", "skill_md", "library_md"):
            if len(values[name]) > self.max_text_chars:
                raise SkillCenterRecordError(
                    f"{values['skill_id']}: {name} exceeds max_text_chars"
                )
        score = row["overall_score"]
        if score is not None:
            try:
                score = float(score)
            except (TypeError, ValueError) as exc:
                raise SkillCenterRecordError(
                    f"{values['skill_id']}: invalid overall_score"
                ) from exc
            if not math.isfinite(score):
                raise SkillCenterRecordError(
                    f"{values['skill_id']}: overall_score must be finite"
                )
        return SkillCenterSkillRecord(
            **values,
            overall_score=score,
            dataset_id=manifest.dataset_id,
            dataset_revision=manifest.dataset_revision,
            repository_file=manifest.repository_file,
            bundle_sha256=manifest.local_sha256,
        )

    def _validate_file_header(self) -> None:
        if not self.path.is_file():
            raise SkillCenterBundleSchemaError(
                f"SkillCenter bundle does not exist: {self.path}"
            )
        with self.path.open("rb") as handle:
            if handle.read(len(_SQLITE_HEADER)) != _SQLITE_HEADER:
                raise SkillCenterBundleSchemaError(
                    "SkillCenter bundle is not a SQLite 3 database"
                )

    def _connect(self) -> sqlite3.Connection:
        uri = f"{self.path.as_uri()}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.enable_load_extension(False)
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table', 'view') ORDER BY name"
            )
        }
        missing_tables = sorted(set(_REQUIRED_COLUMNS) - tables)
        if missing_tables:
            raise SkillCenterBundleSchemaError(
                "Missing SkillCenter table(s): " + ", ".join(missing_tables)
            )
        for table, required_columns in _REQUIRED_COLUMNS.items():
            # Table names come only from the constant allowlist above.
            columns = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
            missing_columns = sorted(required_columns - columns)
            if missing_columns:
                raise SkillCenterBundleSchemaError(
                    f"{table} is missing column(s): {', '.join(missing_columns)}"
                )


def _metadata_scalar(metadata_yaml: str, key: str) -> str:
    """Extract one top-level scalar without constructing arbitrary YAML types."""

    for match in _METADATA_SCALAR_RE.finditer(metadata_yaml or ""):
        if match.group("key") != key:
            continue
        value = match.group("value").strip()
        if not value:
            return ""
        if value[:1] in {'"', "'"}:
            if value[:1] == '"':
                try:
                    decoded = json.loads(value)
                    return str(decoded).strip()
                except (TypeError, ValueError, json.JSONDecodeError):
                    return value.strip('"').strip()
            return value.strip("'").strip()
        return value
    return ""


def _positive_or_zero_int(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise SkillCenterBundleSchemaError(f"{label} must be an integer") from exc
    if result < 0:
        raise SkillCenterBundleSchemaError(f"{label} must be non-negative")
    return result


def _file_sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "DEFAULT_SKILLCENTER_DATASET_ID",
    "SKILLCENTER_BUNDLE_SCHEMA_VERSION",
    "SkillCenterBundleManifest",
    "SkillCenterBundleReader",
    "SkillCenterBundleSchemaError",
    "SkillCenterRecordError",
    "SkillCenterSkillRecord",
]
