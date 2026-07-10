import hashlib
import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import validate_ir


REPO_ROOT = Path(__file__).resolve().parents[4]
IR_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'security-model-ir.json'
CID_PATH = REPO_ROOT / 'security_ir_artifacts' / 'corpora' / 'xaman-app' / 'security-model-ir.cid'
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_security_model_ir.md'


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _canonical_cid(payload: dict[str, Any]) -> str:
    return 'sha256:' + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()


def test_xaman_security_model_ir_validates_against_schema() -> None:
    ir = _load_json(IR_PATH)
    validated = validate_ir(ir)

    assert validated.schema_version == 'security-model-ir/xaman/v1'
    assert validated.model_id == 'xaman-app-security-model-ir'
    assert validated.metadata['source']['commit_sha'] == '942f43876265a7af44f233288ad2b1d00841d5fa'


def test_xaman_security_model_ir_cid_is_deterministic() -> None:
    ir = _load_json(IR_PATH)
    cid = CID_PATH.read_text(encoding='utf-8').strip()

    assert cid == _canonical_cid(ir)
    assert cid.startswith('sha256:')


def test_xaman_security_model_ir_binds_required_artifacts_and_claims() -> None:
    ir = _load_json(IR_PATH)

    artifacts = ir['metadata']['bound_artifacts']
    assert {
        'source_manifest',
        'environment_probe',
        'wallet_auth_facts',
        'payload_lifecycle_facts',
        'xrpl_transaction_facts',
        'security_claims',
        'runtime_trace_report',
        'optional_solver_install_report',
    } <= set(artifacts)
    assert len(ir['claims']) >= 10
    assert {
        'xaman-claim:software-custody-requires-vault-authentication',
        'xaman-claim:payload-integrity-is-digest-checked-and-revalidated',
        'xaman-claim:runtime-equivalence-is-blocked-without-device-traces',
        'xaman-claim:proof-consumer-must-reject-non-proved-results',
    } <= {claim['id'] for claim in ir['claims']}


def test_xaman_security_model_ir_has_solver_obligations_and_disproof_vectors_for_every_claim() -> None:
    ir = _load_json(IR_PATH)
    claim_ids = {claim['id'] for claim in ir['claims']}
    obligation_claims = {obligation['claim_id'] for obligation in ir['proof_obligations']}
    disproof_claims = {vector['claim_id'] for vector in ir['disproof_vectors']}

    assert claim_ids <= obligation_claims
    assert claim_ids <= disproof_claims
    assert {'z3', 'cvc5', 'lean', 'tla', 'tamarin', 'proverif', 'coq'} <= set(ir['prover_targets'])
    assert all(obligation['status'] in {'UNKNOWN', 'NOT_MODELED'} for obligation in ir['proof_obligations'])


def test_xaman_security_model_ir_keeps_runtime_and_release_blocked() -> None:
    ir = _load_json(IR_PATH)

    assert ir['metadata']['security_decision'] == 'BLOCK_SECURITY_CLAIMS_PENDING_PROOFS_AND_ASSUMPTIONS'
    assert ir['metadata']['production_release_blocked'] is True
    assert any(trace['conformance_status'] == 'blocked' for trace in ir['runtime_traces'])
    assert any(result['result'] == 'unknown' for result in ir['solver_results'])


def test_xaman_security_model_ir_document_covers_cid_and_boundaries() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-068' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/security-model-ir.json' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/security-model-ir.cid' in doc
    assert 'BLOCK_SECURITY_CLAIMS_PENDING_PROOFS_AND_ASSUMPTIONS' in doc
