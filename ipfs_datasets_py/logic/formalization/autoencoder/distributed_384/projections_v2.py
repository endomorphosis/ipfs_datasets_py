"""Candidate-bound access to the shared v7 native family projectors.

Caller declarations supplement a decoded candidate; they do not become model
predictions or attest facts about source behavior. Legacy, already-published
training plans retain their old numerical and projection contracts.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path
import weakref

from . import contracts as c, profiles
from .projection_context_contract import validate_context
from .supplemental_context import split_context
from .. import family_training_v3 as catalog_owner, family_training_v7 as native
from . import candidate_native_lake as lake

SCHEMA = "distributed-384-candidate-projections/v2"
FALSE = {**c.FALSE, "execution_authority": False, "complete_target_semantics": False,
         "context_inferred_by_model": False, "target_rewritten": False}


def family_catalog(domain):
    """Expose existing native adapters, including source-bound formula routes."""
    result = catalog_owner.family_training_catalog_v3(domain)
    # Availability is a capability, not applicability of an absent declaration.
    result["default_required_families"] = sorted({row["family_id"] for row in result["family_inventory"]
        if row["projection_adapter_available"]} | set(profiles.get_profile(domain)["native_family_ids"]))
    return result


def _families(domain, requested):
    catalog = family_catalog(domain)
    selected = catalog["default_required_families"] if requested is None else requested
    known = {row["family_id"] for row in catalog["family_inventory"]}
    c.require(type(selected) in (list, tuple) and selected and all(type(f) is str and f in known for f in selected)
              and len(set(selected)) == len(selected), "unique nonempty canonical family selection required")
    return sorted(selected)


def _empty_projection(row):
    # Count actual declarations, not a vacuous compile of an empty namespace.
    payload = row.get("payload", {})
    if payload == [] or payload == {}:
        return True
    if type(payload) is dict:
        for key in ("facts", "formulas", "clauses", "rules"):
            if key in payload and payload[key] == []:
                return True
        if "payload" in payload and ("format" in payload or "representation" in payload):
            return _empty_projection({"payload": payload["payload"]})
    return False


_REGISTRY = weakref.WeakKeyDictionary()


@dataclass(frozen=True, eq=False)
class PreparedCandidateProjection:
    """Issued preparation; callers receive detached copies, never writable state."""
    def _part(self, name):
        c.require(self in _REGISTRY, "live issued candidate preparation required")
        return deepcopy(_REGISTRY[self][name])

    @property
    def report(self):
        return self._part("report")

    @property
    def native_report(self):
        return self._part("native_report")

    @property
    def candidate(self):
        return self._part("source_seed")["target"]

    @property
    def source_text(self):
        return self._part("source_seed")["source_text"]

    @property
    def source_inputs(self):
        if not self._part("has_source_inputs"):
            return None
        seed = self._part("source_seed")
        return _inputs(**seed)

    @property
    def supplemental_interpretations(self):
        seed = self._part("source_seed")
        return split_context(seed["domain"], seed["target"], seed["source_text"], seed["context"])[1]


def _inputs(domain, target, source_text, context):
    if domain in {"intent_ir", "security_ir"}:
        from .projection_inputs import prepare_source_inputs
    else:
        from .legal_ui_inputs import prepare_source_inputs
    native_context, _ = split_context(domain, target, source_text, context)
    return prepare_source_inputs(domain, target, source_text, context=native_context)


def _native_request(domain, selected, source_inputs):
    """Retain dependencies of the native Intent semantic replacement pass."""
    resolved = set(selected)
    if domain == "intent_ir" and resolved.intersection({"first_order", "datalog", "horn_chc"}):
        from .. import intent_semantic_training_views as semantic
        document = source_inputs["document"]
        if not (type(document) is dict and document.get("kind") not in (None, "atom")):
            view = semantic.semantic_document(semantic._source_document(source_inputs))
            # The facts route initiates complete statement accounting even
            # when a rule-family view alone was requested. Statements retain
            # their actual force instead of being relabeled as world facts.
            resolved.add("first_order")
            resolved.update(row["logic_family"] for row in view["semantic_records"])
            if view["action_accounting"]:
                resolved.add("program")
            if view["blocked"]:
                resolved.add("modal")
    if domain == "intent_ir" and source_inputs.get("guarded_effect_bindings") is not None:
        resolved.update(("program", "temporal", "transition_system"))
    elif domain == "intent_ir" and "temporal" in resolved:
        # Native workflow temporal statements need their exact state view.
        # Retain any incomplete state abstraction as an explicit blocker.
        from .. import intent_semantic_training_views as semantic
        document = source_inputs["document"]
        if not (type(document) is dict and document.get("kind") not in (None, "atom")):
            if semantic._document(semantic._source_document(source_inputs))[0].actions:
                resolved.add("transition_system")
    return sorted(resolved)


def prepare_candidate_projection(domain, target, source_text, *, context=None, required_families=None):
    selected = _families(domain, required_families)
    if context is not None:
        validate_context(context, domain, target, source_text)
    _, interpretations = split_context(domain, target, source_text, context)
    legacy = profiles.project_candidate(domain, target, source_text, required_families=selected)
    report = dict(schema=SCHEMA, domain_id=domain, candidate_valid=legacy["candidate_valid"],
        candidate_sha256=legacy["candidate_sha256"], source_sha256=legacy["source_sha256"],
        context_sha256=context["context_sha256"] if context is not None else None,
        requested_families=selected, families=deepcopy(legacy["families"]),
        legacy_report_sha256=legacy["report_sha256"],
        evidence_scope="unchanged_decoded_candidate_plus_explicit_caller_declarations",
        declaration_scope="source_binding_is_identity_not_source_semantic_fidelity",
        qualification_scope="native_typed_projection_and_supported_Lean_lowering",
        native_check_scope="syntax_and_types_only", auxiliary_family_coverage=[],
        supplemental_interpretations=deepcopy(interpretations),
        supplemental_interpretation_count=len(interpretations),
        supplemental_interpretations_inferred=False,
        auxiliary_families=[], native_requested_families=selected,
        lake_build_executed=False, all_requested_native_checks_passed=False,
        native_report_sha256=None, native_preparation=None, **FALSE)
    native_report = source_inputs = None
    if legacy["candidate_valid"]:
        # A scalar source expression does not establish CVE polarity, trace,
        # heap, protocol or policy context. CodeUnit metadata must be supplied.
        if domain == "security_ir" and context is None:
            report["context_frontier"] = "explicit_CodeUnit_and_matching_native_models_required"
        else:
            try:
                source_inputs = _inputs(domain, target, source_text, context)
            except ValueError as error:
                if context is not None:
                    raise
                report["context_frontier"] = str(error)[:2000]
            if source_inputs is not None:
                native_requested = _native_request(domain, selected, source_inputs)
                report["native_requested_families"] = native_requested
                report["auxiliary_families"] = sorted(set(native_requested) - set(selected))
                report["auxiliary_family_coverage"] = [dict(family_id=family,
                    status="missing_context", reason="dependency_requires_native_projection", projections=[])
                    for family in report["auxiliary_families"]]
                native_report = native.prepare_family_training_targets_v7(domain,
                    requested_families=native_requested, **source_inputs)
                preparation = lake.prepare_native_family_lean(native_report, source_inputs=source_inputs,
                    source_text=source_text, candidate=target, interpretations=interpretations)
                report["native_report_sha256"] = native_report["report_sha256"]
                # The full native report is retained for exact replay; the redundant
                # large Lean text is an artifact of preparation, not model output.
                report["native_preparation"] = {k: deepcopy(v) for k, v in preparation.items() if k != "lean_source"}
                lowerings = {row["projection_id"]: row for row in preparation["per_projection"]}
                for family in report["families"] + report["auxiliary_family_coverage"]:
                    values = [row for row in native_report["projections"] if row["logic_family"] == family["family_id"]]
                    if not values:
                        family.update(status="missing_context", reason="no_active_native_projection",
                            legacy_observation=deepcopy(family.get("projections", [])),
                            projections=[], native_lowering=[], coverage_scope="declared_native_views_only",
                            complete_target_semantics=False)
                        continue
                    checks = []
                    for value in values:
                        gaps = value.get("qualification_gaps", [])
                        lowered = lowerings[value["projection_id"]]
                        checks.append(bool(value["ready_for_training"] and
                            "partial_native_projection" not in gaps and not _empty_projection(value)
                            and lowered["semantic_lowering_supported"]))
                    # Every emitted view counts. An easier formula cannot hide a
                    # blocked richer projection belonging to the same family.
                    supported = bool(checks) and all(checks)
                    family.update(status="supported" if supported else "missing_context",
                        reason="all_emitted_native_views_lowered" if supported else "incomplete_native_view_or_interpretation",
                        projections=deepcopy(values), native_lowering=[deepcopy(lowerings[v["projection_id"]]) for v in values],
                        coverage_scope="declared_native_views_only", complete_target_semantics=False)
                report["producer_pins"] = deepcopy(native_report["producer_pins"])
                report["context_declaration_count"] = sum(len(native_report.get(key, [])) for key in
                    ("supplemental_inputs", "formula_inputs", "legal_qualifier_inputs", "ui_confirmation_inputs"))
    report["all_required_families_supported"] = all(r["status"] == "supported" for r in report["families"])
    report["all_auxiliary_families_supported"] = all(r["status"] == "supported"
        for r in report["auxiliary_family_coverage"])
    report["all_requested_dependencies_supported"] = (report["all_required_families_supported"]
        and report["all_auxiliary_families_supported"])
    report["native_report"] = deepcopy(native_report)
    report["bridge_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["report_sha256"] = c.digest(report)
    handle = PreparedCandidateProjection()
    seed = dict(domain=domain, target=deepcopy(target), source_text=source_text, context=deepcopy(context))
    _REGISTRY[handle] = dict(report=deepcopy(report), native_report=deepcopy(native_report),
                             source_seed=seed, has_source_inputs=source_inputs is not None)
    return handle


def project_candidate_v2(domain, target, source_text, *, context=None, required_families=None):
    return prepare_candidate_projection(domain, target, source_text,
        context=context, required_families=required_families).report


def check_candidate_projection(prepared, *, lake_executable, output_directory,
                               java_executable=None, tla2tools_jar=None, timeout_seconds=60):
    """Run and verify an actual native owner handle; saved receipts are history."""
    c.require(type(prepared) is PreparedCandidateProjection and prepared.native_report is not None
              and prepared.source_inputs is not None, "prepared native candidate with required context needed")
    before = c.digest(prepared.report)
    execution = lake.build_native_family_lake(prepared.native_report, source_inputs=prepared.source_inputs,
        source_text=prepared.source_text, candidate=prepared.candidate,
        interpretations=prepared.supplemental_interpretations,
        lake_executable=lake_executable, output_directory=output_directory,
        java_executable=java_executable, tla2tools_jar=tla2tools_jar, timeout_seconds=timeout_seconds)
    observation = lake.verify_native_family_lake(execution, prepared.native_report,
        source_inputs=prepared.source_inputs, source_text=prepared.source_text, candidate=prepared.candidate,
        interpretations=prepared.supplemental_interpretations)
    c.require(c.digest(prepared.report) == before, "candidate report changed during native check")
    report = deepcopy(prepared.report)
    report.pop("report_sha256")
    report.update(lake_build_executed=observation["backend_executed"],
        all_requested_native_checks_passed=observation["all_requested_projections_passed"],
        native_execution={k: v for k, v in observation.items() if k != "lean_source"},
        live_issued_handle_verified=True, saved_receipt_is_live_authority=False)
    by_family = {}
    for row in observation["per_projection"]:
        by_family.setdefault(row["logic_family"], []).append(row)
    for family in report["families"] + report["auxiliary_family_coverage"]:
        checks = by_family.get(family["family_id"], [])
        family["native_checks_passed"] = bool(checks) and all(row["parser_status"] == "passed"
            and row["lake_status"] == "passed" and row["semantic_lowering_supported"] for row in checks)
    report["report_sha256"] = c.digest(report)
    return report


__all__ = ["family_catalog", "prepare_candidate_projection", "project_candidate_v2", "check_candidate_projection"]
