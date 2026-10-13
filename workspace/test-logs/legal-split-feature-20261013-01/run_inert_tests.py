"""Run boundary tests with namespace bootstrap and numerical/network denial."""
import importlib.abc
import ast
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


def _script_constants(path, function, variable):
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
    return [n.value.value for n in node.body if isinstance(n, (ast.Assign, ast.AugAssign))
            and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
            and ((isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == variable for t in n.targets))
                 or (isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) and n.target.id == variable))]


def _allowed_inert_process(values):
    executable, argv, cwd, environment = values
    if executable != sys.executable or type(argv) is not list or argv[:2] != [sys.executable, "-c"]:
        return False
    if environment is not None or (cwd is not None and Path(cwd).resolve() != ROOT):
        return False
    if len(argv) == 4:
        path = ROOT / "tests/unit/logic/legal_ir/test_joint_span_selection.py"
        programs = _script_constants(path, "test_module_import_and_selection_do_not_import_tensor_libraries", "program")
        return argv[2] == programs[0] and argv[3] == str(ROOT / "ipfs_datasets_py/logic/legal_ir/joint_span_selection.py")
    if len(argv) != 3 or len(argv[2].encode()) > 65536:
        return False
    path = ROOT / "tests/unit/logic/legal_ir/test_saved_span_family_adapter.py"
    prefix, suffix = _script_constants(path, "test_import_and_pure_transport_have_no_numerical_imports", "script")
    program = argv[2]
    if not program.startswith(prefix) or not program.endswith(suffix):
        return False
    try:
        middle = ast.parse(program[len(prefix):-len(suffix)])
    except SyntaxError:
        return False
    if len(middle.body) != 2:
        return False
    for node, name in zip(middle.body, ("source", "report")):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name
                and isinstance(node.value, ast.Call) and not node.value.keywords and len(node.value.args) == 1
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "loads"
                and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == "json"
                and isinstance(node.value.args[0], ast.Constant) and isinstance(node.value.args[0].value, str)):
            return False
    return True


def audit(event, values):
    if event == "subprocess.Popen" and _allowed_inert_process(values):
        return
    if event in {"socket.connect", "socket.getaddrinfo", "subprocess.Popen", "os.system"}:
        raise AssertionError("network/process prohibited except two exact inert import controls")


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
