"""Operator deployment seals do not confer proof or task-completion authority."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tomllib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal import validator_profile as profile
from ipfs_datasets_py.logic.autoformal.supervisor_queue import canonical_bytes


@pytest.fixture
def deployment(tmp_path):
    repository = tmp_path / "private-candidate"
    repository.mkdir()
    packets = tmp_path / "packets"
    packets.mkdir()
    for path in profile.SEALED_FILES:
        target = repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# protected test fixture\n")
    setup = "raise AssertionError('setup is data')\nsetup(extras_require={'validation': ['pytest>=9']})\n"
    (repository / "setup.py").write_text(setup)
    authority = {"file": "setup.py", "extra": "validation", "sha256": profile.digest(setup.encode()),
                 "extra-requirements-sha256": profile.digest(canonical_bytes(["pytest>=9"]))}
    (repository / "pyproject.toml").write_text(
        '[project]\nname="fixture"\nrequires-python=">=3.12"\n'
        '[tool.ipfs-accelerate-agent-supervisor.project-dependency-preflight]\n'
        'authority = ' + profile.toml_value(authority) + '\n')
    return repository, packets


def install(repository, packets):
    expected = profile.build_profile(repository, packets)
    target = repository / "pyproject.toml"
    target.write_text(target.read_text() + '\n[tool.ipfs-accelerate-agent-supervisor.sealed-python-validator]\n'
                      + '\n'.join(key + ' = ' + profile.toml_value(value) for key, value in expected.items()) + '\n')
    return expected


def test_generated_profile_is_exact_bound_and_does_not_edit_repository(deployment):
    repository, packets = deployment
    before = (repository / "pyproject.toml").read_bytes()
    patch = profile.profile_patch(repository, packets)
    assert patch.startswith("*** Begin Patch\n*** Update File: " + str(repository))
    assert (repository / "pyproject.toml").read_bytes() == before
    assert not profile.deployment_path(repository).exists()
    assert profile.require_deployment(repository) is None
    expected = install(repository, packets)
    assert profile.profile_in(tomllib.loads((repository / "pyproject.toml").read_text())) == expected
    assert expected["requirements"] == ["pytest>=9"]
    assert expected["interpreter"] == "python3"
    with pytest.raises(ValueError, match="receipt is missing"):
        profile.require_deployment(repository)
    receipt = profile.seal_deployment(repository, packets)
    assert receipt["published"] is False and receipt["production_promotion"] is False
    assert profile.require_deployment(repository)["passed"] is True
    with pytest.raises(FileExistsError):
        profile.seal_deployment(repository, packets)


@pytest.mark.parametrize("path", profile.DEPLOYMENT_PROTECTED)
def test_each_protected_file_mutation_invalidates_seal(deployment, path):
    repository, packets = deployment
    install(repository, packets)
    profile.seal_deployment(repository, packets)
    target = repository / path
    target.write_bytes(target.read_bytes() + b"\n# altered\n")
    with pytest.raises(ValueError, match="deployment drift"):
        profile.require_deployment(repository)


def test_profile_removal_cannot_restore_unconfigured_policy(deployment):
    repository, packets = deployment
    original = (repository / "pyproject.toml").read_bytes()
    install(repository, packets)
    profile.seal_deployment(repository, packets)
    (repository / "pyproject.toml").write_bytes(original)
    with pytest.raises(ValueError, match="deployment or operator receipt is missing"):
        profile.require_deployment(repository)


def test_wrong_repository_and_receipt_symlink_rejected(deployment):
    repository, packets = deployment
    install(repository, packets)
    receipt = profile.seal_deployment(repository, packets)
    receipt["repository"] = str(repository.parent)
    path = profile.deployment_path(repository)
    path.write_bytes(canonical_bytes(receipt))
    with pytest.raises(ValueError, match="invalid sealed"):
        profile.require_deployment(repository)
    moved = path.with_suffix(".saved")
    path.rename(moved)
    path.symlink_to(moved)
    with pytest.raises(ValueError, match="missing"):
        profile.require_deployment(repository)


def test_unreviewed_profile_cannot_be_sealed(deployment):
    repository, packets = deployment
    install(repository, packets)
    target = repository / "pyproject.toml"
    target.write_text(target.read_text().replace('interpreter = "python3"', 'interpreter = "/usr/bin/python3"'))
    with pytest.raises(ValueError, match="differs from generated"):
        profile.seal_deployment(repository, packets)
    assert not profile.deployment_path(repository).exists()


def test_new_profile_cannot_bypass_the_sealed_launcher(deployment):
    repository, packets = deployment
    with pytest.raises(ValueError, match="interpreter"):
        profile.build_profile(repository, packets, interpreter="/usr/bin/python3")


def test_packet_root_symlink_rejected(deployment):
    repository, packets = deployment
    alias = packets.parent / "alias"
    alias.symlink_to(packets, target_is_directory=True)
    with pytest.raises(ValueError, match="canonical"):
        profile.build_profile(repository, alias)


def test_new_profile_anchors_current_setup_but_never_accepts_changed_extra(deployment):
    repository, packets = deployment
    target = repository / "setup.py"
    target.write_text(target.read_text() + "# unrelated packaging metadata update\n")
    generated = profile.build_profile(repository, packets)
    assert generated["authority"]["sha256"] == profile.digest(target.read_bytes())
    target.write_text(target.read_text().replace("pytest>=9", "pytest>=1"))
    with pytest.raises(ValueError, match="extra authority changed"):
        profile.build_profile(repository, packets)


@pytest.mark.parametrize('name', [profile.RUNTIME_PROFILE_V1, profile.RUNTIME_PROFILE_V2])
def test_runtime_profile_declares_the_entire_pinned_extra_without_changing_legacy(deployment, name):
    repository, packets = deployment
    extra, requirements = profile.RUNTIME_PROFILES[name]
    setup = "setup(extras_require=" + repr({"validation": ["pytest>=9"],
        extra: list(requirements)}) + ")\n"
    (repository / "setup.py").write_text(setup)
    assert profile.build_profile(repository, packets)["requirements"] == ["pytest>=9"]
    runtime = profile.build_profile(repository, packets, runtime_profile=name)
    assert runtime["requirements"] == list(requirements)
    assert runtime["authority"]["extra"] == extra
    assert "multiformats==0.3.1.post4" in runtime["requirements"]
    with pytest.raises(ValueError, match="unsupported validator runtime"):
        profile.build_profile(repository, packets, runtime_profile="unreviewed-v2")
    (repository / "setup.py").write_text(setup.replace("multiformats==0.3.1.post4", "multiformats>=0"))
    with pytest.raises(ValueError, match="extra authority changed"):
        profile.build_profile(repository, packets, runtime_profile=name)


def test_validator_uses_fresh_builtin_pytest_without_inherited_plugins(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import supervisor_queue as queue
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("repair_validator_test", root / profile.ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    regression = "tests/test_task.py"
    (tmp_path / "tests").mkdir()
    (tmp_path / regression).write_text("def test_real(): assert True\n")
    monkeypatch.setattr(queue, "read_packet", lambda *a: {"regression_tests": list(queue.REGRESSION_TESTS)})
    monkeypatch.setattr(queue, "repair_outputs", lambda *a: [regression])
    monkeypatch.setattr(queue, "replay_packet", lambda *a: {"passed": True, "admitted": False})
    monkeypatch.setenv("PYTEST_ADDOPTS", "--collect-only")
    monkeypatch.setenv("PYTEST_PLUGINS", "unsafe_plugin")
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=7)
    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.main(["--packet", str(tmp_path / "packet.json"), "--sha256", "a" * 64]) == 7
    command, kwargs = calls[0]
    assert "--noconftest" in command and "addopts=" in command
    assert command[-5:] == [*queue.REGRESSION_TESTS, regression]
    assert kwargs["env"]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert kwargs["env"]["PYTEST_ADDOPTS"] == kwargs["env"]["PYTEST_PLUGINS"] == ""
    assert kwargs["env"]["IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS"] == "0"
