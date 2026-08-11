"""Isolated source and installed-wheel contracts for the datasets bridge.

The subprocesses deliberately use an ordinary direct test node and never pass
``-p``.  Source runs disable entry-point autoload and exercise the root
``pytest_plugins`` fallback.  Wheel runs enable autoload and exercise the real
``pytest11`` metadata produced by this project's packaging files.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PYTEST_SITE = Path(pytest.__file__).resolve().parents[1]
BRIDGE_MODULE = "ipfs_datasets_py.pytest_proof_reuse"
IMPLEMENTATION_MODULE = "ipfs_accelerate_py.testing.proof_reuse.plugin"
CANONICAL_PLUGIN_NAME = "ipfs-proof-reuse"
BRIDGE_ENTRY_POINT = "ipfs-datasets-proof-reuse"
_PYTEST_RUNTIME_PACKAGES = (
    "pytest",
    "_pytest",
    "pluggy",
    "iniconfig",
    "packaging",
    "pygments",
    "py",
)


def _write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")


def _copy_bootstrap_package(destination: Path) -> None:
    package = destination / "ipfs_datasets_py"
    package.mkdir(parents=True)
    for filename in ("__init__.py", "pytest_proof_reuse.py"):
        shutil.copy2(PROJECT_ROOT / "ipfs_datasets_py" / filename, package / filename)


@pytest.fixture(scope="module")
def isolated_pytest_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Provide pytest imports without exposing ambient pytest11 metadata."""

    runtime = tmp_path_factory.mktemp("datasets-pytest-runtime")
    for package_name in _PYTEST_RUNTIME_PACKAGES:
        spec = importlib.util.find_spec(package_name)
        assert spec is not None, f"pytest runtime package is missing: {package_name}"
        if spec.submodule_search_locations:
            source = Path(next(iter(spec.submodule_search_locations))).resolve()
            (runtime / package_name).symlink_to(source, target_is_directory=True)
        else:
            assert spec.origin is not None
            source = Path(spec.origin).resolve()
            (runtime / source.name).symlink_to(source)
    return runtime


def _source_checkout(root: Path) -> Path:
    checkout = root / "source-checkout"
    checkout.mkdir()
    shutil.copy2(PROJECT_ROOT / "conftest.py", checkout / "conftest.py")
    _copy_bootstrap_package(checkout)
    return checkout


@pytest.fixture(scope="module")
def installed_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build and install a wheel from the repository's actual bootstrap files."""

    root = tmp_path_factory.mktemp("datasets-bootstrap-wheel")
    build_source = root / "build-source"
    build_source.mkdir()
    for filename in ("setup.py", "pyproject.toml", "README.md", "ipfs_datasets_cli.py"):
        shutil.copy2(PROJECT_ROOT / filename, build_source / filename)
    _copy_bootstrap_package(build_source)
    source_vendor = PROJECT_ROOT / "typescript" / "logic-runtime-mtl"
    shutil.copytree(source_vendor, build_source / "typescript" / "logic-runtime-mtl")

    wheelhouse = root / "wheelhouse"
    wheelhouse.mkdir()
    pip_home = root / "pip-home"
    pip_temporary = root / "pip-tmp"
    pip_home.mkdir()
    pip_temporary.mkdir()
    environment = dict(os.environ)
    environment.update(
        {
            "IPFS_DATASETS_PY_INCLUDE_VCS_DEPENDENCIES": "0",
            "IPFS_DATASETS_PY_AUTO_NLTK_DOWNLOAD": "0",
            "IPFS_DATASETS_PY_AUTO_GROTH16_BUILD": "0",
            "PYTHONPATH": str(PYTEST_SITE),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HOME": str(pip_home),
            "XDG_CACHE_HOME": str(pip_home / ".cache"),
            "XDG_CONFIG_HOME": str(pip_home / ".config"),
            "TMPDIR": str(pip_temporary),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
            "PIP_NO_CACHE_DIR": "1",
        }
    )
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            "--no-cache-dir",
            "--wheel-dir",
            str(wheelhouse),
            str(build_source),
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    wheels = list(wheelhouse.glob("ipfs_datasets_py-*.whl"))
    assert len(wheels) == 1

    # The built artifact itself must expose one bridge and keep accelerator out
    # of unconditional Requires-Dist metadata.
    with zipfile.ZipFile(wheels[0]) as archive:
        entry_points_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")
        )
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        entry_points = archive.read(entry_points_name).decode("utf-8")
        metadata = archive.read(metadata_name).decode("utf-8")
    assert entry_points.count(
        f"{BRIDGE_ENTRY_POINT} = {BRIDGE_MODULE}"
    ) == 1
    accelerator_requirements = [
        line
        for line in metadata.splitlines()
        if line.lower().replace("_", "-").startswith(
            "requires-dist: ipfs-accelerate-py"
        )
    ]
    assert accelerator_requirements
    assert all(
        "extra == 'accelerate'" in line or 'extra == "accelerate"' in line
        for line in accelerator_requirements
    )

    target = root / "installed"
    installed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--no-compile",
            "--force-reinstall",
            "--target",
            str(target),
            str(wheels[0]),
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    return target


def _accelerator_layout(root: Path, case: str) -> Path:
    import_root = root / f"accelerator-{case}"
    package = import_root / "ipfs_accelerate_py"
    package.mkdir(parents=True)
    if case == "namespace":
        return import_root

    if case != "namespace-plugin-chain-failure":
        _write(package / "__init__.py", "# regular installed-style package\n")
    if case == "regular-incomplete":
        return import_root

    _write(package / "testing" / "__init__.py", "")
    _write(package / "testing" / "proof_reuse" / "__init__.py", "")
    if case == "transitive-failure":
        plugin_source = "import required_proof_reuse_transitive_dependency\n"
    elif case == "namespace-plugin-chain-failure":
        plugin_source = "import ipfs_accelerate_py.testing.runtime_dependency\n"
    elif case == "import-side-effect":
        plugin_source = """
            import os
            from pathlib import Path

            Path(os.environ["PTR_DATASETS_PLUGIN_IMPORT_SENTINEL"]).write_text(
                "imported\\n", encoding="utf-8"
            )
        """
    elif case == "available":
        plugin_source = """
            import os
            from pathlib import Path

            PLUGIN_NAME = "ipfs-proof-reuse"

            def _record(value):
                path = Path(os.environ["PTR_DATASETS_TRACE"])
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(value + "\\n")

            def pytest_addoption(parser):
                parser.addoption("--fake-proof-reuse", action="store_true", default=False)

            def pytest_configure(config):
                _record("plugin-configure")
        """
    else:  # pragma: no cover - test helper misuse
        raise AssertionError(case)
    _write(package / "testing" / "proof_reuse" / "plugin.py", plugin_source)
    if case == "available":
        distribution = import_root / "ptr_fake_accelerator-1.0.dist-info"
        distribution.mkdir()
        _write(
            distribution / "METADATA",
            """
            Metadata-Version: 2.1
            Name: ptr-fake-accelerator
            Version: 1.0
            """,
        )
        _write(
            distribution / "entry_points.txt",
            f"""
            [pytest11]
            {CANONICAL_PLUGIN_NAME} = {IMPLEMENTATION_MODULE}
            """,
        )
    return import_root


def _environment(
    tmp_path: Path,
    *python_paths: Path,
    pytest_runtime: Path,
    autoload: bool,
) -> dict[str, str]:
    home = tmp_path / "home"
    temporary = tmp_path / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(exist_ok=True)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [*(str(path) for path in python_paths), str(pytest_runtime)]
    )
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["HOME"] = str(home)
    environment["XDG_CACHE_HOME"] = str(home / ".cache")
    environment["XDG_CONFIG_HOME"] = str(home / ".config")
    environment["XDG_DATA_HOME"] = str(home / ".local" / "share")
    environment["TMPDIR"] = str(temporary)
    environment["PIP_CONFIG_FILE"] = os.devnull
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    environment["PIP_NO_INDEX"] = "1"
    environment["PIP_NO_CACHE_DIR"] = "1"
    environment["IPFS_DATASETS_PROJECT_ROOT"] = str(tmp_path / "package-state")
    environment["IPFS_DATASETS_PY_MINIMAL_IMPORTS"] = "1"
    environment["IPFS_DATASETS_AUTO_INSTALL"] = "0"
    environment["IPFS_AUTO_INSTALL"] = "0"
    environment["IPFS_DATASETS_ENSURE_INSTALLER"] = "0"
    environment["IPFS_TEST_PROOF_REUSE_MODE"] = "off"
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    if autoload:
        environment.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    else:
        environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return environment


def _execution_project(
    tmp_path: Path,
    installation: str,
    installed_wheel: Path,
) -> tuple[Path, Path, bool]:
    if installation == "source":
        checkout = _source_checkout(tmp_path)
        return checkout, checkout, False
    if installation == "wheel":
        project = tmp_path / "wheel-project"
        project.mkdir()
        return project, installed_wheel, True
    raise AssertionError(installation)  # pragma: no cover


def _run_pytest(
    project: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    # An ordinary direct node: intentionally no ``-p`` plugin injection.
    return subprocess.run(
        [sys.executable, "-m", "pytest", "test_direct.py", "-q"],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _success_body() -> str:
    return f"""
        import os
        from pathlib import Path

        import {IMPLEMENTATION_MODULE} as implementation

        def test_direct(request):
            manager = request.config.pluginmanager
            registrations = manager.list_name_plugin()
            implementation_names = [
                name for name, plugin in registrations if plugin is implementation
            ]
            assert implementation_names == [{CANONICAL_PLUGIN_NAME!r}]
            bridges = [
                (name, plugin)
                for name, plugin in registrations
                if getattr(plugin, "__name__", "") == {BRIDGE_MODULE!r}
            ]
            assert [name for name, _ in bridges] == [
                os.environ["PTR_DATASETS_EXPECTED_BRIDGE_NAME"]
            ]
            assert request.config.getoption("fake_proof_reuse") is False
            with Path(os.environ["PTR_DATASETS_TRACE"]).open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write("body\\n")
    """


def _namespace_body() -> str:
    return f"""
        import os
        from pathlib import Path

        import {BRIDGE_MODULE} as bridge

        def test_direct(request):
            manager = request.config.pluginmanager
            assert manager.get_plugin({CANONICAL_PLUGIN_NAME!r}) is None
            bridges = [
                plugin
                for _, plugin in manager.list_name_plugin()
                if getattr(plugin, "__name__", "") == {BRIDGE_MODULE!r}
            ]
            assert len(bridges) == 1
            Path(os.environ["PTR_DATASETS_TRACE"]).write_text(
                "body\\n", encoding="utf-8"
            )
    """


@pytest.mark.parametrize(
    ("installation", "entry_point_order"),
    (
        ("source", "source-fallback"),
        ("wheel", "datasets-first"),
        ("wheel", "accelerator-first"),
    ),
)
def test_direct_node_loads_one_bridge_and_one_canonical_implementation(
    tmp_path: Path,
    isolated_pytest_site: Path,
    installed_wheel: Path,
    installation: str,
    entry_point_order: str,
) -> None:
    project, datasets_path, autoload = _execution_project(
        tmp_path, installation, installed_wheel
    )
    accelerator_path = _accelerator_layout(tmp_path, "available")
    trace = tmp_path / "trace.txt"
    _write(project / "test_direct.py", _success_body())
    ordered_paths = (
        (accelerator_path, datasets_path)
        if entry_point_order == "accelerator-first"
        else (datasets_path, accelerator_path)
    )
    environment = _environment(
        tmp_path,
        *ordered_paths,
        pytest_runtime=isolated_pytest_site,
        autoload=autoload,
    )
    environment["PTR_DATASETS_TRACE"] = str(trace)
    environment["PTR_DATASETS_EXPECTED_BRIDGE_NAME"] = (
        BRIDGE_MODULE if installation == "source" else BRIDGE_ENTRY_POINT
    )

    completed = _run_pytest(project, environment)
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "1 passed" in output
    assert trace.read_text(encoding="utf-8").splitlines() == [
        "plugin-configure",
        "body",
    ]


@pytest.mark.parametrize("installation", ("source", "wheel"))
def test_empty_namespace_gitlink_is_an_inert_bridge(
    tmp_path: Path,
    isolated_pytest_site: Path,
    installed_wheel: Path,
    installation: str,
) -> None:
    project, datasets_path, autoload = _execution_project(
        tmp_path, installation, installed_wheel
    )
    accelerator_path = _accelerator_layout(tmp_path, "namespace")
    trace = tmp_path / "trace.txt"
    _write(project / "test_direct.py", _namespace_body())
    environment = _environment(
        tmp_path,
        accelerator_path,
        datasets_path,
        pytest_runtime=isolated_pytest_site,
        autoload=autoload,
    )
    environment["PTR_DATASETS_TRACE"] = str(trace)

    completed = _run_pytest(project, environment)
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "1 passed" in output
    assert trace.read_text(encoding="utf-8").splitlines() == ["body"]


@pytest.mark.parametrize("installation", ("source", "wheel"))
@pytest.mark.parametrize(
    ("case", "visible_name"),
    (
        ("regular-incomplete", "ipfs_accelerate_py.testing"),
        ("transitive-failure", "required_proof_reuse_transitive_dependency"),
        (
            "namespace-plugin-chain-failure",
            "ipfs_accelerate_py.testing.runtime_dependency",
        ),
    ),
)
def test_broken_regular_or_found_plugin_import_remains_visible(
    tmp_path: Path,
    isolated_pytest_site: Path,
    installed_wheel: Path,
    installation: str,
    case: str,
    visible_name: str,
) -> None:
    project, datasets_path, autoload = _execution_project(
        tmp_path, installation, installed_wheel
    )
    accelerator_path = _accelerator_layout(tmp_path, case)
    _write(project / "test_direct.py", "def test_direct():\n    assert True\n")
    environment = _environment(
        tmp_path,
        accelerator_path,
        datasets_path,
        pytest_runtime=isolated_pytest_site,
        autoload=autoload,
    )
    environment["PTR_DATASETS_TRACE"] = str(tmp_path / "trace.txt")

    completed = _run_pytest(project, environment)
    output = completed.stdout + completed.stderr
    assert completed.returncode != 0, output
    assert visible_name in output
    assert "1 passed" not in output


def _tree_entries(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def test_parent_and_bridge_import_never_execute_install_build_or_network(
    tmp_path: Path,
    isolated_pytest_site: Path,
) -> None:
    guard = tmp_path / "guard"
    _write(
        guard / "sitecustomize.py",
        """
        import os
        import socket
        import subprocess
        import urllib.request

        CALLS = []

        def blocked(kind):
            def invoke(*args, **kwargs):
                CALLS.append(kind)
                raise AssertionError(f"forbidden import-time action: {kind}")
            return invoke

        subprocess.run = blocked("subprocess.run")
        subprocess.Popen = blocked("subprocess.Popen")
        subprocess.call = blocked("subprocess.call")
        subprocess.check_call = blocked("subprocess.check_call")
        subprocess.check_output = blocked("subprocess.check_output")
        os.system = blocked("os.system")
        urllib.request.urlopen = blocked("urllib.request.urlopen")
        socket.create_connection = blocked("socket.create_connection")
        socket.socket.connect = blocked("socket.connect")
        """,
    )
    accelerator_path = _accelerator_layout(tmp_path, "import-side-effect")
    plugin_import_sentinel = tmp_path / "plugin-imported"
    environment = _environment(
        tmp_path,
        guard,
        accelerator_path,
        PROJECT_ROOT,
        pytest_runtime=isolated_pytest_site,
        autoload=False,
    )
    environment.pop("IPFS_DATASETS_PY_MINIMAL_IMPORTS", None)
    environment["IPFS_DATASETS_AUTO_INSTALL"] = "1"
    environment["IPFS_AUTO_INSTALL"] = "1"
    environment["IPFS_DATASETS_ENSURE_INSTALLER"] = "1"
    environment["IPFS_DATASETS_PY_AUTO_NLTK_DOWNLOAD"] = "1"
    environment["IPFS_DATASETS_PY_AUTO_GROTH16_BUILD"] = "1"
    environment["PTR_DATASETS_PLUGIN_IMPORT_SENTINEL"] = str(plugin_import_sentinel)
    home = Path(environment["HOME"])
    package_state = Path(environment["IPFS_DATASETS_PROJECT_ROOT"])
    state_before = (_tree_entries(home), _tree_entries(package_state))
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sitecustomize; "
                "import ipfs_datasets_py; "
                "import ipfs_datasets_py.pytest_proof_reuse as bridge; "
                f"assert {IMPLEMENTATION_MODULE!r} not in __import__('sys').modules; "
                "assert not __import__('pathlib').Path("
                "__import__('os').environ['PTR_DATASETS_PLUGIN_IMPORT_SENTINEL']"
                ").exists(); "
                "assert sitecustomize.CALLS == [], sitecustomize.CALLS"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not plugin_import_sentinel.exists()
    assert (_tree_entries(home), _tree_entries(package_state)) == state_before
