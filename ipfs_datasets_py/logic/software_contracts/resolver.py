"""Conservative, non-executing symbol resolution for pinned repositories.

Frontends intentionally emit lexical facts only.  This module is the separate
DSCON-G130 resolution stage: it joins those facts against an explicit
``RepositoryComposition`` without importing, evaluating, or reading analyzed
code.  Every answer is typed as definite, finite-may, unresolved, optional,
missing, or revision-mismatch.  In particular, an ambiguous or dynamic target
is never promoted to a guessed definite target.

The composition is the ownership authority.  A source record whose module is
owned by another repository is treated as a mirror and is not indexed.  A
record at a revision other than the selected revision is retained only as
revision-mismatch evidence.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.ast_ir import (
    ASTRecord,
    ImportDefinition,
    ReferenceRecord,
    SymbolDefinition,
)
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_structured,
)


RESOLVER_SCHEMA: Final[str] = "ipfs-datasets.software-contracts.resolution@1"
RESOLVER_VERSION: Final[str] = "1.0.0"
RESOLVER_OWNER_GOAL_ID: Final[str] = "DSCON-G130"
RESOLUTION_FIXTURE_CONTRACT: Final[str] = (
    "ipfs_datasets_py/tests/fixtures/software_contracts/resolution"
)

STATUS_DEFINITE: Final[str] = "definite"
STATUS_FINITE_MAY: Final[str] = "finite_may"
STATUS_UNRESOLVED: Final[str] = "unresolved"
STATUS_OPTIONAL: Final[str] = "optional"
STATUS_MISSING: Final[str] = "missing"
STATUS_REVISION_MISMATCH: Final[str] = "revision_mismatch"
RESOLUTION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        STATUS_DEFINITE,
        STATUS_FINITE_MAY,
        STATUS_UNRESOLVED,
        STATUS_OPTIONAL,
        STATUS_MISSING,
        STATUS_REVISION_MISMATCH,
    }
)

_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,2047}$"
)
_MODULE_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9_$@.][A-Za-z0-9_$@./-]{0,2047}$"
)
_JS_EXTENSIONS: Final[tuple[str, ...]] = (
    ".d.ts",
    ".tsx",
    ".ts",
    ".jsx",
    ".js",
    ".mjs",
    ".cjs",
    ".mts",
    ".cts",
)
_PROTOCOL_BASE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "ABC",
        "Protocol",
        "abc.ABC",
        "typing.Protocol",
        "typing_extensions.Protocol",
    }
)


class ResolutionValidationError(ValueError):
    """Raised when a composition or resolution artifact is not closed."""


def _text(
    value: Any,
    field_name: str,
    *,
    allow_empty: bool = False,
    module: bool = False,
) -> str:
    if type(value) is not str:
        raise ResolutionValidationError(f"{field_name} must be an exact string")
    if not allow_empty and not value:
        raise ResolutionValidationError(f"{field_name} must not be empty")
    if value != value.strip() or any(not char.isprintable() for char in value):
        raise ResolutionValidationError(f"{field_name} is not normalized text")
    if len(value) > 2048:
        raise ResolutionValidationError(f"{field_name} exceeds 2048 characters")
    if (
        value
        and not allow_empty
        and not (
            module
            and _MODULE_RE.fullmatch(value)
            or not module
            and _IDENTIFIER_RE.fullmatch(value)
        )
    ):
        kind = "module path" if module else "identifier"
        raise ResolutionValidationError(f"{field_name} is not a normalized {kind}")
    return value


def _strings(
    value: Any,
    field_name: str,
    *,
    modules: bool = False,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray, Mapping, set, frozenset)):
        raise ResolutionValidationError(f"{field_name} must be an ordered sequence")
    try:
        items = tuple(value)
    except TypeError as exc:
        raise ResolutionValidationError(
            f"{field_name} must be an ordered sequence"
        ) from exc
    result = tuple(
        _text(item, f"{field_name}[{index}]", module=modules)
        for index, item in enumerate(items)
    )
    if not allow_empty and not result:
        raise ResolutionValidationError(f"{field_name} must not be empty")
    if len(set(result)) != len(result):
        raise ResolutionValidationError(f"{field_name} must not contain duplicates")
    return tuple(sorted(result))


def _closed(
    value: Mapping[str, Any],
    fields: frozenset[str],
    record_name: str,
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ResolutionValidationError(f"{record_name} must be an exact mapping")
    missing = fields - set(value)
    extra = set(value) - fields
    if missing or extra:
        raise ResolutionValidationError(
            f"{record_name} fields are closed "
            f"(missing={sorted(missing)}, extra={sorted(extra)})"
        )
    return dict(value)


class _CanonicalResolutionRecord:
    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_dag_json_bytes(self.to_dict())


@dataclass(frozen=True, slots=True)
class RepositoryPin(_CanonicalResolutionRecord):
    """One selected repository revision and its authoritative module prefixes."""

    repository_id: str
    revision: str
    module_prefixes: tuple[str, ...]

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"repository_id", "revision", "module_prefixes"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _text(self.repository_id, "repository_id"),
        )
        object.__setattr__(self, "revision", _text(self.revision, "revision"))
        prefixes = _strings(
            self.module_prefixes,
            "module_prefixes",
            modules=True,
            allow_empty=True,
        )
        if any(item.startswith((".", "/")) or item.endswith((".", "/")) for item in prefixes):
            raise ResolutionValidationError(
                "module_prefixes must be absolute logical package names"
            )
        object.__setattr__(self, "module_prefixes", prefixes)

    def owns(self, module_name: str) -> bool:
        return any(
            module_name == prefix
            or module_name.startswith(prefix + ".")
            or module_name.startswith(prefix + "/")
            for prefix in self.module_prefixes
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "revision": self.revision,
            "module_prefixes": list(self.module_prefixes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepositoryPin":
        return cls(**_closed(value, cls._FIELDS, cls.__name__))


@dataclass(frozen=True, slots=True)
class ModuleAlias(_CanonicalResolutionRecord):
    """A reviewed public module name mapped to one or more finite targets."""

    name: str
    targets: tuple[str, ...]
    optional: bool = False

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"name", "targets", "optional"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _text(self.name, "name", module=True))
        object.__setattr__(
            self,
            "targets",
            _strings(self.targets, "targets", modules=True),
        )
        if type(self.optional) is not bool:
            raise ResolutionValidationError("optional must be an exact bool")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "targets": list(self.targets),
            "optional": self.optional,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModuleAlias":
        return cls(**_closed(value, cls._FIELDS, cls.__name__))


@dataclass(frozen=True, slots=True)
class RepositoryComposition(_CanonicalResolutionRecord):
    """Closed ownership, revision, alias, and optional-dependency authority."""

    repositories: tuple[RepositoryPin, ...]
    aliases: tuple[ModuleAlias, ...] = ()
    optional_modules: tuple[str, ...] = ()
    schema: str = RESOLVER_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"schema", "repositories", "aliases", "optional_modules"}
    )

    def __post_init__(self) -> None:
        if self.schema != RESOLVER_SCHEMA:
            raise ResolutionValidationError(
                f"schema must be exactly {RESOLVER_SCHEMA}"
            )
        if isinstance(self.repositories, (str, bytes, Mapping, set, frozenset)):
            raise ResolutionValidationError("repositories must be an ordered sequence")
        repositories = tuple(self.repositories)
        if not repositories or not all(type(item) is RepositoryPin for item in repositories):
            raise ResolutionValidationError(
                "repositories must contain exact RepositoryPin records"
            )
        repository_ids = [item.repository_id for item in repositories]
        if len(repository_ids) != len(set(repository_ids)):
            raise ResolutionValidationError("repository_id values must be unique")
        prefixes = [
            prefix for item in repositories for prefix in item.module_prefixes
        ]
        if len(prefixes) != len(set(prefixes)):
            raise ResolutionValidationError(
                "a module prefix must have exactly one repository owner"
            )
        object.__setattr__(
            self,
            "repositories",
            tuple(sorted(repositories, key=lambda item: item.repository_id)),
        )

        if isinstance(self.aliases, (str, bytes, Mapping, set, frozenset)):
            raise ResolutionValidationError("aliases must be an ordered sequence")
        aliases = tuple(self.aliases)
        if not all(type(item) is ModuleAlias for item in aliases):
            raise ResolutionValidationError("aliases must contain exact ModuleAlias records")
        names = [item.name for item in aliases]
        if len(names) != len(set(names)):
            raise ResolutionValidationError("alias names must be unique")
        object.__setattr__(
            self,
            "aliases",
            tuple(sorted(aliases, key=lambda item: item.name)),
        )
        object.__setattr__(
            self,
            "optional_modules",
            _strings(
                self.optional_modules,
                "optional_modules",
                modules=True,
                allow_empty=True,
            ),
        )

    @classmethod
    def from_mapping(
        cls,
        repository_revisions: Mapping[str, str],
        package_owners: Mapping[str, str],
        *,
        aliases: Mapping[str, str | Sequence[str]] | None = None,
        optional_modules: Sequence[str] = (),
    ) -> "RepositoryComposition":
        """Build a composition from common manifest-shaped mappings."""

        if type(repository_revisions) is not dict or type(package_owners) is not dict:
            raise ResolutionValidationError(
                "repository_revisions and package_owners must be exact mappings"
            )
        prefixes: dict[str, list[str]] = {
            _text(repository_id, "repository_id"): []
            for repository_id in repository_revisions
        }
        for package, repository_id in package_owners.items():
            package_name = _text(package, "package", module=True)
            owner = _text(repository_id, "package owner")
            if owner not in prefixes:
                raise ResolutionValidationError(
                    f"package {package_name} names unknown repository {owner}"
                )
            prefixes[owner].append(package_name)
        pins = tuple(
            RepositoryPin(
                repository_id=repository_id,
                revision=_text(revision, "revision"),
                module_prefixes=tuple(prefixes[repository_id]),
            )
            for repository_id, revision in repository_revisions.items()
        )
        alias_records: list[ModuleAlias] = []
        for name, targets in (aliases or {}).items():
            normalized_targets = (targets,) if type(targets) is str else tuple(targets)
            alias_records.append(ModuleAlias(name=name, targets=normalized_targets))
        return cls(
            repositories=pins,
            aliases=tuple(alias_records),
            optional_modules=tuple(optional_modules),
        )

    def owner_for(self, module_name: str) -> RepositoryPin | None:
        """Return the longest-prefix owner, never a filesystem mirror."""

        matches: list[tuple[int, RepositoryPin]] = []
        for repository in self.repositories:
            for prefix in repository.module_prefixes:
                if (
                    module_name == prefix
                    or module_name.startswith(prefix + ".")
                    or module_name.startswith(prefix + "/")
                ):
                    matches.append((len(prefix), repository))
        if not matches:
            return None
        return max(matches, key=lambda item: (item[0], item[1].repository_id))[1]

    def repository(self, repository_id: str) -> RepositoryPin | None:
        return next(
            (
                item
                for item in self.repositories
                if item.repository_id == repository_id
            ),
            None,
        )

    def alias_for(self, module_name: str) -> tuple[ModuleAlias | None, str]:
        """Return the longest alias and unmatched suffix."""

        matches = [
            item
            for item in self.aliases
            if module_name == item.name
            or module_name.startswith(item.name + ".")
            or module_name.startswith(item.name + "/")
        ]
        if not matches:
            return (None, "")
        alias = max(matches, key=lambda item: (len(item.name), item.name))
        return (alias, module_name[len(alias.name) :])

    def is_optional(self, module_name: str) -> bool:
        alias, _ = self.alias_for(module_name)
        if alias is not None and alias.optional:
            return True
        return any(
            module_name == prefix
            or module_name.startswith(prefix + ".")
            or module_name.startswith(prefix + "/")
            for prefix in self.optional_modules
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repositories": [item.to_dict() for item in self.repositories],
            "aliases": [item.to_dict() for item in self.aliases],
            "optional_modules": list(self.optional_modules),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepositoryComposition":
        data = _closed(value, cls._FIELDS, cls.__name__)
        return cls(
            schema=data["schema"],
            repositories=tuple(
                RepositoryPin.from_dict(item) for item in data["repositories"]
            ),
            aliases=tuple(ModuleAlias.from_dict(item) for item in data["aliases"]),
            optional_modules=tuple(data["optional_modules"]),
        )


@dataclass(frozen=True, slots=True)
class ResolutionTarget(_CanonicalResolutionRecord):
    repository_id: str
    revision: str
    module: str
    record_cid: str
    symbol_id: str | None = None
    qualified_name: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "repository_id",
            "revision",
            "module",
            "record_cid",
            "symbol_id",
            "qualified_name",
        }
    )

    def __post_init__(self) -> None:
        for name in ("repository_id", "revision", "record_cid"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "module", _text(self.module, "module", module=True))
        for name in ("symbol_id", "qualified_name"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _text(value, name))
        if (self.symbol_id is None) != (self.qualified_name is None):
            raise ResolutionValidationError(
                "symbol_id and qualified_name must both be present or absent"
            )

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.repository_id,
            self.revision,
            self.module,
            self.record_cid,
            self.symbol_id or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "revision": self.revision,
            "module": self.module,
            "record_cid": self.record_cid,
            "symbol_id": self.symbol_id,
            "qualified_name": self.qualified_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResolutionTarget":
        return cls(**_closed(value, cls._FIELDS, cls.__name__))


@dataclass(frozen=True, slots=True)
class ResolutionResult(_CanonicalResolutionRecord):
    requested: str
    status: str
    candidates: tuple[ResolutionTarget, ...] = ()
    reason: str = ""
    is_optional: bool = False

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"requested", "status", "candidates", "reason", "is_optional"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requested",
            _text(self.requested, "requested", module=True),
        )
        if self.status not in RESOLUTION_STATUSES:
            raise ResolutionValidationError(
                f"status must be one of {sorted(RESOLUTION_STATUSES)}"
            )
        if isinstance(self.candidates, (str, bytes, Mapping, set, frozenset)):
            raise ResolutionValidationError("candidates must be an ordered sequence")
        candidates = tuple(self.candidates)
        if not all(type(item) is ResolutionTarget for item in candidates):
            raise ResolutionValidationError(
                "candidates must contain exact ResolutionTarget records"
            )
        by_identity = {item.identity: item for item in candidates}
        object.__setattr__(
            self,
            "candidates",
            tuple(by_identity[key] for key in sorted(by_identity)),
        )
        object.__setattr__(
            self,
            "reason",
            _text(self.reason, "reason", allow_empty=True),
        )
        if type(self.is_optional) is not bool:
            raise ResolutionValidationError("is_optional must be an exact bool")
        if self.status == STATUS_DEFINITE and len(self.candidates) != 1:
            raise ResolutionValidationError(
                "definite resolution requires exactly one candidate"
            )
        if self.status == STATUS_FINITE_MAY and len(self.candidates) < 2:
            raise ResolutionValidationError(
                "finite_may resolution requires at least two candidates"
            )
        if self.status in {STATUS_OPTIONAL, STATUS_MISSING} and self.candidates:
            raise ResolutionValidationError(
                f"{self.status} resolution cannot contain candidates"
            )
        if self.status == STATUS_OPTIONAL and not self.is_optional:
            raise ResolutionValidationError(
                "optional resolution must set is_optional"
            )

    @property
    def is_resolved(self) -> bool:
        return self.status in {STATUS_DEFINITE, STATUS_FINITE_MAY}

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "status": self.status,
            "candidates": [item.to_dict() for item in self.candidates],
            "reason": self.reason,
            "is_optional": self.is_optional,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResolutionResult":
        data = _closed(value, cls._FIELDS, cls.__name__)
        return cls(
            requested=data["requested"],
            status=data["status"],
            candidates=tuple(
                ResolutionTarget.from_dict(item) for item in data["candidates"]
            ),
            reason=data["reason"],
            is_optional=data["is_optional"],
        )


@dataclass(frozen=True, slots=True)
class ImportEdge(_CanonicalResolutionRecord):
    source_repository_id: str
    source_revision: str
    source_module: str
    import_id: str
    import_kind: str
    requested_module: str
    imported_name: str | None
    local_name: str | None
    is_type_only: bool
    resolution: ResolutionResult

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "source_repository_id",
            "source_revision",
            "source_module",
            "import_id",
            "import_kind",
            "requested_module",
            "imported_name",
            "local_name",
            "is_type_only",
            "resolution",
        }
    )

    def __post_init__(self) -> None:
        for name in (
            "source_repository_id",
            "source_revision",
            "import_id",
            "import_kind",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self, "source_module", _text(self.source_module, "source_module", module=True)
        )
        object.__setattr__(
            self,
            "requested_module",
            _text(self.requested_module, "requested_module", module=True),
        )
        for name in ("imported_name", "local_name"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self,
                    name,
                    value if value == "*" else _text(value, name, module=True),
                )
        if type(self.is_type_only) is not bool:
            raise ResolutionValidationError("is_type_only must be an exact bool")
        if type(self.resolution) is not ResolutionResult:
            raise ResolutionValidationError(
                "resolution must be an exact ResolutionResult"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_repository_id": self.source_repository_id,
            "source_revision": self.source_revision,
            "source_module": self.source_module,
            "import_id": self.import_id,
            "import_kind": self.import_kind,
            "requested_module": self.requested_module,
            "imported_name": self.imported_name,
            "local_name": self.local_name,
            "is_type_only": self.is_type_only,
            "resolution": self.resolution.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ImportEdge":
        data = _closed(value, cls._FIELDS, cls.__name__)
        return cls(
            source_repository_id=data["source_repository_id"],
            source_revision=data["source_revision"],
            source_module=data["source_module"],
            import_id=data["import_id"],
            import_kind=data["import_kind"],
            requested_module=data["requested_module"],
            imported_name=data["imported_name"],
            local_name=data["local_name"],
            is_type_only=data["is_type_only"],
            resolution=ResolutionResult.from_dict(data["resolution"]),
        )


@dataclass(frozen=True, slots=True)
class ExportEdge(_CanonicalResolutionRecord):
    source_repository_id: str
    source_revision: str
    source_module: str
    exported_name: str
    via_import_id: str | None
    resolution: ResolutionResult

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "source_repository_id",
            "source_revision",
            "source_module",
            "exported_name",
            "via_import_id",
            "resolution",
        }
    )

    def __post_init__(self) -> None:
        for name in ("source_repository_id", "source_revision", "exported_name"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self, "source_module", _text(self.source_module, "source_module", module=True)
        )
        if self.via_import_id is not None:
            object.__setattr__(
                self,
                "via_import_id",
                _text(self.via_import_id, "via_import_id"),
            )
        if type(self.resolution) is not ResolutionResult:
            raise ResolutionValidationError(
                "resolution must be an exact ResolutionResult"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_repository_id": self.source_repository_id,
            "source_revision": self.source_revision,
            "source_module": self.source_module,
            "exported_name": self.exported_name,
            "via_import_id": self.via_import_id,
            "resolution": self.resolution.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExportEdge":
        data = _closed(value, cls._FIELDS, cls.__name__)
        return cls(
            source_repository_id=data["source_repository_id"],
            source_revision=data["source_revision"],
            source_module=data["source_module"],
            exported_name=data["exported_name"],
            via_import_id=data["via_import_id"],
            resolution=ResolutionResult.from_dict(data["resolution"]),
        )


@dataclass(frozen=True, slots=True)
class ProtocolImplementation(_CanonicalResolutionRecord):
    protocol: ResolutionTarget
    implementation: ResolutionTarget
    kind: str
    certainty: str
    base_reference_id: str | None = None
    required_members: tuple[str, ...] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "protocol",
            "implementation",
            "kind",
            "certainty",
            "base_reference_id",
            "required_members",
        }
    )

    def __post_init__(self) -> None:
        if type(self.protocol) is not ResolutionTarget or self.protocol.symbol_id is None:
            raise ResolutionValidationError("protocol must be a symbol target")
        if (
            type(self.implementation) is not ResolutionTarget
            or self.implementation.symbol_id is None
        ):
            raise ResolutionValidationError("implementation must be a symbol target")
        if self.kind not in {"explicit", "inherited", "structural"}:
            raise ResolutionValidationError(
                "kind must be explicit, inherited, or structural"
            )
        if self.certainty not in {STATUS_DEFINITE, STATUS_FINITE_MAY}:
            raise ResolutionValidationError(
                "protocol certainty must be definite or finite_may"
            )
        if self.base_reference_id is not None:
            object.__setattr__(
                self,
                "base_reference_id",
                _text(self.base_reference_id, "base_reference_id"),
            )
        object.__setattr__(
            self,
            "required_members",
            _strings(
                self.required_members,
                "required_members",
                allow_empty=True,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol.to_dict(),
            "implementation": self.implementation.to_dict(),
            "kind": self.kind,
            "certainty": self.certainty,
            "base_reference_id": self.base_reference_id,
            "required_members": list(self.required_members),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProtocolImplementation":
        data = _closed(value, cls._FIELDS, cls.__name__)
        return cls(
            protocol=ResolutionTarget.from_dict(data["protocol"]),
            implementation=ResolutionTarget.from_dict(data["implementation"]),
            kind=data["kind"],
            certainty=data["certainty"],
            base_reference_id=data["base_reference_id"],
            required_members=tuple(data["required_members"]),
        )


@dataclass(frozen=True, slots=True)
class RepositoryResolution(_CanonicalResolutionRecord):
    composition_cid: str
    import_edges: tuple[ImportEdge, ...]
    export_edges: tuple[ExportEdge, ...]
    protocol_implementations: tuple[ProtocolImplementation, ...]
    ignored_mirror_record_cids: tuple[str, ...] = ()
    stale_record_cids: tuple[str, ...] = ()
    schema: str = RESOLVER_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "composition_cid",
            "import_edges",
            "export_edges",
            "protocol_implementations",
            "ignored_mirror_record_cids",
            "stale_record_cids",
        }
    )

    def __post_init__(self) -> None:
        if self.schema != RESOLVER_SCHEMA:
            raise ResolutionValidationError(
                f"schema must be exactly {RESOLVER_SCHEMA}"
            )
        object.__setattr__(
            self, "composition_cid", _text(self.composition_cid, "composition_cid")
        )
        typed_sequences = (
            ("import_edges", ImportEdge),
            ("export_edges", ExportEdge),
            ("protocol_implementations", ProtocolImplementation),
        )
        for name, record_type in typed_sequences:
            values = tuple(getattr(self, name))
            if not all(type(item) is record_type for item in values):
                raise ResolutionValidationError(
                    f"{name} must contain exact {record_type.__name__} records"
                )
            object.__setattr__(
                self,
                name,
                tuple(sorted(values, key=lambda item: item.canonical_bytes)),
            )
        for name in ("ignored_mirror_record_cids", "stale_record_cids"):
            object.__setattr__(
                self,
                name,
                _strings(getattr(self, name), name, allow_empty=True),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "composition_cid": self.composition_cid,
            "import_edges": [item.to_dict() for item in self.import_edges],
            "export_edges": [item.to_dict() for item in self.export_edges],
            "protocol_implementations": [
                item.to_dict() for item in self.protocol_implementations
            ],
            "ignored_mirror_record_cids": list(self.ignored_mirror_record_cids),
            "stale_record_cids": list(self.stale_record_cids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepositoryResolution":
        data = _closed(value, cls._FIELDS, cls.__name__)
        return cls(
            schema=data["schema"],
            composition_cid=data["composition_cid"],
            import_edges=tuple(
                ImportEdge.from_dict(item) for item in data["import_edges"]
            ),
            export_edges=tuple(
                ExportEdge.from_dict(item) for item in data["export_edges"]
            ),
            protocol_implementations=tuple(
                ProtocolImplementation.from_dict(item)
                for item in data["protocol_implementations"]
            ),
            ignored_mirror_record_cids=tuple(
                data["ignored_mirror_record_cids"]
            ),
            stale_record_cids=tuple(data["stale_record_cids"]),
        )


class SymbolResolver:
    """Resolve immutable AST records against one pinned composition.

    Construction and all resolution methods are pure over the supplied
    records.  No ``importlib``, module loader, filesystem lookup, subprocess,
    evaluator, or compiler API is used.
    """

    def __init__(
        self,
        composition: RepositoryComposition,
        records: Sequence[ASTRecord],
        *,
        max_reexport_depth: int = 32,
    ) -> None:
        if type(composition) is not RepositoryComposition:
            raise ResolutionValidationError(
                "composition must be an exact RepositoryComposition"
            )
        if isinstance(records, (str, bytes, Mapping, set, frozenset)):
            raise ResolutionValidationError("records must be an ordered sequence")
        supplied = tuple(records)
        if not all(type(item) is ASTRecord for item in supplied):
            raise ResolutionValidationError("records must contain exact ASTRecord values")
        if type(max_reexport_depth) is not int or not 1 <= max_reexport_depth <= 256:
            raise ResolutionValidationError(
                "max_reexport_depth must be an integer in 1..256"
            )
        self.composition = composition
        self.records = tuple(sorted(supplied, key=lambda item: item.cid))
        self.max_reexport_depth = max_reexport_depth
        self._pinned: dict[str, list[ASTRecord]] = {}
        self._stale: dict[str, list[ASTRecord]] = {}
        self._ignored: list[ASTRecord] = []
        self._record_by_cid = {item.cid: item for item in self.records}
        self._index_records()

    def _index_records(self) -> None:
        for record in self.records:
            module_name = record.module.name
            owner = self.composition.owner_for(module_name)
            if owner is None or owner.repository_id != record.provenance.repository_id:
                self._ignored.append(record)
                continue
            destination = (
                self._pinned
                if owner.revision == record.provenance.revision
                else self._stale
            )
            destination.setdefault(module_name, []).append(record)
        for index in (self._pinned, self._stale):
            for module_name in index:
                index[module_name].sort(key=lambda item: item.cid)

    @staticmethod
    def _strip_js_extension(path: str) -> str:
        for extension in _JS_EXTENSIONS:
            if path.endswith(extension):
                return path[: -len(extension)]
        return path

    def _normalize_module(self, source: ASTRecord | None, requested: str) -> str | None:
        if source is None:
            value = requested
            if value.startswith("."):
                return None
            return self._strip_js_extension(value).replace("/", ".")

        language = source.frontend.language
        if language == "python":
            if not requested.startswith("."):
                return requested.replace("/", ".")
            level = len(requested) - len(requested.lstrip("."))
            suffix = requested[level:]
            path_name = source.provenance.path
            is_package = path_name.endswith("/__init__.py") or path_name == "__init__.py"
            package = source.module.name.split(".")
            if not is_package:
                package = package[:-1]
            ascend = level - 1
            if ascend > len(package):
                return None
            base = package[: len(package) - ascend] if ascend else package
            return ".".join((*base, *(suffix.split(".") if suffix else ())))

        # JS-family specifiers are path-based.  Resolve relative to the tracked
        # source path and then map the logical path to the frontend module name.
        if requested.startswith(("./", "../")):
            directory = posixpath.dirname(source.provenance.path)
            joined = posixpath.normpath(posixpath.join(directory, requested))
            if joined == ".." or joined.startswith("../") or joined.startswith("/"):
                return None
            value = self._strip_js_extension(joined)
            if value.endswith("/index"):
                package_value = value[: -len("/index")]
                if package_value.replace("/", ".") in self._pinned:
                    value = package_value
            return value.replace("/", ".")
        return self._strip_js_extension(requested).replace("/", ".")

    def _expanded_modules(self, module_name: str) -> tuple[tuple[str, ...], bool]:
        alias, suffix = self.composition.alias_for(module_name)
        if alias is None:
            return ((module_name,), self.composition.is_optional(module_name))
        targets = tuple(
            target + suffix.replace("/", ".") for target in alias.targets
        )
        return (tuple(sorted(set(targets))), alias.optional)

    @staticmethod
    def _module_target(record: ASTRecord) -> ResolutionTarget:
        return ResolutionTarget(
            repository_id=record.provenance.repository_id,
            revision=record.provenance.revision,
            module=record.module.name,
            record_cid=record.cid,
        )

    @staticmethod
    def _symbol_target(
        record: ASTRecord,
        symbol: SymbolDefinition,
    ) -> ResolutionTarget:
        return ResolutionTarget(
            repository_id=record.provenance.repository_id,
            revision=record.provenance.revision,
            module=record.module.name,
            record_cid=record.cid,
            symbol_id=symbol.symbol_id,
            qualified_name=symbol.qualified_name,
        )

    @staticmethod
    def _result(
        requested: str,
        candidates: Iterable[ResolutionTarget],
        *,
        optional: bool,
        missing_reason: str,
        unresolved_reason: str | None = None,
        stale: bool = False,
        incomplete_ambiguity: bool = False,
    ) -> ResolutionResult:
        unique = {item.identity: item for item in candidates}
        ordered = tuple(unique[key] for key in sorted(unique))
        if stale:
            status = STATUS_REVISION_MISMATCH
            reason = "candidate records do not match the composition revision"
        elif unresolved_reason is not None or incomplete_ambiguity:
            status = STATUS_UNRESOLVED
            reason = unresolved_reason or "declared alternatives are not all present"
        elif len(ordered) == 1:
            status = STATUS_DEFINITE
            reason = "one exact pinned target"
        elif len(ordered) > 1:
            status = STATUS_FINITE_MAY
            reason = "multiple exact pinned targets"
        elif optional:
            status = STATUS_OPTIONAL
            reason = "optional dependency is absent from the composition records"
        else:
            status = STATUS_MISSING
            reason = missing_reason
        return ResolutionResult(
            requested=requested,
            status=status,
            candidates=ordered,
            reason=reason,
            is_optional=optional,
        )

    def resolve_module(
        self,
        requested: str,
        *,
        source: ASTRecord | None = None,
    ) -> ResolutionResult:
        """Resolve one Python or JS-family module specifier."""

        normalized = self._normalize_module(source, requested)
        result_name = normalized if normalized is not None else requested
        if normalized is None:
            return self._result(
                result_name,
                (),
                optional=False,
                missing_reason="",
                unresolved_reason="relative module escapes or exceeds its package root",
            )
        names, optional = self._expanded_modules(normalized)
        candidates = [
            self._module_target(record)
            for name in names
            for record in self._pinned.get(name, ())
        ]
        stale = [
            self._module_target(record)
            for name in names
            for record in self._stale.get(name, ())
        ]
        if not candidates and stale:
            return self._result(
                normalized,
                stale,
                optional=optional,
                missing_reason="",
                stale=True,
            )
        missing_alias_alternatives = (
            len(names) > 1
            and any(not self._pinned.get(name) for name in names)
            and (bool(candidates) or not optional)
        )
        return self._result(
            normalized,
            candidates,
            optional=optional,
            missing_reason="module is not present in the pinned composition",
            incomplete_ambiguity=missing_alias_alternatives,
        )

    def _source_revision_result(
        self,
        source: ASTRecord,
        requested: str,
    ) -> ResolutionResult | None:
        owner = self.composition.owner_for(source.module.name)
        if (
            owner is not None
            and owner.repository_id == source.provenance.repository_id
            and owner.revision != source.provenance.revision
        ):
            return self._result(
                requested,
                (self._module_target(source),),
                optional=False,
                missing_reason="",
                stale=True,
            )
        return None

    def _top_level_symbols(
        self,
        record: ASTRecord,
        name: str,
    ) -> tuple[SymbolDefinition, ...]:
        return tuple(
            symbol
            for symbol in record.symbols
            if symbol.scope_id == record.module.scope_id and symbol.name == name
        )

    def _resolve_export(
        self,
        record: ASTRecord,
        name: str,
        *,
        seen: frozenset[tuple[str, str]],
        depth: int,
    ) -> tuple[ResolutionTarget, ...] | None:
        if depth > self.max_reexport_depth:
            return None
        key = (record.cid, name)
        if key in seen:
            return None
        next_seen = seen | {key}
        local = self._top_level_symbols(record, name)
        if local:
            return tuple(self._symbol_target(record, item) for item in local)

        matching_imports = tuple(
            item for item in record.imports if item.local_name == name
        )
        if not matching_imports:
            return ()
        targets: list[ResolutionTarget] = []
        for imported in matching_imports:
            result = self._resolve_import_definition(
                record,
                imported,
                seen=next_seen,
                depth=depth + 1,
            )
            if result.status in {STATUS_UNRESOLVED, STATUS_REVISION_MISMATCH}:
                return None
            targets.extend(result.candidates)
        return tuple(targets)

    def _resolve_symbol_from_modules(
        self,
        requested: str,
        modules: ResolutionResult,
        symbol_name: str,
        *,
        seen: frozenset[tuple[str, str]] = frozenset(),
        depth: int = 0,
    ) -> ResolutionResult:
        if modules.status not in {STATUS_DEFINITE, STATUS_FINITE_MAY}:
            return ResolutionResult(
                requested=requested,
                status=modules.status,
                candidates=modules.candidates,
                reason=modules.reason,
                is_optional=modules.is_optional,
            )
        candidates: list[ResolutionTarget] = []
        unresolved = False
        for module_target in modules.candidates:
            record = self._record_by_cid[module_target.record_cid]
            resolved = self._resolve_export(
                record,
                symbol_name,
                seen=seen,
                depth=depth,
            )
            if resolved is None:
                unresolved = True
            else:
                candidates.extend(resolved)

        # ``from package import submodule`` is valid even when the package
        # module has no symbol definition for the child.
        if not candidates:
            submodule_names = tuple(
                f"{item.module}.{symbol_name}" for item in modules.candidates
            )
            for submodule_name in submodule_names:
                submodule = self.resolve_module(submodule_name)
                candidates.extend(submodule.candidates)
                unresolved = unresolved or submodule.status == STATUS_UNRESOLVED

        return self._result(
            requested,
            candidates,
            optional=modules.is_optional,
            missing_reason="symbol is not exported by the resolved module",
            unresolved_reason=(
                "re-export chain is cyclic or exceeds its configured bound"
                if unresolved
                else None
            ),
        )

    def _resolve_import_definition(
        self,
        source: ASTRecord,
        imported: ImportDefinition,
        *,
        seen: frozenset[tuple[str, str]] = frozenset(),
        depth: int = 0,
    ) -> ResolutionResult:
        normalized = self._normalize_module(source, imported.module)
        requested = normalized or imported.module
        source_mismatch = self._source_revision_result(source, requested)
        if source_mismatch is not None:
            return source_mismatch
        if imported.kind in {"dynamic", "unknown"}:
            return self._result(
                requested,
                (),
                optional=self.composition.is_optional(requested),
                missing_reason="",
                unresolved_reason="dynamic or unknown import has no finite static target",
            )
        modules = self.resolve_module(imported.module, source=source)
        if imported.kind in {"module", "namespace", "side_effect"}:
            return modules
        if imported.imported_name is None:
            return modules
        if imported.imported_name == "*":
            candidates: list[ResolutionTarget] = []
            for module_target in modules.candidates:
                target_record = self._record_by_cid[module_target.record_cid]
                for export_name in target_record.module.export_names:
                    resolved = self._resolve_export(
                        target_record,
                        export_name,
                        seen=seen,
                        depth=depth + 1,
                    )
                    if resolved is None:
                        return self._result(
                            requested,
                            candidates,
                            optional=modules.is_optional,
                            missing_reason="",
                            unresolved_reason="wildcard export chain is not bounded",
                        )
                    candidates.extend(resolved)
            if not modules.is_resolved:
                return modules
            return self._result(
                requested,
                candidates,
                optional=modules.is_optional,
                missing_reason="wildcard import module has no static exports",
            )
        return self._resolve_symbol_from_modules(
            f"{requested}.{imported.imported_name}",
            modules,
            imported.imported_name,
            seen=seen,
            depth=depth,
        )

    def resolve_import(
        self,
        source: ASTRecord,
        imported: ImportDefinition,
    ) -> ImportEdge:
        if type(source) is not ASTRecord or source.cid not in self._record_by_cid:
            raise ResolutionValidationError("source must be one of the resolver records")
        if type(imported) is not ImportDefinition or imported not in source.imports:
            raise ResolutionValidationError("imported must belong to source")
        normalized = self._normalize_module(source, imported.module)
        return ImportEdge(
            source_repository_id=source.provenance.repository_id,
            source_revision=source.provenance.revision,
            source_module=source.module.name,
            import_id=imported.import_id,
            import_kind=imported.kind,
            requested_module=normalized or imported.module,
            imported_name=imported.imported_name,
            local_name=imported.local_name,
            is_type_only=imported.is_type_only,
            resolution=self._resolve_import_definition(source, imported),
        )

    def resolve_imports(self) -> tuple[ImportEdge, ...]:
        edges = [
            self.resolve_import(record, imported)
            for record in self.records
            if record not in self._ignored
            for imported in record.imports
        ]
        return tuple(sorted(edges, key=lambda item: item.canonical_bytes))

    def resolve_exports(self) -> tuple[ExportEdge, ...]:
        edges: list[ExportEdge] = []
        for record in self.records:
            if record in self._ignored:
                continue
            names = set(record.module.export_names)
            names.update(
                item.local_name
                for item in record.imports
                if item.kind == "re_export" and item.local_name is not None
            )
            for name in sorted(names):
                matching_import = next(
                    (
                        item
                        for item in record.imports
                        if item.local_name == name
                        and item.kind in {"re_export", "symbol"}
                    ),
                    None,
                )
                if matching_import is not None:
                    resolution = self._resolve_import_definition(record, matching_import)
                    via_import_id = matching_import.import_id
                else:
                    resolved = self._resolve_export(
                        record,
                        name,
                        seen=frozenset(),
                        depth=0,
                    )
                    resolution = self._result(
                        f"{record.module.name}.{name}",
                        () if resolved is None else resolved,
                        optional=False,
                        missing_reason="declared export has no matching symbol",
                        unresolved_reason=(
                            "export chain is cyclic or exceeds its configured bound"
                            if resolved is None
                            else None
                        ),
                    )
                    via_import_id = None
                edges.append(
                    ExportEdge(
                        source_repository_id=record.provenance.repository_id,
                        source_revision=record.provenance.revision,
                        source_module=record.module.name,
                        exported_name=name,
                        via_import_id=via_import_id,
                        resolution=resolution,
                    )
                )
        return tuple(sorted(edges, key=lambda item: item.canonical_bytes))

    def _member_from_targets(
        self,
        requested: str,
        base: ResolutionResult,
        suffix: str,
    ) -> ResolutionResult:
        if not base.is_resolved:
            return base
        candidates: list[ResolutionTarget] = []
        for target in base.candidates:
            record = self._record_by_cid[target.record_cid]
            prefix = target.qualified_name or target.module
            qualified = f"{prefix}.{suffix}"
            matches = tuple(
                symbol
                for symbol in record.symbols
                if symbol.qualified_name == qualified
            )
            candidates.extend(self._symbol_target(record, item) for item in matches)
        return self._result(
            requested,
            candidates,
            optional=base.is_optional,
            missing_reason="member is not present on the resolved target",
        )

    def resolve_reference(
        self,
        source: ASTRecord,
        reference: ReferenceRecord,
    ) -> ResolutionResult:
        """Resolve a lexical reference through scopes, aliases, and exports."""

        if type(source) is not ASTRecord or source.cid not in self._record_by_cid:
            raise ResolutionValidationError("source must be one of the resolver records")
        if type(reference) is not ReferenceRecord or reference not in source.references:
            raise ResolutionValidationError("reference must belong to source")
        mismatch = self._source_revision_result(source, reference.name)
        if mismatch is not None:
            return mismatch

        first, separator, suffix = reference.name.partition(".")
        parent_by_scope = {
            item.scope_id: item.parent_scope_id for item in source.scopes
        }
        scope_id: str | None = reference.scope_id
        while scope_id is not None:
            symbols = tuple(
                item
                for item in source.symbols
                if item.scope_id == scope_id and item.name == first
            )
            if symbols:
                base = self._result(
                    first,
                    (self._symbol_target(source, item) for item in symbols),
                    optional=False,
                    missing_reason="",
                )
                return (
                    self._member_from_targets(reference.name, base, suffix)
                    if separator
                    else base
                )
            imports = tuple(
                item
                for item in source.imports
                if item.scope_id == scope_id and item.local_name == first
            )
            if imports:
                candidates: list[ResolutionTarget] = []
                unresolved = False
                optional = False
                stale = False
                for imported in imports:
                    result = self._resolve_import_definition(source, imported)
                    candidates.extend(result.candidates)
                    optional = optional or result.is_optional
                    unresolved = unresolved or result.status == STATUS_UNRESOLVED
                    stale = stale or result.status == STATUS_REVISION_MISMATCH
                base = self._result(
                    first,
                    candidates,
                    optional=optional,
                    missing_reason="import binding has no target",
                    unresolved_reason=(
                        "one or more import bindings are unresolved"
                        if unresolved
                        else None
                    ),
                    stale=stale,
                )
                return (
                    self._member_from_targets(reference.name, base, suffix)
                    if separator
                    else base
                )
            scope_id = parent_by_scope.get(scope_id)
        return self._result(
            reference.name,
            (),
            optional=False,
            missing_reason="",
            unresolved_reason="no finite lexical or imported binding is known",
        )

    @staticmethod
    def _enclosing_class(
        record: ASTRecord,
        reference: ReferenceRecord,
    ) -> SymbolDefinition | None:
        classes = [
            symbol
            for symbol in record.symbols
            if symbol.kind == "class"
            and symbol.span.start_byte <= reference.span.start_byte
            and reference.span.end_byte <= symbol.span.end_byte
        ]
        if not classes:
            return None
        return min(
            classes,
            key=lambda item: (
                item.span.end_byte - item.span.start_byte,
                item.symbol_id,
            ),
        )

    @staticmethod
    def _owned_members(record: ASTRecord, owner: SymbolDefinition) -> tuple[str, ...]:
        scope_ids = {
            scope.scope_id
            for scope in record.scopes
            if scope.owner_symbol_id == owner.symbol_id
        }
        return tuple(
            sorted(
                {
                    symbol.name
                    for symbol in record.symbols
                    if symbol.scope_id in scope_ids
                    and symbol.kind in {"method", "property"}
                    and symbol.visibility != "private"
                }
            )
        )

    def resolve_protocols(self) -> tuple[ProtocolImplementation, ...]:
        """Resolve explicit inheritance and conservative structural protocols."""

        class_targets: dict[
            tuple[str, str], tuple[ASTRecord, SymbolDefinition, ResolutionTarget]
        ] = {}
        protocol_keys: set[tuple[str, str]] = set()
        explicit_bases: list[
            tuple[ASTRecord, SymbolDefinition, ReferenceRecord, ResolutionResult]
        ] = []
        for record in self.records:
            if record in self._ignored or record in sum(self._stale.values(), []):
                continue
            for symbol in record.symbols:
                if symbol.kind in {"class", "interface", "protocol"}:
                    key = (record.cid, symbol.symbol_id)
                    class_targets[key] = (
                        record,
                        symbol,
                        self._symbol_target(record, symbol),
                    )
                    if symbol.kind in {"interface", "protocol"} or "protocol" in symbol.flags:
                        protocol_keys.add(key)
            for reference in record.references:
                if reference.context != "base":
                    continue
                implementation = self._enclosing_class(record, reference)
                if implementation is None:
                    continue
                base = self.resolve_reference(record, reference)
                explicit_bases.append((record, implementation, reference, base))
                if reference.name in _PROTOCOL_BASE_NAMES:
                    protocol_keys.add((record.cid, implementation.symbol_id))

        # An explicit base which resolves to a protocol/interface is definite;
        # a finite base set stays finite-may.
        relationships: dict[
            tuple[str, str, str, str], ProtocolImplementation
        ] = {}
        base_links: dict[
            tuple[str, str],
            list[tuple[tuple[str, str], ReferenceRecord, str]],
        ] = {}
        for record, implementation, reference, base in explicit_bases:
            implementation_key = (record.cid, implementation.symbol_id)
            for candidate in base.candidates:
                candidate_key = (candidate.record_cid, candidate.symbol_id or "")
                if candidate_key in class_targets:
                    base_links.setdefault(implementation_key, []).append(
                        (candidate_key, reference, base.status)
                    )
                if candidate_key not in protocol_keys:
                    continue
                protocol_record, protocol_symbol, protocol_target = class_targets[
                    candidate_key
                ]
                implementation_target = self._symbol_target(record, implementation)
                relation = ProtocolImplementation(
                    protocol=protocol_target,
                    implementation=implementation_target,
                    kind="explicit",
                    certainty=(
                        STATUS_DEFINITE
                        if base.status == STATUS_DEFINITE
                        else STATUS_FINITE_MAY
                    ),
                    base_reference_id=reference.reference_id,
                    required_members=self._owned_members(
                        protocol_record, protocol_symbol
                    ),
                )
                relationships[
                    (
                        protocol_target.record_cid,
                        protocol_target.symbol_id or "",
                        implementation_target.record_cid,
                        implementation_target.symbol_id or "",
                    )
                ] = relation

        # Propagate protocol ancestry through resolved class inheritance.  This
        # is deliberately a bounded fixed point over the finite class graph;
        # cycles add no new relation and therefore terminate.
        changed = True
        while changed:
            changed = False
            existing = tuple(relationships.items())
            for implementation_key, links in base_links.items():
                _, _, implementation_target = class_targets[implementation_key]
                for base_key, reference, base_status in links:
                    _, _, base_target = class_targets[base_key]
                    for _, relationship in existing:
                        if relationship.implementation.identity != base_target.identity:
                            continue
                        key = (
                            relationship.protocol.record_cid,
                            relationship.protocol.symbol_id or "",
                            implementation_target.record_cid,
                            implementation_target.symbol_id or "",
                        )
                        if key in relationships:
                            continue
                        protocol_record, protocol_symbol, _ = class_targets[
                            (
                                relationship.protocol.record_cid,
                                relationship.protocol.symbol_id or "",
                            )
                        ]
                        relationships[key] = ProtocolImplementation(
                            protocol=relationship.protocol,
                            implementation=implementation_target,
                            kind="inherited",
                            certainty=(
                                STATUS_DEFINITE
                                if base_status == STATUS_DEFINITE
                                and relationship.certainty == STATUS_DEFINITE
                                else STATUS_FINITE_MAY
                            ),
                            base_reference_id=reference.reference_id,
                            required_members=self._owned_members(
                                protocol_record, protocol_symbol
                            ),
                        )
                        changed = True

        # Structural conformance is a conservative finite dispatch candidate.
        # Empty marker protocols are not expanded structurally because they
        # would match every class and destroy useful precision.
        for protocol_key in sorted(protocol_keys):
            protocol_record, protocol_symbol, protocol_target = class_targets[
                protocol_key
            ]
            required = set(self._owned_members(protocol_record, protocol_symbol))
            if not required:
                continue
            for implementation_key, (
                implementation_record,
                implementation_symbol,
                implementation_target,
            ) in class_targets.items():
                if implementation_key == protocol_key:
                    continue
                key = (
                    protocol_target.record_cid,
                    protocol_target.symbol_id or "",
                    implementation_target.record_cid,
                    implementation_target.symbol_id or "",
                )
                if key in relationships:
                    continue
                provided = set(
                    self._owned_members(
                        implementation_record, implementation_symbol
                    )
                )
                if required <= provided:
                    relationships[key] = ProtocolImplementation(
                        protocol=protocol_target,
                        implementation=implementation_target,
                        kind="structural",
                        certainty=STATUS_FINITE_MAY,
                        required_members=tuple(required),
                    )

        return tuple(
            sorted(relationships.values(), key=lambda item: item.canonical_bytes)
        )

    def resolve(self) -> RepositoryResolution:
        """Build the deterministic resolution artifact consumed by call graphs."""

        stale = tuple(
            record.cid
            for records in self._stale.values()
            for record in records
        )
        return RepositoryResolution(
            composition_cid=self.composition.cid,
            import_edges=self.resolve_imports(),
            export_edges=self.resolve_exports(),
            protocol_implementations=self.resolve_protocols(),
            ignored_mirror_record_cids=tuple(item.cid for item in self._ignored),
            stale_record_cids=stale,
        )


__all__ = [
    "ExportEdge",
    "ImportEdge",
    "ModuleAlias",
    "ProtocolImplementation",
    "RESOLUTION_FIXTURE_CONTRACT",
    "RESOLUTION_STATUSES",
    "RESOLVER_OWNER_GOAL_ID",
    "RESOLVER_SCHEMA",
    "RESOLVER_VERSION",
    "RepositoryComposition",
    "RepositoryPin",
    "RepositoryResolution",
    "ResolutionResult",
    "ResolutionTarget",
    "ResolutionValidationError",
    "STATUS_DEFINITE",
    "STATUS_FINITE_MAY",
    "STATUS_MISSING",
    "STATUS_OPTIONAL",
    "STATUS_REVISION_MISMATCH",
    "STATUS_UNRESOLVED",
    "SymbolResolver",
]
