"""Finite import-adapter controls using synthetic files and inert persistence.

These fixtures contain no model tensors and perform no native database or Hub
operation. Genuine driver persistence and publication remain separate evidence.
"""
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import ir_model_manager_import as adapter


def pin(path):
    raw = Path(path).read_bytes()
    return {"path": str(Path(path).absolute()), "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, allow_nan=False), encoding="utf-8")
    return pin(path)


def make_data(tmp_path, *, count=1, scheme="lfs-payload-sha256"):
    revision, repo = "1" * 40, "Example/security-ir-autoencoder-384d"
    models, published = [], []
    for index in range(count):
        cp = save(tmp_path / f"cp-{index}.json", {"synthetic": True, "variant": index})
        role = f"retained-test-decoder-{index}"
        identity = {"ir_family_id": "security_ir", "dimension": 384,
            "dimension_role": "input_embedding", "role": role,
            "schema_version": "synthetic-checkpoint/v1", "task_id": None,
            "profile_id": None, "format_id": None, "original_checkpoint_pin": cp,
            "trained": None, "initialization_only": False, "donor": None,
            "runtime_ready": False, "teacher_qualified": False, "proof_authority": False}
        model_id = adapter.ir_model_asset_record_id("security_ir", 384, "input_embedding", role, cp["sha256"])
        identity["record_id"] = model_id
        metadata = {"model_id": model_id, "model_name": f"Synthetic decoder {index}",
            "model_type": "decoder_only", "architecture": "declared-test-architecture",
            "inputs": [{"name": "embedding", "data_type": "embeddings", "shape": [384]}],
            "outputs": [{"name": "serialized_ir", "data_type": "text"}],
            "huggingface_config": {"ir_checkpoint": identity},
            "model_revision": cp["sha256"], "revision_id": cp["sha256"],
            "source_url": f"https://huggingface.co/{repo}/tree/{revision}"}
        path = f"assets/{index}/checkpoint.json"
        models.append({"model_metadata": metadata, "checkpoint_pin": cp,
            "release": {"repository_id": repo, "revision": revision,
                        "path_in_repo": path, "checkpoint_sha256": cp["sha256"]}})
        remote = {"scheme": scheme, "bytes": cp["bytes"]}
        if scheme == "lfs-payload-sha256":
            remote["sha256"] = cp["sha256"]
        else:
            raw = Path(cp["path"]).read_bytes()
            remote["blob_id"] = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        published.append({"path_in_repo": path, "file_pin": cp, "bytes": cp["bytes"],
            "sha256": cp["sha256"], "remote_identity": remote, "verified": True})
    plan = {"schema": adapter.SCHEMA, "models": models}
    receipt = {"schema": adapter.PUBLICATION_SCHEMA, "repository_id": repo,
               "revision": revision, "files_verified": True, "files": published}
    return {"plan": plan, "publication": receipt, "manifest": save(tmp_path / "plan.json", plan),
        "releases": [save(tmp_path / "publication.json", receipt)], "tmp": tmp_path}


def repin(data):
    data["manifest"] = save(data["tmp"] / "plan.json", data["plan"])
    data["releases"] = [save(data["tmp"] / "publication.json", data["publication"])]


class InertManager:
    def __init__(self):
        self.models, self.persisted = {}, {}
        self.get_calls, self.add_calls, self.readback_calls = [], [], []
        self.add_result = True
        self.persist = True
        self.after_add = None

    def get_model(self, model_id):
        self.get_calls.append(model_id)
        return deepcopy(self.models.get(model_id))

    def add_model(self, metadata):
        self.add_calls.append(deepcopy(metadata))
        self.models[metadata["model_id"]] = deepcopy(metadata)
        if self.persist:
            self.persisted[metadata["model_id"]] = deepcopy(metadata)
        if self.after_add:
            self.after_add()
        return self.add_result

    def readback(self, model_id):
        self.readback_calls.append(model_id)
        return deepcopy(self.persisted.get(model_id))


def invoke(data, manager=None, *, factory=deepcopy, readback=None, **kwargs):
    manager = manager or InertManager()
    return adapter.import_ir_model_manager_records(data["manifest"], release_receipts=data["releases"],
        manager=manager, readback=readback or manager.readback, metadata_factory=factory, **kwargs)


@pytest.mark.parametrize("scheme", ["lfs-payload-sha256", "git-blob-sha1"])
def test_pinned_original_records_require_independent_persisted_rows(tmp_path, scheme):
    data, manager = make_data(tmp_path, count=2, scheme=scheme), InertManager()
    result = invoke(data, manager)
    assert result["completed"] is True and result["registered_count"] == 2
    assert result["persisted_metadata_matched_count"] == 2
    assert len(manager.add_calls) == len(manager.readback_calls) == 2
    assert all(row["status"] == "registered_verified" for row in result["outcomes"])
    assert result["authority"]["model_numerically_loaded"] is False
    assert result["authority"]["remote_independently_verified_by_adapter"] is False


def test_unknown_format_profile_and_training_status_stay_unknown(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    invoke(data, manager)
    identity = manager.add_calls[0]["huggingface_config"]["ir_checkpoint"]
    assert all(identity[key] is None for key in ("task_id", "profile_id", "format_id", "trained", "donor"))


def test_known_format_record_id_is_retained_exactly(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    metadata = data["plan"]["models"][0]["model_metadata"]
    model_id = "ir-decoder-checkpoint-record/v1:" + "2" * 64
    metadata["model_id"] = model_id
    metadata["huggingface_config"]["ir_checkpoint"].update(record_id=model_id,
        profile_id="ir-decoder-profile/v1:" + "3" * 64,
        format_id="ir-decoder-format/v1:" + "4" * 64)
    repin(data)
    result = invoke(data, manager)
    assert result["outcomes"][0]["model_id"] == model_id
    assert manager.add_calls[0]["model_id"] == model_id


def test_idempotent_existing_records_preserve_activity_and_skip_add(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    existing = deepcopy(data["plan"]["models"][0]["model_metadata"])
    existing.update(inference_count=12, last_run_id="actual-existing-run", last_inference_cid="retained-cid",
                    created_at="2020-01-01T00:00:00", updated_at="2020-01-02T00:00:00")
    manager.models[existing["model_id"]] = existing
    manager.persisted[existing["model_id"]] = deepcopy(existing)
    result = invoke(data, manager)
    assert result["registered_count"] == 0 and result["already_present_count"] == 1
    assert manager.add_calls == [] and manager.persisted[existing["model_id"]]["inference_count"] == 12
    assert manager.readback_calls == [existing["model_id"]]


@pytest.mark.parametrize("field,value", [("architecture", "foreign-architecture"), ("source_url", "https://foreign.example"),
    ("model_revision", "f" * 64), ("serving_config", {"engine": "deploy"}), ("parent_model_id", "foreign-parent")])
def test_foreign_same_id_is_never_overwritten(tmp_path, field, value):
    data, manager = make_data(tmp_path), InertManager()
    existing = deepcopy(data["plan"]["models"][0]["model_metadata"])
    existing[field] = value
    manager.models[existing["model_id"]] = existing
    with pytest.raises(adapter.ModelManagerImportError, match="conflicting"):
        invoke(data, manager)
    assert manager.add_calls == []


def test_late_record_conflict_prevents_any_earlier_mutation(tmp_path):
    data, manager = make_data(tmp_path, count=2), InertManager()
    existing = deepcopy(data["plan"]["models"][1]["model_metadata"])
    existing["architecture"] = "foreign"
    manager.models[existing["model_id"]] = existing
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager)
    assert manager.add_calls == []


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_add_model_must_return_exact_boolean_success(tmp_path, value):
    data, manager = make_data(tmp_path), InertManager()
    manager.add_result = value
    with pytest.raises(adapter.ModelManagerImportError) as caught:
        invoke(data, manager)
    assert caught.value.outcomes[0]["add_model_started"] is True
    assert caught.value.outcomes[0]["add_model_returned"] is True
    assert caught.value.outcomes[0]["persisted_metadata_matched"] is False
    assert manager.readback_calls == []


def test_swallowed_persistence_failure_cannot_qualify_inmemory_success(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    manager.persist = False
    with pytest.raises(adapter.ModelManagerImportError, match="persisted") as caught:
        invoke(data, manager)
    assert manager.models and not manager.persisted
    assert caught.value.outcomes[0]["add_model_result"] is True
    assert caught.value.outcomes[0]["persisted_readback_returned"] is True
    assert caught.value.outcomes[0]["persisted_metadata_matched"] is False


def test_different_fresh_readback_is_refused(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    def foreign(model_id):
        result = manager.readback(model_id)
        result["huggingface_config"]["ir_checkpoint"]["role"] = "foreign-role"
        return result
    with pytest.raises(adapter.ModelManagerImportError, match="persisted"):
        invoke(data, manager, readback=foreign)


@pytest.mark.parametrize("exception", [ValueError("inert"), RuntimeError("inert"), OSError("inert")])
def test_ordinary_add_exceptions_retain_started_not_returned(tmp_path, exception):
    data, manager = make_data(tmp_path), InertManager()
    def failed(_):
        raise exception
    manager.add_model = failed
    with pytest.raises(adapter.ModelManagerImportError) as caught:
        invoke(data, manager)
    assert caught.value.__cause__ is exception
    assert caught.value.outcomes[0]["add_model_started"] is True
    assert caught.value.outcomes[0]["add_model_returned"] is False


@pytest.mark.parametrize("exception", [KeyboardInterrupt(), SystemExit(2)])
def test_control_baseexceptions_propagate_unchanged(tmp_path, exception):
    data, manager = make_data(tmp_path), InertManager()
    def failed(_):
        raise exception
    manager.add_model = failed
    with pytest.raises(type(exception)) as caught:
        invoke(data, manager)
    assert caught.value is exception


@pytest.mark.parametrize("mutation", ["schema", "extra", "revision", "record_id", "source_url", "serving", "ready", "teacher", "proof", "initialization"])
def test_invalid_plan_refuses_before_manager_or_factory(tmp_path, mutation):
    data, manager = make_data(tmp_path), InertManager()
    record = data["plan"]["models"][0]
    metadata, identity = record["model_metadata"], record["model_metadata"]["huggingface_config"]["ir_checkpoint"]
    if mutation == "schema": data["plan"]["schema"] = "foreign/v1"
    elif mutation == "extra": data["plan"]["fallback"] = True
    elif mutation == "revision": metadata["revision_id"] = "f" * 64
    elif mutation == "record_id": identity["record_id"] = "foreign"
    elif mutation == "source_url": metadata["source_url"] = metadata["source_url"].replace("1" * 40, "main")
    elif mutation == "serving": metadata["serving_config"] = None
    elif mutation in ("ready", "teacher", "proof"):
        identity[{"ready": "runtime_ready", "teacher": "teacher_qualified", "proof": "proof_authority"}[mutation]] = True
    elif mutation == "initialization": identity.update(initialization_only=True, trained=True)
    repin(data)
    factory_calls = []
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager, factory=lambda value: factory_calls.append(value))
    assert manager.get_calls == manager.add_calls == factory_calls == []


@pytest.mark.parametrize("mutation", ["unverified", "revision", "remote_sha", "remote_blob", "bytes", "path", "repo", "file_verified"])
def test_publication_receipt_mismatch_refuses_before_effects(tmp_path, mutation):
    data, manager = make_data(tmp_path), InertManager()
    publication, item = data["publication"], data["publication"]["files"][0]
    if mutation == "unverified": publication["files_verified"] = False
    elif mutation == "revision": publication["revision"] = "2" * 40
    elif mutation == "remote_sha": item["remote_identity"]["sha256"] = "f" * 64
    elif mutation == "remote_blob": item["remote_identity"] = {"scheme": "git-blob-sha1", "blob_id": "2" * 40, "bytes": item["bytes"]}
    elif mutation == "bytes": item["bytes"] += 1
    elif mutation == "path": item["path_in_repo"] = "../checkpoint.json"
    elif mutation == "repo": publication["repository_id"] = "Example/foreign"
    elif mutation == "file_verified": item["verified"] = False
    repin(data)
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager)
    assert manager.get_calls == manager.add_calls == []


def test_duplicate_model_ids_and_duplicate_receipt_paths_fail_closed(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    data["plan"]["models"].append(deepcopy(data["plan"]["models"][0]))
    repin(data)
    with pytest.raises(adapter.ModelManagerImportError, match="duplicate"):
        invoke(data, manager)
    data = make_data(tmp_path)
    data["releases"].append(deepcopy(data["releases"][0]))
    with pytest.raises(adapter.ModelManagerImportError, match="unique"):
        invoke(data, manager)
    assert manager.add_calls == []


def test_zero_byte_noncheckpoint_publication_file_is_authenticated(tmp_path):
    data = make_data(tmp_path)
    path = tmp_path / "empty.py"
    path.write_bytes(b"")
    empty = pin(path)
    data["publication"]["files"].append({"path_in_repo": "source/empty.py", "file_pin": empty,
        "bytes": 0, "sha256": empty["sha256"], "verified": True,
        "remote_identity": {"scheme": "git-blob-sha1", "blob_id": hashlib.sha1(b"blob 0\0").hexdigest(), "bytes": 0}})
    repin(data)
    assert invoke(data)["completed"] is True


def test_detached_caller_options_and_result_never_mutate_source(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    original = deepcopy(data)
    result = invoke(data, manager)
    result["outcomes"][0]["model_id"] = "changed-result"
    assert data == original
    assert next(iter(manager.persisted)) != "changed-result"


def test_factory_cannot_change_authenticated_declared_metadata(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    def changed(value):
        value["architecture"] = "changed-by-factory"
        return value
    with pytest.raises(adapter.ModelManagerImportError, match="factory"):
        invoke(data, manager, factory=changed)
    assert manager.add_calls == []


@pytest.mark.parametrize("foreign", [True, False])
def test_reentrant_factory_cannot_overwrite_same_id_insertion(tmp_path, foreign):
    data, manager = make_data(tmp_path), InertManager()
    def insert(value):
        existing = deepcopy(value)
        if foreign:
            existing["architecture"] = "foreign-during-factory"
        existing["inference_count"] = 19
        manager.models[value["model_id"]] = existing
        manager.persisted[value["model_id"]] = deepcopy(existing)
        return value
    if foreign:
        with pytest.raises(adapter.ModelManagerImportError, match="during factory"):
            invoke(data, manager, factory=insert)
    else:
        result = invoke(data, manager, factory=insert)
        assert result["already_present_count"] == 1 and result["registered_count"] == 0
    assert manager.add_calls == []
    assert next(iter(manager.persisted.values()))["inference_count"] == 19


def test_factory_mutating_checkpoint_refuses_before_add(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    def mutate(value):
        Path(data["plan"]["models"][0]["checkpoint_pin"]["path"]).write_text("changed")
        return value
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager, factory=mutate)
    assert manager.add_calls == []


def test_after_add_artifact_drift_retains_persisted_outcome(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    manager.after_add = lambda: Path(data["plan"]["models"][0]["checkpoint_pin"]["path"]).write_text("changed")
    with pytest.raises(adapter.ModelManagerImportError) as caught:
        invoke(data, manager)
    assert caught.value.outcomes[0]["add_model_returned"] is True
    assert caught.value.outcomes[0]["persisted_metadata_matched"] is True


def test_fifo_is_refused_before_manager_without_blocking(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    checkpoint = data["plan"]["models"][0]["checkpoint_pin"]
    path = Path(checkpoint["path"])
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager)
    assert manager.get_calls == []


def test_declared_alias_is_supported_without_hash_path_discovery(tmp_path):
    data = make_data(tmp_path)
    original = data["plan"]["models"][0]["checkpoint_pin"]
    alias = tmp_path / "exact-declared-alias.json"
    alias.symlink_to(original["path"])
    declared = {**original, "path": str(alias)}
    data["plan"]["models"][0]["checkpoint_pin"] = declared
    data["publication"]["files"][0]["file_pin"] = declared
    repin(data)
    assert invoke(data)["completed"] is True


def test_alias_retarget_at_open_is_detected_even_for_equal_bytes(tmp_path, monkeypatch):
    data, manager = make_data(tmp_path), InertManager()
    original = data["plan"]["models"][0]["checkpoint_pin"]
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(Path(original["path"]).read_bytes())
    alias = tmp_path / "exact-declared-alias.json"
    alias.symlink_to(original["path"])
    declared = {**original, "path": str(alias)}
    data["plan"]["models"][0]["checkpoint_pin"] = declared
    data["publication"]["files"][0]["file_pin"] = declared
    repin(data)
    raw_open = os.open
    retargeted = []
    def open_after_retarget(path, *args, **kwargs):
        if str(path) == str(alias) and not retargeted:
            alias.unlink()
            alias.symlink_to(replacement)
            retargeted.append(True)
        return raw_open(path, *args, **kwargs)
    monkeypatch.setattr(adapter.os, "open", open_after_retarget)
    with pytest.raises(adapter.ModelManagerImportError, match="changed"):
        invoke(data, manager)
    assert retargeted == [True] and manager.get_calls == []


def test_dataclass_enum_tuple_io_defaults_match_fresh_readback(tmp_path):
    data = make_data(tmp_path)
    class Types(Enum):
        EMBEDDINGS = "embeddings"
        TEXT = "text"
    @dataclass
    class IO:
        name: str
        data_type: Types
        shape: tuple | None = None
        dtype: str = "float32"
        description: str = ""
        optional: bool = False
    def enriched(value):
        value["inputs"] = [IO("embedding", Types.EMBEDDINGS, (384,))]
        value["outputs"] = [IO("serialized_ir", Types.TEXT)]
        value["serving_config"] = None
        return value
    class TypedManager(InertManager):
        def add_model(self, metadata):
            return super().add_model(adapter._normalize(metadata))
    manager = TypedManager()
    assert invoke(data, manager, factory=enriched)["completed"] is True


@pytest.mark.parametrize("maximum", [0, True, 512 * 1024 * 1024 + 1])
def test_invalid_bound_is_rejected(tmp_path, maximum):
    data, manager = make_data(tmp_path), InertManager()
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager, max_reference_bytes=maximum)
    assert manager.get_calls == []


def test_duplicate_json_keys_are_rejected_before_manager(tmp_path):
    data, manager = make_data(tmp_path), InertManager()
    Path(data["manifest"]["path"]).write_text('{"schema":"a","schema":"b","models":[]}')
    data["manifest"] = pin(data["manifest"]["path"])
    with pytest.raises(adapter.ModelManagerImportError, match="duplicate"):
        invoke(data, manager)
    assert manager.get_calls == []


def make_component_data(tmp_path, *, dimension_role="source_tokens", inputs=None):
    data = make_data(tmp_path)
    record = data["plan"]["models"][0]
    metadata = record["model_metadata"]
    identity = metadata["huggingface_config"]["ir_checkpoint"]
    role = "retained-source-token-head" if dimension_role == "source_tokens" else "retained-off-matrix-projection"
    identity.update(asset_binding_schema=adapter.COMPONENT_BINDING_SCHEMA,
        dimension=None, dimension_role=dimension_role, external_lane_binding=None, role=role)
    model_id = adapter.ir_model_component_record_id("security_ir", dimension_role, role,
        record["checkpoint_pin"]["sha256"])
    identity["record_id"] = metadata["model_id"] = model_id
    metadata["huggingface_config"].update(complete_runtime_io_contract=False,
        internal_model_widths={"token_embedding": 16, "hidden": 64},
        internal_widths_are_external_lane_binding=False)
    metadata["inputs"] = inputs if inputs is not None else [
        {"name": "source_text", "data_type": "text", "dtype": "utf8"}]
    repin(data)
    return data


@pytest.mark.parametrize("data_type,dtype", [("text", "utf8"), ("tokens", "int64")])
def test_source_token_components_preserve_null_geometry_and_unknown_profiles(tmp_path, data_type, dtype):
    data, manager = make_component_data(tmp_path, inputs=[
        {"name": "source", "data_type": data_type, "dtype": dtype}]), InertManager()
    result = invoke(data, manager)
    stored = manager.persisted[result["outcomes"][0]["model_id"]]
    identity = stored["huggingface_config"]["ir_checkpoint"]
    assert identity["dimension"] is identity["external_lane_binding"] is None
    assert identity["dimension_role"] == "source_tokens"
    assert identity["profile_id"] is identity["format_id"] is None
    assert stored["huggingface_config"]["internal_model_widths"] == {"token_embedding": 16, "hidden": 64}
    assert stored["inputs"][0]["data_type"] == data_type
    assert result["registered_count"] == result["persisted_metadata_matched_count"] == 1
    assert all(result["authority"][name] is False for name in (
        "runtime_ready", "teacher_qualified", "proof_authority", "model_numerically_loaded"))


@pytest.mark.parametrize("width", [4, 16, 32, 64])
def test_off_matrix_components_keep_declared_feature_width_without_lane_mapping(tmp_path, width):
    data, manager = make_component_data(tmp_path, dimension_role="unbound_component", inputs=[
        {"name": "authored_component_features", "data_type": "features", "shape": [-1, width]}]), InertManager()
    result = invoke(data, manager)
    stored = manager.add_calls[0]
    assert stored["inputs"][0]["shape"] == [-1, width]
    assert stored["huggingface_config"]["ir_checkpoint"]["dimension"] is None
    assert stored["huggingface_config"]["ir_checkpoint"]["external_lane_binding"] is None
    assert result["registered_count"] == 1


@pytest.mark.parametrize("mutation", ["dimension8", "dimension384", "dimension768", "dimension4",
    "dimension_bool", "role_latent", "role_embedding", "missing_schema", "foreign_schema",
    "missing_external", "external_lane", "profile", "format", "known_format_id",
    "legacy_asset_id", "runtime_io", "missing_runtime_io", "empty_source_inputs", "embedding_input"])
def test_detached_component_cannot_fabricate_lane_format_or_input_contract(tmp_path, mutation):
    data, manager = make_component_data(tmp_path), InertManager()
    record = data["plan"]["models"][0]
    metadata = record["model_metadata"]
    config = metadata["huggingface_config"]
    identity = config["ir_checkpoint"]
    if mutation.startswith("dimension"):
        identity["dimension"] = False if mutation == "dimension_bool" else int(mutation[9:])
    elif mutation.startswith("role_"):
        identity["dimension_role"] = "latent" if mutation == "role_latent" else "input_embedding"
    elif mutation == "missing_schema": identity.pop("asset_binding_schema")
    elif mutation == "foreign_schema": identity["asset_binding_schema"] = "foreign/v1"
    elif mutation == "missing_external": identity.pop("external_lane_binding")
    elif mutation == "external_lane": identity["external_lane_binding"] = {"ir_family_id": "security_ir", "dimension": 384}
    elif mutation == "profile": identity["profile_id"] = "ir-decoder-profile/v1:" + "3" * 64
    elif mutation == "format": identity["format_id"] = "ir-decoder-format/v1:" + "4" * 64
    elif mutation in ("known_format_id", "legacy_asset_id"):
        model_id = ("ir-decoder-checkpoint-record/v1:" + "2" * 64) if mutation == "known_format_id" else \
            adapter.ir_model_asset_record_id("security_ir", 384, "input_embedding", identity["role"], record["checkpoint_pin"]["sha256"])
        identity["record_id"] = metadata["model_id"] = model_id
    elif mutation == "runtime_io": config["complete_runtime_io_contract"] = True
    elif mutation == "missing_runtime_io": config.pop("complete_runtime_io_contract")
    elif mutation == "empty_source_inputs": metadata["inputs"] = []
    elif mutation == "embedding_input": metadata["inputs"] = [{"name": "fake_embedding", "data_type": "embeddings", "shape": [384]}]
    repin(data)
    factory_calls = []
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager, factory=lambda value: factory_calls.append(value))
    assert manager.get_calls == manager.add_calls == factory_calls == []


def test_component_identity_is_deterministic_separate_and_content_specific(tmp_path):
    data = make_component_data(tmp_path)
    record = data["plan"]["models"][0]
    identity = record["model_metadata"]["huggingface_config"]["ir_checkpoint"]
    sha, role = record["checkpoint_pin"]["sha256"], identity["role"]
    selected = adapter.ir_model_component_record_id("security_ir", "source_tokens", role, sha)
    assert selected == identity["record_id"]
    assert selected != adapter.ir_model_component_record_id("security_ir", "unbound_component", role, sha)
    assert selected != adapter.ir_model_component_record_id("legal_ir", "source_tokens", role, sha)
    assert selected != adapter.ir_model_component_record_id("security_ir", "source_tokens", role + "-other", sha)
    assert selected != adapter.ir_model_component_record_id("security_ir", "source_tokens", role, "f" * 64)
    assert selected != adapter.ir_model_asset_record_id("security_ir", 384, "input_embedding", role, sha)


@pytest.mark.parametrize("role", ["latent", "input_embedding", "unknown", None, [], True])
def test_component_id_helper_requires_an_explicit_component_role(role):
    with pytest.raises(adapter.ModelManagerImportError):
        adapter.ir_model_component_record_id("legal_ir", role, "authored-head", "1" * 64)


@pytest.mark.parametrize("width", [4, 16])
def test_existing_lane_api_does_not_accept_off_matrix_widths(width):
    with pytest.raises(adapter.ModelManagerImportError):
        adapter.ir_model_asset_record_id("security_ir", width, "latent", "authored-head", "1" * 64)


def test_component_records_mix_with_existing_lane_records_without_relabeling(tmp_path):
    data, manager = make_data(tmp_path, count=2), InertManager()
    original = deepcopy(data["plan"]["models"][0]["model_metadata"])
    record = data["plan"]["models"][1]
    metadata = record["model_metadata"]
    identity = metadata["huggingface_config"]["ir_checkpoint"]
    role = "authored-query-projection"
    identity.update(asset_binding_schema=adapter.COMPONENT_BINDING_SCHEMA, dimension=None,
        dimension_role="unbound_component", external_lane_binding=None, role=role)
    identity["record_id"] = metadata["model_id"] = adapter.ir_model_component_record_id(
        "security_ir", "unbound_component", role, record["checkpoint_pin"]["sha256"])
    metadata["inputs"] = [{"name": "query_features", "data_type": "features", "shape": [-1, 32]}]
    metadata["huggingface_config"]["complete_runtime_io_contract"] = False
    repin(data)
    result = invoke(data, manager)
    assert result["registered_count"] == 2
    assert manager.persisted[original["model_id"]] == original
    assert manager.persisted[metadata["model_id"]]["huggingface_config"]["ir_checkpoint"]["dimension"] is None


def make_source_representation_data(tmp_path, *, shape=None):
    """Synthetic expected-producer metadata; no native producer is authenticated."""
    from ipfs_datasets_py.logic.formalization.autoencoder import ir_decoder_profile_inventory as inventory
    data = make_data(tmp_path)
    producer = {"profile": "leanstral4096:cpu1:last:l2:single-sequence:tokens512:lazy-mmap:v2",
        "model_sha256": "4668fd2a6d2764de250489852230e96238eb5c0d7495866eb3b9c6c4fac5c7da",
        "worker_sha256": "a" * 64, "worker_source_sha256": "b" * 64,
        "owner_source_sha256": "c" * 64, "vocabulary_owner_source_sha256": "d" * 64,
        "library_sha256": ["e" * 64, "e" * 64, "f" * 64]}
    profile = inventory.build_ir_source_representation_profile(producer)
    profile_pin = save(tmp_path / "synthetic-source-profile.json", profile)
    record = data["plan"]["models"][0]
    metadata = record["model_metadata"]
    identity = metadata["huggingface_config"]["ir_checkpoint"]
    identity.update(asset_binding_schema=adapter.SOURCE_REPRESENTATION_BINDING_SCHEMA,
        ir_family_id="legal_ir", dimension=4096, dimension_role="input_embedding",
        role="synthetic-source-embedding-projection", source_representation_profile_id=profile["profile_id"],
        source_representation_profile_pin=profile_pin)
    metadata["inputs"] = [{"name": "source_embedding", "data_type": "embeddings",
        "shape": [4096] if shape is None else shape, "dtype": "float32"}]
    metadata["huggingface_config"]["complete_runtime_io_contract"] = False
    identity["record_id"] = metadata["model_id"] = adapter.ir_model_source_representation_record_id(
        identity["role"], record["checkpoint_pin"]["sha256"], profile["profile_id"])
    data["source_profile"] = profile
    repin(data)
    return data


@pytest.mark.parametrize("shape", [[4096], [-1, 4096]])
def test_legal4096_source_representation_preserves_pinned_profile_without_decoder_authority(tmp_path, shape):
    data, manager = make_source_representation_data(tmp_path, shape=shape), InertManager()
    result = invoke(data, manager)
    stored = manager.persisted[result["outcomes"][0]["model_id"]]
    identity = stored["huggingface_config"]["ir_checkpoint"]
    assert (identity["ir_family_id"], identity["dimension"], identity["dimension_role"]) == (
        "legal_ir", 4096, "input_embedding")
    assert identity["source_representation_profile_id"] == data["source_profile"]["profile_id"]
    assert identity["source_representation_profile_pin"] == pin(tmp_path / "synthetic-source-profile.json")
    assert identity["profile_id"] is identity["format_id"] is None
    assert stored["huggingface_config"]["complete_runtime_io_contract"] is False
    assert stored["inputs"][0] == {"name": "source_embedding", "data_type": "embeddings",
        "shape": shape, "dtype": "float32"}
    assert identity["trained"] is identity["donor"] is None
    assert result["registered_count"] == result["persisted_metadata_matched_count"] == 1
    assert all(result["authority"][key] is False for key in ("runtime_ready", "teacher_qualified",
        "proof_authority", "model_numerically_loaded", "model_quality_qualified"))
    repeated = invoke(data, manager)
    assert repeated["registered_count"] == 0 and repeated["already_present_count"] == 1
    assert len(manager.add_calls) == 1 and len(manager.readback_calls) == 2


@pytest.mark.parametrize("mutation", ["missing_profile_id", "missing_profile_pin", "foreign_profile_id",
    "profile_pin_hash", "profile_json", "duplicate_profile_json", "resealed_profile_id",
    "family", "dimension", "dimension_bool", "dimension_role", "missing_schema", "foreign_schema",
    "legacy_asset_id", "known_format_id", "decoder_profile", "decoder_format", "runtime_io",
    "missing_runtime_io", "runtime_ready", "teacher_qualified", "proof_authority", "empty_inputs",
    "feature_input", "width384", "rank3", "wrong_dtype", "missing_dtype", "boolean_width",
    "source_authflag", "external_lane"])
def test_legal4096_binding_rejects_incomplete_or_promoted_source_metadata_before_effects(tmp_path, mutation):
    data, manager = make_source_representation_data(tmp_path), InertManager()
    record = data["plan"]["models"][0]
    metadata = record["model_metadata"]
    config = metadata["huggingface_config"]
    identity = config["ir_checkpoint"]
    if mutation == "missing_profile_id": identity.pop("source_representation_profile_id")
    elif mutation == "missing_profile_pin": identity.pop("source_representation_profile_pin")
    elif mutation == "foreign_profile_id": identity["source_representation_profile_id"] = "ir-source-representation-profile/v1:" + "0" * 64
    elif mutation == "profile_pin_hash": identity["source_representation_profile_pin"]["sha256"] = "0" * 64
    elif mutation in ("profile_json", "duplicate_profile_json", "resealed_profile_id"):
        path = Path(identity["source_representation_profile_pin"]["path"])
        if mutation == "profile_json": path.write_text("not JSON", encoding="utf-8")
        elif mutation == "duplicate_profile_json": path.write_text('{"schema":"a","schema":"b"}', encoding="utf-8")
        else:
            changed = deepcopy(data["source_profile"])
            changed["profile_id"] = "ir-source-representation-profile/v1:" + "0" * 64
            save(path, changed)
        identity["source_representation_profile_pin"] = pin(path)
    elif mutation == "family": identity["ir_family_id"] = "security_ir"
    elif mutation == "dimension": identity["dimension"] = 384
    elif mutation == "dimension_bool": identity["dimension"] = True
    elif mutation == "dimension_role": identity["dimension_role"] = "latent"
    elif mutation == "missing_schema": identity.pop("asset_binding_schema")
    elif mutation == "foreign_schema": identity["asset_binding_schema"] = "ir-source-representation-asset-binding/v2"
    elif mutation in ("legacy_asset_id", "known_format_id"):
        selected = adapter.ir_model_asset_record_id("legal_ir", 384, "input_embedding", identity["role"],
            record["checkpoint_pin"]["sha256"]) if mutation == "legacy_asset_id" else "ir-decoder-checkpoint-record/v1:" + "0" * 64
        identity["record_id"] = metadata["model_id"] = selected
    elif mutation == "decoder_profile": identity["profile_id"] = "ir-decoder-profile/v1:" + "0" * 64
    elif mutation == "decoder_format": identity["format_id"] = "ir-decoder-format/v1:" + "0" * 64
    elif mutation == "runtime_io": config["complete_runtime_io_contract"] = True
    elif mutation == "missing_runtime_io": config.pop("complete_runtime_io_contract")
    elif mutation in ("runtime_ready", "teacher_qualified", "proof_authority"): identity[mutation] = True
    elif mutation == "empty_inputs": metadata["inputs"] = []
    elif mutation == "feature_input": metadata["inputs"][0]["data_type"] = "features"
    elif mutation == "width384": metadata["inputs"][0]["shape"] = [384]
    elif mutation == "rank3": metadata["inputs"][0]["shape"] = [1, 1, 4096]
    elif mutation == "wrong_dtype": metadata["inputs"][0]["dtype"] = "float64"
    elif mutation == "missing_dtype": metadata["inputs"][0].pop("dtype")
    elif mutation == "boolean_width": metadata["inputs"][0]["shape"] = [True, 4096]
    elif mutation == "source_authflag": identity["source_producer_execution_authenticated"] = True
    elif mutation == "external_lane": identity["external_lane_binding"] = {"ir_family_id": "legal_ir", "dimension": 4096}
    repin(data)
    factory_calls = []
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager, factory=lambda value: factory_calls.append(value))
    assert manager.get_calls == manager.add_calls == manager.readback_calls == factory_calls == []


@pytest.mark.parametrize("component", [False, True])
@pytest.mark.parametrize("marker", ["source_representation_profile_id", "source_representation_profile_pin",
    "unknown_source_schema", "decoder_profile", "decoder_format"])
def test_source_profile_markers_cannot_be_smuggled_into_existing_bindings(tmp_path, component, marker):
    data = make_component_data(tmp_path) if component else make_data(tmp_path)
    manager = InertManager()
    identity = data["plan"]["models"][0]["model_metadata"]["huggingface_config"]["ir_checkpoint"]
    if marker == "source_representation_profile_id": identity[marker] = "ir-source-representation-profile/v1:" + "0" * 64
    elif marker == "source_representation_profile_pin": identity[marker] = deepcopy(data["plan"]["models"][0]["checkpoint_pin"])
    elif marker == "unknown_source_schema": identity["asset_binding_schema"] = "ir-source-representation-asset-binding/v2"
    else: identity["profile_id" if marker == "decoder_profile" else "format_id"] = "ir-source-representation-profile/v1:" + "0" * 64
    repin(data)
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager)
    assert manager.get_calls == manager.add_calls == manager.readback_calls == []


def test_source_representation_id_binds_profile_checkpoint_and_role_without_extending_v1_lane_api():
    profile = "ir-source-representation-profile/v1:" + "a" * 64
    selected = adapter.ir_model_source_representation_record_id("source-projection", "b" * 64, profile)
    assert selected.startswith(adapter.SOURCE_REPRESENTATION_BINDING_SCHEMA + ":")
    assert selected == adapter.ir_model_source_representation_record_id("source-projection", "b" * 64, profile)
    assert selected != adapter.ir_model_source_representation_record_id("different-projection", "b" * 64, profile)
    assert selected != adapter.ir_model_source_representation_record_id("source-projection", "c" * 64, profile)
    assert selected != adapter.ir_model_source_representation_record_id("source-projection", "b" * 64,
        "ir-source-representation-profile/v1:" + "d" * 64)
    with pytest.raises(adapter.ModelManagerImportError):
        adapter.ir_model_asset_record_id("legal_ir", 4096, "input_embedding", "source-projection", "b" * 64)


@pytest.mark.parametrize("profile", [None, [], True, "ir-source-representation-profile/v2:" + "a" * 64,
    "ir-source-representation-profile/v1:" + "A" * 64, "ir-source-representation-profile/v1:short",
    "ir-decoder-profile/v1:" + "a" * 64])
def test_source_representation_id_requires_exact_versioned_profile_identity(profile):
    with pytest.raises(adapter.ModelManagerImportError):
        adapter.ir_model_source_representation_record_id("source-projection", "b" * 64, profile)


def test_source_profile_reference_obeys_caller_byte_cap_before_profile_read(tmp_path, monkeypatch):
    data, manager = make_source_representation_data(tmp_path), InertManager()
    identity = data["plan"]["models"][0]["model_metadata"]["huggingface_config"]["ir_checkpoint"]
    path = Path(identity["source_representation_profile_pin"]["path"])
    path.write_bytes(path.read_bytes() + b" " * 16384)
    identity["source_representation_profile_pin"] = pin(path)
    repin(data)
    maximum = max(data["manifest"]["bytes"], *(p["bytes"] for p in data["releases"])) + 1
    assert identity["source_representation_profile_pin"]["bytes"] > maximum
    reads, original_read = [], adapter._read
    def recorded_read(reference, **kwargs):
        reads.append(reference["path"])
        return original_read(reference, **kwargs)
    monkeypatch.setattr(adapter, "_read", recorded_read)
    with pytest.raises(adapter.ModelManagerImportError, match="bound"):
        invoke(data, manager, max_reference_bytes=maximum)
    assert str(path) not in reads and manager.get_calls == manager.add_calls == []


@pytest.mark.parametrize("mutation_stage", ["factory", "readback", "existing_readback"])
def test_source_profile_pin_is_fenced_through_factory_and_each_fresh_readback(tmp_path, mutation_stage):
    data, manager = make_source_representation_data(tmp_path), InertManager()
    metadata = data["plan"]["models"][0]["model_metadata"]
    profile_path = Path(metadata["huggingface_config"]["ir_checkpoint"]["source_representation_profile_pin"]["path"])
    def change_profile():
        profile_path.write_bytes(profile_path.read_bytes() + b" ")
    def factory(value):
        change_profile()
        return deepcopy(value)
    def readback(model_id):
        result = manager.readback(model_id)
        change_profile()
        return result
    if mutation_stage == "existing_readback":
        manager.models[metadata["model_id"]] = deepcopy(metadata)
        manager.persisted[metadata["model_id"]] = deepcopy(metadata)
    with pytest.raises(adapter.ModelManagerImportError) as caught:
        invoke(data, manager, factory=factory if mutation_stage == "factory" else deepcopy,
            readback=manager.readback if mutation_stage == "factory" else readback)
    outcome = caught.value.outcomes[0]
    if mutation_stage == "factory":
        assert manager.add_calls == manager.readback_calls == []
        assert outcome["add_model_started"] is False and outcome["persisted_readback_started"] is False
    else:
        assert len(manager.readback_calls) == 1 and outcome["persisted_metadata_matched"] is True
        assert len(manager.add_calls) == (0 if mutation_stage == "existing_readback" else 1)
        assert outcome["already_present"] is (mutation_stage == "existing_readback")


def test_source_binding_coexists_with_v1_lane_without_relabelling_legacy_record(tmp_path):
    data, manager = make_source_representation_data(tmp_path), InertManager()
    source_record = deepcopy(data["plan"]["models"][0])
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy = make_data(legacy_dir)
    original = deepcopy(legacy["plan"]["models"][0]["model_metadata"])
    data["plan"]["models"].insert(0, legacy["plan"]["models"][0])
    # Both synthetic publications use the same checkpoint JSON content and remote
    # asset path, so one existing verified publication covers both concrete rows.
    repin(data)
    result = invoke(data, manager)
    assert result["registered_count"] == 2
    assert manager.persisted[original["model_id"]] == original
    assert manager.persisted[source_record["model_metadata"]["model_id"]] == source_record["model_metadata"]


def make_source4096_data(tmp_path, *, scheme="lfs-payload-sha256", count=1,
                         profile="leanstral4096:cpu1:last:l2:single-sequence:tokens512:lazy-mmap:v2"):
    """Synthetic metadata, never a claim of a native forward or model state."""
    data = make_data(tmp_path, scheme=scheme, count=count)
    data["plan"]["schema"] = adapter.SCHEMA_V2
    repo = "Example/legal-ir-autoencoder-4096d"
    data["publication"]["repository_id"] = repo
    evidence = save(tmp_path / "synthetic-native-evidence.json", {"synthetic": True, "native_executed": False})
    producer = {"profile": profile,
        "model_sha256": "a" * 64, "worker_sha256": "b" * 64, "worker_source_sha256": "c" * 64,
        "owner_source_sha256": "d" * 64, "vocabulary_owner_source_sha256": "e" * 64,
        "library_sha256": {"/explicit/synthetic/library.so": "f" * 64}}
    source = {"schema": adapter.SOURCE_PROFILE_SCHEMA, "expected_producer": producer,
        "pooling": "last", "normalization": "l2", "attention": "causal", "context_tokens": 512,
        "sequences": 1, "source_text_required": True, "evidence_pins": [evidence],
        "evidence_scope": "pinned_historical_metadata_only", "ordinary_receipt_is_capability": False}
    for record in data["plan"]["models"]:
        metadata = record["model_metadata"]
        record["release"]["repository_id"] = repo
        metadata["source_url"] = f"https://huggingface.co/{repo}/tree/{record['release']['revision']}"
        identity = metadata["huggingface_config"]["ir_checkpoint"]
        identity.update(asset_binding_schema=adapter.SOURCE_BINDING_SCHEMA, ir_family_id="legal_ir",
            dimension=4096, dimension_role="source_input_representation_width",
            schema_version="bound-native4096-source-span-checkpoint/v1",
            task_id="source_text_and_representation_to_legal_ir", source_representation=deepcopy(source))
        metadata.update(architecture="utf8-byte-bidirectional-gru-native-4096-film-spans/v1",
            inputs=[{"name": "source_text", "data_type": "text", "dtype": "utf8"},
                {"name": "source_representation", "data_type": "embeddings", "shape": [4096], "dtype": "float32"}],
            outputs=[{"name": "legal_ir", "data_type": "text", "dtype": "utf8"}])
        metadata["huggingface_config"].update(complete_runtime_io_contract=False,
            native_execution_verified_by_importer=False, source_compatibility_verified=False,
            live_native_capability_restored=False)
        identity["record_id"] = metadata["model_id"] = source4096_id(record)
    repin(data)
    return data


def source4096_id(record):
    identity = record["model_metadata"]["huggingface_config"]["ir_checkpoint"]
    return adapter.ir_model_source_record_id_v2(identity["ir_family_id"], identity["dimension_role"],
        identity["role"], record["checkpoint_pin"]["sha256"], schema_version=identity["schema_version"],
        task_id=identity["task_id"], source_representation=identity["source_representation"])


def invoke_v2(data, manager=None, *, factory=deepcopy, **kwargs):
    manager = manager or InertManager()
    return adapter.import_ir_model_manager_records_v2(data["manifest"], release_receipts=data["releases"],
        manager=manager, readback=manager.readback, metadata_factory=factory, **kwargs)


@pytest.mark.parametrize("width,expected", [
    (8, "ir-model-asset-binding/v1:256a250cd544ed116d2371a1535e36c80475d00e6ce8c63db9148b40a0b85428"),
    (384, "ir-model-asset-binding/v1:117b2785390687f722329d0e4bf43d416eca8ccec48dbe29be99715c166f9555"),
    (768, "ir-model-asset-binding/v1:4f303abea13bc38616e1db6fdb21d6f210cb1f7398aa90cac5f3363a287362c2")])
def test_v1_golden_ids_remain_unchanged(width, expected):
    assert adapter.ir_model_asset_record_id("security_ir", width, "input_embedding", "baseline", "a" * 64) == expected


def test_v1_never_silently_accepts_v2_or_source4096_metadata(tmp_path):
    data, manager = make_source4096_data(tmp_path), InertManager()
    with pytest.raises(adapter.ModelManagerImportError, match="schema"):
        invoke(data, manager)
    data["plan"]["schema"] = adapter.SCHEMA
    repin(data)
    with pytest.raises(adapter.ModelManagerImportError, match="v2 importer"):
        invoke(data, manager)
    with pytest.raises(adapter.ModelManagerImportError):
        adapter.ir_model_asset_record_id("legal_ir", 4096, "input_embedding", "head", "a" * 64)
    assert manager.get_calls == manager.add_calls == []


@pytest.mark.parametrize("scheme", ["lfs-payload-sha256", "git-blob-sha1"])
@pytest.mark.parametrize("profile", ["leanstral4096:cpu1:last:l2:single-sequence:tokens512:lazy-mmap:v2",
    "leanstral4096:cpu1:last:l2:single-sequence:tokens512:layer-reclaim:v3"])
def test_v2_registers_explicit_source4096_metadata_with_false_native_authority(tmp_path, scheme, profile):
    data, manager = make_source4096_data(tmp_path, scheme=scheme, profile=profile), InertManager()
    result = invoke_v2(data, manager)
    assert result["schema"] == adapter.RESULT_SCHEMA_V2 and result["registered_count"] == 1
    assert manager.persisted[result["outcomes"][0]["model_id"]] == data["plan"]["models"][0]["model_metadata"]
    assert result["authority"]["registration_metadata_verified"] is True
    assert all(value is False for key, value in result["authority"].items() if key != "registration_metadata_verified")
    assert all(result["authority"][key] is False for key in (
        "native_execution_verified_by_importer", "source_compatibility_verified", "live_native_capability_restored"))


def test_v2_can_retain_legacy_records_and_ids_without_migration(tmp_path):
    data, manager = make_source4096_data(tmp_path, count=2), InertManager()
    old_root = tmp_path / "legacy"
    old_root.mkdir()
    old = make_data(old_root)
    original = deepcopy(old["plan"]["models"][0])
    data["plan"]["models"].append(original)
    # A second receipt keeps its exact independent release binding.
    repin(data)
    data["releases"].extend(old["releases"])
    result = invoke_v2(data, manager)
    assert result["registered_count"] == 3
    assert manager.persisted[original["model_metadata"]["model_id"]] == original["model_metadata"]


def test_v2_source_identity_binds_producer_and_checkpoint_schema_but_not_evidence_locator(tmp_path):
    data = make_source4096_data(tmp_path)
    record = data["plan"]["models"][0]
    identity = record["model_metadata"]["huggingface_config"]["ir_checkpoint"]
    original = source4096_id(record)
    pin0 = identity["source_representation"]["evidence_pins"][0]
    alias = tmp_path / "same-evidence-other-location.json"
    alias.write_bytes(Path(pin0["path"]).read_bytes())
    identity["source_representation"]["evidence_pins"] = [pin(alias)]
    assert source4096_id(record) == original
    identity["schema_version"] = "native-4096-source-span-checkpoint/v1"
    assert source4096_id(record) != original
    identity["schema_version"] = "bound-native4096-source-span-checkpoint/v1"
    identity["source_representation"]["expected_producer"]["worker_sha256"] = "1" * 64
    assert source4096_id(record) != original


@pytest.mark.parametrize("mutation", ["dimension", "bool_dimension", "family", "role", "schema", "task",
    "missing_descriptor", "extra_descriptor", "producer_profile", "producer_hash", "producer_extra",
    "pooling", "normalization", "attention", "context", "sequences", "source_text", "capability", "scope",
    "missing_evidence", "extra_pin", "bad_library", "duplicate_evidence", "profile", "format", "io",
    "runtime_io", "native_authority", "ready", "teacher", "proof", "source_id", "architecture", "missing_flag"])
def test_v2_bad_native_declarations_refuse_before_manager_or_factory(tmp_path, mutation):
    data, manager = make_source4096_data(tmp_path), InertManager()
    metadata = data["plan"]["models"][0]["model_metadata"]
    config, identity = metadata["huggingface_config"], metadata["huggingface_config"]["ir_checkpoint"]
    source = identity["source_representation"]
    if mutation == "dimension": identity["dimension"] = 384
    elif mutation == "bool_dimension": identity["dimension"] = True
    elif mutation == "family": identity["ir_family_id"] = "security_ir"
    elif mutation == "role": identity["dimension_role"] = "latent"
    elif mutation == "schema": identity["schema_version"] = "arbitrary/v1"
    elif mutation == "task": identity["task_id"] = "vector_only_reconstruction"
    elif mutation == "missing_descriptor": identity.pop("source_representation")
    elif mutation == "extra_descriptor": source["native_proof"] = True
    elif mutation == "producer_profile": source["expected_producer"]["profile"] = "arbitrary4096"
    elif mutation == "producer_hash": source["expected_producer"]["model_sha256"] = "A" * 64
    elif mutation == "producer_extra": source["expected_producer"]["authority"] = True
    elif mutation == "pooling": source["pooling"] = "mean"
    elif mutation == "normalization": source["normalization"] = "none"
    elif mutation == "attention": source["attention"] = "bidirectional"
    elif mutation == "context": source["context_tokens"] = 8192
    elif mutation == "sequences": source["sequences"] = True
    elif mutation == "source_text": source["source_text_required"] = False
    elif mutation == "capability": source["ordinary_receipt_is_capability"] = True
    elif mutation == "scope": source["evidence_scope"] = "live_verified"
    elif mutation == "missing_evidence": source["evidence_pins"] = []
    elif mutation == "extra_pin": source["evidence_pins"][0]["authority"] = True
    elif mutation == "bad_library": source["expected_producer"]["library_sha256"] = {"../bad.so": "1" * 64}
    elif mutation == "duplicate_evidence": source["evidence_pins"].append(deepcopy(source["evidence_pins"][0]))
    elif mutation == "profile": identity["profile_id"] = "invented-qualified-profile"
    elif mutation == "format": identity["format_id"] = "invented-qualified-format"
    elif mutation == "io": metadata["inputs"] = metadata["inputs"][1:]
    elif mutation == "runtime_io": config["complete_runtime_io_contract"] = True
    elif mutation == "native_authority": config["native_execution_verified_by_importer"] = True
    elif mutation in ("ready", "teacher", "proof"):
        identity[{"ready": "runtime_ready", "teacher": "teacher_qualified", "proof": "proof_authority"}[mutation]] = True
    elif mutation == "source_id": identity["record_id"] = metadata["model_id"] = "ir-model-source-binding/v2:" + "0" * 64
    elif mutation == "architecture": metadata["architecture"] = "arbitrary-network"
    elif mutation == "missing_flag": config.pop("source_compatibility_verified")
    repin(data)
    def forbidden_factory(value):
        pytest.fail("Invalid native declaration reached metadata factory")
    with pytest.raises(adapter.ModelManagerImportError):
        invoke_v2(data, manager, factory=forbidden_factory)
    assert manager.get_calls == manager.add_calls == []


def test_v2_evidence_drift_before_dispatch_and_during_factory_is_detected(tmp_path):
    data, manager = make_source4096_data(tmp_path), InertManager()
    source = data["plan"]["models"][0]["model_metadata"]["huggingface_config"]["ir_checkpoint"]["source_representation"]
    path = Path(source["evidence_pins"][0]["path"])
    raw = path.read_bytes()
    path.write_bytes(raw + b" ")
    with pytest.raises(adapter.ModelManagerImportError):
        invoke_v2(data, manager)
    assert manager.get_calls == manager.add_calls == []
    path.write_bytes(raw)
    def changing_factory(value):
        path.write_bytes(raw + b" ")
        return deepcopy(value)
    with pytest.raises(adapter.ModelManagerImportError):
        invoke_v2(data, manager, factory=changing_factory)
    assert manager.add_calls == []


def test_v2_requires_fresh_persistence_and_preserves_idempotent_activity(tmp_path):
    data, manager = make_source4096_data(tmp_path), InertManager()
    manager.persist = False
    with pytest.raises(adapter.ModelManagerImportError) as failure:
        invoke_v2(data, manager)
    assert failure.value.outcomes[0]["add_model_returned"] is True
    assert failure.value.outcomes[0]["persisted_metadata_matched"] is False
    manager.persist = True
    stored = deepcopy(data["plan"]["models"][0]["model_metadata"])
    stored["inference_count"] = 17
    model_id = stored["model_id"]
    manager.models[model_id] = manager.persisted[model_id] = stored
    manager.add_calls.clear()
    result = invoke_v2(data, manager)
    assert result["already_present_count"] == 1 and manager.add_calls == []
    assert manager.persisted[model_id]["inference_count"] == 17


def make_reconciled_source_data(tmp_path):
    """Keep four declared binding generations in one explicit v2 plan."""
    roots = {kind: tmp_path / kind for kind in ("native", "legacy", "component", "profile")}
    for root in roots.values():
        root.mkdir()
    data = make_source4096_data(roots["native"])
    others = [make_data(roots["legacy"]), make_component_data(roots["component"]),
              make_source_representation_data(roots["profile"])]
    for kind, other in zip(("legacy", "component", "profile"), others):
        remote_path = f"reconciliation/{kind}/checkpoint.json"
        other["plan"]["models"][0]["release"]["path_in_repo"] = remote_path
        other["publication"]["files"][0]["path_in_repo"] = remote_path
        repin(other)
        data["plan"]["models"].extend(deepcopy(other["plan"]["models"]))
    repin(data)
    for other in others:
        data["releases"].extend(other["releases"])
    data["profile_path"] = roots["profile"] / "synthetic-source-profile.json"
    data["evidence_path"] = roots["native"] / "synthetic-native-evidence.json"
    return data


def invoke_reconciled(data, manager, *, factory=deepcopy, readback=None, **kwargs):
    return adapter.import_ir_model_manager_records_v2(data["manifest"],
        release_receipts=data["releases"], manager=manager,
        readback=manager.readback if readback is None else readback,
        metadata_factory=factory, **kwargs)


def test_reconciled_v2_plan_preserves_all_four_binding_contracts_and_record_ids(tmp_path):
    data, manager = make_reconciled_source_data(tmp_path), InertManager()
    originals = [deepcopy(record["model_metadata"]) for record in data["plan"]["models"]]
    ids = [metadata["model_id"] for metadata in originals]
    assert len(set(ids)) == 4
    result = invoke_reconciled(data, manager)
    assert result["schema"] == adapter.RESULT_SCHEMA_V2
    assert result["registered_count"] == result["persisted_metadata_matched_count"] == 4
    assert manager.persisted == {metadata["model_id"]: metadata for metadata in originals}
    native, legacy, component, profile = [metadata["huggingface_config"]["ir_checkpoint"]
                                           for metadata in originals]
    assert native["dimension_role"] == "source_input_representation_width"
    assert legacy["dimension"] == 384 and component["dimension"] is None
    assert profile["dimension_role"] == "input_embedding" and profile["dimension"] == 4096
    assert native["source_representation"]["expected_producer"]["library_sha256"] == {
        "/explicit/synthetic/library.so": "f" * 64}
    assert data["profile_path"].is_file()
    repeated = invoke_reconciled(data, manager)
    assert repeated["registered_count"] == 0 and repeated["already_present_count"] == 4
    assert len(manager.add_calls) == 4 and manager.persisted == {
        metadata["model_id"]: metadata for metadata in originals}
    assert all(value is False for key, value in result["authority"].items()
               if key != "registration_metadata_verified")


@pytest.mark.parametrize("entrypoint", ["v1", "v2"])
@pytest.mark.parametrize("binding", ["legacy", "component"])
@pytest.mark.parametrize("schema", ["original", "missing", "unknown"])
def test_reconciliation_refuses_embedded_v2_declarations_on_other_binding_schemas_before_effects(
        tmp_path, entrypoint, binding, schema):
    data = make_data(tmp_path) if binding == "legacy" else make_component_data(tmp_path)
    identity = data["plan"]["models"][0]["model_metadata"]["huggingface_config"]["ir_checkpoint"]
    identity["source_representation"] = {"schema": adapter.SOURCE_PROFILE_SCHEMA}
    if schema == "missing":
        identity.pop("asset_binding_schema", None)
    elif schema == "unknown":
        identity["asset_binding_schema"] = "ir-source-representation-binding/v999"
    if entrypoint == "v2":
        data["plan"]["schema"] = adapter.SCHEMA_V2
    repin(data)
    manager, factories = InertManager(), []
    with pytest.raises(adapter.ModelManagerImportError):
        (invoke if entrypoint == "v1" else invoke_reconciled)(data, manager,
            factory=lambda value: factories.append(value))
    assert manager.get_calls == manager.add_calls == factories == []


@pytest.fixture
def decoder_witness_data(tmp_path, monkeypatch):
    """One genuine original metadata registry; no tensors, Hub or native manager."""
    from tests.unit.logic.formalization.autoencoder import test_ir_decoder_profile_inventory as original
    def forbidden(*args, **kwargs):
        pytest.fail("decoder identity import fixture reached a numerical or Hub owner")
    for name in ("_instantiate", "default_descriptor", "open_autoencoder", "open_local_autoencoder",
                 "open_ir_cell_autoencoder", "open_ir_original_corpus_autoencoder",
                 "open_ir_decoder_format_autoencoder"):
        monkeypatch.setattr(original.hub, name, forbidden)
    source_dir, import_dir = tmp_path / "original-metadata", tmp_path / "import-metadata"
    source_dir.mkdir()
    import_dir.mkdir()
    source = original.make_profile_data(source_dir, "security_ir")
    registry = original.build(source)
    selected, profile, target = registry["checkpoints"][0], registry["profiles"][0], registry["formats"][0]
    data = make_data(import_dir)
    record = data["plan"]["models"][0]
    metadata = record["model_metadata"]
    identity = metadata["huggingface_config"]["ir_checkpoint"]
    checkpoint = deepcopy(selected["checkpoint_receipt"])
    record["checkpoint_pin"] = checkpoint
    metadata.update(model_id=selected["record_id"], architecture=profile["identity"]["decoder_architecture_id"],
                    model_revision=checkpoint["sha256"], revision_id=checkpoint["sha256"])
    identity.update(record_id=selected["record_id"], ir_family_id="security_ir", dimension=384,
        dimension_role="input_embedding", task_id=target["identity"]["task_id"],
        schema_version=selected["format_contract"]["checkpoint_schema"],
        profile_id=profile["profile_id"], format_id=target["format_id"], original_checkpoint_pin=checkpoint)
    registry_pin = save(tmp_path / "original-decoder-registry.json", registry)
    record["decoder_identity_witness"] = {"schema": "ir-decoder-identity-witness/v1",
        "registry_pin": registry_pin, "record_id": selected["record_id"],
        "target_format_schema_version": target["identity"]["schema_version"]}
    record["release"]["checkpoint_sha256"] = checkpoint["sha256"]
    remote = data["publication"]["files"][0]
    remote.update(file_pin=deepcopy(checkpoint), bytes=checkpoint["bytes"], sha256=checkpoint["sha256"],
                  remote_identity={"scheme": "lfs-payload-sha256", "bytes": checkpoint["bytes"],
                                   "sha256": checkpoint["sha256"]})
    data.update(decoder_registry=registry, decoder_registry_pin=registry_pin)
    repin(data)
    return data


def test_decoder_identity_witness_binds_pinned_original_without_enriching_persisted_metadata(decoder_witness_data):
    data, manager = decoder_witness_data, InertManager()
    record = data["plan"]["models"][0]
    before = deepcopy(record["model_metadata"])
    result = invoke(data, manager)
    assert result["completed"] is True and result["registered_count"] == 1
    assert manager.add_calls == [before] and manager.persisted[before["model_id"]] == before
    assert "decoder_identity_witness" not in before["huggingface_config"]["ir_checkpoint"]
    outcome = result["outcomes"][0]
    assert outcome["decoder_identity_witness"] == record["decoder_identity_witness"]
    assert outcome["decoder_identity_witness_scope"] == "selected_registry_metadata_identity_consistency_only"
    outcome["decoder_identity_witness"]["registry_pin"]["sha256"] = "0" * 64
    assert record["decoder_identity_witness"]["registry_pin"]["sha256"] != "0" * 64
    assert result["authority"]["model_numerically_loaded"] is False


def test_decoder_identity_witness_verifies_existing_record_without_migration_or_new_id(decoder_witness_data):
    data, manager = decoder_witness_data, InertManager()
    original = deepcopy(data["plan"]["models"][0]["model_metadata"])
    original.update(inference_count=23, last_run_id="existing-activity")
    manager.models[original["model_id"]] = deepcopy(original)
    manager.persisted[original["model_id"]] = deepcopy(original)
    result = invoke(data, manager)
    assert result["registered_count"] == 0 and result["already_present_count"] == 1
    assert manager.add_calls == [] and manager.readback_calls == [original["model_id"]]
    assert manager.persisted[original["model_id"]] == original


@pytest.mark.parametrize("fault", ["family", "task", "checkpoint_schema", "target_schema", "profile_id",
    "format_id", "record_id", "architecture", "original_checkpoint_alias", "float_dimension"])
def test_decoder_identity_witness_rejects_relabelled_known_record_before_manager_or_factory(
        decoder_witness_data, tmp_path, fault):
    data, manager, factories = decoder_witness_data, InertManager(), []
    record = data["plan"]["models"][0]
    metadata, witness = record["model_metadata"], record["decoder_identity_witness"]
    identity = metadata["huggingface_config"]["ir_checkpoint"]
    if fault == "family": identity["ir_family_id"] = "intent_ir"
    elif fault == "task": identity["task_id"] = "legal_text_reconstruction"
    elif fault == "checkpoint_schema": identity["schema_version"] = witness["target_format_schema_version"]
    elif fault == "target_schema": witness["target_format_schema_version"] = identity["schema_version"]
    elif fault == "profile_id": identity["profile_id"] = "ir-decoder-profile/v1:" + "1" * 64
    elif fault == "format_id": identity["format_id"] = "ir-decoder-format/v1:" + "2" * 64
    elif fault == "record_id": witness["record_id"] = "ir-decoder-checkpoint-record/v1:" + "3" * 64
    elif fault == "architecture": metadata["architecture"] = "different-declared-architecture"
    elif fault == "float_dimension": identity["dimension"] = 384.0
    else:
        alias = tmp_path / "same-checkpoint-content.json"
        alias.write_bytes(Path(record["checkpoint_pin"]["path"]).read_bytes())
        identity["original_checkpoint_pin"] = pin(alias)
    repin(data)
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager, factory=lambda value: factories.append(value))
    assert manager.get_calls == manager.add_calls == manager.readback_calls == factories == []


@pytest.mark.parametrize("fault", ["version", "extra", "pin_type", "record_type"])
def test_decoder_identity_witness_requires_closed_typed_versioned_control_record(decoder_witness_data, fault):
    data, manager = decoder_witness_data, InertManager()
    witness = data["plan"]["models"][0]["decoder_identity_witness"]
    if fault == "version": witness["schema"] = "ir-decoder-identity-witness/v2"
    elif fault == "extra": witness["runtime_ready"] = False
    elif fault == "pin_type": witness["registry_pin"]["bytes"] = float(witness["registry_pin"]["bytes"])
    else: witness["record_id"] = True
    repin(data)
    with pytest.raises(adapter.ModelManagerImportError): invoke(data, manager)
    assert manager.get_calls == manager.add_calls == manager.readback_calls == []


def test_decoder_identity_witness_registry_byte_cap_precedes_json_read(decoder_witness_data, monkeypatch):
    data, manager, seen = decoder_witness_data, InertManager(), []
    registry_pin = data["decoder_registry_pin"]
    original = adapter._json
    def observe(reference):
        seen.append(reference["path"])
        return original(reference)
    monkeypatch.setattr(adapter, "_json", observe)
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager, max_reference_bytes=registry_pin["bytes"] - 1)
    assert registry_pin["path"] not in seen
    assert manager.get_calls == manager.add_calls == manager.readback_calls == []


def test_decoder_identity_witness_registry_endpoint_drift_precedes_all_manager_calls(
        decoder_witness_data, monkeypatch):
    data, manager, factories = decoder_witness_data, InertManager(), []
    registry_path = data["decoder_registry_pin"]["path"]
    original = adapter._json
    def change_after_read(reference):
        result = original(reference)
        if reference["path"] == registry_path:
            path = Path(registry_path)
            path.write_bytes(path.read_bytes() + b" ")
        return result
    monkeypatch.setattr(adapter, "_json", change_after_read)
    with pytest.raises(adapter.ModelManagerImportError):
        invoke(data, manager, factory=lambda value: factories.append(value))
    assert manager.get_calls == manager.add_calls == manager.readback_calls == factories == []


@pytest.mark.parametrize("stage", ["factory", "after_add", "existing_readback"])
def test_decoder_identity_witness_registry_pin_remains_fenced_at_effect_boundaries(decoder_witness_data, stage):
    data, manager = decoder_witness_data, InertManager()
    registry_path = Path(data["decoder_registry_pin"]["path"])
    metadata = data["plan"]["models"][0]["model_metadata"]
    def change(): registry_path.write_bytes(registry_path.read_bytes() + b" ")
    def factory(value):
        change()
        return value
    def readback(model_id):
        value = manager.readback(model_id)
        change()
        return value
    if stage == "after_add": manager.after_add = change
    if stage == "existing_readback":
        manager.models[metadata["model_id"]] = deepcopy(metadata)
        manager.persisted[metadata["model_id"]] = deepcopy(metadata)
    with pytest.raises(adapter.ModelManagerImportError) as caught:
        invoke(data, manager, factory=factory if stage == "factory" else deepcopy,
            readback=readback if stage == "existing_readback" else manager.readback)
    outcome = caught.value.outcomes[0]
    if stage == "factory":
        assert manager.add_calls == manager.readback_calls == []
        assert outcome["add_model_started"] is False
    else:
        assert outcome["persisted_metadata_matched"] is True
        assert len(manager.add_calls) == (0 if stage == "existing_readback" else 1)


@pytest.mark.parametrize("stage", ["factory", "readback"])
@pytest.mark.parametrize("fault", ["integer_to_float", "boolean_to_integer"])
def test_decoder_identity_witness_strict_metadata_types_survive_factory_and_persistence(
        decoder_witness_data, stage, fault):
    data, manager = decoder_witness_data, InertManager()
    def erase(value):
        changed = deepcopy(value)
        identity = changed["huggingface_config"]["ir_checkpoint"]
        if fault == "integer_to_float":
            identity["original_checkpoint_pin"]["bytes"] = float(identity["original_checkpoint_pin"]["bytes"])
        else: identity["runtime_ready"] = 0
        return changed
    def readback(model_id): return erase(manager.readback(model_id))
    with pytest.raises(adapter.ModelManagerImportError) as caught:
        invoke(data, manager, factory=erase if stage == "factory" else deepcopy,
            readback=readback if stage == "readback" else manager.readback)
    outcome = caught.value.outcomes[0]
    if stage == "factory":
        assert manager.add_calls == manager.readback_calls == []
        assert outcome["add_model_started"] is False
    else:
        assert outcome["add_model_returned"] is True
        assert outcome["persisted_readback_returned"] is True
        assert outcome["persisted_metadata_matched"] is False


@pytest.mark.parametrize("branch", ["legacy", "component", "source_profile", "native_source_v2"])
def test_decoder_identity_witness_is_not_accepted_by_other_binding_branches(
        decoder_witness_data, tmp_path, branch):
    directory = tmp_path / "other-binding"
    directory.mkdir()
    if branch == "component": data = make_component_data(directory)
    elif branch == "source_profile": data = make_source_representation_data(directory)
    elif branch == "native_source_v2": data = make_source4096_data(directory)
    else: data = make_data(directory)
    data["plan"]["models"][0]["decoder_identity_witness"] = deepcopy(
        decoder_witness_data["plan"]["models"][0]["decoder_identity_witness"])
    repin(data)
    manager, factories = InertManager(), []
    with pytest.raises(adapter.ModelManagerImportError):
        if branch == "native_source_v2": invoke_v2(data, manager, factory=lambda value: factories.append(value))
        else: invoke(data, manager, factory=lambda value: factories.append(value))
    assert manager.get_calls == manager.add_calls == manager.readback_calls == factories == []


def test_decoder_identity_witness_opt_in_keeps_legacy_opaque_known_record_compatibility(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder import ir_decoder_profile_inventory as inventory
    data, manager = make_data(tmp_path), InertManager()
    metadata = data["plan"]["models"][0]["model_metadata"]
    identity = metadata["huggingface_config"]["ir_checkpoint"]
    identity.update(record_id="ir-decoder-checkpoint-record/v1:" + "2" * 64,
        profile_id="ir-decoder-profile/v1:" + "3" * 64, format_id="ir-decoder-format/v1:" + "4" * 64)
    metadata["model_id"] = identity["record_id"]
    def forbidden(*args, **kwargs): pytest.fail("legacy opaque record implicitly selected a strict witness")
    monkeypatch.setattr(inventory, "select_ir_decoder_identity_witness_v1", forbidden)
    repin(data)
    result = invoke(data, manager)
    assert result["registered_count"] == 1
    assert manager.add_calls[0]["model_id"] == metadata["model_id"]


@pytest.mark.parametrize("entrypoint", ["v1", "v2"])
def test_reconciliation_independent_profile_rejects_embedded_native_source_declaration(tmp_path, entrypoint):
    data, manager = make_source_representation_data(tmp_path), InertManager()
    identity = data["plan"]["models"][0]["model_metadata"]["huggingface_config"]["ir_checkpoint"]
    identity["source_representation"] = {"schema": adapter.SOURCE_PROFILE_SCHEMA}
    if entrypoint == "v2":
        data["plan"]["schema"] = adapter.SCHEMA_V2
    repin(data)
    factories = []
    with pytest.raises(adapter.ModelManagerImportError):
        (invoke if entrypoint == "v1" else invoke_reconciled)(data, manager,
            factory=lambda value: factories.append(value))
    assert manager.get_calls == manager.add_calls == factories == []


@pytest.mark.parametrize("extra", ["source_representation_profile_id", "source_representation_profile_pin"])
def test_reconciliation_native_source_rejects_independent_profile_identity_extras(tmp_path, extra):
    data, manager = make_source4096_data(tmp_path), InertManager()
    record = data["plan"]["models"][0]
    identity = record["model_metadata"]["huggingface_config"]["ir_checkpoint"]
    identity[extra] = ("ir-source-representation-profile/v1:" + "1" * 64
                       if extra.endswith("_id") else deepcopy(record["checkpoint_pin"]))
    repin(data)
    factories = []
    with pytest.raises(adapter.ModelManagerImportError):
        invoke_v2(data, manager, factory=lambda value: factories.append(value))
    assert manager.get_calls == manager.add_calls == factories == []


@pytest.mark.parametrize("entrypoint", ["v1", "v2"])
def test_reconciliation_independent_profile_cap_precedes_profile_read_for_each_entrypoint(
        tmp_path, monkeypatch, entrypoint):
    data, manager = make_source_representation_data(tmp_path), InertManager()
    identity = data["plan"]["models"][0]["model_metadata"]["huggingface_config"]["ir_checkpoint"]
    path = Path(identity["source_representation_profile_pin"]["path"])
    path.write_bytes(path.read_bytes() + b" " * 16384)
    identity["source_representation_profile_pin"] = pin(path)
    if entrypoint == "v2":
        data["plan"]["schema"] = adapter.SCHEMA_V2
    repin(data)
    maximum = max(data["manifest"]["bytes"], *(p["bytes"] for p in data["releases"])) + 1
    assert identity["source_representation_profile_pin"]["bytes"] > maximum
    reads, original = [], adapter._read
    def observed(reference, **kwargs):
        reads.append(reference["path"])
        return original(reference, **kwargs)
    monkeypatch.setattr(adapter, "_read", observed)
    with pytest.raises(adapter.ModelManagerImportError, match="bound"):
        (invoke if entrypoint == "v1" else invoke_reconciled)(data, manager,
            max_reference_bytes=maximum)
    assert str(path) not in reads and manager.get_calls == manager.add_calls == []


def test_reconciliation_native_evidence_cap_precedes_evidence_read(tmp_path, monkeypatch):
    data, manager = make_source4096_data(tmp_path), InertManager()
    identity = data["plan"]["models"][0]["model_metadata"]["huggingface_config"]["ir_checkpoint"]
    path = Path(identity["source_representation"]["evidence_pins"][0]["path"])
    path.write_bytes(path.read_bytes() + b" " * 16384)
    identity["source_representation"]["evidence_pins"] = [pin(path)]
    identity["record_id"] = data["plan"]["models"][0]["model_metadata"]["model_id"] = source4096_id(
        data["plan"]["models"][0])
    repin(data)
    maximum = max(data["manifest"]["bytes"], *(p["bytes"] for p in data["releases"])) + 1
    assert identity["source_representation"]["evidence_pins"][0]["bytes"] > maximum
    reads, original = [], adapter._read
    def observed(reference, **kwargs):
        reads.append(reference["path"])
        return original(reference, **kwargs)
    monkeypatch.setattr(adapter, "_read", observed)
    with pytest.raises(adapter.ModelManagerImportError, match="bound"):
        invoke_v2(data, manager, max_reference_bytes=maximum)
    assert str(path) not in reads and manager.get_calls == manager.add_calls == []


@pytest.mark.parametrize("reference", ["profile_path", "evidence_path"])
@pytest.mark.parametrize("stage", ["before_dispatch", "factory", "readback", "existing_readback"])
def test_reconciliation_mixed_plan_fences_both_source_references_at_effect_boundaries(tmp_path, reference, stage):
    data, manager = make_reconciled_source_data(tmp_path), InertManager()
    path = data[reference]
    def change():
        path.write_bytes(path.read_bytes() + b" ")
    def factory(value):
        change()
        return deepcopy(value)
    def readback(model_id):
        returned = manager.readback(model_id)
        change()
        return returned
    if stage == "existing_readback":
        for record in data["plan"]["models"]:
            metadata = record["model_metadata"]
            manager.models[metadata["model_id"]] = deepcopy(metadata)
            manager.persisted[metadata["model_id"]] = deepcopy(metadata)
    if stage == "before_dispatch":
        change()
    with pytest.raises(adapter.ModelManagerImportError) as caught:
        invoke_reconciled(data, manager, factory=factory if stage == "factory" else deepcopy,
            readback=readback if stage in ("readback", "existing_readback") else manager.readback)
    if stage == "before_dispatch":
        assert manager.get_calls == manager.add_calls == manager.readback_calls == []
        assert caught.value.outcomes == []
    elif stage == "factory":
        assert manager.add_calls == manager.readback_calls == []
        assert len(caught.value.outcomes) == 1 and caught.value.outcomes[0]["add_model_started"] is False
    else:
        assert len(manager.readback_calls) == 1 and len(caught.value.outcomes) == 1
        outcome = caught.value.outcomes[0]
        assert outcome["persisted_metadata_matched"] is True
        assert len(manager.add_calls) == (0 if stage == "existing_readback" else 1)
        assert outcome["already_present"] is (stage == "existing_readback")


def test_reconciliation_keeps_library_locations_in_v2_identity_and_outside_declared_profile_identity(tmp_path):
    from ipfs_datasets_py.logic.formalization.autoencoder import ir_decoder_profile_inventory as inventory
    data = make_source4096_data(tmp_path)
    record = data["plan"]["models"][0]
    source = record["model_metadata"]["huggingface_config"]["ir_checkpoint"]["source_representation"]
    source["expected_producer"]["model_sha256"] = (
        "4668fd2a6d2764de250489852230e96238eb5c0d7495866eb3b9c6c4fac5c7da")
    before_id = source4096_id(record)
    declaration = deepcopy(source["expected_producer"])
    declaration["library_sha256"] = list(declaration["library_sha256"].values())
    declared_before = inventory.build_ir_source_representation_profile(declaration)
    libraries = source["expected_producer"]["library_sha256"]
    libraries["/explicit/relocated/library.so"] = libraries.pop("/explicit/synthetic/library.so")
    assert source4096_id(record) != before_id
    declaration["library_sha256"] = list(libraries.values())
    assert inventory.build_ir_source_representation_profile(declaration) == declared_before
    assert source["ordinary_receipt_is_capability"] is False
    assert all(value is False for value in declared_before["authority"].values())


@pytest.mark.parametrize("entrypoint", ["v1", "v2"])
@pytest.mark.parametrize("binding", ["legacy", "component", "registered_format"])
@pytest.mark.parametrize("field", ["profile_id", "format_id"])
def test_reconciliation_native_source_profile_namespace_cannot_be_a_decoder_profile_or_format(
        tmp_path, entrypoint, binding, field):
    data = make_component_data(tmp_path) if binding == "component" else make_data(tmp_path)
    metadata = data["plan"]["models"][0]["model_metadata"]
    identity = metadata["huggingface_config"]["ir_checkpoint"]
    if binding == "registered_format":
        identity["profile_id"] = "ir-decoder-profile/v1:" + "1" * 64
        identity["format_id"] = "ir-decoder-format/v1:" + "2" * 64
        identity["record_id"] = metadata["model_id"] = "ir-decoder-checkpoint-record/v1:" + "3" * 64
    identity[field] = adapter.SOURCE_PROFILE_SCHEMA
    if entrypoint == "v2":
        data["plan"]["schema"] = adapter.SCHEMA_V2
    repin(data)
    manager, factories = InertManager(), []
    with pytest.raises(adapter.ModelManagerImportError):
        (invoke if entrypoint == "v1" else invoke_reconciled)(data, manager,
            factory=lambda value: factories.append(value))
    assert manager.get_calls == manager.add_calls == factories == []
