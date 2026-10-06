#!/usr/bin/env python3
"""Reproduce bounded retained contextual source facts without project imports.

Reads local metadata/source files and writes only this directory's survey JSON.
Does not import torch, invoke models, train, read catalogs, or access the network.
"""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path('/home/barberb/lift_coding')
WT = ROOT / '.worktrees/contextual-legal-runtime-datasets-20261006'
OUT = ROOT / 'artifacts/contextual-legal-runtime-20261006/source-survey'
PREVIOUS = ROOT / 'artifacts/decoder-profile-recovery-20261006/asset-survey/contextual-state-custody-survey.json'
REPLAY = ROOT / 'artifacts/ir-semantic-reconstruction-replay-20261004/contextual384-768-v1'
NAMES = ('decoder_distillation_experiment', 'decoder_distillation_experiment_v2',
    'dimension_native_decoder_experiment', 'projected_source_decoder_experiment',
    'clause_source_decoder_experiment', 'action_factorized_clause_decoder_experiment',
    'ordered_clause_recurrent_decoder_experiment', 'decoder_cardinality_experiment',
    'shared_slot_source_decoder_experiment', 'source_value_decoder_experiment',
    'clause_source_context')


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


def pin(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError('bounded regular evidence file required: ' + str(path))
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    prior = json.loads(PREVIOUS.read_bytes())
    historical = json.loads((REPLAY / 'inference-result.json').read_bytes())
    historical_origins = {row['module']: row['origin'] for row in historical['project_module_origins']}
    original_paths = [Path(row['path']) for row in prior['file_pins_after']]
    original_before = [pin(path) for path in original_paths]
    closure = []
    for name in NAMES:
        module = 'ipfs_datasets_py.logic.formalization.autoencoder.' + name
        path = WT / (module.replace('.', '/') + '.py')
        tree = ast.parse(path.read_text())
        current = pin(path)
        closure.append({'module': module, 'current_pin': current,
            'historical_pin': historical_origins[module],
            'exact_historical_source_match': current['sha256'] == historical_origins[module]['sha256'],
            'relative_imports': [{'level': node.level, 'module': node.module,
                'names': [alias.name for alias in node.names]} for node in tree.body
                if isinstance(node, ast.ImportFrom) and node.level],
            'top_level_definitions': [{'name': node.name, 'line': node.lineno}
                for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]})
    broad_differences, broad_matches = [], 0
    for module, original in historical_origins.items():
        candidate = WT / (module.replace('.', '/') + '.py')
        if not candidate.exists():
            candidate = WT / module.replace('.', '/') / '__init__.py'
        current = pin(candidate) if candidate.exists() else None
        if current and current['sha256'] == original['sha256']:
            broad_matches += 1
        else:
            broad_differences.append({'module': module, 'historical_pin': original, 'current_pin': current,
                'required_by_minimal_numeric_runtime': False})
    lanes = []
    for lane in prior['lanes']:
        checkpoint = json.loads(Path(lane['original_checkpoint_pin']['path']).read_bytes())
        preprocessing = json.loads(Path(lane['exact_cached_file_pins']['original_preprocessing']['path']).read_bytes())
        source_rows = json.loads(Path(lane['exact_cached_file_pins']['source_only_inputs']['path']).read_bytes())
        contexts = json.loads(Path(lane['exact_cached_file_pins']['source_only_contexts']['path']).read_bytes())
        lanes.append({'dimension': lane['dimension'], 'original_checkpoint_pin': pin(lane['original_checkpoint_pin']['path']),
            'cached_file_pins': {key: pin(value['path']) for key, value in lane['exact_cached_file_pins'].items()},
            'selected_serialization_schema': checkpoint['schema'],
            'full_state_entry_count': len(checkpoint['model_state']),
            'selected_native_tensor_sha256': checkpoint['tensor_sha256'],
            'codec_sha256': hashlib.sha256(raw(checkpoint['codec'])).hexdigest(),
            'codec_schema': checkpoint['codec']['schema'],
            'codec_vocabulary_size': len(checkpoint['codec']['target_vocabulary']),
            'decoder_output_limit_tokens': 512, 'encoder_experiment_limit_tokens': 512,
            'source_only_row_count': len(source_rows),
            'source_only_row_keys': sorted({tuple(sorted(row)) for row in source_rows}),
            'contexts_sha256': hashlib.sha256(raw(contexts)).hexdigest(),
            'source_clause_occurrences': sum(len(value['segments']) for value in contexts.values()),
            'source_clause_slot_count': 8, 'source_mask_dtype': 'bool',
            'source_segmentation': 'literal_blank_line_exact_cache_text',
            'input_transform_sha256': hashlib.sha256(raw(checkpoint['input_transform'])).hexdigest(),
            'normalization_receipt_shas': {key: preprocessing[key]['receipt_sha256'] for key in
                ('paragraph_normalization', 'clause_normalization', 'count_prior')},
            'fitting_or_count_reference_rebuild_needed': False,
            'input_preprocessing_order': ['raw cached paragraph vector and real clause vectors',
                'saved original input_transform exactly once', 'zero-pad transformed clause vectors to8 and create bool mask',
                'frozen native identity residual projection',
                'saved separate paragraph/clause feature normalization inside decoder'],
            'observed_restricted_output_contract': lane['target_contract_observations'],
            'native_IR_schema_version': None, 'native_IR_profile_id': None,
            'new_generation_by_this_metadata_survey': False,
            'historical_replay_metrics': lane['historical_replay_metrics'],
            'runtime_authority': False})
    script_pin = pin(__file__)
    implementation = WT / 'ipfs_datasets_py/logic/formalization/autoencoder/contextual_legal_ir_numeric.py'
    before_impl = pin(implementation)
    original_after = [pin(path) for path in original_paths]
    donor = ROOT / 'artifacts/source-reconstruction-v2-20261001/run-01/legal_ir/raw_ce-1729-checkpoint.json'
    report = {'schema': 'contextual-legal-native-numeric-source-survey/v1',
        'completed': True, 'observed_at_utc': datetime.now(timezone.utc).isoformat(),
        'metadata_only_survey': True, 'torch_or_project_imported': False,
        'model_execution_by_this_script': False, 'optimizer_or_encoder_executed': False,
        'network_or_catalog_accessed': False, 'authority': False,
        'datasets_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=WT, text=True).strip(),
        'datasets_status_observation': subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=WT, text=True).splitlines(),
        'script_pin': script_pin, 'previous_custody_survey_pin': pin(PREVIOUS),
        'original_file_pins_before': original_before, 'original_file_pins_after': original_after,
        'original44_files_unchanged_this_survey': original_before == original_after,
        'original44_match_previous_survey': original_after == prior['file_pins_after'],
        'minimal_numeric_owner_count': len(closure), 'minimal_numeric_owners': closure,
        'all_minimal_owners_exact_historical_match': all(row['exact_historical_source_match'] for row in closure),
        'broad_historical_import_count': len(historical_origins),
        'broad_historical_exact_match_count': broad_matches, 'broad_historical_differences': broad_differences,
        'broad_source_closure_equivalence_claimed': False,
        'new_numeric_constructor_pin': before_impl,
        'new_numeric_constructor_unchanged_this_survey': before_impl == pin(implementation),
        'original_raw_donor_pin': pin(donor),
        'constructor_recipe': [
            'private original13-state raw384 Linear/Embedding/GRU geometry; saved donor codec/config/model_state only',
            'strict restore every donor tensor; verify original initializer donor tensor digest',
            'dimension_native.bind_dimension_native_body with saved seed1729 and exact initialization receipt',
            'persistent.bind_persistent_model conditioning every_step',
            'projected.bind_projected_source_model(saved paragraph normalization, saved count prior, guide_boundary true)',
            'clauses.bind_clause_source_model(saved clause normalization, head_seed1729)',
            'action.bind_action_factorized_clause_model', 'ordered.bind_ordered_clause_recurrent_model',
            'require exact saved architecture before full restore',
            'preflight complete32 typed state; explicitly validate nested native raw slice and frozen projections',
            'strict full32 restore; validate native tensor digest; eval-only inference'],
        'generation_chain': ['closed source-only rows + exact original descriptors',
            'original transform paragraphs; clause_source_context.batch_source_context for clauses/mask',
            'decoder_distillation_experiment._greedy -> model.project -> model.start -> model.next_logits -> argmax',
            'return actual raw token IDs, EOS/output-limit/invalid-special/deadline without repair'],
        'training_preparation_not_reused_reason': 'Historical load_context/prepare_lane/native_runner.prepare_dimension rebuilds training transforms, feature normalization and TRAIN label-derived count prior. Cached saved receipts replace all these preparation calls.',
        'historical_metrics_scope': 'Original authored regression48 rows per width; same cached source paragraph and ordered clause vectors, source segmentation and padding masks, output512. Not independent holdout, verbatim legal prose reconstruction, single paragraph-vector-only inference, or8192 qualification.',
        'native_schema_linkage_limit': 'Observed ordered rules array has actor/action/modality/object plus conditions/exceptions/temporal. Qualifiers are empty in this retained corpus. The separate Legal formula codec and CanonicalRoundTripIR helper do not declare a full native LegalIR schema/profile/version for these contextual states.',
        'lanes': lanes}
    target = OUT / 'source-survey.json'
    target.write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'path': str(target), 'sha256': pin(target)['sha256'],
        'minimal_owner_matches': report['all_minimal_owners_exact_historical_match'],
        'original44_unchanged': report['original44_files_unchanged_this_survey'],
        'previous44_match': report['original44_match_previous_survey'],
        'broad_matches': broad_matches, 'broad_count': len(historical_origins)}, sort_keys=True))


if __name__ == '__main__':
    main()
