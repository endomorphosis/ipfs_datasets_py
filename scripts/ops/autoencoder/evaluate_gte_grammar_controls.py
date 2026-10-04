"""Apply a fixed inherited-codec grammar after freezing unmasked baselines.

The generation API receives only private models, source vectors, inherited
codecs and fixed token budgets. All five variants and a complete fresh-model
numerical replay are frozen before references or unmasked scores are scored.
This exposed historical regression cannot establish statutory fidelity.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

# This script is intentionally separate from the frozen unmasked runner.
import importlib.util
_spec = importlib.util.spec_from_file_location('_gte_grammar_controls_base',
    Path(__file__).with_name('evaluate_gte_native_source_controls.py'))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)
require, digest, read_ref, write, file_ref = base.require, base.digest, base.read_ref, base.write, base.file_ref


def admission(plan):
    """Re-admit exact baseline checkpoint/runtime closure before tensor loading."""
    config = read_ref(plan['configuration'])
    for ref in plan['closure']:
        require(file_ref(ref['path']) == ref, 'unmasked parent closure changed')
    root = Path(config['workspace_root']).resolve()
    original_runtime, _ = base.runtime_receipt(config['original_runtime'], expected_start='original_initialization')
    aligned_runtime, _ = base.runtime_receipt(config['aligned_runtime'], expected_start='authenticated_aligned_generation')
    training = base.module('run_gte_aligned_interface_training', Path(__file__).parent)
    native = training._native_cli()
    reader = native._helper('gte_worker_contract')
    parent = base.module('gte_source_evaluation_parent', Path(__file__).parent).admit_training_parent(
        read_ref(aligned_runtime['manifest']), aligned_runtime['manifest'], root=root, reader=reader, training_cli=training)
    original, args, _ = base.admit_original(original_runtime, parent, reader=reader, native=native, training=training)
    p = parent['payloads']
    primary, legacy = read_ref(config['primary_checkpoint']), read_ref(config['legacy8_checkpoint'])
    source = native._helper('gte_decoder_source_evaluation')
    ev = source.prepare_source_evaluation(p['initialization'], p['native_batch'], p['batch'], p['replay'],
        expected_donor_pins=p['donor_pins'], max_primary_rows=60, max_auxiliary_rows=2)
    comparison = native._helper('gte_decoder_source_comparison')
    _, snapshot, aligned_args, _ = comparison._admit(ev, p['initialization'], p['native_batch'], p['batch'], p['replay'],
        p['donor_pins'], primary, legacy, parent['aligned']['checkpoint'], parent['aligned']['file_pins'], parent['trained_checkpoint'])
    return {'native': native, 'parent': parent, 'payloads': p, 'primary': primary, 'legacy_snapshot': snapshot,
        'original_checkpoint': original, 'arguments': args, 'aligned_arguments': aligned_args, 'source': source, 'evaluation': ev}


def load_models(admitted, label, torch):
    """Every call constructs fresh private model storage from admitted artifacts."""
    native, parent, p = admitted['native'], admitted['parent'], admitted['payloads']
    pins, init = p['donor_pins'], p['initialization']
    if label == 'original_donor':
        return {'primary384': native._helper('gte_decoder_transfer_replay')._original_primary_model(torch, admitted['primary']),
            'legacy8': native._helper('gte_legacy8_decoder_donor').load_private_legacy8_decoder_snapshot(admitted['legacy_snapshot'],
                expected_source_checkpoint_sha256=pins['legacy8_checkpoint_sha256'],
                expected_source_model_state_sha256=pins['legacy8_weights_sha256'])['model']}
    if label == 'original_initialization':
        model = native._helper('gte_decoder_reuse').load_dual_decoder(init, expected_donor_pins=pins)
    elif label == 'aligned_initialization':
        model = native._helper('gte_aligned_decoder').load_aligned_decoder(parent['aligned']['checkpoint'],
            expected_file_pins=parent['aligned']['file_pins'], expected_donor_pins=pins)
    elif label == 'original_trained':
        model = native._helper('gte_decoder_interface_checkpoint').load_interface_checkpoint(admitted['original_checkpoint'], **admitted['arguments'])
    elif label == 'aligned_trained':
        model = native._helper('gte_aligned_interface_checkpoint').load_interface_checkpoint(parent['trained_checkpoint'], **admitted['aligned_arguments'])
    else:
        raise ValueError('unsupported model variant')
    return {name: model for name in base.HEADS}


def compare_panel(rows, baseline_rows):
    """Account for every admitted head/source pair; no invalid tail filtering."""
    def key(row):
        return row['head'], row['id'], row['source_sha256']
    baseline = {key(row): row for row in baseline_rows}
    require(len(baseline) == len(baseline_rows) == len(rows)
        and len({key(row) for row in rows}) == len(rows) and set(baseline) == {key(row) for row in rows},
        'grammar and unmasked cohorts differ')
    return sum(row['generation']['generated_ids'] != baseline[key(row)]['generation']['generated_ids'] for row in rows)


def run(baseline_directory, output, *, expected_baseline_freeze_sha256, expected_grammar_sha256):
    baseline_directory = Path(baseline_directory).resolve()
    freeze_ref = file_ref(baseline_directory / 'generation-frozen.json')
    require(freeze_ref['sha256'] == expected_baseline_freeze_sha256, 'unmasked freeze SHA256 differs')
    frozen = read_ref(freeze_ref)
    require(frozen['schema'] == 'gte-native-source-controls-frozen/v1' and frozen['all_variants_completed'] is True
        and frozen['generation_count'] == 930 and frozen['reference_prefix_used'] is False,
        'complete fixed unmasked baseline required')
    baseline_plan = read_ref(frozen['plan'])
    require(baseline_plan['variants'] == list(base.VARIANTS) and baseline_plan['controls'] == list(base.CONTROLS)
        and baseline_plan['heads'] == list(base.HEADS), 'unmasked model/control inventory differs')
    inputs = read_ref(frozen['inputs'])
    require(inputs['contains_references'] is False and inputs['target_access'] is False, 'source-only input record required')
    admitted = admission(baseline_plan)
    grammar_ref = file_ref(base.HELPERS / 'gte_decoder_grammar_generation.py')
    require(grammar_ref['sha256'] == expected_grammar_sha256, 'grammar implementation SHA256 differs')
    import importlib
    import sys
    if str(base.REPOSITORY) not in sys.path:
        sys.path.insert(0, str(base.REPOSITORY))
    grammar = importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.gte_decoder_grammar_generation')
    output = Path(output).resolve()
    root = Path(read_ref(baseline_plan['configuration'])['workspace_root']).resolve()
    require(not output.exists() and output.is_relative_to(root), 'fresh output inside workspace required')
    output.mkdir(parents=True)
    input_ref = write(output / 'inputs.json', inputs)
    # Pin all baseline generation artifacts but do not inspect scores or targets.
    for ref in frozen['generation_files']:
        require(file_ref(ref['path']) == ref, 'unmasked generation bytes changed')
    plan_ref = write(output / 'plan.json', {'schema': 'gte-grammar-controls-plan/v1',
        'baseline_generation_freeze': freeze_ref, 'baseline_plan': frozen['plan'], 'inputs': input_ref,
        'variants': list(base.VARIANTS), 'controls': ['source'], 'heads': list(base.HEADS),
        'budgets': baseline_plan['budgets'], 'implementations': [file_ref(Path(__file__)), file_ref(Path(base.__file__)), grammar_ref],
        'grammar_depends_on_source_reference': False, 'selection': 'all_five_frozen_variants',
        'fresh_private_model_replay': 'every_generated_example', 'independent_holdout': False, 'proof_authority': False})
    import torch
    torch.set_num_threads(1)
    sources = inputs['heads']
    init = admitted['payloads']['initialization']
    exports = []
    for repetition in range(2):
        for label in base.VARIANTS:
            models = load_models(admitted, label, torch)
            records = []
            for name in base.HEADS:
                codec = init['primary' if name == 'primary384' else 'legacy8']['codec']
                for index, row in enumerate(sources[name]):
                    vector, intervention = base.intervention_input(sources[name], index, 'source', donor=label == 'original_donor')
                    receipt = grammar.generate_source_only(models[name],
                        variant=('donor384' if name == 'primary384' else 'legacy8') if label == 'original_donor' else 'student768',
                        head=name, input_vector=vector, codec=codec, **baseline_plan['budgets'][name])
                    grammar.inspect_source_only_generation(receipt, codec)
                    records.append({'id': row['id'], 'source_text': row['source_text'], 'source_sha256': row['source_sha256'],
                        'head': name, 'variant': label, 'control': 'source', 'evaluation_role': row['evaluation_role'],
                        'intervention': intervention, 'generation': receipt})
            panel = {'schema': 'gte-grammar-control-generation/v1', 'variant': label, 'control': 'source',
                'reference_prefix_used': False, 'references_used_for_generation': False, 'rows': records}
            if repetition == 0:
                exports.append(write(output / ('generation-' + label + '.json'), panel))
            else:
                original = read_ref(exports[base.VARIANTS.index(label)])
                require(digest(original) == digest(panel), 'full fresh-private-model grammar replay differs: ' + label)
            print(__import__('json').dumps({'variant': label, 'repetition': repetition, 'rows': len(records)}), flush=True)
            del models
    replay_ref = write(output / 'numerical-replay.json', {'schema': 'gte-grammar-controls-replay/v1',
        'rows_replayed': 310, 'all_generated_tokens_logits_and_receipts_exact': True,
        'fresh_private_models_loaded': True, 'generation_files': exports, 'optimizer_steps': 0,
        'reference_prefix_used': False, 'proof_authority': False})
    generation_freeze = write(output / 'generation-frozen.json', {'schema': 'gte-grammar-controls-frozen/v1',
        'plan': plan_ref, 'inputs': input_ref, 'generation_files': exports, 'generation_count': 310,
        'numerical_replay': replay_ref, 'all_variants_completed': True, 'scoring_started': False,
        'reference_prefix_used': False, 'captured_at_utc': datetime.now(timezone.utc).isoformat()})
    # Only now score references and read the unmasked scoring report.
    source, ev = admitted['source'], admitted['evaluation']
    baseline_summary = read_ref(file_ref(baseline_directory / 'summary.json'))
    require(baseline_summary['generation_freeze'] == freeze_ref, 'unmasked summary refers to a different generation')
    baseline_scores = read_ref(baseline_summary['scores'])
    require(baseline_scores['generation_freeze'] == freeze_ref, 'unmasked scores refer to a different generation')
    baseline_lookup = {(r['variant'], r['head'], r['id']): r for r in baseline_scores['rows'] if r['control'] == 'source'}
    require(len(baseline_lookup) == 310, 'complete source baseline scores required')
    rows, summary = [], []
    for ref in exports:
        panel = read_ref(ref)
        label = panel['variant']
        baseline_generation = next(r for r in frozen['generation_files'] if Path(r['path']).name == 'generation-' + label + '-source.json')
        original_rows = read_ref(baseline_generation)['rows']
        for name in base.HEADS:
            selected = [r for r in panel['rows'] if r['head'] == name]
            unmasked = [r for r in original_rows if r['head'] == name]
            changed = compare_panel(selected, unmasked)
            codec = init['primary' if name == 'primary384' else 'legacy8']['codec']
            scored = []
            for row in selected:
                reference = next(r['reference'] for r in ev['heads'][name]['rows'] if r['id'] == row['id'])
                value = source.score_generation({key: row['generation'][key] for key in ('generated_ids', 'terminated', 'truncated')},
                    reference, codec, name)
                baseline = baseline_lookup[(label, name, row['id'])]
                require(baseline['source_sha256'] == row['source_sha256'], 'baseline scoring source changed')
                scored.append({'id': row['id'], 'source_text': row['source_text'], 'source_sha256': row['source_sha256'],
                    'head': name, 'variant': label, 'control': 'source', 'evaluation_role': row['evaluation_role'],
                    'generation_file': ref, 'generation_sha256': digest(row['generation']), 'score': value,
                    'unmasked_score': baseline['score']})
            rows.extend(scored)
            summary.append({'variant': label, 'head': name, 'count': len(scored),
                'changed_generated_token_sequences': changed,
                **{metric: sum(r['score'][metric] for r in scored) for metric in (
                    'syntax_valid', 'exact_target_match', 'terminated', 'truncated', 'invalid_generation')},
                **{'unmasked_' + metric: sum(r['unmasked_score'][metric] for r in scored) for metric in (
                    'syntax_valid', 'exact_target_match', 'terminated', 'truncated', 'invalid_generation')}})
    score_ref = write(output / 'scores.json', {'schema': 'gte-grammar-control-scores/v1', 'generation_freeze': generation_freeze,
        'rows': rows, 'reference_prefix_used': False, 'independent_holdout': False, 'proof_authority': False})
    for ref in [*baseline_plan['closure'], frozen['plan'], frozen['inputs'], freeze_ref, grammar_ref, input_ref, plan_ref,
                *exports, replay_ref, generation_freeze, score_ref]:
        require(file_ref(ref['path']) == ref, 'input or generation changed during grammar evaluation')
    report = {'schema': 'gte-grammar-controls-summary/v1', 'status': 'completed_exposed_regression_unqualified',
        'generation_freeze': generation_freeze, 'numerical_replay': replay_ref, 'scores': score_ref, 'panels': summary,
        'total_generations': 310, 'replayed_generations': 310, 'reference_prefix_used': False,
        'training_executed': False, 'optimizer_steps': 0, 'independent_holdout': False,
        'source_fidelity_qualified': False, 'proof_authority': False,
        'scope': 'fixed inherited vocabularies; grammar controls syntax only; exposed historical cohort'}
    report_ref = write(output / 'summary.json', report)
    print(__import__('json').dumps({'status': report['status'], 'summary': report_ref}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-directory', required=True)
    parser.add_argument('--expected-baseline-freeze-sha256', required=True)
    parser.add_argument('--expected-grammar-sha256', required=True)
    parser.add_argument('--output-directory', required=True)
    args = parser.parse_args()
    run(args.baseline_directory, args.output_directory,
        expected_baseline_freeze_sha256=args.expected_baseline_freeze_sha256, expected_grammar_sha256=args.expected_grammar_sha256)


if __name__ == '__main__':
    main()
