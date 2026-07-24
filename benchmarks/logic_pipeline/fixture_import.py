"""Strict adapters for reusing existing logic regression fixtures.

The benchmark does not copy or reinterpret expected results.  Instead, a
reviewed import manifest selects records from existing repository fixtures and
binds both the source-file bytes and the selected record's canonical JSON.
Loading is dependency-free and fail-closed: provenance drift, ambiguous
selectors, duplicate JSON keys, field drift, path traversal, and any assertion
of model-generated expected results invalidate the complete import set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Final, Mapping, Self, TypeVar


FIXTURE_IMPORT_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.fixture-import.v1"
)
FIXTURE_IMPORT_MANIFEST_SCHEMA: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.fixture-import-manifest.v1"
)
FIXTURE_IMPORT_MANIFEST_ID: Final = "existing-logic-regressions-v1"
FIXTURE_IMPORT_VERSION: Final = 1
DEFAULT_REPOSITORY_ROOT: Final = Path(__file__).parents[2]
DEFAULT_IMPORT_MANIFEST_PATH: Final = (
    DEFAULT_REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "logic_pipeline_benchmark"
    / "fixture_import_manifest.json"
)
# This digest binds the reviewed adapter membership, order, selectors, source
# identities, and expected-result attestations.  It is intentionally code-pinned
# so rewriting a source and its manifest digests together still fails closed.
FROZEN_IMPORT_MANIFEST_SHA256: Final = (
    "93bc8297c84b85a018305edc311c42d0df345978af767e4b93b1e509d974a0fd"
)

_SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_FIELD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_PATH = re.compile(r"[A-Za-z0-9._/-]{1,512}\Z")
_MODEL_ORIGIN_KEYS: Final = frozenset(
    {
        "generated_by_model",
        "llm_generated",
        "model_generated",
        "model_generated_expected_result",
        "model_generated_ground_truth",
        "model_output_used",
    }
)
_EnumT = TypeVar("_EnumT", bound=Enum)


class FixtureImportError(ValueError):
    """Raised when imported fixture provenance or content is not trustworthy."""


class FixtureFamily(str, Enum):
    """Required existing-fixture families represented by the adapter."""

    LEGAL_IR_AMBIGUITY = "legal_ir_ambiguity"
    FOL_DEONTIC_MODAL = "fol_deontic_modal"
    HAMMER = "hammer"
    LEANSTRAL = "leanstral"


class Coverage(str, Enum):
    """Whether a source record is expected to succeed or reject/regress."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class SourceFormat(str, Enum):
    JSON = "json"
    JSONL = "jsonl"


def HSSLEV0217E25() -> str:
    """Return AST-verifiable evidence for provenance-preserving reuse."""

    return "provenance-preserving existing regression and ambiguity fixture imports"


def canonical_json(value: object) -> str:
    """Return the deterministic JSON representation used by record digests."""

    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _duplicate_rejecting_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FixtureImportError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise FixtureImportError(f"non-finite JSON number is forbidden: {value}")


def _decode_json(text: str, context: str) -> object:
    try:
        return json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_constant,
        )
    except FixtureImportError:
        raise
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise FixtureImportError(f"{context} is not valid strict JSON: {exc}") from exc


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise FixtureImportError(f"{field_name} must be a JSON object")
    return value


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field_name: str,
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append(f"missing {sorted(missing)!r}")
        if unknown:
            details.append(f"unknown {sorted(unknown)!r}")
        raise FixtureImportError(
            f"{field_name} fields invalid: {', '.join(details)}"
        )


def _nonempty(value: object, field_name: str, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise FixtureImportError(
            f"{field_name} must be a nonempty bounded string without "
            "edge whitespace or control characters"
        )
    return value


def _safe_id(value: object, field_name: str) -> str:
    result = _nonempty(value, field_name, maximum=128)
    if not _SAFE_ID.fullmatch(result):
        raise FixtureImportError(f"{field_name} must be a safe lowercase identifier")
    return result


def _field_name(value: object, field_name: str) -> str:
    result = _nonempty(value, field_name, maximum=128)
    if not _FIELD_NAME.fullmatch(result):
        raise FixtureImportError(f"{field_name} must be a safe JSON field name")
    return result


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise FixtureImportError(f"{field_name} must be a lowercase SHA-256")
    return value


def _integer(value: object, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FixtureImportError(f"{field_name} must be an integer >= {minimum}")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise FixtureImportError(f"{field_name} must be a boolean")
    return value


def _enum(
    enum_type: type[_EnumT],
    value: object,
    field_name: str,
) -> _EnumT:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise FixtureImportError(f"{field_name} has an unsupported value") from exc


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise FixtureImportError(f"{field_name} must be an array")
    result = tuple(
        _nonempty(item, f"{field_name}[]", maximum=128) for item in value
    )
    if len(result) != len(set(result)):
        raise FixtureImportError(f"{field_name} must not contain duplicates")
    return result


def _freeze_json(value: object, field_name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FixtureImportError(f"{field_name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise FixtureImportError(f"{field_name} contains a non-string key")
        return MappingProxyType(
            {
                key: _freeze_json(item, f"{field_name}.{key}")
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{field_name}[]") for item in value
        )
    raise FixtureImportError(
        f"{field_name} contains unsupported value {type(value).__name__}"
    )


def _thaw_json(value: object) -> object:
    """Return JSON-native containers for canonical serialization."""

    if isinstance(value, Mapping):
        return {
            key: _thaw_json(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _contains_model_origin(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                key.casefold() in _MODEL_ORIGIN_KEYS
                and item is not False
                and item is not None
            ):
                return True
            if _contains_model_origin(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_model_origin(item) for item in value)
    return False


def _source_path(value: object) -> str:
    result = _nonempty(value, "source_path")
    if (
        not _SOURCE_PATH.fullmatch(result)
        or "\\" in result
        or result.startswith("/")
    ):
        raise FixtureImportError("source_path must be a safe relative POSIX path")
    pure_path = PurePosixPath(result)
    if any(part in {"", ".", ".."} for part in pure_path.parts):
        raise FixtureImportError("source_path must not contain traversal segments")
    return result


@dataclass(frozen=True, slots=True)
class FixtureImportSpec:
    """A digest-bound selector for one record in an existing source fixture."""

    ordinal: int
    import_id: str
    family: FixtureFamily
    coverage: Coverage
    semantic_tags: tuple[str, ...]
    source_path: str
    source_format: SourceFormat
    collection_path: tuple[str, ...]
    identity_field: str
    original_id: str
    source_reference: str
    source_sha256: str
    record_sha256: str
    expected_result_origin: str
    model_generated_expected_result: bool

    def __post_init__(self) -> None:
        _integer(self.ordinal, "ordinal")
        _safe_id(self.import_id, "import_id")
        if not isinstance(self.family, FixtureFamily):
            raise FixtureImportError("family must be a FixtureFamily")
        if not isinstance(self.coverage, Coverage):
            raise FixtureImportError("coverage must be a Coverage")
        if (
            not isinstance(self.semantic_tags, tuple)
            or not self.semantic_tags
            or len(set(self.semantic_tags)) != len(self.semantic_tags)
        ):
            raise FixtureImportError("semantic_tags must be nonempty and unique")
        for tag in self.semantic_tags:
            _safe_id(tag, "semantic_tags[]")
        _source_path(self.source_path)
        if not isinstance(self.source_format, SourceFormat):
            raise FixtureImportError("source_format must be a SourceFormat")
        if not isinstance(self.collection_path, tuple):
            raise FixtureImportError("collection_path must be an immutable tuple")
        for component in self.collection_path:
            _field_name(component, "collection_path[]")
        _field_name(self.identity_field, "identity_field")
        _nonempty(self.original_id, "original_id", maximum=256)
        expected_reference = (
            f"{self.source_path}#{self.identity_field}={self.original_id}"
        )
        if self.source_reference != expected_reference:
            raise FixtureImportError(
                "source_reference must preserve the exact source selector"
            )
        _digest(self.source_sha256, "source_sha256")
        _digest(self.record_sha256, "record_sha256")
        if self.expected_result_origin != "existing_fixture":
            raise FixtureImportError(
                "expected_result_origin must be existing_fixture"
            )
        if type(self.model_generated_expected_result) is not bool:
            raise FixtureImportError(
                "model_generated_expected_result must be a boolean"
            )
        if self.model_generated_expected_result:
            raise FixtureImportError(
                "model-generated expected results are forbidden"
            )

    def to_dict(self) -> dict[str, object]:
        """Return the canonical JSON-native import descriptor."""

        return _spec_to_dict(self)

    @classmethod
    def from_mapping(cls, value: object) -> Self:
        record = _mapping(value, "import")
        _exact_keys(
            record,
            {
                "collection_path",
                "coverage",
                "expected_result_origin",
                "family",
                "identity_field",
                "import_id",
                "model_generated_expected_result",
                "ordinal",
                "original_id",
                "record_sha256",
                "schema",
                "semantic_tags",
                "source_format",
                "source_path",
                "source_reference",
                "source_sha256",
            },
            "import",
        )
        if record["schema"] != FIXTURE_IMPORT_SCHEMA:
            raise FixtureImportError("import schema is unsupported")
        return cls(
            ordinal=_integer(record["ordinal"], "ordinal"),
            import_id=_safe_id(record["import_id"], "import_id"),
            family=_enum(FixtureFamily, record["family"], "family"),
            coverage=_enum(Coverage, record["coverage"], "coverage"),
            semantic_tags=_string_tuple(record["semantic_tags"], "semantic_tags"),
            source_path=_source_path(record["source_path"]),
            source_format=_enum(
                SourceFormat, record["source_format"], "source_format"
            ),
            collection_path=tuple(
                _field_name(item, "collection_path[]")
                for item in _string_tuple(
                    record["collection_path"], "collection_path"
                )
            ),
            identity_field=_field_name(
                record["identity_field"], "identity_field"
            ),
            original_id=_nonempty(
                record["original_id"], "original_id", maximum=256
            ),
            source_reference=_nonempty(
                record["source_reference"], "source_reference"
            ),
            source_sha256=_digest(record["source_sha256"], "source_sha256"),
            record_sha256=_digest(record["record_sha256"], "record_sha256"),
            expected_result_origin=_nonempty(
                record["expected_result_origin"], "expected_result_origin"
            ),
            model_generated_expected_result=_boolean(
                record["model_generated_expected_result"],
                "model_generated_expected_result",
            ),
        )


@dataclass(frozen=True, slots=True)
class FixtureImportManifest:
    """Reviewed, immutable membership and coverage contract."""

    manifest_id: str
    version: int
    import_count: int
    family_counts: Mapping[str, int]
    coverage_counts: Mapping[str, int]
    imports_sha256: str
    imports: tuple[FixtureImportSpec, ...]

    def __post_init__(self) -> None:
        if self.manifest_id != FIXTURE_IMPORT_MANIFEST_ID:
            raise FixtureImportError("manifest_id is unsupported")
        if self.version != FIXTURE_IMPORT_VERSION:
            raise FixtureImportError("manifest version is unsupported")
        if not isinstance(self.imports, tuple) or not all(
            isinstance(item, FixtureImportSpec) for item in self.imports
        ):
            raise FixtureImportError(
                "imports must be an immutable tuple of FixtureImportSpec records"
            )
        family_counts = _count_mapping(
            self.family_counts,
            {family.value for family in FixtureFamily},
            "family_counts",
        )
        coverage_counts = _count_mapping(
            self.coverage_counts,
            {coverage.value for coverage in Coverage},
            "coverage_counts",
        )
        object.__setattr__(
            self,
            "family_counts",
            MappingProxyType(family_counts),
        )
        object.__setattr__(
            self,
            "coverage_counts",
            MappingProxyType(coverage_counts),
        )
        if self.import_count != len(self.imports) or not self.imports:
            raise FixtureImportError("import_count does not match imports")
        if tuple(item.ordinal for item in self.imports) != tuple(
            range(len(self.imports))
        ):
            raise FixtureImportError("import ordinals must be contiguous and ordered")
        import_ids = tuple(item.import_id for item in self.imports)
        if len(import_ids) != len(set(import_ids)):
            raise FixtureImportError("import_id values must be unique")
        references = tuple(item.source_reference for item in self.imports)
        if len(references) != len(set(references)):
            raise FixtureImportError("source_reference values must be unique")

        actual_family_counts = {
            family.value: sum(item.family is family for item in self.imports)
            for family in FixtureFamily
        }
        actual_coverage_counts = {
            coverage.value: sum(
                item.coverage is coverage for item in self.imports
            )
            for coverage in Coverage
        }
        if dict(self.family_counts) != actual_family_counts:
            raise FixtureImportError("family_counts do not match imports")
        if dict(self.coverage_counts) != actual_coverage_counts:
            raise FixtureImportError("coverage_counts do not match imports")
        if any(count == 0 for count in actual_family_counts.values()):
            raise FixtureImportError("every required fixture family must be present")
        if any(count == 0 for count in actual_coverage_counts.values()):
            raise FixtureImportError(
                "positive and negative fixture coverage must both be present"
            )
        fol_tags = {
            tag
            for item in self.imports
            if item.family is FixtureFamily.FOL_DEONTIC_MODAL
            for tag in item.semantic_tags
        }
        if not {"first_order", "deontic", "modal"} <= fol_tags:
            raise FixtureImportError(
                "FOL/deontic/modal imports must explicitly cover first_order, "
                "deontic, and modal semantics"
            )
        if any(
            "ambiguity" not in item.semantic_tags
            for item in self.imports
            if item.family is FixtureFamily.LEGAL_IR_AMBIGUITY
        ):
            raise FixtureImportError(
                "Legal IR ambiguity imports must retain the ambiguity tag"
            )
        hammer_coverage = {
            item.coverage
            for item in self.imports
            if item.family is FixtureFamily.HAMMER
        }
        if hammer_coverage != set(Coverage):
            raise FixtureImportError(
                "Hammer imports must retain positive and negative coverage"
            )
        if any(
            "regression" not in item.semantic_tags
            for item in self.imports
            if item.family is FixtureFamily.LEANSTRAL
        ):
            raise FixtureImportError(
                "Leanstral imports must retain their regression role"
            )
        actual_imports_sha256 = hashlib.sha256(
            canonical_json(
                [_spec_to_dict(spec) for spec in self.imports]
            ).encode("utf-8")
        ).hexdigest()
        if self.imports_sha256 != actual_imports_sha256:
            raise FixtureImportError("imports_sha256 does not match imports")

    def to_dict(self) -> dict[str, object]:
        """Return the canonical JSON-native manifest record."""

        return {
            "coverage_counts": dict(self.coverage_counts),
            "family_counts": dict(self.family_counts),
            "import_count": self.import_count,
            "imports": [spec.to_dict() for spec in self.imports],
            "imports_sha256": self.imports_sha256,
            "manifest_id": self.manifest_id,
            "schema": FIXTURE_IMPORT_MANIFEST_SCHEMA,
            "version": self.version,
        }

    @classmethod
    def from_mapping(cls, value: object) -> Self:
        record = _mapping(value, "fixture import manifest")
        _exact_keys(
            record,
            {
                "coverage_counts",
                "family_counts",
                "import_count",
                "imports",
                "imports_sha256",
                "manifest_id",
                "schema",
                "version",
            },
            "fixture import manifest",
        )
        if record["schema"] != FIXTURE_IMPORT_MANIFEST_SCHEMA:
            raise FixtureImportError("fixture import manifest schema is unsupported")
        raw_imports = record["imports"]
        if not isinstance(raw_imports, list):
            raise FixtureImportError("imports must be an array")
        family_counts = _count_mapping(
            record["family_counts"],
            {family.value for family in FixtureFamily},
            "family_counts",
        )
        coverage_counts = _count_mapping(
            record["coverage_counts"],
            {coverage.value for coverage in Coverage},
            "coverage_counts",
        )
        return cls(
            manifest_id=_safe_id(record["manifest_id"], "manifest_id"),
            version=_integer(record["version"], "version", minimum=1),
            import_count=_integer(record["import_count"], "import_count", minimum=1),
            family_counts=MappingProxyType(family_counts),
            coverage_counts=MappingProxyType(coverage_counts),
            imports_sha256=_digest(record["imports_sha256"], "imports_sha256"),
            imports=tuple(
                FixtureImportSpec.from_mapping(item) for item in raw_imports
            ),
        )


def _count_mapping(
    value: object,
    expected_keys: set[str],
    field_name: str,
) -> dict[str, int]:
    record = _mapping(value, field_name)
    _exact_keys(record, expected_keys, field_name)
    return {
        key: _integer(item, f"{field_name}.{key}")
        for key, item in record.items()
    }


def _spec_to_dict(spec: FixtureImportSpec) -> dict[str, object]:
    return {
        "collection_path": list(spec.collection_path),
        "coverage": spec.coverage.value,
        "expected_result_origin": spec.expected_result_origin,
        "family": spec.family.value,
        "identity_field": spec.identity_field,
        "import_id": spec.import_id,
        "model_generated_expected_result": (
            spec.model_generated_expected_result
        ),
        "ordinal": spec.ordinal,
        "original_id": spec.original_id,
        "record_sha256": spec.record_sha256,
        "schema": FIXTURE_IMPORT_SCHEMA,
        "semantic_tags": list(spec.semantic_tags),
        "source_format": spec.source_format.value,
        "source_path": spec.source_path,
        "source_reference": spec.source_reference,
        "source_sha256": spec.source_sha256,
    }


@dataclass(frozen=True, slots=True)
class ImportedFixture:
    """One unmodified source record with verified provenance."""

    spec: FixtureImportSpec
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.spec, FixtureImportSpec):
            raise FixtureImportError("spec must be a FixtureImportSpec")
        payload = _mapping(self.payload, "payload")
        frozen_payload = _freeze_json(payload, "payload")
        if not isinstance(frozen_payload, Mapping):
            raise FixtureImportError("payload must be an immutable JSON object")
        object.__setattr__(self, "payload", frozen_payload)
        if (
            frozen_payload.get(self.spec.identity_field)
            != self.spec.original_id
        ):
            raise FixtureImportError("imported payload does not preserve original_id")
        payload_sha256 = hashlib.sha256(
            canonical_json(_thaw_json(frozen_payload)).encode("utf-8")
        ).hexdigest()
        if payload_sha256 != self.spec.record_sha256:
            raise FixtureImportError(
                "imported payload does not match record_sha256"
            )
        if _contains_model_origin(frozen_payload):
            raise FixtureImportError(
                "source record asserts a model-generated expected result"
            )


@dataclass(frozen=True, slots=True)
class ImportedFixtureSet:
    """Complete deterministic import result."""

    manifest: FixtureImportManifest
    manifest_sha256: str
    fixtures: tuple[ImportedFixture, ...]
    by_id: Mapping[str, ImportedFixture] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, FixtureImportManifest):
            raise FixtureImportError(
                "manifest must be a FixtureImportManifest"
            )
        _digest(self.manifest_sha256, "manifest_sha256")
        expected_manifest_sha256 = hashlib.sha256(
            (
                canonical_json(self.manifest.to_dict()) + "\n"
            ).encode("utf-8")
        ).hexdigest()
        if self.manifest_sha256 != expected_manifest_sha256:
            raise FixtureImportError(
                "manifest_sha256 does not match canonical manifest bytes"
            )
        if not isinstance(self.fixtures, tuple) or not all(
            isinstance(item, ImportedFixture) for item in self.fixtures
        ):
            raise FixtureImportError(
                "fixtures must be an immutable tuple of ImportedFixture records"
            )
        if len(self.fixtures) != self.manifest.import_count:
            raise FixtureImportError("loaded fixture count does not match manifest")
        if tuple(fixture.spec for fixture in self.fixtures) != self.manifest.imports:
            raise FixtureImportError("loaded fixture order does not match manifest")
        object.__setattr__(
            self,
            "by_id",
            MappingProxyType(
                {
                    fixture.spec.import_id: fixture
                    for fixture in self.fixtures
                }
            ),
        )


def _read_manifest(
    path: Path,
    expected_sha256: str,
) -> tuple[FixtureImportManifest, str]:
    _digest(expected_sha256, "expected_manifest_sha256")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FixtureImportError(f"cannot read fixture import manifest: {exc}") from exc
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise FixtureImportError("fixture import manifest digest mismatch")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FixtureImportError("fixture import manifest is not UTF-8") from exc
    decoded = _decode_json(text, "fixture import manifest")
    if text != canonical_json(decoded) + "\n":
        raise FixtureImportError("fixture import manifest must be canonical JSON")
    return FixtureImportManifest.from_mapping(decoded), actual_sha256


def _resolve_source(repository_root: Path, source_path: str) -> Path:
    try:
        root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise FixtureImportError(f"repository root cannot be resolved: {exc}") from exc
    candidate = (root / source_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FixtureImportError("source_path escapes repository root") from exc
    if not candidate.is_file():
        raise FixtureImportError(f"source fixture is not a file: {source_path}")
    return candidate


def _load_source_records(
    raw: bytes,
    spec: FixtureImportSpec,
) -> tuple[Mapping[str, object], ...]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FixtureImportError(
            f"source fixture is not UTF-8: {spec.source_path}"
        ) from exc
    if spec.source_format is SourceFormat.JSONL:
        if spec.collection_path:
            raise FixtureImportError("JSONL imports cannot have collection_path")
        lines = text.splitlines()
        if not lines or any(not line for line in lines):
            raise FixtureImportError("JSONL source must contain only nonempty records")
        values = [
            _decode_json(line, f"{spec.source_path}:{index}")
            for index, line in enumerate(lines, start=1)
        ]
    else:
        selected: object = _decode_json(text, spec.source_path)
        for component in spec.collection_path:
            container = _mapping(
                selected,
                f"{spec.source_path} collection path",
            )
            if component not in container:
                raise FixtureImportError(
                    f"collection_path component is missing: {component}"
                )
            selected = container[component]
        if isinstance(selected, Mapping):
            values = [selected]
        elif isinstance(selected, list):
            values = selected
        else:
            raise FixtureImportError(
                "selected source collection must be an object or array"
            )
    return tuple(
        _mapping(value, f"{spec.source_path} record") for value in values
    )


def _import_fixture(
    spec: FixtureImportSpec,
    repository_root: Path,
) -> ImportedFixture:
    source_path = _resolve_source(repository_root, spec.source_path)
    try:
        raw = source_path.read_bytes()
    except OSError as exc:
        raise FixtureImportError(
            f"cannot read source fixture {spec.source_path}: {exc}"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != spec.source_sha256:
        raise FixtureImportError(
            f"source fixture digest mismatch: {spec.source_path}"
        )
    records = _load_source_records(raw, spec)
    matches = [
        record
        for record in records
        if record.get(spec.identity_field) == spec.original_id
    ]
    if len(matches) != 1:
        raise FixtureImportError(
            "source selector must resolve to exactly one record: "
            f"{spec.source_reference}"
        )
    record = matches[0]
    actual_record_sha256 = hashlib.sha256(
        canonical_json(record).encode("utf-8")
    ).hexdigest()
    if actual_record_sha256 != spec.record_sha256:
        raise FixtureImportError(
            f"selected record digest mismatch: {spec.source_reference}"
        )
    if _contains_model_origin(record):
        raise FixtureImportError(
            f"model-generated expected result is forbidden: "
            f"{spec.source_reference}"
        )
    frozen = _freeze_json(record, "payload")
    if not isinstance(frozen, Mapping):
        raise FixtureImportError("selected fixture record must be an object")
    return ImportedFixture(spec=spec, payload=frozen)


def load_fixture_imports(
    manifest_path: Path = DEFAULT_IMPORT_MANIFEST_PATH,
    *,
    repository_root: Path = DEFAULT_REPOSITORY_ROOT,
    expected_manifest_sha256: str = FROZEN_IMPORT_MANIFEST_SHA256,
) -> ImportedFixtureSet:
    """Load and verify the complete reviewed existing-fixture import set.

    ``expected_manifest_sha256`` is mandatory and must be a valid digest.
    Tests or later protocol revisions may pass a different explicitly reviewed
    digest; there is deliberately no unpinned loading mode.
    """

    manifest, manifest_sha256 = _read_manifest(
        Path(manifest_path),
        expected_manifest_sha256,
    )
    fixtures = tuple(
        _import_fixture(spec, Path(repository_root))
        for spec in manifest.imports
    )
    return ImportedFixtureSet(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        fixtures=fixtures,
    )


__all__ = [
    "Coverage",
    "DEFAULT_IMPORT_MANIFEST_PATH",
    "DEFAULT_REPOSITORY_ROOT",
    "FIXTURE_IMPORT_MANIFEST_ID",
    "FIXTURE_IMPORT_MANIFEST_SCHEMA",
    "FIXTURE_IMPORT_SCHEMA",
    "FIXTURE_IMPORT_VERSION",
    "FROZEN_IMPORT_MANIFEST_SHA256",
    "FixtureFamily",
    "FixtureImportError",
    "FixtureImportManifest",
    "FixtureImportSpec",
    "HSSLEV0217E25",
    "ImportedFixture",
    "ImportedFixtureSet",
    "SourceFormat",
    "canonical_json",
    "load_fixture_imports",
]
