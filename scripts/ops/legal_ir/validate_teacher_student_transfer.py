#!/usr/bin/env python3
"""Bounded 8D teacher -> 384D formula-head diagnostic with native local embeddings.

Teacher features remain 8D observations. Only screened compiler-produced formula
labels reach the student's explicit formula objective. No weight downloads,
context changes, publication, legal admission, or worker/service changes occur.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
TEACHER = Path('/home/barberb/portland-laws.github.io/ipfs_datasets_py/workspace/todo-queues/legal-ir-autoencoder-canonical.state.json')
TEACHER_SHA = '7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be'
FIXTURE = ROOT / 'tests/fixtures/logic/legacy_teacher_distillation.json'
FALSE = dict(admitted=False, formalized=False, roundtrip_ok=False, qualified=False,
             semantic_correctness_verified=False, independent_text_to_logic=False)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def write(path, value):
    with Path(path).open('xb') as stream:
        stream.write(raw(value))
    return dict(path=str(Path(path).absolute()), sha256=sha(path), bytes=Path(path).stat().st_size)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def source_hashes():
    base = ROOT / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer'
    files = [Path(__file__), FIXTURE]
    files.extend(base / name for name in ('legacy_teacher_distillation.py', 'modal_latent_formula.py',
        'modal_joint_formula.py', 'modal_joint_formula_schema.py', 'autoencoder_runtime_registry.py',
        'autoencoder_embedding_runtime.py', 'autoencoder_embedding_production.py', 'modal_autoencoder.py',
        'legal_samples.py', 'legal_formula_codec.py', 'autoencoder_lineages/_contract.py',
        'autoencoder_lineages/current_v2/__init__.py'))
    files.extend((base / 'autoencoder_lineages/legacy_v1').glob('*.py'))
    for folder in ('_snapshot', '_linguistic_snapshot', '_daemon_snapshot'):
        files.extend((base / 'autoencoder_lineages/legacy_v1' / folder).glob('*.py'))
        files.append(base / 'autoencoder_lineages/legacy_v1' / folder / 'MANIFEST.json')
    files.extend(ROOT / 'ipfs_datasets_py' / name for name in (
        'logic/deontic/utils/deontic_parser.py', 'logic/legal_ir/canonical_compiler.py',
        'logic/legal_ir/canonical_decompiler.py', 'logic/autoformal/__init__.py'))
    return {str(path): sha(path) for path in sorted(files)}


def produce_embeddings(directory, *, fixture_path=FIXTURE):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import SourceArtifact, SourceSpan
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_production import EmbeddingInput
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime import produce_native_embedding_receipt
    require_workspace_logic_tree()
    fixture_path = Path(fixture_path)
    fixture_sha = sha(fixture_path)
    fixture = json.loads(fixture_path.read_text())
    inputs, paths = [], {}
    (directory / 'sources').mkdir()
    for row in fixture['rows']:
        path = directory / 'sources' / (row['id'] + '.txt')
        path.write_bytes(row['text'].encode())
        digest, size = sha(path), path.stat().st_size
        paths[digest] = str(path.absolute())
        source = SourceSpan(SourceArtifact(digest, size), 'diagnostic', fixture['schema'], row['id'],
                            'en', 'authored diagnostic:' + row['id'], 0, size)
        inputs.append(EmbeddingInput(source, 'diagnostic', row['id'], row['text'], source.citation))
    resolver = lambda ref: paths[ref['sha256']]
    started = time.perf_counter()
    receipt = produce_native_embedding_receipt(inputs, resolver=resolver, batch_size=16)
    artifact = receipt.save(directory / 'embeddings.json', resolver=resolver)
    require(receipt.status_counts['embedded'] == len(inputs), 'all fixed diagnostic texts must embed without truncation')
    require(sha(fixture_path) == fixture_sha, 'fixture changed during embedding production')
    write(directory / 'embedding-production.json', dict(artifact=artifact, source_paths=paths,
        fixture_sha256=fixture_sha,
        elapsed_seconds=time.perf_counter() - started, verification=receipt.verification_summary(),
        source_kind='diagnostic', independently_reviewed_legal_gold=False, **FALSE))


def comparison(predictions, targets):
    expected = {row['id']: row['canonical_ir'] for row in targets}
    ids = [row['id'] for row in predictions['rows']]
    require(len(expected) == len(targets) == len(ids) and set(ids) == set(expected),
            'prediction IDs do not exactly cover the target split')
    rows = []
    for prediction in predictions['rows']:
        gold = expected[prediction['id']]
        actual = prediction['canonical_ir']
        fields = ('modality', 'actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
        facets = {field: bool(actual and actual['rules'][0][field] == gold['rules'][0][field]) for field in fields}
        rows.append(dict(sample_id=prediction['id'], status=prediction['status'],
            exact=actual == gold, facets=facets, expected_compiler_weak_label=gold,
            generated=actual, reason=prediction['reason']))
    return dict(sample_count=len(rows), exact_count=sum(row['exact'] for row in rows), rows=rows,
                target_origin='screened_compiler_weak_supervision', independent_semantic_accuracy=False, **FALSE)


def verify_fixture_inputs(data, fixture):
    """Join verified vectors to the exact fixture, including phase boundaries."""
    require(len(data['inputs']) == len(fixture) == len(data['results']), 'embedding row coverage differs')
    expected = {case['id']: case for case in fixture}
    require(len(expected) == len(fixture) and {item['section'] for item in data['inputs']} == set(expected),
            'embedding sections do not exactly cover fixture IDs')
    input_ids = [item['input_id'] for item in data['inputs']]
    require(len(set(input_ids)) == len(input_ids), 'duplicate embedding input IDs')
    for item, result in zip(data['inputs'], data['results']):
        case = expected[item['section']]
        citation = 'authored diagnostic:' + case['id']
        require(item['text'] == case['text'] and item['title'] == 'diagnostic'
                and item['citation'] == citation and item['source']['citation'] == citation
                and item['source']['document_id'] == case['id']
                and item['source']['source_kind'] == 'diagnostic'
                and item['source']['artifact']['sha256'] == hashlib.sha256(case['text'].encode()).hexdigest(),
                'verified embedding source differs from current fixture')
        require(item['input_id'] == result['input_id'] and result['status'] == 'embedded',
                'embedding result is missing or out of order')


def run(directory, *, epochs, teacher_path):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as embeddings
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_decoded_schema as schemas
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_teacher_distillation as transfer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.daemon_teacher import load_checkpoint as load_teacher
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_teacher import LegacyLinguisticTeacher
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_view_reuse import ViewReuseHistoricalDaemonAutoencoder

    started = time.perf_counter()
    pinned = require_workspace_logic_tree()
    sources = source_hashes()
    fixture = json.loads(FIXTURE.read_text())['rows']
    production = json.loads((directory / 'embedding-production.json').read_text())
    require(production['fixture_sha256'] == sha(FIXTURE), 'embedding fixture changed between phases')
    reference = production['artifact']
    resolver = lambda ref: production['source_paths'][ref['sha256']]
    receipt = embeddings.load_embedding_production_receipt(reference['path'], expected_sha256=reference['sha256'],
                expected_size_bytes=reference['bytes'], resolver=resolver)
    data = receipt.to_dict()
    require(data['producer']['code_sha256'] == sha(ROOT / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_runtime.py'),
            'embedding producer does not match the current pinned runtime')
    verify_fixture_inputs(data, fixture)
    vectors = {item['section']: embeddings._decode_vector(result['vector'])
               for item, result in zip(data['inputs'], data['results'])}
    require(data['execution']['kind'] == 'native', 'native local semantic embeddings required')
    before = teacher_path.stat()
    old = load_teacher(teacher_path, expected_sha256=TEACHER_SHA, compute_device='cpu')
    optimized = ViewReuseHistoricalDaemonAutoencoder(state=old.state, compute_device='cpu')
    optimized._checkpoint_identity = copy.deepcopy(old._checkpoint_identity)
    teacher = LegacyLinguisticTeacher(optimized)
    student_samples, teacher_rows, timing = [], [], []
    for case in fixture:
        options = dict(title='diagnostic', section=case['id'], text=case['text'], citation='authored diagnostic:' + case['id'])
        source = optimized.build_sample(**options)
        student = current_v2.build_sample(**options, embedding_vector=vectors[case['id']],
                    embedding_model=data['model']['model_id'] + '@' + data['model']['revision'])
        require(source.sample_id == student.sample_id, 'source IDs differ across explicitly built lineages')
        pairs = []
        for model in (old, optimized):
            tick = time.perf_counter()
            encoded = model.encode(source, use_sample_memory=False)
            pairs.append(dict(encoded=encoded, vector=model.decode(encoded), elapsed_seconds=time.perf_counter()-tick))
        require(pairs[0]['encoded'] == pairs[1]['encoded'] and pairs[0]['vector'] == pairs[1]['vector'], 'retained teacher view-reuse parity failed')
        timing.append(dict(id=case['id'], baseline_seconds=pairs[0]['elapsed_seconds'],
                           optimized_seconds=pairs[1]['elapsed_seconds'], exact=True))
        teacher_rows.append(teacher.distillation_row(source, corpus=case['corpus']))
        student_samples.append(student)
    artifact = write(directory / 'teacher-rows.json', teacher_rows)
    identity = optimized.describe()['linguistic_identity_sha256']
    prepared = {}
    for name, member in (('train','training'), ('tuning','tuning'), ('holdout','holdout'), ('train_excluded','excluded')):
        indices = [i for i,c in enumerate(fixture) if c['split']==member]
        forbidden = [s for s,c in zip(student_samples,fixture) if c['split'] in (
            ('training',) if name=='tuning' else ('training','tuning') if name=='holdout' else ())]
        prepared[name] = transfer.prepare_teacher_distillation(
            [student_samples[i] for i in indices], [teacher_rows[i] for i in indices],
            expected_teacher_identity_sha256=identity, expected_producer_sha256=teacher.producer_sha256,
            teacher_artifact_sha256=artifact['sha256'], split='train' if name=='train_excluded' else name,
            excluded_source_texts=[s.text for s in forbidden], excluded_sample_ids=[s.sample_id for s in forbidden])
        write(directory / (name+'-transfer.json'), prepared[name].receipt)
    require(len(prepared['train_excluded'].formula_targets)==0,'unsupported or Constitution targets reached training')
    train, targets = prepared['train'].training_inputs()
    tune, tune_targets = prepared['tuning'].training_inputs()
    holdout, holdout_targets = prepared['holdout'].training_inputs()
    require(len(train)==len(tune)==len(holdout)==4, 'fixed diagnostic split unexpectedly changed; retain dispositions')
    write(directory / 'student-samples.json', [s.to_dict() for s in student_samples])
    runtime = runtimes.open_runtime('legal_ir', 'current_v2', compute_device='cpu')
    core_before = raw(runtime.model.state.to_dict())
    initial = learning.build_checkpoint(joint._core_binding(runtime.model), joint._rows(runtime.model,train,targets),
        joint._rows(runtime.model,tune,tune_targets), learning_rate=.02, batch_size=4, hidden_size=32,
        token_embedding_dim=16, projection_width=8, seed=1729)
    runtime.model.attach_formula_checkpoint(initial)
    baseline = runtime.infer(holdout)
    trained = runtime.train(train, validation_samples=tune, formula_targets=targets,
        validation_formula_targets=tune_targets, epochs=epochs, max_seconds=120)
    require(trained['report']['training_executed'], 'no student optimizer steps executed')
    for group in ('projection', 'decoder'):
        evidence = trained['report']['parameter_evidence'][group]
        require(evidence['gradient_norm_max'] > 0 and evidence['parameter_update_l2'] > 0
                and evidence['initial_parameters_sha256'] != evidence['final_parameters_sha256'],
                'student parameter group did not receive an optimizer update: ' + group)
    require(trained['report']['formula_projection_gradient_norm_max'] > 0,
            'formula objective supplied no gradient to the residual projection')
    require(raw(runtime.model.state.to_dict())==core_before, 'formula training changed frozen sparse core')
    outputs = {name:runtime.infer(rows) for name,rows in [('training',train),('tuning',tune),('holdout',holdout)]}
    saved = runtime.model.save_formula_checkpoint(directory / 'student-formula.json')
    require(trained['report']['checkpoint_sha256'] == saved['sha256']
            and all(value['checkpoint_sha256'] == saved['sha256'] for value in outputs.values()),
            'training, predictions and saved head differ')
    resumed = runtimes.open_runtime('legal_ir','current_v2',compute_device='cpu',
                                   formula_checkpoint=saved['path'],formula_sha256=saved['sha256'])
    require(resumed.infer(holdout)==outputs['holdout'], 'formula save/reload changed predictions')
    generated_schema = schemas.validate_decoded_outputs(resumed, [train[0],holdout[0]],
                    output_directory=directory/'generated-schema',timeout_seconds=60)
    # Preserve the generated structures even when semantically wrong. A schema
    # build does not establish agreement with the source or the teacher label.
    require(generated_schema['schema_checks_complete'], 'generated output schema checks incomplete')
    require(generated_schema['checkpoint_sha256']==saved['sha256'], 'schema check used a different head')
    options=dict(validation_samples=tune,formula_targets=targets,validation_formula_targets=tune_targets,
                 epochs=1,max_seconds=60,max_optimizer_steps=1)
    continued=runtime.train(train,**options); restarted=resumed.train(train,**options)
    require(continued['checkpoint']==restarted['checkpoint'], 'formula resume diverged from uninterrupted step')
    resumed_artifact=runtime.model.save_formula_checkpoint(directory/'student-resumed-formula.json')
    require(source_hashes()==sources, 'producer sources changed during end-to-end validation')
    after=teacher_path.stat()
    require((before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns)
            and sha(teacher_path)==TEACHER_SHA, 'archived teacher checkpoint changed')
    report=dict(schema='legacy-teacher-current-student-transfer-diagnostic/v1', operational_ok=True,
        fixture_sha256=sha(FIXTURE), source_hashes=sources, resolved_logic_tree=pinned,
        elapsed_seconds=time.perf_counter()-started, peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        embedding_production=production, teacher_artifact=artifact, teacher_checkpoint_sha256=TEACHER_SHA,
        teacher_checkpoint_unchanged=True, teacher_prediction_parity=timing,
        transfer_receipts={k:v.receipt for k,v in prepared.items()}, teacher_vectors_used_as_student_inputs=False,
        baseline=comparison(baseline,holdout_targets), training=trained['report'],
        generation={name:comparison(outputs[name],values) for name,values in [('training',targets),('tuning',tune_targets),('holdout',holdout_targets)]},
        model_outputs=outputs, head_artifact=saved, reload_prediction_exact=True, resume_checkpoint_exact=True,
        resumed_head_artifact=resumed_artifact,
        generated_schema_checks=generated_schema, core_sparse_state_unchanged=True,
        training_scope='fresh frozen sparse core; residual projection and formula token head only',
        temporal_kind_sidecars_preserved=True, temporal_kind_sidecars_encoded_by_head=False,
        retained_teacher_trained=False, student_input_dimension=384, teacher_feature_dimension=8,
        bridge_names=[], legal_ir_target_count=0, legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1,
        metric_disk_cache=False, sample_memory=False, temperature=0, bridge_on_evaluate=None,
        heldout_semantic_qualification=False, full_logic_floor_coverage=False, **FALSE)
    write(directory/'report.json',report)
    print(json.dumps({'operational_ok':True,'seconds':report['elapsed_seconds'],
                      'exact_vs_weak_labels':{name:r['exact_count'] for name,r in report['generation'].items()},
                      'lake_build_count':generated_schema['lake_build_count'],**FALSE}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--phase',choices=('embeddings','validate','all'),default='all')
    parser.add_argument('--epochs',type=int,default=250)
    parser.add_argument('--retained-teacher',type=Path,default=TEACHER)
    args=parser.parse_args()
    require(1<=args.epochs<=1000,'epochs outside existing bound')
    os.environ['IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE']='0'
    os.environ['IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI']='0'
    os.environ['IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS']='0'
    directory=args.output_directory.resolve()
    if args.phase in ('all','embeddings'):
        directory.mkdir(parents=True,exist_ok=False)
        if args.phase=='embeddings':
            produce_embeddings(directory);return
        # Embedding producer changes process-wide network/thread settings; run
        # it in its own process and leave neural training/inference separate.
        directory.rmdir()
        subprocess.run([sys.executable,str(Path(__file__).resolve()),'--phase','embeddings',
                        '--output-directory',str(directory)],check=True,cwd=ROOT)
    run(directory,epochs=args.epochs,teacher_path=args.retained_teacher.resolve())


if __name__=='__main__':
    main()
