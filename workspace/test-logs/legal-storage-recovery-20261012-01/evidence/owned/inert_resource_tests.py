"""Run local recovery fixtures without models, network or host-state writes."""
import importlib.abc
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType

F = Path(__file__).resolve().parent
D = F / "datasets"
TEST_TEMP = F / "runtime-temp"
TEST_TEMP.mkdir(exist_ok=True)
tempfile.tempdir = str(TEST_TEMP)
sys.dont_write_bytecode = True
sys.path.insert(0, str(D))
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"


class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "numpy", "transformers", "sentence_transformers"}:
            raise AssertionError("Numerical import forbidden in resource fixtures: " + fullname)
        return None


def audit(event, args):
    if event == "os.kill" and args == (os.getpid(), 0):
        return  # Existing local fixture scheduler observes its own owner.
    if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn")) or event in {"os.system", "os.fork", "os.posix_spawn", "os.kill", "os.killpg"}:
        raise AssertionError("Network/process/signals forbidden in resource fixtures")
    if event != "open":
        return
    path, mode, flags = args
    write = isinstance(mode, str) and any(c in mode for c in "wax+")
    write |= isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
    if not write:
        return
    if type(path) is int:
        path = os.readlink("/proc/self/fd/" + str(path))
    if not isinstance(path, (str, bytes, os.PathLike)):
        raise AssertionError("Unidentified writable fixture path")
    target = Path(os.fsdecode(path)).resolve()
    if not target.is_relative_to(F):
        raise AssertionError("Write outside owned resource fixtures: " + str(target))


sys.meta_path.insert(0, DenyModels())
sys.addaudithook(audit)
for name in ("ipfs_datasets_py", "ipfs_datasets_py.optimizers", "ipfs_datasets_py.optimizers.logic_theorem_optimizer",
             "tests", "tests.unit", "tests.unit.optimizers", "tests.unit.optimizers.logic_theorem_optimizer"):
    module = ModuleType(name)
    module.__path__ = [str(D.joinpath(*name.split(".")))]
    sys.modules[name] = module

import pytest

raise SystemExit(pytest.main(sys.argv[1:]))
