"""Exercise the normally selected bundled provider with an in-memory sink only.

No parser, detector, loader, or import path is substituted. Profiling observes
the original functions where the order of side effects matters.
"""
from contextlib import contextmanager
import hashlib
import importlib
import inspect
from pathlib import Path
import subprocess
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

from ipfs_datasets_py.logic import software_verification as public
from ipfs_datasets_py.logic.software_verification import pipeline, source_adapters
from ipfs_datasets_py.logic.backends import process, resource_admission
from ipfs_datasets_py.logic.backends.smt import operation_budget


ROOT = Path(__file__).resolve().parents[4]
PROVIDER_PATH = ROOT / "ipfs_accelerate_py/ipfs_accelerate_py/agent_supervisor/analysis/program_ast_adapters.py"
PROVIDER_NAME = "ipfs_accelerate_py.agent_supervisor.analysis.program_ast_adapters"
SINK_NAME = "ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index"
SOURCE = "# exact source: λ\ndef successor(x: int) -> int:\n    return x + 1\n"
PATH = "src/successor.py"
REVISION = "revision:bundled-mirror-fixture"
OMITTED = object()
ROUTES = ("adapter", "object", "pipeline", "pipeline-helper", "public", "public-helper")


@pytest.fixture(autouse=True)
def deny_external_effects(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("bundled-provider fixtures must not launch processes or use the shared pool")
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", denied)
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", denied)


@pytest.fixture
def bundled(monkeypatch):
    calls = []
    sink = ModuleType(SINK_NAME)
    sink.mirror_work_record = lambda **record: calls.append(record)
    monkeypatch.setitem(sys.modules, SINK_NAME, sink)
    provider = importlib.import_module(PROVIDER_NAME)
    assert Path(provider.__file__).resolve() == PROVIDER_PATH
    assert Path(provider.adapt_program_source.__code__.co_filename).resolve() == PROVIDER_PATH
    actual, detector = source_adapters._load_program_ast_adapter()
    assert actual is provider.adapt_program_source
    assert detector is provider.detect_program_language
    return provider, calls, sink


@contextmanager
def observe(*callbacks):
    """Observe original callback entry without changing callable identities."""
    selected = {callback.__code__: callback.__name__ for callback in callbacks}
    calls = []
    old = sys.getprofile()
    def profile(frame, event, arg):
        if event == "call" and frame.f_code in selected:
            calls.append(selected[frame.f_code])
    sys.setprofile(profile)
    try:
        yield calls
    finally:
        sys.setprofile(old)


def invoke(route, mirror=OMITTED, *, include_supervisor_evidence=True, **controls):
    options = {"path": PATH, "language": "python", "revision": REVISION}
    if mirror is not OMITTED:
        options["mirror"] = mirror
    if route == "adapter":
        return source_adapters.adapt_source_to_software_verification(SOURCE,
            preserve_type_annotations=True, include_supervisor_evidence=include_supervisor_evidence, **options)
    if route == "object":
        return source_adapters.SourceSoftwareVerificationAdapter(preserve_type_annotations=True,
            include_supervisor_evidence=include_supervisor_evidence).adapt(SOURCE, **options)
    module = public if route.startswith("public") else pipeline
    configuration = {"execute_solvers": False, "include_supervisor_evidence": include_supervisor_evidence,
                     **controls}
    contracts = [pipeline.ContractSpec("successor", postconditions=("result == x + 1",),
                                      contract_id="contract:bundled-mirror")]
    if route.endswith("helper"):
        return module.run_source_to_verification_pipeline(SOURCE, contracts=contracts, **configuration, **options)
    return module.SourceToVerificationPipeline(**configuration).run(SOURCE, contracts=contracts, **options)


BRANCHES = [
    pytest.param(SOURCE, {"path": PATH}, "success", "python", id="python"),
    pytest.param("export function next(x) { return x + 1; }", {"path": "next.js"}, "success", "javascript", id="javascript"),
    pytest.param("export function next(x: number): number { return x + 1; }", {"path": "next.ts"}, "success", "typescript", id="typescript"),
    pytest.param('{"name": "λ", "count": 1}', {"path": "value.json"}, "success", "json", id="json"),
    pytest.param('{"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}',
                 {"path": "value.json", "language": "json-schema"}, "success", "json-schema", id="json-schema"),
    pytest.param('{"name": "fixture", "tools": [{"name": "read", "inputSchema": {"type": "object"}}]}',
                 {"path": "mcp.json", "language": "mcp-manifest"}, "success", "mcp-manifest", id="mcp"),
    pytest.param("# Contract\nClients MUST retain source identity.\n", {"path": "contract.md"}, "success", "markdown", id="markdown"),
    pytest.param("def broken(:\n", {"path": "broken.py"}, "malformed", "python", id="malformed-python"),
    pytest.param("function broken( {", {"path": "broken.js"}, "malformed", "javascript", id="malformed-js"),
    pytest.param('{"broken":', {"path": "broken.json"}, "malformed", "json", id="malformed-json"),
    pytest.param("λ = 1\n", {"path": "large.py", "max_source_bytes": 1}, "unsupported", "python", id="size-bound"),
    pytest.param("fn main() {}", {"path": "main.rs"}, "unsupported", "unknown", id="unsupported"),
    pytest.param('{"a": 1, "b": 2, "c": 3}', {"path": "facts.json", "max_facts": 1}, "partial", "json", id="fact-bound-json"),
    pytest.param("import os\nimport sys\nvalue = os.getcwd()\n", {"path": "facts.py", "max_facts": 1}, "partial", "python", id="fact-bound-python"),
]


@pytest.mark.parametrize("text,arguments,status,language", BRANCHES)
def test_all_parser_return_paths_keep_complete_evidence_and_only_requested_sink(bundled, text, arguments, status, language):
    provider, calls, _ = bundled
    observations = []
    for mode in (OMITTED, True, False):
        calls.clear()
        with observe(provider._mirror_program_ast) as mirrored:
            value = provider.adapt_program_source(text, **arguments,
                **({} if mode is OMITTED else {"mirror": mode}))
        observations.append(value.to_dict())
        assert value.status == status
        assert value.language == language
        assert value.source_sha256 == "sha256:" + hashlib.sha256(text.encode()).hexdigest()
        assert len(calls) == int(mode is not False)
        assert len(mirrored) == int(mode is not False)
        if calls:
            assert calls[0]["record_ref"] == value.blob_identity
            assert calls[0]["subject_ref"] == arguments["path"]
            assert calls[0]["paths"] == (arguments["path"],)
        if status == "partial":
            assert len(value.facts) == 1
            assert any(item.code == "fact_bound_exceeded" for item in value.diagnostics)
    assert observations[0] == observations[1] == observations[2]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("mode", [OMITTED, True, False], ids=["default", "enabled", "disabled"])
def test_six_normal_public_routes_use_bundled_provider_without_injection(bundled, route, mode):
    provider, calls, _ = bundled
    with observe(provider.adapt_program_source, provider._mirror_program_ast) as entered:
        result = invoke(route, mode)
    adapter = result if route in {"adapter", "object"} else result.adapter
    assert entered.count("adapt_program_source") == 1
    assert entered.count("_mirror_program_ast") == int(mode is not False)
    assert len(calls) == int(mode is not False)
    assert adapter.evidence.status == "success"
    assert adapter.program is not None
    assert adapter.program.sources[0].content_sha256 == hashlib.sha256(SOURCE.encode()).hexdigest()
    if route not in {"adapter", "object"}:
        assert result.obligation_results and result.bindings.translation_receipt_ids
        assert not result.proved and not result.disproved
        assert all(item.differential is None for item in result.obligation_results)


@pytest.mark.parametrize("route", ROUTES)
def test_public_semantic_wire_and_source_proof_identities_ignore_mirror(bundled, route):
    _, calls, _ = bundled
    values = [invoke(route, mode) for mode in (OMITTED, True, False)]
    assert values[0].to_dict() == values[1].to_dict() == values[2].to_dict()
    assert len(calls) == 2
    if route not in {"adapter", "object"}:
        assert values[0].bindings.source.path == PATH
        assert values[0].bindings.source.source_revision == REVISION
        assert values[0].bindings.source.content_sha256 == hashlib.sha256(SOURCE.encode()).hexdigest()
        assert values[0].program.program_id == values[2].program.program_id
        assert [item.compilation.script.digest for item in values[0].obligation_results] == [
            item.compilation.script.digest for item in values[2].obligation_results]


@pytest.mark.parametrize("invalid", [None, 0, 1, "false", object()], ids=["none", "zero", "one", "text", "object"])
def test_provider_exact_boolean_precedes_source_bounds_hash_and_detector(bundled, invalid):
    provider, calls, _ = bundled
    with observe(provider.detect_program_language, provider._source_sha256,
                 provider._positive_limit, provider._mirror_program_ast) as entered:
        with pytest.raises(TypeError, match="program metadata mirroring must be an exact boolean"):
            provider.adapt_program_source(object(), max_source_bytes=0, mirror=invalid)
    assert entered == []
    assert calls == []


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("invalid", [None, 0, 1, "false"], ids=["none", "zero", "one", "text"])
def test_public_exact_boolean_precedes_normal_provider_loading(bundled, route, invalid):
    provider, calls, _ = bundled
    with observe(source_adapters._load_program_ast_adapter, provider.detect_program_language,
                 provider.adapt_program_source) as entered:
        with pytest.raises(ValueError, match="exact boolean"):
            invoke(route, invalid)
    assert entered == []
    assert calls == []


@pytest.mark.parametrize("route", ROUTES)
def test_native_only_never_loads_or_calls_bundled_provider(bundled, route):
    provider, calls, _ = bundled
    with observe(source_adapters._load_program_ast_adapter, provider.detect_program_language,
                 provider.adapt_program_source) as entered:
        values = [invoke(route, mode, include_supervisor_evidence=False).to_dict()
                  for mode in (OMITTED, True, False)]
    assert entered == []
    assert calls == []
    assert values[0] == values[1] == values[2]


@pytest.mark.parametrize("route", ROUTES)
def test_best_effort_sink_failure_preserves_public_semantic_output(bundled, route):
    _, calls, sink = bundled
    baseline = invoke(route, False).to_dict()
    def failed(**record):
        calls.append(record)
        raise OSError("fixture metadata storage unavailable")
    sink.mirror_work_record = failed
    assert invoke(route).to_dict() == baseline
    assert invoke(route, True).to_dict() == baseline
    assert invoke(route, False).to_dict() == baseline
    assert len(calls) == 2


@pytest.mark.parametrize("mode", [True, False])
def test_previous_record_reuse_preserves_identity_and_mirror_policy(bundled, mode):
    provider, calls, _ = bundled
    original = provider.adapt_program_source(SOURCE, path=PATH, mirror=False, generated=True)
    reused = provider.adapt_program_source(SOURCE, path=PATH, previous=original,
                                           mirror=mode, generated=True)
    other = provider.adapt_program_source(SOURCE, path=PATH, previous=original,
                                          mirror=not mode, generated=True)
    assert reused.to_dict() == other.to_dict()
    assert reused.source_sha256 == original.source_sha256
    assert reused.blob_identity == original.blob_identity
    assert reused.ast_record is original.ast_record
    assert reused.generated
    assert len(calls) == 1


def test_normal_diagnostic_reports_bundled_callable_without_parser_or_sink(bundled):
    provider, calls, _ = bundled
    initial_path = tuple(sys.path)
    with observe(provider.detect_program_language, provider.adapt_program_source,
                 provider._mirror_program_ast) as entered:
        diagnostic = source_adapters.inspect_program_ast_provider()
    assert diagnostic["status"] == "supported"
    assert diagnostic["reason"] == "explicit_keyword_parameter"
    assert diagnostic["adapter"]["origin"] == str(PROVIDER_PATH)
    assert diagnostic["adapter"]["module"] == PROVIDER_NAME
    assert entered == calls == []
    assert tuple(sys.path) == initial_path
    assert inspect.signature(provider.adapt_program_source).parameters["mirror"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize("route", ["public", "public-helper"])
def test_precancellation_prevents_normal_loader_and_metadata_sink(bundled, route):
    provider, calls, _ = bundled
    cancellation = threading.Event()
    cancellation.set()
    with observe(source_adapters._load_program_ast_adapter, provider.adapt_program_source) as entered:
        with pytest.raises(operation_budget.ProofOperationCancelled):
            invoke(route, False, cancellation=cancellation)
    assert entered == calls == []


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_best_effort_sink_does_not_hide_late_public_operation_stop(bundled, monkeypatch, stop):
    _, calls, sink = bundled
    cancellation = threading.Event()
    clock = [100.0]
    monkeypatch.setattr(operation_budget, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    def stop_inside_sink(**record):
        calls.append(record)
        if stop == "cancel":
            cancellation.set()
        else:
            clock[0] += 2.0
        raise OSError("ordinary sink failure remains best effort")
    sink.mirror_work_record = stop_inside_sink
    expected = operation_budget.ProofOperationCancelled if stop == "cancel" else operation_budget.ProofOperationTimeout
    with pytest.raises(expected):
        invoke("public", True, cancellation=cancellation, operation_timeout_ms=1000)
    assert len(calls) == 1
