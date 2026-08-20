"""Complete repository diff and change classification (IPS-015).

Datasets semantic authority for deterministic repository-state diffs and
changed-artifact classification used by invalidation and delta seals.

Rules:

* bind the exact diff algorithm/version and all Git parents;
* the changed-artifact commitment is complete and deterministic over a sorted
  path / action / class / content tuple set;
* merges and dirty overlays are explicit fields (never inferred away);
* ordinary documentation is distinct from checked specifications and generated
  inputs;
* unknown or ambiguous changes force broad invalidation or full fallback;
* imports have no side effects (CID minting reuses identity helpers lazily).

Interfaces: ``RepositoryDiff``, ``ChangedArtifact``, ``ChangeClass``,
``diff_repository_states``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from .identity import (
    ABSENCE_TOKEN,
    CANONICALIZATION_VERSION,
    SECRET_AND_NONDETERMINISTIC_FIELDS,
    IdentityError,
    RepositoryState,
    canonical_cid,
    canonicalize_relative_path,
    validate_profile_cid,
)

REPOSITORY_DIFF_SUBSET: Final[str] = "ips/repository-diff@1"
REPOSITORY_DIFF_NAMESPACE: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/repository_diff"
)
SCHEMA_MAJOR: Final[int] = 1
DIFF_SCHEMA_VERSION: Final[str] = f"diff@{SCHEMA_MAJOR}"
# Exact algorithm identity bound into every RepositoryDiff and commitment.
DIFF_ALGORITHM: Final[str] = (
    f"{REPOSITORY_DIFF_NAMESPACE}/algorithm@{SCHEMA_MAJOR}"
)
DIFF_ALGORITHM_VERSION: Final[str] = str(SCHEMA_MAJOR)

CHANGED_ARTIFACT_SCHEMA: Final[str] = (
    f"{REPOSITORY_DIFF_NAMESPACE}/changed-artifact@{SCHEMA_MAJOR}"
)
ARTIFACT_SNAPSHOT_SCHEMA: Final[str] = (
    f"{REPOSITORY_DIFF_NAMESPACE}/artifact-snapshot@{SCHEMA_MAJOR}"
)
PATH_CLASSIFICATION_POLICY_SCHEMA: Final[str] = (
    f"{REPOSITORY_DIFF_NAMESPACE}/path-classification-policy@{SCHEMA_MAJOR}"
)
REPOSITORY_DIFF_SCHEMA: Final[str] = (
    f"{REPOSITORY_DIFF_NAMESPACE}/repository-diff@{SCHEMA_MAJOR}"
)
CHANGED_ARTIFACT_COMMITMENT_SCHEMA: Final[str] = (
    f"{REPOSITORY_DIFF_NAMESPACE}/changed-artifact-commitment@{SCHEMA_MAJOR}"
)

MAX_IDENTIFIER_BYTES: Final[int] = 512
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
MAX_ARTIFACTS: Final[int] = 1 << 20
MAX_PATH_HINTS: Final[int] = 1 << 16

# Closed ordered change classes (plan §6 + IPS-015 effects).
CHANGE_CLASSES: Final[tuple[str, ...]] = (
    "source_implementation",
    "source_interface",
    "test_source",
    "fixture",
    "dependency_lock",
    "configuration",
    "circuit",
    "proving_key",
    "verification_key",
    "test_selector",
    "policy",
    "network_policy",
    "canonicalization",
    "environment",
    "ordinary_documentation",
    "checked_specification",
    "generated_input",
    "unknown",
)

# Closed ordered change actions (add / modify / delete).
CHANGE_ACTIONS: Final[tuple[str, ...]] = (
    "added",
    "modified",
    "deleted",
)

# Closed inventory layers.  Dirty-overlay entries are never silently folded
# into the clean tree.
ARTIFACT_LAYERS: Final[tuple[str, ...]] = (
    "tree",
    "dirty_overlay",
)

# Classes that, under default policy, force full checkpoint when present.
FULL_FALLBACK_CHANGE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "circuit",
        "proving_key",
        "verification_key",
        "canonicalization",
        "environment",
        "unknown",
    }
)

# Classes that broaden invalidation beyond a single unit without full fallback.
BROAD_INVALIDATION_CHANGE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "source_interface",
        "dependency_lock",
        "policy",
        "network_policy",
        "test_selector",
        "checked_specification",
        "generated_input",
    }
)

# Source code extensions treated as implementation by default.
_SOURCE_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".py",
        ".pyi",
        ".rs",
        ".go",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".java",
        ".kt",
        ".swift",
        ".lean",
        ".v",
        ".sv",
    }
)

_DOC_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".md",
        ".rst",
        ".txt",
        ".adoc",
        ".org",
    }
)

_LOCK_BASENAMES: Final[frozenset[str]] = frozenset(
    {
        "poetry.lock",
        "pipfile.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "cargo.lock",
        "go.sum",
        "composer.lock",
        "gemfile.lock",
        "requirements.lock",
        "uv.lock",
        "flake.lock",
    }
)

_CONFIG_BASENAMES: Final[frozenset[str]] = frozenset(
    {
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "tox.ini",
        "pytest.ini",
        "mypy.ini",
        "cargo.toml",
        "package.json",
        "tsconfig.json",
        "dockerfile",
        "makefile",
        "cmakelists.txt",
    }
)

_CONFIG_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".toml",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".conf",
        ".json",
    }
)


class RepositoryDiffError(ValueError):
    """Repository diff or change-classification contract violation."""


class ChangeClass(str, Enum):
    """Closed semantic classification for a changed artifact."""

    SOURCE_IMPLEMENTATION = "source_implementation"
    SOURCE_INTERFACE = "source_interface"
    TEST_SOURCE = "test_source"
    FIXTURE = "fixture"
    DEPENDENCY_LOCK = "dependency_lock"
    CONFIGURATION = "configuration"
    CIRCUIT = "circuit"
    PROVING_KEY = "proving_key"
    VERIFICATION_KEY = "verification_key"
    TEST_SELECTOR = "test_selector"
    POLICY = "policy"
    NETWORK_POLICY = "network_policy"
    CANONICALIZATION = "canonicalization"
    ENVIRONMENT = "environment"
    ORDINARY_DOCUMENTATION = "ordinary_documentation"
    CHECKED_SPECIFICATION = "checked_specification"
    GENERATED_INPUT = "generated_input"
    UNKNOWN = "unknown"


class ChangeAction(str, Enum):
    """Closed add / modify / delete action for one path."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class ArtifactLayer(str, Enum):
    """Whether an inventory entry is from the clean tree or dirty overlay."""

    TREE = "tree"
    DIRTY_OVERLAY = "dirty_overlay"


def closed_change_classes() -> frozenset[str]:
    return frozenset(CHANGE_CLASSES)


def closed_change_actions() -> frozenset[str]:
    return frozenset(CHANGE_ACTIONS)


def closed_artifact_layers() -> frozenset[str]:
    return frozenset(ARTIFACT_LAYERS)


def parse_change_class(value: Any) -> ChangeClass:
    if isinstance(value, ChangeClass):
        return value
    if not isinstance(value, str) or not value.strip():
        raise RepositoryDiffError("change_class must be a non-empty closed string")
    text = value.strip()
    try:
        return ChangeClass(text)
    except ValueError as exc:
        raise RepositoryDiffError(
            f"unknown ChangeClass {value!r}; closed set is {list(CHANGE_CLASSES)}"
        ) from exc


def parse_change_action(value: Any) -> ChangeAction:
    if isinstance(value, ChangeAction):
        return value
    if not isinstance(value, str) or not value.strip():
        raise RepositoryDiffError("change_action must be a non-empty closed string")
    text = value.strip()
    try:
        return ChangeAction(text)
    except ValueError as exc:
        raise RepositoryDiffError(
            f"unknown ChangeAction {value!r}; closed set is {list(CHANGE_ACTIONS)}"
        ) from exc


def parse_artifact_layer(value: Any) -> ArtifactLayer:
    if isinstance(value, ArtifactLayer):
        return value
    if not isinstance(value, str) or not value.strip():
        raise RepositoryDiffError("artifact layer must be a non-empty closed string")
    text = value.strip()
    try:
        return ArtifactLayer(text)
    except ValueError as exc:
        raise RepositoryDiffError(
            f"unknown ArtifactLayer {value!r}; closed set is {list(ARTIFACT_LAYERS)}"
        ) from exc


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_text(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and value == ABSENCE_TOKEN:
        return ABSENCE_TOKEN
    if not isinstance(value, str) or not value.strip():
        raise RepositoryDiffError(
            f"{field} must be a non-empty string or {ABSENCE_TOKEN}"
        )
    text = value.strip()
    if text != value:
        raise RepositoryDiffError(f"{field} must not have surrounding whitespace")
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise RepositoryDiffError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_cid(value: Any, field: str, *, allow_absence: bool = False) -> str:
    if allow_absence and value == ABSENCE_TOKEN:
        return ABSENCE_TOKEN
    text = _require_text(value, field, allow_absence=False)
    try:
        return validate_profile_cid(text, domain="any")
    except IdentityError as exc:
        raise RepositoryDiffError(f"{field}: {exc}") from exc


def _require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise RepositoryDiffError(f"{field} must be a boolean")
    return value


def _require_nonneg_int(value: Any, field: str, *, allow_absence: bool = False) -> int | str:
    if allow_absence and value == ABSENCE_TOKEN:
        return ABSENCE_TOKEN
    if type(value) is not int or isinstance(value, bool):
        raise RepositoryDiffError(f"{field} must be a finite int or {ABSENCE_TOKEN}")
    if value < 0 or value > MAX_SAFE_INTEGER:
        raise RepositoryDiffError(f"{field} is out of bounds")
    return value


def _require_sorted_unique_strings(
    value: Any, field: str, *, allow_absence: bool = True
) -> tuple[str, ...]:
    if allow_absence and value == ABSENCE_TOKEN:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RepositoryDiffError(f"{field} must be a sequence or {ABSENCE_TOKEN}")
    items = tuple(_require_text(item, field, allow_absence=False) for item in value)
    if list(items) != sorted(items):
        raise RepositoryDiffError(f"{field} must be canonically sorted")
    if len(set(items)) != len(items):
        raise RepositoryDiffError(f"{field} must not contain duplicates")
    return items


def _reject_secret_fields(payload: Mapping[str, Any]) -> None:
    leaked = set(payload) & SECRET_AND_NONDETERMINISTIC_FIELDS
    if leaked:
        raise RepositoryDiffError(
            f"secret or nondeterministic fields are forbidden: {sorted(leaked)}"
        )


def _mint_cid(payload: Mapping[str, Any]) -> str:
    try:
        return canonical_cid(dict(payload))
    except IdentityError as exc:
        raise RepositoryDiffError(str(exc)) from exc


def _seq_canonical(values: Sequence[str]) -> list[str] | str:
    return list(values) if values else ABSENCE_TOKEN


def _path_basename(path: str) -> str:
    return path.rsplit("/", 1)[-1].lower()


def _path_extension(path: str) -> str:
    name = _path_basename(path)
    if "." not in name or name.startswith("."):
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _path_segments(path: str) -> tuple[str, ...]:
    return tuple(segment.lower() for segment in path.split("/"))


def _canonicalize_path_set(value: Any, field: str) -> tuple[str, ...]:
    """Return sorted unique repository-relative paths for policy sets."""

    if value == ABSENCE_TOKEN or value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RepositoryDiffError(f"{field} must be a sequence of paths")
    paths: list[str] = []
    for item in value:
        try:
            paths.append(canonicalize_relative_path(item, field=field))
        except IdentityError as exc:
            raise RepositoryDiffError(f"{field}: {exc}") from exc
    if len(set(paths)) != len(paths):
        raise RepositoryDiffError(f"{field} must not contain duplicates")
    return tuple(sorted(paths))


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PathClassificationPolicy:
    """Deterministic path-to-class policy for repository diffs.

    Explicit path sets and overrides always win over heuristics so callers can
    distinguish ordinary documentation from checked specifications and mark
    public-interface modules without relying on naming conventions alone.
    """

    interface_paths: tuple[str, ...] = ()
    checked_specification_paths: tuple[str, ...] = ()
    generated_input_paths: tuple[str, ...] = ()
    class_overrides: tuple[tuple[str, str], ...] = ()
    treat_unknown_as_ambiguous: bool = True
    treat_dependency_lock_as_full_fallback: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "interface_paths",
            _canonicalize_path_set(self.interface_paths, "interface_paths"),
        )
        object.__setattr__(
            self,
            "checked_specification_paths",
            _canonicalize_path_set(
                self.checked_specification_paths,
                "checked_specification_paths",
            ),
        )
        object.__setattr__(
            self,
            "generated_input_paths",
            _canonicalize_path_set(
                self.generated_input_paths,
                "generated_input_paths",
            ),
        )
        if len(self.interface_paths) > MAX_PATH_HINTS:
            raise RepositoryDiffError("interface_paths exceeds bound")
        if len(self.checked_specification_paths) > MAX_PATH_HINTS:
            raise RepositoryDiffError("checked_specification_paths exceeds bound")
        if len(self.generated_input_paths) > MAX_PATH_HINTS:
            raise RepositoryDiffError("generated_input_paths exceeds bound")

        normalized_overrides: list[tuple[str, str]] = []
        if not isinstance(self.class_overrides, Sequence) or isinstance(
            self.class_overrides, (str, bytes)
        ):
            raise RepositoryDiffError("class_overrides must be a sequence of pairs")
        seen_paths: set[str] = set()
        for item in self.class_overrides:
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes)):
                raise RepositoryDiffError(
                    "class_overrides entries must be (path, change_class) pairs"
                )
            if len(item) != 2:
                raise RepositoryDiffError(
                    "class_overrides entries must be (path, change_class) pairs"
                )
            path = canonicalize_relative_path(item[0], field="class_overrides.path")
            change_class = parse_change_class(item[1]).value
            if path in seen_paths:
                raise RepositoryDiffError(
                    f"class_overrides path {path!r} is duplicated"
                )
            seen_paths.add(path)
            normalized_overrides.append((path, change_class))
        normalized_overrides.sort(key=lambda pair: pair[0])
        object.__setattr__(self, "class_overrides", tuple(normalized_overrides))
        object.__setattr__(
            self,
            "treat_unknown_as_ambiguous",
            _require_bool(
                self.treat_unknown_as_ambiguous, "treat_unknown_as_ambiguous"
            ),
        )
        object.__setattr__(
            self,
            "treat_dependency_lock_as_full_fallback",
            _require_bool(
                self.treat_dependency_lock_as_full_fallback,
                "treat_dependency_lock_as_full_fallback",
            ),
        )

    @property
    def override_map(self) -> dict[str, ChangeClass]:
        return {
            path: parse_change_class(change_class)
            for path, change_class in self.class_overrides
        }

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": PATH_CLASSIFICATION_POLICY_SCHEMA,
            "diff_subset": REPOSITORY_DIFF_SUBSET,
            "interface_paths": _seq_canonical(self.interface_paths),
            "checked_specification_paths": _seq_canonical(
                self.checked_specification_paths
            ),
            "generated_input_paths": _seq_canonical(self.generated_input_paths),
            "class_overrides": (
                [[path, change_class] for path, change_class in self.class_overrides]
                if self.class_overrides
                else ABSENCE_TOKEN
            ),
            "treat_unknown_as_ambiguous": self.treat_unknown_as_ambiguous,
            "treat_dependency_lock_as_full_fallback": (
                self.treat_dependency_lock_as_full_fallback
            ),
        }

    def policy_cid(self) -> str:
        return _mint_cid(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> PathClassificationPolicy:
        if not isinstance(payload, Mapping):
            raise RepositoryDiffError(
                "PathClassificationPolicy payload must be a mapping"
            )
        _reject_secret_fields(payload)
        overrides_raw = payload.get("class_overrides", ABSENCE_TOKEN)
        overrides: tuple[tuple[str, str], ...] = ()
        if overrides_raw != ABSENCE_TOKEN and overrides_raw is not None:
            if not isinstance(overrides_raw, Sequence) or isinstance(
                overrides_raw, (str, bytes)
            ):
                raise RepositoryDiffError("class_overrides must be a sequence")
            overrides = tuple(
                (str(item[0]), str(item[1]))  # type: ignore[index]
                for item in overrides_raw
            )
        return cls(
            interface_paths=tuple(
                str(item)
                for item in (
                    ()
                    if payload.get("interface_paths", ABSENCE_TOKEN) == ABSENCE_TOKEN
                    else payload.get("interface_paths") or ()
                )
            ),
            checked_specification_paths=tuple(
                str(item)
                for item in (
                    ()
                    if payload.get("checked_specification_paths", ABSENCE_TOKEN)
                    == ABSENCE_TOKEN
                    else payload.get("checked_specification_paths") or ()
                )
            ),
            generated_input_paths=tuple(
                str(item)
                for item in (
                    ()
                    if payload.get("generated_input_paths", ABSENCE_TOKEN)
                    == ABSENCE_TOKEN
                    else payload.get("generated_input_paths") or ()
                )
            ),
            class_overrides=overrides,
            treat_unknown_as_ambiguous=bool(
                payload.get("treat_unknown_as_ambiguous", True)
            ),
            treat_dependency_lock_as_full_fallback=bool(
                payload.get("treat_dependency_lock_as_full_fallback", False)
            ),
        )


def classify_path(
    path: Any,
    policy: PathClassificationPolicy | None = None,
) -> ChangeClass:
    """Classify one repository-relative path under the closed ChangeClass set.

    Explicit policy sets and overrides win.  Heuristics never promote ordinary
    documentation into a checked specification or generated input.
    """

    active = policy if policy is not None else PathClassificationPolicy()
    if not isinstance(active, PathClassificationPolicy):
        raise RepositoryDiffError("policy must be a PathClassificationPolicy")
    try:
        normalized = canonicalize_relative_path(path, field="path")
    except IdentityError as exc:
        raise RepositoryDiffError(str(exc)) from exc

    overrides = active.override_map
    if normalized in overrides:
        return overrides[normalized]
    if normalized in active.checked_specification_paths:
        return ChangeClass.CHECKED_SPECIFICATION
    if normalized in active.generated_input_paths:
        return ChangeClass.GENERATED_INPUT
    if normalized in active.interface_paths:
        return ChangeClass.SOURCE_INTERFACE

    segments = _path_segments(normalized)
    basename = _path_basename(normalized)
    extension = _path_extension(normalized)
    lower_path = normalized.lower()

    # Checked-specification markers (distinct from ordinary docs).
    if (
        "checked_spec" in segments
        or "checked-specs" in segments
        or "checked_specs" in segments
        or "formal_spec" in segments
        or "formal-specs" in segments
        or basename.endswith(".checked.md")
        or basename.endswith(".spec.md")
        or basename.endswith(".checked.rst")
        or "checked-specification" in lower_path
        or (
            "checked" in segments
            and (
                extension in _DOC_EXTENSIONS
                or "docs" in segments
                or "doc" in segments
                or "spec" in segments
                or "specs" in segments
            )
        )
    ):
        return ChangeClass.CHECKED_SPECIFICATION

    # Generated inputs (distinct from ordinary docs and source).
    if (
        "generated" in segments
        or "generated_inputs" in segments
        or "generated-inputs" in segments
        or basename.startswith("generated_")
        or basename.endswith(".generated")
        or basename.endswith(".gen")
    ):
        return ChangeClass.GENERATED_INPUT

    # Verification / proving keys and circuits first (high-impact classes).
    if (
        "verification_key" in lower_path
        or "verification-key" in lower_path
        or basename.startswith("vk_")
        or basename.endswith(".vk")
        or basename.endswith(".vkey")
        or "verifying_key" in lower_path
    ):
        return ChangeClass.VERIFICATION_KEY
    if (
        "proving_key" in lower_path
        or "proving-key" in lower_path
        or basename.startswith("pk_")
        or basename.endswith(".pk")
        or basename.endswith(".pkey")
    ):
        return ChangeClass.PROVING_KEY
    if (
        "circuit" in segments
        or "circuits" in segments
        or extension in {".circom", ".r1cs", ".wtns", ".zkey", ".ark"}
        or "circuit" in basename
    ):
        return ChangeClass.CIRCUIT

    if (
        "network_policy" in lower_path
        or "network-policy" in lower_path
        or basename in {"network_policy.json", "network-policy.yaml", "network-policy.yml"}
        or (
            "network" in segments
            and ("policy" in segments or basename.startswith("policy"))
        )
    ):
        return ChangeClass.NETWORK_POLICY

    if (
        "environment" in segments
        or basename in {"environment.json", "environment.toml", "environment.yaml"}
        or "environment_policy" in lower_path
        or "environment-policy" in lower_path
        or "trust_policy" in lower_path
        or "trust-policy" in lower_path
    ):
        return ChangeClass.ENVIRONMENT

    if (
        "canonicalization" in segments
        or "canonicalisation" in segments
        or "canonicalization" in basename
        or basename in {"canonicalization.json", "canonicalization.toml"}
    ):
        return ChangeClass.CANONICALIZATION

    if (
        "selector" in segments
        or "selectors" in segments
        or "test_selector" in lower_path
        or "test-selector" in lower_path
        or basename.startswith("selector.")
        or basename.endswith(".selector.json")
    ):
        return ChangeClass.TEST_SELECTOR

    if (
        "policy" in segments
        or "policies" in segments
        or basename.endswith(".policy.json")
        or basename.endswith(".policy.yaml")
        or basename in {"verification_policy.json", "policy.json"}
    ):
        return ChangeClass.POLICY

    if (
        basename in _LOCK_BASENAMES
        or basename.endswith(".lock")
        or "requirements" in basename
        and basename.endswith(".txt")
        or basename in {"constraints.txt", "dependency-lock.json"}
    ):
        return ChangeClass.DEPENDENCY_LOCK

    if (
        "fixture" in segments
        or "fixtures" in segments
        or basename == "conftest.py"
        or basename.startswith("fixture_")
        or basename.endswith("_fixture.py")
        or basename.endswith(".fixture")
        or basename.endswith(".fixture.json")
    ):
        return ChangeClass.FIXTURE

    if (
        "test" in segments
        or "tests" in segments
        or basename.startswith("test_")
        or basename.endswith("_test.py")
        or basename.endswith("_test.rs")
        or basename.endswith(".test.ts")
        or basename.endswith(".test.js")
        or basename.endswith("_spec.py")
    ):
        return ChangeClass.TEST_SOURCE

    if (
        basename in _CONFIG_BASENAMES
        or "config" in segments
        or "configs" in segments
        or "configuration" in segments
        or (
            extension in _CONFIG_EXTENSIONS
            and not any(
                marker in segments
                for marker in ("docs", "doc", "readme", "spec", "specs")
            )
        )
    ):
        return ChangeClass.CONFIGURATION

    if (
        "docs" in segments
        or "doc" in segments
        or "documentation" in segments
        or basename.startswith("readme")
        or basename.startswith("changelog")
        or basename.startswith("license")
        or extension in _DOC_EXTENSIONS
    ):
        return ChangeClass.ORDINARY_DOCUMENTATION

    if extension in _SOURCE_EXTENSIONS:
        return ChangeClass.SOURCE_IMPLEMENTATION

    return ChangeClass.UNKNOWN


# ---------------------------------------------------------------------------
# Artifact inventory and changed-artifact records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    """One path's content binding in a repository inventory."""

    path: str
    content_cid: str
    byte_length: int
    layer: ArtifactLayer = ArtifactLayer.TREE

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "path",
                canonicalize_relative_path(self.path, field="path"),
            )
        except IdentityError as exc:
            raise RepositoryDiffError(str(exc)) from exc
        object.__setattr__(
            self,
            "content_cid",
            _require_cid(self.content_cid, "content_cid", allow_absence=False),
        )
        object.__setattr__(
            self,
            "byte_length",
            _require_nonneg_int(self.byte_length, "byte_length"),
        )
        object.__setattr__(self, "layer", parse_artifact_layer(self.layer))

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": ARTIFACT_SNAPSHOT_SCHEMA,
            "path": self.path,
            "content_cid": self.content_cid,
            "byte_length": self.byte_length,
            "layer": self.layer.value,
        }

    def inventory_key(self) -> tuple[str, str]:
        """Stable key: path plus layer so dirty overlays stay explicit."""

        return (self.path, self.layer.value)

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ArtifactSnapshot:
        if not isinstance(payload, Mapping):
            raise RepositoryDiffError("ArtifactSnapshot payload must be a mapping")
        _reject_secret_fields(payload)
        return cls(
            path=str(payload.get("path") or ""),
            content_cid=str(payload.get("content_cid") or ""),
            byte_length=payload.get("byte_length"),  # type: ignore[arg-type]
            layer=payload.get("layer") or ArtifactLayer.TREE,
        )


@dataclass(frozen=True, slots=True)
class ChangedArtifact:
    """One complete classified change between two repository inventories."""

    path: str
    change_action: ChangeAction
    change_class: ChangeClass
    old_content_cid: str
    new_content_cid: str
    old_byte_length: int | str
    new_byte_length: int | str
    layer: ArtifactLayer = ArtifactLayer.TREE
    from_dirty_overlay: bool = False

    def __post_init__(self) -> None:
        try:
            object.__setattr__(
                self,
                "path",
                canonicalize_relative_path(self.path, field="path"),
            )
        except IdentityError as exc:
            raise RepositoryDiffError(str(exc)) from exc
        object.__setattr__(
            self, "change_action", parse_change_action(self.change_action)
        )
        object.__setattr__(
            self, "change_class", parse_change_class(self.change_class)
        )
        object.__setattr__(self, "layer", parse_artifact_layer(self.layer))
        object.__setattr__(
            self,
            "from_dirty_overlay",
            _require_bool(self.from_dirty_overlay, "from_dirty_overlay"),
        )

        action = self.change_action
        if action is ChangeAction.ADDED:
            object.__setattr__(
                self,
                "old_content_cid",
                _require_cid(self.old_content_cid, "old_content_cid", allow_absence=True),
            )
            if self.old_content_cid != ABSENCE_TOKEN:
                raise RepositoryDiffError(
                    "added artifact must use typed absence for old_content_cid"
                )
            object.__setattr__(
                self,
                "new_content_cid",
                _require_cid(self.new_content_cid, "new_content_cid"),
            )
            object.__setattr__(
                self,
                "old_byte_length",
                _require_nonneg_int(
                    self.old_byte_length, "old_byte_length", allow_absence=True
                ),
            )
            if self.old_byte_length != ABSENCE_TOKEN:
                raise RepositoryDiffError(
                    "added artifact must use typed absence for old_byte_length"
                )
            object.__setattr__(
                self,
                "new_byte_length",
                _require_nonneg_int(self.new_byte_length, "new_byte_length"),
            )
        elif action is ChangeAction.DELETED:
            object.__setattr__(
                self,
                "old_content_cid",
                _require_cid(self.old_content_cid, "old_content_cid"),
            )
            object.__setattr__(
                self,
                "new_content_cid",
                _require_cid(self.new_content_cid, "new_content_cid", allow_absence=True),
            )
            if self.new_content_cid != ABSENCE_TOKEN:
                raise RepositoryDiffError(
                    "deleted artifact must use typed absence for new_content_cid"
                )
            object.__setattr__(
                self,
                "old_byte_length",
                _require_nonneg_int(self.old_byte_length, "old_byte_length"),
            )
            object.__setattr__(
                self,
                "new_byte_length",
                _require_nonneg_int(
                    self.new_byte_length, "new_byte_length", allow_absence=True
                ),
            )
            if self.new_byte_length != ABSENCE_TOKEN:
                raise RepositoryDiffError(
                    "deleted artifact must use typed absence for new_byte_length"
                )
        else:
            object.__setattr__(
                self,
                "old_content_cid",
                _require_cid(self.old_content_cid, "old_content_cid"),
            )
            object.__setattr__(
                self,
                "new_content_cid",
                _require_cid(self.new_content_cid, "new_content_cid"),
            )
            if self.old_content_cid == self.new_content_cid:
                raise RepositoryDiffError(
                    "modified artifact requires distinct old/new content CIDs"
                )
            object.__setattr__(
                self,
                "old_byte_length",
                _require_nonneg_int(self.old_byte_length, "old_byte_length"),
            )
            object.__setattr__(
                self,
                "new_byte_length",
                _require_nonneg_int(self.new_byte_length, "new_byte_length"),
            )

        expected_dirty = self.layer is ArtifactLayer.DIRTY_OVERLAY
        if self.from_dirty_overlay != expected_dirty:
            raise RepositoryDiffError(
                "from_dirty_overlay must match layer == dirty_overlay"
            )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": CHANGED_ARTIFACT_SCHEMA,
            "path": self.path,
            "change_action": self.change_action.value,
            "change_class": self.change_class.value,
            "old_content_cid": self.old_content_cid,
            "new_content_cid": self.new_content_cid,
            "old_byte_length": self.old_byte_length,
            "new_byte_length": self.new_byte_length,
            "layer": self.layer.value,
            "from_dirty_overlay": self.from_dirty_overlay,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def artifact_cid(self) -> str:
        return _mint_cid(self.to_canonical())

    def sort_key(self) -> tuple[str, str, str]:
        return (self.path, self.layer.value, self.change_action.value)

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ChangedArtifact:
        if not isinstance(payload, Mapping):
            raise RepositoryDiffError("ChangedArtifact payload must be a mapping")
        _reject_secret_fields(payload)
        return cls(
            path=str(payload.get("path") or ""),
            change_action=payload.get("change_action") or "",
            change_class=payload.get("change_class") or "",
            old_content_cid=str(payload.get("old_content_cid") or ""),
            new_content_cid=str(payload.get("new_content_cid") or ""),
            old_byte_length=payload.get("old_byte_length"),  # type: ignore[arg-type]
            new_byte_length=payload.get("new_byte_length"),  # type: ignore[arg-type]
            layer=payload.get("layer") or ArtifactLayer.TREE,
            from_dirty_overlay=bool(payload.get("from_dirty_overlay", False)),
        )


def commit_changed_artifacts(
    artifacts: Sequence[ChangedArtifact],
    *,
    diff_algorithm: str = DIFF_ALGORITHM,
) -> str:
    """Mint the complete deterministic changed-artifact commitment CID."""

    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        raise RepositoryDiffError("artifacts must be a sequence of ChangedArtifact")
    if len(artifacts) > MAX_ARTIFACTS:
        raise RepositoryDiffError("changed artifact set exceeds bound")
    normalized: list[ChangedArtifact] = []
    for item in artifacts:
        if not isinstance(item, ChangedArtifact):
            raise RepositoryDiffError(
                "artifacts must contain only ChangedArtifact records"
            )
        normalized.append(item)
    ordered = sorted(normalized, key=lambda item: item.sort_key())
    # Reject duplicates at the same path/layer/action identity.
    seen: set[tuple[str, str, str]] = set()
    for item in ordered:
        key = item.sort_key()
        if key in seen:
            raise RepositoryDiffError(
                f"duplicate changed artifact for path {item.path!r}"
            )
        seen.add(key)
    payload = {
        "schema": CHANGED_ARTIFACT_COMMITMENT_SCHEMA,
        "diff_subset": REPOSITORY_DIFF_SUBSET,
        "diff_algorithm": _require_text(diff_algorithm, "diff_algorithm"),
        "diff_algorithm_version": DIFF_ALGORITHM_VERSION,
        "count": len(ordered),
        "artifacts": [item.to_canonical() for item in ordered],
    }
    return _mint_cid(payload)


# ---------------------------------------------------------------------------
# RepositoryDiff
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RepositoryDiff:
    """Complete, content-addressed repository state diff.

    Merges bind every parent revision ID.  Dirty overlays are explicit fields
    and never silently dropped.  ``changed_artifact_commitment`` commits to the
    full sorted changed-artifact set under the bound diff algorithm.
    """

    repository_id: str
    old_revision: str
    new_revision: str
    old_repository_state_cid: str
    new_repository_state_cid: str
    old_tree_cid: str
    new_tree_cid: str
    parent_revision_ids: tuple[str, ...]
    selected_parent_revision: str
    is_merge: bool
    old_dirty_overlay_cid: str
    new_dirty_overlay_cid: str
    dirty_overlay_present: bool
    dirty_overlay_changed: bool
    changed_artifacts: tuple[ChangedArtifact, ...]
    changed_artifact_commitment: str
    change_classes_present: tuple[str, ...]
    complete: bool
    ambiguous: bool
    full_fallback_required: bool
    requires_broad_invalidation: bool
    inventory_complete: bool
    merge_resolved: bool
    classification_policy_cid: str
    diff_algorithm: str = DIFF_ALGORITHM
    diff_algorithm_version: str = DIFF_ALGORITHM_VERSION
    schema: str = REPOSITORY_DIFF_SCHEMA
    canonicalization_version: str = CANONICALIZATION_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "repository_id", _require_text(self.repository_id, "repository_id")
        )
        object.__setattr__(
            self, "old_revision", _require_text(self.old_revision, "old_revision")
        )
        object.__setattr__(
            self, "new_revision", _require_text(self.new_revision, "new_revision")
        )
        object.__setattr__(
            self,
            "old_repository_state_cid",
            _require_cid(self.old_repository_state_cid, "old_repository_state_cid"),
        )
        object.__setattr__(
            self,
            "new_repository_state_cid",
            _require_cid(self.new_repository_state_cid, "new_repository_state_cid"),
        )
        object.__setattr__(
            self, "old_tree_cid", _require_cid(self.old_tree_cid, "old_tree_cid")
        )
        object.__setattr__(
            self, "new_tree_cid", _require_cid(self.new_tree_cid, "new_tree_cid")
        )
        object.__setattr__(
            self,
            "parent_revision_ids",
            _require_sorted_unique_strings(
                self.parent_revision_ids, "parent_revision_ids", allow_absence=False
            ),
        )
        object.__setattr__(
            self,
            "selected_parent_revision",
            _require_text(
                self.selected_parent_revision,
                "selected_parent_revision",
                allow_absence=True,
            ),
        )
        object.__setattr__(self, "is_merge", _require_bool(self.is_merge, "is_merge"))
        object.__setattr__(
            self,
            "old_dirty_overlay_cid",
            _require_cid(
                self.old_dirty_overlay_cid,
                "old_dirty_overlay_cid",
                allow_absence=True,
            ),
        )
        object.__setattr__(
            self,
            "new_dirty_overlay_cid",
            _require_cid(
                self.new_dirty_overlay_cid,
                "new_dirty_overlay_cid",
                allow_absence=True,
            ),
        )
        object.__setattr__(
            self,
            "dirty_overlay_present",
            _require_bool(self.dirty_overlay_present, "dirty_overlay_present"),
        )
        object.__setattr__(
            self,
            "dirty_overlay_changed",
            _require_bool(self.dirty_overlay_changed, "dirty_overlay_changed"),
        )
        if not isinstance(self.changed_artifacts, tuple):
            object.__setattr__(
                self, "changed_artifacts", tuple(self.changed_artifacts)
            )
        if len(self.changed_artifacts) > MAX_ARTIFACTS:
            raise RepositoryDiffError("changed_artifacts exceeds bound")
        for item in self.changed_artifacts:
            if not isinstance(item, ChangedArtifact):
                raise RepositoryDiffError(
                    "changed_artifacts must contain ChangedArtifact records"
                )
        ordered = tuple(
            sorted(self.changed_artifacts, key=lambda item: item.sort_key())
        )
        if ordered != self.changed_artifacts:
            raise RepositoryDiffError(
                "changed_artifacts must be canonically sorted by path/layer/action"
            )
        object.__setattr__(
            self,
            "changed_artifact_commitment",
            _require_cid(
                self.changed_artifact_commitment, "changed_artifact_commitment"
            ),
        )
        expected_commitment = commit_changed_artifacts(
            self.changed_artifacts, diff_algorithm=self.diff_algorithm
        )
        if self.changed_artifact_commitment != expected_commitment:
            raise RepositoryDiffError(
                "changed_artifact_commitment does not match bound algorithm commitment"
            )
        object.__setattr__(
            self,
            "change_classes_present",
            _require_sorted_unique_strings(
                self.change_classes_present,
                "change_classes_present",
                allow_absence=False,
            ),
        )
        expected_classes = tuple(
            sorted({item.change_class.value for item in self.changed_artifacts})
        )
        if self.change_classes_present != expected_classes:
            raise RepositoryDiffError(
                "change_classes_present must equal sorted unique classes from artifacts"
            )
        for name in self.change_classes_present:
            parse_change_class(name)
        object.__setattr__(self, "complete", _require_bool(self.complete, "complete"))
        object.__setattr__(
            self, "ambiguous", _require_bool(self.ambiguous, "ambiguous")
        )
        object.__setattr__(
            self,
            "full_fallback_required",
            _require_bool(self.full_fallback_required, "full_fallback_required"),
        )
        object.__setattr__(
            self,
            "requires_broad_invalidation",
            _require_bool(
                self.requires_broad_invalidation, "requires_broad_invalidation"
            ),
        )
        object.__setattr__(
            self,
            "inventory_complete",
            _require_bool(self.inventory_complete, "inventory_complete"),
        )
        object.__setattr__(
            self, "merge_resolved", _require_bool(self.merge_resolved, "merge_resolved")
        )
        object.__setattr__(
            self,
            "classification_policy_cid",
            _require_cid(self.classification_policy_cid, "classification_policy_cid"),
        )
        object.__setattr__(
            self,
            "diff_algorithm",
            _require_text(self.diff_algorithm, "diff_algorithm"),
        )
        if self.diff_algorithm != DIFF_ALGORITHM:
            raise RepositoryDiffError(
                f"diff_algorithm must be exactly {DIFF_ALGORITHM}"
            )
        object.__setattr__(
            self,
            "diff_algorithm_version",
            _require_text(self.diff_algorithm_version, "diff_algorithm_version"),
        )
        if self.diff_algorithm_version != DIFF_ALGORITHM_VERSION:
            raise RepositoryDiffError(
                f"diff_algorithm_version must be {DIFF_ALGORITHM_VERSION}"
            )
        object.__setattr__(self, "schema", _require_text(self.schema, "schema"))
        if self.schema != REPOSITORY_DIFF_SCHEMA:
            raise RepositoryDiffError(
                f"repository diff schema must be {REPOSITORY_DIFF_SCHEMA}"
            )
        object.__setattr__(
            self,
            "canonicalization_version",
            _require_text(
                self.canonicalization_version, "canonicalization_version"
            ),
        )

        # Structural consistency for merge and dirty-overlay flags.
        if self.is_merge and len(self.parent_revision_ids) < 2:
            raise RepositoryDiffError(
                "merge diffs must bind at least two parent_revision_ids"
            )
        if not self.is_merge and len(self.parent_revision_ids) >= 2:
            raise RepositoryDiffError(
                "non-merge diffs must not claim two or more parents"
            )
        expected_dirty_present = (
            self.old_dirty_overlay_cid != ABSENCE_TOKEN
            or self.new_dirty_overlay_cid != ABSENCE_TOKEN
        )
        if self.dirty_overlay_present != expected_dirty_present:
            raise RepositoryDiffError(
                "dirty_overlay_present must reflect explicit overlay CIDs"
            )
        expected_dirty_changed = (
            self.old_dirty_overlay_cid != self.new_dirty_overlay_cid
        )
        if self.dirty_overlay_changed != expected_dirty_changed:
            raise RepositoryDiffError(
                "dirty_overlay_changed must compare explicit overlay CIDs"
            )
        if any(item.from_dirty_overlay for item in self.changed_artifacts):
            if not self.dirty_overlay_present:
                raise RepositoryDiffError(
                    "dirty-overlay artifacts require dirty_overlay_present"
                )

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "diff_subset": REPOSITORY_DIFF_SUBSET,
            "diff_schema_version": DIFF_SCHEMA_VERSION,
            "canonicalization_version": self.canonicalization_version,
            "diff_algorithm": self.diff_algorithm,
            "diff_algorithm_version": self.diff_algorithm_version,
            "repository_id": self.repository_id,
            "old_revision": self.old_revision,
            "new_revision": self.new_revision,
            "old_repository_state_cid": self.old_repository_state_cid,
            "new_repository_state_cid": self.new_repository_state_cid,
            "old_tree_cid": self.old_tree_cid,
            "new_tree_cid": self.new_tree_cid,
            "parent_revision_ids": _seq_canonical(self.parent_revision_ids),
            "selected_parent_revision": self.selected_parent_revision,
            "is_merge": self.is_merge,
            "old_dirty_overlay_cid": self.old_dirty_overlay_cid,
            "new_dirty_overlay_cid": self.new_dirty_overlay_cid,
            "dirty_overlay_present": self.dirty_overlay_present,
            "dirty_overlay_changed": self.dirty_overlay_changed,
            "changed_artifacts": [item.to_canonical() for item in self.changed_artifacts],
            "changed_artifact_commitment": self.changed_artifact_commitment,
            "change_classes_present": _seq_canonical(self.change_classes_present),
            "complete": self.complete,
            "ambiguous": self.ambiguous,
            "full_fallback_required": self.full_fallback_required,
            "requires_broad_invalidation": self.requires_broad_invalidation,
            "inventory_complete": self.inventory_complete,
            "merge_resolved": self.merge_resolved,
            "classification_policy_cid": self.classification_policy_cid,
        }

    def to_canonical_json(self) -> str:
        return json.dumps(
            self.to_canonical(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def identity_cid(self) -> str:
        return _mint_cid(self.to_canonical())

    def artifacts_by_class(self, change_class: ChangeClass | str) -> tuple[ChangedArtifact, ...]:
        parsed = parse_change_class(change_class)
        return tuple(
            item for item in self.changed_artifacts if item.change_class is parsed
        )

    def has_class(self, change_class: ChangeClass | str) -> bool:
        return parse_change_class(change_class).value in self.change_classes_present

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> RepositoryDiff:
        if not isinstance(payload, Mapping):
            raise RepositoryDiffError("RepositoryDiff payload must be a mapping")
        _reject_secret_fields(payload)
        artifacts_raw = payload.get("changed_artifacts") or ()
        if not isinstance(artifacts_raw, Sequence) or isinstance(
            artifacts_raw, (str, bytes)
        ):
            raise RepositoryDiffError("changed_artifacts must be a sequence")
        artifacts = tuple(
            ChangedArtifact.from_canonical(item)  # type: ignore[arg-type]
            for item in artifacts_raw
        )
        parents = payload.get("parent_revision_ids", ABSENCE_TOKEN)
        classes = payload.get("change_classes_present", ABSENCE_TOKEN)
        return cls(
            repository_id=str(payload.get("repository_id") or ""),
            old_revision=str(payload.get("old_revision") or ""),
            new_revision=str(payload.get("new_revision") or ""),
            old_repository_state_cid=str(
                payload.get("old_repository_state_cid") or ""
            ),
            new_repository_state_cid=str(
                payload.get("new_repository_state_cid") or ""
            ),
            old_tree_cid=str(payload.get("old_tree_cid") or ""),
            new_tree_cid=str(payload.get("new_tree_cid") or ""),
            parent_revision_ids=(
                ()
                if parents == ABSENCE_TOKEN
                else tuple(str(item) for item in parents)  # type: ignore[arg-type]
            ),
            selected_parent_revision=str(
                payload.get("selected_parent_revision") or ABSENCE_TOKEN
            ),
            is_merge=bool(payload.get("is_merge", False)),
            old_dirty_overlay_cid=str(
                payload.get("old_dirty_overlay_cid") or ABSENCE_TOKEN
            ),
            new_dirty_overlay_cid=str(
                payload.get("new_dirty_overlay_cid") or ABSENCE_TOKEN
            ),
            dirty_overlay_present=bool(payload.get("dirty_overlay_present", False)),
            dirty_overlay_changed=bool(payload.get("dirty_overlay_changed", False)),
            changed_artifacts=artifacts,
            changed_artifact_commitment=str(
                payload.get("changed_artifact_commitment") or ""
            ),
            change_classes_present=(
                ()
                if classes == ABSENCE_TOKEN
                else tuple(str(item) for item in classes)  # type: ignore[arg-type]
            ),
            complete=bool(payload.get("complete", False)),
            ambiguous=bool(payload.get("ambiguous", False)),
            full_fallback_required=bool(
                payload.get("full_fallback_required", False)
            ),
            requires_broad_invalidation=bool(
                payload.get("requires_broad_invalidation", False)
            ),
            inventory_complete=bool(payload.get("inventory_complete", False)),
            merge_resolved=bool(payload.get("merge_resolved", False)),
            classification_policy_cid=str(
                payload.get("classification_policy_cid") or ""
            ),
            diff_algorithm=str(payload.get("diff_algorithm") or DIFF_ALGORITHM),
            diff_algorithm_version=str(
                payload.get("diff_algorithm_version") or DIFF_ALGORITHM_VERSION
            ),
            schema=str(payload.get("schema") or REPOSITORY_DIFF_SCHEMA),
            canonicalization_version=str(
                payload.get("canonicalization_version") or CANONICALIZATION_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Diff algorithm
# ---------------------------------------------------------------------------


def _index_artifacts(
    artifacts: Sequence[ArtifactSnapshot],
    *,
    field: str,
) -> dict[tuple[str, str], ArtifactSnapshot]:
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        raise RepositoryDiffError(f"{field} must be a sequence of ArtifactSnapshot")
    if len(artifacts) > MAX_ARTIFACTS:
        raise RepositoryDiffError(f"{field} exceeds artifact bound")
    index: dict[tuple[str, str], ArtifactSnapshot] = {}
    for item in artifacts:
        if not isinstance(item, ArtifactSnapshot):
            raise RepositoryDiffError(
                f"{field} must contain only ArtifactSnapshot records"
            )
        key = item.inventory_key()
        if key in index:
            raise RepositoryDiffError(
                f"{field} contains duplicate path/layer {item.path!r}/{item.layer.value}"
            )
        index[key] = item
    return index


def diff_artifact_inventories(
    old_artifacts: Sequence[ArtifactSnapshot],
    new_artifacts: Sequence[ArtifactSnapshot],
    *,
    policy: PathClassificationPolicy | None = None,
) -> tuple[ChangedArtifact, ...]:
    """Diff two path inventories into a complete sorted ChangedArtifact tuple."""

    active = policy if policy is not None else PathClassificationPolicy()
    if not isinstance(active, PathClassificationPolicy):
        raise RepositoryDiffError("policy must be a PathClassificationPolicy")
    old_index = _index_artifacts(old_artifacts, field="old_artifacts")
    new_index = _index_artifacts(new_artifacts, field="new_artifacts")
    keys = sorted(set(old_index) | set(new_index))
    changes: list[ChangedArtifact] = []
    for key in keys:
        old_item = old_index.get(key)
        new_item = new_index.get(key)
        path, layer_value = key
        layer = parse_artifact_layer(layer_value)
        from_dirty = layer is ArtifactLayer.DIRTY_OVERLAY
        change_class = classify_path(path, active)
        if old_item is None and new_item is not None:
            changes.append(
                ChangedArtifact(
                    path=path,
                    change_action=ChangeAction.ADDED,
                    change_class=change_class,
                    old_content_cid=ABSENCE_TOKEN,
                    new_content_cid=new_item.content_cid,
                    old_byte_length=ABSENCE_TOKEN,
                    new_byte_length=new_item.byte_length,
                    layer=layer,
                    from_dirty_overlay=from_dirty,
                )
            )
        elif old_item is not None and new_item is None:
            changes.append(
                ChangedArtifact(
                    path=path,
                    change_action=ChangeAction.DELETED,
                    change_class=change_class,
                    old_content_cid=old_item.content_cid,
                    new_content_cid=ABSENCE_TOKEN,
                    old_byte_length=old_item.byte_length,
                    new_byte_length=ABSENCE_TOKEN,
                    layer=layer,
                    from_dirty_overlay=from_dirty,
                )
            )
        elif old_item is not None and new_item is not None:
            if old_item.content_cid == new_item.content_cid:
                # Byte-identical content is not a change even if byte_length
                # metadata were inconsistent; length is derived from content.
                continue
            changes.append(
                ChangedArtifact(
                    path=path,
                    change_action=ChangeAction.MODIFIED,
                    change_class=change_class,
                    old_content_cid=old_item.content_cid,
                    new_content_cid=new_item.content_cid,
                    old_byte_length=old_item.byte_length,
                    new_byte_length=new_item.byte_length,
                    layer=layer,
                    from_dirty_overlay=from_dirty,
                )
            )
    return tuple(sorted(changes, key=lambda item: item.sort_key()))


def _decide_fallback(
    *,
    change_classes: set[str],
    policy: PathClassificationPolicy,
    inventory_complete: bool,
    is_merge: bool,
    merge_resolved: bool,
    parent_revision_ids: tuple[str, ...],
    selected_parent_revision: str,
    repository_ids_match: bool,
) -> tuple[bool, bool, bool, bool]:
    """Return (complete, ambiguous, full_fallback_required, requires_broad)."""

    unknown_present = ChangeClass.UNKNOWN.value in change_classes
    ambiguous = False
    if not inventory_complete:
        ambiguous = True
    if unknown_present and policy.treat_unknown_as_ambiguous:
        ambiguous = True
    if not repository_ids_match:
        ambiguous = True
    if is_merge:
        if len(parent_revision_ids) < 2:
            ambiguous = True
        if not merge_resolved:
            ambiguous = True
        if selected_parent_revision == ABSENCE_TOKEN:
            ambiguous = True
        elif (
            selected_parent_revision not in parent_revision_ids
        ):
            # Selected parent must be one of the bound merge parents.
            ambiguous = True

    full_fallback = ambiguous
    if change_classes & FULL_FALLBACK_CHANGE_CLASSES:
        full_fallback = True
    if (
        policy.treat_dependency_lock_as_full_fallback
        and ChangeClass.DEPENDENCY_LOCK.value in change_classes
    ):
        full_fallback = True
    if not repository_ids_match:
        full_fallback = True

    broad = bool(change_classes & BROAD_INVALIDATION_CHANGE_CLASSES) or full_fallback
    complete = inventory_complete and not ambiguous
    return complete, ambiguous, full_fallback, broad


def diff_repository_states(
    old_state: RepositoryState,
    new_state: RepositoryState,
    *,
    old_artifacts: Sequence[ArtifactSnapshot] = (),
    new_artifacts: Sequence[ArtifactSnapshot] = (),
    policy: PathClassificationPolicy | None = None,
    inventory_complete: bool = True,
    selected_parent_revision: str | None = None,
    merge_resolved: bool | None = None,
) -> RepositoryDiff:
    """Compute a complete deterministic repository diff between two states.

    ``old_artifacts`` / ``new_artifacts`` are hermetic path inventories.  When
    ``inventory_complete`` is false, the diff is marked incomplete/ambiguous and
    requires full fallback.  Merge commits bind every parent revision from
    ``new_state.parent_revision_ids``; unresolved merges force full fallback.
    """

    if not isinstance(old_state, RepositoryState):
        raise RepositoryDiffError("old_state must be a RepositoryState")
    if not isinstance(new_state, RepositoryState):
        raise RepositoryDiffError("new_state must be a RepositoryState")
    active = policy if policy is not None else PathClassificationPolicy()
    if not isinstance(active, PathClassificationPolicy):
        raise RepositoryDiffError("policy must be a PathClassificationPolicy")
    inventory_complete = _require_bool(inventory_complete, "inventory_complete")

    parent_revision_ids = tuple(new_state.parent_revision_ids)
    is_merge = len(parent_revision_ids) >= 2

    if selected_parent_revision is None:
        if is_merge:
            selected = ABSENCE_TOKEN
        elif parent_revision_ids:
            selected = parent_revision_ids[0]
        else:
            selected = old_state.revision
    else:
        selected = _require_text(
            selected_parent_revision,
            "selected_parent_revision",
            allow_absence=True,
        )

    if merge_resolved is None:
        # Single-parent transitions are resolved when inventory is complete.
        # Merges require an explicit True to count as resolved.
        resolved = (not is_merge) and inventory_complete
    else:
        resolved = _require_bool(merge_resolved, "merge_resolved")

    changed = diff_artifact_inventories(
        old_artifacts, new_artifacts, policy=active
    )
    classes = {item.change_class.value for item in changed}
    complete, ambiguous, full_fallback, broad = _decide_fallback(
        change_classes=classes,
        policy=active,
        inventory_complete=inventory_complete,
        is_merge=is_merge,
        merge_resolved=resolved,
        parent_revision_ids=parent_revision_ids,
        selected_parent_revision=selected,
        repository_ids_match=old_state.repository_id == new_state.repository_id,
    )

    commitment = commit_changed_artifacts(changed, diff_algorithm=DIFF_ALGORITHM)
    old_dirty = old_state.dirty_overlay_cid
    new_dirty = new_state.dirty_overlay_cid
    dirty_present = old_dirty != ABSENCE_TOKEN or new_dirty != ABSENCE_TOKEN
    dirty_changed = old_dirty != new_dirty

    return RepositoryDiff(
        repository_id=new_state.repository_id,
        old_revision=old_state.revision,
        new_revision=new_state.revision,
        old_repository_state_cid=old_state.identity_cid(),
        new_repository_state_cid=new_state.identity_cid(),
        old_tree_cid=old_state.tree_cid,
        new_tree_cid=new_state.tree_cid,
        parent_revision_ids=parent_revision_ids,
        selected_parent_revision=selected,
        is_merge=is_merge,
        old_dirty_overlay_cid=old_dirty,
        new_dirty_overlay_cid=new_dirty,
        dirty_overlay_present=dirty_present,
        dirty_overlay_changed=dirty_changed,
        changed_artifacts=changed,
        changed_artifact_commitment=commitment,
        change_classes_present=tuple(sorted(classes)),
        complete=complete,
        ambiguous=ambiguous,
        full_fallback_required=full_fallback,
        requires_broad_invalidation=broad,
        inventory_complete=inventory_complete,
        merge_resolved=resolved,
        classification_policy_cid=active.policy_cid(),
    )


# ---------------------------------------------------------------------------
# Samples and known vectors
# ---------------------------------------------------------------------------


def _sample_cid(label: str) -> str:
    return canonical_cid({"ips_repository_diff_sample": label, "v": SCHEMA_MAJOR})


def _sample_bytes_cid(label: str) -> tuple[str, int]:
    data = f"{label}\n".encode()
    # Use structured CID via identity helper for hermetic tests that do not
    # require raw-byte CIDs; content identity still changes with label.
    return _sample_cid(f"bytes:{label}"), len(data)


def sample_artifact(
    path: str,
    *,
    label: str | None = None,
    layer: ArtifactLayer | str = ArtifactLayer.TREE,
    byte_length: int | None = None,
) -> ArtifactSnapshot:
    content_label = label if label is not None else path
    content_cid, default_len = _sample_bytes_cid(content_label)
    return ArtifactSnapshot(
        path=path,
        content_cid=content_cid,
        byte_length=default_len if byte_length is None else byte_length,
        layer=layer,
    )


def sample_repository_state(
    *,
    repository_id: str = "repo/datasets",
    revision: str = "rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    tree_label: str = "tree-clean",
    dirty_overlay_cid: str = ABSENCE_TOKEN,
    parent_revision_ids: Sequence[str] = (),
) -> RepositoryState:
    return RepositoryState(
        repository_id=repository_id,
        revision=revision,
        tree_cid=_sample_cid(tree_label),
        dirty_overlay_cid=dirty_overlay_cid,
        parent_revision_ids=tuple(parent_revision_ids),
    )


def sample_classification_policy(**overrides: Any) -> PathClassificationPolicy:
    payload: dict[str, Any] = {
        "interface_paths": ("pkg/api.py",),
        "checked_specification_paths": ("docs/checked/soundness.md",),
        "generated_input_paths": ("generated/inputs/case-a.json",),
        "class_overrides": (),
        "treat_unknown_as_ambiguous": True,
        "treat_dependency_lock_as_full_fallback": False,
    }
    payload.update(overrides)
    return PathClassificationPolicy(**payload)


def sample_changed_artifacts(
    policy: PathClassificationPolicy | None = None,
) -> tuple[ChangedArtifact, ...]:
    """Hermetic multi-class change set covering IPS-015 classification axes."""

    active = policy if policy is not None else sample_classification_policy()
    old_inventory = (
        sample_artifact("pkg/main.py", label="main-v1"),
        sample_artifact("pkg/api.py", label="api-v1"),
        sample_artifact("tests/test_main.py", label="test-v1"),
        sample_artifact("tests/fixtures/data.json", label="fixture-v1"),
        sample_artifact("poetry.lock", label="lock-v1"),
        sample_artifact("config/app.toml", label="config-v1"),
        sample_artifact("circuits/prove.circom", label="circuit-v1"),
        sample_artifact("keys/pk_main.pkey", label="pk-v1"),
        sample_artifact("keys/vk_main.vkey", label="vk-v1"),
        sample_artifact("selectors/unit.json", label="selector-v1"),
        sample_artifact("policy/verification_policy.json", label="policy-v1"),
        sample_artifact("policy/network_policy.json", label="net-v1"),
        sample_artifact("meta/canonicalization.json", label="canon-v1"),
        sample_artifact("environment/trust_policy.json", label="env-v1"),
        sample_artifact("docs/guide.md", label="docs-v1"),
        sample_artifact("docs/checked/soundness.md", label="checked-v1"),
        sample_artifact("generated/inputs/case-a.json", label="gen-v1"),
    )
    new_inventory = (
        sample_artifact("pkg/main.py", label="main-v2"),
        sample_artifact("pkg/api.py", label="api-v2"),
        sample_artifact("tests/test_main.py", label="test-v2"),
        sample_artifact("tests/test_new.py", label="test-new"),
        sample_artifact("tests/fixtures/data.json", label="fixture-v2"),
        sample_artifact("poetry.lock", label="lock-v2"),
        sample_artifact("config/app.toml", label="config-v2"),
        sample_artifact("circuits/prove.circom", label="circuit-v2"),
        sample_artifact("keys/pk_main.pkey", label="pk-v2"),
        sample_artifact("keys/vk_main.vkey", label="vk-v2"),
        sample_artifact("selectors/unit.json", label="selector-v2"),
        sample_artifact("policy/verification_policy.json", label="policy-v2"),
        sample_artifact("policy/network_policy.json", label="net-v2"),
        sample_artifact("meta/canonicalization.json", label="canon-v2"),
        sample_artifact("environment/trust_policy.json", label="env-v2"),
        sample_artifact("docs/guide.md", label="docs-v2"),
        sample_artifact("docs/checked/soundness.md", label="checked-v2"),
        sample_artifact("generated/inputs/case-a.json", label="gen-v2"),
        # deleted: none from old except we drop nothing common; add-only path above
    )
    # Explicit delete of an old-only test helper.
    old_with_delete = old_inventory + (
        sample_artifact("tests/test_removed.py", label="test-removed"),
    )
    return diff_artifact_inventories(old_with_delete, new_inventory, policy=active)


def sample_repository_diff(**overrides: Any) -> RepositoryDiff:
    policy = sample_classification_policy()
    old_state = sample_repository_state(
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tree_label="tree-old",
        parent_revision_ids=(),
    )
    new_state = sample_repository_state(
        revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        tree_label="tree-new",
        parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
    )
    old_artifacts = (
        sample_artifact("pkg/main.py", label="main-v1"),
        sample_artifact("docs/guide.md", label="docs-v1"),
    )
    new_artifacts = (
        sample_artifact("pkg/main.py", label="main-v2"),
        sample_artifact("docs/guide.md", label="docs-v1"),
    )
    result = diff_repository_states(
        old_state,
        new_state,
        old_artifacts=old_artifacts,
        new_artifacts=new_artifacts,
        policy=policy,
        inventory_complete=True,
        selected_parent_revision=old_state.revision,
        merge_resolved=True,
    )
    if not overrides:
        return result
    payload = result.to_canonical()
    payload.update(overrides)
    return RepositoryDiff.from_canonical(payload)


def known_vectors() -> dict[str, Any]:
    """Versioned hermetic vectors for repository-diff evidence."""

    policy = sample_classification_policy()
    multi = sample_changed_artifacts(policy)
    commitment_a = commit_changed_artifacts(multi)
    commitment_b = commit_changed_artifacts(tuple(reversed(multi)))
    assert commitment_a == commitment_b

    # Ordinary docs vs checked specification vs generated input.
    docs_old = (
        sample_artifact("docs/guide.md", label="guide-v1"),
        sample_artifact("docs/checked/soundness.md", label="checked-v1"),
        sample_artifact("generated/inputs/case-a.json", label="gen-v1"),
    )
    docs_new = (
        sample_artifact("docs/guide.md", label="guide-v2"),
        sample_artifact("docs/checked/soundness.md", label="checked-v2"),
        sample_artifact("generated/inputs/case-a.json", label="gen-v2"),
    )
    docs_diff = diff_artifact_inventories(docs_old, docs_new, policy=policy)
    docs_classes = {item.path: item.change_class.value for item in docs_diff}

    # Dirty overlay explicit change.
    dirty_cid = _sample_cid("dirty-overlay-v1")
    clean_state = sample_repository_state(
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tree_label="tree-shared",
        dirty_overlay_cid=ABSENCE_TOKEN,
    )
    dirty_state = sample_repository_state(
        revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tree_label="tree-shared",
        dirty_overlay_cid=dirty_cid,
        parent_revision_ids=(),
    )
    dirty_old = (sample_artifact("pkg/main.py", label="main-clean", layer="tree"),)
    dirty_new = (
        sample_artifact("pkg/main.py", label="main-clean", layer="tree"),
        sample_artifact(
            "pkg/main.py", label="main-dirty", layer=ArtifactLayer.DIRTY_OVERLAY
        ),
    )
    dirty_diff = diff_repository_states(
        clean_state,
        dirty_state,
        old_artifacts=dirty_old,
        new_artifacts=dirty_new,
        policy=policy,
        inventory_complete=True,
        selected_parent_revision=clean_state.revision,
        merge_resolved=True,
    )

    # Merge with complete resolution.
    parent_a = "rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    parent_b = "rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    merge_old = sample_repository_state(
        revision=parent_a,
        tree_label="tree-parent-a",
        parent_revision_ids=(),
    )
    merge_new = sample_repository_state(
        revision="rev-cccccccccccccccccccccccccccccccccccccccc",
        tree_label="tree-merge",
        parent_revision_ids=tuple(sorted((parent_a, parent_b))),
    )
    merge_diff = diff_repository_states(
        merge_old,
        merge_new,
        old_artifacts=(sample_artifact("pkg/main.py", label="merge-a"),),
        new_artifacts=(sample_artifact("pkg/main.py", label="merge-c"),),
        policy=policy,
        inventory_complete=True,
        selected_parent_revision=parent_a,
        merge_resolved=True,
    )
    merge_ambiguous = diff_repository_states(
        merge_old,
        merge_new,
        old_artifacts=(sample_artifact("pkg/main.py", label="merge-a"),),
        new_artifacts=(sample_artifact("pkg/main.py", label="merge-c"),),
        policy=policy,
        inventory_complete=True,
        selected_parent_revision=parent_a,
        merge_resolved=False,
    )

    # Unknown class forces full fallback under default policy.
    unknown_diff = diff_repository_states(
        sample_repository_state(tree_label="tree-u1"),
        sample_repository_state(
            revision="rev-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            tree_label="tree-u2",
            parent_revision_ids=("rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
        ),
        old_artifacts=(sample_artifact("blob.bin", label="blob-v1"),),
        new_artifacts=(sample_artifact("blob.bin", label="blob-v2"),),
        policy=policy,
        inventory_complete=True,
        selected_parent_revision="rev-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        merge_resolved=True,
    )

    class_coverage = sorted({item.change_class.value for item in multi})

    return {
        "schema": f"{REPOSITORY_DIFF_NAMESPACE}/known-vectors@{SCHEMA_MAJOR}",
        "diff_subset": REPOSITORY_DIFF_SUBSET,
        "diff_algorithm": DIFF_ALGORITHM,
        "diff_algorithm_version": DIFF_ALGORITHM_VERSION,
        "commitment_order_invariant": commitment_a == commitment_b,
        "changed_artifact_commitment": commitment_a,
        "multi_class_change_classes": class_coverage,
        "documentation_distinction": docs_classes,
        "dirty_overlay_diff": {
            "identity_cid": dirty_diff.identity_cid(),
            "dirty_overlay_present": dirty_diff.dirty_overlay_present,
            "dirty_overlay_changed": dirty_diff.dirty_overlay_changed,
            "from_dirty_overlay_paths": [
                item.path
                for item in dirty_diff.changed_artifacts
                if item.from_dirty_overlay
            ],
        },
        "merge_resolved": {
            "identity_cid": merge_diff.identity_cid(),
            "is_merge": merge_diff.is_merge,
            "parent_revision_ids": list(merge_diff.parent_revision_ids),
            "full_fallback_required": merge_diff.full_fallback_required,
            "complete": merge_diff.complete,
        },
        "merge_unresolved": {
            "identity_cid": merge_ambiguous.identity_cid(),
            "full_fallback_required": merge_ambiguous.full_fallback_required,
            "ambiguous": merge_ambiguous.ambiguous,
            "complete": merge_ambiguous.complete,
        },
        "unknown_forces_fallback": {
            "identity_cid": unknown_diff.identity_cid(),
            "change_classes_present": list(unknown_diff.change_classes_present),
            "full_fallback_required": unknown_diff.full_fallback_required,
            "ambiguous": unknown_diff.ambiguous,
        },
    }


__all__ = (
    "ARTIFACT_LAYERS",
    "BROAD_INVALIDATION_CHANGE_CLASSES",
    "CHANGE_ACTIONS",
    "CHANGE_CLASSES",
    "CHANGED_ARTIFACT_SCHEMA",
    "DIFF_ALGORITHM",
    "DIFF_ALGORITHM_VERSION",
    "DIFF_SCHEMA_VERSION",
    "FULL_FALLBACK_CHANGE_CLASSES",
    "REPOSITORY_DIFF_SCHEMA",
    "REPOSITORY_DIFF_SUBSET",
    "ArtifactLayer",
    "ArtifactSnapshot",
    "ChangeAction",
    "ChangeClass",
    "ChangedArtifact",
    "PathClassificationPolicy",
    "RepositoryDiff",
    "RepositoryDiffError",
    "classify_path",
    "closed_artifact_layers",
    "closed_change_actions",
    "closed_change_classes",
    "commit_changed_artifacts",
    "diff_artifact_inventories",
    "diff_repository_states",
    "known_vectors",
    "parse_artifact_layer",
    "parse_change_action",
    "parse_change_class",
    "sample_artifact",
    "sample_changed_artifacts",
    "sample_classification_policy",
    "sample_repository_diff",
    "sample_repository_state",
)
