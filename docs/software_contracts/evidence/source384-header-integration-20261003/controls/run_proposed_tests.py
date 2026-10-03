"""Load only the new off-tree module; do not override or overlay existing owners."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys
import time

B=Path(__file__).resolve().parent
D=B.parents[1]/'.worktrees/ir-release-datasets-20261002'
source=B/'proposed/ipfs_datasets_py/logic/software_contracts/codebase_header_context.py'
test=B/'proposed/tests/integration/logic/software_contracts/test_codebase_header_context.py'
pins=json.loads((B/'draft-pins.json').read_text())
for path in (source,test):
    assert hashlib.sha256(path.read_bytes()).hexdigest()==pins[str(path.relative_to(B))]
name='ipfs_datasets_py.logic.software_contracts.codebase_header_context'
assert name not in sys.modules
spec=importlib.util.spec_from_file_location(name,source)
module=importlib.util.module_from_spec(spec)
sys.modules[name]=module
spec.loader.exec_module(module)
import pytest
args=['-c',str(D/'pytest.ini'),'-q',str(test),'--junitxml='+str(B/'controls-01.xml')]
(B/'controls-01-command.json').write_text(json.dumps(dict(command=[sys.executable,str(Path(__file__))],
    pytest_args=args,pins=pins,existing_owners_overridden=False,symlink_overlay=False,
    public_fixture=os.environ.get('IPFS_DATASETS_PUBLIC_BOTTLE_FIXTURE'),
    qualification_scope='authored isolated scheduler with injected host telemetry; no actual host-pressure claim'),indent=2)+'\n')
started=time.monotonic();code=int(pytest.main(args))
(B/'controls-01-exit.json').write_text(json.dumps(dict(exit_code=code,seconds=time.monotonic()-started,
    source_pins_after={str(p.relative_to(B)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,test)}),indent=2)+'\n')
raise SystemExit(code)
