"""Fresh isolated interpreter; real filesystem dependency availability only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import resource
import sys
import time

assert sys.flags.isolated and sys.flags.no_site
sys.dont_write_bytecode = True
root, fixture, expected, mode = sys.argv[1:]
sys.path.insert(0, root)
assert all('site-packages' not in value and 'dist-packages' not in value for value in sys.path)
finder_types = [type(value).__name__ if not isinstance(value, type) else value.__name__ for value in sys.meta_path]
assert finder_types == ['BuiltinImporter', 'FrozenImporter', 'PathFinder']
available = importlib.util.find_spec('pandas') is not None
assert available == (mode == 'available')
body = Path(fixture).read_bytes()
assert hashlib.sha256(body).hexdigest() == expected
rows = json.loads(body)
assert len(rows) * len(rows[0]) <= 100000

import duckdb
import _duckdb
import numpy

def usage():
    value = resource.getrusage(resource.RUSAGE_SELF)
    return {name: getattr(value, name) for name in ('ru_utime', 'ru_stime', 'ru_maxrss', 'ru_inblock', 'ru_oublock')}

def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

cx = duckdb.connect(config={'threads': 1, 'memory_limit': '512MB'})
start = time.monotonic()
assert cx.execute('SELECT ?', [1]).fetchall() == [(1,)]
warmup_seconds = time.monotonic() - start
assert ('pandas' in sys.modules) == available
settings = cx.execute("SELECT current_setting('threads'),current_setting('memory_limit')").fetchone()
sql = 'SELECT ' + ','.join(['unnest(?)'] * len(rows[0]))
samples, output = [], []
before = usage()
for offset in range(0, len(rows), 128):
    chunk = rows[offset:offset + 128]
    columns = [list(column) for column in zip(*chunk)]
    start, cpu = time.monotonic(), time.process_time()
    cursor = cx.execute(sql, columns)
    samples.append({'seconds': time.monotonic() - start, 'cpu_seconds': time.process_time() - cpu})
    output.extend([list(row) for row in cursor.fetchall()])
assert output == rows
final_finders = [type(value).__name__ if not isinstance(value, type) else value.__name__ for value in sys.meta_path]
result = dict(schema='isolated-optional-dependency-timing@1', diagnostic_only=True,
    mode=mode, genuine_filesystem_absence=not available, finder_hooks_used=False,
    python=sys.version, executable=str(Path(sys.executable).resolve()), sys_path=sys.path,
    finder_types=finder_types, final_finder_types=final_finders, input_sha256=expected, rows=len(rows), width=len(rows[0]),
    scalar_values=len(rows)*len(rows[0]), statements=len(samples), chunk_rows=128,
    duckdb_version=duckdb.__version__, duckdb_extension_sha256=file_sha(_duckdb.__file__),
    numpy_version=numpy.__version__, pandas_version=sys.modules['pandas'].__version__ if available else None,
    settings={'threads':settings[0], 'memory_limit':settings[1]}, exact_row_parity=True,
    warmup_seconds=warmup_seconds, execute_seconds=sum(r['seconds'] for r in samples),
    execute_cpu_seconds=sum(r['cpu_seconds'] for r in samples), samples=samples,
    before=before, after=usage(), production_changed=False, docker_claim=False)
print(json.dumps(result,sort_keys=True))
