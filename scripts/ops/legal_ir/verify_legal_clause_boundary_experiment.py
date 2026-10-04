#!/usr/bin/env python3
"""Posthoc independent clause-model replay, inventory and compiler-receipt audit.

Replays inference, not optimizer trajectories. Existing build receipts are
reconstructed and verified; this verifier does not execute a second compiler.
"""
from __future__ import annotations

import argparse
from collections import Counter
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as experiment
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as composition
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as calendar_summary

require, digest, read = boundary.require, boundary.digest, experiment.read


def independent_counts(generation, references):
    require(len(generation['rows']) == len(references) and len({r['candidate_id'] for r in references}) == len(references),
            'complete unique document denominator required')
    counts = Counter()
    for prediction, gold in zip(generation['rows'], references):
        require(prediction['candidate_id'] == gold['candidate_id'] and prediction['source_sha256'] == gold['source_sha256']
            == boundary.text_sha(gold['source_text']), 'prediction/reference source identity differs')
        require(prediction['status'] in ('segmented', 'abstained') and prediction['target_access'] is False,
                'source-only prediction status required')
        tokens = boundary.tokenize(gold['source_text'])
        ends = prediction['boundary_token_indices']
        require(ends == sorted(set(ends)) and all(type(i) is int and 0 <= i < len(tokens) for i in ends)
            and prediction['predicted_rule_count'] == len(ends), 'boundary inventory/count differs')
        require(len(prediction['boundary_logits']) == len(tokens) and all(math.isfinite(v) for v in prediction['boundary_logits'])
            and ends == [i for i, value in enumerate(prediction['boundary_logits']) if value >= 0.], 'boundary logits/decisions differ')
        if prediction['status'] == 'segmented':
            plan = prediction['plan']
            composition.validate_source_plan(plan, expected_plan_sha256=plan['plan_sha256'])
            require(plan['source'] == {key: gold[key] for key in ('candidate_id', 'source_text', 'source_sha256')}
                and [r['char_end'] for r in plan['clauses']] == [tokens[i]['char_end'] for i in ends], 'complete source plan differs from predicted boundaries')
        else:
            require(prediction['plan'] is None, 'abstention retained a partial plan')
        counts['documents'] += 1; counts[prediction['status']] += 1
        counts['raw_scope_correct'] += prediction['raw_learned_scope_supported'] == gold['supported']
        counts['surface_guard_rejections'] += prediction['reason'] == 'declared_surface_policy_unsupported_scope'
        if gold['supported']:
            counts['supported_documents'] += 1
            wanted = [(r['char_start'], r['char_end']) for r in gold['clauses']]
            actual = [(r['char_start'], r['char_end']) for r in prediction['plan']['clauses']] if prediction['plan'] else []
            exact = actual == wanted
            counts['exact_supported_segmentation'] += exact
            counts['raw_boundary_document_exact'] += [tokens[i]['char_end'] for i in ends] == [r['char_end'] for r in gold['clauses']]
            counts['rule_count_correct'] += len(ends) == len(wanted)
            counts['reference_rule_occurrences'] += len(wanted)
            counts['raw_supported_scope_correct'] += prediction['raw_learned_scope_supported']
            if gold['repeated_rule_occurrences']:
                counts['repeated_documents'] += 1; counts['repeated_documents_exact'] += exact
        else:
            counts['unsupported_documents'] += 1
            counts['unsupported_abstained'] += prediction['status'] == 'abstained'
            counts['unsupported_accepted'] += prediction['status'] == 'segmented'
            counts['raw_unsupported_scope_correct'] += not prediction['raw_learned_scope_supported']
            exact = prediction['status'] == 'abstained'
        counts['document_decision_exact'] += exact
    return dict(counts)


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as span
    directory = Path(args.run_directory).resolve()
    summary_ref = experiment.ref(directory / 'summary.json'); summary = read(summary_ref)
    plan = read(summary['plan']); training = read(summary['training'])
    require(all(experiment.files.sha(path) == value for path, value in plan['producer_pins'].items()), 'frozen producer changed')
    require(training['optimizer_steps_executed'] == len(training['losses']) == plan['training_steps'] == 600
        and training['torch_threads'] == 1 and training['test_references_read'] is False, 'training budget/declaration differs')
    initial = read(training['initial'])
    torch.manual_seed(boundary.CONFIG['seed'])
    reconstructed = boundary.checkpoint(boundary.model(torch), steps=0,
        training_manifest_sha256=initial['training_manifest_sha256'], tuning_manifest_sha256=initial['tuning_manifest_sha256'])
    require(initial == reconstructed, 'initialization does not reproduce the pinned deterministic model')
    train, tune = read(plan['references']['train']), read(plan['references']['tuning'])
    require(digest(train) == initial['training_manifest_sha256'] and digest(tune) == initial['tuning_manifest_sha256'],
            'fitting manifest hash differs')
    source_panels = {key: read(value) for key, value in plan['sources'].items()}
    stages, replay_rows = [], 0
    for stage in training['stages']:
        cp = read(stage['checkpoint']); saved = read(stage['tuning'])
        require(cp['optimizer_steps'] == stage['steps'] and cp['training_manifest_sha256'] == digest(train)
            and cp['tuning_manifest_sha256'] == digest(tune), 'stage fitting/step commitment differs')
        replay = experiment.decode_all(boundary.ClauseBoundaryDecoder(cp), source_panels['tuning'])
        require(replay == saved['generation'], 'fresh tuning output/logit replay differs')
        measured = independent_counts(replay, tune)
        require(all(saved['metrics'].get(k, 0) == v for k, v in measured.items()), 'independent tuning counts differ')
        require(stage['document_decision_exact'] == measured['document_decision_exact']
            and stage['exact_supported_segmentation'] == measured['exact_supported_segmentation'], 'recorded tuning choice differs')
        stages.append(stage); replay_rows += len(tune)
    chosen = max(stages, key=lambda row: (row['document_decision_exact'], row['exact_supported_segmentation'], -row['steps']))
    require(chosen == training['selected'] and chosen['steps'] == summary['selected_step'], 'tuning-only stage selection differs')
    generations = {}
    for label, checkpoint, frozen in (
        ('selected', read(chosen['checkpoint']), read(summary['test_generation'])['generation']),
        ('untrained', initial, read(summary['initial_test_generation']))):
        generations[label] = experiment.decode_all(boundary.ClauseBoundaryDecoder(checkpoint), source_panels['test'])
        require(generations[label] == frozen, 'fresh test boundary output/logit replay differs')
        replay_rows += len(source_panels['test'])
    saved_compositions = read(summary['composition'])['rows']
    clause_cp = span.load_checkpoint(plan['clause_decoder']['path'], expected_sha256=plan['clause_decoder']['sha256'])
    replay_compositions = experiment.integrate(generations['selected'], source_panels['test'], span.DimensionalSpanDecoder(clause_cp))
    require(replay_compositions == saved_compositions, 'fresh clause inference/composition replay differs')
    clause_rows = sum(len(row['clause_generation']['rows']) for row in replay_compositions if row['clause_generation'])
    builds = read(summary['builds']); selection = read(builds['selection'])
    entries = {row['candidate']['candidate_id']: row for row in selection['entries']}
    require(len(entries) == len(selection['entries']), 'duplicate selected compilation document')
    composed = {row['candidate_id']: row['composition'] for row in saved_compositions if row['composition']}
    excluded = {row['candidate_id'] for row in selection['excluded_compositions']}
    require(set(entries).isdisjoint(excluded) and set(entries) | excluded == set(composed), 'composition/build selection inventory differs')
    for identity, entry in entries.items():
        value = composed[identity]
        composition.validate_composition(value, expected_plan_sha256=value['source_plan_sha256'])
        candidate = composition.calendar_candidate(value, expected_plan_sha256=value['source_plan_sha256'])
        require(entry == {'candidate': candidate, 'interpretation': calendar_summary.expected_interpretation(candidate)},
                'build entry drops or changes composed fields')
    covered, built = [], set()
    for batch in builds['builds']:
        ids = batch['candidate_ids']; covered.extend(ids)
        receipt = calendar_summary.verify_receipt(batch['receipt'], [entries[i] for i in ids])
        require(receipt['build_passed'] == batch['build_passed'] and receipt['backend_executed'] == batch['backend_executed'],
                'build execution declaration differs')
        if receipt['build_passed']: built.update(ids)
    require(len(covered) == len(set(covered)) == len(entries) and set(covered) == set(entries), 'actual build inventory coverage differs')
    # Numerical replay and existing compiler receipts are verified before test labels.
    test = read(plan['references']['test'])
    require(experiment.source_rows(test) == source_panels['test'], 'posthoc source/reference identity differs')
    counts = independent_counts(generations['selected'], test)
    require(all(summary['segmentation_metrics'].get(k, 0) == v for k, v in counts.items()), 'independent held-out counts differ')
    corpus_validation = experiment.validate_corpus({'train': train, 'tuning': tune, 'test': test}, read(plan['fixtures']))
    require(corpus_validation == plan['corpus_validation'], 'split/fixture disjointness audit differs')
    by_id = {row['candidate_id']: row for row in test}
    errors, facets = [], Counter()
    exact = 0
    for identity, value in composed.items():
        target = by_id[identity]
        expected = [row['rule'] for row in target['clauses']]
        actual = value['source_rule_list']
        match = target['supported'] and actual == expected
        exact += match
        if not match:
            differences = []
            for ordinal, (candidate, gold) in enumerate(zip(actual, expected)):
                for field in gold:
                    if candidate[field] != gold[field]:
                        facets[field] += 1
                        differences.append({'source_ordinal': ordinal, 'field': field, 'candidate': candidate[field], 'reference': gold[field]})
            errors.append({'candidate_id': identity, 'source_sha256': target['source_sha256'], 'source_text': target['source_text'],
                'predicted_rule_count': len(actual), 'reference_rule_count': len(expected), 'facet_differences': differences,
                'compiled': identity in built, 'label_origin': target['label_origin']})
    require(exact == summary['end_to_end_metrics']['exact_supported_documents']
        and len(built) == summary['end_to_end_metrics']['built_documents'], 'end-to-end counts differ')
    result = {'schema': 'legal-clause-boundary-independent-audit/v1', 'summary': summary_ref,
        'verifier': experiment.ref(__file__), 'boundary_document_rows_replayed': replay_rows,
        'clause_decoder_rows_replayed': clause_rows, 'exact_recorded_outputs_logits_and_receipts': True,
        'selected_step': chosen['steps'], 'independent_segmentation_counts': counts,
        'split_validation': corpus_validation, 'compiled_documents': len(built), 'exact_supported_documents': exact,
        'end_to_end_wrong_facet_occurrences': dict(facets), 'compiled_mismatch_documents': errors,
        'optimizer_trajectory_replayed': False, 'compiler_reexecuted_by_this_verifier': False,
        'original_native_build_receipts_independently_reconstructed': True, **boundary.FALSE}
    experiment.write(args.output, result)
    print({'output': args.output, 'boundary_rows': replay_rows, 'clause_rows': clause_rows,
           'compiled_documents': len(built), 'exact_supported_documents': exact}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', required=True); parser.add_argument('--output', required=True)
    run(parser.parse_args())
