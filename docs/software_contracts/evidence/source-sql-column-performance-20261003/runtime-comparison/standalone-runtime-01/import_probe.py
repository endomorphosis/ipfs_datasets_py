import hashlib
import importlib
import json
from pathlib import Path
import platform
import sys
import sysconfig

modules = {}
for name in ('duckdb', '_duckdb', 'numpy', 'pandas', 'pyarrow', 'dateutil', 'pytz',
             'multiformats', 'ipfs_datasets_py.logic.software_contracts.duckdb_ast_store'):
    module = importlib.import_module(name)
    modules[name] = dict(path=module.__file__, version=getattr(module, '__version__', None),
        sha256=hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())
assert modules['_duckdb']['sha256'] == '60ba180312ca4d6fcf14ebded76efcc1775485e69dcf89ec8f45653a5892a5ef'
binary = Path(sys.executable).resolve()
print(json.dumps(dict(schema='standalone-replay-imports@1', python=sys.version,
    executable=str(binary), executable_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
    platform=platform.platform(), machine=platform.machine(), modules=modules, pythonpath=sys.path,
    config={k: sysconfig.get_config_var(k) for k in ('CONFIG_ARGS', 'Py_DEBUG', 'Py_GIL_DISABLED',
        'WITH_PYMALLOC', 'MALLOC_LIBS', 'SOABI')}), indent=2))
