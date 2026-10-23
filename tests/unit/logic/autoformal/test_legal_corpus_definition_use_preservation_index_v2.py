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

