"""
Tests for the F-logic (Frame Logic) module.

Covers:
* Pure-Python data types (FLogicFrame, FLogicClass, FLogicOntology, FLogicQuery)
* ErgoAIWrapper in simulation mode (no binary required)
* FLogicSemanticOptimizer
"""

from __future__ import annotations

import importlib.util
import math
import os
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _load_flogic_optimizer():
    """Load the canonical flogic optimizer module directly."""
    _MOD_NAME = "ipfs_datasets_py.logic.flogic_optimizer"
    if _MOD_NAME in sys.modules:
        return sys.modules[_MOD_NAME]
    _path = (
        Path(__file__).parent.parent.parent.parent
        / "ipfs_datasets_py"
        / "logic"
        / "flogic_optimizer.py"
    )
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


def test_lazy_installer_recognizes_ergoai_aliases(monkeypatch):
    from ipfs_datasets_py.logic.external_provers.lazy_installer import (
        normalize_prover_name,
        prover_lazy_install_enabled,
    )

    monkeypatch.delenv("IPFS_DATASETS_PY_MINIMAL_IMPORTS", raising=False)
    monkeypatch.delenv("IPFS_DATASETS_PY_BENCHMARK", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS", "1")
    monkeypatch.delenv("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", raising=False)

    assert normalize_prover_name("runErgo.sh") == "ergoai"
    assert normalize_prover_name("runergo") == "ergoai"
    assert normalize_prover_name("ErgoEngine") == "ergoai"
    assert prover_lazy_install_enabled("ergo") is True

    monkeypatch.setenv("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")

    assert prover_lazy_install_enabled("ergoai") is False


def test_prover_installer_accepts_existing_ergoai_binary(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    fake_binary = tmp_path / "runErgo.sh"
    fake_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (tmp_path / ".ergo_paths").write_text("PROLOG=/usr/bin/false\n", encoding="utf-8")
    fake_binary.chmod(0o644)
    monkeypatch.setenv("ERGOAI_BINARY", str(fake_binary))

    assert prover_installer.ensure_ergoai(yes=False, strict=True) is True
    assert os.access(fake_binary, os.X_OK)


def test_prover_installer_discovers_repo_runergo(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    fake_binary = tmp_path / "ErgoAI" / "runergo"
    fake_binary.parent.mkdir()
    fake_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake_binary.parent / ".ergo_paths").write_text(
        "PROLOG=/usr/bin/false\n",
        encoding="utf-8",
    )
    fake_binary.chmod(0o755)
    monkeypatch.delenv("ERGOAI_BINARY", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR", str(tmp_path / "release"))
    monkeypatch.setattr(prover_installer, "_ergoai_submodule_path", lambda: tmp_path)

    assert prover_installer._find_ergoai_binary() == fake_binary


def test_prover_installer_skips_unconfigured_repo_runergo(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    fake_binary = tmp_path / "ErgoAI" / "runergo"
    fake_binary.parent.mkdir()
    fake_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_binary.chmod(0o755)
    monkeypatch.delenv("ERGOAI_BINARY", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR", str(tmp_path / "release"))
    monkeypatch.setattr(prover_installer, "_ergoai_submodule_path", lambda: tmp_path)

    assert prover_installer._find_ergoai_binary() is None


def test_prover_installer_discovers_release_runergo(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    fake_binary = tmp_path / "Coherent" / "ERGOAI_3.0" / "ErgoAI" / "runergo"
    fake_binary.parent.mkdir(parents=True)
    fake_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake_binary.parent / ".ergo_paths").write_text(
        "PROLOG=/usr/bin/false\n",
        encoding="utf-8",
    )
    fake_binary.chmod(0o755)
    monkeypatch.delenv("ERGOAI_BINARY", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR", str(tmp_path))

    assert prover_installer._find_ergoai_binary() == fake_binary


def test_ergoai_release_installer_runs_noninteractive(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    calls = []
    fake_binary = tmp_path / "Coherent" / "ERGOAI_3.0" / "ErgoAI" / "runergo"

    def fake_download(url, destination, **_kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        return True

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        fake_binary.parent.mkdir(parents=True)
        fake_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fake_binary.parent / ".ergo_paths").write_text(
            "PROLOG=/usr/bin/false\n",
            encoding="utf-8",
        )
        return 0

    monkeypatch.delenv("ERGOAI_BINARY", raising=False)
    monkeypatch.setenv("IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR", str(tmp_path))
    monkeypatch.setattr(prover_installer.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        prover_installer,
        "_which",
        lambda name: "/bin/sh" if name == "sh" else None,
    )
    monkeypatch.setattr(prover_installer, "_download_file", fake_download)
    monkeypatch.setattr(prover_installer, "_run", fake_run)

    assert prover_installer._install_ergoai_release(strict=True) is True
    assert os.environ["ERGOAI_BINARY"] == str(fake_binary)
    assert calls[0][0][-2:] == ["--", "noninteractive"]
    assert calls[0][1]["cwd"] == tmp_path
    monkeypatch.delenv("ERGOAI_BINARY", raising=False)


def test_platform_package_plan_uses_passwordless_sudo_for_apt():
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    profile = prover_installer.PlatformInstallProfile(
        system="linux",
        architecture="x86_64",
        package_manager="apt",
        package_manager_path="/usr/bin/apt-get",
        is_root=False,
        sudo_path="/usr/bin/sudo",
        passwordless_sudo=True,
    )

    install_cmd, update_cmd, mode = prover_installer._platform_install_command(
        profile,
        ["coq"],
        allow_sudo=False,
    )

    assert mode == "passwordless sudo"
    assert update_cmd == ["/usr/bin/sudo", "-n", "/usr/bin/apt-get", "update"]
    assert install_cmd == [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/apt-get",
        "install",
        "-y",
        "coq",
    ]


def test_platform_package_plan_uses_homebrew_without_sudo():
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    profile = prover_installer.PlatformInstallProfile(
        system="darwin",
        architecture="arm64",
        package_manager="brew",
        package_manager_path="/opt/homebrew/bin/brew",
        is_root=False,
        sudo_path=None,
        passwordless_sudo=False,
    )

    install_cmd, update_cmd, mode = prover_installer._platform_install_command(
        profile,
        ["coq"],
        allow_sudo=False,
    )

    assert mode == "homebrew"
    assert update_cmd is None
    assert install_cmd == ["/opt/homebrew/bin/brew", "install", "coq"]


def test_platform_system_install_runs_update_and_install(monkeypatch):
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    profile = prover_installer.PlatformInstallProfile(
        system="linux",
        architecture="aarch64",
        package_manager="apt",
        package_manager_path="/usr/bin/apt-get",
        is_root=True,
        sudo_path=None,
        passwordless_sudo=False,
    )
    commands = []

    monkeypatch.setattr(prover_installer, "detect_platform_install_profile", lambda: profile)
    monkeypatch.setattr(
        prover_installer,
        "_run",
        lambda cmd, **_kwargs: commands.append(cmd) or 0,
    )

    assert prover_installer._install_system_packages(
        ["git", "make"],
        reason="ErgoAI/ErgoEngine build",
        allow_sudo=False,
        strict=True,
    )
    assert commands == [
        ["/usr/bin/apt-get", "update"],
        ["/usr/bin/apt-get", "install", "-y", "git", "make"],
    ]


def test_ergoai_install_attempts_platform_build_dependencies(monkeypatch):
    from ipfs_datasets_py.logic.integration.bridges import prover_installer

    profile = prover_installer.PlatformInstallProfile(
        system="linux",
        architecture="aarch64",
        package_manager="apt",
        package_manager_path="/usr/bin/apt-get",
        is_root=True,
        sudo_path=None,
        passwordless_sudo=False,
    )
    installed = []

    monkeypatch.delenv("ERGOAI_BINARY", raising=False)
    monkeypatch.setattr(prover_installer, "_find_ergoai_binary", lambda: None)
    monkeypatch.setattr(prover_installer, "_run_custom_ergoai_installer", lambda **_kwargs: False)
    monkeypatch.setattr(prover_installer, "detect_platform_install_profile", lambda: profile)
    monkeypatch.setattr(
        prover_installer,
        "_install_system_packages",
        lambda packages, **_kwargs: installed.extend(packages) or True,
    )
    monkeypatch.setattr(prover_installer, "_install_ergoai_release", lambda **_kwargs: False)
    monkeypatch.setattr(prover_installer, "_clone_or_update_ergoai", lambda **_kwargs: False)

    assert prover_installer.ensure_ergoai(yes=True, strict=False) is False
    assert "git" in installed
    assert "make" in installed


# ---------------------------------------------------------------------------
# FLogicFrame
# ---------------------------------------------------------------------------


class TestFLogicFrame:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.flogic_types import FLogicFrame
        self.FLogicFrame = FLogicFrame

    def test_to_ergo_string_no_methods(self):
        f = self.FLogicFrame("obj1")
        assert f.to_ergo_string() == "obj1"

    def test_to_ergo_string_scalar(self):
        f = self.FLogicFrame("obj1", scalar_methods={"age": "30"})
        s = f.to_ergo_string()
        assert "obj1[" in s
        assert "age -> 30" in s

    def test_to_ergo_string_set_method(self):
        f = self.FLogicFrame("proj", set_methods={"member": ["alice", "bob"]})
        s = f.to_ergo_string()
        assert "member ->>" in s
        assert "alice" in s
        assert "bob" in s

    def test_to_ergo_string_isa(self):
        f = self.FLogicFrame("rex", isa="Dog")
        s = f.to_ergo_string()
        assert ": Dog" in s

    def test_dataclass_defaults(self):
        f = self.FLogicFrame("x")
        assert f.scalar_methods == {}
        assert f.set_methods == {}
        assert f.isa is None
        assert f.isaset == []


# ---------------------------------------------------------------------------
# FLogicClass
# ---------------------------------------------------------------------------


class TestFLogicClass:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.flogic_types import FLogicClass
        self.FLogicClass = FLogicClass

    def test_to_ergo_string_subclass(self):
        cls = self.FLogicClass("Dog", superclasses=["Animal"])
        s = cls.to_ergo_string()
        assert "Dog :: Animal." in s

    def test_to_ergo_string_signature(self):
        cls = self.FLogicClass("Person", signature_methods={"age": "integer"})
        s = cls.to_ergo_string()
        assert "Person[age => integer]." in s

    def test_no_superclasses(self):
        cls = self.FLogicClass("Root")
        assert cls.to_ergo_string() == ""


# ---------------------------------------------------------------------------
# FLogicOntology
# ---------------------------------------------------------------------------


class TestFLogicOntology:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.flogic_types import (
            FLogicClass,
            FLogicFrame,
            FLogicOntology,
        )
        self.FLogicClass = FLogicClass
        self.FLogicFrame = FLogicFrame
        self.FLogicOntology = FLogicOntology

    def test_to_ergo_program_empty(self):
        onto = self.FLogicOntology("test")
        assert onto.to_ergo_program() == ""

    def test_to_ergo_program_full(self):
        onto = self.FLogicOntology("animals")
        onto.classes.append(self.FLogicClass("Animal"))
        onto.classes.append(self.FLogicClass("Dog", superclasses=["Animal"]))
        onto.frames.append(
            self.FLogicFrame("rex", scalar_methods={"name": '"Rex"'}, isa="Dog")
        )
        onto.rules.append("?X[barks -> true] :- ?X : Dog.")
        prog = onto.to_ergo_program()
        assert "Dog :: Animal." in prog
        assert 'rex[name -> "Rex"] : Dog.' in prog
        assert "barks -> true" in prog


# ---------------------------------------------------------------------------
# FLogicQuery
# ---------------------------------------------------------------------------


class TestFLogicQuery:
    def test_default_status(self):
        from ipfs_datasets_py.logic.flogic.flogic_types import (
            FLogicQuery,
            FLogicStatus,
        )
        q = FLogicQuery(goal="?X : Dog")
        assert q.status == FLogicStatus.UNKNOWN
        assert q.bindings == []
        assert q.error_message is None


# ---------------------------------------------------------------------------
# ErgoAIWrapper (simulation mode)
# ---------------------------------------------------------------------------


class TestErgoAIWrapperSimulation:
    def setup_method(self):
        from ipfs_datasets_py.logic.flogic.ergoai_wrapper import ErgoAIWrapper
        from ipfs_datasets_py.logic.flogic.flogic_types import (
            FLogicClass,
            FLogicFrame,
            FLogicOntology,
            FLogicStatus,
        )
        self.ErgoAIWrapper = ErgoAIWrapper
        self.FLogicClass = FLogicClass
        self.FLogicFrame = FLogicFrame
        self.FLogicOntology = FLogicOntology
        self.FLogicStatus = FLogicStatus

    def _make_wrapper(self):
        # Force simulation mode without invoking opt-in lazy installers.
        return self.ErgoAIWrapper(
            binary=Path("/__missing_ipfs_datasets_py_ergoai__"),
            lazy_install=False,
        )

    def test_simulation_mode_flag(self):
        ergo = self._make_wrapper()
        assert ergo.simulation_mode is True

    def test_add_class_and_frame(self):
        ergo = self._make_wrapper()
        ergo.add_class(self.FLogicClass("Animal"))
        ergo.add_class(self.FLogicClass("Dog", superclasses=["Animal"]))
        ergo.add_frame(
            self.FLogicFrame("rex", scalar_methods={"name": '"Rex"'}, isa="Dog")
        )
        stats = ergo.get_statistics()
        assert stats["classes"] == 2
        assert stats["frames"] == 1

    def test_query_returns_unknown_in_simulation(self):
        ergo = self._make_wrapper()
        result = ergo.query("?X : Dog")
        assert result.status == self.FLogicStatus.UNKNOWN
        assert result.error_message is not None

    def test_batch_query(self):
        ergo = self._make_wrapper()
        results = ergo.batch_query(["?X : Dog", "?Y : Cat"])
        assert len(results) == 2
        for r in results:
            assert r.status == self.FLogicStatus.UNKNOWN

    def test_add_rule(self):
        ergo = self._make_wrapper()
        ergo.add_rule("?X[barks -> true] :- ?X : Dog.")
        assert ergo.get_statistics()["rules"] == 1

    def test_lazy_installer_can_resolve_missing_ergoai_binary(self, tmp_path, monkeypatch):
        import ipfs_datasets_py.logic.external_provers.lazy_installer as lazy_installer
        import ipfs_datasets_py.logic.flogic.ergoai_wrapper as ergoai_wrapper

        fake_binary = tmp_path / "runErgo.sh"
        fake_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (tmp_path / ".ergo_paths").write_text(
            "PROLOG=/usr/bin/false\n",
            encoding="utf-8",
        )
        fake_binary.chmod(0o755)
        calls = []

        def fake_find_ergo_binary():
            env_path = os.environ.get("ERGOAI_BINARY")
            return Path(env_path) if env_path else None

        def fake_lazy_install(prover_name, **kwargs):
            calls.append((prover_name, kwargs))
            monkeypatch.setenv("ERGOAI_BINARY", str(fake_binary))
            return True

        monkeypatch.delenv("ERGOAI_BINARY", raising=False)
        monkeypatch.setattr(ergoai_wrapper, "_find_ergo_binary", fake_find_ergo_binary)
        monkeypatch.setattr(lazy_installer, "lazy_install_prover", fake_lazy_install)

        ergo = ergoai_wrapper.ErgoAIWrapper(lazy_install=True)

        assert ergo.simulation_mode is False
        assert ergo.binary == fake_binary
        assert calls
        assert calls[0][0] == "ergoai"

    def test_wrapper_discovers_repo_runergo(self, tmp_path, monkeypatch):
        import ipfs_datasets_py.logic.flogic.ergoai_wrapper as ergoai_wrapper

        fake_binary = tmp_path / "ErgoAI" / "runergo"
        fake_binary.parent.mkdir()
        fake_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fake_binary.parent / ".ergo_paths").write_text(
            "PROLOG=/usr/bin/false\n",
            encoding="utf-8",
        )
        fake_binary.chmod(0o755)
        monkeypatch.delenv("ERGOAI_BINARY", raising=False)
        monkeypatch.setenv("IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR", str(tmp_path / "release"))
        monkeypatch.setattr(ergoai_wrapper, "ERGOAI_SUBMODULE_PATH", tmp_path)

        assert ergoai_wrapper.resolve_ergo_binary(lazy_install=False) == fake_binary

    def test_wrapper_discovers_release_runergo(self, tmp_path, monkeypatch):
        import ipfs_datasets_py.logic.flogic.ergoai_wrapper as ergoai_wrapper

        fake_binary = tmp_path / "Coherent" / "ERGOAI_3.0" / "ErgoAI" / "runergo"
        fake_binary.parent.mkdir(parents=True)
        fake_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (fake_binary.parent / ".ergo_paths").write_text(
            "PROLOG=/usr/bin/false\n",
            encoding="utf-8",
        )
        fake_binary.chmod(0o755)
        monkeypatch.delenv("ERGOAI_BINARY", raising=False)
        monkeypatch.setenv("IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR", str(tmp_path))

        assert ergoai_wrapper.resolve_ergo_binary(lazy_install=False) == fake_binary

    def test_wrapper_skips_unconfigured_repo_runergo(self, tmp_path, monkeypatch):
        import ipfs_datasets_py.logic.flogic.ergoai_wrapper as ergoai_wrapper

        fake_binary = tmp_path / "ErgoAI" / "runergo"
        fake_binary.parent.mkdir()
        fake_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_binary.chmod(0o755)
        monkeypatch.delenv("ERGOAI_BINARY", raising=False)
        monkeypatch.setenv("IPFS_DATASETS_PY_ERGOAI_INSTALL_DIR", str(tmp_path / "release"))
        monkeypatch.setattr(ergoai_wrapper, "ERGOAI_SUBMODULE_PATH", tmp_path)

        assert ergoai_wrapper.resolve_ergo_binary(lazy_install=False) is None

    def test_wrapper_feeds_load_command_to_ergo_runner(self, tmp_path):
        runner = tmp_path / "runergo"
        stdin_capture = tmp_path / "stdin.txt"
        argc_capture = tmp_path / "argc.txt"
        runner.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$#\" > '{argc_capture}'\n"
            f"cat > '{stdin_capture}'\n"
            "printf '%s\\n' '?X = rex'\n",
            encoding="utf-8",
        )
        runner.chmod(0o755)
        (tmp_path / ".ergo_paths").write_text(
            "PROLOG=/usr/bin/false\n",
            encoding="utf-8",
        )

        ergo = self.ErgoAIWrapper(binary=runner, lazy_install=False)
        ergo.add_frame(self.FLogicFrame("rex", isa="Dog"))
        result = ergo.query("?X : Dog")

        assert result.status == self.FLogicStatus.SUCCESS
        assert result.bindings == [{"?X": "rex"}]
        assert argc_capture.read_text(encoding="utf-8").strip() == "0"
        stdin_text = stdin_capture.read_text(encoding="utf-8")
        assert "load{'" in stdin_text
        assert "?X : Dog." in stdin_text
        assert "\\halt." in stdin_text

    def test_ergo_output_parser_ignores_timing_lines(self):
        import ipfs_datasets_py.logic.flogic.ergoai_wrapper as ergoai_wrapper

        output = (
            "Times (in seconds): elapsed = 0.420; pure CPU = 0.346\n"
            "?X = rex\n"
            "1 solution(s) in 0.000 seconds; elapsed time = 0.001\n"
        )

        assert ergoai_wrapper._parse_ergo_output(output) == [{"?X": "rex"}]

    def test_load_ontology(self):
        ergo = self._make_wrapper()
        onto = self.FLogicOntology("animals")
        onto.classes.append(self.FLogicClass("Animal"))
        ergo.load_ontology(onto)
        assert ergo.ontology.name == "animals"
        assert ergo.get_statistics()["classes"] == 1

    def test_get_program(self):
        ergo = self._make_wrapper()
        ergo.add_class(self.FLogicClass("Dog", superclasses=["Animal"]))
        ergo.add_frame(self.FLogicFrame("rex", isa="Dog"))
        prog = ergo.get_program()
        assert "Dog :: Animal." in prog
        assert "rex" in prog

    def test_get_statistics_keys(self):
        ergo = self._make_wrapper()
        stats = ergo.get_statistics()
        assert "ontology_name" in stats
        assert "simulation_mode" in stats
        assert "ergoai_binary" in stats
        assert stats["ergoai_binary"] is None


# ---------------------------------------------------------------------------
# ERGOAI_AVAILABLE module-level constant
# ---------------------------------------------------------------------------


def test_ergoai_available_is_bool():
    from ipfs_datasets_py.logic.flogic.ergoai_wrapper import ERGOAI_AVAILABLE

    assert isinstance(ERGOAI_AVAILABLE, bool)


def test_ergoai_submodule_path_is_path():
    from ipfs_datasets_py.logic.flogic.ergoai_wrapper import ERGOAI_SUBMODULE_PATH

    assert isinstance(ERGOAI_SUBMODULE_PATH, Path)


# ---------------------------------------------------------------------------
# Package-level lazy imports
# ---------------------------------------------------------------------------


def test_flogic_package_exports():
    import ipfs_datasets_py.logic.flogic as flogic

    expected = {
        "ErgoAIWrapper",
        "ERGOAI_AVAILABLE",
        "ERGOAI_SUBMODULE_PATH",
        "FLogicStatus",
        "FLogicFrame",
        "FLogicClass",
        "FLogicQuery",
        "FLogicOntology",
    }
    for name in expected:
        assert hasattr(flogic, name), f"flogic missing export: {name}"


def test_flogic_import_is_quiet():
    """Importing the flogic package must not emit warnings."""
    import warnings

    root = "ipfs_datasets_py.logic.flogic"
    for key in list(sys.modules.keys()):
        if key == root or key.startswith(root + "."):
            del sys.modules[key]

    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        import ipfs_datasets_py.logic.flogic  # noqa: F401

    ipfs_warns = [
        w for w in rec if "ipfs_datasets_py" in (getattr(w, "filename", "") or "")
    ]
    assert ipfs_warns == [], [str(w.message) for w in ipfs_warns]


# ---------------------------------------------------------------------------
# FLogicSemanticOptimizer
# ---------------------------------------------------------------------------


class TestFLogicSemanticOptimizer:
    def setup_method(self):
        mod = _load_flogic_optimizer()
        self.FLogicOptimizerConfig = mod.FLogicOptimizerConfig
        self.FLogicSemanticOptimizer = mod.FLogicSemanticOptimizer

    def _optimizer(self, threshold=0.80):
        cfg = self.FLogicOptimizerConfig(similarity_threshold=threshold)
        return self.FLogicSemanticOptimizer(config=cfg)

    def test_identical_embeddings_pass(self):
        opt = self._optimizer(threshold=0.85)
        emb = [0.1, 0.2, 0.3]
        result = opt.evaluate("src", "decoded", emb, emb)
        assert abs(result.similarity_score - 1.0) < 1e-9
        assert result.passed is True
        assert result.ontology_consistent is True

    def test_orthogonal_embeddings_fail(self):
        opt = self._optimizer(threshold=0.5)
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        result = opt.evaluate("src", "decoded", a, b)
        assert abs(result.similarity_score) < 1e-9
        assert result.passed is False

    def test_kg_triples_consistent(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            kg_triples=[
                {"subject": "dog1", "predicate": "type", "object": "Dog"},
                {"subject": "dog1", "predicate": "name", "object": "Rex"},
            ],
        )
        assert result.ontology_consistent is True
        assert result.violations == []

    def test_kg_triples_empty_predicate_violation(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            kg_triples=[{"subject": "x", "predicate": "", "object": "y"}],
        )
        assert result.ontology_consistent is False
        assert len(result.violations) >= 1
        assert result.passed is False

    def test_add_ontology_class(self):
        opt = self._optimizer()
        opt.add_ontology_class("Animal")
        opt.add_ontology_class("Dog", superclasses=["Animal"])
        stats = opt.get_statistics()
        assert stats["ergoai"]["classes"] == 2

    def test_get_statistics_no_ergo(self):
        opt = self._optimizer()
        stats = opt.get_statistics()
        assert "similarity_threshold" in stats
        assert "ergoai" not in stats  # not yet initialised

    def test_default_config(self):
        mod = _load_flogic_optimizer()
        FLogicOptimizerConfig = mod.FLogicOptimizerConfig
        FLogicSemanticOptimizer = mod.FLogicSemanticOptimizer

        opt = FLogicSemanticOptimizer()
        assert opt.config.similarity_threshold == 0.80
        assert opt.config.check_ontology_consistency is True

    def test_dimension_mismatch_raises(self):
        mod = _load_flogic_optimizer()
        FLogicSemanticOptimizer = mod.FLogicSemanticOptimizer

        opt = FLogicSemanticOptimizer()
        with pytest.raises(ValueError, match="dimension mismatch"):
            opt.evaluate("a", "b", [1.0, 2.0], [1.0, 2.0, 3.0])

    def test_result_metadata(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate("hello", "world", emb, emb)
        assert result.metadata["source_text"] == "hello"
        assert result.metadata["decoded_text"] == "world"
        assert result.metadata["frame_ontology_term_count"] == 0
        assert result.metadata["frame_ontology_terms"] == []
        assert "threshold" in result.metadata

    def test_result_metadata_tracks_frame_ontology_terms(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            kg_triples=[
                {
                    "subject": "doc-1",
                    "predicate": "candidate_ontology_term",
                    "object": "notice",
                },
                {
                    "subject": "doc-1",
                    "predicate": "selected_ontology_term",
                    "object": "agency",
                },
            ],
        )
        assert result.metadata["frame_ontology_term_count"] == 2
        assert result.metadata["frame_ontology_terms"] == ["agency", "notice"]

    def test_result_metadata_tracks_frame_ontology_terms_from_feature_keys(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            frame_feature_keys=[
                "slot:selected_frame:administrative_notice_hearing",
                "frame_term:agency notice",
                "selected_frame_term:Final Order",
            ],
        )
        assert result.metadata["frame_ontology_term_count"] == 3
        assert result.metadata["frame_ontology_terms"] == [
            "administrative_notice_hearing",
            "agency_notice",
            "final_order",
        ]
        assert result.metadata["frame_ontology_terms_from_feature_keys_count"] == 3
        assert result.metadata["frame_ontology_terms_from_feature_keys"] == [
            "administrative_notice_hearing",
            "agency_notice",
            "final_order",
        ]
        assert result.metadata["frame_ontology_terms_from_triples_count"] == 0
        assert result.metadata["frame_ontology_terms_from_triples"] == []

    def test_result_metadata_tracks_slot_normalized_source_id_terms_from_feature_keys(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            frame_feature_keys=[
                "slot:source_id:us_code_54_102701_171f636b98d4b36b",
                "slot:source_id:us_code_2_31a_2b_119e8839f18f02be",
            ],
        )
        assert result.metadata["frame_ontology_term_count"] == 2
        assert result.metadata["frame_ontology_terms"] == [
            "2_31a_2b",
            "54_102701",
        ]
        assert result.metadata["frame_ontology_terms_from_feature_keys_count"] == 2
        assert result.metadata["frame_ontology_terms_from_feature_keys"] == [
            "2_31a_2b",
            "54_102701",
        ]

    def test_result_metadata_tracks_frame_ontology_terms_from_frame_cues(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            frame_feature_keys=[
                "cue:frame:Frame:authority",
                "cue:frame:Frame:part of",
                "cue:deontic:O:must",
            ],
        )
        assert result.metadata["frame_ontology_term_count"] == 2
        assert result.metadata["frame_ontology_terms"] == [
            "authority",
            "part",
        ]
        assert result.metadata["frame_ontology_terms_from_feature_keys_count"] == 2
        assert result.metadata["frame_ontology_terms_from_feature_keys"] == [
            "authority",
            "part",
        ]

    def test_result_metadata_normalizes_frame_ontology_terms(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            kg_triples=[
                {
                    "subject": "doc-1",
                    "predicate": "candidate_ontology_term",
                    "object": "Final Order",
                },
                {
                    "subject": "doc-1",
                    "predicate": "selected_ontology_term",
                    "object": "final_order",
                },
                {
                    "subject": "doc-1",
                    "predicate": "interpreted_in_frame_term",
                    "object": "and",
                },
            ],
        )
        assert result.metadata["frame_ontology_term_count"] == 1
        assert result.metadata["frame_ontology_terms"] == ["final_order"]

    def test_result_metadata_tracks_frame_ontology_frame_predicates(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            kg_triples=[
                {
                    "subject": "doc-1",
                    "predicate": "candidate_ontology_frame",
                    "object": "administrative_notice_hearing",
                },
                {
                    "subject": "doc-1",
                    "predicate": "selected_ontology_frame",
                    "object": "administrative_notice_hearing",
                },
            ],
        )
        assert result.metadata["frame_ontology_term_count"] == 1
        assert result.metadata["frame_ontology_terms"] == ["administrative_notice_hearing"]
        assert result.metadata["frame_ontology_terms_from_feature_keys_count"] == 0
        assert result.metadata["frame_ontology_terms_from_feature_keys"] == []
        assert result.metadata["frame_ontology_terms_from_triples_count"] == 1
        assert result.metadata["frame_ontology_terms_from_triples"] == [
            "administrative_notice_hearing"
        ]

    def test_result_metadata_tracks_contextual_flogic_terms_from_triples(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            kg_triples=[
                {
                    "subject": "doc-1",
                    "predicate": "condition",
                    "object": "unless written notice is provided",
                },
                {
                    "subject": "doc-1",
                    "predicate": "predicate_argument",
                    "object": "actor:agency",
                },
                {
                    "subject": "doc-1",
                    "predicate": "modal_cue",
                    "object": "may",
                },
                {
                    "subject": "doc-1",
                    "predicate": "source_id",
                    "object": "us-code-5-552-deadbeefdeadbeef",
                },
            ],
        )
        assert result.metadata["frame_ontology_term_count"] == 4
        assert result.metadata["frame_ontology_terms"] == [
            "5_552",
            "actor_agency",
            "may",
            "unless_written_notice_provided",
        ]
        assert result.metadata["frame_ontology_terms_from_feature_keys_count"] == 0
        assert result.metadata["frame_ontology_terms_from_feature_keys"] == []
        assert result.metadata["frame_ontology_terms_from_triples_count"] == 4
        assert result.metadata["frame_ontology_terms_from_triples"] == [
            "5_552",
            "actor_agency",
            "may",
            "unless_written_notice_provided",
        ]

    def test_result_metadata_tracks_fallback_surface_text_terms_from_triples(self):
        opt = self._optimizer()
        emb = [1.0, 0.0]
        result = opt.evaluate(
            "src",
            "decoded",
            emb,
            emb,
            kg_triples=[
                {
                    "subject": "doc-1",
                    "predicate": "fallback_surface_text",
                    "object": "Housing voucher benefits and utility allowances",
                },
                {
                    "subject": "doc-1",
                    "predicate": "fallback_surface_text_token_suffix",
                    "object": "allowances",
                },
            ],
        )

        assert result.metadata["frame_ontology_terms_from_feature_keys_count"] == 0
        assert result.metadata["frame_ontology_terms_from_feature_keys"] == []
        assert result.metadata["frame_ontology_terms_from_triples_count"] == 2
        assert result.metadata["frame_ontology_terms_from_triples"] == [
            "allowances",
            "housing_voucher_benefits_utility_allowances",
        ]
        assert result.metadata["frame_ontology_term_count"] == 2
        assert result.metadata["frame_ontology_terms"] == [
            "allowances",
            "housing_voucher_benefits_utility_allowances",
        ]
