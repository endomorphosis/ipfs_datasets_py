"""A fresh process must import SymbolicAI without incidental pool imports."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("dependency_fails", [False, True])
def test_managed_symai_import_initializes_pool_and_restores_prefix(tmp_path, dependency_fails):
    package = tmp_path / "dependency/symai"
    package.mkdir(parents=True)
    package.joinpath("__init__.py").write_text(
        "import multiprocessing as mp\n"
        "import sys\n"
        "POOL_TYPES: dict[int, mp.pool.Pool] = {}\n"
        "observed_prefix = sys.prefix\n"
        + ("raise RuntimeError('controlled dependency failure')\n" if dependency_fails else "")
    )
    root = Path(__file__).resolve().parents[3]
    prefix = tmp_path / "managed"
    program = """
import json,sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
assert 'multiprocessing.pool' not in sys.modules
from ipfs_datasets_py.utils.symai_config import ensure_symai_config_for_import
original = sys.prefix
path = ensure_symai_config_for_import()
assert path == Path(sys.argv[3]) / '.symai/symai.config.json'
assert sys.prefix == original
assert 'multiprocessing.pool' in sys.modules
loaded = sys.modules.get('symai')
if sys.argv[4] == 'false':
    assert loaded is not None
    assert loaded.observed_prefix == sys.argv[3]
else:
    assert loaded is None
config = json.loads(path.read_text())
assert config['NEUROSYMBOLIC_ENGINE_MODEL'] == 'codex:fixture'
assert config['NEUROSYMBOLIC_ENGINE_API_KEY'] == 'codex'
assert config['SYMBOLIC_ENGINE'] == 'ipfs'
print(json.dumps({'loaded': loaded is not None, 'prefix_restored': True}))
"""
    environment = os.environ.copy()
    environment.update({"IPFS_DATASETS_PY_SYMAI_PREFIX": str(prefix),
                        "NEUROSYMBOLIC_ENGINE_MODEL": "codex:fixture",
                        "NEUROSYMBOLIC_ENGINE_API_KEY": "codex",
                        "PYTHONDONTWRITEBYTECODE": "1"})
    result = subprocess.run([sys.executable, "-B", "-c", program, str(root), str(package.parent),
                             str(prefix), str(dependency_fails).lower()], env=environment,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"loaded": not dependency_fails, "prefix_restored": True}
