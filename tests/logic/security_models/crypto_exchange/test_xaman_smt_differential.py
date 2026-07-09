from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.compilers.to_smtlib import (
    SMTLIB_SCHEMA_VERSION,
    XAMAN_SMTLIB_QUERY_KIND,
    compile_ir_claims_to_smtlib,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import (
    calculate_artifact_cid,
    calculate_model_cid,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (
    SecurityModelIR,
    validate_ir,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.cvc5_runner import (
    CVC5Runner,
    XAMAN_DIFFERENTIAL_CLASSIFICATIONS,
    XAMAN_DIFFERENTIAL_SCHEMA_VERSION,
    run_xaman_smt_differential,
    run_z3_smtlib_artifact,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
MODEL_PATH = CORPUS_DIR / 'security-model-ir.json'
SMTLIB_DIR = CORPUS_DIR / 'smtlib'
SMTLIB_MANIFEST_PATH = SMTLIB_DIR / 'manifest.json'
DIFFERENTIAL_REPORT_PATH = CORPUS_DIR / 'proof-reports' / 'z3-cvc5-differential.json'


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding='utf-8'))


def _load_model() -> SecurityModelIR:
    return validate_ir(SecurityModelIR.from_untrusted_dict(_load_json(MODEL_PATH), strict=True))


def test_xaman_smtlib_manifest_attaches_all_blocking_and_high_claim_artifacts() -> None:
    model = _load_model()
    manifest = _load_json(SMTLIB_MANIFEST_PATH)
    artifacts = {
        artifact.claim_id: artifact
        for artifact in compile_ir_claims_to_smtlib(model)
    }
    critical_claim_ids = {
        claim['id']
        for claim in model.claims
        if claim.get('severity') in {'blocking', 'high'}
    }

    assert manifest['schema_version'] == SMTLIB_SCHEMA_VERSION
    assert manifest['task_id'] == 'PORTAL-CXTP-069'
    assert manifest['model_id'] == model.model_id
    assert manifest['model_cid'] == calculate_model_cid(model)
    assert manifest['query_kind'] == XAMAN_SMTLIB_QUERY_KIND
    assert manifest['logic'] == 'QF_LIA'
    assert manifest['artifact_count'] == 9
    assert set(artifacts) == critical_claim_ids
    assert {entry['claim_id'] for entry in manifest['artifacts']} == critical_claim_ids

    for entry in manifest['artifacts']:
        artifact = artifacts[entry['claim_id']]
        path = SMTLIB_DIR / entry['path']
        assert path.exists()
        assert path.read_text(encoding='utf-8') == artifact.smtlib
        assert entry['artifact_cid'] == artifact.artifact_cid
        assert entry['modeled'] is True
        assert entry['not_modeled_reason'] is None
        assert entry['logic'] == 'QF_LIA'
        assert entry['query_kind'] == XAMAN_SMTLIB_QUERY_KIND
        assert entry['blocking_assumption_ids']
        assert '(check-sat)' in artifact.smtlib


def test_xaman_smtlib_artifacts_run_with_z3_and_cvc5_without_disagreement() -> None:
    model = _load_model()
    cvc5 = CVC5Runner()

    for artifact in compile_ir_claims_to_smtlib(model):
        z3_result = run_z3_smtlib_artifact(artifact)
        cvc5_result = cvc5.run_smtlib_artifact(artifact)

        assert z3_result.solver_result == 'sat'
        assert cvc5_result.solver_result == 'sat'
        assert artifact.metadata['supported_theories'] == ['QF_LIA']


def test_xaman_z3_cvc5_differential_report_classifies_every_claim_fail_closed() -> None:
    model = _load_model()
    manifest = _load_json(SMTLIB_MANIFEST_PATH)
    report = _load_json(DIFFERENTIAL_REPORT_PATH)
    report_without_cid = dict(report)
    report_cid = report_without_cid.pop('report_cid')

    assert report['schema_version'] == XAMAN_DIFFERENTIAL_SCHEMA_VERSION
    assert report['task_id'] == 'PORTAL-CXTP-069'
    assert report['model_id'] == model.model_id
    assert report['model_cid'] == calculate_model_cid(model)
    assert report['classification_vocabulary'] == list(XAMAN_DIFFERENTIAL_CLASSIFICATIONS)
    assert report['selected_provers'] == ['z3', 'cvc5']
    assert report['smtlib_manifest_cid'] == calculate_artifact_cid(manifest)
    assert report_cid == calculate_artifact_cid(report_without_cid)

    summary = report['summary']
    assert summary == {
        'agreements': 9,
        'blocked': 9,
        'claim_count': 9,
        'critical_claim_count': 9,
        'disagreements': 0,
        'disproved': 0,
        'proved': 0,
        'release_ready': False,
        'unknown': 0,
        'unsupported_theory_rejections': 0,
    }
    assert report['unsupported_theory_rejections'] == []
    assert report['disagreement_rejections'] == []

    manifest_by_claim = {entry['claim_id']: entry for entry in manifest['artifacts']}
    for claim_report in report['claims']:
        claim_id = claim_report['claim_id']
        manifest_entry = manifest_by_claim[claim_id]
        assert claim_report['classification'] == 'blocked'
        assert claim_report['blocked_by_assumptions']
        assert claim_report['agreement'] is True
        assert claim_report['disagreement'] is False
        assert claim_report['unsupported_theory'] is False
        assert claim_report['smtlib_artifact']['artifact_cid'] == manifest_entry['artifact_cid']
        assert claim_report['smtlib_artifact']['logic'] == 'QF_LIA'
        assert claim_report['solver_results']['z3']['solver_result'] == 'sat'
        assert claim_report['solver_results']['cvc5']['solver_result'] == 'sat'


def test_xaman_differential_runner_reemits_equivalent_tmp_artifacts(tmp_path: Path) -> None:
    model = _load_model()
    report = run_xaman_smt_differential(
        model,
        smtlib_dir=tmp_path / 'smtlib',
        report_path=tmp_path / 'proof-reports' / 'z3-cvc5-differential.json',
    )

    assert report['summary']['claim_count'] == 9
    assert report['summary']['blocked'] == 9
    assert report['summary']['disagreements'] == 0
    assert report['summary']['unsupported_theory_rejections'] == 0
    assert (tmp_path / 'smtlib' / 'manifest.json').exists()
    assert (tmp_path / 'proof-reports' / 'z3-cvc5-differential.json').exists()
