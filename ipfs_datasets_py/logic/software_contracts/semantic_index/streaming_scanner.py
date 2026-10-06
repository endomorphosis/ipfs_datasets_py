"""Explicit bounded ordinary-source analysis over an admitted committed population.

Only one modest blob is captured at a time. Trusted analyzers run in owned,
limited children; target modules are never imported or executed. Canonical
facts are accumulated under a separate bound, not an unbounded source cache.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes, cid_for_bytes
from .chunked_snapshot import (
    ChunkedProjection, ChunkedRepositorySnapshot, MAX_FRAME_BYTES, MAX_MATERIALIZED_FILE_BYTES,
    _hash_blob,
)
from .git_decoder_profile import (
    DEFAULT_DECODER_PROFILE, DEFAULT_DECODER_BUDGET, require_decoder_profile,
)
from .committed_snapshot import _fence
from .models import ArtifactRecord, DependencyEdge, RepositoryState, SourceSpan, SymbolRecord
from .paged_snapshot import admit_chunked_snapshot_manifest, page_snapshot_evidence
from .python_analysis import PythonSemanticAnalyzer
from .pytest_analysis import PytestAnalyzer, PytestTestFacts, PytestFixtureFacts, PytestConfigurationFacts, _dag_json
from .scanner import (
    SCANNER_NAME, SCANNER_VERSION, _artifact_path, _opaque_artifact, _typed_artifact,
    _lock_configuration_edges, unify_pytest_identities,
)
from .snapshot import RepositorySnapshot, SnapshotEntry, SnapshotError, _entry, _malformed_raw, _opaque
from .symbol_graph import build_symbol_graph

MAX_FACT_BYTES = 32 * 1024 * 1024
MAX_FILE_FACT_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 100000
MAX_AST_NODES = 100000
WORKER_ADDRESS_BYTES = 256 * 1024 * 1024
WORKER_CPU_SECONDS = 15
WORKER_TIMEOUT_SECONDS = 20
WORKER_SCHEMA = "ipfs-datasets.streaming-scanner-worker@1"


class StreamingAnalysisError(SnapshotError):
    """A complete result was refused; no omitted input is declared analyzed."""
    def __init__(self, code, *, phase="analysis", path=None, limit=None, observed=None):
        super().__init__("streaming scanner refused: " + code)
        self.code, self.phase, self.path, self.limit, self.observed = code, phase, path, limit, observed

    def observation(self):
        return {"schema": "ipfs-datasets.streaming-analysis-refusal@1", "code": self.code,
                "phase": self.phase, "path": self.path, "limit": self.limit, "observed": self.observed,
                "complete_analysis_authority": False, "completion_authority": False}


@dataclass(frozen=True)
class StreamingScanLimits:
    max_fact_bytes: int = MAX_FACT_BYTES
    max_file_fact_bytes: int = MAX_FILE_FACT_BYTES
    max_record_bytes: int = MAX_FRAME_BYTES
    max_records: int = MAX_RECORDS
    max_ast_nodes: int = MAX_AST_NODES
    worker_timeout_seconds: int = WORKER_TIMEOUT_SECONDS

    def __post_init__(self):
        ceilings = (MAX_FACT_BYTES, MAX_FILE_FACT_BYTES, MAX_FRAME_BYTES, MAX_RECORDS,
                    MAX_AST_NODES, WORKER_TIMEOUT_SECONDS)
        if any(type(n) is not int or not 1 <= n <= ceiling
               for n, ceiling in zip(asdict(self).values(), ceilings)):
            raise StreamingAnalysisError("invalid_fixed_analysis_limits", phase="admission")
        if self.max_file_fact_bytes > self.max_fact_bytes:
            raise StreamingAnalysisError("file_fact_limit_exceeds_aggregate", phase="admission")


def analysis_process_profile():
    import multiformats
    return {"schema": "ipfs-datasets.streaming-analysis-process@1",
            "address_space_limit_bytes": WORKER_ADDRESS_BYTES, "cpu_limit_seconds": WORKER_CPU_SECONDS,
            "source_file_limit_bytes": MAX_MATERIALIZED_FILE_BYTES,
            "source_execution": False, "target_imports": False,
            "python_version": list(sys.version_info[:3]), "python_implementation": sys.implementation.name,
            "worker_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "content_identity_dependency_root": str(Path(multiformats.__file__).resolve().parents[1]),
            "memory_measurement": "worker ru_maxrss on Linux; separate from parent allocations and Git decoder"}


def _worker_command():
    import multiformats
    launcher = (
        "import resource,sys; "
        f"resource.setrlimit(resource.RLIMIT_AS,({WORKER_ADDRESS_BYTES},{WORKER_ADDRESS_BYTES})); "
        f"resource.setrlimit(resource.RLIMIT_CPU,({WORKER_CPU_SECONDS},{WORKER_CPU_SECONDS})); "
        "resource.setrlimit(resource.RLIMIT_CORE,(0,0)); "
        "sys.path.insert(0,sys.argv[2]); sys.path.insert(0,sys.argv[1]); "
        "from ipfs_datasets_py.logic.software_contracts.semantic_index.streaming_scanner import _worker_main; "
        "_worker_main()"
    )
    return [sys.executable, "-I", "-B", "-c", launcher, str(Path(__file__).resolve().parents[4]),
            str(Path(multiformats.__file__).resolve().parents[1])]


def _run_worker(header, payload, limits, *, output_limit):
    """Bound all pipes and time; kill and reap this owned process group on refusal."""
    header = {"expected_worker_source_sha256": analysis_process_profile()["worker_source_sha256"], **header}
    wire_header = canonical_dag_json_bytes({**header, "limits": asdict(limits), "size_bytes": len(payload)})
    if len(wire_header) > 4096 or len(payload) > MAX_FACT_BYTES:
        raise StreamingAnalysisError("worker_input_limit", phase=header["operation"])
    wire = wire_header + b"\n" + payload
    env = {key: value for key, value in os.environ.items() if not key.startswith(("PYTHON", "GIT_"))}
    env.update(IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS="0", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    child = subprocess.Popen(_worker_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True, env=env)
    deadline, offset = time.monotonic() + limits.worker_timeout_seconds, 0
    output, errors = bytearray(), bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            for stream, direction, events in ((child.stdin, "input", selectors.EVENT_WRITE),
                    (child.stdout, "output", selectors.EVENT_READ), (child.stderr, "errors", selectors.EVENT_READ)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, events, direction)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StreamingAnalysisError("worker_timeout", phase=header["operation"],
                                                 path=header.get("path"), limit=limits.worker_timeout_seconds)
                for key, _ in selector.select(min(remaining, .1)):
                    stream = key.fileobj
                    if key.data == "input":
                        try:
                            offset += os.write(stream.fileno(), memoryview(wire)[offset:offset + 65536])
                        except BrokenPipeError:
                            offset = len(wire)
                        if offset == len(wire):
                            selector.unregister(stream)
                            stream.close()
                    else:
                        piece = os.read(stream.fileno(), 65536)
                        if not piece:
                            selector.unregister(stream)
                            continue
                        target, bound = (output, output_limit) if key.data == "output" else (errors, 8192)
                        if len(target) + len(piece) > bound:
                            raise StreamingAnalysisError("worker_output_limit", phase=header["operation"],
                                                         path=header.get("path"), limit=bound)
                        target.extend(piece)
        try:
            child.wait(timeout=max(.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise StreamingAnalysisError("worker_timeout", phase=header["operation"]) from exc
        if child.returncode or errors:
            raise StreamingAnalysisError("worker_process_refusal", phase=header["operation"],
                                         path=header.get("path"), observed=child.returncode)
        try:
            result = json.loads(output)
            if canonical_dag_json_bytes(result) != output or result.get("schema") != WORKER_SCHEMA:
                raise ValueError("invalid worker response")
        except (ValueError, TypeError) as exc:
            raise StreamingAnalysisError("invalid_worker_response", phase=header["operation"]) from exc
        if "error" in result:
            refusal = result["error"]
            raise StreamingAnalysisError(refusal["code"], phase=refusal["phase"], path=refusal["path"],
                                         limit=refusal["limit"], observed=refusal["observed"])
        if set(result) != {"schema", "facts", "resources"}:
            raise StreamingAnalysisError("invalid_worker_response", phase=header["operation"])
        if result["resources"].get("worker_source_sha256") != header["expected_worker_source_sha256"]:
            raise StreamingAnalysisError("worker_source_profile_changed", phase=header["operation"])
        return result["facts"], result["resources"]
    finally:
        # Do not signal a numeric process group after wait() has reaped its
        # leader. Its PID could already belong to another process. Before
        # reaping, the retained child reserves that PID even if it has exited.
        if child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


def _check_records(records, limits, *, phase):
    total, count = 0, 0
    for record in records:
        count += 1
        if count > limits.max_records:
            raise StreamingAnalysisError("semantic_record_count", phase=phase, limit=limits.max_records, observed=count)
        size = len(canonical_dag_json_bytes(record))
        if size > limits.max_record_bytes:
            raise StreamingAnalysisError("semantic_record_frame", phase=phase, limit=limits.max_record_bytes, observed=size)
        total += size
        if total > limits.max_fact_bytes:
            raise StreamingAnalysisError("semantic_fact_budget", phase=phase, limit=limits.max_fact_bytes, observed=total)
    return total


def _analyze_one(raw, header, limits):
    path, identity, kind = header["path"], header["repository_id"], header["kind"]
    if len(raw) > MAX_MATERIALIZED_FILE_BYTES or cid_for_bytes(raw) != header["source_cid"]:
        raise StreamingAnalysisError("source_size_or_identity", path=path)
    symbols, edges, artifacts = [], [], []
    if kind == "python":
        try:
            tree = ast.parse(raw, filename=path, type_comments=True)
            for count, _ in enumerate(ast.walk(tree), 1):
                if count > limits.max_ast_nodes:
                    raise StreamingAnalysisError("ast_node_budget", path=path, limit=limits.max_ast_nodes, observed=count)
            del tree
        except StreamingAnalysisError:
            raise
        except (SyntaxError, ValueError):
            # Existing analyzers classify parse failures.
            pass
        analysis = PythonSemanticAnalyzer(repository_id=identity).analyze(raw, path)
        if analysis.diagnostics:
            artifacts.append(ArtifactRecord("artifact:" + path, "python-analysis", path,
                                            header["source_cid"], "opaque", {"diagnostics": list(analysis.diagnostics)}).to_dict())
        else:
            symbols = [item.symbol.to_dict() for item in analysis.symbols]
            edges = [edge.to_dict() for item in analysis.symbols for edge in item.edges]
        del analysis
    pytest = PytestAnalyzer(repository_id=identity, namespace="pytest").analyze(raw, path=path)
    artifacts.extend(item.to_dict() for item in pytest.artifacts)
    facts = {"path": path, "source_cid": header["source_cid"], "symbols": symbols, "edges": edges,
             "artifacts": artifacts, "tests": [_dag_json(asdict(item)) for item in pytest.tests],
             "fixtures": [_dag_json(asdict(item)) for item in pytest.fixtures],
             "configurations": [_dag_json(asdict(item)) for item in pytest.configurations]}
    _check_records((record for name in ("symbols", "edges", "artifacts", "tests", "fixtures", "configurations")
                    for record in facts[name]), limits, phase="analysis")
    if len(canonical_dag_json_bytes(facts)) > limits.max_file_fact_bytes:
        raise StreamingAnalysisError("file_fact_budget", path=path, limit=limits.max_file_fact_bytes)
    return facts


def _pytest_fact(cls, value):
    def tuples(item):
        return tuple(tuples(part) for part in item) if type(item) is list else item
    value = {key: tuples(item) for key, item in value.items()}
    if value.get("span") is not None:
        value["span"] = SourceSpan(**value["span"])
    return cls(**value)


def _assemble(payload, limits):
    symbols, artifacts, edges, tests, fixtures, configurations = [], [], [], [], [], []
    for facts in payload["files"]:
        symbols.extend(SymbolRecord.from_dict(item) for item in facts["symbols"])
        artifacts.extend(ArtifactRecord.from_dict(item) for item in facts["artifacts"])
        edges.extend(DependencyEdge.from_dict(item) for item in facts["edges"])
        tests.extend(_pytest_fact(PytestTestFacts, item) for item in facts["tests"])
        fixtures.extend(_pytest_fact(PytestFixtureFacts, item) for item in facts["fixtures"])
        configurations.extend(_pytest_fact(PytestConfigurationFacts, item) for item in facts["configurations"])
    artifacts.extend(ArtifactRecord.from_dict(item) for item in payload["artifacts"])
    tests.sort(key=lambda item: item.symbol_id)
    fixtures.sort(key=lambda item: item.symbol_id)
    configurations.sort(key=lambda item: item.artifact_id)
    pytest = PytestAnalyzer(repository_id=payload["repository_id"], namespace="pytest")
    pytest_edges = pytest._edges(tests, fixtures, configurations)
    symbols, edges, _ = unify_pytest_identities(symbols, edges, tests, fixtures, pytest_edges,
                                               repository_id=payload["repository_id"], namespace=None)
    edges.extend(_lock_configuration_edges(symbols, artifacts))
    _check_records((item.to_dict() for group in (symbols, edges, artifacts) for item in group), limits, phase="assembly")
    graph = build_symbol_graph(symbols, artifacts, edges)
    _check_records((item.to_dict() for group in (graph.symbols, graph.edges, graph.artifacts) for item in group),
                    limits, phase="resolved_assembly")
    state = RepositoryState(payload["repository_id"], graph.symbols, graph.artifacts, graph.edges,
                            SCANNER_NAME, SCANNER_VERSION)
    result = state.to_dict()
    if len(canonical_dag_json_bytes(result)) > limits.max_fact_bytes:
        raise StreamingAnalysisError("assembled_state_budget", phase="assembly", limit=limits.max_fact_bytes)
    return result


def _worker_main():
    """Trusted analyzer process entrypoint; input bytes never become Python code."""
    import resource
    try:
        header = json.loads(sys.stdin.buffer.readline(4097))
        source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        if source_hash != header["expected_worker_source_sha256"]:
            raise StreamingAnalysisError("worker_source_profile_changed")
        limits = StreamingScanLimits(**header["limits"])
        size = header["size_bytes"]
        if type(size) is not int or not 0 <= size <= MAX_FACT_BYTES:
            raise StreamingAnalysisError("worker_input_limit")
        raw = sys.stdin.buffer.read(size + 1)
        if len(raw) != size:
            raise StreamingAnalysisError("worker_input_size")
        facts = (_analyze_one(raw, header, limits) if header["operation"] == "analysis"
                 else _assemble(json.loads(raw), limits) if header["operation"] == "assembly" else None)
        if facts is None:
            raise StreamingAnalysisError("unknown_worker_operation")
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != source_hash:
            raise StreamingAnalysisError("worker_source_profile_changed")
        result = {"schema": WORKER_SCHEMA, "facts": facts,
                  "resources": {"worker_source_sha256": source_hash, "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                                "address_space_limit_bytes": resource.getrlimit(resource.RLIMIT_AS)[0],
                                "cpu_limit_seconds": resource.getrlimit(resource.RLIMIT_CPU)[0]}}
    except StreamingAnalysisError as exc:
        result = {"schema": WORKER_SCHEMA, "error": exc.observation()}
    except (MemoryError, RecursionError):
        result = {"schema": WORKER_SCHEMA, "error": StreamingAnalysisError("analysis_resource_limit").observation()}
    except Exception as exc:
        result = {"schema": WORKER_SCHEMA, "error": StreamingAnalysisError("analysis_failure_" + type(exc).__name__).observation()}
    sys.stdout.buffer.write(canonical_dag_json_bytes(result))


@dataclass(frozen=True)
class StreamingChunkedScan:
    projection: ChunkedProjection
    state: RepositoryState
    observation: dict


def scan_chunked_repository_streaming(repository, chunked, *, max_file_bytes=MAX_MATERIALIZED_FILE_BYTES,
                                      limits=StreamingScanLimits(),
                                      decoder_profile=DEFAULT_DECODER_PROFILE, decoder_budget=DEFAULT_DECODER_BUDGET):
    """Consume every committed blob while retaining only one file's bytes.

    Metadata admission precedes content use. All content identities and source
    fences must verify before the aggregate state escapes. This is an explicit
    cold path; it neither changes nor invokes the legacy retained-byte scanner.
    """
    if not isinstance(limits, StreamingScanLimits) or not isinstance(chunked, ChunkedRepositorySnapshot):
        raise StreamingAnalysisError("typed_limits_and_manifest_required", phase="admission")
    if type(max_file_bytes) is not int or not 1 <= max_file_bytes <= MAX_MATERIALIZED_FILE_BYTES:
        raise StreamingAnalysisError("fixed_file_limit", phase="admission")
    if sys.platform != "linux":
        raise StreamingAnalysisError("unsupported_analysis_platform", phase="admission")
    decoder = require_decoder_profile(chunked.decoder_profile, decoder_profile, decoder_budget)
    root = Path(repository).resolve(strict=True)
    manifest_cid, blocks = chunked.manifest_blocks()
    chunked = admit_chunked_snapshot_manifest(root, manifest_cid, blocks, repository_id=chunked.repository_id,
        expected_commit=chunked.git_commit, expected_tree=chunked.git_tree, limits=chunked.limits,
        decoder_profile=decoder, decoder_budget=decoder_budget)
    before = _fence(root, chunked.git_commit, chunked.git_tree, chunked.limits.max_metadata_bytes)
    profile = analysis_process_profile()
    members = defaultdict(list)
    for member in chunked.entries:
        members[member.git_object_oid].append(member)
    entries, files, artifacts = [], [], []
    total_facts, ordinary_bytes, peak_source, peak_worker_rss, worker_count = 0, 0, 0, 0, 0
    def add_artifact(artifact):
        nonlocal total_facts
        wire = canonical_dag_json_bytes(artifact.to_dict())
        if len(wire) > limits.max_record_bytes:
            raise StreamingAnalysisError("semantic_record_frame", phase="projection", limit=limits.max_record_bytes)
        total_facts += len(wire)
        if total_facts > limits.max_fact_bytes:
            raise StreamingAnalysisError("aggregate_fact_budget", limit=limits.max_fact_bytes, observed=total_facts)
        artifacts.append(artifact.to_dict())

    def remember(entry, data):
        nonlocal total_facts, ordinary_bytes, peak_worker_rss, worker_count
        entries.append(replace(entry, captured_bytes=None))
        if entry.is_opaque:
            add_artifact(_opaque_artifact(entry, entry.opaque_reason or "opaque_snapshot"))
        elif _artifact_path(entry) != entry.path:
            add_artifact(_opaque_artifact(entry, "raw_path_not_model_safe"))
        elif entry.kind not in {"python", "pytest-config"}:
            add_artifact(_typed_artifact(entry))
        else:
            facts, measurement = _run_worker({"operation": "analysis", "path": entry.path,
                "expected_worker_source_sha256": profile["worker_source_sha256"],
                "repository_id": chunked.repository_id, "source_cid": entry.source_cid, "kind": entry.kind},
                data, limits, output_limit=limits.max_file_fact_bytes + 4096)
            if facts["path"] != entry.path or facts["source_cid"] != entry.source_cid:
                raise StreamingAnalysisError("worker_source_identity", path=entry.path)
            wire = canonical_dag_json_bytes(facts)
            total_facts += len(wire)
            if total_facts > limits.max_fact_bytes:
                raise StreamingAnalysisError("aggregate_fact_budget", limit=limits.max_fact_bytes, observed=total_facts)
            files.append(wire)
            ordinary_bytes += len(data)
            peak_worker_rss = max(peak_worker_rss, measurement["peak_rss_bytes"])
            worker_count += 1
    for blob in chunked.blobs:
        capture = any(item.git_mode in {"100644", "100755"} and item.size_bytes <= max_file_bytes
                      and not _malformed_raw(bytes.fromhex(item.raw_path_hex)) for item in members[blob.git_object_oid])
        observed, data = _hash_blob(root, blob.git_object_oid, blob.size_bytes, chunked.limits.frame_bytes, capture=capture,
                                    decoder_profile=decoder)
        if observed != blob:
            raise StreamingAnalysisError("committed_content_mismatch", phase="projection")
        peak_source = max(peak_source, len(data) if data is not None else 0)
        for member in members[blob.git_object_oid]:
            raw = bytes.fromhex(member.raw_path_hex)
            reason = ("malformed_path" if _malformed_raw(raw) else
                      "symlink_or_nonregular" if member.git_mode == "120000" else
                      "analysis_budget_exceeded" if member.size_bytes > max_file_bytes else None)
            entry = (SnapshotEntry(member.path, "opaque", member.size_bytes, blob.source_cid, reason,
                                   member.raw_path_hex, member.git_object_oid, "git-object", "clean", member.git_object_oid)
                     if reason else _entry(member.path, raw, data, max_file_bytes, member.git_object_oid,
                                           disposition="clean", head_oid=member.git_object_oid, acquisition="git-object"))
            remember(entry, data)
            del entry
        del data
    for member in chunked.entries:
        if member.object_type != "blob":
            remember(_opaque(member.path, "symlink_or_nonregular", None, raw=bytes.fromhex(member.raw_path_hex),
                             oid=member.git_object_oid, disposition="clean", head_oid=member.git_object_oid), None)
    snapshot = RepositorySnapshot(chunked.repository_id, tuple(entries), "git-clean", max_file_bytes,
                                   chunked.limits.max_entries, chunked.git_tree, chunked.git_commit, ())
    evidence = page_snapshot_evidence(snapshot, manifest_cid, max_metadata_bytes=chunked.limits.max_metadata_bytes)
    add_artifact(evidence.artifact())
    prefix = canonical_dag_json_bytes({"repository_id": chunked.repository_id, "artifacts": artifacts})
    # Individual facts were already canonical. Join their bytes without decoding
    # and retaining every file's normalized AST in this parent process.
    assembly = prefix[:-1] + b',"files":[' + b','.join(files) + b']}'
    if len(assembly) > limits.max_fact_bytes:
        raise StreamingAnalysisError("aggregate_fact_budget", phase="assembly", limit=limits.max_fact_bytes, observed=len(assembly))
    del files
    state, measurement = _run_worker({"operation": "assembly",
                "expected_worker_source_sha256": profile["worker_source_sha256"]}, assembly, limits,
                                     output_limit=limits.max_fact_bytes + 4096)
    del assembly
    peak_worker_rss = max(peak_worker_rss, measurement["peak_rss_bytes"])
    if _fence(root, chunked.git_commit, chunked.git_tree, chunked.limits.max_metadata_bytes) != before:
        raise StreamingAnalysisError("source_changed_during_analysis", phase="projection")
    if analysis_process_profile() != profile:
        raise StreamingAnalysisError("worker_source_profile_changed", phase="assembly")
    result = RepositoryState.from_dict(state)
    observation = {"schema": "ipfs-datasets.streaming-chunked-scan@1", "entry_count": len(entries),
        "ordinary_source_bytes_submitted": ordinary_bytes,
        "unique_blob_bytes_verified": sum(blob.size_bytes for blob in chunked.blobs),
        "peak_captured_blob_bytes": peak_source, "retained_snapshot_source_bytes": 0,
        "accumulated_file_fact_bytes": total_facts, "worker_count": worker_count + 1,
        "peak_worker_rss_bytes": peak_worker_rss, "analysis_process_profile": profile,
        "limits": asdict(limits), "complete_analysis_authority": False, "completion_authority": False}
    if decoder != DEFAULT_DECODER_PROFILE or decoder_budget != DEFAULT_DECODER_BUDGET:
        observation.update(git_decoder_profile=decoder.payload(),
                           git_decoder_budget=asdict(decoder_budget))
    return StreamingChunkedScan(ChunkedProjection(snapshot, manifest_cid,
                observation["unique_blob_bytes_verified"], 0), result, observation)


__all__ = ["StreamingScanLimits", "StreamingAnalysisError", "StreamingChunkedScan",
           "analysis_process_profile", "scan_chunked_repository_streaming"]
