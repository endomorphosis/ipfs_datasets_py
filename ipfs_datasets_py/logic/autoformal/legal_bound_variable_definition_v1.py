"""Conditional unary-definition instances at exact bound norm occurrences.

The original norm and every definition alternative remain unchanged. Generated
Lean text is conditional on explicit, unverified interpretation hypotheses; no
membership, governing applicability, source meaning or build result is inferred.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import legal_norm_definition_evidence_v1 as evidence

REQUEST_SCHEMA = "legal-bound-variable-definition-request/v1"
SCHEMA = "legal-bound-variable-definition-report/v1"
PROFILE = "conditional-unary-definition-at-bound-variable/v1"
MAX_REQUEST_BYTES = 128 * 1024
MAX_REPORT_BYTES = evidence.MAX_OUTPUT_BYTES
COMPANION_FIELDS = {"norm_preparation", "request_raw", "expected_norm_preparation_sha256",
    "expected_request_sha256", "norm_inputs", "definitions"}
REQUEST_FIELDS = {"schema", "profile", "companion_sha256", "link_sha256", "alternative_id",
    "target", "binding", "binder_target", "argument", "source_paths", "definition_term_ref",
    "definition_ast_ref", "carrier_map", "evaluation_context", "definition_assumption", "mode",
    "membership_assumption"}
CARRIER_MAP = {"typed_sort": "Object", "native_sort": None, "definition_carrier": "Entity",
    "lean_carrier": "Entity", "mapping": "same_carrier"}
EVALUATION_CONTEXT = {"interpretation": "shared_parameter", "time": "fixed_shared_parameter",
    "variable": "explicit_binder_valuation"}
AUTHORITY = dict(evidence.FALSE_FLAGS, definition_assumption_verified=False,
    membership_assumption_verified=False, binder_valuation_verified=False,
    governing_use_verified=False, norm_witness_extracted=False,
    conditional_theorems_checked=False, lean_compilation_verified=False,
    original_signatures_cover_instance=False)
_SELF_PATH = Path(__file__).resolve()
_EVIDENCE_PATH = Path(evidence.__file__).resolve()
_DIRECT_PINS = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (_SELF_PATH, _EVIDENCE_PATH)}
_OPERATION_PINS = None
_need, _keys, _sha = evidence._need, evidence._keys, evidence._sha


def _wire(value):
    return evidence.norm.correspondence_owner._wire(value, MAX_REPORT_BYTES)


def bound_variable_definition_sha256(value):
    """Hash the full bounded canonical report; this is not a proof check."""
    return hashlib.sha256(_wire(value)).hexdigest()


def _same(left, right):
    return _wire(left) == _wire(right)


def _pure_pins():
    actual = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in _DIRECT_PINS}
    _need(actual == _DIRECT_PINS, "bound-variable definition pure producers changed since import")
    return actual | evidence._pure_pins()


def _owners():
    from ..formalization.autoencoder import native_family_lean_emitters
    from . import legal_family_routes
    return native_family_lean_emitters, legal_family_routes


def _pins(owners):
    global _OPERATION_PINS
    result = _pure_pins()
    observed = evidence._pins(evidence._owners())
    observed.update(owners[1].producer_pins())
    observed.update({str(Path(module.__file__).resolve()):
                     hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in owners})
    for path, pin in observed.items():
        _need(path not in result or result[path] == pin, "bound-variable producer observations disagree")
        result[path] = pin
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(result)
    _need(result == _OPERATION_PINS, "bound-variable operation producers changed since first use")
    return result


def _parse(raw, expected_sha256, *, parent=False):
    _sha(expected_sha256, "bound-variable request")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_REQUEST_BYTES,
          "bounded exact bound-variable request bytes required")
    _need(hashlib.sha256(raw).hexdigest() == expected_sha256, "bound-variable request pin differs")

    def pairs(rows):
        result = {}
        for key, value in rows:
            _need(key not in result, "duplicate bound-variable request key")
            result[key] = value
        return result

    try:
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("finite JSON required")))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError("bounded duplicate-free bound-variable request required") from error
    _need(len(_wire(request)) <= MAX_REQUEST_BYTES, "canonical bound-variable request exceeds bound")
    _keys(request, REQUEST_FIELDS, "bound-variable request")
    _need(request["schema"] == (PARENT_REQUEST_SCHEMA if parent else REQUEST_SCHEMA)
          and request["profile"] == (PARENT_PROFILE if parent else PROFILE),
          "exact conditional bound-variable profile required")
    for field in ("companion_sha256", "link_sha256"):
        _sha(request[field], field)
    _need(_same(request["carrier_map"], CARRIER_MAP), "only explicit shared Object-to-Entity carrier supported")
    _need(_same(request["evaluation_context"], EVALUATION_CONTEXT),
          "one fixed shared interpretation/time and explicit binder valuation required")
    _need(request["mode"] in ("instance_only", "body_with_membership"), "unsupported conditional output mode")
    return request


def _reference(record):
    return {"record_cid": record["record_cid"], "sha256": evidence.norm_definition_evidence_sha256(record)}


def _at(value, path):
    return evidence.norm.correspondence_owner._at(value, path)


def _unary_definition(endpoint, *, parent=False):
    """Restrict the existing V2 native body before the broader renderer loads."""
    term, ast_record = endpoint["term_record"], endpoint["ast_record"]
    _need(endpoint["family"] in ("fol", "tdfol") and
          ast_record["profile"] == ("declared-literal-parent-unary-predicate-definition/v1" if parent
                                    else "declared-scope-v2-source-unary-predicate-definition/v1"),
          "existing V2 unary Boolean definition profile required")
    _need(term["kind"] == "declared_unary_category" and type(term["arity"]) is int
          and term["arity"] == 1 and term["carrier"] == "Entity", "unary Entity definition required")
    ast = ast_record["native_ast"]
    _keys(ast, {"node_type", "quantifier", "variable", "formula"}, "definition quantifier")
    _need(ast["node_type"] == "QuantifiedFormula" and
          _same(ast["quantifier"], {"enum": "Quantifier", "value": "∀"}),
          "universal unary definition required")
    variable = ast["variable"]
    _keys(variable, {"node_type", "name", "sort"}, "definition binder")
    _need(variable["node_type"] == "Variable" and type(variable["name"]) is str
          and bool(variable["name"]) and variable["sort"] is None,
          "one exact native unannotated Object binder required")
    formula = ast["formula"]
    _keys(formula, {"node_type", "operator", "left", "right"}, "definition equivalence")
    _need(formula["node_type"] == "BinaryFormula" and
          _same(formula["operator"], {"enum": "LogicOperator", "value": "↔"}),
          "definition must retain forward head/body equivalence")
    nodes = 0

    def predicate(node):
        _keys(node, {"node_type", "name", "arguments"}, "unary definition predicate")
        _need(node["node_type"] == "Predicate" and type(node["name"]) is str
              and bool(node["name"]) and type(node["arguments"]) is list
              and len(node["arguments"]) == 1 and _same(node["arguments"][0], variable),
              "every definition predicate requires the same exact unary binder")

    def body(node, depth=0):
        nonlocal nodes
        nodes += 1
        _need(nodes <= 4096 and depth <= 64 and type(node) is dict,
              "bounded existing native definition body required")
        kind = node.get("node_type")
        if kind == "Predicate":
            predicate(node)
            _need(node["name"] != term["symbol"], "self-referential definition unsupported")
        elif kind == "UnaryFormula":
            _keys(node, {"node_type", "operator", "formula"}, "definition negation")
            _need(_same(node["operator"], {"enum": "LogicOperator", "value": "¬"}),
                  "only native Boolean negation supported")
            body(node["formula"], depth + 1)
        elif kind == "BinaryFormula":
            _keys(node, {"node_type", "operator", "left", "right"}, "definition Boolean connective")
            _need(any(_same(node["operator"], {"enum": "LogicOperator", "value": op})
                      for op in ("∧", "∨")), "only ordered Boolean conjunction/disjunction supported")
            body(node["left"], depth + 1)
            body(node["right"], depth + 1)
        else:
            raise ValueError("unsupported unary definition body: " + str(kind))

    predicate(formula["left"])
    _need(formula["left"]["name"] == term["symbol"], "exact selected definition head required")
    body(formula["right"])
    return ast, formula["left"], formula["right"]


def _selection(companion, request, inputs, *, parent=False):
    _need(companion["schema"] == (evidence.PARENT_SCHEMA if parent else evidence.SCHEMA)
          and companion["profile"] == (evidence.PARENT_PROFILE if parent else evidence.PROFILE),
          "complete existing norm definition evidence required")
    _need(companion["native_ast_rewritten"] is False and companion["selected_interpretation"] is None
          and companion["governing_definition_use"] is None
          and all(value is False for value in companion["authority"].values()),
          "original unsigned evidence cannot confer governing authority")
    matches = [link for link in companion["links"]
               if evidence.norm_definition_evidence_sha256(link) == request["link_sha256"]]
    _need(len(matches) == 1, "one exact complete original nomination link required")
    link = matches[0]
    target, context = link["request_link"]["target"], link["typed_context"]
    _need(target["kind"] == "variable" and _same(request["target"], target),
          "one exact bound-variable occurrence required; predicates are not variable uses")
    _need(_same(request["binding"], context["binding"]) and context["binding"] is not None
          and _same(request["argument"], context["argument"]) and context["argument"] is not None,
          "exact governing binder and ordered argument role required")
    _need(_same(request["source_paths"], link["request_link"]["source_paths"])
          and _same(request["definition_term_ref"], link["definition_term_ref"])
          and _same(request["definition_ast_ref"], link["definition_ast_ref"]),
          "exact source paths and original definition commitments required")
    _need(request["alternative_id"] == link["request_link"]["alternative_id"],
          "selected nomination belongs to another alternative")
    endpoints = [row for row in companion["definitions"] if row["alternative_id"] == request["alternative_id"]]
    _need(len(endpoints) == 1, "one exact retained definition alternative required")
    endpoint = endpoints[0]["candidate"] if parent else endpoints[0]
    _need(_same(_reference(endpoint["term_record"]), request["definition_term_ref"])
          and _same(_reference(endpoint["ast_record"]), request["definition_ast_ref"]),
          "selected endpoint differs from nomination commitments")
    preparation = inputs["norm_preparation"]
    correspondence = preparation["correspondence"]
    relational = correspondence["relational_fragment"]
    mapping = relational["structural_mapping"]
    _need(sum(_same(target, row) for row in mapping) == 1, "exact original typed/native path mapping required")
    binders = [row for row in mapping if row["typed_path"] == context["binding"]["typed_path"]]
    _need(len(binders) == 1 and _same(request["binder_target"], binders[0]), "exact original binder mapping required")
    binder = binders[0]
    _need(binder["kind"] == "binder" and binder["typed_sort"] == "Object" and binder["native_sort"] is None
          and binder["binder_name"] == context["binding"]["name"], "unsupported binder carrier or identity")
    typed = _at(relational["typed_expression"], target["typed_path"])
    native_variable = _at(relational["native_ast"], target["native_path"])
    native_binder = _at(relational["native_ast"], binder["native_path"])
    _need(_same(typed, link["typed_node"]) and typed["kind"] == "variable"
          and typed["symbol"] == binder["binder_name"], "exact typed bound occurrence required")
    _need(_same(native_variable, native_binder) and native_variable["node_type"] == "Variable"
          and native_variable["name"] == binder["binder_name"] and native_variable["sort"] is None,
          "typed/native binder correspondence differs")
    argument = context["argument"]
    index = argument["index"]
    _need(type(index) is int and 0 <= index < 8, "bounded exact argument index required")
    predicates = [row for row in mapping if row["typed_path"] == argument["predicate_path"]]
    _need(len(predicates) == 1 and predicates[0]["kind"] == "predicate", "exact parent predicate mapping required")
    predicate = _at(relational["native_ast"], predicates[0]["native_path"])
    _need(target["native_path"] == predicates[0]["native_path"] + "/arguments/" + str(index)
          and predicate["node_type"] == "Predicate" and predicate["name"] == argument["symbol"]
          and index < len(predicate["arguments"]) and _same(predicate["arguments"][index], native_variable),
          "ordered native relation argument differs")
    roles = [row for row in relational["argument_roles"] if row["symbol"] == argument["symbol"]]
    _need(len(roles) == 1 and len(roles[0]["roles"]) == len(predicate["arguments"])
          and roles[0]["roles"][index] == argument["role"], "exact declared relation arity/role required")
    _need(_same(request["definition_assumption"], {"kind": "explicit_unverified_parameter",
          "parameter": "hDefinition", "definition_ast_ref": request["definition_ast_ref"]}),
          "explicit unverified definition hypothesis required")
    membership = {"kind": "explicit_unverified_parameter", "parameter": "hMembership",
        "link_sha256": request["link_sha256"], "definition_symbol": endpoint["term_record"]["symbol"],
        "carrier": "Entity"}
    _need((request["mode"] == "instance_only" and request["membership_assumption"] is None)
          or (request["mode"] == "body_with_membership" and _same(request["membership_assumption"], membership)),
          "body output requires an explicit matching unverified membership hypothesis")
    ast, head, body = _unary_definition(endpoint, parent=parent)
    return link, endpoint, binder, native_variable, predicate, ast, head, body


def _preflight(original):
    _pure_pins()
    detached, commitment = evidence._snapshot(original)
    _sha(detached["expected_companion_sha256"], "complete norm definition evidence")
    companion = detached["companion"]
    _need(evidence.norm_definition_evidence_sha256(companion) == detached["expected_companion_sha256"],
          "independent complete evidence pin differs")
    request = _parse(detached["request_raw"], detached["expected_request_sha256"])
    _need(request["companion_sha256"] == detached["expected_companion_sha256"],
          "request names another complete evidence report")
    inputs = detached["companion_inputs"]
    _keys(inputs, COMPANION_FIELDS, "complete original evidence replay inputs")
    evidence._preflight({key: inputs[key] for key in ("norm_preparation", "request_raw", "norm_inputs", "definitions")},
        inputs["expected_norm_preparation_sha256"], inputs["expected_request_sha256"])
    _selection(companion, request, inputs)
    return detached, commitment, request


def _render(endpoint, inputs, request, ast, head, body, owners, *, parent=False, hold=None):
    emitter, routes = owners
    endpoints = [row for row in inputs["definitions"] if row["alternative_id"] == request["alternative_id"]]
    _need(len(endpoints) == 1, "one original selected endpoint replay required")
    # The complete public evidence replay has already validated these original
    # bounded report bytes. They supply a receipt, never a caller-selected path.
    raw = (endpoints[0]["preparation_inputs"] if parent else endpoints[0]["correspondence_inputs"])["candidate_inputs"]["report_raw"]
    original = json.loads(raw.decode("utf-8"))["native"]
    if parent and hold is not None:
        hold("donor_original_native", original)
    _need(_same(original["native_ast"], ast) and original["family"] == endpoint["family"],
          "original donor native receipt differs from exact endpoint")
    native = routes.prepare_native_fragment(family=endpoint["family"],
        formula=original["formula"], expected_ast=ast)
    if parent and hold is not None:
        hold("native_fragment", native)
    _need(_same(native, original) and native["lean_body"] == endpoint["ast_record"]["lean_body"],
          "whole original donor native rendering differs")
    rendering, source, theorems = _render_conditionals(native, ast, head, body, request["mode"], emitter)
    if parent and hold is not None:
        hold("rendering", rendering)
        hold("theorems", theorems)
    return native, rendering, source, theorems


def _render_conditionals(native, ast, head, body, mode, emitter):
    """Render already checked pieces; this seam grants no input qualification."""
    _need(mode in ("instance_only", "body_with_membership"), "unsupported conditional rendering mode")
    _need(_same(ast["formula"]["left"], head) and _same(ast["formula"]["right"], body),
          "conditional rendering must use exact donor subtrees")
    complete = emitter.FormulaRenderer().formula(ast)
    expected = "def formula_0 {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := " + complete
    _need(native["lean_body"] == expected, "whole donor rendering must remain exact")
    environment = {ast["variable"]["name"]: "entity"}
    renderer = emitter.FormulaRenderer()
    head_text = renderer.formula(head, environment)
    body_text = renderer.formula(body, environment)
    source = "namespace LegalBoundVariableDefinition\n" + emitter.PRELUDE + "\n" + native["lean_body"] + "\n"
    source += "def headAt {Entity Agent : Type} (i : Interpretation Entity Agent) (entity : Entity) : Nat → Prop := " + head_text + "\n"
    source += "def bodyAt {Entity Agent : Type} (i : Interpretation Entity Agent) (entity : Entity) : Nat → Prop := " + body_text + "\n"
    source += ("theorem definition_instance {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) (entity : Entity)\n"
        "    (hDefinition : formula_0 i t) : headAt i entity t ↔ bodyAt i entity t := by\n"
        "  exact hDefinition entity\n#print axioms definition_instance\n")
    theorems = ["LegalBoundVariableDefinition.definition_instance"]
    if mode == "body_with_membership":
        source += ("theorem body_instance {Entity Agent : Type} (i : Interpretation Entity Agent) (t : Nat) (entity : Entity)\n"
            "    (hDefinition : formula_0 i t) (hMembership : headAt i entity t) : bodyAt i entity t := by\n"
            "  exact (hDefinition entity).mp hMembership\n#print axioms body_instance\n")
        theorems.append("LegalBoundVariableDefinition.body_instance")
    source += "end LegalBoundVariableDefinition\n"
    return {"environment": environment, "head_expression": head_text, "body_expression": body_text}, source, theorems


def prepare_bound_variable_definition_v1(companion, request_raw, *, expected_companion_sha256,
        expected_request_sha256, companion_inputs):
    """Replay original evidence and prepare conditional text; execute no build."""
    original = dict(companion=companion, request_raw=request_raw,
        expected_companion_sha256=expected_companion_sha256, expected_request_sha256=expected_request_sha256,
        companion_inputs=companion_inputs)
    detached, commitment, request = _preflight(original)
    owners = _owners()
    pins = _pins(owners)

    def fence():
        _need(evidence._snapshot(original)[1] == commitment and evidence._snapshot(detached)[1] == commitment,
              "bound-variable definition inputs changed during operation")
        _need(_pins(owners) == pins, "bound-variable definition producers changed during operation")

    fence()
    checked = evidence.validate_norm_definition_evidence_v1(detached["companion"],
        expected_report_sha256=expected_companion_sha256, **detached["companion_inputs"])
    fence()
    link, endpoint, binder, native_variable, predicate, ast, head, body = _selection(
        checked, request, detached["companion_inputs"])
    native, rendering, source, theorems = _render(endpoint, detached["companion_inputs"], request,
                                                 ast, head, body, owners)
    statements = [{"theorem": theorems[0], "status": "generated_under_explicit_unverified_hypotheses",
        "hypotheses": ["hDefinition : formula_0 i t"],
        "conclusion": "headAt i entity t ↔ bodyAt i entity t", "kernel_checked": False}]
    if request["mode"] == "body_with_membership":
        statements.append({"theorem": theorems[1], "status": "generated_under_explicit_unverified_hypotheses",
            "hypotheses": ["hDefinition : formula_0 i t", "hMembership : headAt i entity t"],
            "conclusion": "bodyAt i entity t", "kernel_checked": False})
    context = link["typed_context"]
    report = {"schema": SCHEMA, "profile": PROFILE, "status": "conditional_unverified_instance_prepared",
        "request": request, "request_sha256": expected_request_sha256,
        "companion_sha256": expected_companion_sha256, "selected_link": link,
        "definition_alternatives": checked["definitions"],
        "nomination_inventory": [{"ordinal": ordinal, "link_sha256": evidence.norm_definition_evidence_sha256(row),
                                  "request_link": row["request_link"]} for ordinal, row in enumerate(checked["links"])],
        "occurrence_binding": {"target": request["target"], "binding": context["binding"],
            "binder_target": binder, "argument": context["argument"], "typed_node": link["typed_node"],
            "native_variable": native_variable, "native_predicate": predicate,
            "source_paths": request["source_paths"], "source_rows": link["source_rows"],
            "norm_source_target": link["norm_source_target"],
            "required_definition_subject": link["required_definition_subject"], "ancestry": context["ancestry"]},
        "original_norm": {"preparation_sha256": checked["norm_preparation_sha256"],
            "correspondence_sha256": checked["norm_correspondence_sha256"], "ast_sha256": checked["norm_ast_sha256"],
            "native_ast_sha256": checked["norm_native_ast_sha256"], "scope_id": checked["norm_scope_id"], "unchanged": True},
        "definition_native_ast": ast, "head_native_ast": head, "body_native_ast": body,
        "definition_native_fragment": native, "rendering": rendering, "lean_source": source,
        "conditional_theorems": theorems, "conditional_theorem_statements": statements,
        "producer_pins": pins, "authority": dict(AUTHORITY),
        "native_ast_rewritten": False, "norm_interpretation_ready": False, "selected_interpretation": None,
        "governing_definition_use": None, "training_mask": 0, "evaluation_gold_mask": 0,
        "backend_executed": False, "lean_compilation_verified": False, "external_complete_inputs_required": True,
        "assumptions": [
            "hDefinition is an explicit unverified hypothesis for the unchanged unary definition at one shared interpretation and fixed Nat time.",
            "The norm's Object sort and donor Entity carrier are explicitly interpreted as the same arbitrary Lean Entity carrier; no coercion or equality between distinct carriers is inferred.",
            "The fresh entity parameter denotes a supplied valuation of the exact governing binder; no existential witness, legal actor identity or membership is extracted from the norm.",
            "Definition instantiation produces only headAt iff bodyAt. The body mode additionally declares hMembership for that same head, entity, interpretation and time.",
            "Original surrounding relations, quantifiers, conditions and modalities remain unchanged; no conjunction, guarded binder, quantifier restriction or modal rewriting is performed.",
            "All original alternatives and unresolved source/meaning reviews remain retained. Hypotheses and generated consequences supply no governing applicability, accepted graph edge or training label.",
            "The generated Lean source and axiom-print commands have not been executed or kernel checked.",
        ]}
    raw = _wire(report)
    fence()
    return json.loads(raw)


def validate_bound_variable_definition_v1(record, companion, request_raw, *, expected_report_sha256,
        expected_companion_sha256, expected_request_sha256, companion_inputs):
    """Require the full independent report pin and exact complete regeneration."""
    _pure_pins()
    _sha(expected_report_sha256, "complete bound-variable report")
    original_raw = _wire(record)
    _need(hashlib.sha256(original_raw).hexdigest() == expected_report_sha256,
          "independent bound-variable report pin differs")
    regenerated = prepare_bound_variable_definition_v1(companion, request_raw,
        expected_companion_sha256=expected_companion_sha256, expected_request_sha256=expected_request_sha256,
        companion_inputs=companion_inputs)
    _need(_wire(record) == original_raw, "offered bound-variable report changed during replay")
    _need(original_raw == _wire(regenerated), "bound-variable report differs from complete regeneration")
    return regenerated


__all__ = ["REQUEST_SCHEMA", "SCHEMA", "PROFILE", "CARRIER_MAP", "EVALUATION_CONTEXT", "AUTHORITY",
    "bound_variable_definition_sha256", "prepare_bound_variable_definition_v1", "validate_bound_variable_definition_v1"]


# Explicit decoded-parent conditional consumer. Legacy public APIs retain the
# original HTML nomination, grammar, renderer and snapshot defaults.
PARENT_REQUEST_SCHEMA = "legal-parent-bound-variable-definition-request/v1"
PARENT_SCHEMA = "legal-parent-bound-variable-definition-report/v1"
PARENT_PROFILE = "conditional-parent-unary-definition-at-bound-variable/v1"
_PARENT_BOUND_PINS = None


def _parent_bound_snapshot(value):
    return evidence._parent_definition_snapshot(value)


def _parent_bound_preflight(original):
    """Bind full original commitments and narrow syntax before render owners."""
    _pure_pins()
    detached, commitment = _parent_bound_snapshot(original)
    _sha(detached["expected_companion_sha256"], "complete parent nomination companion")
    companion = detached["companion"]
    _need(evidence.norm_definition_evidence_sha256(companion) == detached["expected_companion_sha256"],
          "independent complete parent companion pin differs")
    _need(type(companion) is dict and companion.get("schema") == evidence.PARENT_SCHEMA
          and companion.get("profile") == evidence.PARENT_PROFILE,
          "explicit parent nomination companion required")
    _need(all(type(companion[key]) is int and companion[key] == 0 for key in
              ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"))
          and companion["external_context_nominations_applied"] is False
          and companion["shared_context_inferred"] is False,
          "parent nomination masks and unresolved context must remain unchanged")
    request = _parse(detached["request_raw"], detached["expected_request_sha256"], parent=True)
    _need(request["companion_sha256"] == detached["expected_companion_sha256"],
          "parent bound request names another complete companion")
    inputs = detached["companion_inputs"]
    _keys(inputs, COMPANION_FIELDS, "complete original parent companion replay inputs")
    if detached["validating"]:
        _sha(detached["expected_report_sha256"], "complete parent bound report")
        _need(bound_variable_definition_sha256(detached["offered"]) == detached["expected_report_sha256"],
              "independent complete parent bound report pin differs")
        _need(type(detached["offered"]) is dict and detached["offered"].get("schema") == PARENT_SCHEMA
              and detached["offered"].get("profile") == PARENT_PROFILE,
              "explicit parent bound report required")
    # Reuse the upstream pure preflight, including all independently pinned
    # norm, candidate, report and request bodies. No original physical replay
    # or native renderer is dispatched by this check.
    replay = dict(inputs, offered=None, expected_report_sha256=None, validating=False)
    _, _, upstream_parsed = evidence._parent_definition_preflight(replay)
    _selection(companion, request, inputs, parent=True)
    _pure_pins()
    return detached, commitment, {"request": request, "companion": upstream_parsed}


def _parent_bound_pins(owners, evidence_owners):
    global _PARENT_BOUND_PINS
    result = _pure_pins()
    for observed in (evidence._parent_definition_pins(evidence_owners), owners[1].producer_pins(),
                     {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
                      for module in owners}):
        for path, pin in observed.items():
            _need(path not in result or result[path] == pin, "parent bound producer observations disagree")
            result[path] = pin
    if _PARENT_BOUND_PINS is None:
        _PARENT_BOUND_PINS = dict(result)
    _need(result == _PARENT_BOUND_PINS, "parent bound producers changed since first use")
    return result


def _parent_bound_callbacks(owners, evidence_owners):
    functions = (_parent_bound_snapshot, _parent_bound_preflight, _parent_bound_pins,
        _parent_bound_callbacks, _parent_bound_runtime, _parent_bound_serialized_fence,
        _parent_bound_operation, prepare_parent_bound_variable_definition_v1,
        validate_parent_bound_variable_definition_v1, _parse, _selection, _unary_definition,
        _render, _render_conditionals, _owners, _pure_pins, _wire, _same, _reference, _at,
        bound_variable_definition_sha256, owners[1].prepare_native_fragment,
        owners[1].producer_pins, owners[0].FormulaRenderer,
        owners[0].FormulaRenderer.__init__, owners[0].FormulaRenderer.step,
        owners[0].FormulaRenderer.signature, owners[0].FormulaRenderer.term,
        owners[0].FormulaRenderer.formula, owners[0].require, owners[0].string,
        evidence.validate_parent_norm_definition_evidence_v1,
        evidence.prepare_parent_norm_definition_evidence_v1,
        evidence._parent_definition_preflight, evidence._parent_definition_snapshot,
        evidence.norm._parent_review_fingerprint, evidence.norm._parent_review_pure_wire,
        json.loads, json.dumps)
    return evidence._parent_definition_callbacks(evidence_owners) + tuple(
        (function, getattr(function, "__code__", None), id(getattr(function, "__defaults__", None)),
         id(getattr(function, "__kwdefaults__", None))) for function in functions)


def _parent_bound_runtime(owners, evidence_owners):
    return {"schema": PARENT_SCHEMA, "request_schema": PARENT_REQUEST_SCHEMA, "profile": PARENT_PROFILE,
        "authority": dict(AUTHORITY), "carrier_map": CARRIER_MAP, "evaluation_context": EVALUATION_CONTEXT,
        "request_fields": sorted(REQUEST_FIELDS), "companion_fields": sorted(COMPANION_FIELDS),
        "max_request_bytes": MAX_REQUEST_BYTES, "max_report_bytes": MAX_REPORT_BYTES,
        "prelude": owners[0].PRELUDE, "upstream": evidence._parent_definition_runtime(evidence_owners)}


def _parent_bound_serialized_fence(report, expected_wire):
    _need(evidence.norm._parent_review_pure_wire(report) == expected_wire,
          "parent bound report changed after final serialization")


def _parent_bound_operation(original):
    detached, commitment, parsed = _parent_bound_preflight(original)
    owners, evidence_owners = _owners(), evidence._parent_definition_owners()
    _, lineage, scope = evidence_owners
    pins = _parent_bound_pins(owners, evidence_owners)
    callbacks = _parent_bound_callbacks(owners, evidence_owners)
    runtime = evidence.norm._parent_review_pure_wire(_parent_bound_runtime(owners, evidence_owners))
    parsed_commitment = evidence.norm._parent_review_fingerprint(parsed)
    held, physical = [], []
    replay_started = False
    result = serialized = None
    primary = None

    def hold(label, value):
        raw = _wire(value)
        held.append((label, value, raw))
        return raw

    def fence():
        _need(_parent_bound_callbacks(owners, evidence_owners) == callbacks,
              "parent bound replay, renderer or custody callbacks changed")
        _need(evidence.norm._parent_review_pure_wire(_parent_bound_runtime(owners, evidence_owners)) == runtime,
              "parent bound policy or bounds changed")
        _need(_parent_bound_pins(owners, evidence_owners) == pins, "parent bound producer source changed")
        for plan, witness, frozen in physical:
            _need(evidence.norm._parent_review_fingerprint(plan) == frozen,
                  "parent bound physical file plan changed")
            _need(evidence._parent_definition_file_witness(plan, lineage) == witness,
                  "parent bound original physical parent/cache file changed")
        _need(evidence.norm._parent_review_fingerprint(original) == commitment
              and evidence.norm._parent_review_fingerprint(detached) == commitment,
              "parent bound original or detached input changed")
        _need(evidence.norm._parent_review_fingerprint(parsed) == parsed_commitment,
              "parent bound parsed input changed")
        for label, value, raw in held:
            _need(evidence.norm._parent_review_pure_wire(value) == raw,
                  "parent bound actual replay or renderer return changed: " + label)

    def replay():
        checked = evidence.validate_parent_norm_definition_evidence_v1(detached["companion"],
            expected_report_sha256=detached["expected_companion_sha256"], **detached["companion_inputs"])
        raw = hold("nomination_companion", checked)
        _need(hashlib.sha256(raw).hexdigest() == detached["expected_companion_sha256"],
              "complete parent nomination regeneration differs")
        evidence._observe(pins, checked["producer_pins"])
        return checked

    def closing_replay():
        if replay_started:
            fence()  # Refuse altered callbacks before any closing dispatch.
            replay()

    def output_fence():
        if serialized is not None:
            _parent_bound_serialized_fence(result, serialized)
            fence()
            _parent_bound_serialized_fence(result, serialized)

    def terminal_fence():
        fence()
        if serialized is not None:
            _need(evidence.norm._parent_review_pure_wire(result) == serialized,
                  "parent bound output changed after final custody callback")
            _need(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8") == serialized,
                  "parent bound output changed after final direct encoding")

    try:
        fence()
        replay_started = True
        checked = replay()
        fence()
        inputs = detached["companion_inputs"]
        replays = [inputs["norm_inputs"]["correspondence_inputs"]["scope_replay_inputs"]["replay_inputs"]]
        replays.extend(endpoint["preparation_inputs"]["parent_inputs"]["replay_inputs"]
                       for endpoint in inputs["definitions"])
        for replay_inputs in replays:
            fence()
            plan = evidence._parent_definition_file_plan(replay_inputs, lineage)
            frozen = evidence.norm._parent_review_fingerprint(plan)
            witness = evidence._parent_definition_file_witness(plan, lineage)
            physical.append((plan, witness, frozen))
            fence()
        request = parsed["request"]
        link, endpoint, binder, native_variable, predicate, ast, head, body = _selection(
            checked, request, inputs, parent=True)
        native, rendering, lean_source, theorems = _render(endpoint, inputs, request, ast, head, body,
            owners, parent=True, hold=hold)
        fence()
        preparation = checked["norm_preparation"]
        correspondence = preparation["correspondence"]
        relational = correspondence["relational_fragment"]
        _need(relational["source_binding"] is None and relational["source_bound"] is False,
              "original relational source binding must remain explicitly unresolved")
        context = link["typed_context"]
        statements = [{"theorem": theorems[0], "status": "generated_under_explicit_unverified_hypotheses",
            "hypotheses": ["hDefinition : formula_0 i t"],
            "conclusion": "headAt i entity t ↔ bodyAt i entity t", "kernel_checked": False}]
        if request["mode"] == "body_with_membership":
            statements.append({"theorem": theorems[1], "status": "generated_under_explicit_unverified_hypotheses",
                "hypotheses": ["hDefinition : formula_0 i t", "hMembership : headAt i entity t"],
                "conclusion": "bodyAt i entity t", "kernel_checked": False})
        result = {"schema": PARENT_SCHEMA, "profile": PARENT_PROFILE,
            "status": "conditional_unverified_parent_instance_prepared",
            "request": request, "request_sha256": detached["expected_request_sha256"],
            "companion_sha256": detached["expected_companion_sha256"], "companion": checked,
            "selected_link": link,
            "definition_alternative_refs": [{"ordinal": ordinal, "alternative_id": alternative["alternative_id"],
                "preparation_sha256": alternative["preparation_sha256"],
                "candidate_ref": _reference(alternative["candidate"])}
                for ordinal, alternative in enumerate(checked["definitions"])],
            "nomination_inventory": [{"ordinal": ordinal, "link_sha256": evidence.norm_definition_evidence_sha256(row),
                "request_link": row["request_link"]} for ordinal, row in enumerate(checked["links"])],
            "occurrence_binding": {"target": request["target"], "binding": context["binding"],
                "binder_target": binder, "argument": context["argument"], "typed_node": link["typed_node"],
                "native_variable": native_variable, "native_predicate": predicate,
                "source_paths": request["source_paths"], "source_rows": link["source_rows"], "ancestry": context["ancestry"],
                "norm_source_identity": preparation["source_identity"],
                "definition_candidate_ref": link["definition_candidate_ref"]},
            "original_norm": {"preparation_sha256": checked["norm_preparation_sha256"],
                "correspondence_sha256": preparation["correspondence_sha256"],
                "ast_sha256": preparation["ast_sha256"], "native_ast_sha256": preparation["native_ast_sha256"],
                "source_identity": preparation["source_identity"], "source_binding": relational["source_binding"],
                "source_bound": relational["source_bound"], "unchanged": True},
            "definition_native_ast": ast, "head_native_ast": head, "body_native_ast": body,
            "definition_native_fragment": native, "rendering": rendering, "lean_source": lean_source,
            "conditional_theorems": theorems, "conditional_theorem_statements": statements,
            "producer_pins": pins, "authority": dict(AUTHORITY),
            "native_ast_rewritten": False, "norm_interpretation_ready": False,
            "selected_interpretation": None, "governing_definition_use": None,
            "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
            "backend_executed": False, "lean_compilation_verified": False,
            "external_complete_inputs_required": True, "original_signatures_cover_instance": False,
            "assumptions": [
                "hDefinition is an explicit unverified premise for the complete unchanged unary donor at one formal interpretation and fixed Nat time.",
                "The original Object binder is explicitly valued in the same arbitrary Entity carrier; no legal actor, coercion, membership or existential witness is inferred.",
                "Only body_with_membership additionally assumes hMembership for that same selected head, entity, interpretation and time.",
                "The original whole parent nomination, norm AST, every definition alternative and both unavailable source-context populations remain unchanged.",
                "Generated conditional consequences establish no governing definition, source edition, legal meaning, contextual closure, accepted graph edge or learning target.",
                "No substitution into the norm, modality/quantifier rewriting, Lake project, Lean build, signature, model or training is performed.",
            ]}
        serialized = _wire(result)
        if detached["validating"]:
            _need(serialized == _wire(detached["offered"]),
                  "parent bound report differs from complete original regeneration")
        result = json.loads(serialized)
        fence()
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        scope._parent_finish((fence, closing_replay, fence, output_fence, terminal_fence), primary)


def prepare_parent_bound_variable_definition_v1(companion, request_raw, *, expected_companion_sha256,
        expected_request_sha256, companion_inputs):
    """Generate conditional unary text from fully replayed parent nominations."""
    return _parent_bound_operation(dict(companion=companion, request_raw=request_raw,
        expected_companion_sha256=expected_companion_sha256, expected_request_sha256=expected_request_sha256,
        companion_inputs=companion_inputs, offered=None, expected_report_sha256=None, validating=False))


def validate_parent_bound_variable_definition_v1(record, companion, request_raw, *, expected_report_sha256,
        expected_companion_sha256, expected_request_sha256, companion_inputs):
    """Require an independent full report commitment and complete parent replay."""
    return _parent_bound_operation(dict(companion=companion, request_raw=request_raw,
        expected_companion_sha256=expected_companion_sha256, expected_request_sha256=expected_request_sha256,
        companion_inputs=companion_inputs, offered=record, expected_report_sha256=expected_report_sha256,
        validating=True))


__all__ += ["prepare_parent_bound_variable_definition_v1", "validate_parent_bound_variable_definition_v1"]
