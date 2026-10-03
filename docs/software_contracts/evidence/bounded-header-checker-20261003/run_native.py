from pathlib import Path
import importlib, importlib.util, sys
B=Path(__file__).resolve().parent
D=Path("/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002")
sys.path.insert(0,str(D))
name="ipfs_datasets_py.logic.security_ir.bounded_header_checker"
package=importlib.import_module(name.rpartition(".")[0])
spec=importlib.util.spec_from_file_location(name,B/"proposed/ipfs_datasets_py/logic/security_ir/bounded_header_checker.py")
module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
setattr(package,"bounded_header_checker",module)
import pytest
raise SystemExit(pytest.main([str(B/"proposed/tests/unit/logic/security_ir/test_bounded_header_checker_native.py"),"-q","--junitxml="+str(B/"native-03.xml")]))
