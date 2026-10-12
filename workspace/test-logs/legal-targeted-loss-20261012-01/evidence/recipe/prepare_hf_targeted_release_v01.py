"""Archive all four reviewed targeted-loss-curriculum cells under one additive prefix.

No numerical imports or checkpoint restoration. Raw saved model bytes stay
opaque here. Full ledger bodies and private shared-state snapshots are excluded.
Preparation is local; --snapshot-baseline is a read-only Hub metadata request.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

F = Path(__file__).resolve().parent
REPO = 'Publicus/legal-ir-autoencoder'
PREFIX = 'releases/20261012-targeted-loss-v1'
MAX_PAYLOAD_BYTES = 200000000
PUBLIC_RUNTIME = ('pre-admission.json', 'scheduler-adoption.json', 'lease-binding.json', 'command.json', 'child-identity.json', 'resource-observations.json', 'child-exit.json', 'group-rss-summary.json', 'owned-group-final.json', 'guardian-exit.json', 'lease-observations.jsonl', 'group-rss-observations.jsonl', 'child.log')

def require(condition, message):
    if not condition:
        raise ValueError(message)

def read(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'duplicate JSON key')
            value[key] = item
        return value
    def finite(raw):
        value = float(raw)
        require(math.isfinite(value), 'nonfinite JSON number')
        return value
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_float=finite, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))

def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(), 'physical absolute file required')
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

def write(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o444)

def write_json(path, value):
    write(path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode())

def checked_review(path):
    captured = pin(path)
    review = read(path)
    require(review.get('passed') is True and review.get('findings') == [], 'clean independent review required')
    require(type(review.get('artifacts')) is dict and bool(review['artifacts']), 'artifact bindings required')
    for name, expected in review['artifacts'].items():
        actual = pin(Path(name))
        require({key: actual[key] for key in ('bytes', 'sha256')} == expected, 'reviewed bytes changed')
    require(pin(path) == captured, 'independent review changed while checking')
    return review, captured

def identities(info):
    return {item.rfilename: dict(size=item.size, blob_id=item.blob_id, lfs=None if item.lfs is None else dict(sha256=item.lfs.sha256, size=item.lfs.size, pointer_size=item.lfs.pointer_size)) for item in info.siblings}

def snapshot_baseline():
    from huggingface_hub import HfApi
    info = HfApi().model_info(REPO, files_metadata=True)
    files = identities(info)
    require(not any(name.startswith(PREFIX+'/') for name in files), 'release prefix already exists')
    write_json(F/'hf-before-file-identities-v01.json', dict(repo=REPO, revision=info.sha, files=files))
    print(json.dumps(dict(status='baseline_metadata_saved', revision=info.sha, files=len(files))))

def main():
    manifest_path = F/'four-cell-output-freeze-v01.json'
    manifest_pin = pin(manifest_path)
    manifest = read(manifest_path)
    require(pin(manifest_path) == manifest_pin, 'freeze manifest changed while reading')
    result_review_path = F/'result-independent-review-v01.json'
    result_review, result_review_pin = checked_review(result_review_path)
    runtime_review_path = F/'runtime-independent-review-v01.json'
    runtime_review, runtime_review_pin = checked_review(runtime_review_path)
    helper_review_path = F/'hf-helper-source-independent-review-v01.json'
    helper_review, helper_review_pin = checked_review(helper_review_path)
    require(result_review['schema'] == 'targeted-loss-result-independent-review/v1', 'result review identity differs')
    require(runtime_review['schema'] == 'targeted-loss-runtime-independent-review/v1', 'runtime review identity differs')
    require(helper_review['schema'] == 'targeted-loss-Hub-helper-source-independent-review/v1', 'helper source review identity differs')
    require(manifest['schema'] == 'targeted-loss-four-cell-freeze/v1' and manifest['all_four_outputs_frozen'] is True, 'four-cell freeze required')
    expected_cells = {f'rank{r}-presence{p}' for r in (0,1) for p in (1,2)}
    require({row['cell']['id'] for row in manifest['cells']} == expected_cells and len(manifest['cells']) == 4, 'closed four cells required')
    all_results = {name: record for row in manifest['cells'] for name, record in row['results'].items()}
    require(all(result_review['artifacts'].get(name) == record for name, record in all_results.items()), 'all raw result inventories need independent review')
    approved = {}
    for review in (result_review, runtime_review, helper_review):
        for name, record in review['artifacts'].items():
            require(name not in approved or approved[name] == record, 'conflicting review source bindings')
            approved[name] = record
    for path, captured in ((result_review_path, result_review_pin), (runtime_review_path, runtime_review_pin), (helper_review_path, helper_review_pin)):
        approved[str(path)] = {key: captured[key] for key in ('bytes','sha256')}
    require(pin(manifest_path) == manifest_pin and approved.get(str(manifest_path)) == {key: manifest_pin[key] for key in ('bytes','sha256')}, 'freeze manifest needs independent binding')
    root = F/'hf-upload-v01'
    require(not root.exists(), 'immutable new upload root required')
    root.mkdir()
    upload = root/PREFIX
    upload.mkdir(parents=True)
    entries = {}
    def copy(source, relative):
        source = Path(source)
        require('private-runtime-snapshots' not in source.parts and source.name not in ('resources-start.json','resources-final.json','disk-reservations.json'), 'private global record bodies excluded')
        require(not source.is_symlink(), 'symlink source prohibited')
        require(approved.get(str(source)) == {key: pin(source)[key] for key in ('bytes','sha256')}, 'every copied source needs explicit independent provenance')
        target = upload/relative
        require(target.resolve().is_relative_to(upload.resolve()) and not target.exists(), 'unique bounded upload target required')
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = source.read_bytes()
        require(approved.get(str(source)) == dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()), 'copied bytes must equal the independently approved source')
        require(len(raw) < 10000000, 'single public artifact must stay below10MB to avoid implicit root LFS changes; a larger file needs a separately reviewed recipe')
        require(sum(record['bytes'] for record in entries.values())+len(raw) <= MAX_PAYLOAD_BYTES, 'payload byte cap exceeded')
        write(target, raw)
        require(pin(source)['sha256'] == hashlib.sha256(raw).hexdigest(), 'source changed while copying')
        entries[target.relative_to(root).as_posix()] = pin(target)
    for row in manifest['cells']:
        cell = row['cell']['id']
        for key in ('plan','summary','guardian_terminal','pre_admission'):
            require(pin(Path(row[key]['path'])) == row[key], 'frozen descriptor changed')
            require(approved.get(row[key]['path']) == {part: row[key][part] for part in ('bytes','sha256')}, 'frozen descriptor needs independent provenance')
        plan = read(row['plan']['path'])
        summary = read(row['summary']['path'])
        terminal = read(row['guardian_terminal']['path'])
        pre = read(row['pre_admission']['path'])
        require(plan['cell'] == summary['cell'] == row['cell'] and plan['attempt_name'] == summary['attempt_name'] == 'targeted-loss-20261012-'+cell+'-01', 'cell/plan/summary/attempt identity differs')
        require(Path(row['summary']['path']).parent == Path(row['guardian_terminal']['path']).parent/'results', 'exact attempt result root required')
        require(Path(row['guardian_terminal']['path']).parent.name == plan['attempt_name'], 'physical attempt differs')
        require(pre['plan'] == row['plan'] and pre['runner'] == pin(F/'run_targeted_loss.py') and pre['guardian'] == pin(F/'run_scope_guardian.py'), 'actual admitted source binding differs')
        require(summary['status'] == 'completed' and summary['actual_new_updates'] == 32 and summary['actual_encoder_calls'] == 0 and summary['latent_enabled'] is False, 'successful source-only 32-update cell required')
        require(type(terminal['returncode']) is int and terminal['returncode'] == 0 and terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True, 'successful durable released terminal required')
        require(runtime_review['artifacts'].get(row['guardian_terminal']['path']) == {key: row['guardian_terminal'][key] for key in ('bytes','sha256')}, 'terminal runtime review binding required')
        for name, expected in sorted(row['results'].items()):
            require({key: pin(Path(name))[key] for key in ('bytes','sha256')} == expected, 'frozen result changed')
            copy(name, 'cells/'+cell+'/results/'+Path(name).name)
        copy(row['plan']['path'], 'cells/'+cell+'/plan.json')
        attempt = Path(row['guardian_terminal']['path']).parent
        require(pin(Path(pre['review']['path'])) == pre['review'], 'actual training review changed')
        copy(pre['review']['path'], 'cells/'+cell+'/training-protocol-review.json')
        for name in PUBLIC_RUNTIME:
            require((attempt/name).is_file(), 'closed public runtime inventory missing')
            require(runtime_review['artifacts'].get(str(attempt/name)) == {key: pin(attempt/name)[key] for key in ('bytes','sha256')}, 'every public runtime wrapper needs actual runtime review')
            copy(attempt/name, 'cells/'+cell+'/runtime/'+name)
    for name in ('four-cell-output-freeze-v01.json','targeted-result-analysis-v01.json','result-independent-review-v01.json','runtime-independent-review-v01.json','registration-v01.json','training-export-v01.json','authored-reference-packet-v01.json','root-science-source-independent-review-v01.json','trainer-source-independent-review-v01.json','corpus-source-independent-review-v01.json','combined-pure-tests-v02.xml','combined-pure-tests-v02.log','combined-pure-tests-observation-v01.json'):
        copy(F/name, 'evidence/'+name)
    for name in ('run_targeted_loss.py','prepare_targeted_loss.py','run_scope_guardian.py','analyze_targeted_results_v01.py','prepare_hf_targeted_release_v01.py','publish_hf_targeted_release_v01.py','freeze_four_cell_outputs_v01.py','review_targeted_cell.py','audit_targeted_terminal_v02.py'):
        copy(F/name, 'recipe/'+name)
    for relative in ('ipfs_datasets_py/logic/legal_ir/targeted_loss_curriculum.py','ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_targeted_loss.py','tests/unit/logic/legal_ir/test_targeted_loss_curriculum.py','tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_targeted_loss_contracts.py'):
        copy(F/'datasets'/relative, 'source/'+relative)
    copy(F/'targeted-loss-curriculum-model-card-v01.md','README.md')
    release = dict(schema='targeted-loss-curriculum-Hub-release-manifest/v1', repository=REPO, release_prefix=PREFIX, cells=sorted(expected_cells), actual_new_updates=128, dimension=384, latent_enabled=False, actual_encoder_calls=0, same_original_parent_model_sha256='54e745f0dc75a79c11828048ad5deb44b0f07dcac5b9083bde17948b5206bfcb', fresh_Adam_per_cell=True, independent_statutory_gold=False, semantic_accuracy=None, default_promotion=False, Lake_executed=False, all_four_retained=True, sources={name: record for name, record in entries.items()})
    write_json(upload/'release-manifest.json', release)
    entries[(upload/'release-manifest.json').relative_to(root).as_posix()] = pin(upload/'release-manifest.json')
    baseline = read(F/'hf-before-file-identities-v01.json')
    require(baseline['repo'] == REPO and not any(name.startswith(PREFIX+'/') for name in baseline['files']), 'baseline identity differs')
    total = sum(record['bytes'] for record in entries.values())
    require(total <= MAX_PAYLOAD_BYTES and len(entries) <= 1000, 'payload bounds exceeded')
    write_json(F/'hf-preparation-receipt-v01.json', dict(schema='targeted-loss-curriculum-Hub-preparation/v1', repository=REPO, release_prefix=PREFIX, expected_parent_revision=baseline['revision'], upload_root=str(root), complete_upload_files=entries, payload_files=len(entries), payload_bytes=total, baseline_pin=pin(F/'hf-before-file-identities-v01.json'), result_review=pin(result_review_path), runtime_review=pin(runtime_review_path), helper_review=pin(helper_review_path), freeze_manifest=pin(manifest_path), default_promotion=False, additive_only=True))
    print(json.dumps(dict(status='prepared_only', files=len(entries), bytes=total)))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-baseline', action='store_true')
    args = parser.parse_args()
    snapshot_baseline() if args.snapshot_baseline else main()
