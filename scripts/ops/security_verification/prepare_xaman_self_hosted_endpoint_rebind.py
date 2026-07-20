#!/usr/bin/env python3
"""Prepare a verifier-only Xaman source candidate for a self-hosted XRPL testnet.

The public Xaman source routes non-default ledger endpoints through a vendor
proxy and the Android HTTP factory redirects non-trusted hosts to a vendor
host.  A test-only source candidate is therefore required before a local
ledger test can be meaningful.  This tool verifies a frozen public checkout,
describes the required changes, and optionally materializes them into a
separate directory.  It never modifies the upstream checkout or claims a
vendor-release or production equivalence.
"""

from __future__ import annotations

import argparse
from io import BytesIO
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from typing import Any, Mapping


PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
PINNED_XAMAN_ORIGIN = 'https://github.com/XRPL-Labs/Xaman-App.git'
TASK_ID = 'PORTAL-CXTP-154'
SCHEMA_VERSION = 'xaman-self-hosted-endpoint-rebind-candidate/v1'
SELF_HOSTED_NETWORK_ID = 777777
SELF_HOSTED_NETWORK_KEY = 'SELF_HOSTED_TESTNET'
EMULATOR_LOCAL_HOST = '10.0.2.2'
LOCAL_API_PORT = 51236
LOCAL_LEDGER_PORT = 51235

SOURCE_FILES = {
    'endpoints': Path('src/common/constants/endpoints.ts'),
    'network': Path('src/common/constants/network.ts'),
    'network_service': Path('src/services/NetworkService.ts'),
    'http_factory': Path('android/app/src/main/java/libs/common/HTTPClientFactory.java'),
    'debug_manifest': Path('android/app/src/debug/AndroidManifest.xml'),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256:' + _sha256_bytes(canonical)


def _run_git(source_root: Path, *args: str) -> str:
    result = subprocess.run(
        ['git', *args],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def verify_source(source_root: Path) -> dict[str, str]:
    """Require the public checkout pinned for this verification corpus."""
    source_root = source_root.resolve()
    missing = [str(relative) for relative in SOURCE_FILES.values() if not (source_root / relative).is_file()]
    if missing:
        raise ValueError('Xaman checkout is missing required files: ' + ', '.join(missing))

    commit = _run_git(source_root, 'rev-parse', 'HEAD').strip()
    if commit != PINNED_XAMAN_COMMIT:
        raise ValueError(f'expected Xaman commit {PINNED_XAMAN_COMMIT}, found {commit}')
    if _run_git(source_root, 'status', '--porcelain').strip():
        raise ValueError('Xaman checkout must be clean before candidate preparation')
    origin = _run_git(source_root, 'remote', 'get-url', 'origin').strip()
    if origin != PINNED_XAMAN_ORIGIN:
        raise ValueError(f'expected Xaman origin {PINNED_XAMAN_ORIGIN}, found {origin}')
    return {'commit': commit, 'origin': origin}


def _replace_once(value: str, old: str, new: str, label: str) -> str:
    count = value.count(old)
    if count != 1:
        raise ValueError(f'expected exactly one {label} source anchor, found {count}')
    return value.replace(old, new, 1)


def render_candidate_files(source_root: Path) -> dict[Path, str]:
    """Render the four source edits that make vendor fallback impossible."""
    source_root = source_root.resolve()
    rendered = {
        relative: (source_root / relative).read_text(encoding='utf-8')
        for relative in SOURCE_FILES.values()
        if relative != SOURCE_FILES['debug_manifest']
    }

    rendered[SOURCE_FILES['endpoints']] = _replace_once(
        rendered[SOURCE_FILES['endpoints']],
        "export const HOSTNAME = 'xaman.app';\nexport const ApiUrl = `https://${HOSTNAME}/api`;",
        "// Verifier-only self-hosted API bridge. Do not ship in vendor builds.\n"
        f"export const HOSTNAME = '{EMULATOR_LOCAL_HOST}:{LOCAL_API_PORT}';\n"
        'export const ApiUrl = `http://${HOSTNAME}/api`;',
        'API host',
    )
    rendered[SOURCE_FILES['network']] = _replace_once(
        rendered[SOURCE_FILES['network']],
        "name: 'XRPL Testnet',\n            key: 'TESTNET',\n            networkId: 1,",
        "name: 'Self-Hosted XRPL Testnet',\n"
        f"            key: '{SELF_HOSTED_NETWORK_KEY}',\n"
        f'            networkId: {SELF_HOSTED_NETWORK_ID},',
        'Testnet identity',
    )
    rendered[SOURCE_FILES['network']] = _replace_once(
        rendered[SOURCE_FILES['network']],
        "nodes: ['wss://testnet.xrpl-labs.com', 'wss://s.altnet.rippletest.net:51233'],",
        f"nodes: ['ws://{EMULATOR_LOCAL_HOST}:{LOCAL_LEDGER_PORT}'],",
        'Testnet node list',
    )
    rendered[SOURCE_FILES['network_service']] = _replace_once(
        rendered[SOURCE_FILES['network_service']],
        '    normalizeEndpoint = (endpoint: string): string => {\n',
        '    normalizeEndpoint = (endpoint: string): string => {\n'
        f"        const selfHostedEndpoint = 'ws://{EMULATOR_LOCAL_HOST}:{LOCAL_LEDGER_PORT}';\n"
        '        // Fail closed: the verifier candidate never proxies to a vendor endpoint.\n'
        '        if (endpoint !== selfHostedEndpoint) {\n'
        '            return selfHostedEndpoint;\n'
        '        }\n\n',
        'endpoint normalizer',
    )
    rendered[SOURCE_FILES['network_service']] = _replace_once(
        rendered[SOURCE_FILES['network_service']],
        '        // get default node for selected network\n        const { defaultNode, nodes } = this.getNetwork();',
        '        // Reject any persisted or backend-provided non-local network selection.\n'
        f'        if (this.getNetwork().networkId !== {SELF_HOSTED_NETWORK_ID}) {{\n'
        "            this.logger.error('Self-hosted verifier rejected a non-local network selection');\n"
        '            this.setConnectionStatus(NetworkStateStatus.Disconnected);\n'
        '            return;\n'
        '        }\n\n'
        '        // get default node for selected network\n'
        '        const { defaultNode, nodes } = this.getNetwork();',
        'network connection guard',
    )
    rendered[SOURCE_FILES['http_factory']] = _replace_once(
        rendered[SOURCE_FILES['http_factory']],
        '    // TODO: remove "xumm-cdn.imgix.net", "cdn.xumm.pro". "xumm.app" after migration period\n'
        '    private static final List<String> trustedHosts = Arrays.asList("xumm-cdn.imgix.net", "xrplcluster.com", "xahau.network", "custom-node.xrpl-labs.com", "cdn.xumm.pro", "xumm.app", "cdn.xaman.app", "xaman.app", "image-proxy.xrpl-labs.com");\n'
        '    private static final String defaultHost = "xaman.app";',
        '    // Verifier-only local allowlist. Do not ship in vendor builds.\n'
        f'    private static final List<String> trustedHosts = Arrays.asList("{EMULATOR_LOCAL_HOST}");\n'
        f'    private static final String defaultHost = "{EMULATOR_LOCAL_HOST}";',
        'Android HTTP host allowlist',
    )
    return rendered


def _candidate_file_report(source_root: Path, rendered: Mapping[Path, str]) -> list[dict[str, str]]:
    report: list[dict[str, str]] = []
    for relative in sorted(rendered):
        original = source_root / relative
        report.append(
            {
                'path': relative.as_posix(),
                'source_sha256': _sha256_file(original),
                'candidate_sha256': _sha256_bytes(rendered[relative].encode('utf-8')),
            }
        )
    return report


def build_manifest(source_root: Path, source: Mapping[str, str], rendered: Mapping[Path, str], *, materialized: bool) -> dict[str, Any]:
    debug_manifest = (source_root / SOURCE_FILES['debug_manifest']).read_text(encoding='utf-8')
    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'overall_status': (
            'candidate_materialized_pending_independent_review'
            if materialized
            else 'candidate_ready_for_materialization'
        ),
        'security_decision': 'BLOCK_APP_RUNTIME_UNTIL_INDEPENDENT_REVIEW_AND_REDACTED_TRACE',
        'scope': {
            'public_source_commit': source['commit'],
            'public_source_origin': source['origin'],
            'verifier_only': True,
            'vendor_release_equivalent': False,
            'production_usable': False,
            'upstream_checkout_modified': False,
        },
        'source_boundary': {
            'custom_node_routing_uses_vendor_proxy_before_patch': 'custom-node.xrpl-labs.com' in (source_root / SOURCE_FILES['network']).read_text(encoding='utf-8'),
            'android_untrusted_host_falls_back_to_vendor_before_patch': 'defaultHost = "xaman.app"' in (source_root / SOURCE_FILES['http_factory']).read_text(encoding='utf-8'),
            'debug_cleartext_transport_declared': 'android:usesCleartextTraffic="true"' in debug_manifest,
        },
        'candidate_controls': {
            'api_route': 'ANDROID_EMULATOR_LOCAL_API_BRIDGE',
            'ledger_route': 'ANDROID_EMULATOR_LOCAL_LEDGER_BRIDGE',
            'network_id': SELF_HOSTED_NETWORK_ID,
            'non_local_network_selection_rejected': True,
            'custom_node_vendor_proxy_bypassed': True,
            'android_http_vendor_host_fallback_removed': True,
        },
        'changed_files': _candidate_file_report(source_root, rendered),
        'required_before_runtime_evidence': [
            'independent_human_review_of_source_diff',
            'reviewed_loopback_only_api_and_ledger_bridge',
            'debug_build_identity_and_digest',
            'redacted_runtime_trace_showing_local_network_selection',
            'reviewed_mapping_from_trace_categories_to_security_model_claims',
        ],
        'prohibited_claims': [
            'vendor_release_equivalence',
            'production_security_approval',
            'vendor_or_public_testnet_contact',
            'wallet_security_proved',
        ],
    }


def _export_pinned_source(source_root: Path, destination: Path) -> None:
    """Export the committed tree, including sparse-checkout paths not on disk."""
    archive = subprocess.run(
        ['git', 'archive', '--format=tar', 'HEAD'],
        cwd=source_root,
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=BytesIO(archive), mode='r:') as entries:
        for entry in entries.getmembers():
            target = (destination / entry.name).resolve()
            if destination not in target.parents and target != destination:
                raise ValueError(f'refusing unsafe archive member: {entry.name}')
        entries.extractall(destination, filter='data')


def materialize_candidate(source_root: Path, destination: Path, rendered: Mapping[Path, str]) -> None:
    source_root = source_root.resolve()
    destination = destination.resolve()
    if destination == source_root or source_root in destination.parents:
        raise ValueError('candidate destination must be outside the frozen Xaman checkout')
    if destination.exists():
        raise ValueError(f'candidate destination already exists: {destination}')
    destination.mkdir(parents=True)
    try:
        _export_pinned_source(source_root, destination)
        for relative, value in rendered.items():
            target = destination / relative
            target.write_text(value, encoding='utf-8')
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def prepare(source_root: Path, *, destination: Path | None = None) -> dict[str, Any]:
    source_root = source_root.resolve()
    source = verify_source(source_root)
    rendered = render_candidate_files(source_root)
    if destination is not None:
        materialize_candidate(source_root, destination, rendered)
    manifest = build_manifest(source_root, source, rendered, materialized=destination is not None)
    manifest['artifact_cid'] = _artifact_cid(manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, help='Clean frozen public Xaman checkout.')
    parser.add_argument(
        '--out',
        default='security_ir_artifacts/corpora/xaman-app/self-hosted-testnet/endpoint-rebound-candidate.json',
        help='Manifest destination, relative to the ipfs_datasets repository by default.',
    )
    parser.add_argument('--materialize', action='store_true', help='Create a separate verifier-only source candidate.')
    parser.add_argument('--destination', help='Required with --materialize; must not exist.')
    args = parser.parse_args(argv)
    if args.materialize != bool(args.destination):
        parser.error('--materialize and --destination must be supplied together')

    repo_root = _repo_root()
    out = Path(args.out)
    if not out.is_absolute():
        out = repo_root / out
    destination = Path(args.destination) if args.destination else None
    manifest = prepare(Path(args.source_root), destination=destination)
    _write_json(out, manifest)
    print(json.dumps({
        'artifact_cid': manifest['artifact_cid'],
        'overall_status': manifest['overall_status'],
        'out': str(out),
        'security_decision': manifest['security_decision'],
    }, sort_keys=True))
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
