"""Read-only historical receipt summary; no imports of producer/model code."""
from collections import defaultdict
from pathlib import Path
import hashlib
import json
import math

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[3]
PRIOR = BASE.parent / 'autoencoder-parallel-20260929'
OLDER = BASE.parent / 'autoencoder-optimizer-20260929'
def read(path):
    return json.loads(path.read_bytes())
def ref(path):
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

rows = []
stages = defaultdict(float)
qual = defaultdict(float)
for path in sorted((PRIOR / 'rechecked/progress/qualifications').glob('*/qualification.json')):
    q = read(path)
    worker_path = PRIOR / 'rechecked/progress/outputs' / path.parent.name / 'receipt.json'
    worker = read(worker_path)
    report = worker['training_report']
    epoch = report['epoch_reports'][0]
    training_row = next(row for row in q['rows'] if row['split'] == 'training')
    rows.append({
        'section': training_row['source']['section'], 'source_text': training_row['source']['text'],
        'qualified': q['qualified'], 'metric_gate': training_row['metric_gate'],
        'gates': q['gate_results'], 'accepted_epochs': report['accepted_epochs'],
        'selected_update': epoch['selected_update'], 'objective_delta': epoch['objective_delta'],
        'candidates': [{key: candidate.get(key) for key in (
            'update', 'accepted', 'objective_delta', 'pareto_regressions',
            'reconstruction_delta', 'cosine_similarity_delta')}
            for candidate in epoch['candidate_reports']],
        'worker': ref(worker_path), 'qualification': ref(path),
    })
    for name, value in report['projection_profile']['by_stage'].items():
        stages[name] += value['seconds']
    qual['whole_qualification_seconds'] += q['elapsed_seconds']
    for row in q['rows']:
        qual['model_embedding_seconds'] += row['model_evaluation_elapsed_seconds']
        qual['structural_seconds'] += row['structural_elapsed_seconds']
        qual['compile_decompile_seconds'] += row['semantic_gate']['compile_decompile_elapsed_seconds']
        for proof in row['lake_gate']['rows']:
            qual['actual_lake_build_seconds'] += proof['elapsed_seconds']
            qual['actual_lake_build_count'] += 1
qual['outside_rows_seconds'] = qual['whole_qualification_seconds'] - qual['model_embedding_seconds'] - qual['structural_seconds']
performance_path = PRIOR / 'native-performance-summary.json'
performance = read(performance_path)['runs']['rechecked']
report = {
    'schema': 'autoencoder-search-prior-evidence/v1',
    'admitted': False, 'formalized': False, 'constitution_formalized': False,
    'scope': 'Read-only analysis of prior sealed synthetic fixture receipts. No new training, import, Lake build, or database write.',
    'performance_receipt': ref(performance_path),
    'whole_route_seconds': 112.92320104409009,
    'dispatch_wall_seconds': performance['dispatch_wall_seconds_sum'],
    'outside_dispatch_and_qualification_seconds': performance['outside_dispatch_and_serial_qualification_wall_residual_seconds'],
    'qualification_phase_sums': dict(qual),
    'worker_training_profile_stage_sums': dict(stages),
    'phase_limits': [
        'Worker stage sums overlap in concurrent execution and are not whole-route elapsed time.',
        'Projection head seconds are nested inside projection batch seconds; do not add them.',
        'Structural seconds include Lake and compile/decompile seconds.',
        'The outside-rows residual includes checkpoint loading/replay and guards but has no finer sealed phase breakdown.',
    ],
    'rows': sorted(rows, key=lambda row: int(row['section'])),
    'exact_gate_thresholds': {'min_cosine': 0.72, 'max_reconstruction_loss': 0.20},
    'bridge_config': {'names': ['modal_frame_logic', 'deontic_norms', 'fol_tdfol', 'cec_dcec', 'external_prover_router'],
                      'evaluate_provers': False, 'metric_disk_cache': 0, 'parallel_workers': 1,
                      'use_sample_memory': False, 'first_evaluation_sample_count': 1,
                      'first_evaluation_target_count': 1, 'cold_processes': True, 'os_cache_controlled': False},
    'projection_explanation': {
        'source_at_assessment': ref(ROOT / 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py'),
        'method': 'AdaptiveModalAutoencoder._reconstruction_safe_projection',
        'initial_scale': 0.02, 'initial_rotation_scale': 0.10,
        'initial_even_dimension_cosine': 0.02 / math.sqrt(0.02**2 + 0.10**2),
        'behavior': 'A positive residual/update alignment can select the supplied target vector exactly. Nonpositive alignment can retain the initial rotated fallback.',
        'interpretation': 'Target-aware, discontinuous reconstruction metrics; not learned text generation or independent semantic generalization.',
        'criterion_change_proposed': False,
    },
    'optimization_claim_limits': {
        'global_minimum_certified': False,
        'global_minimum_speed_guaranteed': False,
        'reason': 'The supplied implementation has discontinuous target-aware projection, multiple weighted losses and strict Pareto guards; finite bounded search does not certify a global optimum.',
        'recommended_objective': 'Wall time to additional qualified candidates under unchanged gates, plus fixed-budget loss vectors and rejection reasons.',
        'tuning_row': '30-day duration fixture, repeatedly reused for candidate selection.',
        'heldout_canary': False,
        'untouched_canary_requirement': 'Reserve source/document-disjoint examples before tuning; keep them outside gradients and repeated selection; bind source/split/checkpoint provenance and evaluate finalists separately.',
    },
    'syntax_and_lean_coverage': {
        'source_at_assessment': ref(ROOT / 'ipfs_datasets_py/logic/autoformal/family_qualification.py'),
        'families': ['fol', 'deontic_fol', 'temporal_fol', 'deontic_temporal_fol', 'deontic_cognitive_event_calculus', 'frame_logic'],
        'qualification_fragment': 'canonical_atom_syntax_projection',
        'fol_tfol_omitted_facets': ['modality'],
        'temporal_operator_count_per_fixture': 0, 'event_calculus_atom_count_per_fixture': 0,
        'cognitive_operator_count_per_fixture': 0,
        'typed_duration_semantics': 'Parser-supplied minimum_duration or within_duration predicates remain distinct; no invented event time or temporal operator.',
        'lean_admit_command': ['lake', 'build', 'Legal'],
        'lean_scope': 'source_locked_numeric_pattern',
        'complete_legal_ir_proved': False,
    },
    'previous_fixed_gate_pilot_receipt': ref(PRIOR / 'modal-lazy-semantic-gates.json'),
    'prior_refinement_report': ref(ROOT / 'docs/implementation/reports/AUTOENCODER_OPTIMIZER_20260929.md'),
    'recommendations': [
        'Bound qualification subprocess concurrency under CPU/RAM/process reservations, retaining parent-only DuckDB ownership and source/proof checks.',
        'Skip provably useless refinement trials once a finite training reconstruction baseline is already at its exact nonnegative floor, without weakening acceptance.',
        'Compare baseline and improved three-attempt refinement on the same eight fixtures and exact protected seed, including passing, repaired and still-blocked rows.',
        'Report full-route wall and actual qualified count rather than accepted epochs alone.',
        'Use representative source-disjoint federal-law data and an untouched canary before generalization claims.',
    ],
}
output = BASE / 'prior-loss-and-phase-assessment.json'
with output.open('x') as stream:
    json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
    stream.write('\n')
print(json.dumps({'path': str(output), 'rows': len(rows), 'qualified': sum(row['qualified'] for row in rows)}))
