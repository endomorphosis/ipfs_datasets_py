#!/usr/bin/env python3
"""Bind unchanged reconstruction math to final source without executing models."""
from pathlib import Path
import argparse
import ast
import hashlib
import json

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[3]
RELATIVE = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py'
FUNCTIONS = (
    '_decoded_for', '_reconstruction_safe_projection', '_initial_embedding_projection',
    '_family_distribution_for_embedding', '_base_logits_for', '_logits_for',
    '_nudge_family_logits', '_nudge_decoded_embedding', '_embedding_training_error',
    '_head_update_scale', '_evaluation_objective_for_training', '_evaluation_regressions_for_training',
    '_select_codec_feature_keys', '_token_features',
)


def ref(path, data=None):
    data = path.read_bytes() if data is None else data
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def extract(data):
    tree = ast.parse(data)
    text_lines = data.decode().splitlines(keepends=True)
    entries = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCTIONS:
            if node.name in entries:
                raise ValueError('Ambiguous duplicate function ' + node.name)
            snippet = ''.join(text_lines[node.lineno - 1:node.end_lineno]).encode()
            normalized = ast.dump(node, annotate_fields=True, include_attributes=False).encode()
            entries[node.name] = {'line': node.lineno, 'end_line': node.end_lineno,
                'source_snippet_sha256': hashlib.sha256(snippet).hexdigest(),
                'normalized_ast_sha256': hashlib.sha256(normalized).hexdigest()}
    if set(entries) != set(FUNCTIONS):
        raise ValueError('Missing audited function')
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BASE / 'reconstruction-source-parity.json')
    args = parser.parse_args()
    before_path, final_path = BASE / 'before' / RELATIVE, ROOT / RELATIVE
    before_raw, final_raw = before_path.read_bytes(), final_path.read_bytes()
    before, final = extract(before_raw), extract(final_raw)
    parity = {name: {'before': before[name], 'final': final[name],
                    'normalized_ast_equal': before[name]['normalized_ast_sha256'] == final[name]['normalized_ast_sha256'],
                    'source_snippet_bytes_equal': before[name]['source_snippet_sha256'] == final[name]['source_snippet_sha256']}
              for name in FUNCTIONS}
    original_audit = BASE / 'reconstruction-audit.json'
    historical = json.loads(original_audit.read_bytes())
    report = {'schema': 'reconstruction-source-parity/v1',
        'passed': all(row['normalized_ast_equal'] for row in parity.values()),
        'historical_reconstruction_audit': ref(original_audit),
        'historical_audit_source_sha256': historical['source_read']['sha256'],
        'historical_whole_source_binding_is_not_relabelled': True,
        'before_source': ref(before_path, before_raw), 'final_source': ref(final_path, final_raw),
        'functions': parity, 'model_executed': False, 'new_canaries_observed': False,
        'scope': 'Only listed reconstruction/evaluation functions have unchanged AST semantics. Training search intentionally changes elsewhere; this is not a full-package provenance waiver. Native execution still requires complete before/after package equality.',
        'admitted': False}
    if final_path.read_bytes() != final_raw:
        raise ValueError('Source changed during parity capture')
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'passed': report['passed'], 'function_count': len(parity),
                      'final_source_sha256': report['final_source']['sha256']}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
