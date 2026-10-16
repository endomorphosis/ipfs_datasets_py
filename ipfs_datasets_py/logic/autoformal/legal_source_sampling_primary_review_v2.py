"""Prepare an unsigned definition review that binds declared primary evidence.

The original association and source subject are replayed unchanged. A fresh
dependency manifest and plain V2 definition subject bind the added evidence;
old signatures cannot cover this new subject. This owner supplies no source
equivalence decision, trust registry, signer, assessment or legal admission.
Public import loads only standard-library modules and starts no operation owner.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re


SCHEMA = "legal-source-sampling-primary-definition-review-envelope/v2"
PREPARATION_SCHEMA = "legal-source-sampling-primary-definition-review-preparation/v2"
PROFILE = "unsigned-association-bound-v2-definition-review/v1"
MAX_ENVELOPE_BYTES = 4 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 2_000_000
MAX_ARTIFACTS = 4096
MAX_EDGES = 16384
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ENVELOPE_FIELDS = {"schema", "profile", "preparation", "subject", "dependency_manifest"}
_REPLAY_FIELDS = {
    "expected_correspondence_sha256", "correspondence_replay_inputs", "mapping_raw",
    "expected_mapping_file_sha256", "expected_index_sha256",
}
_CORRESPONDENCE_REPLAY_FIELDS = {
    "expected_binding_sha256", "expected_subject_sha256", "binding_replay_inputs",
    "candidate_inputs", "expected_candidate_pin", "context_inputs",
    "expected_context_population", "dependency_manifest", "expected_manifest_sha256",
    "required_dependency_ids",
}
UNRESOLVED_CLAIMS = (
    "official_source_primary_package_equivalence",
    "governing_version_and_applicability",
    "independent_legal_interpretation",
    "independent_formal_interpretation",
    "authenticated_exposure",
)
FALSE_AUTHORITY = dict.fromkeys((
    "admitted", "formalized", "source_authenticity_verified", "source_semantics_verified",
    "primary_source_correspondence_verified", "source_package_content_identity_verified",
    "governing_source_binding_verified", "applicability_verified", "context_closure_verified",
    "exposure_authenticated", "semantic_agreement_verified", "actual_legal_review_performed",
    "authenticated_review_verified", "assessment_performed", "accepted_graph_view_enabled",
    "accepted_view_eligible", "semantic_graph_admitted", "entity_records_merged",
    "training_qualified", "training_gold_qualified", "evaluation_gold_qualified",
    "proof_authority", "Lean_admitted", "published",
), False)
_SELF_PATH = Path(__file__).resolve()
_SELF_PIN = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_OPERATION_PINS = None


class PrimaryAssociationDefinitionReviewError(ValueError):
    """Independent originals, complete closure or a finite boundary differs."""


def _need(condition, message):
    if not condition:
        raise PrimaryAssociationDefinitionReviewError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and _SHA.fullmatch(value), "independent SHA256 required: " + label)


def _copy(value, maximum, *, allow_bytes=False):
    """Detach finite ordinary inputs before any lazy operation import."""
    remaining, nodes = maximum, MAX_JSON_NODES

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= MAX_JSON_DEPTH, "review input node/depth bound exceeded")
        if type(item) is dict:
            _need(len(item) <= nodes, "review object population exceeds bound")
            remaining -= 2 + 2 * len(item)
            _need(remaining >= 0, "review input byte bound exceeded")
            result = {}
            for key, child in item.items():
                _need(type(key) is str, "ordinary review JSON string keys required")
                result[visit(key, depth + 1)] = visit(child, depth + 1)
            return result
        if type(item) is list:
            _need(len(item) <= nodes, "review list population exceeds bound")
            remaining -= 2 + len(item)
            _need(remaining >= 0, "review input byte bound exceeded")
            return [visit(child, depth + 1) for child in item]
        if type(item) is str:
            _need("\x00" not in item and len(item) <= remaining, "bounded review UTF8 string required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise PrimaryAssociationDefinitionReviewError("valid review UTF8 required") from error
        elif allow_bytes and type(item) is bytes:
            remaining -= len(item)
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(abs(item) <= (1 << 63) - 1, "bounded review integer required")
            remaining -= len(str(item))
        elif type(item) is float:
            _need(math.isfinite(item), "finite review JSON required")
            remaining -= len(repr(item))
        else:
            raise PrimaryAssociationDefinitionReviewError("ordinary bounded review input required")
        _need(remaining >= 0, "review input byte bound exceeded")
        return item

    return visit(value, 0)


def _wire(value, maximum=MAX_RECORD_BYTES):
    checked = _copy(value, maximum)
    try:
        raw = json.dumps(checked, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise PrimaryAssociationDefinitionReviewError("finite bounded review JSON required") from error
    _need(len(raw) <= maximum, "complete review JSON byte bound exceeded")
    return raw


def _digest(value, maximum=MAX_RECORD_BYTES):
    return _sha(_wire(value, maximum))


def _snapshot_pin(value):
    digest = hashlib.sha256()

    def add(item):
        if type(item) is bytes:
            digest.update(b"bytes:" + str(len(item)).encode() + b":")
            digest.update(item)
        elif type(item) is dict:
            digest.update(b"dict:")
            for key in sorted(item):
                add(key)
                add(item[key])
            digest.update(b"end-dict:")
        elif type(item) is list:
            digest.update(b"list:")
            for child in item:
                add(child)
            digest.update(b"end-list:")
        else:
            raw = json.dumps(item, ensure_ascii=False, allow_nan=False).encode("utf-8")
            digest.update(b"json:" + str(len(raw)).encode() + b":" + raw)

    add(value)
    return digest.hexdigest()


def _preflight(association, correspondence, binding_result, previous_subject,
               expected_association_sha256, association_replay_inputs):
    _pin(expected_association_sha256, "complete original association")
    _need(type(association_replay_inputs) is dict and set(association_replay_inputs) == _REPLAY_FIELDS,
          "closed original association replay keywords required")
    replay = association_replay_inputs
    for name in _REPLAY_FIELDS - {"correspondence_replay_inputs", "mapping_raw"}:
        _pin(replay[name], name)
    _need(type(replay["correspondence_replay_inputs"]) is dict
          and set(replay["correspondence_replay_inputs"]) == _CORRESPONDENCE_REPLAY_FIELDS,
          "closed original correspondence replay keywords required")
    original = replay["correspondence_replay_inputs"]
    for name in ("expected_binding_sha256", "expected_subject_sha256", "expected_manifest_sha256"):
        _pin(original[name], name)
    raw = replay["mapping_raw"]
    _need(type(raw) is bytes and 0 < len(raw) <= 64 * 1024
          and _sha(raw) == replay["expected_mapping_file_sha256"], "original mapping transport pin differs")
    _need(type(association) is dict and _digest(association) == expected_association_sha256,
          "independent complete association pin differs")
    _need(type(correspondence) is dict and type(binding_result) is dict and type(previous_subject) is dict,
          "ordinary complete original correspondence, binding and subject required")
    _need(_digest(correspondence) == replay["expected_correspondence_sha256"],
          "independent complete correspondence pin differs")
    _need(_digest(binding_result, 4 * MAX_RECORD_BYTES) == original["expected_binding_sha256"],
          "independent complete binding pin differs")
    _need(_digest(previous_subject) == original["expected_subject_sha256"],
          "independent complete previous subject pin differs")
    return _copy({"association": association, "correspondence": correspondence,
        "binding_result": binding_result, "previous_subject": previous_subject,
        "replay": replay}, MAX_INPUT_BYTES, allow_bytes=True)


def _owners():
    from . import legal_source_sampling_primary_association_v2 as association
    from . import legal_graph_dependencies as dependencies
    from . import corpus_definition_review_v2 as review
    from . import corpus_contracts as contracts
    from . import legal_primary_section_index as index
    return association, dependencies, review, contracts, index


def _source_pin(path):
    _need(type(path) is Path or isinstance(path, Path), "producer source path required")
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
    except OSError as error:
        raise PrimaryAssociationDefinitionReviewError("producer source unavailable") from error
    _need(0 < len(raw) <= MAX_SOURCE_BYTES, "bounded producer source required")
    return _sha(raw)


def _pins(owners, existing=None):
    global _OPERATION_PINS
    _need(_source_pin(_SELF_PATH) == _SELF_PIN, "review preparation owner changed since import")
    modules = (*owners, owners[2].cid_utils, owners[2].adapter,
               owners[2].corpus_graph, owners[2].corpus_source)
    pins = {str(_SELF_PATH): _SELF_PIN}
    for module in modules:
        path = Path(module.__file__).resolve()
        pins[str(path)] = _source_pin(path)
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(pins)
    _need(pins == _OPERATION_PINS, "review operation owners changed since first use")
    if existing is not None:
        _need(type(existing) is dict, "complete original association producer pins required")
        for path, expected in existing.items():
            _pin(expected, "original association producer")
            _need(type(path) is str and Path(path).is_absolute(), "absolute original producer path required")
            _need(path not in pins or pins[path] == expected, "review producer observations conflict")
            _need(_source_pin(Path(path)) == expected, "original association producer changed")
            pins[path] = expected
    return pins


def _ref(value, *, maximum=MAX_RECORD_BYTES):
    result = {"schema": value["schema"], "sha256": _digest(value, maximum)}
    if "record_cid" in value:
        result["record_cid"] = value["record_cid"]
    return result


def _closure(artifacts, edges, graph_id, graph_sha256):
    """Independently derive the ordered declared closure, preserving gaps."""
    _need(type(artifacts) is list and 0 < len(artifacts) <= MAX_ARTIFACTS
          and type(edges) is list and len(edges) <= MAX_EDGES, "complete finite review dependency population required")
    by_id = {row["artifact_id"]: row for row in artifacts}
    _need(len(by_id) == len(artifacts) and graph_id in by_id
          and by_id[graph_id]["artifact_sha256"] == graph_sha256,
          "original candidate graph root differs")
    adjacency = {key: [] for key in by_id}
    for edge in edges:
        _need(edge["dependent_id"] in adjacency, "dependency edge dependent is omitted")
        adjacency[edge["dependent_id"]].append(edge["dependency_id"])
    ordered, seen = [graph_id], {graph_id}
    for parent in ordered:
        for child in adjacency.get(parent, []):
            if child not in seen:
                seen.add(child)
                ordered.append(child)
                _need(len(ordered) <= MAX_ARTIFACTS + MAX_EDGES, "complete review closure bound exceeded")
    return ordered


def _compose(old_manifest, previous_subject, checked, correspondence, producers, dependencies):
    artifacts = _copy(old_manifest["artifacts"], MAX_MANIFEST_BYTES)
    edges = _copy(old_manifest["edges"], MAX_MANIFEST_BYTES)
    reserved = {row["artifact_id"] for row in artifacts}
    # Even an unreachable old gap remains open: never satisfy it by appending a
    # new artifact with the same name, or deduplicate a prior physical witness.
    reserved.update(row["dependency_id"] for row in edges)
    added, added_ids = [], set()

    def add(identity, digest, role):
        _pin(digest, "added dependency artifact")
        _need(identity not in reserved and identity not in added_ids,
              "added review artifact collides with original artifact or dependency target")
        added_ids.add(identity)
        artifacts.append({"artifact_id": identity, "artifact_sha256": digest,
            "dependency_pins": {kind: [] for kind in dependencies.PIN_KINDS}})
        added.append({"artifact_id": identity, "artifact_sha256": digest, "role": role})

    association_id = "sampled-primary-review-association:sha256:" + _digest(checked)
    add(association_id, _digest(checked), "complete_unsigned_primary_association")
    add("sampled-primary-review-correspondence:sha256:" + _digest(correspondence),
        _digest(correspondence), "complete_unchanged_source_review_correspondence")
    add("sampled-primary-review-previous-subject:sha256:" + _digest(previous_subject),
        _digest(previous_subject), "complete_unchanged_previous_definition_subject")
    manifest_sha = _digest(old_manifest, MAX_MANIFEST_BYTES)
    add("sampled-primary-review-previous-manifest:sha256:" + manifest_sha,
        manifest_sha, "complete_unchanged_previous_dependency_manifest")
    for ref in checked["primary_artifact_refs"]:
        add(ref["artifact_id"], ref["artifact_sha256"], ref["role"])
    for path, digest in sorted(producers.items()):
        add("sampled-primary-review-producer:sha256:" + _sha(path.encode("utf-8")),
            digest, "review_preparation_producer_source")
    _need(len(artifacts) <= MAX_ARTIFACTS, "complete added review artifact population exceeds bound")
    edges.append({"dependent_id": previous_subject["graph_id"], "dependency_id": association_id})
    edges.extend({"dependent_id": association_id, "dependency_id": row["artifact_id"]}
                 for row in added[1:])
    _need(len(edges) <= MAX_EDGES, "complete added review edge population exceeds bound")
    ids = [row["artifact_id"] for row in artifacts]
    manifest = dependencies.build_dependency_manifest(artifacts, edges, expected_artifact_ids=ids)
    manifest = dependencies.validate_dependency_manifest(manifest,
        expected_manifest_sha256=manifest["manifest_sha256"])
    closure = _closure(artifacts, edges, previous_subject["graph_id"], previous_subject["graph_sha256"])
    _need(all(row["artifact_id"] in closure for row in added), "new review evidence is unreachable")
    _need(manifest["artifacts"][:len(old_manifest["artifacts"])] == old_manifest["artifacts"]
          and manifest["edges"][:len(old_manifest["edges"])] == old_manifest["edges"],
          "original entire dependency population changed")
    return manifest, closure, added


def prepare_primary_association_definition_review_v2(association, correspondence, binding_result,
        previous_subject, primary_index, *, expected_association_sha256, association_replay_inputs):
    """Replay all originals and prepare a fresh unsigned definition subject.

    Every artifact and edge of the old manifest survives, including unrelated
    artifacts and open targets. An unresolved primary association instead returns
    a blocked preparation with null companions. This never assesses or signs a
    review, changes the previous signing domain or resolves source equivalence.
    """
    snapshot = _preflight(association, correspondence, binding_result, previous_subject,
        expected_association_sha256, association_replay_inputs)
    token = _snapshot_pin(snapshot)
    owners = _owners()
    association_owner, dependencies, review, contracts, index_owner = owners
    producers = _pins(owners)
    _need(type(primary_index) is index_owner.PrimarySectionIndex, "exact live PrimarySectionIndex required")
    primary_index.guard()
    index_wire = _wire(primary_index.receipt)

    def fence(existing=None):
        _need(_snapshot_pin(snapshot) == token, "detached review originals changed during preparation")
        pins = _pins(owners, existing)
        _need(all(pins.get(path) == digest for path, digest in producers.items()),
              "review preparation producers changed")
        primary_index.guard()
        _need(_wire(primary_index.receipt) == index_wire, "live primary index changed during review preparation")
        return pins

    fence()
    checked = association_owner.validate_sampled_primary_association_v2(
        snapshot["association"], snapshot["correspondence"], snapshot["binding_result"],
        snapshot["previous_subject"], primary_index,
        expected_association_sha256=expected_association_sha256, **snapshot["replay"])
    _need(_wire(checked) == _wire(snapshot["association"]), "original association changed during replay")
    producers = fence(checked["producer_pins"])
    old_subject = snapshot["previous_subject"]
    replay = snapshot["replay"]["correspondence_replay_inputs"]
    old_manifest = dependencies.validate_dependency_manifest(replay["dependency_manifest"],
        expected_manifest_sha256=replay["expected_manifest_sha256"])
    _need(_wire(old_manifest, MAX_MANIFEST_BYTES) == _wire(replay["dependency_manifest"], MAX_MANIFEST_BYTES),
          "original entire dependency manifest changed")
    _need(_wire(old_subject["context_slot_ids"]) == _wire(checked["context_slot_ids"])
          and old_subject["required_dependency_ids"] == replay["required_dependency_ids"],
          "original context or dependency population differs")
    fence(checked["producer_pins"])
    subject = manifest = None
    closure, added = [], []
    issues = _copy(checked["issues"], MAX_RECORD_BYTES)
    blocked = checked["status"] == "unresolved_primary_association"
    _need(blocked or checked["status"] == "declared_primary_association_only",
          "unsupported original association status")
    if not blocked:
        _need(not issues and bool(checked["primary_artifact_refs"]), "complete healthy primary witnesses required")
        manifest, closure, added = _compose(old_manifest, old_subject, checked,
            snapshot["correspondence"], producers, dependencies)
        fence(checked["producer_pins"])
        evidence = {key: replay[key] for key in (
            "candidate_inputs", "expected_candidate_pin", "context_inputs", "expected_context_population")}
        subject = review.build_definition_review_subject_v2(old_subject["native_binding"], manifest,
            **evidence, expected_manifest_sha256=manifest["manifest_sha256"], required_dependency_ids=closure)
        _need(subject["context_slot_ids"] == old_subject["context_slot_ids"]
              and subject["native_binding"] == old_subject["native_binding"]
              and subject["required_dependency_ids"] == closure,
              "fresh subject changed original preparation or context obligations")
        _wire(subject)
        _wire(manifest, MAX_MANIFEST_BYTES)
        fence(checked["producer_pins"])
    authority = dict.fromkeys(sorted({*FALSE_AUTHORITY, *checked["authority"]}), False)
    old_manifest_ref = _ref(old_manifest, maximum=MAX_MANIFEST_BYTES)
    old_manifest_ref["manifest_sha256"] = old_manifest["manifest_sha256"]
    manifest_ref = None if manifest is None else _ref(manifest, maximum=MAX_MANIFEST_BYTES)
    if manifest_ref is not None:
        manifest_ref["manifest_sha256"] = manifest["manifest_sha256"]
    payload = {
        "schema": PREPARATION_SCHEMA, "profile": PROFILE, "view": "candidate", "unsigned": True,
        "status": "blocked_unresolved_primary_association" if blocked
                  else "unsigned_association_bound_definition_review_subject",
        "review_subject_created": not blocked, "assessment_created": False, "signatures_created": False,
        "association_ref": _ref(checked), "correspondence_ref": _ref(snapshot["correspondence"]),
        "previous_subject_ref": _ref(old_subject), "previous_manifest_ref": old_manifest_ref,
        "previous_preparation_ref": _ref(old_subject["native_binding"]),
        "primary_index_ref": {"schema": checked["primary_index_receipt"]["schema"],
            "index_sha256": snapshot["replay"]["expected_index_sha256"],
            "full_canonical_sha256": _digest(checked["primary_index_receipt"])},
        "candidate_ref": checked["candidate_ref"],
        "source_identity_ref": {"sha256": _digest(checked["source_identity"])},
        "population_ref": checked["population_ref"], "population_counts": checked["population_counts"],
        "population_subject_count": checked["population_subject_count"], "response_count": checked["response_count"],
        "selected_unit_roles": checked["selected_unit_roles"], "context_slot_ids": checked["context_slot_ids"],
        "primary_artifact_refs": checked["primary_artifact_refs"],
        "previous_required_dependency_ids": old_subject["required_dependency_ids"],
        "required_dependency_ids": closure, "added_artifact_refs": added,
        "subject_ref": None if subject is None else _ref(subject), "dependency_manifest_ref": manifest_ref,
        "issues": issues, "unresolved_claims": list(UNRESOLVED_CLAIMS), "producer_pins": producers,
        "authority": authority, "training_mask": 0, "evaluation_gold_mask": 0,
    }
    _wire(payload)
    preparation = contracts.seal_record(payload)
    envelope = {"schema": SCHEMA, "profile": PROFILE, "preparation": preparation,
                "subject": subject, "dependency_manifest": manifest}
    _wire(envelope, MAX_ENVELOPE_BYTES)
    fence(checked["producer_pins"])
    return envelope


def primary_association_definition_review_sha256(envelope):
    """Commit the complete record and companions; a self-hash grants no trust."""
    _need(type(envelope) is dict and set(envelope) == _ENVELOPE_FIELDS
          and envelope["schema"] == SCHEMA and envelope["profile"] == PROFILE,
          "complete primary-association definition-review envelope required")
    return _digest(envelope, MAX_ENVELOPE_BYTES)


def validate_primary_association_definition_review_v2(envelope, *args,
        expected_preparation_sha256, **kwargs):
    """Regenerate every companion under independently retained original pins."""
    _pin(expected_preparation_sha256, "complete original review preparation envelope")
    _need(primary_association_definition_review_sha256(envelope) == expected_preparation_sha256,
          "independent complete review preparation envelope pin differs")
    offered = _wire(envelope, MAX_ENVELOPE_BYTES)
    expected = prepare_primary_association_definition_review_v2(*args, **kwargs)
    _need(offered == _wire(expected, MAX_ENVELOPE_BYTES),
          "review preparation differs from complete original-bound regeneration")
    return expected


__all__ = ["PrimaryAssociationDefinitionReviewError", "prepare_primary_association_definition_review_v2",
           "validate_primary_association_definition_review_v2", "primary_association_definition_review_sha256"]
