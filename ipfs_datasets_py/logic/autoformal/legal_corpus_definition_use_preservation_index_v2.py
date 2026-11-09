"""Strict, non-authorizing observations in the existing unified proof store.

Every preparation and retrieval replays the qualified retained byte-packet
reader. This module neither opens a database nor executes Lean. The caller
owns the existing store/connection and independently trusted commitments.
Storage acknowledgment is separate from proof, legal or review authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time

SCHEMA = "legal-corpus-v2-preservation-index-projection/v1"
OPERATION_SCHEMA = "legal-corpus-v2-preservation-index-operation/v1"
PROFILE = "retained-corpus-preservation-observation-index/v1"
MAX_RECORD_BYTES = 8 * 1024 * 1024
_PACKET_ARGUMENTS = frozenset({
    "expected_preparation_sha256", "expected_corpus_preparation_sha256",
    "expected_assessment_file_sha256", "expected_receipt_file_sha256",
    "expected_bundle_sha256", "review_inputs", "toolchain", "expected_binary_sha256",
})
_SELF_PIN = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _need(value, message):
    if not value:
        raise ValueError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _wire(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    _need(len(raw) <= MAX_RECORD_BYTES, "bounded complete observational index record required")
    return raw


def _tree_digest(value):
    """Type- and length-delimited commitment to the already bounded input tree."""
    digest = hashlib.sha256()

    def token(kind, body):
        digest.update(kind)
        digest.update(len(body).to_bytes(8, "big"))
        digest.update(body)

    def visit(item):
        if type(item) is dict:
            token(b"object", str(len(item)).encode())
            for key in sorted(item):
                visit(key)
                visit(item[key])
        elif type(item) is list:
            token(b"array", str(len(item)).encode())
            for child in item:
                visit(child)
        elif type(item) is bytes:
            token(b"bytes", item)
        elif type(item) is str:
            token(b"string", item.encode("utf-8"))
        elif type(item) is bool:
            token(b"bool", b"true" if item else b"false")
        elif type(item) is int:
            token(b"integer", str(item).encode())
        elif type(item) is float and math.isfinite(item):
            token(b"float", item.hex().encode())
        elif item is None:
            token(b"null", b"")
        else:
            raise ValueError("ordinary bounded index input tree required")

    visit(value)
    return digest.hexdigest()


def _timestamp(value):
    _need(type(value) in (int, float) and 0 <= value <= 253402300799.0
          and math.isfinite(value), "bounded finite ordinary index created_at required")
    return float(value)


def _owners():
    from . import corpus_contracts, legal_corpus_definition_use_preservation_packet_v2
    from ..common import duckdb_proof_store
    return legal_corpus_definition_use_preservation_packet_v2, duckdb_proof_store, corpus_contracts


@dataclass(frozen=True)
class RetainedCorpusIndexProjection:
    projection_json: str
    entry: object

    def to_dict(self):
        _need(type(self.projection_json) is str and len(self.projection_json.encode()) <= MAX_RECORD_BYTES,
              "bounded index projection text required")
        return json.loads(self.projection_json)


@dataclass(frozen=True)
class RetainedCorpusIndexOperation:
    receipt_json: str
    projection: RetainedCorpusIndexProjection

    def to_dict(self):
        _need(type(self.receipt_json) is str and len(self.receipt_json.encode()) <= MAX_RECORD_BYTES,
              "bounded index operation text required")
        return json.loads(self.receipt_json)


def prepare_definition_use_preservation_index_v2(
        packet_files, corpus_preparation, assessment_raw, *,
        expected_packet_observation_sha256, created_at, **packet_arguments):
    """Replay complete current packet inputs and prepare UNKNOWN/NONE storage.

    The packet-observation pin must be independently trusted, alongside every
    original packet pin. Publicly constructible result dataclasses are never
    accepted as substitutes for this replay. ``created_at`` is an explicit
    stable entry timestamp; it does not change the semantic key.
    """
    created_at = _timestamp(created_at)
    _need(type(expected_packet_observation_sha256) is str
          and len(expected_packet_observation_sha256) == 64
          and all(c in "0123456789abcdef" for c in expected_packet_observation_sha256),
          "independent exact packet-observation SHA256 required")
    _need(set(packet_arguments) == _PACKET_ARGUMENTS, "complete closed packet replay arguments required")
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "index projection owner changed since import")
    # Only the qualified bytes reader is loaded before all packet bounds and
    # independent provenance checks. It owns full source/review preparation.
    from . import legal_corpus_definition_use_preservation_packet_v2 as reader
    reader._bound_tree(packet_arguments, reader.MAX_INPUT_BYTES, allow_bytes=True)
    input_digest = _tree_digest(packet_arguments)
    retained = reader.validate_definition_use_preservation_packet_v2(
        packet_files, corpus_preparation, assessment_raw, **packet_arguments)
    reader._bound_tree(packet_arguments, reader.MAX_INPUT_BYTES, allow_bytes=True)
    _need(_tree_digest(packet_arguments) == input_digest,
          "complete original packet arguments changed across packet replay")
    observation_raw = retained.observation_json.encode("utf-8")
    _need(_sha(observation_raw) == expected_packet_observation_sha256,
          "independent exact current packet-observation pin differs")
    observation = retained.to_dict()
    _need(all(observation[field] is False for field in reader.FALSE_FLAGS)
          and all(value is False for value in observation["authority"].values())
          and type(observation["training_mask"]) is int and observation["training_mask"] == 0
          and type(observation["evaluation_gold_mask"]) is int and observation["evaluation_gold_mask"] == 0,
          "packet readback cannot grant index proof/source/review authority")
    reader._bound_tree(packet_arguments, reader.MAX_INPUT_BYTES, allow_bytes=True)
    manifest = reader._parse(dict(retained.files)["project/corpus-manifest.json"])
    _, store, contracts = _owners()
    source = Path(store.__file__).resolve()
    store_pin = _sha(source.read_bytes())
    producer_pins = {**observation["current_producer_pins"], str(Path(__file__).resolve()): _SELF_PIN,
                     str(source): store_pin}
    key_material = {
        "ir": {"full_corpus_preparation_sha256": observation["corpus_preparation_full_canonical_sha256"],
               "full_preservation_preparation_sha256": observation["preparation_full_canonical_sha256"],
               "engineering_reference": observation["reference_contract"]["key_material"]},
        "property_value": {"profile": PROFILE, "scope": "historical engineering observation only",
                           "theorems": manifest["theorems"], "preservation_fragments": manifest["preservation_fragments"]},
        "assumptions": {"theorem_assumptions": manifest["theorem_assumptions"],
                        "original_preparation_state": manifest["original_preparation_state"]},
        "selected_premises": manifest["review_dependency_manifest"]["artifacts"],
        "translator": {"producer_pins": producer_pins, "semantics_sha256": manifest["semantics_sha256"]},
        "solver_identities": {"historical_binary_sha256": observation["expected_binary_sha256"],
                              "fresh_solver_execution": False},
        "toolchain": {"toolchain": observation["toolchain"], "binary_sha256": observation["expected_binary_sha256"]},
        "theorem_registry": {name: manifest[name] for name in
                             ("theorems", "conditional_theorems", "preservation_theorems", "expected_modules", "module_imports")},
        "policy": {"assessment_file_sha256": observation["assessment_file_sha256"],
                   "complete_packet_arguments_sha256": input_digest,
                   "review_intake_binding": manifest["review_intake_binding"],
                   "review_dependency_manifest": manifest["review_dependency_manifest"],
                   "source_custody": observation["source_custody"], "authority": dict(reader.AUTHORITY)},
        "resources": {"packet_inventory": observation["packet_inventory"],
                      "max_packet_bytes": reader.MAX_PACKET_BYTES, "max_original_input_bytes": reader.MAX_INPUT_BYTES,
                      "max_index_record_bytes": MAX_RECORD_BYTES},
        "tree": {"packet_bundle_sha256": observation["packet_bundle_sha256"],
                 "receipt_file_sha256": observation["receipt_file_sha256"],
                 "packet_observation_file_sha256": expected_packet_observation_sha256},
        "backend_id": "legal_ir_retained_corpus_observation",
        "backend_binary": observation["expected_binary_sha256"],
        "backend_version": PROFILE,
        "backend_config": {"schema": SCHEMA, "owner_sha256": _SELF_PIN, "store_owner_sha256": store_pin,
                           "status": "unknown", "result_authority": "candidate", "evidence_authority": "none",
                           "trust_level": "none", "kernel_accepted": False, "deterministic_trusted": False},
    }
    key = store.build_unified_proof_key(**key_material).require_all_dimensions()
    observation_reference = store.ImmutableEnvelopeReference.from_bytes(observation_raw, media_type="application/json")
    receipt_raw = dict(retained.files)["build-receipt.json"]
    receipt_reference = store.ImmutableEnvelopeReference.from_bytes(receipt_raw, media_type="application/json")
    payload = {
        "schema": SCHEMA, "profile": PROFILE, "scope": "retrievable historical engineering observation only",
        "packet_observation_reference": observation_reference.to_dict(),
        "native_receipt_reference": receipt_reference.to_dict(),
        "historical_receipt_record_cid": observation["historical_native_receipt"]["record_cid"],
        "engineering_reference_key_sha256": observation["reference_contract"]["reference_key_sha256"],
        "packet_bundle_sha256": observation["packet_bundle_sha256"],
        "key_material_sha256": _sha(_wire(key_material)), "key_material": key_material,
        "original_preparation_state": manifest["original_preparation_state"],
        "readback_verified": True, "kernel_accepted": False, "deterministic_trusted": False,
        "proof_usable": False, "authority": dict(reader.AUTHORITY), "training_mask": 0,
        "evaluation_gold_mask": 0, **reader.FALSE_FLAGS,
    }
    entry = store.UnifiedProofEntry(
        key=key, outcome=store.ProofOutcomeKind.UNKNOWN, trust_level=store.ProofTrustLevel.NONE,
        status=store.ResultStatus.UNKNOWN, result_authority=store.ResultAuthority.CANDIDATE,
        evidence_authority=store.EvidenceAuthority.NONE, result_payload=store.FrozenMap(payload),
        polarity=store.CachePolarity.NEGATIVE, created_at=created_at,
        result_id=observation_reference.content_id,
        diagnostics=("retained engineering observation; no fresh proof or source admission",),
        evidence=(store.ProofEvidenceRecord(
            evidence_id="sha256:" + _sha(_wire({"key_digest": key.digest,
                                                "native_receipt_reference": receipt_reference.to_dict()})),
            evidence_kind="unreviewed_runtime_observation",
            evidence_authority=store.EvidenceAuthority.NONE, content_digest=receipt_reference.content_digest,
            payload=store.FrozenMap(receipt_reference.to_dict()), created_at=created_at),),
        envelope=observation_reference,
    ).verify_integrity()
    record = contracts.seal_record({
        "schema": SCHEMA, "profile": PROFILE, "key": key.to_dict(), "key_digest": key.digest,
        "key_dimensions": dict(key.dimension_map()), "entry_digest": entry.entry_digest,
        "entry": entry.to_dict(), "producer_pins": producer_pins,
        "packet_observation_sha256": expected_packet_observation_sha256,
        "index_projection_prepared": True, "index_write_acknowledged": False,
        "durable_storage_verified": False, "proof_usable": False,
        "authority": dict(reader.AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        **reader.FALSE_FLAGS,
    })
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN and _sha(source.read_bytes()) == store_pin
          and _tree_digest(packet_arguments) == input_digest,
          "index owner or complete original packet arguments changed during preparation")
    return RetainedCorpusIndexProjection(_wire(record).decode(), entry)


def _full_readback(store, expected, now):
    entry = expected.entry
    value = store.get(entry.key, require_result_authority="candidate", max_evidence_authority="none",
                      max_trust_level="none", now=now)
    _need(value is not None and type(value) is type(entry), "full observational index readback missing or untyped")
    value.verify_integrity()
    _need(_wire(value.to_dict()) == _wire(entry.to_dict()), "full observational index readback differs")
    return value


def _acknowledgment(ack, projection, *, write):
    entry = projection.entry
    expected = entry.to_verification_cache_entry()
    _need(type(ack.hit) is bool and ack.hit is (not write) and ack.usable is True
          and ack.reason.value == ("stored" if write else "negative_hit") and ack.key_digest == entry.key.digest
          and ack.entry is not None and _wire(ack.entry.to_dict()) == _wire(expected.to_dict()),
          "observational index acknowledgment differs or is unusable")


def _operation(projection, operation):
    reader, _, contracts = _owners()
    record = contracts.seal_record({
        "schema": OPERATION_SCHEMA, "profile": PROFILE, "operation": operation,
        "key_digest": projection.entry.key.digest, "entry_digest": projection.entry.entry_digest,
        "index_write_acknowledged": operation == "write", "index_lookup_acknowledged": operation == "lookup",
        "full_entry_readback_verified": True, "current_packet_replayed_before_and_after": True,
        "observation_retrievable": True, "proof_usable": False, "durable_storage_verified": False,
        "authority": dict(reader.AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        **reader.FALSE_FLAGS,
    })
    return RetainedCorpusIndexOperation(_wire(record).decode(), projection)


def write_definition_use_preservation_index_v2(store, packet_files, corpus_preparation, assessment_raw,
                                             *, now=None, **options):
    """Write with explicit acknowledgment, full readback and post-I/O replay.

    Exceptions remain visible. A failed post-write validation may leave an
    observational row but produces no successful operation receipt. This is
    not a transaction spanning source replay and a caller-owned backend.
    """
    now = _timestamp(time.time() if now is None else now)
    projection = prepare_definition_use_preservation_index_v2(
        packet_files, corpus_preparation, assessment_raw, **options)
    _need(now >= projection.entry.created_at, "index query time precedes entry creation")
    acknowledgment = store.put(projection.entry, now=now)
    _acknowledgment(acknowledgment, projection, write=True)
    _full_readback(store, projection, now)
    again = prepare_definition_use_preservation_index_v2(
        packet_files, corpus_preparation, assessment_raw, **options)
    _need(again.projection_json == projection.projection_json, "current index projection changed after write")
    return _operation(projection, "write")


def lookup_definition_use_preservation_index_v2(
        store, packet_files, corpus_preparation, assessment_raw, *,
        expected_key_digest, expected_entry_digest, now=None, **options):
    """Retrieve only an independently expected exact observational entry.

    A genuine miss returns None. An incompatible, corrupt or overstated hit
    raises; retrieval never authorizes proof or compiler-artifact reuse.
    """
    for value in (expected_key_digest, expected_entry_digest):
        _need(type(value) is str and value.startswith("sha256:") and len(value) == 71
              and all(c in "0123456789abcdef" for c in value[7:]), "independent complete index digest required")
    now = _timestamp(time.time() if now is None else now)
    projection = prepare_definition_use_preservation_index_v2(
        packet_files, corpus_preparation, assessment_raw, **options)
    _need(now >= projection.entry.created_at, "index query time precedes entry creation")
    _need(projection.entry.key.digest == expected_key_digest
          and projection.entry.entry_digest == expected_entry_digest,
          "independent expected full observational key or entry differs")
    acknowledgment = store.lookup(projection.entry.key, require_result_authority="candidate",
        max_evidence_authority="none", max_trust_level="none", now=now)
    if acknowledgment.hit is False:
        _need(acknowledgment.usable is False and acknowledgment.entry is None
              and acknowledgment.reason.value == "miss" and acknowledgment.key_digest == expected_key_digest,
              "inconsistent observational index miss")
        return None
    _acknowledgment(acknowledgment, projection, write=False)
    _full_readback(store, projection, now)
    again = prepare_definition_use_preservation_index_v2(
        packet_files, corpus_preparation, assessment_raw, **options)
    _need(again.projection_json == projection.projection_json, "current index projection changed after lookup")
    return _operation(projection, "lookup")


__all__ = ["RetainedCorpusIndexProjection", "RetainedCorpusIndexOperation",
           "prepare_definition_use_preservation_index_v2", "write_definition_use_preservation_index_v2",
           "lookup_definition_use_preservation_index_v2"]


# The direct parent-norm route is deliberately distinct from official V2 above.
# It indexes receipt consistency, including an unprovided outer outcome.
PARENT_NORM_INDEX_SCHEMA = "legal-corpus-parent-norm-preservation-index-projection/v1"
PARENT_NORM_INDEX_OPERATION_SCHEMA = "legal-corpus-parent-norm-preservation-index-operation/v1"
PARENT_NORM_INDEX_PROFILE = "retained-parent-norm-receipt-consistency-index/v1"
_PARENT_NORM_INDEX_ARGUMENTS = frozenset({
    "expected_preparation_sha256", "expected_correspondence_sha256", "correspondence_inputs",
    "toolchain", "expected_receipt_file_sha256", "expected_bundle_sha256", "expected_binary_sha256",
})


PARENT_BOUND_NORM_INDEX_SCHEMA = "legal-corpus-parent-bound-norm-definition-preservation-index-projection/v1"
PARENT_BOUND_NORM_INDEX_OPERATION_SCHEMA = "legal-corpus-parent-bound-norm-definition-preservation-index-operation/v1"
PARENT_BOUND_NORM_INDEX_PROFILE = "retained-parent-bound-norm-definition-receipt-consistency-index/v1"
_PARENT_BOUND_NORM_INDEX_ARGUMENTS = frozenset({
    "expected_preparation_sha256", "expected_bound_report_sha256", "bound_definition_inputs",
    "toolchain", "expected_receipt_file_sha256", "expected_bundle_sha256", "expected_binary_sha256",
})


def _parent_norm_index_profile(reader, *, parent_bound=False):
    """Two trusted private bindings; public old/new routes select fixed values."""
    _need(type(parent_bound) is bool, "exact private parent norm profile selector required")
    if parent_bound:
        return {"schema": PARENT_BOUND_NORM_INDEX_SCHEMA,
            "operation_schema": PARENT_BOUND_NORM_INDEX_OPERATION_SCHEMA,
            "profile": PARENT_BOUND_NORM_INDEX_PROFILE, "arguments": _PARENT_BOUND_NORM_INDEX_ARGUMENTS,
            "report_pin": "expected_bound_report_sha256", "report_observation": "bound_definition_report_sha256",
            "input_name": "bound_report", "originals": "bound_definition_inputs",
            "reader_schema": reader.PARENT_BOUND_NORM_PACKET_SCHEMA,
            "reader_profile": reader.PARENT_BOUND_NORM_PACKET_PROFILE,
            "packet_document": reader._parent_bound_norm_packet_document,
            "packet_digest": reader.parent_bound_norm_definition_packet_sha256,
            "packet_storage": reader._parent_bound_norm_packet_storage,
            "packet_owners": reader._parent_bound_norm_packet_owners,
            "packet_callbacks": reader._parent_bound_norm_packet_callbacks,
            "packet_runtime": reader._parent_bound_norm_packet_runtime,
            "reader": reader.validate_parent_bound_norm_definition_native_packet_v1,
            "prepare": prepare_parent_bound_norm_definition_preservation_index_v1,
            "write": write_parent_bound_norm_definition_preservation_index_v1,
            "lookup": lookup_parent_bound_norm_definition_preservation_index_v1}
    return {"schema": PARENT_NORM_INDEX_SCHEMA, "operation_schema": PARENT_NORM_INDEX_OPERATION_SCHEMA,
        "profile": PARENT_NORM_INDEX_PROFILE, "arguments": _PARENT_NORM_INDEX_ARGUMENTS,
        "report_pin": "expected_correspondence_sha256", "report_observation": "correspondence_sha256",
        "input_name": "correspondence", "originals": "correspondence_inputs",
        "reader_schema": reader.PARENT_NORM_PACKET_SCHEMA, "reader_profile": reader.PARENT_NORM_PACKET_PROFILE,
        "packet_document": reader._parent_norm_packet_document, "packet_digest": reader.parent_norm_packet_sha256,
        "packet_storage": reader._parent_norm_packet_storage, "packet_owners": reader._parent_norm_packet_owners,
        "packet_callbacks": reader._parent_norm_packet_callbacks, "packet_runtime": reader._parent_norm_packet_runtime,
        "reader": reader.validate_parent_norm_native_packet_v1,
        "prepare": prepare_parent_norm_preservation_index_v1, "write": write_parent_norm_preservation_index_v1,
        "lookup": lookup_parent_norm_preservation_index_v1}


def _parent_norm_index_flags(reader, *, parent_bound=False):
    flags = {**reader.FALSE_FLAGS, "receipt_consistency_only": True,
            "accepted_execution": False, "accepted_outer_operation": False,
            "accepted_operation_result_bound": False, "outer_operation_outcome": "unprovided"}
    if parent_bound:
        _need(all(type(value) is bool and value is False for value in reader.FALSE_FLAGS.values())
              and all(type(value) is bool and value is False for value in reader.AUTHORITY.values()),
              "exact false packet/index policy required")
        flags.update(semantic_mask=0, consumer_mask=0, training_mask=0, evaluation_gold_mask=0,
                     selected_interpretation=None, governing_definition_use=None, norm_interpretation_ready=False)
    return flags


def _parent_norm_index_callbacks(reader, store, contracts, native_owners, finish, *, parent_bound=False):
    functions = (_parent_norm_index_profile, _prepare_retained_norm_index, _write_retained_norm_index,
        _lookup_retained_norm_index, _parent_bound_norm_index_key_material, _parent_norm_index_io_value,
        _parent_norm_index_store_runtime, _parent_norm_index_kwdefaults, _parent_norm_index_raw_custody,
        prepare_parent_bound_norm_definition_preservation_index_v1,
        write_parent_bound_norm_definition_preservation_index_v1,
        lookup_parent_bound_norm_definition_preservation_index_v1, _need, _sha, _wire, _tree_digest, _timestamp, _owners, _full_readback, _acknowledgment,
        _parent_norm_index_flags, _parent_norm_index_callbacks, _parent_norm_index_runtime,
        _parent_norm_index_guard, _parent_norm_index_operation, _parent_norm_index_store_callbacks,
        _parent_norm_index_projection_guard,
        prepare_parent_norm_preservation_index_v1, write_parent_norm_preservation_index_v1,
        lookup_parent_norm_preservation_index_v1, RetainedCorpusIndexProjection,
        RetainedCorpusIndexProjection.__init__, RetainedCorpusIndexProjection.to_dict,
        RetainedCorpusIndexOperation, RetainedCorpusIndexOperation.__init__, RetainedCorpusIndexOperation.to_dict,
        store.build_unified_proof_key, store.UnifiedProofKey, store.UnifiedProofKey.__init__,
        store.UnifiedProofKey.require_all_dimensions, store.UnifiedProofKey.to_dict,
        store.UnifiedProofKey.dimension_map, store.UnifiedProofEntry, store.UnifiedProofEntry.__init__,
        store.UnifiedProofEntry.verify_integrity, store.UnifiedProofEntry.to_dict,
        store.UnifiedProofEntry.to_verification_cache_entry, store.FrozenMap, store.FrozenMap.__init__,
        store.FrozenMap.to_dict, store.ProofEvidenceRecord, store.ProofEvidenceRecord.__init__,
        store.ProofEvidenceRecord.to_dict, store.ImmutableEnvelopeReference,
        store.ImmutableEnvelopeReference.from_bytes.__func__, store.ImmutableEnvelopeReference.to_dict,
        contracts.seal_record, contracts.validate_record, json.dumps, json.loads, finish)
    current = tuple((function, getattr(function, "__code__", None),
                     id(getattr(function, "__defaults__", None)), id(getattr(function, "__kwdefaults__", None)))
                    for function in functions)
    if parent_bound:
        protocol = (store.VerificationCacheLookup, store.VerificationCacheLookup.__init__,
            store.VerificationCacheLookup.to_dict, store.VerificationCacheEntry,
            store.VerificationCacheEntry.__init__, store.VerificationCacheEntry.to_dict,
            store.VerificationCacheEntry.verify_integrity, store.VerificationCacheEntry.compute_entry_digest,
            store.VerificationCacheKey, store.VerificationCacheKey.__init__, store.VerificationCacheKey.to_dict)
        current += tuple((function, getattr(function, "__code__", None),
                          id(getattr(function, "__defaults__", None)), id(getattr(function, "__kwdefaults__", None)))
                         for function in protocol)
    return current + _parent_norm_index_profile(reader, parent_bound=parent_bound)["packet_callbacks"](native_owners)


def _parent_norm_index_runtime(reader, *, parent_bound=False):
    profile = _parent_norm_index_profile(reader, parent_bound=parent_bound)
    value = {"schema": profile["schema"], "operation_schema": profile["operation_schema"],
            "profile": profile["profile"], "arguments": sorted(profile["arguments"]),
            "max_record_bytes": MAX_RECORD_BYTES, "flags": _parent_norm_index_flags(reader, parent_bound=parent_bound),
            "authority": dict(reader.AUTHORITY), "owner_sha256": _SELF_PIN,
            "reader_schema": profile["reader_schema"], "reader_profile": profile["reader_profile"],
            "owner_path": str(Path(__file__).resolve()), "reader_path": str(Path(reader.__file__).resolve())}
    if parent_bound:
        value["shared_helper_kwdefaults"] = _parent_norm_index_kwdefaults()
    return value


def _parent_norm_index_store_callbacks(store, names):
    functions = []
    for name in names:
        callback = getattr(store, name)
        function = getattr(callback, "__func__", callback)
        functions.append((function, getattr(function, "__code__", None),
                          id(getattr(function, "__defaults__", None)), id(getattr(function, "__kwdefaults__", None))))
    return tuple(functions)


def _parent_norm_index_guard(packet_files, preparation, correspondence, packet_arguments,
                             expected_packet_observation_sha256, created_at, *, parent_bound=False):
    """Bind complete originals and current owners across every external callback."""
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "parent norm index owner changed since import")
    from . import legal_corpus_definition_use_preservation_packet_v2 as reader
    profile = _parent_norm_index_profile(reader, parent_bound=parent_bound)
    _need(set(packet_arguments) == profile["arguments"], "complete closed retained norm packet arguments required")
    reader._pin(expected_packet_observation_sha256, "complete current parent norm packet observation")
    captured = None
    if parent_bound:
        captured = reader._parent_bound_norm_packet_capture(packet_files, preparation, correspondence, packet_arguments)
        storage = captured["storage"]
    else:
        for name in ("expected_preparation_sha256", "expected_correspondence_sha256",
                     "expected_receipt_file_sha256", "expected_bundle_sha256"):
            reader._pin(packet_arguments[name], "original parent norm index " + name)
        reader._binary_map(packet_arguments["expected_binary_sha256"])
        _need(type(packet_arguments["toolchain"]) is str and len(packet_arguments["toolchain"]) <= 128
              and reader._TOOLCHAIN.fullmatch(packet_arguments["toolchain"]), "version-pinned parent norm index toolchain required")
        reader._keys(packet_arguments["correspondence_inputs"], reader._PARENT_NORM_PACKET_REPLAY_FIELDS,
                     "complete original parent correspondence replay")
        storage = profile["packet_storage"](preparation)
    manifest = reader._parse(storage["manifest_json"].encode("utf-8"))

    def inputs():
        value = {"preparation": profile["packet_storage"](preparation),
                 profile["input_name"]: correspondence, "packet_arguments": packet_arguments,
                 "expected_packet_observation_sha256": expected_packet_observation_sha256,
                 "created_at": created_at}
        reader._bound_tree(value, reader.MAX_INPUT_BYTES, allow_bytes=True)
        return value

    original = inputs()
    original_digest, argument_digest = _tree_digest(original), _tree_digest(packet_arguments)
    semantic_digest = _tree_digest({name: value for name, value in original.items() if name != "created_at"})
    files, inventory = profile["packet_document"](packet_files)
    _need(profile["packet_digest"](packet_files) == packet_arguments["expected_bundle_sha256"]
          and _sha(files["build-receipt.json"]) == packet_arguments["expected_receipt_file_sha256"],
          "independent complete parent norm index packet or receipt pin differs")
    _need(_sha(reader._wire({"manifest": manifest, "files": storage["files"]}, 20 * reader.MAX_RECORD_BYTES))
          == packet_arguments["expected_preparation_sha256"]
          and _sha(reader._wire(correspondence, reader.MAX_PROJECT_BYTES))
          == packet_arguments[profile["report_pin"]],
          "independent complete parent norm index preparation/correspondence pins differ")
    # Bounds and independent original-byte pins precede lazy loading. No owner
    # here starts a database, process, solver, model or numerical kernel.
    native_owners = profile["packet_owners"]()
    native, contracts = native_owners[:2]
    preparer = native_owners[2] if parent_bound else native._owners()[0]
    _, store, same_contracts = _owners()
    _need(same_contracts is contracts, "same canonical parent norm record owner required")
    if parent_bound:
        finish = native_owners[5][2]._parent_finish
        plan = None  # Physical nomination follows the first genuine packet replay.
        observe_witness = lambda: [reader._parent_bound_norm_packet_file_witness(native_owners, value) for value in plan]
        observe_pins = lambda: reader._parent_bound_norm_packet_pins(native_owners, manifest)
        detached_snapshot = reader._review_snapshot(captured["copied"])
    else:
        from . import legal_norm_scope_correspondence_v1 as correspondence_owner
        finish = correspondence_owner._owners()[0]._parent_finish
        plan = preparer._parent_norm_file_plan(packet_arguments["correspondence_inputs"])
        observe_witness = lambda: preparer._parent_norm_file_witness(plan)
        observe_pins = lambda: native._parent_norm_native_pins(native._owners(), manifest)
        detached_snapshot = None
    paths = {str(Path(__file__).resolve()): _SELF_PIN,
             str(Path(reader.__file__).resolve()): reader._SELF_PIN,
             str(Path(store.__file__).resolve()): _sha(Path(store.__file__).read_bytes())}
    witness, current = (None, None) if parent_bound else (observe_witness(), observe_pins())
    active, guard_result = not parent_bound, None
    callbacks = _parent_norm_index_callbacks(reader, store, contracts, native_owners, finish, parent_bound=parent_bound)
    reader_runtime = profile["packet_runtime"](native_owners)
    runtime = _parent_norm_index_runtime(reader, parent_bound=parent_bound)
    typed_runtime = _tree_digest({"reader": reader_runtime, "index": runtime}) if parent_bound else None
    owner_paths = (str(Path(__file__).resolve()), str(Path(reader.__file__).resolve()), str(Path(store.__file__).resolve()))
    store_runtime = (store.PROOF_AUTHORITY_DIMENSIONS, store.UNIFIED_PROOF_KEY_SCHEMA_VERSION,
                     store.UNIFIED_PROOF_ENTRY_SCHEMA_VERSION, store.ProofOutcomeKind.UNKNOWN.value,
                     store.ProofTrustLevel.NONE.value, store.EvidenceAuthority.NONE.value,
                     store.ResultAuthority.CANDIDATE.value, store.CachePolarity.NEGATIVE.value)
    typed_store_runtime = _tree_digest(_parent_norm_index_store_runtime(store)) if parent_bound else None
    held, results, io = [], [], []
    raw_custody = _parent_norm_index_raw_custody
    raw_code = raw_custody.__code__
    raw_detached = raw_custody(captured["copied"], store, reader) if parent_bound else None
    raw_inputs = (raw_custody({"preparation": object.__getattribute__(preparation, "__dict__"),
        "bound_report": correspondence, "packet_arguments": packet_arguments, "packet_files": packet_files,
        "created_at": created_at, "expected_packet_observation_sha256": expected_packet_observation_sha256}, store, reader)
        if parent_bound else None)

    def hold_result(value, cls, fields):
        _need(type(value) is cls, "exact parent norm index result custody type required")
        results.append((value, cls, dict(fields), raw_custody(value, store, reader) if parent_bound else None))

    def hold(value, label):
        reader._bound_tree(value, MAX_RECORD_BYTES)
        held.append((value, reader._review_snapshot(value), label,
                     raw_custody(value, store, reader) if parent_bound else None))
        return value

    hold(manifest, "complete original parent norm manifest")
    if not parent_bound:
        hold(plan, "complete original parent norm physical witness plan")
        hold(witness, "original parent norm physical source identities")
        hold(current, "current genuine parent norm producer pins")
    hold(paths, "index/reader/store owner source pins")

    def hold_io(value, *, acknowledgment):
        if parent_bound:
            raw = raw_custody(value, store, reader)
            observed = _parent_norm_index_io_value(value, store, acknowledgment=acknowledgment)
            io.append((value, acknowledgment, _tree_digest(observed),
                       value.entry if acknowledgment else None, raw))
        return value

    def fence():
        if parent_bound:
            _need(_tree_digest(_parent_norm_index_store_runtime(store)) == typed_store_runtime,
                  "typed parent bound index store declaration changed")
            _need(_tree_digest({"reader": profile["packet_runtime"](native_owners),
                              "index": _parent_norm_index_runtime(reader, parent_bound=True)}) == typed_runtime,
                  "typed parent bound packet/index policy changed")
            _need(reader._review_snapshot(captured["copied"]) == detached_snapshot,
                  "detached complete parent bound index originals changed")
            for value, acknowledgment, expected, entry, raw in io:
                _need(_tree_digest(_parent_norm_index_io_value(value, store, acknowledgment=acknowledgment)) == expected
                      and (not acknowledgment or value.entry is entry),
                      "actual parent bound index acknowledgment/readback changed after return")
        _need(_parent_norm_index_profile(reader, parent_bound=parent_bound) == profile,
              "private fixed index profile binding changed")
        _need(_parent_norm_index_callbacks(reader, store, contracts, native_owners, finish, parent_bound=parent_bound) == callbacks
              and _parent_norm_index_runtime(reader, parent_bound=parent_bound) == runtime
              and profile["packet_runtime"](native_owners) == reader_runtime,
              "parent norm index callable or runtime declarations changed")
        _need((str(Path(__file__).resolve()), str(Path(reader.__file__).resolve()), str(Path(store.__file__).resolve())) == owner_paths,
              "parent norm index/reader/store owner paths changed")
        _need((store.PROOF_AUTHORITY_DIMENSIONS, store.UNIFIED_PROOF_KEY_SCHEMA_VERSION,
               store.UNIFIED_PROOF_ENTRY_SCHEMA_VERSION, store.ProofOutcomeKind.UNKNOWN.value,
               store.ProofTrustLevel.NONE.value, store.EvidenceAuthority.NONE.value,
               store.ResultAuthority.CANDIDATE.value, store.CachePolarity.NEGATIVE.value) == store_runtime,
              "parent norm index store schema/dimension/authority declarations changed")
        _need(_tree_digest(inputs()) == original_digest
              and _tree_digest(packet_arguments) == argument_digest,
              "complete original parent norm index inputs changed across replay or I/O")
        _need(profile["packet_digest"](packet_files) == packet_arguments["expected_bundle_sha256"],
              "original parent norm index packet changed")
        for path, expected in paths.items():
            _need(_sha(Path(path).read_bytes()) == expected, "parent norm index/reader/store source changed")
        if active:
            _need(observe_pins() == current,
                  "current parent norm index producer source identities changed")
            _need(observe_witness() == witness,
                  "original parent norm index physical source witnesses changed")
        if parent_bound and guard_result is not None:
            _need(guard_result["producer_pins"] == ({**current, **paths} if active else dict(paths)),
                  "actual parent bound index producer commitments changed")
        for result, cls, fields, raw in results:
            _need(type(result) is cls, "parent norm index result type changed")
            data = object.__getattribute__(result, "__dict__")
            _need(set(data) == set(fields) and all(
                type(data[name]) is str and data[name] == expected if type(expected) is str else data[name] is expected
                for name, expected in fields.items()), "actual parent norm index result storage changed")
        for value, expected, label, raw in held:
            reader._bound_tree(value, MAX_RECORD_BYTES)
            _need(reader._review_snapshot(value) == expected, "held parent norm index value changed: " + label)

    def activate():
        nonlocal plan, witness, current, active
        if parent_bound and not active:
            # The caller has just received genuine packet/preparation replay.
            plan = reader._parent_bound_norm_packet_file_plans(native_owners, packet_arguments["bound_definition_inputs"])
            witness, current = observe_witness(), observe_pins()
            hold(plan, "complete original parent bound norm/definition physical plans")
            hold(witness, "original parent bound norm/definition physical identities")
            hold(current, "current genuine parent bound norm producer pins")
            guard_result["producer_pins"] = {**current, **paths}
            active = True
        fence()

    def raw_tail():
        if parent_bound:
            _need(raw_custody is _parent_norm_index_raw_custody and raw_custody.__code__ is raw_code,
                  "final raw custody observer changed")
            _need(raw_custody(captured["copied"], store, reader) == raw_detached,
                  "final raw detached parent bound originals changed")
            for value, expected, label, raw in held:
                _need(raw_custody(value, store, reader) == raw,
                      "final raw held parent bound metadata changed: " + label)
            _need(guard_result["producer_pins"] == ({**current, **paths} if active else dict(paths)),
                  "final raw parent bound producer commitments changed")
            _need(raw_custody({"preparation": object.__getattribute__(preparation, "__dict__"),
                "bound_report": correspondence, "packet_arguments": packet_arguments, "packet_files": packet_files,
                "created_at": created_at, "expected_packet_observation_sha256": expected_packet_observation_sha256}, store, reader) == raw_inputs,
                "final raw parent bound index caller inputs changed")
            for value, acknowledgment, expected, entry, raw in io:
                _need(raw_custody(value, store, reader) == raw,
                      "final raw returned acknowledgment/readback custody changed")
            for value, cls, fields, raw in results:
                _need(raw_custody(value, store, reader) == raw,
                      "final raw packet/projection/operation result custody changed")

    def terminal():
        fence()
        raw_tail()

    guard_result = {"reader": reader, "store": store, "contracts": contracts, "manifest": manifest,
            "input_digest": semantic_digest, "argument_digest": argument_digest,
            "producer_pins": dict(paths) if parent_bound else {**current, **paths},
            "fence": fence, "hold": hold, "hold_result": hold_result, "activate": activate,
            "terminal": terminal, "raw_tail": raw_tail,
            "hold_io": hold_io, "profile": profile, "parent_bound": parent_bound, "finish": finish}
    fence()
    return guard_result


def prepare_parent_norm_preservation_index_v1(
        packet_files, preparation, correspondence, *, expected_packet_observation_sha256,
        created_at, **packet_arguments):
    """Project the original direct-parent23 profile with its unchanged defaults."""
    return _prepare_retained_norm_index(packet_files, preparation, correspondence,
        expected_packet_observation_sha256=expected_packet_observation_sha256,
        created_at=created_at, parent_bound=False, **packet_arguments)


def _prepare_retained_norm_index(
        packet_files, preparation, correspondence, *, expected_packet_observation_sha256,
        created_at, parent_bound=False, **packet_arguments):
    """Project direct-parent receipt consistency into UNKNOWN/NONE storage.

    All packet/preparation/correspondence pins and the separately trusted raw
    observation pin are required. A negative candidate hit is retrievable
    engineering evidence only; an accepted outer operation remains unprovided.
    No default official-V2 projection, source interpretation or proof is changed.
    """
    created_at = _timestamp(created_at)
    guard = _parent_norm_index_guard(packet_files, preparation, correspondence, packet_arguments,
                                      expected_packet_observation_sha256, created_at, parent_bound=parent_bound)
    reader, store, contracts = guard["reader"], guard["store"], guard["contracts"]
    fence, hold = guard["fence"], guard["hold"]
    profile = guard["profile"]
    state, primary = {}, None
    raw_custody = _parent_norm_index_raw_custody

    def serialized_fence():
        if "record" in state:
            _need(json.dumps(state["record"], sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8") == state["wire"],
                  "parent norm index record changed after serialization")
        if "result" in state:
            result = state["result"]
            _need(type(result) is RetainedCorpusIndexProjection, "exact parent norm index projection result required")
            data = object.__getattribute__(result, "__dict__")
            _need(set(data) == {"projection_json", "entry"} and type(data["projection_json"]) is str
                  and data["projection_json"].encode("utf-8") == state["wire"]
                  and data["entry"] is state["entry"], "parent norm index projection result storage changed")
        if "entry" in state:
            entry = state["entry"]
            entry.verify_integrity()
            _need(_wire(entry.to_dict()) == state["entry_wire"], "actual parent norm index entry changed")

    try:
        retained = profile["reader"](
            packet_files, preparation, correspondence, **packet_arguments)
        fence()
        _need(type(retained) is reader.RetainedDefinitionUsePreservationPacket
              and retained.files == packet_files, "genuine complete direct parent norm packet result required")
        if parent_bound:
            guard["hold_result"](retained, reader.RetainedDefinitionUsePreservationPacket,
                {"files": retained.files, "observation_json": retained.observation_json})
        observation_raw = retained.observation_json.encode("utf-8")
        _need(_sha(observation_raw) == expected_packet_observation_sha256,
              "independent exact current parent norm packet-observation pin differs")
        observation = hold(retained.to_dict(), "complete current parent norm packet observation")
        _need(observation["schema"] == profile["reader_schema"]
              and observation["profile"] == profile["reader_profile"]
              and observation["readback_verified"] is True and observation["current_preparation_replayed"] is True
              and observation["receipt_consistency_only"] is True
              and observation["accepted_execution"] is False and observation["accepted_outer_operation"] is False
              and observation["accepted_operation_result_bound"] is False
              and observation["outer_operation_outcome"] == "unprovided"
              and all(observation[name] is False for name in reader.FALSE_FLAGS)
              and observation["authority"] == reader.AUTHORITY
              and all(value is False for value in observation["authority"].values())
              and type(observation["training_mask"]) is int and observation["training_mask"] == 0
              and type(observation["evaluation_gold_mask"]) is int and observation["evaluation_gold_mask"] == 0,
              "parent norm packet consistency cannot grant index proof/source/outer-operation authority")
        _need(observation["packet_bundle_sha256"] == packet_arguments["expected_bundle_sha256"]
              and observation["receipt_file_sha256"] == packet_arguments["expected_receipt_file_sha256"]
              and observation["preparation_full_canonical_sha256"] == packet_arguments["expected_preparation_sha256"]
              and observation[profile["report_observation"]] == packet_arguments[profile["report_pin"]]
              and observation["toolchain"] == packet_arguments["toolchain"]
              and observation["expected_binary_sha256"] == packet_arguments["expected_binary_sha256"],
              "parent norm packet observation differs from complete current input/producer pins")
        if parent_bound:
            _need(all(type(observation[name]) is int and observation[name] == 0
                      for name in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask")),
                  "exact four zero masks required for parent bound packet index")
            guard["activate"]()
        _need({**observation["current_producer_pins"], str(Path(__file__).resolve()): _SELF_PIN,
               str(Path(store.__file__).resolve()): _sha(Path(store.__file__).read_bytes())} == guard["producer_pins"],
              "parent norm packet observation differs from complete current input/producer pins")
        manifest = guard["manifest"]
        flags = _parent_norm_index_flags(reader, parent_bound=parent_bound)
        if parent_bound:
            _need(all(type(observation[name]) is int and observation[name] == 0
                      for name in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask")),
                  "exact four zero masks required for parent bound packet index")
            key_material = hold(_parent_bound_norm_index_key_material(guard, observation, packet_arguments, flags, expected_packet_observation_sha256),
                                "complete parent bound norm key material")
        else:
            key_material = hold({
                "ir": {"full_parent_preparation_sha256": observation["preparation_full_canonical_sha256"],
                       "full_parent_correspondence_sha256": observation["correspondence_sha256"],
                       "original_norm": manifest["original_norm"]},
                "property_value": {"profile": PARENT_NORM_INDEX_PROFILE, "scope": "receipt consistency only",
                    "preservation_kind": observation["preservation_kind"], "proof_scope": observation["proof_scope"]},
                "assumptions": {"theorem_assumptions": manifest["theorem_assumptions"],
                    "original_parent_context": manifest["original_parent_context"], "review_blockers": manifest["review_blockers"]},
                "selected_premises": [manifest["review_intake_binding"], manifest["original_parent_context"]],
                "translator": {"producer_pins": guard["producer_pins"], "native_producer_pins": manifest["native_producer_pins"]},
                "solver_identities": {"historical_binary_sha256": observation["expected_binary_sha256"],
                    "historical_native_profile": observation["historical_native_receipt"]["profile"], "fresh_solver_execution": False},
                "toolchain": {"toolchain": observation["toolchain"], "binary_sha256": observation["expected_binary_sha256"]},
                "theorem_registry": {name: manifest[name] for name in
                    ("conditional_theorems", "expected_modules", "module_imports", "native_fragments")},
                "policy": {"complete_original_inputs_sha256": guard["input_digest"],
                    "complete_packet_arguments_sha256": guard["argument_digest"],
                    "original_input_commitment_sha256": manifest["original_input_commitment_sha256"],
                    "review_intake_binding": manifest["review_intake_binding"], "review_blockers": manifest["review_blockers"],
                    "declared_semantic_coverage": manifest["declared_semantic_coverage"],
                    "source_custody": observation["source_custody"], "authority": dict(reader.AUTHORITY), **flags},
                "resources": {"packet_inventory": observation["packet_inventory"], "max_packet_bytes": reader.MAX_PACKET_BYTES,
                    "max_original_input_bytes": reader.MAX_INPUT_BYTES, "max_index_record_bytes": MAX_RECORD_BYTES},
                "tree": {"packet_bundle_sha256": observation["packet_bundle_sha256"],
                    "receipt_file_sha256": observation["receipt_file_sha256"],
                    "packet_observation_file_sha256": expected_packet_observation_sha256,
                    "parent_source_binding_sha256": manifest["parent_source_binding_sha256"]},
                "backend_id": "legal_ir_retained_parent_norm_receipt_consistency",
                "backend_binary": observation["expected_binary_sha256"], "backend_version": PARENT_NORM_INDEX_PROFILE,
                "backend_config": {"schema": PARENT_NORM_INDEX_SCHEMA, "owner_sha256": _SELF_PIN,
                    "store_owner_sha256": _sha(Path(store.__file__).read_bytes()), "status": "unknown",
                    "result_authority": "candidate", "evidence_authority": "none", "trust_level": "none",
                    "kernel_accepted": False, "deterministic_trusted": False, **flags},
            }, "complete parent norm key material")
        key = store.build_unified_proof_key(**key_material).require_all_dimensions()
        observation_reference = store.ImmutableEnvelopeReference.from_bytes(observation_raw, media_type="application/json")
        receipt_raw = dict(retained.files)["build-receipt.json"]
        receipt_reference = store.ImmutableEnvelopeReference.from_bytes(receipt_raw, media_type="application/json")
        original_state = {name: manifest[name] for name in
            ("preparation_only", "lean_compilation_status", "proof_status", "execution_handoff",
             "original_norm", "review_blockers", "training_mask", "evaluation_gold_mask")}
        payload = hold({"schema": profile["schema"], "profile": profile["profile"],
            "scope": "retrievable retained receipt consistency only",
            "packet_observation_reference": observation_reference.to_dict(), "native_receipt_reference": receipt_reference.to_dict(),
            "historical_receipt_record_cid": observation["historical_native_receipt"]["record_cid"],
            "packet_bundle_sha256": observation["packet_bundle_sha256"],
            "key_material_sha256": _sha(_wire(key_material)), "key_material": key_material,
            "original_preparation_state": original_state, "readback_verified": True,
            "kernel_accepted": False, "deterministic_trusted": False, "proof_usable": False,
            "authority": dict(reader.AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0, **flags},
            "complete parent norm entry payload")
        evidence = store.ProofEvidenceRecord(
            evidence_id="sha256:" + _sha(_wire({"key_digest": key.digest, "native_receipt_reference": receipt_reference.to_dict()})),
            evidence_kind="unreviewed_runtime_observation", evidence_authority=store.EvidenceAuthority.NONE,
            content_digest=receipt_reference.content_digest, payload=store.FrozenMap(receipt_reference.to_dict()), created_at=created_at)
        entry = store.UnifiedProofEntry(key=key, outcome=store.ProofOutcomeKind.UNKNOWN,
            trust_level=store.ProofTrustLevel.NONE, status=store.ResultStatus.UNKNOWN,
            result_authority=store.ResultAuthority.CANDIDATE, evidence_authority=store.EvidenceAuthority.NONE,
            result_payload=store.FrozenMap(payload), polarity=store.CachePolarity.NEGATIVE,
            created_at=created_at, result_id=observation_reference.content_id,
            diagnostics=("retained parent norm receipt consistency; outer operation unprovided; no proof or source admission",),
            evidence=(evidence,), envelope=observation_reference).verify_integrity()
        _need(type(entry) is store.UnifiedProofEntry and entry.key == key
              and entry.outcome is store.ProofOutcomeKind.UNKNOWN and entry.trust_level is store.ProofTrustLevel.NONE
              and entry.status is store.ResultStatus.UNKNOWN and entry.result_authority is store.ResultAuthority.CANDIDATE
              and entry.evidence_authority is store.EvidenceAuthority.NONE and entry.polarity is store.CachePolarity.NEGATIVE
              and entry.created_at == created_at and entry.envelope == observation_reference
              and entry.result_id == observation_reference.content_id and entry.evidence == (evidence,)
              and _wire(entry.result_payload.to_dict()) == _wire(payload), "actual parent norm index entry differs from prepared candidate")
        state["entry"] = entry
        if parent_bound:
            state["entry_raw"] = raw_custody(entry, store, reader)
        state["entry_wire"] = _wire(entry.to_dict())
        record_input = hold({"schema": profile["schema"], "profile": profile["profile"],
            "key": key.to_dict(), "key_digest": key.digest, "key_dimensions": dict(key.dimension_map()),
            "entry_digest": entry.entry_digest, "entry": entry.to_dict(), "producer_pins": guard["producer_pins"],
            "packet_observation_sha256": expected_packet_observation_sha256, "index_projection_prepared": True,
            "index_write_acknowledged": False, "durable_storage_verified": False, "proof_usable": False,
            "authority": dict(reader.AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0, **flags},
            "complete parent norm projection seal input")
        record = contracts.seal_record(record_input)
        reader._keys(record, set(record_input) | {"record_cid", "cid_scope"}, "sealed parent norm index projection")
        _need(_wire({name: record[name] for name in record_input}) == _wire(record_input),
              "sealed parent norm index projection differs from complete original input")
        contracts.validate_record(record, schema=profile["schema"],
                                  fields=set(record) - {"schema", "record_cid", "cid_scope"})
        hold(record, "sealed complete parent norm projection")
        state["record"], state["wire"] = record, _wire(record)
        fence(); serialized_fence()
        result = RetainedCorpusIndexProjection(state["wire"].decode("utf-8"), entry)
        state["result"] = result
        if parent_bound:
            guard["hold_result"](result, RetainedCorpusIndexProjection,
                {"projection_json": state["wire"].decode("utf-8"), "entry": entry})
        fence(); serialized_fence()
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        if parent_bound:
            def terminal_serialization():
                serialized_fence()
                guard["terminal"]()
                if "record" in state:
                    direct = json.dumps(state["record"], sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=False, allow_nan=False).encode("utf-8")
                    _need(direct == state["wire"], "final direct parent bound projection encoding changed")
                if "entry_raw" in state:
                    _need(raw_custody(state["entry"], store, reader) == state["entry_raw"],
                          "final direct parent bound entry custody changed")
                guard["raw_tail"]()
            guard["finish"]((fence, serialized_fence, terminal_serialization), primary)
        else:
            guard["finish"]((fence, serialized_fence, fence, serialized_fence), primary)


def _parent_norm_index_projection_guard(projection, *, parent_bound=False):
    """Retain actual projection and entry storage, beyond its serialized copy."""
    _need(type(projection) is RetainedCorpusIndexProjection, "exact parent norm projection custody required")
    original_json, entry = projection.projection_json, projection.entry
    entry_wire = _wire(entry.to_dict())
    document = json.loads(original_json)
    _need(document["schema"] == (PARENT_BOUND_NORM_INDEX_SCHEMA if parent_bound else PARENT_NORM_INDEX_SCHEMA)
          and document["profile"] == (PARENT_BOUND_NORM_INDEX_PROFILE if parent_bound else PARENT_NORM_INDEX_PROFILE)
          and _wire(document["entry"]) == entry_wire, "parent norm projection and actual entry differ")

    def fence():
        data = object.__getattribute__(projection, "__dict__")
        _need(set(data) == {"projection_json", "entry"} and data["projection_json"] == original_json
              and data["entry"] is entry, "actual parent norm projection storage changed across index I/O")
        entry.verify_integrity()
        _need(_wire(entry.to_dict()) == entry_wire, "actual parent norm projection entry changed across index I/O")

    fence()
    return fence


def _parent_norm_index_operation(guard, projection, operation):
    profile, parent_bound = guard["profile"], guard["parent_bound"]
    reader, contracts = guard["reader"], guard["contracts"]
    _need(type(projection) is RetainedCorpusIndexProjection and operation in ("write", "lookup"),
          "genuine direct parent norm index operation projection required")
    before = projection.projection_json
    entry_wire = _wire(projection.entry.to_dict())
    fields = {"schema": profile["operation_schema"], "profile": profile["profile"],
        "operation": operation, "key_digest": projection.entry.key.digest, "entry_digest": projection.entry.entry_digest,
        "index_write_acknowledged": operation == "write", "index_lookup_acknowledged": operation == "lookup",
        "full_entry_readback_verified": True, "current_packet_replayed_before_and_after": True,
        "observation_retrievable": True, "proof_usable": False, "durable_storage_verified": False,
        "authority": dict(reader.AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        **_parent_norm_index_flags(reader, parent_bound=parent_bound)}
    guard["hold"](fields, "complete parent norm operation seal input")
    record = contracts.seal_record(fields)
    reader._keys(record, set(fields) | {"record_cid", "cid_scope"}, "sealed parent norm index operation")
    _need(_wire({name: record[name] for name in fields}) == _wire(fields),
          "sealed parent norm operation differs from original input")
    contracts.validate_record(record, schema=profile["operation_schema"],
                              fields=set(record) - {"schema", "record_cid", "cid_scope"})
    guard["hold"](record, "sealed complete parent norm operation")
    wire = _wire(record)
    result = RetainedCorpusIndexOperation(wire.decode("utf-8"), projection)
    guard["hold_result"](result, RetainedCorpusIndexOperation, {"receipt_json": wire.decode("utf-8"), "projection": projection})
    data = object.__getattribute__(result, "__dict__")
    guard["fence"]()
    _need(type(result) is RetainedCorpusIndexOperation and set(data) == {"receipt_json", "projection"}
          and type(data["receipt_json"]) is str and data["receipt_json"].encode("utf-8") == wire
          and data["projection"] is projection and projection.projection_json == before
          and _wire(projection.entry.to_dict()) == entry_wire
          and json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8") == wire,
          "actual parent norm operation result or final serialization changed")
    return result


def write_parent_norm_preservation_index_v1(store, packet_files, preparation, correspondence, *, now=None, **options):
    """Write the original direct-parent23 observational profile."""
    return _write_retained_norm_index(store, packet_files, preparation, correspondence,
        now=now, parent_bound=False, **options)


def _write_retained_norm_index(store, packet_files, preparation, correspondence, *, now=None, parent_bound=False, **options):
    """Write one exact negative candidate, with full readback and closing replay.

    A callback failure may leave a stored observational row. No successful
    operation receipt or transaction spanning the caller's store is implied.
    """
    _need(type(parent_bound) is bool, "exact private index profile selector required")
    argument_fields = _PARENT_BOUND_NORM_INDEX_ARGUMENTS if parent_bound else _PARENT_NORM_INDEX_ARGUMENTS
    now = _timestamp(time.time() if now is None else now)
    _need(set(options) == argument_fields | {"created_at", "expected_packet_observation_sha256"},
          "complete closed parent norm index write options required")
    created_at = _timestamp(options["created_at"])
    arguments = {name: options[name] for name in argument_fields}
    guard = _parent_norm_index_guard(packet_files, preparation, correspondence, arguments,
                                      options["expected_packet_observation_sha256"], created_at, parent_bound=parent_bound)
    primary, custody = None, None
    try:
        projection = guard["profile"]["prepare"](packet_files, preparation, correspondence, **options)
        custody = _parent_norm_index_projection_guard(projection, parent_bound=parent_bound)
        if parent_bound:
            guard["activate"]()
        guard["fence"]()
        _need(now >= projection.entry.created_at, "index query time precedes entry creation")
        methods = _parent_norm_index_store_callbacks(store, ("put", "get"))
        acknowledgment = store.put(projection.entry, now=now)
        guard["hold_io"](acknowledgment, acknowledgment=True)
        custody(); guard["fence"]()
        _need(_parent_norm_index_store_callbacks(store, ("put", "get")) == methods, "parent norm index backend callbacks changed")
        _acknowledgment(acknowledgment, projection, write=True)
        guard["hold_io"](_full_readback(store, projection, now), acknowledgment=False)
        custody(); guard["fence"]()
        _acknowledgment(acknowledgment, projection, write=True)
        _need(_parent_norm_index_store_callbacks(store, ("put", "get")) == methods, "parent norm index backend callbacks changed")
        again = guard["profile"]["prepare"](packet_files, preparation, correspondence, **options)
        _need(again.projection_json == projection.projection_json, "current parent norm index projection changed after write")
        custody(); guard["fence"]()
        _acknowledgment(acknowledgment, projection, write=True)
        result = _parent_norm_index_operation(guard, projection, "write")
        custody(); guard["fence"]()
        _acknowledgment(acknowledgment, projection, write=True)
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        finish = (guard["fence"], custody, guard["fence"]) if custody is not None else (guard["fence"],)
        if parent_bound:
            finish += (guard["terminal"],)
        guard["finish"](finish, primary)


def lookup_parent_norm_preservation_index_v1(
        store, packet_files, preparation, correspondence, *, expected_key_digest, expected_entry_digest, now=None, **options):
    """Look up the original direct-parent23 observational profile, including misses."""
    return _lookup_retained_norm_index(store, packet_files, preparation, correspondence,
        expected_key_digest=expected_key_digest, expected_entry_digest=expected_entry_digest,
        now=now, parent_bound=False, **options)


def _lookup_retained_norm_index(
        store, packet_files, preparation, correspondence, *, expected_key_digest, expected_entry_digest, now=None, parent_bound=False, **options):
    """Retrieve one independently expected exact negative candidate or None.

    A genuine miss still receives closing source replay. Hits do not authorize
    compiler-artifact reuse, accepted outer execution, proofs or training.
    """
    for value in (expected_key_digest, expected_entry_digest):
        _need(type(value) is str and value.startswith("sha256:") and len(value) == 71
              and all(c in "0123456789abcdef" for c in value[7:]), "independent complete parent norm index digest required")
    _need(type(parent_bound) is bool, "exact private index profile selector required")
    argument_fields = _PARENT_BOUND_NORM_INDEX_ARGUMENTS if parent_bound else _PARENT_NORM_INDEX_ARGUMENTS
    now = _timestamp(time.time() if now is None else now)
    _need(set(options) == argument_fields | {"created_at", "expected_packet_observation_sha256"},
          "complete closed parent norm index lookup options required")
    created_at = _timestamp(options["created_at"])
    arguments = {name: options[name] for name in argument_fields}
    guard = _parent_norm_index_guard(packet_files, preparation, correspondence, arguments,
                                      options["expected_packet_observation_sha256"], created_at, parent_bound=parent_bound)
    primary, custody = None, None
    try:
        projection = guard["profile"]["prepare"](packet_files, preparation, correspondence, **options)
        custody = _parent_norm_index_projection_guard(projection, parent_bound=parent_bound)
        if parent_bound:
            guard["activate"]()
        guard["fence"]()
        _need(now >= projection.entry.created_at, "index query time precedes entry creation")
        _need(projection.entry.key.digest == expected_key_digest and projection.entry.entry_digest == expected_entry_digest,
              "independent expected full parent norm observational key or entry differs")
        methods = _parent_norm_index_store_callbacks(store, ("lookup", "get"))
        acknowledgment = store.lookup(projection.entry.key, require_result_authority="candidate",
            max_evidence_authority="none", max_trust_level="none", now=now)
        guard["hold_io"](acknowledgment, acknowledgment=True)
        custody(); guard["fence"]()
        _need(_parent_norm_index_store_callbacks(store, ("lookup", "get")) == methods, "parent norm index backend callbacks changed")
        missed = acknowledgment.hit is False
        if missed:
            _need(acknowledgment.usable is False and acknowledgment.entry is None
                  and acknowledgment.reason.value == "miss" and acknowledgment.key_digest == expected_key_digest,
                  "inconsistent parent norm observational index miss")
        else:
            _acknowledgment(acknowledgment, projection, write=False)
            guard["hold_io"](_full_readback(store, projection, now), acknowledgment=False)
        custody(); guard["fence"]()
        if not missed:
            _acknowledgment(acknowledgment, projection, write=False)
        _need(_parent_norm_index_store_callbacks(store, ("lookup", "get")) == methods, "parent norm index backend callbacks changed")
        again = guard["profile"]["prepare"](packet_files, preparation, correspondence, **options)
        _need(again.projection_json == projection.projection_json, "current parent norm index projection changed after lookup")
        custody(); guard["fence"]()
        if missed:
            _need(acknowledgment.hit is False and acknowledgment.usable is False and acknowledgment.entry is None
                  and acknowledgment.reason.value == "miss" and acknowledgment.key_digest == expected_key_digest,
                  "parent norm observational miss changed across closing replay")
            return None
        _acknowledgment(acknowledgment, projection, write=False)
        result = _parent_norm_index_operation(guard, projection, "lookup")
        custody(); guard["fence"]()
        _acknowledgment(acknowledgment, projection, write=False)
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        finish = (guard["fence"], custody, guard["fence"]) if custody is not None else (guard["fence"],)
        if parent_bound:
            finish += (guard["terminal"],)
        guard["finish"](finish, primary)


__all__ += ["PARENT_NORM_INDEX_SCHEMA", "PARENT_NORM_INDEX_OPERATION_SCHEMA", "PARENT_NORM_INDEX_PROFILE",
            "prepare_parent_norm_preservation_index_v1", "write_parent_norm_preservation_index_v1",
            "lookup_parent_norm_preservation_index_v1"]


def _parent_norm_index_raw_custody(value, store, reader, *, maximum_depth=384, maximum_nodes=4000000):
    """Read existing immutable object storage without overridable serializers."""
    remaining = maximum_nodes
    classes = (RetainedCorpusIndexProjection, RetainedCorpusIndexOperation,
        reader.RetainedDefinitionUsePreservationPacket, store.UnifiedProofEntry, store.UnifiedProofKey,
        store.ProofEvidenceRecord, store.ImmutableEnvelopeReference, store.VerificationCacheLookup,
        store.VerificationCacheEntry, store.VerificationCacheKey)
    enums = (store.ProofOutcomeKind, store.ProofTrustLevel, store.ResultStatus, store.ResultAuthority,
             store.EvidenceAuthority, store.CachePolarity, store.CacheLookupReason)

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= maximum_depth, "bounded raw index custody required")
        cls = type(item)
        if item is None or cls in (str, bytes, bool, int, float):
            _need(cls is not float or math.isfinite(item), "finite raw index scalar required")
            return (cls.__name__, item)
        if cls in (tuple, list):
            return (cls.__name__, tuple(visit(child, depth + 1) for child in item))
        if cls is dict:
            _need(all(type(key) is str for key in item), "ordinary raw custody keys required")
            return ("dict", tuple((key, visit(item[key], depth + 1)) for key in sorted(item)))
        if cls is store.FrozenMap:
            return ("FrozenMap", id(cls), visit(object.__getattribute__(item, "_items"), depth + 1),
                    visit(object.__getattribute__(item, "_hash"), depth + 1))
        if cls in enums:
            return ("enum", id(cls), cls.__name__, object.__getattribute__(item, "_name_"),
                    visit(object.__getattribute__(item, "_value_"), depth + 1))
        _need(cls in classes, "existing exact packet/index/protocol storage class required")
        return ("record", id(cls), cls.__module__, cls.__name__, tuple((name,
            visit(object.__getattribute__(item, name), depth + 1)) for name in cls.__dataclass_fields__))

    return visit(value, 0)


def _parent_norm_index_kwdefaults():
    """Retain typed actual private defaults; IDs alone miss in-place False→0."""
    result = {}
    for function in (_parent_norm_index_profile, _parent_norm_index_flags, _parent_norm_index_callbacks,
                     _parent_norm_index_runtime, _parent_norm_index_guard, _parent_norm_index_projection_guard,
                     _prepare_retained_norm_index, _write_retained_norm_index, _lookup_retained_norm_index,
                     _parent_norm_index_io_value, _parent_norm_index_raw_custody):
        values = getattr(function, "__kwdefaults__", None)
        if values is None:
            result[function.__name__] = None
            continue
        _need(type(values) is dict and len(values) <= 64
              and all(type(key) is str and len(key) <= 128 for key in values),
              "ordinary bounded shared index defaults required")
        _need(all(value is None or type(value) in (str, bool, int, float) for value in values.values()),
              "ordinary shared index policy defaults required")
        result[function.__name__] = dict(values)
    return result


def _parent_norm_index_store_runtime(store):
    dimensions = store.PROOF_AUTHORITY_DIMENSIONS
    return {"dimensions_type": type(dimensions).__name__, "dimensions": list(dimensions),
        "key_schema": store.UNIFIED_PROOF_KEY_SCHEMA_VERSION,
        "entry_schema": store.UNIFIED_PROOF_ENTRY_SCHEMA_VERSION,
        "outcome": store.ProofOutcomeKind.UNKNOWN.value, "trust": store.ProofTrustLevel.NONE.value,
        "evidence_authority": store.EvidenceAuthority.NONE.value,
        "result_authority": store.ResultAuthority.CANDIDATE.value,
        "polarity": store.CachePolarity.NEGATIVE.value}


def _parent_norm_index_io_value(value, store, *, acknowledgment):
    """Snapshot actual protocol objects, preserving bool/int distinctions."""
    if acknowledgment:
        _need(type(value) is store.VerificationCacheLookup, "exact returned cache acknowledgment required")
        if value.entry is not None:
            _need(type(value.entry) is store.VerificationCacheEntry, "exact returned cache entry required")
            value.entry.verify_integrity()
        return {"hit": value.hit, "usable": value.usable, "reason": value.reason.value,
            "key_digest": value.key_digest, "single_flight_shared": value.single_flight_shared,
            "age_seconds": value.age_seconds,
            "entry": None if value.entry is None else value.entry.to_dict()}
    _need(type(value) is store.UnifiedProofEntry, "exact actual unified entry readback required")
    value.verify_integrity()
    return value.to_dict()


def _parent_bound_norm_index_key_material(guard, observation, packet_arguments, flags, expected_packet_observation_sha256):
    """Project the new report/contexts once through the existing15 dimensions."""
    reader, store, manifest = guard["reader"], guard["store"], guard["manifest"]
    return {
        "ir": {"full_parent_preparation_sha256": observation["preparation_full_canonical_sha256"],
            "full_bound_definition_report_sha256": observation["bound_definition_report_sha256"],
            "original_norm": manifest["original_norm"],
            "parent_bound_definition_report_ref": manifest["parent_bound_definition_report_ref"]},
        "property_value": {"profile": PARENT_BOUND_NORM_INDEX_PROFILE, "scope": "receipt consistency only",
            "preservation_kind": observation["preservation_kind"], "proof_scope": observation["proof_scope"],
            "bound_definition_mode": manifest["bound_definition_mode"]},
        "assumptions": {"theorem_assumptions": manifest["theorem_assumptions"],
            "original_parent_context_bindings": manifest["original_parent_context_bindings"],
            "review_blockers": manifest["review_blockers"]},
        "selected_premises": [manifest[name] for name in ("review_intake_binding", "occurrence_binding",
            "selected_link", "definition_alternative_refs", "nomination_inventory", "original_parent_context_bindings")],
        "translator": {"producer_pins": guard["producer_pins"], "native_producer_pins": manifest["native_producer_pins"]},
        "solver_identities": {"historical_binary_sha256": observation["expected_binary_sha256"],
            "historical_native_profile": observation["historical_native_receipt"]["profile"], "fresh_solver_execution": False},
        "toolchain": {"toolchain": observation["toolchain"], "binary_sha256": observation["expected_binary_sha256"]},
        "theorem_registry": {name: manifest[name] for name in
            ("conditional_theorems", "conditional_theorem_statements", "expected_modules", "module_imports", "native_fragments")},
        "policy": {"complete_original_inputs_sha256": guard["input_digest"],
            "complete_packet_arguments_sha256": guard["argument_digest"],
            "original_input_commitment_sha256": manifest["original_input_commitment_sha256"],
            "review_intake_binding": manifest["review_intake_binding"], "review_blockers": manifest["review_blockers"],
            "conditional_source_binding": manifest["conditional_source_binding"],
            "bound_definition_mode": manifest["bound_definition_mode"],
            "selected_interpretation": manifest["selected_interpretation"],
            "governing_definition_use": manifest["governing_definition_use"],
            "norm_interpretation_ready": manifest["norm_interpretation_ready"],
            "source_custody": observation["source_custody"], "authority": dict(reader.AUTHORITY), **flags},
        "resources": {"packet_inventory": observation["packet_inventory"], "max_packet_bytes": reader.MAX_PACKET_BYTES,
            "max_original_input_bytes": reader.MAX_INPUT_BYTES, "max_index_record_bytes": MAX_RECORD_BYTES},
        "tree": {"packet_bundle_sha256": observation["packet_bundle_sha256"],
            "receipt_file_sha256": observation["receipt_file_sha256"],
            "packet_observation_file_sha256": expected_packet_observation_sha256,
            "bound_definition_report_sha256": observation["bound_definition_report_sha256"],
            "retained_manifest_field_sha256": observation["retained_manifest_field_sha256"]},
        "backend_id": "legal_ir_retained_parent_bound_norm_definition_receipt_consistency",
        "backend_binary": observation["expected_binary_sha256"], "backend_version": PARENT_BOUND_NORM_INDEX_PROFILE,
        "backend_config": {"schema": PARENT_BOUND_NORM_INDEX_SCHEMA, "owner_sha256": _SELF_PIN,
            "store_owner_sha256": _sha(Path(store.__file__).read_bytes()), "status": "unknown",
            "result_authority": "candidate", "evidence_authority": "none", "trust_level": "none",
            "kernel_accepted": False, "deterministic_trusted": False, **flags}}


def prepare_parent_bound_norm_definition_preservation_index_v1(
        packet_files, preparation, bound_report, *, expected_packet_observation_sha256, created_at, **packet_arguments):
    """Prepare only negative receipt-consistency evidence for the explicit29-file profile."""
    return _prepare_retained_norm_index(packet_files, preparation, bound_report,
        expected_packet_observation_sha256=expected_packet_observation_sha256,
        created_at=created_at, parent_bound=True, **packet_arguments)


def write_parent_bound_norm_definition_preservation_index_v1(
        store, packet_files, preparation, bound_report, *, now=None, **options):
    """Write the exact unaccepted29-file observation through the caller's existing store."""
    return _write_retained_norm_index(store, packet_files, preparation, bound_report,
        now=now, parent_bound=True, **options)


def lookup_parent_bound_norm_definition_preservation_index_v1(
        store, packet_files, preparation, bound_report, *, expected_key_digest, expected_entry_digest, now=None, **options):
    """Retrieve an exact negative candidate or closing-replayed genuine miss."""
    return _lookup_retained_norm_index(store, packet_files, preparation, bound_report,
        expected_key_digest=expected_key_digest, expected_entry_digest=expected_entry_digest,
        now=now, parent_bound=True, **options)


__all__ += ["PARENT_BOUND_NORM_INDEX_SCHEMA", "PARENT_BOUND_NORM_INDEX_OPERATION_SCHEMA", "PARENT_BOUND_NORM_INDEX_PROFILE",
    "prepare_parent_bound_norm_definition_preservation_index_v1", "write_parent_bound_norm_definition_preservation_index_v1",
    "lookup_parent_bound_norm_definition_preservation_index_v1"]
