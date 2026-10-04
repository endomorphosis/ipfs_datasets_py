"""Real trained seven-tensor export and inference on new admitted source bytes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

from tests.unit.logic.formalization.autoencoder.test_codebase_autoencoder_transfer import teacher, fork, joint_inputs  # noqa: F401
from ipfs_datasets_py.logic.formalization.autoencoder.security import codebase_autoencoder as trainer
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_autoencoder_checkpoint as portable


@pytest.fixture
def trained(joint_inputs):
    descriptor = trainer.train_codebase_autoencoder(**joint_inputs)
    return joint_inputs, descriptor


@pytest.fixture
def package(trained, tmp_path):
    inputs, descriptor = trained
    result = portable.export_security_checkpoint(repository=inputs["repository"], expected_receipt=descriptor,
        output=tmp_path / "portable-security-model")
    return inputs, descriptor, result


def _new_sources(tmp_path):
    root = tmp_path / "new-admitted-repository"
    root.mkdir()
    raw = b'def current(value):\n    if value < 0:\n        raise ValueError(value)\n    return value * 2\n'
    (root / "new.py").write_bytes(raw)
    return root, {"new.py": hashlib.sha256(raw).hexdigest()}


def _repin(package, filename, value):
    root = Path(package["output"])
    path = root / filename
    path.chmod(0o644)
    path.write_bytes(portable._json(value))
    manifest_path = root / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][filename] = {"sha256": portable._sha(path.read_bytes()), "bytes": path.stat().st_size}
    manifest_path.chmod(0o644)
    manifest_path.write_bytes(portable._json(manifest))
    return portable._sha(manifest_path.read_bytes())


def authored_public_review(trained):
    """Review shape for qualified synthetic weights; no real license asserted."""
    parent = trained["weight_transfer"]
    return {"schema": "security-autoencoder-public-provenance-review@1",
        "bottle_training_input": {"header_copyright": "Authored test fixture", "header_license": "not asserted",
            "raw_source_in_release": False, "source_sha256": next(iter(trained["source_hashes"].values()))},
        "formal_capabilities": "advisory candidates only; no formal or proof authority",
        "license_statement": "Authored qualification; no inherited weight license asserted.",
        "parent_initializer": {"initializer_sha256": parent["initializer_sha256"],
            "source_checkpoint_sha256": parent["source_checkpoint_sha256"], "original_fit_history_known": False,
            "original_training_metadata_available": False, "standalone_weight_license_declared": False,
            "transferred_component": "Authored token lexical vectors; no legal heads"},
        "proposed_repository": "authored/security-model", "release_exclusions": ["raw source", "teacher", "optimizer"],
        "release_kind": "experimental_benchmark_informed_development", "remote_evidence": [],
        "requested_visibility": "public", "review_status": "reviewed_with_explicit_lineage_limits",
        "security_training": {"canonical_export_manifest_sha256": trained["canonical_cve_training"]["manifest_sha256"],
            "checkpoint_sha256": trained["checkpoint_sha256"], "dataset_family_exclusions": "authored fixture only",
            "epochs": trained["epochs_completed"], "external_pairs": trained["metrics"]["security_candidate_training"]["sample_count"],
            "head_target_vocabulary": trained["security_candidate_nominations"]["target_vocabulary"],
            "held_out_evaluation": False, "task_functions": trained["sample_count"]}, "source_components": []}


def test_public_review_is_explicit_lineage_bound_and_has_no_inferred_license(trained, tmp_path):
    inputs, descriptor = trained
    review = authored_public_review(descriptor)
    card = "# Authored public development qualification\nNo standalone inherited-weight license asserted.\n"
    exported = portable.export_security_checkpoint(repository=inputs["repository"], expected_receipt=descriptor,
        output=tmp_path / "public-model", provenance_review=review, model_card=card)
    loaded = portable.load_security_checkpoint(Path(exported["output"]), expected_manifest_sha256=exported["manifest_sha256"])
    assert loaded["provenance_review"] == review and loaded["model_card"] == card
    assert loaded["provenance_review"]["parent_initializer"]["original_fit_history_known"] is False
    altered = deepcopy(review)
    altered["security_training"]["checkpoint_sha256"] = "a" * 64
    pin = _repin(exported, "provenance-review.json", altered)
    with pytest.raises(ValueError, match="provenance review differs"):
        portable.load_security_checkpoint(Path(exported["output"]), expected_manifest_sha256=pin)


def test_unpaired_or_source_payload_review_is_not_packaged(trained, tmp_path):
    inputs, descriptor = trained
    kwargs = dict(repository=inputs["repository"], expected_receipt=descriptor, output=tmp_path / "refused-public")
    with pytest.raises(ValueError, match="supplied together"):
        portable.export_security_checkpoint(**kwargs, model_card="Authored unpaired card")
    review = authored_public_review(descriptor)
    review["raw_cve_body"] = "def source_body(): pass"
    with pytest.raises(ValueError, match="closed explicit public"):
        portable.export_security_checkpoint(**kwargs, model_card="Authored card", provenance_review=review)
    assert not kwargs["output"].exists()


def test_export_exact_tensor_parity_lineage_and_no_original_state_mutation(package, teacher):
    inputs, trained, descriptor = package
    loaded = portable.load_security_checkpoint(Path(descriptor["output"]), expected_manifest_sha256=descriptor["manifest_sha256"])
    old = json.loads((inputs["output"] / "checkpoint.json").read_text())
    assert [loaded["checkpoint"]["tensors"][name] for name in portable.TENSOR_NAMES] == old["weights"]
    assert loaded["descriptor"] == descriptor
    assert loaded["native_manifest"]["domain"] == "security"
    assert loaded["native_manifest"]["metadata"]["runtime_domain_adapter"] == "security-code@1"
    assert loaded["lineage"]["training_receipt_sha256"] == trained["receipt_sha256"]
    assert loaded["lineage"]["parent_fit_metadata"] == "not available in parent checkpoint"
    assert loaded["lineage"]["model_scope"] == "benchmark_informed_development"
    assert teacher[0].read_bytes() == teacher[2]
    assert trainer.validate_codebase_autoencoder(repository=inputs["repository"], expected_receipt=trained)["status"] == "verified"
    names = {p.name for p in Path(descriptor["output"]).iterdir()}
    assert names == portable.PACKAGE_FILES
    content = b"\n".join(p.read_bytes() for p in Path(descriptor["output"]).iterdir())
    assert str(inputs["repository"]).encode() not in content
    assert str(inputs["output"]).encode() not in content
    assert b"def count(value)" not in content and b"legal-only" not in content and b"source.checkpoint" not in content
    assert loaded["provenance_review"]["status"] == "not_reviewed_for_publication"


def test_frozen_inference_survives_removal_of_original_inputs_without_training_or_modal_import(package, tmp_path, monkeypatch):
    inputs, trained, descriptor = package
    old_files = {p: p.read_bytes() for p in inputs["output"].iterdir()}
    relocated = tmp_path / "clean-offline-package"
    shutil.copytree(descriptor["output"], relocated)
    descriptor = {**descriptor, "output": str(relocated)}
    # Old training, initializer and canonical export are no longer available.
    for folder in (inputs["repository"], inputs["output"], Path(inputs["weight_transfer"]["output"]),
                   Path(inputs["canonical_cve_training"]["output"])):
        folder.rename(folder.with_name(folder.name + "-unavailable"))
    monkeypatch.setattr(trainer, "validate_codebase_autoencoder", lambda **kw: pytest.fail("old training validation called"))
    monkeypatch.setattr(trainer, "train_codebase_autoencoder", lambda **kw: pytest.fail("training called"))
    import torch
    monkeypatch.setattr(torch, "randn", lambda *a, **kw: pytest.fail("random initialization called"))
    monkeypatch.setattr(torch.optim, "Adam", lambda *a, **kw: pytest.fail("optimizer called"))
    monkeypatch.setitem(sys.modules, "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder", None)
    root, hashes = _new_sources(tmp_path)
    observed = portable.infer_security_checkpoint(repository=root, paths=["new.py"], source_hashes=hashes,
        checkpoint=descriptor, output=tmp_path / "new-observations")
    assert observed["mode"] == "frozen_inference" and observed["sample_count"] == 1
    assert observed["training_steps"] == observed["provider_calls"] == observed["download_calls"] == 0
    assert observed["security_candidate_nominations"]["rows"][0]["row_id"] == observed["ranks"][0]["row_id"]
    assert portable.validate_security_inference(repository=root, expected_receipt=observed) == observed
    assert all((path.parent.with_name(path.parent.name + "-unavailable") / path.name).read_bytes() == raw for path, raw in old_files.items())


def test_source_projection_and_output_match_original_trainer_numerically(package, tmp_path):
    inputs, trained, descriptor = package
    result = portable.infer_security_checkpoint(repository=inputs["repository"], paths=inputs["paths"],
        source_hashes=inputs["source_hashes"], checkpoint=descriptor, output=tmp_path / "parity-observation")
    index = json.loads((inputs["output"] / "index.json").read_text())
    assert result["ranks"] == index["ranks"]
    assert result["security_candidate_nominations"]["rows"] == index["security_candidate_nominations"]["rows"]
    assert portable.validate_security_inference(repository=inputs["repository"], expected_receipt=result) == result


@pytest.mark.parametrize("kind", ["missing_tensor", "extra_tensor", "shape", "nan", "float32", "vocabulary", "target", "namespace", "authority", "fixture", "lineage"])
def test_consistently_repinned_invalid_package_is_rejected(package, kind):
    _, _, descriptor = package
    name = "checkpoint.json"
    if kind in {"vocabulary", "target"}:
        name = "vocabularies.json"
    elif kind == "authority":
        name = "config.json"
    elif kind == "fixture":
        name = "inference-fixture.json"
    elif kind == "lineage":
        name = "lineage.json"
    value = json.loads(Path(descriptor["output"], name).read_text())
    if kind == "missing_tensor":
        del value["tensors"]["security_head_bias"]
    elif kind == "extra_tensor":
        value["tensors"]["legal_head"] = [0.0]
    elif kind == "shape":
        value["tensors"]["encoder_weight"][0].append(0.0)
    elif kind == "nan":
        path = Path(descriptor["output"], name)
        raw = path.read_bytes().replace(b'"float64"', b'NaN', 1)
        path.chmod(0o644)
        path.write_bytes(raw)
        manifest = json.loads(Path(descriptor["output"], "release-manifest.json").read_text())
        manifest["files"][name] = {"sha256": portable._sha(raw), "bytes": len(raw)}
        mpath = Path(descriptor["output"], "release-manifest.json")
        mpath.chmod(0o644)
        mpath.write_bytes(portable._json(manifest))
        with pytest.raises(ValueError, match="nonfinite"):
            portable.load_security_checkpoint(Path(descriptor["output"]), expected_manifest_sha256=portable._sha(mpath.read_bytes()))
        return
    elif kind == "float32":
        value["dtype"] = "float32"
    elif kind == "vocabulary":
        value["lexical_keys"].reverse()
    elif kind == "target":
        value["targets"].append("formula:proved")
    elif kind == "namespace":
        value["domain"] = "legal-ir"
    elif kind == "authority":
        value["proof_authority"] = True
    elif kind == "fixture":
        value["results"]["rows"][0]["scores"][0] += .01
    else:
        value["raw_body"] = "forbidden payload"
    pin = _repin(descriptor, name, value)
    with pytest.raises(ValueError):
        portable.load_security_checkpoint(Path(descriptor["output"]), expected_manifest_sha256=pin)


@pytest.mark.parametrize("kind", ["extra_file", "symlink", "hardlink", "digest", "namespace"])
def test_artifact_inventory_and_paths_are_closed(package, tmp_path, kind):
    _, _, descriptor = package
    root = Path(descriptor["output"])
    pin = descriptor["manifest_sha256"]
    if kind == "extra_file":
        (root / "teacher.checkpoint").write_bytes(b"must never load")
    elif kind == "symlink":
        moved = tmp_path / "moved.json"
        (root / "checkpoint.json").rename(moved)
        (root / "checkpoint.json").symlink_to(moved)
    elif kind == "hardlink":
        (tmp_path / "linked.json").hardlink_to(root / "checkpoint.json")
    elif kind == "digest":
        pin = "0" * 64
    else:
        other = tmp_path / "legal-ir" / "model"
        other.parent.mkdir()
        root.rename(other)
        root = other
    with pytest.raises(ValueError):
        portable.load_security_checkpoint(root, expected_manifest_sha256=pin)


@pytest.mark.parametrize("kind", ["source", "checkpoint", "receipt", "observation", "descriptor"])
def test_source_and_inference_drift_are_never_reused(package, tmp_path, kind):
    _, _, descriptor = package
    root, hashes = _new_sources(tmp_path)
    output = tmp_path / "inference"
    observed = portable.infer_security_checkpoint(repository=root, paths=["new.py"], source_hashes=hashes,
        checkpoint=descriptor, output=output)
    if kind == "source":
        (root / "new.py").write_text("def changed(value): return value\n")
    elif kind == "checkpoint":
        path = Path(descriptor["output"], "checkpoint.json")
        path.chmod(0o644)
        path.write_bytes(path.read_bytes() + b" ")
    elif kind == "descriptor":
        observed["training_steps"] = 1
    else:
        path = output / ("receipt.json" if kind == "receipt" else "inference.json")
        path.chmod(0o644)
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        portable.validate_security_inference(repository=root, expected_receipt=observed)


def test_new_source_observation_can_refresh_without_weight_changes(package, tmp_path):
    _, _, descriptor = package
    root, hashes = _new_sources(tmp_path)
    before = {p.name: p.read_bytes() for p in Path(descriptor["output"]).iterdir()}
    first = portable.infer_security_checkpoint(repository=root, paths=["new.py"], source_hashes=hashes,
        checkpoint=descriptor, output=tmp_path / "first")
    raw = b'def current(value):\n    return value\n'
    (root / "new.py").write_bytes(raw)
    second = portable.infer_security_checkpoint(repository=root, paths=["new.py"], source_hashes={"new.py": portable._sha(raw)},
        checkpoint=descriptor, output=tmp_path / "second")
    assert first["inference_sha256"] != second["inference_sha256"]
    assert first["checkpoint"] == second["checkpoint"]
    assert before == {p.name: p.read_bytes() for p in Path(descriptor["output"]).iterdir()}
    with pytest.raises(ValueError, match="drift"):
        portable.validate_security_inference(repository=root, expected_receipt=first)
    assert portable.validate_security_inference(repository=root, expected_receipt=second) == second


def test_boolean_counters_and_sample_counts_are_not_valid_integer_receipts(package, tmp_path):
    _, _, descriptor = package
    with pytest.raises(ValueError, match="descriptor differs"):
        portable.score_security_observations(checkpoint={**descriptor, "training_steps": False},
            observations=portable._fixture_observations(3))
    root, hashes = _new_sources(tmp_path)
    output = tmp_path / "inference"
    observed = portable.infer_security_checkpoint(repository=root, paths=["new.py"], source_hashes=hashes,
        checkpoint=descriptor, output=output)
    path = output / "receipt.json"
    receipt = json.loads(path.read_text())
    receipt["sample_count"] = True
    raw = portable._json(receipt)
    path.chmod(0o644)
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="authority, mode or identity"):
        portable.validate_security_inference(repository=root,
            expected_receipt={**observed, "sample_count": True, "receipt_sha256": portable._sha(raw)})


def test_feature_extraction_keeps_secret_screen_and_closed_paths(package, tmp_path):
    _, _, descriptor = package
    root, hashes = _new_sources(tmp_path)
    for path in ("../new.py", "/new.py", ".git/config", ".runtime/input.py"):
        with pytest.raises(ValueError):
            portable.infer_security_checkpoint(repository=root, paths=[path], source_hashes={path: hashes["new.py"]},
                checkpoint=descriptor, output=tmp_path / "refused")
    raw = b'def current():\n    password = "authored-secret-never-export"\n    return password\n'
    (root / "new.py").write_bytes(raw)
    with pytest.raises(Exception, match="secret screen"):
        portable.infer_security_checkpoint(repository=root, paths=["new.py"], source_hashes={"new.py": portable._sha(raw)},
            checkpoint=descriptor, output=tmp_path / "refused")
    assert not (tmp_path / "refused").exists()
