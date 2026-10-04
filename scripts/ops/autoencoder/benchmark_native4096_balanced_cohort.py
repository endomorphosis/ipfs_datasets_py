#!/usr/bin/env python3
"""Reserved native4096 balanced TRAIN/development reconstruction comparison.

Run inside a dedicated systemd scope and the campaign reservation guardian.
All local source/input files must be sealed first. No model is downloaded and
the shared inference service is not used or modified.
"""
import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import sys
import time
import types

PACKAGE = "ipfs_datasets_py.logic.formalization.autoencoder"
FIXED = dict(schema="native4096-balanced-cohort-plan/v1", dimension=4096,
    unique_training_sources=12, development_sources=12, native_forward_rows=25,
    repeat_l2_tolerance=1e-6, optimizer_steps=200, arm_count=2,
    arms=['joint_unscaled', 'joint_source_scaled'], learning_rate=.001, decoder_max_seconds=300,
    encoder_context_tokens=512, decoder_output_tokens=512, temperature=0,
    workers=1, native_threads=1, native_deadline_seconds=900,
    native_rss_limit_bytes=8*1024**3, bridge_names=[], legal_ir_evaluate_provers=False,
    metric_disk_cache_used=False, validation_count=12, checkpoint_promoted=False,
    development_status='previously_exposed_original_development_split')

PRODUCERS = [PACKAGE.replace('.', '/')+'/'+name+'.py' for name in (
    'decoder_distillation_experiment', 'decoder_distillation_experiment_v2',
    'source_embeddings_4096_native_owner', 'source_embeddings_4096_full_owner',
    'native4096_formula_sidecar_experiment', 'native4096_conditioning_experiment',
    'native4096_balanced_cohort_experiment')]


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def install_frozen_namespace(root):
    """No editable-install fallback; every project import has one frozen path."""
    pieces = PACKAGE.split('.')
    for count in range(1, len(pieces)+1):
        name = '.'.join(pieces[:count])
        require(name not in sys.modules, 'project package was imported before source pin')
        module = types.ModuleType(name)
        module.__path__ = [str(root.joinpath(*pieces[:count]))]
        module.__package__ = name
        sys.modules[name] = module
    return importlib.import_module(PACKAGE+'.native4096_balanced_cohort_experiment')


def restore_raw_donor(checkpoint, torch):
    """Exact private original384 GRU body, never a production checkpoint loader."""
    require(checkpoint.get('schema') == 'shared-source-384-autoencoder/v2'
            and checkpoint.get('dimension') == 384, 'original384 donor required')
    config, codec = checkpoint['config'], checkpoint['codec']
    require(config['hidden_size'] == 32 and config['token_embedding_dim'] == 16
            and config['projection_width'] == 8 and len(codec['target_vocabulary']) == 32,
            'sealed donor geometry differs')

    class Donor(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.projection_down = torch.nn.Linear(384, 8, dtype=torch.float32, device='cpu')
            self.projection_up = torch.nn.Linear(8, 384, dtype=torch.float32, device='cpu')
            self.condition = torch.nn.Linear(384, 32, dtype=torch.float32, device='cpu')
            self.target_embedding = torch.nn.Embedding(32, 16, padding_idx=0, dtype=torch.float32, device='cpu')
            self.decoder = torch.nn.GRU(16, 32, batch_first=True, dtype=torch.float32, device='cpu')
            self.output = torch.nn.Linear(32, 32, dtype=torch.float32, device='cpu')

        def project(self, value):
            return value+self.projection_up(torch.tanh(self.projection_down(value)))

        def start(self, value):
            return torch.tanh(self.condition(value)).unsqueeze(0)

        def next_logits(self, tokens, hidden):
            values, hidden = self.decoder(self.target_embedding(tokens), hidden)
            return self.output(values), hidden

    with torch.random.fork_rng(devices=[]):
        model = Donor()
    values = {name: torch.tensor(value, dtype=torch.float32, device='cpu') for name, value in checkpoint['model_state'].items()}
    require(set(values) == set(model.state_dict()), 'donor tensor inventory differs')
    for name, template in model.state_dict().items():
        require(template.shape == values[name].shape and bool(torch.isfinite(values[name]).all()),
                'donor tensor shape or finite values differ')
    model.load_state_dict(values, strict=True)
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['preflight', 'training'], required=True)
    parser.add_argument('--dependency-root', type=Path, required=True)
    parser.add_argument('--extension-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    manifest_bytes, plan_bytes = args.manifest.read_bytes(), args.plan.read_bytes()
    manifest, plan = json.loads(manifest_bytes), json.loads(plan_bytes)
    require(set(PRODUCERS) <= set(manifest['extensions']), 'complete frozen project producer closure required')
    require(hashlib.sha256(plan_bytes).hexdigest() == manifest['plan_sha256'], 'pilot plan changed')
    require(all(type(plan.get(k)) is type(v) and plan[k] == v for k, v in FIXED.items()),
            'fixed native pilot recipe differs')
    reclaim = plan.get('reclaim_model_mappings', False)
    require(type(reclaim) is bool, 'explicit native mapping-reclaim mode required')
    for key in ('cohort_path', 'training_bank_path', 'development_bank_path', 'source_cache_path',
                'token_receipt_path', 'donor_path', 'build_receipt_path'):
        require(type(plan.get(key)) is str and plan[key] in manifest['inputs'],
                'unsealed pilot input: '+key)

    def recheck():
        require(args.manifest.read_bytes() == manifest_bytes and args.plan.read_bytes() == plan_bytes,
                'pilot manifest or plan changed')
        for name, expected in manifest['extensions'].items():
            require(sha(args.extension_root/name) == expected, 'frozen producer changed: '+name)
        for path, expected in manifest['inputs'].items():
            require(sha(path) == expected, 'bound input changed: '+path)

    recheck()
    args.output.mkdir(exist_ok=False)
    subject = install_frozen_namespace(args.extension_root)
    donor_json = json.loads(Path(plan['donor_path']).read_text())
    cohort = json.loads(Path(plan['cohort_path']).read_text())
    selected = subject.select_original_cohort(
        json.loads(Path(plan['training_bank_path']).read_text()),
        json.loads(Path(plan['development_bank_path']).read_text()),
        json.loads(Path(plan['source_cache_path']).read_text()),
        json.loads(Path(plan['token_receipt_path']).read_text()), donor_json['codec'])
    require(cohort == selected, 'cohort differs from deterministic original split selection')
    training_labels, development_labels = cohort['training_labels'], cohort['development_labels']
    source_rows = [{k: row[k] for k in ('id', 'source_text')}
                   for row in training_labels+development_labels]
    source_rows.append(dict(id='repeat:'+source_rows[0]['id'], source_text=source_rows[0]['source_text']))
    require(len(source_rows) == 25 and len({r['id'] for r in source_rows}) == 25,
            '25 unique native request identities required')
    require(source_rows == plan['native_sources'], 'sealed balanced source selection differs')
    import torch
    torch.set_num_threads(1)
    subject.core._torch()
    donor = restore_raw_donor(donor_json, torch)
    require(list(subject.ARMS) == plan['arms'] and subject.STEPS == plan['optimizer_steps'],
            'frozen subject comparison recipe differs from plan')
    save(args.output/'source-request.json', source_rows)
    save(args.output/'cohort.json', cohort)
    if args.phase == 'preflight':
        recheck()
        save(args.output/'summary.json', dict(complete=True, training_executed=False,
            donor_tensor_sha256=subject.core.tensor_digest(donor), source_count=24, training_source_count=12, development_source_count=12,
            native_forward_executed=False, qualified=False, admitted=False))
        return
    import_path = importlib.import_module(PACKAGE+'.source_embeddings_4096_full_owner')
    membership = Path('/proc/self/cgroup').read_text().strip()
    require(membership.startswith('0::') and '\n' not in membership, 'single unified cgroup required')
    cgroup = Path('/sys/fs/cgroup')/membership[3:].lstrip('/')
    require(cgroup.name.startswith('native4096-pilot-') and cgroup.name.endswith('.scope'),
            'dedicated native pilot scope required')
    require((cgroup/'cgroup.procs').read_text().split() == [str(os.getpid())],
            'pilot scope already contains another process')
    (cgroup/'memory.oom.group').write_text('1')
    build = json.loads(Path(plan['build_receipt_path']).read_text())
    operation = import_path.run_full_forward(source_rows,
        worker_path=build['worker']['path'], worker_sha256=build['worker']['sha256'],
        worker_source_path=build['worker_source']['path'], worker_source_sha256=build['worker_source']['sha256'],
        model_path=plan['model_path'], expected_model_sha256=plan['model_sha256'],
        expected_library_sha256=build['runtime_library_sha256'], resource_cgroup=cgroup,
        output_directory=args.output/'native', deadline_seconds=plan['native_deadline_seconds'],
        max_rss_bytes=plan['native_rss_limit_bytes'], reclaim_model_mappings=reclaim)
    native = import_path.require_live_result(operation)
    rows = native['rows']
    require([r['id'] for r in rows] == [r['id'] for r in source_rows], 'native result ordering differs')
    repeat_l2 = math.sqrt(sum((a-b)**2 for a, b in zip(rows[0]['embedding'], rows[-1]['embedding'])))
    require(len(rows[0]['embedding']) == len(rows[-1]['embedding']) == 4096
            and repeat_l2 <= plan['repeat_l2_tolerance'], 'native KV-reset repeat control failed')
    save(args.output/'reset-control.json', dict(repeat_l2=repeat_l2,
        tolerance=plan['repeat_l2_tolerance'], qualified=False, admitted=False))
    recheck()
    result = subject.train_native_cohort(operation, donor=donor, codec=donor_json['codec'],
        training_labels=training_labels, development_labels=development_labels,
        max_seconds=plan['decoder_max_seconds'])
    save(args.output/'training.json', result)
    recheck()
    summary = dict(schema='native4096-balanced-cohort-summary/v1', complete=True,
        training_executed=True, native_forward_executed=True, unique_training_sources=12, development_sources=12,
        native_forward_rows=25, optimizer_steps=sum(arm['optimizer_steps'] for arm in result['arms']),
        arms=[{key: arm[key] for key in ('arm', 'optimizer_steps', 'fit_seconds', 'observations')}
              for arm in result['arms']],
        elapsed_seconds=time.monotonic()-started, training_sha256=sha(args.output/'training.json'),
        native_receipt_sha256=native['provenance']['receipt_sha256'],
        native_profile=native['provenance']['profile'], reclaim_model_mappings=reclaim,
        repeat_l2=repeat_l2, bridge_names=[], legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False, workers=1, validation_count=12,
        admitted=False, qualified=False, lake_executed=False, checkpoint_promoted=False,
        claim_scope='balanced12 original TRAIN and12 exposed original development clauses; two matched GRU pilot arms; no fresh holdout or qualification')
    save(args.output/'summary.json', summary)
    print(json.dumps(summary, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
