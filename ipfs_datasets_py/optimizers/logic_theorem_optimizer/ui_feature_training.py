"""Local UI corpus to native projections, isolated training, and feature inference.

This joins explicit DOM/IDL corpus records to the existing structural backend.
It neither generates application code nor dispatches an object-broker request.
The caller owns resource admission and the single database owner process.
"""
from __future__ import annotations

import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import time

from . import autoencoder_projection_features as features
from .autoencoder_modality_contracts import ModalityContract
from ...logic.formalization.autoencoder import ui_training_inputs

SCHEMA = 'ui-feature-batch/v1'
DEFAULT_PROJECTIONS = ('ui_ux_ir:flogic', 'ui_ux_ir:event_calculus',
                       'ui_ux_ir:tdfol', 'ui_ux_ir:dcec', 'ui_ux_ir:interface_bindings')
MAX_ROWS = 128
MAX_INPUT_BYTES = 8 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _save(path, value):
    with Path(path).open('xb') as stream:
        stream.write(_json(value)); stream.flush(); os.fsync(stream.fileno())


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def load_ui_training_jsonl(path):
    """Read a bounded local JSONL corpus; never fetch datasets or import plugins."""
    path = Path(path)
    _require(path.is_file() and not path.is_symlink(), 'regular local corpus file required')
    with path.open('rb') as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    _require(len(raw) <= MAX_INPUT_BYTES, 'UI input exceeds byte bound')
    lines = [line for line in raw.splitlines() if line.strip()]
    _require(1 <= len(lines) <= MAX_ROWS, 'UI input exceeds row bound or is empty')
    rows = [json.loads(line, object_pairs_hook=_unique_object) for line in lines]
    return rows, {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def producer_identity():
    """Bind selected UI/family/codec sources and dependency versions, not an OS capsule."""
    root = Path(__file__).resolve().parents[2]
    files = {Path(__file__), Path(features.__file__), Path(features.__file__).with_name('modal_autoencoder_cuda.py'),
             Path(features.__file__).with_name('autoencoder_modality_contracts.py'),
             Path(features.__file__).with_name('ui_formal_decoder.py'),
             Path(features.__file__).with_name('native_formal_decoder.py')}
    for directory in ('logic/ui_ux_ir', 'logic/families'):
        files.update((root/directory).rglob('*.py'))
    # Other modalities share this package but are not UI target producers.
    # Pin the concrete imported adapters instead of unrelated Security work.
    for relative in ('logic/formalization/autoencoder/domain_targets.py',
                     'logic/formalization/autoencoder/ui_targets.py',
                     'logic/formalization/autoencoder/ui_training_inputs.py',
                     'logic/conformance/ui_ux_logic_gate_v2.py'):
        files.add(root/relative)
    sources = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in sorted(files)}
    versions = {name: metadata.version(name) for name in ('torch', 'duckdb', 'jsonschema')}
    result = {'sources': sources, 'dependencies': versions,
              'scope': 'selected_ui_family_codec_sources_and_library_versions_not_full_runtime_capsule'}
    return {**result, 'sha256': features.digest(result)}


def prepare_ui_rows(rows, *, role):
    _require(role in {'training', 'tuning', 'inference'}, 'unknown UI data role')
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= MAX_ROWS, 'bounded nonempty UI rows required')
    _require(len(_json(rows)) <= MAX_INPUT_BYTES, 'UI input exceeds byte bound')
    prepared = [ui_training_inputs.prepare_ui_training_row(row) for row in rows]
    identities = [row.input_sha256 for row in prepared]
    _require(len(set(identities)) == len(identities), 'duplicate UI input')
    _require(len({(row.provenance['dataset'], row.provenance['revision'], row.source_id)
                  for row in prepared}) == len(prepared), 'duplicate source record identity')
    if role != 'inference':
        allowed = {'train'} if role == 'training' else {'validation', 'valid', 'tuning'}
        _require(all(row.provenance['split'] in allowed for row in prepared),
                 'training requires train split and tuning requires validation/valid/tuning; test/canary rows are excluded')
    return prepared


def _load_parent(registry, version_id):
    parent = registry.get_version(version_id)
    registry.verify_artifact(parent['artifact'])
    path = registry.artifact_path(parent['artifact'])
    _require(path.stat().st_size <= 32 * 1024 * 1024, 'parent exceeds native checkpoint bound')
    saved = json.loads(path.read_bytes(), object_pairs_hook=_unique_object)
    contract = ModalityContract.from_dict(saved['contract'])
    _require(contract.domain == 'ui_ux_ir' and parent['variant_id'] == contract.variant_id,
             'parent is not the requested UI modality')
    _require(saved['report'].get('ui_batch', {}).get('schema') == SCHEMA,
             'parent requires UI corpus split and producer evidence')
    return saved, contract


def _source_ids(rows):
    return {(r.provenance['dataset'], r.provenance['revision'], r.source_id) for r in rows}


def train_ui_feature_batch(registry, training_rows, tuning_rows, directory, *, parent_version_id=None,
                           projection_ids=DEFAULT_PROJECTIONS, epochs=3, latent_width=4,
                           learning_rate=0.02, max_seconds=60.0, formal_decoder_version=None):
    """Prepare native targets, train/select, and register a private feature candidate.

    Resume keeps the original feature basis, tuning panel, and optimizer state.
    Group exclusions include all prior training groups, not just this batch.
    """
    from . import ui_formal_decoder as decoder
    _require(formal_decoder_version in (None, decoder.VERSION), 'unknown UI formal decoder version')
    started = time.monotonic()
    directory = Path(directory)
    _require(not directory.exists(), 'fresh UI attempt directory required')
    before_source = producer_identity()
    training = prepare_ui_rows(training_rows, role='training')
    tuning = prepare_ui_rows(tuning_rows, role='tuning')
    preparation_seconds = time.monotonic() - started
    train_groups, tune_groups = {row.group_id for row in training}, {row.group_id for row in tuning}
    _require(not train_groups & tune_groups, 'training/tuning group leakage')
    train_sources, tune_sources = _source_ids(training), _source_ids(tuning)
    _require(not train_sources & tune_sources, 'training/tuning source record leakage')
    targets, tuning_targets = [r.target for r in training], [r.target for r in tuning]
    base, decoder_head = None, None
    if parent_version_id is None:
        space = features.build_feature_space('ui_ux_ir', projection_ids, targets)
        contract = features.build_native_feature_contract(space, ir_schema=ui_training_inputs.SCHEMA,
            adapter_sha256=before_source['sha256'], latent_width=latent_width)
    else:
        saved, contract = _load_parent(registry, parent_version_id)
        history = saved['report']['ui_batch']
        _require(history['producer']['sha256'] == before_source['sha256'], 'UI producer changed; use a new variant')
        _require(history['tuning_groups'] == sorted(tune_groups), 'UI tuning groups changed')
        train_groups.update(history['training_groups'])
        _require(not train_groups & tune_groups, 'historical training/tuning group leakage')
        train_sources.update(tuple(item) for item in history['training_source_ids'])
        _require(not train_sources & tune_sources, 'historical training/tuning source record leakage')
        space, base = saved['feature_space'], saved['state']
        _require(sorted(projection_ids) == space['projection_ids'], 'UI projection set changed on resume')
        _require(history.get('formal_decoder_version') == formal_decoder_version, 'UI formal decoder version changed on resume')
        decoder_head = history.get('formal_decoder_head')
    if formal_decoder_version is not None:
        if parent_version_id is None:
            decoder_head = decoder.train_ui_formal_decoder(space, targets)
        else:
            decoder.validate_ui_decoder(space, decoder_head)
    result = features.train_projection_features(contract, space, targets, tuning_targets,
        base_state=base, epochs=epochs, latent_width=latent_width, learning_rate=learning_rate,
        max_seconds=max_seconds)
    _require(producer_identity() == before_source, 'UI producer changed during preparation/training')
    batch = {'schema': SCHEMA, 'producer': before_source, 'training_groups': sorted(train_groups),
             'tuning_groups': sorted(tune_groups), 'training_inputs': [r.input_sha256 for r in training],
             'training_source_ids': sorted(train_sources), 'tuning_source_ids': sorted(tune_sources),
             'tuning_inputs': [r.input_sha256 for r in tuning],
             'target_preparation_seconds': preparation_seconds,
             'source_provenance': [dict(r.provenance) for r in training + tuning],
             'interface_join': 'explicit_source_bound_declaration_not_runtime_authority', **features.FALSE}
    if formal_decoder_version is not None:
        batch.update(formal_decoder_version=formal_decoder_version, formal_decoder_head=decoder_head)
    result['report']['ui_batch'] = batch
    directory.mkdir(parents=True)
    _save(directory/'source_rows.json', {'training': training_rows, 'tuning': tuning_rows})
    _save(directory/'targets.json', {'training': [r.to_dict() for r in targets],
                                    'tuning': [r.to_dict() for r in tuning_targets]})
    receipt = features.register_feature_candidate(registry, contract, space, result, directory/'candidate',
                                                  parent_version_id=parent_version_id)
    summary = {'schema': SCHEMA, 'operation': 'training', 'training_executed': True,
               'registration': receipt, 'parent_version_id': parent_version_id,
               'projection_ids': space['projection_ids'], 'training_target_count': len(training),
               'tuning_target_count': len(tuning), 'target_preparation_seconds': preparation_seconds,
               'training_seconds': result['report']['elapsed_seconds'], 'wall_seconds': time.monotonic() - started,
               'improved': result['report']['improved'], 'attempted_epochs': result['report']['attempted_epochs'],
               'selected_total_epochs': result['state']['completed_epochs'],
               'before': result['report']['before'], 'after': result['report']['after'],
               'tuning_coverage': result['report']['tuning_coverage'], 'heldout_canary': False,
               'transport_executed': False, 'weights_downloaded': False, **features.FALSE}
    if formal_decoder_version is not None:
        predicted = features.infer_projection_features(contract, space, result['state'], tuning_targets)
        fidelity = decoder.evaluate_ui_decoded_fidelity(space, decoder_head, predicted, tuning_targets)
        summary.update(formal_decoder_version=formal_decoder_version, decoder_tuning_fidelity=fidelity,
            formal_decoder_scope='structural_compiler_output_readout_not_source_text_decoder')
        _save(directory/'formal-decoder.json', decoder_head)
        _save(directory/'decoder-tuning-fidelity.json', fidelity)
    _require(producer_identity() == before_source, 'UI producer changed during decoder measurement')
    summary['wall_seconds'] = time.monotonic() - started
    _save(directory/'report.json', summary)
    return summary


def infer_ui_feature_batch(registry, version_id, rows, directory):
    """Read the saved native model; no candidate registration or optimizer call."""
    directory = Path(directory)
    _require(not directory.exists(), 'fresh UI inference directory required')
    producer = producer_identity()
    saved, contract = _load_parent(registry, version_id)
    _require(saved['report']['ui_batch']['producer']['sha256'] == producer['sha256'], 'UI producer changed')
    prepared = prepare_ui_rows(rows, role='inference')
    result = features.infer_projection_features(contract, saved['feature_space'], saved['state'],
                                                 [row.target for row in prepared])
    _require(producer_identity() == producer, 'UI producer changed during inference')
    result.update({'ui_batch_schema': SCHEMA, 'version_id': version_id, 'transport_executed': False})
    if saved['report']['ui_batch'].get('formal_decoder_version') is not None:
        from . import ui_formal_decoder as decoder
        _require(saved['report']['ui_batch']['formal_decoder_version'] == decoder.VERSION, 'unknown saved UI decoder version')
        head = saved['report']['ui_batch']['formal_decoder_head']
        result['formal_decoding'] = decoder.decode_ui_formal_features(saved['feature_space'], head, result)
        result['decoder_fidelity'] = decoder.evaluate_ui_decoded_fidelity(saved['feature_space'], head, result,
            [row.target for row in prepared])
        result['formal_decoder_version'] = decoder.VERSION
    _require(producer_identity() == producer, 'UI producer changed during decoding')
    directory.mkdir(parents=True)
    _save(directory/'source_rows.json', {'inference': rows})
    _save(directory/'inference.json', result)
    return result
