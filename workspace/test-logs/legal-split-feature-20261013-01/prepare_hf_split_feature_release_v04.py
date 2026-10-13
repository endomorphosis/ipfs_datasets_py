"""Prepare an additive, independently reviewed source-only split-feature release.

No models are restored and checkpoint JSON stays opaque. Preparation is local;
--snapshot-baseline alone performs a read-only Hub metadata request. Private
shared ledger/scheduler bodies and the16MB hybrid analysis are excluded.
"""
import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path

F = Path(__file__).resolve().parent
REPO = 'Publicus/legal-ir-autoencoder'
PREFIX = 'releases/20261013-split-feature-v1'
MAX_PAYLOAD_BYTES = 200000000
MAX_FILE_BYTES = 10000000
READ_PINS = {}
PUBLIC_RUNTIME = ('pre-admission.json', 'scheduler-adoption.json', 'lease-binding.json', 'command.json',
 'child-identity.json', 'resource-observations.json', 'child-exit.json', 'group-rss-summary.json',
 'owned-group-final.json', 'guardian-exit.json', 'lease-observations.jsonl', 'group-rss-observations.jsonl', 'child.log')
EVIDENCE = ('split-feature-output-freeze-v01.json', 'split-feature-result-analysis-v01.json',
 'result-independent-review-v01.json', 'runtime-independent-review-v01.json', 'registration-v01.json',
 'training-export-v01.json', 'root-science-source-independent-review-v01.json',
 'trainer-source-independent-review-v01.json', 'terminal-copy-freeze-source-independent-review-v02.json',
 'combined-pure-tests-v01.xml',
 'combined-pure-tests-v01.log', 'combined-pure-tests-observation-v01.json', 'split-feature-evaluation-contract-v01.json',
 'saved-score-hybrid-source-independent-review-v02.json', 'split-feature-gaps-v01.md',
 'hf-helper-source-independent-review-v02.json')
RECIPES = ('run_split_features.py', 'prepare_split_features.py', 'run_scope_guardian.py',
 'review_split_cell_v03.py', 'capture_split_terminal_v01.py',
 'freeze_split_outputs_v02.py', 'audit_split_terminal_v01.py', 'analyze_saved_score_hybrid_v02.py',
 'prepare_hf_split_feature_release_v04.py', 'publish_hf_split_feature_release_v04.py')
SOURCE_FILES = ('ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_split_features.py',
 'tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_split_features_contracts.py')

def require(condition, message):
    if not condition:
        raise ValueError(message)

def brief(record):
    require(type(record) is dict and set(record) in ({'bytes', 'sha256'}, {'path', 'bytes', 'sha256'}),
            'closed raw identity required')
    require(type(record['bytes']) is int and 0 <= record['bytes'] <= MAX_PAYLOAD_BYTES
            and type(record['sha256']) is str and len(record['sha256']) == 64
            and all(c in '0123456789abcdef' for c in record['sha256']), 'bounded raw identity required')
    return {k: record[k] for k in ('bytes', 'sha256')}

def pin(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and path.is_file() and not path.is_symlink(),
            'exact physical absolute file required')
    before = path.stat()
    require(before.st_size <= MAX_PAYLOAD_BYTES, 'raw input byte cap exceeded')
    raw = path.read_bytes(); after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(raw) == before.st_size,
            'file changed during raw pin')
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

def read(path, expected=None):
    path = Path(path)
    require('checkpoint' not in path.name and 'reference-packet' not in path.name,
            'checkpoint/reference JSON parsing prohibited')
    captured = pin(path)
    require(expected is None or captured == expected, 'consumed metadata differs from required descriptor')
    raw = path.read_bytes()
    require(brief(captured) == dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) and pin(path) == captured,
            'consumed metadata bytes differ from opening pin')
    require(str(path) not in READ_PINS or READ_PINS[str(path)] == captured, 'previous parsed identity changed')
    READ_PINS[str(path)] = captured
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key'); result[key] = value
        return result
    def finite(raw):
        result = float(raw); require(math.isfinite(result), 'nonfinite JSON number'); return result
    return json.loads(raw, object_pairs_hook=unique, parse_float=finite,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

def write(path, raw):
    path = Path(path)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    path.chmod(0o444)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return pin(path)

def write_json(path, value):
    return write(path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode())

def approved_map(review):
    require((review.get('passed') is True or review.get('status') == 'PASS') and review.get('findings') == [],
            'clean independent review required')
    require(type(review.get('artifacts')) is dict and review['artifacts'], 'raw review artifact map required')
    result = {}
    for path, expected in review['artifacts'].items():
        require(type(path) is str and ('path' not in expected or expected['path'] == path), 'review path identity differs')
        result[path] = brief(expected)
        require(brief(pin(path)) == result[path], 'independently reviewed source bytes changed')
    return result

def checked_review(path, schema):
    captured = pin(path); review = read(path, captured)
    require(review['schema'] == schema, 'independent review schema differs')
    approved = approved_map(review)
    require(pin(path) == captured, 'independent review changed while checking')
    return review, captured, approved

def fence(approved):
    for path, expected in approved.items():
        require(brief(pin(path)) == expected, 'closing approved source identity changed')
    for path, expected in READ_PINS.items():
        require(pin(path) == expected, 'closing consumed metadata identity changed')

def identities(info):
    result = {}
    for item in info.siblings:
        require(item.rfilename not in result, 'duplicate Hub sibling path')
        result[item.rfilename] = dict(size=item.size, blob_id=item.blob_id,
            lfs=None if item.lfs is None else dict(sha256=item.lfs.sha256, size=item.lfs.size, pointer_size=item.lfs.pointer_size))
    return result

def expected_names():
    names = {'cell-checkpoint.json', 'cell-training.json', 'data-schedule-before-models.json', 'summary.json', 'trained-modality-retention.json'}
    for stage in ('initial', 'trained'):
        names.add(stage+'-parity.json')
        names.update(stage+'-parity-'+control+'.json' for control in ('zeros','alternate_placeholders','disabled','rotated_placeholders'))
    for state in ('baseline','trained'):
        for panel in ('old_tune','fresh_tune','fresh_challenge','old_authored_eval','authored_dev','authored_eval','law'):
            names.update(state+'-'+panel+'-'+kind+'.json' for kind in ('raw','joint'))
            if panel not in ('authored_eval','law'): names.add(state+'-'+panel+'-score.json')
    require(len(names) == 53, 'closed53 result population required')
    return names

def qualified_analyzer(analysis, approved, result_review):
    require(analysis['schema'] == 'split-feature-exposed-result-analysis/v1' and analysis['passed'] is True
            and analysis['findings'] == [], 'clean independently reviewed actual analysis required')
    source = analysis['analyzer']; approval = analysis['independent_source_review']
    for descriptor, pattern in ((source, r'analyze_split_feature_results_v[0-9]{2}\.py'),
                                (approval, r'split-feature-analyzer-source-independent-review-v[0-9]{2}\.json')):
        path = Path(descriptor['path'])
        require(set(descriptor) == {'path','bytes','sha256'} and path.parent == F and path.resolve() == path
                and re.fullmatch(pattern,path.name) is not None and pin(path) == descriptor,
                'exact owned analyzer producer or approval descriptor required')
        require(approved.get(str(path)) == brief(descriptor)
                and str(path) in result_review['artifacts']
                and brief(result_review['artifacts'][str(path)]) == brief(descriptor),
                'actual analyzer and approval need independent result-review raw provenance')
    review = read(approval['path'], approval)
    require(review['schema'] == 'split-feature-analyzer-source-independent-review/v1' and review['passed'] is True
            and review['findings'] == [] and review['analyzer'] == source,
            'actual analysis must join its exact clean source qualification')
    for path, expected in approved_map(review).items():
        require(approved.get(path) == expected, 'source qualification closure absent from approved payload provenance')
    return source, approval

def snapshot_baseline():
    from huggingface_hub import HfApi
    info = HfApi().model_info(REPO, files_metadata=True)
    files = identities(info)
    require(type(info.sha) is str and files and not any(name.startswith(PREFIX+'/') for name in files),
            'nonempty original Hub tree and absent release prefix required')
    write_json(F/'hf-before-file-identities-v01.json', dict(repo=REPO, revision=info.sha, files=files))
    print(json.dumps(dict(status='baseline_metadata_saved', revision=info.sha, files=len(files))))

def main():
    manifest_path = F/'split-feature-output-freeze-v01.json'; manifest_pin = pin(manifest_path)
    manifest = read(manifest_path, manifest_pin)
    reviews = [
        ('result_review', F/'result-independent-review-v01.json', 'split-feature-result-independent-review/v1'),
        ('runtime_review', F/'runtime-independent-review-v01.json', 'split-feature-runtime-independent-review/v1'),
        ('helper_review', F/'hf-helper-source-independent-review-v02.json', 'split-feature-Hub-helper-source-independent-review/v1')]
    approved = {}; review_pins = {}; review_values = {}
    for key, path, schema in reviews:
        value, captured, scope = checked_review(path, schema)
        review_values[key] = value; review_pins[key] = captured
        for name, expected in {**scope, str(path): brief(captured)}.items():
            require(name not in approved or approved[name] == expected, 'conflicting approved source identities')
            approved[name] = expected
    require(approved.get(str(manifest_path)) == brief(manifest_pin), 'freeze manifest needs independent raw binding')
    require(manifest['schema'] == 'split-feature-output-freeze/v1' and manifest['all_outputs_frozen'] is True
            and manifest['authorizes_authored_eval_scoring'] is True and manifest['new_trained_outputs_scored_before_freeze'] is False,
            'reviewed frozen single-cell outputs required')
    require(type(manifest['cells']) is list and len(manifest['cells']) == 1, 'singleton release cell required')
    row = manifest['cells'][0]
    require(row['cell'] == dict(id='split-features',trainable_parameter_policy='split-features',actor_ranking_enabled=False,
            presence_ce_weight=1,modality_loss_weight=2), 'closed split feature objective required')
    results_root = Path(row['summary']['path']).parent
    require(set(Path(name).name for name in row['results']) == expected_names() and len(row['results']) == 53
            and all(Path(name).parent == results_root for name in row['results']), 'exact frozen53 physical result paths required')
    require(all(review_values['result_review']['artifacts'].get(name) is not None and
            brief(review_values['result_review']['artifacts'][name]) == brief(record)
            for name, record in row['results'].items()), 'every raw result needs independent result review')
    consumed = {}
    for key in ('plan','summary','guardian_terminal','pre_admission'):
        descriptor = row[key]
        require(approved.get(descriptor['path']) == brief(descriptor), 'frozen descriptor needs independent provenance')
        consumed[key] = read(descriptor['path'], descriptor)
    plan, summary, terminal, pre = (consumed[key] for key in ('plan','summary','guardian_terminal','pre_admission'))
    require(brief(READ_PINS[row['summary']['path']]) == brief(row['results'][row['summary']['path']]), 'parsed summary differs from frozen result inventory')
    require(plan['cell'] == summary['cell'] == row['cell'] and plan['attempt_name'] == summary['attempt_name']
            == 'split-feature-20261013-split-features-01', 'matched cell/attempt differs')
    attempt = Path(row['guardian_terminal']['path']).parent
    require(results_root == attempt/'results' and attempt.name == plan['attempt_name'], 'exact physical attempt root required')
    require(pre['plan'] == row['plan'] and pre['runner'] == pin(F/'run_split_features.py')
            and pre['guardian'] == pin(F/'run_scope_guardian.py'), 'actual admission source identity differs')
    require(summary['status'] == 'completed' and summary['actual_new_updates'] == 32 and summary['actual_encoder_calls'] == 0
            and summary['actual_encoder_calls_scope'] == 'external_latent_or_context_encoders' and summary['latent_enabled'] is False
            and summary['initial_parent_head_parity']['total_source_rows'] == 392
            and summary['initial_parent_head_parity']['all_four_heads_and_tokens_exact'] is True
            and summary['initial_parent_head_parity']['checked_before_training'] is True, 'completed32 with initial392 source parity required')
    partition = summary['parameter_partition']
    require(len(partition['model_parameter_names']) == 34 and len(partition['trainable_parameter_names']) == 17
            and len(partition['frozen_parameter_names']) == 17 and len(partition['optimizer_parameter_order']) == 17
            and set(partition['optimizer_parameter_order']) == set(partition['trainable_parameter_names']), 'closed34/17/17 parameter partition required')
    require(type(terminal['returncode']) is int and type(terminal['child_returncode']) is int
            and terminal['returncode'] == terminal['child_returncode'] == 0 and terminal['artifacts_durable'] is True
            and terminal['resource_reservation_released'] is True, 'successful durable released terminal required')
    require(brief(review_values['runtime_review']['artifacts'][row['guardian_terminal']['path']]) == brief(row['guardian_terminal']), 'actual terminal needs runtime review')
    require(approved.get(pre['review']['path']) == brief(pre['review']),
            'parsed training protocol review must match independently approved identity')
    read(pre['review']['path'], pre['review'])
    baseline_path = F/'hf-before-file-identities-v01.json'; baseline_pin = pin(baseline_path)
    baseline = read(baseline_path, baseline_pin)
    require(baseline['repo'] == REPO and type(baseline['revision']) is str and baseline['files']
            and not any(name.startswith(PREFIX+'/') for name in baseline['files']), 'absent additive release prefix required')
    analysis_path = F/'split-feature-result-analysis-v01.json'; analysis_pin = pin(analysis_path)
    require(approved.get(str(analysis_path)) == brief(analysis_pin), 'actual analysis must be independently raw bound')
    analysis = read(analysis_path, analysis_pin)
    analyzer_source, analyzer_review = qualified_analyzer(analysis, approved, review_values['result_review'])
    fence(approved)
    root = F/'hf-upload-v01'; require(not os.path.lexists(root), 'exclusive new upload root required'); root.mkdir(mode=0o700)
    upload = root/PREFIX; upload.mkdir(parents=True)
    entries = {}
    def copy(source, relative):
        source = Path(source)
        require('private-runtime-snapshots' not in source.parts and source.name not in
                ('resources-start.json','resources-final.json','disk-reservations.json','saved-score-hybrid-analysis-v01.json'), 'private bodies/full hybrid excluded')
        captured = pin(source)
        require(approved.get(str(source)) == brief(captured), 'every public artifact requires independent raw provenance')
        require(str(source) not in READ_PINS or READ_PINS[str(source)] == captured, 'parsed/copied source identity differs')
        require(captured['bytes'] < MAX_FILE_BYTES, 'single public artifact must stay below10MB')
        target = upload/relative
        require(target.resolve().is_relative_to(upload.resolve()) and not os.path.lexists(target), 'unique bounded upload target required')
        raw = source.read_bytes()
        require(brief(captured) == dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) and pin(source) == captured,
                'copied bytes differ from captured approved source')
        require(sum(record['bytes'] for record in entries.values())+len(raw) <= MAX_PAYLOAD_BYTES, 'payload byte cap exceeded')
        target.parent.mkdir(parents=True,exist_ok=True); write(target, raw)
        entries[target.relative_to(root).as_posix()] = pin(target)
    for name, expected in sorted(row['results'].items()):
        require(brief(pin(name)) == brief(expected), 'frozen raw result changed')
        copy(name, 'cells/split-features/results/'+Path(name).name)
    copy(row['plan']['path'], 'cells/split-features/plan.json')
    copy(pre['review']['path'], 'cells/split-features/training-protocol-review.json')
    for name in PUBLIC_RUNTIME:
        path = attempt/name
        require(brief(review_values['runtime_review']['artifacts'][str(path)]) == brief(pin(path)), 'public runtime wrapper needs actual runtime review')
        copy(path, 'cells/split-features/runtime/'+name)
    for name in EVIDENCE: copy(F/name, 'evidence/'+name)
    for name in RECIPES: copy(F/name, 'recipe/'+name)
    copy(analyzer_source['path'], 'recipe/'+Path(analyzer_source['path']).name)
    copy(analyzer_review['path'], 'evidence/'+Path(analyzer_review['path']).name)
    for relative in SOURCE_FILES: copy(F/'datasets'/relative, 'source/'+relative)
    copy(F/'split-feature-model-card-v01.md', 'README.md')
    release = dict(schema='split-feature-Hub-release-manifest/v1',repository=REPO,release_prefix=PREFIX,cells=['split-features'],
        actual_new_updates=32,dimension=384,latent_enabled=False,actual_external_latent_encoder_calls=0,feature_paths_per_source_model_forward=2,
        same_original_parent_model_sha256=summary['same_original_parent_model_sha256'],fresh_Adam=True,inherited_optimizer_moments=False,
        model_tensors=34,trainable_tensors=17,frozen_tensors=17,initial_parent_head_score_rows=392,
        equal_compute_budget_claimed=False,independent_statutory_gold=False,semantic_accuracy=None,default_promotion=False,Lake_executed=False,
        full_hybrid_analysis_uploaded=False,private_global_bodies_uploaded=False,actual_analyzer=analyzer_source,
        actual_analyzer_source_review=analyzer_review,sources=entries.copy())
    release_pin = write_json(upload/'release-manifest.json', release)
    entries[(upload/'release-manifest.json').relative_to(root).as_posix()] = release_pin
    total = sum(record['bytes'] for record in entries.values())
    require(total <= MAX_PAYLOAD_BYTES and len(entries) <= 1000 and all(record['bytes'] < MAX_FILE_BYTES for record in entries.values()), 'complete payload bounds exceeded')
    fence(approved)
    for name, expected in entries.items(): require(pin(root/name) == expected, 'prepared payload identity changed')
    write_json(F/'hf-preparation-receipt-v01.json',dict(schema='split-feature-Hub-preparation/v1',repository=REPO,release_prefix=PREFIX,
        expected_parent_revision=baseline['revision'],upload_root=str(root),complete_upload_files=entries,payload_files=len(entries),payload_bytes=total,
        baseline_pin=baseline_pin,freeze_manifest=manifest_pin,approved_source_artifacts=approved,**review_pins,default_promotion=False,additive_only=True))
    print(json.dumps(dict(status='prepared_only',files=len(entries),bytes=total)))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--snapshot-baseline',action='store_true')
    args=parser.parse_args();snapshot_baseline() if args.snapshot_baseline else main()
