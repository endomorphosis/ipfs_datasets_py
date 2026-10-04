#!/usr/bin/env python3
"""Posthoc tuning-only failure attribution; no fitting, inference or holdout reads."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_role_curriculum_experiment as runner

FACETS = ('actor', 'modality', 'action', 'object', 'conditions', 'exceptions', 'temporal')
RETENTION = ('earlier', 'temporal', 'prior_consistency', 'document_parent', 'document_expanded')
SCHEMA = 'legal-role-curriculum-posthoc-tuning-failures/v1'
require, read_ref, ref, write, digest = runner.require, runner.read_ref, runner.ref, runner.write, runner.digest


def clause_failures(reference, boundary_row, prediction):
    """Attribute only exact source intervals, including whole-document abstentions."""
    plan = boundary_row.get('plan')
    require(reference['supported'] is True and plan is not None, 'accepted supported boundary required')
    require(reference['candidate_id'] == prediction['candidate_id'] == boundary_row['candidate_id']
        and reference['source_sha256'] == prediction['source_sha256'], 'document source binding differs')
    clauses = plan['clauses']
    expected = reference['clauses']
    require(len(clauses) == len(expected) and
        [(c['char_start'], c['char_end']) for c in clauses] ==
        [(c['char_start'], c['char_end']) for c in expected], 'exact occurrence boundaries required')
    generation = prediction['clause_generation']
    require(generation is not None and len(generation['rows']) == len(clauses), 'complete clause occurrence reports required')
    result = []
    for ordinal, (source, target, row) in enumerate(zip(clauses, expected, generation['rows'])):
        start, end = source['char_start'], source['char_end']
        require(reference['source_text'][start:end] == source['source_text']
            and row['source_sha256'] == source['source_sha256'], 'clause occurrence source binding differs')
        actual = row.get('canonical_ir')
        wrong = {}
        if row['status'] == 'abstained':
            kind = 'clause_abstention'
        else:
            require(row['status'] == 'decoded' and type(actual) is dict
                and len(actual['rules']) == 1 and set(actual['rules'][0]) == set(FACETS), 'one complete decoded rule required')
            wrong = {facet: {'expected': target['rule'][facet], 'actual': actual['rules'][0][facet]}
                for facet in FACETS if target['rule'][facet] != actual['rules'][0][facet]}
            kind = 'wrong_canonical_facets' if wrong else 'clause_exact'
        result.append({'source_ordinal': ordinal, 'char_start': start, 'char_end': end,
            'source_text': source['source_text'], 'source_sha256': source['source_sha256'],
            'kind': kind, 'reason': row.get('reason'), 'wrong_facets': wrong,
            'reference_rule': target['rule'], 'predicted_canonical_ir': actual})
    return result


def family_counts(generation, references, labels):
    require(len(generation['rows']) == len(references) == len(labels), 'complete tuning inventory required')
    totals = {}
    for row, target, label in zip(generation['rows'], references, labels):
        require(target['id'] == label['id'] and row['source_sha256'] == label['source_sha256'], 'tuning family/source binding differs')
        item = totals.setdefault(label['family'], {'count': 0, 'exact': 0, 'decoded': 0, 'abstained': 0})
        item['count'] += 1
        item['decoded'] += row['status'] == 'decoded'
        item['abstained'] += row['status'] == 'abstained'
        item['exact'] += row['status'] == 'decoded' and row.get('canonical_ir') == target['canonical_ir']
    return totals


def run(config_path, run_directory, output):
    from scripts.ops.legal_ir import prepare_legal_role_curriculum as corpus
    # load_config admits only fitting/tuning labels and source-only evaluations.
    inputs = runner.load_config(config_path)
    generated_tuning, labels, pairs = corpus.make_panel('tuning')
    require(generated_tuning == inputs['tuning']['new'] and pairs == inputs['tuning_pairs'],
        'regenerated admitted tuning metadata differs from frozen rows')
    frozen_ref = ref(Path(run_directory) / 'generation-frozen.json'); frozen = read_ref(frozen_ref)
    require(frozen['all_training_selection_and_generation_complete'] is True, 'completed generation freeze required')
    selection = read_ref(frozen['selections']); documents = {r['candidate_id']: r for r in inputs['document_tuning']}
    trials = []; aggregate = {}
    for trial in selection['trials']:
        parent = trial['parent_tuning']; stages = []
        parent_new = read_ref(parent['tuning_new'])['generation']
        pdoc = read_ref(parent['document_tuning_expanded'])
        head = 'expanded-' + str(trial['seed'])
        boundary = read_ref(frozen['boundaries'][head]['document_tuning'])
        by_boundary = {r['candidate_id']: r for r in boundary['rows']}
        pscore = runner.retention.score_document_tuning(pdoc['generation'], inputs['document_tuning'])
        require(pscore == pdoc['metrics'], 'parent document tuning metrics differ')
        parent_exact = {r['id'] for r in pscore['rows'] if r['exact']}
        for stage in trial['stages']:
            metrics = {}
            for key in (*RETENTION, 'new'):
                field = 'tuning_' + key + '_exact'; minimum = parent[field] - 1 if key in RETENTION else None
                metrics[key] = {'parent': parent[field], 'candidate': stage[field], 'delta': stage[field] - parent[field],
                    'minimum': minimum, 'passed': stage[field] >= minimum if minimum is not None else None}
            for policy in ('parent', 'expanded'):
                field = 'tuning_document_' + policy + '_unsupported_accepted'
                metrics['unsupported_accepted_' + policy] = {'parent': parent[field], 'candidate': stage[field],
                    'delta': stage[field] - parent[field], 'maximum': 0, 'passed': stage[field] == 0}
            stages.append({'steps': stage['steps'], 'checkpoint': stage['checkpoint'], 'eligible': stage['eligible'],
                'gate_deltas': metrics, 'new_tuning_by_family': family_counts(read_ref(stage['tuning_new'])['generation'],
                    inputs['tuning']['new'], labels)})
        final = trial['stages'][-1]; require(final['steps'] == 400, 'fixed400 final stage required')
        finaldoc = read_ref(final['document_tuning_expanded'])
        score = runner.retention.score_document_tuning(finaldoc['generation'], inputs['document_tuning'])
        require(score == finaldoc['metrics'], 'stage400 document tuning metrics differ')
        final_exact = {r['id'] for r in score['rows'] if r['exact']}
        lost, gained = sorted(parent_exact - final_exact), sorted(final_exact - parent_exact)
        rows = {r['candidate_id']: r for r in finaldoc['generation']['rows']}
        details = []; kinds = Counter(); facets = Counter(); reasons = Counter()
        for cid in lost:
            failures = clause_failures(documents[cid], by_boundary[cid], rows[cid])
            nonexact = [r for r in failures if r['kind'] != 'clause_exact']
            require(nonexact, 'lost exact document lacks a clause-level error')
            for failure in nonexact:
                kinds[failure['kind']] += 1
                facets.update(failure['wrong_facets'].keys())
                if failure['kind'] == 'clause_abstention': reasons[str(failure['reason'])] += 1
            details.append({'candidate_id': cid, 'construction': documents[cid]['construction'],
                'source_text': documents[cid]['source_text'], 'source_sha256': documents[cid]['source_sha256'],
                'all_reference_intervals_exact': True, 'composition_present': rows[cid]['composition'] is not None,
                'clause_count': len(failures), 'clause_exact': len(failures) - len(nonexact), 'errors': nonexact})
        name = trial['architecture']; arm = aggregate.setdefault(name, {'trial_count': 0, 'new_tuning_slots': 0,
            'parent_new_exact': 0, 'stage400_new_exact': 0, 'supported_document_slots': 0,
            'parent_document_exact': 0, 'stage400_document_exact': 0, 'lost_document_slots': 0,
            'gained_document_slots': 0, 'lost_clause_error_kinds': Counter(), 'lost_clause_wrong_facets': Counter(),
            'lost_clause_abstention_reasons': Counter()})
        arm['trial_count'] += 1; arm['new_tuning_slots'] += 96; arm['supported_document_slots'] += 72
        arm['parent_new_exact'] += parent['tuning_new_exact']; arm['stage400_new_exact'] += final['tuning_new_exact']
        arm['parent_document_exact'] += len(parent_exact); arm['stage400_document_exact'] += len(final_exact)
        arm['lost_document_slots'] += len(lost); arm['gained_document_slots'] += len(gained)
        arm['lost_clause_error_kinds'].update(kinds); arm['lost_clause_wrong_facets'].update(facets)
        arm['lost_clause_abstention_reasons'].update(reasons)
        trials.append({'name': trial['name'], 'parent': trial['parent'], 'selection': trial['selection'],
            'selected_steps': trial['selected_steps'], 'parent_new_tuning_by_family': family_counts(parent_new, inputs['tuning']['new'], labels),
            'stages': stages, 'stage400_expanded_document_transition': {'supported': 72, 'unsupported': 24,
                'parent_exact': len(parent_exact), 'stage400_exact': len(final_exact), 'lost_ids': lost, 'gained_ids': gained,
                'lost_clause_error_kinds': dict(kinds), 'lost_clause_wrong_facets': dict(facets),
                'lost_clause_abstention_reasons': dict(reasons), 'lost_documents': details,
                'parent_generation': parent['document_tuning_expanded'], 'stage400_generation': final['document_tuning_expanded'],
                'fixed_boundary_generation': frozen['boundaries'][head]['document_tuning']}})
    result = {'schema': SCHEMA, 'analyzer': ref(__file__), 'generation_freeze': frozen_ref,
        'config': ref(config_path), 'selections': frozen['selections'], 'tuning_metadata_origin':
        'Only admitted tuning panel regenerated from pinned authored producer, exactly matched to frozen tuning rows and pairs.',
        'trials': trials, 'aggregate_by_architecture': aggregate, 'fitting_executed': False,
        'inference_executed': False, 'challenge_targets_or_sealed_annotation_ledger_opened': False,
        'checkpoint_selection_changed': False, 'rejected_checkpoints_preserved': True,
        'limits': ['Posthoc tuning diagnosis, not heldout evidence or an independent statutory judgment.',
            'Pooled seed slots share the same96 single tuning cases and72 supported document cases.',
            'All clause attributions retain exact source occurrence intervals; abstentions are errors, not omitted rows.',
            'No matched old-data-only400-update arm isolates curriculum from optimization and optimizer reset.']}
    return write(output, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True); parser.add_argument('--run-directory', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(); print(run(args.config, args.run_directory, args.output))
