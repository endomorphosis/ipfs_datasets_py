from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.installers.runtime_mtl import (
    _python_reference_dispatch_marker,
)


def test_independence_audit_allows_dataset_named_install_paths() -> None:
    wrapper = """#!/usr/bin/env bash
NODE='/usr/bin/node'
CLI='/tmp/ipfs_datasets_py/theorem-provers/runtime-mtl/dist/cli.js'
exec "$NODE" "$CLI" "$@"
"""

    assert _python_reference_dispatch_marker(wrapper, "console.log('ok')") is None


@pytest.mark.parametrize(
    "artifact",
    [
        "#!/usr/bin/env python3\nprint('delegated')\n",
        "from ipfs_datasets_py.logic.software_verification import monitoring\n",
        "import ipfs_datasets_py.logic.software_verification\n",
        "sys.path.insert(0, '/tmp/reference')\n",
        "PYTHONPATH=/tmp/reference python3 worker.py\n",
        "python3 -c 'import reference'\n",
        "spawn('/usr/bin/python3', ['worker.py'])\n",
    ],
)
def test_independence_audit_rejects_python_reference_dispatch(artifact: str) -> None:
    assert _python_reference_dispatch_marker(artifact) is not None
