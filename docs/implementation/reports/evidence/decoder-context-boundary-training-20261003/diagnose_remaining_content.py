"""Postfit saved-data description only; never execute or tune a model."""
from pathlib import Path
from collections import Counter
import hashlib
import json

R = Path(__file__).resolve().parent
T = R / 'training-r1/results'
ARTIFACTS = {}
FIELDS = ('actor', 'action', 'modality', 'object')
ALL_FIELDS = (*FIELDS, 'conditions', 'exceptions', 'temporal')


def read(path):
    raw = path.read_bytes()
    ARTIFACTS[str(path)] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return json.loads(raw)


def key(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def duplicates(rules):
    result = []
    for index, rule in enumerate(rules):
        previous = [other + 1 for other, value in enumerate(rules[:index]) if rule == value]
        if previous:
            result.append(dict(position=index + 1, identical_previous_positions=previous, rule=rule))
    return result


def repeated_pairs(rules):
    groups = {}
    for index, rule in enumerate(rules):
        groups.setdefault((rule['actor'], rule['action']), []).append(index + 1)
    return [dict(actor=actor, action=action, positions=positions,
        has_adjacent_positions=any(right == left + 1 for left, right in zip(positions, positions[1:])))
        for (actor, action), positions in groups.items() if len(positions) > 1]


def main():
    source = Path(__file__).resolve()
    raw = source.read_bytes()
    ARTIFACTS[str(source)] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    state = read(T / '768-boundary-first-last-2718/initial-state.json')
    vocabulary = state['codec']['target_vocabulary']
    del state
    contexts = read(T / '768/source-contexts.json')['validation']
    output = []
    for name, expected_failures in [('768-boundary-first-last-2718', 6), ('768-boundary-first-wrong-2718', 7)]:
        folder = T / name / 'last-attempt'
        panel = read(folder / 'evaluation-validation.json')
        raw_values = {row['id']: row for row in panel['source_values']['predictions']}
        counts = {row['id']: row for row in panel['source_count']['predictions']}
        controls = {}
        for label in ('source-shuffle', 'context-only-shuffle', 'context-reverse', 'context-rotate', 'recurrent-residual-off'):
            control = read(folder / f'evaluation-{label}.json')
            controls[label] = dict(metrics=control['source_fidelity']['metrics'],
                rows={row['id']: row for row in control['source_fidelity']['rows']})
        failures = []
        field_counts = Counter()
        raw_correct_generated_wrong = Counter()
        mismatched_slot_pairs = Counter()
        for row in panel['source_fidelity']['rows']:
            if row['counts']['ordered_exact']:
                continue
            identity = row['id']
            expected, generated = row['expected_ir']['rules'], row['generated_ir']['rules']
            values = raw_values[identity]
            context = contexts[identity]
            assert len(context['segments']) == len(expected)
            raw_slots = []
            for index, rule in enumerate(expected):
                actual_values = dict(zip(FIELDS, [json.loads(vocabulary[value])
                    for value in values['predicted_token_ids'][index]]))
                assert dict(zip(FIELDS, [json.loads(vocabulary[value])
                    for value in values['expected_token_ids'][index]])) == {field: rule[field] for field in FIELDS}
                raw_slots.append(dict(position=index + 1, predicted=actual_values,
                    field_correct={field: actual_values[field] == rule[field] for field in FIELDS},
                    source_text=context['segments'][index]['source_text'],
                    source_sha256=context['segments'][index]['source_sha256']))
            errors = []
            for index, (reference, prediction) in enumerate(zip(expected, generated)):
                changed = {field: dict(expected=reference[field], generated=prediction[field])
                    for field in ALL_FIELDS if reference[field] != prediction[field]}
                if not changed:
                    continue
                field_counts.update(changed.keys())
                for field in changed:
                    if field in FIELDS and raw_slots[index]['field_correct'][field]:
                        raw_correct_generated_wrong[field] += 1
                mismatched_slot_pairs.update([f"{reference['actor']}/{reference['action']} -> {prediction['actor']}/{prediction['action']}"])
                errors.append(dict(position=index + 1, changed_fields=changed,
                    raw_source_prediction=raw_slots[index]['predicted'],
                    raw_source_field_correct=raw_slots[index]['field_correct'],
                    source_text=raw_slots[index]['source_text'],
                    source_sha256=raw_slots[index]['source_sha256'],
                    same_literal_source_positions=[slot['position'] for slot in raw_slots
                        if slot['source_sha256'] == raw_slots[index]['source_sha256']],
                    expected_rule=reference, generated_rule=prediction))
            extras = [dict(position=index + 1, rule=rule,
                exact_reference_positions=[position + 1 for position, reference in enumerate(expected) if rule == reference])
                for index, rule in enumerate(generated) if index >= len(expected)]
            failures.append(dict(id=identity, expected_length=len(expected), generated_length=len(generated),
                counts=row['counts'], expected_rules=expected, generated_rules=generated,
                all_expected_prefix_rules_match=generated[:len(expected)] == expected,
                positional_field_errors=errors, appended_rules=extras, duplicate_positions=duplicates(generated),
                reference_repeated_pairs=repeated_pairs(expected),
                reference_literal_duplicate_positions=duplicates(expected), raw_source_slots=raw_slots,
                count_head_prediction=counts[identity]['predicted'], count_head_correct=counts[identity]['predicted'] == len(expected),
                control_outcomes={label: dict(counts=value['rows'][identity]['counts'],
                    generated_rules=value['rows'][identity]['generated_ir']) for label, value in controls.items()}))
        assert len(failures) == expected_failures
        problematic_sources = {error['source_sha256'] for row in failures for error in row['positional_field_errors']}
        repeated_literal_observations = {}
        for row in panel['source_fidelity']['rows']:
            for index, segment in enumerate(contexts[row['id']]['segments']):
                if segment['source_sha256'] not in problematic_sources:
                    continue
                reference = row['expected_ir']['rules'][index]
                generated = row['generated_ir']['rules']
                prediction = generated[index] if index < len(generated) else None
                raw_prediction = dict(zip(FIELDS, [json.loads(vocabulary[value])
                    for value in raw_values[row['id']]['predicted_token_ids'][index]]))
                group = repeated_literal_observations.setdefault(segment['source_sha256'],
                    dict(source_text=segment['source_text'], expected_rule=reference, occurrences=[]))
                assert group['expected_rule'] == reference
                group['occurrences'].append(dict(id=row['id'], position=index + 1, paragraph_length=row['clause_count'],
                    generated_rule=prediction, generated_rule_correct=prediction == reference, raw_source_prediction=raw_prediction,
                    raw_source_all_scalar_correct=all(reference[field] == raw_prediction[field] for field in FIELDS)))
        output.append(dict(arm=name, failures=failures, summary=dict(failed_rows=len(failures),
            rows_with_appended_rules=sum(bool(row['appended_rules']) for row in failures),
            rows_with_only_appended_errors=sum(bool(row['appended_rules']) and row['all_expected_prefix_rules_match'] for row in failures),
            generated_length_correct_rows=sum(row['expected_length'] == row['generated_length'] for row in failures),
            positional_field_errors=dict(field_counts), raw_correct_generated_wrong_fields=dict(raw_correct_generated_wrong),
            mismatched_actor_action_pairs=dict(mismatched_slot_pairs),
            appended_rule_count=sum(len(row['appended_rules']) for row in failures),
            duplicate_occurrences=sum(len(row['duplicate_positions']) for row in failures),
            reference_exact_rule_duplicates=sum(len(row['reference_literal_duplicate_positions']) for row in failures),
            reference_rows_with_repeated_actor_action_pairs=sum(bool(row['reference_repeated_pairs']) for row in failures),
            reference_rows_with_adjacent_repeated_pairs=sum(any(pair['has_adjacent_positions'] for pair in row['reference_repeated_pairs']) for row in failures)),
            same_literal_source_occurrences_across_all_validation_rows=repeated_literal_observations,
            global_metrics=panel['source_fidelity']['metrics'],
            global_raw_source_by_field=panel['source_values']['by_field'],
            controls={label: value['metrics'] for label, value in controls.items()}))
    for path, pin in ARTIFACTS.items():
        raw = Path(path).read_bytes()
        assert pin == dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    value = dict(schema='saved-context-boundary-remaining-content-gap/v1', complete=True, arms=output,
        artifacts=ARTIFACTS, scope='posthoc description of two completed final private attempts; exposed validation',
        position_convention='one-based; positional substitution comparisons followed by appended suffix description',
        actual_generated_field_logits_available=False, raw_source_logits_are_not_autoregressive_logits=True,
        control_scope='existing saved fixed-state inference controls; no causal attribution to individual logits',
        model_executed=False, training_executed=False, encoder_executed=False,
        validation_tuning_performed=False, optimality_claimed=False, fresh_holdout=False,
        qualified=False, admitted=False, lake_executed=False, checkpoint_promoted=False, convergence_proven=False)
    destination = R / 'remaining-content-gap.json'
    destination.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+'\n')
    print(json.dumps(dict(complete=True, output=str(destination), sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
        summaries={arm['arm']: arm['summary'] for arm in output})))


if __name__ == '__main__':
    main()
