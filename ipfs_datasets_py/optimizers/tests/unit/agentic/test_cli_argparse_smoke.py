"""
Smoke tests for OptimizerArgparseCLI agentic CLI interface.
Covers optimize --dry-run, validate, config show.
"""
import json
from ipfs_datasets_py.optimizers.agentic.cli import OptimizerArgparseCLI


def test_argparse_cli_optimize_dry_run(tmp_path, monkeypatch):
    """Smoke test: optimize --dry-run exits 0."""
    target_file = tmp_path / "target.py"
    target_file.write_text("# Python code to optimize\nprint('hello')\n")
    
    cli = OptimizerArgparseCLI()
    
    captured_lines = []
    monkeypatch.setattr('builtins.print', lambda *a, **kw: captured_lines.append(' '.join(map(str, a))))
    
    argv = [
        'optimize',
        '--target', str(target_file),
        '--description', 'smoke test optimization',
        '--dry-run'
    ]
    exit_code = cli.run(argv)
    assert exit_code == 0
    assert any('dry-run' in line.lower() or 'dry run' in line.lower() for line in captured_lines)


def test_argparse_cli_validate_missing_file(tmp_path):
    """Smoke test: validate with missing file exits non-zero."""
    cli = OptimizerArgparseCLI()
    
    argv = [
        'validate',
        str(tmp_path / 'nonexistent.py')
    ]
    exit_code = cli.run(argv)
    assert exit_code != 0


def test_argparse_cli_config_show(tmp_path, monkeypatch):
    """Smoke test: config show displays configuration."""
    cli = OptimizerArgparseCLI()
    
    captured_lines = []
    def capture_print(*args_print, **kwargs):
        captured_lines.append(' '.join(map(str, args_print)))
    
    monkeypatch.setattr('builtins.print', capture_print)
    
    argv = ['config', 'show']
    exit_code = cli.run(argv)
    assert exit_code == 0
    
    # Config show should print some configuration information
    assert len(captured_lines) > 0
