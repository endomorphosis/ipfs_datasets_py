"""Real bounded family attempts for the closed CodebaseIR integer projection.

Canonical kernel/TLA adapters and result types are reused unchanged. Their
legacy runner interface is adapted to the existing thread-safe codebase process
owner; selected native tool bytes and generated requests remain explicit.
"""
from __future__ import annotations

from dataclasses import fields
import hashlib
import json
import math
import os
from pathlib import Path
import time

from .codebase_family_lowering import CodebaseFamilyBundle, CodebaseFamilyError, _require
from .content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from ...duckdb_control.contracts import canonical_json_bytes
from ..backends import process as legacy
from ..backends import codebase_process as native
from ..backends.kernel.lean import LeanKernelBackend
from ..backends.kernel.rocq import RocqKernelBackend
from ..backends.kernel.isabelle import IsabelleKernelBackend
from ..backends.tla.runners import TLCBackend
from ..backends.smt.differential import parse_smt_solver_stdout
from ..ir_core.claims import FrozenMap, stable_digest
from ..ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
from ...optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLease, ResourceLane, LeaseCancelledError, LeaseTimeoutError

TOOL_SCHEMA = "codebase-family-tools@1"
RESULT_SCHEMA = "codebase-family-native-attempt@1"
BACKENDS = ("lean", "rocq", "isabelle", "z3", "cvc5", "tlc")
FAMILY = dict(lean="lean4", rocq="rocq", isabelle="isabelle_hol", z3="smt_lia", cvc5="smt_lia", tlc="tla_plus")
MAX_TOOL_BYTES = 256 * 1024 * 1024
MAX_IO = 256 * 1024
MEMORY_MB = dict(lean=512, rocq=512, isabelle=1536, z3=256, cvc5=256, tlc=768)
DEPENDENCY_SCOPE = "Exact owner-selected executable/launcher and explicitly listed runtime artifacts; authenticity, ambient shared libraries and transitive compiled theorem imports are trusted, not transitively attested."


def implementation_identity():
    """Exact direct producer inventory, separate from selected tool identities."""
    from . import codebase_family_lowering, codebase_integer_profile, codebase_obligation_graph
    from ..backends.kernel import lean, rocq, isabelle
    from ..backends.tla import compiler, runners
    from ..backends.smt import differential
    from ..backends import portfolio
    import sys
    modules = (sys.modules[__name__], codebase_family_lowering, codebase_integer_profile,
        codebase_obligation_graph, native, legacy, lean, rocq, isabelle, compiler, runners,
        differential, portfolio)
    return {**{m.__name__: cid_for_bytes(Path(m.__file__).read_bytes()) for m in modules},
            'native_integer_owner':codebase_integer_profile._implementation_identity()}


def _copy(value):
    return json.loads(canonical_json_bytes(value))


def _file(path, checkpoint=lambda: None):
    path = Path(path).resolve(strict=True)
    size = path.stat().st_size
    _require(path.is_file() and 0 < size <= MAX_TOOL_BYTES, "bounded regular selected tool artifact required")
    digest, read = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while block := stream.read(65536):
            checkpoint();read += len(block)
            _require(read <= MAX_TOOL_BYTES, "selected tool grew beyond identity bound")
            digest.update(block)
    _require(read == size, "selected tool size changed during sealing")
    return dict(path=str(path), bytes=size, sha256=digest.hexdigest())


def seal_family_tools(executables, *, runtime_artifacts=None):
    """Read-only preparation; no installation and no tool execution."""
    _require(type(executables) is dict and set(executables) == set(BACKENDS) | {"java"}, "closed explicit family executable set required")
    artifacts = {} if runtime_artifacts is None else runtime_artifacts
    _require(type(artifacts) is dict and set(artifacts) <= set(executables), "unknown runtime artifact family")
    tools = {}
    for backend, path in sorted(executables.items()):
        extra = artifacts.get(backend, ())
        _require(type(extra) in (tuple, list) and len(extra) <= 8, "bounded selected runtime artifact list required")
        tools[backend] = dict(executable=None if path is None else _file(path), artifacts=[_file(p) for p in extra])
    body = dict(schema=TOOL_SCHEMA, tools=tools, dependency_scope=DEPENDENCY_SCOPE)
    return dict(**body, policy_cid=cid_for_structured(body))


def _policy(value, checkpoint):
    _require(type(value) is dict and set(value) == {"schema", "tools", "dependency_scope", "policy_cid"}
             and value["schema"] == TOOL_SCHEMA and value["dependency_scope"] == DEPENDENCY_SCOPE,
             "closed native family policy required")
    _require(value["policy_cid"] == cid_for_structured({k:v for k,v in value.items() if k != "policy_cid"}), "family tool policy identity differs")
    _require(type(value["tools"]) is dict and set(value["tools"]) == set(BACKENDS) | {"java"}, "complete family tool policy required")
    for backend, descriptor in value["tools"].items():
        _require(type(descriptor) is dict and set(descriptor) == {"executable", "artifacts"}
                 and type(descriptor["artifacts"]) is list and len(descriptor["artifacts"]) <= 8,
                 "closed bounded selected tool descriptor required")
        for item in ([] if descriptor["executable"] is None else [descriptor["executable"]]) + descriptor["artifacts"]:
            _require(type(item) is dict and set(item) == {"path", "bytes", "sha256"}
                     and _file(item["path"], checkpoint) == item, "selected tool bytes changed")
    return _copy(value)


def validate_family_tools(value, *, checkpoint):
    """Detach and revalidate explicit tool bytes under the caller's deadline."""
    return _policy(value, checkpoint)


class FamilyRunner(legacy.BoundedToolRunner):
    """Dataclass bridge only; real execution stays in codebase_process."""
    def __init__(self, parent_lease, *, backend, cancellation, deadline, environment):
        _require(isinstance(parent_lease, ResourceLease) and backend in BACKENDS, "actual native parent lease and family required")
        super().__init__(base_environment=environment)
        self._native = native.BoundedToolRunner(base_environment=environment)
        self.parent_lease, self.backend, self.deadline = parent_lease, backend, deadline
        self.signal = parent_lease.combined_cancellation_signal(cancellation)
        self.observations = []

    def remaining(self):
        if self.signal.is_set():raise LeaseCancelledError("family execution cancelled")
        value = self.deadline - time.monotonic()
        if value <= 0:raise LeaseTimeoutError("family execution deadline exceeded")
        return value

    def run(self, request, *, cancellation=None, runtime=legacy.ToolRuntime.NATIVE, **kwargs):
        _require(type(request) is legacy.ToolRunRequest, "canonical backend must submit typed ToolRunRequest")
        remaining = self.remaining()
        argv = list(request.argv)
        # Enforce reviewed per-tool worker options without mutating global env.
        if self.backend == "lean" and "--json" in argv:argv[1:1] = ["-j", "1"]
        if self.backend == "isabelle" and len(argv) == 6 and argv[1:3] == ["process", "-T"] and argv[4] == "-d":
            # Isabelle2025-2 retired `process`; its native process_theories
            # owns the same explicit theory in an adhoc HOL session.
            argv = [argv[0], "process_theories", "-D", argv[5], "-l", "HOL", "-O", "-o", "threads=1", argv[3]]
        if self.backend == "tlc" and "-config" in argv:argv[1:1] = ["-workers", "1", "-fpmem", "0.05"]
        limit = request.limits
        limits = native.ToolRunLimits(timeout_seconds=min(limit.timeout_seconds,remaining),
            cpu_seconds=max(1, math.ceil(min(limit.timeout_seconds,remaining))),
            memory_bytes=64*1024**3 if self.backend == "isabelle" else (8*1024**3 if self.backend in {"lean", "rocq", "tlc"} else MEMORY_MB[self.backend]*1024**2),
            resident_memory_bytes=MEMORY_MB[self.backend]*1024**2,
            max_input_bytes=min(limit.max_input_bytes,MAX_IO), max_output_bytes=min(limit.max_output_bytes,MAX_IO),
            max_workspace_bytes=16*1024**2, max_output_files=8)
        env = dict(request.environment)
        env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", LEAN_NUM_THREADS="1")
        input_files = dict(request.input_files)
        if self.backend == "isabelle":
            # Isolate reviewed JVM/ML settings in the private tool workspace.
            # Installed/default settings (ZGC/4GiB heap) are not changed.
            input_files["launch-isabelle.sh"] = "#!/bin/sh\nset -eu\nexport USER_HOME=\"$PWD/profile-home\"\nexport ISABELLE_IDENTIFIER=CodebaseProfile\nexec \"$@\"\n"
            input_files["profile-home/.isabelle/CodebaseProfile/etc/settings"] = (
                'ISABELLE_JAVA_SYSTEM_OPTIONS="-server -Dfile.encoding=UTF-8 -Disabelle.threads=1 -XX:+UseSerialGC"\n'
                'ISABELLE_TOOL_JAVA_OPTIONS="-Djava.awt.headless=true -Xms32m -Xmx256m -Xss4m"\n'
                'ML_OPTIONS="--minheap 128 --maxheap 768"\n')
            argv = ["/bin/sh", "{workspace}/launch-isabelle.sh", *argv]
        converted = native.ToolRunRequest(argv=tuple(argv), runtime=native.ToolRuntime(request.runtime.value), limits=limits,
            stdin=request.stdin, input_files=input_files, output_paths=request.output_paths,
            environment=env, secrets=request.secrets)
        signal = self.parent_lease.combined_cancellation_signal(self.signal if cancellation is None else _Combined(self.signal,cancellation))
        raw = self._native.run(converted,cancellation=signal)
        self.observations.append(dict(command=list(raw.command), returncode=raw.returncode, stdout=raw.stdout,
            stderr=raw.stderr, elapsed_seconds=raw.elapsed_seconds, timed_out=raw.timed_out,
            cancelled=raw.cancelled, unavailable=raw.unavailable, output_truncated=raw.output_truncated,
            resource_exhausted=raw.resource_exhausted, workspace_cleaned=raw.workspace_cleaned,
            workspace_limit_exceeded=raw.workspace_limit_exceeded, process_tree_terminated=raw.process_tree_terminated,
            error=raw.error, limits={f.name:getattr(limits,f.name) for f in fields(limits)},
            input_file_cids={name:cid_for_bytes(value.encode() if isinstance(value,str) else value)
                             for name,value in input_files.items()},
            stdin_cid=None if request.stdin is None else cid_for_bytes(request.stdin.encode() if isinstance(request.stdin,str) else request.stdin),
            environment=env))
        values = {f.name:getattr(raw,f.name) for f in fields(legacy.ToolRunResult)}
        values["runtime"] = legacy.ToolRuntime(raw.runtime.value)
        return legacy.ToolRunResult(**values)


class _Combined:
    def __init__(self,*signals):self.signals=signals
    def is_set(self):return any((getattr(s,"is_set",None) or getattr(s,"is_cancelled"))() for s in self.signals if s is not None)


def _request(bundle, backend, timeout, *, bridge):
    family = "lean4" if bridge else FAMILY[backend]
    binding = bundle.to_dict()
    operation = "finite_restriction_bridge" if bridge else binding["operation"]
    identity = stable_digest(dict(bundle=binding,backend=backend,operation=operation))
    source = bundle.kernel_source(family,bridge=bridge) if backend in ("lean", "rocq", "isabelle") else ""
    payload = dict(encoding={"lean":"lean4", "rocq":"rocq", "isabelle":"isabelle"}.get(backend,family),source=source,
        translation=dict(translation_id="codebase-family:"+family,translation_digest=stable_digest(binding),
                         source_family="closed_integer_offset",target_family=family,fidelity="closed_profile",
                         bundle_cid=bundle.cid,operation=operation,source_cid=bundle.compiled.source_cid))
    return BackendRequest(request_id="family:"+identity,claim_id=bundle.cid,declaration_id=bundle.compiled.contract.cid,
        claim_digest=stable_digest(binding),obligation_id="obligation:"+identity,obligation_digest=identity,
        assumption_ids=tuple("assumption:"+stable_digest(text) for text in binding["assumptions"]),
        logic_family=family,query_kind=QueryKind.THEOREM_PROOF if backend in ("lean","rocq","isabelle") else QueryKind.SATISFIABILITY,
        bounds=ExecutionBounds(timeout_ms=max(1,math.floor(timeout*1000)),max_steps=2,max_memory_bytes=MEMORY_MB[backend]*1024**2,max_output_bytes=MAX_IO),
        payload=FrozenMap(payload),requested_backend_id=backend)


def _execute_family(bundle, tools, *, backend, parent_lease, cancel_event=None, timeout_seconds=60, bridge=False):
    """Execute one exact mathematical attempt; no stored verdict can substitute."""
    _require(type(bundle) is CodebaseFamilyBundle and backend in BACKENDS and (not bridge or backend=="lean"), "closed native family attempt required")
    _require(type(timeout_seconds) in (int,float) and math.isfinite(timeout_seconds) and 0<timeout_seconds<=300, "bounded family deadline required")
    _require(isinstance(parent_lease,ResourceLease), "actual native resource parent required")
    deadline=time.monotonic()+timeout_seconds
    signal=parent_lease.combined_cancellation_signal(cancel_event)
    def checkpoint():
        if signal.is_set():raise LeaseCancelledError("family attempt cancelled")
        if time.monotonic()>=deadline:raise LeaseTimeoutError("family attempt deadline exceeded")
    checkpoint()
    bundle=CodebaseFamilyBundle(bundle.compiled,bundle.inputs)
    policy=_policy(tools,checkpoint)
    selection=policy['tools'][backend]['executable']
    producers=implementation_identity()
    result=dict(schema=RESULT_SCHEMA,backend=backend,family=FAMILY[backend],bundle_cid=bundle.cid,
        source_cid=bundle.compiled.source_cid,contract_cid=bundle.compiled.contract.cid,
        operation='finite_restriction_bridge' if bridge else bundle.to_dict()['operation'],
        tools=policy,status='unavailable',request=None,receipt=None,native_observations=[],
        producer=producers,source_runtime_semantics_verified=False,mathematical_model_only=True)
    if selection is None:return result
    paths=[str(Path(v['executable']['path']).parent) for v in policy['tools'].values() if v['executable']]
    environment=dict(PATH=os.pathsep.join(dict.fromkeys(paths+['/usr/bin','/bin'])),LANG='C',LC_ALL='C',HOME=str(Path.home()))
    runner=FamilyRunner(parent_lease,backend=backend,cancellation=signal,deadline=deadline,environment=environment)
    request=_request(bundle,backend,deadline-time.monotonic(),bridge=bridge)
    result['request']=request.to_dict()
    executable=selection['path']
    try:
        if backend in ('lean','rocq','isabelle'):
            cls={'lean':LeanKernelBackend,'rocq':RocqKernelBackend,'isabelle':IsabelleKernelBackend}[backend]
            family_backend=cls(executable=executable,runner=runner,backend_version='selected-sha256:'+selection['sha256'],logic_families=(FAMILY[backend],))
            outcome=family_backend.run(request,cancellation=signal)
            result['receipt']=outcome.receipt.to_dict();result['backend_result']=outcome.result.to_dict()
            if outcome.result.status.value=='proved' and outcome.receipt.accepted:
                result['status']='proved' if bridge or bundle.compiled.body_offset==bundle.compiled.contract.offset else 'refuted'
            else:result['status']=outcome.result.status.value
        elif backend in ('z3','cvc5'):
            args=['-in','-smt2'] if backend=='z3' else ['--lang=smt2']
            raw=runner.run(legacy.ToolRunRequest(argv=(executable,*args),stdin=bundle.smt_source(),
                limits=legacy.ToolRunLimits(timeout_seconds=runner.remaining(),max_input_bytes=MAX_IO,max_output_bytes=MAX_IO)))
            if raw.timed_out:result['status']='timeout'
            elif raw.unavailable:result['status']='unavailable'
            elif raw.returncode==0 and not any((raw.error,raw.output_truncated,raw.resource_exhausted,raw.cancelled,raw.workspace_limit_exceeded)):
                verdict,_,_=parse_smt_solver_stdout(raw.stdout)
                _require(raw.stdout.strip()==verdict,"unexpected SMT response")
                result['status']={'unsat':'proved','sat':'refuted','unknown':'unknown'}[verdict]
                result['receipt']=dict(kind='conditional_native_smt_response',query_cid=cid_for_bytes(bundle.smt_source().encode()),verdict=verdict,kernel_checked=False)
            else:result['status']='error'
        else:
            java=policy['tools']['java']['executable']
            if java is None:return result
            jvm=runner.run(legacy.ToolRunRequest(argv=(java['path'],'-version'),limits=legacy.ToolRunLimits(timeout_seconds=min(5,runner.remaining()),max_output_bytes=65536)))
            java_ok=jvm.returncode==0 and not any((jvm.error,jvm.timed_out,jvm.cancelled,jvm.resource_exhausted))
            # This probe is an actual bounded invocation under the same lease,
            # not a fixture-supplied availability flag or an ambient subprocess.
            checker=TLCBackend(executable=executable,runner=runner,jvm_probe=lambda:java_ok,lazy_install=False)
            outcome=checker.check(bundle.tla()[1],request=request,cancellation=signal)
            result['receipt']=outcome.receipt.to_dict();result['backend_result']=outcome.result.to_dict()
            result['status']={'satisfied':'proved','violated':'refuted'}.get(outcome.result.status.value,outcome.result.status.value)
        checkpoint();_policy(policy,checkpoint)
        _require(producers==implementation_identity(), 'family implementation changed during native execution')
    except LeaseTimeoutError:
        result['status']='timeout'
    except LeaseCancelledError:
        result['status']='cancelled'
    finally:
        result['native_observations']=runner.observations
    if signal.is_set():result['status']='cancelled'
    if result['status'] not in ('timeout','cancelled'):checkpoint()
    _require(len(canonical_json_bytes(result))<=4*1024**2,'family result exceeds byte bound')
    return _copy(result)


def execute_family(bundle, tools, *, backend, parent_lease, cancel_event=None, timeout_seconds=60, bridge=False):
    """Acquire a real child capacity reservation before native family work."""
    _require(backend in BACKENDS and isinstance(parent_lease, ResourceLease), "actual native parent and supported backend required")
    _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds) and 0 < timeout_seconds <= 300,
             "bounded family deadline required")
    deadline = time.monotonic() + timeout_seconds
    with parent_lease.acquire_child(lane=ResourceLane.VALIDATION, cpu_slots=1, memory_mb=MEMORY_MB[backend],
            child_process_slots=1, timeout=timeout_seconds, cancel_event=cancel_event,
            request_id="codebase-family:" + backend) as child:
        remaining = deadline - time.monotonic()
        if remaining <= 0:raise LeaseTimeoutError("family admission consumed deadline")
        result = _execute_family(bundle, tools, backend=backend, parent_lease=child,
            cancel_event=cancel_event, timeout_seconds=remaining, bridge=bridge)
        result["resource_binding"] = dict(parent_lease_id=parent_lease.lease_id, child_lease_id=child.lease_id,
            cpu_slots=child.cpu_slots, memory_mb=child.memory_mb, process_slots=child.child_process_slots)
        return result
