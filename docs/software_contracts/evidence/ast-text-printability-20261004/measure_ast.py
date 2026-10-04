"""Public Bottle AST reconstruction component diagnostic, no task/model workload."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

B = Path(__file__).resolve().parent
D = Path(os.environ['AST_DIAGNOSTIC_DATASETS_ROOT'])
label, mode = sys.argv[1:]
assert mode in {'original', 'current'}
owner_name = 'ipfs_datasets_py.logic.software_contracts.ast_ir'
class OriginalFinder:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == owner_name:
            return importlib.util.spec_from_file_location(fullname, B / 'ast_ir-before.py')
if mode == 'original':
    sys.meta_path.insert(0, OriginalFinder())
import duckdb
from ipfs_datasets_py.logic.software_contracts import ast_ir
from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor

paths = [
    'ipfs_datasets_py/logic/software_contracts/ast_ir.py',
    'ipfs_datasets_py/logic/software_contracts/python_frontend.py',
    'ipfs_datasets_py/logic/software_contracts/duckdb_ast_store.py',
    'ipfs_datasets_py/logic/software_contracts/content.py',
    'ipfs_datasets_py/logic/software_contracts/schema_versions.py',
    'ipfs_datasets_py/logic/software_contracts/codebase_ir.py',
    'ipfs_datasets_py/logic/software_contracts/semantic_index/models.py',
]
def pins():
    return {name: hashlib.sha256((Path(ast_ir.__file__) if name.endswith('/ast_ir.py') else D / name).read_bytes()).hexdigest()
            for name in paths}
def measured(function):
    cpu, wall = time.process_time(), time.monotonic()
    value = function()
    return value, {'cpu_seconds': time.process_time() - cpu, 'wall_seconds': time.monotonic() - wall}

private = B / 'private' / label
private.mkdir(parents=True, exist_ok=False)
report = {'schema': 'public-bottle-ast-reconstruction-diagnostic@1', 'mode': mode,
          'scope': 'one public source; actual immutable AST and isolated reopened DuckDB; no model, Docker or verifier',
          'effective_owner': ast_ir.__file__, 'source_pins_before': pins(),
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
try:
    raw = (B / 'bottle.py').read_bytes()
    report['source_sha256'] = hashlib.sha256(raw).hexdigest()
    assert report['source_sha256'] == '761756ce31753e526c48d28ccbca13a5d2493b16fe37aff3e1e4d2efaf3a2bba'
    record, report['extract'] = measured(lambda: PythonASTExtractor().extract(raw, path='bottle.py',
        repository_id='repository:public-bottle-ast', revision='public-fixture'))
    body = record.to_dict()
    encoded = canonical_dag_json_bytes(body)
    report.update(payload_bytes=len(encoded), payload_sha256=hashlib.sha256(encoded).hexdigest(),
                  ast_cid=cid_for_structured(body), symbols=len(record.symbols), references=len(record.references),
                  calls=len(record.calls), scopes=len(record.scopes))
    reconstructed, report['from_dict'] = measured(lambda: ast_ir.ASTRecord.from_dict(body))
    assert canonical_dag_json_bytes(reconstructed.to_dict()) == encoded
    db = private / 'ast.duckdb'
    connection = duckdb.connect(str(db), config={'threads': 1, 'memory_limit': '256MB'})
    store = DuckDBASTStore(connection=connection)
    projection, report['persist'] = measured(lambda: store.put(record, created_at=0.0))
    assert projection.ast_cid == report['ast_cid']
    connection.close()
    del store, record, reconstructed, projection, body
    connection = duckdb.connect(str(db), config={'threads': 1, 'memory_limit': '256MB'})
    store = DuckDBASTStore(connection=connection)
    observed, report['reopened_store_read'] = measured(lambda: store.get_by_ast_cid(report['ast_cid']))
    assert observed is not None and observed.ast_blob.payload_json.encode() == encoded
    report['reopened_ast_cid'] = observed.ast_cid
    connection.close()
    report['status'] = 'passed'
except BaseException as error:
    report.update(status='failed', error_type=type(error).__name__)
    raise
finally:
    report['source_pins_after'] = pins()
    report['source_pins_unchanged'] = report['source_pins_before'] == report['source_pins_after']
    (B / (label + '-result.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
