"""Actual Lean lowering and adversarial replay for the closed integer grammar.

Pure extraction tests do not establish source/parser or runtime correctness.
Native tests use installed ELF tools and the actual host resource sampler.
"""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import os
import sys
import threading

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_integer_lowering_lean as lowering
from ipfs_datasets_py.logic.software_contracts import codebase_finite_integer_observation as native
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_integer_profile import (
    IntegerOffsetContract, UnsupportedIntegerProfile, compile_integer_offset,
)
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
from ipfs_datasets_py.logic.software_verification.program import ProgramIR
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig, LeaseCancelledError,
)
from .test_codebase_current import git

VIEW = "repository:integer-lowering-qualification"
LEAN = Path("/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lean")


def source(body="n + 1"):
    return ("def increment(n: int) -> int:\n    return " + body + "\n").encode()


def pure_translation(body="n + 1", desired=2):
    """Native compilation with a typed authored head; no owner/proof verdict."""
    cid = cid_for_structured({"authored": "pure lowering extraction diagnostic"})
    head = CodebaseHead(VIEW, 1, cid, cid, f"rev:{VIEW}:snapshot:{cid}", cid)
    compiled = compile_integer_offset(source(body), IntegerOffsetContract("calc.py", "increment", "n", desired),
        revision="snapshot:" + head.snapshot_cid)
    return lowering._translation(compiled, head, {"claim": "pure extraction only"}), compiled, head


@pytest.mark.parametrize("body,desired", [("n", 0), ("n + 2", 2), ("n - 2", -2),
    ("n + -2", -2), ("n - (-2)", 2), ("n + +2", 2)])
def test_pure_independent_source_and_native_target_preserve_source_not_requested_goal(body, desired):
    translation, compiled, _ = pure_translation(body, desired + 1)
    target, used = lowering._native_target(compiled.pipeline.program.to_dict())
    source_ast, _ = lowering._source_syntax(source(body), compiled.contract)
    assert target == lowering._lower_source(source_ast) == translation["native_target_syntax"]
    assert used == translation["executable_expression_ids"]
    assert translation["source_offset"] == desired
    assert translation["requested_offset"] == desired + 1
    assert translation["source_ast_lowering_proved"] is False
    assert translation["native_target_correspondence_proved"] is False
    assert all(translation[key] is False for key in lowering._FALSE)


@pytest.mark.parametrize("damage", ["literal", "operator", "order", "span", "effect", "symbol"])
def test_pure_native_frontend_mutations_fail_independent_correspondence(damage):
    _, compiled, head = pure_translation()
    payload = compiled.pipeline.program.to_dict()
    payload.pop("program_id")
    binary = next(row for row in payload["expressions"] if row["kind"] == "binary"
        and not row["expression_id"].startswith("expr:pipeline:"))
    if damage == "literal":
        next(row for row in payload["expressions"] if row["kind"] == "literal"
            and not row["expression_id"].startswith("expr:pipeline:"))["attributes"]["value"] = 2
    elif damage == "operator": binary["operator"] = "sub"
    elif damage == "order": binary["evaluation_order"] = list(reversed(binary["evaluation_order"]))
    elif damage == "span":
        next(row for row in payload["spans"] if row["span_id"] == binary["span_ids"][0])["start_byte"] += 1
    elif damage == "effect": payload["functions"][0]["effects"]["performs_io"] = True
    else: payload["symbols"][0]["type_ref"] = "bool"
    with pytest.raises(ValueError):
        program = ProgramIR.from_dict(payload)
        changed = replace(compiled, pipeline=replace(compiled.pipeline, program=program))
        lowering._translation(changed, head, {"claim": "pure mutation diagnostic"})


def test_pure_canonical_comparison_distinguishes_bool_integer_aliases():
    assert not lowering._same({"source_offset": 1}, {"source_offset": True})
    assert not lowering._same({"input": 0}, {"input": False})


@pytest.fixture(scope="module")
def tools():
    python = Path(sys.executable).resolve(strict=True)
    for path in (python, LEAN):
        with path.open("rb") as stream:
            assert stream.read(4) == b"\x7fELF", "installed native ELF tools required; no shim or skip"
    return native.seal_finite_integer_tools(python_executable=python, lean_executable=LEAN)


@pytest.fixture
def prepared(tmp_path):
    import duckdb
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Lowering Qualification")
    git(root, "config", "user.email", "fixture@example.invalid")
    (root / "calc.py").write_bytes(source())
    git(root, "add", "calc.py")
    git(root, "commit", "-qm", "authored integer lowering source")
    connection = duckdb.connect(str(tmp_path / "codebase.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(tmp_path / "artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
        catalog=CodebaseCatalog(store, artifacts))
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "admission.json", lane_reservations={}, auto_renew_leases=False))
    try:
        head = index.prepare_current(root, repository_id=VIEW, operation_id="initial",
            expected_head=None, scheduler=scheduler).head
        yield {"index": index, "repository": root, "expected_head": head, "scheduler": scheduler,
            "output": tmp_path / "lowering"}
    finally:
        assert scheduler.snapshot()["active_lease_count"] == scheduler.snapshot()["waiting_request_count"] == 0
        connection.close()


def prove(prepared, tools, **changes):
    options = dict(prepared)
    options.update(contract=IntegerOffsetContract("calc.py", "increment", "n", 2),
        tool_policy=deepcopy(tools), timeout_seconds=60)
    options.update(changes)
    return lowering.prove_current_integer_offset_lowering(**options)


def validate(record, prepared, tools, **changes):
    options = {key: value for key, value in prepared.items() if key != "output"}
    options.update(contract=IntegerOffsetContract("calc.py", "increment", "n", 2),
        tool_policy=deepcopy(tools), timeout_seconds=60)
    options.update(changes)
    return lowering.validate_current_integer_offset_lowering(record, **options)


def recapture(prepared, raw):
    (prepared["repository"] / "calc.py").write_bytes(raw)
    prepared["expected_head"] = prepared["index"].prepare_current(prepared["repository"],
        repository_id=VIEW, operation_id="successor", expected_head=prepared["expected_head"],
        scheduler=prepared["scheduler"]).head


def test_native_lean_checks_generic_lowering_and_refutes_requested_offset(prepared, tools):
    record = prove(prepared, tools)
    value = record.to_dict()
    assert value["scope"] == "formal_ast_lowering_correctness"
    assert value["source_ast_semantics_defined"] is True
    assert value["source_ast_lowering_proved"] is value["native_target_correspondence_proved"] is True
    assert value["status"] == "model_refuted" and value["requested_model_theorem_proved"] is False
    assert value["model_counterexample"] == {"input": 0, "model_output": 1, "required_output": 2}
    assert all(value[key] is False for key in lowering._FALSE)
    translation = value["translation"]
    assert translation["source_ast_syntax"] == {"kind": "add", "literal": {"kind": "literal", "value": 1}}
    assert ProgramIR.from_dict(translation["native_program"]).to_dict() == translation["native_program"]
    assert translation["native_program_cid"] == cid_for_structured(translation["native_program"])
    text = Path(value["artifacts"]["lean_source"]["path"]).read_text()
    assert "∀ body : SourceBody, ∀ input : Int" in text
    assert "signed_literal_lowering_correct" in text and "captured_ast_target_equivalence" in text
    assert "requested_goal_refuted" in text and "sorry" not in text and "axiom " not in text
    assert value["lean_certificate"]["process"]["returncode"] == 0
    assert value["lean_certificate"]["process"]["stdout"] == ""
    assert value["tool_policy"] == tools
    assert value["process_policy"]["base_tool_policy_cid"] == tools["policy_cid"]
    assert value["process_policy"]["max_output_bytes"] == 1024 * 1024
    assert value["process_policy_cid"] == cid_for_structured(value["process_policy"])
    assert value["lean_certificate"]["process_policy_cid"] == value["process_policy_cid"]
    assert value["lean_certificate"]["process"]["limits"]["max_output_bytes"] == 1024 * 1024
    for descriptor in value["artifacts"].values():
        raw = Path(descriptor["path"]).read_bytes()
        assert cid_for_bytes(raw) == descriptor["cid"]
        assert prepared["index"].artifacts.get_bytes(descriptor["cid"]) == raw
    assert validate(record, prepared, tools) is record


@pytest.mark.parametrize("body,desired", [("n", 0), ("n + 2", 2), ("n - 2", -2),
    ("n + -2", -2), ("n - (-2)", 2), ("n + +2", 2),
    ("n + 18446744073709551615", 18446744073709551615)])
def test_native_supported_source_forms_compile_and_prove_requested_identity(prepared, tools, body, desired):
    recapture(prepared, source(body))
    contract = IntegerOffsetContract("calc.py", "increment", "n", desired)
    record = prove(prepared, tools, contract=contract)
    value = record.to_dict()
    assert value["status"] == "model_proved" and value["requested_model_theorem_proved"] is True
    assert value["model_counterexample"] is None
    assert all(value[key] is False for key in lowering._FALSE)
    assert validate(record, prepared, tools, contract=contract) is record


@pytest.mark.parametrize("bad", [source("abs(n)"), source("n + True"), source("n / 2"),
    source("n + 18446744073709551616"),
    b"@decorator\ndef increment(n: int) -> int:\n    return n + 1\n",
    b"def increment(n: int = 0) -> int:\n    return n + 1\n",
    b"def increment(n: int) -> int:\n    changed = n\n    return n + 1\n",
    b"GLOBAL = 1\ndef increment(n: int) -> int:\n    return n + GLOBAL\n"])
def test_native_unsupported_source_refuses_before_tool_invocation(prepared, tools, monkeypatch, bad):
    recapture(prepared, bad)
    monkeypatch.setattr(lowering.BoundedToolRunner, "run", lambda *a, **k: pytest.fail("unsupported source invoked native tool"))
    with pytest.raises(UnsupportedIntegerProfile):
        prove(prepared, tools)
    assert not prepared["output"].exists()


def test_native_lean_rejects_independently_changed_target_correspondence(prepared, tools, monkeypatch):
    original = lowering._lean
    def changed(translation):
        translation = deepcopy(translation)
        translation["native_target_syntax"]["right"]["value"] = 2
        return original(translation)
    monkeypatch.setattr(lowering, "_lean", changed)
    with pytest.raises(lowering.IntegerOffsetLoweringError, match="native Lean"):
        prove(prepared, tools)
    assert prepared["output"].exists() and not (prepared["output"] / "result.json").exists()


@pytest.mark.parametrize("artifact", list(lowering._NAMES))
def test_native_cold_validator_refuses_every_artifact_mutation(prepared, tools, artifact):
    record = prove(prepared, tools)
    path = Path(record.to_dict()["artifacts"][artifact]["path"])
    with path.open("ab") as stream:
        stream.write(b"mutated")
    with pytest.raises(lowering.IntegerOffsetLoweringError):
        validate(record, prepared, tools)


@pytest.mark.parametrize("damage", ["translation_alias", "counterexample_alias", "process_alias", "process_flag", "authority"])
def test_native_rehashed_caller_projection_cannot_replace_exact_reconstruction(prepared, tools, damage):
    value = prove(prepared, tools).to_dict()
    if damage == "translation_alias": value["translation"]["source_offset"] = True
    elif damage == "counterexample_alias": value["model_counterexample"]["input"] = False
    elif damage == "process_alias": value["lean_certificate"]["process"]["returncode"] = False
    elif damage == "process_flag": value["lean_certificate"]["process"]["process_tree_terminated"] = True
    else: value["execution_authority"] = True
    value["result_cid"] = cid_for_structured({key: item for key, item in value.items() if key != "result_cid"})
    record = lowering.IntegerOffsetLoweringProof.from_dict(value)
    with pytest.raises(lowering.IntegerOffsetLoweringError):
        validate(record, prepared, tools)


@pytest.mark.parametrize("phase,damage", [("prove", "source"), ("cold", "source"),
    ("cold", "source_cas"), ("cold", "manifest_cas"), ("cold", "ast_cas")])
def test_native_final_genuine_observer_then_tamper_is_refused(prepared, tools, monkeypatch, phase, damage):
    record = None if phase == "prove" else prove(prepared, tools)
    index = prepared["index"]
    original = index.observe_current
    calls, mutated = [0], []
    def changed(*args, **kwargs):
        observed = original(*args, **kwargs)
        calls[0] += 1
        armed = ((prepared["output"] / "result.json").exists() if phase == "prove" else calls[0] == 2)
        if armed and not mutated:
            manifest = observed.manifest
            entry = next(row for row in manifest.snapshot.entries if row.path == "calc.py")
            unit = next(row for row in manifest.units if row.source_key == entry.source_key)
            if damage == "source": path = prepared["repository"] / "calc.py"
            elif damage == "source_cas": path = index.artifacts.path_for(entry.source_cid, source=True)
            elif damage == "manifest_cas": path = index.artifacts.path_for(manifest.cid)
            else: path = index.artifacts.path_for(unit.ast_cid)
            with path.open("ab") as stream: stream.write(b"late mutation")
            mutated.append(path)
        return observed
    monkeypatch.setattr(index, "observe_current", changed)
    with pytest.raises((lowering.IntegerOffsetLoweringError, StaleCodebaseError, ValueError)):
        prove(prepared, tools) if phase == "prove" else validate(record, prepared, tools)
    assert mutated, "late mutation control must execute"


def test_native_cold_atomic_replacement_after_open_is_refused(prepared, tools, monkeypatch):
    record = prove(prepared, tools)
    path = Path(record.to_dict()["artifacts"]["lean_olean"]["path"])
    original = os.open
    replaced = []
    def changed(target, flags, *args, **kwargs):
        descriptor = original(target, flags, *args, **kwargs)
        if Path(target) == path and not replaced:
            alternate = path.with_suffix(".replacement")
            alternate.write_bytes(path.read_bytes() + b"atomic replacement")
            alternate.replace(path)
            replaced.append(path)
        return descriptor
    monkeypatch.setattr(lowering.os, "open", changed)
    with pytest.raises(lowering.IntegerOffsetLoweringError, match="replaced"):
        validate(record, prepared, tools)
    assert replaced


def test_native_successor_reproof_refuses_old_head_and_proves_new_requested_model(prepared, tools):
    record = prove(prepared, tools)
    recapture(prepared, source("n + 2"))
    with pytest.raises(lowering.IntegerOffsetLoweringError):
        validate(record, prepared, tools)
    successor = prove(prepared, tools, output=prepared["output"].with_name("successor-lowering"))
    assert successor.to_dict()["status"] == "model_proved"
    assert successor.to_dict()["head"]["generation"] == record.to_dict()["head"]["generation"] + 1


def test_native_cancellation_refuses_record_and_leaks_no_lease(prepared, tools):
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(LeaseCancelledError):
        prove(prepared, tools, cancel_event=cancelled)
    assert not prepared["output"].exists()
