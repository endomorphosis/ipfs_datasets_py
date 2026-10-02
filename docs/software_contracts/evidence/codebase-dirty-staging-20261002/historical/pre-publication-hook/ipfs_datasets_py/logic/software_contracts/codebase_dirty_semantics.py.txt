"""Bounded file-local extraction and complete native scanner assembly.

This is a staging adapter for the existing Python/pytest analyzers. It preserves
their raw local facts until the complete inventory is available for resolution.
It neither infers contracts nor gives caller-provided facts proof authority.
"""
from __future__ import annotations

from dataclasses import asdict, fields
import json

from .content import canonical_dag_json_bytes, cid_for_bytes
from .semantic_index import scanner
from .semantic_index.models import ArtifactRecord, DependencyEdge, RepositoryState, SourceSpan, SymbolRecord
from .semantic_index.pytest_analysis import (
    PytestAnalyzer, PytestConfigurationFacts, PytestFixtureFacts, PytestTestFacts,
)
from .semantic_index.python_analysis import PythonSemanticAnalyzer
from .semantic_index.symbol_graph import build_symbol_graph

SCHEMA = "codebase-dirty-file-semantics@1"
MAX_FACT_BYTES = 4 * 1024 * 1024


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _plain(value):
    return json.loads(canonical_dag_json_bytes(json.loads(json.dumps(value))))


def _fact(value):
    return _plain(asdict(value))


def extract(snapshot, entry, raw):
    """Extract one exact file, keeping edges unresolved across file boundaries."""
    _require(not entry.is_opaque and type(raw) is bytes and cid_for_bytes(raw) == entry.source_cid,
             "semantic extraction requires exact captured bytes")
    symbols, edges, artifacts, tests, fixtures, configurations = [], [], [], [], [], []
    path = entry.path
    if scanner._artifact_path(entry) != path:
        artifacts.append(scanner._opaque_artifact(entry, "raw_path_not_model_safe").to_dict())
    else:
        if entry.kind == "python":
            result = PythonSemanticAnalyzer(repository_id=snapshot.repository_id).analyze(raw, path)
            if result.diagnostics:
                artifacts.append(ArtifactRecord(scanner._artifact_id(path), "python-analysis", path,
                    entry.source_cid, "opaque", {"diagnostics": list(result.diagnostics)}).to_dict())
            else:
                symbols = [fact.symbol.to_dict() for fact in result.symbols]
                edges = [edge.to_dict() for fact in result.symbols for edge in fact.edges]
        if entry.kind in {"python", "pytest-config"}:
            result = PytestAnalyzer(repository_id=snapshot.repository_id, namespace="pytest").analyze(raw, path=path)
            artifacts.extend(row.to_dict() for row in result.artifacts)
            tests = [_fact(row) for row in result.tests]
            fixtures = [_fact(row) for row in result.fixtures]
            configurations = [_fact(row) for row in result.configurations]
        else:
            artifacts.append(scanner._typed_artifact(entry).to_dict())
    result = dict(schema=SCHEMA, source_key=entry.source_key, source_cid=entry.source_cid,
                  symbols=symbols, edges=edges, artifacts=artifacts, tests=tests,
                  fixtures=fixtures, configurations=configurations)
    _require(len(canonical_dag_json_bytes(result)) <= MAX_FACT_BYTES, "file semantic facts exceed staging bound")
    return result


def _restore(cls, raw):
    _require(type(raw) is dict and set(raw) == {f.name for f in fields(cls)}, "closed native pytest fact required")
    value = dict(raw)
    if "span" in value and value["span"] is not None:
        value["span"] = SourceSpan(**value["span"])
    for field in fields(cls):
        item = value[field.name]
        if isinstance(item, list):
            value[field.name] = tuple(tuple(v) if isinstance(v, list) else v for v in item)
    result = cls(**value)
    _require(_fact(result) == raw, "native pytest fact did not round trip")
    return result


def restore(snapshot, entry, value):
    """Check native typed facts and their exact entry/source binding."""
    _require(type(value) is dict and set(value) == {
        "schema", "source_key", "source_cid", "symbols", "edges", "artifacts", "tests", "fixtures", "configurations"
    } and value["schema"] == SCHEMA and value["source_key"] == entry.source_key
        and value["source_cid"] == entry.source_cid and not entry.is_opaque,
        "semantic page differs from sealed source")
    _require(len(canonical_dag_json_bytes(value)) <= MAX_FACT_BYTES, "semantic page exceeds byte bound")
    for name in ("symbols", "edges", "artifacts", "tests", "fixtures", "configurations"):
        _require(type(value[name]) is list and len(value[name]) <= 32768, "bounded semantic fact population required")
    symbols = [SymbolRecord.from_dict(v) for v in value["symbols"]]
    edges = [DependencyEdge.from_dict(v) for v in value["edges"]]
    artifacts = [ArtifactRecord.from_dict(v) for v in value["artifacts"]]
    tests = [_restore(PytestTestFacts, v) for v in value["tests"]]
    fixtures = [_restore(PytestFixtureFacts, v) for v in value["fixtures"]]
    configurations = [_restore(PytestConfigurationFacts, v) for v in value["configurations"]]
    _require(all(s.repository_id == snapshot.repository_id and s.module_path == entry.path
                 and s.source_cid == entry.source_cid for s in symbols), "symbol source differs")
    _require(all(e.source_id in {s.stable_id for s in symbols} for e in edges), "local edge source differs")
    _require(all(a.path == scanner._artifact_path(entry) and a.source_cid == entry.source_cid for a in artifacts),
             "local artifact source differs")
    _require(all(f.path == entry.path and f.source_cid == entry.source_cid for f in [*tests, *fixtures, *configurations]),
             "pytest fact source differs")
    return symbols, edges, artifacts, tests, fixtures, configurations


def assemble(snapshot, facts):
    """Globally resolve the complete inventory using the native scanner helpers.

    Every nonopaque entry must have a sealed local fact record, including files
    with zero symbols. No parsing or target execution occurs during assembly.
    """
    expected = {e.source_key for e in snapshot.entries if not e.is_opaque}
    _require(set(facts) == expected, "semantic assembly requires the complete inventory")
    symbols, edges, artifacts, tests, fixtures, configurations = [], [], [], [], [], []
    artifacts.append(ArtifactRecord("artifact:snapshot-evidence", "snapshot-evidence", "@snapshot-evidence",
        snapshot.snapshot_cid, "exact", {"snapshot": snapshot.to_dict(), "acquisition": snapshot.mode,
        "exclusions": list(snapshot.exclusions)}))
    for entry in snapshot.entries:
        if entry.is_opaque:
            artifacts.append(scanner._opaque_artifact(entry, entry.opaque_reason or "opaque_snapshot"))
            continue
        rows = restore(snapshot, entry, facts[entry.source_key])
        for target, items in zip((symbols, edges, artifacts, tests, fixtures, configurations), rows):
            target.extend(items)
    tests.sort(key=lambda v: v.symbol_id)
    fixtures.sort(key=lambda v: v.symbol_id)
    configurations.sort(key=lambda v: v.artifact_id)
    pytest_edges = PytestAnalyzer(repository_id=snapshot.repository_id, namespace="pytest")._edges(tests, fixtures, configurations)
    symbols, edges, _ = scanner.unify_pytest_identities(symbols, edges, tests, fixtures, pytest_edges,
                                                       repository_id=snapshot.repository_id, namespace=None)
    edges.extend(scanner._lock_configuration_edges(symbols, artifacts))
    graph = build_symbol_graph(symbols, artifacts, edges)
    return RepositoryState(snapshot.repository_id, graph.symbols, graph.artifacts, graph.edges,
                           scanner.SCANNER_NAME, scanner.SCANNER_VERSION)


__all__ = ["extract", "restore", "assemble"]
