"""Verified private feature candidates on the fenced distributed campaign owner.

Local embedding receipts and shared targets are provisioned on every host.
Only immutable weights and feature reports travel through the dataset exchange.
Neither transport nor feature improvement provides legal qualification.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from . import autoencoder_distributed_training as work
from . import autoencoder_incremental_training as inc
from .autoencoder_training_worker import BRIDGE_NAMES, SampleRecord, TrainingConfig

SCHEMA = 'autoencoder-distributed-features/v1'
FALSE_FLAGS = {'qualified': False, 'admitted': False, 'formalized': False,
               'promotion_performed': False, 'lake_executed': False}


def _require(condition, message):
    if not condition:
        raise work.DistributedTrainingError(message)


def _sample(value):
    return json.loads(inc._raw(asdict(SampleRecord.from_dict(value.get('sample', value)))))


def _artifact(path, maximum=64 * 1024 * 1024):
    path = Path(path).resolve(strict=True)
    _require(path.is_file() and path.stat().st_size <= maximum, 'feature artifact exceeds regular-file bound')
    with path.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256': sha, 'bytes': path.stat().st_size}


def _plain_reference(reference):
    return {key: reference[key] for key in ('sha256', 'bytes')}


def _samples(path):
    from .autoencoder_feature_inputs import _read, _rows
    return [_sample(row) for row in _rows(_read(path)[0])]


def _local_inputs(feature_inputs):
    from .autoencoder_feature_inputs import verify_feature_training_inputs
    from .legal_ir_target_bundle import DEFAULT_MAX_BYTES
    required = {'manifest_path', 'training_path', 'validation_path', 'shared_targets', 'target_snapshot_id'}
    _require(type(feature_inputs) is dict and required <= set(feature_inputs), 'complete local feature inputs required')
    local = dict(feature_inputs)
    for key in required - {'target_snapshot_id'}:
        _require(not Path(local[key]).is_symlink(), 'feature inputs cannot use symlink aliases')
        local[key] = str(Path(local[key]).resolve(strict=True))
    shard_bytes = local.get('target_shard_max_bytes', 64 * 1024 * 1024)
    timeout = local.get('target_timeout_seconds', 60)
    _require(type(shard_bytes) is int and 1 <= shard_bytes <= 256 * 1024 * 1024,
             'invalid shared target shard bound')
    _require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 600,
             'invalid shared target timeout')
    local.update(target_shard_max_bytes=shard_bytes, target_timeout_seconds=float(timeout))
    verification = verify_feature_training_inputs(local['manifest_path'], local['training_path'], local['validation_path'])
    from .autoencoder_feature_inputs import _read, _rows
    training_rows, validation_rows = _rows(_read(local['training_path'])[0]), _rows(_read(local['validation_path'])[0])
    training = [_sample(row) for row in training_rows]
    # Match the established local runner's stable normalized-record ordering.
    validation = sorted((_sample(row) for row in validation_rows), key=inc._sha)
    _require(len({inc._sha(row) for row in validation}) == len(validation), 'duplicate feature tuning rows')
    for role, path in (('training', local['training_path']), ('validation', local['validation_path'])):
        _require(_artifact(path) == _plain_reference(verification[role]['rows']), 'feature input changed after verification')
    binding = {
        'schema': SCHEMA, 'model': verification['model'],
        'embedding_production_artifact': _plain_reference(verification['embedding_production_receipt']),
        'source_artifacts_sha256': inc._sha(sorted((_plain_reference(ref) for ref in verification['source_artifacts']), key=lambda ref: ref['sha256'])),
        'source_artifact_count': len(verification['source_artifacts']),
        'roles': {role: {'artifact': _plain_reference(verification[role]['rows']),
                         'count': verification[role]['count'], 'input_ids_sha256': inc._sha(verification[role]['input_ids'])}
                  for role in ('training', 'validation')},
        'training_samples_sha256': inc._sha(training), 'validation_samples_sha256': inc._sha(validation),
        'shared_target_artifact': _artifact(local['shared_targets'], DEFAULT_MAX_BYTES),
        'target_snapshot_id': local['target_snapshot_id'], 'target_shard_max_bytes': shard_bytes,
        'target_timeout_seconds': float(timeout), 'local_embedding_verification': True,
        'selected_training_validation_disjoint': True, 'global_holdout_verified': False,
        'heldout_canary': False, **FALSE_FLAGS,
    }
    return {'verification': verification, 'training_samples': training, 'validation_samples': validation,
            'training_rows': training_rows, 'validation_rows': validation_rows,
            'binding': binding, 'feature_inputs': local}


def build_feature_policy(feature_inputs, records, validation):
    """Independently bind portable selected input identities before campaign creation."""
    checked = _local_inputs(feature_inputs)
    _require([_sample(row) for row in records] == checked['training_samples'], 'campaign training records differ from verified local inputs')
    _require(sorted((_sample(row) for row in validation), key=inc._sha) == checked['validation_samples'], 'campaign tuning records differ from verified local inputs')
    return {'training_purpose': 'feature_pretraining', 'feature_input_binding': checked['binding']}


def validate_feature_inputs(policy, feature_inputs):
    _require(policy.get('training_purpose') == 'feature_pretraining', 'explicit feature campaign purpose required')
    checked = _local_inputs(feature_inputs)
    _require(checked['binding'] == policy.get('feature_input_binding'), 'local feature inputs differ from campaign policy')
    return checked


@contextmanager
def _target_environment(binding):
    values = {'IPFS_DATASETS_LEGAL_IR_TARGET_TIMEOUT_SECONDS': str(binding['target_timeout_seconds']),
              'IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE': '0'}
    old = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _immutable_bytes(path, raw):
    """Publish complete durable bytes without replacing a competing writer."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        if not path.exists() and not path.is_symlink():
            descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
            temporary = Path(name)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                # A concurrent publisher owns the final name. Compare its bytes.
                pass
        _require(not path.is_symlink() and path.is_file() and path.read_bytes() == raw,
                 'immutable feature assignment input changed')
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _assignment_manifest(assignment, checked, directory):
    """Select one already verified row; never infer, split or regenerate vectors."""
    from .autoencoder_feature_inputs import INPUT_SCHEMA, verify_feature_training_inputs
    sample = _sample(assignment['record'])
    indices = [index for index, row in enumerate(checked['training_samples']) if row == sample]
    _require(len(indices) == 1, 'assignment is not a unique verified training row')
    selected_id = checked['verification']['training']['input_ids'][indices[0]]
    directory = Path(directory)
    source, tune = directory/'source.jsonl', directory/'validation.jsonl'
    _immutable_bytes(source, inc._raw(checked['training_rows'][indices[0]]) + b'\n')
    _immutable_bytes(tune, b''.join(inc._raw(row)+b'\n' for row in checked['validation_rows']))
    proof = checked['verification']
    manifest = {'schema': INPUT_SCHEMA, 'model': proof['model'],
        'embedding_production_receipt': proof['embedding_production_receipt'],
        'source_artifacts': proof['source_artifacts'], 'artifacts': {
            'training': {'rows': {'path': str(source.resolve()), **_artifact(source)}, 'count': 1, 'input_ids': [selected_id]},
            'validation': {'rows': {'path': str(tune.resolve()), **_artifact(tune)},
                'count': len(checked['validation_samples']), 'input_ids': proof['validation']['input_ids']}}}
    path = directory/'feature-inputs.json'
    _immutable_bytes(path, inc._raw(manifest)+b'\n')
    verify_feature_training_inputs(path, source, tune)
    return path


def _config(assignment, policy, installed, directory, checked, resource_ledger):
    config = work.training_config({'lake_timeout_seconds': 120, 'max_training_rounds': 1, **policy}, directory, installed['checkpoint_path'])
    manifest = _assignment_manifest(assignment, checked, directory)
    local = checked['feature_inputs']
    config.update(training_purpose='feature_pretraining', execution_mode='training', publish_repository=None,
        feature_input_manifest=str(manifest), shared_targets=local['shared_targets'],
        target_snapshot_id=local['target_snapshot_id'], target_shard_max_bytes=local['target_shard_max_bytes'],
        max_batches=1, max_training_rounds=1, fresh_training_workers=True)
    optimizer = policy.get('feature_optimizer', {})
    allowed = {'epochs', 'learning_rate', 'line_search_attempts', 'projection_optimizer_mode',
               'projection_momentum', 'projection_candidate_update_order'}
    _require(set(optimizer) <= allowed, 'unsupported distributed feature optimizer policy')
    config.update(optimizer)
    if isinstance(config.get('projection_candidate_update_order'), str):
        config['projection_candidate_update_order'] = [config['projection_candidate_update_order']]
    if resource_ledger is not None:
        config['resource_ledger'] = str(Path(resource_ledger).resolve())
    return config


def _exchange(exchange):
    if exchange is not None:
        return exchange
    from . import autoencoder_feature_exchange
    return autoencoder_feature_exchange


def execute_feature_assignment(assignment, policy, installed, directory, *, feature_inputs,
                               execute_cycle=None, resource_ledger=None, exchange=None):
    """Run the existing supervised private feature lane, then publish sparse evidence."""
    from ...duckdb_control.autoencoder_registry import AutoencoderRegistry
    _require(work.identity() == policy['source_identity'], 'worker source differs from feature campaign policy')
    checked = validate_feature_inputs(policy, feature_inputs)
    _require(installed['binding']['generation'] == assignment['generation']
             and installed['binding']['version_id'] == assignment['base_version_id'], 'installed generation differs from feature assignment')
    work.verify_complete_checkpoint(installed['checkpoint_path'], installed['binding']['artifact'])
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=True)
    config = _config(assignment, policy, installed, directory, checked, resource_ledger)
    state = directory/'feature-training-result.json'
    if state.exists():
        execution = work._read(state)
    else:
        with _target_environment(checked['binding']):
            execution = (execute_cycle or work.local_cli().supervised_cycle)(config)
        if execution.get('deferred'):
            raise work.CapacityDeferred('feature training capacity unavailable')
    cycle = work._read(execution['receipt'])
    _require(cycle.get('training_purpose') == 'feature_pretraining', 'assignment ran another training purpose')
    completed = cycle['training']['completed']
    if not completed and cycle['training'].get('capacity_deferred'):
        raise work.CapacityDeferred('feature dispatch capacity unavailable')
    _require(len(completed) == 1, 'feature assignment did not produce exactly one completion')
    evidence = completed[0]
    for flag in ('qualified','admitted','formalized','promotion_performed','publication_performed'):
        _require(evidence.get(flag) is False, 'feature completion cannot grant qualification')
    exchange = _exchange(exchange)
    with AutoencoderRegistry(directory/'control.duckdb', directory/'artifacts') as registry:
        worker_ref = evidence['worker_receipt_artifact']; registry.verify_artifact(worker_ref)
        worker = json.loads(registry.artifact_path(worker_ref).read_bytes())
        _require(worker.get('base_materialized_checkpoint') == installed['binding']['artifact'], 'local feature job used different complete parent weights')
        _require(evidence['base_version_id'] == worker['base_version_id'], 'feature evidence parent differs from worker')
        accepted = evidence['optimizer_accepted_epochs']
        _require(type(accepted) is int and accepted >= 0, 'invalid accepted feature epoch count')
        completion = {**evidence, 'result': registry.get_run(evidence['run_id'])['result']}
        # A failed upload must resume publication, never rerun a consumed lane.
        _immutable_bytes(state, inc._raw(execution))
        weight_reference = None
        if accepted:
            parent_reference = installed['binding']['weight_reference']
            depth, cursor = 0, parent_reference
            while cursor.get('kind') == 'feature_sparse':
                depth += 1; cursor = cursor['anchor_reference']
            if depth >= exchange.MAX_DEPTH - 1:
                compacted = work.retry_publication(lambda: exchange.publish_feature_checkpoint(
                    installed['checkpoint_path'], expected_artifact=installed['binding']['artifact'],
                    generation=assignment['generation'], upload=True))
                parent_reference = {**compacted['weight_reference'], 'kind':'anchor',
                                    'materialized_checkpoint':installed['binding']['artifact']}
            staged = exchange.stage_feature_update(registry, evidence['candidate_version_id'], evidence,
                directory/'feature-publication', parent_reference=parent_reference)
            weight_reference = work.retry_publication(lambda: exchange.publish_feature_update(staged['manifest_path'], upload=True))['weight_reference']
        candidate_artifact = worker.get('candidate_materialized_checkpoint')
        _require(type(candidate_artifact) is dict, 'feature worker omitted complete candidate identity')
        if not accepted:
            _require(candidate_artifact == installed['binding']['artifact'], 'feature no-update changed complete weights')
        report = {'schema': exchange.REPORT_SCHEMA, 'training_purpose': 'feature_pretraining',
            'assignment_binding': assignment, 'assignment_sha256': inc._sha(assignment),
            'work_id': assignment['run_id'], 'span_revision': assignment['record']['record_id'],
            'source_provenance': {'source_record': assignment['record'],
                'source_observation': assignment.get('source_observation'),
                'canonical_generation': assignment['generation'], 'canonical_version_id': assignment['base_version_id'],
                'canonical_artifact': installed['binding']['artifact'], 'source_identity': policy['source_identity'],
                'feature_input_binding': checked['binding']},
            'disposition': 'feature_updated' if accepted else 'feature_no_update',
            'candidate_version_id': evidence['candidate_version_id'], 'candidate_artifact': candidate_artifact,
            'base_artifact': installed['binding']['artifact'], 'feature_evidence': evidence,
            'completion': completion,
            'training_config': worker['job_spec']['training_config'],
            'autoencoder_config': worker['job_spec']['autoencoder_config'],
            'training_samples': [_sample(assignment['record'])], 'validation_samples': checked['validation_samples'],
            'worker_receipt': worker, 'weight_publication': weight_reference,
            **FALSE_FLAGS}
    _require(work.identity() == policy['source_identity'], 'worker producer changed before feature publication')
    publication = work.retry_publication(lambda: exchange.publish_feature_report(report, directory/'feature-report', upload=True))
    result = {'schema': SCHEMA, 'assignment': assignment, 'feature_disposition': report['disposition'],
              'report_reference': publication['report_reference'], 'weight_reference': weight_reference,
              'local_training_receipt': execution['receipt'], **FALSE_FLAGS}
    work._write(directory/'result.json', result)
    return result


def _expected_training_config(policy):
    optimizer = policy.get('feature_optimizer', {})
    order = optimizer.get('projection_candidate_update_order')
    if isinstance(order, str):
        order = [order]
    return TrainingConfig(max_seconds=policy['max_seconds'], profile_projection=True,
        epochs=optimizer.get('epochs', 1), learning_rate=optimizer.get('learning_rate', .35),
        max_line_search_attempts=optimizer.get('line_search_attempts', 1),
        projection_optimizer_mode=optimizer.get('projection_optimizer_mode', 'fixed'),
        projection_momentum=optimizer.get('projection_momentum', 0.),
        projection_candidate_update_order=order, projection_max_update_families=5,
        projection_reconstruction_objective='raw_decoder')


def _bind_remote_report(report, assignment, policy, checked, base_artifact):
    """Remote paths carry no authority; compare only assigned bytes and policy."""
    _require(report.get('training_purpose') == 'feature_pretraining'
             and report.get('assignment_binding') == assignment
             and report.get('assignment_sha256') == inc._sha(assignment), 'remote feature assignment binding differs')
    for key, value in FALSE_FLAGS.items():
        _require(report.get(key) is value, 'remote feature report claims qualification')
    expected = {'source_record': assignment['record'], 'source_observation': assignment.get('source_observation'),
        'canonical_generation': assignment['generation'], 'canonical_version_id': assignment['base_version_id'],
        'canonical_artifact': base_artifact, 'source_identity': policy['source_identity'],
        'feature_input_binding': checked['binding']}
    _require(report.get('source_provenance') == expected and report.get('base_artifact') == base_artifact,
             'remote feature source or parent differs')
    _require(report.get('training_samples') == [_sample(assignment['record'])]
             and report.get('validation_samples') == checked['validation_samples'], 'remote feature sample selection differs')
    config = _expected_training_config(policy)
    _require(TrainingConfig.from_dict(report['training_config']).to_dict() == config.to_dict()
             and report.get('autoencoder_config') == {'compute_device': 'python'}, 'remote feature optimizer/model policy differs')
    worker = report['worker_receipt']
    from .autoencoder_training_worker import TrainingJobSpec
    spec = TrainingJobSpec.from_dict(worker['job_spec'])
    _require(spec.canonical_sha256 == worker.get('job_spec_canonical_sha256')
             and inc._raw(spec.to_dict()['training_config']) == inc._raw(config.to_dict())
             and spec.to_dict()['samples'] == report['training_samples']
             and spec.to_dict()['validation_samples'] == report['validation_samples']
             and dict(spec.autoencoder_config) == report['autoencoder_config'], 'remote worker job binding differs')
    expected_sources = {key: policy['source_identity'].get('native:' + key)
                        for key in spec.expected_source_sha256}
    _require(bool(expected_sources) and dict(spec.expected_source_sha256) == expected_sources
             and worker.get('tree_file_sha256') == expected_sources
             and worker.get('source_manifest_verified') is True, 'remote worker native source hashes differ')
    evidence = report['feature_evidence']
    accepted = evidence['optimizer_accepted_epochs']
    _require(type(accepted) is int and 0 <= accepted <= config.epochs
             and worker['training_report'].get('accepted_epochs') == accepted, 'invalid feature accepted-epoch count')
    _require(report['disposition'] == ('feature_updated' if accepted else 'feature_no_update'), 'feature disposition disagrees with optimizer')
    _require(spec.target_snapshot_id == checked['binding']['target_snapshot_id']
             and _plain_reference(asdict(spec.target_snapshot_artifact)) == checked['binding']['shared_target_artifact'],
             'remote feature target artifact differs')
    return config, accepted, spec


def _independent_feature_evaluation(base_path, candidate_path, assignment, checked, config, accepted):
    """Evaluate complete parent/candidate bytes against independently hydrated targets."""
    from . import modal_autoencoder as ma
    from .legal_samples import build_us_code_sample
    from .autoencoder_feature_training import verify_feature_target_supervision
    from .autoencoder_training_worker import _effective_constructor_config
    from .autoencoder_target_preparation import target_snapshot_config, unique_training_samples
    from .legal_ir_target_bundle import load_target_artifact
    from ._autoencoder_prepared_targets import _prepare_native_targets
    training = [build_us_code_sample(**_sample(assignment['record']))]
    tuning = [build_us_code_sample(**sample) for sample in checked['validation_samples']]
    members = unique_training_samples(training, tuning)
    local, binding = checked['feature_inputs'], checked['binding']
    with _target_environment(binding):
        target_config = target_snapshot_config(config)
        snapshot = load_target_artifact(local['shared_targets'], expected_sha256=binding['shared_target_artifact']['sha256'],
            config=target_config, max_bytes=binding['shared_target_artifact']['bytes'], max_shard_bytes=local['target_shard_max_bytes'])
        try:
            _require(snapshot.snapshot_id == binding['target_snapshot_id'], 'owner shared-target snapshot differs')
            targets, checked_ids = {}, set()
            iterator = snapshot.iter_targets_for(members, config=target_config)
            try:
                for sample_id, target in iterator:
                    verify_feature_target_supervision({sample_id:target}, snapshot.statuses, BRIDGE_NAMES, sample_ids=[sample_id])
                    _require(sample_id not in checked_ids, 'owner target repeats a selected sample')
                    converted, reduction = _prepare_native_targets({sample_id: target})
                    _require(reduction['applied'] is True, 'owner target reduction was not applicable')
                    targets[sample_id] = converted[sample_id]
                    checked_ids.add(sample_id)
                    del target, converted
            finally:
                iterator.close()
            _require(checked_ids == {sample.sample_id for sample in members}, 'owner target coverage differs')
            evaluations, observations = {}, {}
            for phase, path in (('before', base_path), ('after', candidate_path)):
                state = ma.ModalAutoencoderTrainingState.load_json(path)
                model = ma.AdaptiveModalAutoencoder(state=state, **_effective_constructor_config(ma.AdaptiveModalAutoencoder, {'compute_device':'python'}))
                result = model.evaluate(tuning, legal_ir_bridge_names=BRIDGE_NAMES, legal_ir_evaluate_provers=False,
                    legal_ir_parallel_workers=1, legal_ir_targets=targets, use_sample_memory=False,
                    reconstruction_objective='raw_decoder')
                _require(not ma.nonfinite_evaluation_fields(result) and result.sample_count == len(tuning)
                         and result.legal_ir_target_count == len(tuning) and bool(result.legal_ir_losses),
                         'owner raw/IR evaluation incomplete or nonfinite')
                observations[phase] = model._raw_decoder_evaluation_observation(result, tuning)
                evaluations[phase] = result
                del model, state
        finally:
            close = getattr(snapshot, 'close', None)
            if close is not None:
                close()
    before, after = evaluations['before'], evaluations['after']
    _require(set(before.legal_ir_losses) == set(after.legal_ir_losses), 'owner IR metric coverage changed')
    regressions = ma._evaluation_regressions_for_training(before, after,
        max_cosine_regression=config.max_cosine_regression*accepted,
        max_reconstruction_regression=config.max_reconstruction_regression*accepted,
        max_cross_entropy_regression=config.max_cross_entropy_regression*accepted,
        max_legal_ir_loss_regression=config.max_legal_ir_loss_regression*accepted)
    weights = {'cross_entropy':config.objective_cross_entropy_weight,
               'reconstruction':config.objective_reconstruction_weight,
               'cosine_gap':config.objective_cosine_gap_weight, 'legal_ir':config.objective_legal_ir_weight}
    delta = ma._evaluation_objective_for_training(before, **weights) - ma._evaluation_objective_for_training(after, **weights)
    _require(math.isfinite(delta) and not regressions and (delta > 0 if accepted else delta == 0),
             'independent owner feature objective did not improve or violated guards')
    return {'before': before.to_dict(), 'after': after.to_dict(), 'raw_observations': observations,
            'objective_delta':delta, 'pareto_regressions':regressions, 'objective_weights':weights,
            'target_sample_count':len(members), 'bridge_names':list(BRIDGE_NAMES),
            'legal_ir_evaluate_provers':False, 'metric_disk_cache':0, 'legal_ir_parallel_workers':1,
            'use_sample_memory':False, 'shared_target_supervision_verified':True,
            'validation_role':'repeated_selection_tuning', 'heldout_canary':False, **FALSE_FLAGS}


def _validate_owner_evaluation(evaluation, checked, config, accepted):
    """Recheck retained native evidence before crash recovery can reuse it."""
    from . import modal_autoencoder as ma
    from .legal_samples import _sample_id
    from .legal_modal_parser import LegalModalParser
    normalizer = LegalModalParser()
    ids = {_sample_id(row['title'], row['section'], normalizer.normalize_text(row['text']))
           for row in checked['validation_samples']}
    count = len(checked['validation_samples'])
    finite = lambda value: type(value) in (int, float) and math.isfinite(value)
    _require(count > 0 and len(ids) == count, 'owner tuning identities incomplete')
    _require(evaluation.get('shared_target_supervision_verified') is True
             and evaluation.get('bridge_names') == list(BRIDGE_NAMES)
             and evaluation.get('target_sample_count') == count + 1
             and evaluation.get('legal_ir_evaluate_provers') is False
             and evaluation.get('metric_disk_cache') == 0
             and evaluation.get('legal_ir_parallel_workers') == 1
             and evaluation.get('use_sample_memory') is False
             and all(evaluation.get(flag) is False for flag in FALSE_FLAGS),
             'owner evaluator bridge, target or qualification evidence differs')
    values = {}
    for phase in ('before', 'after'):
        value, observation = evaluation.get(phase, {}), evaluation.get('raw_observations', {}).get(phase, {})
        _require(value.get('sample_count') == count and value.get('legal_ir_target_count') == count
                 and all(finite(value.get(key)) for key in ('embedding_cosine_similarity', 'reconstruction_loss', 'cross_entropy_loss'))
                 and value['reconstruction_loss'] >= 0
                 and type(value.get('legal_ir_losses')) is dict and bool(value['legal_ir_losses'])
                 and all(finite(item) for item in value['legal_ir_losses'].values()),
                 'owner raw/IR metrics incomplete or nonfinite')
        for key in ('cross_entropy_excess_loss', 'cross_entropy_entropy_loss'):
            _require(key not in value or finite(value[key]), 'owner cross-entropy metric nonfinite')
        rows = observation.get('sample_metrics', [])
        _require(observation.get('complete') is True and observation.get('finite') is True
                 and observation.get('used_for_acceptance') is True and observation.get('sample_memory_used') is False
                 and observation.get('requested_sample_count') == count and observation.get('observed_sample_count') == count
                 and len(rows) == count and {row.get('sample_id') for row in rows} == ids,
                 'owner raw observation sample coverage differs')
        for key, mean in (('embedding_cosine_similarity', 'embedding_cosine_similarity_mean'),
                          ('reconstruction_loss', 'reconstruction_loss_mean')):
            _require(all(finite(row.get(key)) for row in rows) and finite(observation.get(mean))
                     and all(row.get('reconstruction_loss', -1) >= 0 for row in rows)
                     and math.isclose(sum(row[key] for row in rows)/count, value[key], abs_tol=1e-12, rel_tol=1e-10)
                     and math.isclose(observation[mean], value[key], abs_tol=1e-12, rel_tol=1e-10),
                     'owner raw observation aggregate differs')
        values[phase] = SimpleNamespace(**value)
    before, after = values['before'], values['after']
    _require(set(before.legal_ir_losses) == set(after.legal_ir_losses), 'owner IR metric coverage changed')
    weights = {'cross_entropy': config.objective_cross_entropy_weight, 'reconstruction': config.objective_reconstruction_weight,
               'cosine_gap': config.objective_cosine_gap_weight, 'legal_ir': config.objective_legal_ir_weight}
    regressions = ma._evaluation_regressions_for_training(before, after,
        max_cosine_regression=config.max_cosine_regression*accepted,
        max_reconstruction_regression=config.max_reconstruction_regression*accepted,
        max_cross_entropy_regression=config.max_cross_entropy_regression*accepted,
        max_legal_ir_loss_regression=config.max_legal_ir_loss_regression*accepted)
    delta = ma._evaluation_objective_for_training(before, **weights) - ma._evaluation_objective_for_training(after, **weights)
    _require(not regressions and evaluation.get('pareto_regressions') == {}
             and evaluation.get('objective_weights') == weights and finite(evaluation.get('objective_delta'))
             and math.isclose(delta, evaluation['objective_delta'], abs_tol=1e-12, rel_tol=1e-10)
             and (delta > 0 if accepted else delta == 0), 'owner objective or regression guards differ')


def owner_feature_verifier(registry, policy, directory, *, feature_inputs, exchange=None, evaluator=None):
    """Return the owner-only verifier; native raw/IR evaluation is the default."""
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=True)
    exchange = _exchange(exchange)
    def verify(assignment, descriptor):
        _require(work.identity() == policy['source_identity'], 'owner source differs from feature campaign policy')
        checked = validate_feature_inputs(policy, feature_inputs)
        _require(_sample(assignment['record']) in checked['training_samples'], 'remote assignment not in local verified training selection')
        root = directory / descriptor['sha256']; root.mkdir(exist_ok=True)
        report = exchange.download_feature_report(descriptor, root/'report')['report']
        base = registry.get_version(assignment['base_version_id'])
        registry.verify_artifact(base['artifact'])
        config, accepted, spec = _bind_remote_report(report, assignment, policy, checked, base['artifact'])
        worker_path = root/'worker-receipt.json'; _immutable_bytes(worker_path, inc._raw(report['worker_receipt']) + b'\n')
        worker_ref = registry.stage_artifact(worker_path)
        from .autoencoder_feature_training import _feature_evidence
        completion = dict(report['completion'])
        _require({key: completion.get(key) for key in report['feature_evidence']} == report['feature_evidence'],
                 'remote completion differs from feature evidence')
        _require(completion.get('result', {}).get('worker_receipt_artifact') == worker_ref,
                 'remote completion worker receipt bytes differ')
        # Structural remote evidence checks precede independent reconstruction.
        _feature_evidence(registry, spec, completion)
        candidate_path = registry.artifact_path(base['artifact'])
        replay_verified = not accepted
        if accepted:
            reference = report['weight_publication']
            _require(reference and reference['kind'] == 'feature_sparse', 'feature update requires sparse transport')
            anchor = reference['anchor_reference']
            parent_artifact = anchor['materialized_checkpoint'] if 'materialized_checkpoint' in anchor else _plain_reference(anchor)
            _require(parent_artifact == base['artifact'], 'feature sparse parent differs from assignment')
            installed = work.install_generation({'generation':assignment['generation']+1,
                'version_id':report['candidate_version_id'], 'artifact':report['candidate_artifact'],
                'weight_reference':reference}, root/'candidate', advertise_current=False,
                anchor_resolver=lambda expected: registry.artifact_path(expected) if registry.artifact_path(expected).is_file() else None)
            candidate_path = Path(installed['checkpoint_path'])
            replay_verified = installed.get('download_receipt', {}).get('replay_verified') is True
            _require(replay_verified, 'feature sparse reconstruction was not verified')
        else:
            _require(report['weight_publication'] is None and report['candidate_artifact'] == base['artifact'],
                     'feature no-update report changes assigned weights')
        work.verify_complete_checkpoint(candidate_path, report['candidate_artifact'])
        artifact = registry.stage_artifact(candidate_path, report['candidate_artifact']['sha256'])
        owner_evidence = {'schema':SCHEMA, 'training_purpose':'feature_pretraining',
            'assignment_sha256':inc._sha(assignment), 'assignment':assignment,
            'report_artifact':_plain_reference(descriptor), 'base_artifact':base['artifact'],
            'candidate_artifact':artifact, 'source_identity':policy['source_identity'],
            'feature_input_binding':checked['binding'], 'optimizer_accepted_epochs':accepted,
            'disposition':report['disposition'],
            'owner_verified':True, 'sparse_replay_verified':replay_verified,
            'raw_objective_verified':True, 'shared_target_supervision_verified':True, **FALSE_FLAGS}
        evidence_path = root/'owner-feature-evidence.json'
        if evidence_path.exists():
            retained = work._read(evidence_path)
            _require({key:value for key,value in retained.items() if key != 'evaluation'} == owner_evidence,
                     'retained owner feature evidence binding differs')
            evaluation = retained['evaluation']
        else:
            evaluation = (evaluator or _independent_feature_evaluation)(registry.artifact_path(base['artifact']),
                candidate_path, assignment, checked, config, accepted)
        _validate_owner_evaluation(evaluation, checked, config, accepted)
        _require(work.identity() == policy['source_identity'], 'owner source changed during feature verification')
        owner_evidence['evaluation'] = evaluation
        _immutable_bytes(evidence_path, inc._raw(owner_evidence))
        evidence_ref = registry.stage_artifact(evidence_path)
        result = {'training_purpose':'feature_pretraining', 'owner_verified':True,
            'span_disposition':report['disposition'], 'optimizer_accepted_epochs':accepted,
            'feature_evidence_artifact':evidence_ref, 'report_artifact':_plain_reference(descriptor),
            'weight_reference':report['weight_publication'], 'sparse_replay_verified':replay_verified,
            'raw_objective_verified':True, 'shared_target_supervision_verified':True,
            'verification_scope':'independent complete-weight raw decoder and five-bridge tuning evaluation', **FALSE_FLAGS}
        return {'artifact':artifact,'result':result}
    return verify


def advance_feature_generation(campaign):
    """CAS one owner-verified child and requeue previously completed stale siblings."""
    _require(campaign.binding['policy'].get('training_purpose') == 'feature_pretraining', 'feature advancement requires feature purpose')
    current = campaign.status()['weights']; registry = campaign.registry
    with registry._transaction() as cx:
        stale = cx.execute("SELECT attempts.run_id FROM autoencoder_control.runs attempts "
            "JOIN autoencoder_control.runs source ON source.run_id=json_extract_string(attempts.spec,'$.work_id') "
            "WHERE attempts.status='completed' AND source.status='source_completed' "
            "AND json_extract_string(source.result,'$.completion.run_id')=attempts.run_id "
            "AND attempts.base_version_id!=? AND json_extract_string(attempts.spec,'$.campaign_id')=? "
            "AND json_extract_string(attempts.spec,'$.kind')='generation_attempt' "
            "AND json_extract_string(attempts.result,'$.span_disposition')='feature_updated' "
            "ORDER BY attempts.run_id", [current['version_id'], campaign.campaign_id]).fetchall()
        selected = {row[0] for row in cx.execute("SELECT json_extract_string(receipt,'$.version_id') "
            "FROM autoencoder_control.operations WHERE json_extract_string(receipt,'$.command')='AdvanceSpanGeneration' "
            "AND json_extract_string(receipt,'$.campaign_id')=? AND json_extract_string(receipt,'$.binding_sha256')=?",
            [campaign.campaign_id, campaign.binding_sha256]).fetchall()}
    for run_id, in stale:
        version_id = registry.get_run_completion(run_id)['candidate_version']['version_id']
        if version_id not in selected and version_id != current['version_id']:
            campaign.requeue_stale_feature_candidate('rebase-feature-' + version_id, version_id,
                expected_generation=current['generation'], expected_version_id=current['version_id'])
    with registry._transaction() as cx:
        rows = cx.execute("SELECT run_id FROM autoencoder_control.runs WHERE status='completed' "
            "AND base_version_id=? AND json_extract_string(spec,'$.campaign_id')=? "
            "AND json_extract_string(spec,'$.kind')='generation_attempt' "
            "AND json_extract_string(result,'$.span_disposition')='feature_updated' ORDER BY run_id",
            [current['version_id'], campaign.campaign_id]).fetchall()
    if not rows:
        return None
    completed = registry.get_run_completion(rows[0][0]); result=completed['run']['result']; candidate=completed['candidate_version']
    reference=result.get('feature_evidence_artifact')
    _require(reference is not None,'feature advancement lacks owner evidence')
    registry.verify_artifact(reference)
    evidence=json.loads(registry.artifact_path(reference).read_bytes())
    _require(evidence.get('candidate_artifact') == candidate['artifact']
             and evidence.get('base_artifact') == current['artifact']
             and evidence.get('source_identity') == campaign.binding['policy']['source_identity']
             and work.identity() == campaign.binding['policy']['source_identity']
             and evidence.get('feature_input_binding') == campaign.binding['policy']['feature_input_binding']
             and evidence.get('disposition') == 'feature_updated'
             and evidence.get('optimizer_accepted_epochs') == result.get('optimizer_accepted_epochs'),
             'feature advancement evidence differs from candidate or policy')
    for flag in ('owner_verified','sparse_replay_verified','raw_objective_verified','shared_target_supervision_verified'):
        _require(evidence.get(flag) is True and result.get(flag) is True,'feature advancement lacks '+flag)
    for flag in FALSE_FLAGS:
        _require(evidence.get(flag) is False and result.get(flag) is False,'feature advancement cannot qualify legal text')
    return campaign.advance_generation('select-feature-'+candidate['version_id'], candidate['version_id'],
        expected_generation=current['generation'], expected_version_id=current['version_id'],
        weight_reference=result['weight_reference'])
