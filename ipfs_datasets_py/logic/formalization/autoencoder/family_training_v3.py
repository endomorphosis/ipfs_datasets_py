"""Additive, source-bound native projections; structural readiness is not proof.

V1/V2 remain unchanged. V3 exposes the existing Security TLA artifact as a
distinct profile, admits explicit native Intent program/state declarations, and
joins explicit formula declarations to their actual parser/AST owners. It never
infers those declarations from source text or claims their source fidelity.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
from pathlib import Path

from . import family_training as core
from . import family_training_v2 as previous
from . import native_formula_evidence as formulas
from ...software_verification import syntax_bridge

SCHEMA = "domain-family-training-targets/v3"
TypedFamilyEvidence = previous.TypedFamilyEvidence
supplemental_source_ref = previous.supplemental_source_ref
_ADDITIONAL_KINDS = {"intent_ir": {"program", "contract", "state", "transition", "temporal"}}
_IMPORT_PINS = {name: digest for module in (core, previous, syntax_bridge, formulas)
    for name, digest in core._pin(module).items()}
_IMPORT_PINS[__name__] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _guard():
    for name, expected in _IMPORT_PINS.items():
        module = importlib.import_module(name)
        if core._pin(module)[name] != expected:
            raise ValueError("v3 imported projection producer changed")


def family_training_catalog_v3(domain_id):
    _guard()
    catalog = previous.family_training_catalog_v2(domain_id)
    bridge = syntax_bridge.SoftwareVerificationSyntaxBridge()
    available = {bridge.route_for(kind).family_id for kind in _ADDITIONAL_KINDS.get(domain_id, ())}
    routes = formulas.named_logic_routes()
    available.update(row["family_id"] for row in routes)
    for row in catalog["family_inventory"]:
        if row["family_id"] in available:
            row.update(projection_adapter_available=True, applicability="source_bound_explicit_native_model_route",
                frontier="explicit_matching_native_model_or_formula_declaration_required")
    catalog["schema"] = "domain-family-training-catalog/v3"
    catalog["named_formula_routes"] = deepcopy(routes)
    catalog["source_text_to_native_formula_inference"] = False
    return catalog


def _correct_modal_family_views(report, document, requested):
    """Partition complete ModalIR records by declared family, never glyph alone.

    The frozen telemetry aliases temporal F to prohibition and calls every
    temporal record TDFOL. Retain those observations outside active fitting,
    then publish faithful *structural* family partitions. Opaque qualifiers
    are preserved; these rows still lack a native formula/Lake interpretation.
    """
    from ....optimizers.logic_theorem_optimizer import modal_ir
    if type(document) is not modal_ir.ModalIRDocument:
        return
    report["producer_pins"].update(core._pin(modal_ir))
    superseded = {"legal-ir/modal-view/deontic/v1", "legal-ir/modal-view/tdfol/v1"}
    archived = []
    for row in report["projections"]:
        if row["projection_id"] in superseded:
            archived.append({"original_projection": deepcopy(row), "active_for_training": False,
                "reason": "legacy_operator_glyph_and_family_alias_misclassification",
                "replacement_scope": "complete_native_formula_records_partitioned_by_declared_operator_family"})
    report["superseded_projection_observations"] = archived
    report["projections"] = [row for row in report["projections"] if row["projection_id"] not in superseded]
    groups = {"deontic": [], "temporal": [], "unreviewed": []}
    for formula in document.formulas:
        if type(formula.operator) is not modal_ir.ModalIROperator or type(formula.predicate) is not modal_ir.ModalIRPredicate:
            raise ValueError("exact native ModalIR operator and predicate required")
        family = formula.operator.family
        if type(family) is not str or not family or len(family) > 128:
            raise ValueError("bounded explicit native operator family required")
        key = "deontic" if family in {"deontic", "conditional_normative"} else "temporal" if family == "temporal" else "unreviewed"
        groups[key].append(formula.to_dict())
    for key, records in groups.items():
        if not records:
            continue
        records.sort(key=lambda row: row["formula_id"])
        family = "modal" if key == "unreviewed" else key
        failed = key == "unreviewed"
        opaque = [{"formula_id": row["formula_id"], "fields": [field for field in
            ("conditions", "exceptions", "metadata") if row[field]]} for row in records
            if any(row[field] for field in ("conditions", "exceptions", "metadata"))]
        identity = "legal-ir/modal-family/" + key + "/v3"
        if failed:
            report["frontier"].append({"family_id": family,
                "reason": "unreviewed_declared_ModalIR_operator_family", "projection_id": identity,
                "native_formula_records": deepcopy(records)})
        if opaque:
            report["frontier"].append({"family_id": family,
                "reason": "ModalIR_opaque_qualifiers_require_native_interpretation", "projection_id": identity,
                "uninterpreted_fields": opaque})
        if family not in requested:
            # Preserve unrequested declarations as explicit observations; no
            # row is fitted under a caller-selected, different family alias.
            report.setdefault("unrequested_modal_formula_observations", []).append({
                "logic_family": family, "native_formula_records": deepcopy(records),
                "active_for_training": False, "reason": "declared_operator_family_not_requested"})
            continue
        report["projections"].append({"projection_id": identity, "logic_family": family,
            "profile": "modal_ir_" + key + "_structural", "representation_kind": "native_typed_document",
            "producer_id": __name__, "payload": {"schema": "modal-ir-family-partition/v3",
                "document_id": document.document_id, "partition": key, "formulas": records},
            "validation": [{"validator_id": "ModalIR_exact_declared_operator_family_partition",
                "stage": "target", "status": "failed" if failed else "passed",
                "details": {"complete_native_records_preserved": True, "operator_glyph_is_not_a_family": True,
                    "native_family_AST_parser_executed": False, "source_model_fidelity_verified": False}},
                {"validator_id": "ModalIR_opaque_qualifier_semantics", "stage": "target",
                    "status": "failed" if opaque else "passed", "details": {"uninterpreted_fields": opaque}}],
            "qualification_gaps": ["native_structural_partition_not_parser_checked_family_AST",
                "conditions_exceptions_and_metadata_retained_without_interpretation", "source_meaning_not_verified",
                "backend_proofs_not_run", *( ["unreviewed_declared_operator_family"] if failed else [])],
            "ready_for_training": not failed and not opaque, "source_digest": "", **core.AUTHORITY})


def prepare_family_training_targets_v3(domain_id, *, supplemental_inputs=(), formula_inputs=(), **source_inputs):
    """Publish native structural targets without widening semantic authority.

    ``formula_inputs`` are explicit NativeFormulaEvidence declarations, not
    labels or inferred natural-language translations. Exact supplied source
    binding makes a join reproducible; it does not certify its meaning.
    """
    _guard()
    if type(supplemental_inputs) not in (list, tuple) or len(supplemental_inputs) > 16:
        raise ValueError("bounded native supplemental input sequence required")
    if type(formula_inputs) not in (list, tuple) or len(formula_inputs) > 32:
        raise ValueError("bounded native formula input sequence required")
    if domain_id not in core.DOMAINS:
        raise ValueError("supported IR domain required")
    old_inputs, extra_inputs, kinds = [], [], set()
    for item in supplemental_inputs:
        if type(item) is not TypedFamilyEvidence:
            raise ValueError("TypedFamilyEvidence required; labels are not typed models")
        kind = syntax_bridge.kind_of(item.document).value
        if kind in kinds:
            raise ValueError("duplicate supplemental native kind")
        kinds.add(kind)
        if kind in previous._KINDS[domain_id]:
            old_inputs.append(item)
        elif kind in _ADDITIONAL_KINDS.get(domain_id, ()):
            extra_inputs.append(item)
        else:
            raise ValueError("supplemental native kind is not applicable to this domain: " + kind)
    base = previous.prepare_family_training_targets_v2(domain_id, supplemental_inputs=old_inputs, **source_inputs)
    report = deepcopy(base)
    report.update(schema=SCHEMA, v2_report_sha256=base["report_sha256"],
        v2_source_digest=base["source_digest"], additional_native_inputs=[], formula_inputs=[],
        source_text_to_native_formula_inference=False, structural_readiness_is_qualification=False)
    report["producer_pins"].update(_IMPORT_PINS)
    requested = set(report["requested_families"])
    if domain_id == "legal_ir":
        _correct_modal_family_views(report, source_inputs.get("document"), requested)
    need_source = bool(extra_inputs or formula_inputs)
    source = supplemental_source_ref(domain_id, **source_inputs) if need_source else None
    if need_source:
        raw, basis, _ = previous._source_bytes(domain_id, source_inputs)
        report["source_binding_scope"] = {"basis": basis, "source_ref": source.to_dict(), "meaning_verified": False}
    else:
        raw = b""

    def add(identity, family, profile, payload, producer, checks, limitations=()):
        if family in requested:
            report["projections"].append({"projection_id": identity, "logic_family": family,
                "profile": profile, "representation_kind": "native_typed_projection", "producer_id": producer,
                "payload": core._json(payload), "validation": checks,
                "qualification_gaps": ["source_model_fidelity_not_verified", "external_proofs_not_run", *limitations],
                "ready_for_training": core._ready(checks), "source_digest": "", **core.AUTHORITY})

    bridge = syntax_bridge.SoftwareVerificationSyntaxBridge()
    documents = {}
    from ...security_ir import code_logic_projection
    for item in extra_inputs:
        kind = syntax_bridge.kind_of(item.document).value
        if item.source_ref.to_dict() != source.to_dict():
            raise ValueError("supplemental SourceRef differs from exact domain source")
        wire = core._json(item.document)
        code_logic_projection._validate_mapped_refs(wire, source, len(raw))
        native = type(item.document).from_dict(wire)
        if core._wire(core._json(native)) != core._wire(wire):
            raise ValueError("supplemental native reconstruction changed declaration")
        documents[kind] = native
        report["additional_native_inputs"].append({"kind": kind, "source_ref": source.to_dict(), "document": wire})
        for module in (code_logic_projection, importlib.import_module(type(native).__module__)):
            report["producer_pins"].update(core._pin(module))
    report["additional_native_inputs"].sort(key=lambda row: row["kind"])
    for kind, native in sorted(documents.items()):
        route = bridge.route_for(kind)
        if kind == "contract":
            if "program" not in documents:
                report["frontier"].append({"family_id": "program", "reason": "supplemental_contract_requires_matching_native_program"})
                continue
            native.validate_against(documents["program"])
        if kind == "temporal":
            from ...software_verification.temporal import TemporalLogic
            if native.logic is not TemporalLogic.LTL:
                report["frontier"].append({"family_id": route.family_id, "reason": "native_bridge_profile_is_LTL_only", "kind": kind})
                continue
        result = bridge.round_trip(native)
        if not result.exact:
            report["frontier"].append({"family_id": route.family_id, "reason": "native_roundtrip_not_exact", "kind": kind,
                "bridge": result.to_dict()})
            continue
        add(domain_id + "/supplemental/" + kind + "/v3", route.family_id, route.profile_id,
            {"native_document": core._json(native), "typed_expression": result.expression.to_dict(), "bridge": result.to_dict()},
            syntax_bridge.__name__, [{"validator_id": "SoftwareVerificationSyntaxBridge.round_trip", "stage": "target",
                "status": "passed", "details": {"exact": True, "domain_identity": result.domain_identity,
                    "source_model_fidelity_verified": False}}])

    if domain_id == "security_ir" and "transition_system" in requested:
        # Regenerate through the same reviewed, source-bound native route. A
        # successful compile is never reported as a syntax/model checker run.
        native_report = code_logic_projection.project_code_logic(code_unit=source_inputs.get("code_unit"),
            source_bytes=source_inputs.get("source_bytes"), typed_inputs=source_inputs.get("typed_inputs", ()),
            requested_kinds=["transition"])
        from ...backends.tla import compiler as tla
        for module in (code_logic_projection, tla):
            report["producer_pins"].update(core._pin(module))
        for target in native_report["targets"]:
            encoding = target.get("encoding", {})
            if target["kind"] != "transition" or encoding.get("format") != "tla+":
                continue
            artifact = encoding["artifact"]
            add("security_ir/transition/tla_plus/v3", "transition_system", "tla_plus",
                {"native_document": target["native_document"], "artifact": artifact,
                    "source_binding": native_report["source"], "native_bridge": target["bridge"]},
                tla.__name__, [{"validator_id": "TLACompiler.compile_state", "stage": "target", "status": "passed",
                    "details": {"source_bound_native_transition": True, "syntax_checker_executed": False,
                        "model_checker_executed": False, "native_losses": len(artifact["losses"]),
                        "native_generated_properties_are_not_source_obligations": True}}],
                ("bounded_TLA_encoding_not_proved", "native_TLA_losses_retained", "code_model_fidelity_not_verified",
                    "native_BoundedProgress_is_not_a_declared_source_requirement"))

    report["producer_pins"].update(core._pin(formulas))
    seen = set()
    for item in formula_inputs:
        if type(item) is not formulas.NativeFormulaEvidence:
            raise ValueError("NativeFormulaEvidence required; labels are not formulas")
        if item.requirement_id in seen:
            raise ValueError("duplicate named formula requirement")
        seen.add(item.requirement_id)
        value = formulas.prepare_native_formula_evidence(item, source)
        report["formula_inputs"].append({"requirement_id": item.requirement_id,
            "formula": item.formula, "source_ref": item.source_ref.to_dict()})
        report["producer_pins"].update(value["producer_pins"])
        checks = [{"validator_id": "native_formula_evidence." + key, "stage": "target",
            "status": "passed" if value["validation"].get(key) is True else "failed", "details": {
                "requirement_id": item.requirement_id, "source_model_fidelity_verified": False}}
            for key in ("native_parse_passed", "native_structure_checked", "native_reparse_passed")]
        add(domain_id + "/native_formula/" + item.requirement_id + "/v3", value["logic_family"], value["profile"],
            value["payload"], formulas.__name__, checks, value["qualification_gaps"])
    report["formula_inputs"].sort(key=lambda row: row["requirement_id"])

    digest = core._sha({"v2_source_digest": base["source_digest"],
        "additional_native_inputs": report["additional_native_inputs"], "formula_inputs": report["formula_inputs"]})
    report["source_digest"] = report["typed_input_digest"] = digest
    for row in report["projections"]:
        row["source_digest"] = digest
        row["target_sha256"] = core._sha({key: value for key, value in row.items() if key != "target_sha256"})
    report["projections"].sort(key=lambda row: (row["logic_family"], row["projection_id"]))
    if len({row["projection_id"] for row in report["projections"]}) != len(report["projections"]):
        raise ValueError("duplicate projection identity")
    ready = {row["logic_family"] for row in report["projections"] if row["ready_for_training"]}
    catalog = family_training_catalog_v3(domain_id)
    report["frontier"] = [row for row in report["frontier"] if not ("requires" in row
        and row.get("reason") in {item["frontier"] for item in base["family_inventory"]})]
    for row in catalog["family_inventory"]:
        targets = [target for target in report["projections"] if target["logic_family"] == row["family_id"]]
        row.update(requested=row["family_id"] in requested, target_count=len(targets),
            ready_target_count=sum(target["ready_for_training"] for target in targets), ready_for_training=row["family_id"] in ready)
        row["status"] = "not_requested" if not row["requested"] else "targets_available" if row["ready_for_training"] else "unsupported"
        if row["requested"] and not row["ready_for_training"]:
            report["frontier"].append({"family_id": row["family_id"], "reason": row["frontier"], "requires": row["requires"]})
    report["family_inventory"] = catalog["family_inventory"]
    report["ready_for_training"] = bool(ready)
    report["all_requested_families_available"] = requested <= ready
    report["report_sha256"] = core._sha({key: value for key, value in report.items() if key != "report_sha256"})
    _guard()
    validate_family_training_report_v3(report)
    return report


def validate_family_training_report_v3(report, **source_inputs):
    """Verify structural integrity/pins, plus exact replay when inputs are given."""
    _guard()
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("v3 domain family training report required")
    if report.get("report_sha256") != core._sha({key: value for key, value in report.items() if key != "report_sha256"}):
        raise ValueError("v3 family report digest differs")
    if any(report.get("producer_pins", {}).get(name) != digest for name, digest in _IMPORT_PINS.items()):
        raise ValueError("v3 family producer pin required")
    if report.get("source_text_to_native_formula_inference") is not False or report.get("structural_readiness_is_qualification") is not False:
        raise ValueError("structural projections cannot claim source inference or qualification")
    compatible = deepcopy(report)
    compatible["schema"] = core.SCHEMA
    compatible["report_sha256"] = core._sha({key: value for key, value in compatible.items() if key != "report_sha256"})
    core.validate_family_training_report(compatible)
    if source_inputs:
        expected = prepare_family_training_targets_v3(report["domain_id"],
            requested_families=report["requested_families"], **source_inputs)
        if core._wire(expected) != core._wire(report):
            raise ValueError("v3 family report differs from exact typed source replay")
    return report


__all__ = ["SCHEMA", "TypedFamilyEvidence", "supplemental_source_ref", "family_training_catalog_v3",
    "prepare_family_training_targets_v3", "validate_family_training_report_v3"]
