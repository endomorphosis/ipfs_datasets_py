"""Replay source-derived finite states and check their ProgramIR correspondence.

The caller supplies exact candidate predictions and finite input domains. A
rejected prediction remains visible; neither a compiler nor a model repairs it.
Kernel checks establish only the generated finite ProgramIR/state relation,
under the source adapter's declared integer assumptions.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType
import weakref

from . import source_program_lake_384 as original_gate
from . import native_family_lake_v4 as executor
from . import native_tla_projection as tla
from . import source_state_lean as emitter
from .security import source_state_model as derivation

SCHEMA = "source-state-384-lake/v1"
MAX_ROWS = 16
FALSE = dict(proof_authority=False, execution_authority=False,
    completion_authority=False, mutation_authority=False,
    source_semantics_verified=False, whole_program_semantics_verified=False,
    security_specification_inferred=False, normative_compliance_verified=False,
    admitted=False, qualified=False, claim_proved=False, promotion_performed=False,
    source_executed=False, model_checker_executed=False)
_ISSUED = weakref.WeakKeyDictionary()


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _owners():
    """Include imported native owner dependencies, not only facade modules."""
    from ....optimizers.logic_theorem_optimizer import autoencoder_schema_lake
    pending = list((sys.modules[__name__], derivation, emitter, tla, autoencoder_schema_lake,
        *derivation.PRODUCERS, *emitter.PRODUCERS, *original_gate._owners()))
    prefixes = tuple("ipfs_datasets_py.logic." + name + "." for name in
        ("ir_core", "software_verification", "syntax_core", "families", "backends"))
    found = {}
    while pending:
        module = pending.pop()
        if module.__name__ in found:
            continue
        found[module.__name__] = module
        for value in vars(module).values():
            name = value.__name__ if isinstance(value, ModuleType) else getattr(value, "__module__", "")
            if isinstance(name, str) and name.startswith(prefixes):
                owner = sys.modules.get(name)
                if owner is not None and getattr(owner, "__file__", None) and name not in found:
                    pending.append(owner)
    return tuple(found[name] for name in sorted(found))


def _pins():
    return {str(Path(module.__file__).resolve()): _sha(Path(module.__file__).read_bytes())
        for module in _owners()}


_IMPORTED = _pins()


def _guard():
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    original_gate._guard()
    for module in _owners():
        _pin_imported_module(module)
    _require(_pins() == _IMPORTED, "source state producer changed after import")


def _rows(rows):
    _require(type(rows) is list and 1 <= len(rows) <= MAX_ROWS,
        "one to sixteen explicit source-state candidates required")
    try:
        encoded = _raw(rows)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("inert source-state JSON rows required") from error
    _require(len(encoded) <= 4 * 1024 * 1024, "source-state batch exceeds byte bound")
    for row in rows:
        _require(type(row) is dict and set(row) ==
            {"id", "source_text", "candidate_ir", "input_domains"},
            "closed source-state rows required; targets are forbidden")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 256,
            "bounded source-state row identity required")
        _require(type(row["source_text"]) is str and
            0 < len(row["source_text"].encode()) <= 65536,
            "bounded original source text required")
    _require(len({row["id"] for row in rows}) == len(rows),
        "unique source-state row identities required")
    return json.loads(encoded)


def prepare_source_state_lean(rows):
    """Derive every selected state table; keep unsupported predictions as rows."""
    _guard()
    inputs = _rows(rows)
    results, lines = [], ["namespace SecuritySourceStates"]
    for index, row in enumerate(inputs):
        result = dict(id=row["id"], source_sha256=_sha(row["source_text"].encode()),
            candidate_sha256=_sha(_raw(row["candidate_ir"])),
            input_domains_sha256=_sha(_raw(row["input_domains"])),
            status="unsupported", reason=None, model=None,
            semantic_lowering_supported=False, lake_status="blocked", sany_status="not_run",
            finite_correspondence_kernel_checked=False, **FALSE)
        try:
            model = derivation.derive_source_state_model(row["source_text"],
                row["candidate_ir"], row["input_domains"])
            source, details = emitter.emit_source_state_model(model)
            _require(source.strip(), "empty source-state declarations")
            wrapped = f"namespace Candidate_{index}\n{source}\nend Candidate_{index}"
            lines.append(wrapped)
            result.update(status="prepared", model=model, lowering=details,
                semantic_lowering_supported=True, lake_status="not_run",
                case_count=len(model["cases"]),
                lean_declarations_sha256=_sha(wrapped.encode()))
        except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
            # Errors identify closed contract boundaries, not arbitrary source text.
            result.update(reason=str(error)[:1024], error_type=type(error).__name__)
        results.append(result)
    lines.append("end SecuritySourceStates\n")
    source = "\n\n".join(lines)
    _require(len(source.encode()) <= 4 * 1024 * 1024,
        "generated source-state module exceeds byte bound")
    _guard()
    return dict(schema=SCHEMA, library="SecuritySourceStates", rows=results,
        input_sha256=_sha(_raw(inputs)), producer=_pins(), status="prepared",
        producer_pin_scope="listed producer modules and imported native owner closure; excludes generated methods, Python and external libraries",
        lean_source=source, lean_source_sha256=_sha(source.encode()),
        backend_executed=False, source_replay_passed=True, all_candidates_checked=False,
        automatic_operational_model=True, input_domains_inferred=False,
        candidate_repaired=False, model_inference_performed=False,
        finite_correspondence_kernel_checked=False, training_steps=0, provider_calls=0,
        download_calls=0, scope="finite source-derived ProgramIR/state correspondence under explicit integer input assumptions",
        **FALSE)


@dataclass(frozen=True, eq=False)
class SourceStateLakeExecution:
    """A saved dictionary is evidence; only a live issued handle can be replayed."""
    def to_dict(self):
        _require(self in _ISSUED, "unissued source-state build handle")
        return json.loads(_ISSUED[self]["receipt"])


def build_source_state_lake(rows, *, lake_executable, java_executable=None,
        tla2tools_jar=None, timeout_seconds=60, output_directory=None):
    _require(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 60,
        "bounded source-state check timeout required")
    _require(bool(java_executable) == bool(tla2tools_jar),
        "Java and tla2tools must be selected together")
    output = Path(output_directory).resolve() if output_directory is not None else None
    _require(output is None or not output.exists(), "fresh source-state evidence directory required")
    prepared = prepare_source_state_lean(rows)
    receipt = deepcopy(prepared)
    supported = [row for row in receipt["rows"] if row["semantic_lowering_supported"]]
    tool_pins = {}
    found = shutil.which(str(lake_executable)) if supported else None
    if found:
        native_lake = Path(found).resolve()
        for tool in (native_lake, native_lake.with_name("lean")):
            if tool.is_file():
                tool_pins[str(tool)] = _sha(tool.read_bytes())
    execution = (executor._execute(receipt["lean_source"], receipt["library"],
        lake_executable, timeout_seconds) if supported else
        dict(status="blocked", backend_executed=False, reason="no_supported_source_states"))
    if execution.get("executable_sha256"):
        used = Path(execution["command"][0]).resolve()
        _require(tool_pins.get(str(used)) == execution["executable_sha256"] and
            str(used.with_name("lean")) in tool_pins, "native Lake and Lean identities required")
    passed = execution["status"] == "passed" and execution["backend_executed"] is True
    for row in supported:
        row.update(lake_status="passed" if passed else execution["status"],
            finite_correspondence_kernel_checked=passed,
            status="passed" if passed else execution["status"])
        if java_executable:
            syntax = tla.check_sany(row["lowering"]["bounded_tla"],
                java_executable=java_executable, tla2tools_jar=tla2tools_jar,
                timeout_seconds=timeout_seconds)
            row.update(sany_status=syntax["status"], syntax_check=syntax)
            for path, checksum in syntax.get("tool_sha256", {}).items():
                _require(path not in tool_pins or tool_pins[path] == checksum,
                    "source-state tool changed between checks")
                tool_pins[path] = checksum
            if syntax["status"] != "passed":
                row["status"] = "partial" if passed else row["status"]
    _guard()
    _require(prepare_source_state_lean(rows) == prepared,
        "source-state inputs or derived model changed during checks")
    for path, expected in tool_pins.items():
        _require(_sha(Path(path).read_bytes()) == expected, "source-state tool changed during checks")
    complete = passed and len(supported) == len(receipt["rows"]) and all(
        row["sany_status"] == "passed" if java_executable else True for row in supported)
    receipt.update(status="passed" if complete else "partial" if passed else execution["status"],
        execution=execution, backend_executed=execution["backend_executed"],
        all_candidates_checked=complete,
        finite_correspondence_kernel_checked=passed and len(supported) == len(receipt["rows"]),
        supported_count=len(supported), count=len(receipt["rows"]),
        sany_requested=bool(java_executable), tool_binary_sha256=tool_pins,
        tool_pin_scope="Lake/Lean binaries and selected Java/JAR, not complete toolchain libraries")
    if output is not None:
        output.mkdir(parents=True)
        (output / "SecuritySourceStates.lean").write_bytes(receipt["lean_source"].encode())
        (output / "receipt.json").write_bytes(_raw(receipt))
        for index, row in enumerate(receipt["rows"]):
            if row["semantic_lowering_supported"]:
                (output / f"state-{index}.tla").write_bytes(row["lowering"]["bounded_tla"]["model_text"].encode())
    handle = SourceStateLakeExecution()
    _ISSUED[handle] = dict(receipt=_raw(receipt), input_sha256=receipt["input_sha256"], tool_pins=tool_pins)
    return handle


def verify_source_state_lake(execution, rows):
    _guard()
    _require(type(execution) is SourceStateLakeExecution and execution in _ISSUED,
        "live issued source-state build handle required")
    state = _ISSUED[execution]
    _require(_sha(_raw(_rows(rows))) == state["input_sha256"], "source-state input identity differs")
    for path, checksum in state["tool_pins"].items():
        _require(_sha(Path(path).read_bytes()) == checksum, "source-state tool changed")
    receipt = json.loads(state["receipt"])
    replay = prepare_source_state_lean(rows)
    _require(replay["lean_source_sha256"] == receipt["lean_source_sha256"] and
        replay["producer"] == receipt["producer"], "source-state declaration replay differs")
    return receipt


__all__ = ["prepare_source_state_lean", "build_source_state_lake",
    "verify_source_state_lake", "SourceStateLakeExecution"]
