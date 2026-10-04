#!/usr/bin/env python3
"""Bounded authored paragraph curriculum; no production or legal qualification.

Re-embeds complete source paragraphs with already-local GTE-small, then compares
reference training and diagnostic same-codec distillation. Both arms keep one
optimizer across length stages. This experiment never changes a parent codec,
uses an old runtime with rewritten pins, downloads assets, or increases context.
Run inside the existing resource reservation owner, in a fresh output directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

RELATIVE = 'ipfs_datasets_py/logic/formalization/autoencoder'
FALSE = dict(qualified=False, admitted=False, proof_authority=False,
             source_semantics_verified=False, fresh_holdout=False,
             convergence_proven=False, checkpoint_promoted=False, lake_executed=False)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(content):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'duplicate generated JSON key')
            value[key] = item
        return value
    def invalid_constant(value):
        raise ValueError('nonfinite generated JSON constant')
    return json.loads(content, object_pairs_hook=unique, parse_constant=invalid_constant)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw(value) + b'\n')
    return dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size)


def load_extension(root, relative, name, pins):
    path = root / relative
    require(sha(path) == pins[relative], 'extension source differs: ' + relative)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def dependency_inventory(root):
    """Inventory actual package sources, excluding third-party virtual modules."""
    result = {}
    for name, module in list(sys.modules.items()):
        if name != 'ipfs_datasets_py' and not name.startswith('ipfs_datasets_py.'):
            continue
        filename = getattr(module, '__file__', None)
        if filename is None:  # A namespace package has no producer source file.
            continue
        path = Path(filename)
        require(path.is_absolute() and path.is_file() and path.resolve().is_relative_to(root.resolve()),
                'loaded package module outside explicit dependency tree: '+name)
        require(path.suffix == '.py', 'package producer must resolve to source: '+name)
        result[str(path.resolve())] = sha(path)
    return result


def validate_preparation(folder, expected):
    require(sha(folder / 'manifest.json') == expected, 'preparation manifest changed')
    manifest = json.loads((folder / 'manifest.json').read_bytes())
    for entry in manifest['outputs'].values():
        require(sha(entry['path']) == entry['sha256'], 'prepared data changed')
    metadata = json.loads(Path(manifest['outputs']['metadata']['path']).read_bytes())
    source_inventory = metadata['source_compatibility']
    for name in ('original_donor_sources', 'canonical_compiler_tree'):
        for entry in source_inventory[name]['files']:
            require(sha(entry['path']) == entry['sha256'], 'listed source changed')
    require(source_inventory['numerical_owner_matches_original'] is True,
            'unchanged donor numerical owner required')
    # The old full Runtime is deliberately not invoked: its unrelated UI decoder
    # pin differs. This is an explicit private numerical replay, not that runtime.
    require(source_inventory['checkpoint_pins_rewritten'] is False,
            'checkpoint provenance cannot be rewritten')
    return manifest, metadata


def embedding_run(rows, producer, torch):
    """Capture actual forward tokens; do not average pre-existing vectors."""
    started = time.monotonic()
    with producer._offline_guard():
        from sentence_transformers import SentenceTransformer
        snapshot, before = producer._snapshot_assets(producer.DEFAULT_SNAPSHOT_PATH)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(0)
            encoder = SentenceTransformer(str(snapshot), local_files_only=True,
                                          trust_remote_code=False, device='cpu')
        encoder.eval()
        producer._validate_model(encoder, torch)
        inputs = [SimpleNamespace(input_id=row['id'], text=row['source_text']) for row in rows]
        results = producer._produce_results(inputs, encoder, torch, batch_size=8,
                                            token_input_digest=lambda value: value)
        _, after = producer._snapshot_assets(snapshot)
        require(before == after, 'local encoder assets changed')
    return results, dict(model_id='thenlper/gte-small', revision=producer.PINNED_REVISION,
        asset_manifest=before, tokenizer_sha256=next(x['sha256'] for x in before if x['name']=='tokenizer.json'),
        dimension=384, encoder_context_tokens=512, encoder_context_changed=False,
        downloads_performed=False, full_source_reencoded=True, device='cpu', cpu_threads=1,
        actual_forward_tokens_checked=True, normalized=True, dtype='float32',
        elapsed_seconds=time.monotonic()-started, rows=len(rows),
        scope='verified local numerical execution; not corpus source authentication')


def private_teacher(checkpoint, numerical, experiment):
    require(checkpoint['schema'] == 'shared-source-384-autoencoder/v2'
            and checkpoint['dimension'] == 384 and checkpoint['domain_id'] == 'legal_ir',
            'explicit Legal 384D donor required')
    require(checkpoint['architecture'] == numerical.ARCHITECTURE, 'donor architecture differs')
    require(hashlib.sha256(json.dumps(checkpoint['model_state'], sort_keys=True,
            separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
            == checkpoint['weights_sha256'], 'donor weight digest differs')
    require(sha(numerical.__file__) == checkpoint['implementation']['numerical']['files']['modal_latent_formula.py'],
            'private numerical owner differs from donor')
    model = numerical._model({'dimension': 384}, checkpoint['codec'], checkpoint['config'])
    state = checkpoint['model_state']
    require(set(state) == set(model.state_dict()), 'exact donor tensor names required')
    model.load_state_dict({name: numerical._tensor(state[name], tensor, name)
                           for name, tensor in model.state_dict().items()}, strict=True)
    return experiment.bind_model(model.eval(), dimension=384)


def coverage(rows, predictions, vocabulary, validate_rule):
    """Count omitted/extra whole rules, preserving multiplicity and every field."""
    require(len(rows) == len(predictions), 'incomplete evaluation cannot be scored')
    indexed = {row['id']: row for row in rows}
    require(len(indexed) == len(rows) and set(indexed) == {p['id'] for p in predictions}, 'prediction IDs differ')
    reports, buckets = [], {}
    for prediction in predictions:
        reference = indexed[prediction['id']]
        gold = reference['target']['rules']
        generated, reason = None, None
        try:
            require(prediction['eos_reached'] is True, 'generation did not reach EOS')
            require(all(type(i) is int and 3 <= i < len(vocabulary) for i in prediction['token_ids']),
                    'generated token outside codec content')
            generated = strict_json(''.join(vocabulary[i] for i in prediction['token_ids']))
            require(type(generated) is dict and set(generated) == {'rules'}
                    and type(generated['rules']) is list and 1 <= len(generated['rules']) <= 32,
                    'experimental composite grammar invalid')
            for rule in generated['rules']:
                receipt = validate_rule({'rules': [rule]})
                require(type(receipt) is dict and receipt.get('valid') is True,
                        'single-rule validator rejected generated rule')
        except (ValueError, TypeError, KeyError, IndexError) as error:
            generated, reason = None, str(error)[:512]
        expected = Counter(raw(rule) for rule in gold)
        actual = Counter(raw(rule) for rule in generated['rules']) if generated is not None else Counter()
        missing, extra = sum((expected-actual).values()), sum((actual-expected).values())
        record = dict(id=reference['id'], clauses=len(gold), source_text=reference['source_text'],
            expected_ir=reference['target'], generated_ir=generated, error=reason,
            whole_rules_expected=len(gold), whole_rules_missing=missing, whole_rules_extra=extra,
            all_rules_preserved=missing == extra == 0,
            ordered_exact=generated is not None and raw(generated) == raw(reference['target']), **FALSE)
        reports.append(record)
        bucket = buckets.setdefault(str(len(gold)), dict(rows=0, ordered_exact=0, all_rules_preserved=0,
            whole_rules_expected=0, whole_rules_missing=0, whole_rules_extra=0, syntax_valid=0))
        bucket['rows'] += 1
        for key in ('ordered_exact', 'all_rules_preserved', 'whole_rules_expected', 'whole_rules_missing', 'whole_rules_extra'):
            bucket[key] += int(record[key])
        bucket['syntax_valid'] += int(generated is not None)
    return dict(by_clause_count=buckets, rows=reports,
                syntax_scope='ordered authored independent rules; not accepted legacy single-rule grammar', **FALSE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependency-root', type=Path, required=True)
    parser.add_argument('--extension-root', type=Path, required=True)
    parser.add_argument('--extension-manifest', type=Path, required=True)
    parser.add_argument('--preparation', type=Path, required=True)
    parser.add_argument('--preparation-sha256', required=True)
    parser.add_argument('--donor', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds-per-arm', type=float, default=90.)
    parser.add_argument('--epochs-per-stage', type=int, default=4)
    args = parser.parse_args()
    require(not args.output.exists(), 'fresh immutable output directory required')
    require(0 < args.seconds_per_arm <= 120 and 1 <= args.epochs_per_stage <= 20, 'bounded experiment required')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.dependency_root.resolve()))
    pins = json.loads(args.extension_manifest.read_bytes())
    experiment = load_extension(args.extension_root, RELATIVE+'/decoder_distillation_experiment.py', 'length_numeric', pins)
    paragraph = load_extension(args.extension_root, 'scripts/ops/autoencoder/prepare_legal_paragraph_curriculum.py', 'length_data', pins)
    curriculum_owner = load_extension(args.extension_root, RELATIVE+'/source_length_curriculum.py', 'length_plan', pins)
    manifest, metadata = validate_preparation(args.preparation, args.preparation_sha256)
    require(args.dependency_root.resolve() == Path(metadata['source_compatibility']['canonical_compiler_tree']['root']).resolve(),
            'dependency tree differs from sealed preparation')
    require(sha(args.donor) == manifest['original_checkpoint_sha256'], 'donor checkpoint changed')
    checkpoint = json.loads(args.donor.read_bytes())
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_formula_codec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    tree = require_workspace_logic_tree()
    initial_dependencies = dependency_inventory(args.dependency_root)
    def validate_rule(target):
        legal_formula_codec._rule(target)
        return {'valid': True, 'canonical_ir': target}
    corpus = paragraph.build_paragraphs(
        [row['original_row_without_embedding'] for row in metadata['splits']['train']],
        [row['original_row_without_embedding'] for row in metadata['splits']['validation']],
        checkpoint['codec'], clause_counts=(1, 2, 4, 8), rows_per_length=12, validate_single_target=validate_rule)
    args.output.mkdir(parents=True)
    save(args.output/'paragraphs.json', corpus)
    require(corpus['status'] == 'prepared' and len(corpus['length_readiness']) == 8
            and all(entry['produced_rows'] == 12 for entry in corpus['length_readiness']),
            'requested paragraph length panel incomplete; inspect preserved readiness')
    original_rows = corpus['train'] + corpus['validation']
    vectors, embedding = embedding_run(original_rows, producer, torch)
    save(args.output/'embedding-results.json', dict(rows=vectors, producer=embedding, **FALSE))
    by_id = {row['input_id']: row for row in vectors}
    rows = [{**row, 'embedding_result': by_id[row['id']]} for row in original_rows]
    # Adapter is intentionally source/target-only; no cached short-span vector is
    # eligible for a new paragraph. Actual token lengths drive curriculum stages.
    plan_rows = curriculum_owner.paragraph_rows(rows, tokenizer_sha256=embedding['tokenizer_sha256'],
        tokenizer_profile_id='gte-small:'+producer.PINNED_REVISION,
        encoder_context_tokens=512, codec_sha256=experiment.digest(checkpoint['codec']))
    plan = curriculum_owner.prepare_curriculum(plan_rows,
        tokenizer={'profile_id': 'gte-small:'+producer.PINNED_REVISION,
                   'sha256': embedding['tokenizer_sha256'], 'encoder_context_tokens': 512},
        output_limit=512, expected_codec_sha256=experiment.digest(checkpoint['codec']),
        expected_rows_sha256=curriculum_owner.digest(plan_rows))
    save(args.output/'source-curriculum-inputs.json', plan_rows)
    save(args.output/'source-curriculum.json', plan)
    require(plan['ready'], 'source curriculum has unresolved inputs')
    train = [dict(id=row['id'], source_text=row['source_text'], input=by_id[row['id']]['vector'],
                  target_ids=row['target_ids']) for row in corpus['train']]
    validation = [dict(id=row['id'], source_text=row['source_text'], input=by_id[row['id']]['vector'],
                       target_ids=row['target_ids']) for row in corpus['validation']]
    require(not {experiment.digest(row['input']) for row in train}
            & {experiment.digest(row['input']) for row in validation}, 'train/validation input vectors overlap')
    stages = []
    previous = set()
    for stage in plan['stages']:
        ids = stage['training_ids']
        if ids and set(ids) != previous:
            stages.append(dict(name='source_tokens_'+str(stage['max_source_tokens']),
                               training_ids=ids, epochs=args.epochs_per_stage))
            previous = set(ids)
    require(previous == {row['id'] for row in train}, 'last stage omits training rows')
    teacher = private_teacher(checkpoint, numerical, experiment)
    student = private_teacher(checkpoint, numerical, experiment)
    # This first length experiment isolates decoder learning and preserves the
    # donor's feature reconstruction. A joint projection ablation is a separate
    # predeclared arm; never relax the reconstruction gate after seeing results.
    for parameter_name, parameter in student.named_parameters():
        if parameter_name.startswith(('body.projection_down.', 'body.projection_up.')):
            parameter.requires_grad_(False)
    lineage = dict(teacher_checkpoint_sha256=sha(args.donor), teacher_codec_sha256=experiment.digest(checkpoint['codec']),
        input_provenance_sha256=experiment.digest(dict(embedding=embedding, rows=vectors)), domain='legal_ir',
        teacher_lineage='source384_v2_private_numerical_replay', student_lineage='authored_multi_rule_curriculum_v1',
        teacher_output_limit=checkpoint['config']['max_target_tokens'], student_role='source_conditioned_decoder')
    recipes = dict(reference_ce=0., diagnostic_distillation=.25)
    save(args.output/'recipe.json', dict(stages=stages, recipes=recipes, fixed_validation_ids=[r['id'] for r in validation],
        generation_temperature=0, diagnostic_KL_scale=1, output_tokens=512, encoder_context_tokens=512,
        epochs_per_stage=args.epochs_per_stage, seconds_per_arm=args.seconds_per_arm,
        old_runtime_executed=False, private_numerical_replay=True,
        projection_training=False, condition_and_recurrent_decoder_training=True,
        frozen_student_parameters=[name for name, p in student.named_parameters() if not p.requires_grad],
        checkpoint_compatibility=metadata['source_compatibility'], tree_pin=tree, **FALSE))
    summaries = {}
    for name, alpha in recipes.items():
        lineage['student_lineage'] = 'authored_multi_rule_curriculum_v1:'+name
        result = experiment.run_trial(teacher, train, validation, codec=checkpoint['codec'],
            input_transform=checkpoint['input_transform'], lineage=lineage, student=student,
            config=dict(max_seconds=args.seconds_per_arm, max_target_tokens=512, batch_size=8,
                max_optimizer_steps=1000, alpha=alpha, patience=0, learning_rate=.001,
                validation_interval=1, reconstruction_weight=.1), curriculum=stages)
        report = result['report']
        save(args.output/(name+'-training.json'), report)
        save(args.output/(name+'-predictions.json'), result['predictions'])
        if report['selected_validation'] is None:
            summaries[name] = dict(training=report, coverage=None, complete=False,
                                   reason='no_complete_validation; no generation fidelity claim')
            continue
        state = {key: value.tolist() for key, value in result['state_dict'].items()}
        state_receipt = save(args.output/(name+'-experimental-state.json'), dict(schema='private-long-span-decoder-state/v1',
            lineage=dict(lineage), codec=checkpoint['codec'], state=state, weights_sha256=experiment.digest(state),
            optimizer_resumable=False, production_checkpoint=False, **FALSE))
        persisted = json.loads(Path(state_receipt['path']).read_bytes())
        require(experiment.digest(persisted['state']) == persisted['weights_sha256'], 'saved state changed')
        reloaded = private_teacher(checkpoint, numerical, experiment)
        reloaded.load_state_dict({key: numerical._tensor(persisted['state'][key], tensor, key)
            for key, tensor in reloaded.state_dict().items()}, strict=True)
        require(experiment.tensor_digest(reloaded) == report['selected_student_weights_sha256'],
                'saved state does not reproduce selected tensors')
        replay = experiment.evaluate_model(reloaded, validation, codec=checkpoint['codec'],
            input_transform=checkpoint['input_transform'], lineage=lineage,
            max_target_tokens=512, max_seconds=20, batch_size=8)
        require(replay['report']['complete'] and replay['predictions'] == result['predictions'],
                'private reload did not reproduce selected target-free generations')
        save(args.output/(name+'-reload.json'), replay['report'])
        metrics = coverage(corpus['validation'], result['predictions'], checkpoint['codec']['target_vocabulary'], validate_rule)
        save(args.output/(name+'-coverage.json'), metrics)
        summaries[name] = dict(training=report, coverage=metrics['by_clause_count'], complete=True)
        print(json.dumps(dict(arm=name, optimizer_steps=report['optimizer_steps'],
            baseline=report['baseline_validation'], selected=report['selected_validation'],
            coverage=metrics['by_clause_count'])), flush=True)
    validate_preparation(args.preparation, args.preparation_sha256)
    require(sha(args.donor) == manifest['original_checkpoint_sha256'], 'donor changed during experiment')
    for relative, expected in pins.items():
        require(sha(args.extension_root/relative) == expected, 'experiment source changed')
    require(all(sha(path) == expected for path, expected in initial_dependencies.items()),
            'loaded producer changed during experiment')
    loaded = {str(Path(path).relative_to(args.dependency_root.resolve())): digest
              for path, digest in dependency_inventory(args.dependency_root).items()}
    save(args.output/'summary.json', dict(schema='authored-long-span-training-development/v1',
        arms=summaries, train_rows=len(train), validation_rows=len(validation),
        stage_count=len(stages), clause_counts=[1, 2, 4, 8], embedding=embedding,
        dimension=384, unavailable_dimensions=[8, 768],
        unavailable_reasons={'8':'historical linguistic teacher preserved; learned sidecar lacks independent corpus',
                             '768':'configured local encoder assets absent and native input receipts empty'},
        source_kind='authored independent composition; existing exposed component splits',
        native_family_validation_performed=False,
        training_executed=any(value['training']['optimizer_steps'] > 0 for value in summaries.values()),
        complete=all(value['complete'] for value in summaries.values()),
        legal_ir_bridge_evaluation_performed=False, legal_ir_bridge_names=[],
        legal_ir_evaluate_provers=False, timing_is_legal_ir_bridge_timing=False,
        dependencies=loaded, extensions=pins, dependency_root=str(args.dependency_root), **FALSE))


if __name__ == '__main__':
    main()
