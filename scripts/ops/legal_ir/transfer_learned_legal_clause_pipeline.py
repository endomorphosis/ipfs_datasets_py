#!/usr/bin/env python3
"""Combine frozen learned boundaries with all frozen grounding heads, without fit.

The96 authored document outcomes are already exposed. This is a fixed transfer
regression, never a new independent test or checkpoint selection. All generations
and actual builds freeze before this execution opens document reference labels.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_clause_boundary_experiment as clauses
from scripts.ops.legal_ir import run_legal_grounding_experiment as grounding_run
from scripts.ops.legal_ir import verify_legal_clause_boundary_experiment as boundary_audit
from ipfs_datasets_py.logic.autoformal import legal_clause_boundary_decoder as boundary
from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as compose
from scripts.ops.legal_ir import check_legal_calendar_decoder_outputs as calendar
from scripts.ops.legal_ir import summarize_legal_calendar_decoder_outputs as calendar_summary

require, read_ref, ref = grounding_run.require, grounding_run.read_ref, grounding_run.ref
SCHEMA = 'legal-learned-boundary-grounding-transfer/v1'
SEEDS = (1729, 1730, 1731)
ARMS = ('source_continuation', 'trigger_grounding', 'parent')


def model_inventory(frozen, heads):
    require(frozen['schema'] == grounding_run.SCHEMA and frozen['all_training_selection_and_generation_complete'] is True
        and frozen['challenge_targets_opened'] is False, 'complete reference-free grounding model freeze required')
    expected = {f'{arm}-{seed}' for arm in ARMS for seed in SEEDS}
    models = frozen['models']; names = {r['name'] for r in models}
    require(len(models) == len(names) == 9 and names == expected and set(frozen['files']) == names,
            'all six new heads and three parents required')
    require(len(heads) == 6 and {r['name'] for r in heads} == {f'{arm}-{seed}' for arm in ARMS[:2] for seed in SEEDS},
            'all six selected trained heads required')
    by_name = {r['name']: r for r in models}
    for head in heads:
        require(by_name[head['name']] == head, 'model differs from frozen trained head')
    for item in models:
        require(item['name'] == f"{item['arm']}-{item['seed']}" and item['seed'] in SEEDS
            and item['enabled'] is (item['arm'] == 'trigger_grounding'), 'model attribution or branch differs')
        if item['arm'] != 'parent':
            require(item['parent'] == by_name[f"parent-{item['seed']}"]['checkpoint'], 'matched source parent differs')
    return models


def load(item):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_grounding as grounding
    module, cls = (dimensions, dimensions.DimensionalSpanDecoder) if item['arm'] == 'parent' else (grounding, grounding.GroundedSpanDecoder)
    cp = module.load_checkpoint(item['checkpoint']['path'], expected_sha256=item['checkpoint']['sha256'])
    return cls(cp)


def score_documents(records, targets, built):
    require(len(records) == len(targets) and len({r['candidate_id'] for r in records}) == len(records)
        and {r['candidate_id'] for r in records} == set(targets), 'complete document denominator required')
    counts, facets, details = Counter(), Counter(), []
    for record in records:
        target = targets[record['candidate_id']]
        require(target['source_sha256'] == record['source_sha256'], 'posthoc reference source differs')
        supported = target['supported']; composed = record['composition'] is not None
        counts['documents'] += 1; counts['supported_documents'] += supported
        counts['scope_abstentions'] += record['segmentation_status'] == 'abstained'
        counts['decoder_or_composition_abstentions'] += record['segmentation_status'] == 'segmented' and not composed
        counts['composed_documents'] += composed
        actual = record['composition']['source_rule_list'] if composed else None
        expected = [r['rule'] for r in target['clauses']] if supported else None
        exact = bool(supported and actual == expected)
        counts['exact_supported_documents'] += exact
        counts['whole_document_decision_exact'] += exact or (not supported and not composed)
        counts['built_documents'] += record['candidate_id'] in built
        counts['built_reference_mismatch'] += record['candidate_id'] in built and not exact
        counts['unsupported_accepted'] += not supported and composed
        differences = []
        if composed:
            counts['composed_rule_occurrences'] += len(actual)
            require(supported and len(actual) == len(expected), 'composed unsupported source or changed rule count')
            for ordinal, (a, b) in enumerate(zip(actual, expected)):
                for field in b:
                    if a[field] != b[field]:
                        facets[field] += 1
                        differences.append({'source_ordinal': ordinal, 'field': field, 'candidate': a[field], 'reference': b[field]})
        if target['repeated_rule_occurrences']:
            counts['repeated_documents'] += 1
            counts['repeated_exact_documents'] += exact
            counts['repeated_composed_documents'] += composed
        details.append({'candidate_id': record['candidate_id'], 'supported': supported, 'composed': composed,
            'whole_document_reference_exact': exact, 'status': record['status'], 'reason': record['reason'],
            'built': record['candidate_id'] in built, 'facet_differences': differences})
    require(counts['documents'] == counts['scope_abstentions'] + counts['decoder_or_composition_abstentions'] + counts['composed_documents'],
            'document accounting categories overlap or lose rows')
    return {**dict(counts), 'wrong_facet_occurrences': dict(facets), 'rows': details}


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.logic.autoformal import legal_calendar_lake as gate
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_grounding as grounding
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    directory, clause_directory, output = Path(args.grounding_run).resolve(), Path(args.clause_run).resolve(), Path(args.output).resolve()
    frozen_ref = ref(directory / 'generation-frozen.json'); frozen = read_ref(frozen_ref)
    heads = read_ref(frozen['heads']); models = model_inventory(frozen, heads)
    grounding_plan = read_ref(frozen['plan'])
    require(all(grounding_run.sha(path) == wanted for path, wanted in grounding_plan['producer_pins'].items()), 'grounding producer drift')
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
    output.mkdir(parents=True, exist_ok=False)
    pins = {str(Path(module.__file__).resolve()): grounding_run.sha(module.__file__) for module in
        (boundary, clauses, compose, calendar, calendar_summary, dimensions, grounding, grounding_run, sys.modules[__name__])}
    plan_ref = clauses.write(output / 'plan.json', {'schema': SCHEMA, 'grounding_models': frozen_ref,
        'boundary_generation': boundary_ref, 'boundary_checkpoint': cp_ref, 'source_documents': source_ref,
        'reference_commitment': clause_plan['references']['test'], 'models': models, 'producer_pins': pins,
        'selected_by_transfer_score': False, 'training_executed': False, 'exposed_authored_transfer_regression': True,
        'independent_holdout': False, 'scope': 'Fixed96 authored documents, frozen learned segmentation, nine frozen decoders, no fitting or selection', **boundary.FALSE})
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
    generation_freeze = clauses.write(output / 'generation-frozen.json', {'plan': plan_ref, 'models': generation_refs,
        'all_models_completed': True, 'reference_targets_opened': False, 'documents': 864,
        'source_clause_occurrences_replayed': 9 * 192, 'additional_fresh_replay_clause_occurrences': 9 * 192})
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
        for start in range(0, len(entries), gate.MAX_ROWS):
            batch = entries[start:start + gate.MAX_ROWS]
            folder = output / name / f'lake-{start // gate.MAX_ROWS:02d}'
            receipt = gate.build_qualified_legal(batch, toolchain=args.toolchain, lake_executable=args.lake_executable,
                timeout_seconds=60, output_directory=folder).to_dict()
            reference = ref(folder / 'qualified-receipt.json')
            require(calendar_summary.verify_receipt(reference, batch) == receipt, 'independent native compiler receipt reconstruction differs')
            builds[name].append({'receipt': reference, 'candidate_ids': [row['candidate']['candidate_id'] for row in batch],
                'build_passed': receipt['build_passed'], 'backend_executed': receipt['backend_executed'], 'command': receipt['command']})
        print({'phase': 'built', 'model': name, 'supported_documents': len(entries)}, flush=True)
    build_ref = clauses.write(output / 'builds-frozen.json', {'models': builds, 'selections': selection_ref,
        'generation_freeze': generation_freeze, 'reference_targets_opened': False})
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
            'checkpoint': item['checkpoint'], 'metrics': {k: v for k, v in metrics.items() if k != 'rows'}})
    # Parent1730 must reproduce the original fixed integration; no score-dependent parent choice.
    old = read_ref(ref(clause_directory / 'document-compositions-frozen.json'))
    require(compositions['parent-1730'] == old['rows'], 'unchanged parent transfer differs from original clause integration')
    comparisons = []
    for seed in SEEDS:
        for left, right in ((f'trigger_grounding-{seed}', f'source_continuation-{seed}'),
                            (f'source_continuation-{seed}', f'parent-{seed}')):
            a = {r['candidate_id']: r for r in scored[left]['rows']}; b = {r['candidate_id']: r for r in scored[right]['rows']}
            comparisons.append({'left': left, 'right': right, 'documents': len(a),
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
    require(all(grounding_run.sha(path) == wanted for path, wanted in pins.items()), 'transfer implementation drift')
    for reference in [frozen_ref, boundary_ref, cp_ref, source_ref, clause_plan['references']['test'],
                      *generation_refs.values(), *[item['checkpoint'] for item in models]]:
        read_ref(reference, parse=False)
    result = {'schema': SCHEMA, 'plan': plan_ref, 'generation_freeze': generation_freeze, 'builds': build_ref,
        'details': details_ref, 'models': report_models, 'totals': totals, 'paired_comparisons': comparisons,
        'boundary_metrics': boundary_counts, 'all_models_fresh_inference_replayed': True,
        'frozen_boundary_generation_replayed': True, 'unchanged_parent1730_reproduced_original_integration': True,
        'references_opened_after_all_generation_and_build_freezes': True, 'training_executed': False,
        'exposed_authored_transfer_regression': True, 'independent_holdout': False,
        'scope': 'Same96 exposed authored documents under frozen learned flat boundaries; complete model/document denominators and duplicate rule occurrences preserved; no generalized legal scope claim', **boundary.FALSE}
    clauses.write(output / 'summary.json', result)
    print({'complete': str(output / 'summary.json'), 'totals': totals}, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grounding-run', required=True); parser.add_argument('--clause-run', required=True)
    parser.add_argument('--output', required=True); parser.add_argument('--lake-executable', required=True)
    parser.add_argument('--toolchain', default='leanprover/lean4:v4.34.1')
    run(parser.parse_args())
