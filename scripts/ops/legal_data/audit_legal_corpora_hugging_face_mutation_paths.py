"""Audit protected Hugging Face mutation paths without touching the Hub.

The audit is deliberately callsite based. Importing a guard is not authority,
constructing ``HfApi`` is not a write, and a protected-repository literal in an
unrelated function does not taint the rest of a module. For each actual Hub
write, the analyser follows simple aliases, repository-value aliases, local
function calls, and nested callbacks.

Accepted protection is either an actual callback supplied to
``authorize_and_mutate_canonical`` or a same-target/same-method
``require_unprotected_or_runtime`` call that dominates API construction and
the write. A caller-provided ``runtime_authorized`` value is never accepted.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.huggingface.protected_repo_guard import (
    CANONICAL_RUNTIME,
    PROTECTED_REPOS,
    PROTECTED_WRITE_METHODS,
)

TASK_ID = "LCR-084"
GOAL_ID = "LCR-G146"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "audit_legal_corpora_hugging_face_mutation_paths.py"
SCHEMA = "ipfs_datasets_py/legal-corpora-hugging-face-mutation-path-audit@2"
REPORT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/hugging_face_mutation_path_audit.json"
)
SCAN_ROOTS = (
    Path("ipfs_datasets_py/huggingface"),
    Path("ipfs_datasets_py/processors/legal_data"),
    Path("ipfs_datasets_py/processors/legal_scrapers"),
    Path("ipfs_datasets_py/processors/domains/patent"),
    Path("scripts/ops/legal_data"),
    Path("scripts/repair"),
    Path("scripts/ops/security_ir"),
)
SKIP_DIR_NAMES = {"__pycache__", ".git", "node_modules", "workspace", "external"}
_REPOSITORY_KEYWORDS = (
    "repo_id",
    "repository_id",
    "dataset_id",
    "target_repo_id",
)
_REPOSITORY_BEARING_NAMES = frozenset(
    {
        *_REPOSITORY_KEYWORDS,
        "dataset_repo_id",
        "hf_dataset_id",
    }
)
_CANONICAL_FUNCTION = "authorize_and_mutate_canonical"
_LEGACY_GUARD_FUNCTION = "require_unprotected_or_runtime"
_PROTECTED_PROBE_FUNCTION = "is_protected_repo"
_API_METHOD_RESOLVERS = {"_require_api_method", "_require_method"}
_READ_ONLY_METHODS = {
    "repo_info",
    "list_repo_files",
    "list_models",
    "list_datasets",
    "get_paths_info",
    "whoami",
}


class MutationPathAuditError(RuntimeError):
    pass


def _iter_python_files(root: Path, *, repository_root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.is_dir():
        return files
    for path in root.rglob("*.py"):
        try:
            rel_parts = path.relative_to(repository_root).parts
        except ValueError:
            rel_parts = path.parts
        if any(part in SKIP_DIR_NAMES for part in rel_parts[:-1]):
            continue
        files.append(path)
    return sorted(files)


def _source(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001  # pragma: no cover
        return type(node).__name__


def _root_key(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _root_key(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Subscript):
        return f"{_root_key(node.value)}[{_source(node.slice)}]"
    return _source(node)


def _literal_text(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_repository_bearing_name(name: str) -> bool:
    """Return whether an unknown value may designate a Hub repository.

    Public helpers frequently accept ``repo_id`` (or a prefixed spelling such
    as ``target_repo_id``) and are independently callable even when every
    in-tree caller currently supplies an unprotected literal.  Treat those
    unresolved inputs conservatively; this is target-flow inference, not
    module-wide taint from an unrelated protected literal.
    """

    normalized = str(name or "").strip().casefold()
    return bool(
        normalized in _REPOSITORY_BEARING_NAMES
        or normalized.endswith(("_repo_id", "_repository_id"))
    )


@dataclass(frozen=True)
class _Guard:
    roots: frozenset[str]
    protected: frozenset[str]
    potential_protected: bool
    method: str
    line: int
    runtime_override: str


@dataclass(frozen=True)
class _Value:
    protected: frozenset[str] = frozenset()
    roots: frozenset[str] = frozenset()
    methods: frozenset[str] = frozenset()
    symbols: frozenset[str] = frozenset()
    potential_protected: bool = False
    api_bound: bool = False
    api_guards: tuple[_Guard, ...] = ()

    @staticmethod
    def merge(*values: _Value) -> _Value:
        present = [value for value in values if value is not None]
        if not present:
            return _Value()
        api_values = [value for value in present if value.api_bound]
        guards = list(api_values[0].api_guards) if api_values else []
        # An alias can have more than one possible API/method origin after a
        # branch. Only guards common to every origin dominate construction.
        for value in api_values[1:]:
            guards = [guard for guard in guards if guard in value.api_guards]
        return _Value(
            protected=frozenset().union(*(value.protected for value in present)),
            roots=frozenset().union(*(value.roots for value in present)),
            methods=frozenset().union(*(value.methods for value in present)),
            symbols=frozenset().union(*(value.symbols for value in present)),
            potential_protected=any(value.potential_protected for value in present),
            api_bound=any(value.api_bound for value in present),
            api_guards=tuple(guards),
        )


@dataclass
class _FunctionDescriptor:
    identifier: str
    display_name: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    closure_env: dict[str, _Value]
    closure_guards: tuple[_Guard, ...] = ()
    nested: bool = False


@dataclass
class _FunctionContext:
    descriptor: _FunctionDescriptor
    incoming: dict[str, _Value] = field(default_factory=dict)
    canonical: bool = False
    hard_rejected: bool = False
    unprotected_roots: frozenset[str] = frozenset()


def _specific_roots(roots: Iterable[str]) -> frozenset[str]:
    """Keep expression roots that identify the value, not merely its owner.

    ``self.repository_id`` is evaluated from both ``self`` and
    ``self.repository_id``.  Treating the broad ``self`` root as repository
    identity would let a guard for one attribute authorize a different
    attribute on the same object.
    """

    values = {str(root) for root in roots if str(root)}
    return frozenset(
        root
        for root in values
        if not any(
            other != root
            and other.startswith((f"{root}.", f"{root}["))
            for other in values
        )
    )


def _guard_matches(guard: _Guard, repo: _Value, method: str) -> bool:
    if guard.method != method:
        return False
    if _specific_roots(guard.roots) & _specific_roots(repo.roots):
        return True
    # Two unresolved, repository-shaped values are not evidence that they are
    # the same target.  A legacy guard is accepted only for a shared value-flow
    # root or an identical protected literal.
    return bool(guard.protected & repo.protected)


def _dedupe_guards(guards: Iterable[_Guard]) -> tuple[_Guard, ...]:
    result: list[_Guard] = []
    for guard in guards:
        if guard not in result:
            result.append(guard)
    return tuple(result)


def _merge_branch_values(*values: _Value) -> _Value:
    """Merge possible values while retaining only definitely bound symbols."""

    merged = _Value.merge(*values)
    common_symbols = set(values[0].symbols) if values else set()
    for value in values[1:]:
        common_symbols.intersection_update(value.symbols)
    return _Value(
        protected=merged.protected,
        roots=merged.roots,
        methods=merged.methods,
        symbols=frozenset(common_symbols),
        potential_protected=merged.potential_protected,
        api_bound=merged.api_bound,
        api_guards=merged.api_guards,
    )


def _target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(item) for item in target.elts))
    return set()


def _target_roots(target: ast.AST) -> set[str]:
    if isinstance(target, (ast.Name, ast.Attribute, ast.Subscript)):
        return {_root_key(target)}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_roots(item) for item in target.elts))
    return set()


def _block_definitely_terminates(statements: Sequence[ast.stmt]) -> bool:
    """Recognize the small fail-closed forms used before mutation branches."""

    if not statements:
        return False
    final = statements[-1]
    if isinstance(final, (ast.Return, ast.Raise)):
        return True
    if isinstance(final, ast.If):
        return bool(final.orelse) and _block_definitely_terminates(
            final.body
        ) and _block_definitely_terminates(final.orelse)
    return False


def _simple_condition_selector(node: ast.AST) -> tuple[str, bool] | None:
    """Return ``(selector, positive)`` for a simple truthiness condition."""

    if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
        return _root_key(node), True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not) and isinstance(
        node.operand, (ast.Name, ast.Attribute, ast.Subscript)
    ):
        return _root_key(node.operand), False
    return None


class _FileAnalyzer:
    """Small, conservative, flow-sensitive analyser for one Python module."""

    def __init__(
        self,
        *,
        path: Path,
        relpath: str,
        source_text: str,
        tree: ast.Module,
        protected_repos: set[str],
        required_runtime: str,
    ) -> None:
        self.path = path
        self.relpath = relpath
        self.source_text = source_text
        self.tree = tree
        self.protected_repos = protected_repos
        self.required_runtime = required_runtime
        self.base_env: dict[str, _Value] = {}
        self.functions: dict[str, _FunctionDescriptor] = {}
        self.name_to_functions: dict[str, list[str]] = {}
        self.queue: list[_FunctionContext] = []
        self.seen_contexts: set[tuple[Any, ...]] = set()
        self.raw_writes: list[dict[str, Any]] = []
        self.hard_rejections: list[dict[str, Any]] = []
        self.module_descriptor: _FunctionDescriptor | None = None
        self._index_module()

    def _protected_literal(self, text: str) -> frozenset[str]:
        normalized = str(text).strip().casefold()
        return frozenset({normalized}) if normalized in self.protected_repos else frozenset()

    def _import_value(self, original: str) -> _Value:
        symbol = original.rsplit(".", 1)[-1]
        methods = frozenset({symbol}) if symbol in PROTECTED_WRITE_METHODS else frozenset()
        return _Value(methods=methods, symbols=frozenset({symbol, original}))

    def _bind_import(self, stmt: ast.Import | ast.ImportFrom, env: dict[str, _Value]) -> None:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                env[local] = self._import_value(alias.name)
            return
        module = stmt.module or ""
        for alias in stmt.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            original = f"{module}.{alias.name}" if module else alias.name
            env[local] = self._import_value(original)

    def _index_module(self) -> None:
        for stmt in self.tree.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                self._bind_import(stmt, self.base_env)
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
                value = self._eval_static_value(stmt.value, self.base_env)
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets:
                    self._bind_target(target, value, self.base_env)

        for stmt in self.tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._register_function(stmt, stmt.name, nested=False)
            elif isinstance(stmt, ast.ClassDef):
                for member in stmt.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._register_function(member, f"{stmt.name}.{member.name}", nested=False)

        for name, identifiers in self.name_to_functions.items():
            if len(identifiers) == 1:
                self.base_env[name] = _Value(
                    symbols=frozenset({f"function:{identifiers[0]}"}),
                    roots=frozenset({name}),
                )
        module_node = ast.FunctionDef(
            name="<module>",
            args=ast.arguments(
                posonlyargs=[],
                args=[],
                kwonlyargs=[],
                kw_defaults=[],
                defaults=[],
            ),
            body=[
                stmt
                for stmt in self.tree.body
                if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ],
            decorator_list=[],
        )
        self.module_descriptor = _FunctionDescriptor(
            identifier="<module>@1",
            display_name="<module>",
            node=module_node,
            closure_env=dict(self.base_env),
            nested=False,
        )

    def _register_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        display_name: str,
        *,
        nested: bool,
        closure_env: Mapping[str, _Value] | None = None,
        closure_guards: Sequence[_Guard] = (),
        owner: str = "",
    ) -> _FunctionDescriptor:
        identifier = (
            f"{owner}.<locals>.{node.name}@{node.lineno}"
            if nested
            else f"{display_name}@{node.lineno}"
        )
        descriptor = _FunctionDescriptor(
            identifier=identifier,
            display_name=display_name,
            node=node,
            closure_env=dict(closure_env or self.base_env),
            closure_guards=tuple(closure_guards),
            nested=nested,
        )
        self.functions[identifier] = descriptor
        self.name_to_functions.setdefault(node.name, []).append(identifier)
        return descriptor

    def _bind_target(self, target: ast.AST, value: _Value, env: dict[str, _Value]) -> None:
        if isinstance(target, ast.Name):
            env[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self._bind_target(item, _Value(), env)

    def _eval_static_value(self, node: ast.AST, env: Mapping[str, _Value]) -> _Value:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                protected = self._protected_literal(node.value)
                roots = (
                    frozenset({f"literal:{node.value.strip().casefold()}"})
                    if protected
                    else frozenset()
                )
                methods = (
                    frozenset({node.value})
                    if node.value in PROTECTED_WRITE_METHODS
                    else frozenset()
                )
                return _Value(protected=protected, roots=roots, methods=methods)
            return _Value()
        if isinstance(node, ast.Name):
            return env.get(node.id, _Value(roots=frozenset({node.id})))
        if isinstance(node, ast.Attribute):
            base = self._eval_static_value(node.value, env)
            methods = (
                frozenset({node.attr})
                if node.attr in PROTECTED_WRITE_METHODS
                else frozenset()
            )
            attribute_symbols = {node.attr}
            attribute_symbols.update(
                f"{symbol}.{node.attr}" for symbol in base.symbols
            )
            return _Value.merge(
                base,
                _Value(
                    roots=frozenset({_root_key(node)}),
                    methods=methods,
                    symbols=frozenset(attribute_symbols),
                    potential_protected=(
                        base.potential_protected
                        or _is_repository_bearing_name(node.attr)
                    ),
                ),
            )
        if isinstance(node, ast.Subscript):
            base = self._eval_static_value(node.value, env)
            return _Value.merge(base, _Value(roots=frozenset({_root_key(node)})))
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return _Value.merge(*(self._eval_static_value(item, env) for item in node.elts))
        if isinstance(node, ast.Dict):
            return _Value.merge(
                *(self._eval_static_value(item, env) for item in node.values if item is not None)
            )
        if isinstance(node, (ast.BoolOp, ast.BinOp)):
            values = node.values if isinstance(node, ast.BoolOp) else (node.left, node.right)
            return _Value.merge(*(self._eval_static_value(item, env) for item in values))
        if isinstance(node, ast.IfExp):
            return _Value.merge(
                self._eval_static_value(node.body, env),
                self._eval_static_value(node.orelse, env),
            )
        if isinstance(node, ast.UnaryOp):
            return self._eval_static_value(node.operand, env)
        if isinstance(node, ast.Call):
            symbol = self._call_symbol(node.func, env)
            if symbol in {"str", "Path", "PurePath"} and node.args:
                return self._eval_static_value(node.args[0], env)
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                "strip", "casefold", "lower", "upper", "resolve", "expanduser"
            }:
                return self._eval_static_value(node.func.value, env)
        return _Value()

    def _call_symbol(self, func: ast.AST, env: Mapping[str, _Value]) -> str:
        if isinstance(func, ast.Name):
            value = env.get(func.id)
            if value and value.symbols:
                for candidate in (
                    _CANONICAL_FUNCTION,
                    _LEGACY_GUARD_FUNCTION,
                    _PROTECTED_PROBE_FUNCTION,
                    "HfApi",
                    "partial",
                    "getattr",
                    "str",
                    "Path",
                    "PurePath",
                ):
                    if candidate in value.symbols:
                        return candidate
                function_symbol = next(
                    (item for item in value.symbols if item.startswith("function:")), None
                )
                if function_symbol:
                    return function_symbol
                if value.methods:
                    return min(value.methods)
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return ""

    def _is_special_call(
        self,
        func: ast.AST,
        env: Mapping[str, _Value],
        expected: str,
    ) -> bool:
        """Require import provenance for authority-bearing helper names."""

        if isinstance(func, ast.Name):
            value = env.get(func.id)
            if value is None or expected not in value.symbols:
                return False
            provenance = value.symbols
        elif isinstance(func, ast.Attribute) and func.attr == expected:
            provenance = self._eval_static_value(func.value, env).symbols
        else:
            return False
        if expected == _CANONICAL_FUNCTION:
            runtime_name = self.required_runtime.rsplit(".", 1)[-1]
            return any(
                self.required_runtime in item
                or runtime_name in item
                or "legal_corpora_publication_runtime" in item
                for item in provenance
            )
        if expected in {_LEGACY_GUARD_FUNCTION, _PROTECTED_PROBE_FUNCTION}:
            return any("protected_repo_guard" in item for item in provenance)
        return expected in provenance

    def _parameter_defaults(self, descriptor: _FunctionDescriptor) -> dict[str, _Value]:
        node = descriptor.node
        positional = list(node.args.posonlyargs) + list(node.args.args)
        result = {
            arg.arg: _Value(
                roots=frozenset({arg.arg}),
                potential_protected=_is_repository_bearing_name(arg.arg),
            )
            for arg in positional
        }
        result.update(
            {
                arg.arg: _Value(
                    roots=frozenset({arg.arg}),
                    potential_protected=_is_repository_bearing_name(arg.arg),
                )
                for arg in node.args.kwonlyargs
            }
        )
        if node.args.vararg:
            result[node.args.vararg.arg] = _Value(
                roots=frozenset({node.args.vararg.arg}),
                potential_protected=_is_repository_bearing_name(
                    node.args.vararg.arg
                ),
            )
        if node.args.kwarg:
            result[node.args.kwarg.arg] = _Value(
                roots=frozenset({node.args.kwarg.arg}),
                potential_protected=_is_repository_bearing_name(
                    node.args.kwarg.arg
                ),
            )
        offset = len(positional) - len(node.args.defaults)
        for arg, default in zip(positional[offset:], node.args.defaults):
            default_value = self._eval_static_value(default, descriptor.closure_env)
            result[arg.arg] = _Value(
                protected=default_value.protected,
                roots=frozenset({arg.arg}),
                methods=default_value.methods,
                symbols=default_value.symbols,
                potential_protected=(
                    default_value.potential_protected
                    or _is_repository_bearing_name(arg.arg)
                ),
                api_bound=default_value.api_bound,
                api_guards=default_value.api_guards,
            )
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if default is not None:
                default_value = self._eval_static_value(default, descriptor.closure_env)
                result[arg.arg] = _Value(
                    protected=default_value.protected,
                    roots=frozenset({arg.arg}),
                    methods=default_value.methods,
                    symbols=default_value.symbols,
                    potential_protected=(
                        default_value.potential_protected
                        or _is_repository_bearing_name(arg.arg)
                    ),
                    api_bound=default_value.api_bound,
                    api_guards=default_value.api_guards,
                )
        return result

    def _context_key(self, context: _FunctionContext) -> tuple[Any, ...]:
        incoming = tuple(
            sorted(
                (
                    name,
                    tuple(sorted(value.protected)),
                    tuple(sorted(value.roots)),
                    value.potential_protected,
                )
                for name, value in context.incoming.items()
            )
        )
        return (
            context.descriptor.identifier,
            incoming,
            context.canonical,
            context.hard_rejected,
            tuple(sorted(context.unprotected_roots)),
        )

    def enqueue(
        self,
        descriptor: _FunctionDescriptor,
        *,
        incoming: Mapping[str, _Value] | None = None,
        canonical: bool = False,
        hard_rejected: bool = False,
        unprotected_roots: Iterable[str] = (),
    ) -> None:
        context = _FunctionContext(
            descriptor=descriptor,
            incoming=dict(incoming or {}),
            canonical=canonical,
            hard_rejected=hard_rejected,
            unprotected_roots=frozenset(unprotected_roots),
        )
        key = self._context_key(context)
        if key not in self.seen_contexts:
            self.seen_contexts.add(key)
            self.queue.append(context)

    def analyze(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        for descriptor in list(self.functions.values()):
            if not descriptor.nested:
                self.enqueue(descriptor)
        if self.module_descriptor is not None:
            self.enqueue(self.module_descriptor)
        while self.queue:
            _FunctionRun(self, self.queue.pop(0)).run()
        return self.raw_writes, self.hard_rejections


class _FunctionRun:
    def __init__(self, owner: _FileAnalyzer, context: _FunctionContext) -> None:
        self.owner = owner
        self.context = context
        self.descriptor = context.descriptor
        self.node = self.descriptor.node
        self.env = dict(self.descriptor.closure_env)
        for name, value in owner._parameter_defaults(self.descriptor).items():
            self.env[name] = context.incoming.get(name, value)
        self.active_guards: tuple[_Guard, ...] = self.descriptor.closure_guards
        self.protected_probe_roots: set[str] = set()
        self.protected_probe_values: list[_Value] = []
        self.conditional_guard_history: dict[str, tuple[_Guard, ...]] = {}
        self.conditional_guard_dependencies: dict[str, set[str]] = {}
        self.unprotected_when_false: dict[str, frozenset[str]] = {}
        self.refresh_hard_rejection = self._detect_refresh_hard_rejection()

    def _detect_refresh_hard_rejection(self) -> dict[str, Any] | None:
        assignments: dict[str, str] = {}
        for index, stmt in enumerate(self.node.body):
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        assignments[target.id] = _source(stmt.value)
            if not isinstance(stmt, ast.If):
                continue
            test_names = {item.id for item in ast.walk(stmt.test) if isinstance(item, ast.Name)}
            rejected_name = next(
                (
                    name
                    for name in test_names
                    if "publish" in assignments.get(name, "")
                    and "create_repo" in assignments.get(name, "")
                ),
                None,
            )
            if rejected_name is None or not stmt.body:
                continue
            if not isinstance(stmt.body[0], (ast.Return, ast.Raise)):
                continue
            prefix = ast.Module(body=self.node.body[:index], type_ignores=[])
            if any(
                isinstance(item, ast.Call)
                and (
                    self.owner._call_symbol(item.func, self.env) == "HfApi"
                    or self.owner._call_symbol(item.func, self.env) in PROTECTED_WRITE_METHODS
                )
                for item in ast.walk(prefix)
            ):
                continue
            return {
                "path": self.owner.relpath,
                "function": self.descriptor.display_name,
                "line": stmt.lineno,
                "selector": rejected_name,
                "selector_expression": assignments[rejected_name],
                "mechanism": "refresh_hard_rejection",
            }
        return None

    def run(self) -> None:
        if self.refresh_hard_rejection is not None:
            self.owner.hard_rejections.append(self.refresh_hard_rejection)
        self._analyze_block(
            self.node.body,
            self.env,
            self.active_guards,
            self.context.unprotected_roots,
        )

    def _invalidate_conditional_guards(self, targets: Iterable[ast.AST]) -> None:
        names = set().union(*(_target_names(target) for target in targets))
        if not names:
            return
        for condition, dependencies in list(self.conditional_guard_dependencies.items()):
            if names & dependencies:
                self.conditional_guard_dependencies.pop(condition, None)
                self.conditional_guard_history.pop(condition, None)

    def _invalidate_unprotected_implications(
        self,
        targets: Iterable[ast.AST],
    ) -> None:
        roots = set().union(*(_target_roots(target) for target in targets))
        if not roots:
            return
        for selector, repo_roots in list(self.unprotected_when_false.items()):
            if selector in roots or _specific_roots(repo_roots) & roots:
                self.unprotected_when_false.pop(selector, None)

    def _fail_closed_unprotected_implication(
        self,
        stmt: ast.If,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> tuple[str, frozenset[str]] | None:
        """Prove ``not selector -> repository is unprotected`` after a gate.

        Only the exact, fail-closed shape is accepted::

            if is_protected_repo(repository) and not selector:
                raise ...

        The proof is later applied solely to the false branch of the same
        unchanged selector.  It is not mutation authority and cannot make the
        selector's true branch safe.
        """

        if not _block_definitely_terminates(stmt.body):
            return None
        if not isinstance(stmt.test, ast.BoolOp) or not isinstance(
            stmt.test.op, ast.And
        ):
            return None
        if len(stmt.test.values) != 2:
            return None
        probe_calls = [
            value
            for value in stmt.test.values
            if isinstance(value, ast.Call)
            and self.owner._is_special_call(
                value.func,
                env,
                _PROTECTED_PROBE_FUNCTION,
            )
        ]
        negated = [
            value
            for value in stmt.test.values
            if isinstance(value, ast.UnaryOp)
            and isinstance(value.op, ast.Not)
            and isinstance(value.operand, (ast.Name, ast.Attribute, ast.Subscript))
        ]
        if len(probe_calls) != 1 or len(negated) != 1:
            return None
        repo, _ = self._repo_value(probe_calls[0], env, active_guards)
        repo_roots = _specific_roots(repo.roots)
        if not repo_roots:
            return None
        return _root_key(negated[0].operand), repo_roots

    def _repo_value(
        self,
        call: ast.Call,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> tuple[_Value, ast.AST | None]:
        for keyword in call.keywords:
            if keyword.arg in _REPOSITORY_KEYWORDS:
                return self._eval_value(keyword.value, env, active_guards), keyword.value
        if call.args:
            return self._eval_value(call.args[0], env, active_guards), call.args[0]
        return _Value(), None

    def _eval_value(
        self,
        node: ast.AST,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> _Value:
        if isinstance(node, ast.Call):
            symbol = self.owner._call_symbol(node.func, env)
            if symbol == "HfApi":
                return _Value(
                    symbols=frozenset({"HfApi-instance"}),
                    api_bound=True,
                    api_guards=tuple(active_guards),
                )
            if symbol in _API_METHOD_RESOLVERS:
                method = _literal_text(node.args[0]) if node.args else None
                if method in PROTECTED_WRITE_METHODS:
                    return _Value(
                        methods=frozenset({method}),
                        api_bound=True,
                        api_guards=tuple(active_guards),
                    )
            if symbol == "getattr" and len(node.args) >= 2:
                method = _literal_text(node.args[1])
                if method is None:
                    method_value = self._eval_value(node.args[1], env, active_guards)
                    if len(method_value.methods) == 1:
                        method = next(iter(method_value.methods))
                if method in PROTECTED_WRITE_METHODS:
                    receiver = self._eval_value(node.args[0], env, active_guards)
                    return _Value.merge(receiver, _Value(methods=frozenset({method})))
            if symbol == "partial" and node.args:
                bound = self._eval_value(node.args[0], env, active_guards)
                repo_values = [
                    self._eval_value(keyword.value, env, active_guards)
                    for keyword in node.keywords
                    if keyword.arg in _REPOSITORY_KEYWORDS
                ]
                return _Value.merge(bound, *repo_values)
            if symbol in {"str", "Path", "PurePath"} and node.args:
                return self._eval_value(node.args[0], env, active_guards)
            if isinstance(node.func, ast.Attribute) and node.func.attr in {
                "strip", "casefold", "lower", "upper", "resolve", "expanduser"
            }:
                return self._eval_value(node.func.value, env, active_guards)
        value = self.owner._eval_static_value(node, env)
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            return _Value.merge(value, self._eval_value(node.value, env, active_guards))
        if isinstance(node, (ast.BoolOp, ast.BinOp)):
            values = node.values if isinstance(node, ast.BoolOp) else (node.left, node.right)
            return _Value.merge(*(self._eval_value(item, env, active_guards) for item in values))
        if isinstance(node, ast.IfExp):
            return _Value.merge(
                self._eval_value(node.body, env, active_guards),
                self._eval_value(node.orelse, env, active_guards),
            )
        return value

    def _guard_from_call(
        self,
        call: ast.Call,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> _Guard | None:
        if not self.owner._is_special_call(
            call.func,
            env,
            _LEGACY_GUARD_FUNCTION,
        ):
            return None
        repo, _ = self._repo_value(call, env, active_guards)
        method = _literal_text(
            next((kw.value for kw in call.keywords if kw.arg == "method"), None)
        )
        if method not in PROTECTED_WRITE_METHODS:
            return None
        override_node = next(
            (kw.value for kw in call.keywords if kw.arg == "runtime_authorized"), None
        )
        if override_node is None:
            override = "absent"
        elif isinstance(override_node, ast.Constant) and override_node.value is False:
            override = "literal_false"
        else:
            return None
        return _Guard(
            roots=repo.roots,
            protected=repo.protected,
            potential_protected=repo.potential_protected,
            method=method,
            line=call.lineno,
            runtime_override=override,
        )

    def _target_is_protected(
        self,
        repo: _Value,
        unprotected_roots: Iterable[str],
    ) -> bool:
        repo_roots = _specific_roots(repo.roots)
        proven_unprotected = _specific_roots(unprotected_roots)
        if repo_roots and repo_roots.issubset(proven_unprotected):
            return False
        if repo.protected or repo.potential_protected:
            return True
        if _specific_roots(self.protected_probe_roots) & repo_roots:
            return True
        return any(
            bool(
                _specific_roots(value.roots) & repo_roots
                or value.protected & repo.protected
            )
            for value in self.protected_probe_values
        )

    def _record_write(
        self,
        call: ast.Call,
        *,
        method: str,
        callee_value: _Value,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
        unprotected_roots: Iterable[str],
        canonical_override: bool = False,
        hard_rejected_override: bool = False,
    ) -> None:
        repo, repo_node = self._repo_value(call, env, active_guards)
        if repo_node is None and callee_value.methods:
            # A statically resolved partial may bind repo_id before the final
            # method invocation.
            repo = _Value(
                protected=callee_value.protected,
                roots=callee_value.roots,
                potential_protected=callee_value.potential_protected,
            )
        canonical = self.context.canonical or canonical_override
        # A structurally delegated canonical callback is itself the protected
        # mutation boundary. Its repository may be closure-bound and only
        # proven by the runtime request in the caller, so retain it as a
        # protected path even when the local expression is otherwise generic.
        protected_target = self._target_is_protected(
            repo,
            unprotected_roots,
        ) or canonical
        matching = [guard for guard in active_guards if _guard_matches(guard, repo, method)]
        construction_safe = (
            not callee_value.api_bound
            or any(_guard_matches(guard, repo, method) for guard in callee_value.api_guards)
        )
        hard_rejected = (
            self.context.hard_rejected
            or hard_rejected_override
        )
        if not protected_target:
            protection = "not_a_proven_protected_target"
        elif canonical:
            protection = "canonical_runtime"
        elif hard_rejected:
            protection = "refresh_hard_rejection"
        elif matching and construction_safe:
            protection = "legacy_dominating_guard"
        else:
            protection = "unprotected"
        reason = ""
        if protected_target and protection == "unprotected":
            reason = (
                "guard does not dominate API/write-method construction"
                if matching and not construction_safe
                else "no same-target, same-method dominating legacy guard or canonical callback"
            )
        self.owner.raw_writes.append(
            {
                "path": self.owner.relpath,
                "function": self.descriptor.display_name,
                "line": int(getattr(call, "lineno", 0)),
                "column": int(getattr(call, "col_offset", 0)),
                "write_method": method,
                "call_expression": _source(call),
                "repo_expression": _source(repo_node),
                "repo_roots": sorted(repo.roots),
                "protected_repos": sorted(repo.protected),
                "potential_protected_target": bool(repo.potential_protected),
                "protected_target": protected_target,
                "protection": protection,
                "guard_lines": sorted(guard.line for guard in matching),
                "api_or_method_constructed_after_guard": construction_safe,
                "canonical_callback": canonical,
                "reason": reason,
            }
        )

    def _bind_call_arguments(
        self,
        descriptor: _FunctionDescriptor,
        call: ast.Call,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
    ) -> dict[str, _Value]:
        positional = list(descriptor.node.args.posonlyargs) + list(descriptor.node.args.args)
        incoming: dict[str, _Value] = {}
        for argument, parameter in zip(call.args, positional):
            incoming[parameter.arg] = self._eval_value(argument, env, active_guards)
        valid_names = {arg.arg for arg in positional + list(descriptor.node.args.kwonlyargs)}
        for keyword in call.keywords:
            if keyword.arg and keyword.arg in valid_names:
                incoming[keyword.arg] = self._eval_value(keyword.value, env, active_guards)
        return incoming

    def _resolve_function(self, value: _Value) -> _FunctionDescriptor | None:
        identifiers = [
            symbol.split(":", 1)[1]
            for symbol in value.symbols
            if symbol.startswith("function:")
        ]
        return self.owner.functions.get(identifiers[0]) if len(identifiers) == 1 else None

    def _enqueue_callback(
        self,
        callback: ast.AST,
        *,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
        unprotected_roots: Iterable[str],
    ) -> None:
        if isinstance(callback, ast.Lambda):
            self._visit_expr(
                callback.body,
                env,
                active_guards,
                unprotected_roots,
                canonical_override=True,
            )
            return
        if (
            isinstance(callback, ast.Call)
            and self.owner._call_symbol(callback.func, env) == "partial"
            and callback.args
        ):
            target = callback.args[0]
            descriptor = self._resolve_function(self._eval_value(target, env, active_guards))
            if descriptor is not None:
                synthetic = ast.Call(
                    func=target,
                    args=list(callback.args[1:]),
                    keywords=list(callback.keywords),
                )
                ast.copy_location(synthetic, callback)
                incoming = self._bind_call_arguments(descriptor, synthetic, env, active_guards)
                self.owner.enqueue(
                    descriptor,
                    incoming=incoming,
                    canonical=True,
                    unprotected_roots=unprotected_roots,
                )
            return
        descriptor = self._resolve_function(self._eval_value(callback, env, active_guards))
        if descriptor is not None:
            self.owner.enqueue(
                descriptor,
                canonical=True,
                unprotected_roots=unprotected_roots,
            )

    def _visit_expr(
        self,
        node: ast.AST | None,
        env: Mapping[str, _Value],
        active_guards: Sequence[_Guard],
        unprotected_roots: Iterable[str] = (),
        *,
        canonical_override: bool = False,
        hard_rejected_override: bool = False,
    ) -> None:
        if node is None:
            return
        if not isinstance(node, ast.Call):
            for child in ast.iter_child_nodes(node):
                if not isinstance(child, ast.Lambda):
                    self._visit_expr(
                        child,
                        env,
                        active_guards,
                        unprotected_roots,
                        canonical_override=canonical_override,
                        hard_rejected_override=hard_rejected_override,
                    )
            return

        symbol = self.owner._call_symbol(node.func, env)
        callee_value = self._eval_value(node.func, env, active_guards)

        if self.owner._is_special_call(
            node.func,
            env,
            _PROTECTED_PROBE_FUNCTION,
        ):
            repo, _ = self._repo_value(node, env, active_guards)
            self.protected_probe_roots.update(repo.roots)
            self.protected_probe_values.append(repo)

        if self.owner._is_special_call(
            node.func,
            env,
            _CANONICAL_FUNCTION,
        ):
            callback = next(
                (kw.value for kw in node.keywords if kw.arg in {"upload_callback", "callback"}),
                node.args[1] if len(node.args) > 1 else None,
            )
            for index, argument in enumerate(node.args):
                if index != 1:
                    self._visit_expr(
                        argument,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
            for keyword in node.keywords:
                if keyword.value is not callback:
                    self._visit_expr(
                        keyword.value,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
            if callback is not None:
                self._enqueue_callback(
                    callback,
                    env=env,
                    active_guards=active_guards,
                    unprotected_roots=unprotected_roots,
                )
            return

        methods = set(callee_value.methods)
        if symbol in PROTECTED_WRITE_METHODS:
            methods.add(symbol)
        if isinstance(node.func, ast.Attribute) and node.func.attr in PROTECTED_WRITE_METHODS:
            methods.add(node.func.attr)
        for method in sorted(methods):
            self._record_write(
                node,
                method=method,
                callee_value=callee_value,
                env=env,
                active_guards=active_guards,
                unprotected_roots=unprotected_roots,
                canonical_override=canonical_override,
                hard_rejected_override=hard_rejected_override,
            )

        descriptor = self._resolve_function(callee_value)
        if descriptor is not None:
            incoming = self._bind_call_arguments(descriptor, node, env, active_guards)
            self.owner.enqueue(
                descriptor,
                incoming=incoming,
                canonical=self.context.canonical or canonical_override,
                hard_rejected=(
                    self.context.hard_rejected
                    or hard_rejected_override
                ),
                unprotected_roots=unprotected_roots,
            )

        self._visit_expr(
            node.func,
            env,
            active_guards,
            unprotected_roots,
            canonical_override=canonical_override,
            hard_rejected_override=hard_rejected_override,
        )
        for argument in node.args:
            self._visit_expr(
                argument,
                env,
                active_guards,
                unprotected_roots,
                canonical_override=canonical_override,
                hard_rejected_override=hard_rejected_override,
            )
        for keyword in node.keywords:
            self._visit_expr(
                keyword.value,
                env,
                active_guards,
                unprotected_roots,
                canonical_override=canonical_override,
                hard_rejected_override=hard_rejected_override,
            )

    def _analyze_block(
        self,
        statements: Sequence[ast.stmt],
        initial_env: Mapping[str, _Value],
        initial_guards: Sequence[_Guard],
        initial_unprotected_roots: Iterable[str] = (),
    ) -> tuple[dict[str, _Value], tuple[_Guard, ...]]:
        env = dict(initial_env)
        active_guards = tuple(initial_guards)
        unprotected_roots = frozenset(initial_unprotected_roots)
        for stmt in statements:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                self.owner._bind_import(stmt, env)
                continue
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                descriptor = self.owner._register_function(
                    stmt,
                    f"{self.descriptor.display_name}.<locals>.{stmt.name}",
                    nested=True,
                    closure_env=env,
                    closure_guards=active_guards,
                    owner=self.descriptor.identifier,
                )
                env[stmt.name] = _Value(
                    symbols=frozenset({f"function:{descriptor.identifier}"}),
                    roots=frozenset({stmt.name}),
                )
                continue
            if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                self._visit_expr(
                    stmt.value,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                value = self._eval_value(stmt.value, env, active_guards)
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                self._invalidate_conditional_guards(targets)
                self._invalidate_unprotected_implications(targets)
                for target in targets:
                    self.owner._bind_target(target, value, env)
                continue
            if isinstance(stmt, ast.AugAssign):
                self._visit_expr(
                    stmt.value,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                value = _Value.merge(
                    self._eval_value(stmt.target, env, active_guards),
                    self._eval_value(stmt.value, env, active_guards),
                )
                self._invalidate_conditional_guards([stmt.target])
                self._invalidate_unprotected_implications([stmt.target])
                self.owner._bind_target(stmt.target, value, env)
                continue
            if isinstance(stmt, ast.Expr):
                if isinstance(stmt.value, ast.Call):
                    guard = self._guard_from_call(stmt.value, env, active_guards)
                    if guard is not None:
                        active_guards = _dedupe_guards((*active_guards, guard))
                        continue
                self._visit_expr(
                    stmt.value,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                continue
            if isinstance(stmt, ast.If):
                self._visit_expr(
                    stmt.test,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                implication = self._fail_closed_unprotected_implication(
                    stmt,
                    env,
                    active_guards,
                )
                condition = ast.dump(stmt.test, include_attributes=False)
                remembered = self.conditional_guard_history.get(condition, ())
                branch_start = _dedupe_guards((*active_guards, *remembered))
                body_unprotected = set(unprotected_roots)
                else_unprotected = set(unprotected_roots)
                selector = _simple_condition_selector(stmt.test)
                if selector is not None:
                    selector_name, positive = selector
                    false_proof = self.unprotected_when_false.get(
                        selector_name,
                        frozenset(),
                    )
                    if positive:
                        else_unprotected.update(false_proof)
                    else:
                        body_unprotected.update(false_proof)
                implications_before = dict(self.unprotected_when_false)
                body_env, body_guards = self._analyze_block(
                    stmt.body,
                    env,
                    branch_start,
                    body_unprotected,
                )
                implications_body = dict(self.unprotected_when_false)
                self.unprotected_when_false = dict(implications_before)
                else_env, _ = self._analyze_block(
                    stmt.orelse,
                    env,
                    active_guards,
                    else_unprotected,
                )
                implications_else = dict(self.unprotected_when_false)
                self.unprotected_when_false = {
                    name: roots
                    for name, roots in implications_body.items()
                    if implications_else.get(name) == roots
                }
                if implication is not None:
                    proof_selector, proof_roots = implication
                    self.unprotected_when_false[proof_selector] = proof_roots
                for name in set(env) | set(body_env) | set(else_env):
                    before = env.get(name, _Value())
                    body_value = body_env.get(name, before)
                    else_value = else_env.get(name, before)
                    if body_value != before or else_value != before:
                        env[name] = _merge_branch_values(body_value, else_value)
                newly_established = tuple(
                    guard for guard in body_guards if guard not in branch_start
                )
                if newly_established:
                    self.conditional_guard_history[condition] = _dedupe_guards(
                        (*remembered, *newly_established)
                    )
                    self.conditional_guard_dependencies[condition] = {
                        item.id for item in ast.walk(stmt.test) if isinstance(item, ast.Name)
                    }
                continue
            if isinstance(stmt, (ast.For, ast.AsyncFor)):
                self._visit_expr(
                    stmt.iter,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                body_env = dict(env)
                self.owner._bind_target(
                    stmt.target,
                    self._eval_value(stmt.iter, env, active_guards),
                    body_env,
                )
                self._analyze_block(
                    stmt.body,
                    body_env,
                    active_guards,
                    unprotected_roots,
                )
                self._analyze_block(
                    stmt.orelse,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                continue
            if isinstance(stmt, (ast.With, ast.AsyncWith)):
                body_env = dict(env)
                for item in stmt.items:
                    self._visit_expr(
                        item.context_expr,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
                    if item.optional_vars is not None:
                        self.owner._bind_target(
                            item.optional_vars,
                            self._eval_value(item.context_expr, env, active_guards),
                            body_env,
                        )
                self._analyze_block(
                    stmt.body,
                    body_env,
                    active_guards,
                    unprotected_roots,
                )
                continue
            if isinstance(stmt, ast.Try):
                self._analyze_block(
                    stmt.body,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                for handler in stmt.handlers:
                    self._analyze_block(
                        handler.body,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
                self._analyze_block(
                    stmt.orelse,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                self._analyze_block(
                    stmt.finalbody,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                continue
            if isinstance(stmt, ast.Match):
                self._visit_expr(
                    stmt.subject,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                for case in stmt.cases:
                    self._analyze_block(
                        case.body,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
                continue
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Assert)):
                value = getattr(stmt, "value", None) or getattr(stmt, "exc", None)
                self._visit_expr(
                    value,
                    env,
                    active_guards,
                    unprotected_roots,
                )
                continue
            for child in ast.iter_child_nodes(stmt):
                if isinstance(child, ast.expr):
                    self._visit_expr(
                        child,
                        env,
                        active_guards,
                        unprotected_roots,
                    )
        return env, active_guards


def _merge_write_contexts(raw: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in raw:
        key = (
            item["path"], item["function"], item["line"], item["column"], item["write_method"]
        )
        grouped.setdefault(key, []).append(item)
    merged: list[dict[str, Any]] = []
    for key in sorted(grouped):
        variants = grouped[key]
        protected_variants = [item for item in variants if item["protected_target"]]
        record = dict(variants[0])
        record["protected_target"] = bool(protected_variants)
        record["protected_repos"] = sorted(
            {repo for item in variants for repo in item["protected_repos"]}
        )
        record["repo_roots"] = sorted({root for item in variants for root in item["repo_roots"]})
        record["analysis_context_count"] = len(variants)
        mechanisms = sorted({item["protection"] for item in protected_variants})
        record["protection_variants"] = mechanisms
        if not protected_variants:
            record["protection"] = "not_a_proven_protected_target"
            record["reason"] = ""
        elif "unprotected" in mechanisms:
            record["protection"] = "unprotected"
            record["reason"] = "; ".join(
                sorted({item["reason"] for item in protected_variants if item["reason"]})
            )
        elif len(mechanisms) == 1:
            record["protection"] = mechanisms[0]
            record["reason"] = ""
        else:
            record["protection"] = "+".join(mechanisms)
            record["reason"] = ""
        merged.append(record)
    return merged


def inventory_mutation_paths(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    protected_repos: Sequence[str] = tuple(sorted(PROTECTED_REPOS)),
    required_runtime: str = CANONICAL_RUNTIME,
    scan_roots: Sequence[Path | str] = SCAN_ROOTS,
) -> dict[str, Any]:
    protected = {str(item).strip().casefold() for item in protected_repos if str(item).strip()}
    raw_writes: list[dict[str, Any]] = []
    hard_rejections: list[dict[str, Any]] = []
    syntax_errors: list[dict[str, Any]] = []
    for scan_root in scan_roots:
        root = Path(scan_root)
        if not root.is_absolute():
            root = repository_root / root
        for path in _iter_python_files(root, repository_root=repository_root):
            rel = path.relative_to(repository_root).as_posix()
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                syntax_errors.append({"path": rel, "error": f"read_error:{type(exc).__name__}"})
                continue
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError as exc:
                syntax_errors.append({"path": rel, "error": f"SyntaxError:{exc.lineno}:{exc.msg}"})
                continue
            writes, rejections = _FileAnalyzer(
                path=path,
                relpath=rel,
                source_text=source,
                tree=tree,
                protected_repos=protected,
                required_runtime=required_runtime,
            ).analyze()
            raw_writes.extend(writes)
            hard_rejections.extend(rejections)

    callsites = _merge_write_contexts(raw_writes)
    protected_callsites = [item for item in callsites if item["protected_target"]]
    unprotected = [item for item in protected_callsites if item["protection"] == "unprotected"]
    hard_rejections = [
        dict(item)
        for _, item in sorted(
            {
                (item["path"], item["function"], item["line"]): item
                for item in hard_rejections
            }.items()
        )
    ]
    reasons = [
        f"{item['path']}:{item['line']} {item['function']} may mutate a protected "
        f"repository via {item['write_method']}: {item['reason']}"
        for item in unprotected
    ]
    if syntax_errors:
        reasons.extend(f"{item['path']} was not audited: {item['error']}" for item in syntax_errors)
    blocked = bool(unprotected or syntax_errors)
    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "required_runtime": required_runtime,
        "protected_repos": sorted(protected),
        "write_methods": sorted(PROTECTED_WRITE_METHODS),
        "read_only_methods_ignored": sorted(_READ_ONLY_METHODS),
        "callsite_count": len(callsites),
        "protected_callsite_count": len(protected_callsites),
        "unprotected_count": len(unprotected),
        "callsites": callsites,
        "unprotected_callsites": unprotected,
        "hard_rejected_functions": hard_rejections,
        "syntax_errors": syntax_errors,
        "authorizing_hub_upload": False,
        "status": "blocked" if blocked else "passed",
        "reasons": reasons,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory Hugging Face mutation paths for protected LCR repos"
    )
    parser.add_argument("--protected-repo", action="append", dest="protected_repos", default=[])
    parser.add_argument("--require-runtime", default=CANONICAL_RUNTIME)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--write", action="store_true", help="Write the audit receipt (never a Hub mutation)."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.check:
        sys.stderr.write(
            "audit_legal_corpora_hugging_face_mutation_paths: FAILED: --check is required\n"
        )
        return 2
    repos = tuple(args.protected_repos) or tuple(sorted(PROTECTED_REPOS))
    report = inventory_mutation_paths(
        protected_repos=repos, required_runtime=str(args.require_runtime)
    )
    if args.write:
        target = REPOSITORY_ROOT / REPORT_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "audit_legal_corpora_hugging_face_mutation_paths: "
            f"{report['status'].upper()} unprotected={report['unprotected_count']} "
            f"callsites={report['callsite_count']}\n"
        )
        for reason in report["reasons"][:12]:
            sys.stderr.write(f"  {reason}\n")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
