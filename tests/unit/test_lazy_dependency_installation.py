from __future__ import annotations

import multiprocessing
import threading
import time
import types
from pathlib import Path

import pytest


def _hold_process_install_lock(project_root, entered, release):
    import os

    os.environ["IPFS_DATASETS_AUTO_INSTALL"] = "false"
    os.environ["IPFS_DATASETS_PROJECT_ROOT"] = str(project_root)
    from ipfs_datasets_py.auto_installer import DependencyInstaller

    installer = DependencyInstaller(auto_install=False)
    with installer._package_install_lock("shared-process-test") as acquired:
        if acquired:
            entered.set()
            release.wait(timeout=5)


def _installer(monkeypatch, tmp_path, *, auto_install=True):
    from ipfs_datasets_py.auto_installer import DependencyInstaller

    monkeypatch.setenv("IPFS_DATASETS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("IPFS_DATASETS_INSTALL_RETRY_SECONDS", "0")
    return DependencyInstaller(auto_install=auto_install)


def test_catalog_preserves_legacy_packages_and_import_aliases():
    from ipfs_datasets_py.dependency_catalog import (
        dependency_for_distribution,
        dependency_for_import,
        package_candidates,
    )

    legacy_packages = {
        "anthropic",
        "anyio",
        "beartype",
        "beautifulsoup4",
        "coverage",
        "cvc5",
        "datasets",
        "easyocr",
        "elasticsearch",
        "faiss-cpu",
        "faker",
        "fastapi",
        "ffmpeg-python",
        "flask",
        "github-copilot-sdk",
        "hypothesis",
        "imageio-ffmpeg",
        "jsonschema",
        "lxml_html_clean",
        "mathsat",
        "moviepy",
        "networkx",
        "newspaper3k",
        "nltk",
        "numpy",
        "openai",
        "opencv-python",
        "pandas",
        "pdfplumber",
        "pillow",
        "pymupdf",
        "pyarrow",
        "pydantic",
        "pysmt",
        "pytest",
        "pytest-asyncio",
        "pytest-benchmark",
        "pytest-cov",
        "pytest-mock",
        "pytest-timeout",
        "pytest-xdist",
        "pytesseract",
        "qdrant-client",
        "readability-lxml",
        "reportlab",
        "requests",
        "scikit-learn",
        "scipy",
        "sentence-transformers",
        "spacy",
        "surya-ocr",
        "tiktoken",
        "torch",
        "transformers",
        "uvicorn",
        "z3-solver",
    }

    assert legacy_packages <= {name.lower() for name in package_candidates()}
    assert dependency_for_import("fitz").distribution == "pymupdf"
    assert dependency_for_import("PIL.Image").distribution == "pillow"
    assert dependency_for_distribution("symbolicai>=1.14.0,<2.0.0").import_name == "symai"


def test_missing_module_is_installed_and_reimported(monkeypatch, tmp_path):
    import ipfs_datasets_py.auto_installer as auto_installer

    installer = _installer(monkeypatch, tmp_path)
    imported_module = types.ModuleType("example_lazy_module")
    installed = False
    install_specs: list[str] = []

    def fake_import(name):
        if name != "example_lazy_module":
            return __import__(name)
        if not installed:
            raise ModuleNotFoundError(name, name=name)
        return imported_module

    def fake_pip_install(package_spec):
        nonlocal installed
        install_specs.append(package_spec)
        installed = True
        return True

    monkeypatch.setattr(auto_installer.importlib, "import_module", fake_import)
    monkeypatch.setattr(installer, "_pip_install", fake_pip_install)

    success, module = installer.ensure_dependency(
        "example_lazy_module",
        "example-lazy-distribution>=1",
    )

    assert success is True
    assert module is imported_module
    assert install_specs == ["example-lazy-distribution>=1"]


def test_direct_install_tracks_distribution_and_deduplicates(monkeypatch, tmp_path):
    installer = _installer(monkeypatch, tmp_path)
    install_specs: list[str] = []
    monkeypatch.setattr(
        installer,
        "_pip_install",
        lambda package_spec: install_specs.append(package_spec) or True,
    )

    assert installer.install_python_dependency("beartype") is True
    assert installer.install_python_dependency("beartype") is True

    assert install_specs == ["beartype>=0.15.0,<1.0.0"]
    assert "beartype" in installer.installed_packages


def test_direct_install_rejects_pip_option_injection(monkeypatch, tmp_path):
    installer = _installer(monkeypatch, tmp_path)
    install_specs: list[str] = []
    monkeypatch.setattr(
        installer,
        "_pip_install",
        lambda package_spec: install_specs.append(package_spec) or True,
    )

    assert installer.install_python_dependency("--extra-index-url=https://example.test") is False
    assert install_specs == []


def test_nested_missing_import_does_not_reinstall_parent(monkeypatch, tmp_path):
    import ipfs_datasets_py.auto_installer as auto_installer

    installer = _installer(monkeypatch, tmp_path)
    install_specs: list[str] = []

    def fake_import(name):
        raise ModuleNotFoundError("missing transitive dependency", name="transitive_dep")

    monkeypatch.setattr(auto_installer.importlib, "import_module", fake_import)
    monkeypatch.setattr(
        installer,
        "_pip_install",
        lambda package_spec: install_specs.append(package_spec) or True,
    )

    success, module = installer.ensure_dependency("installed_parent", "installed-parent")

    assert success is False
    assert module is None
    assert install_specs == []


def test_parallel_requests_run_one_pip_install(monkeypatch, tmp_path):
    import ipfs_datasets_py.auto_installer as auto_installer

    installer = _installer(monkeypatch, tmp_path)
    imported_module = types.ModuleType("parallel_lazy_module")
    state = {"installed": False, "pip_calls": 0}
    state_lock = threading.Lock()
    start = threading.Barrier(8)

    def fake_import(name):
        if name != "parallel_lazy_module":
            return __import__(name)
        with state_lock:
            installed = state["installed"]
        if not installed:
            raise ModuleNotFoundError(name, name=name)
        return imported_module

    def fake_pip_install(_package_spec):
        with state_lock:
            state["pip_calls"] += 1
        time.sleep(0.03)
        with state_lock:
            state["installed"] = True
        return True

    monkeypatch.setattr(auto_installer.importlib, "import_module", fake_import)
    monkeypatch.setattr(installer, "_pip_install", fake_pip_install)

    results: list[tuple[bool, object | None]] = []

    def worker():
        start.wait()
        results.append(
            installer.ensure_dependency("parallel_lazy_module", "parallel-lazy-package")
        )

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 8
    assert all(success and module is imported_module for success, module in results)
    assert state["pip_calls"] == 1


def test_install_lock_serializes_worker_processes(tmp_path):
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("cross-process lock test requires the fork start method")
    context = multiprocessing.get_context("fork")
    first_entered = context.Event()
    first_release = context.Event()
    second_entered = context.Event()
    second_release = context.Event()
    second_release.set()

    first = context.Process(
        target=_hold_process_install_lock,
        args=(str(tmp_path), first_entered, first_release),
    )
    second = context.Process(
        target=_hold_process_install_lock,
        args=(str(tmp_path), second_entered, second_release),
    )

    first.start()
    assert first_entered.wait(timeout=5)
    second.start()
    assert second_entered.wait(timeout=0.25) is False

    first_release.set()
    assert second_entered.wait(timeout=5)
    first.join(timeout=5)
    second.join(timeout=5)

    assert first.exitcode == 0
    assert second.exitcode == 0


def test_disabled_installer_only_probes_import(monkeypatch, tmp_path):
    import ipfs_datasets_py.auto_installer as auto_installer

    installer = _installer(monkeypatch, tmp_path, auto_install=False)
    install_specs: list[str] = []

    monkeypatch.setattr(
        auto_installer.importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(ModuleNotFoundError(name, name=name)),
    )
    monkeypatch.setattr(
        installer,
        "_pip_install",
        lambda package_spec: install_specs.append(package_spec) or True,
    )

    assert installer.ensure_dependency("disabled_lazy_module") == (False, None)
    assert install_specs == []


def test_minimal_import_mode_disables_runtime_installation(monkeypatch, tmp_path):
    monkeypatch.setenv("IPFS_DATASETS_AUTO_INSTALL", "true")
    monkeypatch.setenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")

    installer = _installer(monkeypatch, tmp_path, auto_install=None)

    assert installer.auto_install is False


def test_proxy_resolves_only_on_first_attribute_access(monkeypatch):
    import ipfs_datasets_py.lazy_dependencies as lazy_dependencies

    imported_module = types.ModuleType("proxy_demo")
    calls: list[str] = []
    monkeypatch.setattr(
        lazy_dependencies,
        "ensure_module",
        lambda module_name, **_kwargs: calls.append(module_name) or imported_module,
    )

    proxy = lazy_dependencies.LazyDependencyProxy(
        ("proxy_demo",),
        critical_dependencies=(),
    )

    assert calls == []
    assert proxy.keys() == ["proxy_demo"]
    assert calls == []
    assert proxy.proxy_demo is imported_module
    assert proxy.proxy_demo is imported_module
    assert calls == ["proxy_demo"]


def test_previously_installer_only_packages_are_declared():
    root = Path(__file__).resolve().parents[2]
    declarations = "\n".join(
        (root / filename).read_text(encoding="utf-8")
        for filename in (
            "setup.py",
            "pyproject.toml",
            "requirements-lazy.txt",
            "requirements-theorem-provers.txt",
        )
    ).lower()

    for distribution in (
        "beartype",
        "easyocr",
        "github-copilot-sdk",
        "imageio-ffmpeg",
        "pysmt",
    ):
        assert distribution in declarations


def test_repo_bootstrap_is_not_implied_by_lazy_python_installs(monkeypatch):
    import ipfs_datasets_py.auto_installer as auto_installer

    monkeypatch.delenv("IPFS_DATASETS_ENSURE_INSTALLER", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_AUTO_INSTALL", "true")

    assert auto_installer._runtime_installer_check_enabled() is False
