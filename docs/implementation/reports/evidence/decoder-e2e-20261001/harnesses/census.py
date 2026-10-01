"""Local real-producer integration; no Hub, supervisor execution, or admission."""
from pathlib import Path
import hashlib
import json
import subprocess
import time
import xml.etree.ElementTree as ET

import torch
torch.set_num_threads(1)

from ipfs_datasets_py.logic.autoformal import AutoformalSession, compile_span
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from ipfs_datasets_py.logic.autoformal import span_cache_exchange as exchange
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as interface

OUT = Path(__file__).resolve().parent
ROOT = Path.cwd()
TRAIN = ROOT / 'workspace/decoder-e2e-20261001/legal-20261001T015700Z/train/report.json'
START = time.monotonic()

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def write(name, value):
    (OUT / name).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')

pin = require_workspace_logic_tree()
source_hashes = {key: sha(Path(path).read_bytes()) for key, path in pin.items()}
code = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
training = json.loads(TRAIN.read_text())
binding = training['checkpoint']
runtime = interface.open_runtime('legal_ir', interface.LEARNED_FORMULA_VERSION,
    checkpoint=binding['path'], expected_sha256=binding['sha256'])
model = interface.LEARNED_FORMULA_VERSION + ':sha256:' + binding['sha256']
texts = ['The officer shall retain the file for at least 20 days unless emergency.',
         'This provision relates to administrative review.']
compile_start = time.monotonic()
compiled = [compile_span(AutoformalSession(), text, f'authored-boundary-{i}') for i, text in enumerate(texts)]
compile_wall = time.monotonic() - compile_start
infer_start = time.monotonic()
inference = runtime.infer([texts[0]])
infer_wall = time.monotonic() - infer_start
prediction = inference['rows'][0]
assert prediction['status'] == 'decoded'
assert prediction['independent_text_to_logic'] is True
assert prediction['teacher_forcing'] is False and prediction['target_access'] is False
assert prediction['source_sha256'] == sha(texts[0].encode())
assert compiled[0]['rules'][0]['exceptions'] == ['emergency']
assert prediction['canonical_ir']['rules'][0]['exceptions'] == []
assert compiled[1]['compiler_status'] == 'abstain'

# Explicit test adapter for the current paired schema. Preserve the full actual
# ASTs. Equality remains raw representation equality (including temporal_records),
# not semantic equivalence. The learned producer's validated decoder grammar is
# the only syntax claim here; this does not claim the eight-family syntax floor.
model_outputs = [{**output, 'family': 'typed_deontic', 'origin': 'autoencoder_decoder',
    'independent': True, 'target_conditioned': False, 'syntax_status': 'passed'}
    for output in prediction['formal_outputs']]
observations = []
for index, (text, compiler) in enumerate(zip(texts, compiled)):
    observations.append({'source_span_id': f'authored-boundary-{index}',
        'legal_id': f'authored:e2e:{index}', 'text': text,
        'source_text_sha256': sha(text.encode()), 'release_id': 'authored-e2e-20261001',
        'compiler_result': compiler, 'strict_compiler_agreement': compiler.get('roundtrip', False),
        'metric_scope': 'authored_local_integration_no_vector_metrics',
        'model_formal_outputs': model_outputs if index == 0 else [],
        'model_formal_output_provenance': {
            'source_text_sha256': sha(text.encode()), 'model_identity': model,
            'complete': index == 0, 'origin': 'autoencoder_decoder',
            'syntax_scope': 'canonical_rule_schema_and_decoder_grammar',
            'producer_original_origin': 'learned_source_conditioned_formula_decoder',
            'adapter_scope': 'test_harness_family_and_origin_vocabulary_only_payloads_unchanged'},
        'actual_learned_inference': prediction if index == 0 else None})

producer_receipt = {'schema': 'authored-real-census-producer/v1',
    'checkpoint': binding, 'inference': inference,
    'rows': [{'source_span_id': row['source_span_id'], 'text': row['text'],
              'compiler': row['compiler_result'], 'actual_learned_inference': row['actual_learned_inference']}
             for row in observations],
    'admitted': False, 'formalized': False}
built = paired.build_paired_census(observations, code_identity=code, model_identity=model,
    original_receipt=producer_receipt, agent_id='local-boundary-e2e', release_id='authored-e2e-20261001')
assert built['paired_spans'][0]['comparison']['status'] == 'disagree'
assert built['paired_spans'][0]['comparison']['independent'] is True
assert any(goal['record_kind'] == 'repair_packet' for goal in built['goals'])
paired_receipt = paired.write_paired_census_bundle(built, OUT / 'paired')
readback = paired.load_paired_census_bundle(paired_receipt['manifest']['path'])
assert readback['original_receipt'] == producer_receipt
assert readback['paired_spans'] == built['paired_spans']
assert readback['goals'] == built['goals']
for row, result in zip(observations, built['paired_spans']):
    row['comparison'] = result['comparison']
    row['comparison_provenance'] = {'kind': 'exact_raw_ast_sequence',
        'observation_id': result['observation_id'], 'independent_model': result['comparison']['independent'],
        'scope': 'representation_equality_not_source_semantic_validation'}

export = exchange.publish_compiled_exchange(observations, OUT / 'exchange', upload=False,
    agent_id='local-boundary-e2e', code_identity=code, model_identity=model,
    release_id='authored-e2e-20261001')
loaded = exchange.load_exchange_bundle(export['manifest']['path'])
goal_only = exchange.load_goal_export(export['goals']['path'])
assert goal_only['goal_rows'] == loaded['goal_rows']
assert len(loaded['census_rows']) == 2
assert len(loaded['repair_packets']) >= 1 and len(loaded['training_goals']) >= 1
by_hash = {row['census_sha256']: row for row in loaded['census_rows']}
for goal in loaded['goal_rows']:
    assert goal['enqueued'] is False and goal['admitted'] is False and goal['formalized'] is False
    packet = json.loads(goal['packet_json'])
    capture = packet.get('capture') or packet['row']['capture']
    evidence = capture['observation_evidence']
    row = by_hash[goal['census_sha256']]
    assert evidence == exchange._observation_evidence(row)
    assert evidence['counts_as_validation'] is False
    assert evidence['retrieval']['require_manifest_verification'] is True
    assert evidence['input_json_sha256'] == sha(row['input_json'].encode())
    original = json.loads(row['input_json'])
    assert original['compiler_result'] == compiled[int(row['source_span_id'].rsplit('-', 1)[1])]
    if original['actual_learned_inference'] is not None:
        assert original['actual_learned_inference'] == prediction

# Verify immutable retry/readback. Tamper rejection is covered in the saved tests.
retry = exchange.publish_compiled_exchange(observations, OUT / 'exchange', upload=False,
    agent_id='local-boundary-e2e', code_identity=code, model_identity=model,
    release_id='authored-e2e-20261001')
assert retry['fingerprint'] == export['fingerprint']
assert source_hashes == {key: sha(Path(path).read_bytes()) for key, path in pin.items()}
test_suites = []
for path in sorted(OUT.parent.glob('*.xml')):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == 'testsuite' else list(root.findall('testsuite'))
    test_suites.append({'path': str(path), 'sha256': sha(path.read_bytes()),
        'tests': sum(int(s.attrib['tests']) for s in suites),
        'failures': sum(int(s.attrib['failures']) for s in suites),
        'errors': sum(int(s.attrib['errors']) for s in suites),
        'skipped': sum(int(s.attrib['skipped']) for s in suites),
        'suite_seconds': sum(float(s.attrib['time']) for s in suites)})
write('producer.json', producer_receipt)
write('observations.json', observations)
write('paired-receipt.json', paired_receipt)
write('exchange-receipt.json', export)
artifact_files = [Path(paired_receipt['manifest']['path']), Path(export['manifest']['path']),
                  Path(export['census']['path']), Path(export['goals']['path']), OUT/'producer.json', OUT/'observations.json']
report = {'schema': 'real-census-boundary-e2e/v1', 'git_head': code, 'tree_pin': pin,
    'logic_source_sha256': source_hashes, 'logic_source_unchanged': True,
    'checkpoint': binding, 'training_report_sha256': sha(TRAIN.read_bytes()),
    'source_kind': 'two_authored_integration_clauses_not_US_Code_corpus',
    'sample_count': len(texts), 'real_compiler_count': len(compiled),
    'real_learned_inference_count': 1, 'synthetic_guidance_used': False,
    'real_missing_exception_observed': True,
    'compiler_wall_seconds': compile_wall, 'compiler_wall_seconds_per_span': compile_wall/len(texts),
    'inference_wall_seconds': infer_wall, 'inference_wall_seconds_per_span': infer_wall,
    'paired_comparisons': [row['comparison'] for row in built['paired_spans']],
    'paired_goal_count': len(readback['goals']), 'paired_readback_exact': True,
    'exchange_repair_packet_count': len(loaded['repair_packets']),
    'exchange_training_goal_count': len(loaded['training_goals']),
    'exchange_observation_evidence_bound': True, 'exchange_immutable_retry': True,
    'full_actual_learned_inference_retained_in_input_json': True,
    'old_exchange_v3_learned_formula_column_support': False,
    'paired_adapter_scope': 'test_harness_maps_family_and_origin_only_full_AST_preserved',
    'comparison_scope': 'exact_raw_representation_including_metadata_not_semantic_equivalence',
    'test_suites': test_suites, 'tested_count': sum(s['tests'] for s in test_suites),
    'artifacts': [{'path': str(p), 'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size} for p in artifact_files],
    'bridge_names': [], 'legal_ir_target_count': 0, 'legal_ir_evaluate_provers': False,
    'metric_disk_cache': False, 'legal_ir_parallel_workers': 1, 'bridge_on_measurement': False,
    'cache_scope': 'fresh_local_census_outputs_no_metric_bridges_invoked',
    'weights_downloaded': False, 'hub_uploaded': False, 'supervisor_enqueued': False,
    'training_executed_here': False, 'temperature': 0, 'device': 'cpu',
    'native_formula_fleet_worker_adapter_available': False,
    'native_formula_hub_exchange_adapter_available': False,
    'lake_executed_here': False, 'admitted': False, 'formalized': False, 'qualified': False,
    'elapsed_seconds': time.monotonic()-START}
write('report.json', report)
print(json.dumps({key: report[key] for key in ['tested_count', 'paired_goal_count', 'exchange_repair_packet_count', 'exchange_training_goal_count', 'elapsed_seconds']}))
