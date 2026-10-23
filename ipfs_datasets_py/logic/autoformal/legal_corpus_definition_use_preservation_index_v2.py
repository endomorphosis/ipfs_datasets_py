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
