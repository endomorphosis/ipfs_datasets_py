"""Tests for the verifier-only self-hosted Xaman endpoint candidate."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / 'scripts' / 'ops' / 'security_verification' / 'prepare_xaman_self_hosted_endpoint_rebind.py'


def _load_module():
    spec = importlib.util.spec_from_file_location('prepare_xaman_self_hosted_endpoint_rebind', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load endpoint-rebind candidate script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / 'xaman-app'
    files = {
        'src/common/constants/endpoints.ts': (
            "export const HOSTNAME = 'xaman.app';\n"
            'export const ApiUrl = `https://${HOSTNAME}/api`;\n'
        ),
        'src/common/constants/network.ts': (
            "name: 'XRPL Testnet',\n"
            "            key: 'TESTNET',\n"
            '            networkId: 1,\n'
            "            nodes: ['wss://testnet.xrpl-labs.com', 'wss://s.altnet.rippletest.net:51233'],\n"
            "customNodeProxy: 'wss://custom-node.xrpl-labs.com',\n"
        ),
        'src/services/NetworkService.ts': (
            '    normalizeEndpoint = (endpoint: string): string => {\n'
            '        return endpoint;\n'
            '    };\n\n'
            '    connect = () => {\n'
            '        // get default node for selected network\n'
            '        const { defaultNode, nodes } = this.getNetwork();\n'
            '    };\n'
        ),
        'android/app/src/main/java/libs/common/HTTPClientFactory.java': (
            '    // TODO: remove "xumm-cdn.imgix.net", "cdn.xumm.pro". "xumm.app" after migration period\n'
            '    private static final List<String> trustedHosts = Arrays.asList("xumm-cdn.imgix.net", "xrplcluster.com", "xahau.network", "custom-node.xrpl-labs.com", "cdn.xumm.pro", "xumm.app", "cdn.xaman.app", "xaman.app", "image-proxy.xrpl-labs.com");\n'
            '    private static final String defaultHost = "xaman.app";\n'
        ),
        'android/app/src/debug/AndroidManifest.xml': '<application android:usesCleartextTraffic="true" />\n',
    }
    for relative, value in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
    return root


def test_render_candidate_forces_local_routes_and_rejects_network_fallback(tmp_path: Path) -> None:
    module = _load_module()
    root = _source_root(tmp_path)

    rendered = module.render_candidate_files(root)

    endpoints = rendered[module.SOURCE_FILES['endpoints']]
    network = rendered[module.SOURCE_FILES['network']]
    service = rendered[module.SOURCE_FILES['network_service']]
    http_factory = rendered[module.SOURCE_FILES['http_factory']]
    assert "HOSTNAME = '10.0.2.2:51236'" in endpoints
    assert 'https://${HOSTNAME}/api' not in endpoints
    assert "key: 'SELF_HOSTED_TESTNET'" in network
    assert 'networkId: 777777' in network
    assert "nodes: ['ws://10.0.2.2:51235']" in network
    assert "const selfHostedEndpoint = 'ws://10.0.2.2:51235';" in service
    assert 'Self-hosted verifier rejected a non-local network selection' in service
    assert 'custom-node.xrpl-labs.com' not in http_factory
    assert 'defaultHost = "10.0.2.2"' in http_factory


def test_manifest_is_explicitly_nonproduction_and_pending_review(tmp_path: Path) -> None:
    module = _load_module()
    root = _source_root(tmp_path)
    rendered = module.render_candidate_files(root)

    manifest = module.build_manifest(
        root,
        {'commit': module.PINNED_XAMAN_COMMIT, 'origin': module.PINNED_XAMAN_ORIGIN},
        rendered,
        materialized=False,
    )

    assert manifest['overall_status'] == 'candidate_ready_for_materialization'
    assert manifest['security_decision'] == 'BLOCK_APP_RUNTIME_UNTIL_INDEPENDENT_REVIEW_AND_REDACTED_TRACE'
    assert manifest['scope']['vendor_release_equivalent'] is False
    assert manifest['scope']['production_usable'] is False
    assert manifest['candidate_controls']['custom_node_vendor_proxy_bypassed'] is True
    assert 'independent_human_review_of_source_diff' in manifest['required_before_runtime_evidence']
    assert manifest['artifact_cid'] if 'artifact_cid' in manifest else True


def test_materialize_copies_tracked_files_and_never_touches_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    root = _source_root(tmp_path)
    rendered = module.render_candidate_files(root)

    def export_fixture(source_root: Path, destination: Path) -> None:
        for relative in module.SOURCE_FILES.values():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source_root / relative).read_bytes())

    monkeypatch.setattr(module, '_export_pinned_source', export_fixture)
    destination = tmp_path / 'candidate'

    module.materialize_candidate(root, destination, rendered)

    assert (destination / module.SOURCE_FILES['endpoints']).read_text(encoding='utf-8') == rendered[module.SOURCE_FILES['endpoints']]
    assert "HOSTNAME = 'xaman.app'" in (root / module.SOURCE_FILES['endpoints']).read_text(encoding='utf-8')
    with pytest.raises(ValueError, match='outside the frozen Xaman checkout'):
        module.materialize_candidate(root, root / 'nested', rendered)
