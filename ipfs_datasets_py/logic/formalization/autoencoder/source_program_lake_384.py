"""Actual bounded Lake checks of source-replayed learned ProgramIR candidates.

Compiles supported candidates together, retaining every unsupported/mismatched
row in the result. Compilation is syntax/type evidence, never source truth or
security proof. Old family gates and numerical checkpoints remain unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sys
import weakref

from .security import source_program_binding_384_v2 as binding
from .security import source_program_binding_384 as original_binding
from . import native_program_lean_v2 as emitter
from . import native_program_lean as original_emitter
from . import native_family_lake_v4 as executor
from ...software_verification import program, source_adapters, syntax_bridge
from ...backends import process

SCHEMA = "source-program-384-lake/v1"
MAX_ROWS = 128
FALSE = dict(proof_authority=False, execution_authority=False, completion_authority=False,
    source_semantics_verified=False, whole_program_semantics_verified=False,
    security_specification_inferred=False, admitted=False, formalized=False,
    claim_proved=False, promotion_performed=False)
_ISSUED = weakref.WeakKeyDictionary()


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _owners():
    return (sys.modules[__name__], binding, original_binding, emitter,
            original_emitter, executor, process, program, source_adapters, syntax_bridge)


def _pins():
    return {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in _owners()}


_IMPORTED = _pins()


def _guard():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for module in _owners():
        _pin_imported_module(module)
    if _pins() != _IMPORTED:
        raise ValueError("source program producer changed after import")


def _rows(rows):
    if type(rows) is not list or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("one to 128 source candidates required")
    for row in rows:
        if type(row) is not dict or set(row) != {"id", "source_text", "candidate_ir"}:
            raise ValueError("closed source/candidate rows required; gold targets are forbidden")
        if type(row["id"]) is not str or not 0 < len(row["id"]) <= 256:
            raise ValueError("bounded candidate identity required")
        if type(row["source_text"]) is not str or not 0 < len(row["source_text"].encode()) <= 65536:
            raise ValueError("bounded source text required")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate source candidate identity")
    if len(_raw(rows)) > 4 * 1024 * 1024:
        raise ValueError("source candidate batch exceeds byte limit")
    return deepcopy(rows)


def prepare_source_program_lean(rows):
    """Replay source/candidate binding and emit complete original program views."""
    _guard()
    inputs = _rows(rows)
    results, lines = [], ["namespace SecuritySourcePrograms"]
    for index, row in enumerate(inputs):
        qualification = binding.qualify_source_candidate(row["source_text"], row["candidate_ir"])
        result = dict(id=row["id"], source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(),
            candidate_sha256=_digest(row["candidate_ir"]), source_qualification=qualification,
            parser_status="blocked", lake_status="blocked", semantic_lowering_supported=False,
            reason=qualification.get("reason"), **FALSE)
        if qualification["status"] == "qualified":
            payload = qualification["projections"][0]["native_document"]
            try:
                source, details = emitter.emit_program(payload)
                if not source.strip():
                    raise ValueError("empty operational declarations")
                wrapped = f"namespace Candidate_{index}\n{source}\nend Candidate_{index}"
                lines.append(wrapped)
                result.update(parser_status="passed", lake_status="not_run", reason=None,
                    semantic_lowering_supported=True, program_sha256=_digest(payload), lowering=details,
                    lean_declarations_sha256=hashlib.sha256(wrapped.encode()).hexdigest())
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                result["reason"] = str(error)[:1024]
        results.append(result)
    lines.append("end SecuritySourcePrograms\n")
    source = "\n\n".join(lines)
    if len(source.encode()) > 4 * 1024 * 1024:
        raise ValueError("generated Lean module exceeds byte limit")
    _guard()
    return dict(schema=SCHEMA, library="SecuritySourcePrograms", input_sha256=_digest(inputs),
        rows=results, lean_source=source, lean_source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        producer=_pins(), source_replay_passed=True, status="prepared", backend_executed=False,
        scope="bounded native operational definitions and metadata declarations, not Python equivalence or security correctness",
        assumptions=["Explicit int annotations are input assumptions, not runtime enforcement.",
                     "Integer arithmetic uses mathematical unbounded Int.",
                     "A successful build checks definitions/types; it does not prove a security specification."], **FALSE)


@dataclass(frozen=True, eq=False)
class SourceProgramLakeExecution:
    """Only a locally issued build handle can be verified as execution evidence."""
    def to_dict(self):
        if self not in _ISSUED:
            raise ValueError("unissued source program Lake execution")
        return json.loads(_ISSUED[self]["receipt"])


def build_source_program_lake(rows, *, lake_executable, timeout_seconds=60, output_directory=None):
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        raise ValueError("bounded Lake timeout required")
    output = Path(output_directory).resolve() if output_directory is not None else None
    if output is not None and output.exists():
        raise ValueError("fresh evidence directory required")
    receipt = prepare_source_program_lean(rows)
    supported = [row for row in receipt["rows"] if row["semantic_lowering_supported"]]
    found = shutil.which(str(lake_executable)) if supported else None
    tool_pins = {}
    if found:
        native_lake = Path(found).resolve()
        for tool in (native_lake, native_lake.with_name("lean")):
            if tool.is_file():
                tool_pins[str(tool)] = hashlib.sha256(tool.read_bytes()).hexdigest()
    execution = (executor._execute(receipt["lean_source"], receipt["library"], lake_executable, timeout_seconds)
        if supported else {"status": "blocked", "backend_executed": False, "reason": "no_supported_source_programs"})
    if execution.get("executable_sha256"):
        used_lake = Path(execution["command"][0]).resolve()
        if tool_pins.get(str(used_lake)) != execution["executable_sha256"] or str(used_lake.with_name("lean")) not in tool_pins:
            raise ValueError("native Lake and Lean executable identities required")
    for path, expected in tool_pins.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError("Lake or Lean executable changed during build")
    _guard()
    # Replay after execution to bind the result to exact unchanged source and
    # candidates, not a mutable prepared dictionary or archived JSON receipt.
    if prepare_source_program_lean(rows) != receipt:
        raise ValueError("source program inputs or preparation changed during build")
    passed = execution["status"] == "passed" and execution["backend_executed"] is True
    for row in supported:
        row["lake_status"] = "passed" if passed else execution["status"]
    complete = passed and len(supported) == len(receipt["rows"])
    receipt.update(status="passed" if complete else "partial" if passed else execution["status"],
        backend_executed=execution["backend_executed"], execution=execution,
        all_candidates_compiled=complete, supported_count=len(supported), count=len(receipt["rows"]),
        tool_binary_sha256=tool_pins, tool_pin_scope="native Lake and Lean binaries, not all toolchain libraries")
    if output is not None:
        output.mkdir(parents=True)
        (output / "SecuritySourcePrograms.lean").write_text(receipt["lean_source"])
        (output / "receipt.json").write_bytes(_raw(receipt))
    handle = SourceProgramLakeExecution()
    _ISSUED[handle] = dict(receipt=_raw(receipt), input_sha256=receipt["input_sha256"], tool_pins=tool_pins)
    return handle


def verify_source_program_lake(execution, rows):
    _guard()
    if type(execution) is not SourceProgramLakeExecution or execution not in _ISSUED:
        raise ValueError("live issued source program Lake handle required")
    state = _ISSUED[execution]
    if _digest(_rows(rows)) != state["input_sha256"]:
        raise ValueError("source program Lake input identity mismatch")
    for path, expected in state["tool_pins"].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError("Lake or Lean executable changed")
    receipt = json.loads(state["receipt"])
    replay = prepare_source_program_lean(rows)
    if replay["lean_source_sha256"] != receipt["lean_source_sha256"]:
        raise ValueError("source program declaration replay differs")
    return receipt


__all__ = ["prepare_source_program_lean", "build_source_program_lake", "verify_source_program_lake",
           "SourceProgramLakeExecution"]
