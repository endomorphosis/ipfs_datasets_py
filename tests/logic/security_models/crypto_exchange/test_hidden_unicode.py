import subprocess
import sys
from pathlib import Path

from scripts.ops.security_verification.check_no_hidden_unicode import file_byte_diagnostics


def test_hidden_unicode_check_passes() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    script = repo_root / 'scripts/ops/security_verification/check_no_hidden_unicode.py'
    result = subprocess.run([sys.executable, str(script)], cwd=repo_root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_security_verification_files_have_real_lf_newlines() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    for relative_path in (
        '.github/workflows/security-logic-ci.yml',
        'scripts/ops/security_verification/check_no_hidden_unicode.py',
        'ipfs_datasets_py/logic/security_models/crypto_exchange/extractors/typescript_schema.py',
        'ipfs_datasets_py/logic/security_models/crypto_exchange/reports/proof_report.py',
        'ipfs_datasets_py/logic/security_models/crypto_exchange/prove_all.py',
        'tests/logic/security_models/crypto_exchange/test_security_artifact_e2e.py',
        'tests/logic/security_models/crypto_exchange/test_typescript_schema_compiles.py',
    ):
        diagnostics = file_byte_diagnostics(repo_root / relative_path)
        assert diagnostics['lf'] > 5, f'{relative_path}: expected physical LF newlines, got {diagnostics}'
        assert diagnostics['cr'] == 0, f'{relative_path}: unexpected CR bytes, got {diagnostics}'
        assert diagnostics['u2028'] == 0, f'{relative_path}: unexpected U+2028, got {diagnostics}'
        assert diagnostics['u2029'] == 0, f'{relative_path}: unexpected U+2029, got {diagnostics}'
