"""Tests for PORTAL-CXTP-125 Xaman Testnet network-selection evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'capture_xaman_testnet_network_selection.py'
)
ARTIFACT_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'runtime'
    / 'testnet-network-selection-report.json'
)
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_testnet_network_selection.md'


def _load_module():
    spec = importlib.util.spec_from_file_location('capture_xaman_testnet_network_selection', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load network-selection capture script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _selection(endpoint: str = 'wss://s.altnet.rippletest.net:51233') -> dict:
    return {
        'schema_version': 'xaman-testnet-selection-evidence/v1',
        'evidence_type': 'deterministic_local_state',
        'fresh_emulator_profile': True,
        'network_key': 'TESTNET',
        'endpoint': endpoint,
        'event_categories': [
            'fresh_emulator_profile',
            'deterministic_testnet_local_state',
            'xaman_network_selected',
            'xrpl_server_info_observed',
            'fresh_testnet_account_boundary',
            'fresh_testnet_account_created',
        ],
        'fresh_account': {
            'created': True,
            'imported_account': False,
            'production_account': False,
            'account_material_recorded': False,
        },
    }


def _selection_with_network(network_key: str) -> dict:
    selection = _selection()
    selection['network_key'] = network_key
    return selection


def _selection_without_account_creation() -> dict:
    selection = _selection()
    selection['event_categories'] = [
        category for category in selection['event_categories'] if category != 'fresh_testnet_account_created'
    ]
    selection['fresh_account']['created'] = False
    return selection


def _reviewed_ui_selection() -> dict:
    selection = _selection()
    selection['evidence_type'] = 'reviewed_ui'
    selection['event_categories'] = [
        category for category in selection['event_categories'] if category != 'deterministic_testnet_local_state'
    ]
    selection['event_categories'].append('reviewed_ui_testnet_selection')
    return selection


def _server_info(network_id: int = 1) -> dict:
    return {
        'id': 'server_info',
        'status': 'success',
        'type': 'response',
        'result': {
            'info': {
                'network_id': network_id,
                'server_state': 'full',
                'validated_ledger': {'seq': 1000},
            }
        },
    }


def _network_constants(path: Path, nodes: str | None = None) -> Path:
    node_list = nodes or "'wss://testnet.xrpl-labs.com', 'wss://s.altnet.rippletest.net:51233'"
    path.write_text(
        '''
        export default {
          networks: [
            { key: 'MAINNET', networkId: 0, nodes: ['wss://xrplcluster.com'] },
            {
              name: 'XRPL Testnet',
              key: 'TESTNET',
              networkId: 1,
              nodes: ['''
        + node_list
        + '''],
            },
          ],
        };
        ''',
        encoding='utf-8',
    )
    return path


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, sort_keys=True), encoding='utf-8')
    return path


def _telemetry_report(path: Path, *, build_provenance_sha256: str = 'a' * 64) -> Path:
    return _write_json(
        path,
        {
            'schema_version': 'xaman-firebase-disabled-testnet-telemetry/v1',
            'task_id': 'PORTAL-CXTP-120',
            'artifact_cid': 'sha256:' + ('b' * 64),
            'xaman_commit': '942f43876265a7af44f233288ad2b1d00841d5fa',
            'build_provenance_sha256': build_provenance_sha256,
            'firebase_mode': 'disabled',
            'telemetry_sink': 'duckdb',
            'accepted_event_count': 4,
            'rejected_event_count': 0,
            'security_decision': 'TESTNET_FIREBASE_DISABLED_TELEMETRY_CAPTURED_NOT_PRODUCTION_EVIDENCE',
        },
    )


def _build_manifest(path: Path, *, artifact_cid: str = 'sha256:' + ('d' * 64)) -> Path:
    return _write_json(
        path,
        {
            'schema_version': 'xaman-firebase-disabled-testnet-build/v1',
            'task_id': 'PORTAL-CXTP-119',
            'artifact_cid': artifact_cid,
        },
    )


def _rnn_compat_overlay(path: Path) -> Path:
    path.write_text(
        'class ReactTypefaceUtils {\n'
        '  private static final int UNSET = -1;\n'
        '  int a = UNSET;\n'
        '  int b = UNSET;\n'
        '}\n',
        encoding='utf-8',
    )
    return path


def test_build_report_verifies_testnet_selection_without_raw_endpoint_storage(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')
    telemetry_report = _telemetry_report(tmp_path / 'telemetry-report.json')
    rnn_compat_overlay = _rnn_compat_overlay(tmp_path / 'ReactTypefaceUtils.java')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        telemetry_report_path=telemetry_report,
        rnn_compat_overlay_path=rnn_compat_overlay,
        run_id='testnet-network-selection-fixture',
        build_provenance_sha256='a' * 64,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['schema_version'] == 'xaman-testnet-network-selection/v1'
    assert report['task_id'] == 'PORTAL-CXTP-125'
    assert report['overall_status'] == 'verified'
    assert report['selection']['network_key'] == 'TESTNET'
    assert report['endpoint_allow_list_decision']['allowed'] is True
    assert report['endpoint_allow_list_decision']['matched_endpoint_key'] == 'ripple_altnet_testnet'
    assert report['source_network_definition']['nodes_match_allow_list'] is True
    assert report['source_network_definition']['source_endpoint_keys'] == [
        'ripple_altnet_testnet',
        'xrpl_labs_testnet',
    ]
    assert report['selected_endpoint_source_binding'] == {
        'selected_endpoint_key': 'ripple_altnet_testnet',
        'selected_endpoint_sha256': report['endpoint_allow_list_decision']['matched_endpoint_sha256'],
        'source_nodes_include_selected_endpoint': True,
    }
    assert (
        report['evidence_inputs']['server_info_request_sha256']
        == '6a1a5cf3644551cf735838bfa1ada32fe420c979bac41dd497fbc13f229070c3'
    )
    assert (
        report['xrpl_server_info_binding']['request_sha256']
        == report['evidence_inputs']['server_info_request_sha256']
    )
    assert report['xrpl_server_info_binding']['network_id'] == 1
    assert report['xrpl_server_info_binding']['network_id_verified'] is True
    assert report['xrpl_server_info_binding']['raw_request_body_recorded'] is False
    assert report['xrpl_server_info_binding']['raw_response_recorded'] is False
    assert report['fresh_account_boundary']['fresh_account_created'] is True
    assert report['fresh_account_boundary']['account_material_recorded'] is False
    assert report['evidence_inputs']['testnet_telemetry_report']['task_id'] == 'PORTAL-CXTP-120'
    assert report['evidence_inputs']['react_native_navigation_compat_overlay']['task_id'] == 'PORTAL-CXTP-123'
    assert (
        report['evidence_inputs']['react_native_navigation_compat_overlay'][
            'reviewed_two_reference_replacement_present'
        ]
        is True
    )
    assert report['blocking_gaps'] == []
    assert {'RUNTIME_EQUIVALENCE_NOT_PROVED'} <= {
        boundary['code'] for boundary in report['residual_boundaries']
    }
    rendered = json.dumps(report, sort_keys=True)
    assert 'wss://s.altnet.rippletest.net:51233' not in rendered
    assert 'wss://testnet.xrpl-labs.com' not in rendered
    assert report['artifact_cid'].startswith('sha256:')


def test_build_report_accepts_reviewed_ui_testnet_selection_evidence(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _reviewed_ui_selection())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'verified'
    assert report['selection']['evidence_type'] == 'reviewed_ui'
    assert 'reviewed_ui_testnet_selection' in report['selection']['event_categories']


def test_build_report_accepts_fresh_profile_without_account_creation_when_boundary_matches(
    tmp_path: Path,
) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection_without_account_creation())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'verified'
    assert report['fresh_account_boundary']['fresh_account_created'] is False
    assert 'fresh_testnet_account_created' not in report['selection']['event_categories']


def test_build_report_fails_closed_when_evidence_type_category_is_missing(tmp_path: Path) -> None:
    module = _load_module()
    selection = _selection()
    selection['event_categories'] = [
        category for category in selection['event_categories'] if category != 'deterministic_testnet_local_state'
    ]
    selection_path = _write_json(tmp_path / 'selection.json', selection)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {'DETERMINISTIC_TESTNET_LOCAL_STATE_EVENT_MISSING'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_build_report_fails_closed_for_non_testnet_selection(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection_with_network('MAINNET'))
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {'XAMAN_SELECTED_NETWORK_NOT_TESTNET'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_build_report_fails_closed_for_non_testnet_endpoint(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection(endpoint='wss://xrplcluster.com'))
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_TESTNET_NETWORK_SELECTION_EVIDENCE_FAILURE'
    assert report['endpoint_allow_list_decision']['allowed'] is False
    assert {'ENDPOINT_NOT_ALLOW_LISTED'} <= {blocker['code'] for blocker in report['blocking_gaps']}


def test_build_report_rejects_path_bearing_endpoint_before_report_emission(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(
        tmp_path / 'selection.json',
        _selection(endpoint='wss://s.altnet.rippletest.net:51233/'),
    )
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(ValueError, match='endpoint must not include a path'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_build_report_fails_closed_for_wrong_server_info_network(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info(network_id=0))
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert report['xrpl_server_info_binding']['network_id'] == 0
    assert {'XRPL_SERVER_INFO_NETWORK_ID_NOT_TESTNET'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_build_report_fails_closed_for_invalid_server_info_shape(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(
        tmp_path / 'server-info.json',
        {'status': 'success', 'network_id': 1, 'note': 'not an XRPL server_info response'},
    )
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert report['xrpl_server_info_binding']['network_id'] == 1
    assert {'XRPL_SERVER_INFO_SHAPE_INVALID'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_build_report_fails_closed_when_server_info_response_type_is_not_response(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    invalid_response = _server_info()
    invalid_response['type'] = 'error'
    server_info_path = _write_json(tmp_path / 'server-info.json', invalid_response)
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {'XRPL_SERVER_INFO_TYPE_NOT_RESPONSE'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_build_report_fails_closed_when_server_info_response_id_is_not_bound(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    invalid_response = _server_info()
    invalid_response['id'] = 'account_info'
    server_info_path = _write_json(tmp_path / 'server-info.json', invalid_response)
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {'XRPL_SERVER_INFO_ID_NOT_BOUND_TO_REQUEST'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_build_report_fails_closed_when_required_event_category_is_missing(tmp_path: Path) -> None:
    module = _load_module()
    selection = _selection()
    selection['event_categories'] = [
        category for category in selection['event_categories'] if category != 'xaman_network_selected'
    ]
    selection_path = _write_json(tmp_path / 'selection.json', selection)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {'REQUIRED_EVENT_CATEGORIES_MISSING'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_build_report_fails_closed_when_fresh_account_created_event_is_missing(tmp_path: Path) -> None:
    module = _load_module()
    selection = _selection()
    selection['event_categories'] = [
        category for category in selection['event_categories'] if category != 'fresh_testnet_account_created'
    ]
    selection_path = _write_json(tmp_path / 'selection.json', selection)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {'FRESH_ACCOUNT_CREATED_EVENT_MISSING'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_build_report_fails_closed_when_fresh_account_created_event_is_inconsistent(tmp_path: Path) -> None:
    module = _load_module()
    selection = _selection()
    selection['fresh_account']['created'] = False
    selection_path = _write_json(tmp_path / 'selection.json', selection)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {'FRESH_ACCOUNT_CREATED_EVENT_INCONSISTENT'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_build_report_fails_closed_when_source_allow_list_does_not_match(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts', nodes="'wss://testnet.xrpl-labs.com'")

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert report['source_network_definition']['nodes_match_allow_list'] is False
    assert {'XAMAN_TESTNET_SOURCE_ALLOW_LIST_MISMATCH'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_source_network_assessment_handles_long_testnet_object(tmp_path: Path) -> None:
    module = _load_module()
    network_constants = tmp_path / 'network.ts'
    network_constants.write_text(
        """
        export default {
          networks: [
            { key: 'MAINNET', networkId: 0, nodes: ['wss://xrplcluster.com'] },
            {
              name: 'XRPL Testnet',
              key: 'TESTNET',
              metadata: {
                icon: '"""
        + ('A' * 1200)
        + """',
              },
              networkId: 1,
              nodes: ['wss://testnet.xrpl-labs.com', 'wss://s.altnet.rippletest.net:51233'],
            },
          ],
        };
        """,
        encoding='utf-8',
    )

    assessment = module._network_constants_assessment(network_constants)

    assert assessment['status'] == 'pass'
    assert assessment['source_network_id'] == 1
    assert assessment['source_endpoint_keys'] == ['ripple_altnet_testnet', 'xrpl_labs_testnet']
    assert assessment['source_endpoint_sha256'] == [
        '4fec7353473e20acda0ecff414da21a36766437c2a79db6332c135233b776d3a',
        'a81289bc29208d10634e2b0c40a94ec0c664f0c3bb1574d742ce8054b7f9abca',
    ]
    assert assessment['nodes_match_allow_list'] is True


def test_source_network_assessment_accepts_same_allow_list_in_source_order(tmp_path: Path) -> None:
    module = _load_module()
    network_constants = _network_constants(
        tmp_path / 'network.ts',
        nodes="'wss://s.altnet.rippletest.net:51233', 'wss://testnet.xrpl-labs.com'",
    )

    assessment = module._network_constants_assessment(network_constants)

    assert assessment['status'] == 'pass'
    assert assessment['source_endpoint_count'] == 2
    assert assessment['nodes_match_allow_list'] is True


def test_source_network_assessment_accepts_double_quoted_testnet_key(tmp_path: Path) -> None:
    module = _load_module()
    network_constants = tmp_path / 'network.ts'
    network_constants.write_text(
        '''
        export default {
          networks: [
            {
              name: "XRPL Testnet",
              key: "TESTNET",
              networkId: 1,
              nodes: ["wss://testnet.xrpl-labs.com", "wss://s.altnet.rippletest.net:51233"],
            },
          ],
        };
        ''',
        encoding='utf-8',
    )

    assessment = module._network_constants_assessment(network_constants)

    assert assessment['status'] == 'pass'
    assert assessment['source_network_key'] == 'TESTNET'
    assert assessment['source_network_id'] == 1
    assert assessment['nodes_match_allow_list'] is True


def test_source_network_assessment_handles_nested_object_before_testnet_key(tmp_path: Path) -> None:
    module = _load_module()
    network_constants = tmp_path / 'network.ts'
    network_constants.write_text(
        '''
        export default {
          networks: [
            {
              display: { label: 'XRPL Testnet', category: 'test' },
              key: 'TESTNET',
              networkId: 1,
              nodes: ['wss://testnet.xrpl-labs.com', 'wss://s.altnet.rippletest.net:51233'],
            },
          ],
        };
        ''',
        encoding='utf-8',
    )

    assessment = module._network_constants_assessment(network_constants)

    assert assessment['status'] == 'pass'
    assert assessment['source_network_key'] == 'TESTNET'
    assert assessment['source_network_id'] == 1
    assert assessment['nodes_match_allow_list'] is True


def test_source_network_assessment_accepts_typescript_whitespace_around_colons(tmp_path: Path) -> None:
    module = _load_module()
    network_constants = tmp_path / 'network.ts'
    network_constants.write_text(
        '''
        export default {
          networks: [
            {
              key: 'TESTNET',
              networkId : 1,
              nodes : ['wss://testnet.xrpl-labs.com', 'wss://s.altnet.rippletest.net:51233'],
            },
          ],
        };
        ''',
        encoding='utf-8',
    )

    assessment = module._network_constants_assessment(network_constants)

    assert assessment['status'] == 'pass'
    assert assessment['source_network_id'] == 1
    assert assessment['nodes_match_allow_list'] is True


def test_source_network_assessment_rejects_duplicate_allow_list_node(tmp_path: Path) -> None:
    module = _load_module()
    network_constants = _network_constants(
        tmp_path / 'network.ts',
        nodes="'wss://testnet.xrpl-labs.com', 'wss://testnet.xrpl-labs.com'",
    )

    assessment = module._network_constants_assessment(network_constants)

    assert assessment['status'] == 'blocked'
    assert assessment['source_endpoint_count'] == 2
    assert assessment['source_endpoint_keys'] == ['xrpl_labs_testnet', 'xrpl_labs_testnet']
    assert assessment['nodes_match_allow_list'] is False


def test_redaction_boundary_rejects_account_seed_payload_transaction_and_raw_body_material(tmp_path: Path) -> None:
    module = _load_module()
    sensitive = _selection()
    sensitive['fresh_account']['account_address'] = 'rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh'
    sensitive['seed'] = 'sn259rEFXrQrWyx3Q7XneWcwV6dfL'
    sensitive['payload'] = {'tx_blob': 'A' * 128}
    sensitive['raw_response_body'] = {'command': 'server_info'}
    selection_path = _write_json(tmp_path / 'selection.json', sensitive)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_rejects_sensitive_server_info_input(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    sensitive_server_info = _server_info()
    sensitive_server_info['request_body'] = {'command': 'server_info'}
    sensitive_server_info['result']['info']['account_address'] = 'rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh'
    server_info_path = _write_json(tmp_path / 'server-info.json', sensitive_server_info)
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_rejects_raw_request_key_variant(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    sensitive_server_info = _server_info()
    sensitive_server_info['request'] = {'command': 'server_info'}
    server_info_path = _write_json(tmp_path / 'server-info.json', sensitive_server_info)
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError, match='forbidden key: request'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_rejects_raw_server_info_request_body_by_shape(tmp_path: Path) -> None:
    module = _load_module()
    sensitive = _selection()
    sensitive['review_context'] = {'body': {'command': 'server_info', 'id': 'server_info'}}
    selection_path = _write_json(tmp_path / 'selection.json', sensitive)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError, match='forbidden key: body'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_rejects_top_level_raw_server_info_request_body(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(
        tmp_path / 'server-info.json',
        {'command': 'server_info', 'id': 'server_info'},
    )
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError, match='raw server_info request body'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_rejects_stringified_raw_server_info_request_body(tmp_path: Path) -> None:
    module = _load_module()
    sensitive = _selection()
    sensitive['review_context'] = {
        'note': 'captured request: {"command":"server_info","id":"server_info"}',
    }
    selection_path = _write_json(tmp_path / 'selection.json', sensitive)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError, match='raw server_info request body'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_allows_explicit_response_and_request_digests(tmp_path: Path) -> None:
    module = _load_module()
    selection = _selection()
    selection['review_context'] = {
        'endpoint_sha256': 'a' * 64,
        'request_sha256': 'b' * 64,
        'response_sha256': 'c' * 64,
        'server_info_response_sha256': 'd' * 64,
    }
    selection_path = _write_json(tmp_path / 'selection.json', selection)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'verified'


def test_redaction_boundary_rejects_raw_response_digest_key(tmp_path: Path) -> None:
    module = _load_module()
    sensitive = _selection()
    sensitive['review_context'] = {'rawResponseSha256': 'a' * 64}
    selection_path = _write_json(tmp_path / 'selection.json', sensitive)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError, match='forbidden key: rawResponseSha256'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_rejects_camelcase_transaction_blob_key(tmp_path: Path) -> None:
    module = _load_module()
    sensitive = _selection()
    sensitive['review_context'] = {'txBlob': 'redacted-by-key-even-without-raw-hex'}
    selection_path = _write_json(tmp_path / 'selection.json', sensitive)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError, match='forbidden key: txBlob'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_rejects_sensitive_build_manifest_input(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')
    build_manifest = _write_json(
        tmp_path / 'build-manifest.json',
        {'schema_version': 'xaman-firebase-disabled-testnet-build/v1', 'token': 'secret'},
    )

    with pytest.raises(module.RedactionBoundaryError, match='build kit manifest contains forbidden key: token'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            build_kit_manifest_path=build_manifest,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_rejects_sensitive_telemetry_dependency_input(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')
    telemetry_report = _write_json(
        tmp_path / 'telemetry-report.json',
        {
            'schema_version': 'xaman-firebase-disabled-testnet-telemetry/v1',
            'task_id': 'PORTAL-CXTP-120',
            'artifact_cid': 'sha256:' + ('b' * 64),
            'xaman_commit': '942f43876265a7af44f233288ad2b1d00841d5fa',
            'firebase_mode': 'disabled',
            'security_decision': 'TESTNET_FIREBASE_DISABLED_TELEMETRY_CAPTURED_NOT_PRODUCTION_EVIDENCE',
            'events': [{'account_address': 'rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh'}],
        },
    )

    with pytest.raises(module.RedactionBoundaryError, match='telemetry report contains forbidden key: account_address'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            telemetry_report_path=telemetry_report,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_build_report_fails_closed_when_telemetry_dependency_contradicts_build_digest(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')
    telemetry_report = _telemetry_report(tmp_path / 'telemetry-report.json', build_provenance_sha256='c' * 64)

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        telemetry_report_path=telemetry_report,
        build_provenance_sha256='a' * 64,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {'TESTNET_TELEMETRY_REPORT_BUILD_DIGEST_MISMATCH'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_build_report_fails_closed_when_dependency_artifact_cids_are_malformed(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')
    build_manifest = _build_manifest(tmp_path / 'build-manifest.json', artifact_cid='not-a-sha256-cid')
    telemetry_report = _write_json(
        tmp_path / 'telemetry-report.json',
        {
            'schema_version': 'xaman-firebase-disabled-testnet-telemetry/v1',
            'task_id': 'PORTAL-CXTP-120',
            'artifact_cid': 'sha256:not-hex',
            'xaman_commit': '942f43876265a7af44f233288ad2b1d00841d5fa',
            'firebase_mode': 'disabled',
            'security_decision': 'TESTNET_FIREBASE_DISABLED_TELEMETRY_CAPTURED_NOT_PRODUCTION_EVIDENCE',
        },
    )

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        build_kit_manifest_path=build_manifest,
        telemetry_report_path=telemetry_report,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {
        'TESTNET_BUILD_MANIFEST_ARTIFACT_CID_INVALID',
        'TESTNET_TELEMETRY_REPORT_ARTIFACT_CID_INVALID',
    } <= {blocker['code'] for blocker in report['blocking_gaps']}


def test_build_report_fails_closed_when_rnn_overlay_is_not_reviewed_replacement(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')
    rnn_overlay = tmp_path / 'ReactTypefaceUtils.java'
    rnn_overlay.write_text('int stale = ReactTextShadowNode.UNSET;\n', encoding='utf-8')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        rnn_compat_overlay_path=rnn_overlay,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert {'RNN_COMPAT_OVERLAY_NOT_REVIEWED_REPLACEMENT'} <= {
        blocker['code'] for blocker in report['blocking_gaps']
    }


def test_redaction_boundary_rejects_xaddress_material(tmp_path: Path) -> None:
    module = _load_module()
    sensitive = _selection()
    sensitive['fresh_account']['note'] = 'T7pLeLnxcNWj6sXWzH9jSr6T5TkHqQ4rtVFGW9LjvjiLJ6Y'
    selection_path = _write_json(tmp_path / 'selection.json', sensitive)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError, match='X-address'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_rejects_api_key_and_jwt_material(tmp_path: Path) -> None:
    module = _load_module()
    sensitive = _selection()
    sensitive['review_context'] = {
        'apiKey': 'never-store-this',
        'note': (
            'credential '
            'eyJhbGciOiJIUzI1NiJ9.'
            'eyJzdWIiOiJ0ZXN0bmV0LXZlcmlmaWVyIn0.'
            'bXlzaWduYXR1cmVmaXh0dXJl'
        ),
    }
    selection_path = _write_json(tmp_path / 'selection.json', sensitive)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_rejects_plural_sensitive_key_variants(tmp_path: Path) -> None:
    module = _load_module()
    sensitive = _selection()
    sensitive['review_context'] = {
        'credentials': {'label': 'do-not-store'},
        'apiKeys': ['do-not-store'],
    }
    selection_path = _write_json(tmp_path / 'selection.json', sensitive)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_redaction_boundary_rejects_bearer_credential_in_free_text(tmp_path: Path) -> None:
    module = _load_module()
    sensitive = _selection()
    sensitive['review_context'] = {
        'note': 'debug header Authorization: Bearer abcdefghijklmnop123456',
    }
    selection_path = _write_json(tmp_path / 'selection.json', sensitive)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(module.RedactionBoundaryError, match='bearer credential'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_blocking_gaps_are_deduplicated(tmp_path: Path) -> None:
    module = _load_module()
    selection = _selection()
    selection['event_categories'] = [
        category for category in selection['event_categories'] if category != 'xrpl_server_info_observed'
    ]
    selection_path = _write_json(tmp_path / 'selection.json', selection)
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    report = module.build_report(
        selection_evidence_path=selection_path,
        server_info_response_path=server_info_path,
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    codes = [blocker['code'] for blocker in report['blocking_gaps']]
    assert codes.count('SERVER_INFO_EVENT_CATEGORY_MISSING') == 1
    assert codes.count('REQUIRED_EVENT_CATEGORIES_MISSING') == 1


def test_report_redaction_audit_rejects_raw_endpoint_leak() -> None:
    module = _load_module()
    with pytest.raises(module.RedactionBoundaryError, match='raw WebSocket endpoint'):
        module._assert_report_redaction_boundary({'leak': 'wss://s.altnet.rippletest.net:51233'})


def test_report_redaction_audit_rejects_stringified_raw_request_body_leak() -> None:
    module = _load_module()
    with pytest.raises(module.RedactionBoundaryError, match='raw server_info request body'):
        module._assert_report_redaction_boundary(
            {'leak': '{"id":"server_info","command":"server_info"}'}
        )


def test_report_redaction_audit_rejects_raw_server_info_response_body_leak() -> None:
    module = _load_module()
    with pytest.raises(module.RedactionBoundaryError, match='raw server_info response body'):
        module._assert_report_redaction_boundary({'leak': _server_info()})


def test_report_redaction_audit_rejects_credential_value_leak() -> None:
    module = _load_module()
    with pytest.raises(module.RedactionBoundaryError, match='bearer credential'):
        module._assert_report_redaction_boundary({'leak': 'Authorization: Bearer abcdefghijklmnop123456'})


def test_generated_timestamp_must_be_utc_second_precision(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(ValueError, match='generated_at_utc'):
        module.build_report(
            selection_evidence_path=selection_path,
            server_info_response_path=server_info_path,
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z wss://s.altnet.rippletest.net:51233',
        )


def test_live_capture_uses_allow_list_and_omits_raw_request_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    network_constants = _network_constants(tmp_path / 'network.ts')
    sent_messages: list[str] = []

    class FakeWebSocket:
        def send(self, payload: str) -> None:
            sent_messages.append(payload)

        def recv(self) -> str:
            return json.dumps(_server_info(), sort_keys=True)

        def close(self) -> None:
            return None

    def create_connection(endpoint: str, *, timeout: float) -> FakeWebSocket:
        assert endpoint == 'wss://s.altnet.rippletest.net:51233'
        assert timeout == 3.0
        return FakeWebSocket()

    monkeypatch.setitem(sys.modules, 'websocket', SimpleNamespace(create_connection=create_connection))

    report = module.build_report(
        selection_evidence_path=selection_path,
        live_endpoint='wss://s.altnet.rippletest.net:51233',
        network_constants_path=network_constants,
        generated_at_utc='2026-07-10T00:00:00Z',
        live_timeout=3.0,
    )

    assert sent_messages == ['{"command":"server_info","id":"server_info"}']
    assert report['overall_status'] == 'verified'
    assert report['evidence_inputs']['server_info_response_source'] == 'live_websocket_server_info'
    assert (
        report['xrpl_server_info_binding']['request_sha256']
        == '6a1a5cf3644551cf735838bfa1ada32fe420c979bac41dd497fbc13f229070c3'
    )
    assert report['xrpl_server_info_binding']['raw_request_body_recorded'] is False
    assert sent_messages[0] not in json.dumps(report, sort_keys=True)


def test_live_capture_rejects_endpoint_that_does_not_match_selection_evidence(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    network_constants = _network_constants(tmp_path / 'network.ts')

    with pytest.raises(ValueError, match='live endpoint must match'):
        module.build_report(
            selection_evidence_path=selection_path,
            live_endpoint='wss://testnet.xrpl-labs.com',
            network_constants_path=network_constants,
            generated_at_utc='2026-07-10T00:00:00Z',
        )


def test_cli_defaults_bind_testnet_dependency_evidence_paths() -> None:
    module = _load_module()

    args = module._parse_args(
        [
            'report',
            '--selection-evidence',
            'selection.json',
            '--server-info-response',
            'server-info.json',
        ]
    )

    assert args.telemetry_report == module.DEFAULT_TELEMETRY_REPORT
    assert args.rnn_compat_overlay == module.DEFAULT_RNN_COMPAT_OVERLAY


def test_checked_artifact_and_documentation_are_present_and_redacted() -> None:
    module = _load_module()

    assert DOC_PATH.is_file()
    report = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))

    assert report['schema_version'] == 'xaman-testnet-network-selection/v1'
    assert report['task_id'] == 'PORTAL-CXTP-125'
    assert report['overall_status'] == 'verified'
    assert report['selection']['network_key'] == 'TESTNET'
    assert report['endpoint_allow_list_decision']['allowed'] is True
    assert report['xrpl_server_info_binding']['network_id_verified'] is True
    assert report['xrpl_server_info_binding']['network_id'] == 1
    assert report['redaction_boundary'][
        'records_only_event_categories_network_key_endpoint_decision_and_digests'
    ] is True
    assert report['evidence_inputs']['testnet_telemetry_report']['task_id'] == 'PORTAL-CXTP-120'
    assert report['evidence_inputs']['react_native_navigation_compat_overlay']['task_id'] == 'PORTAL-CXTP-123'
    module._assert_report_redaction_boundary(report)


def test_cli_writes_verified_report(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection())
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')
    telemetry_report = _telemetry_report(tmp_path / 'telemetry-report.json', build_provenance_sha256='b' * 64)
    rnn_compat_overlay = _rnn_compat_overlay(tmp_path / 'ReactTypefaceUtils.java')
    out = tmp_path / 'report.json'

    rc = module.main(
        [
            'report',
            '--selection-evidence',
            str(selection_path),
            '--server-info-response',
            str(server_info_path),
            '--network-constants',
            str(network_constants),
            '--telemetry-report',
            str(telemetry_report),
            '--rnn-compat-overlay',
            str(rnn_compat_overlay),
            '--build-provenance-sha256',
            'b' * 64,
            '--generated-at-utc',
            '2026-07-10T00:00:00Z',
            '--out',
            str(out),
        ]
    )

    assert rc == 0
    written = json.loads(out.read_text(encoding='utf-8'))
    assert written['overall_status'] == 'verified'
    assert written['security_decision'] == 'TESTNET_NETWORK_SELECTION_VERIFIED_NOT_PRODUCTION_EVIDENCE'


def test_cli_returns_nonzero_for_blocked_report(tmp_path: Path) -> None:
    module = _load_module()
    selection_path = _write_json(tmp_path / 'selection.json', _selection_with_network('MAINNET'))
    server_info_path = _write_json(tmp_path / 'server-info.json', _server_info())
    network_constants = _network_constants(tmp_path / 'network.ts')
    out = tmp_path / 'report.json'

    rc = module.main(
        [
            'report',
            '--selection-evidence',
            str(selection_path),
            '--server-info-response',
            str(server_info_path),
            '--network-constants',
            str(network_constants),
            '--generated-at-utc',
            '2026-07-10T00:00:00Z',
            '--out',
            str(out),
        ]
    )

    assert rc == 2
    written = json.loads(out.read_text(encoding='utf-8'))
    assert written['overall_status'] == 'blocked'
    assert written['security_decision'] == 'BLOCK_TESTNET_NETWORK_SELECTION_EVIDENCE_FAILURE'


def test_checked_artifact_and_document_exist() -> None:
    module = _load_module()
    report = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))
    assert report['schema_version'] == 'xaman-testnet-network-selection/v1'
    assert report['task_id'] == 'PORTAL-CXTP-125'
    assert report['overall_status'] == 'verified'
    assert report['selection']['network_key'] == 'TESTNET'
    assert report['endpoint_allow_list_decision']['allowed'] is True
    assert report['selected_endpoint_source_binding']['source_nodes_include_selected_endpoint'] is True
    assert report['xrpl_server_info_binding']['network_id'] == 1
    assert report['xrpl_server_info_binding']['network_id_verified'] is True
    assert (
        report['evidence_inputs']['server_info_request_sha256']
        == report['xrpl_server_info_binding']['request_sha256']
    )
    assert report['redaction_boundary']['records_only_event_categories_network_key_endpoint_decision_and_digests'] is True
    assert report['redaction_boundary']['raw_request_bodies_recorded'] is False
    assert report['redaction_boundary']['raw_server_info_response_recorded'] is False
    assert report['production_release_blocked'] is True
    assert report['runtime_equivalence_status'] == 'not_proved'
    assert report['blocking_gaps'] == []
    assert {'RUNTIME_EQUIVALENCE_NOT_PROVED'} <= {
        boundary['code'] for boundary in report['residual_boundaries']
    }
    canonical = json.dumps(
        {key: value for key, value in report.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    assert report['artifact_cid'] == 'sha256:' + module._sha256_bytes(canonical)
    rendered = json.dumps(report, sort_keys=True)
    assert 'wss://' not in rendered
    assert 'rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh' not in rendered
    assert 'sn259rEFXrQrWyx3Q7XneWcwV6dfL' not in rendered

    doc = DOC_PATH.read_text(encoding='utf-8')
    assert 'PORTAL-CXTP-125' in doc
    assert 'TESTNET' in doc
    assert 'network_id: 1' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json' in doc
