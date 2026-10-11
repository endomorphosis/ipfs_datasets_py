"""Run boundary tests with namespace bootstrap and numerical/network denial."""
import importlib.abc
import os
from pathlib import Path
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parent / "datasets"
sys.path.insert(0, str(ROOT))
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
os.environ["IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI"] = "0"
os.environ.pop("LEGAL_SOURCE_FAMILY_NATIVE_LAKE", None)


class DenyNumericalImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "transformers", "sentence_transformers", "numpy"}:
            raise AssertionError("numerical import prohibited in inert boundary tests: " + fullname)
        return None


def audit(event, values):
    if event in {"socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
        raise AssertionError("network/process prohibited in inert boundary tests")


sys.meta_path.insert(0, DenyNumericalImports())
sys.addaudithook(audit)
for name in ("ipfs_datasets_py", "ipfs_datasets_py.logic", "ipfs_datasets_py.logic.legal_ir", "ipfs_datasets_py.logic.autoformal",
             "ipfs_datasets_py.logic.CEC", "ipfs_datasets_py.logic.CEC.native",
             "ipfs_datasets_py.logic.formalization", "ipfs_datasets_py.logic.formalization.autoencoder",
             "ipfs_datasets_py.optimizers", "ipfs_datasets_py.optimizers.logic_theorem_optimizer",
             "ipfs_datasets_py.utils"):
    module = ModuleType(name)
    module.__path__ = [str(ROOT.joinpath(*name.split(".")))]
    module.__file__ = str(ROOT.joinpath(*name.split("."), "__init__.py"))
    sys.modules[name] = module

for name in ("tests", "tests.unit", "tests.unit.logic", "tests.unit.logic.autoformal"):
    module = ModuleType(name)
    module.__path__ = [str(ROOT.joinpath(*name.split(".")))]
    sys.modules[name] = module

import pytest

raise SystemExit(pytest.main(sys.argv[1:]))
