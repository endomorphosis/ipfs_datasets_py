#!/usr/bin/env python3
"""Post-qualification clause facets conditional on exact accepted segmentation.

No inference, fitting, selection, or repair occurs. Conditional denominators are
reported alongside every score; these diagnostics cannot replace whole-document
accuracy or be compared as though each boundary policy covered the same cases.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_boundary_curriculum_experiment as runner
from scripts.ops.legal_ir import analyze_legal_construction_segmentation as attribution

require, read_ref, ref, write = runner.require, runner.read_ref, runner.ref, runner.write
FIELDS = ('modality', 'actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
OPTIONAL = ('conditions', 'exceptions', 'temporal')
SCHEMA = 'legal-boundary-conditional-clause-facets/v1'


def presence_outcome(expected, predicted, decoded):
    """Abstention remains separate from presence FN/TN; wrong values remain TP."""
    require(type(expected) is list, 'reference facet list required')
    positive = bool(expected)
    if not decoded:
        require(predicted is None, 'abstained facet must not invent a prediction')
        return {'reference_positive': positive, 'category': 'abstained_positive' if positive else 'abstained_negative',
            'value_exact': False, 'present_wrong_value': False}
    require(type(predicted) is list, 'decoded facet list required')
    present = bool(predicted)
    category = ('true_positive' if present else 'false_negative') if positive else ('false_positive' if present else 'true_negative')
    return {'reference_positive': positive, 'category': category, 'value_exact': predicted == expected,
        'present_wrong_value': positive and present and predicted != expected}


def clause_record(prediction, reference, source_clause, document_id, ordinal):
    require(prediction['source_sha256'] == source_clause['source_sha256'] ==
        runner.boundary.text_sha(source_clause['source_text']), 'clause source occurrence hash differs')
    require(prediction['target_access'] is False and prediction['teacher_forcing'] is False,
        'source-only unforced clause output required')
    expected = reference['rule']
    require(set(expected) == set(FIELDS), 'complete seven-facet reference rule required')
    canonical = prediction['canonical_ir']
    decoded = prediction['status'] == 'decoded'
    require(decoded is (canonical is not None), 'clause status/canonical output differs')
    actual = None
    if decoded:
        require(type(canonical) is dict and set(canonical) == {'rules'} and type(canonical['rules']) is list
            and len(canonical['rules']) == 1 and set(canonical['rules'][0]) == set(FIELDS),
            'one complete canonical rule per clause required')
        actual = canonical['rules'][0]
    facets = {key: bool(decoded and actual[key] == expected[key]) for key in FIELDS}
    return {'document_id': document_id, 'clause_ordinal': ordinal, 'clause_id': source_clause['clause_id'],
        'char_start': source_clause['char_start'], 'char_end': source_clause['char_end'],
        'source_sha256': source_clause['source_sha256'], 'decoded': decoded, 'abstained': not decoded,
        'abstention_reason': None if decoded else prediction['reason'],
        'canonical_rule_exact': bool(decoded and actual == expected), 'all_seven_facets_exact': all(facets.values()),
        'facet_exact': facets, 'presence': {key: presence_outcome(expected[key], actual[key] if decoded else None, decoded)
            for key in OPTIONAL}}


def document_records(sources, boundaries, documents, targets):
    expected = {r['candidate_id']: r for r in targets}
    segmentations = {r['candidate_id']: r for r in boundaries['rows']}
    outputs = {r['candidate_id']: r for r in documents['rows']}
    identities = {r['candidate_id'] for r in sources}
    require(len(sources) == len(identities) == len(targets) == len(expected) == len(boundaries['rows']) == len(segmentations)
        == len(documents['rows']) == len(outputs) and identities == set(expected) == set(segmentations) == set(outputs),
        'complete unique conditional diagnostic document inventory required')
    rows = []
    for source in sources:
        identity = source['candidate_id']; gold, segmentation, output = expected[identity], segmentations[identity], outputs[identity]
        bound = attribution.boundary_record(source, segmentation, gold)
        require(output['candidate_id'] == identity and output['source_sha256'] == source['source_sha256']
            and output['segmentation_status'] == segmentation['status'], 'document pipeline/boundary binding differs')
        if output['composition'] is not None:
            require(segmentation['plan'] is not None and
                output['composition']['source_plan'] == segmentation['plan'], 'composition used different source occurrence plan')
            runner.clauses.compose.validate_composition(output['composition'],
                expected_plan_sha256=segmentation['plan']['plan_sha256'])
        exact = bound['delivered_interval_exact']
        row = {'id': identity, 'source_sha256': source['source_sha256'], 'construction': gold['construction'],
            'supported': gold['supported'], 'accepted_segmentation': segmentation['plan'] is not None,
            'exact_accepted_segmentation': exact, 'supported_boundary_failure': gold['supported'] and not exact,
            'boundary_reason': segmentation['reason'], 'document_composed': output['composition'] is not None,
            'reference_clause_occurrences': len(gold['clauses']) if gold['supported'] else 0, 'clauses': []}
        if exact:
            plan = segmentation['plan']
            runner.clauses.compose.validate_source_plan(plan, expected_plan_sha256=plan['plan_sha256'])
            require(plan['source'] == source, 'exact source plan binding differs')
            report = output['clause_generation']
            require(report is not None and len(report['rows']) == len(plan['clauses']) == len(gold['clauses'])
                and report['target_access'] is False and report['teacher_forcing'] is False,
                'exact segmentation must retain every clause inference including abstentions')
            for ordinal, (prediction, reference, source_clause) in enumerate(zip(report['rows'], gold['clauses'], plan['clauses'])):
                require((reference['char_start'], reference['char_end']) == (source_clause['char_start'], source_clause['char_end']),
                    'conditional clause occurrence interval differs')
                row['clauses'].append(clause_record(prediction, reference, source_clause, identity, ordinal))
        rows.append(row)
    return rows


def summarize(rows):
    clauses = [clause for row in rows for clause in row['clauses']]
    supported = sum(row['supported'] for row in rows)
    exact = sum(row['exact_accepted_segmentation'] for row in rows)
    count = len(clauses)
    presence = {}
    for field in OPTIONAL:
        categories = Counter(clause['presence'][field]['category'] for clause in clauses)
        positives = sum(clause['presence'][field]['reference_positive'] for clause in clauses)
        presence[field] = {'conditional_clause_occurrences': count, 'reference_positive': positives,
            'reference_negative': count - positives, **{key: categories[key] for key in
                ('true_positive', 'false_negative', 'false_positive', 'true_negative', 'abstained_positive', 'abstained_negative')},
            'value_exact': sum(clause['presence'][field]['value_exact'] for clause in clauses),
            'present_wrong_value': sum(clause['presence'][field]['present_wrong_value'] for clause in clauses)}
        require(sum(categories.values()) == count and positives == categories['true_positive'] + categories['false_negative']
            + categories['abstained_positive'], 'presence denominator differs')
    return {'documents': len(rows), 'all_supported_documents': supported, 'unsupported_documents': len(rows) - supported,
        'exact_accepted_segmentation_documents': exact, 'supported_boundary_failure_documents': supported - exact,
        'unsupported_accepted_segmentation_documents': sum(not row['supported'] and row['accepted_segmentation'] for row in rows),
        'reference_clause_occurrences_all_supported': sum(row['reference_clause_occurrences'] for row in rows),
        'conditional_clause_occurrences': count, 'conditional_decoded_clauses': sum(clause['decoded'] for clause in clauses),
        'conditional_abstained_clauses': sum(clause['abstained'] for clause in clauses),
        'conditional_canonical_rule_exact': sum(clause['canonical_rule_exact'] for clause in clauses),
        'conditional_all_seven_facets_exact': sum(clause['all_seven_facets_exact'] for clause in clauses),
        'conditional_facet_exact': {field: sum(clause['facet_exact'][field] for clause in clauses) for field in FIELDS},
        'conditional_abstention_reasons': dict(Counter(clause['abstention_reason'] for clause in clauses if clause['abstained'])),
        'exact_segmentation_documents_with_abstained_clauses': sum(any(c['abstained'] for c in row['clauses']) for row in rows),
        'presence': presence}


def analyze(args):
    summary_path = Path(args.qualification).resolve()
    require(summary_path.is_file(), 'complete independent qualification summary required before any reference access')
    qualification_ref = ref(summary_path); qualification = read_ref(qualification_ref)
    require(qualification['schema'] == 'legal-boundary-curriculum-independent-qualification/v1'
        and qualification['fresh_target_and_regression_references_opened_after_replay_and_build_freezes'] is True
        and qualification['test_results_used_for_selection_or_gate_revision'] is False,
        'completed ordered independent qualification required')
    builds = read_ref(qualification['builds'])
    require(builds['fresh_and_regression_targets_opened'] is False, 'native build freeze must precede target access')
    frozen = read_ref(qualification['generation_freeze']); plan = read_ref(frozen['plan'])
    inputs = runner.load_config(plan['config']['path'])
    targets = {'tuning_old': inputs['tuning']['old'], 'tuning_new': inputs['tuning']['new'],
        **{panel: read_ref(reference) for panel, reference in qualification['reference_documents'].items()}}
    require(set(targets) == set(runner.PANELS) and len(frozen['models']) == 18, 'complete diagnostic model/panel inventory required')
    rows, metrics, arm_rows = {}, {}, {}
    for model in frozen['models']:
        name, arm = model['name'], model['arm']
        rows[name], metrics[name] = {}, {}
        for panel in runner.PANELS:
            values = document_records(inputs['sources'][panel], read_ref(frozen['boundaries'][model['boundary_head']][panel]),
                read_ref(frozen['document_files'][name][panel]), targets[panel])
            rows[name][panel] = values; metrics[name][panel] = summarize(values)
            arm_rows.setdefault(arm, {}).setdefault(panel, []).extend(values)
    output = Path(args.output).resolve()
    require(not output.exists(), 'diagnostic output must not overwrite existing evidence')
    details_path = output.with_name('conditional-facet-details.json')
    require(not details_path.exists(), 'diagnostic details must not overwrite existing evidence')
    details_ref = write(details_path, {'schema': SCHEMA, 'models': rows, 'qualification': qualification_ref})
    result = {'schema': SCHEMA, 'qualification': qualification_ref, 'generation_freeze': qualification['generation_freeze'],
        'builds_freeze': qualification['builds'], 'reference_documents': qualification['reference_documents'],
        'analyzer': ref(__file__), 'details': details_ref, 'models': metrics,
        'totals': {arm: {panel: summarize(values) for panel, values in panels.items()} for arm, panels in arm_rows.items()},
        'scope': 'Posthoc source-bound occurrence diagnostics conditional on exact accepted whole-document segmentation.',
        'presence_policy': 'TP/FN/FP/TN concern presence among decoded clauses; abstentions are separate positive/negative categories. Wrong present values count as presence TP but never value-exact.',
        'facet_policy': 'All seven delivered canonical fields; clause abstentions count as incorrect for every facet. Partial neural diagnostics do not count as delivered values.',
        'limitations': ['Different boundary policies condition on different source subsets; conditional percentages cannot establish relative overall accuracy.',
            'Every score includes its conditional denominator and all-supported coverage; whole-document metrics remain authoritative.',
            'Repeated text occurrences retain distinct offsets and are not collapsed.',
            'Technically authored references are not independently adjudicated statutory gold.',
            'Analysis was designed posthoc and did not alter selection, checkpoints, thresholds, or outputs.'],
        'inference_executed': False, 'training_executed': False, 'selection_changed': False, **runner.FALSE}
    write(output, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualification', required=True); parser.add_argument('--output', required=True)
    return analyze(parser.parse_args(argv))


if __name__ == '__main__':
    main()
