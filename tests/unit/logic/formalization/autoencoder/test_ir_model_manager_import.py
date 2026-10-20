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
