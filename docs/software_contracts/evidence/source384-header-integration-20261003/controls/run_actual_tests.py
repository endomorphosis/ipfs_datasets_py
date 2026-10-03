"""Validate the applied owner directly, without import hooks or overlays."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time

B=Path(__file__).resolve().parent
D=B.parents[1]/'.worktrees/ir-release-datasets-20261002'
from ipfs_datasets_py.logic.software_contracts import codebase_header_context as owner
source=D/'ipfs_datasets_py/logic/software_contracts/codebase_header_context.py'
test=D/'tests/integration/logic/software_contracts/test_codebase_header_context.py'
assert Path(owner.__file__).resolve()==source
pins=json.loads((B/'draft-pins.json').read_text())
for path in (source,test):
    assert hashlib.sha256(path.read_bytes()).hexdigest()==pins['proposed/'+str(path.relative_to(D))]
import pytest
args=['-c',str(D/'pytest.ini'),'-q',str(test),'--junitxml='+str(B/'actual-02.xml')]
(B/'actual-02-command.json').write_text(json.dumps(dict(command=[sys.executable,str(Path(__file__))],
    pytest_args=args,source_pins=pins,actual_loaded_owner=str(Path(owner.__file__).resolve()),
    baseline_git_head=subprocess.check_output(['git','-C',str(D),'rev-parse','HEAD'],text=True).strip(),
    import_hooks_or_overlay=False,public_fixture=os.environ.get('IPFS_DATASETS_PUBLIC_BOTTLE_FIXTURE'),
    environment={k:os.environ.get(k) for k in ('PYTHONPATH','PYTHONDONTWRITEBYTECODE','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')},
    qualification_scope='authored isolated scheduler with injected host telemetry; no actual host-pressure claim'),indent=2)+'\n')
started=time.monotonic();code=int(pytest.main(args))
(B/'actual-02-exit.json').write_text(json.dumps(dict(exit_code=code,seconds=time.monotonic()-started,
    source_pins_after={str(p.relative_to(D)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,test)}),indent=2)+'\n')
raise SystemExit(code)
