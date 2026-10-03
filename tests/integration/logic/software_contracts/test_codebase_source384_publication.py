"""Canonical inference publication stays independent of training workspace guards."""
import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as shared


def test_shared_stage_preserves_canonical_bytes_and_cold_registry(tmp_path, monkeypatch):
    database, artifacts = tmp_path/'registry.duckdb', tmp_path/'artifacts'
    value = {'z': [None, True, 7], 'a': {'text': 'λ\n"quoted"'}}
    expected = b'{"a":{"text":"\xce\xbb\\n\\"quoted\\""},"z":[null,true,7]}'
    assert shared._raw(value) == expected
    with AutoencoderRegistry(database, artifacts) as registry:
        staged = []
        native_stage = registry.stage_artifact
        def capture(path):
            staged.append(Path(path))
            assert path.name == 'artifact.json'
            assert path.parent.name.startswith('codebase-generation-')
            return native_stage(path)
        monkeypatch.setattr(registry, 'stage_artifact', capture)
        descriptor = shared._stage(registry, value)
        assert descriptor == {'sha256': hashlib.sha256(expected).hexdigest(), 'bytes': len(expected)}
        assert registry.read_artifact(descriptor, max_bytes=4096) == expected
        assert not staged[0].parent.exists()
    with AutoencoderRegistry(database, artifacts) as reopened:
        assert reopened.read_artifact(descriptor, max_bytes=4096) == expected
        assert shared._stage(reopened, value) == descriptor


@pytest.mark.parametrize('failure', ['stage', 'serialization'])
def test_shared_stage_cleans_temporary_directory_on_failure(tmp_path, monkeypatch, failure):
    directories = []
    native_temporary = shared.tempfile.TemporaryDirectory
    def temporary(**kwargs):
        result = native_temporary(dir=tmp_path, **kwargs)
        directories.append(Path(result.name))
        return result
    monkeypatch.setattr(shared.tempfile, 'TemporaryDirectory', temporary)
    class RejectedStage:
        calls = 0
        def stage_artifact(self, path):
            self.calls += 1
            assert Path(path).is_file()
            raise RuntimeError('injected registry refusal')
    registry = RejectedStage()
    value = {'bad': float('nan')} if failure == 'serialization' else {'value': 1}
    with pytest.raises(ValueError if failure == 'serialization' else RuntimeError):
        shared._stage(registry, value)
    assert registry.calls == int(failure == 'stage')
    assert len(directories) == 1 and not directories[0].exists()


def test_generation_compatibility_delegates_shared_stage(monkeypatch):
    from ipfs_datasets_py.logic.software_contracts import codebase_model_generation as generation
    registry, value, result = object(), {'value': 'canonical'}, object()
    calls = []
    def stage(actual_registry, actual_value):
        calls.append((actual_registry, actual_value))
        return result
    monkeypatch.setattr(shared, '_stage', stage)
    assert generation._stage(registry, value) is result
    assert calls == [(registry, value)]


def test_training_proof_workspace_guard_still_refuses_no_checkout(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_schema_lake as lake
    # Only the location is varied: the canonical guard and its source remain
    # the real training owner. A packaged directory must not nominate itself.
    owner = tmp_path/'relocated'/'autoencoder_schema_lake.py'
    owner.parent.mkdir()
    owner.write_bytes(Path(lake.__file__).read_bytes())
    monkeypatch.setattr(lake, '__file__', str(owner))
    with pytest.raises(lake.SchemaLakeError, match='canonical workspace checkout is unavailable'):
        lake._workspace()
