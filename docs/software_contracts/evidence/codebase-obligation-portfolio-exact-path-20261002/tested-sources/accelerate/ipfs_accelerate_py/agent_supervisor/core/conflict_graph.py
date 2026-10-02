"""Conflict-surface prediction and explainable lane coloring.

The dependency graph answers *when* a task is ready.  This module answers the
orthogonal question of which ready tasks are safe to execute together.  It
models every declared work surface (not merely the first output path), augments
predictions with branch observations and merge-conflict receipts, and produces
a deterministic coloring with an explanation for every pair of tasks.

The data types deliberately serialize to ordinary JSON objects.  Supervisor
manifests can therefore retain the plan and its evidence without importing this
module when they are inspected by another process.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from hashlib import sha1
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from ..task_sources.task_identity import canonical_content_cid, canonical_json_bytes


DEFAULT_SURFACE_WEIGHTS: dict[str, float] = {
    "files": 8.0,
    "changed_paths": 10.0,
    "ast_symbols": 2.0,
    "interfaces": 7.0,
    "submodules": 12.0,
    "generated_artifacts": 9.0,
}
CONFLICT_RECEIPT_STATUSES = frozenset(
    {"conflict", "conflicted", "merge_conflict", "resolved"}
)
AST_BLOB_RECORD_SCHEMA_VERSION = 1
MAX_CONFLICT_HISTORY_EVIDENCE_IDS = 4096
_ADMISSION_TASK_WORK_CONTRACT_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/task-work-contract@1"
)
TASK_PLANNING_WORK_CONTRACT_SCHEMA = (
    "ipfs_accelerate_py/agent-supervisor/task-planning-work-contract@1"
)
_DERIVED_CONFLICT_METADATA_FIELDS = frozenset(
    {
        "conflict_decisions",
        "conflict_edges",
        "conflict_graph",
        "conflict_planning_decisions",
        "conflict_surface",
        "coverage_inputs",
        "dependency_dag",
        "task_conflict_graph",
        "task_dependency_graph",
        "task_planning_graph",
        "todo_coverage_inputs",
        "todo_vector_summary",
    }
)


def _source_sha256(source: str) -> str:
    return "sha256:" + hashlib.sha256(source.encode("utf-8", errors="surrogatepass")).hexdigest()


def _ast_expression_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _ast_expression_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Subscript):
        parent = _ast_expression_name(node.value)
        try:
            index = ast.unparse(node.slice)
        except (AttributeError, ValueError):
            index = "?"
        return f"{parent}[{index}]" if parent else f"[{index}]"
    if isinstance(node, ast.Call):
        return _ast_expression_name(node.func)
    return ""


def _ast_render(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return " ".join(ast.unparse(node).split())
    except (AttributeError, ValueError):
        return type(node).__name__


def _ast_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Return a deterministic, annotation-preserving Python signature."""

    try:
        arguments = ast.unparse(node.args)
        returns = f" -> {_ast_render(node.returns)}" if node.returns is not None else ""
        prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        return f"{prefix}def {node.name}({arguments}){returns}"
    except (AttributeError, ValueError):
        arguments = [argument.arg for argument in node.args.args]
        return f"{'async ' if isinstance(node, ast.AsyncFunctionDef) else ''}def {node.name}({', '.join(arguments)})"


@dataclass(frozen=True)
class ASTBlobRecord:
    """Path-independent Python facts cached by source/blob identity.

    Paths deliberately do not participate in this record.  A Git rename can
    therefore reuse the parse while the proof-scope compiler separately
    qualifies the facts under the old and new modules.
    """

    blob_identity: str
    source_sha256: str
    qualified_symbols: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()
    state_transitions: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    symbol_hashes: Mapping[str, str] = field(default_factory=dict)
    symbol_lines: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    parse_error: str = ""
    language: str = "python"
    record_schema_version: int = AST_BLOB_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        version = int(self.record_schema_version)
        if version != AST_BLOB_RECORD_SCHEMA_VERSION:
            raise ValueError(f"unsupported AST blob record schema version: {version}")
        object.__setattr__(self, "record_schema_version", version)
        source_hash = str(self.source_sha256 or "").strip()
        if source_hash and ":" not in source_hash:
            source_hash = f"sha256:{source_hash}"
        blob = str(self.blob_identity or source_hash).strip()
        object.__setattr__(self, "source_sha256", source_hash)
        object.__setattr__(self, "blob_identity", blob)
        for name in (
            "qualified_symbols",
            "imports",
            "calls",
            "state_transitions",
            "interfaces",
        ):
            object.__setattr__(
                self,
                name,
                tuple(sorted({str(item).strip() for item in getattr(self, name) if str(item).strip()})),
            )
        object.__setattr__(
            self,
            "symbol_hashes",
            {
                str(key): str(value)
                for key, value in sorted(dict(self.symbol_hashes).items())
                if str(key) and str(value)
            },
        )
        normalized_lines: dict[str, tuple[int, int]] = {}
        for key, value in sorted(dict(self.symbol_lines).items()):
            try:
                start, end = value
                normalized_lines[str(key)] = (max(0, int(start)), max(0, int(end)))
            except (TypeError, ValueError):
                continue
        object.__setattr__(self, "symbol_lines", normalized_lines)
        object.__setattr__(self, "parse_error", str(self.parse_error or "").strip())

    @property
    def record_id(self) -> str:
        payload = self._payload()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return "ast-sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def blob_id(self) -> str:
        return self.blob_identity

    @property
    def source_hash(self) -> str:
        return self.source_sha256

    def _payload(self) -> dict[str, Any]:
        return {
            "record_schema_version": self.record_schema_version,
            "blob_identity": self.blob_identity,
            "blob_hash": self.blob_identity,
            "source_sha256": self.source_sha256,
            "language": self.language,
            "qualified_symbols": list(self.qualified_symbols),
            "imports": list(self.imports),
            "calls": list(self.calls),
            "state_transitions": list(self.state_transitions),
            "interfaces": list(self.interfaces),
            "symbol_hashes": dict(self.symbol_hashes),
            "symbol_lines": {
                key: list(value) for key, value in sorted(self.symbol_lines.items())
            },
            "parse_error": self.parse_error,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"record_id": self.record_id, **self._payload()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ASTBlobRecord":
        record = coerce_ast_blob_record(value)
        if record is None:
            raise ValueError("invalid AST blob record")
        claimed_id = str(value.get("record_id") or "")
        if claimed_id and claimed_id != record.record_id:
            raise ValueError("AST blob record identity does not match payload")
        return record


def build_python_ast_blob_record(
    source: str,
    *,
    blob_identity: str = "",
    source_sha256: str = "",
) -> ASTBlobRecord:
    """Parse reusable, typed Python facts for one exact source blob."""

    source_hash = source_sha256 or _source_sha256(source)
    blob = str(blob_identity or source_hash)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        location = ""
        if isinstance(exc, SyntaxError) and exc.lineno:
            location = f" at line {exc.lineno}"
        return ASTBlobRecord(
            blob_identity=blob,
            source_sha256=source_hash,
            parse_error=f"{type(exc).__name__}{location}: {exc.msg if isinstance(exc, SyntaxError) else exc}",
        )

    symbols: set[str] = set()
    imports: set[str] = set()
    calls: set[str] = set()
    transitions: set[str] = set()
    interfaces: set[str] = set()
    symbol_hashes: dict[str, str] = {}
    symbol_lines: dict[str, tuple[int, int]] = {}
    scope: list[str] = []

    class Visitor(ast.NodeVisitor):
        def _owner(self) -> str:
            return ".".join(scope) or "<module>"

        def _definition(
            self,
            node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
        ) -> None:
            qualified = ".".join([*scope, node.name])
            symbols.add(qualified)
            semantic = ast.dump(node, annotate_fields=True, include_attributes=False)
            symbol_hashes[qualified] = "sha256:" + hashlib.sha256(
                semantic.encode("utf-8")
            ).hexdigest()
            symbol_lines[qualified] = (
                int(getattr(node, "lineno", 0) or 0),
                int(getattr(node, "end_lineno", getattr(node, "lineno", 0)) or 0),
            )
            if isinstance(node, ast.ClassDef):
                bases = {_ast_expression_name(base) for base in node.bases}
                if bases & {"Protocol", "typing.Protocol", "ABC", "abc.ABC", "ABCMeta", "abc.ABCMeta"}:
                    interfaces.add(f"{qualified}({','.join(sorted(base for base in bases if base))})")
            else:
                public = not node.name.startswith("_") or node.name == "__init__"
                decorators = {_ast_expression_name(item) for item in node.decorator_list}
                if public or decorators & {"abstractmethod", "abc.abstractmethod"}:
                    interfaces.add(f"{qualified}:{_ast_signature(node)}")
            scope.append(node.name)
            self.generic_visit(node)
            scope.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._definition(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._definition(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._definition(node)

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                imports.add(
                    f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
                )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            module = "." * int(node.level or 0) + (node.module or "")
            for alias in node.names:
                imports.add(
                    f"from {module} import {alias.name}"
                    + (f" as {alias.asname}" if alias.asname else "")
                )

        def visit_Call(self, node: ast.Call) -> None:
            callee = _ast_expression_name(node.func) or "<dynamic>"
            calls.add(f"{self._owner()}->{callee}")
            lowered = callee.rsplit(".", 1)[-1].lower()
            if lowered in {
                "transition",
                "transition_to",
                "set_state",
                "set_status",
                "change_state",
                "update_state",
            }:
                arguments = ",".join(_ast_render(argument) for argument in node.args)
                transitions.add(f"{self._owner()}:{callee}:call({arguments})")
            self.generic_visit(node)

        def _assignments(
            self,
            targets: Iterable[ast.AST],
            operation: str,
            value: ast.AST | None = None,
        ) -> None:
            rendered_value = _ast_render(value)
            for target in targets:
                name = _ast_expression_name(target)
                if name:
                    suffix = f":{rendered_value}" if rendered_value else ""
                    transitions.add(f"{self._owner()}:{name}:{operation}{suffix}")

        def visit_Assign(self, node: ast.Assign) -> None:
            self._assignments(node.targets, "assign", node.value)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self._assignments((node.target,), "assign", node.value)
            self.generic_visit(node)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            self._assignments(
                (node.target,),
                f"augassign:{type(node.op).__name__}",
                node.value,
            )
            self.generic_visit(node)

        def visit_Delete(self, node: ast.Delete) -> None:
            self._assignments(node.targets, "delete")
            self.generic_visit(node)

    Visitor().visit(tree)
    return ASTBlobRecord(
        blob_identity=blob,
        source_sha256=source_hash,
        qualified_symbols=tuple(symbols),
        imports=tuple(imports),
        calls=tuple(calls),
        state_transitions=tuple(transitions),
        interfaces=tuple(interfaces),
        symbol_hashes=symbol_hashes,
        symbol_lines=symbol_lines,
    )


def coerce_ast_blob_record(value: Any) -> ASTBlobRecord | None:
    """Normalize conflict-graph, objective-dataset, or serialized AST records."""

    if isinstance(value, ASTBlobRecord):
        return value
    if not isinstance(value, Mapping):
        return None
    payload = dict(value)
    source = payload.get("source") or payload.get("source_text") or payload.get("evidence_text")
    blob = str(
        payload.get("blob_identity")
        or payload.get("blob_id")
        or payload.get("blob_hash")
        or ""
    )
    source_hash = str(payload.get("source_sha256") or "")
    if isinstance(source, str):
        actual_hash = _source_sha256(source)
        normalized_source_hash = (
            source_hash[len("sha256:") :]
            if source_hash.startswith("sha256:")
            else source_hash
        )
        normalized_actual_hash = actual_hash[len("sha256:") :]
        if source_hash and normalized_source_hash != normalized_actual_hash:
            return None
        # Reparse legacy objective rows: their ast_text and symbols do not
        # contain the calls, transitions, and interfaces needed by proof work.
        return build_python_ast_blob_record(
            source,
            blob_identity=blob,
            source_sha256=actual_hash,
        )
    if not source_hash:
        legacy_sha1 = str(payload.get("source_sha1") or "")
        if not legacy_sha1:
            return None
        source_hash = (
            legacy_sha1 if legacy_sha1.startswith("sha1:") else f"sha1:{legacy_sha1}"
        )
    try:
        return ASTBlobRecord(
            blob_identity=blob or source_hash,
            source_sha256=source_hash,
            qualified_symbols=tuple(payload.get("qualified_symbols") or payload.get("symbols") or ()),
            imports=tuple(payload.get("imports") or ()),
            calls=tuple(payload.get("calls") or ()),
            state_transitions=tuple(payload.get("state_transitions") or ()),
            interfaces=tuple(payload.get("interfaces") or ()),
            symbol_hashes=payload.get("symbol_hashes") or {},
            symbol_lines=payload.get("symbol_lines") or {},
            parse_error=str(payload.get("parse_error") or ""),
            language=str(payload.get("language") or "python"),
        )
    except (TypeError, ValueError):
        return None


def index_ast_blob_records(records: Iterable[Any]) -> dict[str, ASTBlobRecord]:
    """Index reusable records by blob, source hash, and record identity."""

    result: dict[str, ASTBlobRecord] = {}
    for value in records:
        record = coerce_ast_blob_record(value)
        if record is None:
            continue
        for identity in (record.blob_identity, record.source_sha256, record.record_id):
            if identity:
                result.setdefault(identity, record)
    return result


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        result = asdict(value)
        return dict(result) if isinstance(result, dict) else {}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        return dict(result) if isinstance(result, Mapping) else {}
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _normalized_field_key(value: Any) -> str:
    """Return the canonical lookup spelling for task metadata fields."""

    return re.sub(
        r"[^a-z0-9]+",
        "_",
        str(value or "").strip().casefold(),
    ).strip("_")


def _source_with_normalized_keys(source: Mapping[str, Any]) -> dict[str, Any]:
    """Add non-destructive aliases for human-readable metadata keys.

    Legacy Markdown task boards retain labels such as ``Goal id`` and
    ``Allow concurrent with`` in their nested metadata mapping.  Conflict and
    work-contract consumers use their wire spellings (``goal_id`` and
    ``allow_concurrent_with``).  Preserve the producer's original mapping for
    audit while making both representations equivalent at this boundary.
    Explicit wire-format keys always win if a producer supplied both forms.
    """

    result = dict(source)
    for key, value in source.items():
        normalized = _normalized_field_key(key)
        if normalized:
            result.setdefault(normalized, value)
    return result


def _sources(value: Any) -> list[dict[str, Any]]:
    """Return top-level and common nested task metadata mappings."""

    root = _source_with_normalized_keys(_payload(value))
    found = [root]
    for key in ("finding", "metadata", "conflict_surface", "profile_g", "payload"):
        nested = root.get(key)
        if isinstance(nested, Mapping):
            found.append(_source_with_normalized_keys(nested))
    return found


def _items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # Symbols and paths may be supplied by markdown fields.
        return [item.strip() for item in re.split(r"[,;\n]", value) if item.strip()]
    if isinstance(value, Mapping):
        return [str(key).strip() for key, enabled in value.items() if enabled and str(key).strip()]
    if isinstance(value, Iterable):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _field_items(sources: Sequence[Mapping[str, Any]], names: Sequence[str]) -> list[str]:
    values: list[str] = []
    for source in sources:
        for name in names:
            values.extend(_items(source.get(name)))
    return values


def _contract_integer(
    sources: Sequence[Mapping[str, Any]],
    names: Sequence[str],
) -> int:
    """Return one consistent non-negative integer declared by task metadata."""

    values: list[int] = []
    for source in sources:
        for name in names:
            if name not in source or source[name] in (None, ""):
                continue
            value = source[name]
            if isinstance(value, bool):
                raise ValueError(f"{name} must be a non-negative integer")
            try:
                parsed = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{name} must be a non-negative integer"
                ) from exc
            if parsed < 0 or str(value).strip() not in {
                str(parsed),
                f"{parsed}.0",
            }:
                raise ValueError(f"{name} must be a non-negative integer")
            values.append(parsed)
    if len(set(values)) > 1:
        raise ValueError(
            f"task work contract contains inconsistent {names[0]} values"
        )
    return values[0] if values else 0


@dataclass(frozen=True)
class TaskWorkContract:
    """Canonical acceptance/effect, predicted-scope, and cost binding.

    This is planning evidence, not completion authority.  Its purpose is to
    prevent task admission, conflict planning, vector compaction, and bundle
    execution from silently projecting different work.
    """

    canonical_task_cid: str
    canonical_task_key: str
    goal_id: str
    acceptance: tuple[str, ...]
    effects: tuple[str, ...]
    evidence_subset: tuple[str, ...]
    predicted_paths: tuple[str, ...]
    predicted_symbols: tuple[str, ...]
    context_paths: tuple[str, ...]
    estimated_context_tokens: int
    estimated_tokens: int
    estimated_validation_seconds: int
    resource_class: str
    token_class: str
    dependency_count: int
    conflict_count: int
    preconditions: tuple[str, ...]
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]
    validation_commands: tuple[str, ...]
    merge_fate: str
    work_contract_id: str
    task_work_contract_id: str

    def _material(self) -> dict[str, Any]:
        normalize_semantic = lambda value: " ".join(
            re.findall(r"[a-z0-9]+", str(value or "").casefold())
        )
        return {
            "schema": _ADMISSION_TASK_WORK_CONTRACT_SCHEMA,
            "goal_id": normalize_semantic(self.goal_id),
            "acceptance_effect_subset": {
                "acceptance": sorted(
                    normalize_semantic(value) for value in self.acceptance
                ),
                "effects": sorted(
                    normalize_semantic(value) for value in self.effects
                ),
                "evidence_subset": sorted(
                    normalize_semantic(value)
                    for value in self.evidence_subset
                ),
            },
            "predicted_scope": {
                "paths": list(self.predicted_paths),
                "symbols": sorted(
                    normalize_semantic(value)
                    for value in self.predicted_symbols
                ),
                "context_paths": list(self.context_paths),
            },
            "predicted_costs": {
                "context_tokens": self.estimated_context_tokens,
                "validation_seconds": self.estimated_validation_seconds,
                "task_tokens": self.estimated_tokens,
                "resource_class": self.resource_class,
                "token_class": self.token_class,
                "dependency_count": self.dependency_count,
                "conflict_count": self.conflict_count,
            },
            "execution_boundary": {
                "preconditions": sorted(
                    normalize_semantic(value) for value in self.preconditions
                ),
                "dependencies": list(self.dependencies),
                "conflicts": list(self.conflicts),
                "validation_commands": list(self.validation_commands),
                "merge_fate": normalize_semantic(self.merge_fate),
            },
        }

    @property
    def acceptance_subset(self) -> tuple[str, ...]:
        return self.acceptance

    @property
    def effect_subset(self) -> tuple[str, ...]:
        return self.effects

    @property
    def contract_id(self) -> str:
        """Compatibility alias for the producer-owned identity spelling."""

        return self.work_contract_id

    def verify_integrity(self) -> bool:
        accepted = (
            self.work_contract_id == canonical_content_cid(self._material())
            and self.task_work_contract_id
            == canonical_content_cid(self._binding_material())
        )
        try:
            from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
                mirror_work_record,
            )

            record_ref = str(
                self.work_contract_id or self.canonical_task_cid or "task-work-contract"
            )
            mirror_work_record(
                catalog_kind="metadata",
                record_kind="task_work_contract_integrity",
                record_ref=record_ref,
                subject_kind="task_id",
                subject_ref=str(self.canonical_task_cid or record_ref),
            )
        except Exception:
            pass
        return accepted

    def _binding_material(self) -> dict[str, Any]:
        return {
            "schema": TASK_PLANNING_WORK_CONTRACT_SCHEMA,
            "canonical_task_cid": self.canonical_task_cid,
            "canonical_task_key": self.canonical_task_key,
            "work_contract_id": self.work_contract_id,
            "work_contract": self._material(),
            "acceptance_subset": list(self.acceptance),
            "effect_subset": list(self.effects),
            "evidence_subset": list(self.evidence_subset),
            "predicted_paths": list(self.predicted_paths),
            "predicted_symbols": list(self.predicted_symbols),
            "context_paths": list(self.context_paths),
            "estimated_costs": {
                "context_tokens": self.estimated_context_tokens,
                "task_tokens": self.estimated_tokens,
                "validation_seconds": self.estimated_validation_seconds,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._binding_material(),
            "task_work_contract_id": self.task_work_contract_id,
        }

    @classmethod
    def from_task(cls, task: Any) -> "TaskWorkContract":
        sources = _sources(task)
        root = sources[0]
        canonical_task_cid = str(
            root.get("canonical_task_cid")
            or root.get("task_cid")
            # ``build_conflict_surface`` uses the public task identifier as
            # the compatibility CID when a producer has not emitted a
            # separate content identity.  Derive the contract with the same
            # rule so reconstructing it from the surface is stable.
            or root.get("task_id")
            or root.get("id")
            or root.get("canonical_task_id")
            or ""
        ).strip()
        canonical_task_key = str(
            root.get("canonical_task_key") or ""
        ).strip()
        normalize_semantic = lambda value: " ".join(
            re.findall(r"[a-z0-9]+", str(value or "").casefold())
        )
        normalize_display = lambda value: " ".join(
            str(value or "").split()
        )
        acceptance = tuple(
            sorted(
                {
                    normalize_display(value)
                    for value in _field_items(
                    sources,
                    (
                        "acceptance_subset",
                        "acceptance_criteria",
                        "acceptance",
                    ),
                )
                    if normalize_display(value)
                }
            )
        )
        effects = tuple(
            sorted(
                {
                    normalize_display(value)
                    for value in
                _field_items(
                    sources,
                    ("effect_subset", "effects", "expected_effects"),
                )
                    if normalize_display(value)
                }
            )
        )
        evidence_subset = tuple(
            sorted(
                {
                    normalize_display(value)
                    for value in _field_items(
                        sources,
                        (
                            "evidence_subset",
                            "missing_evidence",
                            "expected_evidence_delta",
                        ),
                    )
                    if normalize_display(value)
                }
            )
        )
        has_declared_paths = any(
            name in source
            for source in sources
            for name in ("predicted_paths", "predicted_files", "outputs")
        )
        declared_paths = _field_items(
            sources,
            ("predicted_paths", "predicted_files", "outputs"),
        )
        predicted_paths = tuple(
            sorted(
                {
                    path.casefold()
                    for path in _normalized_paths(
                    declared_paths
                    if has_declared_paths
                    else _field_items(sources, ("files",)),
                    None,
                )
                }
            )
        )
        has_declared_symbols = any(
            "predicted_symbols" in source for source in sources
        )
        declared_symbols = _field_items(sources, ("predicted_symbols",))
        predicted_symbols = tuple(
            sorted(
                {
                    normalize_display(value)
                    for value in (
                        declared_symbols
                        if has_declared_symbols
                        else _field_items(
                            sources,
                            ("ast_symbols", "symbols", "ast_query"),
                        )
                    )
                    if normalize_display(value)
                }
            )
        )
        context_paths = tuple(
            sorted(
                {
                    path.casefold()
                    for path in _normalized_paths(
                    _field_items(
                        sources,
                        ("context_paths", "context_keys", "context_files"),
                    ),
                    None,
                )
                }
            )
        )
        context_tokens = _contract_integer(
            sources,
            ("estimated_context_tokens", "context_tokens"),
        )
        task_tokens = _contract_integer(
            sources,
            ("estimated_tokens", "token_cost"),
        )
        validation_seconds = _contract_integer(
            sources,
            (
                "estimated_validation_seconds",
                "validation_seconds",
                "validation_cost",
            ),
        )
        dependencies = tuple(
            sorted(
                set(
                    _field_items(
                        sources,
                        (
                            "dependencies",
                            "depends_on",
                            "dependency_task_cids",
                        ),
                    )
                )
            )
        )
        conflicts = tuple(
            sorted(
                set(
                    _field_items(
                        sources,
                        ("conflicts", "conflict_keys"),
                    )
                )
            )
        )
        preconditions = tuple(
            sorted(
                {
                    normalize_semantic(value)
                    for value in _field_items(
                        sources,
                        ("preconditions", "required_preconditions"),
                    )
                    if normalize_semantic(value)
                }
            )
        )
        validation_commands = tuple(
            sorted(
                set(
                    _field_items(
                        sources,
                        ("validation_commands", "validation"),
                    )
                )
            )
        )
        goal_id = normalize_display(
            next(
                (
                    source.get("goal_id")
                    for source in sources
                    if source.get("goal_id")
                ),
                "",
            )
        )
        resource_class = str(
            next(
                (
                    source.get("resource_class")
                    for source in sources
                    if source.get("resource_class")
                ),
                "",
            )
        ).strip().casefold()
        token_class = str(
            next(
                (
                    source.get("token_class")
                    for source in sources
                    if source.get("token_class")
                ),
                "",
            )
        ).strip().casefold()
        merge_fate = normalize_display(
            next(
                (
                    source.get("merge_fate")
                    or source.get("merge_family")
                    or source.get("merge_key")
                    for source in sources
                    if source.get("merge_fate")
                    or source.get("merge_family")
                    or source.get("merge_key")
                ),
                "",
            )
        )
        draft = cls(
            canonical_task_cid=canonical_task_cid,
            canonical_task_key=canonical_task_key,
            goal_id=goal_id,
            acceptance=acceptance,
            effects=effects,
            evidence_subset=evidence_subset,
            predicted_paths=predicted_paths,
            predicted_symbols=predicted_symbols,
            context_paths=context_paths,
            estimated_context_tokens=context_tokens,
            estimated_tokens=task_tokens,
            estimated_validation_seconds=validation_seconds,
            resource_class=resource_class,
            token_class=token_class,
            dependency_count=len(dependencies),
            conflict_count=len(conflicts),
            preconditions=preconditions,
            dependencies=dependencies,
            conflicts=conflicts,
            validation_commands=validation_commands,
            merge_fate=merge_fate,
            work_contract_id="",
            task_work_contract_id="",
        )
        work_contract_id = canonical_content_cid(draft._material())
        result = replace(
            draft,
            work_contract_id=work_contract_id,
        )
        result = replace(
            result,
            task_work_contract_id=canonical_content_cid(
                result._binding_material()
            ),
        )

        admission_contract = root.get("work_contract")
        if admission_contract not in (None, {}):
            if not isinstance(admission_contract, Mapping):
                raise ValueError("work_contract must be a mapping")
            if canonical_json_bytes(
                dict(admission_contract)
            ) != canonical_json_bytes(result._material()):
                raise ValueError(
                    "work_contract does not match canonical task fields"
                )
        explicit = root.get("task_work_contract")
        if explicit not in (None, {}):
            if not isinstance(explicit, Mapping):
                raise ValueError("task_work_contract must be a mapping")
            if canonical_json_bytes(dict(explicit)) != canonical_json_bytes(
                result.to_dict()
            ):
                expected_binding = result.to_dict()
                differing_fields = sorted(
                    key
                    for key in set(explicit) | set(expected_binding)
                    if canonical_json_bytes(explicit.get(key))
                    != canonical_json_bytes(expected_binding.get(key))
                )
                task_label = str(
                    root.get("task_id")
                    or root.get("canonical_task_cid")
                    or root.get("task_cid")
                    or "<unknown>"
                ).strip()
                raise ValueError(
                    "task_work_contract does not match canonical task fields "
                    f"for {task_label}; differing fields: "
                    f"{', '.join(differing_fields) or '<unknown>'}"
                )
        supplied_id = str(
            root.get("work_contract_id") or ""
        ).strip()
        if supplied_id and supplied_id != result.work_contract_id:
            raise ValueError(
                "work_contract_id does not match canonical task fields"
            )
        supplied_binding_id = str(
            root.get("task_work_contract_id") or ""
        ).strip()
        if (
            supplied_binding_id
            and supplied_binding_id != result.task_work_contract_id
        ):
            raise ValueError(
                "task_work_contract_id does not match canonical task fields"
            )
        return result


def build_task_work_contract(task: Any) -> TaskWorkContract:
    """Build and verify the canonical work contract for one task projection."""

    return TaskWorkContract.from_task(task)


def rehydrate_task_work_contract_projection(task: Any) -> dict[str, Any]:
    """Restore contract-bound fields omitted or rewritten by a projection.

    Bounded planning artifacts intentionally omit bulky conflict surfaces and
    dependency planning replaces display aliases with resolved CIDs.  Both
    operations can make a projected row differ from its admitted work
    contract.  Consumers that optimize the admitted work may use this helper
    to construct a local, contract-authoritative copy without changing the
    scheduler's projection.

    The explicit contract remains mandatory and is verified after
    rehydration.  A malformed contract, mismatched task identity, or invalid
    content address therefore still fails closed.
    """

    projected = _payload(task)
    work_contract = projected.get("work_contract")
    task_work_contract = projected.get("task_work_contract")
    if work_contract in (None, {}) and task_work_contract in (None, {}):
        return projected
    if not isinstance(work_contract, Mapping):
        raise ValueError("work_contract must be a mapping")
    if not isinstance(task_work_contract, Mapping):
        raise ValueError("task_work_contract must be a mapping")

    material = dict(work_contract)
    binding = dict(task_work_contract)
    if not isinstance(binding.get("work_contract"), Mapping):
        raise ValueError("task_work_contract.work_contract must be a mapping")
    if canonical_json_bytes(dict(binding["work_contract"])) != canonical_json_bytes(
        material
    ):
        raise ValueError("task_work_contract does not bind work_contract")

    def mapping_field(
        source: Mapping[str, Any],
        key: str,
    ) -> dict[str, Any]:
        value = source.get(key)
        if not isinstance(value, Mapping):
            raise ValueError(f"work contract field {key} must be a mapping")
        return dict(value)

    acceptance_effect = mapping_field(material, "acceptance_effect_subset")
    predicted_scope = mapping_field(material, "predicted_scope")
    predicted_costs = mapping_field(material, "predicted_costs")
    execution_boundary = mapping_field(material, "execution_boundary")
    estimated_costs = mapping_field(binding, "estimated_costs")

    # Remove every alias consumed by TaskWorkContract.from_task so omitted
    # conflict-surface values and scheduler-resolved dependency CIDs cannot be
    # unioned with the contract-authoritative values below.  ``from_task``
    # deliberately reads common nested producer projections as well as the
    # root row.  Sanitising only the root therefore leaves stale aliases in a
    # nested ``metadata``/``finding``/``conflict_surface`` mapping and makes a
    # valid admitted contract fail incremental bundle-index regeneration.
    contract_aliases = (
        "acceptance_subset",
        "acceptance_criteria",
        "acceptance",
        "effect_subset",
        "effects",
        "expected_effects",
        "evidence_subset",
        "missing_evidence",
        "expected_evidence_delta",
        "predicted_paths",
        "predicted_files",
        "outputs",
        "predicted_symbols",
        "ast_symbols",
        "symbols",
        "ast_query",
        "context_paths",
        "context_keys",
        "context_files",
        "estimated_context_tokens",
        "context_tokens",
        "estimated_tokens",
        "token_cost",
        "estimated_validation_seconds",
        "validation_seconds",
        "validation_cost",
        "dependencies",
        "depends_on",
        "dependency_task_cids",
        "conflicts",
        "conflict_keys",
        "preconditions",
        "required_preconditions",
        "validation_commands",
        "validation",
        "merge_fate",
        "merge_family",
        "merge_key",
        "goal_id",
        "resource_class",
        "token_class",
    )
    for key in contract_aliases:
        projected.pop(key, None)
    for source_key in (
        "finding",
        "metadata",
        "conflict_surface",
        "profile_g",
        "payload",
    ):
        nested = projected.get(source_key)
        if not isinstance(nested, Mapping):
            continue
        sanitized = dict(nested)
        for key in contract_aliases:
            sanitized.pop(key, None)
            # Human-readable Markdown metadata keys are normalized by
            # ``_sources``.  Remove those spellings as well or they can
            # reintroduce a stale alias after normalization.
            for existing_key in tuple(sanitized):
                if _normalized_field_key(existing_key) == key:
                    sanitized.pop(existing_key, None)
        projected[source_key] = sanitized

    dependencies = list(execution_boundary.get("dependencies") or [])
    projected.update(
        {
            "goal_id": material.get("goal_id") or "",
            "acceptance_subset": list(binding.get("acceptance_subset") or []),
            "effect_subset": list(binding.get("effect_subset") or []),
            "evidence_subset": list(binding.get("evidence_subset") or []),
            "predicted_paths": list(binding.get("predicted_paths") or []),
            "outputs": list(binding.get("predicted_paths") or []),
            "predicted_symbols": list(binding.get("predicted_symbols") or []),
            "context_paths": list(binding.get("context_paths") or []),
            "estimated_context_tokens": estimated_costs.get(
                "context_tokens", 0
            ),
            "estimated_tokens": estimated_costs.get("task_tokens", 0),
            "estimated_validation_seconds": estimated_costs.get(
                "validation_seconds", 0
            ),
            "resource_class": predicted_costs.get("resource_class") or "",
            "token_class": predicted_costs.get("token_class") or "",
            "dependencies": dependencies,
            "depends_on": dependencies,
            "dependency_task_cids": dependencies,
            "conflicts": list(execution_boundary.get("conflicts") or []),
            "preconditions": list(
                execution_boundary.get("preconditions") or []
            ),
            "validation_commands": list(
                execution_boundary.get("validation_commands") or []
            ),
            "merge_fate": execution_boundary.get("merge_fate") or "",
        }
    )
    # This verifies both content addresses and the root canonical task
    # identity against the explicit binding.
    build_task_work_contract(projected)
    return projected


def normalize_repo_path(value: str, *, repo_root: Path | None = None) -> str:
    """Normalize a repository path without requiring that it already exists."""

    text = str(value or "").strip().replace("\\", "/")
    if not text or "\0" in text:
        return ""
    path = Path(text)
    if path.is_absolute() and repo_root is not None:
        try:
            text = path.resolve().relative_to(Path(repo_root).resolve()).as_posix()
        except (OSError, ValueError):
            return ""
    elif path.is_absolute():
        return ""
    while text.startswith("./"):
        text = text[2:]
    parts: list[str] = []
    for part in PurePosixPath(text).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return ""
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts).rstrip("/")


def _normalized_paths(values: Iterable[str], repo_root: Path | None) -> list[str]:
    return sorted({path for value in values if (path := normalize_repo_path(value, repo_root=repo_root))})


def _normalized_terms(values: Iterable[str]) -> list[str]:
    return sorted({" ".join(str(value).strip().split()) for value in values if str(value).strip()})


def _gitmodule_paths(repo_root: Path | None) -> list[str]:
    if repo_root is None:
        return []
    path = Path(repo_root) / ".gitmodules"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return _normalized_paths(
        (match.group(1).strip() for match in re.finditer(r"^\s*path\s*=\s*(.+?)\s*$", text, re.MULTILINE)),
        repo_root,
    )


def _under(path: str, parent: str) -> bool:
    return bool(path and parent and (path == parent or path.startswith(parent.rstrip("/") + "/")))


def _looks_generated(path: str) -> bool:
    parts = set(PurePosixPath(path).parts)
    name = PurePosixPath(path).name.lower()
    return bool(
        parts & {"build", "dist", "generated", "artifacts", "coverage", "playwright-report", "test-results"}
        or ".generated." in name
        or name.endswith((".min.js", ".lock", ".manifest.json"))
    )


@dataclass(frozen=True)
class ConflictSurface:
    """All predicted and observed mutation surfaces for one task."""

    task_id: str
    task_cid: str = ""
    canonical_task_key: str = ""
    semantic_identity: str = ""
    goal_id: str = ""
    acceptance_subset: list[str] = field(default_factory=list)
    effect_subset: list[str] = field(default_factory=list)
    evidence_subset: list[str] = field(default_factory=list)
    predicted_paths: list[str] = field(default_factory=list)
    predicted_symbols: list[str] = field(default_factory=list)
    context_paths: list[str] = field(default_factory=list)
    estimated_context_tokens: int = 0
    estimated_tokens: int = 0
    estimated_validation_seconds: int = 0
    resource_class: str = ""
    token_class: str = ""
    preconditions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    validation_commands: list[str] = field(default_factory=list)
    merge_fate: str = ""
    work_contract: dict[str, Any] = field(default_factory=dict)
    work_contract_id: str = ""
    task_work_contract: dict[str, Any] = field(default_factory=dict)
    task_work_contract_id: str = ""
    files: list[str] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    ast_symbols: list[str] = field(default_factory=list)
    global_ast_symbols: list[str] | None = None
    interfaces: list[str] = field(default_factory=list)
    submodules: list[str] = field(default_factory=list)
    generated_artifacts: list[str] = field(default_factory=list)
    ast_records: list[dict[str, Any]] = field(default_factory=list)
    blob_identities: list[str] = field(default_factory=list)
    allow_concurrent_with: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_cid:
            object.__setattr__(self, "task_cid", self.task_id)
        if self.global_ast_symbols is None:
            object.__setattr__(self, "global_ast_symbols", list(self.ast_symbols))
        if self.work_contract or self.task_work_contract:
            canonical = build_task_work_contract(self)
            if (
                canonical._material() != self.work_contract
                or canonical.to_dict() != self.task_work_contract
            ):
                raise ValueError(
                    "conflict surface work contract is inconsistent"
                )

    @property
    def all_paths(self) -> list[str]:
        return sorted(set(self.files) | set(self.changed_paths) | set(self.submodules) | set(self.generated_artifacts))

    @property
    def ast_blob_records(self) -> list[dict[str, Any]]:
        return list(self.ast_records)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["all_paths"] = self.all_paths
        return payload


def _python_symbols(path: Path) -> set[str]:
    """Collect qualified Python definitions from a predicted existing file."""

    try:
        record = build_python_ast_blob_record(
            path.read_text(encoding="utf-8", errors="replace")
        )
    except OSError:
        return set()
    symbols = set(record.qualified_symbols)
    symbols.update(symbol.rsplit(".", 1)[-1] for symbol in record.qualified_symbols)
    return symbols


def build_conflict_surface(
    task: Any,
    *,
    repo_root: Path | None = None,
    changed_paths: Sequence[str] | None = None,
    ast_records: Sequence[Any] | None = None,
) -> ConflictSurface:
    """Build a complete normalized conflict surface from a task-like object.

    The accepted aliases cover objective findings, todo-vector rows, proposal
    branches, and bundle payloads.  Unknown metadata is retained for audit but
    does not silently influence the coloring.
    """

    if isinstance(task, ConflictSurface):
        # Re-normalizing makes surfaces loaded from JSON as safe as live ones.
        task = task.to_dict()
    sources = _sources(task)
    root = sources[0]
    work_contract = build_task_work_contract(task)
    task_id = str(root.get("task_id") or root.get("id") or root.get("canonical_task_id") or "").strip()
    task_cid = str(
        # The content-addressed identity is authoritative.  ``task_cid`` is a
        # compatibility projection and can legitimately lag after an
        # evidence-bound task is reprojected.  Preferring that stale alias
        # here makes the ConflictSurface disagree with the already-verified
        # TaskWorkContract and blocks incremental bundle regeneration.
        root.get("canonical_task_cid")
        or root.get("task_cid")
        or next(
            (
                source.get("canonical_task_cid")
                for source in sources[1:]
                if source.get("canonical_task_cid")
            ),
            "",
        )
        or next((source.get("task_cid") for source in sources[1:] if source.get("task_cid")), "")
        or task_id
    ).strip()
    canonical_task_key = str(
        root.get("canonical_task_key")
        or next(
            (
                source.get("canonical_task_key")
                for source in sources[1:]
                if source.get("canonical_task_key")
            ),
            "",
        )
    ).strip()
    semantic_identity = str(
        root.get("canonical_semantic_identity")
        or root.get("semantic_identity")
        or next(
            (
                source.get("canonical_semantic_identity")
                or source.get("semantic_identity")
                for source in sources[1:]
                if source.get("canonical_semantic_identity")
                or source.get("semantic_identity")
            ),
            "",
        )
    ).strip()
    if not task_id:
        task_id = task_cid
    if not task_id:
        digest = sha1(json.dumps(root, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
        task_id = task_cid = f"task-{digest}"

    files = _normalized_paths(
        _field_items(
            sources,
            ("files", "predicted_files", "predicted_paths", "outputs", "requested_outputs", "affected_files"),
        ),
        repo_root,
    )
    normalized_changed_paths = _normalized_paths(
        [
            *_field_items(sources, ("changed_paths", "actual_paths", "branch_diff", "diff_paths")),
            *(changed_paths or []),
        ],
        repo_root,
    )
    declared_ast_symbols = _normalized_terms(
        _field_items(sources, ("ast_symbols", "predicted_symbols", "symbols", "ast_query"))
    )
    has_explicit_global_symbols = any("global_ast_symbols" in source for source in sources)
    global_ast_symbols = (
        _normalized_terms(_field_items(sources, ("global_ast_symbols",)))
        if has_explicit_global_symbols
        else list(declared_ast_symbols)
    )
    ast_symbols = list(declared_ast_symbols)
    external_ast_values: list[Any] = list(ast_records or ())
    task_ast_values: list[Any] = []
    for source in sources:
        for name in ("ast_records", "ast_blob_records", "python_ast_records"):
            value = source.get(name)
            if isinstance(value, Mapping):
                task_ast_values.extend(value.values())
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                task_ast_values.extend(value)
    supplied_by_path: dict[str, ASTBlobRecord] = {}
    reusable_records: dict[str, ASTBlobRecord] = {}
    available_records: dict[str, ASTBlobRecord] = {}
    relevant_paths = set(files) | set(normalized_changed_paths)
    for value in task_ast_values:
        record = coerce_ast_blob_record(value)
        if record is None:
            continue
        if isinstance(value, Mapping):
            record_path = normalize_repo_path(
                str(value.get("root_relative_path") or value.get("path") or ""),
                repo_root=repo_root,
            )
            # A task payload may carry a repository-wide objective AST
            # snapshot.  Only pathless records explicitly attached to the
            # task, or records for this surface, belong in the bounded graph
            # record.  The complete snapshot remains available as a lookup
            # cache below without leaking into the surface.
            if record_path and record_path not in relevant_paths:
                continue
        reusable_records.setdefault(record.record_id, record)
    for value in [*task_ast_values, *external_ast_values]:
        record = coerce_ast_blob_record(value)
        if record is None:
            continue
        available_records.setdefault(record.record_id, record)
        if isinstance(value, Mapping):
            record_path = normalize_repo_path(
                str(value.get("root_relative_path") or value.get("path") or ""),
                repo_root=repo_root,
            )
            if record_path:
                supplied_by_path.setdefault(record_path, record)
                if record_path in files:
                    reusable_records.setdefault(record.record_id, record)
    discovered: set[str] = set(ast_symbols)
    for record in reusable_records.values():
        discovered.update(record.qualified_symbols)
        discovered.update(
            symbol.rsplit(".", 1)[-1] for symbol in record.qualified_symbols
        )
    if repo_root is not None:
        for relative in files:
            if relative.endswith(".py"):
                record = supplied_by_path.get(relative)
                if record is None:
                    path = Path(repo_root) / relative
                    try:
                        source = path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        source = ""
                    if source:
                        source_hash = _source_sha256(source)
                        record = next(
                            (
                                candidate
                                for candidate in available_records.values()
                                if candidate.source_sha256 == source_hash
                            ),
                            None,
                        )
                        if record is None:
                            record = build_python_ast_blob_record(source)
                if record is not None:
                    reusable_records.setdefault(record.record_id, record)
                    discovered.update(record.qualified_symbols)
                    discovered.update(
                        symbol.rsplit(".", 1)[-1] for symbol in record.qualified_symbols
                    )
    ast_symbols = sorted(discovered)
    interfaces = _normalized_terms(
        _field_items(
            sources,
            (
                "interfaces",
                "provides_interfaces",
                "requires_interfaces",
                "required_interfaces",
                "interface_dependencies",
                "public_interfaces",
            ),
        )
    )
    explicit_submodules = _normalized_paths(
        _field_items(sources, ("submodules", "submodule_paths", "gitlinks")), repo_root
    )
    known_submodules = _gitmodule_paths(repo_root)
    submodules = sorted(
        set(explicit_submodules)
        | {
            module
            for module in known_submodules
            if any(_under(path, module) for path in files + normalized_changed_paths)
        }
    )
    generated = _normalized_paths(
        _field_items(
            sources,
            ("generated_artifacts", "generated_paths", "artifacts", "generated_outputs", "derived_outputs"),
        ),
        repo_root,
    )
    generated = sorted(set(generated) | {path for path in files if _looks_generated(path)})
    allowed = _normalized_terms(
        _field_items(sources, ("allow_concurrent_with", "concurrency_overrides", "allowed_concurrent_tasks"))
    )
    return ConflictSurface(
        task_id=task_id,
        task_cid=task_cid,
        canonical_task_key=canonical_task_key,
        semantic_identity=semantic_identity,
        goal_id=work_contract.goal_id,
        acceptance_subset=list(work_contract.acceptance_subset),
        effect_subset=list(work_contract.effect_subset),
        evidence_subset=list(work_contract.evidence_subset),
        predicted_paths=list(work_contract.predicted_paths),
        predicted_symbols=list(work_contract.predicted_symbols),
        context_paths=list(work_contract.context_paths),
        estimated_context_tokens=work_contract.estimated_context_tokens,
        estimated_tokens=work_contract.estimated_tokens,
        estimated_validation_seconds=(
            work_contract.estimated_validation_seconds
        ),
        resource_class=work_contract.resource_class,
        token_class=work_contract.token_class,
        preconditions=list(work_contract.preconditions),
        dependencies=list(work_contract.dependencies),
        conflicts=list(work_contract.conflicts),
        validation_commands=list(work_contract.validation_commands),
        merge_fate=work_contract.merge_fate,
        work_contract=work_contract._material(),
        work_contract_id=work_contract.work_contract_id,
        task_work_contract=work_contract.to_dict(),
        task_work_contract_id=work_contract.task_work_contract_id,
        files=files,
        changed_paths=normalized_changed_paths,
        ast_symbols=ast_symbols,
        global_ast_symbols=global_ast_symbols,
        interfaces=interfaces,
        submodules=submodules,
        generated_artifacts=generated,
        ast_records=[
            record.to_dict()
            for record in sorted(reusable_records.values(), key=lambda item: item.record_id)
        ],
        blob_identities=sorted(
            {record.blob_identity for record in reusable_records.values() if record.blob_identity}
        ),
        allow_concurrent_with=allowed,
        metadata={
            key: value
            for key, value in root.items()
            if key
            not in (
                {
                    "files", "predicted_files", "outputs", "changed_paths", "ast_symbols",
                    "global_ast_symbols", "interfaces",
                    "submodules", "generated_artifacts", "allow_concurrent_with",
                    "ast_records", "ast_blob_records", "python_ast_records", "blob_identities",
                    "acceptance_subset", "acceptance_criteria", "acceptance",
                    "effect_subset", "effects", "expected_effects",
                    "estimated_context_tokens", "context_tokens",
                    "estimated_tokens", "token_cost",
                    "estimated_validation_seconds", "validation_seconds",
                    "validation_cost", "task_work_contract", "work_contract",
                    "work_contract_id", "task_work_contract_id",
                }
                | _DERIVED_CONFLICT_METADATA_FIELDS
            )
        },
    )


def _merge_duplicate_surfaces(
    left: ConflictSurface,
    right: ConflictSurface,
) -> ConflictSurface:
    """Coalesce aliases that resolve to the same canonical task identity."""

    if left.task_cid != right.task_cid:
        raise ValueError("cannot merge conflict surfaces with different task CIDs")
    canonical_keys = {
        value for value in (left.canonical_task_key, right.canonical_task_key) if value
    }
    if len(canonical_keys) > 1:
        raise ValueError(
            "one canonical task CID cannot project multiple canonical task keys"
        )
    semantic_identities = {
        value for value in (left.semantic_identity, right.semantic_identity) if value
    }
    if len(semantic_identities) > 1:
        raise ValueError(
            "one canonical task CID cannot project multiple semantic identities"
        )
    if canonical_keys and canonical_json_bytes(
        left.task_work_contract
    ) != canonical_json_bytes(right.task_work_contract):
        raise ValueError(
            "one canonical task CID cannot project multiple task work contracts"
        )

    ordered = sorted(
        (left, right),
        key=lambda surface: (
            surface.task_id,
            json.dumps(surface.metadata, sort_keys=True, default=str),
        ),
    )
    representative = ordered[0]
    aliases = {
        left.task_id,
        right.task_id,
        *[str(value) for value in left.metadata.get("task_id_aliases", [])],
        *[str(value) for value in right.metadata.get("task_id_aliases", [])],
    }
    metadata = dict(representative.metadata)
    metadata["task_id_aliases"] = sorted(alias for alias in aliases if alias)
    return ConflictSurface(
        task_id=representative.task_id,
        task_cid=representative.task_cid,
        canonical_task_key=next(iter(canonical_keys), ""),
        semantic_identity=next(iter(semantic_identities), ""),
        goal_id=representative.goal_id,
        acceptance_subset=list(representative.acceptance_subset),
        effect_subset=list(representative.effect_subset),
        evidence_subset=list(representative.evidence_subset),
        predicted_paths=list(representative.predicted_paths),
        predicted_symbols=list(representative.predicted_symbols),
        context_paths=list(representative.context_paths),
        estimated_context_tokens=representative.estimated_context_tokens,
        estimated_tokens=representative.estimated_tokens,
        estimated_validation_seconds=(
            representative.estimated_validation_seconds
        ),
        resource_class=representative.resource_class,
        token_class=representative.token_class,
        preconditions=list(representative.preconditions),
        dependencies=list(representative.dependencies),
        conflicts=list(representative.conflicts),
        validation_commands=list(representative.validation_commands),
        merge_fate=representative.merge_fate,
        work_contract=dict(representative.work_contract),
        work_contract_id=representative.work_contract_id,
        task_work_contract=dict(representative.task_work_contract),
        task_work_contract_id=representative.task_work_contract_id,
        files=sorted(set(left.files) | set(right.files)),
        changed_paths=sorted(set(left.changed_paths) | set(right.changed_paths)),
        ast_symbols=sorted(set(left.ast_symbols) | set(right.ast_symbols)),
        global_ast_symbols=sorted(
            set(left.global_ast_symbols or []) | set(right.global_ast_symbols or [])
        ),
        interfaces=sorted(set(left.interfaces) | set(right.interfaces)),
        submodules=sorted(set(left.submodules) | set(right.submodules)),
        generated_artifacts=sorted(
            set(left.generated_artifacts) | set(right.generated_artifacts)
        ),
        ast_records=[
            record
            for _, record in sorted(
                {
                    str(record.get("record_id") or json.dumps(record, sort_keys=True)): record
                    for record in [*left.ast_records, *right.ast_records]
                }.items()
            )
        ],
        blob_identities=sorted(
            set(left.blob_identities) | set(right.blob_identities)
        ),
        allow_concurrent_with=sorted(
            set(left.allow_concurrent_with) | set(right.allow_concurrent_with)
        ),
        metadata=metadata,
    )


def _pair_key(left: str, right: str) -> str:
    return "\0".join(sorted((str(left), str(right))))


@dataclass
class ConflictWeightHistory:
    """Learned conflict weights accumulated from diffs and receipts."""

    path_weights: dict[str, float] = field(default_factory=dict)
    symbol_weights: dict[str, float] = field(default_factory=dict)
    interface_weights: dict[str, float] = field(default_factory=dict)
    submodule_weights: dict[str, float] = field(default_factory=dict)
    artifact_weights: dict[str, float] = field(default_factory=dict)
    pair_weights: dict[str, float] = field(default_factory=dict)
    observation_count: int = 0
    observed_evidence_ids: list[str] = field(default_factory=list)

    def observe_diff(self, task_cid: str, paths: Iterable[str], *, repo_root: Path | None = None) -> None:
        observed = _normalized_paths(paths, repo_root)
        evidence_id = "diff:" + hashlib.sha256(
            json.dumps(
                {"task_cid": str(task_cid), "paths": observed},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if not observed or evidence_id in self.observed_evidence_ids:
            return
        self.observed_evidence_ids.append(evidence_id)
        del self.observed_evidence_ids[:-MAX_CONFLICT_HISTORY_EVIDENCE_IDS]
        for path in observed:
            self.path_weights[path] = self.path_weights.get(path, 0.0) + 1.0
        self.observation_count += 1

    def observe_receipt(self, receipt: Mapping[str, Any], *, repo_root: Path | None = None) -> None:
        explicit_id = str(
            receipt.get("receipt_cid")
            or receipt.get("evidence_id")
            or receipt.get("receipt_id")
            or ""
        ).strip()
        evidence_id = "receipt:" + (
            explicit_id
            or hashlib.sha256(
                json.dumps(
                    dict(receipt),
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
        )
        if evidence_id in self.observed_evidence_ids:
            return
        left, right = _receipt_pair(receipt)
        severity = _receipt_severity(receipt)
        paths = _receipt_paths(receipt, repo_root=repo_root)
        symbols = _field_items(
            [receipt], ("ast_symbols", "symbols", "conflicting_symbols")
        )
        interfaces = _field_items(
            [receipt], ("interfaces", "conflicting_interfaces")
        )
        submodules = _normalized_paths(
            _field_items(
                [receipt], ("submodules", "submodule_paths", "conflicting_submodules")
            ),
            repo_root,
        )
        artifacts = _normalized_paths(
            _field_items(
                [receipt],
                (
                    "generated_artifacts",
                    "artifacts",
                    "conflicting_artifacts",
                ),
            ),
            repo_root,
        )
        if left and right and severity:
            key = _pair_key(left, right)
            self.pair_weights[key] = self.pair_weights.get(key, 0.0) + severity
        for path in paths:
            self.path_weights[path] = self.path_weights.get(path, 0.0) + max(1.0, severity)
        for symbol in symbols:
            self.symbol_weights[symbol] = self.symbol_weights.get(symbol, 0.0) + max(1.0, severity)
        for interface in interfaces:
            self.interface_weights[interface] = (
                self.interface_weights.get(interface, 0.0) + max(1.0, severity)
            )
        for submodule in submodules:
            self.submodule_weights[submodule] = (
                self.submodule_weights.get(submodule, 0.0) + max(1.0, severity)
            )
        for artifact in artifacts:
            self.artifact_weights[artifact] = (
                self.artifact_weights.get(artifact, 0.0) + max(1.0, severity)
            )
        if left or right or paths or symbols or interfaces or submodules or artifacts:
            self.observed_evidence_ids.append(evidence_id)
            del self.observed_evidence_ids[:-MAX_CONFLICT_HISTORY_EVIDENCE_IDS]
            self.observation_count += 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ConflictWeightHistory":
        source = dict(payload or {})
        kwargs: dict[str, Any] = {}
        for name in ("path_weights", "symbol_weights", "interface_weights", "submodule_weights", "artifact_weights", "pair_weights"):
            value = source.get(name)
            kwargs[name] = {str(key): float(weight) for key, weight in value.items()} if isinstance(value, Mapping) else {}
        kwargs["observation_count"] = int(source.get("observation_count") or 0)
        kwargs["observed_evidence_ids"] = sorted(
            {
                str(item)
                for item in (source.get("observed_evidence_ids") or [])
                if str(item)
            }
        )[-MAX_CONFLICT_HISTORY_EVIDENCE_IDS:]
        return cls(**kwargs)

    @classmethod
    def load(cls, path: Path) -> "ConflictWeightHistory":
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return cls()
        return cls.from_dict(payload if isinstance(payload, Mapping) else {})

    def write(self, path: Path) -> Path:
        """Atomically persist history so a killed planner cannot truncate it."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(self.to_dict(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
        return target


@dataclass(frozen=True)
class ConflictEdge:
    left_task_cid: str
    right_task_cid: str
    weight: float
    reasons: list[str]
    overlaps: dict[str, list[str]] = field(default_factory=dict)
    predicted_weight: float = 0.0
    observed_weight: float = 0.0
    explicitly_allowed: bool = False

    @property
    def left(self) -> str:
        return self.left_task_cid

    @property
    def right(self) -> str:
        return self.right_task_cid

    @property
    def blocks_concurrency(self) -> bool:
        return self.weight > 0 and not self.explicitly_allowed

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocks_concurrency"] = self.blocks_concurrency
        return payload


@dataclass(frozen=True)
class LaneAssignment:
    task_cid: str
    task_id: str
    lane: int
    color: int
    explanation: str

    @property
    def lane_color(self) -> int:
        """Compatibility name used by serialized lane planners."""

        return self.color

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["lane_color"] = self.lane_color
        return payload


@dataclass(frozen=True)
class LaneDecision:
    left_task_cid: str
    right_task_cid: str
    action: str
    explanation: str
    weight: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskConflictGraph:
    surfaces: dict[str, ConflictSurface]
    edges: list[ConflictEdge]
    assignments: list[LaneAssignment]
    decisions: list[LaneDecision]
    lanes: dict[int, list[str]]
    history: ConflictWeightHistory = field(default_factory=ConflictWeightHistory)

    @property
    def colors(self) -> dict[str, int]:
        return {assignment.task_cid: assignment.color for assignment in self.assignments}

    @property
    def canonical_lanes(self) -> tuple[tuple[str, ...], ...]:
        """Return conflict-free lanes ordered by color and canonical task CID."""

        return tuple(
            tuple(sorted(self.lanes[color]))
            for color in sorted(self.lanes)
        )

    @property
    def independent_width(self) -> int:
        """Return the largest conflict-free task population in one lane."""

        return max((len(lane) for lane in self.canonical_lanes), default=0)

    def edge_for(self, left: str, right: str) -> ConflictEdge | None:
        pair = _pair_key(left, right)
        return next(
            (edge for edge in self.edges if _pair_key(edge.left_task_cid, edge.right_task_cid) == pair), None
        )

    def conflicts_for(self, task_cid: str) -> list[ConflictEdge]:
        return [
            edge for edge in self.edges
            if edge.blocks_concurrency and task_cid in {edge.left_task_cid, edge.right_task_cid}
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ipfs_accelerate_py.agent_supervisor.core.conflict_graph@1",
            "surfaces": {key: value.to_dict() for key, value in sorted(self.surfaces.items())},
            "edges": [edge.to_dict() for edge in self.edges],
            "assignments": [assignment.to_dict() for assignment in self.assignments],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "lanes": {str(key): list(value) for key, value in sorted(self.lanes.items())},
            "canonical_lanes": [list(lane) for lane in self.canonical_lanes],
            "independent_width": self.independent_width,
            "history": self.history.to_dict(),
        }


# A concise alias used by callers that do not need the task qualifier.
ConflictGraph = TaskConflictGraph


@dataclass(frozen=True)
class ConflictWaveProjection:
    """Deterministic conflict coloring for one dependency-ready task wave."""

    dependency_wave: int
    task_cids: tuple[str, ...]
    blocking_conflict_pairs: tuple[tuple[str, str], ...]
    color_by_task_cid: Mapping[str, int]
    independent_lanes: tuple[tuple[str, ...], ...]

    @property
    def independent_width(self) -> int:
        return max((len(lane) for lane in self.independent_lanes), default=0)

    @property
    def color_count(self) -> int:
        return len(self.independent_lanes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dependency_wave": self.dependency_wave,
            "task_cids": list(self.task_cids),
            "blocking_conflict_pairs": [
                list(pair) for pair in self.blocking_conflict_pairs
            ],
            "color_by_task_cid": dict(sorted(self.color_by_task_cid.items())),
            "independent_lanes": [
                list(lane) for lane in self.independent_lanes
            ],
            "independent_width": self.independent_width,
            "color_count": self.color_count,
        }

    def matches_canonical_replay(self) -> bool:
        """Return whether every serialized field matches a fresh projection.

        Width projections are copied through objective indexes and execution
        packets, so consumers need a cheap way to distinguish canonical
        scheduler output from caller-authored lane metadata.  Replaying from
        the projection's task/pair population catches duplicate lanes and
        non-deterministic color assignments; its owner remains responsible for
        comparing that pair population with the complete conflict graph.
        """

        try:
            replayed = project_conflict_free_wave(
                self.task_cids,
                self.blocking_conflict_pairs,
                dependency_wave=self.dependency_wave,
            )
        except (TypeError, ValueError):
            return False
        return replayed.to_dict() == self.to_dict()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConflictWaveProjection":
        """Decode and validate one canonical serialized width projection."""

        projection = cls(
            dependency_wave=int(value.get("dependency_wave") or 0),
            task_cids=tuple(str(item) for item in value.get("task_cids", ())),
            blocking_conflict_pairs=tuple(
                tuple(str(item) for item in pair)
                for pair in value.get("blocking_conflict_pairs", ())
            ),
            color_by_task_cid={
                str(task_cid): int(color)
                for task_cid, color in dict(
                    value.get("color_by_task_cid") or {}
                ).items()
            },
            independent_lanes=tuple(
                tuple(str(item) for item in lane)
                for lane in value.get("independent_lanes", ())
            ),
        )
        if not projection.matches_canonical_replay():
            raise ValueError(
                "conflict wave projection does not match canonical replay"
            )
        if int(value.get("independent_width") or 0) != projection.independent_width:
            raise ValueError("conflict wave independent width does not match lanes")
        if int(value.get("color_count") or 0) != projection.color_count:
            raise ValueError("conflict wave color count does not match lanes")
        return projection


def project_conflict_free_wave(
    task_cids: Iterable[str],
    blocking_conflict_pairs: Iterable[Iterable[str]],
    *,
    dependency_wave: int = 0,
) -> ConflictWaveProjection:
    """Color one ready wave without inventing ordering between independent work.

    The highest-degree-first coloring is deliberately local to a dependency
    wave.  Orienting blocking edges by these colors lets a scheduler serialize
    true conflicts while tasks in the same lane retain their original
    critical-path width.
    """

    nodes = tuple(sorted({str(value) for value in task_cids if str(value)}))
    node_set = set(nodes)
    pairs: set[tuple[str, str]] = set()
    for raw_pair in blocking_conflict_pairs:
        values = tuple(sorted({str(value) for value in raw_pair if str(value)}))
        if len(values) != 2:
            raise ValueError("blocking conflict pairs must contain two task CIDs")
        if not set(values).issubset(node_set):
            raise ValueError(
                "blocking conflict pairs must remain inside one dependency wave"
            )
        pairs.add((values[0], values[1]))

    adjacency = {
        cid: {
            peer
            for pair in pairs
            if cid in pair
            for peer in pair
            if peer != cid
        }
        for cid in nodes
    }
    colors: dict[str, int] = {}
    for cid in sorted(nodes, key=lambda item: (-len(adjacency[item]), item)):
        unavailable = {
            colors[peer] for peer in adjacency[cid] if peer in colors
        }
        color = 0
        while color in unavailable:
            color += 1
        colors[cid] = color

    lanes = tuple(
        tuple(sorted(cid for cid, assigned in colors.items() if assigned == color))
        for color in range(max(colors.values(), default=-1) + 1)
    )
    if any(
        colors[left] == colors[right]
        for left, right in pairs
    ):
        raise RuntimeError("conflict coloring placed a blocking edge in one lane")
    return ConflictWaveProjection(
        dependency_wave=max(0, int(dependency_wave)),
        task_cids=nodes,
        blocking_conflict_pairs=tuple(sorted(pairs)),
        color_by_task_cid=dict(sorted(colors.items())),
        independent_lanes=lanes,
    )


@dataclass(frozen=True)
class SurfaceEvidenceEdge:
    """One explainable predicted-to-observed surface relationship.

    Coverage maps use these edges independently of conflict weights.  Keeping
    the original predicted and observed values is important: a directory
    prediction can cover a more specific changed path without pretending the
    two strings were an exact match.
    """

    dimension: str
    predicted: str
    observed: str
    relationship: str
    explanation: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SurfaceEvidenceComparison:
    """Deterministic comparison of planned and observed implementation work."""

    matched_paths: list[str] = field(default_factory=list)
    missing_paths: list[str] = field(default_factory=list)
    unexpected_paths: list[str] = field(default_factory=list)
    matched_symbols: list[str] = field(default_factory=list)
    missing_symbols: list[str] = field(default_factory=list)
    unexpected_symbols: list[str] = field(default_factory=list)
    matched_interfaces: list[str] = field(default_factory=list)
    missing_interfaces: list[str] = field(default_factory=list)
    unexpected_interfaces: list[str] = field(default_factory=list)
    evidence_edges: list[SurfaceEvidenceEdge] = field(default_factory=list)
    explanations: list[str] = field(default_factory=list)

    @property
    def matched(self) -> dict[str, list[str]]:
        return {
            "paths": list(self.matched_paths),
            "symbols": list(self.matched_symbols),
            "interfaces": list(self.matched_interfaces),
        }

    @property
    def missing(self) -> dict[str, list[str]]:
        return {
            "paths": list(self.missing_paths),
            "symbols": list(self.missing_symbols),
            "interfaces": list(self.missing_interfaces),
        }

    @property
    def unexpected(self) -> dict[str, list[str]]:
        return {
            "paths": list(self.unexpected_paths),
            "symbols": list(self.unexpected_symbols),
            "interfaces": list(self.unexpected_interfaces),
        }

    @property
    def predicted_count(self) -> int:
        matched_predictions = {
            (edge.dimension, edge.predicted) for edge in self.evidence_edges
        }
        return len(matched_predictions) + sum(len(values) for values in self.missing.values())

    @property
    def matched_count(self) -> int:
        return len({(edge.dimension, edge.predicted) for edge in self.evidence_edges})

    @property
    def coverage_ratio(self) -> float:
        """Return an order-independent ratio, with an empty plan fully covered."""

        return self.matched_count / self.predicted_count if self.predicted_count else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "missing": self.missing,
            "unexpected": self.unexpected,
            # Flat aliases make the record convenient for tabular/vector
            # indexes while the grouped fields remain the canonical shape.
            "matched_paths": list(self.matched_paths),
            "missing_paths": list(self.missing_paths),
            "unexpected_paths": list(self.unexpected_paths),
            "matched_symbols": list(self.matched_symbols),
            "missing_symbols": list(self.missing_symbols),
            "unexpected_symbols": list(self.unexpected_symbols),
            "matched_interfaces": list(self.matched_interfaces),
            "missing_interfaces": list(self.missing_interfaces),
            "unexpected_interfaces": list(self.unexpected_interfaces),
            "predicted_count": self.predicted_count,
            "matched_count": self.matched_count,
            "coverage_ratio": self.coverage_ratio,
            "evidence_edges": [edge.to_dict() for edge in self.evidence_edges],
            "explanations": list(self.explanations),
        }


@dataclass(frozen=True)
class SurfaceContradiction:
    """Strong evidence that a planned surface and observed evidence disagree."""

    dimension: str
    kind: str
    expected: str = ""
    observed: str = ""
    source: str = ""
    provenance_cid: str = ""
    explanation: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SurfaceContradictionReport:
    """Serializable contradiction result retaining the underlying comparison."""

    comparison: SurfaceEvidenceComparison
    contradictions: list[SurfaceContradiction] = field(default_factory=list)
    explanations: list[str] = field(default_factory=list)

    @property
    def contradicted(self) -> bool:
        return bool(self.contradictions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contradicted": self.contradicted,
            "contradictions": [item.to_dict() for item in self.contradictions],
            "explanations": list(self.explanations),
            "comparison": self.comparison.to_dict(),
        }


def _comparison_values(
    value: Any,
    *,
    observed: bool,
    repo_root: Path | None,
) -> dict[str, list[str]]:
    """Extract comparison dimensions without conflating plans with diffs."""

    if isinstance(value, ConflictSurface):
        if observed:
            paths = list(value.changed_paths)
            symbols = list(value.ast_symbols)
            interfaces = list(value.interfaces)
        else:
            paths = [*value.files, *value.submodules, *value.generated_artifacts]
            symbols = list(value.global_ast_symbols or value.ast_symbols)
            interfaces = list(value.interfaces)
        return {
            "paths": _normalized_paths(paths, repo_root),
            "symbols": _normalized_terms(symbols),
            "interfaces": _normalized_terms(interfaces),
        }

    sources = _sources(value)
    if observed:
        paths = _field_items(
            sources,
            (
                "changed_paths", "actual_paths", "observed_paths", "branch_diff", "diff_paths",
            ),
        )
        # ``files`` is the neutral spelling used by scan receipts, but on task
        # rows it commonly means a prediction.  Only use it when no
        # observation-specific path field exists.
        if not paths:
            paths = _field_items(sources, ("files",))
        symbols = _field_items(
            sources,
            (
                "changed_ast_symbols", "actual_ast_symbols", "observed_ast_symbols",
                "changed_symbols", "actual_symbols", "observed_symbols",
            ),
        )
        if not symbols:
            symbols = _field_items(sources, ("ast_symbols", "symbols"))
        interfaces = _field_items(
            sources,
            (
                "changed_interfaces", "actual_interfaces", "observed_interfaces",
            ),
        )
        if not interfaces:
            interfaces = _field_items(sources, ("interfaces", "provides_interfaces", "public_interfaces"))
    else:
        paths = _field_items(
            sources,
            (
                "files", "predicted_files", "predicted_paths", "outputs", "requested_outputs",
                "affected_files", "submodules", "submodule_paths", "gitlinks",
                "generated_artifacts", "generated_paths", "generated_outputs", "derived_outputs",
            ),
        )
        symbols = _field_items(
            sources,
            ("global_ast_symbols", "ast_symbols", "predicted_symbols", "symbols", "ast_query"),
        )
        interfaces = _field_items(
            sources,
            (
                "interfaces", "provides_interfaces", "requires_interfaces", "required_interfaces",
                "interface_dependencies", "public_interfaces",
            ),
        )
    return {
        "paths": _normalized_paths(paths, repo_root),
        "symbols": _normalized_terms(symbols),
        "interfaces": _normalized_terms(interfaces),
    }


def compare_surface_evidence(
    predicted: Any,
    observed: Any,
    *,
    repo_root: Path | None = None,
) -> SurfaceEvidenceComparison:
    """Compare predicted files/symbols/interfaces with observed evidence.

    Paths use the same containment semantics as conflict planning, so a
    predicted directory covers a changed descendant.  Symbols and interfaces
    require exact normalized names.  The returned order depends only on the
    values, never on mapping or input iteration order.
    """

    planned = _comparison_values(predicted, observed=False, repo_root=repo_root)
    actual = _comparison_values(observed, observed=True, repo_root=repo_root)
    edges: list[SurfaceEvidenceEdge] = []

    matched_paths: set[str] = set()
    covered_planned_paths: set[str] = set()
    for planned_path in planned["paths"]:
        for actual_path in actual["paths"]:
            if not (_under(planned_path, actual_path) or _under(actual_path, planned_path)):
                continue
            relationship = "exact" if planned_path == actual_path else "path_contains"
            matched_paths.add(actual_path)
            covered_planned_paths.add(planned_path)
            edges.append(
                SurfaceEvidenceEdge(
                    dimension="paths",
                    predicted=planned_path,
                    observed=actual_path,
                    relationship=relationship,
                    explanation=(
                        f"Observed path {actual_path!r} exactly matches predicted path {planned_path!r}."
                        if relationship == "exact"
                        else f"Observed path {actual_path!r} overlaps predicted path {planned_path!r} by containment."
                    ),
                )
            )

    dimension_results: dict[str, tuple[list[str], list[str], list[str]]] = {}
    for dimension in ("symbols", "interfaces"):
        matched = sorted(set(planned[dimension]) & set(actual[dimension]))
        missing = sorted(set(planned[dimension]) - set(actual[dimension]))
        unexpected = sorted(set(actual[dimension]) - set(planned[dimension]))
        dimension_results[dimension] = (matched, missing, unexpected)
        for term in matched:
            edges.append(
                SurfaceEvidenceEdge(
                    dimension=dimension,
                    predicted=term,
                    observed=term,
                    relationship="exact",
                    explanation=f"Observed {dimension[:-1]} {term!r} exactly matches the prediction.",
                )
            )

    missing_paths = sorted(set(planned["paths"]) - covered_planned_paths)
    unexpected_paths = sorted(
        path
        for path in actual["paths"]
        if not any(_under(path, planned_path) or _under(planned_path, path) for planned_path in planned["paths"])
    )
    edges.sort(key=lambda edge: (edge.dimension, edge.predicted, edge.observed, edge.relationship))

    results = {
        "paths": (sorted(matched_paths), missing_paths, unexpected_paths),
        **dimension_results,
    }
    explanations = [
        (
            f"{dimension}: {len(matched)} observed value(s) match, "
            f"{len(missing)} predicted value(s) lack evidence, and "
            f"{len(unexpected)} observed value(s) were not predicted."
        )
        for dimension, (matched, missing, unexpected) in results.items()
    ]
    return SurfaceEvidenceComparison(
        matched_paths=results["paths"][0],
        missing_paths=results["paths"][1],
        unexpected_paths=results["paths"][2],
        matched_symbols=results["symbols"][0],
        missing_symbols=results["symbols"][1],
        unexpected_symbols=results["symbols"][2],
        matched_interfaces=results["interfaces"][0],
        missing_interfaces=results["interfaces"][1],
        unexpected_interfaces=results["interfaces"][2],
        evidence_edges=edges,
        explanations=explanations,
    )


def _strong_evidence_records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, bool):
        # ``True`` is a concise assertion that the supplied observation is an
        # exhaustive inventory.  False contributes no evidence.
        return [{"coverage_complete": True, "source": "strong_evidence"}] if value else []
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def detect_surface_contradictions(
    predicted: Any,
    observed: Any | None = None,
    *,
    repo_root: Path | None = None,
    unexpected_is_contradiction: bool = False,
    missing_is_contradiction: bool = False,
    strong_evidence: Any = None,
    receipts: Any = None,
) -> SurfaceContradictionReport:
    """Promote comparison discrepancies only when policy or evidence warrants it.

    By default, missing predictions are coverage gaps and extra changed files
    are useful dynamic findings, not contradictions.  Callers may request an
    exact contract with the two boolean flags.  Strong records/receipts can
    also assert ``contradictory``/``contradiction`` or an exhaustive inventory
    (``coverage_complete``/``exhaustive``), in which case missing planned
    surfaces become contradictory.  Receipt provenance is retained verbatim.
    """

    if isinstance(predicted, SurfaceEvidenceComparison):
        if observed is not None:
            raise ValueError("observed must be omitted when predicted is already a comparison")
        comparison = predicted
    else:
        comparison = compare_surface_evidence(predicted, observed or {}, repo_root=repo_root)

    contradictions: list[SurfaceContradiction] = []

    def add(
        dimension: str,
        kind: str,
        *,
        expected: str = "",
        actual: str = "",
        source: str = "policy",
        provenance_cid: str = "",
        explanation: str,
    ) -> None:
        contradictions.append(
            SurfaceContradiction(
                dimension=dimension,
                kind=kind,
                expected=expected,
                observed=actual,
                source=source,
                provenance_cid=provenance_cid,
                explanation=explanation,
            )
        )

    if missing_is_contradiction:
        for dimension, values in comparison.missing.items():
            for value in values:
                add(
                    dimension,
                    "missing_expected_surface",
                    expected=value,
                    explanation=f"Exact-surface policy requires predicted {dimension[:-1]} {value!r}, but it was not observed.",
                )
    if unexpected_is_contradiction:
        for dimension, values in comparison.unexpected.items():
            for value in values:
                add(
                    dimension,
                    "unexpected_observed_surface",
                    actual=value,
                    explanation=f"Exact-surface policy rejects unpredicted observed {dimension[:-1]} {value!r}.",
                )

    records = [*_strong_evidence_records(strong_evidence), *_receipts(receipts)]
    records.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
    for record in records:
        provenance = str(
            record.get("provenance_cid") or record.get("receipt_cid") or record.get("cid") or ""
        ).strip()
        source = str(record.get("source") or record.get("producer_id") or "evidence").strip()
        exhaustive = record.get("coverage_complete") is True or record.get("exhaustive") is True
        if exhaustive:
            for dimension, values in comparison.missing.items():
                for value in values:
                    add(
                        dimension,
                        "missing_from_exhaustive_evidence",
                        expected=value,
                        source=source,
                        provenance_cid=provenance,
                        explanation=(
                            f"Exhaustive evidence {provenance or source!r} does not contain predicted "
                            f"{dimension[:-1]} {value!r}."
                        ),
                    )
        exact_surface = (
            record.get("exact_surface") is True
            or record.get("unexpected_is_contradiction") is True
            or record.get("reject_unexpected") is True
        )
        if exact_surface:
            for dimension, values in comparison.unexpected.items():
                for value in values:
                    add(
                        dimension,
                        "unexpected_in_exact_evidence",
                        actual=value,
                        source=source,
                        provenance_cid=provenance,
                        explanation=(
                            f"Exact-surface evidence {provenance or source!r} rejects unpredicted "
                            f"observed {dimension[:-1]} {value!r}."
                        ),
                    )

        reason = str(record.get("contradiction") or record.get("reason") or "").strip()
        status = str(record.get("status") or record.get("outcome") or "").strip().lower()
        explicit = record.get("contradictory") is True or bool(record.get("contradiction"))
        explicit = explicit or status in {
            "contradicted", "contradictory", "conflict", "conflicted", "failed", "failure", "invalid", "rejected",
        }
        specific: list[tuple[str, str]] = []
        for dimension in ("paths", "symbols", "interfaces"):
            singular = dimension[:-1]
            values = _items(
                record.get(f"contradicted_{dimension}")
                or record.get(f"conflicting_{dimension}")
                or record.get(f"invalid_{dimension}")
                or record.get(f"contradicted_{singular}")
            )
            specific.extend((dimension, value) for value in values)
        if explicit and specific:
            for dimension, value in sorted(set(specific)):
                add(
                    dimension,
                    "explicit_evidence_contradiction",
                    actual=value,
                    source=source,
                    provenance_cid=provenance,
                    explanation=reason or f"Evidence explicitly contradicts {dimension[:-1]} {value!r}.",
                )
        elif explicit:
            add(
                "evidence",
                "explicit_evidence_contradiction",
                source=source,
                provenance_cid=provenance,
                explanation=reason or f"Evidence status {status!r} explicitly reports a contradiction.",
            )

    # Multiple strong records may report the same fact.  Collapse them without
    # losing different provenance, and make serialization independent of input
    # order.
    unique = {
        (
            item.dimension, item.kind, item.expected, item.observed,
            item.source, item.provenance_cid, item.explanation,
        ): item
        for item in contradictions
    }
    ordered = [unique[key] for key in sorted(unique)]
    explanations = (
        [item.explanation for item in ordered]
        if ordered
        else [
            "No contradiction was established; missing predictions remain coverage gaps and unexpected observations remain dynamic findings."
        ]
    )
    return SurfaceContradictionReport(
        comparison=comparison,
        contradictions=ordered,
        explanations=explanations,
    )


def _path_overlaps(left: Iterable[str], right: Iterable[str]) -> list[str]:
    overlaps: set[str] = set()
    for left_path in left:
        for right_path in right:
            if _under(left_path, right_path) or _under(right_path, left_path):
                # Retain the more specific path; it is the actionable surface.
                overlaps.add(left_path if len(left_path) >= len(right_path) else right_path)
    return sorted(overlaps)


def _history_path_weight(paths: Iterable[str], history: ConflictWeightHistory) -> float:
    total = 0.0
    for path in paths:
        total += sum(weight for known, weight in history.path_weights.items() if _under(path, known) or _under(known, path))
    return total


def _is_allowed(left: ConflictSurface, right: ConflictSurface, overrides: set[str]) -> bool:
    candidates = {left.task_cid, left.task_id}
    others = {right.task_cid, right.task_id}
    if any(_pair_key(left_key, right_key) in overrides for left_key in candidates for right_key in others):
        return True
    return bool(candidates & set(right.allow_concurrent_with) or others & set(left.allow_concurrent_with))


def _override_pairs(value: Any) -> set[str]:
    pairs: set[str] = set()
    if isinstance(value, Mapping):
        iterable: Iterable[Any] = value.items()
    else:
        iterable = value or []
    for item in iterable:
        left = right = ""
        enabled = True
        if isinstance(item, Mapping):
            left = str(item.get("left") or item.get("left_task_cid") or item.get("task") or "")
            right = str(item.get("right") or item.get("right_task_cid") or item.get("with") or "")
            enabled = bool(item.get("allowed", item.get("allow", True)))
        elif isinstance(item, tuple) and len(item) == 2:
            if isinstance(item[1], bool):
                # Mapping.items() with {"A\0B": True} or {(A, B): True}.
                key = item[0]
                if isinstance(key, (tuple, list, set, frozenset)) and len(key) == 2:
                    left, right = map(str, key)
                else:
                    parts = re.split(r"\s*(?:<->|::|,|\||\x00)\s*", str(key), maxsplit=1)
                    if len(parts) == 2:
                        left, right = parts
                enabled = item[1]
            else:
                left, right = str(item[0]), str(item[1])
        elif isinstance(item, (list, set, frozenset)) and len(item) == 2:
            left, right = map(str, item)
        elif isinstance(item, str):
            parts = re.split(r"\s*(?:<->|::|,|\|)\s*", item, maxsplit=1)
            if len(parts) == 2:
                left, right = parts
        if left and right and enabled:
            pairs.add(_pair_key(left, right))
    return pairs


def _receipt_pair(receipt: Mapping[str, Any]) -> tuple[str, str]:
    left = str(
        receipt.get("left_task_cid") or receipt.get("source_task_cid") or receipt.get("task_cid")
        or receipt.get("left_task_id") or ""
    ).strip()
    right = str(
        receipt.get("right_task_cid") or receipt.get("target_task_cid") or receipt.get("other_task_cid")
        or receipt.get("right_task_id") or ""
    ).strip()
    pair = receipt.get("task_cids") or receipt.get("tasks")
    if (not left or not right) and isinstance(pair, Sequence) and not isinstance(pair, str) and len(pair) >= 2:
        left, right = str(pair[0]), str(pair[1])
    return left, right


def _receipt_severity(receipt: Mapping[str, Any]) -> float:
    explicit = receipt.get("weight") or receipt.get("conflict_weight") or receipt.get("severity_weight")
    if explicit is not None:
        try:
            base = max(0.0, float(explicit))
            try:
                return base * max(1, int(receipt.get("count") or 1))
            except (TypeError, ValueError):
                return base
        except (TypeError, ValueError):
            pass
    status_values = {
        re.sub(r"[\s-]+", "_", str(receipt.get(key) or "").strip().lower())
        for key in ("status", "result", "outcome")
    }
    diagnostic = " ".join(
        str(receipt.get(key) or "").lower()
        for key in ("reason", "stderr")
    )
    conflict_diagnostic = any(
        marker in diagnostic
        for marker in (
            "merge conflict",
            "content conflict",
            "conflicting path",
            "conflicting file",
            "conflict in ",
            "automatic merge failed",
        )
    )
    if (
        bool(receipt.get("merge_conflict") or receipt.get("conflicted"))
        or bool(status_values & CONFLICT_RECEIPT_STATUSES)
        or conflict_diagnostic
    ):
        try:
            return 5.0 * max(1, int(receipt.get("count") or 1))
        except (TypeError, ValueError):
            return 5.0
    return 0.0


def _receipt_paths(receipt: Mapping[str, Any], *, repo_root: Path | None) -> list[str]:
    return _normalized_paths(
        _field_items(
            [receipt],
            ("paths", "conflicting_paths", "changed_paths", "files", "overlapping_paths", "generated_artifacts"),
        ),
        repo_root,
    )


def _receipts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        # A single receipt has characteristic fields; otherwise values are a receipt map.
        if set(value) & {
            "left_task_cid", "source_task_cid", "task_cids", "status", "outcome",
            "conflicting_paths", "contradictory", "contradiction", "receipt_cid",
            "coverage_complete", "exhaustive", "exact_surface", "reject_unexpected",
        }:
            return [dict(value)]
        receipts: list[dict[str, Any]] = []
        for key, item in value.items():
            if not isinstance(item, Mapping):
                continue
            receipt = dict(item)
            if not any(_receipt_pair(receipt)):
                parts = re.split(r"\s*(?:<->|::|,|\||\x00)\s*", str(key), maxsplit=1)
                if len(parts) == 2:
                    receipt["task_cids"] = parts
            receipts.append(receipt)
        return receipts
    return [dict(item) for item in (value or []) if isinstance(item, Mapping)]


def _branch_diff_map(value: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if isinstance(value, Mapping):
        for key, paths in value.items():
            if isinstance(paths, Mapping):
                paths = paths.get("changed_paths") or paths.get("paths") or paths.get("files") or []
            result[str(key)] = _items(paths)
        return result
    for record in value or []:
        if not isinstance(record, Mapping):
            continue
        task = str(record.get("task_cid") or record.get("task_id") or "")
        if task:
            result.setdefault(task, []).extend(
                _items(record.get("changed_paths") or record.get("paths") or record.get("files"))
            )
    return result


def _make_edge(
    left: ConflictSurface,
    right: ConflictSurface,
    *,
    history: ConflictWeightHistory,
    allowed: bool,
    weights: Mapping[str, float],
) -> ConflictEdge | None:
    overlaps: dict[str, list[str]] = {}
    predicted = 0.0
    observed = 0.0

    # All path categories are compared cross-category; a generated artifact
    # declared by one task still conflicts with the same path declared as a file
    # by another task.
    path_groups = {
        "files": (left.files, right.files),
        "changed_paths": (left.changed_paths, right.changed_paths),
        "submodules": (left.submodules, right.submodules),
        "generated_artifacts": (left.generated_artifacts, right.generated_artifacts),
    }
    all_path_overlap = _path_overlaps(left.all_paths, right.all_paths)
    if all_path_overlap:
        overlaps["paths"] = all_path_overlap
    for surface, (left_values, right_values) in path_groups.items():
        shared = _path_overlaps(left_values, right_values)
        if shared:
            overlaps[surface] = shared
            contribution = float(weights[surface]) * len(shared)
            if surface == "changed_paths":
                observed += contribution
            else:
                predicted += contribution
    # Cross-category path overlaps not counted above remain a real conflict.
    counted_paths = {item for key, values in overlaps.items() if key != "paths" for item in values}
    cross_paths = sorted(set(all_path_overlap) - counted_paths)
    if cross_paths:
        overlaps["cross_surface_paths"] = cross_paths
        observed_cross_paths = {
            path
            for path in cross_paths
            if any(
                _under(path, changed) or _under(changed, path)
                for changed in (*left.changed_paths, *right.changed_paths)
            )
        }
        observed += float(weights["changed_paths"]) * len(observed_cross_paths)
        predicted += float(weights["files"]) * (
            len(cross_paths) - len(observed_cross_paths)
        )

    # Auto-discovered AST terms are local to the Python files from which they
    # were parsed.  A shared non-code path (for example a plan document or a
    # discovery directory) must not make unrelated modules conflict merely
    # because both define common names such as ``__post_init__`` or ``_digest``.
    # Explicit global_ast_symbols remain available for genuine cross-file
    # semantic conflicts.
    python_path_overlap = [
        path
        for path in all_path_overlap
        if PurePosixPath(path).suffix.lower() in {".py", ".pyi", ".pyw"}
    ]
    ast_symbol_values = (
        (left.ast_symbols, right.ast_symbols)
        if python_path_overlap
        else (left.global_ast_symbols or [], right.global_ast_symbols or [])
    )
    for surface, left_values, right_values in (
        ("ast_symbols", *ast_symbol_values),
        ("interfaces", left.interfaces, right.interfaces),
    ):
        shared = sorted(set(left_values) & set(right_values))
        if shared:
            overlaps[surface] = shared
            predicted += float(weights[surface]) * len(shared)

    history_paths = all_path_overlap or _path_overlaps(left.files + left.generated_artifacts, right.files + right.generated_artifacts)
    path_history = _history_path_weight(history_paths, history)
    symbol_history = sum(history.symbol_weights.get(symbol, 0.0) for symbol in overlaps.get("ast_symbols", []))
    interface_history = sum(history.interface_weights.get(name, 0.0) for name in overlaps.get("interfaces", []))
    submodule_history = sum(
        history.submodule_weights.get(path, 0.0)
        for path in overlaps.get("submodules", [])
    )
    artifact_history = sum(
        history.artifact_weights.get(path, 0.0)
        for path in overlaps.get("generated_artifacts", [])
    )
    pair_history = history.pair_weights.get(_pair_key(left.task_cid, right.task_cid), 0.0)
    observed += (
        path_history
        + symbol_history
        + interface_history
        + submodule_history
        + artifact_history
        + pair_history
    )
    if pair_history:
        overlaps["historical_task_pair"] = [f"{left.task_cid}<->{right.task_cid}"]

    weight = predicted + observed
    if weight <= 0:
        return None
    reason_names = {
        "files": "file",
        "changed_paths": "changed_path",
        "ast_symbols": "ast_symbol",
        "interfaces": "interface",
        "submodules": "submodule",
        "generated_artifacts": "generated_artifact",
        "cross_surface_paths": "file",
        "historical_task_pair": "conflict_receipt",
        "paths": "path",
    }
    reasons: list[str] = []
    for surface in sorted(overlaps):
        code = reason_names.get(surface, surface)
        if code not in reasons:
            reasons.append(code)
    # Keep concrete evidence alongside stable reason codes.  Codes make policy
    # filtering reliable; details make receipts and manifests self-explanatory.
    reasons.extend(f"{surface}: {', '.join(values)}" for surface, values in sorted(overlaps.items()))
    if observed:
        reasons.append(f"observed conflict evidence: +{observed:g}")
    if allowed:
        reasons.append("explicit concurrency override")
    return ConflictEdge(
        left_task_cid=left.task_cid,
        right_task_cid=right.task_cid,
        weight=weight,
        reasons=reasons,
        overlaps=overlaps,
        predicted_weight=predicted,
        observed_weight=observed,
        explicitly_allowed=allowed,
    )


def _color(
    surfaces: Mapping[str, ConflictSurface], edges: Sequence[ConflictEdge], *, max_lanes: int | None
) -> tuple[list[LaneAssignment], dict[int, list[str]]]:
    adjacency: dict[str, set[str]] = {task_cid: set() for task_cid in surfaces}
    weighted_degree: dict[str, float] = {task_cid: 0.0 for task_cid in surfaces}
    for edge in edges:
        if not edge.blocks_concurrency:
            continue
        adjacency[edge.left_task_cid].add(edge.right_task_cid)
        adjacency[edge.right_task_cid].add(edge.left_task_cid)
        weighted_degree[edge.left_task_cid] += edge.weight
        weighted_degree[edge.right_task_cid] += edge.weight

    # Deterministic DSATUR: most constrained first, then weighted degree and CID.
    colors: dict[str, int] = {}
    capacity = int(max_lanes) if max_lanes is not None and int(max_lanes) > 0 else None
    while len(colors) < len(surfaces):
        uncolored = [node for node in surfaces if node not in colors]
        node = min(
            uncolored,
            key=lambda item: (
                -len({colors[neighbor] for neighbor in adjacency[item] if neighbor in colors}),
                -len(adjacency[item]),
                -weighted_degree[item],
                item,
            ),
        )
        forbidden = {colors[neighbor] for neighbor in adjacency[node] if neighbor in colors}
        color = 0
        while color in forbidden or (capacity is not None and sum(value == color for value in colors.values()) >= capacity):
            color += 1
        colors[node] = color

    lanes: dict[int, list[str]] = {}
    for task_cid, color in sorted(colors.items(), key=lambda item: (item[1], item[0])):
        lanes.setdefault(color, []).append(task_cid)
    assignments = [
        LaneAssignment(
            task_cid=task_cid,
            task_id=surfaces[task_cid].task_id,
            lane=color,
            color=color,
            explanation=(
                f"color {color} avoids {len(adjacency[task_cid])} blocking conflict(s)"
                if adjacency[task_cid]
                else f"color {color} co-locates this task with non-overlapping work"
            ),
        )
        for task_cid, color in sorted(colors.items(), key=lambda item: (item[1], item[0]))
    ]
    return assignments, lanes


def _explain_decisions(
    surfaces: Mapping[str, ConflictSurface],
    edges: Sequence[ConflictEdge],
    assignments: Sequence[LaneAssignment],
) -> list[LaneDecision]:
    """Explain every pair against the supplied (possibly recolored) plan."""

    task_cids = sorted(surfaces)
    colors = {assignment.task_cid: assignment.color for assignment in assignments}
    edge_by_pair = {_pair_key(edge.left_task_cid, edge.right_task_cid): edge for edge in edges}
    decisions: list[LaneDecision] = []
    for index, left in enumerate(task_cids):
        for right in task_cids[index + 1 :]:
            edge = edge_by_pair.get(_pair_key(left, right))
            if edge is not None and edge.explicitly_allowed:
                action = "concurrent_override"
                explanation = (
                    f"Explicit override permits concurrency despite weight {edge.weight:g}: "
                    + "; ".join(edge.reasons)
                )
            elif edge is not None:
                action = "separate"
                explanation = (
                    f"Separated into colors {colors[left]} and {colors[right]} for conflict weight {edge.weight:g}: "
                    + "; ".join(edge.reasons)
                )
            elif colors[left] == colors[right]:
                action = "co_locate"
                explanation = f"Co-located in color {colors[left]} because no conflict surface overlaps."
            else:
                action = "separate"
                explanation = (
                    f"No conflict surface overlaps; colors {colors[left]} and {colors[right]} differ only because "
                    "of capacity or their conflicts with other tasks."
                )
            decisions.append(
                LaneDecision(
                    left_task_cid=left,
                    right_task_cid=right,
                    action=action,
                    explanation=explanation,
                    weight=edge.weight if edge else 0.0,
                    reasons=list(edge.reasons) if edge else (["lane_capacity"] if colors[left] != colors[right] else []),
                )
            )
    return decisions


def materialize_task_conflict_graph(
    tasks: Sequence[Any],
    *,
    repo_root: Path | None = None,
    ast_records: Sequence[Any] | None = None,
    branch_diffs: Any = None,
    conflict_receipts: Any = None,
    concurrency_overrides: Any = None,
    history: ConflictWeightHistory | Mapping[str, Any] | None = None,
    max_lanes: int | None = None,
    surface_weights: Mapping[str, float] | None = None,
) -> TaskConflictGraph:
    """Materialize conflict edges, deterministic colors, and pair decisions.

    ``max_lanes`` is treated as concurrent capacity per color, never as
    permission to place conflicting work together.  Additional colors are
    created when either conflicts or capacity require them.
    """

    learned = history if isinstance(history, ConflictWeightHistory) else ConflictWeightHistory.from_dict(history)
    diffs = _branch_diff_map(branch_diffs)
    surfaces: dict[str, ConflictSurface] = {}
    observed_paths_by_cid: dict[str, set[str]] = {}
    for task in tasks:
        surface = build_conflict_surface(
            task,
            repo_root=repo_root,
            ast_records=ast_records,
        )
        observed_paths = diffs.get(surface.task_cid, []) + diffs.get(surface.task_id, [])
        if observed_paths:
            normalized = _normalized_paths([*surface.changed_paths, *observed_paths], repo_root)
            surface = ConflictSurface(**{**asdict(surface), "changed_paths": normalized})
            observed_paths_by_cid.setdefault(surface.task_cid, set()).update(
                _normalized_paths(observed_paths, repo_root)
            )
        if surface.task_cid in surfaces:
            surface = _merge_duplicate_surfaces(surfaces[surface.task_cid], surface)
        surfaces[surface.task_cid] = surface

    for task_cid, observed_paths in observed_paths_by_cid.items():
        learned.observe_diff(task_cid, observed_paths, repo_root=repo_root)

    receipts = _receipts(conflict_receipts)
    identity_aliases = {
        identity: surface.task_cid
        for surface in surfaces.values()
        for identity in {
            surface.task_id,
            surface.task_cid,
            *[str(value) for value in surface.metadata.get("task_id_aliases", [])],
        }
    }
    for receipt in receipts:
        left, right = _receipt_pair(receipt)
        normalized_receipt = dict(receipt)
        if left and right:
            normalized_receipt["task_cids"] = [
                identity_aliases.get(left, left),
                identity_aliases.get(right, right),
            ]
            # Ensure the canonical pair wins over any alias-specific fields.
            for key in (
                "left_task_cid", "source_task_cid", "task_cid", "left_task_id",
                "right_task_cid", "target_task_cid", "other_task_cid", "right_task_id",
                "tasks",
            ):
                normalized_receipt.pop(key, None)
        learned.observe_receipt(normalized_receipt, repo_root=repo_root)
    overrides = _override_pairs(concurrency_overrides)
    weights = {**DEFAULT_SURFACE_WEIGHTS, **dict(surface_weights or {})}

    task_cids = sorted(surfaces)
    edges: list[ConflictEdge] = []
    for index, left_cid in enumerate(task_cids):
        for right_cid in task_cids[index + 1 :]:
            left, right = surfaces[left_cid], surfaces[right_cid]
            edge = _make_edge(
                left,
                right,
                history=learned,
                allowed=_is_allowed(left, right, overrides),
                weights=weights,
            )
            if edge is not None:
                edges.append(edge)
    edges.sort(key=lambda edge: (-edge.weight, edge.left_task_cid, edge.right_task_cid))
    assignments, lanes = _color(surfaces, edges, max_lanes=max_lanes)
    decisions = _explain_decisions(surfaces, edges, assignments)
    return TaskConflictGraph(
        surfaces=surfaces,
        edges=edges,
        assignments=assignments,
        decisions=decisions,
        lanes=lanes,
        history=learned,
    )


def build_conflict_graph(tasks: Sequence[Any], **kwargs: Any) -> TaskConflictGraph:
    """Compatibility alias for :func:`materialize_task_conflict_graph`."""

    graph = materialize_task_conflict_graph(tasks, **kwargs)
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(getattr(graph, "graph_id", "") or "task-conflict-graph")
        mirror_work_record(
            catalog_kind="knowledge_graph",
            record_kind="task_conflict_graph",
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return graph


def color_conflict_graph(
    graph: TaskConflictGraph | Sequence[Any], *, max_lanes: int | None = None, **kwargs: Any
) -> TaskConflictGraph:
    """Color an existing graph or materialize and color task-like inputs."""

    if not isinstance(graph, TaskConflictGraph):
        return materialize_task_conflict_graph(graph, max_lanes=max_lanes, **kwargs)
    assignments, lanes = _color(graph.surfaces, graph.edges, max_lanes=max_lanes)
    return TaskConflictGraph(
        surfaces=graph.surfaces,
        edges=graph.edges,
        assignments=assignments,
        decisions=_explain_decisions(graph.surfaces, graph.edges, assignments),
        lanes=lanes,
        history=graph.history,
    )


def update_conflict_weights(
    history: ConflictWeightHistory,
    *,
    branch_diffs: Any = None,
    conflict_receipts: Any = None,
    repo_root: Path | None = None,
) -> ConflictWeightHistory:
    """Apply observations to a reusable history object and return it."""

    for task_cid, paths in _branch_diff_map(branch_diffs).items():
        history.observe_diff(task_cid, paths, repo_root=repo_root)
    for receipt in _receipts(conflict_receipts):
        history.observe_receipt(receipt, repo_root=repo_root)
    return history


LGSWF_CONFLICT_SCOPES = (
    "predicted_path",
    "exact_symbol",
    "interface",
    "schema",
    "state",
    "effect",
    "generated",
    "fixture",
    "taskboard",
    "database",
    "merge",
    "external",
    "exclusive_resource",
    "opaque_file",
    "opaque_repository",
)


class SemanticConflictError(ValueError):
    """LGSWF conflict-graph extension rejected an unsafe admission."""


def _mirror_semantic_conflict(decision: dict[str, Any]) -> dict[str, Any]:
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str(decision.get("scope") or decision.get("reason") or "semantic-conflict")
        mirror_work_record(
            catalog_kind="knowledge_graph",
            record_kind="semantic_conflict",
            record_ref=record_ref,
            subject_kind="record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return decision


def evaluate_semantic_conflict(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    """Extend the existing graph with typed semantic conflict scopes.

    Shared reads do not serialize. Same-symbol / interface / schema / generated
    / effect / exclusive-resource writers conflict. Opaque writes fall back to
    file or repository serialization with an explicit reason.
    """

    left_mode = str(left.get("mode") or "write")
    right_mode = str(right.get("mode") or "write")
    if left_mode == "read" and right_mode == "read":
        return _mirror_semantic_conflict({
            "conflict": False,
            "reason": "compatible-readers",
            "scope": "shared-read",
        })
    if left_mode == "read" or right_mode == "read":
        if left.get("exclusive_resource") and left.get("exclusive_resource") == right.get(
            "exclusive_resource"
        ):
            return _mirror_semantic_conflict({
                "conflict": True,
                "reason": "exclusive-resource",
                "scope": "exclusive_resource",
            })
        return _mirror_semantic_conflict({
            "conflict": False,
            "reason": "compatible-reader-writer",
            "scope": "shared-read",
        })
    for key in ("symbol", "interface", "schema", "generated", "effect", "exclusive_resource"):
        if left.get(key) and left.get(key) == right.get(key):
            return _mirror_semantic_conflict({
                "conflict": True,
                "reason": f"same-{key}",
                "scope": "exact_symbol" if key == "symbol" else key,
            })
    if left.get("opaque") or right.get("opaque"):
        scope = "opaque_file" if left.get("path") or right.get("path") else "opaque_repository"
        return _mirror_semantic_conflict({
            "conflict": True,
            "reason": "opaque-conservative-fallback",
            "scope": scope,
        })
    if left.get("path") and left.get("path") == right.get("path"):
        return _mirror_semantic_conflict({"conflict": True, "reason": "same-path", "scope": "predicted_path"})
    return _mirror_semantic_conflict({"conflict": False, "reason": "disjoint-writes", "scope": "none"})


def admit_conflict_free_frontier(tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    admitted: list[str] = []
    rejected: list[dict[str, str]] = []
    chosen: list[Mapping[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("task_id") or "")
        hit = None
        for other in chosen:
            decision = evaluate_semantic_conflict(task, other)
            if decision["conflict"]:
                hit = {
                    "task_id": task_id,
                    "conflicts_with": str(other.get("task_id") or ""),
                    "reason": str(decision["reason"]),
                }
                break
        if hit:
            rejected.append(hit)
        else:
            chosen.append(task)
            admitted.append(task_id)
    frontier = {
        "admitted": tuple(admitted),
        "rejected": tuple(rejected),
        "deterministic": True,
    }
    try:
        from ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index import (
            mirror_work_record,
        )

        record_ref = str((admitted[0] if admitted else "") or "conflict-free-frontier")
        mirror_work_record(
            catalog_kind="metadata",
            record_kind="conflict_free_frontier",
            record_ref=record_ref,
            subject_kind="task_id" if admitted else "record_cid",
            subject_ref=record_ref,
        )
    except Exception:
        pass
    return frontier


__all__ = [
    "AST_BLOB_RECORD_SCHEMA_VERSION",
    "ASTBlobRecord",
    "ConflictEdge",
    "ConflictGraph",
    "ConflictSurface",
    "ConflictWaveProjection",
    "ConflictWeightHistory",
    "LaneAssignment",
    "LaneDecision",
    "SurfaceContradiction",
    "SurfaceContradictionReport",
    "SurfaceEvidenceComparison",
    "SurfaceEvidenceEdge",
    "TaskConflictGraph",
    "TASK_PLANNING_WORK_CONTRACT_SCHEMA",
    "TaskWorkContract",
    "build_conflict_graph",
    "build_conflict_surface",
    "build_task_work_contract",
    "build_python_ast_blob_record",
    "color_conflict_graph",
    "compare_surface_evidence",
    "detect_surface_contradictions",
    "coerce_ast_blob_record",
    "index_ast_blob_records",
    "materialize_task_conflict_graph",
    "normalize_repo_path",
    "project_conflict_free_wave",
    "update_conflict_weights",
    "LGSWF_CONFLICT_SCOPES",
    "SemanticConflictError",
    "admit_conflict_free_frontier",
    "evaluate_semantic_conflict",
]
