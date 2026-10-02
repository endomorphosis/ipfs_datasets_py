"""Additive domain family targets backed by source-bound native model owners.

V1 targets/checkpoints stay frozen. V2 adds strict UI control/trace lowering and
explicit supplementary models through the native syntax publication bridge.
Projection readiness establishes a structural training target, never that a
caller-supplied model faithfully describes its source or that a theorem holds.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import importlib
from pathlib import Path

from . import family_training as core
from ...ir_core.provenance import SourceRef
from ...software_verification import syntax_bridge

SCHEMA = "domain-family-training-targets/v2"
_KINDS = {
    "intent_ir": {"authorization", "trace"},
    "security_ir": {"authorization", "protocol", "concurrency", "refinement", "trace"},
    "ui_ux_ir": {"program", "contract", "state", "transition", "temporal", "trace", "authorization"},
    "legal_ir": {"authorization", "temporal", "trace"},
}


@dataclass(frozen=True)
class TypedFamilyEvidence:
    document: object
    source_ref: SourceRef

    def __post_init__(self):
        if type(self.source_ref) is not SourceRef or isinstance(self.document, (dict, str, bytes)):
            raise ValueError("native typed model and SourceRef required")
        self.source_ref.validate()
        kind = syntax_bridge.kind_of(self.document)
        if type(self.document) is not syntax_bridge._KIND_TO_TYPE[kind]:
            raise ValueError("exact native model owner required")


def _source_bytes(domain_id, kwargs):
    if domain_id not in core.DOMAINS:
        raise ValueError("supported IR domain required")
    if domain_id == "security_ir":
        from ...security_ir.code_logic_projection import _source_binding
        binding, quarantine = _source_binding(kwargs.get("code_unit"), kwargs.get("source_bytes"))
        if quarantine:
            raise ValueError("exact Security source required for supplementary models: " + quarantine)
        return kwargs["source_bytes"], "exact_code_body", binding
    if kwargs.get("source_text") is not None:
        text = kwargs["source_text"]
        if type(text) is not str or not text or len(text.encode()) > 1048576:
            raise ValueError("bounded exact supplemental source text required")
        return text.encode(), "exact_supplied_source_text", None
    if kwargs.get("ui_training_row") is not None:
        return core._wire(core._json(kwargs["ui_training_row"])), "canonical_UI_training_declaration", None
    document = kwargs.get("document")
    if domain_id == "legal_ir":
        from ....optimizers.logic_theorem_optimizer.modal_ir import ModalIRDocument
        from ...bridge.multiview import MultiViewLegalIRReport
        if type(document) is ModalIRDocument:
            return document.normalized_text.encode(), "native_ModalIR_normalized_source", None
        if type(document) is MultiViewLegalIRReport:
            return document.document.source_text.encode(), "native_legal_bridge_source", None
    if document is None:
        raise ValueError("native source declaration required")
    return core._wire(core._json(document)), "canonical_typed_declaration", None


def supplemental_source_ref(domain_id, **source_inputs):
    """Canonical join for new native evidence; this does not verify its meaning."""
    raw, basis, binding = _source_bytes(domain_id, source_inputs)
    digest = hashlib.sha256(raw).hexdigest()
    if binding is not None:
        return SourceRef(ref_id=binding["code_unit_cid"], source_uri="code-unit:" + binding["code_unit_cid"],
            source_id=binding["path"], source_revision="domain-family-training/v2",
            content_sha256=digest, content_cid=binding["body_cid"])
    return SourceRef(ref_id="source:" + domain_id + ":" + digest,
        source_uri="urn:domain-family-training:" + domain_id + ":" + digest,
        source_id=basis, source_revision="domain-family-training/v2", content_sha256=digest)


def family_training_catalog_v2(domain_id):
    catalog = core.family_training_catalog(domain_id)
    bridge = syntax_bridge.SoftwareVerificationSyntaxBridge()
    available = {bridge.route_for(kind).family_id for kind in _KINDS[domain_id]}
    if domain_id == "ui_ux_ir":
        available |= {"transition_system", "temporal"}
    for row in catalog["family_inventory"]:
        if row["family_id"] in available:
            row.update(projection_adapter_available=True, applicability="source_bound_native_model_route",
                frontier="explicit_matching_native_model_or_supported_UI_declaration_required")
        if row["family_id"] == "horn_chc" and domain_id != "intent_ir":
            row["frontier"] = "no_reviewed_domain_to_Horn_CHC_adapter_authorization_profile_is_not_Horn"
    catalog["schema"] = "domain-family-training-catalog/v2"
    return catalog


def _pins(module):
    return core._pin(module)


def prepare_family_training_targets_v2(domain_id, *, supplemental_inputs=(), **source_inputs):
    if type(supplemental_inputs) not in (list, tuple) or len(supplemental_inputs) > 16:
        raise ValueError("bounded native supplemental input sequence required")
    base = core.prepare_family_training_targets(domain_id, **source_inputs)
    report = deepcopy(base)
    report["schema"] = SCHEMA
    report["base_report_sha256"] = base["report_sha256"]
    report["base_source_digest"] = base["source_digest"]
    report["supplemental_inputs"] = []
    report["derived_native_models"] = []
    report["source_binding_scope"] = None
    report["producer_pins"].update(_pins(importlib.import_module(__name__)))
    report["producer_pins"].update(_pins(syntax_bridge))
    from ...ir_core import provenance, canonical, claims, identity
    from ...syntax_core import ast, signatures, extensions, contracts
    for module in (provenance, canonical, claims, identity, ast, signatures, extensions, contracts):
        report["producer_pins"].update(_pins(module))
    catalog = family_training_catalog_v2(domain_id)
    requested = set(report["requested_families"])
    need_source = bool(supplemental_inputs) or domain_id == "ui_ux_ir"
    source = supplemental_source_ref(domain_id, **source_inputs) if need_source else None
    raw = b""
    if need_source:
        raw, basis, _ = _source_bytes(domain_id, source_inputs)
        report["source_binding_scope"] = {"basis": basis, "source_ref": source.to_dict(),
            "meaning_verified": False}
    bridge = syntax_bridge.SoftwareVerificationSyntaxBridge()
    documents = {}
    for item in supplemental_inputs:
        if type(item) is not TypedFamilyEvidence:
            raise ValueError("TypedFamilyEvidence required; labels are not typed models")
        kind = syntax_bridge.kind_of(item.document).value
        if kind not in _KINDS[domain_id]:
            raise ValueError("supplemental native kind is not applicable to this domain: " + kind)
        if kind in documents:
            raise ValueError("duplicate supplemental native kind")
        if item.source_ref.to_dict() != source.to_dict():
            raise ValueError("supplemental SourceRef differs from exact domain source")
        wire = core._json(item.document)
        from ...security_ir import code_logic_projection
        code_logic_projection._validate_mapped_refs(wire, source, len(raw))
        report["producer_pins"].update(_pins(code_logic_projection))
        reconstructed = type(item.document).from_dict(wire)
        if core._wire(core._json(reconstructed)) != core._wire(wire):
            raise ValueError("supplemental native reconstruction changed declaration")
        documents[kind] = reconstructed
        report["supplemental_inputs"].append({"kind": kind, "source_ref": source.to_dict(), "document": wire})
        report["producer_pins"].update(_pins(importlib.import_module(type(item.document).__module__)))
    report["supplemental_inputs"].sort(key=lambda row: row["kind"])

    def failure(family, reason, **details):
        report["frontier"].append({"family_id": family, "reason": reason, **details})

    def add(identity, family, profile, payload, *, producer, checks, limitations=()):
        if family not in requested:
            return
        row = {"projection_id": identity, "logic_family": family, "profile": profile,
            "representation_kind": "native_typed_projection", "producer_id": producer,
            "payload": core._json(payload), "validation": checks,
            "qualification_gaps": ["source_model_fidelity_not_verified", "external_proofs_not_run", *limitations],
            "ready_for_training": core._ready(checks), "source_digest": "", **core.AUTHORITY}
        report["projections"].append(row)

    def publish(document, identity, *, limitations=()):
        kind = syntax_bridge.kind_of(document).value
        route = bridge.route_for(kind)
        if route.family_id not in requested:
            return
        if kind == "temporal":
            from ...software_verification.temporal import TemporalLogic
            if document.logic is not TemporalLogic.LTL:
                failure(route.family_id, "native_bridge_profile_is_LTL_only", kind=kind)
                return
        result = bridge.round_trip(document)
        if not result.exact:
            failure(route.family_id, "native_roundtrip_not_exact", kind=kind, bridge=result.to_dict())
            return
        add(identity, route.family_id, route.profile_id, {"native_document": core._json(document),
            "typed_expression": result.expression.to_dict(), "bridge": result.to_dict()},
            producer=syntax_bridge.__name__, checks=[{"validator_id": "SoftwareVerificationSyntaxBridge.round_trip",
                "stage": "target", "status": "passed", "details": {"exact": True,
                    "domain_identity": result.domain_identity, "source_model_fidelity_verified": False}}], limitations=limitations)

    for kind, document in sorted(documents.items()):
        if kind == "contract":
            if "program" not in documents:
                failure("program", "supplemental_contract_requires_matching_native_program")
                continue
            document.validate_against(documents["program"])
        publish(document, domain_id + "/supplemental/" + kind + "/v2")

    if domain_id == "ui_ux_ir":
        from . import ui_native_training_views as ui
        from .ui_training_inputs import prepare_ui_training_row
        from ...ui_ux_ir.formalize.roundtrip import _as_document
        from ...software_verification import state, transitions, trace, translations
        from ...ui_ux_ir.model import behavior
        from ...ui_ux_ir.runtime import events
        for module in (ui, state, transitions, trace, translations, behavior, events):
            report["producer_pins"].update(_pins(module))
        document = (prepare_ui_training_row(source_inputs["ui_training_row"]).document
            if source_inputs.get("ui_training_row") is not None else _as_document(source_inputs.get("document")))
        omissions = ui.legacy_ec_omissions(document)
        if omissions:
            for target in report["projections"]:
                if target["projection_id"] == "ui_ux_ir:event_calculus":
                    target["validation"].append({"validator_id": "UI_v2_legacy_EC_scope", "stage": "target",
                        "status": "failed", "details": {"omitted_declared_fields": omissions}})
                    target["ready_for_training"] = False
                    target["qualification_gaps"].append({"code": "UI_legacy_EC_omits_declared_semantics",
                        "omitted_declared_fields": omissions})
                    failure("event_calculus", "UI_legacy_EC_omits_declared_semantics", omitted_declared_fields=omissions)
        if "transition_system" in requested:
            try:
                native = ui.declared_state(document, source)
            except ui.UIProjectionFrontier as error:
                failure("transition_system", str(error))
            else:
                report["derived_native_models"].append({"kind": "UI_declared_state", "document": native.to_dict()})
                publish(native, "ui_ux_ir/declared_state/native/v2", limitations=("untimed_declared_event_labelled_control_only",
                    "actual_event_occurrence_not_asserted", "action_bindings_not_executable_code"))
                from ...backends.tla import compiler as tla
                report["producer_pins"].update(_pins(tla))
                try:
                    artifact = tla.TLACompiler().compile_state(native, module_name="DeclaredUIState")
                except tla.TLACompilerError as error:
                    failure("transition_system", "native_TLA_compile_unsupported", details=str(error))
                else:
                    add("ui_ux_ir/declared_state/tla_plus/v2", "transition_system", "tla_plus", artifact.to_dict(),
                        producer=tla.__name__, checks=[{"validator_id": "TLACompiler.compile_state", "stage": "target",
                            "status": "passed", "details": {"syntax_checker_executed": False,
                                "model_checker_executed": False, "native_losses": len(artifact.losses),
                                "native_generated_properties_are_not_source_obligations": True}}],
                        limitations=("bounded_TLA_encoding_not_proved", "native_TLA_losses_retained",
                            "declared_control_only_no_UI_code_equivalence", "native_BoundedProgress_is_not_a_declared_UI_requirement"))
        if "temporal" in requested:
            try:
                native = ui.supplied_event_prefix(document, source)
            except ui.UIProjectionFrontier as error:
                failure("temporal", str(error))
            else:
                report["derived_native_models"].append({"kind": "UI_supplied_event_prefix", "document": native.to_dict()})
                publish(native, "ui_ux_ir/event_prefix/native/v2", limitations=("supplied_events_not_independently_attested",
                    "finite_prefix_not_complete_or_infinite_trace", "unobserved_propositions_remain_unknown"))

    digest = core._sha({"base_source_digest": base["source_digest"], "supplemental_inputs": report["supplemental_inputs"]})
    report["source_digest"] = report["typed_input_digest"] = digest
    for row in report["projections"]:
        row["source_digest"] = digest
        row["target_sha256"] = core._sha({key: value for key, value in row.items() if key != "target_sha256"})
    report["projections"].sort(key=lambda row: (row["logic_family"], row["projection_id"]))
    if len({row["projection_id"] for row in report["projections"]}) != len(report["projections"]):
        raise ValueError("duplicate projection identity")
    ready_families = {row["logic_family"] for row in report["projections"] if row["ready_for_training"]}
    # Replace v1's generic missing-route rows after real v2 projections ran;
    # retain concrete diagnostics about missing/unsupported individual models.
    report["frontier"] = [row for row in report["frontier"] if not ("requires" in row
        and row.get("reason") in {item["frontier"] for item in base["family_inventory"]})]
    for row in catalog["family_inventory"]:
        values = [target for target in report["projections"] if target["logic_family"] == row["family_id"]]
        row.update(requested=row["family_id"] in requested, target_count=len(values),
            ready_target_count=sum(value["ready_for_training"] for value in values),
            ready_for_training=row["family_id"] in ready_families)
        row["status"] = "not_requested" if not row["requested"] else "targets_available" if row["ready_for_training"] else "unsupported"
        if row["requested"] and not row["ready_for_training"]:
            failure(row["family_id"], row["frontier"], requires=row["requires"])
    report["family_inventory"] = catalog["family_inventory"]
    report["ready_for_training"] = bool(ready_families)
    report["all_requested_families_available"] = requested <= ready_families
    report["report_sha256"] = core._sha({key: value for key, value in report.items() if key != "report_sha256"})
    return report


def validate_family_training_report_v2(report, **source_inputs):
    if type(report) is not dict or report.get("schema") != SCHEMA:
        raise ValueError("v2 domain family training report required")
    if report.get("report_sha256") != core._sha({key: value for key, value in report.items() if key != "report_sha256"}):
        raise ValueError("v2 family report digest differs")
    if __name__ not in report.get("producer_pins", {}):
        raise ValueError("v2 family producer pin required")
    # Reuse all frozen structural, target-hash, coverage and actual-source-pin
    # checks. The compatibility copy is local and never changes the v2 report.
    compatible = deepcopy(report)
    compatible["schema"] = core.SCHEMA
    compatible["report_sha256"] = core._sha({key: value for key, value in compatible.items() if key != "report_sha256"})
    core.validate_family_training_report(compatible)
    if source_inputs:
        expected = prepare_family_training_targets_v2(report["domain_id"],
            requested_families=report["requested_families"], **source_inputs)
        if core._wire(expected) != core._wire(report):
            raise ValueError("v2 family report differs from exact typed source replay")
    return report


__all__ = ["SCHEMA", "TypedFamilyEvidence", "supplemental_source_ref", "family_training_catalog_v2",
    "prepare_family_training_targets_v2", "validate_family_training_report_v2"]
