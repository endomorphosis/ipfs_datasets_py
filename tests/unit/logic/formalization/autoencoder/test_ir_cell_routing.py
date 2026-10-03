"""Read-only routing contracts over miniature, private inventory artifacts.

The synthetic bytes test reference authentication, never model quality. No
checkpoint is deserialized, model loaded, cache recomputed, or database opened.
"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import ir_cell_routing as routing


FAMILIES = ("codebase_ir", "security_ir", "legal_ir", "intent_ir")
DIMENSIONS = (8, 384, 768)
CELLS = tuple((family, width) for family in FAMILIES for width in DIMENSIONS)
TASKS = (
    "source_to_native_ir", "structural_reconstruction", "native_ir_to_logic",
    "native_ir_to_source", "retained_source_byte_restoration",
)


def pin(path):
    raw = Path(path).read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, sort_keys=True, allow_nan=False).encode())
    return pin(path)


def artifact(root, name):
    path = root / "artifacts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    # Deliberately neither a tensor nor a runnable checkpoint.
    path.write_bytes(("synthetic reference only: " + name).encode())
    return pin(path)


def make_inventory(tmp_path):
    root = tmp_path / "metadata"
    documents, pins, entries = {}, {}, []
    for family, width in CELLS:
        key = (family, width)
        name = f"{family}_{width}d"
        role = "latent" if width == 8 and family != "legal_ir" else "input_embedding"
        profile = {
            "dimension": width,
            "encoder_kind": "historical producer" if width == 8 else "source embedding",
            "hard_encoder_token_limit": {8: None, 384: 512, 768: 8192}[width],
            "qualified_source_token_limit": None,
            "dimension_role_required": True,
            "unknown_limit_policy": "Retain unknown producer and qualification provenance.",
        }
        if width != 8:
            profile.update(model_id="thenlper/gte-small" if width == 384 else "Alibaba-NLP/gte-multilingual-base",
                           model_revision="1" * 40, pooling="mean" if width == 384 else "cls", normalization="l2")
        evidence = []
        if width != 768 or family == "legal_ir":
            row = {
                "role": "inherited initialization" if width == 768 else "historical donor",
                "receipt": artifact(root, name + "-checkpoint.bin"),
                "dimension_role": role,
                "input_width": {"codebase_ir": 53, "security_ir": 52, "intent_ir": 12}.get(family, 8)
                if role == "latent" else width,
                "source_access": "compiler-derived structural features" if role == "latent" else "legacy producer; qualification unknown",
                "teacher_qualified": False,
            }
            if role == "latent":
                row.update(latent_width=8, formal_decoder=False)
            if width == 384 and family == "codebase_ir":
                row.update(owning_ir_family="codebase_ir", payload_ir_family="security_ir",
                           native_codebase_decoder_complete=False)
            if width == 768:
                row.update(training_completed=False, native_source_inputs_available_in_prior_evaluation=False)
            evidence.append(row)
        cached = []
        if width == 384:
            cached = [{"role": "original cached source/target/split rows", "split": split,
                       "receipt": artifact(root, name + "-" + split + ".json"),
                       "qualified_for_new_source_inputs": False}
                      for split in ("train", "validation", "test", "canary")]
        storage = {"status": "planned_not_created", "root_template": f"<ir_store_root>/{family}/{width}d",
                   "inventory_export": f"<ir_store_root>/{family}/{width}d/inventory.json",
                   "registry_database": f"<ir_store_root>/{family}/{width}d/registry.duckdb",
                   "index_database": f"<ir_store_root>/{family}/{width}d/index.duckdb",
                   "ducklake_catalog_database": f"<ir_store_root>/{family}/{width}d/lake/catalog.duckdb",
                   "ducklake_data_prefix": f"<ir_store_root>/{family}/{width}d/lake/data/",
                   "mutable_artifact_root": f"<ir_store_root>/{family}/{width}d/artifacts/",
                   "run_namespace": f"<ir_store_root>/{family}/{width}d/runs/<task>/<profile>/<run_id>/"}
        repository = f"fixture/{family.replace('_', '-')}-autoencoder-{width}d"
        template = f"<hf_namespace>/{family.replace('_', '-')}-autoencoder-{width}d"
        document = {
            "schema": "ir-family-dimension-inventory-plan/v1",
            "status": "declarative_plan_not_runtime_inventory",
            "cell_id": name, "ir_family_id": family, "dimension": width,
            "store_id_proposed": f"ir-cell:{family}:{width}d",
            "storage": storage,
            "huggingface": {"status": "proposed_not_created", "repository_id_template": template,
                            "suggested_repository_id": repository, "namespace_write_access_verified": False,
                            "existing_descriptor_source": None},
            "dimension_profile": profile,
            "task_profiles_to_inventory": list(TASKS),
            "existing_checkpoint_evidence": evidence,
            "existing_cached_vector_rows": cached,
            "checkpoint_discovery_complete": False,
            "canonical_ir_identity_depends_on_model_dimension": False,
            "runtime_databases_created": False, "remote_repository_created": False,
            "model_or_embeddings_modified": False,
            "source_only_raw_text_decoder_admission": "not asserted",
        }
        relative = f"inventories/{family}/{width}d.json"
        documents[key] = document
        pins[key] = write_json(root / relative, document)
        entries.append({"cell_id": name, "ir_family_id": family, "dimension": width,
                        "inventory_manifest": relative, "storage": deepcopy(storage),
                        "huggingface_repository_template": template,
                        "suggested_huggingface_repository": repository})
    directory = {"schema": "ir-family-dimension-inventory-directory-plan/v1", "status": "declarative_plan",
                 "ir_family_ids": list(FAMILIES), "dimensions": list(DIMENSIONS), "cell_count": 12,
                 "cells": entries, "physical_runtime_stores_created": False, "remote_repositories_created": False}
    directory_pin = write_json(root / "ir_family_dimension_inventory_plan.json", directory)
    return {"root": root, "directory": directory, "directory_pin": directory_pin,
            "documents": documents, "pins": pins}


@pytest.fixture
def inventory(tmp_path):
    return make_inventory(tmp_path)


def request(family="legal_ir", width=384, *, role="input_embedding", task="source_to_native_ir", checkpoint=None):
    return {"ir_family_id": family, "dimension": width, "dimension_role": role,
            "task_id": task, "checkpoint_sha256": checkpoint}


def resolve(inventory, query=None, **kwargs):
    return routing.resolve_ir_cell_route(inventory["directory_pin"], list(inventory["pins"].values()),
                                         request() if query is None else query, **kwargs)


def rewrite_cell(inventory, family="legal_ir", width=384):
    key = (family, width)
    inventory["pins"][key] = write_json(Path(inventory["pins"][key]["path"]), inventory["documents"][key])


def rewrite_directory(inventory):
    inventory["directory_pin"] = write_json(Path(inventory["directory_pin"]["path"]), inventory["directory"])


def checkpoint_sha(inventory, family="legal_ir", width=384):
    return inventory["documents"][(family, width)]["existing_checkpoint_evidence"][0]["receipt"]["sha256"]


@pytest.mark.parametrize("family,width", CELLS)
def test_all_twelve_cells_route_without_implicit_checkpoint_selection(inventory, family, width):
    result = resolve(inventory, request(family, width))
    assert result["schema"] == "ir-cell-route-resolution/v1"
    assert result["cell_id"] == f"{family}_{width}d"
    assert result["selected_checkpoint"] is None
    assert result["availability"]["checkpoint_bytes"] == "unselected"
    assert result["declared_compatibility"]["dimension_role_match"] is None
    assert result["cell_declaration"]["store_id_proposed"] == f"ir-cell:{family}:{width}d"


@pytest.mark.parametrize("field,value", [
    ("ir_family_id", "LegalIR"), ("ir_family_id", "foreign_ir"),
    ("dimension", 786), ("dimension", True), ("dimension", 384.0),
    ("dimension_role", "decoder_hidden"), ("dimension_role", "projection"),
    ("task_id", "legal_text_roundtrip"), ("checkpoint_sha256", "A" * 64),
    ("checkpoint_sha256", "a" * 63),
])
def test_request_rejects_ambiguous_or_unsupported_identity(inventory, field, value):
    query = request()
    query[field] = value
    with pytest.raises(routing.RoutingError):
        resolve(inventory, query)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_request_is_closed(inventory, mutation):
    query = request()
    if mutation == "missing":
        query.pop("dimension_role")
    else:
        query["fallback_dimension"] = 8
    with pytest.raises(routing.RoutingError):
        resolve(inventory, query)


@pytest.mark.parametrize("family,width", CELLS)
def test_digest_from_another_cell_never_creates_cross_cell_fallback(inventory, family, width):
    other = "legal_ir" if family != "legal_ir" else "security_ir"
    query = request(family, width, checkpoint=checkpoint_sha(inventory, other, 384))
    with pytest.raises(routing.RoutingError):
        resolve(inventory, query)


@pytest.mark.parametrize("role", ["latent", "input_embedding"])
def test_explicit_checkpoint_must_match_dimension_role(inventory, role):
    family = "legal_ir" if role == "latent" else "codebase_ir"
    width = 384 if role == "latent" else 8
    with pytest.raises(routing.RoutingError):
        resolve(inventory, request(family, width, role=role, checkpoint=checkpoint_sha(inventory, family, width)))


@pytest.mark.parametrize("field,value", [("input_width", 8), ("latent_width", 384)])
def test_checkpoint_width_validation_uses_declared_dimension_role(inventory, field, value):
    family, width = ("codebase_ir", 8) if field == "latent_width" else ("legal_ir", 384)
    row = inventory["documents"][(family, width)]["existing_checkpoint_evidence"][0]
    if field == "latent_width":
        query = request(family, width, role="latent", checkpoint=row["receipt"]["sha256"])
    else:
        query = request(checkpoint=row["receipt"]["sha256"])
    row[field] = value
    rewrite_cell(inventory, family, width)
    with pytest.raises(routing.RoutingError):
        resolve(inventory, query)


@pytest.mark.parametrize("field", ["dimension", "ir_family_id", "cell_id", "store_id_proposed"])
def test_inventory_identity_must_match_its_directory_binding(inventory, field):
    document = inventory["documents"][("legal_ir", 384)]
    document[field] = 768 if field == "dimension" else "foreign"
    rewrite_cell(inventory)
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("field", ["root_template", "huggingface_repository_template", "suggested_huggingface_repository"])
def test_directory_cannot_alias_another_cells_storage_or_hub(inventory, field):
    entry = next(row for row in inventory["directory"]["cells"] if row["cell_id"] == "legal_ir_384d")
    if field == "root_template":
        entry["storage"][field] = "<ir_store_root>/security_ir/384d"
    else:
        entry[field] = "fixture/security-ir-autoencoder-384d"
    rewrite_directory(inventory)
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "duplicate_cell", "duplicate_path"])
def test_directory_requires_exactly_twelve_unique_inventory_pins(inventory, mutation):
    supplied = list(inventory["pins"].values())
    if mutation == "missing":
        supplied.pop()
    elif mutation == "duplicate":
        supplied[-1] = supplied[0]
    elif mutation == "duplicate_cell":
        inventory["directory"]["cells"][-1] = deepcopy(inventory["directory"]["cells"][0])
        rewrite_directory(inventory)
    else:
        inventory["directory"]["cells"][-1]["inventory_manifest"] = inventory["directory"]["cells"][0]["inventory_manifest"]
        rewrite_directory(inventory)
    with pytest.raises(routing.RoutingError):
        routing.resolve_ir_cell_route(inventory["directory_pin"], supplied, request())


@pytest.mark.parametrize("target", ["directory", "selected", "unselected"])
def test_every_manifest_pin_is_authenticated_before_route_success(inventory, target):
    reference = inventory["directory_pin"] if target == "directory" else inventory["pins"][("legal_ir", 384) if target == "selected" else ("intent_ir", 768)]
    Path(reference["path"]).write_bytes(b"{}")
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("target", ["directory", "cell"])
def test_manifest_json_rejects_duplicate_keys_even_with_an_authentic_pin(inventory, target):
    reference = inventory["directory_pin"] if target == "directory" else inventory["pins"][("legal_ir", 384)]
    path = Path(reference["path"])
    raw = path.read_bytes()
    path.write_bytes(b'{"schema":"forged",' + raw[1:])
    if target == "directory":
        inventory["directory_pin"] = pin(path)
    else:
        inventory["pins"][("legal_ir", 384)] = pin(path)
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("target", ["directory", "cell"])
def test_manifest_size_limit_applies_before_parsing(inventory, target):
    reference = inventory["directory_pin"] if target == "directory" else inventory["pins"][("legal_ir", 384)]
    path = Path(reference["path"])
    path.write_bytes(b" " * (1024 * 1024 + 1))
    if target == "directory":
        inventory["directory_pin"] = pin(path)
    else:
        inventory["pins"][("legal_ir", 384)] = pin(path)
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("target", ["directory", "cell"])
def test_missing_manifest_fails_closed(inventory, target):
    doc = inventory["documents"][("legal_ir", 384)]
    reference = {"directory": inventory["directory_pin"], "cell": inventory["pins"][("legal_ir", 384)],
                 "checkpoint": doc["existing_checkpoint_evidence"][0]["receipt"],
                 "cache": doc["existing_cached_vector_rows"][0]["receipt"]}[target]
    Path(reference["path"]).unlink()
    query = request(checkpoint=checkpoint_sha(inventory))
    with pytest.raises(routing.RoutingError):
        resolve(inventory, query)


@pytest.mark.parametrize("target", ["checkpoint", "cache"])
def test_absent_historical_artifact_remains_unavailable_with_its_original_pin(inventory, target):
    doc = inventory["documents"][("legal_ir", 384)]
    original = deepcopy(doc["existing_checkpoint_evidence"][0]["receipt"] if target == "checkpoint" else doc["existing_cached_vector_rows"][0]["receipt"])
    Path(original["path"]).unlink()
    result = resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))
    check = result["reference_checks"]["checkpoint"] if target == "checkpoint" else result["reference_checks"]["cached_vectors"][0]
    assert check == {"receipt": original, "status": "unavailable", "reason": "missing"}
    field = "checkpoint_bytes" if target == "checkpoint" else "cached_vector_files"
    assert result["availability"][field] == "unavailable"
    auth = "selected_checkpoint_bytes_verified" if target == "checkpoint" else "cached_vector_file_pins_verified"
    assert result["metadata_authenticity"][auth] is False
    assert result["selected_checkpoint"]["receipt"] == doc["existing_checkpoint_evidence"][0]["receipt"]


@pytest.mark.parametrize("target", ["directory", "cell", "checkpoint", "cache"])
def test_directory_in_place_of_regular_file_never_becomes_authenticated(inventory, target):
    doc = inventory["documents"][("legal_ir", 384)]
    reference = {"directory": inventory["directory_pin"], "cell": inventory["pins"][("legal_ir", 384)],
                 "checkpoint": doc["existing_checkpoint_evidence"][0]["receipt"],
                 "cache": doc["existing_cached_vector_rows"][0]["receipt"]}[target]
    path = Path(reference["path"])
    path.unlink()
    path.mkdir()
    with pytest.raises(routing.RoutingError):
        resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))


@pytest.mark.parametrize("target", ["checkpoint", "cache"])
def test_artifact_hash_authentication_rejects_changed_bytes(inventory, target):
    doc = inventory["documents"][("legal_ir", 384)]
    reference = doc["existing_checkpoint_evidence"][0]["receipt"] if target == "checkpoint" else doc["existing_cached_vector_rows"][0]["receipt"]
    Path(reference["path"]).write_bytes(b"changed synthetic artifact")
    with pytest.raises(routing.RoutingError):
        resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))


def test_artifact_size_limit_does_not_require_reading_a_large_model(inventory):
    with pytest.raises(routing.RoutingError):
        resolve(inventory, request(checkpoint=checkpoint_sha(inventory)), max_reference_bytes=16)


def test_duplicate_matching_checkpoint_is_ambiguous_even_when_bytes_match(inventory):
    evidence = inventory["documents"][("legal_ir", 384)]["existing_checkpoint_evidence"]
    evidence.append(deepcopy(evidence[0]))
    rewrite_cell(inventory)
    with pytest.raises(routing.RoutingError):
        resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))


def test_routing_does_not_mutate_caller_owned_inputs(inventory):
    query = request(checkpoint=checkpoint_sha(inventory))
    references = list(inventory["pins"].values())
    before = deepcopy((inventory["directory_pin"], references, query))
    routing.resolve_ir_cell_route(inventory["directory_pin"], references, query)
    assert (inventory["directory_pin"], references, query) == before


def test_explicit_selection_authenticates_saved_checkpoint_and_all_split_cache_files(inventory):
    doc = inventory["documents"][("legal_ir", 384)]
    before = {row["receipt"]["path"]: Path(row["receipt"]["path"]).read_bytes()
              for row in [*doc["existing_checkpoint_evidence"], *doc["existing_cached_vector_rows"]]}
    result = resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))
    assert result["selected_checkpoint"] == doc["existing_checkpoint_evidence"][0]
    assert result["cached_vector_records"] == doc["existing_cached_vector_rows"]
    assert {row["split"] for row in result["cached_vector_records"]} == {"train", "validation", "test", "canary"}
    assert result["metadata_authenticity"]["selected_checkpoint_bytes_verified"] is True
    assert result["metadata_authenticity"]["cached_vector_file_pins_verified"] is True
    assert all(row["status"] == "verified" for row in result["reference_checks"]["cached_vectors"])
    assert result["declared_compatibility"]["checkpoint_task_binding"] == "unknown"
    assert result["declared_compatibility"]["actual_geometry_verified"] is False
    assert {name: Path(name).read_bytes() for name in before} == before


def test_mutating_returned_records_does_not_relabel_the_saved_inventory(inventory):
    result = resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))
    declaration = deepcopy(inventory["documents"][("legal_ir", 384)])
    result["selected_checkpoint"]["source_access"] = "forged source qualification"
    result["cached_vector_records"][0]["qualified_for_new_source_inputs"] = True
    assert inventory["documents"][("legal_ir", 384)] == declaration
    second = resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))
    assert second["selected_checkpoint"]["source_access"] != "forged source qualification"
    assert second["cached_vector_records"][0]["qualified_for_new_source_inputs"] is False


def test_structural_input_width_53_and_latent_width_8_are_distinct_contracts(inventory):
    result = resolve(inventory, request("codebase_ir", 8, role="latent", task="structural_reconstruction",
                                        checkpoint=checkpoint_sha(inventory, "codebase_ir", 8)))
    assert result["selected_checkpoint"]["input_width"] == 53
    assert result["selected_checkpoint"]["latent_width"] == 8
    assert result["declared_compatibility"]["input_width"] == 53
    assert result["declared_compatibility"]["latent_width"] == 8
    assert result["declared_compatibility"]["dimension_role_match"] is True
    assert result["selected_checkpoint"]["formal_decoder"] is False
    assert result["provenance"]["encoder_tokenizer"] == "unknown"


def test_codebase_owned_security_payload_is_preserved_without_native_relabeling(inventory):
    result = resolve(inventory, request("codebase_ir", 384, checkpoint=checkpoint_sha(inventory, "codebase_ir", 384)))
    assert result["cell_id"] == "codebase_ir_384d"
    assert result["selected_checkpoint"]["owning_ir_family"] == "codebase_ir"
    assert result["selected_checkpoint"]["payload_ir_family"] == "security_ir"
    assert result["selected_checkpoint"]["native_codebase_decoder_complete"] is False
    assert result["declared_compatibility"]["payload_ir_family"] == "security_ir"
    assert result["declared_compatibility"]["checkpoint_task_binding"] == "unknown"


@pytest.mark.parametrize("width,ceiling", [(8, None), (384, 512), (768, 8192)])
def test_declared_encoder_ceiling_does_not_promote_a_qualified_span_budget(inventory, width, ceiling):
    result = resolve(inventory, request("legal_ir", width))
    assert result["budget_status"] == {"hard_encoder_token_limit": ceiling,
                                        "qualified_source_token_limit": None,
                                        "source_token_budget_qualified": False}
    assert result["provenance"]["embedding_producer_execution_authenticated"] is False
    assert result["provenance"]["encoder_tokenizer"] == ("unknown" if width == 8 else "declared_profile_only")


def test_declared_budget_value_is_retained_as_an_unqualified_declaration(inventory):
    inventory["documents"][("legal_ir", 384)]["dimension_profile"]["qualified_source_token_limit"] = 128
    rewrite_cell(inventory)
    result = resolve(inventory)
    assert result["budget_status"]["qualified_source_token_limit"] == 128
    assert result["budget_status"]["source_token_budget_qualified"] is False


@pytest.mark.parametrize("family", FAMILIES)
def test_native_768_source_inputs_and_runtime_remain_unavailable(inventory, family):
    digest = checkpoint_sha(inventory, family, 768) if family == "legal_ir" else None
    result = resolve(inventory, request(family, 768, checkpoint=digest))
    assert result["availability"]["native_768_source_records"] == "unavailable"
    assert result["availability"]["runtime"] == "not_established"
    assert result["availability"]["store"] == "planned_not_created"
    assert result["provenance"]["native_source_records_verified"] is False
    if family == "legal_ir":
        assert result["metadata_authenticity"]["selected_checkpoint_bytes_verified"] is True
        assert result["selected_checkpoint"]["training_completed"] is False
        assert result["selected_checkpoint"]["teacher_qualified"] is False
    else:
        assert result["cell_declaration"]["existing_checkpoint_evidence"] == []
        assert result["selected_checkpoint"] is None


def test_authentic_checkpoint_task_declaration_is_not_execution_or_model_quality(inventory):
    doc = inventory["documents"][("legal_ir", 384)]
    doc["existing_checkpoint_evidence"][0]["task_id"] = "native_ir_to_source"
    rewrite_cell(inventory)
    query = request(task="native_ir_to_source", checkpoint=checkpoint_sha(inventory))
    result = resolve(inventory, query)
    assert result["declared_compatibility"]["checkpoint_task_binding"] == "declared_match"
    assert result["metadata_authenticity"]["selected_checkpoint_bytes_verified"] is True
    assert result["authority"] == {
        "model_inference_executed": False, "training_executed": False, "proof_authority": False,
        "runtime_admitted": False, "model_task_qualified": False, "quality_qualified": False,
        "store_available": False, "huggingface_available": False,
    }


def test_explicit_checkpoint_task_mismatch_is_rejected(inventory):
    inventory["documents"][("legal_ir", 384)]["existing_checkpoint_evidence"][0]["task_id"] = "structural_reconstruction"
    rewrite_cell(inventory)
    with pytest.raises(routing.RoutingError):
        resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))


def test_declared_huggingface_snapshot_alias_is_authenticated_without_rewriting_it(inventory):
    doc = inventory["documents"][("legal_ir", 384)]
    original = Path(doc["existing_checkpoint_evidence"][0]["receipt"]["path"])
    raw = original.read_bytes()
    hf = inventory["root"] / "private-hf" / "models--fixture--donor"
    blob = hf / "blobs" / hashlib.sha256(raw).hexdigest()
    blob.parent.mkdir(parents=True)
    blob.write_bytes(raw)
    alias = hf / "snapshots" / ("a" * 40) / "checkpoint.json"
    alias.parent.mkdir(parents=True)
    alias.symlink_to("../../blobs/" + blob.name)
    doc["existing_checkpoint_evidence"][0]["receipt"] = pin(alias)
    rewrite_cell(inventory)
    result = resolve(inventory, request(checkpoint=hashlib.sha256(raw).hexdigest()))
    assert result["selected_checkpoint"]["receipt"]["path"] == str(alias)
    assert result["reference_checks"]["checkpoint"]["status"] == "verified"
    assert alias.is_symlink()
    assert os.readlink(alias) == "../../blobs/" + blob.name
    assert blob.read_bytes() == raw


@pytest.mark.parametrize("target", ["checkpoint", "cache"])
def test_fifo_artifact_is_rejected_without_blocking_or_reading(inventory, target):
    doc = inventory["documents"][("legal_ir", 384)]
    reference = doc["existing_checkpoint_evidence"][0]["receipt"] if target == "checkpoint" else doc["existing_cached_vector_rows"][0]["receipt"]
    path = Path(reference["path"])
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(routing.RoutingError):
        resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))


@pytest.mark.parametrize("target", ["directory", "cell", "checkpoint", "cache"])
def test_reference_replacement_between_witness_and_open_is_rejected(inventory, monkeypatch, target):
    doc = inventory["documents"][("legal_ir", 384)]
    reference = {"directory": inventory["directory_pin"], "cell": inventory["pins"][("legal_ir", 384)],
                 "checkpoint": doc["existing_checkpoint_evidence"][0]["receipt"],
                 "cache": doc["existing_cached_vector_rows"][0]["receipt"]}[target]
    victim = Path(reference["path"])
    replacement = victim.with_name(victim.name + ".replacement")
    replacement.write_bytes(victim.read_bytes())
    original_open = routing.os.open
    swapped = []

    def open_after_replacement(path, flags, *args, **kwargs):
        if os.fspath(path) == str(victim) and not swapped:
            os.replace(replacement, victim)
            swapped.append(True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(routing.os, "open", open_after_replacement)
    with pytest.raises(routing.RoutingError):
        resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))
    assert swapped == [True]


@pytest.mark.parametrize("target", ["directory", "checkpoint", "cache"])
def test_read_time_file_mutation_is_rejected(inventory, monkeypatch, target):
    doc = inventory["documents"][("legal_ir", 384)]
    reference = {"directory": inventory["directory_pin"],
                 "checkpoint": doc["existing_checkpoint_evidence"][0]["receipt"],
                 "cache": doc["existing_cached_vector_rows"][0]["receipt"]}[target]
    victim = Path(reference["path"])
    identity = victim.stat()
    original_read = routing.os.read
    changed = []

    def read_then_mutate(fd, size):
        block = original_read(fd, size)
        info = os.fstat(fd)
        if block and (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino) and not changed:
            with victim.open("ab") as stream:
                stream.write(b"changed after actual descriptor read")
            changed.append(True)
        return block

    monkeypatch.setattr(routing.os, "read", read_then_mutate)
    with pytest.raises(routing.RoutingError):
        resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))
    assert changed == [True]


def test_same_byte_huggingface_alias_retarget_during_read_is_not_stable_authentication(inventory, monkeypatch):
    doc = inventory["documents"][("legal_ir", 384)]
    original = Path(doc["existing_checkpoint_evidence"][0]["receipt"]["path"])
    raw = original.read_bytes()
    first, second = original.with_name("first-blob"), original.with_name("second-blob")
    first.write_bytes(raw)
    second.write_bytes(raw)
    alias = original.with_name("checkpoint-alias")
    alias.symlink_to(first.name)
    doc["existing_checkpoint_evidence"][0]["receipt"] = pin(alias)
    rewrite_cell(inventory)
    info = first.stat()
    original_read = routing.os.read
    changed = []

    def retarget_after_read(fd, size):
        block = original_read(fd, size)
        opened = os.fstat(fd)
        if block and (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino) and not changed:
            alias.unlink()
            alias.symlink_to(second.name)
            changed.append(True)
        return block

    monkeypatch.setattr(routing.os, "read", retarget_after_read)
    with pytest.raises(routing.RoutingError):
        resolve(inventory, request(checkpoint=hashlib.sha256(raw).hexdigest()))
    assert changed == [True]
    assert first.read_bytes() == second.read_bytes() == raw


def test_explicit_frozen_inventory_copy_retains_its_actual_origin_and_inner_artifact_paths(inventory):
    existing = inventory["pins"][("legal_ir", 384)]
    relocated = inventory["root"] / "undeclared-copy.json"
    relocated.write_bytes(Path(existing["path"]).read_bytes())
    inventory["pins"][("legal_ir", 384)] = pin(relocated)
    result = resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))
    assert result["inventory_receipt"] == pin(relocated)
    assert result["directory_receipt"] == inventory["directory_pin"]
    assert result["cell_id"] == "legal_ir_384d"
    assert result["selected_checkpoint"]["receipt"] == inventory["documents"][("legal_ir", 384)]["existing_checkpoint_evidence"][0]["receipt"]
    assert result["selected_checkpoint"]["receipt"]["path"].startswith(str(inventory["root"] / "artifacts"))
    assert Path(existing["path"]).read_bytes() == relocated.read_bytes()


@pytest.mark.parametrize("field,value", [
    ("schema", "runtime-directory/v1"), ("status", "qualified"),
    ("ir_family_ids", ["codebase_ir", "security_ir", "legal_ir", "legal_ir"]),
    ("ir_family_ids", ["codebase_ir", "security_ir", "legal_ir", ["intent_ir"]]),
    ("dimensions", [8, 384, 786]), ("cell_count", True),
    ("physical_runtime_stores_created", True), ("remote_repositories_created", True),
])
def test_authenticated_directory_declaration_cannot_change_the_routing_contract(inventory, field, value):
    inventory["directory"][field] = value
    rewrite_directory(inventory)
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("field,value", [
    ("schema", "runtime-inventory/v1"), ("status", "qualified"),
    ("runtime_databases_created", True), ("remote_repository_created", True),
    ("model_or_embeddings_modified", True),
    ("task_profiles_to_inventory", ["source_to_native_ir", "source_to_native_ir"]),
    ("task_profiles_to_inventory", ["native_ir_to_source"]),
])
def test_authenticated_cell_declaration_cannot_grant_runtime_or_undeclared_task_access(inventory, field, value):
    inventory["documents"][("legal_ir", 384)][field] = value
    rewrite_cell(inventory)
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("field,value", [("hard_encoder_token_limit", True),
                                         ("qualified_source_token_limit", 513),
                                         ("qualified_source_token_limit", "128")])
def test_token_budget_requires_exact_numbers_within_its_declared_ceiling(inventory, field, value):
    inventory["documents"][("legal_ir", 384)]["dimension_profile"][field] = value
    rewrite_cell(inventory)
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("kind", ["nonfinite", "nonobject", "invalid_utf8"])
def test_authenticated_manifest_rejects_non_json_metadata(inventory, kind):
    raw = {"nonfinite": b'{"number":NaN}', "nonobject": b'[]', "invalid_utf8": b'\xff'}[kind]
    path = Path(inventory["pins"][("legal_ir", 384)]["path"])
    path.write_bytes(raw)
    inventory["pins"][("legal_ir", 384)] = pin(path)
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("field,value", [("bytes", True), ("bytes", 0), ("sha256", "A" * 64),
                                         ("path", "relative-inventory.json")])
def test_manifest_pin_contract_is_closed_and_exact(inventory, field, value):
    inventory["directory_pin"][field] = value
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


def test_pin_does_not_accept_unreviewed_fallback_location(inventory):
    inventory["directory_pin"]["fallback_path"] = inventory["directory_pin"]["path"]
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("field,value", [("domain_id", "security_ir"), ("owning_ir_family", "security_ir")])
def test_foreign_checkpoint_declaration_cannot_be_relabelled_into_selected_family(inventory, field, value):
    inventory["documents"][("legal_ir", 384)]["existing_checkpoint_evidence"][0][field] = value
    rewrite_cell(inventory)
    with pytest.raises(routing.RoutingError):
        resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))


@pytest.mark.parametrize("field,value", [("ir_family_id", "security_ir"), ("dimension", 768)])
def test_foreign_cached_rows_cannot_be_relabelled_into_selected_cell(inventory, field, value):
    inventory["documents"][("legal_ir", 384)]["existing_cached_vector_rows"][0][field] = value
    rewrite_cell(inventory)
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("condition", ["present", "missing", "tampered"])
def test_descriptor_source_is_a_separate_authenticated_reference(inventory, condition):
    source = artifact(inventory["root"], "descriptor-source.py")
    inventory["documents"][("legal_ir", 384)]["huggingface"]["existing_descriptor_source"] = source
    rewrite_cell(inventory)
    if condition == "missing":
        Path(source["path"]).unlink()
    elif condition == "tampered":
        Path(source["path"]).write_bytes(b"changed descriptor bytes")
        with pytest.raises(routing.RoutingError):
            resolve(inventory)
        return
    result = resolve(inventory)
    assert result["reference_checks"]["descriptor_source"]["receipt"] == source
    assert result["metadata_authenticity"]["descriptor_source_pin_verified"] is (condition == "present")
    assert result["authority"]["huggingface_available"] is False


@pytest.mark.parametrize("field", ["root_template", "registry_database", "index_database",
                                   "mutable_artifact_root", "ducklake_catalog_database", "ducklake_data_prefix"])
def test_matching_declarations_cannot_share_another_cells_storage(inventory, field):
    source = inventory["documents"][("security_ir", 384)]["storage"][field]
    inventory["documents"][("legal_ir", 384)]["storage"][field] = source
    row = next(row for row in inventory["directory"]["cells"] if row["cell_id"] == "legal_ir_384d")
    row["storage"][field] = source
    rewrite_cell(inventory)
    rewrite_directory(inventory)
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


@pytest.mark.parametrize("field", ["repository_id_template", "suggested_repository_id"])
def test_matching_declarations_cannot_share_another_cells_hub_repository(inventory, field):
    source = inventory["documents"][("security_ir", 384)]["huggingface"][field]
    inventory["documents"][("legal_ir", 384)]["huggingface"][field] = source
    row = next(row for row in inventory["directory"]["cells"] if row["cell_id"] == "legal_ir_384d")
    row["huggingface_repository_template" if field == "repository_id_template" else "suggested_huggingface_repository"] = source
    rewrite_cell(inventory)
    rewrite_directory(inventory)
    with pytest.raises(routing.RoutingError):
        resolve(inventory)


def test_authenticated_quality_claims_in_old_metadata_do_not_grant_authority(inventory):
    checkpoint = inventory["documents"][("legal_ir", 384)]["existing_checkpoint_evidence"][0]
    checkpoint.update(teacher_qualified=True, source_only_qualified=True, training_completed=True,
                      heldout_exact_text_reconstruction=1.0)
    rewrite_cell(inventory)
    result = resolve(inventory, request(checkpoint=checkpoint_sha(inventory)))
    assert result["selected_checkpoint"]["teacher_qualified"] is True
    assert result["metadata_authenticity"]["selected_checkpoint_bytes_verified"] is True
    assert result["declared_compatibility"]["checkpoint_task_binding"] == "unknown"
    assert result["authority"]["quality_qualified"] is False
    assert result["authority"]["model_task_qualified"] is False
    assert result["authority"]["runtime_admitted"] is False
