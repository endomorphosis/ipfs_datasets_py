#!/usr/bin/env python3
"""Audit persisted execution with stdlib only; never load or invoke a model."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import unicodedata
import xml.etree.ElementTree as ET

ROOT = Path('/home/barberb/lift_coding')
OUT = ROOT / 'artifacts/contextual-legal-runtime-20261006'
WT = ROOT / '.worktrees/contextual-legal-runtime-datasets-20261006'
FACETS = ('modality', 'actor', 'action', 'object', 'conditions', 'exceptions', 'temporal')
PROTECTED = {}


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def pin(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= 64 * 1024 * 1024
    data = path.read_bytes()
    result = dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    PROTECTED.setdefault(str(path), result)
    return result


def load(path, expected=None):
    path = Path(path)
    witnessed = pin(path)
    if expected is not None:
        assert witnessed == expected, str(path)
    # Read same file again only with a before/after byte witness; no in-memory
    # tensor construction or project imports occur in this review.
    value = json.loads(path.read_bytes())
    assert pin(path) == witnessed
    return value


def false(values):
    assert type(values) is dict and all(value is False for value in values.values())


def strict_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result
            result[key] = value
        return result
    def constant(value):
        raise AssertionError('nonfinite JSON constant')
    value = json.loads(text, object_pairs_hook=unique, parse_constant=constant)
    raw(value)
    return value


def canonical(value):
    """Independently implement the saved contract's observed seven-field policy.

    Only canonical payload agreement is recomputed. Calling this helper does not
    establish arbitrary legal meaning or a checkpoint's native schema identity.
    """
    assert type(value) is dict and set(value) == {'rules'} and 1 <= len(value['rules']) <= 32
    rules = deepcopy(value['rules'])
    for rule in rules:
        assert type(rule) is dict and set(rule) == set(FACETS)
        assert rule['modality'] in ('O', 'P', 'F')
        assert all(type(rule[field]) is str for field in FACETS[:4])
        assert rule['actor'].strip() and rule['action'].strip()
        for field in FACETS[4:]:
            assert type(rule[field]) is list and all(type(item) is str and item.strip() for item in rule[field])
            rule[field] = sorted(set(rule[field]))
    # The native owner's last CID tie-breaker cannot change payload order when
    # all seven preceding facets are equal.
    rules.sort(key=lambda rule: tuple(rule[field] for field in FACETS[:4])
               + tuple(tuple(rule[field]) for field in FACETS[4:]))
    return {'rules': rules}


def normalized(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def main():
    assert 'torch' not in sys.modules
    generation = load(OUT / 'generation-qualification.json')
    evaluation = load(OUT / 'separate-evaluation.json')
    survey = load(OUT / 'source-survey/source-survey.json')
    historical = load(evaluation['previous_inference_manifest_pin']['path'], evaluation['previous_inference_manifest_pin'])
    historical_by_width = {lane['dimension']: lane for lane in historical['lanes']}
    assert generation['completed'] is True and evaluation['completed'] is True
    assert generation['datasets_head'] == evaluation['datasets_head'] == '37c2d63f0bf9490e5b019788afcafbc3b806d8c7'
    assert pin(OUT / 'generation-qualification.json') == evaluation['generation_receipt_pin']
    assert generation['script_pin'] == evaluation['script_pin'] == pin(OUT / 'qualify_original_assets.py')
    assert generation['source_pins_before'] == generation['source_pins_after']
    assert len(generation['source_pins_before']) == 21
    for expected in generation['source_pins_after'].values():
        assert pin(expected['path']) == expected
    assert generation['original_files_before'] == generation['original_files_after']
    assert len(generation['original_files_after']) == 8
    for expected in generation['original_files_after']:
        assert pin(expected['path']) == expected
    assert generation['donor_pin_before'] == generation['donor_pin_after']
    assert pin(generation['donor_pin_after']['path']) == generation['donor_pin_after']
    assert evaluation['original44_file_pins_after_generation'] == survey['original_file_pins_before']
    for expected in survey['original_file_pins_before']:
        assert pin(expected['path']) == expected
    assert generation['preparation_torch_free'] is True and generation['source_only_generation'] is True
    assert all(generation[key] is False for key in ('database_or_network_executed', 'encoder_executed',
        'fitting_executed', 'optimizer_executed', 'original_targets_opened_during_generation',
        'fresh_holdout', 'native_profile_qualified', 'proof_authority', 'qualified'))
    assert evaluation['evaluator_torch_free'] is True and evaluation['generated_candidates_persisted_before_reference_access'] is True
    assert all(evaluation[key] is False for key in ('model_loaded', 'training_executed', 'embeddings_generated',
        'source_text_passed_to_decompiler', 'reference_ir_passed_to_decompiler',
        'fresh_holdout', 'native_profile_qualified', 'proof_authority'))
    assert [lane['dimension'] for lane in generation['lanes']] == [384, 768]
    assert [lane['dimension'] for lane in evaluation['lanes']] == [384, 768]
    summaries, examples = [], []
    for source_lane, generated_lane, scored_lane in zip(survey['lanes'], generation['lanes'], evaluation['lanes']):
        width = source_lane['dimension']
        assert width == generated_lane['dimension'] == scored_lane['dimension']
        fresh = load(generated_lane['candidate_pin']['path'], generated_lane['candidate_pin'])
        assert generated_lane['candidate_pin'] == scored_lane['candidate_pin']
        old = load(scored_lane['previous_candidate_pin']['path'], scored_lane['previous_candidate_pin'])
        assert scored_lane['previous_candidate_pin'] == historical_by_width[width]['candidate_report']
        model_report = fresh['raw_candidate_report']
        predictions = model_report['predictions']
        assert predictions == old['predictions']
        assert fresh['model_inference_executed'] is True and fresh['original_targets_accessed'] is False
        false(fresh['authority']); false(fresh['runtime_selection']['authority'])
        assert all(fresh['runtime_selection'][key] is None for key in
                   ('native_ir_schema_version', 'decoder_profile_id', 'decoder_format_id'))
        assert fresh['runtime_selection']['complete_runtime_io_contract'] is False
        assert model_report['row_count'] == len(predictions) == 48 and model_report['completed'] is True
        assert all(model_report[key] is True for key in ('weights_unchanged', 'ambient_rng_preserved', 'source_inputs_unchanged'))
        assert all(model_report[key] is False for key in ('encoder_executed', 'optimizer_executed', 'training_executed',
            'target_access', 'reference_documents_passed_to_generation', 'admitted', 'qualified', 'proof_authority',
            'source_semantics_verified', 'teacher_qualified', 'production_runtime_compatible'))
        assert model_report['model_tensor_sha256'] == model_report['model_tensor_sha256_before'] \
            == model_report['model_tensor_sha256_after'] == source_lane['selected_native_tensor_sha256']
        inputs = load(source_lane['cached_file_pins']['source_only_inputs']['path'], source_lane['cached_file_pins']['source_only_inputs'])
        contexts = load(source_lane['cached_file_pins']['source_only_contexts']['path'], source_lane['cached_file_pins']['source_only_contexts'])
        assert hashlib.sha256(raw(dict(rows=inputs, contexts=contexts))).hexdigest() == model_report['source_inputs_sha256']
        assert hashlib.sha256(raw(contexts)).hexdigest() == model_report['source_contexts_sha256']
        assert [row['id'] for row in inputs] == [row['id'] for row in predictions]
        assert [row['id'] for row in fresh['row_receipts']] == [row['id'] for row in inputs]
        for row, receipt in zip(inputs, fresh['row_receipts']):
            count = len(contexts[row['id']]['segments'])
            assert receipt['source_clause_count'] == count
            assert receipt['source_padding_mask'] == [True] * count + [False] * (8-count)
            assert receipt['source_sha256'] == hashlib.sha256(row['source_text'].encode()).hexdigest()
            assert receipt['input_sha256'] == hashlib.sha256(raw(row['input'])).hexdigest()
        assert sum(len(value['segments']) for value in contexts.values()) == 180
        checkpoint = load(source_lane['original_checkpoint_pin']['path'], source_lane['original_checkpoint_pin'])
        codec = checkpoint['codec']; vocabulary = codec['target_vocabulary']
        assert hashlib.sha256(raw(codec)).hexdigest() == model_report['codec_sha256']
        references = load(scored_lane['reference_pin']['path'], scored_lane['reference_pin'])['validation']
        assert len(references) == 48 and [row['id'] for row in references] == [row['id'] for row in predictions]
        ir_report = load(scored_lane['ir_report_pin']['path'], scored_lane['ir_report_pin'])
        text_report = load(scored_lane['text_report_pin']['path'], scored_lane['text_report_pin'])
        rendering = load(scored_lane['rendering_pin']['path'], scored_lane['rendering_pin'])
        false(ir_report['authority']); false(text_report['authority']); false(rendering['authority'])
        assert all(rendering[key] is False for key in
                   ('decompiler_uses_model', 'originating_source_passed_to_decompiler', 'reference_IR_passed_to_decompiler'))
        assert not rendering['refusals'] and len(rendering['reconstructions']) == 48
        texts = {row['id']: row['reconstructed_text'] for row in rendering['reconstructions']}
        receipts = {row['id']: row for row in rendering['rendering_receipts']}
        text_observations = {row['id']: row for row in text_report['rows']}
        inspection = {row['id']: row for row in ir_report['generated_payload_inspection']['rows']}
        ordered_exact = canonical_exact = utf8_exact = nfc_exact = expected_rules = 0
        by_facet = {field: dict(correct=0, total=0) for field in FACETS}
        rules_distribution = Counter()
        qualifiers_empty = True
        for reference, prediction, stored in zip(references, predictions, ir_report['reference_agreement']['rows']):
            assert prediction['generation_status'] == 'eos' and prediction['eos_reached'] is True
            tokens = prediction['token_ids']; assert len(tokens) + 2 <= 512
            assert all(type(token) is int and 3 <= token < len(vocabulary) for token in tokens)
            candidate = strict_json(''.join(vocabulary[token] for token in tokens))
            target = strict_json(''.join(vocabulary[token] for token in reference['target_ids'][1:-1]))
            assert stored['id'] == reference['id'] and stored['expected_ir'] == target and stored['generated_ir'] == candidate
            assert stored['generated_token_ids'] == tokens and not stored['errors']
            assert inspection[reference['id']]['ordered_generated_ir'] == candidate
            assert inspection[reference['id']]['canonical_contract_ir'] == canonical(candidate)
            assert inspection[reference['id']]['complete_candidate'] is True
            ordered_exact += raw(candidate) == raw(target)
            canonical_exact += canonical(candidate) == canonical(target)
            expected_rules += len(target['rules']); rules_distribution[len(target['rules'])] += 1
            assert Counter(raw(rule) for rule in candidate['rules']) == Counter(raw(rule) for rule in target['rules'])
            for actual, gold in zip(candidate['rules'], target['rules']):
                for field in FACETS:
                    by_facet[field]['correct'] += raw(actual[field]) == raw(gold[field])
                    by_facet[field]['total'] += 1
                qualifiers_empty &= all(not gold[field] for field in FACETS[4:])
            original, rendered = reference['source_text'], texts[reference['id']]
            utf8 = original.encode() == rendered.encode(); nfc = normalized(original) == normalized(rendered)
            utf8_exact += utf8; nfc_exact += nfc
            observation = text_observations[reference['id']]
            assert observation['verbatim_utf8_exact'] == utf8 and observation['nfc_whitespace_exact'] == nfc
            assert observation['source_utf8_sha256'] == hashlib.sha256(original.encode()).hexdigest()
            assert observation['reconstructed_utf8_sha256'] == hashlib.sha256(rendered.encode()).hexdigest()
            result = receipts[reference['id']]['result']
            assert result['text'] == rendered and result['status'] == 'success' and result['source_withheld'] is True
            assert all(trace['deterministic'] is True and trace['model_receipt_cid'] is None for trace in result['component_trace'])
            # Independent realization check is intentionally limited to this
            # observed empty-qualifier corpus; no broad semantic evaluator runs.
            sentences = []
            for rule in canonical(candidate)['rules']:
                assert all(not rule[field] for field in FACETS[4:])
                phrase = ' '.join(' '.join(part.replace('_', ' ').split()) for part in
                    (rule['actor'], {'O': 'must', 'P': 'may', 'F': 'must not'}[rule['modality']],
                     rule['action'], rule['object']) if part)
                sentences.append(phrase[0].upper() + phrase[1:] + '.')
            assert rendered == ' '.join(sentences)
            if original == 'The registrar is allowed to preserve the archive.':
                assert rendered == 'Registrar may preserve archive.'
                examples.append(dict(dimension=width, id=reference['id'], original_text=original, rendered_text=rendered))
        assert ordered_exact == canonical_exact == 48 and expected_rules == 180 and qualifiers_empty
        assert rules_distribution == Counter({1:12, 2:12, 4:12, 8:12})
        assert utf8_exact == nfc_exact == 0
        assert ir_report['reference_agreement']['metrics'] == scored_lane['ir_metrics']
        assert ir_report['reference_agreement']['metrics']['ordered_exact'] == ordered_exact
        assert ir_report['canonical_contract_exact'] == scored_lane['canonical_contract_exact'] == canonical_exact
        assert ir_report['reference_agreement']['metrics']['expected_rules'] == expected_rules
        assert all(by_facet[field] == {key: ir_report['reference_agreement']['by_facet'][field][key]
                                      for key in ('correct', 'total')} for field in FACETS)
        assert text_report['verbatim_utf8_exact'] == utf8_exact and text_report['nfc_whitespace_exact'] == nfc_exact
        assert text_report['prediction_count'] == text_report['reference_count'] == 48 and text_report['missing_prediction_count'] == 0
        assert scored_lane['original_text_metrics'] == {key:value for key,value in text_report.items() if key!='rows'}
        summaries.append(dict(dimension=width, rows=48, EOS=48, old_raw_token_status_EOS_exact=True,
            ordered_IR_exact=ordered_exact, canonical_contract_exact=canonical_exact,
            rules=expected_rules, by_facet=by_facet, main_scalar_fields_correct=720,
            rule_count_distribution=dict(rules_distribution), reference_qualifiers_all_empty=qualifiers_empty,
            source_withheld_text_count=48, UTF8_text_exact=utf8_exact, NFC_whitespace_text_exact=nfc_exact,
            no_model_or_source_or_reference_IR_passed_to_renderer=True,
            original_checkpoint_pin=source_lane['original_checkpoint_pin'],
            candidate_pin=generated_lane['candidate_pin']))
    test_counts = {}
    for name in ('contextual-runtime-tests.xml', 'historical-owner-regression.xml'):
        pin(OUT / name)
        suites = list(ET.parse(OUT / name).getroot().iter('testsuite'))
        counts = {field:sum(int(suite.get(field, '0')) for suite in suites)
                  for field in ('tests', 'failures', 'errors', 'skipped')}
        assert counts['failures'] == counts['errors'] == counts['skipped'] == 0
        test_counts[name] = counts
    assert test_counts['contextual-runtime-tests.xml']['tests'] == 244
    assert test_counts['historical-owner-regression.xml']['tests'] == 210
    doc = WT / 'docs/autoencoders/contextual_legal_reconstruction_runtime.md'
    doc_pin = pin(doc); doc_text = doc.read_text(); doc_normalized = normalized(doc_text)
    assert generation['datasets_head'] in doc_text
    assert '| Original text UTF-8 byte equality | 0/48 | 0/48 |' in doc_text
    assert '| Original text NFC/whitespace equality | 0/48 | 0/48 |' in doc_text
    assert 'The registrar is allowed to preserve the archive.' in doc_normalized
    assert 'Registrar may preserve archive.' in doc_text
    assert len(examples) == 2
    assert 'every reference qualifier is empty' in doc_normalized
    assert '**244**' in doc_text and '**210**' in doc_text
    before = list(PROTECTED.values())
    after = [pin(row['path']) for row in before]
    assert before == after and 'torch' not in sys.modules
    report = dict(schema='contextual-legal-completed-execution-independent-review/v1',
        observed_at_utc=datetime.now(timezone.utc).isoformat(), completed=True,
        review_method='stdlib saved-row recomputation and fresh byte pin joins; no project/model imports',
        torch_imported=False, model_training_or_generation_rerun=False, source_edited=False,
        source_commit=generation['datasets_head'], generation_receipt_pin=pin(OUT / 'generation-qualification.json'),
        separate_evaluation_receipt_pin=pin(OUT / 'separate-evaluation.json'), script_pin=pin(__file__),
        frozen21_source_pins_freshly_match=True, required8_assets_and_donor_freshly_match=True,
        original44_custody_files_freshly_match=True, original_historical_candidate_manifest_and_files_exact=True,
        all_reviewed_file_pins_before=before, all_reviewed_file_pins_after=after,
        all_reviewed_files_unchanged=True, lanes=summaries, verified_doc_example=examples,
        saved_JUnit_counts=test_counts, total_saved_tests_passed=454,
        metric_section_doc_pin=doc_pin, doc_metrics_API_scope_findings=[],
        reconstruction_interpretation='Both retained cached lanes reproduce the original authored semantic rule outputs exactly. Canonical inspection is actual current contract conformance, with checkpoint native schema/profile/format identities still null. The deterministic generated-IR-to-text baseline returns48 texts per lane but recovers0 original texts under either metric. Empty qualifiers and exposed48-row/512-token corpus do not qualify nonempty qualifiers, new source groups,8192 spans, trained original-prose reconstruction, teacher or proof authority.',
        all_native_profile_teacher_production_holdout_proof_authority_false=True,
        no_remaining_findings=True)
    target = OUT / 'source-survey/execution-review.json'
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    docs_path = OUT / 'source-survey/docs-review.json'
    docs = json.loads(docs_path.read_text())
    docs['previous_review_pin_before_final_metrics'] = pin(docs_path)
    docs['doc_pin_after_real_metrics'] = doc_pin
    docs['real_reconstruction_metric_evidence_section_not_yet_reviewed'] = False
    docs['final_real_metric_section_review_pin'] = pin(target)
    docs['review_conclusion'] = 'No remaining API, scope or executed metric findings. Both lane IR48/48,180rules,720main fields, empty qualifiers, deterministic text0/48 under both metrics, registrar example and244+210tests are independently verified from persisted rows/receipts. No reviewer model/test rerun.'
    docs_path.write_text(json.dumps(docs, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(execution_review_pin=pin(target), final_docs_review_pin=pin(docs_path),
        reviewed_original_files=44, model_or_test_reruns=False,
        summaries=[{key:value for key,value in lane.items() if key in ('dimension','rows','ordered_IR_exact',
            'canonical_contract_exact','rules','UTF8_text_exact','NFC_whitespace_text_exact')} for lane in summaries]), sort_keys=True))


if __name__ == '__main__':
    main()
