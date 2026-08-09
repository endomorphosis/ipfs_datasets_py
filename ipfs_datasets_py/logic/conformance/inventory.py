"""Logic surface inventory (``LogicSurfaceInventory@1``).

Static, deterministic census of parser, AST, formula/term, printer, compiler,
result-decoder, type, legacy-duplicate, and formula-boundary surfaces under
explicit logic roots.

This module is intentionally side-effect-free at import time and never imports
production parser implementations.  Production sources are read-only evidence
for the inventory; only this inventory module, its unit test, and the baseline
JSON report are owned by LFP-001.
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

LOGIC_SURFACE_INVENTORY_INTERFACE: Final = "LogicSurfaceInventory@1"
LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION: Final = "logic-surface-inventory/v1"
INVENTORY_TASK_ID: Final = "LFP-001"
INVENTORY_GOAL_ID: Final = "LFP-G010"

# Superproject-relative path of the owned baseline report.
DEFAULT_BASELINE_REPORT_RELATIVE: Final = (
    "ipfs_datasets_py/docs/architecture/logic/"
    "logic_parser_baseline/parser_inventory.json"
)

# Maximum resources accepted by the default policy (bounded inventory).
DEFAULT_MAX_FILE_BYTES: Final = 1_500_000
DEFAULT_MAX_SURFACES: Final = 8_192
DEFAULT_MAX_SCANNED_FILES: Final = 4_096

# Directory names skipped during filesystem walks.
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
    }
)

# Relative roots under the logic package that the baseline policy must cover.
DEFAULT_LOGIC_RELATIVE_ROOTS: Final[tuple[str, ...]] = (
    "TDFOL",
    "CEC",
    "fol",
    "deontic",
    "modal",
    "flogic",
    "software_verification/monitoring",
    "formalization",
    "backends/smt",
    "backends/z3",
    "backends/cvc5",
    "backends/atp",
    "backends/tla",
    "backends/datalog",
    "types",
    "bridge",
    "integration/converters",
    "integration/bridges",
    "external_provers",
    "hammers",
)

# Evidence families required by LFP-001 acceptance.
REQUIRED_EVIDENCE_FAMILIES: Final[tuple[str, ...]] = (
    "tdfol",
    "cec_dcec",
    "fol",
    "deontic",
    "modal",
    "flogic",
    "runtime_mtl",
    "solver_adapter",
)

_PARSER_NAME_RE = re.compile(
    r"(?i)(?:^|_)(?:parse|parser|lexer|tokenizer)(?:$|_)"
)
_PRINTER_NAME_RE = re.compile(
    r"(?i)(?:^|_)(?:print|printer|format|formatter|render|pretty)(?:$|_)"
)
_DECODER_NAME_RE = re.compile(
    r"(?i)(?:^|_)(?:decode|decoder|result_parser|response_parser)(?:$|_)"
)
_COMPILER_NAME_RE = re.compile(
    r"(?i)(?:^|_)(?:compile|compiler|lower|lowering)(?:$|_)"
)
_FORMULA_NAME_RE = re.compile(r"(?i)formula")
_TERM_NAME_RE = re.compile(r"(?i)(?:^|_)term(?:$|_)|Term\b")
_AST_NAME_RE = re.compile(r"(?i)(?:\bast\b|syntax_?tree|cst|node)")
_TYPE_NAME_RE = re.compile(r"(?i)(?:type|sort|signature)")
_LEGACY_PATH_RE = re.compile(
    r"(?i)(?:legacy|compat|deprecated|duplicate|old_|_old|/ARCHIVE/)"
)

_RAW_STRING_ANN_RE = re.compile(r"(?i)\b(?:str|Text|bytes|bytearray)\b")
_ARBITRARY_JSON_ANN_RE = re.compile(
    r"(?i)\b(?:Any|dict|Dict|Mapping|MutableMapping|JSON|FrozenJSON|"
    r"object|JsonValue|JSONValue)\b"
)
_EXPRESSION_FIELD_RE = re.compile(
    r"(?i)^(?:expression|formula|payload|body|source|text|content)$"
)
_EXPRESSION_PARAM_RE = re.compile(
    r"(?i)^(?:expression|formula|text|source|payload|content|raw)$"
)


class SurfaceKind(StrEnum):
    """Role of one inventoried logic surface."""

    PARSER = "parser"
    AST = "ast"
    FORMULA = "formula"
    TERM = "term"
    TYPE = "type"
    PRINTER = "printer"
    COMPILER = "compiler"
    RESULT_DECODER = "result_decoder"
    LEGACY_DUPLICATE = "legacy_duplicate"
    FORMULA_BOUNDARY = "formula_boundary"


class FormulaBoundaryKind(StrEnum):
    """How an untyped formula payload is admitted."""

    RAW_STRING = "raw_string"
    ARBITRARY_JSON = "arbitrary_json"


class InventoryError(ValueError):
    """Raised when inventory inputs or outputs violate the contract."""


class InventoryIncompleteError(InventoryError):
    """Raised when path completeness under policy fails."""


@dataclass(frozen=True, slots=True)
class SurfaceInventoryPolicy:
    """Bounded scan policy for the logic surface inventory."""

    profile_id: str = "logic-surface-inventory-default@1"
    relative_roots: tuple[str, ...] = DEFAULT_LOGIC_RELATIVE_ROOTS
    excluded_dir_names: frozenset[str] = field(
        default_factory=lambda: _DEFAULT_EXCLUDED_DIR_NAMES
    )
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_surfaces: int = DEFAULT_MAX_SURFACES
    max_scanned_files: int = DEFAULT_MAX_SCANNED_FILES
    include_private: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise InventoryError("profile_id must be a non-empty string")
        roots = tuple(
            _posix_relative(root, "relative_roots item")
            for root in self.relative_roots
        )
        if not roots:
            raise InventoryError("relative_roots must not be empty")
        if len(set(roots)) != len(roots):
            raise InventoryError("relative_roots must not contain duplicates")
        object.__setattr__(self, "relative_roots", roots)
        if self.max_file_bytes < 1:
            raise InventoryError("max_file_bytes must be positive")
        if self.max_surfaces < 1:
            raise InventoryError("max_surfaces must be positive")
        if self.max_scanned_files < 1:
            raise InventoryError("max_scanned_files must be positive")
        excluded = frozenset(
            _text(name, "excluded_dir_names item")
            for name in self.excluded_dir_names
        )
        object.__setattr__(self, "excluded_dir_names", excluded)


@dataclass(frozen=True, slots=True)
class LogicSurfaceRecord:
    """One stable inventory record for a parser/AST/type/printer surface."""

    surface_id: str
    kind: SurfaceKind | str
    symbol: str
    path: str
    qualname: str
    family_hints: tuple[str, ...] = ()
    boundary_kind: FormulaBoundaryKind | str | None = None
    line: int | None = None
    notes: str = ""
    discovery: str = "ast_scan"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "surface_id", _text(self.surface_id, "surface_id")
        )
        object.__setattr__(self, "kind", _enum(self.kind, SurfaceKind, "kind"))
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(self, "path", _posix_relative(self.path, "path"))
        object.__setattr__(self, "qualname", _text(self.qualname, "qualname"))
        families = tuple(
            sorted(
                {
                    _identifier(item, "family_hints item")
                    for item in self.family_hints
                }
            )
        )
        object.__setattr__(self, "family_hints", families)
        if self.boundary_kind is not None:
            object.__setattr__(
                self,
                "boundary_kind",
                _enum(self.boundary_kind, FormulaBoundaryKind, "boundary_kind"),
            )
        if self.kind is SurfaceKind.FORMULA_BOUNDARY and self.boundary_kind is None:
            raise InventoryError(
                f"formula boundary surface {self.surface_id!r} requires boundary_kind"
            )
        if self.line is not None:
            if not isinstance(self.line, int) or self.line < 1:
                raise InventoryError("line must be a positive integer when set")
        object.__setattr__(self, "notes", _text(self.notes, "notes", allow_empty=True))
        object.__setattr__(
            self, "discovery", _text(self.discovery, "discovery")
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "discovery": self.discovery,
            "family_hints": list(self.family_hints),
            "kind": self.kind.value if isinstance(self.kind, SurfaceKind) else self.kind,
            "notes": self.notes,
            "path": self.path,
            "qualname": self.qualname,
            "surface_id": self.surface_id,
            "symbol": self.symbol,
        }
        if self.boundary_kind is not None:
            payload["boundary_kind"] = (
                self.boundary_kind.value
                if isinstance(self.boundary_kind, FormulaBoundaryKind)
                else self.boundary_kind
            )
        if self.line is not None:
            payload["line"] = self.line
        return payload


@dataclass(frozen=True, slots=True)
class LogicSurfaceInventory:
    """Deterministic inventory result for one policy application."""

    schema_version: str = LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION
    interface: str = LOGIC_SURFACE_INVENTORY_INTERFACE
    task_id: str = INVENTORY_TASK_ID
    goal_id: str = INVENTORY_GOAL_ID
    policy_profile_id: str = "logic-surface-inventory-default@1"
    logic_root: str = ""
    scanned_files: tuple[str, ...] = ()
    surfaces: tuple[LogicSurfaceRecord, ...] = ()
    required_evidence_families: tuple[str, ...] = REQUIRED_EVIDENCE_FAMILIES
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION:
            raise InventoryError(
                f"unsupported inventory schema_version {self.schema_version!r}"
            )
        object.__setattr__(
            self, "interface", _text(self.interface, "interface")
        )
        if self.interface != LOGIC_SURFACE_INVENTORY_INTERFACE:
            raise InventoryError(f"unsupported interface {self.interface!r}")
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
            sorted({_posix_relative(path, "scanned_files item") for path in self.scanned_files})
        )
        object.__setattr__(self, "scanned_files", files)
        surfaces = tuple(
            sorted(self.surfaces, key=lambda item: (item.path, item.qualname, item.kind.value))
        )
        ids = [item.surface_id for item in surfaces]
        if len(ids) != len(set(ids)):
            raise InventoryError("surface_id values must be unique")
        object.__setattr__(self, "surfaces", surfaces)
        families = tuple(
            sorted(
                {
                    _identifier(item, "required_evidence_families item")
                    for item in self.required_evidence_families
                }
            )
        )
        object.__setattr__(self, "required_evidence_families", families)
        diagnostics = tuple(
            _text(item, "diagnostics item") for item in self.diagnostics
        )
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def surface_ids(self) -> tuple[str, ...]:
        return tuple(item.surface_id for item in self.surfaces)

    @property
    def formula_boundaries(self) -> tuple[LogicSurfaceRecord, ...]:
        return tuple(
            item
            for item in self.surfaces
            if item.kind is SurfaceKind.FORMULA_BOUNDARY
        )

    def surfaces_for_kind(self, kind: SurfaceKind | str) -> tuple[LogicSurfaceRecord, ...]:
        kind_value = _enum(kind, SurfaceKind, "kind")
        return tuple(item for item in self.surfaces if item.kind is kind_value)

    def covered_evidence_families(self) -> frozenset[str]:
        covered: set[str] = set()
        for surface in self.surfaces:
            covered.update(surface.family_hints)
        return frozenset(covered)

    def content_digest(self) -> str:
        """Return a deterministic digest of the inventory payload."""

        payload = self.to_dict()
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": list(self.diagnostics),
            "goal_id": self.goal_id,
            "interface": self.interface,
            "logic_root": self.logic_root,
            "policy_profile_id": self.policy_profile_id,
            "required_evidence_families": list(self.required_evidence_families),
            "scanned_files": list(self.scanned_files),
            "schema_version": self.schema_version,
            "surfaces": [item.to_dict() for item in self.surfaces],
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> LogicSurfaceInventory:
        if not isinstance(value, Mapping):
            raise InventoryError("inventory payload must be a mapping")
        surfaces_raw = value.get("surfaces", ())
        if not isinstance(surfaces_raw, Sequence) or isinstance(
            surfaces_raw, (str, bytes, bytearray)
        ):
            raise InventoryError("surfaces must be a sequence")
        surfaces: list[LogicSurfaceRecord] = []
        for item in surfaces_raw:
            if not isinstance(item, Mapping):
                raise InventoryError("each surface must be a mapping")
            surfaces.append(
                LogicSurfaceRecord(
                    surface_id=str(item.get("surface_id", "")),
                    kind=str(item.get("kind", "")),
                    symbol=str(item.get("symbol", "")),
                    path=str(item.get("path", "")),
                    qualname=str(item.get("qualname", "")),
                    family_hints=tuple(item.get("family_hints", ()) or ()),
                    boundary_kind=item.get("boundary_kind"),
                    line=item.get("line"),
                    notes=str(item.get("notes", "") or ""),
                    discovery=str(item.get("discovery", "ast_scan") or "ast_scan"),
                )
            )
        return cls(
            schema_version=str(
                value.get("schema_version", LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION)
            ),
            interface=str(
                value.get("interface", LOGIC_SURFACE_INVENTORY_INTERFACE)
            ),
            task_id=str(value.get("task_id", INVENTORY_TASK_ID)),
            goal_id=str(value.get("goal_id", INVENTORY_GOAL_ID)),
            policy_profile_id=str(
                value.get("policy_profile_id", "logic-surface-inventory-default@1")
            ),
            logic_root=str(value.get("logic_root", "") or ""),
            scanned_files=tuple(value.get("scanned_files", ()) or ()),
            surfaces=tuple(surfaces),
            required_evidence_families=tuple(
                value.get("required_evidence_families", REQUIRED_EVIDENCE_FAMILIES)
                or REQUIRED_EVIDENCE_FAMILIES
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
    # .../ipfs_datasets_py/logic/conformance/inventory.py -> logic/
    logic_root = here.parents[1]
    if logic_root.name == "logic":
        return logic_root
    raise InventoryError("unable to resolve logic package root from inventory module")


def default_datasets_package_root(logic_root: Path | None = None) -> Path:
    """Resolve the ``ipfs_datasets_py`` package root containing ``logic/``."""

    root = default_logic_package_root(logic_root) if logic_root is None else Path(logic_root)
    # .../ipfs_datasets_py/logic -> .../ipfs_datasets_py (package)
    package = root.parent
    if package.name != "ipfs_datasets_py":
        raise InventoryError(
            f"expected logic parent named ipfs_datasets_py, got {package.name!r}"
        )
    return package


def default_baseline_report_path(logic_root: Path | None = None) -> Path:
    """Return the owned baseline report path for the current checkout layout."""

    package = default_datasets_package_root(logic_root)
    # package is ipfs_datasets_py/ipfs_datasets_py; repo root is its parent.
    repo_root = package.parent
    return repo_root / "docs" / "architecture" / "logic" / "logic_parser_baseline" / "parser_inventory.json"


def inventory_logic_surfaces(
    *,
    logic_root: Path | None = None,
    policy: SurfaceInventoryPolicy | None = None,
    include_curated: bool = True,
) -> LogicSurfaceInventory:
    """Build a deterministic inventory under the given policy.

    The scan is pure filesystem/AST analysis: no production parser modules are
    imported and no files outside the policy roots are written.
    """

    policy = policy or SurfaceInventoryPolicy()
    root = default_logic_package_root(logic_root)
    if not root.is_dir():
        raise InventoryError(f"logic root does not exist: {root}")

    scanned: list[str] = []
    discovered: dict[str, LogicSurfaceRecord] = {}
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
                policy=policy,
            ):
                discovered[record.surface_id] = record
                if len(discovered) > policy.max_surfaces:
                    raise InventoryError(
                        f"surface count exceeded max_surfaces={policy.max_surfaces}"
                    )
        if "max_scanned_files_reached" in diagnostics:
            break

    if include_curated:
        for record in _curated_surfaces():
            discovered.setdefault(record.surface_id, record)

    surfaces = tuple(discovered.values())
    inventory = LogicSurfaceInventory(
        policy_profile_id=policy.profile_id,
        logic_root=_posix_relative(
            str(Path("ipfs_datasets_py") / "logic"), "logic_root"
        ),
        scanned_files=tuple(scanned),
        surfaces=surfaces,
        diagnostics=tuple(sorted(set(diagnostics))),
    )
    return inventory


def curated_logic_surface_inventory() -> LogicSurfaceInventory:
    """Return the sealed curated evidence inventory (no filesystem scan)."""

    surfaces = _curated_surfaces()
    scanned = tuple(sorted({item.path for item in surfaces}))
    return LogicSurfaceInventory(
        policy_profile_id="logic-surface-inventory-curated@1",
        logic_root="ipfs_datasets_py/logic",
        scanned_files=scanned,
        surfaces=surfaces,
        diagnostics=(),
    )


def build_parser_inventory_report(
    inventory: LogicSurfaceInventory | None = None,
    *,
    logic_root: Path | None = None,
    policy: SurfaceInventoryPolicy | None = None,
    curated_only: bool = False,
) -> dict[str, Any]:
    """Return the baseline JSON object for ``parser_inventory.json``."""

    if inventory is not None:
        inv = inventory
    elif curated_only:
        inv = curated_logic_surface_inventory()
    else:
        inv = inventory_logic_surfaces(logic_root=logic_root, policy=policy)
    by_kind: dict[str, int] = {}
    for kind in SurfaceKind:
        by_kind[kind.value] = len(inv.surfaces_for_kind(kind))
    boundaries = {
        "raw_string": [
            item.to_dict()
            for item in inv.formula_boundaries
            if item.boundary_kind is FormulaBoundaryKind.RAW_STRING
        ],
        "arbitrary_json": [
            item.to_dict()
            for item in inv.formula_boundaries
            if item.boundary_kind is FormulaBoundaryKind.ARBITRARY_JSON
        ],
    }
    covered = sorted(inv.covered_evidence_families())
    missing = sorted(set(inv.required_evidence_families) - set(covered))
    return {
        "content_digest": inv.content_digest(),
        "counts_by_kind": by_kind,
        "diagnostics": list(inv.diagnostics),
        "evidence_coverage": {
            "covered_families": covered,
            "missing_families": missing,
            "required_families": list(inv.required_evidence_families),
        },
        "formula_boundaries": boundaries,
        "goal_id": inv.goal_id,
        "interface": inv.interface,
        "logic_root": inv.logic_root,
        "policy_profile_id": inv.policy_profile_id,
        "schema_version": inv.schema_version,
        "scanned_file_count": len(inv.scanned_files),
        "scanned_files": list(inv.scanned_files),
        "surface_count": len(inv.surfaces),
        "surfaces": [item.to_dict() for item in inv.surfaces],
        "task_id": inv.task_id,
    }


def write_parser_inventory(
    path: Path | str | None = None,
    *,
    inventory: LogicSurfaceInventory | None = None,
    logic_root: Path | None = None,
    policy: SurfaceInventoryPolicy | None = None,
    curated_only: bool = False,
) -> Path:
    """Write the baseline inventory report as canonical JSON."""

    report = build_parser_inventory_report(
        inventory,
        logic_root=logic_root,
        policy=policy,
        curated_only=curated_only,
    )
    target = Path(path) if path is not None else default_baseline_report_path(logic_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def load_parser_inventory(path: Path | str) -> dict[str, Any]:
    """Load and lightly validate a baseline inventory report."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InventoryError("parser inventory report must be a JSON object")
    if payload.get("interface") != LOGIC_SURFACE_INVENTORY_INTERFACE:
        raise InventoryError(
            f"unsupported inventory interface {payload.get('interface')!r}"
        )
    if payload.get("schema_version") != LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION:
        raise InventoryError(
            f"unsupported inventory schema_version {payload.get('schema_version')!r}"
        )
    return payload


def assert_inventory_complete(
    inventory: LogicSurfaceInventory,
    *,
    policy: SurfaceInventoryPolicy | None = None,
    require_evidence_families: bool = True,
    require_policy_roots: bool = True,
) -> None:
    """Fail closed when inventory is incomplete under policy."""

    policy = policy or SurfaceInventoryPolicy()
    errors: list[str] = []

    if not inventory.surfaces:
        errors.append("inventory contains no surfaces")

    if require_policy_roots:
        scanned = set(inventory.scanned_files)
        for root in policy.relative_roots:
            prefix = root.rstrip("/") + "/"
            root_file = root if root.endswith(".py") else None
            if root_file and root_file in scanned:
                continue
            if any(path == root or path.startswith(prefix) for path in scanned):
                continue
            # Missing roots are already diagnostic when the tree lacks them.
            if any(
                item.startswith(f"missing_root:{root}")
                for item in inventory.diagnostics
            ):
                continue
            errors.append(f"policy root not represented in scanned_files: {root}")

    kinds_present = {item.kind for item in inventory.surfaces}
    for required in (
        SurfaceKind.PARSER,
        SurfaceKind.FORMULA,
        SurfaceKind.FORMULA_BOUNDARY,
    ):
        if required not in kinds_present:
            errors.append(f"missing required surface kind: {required.value}")

    boundaries = inventory.formula_boundaries
    raw = [
        item
        for item in boundaries
        if item.boundary_kind is FormulaBoundaryKind.RAW_STRING
    ]
    arbitrary = [
        item
        for item in boundaries
        if item.boundary_kind is FormulaBoundaryKind.ARBITRARY_JSON
    ]
    if not raw:
        errors.append("no raw_string formula boundaries identified")
    if not arbitrary:
        errors.append("no arbitrary_json formula boundaries identified")

    if require_evidence_families:
        covered = inventory.covered_evidence_families()
        missing = sorted(set(inventory.required_evidence_families) - covered)
        if missing:
            errors.append(
                "missing evidence family coverage: " + ", ".join(missing)
            )

    if errors:
        raise InventoryIncompleteError("; ".join(errors))


def _curated_surfaces() -> tuple[LogicSurfaceRecord, ...]:
    """Explicit high-signal surfaces for the LFP-001 evidence subset.

    Curated entries ensure path identity for known islands even when name
    heuristics miss a symbol.  Discovery remains additive; AST scan records
    win on identical surface_id only if already present.
    """

    specs: tuple[tuple[str, SurfaceKind, str, str, tuple[str, ...], FormulaBoundaryKind | None, str], ...] = (
        (
            "parser:TDFOL/tdfol_parser.py#TDFOLParser",
            SurfaceKind.PARSER,
            "TDFOLParser",
            "TDFOL/tdfol_parser.py",
            ("tdfol",),
            None,
            "Symbolic/NL/JSON TDFOL parser island.",
        ),
        (
            "formula:TDFOL/tdfol_core.py#Formula",
            SurfaceKind.FORMULA,
            "Formula",
            "TDFOL/tdfol_core.py",
            ("tdfol",),
            None,
            "TDFOL formula AST root.",
        ),
        (
            "term:TDFOL/tdfol_core.py#Term",
            SurfaceKind.TERM,
            "Term",
            "TDFOL/tdfol_core.py",
            ("tdfol",),
            None,
            "TDFOL term AST root.",
        ),
        (
            "parser:CEC/native/dcec_parsing.py#remove_comments",
            SurfaceKind.PARSER,
            "remove_comments",
            "CEC/native/dcec_parsing.py",
            ("cec_dcec",),
            None,
            "DCEC native expression preprocessing/parser surface.",
        ),
        (
            "parser:CEC/native/enhanced_grammar_parser.py#EnhancedGrammarParser",
            SurfaceKind.PARSER,
            "EnhancedGrammarParser",
            "CEC/native/enhanced_grammar_parser.py",
            ("cec_dcec",),
            None,
            "CEC grammar parser island.",
        ),
        (
            "ast:CEC/native/syntax_tree.py#SyntaxTree",
            SurfaceKind.AST,
            "SyntaxTree",
            "CEC/native/syntax_tree.py",
            ("cec_dcec",),
            None,
            "CEC/DCEC syntax tree.",
        ),
        (
            "parser:fol/utils/fol_parser.py#parse_quantifiers",
            SurfaceKind.PARSER,
            "parse_quantifiers",
            "fol/utils/fol_parser.py",
            ("fol",),
            None,
            "Regex-based FOL quantifier parser.",
        ),
        (
            "printer:fol/utils/logic_formatter.py#format_fol",
            SurfaceKind.PRINTER,
            "format_fol",
            "fol/utils/logic_formatter.py",
            ("fol",),
            None,
            "FOL formula printer/formatter.",
        ),
        (
            "parser:deontic/utils/deontic_parser.py#extract_normative_elements",
            SurfaceKind.PARSER,
            "extract_normative_elements",
            "deontic/utils/deontic_parser.py",
            ("deontic",),
            None,
            "Deontic normative-element extraction parser.",
        ),
        (
            "result_decoder:deontic/decoder.py#decode_legal_norm_ir",
            SurfaceKind.RESULT_DECODER,
            "decode_legal_norm_ir",
            "deontic/decoder.py",
            ("deontic",),
            None,
            "Deterministic legal-norm decoder.",
        ),
        (
            "compiler:modal/compiler.py#DeterministicModalCompiler",
            SurfaceKind.COMPILER,
            "DeterministicModalCompiler",
            "modal/compiler.py",
            ("modal",),
            None,
            "Deterministic modal compiler.",
        ),
        (
            "result_decoder:modal/decompiler.py#decode_modal_ir_document",
            SurfaceKind.RESULT_DECODER,
            "decode_modal_ir_document",
            "modal/decompiler.py",
            ("modal",),
            None,
            "Modal IR decoder/decompiler.",
        ),
        (
            "formula:flogic/flogic_types.py#FLogicFrame",
            SurfaceKind.FORMULA,
            "FLogicFrame",
            "flogic/flogic_types.py",
            ("flogic",),
            None,
            "Frame Logic frame/formula type.",
        ),
        (
            "printer:flogic/flogic_types.py#to_ergo_string",
            SurfaceKind.PRINTER,
            "to_ergo_string",
            "flogic/flogic_types.py",
            ("flogic",),
            None,
            "ErgoAI textual printer for F-logic frames.",
        ),
        (
            "formula:software_verification/monitoring/runtime_mtl.py#Formula",
            SurfaceKind.FORMULA,
            "Formula",
            "software_verification/monitoring/runtime_mtl.py",
            ("runtime_mtl",),
            None,
            "Runtime MTL/LTLf formula tree.",
        ),
        (
            "compiler:backends/smt/compiler.py#SoftwareVerificationSMTCompiler",
            SurfaceKind.COMPILER,
            "SoftwareVerificationSMTCompiler",
            "backends/smt/compiler.py",
            ("solver_adapter",),
            None,
            "Shared SMT-LIB compiler for software-verification obligations.",
        ),
        (
            "compiler:backends/z3/compiler.py#Z3Compiler",
            SurfaceKind.COMPILER,
            "Z3Compiler",
            "backends/z3/compiler.py",
            ("solver_adapter",),
            None,
            "Z3 solver adapter compiler surface.",
        ),
        (
            "compiler:backends/cvc5/compiler.py#CVC5Compiler",
            SurfaceKind.COMPILER,
            "CVC5Compiler",
            "backends/cvc5/compiler.py",
            ("solver_adapter",),
            None,
            "cvc5 solver adapter compiler surface.",
        ),
        (
            "formula_boundary:formalization/views.py#FormalFormula.expression",
            SurfaceKind.FORMULA_BOUNDARY,
            "FormalFormula.expression",
            "formalization/views.py",
            ("fol", "modal", "deontic"),
            FormulaBoundaryKind.ARBITRARY_JSON,
            "FormalFormula.expression admits arbitrary FrozenJSON payloads without binding/sort structure.",
        ),
        (
            "formula_boundary:TDFOL/tdfol_parser.py#string_input",
            SurfaceKind.FORMULA_BOUNDARY,
            "string_input",
            "TDFOL/tdfol_parser.py",
            ("tdfol",),
            FormulaBoundaryKind.RAW_STRING,
            "TDFOL parser admits raw symbolic/NL string formulas.",
        ),
        (
            "formula_boundary:fol/utils/fol_parser.py#text_input",
            SurfaceKind.FORMULA_BOUNDARY,
            "text_input",
            "fol/utils/fol_parser.py",
            ("fol",),
            FormulaBoundaryKind.RAW_STRING,
            "FOL parser operates on raw natural-language strings.",
        ),
        (
            "formula_boundary:types/common_types.py#Formula.to_string",
            SurfaceKind.FORMULA_BOUNDARY,
            "Formula.to_string",
            "types/common_types.py",
            ("fol",),
            FormulaBoundaryKind.RAW_STRING,
            "Shared Formula protocol exposes only raw-string rendering.",
        ),
        (
            "formula_boundary:CEC/native/dcec_parsing.py#remove_comments.expression",
            SurfaceKind.FORMULA_BOUNDARY,
            "remove_comments.expression",
            "CEC/native/dcec_parsing.py",
            ("cec_dcec",),
            FormulaBoundaryKind.RAW_STRING,
            "DCEC preprocessing admits raw expression strings.",
        ),
        (
            "legacy_duplicate:fol/utils/deontic_parser.py",
            SurfaceKind.LEGACY_DUPLICATE,
            "deontic_parser",
            "fol/utils/deontic_parser.py",
            ("deontic", "fol"),
            None,
            "Deontic parser living under fol/utils; duplicates deontic package utilities.",
        ),
        (
            "legacy_duplicate:CEC/ARCHIVE",
            SurfaceKind.LEGACY_DUPLICATE,
            "CEC_ARCHIVE",
            "CEC/ARCHIVE",
            ("cec_dcec",),
            None,
            "Archived CEC surfaces retained as legacy evidence only.",
        ),
    )
    records: list[LogicSurfaceRecord] = []
    for (
        surface_id,
        kind,
        symbol,
        path,
        families,
        boundary,
        notes,
    ) in specs:
        records.append(
            LogicSurfaceRecord(
                surface_id=surface_id,
                kind=kind,
                symbol=symbol,
                path=path,
                qualname=symbol if "." not in symbol else symbol,
                family_hints=families,
                boundary_kind=boundary,
                notes=notes,
                discovery="curated",
            )
        )
    return tuple(records)


def _iter_python_files(
    base: Path, policy: SurfaceInventoryPolicy
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
                yield entry


def _scan_module(
    tree: ast.AST,
    *,
    rel_path: str,
    policy: SurfaceInventoryPolicy,
) -> list[LogicSurfaceRecord]:
    family_hints = _family_hints_for_path(rel_path)
    records: list[LogicSurfaceRecord] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            qualname = ".".join([*self.class_stack, node.name])
            if policy.include_private or not node.name.startswith("_"):
                kind = _classify_name(node.name, rel_path, is_class=True)
                if kind is not None:
                    records.append(
                        _record(
                            kind=kind,
                            symbol=node.name,
                            path=rel_path,
                            qualname=qualname,
                            family_hints=family_hints,
                            line=getattr(node, "lineno", None),
                        )
                    )
                for boundary in _class_formula_boundaries(
                    node, rel_path=rel_path, qualname=qualname, family_hints=family_hints
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
            kind = _classify_name(name, rel_path, is_class=False)
            if kind is not None:
                records.append(
                    _record(
                        kind=kind,
                        symbol=name,
                        path=rel_path,
                        qualname=qualname,
                        family_hints=family_hints,
                        line=getattr(node, "lineno", None),
                    )
                )
            for boundary in _function_formula_boundaries(
                node,
                rel_path=rel_path,
                qualname=qualname,
                family_hints=family_hints,
            ):
                records.append(boundary)
            self.generic_visit(node)

    Visitor().visit(tree)

    if _LEGACY_PATH_RE.search(rel_path):
        records.append(
            _record(
                kind=SurfaceKind.LEGACY_DUPLICATE,
                symbol=PurePosixPath(rel_path).stem,
                path=rel_path,
                qualname=PurePosixPath(rel_path).stem,
                family_hints=family_hints,
                notes="Path matches legacy/duplicate heuristic.",
            )
        )
    return records


def _class_formula_boundaries(
    node: ast.ClassDef,
    *,
    rel_path: str,
    qualname: str,
    family_hints: tuple[str, ...],
) -> list[LogicSurfaceRecord]:
    records: list[LogicSurfaceRecord] = []
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
            boundary = _boundary_from_annotation(ann_text)
            if boundary is None and name in {"expression", "formula", "text", "source"}:
                # Untyped expression-like fields are treated as raw-string
                # boundaries until a typed AST contract exists.
                boundary = FormulaBoundaryKind.RAW_STRING
            if boundary is None:
                continue
            field_qualname = f"{qualname}.{name}"
            records.append(
                _record(
                    kind=SurfaceKind.FORMULA_BOUNDARY,
                    symbol=field_qualname,
                    path=rel_path,
                    qualname=field_qualname,
                    family_hints=family_hints,
                    boundary_kind=boundary,
                    line=line,
                    notes=f"Field {name!r} admits {boundary.value} formula payloads.",
                )
            )
    return records


def _function_formula_boundaries(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    rel_path: str,
    qualname: str,
    family_hints: tuple[str, ...],
) -> list[LogicSurfaceRecord]:
    if not (
        _PARSER_NAME_RE.search(node.name)
        or node.name in {"loads", "from_string", "from_text", "from_json"}
    ):
        return []
    records: list[LogicSurfaceRecord] = []
    args = list(node.args.args) + list(node.args.kwonlyargs)
    if node.args.vararg is not None:
        args.append(node.args.vararg)
    if node.args.kwarg is not None:
        args.append(node.args.kwarg)
    for arg in args:
        if arg.arg in {"self", "cls"}:
            continue
        if not _EXPRESSION_PARAM_RE.match(arg.arg):
            continue
        ann_text = _annotation_text(arg.annotation)
        boundary = _boundary_from_annotation(ann_text)
        if boundary is None:
            boundary = FormulaBoundaryKind.RAW_STRING
        param_qualname = f"{qualname}.{arg.arg}"
        records.append(
            _record(
                kind=SurfaceKind.FORMULA_BOUNDARY,
                symbol=param_qualname,
                path=rel_path,
                qualname=param_qualname,
                family_hints=family_hints,
                boundary_kind=boundary,
                line=getattr(node, "lineno", None),
                notes=(
                    f"Parser parameter {arg.arg!r} admits "
                    f"{boundary.value} formula payloads."
                ),
            )
        )
    return records


def _boundary_from_annotation(ann_text: str) -> FormulaBoundaryKind | None:
    if not ann_text:
        return None
    if _ARBITRARY_JSON_ANN_RE.search(ann_text):
        return FormulaBoundaryKind.ARBITRARY_JSON
    if _RAW_STRING_ANN_RE.search(ann_text):
        return FormulaBoundaryKind.RAW_STRING
    return None


def _classify_name(
    name: str, rel_path: str, *, is_class: bool
) -> SurfaceKind | None:
    if _LEGACY_PATH_RE.search(rel_path) and is_class:
        # Prefer specific roles when names match; legacy path also emits a
        # dedicated legacy_duplicate record for the file.
        pass
    if _PARSER_NAME_RE.search(name):
        return SurfaceKind.PARSER
    if _DECODER_NAME_RE.search(name):
        return SurfaceKind.RESULT_DECODER
    if _COMPILER_NAME_RE.search(name):
        return SurfaceKind.COMPILER
    if _PRINTER_NAME_RE.search(name):
        return SurfaceKind.PRINTER
    if _FORMULA_NAME_RE.search(name):
        return SurfaceKind.FORMULA
    if _TERM_NAME_RE.search(name):
        return SurfaceKind.TERM
    if _AST_NAME_RE.search(name):
        return SurfaceKind.AST
    if is_class and _TYPE_NAME_RE.search(name):
        return SurfaceKind.TYPE
    return None


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
    if lower.startswith("backends/") or "external_provers" in lower or "hammers" in lower:
        hints.add("solver_adapter")
    if "formalization" in lower:
        hints.update({"fol", "modal", "deontic"})
    return tuple(sorted(hints))


def _record(
    *,
    kind: SurfaceKind,
    symbol: str,
    path: str,
    qualname: str,
    family_hints: tuple[str, ...] = (),
    boundary_kind: FormulaBoundaryKind | None = None,
    line: int | None = None,
    notes: str = "",
    discovery: str = "ast_scan",
) -> LogicSurfaceRecord:
    surface_id = f"{kind.value}:{path}#{qualname}"
    return LogicSurfaceRecord(
        surface_id=surface_id,
        kind=kind,
        symbol=symbol,
        path=path,
        qualname=qualname,
        family_hints=family_hints,
        boundary_kind=boundary_kind,
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
        raise InventoryError(
            f"{field_name} must be a normalized relative POSIX path; got {value!r}"
        )
    normalized = path.as_posix()
    if normalized != text.replace("\\", "/"):
        # Allow only already-normalized forms (no trailing slash except root).
        if text.replace("\\", "/").rstrip("/") != normalized:
            raise InventoryError(
                f"{field_name} must be a normalized relative POSIX path; got {value!r}"
            )
    return normalized


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise InventoryError(f"{field_name} must be a string")
    if "\x00" in value:
        raise InventoryError(f"{field_name} must not contain NUL bytes")
    if not allow_empty and not value.strip():
        raise InventoryError(f"{field_name} must be a non-empty string")
    return value


def _identifier(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*", text):
        raise InventoryError(
            f"{field_name} must be a lowercase identifier; got {text!r}"
        )
    return text


def _enum(value: object, enum_type: type[StrEnum], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(str(value))
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise InventoryError(f"{field_name} must be one of {choices}") from error


__all__ = [
    "DEFAULT_BASELINE_REPORT_RELATIVE",
    "DEFAULT_LOGIC_RELATIVE_ROOTS",
    "DEFAULT_MAX_FILE_BYTES",
    "DEFAULT_MAX_SCANNED_FILES",
    "DEFAULT_MAX_SURFACES",
    "FormulaBoundaryKind",
    "INVENTORY_GOAL_ID",
    "INVENTORY_TASK_ID",
    "InventoryError",
    "InventoryIncompleteError",
    "LOGIC_SURFACE_INVENTORY_INTERFACE",
    "LOGIC_SURFACE_INVENTORY_SCHEMA_VERSION",
    "LogicSurfaceInventory",
    "LogicSurfaceRecord",
    "REQUIRED_EVIDENCE_FAMILIES",
    "SurfaceInventoryPolicy",
    "SurfaceKind",
    "assert_inventory_complete",
    "build_parser_inventory_report",
    "curated_logic_surface_inventory",
    "default_baseline_report_path",
    "default_datasets_package_root",
    "default_logic_package_root",
    "inventory_logic_surfaces",
    "load_parser_inventory",
    "write_parser_inventory",
]
