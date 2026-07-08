import importlib.util
import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model


SCRIPT_PATH = (
    Path(__file__).resolve().parents[4]
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'audit_security_ir_coverage.py'
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'audit_security_ir_coverage',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load coverage audit script')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _claim_report(claim_id: str, *, risk: str = 'blocking', evidence_refs=None) -> dict[str, object]:
    return {
        'claim_id': claim_id,
        'domain': 'test',
        'status': 'PROVED',
        'risk': risk,
        'assumptions': ['A4'],
        'evidence_refs': list(evidence_refs or []),
        'soundness_notes': [],
    }


def test_example_matrix_reports_all_required_domains() -> None:
    module = _load_script_module()
    model = example_minimal_exchange_model()
    matrix = module.build_coverage_matrix(
        model,
        [
            _claim_report(
                'no_unauthorized_withdrawal',
                evidence_refs=[
                    {
                        'kind': 'test_fixture',
                        'path': 'fixture.py',
                        'review_status': 'trusted_fixture',
                    }
                ],
            )
        ],
        generated_at='2026-07-08T00:00:00Z',
    )

    assert matrix['schema_version'] == 'code-to-ir-coverage/v1'
    assert matrix['release_ready'] is True
    for domain in (
        'wallets',
        'withdrawals',
        'deposits',
        'ledger',
        'capabilities',
        'hsm',
        'audit',
        'assumptions',
        'evidence_refs',
    ):
        assert domain in matrix['domains']
        assert matrix['domains'][domain]['modeled'] is True
    assert matrix['domains']['withdrawals']['claim_ids'] == ['no_unauthorized_withdrawal']
    assert matrix['evidence_refs']['by_review_status']['trusted_fixture'] >= 1
    assert matrix['assumptions']['release_ready'] is True


def test_blocking_or_high_claim_without_reviewed_evidence_fails_closed() -> None:
    module = _load_script_module()
    matrix = module.build_coverage_matrix(
        example_minimal_exchange_model(),
        [
            _claim_report(
                'no_unauthorized_withdrawal',
                evidence_refs=[
                    {
                        'kind': 'source_code',
                        'path': 'wallet.py',
                        'review_status': 'machine_extracted',
                    }
                ],
            ),
            _claim_report('no_deposit_before_finality', risk='high', evidence_refs=[]),
        ],
    )

    assert matrix['release_ready'] is False
    assert {failure['claim_id'] for failure in matrix['failures']} == {
        'no_unauthorized_withdrawal',
        'no_deposit_before_finality',
    }
    assert all('reviewed source, runtime, or policy evidence path' in failure['reason'] for failure in matrix['failures'])


def test_high_claim_with_human_reviewed_policy_evidence_passes() -> None:
    module = _load_script_module()
    matrix = module.build_coverage_matrix(
        example_minimal_exchange_model(),
        [
            _claim_report(
                'no_deposit_before_finality',
                risk='high',
                evidence_refs=[
                    {
                        'kind': 'policy_doc',
                        'path': 'docs/security_verification/deposit_policy.md',
                        'review_status': 'human_reviewed',
                    }
                ],
            )
        ],
    )

    assert matrix['release_ready'] is True
    claim = matrix['claims'][0]
    assert claim['evidence_path_status']['has_reviewed_policy'] is True


def test_medium_claim_does_not_fail_without_reviewed_path() -> None:
    module = _load_script_module()
    matrix = module.build_coverage_matrix(
        example_minimal_exchange_model(),
        [_claim_report('audit_event_exists_for_critical_transition', risk='medium', evidence_refs=[])],
    )

    assert matrix['release_ready'] is True
    assert matrix['failures'] == []


def test_cli_writes_json_and_markdown_outputs(tmp_path: Path, monkeypatch) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'code-to-ir-coverage.json'
    markdown_path = tmp_path / 'code_to_ir_evidence_matrix.md'

    monkeypatch.setattr(
        module,
        '_prove_reports',
        lambda model: [
            _claim_report(
                'no_unauthorized_withdrawal',
                evidence_refs=[
                    {
                        'kind': 'source_code',
                        'path': 'wallet.py',
                        'review_status': 'human_reviewed',
                    }
                ],
            )
        ],
    )

    assert module.main(['--example', '--out', str(out_path), '--markdown-out', str(markdown_path)]) == 0
    payload = json.loads(out_path.read_text(encoding='utf-8'))
    assert payload['release_ready'] is True
    assert payload['domains']['wallets']['modeled'] is True
    markdown = markdown_path.read_text(encoding='utf-8')
    assert '# Code-to-IR Evidence Coverage Matrix' in markdown
    assert '| `no_unauthorized_withdrawal` | `withdrawals` | `blocking` | `PROVED` |' in markdown
