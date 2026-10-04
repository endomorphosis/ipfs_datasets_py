"""Native universal Int-model qualification and source/evidence drift refusal."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
from pathlib import Path
import shutil
import threading

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_integer_model_lean as model
from ipfs_datasets_py.logic.software_contracts import codebase_finite_integer_observation as native
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import IntegerOffsetContract, UnsupportedIntegerProfile
from ipfs_datasets_py.logic.software_contracts.codebase_ir import StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError, LeaseTimeoutError
from .test_codebase_current import current_index, scheduler, git

VIEW = "repository:independent-integer-model"
PYTHON = Path("/home/barberb/.local/bin/python").resolve()
LEAN = Path("/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lean")


def source(body="n + 1"):
    return ("def increment(n: int) -> int:\n    return " + body + "\n").encode()


@pytest.fixture(scope="module")
def tools():
    for path in (PYTHON, LEAN):
        assert path.is_file() and path.read_bytes()[:4] == b"\x7fELF", "installed native tools required; no shim/skip"
    return native.seal_finite_integer_tools(python_executable=PYTHON, lean_executable=LEAN)


@pytest.fixture
def prepared(tmp_path, current_index, scheduler):
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Integer Model Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    (root / "calc.py").write_bytes(source())
    git(root, "add", "calc.py")
    git(root, "commit", "-qm", "authored integer offset source")
    index, connection, _ = current_index
    owner, _, _ = scheduler
    head = index.prepare_current(root, repository_id=VIEW, operation_id="initial", expected_head=None, scheduler=owner).head
    return {"index": index, "repository": root, "expected_head": head,
        "scheduler": owner, "output": tmp_path / "model", "connection": connection}


def prove(prepared, tools, **changes):
    options = {key: value for key, value in prepared.items() if key != "connection"}
    options.update(contract=IntegerOffsetContract("calc.py", "increment", "n", 2),
        tool_policy=deepcopy(tools), timeout_seconds=30)
    options.update(changes)
    return model.prove_current_integer_offset_model(**options)


def validate(record, prepared, tools, **changes):
    options = {key: value for key, value in prepared.items() if key not in {"connection", "output"}}
    options.update(contract=IntegerOffsetContract("calc.py", "increment", "n", 2),
        tool_policy=deepcopy(tools), timeout_seconds=30)
    options.update(changes)
    return model.validate_current_integer_offset_model(record, **options)


def recapture(prepared, body):
    (prepared["repository"] / "calc.py").write_bytes(source(body))
    prepared["expected_head"] = prepared["index"].prepare_current(prepared["repository"],
        repository_id=VIEW, operation_id="next", expected_head=prepared["expected_head"],
        scheduler=prepared["scheduler"]).head


def assert_model_only(value):
    assert value["scope"] == "mathematical_integer_operational_model"
    assert all(value[name] is False for name in model._FALSE)
    assert value["translation"]["translation_correspondence_checked"] is True
    assert value["translation"]["translation_correctness_proved"] is False


def test_native_lean_proves_source_model_for_all_int_and_refutes_desired_goal(prepared, tools):
    record = prove(prepared, tools)
    value = record.to_dict()
    assert value["status"] == "model_refuted"
    assert value["source_identity_proved"] is True
    assert value["requested_model_theorem_proved"] is False
    assert value["model_counterexample"] == {"input": 0, "model_output": 1, "required_output": 2}
    assert value["lean_certificate"]["theorems"] == ["source_offset_identity", "requested_offset_counterexample", "requested_goal_refuted"]
    assert value["lean_certificate"]["process"]["command"] == [str(LEAN), "-j", "1", "-o", "IntegerModel.olean", "IntegerModel.lean"]
    assert value["lean_certificate"]["process"]["returncode"] == 0
    text = Path(value["artifacts"]["lean_source"]["path"]).read_text()
    assert "∀ n : Int" in text and "def run" in text and "def eval" in text
    assert "requested_goal_refuted" in text and "sorry" not in text
    translation = value["translation"]
    assert translation["native_program"]["metadata"] == translation["adapter_metadata"]
    assert translation["native_program"]["sources"][0]["metadata"] == translation["source_adapter_metadata"]
    assert translation["source_offset"] == 1 and translation["requested_offset"] == 2
    assert value["source_cid"] == cid_for_bytes(source())
    assert record.cid == cid_for_structured(value)
    assert value["result_cid"] == cid_for_structured({k: v for k, v in value.items() if k != "result_cid"})
    for artifact in value["artifacts"].values():
        raw = Path(artifact["path"]).read_bytes()
        assert artifact["cid"] == cid_for_bytes(raw)
        assert artifact["sha256"] == hashlib.sha256(raw).hexdigest()
        assert prepared["index"].artifacts.get_bytes(artifact["cid"]) == raw
    assert validate(record, prepared, tools) == record
    value["translation"]["adapter_metadata"]["foreign"] = True
    assert "foreign" not in record.to_dict()["translation"]["adapter_metadata"]
    with pytest.raises(FrozenInstanceError):
        record._wire = b"{}"
    assert_model_only(record.to_dict())


@pytest.mark.parametrize("body,desired", [("n + 2", 2), ("n - (-2)", 2), ("n + -2", -2), ("n - 2", -2), ("n", 0), ("n + +2", 2)])
def test_real_source_expressions_compile_and_prove_requested_model(prepared, tools, body, desired):
    recapture(prepared, body)
    contract = IntegerOffsetContract("calc.py", "increment", "n", desired)
    record = prove(prepared, tools, contract=contract)
    value = record.to_dict()
    assert value["status"] == "model_proved"
    assert value["requested_model_theorem_proved"] is value["source_identity_proved"] is True
    assert value["model_counterexample"] is None
    assert value["lean_certificate"]["theorems"] == ["source_offset_identity", "requested_offset_identity"]
    assert validate(record, prepared, tools, contract=contract) == record
    assert_model_only(value)


@pytest.mark.parametrize("bad", [
    b"def increment(n):\n    return n + 1\n",
    b"def increment(n: bool) -> int:\n    return n + 1\n",
    b"def increment(n: int) -> int:\n    return abs(n)\n",
    b"def increment(n: int) -> int:\n    return n / 2\n",
    b"raise AssertionError('executed')\ndef increment(n: int) -> int:\n    return n + 1\n",
])
def test_unsupported_source_cannot_execute_lean_or_return_model_proof(prepared, tools, monkeypatch, bad):
    (prepared["repository"] / "calc.py").write_bytes(bad)
    prepared["expected_head"] = prepared["index"].prepare_current(prepared["repository"],
        repository_id=VIEW, operation_id="unsupported", expected_head=prepared["expected_head"], scheduler=prepared["scheduler"]).head
    monkeypatch.setattr(model.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("unsupported source invoked a tool"))
    with pytest.raises(UnsupportedIntegerProfile):
        prove(prepared, tools)
    assert not prepared["output"].exists()


@pytest.mark.parametrize("damage", ["metadata", "symbol_type", "literal", "effect"])
def test_native_frontend_drift_is_rejected_before_lean(prepared, tools, monkeypatch, damage):
    original = model.compile_integer_offset
    def changed(*args, **kwargs):
        compiled = original(*args, **kwargs)
        from ipfs_datasets_py.logic.software_verification.program import ProgramIR
        payload = compiled.pipeline.program.to_dict()
        payload.pop("program_id")
        if damage == "metadata": payload["metadata"]["foreign_semantics"] = "unreviewed"
        elif damage == "symbol_type": payload["symbols"][0]["type_ref"] = "boolean"
        elif damage == "literal":
            next(row for row in payload["expressions"] if row["kind"] == "literal" and row["type_ref"] == "int")["attributes"]["value"] = 2
        else: payload["functions"][0]["effects"]["performs_io"] = True
        return replace(compiled, pipeline=replace(compiled.pipeline, program=ProgramIR.from_dict(payload)))
    monkeypatch.setattr(model, "compile_integer_offset", changed)
    monkeypatch.setattr(model.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("bad native semantics invoked Lean"))
    with pytest.raises((model.IntegerOffsetModelError, ValueError)):
        prove(prepared, tools)
    assert not prepared["output"].exists()


def test_old_generation_source_and_fresh_successor_are_distinguished(prepared, tools):
    record = prove(prepared, tools)
    recapture(prepared, "n + 2")
    with pytest.raises(model.IntegerOffsetModelError):
        validate(record, prepared, tools)
    successor = prove(prepared, tools, output=prepared["output"].parent / "successor-model")
    assert successor.to_dict()["requested_model_theorem_proved"] is True
    assert successor.to_dict()["head"]["generation"] == record.to_dict()["head"]["generation"] + 1


@pytest.mark.parametrize("boundary", ["lean", "record_cas", "final_observation"])
def test_live_source_or_artifact_drift_withholds_a_returned_record(prepared, tools, monkeypatch, boundary):
    if boundary == "lean":
        original = model.BoundedToolRunner.run
        def changed(self, command, **options):
            raw = original(self, command, **options)
            if "IntegerModel.lean" in command:
                (prepared["repository"] / "calc.py").write_bytes(source("n + 2"))
            return raw
        monkeypatch.setattr(model.BoundedToolRunner, "run", changed)
    elif boundary == "record_cas":
        original = prepared["index"].artifacts.put
        def changed(value):
            cid = original(value)
            if value.get("schema") == model.SCHEMA:
                (prepared["repository"] / "calc.py").write_bytes(source("n + 2"))
            return cid
        monkeypatch.setattr(prepared["index"].artifacts, "put", changed)
    else:
        original = prepared["index"].observe_current
        def changed(*args, **kwargs):
            current = original(*args, **kwargs)
            if (prepared["output"] / "result.json").exists():
                with (prepared["output"] / "IntegerModel.olean").open("ab") as stream:
                    stream.write(b"late artifact mutation")
            return current
        monkeypatch.setattr(prepared["index"], "observe_current", changed)
    with pytest.raises((StaleCodebaseError, model.IntegerOffsetModelError)):
        prove(prepared, tools)


@pytest.mark.parametrize("artifact", ["source", "compiled", "translation", "frontend", "tool_policy", "lean_source", "lean_olean", "lean_process", "lean_certificate"])
def test_cold_read_detects_every_sealed_artifact_mutation(prepared, tools, artifact):
    record = prove(prepared, tools)
    path = Path(record.to_dict()["artifacts"][artifact]["path"])
    with path.open("ab") as stream: stream.write(b"tampered")
    with pytest.raises(model.IntegerOffsetModelError, match="artifact"):
        validate(record, prepared, tools)


def test_private_native_lean_tool_mutation_is_detected_after_actual_invocation(prepared, tools, monkeypatch, tmp_path):
    executable = tmp_path / "private-lean"
    shutil.copyfile(LEAN, executable)
    executable.chmod(0o700)
    policy = native.seal_finite_integer_tools(python_executable=PYTHON, lean_executable=executable)
    original = model.BoundedToolRunner.run
    def changed(self, command, **options):
        raw = original(self, command, **options)
        # The native --version call is genuine; full library layout isn't copied.
        if "--version" in command:
            with executable.open("ab") as stream: stream.write(b"changed native binary")
        return raw
    monkeypatch.setattr(model.BoundedToolRunner, "run", changed)
    with pytest.raises(native.FiniteIntegerObservationError, match="pinned native tool changed"):
        prove(prepared, tools, tool_policy=policy)


@pytest.mark.parametrize("boundary", ["entry", "lean"])
def test_cancellation_is_observed_before_return_and_leases_are_released(prepared, tools, monkeypatch, boundary):
    cancelled = threading.Event()
    if boundary == "entry": cancelled.set()
    else:
        original = model.BoundedToolRunner.run
        def changed(self, command, **options):
            raw = original(self, command, **options)
            if "IntegerModel.lean" in command: cancelled.set()
            return raw
        monkeypatch.setattr(model.BoundedToolRunner, "run", changed)
    with pytest.raises(LeaseCancelledError):
        prove(prepared, tools, cancel_event=cancelled)
    assert prepared["scheduler"].snapshot()["active_lease_count"] == 0


def test_exhausted_entry_deadline_cannot_execute_native_tool(prepared, tools, monkeypatch):
    monkeypatch.setattr(model.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("expired deadline executed Lean"))
    with pytest.raises(LeaseTimeoutError):
        prove(prepared, tools, timeout_seconds=1e-12)


def test_deadline_after_actual_lean_call_refuses_result(prepared, tools, monkeypatch):
    original = model.BoundedToolRunner.run
    real_clock = model.time.monotonic
    shift = [0]
    monkeypatch.setattr(model.time, "monotonic", lambda: real_clock() + shift[0])
    def changed(self, command, **options):
        raw = original(self, command, **options)
        if "IntegerModel.lean" in command: shift[0] = 1000
        return raw
    monkeypatch.setattr(model.BoundedToolRunner, "run", changed)
    with pytest.raises(LeaseTimeoutError):
        prove(prepared, tools)


def test_cold_goal_tamper_or_authority_upgrade_cannot_validate(prepared, tools):
    record = prove(prepared, tools)
    for name, value in (("requested_model_theorem_proved", True), ("proof_authority", True)):
        body = record.to_dict()
        body[name] = value
        body["result_cid"] = cid_for_structured({k: v for k, v in body.items() if k != "result_cid"})
        changed = model.IntegerOffsetModelProof.from_dict(body)
        with pytest.raises(model.IntegerOffsetModelError):
            validate(changed, prepared, tools)


@pytest.mark.parametrize("artifact", ["lean_olean", "result"])
def test_cold_final_native_observation_cannot_hide_external_artifact_drift(prepared, tools, monkeypatch, artifact):
    record = prove(prepared, tools)
    path = prepared["output"] / ("IntegerModel.olean" if artifact == "lean_olean" else "result.json")
    original = prepared["index"].observe_current
    calls = []
    def changed(*args, **kwargs):
        current = original(*args, **kwargs)
        calls.append(current)
        if len(calls) == 2:
            with path.open("ab") as stream: stream.write(b"mutation after genuine final observation")
        return current
    monkeypatch.setattr(prepared["index"], "observe_current", changed)
    with pytest.raises(model.IntegerOffsetModelError):
        validate(record, prepared, tools)
    assert len(calls) == 2


def test_cold_source_edit_at_same_git_head_refuses_prior_model_certificate(prepared, tools):
    record = prove(prepared, tools)
    before = git(prepared["repository"], "rev-parse", "HEAD")
    (prepared["repository"] / "calc.py").write_bytes(source("n + 2"))
    assert git(prepared["repository"], "rev-parse", "HEAD") == before
    with pytest.raises(StaleCodebaseError):
        validate(record, prepared, tools)


@pytest.mark.parametrize("changes", [{"memory_mb": 512}, {"timeout_seconds": 91}, {"timeout_seconds": False}])
def test_explicit_process_budget_cannot_be_weakened(prepared, tools, monkeypatch, changes):
    monkeypatch.setattr(model.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("invalid controls executed Lean"))
    with pytest.raises(model.IntegerOffsetModelError, match="deadline|MiB"):
        prove(prepared, tools, **changes)
    assert not prepared["output"].exists()


def test_fresh_repeat_requires_new_output_and_new_native_invocations(prepared, tools, monkeypatch):
    first = prove(prepared, tools)
    calls = []
    original = model.BoundedToolRunner.run
    def counted(self, command, **options):
        calls.append(command)
        return original(self, command, **options)
    monkeypatch.setattr(model.BoundedToolRunner, "run", counted)
    with pytest.raises(model.IntegerOffsetModelError, match="fresh"):
        prove(prepared, tools)
    assert not calls
    second = prove(prepared, tools, output=prepared["output"].parent / "repeat-model")
    assert len(calls) == 2
    assert first.to_dict()["translation"] == second.to_dict()["translation"]
    assert first.to_dict()["lean_certificate"]["theorems"] == second.to_dict()["lean_certificate"]["theorems"]
