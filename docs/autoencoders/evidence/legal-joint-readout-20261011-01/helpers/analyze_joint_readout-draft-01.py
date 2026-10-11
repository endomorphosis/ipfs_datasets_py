"""Compare saved outputs only; no numerical imports or checkpoint restoration."""
import collections
import hashlib
import json
from pathlib import Path

F = Path(__file__).resolve().parent
RUN_ROOT = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
RUN = RUN_ROOT / 'retained-joint-readout-20261011-01'
OLD = RUN_ROOT / 'retained-pointer-cache-20261011-03'


def pin(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')


def main():
    inputs = {}

    def read(path):
        inputs[str(path)] = pin(path)
        return json.loads(path.read_bytes())

    summary = read(RUN / 'results/summary.json')
    assert summary['status'] == 'completed' and summary['requested_output_count'] == 64
    packet = read(F / 'statutory-source-review-packet.json')
    sources = {item['input']['id']: item['input'] for item in packet['items']}
    lanes, all_scores, all_results, preserved = [], {}, {}, 0
    selected_instances = []
    fields = ('actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
    for lane in summary['lanes']:
        name, control = lane['name'], lane['control']
        prefix = name + '-' + control
        raw = read(RUN / 'results' / (prefix + '.json'))
        previous = read(OLD / 'results' / (prefix + '.json'))
        captured = read(RUN / 'results' / (prefix + '-scores.json'))
        joint = read(RUN / 'results' / (prefix + '-joint.json'))
        assert len(raw['rows']) == len(previous['rows']) == len(captured['rows']) == len(joint['rows']) == 8
        assert captured['additional_model_forwards'] == 0 and captured['captured_forward_count'] == 8
        assert lane['model_custody_before'] == lane['model_custody_after'] and lane['inference_cpu_rng_unchanged']
        raw_counts, joint_counts = collections.Counter(), collections.Counter()
        record_details = []
        for old, original, scores, candidate in zip(previous['rows'], raw['rows'], captured['rows'], joint['rows']):
            identity = original['id']
            assert identity == old['id'] == scores['id'] == candidate['id']
            equal = wire(original['decoder_row']) == wire(old['decoder_row'])
            preserved += equal
            result = candidate['result']
            raw_counts[original['outcome']] += 1
            joint_counts[result['status'] if result['reason'] is None else result['reason']] += 1
            all_scores[(name, control, identity)] = scores['scores']
            all_results[(name, control, identity)] = result
            fixed = result['fixed_decisions']
            packet_scores = scores['scores']
            modality = ('O', 'P', 'F')[max(range(3), key=lambda i: packet_scores['modality_logits'][i])]
            assert fixed['modality'] == modality
            for field in fields:
                present = field in ('actor', 'action') or packet_scores['presence_logits'][field][1] > packet_scores['presence_logits'][field][0]
                assert fixed['facets'][field]['present'] == present
            detail = {'id': identity, 'citation': sources[identity]['source']['citation'],
                      'original_outcome': original['outcome'], 'original_reason': original['decoder_row']['reason'],
                      'original_decoder_row_equal_to_previous_run': equal,
                      'joint_status': result['status'], 'joint_reason': result['reason'],
                      'canonical_ir': result['canonical_ir'], 'fixed_decisions': fixed,
                      'candidate_domain_truncated': result['candidate_domain_truncated'], 'search': result['search']}
            if result['status'] == 'selected':
                source = sources[identity]['source_text']
                occupied = set()
                rule = result['canonical_ir']['rules'][0]
                assert rule['modality'] == modality and result['canonical_rule_valid'] and result['family_syntax_checked']
                for field in fields:
                    diagnostic = result['span_diagnostics'][field]
                    assert diagnostic['present'] == fixed['facets'][field]['present']
                    span = diagnostic['span']
                    value = rule[field]
                    if span is None:
                        assert value == ([] if field in ('conditions', 'exceptions', 'temporal') else '')
                        continue
                    assert source[span['char_start']:span['char_end']] == span['text']
                    assert source.encode('utf8')[span['utf8_byte_start']:span['utf8_byte_end']].decode('utf8') == span['text']
                    assert value == ([span['text']] if field in ('conditions', 'exceptions', 'temporal') else span['text'])
                    positions = set(range(span['token_start'], span['token_end_inclusive'] + 1))
                    assert not occupied & positions
                    occupied |= positions
                assert result['search']['retained_domain_optimality_established'] and result['search']['unique_within_guard']
                selected_instances.append({'name': name, 'control': control, **detail})
            record_details.append(detail)
        lanes.append({'name': name, 'control': control, 'requested': 8, 'original_outcomes': dict(raw_counts),
                      'joint_outcomes': dict(joint_counts), 'selected_count': joint_counts['selected'],
                      'candidate_domain_truncated_count': sum(row['candidate_domain_truncated'] for row in record_details),
                      'search_budget_exhausted_count': sum(row['search']['budget_exhausted'] for row in record_details),
                      'rows': record_details})
    control_comparisons = []
    for name in ('raw384-1729', 'source_only-1729'):
        for control in ('zero', 'disabled', 'rotate'):
            score_changed, selection_changed, disposition_changed = [], [], []
            for identity in sources:
                if wire(all_scores[name, 'none', identity]) != wire(all_scores[name, control, identity]):
                    score_changed.append(identity)
                a, b = all_results[name, 'none', identity], all_results[name, control, identity]
                if wire(a['canonical_ir']) != wire(b['canonical_ir']):
                    selection_changed.append(identity)
                if (a['status'], a['reason']) != (b['status'], b['reason']):
                    disposition_changed.append(identity)
            control_comparisons.append({'name': name, 'control': control, 'source_count': 8,
                                        'scores_changed_ids': score_changed, 'canonical_ir_changed_ids': selection_changed,
                                        'disposition_changed_ids': disposition_changed})
    assert preserved == 64
    assert all(pin(path) == reference for path, reference in inputs.items())
    value = {'schema': 'saved-joint-readout-comparison/v1', 'passed': True, 'findings': [],
             'analyzer_pin': pin(Path(__file__).resolve()), 'inputs': inputs, 'requested_dispositions': 64,
             'original_decoder_rows_byte_equal_in_canonical_JSON_to_previous_run': preserved,
             'joint_selected_instances': len(selected_instances), 'lanes': lanes,
             'control_comparisons': control_comparisons,
             'all_selected_facets_copy_exact_source_intervals': True, 'all_selected_assignments_nonoverlapping': True,
             'fixed_modality_and_optional_presence_preserved': True,
             'source_count': 8, 'unique_physical_source_count': 8, 'all_sources_previously_exposed': True,
             'independent_semantic_holdout': False, 'human_labels': 0, 'semantic_accuracy': None,
             'semantic_gain_established': False, 'training_updates': 0, 'new_encoder_calls': 0,
             'numerical_execution_by_analyzer': False, 'Lake_executed': False, 'proof_authority': False,
             'full_domain_optimality_established_count': sum(x['search']['full_domain_optimality_established'] for lane in lanes for x in lane['rows']),
             'limitations': ['Repeated controls/states do not supply 64 independent legal observations.',
                             'Copied canonical syntax and nonoverlap do not verify actor/action roles or normative meaning.',
                             'Top8 per-present-facet pool is truncated for all64 requested outputs; no full-domain optimality.',
                             'Changes in scores or candidates under latent controls do not establish beneficial latent conditioning.',
                             'This pure saved-file analyzer checks observations, not continuous independent execution attestation.']}
    with (F / 'joint-comparison-diagnostics.json').open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False); stream.write('\n')
    print(json.dumps({'original_rows_preserved': preserved, 'joint_selected_instances': len(selected_instances),
                      'lanes': [{k: row[k] for k in ('name', 'control', 'selected_count', 'joint_outcomes')} for row in lanes],
                      'controls': control_comparisons}))


if __name__ == '__main__':
    main()
