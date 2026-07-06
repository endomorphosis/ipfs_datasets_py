import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors import TypeScriptSchemaEmitter
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.examples import example_minimal_exchange_model


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / 'pytest.ini').exists():
            return candidate
    raise RuntimeError('repository root not found')


REPO_ROOT = _repo_root()
TEST_VECTOR_DIR = REPO_ROOT / 'docs' / 'security_verification' / 'test_vectors'
EMITTER_SCRIPT = REPO_ROOT / 'scripts' / 'ops' / 'security_verification' / 'emit_security_typescript_schema.py'
MIN_SCHEMA_NEWLINE_COUNT = 2


def _hermetic_env() -> dict[str, str]:
    """Return the env that disables auto-installs and keeps imports local to this test repo."""
    env = os.environ.copy()
    env.setdefault('PYTHONPATH', str(REPO_ROOT))
    env['IPFS_DATASETS_PY_MINIMAL_IMPORTS'] = '1'
    env['IPFS_DATASETS_AUTO_INSTALL'] = '0'
    env['IPFS_KIT_AUTO_INSTALL_DEPS'] = '0'
    return env


def _expected_schema_text() -> str:
    """Return the newline-normalized example schema text expected from the CLI emitter."""
    rendered = TypeScriptSchemaEmitter().emit_schema(example_minimal_exchange_model())
    return rendered if rendered.endswith('\n') else rendered + '\n'


def _compile_typescript_schema(tmp_path: Path, *, via_cli: bool = False) -> tuple[str, str, Path]:
    node = shutil.which('node')
    tsc = shutil.which('tsc') or shutil.which('npx')
    if not node or not tsc:
        pytest.skip('node and tsc/npx are not available')
    schema_path = tmp_path / 'security_schema.ts'
    if via_cli:
        subprocess.run(
            [sys.executable, str(EMITTER_SCRIPT), '--example', '--out', str(schema_path)],
            cwd=REPO_ROOT,
            env=_hermetic_env(),
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        schema_path.write_text(TypeScriptSchemaEmitter().emit_schema(example_minimal_exchange_model()), encoding='utf-8')
    schema_text = schema_path.read_text(encoding='utf-8')
    assert schema_text.count('\n') >= MIN_SCHEMA_NEWLINE_COUNT
    assert 'export interface SecurityModelIR {' in schema_text
    assert 'export function verifyProofReceipt(' in schema_text
    if via_cli:
        assert schema_text == _expected_schema_text()
    (tmp_path / 'tsconfig.json').write_text(
        json.dumps(
            {
                'compilerOptions': {
                    'strict': True,
                    'target': 'ES2020',
                    'module': 'CommonJS',
                    'outDir': 'dist',
                },
                'files': ['security_schema.ts'],
            }
        ),
        encoding='utf-8',
    )
    command = [tsc, 'tsc', '--project', str(tmp_path / 'tsconfig.json')] if tsc.endswith('npx') else [tsc, '--project', str(tmp_path / 'tsconfig.json')]
    subprocess.run(command, cwd=tmp_path, check=True, capture_output=True, text=True)
    return node, tsc, tmp_path / 'dist' / 'security_schema.js'


def test_typescript_schema_compiles_when_tsc_is_available(tmp_path: Path) -> None:
    _, _, compiled = _compile_typescript_schema(tmp_path)
    assert compiled.exists()


def test_typescript_schema_cli_emitter_outputs_strict_compilable_module(tmp_path: Path) -> None:
    _, _, compiled = _compile_typescript_schema(tmp_path, via_cli=True)
    assert compiled.exists()


def test_typescript_runtime_verifier_rejects_bad_receipts_and_accepts_valid_fixture(tmp_path: Path) -> None:
    node, _, compiled = _compile_typescript_schema(tmp_path)
    report_payload = json.loads((TEST_VECTOR_DIR / 'proof_report_minimal.json').read_text(encoding='utf-8'))
    receipt_payload = {
        'schema_version': 'proof-receipt/v1',
        'report_schema_version': report_payload['schema_version'],
        'claim_id': report_payload['claim_id'],
        'model_cid': report_payload['model_cid'],
        'proof_report_cid': report_payload['nondeterministic_report_cid'],
        'accepted_assumptions': list(report_payload['assumptions']),
        'verifier': 'ts-wasm-kernel',
        'verifier_version': '0.1.0',
        'valid': True,
        'metadata': {},
    }
    script_path = tmp_path / 'verify.js'
    script_path.write_text(
        f"""
const schema = require({json.dumps(str(compiled))});
const report = {json.dumps(report_payload)};
const validReceipt = {json.dumps(receipt_payload)};
const unknownReport = {{ ...report, status: "UNKNOWN" }};
const disprovedReport = {{ ...report, status: "DISPROVED" }};
const notModeledReport = {{ ...report, status: "NOT_MODELED" }};
const missingAssumptionReceipt = {{ ...validReceipt, accepted_assumptions: [] }};
const mismatchedModelReceipt = {{ ...validReceipt, model_cid: "sha256:wrong" }};
const mismatchedClaimReceipt = {{ ...validReceipt, claim_id: "claim:wrong" }};
const mismatchedCidReceipt = {{ ...validReceipt, proof_report_cid: "sha256:wrong" }};
if (!schema.validateProofReportStrict(report)) {{
  throw new Error("expected strict report validation to pass");
}}
if (!schema.validateProofReceiptStrict(validReceipt)) {{
  throw new Error("expected strict receipt validation to pass");
}}
if (schema.verifyProofReceipt(validReceipt, unknownReport)) {{
  throw new Error("expected UNKNOWN report rejection");
}}
if (schema.verifyProofReceipt(validReceipt, disprovedReport)) {{
  throw new Error("expected DISPROVED report rejection");
}}
if (schema.verifyProofReceipt(validReceipt, notModeledReport)) {{
  throw new Error("expected NOT_MODELED report rejection");
}}
if (schema.verifyProofReceipt(missingAssumptionReceipt, report)) {{
  throw new Error("expected missing assumption rejection");
}}
if (schema.verifyProofReceipt(mismatchedModelReceipt, report)) {{
  throw new Error("expected mismatched model rejection");
}}
if (schema.verifyProofReceipt(mismatchedClaimReceipt, report)) {{
  throw new Error("expected mismatched claim rejection");
}}
if (schema.verifyProofReceipt(mismatchedCidReceipt, report)) {{
  throw new Error("expected mismatched cid rejection");
}}
if (!schema.verifyProofReceipt(validReceipt, report, {{ expectedModelCid: report.model_cid, expectedClaimId: report.claim_id }})) {{
  throw new Error("expected valid receipt acceptance");
}}
if (schema.verifyProofReceipt(validReceipt, report, {{ mode: "proof_critical" }})) {{
  throw new Error("expected proof critical verification to fail closed");
}}
""",
        encoding='utf-8',
    )
    subprocess.run([node, str(script_path)], cwd=tmp_path, check=True, capture_output=True, text=True)
