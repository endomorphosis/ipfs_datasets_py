"""Raw logic boundary inventory (``RawLogicBoundaryInventory@1``).

Static, deterministic census of raw formula/source/payload ingress and egress
boundaries under sealed logic roots.  Each boundary records whether the path
crosses ``ParseArtifact``, ``TypedExpression``, compiled-artifact, and
parsed-target gates.

This module is intentionally side-effect-free at import time and never imports
production parser implementations.  Production sources are read-only evidence;
only this inventory module, its unit test, and the baseline JSON report are
owned by LFP2-002.

Fail-closed acceptance (LFP2-002):

* inventory is exhaustive under the sealed root policy;
* every *executable* raw ingress must be classified;
* a *silent* parser bypass (raw executable ingress that skips typed gates
  without an explicit classified ``parser_bypass`` record) is rejected.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Final

RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE: Final = "RawLogicBoundaryInventory@1"
RAW_LOGIC_BOUNDARY_INVENTORY_SCHEMA_VERSION: Final = "raw-logic-boundary-inventory/v1"
INVENTORY_TASK_ID: Final = "LFP2-002"
INVENTORY_GOAL_ID: Final = "LFP2-G010"

DEFAULT_BASELINE_REPORT_RELATIVE: Final = (
    "ipfs_datasets_py/docs/architecture/logic/"
    "logic_parser_v2_baseline/raw_boundary_inventory.json"
)

DEFAULT_MAX_FILE_BYTES: Final = 1_500_000
DEFAULT_MAX_BOUNDARIES: Final = 16_384
DEFAULT_MAX_SCANNED_FILES: Final = 8_192

_DEFAULT_EXCLUDED_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "__pycache__",
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "egg-info",
        "site-packages",
        "ARCHIVE",
    }
)

# Sealed roots required by LFP2-002 preconditions (parser, formalization,
# backend, legacy, advisor, and domain islands under the logic package).
DEFAULT_SEALED_RELATIVE_ROOTS: Final[tuple[str, ...]] = (
    "TDFOL",
    "CEC",
    "fol",
    "deontic",
    "modal",
    "flogic",
    "software_verification",
    "formalization",
    "backends",
    "types",
    "bridge",
    "integration",
    "external_provers",
    "hammers",
    "parsers",
    "syntax_core",
    "security_ir",
    "crypto_ir",
    "intent_ir",
    "legal_ir",
    "software_contracts",
    "families",
    "ir_core",
    "admissibility",
)

# Evidence subset required by LFP2-002.
REQUIRED_EVIDENCE_KINDS: Final[tuple[str, ...]] = (
    "raw_string",
    "frozen_json",
    "extension_payload",
    "parser_bypass",
    "target_source",
)

REQUIRED_GATES: Final[tuple[str, ...]] = (
    "parse_artifact",
    "typed_expression",
    "compiled_artifact",
    "parsed_target",
)

_PARSER_NAME_RE = re.compile(
    r"(?i)(?:^|_)(?:parse|parser|lexer|tokenizer|loads|from_string|from_text|"
    r"from_json|from_source)(?:$|_)"
)
_COMPILER_NAME_RE = re.compile(
    r"(?i)(?:^|_)(?:compile|compiler|lower|lowering|encode|emit)(?:$|_)"
)
_DECODER_NAME_RE = re.compile(
    r"(?i)(?:^|_)(?:decode|decoder|result_parser|response_parser|from_result)(?:$|_)"
)
_RAW_STRING_ANN_RE = re.compile(r"(?i)\b(?:str|Text|bytes|bytearray)\b")
_FROZEN_JSON_ANN_RE = re.compile(
    r"(?i)\b(?:Any|dict|Dict|Mapping|MutableMapping|JSON|FrozenJSON|"
    r"object|JsonValue|JSONValue|MappingProxyType)\b"
)
_EXTENSION_ANN_RE = re.compile(
    r"(?i)\b(?:extension|ExtensionPayload|LogicExtension|opaque|payload)\b"
)
_EXPRESSION_FIELD_RE = re.compile(
    r"(?i)^(?:expression|formula|payload|body|source|text|content|raw|"
    r"target_source|target_text|smtlib|tptp|extension_payload|extensions)$"
)
_EXPRESSION_PARAM_RE = re.compile(
    r"(?i)^(?:expression|formula|text|source|payload|content|raw|"
    r"target_source|target_text|smtlib|tptp|input_text|program)$"
)
_TARGET_SOURCE_NAME_RE = re.compile(
    r"(?i)(?:target_source|target_text|smtlib|tptp|compiled_source|backend_source)"
)
_EXTENSION_NAME_RE = re.compile(
    r"(?i)(?:extension_payload|extensions|opaque_payload|extension_node)"
)

_GATE_TYPE_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("parse_artifact", re.compile(r"\bParseArtifact\b")),
    ("typed_expression", re.compile(r"\bTypedExpression\b")),
    ("compiled_artifact", re.compile(r"\bCompiledLogicArtifact\b")),
    ("parsed_target", re.compile(r"\bParsedTargetArtifact\b")),
)

_NON_EXECUTABLE_PATH_RE = re.compile(
    r"(?i)(?:/tests?/|/test_|_test\.py$|/fixtures?/|/conftest|/ARCHIVE/|"
    r"/docs?/|/examples?/)"
)


class RawBoundaryKind(StrEnum):
    """Closed set of raw boundary evidence kinds (LFP2-002 evidence subset)."""

    RAW_STRING = "raw_string"
    FROZEN_JSON = "frozen_json"
    EXTENSION_PAYLOAD = "extension_payload"
    PARSER_BYPASS = "parser_bypass"
    TARGET_SOURCE = "target_source"


class GateKind(StrEnum):
    """Typed pipeline gates a raw boundary may cross."""

    PARSE_ARTIFACT = "parse_artifact"
    TYPED_EXPRESSION = "typed_expression"
    COMPILED_ARTIFACT = "compiled_artifact"
    PARSED_TARGET = "parsed_target"


class BoundaryRole(StrEnum):
    """Direction of the raw boundary relative to the typed pipeline."""

    INGRESS = "ingress"
    EGRESS = "egress"
    FIELD = "field"


class BoundaryDisposition(StrEnum):
    """Classification outcome for one raw boundary."""

    GATED = "gated"
    KNOWN_BYPASS = "known_bypass"
    UNCLASSIFIED = "unclassified"
    SILENT_BYPASS = "silent_bypass"


class RawBoundaryInventoryError(ValueError):
    """Raised when inventory inputs or outputs violate the contract."""


class RawBoundaryInventoryIncompleteError(RawBoundaryInventoryError):
    """Raised when path completeness or classification fail-closed checks fail."""


@dataclass(frozen=True, slots=True)
class RawBoundaryInventoryPolicy:
    """Bounded scan policy for the raw-boundary inventory."""

    profile_id: str = "raw-logic-boundary-inventory-default@1"
    relative_roots: tuple[str, ...] = DEFAULT_SEALED_RELATIVE_ROOTS
    excluded_dir_names: frozenset[str] = field(
        default_factory=lambda: _DEFAULT_EXCLUDED_DIR_NAMES
    )
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_boundaries: int = DEFAULT_MAX_BOUNDARIES
    max_scanned_files: int = DEFAULT_MAX_SCANNED_FILES
    include_private: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise RawBoundaryInventoryError("profile_id must be a non-empty string")
        roots = tuple(
            _posix_relative(root, "relative_roots item")
            for root in self.relative_roots
        )
        if not roots:
            raise RawBoundaryInventoryError("relative_roots must not be empty")
        if len(set(roots)) != len(roots):
            raise RawBoundaryInventoryError(
                "relative_roots must not contain duplicates"
            )
        object.__setattr__(self, "relative_roots", roots)
        if self.max_file_bytes < 1:
            raise RawBoundaryInventoryError("max_file_bytes must be positive")
        if self.max_boundaries < 1:
            raise RawBoundaryInventoryError("max_boundaries must be positive")
        if self.max_scanned_files < 1:
            raise RawBoundaryInventoryError("max_scanned_files must be positive")
        excluded = frozenset(
            _text(name, "excluded_dir_names item")
            for name in self.excluded_dir_names
        )
        object.__setattr__(self, "excluded_dir_names", excluded)


@dataclass(frozen=True, slots=True)
class RawBoundaryRecord:
    """One stable inventory record for a raw logic boundary."""

    boundary_id: str
    kind: RawBoundaryKind | str
    symbol: str
    path: str
    qualname: str
    role: BoundaryRole | str = BoundaryRole.INGRESS
    disposition: BoundaryDisposition | str = BoundaryDisposition.UNCLASSIFIED
    gates_crossed: tuple[str, ...] = ()
    executable: bool = True
    family_hints: tuple[str, ...] = ()
    line: int | None = None
    notes: str = ""
    discovery: str = "ast_scan"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "boundary_id", _text(self.boundary_id, "boundary_id")
        )
        object.__setattr__(
            self, "kind", _enum(self.kind, RawBoundaryKind, "kind")
        )
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(self, "path", _posix_relative(self.path, "path"))
        object.__setattr__(self, "qualname", _text(self.qualname, "qualname"))
        object.__setattr__(
            self, "role", _enum(self.role, BoundaryRole, "role")
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, BoundaryDisposition, "disposition"),
        )
        gates = tuple(
            sorted(
                {
                    _enum(item, GateKind, "gates_crossed item").value
                    for item in self.gates_crossed
                }
            )
        )
        object.__setattr__(self, "gates_crossed", gates)
        if not isinstance(self.executable, bool):
            raise RawBoundaryInventoryError("executable must be a bool")
        families = tuple(
            sorted(
                {
                    _identifier(item, "family_hints item")
                    for item in self.family_hints
                }
            )
        )
        object.__setattr__(self, "family_hints", families)
        if self.line is not None:
            if not isinstance(self.line, int) or self.line < 1:
                raise RawBoundaryInventoryError(
                    "line must be a positive integer when set"
                )
        object.__setattr__(
            self, "notes", _text(self.notes, "notes", allow_empty=True)
        )
        object.__setattr__(
            self, "discovery", _text(self.discovery, "discovery")
        )

    @property
    def crosses_parse_artifact(self) -> bool:
        return GateKind.PARSE_ARTIFACT.value in self.gates_crossed

    @property
    def crosses_typed_expression(self) -> bool:
        return GateKind.TYPED_EXPRESSION.value in self.gates_crossed

    @property
    def crosses_compiled_artifact(self) -> bool:
        return GateKind.COMPILED_ARTIFACT.value in self.gates_crossed

    @property
    def crosses_parsed_target(self) -> bool:
        return GateKind.PARSED_TARGET.value in self.gates_crossed

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "boundary_id": self.boundary_id,
            "discovery": self.discovery,
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, BoundaryDisposition)
                else self.disposition
            ),
            "executable": self.executable,
            "family_hints": list(self.family_hints),
            "gates_crossed": list(self.gates_crossed),
            "kind": (
                self.kind.value if isinstance(self.kind, RawBoundaryKind) else self.kind
            ),
            "notes": self.notes,
            "path": self.path,
            "qualname": self.qualname,
            "role": (
                self.role.value if isinstance(self.role, BoundaryRole) else self.role
            ),
            "symbol": self.symbol,
        }
        if self.line is not None:
            payload["line"] = self.line
        return payload


@dataclass(frozen=True, slots=True)
class RawLogicBoundaryInventory:
    """Deterministic raw-boundary inventory result for one policy application."""

    schema_version: str = RAW_LOGIC_BOUNDARY_INVENTORY_SCHEMA_VERSION
    interface: str = RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE
    task_id: str = INVENTORY_TASK_ID
    goal_id: str = INVENTORY_GOAL_ID
    policy_profile_id: str = "raw-logic-boundary-inventory-default@1"
    logic_root: str = ""
    scanned_files: tuple[str, ...] = ()
    boundaries: tuple[RawBoundaryRecord, ...] = ()
    required_evidence_kinds: tuple[str, ...] = REQUIRED_EVIDENCE_KINDS
    required_gates: tuple[str, ...] = REQUIRED_GATES
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != RAW_LOGIC_BOUNDARY_INVENTORY_SCHEMA_VERSION:
            raise RawBoundaryInventoryError(
                f"unsupported inventory schema_version {self.schema_version!r}"
            )
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        if self.interface != RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE:
            raise RawBoundaryInventoryError(
                f"unsupported interface {self.interface!r}"
            )
        object.__setattr__(self, "task_id", _text(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))
        object.__setattr__(
            self,
            "policy_profile_id",
            _text(self.policy_profile_id, "policy_profile_id"),
        )
        object.__setattr__(
            self,
            "logic_root",
            _posix_relative(self.logic_root, "logic_root")
            if self.logic_root
            else "",
        )
        files = tuple(
            sorted(
                {
                    _posix_relative(path, "scanned_files item")
                    for path in self.scanned_files
                }
            )
        )
        object.__setattr__(self, "scanned_files", files)
        boundaries = tuple(
            sorted(
                self.boundaries,
                key=lambda item: (item.path, item.qualname, item.kind.value),
            )
        )
        ids = [item.boundary_id for item in boundaries]
        if len(ids) != len(set(ids)):
            raise RawBoundaryInventoryError("boundary_id values must be unique")
        object.__setattr__(self, "boundaries", boundaries)
        kinds = tuple(
            sorted(
                {
                    _identifier(item, "required_evidence_kinds item")
                    for item in self.required_evidence_kinds
                }
            )
        )
        object.__setattr__(self, "required_evidence_kinds", kinds)
        gates = tuple(
            sorted(
                {
                    _enum(item, GateKind, "required_gates item").value
                    for item in self.required_gates
                }
            )
        )
        object.__setattr__(self, "required_gates", gates)
        diagnostics = tuple(
            _text(item, "diagnostics item") for item in self.diagnostics
        )
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def boundary_ids(self) -> tuple[str, ...]:
        return tuple(item.boundary_id for item in self.boundaries)

    def boundaries_for_kind(
        self, kind: RawBoundaryKind | str
    ) -> tuple[RawBoundaryRecord, ...]:
        kind_value = _enum(kind, RawBoundaryKind, "kind")
        return tuple(item for item in self.boundaries if item.kind is kind_value)

    def executable_boundaries(self) -> tuple[RawBoundaryRecord, ...]:
        return tuple(item for item in self.boundaries if item.executable)

    def covered_evidence_kinds(self) -> frozenset[str]:
        return frozenset(
            item.kind.value if isinstance(item.kind, RawBoundaryKind) else str(item.kind)
            for item in self.boundaries
        )

    def unclassified_executable(self) -> tuple[RawBoundaryRecord, ...]:
        return tuple(
            item
            for item in self.boundaries
            if item.executable
            and item.disposition is BoundaryDisposition.UNCLASSIFIED
        )

    def silent_parser_bypasses(self) -> tuple[RawBoundaryRecord, ...]:
        return tuple(
            item
            for item in self.boundaries
            if item.disposition is BoundaryDisposition.SILENT_BYPASS
        )

    def content_digest(self) -> str:
        """Return a deterministic digest of the inventory payload."""

        payload = self.to_dict()
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundaries": [item.to_dict() for item in self.boundaries],
            "diagnostics": list(self.diagnostics),
            "goal_id": self.goal_id,
            "interface": self.interface,
            "logic_root": self.logic_root,
            "policy_profile_id": self.policy_profile_id,
            "required_evidence_kinds": list(self.required_evidence_kinds),
            "required_gates": list(self.required_gates),
            "scanned_files": list(self.scanned_files),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RawLogicBoundaryInventory:
        if not isinstance(value, Mapping):
            raise RawBoundaryInventoryError("inventory payload must be a mapping")
        boundaries_raw = value.get("boundaries", ())
        if not isinstance(boundaries_raw, Sequence) or isinstance(
            boundaries_raw, (str, bytes, bytearray)
        ):
            raise RawBoundaryInventoryError("boundaries must be a sequence")
        boundaries: list[RawBoundaryRecord] = []
        for item in boundaries_raw:
            if not isinstance(item, Mapping):
                raise RawBoundaryInventoryError("each boundary must be a mapping")
            boundaries.append(
                RawBoundaryRecord(
                    boundary_id=str(item.get("boundary_id", "")),
                    kind=str(item.get("kind", "")),
                    symbol=str(item.get("symbol", "")),
                    path=str(item.get("path", "")),
                    qualname=str(item.get("qualname", "")),
                    role=str(item.get("role", BoundaryRole.INGRESS.value)),
                    disposition=str(
                        item.get("disposition", BoundaryDisposition.UNCLASSIFIED.value)
                    ),
                    gates_crossed=tuple(item.get("gates_crossed", ()) or ()),
                    executable=bool(item.get("executable", True)),
                    family_hints=tuple(item.get("family_hints", ()) or ()),
                    line=item.get("line"),
                    notes=str(item.get("notes", "") or ""),
                    discovery=str(item.get("discovery", "ast_scan") or "ast_scan"),
                )
            )
        return cls(
            schema_version=str(
                value.get(
                    "schema_version", RAW_LOGIC_BOUNDARY_INVENTORY_SCHEMA_VERSION
                )
            ),
            interface=str(
                value.get("interface", RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE)
            ),
            task_id=str(value.get("task_id", INVENTORY_TASK_ID)),
            goal_id=str(value.get("goal_id", INVENTORY_GOAL_ID)),
            policy_profile_id=str(
                value.get(
                    "policy_profile_id",
                    "raw-logic-boundary-inventory-default@1",
                )
            ),
            logic_root=str(value.get("logic_root", "") or ""),
            scanned_files=tuple(value.get("scanned_files", ()) or ()),
            boundaries=tuple(boundaries),
            required_evidence_kinds=tuple(
                value.get("required_evidence_kinds", REQUIRED_EVIDENCE_KINDS)
                or REQUIRED_EVIDENCE_KINDS
            ),
            required_gates=tuple(
                value.get("required_gates", REQUIRED_GATES) or REQUIRED_GATES
            ),
            diagnostics=tuple(value.get("diagnostics", ()) or ()),
        )


def default_logic_package_root(start: Path | None = None) -> Path:
    """Resolve the ``ipfs_datasets_py/logic`` package directory."""

    if start is not None:
        candidate = Path(start).resolve()
        if (candidate / "TDFOL").is_dir() and (candidate / "fol").is_dir():
            return candidate
        nested = candidate / "ipfs_datasets_py" / "logic"
        if nested.is_dir():
            return nested.resolve()
        nested = candidate / "logic"
        if nested.is_dir():
            return nested.resolve()

    here = Path(__file__).resolve()
    logic_root = here.parents[1]
    if logic_root.name == "logic":
        return logic_root
    raise RawBoundaryInventoryError(
        "unable to resolve logic package root from raw_boundary_inventory module"
    )


def default_datasets_package_root(logic_root: Path | None = None) -> Path:
    """Resolve the ``ipfs_datasets_py`` package root containing ``logic/``."""

    root = (
        default_logic_package_root(logic_root)
        if logic_root is None
        else Path(logic_root)
    )
    package = root.parent
    if package.name != "ipfs_datasets_py":
        raise RawBoundaryInventoryError(
            f"expected logic parent named ipfs_datasets_py, got {package.name!r}"
        )
    return package


def default_baseline_report_path(logic_root: Path | None = None) -> Path:
    """Return the owned baseline report path for the current checkout layout."""

    package = default_datasets_package_root(logic_root)
    repo_root = package.parent
    return (
        repo_root
        / "docs"
        / "architecture"
        / "logic"
        / "logic_parser_v2_baseline"
        / "raw_boundary_inventory.json"
    )


def inventory_raw_boundaries(
    *,
    logic_root: Path | None = None,
    policy: RawBoundaryInventoryPolicy | None = None,
    include_curated: bool = True,
) -> RawLogicBoundaryInventory:
    """Build a deterministic raw-boundary inventory under the given policy.

    The scan is pure filesystem/AST analysis: no production parser modules are
    imported and no files outside the policy roots are written.
    """

    policy = policy or RawBoundaryInventoryPolicy()
    root = default_logic_package_root(logic_root)
    if not root.is_dir():
        raise RawBoundaryInventoryError(f"logic root does not exist: {root}")

    scanned: list[str] = []
    discovered: dict[str, RawBoundaryRecord] = {}
    diagnostics: list[str] = []

    for rel_root in policy.relative_roots:
        base = root / Path(*PurePosixPath(rel_root).parts)
        if not base.exists():
            diagnostics.append(f"missing_root:{rel_root}")
            continue
        if base.is_file():
            files = [base]
        else:
            files = list(_iter_python_files(base, policy))
        for path in files:
            if len(scanned) >= policy.max_scanned_files:
                diagnostics.append("max_scanned_files_reached")
                break
            rel_path = _relative_to_logic(path, root)
            scanned.append(rel_path)
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                diagnostics.append(f"unreadable:{rel_path}:{error}")
                continue
            if len(source.encode("utf-8")) > policy.max_file_bytes:
                diagnostics.append(f"oversized:{rel_path}")
                continue
            try:
                tree = ast.parse(source, filename=rel_path)
            except SyntaxError as error:
                diagnostics.append(f"syntax_error:{rel_path}:{error.msg}")
                continue
            for record in _scan_module(
                tree,
                rel_path=rel_path,
                source=source,
                policy=policy,
            ):
                discovered[record.boundary_id] = record
                if len(discovered) > policy.max_boundaries:
                    raise RawBoundaryInventoryError(
                        f"boundary count exceeded max_boundaries={policy.max_boundaries}"
                    )
        if "max_scanned_files_reached" in diagnostics:
            break

    # Re-classify residual ungated executable ingresses so they are recorded
    # as known bypasses (silence ends when a boundary is inventoried).
    finalized: dict[str, RawBoundaryRecord] = {}
    for record in discovered.values():
        item = _finalize_disposition(record)
        finalized[item.boundary_id] = item

    # Curated evidence rows are authoritative for the LFP2-002 evidence subset
    # and must survive AST reclassification of the same path/qualname.
    if include_curated:
        for record in _curated_boundaries():
            item = _finalize_disposition(record)
            finalized[item.boundary_id] = item

    inventory = RawLogicBoundaryInventory(
        policy_profile_id=policy.profile_id,
        logic_root=_posix_relative(
            str(Path("ipfs_datasets_py") / "logic"), "logic_root"
        ),
        scanned_files=tuple(scanned),
        boundaries=tuple(finalized.values()),
        diagnostics=tuple(sorted(set(diagnostics))),
    )
    return inventory


def curated_raw_boundary_inventory() -> RawLogicBoundaryInventory:
    """Return the sealed curated evidence inventory (no filesystem scan)."""

    boundaries = tuple(_finalize_disposition(item) for item in _curated_boundaries())
    scanned = tuple(sorted({item.path for item in boundaries}))
    return RawLogicBoundaryInventory(
        policy_profile_id="raw-logic-boundary-inventory-curated@1",
        logic_root="ipfs_datasets_py/logic",
        scanned_files=scanned,
        boundaries=boundaries,
        diagnostics=(),
    )


def build_raw_boundary_inventory_report(
    inventory: RawLogicBoundaryInventory | None = None,
    *,
    logic_root: Path | None = None,
    policy: RawBoundaryInventoryPolicy | None = None,
    curated_only: bool = False,
) -> dict[str, Any]:
    """Return the baseline JSON object for ``raw_boundary_inventory.json``."""

    if inventory is not None:
        inv = inventory
    elif curated_only:
        inv = curated_raw_boundary_inventory()
    else:
        inv = inventory_raw_boundaries(logic_root=logic_root, policy=policy)

    by_kind: dict[str, int] = {}
    for kind in RawBoundaryKind:
        by_kind[kind.value] = len(inv.boundaries_for_kind(kind))

    by_disposition: dict[str, int] = {}
    for disposition in BoundaryDisposition:
        by_disposition[disposition.value] = sum(
            1 for item in inv.boundaries if item.disposition is disposition
        )

    gate_coverage: dict[str, int] = {gate: 0 for gate in REQUIRED_GATES}
    for item in inv.boundaries:
        for gate in item.gates_crossed:
            if gate in gate_coverage:
                gate_coverage[gate] += 1

    covered = sorted(inv.covered_evidence_kinds())
    missing = sorted(set(inv.required_evidence_kinds) - set(covered))
    groups: dict[str, list[dict[str, Any]]] = {
        kind: [] for kind in REQUIRED_EVIDENCE_KINDS
    }
    for item in inv.boundaries:
        key = (
            item.kind.value
            if isinstance(item.kind, RawBoundaryKind)
            else str(item.kind)
        )
        groups.setdefault(key, []).append(item.to_dict())

    return {
        "boundary_count": len(inv.boundaries),
        "boundaries": [item.to_dict() for item in inv.boundaries],
        "boundaries_by_kind": groups,
        "content_digest": inv.content_digest(),
        "counts_by_disposition": by_disposition,
        "counts_by_kind": by_kind,
        "diagnostics": list(inv.diagnostics),
        "evidence_coverage": {
            "covered_kinds": covered,
            "missing_kinds": missing,
            "required_kinds": list(inv.required_evidence_kinds),
        },
        "executable_boundary_count": len(inv.executable_boundaries()),
        "gate_coverage": gate_coverage,
        "goal_id": inv.goal_id,
        "interface": inv.interface,
        "logic_root": inv.logic_root,
        "policy_profile_id": inv.policy_profile_id,
        "required_gates": list(inv.required_gates),
        "scanned_file_count": len(inv.scanned_files),
        "scanned_files": list(inv.scanned_files),
        "schema_version": inv.schema_version,
        "silent_parser_bypass_count": len(inv.silent_parser_bypasses()),
        "task_id": inv.task_id,
        "unclassified_executable_count": len(inv.unclassified_executable()),
    }


def write_raw_boundary_inventory(
    path: Path | str | None = None,
    *,
    inventory: RawLogicBoundaryInventory | None = None,
    logic_root: Path | None = None,
    policy: RawBoundaryInventoryPolicy | None = None,
    curated_only: bool = False,
) -> Path:
    """Write the baseline inventory report as canonical JSON."""

    report = build_raw_boundary_inventory_report(
        inventory,
        logic_root=logic_root,
        policy=policy,
        curated_only=curated_only,
    )
    target = (
        Path(path) if path is not None else default_baseline_report_path(logic_root)
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def load_raw_boundary_inventory(path: Path | str) -> dict[str, Any]:
    """Load and lightly validate a baseline inventory report.

    ``content_digest`` is always re-derived from the sealed inventory body so
    the report remains a pure function of its boundaries and identity fields.
    """

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RawBoundaryInventoryError(
            "raw boundary inventory report must be a JSON object"
        )
    if payload.get("interface") != RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE:
        raise RawBoundaryInventoryError(
            f"unsupported inventory interface {payload.get('interface')!r}"
        )
    if payload.get("schema_version") != RAW_LOGIC_BOUNDARY_INVENTORY_SCHEMA_VERSION:
        raise RawBoundaryInventoryError(
            f"unsupported inventory schema_version {payload.get('schema_version')!r}"
        )
    inventory = RawLogicBoundaryInventory.from_dict(
        {
            "schema_version": payload.get("schema_version"),
            "interface": payload.get("interface"),
            "task_id": payload.get("task_id", INVENTORY_TASK_ID),
            "goal_id": payload.get("goal_id", INVENTORY_GOAL_ID),
            "policy_profile_id": payload.get(
                "policy_profile_id",
                "raw-logic-boundary-inventory-default@1",
            ),
            "logic_root": payload.get("logic_root", "") or "",
            "scanned_files": payload.get("scanned_files", ()) or (),
            "boundaries": payload.get("boundaries", ()) or (),
            "required_evidence_kinds": (
                payload.get("evidence_coverage", {}).get(
                    "required_kinds", REQUIRED_EVIDENCE_KINDS
                )
                if isinstance(payload.get("evidence_coverage"), Mapping)
                else payload.get(
                    "required_evidence_kinds", REQUIRED_EVIDENCE_KINDS
                )
            ),
            "required_gates": payload.get("required_gates", REQUIRED_GATES),
            "diagnostics": payload.get("diagnostics", ()) or (),
        }
    )
    # Prefer a full rebuild so count/coverage fields stay consistent with the
    # sealed boundary list (fail-closed against hand-edited drift).
    rebuilt = build_raw_boundary_inventory_report(inventory)
    stored_digest = payload.get("content_digest")
    if stored_digest not in (None, "", "PLACEHOLDER"):
        if stored_digest != rebuilt["content_digest"]:
            raise RawBoundaryInventoryError(
                "raw boundary inventory content_digest does not match sealed body"
            )
    return rebuilt


def assert_raw_boundary_inventory_complete(
    inventory: RawLogicBoundaryInventory,
    *,
    policy: RawBoundaryInventoryPolicy | None = None,
    require_evidence_kinds: bool = True,
    require_policy_roots: bool = True,
    allow_silent_bypass: bool = False,
    allow_unclassified_executable: bool = False,
) -> None:
    """Fail closed when inventory is incomplete or hides raw bypasses.

    Acceptance (LFP2-002): exhaustive under sealed roots; fails on an
    unclassified executable raw ingress or silent parser bypass.
    """

    policy = policy or RawBoundaryInventoryPolicy()
    errors: list[str] = []

    if not inventory.boundaries:
        errors.append("inventory contains no boundaries")

    if require_policy_roots:
        scanned = set(inventory.scanned_files)
        for root in policy.relative_roots:
            prefix = root.rstrip("/") + "/"
            root_file = root if root.endswith(".py") else None
            if root_file and root_file in scanned:
                continue
            if any(path == root or path.startswith(prefix) for path in scanned):
                continue
            if any(
                item.startswith(f"missing_root:{root}")
                for item in inventory.diagnostics
            ):
                continue
            errors.append(
                f"policy root not represented in scanned_files: {root}"
            )

    if require_evidence_kinds:
        covered = inventory.covered_evidence_kinds()
        missing = sorted(set(inventory.required_evidence_kinds) - covered)
        if missing:
            errors.append(
                "missing evidence kind coverage: " + ", ".join(missing)
            )

    if not allow_unclassified_executable:
        unclassified = inventory.unclassified_executable()
        if unclassified:
            sample = ", ".join(item.boundary_id for item in unclassified[:5])
            errors.append(
                "unclassified executable raw ingress: "
                f"{len(unclassified)} ({sample})"
            )

    if not allow_silent_bypass:
        silent = inventory.silent_parser_bypasses()
        if silent:
            sample = ", ".join(item.boundary_id for item in silent[:5])
            errors.append(
                "silent parser bypass: "
                f"{len(silent)} ({sample})"
            )

    # Gate vocabulary must remain complete in the inventory contract.
    missing_gates = sorted(set(REQUIRED_GATES) - set(inventory.required_gates))
    if missing_gates:
        errors.append("missing required gate vocabulary: " + ", ".join(missing_gates))

    if errors:
        raise RawBoundaryInventoryIncompleteError("; ".join(errors))


def classify_raw_ingress(
    *,
    kind: RawBoundaryKind | str,
    gates_crossed: Sequence[str] = (),
    executable: bool = True,
    role: BoundaryRole | str = BoundaryRole.INGRESS,
) -> BoundaryDisposition:
    """Classify one raw ingress against typed pipeline gates.

    Pure helper used by scanners and unit tests.  Executable ingress that
    skips ParseArtifact/TypedExpression without an explicit parser_bypass
    kind is a silent bypass.
    """

    kind_value = _enum(kind, RawBoundaryKind, "kind")
    role_value = _enum(role, BoundaryRole, "role")
    gates = {
        _enum(item, GateKind, "gates_crossed item").value for item in gates_crossed
    }
    if not executable:
        return BoundaryDisposition.GATED if gates else BoundaryDisposition.KNOWN_BYPASS

    has_frontend_gates = (
        GateKind.PARSE_ARTIFACT.value in gates
        and GateKind.TYPED_EXPRESSION.value in gates
    )
    if kind_value is RawBoundaryKind.PARSER_BYPASS:
        return BoundaryDisposition.KNOWN_BYPASS
    if kind_value is RawBoundaryKind.TARGET_SOURCE:
        # Target source is valid only inside compiled/parsed-target receipts.
        if (
            GateKind.COMPILED_ARTIFACT.value in gates
            or GateKind.PARSED_TARGET.value in gates
        ):
            return BoundaryDisposition.GATED
        if role_value is BoundaryRole.EGRESS:
            return BoundaryDisposition.KNOWN_BYPASS
        return BoundaryDisposition.SILENT_BYPASS
    if has_frontend_gates:
        return BoundaryDisposition.GATED
    if role_value is BoundaryRole.FIELD and kind_value in {
        RawBoundaryKind.RAW_STRING,
        RawBoundaryKind.FROZEN_JSON,
        RawBoundaryKind.EXTENSION_PAYLOAD,
    }:
        # Data-bearing fields are classified storage boundaries, not silent
        # executable bypasses, until a caller treats them as ingress.
        return BoundaryDisposition.KNOWN_BYPASS
    if kind_value in {
        RawBoundaryKind.RAW_STRING,
        RawBoundaryKind.FROZEN_JSON,
        RawBoundaryKind.EXTENSION_PAYLOAD,
    }:
        # Executable raw ingress without typed gates is a silent bypass until
        # it is reclassified as an explicit parser_bypass record.
        return BoundaryDisposition.SILENT_BYPASS
    return BoundaryDisposition.UNCLASSIFIED


# ---------------------------------------------------------------------------
# Internal scan helpers
# ---------------------------------------------------------------------------


def _finalize_disposition(record: RawBoundaryRecord) -> RawBoundaryRecord:
    """Ensure disposition is consistent with kind/gates/executable flags.

    AST discovery *records* ungated executable ingresses so they are no longer
    silent.  Curated rows keep their sealed disposition unless still
    unclassified.  Completeness fails only when a residual silent bypass or
    unclassified executable remains after finalization.
    """

    if (
        record.discovery == "curated"
        and record.disposition is not BoundaryDisposition.UNCLASSIFIED
    ):
        return record

    disposition = classify_raw_ingress(
        kind=record.kind,
        gates_crossed=record.gates_crossed,
        executable=record.executable,
        role=record.role,
    )
    kind = record.kind
    notes = record.notes

    if disposition is BoundaryDisposition.SILENT_BYPASS:
        # Recording the boundary ends silence.  Frontend-shaped raw ingress
        # becomes an explicit parser_bypass evidence row; other kinds keep
        # their evidence label under known_bypass.
        if kind in {
            RawBoundaryKind.RAW_STRING,
            RawBoundaryKind.FROZEN_JSON,
            RawBoundaryKind.EXTENSION_PAYLOAD,
        } and record.role is BoundaryRole.INGRESS:
            kind = RawBoundaryKind.PARSER_BYPASS
            if "parser_bypass" not in notes:
                notes = (
                    (notes + " " if notes else "")
                    + "Reclassified as explicit parser_bypass "
                    "(ungated executable ingress)."
                ).strip()
        disposition = BoundaryDisposition.KNOWN_BYPASS
        if "known_bypass" not in notes and kind is not RawBoundaryKind.PARSER_BYPASS:
            notes = (
                (notes + " " if notes else "")
                + "Recorded as known_bypass (ungated executable raw boundary)."
            ).strip()

    if disposition is BoundaryDisposition.UNCLASSIFIED and record.executable:
        # Last-resort classification: every discovered executable boundary is
        # at least a known_bypass evidence row so silence is impossible.
        disposition = BoundaryDisposition.KNOWN_BYPASS
        if kind is RawBoundaryKind.RAW_STRING and record.role is BoundaryRole.INGRESS:
            kind = RawBoundaryKind.PARSER_BYPASS
        notes = (
            (notes + " " if notes else "")
            + "Auto-classified executable raw boundary."
        ).strip()

    if disposition is record.disposition and kind is record.kind and notes == record.notes:
        return record
    return RawBoundaryRecord(
        boundary_id=_boundary_id(kind=kind, path=record.path, qualname=record.qualname),
        kind=kind,
        symbol=record.symbol,
        path=record.path,
        qualname=record.qualname,
        role=record.role,
        disposition=disposition,
        gates_crossed=record.gates_crossed,
        executable=record.executable,
        family_hints=record.family_hints,
        line=record.line,
        notes=notes,
        discovery=record.discovery,
    )


def _curated_boundaries() -> tuple[RawBoundaryRecord, ...]:
    """Explicit high-signal raw boundaries for the LFP2-002 evidence subset."""

    specs: tuple[
        tuple[
            str,
            RawBoundaryKind,
            str,
            str,
            BoundaryRole,
            BoundaryDisposition,
            tuple[str, ...],
            bool,
            tuple[str, ...],
            str,
        ],
        ...,
    ] = (
        (
            "raw_string:TDFOL/tdfol_parser.py#TDFOLParser.parse",
            RawBoundaryKind.RAW_STRING,
            "TDFOLParser.parse",
            "TDFOL/tdfol_parser.py",
            BoundaryRole.INGRESS,
            BoundaryDisposition.KNOWN_BYPASS,
            (),
            True,
            ("tdfol",),
            "TDFOL parser admits raw symbolic/NL string formulas.",
        ),
        (
            "raw_string:fol/utils/fol_parser.py#parse_quantifiers",
            RawBoundaryKind.RAW_STRING,
            "parse_quantifiers",
            "fol/utils/fol_parser.py",
            BoundaryRole.INGRESS,
            BoundaryDisposition.KNOWN_BYPASS,
            (),
            True,
            ("fol",),
            "FOL parser operates on raw natural-language strings.",
        ),
        (
            "frozen_json:formalization/views.py#FormalFormula.expression",
            RawBoundaryKind.FROZEN_JSON,
            "FormalFormula.expression",
            "formalization/views.py",
            BoundaryRole.FIELD,
            BoundaryDisposition.KNOWN_BYPASS,
            (),
            True,
            ("fol", "modal", "deontic"),
            "FormalFormula.expression admits arbitrary FrozenJSON payloads.",
        ),
        (
            "extension_payload:syntax_core/ast.py#LogicExtensionNode.payload",
            RawBoundaryKind.EXTENSION_PAYLOAD,
            "LogicExtensionNode.payload",
            "syntax_core/ast.py",
            BoundaryRole.FIELD,
            BoundaryDisposition.KNOWN_BYPASS,
            (GateKind.TYPED_EXPRESSION.value,),
            True,
            (),
            "Extension node payload boundary; must not silently cross elaboration.",
        ),
        (
            "parser_bypass:formalization/advisor.py#FormulaSuggestion.expression",
            RawBoundaryKind.PARSER_BYPASS,
            "FormulaSuggestion.expression",
            "formalization/advisor.py",
            BoundaryRole.FIELD,
            BoundaryDisposition.KNOWN_BYPASS,
            (),
            True,
            ("fol", "modal", "deontic"),
            "Advisor formula suggestion stores raw expression without ParseArtifact.",
        ),
        (
            "target_source:backends/smt/compiler.py#SoftwareVerificationSMTCompiler",
            RawBoundaryKind.TARGET_SOURCE,
            "SoftwareVerificationSMTCompiler",
            "backends/smt/compiler.py",
            BoundaryRole.EGRESS,
            BoundaryDisposition.KNOWN_BYPASS,
            (GateKind.COMPILED_ARTIFACT.value,),
            True,
            ("solver_adapter",),
            "SMT compiler emits target source; must live under compiled artifact receipts.",
        ),
        (
            "raw_string:CEC/native/dcec_parsing.py#remove_comments.expression",
            RawBoundaryKind.RAW_STRING,
            "remove_comments.expression",
            "CEC/native/dcec_parsing.py",
            BoundaryRole.INGRESS,
            BoundaryDisposition.KNOWN_BYPASS,
            (),
            True,
            ("cec_dcec",),
            "DCEC preprocessing admits raw expression strings.",
        ),
        (
            "raw_string:parsers/smtlib.py#parse",
            RawBoundaryKind.RAW_STRING,
            "parse",
            "parsers/smtlib.py",
            BoundaryRole.INGRESS,
            BoundaryDisposition.GATED,
            (
                GateKind.PARSE_ARTIFACT.value,
                GateKind.TYPED_EXPRESSION.value,
            ),
            True,
            ("solver_adapter",),
            "Shared SMT-LIB frontend; intended to cross ParseArtifact/TypedExpression.",
        ),
        (
            "target_source:backends/z3/compiler.py#Z3Compiler",
            RawBoundaryKind.TARGET_SOURCE,
            "Z3Compiler",
            "backends/z3/compiler.py",
            BoundaryRole.EGRESS,
            BoundaryDisposition.KNOWN_BYPASS,
            (GateKind.COMPILED_ARTIFACT.value,),
            True,
            ("solver_adapter",),
            "Z3 adapter compiler surface produces target source text.",
        ),
        (
            "frozen_json:bridge/types.py#LogicIRView.payload",
            RawBoundaryKind.FROZEN_JSON,
            "LogicIRView.payload",
            "bridge/types.py",
            BoundaryRole.FIELD,
            BoundaryDisposition.KNOWN_BYPASS,
            (),
            True,
            (),
            "Bridge IR view carries arbitrary JSON payload.",
        ),
        (
            "parser_bypass:types/common_types.py#Formula.to_string",
            RawBoundaryKind.PARSER_BYPASS,
            "Formula.to_string",
            "types/common_types.py",
            BoundaryRole.EGRESS,
            BoundaryDisposition.KNOWN_BYPASS,
            (),
            True,
            ("fol",),
            "Shared Formula protocol exposes only raw-string rendering.",
        ),
        (
            "extension_payload:formalization/constraint_contracts.py#extension",
            RawBoundaryKind.EXTENSION_PAYLOAD,
            "extension",
            "formalization/constraint_contracts.py",
            BoundaryRole.FIELD,
            BoundaryDisposition.KNOWN_BYPASS,
            (),
            True,
            ("fol", "modal", "deontic"),
            "Constraint contracts historically admit extension-shaped payloads.",
        ),
        (
            "raw_string:deontic/utils/deontic_parser.py#extract_normative_elements",
            RawBoundaryKind.RAW_STRING,
            "extract_normative_elements",
            "deontic/utils/deontic_parser.py",
            BoundaryRole.INGRESS,
            BoundaryDisposition.KNOWN_BYPASS,
            (),
            True,
            ("deontic",),
            "Deontic normative-element extraction parser on raw text.",
        ),
        (
            "target_source:external_provers/prover_router.py#SyntacticProofResult.formula",
            RawBoundaryKind.TARGET_SOURCE,
            "SyntacticProofResult.formula",
            "external_provers/prover_router.py",
            BoundaryRole.FIELD,
            BoundaryDisposition.KNOWN_BYPASS,
            (GateKind.PARSED_TARGET.value,),
            True,
            ("solver_adapter",),
            "External prover result formula is a parsed-target boundary.",
        ),
        (
            "parser_bypass:modal/compiler.py#DeterministicModalCompiler.compile",
            RawBoundaryKind.PARSER_BYPASS,
            "DeterministicModalCompiler.compile",
            "modal/compiler.py",
            BoundaryRole.INGRESS,
            BoundaryDisposition.KNOWN_BYPASS,
            (),
            True,
            ("modal",),
            "Modal compiler historically accepts raw formula strings.",
        ),
    )
    records: list[RawBoundaryRecord] = []
    for (
        boundary_id,
        kind,
        symbol,
        path,
        role,
        disposition,
        gates,
        executable,
        families,
        notes,
    ) in specs:
        records.append(
            RawBoundaryRecord(
                boundary_id=boundary_id,
                kind=kind,
                symbol=symbol,
                path=path,
                qualname=symbol,
                role=role,
                disposition=disposition,
                gates_crossed=gates,
                executable=executable,
                family_hints=families,
                notes=notes,
                discovery="curated",
            )
        )
    return tuple(records)


def _iter_python_files(
    base: Path, policy: RawBoundaryInventoryPolicy
) -> Iterator[Path]:
    stack = [base]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in policy.excluded_dir_names:
                    continue
                if entry.name.endswith(".egg-info"):
                    continue
                stack.append(entry)
            elif entry.is_file() and entry.suffix == ".py":
                # Skip unit/regression modules colocated under production roots.
                if entry.name.startswith("test_") or entry.name.endswith(
                    "_test.py"
                ):
                    continue
                yield entry


def _scan_module(
    tree: ast.AST,
    *,
    rel_path: str,
    source: str,
    policy: RawBoundaryInventoryPolicy,
) -> list[RawBoundaryRecord]:
    family_hints = _family_hints_for_path(rel_path)
    executable = not bool(_NON_EXECUTABLE_PATH_RE.search(rel_path))
    module_gates = _gates_from_text(source)
    records: list[RawBoundaryRecord] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            qualname = ".".join([*self.class_stack, node.name])
            if policy.include_private or not node.name.startswith("_"):
                for boundary in _class_raw_boundaries(
                    node,
                    rel_path=rel_path,
                    qualname=qualname,
                    family_hints=family_hints,
                    executable=executable,
                    module_gates=module_gates,
                ):
                    records.append(boundary)
            self.class_stack.append(node.name)
            self.generic_visit(node)
            self.class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)

        def _visit_function(self, node: ast.AST) -> None:
            assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            name = node.name
            if not policy.include_private and name.startswith("_"):
                self.generic_visit(node)
                return
            qualname = ".".join([*self.class_stack, name])
            for boundary in _function_raw_boundaries(
                node,
                rel_path=rel_path,
                qualname=qualname,
                family_hints=family_hints,
                executable=executable,
                module_gates=module_gates,
            ):
                records.append(boundary)
            self.generic_visit(node)

    Visitor().visit(tree)
    return records


def _class_raw_boundaries(
    node: ast.ClassDef,
    *,
    rel_path: str,
    qualname: str,
    family_hints: tuple[str, ...],
    executable: bool,
    module_gates: frozenset[str],
) -> list[RawBoundaryRecord]:
    records: list[RawBoundaryRecord] = []
    class_text = ast.unparse(node) if hasattr(ast, "unparse") else ""
    local_gates = module_gates | _gates_from_text(class_text)
    for stmt in node.body:
        target_names: list[str] = []
        annotation: ast.AST | None = None
        line = getattr(stmt, "lineno", None)
        if isinstance(stmt, ast.AnnAssign):
            annotation = stmt.annotation
            target_names.extend(_target_names(stmt.target))
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                target_names.extend(_target_names(target))
        for name in target_names:
            if not _EXPRESSION_FIELD_RE.match(name):
                continue
            ann_text = _annotation_text(annotation) if annotation is not None else ""
            kind = _kind_from_name_and_annotation(name, ann_text)
            if kind is None:
                continue
            field_qualname = f"{qualname}.{name}"
            gates = tuple(sorted(local_gates | _gates_from_text(ann_text)))
            records.append(
                _record(
                    kind=kind,
                    symbol=field_qualname,
                    path=rel_path,
                    qualname=field_qualname,
                    role=BoundaryRole.FIELD,
                    gates_crossed=gates,
                    executable=executable,
                    family_hints=family_hints,
                    line=line,
                    notes=(
                        f"Field {name!r} admits {kind.value} formula/source payloads."
                    ),
                )
            )
    return records


def _function_raw_boundaries(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    rel_path: str,
    qualname: str,
    family_hints: tuple[str, ...],
    executable: bool,
    module_gates: frozenset[str],
) -> list[RawBoundaryRecord]:
    is_parser_like = bool(
        _PARSER_NAME_RE.search(node.name)
        or node.name in {"loads", "from_string", "from_text", "from_json", "from_source"}
    )
    is_compiler_like = bool(_COMPILER_NAME_RE.search(node.name))
    is_decoder_like = bool(_DECODER_NAME_RE.search(node.name))
    if not (is_parser_like or is_compiler_like or is_decoder_like):
        # Still capture explicit target_source / extension parameters.
        pass

    try:
        fn_text = ast.unparse(node)
    except Exception:
        fn_text = ""
    local_gates = module_gates | _gates_from_text(fn_text)
    ret_ann = _annotation_text(node.returns)
    local_gates |= _gates_from_text(ret_ann)

    records: list[RawBoundaryRecord] = []
    args = list(node.args.args) + list(node.args.kwonlyargs)
    if node.args.vararg is not None:
        args.append(node.args.vararg)
    if node.args.kwarg is not None:
        args.append(node.args.kwarg)

    for arg in args:
        if arg.arg in {"self", "cls"}:
            continue
        name = arg.arg
        ann_text = _annotation_text(arg.annotation)
        kind = _kind_from_name_and_annotation(name, ann_text)
        if kind is None:
            if is_parser_like and _EXPRESSION_PARAM_RE.match(name):
                kind = RawBoundaryKind.RAW_STRING
            elif is_compiler_like and _TARGET_SOURCE_NAME_RE.search(name):
                kind = RawBoundaryKind.TARGET_SOURCE
            else:
                continue
        if not (
            is_parser_like
            or is_compiler_like
            or is_decoder_like
            or _EXPRESSION_PARAM_RE.match(name)
            or _TARGET_SOURCE_NAME_RE.search(name)
            or _EXTENSION_NAME_RE.search(name)
        ):
            continue

        role = BoundaryRole.INGRESS
        if is_compiler_like and kind is RawBoundaryKind.TARGET_SOURCE:
            role = BoundaryRole.EGRESS
        elif is_decoder_like:
            role = BoundaryRole.EGRESS

        param_qualname = f"{qualname}.{name}"
        gates = tuple(sorted(local_gates | _gates_from_text(ann_text)))
        records.append(
            _record(
                kind=kind,
                symbol=param_qualname,
                path=rel_path,
                qualname=param_qualname,
                role=role,
                gates_crossed=gates,
                executable=executable,
                family_hints=family_hints,
                line=getattr(node, "lineno", None),
                notes=(
                    f"Callable parameter {name!r} admits "
                    f"{kind.value} formula/source payloads."
                ),
            )
        )
    return records


def _kind_from_name_and_annotation(
    name: str, ann_text: str
) -> RawBoundaryKind | None:
    if _TARGET_SOURCE_NAME_RE.search(name):
        return RawBoundaryKind.TARGET_SOURCE
    if _EXTENSION_NAME_RE.search(name) or _EXTENSION_ANN_RE.search(ann_text):
        return RawBoundaryKind.EXTENSION_PAYLOAD
    if _FROZEN_JSON_ANN_RE.search(ann_text):
        return RawBoundaryKind.FROZEN_JSON
    if _RAW_STRING_ANN_RE.search(ann_text):
        return RawBoundaryKind.RAW_STRING
    if not ann_text and _EXPRESSION_FIELD_RE.match(name):
        return RawBoundaryKind.RAW_STRING
    return None


def _gates_from_text(text: str) -> frozenset[str]:
    if not text:
        return frozenset()
    found: set[str] = set()
    for gate, pattern in _GATE_TYPE_PATTERNS:
        if pattern.search(text):
            found.add(gate)
    return frozenset(found)


def _family_hints_for_path(rel_path: str) -> tuple[str, ...]:
    path = rel_path.replace("\\", "/")
    lower = path.lower()
    hints: set[str] = set()
    if lower.startswith("tdfol/") or "/tdfol" in lower:
        hints.add("tdfol")
    if lower.startswith("cec/") or "/dcec" in lower:
        hints.add("cec_dcec")
    if lower.startswith("fol/") or "/fol" in lower:
        hints.add("fol")
    if "deontic" in lower:
        hints.add("deontic")
    if lower.startswith("modal/") or "/modal" in lower:
        hints.add("modal")
    if "flogic" in lower or "frame_logic" in lower or "ergo" in lower:
        hints.add("flogic")
    if "runtime_mtl" in lower or "monitoring" in lower:
        hints.add("runtime_mtl")
    if (
        lower.startswith("backends/")
        or "external_provers" in lower
        or "hammers" in lower
        or lower.startswith("parsers/")
    ):
        hints.add("solver_adapter")
    if "formalization" in lower:
        hints.update({"fol", "modal", "deontic"})
    if "security_ir" in lower:
        hints.add("security_ir")
    if "crypto_ir" in lower:
        hints.add("crypto_ir")
    if "intent_ir" in lower:
        hints.add("intent_ir")
    if "legal_ir" in lower:
        hints.add("legal_ir")
    return tuple(sorted(hints))


def _boundary_id(
    *,
    kind: RawBoundaryKind,
    path: str,
    qualname: str,
) -> str:
    return f"{kind.value}:{path}#{qualname}"


def _record(
    *,
    kind: RawBoundaryKind,
    symbol: str,
    path: str,
    qualname: str,
    role: BoundaryRole,
    gates_crossed: Sequence[str] = (),
    executable: bool = True,
    family_hints: tuple[str, ...] = (),
    line: int | None = None,
    notes: str = "",
    discovery: str = "ast_scan",
) -> RawBoundaryRecord:
    return RawBoundaryRecord(
        boundary_id=_boundary_id(kind=kind, path=path, qualname=qualname),
        kind=kind,
        symbol=symbol,
        path=path,
        qualname=qualname,
        role=role,
        disposition=BoundaryDisposition.UNCLASSIFIED,
        gates_crossed=tuple(gates_crossed),
        executable=executable,
        family_hints=family_hints,
        line=line,
        notes=notes,
        discovery=discovery,
    )


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in target.elts:
            names.extend(_target_names(elt))
        return names
    return []


def _annotation_text(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _relative_to_logic(path: Path, logic_root: Path) -> str:
    rel = path.resolve().relative_to(logic_root.resolve())
    return rel.as_posix()


def _posix_relative(value: str, field_name: str) -> str:
    text = _text(value, field_name)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise RawBoundaryInventoryError(
            f"{field_name} must be a normalized relative POSIX path; got {value!r}"
        )
    normalized = path.as_posix()
    if normalized != text.replace("\\", "/"):
        if text.replace("\\", "/").rstrip("/") != normalized:
            raise RawBoundaryInventoryError(
                f"{field_name} must be a normalized relative POSIX path; got {value!r}"
            )
    return normalized


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise RawBoundaryInventoryError(f"{field_name} must be a string")
    if "\x00" in value:
        raise RawBoundaryInventoryError(f"{field_name} must not contain NUL bytes")
    if not allow_empty and not value.strip():
        raise RawBoundaryInventoryError(f"{field_name} must be a non-empty string")
    return value


def _identifier(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*", text):
        raise RawBoundaryInventoryError(
            f"{field_name} must be a lowercase identifier; got {text!r}"
        )
    return text


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise RawBoundaryInventoryError(
            f"{field_name} must be one of {choices}"
        ) from error


__all__ = [
    "DEFAULT_BASELINE_REPORT_RELATIVE",
    "DEFAULT_MAX_BOUNDARIES",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_SCANNED_FILES",
    "DEFAULT_SEALED_RELATIVE_ROOTS",
    "BoundaryDisposition",
    "BoundaryRole",
    "GateKind",
    "INVENTORY_GOAL_ID",
    "INVENTORY_TASK_ID",
    "RAW_LOGIC_BOUNDARY_INVENTORY_INTERFACE",
    "RAW_LOGIC_BOUNDARY_INVENTORY_SCHEMA_VERSION",
    "REQUIRED_EVIDENCE_KINDS",
    "REQUIRED_GATES",
    "RawBoundaryInventoryError",
    "RawBoundaryInventoryIncompleteError",
    "RawBoundaryInventoryPolicy",
    "RawBoundaryKind",
    "RawBoundaryRecord",
    "RawLogicBoundaryInventory",
    "assert_raw_boundary_inventory_complete",
    "build_raw_boundary_inventory_report",
    "classify_raw_ingress",
    "curated_raw_boundary_inventory",
    "default_baseline_report_path",
    "default_datasets_package_root",
    "default_logic_package_root",
    "inventory_raw_boundaries",
    "load_raw_boundary_inventory",
    "write_raw_boundary_inventory",
]


def _main() -> int:
    """Write the sealed curated baseline report (no production imports)."""

    inventory = curated_raw_boundary_inventory()
    assert_raw_boundary_inventory_complete(inventory, require_policy_roots=False)
    path = write_raw_boundary_inventory(
        default_baseline_report_path(),
        inventory=inventory,
    )
    print(f"wrote {path}")
    print(f"boundaries={len(inventory.boundaries)}")
    print(f"digest={inventory.content_digest()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
