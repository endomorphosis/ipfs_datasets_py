"""Static, source-bound discovery of pytest tests and configuration.

This module deliberately does *not* ask pytest to collect anything.  It reads
Python with :mod:`ast` and the small, documented pytest configuration formats
only.  Consequently a discovered fixture parameter or decorator is exact
source evidence, while plugin and dynamically-built fixture declarations stay
present as conservative/opaque facts instead of becoming invented edges.
"""

from __future__ import annotations

import ast
import configparser
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

try:  # Python 3.11+, kept lazy so importing this module has no side effects.
    import tomllib
except ImportError:  # pragma: no cover - canonical support target has tomllib
    tomllib = None  # type: ignore[assignment]

from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.semantic_index.identity import stable_symbol_id
from ipfs_datasets_py.logic.software_contracts.semantic_index.models import (
    AnalysisConfidence,
    ArtifactRecord,
    DependencyEdge,
    RelationType,
    SourceSpan,
    SymbolKind,
)


PYTEST_ANALYZER_NAME = "pytest-static-ast"
PYTEST_ANALYZER_VERSION = "1"
_CONFIG_NAMES = frozenset({"pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"})
_SELF_ARGS = frozenset({"self", "cls"})


def _normal_path(path: str) -> str:
    value = str(PurePosixPath(path.replace("\\", "/")))
    if value in {".", ".."} or value.startswith("../") or value.startswith("/"):
        raise ValueError("path must be repository-relative")
    return value


def _span(path: str, node: ast.AST) -> SourceSpan:
    return SourceSpan(
        path, max(1, getattr(node, "lineno", 1)), max(0, getattr(node, "col_offset", 0)),
        max(1, getattr(node, "end_lineno", getattr(node, "lineno", 1))),
        max(0, getattr(node, "end_col_offset", getattr(node, "col_offset", 0))),
    )


def _expr_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expr_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _literal_strings(node: ast.AST) -> tuple[str, ...] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: list[str] = []
        for item in node.elts:
            parsed = _literal_strings(item)
            if parsed is None:
                return None
            values.extend(parsed)
        return tuple(values)
    return None


def _merge_confidence(*values: str) -> str:
    order = {"exact": 0, "conservative": 1, "heuristic": 2, "opaque": 3}
    return max(values, key=lambda value: order[value]) if values else "exact"


def _render_marker_value(node: ast.AST) -> str | None:
    """Return a stable source projection of one marker argument or keyword."""
    try:
        return ast.unparse(node)
    except (TypeError, ValueError, AttributeError):
        return None


def _marker_descriptor(decorator: ast.AST) -> tuple[str, str | None, bool]:
    """Return ``(marker_name, value_projection, dynamic)`` for one decorator."""
    if isinstance(decorator, ast.Call):
        name = _expr_name(decorator.func)
        if not name or not (name.startswith("pytest.mark.") or name.startswith("mark.")):
            return "", None, True
        marker = name.rsplit(".", 1)[-1]
        if marker in {"usefixtures", "parametrize"}:
            return marker, None, False
        parts: list[str] = []
        dynamic = False
        for arg in decorator.args:
            rendered = _render_marker_value(arg)
            if rendered is None:
                dynamic = True
            else:
                parts.append(rendered)
        for keyword in decorator.keywords:
            rendered = _render_marker_value(keyword.value)
            if keyword.arg is None or rendered is None:
                dynamic = True
            else:
                parts.append(f"{keyword.arg}={rendered}")
        projection = f"{marker}({', '.join(parts)})" if parts else marker
        return marker, projection, dynamic
    name = _expr_name(decorator)
    if name and (name.startswith("pytest.mark.") or name.startswith("mark.")):
        marker = name.rsplit(".", 1)[-1]
        return marker, marker, False
    return "", None, name is None


def _pytestmark_from_value(node: ast.AST | None) -> tuple[tuple[str, ...], bool]:
    """Extract marker projections from a ``pytestmark = ...`` assignment."""
    if node is None:
        return (), True
    items: list[ast.AST]
    if isinstance(node, (ast.List, ast.Tuple)):
        items = list(node.elts)
    else:
        items = [node]
    markers: list[str] = []
    dynamic = False
    for item in items:
        marker, projection, item_dynamic = _marker_descriptor(item)
        dynamic = dynamic or item_dynamic
        if projection:
            markers.append(projection)
        elif marker:
            markers.append(marker)
        else:
            dynamic = True
    return tuple(sorted(set(markers))), dynamic


@dataclass(frozen=True, slots=True)
class PytestTestFacts:
    """A test declaration and the source syntax that determines its receipts."""

    symbol_id: str
    path: str
    qualified_name: str
    fixture_parameters: tuple[str, ...] = ()
    usefixtures: tuple[str, ...] = ()
    markers: tuple[str, ...] = ()
    parametrizations: tuple[tuple[str, ...], ...] = ()
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    span: SourceSpan | None = None
    source_cid: str | None = None
    all_parameters: tuple[str, ...] = ()
    module_markers: tuple[str, ...] = ()
    class_markers: tuple[str, ...] = ()

    @property
    def fixture_names(self) -> tuple[str, ...]:
        """Fixture dependencies: parameters and usefixtures, never pure params.

        Parametrized argument names are not fixture dependencies unless the
        same name is independently supplied (parameter list outside
        ``parametrize`` or an explicit ``usefixtures`` entry).
        ``fixture_parameters`` already excludes pure parametrize names; union
        with ``usefixtures`` covers independently supplied names.
        """
        return tuple(sorted(set(self.fixture_parameters) | set(self.usefixtures)))

    @property
    def version_markers(self) -> tuple[str, ...]:
        """All markers that participate in the test version projection."""
        return tuple(sorted(set(self.markers) | set(self.module_markers) | set(self.class_markers)))


@dataclass(frozen=True, slots=True)
class PytestFixtureFacts:
    """A fixture declaration and its explicit fixture-name dependencies."""

    symbol_id: str
    path: str
    qualified_name: str
    name: str
    dependencies: tuple[str, ...] = ()
    scope: str | None = None
    autouse: bool | None = None
    params: tuple[str, ...] = ()
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    span: SourceSpan | None = None
    source_cid: str | None = None


@dataclass(frozen=True, slots=True)
class PytestConfigurationFacts:
    """A parsed config/conftest artifact, including unparseable opaque input."""

    artifact_id: str
    path: str
    kind: str
    values: Mapping[str, Any] = field(default_factory=dict)
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    source_cid: str | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PytestAnalysis:
    """Sorted analyzer output suitable for a later repository-state assembler."""

    tests: tuple[PytestTestFacts, ...] = ()
    fixtures: tuple[PytestFixtureFacts, ...] = ()
    configurations: tuple[PytestConfigurationFacts, ...] = ()
    symbols: tuple[tuple[str, SymbolKind], ...] = ()
    artifacts: tuple[ArtifactRecord, ...] = ()
    edges: tuple[DependencyEdge, ...] = ()
    diagnostics: tuple[str, ...] = ()


class PytestAnalyzer:
    """Discover pytest syntax without imports, collection, plugins, or execution."""

    def __init__(self, *, repository_id: str = "repository:unknown", namespace: str = "pytest") -> None:
        self.repository_id = repository_id
        self.namespace = namespace

    def analyze(self, source: str | bytes, *, path: str) -> PytestAnalysis:
        """Analyze one tracked file; Python and config files may be combined later."""
        path = _normal_path(path)
        if path.endswith(".py"):
            return self.analyze_python(source, path=path)
        if PurePosixPath(path).name in _CONFIG_NAMES:
            return self.analyze_configuration(source, path=path)
        return PytestAnalysis(diagnostics=(f"unsupported pytest artifact: {path}",))

    def analyze_files(self, sources: Mapping[str, str | bytes]) -> PytestAnalysis:
        """Analyze a snapshot and attach each test to applicable config files.

        ``conftest.py`` is scoped by its containing directory; the supported
        INI/TOML files are repository-wide pytest configuration.  This is a
        syntactic scope rule, not pytest collection, so it remains stable
        without loading plugins or importing project code.
        """
        partial = [self.analyze(source, path=path) for path, source in sorted(sources.items())]
        tests = tuple(sorted((item for result in partial for item in result.tests), key=lambda item: item.symbol_id))
        fixtures = tuple(sorted((item for result in partial for item in result.fixtures), key=lambda item: item.symbol_id))
        configurations = tuple(sorted((item for result in partial for item in result.configurations), key=lambda item: item.artifact_id))
        symbols = tuple(sorted((item for result in partial for item in result.symbols), key=lambda item: item[0]))
        artifacts = tuple(sorted((item for result in partial for item in result.artifacts), key=lambda item: item.artifact_id))
        diagnostics = tuple(sorted({item for result in partial for item in result.diagnostics}))
        return PytestAnalysis(tests, fixtures, configurations, symbols, artifacts, self._edges(tests, fixtures, configurations), diagnostics)

    def analyze_python(self, source: str | bytes, *, path: str) -> PytestAnalysis:
        path = _normal_path(path)
        raw, text = _decode(source)
        source_cid = cid_for_bytes(raw)
        try:
            tree = ast.parse(text, filename=path, type_comments=True)
        except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
            config = self._conftest_artifact(path, source_cid, "opaque", {"parse_error": type(exc).__name__}) if PurePosixPath(path).name == "conftest.py" else None
            return PytestAnalysis(configurations=(() if config is None else (config,)), artifacts=(() if config is None else (self._artifact(config),)), diagnostics=(f"python parse failed: {type(exc).__name__}",))

        tests: list[PytestTestFacts] = []
        fixtures: list[PytestFixtureFacts] = []
        configurations: list[PytestConfigurationFacts] = []
        dynamic: list[str] = []
        is_conftest = PurePosixPath(path).name == "conftest.py"
        if is_conftest:
            configurations.append(self._conftest_facts(tree, path, source_cid, dynamic))

        module_markers, module_dynamic = _collect_pytestmark(tree.body)
        if module_dynamic:
            dynamic.append("dynamic module pytestmark")

        def visit_body(body: Sequence[ast.stmt], prefix: str = "", class_markers: tuple[str, ...] = ()) -> None:
            for node in body:
                if isinstance(node, ast.ClassDef):
                    own_markers, class_dynamic = _collect_class_markers(node)
                    if class_dynamic:
                        dynamic.append(f"dynamic class markers at {prefix}{node.name}")
                    visit_body(node.body, f"{prefix}{node.name}.", tuple(sorted(set(class_markers) | set(own_markers))))
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = f"{prefix}{node.name}"
                    fixture = _fixture_decorator(node.decorator_list)
                    test = node.name.startswith("test_") and (not prefix or prefix.split(".")[0].startswith("Test"))
                    if fixture is not None:
                        facts, problem = self._fixture_facts(node, path, qualified, source_cid, fixture)
                        fixtures.append(facts)
                        if problem:
                            dynamic.append(f"dynamic fixture declaration at {qualified}")
                    if test:
                        facts, problems = self._test_facts(
                            node, path, qualified, source_cid,
                            module_markers=module_markers,
                            class_markers=class_markers,
                        )
                        tests.append(facts)
                        dynamic.extend(f"{problem} at {qualified}" for problem in problems)

        visit_body(tree.body)
        artifacts = tuple(self._artifact(item) for item in configurations)
        edges = self._edges(tests, fixtures, configurations)
        symbols = tuple(sorted(((item.symbol_id, SymbolKind.TEST) for item in tests), key=lambda item: item[0])) + tuple(sorted(((item.symbol_id, SymbolKind.FIXTURE) for item in fixtures), key=lambda item: item[0]))
        return PytestAnalysis(tuple(sorted(tests, key=lambda item: item.symbol_id)), tuple(sorted(fixtures, key=lambda item: item.symbol_id)), tuple(sorted(configurations, key=lambda item: item.artifact_id)), symbols, artifacts, edges, tuple(sorted(set(dynamic))))

    def analyze_configuration(self, source: str | bytes, *, path: str) -> PytestAnalysis:
        path = _normal_path(path)
        raw, text = _decode(source)
        source_cid = cid_for_bytes(raw)
        values: dict[str, Any] = {}
        diagnostics: list[str] = []
        confidence = "exact"
        try:
            name = PurePosixPath(path).name
            if name == "pyproject.toml":
                if tomllib is None:
                    raise ValueError("tomllib unavailable")
                payload = tomllib.loads(text)
                tool = payload.get("tool", {}) if isinstance(payload, dict) else {}
                pytest = tool.get("pytest", {}) if isinstance(tool, dict) else {}
                values = dict(pytest.get("ini_options", pytest) if isinstance(pytest, dict) else {})
            else:
                parser = configparser.ConfigParser(interpolation=None)
                parser.read_string(text)
                section = "pytest" if name in {"pytest.ini", "tox.ini"} else "tool:pytest"
                values = dict(parser.items(section)) if parser.has_section(section) else {}
        except (configparser.Error, ValueError, TypeError, UnicodeDecodeError) as exc:
            confidence = "opaque"
            diagnostics.append(f"config parse failed: {type(exc).__name__}")
        if any(key in values for key in ("plugins", "required_plugins")):
            confidence = _merge_confidence(confidence, "conservative")
            diagnostics.append("plugin configuration requires runtime discovery")
        facts = PytestConfigurationFacts(self._config_id(path), path, "pytest_config", dict(sorted(values.items())), confidence, source_cid, tuple(sorted(diagnostics)))
        return PytestAnalysis(configurations=(facts,), artifacts=(self._artifact(facts),), diagnostics=facts.diagnostics)

    def _symbol_id(self, path: str, qualified: str, kind: SymbolKind) -> str:
        return stable_symbol_id(self.repository_id, "python", path, qualified, kind, self.namespace)

    def _fixture_facts(self, node: ast.FunctionDef | ast.AsyncFunctionDef, path: str, qualified: str, source_cid: str, decorator: ast.AST) -> tuple[PytestFixtureFacts, bool]:
        confidence = "exact"; scope: str | None = None; autouse: bool | None = None; params: tuple[str, ...] = (); problem = False
        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if keyword.arg == "scope" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str): scope = keyword.value.value
                elif keyword.arg == "autouse" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, bool): autouse = keyword.value.value
                elif keyword.arg == "params":
                    parsed = _literal_strings(keyword.value)
                    if parsed is None: problem = True
                    else: params = parsed
                elif keyword.arg not in {"name"}:
                    problem = True
            if any(keyword.arg == "name" for keyword in decorator.keywords):
                # Aliased fixture names are source-bound but no longer match the function name.
                name_value = next(keyword.value for keyword in decorator.keywords if keyword.arg == "name")
                parsed = _literal_strings(name_value)
                if parsed is None or len(parsed) != 1: problem = True
                else: fixture_name = parsed[0]
            else: fixture_name = node.name
        else: fixture_name = node.name
        if problem: confidence = "conservative"
        dependencies = tuple(arg.arg for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs if arg.arg not in _SELF_ARGS)
        return PytestFixtureFacts(self._symbol_id(path, qualified, SymbolKind.FIXTURE), path, qualified, fixture_name, tuple(sorted(dependencies)), scope, autouse, tuple(sorted(params)), confidence, _span(path, node), source_cid), problem

    def _test_facts(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        path: str,
        qualified: str,
        source_cid: str,
        *,
        module_markers: tuple[str, ...] = (),
        class_markers: tuple[str, ...] = (),
    ) -> tuple[PytestTestFacts, list[str]]:
        markers: list[str] = []; usefixtures: list[str] = []; parametrizations: list[tuple[str, ...]] = []; problems: list[str] = []
        for decorator in node.decorator_list:
            name = _expr_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
            if name in {"pytest.mark.usefixtures", "mark.usefixtures"}:
                parsed = tuple(item for arg in decorator.args for item in (_literal_strings(arg) or ())) if isinstance(decorator, ast.Call) else ()
                if not parsed or any(_literal_strings(arg) is None for arg in decorator.args): problems.append("dynamic usefixtures")
                else: usefixtures.extend(parsed)
            elif name in {"pytest.mark.parametrize", "mark.parametrize"}:
                if not isinstance(decorator, ast.Call) or not decorator.args:
                    problems.append("dynamic parametrize")
                else:
                    names = _literal_strings(decorator.args[0])
                    if names is None: problems.append("dynamic parametrize")
                    else: parametrizations.append(tuple(sorted(part.strip() for item in names for part in item.split(",") if part.strip())))
                    if len(decorator.args) < 2 or not _is_static_value(decorator.args[1]): problems.append("dynamic parametrization values")
            elif name and (name.startswith("pytest.mark.") or name.startswith("mark.")):
                marker, projection, dynamic = _marker_descriptor(decorator)
                if dynamic:
                    problems.append("dynamic marker arguments")
                if projection:
                    markers.append(projection)
                elif marker:
                    markers.append(marker)
            elif name:
                # A non-pytest decorator can wrap or manufacture the test at
                # import time.  Keep the test, but do not claim exact pytest
                # collection semantics from its name alone.
                problems.append("unknown decorator")
            elif name is None:
                problems.append("dynamic decorator")
        all_parameters = tuple(arg.arg for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs if arg.arg not in _SELF_ARGS)
        parametrized_names = {name for group in parametrizations for name in group}
        # Parametrized names are not fixture parameters; usefixtures may still
        # independently supply a name that also appears in parametrize.
        fixture_parameters = tuple(sorted(name for name in all_parameters if name not in parametrized_names))
        confidence = "conservative" if problems else "exact"
        return PytestTestFacts(
            self._symbol_id(path, qualified, SymbolKind.TEST), path, qualified,
            fixture_parameters, tuple(sorted(set(usefixtures))), tuple(sorted(set(markers))),
            tuple(sorted(set(parametrizations))), confidence, _span(path, node), source_cid,
            tuple(sorted(all_parameters)), tuple(sorted(module_markers)), tuple(sorted(class_markers)),
        ), problems

    def _config_id(self, path: str) -> str: return f"pytest-config:{path}"

    def _conftest_artifact(self, path: str, source_cid: str, confidence: str, values: Mapping[str, Any]) -> PytestConfigurationFacts:
        return PytestConfigurationFacts(self._config_id(path), path, "conftest", dict(values), confidence, source_cid)

    def _conftest_facts(self, tree: ast.Module, path: str, source_cid: str, dynamic: list[str]) -> PytestConfigurationFacts:
        plugins: tuple[str, ...] = (); hooks: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("pytest_"): hooks.append(node.name)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
                if any(isinstance(target, ast.Name) and target.id == "pytest_plugins" for target in targets):
                    parsed = _literal_strings(node.value)
                    if parsed is None: dynamic.append("dynamic pytest_plugins")
                    else: plugins = tuple(sorted(parsed))
        confidence = "conservative" if plugins or any("pytest_plugins" in item for item in dynamic) else "exact"
        return self._conftest_artifact(path, source_cid, confidence, {"hooks": tuple(sorted(hooks)), "plugins": plugins})

    def _artifact(self, facts: PytestConfigurationFacts) -> ArtifactRecord:
        return ArtifactRecord(facts.artifact_id, facts.kind, facts.path, facts.source_cid, facts.confidence, {"values": _dag_json(facts.values), "diagnostics": list(facts.diagnostics)})

    def _edges(self, tests: Iterable[PytestTestFacts], fixtures: Iterable[PytestFixtureFacts], configurations: Iterable[PytestConfigurationFacts]) -> tuple[DependencyEdge, ...]:
        fixture_list = tuple(fixtures)
        test_list = tuple(tests)
        edges: list[DependencyEdge] = []

        def resolve_fixture(name: str, subject_path: str) -> tuple[PytestFixtureFacts | None, str, str]:
            """Resolve one fixture name with conftest/module lexical scope."""
            candidates = [item for item in fixture_list if item.name == name and _fixture_visible(item.path, subject_path)]
            if not candidates:
                return None, f"pytest-fixture:{name}", "conservative"
            ranked = sorted(candidates, key=lambda item: (-_fixture_specificity(item.path, subject_path), item.path, item.symbol_id))
            best_rank = _fixture_specificity(ranked[0].path, subject_path)
            top = [item for item in ranked if _fixture_specificity(item.path, subject_path) == best_rank]
            if len(top) == 1:
                return top[0], top[0].symbol_id, top[0].confidence
            # Same-rank ambiguity is retained as finite may via unresolved name.
            return None, f"pytest-fixture:{name}", "conservative"

        for subject in (*test_list, *fixture_list):
            if isinstance(subject, PytestTestFacts):
                names = list(subject.fixture_names)
                # Autouse fixtures visible from this test are implicit deps.
                for fixture in fixture_list:
                    if fixture.autouse is True and _fixture_visible(fixture.path, subject.path) and fixture.name not in names:
                        names.append(fixture.name)
                names = sorted(set(names))
            else:
                names = list(subject.dependencies)
            for name in names:
                target, target_id, target_confidence = resolve_fixture(name, subject.path)
                confidence = _merge_confidence(subject.confidence, target_confidence)
                metadata = {
                    "fixture_name": name,
                    "source_bound": True,
                    "scope": None if target is None else target.scope,
                    "autouse": None if target is None else target.autouse,
                }
                if target is None:
                    metadata["resolution"] = "unresolved"
                    metadata["unresolved_target"] = target_id
                edges.append(DependencyEdge(
                    subject.symbol_id, target_id, RelationType.USES_FIXTURE,
                    "pytest-static-parameter", confidence, PYTEST_ANALYZER_VERSION,
                    subject.span, metadata,
                ))
        for test in test_list:
            for config in configurations:
                if not _configuration_applies(config.path, test.path):
                    continue
                # A parsed configuration/conftest is an explicit receipt input for every test in this scan.
                edges.append(DependencyEdge(
                    test.symbol_id, config.artifact_id, RelationType.CONFIGURED_BY,
                    "pytest-static-config-scope", config.confidence, PYTEST_ANALYZER_VERSION,
                    test.span, {"config_path": config.path, "source_bound": True},
                ))
        return tuple(sorted(edges, key=lambda item: item.edge_id))


def _collect_pytestmark(body: Sequence[ast.stmt]) -> tuple[tuple[str, ...], bool]:
    markers: list[str] = []
    dynamic = False
    for node in body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            if any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in targets):
                found, item_dynamic = _pytestmark_from_value(node.value)
                markers.extend(found)
                dynamic = dynamic or item_dynamic
    return tuple(sorted(set(markers))), dynamic


def _collect_class_markers(node: ast.ClassDef) -> tuple[tuple[str, ...], bool]:
    markers: list[str] = []
    dynamic = False
    for decorator in node.decorator_list:
        marker, projection, item_dynamic = _marker_descriptor(decorator)
        dynamic = dynamic or item_dynamic
        if projection:
            markers.append(projection)
        elif marker and marker not in {"usefixtures", "parametrize"}:
            markers.append(marker)
    body_markers, body_dynamic = _collect_pytestmark(node.body)
    markers.extend(body_markers)
    dynamic = dynamic or body_dynamic
    return tuple(sorted(set(markers))), dynamic


def _decode(source: str | bytes) -> tuple[bytes, str]:
    if type(source) is str: return source.encode("utf-8"), source
    if type(source) is bytes: return source, source.decode("utf-8")
    raise TypeError("source must be str or bytes")


def _fixture_decorator(decorators: Sequence[ast.expr]) -> ast.AST | None:
    for decorator in decorators:
        name = _expr_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
        if name in {"pytest.fixture", "fixture"}: return decorator
    return None


def _is_static_value(node: ast.AST) -> bool:
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, MemoryError, RecursionError):
        return False
    return True


def _dag_json(value: Any) -> Any:
    """Convert immutable fact conveniences to the closed model's JSON shape."""
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if isinstance(value, Mapping):
        return {str(key): _dag_json(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_dag_json(item) for item in value]
    # TOML permits date/time values, but they are not pytest's declared
    # scalar config vocabulary.  Preserve their observed representation while
    # making the artifact conservative at the caller boundary.
    return str(value)


def _configuration_applies(config_path: str, test_path: str) -> bool:
    """Return the statically known pytest config scope for one test path."""
    if PurePosixPath(config_path).name != "conftest.py":
        return True
    parent = PurePosixPath(config_path).parent
    return parent == PurePosixPath(".") or str(PurePosixPath(test_path)).startswith(f"{parent}/")


def _fixture_visible(fixture_path: str, subject_path: str) -> bool:
    """Whether a fixture declaration is in lexical pytest scope for a subject."""
    if fixture_path == subject_path:
        return True
    name = PurePosixPath(fixture_path).name
    if name != "conftest.py":
        # Non-conftest module fixtures are only visible inside that module.
        return False
    parent = PurePosixPath(fixture_path).parent
    if parent == PurePosixPath("."):
        return True
    return str(PurePosixPath(subject_path)).startswith(f"{parent}/")


def _fixture_specificity(fixture_path: str, subject_path: str) -> int:
    """Higher is closer: same-module fixtures outrank nearer conf tests."""
    if fixture_path == subject_path:
        return 10_000 + len(fixture_path)
    parent = PurePosixPath(fixture_path).parent
    if parent == PurePosixPath("."):
        return 1
    return 100 + len(str(parent))


def analyze_pytest_source(source: str | bytes, *, path: str, repository_id: str = "repository:unknown", namespace: str = "pytest") -> PytestAnalysis:
    """Convenience entry point for one source/config artifact."""
    return PytestAnalyzer(repository_id=repository_id, namespace=namespace).analyze(source, path=path)


__all__ = [
    "PYTEST_ANALYZER_NAME",
    "PYTEST_ANALYZER_VERSION",
    "PytestAnalysis",
    "PytestAnalyzer",
    "PytestConfigurationFacts",
    "PytestFixtureFacts",
    "PytestTestFacts",
    "analyze_pytest_source",
]
