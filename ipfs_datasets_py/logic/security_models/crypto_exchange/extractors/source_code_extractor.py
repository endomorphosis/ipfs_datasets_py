"""Multi-language code extractor for seed security models."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..ir.schema import SecurityModelIR, make_evidence_ref
from .python_ast_extractor import (
    PythonASTExtractor,
    _CRITICAL_ACTION_KEYWORDS,
    _MAX_POLICY_SOURCE_LINES,
    _POLICY_PATTERNS,
)

_SUPPORTED_LANGUAGE_EXTENSIONS = {
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.mjs': 'javascript',
    '.cjs': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.go': 'go',
    '.java': 'java',
    '.rs': 'rust',
}

_FUNCTION_PATTERNS = {
    'javascript': (
        re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\('),
        re.compile(r'^\s*(?:export\s+)?const\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\('),
        re.compile(r'^\s*(?:public\s+|private\s+|protected\s+)?(?:async\s+)?([A-Za-z_]\w*)\s*\([^)]*\)\s*(?:\{|:)'),
    ),
    'typescript': (
        re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\('),
        re.compile(r'^\s*(?:export\s+)?const\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\('),
        re.compile(r'^\s*(?:public\s+|private\s+|protected\s+)?(?:async\s+)?([A-Za-z_]\w*)\s*\([^)]*\)\s*(?:\{|:)'),
    ),
    'go': (
        re.compile(r'^\s*func\s+(?:\(\s*\w+\s+\*?\w+\s*\)\s*)?([A-Za-z_]\w*)\s*\('),
    ),
    'java': (
        re.compile(
            r'^\s*(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?[\w<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\('
        ),
    ),
    'rust': (
        re.compile(r'^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)\s*\('),
    ),
}

_CLASS_PATTERNS = {
    'javascript': (re.compile(r'^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_]\w*)\b'),),
    'typescript': (re.compile(r'^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_]\w*)\b'),),
    'go': (re.compile(r'^\s*type\s+([A-Za-z_]\w*)\s+struct\b'),),
    'java': (re.compile(r'^\s*(?:public|protected|private)?\s*class\s+([A-Za-z_]\w*)\b'),),
    'rust': (re.compile(r'^\s*(?:pub\s+)?struct\s+([A-Za-z_]\w*)\b'),),
}

_COMMENT_PREFIXES = ('//', '///', '//!')
_BLOCK_COMMENT_START = ('/*', '/**')
_BLOCK_COMMENT_END = '*/'
_CRITICAL_ACTION_PATTERNS = tuple(re.compile(r'\b' + re.escape(keyword) + r'\b') for keyword in _CRITICAL_ACTION_KEYWORDS)
_NON_DECLARATION_PREFIXES = ('if', 'for', 'while', 'switch', 'catch', 'return', 'throw', 'new')



def _merge_lists(left: list[Any], right: list[Any]) -> list[Any]:
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged


@dataclass(frozen=True)
class _CodeSymbol:
    """Symbol metadata harvested from non-Python source code."""

    name: str
    kind: str
    comment: str
    body_excerpt: str
    line_start: int
    line_end: int


class SourceCodeExtractor:
    """Autoformalize popular programming languages into a seed security IR."""

    def __init__(self) -> None:
        self._python = PythonASTExtractor()

    def extract_ir_from_source(
        self,
        source: str,
        *,
        language: str,
        model_id: str = 'source-autoformalized-model',
        module_path: str | None = None,
    ) -> SecurityModelIR:
        """Autoformalize *source* written in *language* into a seed security IR."""

        normalized_language = language.lower()
        if normalized_language == 'python':
            return self._python.extract_ir_from_source(source, model_id=model_id, module_path=module_path)
        if normalized_language not in _FUNCTION_PATTERNS:
            raise ValueError(f'Unsupported source language for autoformalization: {language}')

        symbols = self._collect_symbols(source, normalized_language)
        source_name = module_path or '<memory>'
        source_digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
        autoformalization = {
            'kind': 'source_code',
            'language': normalized_language,
            'module_path': source_name,
            'source_digest': source_digest,
            'review_status': 'heuristic',
            'evidence_refs': [
                make_evidence_ref(
                    kind='source_code',
                    path=source_name,
                    line_start=1,
                    line_end=max(len(source.splitlines()), 1),
                    sha256=source_digest,
                    review_status='heuristic',
                    notes='Seed multi-language autoformalization requires human review before blocking proofs.',
                )
            ],
            'gaps': [
                'Facts are inferred from syntax and nearby comments; human review is required before production proofs.',
                'Cross-function dataflow, concrete balances, and principal aliasing remain partially modeled.',
            ],
        }
        functions: list[_CodeSymbol] = []
        classes: list[_CodeSymbol] = []
        for symbol in symbols:
            if symbol.kind == 'function':
                functions.append(symbol)
            elif symbol.kind == 'class':
                classes.append(symbol)
        events = self._collect_events(functions, source_name, source_digest, normalized_language)
        return SecurityModelIR(
            schema_version='security-model-ir/v1',
            model_id=model_id,
            entities=[
                {'id': f'entity:{normalized_language}:class:{symbol.name}', 'kind': f'{normalized_language}_class', 'name': symbol.name, 'module': source_name}
                for symbol in classes
            ],
            assets=[],
            wallets=[],
            accounts=[],
            roles=[],
            principals=[],
            capabilities=[],
            policies=self._collect_policy_entries(functions, source_name, source_digest),
            events=events,
            state_machines=[
                {
                    'id': f'sm:{normalized_language}:{source_digest[:12]}:{event["event"]}:{event["evidence_refs"][0]["line_start"]}',
                    'states': ['defined', 'reachable'],
                    'current': 'reachable',
                    'source_function': event['event'],
                }
                for event in events
                if event.get('critical')
            ],
            invariants=self._collect_invariants(symbols, source_name, source_digest, normalized_language),
            assumptions=[],
            prover_targets=['z3'],
            metadata={'autoformalization': autoformalization},
        )

    def extract_ir_from_path(self, path: str | Path, *, model_id: str | None = None) -> SecurityModelIR:
        """Autoformalize a supported source file or directory tree into a seed security IR."""

        target = Path(path)
        if target.is_dir():
            return self._extract_ir_from_directory(target, model_id=model_id or f'codebase:{target.name}')

        language = self._detect_language(target)
        source = target.read_text(encoding='utf-8')
        return self.extract_ir_from_source(
            source,
            language=language,
            model_id=model_id or f'{language}-module:{target.stem}',
            module_path=str(target),
        )

    def _extract_ir_from_directory(self, root: Path, *, model_id: str) -> SecurityModelIR:
        file_paths = sorted(
            file_path
            for file_path in root.rglob('*')
            if file_path.is_file() and file_path.suffix.lower() in _SUPPORTED_LANGUAGE_EXTENSIONS
        )
        if not file_paths:
            raise ValueError(f'No supported source files found under {root}')

        models = [
            self.extract_ir_from_source(
                file_path.read_text(encoding='utf-8'),
                language=self._detect_language(file_path),
                model_id=f'{self._detect_language(file_path)}-module:{file_path.stem}',
                module_path=str(file_path),
            )
            for file_path in file_paths
        ]
        languages = sorted({self._get_model_language(model) for model in models})
        return SecurityModelIR(
            schema_version='security-model-ir/v1',
            model_id=model_id,
            entities=self._merge_model_field(models, 'entities'),
            assets=[],
            wallets=[],
            accounts=[],
            roles=[],
            principals=[],
            capabilities=[],
            policies=self._merge_model_field(models, 'policies'),
            events=self._merge_model_field(models, 'events'),
            state_machines=self._merge_model_field(models, 'state_machines'),
            invariants=self._merge_model_field(models, 'invariants'),
            assumptions=[],
            prover_targets=['z3'],
            metadata={
                'autoformalization': {
                    'kind': 'source_code_directory',
                    'languages': languages,
                    'root_path': str(root),
                    'source_files': [model.metadata['autoformalization']['module_path'] for model in models],
                    'review_status': 'heuristic',
                    'evidence_refs': [
                        reference
                        for model in models
                        for reference in model.metadata['autoformalization'].get('evidence_refs', [])
                    ],
                    'gaps': [
                        'Directory aggregation preserves per-module facts but does not yet reconcile cross-language principal or asset aliases.',
                    ],
                }
            },
        )

    @staticmethod
    def _detect_language(path: Path) -> str:
        try:
            return _SUPPORTED_LANGUAGE_EXTENSIONS[path.suffix.lower()]
        except KeyError as exc:
            raise ValueError(f'Unsupported source file for autoformalization: {path}') from exc

    def _get_model_language(self, model: SecurityModelIR) -> str:
        autoformalization = model.metadata.get('autoformalization', {})
        language = autoformalization.get('language')
        if language:
            return language
        return self._detect_language(Path(autoformalization['module_path']))

    def _merge_model_field(self, models: list[SecurityModelIR], field_name: str) -> list[dict[str, Any]]:
        return self._dedupe_dicts(self._flatten(getattr(model, field_name) for model in models), 'id')

    def _collect_symbols(self, source: str, language: str) -> list[_CodeSymbol]:
        symbols: list[_CodeSymbol] = []
        comment_buffer: list[str] = []
        block_comment: list[str] = []
        in_block_comment = False
        lines = source.splitlines()

        for index, line in enumerate(lines, start=1):
            stripped = line.strip()
            if in_block_comment:
                before_end, has_end, _ = stripped.partition(_BLOCK_COMMENT_END)
                content = before_end.lstrip('*').strip()
                if content:
                    block_comment.append(content)
                if has_end:
                    in_block_comment = False
                    if block_comment:
                        comment_buffer.extend(block_comment)
                    block_comment = []
                continue

            if stripped.startswith(_BLOCK_COMMENT_START):
                if _BLOCK_COMMENT_END in stripped:
                    content = stripped.split('/*', 1)[1].rsplit(_BLOCK_COMMENT_END, 1)[0].replace('*', ' ').strip()
                    if content:
                        comment_buffer.append(content)
                    continue
                in_block_comment = True
                content = stripped.split('/*', 1)[1].replace('*', ' ').strip()
                if content:
                    block_comment.append(content)
                continue

            if any(stripped.startswith(prefix) for prefix in _COMMENT_PREFIXES):
                comment_buffer.append(stripped.lstrip('/').lstrip('!').strip())
                continue

            matched_kind: str | None = None
            matched_name: str | None = None
            if self._looks_like_non_declaration(stripped):
                continue
            for pattern in _CLASS_PATTERNS[language]:
                match = pattern.match(line)
                if match:
                    matched_kind = 'class'
                    matched_name = match.group(1)
                    break
            if matched_name is None:
                for pattern in _FUNCTION_PATTERNS[language]:
                    match = pattern.match(line)
                    if match:
                        matched_kind = 'function'
                        matched_name = match.group(1)
                        break

            if matched_name:
                body_lines = lines[index - 1 : index - 1 + _MAX_POLICY_SOURCE_LINES]
                symbols.append(
                    _CodeSymbol(
                        name=matched_name,
                        kind=matched_kind or 'function',
                        comment=' '.join(comment_buffer).strip(),
                        body_excerpt='\n'.join(body_lines),
                        line_start=index,
                        line_end=index + max(len(body_lines) - 1, 0),
                    )
                )
                comment_buffer = []
                continue

            if stripped and not stripped.startswith('@'):
                comment_buffer = []

        return symbols

    @staticmethod
    def _looks_like_non_declaration(line: str) -> bool:
        return any(line.startswith(f'{prefix} ') or line.startswith(f'{prefix}(') for prefix in _NON_DECLARATION_PREFIXES)

    @staticmethod
    def _flatten(values: Iterable[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for group in values:
            flattened.extend(group)
        return flattened

    @staticmethod
    def _dedupe_dicts(entries: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for entry in entries:
            entry_key = entry[key]
            if entry_key not in deduped:
                deduped[entry_key] = dict(entry)
                continue
            existing = deduped[entry_key]
            merged = dict(existing)
            for field_name, value in entry.items():
                if field_name == key:
                    continue
                if isinstance(existing.get(field_name), list) and isinstance(value, list):
                    merged[field_name] = _merge_lists(existing[field_name], value)
                elif field_name not in merged or merged[field_name] in (None, '', []):
                    merged[field_name] = value
            deduped[entry_key] = merged
        return [deduped[item_key] for item_key in sorted(deduped)]

    def _evidence_ref(self, *, path: str, source_digest: str, symbol: _CodeSymbol, notes: str) -> dict[str, Any]:
        return make_evidence_ref(
            kind='source_code',
            path=path,
            line_start=symbol.line_start,
            line_end=symbol.line_end,
            sha256=source_digest,
            review_status='heuristic',
            notes=notes,
        )

    def _collect_policy_entries(self, functions: list[_CodeSymbol], path: str, source_digest: str) -> list[dict[str, Any]]:
        policies: dict[str, dict[str, Any]] = {}
        for function in functions:
            haystack = ' '.join(filter(None, [function.name, function.comment, function.body_excerpt])).lower()
            for policy_name, patterns in _POLICY_PATTERNS.items():
                if any(pattern.search(haystack) for pattern in patterns):
                    policy_id = f'policy:{policy_name}'
                    policy = policies.setdefault(
                        policy_id,
                        {
                            'id': policy_id,
                            'name': policy_name,
                            'enabled': True,
                            'sources': [],
                            'evidence_refs': [],
                        },
                    )
                    if function.name not in policy['sources']:
                        policy['sources'].append(function.name)
                    reference = self._evidence_ref(path=path, source_digest=source_digest, symbol=function, notes=f'Policy inferred from {function.name}.')
                    if reference not in policy['evidence_refs']:
                        policy['evidence_refs'].append(reference)
        return sorted(policies.values(), key=lambda item: item['id'])

    def _collect_invariants(self, symbols: list[_CodeSymbol], path: str, source_digest: str, language: str) -> list[dict[str, Any]]:
        invariants: list[dict[str, Any]] = []
        path_hash = source_digest[:12]
        for symbol in symbols:
            if not symbol.comment:
                continue
            for index, sentence in enumerate(self._python._extract_security_sentences(symbol.comment), start=1):
                predicates, relations = self._python._extract_natural_language_features(sentence)
                entry: dict[str, Any] = {
                    'id': f'inv:{language}:{path_hash}:{symbol.name}:{symbol.line_start}:{index}',
                    'description': sentence,
                    'formalization': {
                        'fol': self._python._to_fol(sentence),
                        'predicates': predicates,
                        'relations': relations,
                    },
                    'evidence_refs': [
                        self._evidence_ref(path=path, source_digest=source_digest, symbol=symbol, notes=f'Invariant inferred from comment near {symbol.name}.')
                    ],
                }
                entry['source_function' if symbol.kind == 'function' else 'source_class'] = symbol.name
                invariants.append(entry)
        return invariants

    def _collect_events(self, functions: list[_CodeSymbol], path: str, source_digest: str, language: str) -> list[dict[str, Any]]:
        path_hash = source_digest[:12]
        return [
            {
                'id': f'event:{language}:{path_hash}:{function.name}:{function.line_start}',
                'event': function.name,
                'kind': 'code_path',
                'custom': True,
                'description': f'Autoformalized code-path event for {function.name}.',
                'critical': any(pattern.search(function.name.lower()) for pattern in _CRITICAL_ACTION_PATTERNS),
                'evidence_refs': [
                    self._evidence_ref(path=path, source_digest=source_digest, symbol=function, notes=f'Code-path event harvested from {function.name}.')
                ],
            }
            for function in functions
        ]
