"""Explicit scalar action-contract labels and unchanged-candidate source audits.

This controlled language declares requirements and return observations. A bare
permission is outside its scope. Parsing supplies labels and post-inference
diagnostics, never replacement model predictions. Native training documents
reference a fixed, honestly named unbound-provenance declaration; instruction
provenance is attached separately only after complete source agreement.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from .. import decoder, schema

SCHEMA = "intent-explicit-action-contract/v1"
AUDIT_SCHEMA = "intent-action-contract-source-audit/v1"
BINDING_SCHEMA = "intent-action-contract-source-binding/v1"
PLACEHOLDER_TEXT = "Unbound provenance placeholder for intent-explicit-action-contract/v1; this is not an instruction source."
SOURCE_REF_ID = "intent-contract:source"
OPERATORS = {"+": "add", "-": "sub", "*": "mul"}
INPUTS = ("left", "right")
MAX_BYTES = 65536
FALSE = dict(source_semantics_verified=False, proof_authority=False,
    execution_authority=False, completion_authority=False, mutation_authority=False,
    claim_proved=False, candidate_repaired=False, source_executed=False,
    training_executed=False, kernel_executed=False, admitted=False, qualified=False)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    _require(type(value) is str and 0 < len(value.encode()) <= 4096
        and value.isascii() and not any(c in value for c in "\n\r"),
        "bounded single-line explicit contract source required")
    return value


def _json(value):
    try:
        raw = _wire(value)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("inert bounded contract JSON required") from error
    _require(len(raw) <= MAX_BYTES, "contract candidate exceeds byte bound")
    # JSON encoding can silently turn tuples into lists or integer keys into
    # strings; native candidate identity must consist of exact JSON types.
    def visit(node, depth=0):
        _require(depth <= 20, "contract candidate exceeds nesting bound")
        if type(node) is dict:
            _require(all(type(key) is str for key in node), "string JSON keys required")
            for child in node.values(): visit(child, depth + 1)
        elif type(node) is list:
            for child in node: visit(child, depth + 1)
        else:
            _require(type(node) in (str, int, float, bool, type(None)), "exact JSON values required")
    visit(value)
    return raw


def validate_contract(contract):
    _require(type(contract) is dict and set(contract) == {"actor", "precondition", "equation"},
        "closed explicit scalar contract required")
    _require(type(contract["actor"]) is str and re.fullmatch(r"[a-z][a-z0-9_]{0,31}", contract["actor"])
        and contract["actor"] not in {"the", "must", "may", "not", "if", "true", "false"},
        "explicit bounded actor identifier required")
    pre = contract["precondition"]
    _require(type(pre) is dict, "explicit input requirement required")
    if pre.get("kind") == "true":
        _require(set(pre) == {"kind"}, "literal true requirement has no omitted predicates")
    else:
        _require(set(pre) == {"kind", "input", "threshold"} and pre["kind"] == "gt"
            and type(pre["input"]) is str and pre["input"] in INPUTS
            and type(pre["threshold"]) is int and abs(pre["threshold"]) <= 1_000_000,
            "supported integer input greater-than requirement required")
    equation = contract["equation"]
    _require(type(equation) is dict and set(equation) == {"left", "operator", "right"}
        and all(type(value) is str for value in equation.values())
        and equation["left"] in INPUTS and equation["right"] in INPUTS
        and equation["operator"] in OPERATORS.values(),
        "explicit old-input add/sub/mul return equation required")
    return deepcopy(contract)


def parse_contract(source_text):
    """Parse the complete controlled source for labels or independent audits."""
    text = _text(source_text).strip()
    # No ignored suffixes, implicit returned flag, implicit old(), or inferred
    # effect for a permission. Whitespace is presentation only.
    match = re.fullmatch(r"(?:the[ \t]+)?([a-z][a-z0-9_]{0,31})[ \t]+must[ \t]+compute[ \t]+result"
        r"[ \t]*;[ \t]*requires[ \t]+(true|(?:left|right)[ \t]*>[ \t]*-?(?:0|[1-9][0-9]{0,6}))"
        r"[ \t]*;[ \t]*ensures[ \t]+result[ \t]*=[ \t]*old\([ \t]*(left|right)[ \t]*\)"
        r"[ \t]*([+*-])[ \t]*old\([ \t]*(left|right)[ \t]*\)[ \t]+and[ \t]+returned[ \t]*\.", text)
    _require(match is not None, "source is outside the explicit scalar action-contract grammar")
    actor, requirement, left, operator, right = match.groups()
    if requirement == "true":
        pre = {"kind": "true"}
    else:
        variable, threshold = re.fullmatch(r"(left|right)[ \t]*>[ \t]*(-?(?:0|[1-9][0-9]{0,6}))", requirement).groups()
        _require(threshold != "-0", "canonical signed integer threshold required")
        pre = {"kind": "gt", "input": variable, "threshold": int(threshold)}
    return validate_contract(dict(actor=actor, precondition=pre,
        equation=dict(left=left, operator=OPERATORS[operator], right=right)))


def contract_to_text(contract):
    value = validate_contract(contract)
    pre = value["precondition"]
    condition = "true" if pre["kind"] == "true" else f"{pre['input']} > {pre['threshold']}"
    equation = value["equation"]
    operator = {v: k for k, v in OPERATORS.items()}[equation["operator"]]
    return (f"the {value['actor']} must compute result; requires {condition}; ensures result = "
        f"old({equation['left']}) {operator} old({equation['right']}) and returned.")


def placeholder_source():
    return schema.SourceRef(SOURCE_REF_ID, "urn:intent-action-contract:unbound-source:v1",
        "unbound", "v1", _sha(PLACEHOLDER_TEXT.encode()), review_status=schema.ReviewStatus.UNREVIEWED)


def contract_to_target(contract):
    """Create native typed labels without making instruction hashes model outputs."""
    value = validate_contract(contract)
    refs = (SOURCE_REF_ID,)
    def statement(identity, kind, predicate, arguments, text, modality=schema.IntentModality.ASSERTED):
        return schema.IntentStatement(identity, kind, modality, text, refs, predicate,
            tuple(arguments), confidence=0.0, grounding=schema.NodeGrounding.INFERRED)
    pre, equation = value["precondition"], value["equation"]
    statements = [statement("goal", schema.StatementKind.GOAL, "compute", (value["actor"], "result"),
        "Declared scalar computation.", schema.IntentModality.REQUIRED),
        statement("precondition", schema.StatementKind.PRECONDITION,
            "input_true" if pre["kind"] == "true" else "input_gt",
            () if pre["kind"] == "true" else (pre["input"], str(pre["threshold"])),
            "Declared input requirement."),
        statement("effect:equation", schema.StatementKind.EFFECT, "return_equation",
            ("result", "old:" + equation["left"], equation["operator"], "old:" + equation["right"]),
            "Declared return equation."),
        statement("effect:returned", schema.StatementKind.EFFECT, "returned", ("returned",),
            "Declared returned observation.")]
    action = schema.IntentAction("action", value["actor"], "compute", ("result",), refs,
        precondition_ids=("precondition",), effect_ids=("effect:equation", "effect:returned"),
        grounding=schema.NodeGrounding.INFERRED)
    document = schema.IntentIRDocument("intent-action-contract:single", "Explicit scalar action contract candidate",
        schema.IntentKind.PROCEDURE, (placeholder_source(),), tuple(statements), (action,),
        entry_action_ids=("action",), terminal_action_ids=("action",), tags=("unverified-candidate",))
    document.validate()
    return {"kind": "document", "document": document.to_dict()}


def source_to_target(source_text):
    """Training-label helper only; inference must preserve its own prediction."""
    return contract_to_target(parse_contract(source_text))


def target_to_contract(target):
    """Invert exactly this complete native profile; never discard extra semantics."""
    _json(target)
    _require(type(target) is dict and set(target) == {"kind", "document"}
        and target["kind"] == "document", "explicit native document target envelope required")
    document = decoder.decode_intent_ir(target["document"])
    statements = {row.statement_id: row for row in document.statements}
    _require(len(document.actions) == 1 and set(statements) == {"goal", "precondition", "effect:equation", "effect:returned"},
        "complete single-action explicit contract required")
    pre = statements["precondition"]
    if pre.predicate == "input_true" and not pre.arguments:
        requirement = {"kind": "true"}
    else:
        _require(pre.predicate == "input_gt" and len(pre.arguments) == 2
            and re.fullmatch(r"-?(?:0|[1-9][0-9]{0,6})", pre.arguments[1])
            and pre.arguments[1] != "-0", "canonical explicit input requirement required")
        requirement = dict(kind="gt", input=pre.arguments[0], threshold=int(pre.arguments[1]))
    equation = statements["effect:equation"]
    _require(len(equation.arguments) == 4 and equation.arguments[1].startswith("old:")
        and equation.arguments[3].startswith("old:"), "explicit old-input return equation required")
    contract = validate_contract(dict(actor=document.actions[0].actor, precondition=requirement,
        equation=dict(left=equation.arguments[1][4:], operator=equation.arguments[2], right=equation.arguments[3][4:])))
    _require(_wire(contract_to_target(contract)) == _wire(target),
        "native target changed contract semantics, fields, labels, references, or provenance placeholder")
    return contract


def audit_candidate_source(source_text, candidate):
    """Compare full source and unchanged learned target, without parser fallback."""
    source = _text(source_text)
    raw = _json(candidate)
    report = dict(schema=AUDIT_SCHEMA, source_text=source, source_sha256=_sha(source.encode()),
        candidate=deepcopy(candidate), candidate_sha256=_sha(raw), status="invalid_candidate",
        expected_contract=None, candidate_contract=None, grammar=SCHEMA,
        complete_source_agreement=False, candidate_unchanged=True, **FALSE)
    try:
        predicted = target_to_contract(candidate)
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
        report["reason"] = str(error)[:512]
        return report
    report["candidate_contract"] = predicted
    try:
        expected = parse_contract(source)
    except ValueError as error:
        report.update(status="unsupported_source", reason=str(error))
        return report
    same = expected == predicted
    report.update(status="source_agreement" if same else "source_disagreement",
        expected_contract=expected, complete_source_agreement=same)
    return report


def bind_candidate_source(source_text, candidate):
    """Attach exact source provenance after agreement; preserve the raw candidate."""
    audit = audit_candidate_source(source_text, candidate)
    report = dict(schema=BINDING_SCHEMA, status=audit["status"], source_text=source_text,
        source_sha256=audit["source_sha256"], candidate=deepcopy(candidate),
        candidate_sha256=audit["candidate_sha256"], source_audit=audit,
        bound_candidate=None, bound_candidate_sha256=None, semantic_fields_unchanged=False,
        provenance_binding_only=True, source_identity_predicted=False, continue_planning=True,
        changed_paths=[], **FALSE)
    if audit["status"] != "source_agreement":
        return report
    bound = deepcopy(candidate)
    digest = audit["source_sha256"]
    bound["document"]["sources"] = [schema.SourceRef(SOURCE_REF_ID,
        "instruction:explicit-action-contract", digest, digest, digest,
        review_status=schema.ReviewStatus.MACHINE_EXTRACTED,
        span=schema.SourceSpan(0, len(source_text))).to_dict()]
    decoder.decode_intent_ir(bound["document"])
    original_body = {k: v for k, v in candidate["document"].items() if k != "sources"}
    bound_body = {k: v for k, v in bound["document"].items() if k != "sources"}
    _require(_wire(original_body) == _wire(bound_body), "provenance binding changed candidate semantics")
    report.update(bound_candidate=bound, bound_candidate_sha256=_sha(_wire(bound)),
        semantic_fields_unchanged=True, changed_paths=["/document/sources/0"])
    return report


def verify_bound_candidate(report, source_text, candidate):
    expected = bind_candidate_source(source_text, candidate)
    _require(_json(report) == _json(expected), "explicit contract source binding replay differs")
    return expected


def verify_bound_candidate_source(source_text, bound_candidate):
    """Validate an already bound native envelope without claiming model origin.

    The inverse removes only the declared provenance attachment to replay the
    raw semantic profile. Callers retaining a numerical prediction must also
    compare it with the returned ``candidate``; this function alone does not
    authenticate checkpoint inference.
    """
    _text(source_text)
    _json(bound_candidate)
    _require(type(bound_candidate) is dict and set(bound_candidate) == {"kind", "document"}
        and bound_candidate["kind"] == "document" and type(bound_candidate["document"]) is dict,
        "bound explicit native document target envelope required")
    raw = deepcopy(bound_candidate)
    raw["document"]["sources"] = [placeholder_source().to_dict()]
    replay = bind_candidate_source(source_text, raw)
    _require(replay["status"] == "source_agreement"
        and _wire(replay["bound_candidate"]) == _wire(bound_candidate),
        "bound contract differs from exact source/provenance replay")
    return replay


__all__ = ["SCHEMA", "AUDIT_SCHEMA", "BINDING_SCHEMA", "SOURCE_REF_ID", "PLACEHOLDER_TEXT",
    "parse_contract", "validate_contract", "contract_to_text", "contract_to_target", "source_to_target",
    "target_to_contract", "audit_candidate_source", "bind_candidate_source", "verify_bound_candidate",
    "verify_bound_candidate_source"]
