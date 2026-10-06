#!/usr/bin/env python3
"""Verify the import-only source-value delta with stdlib source inspection."""
import ast
from copy import deepcopy
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path

OUT = Path('/home/barberb/lift_coding/artifacts/contextual-legal-runtime-20261006/source-survey')


def pin(path):
    path = Path(path)
    data = path.read_bytes()
    return dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def is_training_import(node):
    return isinstance(node, ast.ImportFrom) and node.level == 1 \
        and node.module == 'long_span_decoder_training' \
        and len(node.names) == 1 and node.names[0].name == 'reference_weights' \
        and node.names[0].asname is None


def main():
    baseline = json.loads((OUT / 'source-survey.json').read_text())
    changed = next(row for row in baseline['minimal_numeric_owners']
                   if row['module'].endswith('.source_value_decoder_experiment'))
    historical_path, current_path = Path(changed['historical_pin']['path']), Path(changed['current_pin']['path'])
    before = [pin(historical_path), pin(current_path)]
    old_source, new_source = historical_path.read_text(), current_path.read_text()
    old_tree, new_tree = ast.parse(old_source), ast.parse(new_source)
    old_top_imports = [node for node in old_tree.body if is_training_import(node)]
    new_top_imports = [node for node in new_tree.body if is_training_import(node)]
    assert len(old_top_imports) == 1 and not new_top_imports
    function = next(node for node in new_tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'reference_source_values')
    relocated = [node for node in function.body if is_training_import(node)]
    assert len(relocated) == 1 and isinstance(function.body[0], ast.Expr) \
        and is_training_import(function.body[1])
    old_normalized, new_normalized = deepcopy(old_tree), deepcopy(new_tree)
    old_normalized.body = [node for node in old_normalized.body if not is_training_import(node)]
    new_function = next(node for node in new_normalized.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'reference_source_values')
    new_function.body = [node for node in new_function.body if not is_training_import(node)]
    unchanged_ast = ast.dump(old_normalized, include_attributes=False) == ast.dump(new_normalized, include_attributes=False)
    assert unchanged_ast
    owners = []
    for row in baseline['minimal_numeric_owners']:
        current = pin(row['current_pin']['path'])
        historical = pin(row['historical_pin']['path'])
        assert historical == {key: row['historical_pin'][key] for key in ('path', 'bytes', 'sha256')}
        owners.append(dict(module=row['module'], current_pin=current, historical_pin=historical,
            exact_historical_bytes=current['sha256'] == historical['sha256']))
    assert sum(row['exact_historical_bytes'] for row in owners) == 10
    allowed = {row['module'].rsplit('.', 1)[-1] for row in owners}
    out_of_closure = []
    for row in owners:
        tree = ast.parse(Path(row['current_pin']['path']).read_text())
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level:
                names = [node.module] if node.module else [alias.name for alias in node.names]
                if node.level != 1 or any(name not in allowed for name in names):
                    out_of_closure.append(dict(module=row['module'], level=node.level,
                                               imported_module=node.module, names=names))
    assert not out_of_closure
    after = [pin(historical_path), pin(current_path)]
    report = dict(schema='contextual-numeric-lazy-training-import-review/v1',
        observed_at_utc=datetime.now(timezone.utc).isoformat(),
        source_only_review=True, project_or_torch_imported=False,
        tests_models_training_or_encoder_executed=False, source_edits=False,
        original_historical_survey_pin=pin(OUT / 'source-survey.json'),
        original_historical_survey_overwritten=False, script_pin=pin(__file__),
        reviewed_file_pins_before=before, reviewed_file_pins_after=after,
        reviewed_files_unchanged=before == after,
        original_historical_files_preserved=True, numerical_owner_count=11,
        exact_historical_owner_count=10, reviewed_import_only_delta_count=1,
        owners=owners, changed_owner_module=changed['module'],
        top_level_reference_weights_import_removed=True,
        lazy_import_only_in_training_reference_source_values=True,
        normalized_AST_exact_after_removing_relocated_import=unchanged_ast,
        constructor_tensor_forward_greedy_normalization_code_unchanged=True,
        current11_top_level_relative_imports_closed_to_numeric_owner_set=True,
        out_of_closure_top_level_project_imports=out_of_closure,
        unified_source_delta=''.join(difflib.unified_diff(old_source.splitlines(True), new_source.splitlines(True),
            fromfile=str(historical_path), tofile=str(current_path))),
        scope='Ten source owners remain exact archived bytes. Source-value owner has one reviewed import-only delta: its existing training reference helper imports reference_weights when that training helper is called. Numerical generation never calls it. Original external historical files are preserved. Dynamic no-training-import replay remains root-owned.',
        dynamic_no_training_import_replay_rerun_by_this_review=False,
        previous_static_review_limitation='Earlier byte/entrypoint reviews did not exercise an import bomb over transitive runtime imports; root first real replay exposed this lazy-import requirement before successful inference.',
        no_remaining_source_delta_findings=True)
    path = OUT / 'lazy-training-import-review.json'
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    note_path = OUT / 'numeric-post-freeze-review.json'
    note = json.loads(note_path.read_text())
    note['previous_note_pin_before_lazy_import_review'] = pin(note_path)
    note['minimal_original_owners'] = owners
    note['all11_original_owners_exact_historical_bytes'] = False
    note['exact_original_owner_count'] = 10
    note['reviewed_import_only_delta_count'] = 1
    note['lazy_training_import_review_pin'] = pin(path)
    note['current11_top_level_relative_project_imports_closed_to_numeric_owner_set'] = True
    note['previous_static_review_limitation'] = report['previous_static_review_limitation']
    note['no_remaining_findings'] = True
    note_path.write_text(json.dumps(note, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(delta_review_pin=pin(path), updated_numeric_review_pin=pin(note_path),
        exact_owner_count=10, reviewed_import_only_delta_count=1, historical_files_preserved=True), sort_keys=True))


if __name__ == '__main__':
    main()
