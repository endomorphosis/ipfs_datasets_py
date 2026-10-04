"""Default setup routes through bounded admission and preserves failure state."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.external_provers import isabelle_setup as setup
from ipfs_datasets_py.logic.backends.installers import isabelle_preparation as preparation


def receipt(*, usable=True, smoke=False):
    observation = {"returncode": 0, "command": ["/installed/Isabelle2025-2/bin/isabelle"],
                   "stdout": "checked fixed smoke", "error": ""}
    evidence = {"native_runtime": {"executable": "/installed/Isabelle2025-2/bin/isabelle",
                                   "version": "Isabelle2025-2"},
        "probes": [{"phase": "smoke", "observation": observation}] if smoke else [],
        "grants_proof_authority": False}
    return SimpleNamespace(usable=usable, command_available=True,
        smoke_accepted=usable and smoke, readiness_level="kernel_smoke" if smoke else "command",
        reason_code="observed" if usable else "isabelle_runtime_identity_changed", to_dict=lambda: evidence)


@pytest.mark.parametrize('smoke', [False, True])
def test_default_setup_uses_one_bounded_preparation_and_requested_total_timeout(monkeypatch, smoke):
    calls = []
    monkeypatch.setattr(preparation, 'prepare_isabelle_runtime',
        lambda **kwargs: calls.append(kwargs) or receipt(smoke=smoke))
    from ipfs_datasets_py.logic.hammers.frontends import base
    monkeypatch.setattr(base, 'run_bounded_process', lambda *a, **kw: pytest.fail('legacy process bypass'))
    result = setup.ensure_isabelle_ready(smoke=smoke, timeout=1.25, install_root='/installed')
    assert result['ready'] and result['installation'] is None
    assert calls == [{'mode': 'smoke' if smoke else 'command', 'timeout_seconds': 1.25,
                      'install_root': '/installed', 'executable': None}]
    assert result['capability']['executables']['isabelle']['path'] == '/installed/Isabelle2025-2/bin/isabelle'
    assert result['bounded_preparation']['grants_proof_authority'] is False


@pytest.mark.parametrize('smoke', [False, True])
def test_late_failure_does_not_promote_historical_command_or_smoke_success(monkeypatch, smoke):
    monkeypatch.setattr(preparation, 'prepare_isabelle_runtime', lambda **_: receipt(usable=False, smoke=smoke))
    result = setup.ensure_isabelle_ready(smoke=smoke)
    assert not result['ready'] and not result['capability']['available']
    if smoke:
        assert result['smoke']['accepted'] is False
    assert result['capability']['unavailable_reason'] == 'isabelle_runtime_identity_changed'


def test_inspect_explicit_path_uses_bounded_probe_and_preserves_selection(monkeypatch):
    calls = []
    monkeypatch.setattr(preparation, 'prepare_isabelle_runtime', lambda **kw: calls.append(kw) or receipt())
    assert setup.inspect_isabelle('/installed/bin/isabelle', timeout=2)['available']
    assert calls[0]['executable'] == '/installed/bin/isabelle'
    assert calls[0]['install_root'] is None and calls[0]['mode'] == 'command'


def test_requested_long_timeout_is_capped_to_preparation_profile(monkeypatch):
    calls = []
    monkeypatch.setattr(preparation, 'prepare_isabelle_runtime', lambda **kw: calls.append(kw) or receipt())
    assert setup.ensure_isabelle_ready(timeout=3600)['ready']
    assert calls[0]['timeout_seconds'] == 300


def test_failed_persistent_build_never_runs_or_claims_followup_smoke(monkeypatch):
    calls = []
    from ipfs_datasets_py.logic.backends.installers import isabelle_installation as installation
    from ipfs_datasets_py.logic.hammers.frontends import base
    data = {'status': 'failed', 'reason_codes': ['hol_build_failed'], 'preparation': {},
        'hol_build': {'build_succeeded': False, 'persistent_heap_published': False,
            'observation': {'returncode': 1, 'error': 'bounded fixture refusal'}}}
    monkeypatch.setattr(installation, 'ensure_isabelle_installation', lambda **kw:
        calls.append(kw) or SimpleNamespace(usable=False, to_dict=lambda: data))
    monkeypatch.setattr(preparation, 'prepare_isabelle_runtime', lambda **kw: pytest.fail('extra smoke'))
    monkeypatch.setattr(base, 'run_bounded_process', lambda *a, **kw: pytest.fail('legacy build bypass'))
    result = setup.ensure_isabelle_ready(build_hol=True, smoke=True)
    assert not result['ready'] and not result['smoke']['accepted']
    assert result['smoke']['result'] is None
    assert result['hol_build']['returncode'] == 1
    assert result['hol_build']['error'] == 'bounded fixture refusal'
    assert len(calls) == 1 and calls[0]['build_hol'] is True
    assert calls[0]['allow_download'] is False and calls[0]['yes'] is True


def test_native_default_smoke_cli_has_bounded_receipt_and_drained_children():
    from ipfs_datasets_py.logic.backends.installers import isabelle
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
    managed = isabelle.expand_user_local_root() / f'{isabelle.ISABELLE_VERSION}-{isabelle.detect_platform_key()}' / isabelle.ISABELLE_VERSION
    if not (managed / 'bin/isabelle').is_file():
        pytest.skip('installed pinned Isabelle distribution required')
    completed = subprocess.run([sys.executable, '-m', 'ipfs_datasets_py.logic.external_provers.isabelle_setup',
        '--smoke', '--timeout', '90'], capture_output=True, text=True, timeout=100)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result['ready'] and result['smoke']['accepted']
    assert result['installation'] is None and result['readiness_level'] == 'kernel_smoke'
    bounded = result['bounded_preparation']
    assert bounded['grants_proof_authority'] is False
    assert [row['phase'] for row in bounded['probes']] == ['version', 'theory_help', 'hol_no_build', 'smoke']
    assert '-n' in bounded['probes'][2]['command']
    assert all(row['observation']['workspace_cleaned'] for row in bounded['probes'])
    owned = {bounded['resource_lease_id'], *(row['child_lease_id'] for row in bounded['probes'])}
    assert not any(row['lease_id'] in owned for row in get_global_resource_scheduler().active_leases())
