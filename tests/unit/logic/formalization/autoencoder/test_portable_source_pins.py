"""Relocated inference packages retain source/function identity without Git."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import portable_source_pins as original


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "relocated/ipfs_datasets_py"
    helper = root / "logic/formalization/autoencoder/portable_source_pins.py"
    helper.parent.mkdir(parents=True)
    (root / "__init__.py").write_text("")
    helper.write_bytes(Path(original.__file__).read_bytes())
    pins = load(helper, original.__name__)
    target = root / "fixture.py"
    target.write_text("def operation():\n    return 1\n")
    return pins, target


def test_gitless_package_checks_loaded_function_and_disk_hash(package):
    pins, target = package
    assert not (target.parent.parent / ".git").exists()
    module = load(target, "ipfs_datasets_py.fixture")
    expected = hashlib.sha256(target.read_bytes()).hexdigest()
    assert pins.pin_imported_module(module) == expected
    assert pins.pin_imported_module(module) == expected


@pytest.mark.parametrize("phase", ["before_first_pin", "after_first_pin"])
def test_disk_drift_is_rejected_even_if_module_loaded_before_first_pin(package, phase):
    pins, target = package
    module = load(target, "ipfs_datasets_py.fixture")
    if phase == "after_first_pin": pins.pin_imported_module(module)
    target.write_text("def operation():\n    return 2\n")
    with pytest.raises(ValueError, match="changed|differs"):
        pins.pin_imported_module(module)


@pytest.mark.parametrize("phase", ["before_first_pin", "after_first_pin"])
def test_loaded_function_drift_cannot_be_blessed_by_unchanged_disk(package, phase):
    pins, target = package
    module = load(target, "ipfs_datasets_py.fixture")
    if phase == "after_first_pin": pins.pin_imported_module(module)
    exec(compile("def operation():\n    return 99\n", str(target), "exec"), module.__dict__)
    with pytest.raises(ValueError, match="changed|differs"):
        pins.pin_imported_module(module)


@pytest.mark.parametrize("change", ["external_path", "different_name", "external_symlink", "nonmodule"])
def test_producer_must_resolve_to_its_exact_selected_package_module(package, tmp_path, change):
    pins, target = package
    if change in {"external_path", "external_symlink"}:
        external = tmp_path / "external.py"; external.write_bytes(target.read_bytes())
        if change == "external_symlink": target.unlink(); target.symlink_to(external)
        else: target = external
    name = "ipfs_datasets_py.other" if change == "different_name" else "ipfs_datasets_py.fixture"
    module = object() if change == "nonmodule" else load(target, name)
    with pytest.raises(ValueError): pins.pin_imported_module(module)


def test_intent_pin_population_includes_the_portable_checker():
    from ipfs_datasets_py.logic.formalization.autoencoder import intent_action_runtime_384 as runtime
    pins = runtime._pins()
    assert pins[original.__name__] == hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest()
    assert len(pins) == 6


def test_gitless_helper_import_and_pin_work_in_an_isolated_fresh_interpreter(package):
    pins, target = package
    script = '''
import importlib.util, sys
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
pins = load(sys.argv[1], "portable_test_helper")
module = load(sys.argv[2], "ipfs_datasets_py.fixture")
assert len(pins.pin_imported_module(module)) == 64
assert not any("autoencoder_schema_lake" in name for name in sys.modules)
'''
    subprocess.run([sys.executable, "-I", "-S", "-B", "-c", script, pins.__file__, str(target)], check=True)
