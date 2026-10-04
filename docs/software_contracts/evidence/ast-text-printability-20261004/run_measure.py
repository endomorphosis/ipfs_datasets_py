"""Bounded fresh-process controller; exact recipe/exit/source pin retention."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

B = Path(__file__).resolve().parent
D = Path('/home/barberb/lift_coding/.worktrees/ir-pressure-attribution-datasets-20261004')
label, mode = sys.argv[1:]
argv = ['/home/barberb/.local/bin/python', '-B', str(B / 'measure_ast.py'), label, mode]
overrides = {'PYTHONPATH': str(D), 'AST_DIAGNOSTIC_DATASETS_ROOT': str(D), 'PYTHONDONTWRITEBYTECODE': '1',
             'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
command = {'argv': argv, 'cwd': str(D), 'environment_overrides': overrides, 'timeout_seconds': 90,
           'script_sha256': hashlib.sha256((B / 'measure_ast.py').read_bytes()).hexdigest(),
           'controller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(B / (label + '-command.json')).write_text(json.dumps(command, indent=2) + '\n')
start = time.monotonic()
with (B / (label + '-stdout.txt')).open('w') as out, (B / (label + '-stderr.txt')).open('w') as err:
    result = subprocess.run(argv, cwd=D, env={**os.environ, **overrides}, stdout=out, stderr=err, timeout=90)
exit = {'returncode': result.returncode, 'wall_seconds': time.monotonic() - start}
(B / (label + '-exit.json')).write_text(json.dumps(exit, indent=2) + '\n')
print(json.dumps(exit))
raise SystemExit(result.returncode)
