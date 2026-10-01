"""CLI lineage selection and anchored ancestry; never contacts the Hub."""
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_formula_fleet as fleet
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_formula_exchange as exchange
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import native_formula_checkpoint as storage
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry

ROOT = Path(fleet.__file__).resolve().parents[3]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module
cli = load('_formula_exchange_cli', ROOT / 'scripts/ops/autoencoder/formula_checkpoint_exchange.py')
fixtures = load('_formula_exchange_cli_fixtures', ROOT / 'tests/unit/optimizers/logic_theorem_optimizer/test_native_formula_training.py')


@pytest.fixture
def seeded(tmp_path):
    import torch
    previous = torch.get_num_threads(); torch.set_num_threads(1)
    try:
        cp, train, tune = fixtures._build('security_ir')
        result = fixtures.learner.train_native_formula(cp, train, tune, epochs=1, max_seconds=60)
        db, artifacts = tmp_path / 'registry.duckdb', tmp_path / 'artifacts'
        with AutoencoderRegistry(db, artifacts) as owner:
            parent = storage.register_candidate(owner, result, tmp_path / 'parent')
            runtime = runtimes.load_version(owner, parent['version_id'], domain='security_ir', version='native_formula_v1')
            child = runtime.train(train, validation_samples=tune, epochs=1, max_seconds=60)
            version = runtime.register_candidate(owner, tmp_path / 'child')
        yield db, artifacts, result, parent, child, version
    finally:
        torch.set_num_threads(previous)


def options(tmp_path, seeded, domain='security_ir'):
    db, artifacts, *_ = seeded
    return ['--registry', str(db), '--artifact-root', str(artifacts), '--domain', domain,
        '--runtime-version', 'native_formula_v1', '--receipt', str(tmp_path / 'receipt.json')]


def test_anchor_rejects_a_different_native_domain(tmp_path, seeded):
    with pytest.raises(ValueError, match='anchor runtime differs'):
        cli.main(['anchor', '--version-id', seeded[3]['version_id'], '--output', str(tmp_path / 'anchor'),
                  *options(tmp_path, seeded, 'intent_ir')])
    assert not (tmp_path / 'anchor').exists()
    assert not (tmp_path / 'receipt.json').exists()


def test_full_child_anchor_registers_with_existing_exact_parent(tmp_path, seeded):
    db, artifacts, parent_result, parent, child_result, child = seeded
    anchor = exchange.stage_formula_anchor(child_result, tmp_path / 'anchor')
    assert cli.main(['register', '--manifest', anchor['manifest_path'], '--parent-version', parent['version_id'],
        '--output', str(tmp_path / 'received-candidate'), *options(tmp_path, seeded)]) == 0
    receipt = json.loads((tmp_path / 'receipt.json').read_text())
    assert receipt['version_id'] == child['version_id']
    assert not receipt['admitted'] and not receipt['qualified']
    with AutoencoderRegistry(db, artifacts) as owner:
        assert storage.load_registered_candidate(owner, receipt['version_id']) == child_result


def test_publish_child_anchor_dry_run_accepts_local_parent_context(tmp_path, seeded):
    anchor = exchange.stage_formula_anchor(seeded[4], tmp_path / 'anchor')
    assert cli.main(['publish', '--manifest', anchor['manifest_path'], '--parent-version', seeded[3]['version_id'],
                     *options(tmp_path, seeded)]) == 0
    receipt = json.loads((tmp_path / 'receipt.json').read_text())
    assert receipt['uploaded'] is False and receipt['formula_reference'] is None


def test_receive_never_downloads_without_flag(tmp_path, seeded):
    reference = tmp_path / 'reference.json'
    reference.write_text(json.dumps({'binding': {'domain_id': 'security_ir', 'runtime_version': 'native_formula_v1'}}))
    with pytest.raises(ValueError, match='explicit opt-in'):
        cli.main(['receive', '--reference', str(reference), '--kind', 'anchor', '--output', str(tmp_path / 'remote'),
                  *options(tmp_path, seeded)])
    assert not (tmp_path / 'remote').exists()
