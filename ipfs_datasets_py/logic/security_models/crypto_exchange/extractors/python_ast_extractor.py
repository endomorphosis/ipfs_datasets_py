"""Python AST extractor for seed security models."""

from __future__ import annotations

import ast
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Iterable

from ..ir.schema import SecurityModelIR, make_evidence_ref

logger = logging.getLogger(__name__)

_SECURITY_SENTENCE_PATTERN = re.compile(r'(?<=[.!?])\s+|\n+')
_POLICY_KEYWORDS: dict[str, tuple[str, ...]] = {
    'authorization_required': ('authorized', 'authorization', 'authenticate', 'permission', 'permit'),
    'fresh_nonce_required': ('nonce', 'replay', 'fresh'),
    'sufficient_balance_required': ('balance', 'reservation', 'reserve', 'overdraft'),
    'wallet_not_frozen_required': ('frozen', 'freeze', 'locked', 'suspend'),
    'audit_required': ('audit', 'log', 'logged', 'emit audit'),
    'revocation_enforced': ('revoked', 'revocation', 'revoke'),
    'delegation_monotonicity': ('delegate', 'delegation', 'authority', 'capability'),
}
_SECURITY_KEYWORDS = (
    'must',
    'only',
    'before',
    'after',
    'cannot',
    'never',
    'require',
    'required',
    'eventually',
    'authorized',
    'revoked',
    'frozen',
)
_CRITICAL_ACTION_KEYWORDS = (
    'withdraw',
    'deposit',
    'broadcast',
    'sign',
    'freeze',
    'revoke',
    'delegate',
    'approve',
    'credit',
    'transfer',
)



def _compile_keyword_pattern(keyword: str) -> re.Pattern[str]:
    return re.compile(r'\b' + re.escape(keyword).replace(r'\ ', r'\s+') + r'\b')



def _compile_keyword_patterns(keywords: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(_compile_keyword_pattern(keyword) for keyword in keywords)



def _merge_lists(left: list[Any], right: list[Any]) -> list[Any]:
    merged = list(left)
    for item in right:
        if item not in merged:
            merged.append(item)
    return merged


_POLICY_PATTERNS = {
    policy_name: tuple(_compile_keyword_pattern(keyword) for keyword in keywords)
    for policy_name, keywords in _POLICY_KEYWORDS.items()
}
_SECURITY_PATTERNS = tuple(_compile_keyword_pattern(keyword) for keyword in _SECURITY_KEYWORDS)
_MAX_POLICY_SOURCE_LINES = 12


class PythonASTExtractor:
    """Extract lightweight symbol metadata and seed IR facts from Python code."""

    def extract_from_source(self, source: str, *, module_path: str = '<memory>') -> dict[str, Any]:
        """Extract lightweight summary facts from Python *source*."""

        tree = ast.parse(source)
        functions = sorted(node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
        classes = sorted(node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
        policies = self._collect_policy_entries(tree, source, module_path)
        invariants = self._collect_invariants(tree, source, module_path)
        events = self._collect_events(tree, source, module_path)
        return {
            'functions': functions,
            'classes': classes,
            'policies': policies,
            'invariants': invariants,
            'events': events,
        }

    def extract_ir_from_source(
        self,
        source: str,
        *,
        model_id: str = 'python-autoformalized-model',
        module_path: str | None = None,
    ) -> SecurityModelIR:
        """Autoformalize Python *source* into a seed :class:`SecurityModelIR`."""

        source_name = module_path or '<memory>'
        summary = self.extract_from_source(source, module_path=source_name)
        source_digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
        path_hash = source_digest[:12]
        autoformalization = {
            'kind': 'python_ast',
            'language': 'python',
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
                    notes='Seed Python AST autoformalization requires review before blocking proofs.',
                )
            ],
            'gaps': [
                'Policies are inferred from syntax and docstrings; human review is required before production proofs.',
                'Dataflow-sensitive facts such as concrete balances, principals, and on-chain settlement remain partially modeled.',
            ],
        }
        return SecurityModelIR(
            schema_version='security-model-ir/v1',
            model_id=model_id,
            entities=[
                {'id': f'entity:class:{class_name}', 'kind': 'python_class', 'name': class_name, 'module': source_name}
                for class_name in summary['classes']
            ],
            assets=[],
            wallets=[],
            accounts=[],
            roles=[],
            principals=[],
            capabilities=[],
            policies=summary['policies'],
            events=summary['events'],
            state_machines=[
                {
                    'id': f'sm:python:{path_hash}:{event["event"]}:{event["evidence_refs"][0]["line_start"]}',
                    'states': ['defined', 'reachable'],
                    'current': 'reachable',
                    'source_function': event['event'],
                }
                for event in summary['events']
                if event.get('critical')
            ],
            invariants=summary['invariants'],
            assumptions=[],
            prover_targets=['z3'],
            metadata={'autoformalization': autoformalization},
        )

    def extract_ir_from_path(self, path: str | Path, *, model_id: str | None = None) -> SecurityModelIR:
        """Autoformalize a Python file or directory tree into a seed security IR."""

        target = Path(path)
        if target.is_dir():
            return self._extract_ir_from_directory(target, model_id=model_id or f'python-codebase:{target.name}')
        source = target.read_text(encoding='utf-8')
        return self.extract_ir_from_source(source, model_id=model_id or f'python-module:{target.stem}', module_path=str(target))

    def _extract_ir_from_directory(self, root: Path, *, model_id: str) -> SecurityModelIR:
        models = [
            self.extract_ir_from_source(
                file_path.read_text(encoding='utf-8'),
                model_id=f'python-module:{file_path.stem}',
                module_path=str(file_path),
            )
            for file_path in sorted(root.rglob('*.py'))
        ]
        return SecurityModelIR(
            schema_version='security-model-ir/v1',
            model_id=model_id,
            entities=self._dedupe_dicts(self._flatten(model.entities for model in models), 'id'),
            assets=[],
            wallets=[],
            accounts=[],
            roles=[],
            principals=[],
            capabilities=[],
            policies=self._dedupe_dicts(self._flatten(model.policies for model in models), 'id'),
            events=self._dedupe_dicts(self._flatten(model.events for model in models), 'id'),
            state_machines=self._dedupe_dicts(self._flatten(model.state_machines for model in models), 'id'),
            invariants=self._dedupe_dicts(self._flatten(model.invariants for model in models), 'id'),
            assumptions=[],
            prover_targets=['z3'],
            metadata={
                'autoformalization': {
                    'kind': 'python_ast_directory',
                    'languages': ['python'],
                    'root_path': str(root),
                    'source_files': [model.metadata['autoformalization']['module_path'] for model in models],
                    'review_status': 'heuristic',
                    'evidence_refs': [
                        reference
                        for model in models
                        for reference in model.metadata['autoformalization'].get('evidence_refs', [])
                    ],
                    'gaps': [
                        'Directory aggregation preserves per-module facts but does not yet reconcile cross-module principal or asset aliases.',
                    ],
                }
            },
        )

    def _evidence_ref(
        self,
        *,
        path: str,
        source_digest: str,
        line_start: int,
        line_end: int,
        notes: str,
    ) -> dict[str, Any]:
        return make_evidence_ref(
            kind='source_code',
            path=path,
            line_start=line_start,
            line_end=line_end,
            sha256=source_digest,
            review_status='heuristic',
            notes=notes,
        )

    def _collect_policy_entries(self, tree: ast.AST, source: str, module_path: str = '<memory>') -> list[dict[str, Any]]:
        policies: dict[str, dict[str, Any]] = {}
        source_digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
        for function in self._iter_functions(tree):
            body_excerpt = '\n'.join((ast.get_source_segment(source, function) or '').splitlines()[:_MAX_POLICY_SOURCE_LINES])
            haystack = ' '.join(filter(None, [function.name, ast.get_docstring(function) or '', body_excerpt])).lower()
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
                    reference = self._evidence_ref(
                        path=module_path,
                        source_digest=source_digest,
                        line_start=function.lineno,
                        line_end=getattr(function, 'end_lineno', function.lineno),
                        notes=f'Policy inferred from function {function.name}.',
                    )
                    if reference not in policy['evidence_refs']:
                        policy['evidence_refs'].append(reference)
        return sorted(policies.values(), key=lambda item: item['id'])

    def _collect_invariants(self, tree: ast.AST, source: str, module_path: str = '<memory>') -> list[dict[str, Any]]:
        invariants: list[dict[str, Any]] = []
        source_digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
        for function in self._iter_functions(tree):
            docstring = ast.get_docstring(function) or ''
            for index, sentence in enumerate(self._extract_security_sentences(docstring), start=1):
                predicates, relations = self._extract_natural_language_features(sentence)
                invariants.append(
                    {
                        'id': f'inv:python:{source_digest[:12]}:{function.name}:{function.lineno}:{index}',
                        'description': sentence,
                        'source_function': function.name,
                        'formalization': {
                            'fol': self._to_fol(sentence),
                            'predicates': predicates,
                            'relations': relations,
                        },
                        'evidence_refs': [
                            self._evidence_ref(
                                path=module_path,
                                source_digest=source_digest,
                                line_start=function.lineno,
                                line_end=getattr(function, 'end_lineno', function.lineno),
                                notes=f'Invariant inferred from docstring on function {function.name}.',
                            )
                        ],
                    }
                )
        for class_node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
            class_docstring = ast.get_docstring(class_node) or ''
            for index, sentence in enumerate(self._extract_security_sentences(class_docstring), start=1):
                predicates, relations = self._extract_natural_language_features(sentence)
                invariants.append(
                    {
                        'id': f'inv:python:{source_digest[:12]}:{class_node.name}:{class_node.lineno}:{index}',
                        'description': sentence,
                        'source_class': class_node.name,
                        'formalization': {
                            'fol': self._to_fol(sentence),
                            'predicates': predicates,
                            'relations': relations,
                        },
                        'evidence_refs': [
                            self._evidence_ref(
                                path=module_path,
                                source_digest=source_digest,
                                line_start=class_node.lineno,
                                line_end=getattr(class_node, 'end_lineno', class_node.lineno),
                                notes=f'Invariant inferred from docstring on class {class_node.name}.',
                            )
                        ],
                    }
                )
        return invariants

    def _collect_events(self, tree: ast.AST, source: str, module_path: str = '<memory>') -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        source_digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
        for function in self._iter_functions(tree):
            events.append(
                {
                    'id': f'event:python:{source_digest[:12]}:{function.name}:{function.lineno}',
                    'event': function.name,
                    'kind': 'code_path',
                    'custom': True,
                    'description': f'Autoformalized code-path event for function {function.name}.',
                    'critical': any(pattern.search(function.name.lower()) for pattern in _compile_keyword_patterns(_CRITICAL_ACTION_KEYWORDS)),
                    'evidence_refs': [
                        self._evidence_ref(
                            path=module_path,
                            source_digest=source_digest,
                            line_start=function.lineno,
                            line_end=getattr(function, 'end_lineno', function.lineno),
                            notes=f'Code-path event harvested from function {function.name}.',
                        )
                    ],
                }
            )
        return events

    def _extract_security_sentences(self, docstring: str) -> list[str]:
        sentences: list[str] = []
        for part in _SECURITY_SENTENCE_PATTERN.split(docstring):
            candidate = part.strip()
            if candidate and any(pattern.search(candidate.lower()) for pattern in _SECURITY_PATTERNS):
                sentences.append(candidate)
        return sentences

    def _to_fol(self, sentence: str) -> str:
        try:
            from ipfs_datasets_py.logic.fol.converter import FOLConverter

            return FOLConverter(
                use_cache=False,
                use_ipfs=False,
                use_ml=False,
                use_nlp=False,
                enable_monitoring=False,
            ).to_fol(sentence)
        except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
            logger.warning('Falling back to minimal FOL abstraction for autoformalized sentence: %s', sentence[:100])
            return f'Statement({sentence.replace(" ", "_")})'

    def _extract_natural_language_features(self, sentence: str) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
        try:
            from ipfs_datasets_py.logic.fol.utils.predicate_extractor import (
                extract_logical_relations,
                extract_predicates,
            )

            return extract_predicates(sentence), extract_logical_relations(sentence)
        except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
            logger.warning('Falling back to empty natural-language features for autoformalized sentence: %s', sentence[:100])
            return ({'nouns': [], 'verbs': [], 'adjectives': [], 'relations': []}, [])

    @staticmethod
    def _iter_functions(tree: ast.AST) -> Iterable[ast.FunctionDef | ast.AsyncFunctionDef]:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield node

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
