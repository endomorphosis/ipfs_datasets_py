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


def _parent_norm_index_flags(reader):
    return {**reader.FALSE_FLAGS, "receipt_consistency_only": True,
            "accepted_execution": False, "accepted_outer_operation": False,
            "accepted_operation_result_bound": False, "outer_operation_outcome": "unprovided"}


def _parent_norm_index_callbacks(reader, store, contracts, native_owners, finish):
    functions = (_need, _sha, _wire, _tree_digest, _timestamp, _owners, _full_readback, _acknowledgment,
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
    return current + reader._parent_norm_packet_callbacks(native_owners)


def _parent_norm_index_runtime(reader):
    return {"schema": PARENT_NORM_INDEX_SCHEMA, "operation_schema": PARENT_NORM_INDEX_OPERATION_SCHEMA,
            "profile": PARENT_NORM_INDEX_PROFILE, "arguments": sorted(_PARENT_NORM_INDEX_ARGUMENTS),
            "max_record_bytes": MAX_RECORD_BYTES, "flags": _parent_norm_index_flags(reader),
            "authority": dict(reader.AUTHORITY), "owner_sha256": _SELF_PIN,
            "reader_schema": reader.PARENT_NORM_PACKET_SCHEMA, "reader_profile": reader.PARENT_NORM_PACKET_PROFILE,
            "owner_path": str(Path(__file__).resolve()), "reader_path": str(Path(reader.__file__).resolve())}


def _parent_norm_index_store_callbacks(store, names):
    functions = []
    for name in names:
        callback = getattr(store, name)
        function = getattr(callback, "__func__", callback)
        functions.append((function, getattr(function, "__code__", None),
                          id(getattr(function, "__defaults__", None)), id(getattr(function, "__kwdefaults__", None))))
    return tuple(functions)


def _parent_norm_index_guard(packet_files, preparation, correspondence, packet_arguments,
                             expected_packet_observation_sha256, created_at):
    """Bind complete originals and current owners across every external callback."""
    _need(_sha(Path(__file__).read_bytes()) == _SELF_PIN, "parent norm index owner changed since import")
    _need(set(packet_arguments) == _PARENT_NORM_INDEX_ARGUMENTS,
          "complete closed parent norm packet replay arguments required")
    from . import legal_corpus_definition_use_preservation_packet_v2 as reader
    reader._pin(expected_packet_observation_sha256, "complete current parent norm packet observation")
    for name in ("expected_preparation_sha256", "expected_correspondence_sha256",
                 "expected_receipt_file_sha256", "expected_bundle_sha256"):
        reader._pin(packet_arguments[name], "original parent norm index " + name)
    reader._binary_map(packet_arguments["expected_binary_sha256"])
    _need(type(packet_arguments["toolchain"]) is str and len(packet_arguments["toolchain"]) <= 128
          and reader._TOOLCHAIN.fullmatch(packet_arguments["toolchain"]), "version-pinned parent norm index toolchain required")
    reader._keys(packet_arguments["correspondence_inputs"], reader._PARENT_NORM_PACKET_REPLAY_FIELDS,
                 "complete original parent correspondence replay")
    storage = reader._parent_norm_packet_storage(preparation)
    manifest = reader._parse(storage["manifest_json"].encode("utf-8"))

    def inputs():
        value = {"preparation": reader._parent_norm_packet_storage(preparation),
                 "correspondence": correspondence, "packet_arguments": packet_arguments,
                 "expected_packet_observation_sha256": expected_packet_observation_sha256,
                 "created_at": created_at}
        reader._bound_tree(value, reader.MAX_INPUT_BYTES, allow_bytes=True)
        return value

    original = inputs()
    original_digest, argument_digest = _tree_digest(original), _tree_digest(packet_arguments)
    semantic_digest = _tree_digest({name: value for name, value in original.items() if name != "created_at"})
    files, inventory = reader._parent_norm_packet_document(packet_files)
    _need(reader.parent_norm_packet_sha256(packet_files) == packet_arguments["expected_bundle_sha256"]
          and _sha(files["build-receipt.json"]) == packet_arguments["expected_receipt_file_sha256"],
          "independent complete parent norm index packet or receipt pin differs")
    _need(_sha(reader._wire({"manifest": manifest, "files": storage["files"]}, 20 * reader.MAX_RECORD_BYTES))
          == packet_arguments["expected_preparation_sha256"]
          and _sha(reader._wire(correspondence, reader.MAX_PROJECT_BYTES))
          == packet_arguments["expected_correspondence_sha256"],
          "independent complete parent norm index preparation/correspondence pins differ")
    # Bounds and independent original-byte pins precede lazy loading. No owner
    # here starts a database, process, solver, model or numerical kernel.
    native_owners = reader._parent_norm_packet_owners()
    native, contracts = native_owners
    preparer = native._owners()[0]
    _, store, same_contracts = _owners()
    _need(same_contracts is contracts, "same canonical parent norm record owner required")
    from . import legal_norm_scope_correspondence_v1 as correspondence_owner
    finish = correspondence_owner._owners()[0]._parent_finish
    paths = {str(Path(__file__).resolve()): _SELF_PIN,
             str(Path(reader.__file__).resolve()): reader._SELF_PIN,
             str(Path(store.__file__).resolve()): _sha(Path(store.__file__).read_bytes())}
    plan = preparer._parent_norm_file_plan(packet_arguments["correspondence_inputs"])
    witness = preparer._parent_norm_file_witness(plan)
    current = native._parent_norm_native_pins(native._owners(), manifest)
    callbacks = _parent_norm_index_callbacks(reader, store, contracts, native_owners, finish)
    reader_runtime = reader._parent_norm_packet_runtime(native_owners)
    runtime = _parent_norm_index_runtime(reader)
    owner_paths = (str(Path(__file__).resolve()), str(Path(reader.__file__).resolve()), str(Path(store.__file__).resolve()))
    store_runtime = (store.PROOF_AUTHORITY_DIMENSIONS, store.UNIFIED_PROOF_KEY_SCHEMA_VERSION,
                     store.UNIFIED_PROOF_ENTRY_SCHEMA_VERSION, store.ProofOutcomeKind.UNKNOWN.value,
                     store.ProofTrustLevel.NONE.value, store.EvidenceAuthority.NONE.value,
                     store.ResultAuthority.CANDIDATE.value, store.CachePolarity.NEGATIVE.value)
    held, results = [], []

    def hold_result(value, cls, fields):
        _need(type(value) is cls, "exact parent norm index result custody type required")
        results.append((value, cls, dict(fields)))

    def hold(value, label):
        reader._bound_tree(value, MAX_RECORD_BYTES)
        held.append((value, reader._review_snapshot(value), label))
        return value

    hold(manifest, "complete original parent norm manifest")
    hold(plan, "complete original parent norm physical witness plan")
    hold(witness, "original parent norm physical source identities")
    hold(current, "current genuine parent norm producer pins")
    hold(paths, "index/reader/store owner source pins")

    def fence():
        _need(_parent_norm_index_callbacks(reader, store, contracts, native_owners, finish) == callbacks
              and _parent_norm_index_runtime(reader) == runtime
              and reader._parent_norm_packet_runtime(native_owners) == reader_runtime,
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
        _need(reader.parent_norm_packet_sha256(packet_files) == packet_arguments["expected_bundle_sha256"],
              "original parent norm index packet changed")
        for path, expected in paths.items():
            _need(_sha(Path(path).read_bytes()) == expected, "parent norm index/reader/store source changed")
        _need(native._parent_norm_native_pins(native._owners(), manifest) == current,
              "current parent norm index producer source identities changed")
        _need(preparer._parent_norm_file_witness(plan) == witness,
              "original parent norm index physical source witnesses changed")
        for result, cls, fields in results:
            _need(type(result) is cls, "parent norm index result type changed")
            data = object.__getattribute__(result, "__dict__")
            _need(set(data) == set(fields) and all(
                type(data[name]) is str and data[name] == expected if type(expected) is str else data[name] is expected
                for name, expected in fields.items()), "actual parent norm index result storage changed")
        for value, expected, label in held:
            reader._bound_tree(value, MAX_RECORD_BYTES)
            _need(reader._review_snapshot(value) == expected, "held parent norm index value changed: " + label)

    fence()
    return {"reader": reader, "store": store, "contracts": contracts, "manifest": manifest,
            "input_digest": semantic_digest, "argument_digest": argument_digest,
            "producer_pins": {**current, **paths}, "fence": fence, "hold": hold, "hold_result": hold_result, "finish": finish}


def prepare_parent_norm_preservation_index_v1(
        packet_files, preparation, correspondence, *, expected_packet_observation_sha256,
        created_at, **packet_arguments):
    """Project direct-parent receipt consistency into UNKNOWN/NONE storage.

    All packet/preparation/correspondence pins and the separately trusted raw
    observation pin are required. A negative candidate hit is retrievable
    engineering evidence only; an accepted outer operation remains unprovided.
    No default official-V2 projection, source interpretation or proof is changed.
    """
    created_at = _timestamp(created_at)
    guard = _parent_norm_index_guard(packet_files, preparation, correspondence, packet_arguments,
                                      expected_packet_observation_sha256, created_at)
    reader, store, contracts = guard["reader"], guard["store"], guard["contracts"]
    fence, hold = guard["fence"], guard["hold"]
    state, primary = {}, None

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
        retained = reader.validate_parent_norm_native_packet_v1(
            packet_files, preparation, correspondence, **packet_arguments)
        fence()
        _need(type(retained) is reader.RetainedDefinitionUsePreservationPacket
              and retained.files == packet_files, "genuine complete direct parent norm packet result required")
        observation_raw = retained.observation_json.encode("utf-8")
        _need(_sha(observation_raw) == expected_packet_observation_sha256,
              "independent exact current parent norm packet-observation pin differs")
        observation = hold(retained.to_dict(), "complete current parent norm packet observation")
        _need(observation["schema"] == reader.PARENT_NORM_PACKET_SCHEMA
              and observation["profile"] == reader.PARENT_NORM_PACKET_PROFILE
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
              and observation["correspondence_sha256"] == packet_arguments["expected_correspondence_sha256"]
              and observation["toolchain"] == packet_arguments["toolchain"]
              and observation["expected_binary_sha256"] == packet_arguments["expected_binary_sha256"]
              and {**observation["current_producer_pins"], str(Path(__file__).resolve()): _SELF_PIN,
                   str(Path(store.__file__).resolve()): _sha(Path(store.__file__).read_bytes())} == guard["producer_pins"],
              "parent norm packet observation differs from complete current input/producer pins")
        manifest = guard["manifest"]
        flags = _parent_norm_index_flags(reader)
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
        payload = hold({"schema": PARENT_NORM_INDEX_SCHEMA, "profile": PARENT_NORM_INDEX_PROFILE,
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
        state["entry"], state["entry_wire"] = entry, _wire(entry.to_dict())
        record_input = hold({"schema": PARENT_NORM_INDEX_SCHEMA, "profile": PARENT_NORM_INDEX_PROFILE,
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
        contracts.validate_record(record, schema=PARENT_NORM_INDEX_SCHEMA,
                                  fields=set(record) - {"schema", "record_cid", "cid_scope"})
        hold(record, "sealed complete parent norm projection")
        state["record"], state["wire"] = record, _wire(record)
        fence(); serialized_fence()
        result = RetainedCorpusIndexProjection(state["wire"].decode("utf-8"), entry)
        state["result"] = result
        fence(); serialized_fence()
        return result
    except BaseException as error:
        primary = error
        raise
    finally:
        guard["finish"]((fence, serialized_fence, fence, serialized_fence), primary)


def _parent_norm_index_projection_guard(projection):
    """Retain actual projection and entry storage, beyond its serialized copy."""
    _need(type(projection) is RetainedCorpusIndexProjection, "exact parent norm projection custody required")
    original_json, entry = projection.projection_json, projection.entry
    entry_wire = _wire(entry.to_dict())
    document = json.loads(original_json)
    _need(document["schema"] == PARENT_NORM_INDEX_SCHEMA and document["profile"] == PARENT_NORM_INDEX_PROFILE
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
    reader, contracts = guard["reader"], guard["contracts"]
    _need(type(projection) is RetainedCorpusIndexProjection and operation in ("write", "lookup"),
          "genuine direct parent norm index operation projection required")
    before = projection.projection_json
    entry_wire = _wire(projection.entry.to_dict())
    fields = {"schema": PARENT_NORM_INDEX_OPERATION_SCHEMA, "profile": PARENT_NORM_INDEX_PROFILE,
        "operation": operation, "key_digest": projection.entry.key.digest, "entry_digest": projection.entry.entry_digest,
        "index_write_acknowledged": operation == "write", "index_lookup_acknowledged": operation == "lookup",
        "full_entry_readback_verified": True, "current_packet_replayed_before_and_after": True,
        "observation_retrievable": True, "proof_usable": False, "durable_storage_verified": False,
        "authority": dict(reader.AUTHORITY), "training_mask": 0, "evaluation_gold_mask": 0,
        **_parent_norm_index_flags(reader)}
    guard["hold"](fields, "complete parent norm operation seal input")
    record = contracts.seal_record(fields)
    reader._keys(record, set(fields) | {"record_cid", "cid_scope"}, "sealed parent norm index operation")
    _need(_wire({name: record[name] for name in fields}) == _wire(fields),
          "sealed parent norm operation differs from original input")
    contracts.validate_record(record, schema=PARENT_NORM_INDEX_OPERATION_SCHEMA,
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
    """Write one exact negative candidate, with full readback and closing replay.

    A callback failure may leave a stored observational row. No successful
    operation receipt or transaction spanning the caller's store is implied.
    """
    now = _timestamp(time.time() if now is None else now)
    _need(set(options) == _PARENT_NORM_INDEX_ARGUMENTS | {"created_at", "expected_packet_observation_sha256"},
          "complete closed parent norm index write options required")
    created_at = _timestamp(options["created_at"])
    arguments = {name: options[name] for name in _PARENT_NORM_INDEX_ARGUMENTS}
    guard = _parent_norm_index_guard(packet_files, preparation, correspondence, arguments,
                                      options["expected_packet_observation_sha256"], created_at)
    primary, custody = None, None
    try:
        projection = prepare_parent_norm_preservation_index_v1(packet_files, preparation, correspondence, **options)
        custody = _parent_norm_index_projection_guard(projection)
        guard["fence"]()
        _need(now >= projection.entry.created_at, "index query time precedes entry creation")
        methods = _parent_norm_index_store_callbacks(store, ("put", "get"))
        acknowledgment = store.put(projection.entry, now=now)
        custody(); guard["fence"]()
        _need(_parent_norm_index_store_callbacks(store, ("put", "get")) == methods, "parent norm index backend callbacks changed")
        _acknowledgment(acknowledgment, projection, write=True)
        _full_readback(store, projection, now)
        custody(); guard["fence"]()
        _acknowledgment(acknowledgment, projection, write=True)
        _need(_parent_norm_index_store_callbacks(store, ("put", "get")) == methods, "parent norm index backend callbacks changed")
        again = prepare_parent_norm_preservation_index_v1(packet_files, preparation, correspondence, **options)
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
        guard["finish"](finish, primary)


def lookup_parent_norm_preservation_index_v1(
        store, packet_files, preparation, correspondence, *, expected_key_digest, expected_entry_digest, now=None, **options):
    """Retrieve one independently expected exact negative candidate or None.

    A genuine miss still receives closing source replay. Hits do not authorize
    compiler-artifact reuse, accepted outer execution, proofs or training.
    """
    for value in (expected_key_digest, expected_entry_digest):
        _need(type(value) is str and value.startswith("sha256:") and len(value) == 71
              and all(c in "0123456789abcdef" for c in value[7:]), "independent complete parent norm index digest required")
    now = _timestamp(time.time() if now is None else now)
    _need(set(options) == _PARENT_NORM_INDEX_ARGUMENTS | {"created_at", "expected_packet_observation_sha256"},
          "complete closed parent norm index lookup options required")
    created_at = _timestamp(options["created_at"])
    arguments = {name: options[name] for name in _PARENT_NORM_INDEX_ARGUMENTS}
    guard = _parent_norm_index_guard(packet_files, preparation, correspondence, arguments,
                                      options["expected_packet_observation_sha256"], created_at)
    primary, custody = None, None
    try:
        projection = prepare_parent_norm_preservation_index_v1(packet_files, preparation, correspondence, **options)
        custody = _parent_norm_index_projection_guard(projection)
        guard["fence"]()
        _need(now >= projection.entry.created_at, "index query time precedes entry creation")
        _need(projection.entry.key.digest == expected_key_digest and projection.entry.entry_digest == expected_entry_digest,
              "independent expected full parent norm observational key or entry differs")
        methods = _parent_norm_index_store_callbacks(store, ("lookup", "get"))
        acknowledgment = store.lookup(projection.entry.key, require_result_authority="candidate",
            max_evidence_authority="none", max_trust_level="none", now=now)
        custody(); guard["fence"]()
        _need(_parent_norm_index_store_callbacks(store, ("lookup", "get")) == methods, "parent norm index backend callbacks changed")
        missed = acknowledgment.hit is False
        if missed:
            _need(acknowledgment.usable is False and acknowledgment.entry is None
                  and acknowledgment.reason.value == "miss" and acknowledgment.key_digest == expected_key_digest,
                  "inconsistent parent norm observational index miss")
        else:
            _acknowledgment(acknowledgment, projection, write=False)
            _full_readback(store, projection, now)
        custody(); guard["fence"]()
        if not missed:
            _acknowledgment(acknowledgment, projection, write=False)
        _need(_parent_norm_index_store_callbacks(store, ("lookup", "get")) == methods, "parent norm index backend callbacks changed")
        again = prepare_parent_norm_preservation_index_v1(packet_files, preparation, correspondence, **options)
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
        guard["finish"](finish, primary)


__all__ += ["PARENT_NORM_INDEX_SCHEMA", "PARENT_NORM_INDEX_OPERATION_SCHEMA", "PARENT_NORM_INDEX_PROFILE",
            "prepare_parent_norm_preservation_index_v1", "write_parent_norm_preservation_index_v1",
            "lookup_parent_norm_preservation_index_v1"]


# Observational projection of the packet compatibility export. No store write or compiler.
LEAN_COMPATIBILITY_INDEX_SCHEMA = "legal-lean-compatibility-index-projection/v1"
LEAN_COMPATIBILITY_INDEX_PROFILE = "retained-lean-compatibility-request-index/v1"
_LEAN_INDEX_FIELDS = frozenset({
    "schema", "profile", "report_sha256", "key_sha256", "rows", "store_write", "compiler_invoked",
    "lean_admitted", "legal_admission", "admitted", "formalized", "semantic_preservation_claimed",
})
_LEAN_INDEX_ROW_FIELDS = frozenset({
    "candidate_id", "profile", "ast_sha256", "ast_kind", "route", "disposition", "closure_bound",
    "retained_evidence_ids", "unresolved_prerequisites", "admission_blocked", "lean_admitted",
    "legal_admission", "admitted", "formalized", "compiler_invoked",
})


def prepare_lean_compatibility_index_v1(request_raw, *, expected_request_sha256):
    """Project one compatibility report. Do not write storage or invoke a compiler."""
    from . import legal_corpus_definition_use_preservation_packet_v2 as packet
    report = packet.prepare_lean_compatibility_request_v1(
        request_raw, expected_request_sha256=expected_request_sha256)
    _need(type(report) is dict and set(report) == {
        "compatibility_matrix", "request_import_premise_axiom_closure", "artifact_closure",
        "unresolved_questions", "reuse_owners"}, "closed compatibility report required")
    matrix = report["compatibility_matrix"]
    _need(type(matrix) is list and matrix, "compatibility matrix required")
    rows = []
    for row in matrix:
        _need(type(row) is dict and row["lean_admitted"] is False and row["legal_admission"] is False
              and row["admitted"] is False and row["formalized"] is False
              and row["compiler_invoked"] is False and row["semantic_preservation_claimed"] is False
              and row["selected_ast_replaced"] is False and row["unresolved_prerequisites"],
              "unresolved prerequisites block Lean and legal admission")
        projected = {
            "candidate_id": row["candidate_id"], "profile": row["profile"],
            "ast_sha256": row["ast_sha256"], "ast_kind": row["ast_kind"], "route": row["route"],
            "disposition": row["disposition"], "closure_bound": row["closure_bound"],
            "retained_evidence_ids": list(row["retained_evidence_ids"]),
            "unresolved_prerequisites": list(row["unresolved_prerequisites"]),
            "admission_blocked": True, "lean_admitted": False, "legal_admission": False,
            "admitted": False, "formalized": False, "compiler_invoked": False,
        }
        _need(set(projected) == _LEAN_INDEX_ROW_FIELDS, "closed compatibility index row required")
        rows.append(projected)
    projection = {
        "schema": LEAN_COMPATIBILITY_INDEX_SCHEMA, "profile": LEAN_COMPATIBILITY_INDEX_PROFILE,
        "report_sha256": packet.lean_compatibility_request_sha256(report),
        "key_sha256": _sha(_wire(rows)), "rows": rows, "store_write": False,
        "compiler_invoked": False, "lean_admitted": False, "legal_admission": False,
        "admitted": False, "formalized": False, "semantic_preservation_claimed": False,
    }
    _need(set(projection) == _LEAN_INDEX_FIELDS, "closed compatibility index projection required")
    return json.loads(_wire(projection))


def lean_compatibility_index_sha256(projection):
    """Hash one compatibility projection without opening a store."""
    _need(type(projection) is dict and set(projection) == _LEAN_INDEX_FIELDS
          and projection["schema"] == LEAN_COMPATIBILITY_INDEX_SCHEMA
          and projection["profile"] == LEAN_COMPATIBILITY_INDEX_PROFILE,
          "explicit compatibility index projection required")
    return _sha(_wire(projection))


def validate_lean_compatibility_index_v1(projection, request_raw, *, expected_request_sha256,
                                         expected_projection_sha256):
    """Require an independent projection pin and complete regeneration."""
    _need(type(expected_projection_sha256) is str and len(expected_projection_sha256) == 64
          and all(character in "0123456789abcdef" for character in expected_projection_sha256),
          "independent compatibility index digest required")
    _need(lean_compatibility_index_sha256(projection) == expected_projection_sha256,
          "compatibility index projection SHA256 mismatch")
    original = _wire(projection)
    regenerated = prepare_lean_compatibility_index_v1(
        request_raw, expected_request_sha256=expected_request_sha256)
    _need(_wire(regenerated) == original,
          "compatibility index projection differs from complete regeneration")
    return regenerated


__all__ += ["LEAN_COMPATIBILITY_INDEX_SCHEMA", "LEAN_COMPATIBILITY_INDEX_PROFILE",
            "prepare_lean_compatibility_index_v1", "lean_compatibility_index_sha256",
            "validate_lean_compatibility_index_v1"]
