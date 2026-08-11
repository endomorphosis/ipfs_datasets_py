from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.backends.installers.runtime_mtl import (
    MANAGED_EXECUTABLE_NAME,
    ExternalMonitorIdentity,
    RuntimeMTLInstallerError,
    _managed_vendor_launcher_is_current,
    _publish_managed_vendor_launcher,
    _python_reference_dispatch_marker,
    managed_executable_path,
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


def _vendor_identity(tmp_path: Path, content: bytes) -> ExternalMonitorIdentity:
    executable = (
        tmp_path
        / "runtime-mtl-vendor"
        / "runtime-mtl-external"
        / "1.0.0-reviewed"
        / "bin"
        / "runtime-mtl-external"
    )
    executable.parent.mkdir(parents=True)
    executable.write_bytes(content)
    executable.chmod(0o755)
    digest = hashlib.sha256(content).hexdigest()
    return ExternalMonitorIdentity(
        tool_id="runtime-mtl-external",
        version="1.0.0-reviewed",
        executable=str(executable),
        license="Apache-2.0",
        source="ipfs_datasets_py/typescript/logic-runtime-mtl",
        identity_kind="typescript_package",
        is_hermetic_parity_engine=False,
        is_vendor_build=True,
        artifact_sha256="a" * 64,
        executable_digest_sha256=digest,
        install_root=str(tmp_path),
    )


def test_vendor_launcher_is_atomically_published_on_managed_path(
    tmp_path: Path,
) -> None:
    content = b"#!/usr/bin/env bash\nprintf 'runtime-mtl 1.0.0-reviewed\\n'\n"
    identity = _vendor_identity(tmp_path, content)

    launcher = _publish_managed_vendor_launcher(identity)

    assert launcher == tmp_path / "bin" / MANAGED_EXECUTABLE_NAME
    assert launcher == managed_executable_path(tmp_path)
    assert launcher.read_bytes() == content
    assert launcher.stat().st_mode & 0o111
    assert _managed_vendor_launcher_is_current(identity) is True


def test_vendor_launcher_digest_mismatch_preserves_existing_publication(
    tmp_path: Path,
) -> None:
    prior = tmp_path / "bin" / MANAGED_EXECUTABLE_NAME
    prior.parent.mkdir(parents=True)
    prior.write_bytes(b"previous-reviewed-launcher")
    prior.chmod(0o755)
    identity = _vendor_identity(tmp_path, b"tampered")
    object.__setattr__(identity, "executable_digest_sha256", "b" * 64)

    with pytest.raises(RuntimeMTLInstallerError, match="digest mismatch"):
        _publish_managed_vendor_launcher(identity)

    assert prior.read_bytes() == b"previous-reviewed-launcher"


def test_hermetic_parity_engine_cannot_be_path_visible(tmp_path: Path) -> None:
    executable = tmp_path / "runtime-mtl-external"
    executable.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    executable.chmod(0o755)
    identity = ExternalMonitorIdentity(
        tool_id="runtime-mtl-external",
        version="1.0.0-reviewed",
        executable=str(executable),
        license="Apache-2.0",
        source="ipfs_datasets_py/typescript/logic-runtime-mtl",
        identity_kind="typescript_package",
        is_hermetic_parity_engine=True,
        is_vendor_build=False,
        artifact_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        executable_digest_sha256=hashlib.sha256(
            executable.read_bytes()
        ).hexdigest(),
        install_root=str(tmp_path),
    )

    with pytest.raises(RuntimeMTLInstallerError, match="only an independent vendor"):
        _publish_managed_vendor_launcher(identity)

    assert not managed_executable_path(tmp_path).exists()
