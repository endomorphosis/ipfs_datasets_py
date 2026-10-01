"""Replay-bound native builds with one audited CodeUnit program extension.

The frozen v5 gate still owns every existing lowering. Only its blocked,
source-joined scalar Security program is extended, after exact inverse replay.
Issued handles record real backend execution, never source truth or admission.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import weakref

from . import codeunit_program_lean as program
from .contracts import digest, raw, require
from .. import native_family_lake_v5 as previous

SCHEMA = "distributed-384-candidate-native-lake/v1"
FALSE = previous.FALSE
_REGISTRY = weakref.WeakKeyDictionary()


def _pins():
    return {str(Path(path).resolve()): hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in (__file__, program.__file__)}


_IMPORTED = _pins()


def _guard():
    previous._guard()
    require(_pins() == _IMPORTED, "candidate Lake implementation changed since import")
    previous._check_pins(_IMPORTED)


def _candidate_document_join(domain, validated, source_inputs, source_text, candidate):
    """Check the predicted fragment without treating extra declarations as it."""
    document = source_inputs.get("document")
    if domain == "legal_ir":
        require(raw(previous.v1._json(document)) == raw(validated["canonical_ir"]),
                "Legal native document differs from decoded canonical candidate")
    elif domain == "ui_ux_ir":
        from ..ui_source_contract_384 import _native
        from ....ui_ux_ir.formalize.roundtrip import _as_document
        expected, _ = _native(candidate)
        actual = _as_document(document).component_graph
        require(actual is not None, "UI candidate component graph is absent")
        if validated["kind"] == "ui_component":
            component = expected.components[0]
            matches = [item for item in actual.components if item.component_id == component.component_id]
            require(len(matches) == 1 and raw(matches[0].to_dict()) == raw(component.to_dict()),
                    "UI native component differs from decoded candidate")
        else:
            require(raw(actual.to_dict()) == raw(expected.to_dict()),
                    "UI native graph differs from decoded document candidate")
    elif domain == "intent_ir":
        expected = validated["native_ir"]
        if validated["kind"] == "intent_rich_ast":
            from ....intent_ir.formalize.rich_grammar import parse_instruction
            require(parse_instruction(source_text) == expected, "Intent candidate differs from exact source")
            if type(document) is not dict:
                require(expected["kind"] == "atom", "only atomic Intent can use native document lowering")
                from ....intent_ir.formalize.rich_logic import project_rich_intent_logic
                expected = project_rich_intent_logic(expected, instruction=source_text)["native_intent_ir"]
        else:
            source_sha = hashlib.sha256(source_text.encode()).hexdigest()
            require(bool(expected["sources"]) and all(row.get("content_sha256") == source_sha
                    for row in expected["sources"]), "Intent native candidate source hash differs")
        require(raw(previous.v1._json(document)) == raw(expected),
                "Intent native document differs from decoded candidate")
    elif validated["kind"] == "program_expression":
        models = [item.document.to_dict() for item in source_inputs.get("typed_inputs", ())
                  if getattr(item.document, "to_dict", None)]
        joined = [model for model in models if type(model) is dict
                  and type(model.get("metadata")) is dict
                  and "distributed_candidate_source_join" in model["metadata"]]
        require(len(joined) == 1, "one exact source-joined Security candidate program required")
        program.replay_original_program(joined[0], code_unit=source_inputs.get("code_unit"),
            source_text=source_text, candidate=candidate)
    else:
        source_sha = hashlib.sha256(source_text.encode()).hexdigest()
        require(any(row.get("content_sha256") == source_sha for row in validated["native_ir"]["sources"]),
                "Security document candidate lacks the exact code source")


def _identity(report, source_inputs, source_text, candidate):
    from ..source_training_v2 import validate_target
    require(type(source_text) is str and source_text.strip()
            and len(source_text.encode()) <= 1048576, "bounded exact candidate source text required")
    require(type(candidate) is dict, "original native decoder candidate required")
    validated = validate_target(report["domain_id"], candidate)
    require(type(source_inputs) is dict and source_inputs, "original typed source inputs required")
    if report["domain_id"] == "security_ir":
        require(source_inputs.get("source_bytes") == source_text.encode(),
                "Security native source bytes differ from candidate source")
    else:
        require(source_inputs.get("source_text") == source_text,
                "native source text differs from candidate source")
    _candidate_document_join(report["domain_id"], validated, source_inputs, source_text, candidate)
    serialized = previous.v1._json(source_inputs)
    if "source_bytes" in serialized:
        require(type(serialized["source_bytes"]) is bytes, "native source_bytes must be bytes")
        serialized["source_bytes"] = {"sha256": hashlib.sha256(serialized["source_bytes"]).hexdigest()}
    return {"candidate_sha256": digest(candidate),
            "candidate_source_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
            "typed_source_inputs_sha256": digest(serialized)}


def _recognizes(report, projection):
    if report["domain_id"] != "security_ir":
        return False
    payload = projection.get("payload", {})
    if type(payload) is not dict or type(payload.get("metadata", {})) is not dict:
        return False
    join = payload.get("metadata", {}).get("distributed_candidate_source_join", {})
    return (type(join) is dict and projection["projection_id"] == "program.program_ir/v1"
            and projection["logic_family"] == "program" and projection.get("profile") == "program_ir"
            and payload.get("schema_version") == "program-ir/v1"
            and join.get("schema") == program.SOURCE_JOIN_SCHEMA)


def _preparation_digest(prepared):
    # v5 inventories every currently imported logic module. Importing another
    # unrelated parser later must not change candidate/source identity. Every
    # producer that participated in the build remains checked independently.
    return digest({key: value for key, value in prepared.items()
                   if key not in {"producer", "preparation_sha256"}})


def prepare_native_family_lean(report, *, source_inputs, source_text, candidate):
    """Preserve v5 results and extend only an exactly replayed joined program."""
    _guard()
    identity = _identity(report, source_inputs, source_text, candidate)
    original = previous.prepare_native_family_lean(report, source_inputs=source_inputs)
    prepared = deepcopy(original)
    extensions = []
    recognized = [p for p in report["projections"] if _recognizes(report, p)]
    require(len(recognized) <= 1, "one source-joined native program projection required")
    for index, (projection, row) in enumerate(zip(report["projections"], prepared["per_projection"])):
        require(projection["projection_id"] == row["projection_id"], "native projection order changed")
        if not _recognizes(report, projection) or row["semantic_lowering_supported"]:
            continue
        require(projection["ready_for_training"] is True, "joined native program is not ready")
        source, lowering = program.emit_program(projection["payload"], code_unit=source_inputs.get("code_unit"),
            source_text=source_text, candidate=candidate)
        require(type(source) is str and source.strip(), "nonempty audited native program lowering required")
        wrapped = "namespace Projection_" + str(index) + "\n" + source + "\nend Projection_" + str(index)
        extensions.append(wrapped)
        prior = deepcopy(row)
        row.update(parser_status="passed", lake_status="not_run", semantic_lowering_supported=True,
            reason=None, lowering=lowering, lean_declarations_sha256=hashlib.sha256(wrapped.encode()).hexdigest(),
            previous_lowering_observation=prior, extension_profile=program.PROFILE)
    if extensions:
        prepared["lean_source"] += "\nnamespace " + prepared["library"] + "\n" + "\n\n".join(extensions) + "\nend " + prepared["library"] + "\n"
    require(len(prepared["lean_source"].encode()) <= 4 * 1024 * 1024, "candidate native Lean module exceeds byte bound")
    previous._validate_report(report, source_inputs)
    require(identity == _identity(report, source_inputs, source_text, candidate),
            "source or candidate changed during native preparation")
    require(previous._digest(report) == original["report_sha256"], "native report changed during preparation")
    prepared.update(schema=SCHEMA, **identity, legacy_schema=previous.SCHEMA,
        legacy_preparation_sha256=_preparation_digest(original), source_candidate_replay_bound=True,
        candidate_rewritten=False, extended_projection_count=len(extensions),
        lean_source_sha256=hashlib.sha256(prepared["lean_source"].encode()).hexdigest())
    prepared["producer"].update(previous._loaded_pins(report))
    prepared["producer"].update(_pins())
    _guard()
    previous._check_pins(prepared["producer"])
    prepared["preparation_digest_scope"] = "exact_payloads_inputs_and_generated_source; producer_pins_verified_separately"
    prepared["preparation_sha256"] = _preparation_digest(prepared)
    return prepared


@dataclass(frozen=True, eq=False)
class CandidateNativeLakeExecution:
    """Only handles issued after a backend attempt can carry live evidence."""
    def to_dict(self):
        require(self in _REGISTRY, "unissued candidate native Lake execution")
        return json.loads(_REGISTRY[self]["receipt"])


def build_native_family_lake(report, *, source_inputs, source_text, candidate,
                            lake_executable, timeout_seconds=60, output_directory=None,
                            java_executable=None, tla2tools_jar=None):
    """Execute Lake and every required native syntax check, then replay inputs."""
    require(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 60,
            "bounded native Lake timeout required")
    output = Path(output_directory).resolve() if output_directory is not None else None
    require(output is None or not output.exists(), "fresh candidate native Lake evidence directory required")
    receipt = prepare_native_family_lean(report, source_inputs=source_inputs, source_text=source_text, candidate=candidate)
    before = receipt["preparation_sha256"]
    candidates = [row for row in receipt["per_projection"] if row["semantic_lowering_supported"]]
    for row in candidates:
        requirements = row["lowering"].get("syntax_requirements", [])
        row["additional_syntax_checks"] = [previous.tla.check_sany(requirement,
            java_executable=java_executable, tla2tools_jar=tla2tools_jar,
            timeout_seconds=min(30, timeout_seconds)) for requirement in requirements]
        for check in row["additional_syntax_checks"]:
            receipt["producer"].update(check.get("tool_sha256", {}))
        if any(check["status"] != "passed" for check in row["additional_syntax_checks"]):
            row.update(parser_status="blocked", reason="required_native_syntax_checker_not_passed")
    execution = previous._execute(receipt["lean_source"], receipt["library"], lake_executable, timeout_seconds) if candidates else {
        "status": "blocked", "backend_executed": False, "reason": "no_supported_native_declarations"}
    if execution.get("executable_sha256") and execution.get("command"):
        receipt["producer"][str(Path(execution["command"][0]).resolve())] = execution["executable_sha256"]
    fresh = prepare_native_family_lean(report, source_inputs=source_inputs, source_text=source_text, candidate=candidate)
    require(fresh["preparation_sha256"] == before, "candidate native inputs or generated source changed during build")
    previous._check_pins(receipt["producer"])
    passed = execution["status"] == "passed" and execution["backend_executed"] is True
    for row in candidates:
        row["lake_status"] = "passed" if passed else execution["status"]
    complete = bool(receipt["per_projection"]) and not receipt["missing_requested_families"] and all(
        row["lake_status"] == "passed" and row["parser_status"] == "passed" and row["semantic_lowering_supported"]
        for row in receipt["per_projection"])
    receipt.update(backend_executed=execution["backend_executed"], execution=execution,
        status="passed" if complete else "partial" if passed else execution["status"],
        all_requested_projections_passed=complete)
    if output is not None:
        output.mkdir(parents=True)
        (output / (receipt["library"] + ".lean")).write_text(receipt["lean_source"])
        (output / "receipt.json").write_bytes(raw(receipt))
    handle = CandidateNativeLakeExecution()
    _REGISTRY[handle] = {"receipt": raw(receipt), "preparation_sha256": before,
                         "producer": deepcopy(receipt["producer"])}
    return handle


def verify_native_family_lake(execution, report, projection_id=None, *, source_inputs, source_text, candidate):
    """Verify a live issued handle against fresh typed source/candidate replay."""
    _guard()
    require(type(execution) is CandidateNativeLakeExecution and execution in _REGISTRY,
            "live issued candidate native Lake execution required; archived receipts are insufficient")
    recorded = _REGISTRY[execution]
    previous._check_pins(recorded["producer"])
    fresh = prepare_native_family_lean(report, source_inputs=source_inputs, source_text=source_text, candidate=candidate)
    require(fresh["preparation_sha256"] == recorded["preparation_sha256"],
            "candidate Lake execution belongs to another report, source, candidate or input declaration")
    receipt = json.loads(recorded["receipt"])
    if projection_id is None:
        return receipt
    matches = [row for row in receipt["per_projection"] if row["projection_id"] == projection_id]
    require(len(matches) == 1, "native projection has no bound candidate Lake observation")
    return matches[0]


__all__ = ["SCHEMA", "CandidateNativeLakeExecution", "prepare_native_family_lean",
           "build_native_family_lake", "verify_native_family_lake"]
