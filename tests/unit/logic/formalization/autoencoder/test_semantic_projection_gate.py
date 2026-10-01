"""Source replay and live-authority boundaries of the additive semantic gate.

Backend doubles test control flow only. The release runner separately records
real Lake/SANY builds and numerical training against the same frozen sources.
"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v5 as targets
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v3 as gate
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v2 as old_gate
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v3 as policy
from ipfs_datasets_py.logic.formalization.autoencoder import projection_validation_contract_v2 as old_policy
from ipfs_datasets_py.logic.formalization.autoencoder.native_formula_evidence import NativeFormulaEvidence
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRule, CanonicalRoundTripIR
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v3 as trainer

FORMULAS = {
    'FOL': 'forall x. Person(x) -> Reports(x)', 'DFOL': 'forall x. O(Reports(x))',
    'TFOL': 'forall x. □(Reports(x))', 'TDFOL': 'forall x. O(□(Reports(x)))',
    'CEC': 'K(Officer,Happens(Submit,Time))', 'DCEC': 'O(K(Officer,Happens(Submit,Time)))',
    'frame_logic': 'alice[role -> officer].', 'propositional': 'p and q',
}


def fixture(index=0, **options):
    inputs = {'document': CanonicalRoundTripIR((CanonicalRule('O', 'agency'+str(index), 'submit', 'record'+str(index)),)),
              'source_text': 'Authored semantic gate fixture '+str(index)+'.'}
    source = targets.supplemental_source_ref('legal_ir', **inputs)
    inputs['formula_inputs'] = [NativeFormulaEvidence(k, v, source) for k, v in FORMULAS.items()]
    return inputs, targets.prepare_family_training_targets_v5('legal_ir', **inputs, **options)


@pytest.fixture
def backend_double(monkeypatch, tmp_path):
    control = SimpleNamespace(calls=[], fail=False)
    class RuntimeDouble:
        def run(self, request):
            probe = request.argv[-1] == '--version'
            if not probe:
                control.calls.append(request.argv[-1])
            passed = probe or not control.fail
            return SimpleNamespace(ok=passed,
                stdout='Lean version 4.30.0\n' if probe else 'unit_dependency_double_no_native_execution\n',
                stderr='', output_truncated=False, workspace_limit_exceeded=False,
                returncode=0 if passed else 1, timed_out=False)
    tool = tmp_path / 'unit-only-tool'
    tool.write_text('Only hashed; RuntimeDouble never executes this file.\n')
    tool.chmod(0o700)
    control.executable = str(tool)
    monkeypatch.setattr(gate, 'BoundedToolRunner', RuntimeDouble)
    return control


def observe(inputs, report, backend):
    execution = gate.build_native_family_lake(report, source_inputs=inputs, lake_executable=backend.executable)
    present = {r['logic_family'] for r in report['projections']}
    reviews = [{'family_id': f, 'source_digest': report['source_digest'], 'disposition': 'inapplicable',
                'reason': 'Closed authored unit fixture supplies only these native declarations.',
                'evidence_refs': ['unit:authored-semantic-gate']}
               for f in policy.domain_projection_policy('legal_ir')['family_inventory'] if f not in present]
    return execution, policy.validate_projection_report(report, lake_execution=execution, applicability_review=reviews)


def test_all_nine_targets_keep_exact_source_binding_and_live_gate(backend_double):
    inputs, report = fixture()
    handle, observation = observe(inputs, report, backend_double)
    assert len(handle.to_dict()['per_projection']) == 9
    result = policy.require_projection_training_batch([observation], domain_id='legal_ir', target_reports=[report])
    assert result['strict_training_allowed'] and backend_double.calls == ['LegalIR']
    assert all(result[key] is False for key in policy._FALSE)


def test_rehashed_changed_formula_cannot_skip_source_replay(backend_double):
    inputs, report = fixture()
    altered = deepcopy(report)
    row = next(r for r in altered['projections'] if r['projection_id'].endswith('/FOL/v3'))
    row['payload']['formula'] = 'Fabricated(a)'
    row['target_sha256'] = targets.core._sha({k: v for k, v in row.items() if k != 'target_sha256'})
    altered['report_sha256'] = targets.core._sha({k: v for k, v in altered.items() if k != 'report_sha256'})
    with pytest.raises(ValueError):
        gate.build_native_family_lake(altered, source_inputs=inputs, lake_executable=backend_double.executable)
    assert backend_double.calls == []


def test_old_and_archived_execution_objects_cannot_authorize_new_gate(backend_double):
    inputs, report = fixture()
    handle, _ = observe(inputs, report, backend_double)
    for item in (handle.to_dict(), old_gate.NativeFamilyLakeExecution(), gate.NativeFamilyLakeExecution()):
        with pytest.raises(ValueError, match='live issued'):
            gate.verify_native_family_lake(item, report)


def test_old_or_serialized_observations_stop_before_optimizer(backend_double, tmp_path):
    inputs, report = fixture()
    _, observation = observe(inputs, report, backend_double)
    old = old_policy.ProjectionValidationObservation(b'{}')
    for candidate in (old, observation.to_dict()):
        with pytest.raises(ValueError, match='live validation observations'):
            trainer.train_validated_family_projection_autoencoder([candidate], [candidate],
                domain_id='legal_ir', output_dir=tmp_path/'never')
    assert not (tmp_path/'never').exists()


def test_narrow_request_still_cannot_satisfy_complete_policy(backend_double):
    inputs, report = fixture(requested_families=['first_order'])
    handle, observation = observe(inputs, report, backend_double)
    assert handle.to_dict()['per_projection'][0]['lake_status'] == 'passed'
    result = policy.evaluate_projection_training_batch([observation], domain_id='legal_ir', target_reports=[report])
    assert not result['strict_training_allowed']
    assert not observation.to_dict()['full_request_scope']


def test_build_failure_remains_blocking_after_successful_lowering(backend_double, tmp_path):
    inputs, report = fixture()
    backend_double.fail = True
    _, observation = observe(inputs, report, backend_double)
    with pytest.raises(policy.ProjectionValidationError):
        trainer.train_validated_family_projection_autoencoder([observation], [observation],
            domain_id='legal_ir', output_dir=tmp_path/'never')
    assert not (tmp_path/'never').exists()
