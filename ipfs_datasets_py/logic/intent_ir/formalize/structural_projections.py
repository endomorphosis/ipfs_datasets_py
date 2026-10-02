"""Reify Intent declarations in native frame/rule and typed refinement views.

The facts below say what an IntentIR *declares*.  In particular a field with
value ``permitted`` is data, not an authorization assertion.  Parsing these
views does not verify the source language, execute an action, or prove a code
contract.  Refinement needs a caller-supplied typed model bound to the Intent
document; no program model is invented from an action's verb.
"""
from __future__ import annotations

import json

from .projection_contracts import (
    canonical_bytes, make_projection, safe_symbol, source_ir_sha256,
    validated_document,
)

DEFAULT_FAMILIES = ("frame_logic", "datalog", "horn_chc")
MAX_DOCUMENT_BYTES = 128 * 1024
MAX_RECORDS = 256
MAX_FIELDS = 2048
MAX_SYNTAX_BYTES = 768 * 1024
_COLLECTIONS = {
    "sources": ("SourceRef", "ref_id"),
    "statements": ("IntentStatement", "statement_id"),
    "actions": ("IntentAction", "action_id"),
    "control_edges": ("IntentControlEdge", "edge_id"),
}
_FRONTIERS = {
    "refinement": "Explicit source-bound RefinementIR systems, simulation relations, obligations, and boundedness are required.",
    "separation_logic": "A typed heap model, ownership assertions, separating conjunction, and frame conditions are required; Intent declarations do not specify heap ownership.",
    "hyperproperty": "A typed trace-set model, trace quantifiers, and observation relations are required; a single declared intent does not specify noninterference.",
    "epistemic": "A typed agent/world model, accessibility relations, and knowledge or belief scope are required; an action actor alone does not specify epistemic semantics.",
}
_DECLARATION_ASSUMPTIONS = (
    "Every generated fact describes a field of the supplied IntentIR declaration, not an event or truth about program execution.",
    "Modality, confidence, review status, and grounding remain data; permitted does not grant permission and required does not establish compliance.",
    "JSON pointer indexes preserve ordered arguments; each field value is canonical JSON text so scalar types and empty containers remain distinct.",
    "Native parser round trips establish representation fidelity only; correspondence between IntentIR and natural-language intent is unverified.",
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _quote(value):
    # Quoting, rather than syntax interpolation, makes instructions inert even
    # when a declared field contains rules, quotes, or ErgoAI directives.
    return json.dumps(value, ensure_ascii=False)


def _flatten(value, pointer=""):
    if type(value) is dict and value:
        for key in sorted(value):
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from _flatten(value[key], pointer + "/" + escaped)
    elif type(value) is list and value:
        for index, item in enumerate(value):
            yield from _flatten(item, pointer + "/" + str(index))
    else:
        yield pointer, _json(value)


def _declarations(document):
    from ..canonicalize import canonical_intent_ir_bytes

    raw = canonical_intent_ir_bytes(document)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("Intent declaration projection document byte bound exceeded")
    wire = json.loads(raw)
    records = [("", "IntentDocument", document.document_id,
                {key: value for key, value in wire.items() if key not in _COLLECTIONS})]
    # Record locations retain the native wire's order, including set-like
    # collections whose owner determines their canonical serialization.
    for collection, (kind, id_key) in _COLLECTIONS.items():
        for index, record in enumerate(wire[collection]):
            records.append((f"/{collection}/{index}", kind, record[id_key], record))
    if len(records) > MAX_RECORDS:
        raise ValueError("Intent declaration projection record bound exceeded")
    nodes, fields = [], []
    for location, kind, native_id, record in records:
        symbol = safe_symbol(kind + ":" + native_id, prefix="intent")
        nodes.append({"symbol": symbol, "kind": kind, "node_id": native_id,
                      "location": location})
        for pointer, value in _flatten(record):
            fields.append({"subject": symbol, "predicate": pointer, "object": value})
            if len(fields) > MAX_FIELDS:
                raise ValueError("Intent declaration projection field bound exceeded")
    # Empty node collections have no record, so their existence is retained
    # separately. This map plus locations/fields covers the complete wire.
    collections = {key: len(wire[key]) for key in _COLLECTIONS}
    return nodes, fields, collections


def _source_ids(nodes):
    return tuple(dict.fromkeys(node["node_id"] for node in nodes))


def _source(text):
    if len(text.encode("utf-8")) > MAX_SYNTAX_BYTES:
        raise ValueError("Intent declaration projection syntax byte bound exceeded")
    return text


def _observation(validator, passed, **details):
    return {"validator": validator, "status": "passed" if passed else "failed",
            "details": details}


def _frame_view(document, nodes, fields, collections):
    from ...parsers.flogic import parse_print_parse_flogic
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIRFrameLogic

    lines = [f'{row["symbol"]} : {row["kind"]}.' for row in nodes]
    lines += [f'{row["subject"]}[field({_quote(row["predicate"])}) -> {_quote(row["object"])}].'
              for row in fields]
    text = _source("\n".join(lines) + "\n")
    parsed = parse_print_parse_flogic(text)
    exact = bool(parsed.ok and not parsed.document.unsupported
                 and not parsed.document.rules and not parsed.document.queries)
    restored_nodes, restored_fields = [], []
    if exact:
        for statement in parsed.document.facts:
            head = statement.head
            if (head is None or head.subclass_of is not None
                    or head.object.kind.value != "constant" or head.object.arguments):
                exact = False
                continue
            if (head.isa is not None and not head.specs
                    and head.isa.kind.value == "constant" and not head.isa.arguments):
                restored_nodes.append((head.object.name, head.isa.name))
            elif (head.isa is None and len(head.specs) == 1
                  and head.specs[0].kind.value == "scalar_value"
                  and head.specs[0].method.name == "field"
                  and head.specs[0].method.kind.value == "application"
                  and len(head.specs[0].method.arguments) == 1
                  and head.specs[0].method.arguments[0].kind.value == "string"
                  and len(head.specs[0].values) == 1
                  and head.specs[0].values[0].kind.value == "string"):
                spec = head.specs[0]
                restored_fields.append({"subject": head.object.name,
                    "predicate": spec.method.arguments[0].name,
                    "object": spec.values[0].name})
            else:
                exact = False
        exact = bool(exact and restored_nodes == [(n["symbol"], n["kind"]) for n in nodes]
                     and restored_fields == fields)
    # Reuse the triple owner used by modal_frame_logic; its legal text codec is
    # deliberately not used for code intent.
    native = ModalIRFrameLogic.from_triples(fields, ontology_name="intent_declarations/v1",
        graph_id="sha256:" + source_ir_sha256(document),
        metadata={"declaration_data_only": True, "source_semantics_verified": False})
    triples_exact = native.to_triples() == fields
    exact = exact and triples_exact
    return make_projection(document, family_id="frame_logic",
        status="projected" if exact else "partial",
        representation={"format": "intent-flogic-declarations/v1", "source": text,
            "payload": {"nodes": nodes, "collection_sizes": collections,
                        "frame_logic": native.to_dict(), "modality_as_data": True}},
        source_node_ids=_source_ids(nodes), assumptions=_DECLARATION_ASSUMPTIONS,
        validation=[_observation("FLogicFrontend@1.parse_print_parse", exact,
            parsed=parsed.ok, exact_declaration_fields=exact,
            native_triples_preserved=triples_exact,
            diagnostic_codes=[d.code for d in parsed.diagnostics],
            fact_count=len(nodes) + len(fields), solver_calls=0)],
        unsupported=[] if exact else [{"node_id": document.document_id,
            "reason": "Native F-logic syntax or exact declaration readback failed."}],
        semantics="reified_intent_declarations")


def _rule_views(document, nodes, fields, collections, requested):
    from ...parsers.rules import parse_print_parse_rules, lower_to_chc

    expected = [("intent_kind", (row["symbol"], row["kind"])) for row in nodes]
    expected += [("intent_field", (row["subject"], row["predicate"], row["object"]))
                 for row in fields]
    text = _source("\n".join(name + "(" + ",".join(_quote(v) for v in args) + ")."
                             for name, args in expected) + "\n")
    parsed = parse_print_parse_rules(text, profile="datalog")
    exact = bool(parsed.ok and not parsed.document.unsupported
                 and not parsed.document.rules and not parsed.document.queries)
    if exact:
        actual = [(s.head.predicate, tuple(t.name for t in s.head.arguments))
                  for s in parsed.document.facts]
        exact = actual == expected and all(
            s.effect.value == "derive" and not s.body and not s.head.issuer
            and s.head.polarity.value == "positive"
            and all(t.kind.value == "string" for t in s.head.arguments)
            for s in parsed.document.facts)
    observations = [_observation("RuleFrontend@1.parse_print_parse", exact,
        parsed=parsed.ok, exact_declaration_fields=exact, fact_count=len(expected),
        diagnostic_codes=[d.code for d in parsed.diagnostics], solver_calls=0)]
    results = []
    if "datalog" in requested:
        results.append(make_projection(document, family_id="datalog",
            status="projected" if exact else "partial",
            representation={"format": "intent-datalog-declarations/v1", "source": text,
                "payload": {"nodes": nodes, "fields": fields, "collection_sizes": collections,
                            "modality_as_data": True, "native_profile": "datalog"}},
            source_node_ids=_source_ids(nodes), validation=observations,
            assumptions=_DECLARATION_ASSUMPTIONS,
            unsupported=[] if exact else [{"node_id": document.document_id,
                "reason": "Native Datalog syntax or exact declaration readback failed."}],
            semantics="reified_intent_declarations"))
    if "horn_chc" in requested:
        lowering = lower_to_chc(parsed.document) if exact else None
        lossless = bool(lowering and lowering.ok and not lowering.unsupported
                        and not lowering.loss_receipts)
        if lossless:
            restored = [(c.head.predicate, tuple(t.name for t in c.head.arguments))
                        for c in lowering.clauses if c.head is not None]
            lossless = bool(restored == expected and all(not c.body and not c.constraints
                and not c.is_query and c.head is not None and not c.head.issuer
                and c.head.polarity.value == "positive"
                and all(t.kind.value == "string" for t in c.head.arguments)
                for c in lowering.clauses))
        results.append(make_projection(document, family_id="horn_chc",
            status="projected" if lossless else "partial",
            representation={"format": "intent-chc-declarations/v1", "source": text,
                "payload": {"nodes": nodes, "collection_sizes": collections,
                            "modality_as_data": True,
                            "lowering": lowering.to_dict() if lowering else None}},
            source_node_ids=_source_ids(nodes), validation=observations + [_observation(
                "RuleFrontend@1.lower_to_chc", lossless,
                exact_ground_clauses=lossless, solver_calls=0)],
            assumptions=_DECLARATION_ASSUMPTIONS + (
                "Positive ground declaration facts are empty-body Horn clauses; no verification condition or permission rule is inferred.",),
            unsupported=[] if lossless else [{"node_id": document.document_id,
                "reason": "Native Horn lowering was unavailable, lossy, or changed ground declaration facts."}],
            semantics="reified_intent_declarations"))
    return results


def _frontier(document, family):
    return make_projection(document, family_id=family, status="unsupported",
        representation={"format": "intent-typed-context-required/v1",
            "payload": {"required_evidence": _FRONTIERS[family]}, "source": ""},
        source_node_ids=(document.document_id,),
        validation=[{"validator": "typed_context_admission", "status": "not_run",
                     "details": {"typed_context_available": False, "solver_calls": 0}}],
        unsupported=[{"node_id": document.document_id, "reason": _FRONTIERS[family]}],
        assumptions=("Intent declarations alone do not provide this family's program semantics.",),
        semantics="missing_typed_context")


def _refinement(document, evidence):
    from ...software_verification.refinement import RefinementIR
    from ...software_verification.syntax_bridge import SoftwareVerificationSyntaxBridge

    if (type(evidence) is not dict or set(evidence) != {"source_ir_sha256", "document"}
            or evidence["source_ir_sha256"] != source_ir_sha256(document)
            or type(evidence["document"]) is not dict):
        raise ValueError("Refinement evidence must bind the exact source IntentIR and a native wire document")
    canonical_bytes(evidence)
    native = RefinementIR.from_dict(evidence["document"])
    native.validate()
    bridge = SoftwareVerificationSyntaxBridge()
    result = bridge.round_trip(native)
    meaningful = bool(native.simulations and native.obligations and native.boundedness)
    exact = result.exact and result.document.to_dict() == native.to_dict()
    projected = meaningful and exact
    reason = ("Typed refinement requires explicit simulation relations, obligations, and boundedness declarations."
              if not meaningful else "Native refinement syntax round trip did not preserve the model.")
    # The owner's local "simulation" profile is retained in syntax_bridge.
    # It is not a globally registered family profile, so do not assert one.
    return make_projection(document, family_id="refinement",
        status="projected" if projected else "partial",
        representation={"format": "intent-bound-refinement-ir/v1", "source": "",
            "payload": {"source_ir_sha256": evidence["source_ir_sha256"],
                        "document": native.to_dict(), "syntax_bridge": result.to_dict(),
                        "refinement_proved": False, "model_intent_correspondence_verified": False}},
        source_node_ids=(document.document_id,),
        validation=[_observation("RefinementIR@1.from_dict.validate", True,
                        native_document_id=native.document_id, solver_calls=0),
                    _observation("SoftwareVerificationSyntaxBridge@1.round_trip", exact,
                        exact_typed_model=exact, solver_calls=0)],
        assumptions=("The caller supplied this typed model and its association with the IntentIR; the source digest binds identity, not semantic correspondence.",
                     "Systems, simulation relations, obligations and boundedness are preserved as declarations; no simulation obligation has been discharged."),
        unsupported=[] if projected else [{"node_id": document.document_id, "reason": reason}],
        semantics="caller_supplied_refinement_model")


def project_structural_families(document, context=None):
    """Return bounded native projections; request extra families explicitly.

    ``context['structural']['refinement_evidence']`` accepts only
    ``{'source_ir_sha256': <exact Intent digest>, 'document': <RefinementIR wire>}``.
    This is an input modeling assumption, not a certificate. Unknown or malformed
    context fails validation instead of silently replacing it with defaults.
    """
    document = validated_document(document)
    if context is None:
        context = {}
    if type(context) is not dict or type(context.get("structural", {})) is not dict:
        raise ValueError("structured Intent projection context required")
    settings = context.get("structural", {})
    if set(settings) - {"requested_families", "refinement_evidence"}:
        raise ValueError("unknown structural Intent projection context fields")
    evidence = settings.get("refinement_evidence")
    default = [*DEFAULT_FAMILIES, *(["refinement"] if evidence is not None else [])]
    requested = settings.get("requested_families", default)
    if (type(requested) is not list or len(requested) > 8
            or any(type(f) is not str or f not in {*DEFAULT_FAMILIES, *_FRONTIERS} for f in requested)
            or len(set(requested)) != len(requested)):
        raise ValueError("bounded unique supported structural family names required")
    if evidence is not None and "refinement" not in requested:
        raise ValueError("refinement evidence supplied without a requested refinement view")
    results = {}
    if any(f in DEFAULT_FAMILIES for f in requested):
        nodes, fields, collections = _declarations(document)
        if "frame_logic" in requested:
            results["frame_logic"] = _frame_view(document, nodes, fields, collections)
        if "datalog" in requested or "horn_chc" in requested:
            for row in _rule_views(document, nodes, fields, collections, requested):
                results[row["family_id"]] = row
    for family in requested:
        if family not in results:
            results[family] = (_refinement(document, evidence)
                if family == "refinement" and evidence is not None else _frontier(document, family))
    return [results[family] for family in requested]


def validate_structural_projections(reports, document, context=None):
    """Replay native parsers/lowering; a re-signed fabricated report is rejected."""
    if type(reports) is not list:
        raise ValueError("structural projection reports must be a list")
    expected = project_structural_families(document, context)
    if canonical_bytes(reports) != canonical_bytes(expected):
        raise ValueError("structural projection evidence differs from native replay")
    return reports


__all__ = ["DEFAULT_FAMILIES", "project_structural_families", "validate_structural_projections"]
