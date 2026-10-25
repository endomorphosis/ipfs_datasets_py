"""Exact observational indexing, with genuine source/review packet replay.

The retained packets below deliberately contain synthetic historical compiler
observations and artifact bytes. Independent unit pins establish their exact
identity, never actual compilation, statutory correspondence or proof authority.
Current preparation and the process-local DuckDBProofStore run unmocked.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_index_v2 as owner
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_native_v2 as native
from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_preservation_packet_v2 as packet_owner
from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.common.duckdb_proof_store import (
    DuckDBProofStore, ProofOutcomeKind, ProofTrustLevel, UnifiedProofEntry,
)
from ipfs_datasets_py.logic.backends.cache_protocol import CachePolarity
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.families.models import EvidenceAuthority


_SPEC = importlib.util.spec_from_file_location(
    "_genuine_preservation_index_packet_fixtures",
    Path(__file__).with_name("test_legal_corpus_definition_use_preservation_packet_v2.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _FIXTURE
_SPEC.loader.exec_module(_FIXTURE)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module")
def packets():
    return {family: _FIXTURE.synthetic_packet(family) for family in ("fol", "tdfol")}


@pytest.fixture(scope="module")
def inputs(packets):
    return {
        family: _FIXTURE.arguments(packet) | {
            "expected_packet_observation_sha256": sha(_FIXTURE.read(packet).observation_json.encode()),
            "created_at": 1_792_100_000.0,
        }
        for family, packet in packets.items()
    }


@pytest.fixture(scope="module")
def projections(packets, inputs):
    return {family: prepare(packet, inputs[family]) for family, packet in packets.items()}


@pytest.fixture
def base(packets):
    return packets["fol"]


@pytest.fixture
def no_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("observational index reached compiler, identity probe or model/database import")
    monkeypatch.setattr(native, "build_definition_use_preservation_native_v2", forbidden)
    monkeypatch.setattr(native, "_installed_toolchain", forbidden)
    monkeypatch.setattr(native, "_binary_recheck", forbidden)
    monkeypatch.setattr(process.BoundedToolRunner, "run", forbidden)
    monkeypatch.setattr(process, "_linux_owned_identity", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    class DenyBackendImport:
        def find_spec(self, fullname, path=None, target=None):
            if any(fullname == name or fullname.startswith(name + ".")
                   for name in ("duckdb", "torch", "transformers")):
                forbidden()
    deny = DenyBackendImport()
    sys.meta_path.insert(0, deny)
    yield
    sys.meta_path.remove(deny)


class CountingStore(DuckDBProofStore):
    def __init__(self):
        super().__init__(positive_ttl_seconds=0, negative_ttl_seconds=0)
        self.calls = []

    def put(self, entry, **kwargs):
        self.calls.append("put")
        return super().put(entry, **kwargs)

    def get(self, key, **kwargs):
        self.calls.append("get")
        return super().get(key, **kwargs)

    def lookup(self, key, **kwargs):
        self.calls.append("lookup")
        return super().lookup(key, **kwargs)


def prepare(base, arguments, **overrides):
    return owner.prepare_definition_use_preservation_index_v2(
        base.files, base.data["corpus_preparation"], base.data["assessment_raw"],
        **(arguments | overrides),
    )


def write(store, base, arguments, **overrides):
    return owner.write_definition_use_preservation_index_v2(
        store, base.files, base.data["corpus_preparation"], base.data["assessment_raw"],
        **(arguments | {"now": arguments["created_at"] + 1} | overrides),
    )


def lookup(store, base, arguments, projection, **overrides):
    return owner.lookup_definition_use_preservation_index_v2(
        store, base.files, base.data["corpus_preparation"], base.data["assessment_raw"],
        **(arguments | {"expected_key_digest": projection.entry.key.digest,
                       "expected_entry_digest": projection.entry.entry_digest,
                       "now": arguments["created_at"] + 1} | overrides),
    )


def test_public_import_is_stdlib_only():
    code = r"""
import importlib.util,sys
blocked=('ipfs_datasets_py','torch','transformers','numpy','cryptography','multiformats','pyarrow','duckdb','requests')
class Deny:
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==name or fullname.startswith(name+'.') for name in blocked):
            raise AssertionError('operation owner reached: '+fullname)
sys.meta_path.insert(0,Deny())
spec=importlib.util.spec_from_file_location('_index_cold',sys.argv[1])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
spec.loader.exec_module(module)
for name in ('RetainedCorpusIndexProjection','RetainedCorpusIndexOperation',
             'prepare_definition_use_preservation_index_v2',
             'write_definition_use_preservation_index_v2',
             'lookup_definition_use_preservation_index_v2'):
    assert hasattr(module,name),name
assert not any(any(name==prefix or name.startswith(prefix+'.') for prefix in blocked) for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, owner.__file__],
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_genuine_packet_projection_has_no_proof_authority(family, packets, inputs, projections, no_execution):
    projection = projections[family]
    entry = projection.entry
    assert isinstance(entry, UnifiedProofEntry)
    assert entry.outcome is ProofOutcomeKind.UNKNOWN
    assert entry.status is ResultStatus.UNKNOWN
    assert entry.result_authority is ResultAuthority.CANDIDATE
    assert entry.evidence_authority is EvidenceAuthority.NONE
    assert entry.trust_level is ProofTrustLevel.NONE
    assert entry.polarity is CachePolarity.NEGATIVE
    assert entry.created_at == inputs[family]["created_at"]
    assert len(entry.key.dimension_map()) == 15
    assert entry.verify_integrity() is entry
    assert entry.evidence and all(item.evidence_authority is EvidenceAuthority.NONE for item in entry.evidence)
    value = projection.to_dict()
    assert value["training_mask"] == value["evaluation_gold_mask"] == 0
    assert all(value[name] is False for name in packet_owner.FALSE_FLAGS)
    assert entry.envelope is not None
    assert entry.envelope.content_digest == "sha256:" + inputs[family]["expected_packet_observation_sha256"]
    assert entry.envelope.content_id == entry.envelope.content_digest
    assert entry.envelope.media_type == "application/json"
    assert len(entry.evidence) == 1
    assert entry.evidence[0].content_digest == "sha256:" + inputs[family]["expected_receipt_file_sha256"]
    assert entry.evidence[0].evidence_kind == "unreviewed_runtime_observation"
    assert _FIXTURE.sha(dict(packets[family].files)["build-receipt.json"]) == inputs[family]["expected_receipt_file_sha256"]


@pytest.mark.parametrize("family", ("fol", "tdfol"))
def test_genuine_store_write_and_lookup_preserve_projection(family, packets, inputs, projections, no_execution):
    store = CountingStore()
    operation = write(store, packets[family], inputs[family])
    assert operation.projection == projections[family]
    assert store.stats()["writes"] == 1
    observed = lookup(store, packets[family], inputs[family], projections[family])
    assert observed is not None
    assert observed.projection == projections[family]
    assert observed.projection.entry.result_authority is ResultAuthority.CANDIDATE
    assert observed.projection.entry.status is ResultStatus.UNKNOWN
    assert all(observed.to_dict()[name] is False for name in packet_owner.FALSE_FLAGS)
    assert "put" in store.calls and "get" in store.calls and "lookup" in store.calls


KEY_FIELDS = (
    "ir_digest", "property_digest", "assumptions_digest", "selected_premise_digests",
    "translator_digest", "solver_identities_digest", "toolchain_identity_digest",
    "theorem_registry_digest", "policy_digest", "resources_digest", "tree_digest",
    "backend_id", "backend_binary_digest", "backend_version", "backend_config_digest",
)


@pytest.mark.parametrize("dimension", KEY_FIELDS)
def test_each_full_key_dimension_forces_genuine_store_miss(dimension, projections):
    entry = projections["fol"].entry
    changed = ("sha256:" + "9" * 64,) if dimension == "selected_premise_digests" else (
        "changed-observation-profile" if dimension in {"backend_id", "backend_version"}
        else "sha256:" + "9" * 64)
    mutant = replace(entry.key, **{dimension: changed})
    assert mutant.digest != entry.key.digest
    store = CountingStore()
    store.put(entry)
    assert store.get(mutant) is None
    assert store.get(entry.key) == entry


def test_projection_determinism_and_family_separation(base, inputs, projections, no_execution):
    again = prepare(base, inputs["fol"])
    assert again == projections["fol"]
    assert projections["fol"].entry.key.digest != projections["tdfol"].entry.key.digest
    assert projections["fol"].entry.entry_digest != projections["tdfol"].entry.entry_digest
    # A protocol projection may encode fifteen dimensions, but its digest is a
    # different identity and must never substitute for the full unified key.
    assert again.entry.key.to_verification_cache_key().digest != again.entry.key.digest


def test_key_material_retains_actual_source_review_role_theorem_and_packet_bindings(base, inputs, projections):
    entry = projections["fol"].entry
    payload = entry.result_payload.to_dict()
    material = payload["key_material"]
    manifest = json.loads(dict(base.files)["project/corpus-manifest.json"])
    assert material["ir"]["full_corpus_preparation_sha256"] == inputs["fol"]["expected_corpus_preparation_sha256"]
    assert material["ir"]["full_preservation_preparation_sha256"] == inputs["fol"]["expected_preparation_sha256"]
    assert material["ir"]["engineering_reference"] == manifest["reference_contract"]["key_material"]
    assert material["property_value"]["preservation_fragments"] == manifest["preservation_fragments"]
    assert material["property_value"]["theorems"] == manifest["theorems"]
    assert material["assumptions"]["theorem_assumptions"] == manifest["theorem_assumptions"]
    assert material["assumptions"]["original_preparation_state"] == manifest["original_preparation_state"]
    assert material["selected_premises"] == manifest["review_dependency_manifest"]["artifacts"]
    assert material["translator"]["semantics_sha256"] == manifest["semantics_sha256"]
    assert material["policy"]["review_intake_binding"] == manifest["review_intake_binding"]
    assert material["policy"]["review_dependency_manifest"] == manifest["review_dependency_manifest"]
    assert material["policy"]["assessment_file_sha256"] == inputs["fol"]["expected_assessment_file_sha256"]
    assert material["tree"] == {
        "packet_bundle_sha256": inputs["fol"]["expected_bundle_sha256"],
        "receipt_file_sha256": inputs["fol"]["expected_receipt_file_sha256"],
        "packet_observation_file_sha256": inputs["fol"]["expected_packet_observation_sha256"],
    }
    assert material["solver_identities"]["historical_binary_sha256"] == _FIXTURE.BINARIES
    assert material["backend_binary"] == _FIXTURE.BINARIES
    assert material["toolchain"] == {"toolchain": _FIXTURE.TOOLCHAIN, "binary_sha256": _FIXTURE.BINARIES}
    assert material["theorem_registry"] == {name: manifest[name] for name in
        ("theorems", "conditional_theorems", "preservation_theorems", "expected_modules", "module_imports")}
    assert material["resources"]["packet_inventory"] == [
        {"path": path, "bytes": len(raw), "sha256": sha(raw)} for path, raw in base.files
    ]
    assert payload["key_material_sha256"] == sha(canonical(material))
    assert material["backend_config"]["kernel_accepted"] is False
    assert material["backend_config"]["deterministic_trusted"] is False
    pins = material["translator"]["producer_pins"]
    assert pins[str(Path(owner.__file__).resolve())] == sha(Path(owner.__file__).read_bytes())
    assert pins[str(Path(packet_owner.__file__).resolve())] == sha(Path(packet_owner.__file__).read_bytes())


@pytest.mark.parametrize("overrides", (
    {"expected_packet_observation_sha256": "0" * 64},
    {"expected_receipt_file_sha256": "0" * 64},
    {"expected_bundle_sha256": "0" * 64},
    {"created_at": True},
    {"created_at": float("inf")},
    {"unexpected_contract_field": "ignored?"},
))
def test_malformed_or_unpinned_input_refuses_before_store(base, inputs, overrides, no_execution):
    store = CountingStore()
    with pytest.raises((ValueError, TypeError)):
        write(store, base, inputs["fol"], **overrides)
    assert store.calls == []
    assert store.stats()["writes"] == 0


def test_mutable_packet_bytes_refuse_before_store(base, inputs, no_execution):
    pairs = list(base.files)
    pairs[0] = (pairs[0][0], bytearray(pairs[0][1]))
    mutable = replace(base, files=tuple(pairs))
    store = CountingStore()
    with pytest.raises((ValueError, TypeError)):
        write(store, mutable, inputs["fol"])
    assert store.calls == []


def test_current_review_drift_refuses_before_index_hit(base, inputs, projections, no_execution):
    store = CountingStore()
    store.put(projections["fol"].entry)
    store.calls.clear()
    reviews = deepcopy(inputs["fol"]["review_inputs"])
    reviews["unexpected_review_field"] = "a cache hit must not bypass current review replay"
    with pytest.raises(ValueError):
        lookup(store, base, inputs["fol"], projections["fol"], review_inputs=reviews)
    assert store.calls == []


@pytest.mark.parametrize("field", ("expected_key_digest", "expected_entry_digest"))
def test_independently_pinned_full_identity_refuses_before_store(field, base, inputs, projections, no_execution):
    store = CountingStore()
    with pytest.raises(ValueError):
        lookup(store, base, inputs["fol"], projections["fol"], **{field: "sha256:" + "0" * 64})
    assert store.calls == []


def test_missing_observation_is_visible_miss(base, inputs, projections, no_execution):
    store = CountingStore()
    assert lookup(store, base, inputs["fol"], projections["fol"]) is None
    assert store.stats()["writes"] == 0


@pytest.mark.parametrize("stage", ("put", "lookup", "get"))
def test_store_failures_are_visible(stage, base, inputs, projections, no_execution):
    class BrokenStore(CountingStore):
        pass
    def fail(*args, **kwargs):
        raise OSError("visible unit store " + stage + " failure")
    store = BrokenStore()
    setattr(store, stage, fail)
    with pytest.raises(Exception, match="visible unit store " + stage + " failure"):
        if stage == "lookup":
            lookup(store, base, inputs["fol"], projections["fol"])
        else:
            write(store, base, inputs["fol"])


@pytest.mark.parametrize("fault", ("unusable", "wrong_full_key", "wrong_projected_entry"))
def test_put_acknowledgement_cannot_claim_unverified_storage(fault, base, inputs, no_execution):
    class LyingStore(CountingStore):
        def put(self, entry, **kwargs):
            ack = super().put(entry, **kwargs)
            if fault == "unusable":
                return replace(ack, usable=False)
            if fault == "wrong_full_key":
                return replace(ack, key_digest=entry.key.to_verification_cache_key().digest)
            changed = replace(ack.entry, result_payload={"invented": True}, entry_digest="")
            return replace(ack, entry=changed)
    with pytest.raises(ValueError):
        write(LyingStore(), base, inputs["fol"])


def test_successful_put_ack_requires_exact_full_readback(base, inputs, no_execution):
    class DroppingStore(CountingStore):
        def get(self, key, **kwargs):
            return None
    with pytest.raises(ValueError):
        write(DroppingStore(), base, inputs["fol"])


@pytest.mark.parametrize("operation", ("write", "lookup"))
def test_time_rewind_refuses_before_store(operation, base, inputs, projections, no_execution):
    store = CountingStore()
    with pytest.raises(ValueError, match="precedes entry creation"):
        if operation == "write":
            write(store, base, inputs["fol"], now=inputs["fol"]["created_at"] - 1)
        else:
            lookup(store, base, inputs["fol"], projections["fol"], now=inputs["fol"]["created_at"] - 1)
    assert store.calls == []


def test_expired_negative_observation_cannot_return_usable_hit(base, inputs, projections, no_execution):
    store = DuckDBProofStore(positive_ttl_seconds=10, negative_ttl_seconds=2)
    write(store, base, inputs["fol"])
    with pytest.raises(ValueError):
        lookup(store, base, inputs["fol"], projections["fol"], now=inputs["fol"]["created_at"] + 3)
    assert store.stats()["expirations"] == 1
    # The existing store evicts expired rows; a subsequent genuine miss is
    # distinguishable from the rejected stale acknowledgement.
    assert lookup(store, base, inputs["fol"], projections["fol"], now=inputs["fol"]["created_at"] + 3) is None


def test_exact_readback_refuses_integrity_valid_payload_substitution(base, inputs, projections, no_execution):
    class SubstitutingStore(CountingStore):
        def get(self, key, **kwargs):
            entry = super().get(key, **kwargs)
            return replace(entry, result_payload={"invented": True}, entry_digest="") if entry is not None else None
    store = SubstitutingStore()
    store.put(projections["fol"].entry)
    with pytest.raises(ValueError):
        lookup(store, base, inputs["fol"], projections["fol"])


def test_review_change_during_store_io_prevents_success_receipt(base, inputs, no_execution):
    reviews = deepcopy(inputs["fol"]["review_inputs"])
    class MutatingStore(CountingStore):
        def put(self, entry, **kwargs):
            ack = super().put(entry, **kwargs)
            reviews["injected_after_write"] = "must replay again before declaring success"
            return ack
    store = MutatingStore()
    with pytest.raises(ValueError):
        write(store, base, inputs["fol"], review_inputs=reviews)
    # Storage may have happened; the failure remains explicit and yields no
    # operation receipt that claims a fully validated round trip.
    assert store.stats()["writes"] == 1


def test_review_change_after_genuine_reader_return_refuses_pure_projection(base, inputs, monkeypatch, no_execution):
    reviews = deepcopy(inputs["fol"]["review_inputs"])
    genuine = packet_owner.validate_definition_use_preservation_packet_v2
    completed = []

    def mutate_after_genuine_replay(*args, **kwargs):
        retained = genuine(*args, **kwargs)
        completed.append(retained)
        reviews["injected_after_packet_replay"] = "not among the inputs validated by the genuine reader"
        return retained

    monkeypatch.setattr(packet_owner, "validate_definition_use_preservation_packet_v2", mutate_after_genuine_replay)
    with pytest.raises(ValueError, match="arguments changed across packet replay"):
        prepare(base, inputs["fol"], review_inputs=reviews)
    assert len(completed) == 1
    assert completed[0].to_dict()["current_preparation_replayed"] is True


def test_to_dict_returns_fresh_mapping_without_mutating_frozen_projection(projections):
    projection = projections["fol"]
    raw = projection.projection_json
    returned = projection.to_dict()
    returned["training_mask"] = 1
    assert projection.projection_json == raw
    assert projection.to_dict()["training_mask"] == 0
    with pytest.raises((AttributeError, TypeError)):
        projection.projection_json = "{}"



# Parent-norm packet indexing is a distinct receipt-consistency profile. The
# compiler/artifact/lifecycle claims come from the existing authored packet
# fixture. Genuine current preparation and physical-source replay are retained;
# these cases neither compile Lean nor establish legal or outer-operation truth.


@pytest.fixture(scope="module")
def parent_index_base(tmp_path_factory):
    return _FIXTURE.parent_norm_packet_base.__wrapped__(tmp_path_factory)


@pytest.fixture(scope="module")
def parent_index_observation(parent_index_base):
    return _FIXTURE._parent_norm_packet_read(parent_index_base)


@pytest.fixture(scope="module")
def parent_index_inputs(parent_index_base, parent_index_observation):
    return _FIXTURE._parent_norm_packet_arguments(parent_index_base) | {
        "expected_packet_observation_sha256": sha(
            parent_index_observation.observation_json.encode()),
        "created_at": 1_792_100_100.0,
    }


@pytest.fixture(scope="module")
def parent_index_projection(parent_index_base, parent_index_inputs):
    return _parent_index_prepare(parent_index_base, parent_index_inputs)


@pytest.fixture
def parent_index_no_execution(no_execution, monkeypatch):
    _FIXTURE.parent_norm_packet_no_execution.__wrapped__(no_execution, monkeypatch)


def _parent_index_prepare(base, arguments, *, files=None, preparation=None,
                          correspondence=None, **overrides):
    return owner.prepare_parent_norm_preservation_index_v1(
        base.files if files is None else files,
        base.preparation if preparation is None else preparation,
        base.data["correspondence"] if correspondence is None else correspondence,
        **(arguments | overrides),
    )


def _parent_index_write(store, base, arguments, *, files=None, preparation=None,
                        correspondence=None, **overrides):
    return owner.write_parent_norm_preservation_index_v1(
        store, base.files if files is None else files,
        base.preparation if preparation is None else preparation,
        base.data["correspondence"] if correspondence is None else correspondence,
        **(arguments | {"now": arguments["created_at"] + 1} | overrides),
    )


def _parent_index_lookup(store, base, arguments, projection, **overrides):
    return owner.lookup_parent_norm_preservation_index_v1(
        store, base.files, base.preparation, base.data["correspondence"],
        **(arguments | {
            "expected_key_digest": projection.entry.key.digest,
            "expected_entry_digest": projection.entry.entry_digest,
            "now": arguments["created_at"] + 1,
        } | overrides),
    )


def _parent_index_assert_unaccepted(value):
    assert value["receipt_consistency_only"] is True
    assert value["accepted_execution"] is value["accepted_outer_operation"] is False
    assert value["accepted_operation_result_bound"] is False
    assert value["outer_operation_outcome"] == "unprovided"
    assert value["proof_usable"] is False
    assert value["authority"] and all(flag is False for flag in value["authority"].values())
    assert type(value["training_mask"]) is type(value["evaluation_gold_mask"]) is int
    assert value["training_mask"] == value["evaluation_gold_mask"] == 0
    assert all(value[name] is False for name in packet_owner.FALSE_FLAGS)


def test_parent_norm_index_public_profile_is_explicit_and_separate():
    assert owner.PARENT_NORM_INDEX_SCHEMA == "legal-corpus-parent-norm-preservation-index-projection/v1"
    assert owner.PARENT_NORM_INDEX_OPERATION_SCHEMA == "legal-corpus-parent-norm-preservation-index-operation/v1"
    assert owner.PARENT_NORM_INDEX_PROFILE == "retained-parent-norm-receipt-consistency-index/v1"
    assert owner.PARENT_NORM_INDEX_SCHEMA != owner.SCHEMA
    assert owner.PARENT_NORM_INDEX_OPERATION_SCHEMA != owner.OPERATION_SCHEMA
    assert owner.PARENT_NORM_INDEX_PROFILE != owner.PROFILE
    for name in (
        "prepare_parent_norm_preservation_index_v1",
        "write_parent_norm_preservation_index_v1",
        "lookup_parent_norm_preservation_index_v1",
    ):
        assert callable(getattr(owner, name)) and name in owner.__all__


def test_parent_norm_index_genuine_projection_keeps_unaccepted_outer_result(
        parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution):
    projection = parent_index_projection
    entry = projection.entry
    assert type(projection) is owner.RetainedCorpusIndexProjection
    assert isinstance(entry, UnifiedProofEntry) and entry.verify_integrity() is entry
    assert entry.outcome is ProofOutcomeKind.UNKNOWN
    assert entry.status is ResultStatus.UNKNOWN
    assert entry.result_authority is ResultAuthority.CANDIDATE
    assert entry.evidence_authority is EvidenceAuthority.NONE
    assert entry.trust_level is ProofTrustLevel.NONE
    assert entry.polarity is CachePolarity.NEGATIVE
    assert len(entry.key.dimension_map()) == len(KEY_FIELDS) == 15
    assert entry.created_at == parent_index_inputs["created_at"]
    assert entry.key.to_verification_cache_key().digest != entry.key.digest
    value = projection.to_dict()
    assert value["schema"] == owner.PARENT_NORM_INDEX_SCHEMA
    assert value["profile"] == owner.PARENT_NORM_INDEX_PROFILE
    _parent_index_assert_unaccepted(value)
    _parent_index_assert_unaccepted(entry.result_payload.to_dict())
    assert entry.envelope.content_digest == (
        "sha256:" + parent_index_inputs["expected_packet_observation_sha256"])
    assert entry.envelope.media_type == "application/json"
    assert len(entry.evidence) == 1
    assert entry.evidence[0].content_digest == (
        "sha256:" + parent_index_inputs["expected_receipt_file_sha256"])
    assert entry.evidence[0].evidence_authority is EvidenceAuthority.NONE
    assert entry.evidence[0].evidence_kind == "unreviewed_runtime_observation"
    # The persisted fixture claims success, but its outer accepted outcome is
    # absent. Indexing may preserve that claim without promoting its authority.
    receipt = json.loads(dict(parent_index_base.files)["build-receipt.json"])
    assert receipt["build_passed"] is True
    assert value["accepted_execution"] is False


def test_parent_norm_index_genuine_memory_store_roundtrip_keeps_observation_only(
        parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution):
    store = CountingStore()
    written = _parent_index_write(store, parent_index_base, parent_index_inputs)
    assert written.projection == parent_index_projection
    written_value = written.to_dict()
    assert written_value["schema"] == owner.PARENT_NORM_INDEX_OPERATION_SCHEMA
    assert written_value["profile"] == owner.PARENT_NORM_INDEX_PROFILE
    assert written_value["index_write_acknowledged"] is True
    assert written_value["full_entry_readback_verified"] is True
    assert written_value["durable_storage_verified"] is False
    _parent_index_assert_unaccepted(written_value)
    observed = _parent_index_lookup(
        store, parent_index_base, parent_index_inputs, parent_index_projection)
    assert observed is not None and observed.projection == parent_index_projection
    assert observed.to_dict()["index_lookup_acknowledged"] is True
    _parent_index_assert_unaccepted(observed.to_dict())
    assert store.stats()["writes"] == 1
    assert "put" in store.calls and "get" in store.calls and "lookup" in store.calls


@pytest.mark.parametrize("dimension", KEY_FIELDS, ids=KEY_FIELDS)
def test_parent_norm_index_each_supported_key_dimension_forces_memory_miss(
        dimension, parent_index_projection):
    entry = parent_index_projection.entry
    changed = ("sha256:" + "9" * 64,) if dimension == "selected_premise_digests" else (
        "different-parent-norm-index-profile" if dimension in {"backend_id", "backend_version"}
        else "sha256:" + "9" * 64)
    mutant = replace(entry.key, **{dimension: changed})
    assert mutant.digest != entry.key.digest
    store = CountingStore()
    store.put(entry)
    assert store.get(mutant) is None
    assert store.get(entry.key) == entry


def test_parent_norm_index_unknown_unified_key_schema_refuses(parent_index_projection):
    with pytest.raises(ValueError, match="unsupported unified proof key schema"):
        replace(parent_index_projection.entry.key, schema_version="different-key-schema")


def test_parent_norm_index_determinism_and_explicit_timestamp_are_distinct(
        parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution):
    again = _parent_index_prepare(parent_index_base, parent_index_inputs)
    assert again == parent_index_projection
    later = _parent_index_prepare(
        parent_index_base, parent_index_inputs,
        created_at=parent_index_inputs["created_at"] + 1)
    assert later.entry.key.digest == again.entry.key.digest
    assert later.entry.entry_digest != again.entry.entry_digest


def test_parent_norm_index_profiles_cannot_substitute_each_others_inputs(
        parent_index_base, parent_index_inputs, parent_index_projection,
        base, inputs, projections, parent_index_no_execution):
    assert parent_index_projection.entry.key.digest != projections["fol"].entry.key.digest
    with pytest.raises((ValueError, TypeError)):
        owner.prepare_definition_use_preservation_index_v2(
            parent_index_base.files, parent_index_base.preparation,
            parent_index_base.data["correspondence"], **inputs["fol"])
    with pytest.raises((ValueError, TypeError)):
        owner.prepare_parent_norm_preservation_index_v1(
            base.files, parent_index_base.preparation,
            parent_index_base.data["correspondence"], **parent_index_inputs)
    store = CountingStore()
    store.put(projections["fol"].entry)
    assert store.get(parent_index_projection.entry.key) is None


def test_parent_norm_index_key_retains_complete_original_parent_premises(
        parent_index_base, parent_index_inputs, parent_index_observation,
        parent_index_projection):
    payload = parent_index_projection.entry.result_payload.to_dict()
    material = payload["key_material"]
    manifest = parent_index_base.preparation.to_dict()
    observation = parent_index_observation.to_dict()
    assert material["ir"]["full_parent_preparation_sha256"] == parent_index_inputs["expected_preparation_sha256"]
    assert material["ir"]["full_parent_correspondence_sha256"] == parent_index_inputs["expected_correspondence_sha256"]
    assert material["ir"]["original_norm"] == manifest["original_norm"]
    assert material["assumptions"]["theorem_assumptions"] == manifest["theorem_assumptions"]
    assert material["assumptions"]["original_parent_context"] == manifest["original_parent_context"]
    assert material["assumptions"]["review_blockers"] == manifest["review_blockers"]
    assert material["selected_premises"] == [
        manifest["review_intake_binding"], manifest["original_parent_context"]]
    assert material["theorem_registry"] == {name: manifest[name] for name in (
        "conditional_theorems", "expected_modules", "module_imports", "native_fragments")}
    assert material["policy"]["review_intake_binding"] == manifest["review_intake_binding"]
    assert material["policy"]["review_blockers"] == manifest["review_blockers"]
    assert material["policy"]["source_custody"] == observation["source_custody"]
    assert material["resources"]["packet_inventory"] == [
        {"path": path, "bytes": len(raw), "sha256": sha(raw)}
        for path, raw in parent_index_base.files]
    assert material["backend_binary"] == parent_index_inputs["expected_binary_sha256"]
    assert material["backend_config"]["kernel_accepted"] is False
    assert material["backend_config"]["deterministic_trusted"] is False
    assert payload["key_material_sha256"] == sha(canonical(material))
    pins = material["translator"]["producer_pins"]
    assert pins[str(Path(owner.__file__).resolve())] == sha(Path(owner.__file__).read_bytes())
    assert pins[str(Path(packet_owner.__file__).resolve())] == sha(Path(packet_owner.__file__).read_bytes())
    assert material["translator"]["native_producer_pins"] == manifest["native_producer_pins"]


@pytest.mark.parametrize("damage", (
    "observation_pin", "preparation_pin", "correspondence_pin", "receipt_pin",
    "bundle_pin", "binary_pin", "boolean_created_at", "nonfinite_created_at",
    "unknown_argument", "missing_argument", "mutable_packet", "nonordinary_inputs",
), ids=(
    "observation-pin", "preparation-pin", "correspondence-pin", "receipt-pin",
    "bundle-pin", "binary-pin", "boolean-created-at", "nonfinite-created-at",
    "unknown-argument", "missing-argument", "mutable-packet", "nonordinary-inputs",
))
def test_parent_norm_index_closed_originals_refuse_before_store(
        damage, parent_index_base, parent_index_inputs, parent_index_no_execution):
    arguments = deepcopy(parent_index_inputs)
    files = parent_index_base.files
    names = {
        "observation_pin": "expected_packet_observation_sha256",
        "preparation_pin": "expected_preparation_sha256",
        "correspondence_pin": "expected_correspondence_sha256",
        "receipt_pin": "expected_receipt_file_sha256",
        "bundle_pin": "expected_bundle_sha256",
    }
    if damage in names:
        arguments[names[damage]] = "0" * 64
    elif damage == "binary_pin":
        key = next(iter(arguments["expected_binary_sha256"]))
        arguments["expected_binary_sha256"][key] = "0" * 64
    elif damage == "boolean_created_at":
        arguments["created_at"] = True
    elif damage == "nonfinite_created_at":
        arguments["created_at"] = float("inf")
    elif damage == "unknown_argument":
        arguments["unreviewed_extra_input"] = "must not be ignored"
    elif damage == "missing_argument":
        arguments.pop("correspondence_inputs")
    elif damage == "mutable_packet":
        pairs = list(files)
        pairs[0] = (pairs[0][0], bytearray(pairs[0][1]))
        files = tuple(pairs)
    else:
        class DictSubclass(dict):
            pass
        arguments["correspondence_inputs"] = DictSubclass(arguments["correspondence_inputs"])
    store = CountingStore()
    with pytest.raises((ValueError, TypeError)):
        _parent_index_write(store, parent_index_base, arguments, files=files)
    assert store.calls == [] and store.stats()["writes"] == 0


def test_parent_norm_index_preconstructed_projection_cannot_replace_preparation(
        parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution):
    store = CountingStore()
    with pytest.raises((ValueError, TypeError)):
        _parent_index_write(
            store, parent_index_base, parent_index_inputs,
            preparation=parent_index_projection)
    assert store.calls == []


@pytest.mark.parametrize("field", ("expected_key_digest", "expected_entry_digest"),
                         ids=("full-key", "entry"))
def test_parent_norm_index_independent_identity_refuses_before_storage(
        field, parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution):
    store = CountingStore()
    with pytest.raises(ValueError):
        _parent_index_lookup(
            store, parent_index_base, parent_index_inputs, parent_index_projection,
            **{field: "sha256:" + "0" * 64})
    assert store.calls == []


def test_parent_norm_index_genuine_absence_is_visible_miss(
        parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution):
    store = CountingStore()
    assert _parent_index_lookup(
        store, parent_index_base, parent_index_inputs, parent_index_projection) is None
    assert store.stats()["writes"] == 0


@pytest.mark.parametrize("fault", ("usable", "wrong-key", "wrong-reason"))
def test_parent_norm_index_inconsistent_miss_is_not_a_genuine_absence(
        fault, parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution):
    class InvalidMiss(CountingStore):
        def lookup(self, key, **kwargs):
            ack = super().lookup(key, **kwargs)
            if fault == "usable":
                return replace(ack, usable=True)
            if fault == "wrong-key":
                return replace(ack, key_digest="sha256:" + "9" * 64)
            return replace(ack, reason=type(ack.reason).EXPIRED)
    with pytest.raises(ValueError):
        _parent_index_lookup(
            InvalidMiss(), parent_index_base, parent_index_inputs, parent_index_projection)


@pytest.mark.parametrize("stage", ("put", "lookup", "get"))
def test_parent_norm_index_backend_failures_remain_visible(
        stage, parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution):
    store = CountingStore()
    def failed(*args, **kwargs):
        raise OSError("explicit parent index " + stage + " failure")
    setattr(store, stage, failed)
    with pytest.raises(Exception, match="explicit parent index " + stage + " failure"):
        if stage == "lookup":
            _parent_index_lookup(
                store, parent_index_base, parent_index_inputs, parent_index_projection)
        else:
            _parent_index_write(store, parent_index_base, parent_index_inputs)


@pytest.mark.parametrize("fault", ("unusable", "wrong-key", "wrong-entry", "wrong-hit"))
def test_parent_norm_index_put_acknowledgment_does_not_establish_readback(
        fault, parent_index_base, parent_index_inputs, parent_index_no_execution):
    class InvalidAcknowledgment(CountingStore):
        def put(self, entry, **kwargs):
            ack = super().put(entry, **kwargs)
            if fault == "unusable":
                return replace(ack, usable=False)
            if fault == "wrong-key":
                return replace(ack, key_digest=entry.key.to_verification_cache_key().digest)
            if fault == "wrong-hit":
                return replace(ack, hit=True)
            changed = replace(ack.entry, result_payload={"invented": True}, entry_digest="")
            return replace(ack, entry=changed)
    with pytest.raises(ValueError):
        _parent_index_write(InvalidAcknowledgment(), parent_index_base, parent_index_inputs)


@pytest.mark.parametrize("fault", ("absent", "substituted"))
def test_parent_norm_index_full_entry_readback_is_exact(
        fault, parent_index_base, parent_index_inputs, parent_index_no_execution):
    class InvalidReadback(CountingStore):
        def get(self, key, **kwargs):
            if fault == "absent":
                return None
            entry = super().get(key, **kwargs)
            return replace(entry, result_payload={"invented": True}, entry_digest="")
    with pytest.raises(ValueError):
        _parent_index_write(InvalidReadback(), parent_index_base, parent_index_inputs)


@pytest.mark.parametrize("stage", ("put", "get"))
def test_parent_norm_index_integrity_valid_entry_mutation_during_io_refuses(
        stage, parent_index_base, parent_index_inputs, parent_index_no_execution):
    changed = []
    def alter(entry):
        replacement = replace(
            entry, diagnostics=("substituted valid entry after projection",), entry_digest="")
        object.__setattr__(entry, "diagnostics", replacement.diagnostics)
        object.__setattr__(entry, "entry_digest", replacement.entry_digest)
        assert entry.verify_integrity() is entry
        changed.append(True)
    class ChangingActualEntry(CountingStore):
        def put(self, entry, **kwargs):
            if stage == "put":
                alter(entry)
            return super().put(entry, **kwargs)
        def get(self, key, **kwargs):
            entry = super().get(key, **kwargs)
            if stage == "get":
                alter(entry)
            return entry
    with pytest.raises(ValueError):
        _parent_index_write(ChangingActualEntry(), parent_index_base, parent_index_inputs)
    assert changed


@pytest.mark.parametrize("operation", ("write", "lookup"))
def test_parent_norm_index_time_rewind_refuses_before_io(
        operation, parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution):
    store = CountingStore()
    earlier = parent_index_inputs["created_at"] - 1
    with pytest.raises(ValueError, match="precedes entry creation"):
        if operation == "write":
            _parent_index_write(store, parent_index_base, parent_index_inputs, now=earlier)
        else:
            _parent_index_lookup(
                store, parent_index_base, parent_index_inputs, parent_index_projection, now=earlier)
    assert store.calls == []


def test_parent_norm_index_expired_negative_hit_is_not_usable(
        parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution):
    store = DuckDBProofStore(positive_ttl_seconds=10, negative_ttl_seconds=2)
    _parent_index_write(store, parent_index_base, parent_index_inputs)
    later = parent_index_inputs["created_at"] + 3
    with pytest.raises(ValueError):
        _parent_index_lookup(
            store, parent_index_base, parent_index_inputs, parent_index_projection, now=later)
    assert store.stats()["expirations"] == 1
    assert _parent_index_lookup(
        store, parent_index_base, parent_index_inputs, parent_index_projection, now=later) is None


@pytest.mark.parametrize("operation", ("write", "lookup"))
def test_parent_norm_index_input_drift_during_io_never_returns_success(
        operation, parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution):
    original_inputs = deepcopy(parent_index_inputs["correspondence_inputs"])
    class ChangingStore(CountingStore):
        def put(self, entry, **kwargs):
            ack = super().put(entry, **kwargs)
            original_inputs["expected_mapping_request_sha256"] = "0" * 64
            return ack
        def lookup(self, key, **kwargs):
            ack = super().lookup(key, **kwargs)
            original_inputs["expected_mapping_request_sha256"] = "0" * 64
            return ack
    store = ChangingStore()
    if operation == "lookup":
        # Populate without triggering the mutating put override.
        DuckDBProofStore.put(store, parent_index_projection.entry)
        store.calls.clear()
    with pytest.raises(ValueError):
        if operation == "write":
            _parent_index_write(
                store, parent_index_base, parent_index_inputs,
                correspondence_inputs=original_inputs)
        else:
            _parent_index_lookup(
                store, parent_index_base, parent_index_inputs, parent_index_projection,
                correspondence_inputs=original_inputs)
    assert store.stats()["writes"] == 1


def test_parent_norm_index_late_miss_mutation_cannot_invent_verified_hit(
        parent_index_base, parent_index_inputs, parent_index_projection,
        parent_index_no_execution, monkeypatch):
    acknowledged, completed = [], []
    class MutableAcknowledgment(CountingStore):
        def lookup(self, key, **kwargs):
            result = super().lookup(key, **kwargs)
            assert result.hit is False
            acknowledged.append(result)
            return result
    genuine = owner.prepare_parent_norm_preservation_index_v1
    def change_miss_after_closing_replay(*args, **kwargs):
        result = genuine(*args, **kwargs)
        completed.append(result)
        if acknowledged:
            object.__setattr__(acknowledged[0], "hit", True)
        return result
    monkeypatch.setattr(owner, "prepare_parent_norm_preservation_index_v1", change_miss_after_closing_replay)
    with pytest.raises(ValueError):
        _parent_index_lookup(
            MutableAcknowledgment(), parent_index_base, parent_index_inputs, parent_index_projection)
    assert len(acknowledged) == 1 and len(completed) == 2


def test_parent_norm_index_original_inputs_changed_after_genuine_reader_refuse(
        parent_index_base, parent_index_inputs, parent_index_no_execution, monkeypatch):
    original_inputs = deepcopy(parent_index_inputs["correspondence_inputs"])
    genuine = packet_owner.validate_parent_norm_native_packet_v1
    completed = []
    def mutate_after_return(*args, **kwargs):
        result = genuine(*args, **kwargs)
        completed.append(result)
        original_inputs["expected_mapping_request_sha256"] = "0" * 64
        return result
    monkeypatch.setattr(packet_owner, "validate_parent_norm_native_packet_v1", mutate_after_return)
    with pytest.raises(ValueError):
        _parent_index_prepare(
            parent_index_base, parent_index_inputs, correspondence_inputs=original_inputs)
    assert len(completed) == 1
    assert completed[0].to_dict()["current_preparation_replayed"] is True


def test_parent_norm_index_late_reader_replacement_is_never_invoked(
        parent_index_base, parent_index_inputs, parent_index_no_execution, monkeypatch):
    genuine = packet_owner.validate_parent_norm_native_packet_v1
    completed, unexpected = [], []
    def substituted(*args, **kwargs):
        unexpected.append(True)
        return completed[0]
    def mutate_after_return(*args, **kwargs):
        result = genuine(*args, **kwargs)
        completed.append(result)
        monkeypatch.setattr(packet_owner, "validate_parent_norm_native_packet_v1", substituted)
        return result
    monkeypatch.setattr(packet_owner, "validate_parent_norm_native_packet_v1", mutate_after_return)
    with pytest.raises(ValueError):
        _parent_index_prepare(parent_index_base, parent_index_inputs)
    assert len(completed) == 1 and unexpected == []


def test_parent_norm_index_local_source_drift_refuses_after_genuine_reader(
        parent_index_base, parent_index_inputs, parent_index_no_execution, monkeypatch, tmp_path):
    source = tmp_path / "copied_parent_index_owner.py"
    source.write_bytes(Path(owner.__file__).read_bytes())
    monkeypatch.setattr(owner, "__file__", str(source))
    genuine = packet_owner.validate_parent_norm_native_packet_v1
    completed = []
    def mutate_after_return(*args, **kwargs):
        result = genuine(*args, **kwargs)
        completed.append(result)
        source.write_bytes(source.read_bytes() + b"\n# authored late source drift\n")
        return result
    monkeypatch.setattr(packet_owner, "validate_parent_norm_native_packet_v1", mutate_after_return)
    with pytest.raises(ValueError):
        _parent_index_prepare(parent_index_base, parent_index_inputs)
    assert len(completed) == 1


def test_parent_norm_index_physical_parent_changed_during_store_io_refuses(
        parent_index_base, parent_index_inputs, parent_index_no_execution):
    path = _FIXTURE._FIXTURE._FIXTURE._parent_norm_parent_path(parent_index_base.data)
    before = path.read_bytes()
    class ChangingPhysicalParent(CountingStore):
        def put(self, entry, **kwargs):
            ack = super().put(entry, **kwargs)
            path.write_bytes(before + b"\nexplicit late parent physical witness drift\n")
            return ack
    store = ChangingPhysicalParent()
    try:
        with pytest.raises(ValueError):
            _parent_index_write(store, parent_index_base, parent_index_inputs)
        assert store.stats()["writes"] == 1
    finally:
        path.write_bytes(before)
        assert path.read_bytes() == before


@pytest.mark.parametrize("repin", (False, True), ids=("original-pin", "forged-pin"))
def test_parent_norm_index_forged_typed_observation_cannot_promote_execution(
        repin, parent_index_base, parent_index_inputs, parent_index_no_execution, monkeypatch):
    original = _FIXTURE._parent_norm_packet_read(parent_index_base)
    altered = original.to_dict()
    altered["accepted_execution"] = True
    forged = type(original)(canonical(_FIXTURE.seal(altered)).decode(), original.files)
    genuine = packet_owner.validate_parent_norm_native_packet_v1
    calls = []
    def replaced_after_genuine_replay(*args, **kwargs):
        result = genuine(*args, **kwargs)
        calls.append(result)
        return forged
    monkeypatch.setattr(
        packet_owner, "validate_parent_norm_native_packet_v1", replaced_after_genuine_replay)
    override = {"expected_packet_observation_sha256": sha(forged.observation_json.encode())} if repin else {}
    with pytest.raises(ValueError):
        _parent_index_prepare(parent_index_base, parent_index_inputs, **override)
    assert len(calls) == 1


@pytest.mark.parametrize("delegate", ("seal", "serialization", "constructor"))
def test_parent_norm_index_final_delegate_cannot_launder_outer_acceptance(
        delegate, parent_index_base, parent_index_inputs, parent_index_no_execution, monkeypatch):
    changed = []
    if delegate == "seal":
        genuine = _FIXTURE.contracts.seal_record
        def substituted(value, *args, **kwargs):
            result = genuine(value, *args, **kwargs)
            if type(value) is dict and value.get("schema") == owner.PARENT_NORM_INDEX_SCHEMA:
                altered = {key: item for key, item in deepcopy(result).items()
                           if key not in {"record_cid", "cid_scope"}}
                altered["accepted_execution"] = True
                changed.append(True)
                return genuine(altered)
            return result
        monkeypatch.setattr(_FIXTURE.contracts, "seal_record", substituted)
    elif delegate == "serialization":
        genuine = owner._wire
        def substituted(value):
            raw = genuine(value)
            if type(value) is dict and value.get("schema") == owner.PARENT_NORM_INDEX_SCHEMA:
                value["accepted_execution"] = True
                changed.append(True)
            return raw
        monkeypatch.setattr(owner, "_wire", substituted)
    else:
        genuine = owner.RetainedCorpusIndexProjection.__init__
        def substituted(result, *args, **kwargs):
            genuine(result, *args, **kwargs)
            altered = result.to_dict()
            if altered.get("schema") == owner.PARENT_NORM_INDEX_SCHEMA:
                altered["accepted_execution"] = True
                object.__setattr__(result, "projection_json", canonical(_FIXTURE.seal(altered)).decode())
                changed.append(True)
        monkeypatch.setattr(owner.RetainedCorpusIndexProjection, "__init__", substituted)
    with pytest.raises(ValueError):
        _parent_index_prepare(parent_index_base, parent_index_inputs)
    assert changed


def test_parent_norm_index_mutating_returned_dict_does_not_change_projection(
        parent_index_projection):
    original = parent_index_projection.projection_json
    value = parent_index_projection.to_dict()
    value["accepted_execution"] = True
    value["training_mask"] = 1
    assert parent_index_projection.projection_json == original
    _parent_index_assert_unaccepted(parent_index_projection.to_dict())
    with pytest.raises((AttributeError, TypeError)):
        parent_index_projection.projection_json = "{}"

