"""Consume the exact experimental Hub checkpoint through supervisor inference."""
import argparse
import hashlib
import json
from pathlib import Path

from ipfs_datasets_py.logic.formalization.autoencoder.intent_action_hub_384 import resolve_intent_action_checkpoint, SCHEMA
from ipfs_accelerate_py.agent_supervisor.runtime.intent_384_advisor import prepare_intent_384_advice, validate_intent_384_advice

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--receipt', type=Path, required=True)
args = parser.parse_args()
receipt = json.loads(args.receipt.read_bytes())
reference = {key: receipt[key] for key in ('repository_id', 'revision', 'checkpoint_path', 'checkpoint_sha256')}
reference['schema'] = SCHEMA
options = resolve_intent_action_checkpoint(reference, local_files_only=False)
source = json.loads((root / 'native-01/case-000/instruction.json').read_bytes())['instruction']
config = dict(schema='supervisor-intent-action-384-config/v1', checkpoint_path=options['checkpoint_path'],
    checkpoint_sha256=options['expected_sha256'], embedding_snapshot_path=None)
advice = prepare_intent_384_advice(instruction=source, config=config)
assert advice['status'] == 'semantic_candidate_advice' and advice['numerical_replay_verified'] is True
assert validate_intent_384_advice(advice, instruction=source) == advice
original = json.loads((root / 'native-01/case-000/intent-advice.json').read_bytes())
assert advice['raw_candidate_ir'] == original['raw_candidate_ir']
assert advice['candidate_intent_ir'] == original['candidate_intent_ir']
assert hashlib.sha256(Path(options['checkpoint_path']).read_bytes()).hexdigest() == reference['checkpoint_sha256']
for name, value in [('hub-reference.json', reference), ('hub-consumer-advice.json', advice),
    ('hub-consumer-verification.json', dict(schema='intent-action-hub-consumer-verification/v1', reference=reference,
        model_inference_executed=advice['report']['model_inference_executed'], numerical_replay_verified=True,
        same_raw_candidate=True, same_source_bound_candidate=True, downloaded_checkpoint_unchanged=True,
        default_model_promoted=False, proof_authority=False, source_semantics_verified=False))]:
    with (root / name).open('xb') as handle:
        handle.write(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
print(json.dumps({'status': advice['status'], 'revision': reference['revision'], 'same_candidate': True}))
