"""Check pinned TRAIN relation declarations without admitting any relation.

Exact formal-view identity is a weak structural observation. Declared positive
and negative relations, family scopes and evidence hashes remain unverified
metadata. This owner performs no file I/O, numerical loss, model or proof call.
"""
from __future__ import annotations

import json
from collections import Counter

from . import alignment_stage_declarations as stages
from .alignment_lane_bundle import MASKS, _closed, _digest, _raw, _require, _sha, _text

SCHEMA = "alignment-train-relation-declaration/v1"
POLICY_SCHEMA = "alignment-train-relation-policy/v1"
LEDGER_SCHEMA = "alignment-train-pair-ledger/v1"
VALIDATION_SCHEMA = "alignment-train-relation-validation/v1"
MAX_TRAIN_ROWS = 128
MAX_BYTES = 16 * 1024 * 1024
MAX_EXPECTED_BYTES = 1024 * 1024
MODE = "diagnostic_unadmitted_relations/v1"
PAIR_ORDER = "train_row_major/v1"
WEAK_STRUCTURAL_POLICY = "exact_formal_identity_only/v1"
FAMILY_COERCION_POLICY = "not_performed/v1"
ELIGIBILITY = "blocked_no_admitted_relations"
STATUSES = ("unknown", "declared_positive", "declared_negative", "weak_structural_identity")
PAIR_FIELDS = {"left_id", "right_id", "left_input_sha256", "right_input_sha256",
               "left_formal_view_sha256", "right_formal_view_sha256", "relation_status",
               "evidence_sha256", "reason", "positive_mask", "permitted_negative_mask"}
FALSE = dict.fromkeys(("accepted", "qualified", "source_fidelity_established", "proof_authority",
                      "semantic_label_admission", "reviewer_identity_authenticated",
                      "independent_semantic_review_completed", "file_bindings_verified",
                      "evidence_contents_verified", "relation_semantics_verified", "family_profile_scope_verified",
                      "family_coercion_executed", "split_provenance_authenticated", "training_executed",
                      "model_executed", "numerical_worker_executed", "query_reference_accessed",
                      "weak_structural_diagnostic_fit_authorized"), False)


def _bounded(value, maximum, label):
    _require(len(_raw(value)) <= maximum, label + " byte bound exceeded")


def _policy(policy, lane):
    fields = {"mode", "pair_order", "weak_structural_policy", "family_coercion_policy",
              "source_family_id", "target_family_id", "source_profile_sha256", "target_profile_sha256"}
    stages._role(policy, fields, POLICY_SCHEMA, "diagnostic relation policy")
    for key, expected in (("mode", MODE), ("pair_order", PAIR_ORDER),
                          ("weak_structural_policy", WEAK_STRUCTURAL_POLICY),
                          ("family_coercion_policy", FAMILY_COERCION_POLICY)):
        _require(policy[key] == expected, "diagnostic relation " + key + " differs")
    for key in ("source_family_id", "target_family_id"):
        if policy[key] is not None:
            _text(policy[key], "declared " + key, maximum=512)
    _sha(policy["source_profile_sha256"], "declared source profile SHA")
    _require(policy["source_profile_sha256"] == lane["profile_sha256"],
             "relation policy source profile differs from bound lane")
    _sha(policy["target_profile_sha256"], "opaque declared target profile SHA", nullable=True)


def validate_relation_declaration(declaration, *, expected_bindings):
    """Validate a complete row-major ledger; all semantic masks stay false.

    Required external role pins hash each full sealed role and its ordered
    ``rows`` (null when absent), following the frozen stage declaration recipe.
    Matching pins establish declared associations, never evidence authenticity.
    """
    _bounded(declaration, MAX_BYTES, "relation declaration")
    _bounded(expected_bindings, MAX_EXPECTED_BYTES, "external relation pins")
    names = ("lane_validation", "train_manifest", "relation_policy", "pair_ledger")
    stages._role(declaration, names, SCHEMA, "relation declaration")
    values = {name: declaration[name] for name in names}
    stages._pins(values, expected_bindings)
    lane, train, policy, ledger = (values[name] for name in names)
    stages._lane(lane)
    stages._role(train, {"rows", "file_binding"}, "alignment-train-manifest/v1", "relation TRAIN manifest")
    stages._file(train["file_binding"])
    stages._rows(train["rows"], stages.ROW_FIELDS | {"split", "formal_view_sha256", "masks"}, "relation TRAIN")
    rows = train["rows"]
    _require(1 <= len(rows) <= MAX_TRAIN_ROWS, "bounded nonempty TRAIN manifest required")
    stages._join([{key: row[key] for key in stages.ROW_FIELDS} for row in rows], lane)
    for row in rows:
        _require(row["split"] == "train", "relation manifest contains a non-TRAIN row")
        _sha(row["formal_view_sha256"], "TRAIN formal view SHA")
        stages._zero_masks(row["masks"])
    _policy(policy, lane)
    stages._role(ledger, {"rows"}, LEDGER_SCHEMA, "complete TRAIN pair ledger")
    pairs = ledger["rows"]
    count = len(rows)
    _require(type(pairs) is list and len(pairs) == count * count,
             "complete ordered TRAIN Cartesian pair ledger required")
    counts = Counter()
    result_rows = []
    for index, pair in enumerate(pairs):
        _closed(pair, PAIR_FIELDS, "TRAIN pair declaration")
        left, right = rows[index // count], rows[index % count]
        for prefix, source in (("left", left), ("right", right)):
            expected = {prefix + "_id": source["id"], prefix + "_input_sha256": source["input_sha256"],
                        prefix + "_formal_view_sha256": source["formal_view_sha256"]}
            _require(all(pair[key] == value for key, value in expected.items()),
                     "TRAIN pair order or source/input/formal binding differs")
        status = pair["relation_status"]
        _require(type(status) is str and status in STATUSES, "known diagnostic relation status required")
        if status == "weak_structural_identity":
            _require(left["formal_view_sha256"] == right["formal_view_sha256"],
                     "weak structural identity requires exact formal-view identity")
        _sha(pair["evidence_sha256"], "declared unadmitted evidence SHA", nullable=True)
        _text(pair["reason"], "diagnostic relation reason", maximum=4096)
        _require(pair["positive_mask"] is False and pair["permitted_negative_mask"] is False,
                 "diagnostic relation masks must be exact boolean false")
        counts[status] += 1
        result_rows.append({**pair, "eligibility": ELIGIBILITY,
                            "evidence_status": "not_provided" if pair["evidence_sha256"] is None
                            else "declared_unverified_unadmitted"})
    result = {"schema": VALIDATION_SCHEMA, "status": "validated_declared_train_relations_only",
              "eligibility": ELIGIBILITY, "declaration_sha256": _digest(declaration),
              "role_bindings": stages._bindings(values),
              "validation_scope": "externally_pinned_declared_train_pair_associations_only",
              "train_row_count": count, "pair_count": len(pairs), "pair_order": PAIR_ORDER,
              "declared_relation_counts": {status: counts[status] for status in STATUSES},
              "declared_evidence_count": sum(pair["evidence_sha256"] is not None for pair in pairs),
              "exact_formal_identity_pair_count": sum(left["formal_view_sha256"] == right["formal_view_sha256"]
                                                      for left in rows for right in rows),
              "admitted_positive_pair_count": 0, "permitted_negative_pair_count": 0,
              "semantic_positive_pair_count": 0, "admitted_evidence_count": 0,
              "positive_mask": [[False for _ in rows] for _ in rows],
              "permitted_negative_mask": [[False for _ in rows] for _ in rows],
              "rows": result_rows, "declared_family_profile_scope": {key: policy[key] for key in (
                  "source_family_id", "target_family_id", "source_profile_sha256", "target_profile_sha256")},
              "weak_diagnostic_policy_required": True, "verification_status": "pending", "admission_status": "pending",
              "masks": dict.fromkeys(MASKS, 0), "model_calls": 0, "encoder_calls": 0, "prover_calls": 0,
              "optimizer_updates": 0, **FALSE}
    result["content_sha256"] = _digest(result)
    _bounded(result, MAX_BYTES, "relation validation receipt")
    return json.loads(_raw(result))


__all__ = ["validate_relation_declaration"]


# This profile commits a complete directed pair ledger for a separate review.
# Endpoint admission is necessary; it never implies a positive or negative pair.
REVIEWED_SCHEMA = "alignment-reviewed-pair-preparation/v2"
REVIEWED_BODY_SCHEMA = "alignment-reviewed-pair-declaration/v2"
REVIEWED_PROFILE = "reviewed-native384-source-formal-pairs/v2"
REVIEWED_SUBJECT_SCHEMA = "alignment-reviewed-pair-subject/v2"
REVIEWED_CLAIM_SCHEMA = "alignment-reviewed-pair-signed-claim/v2"
REVIEWED_ACTION = "authorize_reviewed_contrastive_pair_labels/v2"
REVIEWED_AUDIENCE = "legal-autoformalization-reviewed-contrastive-pairs/v2"
REVIEWED_SLOTS = ("directed_pair_relationships", "governing_context", "contrastive_purpose",
                  "representation_provenance", "split_and_dependency_scope")
REVIEWED_RELATIONS = ("corresponding", "equivalent", "incompatible", "unknown", "analogy")
REVIEWED_ENDPOINT_FIELDS = {"id", "unit_id", "admission_id", "source_sha256", "formal_view_sha256",
    "context_sha256", "input_sha256", "vector_sha256", "split_sample_id", "exposure_group",
    "dependency_group_sha256"}

# Freeze the raw source identities when this module and its direct pure owners
# are loaded, rather than relabel an older in-memory implementation on first use.
from pathlib import Path as _ReviewedPath
import hashlib as _reviewed_hashlib
from . import alignment_lane_bundle as _reviewed_lane_owner
_REVIEWED_IMPORTED_RAW_PINS = {
    str(_ReviewedPath(path).resolve()): _reviewed_hashlib.sha256(_ReviewedPath(path).read_bytes()).hexdigest()
    for path in (__file__, stages.__file__, _reviewed_lane_owner.__file__)
}


def _reviewed_imported_pins():
    observed = {path: _reviewed_hashlib.sha256(_ReviewedPath(path).read_bytes()).hexdigest()
                for path in _REVIEWED_IMPORTED_RAW_PINS}
    _require(observed == _REVIEWED_IMPORTED_RAW_PINS,
             "reviewed pair self or directly imported source changed since import")
    return dict(_REVIEWED_IMPORTED_RAW_PINS)


def _reviewed_owners():
    from ...autoformal import legal_norm_content_adjudication_v1 as admission
    from ...autoformal import legal_graph_review as review, legal_graph_dependencies as dependencies
    from ....optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    from . import alignment_lane_bundle as lanes
    return admission, review, dependencies, splits, lanes


def _reviewed_pins():
    from pathlib import Path
    import hashlib
    imported = _reviewed_imported_pins()
    owners = _reviewed_owners()
    pins = dict(owners[0]._reviewed_pins())
    pins.update(imported)
    for module in (*owners[1:], stages):
        path = Path(module.__file__).resolve()
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        _require(str(path) not in imported or imported[str(path)] == observed,
                 "reviewed pair direct dependency differs from imported source")
        pins[str(path)] = observed
    _require(_reviewed_imported_pins() == imported, "reviewed pair direct source changed during pin capture")
    return pins


def _reviewed_finish(original, copied, commitment, pins, report):
    admission = _reviewed_owners()[0]
    _require(admission.norm._snapshot(original)[1] == commitment
             and admission.norm._snapshot(copied)[1] == commitment, "reviewed pair inputs changed during operation")
    _require(_reviewed_pins() == pins, "reviewed pair source owners changed during operation")
    return json.loads(admission.norm._wire(report))


def _reviewed_subject(subject, manifest):
    _, review, _, _, _ = _reviewed_owners()
    _closed(subject, {"schema", "graph_id", "graph_sha256", "ast_sha256", "scope_id", "context_slot_ids",
        "dependency_manifest_sha256", "required_dependency_ids", "source_binding_sha256",
        "context_packet_sha256"}, "reviewed pair signing subject")
    _require(subject["schema"] == REVIEWED_SUBJECT_SCHEMA and subject["context_slot_ids"] == list(REVIEWED_SLOTS),
             "fixed reviewed directed-pair subject required")
    for key, value in subject.items():
        if key.endswith("_sha256"): _sha(value, key)
    review._id(subject["graph_id"], "reviewed pair ledger identity")
    review._text(subject["scope_id"], "reviewed pair governing scope")
    reachable, _ = review._closure(manifest, subject["graph_id"], subject["graph_sha256"])
    _require(subject["required_dependency_ids"] == reachable, "reviewed pair dependency closure differs")


def prepare_reviewed_relation_declaration_v2(body, *, expected_body_sha256, endpoint_admissions,
        source_lane, formal_lane, expected_source_lane_bindings, expected_formal_lane_bindings,
        split_manifest, expected_split_manifest_sha256, dependency_manifest, expected_manifest_sha256,
        allow_fictional_fixture=False):
    """Replay endpoints, vector custody and splits; grant no pair-label authority.

    Vector rows remain externally pinned producer declarations. This operation
    neither attests their runtime computation nor authorizes a fit. Unknown pairs
    need no invented review. Cross-context applicability is outside this profile.
    """
    _reviewed_imported_pins()
    import hashlib
    admission, review, dependencies, splits, lanes = _reviewed_owners()
    original = dict(body=body, expected_body_sha256=expected_body_sha256, endpoint_admissions=endpoint_admissions,
        source_lane=source_lane, formal_lane=formal_lane, expected_source_lane_bindings=expected_source_lane_bindings,
        expected_formal_lane_bindings=expected_formal_lane_bindings, split_manifest=split_manifest,
        expected_split_manifest_sha256=expected_split_manifest_sha256, dependency_manifest=dependency_manifest,
        expected_manifest_sha256=expected_manifest_sha256, allow_fictional_fixture=allow_fictional_fixture)
    copied, commitment = admission.norm._snapshot(original)
    pins = _reviewed_pins()
    value = copied["body"]
    _sha(expected_body_sha256, "reviewed pair body")
    _require(admission.norm_content_adjudication_sha256(value) == expected_body_sha256,
             "independent complete reviewed pair body pin differs")
    _closed(value, {"schema", "ledger_id", "purpose", "provenance_kind", "declared_at_utc", "source_endpoints",
        "formal_endpoints", "pairs", "author_actors", "source_lane_sha256", "formal_lane_sha256",
        "split_manifest_sha256"}, "reviewed pair declaration")
    _require(value["schema"] == REVIEWED_BODY_SCHEMA and value["purpose"] == "contrastive_supervision",
             "explicit versioned contrastive purpose required")
    _require(value["provenance_kind"] in ("statutory", "fictional_fixture"), "explicit pair provenance required")
    _require(type(allow_fictional_fixture) is bool and
        (value["provenance_kind"] != "fictional_fixture" or allow_fictional_fixture),
        "fictional pair fixtures require explicit opt-in")
    review._id(value["ledger_id"], "pair ledger")
    declared = review._time(value["declared_at_utc"])
    _require(type(copied["endpoint_admissions"]) is dict and 1 <= len(copied["endpoint_admissions"]) <= MAX_TRAIN_ROWS,
             "bounded complete endpoint admission mapping required")
    validated, authors, clocks, artifact_pins = {}, list(value["author_actors"]), set(), {}
    _require(type(value["author_actors"]) is list and 1 <= len(value["author_actors"]) <= 32,
             "explicit pair declaration author inventory required")
    for actor in value["author_actors"]:
        _closed(actor, {"principal_id", "signer_did", "public_key_hex"}, "pair declaration author")
        review._id(actor["principal_id"], "pair author principal")
        _require(type(actor["signer_did"]) is str and review._DID.fullmatch(actor["signer_did"]), "pair author DID required")
        _sha(actor["public_key_hex"], "pair author Ed25519 public key")
    for identity, entry in copied["endpoint_admissions"].items():
        review._id(identity, "endpoint admission identity")
        _closed(entry, {"report", "args", "kwargs", "expected_report_sha256"}, "complete endpoint admission replay")
        _require(type(entry["args"]) is list and len(entry["args"]) == 4 and type(entry["kwargs"]) is dict,
                 "exact original admission arguments required")
        result = admission.validate_reviewed_norm_admission_v2(entry["report"], *entry["args"],
            expected_report_sha256=entry["expected_report_sha256"], **entry["kwargs"])
        _require(result["semantic_use_eligible"] is True and "training" in result["permitted_uses"],
                 "all endpoints need current explicit semantic training permission")
        _require(result["provenance_kind"] == value["provenance_kind"], "endpoint and pair provenance differ")
        declaration = entry["kwargs"]["preparation_inputs"]["declaration"]
        authors.extend(declaration["source_actors"])
        clock = entry["kwargs"]["at_time_utc"]
        _require(declared >= review._time(clock), "pair declaration predates endpoint admission snapshot")
        clocks.add(clock)
        validated[identity] = (result, entry, declaration)
        artifact_pins[value["ledger_id"] + ":admission:" + identity] = entry["expected_report_sha256"]
    _require(len(clocks) == 1, "endpoint admissions require one explicit assessment clock")
    lane_receipts = []
    for side in ("source", "formal"):
        lane, expected = copied[side + "_lane"], copied["expected_" + side + "_lane_bindings"]
        receipt = lanes.validate_lane_bundle(lane, expected_bindings=expected)
        profile = lane["profile"]
        _require(profile["lane_id"] == "native384" and profile["stage"] == "raw_embedding"
            and profile["dimension"] == 384 and profile["inference_input_recipe"] == "exact_source_only/v1",
            "initial reviewed route requires native unmodified 384-dimensional source-only producer declarations")
        _require(value[side + "_lane_sha256"] == lanes._digest(lane), "reviewed vector lane differs from complete declaration")
        lane_receipts.append(receipt)
        artifact_pins[value["ledger_id"] + ":" + side + "-lane"] = lanes._digest(lane)
    _require(copied["source_lane"]["profile"] == copied["formal_lane"]["profile"],
             "source and formal representations require the same exact initial encoder profile")
    _sha(expected_split_manifest_sha256, "split manifest")
    _require(lanes._digest(copied["split_manifest"]) == expected_split_manifest_sha256
        == value["split_manifest_sha256"], "independent complete split manifest differs")
    manifest = splits.LegalIRSplitManifest.from_mapping(copied["split_manifest"])
    _require(manifest.to_dict() == copied["split_manifest"] and manifest.protected_splits == splits.PROTECTED_LEGAL_IR_SPLITS
        and manifest.partition_names == splits.LEGAL_IR_EVAL_SPLITS, "exact canonical split manifest required")
    examples = {row.sample_id: row for row in manifest.examples}
    _require(set(examples) == set(manifest.assignments), "complete split assignment population required")
    artifact_pins[value["ledger_id"] + ":split"] = expected_split_manifest_sha256
    endpoint_results, vectors, scopes, used_admissions, unavailable = {}, {}, set(), set(), []
    for side in ("source", "formal"):
        endpoints, rows = value[side + "_endpoints"], copied[side + "_lane"]["rows"]
        _require(type(endpoints) is list and 1 <= len(endpoints) <= MAX_TRAIN_ROWS and len(endpoints) == len(rows),
                 "complete bounded ordered source and formal endpoint populations required")
        summaries, side_vectors, seen = [], [], set()
        for endpoint, row in zip(endpoints, rows, strict=True):
            _closed(endpoint, REVIEWED_ENDPOINT_FIELDS, "reviewed pair endpoint")
            _require(endpoint["id"] == row["id"] and endpoint["id"] not in seen, "endpoint/vector order or unique identity differs")
            seen.add(endpoint["id"])
            identity = endpoint["admission_id"]
            _require(identity in validated, "endpoint names an unprovided admission")
            used_admissions.add(identity)
            result, entry, declaration = validated[identity]
            candidates = [unit for unit in result["units"] if unit["unit_id"] == endpoint["unit_id"]]
            _require(len(candidates) == 1, "one exact completely admitted unit per endpoint required")
            unit = candidates[0]
            ir = unit["canonical_ir"]
            scope = {key: ir[key] for key in ("governing_context", "interpretation_id", "assumptions")}
            scope_sha = admission.norm_content_adjudication_sha256(scope)
            scopes.add(scope_sha)
            _require(endpoint["source_sha256"] == hashlib.sha256(unit["source_text"].encode("utf-8")).hexdigest()
                and endpoint["formal_view_sha256"] == admission.norm_content_adjudication_sha256(ir)
                and endpoint["context_sha256"] == scope_sha, "complete endpoint source, formal view or context differs")
            encoder_text = unit["source_text"] if side == "source" else admission.norm._wire(ir).decode("utf-8")
            _require(row["input"]["source_text"] == encoder_text and row["input"]["context"]["role"] == "none_required"
                and endpoint["input_sha256"] == row["input_sha256"] and endpoint["vector_sha256"] == row["vector_sha256"],
                "producer input/view/vector binding differs from reviewed endpoint")
            sample = examples.get(endpoint["split_sample_id"])
            _require(sample is not None and sample.content_hash == splits._content_hash(unit["source_text"])
                and sample.lineage_group_id and endpoint["exposure_group"] == sample.lineage_group_id,
                "endpoint exposure group or exact source differs from split population")
            deps = entry["kwargs"]["preparation_inputs"]["dependency_manifest"]["expected_artifact_ids"]
            _require(endpoint["dependency_group_sha256"] == lanes._digest(deps), "complete endpoint dependency group differs")
            splits.authorize_legal_ir_split_use(manifest, operation="training", items=[{"sample_id": sample.sample_id}])
            if row["status"] != "available": unavailable.append(side + ":" + endpoint["id"])
            side_vectors.append(row["vector"])
            summaries.append({**endpoint, "admission_sha256": entry["expected_report_sha256"],
                "producer_row_sha256": row["producer_row_sha256"], "scope": scope,
                "jurisdiction": ir["governing_context"]["jurisdiction"], "split": "train"})
        endpoint_results[side] = summaries
        vectors[side] = side_vectors
    _require(len(scopes) == 1, "differing governing contexts require a separately reviewed applicability contract")
    _require(used_admissions == set(validated), "unused endpoint admission rows cannot be silently ignored")
    left, right, pairs = value["source_endpoints"], value["formal_endpoints"], value["pairs"]
    _require(type(pairs) is list and len(pairs) == len(left) * len(right), "complete rectangular directed pair ledger required")
    for index, pair in enumerate(pairs):
        _closed(pair, {"left_id", "right_id", "relation", "reason", "evidence_refs"}, "directed reviewed pair declaration")
        _require(pair["left_id"] == left[index // len(right)]["id"] and pair["right_id"] == right[index % len(right)]["id"],
                 "directed pair order or endpoint identities differ")
        _require(pair["relation"] in REVIEWED_RELATIONS, "explicit reviewed relationship kind required")
        _text(pair["reason"], "pair relationship reason", maximum=4096)
        _require(type(pair["evidence_refs"]) is list, "explicit pair evidence inventory required")
        if pair["relation"] in ("corresponding", "equivalent", "incompatible"):
            admission._reviewed_refs(pair["evidence_refs"])
        else:
            _require(len(pair["evidence_refs"]) <= 8, "bounded unknown or analogy references required")
            for ref in pair["evidence_refs"]:
                _closed(ref, {"artifact_id", "sha256"}, "pair evidence reference")
                review._id(ref["artifact_id"], "pair evidence"); _sha(ref["sha256"], "pair evidence")
    artifact_pins[value["ledger_id"]] = expected_body_sha256
    checked_manifest = dependencies.validate_dependency_manifest(copied["dependency_manifest"],
        expected_manifest_sha256=expected_manifest_sha256)
    _require({row["artifact_id"]: row["artifact_sha256"] for row in checked_manifest["artifacts"]} == artifact_pins,
             "reviewed pair body, endpoints, vectors or split dependency identity differs")
    reachable, _ = review._closure(checked_manifest, value["ledger_id"], expected_body_sha256)
    _require(set(reachable) == set(artifact_pins) and not checked_manifest["cycles"]
        and not checked_manifest["missing_dependencies"], "complete acyclic reviewed pair dependency closure required")
    subject = {"schema": REVIEWED_SUBJECT_SCHEMA, "graph_id": value["ledger_id"], "graph_sha256": expected_body_sha256,
        "ast_sha256": admission.norm_content_adjudication_sha256(value["pairs"]),
        "scope_id": endpoint_results["source"][0]["jurisdiction"], "context_slot_ids": list(REVIEWED_SLOTS),
        "dependency_manifest_sha256": expected_manifest_sha256, "required_dependency_ids": reachable,
        "source_binding_sha256": admission.norm_content_adjudication_sha256(endpoint_results),
        "context_packet_sha256": admission.norm_content_adjudication_sha256({"body": value, "producer_pins": pins})}
    _reviewed_subject(subject, checked_manifest)
    report = {"schema": REVIEWED_SCHEMA, "profile": REVIEWED_PROFILE, "body": value, "body_sha256": expected_body_sha256,
        "subject": subject, "source_endpoints": endpoint_results["source"], "formal_endpoints": endpoint_results["formal"],
        "source_vectors": vectors["source"], "formal_vectors": vectors["formal"], "pairs": pairs,
        "source_lane_validation": lane_receipts[0], "formal_lane_validation": lane_receipts[1],
        "source_representation_profile": copied["source_lane"]["profile"],
        "formal_representation_profile": copied["formal_lane"]["profile"],
        "source_profile_sha256": copied["expected_source_lane_bindings"]["profile_sha256"],
        "formal_profile_sha256": copied["expected_formal_lane_bindings"]["profile_sha256"],
        "source_producer_receipt_sha256": copied["expected_source_lane_bindings"]["producer_receipt_sha256"],
        "formal_producer_receipt_sha256": copied["expected_formal_lane_bindings"]["producer_receipt_sha256"],
        "source_vector_sha256": lanes._digest(vectors["source"]), "formal_vector_sha256": lanes._digest(vectors["formal"]),
        "ordered_endpoint_sha256": admission.norm_content_adjudication_sha256(endpoint_results),
        "author_exclusions": authors, "endpoint_assessment_time_utc": next(iter(clocks)),
        "unavailable_vector_ids": unavailable, "producer_pins": pins, "semantic_label_admission": False,
        "actual_fit_authorized": False, "runtime_computation_proven": False, "training_executed": False}
    return _reviewed_finish(original, copied, commitment, pins, report)


def validate_reviewed_relation_declaration_v2(preparation, *, expected_preparation_sha256, **inputs):
    """Regenerate every endpoint/source/vector/split binding from original inputs."""
    _reviewed_imported_pins()
    admission = _reviewed_owners()[0]
    original = {"preparation": preparation, "inputs": inputs}
    copied, commitment = admission.norm._snapshot(original)
    pins = _reviewed_pins()
    _sha(expected_preparation_sha256, "reviewed pair preparation")
    _require(admission.norm_content_adjudication_sha256(copied["preparation"]) == expected_preparation_sha256,
             "independent reviewed pair preparation differs")
    expected = prepare_reviewed_relation_declaration_v2(**copied["inputs"])
    _require(admission.norm._same(copied["preparation"], expected), "reviewed pair preparation differs from complete replay")
    return _reviewed_finish(original, copied, commitment, pins, expected)


__all__ += ["prepare_reviewed_relation_declaration_v2", "validate_reviewed_relation_declaration_v2",
    "REVIEWED_PROFILE", "REVIEWED_BODY_SCHEMA", "REVIEWED_SUBJECT_SCHEMA", "REVIEWED_CLAIM_SCHEMA",
    "REVIEWED_ACTION", "REVIEWED_AUDIENCE", "REVIEWED_SLOTS"]
