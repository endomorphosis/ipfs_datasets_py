"""Owner migration preserves inert weights and rejects unreviewed semantics."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from .test_security_autoencoder_checkpoint import teacher, fork, joint_inputs, trained, package, _repin
from ipfs_datasets_py.logic.formalization.autoencoder.security import checkpoint_migration as migration
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_autoencoder_checkpoint as portable


def legacy(package):
    descriptor = package[2]
    config = json.loads(Path(descriptor["output"], "config.json").read_bytes())
    config.update(migration.LEGACY_IMPLEMENTATIONS)
    return descriptor, _repin(descriptor, "config.json", config)


def test_migration_preserves_every_weight_and_replays_numeric_fixture(package, tmp_path):
    descriptor, digest = legacy(package)
    root = Path(descriptor["output"])
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    with pytest.raises(ValueError, match="implementation"):
        portable.load_security_checkpoint(root, expected_manifest_sha256=digest)
    result = migration.migrate_supervisor_security_checkpoint(package=root,
        expected_manifest_sha256=digest, output=tmp_path / "datasets-owned")
    loaded = portable.load_security_checkpoint(Path(result["destination"]["output"]),
        expected_manifest_sha256=result["destination"]["manifest_sha256"])
    assert loaded["descriptor"]["checkpoint_sha256"] == descriptor["checkpoint_sha256"]
    assert result["numeric_fixture_replayed"] and not result["runtime_promoted"]
    assert result["training_steps"] == result["provider_calls"] == result["download_calls"] == 0
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}
    for name in result["unchanged_files"]:
        assert Path(result["destination"]["output"], name).read_bytes() == before[name]


@pytest.mark.parametrize("change", ["producer", "semantics", "fixture", "authority", "manifest"])
def test_migration_refuses_rebound_invalid_inputs_without_publishing(package, tmp_path, change):
    descriptor, digest = legacy(package)
    root = Path(descriptor["output"])
    name = "config.json"
    value = json.loads((root / name).read_bytes())
    if change == "producer": value["feature_implementation_sha256"] = "f" * 64
    elif change == "semantics": value["normalization"] = "none"
    elif change == "authority": value["proof_authority"] = True
    elif change == "fixture":
        name = "inference-fixture.json"
        value = json.loads((root / name).read_bytes())
        value["results"] = {"forged": True}
    if change == "manifest": digest = "0" * 64
    else: digest = _repin(descriptor, name, value)
    output = tmp_path / "refused-migration"
    with pytest.raises(ValueError):
        migration.migrate_supervisor_security_checkpoint(package=root,
            expected_manifest_sha256=digest, output=output)
    assert not output.exists()
