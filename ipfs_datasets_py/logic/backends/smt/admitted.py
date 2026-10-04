"""Admitted native transports for the public Z3 and CVC5 adapters.

The compiler modules and differential semantics remain compatibility owners.
These subclasses replace native process transport only: successful observations
still pass through their original compiler, parser and evidence rules. Explicit
callable runners remain trusted injection points. Default native execution owns
one shared reservation per phase and bounds query, applicable artifact replay
and version discovery with one deadline. Native scripts must fit the closed
single-check profile. This is admission and sampled RSS protection, not a
cgroup ceiling.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
import time

from ...ir_core.protocols import ExecutionBounds
from .. import process
from ..process import BoundedToolRunner, ToolRunLimits, ToolRunRequest
from ..registry import BackendRequest, BackendRunnerOutput
from ..resource_admission import ResourceAdmittedToolRunner
from ..z3.compiler import Z3Backend as _Z3Backend, Z3SoftwareVerificationBackend as _Z3SV
from ..cvc5.compiler import CVC5Backend as _CVC5Backend, CVC5SoftwareVerificationBackend as _CVC5SV
from .differential import SmtRawSolverOutput
from .operation_budget import current_proof_operation
from ...parsers.smtlib import SAtom, SList, read_sexprs
from ...syntax_core.contracts import ParseLimits
from ...software_contracts.codebase_smt_protocol import (
    SmtProtocolError, split_smt_script, parse_verdict, artifact_script,
    validate_artifact_response, MAX_PROTOCOL_BYTES,
)

DEFAULT_MAX_INPUT_BYTES = 1_048_576


def _bounded_source(source, limit):
    if type(source) is not str or len(source) > limit:
        raise _Failure("native SMT input must be an exact bounded string")
    try:
        if len(source.encode("utf-8")) > limit or "\x00" in source:
            raise _Failure("native SMT input exceeds byte bound or contains NUL")
    except UnicodeError as error:
        raise _Failure("native SMT input must be valid UTF-8") from error


def _split_native_script(source, *, registry):
    """Validate a closed single-check profile without rewriting its assertions.

    Registry compilers additionally emit numeric :timeout/:rlimit options. Only
    those options are blanked in a same-length validation copy; the bytes sent
    to the solver retain them. All other options use the unchanged closed
    protocol, which refuses parallel settings and incremental commands.
    """
    validation = source
    if registry:
        forms, diagnostics = read_sexprs(source, limits=ParseLimits(
            max_input_bytes=MAX_PROTOCOL_BYTES, max_tokens=65_536, max_depth=64))
        if diagnostics:
            raise _Failure("native SMT registry script is malformed")
        ranges = []
        checked = False
        for form in forms:
            if not isinstance(form, SList) or not form.items:
                continue  # The closed protocol diagnoses all other forms.
            head = form.items[0]
            if not isinstance(head, SAtom) or head.kind != "symbol":
                continue
            if head.value == "check-sat":
                checked = True
            if (head.value == "set-option" and len(form.items) == 3
                    and isinstance(form.items[1], SAtom) and form.items[1].kind == "keyword"
                    and form.items[1].value in {":timeout", ":rlimit"}):
                value = form.items[2]
                if (checked or not isinstance(value, SAtom) or value.kind != "numeral"
                        or not value.value.isascii() or not value.value.isdecimal()):
                    raise _Failure("native SMT resource options require prefix nonnegative numerals")
                ranges.append((form.range.start_char, form.range.end_char))
        if ranges:
            parts, cursor = [], 0
            for start, end in ranges:
                parts.extend((source[cursor:start], "".join("\n" if ch == "\n" else " " for ch in source[start:end])))
                cursor = end
            parts.append(source[cursor:])
            validation = "".join(parts)
    try:
        validated_base, model, core = split_smt_script(validation)
    except SmtProtocolError as error:
        raise _Failure(f"unsupported native SMT single-check profile: {error}") from error
    # split_smt_script appends exactly one newline to the original prefix.
    return source[:len(validated_base) - 1] + "\n", validated_base, model, core


class _Failure(RuntimeError):
    def __init__(self, reason: str, *, timed_out=False, unavailable=False):
        self.timed_out = timed_out
        self.unavailable = unavailable
        super().__init__(" ".join(str(reason).split())[:512] or "native SMT operation failed")


class _Signals:
    def __init__(self, *signals):
        self.signals = tuple(signal for signal in signals if signal is not None)

    def is_set(self):
        return any(process._is_cancelled(signal) for signal in self.signals)


@dataclass
class _Operation:
    started: float
    deadline: float
    signal: _Signals
    version: str = ""

    def checkpoint(self):
        if self.signal.is_set():
            raise _Failure("native SMT operation cancelled")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _Failure("native SMT operation deadline exhausted", timed_out=True)
        return remaining

    def elapsed_ms(self):
        return max(0, int((time.monotonic() - self.started) * 1000))


class _NativeTransport:
    def __init__(self, solver, executable, *, tool_runner, scheduler, parent_lease,
                 max_input_bytes, version_probe=None):
        if tool_runner is not None and (scheduler is not None or parent_lease is not None):
            raise ValueError("supply tool_runner or scheduler/parent_lease, not both")
        if tool_runner is not None and not isinstance(tool_runner, BoundedToolRunner):
            raise TypeError("tool_runner must be a BoundedToolRunner")
        if type(max_input_bytes) is not int or not 0 < max_input_bytes <= MAX_PROTOCOL_BYTES:
            raise ValueError("max_input_bytes must be a positive integer no greater than the protocol byte limit")
        self.solver, self.executable = solver, executable
        self.runner = tool_runner if tool_runner is not None else ResourceAdmittedToolRunner(
            scheduler=scheduler, parent_lease=parent_lease)
        self.max_input_bytes = max_input_bytes
        self.version_probe = version_probe
        self.last_version = ""

    def _phase(self, argv, stdin, bounds, operation, *, output_budget):
        if output_budget <= 0:
            raise _Failure("native SMT combined output budget exhausted")
        remaining = operation.checkpoint()
        _bounded_source(stdin, self.max_input_bytes)
        request = ToolRunRequest(argv=tuple(argv), stdin=stdin,
            limits=ToolRunLimits(timeout_seconds=remaining, cpu_seconds=remaining,
                memory_bytes=bounds.max_memory_bytes, resident_memory_bytes=bounds.max_memory_bytes,
                max_input_bytes=self.max_input_bytes, max_output_bytes=output_budget,
                max_workspace_bytes=max(16_777_216, self.max_input_bytes)))
        try:
            observed = self.runner.run(request, cancellation=operation.signal)
        except Exception as error:
            raise _Failure(f"native SMT lifecycle failed: {type(error).__name__}: {error}") from error
        operation.checkpoint()
        if observed.timed_out:
            raise _Failure(observed.error or "native SMT phase timed out", timed_out=True)
        if observed.unavailable:
            raise _Failure(observed.error or "native SMT executable unavailable", unavailable=True)
        reasons = [name for name in (
            "cancelled", "resource_exhausted", "output_truncated", "workspace_limit_exceeded",
            "process_tree_terminated",
        ) if getattr(observed, name)]
        if not observed.workspace_cleaned:
            reasons.append("workspace_not_cleaned")
        if observed.returncode != 0:
            reasons.append(f"returncode={observed.returncode}")
        if observed.error:
            reasons.append(observed.error)
        if reasons:
            raise _Failure("native SMT phase rejected: " + ", ".join(reasons))
        used = len(observed.stdout.encode("utf-8")) + len(observed.stderr.encode("utf-8"))
        if used > output_budget:
            raise _Failure("native SMT combined output exceeds byte bound")
        return observed, used

    def query(self, source, bounds, operation, *, registry=False):
        remaining = operation.checkpoint()
        _bounded_source(source, self.max_input_bytes)
        base, validation_base, model_requested, core_requested = _split_native_script(source, registry=registry)
        if self.solver == "z3":
            argv = (self.executable, "-in", "-smt2")
            version_argv = (self.executable, "-version")
        else:
            argv = (self.executable, "--lang=smt2",
                    f"--tlimit-per={max(1, min(bounds.timeout_ms, int(remaining * 1000)))}",
                    f"--rlimit={bounds.max_steps}")
            version_argv = (self.executable, "--version")
        query, used = self._phase(argv, base, bounds, operation,
                                  output_budget=bounds.max_output_bytes)
        try:
            verdict = parse_verdict(query.stdout)
            if query.stderr.strip():
                raise SmtProtocolError("native SMT verdict has unexpected stderr")
            followup = artifact_script(validation_base, verdict, model_requested, core_requested)
        except SmtProtocolError as error:
            raise _Failure(f"native SMT verdict protocol failed: {error}") from error
        if followup is not None:
            command, kind = (("get-model", "model") if verdict == "sat"
                             else ("get-unsat-core", "unsat_core"))
            query, artifact_used = self._phase(argv, base + f"({command})\n", bounds, operation,
                output_budget=bounds.max_output_bytes - used)
            used += artifact_used
            try:
                if query.stderr.strip():
                    raise SmtProtocolError("native SMT artifact has unexpected stderr")
                validate_artifact_response(query.stdout, verdict, kind)
            except SmtProtocolError as error:
                raise _Failure(f"native SMT artifact protocol failed: {error}") from error
        operation.checkpoint()
        if self.version_probe is None:
            version, _ = self._phase(version_argv, "", bounds, operation,
                output_budget=min(65_536, bounds.max_output_bytes - used))
            lines = (version.stdout or version.stderr).strip().splitlines()
            version_text = lines[0] if lines else ""
        else:
            # An explicitly supplied metadata callback belongs to its caller.
            try:
                version_text = self.version_probe()
            except Exception as error:
                raise _Failure(f"explicit version probe failed: {type(error).__name__}: {error}") from error
        operation.checkpoint()
        if not isinstance(version_text, str) or not version_text.strip() or len(version_text.encode("utf-8")) > 512:
            raise _Failure("native SMT version observation is empty or exceeds its bound")
        if used + len(version_text.encode("utf-8")) > bounds.max_output_bytes:
            raise _Failure("native SMT combined query/version output exceeds byte bound")
        operation.version = version_text
        self.last_version = version_text
        return query


class _AdmittedMixin:
    def _configure(self, solver, executable, *, runner, tool_runner, scheduler, parent_lease,
                   cancellation, max_input_bytes, version_probe=None):
        if runner is not None and (tool_runner is not None or scheduler is not None or parent_lease is not None):
            raise ValueError("an explicit callable runner owns its lifecycle; do not also supply native ownership")
        if runner is not None and not callable(runner):
            raise TypeError("runner must be callable")
        if version_probe is not None and not callable(version_probe):
            raise TypeError("version_probe must be callable")
        self._injected_runner = runner
        self._supplied_version_probe = version_probe
        self._default_cancellation = cancellation
        self._operation_context = ContextVar("admitted_smt_operation", default=None)
        self._transport = None if runner is not None else _NativeTransport(
            solver, executable, tool_runner=tool_runner, scheduler=scheduler, parent_lease=parent_lease,
            max_input_bytes=max_input_bytes, version_probe=version_probe)

    @contextmanager
    def _operation(self, bounds, cancellation=None):
        if not isinstance(bounds, ExecutionBounds):
            raise TypeError("bounds must be an ExecutionBounds")
        prior = self._operation_context.get()
        outer = current_proof_operation()
        started = time.monotonic()
        deadline = min(prior.deadline, started + bounds.timeout_ms / 1000) if prior else started + bounds.timeout_ms / 1000
        if outer is not None:
            deadline = min(deadline, outer.deadline)
        operation = _Operation(prior.started if prior else started,
            deadline,
            _Signals(outer, self._default_cancellation, prior.signal if prior else None, cancellation))
        token = self._operation_context.set(operation)
        try:
            yield operation
        finally:
            self._operation_context.reset(token)

    def _current(self):
        operation = self._operation_context.get()
        if operation is None:
            raise _Failure("native SMT execution requires an active bounded operation")
        return operation


class _AdmittedGeneric(_AdmittedMixin):
    def run(self, request, *, cancellation=None):
        if not isinstance(request, BackendRequest):
            raise TypeError("request must be a BackendRequest")
        with self._operation(request.bounds, cancellation):
            return super().run(request)

    def _execute_native(self, compiled, request):
        operation = self._current()
        try:
            operation.checkpoint()
            if self._injected_runner is not None:
                result = self._injected_runner(compiled, request)
                operation.checkpoint()
                return result
            observed = self._transport.query(compiled.source, request.bounds, operation, registry=True)
            return BackendRunnerOutput(stdout=observed.stdout, stderr=observed.stderr,
                returncode=0, elapsed_ms=operation.elapsed_ms(), solver_version=operation.version)
        except _Failure as error:
            if error.timed_out:
                raise TimeoutError(str(error)) from error
            if error.unavailable:
                raise OSError(str(error)) from error
            return BackendRunnerOutput(stdout="", stderr=str(error), returncode=1,
                                       elapsed_ms=min(operation.elapsed_ms(), request.bounds.timeout_ms))


class _AdmittedSV(_AdmittedMixin):
    def run(self, obligation, *, bounds=None, cancellation=None):
        effective = bounds or ExecutionBounds(timeout_ms=5_000, max_steps=100_000)
        with self._operation(effective, cancellation):
            return super().run(obligation, bounds=effective)

    def run_compilation(self, compilation, *, bounds, cancellation=None):
        with self._operation(bounds, cancellation):
            return super().run_compilation(compilation, bounds=bounds)

    def solver_version(self):
        """Return operation-local or last checked metadata without a subprocess.

        Failed operations never borrow another thread's or prior run's version.
        Explicit version callbacks retain caller ownership. Before the first
        native success, the cached version is unknown (the empty string).
        """
        operation = self._operation_context.get()
        if operation is not None:
            return operation.version
        if self._supplied_version_probe is not None:
            try:
                value = self._supplied_version_probe()
                return value if isinstance(value, str) else ""
            except Exception:
                return ""
        return self._transport.last_version if self._transport is not None else ""

    def _execute_native(self, source, bounds):
        operation = self._current()
        try:
            operation.checkpoint()
            if self._injected_runner is not None:
                raw = self._injected_runner(source, bounds)
                operation.checkpoint()
                if (isinstance(raw, SmtRawSolverOutput) and not raw.solver_version
                        and not raw.timed_out and not raw.unavailable and raw.returncode == 0
                        and self._supplied_version_probe is not None):
                    try:
                        value = self._supplied_version_probe()
                    except Exception:
                        value = ""
                    operation.checkpoint()
                    if isinstance(value, str):
                        raw = replace(raw, solver_version=value)
                return raw
            observed = self._transport.query(source, bounds, operation)
            return SmtRawSolverOutput(stdout=observed.stdout, stderr=observed.stderr,
                returncode=0, elapsed_ms=operation.elapsed_ms(), solver_version=operation.version)
        except _Failure as error:
            # Frozen SV semantics accept some nonzero observations with stdout.
            # Never let an interrupted/truncated native verdict reach that parser.
            operation.version = ""
            return SmtRawSolverOutput(stdout="", stderr=str(error), returncode=1,
                elapsed_ms=min(operation.elapsed_ms(), bounds.timeout_ms),
                timed_out=error.timed_out, unavailable=error.unavailable)


class Z3Backend(_AdmittedGeneric, _Z3Backend):
    def __init__(self, *, executable="z3", runner=None, availability_probe=None, compiler=None,
                 tool_runner=None, scheduler=None, parent_lease=None, cancellation=None,
                 max_input_bytes=DEFAULT_MAX_INPUT_BYTES):
        self._configure("z3", executable, runner=runner, tool_runner=tool_runner, scheduler=scheduler,
            parent_lease=parent_lease, cancellation=cancellation, max_input_bytes=max_input_bytes)
        super().__init__(executable=executable, runner=self._execute_native,
                         availability_probe=availability_probe, compiler=compiler)


class CVC5Backend(_AdmittedGeneric, _CVC5Backend):
    def __init__(self, *, executable="cvc5", runner=None, availability_probe=None, compiler=None,
                 tool_runner=None, scheduler=None, parent_lease=None, cancellation=None,
                 max_input_bytes=DEFAULT_MAX_INPUT_BYTES):
        self._configure("cvc5", executable, runner=runner, tool_runner=tool_runner, scheduler=scheduler,
            parent_lease=parent_lease, cancellation=cancellation, max_input_bytes=max_input_bytes)
        super().__init__(executable=executable, runner=self._execute_native,
                         availability_probe=availability_probe, compiler=compiler)


class Z3SoftwareVerificationBackend(_AdmittedSV, _Z3SV):
    def __init__(self, *, executable="z3", runner=None, availability_probe=None, compiler=None,
                 version_probe=None, tool_runner=None, scheduler=None, parent_lease=None,
                 cancellation=None, max_input_bytes=DEFAULT_MAX_INPUT_BYTES):
        executable = executable.strip() if isinstance(executable, str) else executable
        self._configure("z3", executable, runner=runner, tool_runner=tool_runner, scheduler=scheduler,
            parent_lease=parent_lease, cancellation=cancellation, max_input_bytes=max_input_bytes,
            version_probe=version_probe)
        super().__init__(executable=executable, runner=self._execute_native, compiler=compiler,
                         availability_probe=availability_probe, version_probe=lambda: "")


class CVC5SoftwareVerificationBackend(_AdmittedSV, _CVC5SV):
    def __init__(self, *, executable="cvc5", runner=None, availability_probe=None, compiler=None,
                 version_probe=None, tool_runner=None, scheduler=None, parent_lease=None,
                 cancellation=None, max_input_bytes=DEFAULT_MAX_INPUT_BYTES):
        executable = executable.strip() if isinstance(executable, str) else executable
        self._configure("cvc5", executable, runner=runner, tool_runner=tool_runner, scheduler=scheduler,
            parent_lease=parent_lease, cancellation=cancellation, max_input_bytes=max_input_bytes,
            version_probe=version_probe)
        super().__init__(executable=executable, runner=self._execute_native, compiler=compiler,
                         availability_probe=availability_probe, version_probe=lambda: "")


__all__ = ["Z3Backend", "CVC5Backend", "Z3SoftwareVerificationBackend", "CVC5SoftwareVerificationBackend"]
