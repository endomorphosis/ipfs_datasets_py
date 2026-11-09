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


# This unsigned companion has no subject, claim, action or signing audience.
# The original relational review and every original signing domain stay strict.
COUNTED_PREPARATION_SCHEMA = "legal-counted-norm-review-evidence/v1"
COUNTED_PROFILE = "unsigned-source-counted-frame-review/v1"
_COUNTED_REPLAY_FIELDS = {
    "scope_report", "counted_report", "join_request_raw", "expected_join_request_sha256",
    "expected_scope_report_sha256", "expected_counted_report_sha256", "scope_replay_inputs",
    "counted_request_raw", "expected_counted_request_sha256",
}
_COUNTED_REVIEW_OWNER_PINS = None
_COUNTED_DEPENDENCIES_SHA256 = "86cb7c3b09102a94237d0455d610d437e558cca4250242201becd06c775ca2e8"


def _counted_review_preflight(correspondence, inputs):
    """Reuse bounded pure request parsers before discovering operation owners."""
    _keys(inputs, _COUNTED_REPLAY_FIELDS, "complete counted correspondence replay inputs")
    from . import legal_source_typed_norm_join_v1 as join
    _need(type(correspondence) is dict
          and correspondence.get("schema") == join.SCHEMA_V2
          and correspondence.get("profile") == join.PROFILE_V2,
          "explicit counted-only correspondence required")
    request = join._request_for_schema(inputs["join_request_raw"],
        inputs["expected_join_request_sha256"], join.REQUEST_SCHEMA_V2)
    join._pinned_copy(inputs["scope_report"], inputs["expected_scope_report_sha256"],
                      "complete scope report", join.MAX_SCOPE_REPORT_BYTES)
    join._pinned_copy(inputs["counted_report"], inputs["expected_counted_report_sha256"],
                      "complete counted report", join.MAX_COUNTED_REPORT_BYTES)
    replay = join._replay_inputs(inputs["scope_replay_inputs"])
    _need(request["selected_unit_ref"] == replay["selected_unit_ref"],
          "counted review selected unit differs from original replay")
    source_scope, counted = join._counted_owners()  # Public stdlib-only modules.
    source_scope._load(replay["scope_request_raw"], replay["expected_scope_request_sha256"],
                       "scope request")
    source_scope._load(replay["scope_declaration_raw"], replay["expected_scope_declaration_sha256"],
                       "scope declaration")
    counted._parse(inputs["counted_request_raw"], inputs["expected_counted_request_sha256"])


def _counted_review_owners():
    from . import legal_source_typed_norm_join_v1, legal_graph_dependencies
    return legal_source_typed_norm_join_v1, legal_graph_dependencies


def _counted_review_pins(owners, correspondence, inputs):
    """Check actual owner closure before offered producer paths affect reads."""
    global _COUNTED_REVIEW_OWNER_PINS
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "counted review producer changed since import")
    _need(hashlib.sha256(Path(correspondence_owner.__file__).read_bytes()).hexdigest() == _BASE_PIN,
          "counted review scalar/snapshot base changed since import")
    join, dependencies = owners
    trusted = join._counted_producer_pins(*join._counted_owners(),
        inputs["scope_report"], inputs["counted_report"])
    _need(type(correspondence.get("producer_pins")) is dict
          and correspondence["producer_pins"] == trusted,
          "counted correspondence producer commitments differ from trusted owners")
    dependency_path = Path(__file__).resolve().with_name("legal_graph_dependencies.py")
    _need(Path(dependencies.__file__).resolve() == dependency_path,
          "known sibling counted review dependency owner required")
    _need(hashlib.sha256(dependency_path.read_bytes()).hexdigest() == _COUNTED_DEPENDENCIES_SHA256,
          "counted review dependency producer differs from reviewed baseline")
    pins = dict(trusted)
    direct = {
        str(Path(__file__).resolve()): _SELF_PIN,
        str(Path(correspondence_owner.__file__).resolve()): _BASE_PIN,
        str(dependency_path): _COUNTED_DEPENDENCIES_SHA256,
    }
    for path, expected in direct.items():
        _need(path not in pins or pins[path] == expected,
              "shared counted review producer commitments differ")
        pins[path] = expected
    join._check_producer_pins(pins)
    if _COUNTED_REVIEW_OWNER_PINS is None:
        _COUNTED_REVIEW_OWNER_PINS = dict(pins)
    _need(pins == _COUNTED_REVIEW_OWNER_PINS,
          "counted review producers changed since first use")
    return pins


def _counted_review_obligations(checked, expected_correspondence_sha256):
    """Keep every declared obligation in original order without deduplication."""
    obligations, seen = [], set()

    def append(kind, original, index, *, original_slot=None, question=False):
        _need(len(obligations) < MAX_OBLIGATIONS,
              "complete counted review obligation bound exceeded; no truncation")
        slot = original_slot if original_slot is not None else "counted-norm-review:" + norm_review_sha256([
            COUNTED_PREPARATION_SCHEMA, expected_correspondence_sha256, kind, index, original])
        _need(type(slot) is str and bool(slot) and slot not in seen,
              "distinct complete counted review obligation identities required")
        seen.add(slot)
        obligations.append({"slot_id": slot, "kind": kind,
                            "question" if question else "original": original})

    source = checked["source_scope_report"]
    for index, row in enumerate(source["source_context_packet"]["dependency_slots"]):
        append("original_context", row, index, original_slot=row["slot_id"])
    for index, issue in enumerate(checked["original_unresolved"]):
        append("original_unresolved_issue", issue, index)
    for index, issue in enumerate(checked["introduced_unresolved"]):
        append("introduced_unresolved_issue", issue, index)
    for index, assumption in enumerate(checked["counted_frame_report"]["assumptions"]):
        append("authored_counted_assumption", assumption, index)
    for index, question in enumerate(SEMANTIC_QUESTIONS):
        append("interpretation_question", question, index, question=True)
    return obligations


def _counted_review_artifacts(checked, expected_correspondence_sha256, pins, dependencies):
    """Declare original input custody, not a legal graph or current observation."""
    prefix = "counted-norm-correspondence:" + expected_correspondence_sha256
    original = checked["input_pins"]
    source = original["source_scope_input_pins"]
    sampler = source["sampler_replay_inputs"]
    items = [
        ("scope-report", original["scope_report_full_canonical_sha256"]),
        ("counted-report", original["counted_report_full_canonical_sha256"]),
        ("join-request-raw", original["join_request_raw_sha256"]),
        ("counted-request-raw", original["counted_request_raw_sha256"]),
        ("sampling-report", source["sampling_report_full_canonical_sha256"]),
        ("source-html", sampler["expected_raw_sha256"]),
        ("source-descriptor", sampler["expected_descriptor_sha256"]),
        ("scope-request-raw", source["scope_request_raw_sha256"]),
        ("scope-declaration-raw", source["scope_declaration_raw_sha256"]),
        ("selected-source-unit", source["selected_unit_ref"]["sha256"]),
        ("review-producers", norm_review_sha256(pins)),
    ]
    artifacts = []

    def artifact(identity, pin, *, policy=()):
        _sha(pin, "counted review dependency artifact")
        artifacts.append({"artifact_id": identity, "artifact_sha256": pin,
            "dependency_pins": {kind: list(policy) if kind == "policy" else []
                                for kind in dependencies.PIN_KINDS}})

    artifact(prefix, expected_correspondence_sha256)
    for label, pin in items:
        artifact(prefix + ":" + label, pin, policy=(
            [{"key": path, "sha256": expected} for path, expected in sorted(pins.items())]
            if label == "review-producers" else ()))
    identities = [row["artifact_id"] for row in artifacts]
    edges = [{"dependent_id": prefix, "dependency_id": identity} for identity in identities[1:]]
    return artifacts, edges, identities


def prepare_counted_norm_review_evidence_v1(correspondence, *, expected_correspondence_sha256,
                                           correspondence_inputs):
    """Prepare an unsigned counted-fragment inventory through full join replay.

    External contextual nominations and all signing/assessment entry points are
    deliberately absent. The original source's open context remains evidence.
    """
    _sha(expected_correspondence_sha256, "counted correspondence")
    _keys(correspondence_inputs, _COUNTED_REPLAY_FIELDS,
          "complete counted correspondence replay inputs")
    original = {"correspondence": correspondence, "correspondence_inputs": correspondence_inputs}
    detached, commitment = _snapshot(original)
    _need(norm_review_sha256(detached["correspondence"]) == expected_correspondence_sha256,
          "independently pinned complete counted correspondence differs")
    _counted_review_preflight(detached["correspondence"], detached["correspondence_inputs"])
    owners = _counted_review_owners()
    pins = _counted_review_pins(owners, detached["correspondence"], detached["correspondence_inputs"])

    def fence():
        _need(_snapshot(original)[1] == commitment and _snapshot(detached)[1] == commitment,
              "counted review inputs changed during preparation")
        _need(_counted_review_pins(owners, detached["correspondence"],
                                 detached["correspondence_inputs"]) == pins,
              "counted review producers changed during preparation")

    fence()
    join, dependencies = owners
    checked = join.validate_source_typed_norm_join_v2(detached["correspondence"],
        expected_report_sha256=expected_correspondence_sha256,
        **detached["correspondence_inputs"])
    fence()
    obligations = _counted_review_obligations(checked, expected_correspondence_sha256)
    artifacts, edges, identities = _counted_review_artifacts(
        checked, expected_correspondence_sha256, pins, dependencies)
    fence()
    manifest = dependencies.build_dependency_manifest(artifacts, edges,
        expected_artifact_ids=identities)
    fence()
    manifest = dependencies.validate_dependency_manifest(manifest,
        expected_manifest_sha256=manifest["manifest_sha256"])
    fence()
    source = checked["source_scope_report"]
    ledger = checked["provenance_ledger"]
    report = {
        "schema": COUNTED_PREPARATION_SCHEMA, "profile": COUNTED_PROFILE,
        "status": "unsigned_counted_fragment_review_evidence_prepared",
        "correspondence": checked, "correspondence_sha256": expected_correspondence_sha256,
        "selected_unit_ref": source["input_pins"]["selected_unit_ref"],
        "typed_inventory": {"path": "/correspondence/provenance_ledger",
            "sha256": norm_review_sha256(ledger), "rows": len(ledger),
            "nodes": checked["counted_frame_report"]["counts"]["nodes"],
            "binders": len(checked["counted_frame_report"]["binder_ledger"])},
        "obligations": obligations, "obligation_ids": [row["slot_id"] for row in obligations],
        "original_context_slot_ids": [row["slot_id"]
            for row in source["source_context_packet"]["dependency_slots"]],
        "dependency_manifest": manifest, "required_dependency_ids": identities,
        "producer_pins": pins, "external_context_not_supplied": True,
        "external_context_nominations_applied": False,
        "original_signatures_cover_counted_review": False,
        "selected_interpretation": None, "governing_definition_use": None,
        "formal_norm_ast": None, "lowered_IR": None, "native_output_for_source": None,
        "graph": None, "accepted_lookup": None,
        "norm_interpretation_ready": False, "native_build_executed": False,
        "authority": {**FALSE_FLAGS, **checked["authority"]},
        "training_mask": 0, "evaluation_gold_mask": 0,
        "human_reviews": 0, "signatures_constructed": 0, "admissions": 0,
        "model_calls": 0, "training_calls": 0, "native_processes": 0,
        "limitations": [
            "The complete counted correspondence and its55 syntax/binder rows remain an unreviewed partial hypothesis, not a complete statutory norm.",
            "Original context, source issues, introduced groups and authored counted assumptions remain separate obligations in exact order; similar wording is not deduplicated.",
            "The returned dependency manifest binds declared artifacts and producer identities only. Its reverse index accepts no fabricated current observations or legal completeness claim.",
            "No native AST, native mapping, signing subject or new signing domain is manufactured for the counted fragment.",
            "Existing relational review, definition applicability/application and native/signature consumers retain their original closed contracts.",
            "No external context nomination, governing choice, review authentication, graph admission, model, training or Lean execution is supplied.",
        ],
    }
    raw = _wire(report)
    fence()
    return json.loads(raw)


def validate_counted_norm_review_evidence_v1(report, correspondence, *, expected_report_sha256,
                                            **preparation_inputs):
    """Require an independent unsigned report pin and complete original replay."""
    _sha(expected_report_sha256, "counted review evidence")
    _keys(preparation_inputs, {"expected_correspondence_sha256", "correspondence_inputs"},
          "complete counted review preparation inputs")
    original = {"report": report, "correspondence": correspondence, "inputs": preparation_inputs}
    detached, commitment = _snapshot(original)
    _need(norm_review_sha256(detached["report"]) == expected_report_sha256,
          "independently pinned complete counted review evidence differs")
    _sha(detached["inputs"]["expected_correspondence_sha256"], "counted correspondence")
    _need(norm_review_sha256(detached["correspondence"]) ==
          detached["inputs"]["expected_correspondence_sha256"],
          "independently pinned complete counted correspondence differs")
    inputs = detached["inputs"]["correspondence_inputs"]
    _counted_review_preflight(detached["correspondence"], inputs)
    owners = _counted_review_owners()
    pins = _counted_review_pins(owners, detached["correspondence"], inputs)

    def fence():
        _need(_snapshot(original)[1] == commitment and _snapshot(detached)[1] == commitment,
              "counted review validation inputs changed during replay")
        _need(_counted_review_pins(owners, detached["correspondence"], inputs) == pins,
              "counted review producers changed during validation")

    fence()
    regenerated = prepare_counted_norm_review_evidence_v1(
        detached["correspondence"], **detached["inputs"])
    fence()
    _need(_same(detached["report"], regenerated),
          "counted review evidence differs from complete original replay")
    fence()
    return regenerated


__all__ += ["prepare_counted_norm_review_evidence_v1", "validate_counted_norm_review_evidence_v1"]


# Parent review is unsigned custody/worksheet evidence. Existing relational
# signing domains and the separate counted profile keep their closed contracts.
PARENT_PREPARATION_SCHEMA = "legal-parent-norm-review-evidence/v1"
PARENT_REVIEW_PROFILE = "unsigned-parent-literal-occurrence-review/v1"
_PARENT_REVIEW_OWNER_PINS = None
_PARENT_REVIEW_DEPENDENCIES_SHA256 = "86cb7c3b09102a94237d0455d610d437e558cca4250242201becd06c775ca2e8"
_PARENT_CONTEXT_REQUIREMENTS = (
    "definition", "authority", "antecedent", "shared_qualifier", "temporal_origin", "referenced_provision",
)
_PARENT_SCALAR_WIRE = correspondence_owner._scalar_wire


def _parent_review_fingerprint(value):
    """Verify the existing snapshot commitment without operation callbacks.

    Retain the original finite, type-separated recipe and limits. The trusted
    scalar encoder is captured directly, bypassing the instrumentable general
    correspondence encoder used by the original detaching snapshot.
    """
    budget, nodes = MAX_INPUT_BYTES, 1_500_000
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
            _need(len(item) <= nodes and all(type(key) is str for key in item),
                  "ordinary review mapping required")
            token(b"d", str(len(item)).encode())
            for key in sorted(item):
                visit(key, depth + 1)
                visit(item[key], depth + 1)
        elif type(item) is list:
            _need(len(item) <= nodes, "bounded review list required")
            token(b"l", str(len(item)).encode())
            for child in item:
                visit(child, depth + 1)
        elif type(item) is bytes:
            _need(len(item) <= min(budget, 32 * 1024**2), "bounded exact review bytes required")
            token(b"b", item)
        else:
            token(b"j", _PARENT_SCALAR_WIRE(item, min(budget, MAX_INPUT_BYTES)))

    visit(value, 0)
    return digest.hexdigest()


def _parent_review_pure_wire(value):
    """Bound ordinary values, then encode directly for the final custody check."""
    _parent_review_fingerprint(value)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    _need(len(raw) <= MAX_BYTES, "complete JSON byte bound exceeded")
    return raw


def _parent_review_owners():
    from . import legal_graph_dependencies
    from . import legal_source_norm_scope_v1
    return correspondence_owner, legal_graph_dependencies, legal_source_norm_scope_v1


def _parent_review_pins(owners):
    """Discover trusted selected owners; never open an offered producer path."""
    global _PARENT_REVIEW_OWNER_PINS
    base, dependencies, source = owners
    _need(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_PIN,
          "parent review producer changed since import")
    _need(hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest() == _BASE_PIN,
          "parent correspondence producer changed since review import")
    pins = base._parent_correspondence_pins(base._owners())
    dependency_path = Path(__file__).resolve().with_name("legal_graph_dependencies.py")
    _need(Path(dependencies.__file__).resolve() == dependency_path
          and hashlib.sha256(dependency_path.read_bytes()).hexdigest() == _PARENT_REVIEW_DEPENDENCIES_SHA256,
          "known parent review dependency owner differs from reviewed baseline")
    _need(str(Path(source.__file__).resolve()) in pins,
          "genuine parent scope utility owner absent from selected closure")
    pins[str(dependency_path)] = _PARENT_REVIEW_DEPENDENCIES_SHA256
    pins[str(Path(__file__).resolve())] = _SELF_PIN
    if _PARENT_REVIEW_OWNER_PINS is None:
        _PARENT_REVIEW_OWNER_PINS = dict(pins)
    _need(pins == _PARENT_REVIEW_OWNER_PINS,
          "parent review selected producers changed since first use")
    return dict(pins)


def _parent_review_preflight(correspondence, inputs):
    """Use only existing bounded pure parsers before operation dependencies."""
    base = correspondence_owner
    _keys(inputs, _REPLAY_FIELDS, "complete original parent correspondence inputs")
    _need(type(correspondence) is dict and correspondence.get("schema") == base.SCHEMA_V2
          and correspondence.get("profile") == "parent-literal-occurrence-authored-correspondence/v2",
          "explicit parent correspondence v2 required")
    parsed = {"mapping_request": base._parse(inputs["mapping_request_raw"],
        inputs["expected_mapping_request_sha256"], request_schema=base.REQUEST_SCHEMA_V2)}
    source, relational = base._owners()  # Both are stdlib-only public modules.
    copied, commitments = base._parent_correspondence_snapshot(
        inputs["scope_report"], inputs["relational_report"], inputs["scope_replay_inputs"], source)
    for name in ("scope_report", "relational_report"):
        _sha(inputs["expected_" + name + "_sha256"], name)
        _need(commitments[name]["sha256"] == inputs["expected_" + name + "_sha256"],
              "independent parent correspondence input report pin differs")
        _need(parsed["mapping_request"][name + "_sha256"] == inputs["expected_" + name + "_sha256"],
              "parent mapping request binds another input report")
    _need(copied["scope_report"].get("schema") == source.PARENT_SCHEMA
          and copied["scope_report"].get("profile") == source.PARENT_PROFILE,
          "whole selected parent literal scope profile required")
    replay = copied["scope_replay_inputs"]
    parsed["scope_request"] = source._load(replay["scope_request_raw"],
        replay["expected_scope_request_sha256"], "scope request")
    parsed["scope_declaration"] = source._load(replay["scope_declaration_raw"],
        replay["expected_scope_declaration_sha256"], "scope declaration")
    parsed["relational_request"] = relational._parse(inputs["relational_request_raw"],
        inputs["expected_relational_request_sha256"])
    _wire(parsed)
    return parsed


def _parent_review_identity(checked):
    source = checked["source_scope"]
    binding = source["parent_source_binding"]
    context, occurrence = binding["context"], binding["selector"]
    _need(_same(context, source["source_context_record"])
          and _same(occurrence, source["source_selector"]),
          "retained parent source/context bodies differ")
    _need(context["availability"] == "required_unavailable"
          and context["missing_requirements"] == list(_PARENT_CONTEXT_REQUIREMENTS),
          "all six original parent context requirements must remain open in order")
    identity = {"schema": "legal-parent-norm-review-source-identity/v1",
        "parent_manifest_cid": binding["parent_manifest_cid"],
        "source_version_cid": binding["source_version"]["record_cid"],
        "source_occurrence_cid": occurrence["record_cid"],
        "companion_record_cid": binding["companion_record"]["record_cid"],
        "context_record_cid": context["record_cid"],
        "source_binding_sha256": binding["source_binding_sha256"]}
    _need(identity["source_version_cid"] == occurrence["source_version_cid"]
          and identity["source_occurrence_cid"] == source["input_pins"]["source_occurrence_cid"]
          and identity["companion_record_cid"] == source["input_pins"]["companion_record_cid"]
          and identity["parent_manifest_cid"] == source["input_pins"]["parent_manifest_cid"],
          "explicit parent review source identities differ")
    return identity, context


def _parent_review_obligations(checked, correspondence_sha256, identity, context):
    obligations, seen = [], set()

    def append(row):
        _need(len(obligations) < MAX_OBLIGATIONS and row["slot_id"] not in seen,
              "complete distinct parent review obligation bound exceeded; no truncation")
        seen.add(row["slot_id"])
        obligations.append(row)

    for ordinal, requirement in enumerate(context["missing_requirements"]):
        source = {key: identity[key] for key in
                  ("source_version_cid", "source_occurrence_cid", "context_record_cid")}
        slot_identity = {"schema": "legal-parent-norm-review-context-id/v1", **source,
                         "requirement_ordinal": ordinal, "missing_requirement": requirement}
        append({"slot_id": "parent-norm-context:" + norm_review_sha256(slot_identity),
            "kind": "original_parent_context",
            "original": {"schema": "legal-parent-norm-review-context-requirement/v1", **source,
                "requirement_ordinal": ordinal, "missing_requirement": requirement, "context": context}})
    for ordinal, issue in enumerate(checked["retained_unresolved"]):
        append({"slot_id": "parent-norm-issue:" + norm_review_sha256(
            [PARENT_PREPARATION_SCHEMA, correspondence_sha256, ordinal, issue]),
            "kind": "original_unresolved_issue", "original": issue})
    for ordinal, question in enumerate(SEMANTIC_QUESTIONS):
        append({"slot_id": "parent-norm-question:" + norm_review_sha256(
            [PARENT_PREPARATION_SCHEMA, correspondence_sha256, ordinal, question]),
            "kind": "interpretation_question", "question": question})
    return obligations


def _parent_review_render(checked, correspondence_sha256, pins, dependencies, returned):
    identity, context = _parent_review_identity(checked)
    obligations = _parent_review_obligations(checked, correspondence_sha256, identity, context)
    root = "parent-norm-correspondence:" + correspondence_sha256
    artifacts = []

    def artifact(label, pin, *, policy=()):
        _sha(pin, "parent review declared custody artifact")
        artifacts.append({"artifact_id": root if label is None else root + ":" + label,
            "artifact_sha256": pin, "dependency_pins": {
                kind: list(policy) if kind == "policy" else [] for kind in dependencies.PIN_KINDS}})

    artifact(None, correspondence_sha256)
    # CIDs remain identities. This SHA commits the explicitly retained identity
    # JSON; it is not presented as a CID payload or original-source byte digest.
    artifact("source-identity-json", norm_review_sha256(identity))
    for ordinal, (label, observation) in enumerate(sorted(checked["input_pins"]["replay_inputs"].items())):
        artifact("input-" + str(ordinal) + ":" + label, observation["sha256"])
    for label in ("mapping_request_raw_sha256", "relational_request_raw_sha256"):
        artifact(label, checked["input_pins"][label])
    artifact("review-producers", norm_review_sha256(pins),
             policy=[{"key": path, "sha256": pin} for path, pin in sorted(pins.items())])
    identities = [row["artifact_id"] for row in artifacts]
    edges = [{"dependent_id": root, "dependency_id": identifier} for identifier in identities[1:]]
    manifest = dependencies.build_dependency_manifest(artifacts, edges, expected_artifact_ids=identities)
    raw = _wire(manifest)
    returned.append((manifest, raw))
    verified = dependencies.validate_dependency_manifest(manifest,
        expected_manifest_sha256=manifest["manifest_sha256"])
    _need(_wire(verified) == raw, "parent review custody manifest replay differs")
    returned.append((verified, raw))
    manifest = json.loads(raw)
    return {"schema": PARENT_PREPARATION_SCHEMA, "profile": PARENT_REVIEW_PROFILE,
        "status": "unsigned_parent_literal_review_evidence_prepared",
        "correspondence": checked, "correspondence_sha256": correspondence_sha256,
        "source_identity": identity, "source_identity_sha256": norm_review_sha256(identity),
        "original_parent_context": context, "obligations": obligations,
        "obligation_ids": [row["slot_id"] for row in obligations],
        "context_obligation_ids": [row["slot_id"] for row in obligations[:6]],
        "typed_context_inventory": checked["typed_context_inventory"],
        "source_rows": checked["request"]["source_rows"],
        "ast_sha256": norm_review_sha256(checked["relational_fragment"]["typed_expression"]),
        "native_ast_sha256": norm_review_sha256(checked["relational_fragment"]["native_ast"]),
        "dependency_manifest": manifest, "required_dependency_ids": identities,
        "input_commitments": checked["input_pins"]["replay_inputs"], "producer_pins": pins,
        "counts": {"original_parent_context": 6, "original_unresolved_issues": len(checked["retained_unresolved"]),
                   "interpretation_questions": len(SEMANTIC_QUESTIONS), "obligations": len(obligations)},
        "subject": None, "signature": None, "clock": None, "registry": None,
        "external_context_not_supplied": True, "external_context_nominations_applied": False,
        "original_signatures_cover_parent_review": False,
        "selected_interpretation": None, "accepted_interpretation": None, "governing_definition_use": None,
        "norm_interpretation_ready": False, "authority": dict(FALSE_FLAGS),
        "semantic_mask": 0, "consumer_mask": 0, "training_mask": 0, "evaluation_gold_mask": 0,
        "human_reviews": 0, "signatures_constructed": 0, "admissions": 0,
        "model_calls": 0, "training_calls": 0, "native_processes": 0,
        "limitations": [
            "Context obligations are explicitly derived from genuine parent context provenance; they are not original HTML dependency slots or verified legal dependencies.",
            "The whole selected literal occurrence may be a fragment or unclassified region. Edition, all six context requirements and caller issues remain unresolved.",
            "The complete authored correspondence and seven existing semantic questions are retained without selecting an interpretation or claiming exhaustive legal coverage.",
            "Dependency SHA values commit exact declared input bytes, JSON and producers. Source CIDs are retained in explicit identity JSON, not treated as source-byte SHA256 values.",
            "No signing subject, registry, clock, signature, authenticated response, content adjudication, graph admission, model, training or Lean process is supplied.",
        ]}


def _parent_review_operation(correspondence, expected_correspondence_sha256, correspondence_inputs,
                             *, offered=None, expected_report_sha256=None, validating=False):
    _sha(expected_correspondence_sha256, "complete parent correspondence")
    original = dict(correspondence=correspondence, expected_correspondence_sha256=expected_correspondence_sha256,
                    correspondence_inputs=correspondence_inputs, offered=offered,
                    expected_report_sha256=expected_report_sha256)
    detached, commitment = _snapshot(original)
    correspondence_raw = _wire(detached["correspondence"])
    _need(hashlib.sha256(correspondence_raw).hexdigest() == expected_correspondence_sha256,
          "independently pinned complete parent correspondence differs")
    if validating:
        _sha(expected_report_sha256, "complete unsigned parent review evidence")
        offered_raw = _wire(detached["offered"])
        _need(hashlib.sha256(offered_raw).hexdigest() == expected_report_sha256,
              "independently pinned unsigned parent review evidence differs")
        _need(type(detached["offered"]) is dict
              and detached["offered"].get("schema") == PARENT_PREPARATION_SCHEMA
              and detached["offered"].get("profile") == PARENT_REVIEW_PROFILE,
              "explicit unsigned parent review evidence profile required")
    else:
        offered_raw = None
    parsed = _parent_review_preflight(detached["correspondence"], detached["correspondence_inputs"])
    parsed_raw = _wire(parsed)
    owners = _parent_review_owners()
    base, dependencies, source = owners
    pins = _parent_review_pins(owners)
    trusted = base._parent_correspondence_pins(base._owners())
    _need(_same(detached["correspondence"].get("producer_pins"), trusted),
          "parent correspondence producer commitments differ from trusted owners")
    opening = checked = result = serialized = opening_raw = None
    returned = []
    replay_started = False
    primary = None
    encoder = lambda value, maximum: _wire(value)  # Existing fixed8MiB recipe.

    def input_fence():
        _need(_parent_review_fingerprint(original) == commitment
              and _parent_review_fingerprint(detached) == commitment,
              "parent review caller or detached inputs changed during operation")
        _need(_parent_review_pure_wire(parsed) == parsed_raw,
              "parent review parsed requests changed during operation")

    def fence():
        _need(_parent_review_pins(owners) == pins, "parent review producers changed during operation")
        input_fence()

    def pure_returned_fence():
        if opening_raw is not None:
            _need(_parent_review_pure_wire(opening) == opening_raw
                  and _parent_review_pure_wire(checked) == opening_raw,
                  "parent review returned correspondence changed during operation")
        for value, raw in returned:
            _need(_parent_review_pure_wire(value) == raw,
                  "parent review retained dependency or closing return changed during operation")

    def returned_fence():
        if opening_raw is not None:
            source._parent_serialized_fence(opening, opening_raw, MAX_BYTES, encoder)
            source._parent_serialized_fence(checked, opening_raw, MAX_BYTES, encoder)
        for value, raw in returned:
            source._parent_serialized_fence(value, raw, MAX_BYTES, encoder)

    def closing_replay():
        if replay_started:
            closing = base.validate_norm_scope_correspondence_v2(detached["correspondence"],
                expected_report_sha256=expected_correspondence_sha256, **detached["correspondence_inputs"])
            source._parent_serialized_fence(closing, correspondence_raw, MAX_BYTES, encoder)
            returned.append((closing, correspondence_raw))

    def output_fence():
        if serialized is not None:
            def final_encoder(value, maximum):
                raw = encoder(value, maximum)
                input_fence()
                pure_returned_fence()
                return raw
            source._parent_serialized_fence(result, serialized, MAX_BYTES, final_encoder)

    try:
        fence()
        replay_started = True
        opening = base.validate_norm_scope_correspondence_v2(detached["correspondence"],
            expected_report_sha256=expected_correspondence_sha256, **detached["correspondence_inputs"])
        opening_raw = _wire(opening)
        _need(opening_raw == correspondence_raw, "validated parent correspondence changed after return")
        checked = json.loads(opening_raw)
        fence()
        result = _parent_review_render(checked, expected_correspondence_sha256, pins, dependencies, returned)
        serialized = _wire(result)
        _need(not validating or serialized == offered_raw,
              "unsigned parent review evidence differs from complete original regeneration")
        result = json.loads(serialized)
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        source._parent_finish((fence, returned_fence, closing_replay, fence,
                               returned_fence, fence, output_fence), primary)


def prepare_parent_norm_review_evidence_v1(correspondence, *, expected_correspondence_sha256,
                                          correspondence_inputs):
    """Prepare unsigned parent review custody; apply no meaning or trust."""
    return _parent_review_operation(correspondence, expected_correspondence_sha256, correspondence_inputs)


def validate_parent_norm_review_evidence_v1(report, correspondence, *, expected_report_sha256,
                                           expected_correspondence_sha256, correspondence_inputs):
    """Regenerate the entire unsigned profile against original parent inputs."""
    return _parent_review_operation(correspondence, expected_correspondence_sha256, correspondence_inputs,
        offered=report, expected_report_sha256=expected_report_sha256, validating=True)


__all__ += ["prepare_parent_norm_review_evidence_v1", "validate_parent_norm_review_evidence_v1"]
