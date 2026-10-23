"""Fixed-domain review evidence for unreviewed source/relational alternatives.

The existing graph-review verifier authenticates caller-selected credentials.
Its legacy graph field names bind this exact correspondence, not a new graph.
No registry, signer, clock, semantic admission or training default is supplied.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import legal_norm_scope_correspondence_v1 as correspondence_owner

PREPARATION_SCHEMA = "legal-norm-interpretation-review-evidence/v1"
SUBJECT_SCHEMA = "legal-norm-interpretation-review-subject/v1"
CLAIM_SCHEMA = "legal-norm-interpretation-review-signed-claim/v1"
SCHEMA = "legal-norm-interpretation-review-assessment/v1"
ACTION = "record_norm_interpretation_review_evidence/v1"
AUDIENCE = "legal-autoformalization-norm-interpretation-review/v1"
MAX_BYTES = 8 * 1024**2
MAX_INPUT_BYTES = 128 * 1024**2
MAX_OBLIGATIONS = 512
SEMANTIC_QUESTIONS = (
    "source_meaning", "participant_roles", "condition_and_modal_scope",
    "definition_applicability", "exceptions_and_time", "unsupported_grammar", "source_coverage",
)
FALSE_FLAGS = dict(correspondence_owner.AUTHORITY, human_identity_verified=False,
                  human_independence_verified=False, training_qualified=False,
                  legal_dependency_inventory_exhaustive=False)
_REPLAY_FIELDS = {
    "scope_report", "relational_report", "mapping_request_raw", "expected_scope_report_sha256",
    "expected_relational_report_sha256", "expected_mapping_request_sha256", "scope_replay_inputs",
    "relational_request_raw", "expected_relational_request_sha256",
}
_SUBJECT_FIELDS = {
    "schema", "graph_id", "graph_sha256", "ast_sha256", "native_ast_sha256", "scope_id",
    "context_slot_ids", "dependency_manifest_sha256", "required_dependency_ids",
    "dependency_artifacts", "graph_declared_dependency_refs", "native_binding",
}
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_BASE_PIN = hashlib.sha256(Path(correspondence_owner.__file__).read_bytes()).hexdigest()
_OWNER_PINS = None
_need = correspondence_owner._need
_keys = correspondence_owner._keys
_sha = correspondence_owner._sha


def _wire(value):
    return correspondence_owner._wire(value, MAX_BYTES)


def norm_review_sha256(value):
    """Complete canonical hash; distinct from an embedded assessment digest."""
    return hashlib.sha256(_wire(value)).hexdigest()


def _same(left, right):
    return _wire(left) == _wire(right)


def _snapshot(value, *, max_nodes=1_500_000):
    """Detach bounded JSON/bytes with a type-separated streaming commitment.

    Compound evidence callers may select a bounded node profile. The ordinary
    norm profile and every byte/depth limit retain their existing defaults.
    """
    _need(type(max_nodes) is int and 0 < max_nodes <= 4_000_000,
          "bounded positive integer snapshot node budget required")
    budget, nodes = MAX_INPUT_BYTES, max_nodes
    digest = hashlib.sha256()

    def token(tag, raw):
        nonlocal budget
        budget -= len(raw) + 16
        _need(budget >= 0, "aggregate review input byte bound exceeded")
        digest.update(tag + str(len(raw)).encode() + b":" + raw)

    def visit(item, depth):
        nonlocal nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 96, "bounded review input structure required")
        if type(item) is dict:
            _need(len(item) <= nodes and all(type(key) is str for key in item), "ordinary review mapping required")
            token(b"d", str(len(item)).encode())
            return {visit(key, depth + 1): visit(item[key], depth + 1) for key in sorted(item)}
        if type(item) is list:
            _need(len(item) <= nodes, "bounded review list required")
            token(b"l", str(len(item)).encode())
            return [visit(child, depth + 1) for child in item]
        if type(item) is bytes:
            _need(len(item) <= min(budget, 32 * 1024**2), "bounded exact review bytes required")
            token(b"b", item)
            return item
        raw = correspondence_owner._wire(item, min(budget, MAX_INPUT_BYTES))
        token(b"j", raw)
        # _wire accepts only exact immutable JSON scalars on this branch.
        # Containers above are still copied per occurrence, without memoization.
        return item

    detached = visit(value, 0)
    return detached, digest.hexdigest()


def _owners():
    from . import legal_graph_dependencies, legal_graph_review, legal_source_sampling_review_context
    return legal_graph_dependencies, legal_graph_review, legal_source_sampling_review_context


def _pins(owners):
    global _OWNER_PINS
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "norm review producer changed since import")
    _need(hashlib.sha256(Path(correspondence_owner.__file__).read_bytes()).hexdigest() == _BASE_PIN,
          "correspondence producer changed since review import")
    pins = correspondence_owner._pins(correspondence_owner._owners())
    dependencies, review, context = owners
    for module in (*owners, context.owner, review.graphs, review.contexts):
        path = Path(module.__file__).resolve()
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (Path(__file__).resolve(), Path(review.__file__).resolve().parent.parent / "profile_g.py"):
        pins[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if _OWNER_PINS is None:
        _OWNER_PINS = dict(pins)
    _need(pins == _OWNER_PINS, "norm review producers changed since first use")
    return pins


def _source_context(checked, inputs, context):
    if inputs is None:
        return {"status": "not_supplied", "packet_sha256": None, "target": None,
                "nominations": [], "source_commitments": [], "packet_counts": None,
                "typed_definition_reviews_supplied": False}, []
    packet = context.validate(**inputs)
    scope = checked["source_scope"]
    expected_sampling = scope["input_pins"]["sampling_report_full_canonical_sha256"]
    candidates = [entry for entry in packet["sources"]
                  if entry["replay_inputs"]["expected_sampling_report_sha256"] == expected_sampling]
    _need(len(candidates) == 1, "one exact target source bundle required")
    entry = candidates[0]
    sampling = entry["bundle"]["sampling_report"]
    _need(correspondence_owner._digest(sampling, 32 * 1024**2) == expected_sampling,
          "complete target sampling report differs")
    replay = scope["input_pins"]["sampler_replay_inputs"]
    for key in ("expected_descriptor_sha256", "expected_raw_sha256", "expected_raw_bytes"):
        _need(_same(entry["replay_inputs"][key], replay[key]), "target raw/descriptor commitments differ")
    unit = scope["source_records"]["unit"]
    subject_ref = {"kind": "unit", "index": unit["ordinal"],
                   "sha256": scope["input_pins"]["selected_unit_ref"]["sha256"]}
    guides = [guide for guide in entry["bundle"]["guides"] if _same(guide["subject_ref"], subject_ref)]
    _need(len(guides) == 1, "one exact selected unit guide required")
    guide = guides[0]
    for key in ("source_occurrence_ref", "context_ref"):
        _need(_same(guide[key], unit[key]), "target source occurrence/context differs")
    selected = [row for row in packet["attachments"]
                if row["nomination"]["target_bundle_sha256"] == entry["bundle_sha256"] and
                _same(row["nomination"]["target_subject_ref"], subject_ref)]
    _need(bool(selected), "supplied context has no nomination for this exact norm occurrence")
    commitments = []
    for index, source in enumerate(inputs["sources"]):
        commitments.extend((
            (f"context-source-{index}-bundle", source["expected_bundle_sha256"]),
            (f"context-source-{index}-replay", norm_review_sha256(source["replay_inputs"])),
            (f"context-source-{index}-raw", hashlib.sha256(source["raw"]).hexdigest()
             if type(source["raw"]) is bytes else None),
        ))
    _need(all(pin is not None for _, pin in commitments), "complete context source bytes required")
    commitments.extend((("context-packet", inputs["expected_context_sha256"]),
                        ("context-attachments", inputs["expected_attachments_sha256"])))
    return {"status": "replayed_source_nominations_not_applicability",
            "packet_sha256": inputs["expected_context_sha256"], "packet_counts": packet["counts"],
            "target": {"bundle_sha256": entry["bundle_sha256"], "subject_ref": subject_ref,
                       "source_occurrence_ref": guide["source_occurrence_ref"], "context_ref": guide["context_ref"]},
            "nominations": selected,
            "source_commitments": [{"label": label, "sha256": pin} for label, pin in commitments],
            "typed_definition_reviews_supplied": False}, commitments


def _preflight_correspondence(inputs):
    """Reuse pure parsers before recording operation producers or replaying."""
    base = correspondence_owner
    base._parse(inputs["mapping_request_raw"], inputs["expected_mapping_request_sha256"])
    _, pins = base._snapshot(inputs["scope_report"], inputs["relational_report"], inputs["scope_replay_inputs"])
    for name in ("scope_report", "relational_report"):
        _need(pins[name]["sha256"] == inputs["expected_" + name + "_sha256"],
              "independent original report pin differs before review imports")
    replay = inputs["scope_replay_inputs"]
    for name, pin in (("raw_html", "expected_raw_sha256"), ("scope_request_raw", "expected_scope_request_sha256"),
                      ("scope_declaration_raw", "expected_scope_declaration_sha256"),
                      ("descriptor", "expected_descriptor_sha256"), ("sampling_report", "expected_sampling_report_sha256")):
        _need(pins[name]["sha256"] == replay[pin], "original correspondence replay pin differs before review imports")
    _need(type(replay["expected_raw_bytes"]) is int and replay["expected_raw_bytes"] == len(replay["raw_html"]),
          "exact original byte count required")
    scope, relational = base._owners()  # stdlib-only public modules, not their operation owners
    scope._load(replay["scope_request_raw"], replay["expected_scope_request_sha256"], "scope request")
    scope._load(replay["scope_declaration_raw"], replay["expected_scope_declaration_sha256"], "scope declaration")
    relational._parse(inputs["relational_request_raw"], inputs["expected_relational_request_sha256"])


def prepare_norm_review_evidence_v1(correspondence, *, expected_correspondence_sha256,
                                    correspondence_inputs, context_inputs):
    """Prepare a distinct unsigned interpretation subject's complete evidence."""
    _sha(expected_correspondence_sha256, "correspondence")
    _keys(correspondence_inputs, _REPLAY_FIELDS, "complete correspondence replay inputs")
    if context_inputs is not None:
        _keys(context_inputs, {"packet", "sources", "attachments", "expected_context_sha256",
                              "expected_attachments_sha256", "limits"}, "context replay inputs")
    original = {"correspondence": correspondence, "correspondence_inputs": correspondence_inputs,
                "context_inputs": context_inputs}
    detached, commitment = _snapshot(original)
    _need(norm_review_sha256(detached["correspondence"]) == expected_correspondence_sha256,
          "independently pinned complete correspondence differs")
    _preflight_correspondence(detached["correspondence_inputs"])
    owners = _owners()
    pins = _pins(owners)

    def fence():
        _need(_snapshot(original)[1] == commitment and _snapshot(detached)[1] == commitment,
              "norm review inputs changed during preparation")
        _need(_pins(owners) == pins, "norm review producers changed during preparation")

    fence()
    checked = correspondence_owner.validate_norm_scope_correspondence_v1(
        detached["correspondence"], expected_report_sha256=expected_correspondence_sha256,
        **detached["correspondence_inputs"])
    fence()
    context_evidence, external_pins = _source_context(checked, detached["context_inputs"], owners[2])
    fence()
    source = checked["source_scope"]
    obligations = [{"slot_id": row["slot_id"], "kind": "original_context", "original": row}
                   for row in source["source_context_packet"]["dependency_slots"]]
    for index, issue in enumerate(checked["retained_unresolved"]):
        obligations.append({"slot_id": "norm-issue:" + norm_review_sha256(
            [expected_correspondence_sha256, index, issue]), "kind": "original_unresolved_issue", "original": issue})
    for question in SEMANTIC_QUESTIONS:
        obligations.append({"slot_id": "norm-question:" + norm_review_sha256(
            [expected_correspondence_sha256, question]), "kind": "interpretation_question", "question": question})
    _need(len(obligations) <= MAX_OBLIGATIONS, "complete norm review obligation bound exceeded")
    root = "norm-correspondence:" + expected_correspondence_sha256
    scope_id = "norm-review-scope:" + norm_review_sha256({
        "domain": SUBJECT_SCHEMA, "correspondence_sha256": expected_correspondence_sha256,
        "source_unit": source["input_pins"]["selected_unit_ref"]})
    artifacts = []
    dependencies = owners[0]

    def artifact(identity, pin, policy=()):
        artifacts.append({"artifact_id": identity, "artifact_sha256": pin,
                          "dependency_pins": {kind: list(policy) if kind == "policy" else []
                                              for kind in dependencies.PIN_KINDS}})

    artifact(root, expected_correspondence_sha256)
    for label, observation in sorted(checked["input_pins"]["replay_inputs"].items()):
        artifact("norm-input:" + label, observation["sha256"])
    for label in ("mapping_request_raw_sha256", "relational_request_raw_sha256"):
        artifact("norm-input:" + label, checked["input_pins"][label])
    for label, pin in external_pins:
        artifact("norm-input:" + label, pin)
    artifact("norm-review-producers", norm_review_sha256(pins),
             [{"key": path, "sha256": pin} for path, pin in sorted(pins.items())])
    ids = [row["artifact_id"] for row in artifacts]
    edges = [{"dependent_id": root, "dependency_id": identity} for identity in ids[1:]]
    dependencies.build_dependency_manifest(artifacts, edges, expected_artifact_ids=ids)
    report = {
        "schema": PREPARATION_SCHEMA, "correspondence": checked,
        "correspondence_sha256": expected_correspondence_sha256,
        "graph_id": root, "graph_sha256": expected_correspondence_sha256,
        "ast_sha256": norm_review_sha256(checked["relational_fragment"]["typed_expression"]),
        "native_ast_sha256": norm_review_sha256(checked["relational_fragment"]["native_ast"]),
        "scope_id": scope_id, "obligations": obligations,
        "context_slot_ids": [row["slot_id"] for row in obligations],
        "context_evidence": context_evidence, "artifacts": artifacts, "edges": edges,
        "required_dependency_ids": ids, "producer_pins": pins,
        "original_signatures_cover_norm_review": False, "governing_definition_use": None,
        "authority": dict(FALSE_FLAGS), "training_mask": 0, "evaluation_gold_mask": 0,
        "status": "unsigned_interpretation_review_evidence_prepared",
    }
    raw = _wire(report)
    fence()
    return json.loads(raw)


def _manifest(preparation, manifest, expected_pin, required_ids, dependencies, review):
    checked = dependencies.validate_dependency_manifest(manifest, expected_manifest_sha256=expected_pin)
    for key in ("artifacts", "edges"):
        _need(_same(checked[key], preparation[key]), "review manifest differs from complete original inventory")
    ids = preparation["required_dependency_ids"]
    _need(_same(required_ids, ids) and _same(checked["expected_artifact_ids"], ids),
          "independent complete review dependency population differs")
    reachable, artifacts = review._closure(checked, preparation["graph_id"], preparation["graph_sha256"])
    _need(_same(reachable, ids), "review dependency closure differs")
    refs = [{"origin": "/artifacts/" + str(index), "reference": {
        "artifact_id": item["artifact_id"], "artifact_sha256": item["artifact_sha256"],
        "role": "norm_review_custody"}} for index, item in enumerate(preparation["artifacts"])]
    return artifacts, refs


def _subject(subject, manifest):
    _keys(subject, _SUBJECT_FIELDS, "norm review subject")
    _need(subject["schema"] == SUBJECT_SCHEMA, "distinct norm interpretation review domain required")
    binding = subject["native_binding"]
    _keys(binding, {"preparation_sha256", "correspondence_sha256", "obligations_sha256",
                    "context_evidence_sha256", "producer_pins_sha256", "source_scope_sha256",
                    "typed_expression_sha256", "native_ast_sha256", "original_issues_sha256"},
          "compact exact norm review evidence commitments")
    for key, pin in binding.items():
        _sha(pin, key)
    _need(subject["graph_sha256"] == binding["correspondence_sha256"] and
          subject["ast_sha256"] == binding["typed_expression_sha256"] and
          subject["native_ast_sha256"] == binding["native_ast_sha256"], "norm subject commitment differs")
    slots = subject["context_slot_ids"]
    _need(type(slots) is list and 0 < len(slots) <= MAX_OBLIGATIONS and
          all(type(slot) is str for slot in slots) and len(set(slots)) == len(slots),
          "complete distinct norm obligations required")
    dependencies, review, _ = _owners()
    checked = dependencies.validate_dependency_manifest(manifest,
                    expected_manifest_sha256=subject["dependency_manifest_sha256"])
    ids, artifacts = review._closure(checked, subject["graph_id"], subject["graph_sha256"])
    _need(_same(subject["required_dependency_ids"], ids), "norm subject dependency closure differs")
    refs = [{"origin": "/artifacts/" + str(index), "reference": {
        "artifact_id": item["artifact_id"], "artifact_sha256": item["artifact_sha256"],
        "role": "norm_review_custody"}} for index, item in enumerate(checked["artifacts"])]
    _need(_same(subject["dependency_artifacts"], artifacts) and
          _same(subject["graph_declared_dependency_refs"], refs), "norm review dependency binding differs")


def build_norm_review_subject_v1(preparation, dependency_manifest, *, expected_preparation_sha256,
                                expected_manifest_sha256, required_dependency_ids, **preparation_inputs):
    _sha(expected_preparation_sha256, "norm review preparation")
    original = {"preparation": preparation, "manifest": dependency_manifest,
                "required_ids": required_dependency_ids, "inputs": preparation_inputs}
    snapshot, commitment = _snapshot(original)
    _need(norm_review_sha256(snapshot["preparation"]) == expected_preparation_sha256,
          "independently pinned norm preparation differs")
    checked = prepare_norm_review_evidence_v1(**snapshot["inputs"])
    _need(_same(snapshot["preparation"], checked), "norm preparation differs from full replay")
    owners = _owners()
    pins = _pins(owners)
    artifacts, refs = _manifest(checked, snapshot["manifest"], expected_manifest_sha256,
                                snapshot["required_ids"], *owners[:2])
    candidate = checked["correspondence"]
    # Keep exact original JSON (including allowed acquisition floats and deep
    # typed ASTs) in the separately replayed preparation. The shared signing
    # engine intentionally accepts a shallower, integer-only JSON vocabulary.
    # Commit the complete evidence; do not coerce, truncate or recode its bytes.
    binding = {
        "preparation_sha256": expected_preparation_sha256,
        "correspondence_sha256": checked["correspondence_sha256"],
        "obligations_sha256": norm_review_sha256(checked["obligations"]),
        "context_evidence_sha256": norm_review_sha256(checked["context_evidence"]),
        "producer_pins_sha256": norm_review_sha256(checked["producer_pins"]),
        "source_scope_sha256": norm_review_sha256(candidate["source_scope"]),
        "typed_expression_sha256": checked["ast_sha256"], "native_ast_sha256": checked["native_ast_sha256"],
        "original_issues_sha256": norm_review_sha256(candidate["retained_unresolved"]),
    }
    subject = {"schema": SUBJECT_SCHEMA,
               **{key: checked[key] for key in ("graph_id", "graph_sha256", "ast_sha256",
                  "native_ast_sha256", "scope_id", "context_slot_ids")},
               "dependency_manifest_sha256": expected_manifest_sha256,
               "required_dependency_ids": snapshot["required_ids"], "dependency_artifacts": artifacts,
               "graph_declared_dependency_refs": refs, "native_binding": binding}
    _subject(subject, snapshot["manifest"])
    owners[1].wire(subject)
    raw = _wire(subject)
    _need(_snapshot(original)[1] == commitment and _snapshot(snapshot)[1] == commitment,
          "subject inputs changed during preparation")
    _need(_pins(owners) == pins, "subject producer changed during preparation")
    return json.loads(raw)


def assess_norm_reviews_v1(subject, registry, policy, reviews, dependency_manifest, *,
        preparation, expected_preparation_sha256, correspondence, expected_correspondence_sha256,
        correspondence_inputs, context_inputs, expected_subject_sha256, expected_registry_sha256,
        expected_policy_sha256, expected_reviews_sha256, expected_manifest_sha256,
        at_time_utc, observed_artifact_sha256s, observed_pins, evidence_artifacts):
    """Authenticate statements under explicit selected trust; admit no meanings."""
    original = dict(subject=subject, registry=registry, policy=policy, reviews=reviews, preparation=preparation,
        dependency_manifest=dependency_manifest, correspondence=correspondence,
        correspondence_inputs=correspondence_inputs, context_inputs=context_inputs,
        observed_artifact_sha256s=observed_artifact_sha256s, observed_pins=observed_pins,
        evidence_artifacts=evidence_artifacts)
    offered, commitment = _snapshot(original)
    _sha(expected_subject_sha256, "norm review subject")
    _need(norm_review_sha256(offered["subject"]) == expected_subject_sha256, "independently pinned norm subject differs")
    checked = build_norm_review_subject_v1(offered["preparation"], offered["dependency_manifest"],
        expected_preparation_sha256=expected_preparation_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
        required_dependency_ids=offered["subject"]["required_dependency_ids"],
        correspondence=offered["correspondence"], expected_correspondence_sha256=expected_correspondence_sha256,
        correspondence_inputs=offered["correspondence_inputs"], context_inputs=offered["context_inputs"])
    _need(_same(checked, offered["subject"]), "norm subject differs from full replay")
    owners = _owners()
    pins = _pins(owners)
    review = owners[1]
    domain = review._ReviewDomain(SUBJECT_SCHEMA, CLAIM_SCHEMA, ACTION, AUDIENCE, SCHEMA, _subject, MAX_OBLIGATIONS)
    result = review._assess_reviews(checked, offered["registry"], offered["policy"], offered["reviews"],
        offered["dependency_manifest"], domain=domain, expected_subject_sha256=expected_subject_sha256,
        expected_registry_sha256=expected_registry_sha256, expected_policy_sha256=expected_policy_sha256,
        expected_reviews_sha256=expected_reviews_sha256, expected_manifest_sha256=expected_manifest_sha256,
        at_time_utc=at_time_utc, observed_artifact_sha256s=offered["observed_artifact_sha256s"],
        observed_pins=offered["observed_pins"], evidence_artifacts=offered["evidence_artifacts"])
    body = {key: value for key, value in result.items() if key != "assessment_sha256"}
    body.update(norm_interpretation_ready=False,
        norm_readiness_blockers=["source_scope_partial_or_unassessed", "original_source_issues_unresolved",
                                "governing_definition_applicability_not_verified", "independent_semantic_validation_required"],
        original_unresolved=offered["preparation"]["correspondence"]["retained_unresolved"],
        original_context_slots=offered["preparation"]["correspondence"]["source_scope"]["source_context_packet"]["dependency_slots"],
        original_signatures_cover_norm_review=False, governing_definition_use=None,
        authority=dict(FALSE_FLAGS), training_mask=0, evaluation_gold_mask=0,
        **FALSE_FLAGS)
    report = {**body, "assessment_sha256": norm_review_sha256(body)}
    raw = _wire(report)
    _need(_snapshot(original)[1] == commitment and _snapshot(offered)[1] == commitment,
          "norm review inputs changed during authentication")
    _need(_pins(owners) == pins, "norm review producer changed during authentication")
    return json.loads(raw)


def validate_norm_review_assessment_v1(report, *args, **kwargs):
    offered = _wire(report)
    regenerated = assess_norm_reviews_v1(*args, **kwargs)
    _need(offered == _wire(regenerated), "norm review assessment differs from complete replay")
    return regenerated


__all__ = ["prepare_norm_review_evidence_v1", "build_norm_review_subject_v1",
           "assess_norm_reviews_v1", "validate_norm_review_assessment_v1", "norm_review_sha256"]
