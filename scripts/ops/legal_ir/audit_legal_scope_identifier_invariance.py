#!/usr/bin/env python3
"""Measure scope decoder invariance to opaque replacements for exposed IDs.

Reads frozen source-only inputs and saved generations, never reference targets.
The complete output is compared after rebuilding only identifier-bound plans.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_scope_retention_experiment as experiment

boundary, clauses = experiment.boundary, experiment.clauses
require, digest, read_ref, ref, write = experiment.require, experiment.digest, experiment.read_ref, experiment.file_ref, experiment.write_new
SCHEMA = 'legal-scope-identifier-invariance/v1'
SEED = 864139


def opaque_sources(sources):
    experiment.old.validate_sources(sources, len(sources))
    rng = random.Random(SEED)
    rows = [{**r, 'candidate_id': 'opaque-' + f'{rng.getrandbits(128):032x}'} for r in sources]
    require(len({r['candidate_id'] for r in rows}) == len(rows), 'opaque IDs collided')
    require(not {r['candidate_id'] for r in rows} & {r['candidate_id'] for r in sources}, 'IDs were not changed')
    return rows


def expected_row(original, source, renamed):
    require(set(source) == set(renamed) == experiment.corpus.SOURCE_KEYS
            and source['source_text'] == renamed['source_text'] and source['source_sha256'] == renamed['source_sha256']
            and source['candidate_id'] != renamed['candidate_id'], 'only source identity may change')
    require(original['candidate_id'] == source['candidate_id'] and original['source_sha256'] == source['source_sha256'], 'original source/output identity differs')
    result = deepcopy(original); result['candidate_id'] = renamed['candidate_id']
    if original['plan'] is not None:
        expected_old_plan = boundary.source_plan(source, boundary.tokenize(source['source_text']), original['boundary_token_indices'])
        require(original['plan'] == expected_old_plan, 'original source plan differs from raw learned intervals')
        result['plan'] = boundary.source_plan(renamed, boundary.tokenize(renamed['source_text']), original['boundary_token_indices'])
        old_body, new_body = deepcopy(original['plan']), deepcopy(result['plan'])
        old_body.pop('plan_sha256'); new_body.pop('plan_sha256')
        old_body['source']['candidate_id'] = renamed['candidate_id']
        require(old_body == new_body, 'source-plan reconstruction altered fields beyond identity and derived commitment')
    return result


def expected_generation(original, sources, renamed):
    require(len(original['rows']) == len(sources) == len(renamed), 'complete ID invariance denominator required')
    wanted = deepcopy(original)
    wanted['rows'] = [expected_row(row, source, changed) for row, source, changed in zip(original['rows'], sources, renamed, strict=True)]
    cursor = 0
    for report in wanted['reports']:
        count = len(report['rows']); report['rows'] = deepcopy(wanted['rows'][cursor:cursor + count]); cursor += count
    require(cursor == len(sources), 'batch report row coverage differs')
    return wanted


def assert_generation_invariance(original, actual, sources, renamed):
    expected = expected_generation(original, sources, renamed)
    require(actual == expected, 'opaque ID changed numerical decisions, final output, or nonidentity metadata')
    return {'rows': len(sources), 'expected_output_sha256': digest(expected), 'actual_output_sha256': digest(actual),
            'all_output_fields_equal_after_identity_rebinding': True,
            'segmented': sum(r['status'] == 'segmented' for r in actual['rows']),
            'abstained': sum(r['status'] == 'abstained' for r in actual['rows'])}


def run(generation_path, output):
    frozen_ref = ref(generation_path); frozen = read_ref(frozen_ref)
    require(frozen['schema'] == experiment.SCHEMA and frozen['all_training_selection_and_generation_complete'] is True
            and [m['name'] for m in frozen['models']] == ['parent', 'control', 'target'], 'complete three frozen boundary slots required')
    sources = read_ref(frozen['sources']['scope_fresh']); require(len(sources) == 192, 'all192 scope source views required')
    renamed = opaque_sources(sources)
    output = Path(output).resolve(); require(not output.exists(), 'new ID audit directory required'); output.mkdir(parents=True)
    producers = [ref(module.__file__) for module in (experiment, boundary, clauses)] + [ref(__file__)]
    sources_ref = write(output / 'opaque-sources.json', renamed)
    mapping_ref = write(output / 'identifier-map.json', [{'original_id': a['candidate_id'], 'opaque_id': b['candidate_id'], 'source_sha256': a['source_sha256']} for a, b in zip(sources, renamed, strict=True)])
    rows = []
    for model in frozen['models']:
        original_ref = frozen['files'][model['name']]['scope_fresh']; original = read_ref(original_ref)
        checkpoint = read_ref(model['checkpoint']); decoder = boundary.ClauseBoundaryDecoder(checkpoint)
        before = digest({k: v.detach().cpu().tolist() for k, v in decoder.network.state_dict().items()})
        require(before == digest(checkpoint['model_state']), 'restored inference weights differ')
        generation = clauses.decode_all(decoder, renamed)
        after = digest({k: v.detach().cpu().tolist() for k, v in decoder.network.state_dict().items()})
        require(after == before and decoder.checkpoint_sha256 == digest(checkpoint), 'model weights/checkpoint changed during ID audit')
        comparison = assert_generation_invariance(original, generation, sources, renamed)
        generated_ref = write(output / (model['name'] + '-opaque-generation.json'), generation)
        rows.append({'name': model['name'], 'checkpoint': model['checkpoint'], 'original_generation': original_ref,
                     'renamed_generation': generated_ref, 'original_output_sha256': digest(original),
                     'model_state_sha256_before': before, 'model_state_sha256_after': after, **comparison})
    require(all(ref(p['path']) == p for p in producers), 'audit producer drift')
    receipt = {'schema': SCHEMA, 'generation_freeze': frozen_ref, 'producer_files': producers,
               'original_sources': frozen['sources']['scope_fresh'], 'opaque_sources': sources_ref, 'identifier_map': mapping_ref,
               'opaque_identifier_policy': {'seed': SEED, 'generator': 'random.Random(seed).getrandbits(128), fixed source order', 'uses_labels_or_source_content': False},
               'source_rows_per_slot': 192, 'head_slots': 3, 'additional_source_evaluations': 576,
               'distinct_checkpoint_hashes': len({m['checkpoint']['sha256'] for m in frozen['models']}), 'heads': rows,
               'all_numeric_and_final_outputs_invariant': True,
               'checked_fields': 'Complete per-document dictionaries, complete duplicated batch-report dictionaries and complete aggregate generation dictionary.',
               'explicit_numeric_fields': ['boundary_logits', 'boundary_token_indices', 'predicted_rule_count', 'scope_logits', 'scope_supported_probability', 'raw_learned_scope_supported'],
               'explicit_final_fields': ['status', 'reason', 'source_sha256', 'plan.clauses', 'plan.whitespace_gaps', 'plan.coverage', 'plan.clause_count', 'plan.scope', 'all authority/qualification flags'],
               'only_rebound_fields': ['rows[].candidate_id', 'rows[].plan.source.candidate_id', 'rows[].plan.plan_sha256', 'identical copies of these fields inside reports[].rows[]'],
               'plan_rebinding_method': 'Reconstruct old and renamed plans from unchanged frozen raw token end indices; assert all remaining plan fields exactly equal.',
               'new_reference_targets_opened': False, 'new_reference_ledger_opened': False, 'training_executed': False, 'fixed_choices_changed': False,
               'saved_output_replay_claimed_by_this_receipt': False,
               'limitation': 'Original source identifiers still expose authored scope labels. This measured interface invariance does not establish label-free metadata or human-blind holdout labels. Three retained policy slots may share checkpoint bytes.'}
    return write(output / 'receipt.json', receipt)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generation', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args(); print(json.dumps(run(args.generation, args.output), sort_keys=True))
