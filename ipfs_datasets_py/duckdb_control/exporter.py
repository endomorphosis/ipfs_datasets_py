"""Deterministic Markdown, JSON, Parquet, Arrow, and CAR exports (DQK-045).

Exports are explicit **read-only** jobs. Each job is bound to:

* query / template ID
* parameters digest
* schema version
* snapshot / revision
* root CID
* content digest
* destination policy
* replay verification

Acceptance properties enforced by construction:

* repeated export of one snapshot is **byte-identical**
* an export **cannot mutate** source state or become implicit authority
* **sensitive columns** are excluded by policy

Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    ClassVar,
    Final,
    Iterable,
    Mapping,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.contracts import (
    ContentMediaType,
    ContentReference,
    ContractError,
    ExportReceipt,
    SnapshotId,
    SourceDigest,
    canonical_json_bytes,
    content_identity,
    normalize_timestamp,
    parse_cid,
    parse_schema_id,
    parse_source_digest,
)
from ipfs_datasets_py.duckdb_control.query_registry import (
    SENSITIVE_COLUMN_NAMES,
    ColumnClassification,
    ColumnPolicy,
    ColumnPolicyError,
)

__all__ = [
    "EXPORTER_SCHEMA",
    "EXPORT_JOB_SCHEMA",
    "EXPORT_ARTIFACT_SCHEMA",
    "RENDERER_VERSION",
    "DEFAULT_DESTINATION_PREFIXES",
    "AUTHORITY_PATH_MARKERS",
    "DestinationPolicy",
    "DestinationPolicyViolation",
    "ExportArtifact",
    "ExportError",
    "ExportFormat",
    "ExportJob",
    "ExportJobResult",
    "ExportStatus",
    "ReplayVerificationError",
    "SensitiveColumnError",
    "SnapshotExporter",
    "default_destination_policy",
    "digest_parameters",
    "project_rows_for_export",
    "render_export_bytes",
    "verify_export_replay",
]


# ---------------------------------------------------------------------------
# Schema pins / constants
# ---------------------------------------------------------------------------

EXPORTER_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-exporter@1"
EXPORT_JOB_SCHEMA: Final[str] = "ipfs_datasets_py/duckdb-control-export-job@1"
EXPORT_ARTIFACT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-export-artifact@1"
)

RENDERER_VERSION: Final[str] = "dqk-045@1"

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_TEMPLATE_ID_RE = re.compile(
    r"^[a-z][a-z0-9_]{0,63}(?:\.[a-z][a-z0-9_]{0,63}){0,3}$"
)

DEFAULT_DESTINATION_PREFIXES: Final[tuple[str, ...]] = (
    "exports/",
    "derived/",
    "projections/",
    "release_exports/",
)

# Paths that imply operational authority; destination policy refuses these.
AUTHORITY_PATH_MARKERS: Final[tuple[str, ...]] = (
    "/control/",
    "/state/",
    "/authority/",
    "/ledger/",
    "/checkpoints/",
    "/leases/",
    "/idempotency/",
    "control.duckdb",
    "records.jsonl",
    ".meta.json",
)

_MAX_ROWS: Final[int] = 1_000_000
_MAX_BYTES: Final[int] = 64 * 1024 * 1024
_ARROW_MAGIC: Final[bytes] = b"ARROW1\x00"
_CAR_VERSION: Final[int] = 1


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ExportError(ValueError):
    """Fail-closed rejection of an export job, policy, or render input."""


class DestinationPolicyViolation(ExportError):
    """Raised when destination policy forbids the requested write surface."""


class SensitiveColumnError(ExportError):
    """Raised when a sensitive or secret column would enter the export surface."""


class ReplayVerificationError(ExportError):
    """Raised when a replay export is not byte-identical to the prior artifact."""


# ---------------------------------------------------------------------------
# Formats / status
# ---------------------------------------------------------------------------


class ExportFormat(str, Enum):
    """Closed set of deterministic export render formats (DQK-045)."""

    MARKDOWN = "markdown"
    JSON = "json"
    PARQUET = "parquet"
    ARROW = "arrow"
    CAR = "car"

    @classmethod
    def parse(cls, value: "ExportFormat | str") -> "ExportFormat":
        if isinstance(value, cls):
            return value
        # Accept cross-reload Enum members and bare strings.
        if isinstance(value, Enum):
            raw = getattr(value, "value", None)
            text = str(raw if raw is not None else value).strip().lower()
        else:
            text = str(value or "").strip().lower()
        if text.startswith("exportformat."):
            text = text.rsplit(".", 1)[-1]
        try:
            return cls(text)
        except ValueError as exc:
            raise ExportError(
                f"unsupported export format {value!r}; "
                f"allowed: {', '.join(f.value for f in cls)}"
            ) from exc


class ExportStatus(str, Enum):
    """Terminal status recorded on an export job result."""

    COMPLETED = "completed"
    DENIED = "denied"
    FAILED = "failed"


_FORMAT_MEDIA: Final[Mapping[ExportFormat, ContentMediaType]] = MappingProxyType(
    {
        ExportFormat.MARKDOWN: ContentMediaType.BYTES,
        ExportFormat.JSON: ContentMediaType.JSON,
        ExportFormat.PARQUET: ContentMediaType.PARQUET,
        ExportFormat.ARROW: ContentMediaType.BYTES,
        ExportFormat.CAR: ContentMediaType.CAR,
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def digest_parameters(params: Mapping[str, Any] | None) -> str:
    """Return ``sha256:<hex>`` over canonical JSON of bound parameters."""

    payload = dict(params or {})
    return content_identity(payload)


def _safe_token(value: str, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ExportError(f"{field_name} is required")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ExportError(f"{field_name} must be single-line text")
    if _SAFE_TOKEN.fullmatch(text) is None:
        raise ExportError(f"{field_name} is not a safe token: {value!r}")
    return text


def _normalize_location(path: str) -> str:
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def _looks_like_authority_path(path: str) -> bool:
    lower = f"/{_normalize_location(path).lower()}"
    for marker in AUTHORITY_PATH_MARKERS:
        if marker in lower:
            return True
    return False


def _uvarint(value: int) -> bytes:
    if value < 0:
        raise ExportError("varint value must be non-negative")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def _content_cid_from_digest(digest: str) -> str:
    """Bind root CID to the content digest (storage-neutral content addressing)."""

    return parse_cid(parse_source_digest(digest))


def _default_column_policy_for_rows(
    rows: Sequence[Mapping[str, Any]],
) -> ColumnPolicy:
    """Build a public-only column policy from observed non-sensitive keys."""

    names: dict[str, ColumnClassification] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ExportError("each export row must be a mapping")
        for key in row:
            if not isinstance(key, str) or not key:
                raise ExportError("column names must be nonempty strings")
            lower = key.lower()
            if lower in SENSITIVE_COLUMN_NAMES:
                raise SensitiveColumnError(
                    f"result column {key!r} is forbidden on export surface"
                )
            if not _SAFE_IDENT.match(key):
                raise ExportError(f"invalid column name {key!r}")
            names.setdefault(key, ColumnClassification.PUBLIC)
    if not names:
        # Empty result set still needs a declared surface for policy identity.
        names["__empty__"] = ColumnClassification.PUBLIC
    return ColumnPolicy(columns=names)


def project_rows_for_export(
    rows: Sequence[Mapping[str, Any]],
    column_policy: ColumnPolicy | None = None,
) -> tuple[tuple[dict[str, Any], ...], ColumnPolicy]:
    """Project rows onto the allowlisted non-sensitive export surface.

    Sensitive-named columns (see :data:`SENSITIVE_COLUMN_NAMES`) and secret
    classifications are rejected.  Input row mappings are never mutated.
    """

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise ExportError("rows must be a sequence of mappings")
    if len(rows) > _MAX_ROWS:
        raise ExportError(f"row count exceeds {_MAX_ROWS}-row export bound")

    materialised = list(rows)
    policy = column_policy
    if policy is None:
        policy = _default_column_policy_for_rows(materialised)
    elif not isinstance(policy, ColumnPolicy):
        raise ExportError("column_policy must be a ColumnPolicy")

    projected: list[dict[str, Any]] = []
    for index, row in enumerate(materialised):
        if not isinstance(row, Mapping):
            raise ExportError(f"row[{index}] must be a mapping")
        # Fail closed on sensitive names before projection drops them.
        for key in row:
            if not isinstance(key, str):
                raise SensitiveColumnError("column names must be strings")
            if key.lower() in SENSITIVE_COLUMN_NAMES:
                raise SensitiveColumnError(
                    f"result column {key!r} is forbidden on export surface"
                )
        try:
            out = policy.project_row(row)
        except ColumnPolicyError as exc:
            raise SensitiveColumnError(str(exc)) from exc
        # Drop synthetic empty marker when present without real data.
        if "__empty__" in out and len(out) == 1 and not row:
            projected.append({})
        else:
            # Stable key order for determinism independent of input dict order.
            projected.append({k: out[k] for k in sorted(out)})
    return tuple(projected), policy


# ---------------------------------------------------------------------------
# Destination policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DestinationPolicy:
    """Closed policy for where and how an export may be materialised.

    Exports are one-way projections: they may only land under declared
    non-authority prefixes, never write back to source authority paths, and
    never claim authoritative status.
    """

    policy_id: str
    allowed_formats: frozenset[ExportFormat]
    allowed_location_prefixes: tuple[str, ...] = DEFAULT_DESTINATION_PREFIXES
    forbid_authority_paths: bool = True
    allow_source_mutation: bool = False
    non_authoritative: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_id", _safe_token(self.policy_id, field_name="policy_id")
        )
        if not self.non_authoritative:
            raise DestinationPolicyViolation(
                "destination policy must declare non_authoritative=true"
            )
        if self.allow_source_mutation:
            raise DestinationPolicyViolation(
                "destination policy must not allow source mutation"
            )
        formats = self.allowed_formats
        if not isinstance(formats, frozenset) or not formats:
            if isinstance(formats, (set, list, tuple)) and formats:
                formats = frozenset(
                    ExportFormat.parse(item) for item in formats  # type: ignore[arg-type]
                )
                object.__setattr__(self, "allowed_formats", formats)
            else:
                raise DestinationPolicyViolation(
                    "allowed_formats must be a nonempty frozenset of ExportFormat"
                )
        else:
            object.__setattr__(
                self,
                "allowed_formats",
                frozenset(ExportFormat.parse(item) for item in formats),
            )
        prefixes = tuple(
            _normalize_location(p) + ("" if _normalize_location(p).endswith("/") else "/")
            if _normalize_location(p)
            else ""
            for p in self.allowed_location_prefixes
        )
        prefixes = tuple(p for p in prefixes if p)
        if not prefixes:
            raise DestinationPolicyViolation(
                "allowed_location_prefixes must be nonempty"
            )
        object.__setattr__(self, "allowed_location_prefixes", prefixes)
        if not self.forbid_authority_paths:
            raise DestinationPolicyViolation(
                "destination policy must forbid authority paths"
            )

    def permits_format(self, fmt: ExportFormat | str) -> bool:
        return ExportFormat.parse(fmt) in self.allowed_formats

    def validate_destination(
        self,
        *,
        format: ExportFormat | str,
        location_hint: str = "",
    ) -> str:
        fmt = ExportFormat.parse(format)
        if fmt not in self.allowed_formats:
            raise DestinationPolicyViolation(
                f"format {fmt.value!r} is not allowed by destination policy "
                f"{self.policy_id!r}"
            )
        hint = _normalize_location(location_hint)
        if not hint:
            # Empty hint is allowed: storage-neutral content identity only.
            return ""
        if self.forbid_authority_paths and _looks_like_authority_path(hint):
            raise DestinationPolicyViolation(
                f"location_hint {location_hint!r} looks like an authority path"
            )
        # Absolute paths and parent traversal are never destinations.
        if (
            location_hint.strip().startswith(("/", "\\"))
            or ".." in hint.split("/")
            or re.match(r"^[A-Za-z]:", location_hint.strip())
        ):
            raise DestinationPolicyViolation(
                "location_hint must be a relative non-authority export path"
            )
        if not any(hint.startswith(prefix) for prefix in self.allowed_location_prefixes):
            raise DestinationPolicyViolation(
                f"location_hint {location_hint!r} is outside allowed prefixes "
                f"{list(self.allowed_location_prefixes)}"
            )
        return hint

    @property
    def identity_id(self) -> str:
        return content_identity(
            {
                "policy_id": self.policy_id,
                "allowed_formats": sorted(f.value for f in self.allowed_formats),
                "allowed_location_prefixes": list(self.allowed_location_prefixes),
                "forbid_authority_paths": True,
                "allow_source_mutation": False,
                "non_authoritative": True,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "allowed_formats": sorted(f.value for f in self.allowed_formats),
            "allowed_location_prefixes": list(self.allowed_location_prefixes),
            "forbid_authority_paths": True,
            "allow_source_mutation": False,
            "non_authoritative": True,
            "identity_id": self.identity_id,
        }


def default_destination_policy(
    *,
    policy_id: str = "export:default",
    formats: Iterable[ExportFormat | str] | None = None,
) -> DestinationPolicy:
    """Return a production-default destination policy for derived exports."""

    if formats is None:
        allowed = frozenset(ExportFormat)
    else:
        allowed = frozenset(ExportFormat.parse(f) for f in formats)
    return DestinationPolicy(
        policy_id=policy_id,
        allowed_formats=allowed,
        allowed_location_prefixes=DEFAULT_DESTINATION_PREFIXES,
        forbid_authority_paths=True,
        allow_source_mutation=False,
        non_authoritative=True,
    )


# ---------------------------------------------------------------------------
# Renderers (deterministic, stdlib-only)
# ---------------------------------------------------------------------------


def _render_json(
    rows: Sequence[Mapping[str, Any]],
    *,
    envelope: Mapping[str, Any],
) -> bytes:
    payload = {
        **dict(envelope),
        "rows": [dict(r) for r in rows],
    }
    return canonical_json_bytes(payload)


def _markdown_escape_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").replace("\r", "")


def _render_markdown(
    rows: Sequence[Mapping[str, Any]],
    *,
    envelope: Mapping[str, Any],
) -> bytes:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in sorted(row):
            if key not in seen:
                seen.add(key)
                columns.append(key)
    lines: list[str] = [
        f"# Export `{envelope.get('template_id', '')}`",
        "",
        f"- schema_version: `{envelope.get('schema_version', '')}`",
        f"- snapshot: `{envelope.get('snapshot_id', '')}`",
        f"- revision: `{envelope.get('revision', '')}`",
        f"- parameters_digest: `{envelope.get('parameters_digest', '')}`",
        f"- non_authoritative: `true`",
        f"- read_only: `true`",
        "",
    ]
    if not columns:
        lines.append("_empty result_")
        lines.append("")
    else:
        header = "| " + " | ".join(columns) + " |"
        sep = "| " + " | ".join("---" for _ in columns) + " |"
        lines.append(header)
        lines.append(sep)
        for row in rows:
            cells = [
                _markdown_escape_cell(row.get(col, "")) for col in columns
            ]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    # Trailing newline for stable POSIX text files.
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def _render_parquet_envelope(
    rows: Sequence[Mapping[str, Any]],
    *,
    envelope: Mapping[str, Any],
) -> bytes:
    """Deterministic PAR1-framed payload (stdlib; no pyarrow required).

    Layout: ``PAR1`` + body + footer + ``u32le(len(footer))`` + ``PAR1``.
    Body and footer are canonical JSON so repeated renders are byte-identical.
    """

    body_obj = {
        "kind": "duckdb_control_parquet_envelope",
        "envelope": dict(envelope),
        "rows": [dict(r) for r in rows],
    }
    body = canonical_json_bytes(body_obj)
    footer_obj = {
        "format": "parquet-envelope@1",
        "row_count": len(rows),
        "body_digest": SourceDigest.from_bytes(body).digest,
    }
    footer = canonical_json_bytes(footer_obj)
    out = bytearray()
    out.extend(b"PAR1")
    out.extend(body)
    out.extend(footer)
    out.extend(struct.pack("<I", len(footer)))
    out.extend(b"PAR1")
    return bytes(out)


def _render_arrow_stream(
    rows: Sequence[Mapping[str, Any]],
    *,
    envelope: Mapping[str, Any],
) -> bytes:
    """Deterministic Arrow-like stream envelope (stdlib IPC substitute).

    Layout: ``ARROW1\\0`` + ``u32be(schema_len)`` + schema +
    ``u32be(body_len)`` + body. Schema/body are canonical JSON.
    """

    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in sorted(row):
            if key not in seen:
                seen.add(key)
                columns.append(key)
    schema = canonical_json_bytes(
        {
            "format": "arrow-envelope@1",
            "columns": columns,
            "envelope": dict(envelope),
        }
    )
    body = canonical_json_bytes({"rows": [dict(r) for r in rows]})
    out = bytearray()
    out.extend(_ARROW_MAGIC)
    out.extend(struct.pack(">I", len(schema)))
    out.extend(schema)
    out.extend(struct.pack(">I", len(body)))
    out.extend(body)
    return bytes(out)


def _render_car(
    rows: Sequence[Mapping[str, Any]],
    *,
    envelope: Mapping[str, Any],
) -> bytes:
    """Minimal deterministic CARv1 with one raw block rooted at content CID."""

    payload = canonical_json_bytes(
        {
            "kind": "duckdb_control_car_export",
            "envelope": dict(envelope),
            "rows": [dict(r) for r in rows],
        }
    )
    # Content-addressed block identity (sha256 of payload bytes).
    digest_hex = hashlib.sha256(payload).hexdigest()
    # Multihash identity tag as ASCII digest for hermetic CAR (storage-neutral).
    # Block key = "sha256:" + hex so root_cid matches ContentReference style.
    block_key = f"sha256:{digest_hex}".encode("utf-8")
    header_obj = {
        "version": _CAR_VERSION,
        "roots": [f"sha256:{digest_hex}"],
    }
    header_cbor_like = canonical_json_bytes(header_obj)
    out = bytearray()
    out.extend(_uvarint(len(header_cbor_like)))
    out.extend(header_cbor_like)
    section = block_key + payload
    out.extend(_uvarint(len(section)))
    out.extend(section)
    return bytes(out)


def render_export_bytes(
    rows: Sequence[Mapping[str, Any]],
    *,
    format: ExportFormat | str,
    envelope: Mapping[str, Any],
) -> bytes:
    """Render projected rows to deterministic bytes for ``format``."""

    fmt = ExportFormat.parse(format)
    if not isinstance(envelope, Mapping):
        raise ExportError("envelope must be a mapping")
    # Envelope keys sorted via canonical JSON paths inside each renderer.
    if fmt is ExportFormat.JSON:
        data = _render_json(rows, envelope=envelope)
    elif fmt is ExportFormat.MARKDOWN:
        data = _render_markdown(rows, envelope=envelope)
    elif fmt is ExportFormat.PARQUET:
        data = _render_parquet_envelope(rows, envelope=envelope)
    elif fmt is ExportFormat.ARROW:
        data = _render_arrow_stream(rows, envelope=envelope)
    elif fmt is ExportFormat.CAR:
        data = _render_car(rows, envelope=envelope)
    else:  # pragma: no cover - enum exhaustiveness
        raise ExportError(f"unsupported export format {fmt!r}")
    if len(data) > _MAX_BYTES:
        raise ExportError(f"export payload exceeds {_MAX_BYTES}-byte bound")
    return data


# ---------------------------------------------------------------------------
# Job / artifact / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExportJob:
    """Explicit read-only export job identity (never authoritative).

    Binds query/template ID, parameters digest, schema version, snapshot /
    revision, destination policy, and render format.  ``root_cid`` and
    ``content_digest`` are filled on the resulting artifact after render.
    """

    SCHEMA: ClassVar[str] = EXPORT_JOB_SCHEMA

    job_id: str
    template_id: str
    parameters_digest: str
    schema_version: str
    snapshot: SnapshotId
    format: ExportFormat
    destination_policy: DestinationPolicy
    revision: str = "1"
    template_version: int = 1
    location_hint: str = ""
    column_policy: ColumnPolicy | None = None
    renderer_version: str = RENDERER_VERSION
    read_only: bool = True
    non_authoritative: bool = True
    created_at: str = "1970-01-01T00:00:00Z"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "job_id", _safe_token(self.job_id, field_name="job_id")
        )
        tid = str(self.template_id or "").strip()
        if not tid or _TEMPLATE_ID_RE.fullmatch(tid) is None:
            raise ExportError(f"invalid template_id {self.template_id!r}")
        object.__setattr__(self, "template_id", tid)

        try:
            object.__setattr__(
                self,
                "parameters_digest",
                parse_source_digest(self.parameters_digest),
            )
        except ContractError as exc:
            raise ExportError(f"parameters_digest: {exc}") from exc

        try:
            schema = parse_schema_id(self.schema_version)
        except ContractError as exc:
            # Also accept bare version tags like "1" by expanding to a schema id.
            rev = str(self.schema_version or "").strip()
            if re.fullmatch(r"[0-9]+", rev):
                schema = parse_schema_id(
                    f"ipfs_datasets_py/duckdb-control-export-schema@{rev}"
                )
            else:
                raise ExportError(f"schema_version: {exc}") from exc
        object.__setattr__(self, "schema_version", schema)

        if not isinstance(self.snapshot, SnapshotId):
            raise ExportError("snapshot must be a SnapshotId")

        object.__setattr__(
            self, "revision", _safe_token(str(self.revision), field_name="revision")
        )

        object.__setattr__(self, "format", ExportFormat.parse(self.format))

        if not isinstance(self.destination_policy, DestinationPolicy):
            raise ExportError("destination_policy must be a DestinationPolicy")

        if (
            not isinstance(self.template_version, int)
            or isinstance(self.template_version, bool)
            or self.template_version < 1
        ):
            raise ExportError("template_version must be a positive int")

        if not self.read_only:
            raise ExportError("export jobs must be read_only=true")
        if not self.non_authoritative:
            raise ExportError("export jobs must declare non_authoritative=true")

        object.__setattr__(
            self,
            "renderer_version",
            _safe_token(self.renderer_version, field_name="renderer_version"),
        )

        try:
            object.__setattr__(
                self, "created_at", normalize_timestamp(self.created_at)
            )
        except ContractError as exc:
            raise ExportError(str(exc)) from exc

        # Validate destination against policy at construction when hint present.
        hint = self.destination_policy.validate_destination(
            format=self.format, location_hint=self.location_hint
        )
        object.__setattr__(self, "location_hint", hint)

        if self.column_policy is not None and not isinstance(
            self.column_policy, ColumnPolicy
        ):
            raise ExportError("column_policy must be a ColumnPolicy or None")

    @property
    def query_id(self) -> str:
        """Alias for template_id (query/template ID in the job contract)."""

        return self.template_id

    @property
    def identity_id(self) -> str:
        """Identity excluding wall-clock fields and location hints."""

        return content_identity(
            {
                "schema": EXPORT_JOB_SCHEMA,
                "job_id": self.job_id,
                "template_id": self.template_id,
                "template_version": self.template_version,
                "parameters_digest": self.parameters_digest,
                "schema_version": self.schema_version,
                "snapshot": self.snapshot.to_dict(),
                "revision": self.revision,
                "format": self.format.value,
                "destination_policy_identity": self.destination_policy.identity_id,
                "column_policy_identity": (
                    self.column_policy.identity_id if self.column_policy else ""
                ),
                "renderer_version": self.renderer_version,
                "read_only": True,
                "non_authoritative": True,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EXPORT_JOB_SCHEMA,
            "job_id": self.job_id,
            "template_id": self.template_id,
            "query_id": self.query_id,
            "template_version": self.template_version,
            "parameters_digest": self.parameters_digest,
            "schema_version": self.schema_version,
            "snapshot": self.snapshot.to_dict(),
            "revision": self.revision,
            "format": self.format.value,
            "destination_policy": self.destination_policy.to_dict(),
            "location_hint": self.location_hint,
            "column_policy": (
                self.column_policy.to_dict() if self.column_policy else None
            ),
            "renderer_version": self.renderer_version,
            "read_only": True,
            "non_authoritative": True,
            "created_at": self.created_at,
            "identity_id": self.identity_id,
        }

    def render_envelope(self) -> dict[str, Any]:
        """Stable envelope fields embedded into every format payload."""

        return {
            "schema": EXPORTER_SCHEMA,
            "job_id": self.job_id,
            "template_id": self.template_id,
            "query_id": self.query_id,
            "template_version": self.template_version,
            "parameters_digest": self.parameters_digest,
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot.value,
            "store_generation": self.snapshot.store_generation,
            "revision": self.revision,
            "format": self.format.value,
            "destination_policy_id": self.destination_policy.policy_id,
            "destination_policy_identity": self.destination_policy.identity_id,
            "renderer_version": self.renderer_version,
            "read_only": True,
            "non_authoritative": True,
        }


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    """Rendered export bytes bound to content digest and root CID."""

    SCHEMA: ClassVar[str] = EXPORT_ARTIFACT_SCHEMA

    payload: bytes
    content_digest: str
    root_cid: str
    format: ExportFormat
    media_type: ContentMediaType
    row_count: int
    projected_columns: tuple[str, ...]
    byte_size: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.payload, (bytes, bytearray)):
            raise ExportError("payload must be bytes")
        payload = bytes(self.payload)
        object.__setattr__(self, "payload", payload)
        digest = SourceDigest.from_bytes(payload).digest
        object.__setattr__(
            self, "content_digest", parse_source_digest(self.content_digest)
        )
        if self.content_digest != digest:
            raise ExportError(
                "content_digest does not match payload bytes "
                f"(expected {digest}, got {self.content_digest})"
            )
        object.__setattr__(self, "root_cid", parse_cid(str(self.root_cid)))
        object.__setattr__(self, "format", ExportFormat.parse(self.format))
        if not isinstance(self.media_type, ContentMediaType):
            try:
                object.__setattr__(
                    self, "media_type", ContentMediaType(str(self.media_type))
                )
            except ValueError as exc:
                raise ExportError(f"invalid media_type {self.media_type!r}") from exc
        if (
            not isinstance(self.row_count, int)
            or isinstance(self.row_count, bool)
            or self.row_count < 0
        ):
            raise ExportError("row_count must be a non-negative int")
        if not isinstance(self.projected_columns, tuple):
            object.__setattr__(
                self, "projected_columns", tuple(self.projected_columns)
            )
        size = len(payload) if self.byte_size == 0 else int(self.byte_size)
        if size != len(payload):
            raise ExportError("byte_size must equal len(payload)")
        object.__setattr__(self, "byte_size", size)

    def content_reference(self, *, location_hint: str = "") -> ContentReference:
        return ContentReference(
            media_type=self.media_type,
            content_id=self.root_cid,
            byte_size=self.byte_size,
            source_digest=self.content_digest,
            location_hint=location_hint,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EXPORT_ARTIFACT_SCHEMA,
            "content_digest": self.content_digest,
            "root_cid": self.root_cid,
            "format": self.format.value,
            "media_type": self.media_type.value,
            "row_count": self.row_count,
            "projected_columns": list(self.projected_columns),
            "byte_size": self.byte_size,
        }


@dataclass(frozen=True, slots=True)
class ExportJobResult:
    """Completed export: job, artifact, contract receipt, and status flags."""

    job: ExportJob
    artifact: ExportArtifact
    receipt: ExportReceipt
    status: ExportStatus = ExportStatus.COMPLETED
    # Hard invariants: always true for a successful construction.
    read_only: bool = True
    non_authoritative: bool = True
    mutated_source: bool = False

    def __post_init__(self) -> None:
        if not self.read_only:
            raise ExportError("export result must remain read_only")
        if not self.non_authoritative:
            raise ExportError("export result must remain non_authoritative")
        if self.mutated_source:
            raise ExportError("export result must not report source mutation")
        if not isinstance(self.job, ExportJob):
            raise ExportError("job must be an ExportJob")
        if not isinstance(self.artifact, ExportArtifact):
            raise ExportError("artifact must be an ExportArtifact")
        if not isinstance(self.receipt, ExportReceipt):
            raise ExportError("receipt must be an ExportReceipt")
        if not isinstance(self.status, ExportStatus):
            object.__setattr__(self, "status", ExportStatus(str(self.status)))
        if self.receipt.non_authoritative is not True:
            raise ExportError("receipt must declare non_authoritative=true")

    @property
    def content_digest(self) -> str:
        return self.artifact.content_digest

    @property
    def root_cid(self) -> str:
        return self.artifact.root_cid

    @property
    def parameters_digest(self) -> str:
        return self.job.parameters_digest

    @property
    def template_id(self) -> str:
        return self.job.template_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EXPORTER_SCHEMA,
            "job": self.job.to_dict(),
            "artifact": self.artifact.to_dict(),
            "receipt": self.receipt.to_dict(),
            "status": self.status.value,
            "read_only": True,
            "non_authoritative": True,
            "mutated_source": False,
            "content_digest": self.content_digest,
            "root_cid": self.root_cid,
            "parameters_digest": self.parameters_digest,
            "template_id": self.template_id,
            "schema_version": self.job.schema_version,
            "snapshot": self.job.snapshot.to_dict(),
            "revision": self.job.revision,
            "destination_policy": self.job.destination_policy.to_dict(),
        }


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------


class SnapshotExporter:
    """Render snapshot-bound, policy-filtered, read-only export jobs.

    The exporter never mutates input rows or any external authority.  It only
    projects, serialises, digests, and issues non-authoritative receipts.
    """

    SCHEMA: ClassVar[str] = EXPORTER_SCHEMA

    def __init__(self) -> None:
        # Track source object ids seen during export to assert non-mutation.
        self._last_source_fingerprints: tuple[tuple[int, str], ...] = ()

    def export_rows(
        self,
        rows: Sequence[Mapping[str, Any]],
        job: ExportJob,
        *,
        source_mutability_probe: list[Mapping[str, Any]] | None = None,
    ) -> ExportJobResult:
        """Export ``rows`` under ``job``; return artifact + receipt.

        Parameters
        ----------
        rows:
            Projected query result rows (mappings). Never mutated.
        job:
            Explicit read-only :class:`ExportJob`.
        source_mutability_probe:
            Optional list identity that must be unchanged after export (tests
            and callers can pass the same list they sourced rows from).
        """

        if not isinstance(job, ExportJob):
            raise ExportError("job must be an ExportJob")

        # Snapshot source fingerprints for mutation detection.
        source_list = (
            source_mutability_probe
            if source_mutability_probe is not None
            else list(rows)
        )
        before = _fingerprint_rows(source_list)

        projected, policy = project_rows_for_export(rows, job.column_policy)
        # If job carried no column policy, bind the derived one for identity.
        effective_job = job
        if job.column_policy is None:
            effective_job = ExportJob(
                job_id=job.job_id,
                template_id=job.template_id,
                parameters_digest=job.parameters_digest,
                schema_version=job.schema_version,
                snapshot=job.snapshot,
                format=job.format,
                destination_policy=job.destination_policy,
                revision=job.revision,
                template_version=job.template_version,
                location_hint=job.location_hint,
                column_policy=policy,
                renderer_version=job.renderer_version,
                read_only=True,
                non_authoritative=True,
                created_at=job.created_at,
            )

        envelope = effective_job.render_envelope()
        payload = render_export_bytes(
            projected, format=effective_job.format, envelope=envelope
        )
        content_digest = SourceDigest.from_bytes(payload).digest
        root_cid = _content_cid_from_digest(content_digest)

        columns: list[str] = []
        seen: set[str] = set()
        for row in projected:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    columns.append(key)
        columns.sort()

        artifact = ExportArtifact(
            payload=payload,
            content_digest=content_digest,
            root_cid=root_cid,
            format=effective_job.format,
            media_type=_FORMAT_MEDIA[effective_job.format],
            row_count=len(projected),
            projected_columns=tuple(columns),
        )

        content_ref = artifact.content_reference(
            location_hint=effective_job.location_hint
        )
        receipt = ExportReceipt(
            export_id=effective_job.job_id,
            snapshot=effective_job.snapshot,
            content=content_ref,
            created_at=effective_job.created_at,
            renderer_version=effective_job.renderer_version,
            non_authoritative=True,
        )

        after = _fingerprint_rows(source_list)
        if before != after:
            raise ExportError(
                "export mutated source rows; exports must be read-only"
            )
        self._last_source_fingerprints = after

        return ExportJobResult(
            job=effective_job,
            artifact=artifact,
            receipt=receipt,
            status=ExportStatus.COMPLETED,
            read_only=True,
            non_authoritative=True,
            mutated_source=False,
        )

    def verify_replay(
        self,
        rows: Sequence[Mapping[str, Any]],
        job: ExportJob,
        expected: ExportArtifact | ExportJobResult,
    ) -> ExportJobResult:
        """Re-export and require byte-identical payload and matching digests."""

        if isinstance(expected, ExportJobResult):
            expected_artifact = expected.artifact
        elif isinstance(expected, ExportArtifact):
            expected_artifact = expected
        else:
            raise ExportError("expected must be ExportArtifact or ExportJobResult")

        again = self.export_rows(rows, job)
        verify_export_replay(again.artifact, expected_artifact)
        return again


def _fingerprint_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[tuple[int, str], ...]:
    """Stable fingerprint of row object identities and content digests."""

    out: list[tuple[int, str]] = []
    for row in rows:
        if isinstance(row, Mapping):
            # Capture mapping content without mutating; use canonical JSON.
            try:
                digest = content_identity(dict(row))
            except ContractError:
                digest = hashlib.sha256(repr(dict(row)).encode("utf-8")).hexdigest()
                digest = f"sha256:{digest}"
            out.append((id(row), digest))
        else:
            out.append((id(row), f"type:{type(row).__name__}"))
    return tuple(out)


def verify_export_replay(
    observed: ExportArtifact,
    expected: ExportArtifact,
) -> None:
    """Fail closed unless ``observed`` is byte-identical to ``expected``."""

    if not isinstance(observed, ExportArtifact) or not isinstance(
        expected, ExportArtifact
    ):
        raise ReplayVerificationError("both sides must be ExportArtifact")
    if observed.payload != expected.payload:
        raise ReplayVerificationError(
            "replay export payload is not byte-identical"
        )
    if observed.content_digest != expected.content_digest:
        raise ReplayVerificationError(
            "replay content_digest mismatch: "
            f"expected {expected.content_digest}, observed {observed.content_digest}"
        )
    if observed.root_cid != expected.root_cid:
        raise ReplayVerificationError(
            "replay root_cid mismatch: "
            f"expected {expected.root_cid}, observed {observed.root_cid}"
        )
    if observed.format != expected.format:
        raise ReplayVerificationError("replay format mismatch")
    if observed.byte_size != expected.byte_size:
        raise ReplayVerificationError("replay byte_size mismatch")
