"""Diagnostic coverage frontiers for exact native targets and inert receipts.

This module never builds, infers, trains, issues a live validation handle, or
reopens a qualification gate. Receipt success is a recorded claim, including
when its internally consistent command says ``lake build``. The versioned v8
policy with the unchanged minimum floors remains responsible for authenticating actual execution and enforcing
the complete modality floor.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import family_training as core
from . import native_formula_evidence as formulas
from . import projection_validation_contract_v8 as policy

SCHEMA = "native-family-coverage-frontier/v2"
MAX_BYTES = 32 * 1024 * 1024
FALSE = {"qualified": False, "admitted": False, "formalized": False,
    "roundtrip_ok": False, "proof_authority": False, "execution_authority": False,
    "source_semantics_verified": False, "strict_training_allowed": False,
    "native_execution_authenticated": False, "lake_executed_by_diagnostic": False,
    "training_executed": False, "checkpoint_promoted": False}
_AUTHORITY = frozenset(FALSE) | {"proof_of_source_meaning", "promotion_performed",
    "source_meaning_verified", "proof_of_source_semantics"}
_PINS = {str(Path(module.__file__).resolve()): hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
         for module in (core, formulas, policy)}
_PINS[str(Path(__file__).resolve())] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _guard():
    from ...autoformal.tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    _require(all(Path(name).is_file() and hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected
                 for name, expected in _PINS.items()), "coverage diagnostic producer changed")


def _no_authority(value):
    # Check envelope claims, not unrelated literal fields inside source models.
    for key in _AUTHORITY & value.keys():
        _require(value[key] is False, "diagnostic input cannot claim authority: " + key)


def _receipt(report, value):
    if value is None:
        return {}, None
    _require(type(value) is dict and len(_raw(value)) <= MAX_BYTES, "bounded inert native receipt required")
    _no_authority(value)
    _require(type(value.get("schema")) is str and
        re.fullmatch(r"native-family-modality-lake/v[1-8]", value["schema"]), "known native receipt schema required")
    _require(value.get("report_sha256") == _sha(report) and
        value.get("source_digest") == report["source_digest"] and
        value.get("domain_id") == report["domain_id"], "native receipt report/source/domain binding differs")
    if "requested_families" in value:
        _require(value["requested_families"] == report["requested_families"], "native receipt family inventory differs")
    if "source_sha256" in value:
        _require(value["source_sha256"] == report.get("source_sha256"), "native receipt source hash differs")
    execution = value.get("execution")
    _require(execution is None or type(execution) is dict, "native execution receipt must be a mapping")
    command_claim = False
    if execution is not None:
        _no_authority(execution)
        command = execution.get("command")
        library = {"intent_ir": "IntentIR", "ui_ux_ir": "UIUXIR", "security_ir": "SecurityIR", "legal_ir": "LegalIR"}[report["domain_id"]]
        command_claim = (type(command) is list and len(command) == 3 and type(command[0]) is str
            and bool(command[0]) and command[1:] == ["build", library]
            and execution.get("status") == "passed" and execution.get("backend_executed") is True
            and type(execution.get("returncode")) is int and execution["returncode"] == 0
            and all(execution.get(key) is False for key in ("timed_out", "output_truncated", "workspace_limit_exceeded")))
    rows = value.get("per_projection")
    expected = {row["projection_id"]: row for row in report["projections"]}
    _require(type(rows) is list and len(rows) == len(expected), "complete native receipt projection inventory required")
    by_id = {}
    for row in rows:
        _require(type(row) is dict and type(row.get("projection_id")) is str
            and row["projection_id"] in expected and row["projection_id"] not in by_id,
            "unique exact native receipt projection IDs required")
        _no_authority(row)
        target = expected[row["projection_id"]]
        _require(row.get("logic_family") == target["logic_family"], "native receipt projection family differs")
        bindings = {"profile": target.get("profile"), "source_digest": report["source_digest"],
            "payload_sha256": _sha(target["payload"]), "target_sha256": target["target_sha256"]}
        for key, wanted in bindings.items():
            if key in row:
                _require(row[key] == wanted, "native receipt projection binding differs: " + key)
        _require(row.get("parser_status") in {"passed", "blocked", "failed", "not_run", None}
            and row.get("lake_status") in {"passed", "blocked", "failed", "not_run", "unavailable", None},
            "recognized native parser/Lake receipt status required")
        _require(row.get("lake_status") != "passed" or command_claim,
            "reported Lake success requires a consistent explicit build command record")
        _require("semantic_lowering_supported" not in row or type(row["semantic_lowering_supported"]) is bool,
            "native lowering support flag must be Boolean")
        lowering = row.get("lowering")
        _require(lowering is None or type(lowering) is dict, "native lowering receipt must be a mapping")
        if lowering is not None:
            _no_authority(lowering)
            _require("capability_floor_eligible" not in lowering or type(lowering["capability_floor_eligible"]) is bool,
                "native floor eligibility flag must be Boolean")
        by_id[row["projection_id"]] = row
    _require(set(by_id) == set(expected), "native receipt omitted projection rows")
    return by_id, {"schema": value["schema"], "sha256": _sha(value),
        "scope": "internally_bound_inert_receipt_claims_not_authenticated_execution",
        "recorded_status": value.get("status"), "projection_count": len(rows),
        "consistent_Lake_command_recorded": command_claim}


def _requirements(domain, family):
    specific = {
        ("intent_ir", "first_order"): [
            "An explicit asserted ASSUMPTION with a predicate and ordered arguments, or a separately supplied source-bound FOL declaration.",
            "A modal goal or unexecuted action cannot be converted into an observed fact by deleting its modality."],
        ("intent_ir", "intention_agency"): [
            "An explicit intended statement and a unique matching native action with the exact actor and ordered arguments.",
            "Permission, obligation, recommendation, belief and event occurrence do not establish intention."],
        ("intent_ir", "program"): [
            "A source-bound action/program with meaningful joined preconditions, postconditions or effects and a supported native interpretation.",
            "An empty or vacuous postcondition cannot satisfy the program capability floor; do not invent effects."],
        ("ui_ux_ir", "event_calculus"): [
            "An explicit source/candidate-bound behavior model, guard interpretation, clock unit/origin/resolution, initial fluent vector and complete signed event observations.",
            "An explicit effect timing and persistence policy with the finite observation/unknown boundary; component labels are not event evidence."],
        ("ui_ux_ir", "tdfol"): [
            "An explicit normative declaration with temporal scope, typed ordered arguments and any required time premises.",
            "Use the named TDFOL operator check for actual deontic plus temporal structure; a TDFOL parser accepting a pure norm is insufficient evidence of both."],
        ("ui_ux_ir", "dcec"): [
            "Explicit agent/cognitive, event and normative declarations with preserved operator scope and required time/role bindings.",
            "Privacy or presentation classifications do not imply knowledge, belief, intention, an occurrence or a duty."],
        ("ui_ux_ir", "temporal"): [
            "An explicit temporal property over a declared time/trace model with a supported operator interpretation.",
            "A UI component or declared transition alone does not supply a temporal obligation or observed execution."],
        ("ui_ux_ir", "transition_system"): [
            "A complete source-bound behavior model with explicit states, initial state, transitions, guards and parameter persistence.",
            "TLA+ needs its own supported profile and actual SANY plus Lake checks; no terminal/recovery defaults may be invented."],
    }
    return [core.REQUIREMENTS[family], *specific.get((domain, family), ()),
        "Native parser, faithful supported interpretation and actual live Lake evidence remain separate requirements."]


def _projection(target, row):
    reasons = []
    if target["ready_for_training"] is not True:
        reasons.append("native_target_not_ready")
    eligible = None
    if row is None:
        reasons.append("native_receipt_not_supplied")
        status = "native_evidence_not_supplied"
    else:
        lowering = row.get("lowering")
        eligible = lowering.get("capability_floor_eligible", True) if lowering else None
        if row.get("semantic_lowering_supported") is not True:
            reasons.append("semantic_lowering_unsupported_or_unreported")
        if row.get("parser_status") != "passed":
            reasons.append("native_parser_not_passed_or_unreported")
        if row.get("lake_status") != "passed":
            reasons.append("Lake_not_reported_passed")
        if eligible is not True:
            reasons.append("native_lowering_not_floor_eligible" if eligible is False else "native_floor_eligibility_unreported")
        status = ("semantic_lowering_missing" if row.get("semantic_lowering_supported") is not True else
            "native_parser_not_passed" if row.get("parser_status") != "passed" else
            "Lake_not_reported_passed" if row.get("lake_status") != "passed" else
            "recorded_native_success_unverified")
    if target["ready_for_training"] is not True:
        status = "native_target_not_ready"
    return {"projection_id": target["projection_id"], "logic_family": target["logic_family"],
        "profile": target.get("profile"), "target_sha256": target["target_sha256"],
        "payload_sha256": _sha(target["payload"]), "target_ready": target["ready_for_training"],
        "status": status, "blocking_reasons": reasons,
        "recorded_parser_status": row.get("parser_status") if row else None,
        "recorded_lake_status": row.get("lake_status") if row else None,
        "recorded_floor_eligible": eligible,
        "recorded_floor_reason": (row.get("lowering") or {}).get("capability_floor_reason") if row else None,
        "recorded_lowering_reason": row.get("reason") if row else None,
        "receipt_projection_binding_fields": sorted(k for k in
            ("profile", "source_digest", "payload_sha256", "target_sha256") if row is not None and k in row),
        "validation_required": "v8_live_native_validation_with_unchanged_floors_not_this_diagnostic"}


def _declared_ui_records(report, route):
    """Check actual operator trees in new UI declarations, without executing."""
    if report["domain_id"] != "ui_ux_ir":
        return []
    mappings = {
        "TFOL": ("ui_ux_ir/declared_state_logic/TFOL/v1", "explicit_ui_state_temporal/v1",
            "native-ui-state-temporal-logic/v1", "formulas", "tdfol_native"),
        "TDFOL": ("ui_ux_ir/declared_state_logic/TDFOL/v1", "explicit_ui_state_deontic_temporal/v1",
            "native-ui-state-temporal-logic/v1", "formulas", "tdfol_native"),
        "DCEC": ("ui_ux_ir/explicit_logic/bounded_dcec/v1", "explicit_ui_bounded_dcec/v1",
            "native-ui-bounded-dcec/v1", "native_dcec_formulas", "dcec_native"),
    }
    name = route["requirement_id"]
    if name not in mappings:
        return []
    identity, profile, schema, field, ast_format = mappings[name]
    rows = [row for row in report["projections"] if row["projection_id"] == identity]
    records = []
    for row in rows:
        _require(report["schema"] == "ui-declared-logic-family-targets/v1"
            and row["logic_family"] == route["family_id"] and row.get("profile") == profile,
            "exact declared UI named-fragment route required")
        payload = row["payload"]
        _require(type(payload) is dict and payload.get("schema") == schema,
            "exact declared UI named-fragment payload required")
        values = payload.get(field)
        _require(type(values) is list and 1 <= len(values) <= 32,
            "bounded nonempty declared UI native formulas required")
        seen = set()
        for value in values:
            _require(type(value) is dict and type(value.get("formula_id")) is str
                and value["formula_id"] and value["formula_id"] not in seen
                and value.get("ast_format") == ast_format,
                "unique exact declared UI native formula identity required")
            seen.add(value["formula_id"])
            parsed, printed, actual_format, counts, _ = (
                formulas._dcec(value["formula"], name) if name == "DCEC"
                else formulas._tdfol(value["formula"], name))
            _require(actual_format == ast_format and printed == value.get("printed")
                and _raw(parsed) == _raw(value.get("native_ast"))
                and _raw(counts) == _raw(value.get("operator_counts")),
                "declared UI formula AST/operators differ from native parser replay")
            records.append({"projection_id": identity, "profile": profile,
                "formula_id": value["formula_id"], "ast_format": ast_format,
                "native_ast_sha256": _sha(parsed), "recorded_operator_counts": deepcopy(counts),
                "required_operator_pattern_recorded": True, "native_formula_parse_replayed": True,
                "scope": "declared_UI_operator_composition_not_source_truth_or_context_authentication"})
    return records


def _named_fragments(report):
    results = []
    for route in formulas.named_logic_routes():
        name = route["requirement_id"]
        identity = report["domain_id"] + "/native_formula/" + name + "/v3"
        rows = [row for row in report["projections"] if row["projection_id"] == identity
            and row["logic_family"] == route["family_id"] and row.get("profile") == route["profile"]]
        records = []
        for row in rows:
            payload = row["payload"]
            _require(type(payload) is dict and payload.get("requirement_id") == name
                and type(payload.get("operator_counts")) is dict, "exact named formula operator record required")
            # Reparse the native declaration instead of trusting its counts or
            # an internally rehashed AST. This checks formula syntax/structure,
            # never its correspondence to the original natural-language source.
            ref = formulas.SourceRef.from_dict(payload["source_ref"])
            _require(ref.to_dict() == payload["source_ref"], "exact named formula source reference required")
            replay = formulas.prepare_native_formula_evidence(
                formulas.NativeFormulaEvidence(name, payload["formula"], ref), ref)
            _require(_raw(replay["payload"]) == _raw(payload), "named formula AST/operators differ from native parser replay")
            counts = payload["operator_counts"]
            _require(all(type(k) is str and type(v) is int and 0 <= v <= 16384 for k, v in counts.items()),
                "bounded named formula operator counts required")
            if name in {"FOL", "DFOL", "TFOL", "TDFOL"}:
                expected = {"FOL": (False, False), "DFOL": (True, False), "TFOL": (False, True), "TDFOL": (True, True)}[name]
                has_operators = (counts.get("predicate", 0) > 0 and
                    (counts.get("deontic", 0) > 0, counts.get("temporal", 0) > 0) == expected)
            elif name in {"CEC", "DCEC"}:
                has_operators = (counts.get("cognitive", 0) > 0 and counts.get("event", 0) > 0
                    and (counts.get("deontic", 0) > 0) == (name == "DCEC"))
            else:
                has_operators = counts.get("statement" if name == "frame_logic" else "propositional", 0) > 0
            records.append({"projection_id": identity, "ast_format": payload.get("ast_format"),
                "native_ast_sha256": _sha(payload.get("native_ast")), "recorded_operator_counts": deepcopy(counts),
                "required_operator_pattern_recorded": has_operators, "native_formula_parse_replayed": True})
        records.extend(_declared_ui_records(report, route))
        recorded_ids = {record["projection_id"] for record in records}
        results.append({**route, "status": "named_operator_record_available" if records else "named_fragment_not_supplied",
            "records": records, "other_same_family_projection_ids": [row["projection_id"] for row in report["projections"]
                if row["logic_family"] == route["family_id"] and row["projection_id"] not in recorded_ids],
            "scope": "native_formula_parser_replay_not_source_truth_or_Lake_or_full_family_semantics"})
    return results


def diagnose_family_coverage(report, *, native_receipt=None, applicability_review=()):
    """Explain exact catalog, floor and native-stage gaps without qualification.

The optional receipt is an inert dictionary, never a live handle. It must bind
the whole report and contain every projection exactly once. Older receipts may
lack per-row hashes; supplied hashes must match, and present binding fields are
reported. An omitted/duplicated row or unrelated report is rejected. No source
    meaning, execution authenticity, applicability or missing context is inferred.
    Named formula declarations are reparsed by their existing native owner;
    source-to-target semantic agreement is not re-established here.
"""
    _guard()
    _require(type(report) is dict and len(_raw(report)) <= MAX_BYTES, "bounded exact native target report required")
    _no_authority(report)
    before = _raw(report)
    report = json.loads(before)
    policy._validate_report(report)
    owned_policy = policy.domain_projection_policy(report["domain_id"])
    known = owned_policy["family_inventory"]
    _require(len(known) == len(set(known)) == 40, "unchanged canonical forty-family inventory required")
    targets = report["projections"]
    _require(type(targets) is list and len(targets) <= 256 and
        len({row["projection_id"] for row in targets}) == len(targets), "bounded unique target projection rows required")
    for target in targets:
        _no_authority(target)
    reviews = policy._reviews(applicability_review, report, set(known))
    native_rows, receipt_binding = _receipt(report, native_receipt)
    projections = [_projection(row, native_rows.get(row["projection_id"])) for row in targets]
    requested, emitted = set(report["requested_families"]), {row["logic_family"] for row in targets}
    inventory = []
    for family in known:
        rows = [row for row in projections if row["logic_family"] == family]
        review = reviews.get(family)
        inventory.append({"family_id": family, "requested": family in requested,
            "projection_ids": [row["projection_id"] for row in rows],
            "catalog_status": "projection_emitted" if rows else "no_projection_emitted",
            "applicability": "applicable_projection_emitted" if rows else review["disposition"] if review else "needs_evidence",
            "applicability_review": deepcopy(review),
            "review_conflicts_with_emitted_projection": bool(rows and review and review["disposition"] == "inapplicable"),
            "next_required_evidence": _requirements(report["domain_id"], family)})
    floors = []
    for requirement in owned_policy["minimum_batch_floor"]:
        rows = [row for row in projections if row["logic_family"] == requirement["family_id"]
            and (requirement["profile"] is None or row["profile"] == requirement["profile"])
            and (report["domain_id"] != "legal_ir" or row["projection_id"] ==
                report["domain_id"] + "/native_formula/" + requirement["requirement_id"] + "/v3")]
        eligible = [row for row in rows if row["recorded_floor_eligible"] is True]
        status = ("floor_requirement_absent" if not rows else "native_evidence_not_supplied" if not native_rows else
            "emitted_but_floor_ineligible" if all(row["recorded_floor_eligible"] is False for row in rows) else "recorded_native_success_unverified" if
            any(row["status"] == "recorded_native_success_unverified" for row in eligible) else "native_stage_incomplete")
        floors.append({**requirement, "status": status, "projection_ids": [row["projection_id"] for row in rows],
            "recorded_floor_eligible_projection_ids": [row["projection_id"] for row in eligible],
            "blocking_reasons": sorted({reason for row in rows for reason in row["blocking_reasons"]}),
            "next_required_evidence": _requirements(report["domain_id"], requirement["family_id"]),
            "inapplicability_review_cannot_waive_requirement": True})
    result = {"schema": SCHEMA, "domain_id": report["domain_id"], "report_schema": report["schema"],
        "native_report_sha256": _sha(report), "source_digest": report["source_digest"],
        "source_sha256": report.get("source_sha256"), "policy_id": owned_policy["policy_id"],
        "policy_sha256": owned_policy["policy_sha256"], "policy_source_sha256": owned_policy["policy_source_sha256"],
        "producer_pins": deepcopy(_PINS), "requested_families": report["requested_families"],
        "canonical_family_count": len(known), "full_request_scope": requested == set(known),
        "unrequested_catalog_families": sorted(set(known) - requested),
        "missing_catalog_families": sorted(set(known) - emitted),
        "unreviewed_applicability_families": sorted(set(known) - emitted - set(reviews)),
        "family_inventory": inventory, "floor_requirement_diagnostics": floors,
        "projection_diagnostics": projections, "named_fragment_evidence": _named_fragments(report),
        "native_receipt_binding": receipt_binding,
        "applicability_review_sha256": _sha(list(applicability_review)),
        "payload_scope": "source-bound_typed_declarations_and_supported_interpretations_not_asserted_world_facts",
        "runtime_proof_scope": "no_execution_or_proof_authentication; use_v8_live_validation_with_unchanged_floors",
        "missing_context_inferred": False, "inapplicability_inferred": False, **FALSE}
    _guard()
    _require(_raw(report) == before, "diagnostic report mutated")
    result["diagnostic_sha256"] = _sha(result)
    return result


__all__ = ["SCHEMA", "diagnose_family_coverage"]
