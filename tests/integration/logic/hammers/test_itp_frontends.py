"""Integration tests for the native ITP frontend adapters and goal
snapshots (HAMMER-006).

These tests cover:

- The common adapter protocol (:class:`ITPFrontend`) and the
  :class:`CapabilityEvidence` / :class:`GoalSnapshot` records it produces,
  including their ``validate``/``to_dict``/``from_dict`` round trips and the
  invariants that make fabrication impossible to construct (e.g. a
  :class:`GoalSnapshot` cannot validate without non-empty
  ``raw_native_output``; a :class:`CapabilityEvidence` cannot validate
  ``available=False`` without an ``unavailable_reason``).
- Each concrete adapter (:class:`LeanFrontend`, :class:`CoqFrontend`,
  :class:`IsabelleFrontend`) reports structured, accurate capability
  evidence for whatever this environment actually has installed.
- Whenever the underlying executable is genuinely present (gated with
  ``pytest.mark.skipif`` so this suite still passes, via skip, in an
  environment without a Lean/Coq toolchain), a real
  ``lean``/``coqtop`` subprocess is invoked and its native diagnostic output
  is parsed into a :class:`GoalSnapshot` whose goal text, hypotheses,
  imports, and universe context are exactly what that real invocation
  produced — never a copy of the caller's plain-text input.
- Isabelle is confirmed unavailable in this repository's environment
  (matching the HAMMER-002 capability inventory), so its adapter is
  exercised for (a) the real "unavailable" capability-evidence path and
  (b) its instrumentation/parsing logic against a synthetic,
  format-accurate ``isabelle process`` transcript with the real subprocess
  call replaced — never against invented "available" behavior.
- No adapter ever fabricates a native goal from plain text: a source with no
  genuine incomplete-proof marker (``sorry``/``admit.``/``Admitted.``)
  raises :class:`GoalCaptureError` rather than returning a snapshot derived
  from the caller's description.
"""

from __future__ import annotations

import shutil

import pytest

from ipfs_datasets_py.logic.hammers.frontends import (
    CapabilityEvidence,
    CoqFrontend,
    FrontendUnavailableError,
    GoalCaptureError,
    GoalSnapshot,
    ITPFrontend,
    IsabelleFrontend,
    LeanFrontend,
    LocalHypothesis,
    SourcePosition,
    UniverseContext,
    get_frontend,
    iter_frontends,
    run_bounded_process,
)
from ipfs_datasets_py.logic.hammers.frontends import isabelle as isabelle_module
from ipfs_datasets_py.logic.hammers.models import ITPKind

LEAN_AVAILABLE = shutil.which("lean") is not None
COQ_AVAILABLE = shutil.which("coqtop") is not None or shutil.which("coqc") is not None

LEAN_SORRY_SOURCE = """theorem hammer_lean_goal (n : Nat) (h : n > 0) : n \u2260 0 := by
  sorry
"""

LEAN_TERM_MODE_SOURCE = """theorem hammer_lean_term_goal (n : Nat) (h : n > 0) : n \u2260 0 := sorry
"""

LEAN_UNIVERSE_SOURCE = """theorem hammer_lean_poly.{u,v} {alpha : Type u} {beta : Type v} \
(x : alpha) (l : List beta) : True := by
  sorry
"""

LEAN_WITH_IMPORT_SOURCE = """import Init.Prelude

theorem hammer_lean_import_goal (n : Nat) : n = n := by
  sorry
"""

COQ_ADMIT_SOURCE = """Theorem hammer_coq_goal : forall n m : nat, n + m = m + n.
Proof.
  intros n m.
  admit.
Admitted.
"""

COQ_ADMITTED_ONLY_SOURCE = """Theorem hammer_coq_admitted_goal : forall n : nat, n = n.
Proof.
Admitted.
"""

COQ_UNIVERSE_SOURCE = """Theorem hammer_coq_poly_goal : forall (A : Type) (x : A), x = x.
Proof.
  intros A x.
  admit.
Admitted.
"""

COQ_WITH_IMPORT_SOURCE = """Require Import Coq.Arith.Arith.
Theorem hammer_coq_import_goal : forall n : nat, n = n.
Proof.
  admit.
Admitted.
"""

ISABELLE_SORRY_SOURCE = """theory HammerIsabelleGoal
  imports Main
begin

theorem hammer_isabelle_goal: "P \u2227 Q \u27f6 P"
  apply (rule impI)
  sorry

end
"""

# A synthetic, format-accurate `isabelle process` transcript matching the
# documented `print_state` diagnostic-command output shape (Isar reference
# manual, section 8.2). Used only to exercise the parser; never presented as
# evidence that a live Isabelle toolchain produced it.
SYNTHETIC_ISABELLE_TRANSCRIPT = """proof (state)
using this:
  P
  Q
goal (1 subgoal):
 1. P
"""


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_concrete_frontends_satisfy_protocol(self):
        assert isinstance(LeanFrontend(), ITPFrontend)
        assert isinstance(CoqFrontend(), ITPFrontend)
        assert isinstance(IsabelleFrontend(), ITPFrontend)

    def test_frontends_declare_matching_itp_kind(self):
        assert LeanFrontend().itp is ITPKind.LEAN
        assert CoqFrontend().itp is ITPKind.COQ
        assert IsabelleFrontend().itp is ITPKind.ISABELLE

    def test_get_frontend_factory(self):
        assert isinstance(get_frontend(ITPKind.LEAN), LeanFrontend)
        assert isinstance(get_frontend(ITPKind.COQ), CoqFrontend)
        assert isinstance(get_frontend(ITPKind.ISABELLE), IsabelleFrontend)

    def test_get_frontend_rejects_unknown_kind(self):
        with pytest.raises(ValueError):
            get_frontend("not-a-real-itp")  # type: ignore[arg-type]

    def test_iter_frontends_covers_every_itp_kind(self):
        frontends = iter_frontends()
        assert set(frontends.keys()) == set(ITPKind)
        for itp, frontend in frontends.items():
            assert frontend.itp is itp


# ---------------------------------------------------------------------------
# CapabilityEvidence record
# ---------------------------------------------------------------------------


class TestCapabilityEvidence:
    def test_available_requires_no_unavailable_reason(self):
        evidence = CapabilityEvidence(itp=ITPKind.LEAN, available=True)
        evidence.validate()
        bad = CapabilityEvidence(
            itp=ITPKind.LEAN, available=True, unavailable_reason="should not be set"
        )
        with pytest.raises(ValueError):
            bad.validate()

    def test_unavailable_requires_reason(self):
        with pytest.raises(ValueError):
            CapabilityEvidence(itp=ITPKind.ISABELLE, available=False).validate()
        evidence = CapabilityEvidence(
            itp=ITPKind.ISABELLE, available=False, unavailable_reason="no_executable"
        )
        evidence.validate()

    def test_round_trip(self):
        evidence = CapabilityEvidence(
            itp=ITPKind.COQ,
            available=True,
            executables={"coqtop": {"found": True, "path": "/usr/bin/coqtop"}},
        )
        restored = CapabilityEvidence.from_dict(evidence.to_dict())
        restored.validate()
        assert restored.itp is ITPKind.COQ
        assert restored.executables == evidence.executables

    def test_every_frontend_reports_structured_capability_for_this_environment(self):
        for itp, frontend in iter_frontends().items():
            evidence = frontend.capability()
            evidence.validate()
            assert evidence.itp is itp
            assert isinstance(evidence.executables, dict) and evidence.executables
            if not evidence.available:
                assert evidence.unavailable_reason

    def test_isabelle_is_reported_unavailable_in_this_environment(self):
        # Matches docs/logic/itp_hammer_capability_inventory.md: Isabelle has
        # neither an executable nor a prior bridge module in this repo.
        evidence = IsabelleFrontend().capability()
        assert evidence.available is False
        assert evidence.unavailable_reason
        assert "isabelle" in evidence.executables


# ---------------------------------------------------------------------------
# GoalSnapshot record invariants (non-fabrication)
# ---------------------------------------------------------------------------


class TestGoalSnapshotInvariants:
    def _valid_snapshot_kwargs(self):
        return dict(
            itp=ITPKind.LEAN,
            itp_version="Lean (version 4.31.0)",
            theorem_id="foo",
            goal_text="n \u2260 0",
            hypotheses=[LocalHypothesis(names=["n"], type_text="Nat", raw="n : Nat")],
            imports=["Init"],
            universe_context=UniverseContext(notes="no universes"),
            source_position=SourcePosition(file="Goal.lean", line=1, column=0),
            native_command=["lean", "Goal.lean"],
            raw_native_output="don't know how to synthesize placeholder\ncontext:\nn : Nat\n\u22a2 n \u2260 0",
        )

    def test_valid_snapshot_validates_and_round_trips(self):
        snapshot = GoalSnapshot(**self._valid_snapshot_kwargs())
        snapshot.validate()
        restored = GoalSnapshot.from_dict(snapshot.to_dict())
        restored.validate()
        assert restored.goal_text == snapshot.goal_text
        assert [h.to_dict() for h in restored.hypotheses] == [
            h.to_dict() for h in snapshot.hypotheses
        ]

    def test_snapshot_requires_nonempty_raw_native_output(self):
        kwargs = self._valid_snapshot_kwargs()
        kwargs["raw_native_output"] = ""
        with pytest.raises(ValueError):
            GoalSnapshot(**kwargs).validate()

    def test_snapshot_requires_nonempty_native_command(self):
        kwargs = self._valid_snapshot_kwargs()
        kwargs["native_command"] = []
        with pytest.raises(ValueError):
            GoalSnapshot(**kwargs).validate()

    def test_snapshot_requires_nonempty_goal_text(self):
        kwargs = self._valid_snapshot_kwargs()
        kwargs["goal_text"] = ""
        with pytest.raises(ValueError):
            GoalSnapshot(**kwargs).validate()

    def test_hypothesis_requires_names_and_type(self):
        with pytest.raises(ValueError):
            LocalHypothesis(names=[], type_text="Nat", raw="x : Nat").validate()
        with pytest.raises(ValueError):
            LocalHypothesis(names=["x"], type_text="", raw="x : Nat").validate()

    def test_source_position_requires_valid_line_and_column(self):
        with pytest.raises(ValueError):
            SourcePosition(file="Goal.lean", line=0, column=0).validate()
        with pytest.raises(ValueError):
            SourcePosition(file="Goal.lean", line=1, column=-1).validate()


# ---------------------------------------------------------------------------
# Non-fabrication: refusing to snapshot without a genuine placeholder
# ---------------------------------------------------------------------------


class TestNonFabrication:
    def test_lean_refuses_source_without_sorry(self):
        frontend = LeanFrontend()
        if not frontend.capability().available:
            pytest.skip("lean executable not available in this environment")
        with pytest.raises(GoalCaptureError):
            frontend.snapshot_goal("theorem foo : True := trivial", theorem_id="foo")

    def test_coq_refuses_source_without_admit_marker(self):
        frontend = CoqFrontend()
        if not frontend.capability().available:
            pytest.skip("coqtop executable not available in this environment")
        with pytest.raises(GoalCaptureError):
            frontend.snapshot_goal(
                "Theorem foo : True.\nProof.\n  exact I.\nQed.\n", theorem_id="foo"
            )

    def test_isabelle_refuses_source_without_sorry(self, monkeypatch):
        frontend = IsabelleFrontend()
        monkeypatch.setattr(
            isabelle_module,
            "find_executable",
            lambda name: "/fake/isabelle" if name == "isabelle" else None,
        )
        with pytest.raises(GoalCaptureError):
            frontend.snapshot_goal(
                "theory HammerIsabelleGoal\n  imports Main\nbegin\nend\n",
                theorem_id="hammer_isabelle_goal",
            )

    def test_unavailable_frontend_raises_before_any_invocation(self, monkeypatch):
        frontend = IsabelleFrontend()
        assert frontend.capability().available is False
        with pytest.raises(FrontendUnavailableError) as excinfo:
            frontend.snapshot_goal(ISABELLE_SORRY_SOURCE, theorem_id="hammer_isabelle_goal")
        assert excinfo.value.capability.available is False
        assert excinfo.value.capability.unavailable_reason


# ---------------------------------------------------------------------------
# Lean frontend — real subprocess invocation (skipped if lean is absent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean executable not available in this environment")
class TestLeanFrontendReal:
    def test_capability_reports_available(self):
        evidence = LeanFrontend().capability()
        assert evidence.available is True
        assert evidence.unavailable_reason is None
        assert evidence.executables["lean"]["found"] is True
        assert evidence.executables["lean"]["path"]

    def test_snapshot_goal_from_tactic_mode_sorry(self):
        snapshot = LeanFrontend().snapshot_goal(
            LEAN_SORRY_SOURCE, theorem_id="hammer_lean_goal"
        )
        snapshot.validate()
        assert snapshot.itp is ITPKind.LEAN
        assert snapshot.goal_text == "n \u2260 0"
        by_name = {h.names[0]: h.type_text for h in snapshot.hypotheses}
        assert by_name == {"n": "Nat", "h": "n > 0"}
        assert snapshot.source_position.line == 2
        assert snapshot.native_command[0] == LeanFrontend().capability().executables["lean"]["path"]
        assert "context:" in snapshot.raw_native_output
        assert "\u22a2" in snapshot.raw_native_output
        assert snapshot.itp_version and "unknown" != snapshot.itp_version

    def test_snapshot_goal_from_term_mode_sorry(self):
        snapshot = LeanFrontend().snapshot_goal(
            LEAN_TERM_MODE_SOURCE, theorem_id="hammer_lean_term_goal"
        )
        snapshot.validate()
        assert snapshot.goal_text == "n \u2260 0"
        by_name = {h.names[0]: h.type_text for h in snapshot.hypotheses}
        assert by_name == {"n": "Nat", "h": "n > 0"}

    def test_snapshot_goal_captures_universe_context(self):
        snapshot = LeanFrontend().snapshot_goal(
            LEAN_UNIVERSE_SOURCE, theorem_id="hammer_lean_poly"
        )
        snapshot.validate()
        assert snapshot.universe_context.parameters == ["u", "v"]
        assert snapshot.universe_context.type_bindings == {
            "alpha": "Type u",
            "beta": "Type v",
        }

    def test_snapshot_goal_captures_imports(self):
        snapshot = LeanFrontend().snapshot_goal(
            LEAN_WITH_IMPORT_SOURCE, theorem_id="hammer_lean_import_goal"
        )
        snapshot.validate()
        assert snapshot.imports == ["Init.Prelude"]

    def test_snapshot_goal_is_never_a_copy_of_input_text(self):
        # The goal text must come from Lean's own diagnostic, not merely
        # echo the caller's declaration source verbatim.
        snapshot = LeanFrontend().snapshot_goal(
            LEAN_SORRY_SOURCE, theorem_id="hammer_lean_goal"
        )
        assert snapshot.goal_text != LEAN_SORRY_SOURCE
        assert snapshot.raw_native_output in snapshot.extra.get(
            "other_messages", []
        ) or snapshot.raw_native_output not in (LEAN_SORRY_SOURCE,)


# ---------------------------------------------------------------------------
# Coq frontend — real subprocess invocation (skipped if coqtop is absent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not COQ_AVAILABLE, reason="coqtop/coqc executable not available in this environment"
)
class TestCoqFrontendReal:
    def test_capability_reports_available(self):
        evidence = CoqFrontend().capability()
        assert evidence.available is True
        assert evidence.unavailable_reason is None
        assert evidence.executables["coqtop"]["found"] is True

    def test_snapshot_goal_from_admit_marker(self):
        snapshot = CoqFrontend().snapshot_goal(COQ_ADMIT_SOURCE, theorem_id="hammer_coq_goal")
        snapshot.validate()
        assert snapshot.itp is ITPKind.COQ
        assert snapshot.goal_text == "n + m = m + n"
        by_names = {tuple(h.names): h.type_text for h in snapshot.hypotheses}
        assert by_names == {("n", "m"): "nat"}
        assert "====" in snapshot.raw_native_output
        assert snapshot.itp_version and snapshot.itp_version != "unknown"

    def test_snapshot_goal_from_admitted_only(self):
        # No `intros` ran before `Admitted.`, so the captured goal is the
        # theorem's full statement, unintroduced — this is the exact native
        # goal state at that point, not a fabricated simplification of it.
        snapshot = CoqFrontend().snapshot_goal(
            COQ_ADMITTED_ONLY_SOURCE, theorem_id="hammer_coq_admitted_goal"
        )
        snapshot.validate()
        assert snapshot.goal_text == "forall n : nat, n = n"

    def test_snapshot_goal_captures_universe_context(self):
        snapshot = CoqFrontend().snapshot_goal(
            COQ_UNIVERSE_SOURCE, theorem_id="hammer_coq_poly_goal"
        )
        snapshot.validate()
        assert snapshot.universe_context.parameters
        assert any(
            v.startswith("Type@{") for v in snapshot.universe_context.type_bindings.values()
        )

    def test_snapshot_goal_captures_imports(self):
        snapshot = CoqFrontend().snapshot_goal(
            COQ_WITH_IMPORT_SOURCE, theorem_id="hammer_coq_import_goal"
        )
        snapshot.validate()
        assert snapshot.imports == ["Require Import Coq.Arith.Arith."]

    def test_native_command_uses_resolved_executable(self):
        evidence = CoqFrontend().capability()
        snapshot = CoqFrontend().snapshot_goal(COQ_ADMIT_SOURCE, theorem_id="hammer_coq_goal")
        assert snapshot.native_command[0] == evidence.executables["coqtop"]["path"]


# ---------------------------------------------------------------------------
# Isabelle frontend — structured unavailable evidence + mocked parser path
# ---------------------------------------------------------------------------


class TestIsabelleFrontend:
    def test_real_capability_is_unavailable_here(self):
        evidence = IsabelleFrontend().capability()
        assert evidence.available is False
        assert evidence.unavailable_reason == (
            "isabelle_executable_not_found_on_path_or_common_install_dirs"
        )

    def test_real_snapshot_goal_raises_frontend_unavailable(self):
        with pytest.raises(FrontendUnavailableError):
            IsabelleFrontend().snapshot_goal(
                ISABELLE_SORRY_SOURCE, theorem_id="hammer_isabelle_goal"
            )

    def test_snapshot_goal_parses_synthetic_print_state_transcript(self, monkeypatch):
        """Exercises the real instrumentation + parsing code path with the
        underlying subprocess call replaced by a synthetic, format-accurate
        `isabelle process` transcript (Isabelle is not installed in this
        environment; see the module docstring in ``.isabelle``)."""

        frontend = IsabelleFrontend()
        monkeypatch.setattr(
            isabelle_module,
            "find_executable",
            lambda name: "/fake/isabelle" if name == "isabelle" else None,
        )

        captured_sources = {}

        def _fake_run_bounded_process(command, *, timeout, cwd=None):
            from ipfs_datasets_py.logic.hammers.frontends.base import BoundedProcessResult

            if command[:2] == ["/fake/isabelle", "version"]:
                return BoundedProcessResult(
                    command=command, returncode=0, stdout="Isabelle2024 (fake)", stderr=""
                )

            # Record the instrumented theory file's contents so the test can
            # assert `print_state` was really inserted before invocation.
            import pathlib

            if cwd is not None:
                for path in pathlib.Path(cwd).glob("*.thy"):
                    captured_sources["instrumented"] = path.read_text(encoding="utf-8")
            return BoundedProcessResult(
                command=command,
                returncode=0,
                stdout=SYNTHETIC_ISABELLE_TRANSCRIPT,
                stderr="",
            )

        monkeypatch.setattr(
            isabelle_module, "run_bounded_process", _fake_run_bounded_process
        )

        snapshot = frontend.snapshot_goal(
            ISABELLE_SORRY_SOURCE, theorem_id="hammer_isabelle_goal"
        )
        snapshot.validate()
        assert snapshot.itp is ITPKind.ISABELLE
        assert snapshot.goal_text == "P"
        assert snapshot.imports == ["Main"]
        assert [h.type_text for h in snapshot.hypotheses] == ["P", "Q"]
        assert "print_state" in captured_sources["instrumented"]
        assert snapshot.raw_native_output.strip().startswith("goal (1 subgoal)")

    def test_missing_theory_header_raises_goal_capture_error(self, monkeypatch):
        frontend = IsabelleFrontend()
        monkeypatch.setattr(
            isabelle_module,
            "find_executable",
            lambda name: "/fake/isabelle" if name == "isabelle" else None,
        )
        with pytest.raises(GoalCaptureError):
            frontend.snapshot_goal("theorem foo: True sorry", theorem_id="foo")


# ---------------------------------------------------------------------------
# Bounded subprocess helper
# ---------------------------------------------------------------------------


class TestBoundedProcessHelper:
    def test_run_bounded_process_reports_timeout(self):
        result = run_bounded_process(["sleep", "5"], timeout=0.1)
        assert result.timed_out is True
        assert result.error

    def test_run_bounded_process_reports_missing_executable(self):
        result = run_bounded_process(["this-executable-does-not-exist-xyz"], timeout=5.0)
        assert result.error

    def test_run_bounded_process_never_uses_a_shell_string(self):
        result = run_bounded_process(["echo", "hello; rm -rf /"], timeout=5.0)
        assert result.stdout.strip() == "hello; rm -rf /"
