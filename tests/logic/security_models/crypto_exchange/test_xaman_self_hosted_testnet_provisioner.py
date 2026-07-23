"""Tests for the self-hosted XRPL bridge provisioner (PORTAL-CXTP-155).

These tests exercise the pure-Python rendering, categorization, and report
construction logic without requiring a Docker daemon. Docker-dependent
behavior (creating a real isolated network and daemon) is validated
separately by running the script itself with `--activate` against a live
Docker Engine, per the task's validation command.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'provision_xaman_self_hosted_testnet.py'
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        'provision_xaman_self_hosted_testnet', SCRIPT_PATH
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load provisioner script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rippled_cfg_pins_self_hosted_network_id_and_minimal_ports() -> None:
    module = _load_module()

    cfg = module.render_rippled_cfg()

    assert '[network_id]\n777777' in cfg
    assert 'port_rpc_admin_local' in cfg and 'ip = 127.0.0.1' in cfg
    assert 'port_ws_public' in cfg
    # The public bridge port must bind to all container interfaces so the
    # host can publish it, but the admin ports must stay loopback-only.
    assert cfg.count('ip = 127.0.0.1') == 2
    assert 'ip = 0.0.0.0' in cfg
    # No peer or gRPC port is opened for a standalone-only daemon.
    assert 'port_peer' not in cfg
    assert 'port_grpc' not in cfg


def test_validators_txt_configures_no_vendor_or_public_publisher() -> None:
    module = _load_module()

    validators = module.render_validators_txt()

    active_lines = [line for line in validators.splitlines() if line.strip() and not line.strip().startswith('#')]
    assert active_lines == ['[validators]']
    assert 'https://vl.ripple.com' not in validators
    assert 'https://vl.xrplf.org' not in validators


def test_image_is_pinned_by_digest_not_mutable_tag() -> None:
    module = _load_module()

    assert module.RIPPLED_IMAGE_REF == f'{module.RIPPLED_IMAGE_REPO}@{module.RIPPLED_IMAGE_DIGEST}'
    assert module.RIPPLED_IMAGE_DIGEST.startswith('sha256:')
    assert '@sha256:' in module.RIPPLED_IMAGE_REF


def test_categorize_server_info_extracts_only_categorical_fields() -> None:
    module = _load_module()
    raw = {
        'result': {
            'status': 'success',
            'info': {
                'server_state': 'full',
                'network_id': 777777,
                'peers': 0,
                'uptime': 42,
                'validated_ledger': {'seq': 3, 'hash': 'DEADBEEF'},
                'pubkey_node': 'n9SomeSensitiveLookingIdentity',
            },
        }
    }

    categorized = module._categorize_server_info(raw)

    assert categorized['server_state_category'] == 'HEALTHY_STANDALONE_FULL'
    assert categorized['network_id_matches_self_hosted'] is True
    assert categorized['standalone_mode_confirmed'] is True
    assert categorized['validated_ledger_sequence_positive'] is True
    # The raw RPC payload (e.g. pubkey_node, ledger hash) must never surface.
    serialized_keys = set(categorized)
    assert 'pubkey_node' not in serialized_keys
    assert not any('hash' in key for key in serialized_keys)


def test_categorize_server_info_handles_unreachable_daemon() -> None:
    module = _load_module()

    categorized = module._categorize_server_info(None)

    assert categorized['rpc_reachable'] is False
    assert categorized['server_state_category'] == 'UNREACHABLE'
    assert categorized['network_id_matches_self_hosted'] is False


def test_dry_run_reports_never_start_a_container(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, 'docker_available', lambda: True)
    monkeypatch.setattr(module, 'image_digest_present', lambda _ref: True)

    health, isolation = module.run_dry_run()

    assert health['mode'] == 'dry_run'
    assert health['container_started'] is False
    assert health['overall_status'] == 'dry_run_validated_no_container_started'
    assert isolation['mode'] == 'dry_run'
    assert isolation['container_started'] is False
    assert isolation['network_created'] is False
    assert isolation['teardown_or_retention_state'] == 'not_applicable_dry_run'


def test_build_daemon_health_report_blocks_when_not_full() -> None:
    module = _load_module()
    unhealthy = module._categorize_server_info(None)

    report = module.build_daemon_health_report(unhealthy, materialized=True)

    assert report['overall_status'] == 'daemon_unhealthy_or_unreachable'
    assert report['security_decision'] == 'BLOCK_RUNTIME_EVIDENCE_DAEMON_NOT_HEALTHY'
    assert report['evidence_boundary']['raw_rpc_response_retained'] is False
    assert 'artifact_cid' in report


def test_build_daemon_health_report_healthy_state() -> None:
    module = _load_module()
    healthy = module._categorize_server_info({
        'result': {
            'status': 'success',
            'info': {
                'server_state': 'full',
                'network_id': module.SELF_HOSTED_NETWORK_ID,
                'peers': 0,
                'uptime': 5,
                'validated_ledger': {'seq': 1},
            },
        }
    })

    report = module.build_daemon_health_report(healthy, materialized=True)

    assert report['overall_status'] == 'daemon_healthy_standalone_full'
    assert report['security_decision'] == 'SELF_HOSTED_BRIDGE_HEALTHY_PENDING_INDEPENDENT_REVIEW'
    assert 'vendor_release_equivalence' in report['prohibited_claims']


def test_build_bridge_isolation_report_flags_incomplete_isolation() -> None:
    module = _load_module()

    report = module.build_bridge_isolation_report(
        network_facts={'docker_internal_flag': False, 'ip_masquerade_enabled': True},
        port_facts={'no_public_ingress': True},
        egress_facts={'public_egress_denied': False},
        teardown_or_retention_state='retained_for_follow_on_runtime_evidence',
    )

    assert report['overall_status'] == 'bridge_isolation_controls_incomplete'
    assert report['security_decision'] == 'BLOCK_RUNTIME_EVIDENCE_ISOLATION_NOT_CONFIRMED'


def test_build_bridge_isolation_report_confirms_full_isolation() -> None:
    module = _load_module()

    report = module.build_bridge_isolation_report(
        network_facts={'docker_internal_flag': False, 'ip_masquerade_enabled': False},
        port_facts={'no_public_ingress': True},
        egress_facts={'public_egress_denied': True},
        teardown_or_retention_state='retained_for_follow_on_runtime_evidence',
    )

    assert report['overall_status'] == 'bridge_isolated_loopback_only_no_public_ingress_or_egress'
    assert report['security_decision'] == 'SELF_HOSTED_BRIDGE_ISOLATED_PENDING_INDEPENDENT_REVIEW'
    assert report['self_hosted_network_id'] == 777777
    assert report['reviewed_loopback_listener']['host'] == '127.0.0.1'
    assert 'artifact_cid' in report


def test_inspect_published_ports_flags_non_loopback_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    def fake_docker(*args, check=False, timeout=None):
        class _Result:
            returncode = 0
            stdout = (
                '[{"NetworkSettings": {"Ports": {'
                '"6005/tcp": [{"HostIp": "0.0.0.0", "HostPort": "51235"}]'
                '}}}]'
            )
            stderr = ''
        return _Result()

    monkeypatch.setattr(module, '_docker', fake_docker)

    facts = module.inspect_published_ports('some-container')

    assert facts['any_non_loopback_publish_found'] is True
    assert facts['no_public_ingress'] is False


def test_inspect_published_ports_confirms_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    def fake_docker(*args, check=False, timeout=None):
        class _Result:
            returncode = 0
            stdout = (
                '[{"NetworkSettings": {"Ports": {'
                f'"{module.CONTAINER_WS_PUBLIC_PORT}/tcp": [{{"HostIp": "127.0.0.1", "HostPort": "51235"}}]'
                '}}}]'
            )
            stderr = ''
        return _Result()

    monkeypatch.setattr(module, '_docker', fake_docker)

    facts = module.inspect_published_ports('some-container')

    assert facts['any_non_loopback_publish_found'] is False
    assert facts['admin_ports_published_to_host'] is False
    assert facts['reviewed_ledger_bridge_published_loopback_only'] is True
    assert facts['no_public_ingress'] is True
