"""Exhaustive observations of a closed integer source over a finite domain.

The owner runs captured bytes with pinned native tools. Lean checks arithmetic
about the recorded table, not the physical origin of those observations or
general CPython semantics. No historical verdict bypasses either execution.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any

from .codebase_integer_profile import (
    IntegerOffsetContract, UnsupportedIntegerProfile, compile_integer_offset,
)
from .codebase_ir import RepositoryCodebaseIndex
from .codebase_resources import acquire_codebase_resources
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from ..backends.process import BoundedToolRunner, ToolRunLimits
from ...optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError, LeaseTimeoutError, ResourceLane,
)

PROFILE = "python-integer-offset-finite@1"
SCHEMA = "codebase-finite-integer-observation@1"
TOOL_SCHEMA = "codebase-finite-integer-tools@1"
DOMAIN_SCHEMA = "codebase-finite-integer-domain@1"
TRACE_SCHEMA = "codebase-finite-integer-trace@1"
MAX_BINARY_BYTES = 128 * 1024 * 1024
MAX_IO_BYTES = 256 * 1024
MAX_WORKSPACE_BYTES = 4 * 1024 * 1024
_FALSE = {name: False for name in (
    "source_semantics_verified", "runtime_behavior_verified", "behavior_authority",
    "proof_authority", "execution_authority", "completion_authority", "mutation_authority",
)}
SCOPE = "Exhaustive observations over the exact declared finite integer inputs only; Lean certifies recorded table arithmetic, not CPython observation origin, universal source semantics, module loading, resource failures or worker admission."
_CERTIFICATE_SCOPE = "Kernel-checked recorded finite table arithmetic under standard trusted compiled Init imports; observation origin and CPython semantics are not Lean theorems."
_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
        "LEAN_NUM_THREADS": "1", "LEAN_STACK_SIZE_KB": "8192"}
_DEPENDENCY_SCOPE = "Exact selected native executable bytes; ambient shared libraries, Python standard library and Lean compiled imports are not transitively attested."
_LEAN_ARGS = ["-j", "1", "-o", "FiniteInteger.olean", "FiniteInteger.lean"]
_LIMITS = {"python": {"address_space_bytes": 512 * 1024 * 1024, "resident_memory_bytes": 512 * 1024 * 1024},
           "lean": {"address_space_bytes": 4 * 1024 * 1024 * 1024, "resident_memory_bytes": 512 * 1024 * 1024},
           "max_input_bytes": MAX_IO_BYTES, "max_output_bytes": MAX_IO_BYTES,
           "max_workspace_bytes": MAX_WORKSPACE_BYTES, "max_output_files": 8,
           "lean_arguments": list(_LEAN_ARGS),
           "memory_control": "Per-process virtual-address cap and sampled process-tree RSS guard; shared admission reserves 512 MiB per child; this is not a kernel aggregate cgroup limit."}


class FiniteIntegerObservationError(ValueError):
    """Malformed input or changed source, tool, trace or certificate binding."""


def _copy(value):
    try:
        raw = canonical_dag_json_bytes(value)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("record byte bound")
        return json.loads(raw)
    except (ValueError, TypeError, RecursionError) as error:
        raise FiniteIntegerObservationError("bounded exact canonical JSON required") from error


def _domain(inputs):
    if (type(inputs) is not list or not 1 <= len(inputs) <= 32
            or any(type(value) is not int or abs(value) > 2**31 for value in inputs)
            or inputs != sorted(set(inputs))):
        raise FiniteIntegerObservationError("inputs must be 1–32 sorted unique exact integers of magnitude at most 2^31")
    return {"schema": DOMAIN_SCHEMA, "profile": PROFILE, "inputs": list(inputs)}


def build_finite_integer_domain(inputs: list[int]) -> dict[str, Any]:
    """Validate and detach the complete explicit domain without running tools."""
    return _domain(inputs)


def _digest(path: Path, checkpoint=lambda: None):
    digest, size = hashlib.sha256(), 0
    checkpoint()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            checkpoint()
            size += len(chunk)
            if size > MAX_BINARY_BYTES:
                raise FiniteIntegerObservationError("native executable exceeds identity bound")
            digest.update(chunk)
    checkpoint()
    return digest.hexdigest(), size


def _tool(path: Path, checkpoint=lambda: None):
    if not isinstance(path, Path):
        raise FiniteIntegerObservationError("native tool must be a Path")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise FiniteIntegerObservationError("native tool must be a regular file")
    with resolved.open("rb") as stream:
        if stream.read(4) != b"\x7fELF":
            raise FiniteIntegerObservationError("select the installed native ELF tool, not a launcher")
    if resolved.parent.name == "bin" and resolved.parent.parent.name == ".elan":
        raise FiniteIntegerObservationError("select installed native Lean, not an elan shim")
    digest, size = _digest(resolved, checkpoint)
    return {"path": str(resolved), "sha256": digest, "size_bytes": size}


def seal_finite_integer_tools(*, python_executable: Path, lean_executable: Path) -> dict[str, Any]:
    """Seal caller-selected native binary identities without running a tool.

    This is a preparation policy, not an attestation of the whole machine or
    transitive Python/Lean runtime libraries. Observation checks these pins
    before and after each invocation under its overall deadline.
    """
    policy = {"schema": TOOL_SCHEMA, "profile": PROFILE,
              "python": _tool(python_executable), "lean": _tool(lean_executable),
              "environment": dict(_ENV), "process_limits": _copy(_LIMITS),
              "dependency_scope": _DEPENDENCY_SCOPE}
    policy["policy_cid"] = cid_for_structured(policy)
    return _copy(policy)


def _policy(value, checkpoint=lambda: None):
    policy = _copy(value)
    if (type(policy) is not dict or set(policy) != {
            "schema", "profile", "python", "lean", "environment", "process_limits", "dependency_scope", "policy_cid"}
            or policy["schema"] != TOOL_SCHEMA or policy["profile"] != PROFILE
            or policy["environment"] != _ENV or policy["dependency_scope"] != _DEPENDENCY_SCOPE
            or canonical_dag_json_bytes(policy["process_limits"]) != canonical_dag_json_bytes(_LIMITS)):
        raise FiniteIntegerObservationError("invalid finite native tool policy")
    body = {key: item for key, item in policy.items() if key != "policy_cid"}
    if policy["policy_cid"] != cid_for_structured(body):
        raise FiniteIntegerObservationError("native tool policy identity differs")
    for name in ("python", "lean"):
        tool = policy[name]
        if type(tool) is not dict or set(tool) != {"path", "sha256", "size_bytes"}:
            raise FiniteIntegerObservationError("complete closed native tool pin required")
        if type(tool["path"]) is not str or str(Path(tool["path"]).resolve(strict=True)) != tool["path"]:
            raise FiniteIntegerObservationError("native tool path must remain canonical")
        if canonical_dag_json_bytes(_tool(Path(tool["path"]), checkpoint)) != canonical_dag_json_bytes(tool):
            raise FiniteIntegerObservationError("pinned native tool changed")
    return policy


_DRIVER = r'''import ast, hashlib, json, pathlib, sys
request = json.loads(pathlib.Path("request.json").read_text(encoding="ascii"))
raw = pathlib.Path("captured_source.py").read_bytes()
assert hashlib.sha256(raw).hexdigest() == request["source_sha256"]
tree = ast.parse(raw, type_comments=True)
assert len(tree.body) == 1 and type(tree.body[0]) is ast.FunctionDef
namespace = {"__builtins__": {"int": int}}
exec(compile(raw, "captured_source.py", "exec"), namespace, namespace)
function = namespace[request["function_name"]]
rows = []
trace = {"schema": "codebase-finite-integer-trace@1", "source_cid": request["source_cid"],
         "source_sha256": request["source_sha256"], "domain_cid": request["domain_cid"],
         "inputs": request["inputs"], "observations": rows, "status": "complete",
         "exception_type": None,
         "python": {"executable": str(pathlib.Path(sys.executable).resolve()),
                    "version": sys.version, "implementation": sys.implementation.name,
                    "cache_tag": sys.implementation.cache_tag}}
try:
    for value in request["inputs"]:
        assert type(value) is int and abs(value) <= 2**31
        result = function(value)
        if type(result) is not int:
            raise TypeError("exact integer result required")
        rows.append({"input": value, "output": result, "input_type": "int", "output_type": "int"})
except BaseException as error:
    trace["status"] = "exception"
    trace["exception_type"] = type(error).__name__
print(json.dumps(trace, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False))
'''


def _lean(rows, inputs, body_offset, offset, trace_cid, source_cid, domain_cid):
    integer = lambda value: "(" + str(value) + " : Int)"
    input_text = ", ".join(integer(value) for value in inputs)
    row_text = ", ".join("(" + integer(row["input"]) + ", " + integer(row["output"]) + ")" for row in rows)
    lines = ["import Init", "-- Recorded table arithmetic only; no Python-origin or universal-runtime theorem.",
             "-- source " + source_cid, "-- domain " + domain_cid, "-- trace " + trace_cid,
             "namespace CodebaseFiniteInteger", "set_option autoImplicit false",
             "def inputs : List Int := [" + input_text + "]",
             "def rows : List (Int × Int) := [" + row_text + "]",
             "theorem domain_coverage : rows.map Prod.fst = inputs := by decide",
             "theorem recorded_integer_types : (" + str(len(rows)) + " : Nat) = inputs.length := by decide",
             "theorem observed_body_offset : rows.all (fun row => decide (row.2 = row.1 + " + integer(body_offset) + ")) = true := by decide"]
    names = ["domain_coverage", "recorded_integer_types", "observed_body_offset"]
    counterexample = next((row for row in rows if row["output"] != row["input"] + offset), None)
    if counterexample is None:
        lines.append("theorem offset_clause : rows.all (fun row => decide (row.2 = row.1 + " + integer(offset) + ")) = true := by decide")
        names.append("offset_clause")
    else:
        lines.append("theorem offset_counterexample : " + integer(counterexample["output"]) + " ≠ " + integer(counterexample["input"]) + " + " + integer(offset) + " := by decide")
        names.append("offset_counterexample")
    return ("\n".join(lines + ["end CodebaseFiniteInteger", ""])).encode(), names


def _process(raw, limits):
    return {"interface_version": raw.interface_version, "command": list(raw.command),
            "returncode": raw.returncode, "stdout": raw.stdout, "stderr": raw.stderr,
            "elapsed_ms": max(0, int(raw.elapsed_seconds * 1000)), "limits": limits,
            **{name: getattr(raw, name) for name in (
                "timed_out", "cancelled", "unavailable", "output_truncated",
                "workspace_limit_exceeded", "process_tree_terminated", "resource_exhausted",
                "workspace_cleaned", "termination_reason", "error")}}


def _success(raw):
    return (raw.returncode == 0 and not raw.error and not raw.stderr
            and not any(getattr(raw, name) for name in (
                "timed_out", "cancelled", "unavailable", "output_truncated",
                "workspace_limit_exceeded", "resource_exhausted"))
            and raw.workspace_cleaned)


def _artifact(output, name, raw):
    path = output / name
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw), "cid": cid_for_bytes(raw)}


def observe_finite_integer_source(
    *, index, repository, expected_head, contract: IntegerOffsetContract,
    inputs: list[int], output: Path, tool_policy, scheduler=None, parent_lease=None,
    cancel_event=None, admission_timeout_seconds=30, timeout_seconds=60, memory_mb=1024,
) -> dict[str, Any]:
    """Observe every declared case and certify its finite recorded table.

    Malformed inputs/tool drift, stale source and cancellation raise. Unsupported
    source or failed native checks return non-covering records. Output is private
    and fresh; neither repository code imports nor historical verdicts run here.
    ``result_cid`` identifies the record body excluding that self-ID. The full
    returned record is separately retained in CAS at ``cid_for_structured(result)``.
    """
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    if (type(index) is not RepositoryCodebaseIndex or index.catalog is None or index.artifacts is None
            or type(expected_head) is not CodebaseHead or type(contract) is not IntegerOffsetContract):
        raise FiniteIntegerObservationError("canonical current source owner, head and integer contract required")
    domain = _domain(inputs)
    inputs = list(domain["inputs"])
    tool_policy = _copy(tool_policy)
    contract = IntegerOffsetContract.from_dict(contract.to_dict())
    expected_head = CodebaseHead.from_dict(expected_head.to_dict())
    if (type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 300 or type(memory_mb) is not int or memory_mb < 1024):
        raise FiniteIntegerObservationError("bounded deadline and at least 1024 MiB reservation required")
    if (type(admission_timeout_seconds) not in {int, float} or not math.isfinite(admission_timeout_seconds)
            or admission_timeout_seconds < 0):
        raise FiniteIntegerObservationError("nonnegative finite admission timeout required")
    if not isinstance(output, Path) or not output.is_absolute() or output != output.resolve():
        raise FiniteIntegerObservationError("fresh canonical absolute output Path required")
    repository = Path(repository).resolve(strict=True)
    if output == repository or repository in output.parents or output.exists():
        raise FiniteIntegerObservationError("fresh output must be outside the tested repository")
    deadline = time.monotonic() + timeout_seconds
    with acquire_codebase_resources(scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, timeout_seconds=min(admission_timeout_seconds, timeout_seconds),
            memory_mb=memory_mb) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)
        def remaining():
            if signal.is_set():
                raise LeaseCancelledError("finite integer observation cancelled")
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise LeaseTimeoutError("finite integer observation deadline exceeded")
            return seconds
        policy = _policy(tool_policy, remaining)
        def observe():
            duration = remaining()
            return index.observe_current(repository, expected_head=expected_head, parent_lease=lease,
                cancel_event=signal, admission_timeout_seconds=min(admission_timeout_seconds, duration),
                timeout_seconds=duration, memory_mb=512)
        current = observe()
        output.mkdir(parents=True, mode=0o700, exist_ok=False)
        artifacts = {"tool_policy": _artifact(output, "tool_policy.json", canonical_dag_json_bytes(policy))}
        result = {"schema": SCHEMA, "profile": PROFILE, "status": "unsupported",
            "head": expected_head.to_dict(), "source_path": contract.path,
            "source_cid": None, "source_sha256": None, "compiled_cid": None,
            "contract": contract.to_dict(), "contract_cid": contract.cid,
            "domain_inputs": inputs, "domain_cid": cid_for_structured(domain),
            "observations": [], "trace": None, "trace_cid": None,
            "tool_policy": policy, "tool_policy_cid": policy["policy_cid"],
            "python_process": None, "lean_certificate": None,
            "artifacts": artifacts, "output": str(output),
            "type_clause_satisfied": False, "offset_clause_satisfied": False,
            "runtime_observation_coverage_complete": False, "kernel_checked_model_table": False,
            "counterexample": None, "scope": SCOPE, "diagnostics": [], **_FALSE}
        runner = BoundedToolRunner(base_environment=_ENV)
        def run(tool, arguments, input_files, output_paths=()):
            remaining()
            if _tool(Path(policy[tool]["path"]), remaining) != policy[tool]:
                raise FiniteIntegerObservationError("pinned tool drift before execution")
            with lease.acquire_child(lane=ResourceLane.VALIDATION, cpu_slots=1, memory_mb=512,
                    child_process_slots=1, timeout=remaining(), cancel_event=signal,
                    request_id="finite-integer:" + tool) as child:
                limits = ToolRunLimits(timeout_seconds=remaining(), cpu_seconds=max(1, math.ceil(remaining())),
                    memory_bytes=policy["process_limits"][tool]["address_space_bytes"],
                    resident_memory_bytes=policy["process_limits"][tool]["resident_memory_bytes"],
                    max_input_bytes=MAX_IO_BYTES, max_output_bytes=MAX_IO_BYTES,
                    max_workspace_bytes=MAX_WORKSPACE_BYTES, max_output_files=8)
                raw = runner.run([policy[tool]["path"], *arguments], input_files=input_files,
                    output_paths=output_paths, limits=limits, cancellation=child.combined_cancellation_signal(signal))
                if raw.cancelled or signal.is_set():
                    raise LeaseCancelledError("finite native tool cancelled")
            if _tool(Path(policy[tool]["path"]), remaining) != policy[tool]:
                raise FiniteIntegerObservationError("pinned tool drift after execution")
            remaining()
            return raw, {"timeout_ms": math.ceil(limits.timeout_seconds * 1000),
                "cpu_seconds": limits.cpu_seconds, "address_space_bytes": limits.memory_bytes,
                "resident_memory_bytes": limits.resident_memory_bytes,
                "max_input_bytes": limits.max_input_bytes, "max_output_bytes": limits.max_output_bytes,
                "max_workspace_bytes": limits.max_workspace_bytes, "max_output_files": limits.max_output_files}
        entry = next((item for item in current.manifest.snapshot.entries if item.path == contract.path), None)
        if entry is None or entry.is_opaque:
            result["diagnostics"] = ["selected source is absent or opaque in current captured snapshot"]
        else:
            source = index.artifacts.get_bytes(entry.source_cid)
            result.update(source_cid=entry.source_cid, source_sha256=hashlib.sha256(source).hexdigest())
            artifacts["source"] = _artifact(output, "captured_source.py", source)
            remaining()
            try:
                compiled = compile_integer_offset(source, contract, revision="snapshot:" + expected_head.snapshot_cid)
            except UnsupportedIntegerProfile as error:
                result["diagnostics"] = [str(error)]
            else:
                if compiled.source_cid != entry.source_cid:
                    raise FiniteIntegerObservationError("captured source identity differs after compilation")
                result["compiled_cid"] = compiled.cid
                artifacts["compiled"] = _artifact(output, "compiled.json", canonical_dag_json_bytes(compiled.to_dict()))
                request = {"source_cid": entry.source_cid, "source_sha256": result["source_sha256"],
                           "function_name": contract.function_name, "inputs": inputs, "domain_cid": result["domain_cid"]}
                artifacts["driver"] = _artifact(output, "driver.py", _DRIVER.encode())
                artifacts["request"] = _artifact(output, "request.json", canonical_dag_json_bytes(request))
                raw, python_limits = run("python", ["-I", "-S", "driver.py"],
                    {"driver.py": _DRIVER, "captured_source.py": source, "request.json": canonical_dag_json_bytes(request)})
                result["python_process"] = _process(raw, python_limits)
                artifacts["python_process"] = _artifact(output, "python_process.json", canonical_dag_json_bytes(result["python_process"]))
                result["status"] = "python_failed"
                if not _success(raw):
                    result["diagnostics"] = ["bounded isolated Python observation failed"]
                else:
                    try:
                        trace = json.loads(raw.stdout)
                        rows = trace["observations"]
                        if (set(trace) != {"schema", "source_cid", "source_sha256", "domain_cid", "inputs", "observations", "status", "exception_type", "python"}
                                or trace["schema"] != TRACE_SCHEMA or trace["status"] != "complete" or trace["exception_type"] is not None
                                or trace["source_cid"] != entry.source_cid or trace["source_sha256"] != result["source_sha256"]
                                or trace["domain_cid"] != result["domain_cid"] or trace["inputs"] != inputs
                                or type(rows) is not list or len(rows) != len(inputs)
                                or trace["python"]["executable"] != policy["python"]["path"]
                                or trace["python"]["implementation"] != "cpython"
                                or any(type(row) is not dict or set(row) != {"input", "output", "input_type", "output_type"}
                                    or type(row["input"]) is not int or row["input"] != value
                                    or type(row["output"]) is not int or abs(row["output"]) > 2**66
                                    or row["input_type"] != "int" or row["output_type"] != "int"
                                    for row, value in zip(rows, inputs))):
                            raise ValueError("incomplete exact trace")
                        trace = _copy(trace)
                    except (ValueError, TypeError, KeyError, AttributeError) as error:
                        result["diagnostics"] = ["isolated Python did not produce the complete exact finite trace"]
                    else:
                        result.update(trace=trace, trace_cid=cid_for_structured(trace), observations=rows)
                        artifacts["trace"] = _artifact(output, "observations.json", canonical_dag_json_bytes(trace))
                        text, theorems = _lean(rows, inputs, compiled.body_offset, contract.offset,
                            result["trace_cid"], entry.source_cid, result["domain_cid"])
                        artifacts["lean_source"] = _artifact(output, "FiniteInteger.lean", text)
                        version, version_limits = run("lean", ["--version"], {})
                        checked, lean_limits = run("lean", _LEAN_ARGS,
                            {"FiniteInteger.lean": text}, ("FiniteInteger.olean",))
                        certificate = {"schema": "codebase-finite-integer-table-certificate@1",
                            "source_cid": cid_for_bytes(text), "olean_cid": None,
                            "trace_cid": result["trace_cid"], "domain_cid": result["domain_cid"],
                            "tool": policy["lean"], "version_process": _process(version, version_limits),
                            "process": _process(checked, lean_limits), "theorems": theorems,
                            "scope": _CERTIFICATE_SCOPE}
                        result["lean_certificate"] = certificate
                        artifacts["lean_process"] = _artifact(output, "lean_process.json", canonical_dag_json_bytes({
                            "version_process": certificate["version_process"], "process": certificate["process"]}))
                        result["status"] = "lean_failed"
                        if (not _success(version) or not version.stdout.startswith("Lean (version ")
                                or not _success(checked) or checked.stdout or not checked.output_files.get("FiniteInteger.olean")):
                            result["diagnostics"] = ["native Lean failed the finite recorded table certificate"]
                        else:
                            binary = checked.output_files["FiniteInteger.olean"]
                            artifacts["lean_olean"] = _artifact(output, "FiniteInteger.olean", binary)
                            certificate["olean_cid"] = cid_for_bytes(binary)
                            result.update(status="observed", type_clause_satisfied=True,
                                offset_clause_satisfied=all(row["output"] == row["input"] + contract.offset for row in rows),
                                runtime_observation_coverage_complete=True, kernel_checked_model_table=True)
                            wrong = next((row for row in rows if row["output"] != row["input"] + contract.offset), None)
                            if wrong is not None:
                                result["counterexample"] = {"input": wrong["input"], "observed_output": wrong["output"],
                                    "required_output": wrong["input"] + contract.offset}
                        artifacts["lean_certificate"] = _artifact(output, "lean_certificate.json", canonical_dag_json_bytes(certificate))
        remaining()
        _policy(policy, remaining)
        result["result_cid"] = cid_for_structured(result)
        sealed = _copy(result)
        index.artifacts.put(sealed)
        _artifact(output, "result.json", canonical_dag_json_bytes(sealed))
        observe()  # Publication does not authorize a result against a changed head.
        _policy(policy, remaining)
        remaining()
        return sealed


def validate_finite_integer_observation(
    result, *, expected_head, contract: IntegerOffsetContract, inputs: list[int], tool_policy,
) -> dict[str, Any]:
    """Recompute a retained record and all its local artifact relationships.

    This performs no native invocation and is not a historical execution bypass.
    Consumers obtain records by calling the observer themselves, check current
    source through its owner, and use this validator only as an integrity guard.
    It cannot establish physical execution from an arbitrary caller's JSON.
    """
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
    if type(expected_head) is not CodebaseHead or type(contract) is not IntegerOffsetContract:
        raise FiniteIntegerObservationError("canonical expected head and contract required")
    domain = _domain(inputs)
    policy = _policy(tool_policy)
    value = _copy(result)
    fields = {"schema", "profile", "status", "head", "source_path", "source_cid", "source_sha256",
        "compiled_cid", "contract", "contract_cid", "domain_inputs", "domain_cid", "observations", "trace",
        "trace_cid", "tool_policy", "tool_policy_cid", "python_process", "lean_certificate", "artifacts",
        "output", "type_clause_satisfied", "offset_clause_satisfied", "runtime_observation_coverage_complete",
        "kernel_checked_model_table", "counterexample", "scope", "diagnostics", "result_cid", *_FALSE}
    if (type(value) is not dict or set(value) != fields or value["schema"] != SCHEMA or value["profile"] != PROFILE
            or value["status"] not in {"observed", "unsupported", "python_failed", "lean_failed"}
            or canonical_dag_json_bytes(value["head"]) != canonical_dag_json_bytes(expected_head.to_dict())
            or canonical_dag_json_bytes(value["contract"]) != canonical_dag_json_bytes(contract.to_dict())
            or value["contract_cid"] != contract.cid or value["source_path"] != contract.path
            or canonical_dag_json_bytes(_domain(value["domain_inputs"])) != canonical_dag_json_bytes(domain)
            or value["domain_cid"] != cid_for_structured(domain)
            or canonical_dag_json_bytes(value["tool_policy"]) != canonical_dag_json_bytes(policy)
            or value["tool_policy_cid"] != policy["policy_cid"]
            or value["scope"] != SCOPE or any(value[name] is not False for name in _FALSE)):
        raise FiniteIntegerObservationError("finite observation fields, source/domain bindings or authority differ")
    for name in ("type_clause_satisfied", "offset_clause_satisfied", "runtime_observation_coverage_complete", "kernel_checked_model_table"):
        if type(value[name]) is not bool:
            raise FiniteIntegerObservationError("exact finite clause booleans required")
    if value["result_cid"] != cid_for_structured({key: item for key, item in value.items() if key != "result_cid"}):
        raise FiniteIntegerObservationError("finite observation content identity differs")
    output = Path(value["output"])
    if not output.is_absolute() or output != output.resolve(strict=True) or not output.is_dir():
        raise FiniteIntegerObservationError("finite artifact directory is not canonical")
    raws = {}
    if type(value["artifacts"]) is not dict or len(value["artifacts"]) > 16:
        raise FiniteIntegerObservationError("bounded complete finite artifact map required")
    for name, descriptor in value["artifacts"].items():
        if (type(descriptor) is not dict or set(descriptor) != {"path", "sha256", "size_bytes", "cid"}
                or type(descriptor["path"]) is not str or type(descriptor["size_bytes"]) is not int
                or not 0 <= descriptor["size_bytes"] <= MAX_WORKSPACE_BYTES):
            raise FiniteIntegerObservationError("invalid finite artifact descriptor")
        path = Path(descriptor["path"])
        if path.parent != output or path != path.resolve(strict=True) or not path.is_file():
            raise FiniteIntegerObservationError("finite artifact escaped its canonical directory")
        with path.open("rb") as stream:
            raw = stream.read(MAX_WORKSPACE_BYTES + 1)
        if (len(raw) != descriptor["size_bytes"] or hashlib.sha256(raw).hexdigest() != descriptor["sha256"]
                or cid_for_bytes(raw) != descriptor["cid"]):
            raise FiniteIntegerObservationError("finite artifact bytes changed")
        raws[name] = raw
    if raws.get("tool_policy") != canonical_dag_json_bytes(policy):
        raise FiniteIntegerObservationError("finite tool policy artifact differs")
    if value["source_cid"] is not None:
        source = raws.get("source")
        if (source is None or cid_for_bytes(source) != value["source_cid"]
                or hashlib.sha256(source).hexdigest() != value["source_sha256"]):
            raise FiniteIntegerObservationError("finite source bytes differ")
    else:
        source = None
        if value["source_sha256"] is not None or "source" in raws:
            raise FiniteIntegerObservationError("absent finite source has a forged byte binding")
    compiled = None
    if value["compiled_cid"] is not None:
        if source is None:
            raise FiniteIntegerObservationError("finite compilation requires captured source")
        compiled = compile_integer_offset(source, contract, revision="snapshot:" + expected_head.snapshot_cid)
        if value["compiled_cid"] != compiled.cid or raws.get("compiled") != canonical_dag_json_bytes(compiled.to_dict()):
            raise FiniteIntegerObservationError("finite source compilation does not replay")
        if raws.get("driver") != _DRIVER.encode():
            raise FiniteIntegerObservationError("finite isolated observation driver differs")
        request = {"source_cid": value["source_cid"], "source_sha256": value["source_sha256"],
                   "function_name": contract.function_name, "inputs": domain["inputs"], "domain_cid": value["domain_cid"]}
        if raws.get("request") != canonical_dag_json_bytes(request):
            raise FiniteIntegerObservationError("finite execution request differs")
    if value["python_process"] is not None and raws.get("python_process") != canonical_dag_json_bytes(value["python_process"]):
        raise FiniteIntegerObservationError("finite Python process artifact differs")
    def check_process(process, tool):
        fields = {"interface_version", "command", "returncode", "stdout", "stderr", "elapsed_ms", "limits",
            "timed_out", "cancelled", "unavailable", "output_truncated", "workspace_limit_exceeded",
            "process_tree_terminated", "resource_exhausted", "workspace_cleaned", "termination_reason", "error"}
        if (type(process) is not dict or set(process) != fields
                or process["returncode"] is not None and type(process["returncode"]) is not int
                or type(process["elapsed_ms"]) is not int or process["elapsed_ms"] < 0
                or any(type(process[name]) is not str for name in ("interface_version", "stdout", "stderr", "termination_reason", "error"))
                or any(type(process[name]) is not bool for name in ("timed_out", "cancelled", "unavailable", "output_truncated",
                    "workspace_limit_exceeded", "process_tree_terminated", "resource_exhausted", "workspace_cleaned"))):
            raise FiniteIntegerObservationError("complete exact finite native process receipt required")
        limits = process["limits"]
        if (type(limits) is not dict or set(limits) != {"timeout_ms", "cpu_seconds", "address_space_bytes",
                "resident_memory_bytes", "max_input_bytes", "max_output_bytes", "max_workspace_bytes", "max_output_files"}
                or any(type(item) is not int or item <= 0 for item in limits.values())
                or limits["timeout_ms"] > 300000 or limits["cpu_seconds"] > 300
                or limits["address_space_bytes"] != policy["process_limits"][tool]["address_space_bytes"]
                or limits["resident_memory_bytes"] != policy["process_limits"][tool]["resident_memory_bytes"]
                or any(limits[name] != policy["process_limits"][name] for name in
                    ("max_input_bytes", "max_output_bytes", "max_workspace_bytes", "max_output_files"))):
            raise FiniteIntegerObservationError("finite native process limits differ from the sealed profile")
    if value["python_process"] is not None:
        check_process(value["python_process"], "python")
    trace, rows = value["trace"], value["observations"]
    if trace is not None:
        if (type(trace) is not dict or set(trace) != {"schema", "source_cid", "source_sha256", "domain_cid", "inputs", "observations", "status", "exception_type", "python"}
                or trace["schema"] != TRACE_SCHEMA or trace["status"] != "complete" or trace["exception_type"] is not None
                or trace["source_cid"] != value["source_cid"] or trace["source_sha256"] != value["source_sha256"]
                or trace["domain_cid"] != value["domain_cid"]
                or canonical_dag_json_bytes(_domain(trace["inputs"])) != canonical_dag_json_bytes(domain)
                or canonical_dag_json_bytes(trace["observations"]) != canonical_dag_json_bytes(rows)
                or value["trace_cid"] != cid_for_structured(trace)
                or raws.get("trace") != canonical_dag_json_bytes(trace)
                or type(rows) is not list or len(rows) != len(domain["inputs"])
                or type(trace["python"]) is not dict or set(trace["python"]) != {"executable", "version", "implementation", "cache_tag"}
                or trace["python"]["executable"] != policy["python"]["path"] or trace["python"]["implementation"] != "cpython"
                or any(type(trace["python"][name]) is not str or not trace["python"][name] for name in
                    ("version", "implementation", "cache_tag"))
                or any(type(row) is not dict or set(row) != {"input", "output", "input_type", "output_type"}
                    or type(row["input"]) is not int or row["input"] != number or type(row["output"]) is not int
                    or row["input_type"] != "int" or row["output_type"] != "int"
                    for row, number in zip(rows, domain["inputs"]))):
            raise FiniteIntegerObservationError("finite complete trace/domain relation differs")
        process = value["python_process"]
        if (compiled is None or process is None or process["command"] != [policy["python"]["path"], "-I", "-S", "driver.py"]
                or json.loads(process["stdout"]) != trace):
            raise FiniteIntegerObservationError("finite trace is not bound to the isolated Python command")
    elif rows or value["trace_cid"] is not None:
        raise FiniteIntegerObservationError("absent trace cannot cover finite observations")
    certificate = value["lean_certificate"]
    if certificate is not None:
        if (compiled is None or trace is None or type(certificate) is not dict
                or set(certificate) != {"schema", "source_cid", "olean_cid", "trace_cid", "domain_cid", "tool", "version_process", "process", "theorems", "scope"}
                or certificate["schema"] != "codebase-finite-integer-table-certificate@1"
                or certificate["trace_cid"] != value["trace_cid"] or certificate["domain_cid"] != value["domain_cid"]
                or certificate["scope"] != _CERTIFICATE_SCOPE
                or canonical_dag_json_bytes(certificate["tool"]) != canonical_dag_json_bytes(policy["lean"])):
            raise FiniteIntegerObservationError("finite Lean certificate bindings differ")
        check_process(certificate["process"], "lean")
        check_process(certificate["version_process"], "lean")
        text, theorems = _lean(rows, domain["inputs"], compiled.body_offset, contract.offset,
            value["trace_cid"], value["source_cid"], value["domain_cid"])
        if (raws.get("lean_source") != text or certificate["source_cid"] != cid_for_bytes(text)
                or certificate["theorems"] != theorems or raws.get("lean_certificate") != canonical_dag_json_bytes(certificate)
                or raws.get("lean_process") != canonical_dag_json_bytes({"version_process": certificate["version_process"], "process": certificate["process"]})
                or certificate["process"]["command"] != [policy["lean"]["path"], *_LEAN_ARGS]
                or certificate["version_process"]["command"] != [policy["lean"]["path"], "--version"]):
            raise FiniteIntegerObservationError("finite Lean table does not replay from exact observations")
    if value["status"] == "observed":
        def succeeded(process):
            return (process["returncode"] == 0 and not process["stderr"] and not process["error"]
                and process["workspace_cleaned"] is True and all(process[name] is False for name in
                ("cancelled", "timed_out", "unavailable", "output_truncated", "workspace_limit_exceeded", "resource_exhausted")))
        expected_clause = all(row["output"] == row["input"] + contract.offset for row in rows)
        wrong = next((row for row in rows if row["output"] != row["input"] + contract.offset), None)
        witness = None if wrong is None else {"input": wrong["input"], "observed_output": wrong["output"], "required_output": wrong["input"] + contract.offset}
        if (trace is None or certificate is None or not succeeded(value["python_process"])
                or not succeeded(certificate["version_process"]) or not succeeded(certificate["process"])
                or not certificate["version_process"]["stdout"].startswith("Lean (version ") or certificate["process"]["stdout"]
                or not raws.get("lean_olean") or certificate["olean_cid"] != cid_for_bytes(raws["lean_olean"])
                or value["type_clause_satisfied"] is not True or value["offset_clause_satisfied"] is not expected_clause
                or value["runtime_observation_coverage_complete"] is not True or value["kernel_checked_model_table"] is not True
                or canonical_dag_json_bytes(value["counterexample"]) != canonical_dag_json_bytes(witness)
                or any(row["output"] != row["input"] + compiled.body_offset for row in rows)):
            raise FiniteIntegerObservationError("observed finite clauses require complete genuine process/certificate bindings")
    elif any(value[name] is not False for name in ("type_clause_satisfied", "offset_clause_satisfied", "runtime_observation_coverage_complete", "kernel_checked_model_table")) or value["counterexample"] is not None:
        raise FiniteIntegerObservationError("incomplete native observation cannot claim finite coverage")
    result_path = output / "result.json"
    with result_path.open("rb") as stream:
        recorded = stream.read(2 * 1024 * 1024 + 1)
    if recorded != canonical_dag_json_bytes(value):
        raise FiniteIntegerObservationError("sealed finite result file differs")
    return value


__all__ = ["PROFILE", "SCHEMA", "TOOL_SCHEMA", "DOMAIN_SCHEMA", "TRACE_SCHEMA",
           "FiniteIntegerObservationError", "build_finite_integer_domain", "seal_finite_integer_tools",
           "observe_finite_integer_source", "validate_finite_integer_observation"]
