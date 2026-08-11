from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.ops import ipfs_datasets_duckdb_quack_validator as validator


BASE_PYTHON = Path("/usr/bin/python3.12")


def _record_digest(raw: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()


def _build_wheel(
    path: Path,
    *,
    package: str,
    version: str,
    tag: str,
    files: dict[str, bytes],
    corrupt_record: bool = False,
) -> str:
    dist_info = f"{package.replace('-', '_')}-{version}.dist-info"
    members = {
        **files,
        f"{dist_info}/METADATA": (
            f"Metadata-Version: 2.1\nName: {package}\nVersion: {version}\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: dqk-test\n"
            f"Root-Is-Purelib: {'false' if package == 'duckdb' else 'true'}\n"
            f"Tag: {tag}\n"
        ).encode(),
    }
    record_name = f"{dist_info}/RECORD"
    rows = [
        [
            name,
            "sha256=" + ("A" * 43 if corrupt_record and index == 0 else _record_digest(raw)),
            str(len(raw)),
        ]
        for index, (name, raw) in enumerate(sorted(members.items()))
    ]
    rows.append([record_name, "", ""])
    stream = io.StringIO()
    csv.writer(stream, lineterminator="\n").writerows(rows)
    members[record_name] = stream.getvalue().encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(members.items()):
            archive.writestr(name, raw)
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_artifacts(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    validator_root = tmp_path / "validator"
    runtime_root = tmp_path / "runtime"
    hashes: dict[str, str] = {}
    fake_pytest = b"""\
__version__ = '9.0.3'
def main(args, plugins=None):
    import runpy
    assert len(plugins) == 1
    plugins[0].pytest_collection_finish(None)
    for value in args:
        if value.endswith('.py'):
            runpy.run_path(value, run_name='__dqk_validation_test__')
    return 0
"""
    modules = {
        "iniconfig": {"iniconfig/__init__.py": b"__version__='2.3.0'\n"},
        "packaging": {"packaging/__init__.py": b"__version__='26.2'\n"},
        "pluggy": {"pluggy/__init__.py": b"__version__='1.6.0'\n"},
        "pygments": {"pygments/__init__.py": b"__version__='2.19.2'\n"},
        "pytest": {"pytest/__init__.py": fake_pytest},
    }
    for name in validator.VALIDATOR_PACKAGES:
        source = validator.PURE_SOURCES[name]
        hashes[name] = _build_wheel(
            validator_root / "wheels" / source.filename,
            package=name,
            version=validator.EXPECTED_VERSIONS[name],
            tag="py3-none-any",
            files=modules[name],
        )

    machine = validator._host_machine()
    source = validator.DUCKDB_SOURCES[machine]
    native_name = f"_duckdb.cpython-312-{machine}-linux-gnu.so"
    archive = runtime_root / "bootstrap-artifacts" / source.filename
    hashes["duckdb"] = _build_wheel(
        archive,
        package="duckdb",
        version="1.5.5",
        tag=f"cp312-cp312-manylinux_2_28_{machine}",
        files={
            "duckdb/__init__.py": b"__version__='1.5.5'\n",
            native_name: b"\x7fELFsynthetic-test-module",
        },
    )
    site = runtime_root / "lib/python3.12/site-packages"
    site.mkdir(parents=True)
    with zipfile.ZipFile(archive) as wheel:
        wheel.extractall(site)
    return validator_root, runtime_root, hashes


def _write_lock(path: Path, hashes: dict[str, str]) -> None:
    lines = []
    for name in ("pytest", "iniconfig", "packaging", "pluggy", "pygments"):
        lines.append(
            f"{name}=={validator.EXPECTED_VERSIONS[name]} "
            f"--hash=sha256:{hashes[name].removeprefix('sha256:')}"
        )
    lines.append(
        "duckdb==1.5.5 "
        f"--hash=sha256:{hashes['duckdb'].removeprefix('sha256:')} "
        f"--hash=sha256:{'0' * 64}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        [str(validator.GIT_EXECUTABLE), *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _commit_repository(root: Path, message: str) -> None:
    _git(root, "init", "-b", "validation-test")
    _git(root, "config", "user.name", "DQK Validator Test")
    _git(root, "config", "user.email", "dqk-validator@example.test")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)


def _fake_repositories(
    tmp_path: Path,
    *,
    hashes: dict[str, str],
    test_source: str,
) -> tuple[Path, Path, Path, Path]:
    parent = tmp_path / "parent"
    script = parent / "scripts/ops/ipfs_datasets_duckdb_quack_validator.py"
    script.parent.mkdir(parents=True)
    shutil.copy2(validator.SCRIPT_PATH, script)
    lock = parent / "requirements/duckdb-quack-validator.lock"
    _write_lock(lock, hashes)

    accelerate = parent / "ipfs_accelerate_py"
    package = accelerate / "ipfs_accelerate_py"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("SEALED_TEST_PACKAGE=True\n", encoding="utf-8")
    supervisor = package / "agent_supervisor"
    supervisor.mkdir()
    (supervisor / "__init__.py").write_text("", encoding="utf-8")
    (supervisor / "validation_runtime.py").write_text(
        "from pathlib import Path\n"
        "class ValidationRuntimeError(ValueError): pass\n"
        "def validation_python_executable(environment=None): return '/usr/bin/python3.12'\n"
        "def _file_identity(path): return {'path': str(Path(path))}\n",
        encoding="utf-8",
    )
    test_file = accelerate / "test/api/test_sealed_probe.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(test_source, encoding="utf-8")
    _commit_repository(accelerate, "accelerator validation fixture")
    _commit_repository(parent, "parent validation fixture")
    return parent, accelerate, script, lock


def test_canonical_validator_lock_matches_primary_wheel_artifacts() -> None:
    lock = validator.parse_lock(validator.DEFAULT_LOCK)

    assert {name: item.version for name, item in lock.items()} == validator.EXPECTED_VERSIONS
    for name, source in validator.PURE_SOURCES.items():
        assert lock[name].hashes == {"sha256:" + source.sha256}
        assert source.url.startswith("https://files.pythonhosted.org/")
        assert source.url.endswith(source.filename)
    assert lock["duckdb"].hashes == {
        "sha256:" + source.sha256 for source in validator.DUCKDB_SOURCES.values()
    }


def test_wheel_verifier_rejects_record_and_member_path_forgery(tmp_path: Path) -> None:
    corrupt = tmp_path / "pytest-9.0.3-py3-none-any.whl"
    digest = _build_wheel(
        corrupt,
        package="pytest",
        version="9.0.3",
        tag="py3-none-any",
        files={"pytest/__init__.py": b"__version__='9.0.3'\n"},
        corrupt_record=True,
    )
    with pytest.raises(RuntimeError, match="RECORD digest"):
        validator.verify_wheel(
            corrupt,
            package="pytest",
            version="9.0.3",
            allowed_hashes={digest},
            required_tags={"py3-none-any"},
        )

    traversal = tmp_path / "pluggy-1.6.0-py3-none-any.whl"
    _build_wheel(
        traversal,
        package="pluggy",
        version="1.6.0",
        tag="py3-none-any",
        files={"pluggy/__init__.py": b"__version__='1.6.0'\n"},
    )
    with zipfile.ZipFile(traversal, "a") as archive:
        archive.writestr("../foreign.py", b"raise RuntimeError\n")
    traversal_digest = "sha256:" + hashlib.sha256(traversal.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError, match="portable relative path"):
        validator.verify_wheel(
            traversal,
            package="pluggy",
            version="1.6.0",
            allowed_hashes={traversal_digest},
            required_tags={"py3-none-any"},
        )


@pytest.mark.skipif(not BASE_PYTHON.is_file(), reason="canonical CPython 3.12 unavailable")
def test_real_subprocess_is_sealed_and_receipt_binds_both_repositories(
    tmp_path: Path,
) -> None:
    validator_root, runtime_root, hashes = _fake_artifacts(tmp_path)
    test_source = """\
import os
import sys
import duckdb
import ipfs_accelerate_py

assert duckdb.__version__ == '1.5.5'
assert ipfs_accelerate_py.SEALED_TEST_PACKAGE is True
assert sys.flags.isolated and sys.flags.no_site and sys.flags.safe_path
assert sys.flags.dont_write_bytecode
assert os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'
assert os.environ['IPFS_ACCEL_SKIP_CORE'] == '1'
assert 'PYTHONPATH' not in os.environ
assert 'PYTEST_ADDOPTS' not in os.environ
assert all('foreign-poison' not in value for value in sys.path)
"""
    parent, accelerate, script, lock = _fake_repositories(
        tmp_path, hashes=hashes, test_source=test_source
    )
    environment = {
        **os.environ,
        "PYTHONPATH": str(tmp_path / "foreign-poison"),
        "PYTEST_ADDOPTS": "--help",
        "PYTEST_PLUGINS": "foreign_plugin",
        "LD_PRELOAD": str(tmp_path / "foreign.so"),
    }
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "run",
            "--parent-root",
            str(parent),
            "--accelerate-root",
            str(accelerate),
            "--runtime-root",
            str(runtime_root),
            "--validator-root",
            str(validator_root),
            "--base-python",
            str(BASE_PYTHON),
            "--lock",
            str(lock),
            "--test",
            "test/api/test_sealed_probe.py",
        ],
        cwd=parent,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["schema"] == validator.SCHEMA
    assert receipt["repository_before"] == receipt["repository_after"]
    assert receipt["repository_before"]["parent"]["accelerator_gitlink"] == (
        receipt["repository_before"]["accelerator"]["head"]
    )
    assert receipt["base_python"]["executable"] == str(BASE_PYTHON)
    assert receipt["canonical_invocation"]["argv"][:4] == [
        str(BASE_PYTHON),
        "-I",
        "-B",
        "-S",
    ]
    assert receipt["output"]["returncode"] == 0
    assert receipt["output"]["bounds"]["timeout_seconds"] == "900.000"

    def assert_formal_json(value: object) -> None:
        assert not isinstance(value, float)
        if isinstance(value, dict):
            for nested in value.values():
                assert_formal_json(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_formal_json(nested)

    assert_formal_json(receipt)
    assert {item["repository_role"] for item in receipt["validation_artifacts"]} == {
        "parent",
        "accelerator",
    }
    assert receipt["receipt_id"].startswith("sha256:")


@pytest.mark.skipif(not BASE_PYTHON.is_file(), reason="canonical CPython 3.12 unavailable")
def test_real_subprocess_rejects_repository_mutation(
    tmp_path: Path,
) -> None:
    validator_root, runtime_root, hashes = _fake_artifacts(tmp_path)
    parent, accelerate, script, lock = _fake_repositories(
        tmp_path,
        hashes=hashes,
        test_source=(
            "from pathlib import Path\n"
            "Path(__file__).write_text('changed\\n', encoding='utf-8')\n"
        ),
    )
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "run",
            "--parent-root",
            str(parent),
            "--accelerate-root",
            str(accelerate),
            "--runtime-root",
            str(runtime_root),
            "--validator-root",
            str(validator_root),
            "--base-python",
            str(BASE_PYTHON),
            "--lock",
            str(lock),
            "--test",
            "test/api/test_sealed_probe.py",
        ],
        cwd=parent,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 1
    error = json.loads(result.stderr)
    assert "repository is not clean" in error["detail"]


@pytest.mark.skipif(not BASE_PYTHON.is_file(), reason="canonical CPython 3.12 unavailable")
def test_real_subprocess_output_is_bounded(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="stdout exceeded its byte bound"):
        validator._run_bounded(
            [
                str(BASE_PYTHON),
                "-I",
                "-B",
                "-S",
                "-c",
                "import sys; sys.stdout.write('x' * 4096); sys.stdout.flush()",
            ],
            cwd=tmp_path,
            environment={},
            timeout_seconds=10.0,
            stdout_limit=512,
            stderr_limit=512,
            combined_limit=512,
        )
