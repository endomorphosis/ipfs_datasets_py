"""Versioned output requirements, not qualification evidence or execution.

Every domain needs the same minimum schema capabilities, with additional typed
software routes for code. A capability requirement never asserts that every
source span has an equivalent projection into every family. Feature training
may continue with explicit qualification gaps; it cannot confer admission.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ...logic.families import models, namespaces, profiles, registry
from ...logic.families import profile_catalog_v3
from ...logic.software_verification import syntax_bridge

SCHEMA = "autoencoder-logic-requirements/v1"
DOMAINS = ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir", "codebase_ir")
MAX_BYTES = 128 * 1024
FALSE = {"qualified": False, "admitted": False, "formalized": False,
         "proof_authority": False, "semantic_correctness_verified": False,
         "validation_executed": False, "lake_executed": False,
         "training_executed": False, "promotion_performed": False}

# Labels express the user's capability floor; canonical family/profile roles
# come from the registries below, without promoting aliases to family IDs.
_FLOOR = (
    ("first_order_logic", ("first_order",), None),
    ("temporal_deontic_first_order_logic", ("tdfol",), "tdfol_composition_v1"),
    ("deontic_first_order_logic", ("deontic", "first_order"), None),
    ("temporal_first_order_logic", ("temporal", "first_order"), "pure_temporal_fol_v1"),
    ("cognitive_event_calculus", ("event_calculus", "modal"), None),
    ("deontic_cognitive_event_calculus", ("dcec",), "dcec_composition_v1"),
    ("frame_logic", ("frame_logic",), None),
    ("propositional_logic", ("propositional",), None),
)


class LogicRequirementError(ValueError):
    """Unknown domain, invalid policy option or inconsistent local catalog."""


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _family(identifier):
    try:
        value = registry.DEFAULT_REGISTRY.families[identifier].to_dict()
    except KeyError as exc:
        raise LogicRequirementError("unregistered canonical family: " + identifier) from exc
    return {"family_id": identifier, "descriptor_sha256": _sha(value)}


def _source_identity():
    # Bind exactly these catalog sources, not an unverified transitive tree.
    modules = (models, namespaces, profiles, registry, profile_catalog_v3, syntax_bridge)
    package = Path(registry.__file__).resolve().parents[2]
    expected = next((parent / "ipfs_datasets_py" for parent in Path(__file__).resolve().parents
                     if (parent / "ipfs_datasets_py/logic/autoformal/tree_pin.py").is_file()), None)
    if expected is None or package != expected.resolve():
        raise LogicRequirementError("catalog source resolved outside canonical workspace tree")
    files = {}
    for module in modules:
        path = Path(module.__file__).resolve()
        if package not in path.parents or not path.is_file():
            raise LogicRequirementError("catalog source resolved outside canonical workspace tree")
        files[str(path.relative_to(package))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"scope": "listed_catalog_sources_only_not_transitive_provenance",
            "files": files, "sha256": _sha(files)}


def _floor_requirements():
    result = []
    for identifier, family_ids, composition_id in _FLOOR:
        composition = profiles.default_composition_map().get(composition_id) if composition_id else None
        if composition_id and (composition is None or composition.composition_id != composition_id):
            raise LogicRequirementError("registered composition is missing: " + composition_id)
        row = {"requirement_id": identifier, "required": True,
               "scope": "schema_capability_not_universal_per_span_translation",
               "canonical_families": [_family(name) for name in family_ids],
               "composition": None if composition is None else composition.to_dict(),
               "binding_gaps": [],
               "validation_required": ["typed_output_schema", "strict_family_syntax",
                    "operator_and_argument_coverage", "explicit_projection_losses",
                    "source_binding", "decoded_semantic_evaluation"]}
        if identifier == "cognitive_event_calculus":
            row["binding_gaps"] = ["standalone_cognitive_event_calculus_composition_not_registered"]
            row["coverage_requirement"] = "cognitive_and_event_operators_require_explicit_semantics_not_dcec_alias"
        elif identifier == "deontic_first_order_logic":
            row["binding_gaps"] = ["standalone_deontic_first_order_composition_not_registered"]
            row["coverage_requirement"] = "deontic_and_first_order_semantics_must_be_bound_together"
        result.append(row)
    return result


def _software_routes():
    result = []
    for key, route in sorted(syntax_bridge.default_ir_routes().items(), key=lambda pair: pair[0].value):
        wire = route.to_dict()
        if key != route.kind or wire["family_id"] not in registry.DEFAULT_REGISTRY.families:
            raise LogicRequirementError("software route differs from its registered kind/family")
        result.append({"requirement_id": "software_verification." + key.value,
            "required": True, "route": wire, "route_sha256": _sha(wire),
            "canonical_family": _family(route.family_id),
            "profile_namespace": "software_verification_native_profile",
            "validation_required": ["typed_owner_roundtrip", "strict_family_syntax",
                "operator_and_argument_coverage", "explicit_projection_losses", "source_binding"]})
    return result


def describe_logic_requirements(domain, *, contains_code=False):
    """Declare a floor for a domain; do not accept evidence or award success.

    ``contains_code`` requests the code extension in this description. False
    never waives it: execution must derive applicability from the trusted typed
    source/output adapter, including executable UI/IDL contracts. Security
    and CodebaseIR always require the code extension. This function runs no backend.
    """
    if type(domain) is not str or domain not in DOMAINS:
        raise LogicRequirementError("unknown autoencoder domain")
    if type(contains_code) is not bool:
        raise LogicRequirementError("contains_code must be boolean")
    from ...logic.autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    code = domain in ("security_ir", "codebase_ir") or contains_code
    source_before = _source_identity()
    floor = _floor_requirements()
    routes = _software_routes()
    tla = namespaces.BASELINE_NAMESPACES.get(namespaces.NamespaceKind.PROFILE, "tla_plus").to_dict()
    result = {"schema": SCHEMA, "domain": domain, "declaration_only": True,
        "scope": "output_schema_capability_floor",
        "contains_code": code,
        "code_requirement_trigger": {
            "security_ir_always_required": True,
            "codebase_ir_always_required": True,
            "otherwise": "trusted_typed_source_or_output_contains_code_state_transition_or_executable_idl_contract",
            "false_is_not_a_waiver": True,
            "applicability_owner": "trusted_domain_adapter_not_dataset_or_caller_pass_flags",
            "conditional_route_ids": [row["requirement_id"] for row in routes]},
        "logic_floor": floor,
        "software_routes": routes if code else [],
        "lake_schema_requirement": {
            "required": True, "command_template": ["lake", "build", "<Lib>"],
            "scope": "exact_emitted_output_schema_and_typed_instance",
            "lean_major_version": 4, "mathlib_allowed": False,
            "downloads_allowed": False, "sorry_admit_axiom_allowed": False,
            "receipt_binding_required": ["domain", "schema_version", "schema_sha256",
                "decoded_output_sha256", "source_sha256", "emitter_sha256",
                "lean_source_sha256", "lake_project_sha256", "library_target",
                "installed_toolchain_identity", "command", "returncode", "complete_build_log_sha256"],
            "receipt_authority": "locally_verified_actual_source_bound_lake_build_only",
            "fingerprint_only_theorem_satisfies_requirement": False,
            "successful_schema_build_proves_source_meaning": False},
        "code_state_requirement": {
            "required": code, "conditionally_required": not code,
            "profile": tla, "profile_sha256": _sha(tla),
            "canonical_families": [_family("transition_system"), _family("temporal")],
            "validation_required": ["typed_state_schema", "typed_transition_system",
                "tla_plus_strict_syntax", "explicit_initial_state_and_next_relation",
                "invariant_and_liveness_obligations", "declared_fairness_and_model_bounds",
                "backend_specific_model_check_receipt_when_model_check_claimed"],
            "bounded_model_check_is_unbounded_proof": False},
        "training_loss_requirements": {
            "required_for_decoder_aware_training": ["source_conditioned_output_reconstruction",
                "operator_and_polarity", "arguments_and_quantifier_scope", "conditions_and_exceptions",
                "temporal_scope_and_quantity", "structural_presence_and_references",
                "per_required_family_output_coverage", "explicit_unsupported_and_projection_loss"],
            "gradient_evidence_required": "nonzero_updates_to_the_relevant_learned_decoder_parameters",
            "selection_checks_required": ["free_running_decoded_output", "disjoint_tuning_evaluation",
                "strict_family_syntax", "source_semantic_fidelity", "source_bound_lake_schema_build"],
            "heldout_canary_required_for_generalization_claim": True,
            "heldout_canary_used_for_fit_or_selection": False,
            "lake_and_family_verifiers_are_differentiable_losses": False,
            "embedding_cosine_alone_satisfies_requirement": False},
        "qualification_gaps": [
            "declaration_does_not_execute_independent_evidence_checker",
            "complete_domain_schema_lake_emitter_and_receipt_not_established_by_this_interface",
            "per_family_decoder_training_and_semantic_coverage_must_be_verified",
            *sorted({gap for row in floor for gap in row["binding_gaps"]})],
        "feature_pretraining_policy": "may_continue_with_explicit_gaps_without_qualification_or_promotion",
        "constitution_policy": "never_mark_roundtrip_ok_or_formalized",
        "catalog_binding": {"family_registry_version": registry.REGISTRY_VERSION,
            "family_registry_sha256": _sha(registry.DEFAULT_REGISTRY.to_dict()),
            "profile_catalog_sha256": _sha(profile_catalog_v3.DEFAULT_PROFILE_CATALOG_V3.to_dict()),
            "software_routes_sha256": _sha([row["route"] for row in routes]),
            "source_identity": source_before}, **FALSE}
    if _source_identity() != source_before:
        raise LogicRequirementError("catalog sources changed while declaring requirements")
    if len(_bytes(result)) > MAX_BYTES:
        raise LogicRequirementError("requirements exceed bounded declaration size")
    result["requirements_sha256"] = _sha(result)
    return result


__all__ = ["SCHEMA", "DOMAINS", "LogicRequirementError", "describe_logic_requirements"]
