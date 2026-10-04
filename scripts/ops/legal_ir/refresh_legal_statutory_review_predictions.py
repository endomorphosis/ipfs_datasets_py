#!/usr/bin/env python3
"""Refresh source-only predictions on a pinned, unadjudicated US Code packet.

Predictions are review material, never gold labels. Exact-text grouping is a
compute optimization; each original observation retains its separate context.
No source fetching, annotation admission, fitting or checkpoint selection occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_grounding_experiment as shared
from scripts.ops.legal_ir import audit_legal_grounding_experiment as audit

require, read_ref, ref, write = shared.require, shared.read_ref, shared.ref, shared.write


def source_projection(packet):
    require(packet['repository'] == 'justicedao/uscode-autoformal-span-cache'
        and packet['training_qualified'] is False and packet['status'] == 'unreviewed',
        'pinned unreviewed statutory packet required')
    sources, observations, seen = [], {}, set()
    for group in packet['groups']:
        require(group['training_qualified'] is False and group['gold_target'] is None
            and group['adjudication'] is None and group['independent_reviews'] == [],
            'review refresh cannot silently discard existing adjudication')
        identity, text = group['text_group_id'], group['source_text']
        source = shared.source_rows([{'id': identity, 'source_text': text,
            'source_sha256': group['source_text_sha256']}])[0]
        require(identity == 'source-text-sha256:' + source['source_sha256'] and identity not in observations,
            'unique exact-text group identity required')
        bindings = []
        for observation in group['source_observations']:
            span_id = observation['source_span_id']
            require(span_id not in seen and observation['source_text_variants'] == [text]
                and observation['training_qualified'] is False and observation['gold_target'] is None,
                'source observation identity, context or admission differs')
            seen.add(span_id)
            bindings.append({'source_span_id': span_id, 'legal_ids': observation['legal_ids'],
                'available_context': observation['available_context'], 'context_review': observation['context_review'],
                'producer_occurrence_count': observation['occurrence_count'],
                'context_verified': False, 'training_qualified': False, 'gold_target': None})
        require(bindings, 'nonempty observation membership required')
        sources.append(source); observations[identity] = bindings
    declared = packet['deduplication']
    require(len(sources) == declared['unique_text_groups'] and len(seen) == declared['source_observations'],
        'complete source observation denominator required')
    return sources, observations


def source_only_generate(decoder, sources, *, parent):
    require(all(set(row) == {'id', 'source_text', 'source_sha256'} for row in sources),
        'only source text and identity may cross inference boundary')
    result = shared.generate(decoder, sources, parent=parent)
    for prediction, source in zip(result['rows'], sources): audit.verify_prediction(prediction, source)
    return result


def validate_model_freeze(frozen):
    require(frozen.get('schema') == 'legal-construction-retention-experiment/v1'
        and frozen.get('all_selection_and_generation_complete') is True
        and frozen.get('challenge_targets_opened') is False and frozen.get('regression_targets_opened') is False
        and type(frozen.get('executed_optimizer_updates')) is int and frozen['executed_optimizer_updates'] == 0
        and frozen.get('training_executed') is False, 'completed reference-free selection freeze required')
    models = frozen['models']
    arms = ('prior_continuation', 'prior_grounding', 'document_retained_continuation', 'document_retained_grounding', 'parent')
    expected = {f'{arm}-{seed}' for arm in arms for seed in (1729, 1730, 1731)}
    require(len(models) == 15 and {m['name'] for m in models} == expected,
        'all fifteen selected experiment slots required')
    for item in models:
        require(item['name'] == f"{item['arm']}-{item['seed']}" and item['arm'] in arms
            and item['seed'] in (1729, 1730, 1731) and type(item['new_optimizer_steps']) is int
            and item['new_optimizer_steps'] == 0, 'model slot attribution differs')
        if item['arm'] == 'parent':
            require(item['decoder_kind'] == item['architecture'] == item['curriculum'] == 'parent'
                and item['selection'] == 'unchanged_parent' and item['selected_steps'] == 0
                and item['enabled'] is item['requested_enabled'] is False, 'parent identity differs')
            continue
        architecture = 'grounding' if item['arm'].endswith('_grounding') else 'continuation'
        require(item['architecture'] == architecture and item['decoder_kind'] == 'mixed'
            and item['enabled'] is item['requested_enabled'] is (architecture == 'grounding'), 'architecture identity differs')
        if item['arm'].startswith('prior_'):
            require(item['selection'] == 'prior_selected' and item['curriculum'] == 'temporal_augmented'
                and item['selected_steps'] == 800, 'prior control identity differs')
        elif item['selection'] == 'baseline_fallback':
            require(item['curriculum'] == 'baseline' and item['selected_steps'] == 800, 'fallback identity differs')
        else:
            require(item['selection'] == 'candidate' and item['curriculum'] == 'temporal_augmented'
                and item['selected_steps'] in (400, 800), 'candidate identity differs')
    return models


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    frozen_ref, packet_ref = ref(args.generation_freeze), ref(args.review_packet)
    frozen, packet = read_ref(frozen_ref), read_ref(packet_ref)
    models = validate_model_freeze(frozen)
    require(read_ref(frozen['heads']) == models, 'selected model bank differs from frozen heads')
    experiment_plan = read_ref(frozen['plan'])
    require(all(shared.sha(path) == wanted for path, wanted in experiment_plan['producer_pins'].items()),
        'source experiment producer drift')
    sources, observations = source_projection(packet)
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    pins = {str(Path(module.__file__).resolve()): shared.sha(module.__file__)
        for module in (shared, audit, dimensions, mixed, sys.modules[__name__])}
    source_ref = write(output / 'source-inputs.json', sources)
    plan_ref = write(output / 'plan.json', {'schema': 'legal-statutory-prediction-refresh/v1',
        'generation_freeze': frozen_ref, 'review_packet': packet_ref, 'sources': source_ref,
        'models': models, 'producer_pins': pins, 'source_group_count': len(sources),
        'source_observation_count': sum(map(len, observations.values())),
        'fitting_performed': False, 'checkpoint_selection_performed': False,
        'source_context_recovered': False, 'reference_accuracy_available': False})
    outputs, metrics, by_model = {}, {}, {}
    for item in models:
        parent = item['decoder_kind'] == 'parent'
        require(parent or item['decoder_kind'] == 'mixed', 'unsupported decoder kind')
        module, cls = (dimensions, dimensions.DimensionalSpanDecoder) if parent else (mixed, mixed.MixedReplayDecoder)
        checkpoint = module.load_checkpoint(item['checkpoint']['path'], expected_sha256=item['checkpoint']['sha256'])
        generated = source_only_generate(cls(checkpoint), sources, parent=parent)
        replayed = source_only_generate(cls(checkpoint), sources, parent=parent)
        require(generated == replayed, 'statutory source-only prediction replay differs')
        outputs[item['name']] = write(output / (item['name'] + '-generation.json'), generated)
        counts = Counter(r['status'] for r in generated['rows'])
        metrics[item['name']] = {'source_groups': len(sources), 'decoded': counts['decoded'], 'abstained': counts['abstained'],
            'decoder_kind': item['decoder_kind'], 'selection': item['selection'], 'checkpoint': item['checkpoint'],
            'reference_accuracy': None, 'training_qualified': False, 'exact_numerical_replay': True}
        by_model[item['name']] = generated['rows']
        print({'phase': 'statutory_review_generated', 'model': item['name'], 'decoded': counts['decoded']}, flush=True)
    group_rows = []
    for index, source in enumerate(sources):
        predictions = {name: rows[index] for name, rows in by_model.items()}
        decisions = {shared.digest({'status': row['status'], 'canonical_ir': row['canonical_ir']}) for row in predictions.values()}
        group_rows.append({**source, 'observations': observations[source['id']],
            'prediction_references': {name: {'artifact': outputs[name], 'row_index': index} for name in outputs},
            'distinct_status_and_canonical_outputs': len(decisions),
            'decoded_model_slots': sum(row['status'] == 'decoded' for row in predictions.values()),
            'model_disagreement_is_error_label': False, 'context_verified': False,
            'independent_reviews': [], 'adjudication': None, 'gold_target': None, 'training_qualified': False})
    require(all(shared.sha(path) == wanted for path, wanted in pins.items()), 'review producer changed')
    read_ref(frozen_ref); read_ref(packet_ref)
    return write(output / 'summary.json', {'schema': 'legal-statutory-prediction-refresh/v1', 'plan': plan_ref,
        'repository': packet['repository'], 'revision': packet['revision'], 'source_packet': packet_ref,
        'model_generation_freeze': frozen_ref, 'generations': outputs, 'models': metrics, 'groups': group_rows,
        'source_groups': len(sources), 'source_observations': sum(map(len, observations.values())),
        'model_source_slots': len(models) * len(sources), 'inference_records_replayed': len(models) * len(sources),
        'admitted_statutory_gold_examples': 0, 'source_context_recovered': False,
        'reference_accuracy_available': False, 'training_performed': False, 'qualified': False,
        'scope': packet['scope'], 'context_policy': 'Identical text shares inference only; legal context and adjudication remain separate per original source_span_id.',
        'review_acceptance_requirements': packet['review_acceptance_requirements'],
        'limitations': ['This diagnostic export is not a census or representative statutory test.',
            'A decoded output or model agreement does not establish statutory meaning.',
            'No source document version, definitions or cross-references were recovered by this refresh.',
            'No statutory compilation result or semantic accuracy is claimed.']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generation-freeze', required=True)
    parser.add_argument('--review-packet', required=True)
    parser.add_argument('--output', required=True)
    print(run(parser.parse_args()))
