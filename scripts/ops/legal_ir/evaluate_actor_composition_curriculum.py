#!/usr/bin/env python3
"""Fixed-budget actor/template data ablation with separate fitting/evaluation.

Uses verified offline 384D embeddings and shared screened compiler weak labels.
No historical teacher weights are loaded or changed. A manifest seals sources,
splits and settings before either model trains; both heads are frozen before
evaluation labels are opened. All qualification flags remain false.
"""
from __future__ import annotations

import argparse
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
from scripts.ops.legal_ir import validate_teacher_student_transfer as shared

PANEL = ROOT / 'tests/fixtures/logic/actor_composition_panel.json'
BASE = ROOT / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer'
ARMS = ('confounded_diagonal', 'balanced')
EXPOSED_PAIRS = [('officer', 'disclose'), ('agency', 'retain'),
                 ('Company A', 'disclose'), ('officer', 'submit')]
OPTIONS = dict(learning_rate=.02, batch_size=6, hidden_size=32,
               token_embedding_dim=16, projection_width=8, seed=1729)
FALSE = dict(shared.FALSE, proof_authority=False, promotion_performed=False)
require, sha, raw, write = shared.require, shared.sha, shared.raw, shared.write


def sources():
    hashes = shared.source_hashes()
    for path in (Path(__file__), PANEL, BASE/'formula_curriculum.py', BASE/'formula_generation_metrics.py'):
        hashes[str(path)] = sha(path)
    return hashes


def panel():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_curriculum import load_curriculum
    old = json.loads(shared.FIXTURE.read_text())
    return load_curriculum(PANEL, expected_file_sha256=sha(PANEL),
        excluded_source_texts=[row['text'] for row in old['rows']],
        excluded_evaluation_actor_actions=EXPOSED_PAIRS)


def read_reference(ref):
    path = Path(ref['path'])
    require(path.stat().st_size == ref['bytes'] and sha(path) == ref['sha256'], 'artifact changed: ' + str(path))
    return json.loads(path.read_text())


def reference(path):
    return dict(path=str(path.resolve()), sha256=sha(path), bytes=path.stat().st_size)


def load_plan(directory):
    plan = json.loads((directory/'plan.json').read_text())
    require(plan['source_hashes'] == sources(), 'producer source changed after plan was sealed')
    require(plan['panel_manifest_sha256'] == panel().manifest_sha256, 'panel changed after plan was sealed')
    require(plan['formula_options'] == OPTIONS and plan['arms'] == list(ARMS), 'experiment settings changed')
    return plan


def native_samples(directory, prepared_panel):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as embeddings
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2
    production = json.loads((directory/'embedding-production.json').read_text())
    require(production['fixture_sha256'] == sha(PANEL), 'embeddings belong to a different panel')
    ref = production['artifact']
    receipt = embeddings.load_embedding_production_receipt(ref['path'], expected_sha256=ref['sha256'],
        expected_size_bytes=ref['bytes'], resolver=lambda value: production['source_paths'][value['sha256']])
    data = receipt.to_dict()
    require(data['execution']['kind'] == 'native', 'verified native embeddings required')
    require(data['producer']['code_sha256'] == sha(BASE/'autoencoder_embedding_runtime.py'), 'embedding producer differs')
    rows = prepared_panel.manifest['rows']
    shared.verify_fixture_inputs(data, rows)
    vectors = {item['section']: embeddings._decode_vector(result['vector'])
               for item, result in zip(data['inputs'], data['results'])}
    return {row['id']: current_v2.build_sample(title='diagnostic', section=row['id'], text=row['text'],
        citation='authored diagnostic:' + row['id'], embedding_vector=vectors[row['id']],
        embedding_model=data['model']['model_id'] + '@' + data['model']['revision']) for row in rows}


def prepare(directory, *, optimizer_steps):
    started = time.perf_counter()
    prepared_panel = panel()
    directory.mkdir(parents=True, exist_ok=False)
    write(directory/'plan.json', dict(schema='actor-composition-ablation-plan/v1',
        source_hashes=sources(), panel_file_sha256=sha(PANEL), panel_manifest_sha256=prepared_panel.manifest_sha256,
        curriculum=prepared_panel.receipt, arms=list(ARMS), formula_options=OPTIONS,
        optimizer_steps_per_arm=optimizer_steps, training_max_seconds_per_arm=120,
        training_scope='fresh frozen sparse core; joint residual projection and formula head only',
        evaluation_protocol='both fixed-budget heads saved before evaluation target file is opened',
        hyperparameter_selection_performed=False, bridge_names=[], legal_ir_target_count=0,
        legal_ir_evaluate_provers=False, metric_disk_cache=False, legal_ir_parallel_workers=1,
        sample_memory=False, temperature=0, **FALSE))
    subprocess.run([sys.executable, str(Path(__file__).resolve()), '--phase', 'embeddings',
                    '--output-directory', str(directory)], cwd=ROOT, check=True)
    plan = load_plan(directory)
    samples = native_samples(directory, prepared_panel)
    # Reuse the unchanged compiler screening policy. This observer's numerical
    # model is never encoded, decoded or trained; no teacher prediction is made.
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic import LinguisticAutoencoder
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_teacher import LegacyLinguisticTeacher
    observer = LegacyLinguisticTeacher(LinguisticAutoencoder())
    targets, observations = {}, []
    tick = time.perf_counter()
    for row in prepared_panel.manifest['rows']:
        observer._require_sources()
        evidence = observer._prepare(samples[row['id']], 'authored_fixture')
        require(evidence['candidate'], 'compiler screening rejected ' + row['id'] + ': ' + str(evidence['reasons']))
        sample = samples[row['id']]
        targets[row['id']] = dict(id=sample.sample_id, source_text=sample.text,
                                 canonical_ir={'rules': evidence['compiler']['rules']})
        observations.append(dict(panel_id=row['id'], source_sha256=hashlib.sha256(sample.text.encode()).hexdigest(),
                                 producer_sha256=observer.producer_sha256, evidence=evidence, **FALSE))
    observer._require_sources()
    elapsed = time.perf_counter()-tick
    files = {}
    for split in ('training', 'tuning', 'sealed_evaluation'):
        files[split] = write(directory/('targets-'+split+'.json'),
                             [targets[row['id']] for row in prepared_panel.rows(split)])
    files['compiler_observations'] = write(directory/'compiler-observations.json', observations)
    files['samples'] = write(directory/'student-samples.json', [sample.to_dict() for sample in samples.values()])
    files['embedding_production'] = reference(directory/'embedding-production.json')
    require(plan['source_hashes'] == sources(), 'source changed during preparation')
    write(directory/'prepared.json', dict(schema='actor-composition-preparation/v1', plan_sha256=sha(directory/'plan.json'),
        files=files, compiler_weak_target_count=len(targets), compiler_label_elapsed_seconds=elapsed,
        compiler_label_wall_seconds_per_span=elapsed/len(targets), shared_targets_prepared_once=True,
        preparation_seconds=time.perf_counter()-started,
        peak_preparation_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        legacy_teacher_prediction_executed=False, teacher_weights_loaded=False, **FALSE))
    print(json.dumps({'phase':'prepared','weak_target_count':len(targets),'seconds':elapsed}), flush=True)


def prepared_inputs(directory):
    plan, curriculum = load_plan(directory), panel()
    prepared = json.loads((directory/'prepared.json').read_text())
    require(prepared['plan_sha256'] == sha(directory/'plan.json'), 'preparation plan differs')
    read_reference(prepared['files']['embedding_production'])
    samples = native_samples(directory, curriculum)
    require([sample.to_dict() for sample in samples.values()] == read_reference(prepared['files']['samples']),
            'rebuilt student inputs differ from the prepared samples')
    return plan, curriculum, prepared, samples


def train(directory):
    started = time.perf_counter()
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import compare_free_running_formulas
    plan, curriculum, prepared, samples = prepared_inputs(directory)
    # Deliberately do not open targets-sealed_evaluation.json in this process.
    training_targets = {row['id']: row for row in read_reference(prepared['files']['training'])}
    tuning_targets = read_reference(prepared['files']['tuning'])
    tuning = [samples[row['id']] for row in curriculum.rows('tuning')]
    results, initial_identity = {}, None
    for arm in ARMS:
        training = [samples[row['id']] for row in curriculum.rows('training', training_subset=arm)]
        targets = [training_targets[sample.sample_id] for sample in training]
        runtime = runtimes.open_runtime('legal_ir', 'current_v2', compute_device='cpu')
        core = raw(runtime.model.state.to_dict())
        checkpoint = learning.build_checkpoint(joint._core_binding(runtime.model), joint._rows(runtime.model,training,targets),
            joint._rows(runtime.model,tuning,tuning_targets), **plan['formula_options'])
        identity = {name: learning.checkpoint_digest(checkpoint[name]) for name in ('binding','config','codec','model_state')}
        require(initial_identity is None or initial_identity == identity, 'ablation initialization or vocabulary differs')
        initial_identity = identity
        runtime.model.attach_formula_checkpoint(checkpoint)
        trained = runtime.train(training, validation_samples=tuning, formula_targets=targets,
            validation_formula_targets=tuning_targets, epochs=1000, max_optimizer_steps=plan['optimizer_steps_per_arm'],
            max_seconds=plan['training_max_seconds_per_arm'])
        report = trained['report']
        require(report['optimizer_steps'] == plan['optimizer_steps_per_arm'], 'arm stopped before its fixed update budget')
        require(report['training_after']['complete'] and report['tuning']['complete'], 'loss observations incomplete')
        require(raw(runtime.model.state.to_dict()) == core, 'sparse core changed during formula training')
        for group in ('projection','decoder'):
            require(report['parameter_evidence'][group]['parameter_update_l2'] > 0, 'parameter group did not train')
        outputs = {'training':runtime.infer(training), 'tuning':runtime.infer(tuning)}
        head = runtime.model.save_formula_checkpoint(directory/(arm+'-head.json'))
        require(head['sha256'] == report['checkpoint_sha256']
                and all(value['checkpoint_sha256'] == head['sha256'] for value in outputs.values()), 'head identity differs')
        resumed = runtimes.open_runtime('legal_ir','current_v2',compute_device='cpu',
                                       formula_checkpoint=head['path'],formula_sha256=head['sha256'])
        require(resumed.infer(tuning) == outputs['tuning'], 'save/reload changed predictions')
        resume_options = dict(validation_samples=tuning,formula_targets=targets,validation_formula_targets=tuning_targets,
                              epochs=1,max_seconds=60,max_optimizer_steps=1)
        continued, reloaded = runtime.train(training,**resume_options), resumed.train(training,**resume_options)
        require(continued['checkpoint'] == reloaded['checkpoint'], 'one-step exact resume failed')
        metrics = {name:compare_free_running_formulas(outputs[name], labels, partition=name)
                   for name,labels in [('training',targets),('tuning',tuning_targets)]}
        require(all(value['valid_evaluation'] for value in metrics.values()), 'generation evaluation lacks exact input coverage')
        results[arm] = dict(head=head, report=report, initial_identity=identity, generation=metrics,
            outputs=outputs, training_row_count=len(training), tuning_row_count=len(tuning),
            core_sparse_state_unchanged=True, reload_prediction_exact=True, resume_checkpoint_exact=True,
            resume_check_extra_steps_excluded_from_frozen_head=True, **FALSE)
        write(directory/(arm+'-training.json'), results[arm])
        print(json.dumps({'phase':'trained','arm':arm,'steps':report['optimizer_steps'],'seconds':report['elapsed_seconds']}),flush=True)
    require(plan['source_hashes'] == sources(), 'source changed during fitting')
    write(directory/'frozen.json', dict(schema='actor-composition-frozen-heads/v1',
        plan_sha256=sha(directory/'plan.json'), prepared_sha256=sha(directory/'prepared.json'),
        heads={arm:result['head'] for arm,result in results.items()},
        training_reports={arm:dict(path=str((directory/(arm+'-training.json')).resolve()),
                                  sha256=sha(directory/(arm+'-training.json')),
                                  bytes=(directory/(arm+'-training.json')).stat().st_size) for arm in ARMS},
        initial_weights_and_vocabulary_equal=True, evaluation_targets_opened=False,
        training_phase_seconds=time.perf_counter()-started,
        peak_training_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        selection_performed=False, **FALSE))


def verify_frozen_artifacts(directory, plan):
    """Verify both frozen heads and fit receipts before opening evaluation labels."""
    frozen = json.loads((directory/'frozen.json').read_text())
    require(frozen['plan_sha256'] == sha(directory/'plan.json') and frozen['prepared_sha256'] == sha(directory/'prepared.json'),
            'frozen head provenance differs')
    require(set(frozen['heads']) == set(ARMS) and set(frozen['training_reports']) == set(ARMS)
            and frozen['evaluation_targets_opened'] is False, 'both heads must be frozen first')
    verified, identity = {}, None
    for arm in ARMS:
        head = read_reference(frozen['heads'][arm])
        fit = read_reference(frozen['training_reports'][arm])
        require(fit['head'] == frozen['heads'][arm]
                and fit['report']['checkpoint_sha256'] == frozen['heads'][arm]['sha256'], 'fit receipt differs from frozen head')
        require(head['progress']['optimizer_steps'] == fit['report']['optimizer_steps'] == plan['optimizer_steps_per_arm'],
                'fixed optimizer budget differs')
        require(all(head['config'][key] == value for key,value in plan['formula_options'].items()), 'frozen optimizer settings differ')
        require(identity is None or identity == fit['initial_identity'], 'frozen initialization differs between arms')
        identity = fit['initial_identity']
        verified[arm] = fit
    return frozen, verified


def schema_checks_passed(lake, expected_count):
    return bool(expected_count > 0 and lake['schema_checks_complete'] and
                lake['lake_build_count'] == lake['schema_pass_count'] == expected_count)


def evaluate(directory):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_decoded_schema as schemas
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import compare_free_running_formulas
    started = time.perf_counter()
    plan, curriculum, prepared, samples = prepared_inputs(directory)
    frozen, fitting = verify_frozen_artifacts(directory,plan)
    models = {arm:runtimes.open_runtime('legal_ir','current_v2',compute_device='cpu',
              formula_checkpoint=frozen['heads'][arm]['path'],formula_sha256=frozen['heads'][arm]['sha256']) for arm in ARMS}
    # This is the first evaluation-label read after fitting, with both artifacts
    # fixed. There is no training or hyperparameter selection in this phase.
    targets = read_reference(prepared['files']['sealed_evaluation'])
    evaluation = [samples[row['id']] for row in curriculum.rows('sealed_evaluation')]
    results = {}
    for arm in ARMS:
        head = frozen['heads'][arm]
        training, runtime = fitting[arm], models[arm]
        tick = time.perf_counter()
        outputs = runtime.infer(evaluation)
        seconds = time.perf_counter()-tick
        require(outputs['checkpoint_sha256'] == head['sha256'], 'evaluation used another head')
        metrics = compare_free_running_formulas(outputs,targets,partition='sealed_evaluation')
        require(metrics['valid_evaluation'], 'evaluation provenance or row coverage failed')
        lake = schemas.validate_decoded_outputs(runtime,evaluation,
                      output_directory=directory/(arm+'-schema'),timeout_seconds=60)
        require(lake['checkpoint_sha256'] == head['sha256'] and sha(head['path']) == head['sha256'], 'schema checks changed head')
        results[arm] = dict(training=training,evaluation=metrics,outputs=outputs,generated_schema=lake,
                            generated_schema_builds_ok=schema_checks_passed(lake,len(evaluation)),
                            inference_seconds=seconds,wall_seconds_per_span=seconds/len(evaluation))
    require(plan['source_hashes'] == sources(), 'source changed during evaluation')
    operational_ok = all(row['generated_schema_builds_ok'] and row['evaluation']['operational_complete'] for row in results.values())
    report = dict(schema='actor-composition-ablation-result/v1',operational_ok=operational_ok,
        experiment_completed=True,evaluation_panel_now_exposed=True,plan=plan,prepared=prepared,frozen=frozen,
        results=results,evaluation_seconds=time.perf_counter()-started,
        peak_evaluation_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        source_only_formalization=False,temporal_kind_sidecars_encoded_by_head=False,full_logic_floor_coverage=False,
        bridge_on_evaluate=None,legal_ir_target_count=0,legacy_teacher_prediction_executed=False,
        teacher_weights_loaded=False,selection_performed=False,**FALSE)
    write(directory/'report.json',report)
    print(json.dumps({'phase':'evaluated','results':{arm:row['evaluation']['exact_reconstruction']
                                                  for arm,row in results.items()},**FALSE}),flush=True)
    require(operational_ok, 'evaluation or generated schema checks incomplete; inspect retained report')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory',type=Path,required=True)
    parser.add_argument('--phase',choices=('all','prepare','embeddings','train','evaluate'),default='all')
    parser.add_argument('--optimizer-steps',type=int,default=1000)
    args = parser.parse_args()
    require(1 <= args.optimizer_steps <= 1000, 'step budget outside supported epoch bound')
    os.environ['IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE']='0'
    os.environ['IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI']='0'
    os.environ['IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS']='0'
    directory = args.output_directory.resolve()
    if args.phase == 'all':
        for phase in ('prepare','train','evaluate'):
            subprocess.run([sys.executable,str(Path(__file__).resolve()),'--phase',phase,
                '--optimizer-steps',str(args.optimizer_steps),'--output-directory',str(directory)],cwd=ROOT,check=True)
    elif args.phase == 'prepare': prepare(directory,optimizer_steps=args.optimizer_steps)
    elif args.phase == 'embeddings':
        load_plan(directory)
        shared.produce_embeddings(directory,fixture_path=PANEL)
    elif args.phase == 'train': train(directory)
    else: evaluate(directory)


if __name__ == '__main__':
    main()
