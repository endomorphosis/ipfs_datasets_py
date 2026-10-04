"""The reusable model stack must run without its supervisor consumer installed."""
import ast
from pathlib import Path
import subprocess
import sys

from ipfs_datasets_py.logic.formalization import autoencoder


def test_reusable_modules_do_not_import_the_accelerate_consumer():
    root = Path(autoencoder.__file__).parent
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                       else [item.name for item in node.names] if isinstance(node, ast.Import) else [])
            assert not any(name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py.")
                           for name in modules), str(path)


def test_standalone_training_export_and_frozen_inference_without_accelerate():
    script = '''
import importlib.abc, sys
attempts = []
class ConsumerBlock(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == "ipfs_accelerate_py" or fullname.startswith("ipfs_accelerate_py."):
            attempts.append(fullname)
            raise ModuleNotFoundError("consumer unavailable: " + fullname)
sys.meta_path.insert(0, ConsumerBlock())
import pytest
result = pytest.main(["-o", "addopts=", "--noconftest", "-q", "-o", "log_cli=false",
    "tests/unit/logic/formalization/autoencoder/test_security_autoencoder_checkpoint.py::test_source_projection_and_output_match_original_trainer_numerically",
    "tests/unit/logic/formalization/autoencoder/test_security_autoencoder_hub.py::test_download_uses_native_pinned_verification_and_warm_offline_reuse"])
assert result == 0, result
assert not attempts, attempts
assert not any(name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py.") for name in sys.modules)
'''
    repository = Path(__file__).resolve().parents[5]
    result = subprocess.run([sys.executable, "-c", script], cwd=repository,
                            text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
