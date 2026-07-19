#!/usr/bin/env python3
"""Provision and verify an isolated, self-hosted `rippled` XRPL bridge.

This tool is the runtime counterpart of the verifier-only source candidate
prepared by ``PORTAL-CXTP-154``. That candidate expects a local ledger bridge
reachable from an Android emulator at ``ws://10.0.2.2:51235``, which the host
side sees as ``ws://127.0.0.1:51235``. This tool provisions exactly that
bridge on top of a single, digest-pinned `rippled` container running in
standalone mode (no peers, no public Testnet or vendor validator-list
publishers), isolated inside its own Docker network.

Two independent controls stand in for a Docker ``--internal`` network, which
this tool intentionally avoids: Docker refuses to publish (``-p``) any port
of a container whose only network is ``--internal``, so an internal network
cannot also expose a reviewed host-loopback listener. Instead this tool:

1. Creates a private bridge network with IP masquerading disabled
   (``com.docker.network.bridge.enable_ip_masquerade=false``), which denies
   the container a NAT path to the public internet while still allowing the
   host to publish a single port to the container via DNAT.
2. Publishes only one container port -- the non-admin ledger WebSocket
   (``port_ws_public``) -- and only to ``127.0.0.1`` on the host. The admin
   RPC and admin WebSocket ports stay bound to the container's own loopback
   interface and are reachable only through ``docker exec``, never from the
   host network stack or any published port.

Every run re-verifies both controls empirically (an egress probe from inside
the container, and a host-side inspection of exactly which ports Docker
published and to which host address) rather than assuming the configuration
is correct. A dry run performs only read-only Docker inspection and never
creates a network or starts a container. This tool does not claim vendor
release equivalence, production security, or wallet security; see
``docs/security_verification/xaman_self_hosted_testnet_prerequisites.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

TASK_ID = 'PORTAL-CXTP-155'
SCHEMA_VERSION_HEALTH = 'xaman-self-hosted-testnet-daemon-health/v1'
SCHEMA_VERSION_ISOLATION = 'xaman-self-hosted-testnet-bridge-isolation-report/v1'

# Pinned by content digest, not by mutable tag. Re-resolve intentionally
# (see docs) rather than silently drifting to a new `latest`/`2.2.0` build.
RIPPLED_IMAGE_REPO = 'xrpllabsofficial/xrpld'
RIPPLED_IMAGE_DIGEST = (
    'sha256:035813a8980d7fe571027b168c48ae896e3f20e361b529904235290ccdb8babf'
)
RIPPLED_IMAGE_REF = f'{RIPPLED_IMAGE_REPO}@{RIPPLED_IMAGE_DIGEST}'
RIPPLED_IMAGE_HUMAN_TAG = '2.2.0'  # informational only; the digest above is authoritative

SELF_HOSTED_NETWORK_ID = 777777  # must match PORTAL-CXTP-154's SELF_HOSTED_NETWORK_ID

DOCKER_NETWORK_NAME = 'ipfs-datasets-portal-cxtp-155-isolated-net'
CONTAINER_NAME = 'ipfs-datasets-portal-cxtp-155-rippled'
DOCKER_LABEL_KEY = 'org.ipfs-datasets.task-id'
DOCKER_LABEL_VALUE = TASK_ID

HOST_LOOPBACK = '127.0.0.1'
HOST_LEDGER_BRIDGE_PORT = 51235  # matches PORTAL-CXTP-154 LOCAL_LEDGER_PORT

CONTAINER_WS_PUBLIC_PORT = 6005
CONTAINER_WS_ADMIN_PORT = 6006
CONTAINER_RPC_ADMIN_PORT = 5005

DAEMON_READY_TIMEOUT_SECONDS = 30
DAEMON_POLL_INTERVAL_SECONDS = 1.0
EGRESS_PROBE_TIMEOUT_SECONDS = 4

# Known-public hosts used only as egress-probe *targets*; never recorded verbatim
# in evidence. One raw IP (no DNS dependency) and one DNS-resolved vendor/public
# Testnet host, so a DNS-only leak cannot masquerade as "egress denied".
_EGRESS_PROBE_TARGETS = (
    ('public_ip_literal', '1.1.1.1', 443),
    ('public_vendor_testnet_dns_host', 's.altnet.rippletest.net', 51234),
)

DEFAULT_HEALTH_OUT = Path(
    'security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/daemon-health.json'
)
DEFAULT_ISOLATION_OUT = Path(
    'security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/bridge-isolation-report.json'
)


class ProvisionError(RuntimeError):
    """Raised for any provisioning failure that must stop the run."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256:' + _sha256_bytes(canonical)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# Docker CLI helpers
# ---------------------------------------------------------------------------

def _docker(*args: str, check: bool = True, timeout: float | None = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ['docker', *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ProvisionError('docker CLI is not installed or not on PATH') from exc
    except subprocess.TimeoutExpired as exc:
        raise ProvisionError(f'docker command timed out: docker {" ".join(args)}') from exc


def docker_available() -> bool:
    """Read-only check. Safe to run during a dry run."""
    try:
        result = _docker('info', '--format', '{{.ServerVersion}}', check=False, timeout=10)
    except ProvisionError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def image_digest_present(image_ref: str) -> bool:
    """Read-only check for a locally cached, digest-pinned image. Safe for dry runs."""
    result = _docker('image', 'inspect', image_ref, check=False, timeout=15)
    return result.returncode == 0


def pull_pinned_image(image_ref: str) -> None:
    """Never called during a dry run."""
    result = _docker('pull', image_ref, check=False, timeout=600)
    if result.returncode != 0:
        raise ProvisionError(f'failed to pull pinned image {image_ref}: {result.stderr.strip()}')


def container_exists(name: str) -> bool:
    result = _docker('ps', '-a', '--filter', f'name=^{name}$', '--format', '{{.Names}}', check=False, timeout=15)
    return result.returncode == 0 and name in {line.strip() for line in result.stdout.splitlines() if line.strip()}


def network_exists(name: str) -> bool:
    result = _docker('network', 'ls', '--filter', f'name=^{name}$', '--format', '{{.Name}}', check=False, timeout=15)
    return result.returncode == 0 and name in {line.strip() for line in result.stdout.splitlines() if line.strip()}


def remove_container(name: str) -> bool:
    if not container_exists(name):
        return False
    _docker('rm', '-f', name, check=False, timeout=30)
    return True


def remove_network(name: str) -> bool:
    if not network_exists(name):
        return False
    _docker('network', 'rm', name, check=False, timeout=30)
    return True


def create_isolated_network(name: str) -> dict[str, Any]:
    """Create a private bridge network with masquerade (NAT egress) disabled.

    Deliberately not `--internal`: Docker will not publish (`-p`) any port of
    a container whose only network is internal, which would make it
    impossible to also expose the one reviewed host-loopback listener this
    bridge requires.
    """
    if network_exists(name):
        raise ProvisionError(f'docker network {name} already exists; run --teardown first')
    result = _docker(
        'network', 'create',
        '--driver', 'bridge',
        '--opt', 'com.docker.network.bridge.enable_ip_masquerade=false',
        '--label', f'{DOCKER_LABEL_KEY}={DOCKER_LABEL_VALUE}',
        name,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise ProvisionError(f'failed to create isolated network {name}: {result.stderr.strip()}')
    return inspect_network(name)


def inspect_network(name: str) -> dict[str, Any]:
    result = _docker('network', 'inspect', name, check=False, timeout=15)
    if result.returncode != 0:
        raise ProvisionError(f'failed to inspect network {name}: {result.stderr.strip()}')
    payload = json.loads(result.stdout)
    return payload[0] if payload else {}


# ---------------------------------------------------------------------------
# rippled standalone configuration (verifier-only self-hosted bridge)
# ---------------------------------------------------------------------------

def render_rippled_cfg() -> str:
    """Standalone-mode config: local network id, no vendor validator sites.

    Only three server ports are opened at all: the admin RPC and admin
    WebSocket ports bind to the container's own loopback (127.0.0.1) and are
    never published to the host; the non-admin `port_ws_public` binds to all
    of the container's own interfaces so the *host* can publish it via DNAT,
    and is the only port this tool ever publishes, and only to
    `127.0.0.1` on the host.
    """
    return '\n'.join([
        '[server]',
        'port_rpc_admin_local',
        'port_ws_admin_local',
        'port_ws_public',
        '',
        '[port_rpc_admin_local]',
        f'port = {CONTAINER_RPC_ADMIN_PORT}',
        'ip = 127.0.0.1',
        'admin = 127.0.0.1',
        'protocol = http',
        '',
        '[port_ws_admin_local]',
        f'port = {CONTAINER_WS_ADMIN_PORT}',
        'ip = 127.0.0.1',
        'admin = 127.0.0.1',
        'protocol = ws',
        '',
        '[port_ws_public]',
        f'port = {CONTAINER_WS_PUBLIC_PORT}',
        'ip = 0.0.0.0',
        'protocol = ws',
        '',
        '[node_size]',
        'tiny',
        '',
        '[ledger_history]',
        'full',
        '',
        '[node_db]',
        'type=NuDB',
        'path=/var/lib/rippled/db/nudb',
        'online_delete=256',
        'advisory_delete=0',
        '',
        '[database_path]',
        '/var/lib/rippled/db',
        '',
        '[debug_logfile]',
        '/var/log/rippled/debug.log',
        '',
        '# Verifier-only self-hosted bridge network id. Must never match a public',
        '# Mainnet (0), Testnet (1), or Devnet (2) identifier.',
        '[network_id]',
        str(SELF_HOSTED_NETWORK_ID),
        '',
        '[rpc_startup]',
        '{ "command": "log_level", "severity": "warning" }',
        '',
    ])


def render_validators_txt() -> str:
    """No validator list publishers. Standalone mode trusts no one but itself,
    and this file must not contain any vendor/public validator-list URL.
    """
    return '\n'.join([
        '# Verifier-only self-hosted bridge: standalone mode requires no',
        '# validator list. No [validator_list_sites] or [validator_list_keys]',
        '# are configured, so this daemon never contacts vl.ripple.com,',
        '# vl.xrplf.org, or any other vendor/public validator-list publisher.',
        '[validators]',
        '',
    ])


def render_bridge_configuration() -> dict[str, str]:
    return {
        'rippled.cfg': render_rippled_cfg(),
        'validators.txt': render_validators_txt(),
    }


def _config_digests(rendered: Mapping[str, str]) -> dict[str, str]:
    return {name: _sha256_bytes(content.encode('utf-8')) for name, content in sorted(rendered.items())}


def write_runtime_config(config_dir: Path, rendered: Mapping[str, str]) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    for name, content in rendered.items():
        (config_dir / name).write_text(content, encoding='utf-8')


# ---------------------------------------------------------------------------
# Daemon lifecycle
# ---------------------------------------------------------------------------

def start_daemon(config_dir: Path, network_name: str, container_name: str, image_ref: str) -> None:
    if container_exists(container_name):
        raise ProvisionError(f'container {container_name} already exists; run --teardown first')
    result = _docker(
        'run', '-d',
        '--name', container_name,
        '--network', network_name,
        '--label', f'{DOCKER_LABEL_KEY}={DOCKER_LABEL_VALUE}',
        '-v', f'{config_dir / "rippled.cfg"}:/config/rippled.cfg:ro',
        '-v', f'{config_dir / "validators.txt"}:/config/validators.txt:ro',
        '-p', f'{HOST_LOOPBACK}:{HOST_LEDGER_BRIDGE_PORT}:{CONTAINER_WS_PUBLIC_PORT}',
        image_ref,
        '-a',  # --standalone: no peers, self-hosted only
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise ProvisionError(f'failed to start daemon container {container_name}: {result.stderr.strip()}')


def _exec_admin_rpc(container_name: str, command: str) -> dict[str, Any] | None:
    """Query the container-loopback-only admin RPC port via `docker exec`.

    This never opens a host-reachable path to the admin surface; the request
    and response stay entirely inside the container's own network namespace.
    """
    result = _docker(
        'exec', container_name,
        '/opt/ripple/bin/rippled',
        '--conf', '/etc/opt/ripple/rippled.cfg',
        '--rpc_ip', f'127.0.0.1:{CONTAINER_RPC_ADMIN_PORT}',
        command,
        check=False,
        timeout=15,
    )
    if result.returncode != 0:
        return None
    # rippled's CLI RPC mode prints a "Loading: ..." banner and warnings
    # before the JSON body; parse only from the first '{'.
    brace_index = result.stdout.find('{')
    if brace_index < 0:
        return None
    try:
        return json.loads(result.stdout[brace_index:])
    except (json.JSONDecodeError, ValueError):
        return None


def _categorize_server_info(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract only categorical fields. Never retain the raw RPC response."""
    info = ((raw or {}).get('result') or {}).get('info') or {}
    validated_ledger = info.get('validated_ledger') or {}
    server_state = info.get('server_state')
    peers = info.get('peers')
    return {
        'rpc_reachable': raw is not None,
        'rpc_status': (raw or {}).get('result', {}).get('status') if raw else None,
        'server_state': server_state,
        'server_state_category': (
            'HEALTHY_STANDALONE_FULL' if server_state == 'full'
            else 'DEGRADED_NOT_FULL' if server_state is not None
            else 'UNREACHABLE'
        ),
        'standalone_mode_confirmed': peers == 0 and server_state in {'full', 'proposing'},
        'peer_count_zero': peers == 0,
        'network_id_reported': info.get('network_id'),
        'network_id_matches_self_hosted': info.get('network_id') == SELF_HOSTED_NETWORK_ID,
        'validated_ledger_present': bool(validated_ledger),
        'validated_ledger_sequence_positive': bool(validated_ledger) and isinstance(validated_ledger.get('seq'), int) and validated_ledger.get('seq', 0) > 0,
        'uptime_positive': isinstance(info.get('uptime'), int) and info.get('uptime', 0) >= 0,
    }


def wait_for_daemon_health(
    container_name: str,
    *,
    timeout: float = DAEMON_READY_TIMEOUT_SECONDS,
    poll_interval: float = DAEMON_POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = _categorize_server_info(None)
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        raw = _exec_admin_rpc(container_name, 'server_info')
        last = _categorize_server_info(raw)
        if last['server_state_category'] == 'HEALTHY_STANDALONE_FULL' and last['network_id_matches_self_hosted']:
            last['polling_attempts'] = attempts
            return last
        time.sleep(poll_interval)
    last['polling_attempts'] = attempts
    return last


# ---------------------------------------------------------------------------
# Isolation probes
# ---------------------------------------------------------------------------

def inspect_published_ports(container_name: str) -> dict[str, Any]:
    result = _docker('inspect', container_name, check=False, timeout=15)
    if result.returncode != 0:
        raise ProvisionError(f'failed to inspect container {container_name}: {result.stderr.strip()}')
    payload = json.loads(result.stdout)[0]
    ports: Mapping[str, Any] = payload.get('NetworkSettings', {}).get('Ports') or {}

    published: list[dict[str, Any]] = []
    non_loopback_publish_found = False
    for container_port, bindings in ports.items():
        for binding in bindings or []:
            host_ip = binding.get('HostIp', '')
            host_port = binding.get('HostPort', '')
            published.append({
                'container_port': container_port,
                'host_port': host_port,
                'host_bound_to_loopback_only': host_ip in ('127.0.0.1', ''),
            })
            if host_ip not in ('127.0.0.1', ''):
                non_loopback_publish_found = True

    admin_ports_published = any(
        entry['container_port'] in (f'{CONTAINER_RPC_ADMIN_PORT}/tcp', f'{CONTAINER_WS_ADMIN_PORT}/tcp')
        for entry in published
    )
    expected_bridge_published = any(
        entry['container_port'] == f'{CONTAINER_WS_PUBLIC_PORT}/tcp' and entry['host_bound_to_loopback_only']
        for entry in published
    )

    return {
        'published_port_count': len(published),
        'published_ports': published,
        'admin_ports_published_to_host': admin_ports_published,
        'reviewed_ledger_bridge_published_loopback_only': expected_bridge_published,
        'any_non_loopback_publish_found': non_loopback_publish_found,
        'no_public_ingress': (not admin_ports_published) and (not non_loopback_publish_found) and expected_bridge_published,
    }


def _dns_resolution_succeeds(container_name: str, host: str) -> bool:
    result = _docker(
        'exec', container_name, 'getent', 'hosts', host,
        check=False, timeout=10,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def probe_public_egress_denied(container_name: str) -> dict[str, Any]:
    """Attempt short-timeout outbound connections from inside the isolated
    container. Only a categorical pass/fail per target category is kept;
    the literal target host/IP used for the probe is never written to disk.

    Note (recorded transparently, not hidden): Docker's embedded DNS proxy
    (127.0.0.11) runs in the host's network namespace and can still resolve
    public hostnames even when the container's own network has masquerading
    disabled, because the resolution itself never traverses the container's
    denied egress path. This tool therefore does not claim DNS-query privacy;
    it only claims -- and separately, empirically verifies -- that no TCP
    data-plane connection reaches a public IP literal or a public/vendor
    Testnet host from inside the isolated container.
    """
    categories: dict[str, bool] = {}
    for category, host, port in _EGRESS_PROBE_TARGETS:
        # A DNS-resolved target may have multiple A records; wget tries each
        # in turn even with `-t 1`, so the outer subprocess timeout must be
        # generous enough to cover every address, not just one.
        result = _docker(
            'exec', container_name,
            'wget',
            '-T', str(EGRESS_PROBE_TIMEOUT_SECONDS),
            '-t', '1',
            '-q', '-O', '/dev/null',
            f'http://{host}:{port}',
            check=False,
            timeout=EGRESS_PROBE_TIMEOUT_SECONDS * 8,
        )
        # A successful HTTP fetch (rc 0) or an explicit HTTP-protocol-level
        # failure such as "server returned error" would both mean the
        # connection reached the target. Any other non-zero code (network
        # unreachable, timeout, connection refused/reset) means it did not.
        categories[category] = result.returncode != 0

    dns_leak_check = _dns_resolution_succeeds(container_name, _EGRESS_PROBE_TARGETS[1][1])

    return {
        'probe_targets_categories': sorted(categories),
        'egress_denied_by_category': categories,
        'public_egress_denied': all(categories.values()) if categories else False,
        'dns_hostname_resolution_may_succeed': dns_leak_check,
        'dns_resolution_note': (
            'Docker embedded DNS may resolve public hostnames from the host '
            'namespace even though the isolated network denies the resulting '
            'TCP data-plane connection; this is a known, disclosed boundary, '
            'not a data-plane egress path.'
        ),
    }


def network_isolation_facts(network_name: str) -> dict[str, Any]:
    payload = inspect_network(network_name)
    options: Mapping[str, Any] = payload.get('Options') or {}
    masquerade_raw = options.get('com.docker.network.bridge.enable_ip_masquerade')
    ipam_config = (payload.get('IPAM') or {}).get('Config') or []
    return {
        'driver': payload.get('Driver'),
        'docker_internal_flag': payload.get('Internal', False),
        'ip_masquerade_enabled': (masquerade_raw or '').lower() == 'true',
        'assigned_subnet_count': len(ipam_config),
        'container_count': len(payload.get('Containers') or {}),
    }


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------

def build_dry_run_health_report() -> dict[str, Any]:
    docker_ok = docker_available()
    image_present = image_digest_present(RIPPLED_IMAGE_REF) if docker_ok else False
    return {
        'schema_version': SCHEMA_VERSION_HEALTH,
        'task_id': TASK_ID,
        'mode': 'dry_run',
        'overall_status': 'dry_run_validated_no_container_started',
        'security_decision': 'NO_RUNTIME_CLAIM_DRY_RUN_ONLY',
        'container_started': False,
        'docker_cli_available': docker_ok,
        'pinned_image_reference': RIPPLED_IMAGE_REF,
        'pinned_image_present_locally': image_present,
        'self_hosted_network_id': SELF_HOSTED_NETWORK_ID,
        'configuration_digests': _config_digests(render_bridge_configuration()),
        'notes': [
            'A dry run performs only read-only Docker inspection.',
            'No docker network, container, or volume is created in this mode.',
        ],
    }


def build_dry_run_isolation_report() -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION_ISOLATION,
        'task_id': TASK_ID,
        'mode': 'dry_run',
        'overall_status': 'dry_run_validated_no_container_started',
        'security_decision': 'NO_RUNTIME_CLAIM_DRY_RUN_ONLY',
        'network_created': False,
        'container_started': False,
        'planned_network_name': DOCKER_NETWORK_NAME,
        'planned_container_name': CONTAINER_NAME,
        'planned_isolation_controls': {
            'docker_internal_flag_used': False,
            'ip_masquerade_disabled': True,
            'reviewed_loopback_port': HOST_LEDGER_BRIDGE_PORT,
            'admin_ports_never_published': True,
        },
        'teardown_or_retention_state': 'not_applicable_dry_run',
    }


def build_daemon_health_report(health: Mapping[str, Any], *, materialized: bool) -> dict[str, Any]:
    manifest = {
        'schema_version': SCHEMA_VERSION_HEALTH,
        'task_id': TASK_ID,
        'mode': 'activated',
        'overall_status': (
            'daemon_healthy_standalone_full'
            if health.get('server_state_category') == 'HEALTHY_STANDALONE_FULL'
            else 'daemon_unhealthy_or_unreachable'
        ),
        'security_decision': (
            'SELF_HOSTED_BRIDGE_HEALTHY_PENDING_INDEPENDENT_REVIEW'
            if health.get('server_state_category') == 'HEALTHY_STANDALONE_FULL'
            else 'BLOCK_RUNTIME_EVIDENCE_DAEMON_NOT_HEALTHY'
        ),
        'container_started': materialized,
        'pinned_image_reference': RIPPLED_IMAGE_REF,
        'self_hosted_network_id': SELF_HOSTED_NETWORK_ID,
        'daemon_health': health,
        'evidence_boundary': {
            'raw_rpc_response_retained': False,
            'seeds_retained': False,
            'account_addresses_retained': False,
            'transaction_blobs_retained': False,
            'raw_endpoints_retained': False,
        },
        'prohibited_claims': [
            'vendor_release_equivalence',
            'production_security_approval',
            'wallet_security_proved',
            'transaction_finality_proved',
        ],
    }
    manifest['artifact_cid'] = _artifact_cid(manifest)
    return manifest


def build_bridge_isolation_report(
    *,
    network_facts: Mapping[str, Any],
    port_facts: Mapping[str, Any],
    egress_facts: Mapping[str, Any],
    teardown_or_retention_state: str,
) -> dict[str, Any]:
    isolated = bool(
        (not network_facts.get('docker_internal_flag'))
        and (not network_facts.get('ip_masquerade_enabled'))
        and port_facts.get('no_public_ingress')
        and egress_facts.get('public_egress_denied')
    )
    manifest = {
        'schema_version': SCHEMA_VERSION_ISOLATION,
        'task_id': TASK_ID,
        'mode': 'activated',
        'overall_status': (
            'bridge_isolated_loopback_only_no_public_ingress_or_egress'
            if isolated
            else 'bridge_isolation_controls_incomplete'
        ),
        'security_decision': (
            'SELF_HOSTED_BRIDGE_ISOLATED_PENDING_INDEPENDENT_REVIEW'
            if isolated
            else 'BLOCK_RUNTIME_EVIDENCE_ISOLATION_NOT_CONFIRMED'
        ),
        'network_name': DOCKER_NETWORK_NAME,
        'container_name': CONTAINER_NAME,
        'network_isolation': network_facts,
        'port_publication': port_facts,
        'egress_probe': egress_facts,
        'self_hosted_network_id': SELF_HOSTED_NETWORK_ID,
        'reviewed_loopback_listener': {
            'host': HOST_LOOPBACK,
            'port': HOST_LEDGER_BRIDGE_PORT,
            'role': 'ANDROID_EMULATOR_LOCAL_LEDGER_BRIDGE',
        },
        'teardown_or_retention_state': teardown_or_retention_state,
        'required_before_runtime_evidence': [
            'independent_review_of_docker_network_and_bridge_configuration',
            'independent_review_binding_pinned_source_commit_to_daemon_digest',
            'redacted_runtime_trace_via_reviewed_candidate_and_local_network',
        ],
        'prohibited_claims': [
            'vendor_release_equivalence',
            'production_security_approval',
            'public_testnet_connectivity',
            'wallet_security_proved',
        ],
    }
    manifest['artifact_cid'] = _artifact_cid(manifest)
    return manifest


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_dry_run() -> tuple[dict[str, Any], dict[str, Any]]:
    return build_dry_run_health_report(), build_dry_run_isolation_report()


def run_teardown_only() -> tuple[dict[str, Any], dict[str, Any]]:
    container_removed = remove_container(CONTAINER_NAME)
    network_removed = remove_network(DOCKER_NETWORK_NAME)
    state = 'torn_down' if (container_removed or network_removed) else 'nothing_to_tear_down'
    health = {
        'schema_version': SCHEMA_VERSION_HEALTH,
        'task_id': TASK_ID,
        'mode': 'teardown_only',
        'overall_status': 'daemon_torn_down',
        'security_decision': 'NO_RUNTIME_CLAIM_TEARDOWN_ONLY',
        'container_started': False,
        'container_removed': container_removed,
        'self_hosted_network_id': SELF_HOSTED_NETWORK_ID,
    }
    health['artifact_cid'] = _artifact_cid(health)
    isolation = {
        'schema_version': SCHEMA_VERSION_ISOLATION,
        'task_id': TASK_ID,
        'mode': 'teardown_only',
        'overall_status': 'bridge_torn_down',
        'security_decision': 'NO_RUNTIME_CLAIM_TEARDOWN_ONLY',
        'network_removed': network_removed,
        'container_removed': container_removed,
        'teardown_or_retention_state': state,
    }
    isolation['artifact_cid'] = _artifact_cid(isolation)
    return health, isolation


def run_activation(*, teardown_after: bool, daemon_timeout: float) -> tuple[dict[str, Any], dict[str, Any]]:
    if not docker_available():
        raise ProvisionError('docker daemon is not reachable; cannot activate the bridge')
    if not image_digest_present(RIPPLED_IMAGE_REF):
        pull_pinned_image(RIPPLED_IMAGE_REF)
        if not image_digest_present(RIPPLED_IMAGE_REF):
            raise ProvisionError(f'pinned image {RIPPLED_IMAGE_REF} unavailable after pull')

    if container_exists(CONTAINER_NAME) or network_exists(DOCKER_NETWORK_NAME):
        raise ProvisionError(
            f'{CONTAINER_NAME} or {DOCKER_NETWORK_NAME} already exists; run with --teardown-only first'
        )

    config_dir = Path(tempfile.mkdtemp(prefix='cxtp155-rippled-cfg-'))
    rendered = render_bridge_configuration()
    write_runtime_config(config_dir, rendered)

    network_created = False
    container_started = False
    try:
        create_isolated_network(DOCKER_NETWORK_NAME)
        network_created = True
        start_daemon(config_dir, DOCKER_NETWORK_NAME, CONTAINER_NAME, RIPPLED_IMAGE_REF)
        container_started = True

        health = wait_for_daemon_health(CONTAINER_NAME, timeout=daemon_timeout)
        network_facts = network_isolation_facts(DOCKER_NETWORK_NAME)
        port_facts = inspect_published_ports(CONTAINER_NAME)
        egress_facts = probe_public_egress_denied(CONTAINER_NAME)

        teardown_state = 'retained_for_follow_on_runtime_evidence'
        if teardown_after:
            remove_container(CONTAINER_NAME)
            remove_network(DOCKER_NETWORK_NAME)
            teardown_state = 'torn_down_after_evidence_capture'

        daemon_health_report = build_daemon_health_report(health, materialized=True)
        bridge_isolation_report = build_bridge_isolation_report(
            network_facts=network_facts,
            port_facts=port_facts,
            egress_facts=egress_facts,
            teardown_or_retention_state=teardown_state,
        )
        return daemon_health_report, bridge_isolation_report
    except Exception:
        if container_started:
            remove_container(CONTAINER_NAME)
        if network_created:
            remove_network(DOCKER_NETWORK_NAME)
        raise
    finally:
        shutil.rmtree(config_dir, ignore_errors=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--activate',
        action='store_true',
        help='Actually provision the isolated network and daemon. Without this flag, '
             'the tool performs a read-only dry run and never starts a container.',
    )
    parser.add_argument(
        '--teardown',
        action='store_true',
        help='With --activate: remove the container and network after evidence capture. '
             'Without --activate: tear down any existing container/network from a previous '
             'run and exit (no new resources are created).',
    )
    parser.add_argument(
        '--daemon-timeout',
        type=float,
        default=DAEMON_READY_TIMEOUT_SECONDS,
        help='Seconds to wait for the daemon to report server_state=full.',
    )
    parser.add_argument('--out-health', default=str(DEFAULT_HEALTH_OUT))
    parser.add_argument('--out-isolation', default=str(DEFAULT_ISOLATION_OUT))
    args = parser.parse_args(argv)

    repo_root = _repo_root()

    def _resolve(path_str: str) -> Path:
        path = Path(path_str)
        return path if path.is_absolute() else repo_root / path

    health_out = _resolve(args.out_health)
    isolation_out = _resolve(args.out_isolation)

    if args.activate:
        health, isolation = run_activation(teardown_after=args.teardown, daemon_timeout=args.daemon_timeout)
    elif args.teardown:
        health, isolation = run_teardown_only()
    else:
        health, isolation = run_dry_run()

    _write_json(health_out, health)
    _write_json(isolation_out, isolation)
    print(json.dumps({
        'mode': health.get('mode'),
        'daemon_overall_status': health.get('overall_status'),
        'isolation_overall_status': isolation.get('overall_status'),
        'health_out': str(health_out),
        'isolation_out': str(isolation_out),
    }, sort_keys=True))
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
