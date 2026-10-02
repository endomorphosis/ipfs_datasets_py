"""Explicit, bounded Intent action interpretations over source-derived code states.

Instruction and code retain distinct exact native provenance. A caller binds
existing action conditions to typed ProgramIR expression roots; this adapter
does not infer their meaning, add effects, execute source, or grant authority.
All code input cases remain visible, including disabled guards and refutations.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from . import native_interpretation_expressions as typed
from .distributed_384 import intent_world_model as intent_owner
from .security import source_state_model as state_owner
from ...intent_ir import schema as intent_schema, canonicalize
from ...intent_ir.formalize import projection_contracts

SCHEMA = "intent-code-effects/v1"
ASSOCIATION_SCHEMA = "intent-code-effect-association/v1"
REQUIREMENTS_SCHEMA = "intent-code-effect-requirements/v1"
IDENTITY_FIELDS = {"intent_source_sha256", "intent_candidate_sha256", "intent_document_sha256",
    "code_source_sha256", "code_candidate_sha256", "source_state_report_sha256"}
ASSOCIATION_FIELDS = {"schema", *IDENTITY_FIELDS, "action_id", "intent_evidence_ref", "code_evidence_ref",
    "expression_program", "symbol_bindings", "precondition_bindings", "effect_bindings"}
FALSE = dict(proof_authority=False, execution_authority=False, completion_authority=False,
    mutation_authority=False, admitted=False, qualified=False, source_semantics_verified=False,
    instruction_interpretation_verified=False, whole_intent_compliance_verified=False,
    security_policy_inferred=False, association_inferred=False, candidate_repaired=False,
    source_executed=False, model_inference_performed=False, kernel_executed=False,
    bounded_effects_kernel_checked=False, goals_asserted_true=False)
PRODUCERS = (typed, *typed.PRODUCERS, intent_owner, state_owner, *state_owner.PRODUCERS,
    intent_schema, canonicalize, projection_contracts)


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _raw(value):
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        raise ValueError("bounded inert Intent/code JSON required") from error
    _require(len(data) <= 4 * 1024 * 1024, "bounded Intent/code artifact required")
    return data


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _source(value):
    _require(type(value) is str and value.strip() and len(value.encode()) <= 65536,
        "bounded nonempty exact Intent/code source text required")
    return hashlib.sha256(value.encode()).hexdigest()


def _closed(value, fields, reason):
    _require(type(value) is dict and set(value) == set(fields), reason)


def _owners(intent_source, intent_candidate, code_source, code_candidate, input_domains):
    intent_sha, code_sha = _source(intent_source), _source(code_source)
    document = intent_owner.intent_document(intent_candidate, intent_source)
    wire = json.loads(canonicalize.canonical_intent_ir_bytes(document))
    model = state_owner.derive_source_state_model(code_source, code_candidate, input_domains)
    intent_refs = [row.to_dict() for row in document.sources]
    code_refs = deepcopy(model["source_program"]["sources"])
    _require(not {row["ref_id"] for row in intent_refs} & {row["ref_id"] for row in code_refs},
        "conflicting cross-source evidence reference identifiers")
    identity = dict(intent_source_sha256=intent_sha, intent_candidate_sha256=_digest(intent_candidate),
        intent_document_sha256=projection_contracts.source_ir_sha256(document),
        code_source_sha256=code_sha, code_candidate_sha256=_digest(code_candidate),
        source_state_report_sha256=model["report_sha256"])
    return document, wire, model, intent_refs, code_refs, identity


def intent_code_effect_requirements(intent_source, intent_candidate, code_source, code_candidate, input_domains):
    """Expose exact native IDs/types; supply no interpretation or inferred effect."""
    document, wire, model, intent_refs, code_refs, identity = _owners(
        intent_source, intent_candidate, code_source, code_candidate, input_domains)
    return dict(schema=REQUIREMENTS_SCHEMA, association_schema=ASSOCIATION_SCHEMA, **identity,
        intent_source_refs=intent_refs, code_source_refs=code_refs,
        actions=[row.to_dict() for row in document.actions],
        statements=[row.to_dict() for row in document.statements],
        state_variables=deepcopy(model["state_model"]["schema"]["variables"]),
        case_count=model["case_count"], scope="selected_existing_action_conditions_only", **FALSE)


class _Expressions:
    """Use native typing/rendering ownership and a bounded pure data evaluator."""
    def __init__(self, payload):
        self.carrier = typed.TypedExpressions(payload)
        self.nodes = {row["expression_id"]: row for row in payload["expressions"]}
        self.reached = set()

    def root(self, identity, *, precondition=False):
        self.carrier.require_root(identity, "boolean", allow_old=not precondition)
        active, visited = set(), set()
        def visit(key, depth):
            _require(depth <= 24 and key not in active and len(visited) < 256,
                "bounded acyclic Intent effect expression required")
            if key in visited:
                return
            active.add(key); visited.add(key)
            row = self.nodes[key]
            _require(row["kind"] in {"literal", "symbol", "old", "unary", "binary", "conditional"},
                "closed pure Intent effect expression required")
            if row["kind"] == "literal" and row["type_ref"] == "integer":
                _require(abs(row["attributes"]["value"]) <= 1_000_000,
                    "bounded Intent effect integer literal required")
            for child in row["operand_ids"]:
                visit(child, depth + 1)
            active.remove(key)
        visit(identity, 0)
        self.reached.update(visited)

    def signature(self, key):
        """Compare structure rather than caller-chosen expression identifiers."""
        row = self.nodes[key]
        return {"kind": row["kind"], "type_ref": row["type_ref"], "operator": row["operator"],
            "symbol_ids": row["symbol_ids"], "attributes": row["attributes"],
            "operands": [self.signature(child) for child in row["operand_ids"]]}

    def evaluate(self, key, before, current):
        visits = 0
        def run(identity, values, depth):
            nonlocal visits
            visits += 1
            _require(depth <= 24 and visits <= 4096, "bounded Intent expression evaluation required")
            row = self.nodes[identity]
            kind, op, operands = row["kind"], row["operator"], row["operand_ids"]
            if kind == "literal":
                value = row["attributes"]["value"]
            elif kind == "symbol":
                symbol, = row["symbol_ids"]
                _require(symbol in values, "unbound Intent expression symbol")
                value = values[symbol]
            elif kind == "old":
                value = run(operands[0], before, depth + 1)
            elif kind == "conditional":
                guard = run(operands[0], values, depth + 1)
                value = run(operands[1 if guard else 2], values, depth + 1)
            elif kind == "unary":
                child = run(operands[0], values, depth + 1)
                value = not child if op == "not" else -child if op == "neg" else child
            else:
                left, right = [run(child, values, depth + 1) for child in operands]
                operators = {"add": lambda: left + right, "sub": lambda: left - right,
                    "mul": lambda: left * right, "and": lambda: left and right, "or": lambda: left or right,
                    "eq": lambda: left == right, "ne": lambda: left != right, "lt": lambda: left < right,
                    "le": lambda: left <= right, "gt": lambda: left > right, "ge": lambda: left >= right}
                _require(op in operators, "unsupported Intent expression operator")
                value = operators[op]()
            _require(type(value) is (int if row["type_ref"] == "integer" else bool),
                "Intent expression value type differs")
            _require(type(value) is not int or value.bit_length() <= 4096,
                "bounded Intent expression integer result required")
            return value
        return run(key, current, 0)


def _bindings(rows, required, statements, expressions, *, precondition, meanings):
    _require(type(rows) is list and len(rows) <= 32, "bounded complete Intent condition bindings required")
    seen, result = set(), []
    for row in rows:
        _closed(row, {"statement_id", "expression_id", "evidence_ref"}, "closed Intent condition binding required")
        sid = row["statement_id"]
        _require(type(sid) is str and sid in required and sid not in seen,
            "unique exact selected action condition IDs required")
        seen.add(sid)
        statement = statements[sid]
        kinds = {intent_schema.StatementKind.PRECONDITION} if precondition else {
            intent_schema.StatementKind.EFFECT, intent_schema.StatementKind.POSTCONDITION}
        _require(statement.kind in kinds and statement.modality is intent_schema.IntentModality.ASSERTED,
            "asserted native precondition or effect/postcondition required")
        _require(type(row["evidence_ref"]) is str and row["evidence_ref"] in statement.source_ref_ids,
            "condition interpretation requires exact Intent evidence reference")
        _require(statement.predicate and len(statement.arguments) <= 32,
            "bounded explicit native condition predicate required")
        expressions.root(row["expression_id"], precondition=precondition)
        meaning_key = (statement.predicate, tuple(statement.arguments))
        signature = _raw(expressions.signature(row["expression_id"]))
        _require(meaning_key not in meanings or meanings[meaning_key] == signature,
            "conflicting interpretation for native predicate and ordered arguments")
        meanings[meaning_key] = signature
        result.append(deepcopy(row))
    _require(seen == set(required), "exactly every selected action condition requires a binding")
    return result


def prepare_intent_code_effects(intent_source, intent_candidate, code_source, code_candidate, input_domains, association):
    """Evaluate all finite cases under explicit selected-action interpretations."""
    _closed(association, ASSOCIATION_FIELDS, "closed cross-source Intent/code association required")
    _require(association["schema"] == ASSOCIATION_SCHEMA and len(_raw(association)) <= 512 * 1024,
        "bounded supported cross-source association required")
    document, wire, model, intent_refs, code_refs, identity = _owners(
        intent_source, intent_candidate, code_source, code_candidate, input_domains)
    _require(all(association[key] == value for key, value in identity.items()),
        "association exact source, candidate, native document or state model identity differs")
    actions = {row.action_id: row for row in document.actions}
    _require(type(association["action_id"]) is str and association["action_id"] in actions,
        "known selected native Intent action required")
    action = actions[association["action_id"]]
    _require(action.effect_ids, "selected native Intent action has no declared effects")
    _require(type(association["intent_evidence_ref"]) is str
        and association["intent_evidence_ref"] in action.source_ref_ids,
        "selected action requires exact Intent evidence reference")
    _require(type(association["code_evidence_ref"]) is str
        and association["code_evidence_ref"] in {row["ref_id"] for row in code_refs},
        "exact code evidence reference required")
    expressions = _Expressions(association["expression_program"])
    _require(_raw(expressions.carrier.payload["sources"]) == _raw(code_refs),
        "typed expression carrier must retain exact original code SourceRefs")
    variables = {row["variable_id"]: row for row in model["state_model"]["schema"]["variables"]}
    rows = association["symbol_bindings"]
    _require(type(rows) is list and len(rows) == len(variables), "complete code state symbol bindings required")
    mapping, symbols = {}, set()
    for row in rows:
        _closed(row, {"symbol_id", "state_variable_id"}, "closed code state symbol binding required")
        sid, vid = row["symbol_id"], row["state_variable_id"]
        _require(type(sid) is str and type(vid) is str and vid in variables and vid not in mapping
            and sid not in symbols and expressions.carrier.symbol_types.get(sid) == variables[vid]["type_kind"],
            "unique exact typed code state symbol binding required")
        mapping[vid] = sid; symbols.add(sid)
    _require(symbols == set(expressions.carrier.symbol_types), "all expression symbols must bind code state")
    statements = {row.statement_id: row for row in document.statements}
    meanings = {}
    preconditions = _bindings(association["precondition_bindings"], action.precondition_ids,
        statements, expressions, precondition=True, meanings=meanings)
    effects = _bindings(association["effect_bindings"], action.effect_ids,
        statements, expressions, precondition=False, meanings=meanings)
    carrier_return = expressions.carrier.payload["commands"][0]["expression_ids"][0]
    _require(expressions.reached | {carrier_return} == set(expressions.nodes),
        "every declared interpretation expression must belong to a bound root")
    cases = []
    for original in model["cases"]:
        before = {mapping[key]: value for key, value in original["initial_state"].items()}
        after = {mapping[key]: value for key, value in original["final_state"].items()}
        def checks(bindings, current):
            return [dict(statement_id=row["statement_id"], expression_id=row["expression_id"],
                value=expressions.evaluate(row["expression_id"], before, current)) for row in bindings]
        pre, effect = checks(preconditions, before), checks(effects, after)
        enabled, satisfied = all(row["value"] for row in pre), all(row["value"] for row in effect)
        cases.append(dict(index=original["index"], code_action_id=original["action_id"],
            parameter_values=deepcopy(original["parameter_values"]),
            before_state=deepcopy(original["initial_state"]), after_state=deepcopy(original["final_state"]),
            before_symbols=before, after_symbols=after, preconditions=pre, effects=effect,
            enabled=enabled, preconditions_passed=enabled, effects_passed=satisfied,
            conditional_effects_passed=not enabled or satisfied))
    enabled = sum(row["enabled"] for row in cases)
    counterexamples = [row["index"] for row in cases if row["enabled"] and not row["effects_passed"]]
    status = "no_enabled_cases" if not enabled else "refuted" if counterexamples else "satisfied"
    selected = set(action.precondition_ids) | set(action.effect_ids)
    report = dict(schema=SCHEMA, status=status, scope="selected_existing_action_conditions_only",
        intent_source_text=intent_source, intent_candidate_ir=deepcopy(intent_candidate),
        code_source_text=code_source, code_candidate_ir=deepcopy(code_candidate),
        input_domains=deepcopy(input_domains), association=deepcopy(association), **identity,
        intent_document=wire, source_state_model=model, variable_symbols=mapping,
        intent_source_refs=intent_refs, code_source_refs=code_refs,
        selected_action_id=action.action_id, selected_statement_ids=sorted(selected),
        unselected_action_ids=sorted(set(actions) - {action.action_id}),
        unselected_statement_ids=sorted(set(statements) - selected),
        unmodeled_control_edge_ids=sorted(row.edge_id for row in document.control_edges),
        cases=cases, case_count=len(cases), enabled_case_count=enabled,
        disabled_case_count=len(cases) - enabled, counterexample_case_indices=counterexamples,
        all_input_cases_retained=len(cases) == model["case_count"],
        all_enabled_effects_satisfied=status == "satisfied", bounded_effects_satisfied=False,
        interpretation_origin="explicit_caller_declaration", provider_calls=0, training_steps=0,
        assumptions=[*model["assumptions"],
            "The action-to-code association and condition meanings are explicit caller declarations, not inferred policies or verified instruction translations.",
            "The expression carrier retains code SourceRefs only; exact native Intent SourceRefs remain separately typed and are neither converted nor rebound to code.",
            "Preconditions read the before-state. Effects read the after-state, with explicit old expressions reading the before-state.",
            "Only the selected action's declared preconditions and effects are interpreted; other statements, goals, norms, control edges and actions remain unverified.",
            "All bounded code input cases are retained. Disabled preconditions exclude a case from the conditional contract but do not remove it from the report.",
            "Zero enabled cases are blocked evidence, not vacuous satisfaction. Python evaluation is not a Lean kernel check or execution authorization."], **FALSE)
    report["report_sha256"] = _digest(report)
    return report


def verify_intent_code_effects(report, intent_source, intent_candidate, code_source, code_candidate, input_domains, association):
    """Replay original sources, predictions, native models and every bound case."""
    expected = prepare_intent_code_effects(intent_source, intent_candidate, code_source, code_candidate, input_domains, association)
    _require(_raw(report) == _raw(expected), "Intent/code effects differ from complete source replay")
    return expected


__all__ = ["SCHEMA", "ASSOCIATION_SCHEMA", "REQUIREMENTS_SCHEMA", "PRODUCERS",
    "intent_code_effect_requirements", "prepare_intent_code_effects", "verify_intent_code_effects"]
