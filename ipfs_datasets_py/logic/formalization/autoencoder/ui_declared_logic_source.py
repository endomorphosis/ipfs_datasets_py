"""Explicit UI logic candidates joined to declared bounded event semantics.

This is a new authored target contract, not a decoder migration. Both original
source and candidate carry every modal declaration. Source audit cannot append
formulas to a generated component or silently complete an interpretation.
"""
from copy import deepcopy
import importlib
import json

from . import family_training as core
from . import ui_declared_source_fidelity as previous
from . import ui_source_contract_384_v5 as base_owner
from . import native_ui_bounded_event_calculus as events

SOURCE_SCHEMA = "ui-declared-logic-source/v1"
TARGET_KIND = "ui_declared_logic"
SCHEMA = "ui-declared-logic-family-targets/v1"
AUDIT_SCHEMA = "ui-declared-logic-source-audit/v1"
FALSE = {**previous.FALSE, "neural_rich_document_generation_verified": False,
         "current_learned_decoder_compatible": False, "training_token_limit_changed": False}
require, digest = events.require, events.digest
_json = previous.json_audit


def _pins():
    modules = (importlib.import_module(__name__), previous, base_owner, events)
    return {name: sha for module in modules for name, sha in core._pin(module).items()}


def _candidate(value):
    _json._json_input(value)
    previous._closed(value, {"kind", "document", "logic"}, "compound UI candidate")
    require(value["kind"] == TARGET_KIND, "explicit compound UI logic candidate required")
    previous._complete_document(value["document"])
    previous._closed(value["logic"], {"temporal", "tdfol", "dcec"}, "complete UI logic declarations")
    require(any(body is not None for body in value["logic"].values()), "at least one explicit UI logic declaration required")
    require(all(body is None or type(body) is dict for body in value["logic"].values()),
            "each UI logic declaration must be an explicit object or null")
    return value


def _source(source_text):
    require(type(source_text) is str and 0 < len(source_text.encode()) <= previous.MAX_BYTES,
            "bounded original declared UI logic source required")
    try:
        value = json.loads(source_text, object_pairs_hook=previous._unique, parse_constant=previous._constant)
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("invalid declared UI logic source JSON: " + str(error)) from error
    _json._json_input(value)
    previous._closed(value, {"schema", "candidate", "interpretations"}, "UI logic source")
    require(value["schema"] == SOURCE_SCHEMA, "explicit UI logic source version required")
    _candidate(value["candidate"])
    previous._closed(value["interpretations"], {"behavior", "guard", "event"}, "UI logic interpretation bodies")
    require(all(type(body) is dict for body in value["interpretations"].values()),
            "UI logic requires complete explicit behavior, guard and event interpretations")
    native = {"kind": "document", "document": value["candidate"]["document"]}
    previous._bound_options(source_text, native, value["interpretations"])
    return value


def audit_candidate(source_text, candidate):
    """Compare every original candidate field; interpretation replay is separate."""
    require(type(source_text) is str and len(source_text.encode()) <= previous.MAX_BYTES,
            "bounded original UI logic source required")
    before = _json._json_input(candidate)
    original = deepcopy(candidate)
    pins = _pins()
    tree = previous.component_audit.tree_pin.require_workspace_logic_tree()
    native_error = source_error = None
    try:
        _candidate(original)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        native_error = str(error)
    reference = None
    try:
        parsed = _source(source_text)
        reference = parsed["candidate"]
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        source_error = str(error)
    differences = None if reference is None else _json._differences(reference, original)
    exact = native_error is None and source_error is None and not differences
    status = ("native_invalid" if native_error else "source_unsupported" if source_error else
              "source_agreement" if exact else "source_disagreement")
    report = {"schema": AUDIT_SCHEMA, "domain_id": "ui_ux_ir", "status": status,
        "source_text": source_text, "source_sha256": _json._sha(source_text.encode()),
        "candidate": original, "candidate_sha256": _json._sha(before),
        "source_reference": reference, "native_valid": native_error is None,
        "native_error": native_error, "source_supported": source_error is None,
        "source_error": source_error, "source_agreement": exact, "exact": exact,
        "differences": differences, "interpretation_semantics_checked": False,
        "comparison_scope": "entire_original_UI_document_and_modal_declarations",
        "candidate_rewritten": False, "model_inference_executed": False,
        "producer_pins": pins, "resolved_logic_tree": tree,
        "target_token_window": previous._token_window(original) if native_error is None else None,
        **FALSE}
    require(before == _json._json_input(candidate) == _json._json_input(original), "UI logic audit changed candidate")
    require(pins == _pins(), "UI logic source producer changed during audit")
    report["report_sha256"] = digest(report)
    return report


def _prepare(source_text, candidate, requested_families=None):
    audit = audit_candidate(source_text, candidate)
    require(audit["status"] == "source_agreement", "complete UI logic source agreement required: " + audit["status"])
    original_bytes = _json._json_input(candidate)
    declared = _source(source_text)
    native = {"kind": "document", "document": deepcopy(candidate["document"])}
    options = previous._bound_options(source_text, native, declared["interpretations"])
    base = base_owner.prepare_family_targets(source_text, native, requested_families, **options)
    ec_rows = [row for row in base["report"]["projections"] if row["projection_id"] == events.PROJECTION_ID]
    require(len(ec_rows) == 1 and ec_rows[0]["ready_for_training"], "exact prepared bounded UI EC projection required")
    report = deepcopy(base["report"])
    report.update(schema=SCHEMA, base_ui_report=deepcopy(base["report"]),
        declared_logic_source_binding={"source_text": source_text, "candidate": deepcopy(candidate)},
        declared_logic_source_audit_sha256=audit["report_sha256"],
        source_text_to_native_formula_inference=False, structural_readiness_is_qualification=False,
        current_learned_decoder_compatible=False, source_candidate_fields_modified=False)
    report["producer_pins"].update(_pins())
    for field, family, requirement in (("temporal", "temporal", "TFOL"), ("tdfol", "tdfol", "TDFOL"), ("dcec", "dcec", "DCEC")):
        descriptor = candidate["logic"][field]
        if descriptor is None:
            continue
        require(family in report["requested_families"], "declared logic family cannot be omitted: " + family)
        name = "native_ui_dcec_logic" if field == "dcec" else "native_ui_temporal_logic"
        owner = importlib.import_module(__package__ + "." + name)
        arguments = {} if field == "dcec" else {"requirement_id": requirement}
        payload = owner.prepare_payload(source_text, candidate, ec_payload=ec_rows[0]["payload"],
                                        descriptor=descriptor, **arguments)
        identity = owner.PROJECTION_ID if field == "dcec" else owner.PROJECTION_IDS[requirement]
        profile = owner.PROFILE if field == "dcec" else owner.PROFILES[requirement]
        report["producer_pins"].update(owner.producer_pins())
        report["projections"].append({"projection_id": identity, "logic_family": family,
            "profile": profile, "representation_kind": "native_typed_projection", "producer_id": owner.__name__,
            "payload": payload, "ready_for_training": True,
            "validation": [{"validator_id": "complete_declared_UI_modal_AST_and_bounded_EC_binding", "stage": "target",
                "status": "passed", "details": {"Lake_executed": False, "source_meaning_verified": False}}],
            "qualification_gaps": list(payload["limitations"]), "source_digest": "", **core.AUTHORITY})
    report["source_digest"] = report["typed_input_digest"] = digest({
        "base_ui_report_sha256": base["report"]["report_sha256"],
        "source_text": source_text, "candidate": candidate})
    report["projections"].sort(key=lambda row: (row["logic_family"], row["projection_id"]))
    for row in report["projections"]:
        row["source_digest"] = report["source_digest"]
        row["target_sha256"] = digest({k: v for k, v in row.items() if k != "target_sha256"})
    for row in report["family_inventory"]:
        projections = [p for p in report["projections"] if p["logic_family"] == row["family_id"]]
        ready = sum(p["ready_for_training"] for p in projections)
        row.update(target_count=len(projections), ready_target_count=ready, ready_for_training=bool(ready),
            status="not_requested" if not row["requested"] else "targets_available" if ready else "unsupported")
    ready = {row["logic_family"] for row in report["projections"] if row["ready_for_training"]}
    report["all_requested_families_available"] = set(report["requested_families"]) <= ready
    report["report_sha256"] = digest({k: v for k, v in report.items() if k != "report_sha256"})
    require(original_bytes == _json._json_input(candidate), "UI logic preparation changed candidate")
    return {"report": report, "source_inputs": {"source_text": source_text, "candidate": deepcopy(candidate),
            "requested_families": list(report["requested_families"])},
        "audit": {"status": "projected_candidate", "source_audit": audit,
            "base_ui_audit": base["audit"], "modal_declarations_in_original_candidate": True,
            "native_decoder_support_demonstrated": False, "candidate_rewritten": False, **FALSE}}


def prepare_family_targets(source_text, candidate, requested_families=None):
    result = _prepare(source_text, candidate, requested_families)
    validate_family_training_report(result["report"])
    return result


def validate_family_training_report(report, **source_inputs):
    """Validate integrity, and replay exact supplied inputs when provided."""
    require(type(report) is dict and report.get("schema") == SCHEMA and report.get("domain_id") == "ui_ux_ir",
            "declared UI logic family report required")
    require(report.get("report_sha256") == digest({k: v for k, v in report.items() if k != "report_sha256"}),
            "declared UI logic report digest differs")
    require(all(report.get("producer_pins", {}).get(name) == value for name, value in _pins().items()),
            "declared UI logic producer pin differs")
    for name in ("source_text_to_native_formula_inference", "structural_readiness_is_qualification",
                 "current_learned_decoder_compatible", "source_candidate_fields_modified"):
        require(report.get(name) is False, "declared UI logic cannot acquire model or semantic authority")
    compatible = deepcopy(report)
    compatible["schema"] = core.SCHEMA
    compatible["report_sha256"] = digest({k: v for k, v in compatible.items() if k != "report_sha256"})
    core.validate_family_training_report(compatible)
    base_owner.validate_family_training_report(report["base_ui_report"])
    previous._closed(report["declared_logic_source_binding"], {"source_text", "candidate"}, "UI logic source binding")
    if source_inputs:
        require(set(source_inputs) <= {"source_text", "candidate", "requested_families"}
                and {"source_text", "candidate"} <= set(source_inputs), "complete original UI logic inputs required")
        requested = source_inputs.get("requested_families", report["requested_families"])
        require(list(requested) == report["requested_families"], "UI logic family replay scope differs")
        expected = _prepare(source_inputs["source_text"], source_inputs["candidate"], requested)["report"]
        require(core._wire(expected) == core._wire(report), "complete UI logic source/candidate/report replay differs")
    return report


__all__ = ["SOURCE_SCHEMA", "TARGET_KIND", "SCHEMA", "audit_candidate", "prepare_family_targets", "validate_family_training_report"]
