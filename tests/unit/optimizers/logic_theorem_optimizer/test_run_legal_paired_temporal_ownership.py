"""Closed selection policy, source-only output and fresh-reference isolation."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from scripts.ops.legal_ir import run_legal_paired_temporal_ownership as runner


def stage(step, *, correct=144, accepted_wrong=0, f1=.8, nll=.4):
    return {'steps': step, 'checkpoint': {'path': f'/checkpoint-{step}', 'sha256': str(step).zfill(64)},
            'decoder_kind': 'old_owner_type' if step == 0 else 'paired_owner_type',
            'single_tuning_metrics': {'count': 144, 'correct': correct, 'accepted_wrong': accepted_wrong},
            'paired_tuning_metrics': {'count': 288, 'macro_f1': f1, 'nll': nll}}


def test_old_single_accuracy_gate_rejects_even_large_new_multi_gain():
    parent = stage(0)
    stages = [stage(step, correct=143, f1=.99, nll=.01) for step in runner.STAGES]
    assert runner.select_stage(parent, stages) is parent


def test_old_accepted_errors_cannot_be_hidden_by_equal_accuracy():
    parent = stage(0)
    stages = [stage(step, accepted_wrong=1, f1=1., nll=0.) for step in runner.STAGES]
    assert runner.select_stage(parent, stages) is parent


def test_fixed_policy_has_no_undocumented_confidence_coverage_gate():
    parent = stage(0); candidate = stage(50, f1=.9)
    parent['single_tuning_metrics']['accepted'] = 144
    candidate['single_tuning_metrics']['accepted'] = 0
    assert runner.eligible(candidate, parent)
    assert runner.select_stage(parent, [candidate, stage(100), stage(200)]) is candidate


def test_parent_wins_complete_tie_and_no_gain_falls_back():
    parent = stage(0)
    assert runner.select_stage(parent, [stage(step) for step in runner.STAGES]) is parent
    assert runner.select_stage(parent, [stage(step, f1=.79, nll=.01) for step in runner.STAGES]) is parent


def test_rank_is_new_multi_macro_f1_then_nll_then_earlier():
    parent = stage(0)
    stages = [stage(50, f1=.9, nll=.5), stage(100, f1=.9, nll=.3), stage(200, f1=.9, nll=.3)]
    assert runner.select_stage(parent, stages) is stages[1]
    stages[2]['paired_tuning_metrics']['macro_f1'] = .91
    stages[2]['paired_tuning_metrics']['nll'] = 2.
    assert runner.select_stage(parent, stages) is stages[2]


@pytest.mark.parametrize('steps', [(50, 200), (50, 50, 200), (200, 100, 50), (0, 100, 200)])
def test_incomplete_or_reordered_stage_inventory_rejected(steps):
    with pytest.raises(ValueError, match='prospective'): runner.select_stage(stage(0), [stage(step) for step in steps])


@pytest.mark.parametrize('key,value', [('count', 143), ('count', 144.), ('correct', True), ('correct', 145), ('accepted_wrong', -1)])
def test_bad_old_retention_counts_fail_closed(key, value):
    candidate = stage(50); candidate['single_tuning_metrics'][key] = value
    with pytest.raises(ValueError): runner.eligible(candidate, stage(0))


@pytest.mark.parametrize('key,value', [('count', 287), ('count', 288.), ('macro_f1', float('nan')),
                                      ('macro_f1', 1.1), ('macro_f1', True), ('nll', -1), ('nll', float('inf'))])
def test_bad_new_tuning_metrics_fail_closed(key, value):
    candidate = stage(50); candidate['paired_tuning_metrics'][key] = value
    with pytest.raises(ValueError): runner.stage_rank(candidate)


def source(index):
    text = f'Registry{index} shall file within 10 days.'; start = text.index('within')
    return {'id': f'query-{index}', 'source_text': text, 'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'proposed_time_span': {'char_start': start, 'char_end': start + len('within 10 days')}}


def test_generate_receives_only_exact_source_queries_and_records_physical_metadata(tmp_path, monkeypatch):
    queries = [source(index) for index in range(50)]
    source_pin = runner.write(tmp_path / 'sources.json', queries)
    cp_pin = {'path': '/old-checkpoint', 'sha256': 'a' * 64, 'schema': runner.runtime.previous.SCHEMA}
    class Decoder:
        encoder_batch_forwards = 0
        encoder_source_evaluations = 0
        def predict_many(self, rows):
            assert all(set(row) == runner.runtime.SOURCE_KEYS for row in rows)
            self.encoder_batch_forwards += 1; self.encoder_source_evaluations += len(rows)
            return [{'id': row['id'], 'source_sha256': row['source_sha256'], 'proposed_time_span': row['proposed_time_span']} for row in rows]
    monkeypatch.setattr(runner, 'load_decoder', lambda pin, kind: ({'config': {'arm': 'finetune_occurrence', 'seed': 1730}, 'optimizer_steps': 200}, Decoder()))
    pin, value = runner.generate(cp_pin, source_pin, tmp_path / 'generation.json', decoder_kind='old_owner_type')
    assert value['model'] == {'checkpoint': cp_pin, 'decoder_kind': 'old_owner_type', 'arm': 'finetune_occurrence', 'seed': 1730, 'steps': 200}
    assert value['encoder_batch_forwards'] == 2 and value['encoder_source_evaluations'] == 50
    assert [row['id'] for row in value['rows']] == [row['id'] for row in queries]
    assert value['labels_supplied'] is False and value['source_id_used_as_feature'] is False
    assert all(value[key] is False for key in runner.runtime.FALSE)
    assert runner.read(pin) == value


def test_selected_parent_is_old_checkpoint_reference_not_new_initial_alias():
    parent = stage(0); chosen = runner.select_stage(parent, [stage(step) for step in runner.STAGES])
    assert chosen['decoder_kind'] == 'old_owner_type' and chosen['checkpoint'] is parent['checkpoint']


def test_unknown_decoder_kind_rejected_before_any_file_read(monkeypatch):
    with pytest.raises(ValueError, match='kind'): runner.load_decoder({'path': '/missing', 'sha256': 'a' * 64}, 'guess')


def test_reference_read_handles_documented_schema_metadata_but_not_wrong_bytes(tmp_path):
    ref = runner.write(tmp_path / 'cp.json', {'schema': 'fixture'})
    assert runner.read({**ref, 'schema': 'fixture'}) == {'schema': 'fixture'}
    with pytest.raises(ValueError, match='binding'): runner.read({**ref, 'bytes': ref['bytes'] + 1})


def test_producer_closure_includes_inherited_source_proposer_and_corpus_loader():
    from ipfs_datasets_py.logic.autoformal import legal_paired_temporal_ownership_corpus as schema
    pins = runner.producer_pins()
    for ref in schema.old.producer_refs():
        assert pins[ref['path']] == ref['sha256']
    assert pins[str(Path(runner.runtime.previous.__file__).resolve())] == runner.reference(runner.runtime.previous.__file__)['sha256']


def test_fresh_four_file_denial_is_installed_before_corpus_loading(tmp_path):
    artifacts = {}
    for key in runner.SEALED_KEYS:
        artifacts[key] = runner.write(tmp_path / (key + '.json'), {'forbidden': True})
    manifest = runner.write(tmp_path / 'manifest.json', {'artifacts': artifacts})
    config = runner.write(tmp_path / 'config.json', {'corpus_manifest': manifest})
    program = '''
import json,sys
from pathlib import Path
from scripts.ops.legal_ir import run_legal_paired_temporal_ownership as r
r.install_fresh_reference_guard(sys.argv[1])
paths=list(r._GUARD['paths'])
for path in paths:
 try:Path(path).read_bytes()
 except PermissionError:pass
 else:raise AssertionError('fresh label unexpectedly readable')
assert r.guard_receipt()['premature_read_attempts']==4
print('all four blocked')
'''
    result = subprocess.run([sys.executable, '-c', program, config['path']], cwd=runner.ROOT,
                            env={**os.environ, 'CUDA_VISIBLE_DEVICES': '-1'}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'all four blocked' in result.stdout
