#!/usr/bin/env python3
"""Combine frozen learned boundaries with all retained temporal-curriculum model slots.

The96 authored document outcomes are already exposed. This is a fixed transfer
regression, never a new independent test or checkpoint selection. All generations
and actual builds freeze before this execution opens document reference labels.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as clauses
from scripts.ops.legal_ir import run_legal_temporal_curriculum_experiment as temporal_run
from scripts.ops.legal_ir import transfer_mixed_replay_legal_clause_pipeline as previous_transfer
from scripts.ops.legal_ir import verify_legal_clause_boundary_experiment as boundary_audit
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as compose
from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as calendar
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as calendar_summary

require, read_ref, ref = temporal_run.require, temporal_run.read_ref, temporal_run.ref
SCHEMA = 'legal-learned-boundary-temporal-curriculum-transfer/v1'
SEEDS = (1729, 1730, 1731)
ARMS = (*temporal_run.ARMS, 'parent')


def model_inventory(frozen, heads):
    require(frozen['schema'] == temporal_run.SCHEMA and frozen['all_training_selection_and_generation_complete'] is True
        and frozen['challenge_targets_opened'] is False and frozen['regression_targets_opened'] is False,
        'complete reference-free temporal curriculum model freeze required')
    expected = {f'{arm}-{seed}' for arm in ARMS for seed in SEEDS}
    models = frozen['models']; names = {r['name'] for r in models}
    require(len(models) == len(names) == 15 and names == expected and set(frozen['files']) == names,
            'all twelve retained model slots and three unchanged parents required')
    require(len(heads) == 12 and {r['name'] for r in heads} == {f'{arm}-{seed}' for arm in ARMS[:-1] for seed in SEEDS},
            'all twelve retained temporal model slots required')
    by_name = {r['name']: r for r in models}
    for head in heads:
        require(by_name[head['name']] == head, 'model differs from frozen retained head')
    for item in models:
        require(item['name'] == f"{item['arm']}-{item['seed']}" and item['seed'] in SEEDS
            and type(item['enabled']) is bool and type(item['requested_enabled']) is bool,
            'model attribution or branch differs')
        if item['arm'] == 'parent':
            require(item['decoder_kind'] == 'parent' and item['selection'] == 'unchanged_parent'
                and item['enabled'] is False and item['requested_enabled'] is False
                and item['selected_steps'] == item['executed_steps'] == 0
                and item['architecture'] == item['curriculum'] == 'parent', 'unchanged parent attribution differs')
            continue
        require(item['parent'] == by_name[f"parent-{item['seed']}"]['checkpoint'], 'matched source parent differs')
        settings = temporal_run.ARMS[item['arm']]
        require(item['architecture'] == settings['architecture'] and item['curriculum'] == settings['curriculum']
            and item['requested_enabled'] is settings['enabled'] and item['executed_steps'] == 800,
            'requested architecture/curriculum/branch or completed budget differs')
        require([stage['steps'] for stage in item['stages']] == [400, 800], 'complete two-stage inventory required')
        selected = temporal_run.select_retained_stage(item['stages'], item['parent_tuning_exact']['earlier'])
        if selected is None:
            require(item['selection'] == 'parent_fallback' and item['decoder_kind'] == 'parent'
                and item['checkpoint'] == item['parent'] and item['selected_steps'] == 0 and item['enabled'] is False,
                'parent fallback identity or selection differs')
        else:
            require(item['selection'] == 'candidate' and item['decoder_kind'] == 'mixed'
                and item['checkpoint'] == selected['checkpoint'] and item['selected_steps'] == selected['steps']
                and item['enabled'] is item['requested_enabled'], 'retained mixed selection or branch differs')
    require(sorted(frozen['retention_gate_failures']) == sorted(r['name'] for r in heads if r['selection'] == 'parent_fallback'),
        'retention failure denominator differs')
    return models


def load(item):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    require(item['decoder_kind'] in ('parent', 'mixed'), 'unsupported decoder kind')
    module, cls = (dimensions, dimensions.DimensionalSpanDecoder) if item['decoder_kind'] == 'parent' else (mixed, mixed.MixedReplayDecoder)
    cp = module.load_checkpoint(item['checkpoint']['path'], expected_sha256=item['checkpoint']['sha256'])
    return cls(cp)


# Reuse the frozen full-denominator, occurrence-preserving scoring contract.
score_documents = previous_transfer.score_documents


# Parent and fallback comparisons include complete numeric reports and all source
# occurrences. The unchanged policy is shared with the previous transfer.
reproduce_parents = previous_transfer.reproduce_parents


def comparison_pairs():
    """All seeds and both factors, without selecting a winning architecture."""
    pairs = []
    for seed in SEEDS:
        for curriculum in ("baseline", "temporal_augmented"):
            pairs.append((f"{curriculum}_grounding-{seed}", f"{curriculum}_continuation-{seed}", "architecture"))
        for architecture in ("continuation", "grounding"):
            pairs.append((f"temporal_augmented_{architecture}-{seed}", f"baseline_{architecture}-{seed}", "curriculum"))
        for arm in ARMS[:-1]:
            pairs.append((f"{arm}-{seed}", f"parent-{seed}", "versus_unchanged_parent"))
    return pairs


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    directory, clause_directory, output = Path(args.temporal_run).resolve(), Path(args.clause_run).resolve(), Path(args.output).resolve()
    frozen_ref = ref(directory / 'generation-frozen.json'); frozen = read_ref(frozen_ref)
    heads = read_ref(frozen['heads']); models = model_inventory(frozen, heads)
    temporal_plan = read_ref(frozen['plan'])
    require(all(temporal_run.sha(path) == wanted for path, wanted in temporal_plan['producer_pins'].items()), 'temporal curriculum producer drift')
    boundary_ref = ref(clause_directory / 'test-generation-frozen.json'); payload = read_ref(boundary_ref)
    boundary_training = read_ref(payload['training']); clause_plan_ref = boundary_training['plan']; clause_plan = read_ref(clause_plan_ref)
    source_ref = clause_plan['sources']['test']; sources = read_ref(source_ref)
    require(len(sources) == 96 and len({s['candidate_id'] for s in sources}) == 96, 'all96 exposed document sources required')
    cp_ref = boundary_training['selected']['checkpoint']; cp = read_ref(cp_ref)
    boundary_generation = clauses.decode_all(boundary.ClauseBoundaryDecoder(cp), sources)
    require(boundary_generation == payload['generation'], 'frozen learned boundary replay differs')
    require(sum(r['status'] == 'segmented' for r in boundary_generation['rows']) == 72
        and sum(r['plan']['clause_count'] for r in boundary_generation['rows'] if r['plan']) == 192,
        'frozen supported segmentation or occurrence inventory differs')
    previous_frozen_ref = ref(Path(args.prior_transfer).resolve() / 'generation-frozen.json')
    previous_frozen = read_ref(previous_frozen_ref); previous_plan = read_ref(previous_frozen['plan'])
    require(previous_plan['boundary_generation'] == boundary_ref and previous_plan['source_documents'] == source_ref,
        'prior transfer boundary or document sources differ')
    output.mkdir(parents=True, exist_ok=False)
    pins = {str(Path(module.__file__).resolve()): temporal_run.sha(module.__file__) for module in
        (boundary, clauses, compose, calendar, calendar_summary, dimensions, mixed, temporal_run,
         previous_transfer, sys.modules[score_documents.__module__], sys.modules[__name__])}
    plan_ref = clauses.write(output / 'plan.json', {'schema': SCHEMA, 'temporal_models': frozen_ref, 'prior_transfer_generation': previous_frozen_ref,
        'boundary_generation': boundary_ref, 'boundary_checkpoint': cp_ref, 'source_documents': source_ref,
        'reference_commitment': clause_plan['references']['test'], 'models': models, 'producer_pins': pins,
        'selected_by_transfer_score': False, 'training_executed': False, 'exposed_authored_transfer_regression': True,
        'independent_holdout': False, 'scope': 'Fixed96 authored documents, frozen learned segmentation, fifteen frozen decoder slots, no fitting or selection', **boundary.FALSE})
    compositions, generation_refs = {}, {}
    for item in models:
        rows = clauses.integrate(boundary_generation, sources, load(item))
        replay = clauses.integrate(boundary_generation, sources, load(item))
        require(rows == replay and len(rows) == 96, 'fresh clause model output/composition replay differs')
        folder = output / item['name']; folder.mkdir()
        generation_refs[item['name']] = clauses.write(folder / 'generation-compositions.json', {'rows': rows, 'checkpoint': item['checkpoint'],
            'boundary_generation': boundary_ref, 'exact_fresh_model_replay': True, 'reference_targets_opened': False})
        compositions[item['name']] = rows
        print({'phase': 'transferred', 'model': item['name'], 'composed': sum(r['composition'] is not None for r in rows)}, flush=True)
    prior_parent_refs = reproduce_parents(compositions, models, previous_frozen, previous_plan)
    generation_freeze = clauses.write(output / 'generation-frozen.json', {'plan': plan_ref, 'models': generation_refs,
        'all_models_completed': True, 'reference_targets_opened': False, 'documents': 1440,
        'all_three_parent_outputs_match_prior_transfer': True, 'prior_parent_generations': prior_parent_refs,
        'source_clause_occurrences_replayed': 15 * 192, 'additional_fresh_replay_clause_occurrences': 15 * 192})
    selections = {}
    for item in models:
        entries, exclusions = [], []
        for record in compositions[item['name']]:
            if record['composition'] is None:
                exclusions.append({'candidate_id': record['candidate_id'], 'reason': record['reason'], 'status': record['status']})
                continue
            value = record['composition']; plan_hash = value['source_plan_sha256']
            candidate = compose.calendar_candidate(value, expected_plan_sha256=plan_hash)
            try:
                sidecar = calendar.synthetic_interpretation(candidate, policy=calendar.POLICY)
                compose.prepare_calendar_composition(value, sidecar, expected_plan_sha256=plan_hash)
                entry = {'candidate': candidate, 'interpretation': sidecar}
                require(entry['interpretation'] == calendar_summary.expected_interpretation(candidate), 'independent interpretation differs')
                require(gate.prepare_qualified_legal([entry], toolchain=args.toolchain).to_dict()['all_candidates_supported'], 'unsupported calendar candidate')
                entries.append(entry)
            except (ValueError, KeyError, TypeError) as error:
                exclusions.append({'candidate_id': record['candidate_id'], 'reason': str(error), 'status': 'interpretation_unsupported'})
        require(len(entries) + len(exclusions) == 96, 'complete build selection denominator required')
        selections[item['name']] = {'entries': entries, 'excluded': exclusions, 'source_documents': 96}
    selection_ref = clauses.write(output / 'build-selection-frozen.json', {'models': selections,
        'generation_freeze': generation_freeze, 'reference_targets_opened': False, 'policy': calendar.POLICY})
    builds = {}
    for item in models:
        name = item['name']; entries = selections[name]['entries']; builds[name] = []
        require(0 < len(entries) <= gate.MAX_ROWS, 'exactly one bounded nonempty build per model required')
        for start in range(0, len(entries), gate.MAX_ROWS):
            batch = entries[start:start + gate.MAX_ROWS]
            folder = output / name / f'lake-{start // gate.MAX_ROWS:02d}'
            receipt = gate.build_qualified_legal(batch, toolchain=args.toolchain, lake_executable=args.lake_executable,
                timeout_seconds=60, output_directory=folder).to_dict()
            reference = ref(folder / 'qualified-receipt.json')
            require(calendar_summary.verify_receipt(reference, batch) == receipt, 'independent native compiler receipt reconstruction differs')
            require(receipt['backend_executed'] is True and len(receipt['command']) == 3
                and Path(receipt['command'][0]).name == 'lake' and receipt['command'][1:] == ['build', 'legal'],
                'actual lake build legal command required')
            builds[name].append({'receipt': reference, 'candidate_ids': [row['candidate']['candidate_id'] for row in batch],
                'build_passed': receipt['build_passed'], 'backend_executed': receipt['backend_executed'], 'command': receipt['command']})
        print({'phase': 'built', 'model': name, 'supported_documents': len(entries)}, flush=True)
    build_ref = clauses.write(output / 'builds-frozen.json', {'models': builds, 'selections': selection_ref,
        'generation_freeze': generation_freeze, 'reference_targets_opened': False})
    require(sum(len(rows) for rows in builds.values()) == 15, 'all fifteen actual builds required before labels')
    # Only now parse the already exposed authored document labels in this transfer execution.
    target_rows = read_ref(clause_plan['references']['test'])
    require(clauses.source_rows(target_rows) == sources, 'posthoc source/reference commitment differs')
    boundary_counts = boundary_audit.independent_counts(boundary_generation, target_rows)
    targets = {row['candidate_id']: row for row in target_rows}
    scored, report_models = {}, []
    for item in models:
        name = item['name']
        built = {identity for batch in builds[name] if batch['build_passed'] for identity in batch['candidate_ids']}
        metrics = score_documents(compositions[name], targets, built)
        metrics['actual_build_invocations'] = sum(batch['backend_executed'] for batch in builds[name])
        scored[name] = metrics
        report_models.append({'name': name, 'arm': item['arm'], 'seed': item['seed'],
            'checkpoint': item['checkpoint'], 'decoder_kind': item['decoder_kind'], 'selection': item['selection'],
            'architecture': item['architecture'], 'curriculum': item['curriculum'],
            'selected_steps': item['selected_steps'], 'metrics': {k: v for k, v in metrics.items() if k != 'rows'}})
    # Keep the original parent1730 integration check as well as all-three replay.
    old = read_ref(ref(clause_directory / 'document-compositions-frozen.json'))
    require(compositions['parent-1730'] == old['rows'], 'unchanged parent transfer differs from original clause integration')
    comparisons = []
    for left, right, comparison in comparison_pairs():
        a = {r['candidate_id']: r for r in scored[left]['rows']}; b = {r['candidate_id']: r for r in scored[right]['rows']}
        comparisons.append({'left': left, 'right': right, 'comparison': comparison, 'documents': len(a),
            'supported_documents': 72,
            'left_only_reference_exact': sum(a[i]['whole_document_reference_exact'] and not b[i]['whole_document_reference_exact'] for i in a),
            'right_only_reference_exact': sum(b[i]['whole_document_reference_exact'] and not a[i]['whole_document_reference_exact'] for i in a),
            'both_reference_exact': sum(a[i]['whole_document_reference_exact'] and b[i]['whole_document_reference_exact'] for i in a)})
    details_ref = clauses.write(output / 'scored-document-details.json', scored)
    totals = {}
    keys = ('documents', 'supported_documents', 'scope_abstentions', 'decoder_or_composition_abstentions', 'composed_documents',
        'exact_supported_documents', 'whole_document_decision_exact', 'built_documents', 'built_reference_mismatch',
        'composed_rule_occurrences', 'repeated_documents', 'repeated_exact_documents', 'repeated_composed_documents', 'actual_build_invocations')
    for arm in ARMS:
        selected = [row for row in report_models if row['arm'] == arm]
        totals[arm] = {key: sum(row['metrics'].get(key, 0) for row in selected) for key in keys}
    require(totals['parent']['exact_supported_documents'] == 170 and totals['parent']['supported_documents'] == 216,
        'prior all-seed parent regression counts differ')
    require(all(temporal_run.sha(path) == wanted for path, wanted in pins.items()), 'transfer implementation drift')
    for reference in [frozen_ref, boundary_ref, cp_ref, source_ref, clause_plan['references']['test'],
                      previous_frozen_ref, previous_frozen['plan'], *prior_parent_refs.values(),
                      *generation_refs.values(), *[item['checkpoint'] for item in models]]:
        read_ref(reference, parse=False)
    result = {'schema': SCHEMA, 'plan': plan_ref, 'generation_freeze': generation_freeze, 'builds': build_ref,
        'details': details_ref, 'models': report_models, 'totals': totals, 'paired_comparisons': comparisons,
        'boundary_metrics': boundary_counts, 'all_models_fresh_inference_replayed': True,
        'frozen_boundary_generation_replayed': True, 'unchanged_parent1730_reproduced_original_integration': True,
        'all_three_parents_reproduced_previous_transfer_exactly': True,
        'parent_fallback_slots': [item['name'] for item in models if item['selection'] == 'parent_fallback'],
        'references_opened_after_all_generation_and_build_freezes': True, 'training_executed': False,
        'exposed_authored_transfer_regression': True, 'independent_holdout': False,
        'scope': 'Same96 exposed authored documents under frozen learned flat boundaries; complete model/document denominators and duplicate rule occurrences preserved; no generalized legal scope claim', **boundary.FALSE}
    clauses.write(output / 'summary.json', result)
    print({'complete': str(output / 'summary.json'), 'totals': totals}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--temporal-run', required=True); parser.add_argument('--clause-run', required=True)
    parser.add_argument('--prior-transfer', required=True)
    parser.add_argument('--output', required=True); parser.add_argument('--lake-executable', required=True)
    parser.add_argument('--toolchain', default='leanprover/lean4:v4.34.1')
    run(parser.parse_args())
