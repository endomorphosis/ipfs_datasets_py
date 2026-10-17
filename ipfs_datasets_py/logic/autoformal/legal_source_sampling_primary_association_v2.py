"""Unsigned declared primary anchors for an unchanged sampled V2 subject.

The existing correspondence owner replays source, interpretation and review
inputs. The live primary index owns complete original population and lookup.
This additive sidecar records a caller's association and every lookup witness;
it proves no package-to-official-source equivalence or governing legal meaning.
Public import uses only the standard library and starts no operation owner.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re


SCHEMA = "legal-source-sampling-primary-association/v2"
PROFILE = "unsigned-declared-v2-sampled-source-primary-association/v1"
MAPPING_SCHEMA = "legal-source-sampling-primary-association-mapping/v1"
MAX_MAPPING_BYTES = 64 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_LOOKUP_BYTES = 16 * 1024 * 1024
MAX_OCCURRENCES = 256
MAX_JSON_NODES = 2_000_000
MAX_JSON_DEPTH = 64
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_REPLAY_FIELDS = {
    "expected_binding_sha256", "expected_subject_sha256", "binding_replay_inputs",
    "candidate_inputs", "expected_candidate_pin", "context_inputs",
    "expected_context_population", "dependency_manifest", "expected_manifest_sha256",
    "required_dependency_ids",
}
_MAPPING_FIELDS = {
    "schema", "correspondence_sha256", "source_identity_sha256",
    "source_occurrence_cids", "legal_id", "section_entry_cid", "source_package_entry_cid",
}
_CORRESPONDENCE_FIELDS = (
    "source_identity", "population_ref", "population_subjects", "population_counts",
    "population_subject_count", "response_count", "selected_unit_roles", "required_subjects",
    "source_role_bindings", "occurrence_context_links", "candidate_ref", "subject_ref",
    "dependency_manifest_ref", "context_slot_ids",
)
FALSE_AUTHORITY = dict.fromkeys((
    "admitted", "formalized", "source_authenticity_verified", "source_semantics_verified",
    "primary_source_correspondence_verified", "source_package_content_identity_verified",
    "governing_source_binding_verified", "applicability_verified", "context_closure_verified",
    "exposure_authenticated", "semantic_agreement_verified", "actual_legal_review_performed",
    "authenticated_review_verified", "assessment_performed", "accepted_graph_view_enabled",
    "accepted_view_eligible", "semantic_graph_admitted", "entity_records_merged",
    "historical_flat_occurrences_repaired", "training_qualified", "training_gold_qualified",
    "evaluation_gold_qualified", "proof_authority", "Lean_admitted", "published",
), False)
_SELF_PATH = Path(__file__).resolve()
_SELF_PIN = hashlib.sha256(_SELF_PATH.read_bytes()).hexdigest()
_OPERATION_PINS = None


class SampledPrimaryAssociationError(ValueError):
    """An independent input, source fence or finite sidecar contract differs."""


def _need(condition, message):
    if not condition:
        raise SampledPrimaryAssociationError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pin(value, label):
    _need(type(value) is str and _SHA.fullmatch(value), "independent SHA256 required: " + label)


def _text(value, label, maximum=4096):
    _need(type(value) is str and value.strip() and "\x00" not in value and len(value) <= maximum,
          "bounded ordinary text required: " + label)
    try:
        _need(len(value.encode("utf-8")) <= maximum, "UTF8 text bound exceeded: " + label)
    except UnicodeError as error:
        raise SampledPrimaryAssociationError("valid UTF8 text required: " + label) from error


def _copy(value, maximum, *, allow_bytes=False):
    """Detach bounded ordinary inputs before loading any operation owner."""
    remaining, nodes = maximum, MAX_JSON_NODES

    def visit(item, depth):
        nonlocal remaining, nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= MAX_JSON_DEPTH, "association input node/depth bound exceeded")
        if type(item) is dict:
            _need(len(item) <= nodes, "association object population exceeds bound")
            remaining -= 2 + 2 * len(item)
            _need(remaining >= 0, "association input byte bound exceeded")
            result = {}
            for key, child in item.items():
                _need(type(key) is str, "ordinary association JSON string keys required")
                result[visit(key, depth + 1)] = visit(child, depth + 1)
            return result
        if type(item) is list:
            _need(len(item) <= nodes, "association list population exceeds bound")
            remaining -= 2 + len(item)
            _need(remaining >= 0, "association input byte bound exceeded")
            return [visit(child, depth + 1) for child in item]
        if type(item) is str:
            _need("\x00" not in item and len(item) <= remaining, "bounded association UTF8 string required")
            try:
                remaining -= len(item.encode("utf-8")) + 2
            except UnicodeError as error:
                raise SampledPrimaryAssociationError("valid association UTF8 required") from error
        elif allow_bytes and type(item) is bytes:
            remaining -= len(item)
        elif item is None or type(item) is bool:
            remaining -= 5
        elif type(item) is int:
            _need(abs(item) <= (1 << 63) - 1, "bounded association integer required")
            remaining -= len(str(item))
        elif type(item) is float:
            _need(math.isfinite(item), "finite association JSON required")
            remaining -= len(repr(item))
        else:
            raise SampledPrimaryAssociationError("ordinary bounded association input required")
        _need(remaining >= 0, "association input byte bound exceeded")
        return item

    return visit(value, 0)


def _wire(value, maximum=MAX_RECORD_BYTES):
    checked = _copy(value, maximum)
    try:
        raw = json.dumps(checked, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise SampledPrimaryAssociationError("finite bounded association JSON required") from error
    _need(len(raw) <= maximum, "complete association JSON byte bound exceeded")
    return raw


def _digest(value):
    return _sha(_wire(value))


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


def _mapping(raw, expected):
    _pin(expected, "mapping original file")
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_MAPPING_BYTES,
          "bounded original mapping bytes required")
    _need(_sha(raw) == expected, "independent original mapping file pin differs")

    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate mapping JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise SampledPrimaryAssociationError("finite mapping JSON required")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise SampledPrimaryAssociationError("duplicate-free original mapping JSON required") from error
    _need(type(value) is dict and set(value) == _MAPPING_FIELDS and value["schema"] == MAPPING_SCHEMA,
          "closed supported mapping fields required")
    _wire(value, MAX_MAPPING_BYTES)
    for key in ("correspondence_sha256", "source_identity_sha256"):
        _pin(value[key], key)
    occurrences = value["source_occurrence_cids"]
    _need(type(occurrences) is list and 0 < len(occurrences) <= MAX_OCCURRENCES,
          "complete bounded ordered source occurrence population required")
    for identity in occurrences:
        _text(identity, "source occurrence CID")
    _need(len(set(occurrences)) == len(occurrences), "physical source occurrences cannot repeat in mapping")
    _text(value["legal_id"], "literal legal ID")
    for key in ("section_entry_cid", "source_package_entry_cid"):
        if value[key] is not None:
            _text(value[key], key)
    return value


def _source_mapping(mapping, correspondence, expected_correspondence):
    _need(mapping["correspondence_sha256"] == expected_correspondence,
          "mapping addresses a different correspondence")
    identity, links = correspondence.get("source_identity"), correspondence.get("occurrence_context_links")
    _need(type(identity) is dict and mapping["source_identity_sha256"] == _digest(identity),
          "mapping source identity differs from complete correspondence source")
    _need(type(links) is list and 0 < len(links) <= MAX_OCCURRENCES,
          "complete correspondence physical occurrence links required")
    ids = []
    for link in links:
        _need(type(link) is dict and type(link.get("occurrence_ref")) is dict,
              "complete correspondence occurrence reference required")
        ids.append(link["occurrence_ref"].get("record_cid"))
    _need(_wire(ids) == _wire(mapping["source_occurrence_cids"]),
          "mapping omits, substitutes or reorders a physical source occurrence")


def _preflight(correspondence, binding_result, review_subject, expected_correspondence_sha256,
               correspondence_replay_inputs, mapping_raw, expected_mapping_file_sha256,
               expected_index_sha256):
    _pin(expected_correspondence_sha256, "complete original correspondence")
    _pin(expected_index_sha256, "original primary index receipt")
    mapping = _mapping(mapping_raw, expected_mapping_file_sha256)
    _need(type(correspondence_replay_inputs) is dict
          and set(correspondence_replay_inputs) == _REPLAY_FIELDS,
          "closed original correspondence replay keywords required")
    _need(type(correspondence) is dict and _digest(correspondence) == expected_correspondence_sha256,
          "independent complete correspondence pin differs")
    _wire(binding_result, 4 * MAX_RECORD_BYTES)
    _wire(review_subject)
    snapshot = _copy({"correspondence": correspondence, "binding_result": binding_result,
        "review_subject": review_subject, "replay": correspondence_replay_inputs,
        "mapping": mapping, "mapping_raw": mapping_raw}, MAX_INPUT_BYTES, allow_bytes=True)
    _source_mapping(snapshot["mapping"], snapshot["correspondence"], expected_correspondence_sha256)
    return snapshot


def _owners():
    from . import legal_source_sampling_definition_review_v2 as correspondence
    from . import legal_primary_section_index as index
    from . import legal_source_graph_proposals as proposals
    from . import corpus_contracts as contracts
    from ...processors.legal_data import uscode_release_schema as release
    return correspondence, index, proposals, contracts, release


def _pins(owners, existing=None):
    global _OPERATION_PINS
    _need(_sha(_SELF_PATH.read_bytes()) == _SELF_PIN, "association owner changed since import")
    modules = (*owners, owners[2].intake, owners[1].manifests, owners[1].reconstruction,
               owners[1].reconstruction.records)
    pins = {str(_SELF_PATH): _SELF_PIN}
    for module in modules:
        path = Path(module.__file__).resolve()
        pins[str(path)] = _sha(path.read_bytes())
    if _OPERATION_PINS is None:
        _OPERATION_PINS = dict(pins)
    _need(pins == _OPERATION_PINS, "association operation owners changed since first use")
    if existing is not None:
        _need(type(existing) is dict, "complete original producer pins required")
        for path, expected in existing.items():
            _pin(expected, "original correspondence producer")
            _need(type(path) is str and Path(path).is_absolute(), "original producer path required")
            _need(path not in pins or pins[path] == expected, "association producer observations conflict")
            _need(_sha(Path(path).read_bytes()) == expected, "original correspondence producer changed")
            pins[path] = expected
    return pins


def _healthy(row, family, kind):
    return (type(row) is dict and row.get("family") == family
        and row.get("disposition") == "proposed_unreviewed_transport"
        and type(row.get("identity_resolution")) is dict
        and row["identity_resolution"].get("status") == "unique_declared_identity"
        and type(row.get("original_body")) is dict
        and row["original_body"].get("node_type" if family == "graph_nodes" else "edge_type") == kind)


def _resolve(mapping, lookup, proposals):
    issues, refs = [], []

    def issue(code):
        issues.append({"code": code})

    if mapping["section_entry_cid"] is None:
        issue("section_mapping_unavailable")
    if mapping["source_package_entry_cid"] is None:
        issue("source_package_mapping_unavailable")
    sections = lookup["sections"]
    if lookup["issues"] or len(sections) != 1:
        issue("literal_primary_section_missing_or_ambiguous")
    if len(sections) != 1:
        return refs, issues
    section = sections[0]
    if section["entry_cid"] != mapping["section_entry_cid"]:
        issue("declared_section_entry_does_not_match")
    if section["issues"] or not _healthy(section["section_observation"], "graph_nodes", "section"):
        issue("primary_section_or_relationships_quarantined")
    packages = [row for row in section["source_packages"]
                if row["entry_cid"] == mapping["source_package_entry_cid"]]
    if len(packages) != 1:
        issue("declared_source_package_missing_or_ambiguous")
    else:
        package = packages[0]
        if not _healthy(package["source_package_observation"], "graph_nodes", "source_package"):
            issue("primary_source_package_quarantined")
        witnesses = package["has_source_observations"]
        if not witnesses or any(not _healthy(row, "graph_edges", "HAS_SOURCE") for row in witnesses):
            issue("primary_source_relationship_witnesses_quarantined")
    if not issues:
        refs = proposals.required_primary_artifacts(mapping, section)
        _wire(refs, MAX_LOOKUP_BYTES)
    return refs, issues


def prepare_sampled_primary_association_v2(correspondence, binding_result, review_subject, primary_index, *,
        expected_correspondence_sha256, correspondence_replay_inputs, mapping_raw,
        expected_mapping_file_sha256, expected_index_sha256):
    """Replay unchanged source/subject inputs and retain only declared anchors.

    A valid unmatched mapping returns a complete unresolved sidecar. Invalid
    source commitments or original inputs refuse. No existing graph, subject,
    manifest, index or caller container is modified. Resource custody remains
    with the caller's existing native validation owner.
    """
    snapshot = _preflight(correspondence, binding_result, review_subject,
        expected_correspondence_sha256, correspondence_replay_inputs, mapping_raw,
        expected_mapping_file_sha256, expected_index_sha256)
    token = _snapshot_pin(snapshot)
    owners = _owners()
    correspondence_owner, index_owner, proposals, contracts, release = owners
    producers = _pins(owners)
    _need(type(primary_index) is index_owner.PrimarySectionIndex, "exact live PrimarySectionIndex required")
    primary_index.guard()
    _need(primary_index.index_sha256 == expected_index_sha256, "independent primary index pin differs")
    receipt = primary_index.receipt
    identity = primary_index.primary_identity
    receipt_wire, identity_wire = _wire(receipt), _wire(identity)
    _need(_wire(receipt["primary_identity"]) == identity_wire, "primary index identity and receipt differ")

    def fence(existing=None):
        _need(_snapshot_pin(snapshot) == token, "detached association inputs changed during replay")
        pins = _pins(owners, existing)
        _need(all(pins.get(path) == expected for path, expected in producers.items()),
              "association producers changed during replay")
        primary_index.guard()
        _need(primary_index.index_sha256 == expected_index_sha256
              and _wire(primary_index.receipt) == receipt_wire
              and _wire(primary_index.primary_identity) == identity_wire,
              "primary index changed during association replay")
        return pins

    fence()
    checked = correspondence_owner.validate_definition_review_correspondence_v2(
        snapshot["correspondence"], snapshot["binding_result"], snapshot["review_subject"],
        expected_correspondence_sha256=expected_correspondence_sha256, **snapshot["replay"])
    _need(_wire(checked) == _wire(snapshot["correspondence"]),
          "original correspondence changed during complete replay")
    producers = fence(checked["producer_pins"])
    mapping = snapshot["mapping"]
    _source_mapping(mapping, checked, expected_correspondence_sha256)
    _need(release.validate_legal_id(mapping["legal_id"]) == mapping["legal_id"],
          "literal release-shape legal ID required")
    fence(checked["producer_pins"])
    lookup = primary_index.lookup_sections(mapping["legal_id"])
    _wire(lookup, MAX_LOOKUP_BYTES)
    _need(lookup["legal_id"] == mapping["legal_id"]
          and lookup["index_sha256"] == expected_index_sha256
          and _wire(lookup["primary_identity"]) == identity_wire,
          "complete primary lookup identity differs")
    fence(checked["producer_pins"])
    refs, issues = _resolve(mapping, lookup, proposals)
    fence(checked["producer_pins"])
    authority = dict.fromkeys(sorted({*FALSE_AUTHORITY, *checked["authority"]}), False)
    payload = {
        "schema": SCHEMA, "profile": PROFILE, "view": "candidate", "unsigned": True,
        "status": "unresolved_primary_association" if issues else "declared_primary_association_only",
        "association_basis": "independently_pinned_caller_mapping_not_source_equivalence",
        "correspondence_ref": {"schema": checked["schema"], "record_cid": checked["record_cid"],
                               "sha256": expected_correspondence_sha256},
        **{field: checked[field] for field in _CORRESPONDENCE_FIELDS},
        "primary_index_receipt": receipt, "primary_identity": identity,
        "primary_lookup": lookup, "mapping": mapping,
        "mapping_transport": {"utf8": snapshot["mapping_raw"].decode("utf-8"),
                              "bytes": len(snapshot["mapping_raw"]), "sha256": expected_mapping_file_sha256},
        "primary_artifact_refs": refs, "issues": issues, "producer_pins": producers,
        "authority": authority, "training_mask": 0, "evaluation_gold_mask": 0,
    }
    _wire(payload)
    # Existing envelope owner supplies the stricter common one-MiB record,
    # depth and node contracts. A complete over-bound result refuses, never clips.
    result = contracts.seal_record(payload)
    _wire(result)
    fence(checked["producer_pins"])
    return result


def sampled_primary_association_sha256(association):
    """Full canonical sealed-record commitment; not an admission credential."""
    _need(type(association) is dict and association.get("schema") == SCHEMA,
          "complete sampled primary association required")
    return _digest(association)


def validate_sampled_primary_association_v2(association, *args, expected_association_sha256, **kwargs):
    """Check an independently retained full pin and regenerate the whole sidecar."""
    _pin(expected_association_sha256, "complete original association")
    offered = _wire(association)
    _need(_sha(offered) == expected_association_sha256, "independent complete association pin differs")
    expected = prepare_sampled_primary_association_v2(*args, **kwargs)
    _need(offered == _wire(expected), "association differs from complete original-bound regeneration")
    return expected


__all__ = ["SampledPrimaryAssociationError", "prepare_sampled_primary_association_v2",
           "validate_sampled_primary_association_v2", "sampled_primary_association_sha256"]
