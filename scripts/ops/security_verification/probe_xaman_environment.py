#!/usr/bin/env python3
"""Probe Xaman-App dependency and build-environment assumptions.

This probe consumes the pinned Xaman-App source manifest produced by
``fetch_xaman_corpus.py`` (PORTAL-CXTP-060) and the solver/runtime
dependency evidence produced by ``probe_theorem_prover_environment.py``
(PORTAL-CXTP-058) and ``provision_required_typescript_toolchain.py``
(PORTAL-CXTP-089).  It records, as reproducible evidence:

* Node and npm requirements declared by the pinned ``package.json``.
* React Native build assumptions (React Native/React versions, Hermes and
  New Architecture flags, Metro/Babel configuration presence).
* iOS native assumptions (Podfile platform pin, CocoaPods lockfile digest,
  Ruby version pin).
* Android native assumptions (compile/min/target SDK, NDK, Kotlin, and
  Android Gradle Plugin versions).
* Dependency lockfile digests already recorded in the pinned corpus
  manifest.
* The pinned TypeScript compiler configuration and version, cross
  referenced against the locally resolved TypeScript compiler.
* Detox/e2e availability (``.detoxrc.js`` configurations and pinned e2e
  feature files).
* Solver and runtime tool paths inherited from the solver dependency probe.
* Missing dependency blockers for reproducing the Xaman build/e2e
  environment on this host.

Content-derived fields require reading a small set of pinned configuration
files from the exact pinned commit.  This probe performs a narrow,
best-effort git sparse checkout of only those files.  When that checkout
cannot be reproduced (no network, no git, wrong commit), the probe fails
closed: it still writes a report, but marks the content-derived sections as
unavailable and records a blocking evidence entry so downstream tasks do
not silently treat an unverified environment as ready.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence


SCHEMA_VERSION = 'xaman-environment-probe/v1'
TASK_ID = 'PORTAL-CXTP-061'
POLICY_DOCUMENT = 'docs/security_verification/xaman_environment_assumptions.md'

DEFAULT_MANIFEST_PATH = Path('security_ir_artifacts/corpora/xaman-app/source-manifest.json')
DEFAULT_OUT = Path('security_ir_artifacts/corpora/xaman-app/environment-probe.json')
DEFAULT_SOLVER_PROBE_PATH = Path('security_ir_artifacts/environment/solver-dependency-probe.json')
DEFAULT_TYPESCRIPT_REMEDIATION_PATH = Path(
    'security_ir_artifacts/environment/typescript-remediation-report.json'
)
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_LOCAL_TOOL_TIMEOUT_SECONDS = 5

# The full corpus manifest already records paths, sizes, and digests for
# every tracked file (including dependency lockfiles).  Only a small set of
# configuration files require *content* inspection, so the live checkout
# performed by this probe is intentionally narrow.
CONTENT_PROBE_PATHS: tuple[str, ...] = (
    'package.json',
    'tsconfig.json',
    'tsconfig.jest.json',
    '.detoxrc.js',
    'jest.config.js',
    'android/build.gradle',
    'android/app/build.gradle',
    'android/gradle.properties',
    'ios/Podfile',
    '.ruby-version',
    '.watchmanconfig',
)


class XamanEnvironmentProbeError(RuntimeError):
    """Raised when the Xaman environment probe cannot proceed."""


@dataclass(frozen=True)
class NativeToolSpec:
    name: str
    display_name: str
    candidates: tuple[str, ...]
    version_args: tuple[str, ...]
    blocks: tuple[str, ...]
    purpose: str


NATIVE_TOOLCHAIN_SPECS: tuple[NativeToolSpec, ...] = (
    NativeToolSpec(
        name='ruby',
        display_name='Ruby',
        candidates=('ruby',),
        version_args=('--version',),
        blocks=('ios_pod_install',),
        purpose='Run CocoaPods to install iOS dependencies declared in ios/Podfile.',
    ),
    NativeToolSpec(
        name='pod',
        display_name='CocoaPods',
        candidates=('pod',),
        version_args=('--version',),
        blocks=('ios_pod_install',),
        purpose='Resolve and install the pinned ios/Podfile.lock dependency graph.',
    ),
    NativeToolSpec(
        name='java',
        display_name='Java',
        candidates=('java',),
        version_args=('-version',),
        blocks=('android_build',),
        purpose='Run the Gradle wrapper used by android/build.gradle and android/app/build.gradle.',
    ),
    NativeToolSpec(
        name='xcodebuild',
        display_name='Xcode command line tools',
        candidates=('xcodebuild',),
        version_args=('-version',),
        blocks=('ios_build', 'ios_detox_e2e'),
        purpose='Compile the iOS app and Detox iOS e2e binaries (macOS + Xcode only).',
    ),
    NativeToolSpec(
        name='watchman',
        display_name='Watchman',
        candidates=('watchman',),
        version_args=('--version',),
        blocks=('metro_bundler',),
        purpose='Filesystem watcher recommended by React Native Metro bundler and .watchmanconfig.',
    ),
    NativeToolSpec(
        name='adb',
        display_name='Android Debug Bridge',
        candidates=('adb',),
        version_args=('version',),
        blocks=('android_detox_e2e',),
        purpose='Deploy and drive Android Detox e2e builds against an emulator or device.',
    ),
    NativeToolSpec(
        name='detox_cli',
        display_name='Detox CLI',
        candidates=('detox',),
        version_args=('--version',),
        blocks=('detox_e2e_orchestration',),
        purpose='Orchestrate Detox e2e test runs across the configurations in .detoxrc.js.',
    ),
)


CommandRunner = Callable[[Sequence[str], int], dict[str, Any]]
Which = Callable[[str], str | None]
CheckoutFn = Callable[[str, str, Sequence[str], int], dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _default_runner(command: Sequence[str], timeout_seconds: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        return {'exit_code': None, 'stdout': '', 'stderr': str(exc), 'timed_out': False, 'error': 'file_not_found'}
    except subprocess.TimeoutExpired as exc:
        return {
            'exit_code': None,
            'stdout': exc.stdout or '',
            'stderr': exc.stderr or '',
            'timed_out': True,
            'error': 'timeout',
        }
    except OSError as exc:
        return {'exit_code': None, 'stdout': '', 'stderr': str(exc), 'timed_out': False, 'error': exc.__class__.__name__}
    return {
        'exit_code': completed.returncode,
        'stdout': completed.stdout,
        'stderr': completed.stderr,
        'timed_out': False,
        'error': None,
    }


def _first_line(*values: str) -> str | None:
    for value in values:
        for line in value.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


def _version_token(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.search(r'(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)', raw)
    return match.group(1) if match else None


# --------------------------------------------------------------------------
# Manifest loading
# --------------------------------------------------------------------------


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise XamanEnvironmentProbeError(f'corpus manifest not found: {path}')
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise XamanEnvironmentProbeError(f'corpus manifest is not valid JSON: {path}: {exc}') from exc
    if not isinstance(manifest, dict):
        raise XamanEnvironmentProbeError(f'corpus manifest must be a JSON object: {path}')
    source = manifest.get('source')
    if not isinstance(source, dict) or not source.get('repo_url') or not source.get('commit_sha'):
        raise XamanEnvironmentProbeError(
            f'corpus manifest is missing source.repo_url or source.commit_sha: {path}'
        )
    files = manifest.get('files')
    if not isinstance(files, list) or not files:
        raise XamanEnvironmentProbeError(f'corpus manifest has no file digest entries: {path}')
    return manifest


def _manifest_files_index(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(entry['path']): entry for entry in manifest.get('files', []) if isinstance(entry, dict)}


def _manifest_category(manifest: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = manifest.get(key)
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


# --------------------------------------------------------------------------
# Narrow, best-effort live content checkout
# --------------------------------------------------------------------------


def _run_git(args: list[str], *, cwd: Path | None = None, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    completed = subprocess.run(
        ['git', *args],
        cwd=str(cwd) if cwd else None,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        command = 'git ' + ' '.join(args)
        raise XamanEnvironmentProbeError(
            f'{command} failed with exit code {completed.returncode}: {completed.stderr.strip()}'
        )
    return completed.stdout.strip()


def _default_checkout(
    repo_url: str,
    commit_sha: str,
    paths: Sequence[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch a narrow sparse checkout of ``paths`` at ``commit_sha``.

    Returns a dict with ``success``, ``error``, ``resolved_commit`` and
    ``files`` (a mapping of requested path to file text, or ``None`` when a
    requested path was absent from the checkout). Never raises; any failure
    is reported in ``error`` so the caller can degrade gracefully.
    """

    if not paths:
        return {'success': True, 'error': None, 'resolved_commit': commit_sha, 'files': {}}
    try:
        with tempfile.TemporaryDirectory(prefix='xaman-env-probe-') as temp_dir_name:
            repo_dir = Path(temp_dir_name) / 'xaman-app'
            _run_git(
                ['clone', '--filter=blob:none', '--sparse', '--no-checkout', repo_url, str(repo_dir)],
                timeout_seconds=timeout_seconds,
            )
            _run_git(['sparse-checkout', 'set', *paths], cwd=repo_dir, timeout_seconds=timeout_seconds)
            _run_git(['checkout', '--detach', commit_sha], cwd=repo_dir, timeout_seconds=timeout_seconds)
            resolved_commit = _run_git(['rev-parse', 'HEAD'], cwd=repo_dir, timeout_seconds=timeout_seconds)
            if resolved_commit != commit_sha:
                return {
                    'success': False,
                    'error': f'checked out commit {resolved_commit}, expected {commit_sha}',
                    'resolved_commit': resolved_commit,
                    'files': {},
                }
            files: dict[str, str | None] = {}
            for relative_path in paths:
                candidate = repo_dir / relative_path
                files[relative_path] = (
                    candidate.read_text(encoding='utf-8', errors='replace') if candidate.is_file() else None
                )
            return {'success': True, 'error': None, 'resolved_commit': resolved_commit, 'files': files}
    except (XamanEnvironmentProbeError, subprocess.SubprocessError, OSError) as exc:
        return {'success': False, 'error': str(exc), 'resolved_commit': None, 'files': {}}


# --------------------------------------------------------------------------
# Content parsers
# --------------------------------------------------------------------------

_JSON_TRAILING_COMMA_RE = re.compile(r',(\s*[}\]])')


def _strip_json_comments(text: str) -> str:
    """Strip ``//`` and ``/* */`` comments from JSONC text.

    Unlike a naive regex, this respects string literal boundaries so that
    glob-like values (for example ``"src/**/*.ts"`` in a tsconfig
    ``include``/``exclude`` list) are never mistaken for comment markers.
    """

    result: list[str] = []
    i = 0
    length = len(text)
    in_string = False
    string_char = ''
    while i < length:
        char = text[i]
        if in_string:
            result.append(char)
            if char == '\\' and i + 1 < length:
                result.append(text[i + 1])
                i += 2
                continue
            if char == string_char:
                in_string = False
            i += 1
            continue
        if char in ('"', "'"):
            in_string = True
            string_char = char
            result.append(char)
            i += 1
            continue
        if char == '/' and i + 1 < length and text[i + 1] == '/':
            newline_index = text.find('\n', i)
            i = length if newline_index == -1 else newline_index
            continue
        if char == '/' and i + 1 < length and text[i + 1] == '*':
            end_index = text.find('*/', i + 2)
            i = length if end_index == -1 else end_index + 2
            continue
        result.append(char)
        i += 1
    return ''.join(result)


def _parse_jsonc(text: str) -> Any:
    """Parse JSON that may include ``//``/``/* */`` comments and trailing commas."""

    stripped = _strip_json_comments(text)
    previous = None
    while previous != stripped:
        previous = stripped
        stripped = _JSON_TRAILING_COMMA_RE.sub(lambda m: m.group(1), stripped)
    return json.loads(stripped)


def _parse_java_properties(text: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('!'):
            continue
        if '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        properties[key.strip()] = value.strip()
    return properties


def _drop_comment_lines(text: str, prefix: str) -> str:
    """Drop lines that are entirely a comment, so stray or malformed inline
    comments (for example an unterminated quote in a commented-out Groovy or
    Ruby line) cannot cause a later regex match to spill across lines."""

    return '\n'.join(line for line in text.splitlines() if not line.strip().startswith(prefix))


def _extract_gradle_int(text: str, key: str) -> int | None:
    match = re.search(rf'{key}\s*=\s*(\d+)', text)
    return int(match.group(1)) if match else None


def _extract_gradle_str(text: str, key: str) -> str | None:
    match = re.search(rf'{key}\s*=\s*["\']([^"\'\n]+)["\']', text)
    return match.group(1) if match else None


def _extract_android_build_gradle(text: str) -> dict[str, Any]:
    text = _drop_comment_lines(text, '//')
    android_gradle_plugin = re.search(
        r'com\.android\.tools\.build:gradle:([\d.]+)',
        text,
    )
    return {
        'compile_sdk_version': _extract_gradle_int(text, 'compileSdkVersion'),
        'min_sdk_version': _extract_gradle_int(text, 'minSdkVersion'),
        'target_sdk_version': _extract_gradle_int(text, 'targetSdkVersion'),
        'build_tools_version': _extract_gradle_str(text, 'buildToolsVersion'),
        'ndk_version': _extract_gradle_str(text, 'ndkVersion'),
        'kotlin_version': _extract_gradle_str(text, 'kotlinVersion'),
        'android_gradle_plugin_version': android_gradle_plugin.group(1) if android_gradle_plugin else None,
    }


def _extract_app_build_gradle(text: str) -> dict[str, Any]:
    text = _drop_comment_lines(text, '//')
    version_name = re.search(r'canonicalVersionName\s*=\s*["\']([^"\'\n]+)["\']', text)
    version_code = re.search(r'canonicalVersionCode\s*=\s*(\d+)', text)
    applied_plugins = re.findall(r'apply\s+plugin:\s*["\']([^"\'\n]+)["\']', text)
    return {
        'canonical_version_name': version_name.group(1) if version_name else None,
        'canonical_version_code': int(version_code.group(1)) if version_code else None,
        'applied_plugins': applied_plugins,
    }


def _extract_podfile(text: str) -> dict[str, Any]:
    text = _drop_comment_lines(text, '#')
    platform_version = re.search(r"platform\s*:ios,\s*['\"]([\d.]+)['\"]", text)
    target_names = re.findall(r"^target\s+['\"]([^'\"]+)['\"]\s+do", text, re.MULTILINE)
    pod_names = sorted(set(re.findall(r"^\s*pod\s+['\"]([^'\"]+)['\"]", text, re.MULTILINE)))
    return {
        'ios_platform_version': platform_version.group(1) if platform_version else None,
        'use_frameworks_referenced': 'use_frameworks!' in text,
        'new_architecture_referenced': 'RCT_NEW_ARCH_ENABLED' in text or 'new_arch' in text.lower(),
        'targets': target_names,
        'pinned_pods': pod_names,
    }


def _extract_detoxrc(text: str) -> dict[str, Any]:
    apps = [
        {'name': name, 'type': app_type}
        for name, app_type in re.findall(r"'([\w.]+)':\s*\{\s*type:\s*'([\w.]+)'", text)
    ]
    configurations = re.findall(r"'([\w.+]+)':\s*\{\s*device:", text)
    devices = re.findall(r"'([\w.]+)':\s*\{\s*type:\s*'([\w.]+)',\s*(?:headless|device)", text)
    return {
        'apps': apps,
        'configurations': configurations,
        'device_count': len(devices),
        'references_ios': any(app['type'].startswith('ios') for app in apps),
        'references_android': any(app['type'].startswith('android') for app in apps),
    }


def _extract_jest_config(text: str) -> dict[str, Any]:
    preset = re.search(r"preset:\s*'([^']+)'", text)
    uses_ts_jest = "'ts-jest'" in text or '"ts-jest"' in text
    return {
        'preset': preset.group(1) if preset else None,
        'uses_ts_jest': uses_ts_jest,
    }


# --------------------------------------------------------------------------
# Version constraint comparison (minimal semver-lite range support)
# --------------------------------------------------------------------------


def _version_tuple(version: str) -> tuple[int, int, int] | None:
    match = re.match(r'^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?', version)
    if not match:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor or 0), int(patch or 0))


def _parse_constraint(constraint: str) -> tuple[str, tuple[int, int, int]] | None:
    match = re.match(r'^\s*(>=|<=|>|<|=|\^|~)?\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?', constraint)
    if not match:
        return None
    op, major, minor, patch = match.groups()
    return (op or '=', (int(major), int(minor or 0), int(patch or 0)))


def _engine_satisfied(local_version: str | None, constraint: str | None) -> bool | None:
    if not local_version or not constraint:
        return None
    parsed_constraint = _parse_constraint(constraint)
    local = _version_tuple(local_version)
    if parsed_constraint is None or local is None:
        return None
    op, required = parsed_constraint
    if op == '>=':
        return local >= required
    if op == '<=':
        return local <= required
    if op == '>':
        return local > required
    if op == '<':
        return local < required
    if op == '=':
        return local == required
    if op == '^':
        return local[0] == required[0] and local >= required
    if op == '~':
        return local[:2] == required[:2] and local >= required
    return None


# --------------------------------------------------------------------------
# Local native toolchain probing (informational, non-blocking)
# --------------------------------------------------------------------------


def _probe_native_tool(
    spec: NativeToolSpec,
    which: Which,
    runner: CommandRunner,
    timeout_seconds: int,
) -> dict[str, Any]:
    executable: str | None = None
    for candidate in spec.candidates:
        executable = which(candidate)
        if executable:
            break
    if executable is None:
        return {
            'name': spec.name,
            'display_name': spec.display_name,
            'status': 'missing',
            'executable': None,
            'version': None,
            'version_raw': None,
            'blocks': list(spec.blocks),
            'purpose': spec.purpose,
        }
    command_result = runner([executable, *spec.version_args], timeout_seconds)
    raw_version = _first_line(str(command_result.get('stdout', '')), str(command_result.get('stderr', '')))
    status = 'present' if command_result.get('exit_code') == 0 and not command_result.get('timed_out') else 'error'
    return {
        'name': spec.name,
        'display_name': spec.display_name,
        'status': status,
        'executable': executable,
        'version': _version_token(raw_version),
        'version_raw': raw_version,
        'blocks': list(spec.blocks),
        'purpose': spec.purpose,
    }


def _probe_native_toolchain(
    which: Which,
    runner: CommandRunner,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    return [_probe_native_tool(spec, which, runner, timeout_seconds) for spec in NATIVE_TOOLCHAIN_SPECS]


# --------------------------------------------------------------------------
# Solver / runtime probe evidence loading
# --------------------------------------------------------------------------


def _load_json_if_exists(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _solver_paths_section(solver_probe: dict[str, Any] | None, solver_probe_path: Path) -> dict[str, Any]:
    if solver_probe is None:
        return {
            'solver_probe_path': solver_probe_path.as_posix(),
            'solver_probe_found': False,
            'overall_status': None,
            'proof_acceptance_blocked': None,
            'resolved_executables': {},
        }
    dependencies = solver_probe.get('dependencies', [])
    resolved = {
        dependency['name']: {
            'executable': dependency.get('executable'),
            'version': dependency.get('version'),
            'status': dependency.get('status'),
            'required': dependency.get('required'),
        }
        for dependency in dependencies
        if isinstance(dependency, dict) and dependency.get('name') in {
            'python', 'node', 'npm', 'typescript', 'z3', 'cvc5'
        }
    }
    return {
        'solver_probe_path': solver_probe_path.as_posix(),
        'solver_probe_found': True,
        'schema_version': solver_probe.get('schema_version'),
        'overall_status': solver_probe.get('overall_status'),
        'proof_acceptance_blocked': solver_probe.get('proof_acceptance_blocked'),
        'resolved_executables': resolved,
    }


def _typescript_remediation_section(remediation: dict[str, Any] | None, remediation_path: Path) -> dict[str, Any]:
    if remediation is None:
        return {
            'remediation_report_path': remediation_path.as_posix(),
            'remediation_report_found': False,
            'pinned_typescript_version': None,
            'toolchain_dir': None,
        }
    toolchain = remediation.get('toolchain', {}) if isinstance(remediation.get('toolchain'), dict) else {}
    return {
        'remediation_report_path': remediation_path.as_posix(),
        'remediation_report_found': True,
        'overall_status': remediation.get('overall_status'),
        'proof_acceptance_blocked': remediation.get('proof_acceptance_blocked'),
        'pinned_typescript_version': toolchain.get('pinned_typescript_version'),
        'toolchain_dir': toolchain.get('toolchain_dir'),
    }


# --------------------------------------------------------------------------
# Section builders derived from the checked-out content
# --------------------------------------------------------------------------


def _node_npm_requirements(package_json: dict[str, Any] | None) -> dict[str, Any]:
    if package_json is None:
        return {
            'status': 'content_unavailable',
            'package_json_path': 'package.json',
            'node_requirement': None,
            'npm_requirement': None,
            'package_manager_field': None,
        }
    engines = package_json.get('engines') if isinstance(package_json.get('engines'), dict) else {}
    return {
        'status': 'parsed',
        'package_json_path': 'package.json',
        'app_name': package_json.get('name'),
        'app_version': package_json.get('version'),
        'node_requirement': engines.get('node'),
        'npm_requirement': engines.get('npm'),
        'package_manager_field': package_json.get('packageManager'),
    }


def _react_native_build_assumptions(package_json: dict[str, Any] | None, gradle_properties: dict[str, str] | None) -> dict[str, Any]:
    if package_json is None:
        return {'status': 'content_unavailable'}
    dependencies = package_json.get('dependencies', {}) if isinstance(package_json.get('dependencies'), dict) else {}
    dev_dependencies = (
        package_json.get('devDependencies', {}) if isinstance(package_json.get('devDependencies'), dict) else {}
    )
    hermes_enabled = None
    new_arch_enabled = None
    if gradle_properties:
        hermes_raw = gradle_properties.get('hermesEnabled')
        new_arch_raw = gradle_properties.get('newArchEnabled')
        hermes_enabled = hermes_raw.lower() == 'true' if hermes_raw is not None else None
        new_arch_enabled = new_arch_raw.lower() == 'true' if new_arch_raw is not None else None
    return {
        'status': 'parsed',
        'react_native_version': dependencies.get('react-native'),
        'react_version': dependencies.get('react'),
        'hermes_enabled': hermes_enabled,
        'new_architecture_enabled': new_arch_enabled,
        'detox_dev_dependency_version': dev_dependencies.get('detox'),
        'typescript_dev_dependency_version': dev_dependencies.get('typescript'),
        'babel_preset_dev_dependency_version': dev_dependencies.get('@react-native/babel-preset'),
        'metro_config_dev_dependency_version': dev_dependencies.get('@react-native/metro-config'),
    }


def _typescript_config_section(
    tsconfig: dict[str, Any] | None,
    package_json: dict[str, Any] | None,
    solver_paths: dict[str, Any],
    typescript_remediation: dict[str, Any],
) -> dict[str, Any]:
    dev_dependencies = (
        package_json.get('devDependencies', {})
        if isinstance(package_json, dict) and isinstance(package_json.get('devDependencies'), dict)
        else {}
    )
    pinned_version = dev_dependencies.get('typescript') if isinstance(dev_dependencies, dict) else None
    compiler_options: dict[str, Any] = {}
    include: list[Any] = []
    exclude: list[Any] = []
    path_alias_count = 0
    if isinstance(tsconfig, dict):
        raw_options = tsconfig.get('compilerOptions', {})
        if isinstance(raw_options, dict):
            for key in (
                'target', 'module', 'jsx', 'strict', 'moduleResolution',
                'baseUrl', 'isolatedModules', 'noEmit', 'esModuleInterop',
                'skipLibCheck', 'resolveJsonModule',
            ):
                if key in raw_options:
                    compiler_options[key] = raw_options[key]
            paths = raw_options.get('paths')
            if isinstance(paths, dict):
                path_alias_count = len(paths)
        include = tsconfig.get('include', []) if isinstance(tsconfig.get('include'), list) else []
        exclude = tsconfig.get('exclude', []) if isinstance(tsconfig.get('exclude'), list) else []

    local_tsc = solver_paths.get('resolved_executables', {}).get('typescript')
    return {
        'status': 'parsed' if tsconfig is not None else 'content_unavailable',
        'tsconfig_path': 'tsconfig.json',
        'pinned_typescript_version': pinned_version,
        'compiler_options': compiler_options,
        'path_alias_count': path_alias_count,
        'include_pattern_count': len(include),
        'exclude_pattern_count': len(exclude),
        'locally_resolved_tsc_version': (local_tsc or {}).get('version') if local_tsc else None,
        'locally_resolved_tsc_executable': (local_tsc or {}).get('executable') if local_tsc else None,
        'remediation_toolchain_pinned_version': typescript_remediation.get('pinned_typescript_version'),
    }


def _ios_native_assumptions(
    podfile: dict[str, Any] | None,
    ruby_version: str | None,
    manifest_files: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    podfile_lock_entry = manifest_files.get('ios/Podfile.lock')
    security_txt_entry = manifest_files.get('ios/security.txt')
    result: dict[str, Any] = {
        'status': 'parsed' if podfile is not None else 'content_unavailable',
        'podfile_path': 'ios/Podfile',
        'podfile_lock_path': 'ios/Podfile.lock',
        'podfile_lock_present': podfile_lock_entry is not None,
        'podfile_lock_sha256': podfile_lock_entry.get('sha256') if podfile_lock_entry else None,
        'ruby_version_pin': ruby_version,
        'security_disclosure_file_present': security_txt_entry is not None,
        'build_host_requirement': 'macOS with Xcode command line tools; iOS builds are not reproducible on Linux hosts.',
    }
    if podfile is not None:
        result.update(podfile)
    return result


def _android_native_assumptions(
    build_gradle: dict[str, Any] | None,
    app_build_gradle: dict[str, Any] | None,
    gradle_properties: dict[str, str] | None,
    manifest_files: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    security_txt_entry = manifest_files.get('android/app/src/main/assets/security.txt')
    result: dict[str, Any] = {
        'status': 'parsed' if build_gradle is not None else 'content_unavailable',
        'build_gradle_path': 'android/build.gradle',
        'app_build_gradle_path': 'android/app/build.gradle',
        'security_disclosure_file_present': security_txt_entry is not None,
        'build_host_requirement': (
            'Java Development Kit and Android SDK/NDK; Gradle wrapper is vendored at android/gradlew.'
        ),
    }
    if build_gradle is not None:
        result.update(build_gradle)
    if app_build_gradle is not None:
        result['app_version'] = {
            'canonical_version_name': app_build_gradle.get('canonical_version_name'),
            'canonical_version_code': app_build_gradle.get('canonical_version_code'),
        }
        result['applied_plugins'] = app_build_gradle.get('applied_plugins', [])
    if gradle_properties is not None:
        result['gradle_properties_new_arch_enabled_raw'] = gradle_properties.get('newArchEnabled')
        result['gradle_properties_hermes_enabled_raw'] = gradle_properties.get('hermesEnabled')
    return result


def _detox_e2e_assumptions(
    detoxrc: dict[str, Any] | None,
    jest_config: dict[str, Any] | None,
    package_json: dict[str, Any] | None,
    manifest_files: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    e2e_feature_files = sorted(
        path for path in manifest_files if path.startswith('e2e/') and path.endswith('.feature')
    )
    e2e_support_present = any(path.startswith('e2e/support/') for path in manifest_files)
    e2e_step_definitions_present = any(path.startswith('e2e/step_definitions/') for path in manifest_files)
    e2e_helpers_present = any(path.startswith('e2e/helpers/') for path in manifest_files)
    dev_dependencies = (
        package_json.get('devDependencies', {})
        if isinstance(package_json, dict) and isinstance(package_json.get('devDependencies'), dict)
        else {}
    )
    return {
        'status': 'parsed' if detoxrc is not None else 'content_unavailable',
        'detoxrc_path': '.detoxrc.js',
        'detoxrc_present': detoxrc is not None,
        'detox_dev_dependency_version': dev_dependencies.get('detox') if isinstance(dev_dependencies, dict) else None,
        'cucumber_dev_dependency_version': (
            dev_dependencies.get('@cucumber/cucumber') if isinstance(dev_dependencies, dict) else None
        ),
        'apps': (detoxrc or {}).get('apps', []),
        'configurations': (detoxrc or {}).get('configurations', []),
        'references_ios': (detoxrc or {}).get('references_ios'),
        'references_android': (detoxrc or {}).get('references_android'),
        'e2e_feature_file_count': len(e2e_feature_files),
        'e2e_feature_files': e2e_feature_files,
        'e2e_support_present': e2e_support_present,
        'e2e_step_definitions_present': e2e_step_definitions_present,
        'e2e_helpers_present': e2e_helpers_present,
        'jest_config': jest_config,
    }


# --------------------------------------------------------------------------
# Blocker aggregation
# --------------------------------------------------------------------------


def _missing_dependency_blockers(
    *,
    checkout_result: Mapping[str, Any],
    solver_paths: Mapping[str, Any],
    node_npm_requirements: Mapping[str, Any],
    native_toolchain: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []

    if not checkout_result.get('success'):
        blockers.append(
            {
                'code': 'XAMAN_CORPUS_CONTENT_UNAVAILABLE',
                'component': 'xaman_corpus_content',
                'category': 'corpus_content',
                'status': 'unavailable',
                'blocking': True,
                'required': True,
                'remediation': (
                    'Ensure git and network access to the pinned Xaman-App repository are available, '
                    'then rerun probe_xaman_environment.py to refresh content-derived assumptions.'
                ),
                'detail': checkout_result.get('error'),
            }
        )

    if not solver_paths.get('solver_probe_found'):
        blockers.append(
            {
                'code': 'SOLVER_DEPENDENCY_PROBE_MISSING',
                'component': 'solver_dependency_probe',
                'category': 'solver_toolchain',
                'status': 'missing',
                'blocking': True,
                'required': True,
                'remediation': (
                    'Run scripts/ops/security_verification/probe_theorem_prover_environment.py '
                    '(PORTAL-CXTP-058) before probing the Xaman environment.'
                ),
                'detail': None,
            }
        )
    elif solver_paths.get('proof_acceptance_blocked'):
        blockers.append(
            {
                'code': 'INHERITED_SOLVER_DEPENDENCY_BLOCKER',
                'component': 'solver_dependency_probe',
                'category': 'solver_toolchain',
                'status': solver_paths.get('overall_status'),
                'blocking': True,
                'required': True,
                'remediation': (
                    'Resolve the blocking evidence recorded in '
                    'security_ir_artifacts/environment/solver-dependency-probe.json before accepting '
                    'Xaman proof evidence.'
                ),
                'detail': None,
            }
        )

    node_requirement = node_npm_requirements.get('node_requirement')
    local_node = solver_paths.get('resolved_executables', {}).get('node') if solver_paths.get('solver_probe_found') else None
    if node_requirement and local_node and local_node.get('status') == 'present':
        satisfied = _engine_satisfied(local_node.get('version'), node_requirement)
        if satisfied is False:
            blockers.append(
                {
                    'code': 'NODE_ENGINE_REQUIREMENT_NOT_SATISFIED',
                    'component': 'node',
                    'category': 'runtime_engine_constraint',
                    'status': 'version_mismatch',
                    'blocking': True,
                    'required': True,
                    'remediation': (
                        f'Install a Node.js release satisfying {node_requirement} '
                        f'(found {local_node.get("version")}).'
                    ),
                    'detail': None,
                }
            )

    for tool in native_toolchain:
        if tool.get('status') != 'missing':
            continue
        blockers.append(
            {
                'code': 'NATIVE_TOOLCHAIN_DEPENDENCY_MISSING',
                'component': tool['name'],
                'category': 'native_build_toolchain',
                'status': 'missing',
                'blocking': False,
                'required': False,
                'remediation': f'Install {tool["display_name"]} to enable: {", ".join(tool["blocks"])}.',
                'detail': tool.get('purpose'),
                'blocks': tool.get('blocks'),
            }
        )

    return blockers


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def build_probe(
    *,
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    solver_probe_path: Path | str = DEFAULT_SOLVER_PROBE_PATH,
    typescript_remediation_path: Path | str = DEFAULT_TYPESCRIPT_REMEDIATION_PATH,
    repo_root: Path | str | None = None,
    checkout_fn: CheckoutFn | None = None,
    repo_url_override: str | None = None,
    commit_sha_override: str | None = None,
    content_paths: Sequence[str] = CONTENT_PROBE_PATHS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    which: Which | None = None,
    runner: CommandRunner | None = None,
    native_tool_timeout_seconds: int = DEFAULT_LOCAL_TOOL_TIMEOUT_SECONDS,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    manifest_path = Path(manifest_path)
    manifest_abs = manifest_path if manifest_path.is_absolute() else root / manifest_path
    manifest = _load_manifest(manifest_abs)

    source = manifest['source']
    repo_url = repo_url_override or str(source['repo_url'])
    commit_sha = commit_sha_override or str(source['commit_sha'])
    manifest_files = _manifest_files_index(manifest)

    existing_content_paths = [path for path in content_paths if path in manifest_files]
    checkout = checkout_fn or _default_checkout
    checkout_result = checkout(repo_url, commit_sha, existing_content_paths, timeout_seconds)
    checked_out_files: dict[str, str | None] = checkout_result.get('files', {}) if checkout_result.get('success') else {}

    def _content(path: str) -> str | None:
        return checked_out_files.get(path)

    package_json: dict[str, Any] | None = None
    if _content('package.json'):
        try:
            package_json = json.loads(_content('package.json'))
        except json.JSONDecodeError:
            package_json = None

    tsconfig: dict[str, Any] | None = None
    if _content('tsconfig.json'):
        try:
            tsconfig = _parse_jsonc(_content('tsconfig.json'))
        except json.JSONDecodeError:
            tsconfig = None

    detoxrc = _extract_detoxrc(_content('.detoxrc.js')) if _content('.detoxrc.js') else None
    jest_config = _extract_jest_config(_content('jest.config.js')) if _content('jest.config.js') else None
    android_build_gradle = (
        _extract_android_build_gradle(_content('android/build.gradle')) if _content('android/build.gradle') else None
    )
    android_app_build_gradle = (
        _extract_app_build_gradle(_content('android/app/build.gradle'))
        if _content('android/app/build.gradle')
        else None
    )
    gradle_properties = (
        _parse_java_properties(_content('android/gradle.properties'))
        if _content('android/gradle.properties')
        else None
    )
    podfile = _extract_podfile(_content('ios/Podfile')) if _content('ios/Podfile') else None
    ruby_version = _content('.ruby-version').strip() if _content('.ruby-version') else None

    solver_probe = _load_json_if_exists(
        solver_probe_path if Path(solver_probe_path).is_absolute() else root / solver_probe_path
    )
    typescript_remediation = _load_json_if_exists(
        typescript_remediation_path
        if Path(typescript_remediation_path).is_absolute()
        else root / typescript_remediation_path
    )
    solver_paths = _solver_paths_section(solver_probe, Path(solver_probe_path))
    typescript_remediation_section = _typescript_remediation_section(
        typescript_remediation, Path(typescript_remediation_path)
    )

    which_fn = which or shutil.which
    runner_fn = runner or _default_runner
    native_toolchain = _probe_native_toolchain(which_fn, runner_fn, native_tool_timeout_seconds)

    node_npm_requirements = _node_npm_requirements(package_json)
    react_native_build_assumptions = _react_native_build_assumptions(package_json, gradle_properties)
    typescript_config = _typescript_config_section(
        tsconfig, package_json, solver_paths, typescript_remediation_section
    )
    ios_native_assumptions = _ios_native_assumptions(podfile, ruby_version, manifest_files)
    android_native_assumptions = _android_native_assumptions(
        android_build_gradle, android_app_build_gradle, gradle_properties, manifest_files
    )
    detox_e2e_assumptions = _detox_e2e_assumptions(detoxrc, jest_config, package_json, manifest_files)

    missing_dependency_blockers = _missing_dependency_blockers(
        checkout_result=checkout_result,
        solver_paths=solver_paths,
        node_npm_requirements=node_npm_requirements,
        native_toolchain=native_toolchain,
    )
    blocking_evidence = [entry for entry in missing_dependency_blockers if entry.get('blocking')]
    optional_capability_gaps = [entry for entry in missing_dependency_blockers if not entry.get('blocking')]
    blocked = bool(blocking_evidence)

    dependency_lockfiles = _manifest_category(manifest, 'dependency_lockfiles')

    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'policy_document': POLICY_DOCUMENT,
        'probe_script': 'scripts/ops/security_verification/probe_xaman_environment.py',
        'corpus_manifest_path': _relative(manifest_abs, root),
        'corpus': {
            'name': manifest.get('corpus', 'xaman-app'),
            'repo_url': repo_url,
            'commit_sha': commit_sha,
            'requested_ref': source.get('requested_ref'),
            'manifest_schema_version': manifest.get('schema_version'),
            'manifest_file_count': len(manifest_files),
            'manifest_aggregate_sha256': manifest.get('reproducibility', {}).get('aggregate_sha256'),
        },
        'content_inspection': {
            'mode': 'live_checkout' if checkout_result.get('success') else 'checkout_failed',
            'requested_paths': list(existing_content_paths),
            'resolved_commit': checkout_result.get('resolved_commit'),
            'error': checkout_result.get('error'),
        },
        'dependency_lockfiles': [
            {
                'path': entry.get('path'),
                'sha256': entry.get('sha256'),
                'size_bytes': entry.get('size_bytes'),
            }
            for entry in dependency_lockfiles
        ],
        'node_npm_requirements': node_npm_requirements,
        'react_native_build_assumptions': react_native_build_assumptions,
        'typescript_config': typescript_config,
        'ios_native_assumptions': ios_native_assumptions,
        'android_native_assumptions': android_native_assumptions,
        'detox_e2e_assumptions': detox_e2e_assumptions,
        'solver_paths': solver_paths,
        'typescript_remediation': typescript_remediation_section,
        'local_native_toolchain_probe': native_toolchain,
        'missing_dependency_blockers': missing_dependency_blockers,
        'blocking_evidence': blocking_evidence,
        'optional_capability_gaps': optional_capability_gaps,
        'overall_status': 'blocked' if blocked else 'ready',
        'proof_acceptance_blocked': blocked,
        'security_decision': (
            'BLOCK_XAMAN_ENVIRONMENT_ACCEPTANCE_MISSING_DEPENDENCY'
            if blocked
            else (
                'XAMAN_ENVIRONMENT_READY_WITH_CAPABILITY_GAPS'
                if optional_capability_gaps
                else 'XAMAN_ENVIRONMENT_READY'
            )
        ),
        'summary': {
            'dependency_lockfile_count': len(dependency_lockfiles),
            'blocking_evidence_count': len(blocking_evidence),
            'optional_capability_gap_count': len(optional_capability_gaps),
            'e2e_feature_file_count': detox_e2e_assumptions.get('e2e_feature_file_count'),
            'native_toolchain_present_count': len(
                [tool for tool in native_toolchain if tool.get('status') == 'present']
            ),
            'native_toolchain_count': len(native_toolchain),
        },
    }


def write_json(document: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Probe Xaman-App dependency and build-environment assumptions.')
    parser.add_argument('--repo-root', default=str(_repo_root()), help='repository root to resolve relative paths against')
    parser.add_argument(
        '--corpus-manifest',
        default=DEFAULT_MANIFEST_PATH.as_posix(),
        help='path to the pinned Xaman-App source manifest',
    )
    parser.add_argument('--out', default=DEFAULT_OUT.as_posix(), help='probe report JSON path')
    parser.add_argument(
        '--solver-probe',
        default=DEFAULT_SOLVER_PROBE_PATH.as_posix(),
        help='path to the solver dependency probe JSON (PORTAL-CXTP-058)',
    )
    parser.add_argument(
        '--typescript-remediation',
        default=DEFAULT_TYPESCRIPT_REMEDIATION_PATH.as_posix(),
        help='path to the TypeScript remediation report JSON (PORTAL-CXTP-089)',
    )
    parser.add_argument(
        '--timeout-seconds',
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help='timeout for the narrow live content checkout',
    )
    parser.add_argument(
        '--fail-on-blocking',
        action='store_true',
        help='exit non-zero when required evidence is missing or blocked',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path

    try:
        report = build_probe(
            manifest_path=Path(args.corpus_manifest),
            solver_probe_path=Path(args.solver_probe),
            typescript_remediation_path=Path(args.typescript_remediation),
            repo_root=repo_root,
            timeout_seconds=args.timeout_seconds,
        )
    except XamanEnvironmentProbeError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2

    write_json(report, out_path)
    print(
        json.dumps(
            {
                'out': _relative(out_path, repo_root),
                'schema_version': report['schema_version'],
                'overall_status': report['overall_status'],
                'proof_acceptance_blocked': report['proof_acceptance_blocked'],
                'blocking_evidence_count': report['summary']['blocking_evidence_count'],
                'optional_capability_gap_count': report['summary']['optional_capability_gap_count'],
            },
            indent=2,
        )
    )
    if args.fail_on_blocking and report['proof_acceptance_blocked']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
