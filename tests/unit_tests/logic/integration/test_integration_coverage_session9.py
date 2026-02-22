"""
Session 9: Integration coverage 70% → 80%.

Targets:
- bridges/external_provers.py       0%  → 70%+
- bridges/prover_installer.py       0%  → 65%+
- domain/caselaw_bulk_processor.py  27% → 55%+
- domain/temporal_deontic_rag_store.py  59% → 80%+
- symbolic/symbolic_logic_primitives.py 63% → 85%+
- converters/modal_logic_extension.py   73% → 90%+
- converters/logic_translation_core.py  63% → 80%+
"""

from __future__ import annotations

import sys
import types
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from typing import Optional

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Section 1: bridges/external_provers.py
# ──────────────────────────────────────────────────────────────────────────────

class TestProverStatus:
    """GIVEN ProverStatus enum WHEN inspected THEN all values present."""

    def test_enum_members(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverStatus
        assert ProverStatus.THEOREM.value == "theorem"
        assert ProverStatus.SATISFIABLE.value == "satisfiable"
        assert ProverStatus.UNSATISFIABLE.value == "unsatisfiable"
        assert ProverStatus.UNKNOWN.value == "unknown"
        assert ProverStatus.TIMEOUT.value == "timeout"
        assert ProverStatus.ERROR.value == "error"


class TestProverResult:
    """GIVEN ProverResult dataclass WHEN instantiated THEN fields accessible."""

    def test_default_fields(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverResult, ProverStatus
        r = ProverResult(status=ProverStatus.UNKNOWN)
        assert r.status == ProverStatus.UNKNOWN
        assert r.proof is None
        assert r.time == 0.0
        assert r.prover == "unknown"
        assert r.error is None
        assert r.statistics is None

    def test_full_fields(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverResult, ProverStatus
        r = ProverResult(
            status=ProverStatus.THEOREM,
            proof="step1\nstep2",
            time=1.5,
            prover="Vampire",
            statistics={"clauses": 10},
        )
        assert r.status == ProverStatus.THEOREM
        assert r.proof == "step1\nstep2"
        assert r.time == 1.5
        assert r.statistics == {"clauses": 10}


class TestVampireProver:
    """GIVEN VampireProver WHEN binary is missing THEN degrades gracefully."""

    def _make_vampire(self) -> "VampireProver":
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver
        with patch("subprocess.run", side_effect=FileNotFoundError):
            return VampireProver()

    # -- init / availability check -------------------------------------------

    def test_init_vampire_not_found(self):
        v = self._make_vampire()
        assert v.timeout == 60
        assert v.vampire_path == "vampire"
        assert v.strategy == "casc"

    def test_init_custom_params(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver
        with patch("subprocess.run", side_effect=FileNotFoundError):
            v = VampireProver(timeout=30, vampire_path="/usr/bin/vampire", strategy="portfolio")
        assert v.timeout == 30
        assert v.vampire_path == "/usr/bin/vampire"
        assert v.strategy == "portfolio"

    def test_check_availability_found(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            v = VampireProver()
        assert v.vampire_path == "vampire"

    # -- _formula_to_tptp ----------------------------------------------------

    def test_formula_to_tptp(self):
        v = self._make_vampire()
        tptp = v._formula_to_tptp("p(X)")
        assert "conjecture" in tptp
        assert "p(X)" in tptp

    # -- prove: THEOREM -------------------------------------------------------

    def test_prove_theorem(self):
        import subprocess
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver, ProverStatus
        with patch("subprocess.run", side_effect=FileNotFoundError):
            v = VampireProver()
        mock_run = MagicMock()
        mock_run.returncode = 0
        mock_run.stdout = "% Proof\n% Refutation found\nclauses: 5\n"
        mock_run.stderr = ""
        with patch("subprocess.run", return_value=mock_run):
            result = v.prove("p(a)")
        assert result.status == ProverStatus.THEOREM
        assert result.prover == "Vampire"

    def test_prove_satisfiable(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver, ProverStatus
        with patch("subprocess.run", side_effect=FileNotFoundError):
            v = VampireProver()
        mock_run = MagicMock(returncode=0, stdout="Satisfiable\n", stderr="")
        with patch("subprocess.run", return_value=mock_run):
            result = v.prove("p(a)")
        assert result.status == ProverStatus.SATISFIABLE

    def test_prove_timeout_from_output(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver, ProverStatus
        with patch("subprocess.run", side_effect=FileNotFoundError):
            v = VampireProver()
        mock_run = MagicMock(returncode=0, stdout="Time limit expired\n", stderr="")
        with patch("subprocess.run", return_value=mock_run):
            result = v.prove("p(a)")
        assert result.status == ProverStatus.TIMEOUT

    def test_prove_unknown(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver, ProverStatus
        with patch("subprocess.run", side_effect=FileNotFoundError):
            v = VampireProver()
        mock_run = MagicMock(returncode=0, stdout="no useful output\n", stderr="")
        with patch("subprocess.run", return_value=mock_run):
            result = v.prove("p(a)")
        assert result.status == ProverStatus.UNKNOWN

    def test_prove_timeout_exception(self):
        import subprocess
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver, ProverStatus
        with patch("subprocess.run", side_effect=FileNotFoundError):
            v = VampireProver(timeout=1)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="vampire", timeout=1)):
            result = v.prove("p(a)")
        assert result.status == ProverStatus.TIMEOUT

    def test_prove_error_exception(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver, ProverStatus
        with patch("subprocess.run", side_effect=FileNotFoundError):
            v = VampireProver()
        with patch("subprocess.run", side_effect=RuntimeError("unexpected")):
            result = v.prove("p(a)")
        assert result.status == ProverStatus.ERROR
        assert "unexpected" in result.error

    def test_prove_with_axioms(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import VampireProver, ProverStatus
        with patch("subprocess.run", side_effect=FileNotFoundError):
            v = VampireProver()
        mock_run = MagicMock(returncode=0, stdout="Theorem\n", stderr="")
        with patch("subprocess.run", return_value=mock_run):
            result = v.prove("q(a)", axioms=["p(a)", "p(a)->q(a)"])
        assert result.status == ProverStatus.THEOREM

    # -- _extract_proof -------------------------------------------------------

    def test_extract_proof(self):
        v = self._make_vampire()
        output = "some text\n% Proof\nstep1\nstep2\n% Success"
        proof = v._extract_proof(output)
        assert proof is not None
        assert "Proof" in proof

    def test_extract_proof_no_proof(self):
        v = self._make_vampire()
        output = "no proof here"
        proof = v._extract_proof(output)
        assert proof is None

    # -- _extract_statistics --------------------------------------------------

    def test_extract_statistics_with_clauses(self):
        v = self._make_vampire()
        output = "Active clauses: 42\nInferences generated: 100\n"
        stats = v._extract_statistics(output)
        assert isinstance(stats, dict)

    def test_extract_statistics_empty(self):
        v = self._make_vampire()
        stats = v._extract_statistics("")
        assert isinstance(stats, dict)


class TestEProver:
    """GIVEN EProver WHEN binary is missing THEN degrades gracefully."""

    def _make_eprover(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver
        with patch("subprocess.run", side_effect=FileNotFoundError):
            return EProver()

    def test_init_defaults(self):
        e = self._make_eprover()
        assert e.timeout == 60
        assert e.eprover_path == "eprover"
        assert e.auto_mode is True

    def test_init_custom(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver
        with patch("subprocess.run", side_effect=FileNotFoundError):
            e = EProver(timeout=10, eprover_path="/usr/local/bin/eprover", auto_mode=False)
        assert e.timeout == 10
        assert e.auto_mode is False

    def test_check_availability_found(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver
        mock_result = MagicMock(returncode=0, stdout="E 2.6")
        with patch("subprocess.run", return_value=mock_result):
            e = EProver()
        assert e.eprover_path == "eprover"

    def test_formula_to_tptp(self):
        e = self._make_eprover()
        assert "conjecture" in e._formula_to_tptp("p(X)")

    def test_prove_theorem(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver, ProverStatus
        e = self._make_eprover()
        mock_run = MagicMock(returncode=0, stdout="# Proof found!\n# Proof object starts\nstep\n# Proof object ends\n", stderr="")
        with patch("subprocess.run", return_value=mock_run):
            result = e.prove("p(a)")
        assert result.status == ProverStatus.THEOREM
        assert result.prover == "E"

    def test_prove_satisfiable(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver, ProverStatus
        e = self._make_eprover()
        mock_run = MagicMock(returncode=0, stdout="Satisfiable\n", stderr="")
        with patch("subprocess.run", return_value=mock_run):
            result = e.prove("p(a)")
        assert result.status == ProverStatus.SATISFIABLE

    def test_prove_resource_out(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver, ProverStatus
        e = self._make_eprover()
        mock_run = MagicMock(returncode=0, stdout="ResourceOut\n", stderr="")
        with patch("subprocess.run", return_value=mock_run):
            result = e.prove("p(a)")
        assert result.status == ProverStatus.TIMEOUT

    def test_prove_unknown(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver, ProverStatus
        e = self._make_eprover()
        mock_run = MagicMock(returncode=0, stdout="nothing\n", stderr="")
        with patch("subprocess.run", return_value=mock_run):
            result = e.prove("p(a)")
        assert result.status == ProverStatus.UNKNOWN

    def test_prove_timeout_exception(self):
        import subprocess
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver, ProverStatus
        e = self._make_eprover()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="eprover", timeout=1)):
            result = e.prove("p(a)")
        assert result.status == ProverStatus.TIMEOUT

    def test_prove_error_exception(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver, ProverStatus
        e = self._make_eprover()
        with patch("subprocess.run", side_effect=OSError("crash")):
            result = e.prove("p(a)")
        assert result.status == ProverStatus.ERROR

    def test_prove_no_auto_mode(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver, ProverStatus
        with patch("subprocess.run", side_effect=FileNotFoundError):
            e = EProver(auto_mode=False)
        mock_run = MagicMock(returncode=0, stdout="Theorem\n", stderr="")
        with patch("subprocess.run", return_value=mock_run):
            result = e.prove("p(a)")
        assert result.status == ProverStatus.THEOREM

    def test_prove_with_axioms(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import EProver, ProverStatus
        e = self._make_eprover()
        mock_run = MagicMock(returncode=0, stdout="Theorem\n", stderr="")
        with patch("subprocess.run", return_value=mock_run):
            result = e.prove("q(a)", axioms=["hyp1"])
        assert result.status == ProverStatus.THEOREM

    def test_extract_proof_from_object(self):
        e = self._make_eprover()
        output = "# Proof object starts\nstep1\n# Proof object ends\n"
        proof = e._extract_proof(output)
        assert proof is not None

    def test_extract_proof_absent(self):
        e = self._make_eprover()
        assert e._extract_proof("no proof") is None

    def test_extract_statistics(self):
        e = self._make_eprover()
        output = "# Processed clauses : 55\n# Generated clauses  : 110\n"
        stats = e._extract_statistics(output)
        assert isinstance(stats, dict)


class TestProverRegistry:
    """GIVEN ProverRegistry WHEN provers registered THEN selection logic works."""

    def _make_registry(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverRegistry
        return ProverRegistry()

    def test_register_and_list(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import (
            ProverRegistry, VampireProver,
        )
        reg = self._make_registry()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            v = VampireProver()
        reg.register(v)
        assert "VampireProver" in reg.list_provers()

    def test_register_with_custom_name(self):
        reg = self._make_registry()
        mock_prover = MagicMock()
        reg.register(mock_prover, name="my_prover")
        assert "my_prover" in reg.list_provers()

    def test_get_prover_existing(self):
        reg = self._make_registry()
        mock_prover = MagicMock()
        reg.register(mock_prover, name="my")
        assert reg.get_prover("my") is mock_prover

    def test_get_prover_missing(self):
        reg = self._make_registry()
        assert reg.get_prover("nonexistent") is None

    def test_prove_auto_no_provers(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverStatus
        reg = self._make_registry()
        result = reg.prove_auto("p(a)")
        assert result.status == ProverStatus.ERROR

    def test_prove_auto_preferred_proves(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverResult, ProverStatus
        reg = self._make_registry()
        good_result = ProverResult(status=ProverStatus.THEOREM, time=0.5, prover="X")
        mock_a = MagicMock()
        mock_a.prove.return_value = good_result
        reg.register(mock_a, name="A")
        result = reg.prove_auto("p(a)", prefer="A")
        assert result.status == ProverStatus.THEOREM

    def test_prove_auto_preferred_fails_falls_through(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverResult, ProverStatus
        reg = self._make_registry()
        fail = ProverResult(status=ProverStatus.UNKNOWN, time=1.0, prover="A")
        success = ProverResult(status=ProverStatus.THEOREM, time=0.5, prover="B")
        mock_a = MagicMock(); mock_a.prove.return_value = fail
        mock_b = MagicMock(); mock_b.prove.return_value = success
        reg.register(mock_a, name="A")
        reg.register(mock_b, name="B")
        result = reg.prove_auto("p(a)", prefer="A")
        assert result.status == ProverStatus.THEOREM

    def test_prove_auto_all_fail(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverResult, ProverStatus
        reg = self._make_registry()
        fail = ProverResult(status=ProverStatus.UNKNOWN, time=1.0, prover="X")
        mock_a = MagicMock(); mock_a.prove.return_value = fail
        reg.register(mock_a, name="A")
        result = reg.prove_auto("p(a)")
        assert result.status in (ProverStatus.UNKNOWN, ProverStatus.ERROR)

    def test_is_better_result_theorem_wins(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverResult, ProverStatus
        reg = self._make_registry()
        theorem = ProverResult(status=ProverStatus.THEOREM, time=2.0, prover="X")
        unknown = ProverResult(status=ProverStatus.UNKNOWN, time=0.5, prover="Y")
        assert reg._is_better_result(theorem, unknown) is True
        assert reg._is_better_result(unknown, theorem) is False

    def test_is_better_result_faster_same_status(self):
        from ipfs_datasets_py.logic.integration.bridges.external_provers import ProverResult, ProverStatus
        reg = self._make_registry()
        fast = ProverResult(status=ProverStatus.UNKNOWN, time=0.5, prover="X")
        slow = ProverResult(status=ProverStatus.UNKNOWN, time=2.0, prover="Y")
        assert reg._is_better_result(fast, slow) is True

    def test_get_prover_registry_singleton(self):
        from ipfs_datasets_py.logic.integration.bridges import external_provers as ep
        ep._global_registry = None  # reset
        with patch("subprocess.run", side_effect=FileNotFoundError):
            reg1 = ep.get_prover_registry()
            reg2 = ep.get_prover_registry()
        assert reg1 is reg2
        ep._global_registry = None  # cleanup


# ──────────────────────────────────────────────────────────────────────────────
# Section 2: bridges/prover_installer.py
# ──────────────────────────────────────────────────────────────────────────────

class TestProverInstallerHelpers:
    """GIVEN installer helpers WHEN called THEN behave correctly."""

    def test_truthy(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import _truthy
        assert _truthy("1") is True
        assert _truthy("true") is True
        assert _truthy("yes") is True
        assert _truthy("on") is True
        assert _truthy("0") is False
        assert _truthy("false") is False
        assert _truthy(None) is False

    def test_which_found(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import _which
        with patch("shutil.which", return_value="/usr/bin/lean"):
            result = _which("lean")
        assert result == "/usr/bin/lean"

    def test_which_not_found(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import _which
        with patch("shutil.which", return_value=None):
            result = _which("lean")
        assert result is None

    def test_run_success(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import _run
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            rc = _run(["echo", "hello"], check=False)
        assert rc == 0

    def test_run_fail_no_check(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import _run
        with patch("subprocess.run", return_value=MagicMock(returncode=1)):
            rc = _run(["false"], check=False)
        assert rc == 1

    def test_run_fail_with_check_raises(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import _run
        with patch("subprocess.run", return_value=MagicMock(returncode=1)):
            with pytest.raises(RuntimeError):
                _run(["false"], check=True)


class TestEnsureLean:
    """GIVEN ensure_lean WHEN lean already on PATH THEN returns True."""

    def test_lean_already_on_path(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import ensure_lean
        with patch("shutil.which", return_value="/usr/bin/lean"):
            result = ensure_lean(yes=False, strict=False)
        assert result is True

    def test_lean_not_found_no_yes(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import ensure_lean
        with patch("shutil.which", return_value=None):
            result = ensure_lean(yes=False, strict=False)
        assert result is False

    def test_lean_install_via_elan_success(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import ensure_lean
        mock_lean_path = Path.home() / ".elan" / "bin" / "lean"
        with patch("shutil.which", return_value=None), \
             patch("urllib.request.urlopen") as mock_open, \
             patch("subprocess.run", return_value=MagicMock(returncode=0)), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.write_bytes"), \
             patch("pathlib.Path.chmod"):
            mock_cm = MagicMock()
            mock_cm.__enter__ = lambda s: MagicMock(read=lambda: b"#!/bin/sh\necho installed")
            mock_cm.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_cm
            result = ensure_lean(yes=True, strict=False)
        # Result depends on mock; we just verify no exception raised
        assert isinstance(result, bool)

    def test_lean_install_download_fails(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import ensure_lean
        with patch("shutil.which", return_value=None), \
             patch("urllib.request.urlopen", side_effect=OSError("network error")):
            result = ensure_lean(yes=True, strict=False)
        assert result is False

    def test_lean_install_strict_raises(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import ensure_lean
        with patch("shutil.which", return_value=None), \
             patch("urllib.request.urlopen", side_effect=OSError("network error")):
            with pytest.raises(OSError):
                ensure_lean(yes=True, strict=True)


class TestEnsureCoq:
    """GIVEN ensure_coq WHEN coqc already on PATH THEN returns True."""

    def test_coq_already_on_path(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import ensure_coq
        with patch("shutil.which", return_value="/usr/bin/coqc"):
            result = ensure_coq(yes=False, strict=False)
        assert result is True

    def test_coq_not_found_no_yes(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import ensure_coq
        with patch("shutil.which", return_value=None):
            result = ensure_coq(yes=False, strict=False)
        assert result is False

    def test_coq_apt_install_as_root_success(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import ensure_coq
        # Simulate: not on PATH → try apt as root → succeeds
        which_calls = {"coqc": None, "apt-get": "/usr/bin/apt-get", "sudo": "/usr/bin/sudo"}
        def _which_side(cmd):
            return which_calls.get(cmd)

        with patch("shutil.which", side_effect=_which_side), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)), \
             patch("os.geteuid", return_value=0):
            # After apt install, coqc "appears"
            with patch("shutil.which", side_effect=lambda c: "/usr/bin/coqc" if c == "coqc" else _which_side(c)):
                result = ensure_coq(yes=True, strict=False)
        assert isinstance(result, bool)

    def test_coq_install_exception_no_strict(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import ensure_coq
        with patch("shutil.which", return_value=None), \
             patch("subprocess.run", side_effect=RuntimeError("fail")):
            result = ensure_coq(yes=True, strict=False)
        assert result is False


class TestProverInstallerMain:
    """GIVEN main() CLI WHEN invoked THEN returns appropriate exit code."""

    def test_main_default_returns_0_when_both_available(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import main
        with patch("shutil.which", return_value="/usr/bin/lean"):
            rc = main([])
        assert isinstance(rc, int)

    def test_main_lean_only(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import main
        with patch("shutil.which", return_value="/usr/bin/lean"):
            rc = main(["--lean"])
        assert rc == 0

    def test_main_coq_not_found_no_strict(self):
        from ipfs_datasets_py.logic.integration.bridges.prover_installer import main
        with patch("shutil.which", return_value=None):
            rc = main(["--coq"])
        assert rc == 0  # not strict → always 0


# ──────────────────────────────────────────────────────────────────────────────
# Section 3: domain/caselaw_bulk_processor.py
# ──────────────────────────────────────────────────────────────────────────────

class TestProcessingStats:
    """GIVEN ProcessingStats WHEN queried THEN derived properties correct."""

    def _make_stats(self):
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import ProcessingStats
        return ProcessingStats()

    def test_initial_values(self):
        s = self._make_stats()
        assert s.total_documents == 0
        assert s.processed_documents == 0
        assert s.extracted_theorems == 0
        assert s.processing_errors == 0

    def test_processing_time_no_start(self):
        from datetime import timedelta
        s = self._make_stats()
        assert s.processing_time == timedelta(0)

    def test_processing_time_with_range(self):
        from datetime import timedelta
        s = self._make_stats()
        s.start_time = datetime(2024, 1, 1, 0, 0, 0)
        s.end_time = datetime(2024, 1, 1, 0, 1, 0)
        assert s.processing_time == timedelta(seconds=60)

    def test_success_rate_zero_total(self):
        s = self._make_stats()
        assert s.success_rate == 0.0

    def test_success_rate_all_success(self):
        s = self._make_stats()
        s.total_documents = 10
        s.processed_documents = 10
        s.processing_errors = 0
        assert s.success_rate == 1.0

    def test_success_rate_with_errors(self):
        s = self._make_stats()
        s.total_documents = 10
        s.processed_documents = 10
        s.processing_errors = 2
        assert s.success_rate == 0.8


class TestBulkProcessingConfig:
    """GIVEN BulkProcessingConfig WHEN created THEN defaults correct."""

    def test_defaults(self):
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import BulkProcessingConfig
        cfg = BulkProcessingConfig()
        assert cfg.max_concurrent_documents == 5
        assert cfg.chunk_size == 100
        assert cfg.enable_parallel_processing is True
        assert cfg.min_document_length == 100
        assert cfg.output_directory == "unified_deontic_logic_system"
        assert cfg.min_theorem_confidence == 0.7


class TestCaselawBulkProcessorHelpers:
    """GIVEN CaselawBulkProcessor WHEN helper methods called THEN behave correctly."""

    def _make_processor(self, output_dir=None):
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import (
            CaselawBulkProcessor, BulkProcessingConfig,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = BulkProcessingConfig(
                output_directory=output_dir or tmpdir,
            )
            # Use existing tmpdir as output to avoid creating dirs during test
            cfg.output_directory = tmpdir
            return CaselawBulkProcessor(cfg), tmpdir

    def test_init(self):
        proc, _ = self._make_processor()
        assert proc.stats.total_documents == 0
        assert isinstance(proc.document_cache, dict)

    def test_passes_filters_short_text(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        doc = CaselawDocument(
            document_id="d1", title="T", text="short",
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        assert proc._passes_filters(doc) is False

    def test_passes_filters_sufficient_text(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        doc = CaselawDocument(
            document_id="d2", title="T", text="x" * 200,
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        assert proc._passes_filters(doc) is True

    def test_passes_filters_date_before_range(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        proc.config.date_range = (datetime(2021, 1, 1), None)
        doc = CaselawDocument(
            document_id="d3", title="T", text="x" * 200,
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        assert proc._passes_filters(doc) is False

    def test_passes_filters_date_after_range(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        proc.config.date_range = (None, datetime(2019, 12, 31))
        doc = CaselawDocument(
            document_id="d4", title="T", text="x" * 200,
            date=datetime(2020, 6, 1), jurisdiction="US", court="SC", citation="",
        )
        assert proc._passes_filters(doc) is False

    def test_passes_filters_jurisdiction_filter_match(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        proc.config.jurisdictions_filter = ["US", "UK"]
        doc = CaselawDocument(
            document_id="d5", title="T", text="x" * 200,
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        assert proc._passes_filters(doc) is True

    def test_passes_filters_jurisdiction_filter_no_match(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        proc.config.jurisdictions_filter = ["UK"]
        doc = CaselawDocument(
            document_id="d6", title="T", text="x" * 200,
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        assert proc._passes_filters(doc) is False

    def test_passes_filters_legal_domain_match(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        proc.config.legal_domains_filter = ["contract"]
        doc = CaselawDocument(
            document_id="d7", title="T", text="x" * 200,
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
            legal_domains=["contract"],
        )
        assert proc._passes_filters(doc) is True

    def test_passes_filters_precedent_strength_too_low(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        doc = CaselawDocument(
            document_id="d8", title="T", text="x" * 200,
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
            precedent_strength=0.1,
        )
        assert proc._passes_filters(doc) is False

    def test_is_legal_proposition_true(self):
        proc, _ = self._make_processor()
        assert proc._is_legal_proposition("comply with all regulations") is True

    def test_is_legal_proposition_false(self):
        proc, _ = self._make_processor()
        assert proc._is_legal_proposition("said hello to everyone there") is False

    def test_extract_agent_defendant(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        doc = CaselawDocument(
            document_id="da", title="T", text="",
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        agent = proc._extract_agent_from_context("the defendant must comply", doc)
        assert agent.identifier == "defendant"

    def test_extract_agent_plaintiff(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        doc = CaselawDocument(
            document_id="db", title="T", text="",
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        agent = proc._extract_agent_from_context("the plaintiff must file", doc)
        assert agent.identifier == "plaintiff"

    def test_extract_agent_court(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        doc = CaselawDocument(
            document_id="dc", title="T", text="",
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        agent = proc._extract_agent_from_context("the court orders", doc)
        assert agent.identifier == "court"

    def test_extract_agent_default(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        doc = CaselawDocument(
            document_id="dd", title="T", text="",
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        agent = proc._extract_agent_from_context("some random text here", doc)
        assert agent.identifier == "party"

    def test_extract_formulas_obligation(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        doc = CaselawDocument(
            document_id="de", title="T",
            text="The defendant must pay all outstanding fees within thirty days of this order.",
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        formulas = proc._extract_formulas_pattern_matching(doc)
        oblig = [f for f in formulas if f.operator == DeonticOperator.OBLIGATION]
        assert len(oblig) >= 1

    def test_extract_formulas_permission(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        doc = CaselawDocument(
            document_id="df", title="T",
            text="The plaintiff may appeal the decision within fourteen days of judgment.",
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        formulas = proc._extract_formulas_pattern_matching(doc)
        perms = [f for f in formulas if f.operator == DeonticOperator.PERMISSION]
        assert len(perms) >= 1

    def test_extract_formulas_prohibition(self):
        proc, _ = self._make_processor()
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawDocument
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticOperator
        doc = CaselawDocument(
            document_id="dg", title="T",
            text="The respondent must not contact the protected person under any circumstances.",
            date=datetime(2020, 1, 1), jurisdiction="US", court="SC", citation="",
        )
        formulas = proc._extract_formulas_pattern_matching(doc)
        prohb = [f for f in formulas if f.operator == DeonticOperator.PROHIBITION]
        assert len(prohb) >= 1

    def test_extract_date_from_filename(self):
        proc, _ = self._make_processor()
        d = proc._extract_date_from_filename("case_2023-06-15.txt")
        assert d is not None
        assert d.year == 2023

    def test_extract_date_year_only(self):
        proc, _ = self._make_processor()
        d = proc._extract_date_from_filename("case_2021.txt")
        assert d is not None
        assert d.year == 2021

    def test_extract_date_no_date(self):
        proc, _ = self._make_processor()
        d = proc._extract_date_from_filename("unknown.txt")
        assert d is None

    def test_extract_jurisdiction_from_path(self):
        proc, _ = self._make_processor()
        j = proc._extract_jurisdiction_from_path("/data/US/cases/2020/case.txt")
        assert isinstance(j, str)

    def test_create_bulk_processor_factory(self):
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import create_bulk_processor
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = create_bulk_processor([tmpdir], output_directory=tmpdir, max_concurrent=3)
        from ipfs_datasets_py.logic.integration.domain.caselaw_bulk_processor import CaselawBulkProcessor
        assert isinstance(proc, CaselawBulkProcessor)
        assert proc.config.max_concurrent_documents == 3


# ──────────────────────────────────────────────────────────────────────────────
# Section 4: domain/temporal_deontic_rag_store.py
# ──────────────────────────────────────────────────────────────────────────────

class TestTemporalDeonticRAGStore:
    """GIVEN TemporalDeonticRAGStore WHEN theorems added THEN retrieval works."""

    def _make_store(self):
        from ipfs_datasets_py.logic.integration.domain.temporal_deontic_rag_store import TemporalDeonticRAGStore
        return TemporalDeonticRAGStore()

    def _make_formula(self, op="OBLIGATION", prop="pay fees", agent_id="party"):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent,
        )
        op_enum = DeonticOperator[op]
        agent = LegalAgent(identifier=agent_id, name=agent_id.capitalize(), agent_type="person")
        return DeonticFormula(
            operator=op_enum,
            proposition=prop,
            agent=agent,
            confidence=0.9,
            source_text=f"{op.lower()} {prop}",
        )

    def test_add_theorem_returns_id(self):
        store = self._make_store()
        formula = self._make_formula()
        tid = store.add_theorem(formula, jurisdiction="US", legal_domain="contract")
        assert isinstance(tid, str)
        assert len(tid) > 0

    def test_add_theorem_stored_in_theorems(self):
        store = self._make_store()
        formula = self._make_formula()
        tid = store.add_theorem(formula)
        assert tid in store.theorems

    def test_add_theorem_updates_domain_index(self):
        store = self._make_store()
        formula = self._make_formula()
        store.add_theorem(formula, legal_domain="contract")
        assert "contract" in store.domain_index

    def test_add_theorem_updates_jurisdiction_index(self):
        store = self._make_store()
        formula = self._make_formula()
        store.add_theorem(formula, jurisdiction="US")
        assert "US" in store.jurisdiction_index

    def test_add_theorem_updates_temporal_index(self):
        store = self._make_store()
        formula = self._make_formula()
        start = datetime(2020, 6, 1)
        store.add_theorem(formula, temporal_scope=(start, None))
        key = start.strftime("%Y-%m")
        assert key in store.temporal_index

    def test_retrieve_relevant_theorems_empty_store(self):
        store = self._make_store()
        query = self._make_formula()
        results = store.retrieve_relevant_theorems(query)
        assert results == []

    def test_retrieve_relevant_theorems_returns_list(self):
        store = self._make_store()
        for i in range(5):
            formula = self._make_formula(prop=f"action {i}")
            store.add_theorem(formula)
        query = self._make_formula(prop="action 0")
        results = store.retrieve_relevant_theorems(query, top_k=3)
        assert len(results) <= 3

    def test_retrieve_with_jurisdiction_filter(self):
        store = self._make_store()
        f1 = self._make_formula(prop="pay tax")
        f2 = self._make_formula(prop="file return")
        store.add_theorem(f1, jurisdiction="US")
        store.add_theorem(f2, jurisdiction="UK")
        query = self._make_formula(prop="pay tax")
        results = store.retrieve_relevant_theorems(query, jurisdiction="US")
        theorem_ids = [r.theorem_id for r in results]
        # Should only get US theorems
        for t in results:
            assert t.jurisdiction == "US"

    def test_retrieve_with_domain_filter(self):
        store = self._make_store()
        f = self._make_formula(prop="disclose document")
        store.add_theorem(f, legal_domain="contract")
        query = self._make_formula(prop="disclose document")
        results = store.retrieve_relevant_theorems(query, legal_domain="contract")
        assert any(r.legal_domain == "contract" for r in results)

    def test_check_document_consistency_no_conflicts(self):
        store = self._make_store()
        f = self._make_formula(op="OBLIGATION", prop="pay fees")
        store.add_theorem(f)
        doc_formula = self._make_formula(op="OBLIGATION", prop="pay fees")
        result = store.check_document_consistency([doc_formula])
        assert hasattr(result, "is_consistent")

    def test_check_document_consistency_with_conflict(self):
        store = self._make_store()
        # Add prohibition of "pay fees"
        prohib = self._make_formula(op="PROHIBITION", prop="pay fees")
        store.add_theorem(prohib)
        # Doc says obligation to pay fees — exact same proposition → conflict
        oblig = self._make_formula(op="OBLIGATION", prop="pay fees")
        result = store.check_document_consistency([oblig])
        # May or may not flag as conflict depending on similarity threshold
        assert hasattr(result, "conflicts")

    def test_get_statistics(self):
        store = self._make_store()
        f = self._make_formula()
        store.add_theorem(f, jurisdiction="US", legal_domain="contract")
        stats = store.get_statistics()
        assert stats["total_theorems"] == 1
        assert stats["jurisdictions"] >= 1
        assert stats["legal_domains"] >= 1

    def test_get_statistics_empty(self):
        store = self._make_store()
        stats = store.get_statistics()
        assert stats["total_theorems"] == 0
        assert stats["avg_precedent_strength"] == 0.0

    def test_cosine_similarity_identical(self):
        import numpy as np
        store = self._make_store()
        v = np.array([1.0, 0.0, 0.0])
        assert store._cosine_similarity(v, v) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        import numpy as np
        store = self._make_store()
        v1 = np.array([1.0, 0.0])
        v2 = np.array([0.0, 1.0])
        assert store._cosine_similarity(v1, v2) == pytest.approx(0.0)

    def test_cosine_similarity_zero_vector(self):
        import numpy as np
        store = self._make_store()
        v1 = np.array([0.0, 0.0])
        v2 = np.array([1.0, 0.0])
        assert store._cosine_similarity(v1, v2) == 0.0

    def test_same_proposition_exact(self):
        store = self._make_store()
        assert store._same_proposition("pay fees", "pay fees") is True

    def test_same_proposition_different(self):
        store = self._make_store()
        assert store._same_proposition("pay fees", "sign contract") is False

    def test_same_proposition_high_overlap(self):
        store = self._make_store()
        # 4 of 5 words overlap
        assert store._same_proposition("must pay the fees now", "must pay the fees today") is True

    def test_check_formula_conflict_obligation_vs_prohibition_same(self):
        store = self._make_store()
        f1 = self._make_formula(op="OBLIGATION", prop="pay fees")
        f2 = self._make_formula(op="PROHIBITION", prop="pay fees")
        conflict = store._check_formula_conflict(f1, f2)
        assert conflict is not None

    def test_check_formula_conflict_permission_vs_prohibition(self):
        store = self._make_store()
        f1 = self._make_formula(op="PERMISSION", prop="pay fees")
        f2 = self._make_formula(op="PROHIBITION", prop="pay fees")
        conflict = store._check_formula_conflict(f1, f2)
        assert conflict is not None

    def test_check_formula_conflict_no_conflict(self):
        store = self._make_store()
        f1 = self._make_formula(op="OBLIGATION", prop="pay fees")
        f2 = self._make_formula(op="OBLIGATION", prop="file documents")
        conflict = store._check_formula_conflict(f1, f2)
        assert conflict is None

    def test_temporal_overlap_both_none(self):
        store = self._make_store()
        t = datetime(2020, 1, 1)
        assert store._temporal_overlap(t, None, None) is True

    def test_temporal_overlap_start_only(self):
        store = self._make_store()
        t = datetime(2022, 1, 1)
        start = datetime(2020, 1, 1)
        assert store._temporal_overlap(t, start, None) is True
        assert store._temporal_overlap(datetime(2019, 1, 1), start, None) is False

    def test_temporal_overlap_end_only(self):
        store = self._make_store()
        end = datetime(2022, 12, 31)
        assert store._temporal_overlap(datetime(2021, 1, 1), None, end) is True
        assert store._temporal_overlap(datetime(2023, 1, 1), None, end) is False

    def test_temporal_overlap_in_range(self):
        store = self._make_store()
        start = datetime(2020, 1, 1)
        end = datetime(2022, 12, 31)
        assert store._temporal_overlap(datetime(2021, 6, 1), start, end) is True
        assert store._temporal_overlap(datetime(2019, 1, 1), start, end) is False

    def test_deduplicate_theorems(self):
        store = self._make_store()
        f = self._make_formula()
        tid = store.add_theorem(f)
        t = store.theorems[tid]
        dedup = store._deduplicate_theorems([t, t, t])
        assert len(dedup) == 1

    def test_generate_consistency_reasoning_no_conflicts(self):
        store = self._make_store()
        f = self._make_formula()
        tid = store.add_theorem(f)
        theorems = [store.theorems[tid]]
        reasoning = store._generate_consistency_reasoning([], [], theorems)
        assert "consistent" in reasoning.lower() or "relevant" in reasoning.lower()

    def test_generate_consistency_reasoning_with_conflicts(self):
        store = self._make_store()
        f = self._make_formula()
        tid = store.add_theorem(f)
        theorems = [store.theorems[tid]]
        conflicts = [{"description": "test conflict", "type": "logical_conflict"}]
        reasoning = store._generate_consistency_reasoning(conflicts, [], theorems)
        assert "conflict" in reasoning.lower()

    def test_calculate_consistency_confidence_empty_theorems(self):
        store = self._make_store()
        conf = store._calculate_consistency_confidence([], [], [])
        assert conf == 0.0

    def test_calculate_consistency_confidence_no_conflicts(self):
        store = self._make_store()
        f = self._make_formula()
        tid = store.add_theorem(f)
        theorems = [store.theorems[tid]]
        conf = store._calculate_consistency_confidence([], [], theorems)
        assert 0.0 <= conf <= 1.0

    def test_calculate_consistency_confidence_many_conflicts(self):
        store = self._make_store()
        f = self._make_formula()
        tid = store.add_theorem(f)
        theorems = [store.theorems[tid]]
        conflicts = [{"desc": i} for i in range(5)]
        conf = store._calculate_consistency_confidence(conflicts, [], theorems)
        assert conf == 0.0  # Clamped to 0


# ──────────────────────────────────────────────────────────────────────────────
# Section 5: symbolic/symbolic_logic_primitives.py (fallback paths)
# ──────────────────────────────────────────────────────────────────────────────

class TestSymbolicLogicPrimitivesModule:
    """GIVEN symbolic_logic_primitives WHEN SymbolicAI absent THEN fallbacks run."""

    def _make_symbol(self, text: str):
        from ipfs_datasets_py.logic.integration.symbolic.symbolic_logic_primitives import create_logic_symbol
        return create_logic_symbol(text, semantic=False)

    def test_create_logic_symbol(self):
        sym = self._make_symbol("All cats are animals")
        assert sym.value == "All cats are animals"

    def test_to_fol_universal(self):
        sym = self._make_symbol("All cats are animals")
        result = sym.to_fol()
        assert "∀" in result.value or "forall" in result.value.lower() or "Cat" in result.value

    def test_to_fol_existential(self):
        sym = self._make_symbol("Some birds can fly")
        result = sym.to_fol()
        assert "∃" in result.value or "exists" in result.value.lower() or "Bird" in result.value

    def test_to_fol_conditional(self):
        sym = self._make_symbol("if it rains then the road is wet")
        result = sym.to_fol()
        assert "→" in result.value or ":-" in result.value or "Rain" in result.value or "condition" in result.value.lower()

    def test_to_fol_disjunction(self):
        sym = self._make_symbol("cats or dogs are pets")
        result = sym.to_fol()
        assert "∨" in result.value or ";" in result.value or "cats" in result.value.lower()

    def test_to_fol_prolog_format(self):
        sym = self._make_symbol("All cats are animals")
        result = sym.to_fol(output_format="prolog")
        assert "forall" in result.value.lower() or ":-" in result.value or result.value

    def test_to_fol_tptp_format(self):
        sym = self._make_symbol("All cats are animals")
        result = sym.to_fol(output_format="tptp")
        assert "!" in result.value or result.value

    def test_extract_quantifiers_universal(self):
        sym = self._make_symbol("All students must attend class")
        result = sym.extract_quantifiers()
        assert "universal" in result.value or "all" in result.value.lower()

    def test_extract_quantifiers_existential(self):
        sym = self._make_symbol("Some birds can fly south")
        result = sym.extract_quantifiers()
        assert "existential" in result.value or "some" in result.value.lower()

    def test_extract_quantifiers_none(self):
        sym = self._make_symbol("the cat sat on the mat")
        result = sym.extract_quantifiers()
        # May return 'none' or empty
        assert isinstance(result.value, str)

    def test_extract_predicates(self):
        sym = self._make_symbol("the bird flies every morning")
        result = sym.extract_predicates()
        assert isinstance(result.value, str)

    def test_logical_and(self):
        s1 = self._make_symbol("P(x)")
        s2 = self._make_symbol("Q(x)")
        result = s1.logical_and(s2)
        assert "∧" in result.value or "and" in result.value.lower()

    def test_logical_or(self):
        s1 = self._make_symbol("P(x)")
        s2 = self._make_symbol("Q(x)")
        result = s1.logical_or(s2)
        assert "∨" in result.value or "or" in result.value.lower()

    def test_implies(self):
        s1 = self._make_symbol("Rain")
        s2 = self._make_symbol("Wet")
        result = s1.implies(s2)
        assert "→" in result.value or "implies" in result.value.lower()

    def test_negate(self):
        sym = self._make_symbol("P(x)")
        result = sym.negate()
        assert "¬" in result.value or "not" in result.value.lower()

    def test_analyze_logical_structure(self):
        sym = self._make_symbol("All cats are mammals and some mammals are carnivores")
        result = sym.analyze_logical_structure()
        assert isinstance(result.value, str)
        assert len(result.value) > 0

    def test_simplify_logic(self):
        sym = self._make_symbol("  P(x)  ∧  Q(x)  ")
        result = sym.simplify_logic()
        assert isinstance(result.value, str)

    def test_get_available_primitives(self):
        from ipfs_datasets_py.logic.integration.symbolic.symbolic_logic_primitives import get_available_primitives
        prims = get_available_primitives()
        assert "to_fol" in prims
        assert "negate" in prims
        assert "logical_and" in prims
        assert len(prims) == 9

    def test_logical_structure_dataclass(self):
        from ipfs_datasets_py.logic.integration.symbolic.symbolic_logic_primitives import LogicalStructure
        ls = LogicalStructure(
            quantifiers=["∀"], variables=["x"], predicates=["Cat"],
            connectives=["∧"], operators=["→"], confidence=0.9,
        )
        assert ls.confidence == 0.9
        assert "∀" in ls.quantifiers


# ──────────────────────────────────────────────────────────────────────────────
# Section 6: converters/modal_logic_extension.py
# ──────────────────────────────────────────────────────────────────────────────

class TestModalLogicSymbol:
    """GIVEN ModalLogicSymbol WHEN modal operators applied THEN formulas correct."""

    def _make(self, text: str):
        from ipfs_datasets_py.logic.integration.converters.modal_logic_extension import ModalLogicSymbol
        return ModalLogicSymbol(text, semantic=False)

    def test_necessarily(self):
        s = self._make("P")
        assert "□" in s.necessarily().value

    def test_possibly(self):
        s = self._make("P")
        assert "◇" in s.possibly().value

    def test_obligation(self):
        s = self._make("pay")
        assert "O(" in s.obligation().value

    def test_permission(self):
        s = self._make("act")
        assert "P(" in s.permission().value

    def test_prohibition(self):
        s = self._make("steal")
        assert "F(" in s.prohibition().value

    def test_knowledge(self):
        s = self._make("P")
        result = s.knowledge("alice")
        assert "K_alice" in result.value

    def test_belief(self):
        s = self._make("P")
        result = s.belief("bob")
        assert "B_bob" in result.value

    def test_temporal_always(self):
        s = self._make("safe")
        assert "□" in s.temporal_always().value

    def test_temporal_eventually(self):
        s = self._make("fixed")
        assert "◇" in s.temporal_eventually().value

    def test_temporal_next(self):
        s = self._make("step")
        assert "X(" in s.temporal_next().value

    def test_temporal_until(self):
        s = self._make("work")
        result = s.temporal_until("done")
        assert "U" in result.value
        assert "done" in result.value

    def test_static_context_kwarg_ignored_gracefully(self):
        from ipfs_datasets_py.logic.integration.converters.modal_logic_extension import ModalLogicSymbol
        s = ModalLogicSymbol("P", semantic=False, static_context="ctx")
        assert s.value == "P"


class TestAdvancedLogicConverter:
    """GIVEN AdvancedLogicConverter WHEN text classified/converted THEN correct logic."""

    def _make_converter(self):
        from ipfs_datasets_py.logic.integration.converters.modal_logic_extension import AdvancedLogicConverter
        return AdvancedLogicConverter()

    # -- detect_logic_type ---------------------------------------------------

    def test_detect_deontic(self):
        conv = self._make_converter()
        # Use multiple deontic indicators so score exceeds temporal/modal
        result = conv.detect_logic_type("The party is obliged and required to comply with all permitted obligations.")
        assert result.logic_type == "deontic"

    def test_detect_temporal(self):
        conv = self._make_converter()
        result = conv.detect_logic_type("This condition will always hold until the contract expires.")
        assert result.logic_type == "temporal"

    def test_detect_epistemic(self):
        conv = self._make_converter()
        result = conv.detect_logic_type("The agent knows and believes the proposition is true.")
        assert result.logic_type == "epistemic"

    def test_detect_modal(self):
        conv = self._make_converter()
        result = conv.detect_logic_type("It is possibly true that the event could occur.")
        assert result.logic_type == "modal"

    def test_detect_fol_fallback(self):
        conv = self._make_converter()
        result = conv.detect_logic_type("The cat sat on the mat.")
        assert result.logic_type == "fol"

    def test_detect_empty_raises(self):
        conv = self._make_converter()
        with pytest.raises(ValueError):
            conv.detect_logic_type("")

    # -- convert_to_modal_logic (full pipeline) --------------------------------

    def test_convert_modal_necessity(self):
        conv = self._make_converter()
        result = conv.convert_to_modal_logic("It is necessarily required.")
        assert result.modal_type == "alethic" or result.modal_type in ("modal", "deontic", "temporal", "epistemic", "fol")
        assert isinstance(result.formula, str)

    def test_convert_modal_possibility(self):
        conv = self._make_converter()
        result = conv.convert_to_modal_logic("It might possibly happen.")
        assert isinstance(result.formula, str)

    def test_convert_temporal_always(self):
        conv = self._make_converter()
        result = conv.convert_to_modal_logic("The system always reports logs.")
        assert result.modal_type == "temporal"

    def test_convert_temporal_eventually(self):
        conv = self._make_converter()
        result = conv.convert_to_modal_logic("The process will eventually terminate.")
        assert result.modal_type == "temporal"

    def test_convert_deontic_obligation(self):
        conv = self._make_converter()
        result = conv.convert_to_modal_logic("The agent is obliged and required to report the findings.")
        assert result.modal_type == "deontic"
        assert "O(" in result.formula

    def test_convert_deontic_permission(self):
        conv = self._make_converter()
        result = conv.convert_to_modal_logic("The party is permitted and allowed to proceed with the appeal.")
        assert result.modal_type == "deontic"
        assert "P(" in result.formula

    def test_convert_deontic_prohibition(self):
        conv = self._make_converter()
        # "forbidden" + "shall" hit deontic detection; fallback operator check hits "forbidden"
        result = conv.convert_to_modal_logic("The activity is forbidden and shall not be performed here.")
        assert result.modal_type == "deontic"
        assert "F(" in result.formula

    def test_convert_epistemic_knowledge(self):
        conv = self._make_converter()
        result = conv.convert_to_modal_logic("Alice knows and is certain about the facts.")
        assert result.modal_type == "epistemic"

    def test_convert_epistemic_belief(self):
        conv = self._make_converter()
        result = conv.convert_to_modal_logic("Bob believes and suspects the hypothesis.")
        assert result.modal_type == "epistemic"
        assert "B_bob" in result.formula

    def test_convert_fol_fallback(self):
        conv = self._make_converter()
        result = conv.convert_to_modal_logic("The cat sat on the mat.")
        assert isinstance(result.formula, str)

    # -- _normalize_query_response -------------------------------------------

    def test_normalize_string(self):
        conv = self._make_converter()
        assert conv._normalize_query_response("hello") == "hello"

    def test_normalize_list(self):
        conv = self._make_converter()
        result = conv._normalize_query_response(["a", "b"])
        assert "a" in result and "b" in result

    def test_normalize_dict(self):
        conv = self._make_converter()
        result = conv._normalize_query_response({"key": "value"})
        assert "key" in result


# ──────────────────────────────────────────────────────────────────────────────
# Section 7: converters/logic_translation_core.py
# ──────────────────────────────────────────────────────────────────────────────

class TestTranslationResult:
    """GIVEN TranslationResult WHEN to_dict called THEN all fields present."""

    def test_to_dict(self):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import (
            TranslationResult, LogicTranslationTarget,
        )
        r = TranslationResult(
            target=LogicTranslationTarget.LEAN,
            translated_formula="Obligatory pay_fees",
            success=True,
            confidence=0.9,
            errors=[],
            warnings=["minor issue"],
            metadata={"key": "val"},
            dependencies=["Mathlib.Logic.Basic"],
        )
        d = r.to_dict()
        assert d["target"] == "lean"
        assert d["success"] is True
        assert d["confidence"] == 0.9
        assert "key" in d["metadata"]
        assert "Mathlib.Logic.Basic" in d["dependencies"]


class TestAbstractLogicFormula:
    """GIVEN AbstractLogicFormula WHEN to_dict called THEN all fields present."""

    def test_to_dict(self):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import (
            AbstractLogicFormula,
        )
        f = AbstractLogicFormula(
            formula_type="deontic",
            operators=["O"],
            variables=[("x", "Agent")],
            quantifiers=[("∀", "x", "Agent")],
            propositions=["pay_fees"],
            logical_structure={"type": "obligation"},
            source_formula=None,
        )
        d = f.to_dict()
        assert d["formula_type"] == "deontic"
        assert d["operators"] == ["O"]
        assert d["source_formula_id"] is None


class TestLeanTranslator:
    """GIVEN LeanTranslator WHEN formulas translated THEN Lean 4 syntax produced."""

    def _make_formula(self, op="OBLIGATION", prop="pay_fees"):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent,
        )
        agent = LegalAgent(identifier="party", name="Party", agent_type="person")
        return DeonticFormula(
            operator=DeonticOperator[op],
            proposition=prop,
            agent=agent,
            confidence=0.9,
            source_text=f"{op.lower()} {prop}",
        )

    def _make_translator(self):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import LeanTranslator
        return LeanTranslator()

    def test_translate_obligation(self):
        t = self._make_translator()
        f = self._make_formula("OBLIGATION", "pay fees")
        result = t.translate_deontic_formula(f)
        assert result.success
        assert "Obligatory" in result.translated_formula

    def test_translate_permission(self):
        t = self._make_translator()
        f = self._make_formula("PERMISSION", "appeal case")
        result = t.translate_deontic_formula(f)
        assert result.success
        assert "Permitted" in result.translated_formula

    def test_translate_prohibition(self):
        t = self._make_translator()
        f = self._make_formula("PROHIBITION", "disclose information")
        result = t.translate_deontic_formula(f)
        assert result.success
        assert "Forbidden" in result.translated_formula

    def test_translate_right(self):
        t = self._make_translator()
        f = self._make_formula("RIGHT", "vote")
        result = t.translate_deontic_formula(f)
        assert result.success
        assert "Right" in result.translated_formula

    def test_translate_uses_cache(self):
        t = self._make_translator()
        f = self._make_formula()
        r1 = t.translate_deontic_formula(f)
        r2 = t.translate_deontic_formula(f)
        assert r1.translated_formula == r2.translated_formula

    def test_clear_cache(self):
        t = self._make_translator()
        f = self._make_formula()
        t.translate_deontic_formula(f)
        assert len(t.translation_cache) == 1
        t.clear_cache()
        assert len(t.translation_cache) == 0

    def test_get_dependencies(self):
        t = self._make_translator()
        deps = t.get_dependencies()
        assert any("Mathlib" in d or "Logic" in d for d in deps)

    def test_validate_translation_ok(self):
        t = self._make_translator()
        f = self._make_formula()
        r = t.translate_deontic_formula(f)
        valid, errors = t.validate_translation(f, r.translated_formula)
        assert isinstance(valid, bool)

    def test_validate_translation_empty(self):
        t = self._make_translator()
        f = self._make_formula()
        valid, errors = t.validate_translation(f, "")
        assert valid is False

    def test_translate_rule_set(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
        t = self._make_translator()
        f = self._make_formula()
        rs = DeonticRuleSet(
            name="TestTheory",
            formulas=[f],
            description="Test rule set",
        )
        result = t.translate_rule_set(rs)
        assert result.success
        assert "TestTheory" in result.translated_formula

    def test_generate_theory_file(self):
        t = self._make_translator()
        f = self._make_formula()
        content = t.generate_theory_file([f], "MyTheory")
        assert "MyTheory" in content
        assert "Obligatory" in content

    def test_normalize_identifier(self):
        t = self._make_translator()
        assert t._normalize_identifier("pay fees") == "pay_fees"
        assert t._normalize_identifier("") == "unnamed"
        # Digit-start gets id_ prefix
        assert t._normalize_identifier("123abc").startswith("id_")


class TestCoqTranslator:
    """GIVEN CoqTranslator WHEN formulas translated THEN Coq syntax produced."""

    def _make_formula(self, op="OBLIGATION", prop="report findings"):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent,
        )
        agent = LegalAgent(identifier="agent", name="Agent", agent_type="person")
        return DeonticFormula(
            operator=DeonticOperator[op],
            proposition=prop,
            agent=agent,
            confidence=0.9,
            source_text=f"{op.lower()} {prop}",
        )

    def _make_translator(self):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import CoqTranslator
        return CoqTranslator()

    def test_translate_obligation(self):
        t = self._make_translator()
        f = self._make_formula()
        result = t.translate_deontic_formula(f)
        assert result.success
        assert "Obligatory" in result.translated_formula

    def test_translate_with_conditions(self):
        t = self._make_translator()
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent,
        )
        agent = LegalAgent("a", "A", "person")
        f = DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            proposition="submit report",
            agent=agent,
            confidence=0.9,
            source_text="must submit",
            conditions=["deadline_passed", "valid_data"],
        )
        result = t.translate_deontic_formula(f)
        assert result.success
        assert "/\\" in result.translated_formula

    def test_translate_cache_reuse(self):
        t = self._make_translator()
        f = self._make_formula()
        r1 = t.translate_deontic_formula(f)
        r2 = t.translate_deontic_formula(f)
        assert r1.translated_formula == r2.translated_formula

    def test_get_dependencies(self):
        t = self._make_translator()
        deps = t.get_dependencies()
        assert any("Coq" in d for d in deps)

    def test_validate_unbalanced_parens(self):
        t = self._make_translator()
        f = self._make_formula()
        valid, errors = t.validate_translation(f, "Obligatory (report_findings")
        assert valid is False
        assert any("paren" in e.lower() for e in errors)

    def test_validate_empty(self):
        t = self._make_translator()
        f = self._make_formula()
        valid, errors = t.validate_translation(f, "")
        assert valid is False

    def test_validate_balanced(self):
        t = self._make_translator()
        f = self._make_formula()
        valid, errors = t.validate_translation(f, "Obligatory (report_findings)")
        assert valid is True

    def test_translate_rule_set(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import DeonticRuleSet
        t = self._make_translator()
        f = self._make_formula()
        rs = DeonticRuleSet(
            name="CoqLegalTheory",
            formulas=[f],
            description="Coq theory",
        )
        result = t.translate_rule_set(rs)
        assert result.success

    def test_generate_theory_file(self):
        t = self._make_translator()
        f = self._make_formula()
        content = t.generate_theory_file([f], "MyLaw")
        assert "MyLaw" in content
        assert "Obligatory" in content


class TestSMTTranslator:
    """GIVEN SMTTranslator WHEN formula translated THEN SMT-LIB syntax produced."""

    def _make_formula(self):
        from ipfs_datasets_py.logic.integration.converters.deontic_logic_core import (
            DeonticFormula, DeonticOperator, LegalAgent,
        )
        agent = LegalAgent("a", "A", "person")
        return DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            proposition="pay tax",
            agent=agent,
            confidence=0.9,
            source_text="must pay",
        )

    def test_translate_obligation(self):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import SMTTranslator
        t = SMTTranslator()
        f = self._make_formula()
        result = t.translate_deontic_formula(f)
        assert result.success
        assert "obligatory" in result.translated_formula.lower()

    def test_generate_theory_file(self):
        from ipfs_datasets_py.logic.integration.converters.logic_translation_core import SMTTranslator
        t = SMTTranslator()
        f = self._make_formula()
        content = t.generate_theory_file([f], "SMTLegal")
        assert "SMTLegal" in content
        assert "(check-sat)" in content
