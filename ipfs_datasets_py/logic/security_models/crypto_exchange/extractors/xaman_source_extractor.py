"""Xaman React Native source coverage extractor.

The Xaman corpus is pinned as a source manifest, while downstream wallet
modeling needs a reviewed inventory of the security-relevant React Native
TypeScript surface.  This extractor keeps those two concerns separate:
manifest entries are enough to classify coverage, but source content is
required before a file is marked parsed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from ..ir.schema import make_evidence_ref
from .source_code_extractor import SourceCodeExtractor

SCHEMA_VERSION = 'xaman-source-coverage/v1'
DEFAULT_MANIFEST_PATH = Path('security_ir_artifacts/corpora/xaman-app/source-manifest.json')
DEFAULT_COVERAGE_PATH = Path('security_ir_artifacts/corpora/xaman-app/source-coverage.json')

_TYPESCRIPT_EXTENSIONS = {'.ts', '.tsx'}
_SUPPORTED_SOURCE_EXTENSIONS = {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'}
_E2E_FLOW_EXTENSIONS = {'.feature'}
_PARSABLE_EXTENSIONS = _SUPPORTED_SOURCE_EXTENSIONS | _E2E_FLOW_EXTENSIONS
_IMPORT_PATTERNS = (
    re.compile(r'\bimport\s+(?:type\s+)?(?:[\s\S]*?\s+from\s+)?[\'"]([^\'"]+)[\'"]', re.MULTILINE),
    re.compile(r'\bexport\s+(?:type\s+)?[\s\S]*?\s+from\s+[\'"]([^\'"]+)[\'"]', re.MULTILINE),
    re.compile(r'\brequire\(\s*[\'"]([^\'"]+)[\'"]\s*\)'),
    re.compile(r'\bimport\(\s*[\'"]([^\'"]+)[\'"]\s*\)'),
)
_JSON_LINE_COMMENT_RE = re.compile(r'(^|[^\:])//.*$', re.MULTILINE)
_JSON_BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
_JSON_TRAILING_COMMA_RE = re.compile(r',(\s*[}\]])')


@dataclass(frozen=True)
class _SourceFile:
    path: str
    size_bytes: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class _PathAlias:
    alias: str
    targets: tuple[str, ...]
    source_path: str
    source_kind: str
    base_url: str = '.'

    def as_dict(self) -> dict[str, Any]:
        return {
            'alias': self.alias,
            'targets': list(self.targets),
            'source_path': self.source_path,
            'source_kind': self.source_kind,
            'base_url': self.base_url,
            'review_status': 'parsed',
        }


class XamanSourceExtractor:
    """Extract reviewed source coverage for the pinned Xaman-App corpus."""

    def __init__(self) -> None:
        self._source_extractor = SourceCodeExtractor()

    def extract_coverage(
        self,
        *,
        corpus_root: str | Path | None = None,
        manifest_path: str | Path | None = DEFAULT_MANIFEST_PATH,
        out_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """Return deterministic Xaman source coverage.

        ``corpus_root`` may point at a real Xaman checkout.  ``manifest_path``
        supplies reproducibility metadata and lets the extractor fail closed
        when only digests are present.
        """

        root = Path(corpus_root) if corpus_root is not None else None
        manifest = self._read_manifest(Path(manifest_path)) if manifest_path is not None and Path(manifest_path).exists() else None
        source_files = self._source_files(root=root, manifest=manifest)
        aliases, alias_gaps = self._collect_path_aliases(root=root, source_files=source_files)
        relevant_files = [
            source_file
            for source_file in source_files
            if self._security_category(source_file.path) is not None
        ]

        modules: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = list(alias_gaps)
        for source_file in relevant_files:
            module, module_gaps = self._extract_module(source_file, root=root, aliases=aliases)
            modules.append(module)
            gaps.extend(module_gaps)

        gaps = self._dedupe_gaps(gaps)
        summary = self._coverage_summary(source_files, relevant_files, modules, gaps)
        coverage = {
            'schema_version': SCHEMA_VERSION,
            'corpus': manifest.get('corpus', 'xaman-app') if manifest else 'xaman-app',
            'source': self._source_metadata(manifest),
            'analysis_mode': self._analysis_mode(root, modules),
            'path_aliases': [alias.as_dict() for alias in aliases],
            'security_relevant_roots': [
                'src/services',
                'src/store',
                'src/common/libs/payload',
                'src/common/libs/ledger',
                'src/common/libs/vault.ts',
                'src/screens/Overlay/Authenticate',
                'src/screens/Overlay/PassphraseAuthentication',
                'e2e',
            ],
            'security_relevant_modules': sorted(modules, key=lambda item: item['path']),
            'coverage_summary': summary,
            'coverage_gaps': gaps,
            'reviewed_coverage_gaps': gaps,
            'metadata': {
                'generated_by': 'XamanSourceExtractor',
                'review_status': 'heuristic',
                'notes': [
                    'Parsed coverage is source-backed only when corpus_root is provided.',
                    'Manifest-only inputs are inventoried but recorded as reviewed gaps until source content is available.',
                ],
            },
        }
        if out_path is not None:
            self.write_coverage(coverage, Path(out_path))
        return coverage

    def parse_path_aliases(self, corpus_root: str | Path) -> list[dict[str, Any]]:
        """Parse TypeScript and local package aliases from a Xaman checkout."""

        root = Path(corpus_root)
        aliases, _ = self._collect_path_aliases(root=root, source_files=self._source_files(root=root, manifest=None))
        return [alias.as_dict() for alias in aliases]

    @staticmethod
    def write_coverage(coverage: dict[str, Any], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(coverage, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    def _read_manifest(self, manifest_path: Path) -> dict[str, Any]:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not isinstance(manifest.get('files'), list):
            raise ValueError(f'Xaman source manifest must contain a files array: {manifest_path}')
        return manifest

    def _source_files(self, *, root: Path | None, manifest: dict[str, Any] | None) -> list[_SourceFile]:
        if manifest is not None:
            files = [
                _SourceFile(
                    path=str(entry['path']),
                    size_bytes=int(entry['size_bytes']) if 'size_bytes' in entry else None,
                    sha256=str(entry['sha256']) if entry.get('sha256') else None,
                )
                for entry in manifest.get('files', [])
                if isinstance(entry, dict) and isinstance(entry.get('path'), str)
            ]
            return sorted(files, key=lambda item: item.path)
        if root is None:
            return []
        files: list[_SourceFile] = []
        for path in sorted(item for item in root.rglob('*') if item.is_file()):
            relative_path = path.relative_to(root).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append(_SourceFile(path=relative_path, size_bytes=path.stat().st_size, sha256=digest))
        return files

    def _collect_path_aliases(
        self,
        *,
        root: Path | None,
        source_files: list[_SourceFile],
    ) -> tuple[list[_PathAlias], list[dict[str, Any]]]:
        aliases: list[_PathAlias] = []
        gaps: list[dict[str, Any]] = []
        tsconfig_paths = [
            source_file.path
            for source_file in source_files
            if PurePosixPath(source_file.path).name in {'tsconfig.json', 'tsconfig.jest.json'}
        ]
        for tsconfig_path in sorted(tsconfig_paths):
            content = self._read_text(root, tsconfig_path)
            if content is None:
                gaps.append(
                    self._gap(
                        path=tsconfig_path,
                        category='path_alias',
                        reason='source_content_unavailable',
                        notes='TypeScript path aliases could not be parsed from manifest metadata alone.',
                    )
                )
                continue
            config = self._load_jsonc(content, tsconfig_path)
            compiler_options = config.get('compilerOptions', {}) if isinstance(config, dict) else {}
            if not isinstance(compiler_options, dict):
                continue
            base_url = str(compiler_options.get('baseUrl', '.'))
            paths = compiler_options.get('paths', {})
            if not isinstance(paths, dict):
                continue
            for alias, targets in sorted(paths.items()):
                if isinstance(targets, str):
                    target_values = (targets,)
                elif isinstance(targets, list):
                    target_values = tuple(str(target) for target in targets if isinstance(target, str))
                else:
                    continue
                if target_values:
                    aliases.append(
                        _PathAlias(
                            alias=str(alias),
                            targets=tuple(self._normalize_alias_target(base_url, target) for target in target_values),
                            source_path=tsconfig_path,
                            source_kind='typescript_paths',
                            base_url=base_url,
                        )
                    )

        package_json_paths = [
            source_file.path
            for source_file in source_files
            if PurePosixPath(source_file.path).name == 'package.json' and PurePosixPath(source_file.path).parent.as_posix() not in {'', '.'}
        ]
        for package_json_path in sorted(package_json_paths):
            content = self._read_text(root, package_json_path)
            if content is None:
                if package_json_path.startswith(('src/', 'e2e/')):
                    gaps.append(
                        self._gap(
                            path=package_json_path,
                            category='path_alias',
                            reason='source_content_unavailable',
                            notes='Local package alias metadata could not be parsed from manifest metadata alone.',
                        )
                    )
                continue
            package_data = self._load_jsonc(content, package_json_path)
            if not isinstance(package_data, dict) or not isinstance(package_data.get('name'), str):
                continue
            package_name = str(package_data['name']).strip()
            if not package_name:
                continue
            package_dir = PurePosixPath(package_json_path).parent.as_posix()
            aliases.append(
                _PathAlias(
                    alias=package_name,
                    targets=(package_dir,),
                    source_path=package_json_path,
                    source_kind='local_package_name',
                    base_url='.',
                )
            )
            aliases.append(
                _PathAlias(
                    alias=f'{package_name}/*',
                    targets=(f'{package_dir}/*',),
                    source_path=package_json_path,
                    source_kind='local_package_name',
                    base_url='.',
                )
            )
        return self._dedupe_aliases(aliases), gaps

    @staticmethod
    def _normalize_alias_target(base_url: str, target: str) -> str:
        normalized_base = base_url.strip().strip('/')
        normalized_target = target.strip().strip('/')
        if not normalized_base or normalized_base == '.':
            return normalized_target
        if normalized_target == normalized_base or normalized_target.startswith(f'{normalized_base}/'):
            return normalized_target
        return f'{normalized_base}/{normalized_target}'

    def _extract_module(
        self,
        source_file: _SourceFile,
        *,
        root: Path | None,
        aliases: list[_PathAlias],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        category = self._security_category(source_file.path)
        if category is None:
            raise ValueError(f'file is not security-relevant for Xaman extraction: {source_file.path}')
        language = self._language_for_path(source_file.path)
        suffix = PurePosixPath(source_file.path).suffix.lower()
        evidence = [
            make_evidence_ref(
                kind='source_code',
                path=source_file.path,
                line_start=1,
                line_end=1,
                sha256=source_file.sha256,
                review_status='heuristic',
                notes='Xaman security-relevant source file selected for coverage extraction.',
            )
        ]
        module: dict[str, Any] = {
            'path': source_file.path,
            'category': category,
            'security_tags': self._security_tags(source_file.path),
            'language': language,
            'size_bytes': source_file.size_bytes,
            'sha256': source_file.sha256,
            'parse_status': 'pending',
            'parser': None,
            'imports': [],
            'resolved_imports': [],
            'symbols': [],
            'policies': [],
            'events': [],
            'invariants': [],
            'evidence_refs': evidence,
            'review_status': 'heuristic',
        }
        gaps: list[dict[str, Any]] = []
        if suffix not in _PARSABLE_EXTENSIONS:
            module['parse_status'] = 'unsupported'
            gaps.append(
                self._gap(
                    path=source_file.path,
                    category=category,
                    reason='unsupported_extension',
                    notes=f'Extension {suffix or "<none>"} is inventoried but not parsed by the Xaman TypeScript extractor.',
                )
            )
            return module, gaps

        content = self._read_text(root, source_file.path)
        if content is None:
            module['parse_status'] = 'content_unavailable'
            gaps.append(
                self._gap(
                    path=source_file.path,
                    category=category,
                    reason='source_content_unavailable',
                    notes='The manifest records this security-relevant file, but source text was not available in this worktree.',
                )
            )
            return module, gaps

        module['line_count'] = max(len(content.splitlines()), 1)
        module['evidence_refs'][0]['line_end'] = module['line_count']
        imports = self._imports_from_source(content)
        module['imports'] = imports
        module['resolved_imports'] = [self._resolve_import(import_spec, source_file.path, aliases) for import_spec in imports]

        if suffix in _E2E_FLOW_EXTENSIONS:
            module['parse_status'] = 'parsed'
            module['parser'] = 'gherkin_feature'
            module['symbols'] = self._parse_gherkin_symbols(content)
            module['events'] = [
                {
                    'event': symbol['name'],
                    'kind': 'xaman_e2e_flow',
                    'critical': True,
                    'line_start': symbol['line_start'],
                }
                for symbol in module['symbols']
            ]
            return module, gaps

        try:
            ir = self._source_extractor.extract_ir_from_source(
                content,
                language='typescript' if suffix in _TYPESCRIPT_EXTENSIONS else 'javascript',
                model_id=f'xaman-source:{source_file.path}',
                module_path=source_file.path,
            )
        except ValueError as exc:
            module['parse_status'] = 'parse_error'
            gaps.append(
                self._gap(
                    path=source_file.path,
                    category=category,
                    reason='parse_error',
                    notes=str(exc),
                )
            )
            return module, gaps

        module['parse_status'] = 'parsed'
        module['parser'] = 'source_code_extractor'
        module['symbols'] = self._symbols_from_ir(ir)
        module['policies'] = [
            {
                'id': policy.get('id'),
                'name': policy.get('name'),
                'sources': policy.get('sources', []),
            }
            for policy in ir.policies
        ]
        module['events'] = [
            {
                'id': event.get('id'),
                'event': event.get('event'),
                'critical': bool(event.get('critical')),
            }
            for event in ir.events
        ]
        module['invariants'] = [
            {
                'id': invariant.get('id'),
                'description': invariant.get('description'),
            }
            for invariant in ir.invariants
        ]
        return module, gaps

    @staticmethod
    def _security_category(path: str) -> str | None:
        if path == 'src/common/libs/vault.ts':
            return 'vault'
        if path.startswith('src/common/libs/payload/'):
            return 'payload'
        if path.startswith('src/common/libs/ledger/'):
            return 'ledger'
        if path.startswith('src/screens/Overlay/Authenticate/') or path.startswith('src/screens/Overlay/PassphraseAuthentication/'):
            return 'auth_component'
        if path.startswith('src/services/'):
            return 'service'
        if path.startswith('src/store/'):
            return 'store'
        if path.startswith('e2e/'):
            return 'e2e_flow'
        return None

    @staticmethod
    def _security_tags(path: str) -> list[str]:
        normalized = path.lower()
        tags: list[str] = []
        tag_patterns = {
            'account': ('account', 'profile'),
            'authentication': ('auth', 'biometric', 'passphrase'),
            'ledger': ('ledger', 'xrpl', 'transaction', 'sign', 'submit'),
            'payload': ('payload', 'digest'),
            'storage': ('store', 'storage', 'repository', 'vault'),
            'network': ('api', 'backend', 'network', 'resolver'),
            'e2e': ('e2e/', '.feature'),
        }
        for tag, patterns in tag_patterns.items():
            if any(pattern in normalized for pattern in patterns):
                tags.append(tag)
        return tags or ['security_review']

    @staticmethod
    def _language_for_path(path: str) -> str:
        suffix = PurePosixPath(path).suffix.lower()
        return {
            '.ts': 'typescript',
            '.tsx': 'typescriptreact',
            '.js': 'javascript',
            '.jsx': 'javascriptreact',
            '.mjs': 'javascript',
            '.cjs': 'javascript',
            '.feature': 'gherkin',
            '.json': 'json',
        }.get(suffix, suffix.lstrip('.') or 'unknown')

    @staticmethod
    def _imports_from_source(source: str) -> list[str]:
        imports: list[str] = []
        for pattern in _IMPORT_PATTERNS:
            for match in pattern.finditer(source):
                specifier = match.group(1)
                if specifier not in imports:
                    imports.append(specifier)
        return imports

    def _resolve_import(self, import_spec: str, from_path: str, aliases: list[_PathAlias]) -> dict[str, Any]:
        resolved: dict[str, Any] = {
            'specifier': import_spec,
            'resolved_path': None,
            'resolution': 'external',
            'alias': None,
        }
        if import_spec.startswith('.'):
            base = PurePosixPath(from_path).parent
            resolved['resolved_path'] = self._normalize_posix_path(base.joinpath(import_spec).as_posix())
            resolved['resolution'] = 'relative'
            return resolved
        for alias in aliases:
            target = self._match_alias(import_spec, alias)
            if target is not None:
                resolved['resolved_path'] = target
                resolved['resolution'] = 'alias'
                resolved['alias'] = alias.alias
                return resolved
        return resolved

    @staticmethod
    def _match_alias(import_spec: str, alias: _PathAlias) -> str | None:
        if '*' in alias.alias:
            prefix, suffix = alias.alias.split('*', 1)
            if not import_spec.startswith(prefix) or (suffix and not import_spec.endswith(suffix)):
                return None
            wildcard = import_spec[len(prefix) : len(import_spec) - len(suffix) if suffix else len(import_spec)]
            target = alias.targets[0].replace('*', wildcard)
            return XamanSourceExtractor._normalize_posix_path(target)
        if import_spec == alias.alias:
            return XamanSourceExtractor._normalize_posix_path(alias.targets[0])
        if import_spec.startswith(f'{alias.alias}/'):
            remainder = import_spec[len(alias.alias) + 1 :]
            return XamanSourceExtractor._normalize_posix_path(f'{alias.targets[0]}/{remainder}')
        return None

    @staticmethod
    def _normalize_posix_path(path: str) -> str:
        parts: list[str] = []
        for part in PurePosixPath(path).parts:
            if part in {'', '.'}:
                continue
            if part == '..':
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        return '/'.join(parts)

    @staticmethod
    def _parse_gherkin_symbols(source: str) -> list[dict[str, Any]]:
        symbols: list[dict[str, Any]] = []
        for line_number, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            match = re.match(r'^(Feature|Scenario(?: Outline)?):\s*(.+)$', stripped)
            if match:
                symbols.append(
                    {
                        'name': match.group(2).strip(),
                        'kind': match.group(1).lower().replace(' ', '_'),
                        'line_start': line_number,
                    }
                )
        return symbols

    @staticmethod
    def _symbols_from_ir(ir: Any) -> list[dict[str, Any]]:
        symbols: list[dict[str, Any]] = []
        for entity in ir.entities:
            symbols.append({'name': entity.get('name'), 'kind': 'class'})
        for event in ir.events:
            symbols.append({'name': event.get('event'), 'kind': 'function'})
        seen: set[tuple[str, str]] = set()
        deduped: list[dict[str, Any]] = []
        for symbol in symbols:
            key = (str(symbol.get('kind')), str(symbol.get('name')))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(symbol)
        return deduped

    @staticmethod
    def _strip_jsonc_comments(source: str) -> str:
        """Remove JSONC comments without treating URL-like string content as a comment."""

        result: list[str] = []
        index = 0
        quote = ''
        escaped = False
        length = len(source)
        while index < length:
            character = source[index]
            if quote:
                result.append(character)
                if escaped:
                    escaped = False
                elif character == '\\':
                    escaped = True
                elif character == quote:
                    quote = ''
                index += 1
                continue
            if character in {'"', "'"}:
                quote = character
                result.append(character)
                index += 1
                continue
            if source.startswith('//', index):
                newline = source.find('\n', index)
                if newline == -1:
                    break
                result.append('\n')
                index = newline + 1
                continue
            if source.startswith('/*', index):
                closing = source.find('*/', index + 2)
                if closing == -1:
                    raise ValueError('unterminated JSONC block comment')
                result.extend('\n' for character in source[index:closing + 2] if character == '\n')
                index = closing + 2
                continue
            result.append(character)
            index += 1
        return ''.join(result)

    @classmethod
    def _load_jsonc(cls, source: str, path: str) -> dict[str, Any]:
        stripped = cls._strip_jsonc_comments(source)
        stripped = _JSON_TRAILING_COMMA_RE.sub(r'\1', stripped)
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f'failed to parse JSON config {path}: {exc}') from exc
        if not isinstance(loaded, dict):
            raise ValueError(f'JSON config must be an object: {path}')
        return loaded

    @staticmethod
    def _read_text(root: Path | None, relative_path: str) -> str | None:
        if root is None:
            return None
        path = root / relative_path
        if not path.is_file():
            return None
        return path.read_text(encoding='utf-8')

    @staticmethod
    def _source_metadata(manifest: dict[str, Any] | None) -> dict[str, Any]:
        if manifest is None:
            return {'kind': 'local_checkout'}
        source = manifest.get('source', {})
        reproducibility = manifest.get('reproducibility', {})
        return {
            'kind': 'xaman_source_manifest',
            'repo_url': source.get('repo_url') or source.get('repository_url'),
            'commit_sha': source.get('commit_sha') or source.get('commit'),
            'aggregate_sha256': reproducibility.get('aggregate_sha256'),
            'manifest_schema_version': manifest.get('schema_version'),
        }

    @staticmethod
    def _analysis_mode(root: Path | None, modules: list[dict[str, Any]]) -> str:
        if root is None:
            return 'manifest_only'
        if modules and all(module.get('parse_status') == 'parsed' for module in modules):
            return 'source'
        return 'mixed'

    @staticmethod
    def _coverage_summary(
        source_files: list[_SourceFile],
        relevant_files: list[_SourceFile],
        modules: list[dict[str, Any]],
        gaps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        parsed = sum(1 for module in modules if module.get('parse_status') == 'parsed')
        unsupported = sum(1 for module in modules if module.get('parse_status') == 'unsupported')
        content_unavailable = sum(1 for module in modules if module.get('parse_status') == 'content_unavailable')
        parse_errors = sum(1 for module in modules if module.get('parse_status') == 'parse_error')
        relevant_count = len(relevant_files)
        return {
            'manifest_files': len(source_files),
            'security_relevant_files': relevant_count,
            'parsed_files': parsed,
            'unsupported_files': unsupported,
            'content_unavailable_files': content_unavailable,
            'parse_error_files': parse_errors,
            'reviewed_gap_count': len(gaps),
            'parsed_coverage_percent': round((parsed / relevant_count) * 100, 2) if relevant_count else 0.0,
        }

    @staticmethod
    def _gap(*, path: str, category: str, reason: str, notes: str) -> dict[str, Any]:
        digest = hashlib.sha256(f'{path}\0{category}\0{reason}\0{notes}'.encode('utf-8')).hexdigest()[:16]
        return {
            'id': f'xaman-coverage-gap:{digest}',
            'path': path,
            'category': category,
            'reason': reason,
            'review_status': 'reviewed_gap',
            'blocking': reason in {'source_content_unavailable', 'parse_error'},
            'notes': notes,
        }

    @staticmethod
    def _dedupe_aliases(aliases: list[_PathAlias]) -> list[_PathAlias]:
        deduped: dict[tuple[str, tuple[str, ...], str, str], _PathAlias] = {}
        for alias in aliases:
            deduped[(alias.alias, alias.targets, alias.source_path, alias.source_kind)] = alias
        return sorted(
            deduped.values(),
            key=lambda alias: (
                alias.alias.count('*'),
                -len(alias.alias.replace('*', '')),
                alias.alias,
                alias.source_path,
            ),
        )

    @staticmethod
    def _dedupe_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for gap in gaps:
            deduped[str(gap['id'])] = gap
        return [deduped[key] for key in sorted(deduped)]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Extract Xaman source coverage metadata.')
    parser.add_argument('--corpus-root', help='Optional Xaman checkout root containing source text.')
    parser.add_argument('--manifest', default=str(DEFAULT_MANIFEST_PATH), help='Pinned Xaman source manifest path.')
    parser.add_argument('--out', default=str(DEFAULT_COVERAGE_PATH), help='Coverage JSON output path.')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    extractor = XamanSourceExtractor()
    extractor.extract_coverage(
        corpus_root=args.corpus_root,
        manifest_path=args.manifest,
        out_path=args.out,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
