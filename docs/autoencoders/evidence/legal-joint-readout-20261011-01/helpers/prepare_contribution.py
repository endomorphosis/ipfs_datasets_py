"""Copy a closed pinned inventory into source/root evidence, without weights or ledgers."""
import hashlib
import json
from pathlib import Path
import shutil

F = Path(__file__).resolve().parent
D, W = F / 'datasets', F / 'workspace'


def pin(path):
    path = Path(path)
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    inventory_path = F / 'contribution-copy-inputs.json'
    inventory_pin = pin(inventory_path)
    declared = json.loads(inventory_path.read_bytes())
    assert declared['schema'] == 'joint-readout-contribution-inputs/v1'
    assert 1 <= len(declared['entries']) <= 256
    evidence = D / 'docs/autoencoders/evidence/legal-joint-readout-20261011-01'
    assert not evidence.exists()
    evidence.mkdir(parents=True)
    copied, observed = {}, {}
    for entry in declared['entries']:
        assert set(entry) == {'relative', 'pin', 'role'}
        relative = Path(entry['relative'])
        source = Path(entry['pin']['path'])
        assert not relative.is_absolute() and '..' not in relative.parts and str(relative) not in copied
        assert entry['role'] in ('owned_receipt', 'owned_attempt', 'raw_source_view', 'prior_baseline_receipt', 'helper')
        assert source.is_file() and not source.is_symlink() and source.stat().st_size <= 2 * 1024**2
        assert not any(text in source.name for text in ('checkpoint-', 'selected-state', 'disk-reservations', '.local.json'))
        before = pin(source)
        assert before == entry['pin']
        target = evidence / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(source.read_bytes())
        retained = pin(target)
        assert all(retained[key] == before[key] for key in ('bytes', 'sha256'))
        assert pin(source) == before
        copied[str(relative)] = {'origin': before, 'retained': retained, 'role': entry['role']}
        observed[str(source)] = before
    assert all(pin(path) == value for path, value in observed.items())
    assert pin(inventory_path) == inventory_pin
    inventory_target = evidence / 'receipts/contribution-copy-inputs.json'
    with inventory_target.open('xb') as stream:
        stream.write(inventory_path.read_bytes())
    assert all(pin(inventory_target)[key] == inventory_pin[key] for key in ('bytes', 'sha256'))
    copied['receipts/contribution-copy-inputs.json'] = {'origin': inventory_pin, 'retained': pin(inventory_target), 'role': 'owned_receipt'}
    manifest = {'schema': 'legal-joint-readout-evidence-manifest/v1', 'files': copied,
                'input_inventory': inventory_pin, 'closing_source_pins_match': True,
                'weights_in_source_evidence': False, 'full_shared_ledgers_in_evidence': False,
                'requested_dispositions': 64, 'physical_sources': 8, 'all_previously_exposed': True,
                'joint_selected_instances': 48, 'original_selected_instances': 8,
                'original_decoder_row_payloads_preserved': 64, 'optimizer_updates': 0, 'new_encoder_calls': 0,
                'human_labels': 0, 'semantic_accuracy': None, 'semantic_gain_established': False,
                'Lake_executed': False, 'proof_authority': False, 'default_promotion': False,
                'qualification': False, 'standalone_numeric_environment_promised': False}
    with (evidence / 'manifest.json').open('x') as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True); stream.write('\n')
    document_pin = pin(F / 'contribution.md')
    source_document = D / 'docs/autoencoders/legal_joint_readout_20261011.md'
    assert not source_document.exists()
    shutil.copyfile(F / 'contribution.md', source_document)
    assert pin(F / 'contribution.md') == document_pin
    assert pin(source_document)['sha256'] == document_pin['sha256']
    mirror = W / 'artifacts/legal-joint-readout-20261011-01/evidence'
    assert not mirror.exists()
    shutil.copytree(evidence, mirror)
    source_files = {str(path.relative_to(evidence)): pin(path) for path in evidence.rglob('*') if path.is_file()}
    mirror_files = {str(path.relative_to(mirror)): pin(path) for path in mirror.rglob('*') if path.is_file()}
    assert set(source_files) == set(mirror_files)
    assert all(all(source_files[path][key] == mirror_files[path][key] for key in ('bytes', 'sha256')) for path in source_files)
    root_document = W / 'implementation_plan/docs/74-legal-joint-readout-2026-10-11.md'
    assert not root_document.exists()
    root_document.parent.mkdir(parents=True, exist_ok=True)
    text = (F / 'contribution.md').read_text().replace('evidence/legal-joint-readout-20261011-01/manifest.json',
            '../../artifacts/legal-joint-readout-20261011-01/evidence/manifest.json')
    with root_document.open('x') as stream:
        stream.write(text)
    assert pin(F / 'contribution.md') == document_pin
    assert pin(inventory_path) == inventory_pin
    assert all(pin(inventory_target)[key] == inventory_pin[key] for key in ('bytes', 'sha256'))
    assert all(pin(path) == value for path, value in observed.items())
    value = {'schema': 'joint-readout-contribution-copy-receipt/v1', 'passed': True, 'findings': [],
             'files_in_each_evidence_bundle': len(copied) + 1, 'source_document_pin': pin(source_document),
             'root_document_pin': pin(root_document), 'manifest_pin': pin(evidence / 'manifest.json'),
             'all_opening_and_closing_pins_match': True, 'inventory_pin': inventory_pin}
    with (F / 'contribution-copy-receipt.json').open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True); stream.write('\n')
    print(json.dumps(value))


if __name__ == '__main__':
    main()
