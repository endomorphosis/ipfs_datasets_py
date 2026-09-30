"""Local evidence harness: explicit diagnostic vectors, no training or admission."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ['IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE'] = '0'
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', choices=('legacy_v1', 'legacy_v1_optimized'), required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    parser.error('output already exists; retain previous receipts and choose a fresh path')
runtime = importlib.import_module('ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.' + args.runtime)
paths = require_workspace_logic_tree()
def hashes():
    return {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in paths.items()}
before = hashes()
state_path = ROOT / 'workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json'
expected = '1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd'
t0 = time.perf_counter()
model = runtime.load_checkpoint(state_path, expected_sha256=expected, compute_device='cpu')
load_seconds = time.perf_counter() - t0
texts = [
    'Company A shall submit backup report within 10 days unless emergency.',
    'The agency shall not disclose records.',
    'The officer shall retain the file for at least 20 days.',
]
t0 = time.perf_counter()
samples = [runtime.build_sample(title='gate', section=str(i), text=text,
    embedding_vector=[(i % 7 - 3) / 7 for i in range(8)],
    embedding_model='test:explicit-synthetic-8d-not-semantic') for i, text in enumerate(texts)]
sample_seconds = time.perf_counter() - t0
names = ['modal_frame_logic', 'deontic_norms', 'fol_tdfol', 'cec_dcec', 'external_prover_router']
t0 = time.perf_counter()
result = model.evaluate(samples, legal_ir_bridge_names=names, legal_ir_evaluate_provers=False,
    legal_ir_parallel_workers=1, use_sample_memory=False)
seconds = time.perf_counter() - t0
after = hashes()
assert before == after, 'canonical compiler/parser/decompiler changed during measurement'
assert result.legal_ir_target_count == len(samples)
payload = dict(schema='legacy-profile-bridge-parity/v1', runtime=args.runtime, checkpoint_sha256=expected,
    source_paths=paths, source_sha256=before, canonical_sources_stable=True,
    load_seconds=load_seconds, sample_preparation_seconds=sample_seconds,
    bridge_on_evaluate_seconds=seconds, seconds_per_span=seconds/len(samples),
    bridge_names=names, legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1,
    metric_disk_cache=0, cache_scope='fresh process; no supplied targets; OS cache uncontrolled',
    use_sample_memory=False, sample_count=len(samples), texts=texts,
    embedding_kind='explicit synthetic diagnostics; semantic qualification unavailable',
    legal_ir_target_count=result.legal_ir_target_count,
    metrics={key: getattr(result, key) for key in ['reconstruction_loss', 'embedding_cosine_similarity',
        'legal_ir_losses', 'legal_ir_view_family_metrics', 'legal_ir_view_distribution']},
    admitted=False, qualified=False, optimizer_step=False)
out = args.output
out.parent.mkdir(parents=True, exist_ok=True)
payload['harness_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
with out.open('x', encoding='utf-8') as handle:
    handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + '\n')
print(json.dumps({k: payload[k] for k in ['runtime', 'sample_count', 'legal_ir_target_count',
    'bridge_on_evaluate_seconds', 'seconds_per_span']}))
