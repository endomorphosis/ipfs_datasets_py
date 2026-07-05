from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import SecurityIRFeatureLoopProjector
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model


def test_feature_loop_projector_projects_example_model() -> None:
    """GIVEN the example model WHEN projected THEN Codex-facing proof features stay explicit."""

    payload = SecurityIRFeatureLoopProjector().project_model(example_minimal_exchange_model())

    assert payload['projection_kind'] == 'security-ir-feature-loop/v1'
    assert payload['model_id'] == 'minimal-btc-exchange'
    assert payload['model_cid']
    assert payload['features']['assumption_ids'] == [f'A{index}' for index in range(1, 11)]
    assert payload['features']['critical_events'] == ['withdrawal_broadcast']
    assert payload['codex_program_synthesis']['scope'] == 'security_ir_autoformalization'
    assert any(claim['claim_id'] == 'no_unauthorized_withdrawal' for claim in payload['codex_program_synthesis']['claims'])


def test_feature_loop_projector_autoformalizes_source_paths_before_projection(tmp_path: Path) -> None:
    """GIVEN a supported code path WHEN projected THEN autoformalized review gaps and policies are preserved."""

    source_path = tmp_path / 'withdrawals.ts'
    source_path.write_text(
        '''
/** Every withdrawal must be authorized before broadcast. */
export function approveWithdrawal(authorized: boolean): boolean {
  if (!authorized) {
    throw new Error("authorization required");
  }
  return true;
}
''',
        encoding='utf-8',
    )

    payload = SecurityIRFeatureLoopProjector().project_path(source_path, model_id='projected-typescript-model')

    assert payload['model_id'] == 'projected-typescript-model'
    assert payload['features']['languages'] == ['typescript']
    assert payload['features']['policy_names'] == ['authorization_required']
    assert payload['features']['source_inputs'] == [str(source_path)]
    assert payload['codex_program_synthesis']['review_status'] == 'seed-autoformalization'
    assert payload['codex_program_synthesis']['review_gaps']
