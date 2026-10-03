"""Conditional integer-offset checks over exact captured Python source.

The profile checks source correspondence for a closed syntax fragment. Integer
annotations are assumptions about callers, never runtime type enforcement.
Native SMT agreement is neither a checked proof certificate nor execution of
repository code. Every execution revalidates the source/translation and runs
fresh bounded native processes under a supplied shared resource lease.
Installed executables are trusted owner-selected tools. Their digests record
identity, not authenticity or an independent proof of solver correctness.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
import hashlib
import keyword
import math
from pathlib import Path, PurePosixPath
import platform
import shlex
import shutil
import sys
import time
from typing import Any

from .content import cid_for_bytes, cid_for_structured
from ..backends.process import BoundedToolRunner, ToolRunLimits, run_bounded_stdin_tool
from ..backends.smt.compiler import (
    INT_SORT, SmtCompilation, SmtQueryMode, SmtTerm, SmtTermKind,
    SoftwareVerificationSMTCompiler, smt_sanitize, term_eq, term_int, term_symbol,
)
from ..backends.smt.differential import normalize_smtlib_for_solver, parse_smt_solver_stdout
from ..software_verification.pipeline import (
    ContractSpec, PipelineStatus, SourceToVerificationPipeline, SourceToVerificationResult,
)
from ..software_verification.vc import VCRuleKind
from ...optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError, LeaseTimeoutError, ResourceLane, ResourceLease,
)

PROFILE = "python-integer-offset@1"
CONTRACT_SCHEMA = "codebase-integer-offset-contract@1"
COMPILED_SCHEMA = "codebase-integer-offset-compilation@1"
RESULT_SCHEMA = "codebase-integer-offset-result@1"
MAX_SOURCE_BYTES = 65536
MAX_AST_NODES = 64
MAX_LITERAL_BITS = 64
SOLVER_MEMORY_MB = 256
MAX_IO_BYTES = 65536
ASSUMPTIONS = (
    "The argument is an exact built-in Python int, excluding bool and subclasses; source annotations do not enforce this.",
    "Integer arithmetic uses the unbounded mathematical model; allocation failure, resource exhaustion and asynchronous interruption are excluded from modeled execution.",
    "The captured function is called directly with one supplied argument in sequential execution; module loading, rebinding and concurrent code changes are outside the model.",
)


class IntegerProfileError(ValueError):
    """Source, contract or translation is outside the closed profile."""


class UnsupportedIntegerProfile(IntegerProfileError):
    """Exact source is outside this deliberately small language fragment."""


def _identifier(value: Any, label: str) -> str:
    if (type(value) is not str or not value.isascii() or not value.isidentifier()
            or keyword.iskeyword(value) or len(value) > 128):
        raise IntegerProfileError(f"{label} must be a bounded ASCII identifier")
    return value


@dataclass(frozen=True, slots=True)
class IntegerOffsetContract:
    path: str
    function_name: str
    parameter: str
    offset: int

    def __post_init__(self) -> None:
        path = self.path
        if (type(path) is not str or not path or len(path.encode("utf-8")) > 512
                or "\\" in path or any(ord(c) < 32 or ord(c) == 127 for c in path)
                or PurePosixPath(path).is_absolute() or PurePosixPath(path).as_posix() != path
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or not path.endswith(".py")):
            raise IntegerProfileError("path must be a normalized relative Python file path")
        _identifier(self.function_name, "function_name")
        _identifier(self.parameter, "parameter")
        if self.parameter in {"result", self.function_name}:
            raise IntegerProfileError("parameter conflicts with the result or function name")
        if type(self.offset) is not int or self.offset.bit_length() > MAX_LITERAL_BITS:
            raise IntegerProfileError("offset must be an exact integer of at most 64 bits")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CONTRACT_SCHEMA, "profile": PROFILE, "path": self.path,
                "function_name": self.function_name, "parameter": self.parameter, "offset": self.offset}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> IntegerOffsetContract:
        if (type(value) is not dict or set(value) != {"schema", "profile", "path", "function_name", "parameter", "offset"}
                or value["schema"] != CONTRACT_SCHEMA or value["profile"] != PROFILE):
            raise IntegerProfileError("invalid integer offset contract fields or profile")
        return cls(value["path"], value["function_name"], value["parameter"], value["offset"])

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())


def _literal(node: ast.AST) -> int:
    sign = 1
    if type(node) is ast.UnaryOp and type(node.op) in {ast.UAdd, ast.USub}:
        sign = -1 if type(node.op) is ast.USub else 1
        node = node.operand
    if type(node) is not ast.Constant or type(node.value) is not int or node.value.bit_length() > MAX_LITERAL_BITS:
        raise UnsupportedIntegerProfile("return offset must be a signed integer literal of at most 64 bits")
    return sign * node.value


def _guard(source: bytes, contract: IntegerOffsetContract) -> tuple[ast.FunctionDef, int]:
    if type(source) is not bytes or not 0 < len(source) <= MAX_SOURCE_BYTES:
        raise UnsupportedIntegerProfile("source must be exact bytes within the 64 KiB bound")
    if not source.isascii() or any(c < 32 and c not in {9, 10} or c == 127 for c in source):
        raise UnsupportedIntegerProfile("source requires ASCII with only LF and tab control characters")
    try:
        tree = ast.parse(source.decode("ascii"), type_comments=True)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise UnsupportedIntegerProfile("source does not parse in the integer offset profile") from exc
    for count, _ in enumerate(ast.walk(tree), 1):
        if count > MAX_AST_NODES:
            raise UnsupportedIntegerProfile("source exceeds the AST node bound")
    if len(tree.body) != 1 or type(tree.body[0]) is not ast.FunctionDef or tree.type_ignores:
        raise UnsupportedIntegerProfile("source must contain exactly one synchronous function")
    function = tree.body[0]
    args = function.args
    int_annotation = lambda node: type(node) is ast.Name and node.id == "int"
    if (function.name != contract.function_name or function.decorator_list or function.type_comment
            or getattr(function, "type_params", ()) or not int_annotation(function.returns)
            or len(args.args) != 1 or args.args[0].arg != contract.parameter
            or not int_annotation(args.args[0].annotation) or args.args[0].type_comment
            or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults or args.kw_defaults):
        raise UnsupportedIntegerProfile("function must have one exact int parameter and int result without defaults or decorators")
    if len(function.body) != 1 or type(function.body[0]) is not ast.Return:
        raise UnsupportedIntegerProfile("function must contain exactly one value return")
    value = function.body[0].value
    if type(value) is ast.Name and value.id == contract.parameter:
        return function, 0
    if (type(value) is not ast.BinOp or type(value.op) not in {ast.Add, ast.Sub}
            or type(value.left) is not ast.Name or value.left.id != contract.parameter):
        raise UnsupportedIntegerProfile("return must be the parameter, or parameter plus/minus an integer literal")
    return function, _literal(value.right) * (-1 if type(value.op) is ast.Sub else 1)


def _term(node: ast.AST, parameter_name: str) -> SmtTerm:
    if type(node) is ast.Name:
        return term_symbol(parameter_name)
    if type(node) is ast.Constant:
        return term_int(node.value)
    if type(node) is ast.UnaryOp:
        value = _term(node.operand, parameter_name)
        return SmtTerm(SmtTermKind.NEG, arguments=(value,)) if type(node.op) is ast.USub else value
    return SmtTerm(SmtTermKind.ADD if type(node.op) is ast.Add else SmtTermKind.SUB,
                   arguments=(_term(node.left, parameter_name), _term(node.right, parameter_name)))


@dataclass(frozen=True, slots=True)
class CompiledIntegerOffset:
    contract: IntegerOffsetContract
    source_cid: str
    revision: str
    body_offset: int
    pipeline: SourceToVerificationResult
    source: bytes = field(repr=False)

    @property
    def compilation(self) -> SmtCompilation:
        return self.pipeline.obligation_results[0].compilation

    def to_dict(self) -> dict[str, Any]:
        return {"schema": COMPILED_SCHEMA, "profile": PROFILE, "contract": self.contract.to_dict(),
                "contract_cid": self.contract.cid, "source_cid": self.source_cid,
                "revision": self.revision, "body_offset": self.body_offset,
                "parser": sys.implementation.cache_tag, "assumptions": list(ASSUMPTIONS),
                "source_binding": self.pipeline.bindings.source.to_dict(),
                "compilation": self.compilation.to_dict(),
                "kernel_checked": False, "behavior_authority": False}

    @property
    def cid(self) -> str:
        return cid_for_structured(self.to_dict())


def compile_integer_offset(source: bytes, contract: IntegerOffsetContract, *, revision: str) -> CompiledIntegerOffset:
    if type(contract) is not IntegerOffsetContract:
        raise IntegerProfileError("contract must be an exact IntegerOffsetContract")
    if (type(revision) is not str or not revision or len(revision.encode("utf-8")) > 1024
            or any(ord(c) < 32 for c in revision)):
        raise IntegerProfileError("revision must be a bounded nonempty identity")
    function, offset = _guard(source, contract)
    specification = ContractSpec(contract.function_name, contract_id=contract.cid,
                                 postconditions=(f"result == {contract.parameter} + ({contract.offset})",))
    pipeline = SourceToVerificationPipeline(execute_solvers=False).run(
        source.decode("ascii"), path=contract.path, language="python", revision=revision,
        contracts=(specification,),
    )
    if (pipeline.status is not PipelineStatus.SUCCESS or pipeline.unsupported_constructs or pipeline.diagnostics
            or pipeline.bindings is None or pipeline.program is None or pipeline.adapter is None
            or len(pipeline.obligation_results) != 1 or len(pipeline.contracts) != 1):
        raise IntegerProfileError("native compiler did not admit the complete integer offset profile")
    binding = pipeline.bindings.source
    if (binding.path != contract.path or binding.language != "python" or binding.source_revision != revision
            or binding.content_sha256 != hashlib.sha256(source).hexdigest()):
        raise IntegerProfileError("native source binding differs from exact source")
    program = pipeline.program
    if len(program.functions) != 1 or len(program.symbols) != 2 or len(program.commands) != 1:
        raise IntegerProfileError("native program shape differs from the source")
    native = program.functions[0]
    symbols = {item.symbol_id: item for item in program.symbols}
    if (native.name != function.name or len(native.parameter_symbol_ids) != 1 or native.return_type != "int"
            or native.local_symbol_ids or len(native.cfg.blocks) != 1 or native.cfg.edges
            or len(native.cfg.command_ids) != 1 or native.result_symbol_id is None):
        raise IntegerProfileError("native function shape differs from the source")
    parameter = symbols[native.parameter_symbol_ids[0]]
    result = symbols[native.result_symbol_id]
    if (parameter.name != contract.parameter or parameter.type_ref != "int" or parameter.kind.value != "parameter"
            or result.name != "result" or result.type_ref != "int" or result.kind.value != "result"):
        raise IntegerProfileError("native integer symbol bindings differ")
    def name(symbol):
        return f"{smt_sanitize(symbol.name, prefix='v')[:64]}_{hashlib.sha256(symbol.symbol_id.encode()).hexdigest()}"
    parameter_name, result_name = name(parameter), name(result)
    item = pipeline.obligation_results[0]
    obligation = item.smt_obligation
    expected_body = term_eq(term_symbol(result_name), _term(function.body[0].value, parameter_name))
    expected_goal = term_eq(term_symbol(result_name), _term(ast.parse(
        f"{contract.parameter} + ({contract.offset})", mode="eval").body, parameter_name))
    if (item.solver_executed or item.differential is not None
            or item.vc_obligation.rule is not VCRuleKind.POSTCONDITION_NORMAL
            or item.vc_obligation.parent_contract_id != contract.cid
            or item.vc_obligation.assumption_expression_ids or item.vc_obligation.path_condition_expression_ids
            or obligation.query_mode is not SmtQueryMode.THEOREM_BY_NEGATION
            or len(obligation.assumptions) != 1 or obligation.assumptions[0].name != "body_return_0"
            or obligation.assumptions[0].formula != expected_body or obligation.goal != expected_goal
            or len(obligation.functions) != 2
            or {decl.name for decl in obligation.functions} != {parameter_name, result_name}
            or any(decl.range != INT_SORT or not decl.is_const or decl.domain for decl in obligation.functions)):
        raise IntegerProfileError("native body or contract SMT correspondence differs from exact source")
    if cid_for_structured(SoftwareVerificationSMTCompiler().compile(obligation).to_dict()) != cid_for_structured(item.compilation.to_dict()):
        raise IntegerProfileError("native compilation does not replay")
    compiled = CompiledIntegerOffset(contract, cid_for_bytes(source), revision, offset, pipeline, source)
    compiled.cid  # Fail before publication if the artifact is not canonically serializable.
    return compiled


def _binary_digest(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        size = 0
        while chunk := stream.read(65536):
            size += len(chunk)
            if size > 128 * 1024 * 1024:
                raise IntegerProfileError("solver executable exceeds the identity-read bound")
            digest.update(chunk)
    return digest.hexdigest()


def _native_executable(discovered: str) -> tuple[str, str]:
    """Resolve native ELF or the exact fixed launcher emitted by our installer."""
    resolved = Path(discovered).resolve()
    with resolved.open("rb") as stream:
        header = stream.read(4097)
    launcher_digest = ""
    if not header.startswith(b"\x7fELF"):
        expected = ['#!/bin/sh', 'set -eu',
                    'launcher_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
                    'export PATH="$launcher_dir${PATH:+:$PATH}"']
        try:
            lines = header.decode("ascii").splitlines()
            command = shlex.split(lines[-1])
        except (ValueError, IndexError, UnicodeDecodeError) as exc:
            raise IntegerProfileError("solver is not an admitted native executable or installer launcher") from exc
        if (len(header) > 4096 or len(lines) != 5 or lines[:4] != expected or len(command) != 3
                or command[0] != "exec" or command[2] != "$@" or not Path(command[1]).is_absolute()):
            raise IntegerProfileError("solver launcher is outside the exact installer profile")
        launcher_digest = _binary_digest(str(resolved))
        resolved = Path(command[1]).resolve()
        with resolved.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                raise IntegerProfileError("installer launcher target must be a native ELF executable")
    return str(resolved), launcher_digest


def _implementation_identity() -> dict[str, Any]:
    from ..software_verification import pipeline, source_adapters, vc
    from ..backends import process
    from ..backends.smt import compiler, differential
    modules = (sys.modules[__name__], pipeline, source_adapters, vc, process, compiler, differential)
    return {"python": sys.version, "implementation": sys.implementation.name,
            "parser": sys.implementation.cache_tag,
            "system": platform.system(), "machine": platform.machine(), "release": platform.release(),
            "resource_helper": {"kind": "linux-prlimit", "sha256": _binary_digest(process._linux_prlimit_path())},
            "source_sha256": {module.__name__: _binary_digest(module.__file__) for module in modules},
            "environment": {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                            "HOME": "private-workspace", "TMPDIR": "private-workspace",
                            "TMP": "private-workspace", "TEMP": "private-workspace"},
            "dependency_scope": "selected Python implementation files and native executables; ambient shared libraries are not attested"}


def execute_integer_offset(compiled: CompiledIntegerOffset, *, parent_lease: ResourceLease,
                           cancel_event: Any = None, timeout_seconds: float = 10.0) -> dict[str, Any]:
    """Run both native solvers; agreement is conditional evidence, not a certificate.

    Cancellation raises LeaseCancelledError. Deadline exhaustion returns timeout;
    errors and unavailable checkers cannot become proved/refuted. No caller runner
    or previously stored verdict can substitute for these native executions.
    """
    if type(compiled) is not CompiledIntegerOffset or not isinstance(parent_lease, ResourceLease):
        raise IntegerProfileError("execution requires an exact compilation and shared parent lease")
    if type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 120:
        raise IntegerProfileError("timeout_seconds must be finite, positive and at most 120")
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise IntegerProfileError("cancel_event must provide is_set")
    deadline = time.monotonic() + timeout_seconds
    cancelled = parent_lease.combined_cancellation_signal(cancel_event)
    def remaining():
        if cancelled.is_set():
            raise LeaseCancelledError("integer offset verification cancelled")
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise LeaseTimeoutError("integer offset verification deadline exceeded")
        return seconds
    remaining()
    replay = compile_integer_offset(compiled.source, compiled.contract, revision=compiled.revision)
    if (replay.cid != compiled.cid or type(compiled.pipeline) is not SourceToVerificationResult
            or cid_for_structured(replay.pipeline.to_dict()) != cid_for_structured(compiled.pipeline.to_dict())):
        raise IntegerProfileError("compiled integer profile was changed after source validation")
    checker_identity = _implementation_identity()
    runner = BoundedToolRunner(base_environment={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})
    script = "\n".join(line for line in normalize_smtlib_for_solver(replay.compilation.smtlib).splitlines()
                       if line.strip() not in {"(get-model)", "(get-unsat-core)"}) + "\n"
    observations = []
    for solver in ("z3", "cvc5"):
        observation = {"solver": solver, "status": "unavailable", "executable": "", "executable_sha256": "", "launcher_sha256": "",
                       "version": "", "verdict": "", "model_text": "", "stdout": "", "stderr": "",
                       "elapsed_ms": 0, "workspace_cleaned": True}
        try:
            remaining()
            executable = shutil.which(solver)
            if not executable:
                observations.append(observation)
                continue
            with parent_lease.acquire_child(lane=ResourceLane.VALIDATION, cpu_slots=1,
                    memory_mb=SOLVER_MEMORY_MB, child_process_slots=1,
                    timeout=remaining(), cancel_event=cancelled, request_id=f"integer-offset:{solver}") as lease:
                signal = lease.combined_cancellation_signal(cancel_event)
                executable, launcher_digest = _native_executable(executable)
                observation.update(executable=executable, executable_sha256=_binary_digest(executable), launcher_sha256=launcher_digest)
                def run(arguments, text):
                    limits = ToolRunLimits(timeout_seconds=remaining(), cpu_seconds=max(1, math.ceil(remaining())),
                        memory_bytes=SOLVER_MEMORY_MB * 1024 * 1024,
                        resident_memory_bytes=SOLVER_MEMORY_MB * 1024 * 1024,
                        max_input_bytes=MAX_IO_BYTES, max_output_bytes=MAX_IO_BYTES,
                        max_workspace_bytes=MAX_IO_BYTES)
                    raw = run_bounded_stdin_tool([executable, *arguments], text, runner=runner, limits=limits, cancellation=signal)
                    if raw.cancelled or signal.is_set():
                        raise LeaseCancelledError("native integer checker cancelled")
                    observation["elapsed_ms"] += raw.elapsed_ms
                    observation["workspace_cleaned"] &= raw.workspace_cleaned
                    if raw.timed_out:
                        raise LeaseTimeoutError("native integer checker deadline exceeded")
                    if (raw.returncode != 0 or raw.error or raw.output_truncated or raw.resource_exhausted
                            or raw.unavailable or not raw.workspace_cleaned):
                        raise IntegerProfileError("bounded native checker failed: " + (raw.error or raw.termination_reason))
                    return raw
                version = run(["-version" if solver == "z3" else "--version"], "")
                observation["version"] = (version.stdout or version.stderr).strip()
                if not observation["version"]:
                    raise IntegerProfileError("native checker version is missing")
                arguments = ["-in", "-smt2"] if solver == "z3" else ["--lang=smt2", "--produce-models"]
                raw = run(arguments, script)
                observation.update(stdout=raw.stdout, stderr=raw.stderr)
                verdict, _, _ = parse_smt_solver_stdout(raw.stdout)
                if raw.stdout.strip() != verdict:
                    raise IntegerProfileError("unexpected native checker output")
                observation.update(verdict=verdict, status={"sat": "refuted", "unsat": "proved", "unknown": "unknown"}[verdict])
                if verdict == "sat":
                    model = run(arguments, script + "(get-model)\n")
                    repeated, _, model_text = parse_smt_solver_stdout(model.stdout, expect_model=True)
                    if repeated != "sat" or not model_text or "(error" in model_text:
                        raise IntegerProfileError("native checker model does not replay the SAT verdict")
                    observation["model_text"] = model_text
                if _binary_digest(executable) != observation["executable_sha256"]:
                    raise IntegerProfileError("native checker executable changed during execution")
                remaining()
        except LeaseTimeoutError:
            observation["status"] = "timeout"
        except (OSError, ValueError) as exc:
            observation["status"] = "error"
            observation["stderr"] = str(exc)[:4096]
        observations.append(observation)
    remaining_status = "timeout" if time.monotonic() >= deadline else None
    if cancelled.is_set():
        raise LeaseCancelledError("integer offset verification cancelled")
    statuses = {item["status"] for item in observations}
    status = ("disagreement" if {"proved", "refuted"} <= statuses else
              "timeout" if remaining_status or "timeout" in statuses else
              "error" if "error" in statuses else "unavailable" if "unavailable" in statuses else
              "unknown" if "unknown" in statuses else observations[0]["status"])
    checker_identity["solvers"] = [{key: item[key] for key in
        ("solver", "executable_sha256", "launcher_sha256", "version")} for item in observations]
    return {"schema": RESULT_SCHEMA, "profile": PROFILE, "status": status,
            "compiled_cid": replay.cid, "contract_cid": replay.contract.cid,
            "source_cid": replay.source_cid, "revision": replay.revision,
            "assumptions": list(ASSUMPTIONS), "solvers": observations,
            "query_cid": cid_for_bytes(script.encode()), "evidence_kind": "conditional_smt",
            "checker_identity": checker_identity,
            "kernel_checked": False, "behavior_authority": False, "model_checked_against_runtime": False,
            "bounds": {"total_timeout_ms": math.ceil(timeout_seconds * 1000), "solver_memory_mb": SOLVER_MEMORY_MB,
                       "max_input_bytes": MAX_IO_BYTES, "max_output_bytes": MAX_IO_BYTES,
                       "max_workspace_bytes": MAX_IO_BYTES, "cpu_seconds": math.ceil(timeout_seconds),
                       "termination_grace_ms": 250, "rss_sampling_ms": 100,
                       "solver_cpu_slots": 1, "solver_process_slots": 1, "sequential_solvers": 2,
                       "max_source_bytes": MAX_SOURCE_BYTES, "max_ast_nodes": MAX_AST_NODES,
                       "max_literal_bits": MAX_LITERAL_BITS,
                       "memory_control": "per-process address-space cap and sampled process-tree RSS guard"}}


__all__ = ["PROFILE", "IntegerProfileError", "UnsupportedIntegerProfile", "IntegerOffsetContract", "CompiledIntegerOffset",
           "compile_integer_offset", "execute_integer_offset"]
