"""Actual domain projections as auxiliary training targets, with full inventory.

Registry publication is never training readiness. Targets here are deterministic
typed-IR views, not learned source decodes, theorem proofs, or source semantics.
Missing model evidence stays in the inventory/frontier and never becomes a
synthetic target. The frozen domain compilers and checkpoints are unchanged.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from collections.abc import Mapping
from enum import Enum
import hashlib
import importlib
import json
from pathlib import Path
import re

SCHEMA = "domain-family-training-targets/v1"
DOMAINS = ("intent_ir", "security_ir", "ui_ux_ir", "legal_ir")
AUTHORITY = {"proof_authority": False, "execution_authority": False,
    "source_semantics_verified": False, "source_decoder_trained": False,
    "all_logic_families_supported": False}

# Evidence requirements are model contracts, not inferred facts or formulas.
REQUIREMENTS = {
    "agency": "explicit agents, actions, choices, and agency semantics",
    "argumentation": "explicit arguments, attacks, and extension semantics",
    "authorization": "principals, permissions, delegation, and authorization policy",
    "bdi": "separate belief, desire, intention and update declarations",
    "concurrency": "shared state, interference, scheduling and synchronization model",
    "cryptographic_protocol": "protocol roles, primitives, adversary and security claims",
    "datalog": "range-restricted facts/rules and closed rule semantics",
    "dcec": "typed agents, modal/event scope and any required time premises",
    "defeasible_logic": "rules, exceptions, priority and conflict resolution semantics",
    "deontic": "explicit normative modality, argument order, conditions and exceptions",
    "dependent_type": "dependent types, terms and an explicit kernel encoding",
    "description_logic": "ontology concepts, roles and a declared description-logic fragment",
    "doxastic": "explicit beliefs and belief-accessibility semantics",
    "epistemic": "explicit knowledge and epistemic-accessibility semantics",
    "epistemic_temporal": "joint epistemic accessibility and temporal model",
    "event_calculus": "events, fluents, occurrence times and initiation/termination rules",
    "finite_field_constraint": "field modulus, typed variables and arithmetic constraints",
    "first_order": "typed predicates, ordered arguments and explicit quantifier scope",
    "frame_logic": "object identities, slots, classes and structural relationships",
    "fuzzy_weighted": "explicit grades, combination operators and calibrated semantics",
    "higher_order": "typed terms and explicit parameterization/kernel encoding",
    "horn_chc": "Horn clauses, typed constraints and relation signatures",
    "hyperproperty": "multiple traces, trace quantifiers and relational policies",
    "intention_agency": "explicit intended action declarations; not beliefs or observations",
    "linear_logic": "resources and linear consumption/production semantics",
    "modal": "declared modal operators and accessibility/frame assumptions",
    "mu_calculus": "transition model and scoped least/greatest fixed points",
    "nonmonotonic_logic": "explicit defaults, negation and consequence semantics",
    "probabilistic": "explicit probability model; model confidence is not probability of truth",
    "process_calculus": "processes, communication channels and operational semantics",
    "program": "typed program/control-flow/contracts with source binding",
    "propositional": "closed proposition vocabulary and Boolean structure",
    "refinement": "typed source/target models and explicit refinement relation",
    "relevance_paraconsistent": "declared relevance/inconsistency-tolerant consequence relation",
    "separation_logic": "typed heap, ownership and frame/resource semantics",
    "session_process": "participants, message types and session ordering",
    "situation_calculus": "actions, situations and successor-state axioms",
    "tdfol": "explicit deontic/temporal scope and first-order arguments",
    "temporal": "time/trace semantics and explicit temporal properties",
    "transition_system": "states, initial condition and explicit transition relation",
}
_NATIVE = {
    "intent_ir": {"first_order", "deontic", "intention_agency", "program", "temporal",
        "dcec", "tdfol", "event_calculus", "frame_logic", "datalog", "horn_chc",
        "transition_system", "higher_order", "refinement"},
    "security_ir": {"program", "transition_system", "temporal", "separation_logic", "hyperproperty"},
    "ui_ux_ir": {"frame_logic", "event_calculus", "tdfol", "dcec"},
    "legal_ir": {"deontic", "tdfol", "frame_logic", "event_calculus"},
}
_RELATED = {
    "intent_ir": {"agency", "bdi", "authorization", "epistemic", "doxastic", "modal", "propositional",
        "concurrency", "session_process", "refinement", "defeasible_logic", "situation_calculus"},
    "security_ir": {"authorization", "first_order", "higher_order", "horn_chc", "refinement", "concurrency",
        "session_process", "process_calculus", "linear_logic", "cryptographic_protocol", "finite_field_constraint",
        "datalog", "propositional", "mu_calculus", "dependent_type"},
    "ui_ux_ir": {"program", "transition_system", "temporal", "authorization", "epistemic", "intention_agency",
        "concurrency", "refinement", "higher_order", "first_order", "propositional", "modal"},
    "legal_ir": {"tdfol", "dcec", "event_calculus", "frame_logic", "first_order", "higher_order", "temporal",
        "authorization", "modal", "argumentation", "defeasible_logic", "description_logic", "nonmonotonic_logic",
        "epistemic", "doxastic", "intention_agency", "relevance_paraconsistent", "propositional"},
}


def _json(value):
    if hasattr(value, "to_dict"):
        return _json(value.to_dict())
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {key: _json(item) for key, item in value.items()}
    if type(value) in (tuple, list):
        return [_json(item) for item in value]
    if type(value) in (set, frozenset):
        return sorted((_json(item) for item in value), key=lambda item: _wire(item))
    return value


def _wire(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("family training record exceeds byte bound")
    return raw


def _sha(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _families():
    from ...families.canonical_catalog import DEFAULT_CANONICAL_CATALOG_SNAPSHOT
    return tuple(DEFAULT_CANONICAL_CATALOG_SNAPSHOT.family_ids)


def family_training_catalog(domain_id):
    """Inventory all canonical families; availability still requires projection."""
    from ...families.registry import DEFAULT_REGISTRY
    if domain_id not in DOMAINS:
        raise ValueError("explicit supported IR domain required")
    rows = []
    for family in _families():
        known = family in _NATIVE[domain_id]
        frontier = "typed_input_and_successful_native_projection_required" if known else "domain_training_adapter_not_implemented"
        if domain_id == "legal_ir" and family in {"dcec", "modal", "temporal"}:
            frontier = "existing_modal_and_legal_bridge_views_require_separate_typed_source_adapter"
        rows.append({"family_id": family, "registry_layer": "baseline_v2" if family in DEFAULT_REGISTRY.families else "published_extension_v3",
            "applicability": "native_projection_route" if known else "domain_related_explicit_model" if family in _RELATED[domain_id] else "specialized_explicit_model",
            "projection_adapter_available": known, "requires": REQUIREMENTS.get(family, "reviewed domain model and adapter"),
            "frontier": frontier, "ready_for_training": False})
    return {"schema": "domain-family-training-catalog/v1", "domain_id": domain_id,
        "family_inventory": rows, "registry_presence_establishes_support": False, **AUTHORITY}


def _pin(module):
    return {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}


def _rich_pins():
    from ...intent_ir.formalize import rich_logic, rich_grammar, modal_projections, state_projections
    from .. import typed_slots
    from ...syntax_core import ast, signatures, extensions
    from ...CEC.native import dcec_core, dcec_integration
    from ...TDFOL import tdfol_core, tdfol_parser
    return {name: digest for module in (rich_logic, rich_grammar, modal_projections, state_projections,
        typed_slots, ast, signatures, extensions, dcec_core, dcec_integration, tdfol_core, tdfol_parser)
        for name, digest in _pin(module).items()}


def _ready(checks):
    required = [row for row in checks if row.get("stage", "target") == "target" and row.get("required", True)]
    return bool(required) and all(row.get("status") == "passed" for row in required)


def prepare_family_training_targets(domain_id, *, document=None, source_text=None, context=None,
        code_unit=None, source_bytes=None, typed_inputs=(), ui_training_row=None, requested_families=None):
    """Execute native projectors and expose ready structural auxiliary targets.

    Intent accepts native IntentIR or a bounded rich AST plus exact instruction.
    Security requires CodeUnit, exact bytes and native CodeLogicEvidence. UI
    accepts native RoundTripDocument/FormalizationInputs. Legal accepts native
    CanonicalRoundTripIR, ModalIRDocument or native MultiViewLegalIRReport.
    Opaque qualifiers remain structural fields, not proved formulas.
    """
    from ...families import registry, canonical_catalog
    requested = list(_families() if requested_families is None else requested_families)
    if (type(requested_families) not in (type(None), list, tuple) or not requested
            or any(type(item) is not str or item not in _families() for item in requested)
            or len(set(requested)) != len(requested)):
        raise ValueError("unique canonical family IDs required; profiles/aliases are not families")
    catalog = family_training_catalog(domain_id)
    if source_text is not None and (type(source_text) is not str or len(source_text.encode()) > 1048576):
        raise ValueError("bounded optional exact source text required")
    if source_bytes is not None and (type(source_bytes) is not bytes or len(source_bytes) > 4_000_000):
        raise ValueError("bounded exact source bytes required")
    if type(typed_inputs) not in (list, tuple) or len(typed_inputs) > 7:
        raise ValueError("bounded native typed input sequence required")
    if domain_id != "security_ir" and (code_unit is not None or source_bytes is not None or typed_inputs):
        raise ValueError("code evidence belongs only to SecurityIR")
    if domain_id != "intent_ir" and context is not None:
        raise ValueError("this context contract belongs only to IntentIR")
    if domain_id == "security_ir" and (document is not None or source_text is not None):
        raise ValueError("SecurityIR source contract requires code_unit/source_bytes")
    if ui_training_row is not None and (domain_id != "ui_ux_ir" or document is not None or source_text is not None):
        raise ValueError("UI training row requires UI domain and is exclusive with document/source_text")
    source_hash = hashlib.sha256(source_bytes).hexdigest() if source_bytes is not None else hashlib.sha256(source_text.encode()).hexdigest() if source_text is not None else None
    binding = {"domain_id": domain_id, "document": _json(document), "source_sha256": source_hash,
        "context": _json(context), "code_unit": _json(code_unit), "typed_inputs": _json(typed_inputs),
        "ui_training_row": _json(ui_training_row)}
    source_digest = _sha(binding)
    pins = {__name__: hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), **_pin(registry), **_pin(canonical_catalog)}
    targets, frontier, gaps, views = [], [], [], []

    def add(family, identity, payload, *, producer, checks, profile=None, kind="domain_structured_formula", limitations=()):
        if family not in requested:
            return
        if payload is None or payload == {} or payload == []:
            frontier.append({"family_id": family, "reason": "empty_native_projection", "projection_id": identity})
            return
        row = {"projection_id": identity, "logic_family": family, "payload": _json(payload),
            "representation_kind": kind, "profile": profile, "producer_id": producer,
            "validation": _json(checks), "qualification_gaps": _json(list(limitations)),
            "ready_for_training": _ready(checks), "source_digest": source_digest, **AUTHORITY}
        row["target_sha256"] = _sha(row)
        targets.append(row)

    def envelope(value):
        wire = value.to_dict()
        views.append({"schema": wire["schema_version"], "digest": value.digest,
            "source_digest": value.source_digest, "validation": wire["validation"], "unsupported": wire["unsupported"]})
        gaps.extend(wire["qualification_gaps"])
        checks = wire["validation"] + [{"validator_id": "native_envelope_readiness", "stage": "target",
            "status": "passed" if wire["ready_for_training"] else "failed", "details": {}}]
        for row in wire["projections"]:
            if row["logic_family"] is None:
                continue  # Verification roles never become logic families.
            add(row["logic_family"], row["projection_id"], row["expression"], producer=row["producer_id"],
                profile=row.get("profile"), kind=row["representation_kind"], checks=checks,
                limitations=wire["qualification_gaps"])
        return wire

    def extension(row, producer):
        family = row["family_id"]
        if family not in requested:
            return
        if row["status"] == "unsupported":
            frontier.append({"family_id": family, "reason": "native_projection_unsupported", "details": row.get("unsupported", [])})
            return
        checks = [{"validator_id": producer, "stage": "target", "status": "passed",
            "details": {"projection_status": row["status"], "scope": "deterministic_typed_projection_only"}}]
        checks += [{"validator_id": v["validator"], "stage": "qualification", "status": v["status"], "details": v["details"]}
                   for v in row.get("validation", [])]
        limitations = ["source_semantics_not_verified", "backend_proofs_not_run", *row.get("unsupported", [])]
        if row["status"] == "partial": limitations.append("partial_native_projection")
        identity = row.get("projection_id", "rich-intent/" + family + "/v1")
        # Rich sequence state views reuse the native projection schema, but
        # their producer preserves ordering across two modal propositions.
        # Keep that training head distinct from the atomic extension producer.
        if producer.endswith(".rich_logic") and identity.startswith("intent-extended/"):
            identity = "rich-intent/" + identity.removeprefix("intent-extended/")
        add(family, identity, row["representation"], producer=producer, checks=checks,
            profile=row.get("profile_id"), limitations=limitations)

    if domain_id == "intent_ir":
        from ...intent_ir.formalize import rich_logic, rich_grammar, extended_projections
        from . import domain_targets
        pins.update(_pin(domain_targets))
        native = document
        if type(document) is dict and "kind" in document:
            if source_text is None or rich_grammar.parse_instruction(source_text) != rich_grammar.validate_ast(document):
                raise ValueError("rich Intent AST requires exact complete source agreement")
            rich = rich_logic.project_rich_intent_logic(document, instruction=source_text, context=context)
            pins.update(_rich_pins())
            pins.update(_pin(rich_grammar))
            for row in rich["projections"]: extension(row, rich_logic.__name__)
            gaps.extend(rich["frontiers"])
            # Unconditional native views must not erase guards or choices.
            native = rich["native_intent_ir"] if document["kind"] == "atom" else None
            context_for_extensions = None
        else:
            context_for_extensions = context
        if native is not None:
            from ...intent_ir.formalize.projection_contracts import validated_document
            native = validated_document(native)
            envelope(domain_targets.prepare_intent_targets(native))
            extensions = sorted(set(requested) & (set(extended_projections.DEFAULT_FAMILIES) | set(extended_projections.ADDITIONAL_REQUIREMENTS)))
            if extensions:
                result = extended_projections.project_intent_families(native, context=context_for_extensions, requested_families=extensions)
                pins.update(result["producer_pins"])
                for row in result["projections"]: extension(row, extended_projections.__name__)
            elif context_for_extensions:
                raise ValueError("Intent context requires a selected native extension")
    elif domain_id == "security_ir":
        from ...security_ir import code_logic_projection
        from . import domain_targets
        pins.update(_pin(code_logic_projection)); pins.update(_pin(domain_targets))
        kinds = [row for row in code_logic_projection.describe_code_logic_projection_profile()["projections"] if row["family"] in requested]
        # Per-kind envelopes keep a missing heap from invalidating a present
        # program target. Contract validation still requires supplied ProgramIR.
        for route in kinds:
            wire = envelope(domain_targets.prepare_security_targets(code_unit=code_unit, source_bytes=source_bytes,
                typed_inputs=typed_inputs, requested_kinds=[route["kind"]]))
            for problem in wire["unsupported"]:
                frontier.append({"family_id": route["family"], **problem})
    elif domain_id == "ui_ux_ir":
        from . import ui_targets
        from ...ui_ux_ir.formalize import compiler, roundtrip
        pins.update(_pin(ui_targets)); pins.update(_pin(compiler)); pins.update(_pin(roundtrip))
        if ui_training_row is not None:
            from . import ui_training_inputs
            from ...ui_ux_ir.source_adapters import dom_aria, mcp_idl, mcp_idl_identity
            for module in (ui_training_inputs, dom_aria, mcp_idl, mcp_idl_identity): pins.update(_pin(module))
            wire = envelope(ui_training_inputs.prepare_ui_training_row(ui_training_row).target)
        else:
            wire = envelope(ui_targets.prepare_ui_targets(document))
        if wire["unsupported"]: frontier.append({"family_id": None, "reason": "native_UI_input_invalid", "details": wire["unsupported"]})
    else:
        from ...legal_ir import canonical_contracts, typed_adapter
        from ...bridge import multiview, types as bridge_types
        from ....optimizers.logic_theorem_optimizer import modal_ir
        legal_ir_contract_telemetry = importlib.import_module("ipfs_datasets_py.logic.integration.reasoning.legal_ir_contract_telemetry")
        legal_ir_view_contracts = importlib.import_module("ipfs_datasets_py.logic.integration.reasoning.legal_ir_view_contracts")
        pins.update(_pin(canonical_contracts))
        if type(document) is canonical_contracts.CanonicalRoundTripIR:
            native = canonical_contracts.CanonicalRoundTripIR.from_dict(document.to_dict())
            if _wire(native.to_dict()) != _wire(document.to_dict()):
                raise ValueError("canonical LegalIR reconstruction changed source")
            add("deontic", "legal-ir/canonical-norms/v1", native.to_dict(), producer=canonical_contracts.__name__,
                checks=[{"validator_id": "CanonicalRoundTripIR.from_dict", "stage": "target", "status": "passed", "details": {"ir_cid": native.ir_cid}}],
                limitations=["typed_declaration_only_source_meaning_not_verified", "conditions_exceptions_temporal_fields_are_opaque_structural_values",
                    "TDFOL_DCEC_modal_and_frame_bridge_adapters_not_invoked", "family_syntax_and_backend_proofs_not_run"])
        elif type(document) is modal_ir.ModalIRDocument:
            if source_text is not None and source_text != document.normalized_text:
                raise ValueError("ModalIR exact source differs from normalized_text")
            if (type(document.formulas) is not list or len(document.formulas) > 1024
                    or any(type(f) is not modal_ir.ModalIRFormula for f in document.formulas)
                    or len({f.formula_id for f in document.formulas}) != len(document.formulas)):
                raise ValueError("bounded unique native ModalIR formulas required")
            for formula in document.formulas:
                provenance = formula.provenance
                if (type(provenance) is not modal_ir.ModalIRProvenance or provenance.source_id != document.document_id
                        or type(provenance.start_char) is not int or type(provenance.end_char) is not int
                        or not 0 <= provenance.start_char < provenance.end_char <= len(document.normalized_text)):
                    raise ValueError("ModalIR formula provenance differs from document")
            for module in (modal_ir, typed_adapter, legal_ir_contract_telemetry, legal_ir_view_contracts): pins.update(_pin(module))
            # Deliberately bypass extract_legal_ir_contract_payloads: metadata
            # overrides do not establish that a family projection ran.
            derived = legal_ir_contract_telemetry._derive_modal_ir_payloads(document)
            for alias, records in derived.items():
                route = typed_adapter.resolve_legal_route(alias)
                if not route.family_id:
                    continue
                checks = []
                for record in records:
                    checked = legal_ir_view_contracts.LEGAL_IR_VIEW_CONTRACTS.validate(alias, record)
                    checks.append({"validator_id": "LEGAL_IR_VIEW_CONTRACTS:" + alias, "stage": "target",
                        "status": "passed" if checked.valid else "failed", "details": checked.to_dict()})
                add(route.family_id, "legal-ir/modal-view/" + alias + "/v1", records,
                    producer=legal_ir_contract_telemetry.__name__, profile=route.profile_id or None, checks=checks,
                    limitations=["native_structural_view_not_parser_checked_family_AST", "opaque_qualifiers_not_fully_formalized",
                        "source_meaning_not_verified", "backend_proofs_not_run", "metadata_overrides_excluded"])
        elif type(document) is multiview.MultiViewLegalIRReport:
            merged = document.document
            if (type(merged) is not bridge_types.LegalIRDocument or type(merged.source_text) is not str
                    or not merged.source_text or len(merged.source_text.encode()) > 1048576
                    or (source_text is not None and source_text != merged.source_text)):
                raise ValueError("native multiview exact source document required")
            names = document.bridge_names
            if (type(names) not in (list, tuple) or not 1 <= len(names) <= 16
                    or any(type(name) is not str for name in names) or len(set(names)) != len(names)
                    or not isinstance(document.reports, Mapping) or not isinstance(document.failures, Mapping)
                    or set(document.reports) - set(names) or set(document.failures) - set(names)
                    or set(document.reports) & set(document.failures)):
                raise ValueError("bounded nonconflicting native multiview stages required")
            retained = {}
            for name, stage in document.reports.items():
                if (type(stage) is not bridge_types.BridgeEvaluationReport or stage.adapter_name != name
                        or type(stage.ir_document) is not bridge_types.LegalIRDocument
                        or stage.ir_document.source_text != merged.source_text
                        or not isinstance(stage.ir_document.views, Mapping)
                        or any(type(view) is not bridge_types.LogicIRView or view.name != key
                               for key, view in stage.ir_document.views.items())):
                    raise ValueError("native bridge stage identity/source/view binding differs")
                if stage.status in {"ok", "partial"}:
                    retained[name] = stage
                else:
                    frontier.append({"family_id": None, "reason": "failed_native_bridge_stage_not_training_evidence", "adapter": name, "status": stage.status})
            for module in (multiview, bridge_types, typed_adapter, legal_ir_contract_telemetry, legal_ir_view_contracts): pins.update(_pin(module))
            derived = legal_ir_contract_telemetry.legal_ir_contract_payloads_from_multiview_report(replace(document, reports=retained))
            for alias, records in derived.items():
                if alias not in {"deontic", "frame_logic", "tdfol", "cec"}:
                    continue  # Graph/prover/decompiler roles are not families.
                route = typed_adapter.resolve_legal_route(alias)
                checks = []
                for record in records:
                    checked = legal_ir_view_contracts.LEGAL_IR_VIEW_CONTRACTS.validate(alias, record)
                    checks.append({"validator_id": "LEGAL_IR_VIEW_CONTRACTS:" + alias, "stage": "target",
                        "status": "passed" if checked.valid else "failed", "details": checked.to_dict()})
                add(route.family_id, "legal-ir/bridge-view/" + alias + "/v1", records,
                    producer=legal_ir_contract_telemetry.__name__, profile=route.profile_id or None, checks=checks,
                    limitations=["supplied_native_bridge_artifact_not_independently_executed_here", "native_structural_contract_view",
                        "source_meaning_not_verified", "backend_proof_receipts_not_promoted", "metadata_overrides_excluded",
                        "CEC_lifecycle_view_uses_existing_bridge_projection_not_new_source_semantic_inference"])
            gaps.extend({"adapter": name, "reason": "native_bridge_failure", "details": failure}
                        for name, failure in document.failures.items())
        else:
            raise TypeError("Legal targets require native CanonicalRoundTripIR, ModalIRDocument or MultiViewLegalIRReport")

    targets.sort(key=lambda row: (row["logic_family"], row["projection_id"]))
    if len({row["projection_id"] for row in targets}) != len(targets):
        raise ValueError("duplicate native projection identity")
    inventory = catalog["family_inventory"]
    for row in inventory:
        family = row["family_id"]
        present = [target for target in targets if target["logic_family"] == family]
        row.update(requested=family in requested, target_count=len(present),
            ready_target_count=sum(target["ready_for_training"] for target in present))
        row["ready_for_training"] = bool(row["ready_target_count"])
        row["status"] = "not_requested" if family not in requested else "targets_available" if row["ready_for_training"] else "unsupported"
        if family in requested and not row["ready_for_training"]:
            frontier.append({"family_id": family, "reason": row["frontier"], "requires": row["requires"]})
    result = {"schema": SCHEMA, "domain_id": domain_id, "source_digest": source_digest, "source_sha256": source_hash,
        "typed_input_digest": _sha(binding), "requested_families": sorted(requested), "projections": targets,
        "family_inventory": inventory, "frontier": frontier, "qualification_gaps": gaps,
        "native_envelope_observations": views, "producer_pins": pins,
        "ready_for_training": any(row["ready_for_training"] for row in targets),
        "all_requested_families_available": all(row["ready_for_training"] for row in inventory if row["requested"]),
        "training_target_scope": "auxiliary_structural_IR_views_not_source_to_IR_supervision",
        "training_executed": False, "provider_calls": 0, "download_calls": 0, "external_backend_calls": 0, **AUTHORITY}
    result["report_sha256"] = _sha(result)
    return result


def validate_family_training_report(report, **source_inputs):
    """Check structure/pins, or additionally replay supplied original typed inputs.

    A digest is an integrity check, not proof that a caller's data are authentic.
    Without source_inputs this function grants only structural validation.
    """
    if type(report) is not dict or report.get("schema") != SCHEMA or report.get("domain_id") not in DOMAINS:
        raise ValueError("domain family training report required")
    if report.get("report_sha256") != _sha({key: value for key, value in report.items() if key != "report_sha256"}):
        raise ValueError("family training report digest differs")
    if any(report.get(key) is not False for key in AUTHORITY):
        raise ValueError("training projections cannot grant semantic authority")
    if (report.get("training_executed") is not False or any(report.get(key) != 0 for key in
            ("provider_calls", "download_calls", "external_backend_calls"))
            or type(report.get("source_digest")) is not str or not re.fullmatch(r"[0-9a-f]{64}", report["source_digest"])):
        raise ValueError("pure source-bound projection report required")
    pins = report.get("producer_pins")
    if type(pins) is not dict or __name__ not in pins:
        raise ValueError("current native producer pins required")
    for name, digest in pins.items():
        if type(name) is not str or not re.fullmatch(r"ipfs_datasets_py(?:\.[A-Za-z_][A-Za-z_0-9]*)+", name):
            raise ValueError("native producer module required")
        # Read source bytes without importing a caller-selected module.
        path = Path(__file__).resolve().parents[3].joinpath(*name.split(".")[1:])
        path = path.with_suffix(".py") if path.with_suffix(".py").is_file() else path / "__init__.py"
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("family training producer changed")
    rows = report.get("projections")
    if type(rows) is not list or len(rows) > 256:
        raise ValueError("bounded native projections required")
    known = set(_families())
    requested = report.get("requested_families")
    if type(requested) is not list or not requested or requested != sorted(set(requested)) or set(requested) - known:
        raise ValueError("canonical family selection required")
    if len({row["projection_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate native projection identity")
    for row in rows:
        if (row["logic_family"] not in requested or row["source_digest"] != report["source_digest"]
                or type(row["payload"]) not in (dict, list) or not row["payload"]
                or row["ready_for_training"] is not _ready(row["validation"])
                or any(row.get(key) is not False for key in AUTHORITY)
                or row["target_sha256"] != _sha({key: value for key, value in row.items() if key != "target_sha256"})):
            raise ValueError("native training target identity/readiness differs")
    inventory = report.get("family_inventory")
    if type(inventory) is not list or [row["family_id"] for row in inventory] != list(_families()):
        raise ValueError("complete canonical family inventory required")
    for item in inventory:
        present = [row for row in rows if row["logic_family"] == item["family_id"]]
        ready = sum(row["ready_for_training"] for row in present)
        if (item["target_count"] != len(present) or item["ready_target_count"] != ready
                or item["ready_for_training"] is not bool(ready) or item["requested"] is not (item["family_id"] in requested)):
            raise ValueError("family coverage counts differ from actual targets")
        expected_status = "not_requested" if item["family_id"] not in requested else "targets_available" if ready else "unsupported"
        if item["status"] != expected_status:
            raise ValueError("family coverage status differs from actual targets")
    if report["ready_for_training"] is not any(row["ready_for_training"] for row in rows):
        raise ValueError("report readiness differs from targets")
    if report["all_requested_families_available"] is not all(row["ready_for_training"] for row in inventory if row["requested"]):
        raise ValueError("requested family completeness differs from actual targets")
    if source_inputs:
        expected = prepare_family_training_targets(report["domain_id"], requested_families=requested, **source_inputs)
        if _wire(expected) != _wire(report):
            raise ValueError("family training report differs from typed source replay")
    return report


__all__ = ["SCHEMA", "DOMAINS", "family_training_catalog", "prepare_family_training_targets", "validate_family_training_report"]
