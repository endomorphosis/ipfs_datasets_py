"""Source-bound Lean operational models for the closed integer-offset profile.

The kernel checks a mathematical Int model. The guarded Python frontend and
its source-to-model correspondence remain trusted, explicitly bound checks;
neither the certificate nor this record proves CPython/source equivalence.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

from . import codebase_integer_profile as frontend
from . import codebase_finite_integer_observation as native
from .codebase_integer_profile import IntegerOffsetContract, compile_integer_offset
from .codebase_ir import RepositoryCodebaseIndex
from .codebase_resources import acquire_codebase_resources
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from ..backends.process import BoundedToolRunner, ToolRunLimits
from ..software_verification.program import ProgramIR
from ...optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError, LeaseTimeoutError, ResourceLane,
)

SCHEMA = "codebase-integer-operational-model-proof@1"
PROFILE = "guarded-python-integer-offset-lean-model@1"
TRANSLATION_SCHEMA = "codebase-integer-operational-model-translation@1"
SCOPE = "mathematical_integer_operational_model"
_FALSE = {key: False for key in (
    "source_semantics_verified", "runtime_behavior_verified", "behavior_authority",
    "proof_authority", "execution_authority", "completion_authority", "mutation_authority",
    "whole_program_semantics_verified", "cpython_equivalence_proved",
    "source_origin_proved", "training_convergence_proved",
)}
_ARGS = ["-j", "1", "-o", "IntegerModel.olean", "IntegerModel.lean"]
_NAMES = {"source": "captured_source.py", "compiled": "compiled.json",
    "translation": "translation.json", "frontend": "frontend.json",
    "tool_policy": "tool_policy.json", "lean_source": "IntegerModel.lean",
    "lean_olean": "IntegerModel.olean", "lean_process": "lean_process.json",
    "lean_certificate": "lean_certificate.json"}
_RECORD_FIELDS = {"schema", "profile", "scope", "status", "head", "manifest_cid", "source_path",
    "source_cid", "source_sha256", "compiled_cid", "contract", "contract_cid", "translation",
    "translation_cid", "tool_policy", "tool_policy_cid", "lean_certificate", "source_identity_proved",
    "requested_model_theorem_proved", "kernel_checked_model", "model_counterexample", "artifacts",
    "output", "result_cid", *_FALSE}
_CERTIFICATE_FIELDS = {"schema", "scope", "translation_cid", "source_cid", "olean_cid", "tool",
    "version_process", "process", "theorems", "dependency_scope", "claim"}
_CERTIFICATE_CLAIM = "Lean kernel checks the emitted Int operational model under trusted Init imports; source/frontend correctness and CPython equivalence remain unproved."


class IntegerOffsetModelError(ValueError):
    """Unsupported translation, invalid binding, or changed checked evidence."""


def _copy(value):
    try:
        raw = canonical_dag_json_bytes(value)
        if len(raw) > native.MAX_WORKSPACE_BYTES:
            raise ValueError("record byte bound")
        return json.loads(raw)
    except (TypeError, ValueError, RecursionError) as error:
        raise IntegerOffsetModelError("bounded canonical model record required") from error


@dataclass(frozen=True, slots=True)
class IntegerOffsetModelProof:
    """Immutable evidence record; constructing one grants no proof authority."""

    _wire: bytes

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._wire)

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        value = _copy(value)
        if set(value) != _RECORD_FIELDS or value.get("schema") != SCHEMA or value.get("profile") != PROFILE:
            raise IntegerOffsetModelError("exact operational model record required")
        return cls(canonical_dag_json_bytes(value))


def _implementation():
    from ..software_verification import program
    identity = frontend._implementation_identity()
    identity["source_sha256"].update({module.__name__: hashlib.sha256(
        Path(module.__file__).read_bytes()).hexdigest() for module in (sys.modules[__name__], program)})
    identity["frontend_python"] = native._tool(Path(sys.executable))
    identity["claim"] = "Selected frontend implementation files; no parser, CPython, or transitive dependency correctness theorem."
    return _copy(identity)


def _need(condition, message):
    if not condition:
        raise IntegerOffsetModelError(message)


def _translation(compiled, head, implementation):
    """Check body AST correspondence, retaining the complete original ProgramIR."""
    function, offset = frontend._guard(compiled.source, compiled.contract)
    payload = compiled.pipeline.program.to_dict()
    _need(ProgramIR.from_dict(payload).to_dict() == payload, "native ProgramIR does not round trip")
    contract = compiled.contract
    _need(payload["metadata"] == {"adapter": "SourceSoftwareVerificationAdapter@1",
        "language": "python", "path": contract.path}, "unsupported adapter metadata")
    _need(offset == compiled.body_offset and compiled.source_cid == cid_for_bytes(compiled.source),
          "compiled source offset or identity differs")
    sources = payload["sources"]
    _need(len(sources) == 1 and sources[0]["content_sha256"] == hashlib.sha256(compiled.source).hexdigest()
        and sources[0]["source_revision"] == "snapshot:" + head.snapshot_cid
        and sources[0]["source_id"] == contract.path, "native source binding differs")
    fn = payload["functions"][0]
    _need(len(payload["functions"]) == 1 and not payload["global_symbol_ids"]
        and not fn["local_symbol_ids"] and fn["return_type"] == "int"
        and not fn["declared_exceptions"] and not fn["exception_symbol_ids"], "unsupported native function semantics")
    parameter = fn["parameter_symbol_ids"][0]
    symbols = {item["symbol_id"]: item for item in payload["symbols"]}
    _need(set(symbols) == {parameter, fn["result_symbol_id"]}
        and all(item["type_ref"] == "int" and not item["attributes"] for item in symbols.values()),
        "unsupported native symbol types or attributes")
    commands = payload["commands"]
    _need(len(commands) == 1 and commands[0]["kind"] == "return"
        and not commands[0]["attributes"] and not commands[0]["undefined_behavior"]
        and not commands[0]["target_symbol_ids"] and len(commands[0]["expression_ids"]) == 1
        and commands[0]["evaluation_order"] == commands[0]["expression_ids"], "unsupported native command semantics")
    for effects in (fn["effects"], commands[0]["effects"]):
        _need(not any(effects[key] for key in ("allocates", "deallocates", "raises", "performs_io", "nondeterministic", "synchronizes", "writes"))
            and set(effects["reads"]) <= {parameter}, "unsupported native external effects")
    expressions = {item["expression_id"]: item for item in payload["expressions"]}
    spans = {item["span_id"]: item for item in payload["spans"]}
    lines = [0]
    for line in compiled.source.splitlines(keepends=True):
        lines.append(lines[-1] + len(line))
    used, mappings = set(), []

    def lower(key, node):
        row = expressions[key]
        used.add(key)
        _need(row["type_ref"] in {"any", "int"} and row["source_ref_ids"] == [sources[0]["ref_id"]]
            and len(row["span_ids"]) == 1, "source body type or provenance differs")
        span = spans[row["span_ids"][0]]
        _need((span["start_byte"], span["end_byte"]) == (lines[node.lineno - 1] + node.col_offset,
            lines[node.end_lineno - 1] + node.end_col_offset), "source body AST span differs")
        mappings.append({"expression_id": key, "source_type": row["type_ref"], "model_type": "Lean.Int",
            "basis": "closed AST and exact built-in integer input assumption", "span_ids": row["span_ids"]})
        if type(node) is ast.Name:
            _need(row["kind"] == "symbol" and row["symbol_ids"] == [parameter]
                and not row["operand_ids"] and not row["operator"] and not row["attributes"], "native parameter expression differs")
            return {"kind": "parameter"}
        if type(node) is ast.Constant:
            _need(type(node.value) is int and row["kind"] == "literal"
                and row["attributes"] == {"value": node.value} and not row["operand_ids"]
                and not row["symbol_ids"] and not row["operator"], "native literal expression differs")
            return {"kind": "literal", "value": node.value}
        _need(not row["attributes"] and not row["symbol_ids"]
            and row["evaluation_order"] == row["operand_ids"], "native operation attributes or order differ")
        if type(node) is ast.UnaryOp:
            expected = "neg" if type(node.op) is ast.USub else "pos"
            _need(row["kind"] == "unary" and row["operator"] == expected and len(row["operand_ids"]) == 1,
                  "native unary operation differs")
            return {"kind": expected, "operand": lower(row["operand_ids"][0], node.operand)}
        expected = "add" if type(node.op) is ast.Add else "sub"
        _need(row["kind"] == "binary" and row["operator"] == expected and len(row["operand_ids"]) == 2,
              "native binary operation differs")
        return {"kind": expected, "left": lower(row["operand_ids"][0], node.left),
                "right": lower(row["operand_ids"][1], node.right)}

    tree = lower(commands[0]["expression_ids"][0], function.body[0].value)
    # Contract expressions are retained separately, not treated as executable commands.
    contract_expressions = sorted(set(expressions) - used)
    _need(all(key.startswith("expr:pipeline:") for key in contract_expressions), "unaccounted native body expressions")
    return {"schema": TRANSLATION_SCHEMA, "profile": PROFILE, "head": head.to_dict(),
        "source_cid": compiled.source_cid, "source_sha256": hashlib.sha256(compiled.source).hexdigest(),
        "revision": compiled.revision, "contract": contract.to_dict(), "contract_cid": contract.cid,
        "source_offset": offset, "requested_offset": contract.offset,
        "frontend": implementation, "native_program": payload,
        "native_program_cid": cid_for_structured(payload), "adapter_metadata": payload["metadata"],
        "source_adapter_metadata": sources[0]["metadata"], "compiled_cid": compiled.cid,
        "assumptions": list(frontend.ASSUMPTIONS), "operational_expression": tree,
        "type_mapping": {"symbols": [{"symbol_id": key, "source_type": "int", "model_type": "Lean.Int"}
            for key in sorted(symbols)], "expressions": mappings},
        "effect_mapping": {"native_function": fn["effects"], "native_return": commands[0]["effects"],
            "model": {"reads": [parameter], "writes": [], "returns": "Lean.Int"},
            "basis": "Closed one-return AST; conservative native summaries retained without rewriting."},
        "executable_expression_ids": sorted(used), "retained_contract_expression_ids": contract_expressions,
        "scope": SCOPE, "translation_correspondence_checked": True,
        "translation_correctness_proved": False, **_FALSE}


def _lean(translation):
    def expression(tree):
        kind = tree["kind"]
        if kind == "parameter": return "Expr.parameter"
        if kind == "literal": return "(Expr.literal (" + str(tree["value"]) + " : Int))"
        if kind == "pos": return "(Expr.pos " + expression(tree["operand"]) + ")"
        if kind == "neg": return "(Expr.neg " + expression(tree["operand"]) + ")"
        return "(Expr." + kind + " " + expression(tree["left"]) + " " + expression(tree["right"]) + ")"
    # Metadata is explicit evidence, not an uninterpreted substitute for run semantics.
    evidence = json.dumps(canonical_dag_json_bytes(translation).decode(), ensure_ascii=False)
    actual, desired = translation["source_offset"], translation["requested_offset"]
    lines = ["import Init", "namespace CodebaseIntegerModel", "set_option autoImplicit false",
        "-- Mathematical model only: no CPython, frontend-correctness or physical-source theorem.",
        "def translationEvidence : String := " + evidence,
        "inductive Expr where\n  | parameter\n  | literal (value : Int)\n  | add (left right : Expr)\n  | sub (left right : Expr)\n  | neg (operand : Expr)\n  | pos (operand : Expr)",
        "def eval : Expr → Int → Int\n  | .parameter, n => n\n  | .literal value, _ => value\n  | .add left right, n => eval left n + eval right n\n  | .sub left right, n => eval left n - eval right n\n  | .neg operand, n => -(eval operand n)\n  | .pos operand, n => eval operand n",
        "def sourceExpression : Expr := " + expression(translation["operational_expression"]),
        "def run (n : Int) : Int := eval sourceExpression n",
        "theorem source_offset_identity : ∀ n : Int, run n = n + (" + str(actual) + " : Int) := by\n  intro n\n  simp [run, sourceExpression, eval]\n  <;> omega"]
    names = ["source_offset_identity"]
    if actual == desired:
        lines.append("theorem requested_offset_identity : ∀ n : Int, run n = n + (" + str(desired) + " : Int) := source_offset_identity")
        names.append("requested_offset_identity")
    else:
        lines.extend(["theorem requested_offset_counterexample : run (0 : Int) ≠ (0 : Int) + (" + str(desired) + " : Int) := by decide",
            "theorem requested_goal_refuted : ¬ (∀ n : Int, run n = n + (" + str(desired) + " : Int)) := by\n  intro claimed\n  exact requested_offset_counterexample (claimed 0)"])
        names.extend(["requested_offset_counterexample", "requested_goal_refuted"])
    return ("\n\n".join(lines + ["end CodebaseIntegerModel", ""]).encode(), names)


def _verify_artifacts(value, index, checkpoint):
    output = Path(value["output"])
    _need(output.is_absolute() and output.resolve(strict=True) == output and not output.is_symlink(), "model output directory changed")
    _need(set(value["artifacts"]) == set(_NAMES), "model artifact population differs")
    for key, descriptor in value["artifacts"].items():
        checkpoint()
        path = output / _NAMES[key]
        _need(set(descriptor) == {"path", "sha256", "size_bytes", "cid"}
            and descriptor["path"] == str(path) and not path.is_symlink()
            and path.resolve(strict=True) == path and path.is_file(), "model artifact path changed")
        _need(path.stat().st_size <= native.MAX_WORKSPACE_BYTES, "model artifact byte bound exceeded")
        raw = path.read_bytes()
        _need(descriptor["sha256"] == hashlib.sha256(raw).hexdigest()
            and descriptor["size_bytes"] == len(raw) and descriptor["cid"] == cid_for_bytes(raw)
            and index.artifacts.get_bytes(descriptor["cid"]) == raw, "sealed model artifact changed")
    checkpoint()


def _controls(index, repository, expected_head, contract, timeout_seconds, memory_mb):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    _need(type(index) is RepositoryCodebaseIndex and index.catalog is not None and index.artifacts is not None
        and index.catalog.store is index.ingestor.store and index.catalog.artifacts is index.artifacts
        and type(expected_head) is CodebaseHead and type(contract) is IntegerOffsetContract,
        "exact native index, head and integer contract required")
    _need(type(timeout_seconds) in {int, float} and math.isfinite(timeout_seconds)
        and 0 < timeout_seconds <= 90 and type(memory_mb) is int and memory_mb >= 1024,
        "model check requires deadline at most 90 seconds and at least 1024 MiB")
    repository = Path(repository)
    _need(repository.is_absolute() and repository.resolve(strict=True) == repository and not repository.is_symlink(),
          "canonical repository required")
    return repository, CodebaseHead.from_dict(expected_head.to_dict()), IntegerOffsetContract.from_dict(contract.to_dict())


def prove_current_integer_offset_model(index, repository, *, expected_head, contract,
        tool_policy, output: Path, scheduler=None, parent_lease=None, cancel_event=None,
        timeout_seconds=60, memory_mb=1024) -> IntegerOffsetModelProof:
    """Run native Lean on a freshly captured, guarded operational model.

    Unsupported source and all stale/failed checks raise without returning a
    proof record. The desired offset is always retained, including refutation.
    """
    repository, expected_head, contract = _controls(index, repository, expected_head, contract, timeout_seconds, memory_mb)
    _need(isinstance(output, Path) and output.is_absolute() and output.resolve() == output
        and not output.exists() and not output.is_relative_to(repository), "fresh external canonical output required")
    policy = _copy(tool_policy)
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(30, timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def remaining():
            if signal.is_set(): raise LeaseCancelledError("integer model check cancelled")
            duration = deadline - time.monotonic()
            if duration <= 0: raise LeaseTimeoutError("integer model deadline exceeded")
            return duration
        policy = native._policy(policy, remaining)
        implementation = _implementation()
        def observe():
            duration = remaining()
            return index.observe_current(repository, expected_head=expected_head, parent_lease=lease,
                cancel_event=signal, admission_timeout_seconds=min(30, duration),
                timeout_seconds=duration, memory_mb=512)
        current = observe()
        entry = next((item for item in current.manifest.snapshot.entries if item.path == contract.path), None)
        _need(entry is not None and not entry.is_opaque, "selected source absent or opaque")
        source = index.artifacts.get_bytes(entry.source_cid)
        compiled = compile_integer_offset(source, contract, revision="snapshot:" + expected_head.snapshot_cid)
        translation = _translation(compiled, expected_head, implementation)
        _need(compiled.source_cid == entry.source_cid, "current captured source identity differs")
        text, names = _lean(translation)
        output.mkdir(parents=True, mode=0o700, exist_ok=False)
        artifacts = {}
        def save(key, raw):
            descriptor = native._artifact(output, _NAMES[key], raw)
            _need(index.artifacts.put_bytes(raw) == descriptor["cid"], "model CAS artifact identity differs")
            artifacts[key] = descriptor
        for key, raw in (("source", source), ("compiled", canonical_dag_json_bytes(compiled.to_dict())),
                ("translation", canonical_dag_json_bytes(translation)), ("frontend", canonical_dag_json_bytes(implementation)),
                ("tool_policy", canonical_dag_json_bytes(policy)), ("lean_source", text)):
            save(key, raw)
        def fence():
            observe()
            native._policy(policy, remaining)
            _need(_implementation() == implementation, "model frontend implementation changed")
            for key, descriptor in artifacts.items():
                raw = (output / _NAMES[key]).read_bytes()
                _need(not (output / _NAMES[key]).is_symlink() and cid_for_bytes(raw) == descriptor["cid"]
                    and index.artifacts.get_bytes(descriptor["cid"]) == raw, "sealed model artifact changed")
            remaining()
        runner = BoundedToolRunner(base_environment=native._ENV)
        def run(arguments, files, outputs=()):
            fence()
            with lease.acquire_child(lane=ResourceLane.VALIDATION, cpu_slots=1, memory_mb=512,
                    child_process_slots=1, timeout=remaining(), cancel_event=signal,
                    request_id="codebase-integer-model:lean") as child:
                limits = ToolRunLimits(timeout_seconds=remaining(), cpu_seconds=max(1, math.ceil(remaining())),
                    memory_bytes=policy["process_limits"]["lean"]["address_space_bytes"],
                    resident_memory_bytes=policy["process_limits"]["lean"]["resident_memory_bytes"],
                    max_input_bytes=native.MAX_IO_BYTES, max_output_bytes=native.MAX_IO_BYTES,
                    max_workspace_bytes=native.MAX_WORKSPACE_BYTES, max_output_files=8)
                raw = runner.run([policy["lean"]["path"], *arguments], input_files=files,
                    output_paths=outputs, limits=limits, cancellation=child.combined_cancellation_signal(signal))
                if raw.cancelled or signal.is_set(): raise LeaseCancelledError("native model Lean cancelled")
            fence()
            process = native._process(raw, {"timeout_ms": math.ceil(limits.timeout_seconds * 1000),
                "cpu_seconds": limits.cpu_seconds, "address_space_bytes": limits.memory_bytes,
                "resident_memory_bytes": limits.resident_memory_bytes,
                "max_input_bytes": limits.max_input_bytes, "max_output_bytes": limits.max_output_bytes,
                "max_workspace_bytes": limits.max_workspace_bytes, "max_output_files": limits.max_output_files})
            return raw, process
        version, version_process = run(["--version"], {})
        checked, process = run(_ARGS, {"IntegerModel.lean": text}, ("IntegerModel.olean",))
        _need(native._success(version) and version.stdout.startswith("Lean (version ")
            and native._success(checked) and not checked.stdout and checked.output_files.get("IntegerModel.olean"),
            "native Lean operational model check failed: " + checked.stderr[:2048])
        save("lean_olean", checked.output_files["IntegerModel.olean"])
        certificate = {"schema": "codebase-integer-operational-model-certificate@1", "scope": SCOPE,
            "translation_cid": cid_for_structured(translation), "source_cid": cid_for_bytes(text),
            "olean_cid": artifacts["lean_olean"]["cid"], "tool": policy["lean"],
            "version_process": version_process, "process": process, "theorems": names,
            "dependency_scope": policy["dependency_scope"],
            "claim": _CERTIFICATE_CLAIM}
        save("lean_process", canonical_dag_json_bytes({"version_process": version_process, "process": process}))
        save("lean_certificate", canonical_dag_json_bytes(certificate))
        matches = compiled.body_offset == contract.offset
        value = {"schema": SCHEMA, "profile": PROFILE, "scope": SCOPE,
            "status": "model_proved" if matches else "model_refuted", "head": expected_head.to_dict(),
            "manifest_cid": current.manifest.cid, "source_path": contract.path, "source_cid": entry.source_cid,
            "source_sha256": hashlib.sha256(source).hexdigest(), "compiled_cid": compiled.cid,
            "contract": contract.to_dict(), "contract_cid": contract.cid,
            "translation": translation, "translation_cid": cid_for_structured(translation),
            "tool_policy": policy, "tool_policy_cid": policy["policy_cid"], "lean_certificate": certificate,
            "source_identity_proved": True, "requested_model_theorem_proved": matches, "kernel_checked_model": True,
            "model_counterexample": None if matches else {"input": 0, "model_output": compiled.body_offset,
                "required_output": contract.offset}, "artifacts": artifacts, "output": str(output), **_FALSE}
        fence()
        value["result_cid"] = cid_for_structured(value)
        record = IntegerOffsetModelProof.from_dict(value)
        index.artifacts.put(record.to_dict())
        native._artifact(output, "result.json", record._wire)
        # CAS writes, output writes and the final native observer are all fences.
        fence()
        _verify_artifacts(value, index, remaining)
        _need(not (output / "result.json").is_symlink() and (output / "result.json").read_bytes() == record._wire
            and index.artifacts.get(record.cid) == value, "sealed model result changed")
        remaining()
        return record


def validate_current_integer_offset_model(record, index, repository, *, expected_head,
        contract, tool_policy, scheduler=None, parent_lease=None, cancel_event=None,
        timeout_seconds=60, memory_mb=1024) -> IntegerOffsetModelProof:
    """Cold-read exact source, frontend, native model and sealed certificates.

    This does not invoke Lean or confer evidence-origin authority on a caller
    record. Consumers must retain the result of their actual proving call.
    """
    repository, expected_head, contract = _controls(index, repository, expected_head, contract, timeout_seconds, memory_mb)
    _need(type(record) is IntegerOffsetModelProof, "typed operational model record required")
    value = record.to_dict()
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(30, timeout_seconds), memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def remaining():
            if signal.is_set(): raise LeaseCancelledError("integer model cold validation cancelled")
            duration = deadline - time.monotonic()
            if duration <= 0: raise LeaseTimeoutError("integer model cold validation deadline exceeded")
            return duration
        def observe():
            duration = remaining()
            return index.observe_current(repository, expected_head=expected_head, parent_lease=lease,
                cancel_event=signal, admission_timeout_seconds=min(30, duration), timeout_seconds=duration, memory_mb=512)
        policy = native._policy(tool_policy, remaining)
        current = observe()
        _need(set(value) == _RECORD_FIELDS and value.get("schema") == SCHEMA and value.get("profile") == PROFILE and value.get("scope") == SCOPE
            and value.get("head") == expected_head.to_dict() and value.get("manifest_cid") == current.manifest.cid
            and value.get("contract") == contract.to_dict() and value.get("contract_cid") == contract.cid
            and value.get("source_path") == contract.path and value.get("tool_policy") == policy
            and value.get("tool_policy_cid") == policy["policy_cid"]
            and all(value.get(key) is False for key in _FALSE), "model record roots, policy, or authority differ")
        _need(value.get("result_cid") == cid_for_structured({key: item for key, item in value.items() if key != "result_cid"}),
              "model result identity differs")
        entry = next((item for item in current.manifest.snapshot.entries if item.path == contract.path), None)
        _need(entry is not None and not entry.is_opaque and entry.source_cid == value["source_cid"], "current model source differs")
        source = index.artifacts.get_bytes(entry.source_cid)
        implementation = _implementation()
        compiled = compile_integer_offset(source, contract, revision="snapshot:" + expected_head.snapshot_cid)
        translation = _translation(compiled, expected_head, implementation)
        _need(value["translation"] == translation and value["translation_cid"] == cid_for_structured(translation)
            and value["compiled_cid"] == compiled.cid and value["source_sha256"] == hashlib.sha256(source).hexdigest(),
            "cold native model translation differs")
        text, names = _lean(translation)
        certificate = value["lean_certificate"]
        _need(type(certificate) is dict and set(certificate) == _CERTIFICATE_FIELDS
            and certificate["schema"] == "codebase-integer-operational-model-certificate@1"
            and certificate["theorems"] == names and certificate["scope"] == SCOPE
            and certificate["translation_cid"] == value["translation_cid"] and certificate["tool"] == policy["lean"]
            and certificate["dependency_scope"] == policy["dependency_scope"] and certificate["claim"] == _CERTIFICATE_CLAIM
            and certificate["source_cid"] == cid_for_bytes(text)
            and certificate["olean_cid"] == value["artifacts"]["lean_olean"]["cid"], "model certificate bindings differ")
        for process, arguments in ((certificate["version_process"], ["--version"]), (certificate["process"], _ARGS)):
            _need(process["command"] == [policy["lean"]["path"], *arguments] and process["returncode"] == 0
                and not process["stderr"] and not process["error"] and process["workspace_cleaned"]
                and not any(process[key] for key in ("timed_out", "cancelled", "unavailable", "output_truncated", "workspace_limit_exceeded", "resource_exhausted")),
                "model certificate native process unsuccessful")
        _need(certificate["version_process"]["stdout"].startswith("Lean (version ")
            and not certificate["process"]["stdout"], "model native version or compiler output differs")
        matches = compiled.body_offset == contract.offset
        _need(value["source_identity_proved"] is True and value["kernel_checked_model"] is True
            and value["requested_model_theorem_proved"] is matches
            and value["status"] == ("model_proved" if matches else "model_refuted")
            and value["model_counterexample"] == (None if matches else {"input": 0,
                "model_output": compiled.body_offset, "required_output": contract.offset}), "model goal verdict differs")
        _verify_artifacts(value, index, remaining)
        expected_bytes = {"source": source, "compiled": canonical_dag_json_bytes(compiled.to_dict()),
            "translation": canonical_dag_json_bytes(translation), "frontend": canonical_dag_json_bytes(implementation),
            "tool_policy": canonical_dag_json_bytes(policy), "lean_source": text,
            "lean_certificate": canonical_dag_json_bytes(certificate),
            "lean_process": canonical_dag_json_bytes({"version_process": certificate["version_process"], "process": certificate["process"]})}
        _need(all(index.artifacts.get_bytes(value["artifacts"][key]["cid"]) == raw for key, raw in expected_bytes.items()),
              "model artifact content does not replay")
        _need(index.artifacts.get(record.cid) == value and (Path(value["output"]) / "result.json").read_bytes() == record._wire,
              "cold sealed model result differs")
        observe()
        native._policy(policy, remaining)
        _need(_implementation() == implementation, "model frontend changed during cold validation")
        _verify_artifacts(value, index, remaining)
        _need(not (Path(value["output"]) / "result.json").is_symlink()
            and (Path(value["output"]) / "result.json").read_bytes() == record._wire
            and index.artifacts.get(record.cid) == value, "cold sealed model result changed at final fence")
        remaining()
        return record


__all__ = ["SCHEMA", "PROFILE", "SCOPE", "IntegerOffsetModelError", "IntegerOffsetModelProof",
    "prove_current_integer_offset_model", "validate_current_integer_offset_model"]
