import subprocess
import sys
from pathlib import Path

from scripts.ops.security_verification.check_no_hidden_unicode import (
    _iter_files,
    file_byte_diagnostics,
    file_line_count,
    requires_multiple_physical_lines,
)


def test_hidden_unicode_check_passes() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    script = repo_root / 'scripts/ops/security_verification/check_no_hidden_unicode.py'
    result = subprocess.run([sys.executable, str(script)], cwd=repo_root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_security_verification_files_have_real_lf_newlines() -> None:
    for path in _iter_files():
        diagnostics = file_byte_diagnostics(path)
        assert diagnostics['cr'] == 0, f'{path}: unexpected CR bytes, got {diagnostics}'
        assert diagnostics['u2028'] == 0, f'{path}: unexpected U+2028, got {diagnostics}'
        assert diagnostics['u2029'] == 0, f'{path}: unexpected U+2029, got {diagnostics}'
        if requires_multiple_physical_lines(path):
            line_count = file_line_count(path.read_text(encoding='utf-8'))
            assert line_count > 1, f'{path}: expected ordinary physical newlines, got {diagnostics}'
