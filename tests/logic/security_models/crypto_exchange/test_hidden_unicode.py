import subprocess
import sys
import json
from pathlib import Path

from scripts.ops.security_verification.check_no_hidden_unicode import (
    _iter_files,
    build_report,
    file_byte_diagnostics,
    file_line_count,
    must_be_multiline,
    scan_file,
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
        if must_be_multiline(path):
            line_count = file_line_count(path.read_text(encoding='utf-8'))
            assert line_count > 1, f'{path}: expected ordinary physical newlines, got {diagnostics}'


def test_hidden_unicode_check_fails_closed_on_single_line_source_file(tmp_path: Path) -> None:
    candidate = tmp_path / 'single_line.py'
    candidate.write_text('print("security")', encoding='utf-8')
    errors = scan_file(candidate)
    assert any(error['category'] == 'single_line_file' for error in errors)
    assert any(error['message'] == 'expected ordinary physical newlines, found a single logical line' for error in errors)


def test_hidden_unicode_check_rejects_carriage_return_bytes(tmp_path: Path) -> None:
    candidate = tmp_path / 'carriage_return.py'
    candidate.write_bytes(b'print("security")\rprint("verification")\r')
    errors = scan_file(candidate)
    assert any(error['category'] == 'carriage_return' for error in errors)
    assert [error['byte_offset'] for error in errors if error['category'] == 'carriage_return'] == [17, 39]


def test_hidden_unicode_check_emits_machine_readable_report(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[4]
    script = repo_root / 'scripts/ops/security_verification/check_no_hidden_unicode.py'
    report_path = tmp_path / 'hidden_unicode_report.json'
    result = subprocess.run(
        [sys.executable, str(script), '--verbose', '--report', str(report_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding='utf-8'))
    assert payload == build_report()
    assert payload['violations'] == []
