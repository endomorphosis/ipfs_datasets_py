"""Mirroring is an optional side effect, independent of source/proof identity.

The supervisor parser is real, but its metadata sink is an in-memory spy. Native
execution and the shared resource pool are denied unless a test installs its own
private scheduler and synthetic executor.
"""
import hashlib
import importlib
import importlib.util
import inspect
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

from ipfs_datasets_py.logic import software_verification as public
from ipfs_datasets_py.logic.software_verification import admitted_pipeline, pipeline, source_adapters
from ipfs_datasets_py.logic.backends import process, resource_admission
from ipfs_datasets_py.logic.backends.smt import operation_budget
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

SOURCE = "# provenance: λ\ndef successor(x: int) -> int:\n    return x + 1\n"
PATH = "src/successor.py"
REVISION = "revision:mirroring-fixture"
MIB = 1024**2
OMITTED = object()
ROUTES = ("adapter", "adapter-object", "pipeline", "pipeline-helper", "public", "public-helper")
ROOT = Path(__file__).resolve().parents[4]
REVIEWED_SUPERVISOR = ROOT.parent/"ipfs_accelerate/ipfs_accelerate_py/agent_supervisor/analysis/program_ast_adapters.py"


def bounds():
    return ExecutionBounds(timeout_ms=3000, max_memory_bytes=128*MIB, max_output_bytes=4096)


def contracts():
    return [pipeline.ContractSpec(function_name="successor", postconditions=("result == x + 1",),
                                  contract_id="contract:successor")]


def invoke(route, mirror=OMITTED, *, source=SOURCE, path=PATH, revision=REVISION,
           include_supervisor_evidence=True, **controls):
    arguments = {"path": path, "language": "python", "revision": revision}
    if mirror is not OMITTED:
        arguments["mirror"] = mirror
    if route == "adapter":
        return source_adapters.adapt_source_to_software_verification(source, **arguments,
            include_supervisor_evidence=include_supervisor_evidence, preserve_type_annotations=True)
    if route == "adapter-object":
        return source_adapters.SourceSoftwareVerificationAdapter(
            include_supervisor_evidence=include_supervisor_evidence,
            preserve_type_annotations=True).adapt(source, **arguments)
    options = {"execute_solvers": False, "include_supervisor_evidence": include_supervisor_evidence,
               "bounds": bounds(), **controls}
    module = public if route.startswith("public") else pipeline
    if route.endswith("helper"):
        return module.run_source_to_verification_pipeline(source, contracts=contracts(), **arguments, **options)
    return module.SourceToVerificationPipeline(**options).run(source, contracts=contracts(), **arguments)


@pytest.fixture(autouse=True)
def no_external_effects(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("this fixture must not launch processes or access the shared resource pool")
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", denied)
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", denied)


@pytest.fixture
def supervisor(monkeypatch):
    # The exact lazy import used by _mirror_program_ast is replaced before the
    # parser module is loaded; no real database/index object is constructed.
    sink = ModuleType("ipfs_accelerate_py.agent_supervisor.runtime.supervisor_meta_index")
    calls = []
    sink.mirror_work_record = lambda **record: calls.append(record)
    monkeypatch.setitem(sys.modules, sink.__name__, sink)
    # The working directory also contains an older optional checkout. Exercise
    # the reviewed sibling implementation explicitly, without changing default
    # import selection or claiming that a legacy provider learned this option.
    importlib.import_module("ipfs_accelerate_py.agent_supervisor.analysis")
    name = "ipfs_accelerate_py.agent_supervisor.analysis._source_mirroring_control_fixture"
    spec = importlib.util.spec_from_file_location(name, REVIEWED_SUPERVISOR)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    assert Path(module.adapt_program_source.__code__.co_filename) == REVIEWED_SUPERVISOR
    monkeypatch.setattr(source_adapters, "_load_program_ast_adapter",
                        lambda: (module.adapt_program_source, module.detect_program_language))
    return module, calls, sink


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("mirror", [OMITTED, True, False], ids=["default", "enabled", "disabled"])
def test_all_entrypoints_attempt_only_requested_mirroring(supervisor, route, mirror):
    _, calls, _ = supervisor
    result = invoke(route, mirror)
    adapter = result if route.startswith("adapter") else result.adapter
    assert adapter.evidence is not None and adapter.evidence.status == "success"
    assert adapter.program is not None
    assert adapter.program.sources[0].content_sha256 == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert len(calls) == (mirror is not False)
    if calls:
        assert calls[0]["catalog_kind"] == "ast"
        assert calls[0]["record_kind"] == "program_ast_adapter"
        assert calls[0]["subject_ref"] == PATH
        assert calls[0]["record_ref"] == adapter.evidence.blob_identity
        assert calls[0]["record_ref"] == "sha256:" + hashlib.sha256(SOURCE.encode()).hexdigest()
    if not route.startswith("adapter"):
        assert result.obligation_results and result.bindings.translation_receipt_ids
        assert not result.proved and not result.disproved
        assert all(item.differential is None for item in result.obligation_results)


@pytest.mark.parametrize("route", ROUTES)
def test_mirror_control_never_changes_complete_semantic_wire(supervisor, route):
    _, calls, _ = supervisor
    results = [invoke(route, control) for control in (OMITTED, True, False)]
    assert results[0].to_dict() == results[1].to_dict() == results[2].to_dict()
    assert len(calls) == 2
    if not route.startswith("adapter"):
        for value in results:
            assert value.bindings.source.path == PATH
            assert value.bindings.source.source_revision == REVISION
            assert value.bindings.source.content_sha256 == hashlib.sha256(SOURCE.encode()).hexdigest()
            assert value.program.program_id == results[0].program.program_id
            assert [row.compilation.script.digest for row in value.obligation_results] == [
                row.compilation.script.digest for row in results[0].obligation_results]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("invalid", [None, 0, 1, "false", object()], ids=["none", "zero", "one", "text", "object"])
def test_non_boolean_rejected_before_loading_or_guarding(monkeypatch, route, invalid):
    def denied(*args, **kwargs):
        pytest.fail("invalid mirror control reached a side-effect boundary")
    monkeypatch.setattr(source_adapters, "_load_program_ast_adapter", denied)
    monkeypatch.setattr(source_adapters, "_adapt_python", denied)
    monkeypatch.setattr(admitted_pipeline, "_guard_compiler", denied)
    monkeypatch.setattr(admitted_pipeline, "_guard_backend", denied)
    error = source_adapters.SourceAdapterError if route.startswith("adapter") else pipeline.PipelineError
    with pytest.raises(error, match="exact boolean"):
        invoke(route, invalid)


@pytest.mark.parametrize("route", ROUTES)
def test_invalid_bool_stays_invalid_with_supervisor_evidence_disabled(monkeypatch, route):
    monkeypatch.setattr(source_adapters, "_load_program_ast_adapter", lambda: pytest.fail("optional import"))
    error = source_adapters.SourceAdapterError if route.startswith("adapter") else pipeline.PipelineError
    with pytest.raises(error, match="exact boolean"):
        invoke(route, 0, include_supervisor_evidence=False)


@pytest.mark.parametrize("route", ROUTES)
def test_legacy_supervisor_default_works_but_disabled_mirroring_never_retries(monkeypatch, route):
    calls = []
    def legacy(source, *, path, language, max_source_bytes):
        calls.append((source, path, language, max_source_bytes))
        return SimpleNamespace(language="python")
    monkeypatch.setattr(source_adapters, "_load_program_ast_adapter", lambda: (legacy, lambda path, lang: "python"))
    baseline = invoke(route).to_dict()
    assert invoke(route, True).to_dict() == baseline
    assert len(calls) == 2
    with pytest.raises(TypeError, match="mirror"):
        invoke(route, False)
    assert len(calls) == 2  # Signature rejection happens before the legacy body.


@pytest.mark.parametrize("route", ROUTES)
def test_supervisor_internal_type_error_is_not_retried(monkeypatch, route):
    calls = []
    def failing(source, *, path, language, max_source_bytes, mirror=True):
        calls.append(mirror)
        raise TypeError("parser body failed")
    monkeypatch.setattr(source_adapters, "_load_program_ast_adapter", lambda: (failing, lambda path, lang: "python"))
    with pytest.raises(TypeError, match="parser body failed"):
        invoke(route, False)
    assert calls == [False]


@pytest.mark.parametrize("route", ROUTES)
def test_native_only_does_not_load_optional_supervisor(monkeypatch, route):
    monkeypatch.setattr(source_adapters, "_load_program_ast_adapter", lambda: pytest.fail("optional supervisor loaded"))
    results = [invoke(route, mode, include_supervisor_evidence=False).to_dict() for mode in (OMITTED, True, False)]
    assert results[0] == results[1] == results[2]


@pytest.mark.parametrize("route", ROUTES)
def test_missing_optional_supervisor_preserves_native_lowering(monkeypatch, route):
    monkeypatch.setattr(source_adapters, "_load_program_ast_adapter", lambda: (None, None))
    with_missing = invoke(route, False)
    native_only = invoke(route, False, include_supervisor_evidence=False)
    assert with_missing.to_dict() == native_only.to_dict()
    assert with_missing.program is not None


SUPERVISOR_BRANCHES = [
    pytest.param("x = 1\n", {"path": "valid.py"}, "success", id="success"),
    pytest.param("def broken(:\n", {"path": "broken.py"}, "malformed", id="malformed"),
    pytest.param("x = 1\n", {"path": "large.py", "max_source_bytes": 1}, "unsupported", id="size-bound"),
    pytest.param("fn main() {}", {"path": "main.rs"}, "unsupported", id="unsupported"),
    pytest.param('{"a": 1, "b": 2, "c": 3}', {"path": "facts.json", "max_facts": 1}, "partial", id="fact-bound"),
]


@pytest.mark.parametrize("source,arguments,status", SUPERVISOR_BRANCHES)
def test_real_supervisor_mirror_choice_preserves_every_return_path(supervisor, source, arguments, status):
    module, calls, _ = supervisor
    values = [module.adapt_program_source(source, **arguments, **({} if mode is OMITTED else {"mirror": mode}))
              for mode in (OMITTED, True, False)]
    assert all(value.status == status for value in values)
    assert values[0].to_dict() == values[1].to_dict() == values[2].to_dict()
    assert values[0].source_sha256 == "sha256:" + hashlib.sha256(source.encode()).hexdigest()
    assert len(calls) == 2


@pytest.mark.parametrize("source,arguments,status", SUPERVISOR_BRANCHES)
def test_disabled_real_supervisor_never_enters_mirroring(supervisor, monkeypatch, source, arguments, status):
    module, calls, _ = supervisor
    monkeypatch.setattr(module, "_mirror_program_ast", lambda *args: pytest.fail("disabled mirroring entered sink wrapper"))
    result = module.adapt_program_source(source, mirror=False, **arguments)
    assert result.status == status and calls == []


@pytest.mark.parametrize("invalid", [None, 0, 1, "false", object()], ids=["none", "zero", "one", "text", "object"])
def test_real_supervisor_rejects_invalid_control_before_parser_or_sink(supervisor, monkeypatch, invalid):
    module, calls, _ = supervisor
    monkeypatch.setattr(module, "detect_program_language", lambda *args: pytest.fail("invalid control parsed"))
    with pytest.raises(TypeError, match="exact boolean"):
        module.adapt_program_source(SOURCE, path=PATH, mirror=invalid)
    assert calls == []


def test_enabled_mirroring_remains_best_effort_without_changing_output(supervisor):
    module, calls, sink = supervisor
    expected = module.adapt_program_source(SOURCE, path=PATH, mirror=False)
    def unavailable(**record):
        calls.append(record)
        raise OSError("isolated metadata sink unavailable")
    sink.mirror_work_record = unavailable
    actual = module.adapt_program_source(SOURCE, path=PATH, mirror=True)
    assert actual.to_dict() == expected.to_dict() and len(calls) == 1


def test_explicit_provider_uses_reviewed_source_and_traceable_existing_dependencies(supervisor):
    module, _, _ = supervisor
    assert "mirror" in inspect.signature(module.adapt_program_source).parameters
    assert Path(module.__file__) == REVIEWED_SUPERVISOR
    for value in (module.AnalysisASTIndex, module.ASTBlobRecord, module.validate_cid,
                  module.content_identity, module.RepositoryCorpusIndex):
        dependency = Path(inspect.getfile(value)).resolve()
        assert dependency.is_file()
        assert dependency.is_relative_to(ROOT/"ipfs_accelerate_py") or dependency.is_relative_to(ROOT.parent/"ipfs_accelerate")


@pytest.mark.parametrize("field,changed", [("source", SOURCE.replace("x + 1", "x + 2")),
                                            ("path", "other/successor.py"), ("revision", "revision:other")])
def test_source_identity_changes_for_source_snapshot_changes_only(supervisor, field, changed):
    baseline = invoke("public", False)
    changed_result = invoke("public", False, **{field: changed})
    assert baseline.bindings.source.to_dict() != changed_result.bindings.source.to_dict()
    assert baseline.to_dict() != changed_result.to_dict()
    assert invoke("public", True).to_dict() == baseline.to_dict()


@pytest.mark.parametrize("route", ["public", "public-helper"])
def test_precancellation_prevents_optional_evidence_or_mirroring(supervisor, monkeypatch, route):
    _, calls, _ = supervisor
    token = threading.Event()
    token.set()
    monkeypatch.setattr(source_adapters, "_load_program_ast_adapter", lambda: pytest.fail("cancelled parse"))
    with pytest.raises(operation_budget.ProofOperationCancelled):
        invoke(route, False, cancellation=token)
    assert calls == []


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_late_mirror_callback_cannot_escape_public_operation_gate(supervisor, monkeypatch, stop):
    _, calls, sink = supervisor
    token = threading.Event()
    clock = [100.0]
    monkeypatch.setattr(operation_budget, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    def slow_mirror(**record):
        calls.append(record)
        if stop == "cancel":
            token.set()
        else:
            clock[0] += 2.0
    sink.mirror_work_record = slow_mirror
    expected = operation_budget.ProofOperationCancelled if stop == "cancel" else operation_budget.ProofOperationTimeout
    with pytest.raises(expected):
        invoke("public", True, cancellation=token, operation_timeout_ms=1000)
    assert len(calls) == 1


@pytest.fixture
def private_admission(tmp_path, monkeypatch):
    host = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    scheduler = resource_scheduler.GlobalResourceScheduler(resource_scheduler.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/"mirror-pool.json", proof_resource_sampler=lambda: host,
        total_cpu_slots=2, total_memory_mb=512, total_child_process_slots=2,
        proof_memory_headroom_mb=64, lane_reservations={}, auto_renew_leases=False,
        poll_interval_seconds=.002))
    monkeypatch.setattr(resource_admission, "get_global_resource_scheduler", lambda: scheduler)
    monkeypatch.setattr(shutil, "which", lambda *args, **kwargs: sys.executable)
    phases = []
    def execute(executor, invocation, cancellation=None):
        leases = scheduler.active_leases()
        assert len(leases) == 1
        assert (leases[0]["cpu_slots"], leases[0]["memory_mb"], leases[0]["child_process_slots"]) == (1,128,1)
        assert invocation.limits.memory_bytes == invocation.limits.resident_memory_bytes == 128*MIB
        assert 0 < invocation.limits.timeout_seconds <= 3
        assert not cancellation.is_set()
        text = invocation.stdin or ""
        text = text.decode() if isinstance(text, bytes) else text
        version = any(arg in ("-version", "--version") for arg in invocation.argv)
        phase = "version" if version else "core" if "(get-unsat-core)" in text else "query"
        phases.append((phase, leases[0]["lease_id"]))
        return process.RawProcessResult(returncode=0, stdout="fixture/1\n" if version else "unsat\n()\n" if phase == "core" else "unsat\n")
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    yield scheduler, phases
    final = scheduler.snapshot()
    assert final["active_lease_count"] == final["waiting_request_count"] == 0


@pytest.mark.parametrize("route", ["public", "public-helper"])
@pytest.mark.parametrize("mirror", [True, False], ids=["enabled", "disabled"])
def test_public_execution_keeps_default_native_admission(supervisor, private_admission, route, mirror):
    _, calls, _ = supervisor
    _, phases = private_admission
    result = invoke(route, mirror, execute_solvers=True)
    assert result.proved and not result.disproved
    assert len(calls) == int(mirror)
    assert [phase for phase, _ in phases] == ["query", "core", "version"]*2
    assert len({lease for _, lease in phases}) == 6
    assert result.bindings.source.content_sha256 == hashlib.sha256(SOURCE.encode()).hexdigest()


def test_adapter_object_configuration_and_pipeline_wire_do_not_gain_mirror_field():
    from dataclasses import fields
    assert "mirror" not in {field.name for field in fields(source_adapters.SourceSoftwareVerificationAdapter)}
    assert "mirror" not in {field.name for field in fields(public.SourceToVerificationPipeline)}
    selected = public.SourceToVerificationPipeline(execute_solvers=False, include_supervisor_evidence=False)
    assert "mirror" not in selected.to_dict()


@pytest.mark.parametrize("mirror", [OMITTED, True, False], ids=["default", "enabled", "disabled"])
def test_existing_integer_offset_compiler_forwards_mirroring_without_identity_changes(supervisor, mirror):
    from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as integer
    _, calls, _ = supervisor
    raw = b"def increment(n: int) -> int:\n    return n + 1\n"
    contract = integer.IntegerOffsetContract("counter.py", "increment", "n", 1)
    expected = integer.compile_integer_offset(raw, contract, revision=REVISION, mirror=False)
    assert calls == []
    actual = integer.compile_integer_offset(raw, contract, revision=REVISION,
        **({} if mirror is OMITTED else {"mirror": mirror}))
    assert actual.to_dict() == expected.to_dict() and actual.cid == expected.cid
    assert len(calls) == (mirror is not False)
    assert actual.pipeline.bindings.source.content_sha256 == hashlib.sha256(raw).hexdigest()
    assert not actual.pipeline.proved and not actual.pipeline.disproved


@pytest.mark.parametrize("invalid", [None, 0, 1, "false", object()], ids=["none", "zero", "one", "text", "object"])
def test_existing_integer_offset_compiler_rejects_invalid_control_before_source_work(monkeypatch, invalid):
    from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as integer
    monkeypatch.setattr(integer, "_guard", lambda *args: pytest.fail("invalid mirror parsed source"))
    monkeypatch.setattr(source_adapters, "_load_program_ast_adapter", lambda: pytest.fail("invalid mirror loaded supervisor"))
    with pytest.raises(integer.IntegerProfileError, match="exact boolean"):
        integer.compile_integer_offset(b"not evaluated", object(), revision=REVISION, mirror=invalid)


def test_closed_profile_compile_only_configuration_keeps_supervisor_disabled(monkeypatch):
    monkeypatch.setattr(source_adapters, "_load_program_ast_adapter", lambda: pytest.fail("closed profile loaded supervisor"))
    # This is the constructor configuration used by the closed producer and
    # replay paths; complete receipt/cache replay is qualified separately.
    selected = pipeline.SourceToVerificationPipeline(
        bounds=bounds(), execute_solvers=False, include_supervisor_evidence=False)
    baseline = selected.run(SOURCE, path=PATH, contracts=contracts(), revision=REVISION)
    for mode in (True, False):
        result = selected.run(SOURCE, path=PATH, contracts=contracts(), revision=REVISION, mirror=mode)
        assert result.to_dict() == baseline.to_dict()
        assert result.adapter.evidence is None and not result.proved and not result.disproved
