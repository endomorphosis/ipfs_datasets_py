import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'probe_xaman_environment.py'
)
CHECKED_IN_ARTIFACT_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'environment-probe.json'
)
CHECKED_IN_MANIFEST_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'source-manifest.json'
)
POLICY_DOC_PATH = (
    REPO_ROOT / 'docs' / 'security_verification' / 'xaman_environment_assumptions.md'
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location('probe_xaman_environment', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load Xaman environment probe script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PACKAGE_JSON = json.dumps(
    {
        'name': 'xaman',
        'version': '4.1.3',
        'dependencies': {
            'react': '18.2.0',
            'react-native': '0.74.2',
        },
        'devDependencies': {
            'typescript': '5.4.3',
            'detox': '20.32.0',
            '@cucumber/cucumber': '10.3.1',
            '@react-native/babel-preset': '0.74.84',
            '@react-native/metro-config': '0.74.84',
        },
        'engines': {'node': '>=18'},
    }
)

TSCONFIG_JSON = """{
  // Causes issues with package.json "exports"
  "compilerOptions": {
    "target": "esnext",
    "module": "es2015",
    "jsx": "react-native",
    "noEmit": true,
    "strict": true,
    "moduleResolution": "bundler",
    "baseUrl": "src",
    "paths": {
      "@components/*": ["./components/*"],
      "@components": ["./components"],
    },
  },
  "include": ["src/**/*.ts", "src/**/*.tsx", "typings/**/*.d.ts"],
  "exclude": [ "node_modules", "**/*.test.tsx", "**/*.test.ts"],
}
"""

DETOXRC_JS = """module.exports = {
    apps: {
        'xaman.ios': {
            type: 'ios.app',
            binaryPath: 'ios/build/Build/Products/Release-iphonesimulator/Xaman.app',
        },
        'xaman.android': {
            type: 'android.apk',
            binaryPath: 'android/app/build/outputs/apk/release/app-x86_64-release.apk',
        },
    },
    devices: {
        'ios.simulator': {
            type: 'ios.simulator',
            device: { type: 'iPhone 16 Pro' },
        },
    },
    configurations: {
        'ios.simulator+xaman.ios': {
            device: 'ios.simulator',
            app: 'xaman.ios',
        },
    },
};
"""

JEST_CONFIG_JS = """module.exports = {
    preset: 'react-native',
    transform: {
        '\\\\.(ts|tsx)$': ['ts-jest', {}],
    },
};
"""

ANDROID_BUILD_GRADLE = """buildscript {
    ext {
        buildToolsVersion = "34.0.0"
        minSdkVersion = 26
        compileSdkVersion = 34
        targetSdkVersion = 35
        kotlinVersion = "1.9.24"
        ndkVersion = "26.1.10909125"
    }
    dependencies {
        // classpath("com.android.tools.build:gradle:7.3.1")
        classpath("com.android.tools.build:gradle:7.4.0")
    }
}
"""

ANDROID_APP_BUILD_GRADLE = """apply plugin: "com.android.application"
apply plugin: "org.jetbrains.kotlin.android"
// apply plugin: 'com.google.android.gms.strict-version-matcher-plugin

def canonicalVersionName = "4.2.1"
def canonicalVersionCode = 123
"""

ANDROID_GRADLE_PROPERTIES = """newArchEnabled=false
hermesEnabled=true
"""

IOS_PODFILE = """# Resolve react_native_pods.rb with node
platform :ios, '13.4'

target 'Xaman' do
  pod 'Firebase', :modular_headers => true
end
"""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _manifest_file_entry(path: str, content: str | None = None, size_bytes: int = 10) -> dict[str, Any]:
    return {
        'path': path,
        'size_bytes': len(content) if content is not None else size_bytes,
        'sha256': _sha256(content) if content is not None else '0' * 64,
    }


def _build_fake_manifest() -> dict[str, Any]:
    file_contents = {
        'package.json': PACKAGE_JSON,
        'tsconfig.json': TSCONFIG_JSON,
        '.detoxrc.js': DETOXRC_JS,
        'jest.config.js': JEST_CONFIG_JS,
        'android/build.gradle': ANDROID_BUILD_GRADLE,
        'android/app/build.gradle': ANDROID_APP_BUILD_GRADLE,
        'android/gradle.properties': ANDROID_GRADLE_PROPERTIES,
        'ios/Podfile': IOS_PODFILE,
        '.ruby-version': '2.7.4\n',
        '.watchmanconfig': '{}\n',
    }
    other_paths = [
        'Gemfile.lock',
        'ios/Podfile.lock',
        'package-lock.json',
        'LICENSE',
        'RESPONSIBLE-DISCLOSURE.md',
        'ios/security.txt',
        'android/app/src/main/assets/security.txt',
        'e2e/01_setup.feature',
        'e2e/02_generate_account.feature',
        'e2e/support/env.js',
        'e2e/step_definitions/setup.js',
        'e2e/helpers/fixtures.js',
    ]
    files = [_manifest_file_entry(path, content) for path, content in file_contents.items()]
    files.extend(_manifest_file_entry(path) for path in other_paths)

    return {
        'schema_version': 'xaman-corpus-source-manifest/v1',
        'corpus': 'xaman-app',
        'source': {
            'repo_url': 'https://example.invalid/XRPL-Labs/Xaman-App',
            'requested_ref': '942f43876265a7af44f233288ad2b1d00841d5fa',
            'commit_sha': '942f43876265a7af44f233288ad2b1d00841d5fa',
        },
        'sparse_checkout': {'mode': 'git sparse-checkout cone', 'paths': ['src', 'android', 'ios', 'e2e']},
        'reproducibility': {
            'aggregate_sha256': 'a' * 64,
            'file_count': len(files),
            'total_size_bytes': sum(f['size_bytes'] for f in files),
        },
        'dependency_lockfiles': [
            _manifest_file_entry('Gemfile.lock'),
            _manifest_file_entry('ios/Podfile.lock'),
            _manifest_file_entry('package-lock.json'),
        ],
        'license_files': [_manifest_file_entry('LICENSE')],
        'security_disclosure_files': [
            _manifest_file_entry('RESPONSIBLE-DISCLOSURE.md'),
            _manifest_file_entry('ios/security.txt'),
            _manifest_file_entry('android/app/src/main/assets/security.txt'),
        ],
        'files': files,
    }, file_contents


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding='utf-8')


def _fake_checkout_success(file_contents: Mapping[str, str]):
    def _checkout(repo_url: str, commit_sha: str, paths: Sequence[str], timeout_seconds: int) -> dict[str, Any]:
        return {
            'success': True,
            'error': None,
            'resolved_commit': commit_sha,
            'files': {path: file_contents.get(path) for path in paths},
        }

    return _checkout


def _fake_checkout_failure(error: str):
    def _checkout(repo_url: str, commit_sha: str, paths: Sequence[str], timeout_seconds: int) -> dict[str, Any]:
        return {'success': False, 'error': error, 'resolved_commit': None, 'files': {}}

    return _checkout


def _write_solver_probe(path: Path, *, blocked: bool = False) -> None:
    dependencies = [
        {'name': 'python', 'status': 'present', 'executable': '/usr/bin/python3', 'version': '3.12.1', 'required': True},
        {'name': 'node', 'status': 'present', 'executable': '/usr/bin/node', 'version': '24.18.0', 'required': True},
        {'name': 'npm', 'status': 'present', 'executable': '/usr/bin/npm', 'version': '11.16.0', 'required': True},
        {'name': 'typescript', 'status': 'present', 'executable': '/usr/bin/tsc', 'version': '5.6.3', 'required': True},
        {'name': 'z3', 'status': 'present', 'executable': '/usr/bin/z3', 'version': '4.13.0', 'required': True},
        {
            'name': 'cvc5',
            'status': 'missing' if blocked else 'present',
            'executable': None if blocked else '/usr/bin/cvc5',
            'version': None if blocked else '1.1.2',
            'required': True,
        },
    ]
    _write_json(
        path,
        {
            'schema_version': 'crypto-exchange-solver-dependency-probe/v1',
            'task_id': 'PORTAL-CXTP-058',
            'overall_status': 'blocked' if blocked else 'ready',
            'proof_acceptance_blocked': blocked,
            'dependencies': dependencies,
        },
    )


def _write_typescript_remediation(path: Path) -> None:
    _write_json(
        path,
        {
            'schema_version': 'crypto-exchange-typescript-dependency-remediation/v1',
            'task_id': 'PORTAL-CXTP-089',
            'toolchain': {
                'pinned_typescript_version': '5.6.3',
                'toolchain_dir': 'security_ir_artifacts/environment/typescript_toolchain',
            },
        },
    )


def _no_native_tools_which(_candidate: str) -> str | None:
    return None


def _no_native_tools_runner(command, timeout_seconds):  # pragma: no cover - never invoked
    raise AssertionError('runner should not be invoked when no candidates resolve')


def test_build_probe_parses_pinned_content_and_reports_ready(tmp_path: Path) -> None:
    module = _load_script_module()
    manifest, file_contents = _build_fake_manifest()
    manifest_path = tmp_path / 'source-manifest.json'
    _write_json(manifest_path, manifest)
    solver_probe_path = tmp_path / 'solver-dependency-probe.json'
    _write_solver_probe(solver_probe_path)
    typescript_remediation_path = tmp_path / 'typescript-remediation-report.json'
    _write_typescript_remediation(typescript_remediation_path)

    report = module.build_probe(
        manifest_path=manifest_path,
        solver_probe_path=solver_probe_path,
        typescript_remediation_path=typescript_remediation_path,
        repo_root=tmp_path,
        checkout_fn=_fake_checkout_success(file_contents),
        which=_no_native_tools_which,
        runner=_no_native_tools_runner,
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['schema_version'] == 'xaman-environment-probe/v1'
    assert report['task_id'] == 'PORTAL-CXTP-061'
    assert report['overall_status'] == 'ready'
    assert report['proof_acceptance_blocked'] is False
    assert report['blocking_evidence'] == []

    assert report['node_npm_requirements']['node_requirement'] == '>=18'
    assert report['node_npm_requirements']['app_version'] == '4.1.3'

    rn_assumptions = report['react_native_build_assumptions']
    assert rn_assumptions['react_native_version'] == '0.74.2'
    assert rn_assumptions['react_version'] == '18.2.0'
    assert rn_assumptions['hermes_enabled'] is True
    assert rn_assumptions['new_architecture_enabled'] is False
    assert rn_assumptions['detox_dev_dependency_version'] == '20.32.0'

    ts_config = report['typescript_config']
    assert ts_config['pinned_typescript_version'] == '5.4.3'
    assert ts_config['compiler_options']['strict'] is True
    assert ts_config['compiler_options']['target'] == 'esnext'
    assert ts_config['path_alias_count'] == 2
    assert ts_config['include_pattern_count'] == 3
    assert ts_config['locally_resolved_tsc_version'] == '5.6.3'

    ios_assumptions = report['ios_native_assumptions']
    assert ios_assumptions['ios_platform_version'] == '13.4'
    assert ios_assumptions['ruby_version_pin'] == '2.7.4'
    assert ios_assumptions['podfile_lock_present'] is True

    android_assumptions = report['android_native_assumptions']
    assert android_assumptions['compile_sdk_version'] == 34
    assert android_assumptions['min_sdk_version'] == 26
    assert android_assumptions['target_sdk_version'] == 35
    assert android_assumptions['ndk_version'] == '26.1.10909125'
    assert android_assumptions['android_gradle_plugin_version'] == '7.4.0'
    assert android_assumptions['app_version']['canonical_version_name'] == '4.2.1'
    assert 'com.google.android.gms.strict-version-matcher-plugin' not in ''.join(
        android_assumptions['applied_plugins']
    )

    detox_assumptions = report['detox_e2e_assumptions']
    assert detox_assumptions['detoxrc_present'] is True
    assert detox_assumptions['detox_dev_dependency_version'] == '20.32.0'
    assert detox_assumptions['e2e_feature_file_count'] == 2
    assert detox_assumptions['e2e_support_present'] is True
    assert detox_assumptions['e2e_step_definitions_present'] is True
    assert detox_assumptions['e2e_helpers_present'] is True

    lockfile_paths = {entry['path'] for entry in report['dependency_lockfiles']}
    assert lockfile_paths == {'Gemfile.lock', 'ios/Podfile.lock', 'package-lock.json'}

    solver_paths = report['solver_paths']
    assert solver_paths['solver_probe_found'] is True
    assert solver_paths['resolved_executables']['node']['version'] == '24.18.0'

    native_gaps = {gap['component'] for gap in report['optional_capability_gaps']}
    assert {'ruby', 'pod', 'java', 'xcodebuild', 'watchman', 'adb', 'detox_cli'}.issubset(native_gaps)
    assert all(gap['blocking'] is False for gap in report['optional_capability_gaps'])


def test_build_probe_blocks_when_live_checkout_fails(tmp_path: Path) -> None:
    module = _load_script_module()
    manifest, _file_contents = _build_fake_manifest()
    manifest_path = tmp_path / 'source-manifest.json'
    _write_json(manifest_path, manifest)
    solver_probe_path = tmp_path / 'solver-dependency-probe.json'
    _write_solver_probe(solver_probe_path)

    report = module.build_probe(
        manifest_path=manifest_path,
        solver_probe_path=solver_probe_path,
        typescript_remediation_path=tmp_path / 'missing-typescript-remediation.json',
        repo_root=tmp_path,
        checkout_fn=_fake_checkout_failure('simulated network failure'),
        which=_no_native_tools_which,
        runner=_no_native_tools_runner,
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert report['proof_acceptance_blocked'] is True
    blockers = {entry['code']: entry for entry in report['blocking_evidence']}
    assert 'XAMAN_CORPUS_CONTENT_UNAVAILABLE' in blockers
    assert blockers['XAMAN_CORPUS_CONTENT_UNAVAILABLE']['detail'] == 'simulated network failure'
    assert report['node_npm_requirements']['status'] == 'content_unavailable'
    assert report['react_native_build_assumptions']['status'] == 'content_unavailable'
    assert report['typescript_remediation']['remediation_report_found'] is False


def test_build_probe_blocks_when_solver_probe_missing(tmp_path: Path) -> None:
    module = _load_script_module()
    manifest, file_contents = _build_fake_manifest()
    manifest_path = tmp_path / 'source-manifest.json'
    _write_json(manifest_path, manifest)

    report = module.build_probe(
        manifest_path=manifest_path,
        solver_probe_path=tmp_path / 'missing-solver-probe.json',
        typescript_remediation_path=tmp_path / 'missing-typescript-remediation.json',
        repo_root=tmp_path,
        checkout_fn=_fake_checkout_success(file_contents),
        which=_no_native_tools_which,
        runner=_no_native_tools_runner,
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    blockers = {entry['code'] for entry in report['blocking_evidence']}
    assert 'SOLVER_DEPENDENCY_PROBE_MISSING' in blockers


def test_build_probe_inherits_blocking_evidence_from_solver_probe(tmp_path: Path) -> None:
    module = _load_script_module()
    manifest, file_contents = _build_fake_manifest()
    manifest_path = tmp_path / 'source-manifest.json'
    _write_json(manifest_path, manifest)
    solver_probe_path = tmp_path / 'solver-dependency-probe.json'
    _write_solver_probe(solver_probe_path, blocked=True)

    report = module.build_probe(
        manifest_path=manifest_path,
        solver_probe_path=solver_probe_path,
        typescript_remediation_path=tmp_path / 'missing-typescript-remediation.json',
        repo_root=tmp_path,
        checkout_fn=_fake_checkout_success(file_contents),
        which=_no_native_tools_which,
        runner=_no_native_tools_runner,
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    blockers = {entry['code'] for entry in report['blocking_evidence']}
    assert 'INHERITED_SOLVER_DEPENDENCY_BLOCKER' in blockers


def test_build_probe_flags_node_engine_mismatch_as_blocking(tmp_path: Path) -> None:
    module = _load_script_module()
    manifest, file_contents = _build_fake_manifest()
    file_contents = dict(file_contents)
    file_contents['package.json'] = json.dumps(
        {
            'name': 'xaman',
            'version': '4.1.3',
            'dependencies': {'react': '18.2.0', 'react-native': '0.74.2'},
            'devDependencies': {'typescript': '5.4.3'},
            'engines': {'node': '>=999'},
        }
    )
    manifest_path = tmp_path / 'source-manifest.json'
    _write_json(manifest_path, manifest)
    solver_probe_path = tmp_path / 'solver-dependency-probe.json'
    _write_solver_probe(solver_probe_path)

    report = module.build_probe(
        manifest_path=manifest_path,
        solver_probe_path=solver_probe_path,
        typescript_remediation_path=tmp_path / 'missing-typescript-remediation.json',
        repo_root=tmp_path,
        checkout_fn=_fake_checkout_success(file_contents),
        which=_no_native_tools_which,
        runner=_no_native_tools_runner,
        generated_at_utc='2026-07-08T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    blockers = {entry['code'] for entry in report['blocking_evidence']}
    assert 'NODE_ENGINE_REQUIREMENT_NOT_SATISFIED' in blockers


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def _create_local_xaman_like_repo(repo: Path) -> str:
    repo.mkdir()
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'security-tests@example.invalid')
    _git(repo, 'config', 'user.name', 'Security Tests')
    _write(repo / 'package.json', PACKAGE_JSON)
    _write(repo / 'tsconfig.json', TSCONFIG_JSON)
    _write(repo / '.detoxrc.js', DETOXRC_JS)
    _write(repo / 'jest.config.js', JEST_CONFIG_JS)
    _write(repo / 'android' / 'build.gradle', ANDROID_BUILD_GRADLE)
    _write(repo / 'android' / 'app' / 'build.gradle', ANDROID_APP_BUILD_GRADLE)
    _write(repo / 'android' / 'gradle.properties', ANDROID_GRADLE_PROPERTIES)
    _write(repo / 'ios' / 'Podfile', IOS_PODFILE)
    _write(repo / '.ruby-version', '2.7.4\n')
    _write(repo / '.watchmanconfig', '{}\n')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-m', 'seed reproducible xaman-like fixture repo')
    return _git(repo, 'rev-parse', 'HEAD')


def test_cli_writes_probe_report_using_real_git_checkout_of_local_fixture_repo(tmp_path: Path) -> None:
    module = _load_script_module()
    source_repo = tmp_path / 'source-repo'
    commit_sha = _create_local_xaman_like_repo(source_repo)

    manifest = {
        'schema_version': 'xaman-corpus-source-manifest/v1',
        'corpus': 'xaman-app',
        'source': {
            'repo_url': source_repo.as_posix(),
            'requested_ref': commit_sha,
            'commit_sha': commit_sha,
        },
        'reproducibility': {'aggregate_sha256': 'a' * 64},
        'dependency_lockfiles': [],
        'files': [
            _manifest_file_entry(path)
            for path in (
                'package.json',
                'tsconfig.json',
                '.detoxrc.js',
                'jest.config.js',
                'android/build.gradle',
                'android/app/build.gradle',
                'android/gradle.properties',
                'ios/Podfile',
                '.ruby-version',
                '.watchmanconfig',
            )
        ],
    }
    manifest_path = tmp_path / 'source-manifest.json'
    _write_json(manifest_path, manifest)
    solver_probe_path = tmp_path / 'solver-dependency-probe.json'
    _write_solver_probe(solver_probe_path)
    typescript_remediation_path = tmp_path / 'typescript-remediation-report.json'
    _write_typescript_remediation(typescript_remediation_path)
    out_path = tmp_path / 'environment-probe.json'

    rc = module.main(
        [
            '--repo-root', tmp_path.as_posix(),
            '--corpus-manifest', manifest_path.as_posix(),
            '--solver-probe', solver_probe_path.as_posix(),
            '--typescript-remediation', typescript_remediation_path.as_posix(),
            '--out', out_path.as_posix(),
            '--timeout-seconds', '30',
        ]
    )

    assert rc == 0
    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert report['schema_version'] == 'xaman-environment-probe/v1'
    assert report['content_inspection']['mode'] == 'live_checkout'
    assert report['content_inspection']['resolved_commit'] == commit_sha
    assert report['react_native_build_assumptions']['react_native_version'] == '0.74.2'
    assert report['android_native_assumptions']['compile_sdk_version'] == 34


def test_cli_fails_closed_when_corpus_manifest_is_missing(tmp_path: Path) -> None:
    module = _load_script_module()
    rc = module.main(
        [
            '--repo-root', tmp_path.as_posix(),
            '--corpus-manifest', (tmp_path / 'does-not-exist.json').as_posix(),
            '--out', (tmp_path / 'out.json').as_posix(),
        ]
    )
    assert rc == 2
    assert not (tmp_path / 'out.json').exists()


def test_checked_in_probe_artifact_has_required_schema_and_sections() -> None:
    assert CHECKED_IN_ARTIFACT_PATH.exists(), 'environment-probe.json must be checked in'
    report = json.loads(CHECKED_IN_ARTIFACT_PATH.read_text(encoding='utf-8'))

    assert report['schema_version'] == 'xaman-environment-probe/v1'
    assert report['task_id'] == 'PORTAL-CXTP-061'
    assert report['policy_document'] == 'docs/security_verification/xaman_environment_assumptions.md'
    assert isinstance(report['proof_acceptance_blocked'], bool)
    assert isinstance(report['blocking_evidence'], list)
    assert isinstance(report['missing_dependency_blockers'], list)

    manifest = json.loads(CHECKED_IN_MANIFEST_PATH.read_text(encoding='utf-8'))
    assert report['corpus']['commit_sha'] == manifest['source']['commit_sha']
    assert report['corpus']['repo_url'] == manifest['source']['repo_url']

    for key in (
        'node_npm_requirements',
        'react_native_build_assumptions',
        'typescript_config',
        'ios_native_assumptions',
        'android_native_assumptions',
        'detox_e2e_assumptions',
        'solver_paths',
        'dependency_lockfiles',
    ):
        assert key in report, f'missing required section: {key}'

    assert {entry['path'] for entry in report['dependency_lockfiles']} == {
        'Gemfile.lock',
        'ios/Podfile.lock',
        'package-lock.json',
    }
    assert report['detox_e2e_assumptions']['e2e_feature_file_count'] == 6


def test_policy_document_exists_and_references_task() -> None:
    assert POLICY_DOC_PATH.exists(), 'xaman_environment_assumptions.md must be checked in'
    contents = POLICY_DOC_PATH.read_text(encoding='utf-8')
    assert 'PORTAL-CXTP-061' in contents
    assert 'environment-probe.json' in contents
