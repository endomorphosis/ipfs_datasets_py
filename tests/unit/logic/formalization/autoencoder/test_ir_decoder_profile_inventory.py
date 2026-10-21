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
