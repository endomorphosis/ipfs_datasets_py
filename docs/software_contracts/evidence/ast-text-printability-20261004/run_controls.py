"""Retain bounded focused validation receipts and exact source/test pins."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time

B = Path(__file__).resolve().parent
D = Path('/home/barberb/lift_coding/.worktrees/ir-pressure-attribution-datasets-20261004')
tests = ['tests/unit/logic/software_contracts/' + name for name in [
    'test_ast_text_validation.py', 'test_ast_ir.py', 'test_python_frontend.py',
    'test_duckdb_ast_store.py', 'test_duckdb_ast_store_persistence.py']]
sources = ['ipfs_datasets_py/logic/software_contracts/' + name for name in [
    'ast_ir.py', 'python_frontend.py', 'duckdb_ast_store.py', 'content.py',
    'schema_versions.py', 'codebase_ir.py', 'semantic_index/models.py']]
def pins():
    return {name: hashlib.sha256((D / name).read_bytes()).hexdigest() for name in sources + tests}

label = 'focused-01'
argv = ['/home/barberb/.local/bin/python', '-B', '-m', 'pytest', '-q', *tests,
        '--junitxml=' + str(B / (label + '.xml'))]
overrides = {'PYTHONPATH': str(D), 'PYTHONDONTWRITEBYTECODE': '1',
             'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
initial = pins()
(B / (label + '-command.json')).write_text(json.dumps({'argv': argv, 'cwd': str(D),
    'environment_overrides': overrides, 'source_sha256': initial, 'timeout_seconds': 180,
    'controller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, indent=2) + '\n')
start = time.monotonic()
with (B / (label + '-stdout.txt')).open('w') as out, (B / (label + '-stderr.txt')).open('w') as err:
    result = subprocess.run(argv, cwd=D, env={**os.environ, **overrides}, stdout=out, stderr=err, timeout=180)
final = pins()
receipt = {'returncode': result.returncode, 'wall_seconds': time.monotonic() - start,
           'source_pins_after': final, 'source_pins_unchanged': initial == final}
(B / (label + '-exit.json')).write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
raise SystemExit(result.returncode)
