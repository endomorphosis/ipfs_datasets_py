"""Explicit mixed-sort reviewed norm admission with a separate V3 signing domain.

Reuses the unchanged V2 source, trust and dependency owners with strict Object
and mixed relational validators. Existing preparations and signed V2 receipts
retain their original producer identities and signing domain.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import legal_norm_content_adjudication_v1 as legacy

norm = legacy.norm
_need, _keys, _sha = legacy._need, legacy._keys, legacy._sha
_auth = legacy._auth
_reviewed_refs = legacy._reviewed_refs
_distinct_pair = legacy._distinct_pair
_reviewed_owners = legacy._reviewed_owners
norm_content_adjudication_sha256 = legacy.norm_content_adjudication_sha256

REVIEWED_PROFILE = "complete-reviewed-mixed-sort-norm-admission/v3"
REVIEWED_DECLARATION_SCHEMA = "legal-reviewed-mixed-sort-norm-declaration/v3"
REVIEWED_SUBJECT_SCHEMA = "legal-reviewed-mixed-sort-norm-subject/v3"
REVIEWED_CLAIM_SCHEMA = "legal-reviewed-mixed-sort-norm-signed-claim/v3"
REVIEWED_ACTION = "admit_complete_reviewed_mixed_sort_norm_meaning/v3"
REVIEWED_AUDIENCE = "legal-autoformalization-reviewed-mixed-sort-norm/v3"
REVIEWED_SLOTS = legacy.REVIEWED_SLOTS
REVIEWED_USES = legacy.REVIEWED_USES
_SELF_PATH = Path(__file__).resolve()
_SELF_PIN = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()


def _reviewed_pins():
    pins = legacy._reviewed_pins()
    relational = _reviewed_owners()[2]
    for path, digest in relational._mixed_owners()[-1].items():
        _need(path not in pins or pins[path] == digest,
              "reviewed relational producer pins disagree")
        pins[path] = digest
    _need(hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest() == _SELF_PIN,
          "mixed reviewed admission producer changed since import")
    pins[str(_SELF_PATH)] = _SELF_PIN
    return pins


def _validate_relational(relational, profile, inputs, request_sha256):
    if profile == relational.PROFILE:
        validator = relational.validate_relational_norm_v1
    elif profile == relational.MIXED_PROFILE:
        validator = relational.validate_mixed_relational_norm_v1
    else:
        raise ValueError("explicit Object or mixed relational profile required")
    return validator(inputs["report"], inputs["request_raw"],
                     expected_request_sha256=request_sha256,
                     expected_report_sha256=inputs["expected_report_sha256"])


def _predicate_domain(ir, symbol):
    signature = ir["typed_expression"]["signature"]
    return next(row["domain"] for row in signature["symbols"]
                if row["kind"] == "predicate" and row["name"] == symbol)


# Keep this replay guard local: the V2 function closes over its V2 pin set.
def _reviewed_finish(original, detached, commitment, pins, report):
    raw = norm._wire(report)
    _need(len(raw) <= _auth().MAX_BYTES, "complete reviewed admission report byte bound exceeded")
    _need(norm._snapshot(original)[1] == commitment and norm._snapshot(detached)[1] == commitment,
          "reviewed admission inputs changed during operation")
    _need(_reviewed_pins() == pins, "reviewed admission producers changed during operation")
    return json.loads(raw)


# The V3 signing domain must not resolve through the unchanged V2 globals.
def _reviewed_subject(subject, manifest):
    auth = _auth()
    _keys(subject, {"schema", "graph_id", "graph_sha256", "ast_sha256", "scope_id",
        "context_slot_ids", "dependency_manifest_sha256", "required_dependency_ids",
        "declaration_sha256", "source_binding_sha256", "context_packet_sha256"}, "reviewed norm subject")
    _need(subject["schema"] == REVIEWED_SUBJECT_SCHEMA and subject["context_slot_ids"] == list(REVIEWED_SLOTS),
          "fixed complete reviewed norm signing subject required")
    for key, value in subject.items():
        if key.endswith("_sha256"):
            _sha(value, key)
    auth._id(subject["graph_id"], "reviewed component identity")
    auth._text(subject["scope_id"], "reviewed jurisdiction")
    reachable, _ = auth._closure(manifest, subject["graph_id"], subject["graph_sha256"])
    _need(subject["graph_sha256"] == subject["declaration_sha256"]
          and subject["required_dependency_ids"] == reachable, "complete reviewed dependency closure differs")


def _reviewed_units(body, source_inputs, relational_inputs):
    source, _, relational, _ = _reviewed_owners()
    units = body["units"]
    _need(type(units) is list and 3 <= len(units) <= 16, "bounded definition and distinct-use component required")
    ids = [row.get("unit_id") for row in units if type(row) is dict]
    _need(len(ids) == len(units) and all(type(key) is str for key in ids) and len(set(ids)) == len(ids),
          "unique complete source unit identities required")
    _need(type(source_inputs) is dict and type(relational_inputs) is dict
          and set(source_inputs) == set(relational_inputs) == set(ids), "complete original source and IR inputs required")
    results, expected_artifacts = [], {}
    source_uses = legacy._ReviewedSourceUseTracker()
    for unit in units:
        _keys(unit, {"unit_id", "kind", "source_version", "occurrence", "document_revision",
            "parent_unit_ids", "relational_profile", "relational_request_sha256", "source_artifact_id",
            "ir_artifact_id", "coverage"},
            "complete reviewed source unit")
        identity = unit["unit_id"]
        _auth()._id(identity, "reviewed unit")
        _need(unit["kind"] in ("norm", "definition"), "supported complete unit kind required")
        _auth()._text(unit["document_revision"], "exact document revision")
        parents = unit["parent_unit_ids"]
        _need(type(parents) is list and len(parents) == len(set(parents)) and all(
            type(key) is str and key in ids and key != identity for key in parents), "explicit distinct parent unit references required")
        inputs = source_inputs[identity]
        _keys(inputs, {"raw_bytes", "extracted_text"}, "complete original source bytes and view")
        version = unit["source_version"]
        raw_sha, view_sha = version["raw_artifact"]["sha256"], version["extracted_view"]["sha256"]
        _need(type(inputs["raw_bytes"]) is bytes, "original raw source bytes required")
        source.validate_source_version(version, expected_raw_sha256=raw_sha, raw_bytes=inputs["raw_bytes"],
            extracted_text=inputs["extracted_text"], expected_extracted_sha256=view_sha)
        occurrence = source.validate_source_occurrence(unit["occurrence"], source_version=version,
            expected_raw_sha256=raw_sha, extracted_text=inputs["extracted_text"], expected_extracted_sha256=view_sha)
        source_uses.add(unit, version, occurrence)
        if body["provenance_kind"] == "statutory":
            _need(not any(str(version[key]).startswith("fixture:") for key in ("source_id", "release_id", "provision_id")),
                  "fictional source identities cannot be promoted to statutory evidence")
        ir_inputs = relational_inputs[identity]
        _keys(ir_inputs, {"request_raw", "report", "expected_report_sha256"}, "complete relational replay inputs")
        report = _validate_relational(relational, unit["relational_profile"], ir_inputs,
                                      unit["relational_request_sha256"])
        coverage = unit["coverage"]
        paths = [row["typed_path"] for row in report["structural_mapping"]]
        _need(type(coverage) is list and len(coverage) == len(paths), "complete typed-node source correspondence required")
        intervals = []
        for row, path in zip(coverage, paths, strict=True):
            _keys(row, {"typed_path", "start_char", "end_char", "start_utf8", "end_utf8"}, "typed-node correspondence")
            _need(row["typed_path"] == path, "complete ordered typed-node population differs")
            _need(all(type(row[key]) is int for key in ("start_char", "end_char", "start_utf8", "end_utf8")),
                  "exact integer source coordinates required")
            _need(occurrence["start_char"] <= row["start_char"] < row["end_char"] <= occurrence["end_char"],
                  "typed-node correspondence leaves the reviewed occurrence")
            source.build_source_occurrence(version, expected_raw_sha256=raw_sha,
                extracted_text=inputs["extracted_text"], expected_extracted_sha256=view_sha,
                **{key: row[key] for key in ("start_char", "end_char", "start_utf8", "end_utf8")})
            intervals.append((row["start_char"], row["end_char"]))
        frontier = occurrence["start_char"]
        for start, end in sorted(intervals):
            _need(start <= frontier, "reviewed source coverage has a gap")
            frontier = max(frontier, end)
        _need(frontier == occurrence["end_char"], "reviewed source coverage is incomplete")
        for field, pin in (("source_artifact_id", norm_content_adjudication_sha256(version)),
                           ("ir_artifact_id", unit["relational_request_sha256"])):
            artifact = unit[field]
            _auth()._id(artifact, field)
            _need(artifact not in expected_artifacts, "source and IR artifacts need distinct identities")
            expected_artifacts[artifact] = pin
        results.append({"unit_id": identity, "kind": unit["kind"], "source_text": occurrence["span_text"],
            "occurrence_cid": occurrence["record_cid"], "source_version_cid": version["record_cid"],
            "canonical_ir": {"profile": report["profile"], "typed_expression": report["typed_expression"],
                "argument_roles": report["argument_roles"], "assumptions": body["assumptions"],
                "governing_context": body["governing_context"], "interpretation_id": body["interpretation_id"],
                "source_binding": {"source_version_cid": version["record_cid"],
                    "occurrence_cid": occurrence["record_cid"], "document_revision": unit["document_revision"]},
                "definition_uses": [use for use in body["definition_uses"]
                    if use.get("use_unit_id") == identity or use.get("definition_unit_id") == identity],
                "cross_references": [ref for ref in body["cross_references"] if ref.get("from_unit_id") == identity]},
            "argument_roles": report["argument_roles"],
            "relational_profile": report["profile"], "typed_paths": paths})
    return results, expected_artifacts


def _reviewed_body(body, source_inputs, relational_inputs):
    _keys(body, {"schema", "component_id", "provenance_kind", "interpretation_id", "governing_context",
        "units", "definition_uses", "cross_references", "permitted_uses", "unresolved", "unsupported",
        "assumptions", "source_actors", "declared_at_utc"}, "complete reviewed meaning declaration")
    _need(body["schema"] == REVIEWED_DECLARATION_SCHEMA and body["provenance_kind"] in ("fictional_fixture", "statutory"),
          "explicit complete reviewed declaration and provenance required")
    auth = _auth()
    auth._id(body["component_id"], "reviewed component")
    auth._id(body["interpretation_id"], "selected interpretation")
    declared = auth._time(body["declared_at_utc"])
    context = body["governing_context"]
    _keys(context, {"jurisdiction", "instrument_id", "governing_edition", "legal_as_of_utc",
        "valid_from_utc", "valid_until_utc"}, "governing legal context")
    for key in ("jurisdiction", "instrument_id", "governing_edition"):
        auth._text(context[key], key)
    start, end = auth._interval(context)
    _need(start <= auth._time(context["legal_as_of_utc"]) < end, "legal-as-of lies outside declared applicability interval")
    _need(body["unresolved"] == [] and body["unsupported"] == [], "unresolved or unsupported meaning cannot be admitted")
    assumptions = body["assumptions"]
    _need(type(assumptions) is list and assumptions == [],
          "nonempty formal assumptions require a separately supported typed-premise profile")
    uses = body["permitted_uses"]
    _need(type(uses) is list and uses and all(type(use) is str and use in REVIEWED_USES for use in uses)
          and len(set(uses)) == len(uses), "distinct explicitly permitted semantic uses required")
    actors = body["source_actors"]
    _need(type(actors) is list and 0 < len(actors) <= 32, "complete declared source/IR producer actor inventory required")
    for actor in actors:
        _keys(actor, {"principal_id", "signer_did", "public_key_hex"}, "source producer actor")
        auth._id(actor["principal_id"], "source principal")
        _need(type(actor["signer_did"]) is str and auth._DID.fullmatch(actor["signer_did"]), "source signer DID required")
        _sha(actor["public_key_hex"], "source Ed25519 public key")
    units, artifacts = _reviewed_units(body, source_inputs, relational_inputs)
    mixed_profile = _reviewed_owners()[2].MIXED_PROFILE
    _need(any(unit["kind"] == "norm" and unit["relational_profile"] == mixed_profile for unit in units),
          "mixed admission requires at least one mixed-sort normative use")
    by_id = {row["unit_id"]: row for row in units}
    definitions = {key for key, row in by_id.items() if row["kind"] == "definition"}
    norms = {key for key, row in by_id.items() if row["kind"] == "norm"}
    _need(definitions and len(norms) >= 2, "a governing definition and two actual normative uses are required")
    applications, applied, distinct, governed = body["definition_uses"], set(), set(), set()
    _need(type(applications) is list and 2 <= len(applications) <= 64, "complete every-use definition applicability required")
    for use in applications:
        _keys(use, {"definition_unit_id", "defined_predicate", "use_unit_id", "use_occurrence_cid", "target_typed_paths",
            "applicability", "interpretation_id", "evidence_refs"}, "reviewed definition use")
        definition, target = use["definition_unit_id"], use["use_unit_id"]
        _need(definition in definitions and target in norms and use["applicability"] == "governing"
              and use["interpretation_id"] == body["interpretation_id"], "selected governing definition and interpretation required")
        _need(use["use_occurrence_cid"] == by_id[target]["occurrence_cid"] and (definition, target) not in applied,
              "definition use duplicates a physical use or names another occurrence")
        symbol = use["defined_predicate"]
        _auth()._text(symbol, "defined predicate identity")
        definition_ir = by_id[definition]["canonical_ir"]
        node, binders = definition_ir["typed_expression"]["root"], []
        while node["kind"] == "forall":
            binders.extend(binder["name"] for binder in node["binders"])
            node = node["arguments"][0]
        _need(node["kind"] == "iff" and node["arguments"][0]["kind"] == "predicate",
              "supported definition must universally bind a predicate equivalence")
        left = node["arguments"][0]
        _need(left["symbol"] == symbol and [argument["symbol"] for argument in left["arguments"]] == binders,
              "defined predicate must apply to the complete ordered definition binders")
        definition_roles = next(row["roles"] for row in definition_ir["argument_roles"] if row["symbol"] == symbol)
        norm_ir = by_id[target]["canonical_ir"]
        norm_roles = [row["roles"] for row in norm_ir["argument_roles"] if row["symbol"] == symbol]
        _need(norm_roles == [definition_roles], "governing predicate arity or ordered argument roles differ")
        _need(_predicate_domain(norm_ir, symbol) == _predicate_domain(definition_ir, symbol),
              "governing predicate argument sorts differ")
        actual_paths = []
        for path in by_id[target]["typed_paths"]:
            selected = norm_ir["typed_expression"]
            for token in path.split("/")[1:]:
                selected = selected[int(token)] if type(selected) is list else selected[token]
            if type(selected) is dict and selected.get("kind") == "predicate" and selected.get("symbol") == symbol:
                actual_paths.append(path)
        paths = use["target_typed_paths"]
        _need(type(paths) is list and bool(paths) and paths == actual_paths,
              "complete ordered predicate definition-use targets required")
        for path in paths:
            _need((target, path) not in governed, "competing governing definitions for one typed use remain unresolved")
            governed.add((target, path))
        _reviewed_refs(use["evidence_refs"])
        applied.add((definition, target))
        distinct.add(target)
    _need(distinct == norms and {key for key, _ in applied} == definitions,
          "every normative use and governing definition must be reviewed")
    refs = body["cross_references"]
    _need(type(refs) is list and len(refs) <= 64, "bounded complete cross-reference inventory required")
    versions = {}
    for ref in refs:
        _keys(ref, {"from_unit_id", "dependency_artifact_id", "dependency_sha256", "version", "evidence_refs"},
              "versioned reviewed cross reference")
        _need(ref["from_unit_id"] in by_id, "cross reference names another source unit")
        auth._id(ref["dependency_artifact_id"], "cross-reference dependency")
        _sha(ref["dependency_sha256"], "cross-reference dependency version")
        auth._text(ref["version"], "cross-reference version")
        _reviewed_refs(ref["evidence_refs"])
        key = ref["dependency_artifact_id"]
        _need(key not in artifacts or artifacts[key] == ref["dependency_sha256"], "conflicting dependency versions")
        version = ref["version"]
        _need(versions.setdefault(key, version) == version, "conflicting dependency versions")
        artifacts[key] = ref["dependency_sha256"]
    # The artifact manifest can be acyclic even when the reviewed units are not.
    # Match the incremental owner's dependent-to-dependency relation.
    unit_edges = [
        {"dependent_id": unit["unit_id"], "dependency_id": parent}
        for unit in body["units"] for parent in unit["parent_unit_ids"]
    ]
    unit_edges.extend(
        {"dependent_id": use["use_unit_id"], "dependency_id": use["definition_unit_id"]}
        for use in applications
    )
    dependencies = _reviewed_owners()[-1]
    _need(not dependencies._cycles(by_id, unit_edges),
          "cyclic or unresolved reviewed governing dependency")
    return units, artifacts, declared


def prepare_reviewed_norm_admission_v3(declaration, *, expected_declaration_sha256,
        source_inputs, relational_inputs, dependency_manifest, expected_manifest_sha256):
    """Replay a complete meaning proposal; preparation grants no authority.

    Full source geometry and the selected strict typed relational profiles are
    checked mechanically. Meaning, governing context and dependency completeness
    are explicit review subjects, not facts inferred from hashes or compilation.
    """
    original = dict(declaration=declaration, expected_declaration_sha256=expected_declaration_sha256,
        source_inputs=source_inputs, relational_inputs=relational_inputs,
        dependency_manifest=dependency_manifest, expected_manifest_sha256=expected_manifest_sha256)
    detached, commitment = norm._snapshot(original)
    pins = _reviewed_pins()
    _sha(expected_declaration_sha256, "complete reviewed declaration")
    body = detached["declaration"]
    _need(norm_content_adjudication_sha256(body) == expected_declaration_sha256, "complete reviewed declaration pin differs")
    units, artifacts, _ = _reviewed_body(body, detached["source_inputs"], detached["relational_inputs"])
    dependencies = _reviewed_owners()[-1]
    manifest = dependencies.validate_dependency_manifest(detached["dependency_manifest"],
        expected_manifest_sha256=expected_manifest_sha256)
    root = body["component_id"]
    _need(root not in artifacts, "component and dependency artifact identities must differ")
    artifacts = {root: expected_declaration_sha256, **artifacts}
    _need({row["artifact_id"]: row["artifact_sha256"] for row in manifest["artifacts"]} == artifacts,
          "source, IR or cross-reference dependency version omitted or changed")
    reachable, _ = _auth()._closure(manifest, root, expected_declaration_sha256)
    _need(set(reachable) == set(artifacts) and not manifest["missing_dependencies"] and not manifest["cycles"],
          "complete acyclic reviewed dependency closure required")
    subject = {"schema": REVIEWED_SUBJECT_SCHEMA, "graph_id": root,
        "graph_sha256": expected_declaration_sha256, "declaration_sha256": expected_declaration_sha256,
        "ast_sha256": norm_content_adjudication_sha256([{key: row[key] for key in
            ("unit_id", "canonical_ir", "argument_roles", "relational_profile")} for row in units]),
        "source_binding_sha256": norm_content_adjudication_sha256(body["units"]),
        "scope_id": body["governing_context"]["jurisdiction"], "context_slot_ids": list(REVIEWED_SLOTS),
        "context_packet_sha256": norm_content_adjudication_sha256({"declaration": body, "producer_pins": pins}),
        "dependency_manifest_sha256": expected_manifest_sha256, "required_dependency_ids": reachable}
    _reviewed_subject(subject, manifest)
    report = {"schema": "legal-reviewed-mixed-sort-norm-preparation/v3", "profile": REVIEWED_PROFILE,
        "declaration_sha256": expected_declaration_sha256, "declaration": body, "subject": subject,
        "units": units, "producer_pins": pins, "semantic_use_eligible": False,
        "training_mask": 0, "evaluation_gold_mask": 0, "Lean_admitted": False, "proof_authority": False}
    return _reviewed_finish(original, detached, commitment, pins, report)


def assess_reviewed_norm_admission_v3(preparation, registry, policy, reviews, *,
        expected_preparation_sha256, preparation_inputs, expected_registry_sha256,
        expected_policy_sha256, expected_reviews_sha256, at_time_utc,
        observed_artifact_sha256s, observed_pins, evidence_artifacts):
    """Admit declared semantic uses only after fresh full replay and review.

    The caller supplies independent trust pins and current observations. This
    API authenticates neither human competence nor the freshness of an external
    clock/registry. It never establishes formal assumptions or proof/corpus entry.
    """
    original = dict(preparation=preparation, registry=registry, policy=policy, reviews=reviews,
        expected_preparation_sha256=expected_preparation_sha256, preparation_inputs=preparation_inputs,
        expected_registry_sha256=expected_registry_sha256, expected_policy_sha256=expected_policy_sha256,
        expected_reviews_sha256=expected_reviews_sha256, at_time_utc=at_time_utc,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins, evidence_artifacts=evidence_artifacts)
    detached, commitment = norm._snapshot(original)
    pins = _reviewed_pins()
    _sha(expected_preparation_sha256, "complete reviewed preparation")
    _need(norm_content_adjudication_sha256(detached["preparation"]) == expected_preparation_sha256,
          "independently pinned reviewed preparation differs")
    prepared = prepare_reviewed_norm_admission_v3(**detached["preparation_inputs"])
    _need(norm._same(detached["preparation"], prepared), "reviewed preparation differs from complete original replay")
    body, subject, auth = prepared["declaration"], prepared["subject"], _auth()
    domain = auth._ReviewDomain(REVIEWED_SUBJECT_SCHEMA, REVIEWED_CLAIM_SCHEMA, REVIEWED_ACTION,
        REVIEWED_AUDIENCE, "legal-reviewed-mixed-sort-norm-authority-assessment/v3", _reviewed_subject, len(REVIEWED_SLOTS))
    authority = auth._assess_reviews(subject, detached["registry"], detached["policy"], detached["reviews"],
        detached["preparation_inputs"]["dependency_manifest"], domain=domain,
        **{key: detached[key] for key in ("expected_registry_sha256", "expected_policy_sha256", "expected_reviews_sha256",
            "at_time_utc", "observed_artifact_sha256s", "observed_pins", "evidence_artifacts")},
        expected_subject_sha256=auth.digest(subject), expected_manifest_sha256=subject["dependency_manifest_sha256"])
    blockers = [] if authority["review_prerequisites_satisfied_under_selected_trust"] else [
        item for item in authority["blockers"] if item not in
        ("downstream_semantic_validation_required", "downstream_Lean_kernel_admission_required")]
    keys = {key["key_id"]: key for key in detached["registry"]["keys"]}
    current = [claim for claim in detached["reviews"] if any(row["review_id"] == claim["review_id"]
        and row["status"] == "authenticated" for row in authority["reviews"])]
    if not _distinct_pair(current, keys):
        blockers.append("independent_review_roles_missing")
    body_ref = {"artifact_id": body["component_id"], "sha256": prepared["declaration_sha256"]}
    evidence = detached["evidence_artifacts"]
    if evidence.get(body["component_id"]) != norm._wire(body):
        blockers.append("complete_signed_declaration_evidence_missing_or_changed")
    declared = auth._time(body["declared_at_utc"])
    if declared > auth._time(at_time_utc) or any(auth._time(claim["issued_at_utc"]) < declared for claim in detached["reviews"]):
        blockers.append("review_or_evaluation_predates_declaration")
    excluded_ids = {body["component_id"]}
    excluded_hashes = {prepared["declaration_sha256"], expected_preparation_sha256,
        expected_registry_sha256, expected_policy_sha256, expected_reviews_sha256}
    for unit in body["units"]:
        excluded_ids.update((unit["source_artifact_id"], unit["ir_artifact_id"]))
        excluded_hashes.update((unit["source_version"]["raw_artifact"]["sha256"],
            unit["source_version"]["extracted_view"]["sha256"], unit["occurrence"]["span_sha256"],
            norm_content_adjudication_sha256(unit["source_version"]),
            norm_content_adjudication_sha256(unit["occurrence"]),
            unit["relational_request_sha256"],
            detached["preparation_inputs"]["relational_inputs"][unit["unit_id"]]["expected_report_sha256"]))
    excluded_ids.update(ref["dependency_artifact_id"] for ref in body["cross_references"])
    excluded_hashes.update(ref["dependency_sha256"] for ref in body["cross_references"])
    excluded_hashes.update(auth.digest(claim) for claim in detached["reviews"])
    for claim in detached["reviews"]:
        key = keys.get(claim["key_id"])
        if any(claim["principal_id"] == actor["principal_id"] or claim["signer_did"] == actor["signer_did"]
               or key is not None and (key["principal_id"] == actor["principal_id"]
                   or key["signer_did"] == actor["signer_did"] or key["public_key_hex"] == actor["public_key_hex"])
               for actor in body["source_actors"]):
            blockers.append("reviewer_reuses_source_or_IR_producer_identity")
        for obligation in claim["context_closure"]["obligations"]:
            refs = obligation["evidence_refs"]
            independent = [ref for ref in refs if ref["artifact_id"] not in excluded_ids
                and ref["sha256"] not in excluded_hashes]
            if obligation["disposition"] != "resolved_by_evidence" or body_ref not in refs or not independent:
                blockers.append("whole_body_and_independent_process_evidence_required_for_each_review_obligation")
    for item in body["definition_uses"] + body["cross_references"]:
        for ref in item["evidence_refs"]:
            raw = evidence.get(ref["artifact_id"])
            if ref["artifact_id"] in excluded_ids or ref["sha256"] in excluded_hashes or type(raw) is not bytes or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                blockers.append("definition_or_cross_reference_process_evidence_missing_or_changed")
    eligible = not blockers
    statutory = body["provenance_kind"] == "statutory"
    report = {"schema": "legal-reviewed-mixed-sort-norm-admission-assessment/v3", "profile": REVIEWED_PROFILE,
        "declaration_sha256": prepared["declaration_sha256"], "preparation_sha256": expected_preparation_sha256,
        "provenance_kind": body["provenance_kind"], "semantic_use_eligible": eligible,
        "permitted_uses": body["permitted_uses"] if eligible else [], "blockers": sorted(set(blockers)),
        "units": prepared["units"], "producer_pins": pins, "review_authority": authority,
        "training_mask": int(eligible and statutory and "training" in body["permitted_uses"]),
        "evaluation_gold_mask": int(eligible and statutory and "heldout_evaluation" in body["permitted_uses"]),
        "fixture_only": not statutory, "eligibility_scope": "declared semantic uses under supplied current trust and observations",
        "formal_assumptions": body["assumptions"], "formal_assumptions_proved": False,
        "human_identity_and_competence_verified": False, "global_reviewer_cohort_verified": False,
        "evaluation_clock_authenticated": False, "registry_freshness_authenticated": False,
        "Lean_admitted": False, "proof_authority": False, "semantic_graph_admitted": False,
        "corpus_admitted": False, "training_executed": False}
    return _reviewed_finish(original, detached, commitment, pins, report)


def validate_reviewed_norm_admission_v3(report, *args, expected_report_sha256, **kwargs):
    """Recompute eligibility from complete original inputs, never saved flags."""
    original = dict(report=report, args=list(args), kwargs=kwargs)
    detached, commitment = norm._snapshot(original)
    pins = _reviewed_pins()
    _sha(expected_report_sha256, "reviewed admission report")
    _need(norm_content_adjudication_sha256(detached["report"]) == expected_report_sha256,
          "independent reviewed admission report pin differs")
    expected = assess_reviewed_norm_admission_v3(*detached["args"], **detached["kwargs"])
    _need(norm._same(expected, detached["report"]), "reviewed admission report differs from complete current replay")
    return _reviewed_finish(original, detached, commitment, pins, expected)


__all__ = ["prepare_reviewed_norm_admission_v3", "assess_reviewed_norm_admission_v3",
    "validate_reviewed_norm_admission_v3", "REVIEWED_PROFILE", "REVIEWED_DECLARATION_SCHEMA",
    "REVIEWED_SUBJECT_SCHEMA", "REVIEWED_CLAIM_SCHEMA", "REVIEWED_ACTION", "REVIEWED_AUDIENCE", "REVIEWED_SLOTS"]
