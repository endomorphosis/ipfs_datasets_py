"""One immutable artifact binds native numeric state and structural readout."""
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.logic.formalization.autoencoder import domain_targets, ui_targets

PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
ROOT = Path(features.__file__).resolve().parents[3]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


staged = os.environ.get("NATIVE_FORMAL_CHECKPOINT_MODULE_DIR")
if staged:
    decoder = _load(Path(staged) / "native_formal_decoder.py", PREFIX + ".native_formal_decoder")
    storage = _load(Path(staged) / "native_formal_checkpoint.py", PREFIX + ".native_formal_checkpoint")
else:
    decoder = importlib.import_module(PREFIX + ".native_formal_decoder")
    storage = importlib.import_module(PREFIX + ".native_formal_checkpoint")
fixtures = _load(ROOT / "tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_projection_features.py",
                 "_native_formal_checkpoint_fixtures")


@pytest.fixture(scope="module", params=storage.DOMAINS)
def native(request):
    make = {"intent_ir": fixtures._intent, "security_ir": fixtures._security, "ui_ux_ir": fixtures._ui}[request.param]
    train, tune = [make(1), make(2)], [make(3), make(4)]
    ids = [row["projection_id"] for row in train[0].to_dict()["projections"] if row["logic_family"]]
    space = features.build_feature_space(request.param, ids, train)
    adapter = ui_targets if request.param == "ui_ux_ir" else domain_targets
    contract = features.build_native_feature_contract(space, ir_schema=request.param + "/fixture-v1",
        adapter_sha256=hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest(), latent_width=4)
    head = decoder.train_formal_decoder(space, train)
    result = features.train_projection_features(contract, space, train, tune, epochs=1)
    return contract, space, head, result, train, tune


def _registry(tmp_path):
    return AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "artifacts")


def _register(registry, native, path, *, result=None, head=None, parent=None):
    contract, space, original_head, original_result, _, _ = native
    return storage.register_formal_candidate(registry, contract, space,
        original_result if result is None else result, original_head if head is None else head,
        path, parent_version_id=parent)


def test_register_reload_resume_preserves_full_numeric_state_and_head(native, tmp_path, monkeypatch):
    contract, space, head, result, train, tune = native
    before = features.digest([space, head, result])
    with _registry(tmp_path) as registry:
        calls = []
        original = registry.register_version
        def record(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)
        monkeypatch.setattr(registry, "register_version", record)
        receipt = _register(registry, native, tmp_path / "first")
        assert len(calls) == 1
        assert receipt["variant_id"] == storage.formal_variant_id(contract, head)
        assert receipt["variant_id"] != contract.variant_id
        saved = json.loads(registry.artifact_path(receipt["artifact"]).read_bytes())
        assert set(saved) == {"schema", "contract", "feature_space", "state", "report", "decoder_head"}
        loaded = storage.load_formal_candidate(registry, receipt["version_id"], contract.domain)
        assert loaded["contract"] == contract
        assert loaded["state"] == result["state"] and loaded["report"] == result["report"]
        assert loaded["decoder_head"] == head and loaded["feature_space"] == space
        resumed = features.train_projection_features(contract, space, train, tune,
            base_state=loaded["state"], epochs=1)
        child = _register(registry, native, tmp_path / "second", result=resumed, parent=receipt["version_id"])
        restored = storage.load_formal_candidate(registry, child["version_id"], contract.domain)
        assert restored["parent_version_id"] == receipt["version_id"]
        assert restored["state"] == resumed["state"]
        assert restored["decoder_head"] == head
        assert resumed["report"]["base_state_sha256"] == features.digest(result["state"])
        assert all(restored["state"][key] is False for key in features.FALSE)
        for foreign in set(storage.DOMAINS) - {contract.domain}:
            with pytest.raises(ValueError, match="another domain"):
                storage.load_formal_candidate(registry, receipt["version_id"], foreign)
    assert features.digest([space, head, result]) == before


def test_changed_head_is_a_distinct_variant_and_cannot_reuse_parent(native, tmp_path):
    contract, space, head, result, train, tune = native
    changed = deepcopy(head)
    selected = next(name for name, value in changed["projections"].items() if value["status"] == "ready")
    changed["projections"][selected] = {"status": "unsupported", "reason": "variable_shape_requires_presence_head", "shape": None}
    decoder.validate_decoder(space, changed)
    with _registry(tmp_path) as registry:
        parent = _register(registry, native, tmp_path / "parent")
        resumed = features.train_projection_features(contract, space, train, tune, base_state=result["state"], epochs=1)
        with pytest.raises(ValueError, match="parent variant"):
            _register(registry, native, tmp_path / "bad-head", result=resumed, head=changed, parent=parent["version_id"])
        separate = _register(registry, native, tmp_path / "separate", head=changed)
        assert separate["variant_id"] != parent["variant_id"]
        assert not (tmp_path / "bad-head").exists()


@pytest.mark.parametrize("fault", ("numeric_parent", "missing_parent", "report_source", "report_state", "authority", "extra_report"))
def test_bad_bindings_are_rejected_before_staging(native, tmp_path, fault):
    contract, space, head, result, train, tune = native
    with _registry(tmp_path) as registry:
        parent = _register(registry, native, tmp_path / "parent")
        changed = deepcopy(result)
        parent_id = None
        if fault == "numeric_parent":
            changed["report"]["base_state_sha256"] = "0" * 64
            parent_id = parent["version_id"]
        elif fault == "missing_parent":
            changed["report"]["base_state_sha256"] = features.digest(result["state"])
        elif fault == "report_source":
            changed["report"]["training_targets_sha256"] = "not-a-digest"
        elif fault == "report_state":
            changed["report"]["selected_total_epochs"] += 1
        elif fault == "authority":
            changed["report"]["admitted"] = True
        else:
            changed["report"]["proof_authority"] = True
        with pytest.raises(ValueError):
            _register(registry, native, tmp_path / "bad", result=changed, parent=parent_id)
        assert not (tmp_path / "bad").exists()


def test_load_rejects_content_valid_forged_metadata_and_numeric_parent(native, tmp_path):
    contract, space, head, result, train, tune = native
    with _registry(tmp_path) as registry:
        parent = _register(registry, native, tmp_path / "parent")
        row = registry.get_version(parent["version_id"])
        metadata = {**row["metadata"], "decoder_head_sha256": "0" * 64}
        forged = registry.register_version("forged-metadata", row["variant_id"], row["artifact"], metadata)
        with pytest.raises(ValueError, match="metadata differs"):
            storage.load_formal_candidate(registry, forged["version_id"], contract.domain)
        envelope = json.loads(registry.artifact_path(row["artifact"]).read_bytes())
        envelope["report"]["base_state_sha256"] = "0" * 64
        path = tmp_path / "forged.json"
        path.write_bytes(features._raw(envelope))
        artifact = registry.stage_artifact(path)
        forged = registry.register_version("forged-parent", row["variant_id"], artifact, row["metadata"], parent["version_id"])
        with pytest.raises(ValueError, match="numerical parent differs"):
            storage.load_formal_candidate(registry, forged["version_id"], contract.domain)


def test_load_rejects_blob_tamper_and_closed_envelope(native, tmp_path):
    contract = native[0]
    with _registry(tmp_path) as registry:
        parent = _register(registry, native, tmp_path / "parent")
        row = registry.get_version(parent["version_id"])
        envelope = json.loads(registry.artifact_path(row["artifact"]).read_bytes())
        envelope["unexpected"] = "must reject"
        path = tmp_path / "extra.json"
        path.write_bytes(features._raw(envelope))
        artifact = registry.stage_artifact(path)
        forged = registry.register_version("extra-envelope", row["variant_id"], artifact, row["metadata"])
        with pytest.raises(ValueError, match="closed formal"):
            storage.load_formal_candidate(registry, forged["version_id"], contract.domain)
        original = registry.artifact_path(parent["artifact"])
        raw = original.read_bytes()
        original.write_bytes(raw[:-1] + b" ")
        with pytest.raises(ValueError, match="digest differs"):
            storage.load_formal_candidate(registry, parent["version_id"], contract.domain)


def test_incremental_training_batch_retains_basis_and_head(native, tmp_path):
    contract, space, head, result, train, tune = native
    make = {"intent_ir": fixtures._intent, "security_ir": fixtures._security, "ui_ux_ir": fixtures._ui}[contract.domain]
    incremental = [make(5)]
    resumed = features.train_projection_features(contract, space, incremental, tune,
        base_state=result["state"], epochs=1)
    assert resumed["report"]["training_targets_sha256"] != space["training_targets_sha256"]
    assert resumed["report"]["training_target_count"] == 1
    with _registry(tmp_path) as registry:
        parent = _register(registry, native, tmp_path / "parent")
        child = _register(registry, native, tmp_path / "incremental", result=resumed, parent=parent["version_id"])
        restored = storage.load_formal_candidate(registry, child["version_id"], contract.domain)
        assert restored["state"] == resumed["state"]
        assert restored["decoder_head"] == head
        assert restored["feature_space"] == space
        assert restored["report"]["training_targets_sha256"] == features.digest([value.to_dict() for value in incremental])


def test_decoder_source_guard_and_numeric_nan_reject_before_staging(native, tmp_path):
    with _registry(tmp_path) as registry:
        head = deepcopy(native[2])
        head["implementation_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="implementation changed"):
            _register(registry, native, tmp_path / "drifted", head=head)
        result = deepcopy(native[3])
        result["state"]["parameters"][0][0][0] = float("nan")
        with pytest.raises(ValueError, match="finite JSON"):
            _register(registry, native, tmp_path / "nonfinite", result=result)
        assert not (tmp_path / "drifted").exists()
        assert not (tmp_path / "nonfinite").exists()


def test_artifact_bound_is_checked_before_any_blob_read(native, tmp_path, monkeypatch):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import SCHEMA, content_identity
    contract = native[0]
    with _registry(tmp_path) as registry:
        receipt = _register(registry, native, tmp_path / "parent")
        row = registry.get_version(receipt["version_id"])
        row["artifact"]["bytes"] = storage.MAX_CANDIDATE_BYTES + 1
        row["version_id"] = content_identity({"schema": SCHEMA, **{key: row[key]
            for key in ("variant_id", "artifact", "metadata", "parent_version_id")}})
        monkeypatch.setattr(registry, "get_version", lambda version_id: row)
        def forbidden(artifact):
            pytest.fail("over-limit artifact must be rejected before file access")
        monkeypatch.setattr(registry, "artifact_path", forbidden)
        with pytest.raises(ValueError, match="byte bound"):
            storage.load_formal_candidate(registry, row["version_id"], contract.domain)
