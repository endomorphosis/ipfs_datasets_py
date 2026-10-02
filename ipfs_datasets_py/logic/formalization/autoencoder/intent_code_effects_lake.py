"""Check explicit cross-source Intent/code effects with live Lean evidence.

Successful compilation can check a satisfaction theorem, a counterexample, or
a no-enabled-input theorem. Those dispositions remain distinct. The checker
does not infer the interpretation of an instruction or authorize task execution.
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

from . import source_state_lake as source_gate
from . import native_family_lake_v4 as executor
from . import intent_code_effects as contracts
from . import intent_code_effects_lean as emitter

SCHEMA = "intent-code-effects-lake/v1"
FIELDS = {"id", "intent_source_text", "intent_candidate_ir", "code_source_text",
          "code_candidate_ir", "input_domains", "association"}
MAX_ROWS = 16
FALSE = dict(proof_authority=False, execution_authority=False,
    completion_authority=False, mutation_authority=False,
    source_semantics_verified=False, intent_meaning_verified=False,
    whole_instruction_verified=False, security_specification_inferred=False,
    normative_compliance_verified=False, source_executed=False,
    input_domains_inferred=False, association_inferred=False, candidate_repaired=False,
    admitted=False, qualified=False, claim_proved=False, promotion_performed=False)
_ISSUED = weakref.WeakKeyDictionary()


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _owners():
    pending = [sys.modules[__name__], contracts, emitter, *source_gate._owners(),
        *getattr(contracts, "PRODUCERS", ()), *getattr(emitter, "PRODUCERS", ())]
    found = {}
    # Follow the actual imported native contracts and their owners. Python and
    # external dependencies are outside this explicitly limited code pin.
    prefixes = ("ipfs_datasets_py.logic.", "ipfs_datasets_py.optimizers.logic_theorem_optimizer.")
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
    source_gate._guard()
    for module in _owners():
        _pin_imported_module(module)
    _require(_pins() == _IMPORTED, "Intent/code effect producer changed after import")


def _rows(rows):
    _require(type(rows) is list and 1 <= len(rows) <= MAX_ROWS,
        "one to sixteen explicit Intent/code contracts required")
    try:
        encoded = _raw(rows)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("inert Intent/code contract JSON required") from error
    _require(len(encoded) <= 4 * 1024 * 1024, "Intent/code contract batch exceeds byte bound")
    for row in rows:
        _require(type(row) is dict and set(row) == FIELDS,
            "closed target-free Intent/code contract row required")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 256,
            "bounded contract row identity required")
        for key in ("intent_source_text", "code_source_text"):
            _require(type(row[key]) is str and 0 < len(row[key].encode()) <= 65536,
                "bounded exact instruction and code sources required")
    _require(len({row["id"] for row in rows}) == len(rows), "unique contract row IDs required")
    return json.loads(encoded)


def _inputs(row):
    return (row["intent_source_text"], row["intent_candidate_ir"], row["code_source_text"],
        row["code_candidate_ir"], row["input_domains"], row["association"])


def prepare_intent_code_effects_lean(rows):
    """Preserve the entire candidate population and its separate source identities."""
    _guard()
    inputs = _rows(rows)
    results, lines = [], ["namespace IntentCodeEffects"]
    for index, row in enumerate(inputs):
        result = dict(id=row["id"],
            intent_source_sha256=_sha(row["intent_source_text"].encode()),
            intent_candidate_sha256=_sha(_raw(row["intent_candidate_ir"])),
            code_source_sha256=_sha(row["code_source_text"].encode()),
            code_candidate_sha256=_sha(_raw(row["code_candidate_ir"])),
            input_domains_sha256=_sha(_raw(row["input_domains"])),
            association_sha256=_sha(_raw(row["association"])),
            status="unsupported", reason=None, contract=None, effect_status=None,
            semantic_lowering_supported=False, lake_status="blocked",
            finite_effects_kernel_checked=False, counterexample_kernel_checked=False,
            bounded_effects_satisfied=False, **FALSE)
        try:
            contract = contracts.prepare_intent_code_effects(*_inputs(row))
            source, details = emitter.emit_intent_code_effects(contract)
            _require(contract["status"] in {"satisfied", "refuted", "no_enabled_cases"},
                "known explicit finite effect disposition required")
            _require(source.strip(), "nonempty Intent/code proof declarations required")
            wrapped = f"namespace Candidate_{index}\n{source}\nend Candidate_{index}"
            lines.append(wrapped)
            result.update(status="prepared", contract=contract, lowering=details,
                semantic_lowering_supported=True, lake_status="not_run",
                effect_status=contract["status"], case_count=len(contract["cases"]),
                enabled_case_count=contract["enabled_case_count"],
                lean_declarations_sha256=_sha(wrapped.encode()))
        except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
            result.update(reason=str(error)[:1024], error_type=type(error).__name__)
        results.append(result)
    lines.append("end IntentCodeEffects\n")
    source = "\n\n".join(lines)
    _require(len(source.encode()) <= 4 * 1024 * 1024, "Intent/code Lean module exceeds byte bound")
    _guard()
    return dict(schema=SCHEMA, library="IntentCodeEffects", rows=results,
        count=len(results), supported_count=sum(row["semantic_lowering_supported"] for row in results),
        input_sha256=_sha(_raw(inputs)), producer=_pins(), status="prepared",
        producer_pin_scope="listed imported native owner modules; excludes generated methods, Python and external libraries",
        lean_source=source, lean_source_sha256=_sha(source.encode()),
        backend_executed=False, source_replay_passed=True, all_candidates_checked=False,
        finite_effects_kernel_checked=False, bounded_effects_satisfied=False,
        scope="selected Intent action under explicitly authored two-source interpretation and finite code input bounds",
        training_steps=0, provider_calls=0, download_calls=0, **FALSE)


@dataclass(frozen=True, eq=False)
class IntentCodeEffectsLakeExecution:
    """Only a live issued handle can establish execution-replay identity."""
    def to_dict(self):
        _require(self in _ISSUED, "unissued Intent/code effect build handle")
        return json.loads(_ISSUED[self]["receipt"])


def build_intent_code_effects_lake(rows, *, lake_executable, timeout_seconds=60, output_directory=None):
    _require(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 60,
        "bounded Intent/code check timeout required")
    output = Path(output_directory).resolve() if output_directory is not None else None
    _require(output is None or not output.exists(), "fresh Intent/code evidence directory required")
    prepared = prepare_intent_code_effects_lean(rows)
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
        dict(status="blocked", backend_executed=False, reason="no_supported_Intent_code_contracts"))
    if execution.get("executable_sha256"):
        used = Path(execution["command"][0]).resolve()
        _require(tool_pins.get(str(used)) == execution["executable_sha256"] and
            str(used.with_name("lean")) in tool_pins, "native Lake and Lean identities required")
    passed = execution["status"] == "passed" and execution["backend_executed"] is True
    for row in supported:
        row.update(lake_status="passed" if passed else execution["status"],
            status="passed" if passed else execution["status"],
            finite_effects_kernel_checked=passed,
            counterexample_kernel_checked=passed and row["effect_status"] == "refuted",
            bounded_effects_satisfied=passed and row["effect_status"] == "satisfied")
    _guard()
    _require(prepare_intent_code_effects_lean(rows) == prepared,
        "Intent/code inputs or interpretations changed during checking")
    for path, expected in tool_pins.items():
        _require(_sha(Path(path).read_bytes()) == expected, "Intent/code checker changed during checking")
    complete = passed and len(supported) == len(receipt["rows"])
    receipt.update(status="passed" if complete else "partial" if passed else execution["status"],
        execution=execution, backend_executed=execution["backend_executed"],
        all_candidates_checked=complete, finite_effects_kernel_checked=complete,
        bounded_effects_satisfied=complete and all(row["effect_status"] == "satisfied" for row in supported),
        tool_binary_sha256=tool_pins, tool_pin_scope="Lake and Lean binaries, not full toolchain libraries")
    if output is not None:
        output.mkdir(parents=True)
        (output / "IntentCodeEffects.lean").write_bytes(receipt["lean_source"].encode())
        (output / "receipt.json").write_bytes(_raw(receipt))
    handle = IntentCodeEffectsLakeExecution()
    _ISSUED[handle] = dict(receipt=_raw(receipt), input_sha256=receipt["input_sha256"], tool_pins=tool_pins)
    return handle


def verify_intent_code_effects_lake(execution, rows):
    _guard()
    _require(type(execution) is IntentCodeEffectsLakeExecution and execution in _ISSUED,
        "live issued Intent/code build handle required")
    state = _ISSUED[execution]
    _require(_sha(_raw(_rows(rows))) == state["input_sha256"], "Intent/code input identity differs")
    for path, checksum in state["tool_pins"].items():
        _require(_sha(Path(path).read_bytes()) == checksum, "Intent/code checker changed")
    receipt = json.loads(state["receipt"])
    replay = prepare_intent_code_effects_lean(rows)
    _require(replay["lean_source_sha256"] == receipt["lean_source_sha256"] and
        replay["producer"] == receipt["producer"], "Intent/code declaration replay differs")
    return receipt


__all__ = ["prepare_intent_code_effects_lean", "build_intent_code_effects_lake",
    "verify_intent_code_effects_lake", "IntentCodeEffectsLakeExecution"]
