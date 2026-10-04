"""Closed source correspondence and native bounded integer-checker qualification."""
from dataclasses import replace
from pathlib import Path
import shutil
import threading

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_integer_profile as profile
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

SOURCE = b"def increment(n: int) -> int:\n    return n + 1\n"


def compile_source(source=SOURCE, offset=1):
    return profile.compile_integer_offset(source, profile.IntegerOffsetContract(
        "counter.py", "increment", "n", offset), revision="snapshot:fixture")


@pytest.fixture
def admitted(tmp_path):
    healthy = ProofHostResources(8, 8192, 8192)
    pressure = [healthy]
    owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json", proof_resource_sampler=lambda: pressure[0],
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=0.005,
        proof_backoff_seconds=0.02,
    ))
    with owner.acquire("orchestration", cpu_slots=1, memory_mb=1024,
                       child_process_slots=1, timeout=0) as parent:
        yield owner, parent, pressure, healthy
        assert owner.snapshot()["active_lease_count"] == 1
        assert owner.snapshot()["waiting_request_count"] == 0
    assert owner.snapshot()["active_lease_count"] == 0


@pytest.mark.parametrize("field,value", [
    ("path", "../counter.py"), ("path", "/counter.py"), ("path", "a//counter.py"),
    ("path", "./counter.py"), ("path", "counter.py\n"), ("path", "counter.js"),
    ("function_name", "def"), ("function_name", "f()"), ("parameter", "result"),
    ("parameter", "increment"), ("offset", True), ("offset", 1.0), ("offset", 2**64),
])
def test_contract_rejects_unbound_or_ambiguous_fields(field, value):
    arguments = dict(path="counter.py", function_name="increment", parameter="n", offset=1)
    arguments[field] = value
    with pytest.raises(profile.IntegerProfileError):
        profile.IntegerOffsetContract(**arguments)


def test_contract_and_compilation_are_stable_complete_content_identities():
    compiled = compile_source()
    contract = compiled.contract
    assert profile.IntegerOffsetContract.from_dict(contract.to_dict()) == contract
    assert contract.cid == cid_for_structured(contract.to_dict())
    assert replace(contract, offset=2).cid != contract.cid
    assert compile_source().to_dict() == compiled.to_dict()
    assert compiled.cid == cid_for_structured(compiled.to_dict())
    assert compiled.source_cid != compile_source(SOURCE + b"# exact bytes differ\n").source_cid
    assert compiled.cid != compile_source(offset=2).cid
    assert compiled.body_offset == 1
    assert not compiled.pipeline.proved and not compiled.pipeline.disproved
    assert all(not item.solver_executed for item in compiled.pipeline.obligation_results)
    assert not compiled.to_dict()["kernel_checked"] and not compiled.to_dict()["behavior_authority"]
    assert "do not enforce" in compiled.to_dict()["assumptions"][0]
    for addition in ({"extra": 1}, {"profile": "another-profile"}, {"schema": "other"}):
        with pytest.raises(profile.IntegerProfileError):
            profile.IntegerOffsetContract.from_dict({**contract.to_dict(), **addition})


@pytest.mark.parametrize("source", [
    b"def increment(n):\n    return n + 1\n",
    b"def increment(n: integer) -> int:\n    return n + 1\n",
    b"def increment(n: 'int') -> int:\n    return n + 1\n",
    b"def increment(n: bool) -> int:\n    return n + 1\n",
    b"def increment(n: int = side_effect()) -> int:\n    return n + 1\n",
    b"def increment(n: int = 1) -> int:\n    return n + 1\n",
    b"@decorator\ndef increment(n: int) -> int:\n    return n + 1\n",
    b"async def increment(n: int) -> int:\n    return n + 1\n",
    b"def increment(n: int, /) -> int:\n    return n + 1\n",
    b"def increment(*, n: int) -> int:\n    return n + 1\n",
    b"import dependency\n" + SOURCE,
    SOURCE + b"def other():\n    return 1\n",
    b"def increment(n: int) -> int:\n    x = n + 1\n    return x\n",
    b"def increment(n: int) -> int:\n    return callback(n)\n",
    b"def increment(n: int) -> int:\n    return global_value\n",
    b"def increment(n: int) -> int:\n    return n + True\n",
    b"def increment(n: int) -> int:\n    return n * 1\n",
    b"def increment(n: int) -> int:\n    return 1 + n\n",
    b"def increment(n: int) -> int:\n    return n + (1 + 1)\n",
    b"def increment(n: int) -> int:\n    return n + 18446744073709551616\n",
    b"def increment(n: int) -> int:\n    return n\n    return n + 1\n",
    SOURCE.replace(b"\n", b"\r\n"), SOURCE + b"# non-ascii \xc3\xa9\n", b"#" * 65537,
])
def test_unsupported_source_cannot_reach_pipeline(source, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("unsupported source reached the native pipeline")
    monkeypatch.setattr(profile.SourceToVerificationPipeline, "run", forbidden)
    with pytest.raises(profile.UnsupportedIntegerProfile):
        compile_source(source)


@pytest.mark.parametrize("mutation", ["body", "goal", "assumption", "source_binding"])
def test_mutated_native_translation_fails_source_correspondence(monkeypatch, mutation):
    original = profile.SourceToVerificationPipeline.run
    def changed(*args, **kwargs):
        pipeline = original(*args, **kwargs)
        item = pipeline.obligation_results[0]
        obligation = item.smt_obligation
        if mutation == "body":
            assumption = replace(obligation.assumptions[0], formula=profile.term_eq(profile.term_int(1), profile.term_int(1)))
            obligation = replace(obligation, assumptions=(assumption,))
        elif mutation == "goal":
            obligation = replace(obligation, goal=profile.term_eq(profile.term_int(1), profile.term_int(1)))
        elif mutation == "assumption":
            obligation = replace(obligation, assumptions=(*obligation.assumptions, obligation.assumptions[0]))
        else:
            return replace(pipeline, bindings=replace(pipeline.bindings,
                source=replace(pipeline.bindings.source, content_sha256="0" * 64)))
        return replace(pipeline, obligation_results=(replace(item, smt_obligation=obligation),))
    monkeypatch.setattr(profile.SourceToVerificationPipeline, "run", changed)
    with pytest.raises(profile.IntegerProfileError):
        compile_source()


NATIVE = pytest.mark.skipif(not shutil.which("z3") or not shutil.which("cvc5"), reason="native Z3/CVC5 unavailable")


@NATIVE
@pytest.mark.parametrize("body,offset,expected", [
    ("n + 1", 1, "proved"), ("n + 1", 2, "refuted"),
    ("n - 2", -2, "proved"), ("n + -2", -2, "proved"),
    ("n - -2", 2, "proved"), ("n", 0, "proved"),
    ("n + 18446744073709551615", 18446744073709551615, "proved"),
])
def test_both_native_checkers_execute_under_shared_bounded_children(admitted, monkeypatch, body, offset, expected):
    owner, parent, _, _ = admitted
    original = profile.run_bounded_stdin_tool
    calls = []
    allocated = owner.snapshot()["allocated"]
    def observed(arguments, source, **kwargs):
        state = owner.snapshot()
        assert state["active_root_lease_count"] == 1 and state["active_lease_count"] == 2
        assert state["allocated"] == allocated
        limits = kwargs["limits"]
        assert limits.memory_bytes == limits.resident_memory_bytes == 256 * 1024 * 1024
        assert limits.max_input_bytes == limits.max_output_bytes == 65536
        assert 0 < limits.timeout_seconds <= 10
        calls.append(tuple(arguments))
        return original(arguments, source, **kwargs)
    monkeypatch.setattr(profile, "run_bounded_stdin_tool", observed)
    compiled = compile_source(f"def increment(n: int) -> int:\n    return {body}\n".encode(), offset)
    result = profile.execute_integer_offset(compiled, parent_lease=parent)
    assert result["status"] == expected, result
    assert {item["solver"] for item in result["solvers"]} == {"z3", "cvc5"}
    assert all(item["status"] == expected and item["version"] and len(item["executable_sha256"]) == 64
               and item["workspace_cleaned"] for item in result["solvers"])
    assert len(calls) == (6 if expected == "refuted" else 4)
    for call in calls:
        with Path(call[0]).open("rb") as stream:
            assert stream.read(4) == b"\x7fELF"
    if expected == "refuted":
        assert all(item["model_text"] for item in result["solvers"])
        assert not result["model_checked_against_runtime"]
    assert not result["kernel_checked"] and not result["behavior_authority"]
    assert result["compiled_cid"] == compiled.cid
    assert result["checker_identity"]["source_sha256"]
    assert cid_for_structured(result)


@NATIVE
def test_repeated_execution_is_fresh_with_stable_checker_identity(admitted, monkeypatch):
    _, parent, _, _ = admitted
    compiled = compile_source()
    original = profile.run_bounded_stdin_tool
    calls = []
    def observed(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(profile, "run_bounded_stdin_tool", observed)
    first = profile.execute_integer_offset(compiled, parent_lease=parent)
    second = profile.execute_integer_offset(compiled, parent_lease=parent)
    assert first["status"] == second["status"] == "proved"
    assert first["checker_identity"] == second["checker_identity"]
    assert first["bounds"] == second["bounds"]
    assert len(calls) == 8


@pytest.mark.parametrize("field", ["body_offset", "boolean_body_offset", "source_cid", "contract", "pipeline", "pipeline_boolean"])
def test_changed_compilation_cannot_reach_a_checker(admitted, monkeypatch, field):
    _, parent, _, _ = admitted
    original = compile_source()
    value = {"body_offset": 2, "boolean_body_offset": True, "source_cid": "changed", "contract": replace(original.contract, offset=2),
             "pipeline": replace(original.pipeline, diagnostics=("fabricated",)),
             "pipeline_boolean": replace(original.pipeline, obligation_results=(
                 replace(original.pipeline.obligation_results[0], solver_executed=0),))}[field]
    if field == "boolean_body_offset":
        field = "body_offset"
    if field == "pipeline_boolean":
        field = "pipeline"
    compiled = replace(original, **{field: value})
    monkeypatch.setattr(profile, "run_bounded_stdin_tool", lambda *args, **kwargs: pytest.fail("tampered compilation executed"))
    with pytest.raises(profile.IntegerProfileError, match="changed after"):
        profile.execute_integer_offset(compiled, parent_lease=parent)


def test_external_pressure_blocks_every_native_child(admitted, monkeypatch):
    owner, parent, pressure, healthy = admitted
    pressure[0] = replace(healthy, memory_stall_percent=10)
    monkeypatch.setattr(profile, "run_bounded_stdin_tool", lambda *args, **kwargs: pytest.fail("checker ran during pressure"))
    result = profile.execute_integer_offset(compile_source(), parent_lease=parent, timeout_seconds=0.05)
    assert result["status"] == "timeout"
    assert owner.snapshot()["active_lease_count"] == 1


def test_cancelled_parent_prevents_all_native_execution(admitted, monkeypatch):
    _, parent, _, _ = admitted
    parent.cancel()
    monkeypatch.setattr(profile, "run_bounded_stdin_tool", lambda *args, **kwargs: pytest.fail("cancelled checker executed"))
    with pytest.raises(schedulers.LeaseCancelledError):
        profile.execute_integer_offset(compile_source(), parent_lease=parent)


@NATIVE
def test_cancellation_after_native_probe_releases_only_owned_child(admitted, monkeypatch):
    _, parent, _, _ = admitted
    event = threading.Event()
    original = profile.run_bounded_stdin_tool
    calls = []
    def cancel_after_run(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        event.set()
        return result
    monkeypatch.setattr(profile, "run_bounded_stdin_tool", cancel_after_run)
    with pytest.raises(schedulers.LeaseCancelledError):
        profile.execute_integer_offset(compile_source(), parent_lease=parent, cancel_event=event)
    assert calls == [1]


def test_unavailable_checkers_cannot_be_proofs(admitted, monkeypatch):
    _, parent, _, _ = admitted
    monkeypatch.setattr(profile.shutil, "which", lambda _: None)
    result = profile.execute_integer_offset(compile_source(), parent_lease=parent)
    assert result["status"] == "unavailable"
    assert all(item["status"] == "unavailable" for item in result["solvers"])


@NATIVE
@pytest.mark.parametrize("corruption", ["multiple_verdicts", "output_truncated", "resource_exhausted"])
def test_solver_output_failures_never_become_agreement(admitted, monkeypatch, corruption):
    _, parent, _, _ = admitted
    original = profile.run_bounded_stdin_tool
    def corrupt(*args, **kwargs):
        raw = original(*args, **kwargs)
        if "(check-sat)" in args[1]:
            return replace(raw, **({"stdout": "sat\nunsat\n"} if corruption == "multiple_verdicts" else {corruption: True}))
        return raw
    monkeypatch.setattr(profile, "run_bounded_stdin_tool", corrupt)
    result = profile.execute_integer_offset(compile_source(), parent_lease=parent)
    assert result["status"] == "error"
    assert all(item["status"] == "error" for item in result["solvers"])


@NATIVE
@pytest.mark.parametrize("outcome", ["unknown", "disagreement"])
def test_inconclusive_native_observations_never_become_proofs(admitted, monkeypatch, outcome):
    _, parent, _, _ = admitted
    original = profile.run_bounded_stdin_tool
    def replace_verdict(*args, **kwargs):
        raw = original(*args, **kwargs)
        if "(check-sat)" in args[1] and "(get-model)" not in args[1]:
            if outcome == "unknown":
                return replace(raw, stdout="unknown\n")
            if "--lang=smt2" in args[0]:
                return replace(raw, stdout="unsat\n")
        return raw
    monkeypatch.setattr(profile, "run_bounded_stdin_tool", replace_verdict)
    result = profile.execute_integer_offset(compile_source(offset=2), parent_lease=parent)
    assert result["status"] == outcome
