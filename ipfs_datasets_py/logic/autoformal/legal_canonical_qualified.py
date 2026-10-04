"""Reversible canonical LegalIR lowering under explicit caller interpretations.

This narrow bridge retains all seven canonical facets and uses the existing
native qualified Lean emitter. It does not infer qualifier meanings from text.
Its skeleton intentionally cannot compile until a caller supplies every scope,
qualifier expression and clock declaration. The source join proves byte identity,
not that an interpretation is faithful to legislation or that a norm is true.

Bridge hashes use sorted compact UTF-8 JSON (ensure_ascii=False). Hashes inside
native declarations use native.digest, preserving that existing wire contract.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from ..formalization.autoencoder import native_family_lean_emitters as emitters
from ..formalization.autoencoder import native_legal_qualified_lean as native
from ..formalization.autoencoder import native_qualified_lean as qualified
from ..ir_core import provenance
from ..legal_ir import canonical_contracts as contracts

SCHEMA = "legal-canonical-qualified/v1"
INTERPRETATION_SCHEMA = "legal-canonical-qualified-interpretation/v1"
MAPPING_SCHEMA = "legal-canonical-modal-mapping/v1"
DECLARATION_SCOPE = "caller_supplied_interpretation_not_source_translation"
MAX_SOURCE_BYTES = 1_000_000
MAX_IR_BYTES = 262_144
MAX_RULES = 64
_MODALITIES = {"O": "obligation", "P": "permission", "F": "prohibition"}
_DURATION = re.compile(r"(?:within|for at least) [1-9][0-9]{0,6} (?:days?|hours?)")


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    """SHA256 of the bridge's canonical JSON encoding."""
    try:
        return hashlib.sha256(_wire(value)).hexdigest()
    except (TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded JSON value required") from error


def _pins():
    modules = (native, qualified, emitters, provenance, contracts)
    return {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in modules} | {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_IMPORTED_PINS = _pins()


def producer_pins():
    """Return immutable producer identities, refusing source changes after import."""
    if _pins() != _IMPORTED_PINS:
        raise ValueError("canonical qualified producer changed since import")
    return dict(_IMPORTED_PINS)


def _closed(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError("exact " + label + " fields required")


def _candidate(value):
    producer_pins()
    _closed(value, {"candidate_id", "source_text", "source_sha256", "canonical_ir"}, "candidate")
    qualified._text(value["candidate_id"], "candidate_id")
    text = value["source_text"]
    if type(text) is not str or not text.strip():
        raise ValueError("nonblank complete source text required")
    try:
        source_bytes = text.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("valid UTF-8 source required") from error
    if len(source_bytes) > MAX_SOURCE_BYTES:
        raise ValueError("source exceeds byte bound")
    if hashlib.sha256(source_bytes).hexdigest() != value["source_sha256"]:
        raise ValueError("source SHA256 differs from complete source bytes")
    ir = value["canonical_ir"]
    _closed(ir, {"rules"}, "canonical IR")
    if type(ir["rules"]) is not list or not 0 < len(ir["rules"]) <= MAX_RULES:
        raise ValueError("canonical IR requires 1..64 rules")
    for rule in ir["rules"]:
        _closed(rule, {"modality", "actor", "action", "object", "conditions", "exceptions", "temporal"}, "canonical rule")
        for facet in ("conditions", "exceptions", "temporal"):
            if type(rule[facet]) is not list:
                raise ValueError("canonical qualifier facets must be lists")
            for item in rule[facet]:
                qualified._text(item, facet)
        if len(rule["temporal"]) > 1:
            raise ValueError("at most one duration temporal atom per rule is supported")
        if len(rule["conditions"]) + len(rule["temporal"]) > 16 or len(rule["exceptions"]) > 8:
            raise ValueError("native qualifier cardinality exceeded")
        if rule["temporal"] and not _DURATION.fullmatch(rule["temporal"][0]):
            raise ValueError("only explicit within/minimum durations are supported; calendar dates are unsupported")
        # The native predicate grammar is narrower than canonical open vocabulary.
        # Refuse unsupported names rather than renaming a source atom.
        qualified._predicate({"name": rule["action"], "arguments": [rule["actor"]] +
                             ([rule["object"]] if rule["object"] != "" else [])})
    if contracts.CanonicalRoundTripIR.from_dict(ir).to_dict() != ir:
        raise ValueError("canonical IR must already be ordered and deduplicated")
    if len(_wire(ir)) > MAX_IR_BYTES:
        raise ValueError("canonical IR exceeds byte bound")
    return json.loads(_wire(value))


def _mapping(candidate):
    """Construct a structural mapping only; no expressions or clocks are inferred."""
    source_sha, identity = candidate["source_sha256"], digest(candidate)
    source_ref = provenance.SourceRef(
        "source:" + identity, "urn:legal-canonical-qualified:" + identity,
        candidate["candidate_id"], "candidate-source/v1", source_sha)
    source_ref.validate()
    formulas, ledger = [], []
    for index, rule in enumerate(candidate["canonical_ir"]["rules"]):
        formula = {
            "conditions": rule["conditions"] + rule["temporal"], "exceptions": rule["exceptions"],
            "formula_id": "canonical-rule:" + str(index), "metadata": {},
            "operator": {"family": "deontic", "system": "D", "symbol": rule["modality"],
                         "label": _MODALITIES[rule["modality"]]},
            "predicate": {"name": rule["action"], "arguments": [rule["actor"]] +
                          ([rule["object"]] if rule["object"] != "" else []), "role": "clause"},
            "provenance": {"source_id": candidate["candidate_id"], "start_char": 0,
                           "end_char": len(candidate["source_text"]), "citation": None},
        }
        origins = []
        for facet in ("conditions", "temporal", "exceptions"):
            for item_index in range(len(rule[facet])):
                origins.append({"canonical_facet": facet, "canonical_index": item_index,
                    "native_facet": "conditions" if facet == "temporal" else facet,
                    "native_index": item_index + (len(rule["conditions"]) if facet == "temporal" else 0)})
        formulas.append(formula)
        ledger.append({"canonical_rule_index": index, "native_formula_index": index,
                       "canonical_rule_sha256": digest(rule), "native_formula_sha256": native.digest(formula),
                       "qualifier_origins": origins})
    projection = {"projection_id": "canonical-qualified/" + identity + "/deontic/v1",
        "source_digest": source_sha, "logic_family": "deontic", "profile": "modal_ir_deontic_structural",
        "payload": {"schema": "modal-ir-family-partition/v3", "document_id": candidate["candidate_id"],
                    "partition": "deontic", "formulas": formulas}}
    mapping = {"schema": MAPPING_SCHEMA, "candidate_id": candidate["candidate_id"],
        "candidate_sha256": identity, "source_sha256": source_sha,
        "canonical_ir_sha256": digest(candidate["canonical_ir"]), "rules": ledger}
    return projection, mapping, source_ref


def reconstruct_canonical(native_projection, reversible_mapping):
    """Invert the bridge's structural map, checking complete facet accounting.

    This is structural validation only. A caller cannot establish source fidelity
    by supplying a self-consistent projection and mapping.
    """
    try:
        producer_pins()
        mapping = reversible_mapping
        _closed(mapping, {"schema", "candidate_id", "candidate_sha256", "source_sha256",
                          "canonical_ir_sha256", "rules"}, "reversible mapping")
        if mapping["schema"] != MAPPING_SCHEMA:
            raise ValueError("mapping schema differs")
        _closed(native_projection, {"projection_id", "source_digest", "logic_family", "profile", "payload"}, "native projection")
        payload = native_projection["payload"]
        _closed(payload, {"schema", "document_id", "partition", "formulas"}, "native payload")
        if (native_projection["logic_family"] != "deontic" or
                native_projection["profile"] != "modal_ir_deontic_structural" or
                payload["schema"] != "modal-ir-family-partition/v3" or payload["partition"] != "deontic" or
                payload["document_id"] != mapping["candidate_id"] or
                native_projection["source_digest"] != mapping["source_sha256"]):
            raise ValueError("mapping family or source identity differs")
        formulas, records = payload["formulas"], mapping["rules"]
        if type(formulas) is not list or type(records) is not list or not 0 < len(formulas) <= MAX_RULES or len(formulas) != len(records):
            raise ValueError("complete ordered rule mapping required")
        rules = []
        for index, (formula, record) in enumerate(zip(formulas, records)):
            _closed(record, {"canonical_rule_index", "native_formula_index", "canonical_rule_sha256",
                             "native_formula_sha256", "qualifier_origins"}, "rule mapping")
            if (type(record["canonical_rule_index"]) is not int or type(record["native_formula_index"]) is not int or
                    record["canonical_rule_index"] != index or record["native_formula_index"] != index or
                    native.digest(formula) != record["native_formula_sha256"]):
                raise ValueError("ordered formula mapping or hash differs")
            args, operator = formula["predicate"]["arguments"], formula["operator"]
            if type(args) is not list or len(args) not in (1, 2) or operator != {
                    "family": "deontic", "system": "D", "symbol": operator["symbol"],
                    "label": _MODALITIES.get(operator["symbol"])} or operator["symbol"] not in _MODALITIES:
                raise ValueError("reversible deontic predicate/operator required")
            rule = {"modality": operator["symbol"], "actor": args[0], "action": formula["predicate"]["name"],
                    "object": args[1] if len(args) == 2 else "", "conditions": [], "exceptions": [], "temporal": []}
            origins, seen = record["qualifier_origins"], set()
            if type(origins) is not list:
                raise ValueError("qualifier origin ledger required")
            expected_order = []
            for origin in origins:
                _closed(origin, {"canonical_facet", "canonical_index", "native_facet", "native_index"}, "qualifier origin")
                facet, ni, nf = origin["canonical_facet"], origin["native_index"], origin["native_facet"]
                if facet not in ("conditions", "exceptions", "temporal") or nf != ("conditions" if facet == "temporal" else facet):
                    raise ValueError("qualifier origin facet differs")
                if (type(origin["canonical_index"]) is not int or origin["canonical_index"] != len(rule[facet]) or
                        type(ni) is not int or ni < 0 or (nf, ni) in seen):
                    raise ValueError("qualifier mapping duplicates, order or index differs")
                rule[facet].append(formula[nf][ni])
                seen.add((nf, ni))
            for facet in ("conditions", "temporal", "exceptions"):
                for j in range(len(rule[facet])):
                    expected_order.append({"canonical_facet": facet, "canonical_index": j,
                        "native_facet": "conditions" if facet == "temporal" else facet,
                        "native_index": j + (len(rule["conditions"]) if facet == "temporal" else 0)})
            if origins != expected_order or seen != {(facet, j) for facet in ("conditions", "exceptions") for j in range(len(formula[facet]))}:
                raise ValueError("complete ordered qualifier accounting required")
            if digest(rule) != record["canonical_rule_sha256"]:
                raise ValueError("reconstructed canonical rule hash differs")
            rules.append(rule)
        result = {"rules": rules}
        if contracts.CanonicalRoundTripIR.from_dict(result).to_dict() != result or digest(result) != mapping["canonical_ir_sha256"]:
            raise ValueError("reconstructed canonical IR hash or order differs")
        return result
    except (KeyError, IndexError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid reversible canonical mapping") from error


def interpretation_skeleton(candidate):
    """Bind immutable source/index identities, leaving all semantic choices unset.

    Conditions and temporal stay separate in the canonical ledger even though
    the native ModalIR transport stores both in its conditions array.
    """
    try:
        candidate = _candidate(candidate)
        projection, mapping, _ = _mapping(candidate)
        formulas = []
        for index, (rule, formula) in enumerate(zip(candidate["canonical_ir"]["rules"], projection["payload"]["formulas"])):
            temporal = None
            if rule["temporal"]:
                temporal = {"source_index": len(rule["conditions"]), "source_text": rule["temporal"][0],
                    "temporal_kind": None, "quantity": None, "unit": None, "time_domain": None,
                    "origin": None, "lower_inclusive": None, "upper_inclusive": None}
            formulas.append({"formula_index": index, "original_formula_sha256": native.digest(formula),
                "kind": "activation_guarded_legal_rule", "activation_scope": None,
                "conditions": [{"source_index": j, "source_text": text, "expression": None}
                               for j, text in enumerate(rule["conditions"])],
                "temporal": temporal, "exception_scope": None,
                "exceptions": [{"source_index": j, "source_text": text, "expression": None}
                               for j, text in enumerate(rule["exceptions"])]})
        return {"schema": INTERPRETATION_SCHEMA, "candidate_id": candidate["candidate_id"],
            "candidate_sha256": digest(candidate), "source_sha256": candidate["source_sha256"],
            "canonical_ir_sha256": digest(candidate["canonical_ir"]), "mapping_sha256": digest(mapping),
            "declaration_scope": DECLARATION_SCOPE, "formulas": formulas}
    except (KeyError, IndexError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid canonical candidate") from error


def prepare_canonical_qualified(candidate, interpretation):
    """Return a closed reproducible lowering record or raise ValueError.

    Deontic modalities remain caller-interpreted, including the explicit-clock
    annotation for unqualified rules. This profile does not assert equivalence
    to the old unqualified emitter whose modal annotation was absent.
    """
    try:
        candidate = _candidate(candidate)
        projection, mapping, source_ref = _mapping(candidate)
        skeleton = interpretation_skeleton(candidate)
        _closed(interpretation, set(skeleton), "canonical interpretation")
        if any(interpretation[key] != skeleton[key] for key in skeleton if key != "formulas"):
            raise ValueError("interpretation candidate, source, canonical or mapping binding differs")
        if len(_wire(interpretation)) > MAX_IR_BYTES:
            raise ValueError("interpretation exceeds byte bound")
        declarations = interpretation["formulas"]
        rules = candidate["canonical_ir"]["rules"]
        if type(declarations) is not list or len(declarations) != len(rules):
            raise ValueError("complete ordered canonical declarations required")
        for rule, declaration in zip(rules, declarations):
            if type(declaration) is not dict:
                raise ValueError("native formula declaration required")
            # A native consumer cannot infer which flattened condition belonged
            # to the canonical temporal facet. Enforce that distinction here.
            temporal = declaration.get("temporal")
            if rule["temporal"]:
                if (type(temporal) is not dict or type(temporal.get("source_index")) is not int or
                        temporal.get("source_index") != len(rule["conditions"]) or
                        temporal.get("source_text") != rule["temporal"][0]):
                    raise ValueError("canonical temporal facet must be interpreted exactly, never dropped or exchanged")
            elif temporal is not None:
                raise ValueError("canonical activation condition cannot become temporal")
        evidence = native.LegalQualifierInterpretation.from_dict({
            "schema": native.EVIDENCE_SCHEMA, "source_ref": source_ref.to_dict(),
            "original_projection_id": projection["projection_id"], "original_source_digest": projection["source_digest"],
            "original_payload_sha256": native.digest(projection["payload"]),
            "declaration_scope": DECLARATION_SCOPE, "formulas": declarations})
        prepared = native.prepare_qualified_payload(projection, evidence, expected_source_ref=source_ref)
        code, details = native.emit_projection(prepared)
        if reconstruct_canonical(projection, mapping) != candidate["canonical_ir"]:
            raise ValueError("canonical native mapping is not exactly reversible")
        details = dict(details, canonical_facets_preserved=True,
            origin_provenance_scope="whole_source_identity_not_qualifier_span_alignment",
            supported_family_profile="deontic/canonical-explicit-qualified/v1",
            old_unqualified_lowering_equivalence_verified=False,
            clock_unit_conversion_verified=False)
        return json.loads(_wire({"schema": SCHEMA, "candidate_id": candidate["candidate_id"],
            "candidate_sha256": digest(candidate), "source_sha256": candidate["source_sha256"],
            "canonical_ir_sha256": digest(candidate["canonical_ir"]),
            "interpretation_sha256": digest(interpretation), "mapping_sha256": digest(mapping),
            "source_ref": source_ref.to_dict(), "original_canonical_ir": candidate["canonical_ir"],
            "reversible_mapping": mapping, "native_projection": projection,
            "declaration_scope": DECLARATION_SCOPE, "interpretation": interpretation,
            "qualified_projection": prepared, "lean_body": code, "lowering_details": details,
            "producer_pins": producer_pins(), "source_semantics_verified": False,
            "source_text_inference_executed": False, "admitted": False}))
    except (KeyError, IndexError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("invalid canonical candidate or explicit interpretation") from error
