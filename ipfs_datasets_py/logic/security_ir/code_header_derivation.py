"""Source-bound local header models, native declarations and string obligations.

The reviewed protocol is a premise. This adapter recognizes a small Python
shape; it does not establish dynamic dispatch, conversion or whole-program
semantics. Native SMT compilation preserves the supplied string model, not
arbitrary Python source. No target source is imported or executed.
"""
from __future__ import annotations

import ast
from dataclasses import asdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil

from . import doctor_header_contracts as contracts
from .doctor_header_contracts import WsgiHeaderProtocolContract
from .model import SecurityIR, SecuritySource, Asset, ThreatAssumption, SecurityClaim, StateMachine, StateTransition
from .formalization_adapter import SecurityIRFormalizationAdapter
from ..ir_core.identity import canonical_identity
from ..ir_core.claims import FrozenMap
from ..ir_core.protocols import ExecutionBounds
from ..backends.smt.compiler import (
    SmtTerm, SmtSort, SmtFunDecl, SmtNamedAssertion, SmtObligation,
    SoftwareVerificationSMTCompiler, term_and, term_or, term_not, term_implies,
)

SCHEMA = "security-code-header-derivation/v1"
PROFILE_SCHEMA = "security-code-header-derivation-profile/v1"
CHECK_SCHEMA = "security-code-header-model-check/v1"
MAX_SOURCE_BYTES = 2_000_000
_ASSUMPTIONS = (
    "reviewed_wsgi_callback_identity",
    "reviewed_unique_property_receiver_binding",
    "ordinary_unmodified_python_builtins_and_helper_bindings",
    "recognized_conversion_returns_an_ordinary_string",
    "model_starts_after_successful_conversion_and_ignores_conversion_exceptions",
    "normalization_terminates_and_preserves_NUL_LF_CR_membership",
)
_FRONTIERS = (*contracts.OPEN_FRONTIERS, "arbitrary_python_source_equivalence",
    "conversion_implementation_correctness", "unicode_normalization_implementation",
    "SMT_String_excludes_some_Python_codepoints", "learned_formula_generation")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _cid(payload: dict, schema: str) -> str:
    return canonical_identity(payload, domain="security-code-header", schema_version=schema).cid


def _wire(value):
    return json.loads(json.dumps(value, sort_keys=True))


def describe_header_semantics_profile() -> dict:
    result = {"schema": PROFILE_SCHEMA, "adapter": "SourceHeaderSemantics@1",
        "native_recognizer": contracts.OPERATOR_ID,
        "required_protocol": "explicit WsgiHeaderProtocolContract; caller review remains a premise",
        "roles": ["field_name", "field_value"],
        "normalization_ops": ["identity", "title", "lower", "upper", "casefold", "replace_underscore_hyphen"],
        "guard": {"forbidden_codepoints": [0, 10, 13], "exception": "ValueError"},
        "native_targets": ["SecurityIR", "FormalizationSample", "FormalizationArtifact", "SmtObligation", "SmtCompilation"],
        "string_lowering": "fixed String sort, str.contains and three trusted SMT string literals; normalization abstracted",
        "assumptions": list(_ASSUMPTIONS), "open_frontiers": list(_FRONTIERS),
        "proof_authority": False, "executes_source": False, "learned": False,
        "max_source_bytes": MAX_SOURCE_BYTES}
    result["profile_cid"] = _cid(result, PROFILE_SCHEMA)
    return result


def _input(source_bytes: bytes, source_path: str, protocol: WsgiHeaderProtocolContract) -> str:
    if type(source_bytes) is not bytes or type(protocol) is not WsgiHeaderProtocolContract:
        raise TypeError("exact source bytes and explicit reviewed protocol are required")
    if (type(source_path) is not str or not source_path or "\\" in source_path
            or any(ord(c) < 32 for c in source_path) or PurePosixPath(source_path).is_absolute()
            or any(p in {"", ".", ".."} for p in source_path.split("/"))):
        raise ValueError("canonical repository-relative source_path is required")
    if len(source_bytes) > MAX_SOURCE_BYTES:
        raise ValueError("header source exceeds bounded input size")
    return source_bytes.decode("utf-8")


def _span(node: ast.AST, raw: bytes) -> dict:
    # Unicode line separators are ordinary bytes to Python's tokenizer.
    parts = raw.split(b"\n")
    lines = [part + b"\n" for part in parts[:-1]] + [parts[-1]]
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    start = offsets[node.lineno - 1] + node.col_offset
    end = offsets[node.end_lineno - 1] + node.end_col_offset
    if not 0 <= start < end <= len(raw):
        raise ValueError("native AST source span is outside current bytes")
    return {"start_byte": start, "end_byte": end, "sha256": _sha(raw[start:end])}


def _normalization_ops(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return []
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return _normalization_ops(node.func.value) + [
            "replace_underscore_hyphen" if node.func.attr == "replace" else node.func.attr]
    raise ValueError("recognized normalization structure drifted")


def _bad(value: SmtTerm) -> SmtTerm:
    # These three literals are the sole trusted RAW terms; no caller/source
    # text is interpolated into SMT-LIB identifiers, operators or literals.
    return term_or(*(SmtTerm("apply", value="str.contains", arguments=(value,
        SmtTerm("raw", value='"\\u{' + format(point, 'x') + '}"', sort=SmtSort("String"))))
        for point in (0, 10, 13)))


def _obligations(row: dict, source_sha256: str) -> list[dict]:
    string = SmtSort("String")
    converted = SmtTerm("symbol", value="converted", sort=string)
    normalized = (converted if row["normalization_ops"] == ["identity"]
        else SmtTerm("symbol", value="normalized", sort=string))
    bad = _bad(converted)
    acceptance_rule = term_not(bad) if row["guarded"] else SmtTerm("true")
    accepted = SmtTerm("symbol", value="accepted", sort=SmtSort("Bool"))
    result = SmtTerm("symbol", value="result", sort=string)
    result_rule = SmtTerm("ite", arguments=(accepted, normalized,
        SmtTerm("raw", value='""', sort=string)), sort=string)
    equality = lambda a, b: SmtTerm("eq", arguments=(a, b))
    preservation = term_implies(term_not(bad), term_and(accepted, equality(result, normalized)))
    goals = (("unsafe_converted_input_accepted", term_and(bad, accepted), "satisfiability"),
             ("safe_normalization_preserved", preservation, "theorem_by_negation"),
             ("forbidden_output_accepted", term_and(accepted, _bad(result)), "satisfiability"))
    declarations = [SmtFunDecl("converted", range=string, is_const=True),
                    SmtFunDecl("accepted", range=SmtSort("Bool"), is_const=True),
                    SmtFunDecl("result", range=string, is_const=True)]
    if normalized is not converted:
        declarations.append(SmtFunDecl("normalized", range=string, is_const=True))
    output = []
    for kind, goal, mode in goals:
        assumptions = (SmtNamedAssertion(equality(accepted, acceptance_rule), "source_acceptance_rule"),
                       SmtNamedAssertion(equality(result, result_rule), "source_result_rule"))
        control_preservation_assumed = kind == "forbidden_output_accepted" and normalized is not converted
        if control_preservation_assumed:
            assumptions += (SmtNamedAssertion(equality(_bad(normalized), bad),
                                              "normalization_preserves_controls"),)
        expected = "unsat" if row["guarded"] or mode == "theorem_by_negation" else "sat"
        obligation = SmtObligation(
            obligation_id="header:" + _sha((source_sha256 + row["symbol"] + kind).encode()),
            query_mode=mode, features=("equality", "verification_conditions"),
            goal=goal, assumptions=assumptions, functions=tuple(declarations),
            logic="QF_SLIA", request_model=expected == "sat", request_unsat_core=expected == "unsat",
            source_family_id="security_ir", source_family_version="1.0.0",
            property_ids=("property:" + kind,),
            attributes=FrozenMap({"source_sha256": source_sha256, "symbol": row["symbol"],
                "source_ast_sha256": row["source_ast_sha256"], "header_model": "converted ordinary strings",
                "string_operator_extension": "trusted fixed String/str.contains/literals outside compiler feature registry",
                "source_equivalence_proved": False}))
        compilation = SoftwareVerificationSMTCompiler().compile(obligation)
        output.append({"kind": kind, "symbol": row["symbol"], "expected_model_answer": expected,
            "normalization_control_preservation_assumed": control_preservation_assumed,
            "obligation": obligation.to_dict(), "compilation": compilation.to_dict()})
    return output


def _native_targets(rows: list[dict], contract: dict, source_path: str, source_sha256: str) -> dict:
    source_id = "source:" + source_sha256
    source = SecuritySource(source_id, "repository-source:" + source_path,
        revision="sha256:" + source_sha256, content_sha256=source_sha256,
        attributes={"protocol_review_ref": contract["protocol"]["review_ref"],
                    "review_is_a_premise": True})
    assumptions = tuple(ThreatAssumption("assumption:" + str(i), statement,
        source_ids=(source_id,), attributes={"declared_premise": True})
        for i, statement in enumerate(_ASSUMPTIONS))
    assets, claims, machines = [], [], []
    for index, row in enumerate(rows):
        name = str(index)
        attributes = {"symbol": row["symbol"], "role": row["role"],
            "source_span": row["source_span"], "ast_sha256": row["source_ast_sha256"],
            "guard_observed": row["guarded"], "normalization_ops": row["normalization_ops"]}
        assets.append(Asset("asset:" + name, kind="python-header-normalizer",
            symbol=row["symbol"], source_ids=(source_id,), attributes=attributes))
        claims.append(SecurityClaim("claim:" + name,
            "Converted NUL/LF/CR strings must be rejected and safe normalization preserved.",
            domain="http-header-local-contract", assumption_ids=tuple(a.assumption_id for a in assumptions),
            source_ids=(source_id,), attributes={**attributes, "expected_behavior_only": True}))
        transitions = [StateTransition("converted", "accepted", "normalize",
            guard="not contains_any(converted, [0, 10, 13])" if row["guarded"] else "true",
            effect="unchanged normalization result")]
        if row["guarded"]:
            transitions.append(StateTransition("converted", "rejected", "validate",
                guard="contains_any(converted, [0, 10, 13])", effect="raise ValueError"))
        machines.append(StateMachine("machine:" + name, states=("converted", "accepted", "rejected"),
            initial_state="converted", transitions=tuple(transitions), source_ids=(source_id,),
            attributes={**attributes, "semantics": "source-observed local shape under explicit premises"}))
    declaration = SecurityIR("header:" + source_sha256, sources=(source,), assets=tuple(assets),
        assumptions=assumptions, claims=tuple(claims), state_machines=tuple(machines))
    adapter = SecurityIRFormalizationAdapter()
    sample = adapter.adapt_sample(declaration)
    artifact = adapter.compile(sample, adapter.default_config(sample))
    return {"declaration": declaration.to_dict(), "sample": sample.to_dict(),
        "formalization": artifact.to_dict(), "declaration_cid": declaration.cid,
        "sample_cid": sample.identity.cid, "artifact_cid": artifact.identity.cid,
        "formula_count": len(artifact.formulas), "proof_obligation_count": len(artifact.proof_obligations)}


def derive_header_semantics(*, source_bytes: bytes, source_path: str,
                            protocol: WsgiHeaderProtocolContract) -> dict:
    """Recognize current source and compile its local model without executing it."""
    source = _input(source_bytes, source_path, protocol)
    profile = describe_header_semantics_profile()
    result = {"schema": SCHEMA, "profile_cid": profile["profile_cid"],
        "source_path": source_path, "source_sha256": _sha(source_bytes), "protocol": asdict(protocol),
        "status": "unsupported", "modeled_symbols": [], "native_targets": None, "smt_targets": [],
        "formula_count": 0, "smt_obligation_count": 0, "unsupported": [],
        "assumptions": list(_ASSUMPTIONS), "open_frontiers": list(_FRONTIERS),
        "provider_calls": 0, "solver_calls": 0, "learned_formula_count": 0,
        "proof_authority": False, "mutation_authority": False, "completion_authority": False,
        "source_semantics_verified": False, "whole_program_proved": False, "executes_source": False,
        "implementation_sha256": {"adapter": _sha(Path(__file__).read_bytes()),
                                  "recognizer": _sha(Path(contracts.__file__).read_bytes())}}
    if any(c in source for c in ("\r", "\v", "\f", "\x00")):
        result["unsupported"] = ["unsupported_source_line_control"]
    else:
        analysis = contracts.analyze_http_header_contracts(source, protocol=protocol)
        if not analysis.contracts:
            result["unsupported"] = list(analysis.reason_codes)
        else:
            contract = analysis.contracts[0]
            tree = ast.parse(source)
            bindings = contracts._top_bindings(tree)
            rows = []
            for item in contract["normalizers"]:
                node = bindings[item["symbol"]][0]
                if (node.returns or any(arg.annotation for arg in node.args.args)
                        or getattr(node, "type_params", []) or node.type_comment):
                    result["unsupported"] = ["normalizer_annotations_not_modeled"]
                    break
                ops = _normalization_ops(contracts._body(node)[-1].value) or ["identity"]
                rows.append({"symbol": item["symbol"], "role": item["role"],
                    "line": node.lineno, "end_line": node.end_lineno, "source_span": _span(node, source_bytes),
                    "source_ast_sha256": item["ast_sha256"], "conversion_symbol": item["conversion"],
                    "normalization_ops": ops, "guarded": item["already_guarded"]})
            if not result["unsupported"]:
                result.update(status="modeled", modeled_symbols=rows, contract=_wire(contract))
                result["native_targets"] = _native_targets(rows, contract, source_path, result["source_sha256"])
                result["smt_targets"] = [target for row in rows for target in _obligations(row, result["source_sha256"])]
                result["formula_count"] = result["native_targets"]["formula_count"]
                result["smt_obligation_count"] = len(result["smt_targets"])
    result = _wire(result)
    result["derivation_cid"] = _cid(result, SCHEMA)
    return result


def validate_header_semantics(expected_report: dict, *, source_bytes: bytes, source_path: str,
                              protocol: WsgiHeaderProtocolContract) -> dict:
    """Reject stale bytes, modified formulas, forged roles and extra authority."""
    actual = derive_header_semantics(source_bytes=source_bytes, source_path=source_path, protocol=protocol)
    if (type(expected_report) is not dict or
            json.dumps(expected_report, sort_keys=True, separators=(",", ":")) !=
            json.dumps(actual, sort_keys=True, separators=(",", ":"))):
        raise ValueError("header semantics differ from current source and native replay")
    return actual


def validate_header_candidate_function(*, source_bytes: bytes, source_path: str,
        protocol: WsgiHeaderProtocolContract, symbol: str, candidate_function_source: str) -> dict:
    """Admit an independently produced function only after exact AST equality.

    The candidate producer may be learned, but this function does not certify
    that provenance. Native formal lowering remains deterministic and is run
    only after the candidate matches the selected current-source normalizer.
    There is no source-template substitution on a mismatch.
    """
    source = _input(source_bytes, source_path, protocol)
    if (type(symbol) is not str or not symbol.isidentifier()
            or type(candidate_function_source) is not str
            or len(candidate_function_source.encode("utf-8")) > 65536):
        raise ValueError("bounded candidate function text and symbol required")
    try:
        candidate_tree = ast.parse(candidate_function_source, type_comments=True)
        original_tree = ast.parse(source, type_comments=True)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ValueError("candidate or original function cannot be parsed") from exc
    if (len(candidate_tree.body) != 1 or type(candidate_tree.body[0]) is not ast.FunctionDef
            or candidate_tree.body[0].name != symbol):
        raise ValueError("candidate must contain exactly the selected function")
    original = contracts._top_bindings(original_tree).get(symbol, [])
    if len(original) != 1 or type(original[0]) is not ast.FunctionDef:
        raise ValueError("candidate symbol has no unique source function binding")
    candidate_ast = ast.dump(candidate_tree.body[0], include_attributes=False)
    original_ast = ast.dump(original[0], include_attributes=False)
    if candidate_ast != original_ast:
        raise ValueError("candidate function differs from independently parsed source AST")
    report = derive_header_semantics(source_bytes=source_bytes, source_path=source_path, protocol=protocol)
    if report["status"] != "modeled" or symbol not in {row["symbol"] for row in report["modeled_symbols"]}:
        raise ValueError("candidate source function is outside supported header semantics")
    receipt = {"schema": "security-code-header-candidate-validation/v1",
        "symbol": symbol, "source_path": source_path, "source_sha256": _sha(source_bytes),
        "candidate_source_sha256": _sha(candidate_function_source.encode("utf-8")),
        "candidate_ast_sha256": _sha(candidate_ast.encode()), "candidate_ast_matches_source": True,
        "candidate_producer_verified": False, "compiler_attribution": "deterministic native header model",
        "native_derivation": report, "provider_calls": 0, "solver_calls": 0,
        "proof_authority": False, "mutation_authority": False, "completion_authority": False}
    receipt["validation_cid"] = _cid(receipt, receipt["schema"])
    return receipt


def check_header_semantics(expected_report: dict, *, source_bytes: bytes, source_path: str,
                           protocol: WsgiHeaderProtocolContract, z3_executable: str = "z3",
                           timeout_seconds: float | None = None, cancel_event=None,
                           parent_lease=None) -> dict:
    """Execute optional real Z3 against independently rebuilt source-bound goals.

    SAT is a counterexample in the stated string model; UNSAT establishes only
    that model obligation. Neither grants source, mutation or completion authority.
    """
    import math
    import time
    if timeout_seconds is not None and (type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300):
        raise ValueError("bounded header checker deadline required")
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    def remaining_seconds():
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("header checker cancelled")
        left = 5. if deadline is None else deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("header checker deadline expired")
        return left
    def remaining_ms():
        return min(5000, max(1, int(remaining_seconds() * 1000)))
    if parent_lease is not None and deadline is None:
        raise ValueError("leased header checking requires an aggregate deadline")
    remaining_seconds()
    report = validate_header_semantics(expected_report, source_bytes=source_bytes,
        source_path=source_path, protocol=protocol)
    if type(z3_executable) is not str or not z3_executable.strip():
        raise ValueError("z3_executable must name an optional local solver")
    output = {"schema": CHECK_SCHEMA, "derivation_cid": report["derivation_cid"],
        "source_sha256": report["source_sha256"], "status": "unsupported", "results": [],
        "solver_calls": 0, "provider_calls": 0, "proof_authority": False,
        "mutation_authority": False, "completion_authority": False, "whole_program_proved": False,
        "source_semantics_verified": False, "assumptions": report["assumptions"],
        "open_frontiers": report["open_frontiers"]}
    executable = shutil.which(z3_executable)
    if report["status"] == "modeled" and executable is None:
        output["status"] = "solver_unavailable"
    elif report["status"] == "modeled":
        from ..backends.z3.compiler import Z3SoftwareVerificationBackend
        if parent_lease is None:
            backend = Z3SoftwareVerificationBackend(executable=executable)
        else:
            from .bounded_header_checker import bounded_header_runner
            runner = bounded_header_runner(executable, parent_lease=parent_lease,
                remaining_seconds=remaining_seconds, cancel_event=cancel_event)
            backend = Z3SoftwareVerificationBackend(executable=executable, runner=runner)
            output["execution_profile"] = "native-leased-bounded-header-checker@1"
        output["solver_executable_sha256"] = _sha(Path(executable).read_bytes())
        for target in report["smt_targets"]:
            compilation = SoftwareVerificationSMTCompiler().compile(SmtObligation.from_dict(target["obligation"]))
            if compilation.to_dict() != target["compilation"]:
                raise ValueError("SMT target differs from native recompilation")
            outcome = backend.run(compilation, bounds=ExecutionBounds(timeout_ms=remaining_ms(),
                max_steps=100000, max_memory_bytes=128 * 1024 * 1024, max_output_bytes=65536))
            remaining_ms()
            status = outcome.result.status.value
            answer = {"satisfiable": "sat", "unsatisfiable": "unsat", "proved": "unsat", "disproved": "sat"}.get(status, "unknown")
            output["results"].append({"symbol": target["symbol"], "kind": target["kind"],
                "query_mode": target["obligation"]["query_mode"], "status": status, "solver_answer": answer,
                "expected_model_answer": target["expected_model_answer"],
                "matches_model_expectation": answer == target["expected_model_answer"],
                "solver_version": outcome.solver_version, "script_digest": compilation.script.digest,
                "script_sha256": _sha(compilation.smtlib.encode()), "compilation_id": compilation.compilation_id,
                "model_text": outcome.model_text, "unsat_core": list(outcome.unsat_core)})
            output["solver_calls"] += 1
        output["status"] = ("checked_local_model" if all(row["matches_model_expectation"] for row in output["results"])
                            else "model_check_inconclusive_or_mismatch")
    remaining_ms()
    output["check_cid"] = _cid(output, CHECK_SCHEMA)
    return output
