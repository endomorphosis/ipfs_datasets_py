"""Legacy frontend diagnostics preserve wrapped native command failures."""
import sys

import pytest

from ipfs_datasets_py.logic.hammers.frontends import base
from ipfs_datasets_py.logic.hammers.process_lifecycle import ProcessSupervisor


@pytest.fixture
def supervised(tmp_path, monkeypatch):
    with ProcessSupervisor(state_directory=tmp_path / 'processes', recover=False) as supervisor:
        monkeypatch.setattr(base, 'get_process_supervisor', lambda: supervisor)
        yield supervisor
        assert supervisor.active_process_count == 0
        assert not list(supervisor.manifest_directory.glob('*.json'))


def test_missing_command_wrapped_by_prlimit_retains_failure_diagnostic(supervised):
    result = base.run_bounded_process(['this-native-command-is-missing-ipfs-test'], timeout=2)
    assert result.error
    if sys.platform.startswith('linux'):
        assert result.returncode == 127
        assert 'native invocation failed (exit 127)' in result.error
        assert 'this-native-command-is-missing-ipfs-test' in result.stderr


@pytest.mark.parametrize('exit_code', [126, 127])
def test_intentional_native_failure_is_not_misreported_as_missing_command(supervised, exit_code):
    result = base.run_bounded_process([sys.executable, '-c',
        f"import sys; print('intentional failure', file=sys.stderr); sys.exit({exit_code})"], timeout=2)
    assert result.returncode == exit_code and result.stderr == 'intentional failure\n'
    assert result.error.startswith(f'native invocation failed (exit {exit_code}):')
    assert 'not found' not in result.error and 'missing' not in result.error


def test_goal_diagnostic_exit_one_remains_available_to_frontend_parser(supervised):
    result = base.run_bounded_process([sys.executable, '-c',
        "import sys; print('native placeholder diagnostic'); sys.exit(1)"], timeout=2)
    assert result.returncode == 1 and result.stdout == 'native placeholder diagnostic\n'
    assert result.error is None
