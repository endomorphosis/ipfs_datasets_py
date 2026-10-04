#!/usr/bin/env python3
"""Frozen 2x2 source-retention/loss comparison on exposed paragraph diagnostics.

Requires the exact completed paragraph preparation, an explicit frozen source
inventory, and the existing resource owner. Cached vectors bind whole paragraph
sources. Negative controls run only after each selected checkpoint is frozen.
No model download, context increase, old checkpoint rewrite, or admission occurs.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import time

PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
FALSE = dict(qualified=False, admitted=False, proof_authority=False,
    source_semantics_verified=False, fresh_holdout=False, convergence_proven=False,
    checkpoint_promoted=False, lake_executed=False, formalized=False, roundtrip_ok=False)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def validate_manifest_inputs(manifest):
    require(type(manifest) is dict and type(manifest.get('inputs')) is dict, 'pinned input inventory required')
    for key in ('donor', 'paragraphs', 'embeddings', 'curriculum', 'curriculum_inputs'):
        path = manifest.get(key)
        require(type(path) is str and Path(path).is_absolute() and path in manifest['inputs'],
                'required input pointer is not pinned: '+key)
    for path, expected in manifest['inputs'].items():
        require(type(path) is str and Path(path).is_absolute() and type(expected) is str
            and len(expected)==64, 'absolute SHA-256 input pin required')
        require(sha(path)==expected, 'prepared input changed: '+path)


def validate_plan(plan):
    # This driver owns one bounded predeclared experiment, not an open sweep.
    fixed = dict(schema='long-source-fidelity-ablation-plan/v1', representations=[384],
        architecture_arms=['first_step', 'every_step'], loss_arms=['reference_ce', 'semantic_fields'],
        seed_order=[1729, 2718], epochs_per_source_stage=20, expected_optimizer_steps_per_arm=340,
        expected_training_token_presentations_per_arm=225840, batch_size=8, learning_rate=.001,
        max_seconds_per_arm=45, validation_interval=4, fixed_encoder_context_tokens=512,
        fixed_decoder_output_limit=512, projection_frozen=True, teacher_distillation_used=False,
        controls=['zero_condition', 'source_shuffle_within_clause_count'],
        no_downloads=True, strict_gates_changed=False)
    require(type(plan) is dict, 'explicit experiment plan required')
    for key, expected in fixed.items():
        require(type(plan.get(key)) is type(expected) and plan[key]==expected, 'unsupported experiment plan: '+key)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw(value)+b'\n')
    return dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size)


def save_evaluation(folder, label, evaluation):
    require(label in ('validation', 'training', 'zero-condition', 'source-shuffle'), 'unknown evaluation label')
    return save(folder/('evaluation-'+label+'.json'), evaluation)


def extension(root, path, name, pins):
    require(sha(root/path) == pins[path], 'frozen extension changed: '+path)
    require(name not in sys.modules, 'extension must be loaded exactly once: '+name)
    spec = importlib.util.spec_from_file_location(name, root/path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def inventory(dependency_root, extension_root, pins):
    result = {}
    for name, module in list(sys.modules.items()):
        if name != 'ipfs_datasets_py' and not name.startswith('ipfs_datasets_py.'):
            continue
        filename = getattr(module, '__file__', None)
        if filename is None:
            continue
        path = Path(filename)
        require(path.is_absolute() and path.is_file() and path.suffix == '.py', 'unbound package source')
        path = path.resolve()
        if path.is_relative_to(dependency_root):
            scope, relative = 'dependency', str(path.relative_to(dependency_root))
        else:
            require(path.is_relative_to(extension_root), 'different package tree loaded')
            scope, relative = 'extension', str(path.relative_to(extension_root))
            require(pins.get(relative) == sha(path), 'unregistered package extension')
        result[scope+':'+relative] = sha(path)
    return result


def shuffle_inputs(rows, references):
    """Length-matched, intentional provenance-breaking negative control."""
    require(type(rows) is list and type(references) is list and rows and references, 'complete shuffle inputs required')
    require(all(type(r) is dict and type(r.get('id')) is str for r in rows+references), 'shuffle row IDs required')
    ids, ref_ids = [r['id'] for r in rows], [r['id'] for r in references]
    require(len(set(ids))==len(ids) and len(set(ref_ids))==len(ref_ids) and set(ids)==set(ref_ids),
            'shuffle requires unique exact reference and row inventories')
    result, assignment, by_id = [], {}, {r['id']: r for r in rows}
    bins = {}
    for reference in references:
        require(type(reference.get('clause_count')) is int and reference['clause_count'] > 0, 'shuffle clause count required')
        bins.setdefault(reference['clause_count'], []).append(reference['id'])
    for members in bins.values():
        members.sort()
        require(len(members) >= 2, 'a source-shuffle stratum needs two rows')
        assignment.update(zip(members, members[1:]+members[:1]))
    for row in rows:
        require(row['input'] != by_id[assignment[row['id']]]['input'], 'ineffective equal-vector source shuffle')
        result.append({**row, 'input': deepcopy(by_id[assignment[row['id']]]['input'])})
    return result, dict(kind='source_shuffle', source_assignment=assignment,
        input_substitutions={row['id']: dict(original_input_sha256=hashlib.sha256(raw(row['input'])).hexdigest(),
            substituted_input_sha256=hashlib.sha256(raw(by_id[assignment[row['id']]]['input'])).hexdigest()) for row in rows})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependency-root', type=Path, required=True)
    parser.add_argument('--extension-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'fresh immutable experiment directory required')
    args.dependency_root = args.dependency_root.resolve()
    args.extension_root = args.extension_root.resolve()
    manifest = json.loads(args.manifest.read_bytes())
    pins = manifest['extensions']
    require(sha(args.plan) == manifest['plan_sha256'], 'experiment plan changed')
    plan = json.loads(args.plan.read_bytes())
    validate_plan(plan)
    validate_manifest_inputs(manifest)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.dependency_root))
    importlib.import_module(PREFIX.rstrip('.'))
    core = extension(args.extension_root, AUTO+'decoder_distillation_experiment.py', PREFIX+'decoder_distillation_experiment', pins)
    adapter = extension(args.extension_root, AUTO+'decoder_distillation_experiment_v2.py', PREFIX+'decoder_distillation_experiment_v2', pins)
    scorer = extension(args.extension_root, AUTO+'decoder_source_fidelity.py', PREFIX+'decoder_source_fidelity', pins)
    trainer = extension(args.extension_root, AUTO+'long_span_decoder_training.py', PREFIX+'long_span_decoder_training', pins)
    curriculum_owner = extension(args.extension_root, AUTO+'source_length_curriculum.py', PREFIX+'source_length_curriculum', pins)
    prior = extension(args.extension_root, 'scripts/ops/autoencoder/benchmark_long_span_decoder.py', 'prior_source_benchmark', pins)
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    tree = require_workspace_logic_tree()
    before_sources = inventory(args.dependency_root, args.extension_root, pins)
    donor_path = Path(manifest['donor'])
    donor = json.loads(donor_path.read_bytes())
    corpus = json.loads(Path(manifest['paragraphs']).read_bytes())
    embeddings = json.loads(Path(manifest['embeddings']).read_bytes())
    source_plan = json.loads(Path(manifest['curriculum']).read_bytes())
    require(corpus['status'] == 'prepared' and source_plan['ready'], 'original full length panel unavailable')
    require(embeddings['producer']['actual_forward_tokens_checked'] and embeddings['producer']['encoder_context_tokens']==512,
            'complete original native inputs required')
    by_id = {row['input_id']: row for row in embeddings['rows']}
    original_rows = corpus['train']+corpus['validation']
    require(len(by_id)==len(embeddings['rows'])==96 and len({r['id'] for r in original_rows})==96
        and set(by_id)=={r['id'] for r in original_rows}, 'complete unique paragraph/embedding IDs required')
    require(core.digest(donor['codec'])==corpus['codec_sha256']==source_plan['codec_sha256'], 'paragraph codec differs')
    plan_rows = curriculum_owner.paragraph_rows([{**r, 'embedding_result': by_id[r['id']]} for r in original_rows],
        tokenizer_sha256=embeddings['producer']['tokenizer_sha256'],
        tokenizer_profile_id='gte-small:'+embeddings['producer']['revision'], encoder_context_tokens=512,
        codec_sha256=core.digest(donor['codec']))
    require(plan_rows==json.loads(Path(manifest['curriculum_inputs']).read_bytes()), 'source input replay differs')
    curriculum_owner.validate_curriculum(source_plan, plan_rows, tokenizer=source_plan['tokenizer'],
        output_limit=512, expected_codec_sha256=core.digest(donor['codec']),
        expected_rows_sha256=curriculum_owner.digest(plan_rows))
    rows, references = {}, {}
    for split in ('train', 'validation'):
        references[split] = [dict(id=row['id'], source_text=row['source_text'], source_sha256=row['source_sha256'],
            target=row['target'], clause_count=row['clause_count']) for row in corpus[split]]
        rows[split] = [dict(id=row['id'], source_text=row['source_text'], target_ids=row['target_ids'],
            input=by_id[row['id']]['vector']) for row in corpus[split]]
        require(len(rows[split]) == 48 and all(by_id[row['id']]['status']=='embedded' for row in rows[split]), 'complete48row panel required')
    require(not {core.digest(r['input']) for r in rows['train']} & {core.digest(r['input']) for r in rows['validation']}, 'input-vector split leakage')
    stages, previous = [], set()
    for stage in source_plan['stages']:
        if stage['training_ids'] and set(stage['training_ids']) != previous:
            stages.append(dict(name=stage['stage_id'], training_ids=stage['training_ids'], epochs=plan['epochs_per_source_stage']))
            previous = set(stage['training_ids'])
    require(previous == {row['id'] for row in rows['train']}, 'curriculum dropped training rows')
    validator_id = 'canonical-single-rule-sha256:'+sha(legal_formula_codec.__file__)
    def validate_rule(target):
        legal_formula_codec._rule(target)
        return dict(valid=True, canonical_ir=target)
    base_model = prior.private_teacher(donor, numerical, core)
    lineage = dict(teacher_checkpoint_sha256=sha(donor_path), teacher_codec_sha256=core.digest(donor['codec']),
        input_provenance_sha256=sha(manifest['embeddings']), domain='legal_ir',
        teacher_lineage='private_original_source384_numerical_replay', student_lineage='long_source_fidelity_v1',
        teacher_output_limit=512, student_role='source_conditioned_decoder')
    args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json', dict(plan=plan, manifest=manifest, tree_pin=tree, **FALSE))
    def fixed_evaluation(model, split, *, control_kind='conditioned'):
        actual = rows[split]
        execution = dict(kind=control_kind, source_assignment={row['id']: row['id'] for row in actual})
        if control_kind == 'source_shuffle':
            actual, execution = shuffle_inputs(actual, references[split])
        elif control_kind == 'zero_condition':
            model = adapter.bind_zero_condition_model(model, dimension=384)
        evaluation = core.evaluate_model(model, actual, codec=donor['codec'], input_transform=donor['input_transform'],
            lineage=lineage, max_target_tokens=512, max_seconds=20, batch_size=8)
        require(evaluation['report']['complete'], 'post-fit control incomplete')
        evaluation['source_fidelity'] = scorer.score_predictions(references[split], evaluation['predictions'],
            codec=donor['codec'], validate_rule=validate_rule, validator_id=validator_id, output_limit=512,
            control={key: execution[key] for key in ('kind', 'source_assignment')})
        evaluation['execution'] = {**execution, 'selection_performed': False, 'training_performed': False,
            'provenance_breaking_negative_control': control_kind=='source_shuffle'}
        return evaluation
    summaries = []
    for seed in plan['seed_order']:
        for architecture in plan['architecture_arms']:
            for strategy in plan['loss_arms']:
                name = f'{architecture}-{strategy}-{seed}'
                model = adapter.bind_persistent_model(base_model.body, dimension=384, conditioning=architecture)
                for parameter_name, parameter in model.named_parameters():
                    if parameter_name.startswith(('body.projection_down.', 'body.projection_up.')):
                        parameter.requires_grad_(False)
                lineage['student_lineage'] = name
                result = trainer.train(model, rows['train'], rows['validation'],
                    training_references=references['train'], validation_references=references['validation'],
                    codec=donor['codec'], input_transform=donor['input_transform'], lineage=lineage,
                    validate_rule=validate_rule, validator_id=validator_id, curriculum=stages, strategy=strategy,
                    config=dict(seed=seed, max_seconds=plan['max_seconds_per_arm'], max_target_tokens=512,
                        learning_rate=plan['learning_rate'], batch_size=8, max_optimizer_steps=1000,
                        patience=0, validation_interval=plan['validation_interval'], alpha=0.))
                folder = args.output/name
                report = result['report']
                save(folder/'training.json', report)
                save(folder/'selected-predictions.json', result['predictions'])
                save(folder/'last-complete-attempt-predictions.json', result['last_complete_attempt_predictions'])
                model.load_state_dict(result['state_dict'], strict=True)
                weights = {key: tensor.tolist() for key, tensor in result['state_dict'].items()}
                state = save(folder/'private-state.json', dict(schema='long-source-private-state/v1',
                    architecture=architecture, architecture_specification=model.describe(),
                    lineage=dict(lineage), codec=donor['codec'], model_state=weights,
                    weights_sha256=core.digest(weights), production_checkpoint=False, optimizer_resumable=False, **FALSE))
                persisted = json.loads(Path(state['path']).read_bytes())
                require(core.digest(persisted['model_state'])==persisted['weights_sha256'], 'saved state differs')
                model.load_state_dict({key: numerical._tensor(persisted['model_state'][key], tensor, key)
                    for key, tensor in model.state_dict().items()}, strict=True)
                require(core.tensor_digest(model)==report['selected_weights_sha256'], 'private reload tensor mismatch')
                postfit = {}
                if report['selected'] is not None:
                    for label, split, control in [('validation','validation','conditioned'),('training','train','conditioned'),
                        ('zero-condition','validation','zero_condition'),('source-shuffle','validation','source_shuffle')]:
                        evaluation = fixed_evaluation(model, split, control_kind=control)
                        if label == 'validation':
                            require(evaluation['predictions']==result['predictions'], 'reloaded generation mismatch')
                        save_evaluation(folder, label, evaluation)
                        postfit[label] = dict(numerical=evaluation['report'],
                            source_fidelity={key: value for key, value in evaluation['source_fidelity'].items() if key!='rows'})
                last_state = result['last_complete_attempt_state_dict']
                if last_state is not None:
                    values = {key: tensor.tolist() for key, tensor in last_state.items()}
                    save(folder/'last-complete-attempt-state.json', dict(schema='long-source-last-complete-diagnostic/v1',
                        architecture=architecture, model_state=values, lineage=dict(lineage),
                        weights_sha256=core.digest(values), selected=report['last_complete_attempt_is_selected'], production_checkpoint=False,
                        optimizer_resumable=False, **FALSE))
                completed = report['optimizer_steps']==plan['expected_optimizer_steps_per_arm'] and \
                    report['valid_target_token_presentations']==plan['expected_training_token_presentations_per_arm']
                summary = dict(arm=name, architecture=architecture, strategy=strategy, seed=seed,
                    budget_completed=completed, training=report, postfit=postfit,
                    trainable_parameter_count=sum(p.numel() for p in model.parameters() if p.requires_grad))
                summaries.append(summary)
                save(folder/'summary.json', summary)
                print(json.dumps(dict(arm=name, steps=report['optimizer_steps'], seconds=report['elapsed_seconds'],
                    selected_epoch=report['selected_epoch'], selected=report['selected']['fidelity']['metrics'] if report['selected'] else None,
                    last=report['last_complete_attempt']['fidelity']['metrics'] if report['last_complete_attempt'] else None)), flush=True)
    after_sources = inventory(args.dependency_root, args.extension_root, pins)
    require(all(after_sources.get(path)==expected for path, expected in before_sources.items()), 'loaded source changed')
    for path, expected in manifest['inputs'].items():
        require(sha(path)==expected, 'sealed input changed during training')
    for path, expected in pins.items():
        require(sha(args.extension_root/path)==expected, 'experiment extension changed')
    save(args.output/'summary.json', dict(schema='long-source-fidelity-comparison/v1', runs=summaries,
        complete=len(summaries)==8 and all(r['budget_completed'] for r in summaries),
        training_executed=any(r['training']['optimizer_steps']>0 for r in summaries),
        source_dependencies=after_sources, paragraph_embedding_cache_used=True,
        encoder_executed=False, encoder_context_changed=False, downloads_performed=False,
        dimensions_actually_trained=[384], bridge_evaluation_performed=False, bridge_names=[],
        legal_ir_evaluate_provers=False, workers=1, **FALSE))


if __name__ == '__main__':
    main()
