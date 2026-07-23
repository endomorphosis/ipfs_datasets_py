#!/usr/bin/env python3
"""Prepare a Firebase-disabled Xaman Testnet build and capture local telemetry.

This tool never changes the Xaman checkout.  ``prepare`` writes an external
Gradle init script, Metro configuration, and Firebase module stubs. The stubs
send only categorical events to an optional loopback-only DuckDB Firebase mock
and otherwise emit telemetry markers for ``ingest`` to validate and store. It
deliberately does not claim runtime equivalence or production assurance.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import textwrap
from typing import Any
from urllib.parse import urlparse


BUILD_SCHEMA_VERSION = 'xaman-firebase-disabled-testnet-build/v1'
TELEMETRY_SCHEMA_VERSION = 'xaman-firebase-disabled-testnet-telemetry/v1'
TASK_BUILD_ID = 'PORTAL-CXTP-119'
TASK_TELEMETRY_ID = 'PORTAL-CXTP-120'
TASK_FIREBASE_MOCK_ID = 'PORTAL-CXTP-127'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
TELEMETRY_MARKER = 'XAMAN_TESTNET_TELEMETRY:'
FIREBASE_MODULES = ('analytics', 'crashlytics', 'messaging')
FIREBASE_MOCK_PATH = '/v1/events'
FIREBASE_MOCK_HEALTH_PATH = '/v1/health'
FIREBASE_MOCK_ALLOWED_HOSTS = frozenset({'127.0.0.1', '::1', 'localhost', '10.0.2.2'})
FIREBASE_MOCK_BIND_HOSTS = frozenset({'127.0.0.1', '::1'})
FIREBASE_MOCK_MAX_BODY_BYTES = 16 * 1024
ALLOWED_ATTRIBUTE_KEYS = {
    'arg_count',
    'build_variant',
    'error_class',
    'operation',
    'reason_code',
    'source',
}
SENSITIVE_KEY_PARTS = (
    'address',
    'authorization',
    'credential',
    'mnemonic',
    'passcode',
    'password',
    'payload',
    'private',
    'seed',
    'secret',
    'token',
    'transaction',
    'tx_blob',
)
IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,160}$')
EVENT_RE = re.compile(r'^[a-z][a-z0-9_.-]{0,119}$')


class TelemetryValidationError(ValueError):
    """Raised when a test telemetry event violates the redaction contract."""


def _validate_firebase_mock_endpoint(endpoint: str) -> str:
    """Allow only the local verifier's Firebase mock endpoint.

    Android emulators reach the host loopback service through ``10.0.2.2``.
    This prevents a verifier build from being configured to export telemetry to
    an arbitrary remote endpoint.
    """
    parsed = urlparse(endpoint)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError('firebase_mock_endpoint must use a valid port') from exc
    if (
        parsed.scheme != 'http'
        or parsed.hostname not in FIREBASE_MOCK_ALLOWED_HOSTS
        or parsed.path != FIREBASE_MOCK_PATH
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or port is None
    ):
        raise ValueError(
            'firebase_mock_endpoint must be an http loopback or Android-emulator '
            f'endpoint ending in {FIREBASE_MOCK_PATH}'
        )
    return endpoint


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256:' + _sha256_bytes(canonical)


def _http_url(host: str, port: int, path: str) -> str:
    formatted_host = f'[{host}]' if ':' in host and not host.startswith('[') else host
    return f'http://{formatted_host}:{port}{path}'


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_text(path, json.dumps(value, indent=2, sort_keys=True) + '\n')


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _require_xaman_root(path: Path) -> None:
    required = (path / 'metro.config.js', path / 'android' / 'app' / 'build.gradle')
    missing = [candidate.as_posix() for candidate in required if not candidate.is_file()]
    if missing:
        raise ValueError('Xaman checkout is missing required files: ' + ', '.join(missing))


def _stub_source(module_name: str, firebase_mock_endpoint: str | None = None) -> str:
    telemetry_emit = textwrap.dedent(
        f'''\
        const PREFIX = {TELEMETRY_MARKER!r};
        const MOCK_ENDPOINT = {json.dumps(firebase_mock_endpoint)};
        const fallbackToLog = (payload) => console.info(PREFIX + JSON.stringify(payload));
        const emit = (event, attributes = {{}}) => {{
          const payload = {{
            schema_version: {TELEMETRY_SCHEMA_VERSION!r},
            timestamp_utc: new Date().toISOString(),
            category: 'firebase_disabled',
            event,
            outcome: 'stubbed',
            attributes,
          }};
          if (!MOCK_ENDPOINT || typeof global.fetch !== 'function') {{
            fallbackToLog(payload);
            return;
          }}
          try {{
            Promise.resolve(global.fetch(MOCK_ENDPOINT, {{
              method: 'POST',
              headers: {{'Content-Type': 'application/json'}},
              body: JSON.stringify(payload),
            }})).then((response) => {{
              if (!response || !response.ok) fallbackToLog(payload);
            }}).catch(() => fallbackToLog(payload));
          }} catch (_error) {{
            fallbackToLog(payload);
          }}
        }};
        '''
    )
    if module_name == 'messaging':
        return textwrap.dedent(
            f'''\
            'use strict';

            {telemetry_emit}
            const unsubscribe = () => undefined;
            const messaging = () => {{
              const service = {{
                hasPermission: () => {{ emit('messaging_has_permission'); return Promise.resolve(0); }},
                requestPermission: () => {{ emit('messaging_request_permission'); return Promise.resolve(0); }},
                getToken: () => {{ emit('messaging_get_token'); return Promise.resolve(undefined); }},
                getInitialNotification: () => {{ emit('messaging_get_initial_notification'); return Promise.resolve(null); }},
                onMessage: () => {{ emit('messaging_on_message'); return unsubscribe; }},
                onNotificationOpenedApp: () => {{ emit('messaging_on_notification_opened'); return unsubscribe; }},
              }};
              return new Proxy(service, {{
                get(target, property) {{
                  if (property in target) return target[property];
                  return (...args) => {{
                    emit('messaging_operation', {{operation: String(property), arg_count: args.length}});
                    return Promise.resolve(undefined);
                  }};
                }},
              }});
            }};
            messaging.AuthorizationStatus = {{ NOT_DETERMINED: -1, DENIED: 0, AUTHORIZED: 1, PROVISIONAL: 2 }};
            module.exports = messaging;
            module.exports.default = messaging;
            '''
        )
    return textwrap.dedent(
        f'''\
        'use strict';

        {telemetry_emit}
        const service = new Proxy({{}}, {{
          get(_target, property) {{
            return (...args) => {{
              emit('firebase_{module_name}_operation', {{operation: String(property), arg_count: args.length}});
              return Promise.resolve(undefined);
            }};
          }},
        }});
        const moduleFactory = () => service;
        module.exports = moduleFactory;
        module.exports.default = moduleFactory;
        '''
    )


def _metro_config(xaman_root: Path, stub_root: Path) -> str:
    base_config = json.dumps((xaman_root / 'metro.config.js').as_posix())
    metro_resolver = json.dumps((xaman_root / 'node_modules' / 'metro-resolver').as_posix())
    stub_root_path = json.dumps(stub_root.as_posix())
    stubs = {
        f'@react-native-firebase/{name}': (stub_root / name).as_posix()
        for name in FIREBASE_MODULES
    }
    module_map = json.dumps(stubs, indent=2, sort_keys=True)
    return textwrap.dedent(
        f'''\
        // Generated verifier-only Metro configuration. Do not use for production builds.
        const baseConfig = require({base_config});
        const {{ resolve }} = require({metro_resolver});
        const path = require('path');
        const firebaseStubRoot = {stub_root_path};
        const firebaseStubs = {module_map};

        module.exports = {{
          ...baseConfig,
          // The generated stubs are outside the corpus root, so Metro must
          // hash this one explicit verifier-owned folder for resolution.
          watchFolders: [
            ...((baseConfig.watchFolders) || []),
            firebaseStubRoot,
          ],
          // React Native's Android dev client checks this endpoint before it
          // fetches a bundle. Metro's CLI does not provide it by default.
          server: {{
            ...((baseConfig.server) || {{}}),
            enhanceMiddleware: (middleware, metroServer) => {{
              const baseEnhance = baseConfig.server && baseConfig.server.enhanceMiddleware;
              const enhanced = baseEnhance ? baseEnhance(middleware, metroServer) : middleware;
              return (request, response, next) => {{
                if (request.url === '/status') {{
                  response.statusCode = 200;
                  response.setHeader('Content-Type', 'text/plain');
                  response.end('packager-status:running');
                  return;
                }}
                return enhanced(request, response, next);
              }};
            }},
          }},
          resolver: {{
            ...(baseConfig.resolver || {{}}),
            // The verifier runs under CI to disable Metro file watches completely.
            useWatchman: false,
            extraNodeModules: {{
              ...((baseConfig.resolver && baseConfig.resolver.extraNodeModules) || {{}}),
              ...firebaseStubs,
            }},
            // Extra-node-module mappings are not guaranteed to override an
            // installed package. Resolve the three Firebase entry points
            // explicitly so an installed native package cannot reach JS.
            resolveRequest: (context, moduleName, platform) => {{
              const stubDirectory = firebaseStubs[moduleName];
              if (stubDirectory) {{
                return {{
                  type: 'sourceFile',
                  filePath: path.join(stubDirectory, 'index.js'),
                }};
              }}
              return resolve(context, moduleName, platform);
            }},
          }},
        }};
        '''
    )


def _gradle_init(
    metro_config: Path,
    tangem_maven: Path | None,
    rnn_compat_source: Path,
    react_native_debug_aar: Path | None,
) -> str:
    tangem_path = json.dumps(tangem_maven.as_posix() if tangem_maven is not None else '')
    metro_path = json.dumps(metro_config.as_posix())
    rnn_compat_path = json.dumps(rnn_compat_source.as_posix())
    react_native_debug_path = json.dumps(
        react_native_debug_aar.as_posix() if react_native_debug_aar is not None else ''
    )
    return textwrap.dedent(
        f'''\
        // Generated verifier-only overrides. They do not modify the Xaman checkout.
        def xamanTestnetMetroConfig = new File({metro_path})
        def tangemMaven = new File({tangem_path})
        def rnnCompatibilitySource = new File({rnn_compat_path})
        def reactNativeDebugAar = new File({react_native_debug_path})

        allprojects {{
            if (tangemMaven.isDirectory()) {{
                repositories {{
                    maven {{ url uri(tangemMaven) }}
                }}
                configurations.configureEach {{
                    resolutionStrategy.dependencySubstitution {{
                        substitute module('com.github.tangem.tangem-sdk-android:android') using module('com.github.Tangem.tangem-sdk-android:android:3.7.2')
                        substitute module('com.github.tangem.tangem-sdk-android:core') using module('com.github.Tangem.tangem-sdk-android:core:3.7.2')
                    }}
                }}
            }}
        }}

        gradle.beforeProject {{ project ->
            if (project.path == ':app' && reactNativeDebugAar.isFile()) {{
                project.afterEvaluate {{
                    def localDebugAar = project.file('libs/ReactAndroid-debug.aar').canonicalFile
                    def debugImplementation = project.configurations.getByName('debugImplementation')
                    debugImplementation.dependencies.removeIf {{ dependency ->
                        dependency instanceof org.gradle.api.artifacts.SelfResolvingDependency &&
                            dependency.files.files.any {{ artifact -> artifact.canonicalFile == localDebugAar }}
                    }}
                    project.dependencies.add('debugImplementation', project.files(reactNativeDebugAar))
                }}
            }}
            if (project.path == ':react-native-navigation' && rnnCompatibilitySource.isFile()) {{
                project.afterEvaluate {{
                    project.android.sourceSets.main.java.exclude('com/reactnativenavigation/utils/ReactTypefaceUtils.java')
                    // The source path is intentionally different from the package path so
                    // the exclude applies only to the known-incompatible upstream file.
                    project.android.sourceSets.main.java.srcDir(rnnCompatibilitySource.parentFile)
                }}
            }}
            project.pluginManager.withPlugin('com.google.gms.google-services') {{
                project.tasks.configureEach {{ task ->
                    if (task.name ==~ /process.*GoogleServices/) {{
                        task.enabled = false
                        task.onlyIf {{ false }}
                    }}
                }}
            }}
            project.pluginManager.withPlugin('com.google.firebase.crashlytics') {{
                project.tasks.configureEach {{ task ->
                    if (task.name ==~ /(?i).*(crashlytics|mappingfileid).*/) {{
                        task.enabled = false
                        task.onlyIf {{ false }}
                    }}
                }}
            }}
            project.pluginManager.withPlugin('com.facebook.react') {{
                project.extensions.getByName('react').bundleConfig.set(
                    project.layout.projectDirectory.file(xamanTestnetMetroConfig.absolutePath)
                )
            }}
        }}
        '''
    )


def _runner_script(xaman_root: Path, kit_dir: Path, tangem_maven: Path | None) -> str:
    tangem_export = ''
    if tangem_maven is not None:
        tangem_export = f'export XAMAN_TESTNET_TANGEM_MAVEN={tangem_maven.as_posix()!r}\n'
    return textwrap.dedent(
        f'''\
        #!/usr/bin/env bash
        set -euo pipefail

        export CI=1
        export XAMAN_TESTNET_MODE=1
        {tangem_export}cd {str(xaman_root / 'android')!r}
        # Testnet trials use the debug APK.  The release build has a separate
        # R8 dependency blocker and is neither required nor suitable for this
        # verifier-only lane.
        ./gradlew app:assembleDebug --init-script {str(kit_dir / 'firebase-disabled.init.gradle')!r} "$@"
        '''
    )


def _rnn_compatibility_source(xaman_root: Path) -> str:
    """Return the exact two-line Testnet-only RNN compatibility overlay."""
    source_path = (
        xaman_root
        / 'node_modules'
        / 'react-native-navigation'
        / 'lib'
        / 'android'
        / 'app'
        / 'src'
        / 'main'
        / 'java'
        / 'com'
        / 'reactnativenavigation'
        / 'utils'
        / 'ReactTypefaceUtils.java'
    )
    if not source_path.is_file():
        raise ValueError(f'React Native Navigation compatibility source is missing: {source_path}')
    source = source_path.read_text(encoding='utf-8')
    expected = 'ReactTextShadowNode.UNSET'
    if source.count(expected) != 2 or 'public static final int UNSET = -1;' not in source:
        raise ValueError('React Native Navigation source does not match the reviewed compatibility patch precondition')
    return source.replace(expected, 'UNSET')


def prepare_testnet_kit(
    *,
    xaman_root: Path | str,
    out_dir: Path | str,
    run_id: str,
    tangem_maven: Path | str | None = None,
    react_native_debug_aar: Path | str | None = None,
    firebase_mock_endpoint: str | None = None,
) -> dict[str, Any]:
    """Write an external Firebase-disabled Testnet build kit."""
    xaman = Path(xaman_root).resolve()
    kit_dir = Path(out_dir).resolve()
    if not IDENTIFIER_RE.fullmatch(run_id):
        raise ValueError('run_id must be a short identifier containing only letters, digits, . _ : or -')
    _require_xaman_root(xaman)
    tangem = Path(tangem_maven).resolve() if tangem_maven is not None else None
    if tangem is not None and not tangem.is_dir():
        raise ValueError(f'tangem_maven is not a directory: {tangem}')
    debug_aar = Path(react_native_debug_aar).resolve() if react_native_debug_aar is not None else None
    if debug_aar is not None and not debug_aar.is_file():
        raise ValueError(f'react_native_debug_aar is not a file: {debug_aar}')
    if firebase_mock_endpoint is not None:
        firebase_mock_endpoint = _validate_firebase_mock_endpoint(firebase_mock_endpoint)

    stub_root = kit_dir / 'firebase-stubs'
    rendered_paths: list[Path] = []
    for module_name in FIREBASE_MODULES:
        target = stub_root / module_name / 'index.js'
        _write_text(target, _stub_source(module_name, firebase_mock_endpoint))
        rendered_paths.append(target)

    compatibility_source = kit_dir / 'react-native-navigation-compat' / 'ReactTypefaceUtils.java'
    metro_config = kit_dir / 'metro.config.js'
    gradle_init = kit_dir / 'firebase-disabled.init.gradle'
    runner = kit_dir / 'build-xaman-testnet.sh'
    _write_text(metro_config, _metro_config(xaman, stub_root))
    _write_text(compatibility_source, _rnn_compatibility_source(xaman))
    _write_text(gradle_init, _gradle_init(metro_config, tangem, compatibility_source, debug_aar))
    _write_text(runner, _runner_script(xaman, kit_dir, tangem))
    runner.chmod(runner.stat().st_mode | 0o111)
    rendered_paths.extend((compatibility_source, metro_config, gradle_init, runner))

    manifest = {
        'schema_version': BUILD_SCHEMA_VERSION,
        'task_id': TASK_BUILD_ID,
        'generated_at_utc': _utc_now(),
        'run_id': run_id,
        'xaman_root': xaman.as_posix(),
        'firebase_mode': 'disabled_by_external_gradle_and_metro_overrides',
        'ledger_network': 'testnet_required',
        'runtime_constraints': {
            'ci_required': True,
            'metro_watchman_disabled': True,
            'firebase_js_modules_stubbed': [f'@react-native-firebase/{name}' for name in FIREBASE_MODULES],
            'firebase_mock_endpoint': firebase_mock_endpoint,
            'firebase_mock_loopback_only': firebase_mock_endpoint is not None,
            'firebase_gradle_tasks_disabled': True,
            'react_native_navigation_compatibility_overlay': True,
            'android_build_variant': 'debug',
            'production_usable': False,
        },
        'tangem_maven': tangem.as_posix() if tangem is not None else None,
        'react_native_debug_aar': (
            {
                'path': debug_aar.as_posix(),
                'sha256': _sha256_file(debug_aar),
                'size_bytes': debug_aar.stat().st_size,
            }
            if debug_aar is not None
            else None
        ),
        'files': [
            {
                'path': path.relative_to(kit_dir).as_posix(),
                'sha256': _sha256_file(path),
                'size_bytes': path.stat().st_size,
            }
            for path in sorted(rendered_paths)
        ],
    }
    manifest['artifact_cid'] = _artifact_cid(manifest)
    _write_json(kit_dir / 'testnet-build-manifest.json', manifest)
    return manifest


def _load_duckdb() -> Any:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependent on verifier environment
        raise RuntimeError('duckdb is required for Testnet telemetry capture') from exc
    return duckdb


def _is_testnet_endpoint(endpoint: str) -> bool:
    hostname = (urlparse(endpoint).hostname or '').lower()
    return 'testnet' in hostname or 'altnet' in hostname


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).replace('-', '_').lower()
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                return True
            if _contains_sensitive_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _normalize_event(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get('schema_version') != TELEMETRY_SCHEMA_VERSION:
        raise TelemetryValidationError('TELEMETRY_SCHEMA_VERSION_INVALID')
    timestamp = value.get('timestamp_utc')
    category = value.get('category')
    event = value.get('event')
    outcome = value.get('outcome')
    attributes = value.get('attributes') or {}
    if not all(isinstance(item, str) for item in (timestamp, category, event, outcome)):
        raise TelemetryValidationError('TELEMETRY_REQUIRED_FIELD_INVALID')
    if not EVENT_RE.fullmatch(category) or not EVENT_RE.fullmatch(event) or not EVENT_RE.fullmatch(outcome):
        raise TelemetryValidationError('TELEMETRY_NAME_INVALID')
    if not isinstance(attributes, Mapping):
        raise TelemetryValidationError('TELEMETRY_ATTRIBUTES_INVALID')
    if set(attributes) - ALLOWED_ATTRIBUTE_KEYS:
        raise TelemetryValidationError('TELEMETRY_ATTRIBUTE_KEY_NOT_ALLOWED')
    if _contains_sensitive_key(attributes):
        raise TelemetryValidationError('TELEMETRY_SENSITIVE_FIELD_REJECTED')
    for attribute_value in attributes.values():
        if not isinstance(attribute_value, (str, int, float, bool)) and attribute_value is not None:
            raise TelemetryValidationError('TELEMETRY_ATTRIBUTE_VALUE_INVALID')
    return {
        'timestamp_utc': timestamp,
        'category': category,
        'event': event,
        'outcome': outcome,
        'attributes': dict(attributes),
    }


def _event_payloads(path: Path) -> list[tuple[int, Mapping[str, Any] | None, str | None]]:
    payloads: list[tuple[int, Mapping[str, Any] | None, str | None]] = []
    for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        marker_index = line.find(TELEMETRY_MARKER)
        candidate = line[marker_index + len(TELEMETRY_MARKER) :] if marker_index >= 0 else line.strip()
        if not candidate:
            continue
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            if marker_index >= 0:
                payloads.append((line_number, None, 'TELEMETRY_JSON_INVALID'))
            continue
        payloads.append((line_number, value if isinstance(value, Mapping) else None, None))
    return payloads


def _initialize_schema(connection: Any) -> None:
    connection.execute(
        '''
        CREATE TABLE IF NOT EXISTS xaman_testnet_runs (
            run_id VARCHAR PRIMARY KEY,
            captured_at_utc VARCHAR NOT NULL,
            xaman_commit VARCHAR NOT NULL,
            build_provenance_sha256 VARCHAR NOT NULL,
            ledger_network VARCHAR NOT NULL,
            ledger_endpoint VARCHAR NOT NULL,
            firebase_mode VARCHAR NOT NULL,
            event_log_sha256 VARCHAR NOT NULL,
            accepted_event_count BIGINT NOT NULL,
            rejected_event_count BIGINT NOT NULL
        )
        '''
    )
    connection.execute(
        '''
        CREATE TABLE IF NOT EXISTS xaman_testnet_events (
            run_id VARCHAR NOT NULL,
            ordinal BIGINT NOT NULL,
            timestamp_utc VARCHAR NOT NULL,
            category VARCHAR NOT NULL,
            event_name VARCHAR NOT NULL,
            outcome VARCHAR NOT NULL,
            attributes_json VARCHAR NOT NULL,
            source_line_sha256 VARCHAR NOT NULL,
            PRIMARY KEY (run_id, ordinal)
        )
        '''
    )
    connection.execute(
        '''
        CREATE TABLE IF NOT EXISTS xaman_testnet_rejections (
            run_id VARCHAR NOT NULL,
            source_line_number BIGINT NOT NULL,
            reason_code VARCHAR NOT NULL,
            source_line_sha256 VARCHAR NOT NULL,
            PRIMARY KEY (run_id, source_line_number)
        )
        '''
    )


def _initialize_firebase_mock_schema(connection: Any) -> None:
    """Create isolated tables for the direct DuckDB-backed Firebase mock."""
    connection.execute(
        '''
        CREATE TABLE IF NOT EXISTS xaman_firebase_mock_runs (
            run_id VARCHAR PRIMARY KEY,
            started_at_utc VARCHAR NOT NULL,
            last_event_at_utc VARCHAR,
            xaman_commit VARCHAR NOT NULL,
            build_provenance_sha256 VARCHAR NOT NULL,
            ledger_network VARCHAR NOT NULL,
            ledger_endpoint VARCHAR NOT NULL,
            firebase_mode VARCHAR NOT NULL,
            accepted_event_count BIGINT NOT NULL,
            rejected_event_count BIGINT NOT NULL
        )
        '''
    )
    connection.execute(
        '''
        CREATE TABLE IF NOT EXISTS xaman_firebase_mock_events (
            run_id VARCHAR NOT NULL,
            ordinal BIGINT NOT NULL,
            received_at_utc VARCHAR NOT NULL,
            timestamp_utc VARCHAR NOT NULL,
            category VARCHAR NOT NULL,
            event_name VARCHAR NOT NULL,
            outcome VARCHAR NOT NULL,
            attributes_json VARCHAR NOT NULL,
            request_sha256 VARCHAR NOT NULL,
            PRIMARY KEY (run_id, ordinal)
        )
        '''
    )
    connection.execute(
        '''
        CREATE TABLE IF NOT EXISTS xaman_firebase_mock_rejections (
            run_id VARCHAR NOT NULL,
            ordinal BIGINT NOT NULL,
            received_at_utc VARCHAR NOT NULL,
            reason_code VARCHAR NOT NULL,
            request_sha256 VARCHAR NOT NULL,
            PRIMARY KEY (run_id, ordinal)
        )
        '''
    )


def _validate_capture_arguments(
    *,
    run_id: str,
    xaman_commit: str,
    build_provenance_sha256: str,
    ledger_endpoint: str,
) -> None:
    if not IDENTIFIER_RE.fullmatch(run_id):
        raise ValueError('run_id must be a short identifier containing only letters, digits, . _ : or -')
    if xaman_commit != PINNED_XAMAN_COMMIT:
        raise ValueError('xaman_commit must match the pinned Xaman corpus commit')
    if not re.fullmatch(r'[a-f0-9]{64}', build_provenance_sha256):
        raise ValueError('build_provenance_sha256 must be a lowercase SHA-256 hex digest')
    if not _is_testnet_endpoint(ledger_endpoint):
        raise ValueError('ledger_endpoint must be a public XRPL Testnet or altnet endpoint')


class DuckDBFirebaseMockStore:
    """Persist the narrow Firebase-stub contract directly to local DuckDB.

    The store never writes raw request bodies.  It keeps only validated,
    categorical attributes and a SHA-256 request fingerprint for either an
    accepted record or a rejection reason.
    """

    def __init__(
        self,
        *,
        database_path: Path | str,
        run_id: str,
        xaman_commit: str,
        build_provenance_sha256: str,
        ledger_endpoint: str,
        started_at_utc: str | None = None,
    ) -> None:
        _validate_capture_arguments(
            run_id=run_id,
            xaman_commit=xaman_commit,
            build_provenance_sha256=build_provenance_sha256,
            ledger_endpoint=ledger_endpoint,
        )
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self._duckdb = _load_duckdb()
        self._connection = self._duckdb.connect(str(self.database_path))
        _initialize_firebase_mock_schema(self._connection)
        self._connection.execute(
            '''
            INSERT INTO xaman_firebase_mock_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (run_id) DO UPDATE SET
                xaman_commit = excluded.xaman_commit,
                build_provenance_sha256 = excluded.build_provenance_sha256,
                ledger_network = excluded.ledger_network,
                ledger_endpoint = excluded.ledger_endpoint,
                firebase_mode = excluded.firebase_mode
            ''',
            [
                run_id,
                started_at_utc or _utc_now(),
                None,
                xaman_commit,
                build_provenance_sha256,
                'testnet',
                ledger_endpoint,
                'disabled_with_duckdb_firebase_mock',
                0,
                0,
            ],
        )

    def _next_ordinal(self, table_name: str) -> int:
        return int(
            self._connection.execute(
                f'SELECT COALESCE(MAX(ordinal), 0) + 1 FROM {table_name} WHERE run_id = ?',
                [self.run_id],
            ).fetchone()[0]
        )

    def _refresh_counts(self, received_at_utc: str) -> None:
        accepted = self._connection.execute(
            'SELECT COUNT(*) FROM xaman_firebase_mock_events WHERE run_id = ?', [self.run_id]
        ).fetchone()[0]
        rejected = self._connection.execute(
            'SELECT COUNT(*) FROM xaman_firebase_mock_rejections WHERE run_id = ?', [self.run_id]
        ).fetchone()[0]
        self._connection.execute(
            '''
            UPDATE xaman_firebase_mock_runs
            SET last_event_at_utc = ?, accepted_event_count = ?, rejected_event_count = ?
            WHERE run_id = ?
            ''',
            [received_at_utc, accepted, rejected, self.run_id],
        )

    def record_request(self, request_body: bytes, received_at_utc: str | None = None) -> dict[str, Any]:
        """Validate and persist one mock request without retaining its body."""
        received_at = received_at_utc or _utc_now()
        request_sha256 = _sha256_bytes(request_body)
        try:
            decoded = request_body.decode('utf-8')
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
            reason = 'TELEMETRY_JSON_INVALID'
        else:
            if not isinstance(payload, Mapping):
                reason = 'TELEMETRY_EVENT_NOT_OBJECT'
            else:
                try:
                    event = _normalize_event(payload)
                except TelemetryValidationError as exc:
                    reason = str(exc)
                else:
                    ordinal = self._next_ordinal('xaman_firebase_mock_events')
                    self._connection.execute(
                        'INSERT INTO xaman_firebase_mock_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        [
                            self.run_id,
                            ordinal,
                            received_at,
                            event['timestamp_utc'],
                            event['category'],
                            event['event'],
                            event['outcome'],
                            json.dumps(event['attributes'], sort_keys=True, separators=(',', ':')),
                            request_sha256,
                        ],
                    )
                    self._refresh_counts(received_at)
                    return {'accepted': True, 'ordinal': ordinal, 'request_sha256': request_sha256}

        ordinal = self._next_ordinal('xaman_firebase_mock_rejections')
        self._connection.execute(
            'INSERT INTO xaman_firebase_mock_rejections VALUES (?, ?, ?, ?, ?)',
            [self.run_id, ordinal, received_at, reason, request_sha256],
        )
        self._refresh_counts(received_at)
        return {
            'accepted': False,
            'ordinal': ordinal,
            'reason_code': reason,
            'request_sha256': request_sha256,
        }

    def status(self) -> dict[str, Any]:
        row = self._connection.execute(
            '''
            SELECT started_at_utc, last_event_at_utc, accepted_event_count, rejected_event_count
            FROM xaman_firebase_mock_runs WHERE run_id = ?
            ''',
            [self.run_id],
        ).fetchone()
        if row is None:  # pragma: no cover - protected by constructor initialization
            raise RuntimeError(f'Firebase mock run disappeared: {self.run_id}')
        return {
            'schema_version': TELEMETRY_SCHEMA_VERSION,
            'run_id': self.run_id,
            'storage': 'duckdb',
            'firebase_mode': 'disabled_with_duckdb_firebase_mock',
            'started_at_utc': row[0],
            'last_event_at_utc': row[1],
            'accepted_event_count': row[2],
            'rejected_event_count': row[3],
        }

    def close(self) -> None:
        self._connection.close()


def _firebase_mock_handler(store: DuckDBFirebaseMockStore) -> type[BaseHTTPRequestHandler]:
    class FirebaseMockHandler(BaseHTTPRequestHandler):
        server_version = 'XamanDuckDBFirebaseMock/1.0'

        def _send_json(self, status: HTTPStatus, payload: Mapping[str, Any]) -> None:
            encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
            self.send_response(status.value)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path != FIREBASE_MOCK_HEALTH_PATH:
                self._send_json(HTTPStatus.NOT_FOUND, {'status': 'not_found'})
                return
            self._send_json(HTTPStatus.OK, {'status': 'ok', **store.status()})

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if self.path != FIREBASE_MOCK_PATH:
                self._send_json(HTTPStatus.NOT_FOUND, {'status': 'not_found'})
                return
            try:
                content_length = int(self.headers.get('Content-Length', ''))
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {'status': 'invalid_content_length'})
                return
            if content_length < 1 or content_length > FIREBASE_MOCK_MAX_BODY_BYTES:
                self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {'status': 'invalid_content_length'})
                return
            result = store.record_request(self.rfile.read(content_length))
            status = HTTPStatus.ACCEPTED if result['accepted'] else HTTPStatus.UNPROCESSABLE_ENTITY
            self._send_json(status, {'status': 'accepted' if result['accepted'] else 'rejected', **result})

        def log_message(self, _format: str, *args: Any) -> None:
            # Request bodies can contain secrets.  Persisted hashes and explicit
            # response fields are enough for verifier evidence.
            return

    return FirebaseMockHandler


def create_firebase_mock_server(
    *,
    database_path: Path | str,
    run_id: str,
    xaman_commit: str,
    build_provenance_sha256: str,
    ledger_endpoint: str,
    bind_host: str = '127.0.0.1',
    port: int = 43127,
) -> tuple[HTTPServer, DuckDBFirebaseMockStore]:
    """Create a verifier-only Firebase HTTP mock backed by local DuckDB."""
    if bind_host not in FIREBASE_MOCK_BIND_HOSTS:
        raise ValueError('firebase mock must bind only to 127.0.0.1 or ::1')
    if not 0 <= port <= 65535:
        raise ValueError('firebase mock port must be between 0 and 65535')
    store = DuckDBFirebaseMockStore(
        database_path=database_path,
        run_id=run_id,
        xaman_commit=xaman_commit,
        build_provenance_sha256=build_provenance_sha256,
        ledger_endpoint=ledger_endpoint,
    )
    try:
        return HTTPServer((bind_host, port), _firebase_mock_handler(store)), store
    except Exception:
        store.close()
        raise


def firebase_mock_report(
    *,
    database_path: Path | str,
    run_id: str,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Read a closed DuckDB Firebase-mock run into a redacted evidence report."""
    if not IDENTIFIER_RE.fullmatch(run_id):
        raise ValueError('run_id must be a short identifier containing only letters, digits, . _ : or -')
    database = Path(database_path).resolve()
    if not database.is_file():
        raise ValueError(f'database_path is not a file: {database}')
    duckdb = _load_duckdb()
    connection = duckdb.connect(str(database), read_only=True)
    try:
        row = connection.execute(
            '''
            SELECT started_at_utc, last_event_at_utc, xaman_commit, build_provenance_sha256,
                   ledger_network, ledger_endpoint, firebase_mode,
                   accepted_event_count, rejected_event_count
            FROM xaman_firebase_mock_runs WHERE run_id = ?
            ''',
            [run_id],
        ).fetchone()
        if row is None:
            raise ValueError(f'Firebase mock run is missing: {run_id}')
        categories = [
            result[0]
            for result in connection.execute(
                'SELECT DISTINCT category FROM xaman_firebase_mock_events WHERE run_id = ? ORDER BY category',
                [run_id],
            ).fetchall()
        ]
        rejection_codes = [
            result[0]
            for result in connection.execute(
                'SELECT DISTINCT reason_code FROM xaman_firebase_mock_rejections WHERE run_id = ? ORDER BY reason_code',
                [run_id],
            ).fetchall()
        ]
    finally:
        connection.close()

    report = {
        'schema_version': TELEMETRY_SCHEMA_VERSION,
        'task_id': TASK_FIREBASE_MOCK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'run_id': run_id,
        'firebase_mode': row[6],
        'telemetry_sink': 'duckdb_firebase_mock',
        'started_at_utc': row[0],
        'last_event_at_utc': row[1],
        'production_release_blocked': True,
        'runtime_equivalence_status': 'not_proved',
        'security_decision': (
            'BLOCK_TESTNET_TELEMETRY_REDACTION_FAILURE'
            if row[8]
            else 'TESTNET_DUCKDB_FIREBASE_MOCK_CAPTURED_NOT_PRODUCTION_EVIDENCE'
        ),
        'overall_status': 'blocked' if row[8] else 'captured_testnet_events',
        'xaman_commit': row[2],
        'build_provenance_sha256': row[3],
        'ledger': {
            'network': row[4],
            'endpoint': row[5],
            'target_binding_status': 'declared_not_runtime_verified',
            'runtime_connection_status': 'not_observed_by_firebase_mock_telemetry',
        },
        'duckdb': {'path': database.as_posix(), 'sha256': _sha256_file(database)},
        'accepted_event_count': row[7],
        'rejected_event_count': row[8],
        'accepted_categories': categories,
        'rejection_reason_codes': rejection_codes,
        'blocking_gaps': [
            {
                'code': 'RUNTIME_EQUIVALENCE_NOT_PROVED',
                'reason': 'A Firebase mock demonstrates only the replaced JavaScript telemetry boundary.',
            }
        ],
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def ingest_telemetry(
    *,
    database_path: Path | str,
    event_log_path: Path | str,
    run_id: str,
    xaman_commit: str,
    build_provenance_sha256: str,
    ledger_endpoint: str,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Ingest redacted Firebase-stub telemetry into a local DuckDB database."""
    if not IDENTIFIER_RE.fullmatch(run_id):
        raise ValueError('run_id must be a short identifier containing only letters, digits, . _ : or -')
    if xaman_commit != PINNED_XAMAN_COMMIT:
        raise ValueError('xaman_commit must match the pinned Xaman corpus commit')
    if not re.fullmatch(r'[a-f0-9]{64}', build_provenance_sha256):
        raise ValueError('build_provenance_sha256 must be a lowercase SHA-256 hex digest')
    if not _is_testnet_endpoint(ledger_endpoint):
        raise ValueError('ledger_endpoint must be a public XRPL Testnet or altnet endpoint')

    database = Path(database_path).resolve()
    event_log = Path(event_log_path).resolve()
    if not event_log.is_file():
        raise ValueError(f'event_log_path is not a file: {event_log}')
    database.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = event_log.read_bytes()
    source_lines = event_log.read_text(encoding='utf-8').splitlines()
    accepted: list[tuple[int, dict[str, Any]]] = []
    rejected: list[tuple[int, str]] = []
    for line_number, payload, parse_error in _event_payloads(event_log):
        if parse_error is not None:
            rejected.append((line_number, parse_error))
            continue
        if payload is None:
            rejected.append((line_number, 'TELEMETRY_EVENT_NOT_OBJECT'))
            continue
        try:
            accepted.append((line_number, _normalize_event(payload)))
        except TelemetryValidationError as exc:
            rejected.append((line_number, str(exc)))

    duckdb = _load_duckdb()
    connection = duckdb.connect(str(database))
    try:
        _initialize_schema(connection)
        connection.execute('DELETE FROM xaman_testnet_events WHERE run_id = ?', [run_id])
        connection.execute('DELETE FROM xaman_testnet_rejections WHERE run_id = ?', [run_id])
        connection.execute('DELETE FROM xaman_testnet_runs WHERE run_id = ?', [run_id])
        for ordinal, (line_number, event) in enumerate(accepted, start=1):
            connection.execute(
                '''
                INSERT INTO xaman_testnet_events VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    run_id,
                    ordinal,
                    event['timestamp_utc'],
                    event['category'],
                    event['event'],
                    event['outcome'],
                    json.dumps(event['attributes'], sort_keys=True, separators=(',', ':')),
                    _sha256_bytes(source_lines[line_number - 1].encode('utf-8')),
                ],
            )
        for line_number, reason in rejected:
            connection.execute(
                'INSERT INTO xaman_testnet_rejections VALUES (?, ?, ?, ?)',
                [run_id, line_number, reason, _sha256_bytes(source_lines[line_number - 1].encode('utf-8'))],
            )
        connection.execute(
            'INSERT INTO xaman_testnet_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            [
                run_id,
                generated_at_utc or _utc_now(),
                xaman_commit,
                build_provenance_sha256,
                'testnet',
                ledger_endpoint,
                'disabled',
                _sha256_bytes(source_bytes),
                len(accepted),
                len(rejected),
            ],
        )
    finally:
        connection.close()

    blockers: list[dict[str, Any]] = []
    if not accepted:
        blockers.append({'code': 'TESTNET_TELEMETRY_NO_ACCEPTED_EVENTS'})
    if rejected:
        blockers.append({'code': 'TESTNET_TELEMETRY_REJECTED_EVENTS', 'count': len(rejected)})
    report = {
        'schema_version': TELEMETRY_SCHEMA_VERSION,
        'task_id': TASK_TELEMETRY_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'run_id': run_id,
        'firebase_mode': 'disabled',
        'telemetry_sink': 'duckdb',
        'production_release_blocked': True,
        'runtime_equivalence_status': 'not_proved',
        'security_decision': (
            'BLOCK_TESTNET_TELEMETRY_REDACTION_FAILURE'
            if rejected
            else 'BLOCK_TESTNET_RUNTIME_EQUIVALENCE_NOT_PROVED'
            if not accepted
            else 'TESTNET_FIREBASE_DISABLED_TELEMETRY_CAPTURED_NOT_PRODUCTION_EVIDENCE'
        ),
        'overall_status': 'blocked' if blockers else 'captured_testnet_events',
        'xaman_commit': xaman_commit,
        'build_provenance_sha256': build_provenance_sha256,
        'ledger': {
            'network': 'testnet',
            'endpoint': ledger_endpoint,
            'target_binding_status': 'declared_not_runtime_verified',
            'runtime_connection_status': 'not_observed_by_firebase_stub_telemetry',
        },
        'duckdb': {'path': database.as_posix(), 'sha256': _sha256_file(database)},
        'source_event_log': {'path': event_log.as_posix(), 'sha256': _sha256_bytes(source_bytes)},
        'accepted_event_count': len(accepted),
        'rejected_event_count': len(rejected),
        'accepted_categories': sorted({event['category'] for _, event in accepted}),
        'rejected_events': [
            {'source_line_number': line_number, 'reason_code': reason}
            for line_number, reason in rejected
        ],
        'blocking_gaps': blockers
        + [
            {
                'code': 'RUNTIME_EQUIVALENCE_NOT_PROVED',
                'reason': 'Testnet Firebase-disabled telemetry is not proof of production or device-runtime equivalence.',
            }
        ],
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)

    prepare = subparsers.add_parser('prepare', help='write an external Firebase-disabled build kit')
    prepare.add_argument('--xaman-root', type=Path, required=True)
    prepare.add_argument('--out-dir', type=Path, required=True)
    prepare.add_argument('--run-id', required=True)
    prepare.add_argument('--tangem-maven', type=Path)
    prepare.add_argument('--react-native-debug-aar', type=Path)
    prepare.add_argument(
        '--firebase-mock-endpoint',
        help=f'loopback-only Firebase mock endpoint ending in {FIREBASE_MOCK_PATH}',
    )

    ingest = subparsers.add_parser('ingest', help='ingest redacted Testnet telemetry into DuckDB')
    ingest.add_argument('--database', type=Path, required=True)
    ingest.add_argument('--events', type=Path, required=True)
    ingest.add_argument('--run-id', required=True)
    ingest.add_argument('--xaman-commit', default=PINNED_XAMAN_COMMIT)
    ingest.add_argument('--build-provenance-sha256', required=True)
    ingest.add_argument('--ledger-endpoint', required=True)
    ingest.add_argument('--out', type=Path, required=True)

    mock_server = subparsers.add_parser(
        'mock-server',
        help='serve a loopback-only Firebase mock that persists redacted events to DuckDB',
    )
    mock_server.add_argument('--database', type=Path, required=True)
    mock_server.add_argument('--run-id', required=True)
    mock_server.add_argument('--xaman-commit', default=PINNED_XAMAN_COMMIT)
    mock_server.add_argument('--build-provenance-sha256', required=True)
    mock_server.add_argument('--ledger-endpoint', required=True)
    mock_server.add_argument('--bind-host', default='127.0.0.1')
    mock_server.add_argument('--port', type=int, default=43127)

    mock_report = subparsers.add_parser(
        'mock-report',
        help='write a redacted evidence report from a closed DuckDB Firebase-mock run',
    )
    mock_report.add_argument('--database', type=Path, required=True)
    mock_report.add_argument('--run-id', required=True)
    mock_report.add_argument('--out', type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == 'prepare':
        payload = prepare_testnet_kit(
            xaman_root=args.xaman_root,
            out_dir=args.out_dir,
            run_id=args.run_id,
            tangem_maven=args.tangem_maven,
            react_native_debug_aar=args.react_native_debug_aar,
            firebase_mock_endpoint=args.firebase_mock_endpoint,
        )
        print(json.dumps({'out_dir': args.out_dir.as_posix(), 'artifact_cid': payload['artifact_cid']}, sort_keys=True))
        return 0
    if args.command == 'mock-server':
        server, store = create_firebase_mock_server(
            database_path=args.database,
            run_id=args.run_id,
            xaman_commit=args.xaman_commit,
            build_provenance_sha256=args.build_provenance_sha256,
            ledger_endpoint=args.ledger_endpoint,
            bind_host=args.bind_host,
            port=args.port,
        )
        host, port = server.server_address[:2]
        print(
            json.dumps(
                {
                    'android_emulator_endpoint': f'http://10.0.2.2:{port}{FIREBASE_MOCK_PATH}',
                    'endpoint': _http_url(host, port, FIREBASE_MOCK_PATH),
                    'health_endpoint': _http_url(host, port, FIREBASE_MOCK_HEALTH_PATH),
                    'storage': 'duckdb',
                },
                sort_keys=True,
            ),
            flush=True,
        )
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            store.close()
        return 0
    if args.command == 'mock-report':
        payload = firebase_mock_report(database_path=args.database, run_id=args.run_id)
        _write_json(args.out, payload)
        print(json.dumps({'out': args.out.as_posix(), 'overall_status': payload['overall_status']}, sort_keys=True))
        return 0 if payload['overall_status'] == 'captured_testnet_events' else 2
    payload = ingest_telemetry(
        database_path=args.database,
        event_log_path=args.events,
        run_id=args.run_id,
        xaman_commit=args.xaman_commit,
        build_provenance_sha256=args.build_provenance_sha256,
        ledger_endpoint=args.ledger_endpoint,
    )
    _write_json(args.out, payload)
    print(json.dumps({'out': args.out.as_posix(), 'overall_status': payload['overall_status']}, sort_keys=True))
    return 0 if payload['overall_status'] == 'captured_testnet_events' else 2


if __name__ == '__main__':
    raise SystemExit(main())
