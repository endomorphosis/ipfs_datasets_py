"""Hermetic import and CLI-help regression coverage for semantic indexing."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[5]
CLI_MODULE = ROOT / "ipfs_datasets_py" / "cli" / "semantic_index_cli.py"
_OPT_OUTS = {
    "IPFS_DATASETS_AUTO_INSTALL": "0",
    "IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS": "0",
    "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
    "IPFS_KIT_AUTO_INSTALL_DEPS": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def _probe(*, cli_help: bool) -> subprocess.CompletedProcess[str]:
    """Import in a fresh process that turns prohibited effects into failures."""
    action = (
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('_semantic_index_cli_probe', sys.argv[1])\n"
        "assert spec is not None and spec.loader is not None\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "try:\n"
        "    module.main(['--help'])\n"
        "except SystemExit as exc:\n"
        "    assert exc.code == 0\n"
        if cli_help
        else "import ipfs_datasets_py.logic.software_contracts.semantic_index\n"
    )
    script = f'''\
import json
import os
import subprocess
import sys

before = dict(os.environ)
effects = []

def forbidden(name):
    def call(*args, **kwargs):
        effects.append(name)
        raise AssertionError(f"forbidden import side effect: {{name}}")
    return call

os.system = forbidden("os.system")
for name in ("posix_spawn", "posix_spawnp", "spawnv", "spawnve", "spawnvp", "spawnvpe"):
    if hasattr(os, name):
        setattr(os, name, forbidden("os." + name))

def audit(event, args):
    if event == "open" and len(args) > 2:
        flags = args[2]
        if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            effects.append("write:" + str(args[0]))
            raise AssertionError("forbidden import write")
    if event in {{"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.replace", "socket.connect", "subprocess.Popen"}}:
        effects.append(event)
        raise AssertionError(f"forbidden import side effect: {{event}}")

sys.addaudithook(audit)
{action}
assert os.environ == before, "import changed environment variables"
assert not effects, effects
print(json.dumps({{"ok": True}}, sort_keys=True))
'''
    environment = dict(os.environ)
    environment.update(_OPT_OUTS)
    return subprocess.run(
        [sys.executable, "-c", script, str(CLI_MODULE)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_hermetic(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {"ok": True}


def test_semantic_index_import_is_hermetic_under_opt_outs() -> None:
    _assert_hermetic(_probe(cli_help=False))


def test_semantic_index_cli_help_is_hermetic_under_opt_outs() -> None:
    _assert_hermetic(_probe(cli_help=True))
