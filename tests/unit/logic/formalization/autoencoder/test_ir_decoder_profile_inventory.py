"""Detached decoder profile metadata using private, nonnumerical fixtures.

The tiny packages omit model tensors and do not claim trained candidates. Real
route, source, codec, corpus and endpoint checks run; Hub owners/defaults are
forbidden. Stable profiles describe compatibility, not runtime or quality.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub as hub
from ipfs_datasets_py.logic.formalization.autoencoder import ir_decoder_profile_inventory as inventory
from tests.unit.logic.formalization.autoencoder import test_ir_decoder_format_runtime as format_shared
from tests.unit.logic.formalization.autoencoder import test_ir_original_corpus_runtime as original_shared
from tests.unit.logic.formalization.autoencoder import test_ir_cell_routing as shared


FAMILIES = ("intent_ir", "security_ir")
EXPERIMENT_KEYS = ("seed", "epochs", "batch_size", "learning_rate", "patience",
                   "reconstruction_weight", "max_seconds")


def source4096_producer():
    # Authored metadata only: these hashes are not a native execution witness.
    return {"profile": "leanstral4096:cpu1:last:l2:single-sequence:tokens512:lazy-mmap:v2",
        "model_sha256": "4668fd2a6d2764de250489852230e96238eb5c0d7495866eb3b9c6c4fac5c7da",
        "worker_sha256": "a" * 64, "worker_source_sha256": "b" * 64,
        "owner_source_sha256": "c" * 64, "vocabulary_owner_source_sha256": "d" * 64,
        "library_sha256": ["f" * 64, "e" * 64, "f" * 64]}


def test_source4096_profile_is_separate_content_bound_detached_declared_metadata():
    producer = source4096_producer()
    profile = inventory.build_ir_source_representation_profile(producer)
    assert profile["schema"] == "ir-source-representation-profile/v1"
    identity = profile["identity"]
    assert profile["profile_id"] == profile["schema"] + ":" + hashlib.sha256(
        inventory.cached._raw(identity)).hexdigest()
    assert identity["ir_family_id"] == "legal_ir"
    assert identity["dimension"] == 4096 and identity["dimension_role"] == "input_embedding"
    assert identity["producer"]["library_sha256"] == ["e" * 64, "f" * 64, "f" * 64]
    assert identity["source_text_policy"] == "exact_utf8_no_normalization"
    assert identity["maximum_source_tokens_including_special"] == 512
    assert identity["maximum_source_utf8_bytes"] == 65536 and identity["source_nul_policy"] == "reject"
    assert profile["scope"] == "declared_expected_source_producer_only"
    assert all(value is False for value in profile["authority"].values())
    assert inventory.validate_ir_source_representation_profile(profile) == profile
    producer["library_sha256"].append("1" * 64)
    assert len(profile["identity"]["producer"]["library_sha256"]) == 3
    restored = inventory.validate_ir_source_representation_profile(profile)
    restored["identity"]["producer"]["library_sha256"].clear()
    assert len(profile["identity"]["producer"]["library_sha256"]) == 3


def test_source4096_profile_retains_library_multiplicity_and_distinct_producer_generations():
    producer = source4096_producer()
    before = inventory.build_ir_source_representation_profile(producer)
    producer["library_sha256"].reverse()
    assert inventory.build_ir_source_representation_profile(producer) == before
    for key, replacement in (
        ("library_sha256", ["e" * 64, "f" * 64]),
        ("worker_sha256", "2" * 64),
        ("profile", "leanstral4096:cpu1:last:l2:single-sequence:tokens512:layer-reclaim:v3"),
    ):
        changed = dict(producer, **{key: replacement})
        assert inventory.build_ir_source_representation_profile(changed)["profile_id"] != before["profile_id"]


@pytest.mark.parametrize("location", ["producer", "profile", "identity", "authority"])
def test_source4096_profile_refuses_nonbuiltin_keys_before_hash_or_equality_callbacks(location):
    callbacks = []
    class ForeignKey(str):
        armed = False
        def __hash__(self):
            if self.armed:
                callbacks.append("hash")
                raise AssertionError("foreign key hash executed")
            return super().__hash__()
        def __eq__(self, other):
            if self.armed:
                callbacks.append("equality")
                raise AssertionError("foreign key equality executed")
            return super().__eq__(other)
    profile = inventory.build_ir_source_representation_profile(source4096_producer())
    target = profile if location == "profile" else profile["identity"] if location == "identity" else \
        profile["authority"] if location == "authority" else profile["identity"]["producer"]
    key = ForeignKey("foreign")
    target[key] = "unused"
    key.armed = True
    with pytest.raises(inventory.DecoderProfileInventoryError):
        inventory.validate_ir_source_representation_profile(profile)
    assert callbacks == []


@pytest.mark.parametrize("mutation", ["unknown_profile", "model", "bad_hash", "library_map",
    "empty_libraries", "too_many_libraries", "missing_worker", "extra_claim"])
def test_source4096_profile_requires_complete_expected_producer_without_geometry_shortcuts(mutation):
    producer = source4096_producer()
    if mutation == "unknown_profile": producer["profile"] = "arbitrary-vector4096"
    elif mutation == "model": producer["model_sha256"] = "1" * 64
    elif mutation == "bad_hash": producer["worker_sha256"] = True
    elif mutation == "library_map": producer["library_sha256"] = {"/tmp/lib.so": "e" * 64}
    elif mutation == "empty_libraries": producer["library_sha256"] = []
    elif mutation == "too_many_libraries": producer["library_sha256"] = ["e" * 64] * 64
    elif mutation == "missing_worker": producer.pop("worker_sha256")
    elif mutation == "extra_claim": producer["native_execution_authenticated"] = True
    with pytest.raises(inventory.DecoderProfileInventoryError):
        inventory.build_ir_source_representation_profile(producer)


@pytest.mark.parametrize("mutation", ["family", "dimension", "float_dimension", "boolean_tokens",
    "role", "pooling", "normalization", "tokenizer", "text_policy", "id", "authority",
    "integer_authority", "extra_identity", "extra_top", "source_byte_limit", "nul_policy"])
def test_source4096_profile_refuses_resealed_geometry_policy_or_authority_changes(mutation):
    profile = inventory.build_ir_source_representation_profile(source4096_producer())
    identity = profile["identity"]
    if mutation == "family": identity["ir_family_id"] = "intent_ir"
    elif mutation == "dimension": identity["dimension"] = 768
    elif mutation == "float_dimension": identity["dimension"] = 4096.0
    elif mutation == "boolean_tokens": identity["maximum_source_tokens_including_special"] = True
    elif mutation == "role": identity["dimension_role"] = "latent"
    elif mutation == "pooling": identity["pooling"] = "mean"
    elif mutation == "normalization": identity["normalization"] = "none"
    elif mutation == "tokenizer": identity["tokenizer_policy"] = "caller_tokens"
    elif mutation == "text_policy": identity["source_text_policy"] = "strip"
    elif mutation == "id": profile["profile_id"] = profile["schema"] + ":" + "0" * 64
    elif mutation == "authority": profile["authority"]["source_producer_execution_authenticated"] = True
    elif mutation == "integer_authority": profile["authority"]["runtime_ready"] = 0
    elif mutation == "extra_identity": identity["runtime_ready"] = False
    elif mutation == "extra_top": profile["execution_witness"] = "caller"
    elif mutation == "source_byte_limit": identity["maximum_source_utf8_bytes"] = 65537
    elif mutation == "nul_policy": identity["source_nul_policy"] = "allow"
    if mutation != "id":
        profile["profile_id"] = profile["schema"] + ":" + hashlib.sha256(inventory.cached._raw(identity)).hexdigest()
    with pytest.raises(inventory.DecoderProfileInventoryError):
        inventory.validate_ir_source_representation_profile(profile)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def make_profile_data(tmp_path, family="intent_ir"):
    data = format_shared.make_format_data(tmp_path, family)
    data["checkpoint"]["config"].update(hidden_size=16, token_embedding_dim=8, projection_width=8,
        seed=1, epochs=2, batch_size=2, learning_rate=0.001, patience=1,
        reconstruction_weight=0.1, max_seconds=10,
        embedding_provenance={"model_id": "caller_supplied", "verified_by_runtime": False,
                              "scope": "synthetic metadata; no producer execution"})
    original_shared.repin(data)
    return data


@pytest.fixture
def data(tmp_path):
    return make_profile_data(tmp_path)


@pytest.fixture(autouse=True)
def forbidden_owners(monkeypatch):
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Metadata inventory called a Hub default or numerical owner")
    for name in ("_instantiate", "default_descriptor", "open_autoencoder", "open_local_autoencoder",
                 "open_ir_cell_autoencoder", "open_ir_original_corpus_autoencoder",
                 "open_ir_decoder_format_autoencoder"):
        monkeypatch.setattr(hub, name, forbidden)
    yield calls
    assert calls == []


def binding(data, run_id="run-a"):
    return {"request": deepcopy(data["request"]), "format_request": deepcopy(format_shared.SPECS[data["family"]]),
            "package_manifest_pin": deepcopy(data["manifest_pin"]), "corpus_pin": deepcopy(data["corpus_pin"]),
            "run_id": run_id}


def build(data, bindings=None, **options):
    return inventory.build_ir_decoder_profile_inventory(data["directory_pin"], list(data["pins"].values()),
        [binding(data)] if bindings is None else bindings, **options)


def publish(tmp_path, registry):
    return shared.write_json(tmp_path / "registry.json", registry)


def resolve(data, registry_pin, registry, **options):
    defaults = {"format_request": deepcopy(format_shared.SPECS[data["family"]]),
                "profile_id": registry["profiles"][0]["profile_id"], "run_id": "run-a"}
    defaults.update(options)
    return inventory.resolve_ir_decoder_profile_route(registry_pin, data["request"], **defaults)


def add_candidate(tmp_path, base, *, run_id="run-b", seed=2):
    candidate = make_profile_data(tmp_path, base["family"])
    candidate["checkpoint"]["config"]["seed"] = seed
    original_shared.repin(candidate)
    evidence = candidate["documents"][(candidate["family"], 384)]["existing_checkpoint_evidence"][0]
    base["documents"][(base["family"], 384)]["existing_checkpoint_evidence"].append(deepcopy(evidence))
    shared.rewrite_cell(base, base["family"], 384)
    return candidate, binding(candidate, run_id)


def change_fixture(data, change):
    checkpoint = data["checkpoint"]
    if change == "codec":
        vocabulary = checkpoint["codec"]["target_vocabulary"]
        vocabulary.append('"unused_token"')
        vocabulary[3:] = sorted(vocabulary[3:])
    elif change == "shape":
        checkpoint["config"]["hidden_size"] = 24
    elif change == "implementation":
        checkpoint["implementation"]["dependencies"]["synthetic.extra_implementation"] = "a" * 64
    elif change == "producer":
        checkpoint["config"]["embedding_provenance"]["model_id"] = "another_declared_producer"
    elif change == "source_budget":
        data["documents"][(data["family"], 384)]["dimension_profile"]["qualified_source_token_limit"] = 256
    elif change == "target_budget":
        checkpoint["config"]["max_target_tokens"] = 600
    elif change == "unknown_config":
        checkpoint["config"]["unknown_inference_option"] = {"declared": True}
    else:
        raise AssertionError(change)
    original_shared.repin(data)


@pytest.mark.parametrize("family", FAMILIES)
def test_catalog_is_detached_metadata_with_exact_format_and_profile_digests(tmp_path, forbidden_owners, family):
    data = make_profile_data(tmp_path, family)
    registry = build(data)
    assert registry["schema"] == "ir-decoder-profile-inventory/v1"
    assert len(registry["cells"]) == 12 and len(registry["formats"]) == len(registry["profiles"]) == 1
    assert len(registry["checkpoints"]) == 1 and registry["bindings"] == [binding(data)]
    assert registry["checkpoints"][0]["run_id_provenance"] == "operator_assigned_inventory_alias"
    format_record, profile = registry["formats"][0], registry["profiles"][0]
    assert format_record["format_id"] == "ir-decoder-format/v1:" + digest(format_record["identity"])
    assert profile["profile_id"] == "ir-decoder-profile/v1:" + digest(profile["identity"])
    assert profile["format_id"] == format_record["format_id"]
    assert format_record["identity"]["ir_family_id"] == family
    assert format_record["identity"]["target_format_id"] == format_shared.SPECS[family]["target_format_id"]
    assert format_record["identity"]["schema_version"] == format_shared.SPECS[family]["schema_version"]
    assert format_record["identity"]["task_id"] == "source_to_native_ir"
    assert format_record["identity"]["output_scope"] == "serialized_native_fragment"
    assert profile["identity"]["dimension"] == 384 and profile["identity"]["dimension_role"] == "input_embedding"
    assert profile["identity"]["declared_shape"] == {"input_width": 384, "projection_width": 8,
        "hidden_size": 16, "token_embedding_dim": 8, "status": "declared_not_tensor_verified",
        "tensor_shapes_verified": False}
    assert profile["identity"]["source_producer"]["status"] == "declared_not_execution_authenticated"
    assert profile["identity"]["source_budget_policy"]["qualified_source_token_limit"] is None
    assert profile["identity"]["target_budget_policy"] == {"max_target_tokens": 512,
                                                          "qualified_target_token_limit": None}
    assert not any(registry["authority"].values()) and forbidden_owners == []


@pytest.mark.parametrize("field", EXPERIMENT_KEYS)
def test_training_options_change_checkpoint_identity_without_changing_profile(data, field):
    before = build(data)
    data["checkpoint"]["config"][field] *= 2
    original_shared.repin(data)
    after = build(data)
    assert before["formats"] == after["formats"] and before["profiles"] == after["profiles"]
    assert before["checkpoints"] != after["checkpoints"]
    assert not any(after["authority"].values())


def test_paths_and_operator_run_aliases_are_outside_compatibility_profile(tmp_path):
    first = make_profile_data(tmp_path / "first")
    second = make_profile_data(tmp_path / "other-location")
    first_registry = build(first, [binding(first, "operator-label-a")])
    second_registry = build(second, [binding(second, "operator-label-b")])
    assert first_registry["formats"] == second_registry["formats"]
    assert first_registry["profiles"] == second_registry["profiles"]
    assert first_registry["checkpoints"] != second_registry["checkpoints"]
    assert first["request"]["checkpoint_sha256"] == second["request"]["checkpoint_sha256"]


def test_fitting_corpus_and_manifests_are_record_bindings_outside_profile(data):
    before = build(data)
    row = data["corpus"]["rows"][0]
    row["source_text"] = "Different private synthetic fitting source; target and vector held fixed."
    row["group_id"] = "different-private-fitting-group"
    original_shared.repin(data, manifests=True, row_digests=True)
    after = build(data)
    assert before["formats"] == after["formats"] and before["profiles"] == after["profiles"]
    first, second = before["checkpoints"][0], after["checkpoints"][0]
    assert first["record_id"] != second["record_id"]
    assert first["corpus_receipt"] != second["corpus_receipt"]
    assert first["training_manifest_sha256"] != second["training_manifest_sha256"]
    assert not any(after["authority"].values())


@pytest.mark.parametrize("change", ["codec", "shape", "implementation", "producer", "source_budget",
                                   "target_budget", "unknown_config"])
def test_inference_relevant_declarations_change_profile_without_new_physical_lane(data, change):
    before = build(data)
    change_fixture(data, change)
    after = build(data)
    assert before["formats"] == after["formats"]
    assert before["profiles"][0]["profile_id"] != after["profiles"][0]["profile_id"]
    assert len(after["cells"]) == 12 and len(after["profiles"]) == 1
    assert not any(after["authority"].values())


def test_profile_can_be_shared_by_two_distinct_checkpoint_run_records(tmp_path, data):
    candidate, second_binding = add_candidate(tmp_path / "candidate", data, run_id="run-a")
    registry = build(data, [binding(data), second_binding])
    assert len(registry["formats"]) == len(registry["profiles"]) == 1
    assert len(registry["checkpoints"]) == 2
    registry_pin = publish(tmp_path, registry)
    first = resolve(data, registry_pin, registry)
    second = resolve(candidate, registry_pin, registry)
    assert first["selected_profile"] == second["selected_profile"]
    assert first["selected_checkpoint"] != second["selected_checkpoint"]
    assert not any(first["authority"].values()) and not any(second["authority"].values())


def test_same_checkpoint_can_have_separate_explicit_operator_aliases(tmp_path, data):
    registry = build(data, [binding(data, "run-a"), binding(data, "run-b")])
    assert len(registry["profiles"]) == 1 and len(registry["checkpoints"]) == 2
    pin = publish(tmp_path, registry)
    first = resolve(data, pin, registry)
    second = resolve(data, pin, registry, run_id="run-b")
    assert first["selected_profile"] == second["selected_profile"]
    assert first["selected_checkpoint"] != second["selected_checkpoint"]
    assert first["replay_binding_options"]["request"] == second["replay_binding_options"]["request"]


def test_exact_duplicate_binding_is_rejected(data):
    record = binding(data)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        build(data, [record, deepcopy(record)])


@pytest.mark.parametrize("change", ["empty", "extra", "missing", "nonlist", "too_many"])
def test_binding_input_is_closed_bounded_and_has_no_split_fallback(data, change):
    record = binding(data)
    if change == "empty":
        records = []
    elif change == "extra":
        record["row_ids"] = ["intent_ir:test:0"]
        records = [record]
    elif change == "missing":
        del record["format_request"]
        records = [record]
    elif change == "nonlist":
        records = record
    else:
        records = [record] * 257
    with pytest.raises(inventory.DecoderProfileInventoryError):
        build(data, records)


@pytest.mark.parametrize("run_id", [None, "", True, "../foreign", "x" * 257])
def test_run_alias_is_explicit_bounded_and_is_not_an_implicit_training_claim(data, run_id):
    with pytest.raises(inventory.DecoderProfileInventoryError):
        build(data, [binding(data, run_id)])


@pytest.mark.parametrize("field,value", [("ir_family_id", "security_ir"), ("dimension", 768),
    ("dimension_role", "latent"), ("task_id", "native_ir_to_source"), ("checkpoint_sha256", "f" * 64)])
def test_foreign_request_rejects_without_owner_dispatch(tmp_path, data, field, value):
    registry = build(data)
    pin = publish(tmp_path, registry)
    data["request"][field] = value
    with pytest.raises(inventory.DecoderProfileInventoryError):
        resolve(data, pin, registry)


@pytest.mark.parametrize("field,value", [("target_format_id", "intent_ir/full_document"),
    ("schema_version", "intent-rich-grammar/v2"), ("task_id", "native_ir_to_logic")])
def test_foreign_format_and_version_rejects_without_owner_dispatch(tmp_path, data, field, value):
    registry = build(data)
    pin = publish(tmp_path, registry)
    request = deepcopy(format_shared.SPECS["intent_ir"])
    request[field] = value
    with pytest.raises(inventory.DecoderProfileInventoryError):
        resolve(data, pin, registry, format_request=request)


@pytest.mark.parametrize("field,value", [("profile_id", "ir-decoder-profile/v1:" + "f" * 64),
                                       ("run_id", "absent-run")])
def test_foreign_profile_or_run_has_no_default_selection(tmp_path, data, field, value):
    registry = build(data)
    pin = publish(tmp_path, registry)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        resolve(data, pin, registry, **{field: value})


def test_registry_export_contains_pins_and_hashes_without_training_targets_or_vector_bodies(data):
    registry = build(data)
    forbidden = {"source_text", "embedding", "target", "native_evidence", "model_state", "optimizer_state"}
    def check(value):
        if type(value) is dict:
            assert forbidden.isdisjoint(value)
            for item in value.values():
                check(item)
        elif type(value) is list:
            for item in value:
                check(item)
    check(registry)


def test_old_five_field_prepare_api_remains_separate_from_catalog(data):
    before = format_shared.prepare(data)
    registry = build(data)
    after = format_shared.prepare(data)
    assert before == after and len(registry["cells"]) == 12
    assert set(data["request"]) == {"ir_family_id", "dimension", "dimension_role", "task_id", "checkpoint_sha256"}
    assert "profile_id" not in data["request"] and "run_id" not in data["request"]


def test_all_twelve_declared_lanes_remain_present_with_unbound_checkpoints(data):
    registry = build(data)
    cells = {(row["ir_family_id"], row["dimension"]): row for row in registry["cells"]}
    assert set(cells) == set(shared.CELLS)
    for key, cell in cells.items():
        declaration = data["documents"][key]
        assert cell["original_declared_checkpoints"] == declaration["existing_checkpoint_evidence"]
        assert cell["storage_plan"] == declaration["storage"]
        assert cell["huggingface_plan"] == declaration["huggingface"]
        assert not any(cell["authority"].values())
        if key == ("intent_ir", 384):
            assert cell["binding_status"] == "registered_supported_formats"
            assert len(cell["registered_record_ids"]) == 1
        else:
            assert cell["binding_status"] == "declared_only_no_supported_format_binding"
            assert cell["registered_record_ids"] == []
    assert cells[("legal_ir", 768)]["original_declared_checkpoints"]
    legal_768 = cells[("legal_ir", 768)]
    assert legal_768["reference_checks"]["checkpoints"][0]["status"] == "verified"
    assert legal_768["registered_record_ids"] == []
    codebase_8 = cells[("codebase_ir", 8)]["original_declared_checkpoints"][0]
    assert codebase_8["dimension_role"] == "latent" and codebase_8["latent_width"] == 8
    assert codebase_8["input_width"] == 53
    codebase_384 = cells[("codebase_ir", 384)]["original_declared_checkpoints"][0]
    assert codebase_384["payload_ir_family"] == "security_ir"


@pytest.mark.parametrize("change", ["authority", "profile_identity", "run_label", "missing_cell"])
def test_byte_authenticated_registry_tampering_rejects_independent_rebuild(tmp_path, data, change):
    registry = build(data)
    tampered = deepcopy(registry)
    if change == "authority":
        tampered["authority"][next(iter(tampered["authority"]))] = True
    elif change == "profile_identity":
        tampered["profiles"][0]["identity"]["dimension"] = 768
    elif change == "run_label":
        tampered["checkpoints"][0]["run_id"] = "forged-alias"
    else:
        tampered["cells"].pop()
    pin = publish(tmp_path, tampered)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        resolve(data, pin, registry)


def test_registry_raw_pin_drift_rejects_before_returning_any_selection(tmp_path, data):
    registry = build(data)
    pin = publish(tmp_path, registry)
    path = Path(pin["path"])
    path.write_bytes(path.read_bytes() + b"\n ")
    with pytest.raises(inventory.DecoderProfileInventoryError):
        resolve(data, pin, registry)


@pytest.mark.parametrize("artifact", ["checkpoint", "corpus", "package", "directory", "cell", "unselected_cache"])
def test_referenced_asset_drift_invalidates_whole_registry_rebuild(tmp_path, data, artifact):
    registry = build(data)
    pin = publish(tmp_path, registry)
    if artifact == "unselected_cache":
        record = data["documents"][("legal_ir", 384)]["existing_cached_vector_rows"][0]
        path = Path(record["receipt"]["path"])
        path.write_bytes(path.read_bytes() + b" changed")
    else:
        format_shared.alter_bytes(data, artifact)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        resolve(data, pin, registry)


@pytest.mark.parametrize("field,value", [("profile_id", None), ("profile_id", ""), ("run_id", None)])
def test_resolver_requires_explicit_profile_and_run_even_for_single_candidate(tmp_path, data, field, value):
    registry = build(data)
    pin = publish(tmp_path, registry)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        resolve(data, pin, registry, **{field: value})


def test_bindings_are_captured_and_returned_catalogs_are_detached(data):
    records = [binding(data)]
    before = deepcopy(records)
    first = build(data, records)
    assert records == before
    records[0]["run_id"] = "mutated-caller"
    records[0]["request"]["task_id"] = "native_ir_to_source"
    assert first["bindings"] == before
    first["profiles"][0]["identity"]["dimension"] = 768
    first["cells"][0]["original_declared_checkpoints"].clear()
    second = build(data)
    assert second["profiles"][0]["identity"]["dimension"] == 384
    assert data["documents"][("legal_ir", 8)]["existing_checkpoint_evidence"]
    assert not any(second["authority"].values())


def test_resolved_records_and_replay_options_are_detached_without_row_selection(tmp_path, data):
    registry = build(data)
    pin = publish(tmp_path, registry)
    first = resolve(data, pin, registry)
    assert first["schema"] == "ir-decoder-profile-route/v1"
    expected = binding(data)
    del expected["run_id"]
    expected.update(directory_plan_pin=data["directory_pin"],
                    inventory_pins=sorted(data["pins"].values(), key=lambda item: item["path"]))
    assert first["replay_binding_options"] == expected
    assert "row_ids" not in first["replay_binding_options"] and "corpus_split" not in first["replay_binding_options"]
    first["selected_profile"]["identity"]["dimension"] = 768
    first["selected_checkpoint"]["run_id"] = "mutated-result"
    first["replay_binding_options"]["request"]["checkpoint_sha256"] = "f" * 64
    second = resolve(data, pin, registry)
    assert second["selected_profile"]["identity"]["dimension"] == 384
    assert second["selected_checkpoint"]["run_id"] == "run-a"
    assert second["replay_binding_options"] == expected


def test_missing_shape_and_producer_stay_unknown_instead_of_inferred_defaults(data):
    for field in ("hidden_size", "token_embedding_dim", "projection_width", "embedding_provenance"):
        data["checkpoint"]["config"].pop(field)
    original_shared.repin(data)
    registry = build(data)
    identity = registry["profiles"][0]["identity"]
    assert identity["decoder_configuration"] == {"max_target_tokens": 512}
    assert identity["source_producer"]["embedding_provenance"] is None
    assert identity["source_producer"]["status"] == "unknown"
    assert identity["declared_shape"] == {"input_width": 384, "projection_width": None,
        "hidden_size": None, "token_embedding_dim": None, "status": "unknown", "tensor_shapes_verified": False}
    assert not any(registry["authority"].values())


def test_producer_elapsed_and_execution_observations_are_excluded_from_identity(data):
    before = build(data)
    provenance = data["checkpoint"]["config"]["embedding_provenance"]
    provenance.update(elapsed_seconds_including_load=123.0, vectors_executed=True)
    original_shared.repin(data)
    after = build(data)
    assert before["formats"] == after["formats"] and before["profiles"] == after["profiles"]
    assert before["checkpoints"] != after["checkpoints"]
    assert not any(after["authority"].values())


def test_binding_order_does_not_change_format_or_profile_identifiers(tmp_path, data):
    _, other = add_candidate(tmp_path / "candidate", data)
    forward = build(data, [binding(data), other])
    reverse = build(data, [other, binding(data)])
    assert forward["formats"] == reverse["formats"] and forward["profiles"] == reverse["profiles"]
    assert {row["record_id"] for row in forward["checkpoints"]} == {row["record_id"] for row in reverse["checkpoints"]}


def test_missing_unsupported_checkpoint_remains_declared_unavailable(data):
    declared = deepcopy(data["documents"][("legal_ir", 768)]["existing_checkpoint_evidence"])
    Path(declared[0]["receipt"]["path"]).unlink()
    registry = build(data)
    cell = next(cell for cell in registry["cells"] if cell["ir_family_id"] == "legal_ir" and cell["dimension"] == 768)
    assert cell["original_declared_checkpoints"] == declared
    assert cell["reference_checks"]["checkpoints"][0]["status"] == "unavailable"
    assert cell["reference_checks"]["checkpoints"][0]["receipt"] == declared[0]["receipt"]
    assert cell["binding_status"] == "declared_only_no_supported_format_binding"
    assert cell["registered_record_ids"] == [] and not any(cell["authority"].values())


def test_two_family_formats_coexist_inside_existing_lanes(tmp_path, data):
    other = make_profile_data(tmp_path / "security", "security_ir")
    evidence = other["documents"][("security_ir", 384)]["existing_checkpoint_evidence"]
    data["documents"][("security_ir", 384)]["existing_checkpoint_evidence"] = deepcopy(evidence)
    shared.rewrite_cell(data, "security_ir", 384)
    registry = build(data, [binding(data), binding(other, "security-run")])
    assert len(registry["cells"]) == 12 and len(registry["formats"]) == len(registry["profiles"]) == 2
    assert {record["identity"]["ir_family_id"] for record in registry["formats"]} == set(FAMILIES)
    assert len({record["format_id"] for record in registry["formats"]}) == 2
    supported = [cell for cell in registry["cells"] if cell["binding_status"] == "registered_supported_formats"]
    assert {(cell["ir_family_id"], cell["dimension"]) for cell in supported} == {("intent_ir", 384), ("security_ir", 384)}
    pin = publish(tmp_path, registry)
    other_profile = next(profile for profile in registry["profiles"] if
                         profile["identity"]["ir_family_id"] == "security_ir")
    selected = resolve(other, pin, registry, profile_id=other_profile["profile_id"], run_id="security-run")
    assert selected["selected_format"]["identity"]["ir_family_id"] == "security_ir"
    assert not any(selected["authority"].values())


@pytest.mark.parametrize("artifact", ["package", "unselected_cache"])
def test_late_asset_change_after_lane_capture_is_refused(data, monkeypatch, artifact):
    original_cells = inventory._cells
    reached = []
    def cells_then_change(options, records):
        captured = original_cells(options, records)
        reached.append(True)
        if artifact == "package":
            format_shared.alter_bytes(data, "package")
        else:
            cache = data["documents"][("legal_ir", 384)]["existing_cached_vector_rows"][0]["receipt"]
            path = Path(cache["path"])
            path.write_bytes(path.read_bytes() + b" changed after capture")
        return captured
    # The genuine metadata capture runs first; only a private file changes at
    # its return boundary. No model, native validator or fabricated receipt.
    monkeypatch.setattr(inventory, "_cells", cells_then_change)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        build(data)
    assert reached


# Counted metadata reuses the actual public codec and old declared layout.
# No checkpoint, state tensor, model, source preparation or registry is made.
@pytest.fixture(scope="module")
def counted_head_codec():
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    return counted.build_counted_frame_token_codec_v1()


@pytest.fixture(scope="module")
def counted_head_spec(counted_head_codec):
    return inventory.build_counted_content_head_spec_v1(counted_head_codec,
        expected_codec_sha256=digest(counted_head_codec))


def _counted_spec_build(codec, config=None):
    return inventory.build_counted_content_head_spec_v1(codec,
        expected_codec_sha256=digest(codec), config=config)


def _counted_spec_validate(spec, codec, config=None):
    return inventory.validate_counted_content_head_spec_v1(spec, codec,
        expected_spec_sha256=inventory.counted_content_head_spec_sha256(spec),
        expected_codec_sha256=digest(codec), config=config)


def test_counted_head_spec_uses_genuine_pure_owners_without_models_or_registry(
        counted_head_codec, counted_head_spec, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
    actual_codec, actual_shapes = counted.build_counted_frame_token_codec_v1, head._shapes
    seen = []

    def codec():
        seen.append("public counted codec")
        return actual_codec()

    def shapes(config):
        seen.append("original thirteen-shape declaration")
        return actual_shapes(config)

    def denied(*args, **kwargs):
        raise AssertionError("declared metadata allocated or dispatched a numerical model or registry")

    monkeypatch.setattr(counted, "build_counted_frame_token_codec_v1", codec)
    monkeypatch.setattr(head, "_shapes", shapes)
    for name in ("_torch", "_new_model", "_model", "_forward"):
        monkeypatch.setattr(head, name, denied)
    monkeypatch.setattr(inventory, "_cells", denied)
    offered = deepcopy(counted_head_codec)
    spec = _counted_spec_build(offered)
    assert spec == counted_head_spec and offered == counted_head_codec
    assert seen == ["public counted codec", "original thirteen-shape declaration"]
    assert _counted_spec_validate(spec, offered) == spec
    assert seen == ["public counted codec", "original thirteen-shape declaration"] * 2
    assert spec["schema"] == "legal-counted-content-head-spec/v1"
    assert spec["scope"] == "declared_checkpoint_free_counted_head_spec_only"
    assert spec["spec_id"] == spec["schema"] + ":" + digest(spec["identity"])
    assert spec["identity"]["input"] == {
        "dimension": 384, "dimension_role": "input_embedding", "space": "raw_native_gte_small384",
        "conditioning_schema": "legal-compact-source-conditioning/v1",
        "conditioning_profile": "exact-native-gte-small384-receipt-reuse/v1",
        "model": "thenlper/gte-small", "revision": "17e1f347d17fe144873b1201da91788898c639cd",
        "asset_manifest_sha256": "def8d7e04c05560b1d0dd1fa9317be7a59a1ba8399ca725be0ac807a9a264edc"}
    for name in ("runtime_compatible", "tensor_shapes_verified", "checkpoint_compatible",
                 "prefix_api_available", "permitted_source_only_context", "varied_reviewed_targets_supplied"):
        assert spec[name] is False
    assert all(type(value) is bool and value is False for value in spec["authority"].values())
    for name in ("training_mask", "evaluation_gold_mask", "model_calls", "training_calls"):
        assert type(spec[name]) is int and spec[name] == 0
    assert not {"model_state", "checkpoint", "weights", "source_request", "conditioning", "target"} & set(spec)


def test_counted_head_spec_changes_only_three_lexical_dimensions_and_counts_arithmetic(counted_head_spec):
    identity = counted_head_spec["identity"]
    assert identity["geometry"] == {"hidden_size": 32, "token_embedding_dim": 16, "projection_width": 16}
    assert identity["tensor_shapes"] == {
        "projection_down.weight": [16, 384], "projection_down.bias": [16],
        "projection_up.weight": [384, 16], "projection_up.bias": [384],
        "condition.weight": [32, 384], "condition.bias": [32],
        "target_embedding.weight": [28, 16], "decoder.weight_ih_l0": [96, 16],
        "decoder.weight_hh_l0": [96, 32], "decoder.bias_ih_l0": [96],
        "decoder.bias_hh_l0": [96], "output.weight": [28, 32], "output.bias": [28]}
    assert identity["lexical_shape_changes"] == [
        {"tensor": "target_embedding.weight", "axis": 0, "before": [537, 16], "after": [28, 16]},
        {"tensor": "output.weight", "axis": 0, "before": [537, 32], "after": [28, 32]},
        {"tensor": "output.bias", "axis": 0, "before": [537], "after": [28]}]
    assert identity["parameter_count"] == 31180 and identity["parameter_bytes"] == 124720
    assert identity["codec"]["vocabulary_size"] == 28 and identity["max_total_ids"] == 512
    assert identity["codec"]["vocabulary"][:3] == ["<pad>", "<bos>", "<eos>"]


@pytest.mark.parametrize("config", [{}, {"hidden_size": 8},
    {"hidden_size": 128, "token_embedding_dim": 64, "projection_width": 64}])
def test_counted_head_spec_geometry_is_declared_and_has_exact_complete_shape_arithmetic(counted_head_codec, config):
    spec = _counted_spec_build(counted_head_codec, config)
    identity = spec["identity"]
    h, e, p = (identity["geometry"][key] for key in ("hidden_size", "token_embedding_dim", "projection_width"))
    expected_parameters = p*384+p + 384*p+384 + h*384+h + 28*e + 3*h*e + 3*h*h + 6*h + 28*h+28
    assert identity["parameter_count"] == expected_parameters
    assert identity["parameter_bytes"] == 4*expected_parameters
    assert len(identity["tensor_shapes"]) == 13
    assert _counted_spec_validate(spec, counted_head_codec, config) == spec


@pytest.mark.parametrize("config", [{"hidden_size": True}, {"hidden_size": 0}, {"hidden_size": 129},
    {"token_embedding_dim": 7}, {"token_embedding_dim": 65}, {"projection_width": 0},
    {"projection_width": 65}, {"seed": 1729}, {"input_dimension": 768}])
def test_counted_head_spec_rejects_invalid_geometry_before_operation_owner_import(counted_head_codec, monkeypatch, config):
    monkeypatch.setattr(inventory, "_counted_head_owners", lambda: pytest.fail("invalid geometry reached operation owners"))
    with pytest.raises(inventory.DecoderProfileInventoryError):
        _counted_spec_build(counted_head_codec, config)


@pytest.mark.parametrize("damage", ["old_schema", "old_vocabulary_size", "vocabulary_order", "prefix_claim", "boolean_id"])
def test_counted_head_spec_rehashed_foreign_codec_is_refused_before_owners(counted_head_codec, monkeypatch, damage):
    codec = deepcopy(counted_head_codec)
    if damage == "old_schema": codec["schema"] = "legal-compact-content-token-codec/v1"
    elif damage == "old_vocabulary_size": codec["vocabulary_size"] = 537
    elif damage == "vocabulary_order": codec["vocabulary"].reverse()
    elif damage == "prefix_claim": codec["allowed_prefix_api"] = True
    else: codec["bos_id"] = True
    monkeypatch.setattr(inventory, "_counted_head_owners", lambda: pytest.fail("foreign codec reached owners"))
    with pytest.raises(inventory.DecoderProfileInventoryError):
        _counted_spec_build(codec)


@pytest.mark.parametrize("part,pin", [("codec", "0" * 64), ("spec", "0" * 64),
    ("spec", "A" * 64), ("spec", True)])
def test_counted_head_spec_independent_full_pins_are_required_before_owners(
        counted_head_codec, counted_head_spec, monkeypatch, part, pin):
    monkeypatch.setattr(inventory, "_counted_head_owners", lambda: pytest.fail("wrong independent pin reached owners"))
    with pytest.raises(inventory.DecoderProfileInventoryError):
        if part == "codec":
            inventory.build_counted_content_head_spec_v1(counted_head_codec, expected_codec_sha256=pin)
        else:
            inventory.validate_counted_content_head_spec_v1(counted_head_spec, counted_head_codec,
                expected_spec_sha256=pin, expected_codec_sha256=digest(counted_head_codec))


@pytest.mark.parametrize("damage", ["shape", "parameter_count", "input_space", "runtime", "permission", "authority", "mask_bool", "extra"])
def test_counted_head_spec_resealed_claims_cannot_replace_public_regeneration(
        counted_head_codec, counted_head_spec, damage):
    spec = deepcopy(counted_head_spec)
    if damage == "shape": spec["identity"]["tensor_shapes"]["output.weight"][0] = 537
    elif damage == "parameter_count": spec["identity"]["parameter_count"] += 1
    elif damage == "input_space": spec["identity"]["input"]["space"] = "trained384"
    elif damage == "runtime": spec["runtime_compatible"] = True
    elif damage == "permission": spec["permitted_source_only_context"] = True
    elif damage == "authority": spec["authority"]["tensor_shapes_verified"] = True
    elif damage == "mask_bool": spec["training_mask"] = False
    else: spec["checkpoint"] = {"path": "/must/not/be/read/model"}
    with pytest.raises(inventory.DecoderProfileInventoryError):
        _counted_spec_validate(spec, counted_head_codec)


def test_counted_head_spec_validation_reuses_independent_original_geometry(counted_head_codec):
    config = {"hidden_size": 64}
    spec = _counted_spec_build(counted_head_codec, config)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        _counted_spec_validate(spec, counted_head_codec)
    assert _counted_spec_validate(spec, counted_head_codec, config) == spec


@pytest.mark.parametrize("constant", ["_COUNTED_HEAD_SELF_SHA", "_COUNTED_HEAD_OWNER_SHA", "_COUNTED_CODEC_OWNER_SHA"])
def test_counted_head_spec_stale_known_sources_are_refused_before_lazy_import(counted_head_codec, monkeypatch, constant):
    monkeypatch.setattr(inventory, constant, "0" * 64)
    monkeypatch.setattr(inventory.importlib, "import_module", lambda *_: pytest.fail("stale source reached lazy imports"))
    with pytest.raises(inventory.DecoderProfileInventoryError):
        _counted_spec_build(counted_head_codec)


@pytest.mark.parametrize("which", ["counted", "head"])
def test_counted_head_spec_foreign_preimported_owner_origin_never_opens_foreign_source(
        counted_head_codec, monkeypatch, which, tmp_path):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
    owner = counted if which == "counted" else head
    foreign = tmp_path / "foreign-owner.py"
    real_source, opened = inventory._counted_head_source, []

    def source(path, expected):
        opened.append(path)
        assert path != foreign
        return real_source(path, expected)

    monkeypatch.setattr(inventory, "_counted_head_source", source)
    monkeypatch.setattr(owner, "__file__", str(foreign))
    with pytest.raises(inventory.DecoderProfileInventoryError):
        _counted_spec_build(counted_head_codec)
    assert opened and foreign not in opened


@pytest.mark.parametrize("boundary,target", [("codec", "original"), ("codec", "captured"),
    ("layout", "original"), ("layout", "captured")])
def test_counted_head_spec_caller_and_captured_inputs_are_fenced(
        counted_head_codec, monkeypatch, boundary, target):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
    codec, config = deepcopy(counted_head_codec), {"hidden_size": 32}
    actual_copy = inventory._counted_head_copy
    actual_codec, actual_layout = counted.build_counted_frame_token_codec_v1, head._shapes
    captured = []

    def copy(value, *args, **kwargs):
        result = actual_copy(value, *args, **kwargs)
        if type(value) is dict and set(value) == {"codec", "config"} and not captured:
            captured.append(result)
        return result

    def mutate():
        row = config if target == "original" else captured[0]["config"]
        row["hidden_size"] = 64

    def public_codec():
        result = actual_codec()
        if boundary == "codec": mutate()
        return result

    def layout(value):
        result = actual_layout(value)
        if boundary == "layout": mutate()
        return result

    monkeypatch.setattr(inventory, "_counted_head_copy", copy)
    monkeypatch.setattr(counted, "build_counted_frame_token_codec_v1", public_codec)
    monkeypatch.setattr(head, "_shapes", layout)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        inventory.build_counted_content_head_spec_v1(codec, expected_codec_sha256=digest(codec), config=config)


@pytest.mark.parametrize("boundary", ["layout", "final_wire"])
def test_counted_head_spec_producer_fences_extend_through_final_serialization(
        counted_head_codec, monkeypatch, boundary):
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
    actual_layout, actual_wire = head._shapes, inventory._counted_head_wire

    def layout(value):
        result = actual_layout(value)
        if boundary == "layout": monkeypatch.setattr(inventory, "_COUNTED_HEAD_OWNER_SHA", "0" * 64)
        return result

    def wire(value):
        result = actual_wire(value)
        if boundary == "final_wire" and type(value) is dict and value.get("schema") == "legal-counted-content-head-spec/v1":
            monkeypatch.setattr(inventory, "_COUNTED_HEAD_OWNER_SHA", "0" * 64)
        return result

    monkeypatch.setattr(head, "_shapes", layout)
    monkeypatch.setattr(inventory, "_counted_head_wire", wire)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        _counted_spec_build(counted_head_codec)


def test_counted_head_spec_validator_fences_offered_report_during_regeneration(
        counted_head_codec, counted_head_spec, monkeypatch):
    offered = deepcopy(counted_head_spec)
    actual = inventory.build_counted_content_head_spec_v1
    pin = inventory.counted_content_head_spec_sha256(offered)

    def regenerate(*args, **kwargs):
        result = actual(*args, **kwargs)
        offered["identity"]["parameter_count"] += 1
        return result

    monkeypatch.setattr(inventory, "build_counted_content_head_spec_v1", regenerate)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        inventory.validate_counted_content_head_spec_v1(offered, counted_head_codec,
            expected_spec_sha256=pin, expected_codec_sha256=digest(counted_head_codec))


@pytest.mark.parametrize("boundary", ["codec", "layout", "final_wire"])
def test_counted_head_spec_loaded_owner_origins_are_fenced_through_final_serialization(
        counted_head_codec, monkeypatch, tmp_path, boundary):
    from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as counted
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
    actual_codec, actual_layout = counted.build_counted_frame_token_codec_v1, head._shapes
    actual_wire = inventory._counted_head_wire
    foreign = str(tmp_path / "not-opened-relocated-head.py")

    def relocate():
        monkeypatch.setattr(head, "__file__", foreign)

    def codec():
        result = actual_codec()
        if boundary == "codec": relocate()
        return result

    def layout(value):
        result = actual_layout(value)
        if boundary == "layout": relocate()
        return result

    def wire(value):
        result = actual_wire(value)
        if boundary == "final_wire" and type(value) is dict and value.get("schema") == "legal-counted-content-head-spec/v1":
            relocate()
        return result

    monkeypatch.setattr(counted, "build_counted_frame_token_codec_v1", codec)
    monkeypatch.setattr(head, "_shapes", layout)
    monkeypatch.setattr(inventory, "_counted_head_wire", wire)
    with pytest.raises(inventory.DecoderProfileInventoryError, match="owner origin"):
        _counted_spec_build(counted_head_codec)


@pytest.mark.parametrize("damage", ["cycle", "float", "foreign_key", "foreign_container", "lowered_bound"])
def test_counted_head_spec_bounded_plain_inputs_precede_operation_owners(counted_head_codec, monkeypatch, damage):
    codec = deepcopy(counted_head_codec)
    if damage == "cycle": codec["cycle"] = codec
    elif damage == "float": codec["unsupported"] = float("nan")
    elif damage == "foreign_key":
        class ForeignKey(str):
            pass
        codec[ForeignKey("unsupported")] = 1
    elif damage == "foreign_container":
        class ForeignDict(dict):
            pass
        codec = ForeignDict(codec)
    else: monkeypatch.setattr(inventory, "MAX_COUNTED_HEAD_SPEC_BYTES", 32)
    monkeypatch.setattr(inventory, "_counted_head_owners", lambda: pytest.fail("malformed metadata reached owners"))
    with pytest.raises(inventory.DecoderProfileInventoryError):
        inventory.build_counted_content_head_spec_v1(codec,
            expected_codec_sha256="8a1e8e0f8c6c2259b7c1040d3518974b1c84ac6d532521199f46a76b7d78dcd8")
# The narrow transfer companion reuses the peer head-spec and pure mapping
# owners. All donor hashes below are authored placeholders, never weight paths.
def _counted_transfer_donor_fixture(spec, *, conditioning='authored_sparse384'):
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_tokens_v1
    vocabulary = legal_compact_content_tokens_v1.build_compact_content_token_codec_v1()['vocabulary']
    return dict(schema='legal-counted-content-head-donor-declaration/v1',
        profile='authored_unverified_public537_vocabulary_only',
        architecture='residual-projection-latent-formula-gru/v1', input_dimension=384,
        input_role='caller_supplied_conditioning_vector', geometry=deepcopy(spec['identity']['geometry']),
        checkpoint_sha256='1'*64, weights_sha256='2'*64, vocabulary=vocabulary,
        vocabulary_sha256=hashlib.sha256(inventory._counted_head_wire(vocabulary)).hexdigest(),
        torch_version='authored_no_runtime_validation', conditioning_profile=conditioning)


def _counted_transfer_build(spec, codec, donor, config=None):
    return inventory.plan_counted_content_head_transfer_v1(spec, codec,
        expected_spec_sha256=inventory.counted_content_head_spec_sha256(spec),
        expected_codec_sha256=inventory.counted_content_head_spec_sha256(codec),
        donor_declaration=donor, config=config)


def _counted_transfer_validate(plan, spec, codec, donor, config=None):
    return inventory.validate_counted_content_head_transfer_v1(plan, spec, codec,
        expected_plan_sha256=inventory.counted_content_head_transfer_sha256(plan),
        expected_spec_sha256=inventory.counted_content_head_spec_sha256(spec),
        expected_codec_sha256=inventory.counted_content_head_spec_sha256(codec),
        donor_declaration=donor, config=config)


def test_counted_transfer_reuses_public_spec_and_genuine_head_spelling_map(counted_head_codec, counted_head_spec, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
    donor = _counted_transfer_donor_fixture(counted_head_spec)
    actual_map, actual_spec = head._token_rows, inventory.validate_counted_content_head_spec_v1
    mapped, replayed = [], []
    def mapping(*args):
        mapped.append(deepcopy(args))
        return actual_map(*args)
    def validate(*args, **kwargs):
        replayed.append(kwargs['expected_spec_sha256'])
        return actual_spec(*args, **kwargs)
    monkeypatch.setattr(head, '_token_rows', mapping)
    monkeypatch.setattr(inventory, 'validate_counted_content_head_spec_v1', validate)
    plan = _counted_transfer_build(counted_head_spec, counted_head_codec, donor)
    assert len(replayed) == len(mapped) == 1
    assert mapped[0] == (counted_head_codec['vocabulary'], donor['vocabulary'])
    assert plan['lexical_row_map'] == actual_map(*mapped[0])
    assert plan['spec'] == counted_head_spec
    assert plan['target_conditioning_space'] == 'raw_native_gte_small384'
    assert plan['declared_conditioning_relation'] == 'different'
    assert len([r for r in plan['lexical_row_map'] if r['parent_token_id'] is not None]) == 23
    assert len([r for r in plan['lexical_row_map'] if r['parent_token_id'] is None]) == 5
    ledger = plan['tensor_ledger']
    assert len(ledger) == 13
    assert {r['parameter']: r['target_shape'] for r in ledger} == counted_head_spec['identity']['tensor_shapes']
    lexical = {'target_embedding.weight', 'output.weight', 'output.bias'}
    assert len([r for r in ledger if r['parameter'] not in lexical]) == 10
    assert all(r['declared_donor_shape'] == r['target_shape'] for r in ledger if r['parameter'] not in lexical)
    assert all(r['target_shape'][0] == 28 and r['declared_donor_shape'][0] == 537 for r in ledger if r['parameter'] in lexical)
    assert all(r['semantic_role'] and r['fit_policy'] == 'unprovided' for r in ledger)
    assert plan['donor_validation_scope'] == 'bounded_caller_declaration_only'
    assert plan['optimizer_policy'] == dict(fresh_required=True, inherit_donor_state=False,
        exact_Adam_continuation_supported=False, optimizer_created=False)
    assert not any(plan['authority'].values()) and all(type(v) is bool for v in plan['authority'].values())
    assert plan['training_mask'] == plan['evaluation_gold_mask'] == plan['model_calls'] == plan['transfer_calls'] == plan['training_calls'] == 0


def test_counted_transfer_plan_roundtrip_is_detached_and_metadata_only(counted_head_codec, counted_head_spec):
    donor = _counted_transfer_donor_fixture(counted_head_spec)
    plan = _counted_transfer_build(counted_head_spec, counted_head_codec, donor)
    assert _counted_transfer_validate(plan, counted_head_spec, counted_head_codec, donor) == plan
    assert _counted_transfer_build(counted_head_spec, counted_head_codec, donor) == plan
    assert plan['fixed_language'] == dict(admissible_content_count=1, admissible_context_count=1,
        varied_target_population=False, source_dependence_established=False)
    assert not any(plan['implementation_readiness'].values())
    assert plan['unresolved']['complete_statutory_target'] is None
    donor['profile'] = 'caller-mutation-after-success'
    assert plan['donor_declaration']['profile'] != donor['profile']
    assert 'model_state' not in plan and 'optimizer_state' not in plan


@pytest.mark.parametrize('conditioning,expected', [('raw_native_gte_small384', 'matching'),
    ('authored_sparse384', 'different'), ('caller_supplied_unverified384', 'unknown')])
def test_counted_transfer_conditioning_comparison_remains_unqualified(counted_head_codec, counted_head_spec, conditioning, expected):
    donor = _counted_transfer_donor_fixture(counted_head_spec, conditioning=conditioning)
    plan = _counted_transfer_build(counted_head_spec, counted_head_codec, donor)
    assert plan['declared_conditioning_relation'] == expected
    assert plan['authority']['conditioning_space_compatible'] is False
    assert plan['unresolved']['conditioning_space_compatibility'] == 'unprovided'


@pytest.mark.parametrize('damage', ['dimension', 'geometry', 'duplicate_vocab', 'vocab_hash', 'weights_body', 'missing', 'bool_config', 'none'])
def test_counted_transfer_declared_donor_is_closed_bounded_and_not_a_checkpoint(counted_head_codec, counted_head_spec, monkeypatch, damage):
    donor = _counted_transfer_donor_fixture(counted_head_spec)
    if damage == 'dimension': donor['input_dimension'] = 768
    elif damage == 'geometry': donor['geometry']['hidden_size'] = 64
    elif damage == 'duplicate_vocab': donor['vocabulary'][-1] = donor['vocabulary'][0]
    elif damage == 'vocab_hash': donor['vocabulary_sha256'] = '3'*64
    elif damage == 'weights_body': donor['model_state'] = {'not-accepted': []}
    elif damage == 'missing': donor.pop('checkpoint_sha256')
    elif damage == 'bool_config': donor['geometry']['hidden_size'] = True
    else: donor = None
    with pytest.raises(inventory.DecoderProfileInventoryError):
        _counted_transfer_build(counted_head_spec, counted_head_codec, donor)


@pytest.mark.parametrize('damage', ['row_map', 'shape', 'authority', 'optimizer', 'mask_bool', 'singleton_bool'])
def test_counted_transfer_resealed_plan_cannot_promote_or_change_original_metadata(counted_head_codec, counted_head_spec, damage):
    donor = _counted_transfer_donor_fixture(counted_head_spec)
    plan = _counted_transfer_build(counted_head_spec, counted_head_codec, donor)
    if damage == 'row_map': plan['lexical_row_map'][0]['parent_token_id'] = 3
    elif damage == 'shape': plan['tensor_ledger'][0]['target_shape'][0] += 1
    elif damage == 'authority': plan['authority']['weights_transferred'] = True
    elif damage == 'optimizer': plan['optimizer_policy']['inherit_donor_state'] = True
    elif damage == 'mask_bool': plan['training_mask'] = False
    else: plan['fixed_language']['admissible_content_count'] = True
    with pytest.raises(inventory.DecoderProfileInventoryError):
        _counted_transfer_validate(plan, counted_head_spec, counted_head_codec, donor)


@pytest.mark.parametrize('location', ['spec', 'codec', 'donor'])
def test_counted_transfer_original_inputs_close_after_genuine_head_mapping(counted_head_codec, counted_head_spec, monkeypatch, location):
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
    spec, codec = deepcopy(counted_head_spec), deepcopy(counted_head_codec)
    donor = _counted_transfer_donor_fixture(spec)
    actual = head._token_rows
    def mapping(*args):
        result = actual(*args)
        if location == 'spec': spec['scope'] = 'mutated-after-genuine-map'
        elif location == 'codec': codec['profile'] = 'mutated-after-genuine-map'
        else: donor['profile'] = 'mutated-after-genuine-map'
        return result
    monkeypatch.setattr(head, '_token_rows', mapping)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        _counted_transfer_build(spec, codec, donor)


def test_counted_transfer_requires_original_geometry_and_independent_whole_plan_pin(counted_head_codec):
    config = dict(hidden_size=16, token_embedding_dim=8, projection_width=4)
    spec = _counted_spec_build(counted_head_codec, config)
    donor = _counted_transfer_donor_fixture(spec)
    plan = _counted_transfer_build(spec, counted_head_codec, donor, config)
    assert _counted_transfer_validate(plan, spec, counted_head_codec, donor, config) == plan
    with pytest.raises(inventory.DecoderProfileInventoryError): _counted_transfer_build(spec, counted_head_codec, donor)
    with pytest.raises(inventory.DecoderProfileInventoryError):
        inventory.validate_counted_content_head_transfer_v1(plan, spec, counted_head_codec,
            expected_plan_sha256='0'*64, expected_spec_sha256=inventory.counted_content_head_spec_sha256(spec),
            expected_codec_sha256=inventory.counted_content_head_spec_sha256(counted_head_codec),
            donor_declaration=donor, config=config)


def test_counted_transfer_never_calls_model_tensor_or_optimizer_owners(counted_head_codec, counted_head_spec, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import legal_compact_content_head_v1 as head
    donor = _counted_transfer_donor_fixture(counted_head_spec)
    def forbidden(*args, **kwargs): pytest.fail('numerical execution is outside a declared transfer plan')
    for name in ('_torch', '_new_model', '_model', 'create_compact_content_head_v1'):
        monkeypatch.setattr(head, name, forbidden)
    plan = _counted_transfer_build(counted_head_spec, counted_head_codec, donor)
    assert plan['model_calls'] == plan['transfer_calls'] == plan['training_calls'] == 0
    assert plan['authority']['weights_transferred'] is False


def decoder_witness_expected_identity(registry):
    """Read the original serialized declarations; never synthesize replacement IDs."""
    record, profile, target = registry["checkpoints"][0], registry["profiles"][0], registry["formats"][0]
    return {**{key: record["request"][key] for key in
        ("ir_family_id", "dimension", "dimension_role", "task_id")},
        "checkpoint_schema": record["format_contract"]["checkpoint_schema"],
        "target_format_schema_version": target["identity"]["schema_version"],
        "profile_id": profile["profile_id"], "format_id": target["format_id"],
        "original_checkpoint_pin": deepcopy(record["checkpoint_receipt"]),
        "architecture": profile["identity"]["decoder_architecture_id"]}


@pytest.fixture
def decoder_witness_original(data):
    # Reuse the existing nonnumerical original-format fixture, including its
    # serialized registry shape. The selector itself must not rebuild it.
    registry = build(data)
    return registry, decoder_witness_expected_identity(registry)


def select_decoder_witness(registry, expected, record_id=None):
    return inventory.select_ir_decoder_identity_witness_v1(registry,
        record_id=registry["checkpoints"][0]["record_id"] if record_id is None else record_id,
        expected_identity=expected)


@pytest.mark.parametrize("family", FAMILIES)
def test_decoder_identity_witness_selects_original_ids_without_asset_reads_or_rebuild(
        tmp_path, monkeypatch, family):
    registry = build(make_profile_data(tmp_path, family))
    expected, before = decoder_witness_expected_identity(registry), deepcopy(registry)
    record, profile, target = registry["checkpoints"][0], registry["profiles"][0], registry["formats"][0]
    material = {key: record[key] for key in ("profile_id", "format_id", "run_id",
        "checkpoint_receipt", "package_manifest_receipt", "corpus_receipt")}
    assert record["record_id"] == "ir-decoder-checkpoint-record/v1:" + digest(material)
    assert profile["profile_id"] == "ir-decoder-profile/v1:" + digest(profile["identity"])
    assert target["format_id"] == "ir-decoder-format/v1:" + digest(target["identity"])
    def forbidden(*args, **kwargs):
        pytest.fail("selected metadata identity witness reopened or rebuilt original assets")
    monkeypatch.setattr(inventory, "_build", forbidden)
    monkeypatch.setattr(inventory, "_endpoint_fence", forbidden)
    monkeypatch.setattr(inventory.routing, "_read_pin", forbidden)
    monkeypatch.setattr(inventory.cached, "_json", forbidden)
    monkeypatch.setattr(inventory.formats, "prepare_ir_decoder_format_runtime", forbidden)
    selected = select_decoder_witness(registry, expected)
    assert selected["schema"] == "ir-decoder-identity-witness-selection/v1"
    assert selected["record_id"] == record["record_id"]
    assert selected["selected_checkpoint"] == record
    assert selected["selected_profile"] == profile and selected["selected_format"] == target
    assert selected["checkpoint_schema"] == expected["checkpoint_schema"]
    assert selected["target_format_schema_version"] == expected["target_format_schema_version"]
    assert selected["checkpoint_schema"] != selected["target_format_schema_version"]
    assert selected["scope"] == "selected_registry_metadata_identity_consistency_only"
    for key in ("registry_rebuilt", "descriptor_files_authenticated", "checkpoint_payload_schema_verified"):
        assert selected[key] is False
    assert all(type(value) is bool and value is False for value in selected["authority"].values())
    selected["selected_checkpoint"]["request"]["ir_family_id"] = "foreign"
    selected["selected_profile"]["identity"]["decoder_configuration"].clear()
    assert registry == before


def test_decoder_identity_witness_preserves_original_literal_receipt_path_spellings(tmp_path, monkeypatch):
    original_directory = tmp_path / "literal[?]*-é"
    original_directory.mkdir()
    registry = build(make_profile_data(original_directory))
    expected = decoder_witness_expected_identity(registry)
    checkpoint = registry["checkpoints"][0]
    assert "literal[?]*-é" in checkpoint["checkpoint_receipt"]["path"]
    original_id, original_pin = checkpoint["record_id"], deepcopy(checkpoint["checkpoint_receipt"])
    def forbidden(*args, **kwargs):
        pytest.fail("pure witness attempted to reopen a literal original receipt path")
    monkeypatch.setattr(inventory.routing, "_read_pin", forbidden)
    selected = select_decoder_witness(registry, expected)
    assert selected["record_id"] == original_id
    assert selected["selected_checkpoint"]["checkpoint_receipt"] == original_pin
    assert selected["descriptor_files_authenticated"] is False


@pytest.mark.parametrize("field,value", [
    ("ir_family_id", "security_ir"), ("dimension", 768), ("dimension", 384.0),
    ("dimension", True), ("dimension_role", "latent"), ("task_id", "legal_text_reconstruction"),
    ("checkpoint_schema", "foreign-checkpoint/v1"),
    ("target_format_schema_version", "foreign-target/v1"),
    ("profile_id", "ir-decoder-profile/v1:" + "1" * 64),
    ("format_id", "ir-decoder-format/v1:" + "2" * 64),
    ("architecture", "foreign-decoder"),
])
def test_decoder_identity_witness_rejects_same_id_with_different_expected_labels(
        decoder_witness_original, field, value):
    registry, expected = decoder_witness_original
    expected[field] = value
    with pytest.raises(inventory.DecoderProfileInventoryError):
        select_decoder_witness(registry, expected)


@pytest.mark.parametrize("fault", ["checkpoint_as_target", "target_as_checkpoint", "pin_float", "pin_path"])
def test_decoder_identity_witness_separates_checkpoint_schema_target_schema_and_original_pin(
        decoder_witness_original, fault):
    registry, expected = decoder_witness_original
    if fault == "checkpoint_as_target":
        expected["target_format_schema_version"] = expected["checkpoint_schema"]
    elif fault == "target_as_checkpoint":
        expected["checkpoint_schema"] = expected["target_format_schema_version"]
    elif fault == "pin_float":
        expected["original_checkpoint_pin"]["bytes"] = float(expected["original_checkpoint_pin"]["bytes"])
    else:
        expected["original_checkpoint_pin"]["path"] += ".same-content-alias"
    with pytest.raises(inventory.DecoderProfileInventoryError):
        select_decoder_witness(registry, expected)


@pytest.mark.parametrize("collection", ["formats", "profiles", "checkpoints"])
def test_decoder_identity_witness_rejects_duplicate_original_selections(decoder_witness_original, collection):
    registry, expected = decoder_witness_original
    registry[collection].append(deepcopy(registry[collection][0]))
    with pytest.raises(inventory.DecoderProfileInventoryError):
        select_decoder_witness(registry, expected)


@pytest.mark.parametrize("fault", ["format_id", "profile_id", "record_id", "profile_link",
    "configuration_link", "request_link", "original_pin", "registry_binding", "replay_link",
    "contract_digest", "contract_architecture", "authority_true", "authority_integer"])
def test_decoder_identity_witness_rejects_original_id_and_crosslink_corruption(decoder_witness_original, fault):
    registry, expected = decoder_witness_original
    record, profile, target = registry["checkpoints"][0], registry["profiles"][0], registry["formats"][0]
    selected_id = record["record_id"]
    if fault == "format_id": target["format_id"] = "ir-decoder-format/v1:" + "0" * 64
    elif fault == "profile_id": profile["profile_id"] = "ir-decoder-profile/v1:" + "0" * 64
    elif fault == "record_id": record["record_id"] = "ir-decoder-checkpoint-record/v1:" + "0" * 64
    elif fault == "profile_link": profile["format_id"] = "ir-decoder-format/v1:" + "0" * 64
    elif fault == "configuration_link": record["full_checkpoint_configuration"]["hidden_size"] += 1
    elif fault == "request_link": record["request"]["checkpoint_sha256"] = "0" * 64
    elif fault == "original_pin": record["checkpoint_receipt"]["sha256"] = "0" * 64
    elif fault == "registry_binding": registry["bindings"][0]["run_id"] = "different-run"
    elif fault == "replay_link": record["replay_binding_options"]["request"]["dimension"] = 768
    elif fault == "contract_digest": record["format_contract"]["contract_sha256"] = "0" * 64
    elif fault == "contract_architecture":
        contract = record["format_contract"]
        contract["architecture"] = "foreign-decoder"
        body = {key: value for key, value in contract.items() if key not in ("contract_sha256", "contract_id")}
        contract["contract_sha256"] = digest(body)
        contract["contract_id"] = inventory.formats.CONTRACT_SCHEMA + ":" + digest(body)
    elif fault == "authority_true": registry["authority"][next(iter(registry["authority"]))] = True
    else: registry["authority"][next(iter(registry["authority"]))] = 0
    with pytest.raises(inventory.DecoderProfileInventoryError):
        select_decoder_witness(registry, expected, selected_id)


@pytest.mark.parametrize("fault", ["unknown_record", "nonfinite", "too_deep", "expected_extra"])
def test_decoder_identity_witness_refuses_unbounded_or_nonplain_metadata(decoder_witness_original, fault):
    registry, expected = decoder_witness_original
    selected_id = registry["checkpoints"][0]["record_id"]
    if fault == "unknown_record": selected_id = "ir-decoder-checkpoint-record/v1:" + "f" * 64
    elif fault == "nonfinite": expected["dimension"] = float("nan")
    elif fault == "expected_extra": expected["runtime_ready"] = False
    else:
        nested = None
        for _ in range(35): nested = [nested]
        expected["dimension"] = nested
    with pytest.raises(inventory.DecoderProfileInventoryError):
        select_decoder_witness(registry, expected, selected_id)
