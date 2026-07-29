import importlib.util
import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    ROOT_DIR
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'run_security_ir_disproof_suite.py'
)
VECTOR_DIR = (
    ROOT_DIR
    / 'docs'
    / 'security_verification'
    / 'test_vectors'
    / 'counterexamples'
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'run_security_ir_disproof_suite',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load disproof suite script')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_vectors(directory: Path) -> dict[tuple[str, str], dict[str, object]]:
    vectors: dict[tuple[str, str], dict[str, object]] = {}
    for path in sorted(directory.glob('*.json')):
        payload = json.loads(path.read_text(encoding='utf-8'))
        key = (str(payload['scenario']), str(payload['claim_id']))
        vectors[key] = payload
    return vectors


def test_checked_in_counterexample_vectors_match_default_disproof_suite(
    tmp_path: Path,
) -> None:
    """GIVEN checked-in counterexample vectors WHEN the disproof suite runs.

    THEN the same named scenarios and claims are still rejected.
    """

    module = _load_script_module()
    output_path = tmp_path / 'disproof-report.json'
    generated_dir = tmp_path / 'counterexamples'

    assert (
        module.main(
            [
                '--example',
                '--out',
                str(output_path),
                '--emit-counterexamples-dir',
                str(generated_dir),
            ]
        )
        == 0
    )

    checked_in = _load_vectors(VECTOR_DIR)
    generated = _load_vectors(generated_dir)
    assert checked_in
    assert checked_in.keys() == generated.keys()

    required_pairs = {
        ('multi_chain_conservation_gap', 'global_asset_conservation'),
        ('mempool_replacement_gap', 'no_unauthorized_withdrawal'),
        ('partial_rollback_deposit_gap', 'no_deposit_before_finality'),
        ('rpc_censorship_finality_gap', 'no_deposit_before_finality'),
    }
    assert required_pairs.issubset(checked_in.keys())

    for key, vector in checked_in.items():
        generated_vector = generated[key]
        assert vector['schema_version'] == 'crypto-exchange-counterexample-vector/v1'
        assert vector['status'] == 'DISPROVED'
        assert isinstance(vector['counterexample'], dict)
        assert vector['proof_or_trace_cid'] == generated_vector['proof_or_trace_cid']
        assert vector['matched_claims'] == generated_vector['matched_claims']
