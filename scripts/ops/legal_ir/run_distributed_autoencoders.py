#!/usr/bin/env python3
"""Shared-owner span training with verified complete-weight synchronization.

Run one owner and independent worker processes (local or through explicit SSH
forwarding). Only the owner opens the shared registry. All legal qualifications
remain in the existing native gate engine; transport never admits a theorem.
Explicit feature_pretraining shares unqualified feature checkpoints through a
separate verifier and Hub namespace, with locally provisioned verified inputs.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_distributed_training as work
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.autoencoder_span_campaign import (
    AutoencoderSpanCampaign, SpanCampaignQuackGateway, SpanCampaignTransportClient,
)


def normalize(records):
    result = []
    for record in records:
        row = dict(record)
        row['sample'] = json.loads(work.inc._raw(asdict(SampleRecord.from_dict(row['sample']))))
        row['text'] = row['sample']['text']
        row['source_text_sha256'] = hashlib.sha256(row['text'].encode()).hexdigest()
        row.setdefault('source_span_id', row['record_id'])
        result.append(row)
    return result


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _emit(value):
    print(_json(value), flush=True)


def _connection(path, token_path=None, endpoint_override=None):
    config = work._read(path)
    token_path = Path(token_path or config['token_file'])
    if token_path.is_symlink() or token_path.stat().st_mode & 0o077 or token_path.stat().st_size > 1024:
        raise work.DistributedTrainingError('token must be a bounded private regular file')
    return SpanCampaignTransportClient(endpoint_override or config['endpoint'], token_path.read_text().strip())


def _reserve(args):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation
    ledger = Path(args.resource_ledger)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    roots = [row['path'] for row in json.loads(ledger.read_bytes())['roots']] if ledger.exists() else [str(args.state_directory)]
    state = Path(args.state_directory)
    if not any(state == Path(root) or Path(root) in state.parents for root in roots):
        raise work.DistributedTrainingError('state is outside resource ledger roots')
    return DaemonResourceReservation(ledger, roots=roots, storage_bytes=args.storage_bytes,
        memory_mb=8192 if args.mode == 'owner' else 1024,
        cpu_slots=1, timeout_seconds=0, ledger_lock_timeout_seconds=60)


def _feature_inputs(args):
    """Local paths are verified on each host, never put in the shared policy."""
    return {'manifest_path': args.feature_input_manifest,
        'training_path': args.input_jsonl if args.mode == 'owner' else args.feature_training_jsonl,
        'validation_path': args.validation_jsonl if args.mode == 'owner' else args.feature_validation_jsonl,
        'shared_targets': args.shared_targets, 'target_snapshot_id': args.target_snapshot_id,
        'target_shard_max_bytes': args.target_shard_max_bytes,
        'target_timeout_seconds': args.target_timeout_seconds}


def owner(args):
    from ipfs_datasets_py.huggingface.autoencoder_incremental_download import publish_seed_checkpoint
    state = args.state_directory
    configuration = state/'campaign.json'
    hashes = work.identity()
    validation = normalize(work.records_from_jsonl(args.validation_jsonl))
    if not 1 <= len(validation) <= 32:
        raise work.DistributedTrainingError('supply one to 32 disjoint tuning validation rows')
    validation_samples = [row['sample'] for row in validation]
    policy = {'source_identity': hashes, 'validation_samples': validation_samples,
        'max_training_rounds': args.max_training_rounds, 'max_seconds': args.max_seconds,
        'lake_timeout_seconds': args.lake_timeout_seconds, 'source_language': args.source_language,
        'model_variant': args.model_variant, 'cycle_timeout': args.cycle_timeout,
        'worker_storage_bytes': args.worker_storage_bytes, 'known_workers': sorted(args.worker_id)}
    feature = args.training_purpose == 'feature_pretraining'
    feature_inputs = None
    if feature:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_distributed_features as features
        feature_inputs = _feature_inputs(args)
        # Each host has verified tuning bytes. Keep the bounded control plane
        # portable by binding their digest instead of transporting all vectors.
        policy.pop('validation_samples')
        policy.update(features.build_feature_policy(feature_inputs,
            normalize(work.records_from_jsonl(args.input_jsonl)), validation))
        policy['feature_optimizer'] = {name: getattr(args, name) for name in (
            'epochs', 'learning_rate', 'line_search_attempts', 'projection_optimizer_mode',
            'projection_momentum', 'projection_candidate_update_order')}
    with _reserve(args) as resources, ExitStack() as stack:
        registry = stack.enter_context(AutoencoderRegistry(state/'weights.duckdb', state/'artifacts'))
        if configuration.exists():
            saved = work._read(configuration)
            if saved['policy'] != policy or saved['campaign_id'] != args.campaign_id:
                raise work.DistributedTrainingError('campaign source, worker set or policy changed; new campaign required')
        else:
            checkpoint = args.checkpoint.resolve()
            cli = work.local_cli()
            digest = cli._sha(checkpoint)
            if checkpoint == cli.PINNED.resolve() and digest != cli.PINNED_SHA:
                raise work.DistributedTrainingError('protected checkpoint hash changed')
            artifact = registry.stage_artifact(checkpoint, digest)
            if feature:
                from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_feature_exchange import publish_feature_checkpoint
                seed = work.retry_publication(lambda: publish_feature_checkpoint(checkpoint,
                    expected_artifact=artifact, generation=1, upload=True))
            else:
                seed = work.retry_publication(lambda: publish_seed_checkpoint(checkpoint, expected_artifact=artifact, upload=True))
            variant_id = 'span-campaign-' + hashlib.sha256(args.campaign_id.encode()).hexdigest()[:32]
            registry.register_variant('variant-'+variant_id, variant_id,
                {'source_language':args.source_language, 'target_formal_language':'typed_deontic_ir',
                 'jurisdiction':'us','model_variant':args.model_variant,'campaign_id':args.campaign_id,
                 **({'training_purpose': 'feature_pretraining'} if feature else {})})
            version = registry.register_version('seed-'+variant_id, variant_id, artifact)['version_id']
            saved = {'campaign_id':args.campaign_id, 'variant_id':variant_id, 'base_version_id':version,
                     'policy':policy, 'seed_weight_reference':{**seed['anchor_reference'],'kind':'anchor',
                                                             'materialized_checkpoint':artifact},
                     'seed_publication':seed}
            work._write(configuration, saved)
        campaign = AutoencoderSpanCampaign(registry, campaign_id=args.campaign_id,
            variant_id=saved['variant_id'],base_version_id=saved['base_version_id'], policy=policy,
            result_repository=work.REPOSITORY, seed_weight_reference=saved['seed_weight_reference'])
        validation_keys = {work.inc._sha(' '.join(row['text'].casefold().split())) for row in validation_samples}
        feed = None
        if args.repository_id:
            from ipfs_datasets_py.logic.autoformal.span_cache_feed import SpanCacheFeed
            feed = stack.enter_context(SpanCacheFeed(state/'feed.duckdb',state/'feed-artifacts',repository_id=args.repository_id))
        for worker_id in args.worker_id:
            gateway = stack.enter_context(SpanCampaignQuackGateway(campaign,worker_id))
            parameters = gateway.connection_parameters()
            token = state/'connections'/(worker_id+'.token')
            token.parent.mkdir(parents=True,exist_ok=True)
            with open(token, 'w', opener=lambda path, flags: os.open(path,flags,0o600)) as handle:
                handle.write(parameters['token']+'\n')
            os.chmod(token,0o600)
            work._write(token.with_suffix('.json'), {'worker_id':worker_id,'campaign_id':args.campaign_id,
                'endpoint':parameters['endpoint'],'token_file':str(token), 'transport':'native_quack_via_loopback_or_explicit_ssh_forward'})
        verifier = (features.owner_feature_verifier(registry, policy, state/'verification',
            feature_inputs=feature_inputs) if feature else work.owner_verifier(registry,policy,state/'verification'))
        advance = features.advance_feature_generation if feature else work.advance_verified_generation
        started = time.monotonic()
        iteration = 0
        stop = False
        def halt(*unused):
            nonlocal stop
            stop = True
        for sig in (signal.SIGTERM,signal.SIGINT):
            signal.signal(sig,halt)
        while not stop and (args.serve_seconds == 0 or time.monotonic()-started < args.serve_seconds):
            if work.identity() != hashes:
                raise work.DistributedTrainingError('owner producer changed while serving')
            records = normalize(work.records_from_jsonl(args.input_jsonl)) if args.input_jsonl else []
            if feature:
                # Bind every intake to the verified immutable corpus generation.
                # Growing the corpus requires a fresh verified campaign policy.
                features.validate_feature_inputs(policy, feature_inputs)
            feed_report = feed.poll_once(max_bundles=args.max_bundles) if feed else None
            if feed_report:
                records.extend(normalize(feed_report['records']))
            if any(work.inc._sha(' '.join(row['sample']['text'].casefold().split())) in validation_keys for row in records):
                raise work.DistributedTrainingError('campaign training/validation source overlap')
            for offset in range(0, len(records), 10_000):
                campaign.register_records(records[offset:offset+10_000])
            if feed:
                for bundle in feed_report['new_bundles']:
                    feed.acknowledge(bundle['manifest_in_repo'],fingerprint=bundle['fingerprint'])
            advanced = advance(campaign)
            verified = campaign.verify_reports(verifier,max_reports=1)
            advanced = advance(campaign) or advanced
            status = campaign.status()
            work._write(state/'status.json',status)
            work._write(state/'observations'/f'{iteration:08d}-{uuid.uuid4().hex}.json',
                {'status':status,'verified':verified,'advanced':advanced,'admitted':False})
            resources.check_usage(attempt_directory=state)
            _emit({'owner_iteration':iteration,'weights':status['weights'], 'counts':status['counts'],
                   'acknowledged_current_workers':status['acknowledged_current_workers'],
                   'verified_count':len(verified),'advanced':bool(advanced),'admitted':False})
            iteration += 1
            time.sleep(args.sync_interval)
        resources.release(artifacts_durable=True)


def worker(args):
    state = args.state_directory
    current_sources = work.identity()
    processed = 0
    stop = False
    def halt(*unused):
        nonlocal stop
        stop = True
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, halt)
    with _reserve(args) as resources, _connection(args.connection_file,args.token_file,args.endpoint) as transport:
        client = work.DurableCampaignClient(transport,state/'control-journal')
        for ordinal in range(args.polls) if args.polls else iter(int,1):
            if stop:
                break
            campaign = client.read('ReadCampaign')
            policy = campaign['policy']
            if current_sources != policy['source_identity'] or work.identity() != current_sources:
                raise work.DistributedTrainingError('worker and owner sources differ')
            purpose = policy.get('training_purpose', 'formalization')
            if purpose != args.training_purpose:
                raise work.DistributedTrainingError('worker training purpose differs from owner campaign')
            feature = purpose == 'feature_pretraining'
            feature_inputs = None
            if feature and not args.sync_only:
                from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_distributed_features as features
                feature_inputs = _feature_inputs(args)
                features.validate_feature_inputs(policy, feature_inputs)
            # Download/replay complete bytes before acknowledging this generation.
            installed = work.install_generation(campaign['weights'],state/'weights')
            weights = campaign['weights']
            try:
                client.request(['ack',campaign['binding_sha256'],weights['generation']], 'AcknowledgeWeights',
                    {key:weights[key] for key in ('generation','version_id','artifact')})
            except Exception:
                if client.read('ReadCampaign')['weights'] != weights:
                    continue  # The owner advanced during a download; synchronize again.
                raise
            pending_path = state/'pending.json'
            if not args.sync_only and (args.max_jobs == 0 or processed < args.max_jobs):
                pending = work._read(pending_path) if pending_path.exists() else {'slot':'claim-'+uuid.uuid4().hex}
                work._write(pending_path,pending)
                try:
                    claim = client.request(pending['slot'],'ClaimSpan',{'lease_seconds':args.lease_seconds})
                except Exception:
                    if client.read('ReadCampaign')['weights'] != weights:
                        continue  # Reuse the pending operation after acknowledging new weights.
                    raise
                if claim['status'] == 'claimed':
                    assignment = claim['assignment']
                    job = state/'jobs'/assignment['run_id']/('attempt-'+str(claim['lease']['attempt']))
                    job.mkdir(parents=True,exist_ok=True)
                    remote = client.read('ReadSpan',{'run_id':assignment['run_id']})
                    lease_identity = ('run_id','attempt','fence','owner_generation','worker_id')
                    if remote.get('lease_live') is not True or any((remote.get('lease') or {}).get(key) != claim['lease'][key] for key in lease_identity):
                        work._write(job/'expired.json',{'claim':claim,'observed':remote,'admitted':False})
                        pending_path.unlink()
                        continue
                    installed = work.install_generation(claim['weights'],state/'weights',advertise_current=False)
                    try:
                        with work.renewable_assignment(client,claim,job/'heartbeat.json',lease_seconds=args.lease_seconds) as heartbeat:
                            result_path = job/'result.json'
                            if result_path.exists():
                                result = work._read(result_path)
                            elif feature:
                                result = features.execute_feature_assignment(assignment, policy, installed, job,
                                    feature_inputs=feature_inputs, resource_ledger=args.resource_ledger)
                            else:
                                result = work.execute_assignment(assignment,policy,installed,job,
                                    resource_ledger=args.resource_ledger)
                    except work.CapacityDeferred:
                        resources.check_usage(attempt_directory=state)
                        work._write(state/'worker-status.json', {'generation': weights['generation'],
                            'artifact': weights['artifact'], 'full_weights_verified': True,
                            'processed_jobs_this_invocation': processed, 'deferred': True,
                            'reason': 'resource_capacity_unavailable', 'admitted': False})
                        if args.polls == 0 or ordinal+1 < args.polls:
                            time.sleep(args.sync_interval)
                        continue
                    submitted = client.request(['report',assignment['run_id'],claim['lease']['fence']], 'ReportSpan',
                        {'lease':heartbeat['lease'],'report_descriptor':result['report_reference']})
                    work._write(job/'submitted.json',submitted)
                    processed += 1
                    _emit({'worker_id':assignment['worker_id'],'run_id':assignment['run_id'],
                           'generation':claim['weights']['generation'],
                           'disposition':result['feature_disposition'] if feature else result['qualification_disposition'],
                           'report_reference':result['report_reference'],'admitted':False})
                pending_path.unlink(missing_ok=True)
            resources.check_usage(attempt_directory=state)
            work._write(state/'worker-status.json',{'generation':weights['generation'],'artifact':weights['artifact'],
                'full_weights_verified':True,'processed_jobs_this_invocation':processed,'admitted':False})
            if not stop and (args.polls == 0 or ordinal+1 < args.polls):
                time.sleep(args.sync_interval)
        resources.release(artifacts_durable=True)


def parser():
    cli = work.local_cli()
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode',required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--state-directory',type=Path,required=True)
    common.add_argument('--sync-interval',type=float,default=30)
    common.add_argument('--training-purpose', choices=['formalization', 'feature_pretraining'], default='formalization')
    common.add_argument('--feature-input-manifest', type=Path)
    common.add_argument('--shared-targets', type=Path)
    common.add_argument('--target-snapshot-id')
    common.add_argument('--target-shard-max-bytes', type=int, default=64*1024*1024)
    common.add_argument('--target-timeout-seconds', type=float, default=60)
    owner_p = sub.add_parser('owner',parents=[common])
    owner_p.add_argument('--campaign-id',required=True)
    owner_p.add_argument('--worker-id',action='append',required=True)
    owner_p.add_argument('--checkpoint',type=Path,default=cli.PINNED)
    owner_p.add_argument('--input-jsonl',type=Path)
    owner_p.add_argument('--repository-id',choices=[work.REPOSITORY])
    owner_p.add_argument('--validation-jsonl',type=Path,required=True)
    owner_p.add_argument('--serve-seconds',type=float,default=600,help='0 serves until interrupted')
    owner_p.add_argument('--max-bundles',type=int,default=4)
    owner_p.add_argument('--max-training-rounds',type=int,default=3)
    owner_p.add_argument('--max-seconds',type=float,default=120)
    owner_p.add_argument('--lake-timeout-seconds',type=int,default=120)
    owner_p.add_argument('--cycle-timeout',type=float,default=900)
    owner_p.add_argument('--source-language',default='en')
    owner_p.add_argument('--model-variant',default='incremental-modal')
    owner_p.add_argument('--storage-bytes',type=int,default=1_500_000_000)
    owner_p.add_argument('--worker-storage-bytes',type=int,default=750_000_000)
    owner_p.add_argument('--resource-ledger',type=Path,default=cli.DEFAULT_LEDGER)
    owner_p.add_argument('--epochs', type=int, default=3)
    owner_p.add_argument('--learning-rate', type=float, default=0.35)
    owner_p.add_argument('--line-search-attempts', type=int, default=2)
    owner_p.add_argument('--projection-optimizer-mode', choices=['fixed', 'productive_adaptive'], default='productive_adaptive')
    owner_p.add_argument('--projection-momentum', type=float, default=0.25)
    owner_p.add_argument('--projection-candidate-update-order', choices=['decoded_embedding_structural'], default='decoded_embedding_structural')
    worker_p = sub.add_parser('worker',parents=[common])
    worker_p.add_argument('--connection-file',type=Path,required=True)
    worker_p.add_argument('--token-file',type=Path)
    worker_p.add_argument('--endpoint',help='Explicit loopback endpoint of an authenticated SSH forward')
    worker_p.add_argument('--polls',type=int,default=1,help='0 polls until interrupted')
    worker_p.add_argument('--max-jobs',type=int,default=1,help='0 processes until the poll bound')
    worker_p.add_argument('--lease-seconds',type=float,default=300)
    worker_p.add_argument('--sync-only',action='store_true')
    worker_p.add_argument('--feature-training-jsonl', type=Path)
    worker_p.add_argument('--feature-validation-jsonl', type=Path)
    worker_p.add_argument('--storage-bytes',type=int,default=1_500_000_000)
    worker_p.add_argument('--resource-ledger',type=Path,default=cli.DEFAULT_LEDGER)
    return p


def main(argv=None):
    import math,re
    p = parser(); args = p.parse_args(argv)
    feature = args.training_purpose == 'feature_pretraining'
    if not math.isfinite(args.target_timeout_seconds) or not 0 < args.target_timeout_seconds <= 600 or not 1 <= args.target_shard_max_bytes <= 256*1024*1024:
        p.error('invalid bounded shared target timeout or shard size')
    if feature and not (args.mode == 'worker' and args.sync_only):
        if not all(_feature_inputs(args).values()):
            p.error('feature training requires a verified local input manifest, training/tuning rows and shared targets on each host')
        if args.mode == 'owner' and args.repository_id:
            p.error('feature campaigns require verified local inputs; unverified span feed intake is disabled')
    elif not feature and any((args.feature_input_manifest, args.shared_targets, args.target_snapshot_id,
                             getattr(args, 'feature_training_jsonl', None), getattr(args, 'feature_validation_jsonl', None))):
        p.error('feature input options require feature_pretraining purpose')
    if not math.isfinite(args.sync_interval) or not 0 < args.sync_interval <= 3600:
        p.error('sync interval must be finite and in (0,3600]')
    args.state_directory = args.state_directory.absolute()
    args.state_directory.mkdir(parents=True,exist_ok=True)
    if args.mode == 'owner':
        if (not 1 <= args.epochs <= 100 or not 1 <= args.line_search_attempts <= 32
                or not math.isfinite(args.learning_rate) or not 0 < args.learning_rate <= 1
                or not math.isfinite(args.projection_momentum) or not 0 <= args.projection_momentum < 1):
            p.error('invalid bounded feature optimizer settings')
        if feature:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingConfig
            try:
                TrainingConfig(epochs=args.epochs, learning_rate=args.learning_rate,
                    max_seconds=args.max_seconds, max_line_search_attempts=args.line_search_attempts,
                    projection_optimizer_mode=args.projection_optimizer_mode,
                    projection_momentum=args.projection_momentum,
                    projection_candidate_update_order=[args.projection_candidate_update_order],
                    projection_reconstruction_objective='raw_decoder')
            except ValueError as exc:
                p.error(str(exc))
        if not args.input_jsonl and not args.repository_id:
            p.error('owner requires local input and/or the campaign dataset')
        if len(args.worker_id) != len(set(args.worker_id)) or not 1 <= len(args.worker_id) <= 32 or any(
                re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',value) is None for value in args.worker_id):
            p.error('one to 32 unique safe worker IDs required')
        if not 1 <= args.max_training_rounds <= 100 or not 1 <= args.lake_timeout_seconds <= 600 or not 1 <= args.max_bundles <= 128:
            p.error('invalid bounded training or intake count')
        if not math.isfinite(args.max_seconds) or not 0 < args.max_seconds <= 300 or not math.isfinite(args.serve_seconds) or args.serve_seconds < 0:
            p.error('invalid finite training/server time bound')
        if not math.isfinite(args.cycle_timeout) or not 0 < args.cycle_timeout <= 7200:
            p.error('cycle timeout must be finite and in (0,7200]')
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',args.campaign_id) is None or re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*',args.source_language) is None or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',args.model_variant) is None:
            p.error('safe campaign/model identifiers and language tag required')
        if not 1 <= args.storage_bytes <= 50_000_000_000 or not 1 <= args.worker_storage_bytes <= 50_000_000_000:
            p.error('storage allowance must be at most 50 GB per process')
    elif not 1 <= args.storage_bytes <= 50_000_000_000 or args.polls < 0 or args.max_jobs < 0 or not math.isfinite(args.lease_seconds) or not 120 <= args.lease_seconds <= 86400:
        p.error('invalid worker polling or lease bound')
    with (args.state_directory/'distributed.lock').open('a+') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        owner(args) if args.mode == 'owner' else worker(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
