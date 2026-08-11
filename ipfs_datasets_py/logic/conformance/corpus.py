"""Cross-family logic conformance corpus (LogicConformanceCorpus@1 / LFP-002).

Freezes a versioned, content-addressed fixture manifest covering positive,
negative, ambiguous, adversarial, translation, model, proof, and trace cases.

Fail-closed validation rejects:

* missing digests
* duplicate fixture IDs
* unsafe paths (absolute, traversal, backslashes, NUL)
* unbounded payloads (size exceeds ``max_payload_bytes``)
* fixtures without an expected disposition

Labels not yet known to the baseline family registry are preserved losslessly
with an explicit ``unknown`` label disposition so LFP-003 / LFP-010 can close
observed drift without silent rewrite or drop.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Final

from ipfs_datasets_py.logic.families.registry import (
    DEFAULT_REGISTRY,
    LogicFamilyRegistry,
    LogicFamilyRegistryError,
    UnknownDescriptorError,
    normalize_family_name,
)

LOGIC_CONFORMANCE_CORPUS_INTERFACE: Final = "LogicConformanceCorpus@1"
LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION: Final = "logic-conformance-corpus/v1"
FIXTURE_SCHEMA_VERSION: Final = "logic-conformance-fixture/v1"

DEFAULT_MAX_PAYLOAD_BYTES: Final = 1_048_576
DEFAULT_MAX_FIXTURES: Final = 65_536
DEFAULT_MAX_INLINE_PAYLOAD_CHARS: Final = 65_536

_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_BARE_DIGEST_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_FIXTURE_ID_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_LICENSE_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")

_DATASETS_ROOT: Final = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH: Final = (
    _DATASETS_ROOT / "tests" / "fixtures" / "logic_conformance" / "manifest.json"
)

_MANIFEST_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "corpus_id",
        "description",
        "fixtures",
        "interface",
        "max_fixtures",
        "max_payload_bytes",
        "objective",
        "schema_version",
        "task",
        "version",
    }
)

_FIXTURE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "authority",
        "content_digest",
        "expected_diagnostics",
        "expected_disposition",
        "family_id",
        "family_label",
        "fixture_id",
        "kind",
        "label_disposition",
        "license",
        "media_type",
        "notation",
        "path",
        "payload",
        "profile",
        "schema_version",
        "size_bytes",
        "source",
    }
)


class CorpusError(ValueError):
    """Raised when a conformance corpus or fixture is malformed."""


class CorpusIntegrityError(CorpusError):
    """Raised when a corpus fails integrity or safety checks."""


class FixtureKind(StrEnum):
    """Closed vocabulary of corpus fixture kinds (LFP-002)."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    AMBIGUOUS = "ambiguous"
    ADVERSARIAL = "adversarial"
    TRANSLATION = "translation"
    MODEL = "model"
    PROOF = "proof"
    TRACE = "trace"


class ExpectedDisposition(StrEnum):
    """Expected parser/pipeline disposition for a fixture."""

    ACCEPT = "accept"
    REJECT = "reject"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class LabelDisposition(StrEnum):
    """How an observed family label relates to the baseline registry."""

    CANONICAL = "canonical"
    ALIAS = "alias"
    UNKNOWN = "unknown"


REQUIRED_FIXTURE_KINDS: Final[frozenset[str]] = frozenset(
    kind.value for kind in FixtureKind
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    """Return ``sha256:<hex>`` for raw bytes."""

    if not isinstance(data, (bytes, bytearray)):
        raise CorpusError("digest input must be bytes")
    return "sha256:" + hashlib.sha256(bytes(data)).hexdigest()


def digest_text(text: str, *, encoding: str = "utf-8") -> str:
    """Return ``sha256:<hex>`` for Unicode text."""

    if not isinstance(text, str):
        raise CorpusError("digest text input must be a string")
    return digest_bytes(text.encode(encoding))


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CorpusError(f"{label} must be a mapping")
    return value


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CorpusError(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise CorpusError(f"{field_name} must not contain NUL bytes")
    return value


def _optional_text(value: Any, field_name: str) -> str:
    if value in (None, ""):
        return ""
    return _require_text(value, field_name)


def _require_digest(value: Any, field_name: str) -> str:
    digest = _require_text(value, field_name)
    if _BARE_DIGEST_RE.fullmatch(digest):
        digest = f"sha256:{digest}"
    if not _DIGEST_RE.fullmatch(digest):
        raise CorpusError(f"{field_name} must be a sha256:<hex> digest")
    return digest


def _require_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CorpusError(f"{field_name} must be an int")
    if value < 0:
        raise CorpusError(f"{field_name} must be a non-negative int")
    return value


def _require_positive_int(value: Any, field_name: str) -> int:
    number = _require_non_negative_int(value, field_name)
    if number <= 0:
        raise CorpusError(f"{field_name} must be a positive int")
    return number


def _require_fixture_id(value: Any, field_name: str = "fixture_id") -> str:
    text = _require_text(value, field_name)
    if not _FIXTURE_ID_RE.fullmatch(text):
        raise CorpusError(
            f"{field_name} must be a lowercase identifier "
            "(letters, digits, underscore)"
        )
    return text


def _parse_enum(
    value: Any,
    enum_cls: type[StrEnum],
    field_name: str,
) -> StrEnum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_cls)
        raise CorpusError(f"{field_name} must be one of: {allowed}") from exc


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], record_name: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise CorpusError(
            f"unknown {record_name} field(s): {', '.join(unknown)}"
        )


def require_safe_relative_path(value: Any, field_name: str = "path") -> str:
    """Require a root-relative POSIX path with no traversal segments."""

    path = _require_text(value, field_name)
    if "\\" in path or "\x00" in path:
        raise CorpusIntegrityError(
            f"{field_name} must be a root-relative POSIX path without "
            f"backslashes or null bytes (unsafe path rejected): {path!r}"
        )
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise CorpusIntegrityError(
            f"{field_name} must be root-relative and contain no '.'/'..' "
            f"segments (unsafe path rejected): {path!r}"
        )
    normalized = pure.as_posix()
    if normalized != path:
        raise CorpusIntegrityError(
            f"{field_name} must be normalized POSIX text "
            f"(unsafe path rejected): {path!r}"
        )
    return path


def resolve_label_disposition(
    family_label: str,
    *,
    registry: LogicFamilyRegistry | None = None,
) -> tuple[LabelDisposition, str | None]:
    """Classify an observed family label against the baseline registry.

    Unknown labels are preserved losslessly: the original string is never
    rewritten, and the disposition is explicitly :attr:`LabelDisposition.UNKNOWN`.
    """

    label = _require_text(family_label, "family_label")
    active = registry if registry is not None else DEFAULT_REGISTRY
    try:
        descriptor = active.resolve(label)
        normalized_input = normalize_family_name(label)
    except (UnknownDescriptorError, LogicFamilyRegistryError, ValueError):
        # Preserve free-form observed labels losslessly for LFP-003/LFP-010.
        return LabelDisposition.UNKNOWN, None

    if normalized_input == normalize_family_name(descriptor.family_id):
        return LabelDisposition.CANONICAL, descriptor.family_id
    return LabelDisposition.ALIAS, descriptor.family_id


def _normalize_payload(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        if "\x00" in value:
            raise CorpusError("payload must not contain NUL bytes")
        if len(value) > DEFAULT_MAX_INLINE_PAYLOAD_CHARS:
            raise CorpusIntegrityError(
                f"inline payload exceeds max of "
                f"{DEFAULT_MAX_INLINE_PAYLOAD_CHARS} characters "
                "(unbounded payload rejected)"
            )
        return value
    if isinstance(value, (dict, list)):
        encoded = _canonical_bytes(value).decode("utf-8")
        if len(encoded) > DEFAULT_MAX_INLINE_PAYLOAD_CHARS:
            raise CorpusIntegrityError(
                f"inline payload exceeds max of "
                f"{DEFAULT_MAX_INLINE_PAYLOAD_CHARS} characters "
                "(unbounded payload rejected)"
            )
        return encoded
    raise CorpusError("payload must be a string or JSON object/array")


def _normalize_diagnostics(value: Any) -> tuple[str, ...]:
    if value in (None, ()):
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise CorpusError("expected_diagnostics must be a sequence of strings")
    items = tuple(_require_text(item, "expected_diagnostics item") for item in value)
    if len(set(items)) != len(items):
        raise CorpusError("expected_diagnostics must not contain duplicates")
    return items


@dataclass(frozen=True, slots=True)
class ConformanceFixture:
    """One content-addressed fixture in the cross-family corpus."""

    fixture_id: str
    kind: FixtureKind | str
    path: str
    content_digest: str
    size_bytes: int
    family_label: str
    expected_disposition: ExpectedDisposition | str
    source: str
    license: str
    label_disposition: LabelDisposition | str = LabelDisposition.UNKNOWN
    family_id: str | None = None
    profile: str = ""
    notation: str = ""
    authority: str = ""
    media_type: str = ""
    payload: str = ""
    expected_diagnostics: tuple[str, ...] | Sequence[str] = ()
    schema_version: str = FIXTURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fixture_id", _require_fixture_id(self.fixture_id)
        )
        object.__setattr__(
            self, "kind", _parse_enum(self.kind, FixtureKind, "kind")
        )
        object.__setattr__(
            self, "path", require_safe_relative_path(self.path, "path")
        )
        if self.content_digest in (None, ""):
            raise CorpusError(
                f"fixture {self.fixture_id!r} is missing content_digest "
                "(missing digests rejected)"
            )
        object.__setattr__(
            self,
            "content_digest",
            _require_digest(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "size_bytes",
            _require_non_negative_int(self.size_bytes, "size_bytes"),
        )
        object.__setattr__(
            self,
            "family_label",
            _require_text(self.family_label, "family_label"),
        )
        if self.expected_disposition in (None, ""):
            raise CorpusError(
                f"fixture {self.fixture_id!r} is missing expected_disposition "
                "(fixtures without expected disposition rejected)"
            )
        object.__setattr__(
            self,
            "expected_disposition",
            _parse_enum(
                self.expected_disposition,
                ExpectedDisposition,
                "expected_disposition",
            ),
        )
        object.__setattr__(self, "source", _require_text(self.source, "source"))
        license_id = _require_text(self.license, "license")
        if not _LICENSE_RE.fullmatch(license_id):
            raise CorpusError(f"license must be a compact license id: {license_id!r}")
        object.__setattr__(self, "license", license_id)
        object.__setattr__(
            self,
            "label_disposition",
            _parse_enum(
                self.label_disposition, LabelDisposition, "label_disposition"
            ),
        )
        family_id = self.family_id
        if family_id in (None, ""):
            object.__setattr__(self, "family_id", None)
        else:
            object.__setattr__(
                self, "family_id", _require_text(family_id, "family_id")
            )
        object.__setattr__(self, "profile", _optional_text(self.profile, "profile"))
        object.__setattr__(
            self, "notation", _optional_text(self.notation, "notation")
        )
        object.__setattr__(
            self, "authority", _optional_text(self.authority, "authority")
        )
        object.__setattr__(
            self, "media_type", _optional_text(self.media_type, "media_type")
        )
        object.__setattr__(self, "payload", _normalize_payload(self.payload))
        object.__setattr__(
            self,
            "expected_diagnostics",
            _normalize_diagnostics(self.expected_diagnostics),
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != FIXTURE_SCHEMA_VERSION:
            raise CorpusError(
                f"fixture schema_version must be {FIXTURE_SCHEMA_VERSION!r}"
            )
        if self.payload:
            payload_bytes = self.payload.encode("utf-8")
            if len(payload_bytes) != self.size_bytes:
                raise CorpusIntegrityError(
                    f"fixture {self.fixture_id!r} size_bytes "
                    f"{self.size_bytes} does not match payload byte length "
                    f"{len(payload_bytes)}"
                )
            expected = digest_bytes(payload_bytes)
            if self.content_digest != expected:
                raise CorpusIntegrityError(
                    f"fixture {self.fixture_id!r} content_digest does not "
                    "match payload"
                )
        if (
            self.label_disposition is LabelDisposition.UNKNOWN
            and self.family_id is not None
        ):
            raise CorpusIntegrityError(
                f"fixture {self.fixture_id!r} has unknown label disposition "
                "but set family_id; unknown labels must not invent a family_id"
            )
        if (
            self.label_disposition is not LabelDisposition.UNKNOWN
            and not self.family_id
        ):
            raise CorpusIntegrityError(
                f"fixture {self.fixture_id!r} has {self.label_disposition.value} "
                "label disposition but missing family_id"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready fixture record."""

        record: dict[str, Any] = {
            "authority": self.authority,
            "content_digest": self.content_digest,
            "expected_diagnostics": list(self.expected_diagnostics),
            "expected_disposition": self.expected_disposition.value
            if isinstance(self.expected_disposition, ExpectedDisposition)
            else self.expected_disposition,
            "family_id": self.family_id,
            "family_label": self.family_label,
            "fixture_id": self.fixture_id,
            "kind": self.kind.value
            if isinstance(self.kind, FixtureKind)
            else self.kind,
            "label_disposition": self.label_disposition.value
            if isinstance(self.label_disposition, LabelDisposition)
            else self.label_disposition,
            "license": self.license,
            "media_type": self.media_type,
            "notation": self.notation,
            "path": self.path,
            "profile": self.profile,
            "schema_version": self.schema_version,
            "size_bytes": self.size_bytes,
            "source": self.source,
        }
        if self.payload:
            record["payload"] = self.payload
        return record

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        registry: LogicFamilyRegistry | None = None,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        enforce_label_registry: bool = True,
    ) -> ConformanceFixture:
        """Parse and validate one fixture mapping."""

        payload = _as_mapping(value, "fixture")
        _reject_unknown(payload, _FIXTURE_FIELDS, "fixture")

        family_label = _require_text(payload.get("family_label"), "family_label")
        declared_disposition = payload.get("label_disposition")
        declared_family_id = payload.get("family_id")

        if enforce_label_registry:
            resolved_disposition, resolved_family_id = resolve_label_disposition(
                family_label, registry=registry
            )
            if declared_disposition not in (None, ""):
                parsed = _parse_enum(
                    declared_disposition, LabelDisposition, "label_disposition"
                )
                if parsed is not resolved_disposition:
                    # Preserve unknown labels losslessly; do not silently
                    # promote them. Mismatches for known labels fail closed.
                    if resolved_disposition is LabelDisposition.UNKNOWN:
                        if parsed is not LabelDisposition.UNKNOWN:
                            raise CorpusIntegrityError(
                                f"family_label {family_label!r} is unknown to "
                                "the baseline registry and must use "
                                "label_disposition='unknown'"
                            )
                    else:
                        raise CorpusIntegrityError(
                            f"family_label {family_label!r} resolves as "
                            f"{resolved_disposition.value}, not "
                            f"{parsed.value}"
                        )
            label_disposition = resolved_disposition
            family_id = resolved_family_id
            if (
                declared_family_id not in (None, "")
                and resolved_family_id is not None
                and declared_family_id != resolved_family_id
            ):
                raise CorpusIntegrityError(
                    f"family_id {declared_family_id!r} does not match registry "
                    f"resolution {resolved_family_id!r} for label "
                    f"{family_label!r}"
                )
            if (
                resolved_disposition is LabelDisposition.UNKNOWN
                and declared_family_id not in (None, "")
            ):
                raise CorpusIntegrityError(
                    f"unknown family_label {family_label!r} must not invent "
                    f"family_id {declared_family_id!r}"
                )
        else:
            label_disposition = declared_disposition or LabelDisposition.UNKNOWN
            family_id = declared_family_id

        size_bytes = _require_non_negative_int(
            payload.get("size_bytes"), "size_bytes"
        )
        if size_bytes > max_payload_bytes:
            raise CorpusIntegrityError(
                f"fixture size_bytes {size_bytes} exceeds max_payload_bytes "
                f"{max_payload_bytes} (unbounded payload rejected)"
            )

        fixture = cls(
            fixture_id=payload.get("fixture_id"),
            kind=payload.get("kind"),
            path=payload.get("path"),
            content_digest=payload.get("content_digest"),
            size_bytes=size_bytes,
            family_label=family_label,
            expected_disposition=payload.get("expected_disposition"),
            source=payload.get("source"),
            license=payload.get("license"),
            label_disposition=label_disposition,
            family_id=family_id,
            profile=payload.get("profile", ""),
            notation=payload.get("notation", ""),
            authority=payload.get("authority", ""),
            media_type=payload.get("media_type", ""),
            payload=payload.get("payload", ""),
            expected_diagnostics=payload.get("expected_diagnostics", ()),
            schema_version=payload.get(
                "schema_version", FIXTURE_SCHEMA_VERSION
            ),
        )
        return fixture


@dataclass(frozen=True, slots=True)
class LogicConformanceCorpus:
    """Versioned, fail-closed cross-family conformance corpus manifest."""

    corpus_id: str
    version: str
    fixtures: tuple[ConformanceFixture, ...] | Sequence[ConformanceFixture] = ()
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
    max_fixtures: int = DEFAULT_MAX_FIXTURES
    description: str = ""
    objective: str = "LFP-G010"
    task: str = "LFP-002"
    interface: str = LOGIC_CONFORMANCE_CORPUS_INTERFACE
    schema_version: str = LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "corpus_id", _require_text(self.corpus_id, "corpus_id")
        )
        object.__setattr__(
            self, "version", _require_text(self.version, "version")
        )
        object.__setattr__(
            self,
            "max_payload_bytes",
            _require_positive_int(self.max_payload_bytes, "max_payload_bytes"),
        )
        object.__setattr__(
            self,
            "max_fixtures",
            _require_positive_int(self.max_fixtures, "max_fixtures"),
        )
        object.__setattr__(
            self, "description", _optional_text(self.description, "description")
        )
        object.__setattr__(
            self, "objective", _optional_text(self.objective, "objective")
        )
        object.__setattr__(self, "task", _optional_text(self.task, "task"))
        object.__setattr__(
            self,
            "interface",
            _require_text(self.interface, "interface"),
        )
        if self.interface != LOGIC_CONFORMANCE_CORPUS_INTERFACE:
            raise CorpusError(
                f"interface must be {LOGIC_CONFORMANCE_CORPUS_INTERFACE!r}"
            )
        object.__setattr__(
            self,
            "schema_version",
            _require_text(self.schema_version, "schema_version"),
        )
        if self.schema_version != LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION:
            raise CorpusError(
                f"schema_version must be "
                f"{LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION!r}"
            )

        if isinstance(self.fixtures, (str, bytes, bytearray)) or not isinstance(
            self.fixtures, Sequence
        ):
            raise CorpusError("fixtures must be a sequence")
        normalized = tuple(self.fixtures)
        if len(normalized) > self.max_fixtures:
            raise CorpusIntegrityError(
                f"fixture count {len(normalized)} exceeds max_fixtures "
                f"{self.max_fixtures}"
            )
        seen_ids: set[str] = set()
        for fixture in normalized:
            if not isinstance(fixture, ConformanceFixture):
                raise CorpusError(
                    "fixtures must contain ConformanceFixture instances"
                )
            if fixture.fixture_id in seen_ids:
                raise CorpusIntegrityError(
                    f"duplicate fixture_id {fixture.fixture_id!r} "
                    "(duplicate IDs rejected)"
                )
            seen_ids.add(fixture.fixture_id)
            if fixture.size_bytes > self.max_payload_bytes:
                raise CorpusIntegrityError(
                    f"fixture {fixture.fixture_id!r} size_bytes "
                    f"{fixture.size_bytes} exceeds max_payload_bytes "
                    f"{self.max_payload_bytes} (unbounded payload rejected)"
                )
        object.__setattr__(self, "fixtures", normalized)

    def __iter__(self) -> Iterator[ConformanceFixture]:
        return iter(self.fixtures)

    def __len__(self) -> int:
        return len(self.fixtures)

    def get(self, fixture_id: str) -> ConformanceFixture:
        """Return a fixture by id or raise :class:`KeyError`."""

        for fixture in self.fixtures:
            if fixture.fixture_id == fixture_id:
                return fixture
        raise KeyError(fixture_id)

    def by_kind(self, kind: FixtureKind | str) -> tuple[ConformanceFixture, ...]:
        """Return fixtures of one kind, ordered as in the manifest."""

        wanted = _parse_enum(kind, FixtureKind, "kind")
        return tuple(item for item in self.fixtures if item.kind is wanted)

    def unknown_labels(self) -> tuple[str, ...]:
        """Return preserved observed labels with unknown disposition."""

        labels = [
            fixture.family_label
            for fixture in self.fixtures
            if fixture.label_disposition is LabelDisposition.UNKNOWN
        ]
        # Stable unique order preserving first occurrence.
        seen: set[str] = set()
        ordered: list[str] = []
        for label in labels:
            if label not in seen:
                seen.add(label)
                ordered.append(label)
        return tuple(ordered)

    def covered_kinds(self) -> frozenset[str]:
        return frozenset(
            fixture.kind.value
            if isinstance(fixture.kind, FixtureKind)
            else str(fixture.kind)
            for fixture in self.fixtures
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready manifest document."""

        return {
            "corpus_id": self.corpus_id,
            "description": self.description,
            "fixtures": [fixture.to_dict() for fixture in self.fixtures],
            "interface": self.interface,
            "max_fixtures": self.max_fixtures,
            "max_payload_bytes": self.max_payload_bytes,
            "objective": self.objective,
            "schema_version": self.schema_version,
            "task": self.task,
            "version": self.version,
        }

    def content_digest(self) -> str:
        """Deterministic digest of the canonical manifest document."""

        return digest_bytes(_canonical_bytes(self.to_dict()))

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        registry: LogicFamilyRegistry | None = None,
        enforce_label_registry: bool = True,
    ) -> LogicConformanceCorpus:
        """Parse and validate a full corpus manifest mapping."""

        payload = _as_mapping(value, "manifest")
        _reject_unknown(payload, _MANIFEST_FIELDS, "manifest")

        max_payload_bytes = _require_positive_int(
            payload.get("max_payload_bytes", DEFAULT_MAX_PAYLOAD_BYTES),
            "max_payload_bytes",
        )
        max_fixtures = _require_positive_int(
            payload.get("max_fixtures", DEFAULT_MAX_FIXTURES),
            "max_fixtures",
        )
        raw_fixtures = payload.get("fixtures", [])
        if isinstance(raw_fixtures, (str, bytes, bytearray)) or not isinstance(
            raw_fixtures, Sequence
        ):
            raise CorpusError("fixtures must be a sequence")
        if len(raw_fixtures) > max_fixtures:
            raise CorpusIntegrityError(
                f"fixture count {len(raw_fixtures)} exceeds max_fixtures "
                f"{max_fixtures}"
            )

        fixtures: list[ConformanceFixture] = []
        for index, item in enumerate(raw_fixtures):
            try:
                fixtures.append(
                    ConformanceFixture.from_dict(
                        item,
                        registry=registry,
                        max_payload_bytes=max_payload_bytes,
                        enforce_label_registry=enforce_label_registry,
                    )
                )
            except CorpusError as exc:
                raise CorpusError(
                    f"fixtures[{index}]: {exc}"
                ) from exc

        return cls(
            corpus_id=payload.get("corpus_id"),
            version=payload.get("version"),
            fixtures=fixtures,
            max_payload_bytes=max_payload_bytes,
            max_fixtures=max_fixtures,
            description=payload.get("description", ""),
            objective=payload.get("objective", "LFP-G010"),
            task=payload.get("task", "LFP-002"),
            interface=payload.get(
                "interface", LOGIC_CONFORMANCE_CORPUS_INTERFACE
            ),
            schema_version=payload.get(
                "schema_version", LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION
            ),
        )


def build_fixture(
    *,
    fixture_id: str,
    kind: FixtureKind | str,
    path: str,
    family_label: str,
    expected_disposition: ExpectedDisposition | str,
    source: str,
    license: str,
    payload: str | Mapping[str, Any] | Sequence[Any] | None = None,
    content_digest: str | None = None,
    size_bytes: int | None = None,
    profile: str = "",
    notation: str = "",
    authority: str = "",
    media_type: str = "",
    expected_diagnostics: Sequence[str] = (),
    registry: LogicFamilyRegistry | None = None,
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
) -> ConformanceFixture:
    """Build a validated fixture, computing digest/size from payload when given."""

    normalized_payload = _normalize_payload(payload)
    if normalized_payload:
        payload_bytes = normalized_payload.encode("utf-8")
        computed_size = len(payload_bytes)
        computed_digest = digest_bytes(payload_bytes)
        if size_bytes is not None and size_bytes != computed_size:
            raise CorpusIntegrityError(
                f"size_bytes {size_bytes} does not match payload length "
                f"{computed_size}"
            )
        if content_digest is not None:
            normalized_digest = _require_digest(content_digest, "content_digest")
            if normalized_digest != computed_digest:
                raise CorpusIntegrityError(
                    "content_digest does not match payload"
                )
        size_bytes = computed_size
        content_digest = computed_digest
    else:
        if content_digest in (None, ""):
            raise CorpusError(
                "content_digest is required when payload is absent "
                "(missing digests rejected)"
            )
        if size_bytes is None:
            raise CorpusError(
                "size_bytes is required when payload is absent"
            )
        content_digest = _require_digest(content_digest, "content_digest")
        size_bytes = _require_non_negative_int(size_bytes, "size_bytes")

    if size_bytes > max_payload_bytes:
        raise CorpusIntegrityError(
            f"size_bytes {size_bytes} exceeds max_payload_bytes "
            f"{max_payload_bytes} (unbounded payload rejected)"
        )

    label_disposition, family_id = resolve_label_disposition(
        family_label, registry=registry
    )
    return ConformanceFixture(
        fixture_id=fixture_id,
        kind=kind,
        path=path,
        content_digest=content_digest,
        size_bytes=size_bytes,
        family_label=family_label,
        expected_disposition=expected_disposition,
        source=source,
        license=license,
        label_disposition=label_disposition,
        family_id=family_id,
        profile=profile,
        notation=notation,
        authority=authority,
        media_type=media_type,
        payload=normalized_payload,
        expected_diagnostics=expected_diagnostics,
    )


def build_corpus(
    *,
    corpus_id: str,
    version: str,
    fixtures: Iterable[ConformanceFixture],
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    max_fixtures: int = DEFAULT_MAX_FIXTURES,
    description: str = "",
    objective: str = "LFP-G010",
    task: str = "LFP-002",
) -> LogicConformanceCorpus:
    """Build a validated corpus from fixture records."""

    return LogicConformanceCorpus(
        corpus_id=corpus_id,
        version=version,
        fixtures=tuple(fixtures),
        max_payload_bytes=max_payload_bytes,
        max_fixtures=max_fixtures,
        description=description,
        objective=objective,
        task=task,
    )


def load_corpus(
    path: str | Path | None = None,
    *,
    registry: LogicFamilyRegistry | None = None,
    enforce_label_registry: bool = True,
) -> LogicConformanceCorpus:
    """Load and validate a corpus manifest from disk."""

    manifest_path = Path(path) if path is not None else DEFAULT_MANIFEST_PATH
    if not manifest_path.is_file():
        raise CorpusError(f"corpus manifest not found: {manifest_path}")
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusError(
            f"corpus manifest is not valid JSON: {manifest_path}"
        ) from exc
    return LogicConformanceCorpus.from_dict(
        document,
        registry=registry,
        enforce_label_registry=enforce_label_registry,
    )


def validate_corpus(
    value: Mapping[str, Any] | LogicConformanceCorpus,
    *,
    registry: LogicFamilyRegistry | None = None,
    enforce_label_registry: bool = True,
    require_all_kinds: bool = False,
) -> LogicConformanceCorpus:
    """Validate a corpus mapping or instance and optionally require kind coverage."""

    if isinstance(value, LogicConformanceCorpus):
        corpus = value
        # Re-run fixture size bounds against the instance max.
        for fixture in corpus.fixtures:
            if fixture.size_bytes > corpus.max_payload_bytes:
                raise CorpusIntegrityError(
                    f"fixture {fixture.fixture_id!r} size_bytes "
                    f"{fixture.size_bytes} exceeds max_payload_bytes "
                    f"{corpus.max_payload_bytes} (unbounded payload rejected)"
                )
    else:
        corpus = LogicConformanceCorpus.from_dict(
            value,
            registry=registry,
            enforce_label_registry=enforce_label_registry,
        )
    if require_all_kinds:
        missing = sorted(REQUIRED_FIXTURE_KINDS - corpus.covered_kinds())
        if missing:
            raise CorpusIntegrityError(
                "corpus is missing required fixture kinds: "
                + ", ".join(missing)
            )
    return corpus


def default_manifest_path() -> Path:
    """Return the frozen repository fixture path for this corpus."""

    return DEFAULT_MANIFEST_PATH


# Stable public surface for LogicConformanceCorpus@1.
__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "DEFAULT_MAX_FIXTURES",
    "DEFAULT_MAX_PAYLOAD_BYTES",
    "FIXTURE_SCHEMA_VERSION",
    "LOGIC_CONFORMANCE_CORPUS_INTERFACE",
    "LOGIC_CONFORMANCE_CORPUS_SCHEMA_VERSION",
    "REQUIRED_FIXTURE_KINDS",
    "ConformanceFixture",
    "CorpusError",
    "CorpusIntegrityError",
    "ExpectedDisposition",
    "FixtureKind",
    "LabelDisposition",
    "LogicConformanceCorpus",
    "build_corpus",
    "build_fixture",
    "default_manifest_path",
    "digest_bytes",
    "digest_text",
    "load_corpus",
    "require_safe_relative_path",
    "resolve_label_disposition",
    "validate_corpus",
]
