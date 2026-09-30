"""Portable campaign workers around the existing qualified training runner.

The campaign owner publishes an immutable complete-weight generation. Workers
reconstruct and hash that generation before acknowledging it, train private
candidates, and send immutable report references through Quack. Download or
transport never supplies qualification authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import threading
import time
import uuid

from . import autoencoder_incremental_training as inc
from .autoencoder_training_worker import SampleRecord

ROOT = Path(__file__).resolve().parents[3]
REPOSITORY = 'justicedao/uscode-autoformal-span-cache'
SCHEMA = 'autoencoder-distributed-worker/v1'


class DistributedTrainingError(ValueError):
    pass


class CapacityDeferred(DistributedTrainingError):
    """A resource estimate declined work; no optimizer attempt was committed."""


def local_cli():
    path = ROOT / 'scripts/ops/legal_ir/run_incremental_autoencoders.py'
    spec = importlib.util.spec_from_file_location('_qualified_campaign_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity():
    """Code identities are portable across checkout locations, never across trees."""
    cli = local_cli()
    hashes = {'native:' + key: value for key, value in cli._pin(dataset_network=True).items()}
    for key, value in cli.orchestration_hashes().items():
        normalized = 'JevOps/jevops/statement_lock.py' if key.endswith('/JevOps/jevops/statement_lock.py') else key
        hashes[normalized] = value
    paths = ['ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_distributed_training.py',
             'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_distributed_features.py',
             'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_feature_exchange.py',
             'ipfs_datasets_py/duckdb_control/autoencoder_span_campaign.py',
             'ipfs_datasets_py/huggingface/autoencoder_incremental_download.py',
             'ipfs_datasets_py/huggingface/autoencoder_span_attempts.py',
             'scripts/ops/legal_ir/run_distributed_autoencoders.py']
    for relative in paths:
        hashes[relative] = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    return hashes


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    inc._write(path, value)


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise DistributedTrainingError('invalid bounded local campaign record')
    return json.loads(path.read_bytes())


def verify_complete_checkpoint(path, artifact):
    """Check complete bytes before changing the worker's installed generation."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size != artifact['bytes']:
        raise DistributedTrainingError('complete checkpoint size differs')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != artifact['sha256']:
        raise DistributedTrainingError('complete checkpoint hash differs')
    return path


def install_generation(generation, directory, *, downloader=None, advertise_current=True, anchor_resolver=None):
    """Retain old generations; atomically advertise only a fully replayed one."""
    from ...huggingface import autoencoder_incremental_download as downloads
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / str(generation['generation'])
    target.mkdir(exist_ok=True)
    binding = {key: generation[key] for key in ('generation', 'version_id', 'artifact', 'weight_reference')}
    record_path = target / 'installed.json'
    if record_path.exists():
        saved = _read(record_path)
        if saved['binding'] != binding:
            raise DistributedTrainingError('immutable installed generation changed')
        verify_complete_checkpoint(saved['checkpoint_path'], binding['artifact'])
        if advertise_current:
            _write(directory / 'current.json', saved)
        return {**saved, 'downloaded_bytes': 0, 'cache_hit': True}
    reference = binding['weight_reference']
    if downloader is not None:
        result = downloader(reference, target)
    elif reference['kind'] == 'anchor':
        result = downloads.download_seed_checkpoint({key: reference[key] for key in ('repository_id','commit_sha','path_in_repo','sha256','bytes')}, target)
    elif reference['kind'] in {'sparse', 'feature_sparse'}:
        def local_anchor(expected):
            # Reuse a previously verified complete generation. Numerical work
            # stays local; ordinary updates need only the new sparse closure.
            receipts = [directory / 'current.json', *directory.glob('*/installed.json')]
            for receipt_path in receipts:
                if not receipt_path.exists():
                    continue
                known = _read(receipt_path)
                if known.get('materialized_checkpoint') == expected:
                    return verify_complete_checkpoint(known['checkpoint_path'], expected)
            if anchor_resolver is not None:
                supplied = anchor_resolver(expected)
                if supplied is not None:
                    return verify_complete_checkpoint(supplied, expected)
            return None
        if reference['kind'] == 'feature_sparse':
            from .autoencoder_feature_exchange import download_feature_update
            result = download_feature_update(reference, target, local_parent_resolver=local_anchor)
        else:
            result = downloads.download_sparse_update(reference['repository_id'], reference['commit_sha'],
                reference['path_in_repo'], reference['sha256'], target,
                anchor_reference=reference['anchor_reference'], local_anchor_resolver=local_anchor)
    else:
        raise DistributedTrainingError('unsupported canonical weight transport')
    path = verify_complete_checkpoint(result['materialized_checkpoint_path'], binding['artifact'])
    saved = {'schema': SCHEMA, 'binding': binding, 'checkpoint_path': str(path.resolve()),
             'materialized_checkpoint': binding['artifact'], 'full_weights_verified': True,
             'download_receipt': result, 'admitted': False, 'formalized': False}
    _write(record_path, saved)
    if advertise_current:
        _write(directory / 'current.json', saved)
    return saved


def records_from_jsonl(path):
    """Explicit source IDs support revisions; bare samples remain content-addressed."""
    cli = local_cli()
    path = Path(path)
    if path.stat().st_size > cli.MAX_INPUT_BYTES or path.is_symlink():
        raise DistributedTrainingError('source input exceeds local bound')
    records = []
    for ordinal, line in enumerate(path.read_bytes().splitlines()):
        if ordinal >= cli.MAX_INPUT_ROWS:
            raise DistributedTrainingError('source input exceeds row bound')
        if not line.strip():
            continue
        supplied = json.loads(line)
        sample = json.loads(inc._raw(asdict(SampleRecord.from_dict(supplied.get('sample', supplied)))))
        source_id = supplied.get('source_span_id') if 'sample' in supplied else None
        source_id = source_id or 'local-content:' + inc._sha(sample)
        revision = inc._sha({'source_span_id': source_id, 'sample': sample})
        record = {'record_id': revision, 'source_span_id': source_id, 'sample': sample,
                  'provenance': {'kind': 'explicit_local_source' if 'sample' in supplied else 'local_content',
                                 'source_text_sha256': hashlib.sha256(sample['text'].encode()).hexdigest()}}
        for key in ('legal_id', 'document_id'):
            if key in supplied:
                if not isinstance(supplied[key], str) or not supplied[key].strip() or len(supplied[key]) > 2048:
                    raise DistributedTrainingError('source ' + key + ' must be a bounded nonempty string')
                record[key] = supplied[key]
        citation = sample.get('citation')
        if ('legal_id' not in record and isinstance(citation, str)
                and re.fullmatch(r'usc:(?:us:)?[0-9]+:[^\s:]+', citation)):
            record['legal_id'] = citation
        records.append(record)
    return records


def training_config(policy, directory, checkpoint):
    cli = local_cli()
    directory = Path(directory).resolve()
    return {'state_directory': str(directory), 'checkpoint': str(Path(checkpoint).resolve()),
        'input_jsonl': str(directory / 'source.jsonl'), 'validation_jsonl': str(directory / 'validation.jsonl'),
        'repository_id': None, 'publish_repository': REPOSITORY, 'revision': 'main',
        'workers': 1, 'shard_count': 1, 'shard_index': 0,
        'max_batches': policy['max_training_rounds'], 'max_training_rounds': policy['max_training_rounds'],
        'lake_timeout_seconds': policy['lake_timeout_seconds'], 'max_bundles': 1,
        'max_seconds': policy['max_seconds'], 'source_language': policy['source_language'],
        'model_variant': policy['model_variant'], 'memory_mb': policy.get('memory_mb', 8192),
        'storage_bytes': policy.get('worker_storage_bytes', 750_000_000),
        'resource_ledger': str(cli.DEFAULT_LEDGER), 'resource_roots': [],
        'cycle_timeout': policy.get('cycle_timeout', 900), 'polls': 1, 'sync_interval': 1,
        'arrow_feature_weights': None, 'shared_targets': None, 'target_snapshot_id': None}


def retry_publication(call, *, attempts=3):
    for number in range(attempts):
        try:
            return call()
        except Exception as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status not in {409,412,429,500,502,503,504} or number+1 == attempts:
                raise
            time.sleep(.25 * (number+1))


def execute_assignment(assignment, policy, installed, directory, *, execute_cycle=None, resource_ledger=None):
    """Bounded native training, source repair evidence, and exact Hub publication."""
    from ...duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ...huggingface.autoencoder_span_attempts import stage_span_attempt, publish_span_attempt
    if identity() != policy['source_identity']:
        raise DistributedTrainingError('worker source differs from campaign policy')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    source = assignment['record']['sample']
    for name, values in [('source.jsonl', [source]), ('validation.jsonl', policy['validation_samples'])]:
        path = directory / name
        raw = b''.join(inc._raw(value) + b'\n' for value in values)
        if path.exists() and path.read_bytes() != raw:
            raise DistributedTrainingError('immutable worker source/validation changed')
        if not path.exists():
            path.write_bytes(raw)
    state = directory / 'training-result.json'
    config = training_config(policy, directory, installed['checkpoint_path'])
    if resource_ledger is not None:
        config['resource_ledger'] = str(Path(resource_ledger).resolve())
    if state.exists():
        result = _read(state)
    else:
        result = (execute_cycle or local_cli().supervised_cycle)(config)
        if result.get('deferred'):
            raise CapacityDeferred('training capacity is currently unavailable')
    cycle = _read(result['receipt'])
    completed = cycle['training']['completed']
    if not completed and cycle['training'].get('capacity_deferred'):
        raise CapacityDeferred('training dispatch capacity is currently unavailable')
    if len(cycle['training']['batch_status_counts']) != 1 or not completed:
        raise DistributedTrainingError('assignment did not produce exactly one span disposition')
    attempt = max(completed, key=lambda row: row['round'])
    disposition = attempt['qualification_status']
    if disposition == 'pending' and cycle['training'].get('capacity_deferred'):
        raise CapacityDeferred('metric retry is waiting for training capacity')
    if disposition not in {'qualified', 'needs_repair', 'training_exhausted'}:
        raise DistributedTrainingError('unfinished local training requires another bounded cycle')
    if not state.exists():
        _write(state, result)
    if identity() != policy['source_identity']:
        raise DistributedTrainingError('worker producer changed before publishing result')
    weight_reference = None
    if disposition == 'qualified':
        delivery_path = directory / 'weight-delivery.json'
        found = [row for row in cycle['weight_publications']
                 if row.get('version_id') == attempt['optimizer']['candidate_version_id'] and row.get('acknowledged')]
        if delivery_path.exists():
            found = [_read(delivery_path)]
        deferred = attempt.get('publication') or {}
        full_candidate = (deferred.get('status') == 'deferred' and deferred.get('reason') ==
                          'incremental publication requires a sparse candidate, never a full checkpoint')
        if not found and not full_candidate:
            retried = (execute_cycle or local_cli().supervised_cycle)(config)
            if retried.get('deferred'):
                raise CapacityDeferred('publication replay capacity is currently unavailable')
            retry_cycle = _read(retried['receipt'])
            found = [row for row in retry_cycle['weight_publications']
                     if row.get('version_id') == attempt['optimizer']['candidate_version_id'] and row.get('acknowledged')]
            if len(found) != 1:
                raise DistributedTrainingError('qualified weight upload remains pending')
        from ...huggingface.autoencoder_incremental_download import publish_seed_checkpoint
        if full_candidate:
            # The existing sparse policy sometimes compacts a candidate. Its
            # complete snapshot may transfer only with the exact native passed
            # qualification; it is never relabeled as a sparse upload.
            with AutoencoderRegistry(directory/'control.duckdb', directory/'artifacts') as owner:
                version = owner.get_version(attempt['optimizer']['candidate_version_id'])
                anchor = retry_publication(lambda: publish_seed_checkpoint(owner.artifact_path(version['artifact']),
                    expected_artifact=version['artifact'], upload=True))
            weight_reference = {**anchor['anchor_reference'], 'kind': 'anchor',
                                'materialized_checkpoint': version['artifact']}
        else:
            _write(delivery_path, found[0])
            manifests = list((directory/'progress/weight-publications'/attempt['run_id']).glob('update-*.json'))
            if len(manifests) != 1:
                raise DistributedTrainingError('qualified sparse manifest is ambiguous')
            manifest = _read(manifests[0])
            parent = installed['binding']['weight_reference']
            depth, cursor = 0, parent
            while cursor.get('kind') == 'sparse':
                depth += 1
                cursor = cursor['anchor_reference']
            if depth >= 7:
                # Bounded periodic compaction; ordinary generations upload only
                # their sparse update and reconstruct their parent on demand.
                anchor = retry_publication(lambda: publish_seed_checkpoint(installed['checkpoint_path'],
                    expected_artifact=manifest['anchor_checkpoint'], upload=True))
                parent = {**anchor['anchor_reference'], 'kind': 'anchor',
                          'materialized_checkpoint': manifest['anchor_checkpoint']}
            if manifest['anchor_checkpoint'] != installed['binding']['artifact']:
                raise DistributedTrainingError('sparse update does not descend from assigned complete weights')
            weight_reference = {'kind': 'sparse', 'repository_id': REPOSITORY,
                'commit_sha': found[0]['commit_sha'], 'path_in_repo': manifest['path_in_repo'],
                **found[0]['manifest_artifact'], 'materialized_checkpoint': manifest['materialized_checkpoint'],
                'anchor_reference': parent}
    with AutoencoderRegistry(directory/'control.duckdb', directory/'artifacts') as registry:
        ref = {key: attempt['qualification_artifact'][key] for key in ('sha256','bytes')}
        qualification = json.loads(registry.artifact_path(ref).read_bytes())
        row = next(row for row in qualification['rows'] if row['split'] == 'training')
        staged = stage_span_attempt(registry, attempt['optimizer']['candidate_version_id'], ref,
            directory/'span-publication', work_id=assignment['run_id'],
            span_revision=assignment['record']['record_id'], sample_id=row['sample_id'],
            source_provenance={'source_record': assignment['record'],
                'source_observation': assignment.get('source_observation'),
                'canonical_generation': installed['binding']['generation'],
                'canonical_version_id': installed['binding']['version_id'],
                'canonical_artifact': installed['binding']['artifact'], 'source_identity': policy['source_identity']},
            disposition=disposition, attempt_index=attempt['round'],
            agent_id=assignment['worker_id'], weight_publication=weight_reference)
    publication = retry_publication(lambda: publish_span_attempt(staged['report_path'], upload=True))
    result = {'schema': SCHEMA, 'assignment': assignment, 'qualification_disposition': disposition,
              'report_reference': publication['report_reference'], 'weight_reference': weight_reference,
              'local_training_receipt': result['receipt'], 'admitted': False, 'formalized': False}
    _write(directory/'result.json', result)
    return result


def owner_verifier(registry, policy, directory):
    """Independently qualify downloaded candidates before canonical selection."""
    from ...huggingface.autoencoder_span_attempts import download_span_attempt_report
    from .autoencoder_candidate_qualification import qualify_candidate
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    def verify(assignment, descriptor):
        if identity() != policy['source_identity']:
            raise DistributedTrainingError('owner source differs from campaign policy')
        root = directory / descriptor['sha256']
        root.mkdir(exist_ok=True)
        report = download_span_attempt_report(descriptor, root/'report')['report']
        provenance = report['source_provenance']
        base = registry.get_version(assignment['base_version_id'])
        if (report['work_id'] != assignment['run_id'] or report['span_revision'] != assignment['record']['record_id']
                or provenance['source_record'] != assignment['record']
                or provenance.get('source_observation') != assignment.get('source_observation')
                or provenance['canonical_generation'] != assignment['generation']
                or provenance['canonical_version_id'] != assignment['base_version_id']
                or provenance['canonical_artifact'] != base['artifact']
                or provenance.get('source_identity') != policy['source_identity']):
            raise DistributedTrainingError('remote report differs from exact assigned source, code or weights')
        receipt = report['qualification']
        training = [row['source'] for row in receipt['rows'] if row['split'] == 'training']
        validation = [row['source'] for row in receipt['rows'] if row['split'] == 'heldout']
        if training != [assignment['record']['sample']] or validation != policy['validation_samples']:
            raise DistributedTrainingError('remote qualification changed the assigned sample set')
        _remote_qualification_binding(receipt, policy, training)
        result = {'admitted': False, 'formalized': False, 'owner_verified': True,
                  'qualified': False, 'span_disposition': report['disposition'],
                  'report_artifact': {key: descriptor[key] for key in ('sha256','bytes')},
                  'weight_reference': report['weight_publication'],
                  'verification_scope': 'source-bound failure evidence; no independent failed-model metric measurement'}
        if report['disposition'] != 'qualified':
            return {'artifact': base['artifact'], 'result': result}
        reference = report['weight_publication']
        installed = install_generation({'generation': assignment['generation'] + 1,
            'version_id': report['candidate_version_id'], 'artifact': receipt['materialized_checkpoint'],
            'weight_reference': reference}, root/'candidate',
            anchor_resolver=lambda expected: (registry.artifact_path(expected)
                if registry.artifact_path(expected).is_file() else None))
        artifact = registry.stage_artifact(installed['checkpoint_path'], receipt['materialized_checkpoint']['sha256'])
        # This provisional registered snapshot has no qualification authority.
        # Its exact bytes are evaluated independently on this owner's machine.
        provisional = registry.register_version('span-snapshot-' + descriptor['sha256'], assignment['variant_id'],
            artifact, metadata={'scope':'downloaded_snapshot_pending_qualification','remote_report':descriptor},
            parent_version_id=assignment['base_version_id'])['version_id']
        qualification_file = root/'owner-qualification'/'qualification.json'
        needs_qualification = not qualification_file.exists()
        if qualification_file.exists():
            try:
                qualified = _read(qualification_file)
            except json.JSONDecodeError:
                # Exclusive qualification output can be interrupted mid-write.
                # Keep the original bytes but never interpret them as evidence.
                needs_qualification = True
            else:
                if (not isinstance(qualified, dict) or qualified.get('candidate_version_id') != provisional
                        or qualified.get('candidate_artifact') != artifact):
                    raise DistributedTrainingError('retained owner qualification differs from downloaded candidate')
        if needs_qualification:
            incomplete = qualification_file.parent
            if incomplete.exists() or incomplete.is_symlink():
                if incomplete.is_symlink() or not incomplete.is_dir():
                    raise DistributedTrainingError('unfinished owner qualification is not an owned directory')
                # No final receipt grants authority to this interrupted attempt.
                # Preserve every partial artifact, then use the original path
                # for a fresh exclusive qualifier invocation. Decodable but
                # altered retained receipts take the strict branch above.
                quarantine = root / ('owner-qualification-incomplete-' + uuid.uuid4().hex)
                incomplete.rename(quarantine)
                descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            qualified = qualify_candidate({**artifact,'path':str(registry.artifact_path(artifact))}, provisional,
                training, root/'owner-qualification', model_config={'compute_device':'python'},
                heldout_samples=policy['validation_samples'], lake_timeout_seconds=policy['lake_timeout_seconds'])
            qualified = _read(qualification_file)
        if identity() != policy['source_identity']:
            raise DistributedTrainingError('owner producer changed during qualification')
        # Validate retained evidence as strictly as a fresh gate result. The
        # comparison binds full bytes and the exact samples/code/model policy.
        from ...huggingface.autoencoder_span_attempts import _receipt as validate_receipt
        validate_receipt(qualified, provisional, artifact)
        expected_samples = inc._sha({'training': training, 'heldout': policy['validation_samples']})
        if qualified['sample_set_sha256'] != expected_samples or qualified['requested_model_config'] != {'compute_device':'python'}:
            raise DistributedTrainingError('owner qualification sample/model binding differs')
        if qualified['qualified']:
            from ...huggingface.autoencoder_incremental import _qualified, _proofs
            _qualified(qualified, registry.get_version(provisional))
            _proofs(qualified, read_local=True)
        _owner_producer_binding(qualified, policy)
        proof = registry.stage_artifact(qualification_file)
        result.update(qualified=qualified['qualified'],
            span_disposition='qualified' if qualified['qualified'] else 'needs_repair',
            owner_qualification_artifact=proof, qualification_version_id=provisional,
            verification_scope='exact complete snapshot independently qualified on owner',
            qualification_scope=qualified['qualification_scope'])
        return {'artifact': artifact, 'result': result}
    return verify


def _remote_producer_paths():
    from .autoencoder_candidate_qualification import QUALIFICATION_DEPENDENCIES
    paths = {
        'compiler': 'ipfs_datasets_py/logic/legal_ir/canonical_compiler.py',
        'decompiler': 'ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py',
        'parser': 'ipfs_datasets_py/logic/deontic/utils/deontic_parser.py',
        'autoencoder': 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py',
        'samples': 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_samples.py',
        'qualification': 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_candidate_qualification.py',
        'autoformal': 'ipfs_datasets_py/logic/autoformal/__init__.py',
        'family_syntax': 'ipfs_datasets_py/logic/autoformal/family_qualification.py',
        'statement_lock': 'JevOps/jevops/statement_lock.py',
    }
    paths.update({'dependency:' + relative: 'ipfs_datasets_py/' + relative for relative in QUALIFICATION_DEPENDENCIES})
    return paths


def _remote_qualification_binding(receipt, policy, training):
    """Bind all remote dispositions to the campaign without reading remote paths."""
    expected_paths = _remote_producer_paths()
    paths, hashes = receipt.get('source_files'), receipt.get('source_sha256')
    if (type(paths) is not dict or type(hashes) is not dict
            or set(paths) != set(expected_paths) or set(hashes) != set(expected_paths)):
        raise DistributedTrainingError('remote qualification producer roles differ from campaign')
    native_roles = {'compiler', 'decompiler', 'parser', 'autoencoder', 'samples'}
    package_root = None
    for role, relative in expected_paths.items():
        source = paths[role]
        if not isinstance(source, str) or '\\' in source:
            raise DistributedTrainingError('remote qualification source path is invalid')
        path, suffix = PurePosixPath(source), PurePosixPath(relative)
        if (not path.is_absolute() or '..' in path.parts
                or path.parts[-len(suffix.parts):] != suffix.parts):
            raise DistributedTrainingError('remote qualification source path differs from canonical suffix')
        if role != 'statement_lock':
            root = PurePosixPath(*path.parts[:-len(suffix.parts)])
            if package_root is None:
                package_root = root
            elif root != package_root:
                raise DistributedTrainingError('remote qualification producers use different package trees')
        key = 'native:' + role if role in native_roles else relative
        expected = policy['source_identity'].get(key)
        if (not isinstance(expected, str) or len(expected) != 64
                or hashes[role] != expected):
            raise DistributedTrainingError('remote qualification producer hash differs from campaign')
    if (package_root is None or len(package_root.parents) < 2
            or PurePosixPath(paths['statement_lock']) != package_root.parents[1] / expected_paths['statement_lock']):
        raise DistributedTrainingError('remote statement lock is outside the canonical sibling checkout')
    expected_samples = inc._sha({'training': training, 'heldout': policy['validation_samples']})
    if receipt.get('sample_set_sha256') != expected_samples:
        raise DistributedTrainingError('remote qualification sample-set identity differs from campaign')
    if receipt.get('requested_model_config') != {'compute_device': 'python'}:
        raise DistributedTrainingError('remote qualification model configuration differs from campaign')


def _owner_producer_binding(receipt, policy):
    paths, hashes = receipt.get('source_files', {}), receipt.get('source_sha256', {})
    if not paths or set(paths) != set(hashes):
        raise DistributedTrainingError('owner qualification producer evidence is incomplete')
    for name, source in paths.items():
        path = Path(source).resolve()
        if ROOT in path.parents:
            relative = str(path.relative_to(ROOT))
            expected = policy['source_identity'].get(relative, policy['source_identity'].get('native:' + name))
        elif path == ROOT.parents[1] / 'JevOps/jevops/statement_lock.py':
            expected = policy['source_identity'].get('JevOps/jevops/statement_lock.py')
        else:
            raise DistributedTrainingError('owner qualification producer is outside pinned workspace')
        if expected != hashes[name] or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise DistributedTrainingError('owner qualification producer differs from campaign')


def advance_verified_generation(campaign):
    """Recover a crash after completion and before canonical generation CAS."""
    current = campaign.status()['weights']
    registry = campaign.registry
    with registry._transaction() as cx:
        rows = cx.execute("SELECT run_id FROM autoencoder_control.runs WHERE status='completed' "
            "AND base_version_id=? AND json_extract_string(spec,'$.campaign_id')=? "
            "AND json_extract_string(spec,'$.kind')='generation_attempt' "
            "AND json_extract_string(result,'$.span_disposition')='qualified' ORDER BY run_id",
            [current['version_id'], campaign.campaign_id]).fetchall()
    if not rows:
        return None
    completed = registry.get_run_completion(rows[0][0])
    result = completed['run']['result']
    candidate = completed['candidate_version']
    proof = result.get('owner_qualification_artifact')
    if not proof:
        raise DistributedTrainingError('canonical selection lacks owner qualification artifact')
    registry.verify_artifact(proof)
    qualification = json.loads(registry.artifact_path(proof).read_bytes())
    from ...huggingface.autoencoder_span_attempts import _receipt as validate_receipt
    validate_receipt(qualification, result['qualification_version_id'], candidate['artifact'])
    required = {'metric_gate','semantic_gate','family_syntax_gate','family_coverage_gate','lake_gate','heldout_gate'}
    if (qualification.get('qualified') is not True or qualification['candidate_artifact'] != candidate['artifact']
            or qualification['candidate_version_id'] != result['qualification_version_id']
            or set(qualification.get('gate_results', {})) != required
            or any(qualification['gate_results'][name].get('passed') is not True for name in required)):
        raise DistributedTrainingError('canonical selection differs from exact owner gate evidence')
    _owner_producer_binding(qualification, campaign.binding['policy'])
    from ...huggingface.autoencoder_incremental import _qualified, _proofs
    _qualified(qualification, registry.get_version(result['qualification_version_id']))
    _proofs(qualification, read_local=True)
    return campaign.advance_generation('select-' + candidate['version_id'], candidate['version_id'],
        expected_generation=current['generation'], expected_version_id=current['version_id'],
        weight_reference=result['weight_reference'])


class DurableCampaignClient:
    """Persist exact control commands before network calls and reuse them on retry."""
    def __init__(self, client, directory):
        self.client, self.directory = client, Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def request(self, slot, command, payload):
        with self.lock:
            path = self.directory / (inc._sha(slot) + '.json')
            if path.exists():
                item = _read(path)
                if item['command'] != command or item['payload'] != payload:
                    raise DistributedTrainingError('durable control slot changed')
                if 'receipt' in item:
                    return item['receipt']
            else:
                item = {'operation_id':uuid.uuid4().hex,'command':command,'payload':payload}
                _write(path, item)
            result = self.client.request(command, payload, item['operation_id'], timeout=30)
            _write(path, {**item, 'receipt':result})
            return result

    def read(self, command, payload=None):
        with self.lock:
            return self.client.request(command, payload or {}, uuid.uuid4().hex, timeout=30)


@contextmanager
def renewable_assignment(client, claim, path, *, lease_seconds=300):
    """Persist every renewal and stop result submission if its fence is lost."""
    path = Path(path)
    saved = _read(path) if path.exists() else {'lease':claim['lease'], 'renewal':0}
    if saved['lease']['run_id'] != claim['lease']['run_id'] or saved['lease']['fence'] != claim['lease']['fence']:
        raise DistributedTrainingError('local heartbeat belongs to a different assignment')
    _write(path, saved)
    stop = threading.Event()
    errors = []
    guard = threading.RLock()
    def renew_once():
        with guard:
            slot = ['renew',saved['lease']['run_id'],saved['lease']['fence'],saved['renewal']+1]
            result = client.request(slot,'RenewSpan',{'lease':saved['lease'],'lease_seconds':lease_seconds})
            saved.update(lease=result['lease'],renewal=saved['renewal']+1)
            _write(path,saved)
    # Replays a remotely committed renewal whose reply/local heartbeat write
    # was interrupted. A cached result may be submitted immediately, before
    # the periodic timer would otherwise run, so refresh before yielding.
    renew_once()
    def renew():
        while not stop.wait(min(30, lease_seconds / 4)):
            try:
                renew_once()
            except Exception as exc:
                errors.append(type(exc).__name__)
                stop.set()
    thread = threading.Thread(target=renew,daemon=True)
    thread.start()
    try:
        yield saved
    finally:
        stop.set()
        thread.join(timeout=35)
        if thread.is_alive() or errors:
            raise DistributedTrainingError('assignment lease renewal failed; candidate remains private')
