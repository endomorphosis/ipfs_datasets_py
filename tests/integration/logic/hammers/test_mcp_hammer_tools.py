"""Integration tests for the governed MCP/CLI hammer operations (HAMMER-013,
``## HAMMER-013`` in ``docs/logic/itp_hammer_taskboard.todo.md``).

These tests exercise :mod:`ipfs_datasets_py.mcp_server.tools.logic_hammer`
directly (the module the MCP server and ``scripts/cli/logic_cli.py`` both
call into), covering every acceptance criterion:

- All seven named operations (inspect, select-premises, translate,
  run-candidate, reconstruct, retrieve-receipt, capability-status) exist and
  return the shared, structured response envelope.
- Every operation that launches a native process (inspect, run-candidate,
  reconstruct) refuses to run without ``confirm_native_execution=True`` and
  returns a structured ``confirmation_required`` response instead.
- A missing ITP toolchain or solver executable always yields a structured
  ``unavailable`` response carrying machine-readable capability evidence,
  never a crash or a silent default.
- Correlation ids are always present in the response (caller-supplied or
  freshly generated) so a caller can thread one id across an entire
  inspect -> select-premises -> translate -> run-candidate -> reconstruct ->
  retrieve-receipt flow.
- ``hammer_run_candidate`` never reports ``verified`` -- only
  ``hammer_reconstruct`` may, and only when the underlying
  ``ReconstructionRecord.kernel_accepted`` bit (set exclusively by a real
  kernel subprocess) is ``True``. An adversarial, false theorem statement
  proves the negative case: reconstruction runs against a real kernel and
  is correctly rejected, never silently upgraded to ``verified``.

Real ``lean``/``coqtop``/``cvc5`` invocations are exercised when those
toolchains are installed (gated with ``pytest.mark.skipif``, mirroring
``tests/integration/logic/hammers/test_reconstruction.py`` and
``tests/integration/logic/hammers/test_solver_portfolio.py``); the suite
still passes, via skip, on a host lacking any of them. Executable-independent
governance behavior (confirmation gating, policy validation, correlation
ids, envelope shape, translation fail-closed behavior, receipt persistence)
is always exercised regardless of what happens to be installed.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any, Coroutine, Dict, TypeVar

import pytest

from ipfs_datasets_py.logic.hammers.corpus import CorpusManifest, CorpusSource
from ipfs_datasets_py.logic.hammers.models import (
    HammerPolicy,
    HammerRequest,
    HammerResult,
    HammerResultStatus,
    ITPKind,
    TranslationRecord,
    TranslationStatus,
    TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.policy import known_solver_names
from ipfs_datasets_py.logic.hammers.receipts import HammerReceipt
from ipfs_datasets_py.mcp_server.tools import logic_hammer as lh

LEAN_AVAILABLE = shutil.which("lean") is not None
COQ_AVAILABLE = shutil.which("coqtop") is not None
ISABELLE_AVAILABLE = shutil.which("isabelle") is not None
CVC5_AVAILABLE = shutil.which("cvc5") is not None
Z3_AVAILABLE = shutil.which("z3") is not None
VAMPIRE_AVAILABLE = shutil.which("vampire") is not None

_T = TypeVar("_T")


def run(coro: "Coroutine[Any, Any, _T]") -> _T:
    """Run an async hammer operation synchronously for test convenience."""

    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Shared fixtures / term payloads
# ---------------------------------------------------------------------------

NAT_SORT = {"kind": "sort", "name": "nat"}
PROP_SORT = {"kind": "sort", "name": "$prop"}
PREDICATE_TYPE = {"kind": "function", "params": [NAT_SORT], "result": PROP_SORT}


def _predicate_app(name: str, var: str) -> Dict[str, Any]:
    return {
        "kind": "app",
        "fn": {"kind": "const", "name": name, "type": PREDICATE_TYPE},
        "args": [{"kind": "var", "name": var, "type": NAT_SORT}],
    }


def tautology_term() -> Dict[str, Any]:
    """``forall x. p(x) => p(x)`` -- trivially valid regardless of format."""

    return {
        "kind": "forall",
        "var": "x",
        "var_type": NAT_SORT,
        "body": {
            "kind": "implies",
            "left": _predicate_app("p", "x"),
            "right": _predicate_app("p", "x"),
        },
    }


def dependent_type_term() -> Dict[str, Any]:
    """A ``Vec n``-typed equality -- must fail closed at translation time."""

    dependent_const = {
        "kind": "const",
        "name": "v",
        "type": {"kind": "dependent", "description": "Vec n"},
    }
    return {"kind": "eq", "left": dependent_const, "right": dependent_const}


def _corpus_manifest_payload() -> Dict[str, Any]:
    manifest = CorpusManifest(manifest_id="hammer013-test-manifest")
    manifest.register_source(
        CorpusSource(
            corpus_id="c1",
            name="Test Corpus",
            source_itp=ITPKind.LEAN,
            version_ref="v1",
            license_id="MIT",
        )
    )
    manifest.add_theorem(
        theorem_id="th_reflexive",
        corpus_id="c1",
        statement="theorem foo : forall x, p x -> p x",
        imports=["A"],
    )
    manifest.add_theorem(
        theorem_id="th_unrelated",
        corpus_id="c1",
        statement="theorem bar : forall y, q y -> q y",
        imports=["B"],
    )
    return manifest.to_dict()


def _minimal_unsupported_receipt(request_id: str = "receipt-req-1") -> HammerReceipt:
    """Build the smallest valid, fully offline
    :class:`~ipfs_datasets_py.logic.hammers.receipts.HammerReceipt` --
    an ``UNSUPPORTED_TRANSLATION`` outcome requires no solver attempt,
    candidate, or reconstruction, keeping this fixture dependency-free."""

    request = HammerRequest(
        request_id=request_id,
        itp=ITPKind.LEAN,
        theorem_id="t_dependent",
        goal_statement="a dependent goal",
        corpus_revision="sha256:test-revision",
        policy=HammerPolicy(timeout_seconds=10.0, allowed_solvers=[]),
    )
    translation = TranslationRecord(
        translation_id=f"{request_id}:goal:tptp:0",
        request_id=request_id,
        target=TranslationTarget.TPTP,
        status=TranslationStatus.UNSUPPORTED,
        source_construct="goal",
        unsupported_reason="dependent type is not supported: Vec n",
    )
    result = HammerResult(
        result_id=f"{request_id}:result",
        request=request,
        status=HammerResultStatus.UNSUPPORTED_TRANSLATION,
        corpus_revision=request.corpus_revision,
        translations=[translation],
    )
    return HammerReceipt(result=result)


# ---------------------------------------------------------------------------
# Shared envelope-shape assertions
# ---------------------------------------------------------------------------


def _assert_envelope_shape(response: Dict[str, Any], *, operation: str) -> None:
    assert response["operation"] == operation
    assert isinstance(response["correlation_id"], str) and response["correlation_id"]
    assert isinstance(response["success"], bool)
    assert response["status"] in {
        "ok",
        "unavailable",
        "policy_denied",
        "confirmation_required",
        "unsupported_translation",
        "not_found",
        "error",
    }
    assert "data" in response and "error" in response and "notes" in response


# ---------------------------------------------------------------------------
# capability-status
# ---------------------------------------------------------------------------


class TestCapabilityStatus:
    def test_reports_structured_evidence_for_every_itp_and_solver(self):
        response = run(lh.hammer_capability_status(probe_versions=False))
        _assert_envelope_shape(response, operation="capability-status")
        assert response["success"] is True
        assert response["status"] == "ok"

        itps = response["data"]["itps"]
        assert set(itps.keys()) == {"lean", "coq", "isabelle"}
        for entry in itps.values():
            assert set(entry.keys()) == {"frontend", "reconstruction"}
            assert isinstance(entry["frontend"]["available"], bool)
            assert isinstance(entry["reconstruction"]["available"], bool)

        solvers = response["data"]["solvers"]
        assert set(solvers.keys()) == set(known_solver_names())
        for entry in solvers.values():
            assert isinstance(entry["available"], bool)
            if not entry["available"]:
                assert entry["path"] is None

    def test_never_probes_versions_when_disabled(self):
        response = run(lh.hammer_capability_status(probe_versions=False))
        for entry in response["data"]["solvers"].values():
            assert entry["version"] is None
            assert entry["version_probe_error"] is None

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean executable not available")
    def test_lean_reports_available(self):
        response = run(lh.hammer_capability_status(itps=["lean"], solvers=[]))
        assert response["data"]["itps"]["lean"]["frontend"]["available"] is True
        assert response["data"]["any_capability_available"] is True

    @pytest.mark.skipif(ISABELLE_AVAILABLE, reason="this host has isabelle installed")
    def test_isabelle_reports_structured_unavailable_when_absent(self):
        response = run(lh.hammer_capability_status(itps=["isabelle"], solvers=[]))
        entry = response["data"]["itps"]["isabelle"]["frontend"]
        assert entry["available"] is False
        assert entry["unavailable_reason"]

    def test_filters_by_itps_and_solvers(self):
        response = run(
            lh.hammer_capability_status(itps=["lean"], solvers=["z3"], probe_versions=False)
        )
        assert set(response["data"]["itps"]) == {"lean"}
        assert set(response["data"]["solvers"]) == {"z3"}

    def test_unknown_itp_is_a_structured_error(self):
        response = run(lh.hammer_capability_status(itps=["not-a-real-itp"]))
        assert response["success"] is False
        assert response["status"] == "error"
        assert response["error"]

    def test_unknown_solver_is_a_structured_error(self):
        response = run(lh.hammer_capability_status(solvers=["not-a-real-solver"]))
        assert response["success"] is False
        assert response["status"] == "error"
        assert "not-a-real-solver" in response["error"]

    def test_correlation_id_is_echoed_or_autogenerated(self):
        explicit = run(lh.hammer_capability_status(correlation_id="corr-fixed-1", probe_versions=False))
        assert explicit["correlation_id"] == "corr-fixed-1"

        auto_a = run(lh.hammer_capability_status(probe_versions=False))
        auto_b = run(lh.hammer_capability_status(probe_versions=False))
        assert auto_a["correlation_id"] != auto_b["correlation_id"]
        assert auto_a["correlation_id"].startswith("hammer-")

    def test_never_requires_native_confirmation(self):
        # capability-status has no confirm_native_execution parameter at
        # all -- it never launches a goal-capture or solver-search process.
        import inspect as _inspect

        signature = _inspect.signature(lh.hammer_capability_status)
        assert "confirm_native_execution" not in signature.parameters


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


class TestInspect:
    def test_unknown_itp_is_a_structured_error(self):
        response = run(
            lh.hammer_inspect(itp="not-a-real-itp", theorem_id="t1", native_source="x")
        )
        _assert_envelope_shape(response, operation="inspect")
        assert response["status"] == "error"
        assert response["success"] is False

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean executable not available")
    def test_requires_confirmation_before_launching_lean(self):
        response = run(
            lh.hammer_inspect(
                itp="lean",
                theorem_id="t1",
                native_source="theorem t1 : 1 = 1 := by sorry",
            )
        )
        _assert_envelope_shape(response, operation="inspect")
        assert response["status"] == "confirmation_required"
        assert response["success"] is False
        assert response["capability"] is not None

    @pytest.mark.skipif(ISABELLE_AVAILABLE, reason="this host has isabelle installed")
    def test_unavailable_itp_reports_structured_capability(self):
        response = run(
            lh.hammer_inspect(
                itp="isabelle",
                theorem_id="t1",
                native_source="theorem t1: \"1 = (1::nat)\" sorry",
                confirm_native_execution=True,
            )
        )
        _assert_envelope_shape(response, operation="inspect")
        assert response["status"] == "unavailable"
        assert response["success"] is False
        assert response["capability"]["available"] is False
        assert response["capability"]["unavailable_reason"]

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean executable not available")
    def test_captures_genuine_goal_snapshot_when_confirmed(self):
        response = run(
            lh.hammer_inspect(
                itp="lean",
                theorem_id="hammer013_inspect",
                native_source="theorem hammer013_inspect : 1 = 1 := by sorry",
                confirm_native_execution=True,
            )
        )
        _assert_envelope_shape(response, operation="inspect")
        assert response["status"] == "ok"
        assert response["success"] is True
        snapshot = response["data"]["goal_snapshot"]
        assert snapshot["itp"] == "lean"
        assert snapshot["theorem_id"] == "hammer013_inspect"
        assert "1 = 1" in snapshot["goal_text"]
        assert snapshot["raw_native_output"]

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean executable not available")
    def test_refuses_to_fabricate_goal_without_native_marker(self):
        response = run(
            lh.hammer_inspect(
                itp="lean",
                theorem_id="hammer013_no_marker",
                native_source="theorem hammer013_no_marker : True := trivial",
                confirm_native_execution=True,
            )
        )
        _assert_envelope_shape(response, operation="inspect")
        assert response["status"] == "error"
        assert response["success"] is False
        assert "sorry" in response["error"]


# ---------------------------------------------------------------------------
# select-premises
# ---------------------------------------------------------------------------


class TestSelectPremises:
    def test_selects_ranked_premises_from_manifest(self):
        response = run(
            lh.hammer_select_premises(
                goal_statement="forall x, p x -> p x",
                corpus_manifest=_corpus_manifest_payload(),
                top_k=5,
            )
        )
        _assert_envelope_shape(response, operation="select-premises")
        assert response["status"] == "ok"
        assert response["success"] is True
        selected = response["data"]["selection"]["selected"]
        assert selected
        assert selected[0]["premise_id"] == "th_reflexive"
        assert response["data"]["corpus_revision"]

    def test_never_requires_native_confirmation(self):
        import inspect as _inspect

        signature = _inspect.signature(lh.hammer_select_premises)
        assert "confirm_native_execution" not in signature.parameters

    def test_top_k_exceeding_policy_is_policy_denied(self):
        response = run(
            lh.hammer_select_premises(
                goal_statement="forall x, p x -> p x",
                corpus_manifest=_corpus_manifest_payload(),
                top_k=1000,
                policy={"timeout_seconds": 10.0, "allowed_solvers": [], "max_premises": 4},
            )
        )
        _assert_envelope_shape(response, operation="select-premises")
        assert response["status"] == "policy_denied"
        assert response["success"] is False

    def test_missing_manifest_source_is_a_structured_error(self):
        response = run(lh.hammer_select_premises(goal_statement="forall x, p x -> p x"))
        _assert_envelope_shape(response, operation="select-premises")
        assert response["status"] == "error"
        assert response["success"] is False

    def test_correlation_id_is_echoed(self):
        response = run(
            lh.hammer_select_premises(
                goal_statement="forall x, p x -> p x",
                corpus_manifest=_corpus_manifest_payload(),
                correlation_id="corr-select-1",
            )
        )
        assert response["correlation_id"] == "corr-select-1"


# ---------------------------------------------------------------------------
# translate
# ---------------------------------------------------------------------------


class TestTranslate:
    def test_supported_construct_translates_to_tptp(self):
        response = run(
            lh.hammer_translate(
                request_id="req-translate-1",
                source_construct="goal",
                term=tautology_term(),
                target="tptp",
            )
        )
        _assert_envelope_shape(response, operation="translate")
        assert response["status"] == "ok"
        assert response["success"] is True
        translation = response["data"]["translation"]
        assert translation["status"] == "supported"
        assert "fof" in translation["translated_text"] or "tff" in translation["translated_text"]
        assert response["data"]["translation_map"]["entries"]

    def test_supported_construct_translates_to_smtlib(self):
        response = run(
            lh.hammer_translate(
                request_id="req-translate-2",
                source_construct="goal",
                term=tautology_term(),
                target="smtlib",
            )
        )
        assert response["status"] == "ok"
        translation = response["data"]["translation"]
        assert translation["target"] == "smtlib"
        assert translation["status"] == "supported"

    def test_dependent_type_fails_closed(self):
        response = run(
            lh.hammer_translate(
                request_id="req-translate-3",
                source_construct="goal",
                term=dependent_type_term(),
                target="tptp",
            )
        )
        _assert_envelope_shape(response, operation="translate")
        assert response["status"] == "unsupported_translation"
        assert response["success"] is False
        translation = response["data"]["translation"]
        assert translation["status"] == "unsupported"
        assert translation["translated_text"] is None
        assert "Vec n" in translation["unsupported_reason"]
        assert response["error"] == translation["unsupported_reason"]

    def test_unknown_target_is_a_structured_error(self):
        response = run(
            lh.hammer_translate(
                request_id="req-translate-4",
                source_construct="goal",
                term=tautology_term(),
                target="not-a-real-target",
            )
        )
        assert response["status"] == "error"
        assert response["success"] is False

    def test_malformed_term_payload_is_a_structured_error(self):
        response = run(
            lh.hammer_translate(
                request_id="req-translate-5",
                source_construct="goal",
                term={"kind": "not-a-real-kind"},
                target="tptp",
            )
        )
        assert response["status"] == "error"
        assert response["success"] is False

    def test_never_requires_native_confirmation(self):
        import inspect as _inspect

        signature = _inspect.signature(lh.hammer_translate)
        assert "confirm_native_execution" not in signature.parameters


# ---------------------------------------------------------------------------
# run-candidate
# ---------------------------------------------------------------------------


def _base_request_payload(*, request_id: str, allowed_solvers) -> Dict[str, Any]:
    return {
        "request_id": request_id,
        "itp": "lean",
        "theorem_id": "t_run_candidate",
        "goal_statement": "forall x, p x -> p x",
        "corpus_revision": "sha256:test-revision",
        "policy": {"timeout_seconds": 20.0, "allowed_solvers": list(allowed_solvers)},
    }


class TestRunCandidate:
    def test_requires_confirmation_before_launching_solvers(self):
        request = _base_request_payload(
            request_id="req-run-candidate-confirm", allowed_solvers=["vampire"]
        )
        translate_response = run(
            lh.hammer_translate(
                request_id=request["request_id"],
                source_construct="goal",
                term=tautology_term(),
                target="tptp",
            )
        )
        attempts = [
            {"translation": translate_response["data"]["translation"], "solver_name": "vampire"}
        ]
        response = run(lh.hammer_run_candidate(request=request, attempts=attempts))
        _assert_envelope_shape(response, operation="run-candidate")
        assert response["status"] == "confirmation_required"
        assert response["success"] is False

    @pytest.mark.skipif(VAMPIRE_AVAILABLE, reason="this host has vampire installed")
    def test_unavailable_solver_after_confirmation(self):
        request = _base_request_payload(
            request_id="req-run-candidate-unavailable", allowed_solvers=["vampire"]
        )
        translate_response = run(
            lh.hammer_translate(
                request_id=request["request_id"],
                source_construct="goal",
                term=tautology_term(),
                target="tptp",
            )
        )
        attempts = [
            {"translation": translate_response["data"]["translation"], "solver_name": "vampire"}
        ]
        response = run(
            lh.hammer_run_candidate(
                request=request, attempts=attempts, confirm_native_execution=True
            )
        )
        _assert_envelope_shape(response, operation="run-candidate")
        assert response["status"] == "unavailable"
        assert response["data"]["recommended_status"] == "unavailable"
        assert response["data"]["run_result"]["denied"]
        assert response["data"]["run_result"]["denied"][0]["solver_name"] == "vampire"
        # Never claims verified -- this is an untrusted, solver-derived signal only.
        assert "verified" not in response["data"]["recommended_status"]

    @pytest.mark.skipif(not CVC5_AVAILABLE, reason="cvc5 executable not available")
    def test_real_cvc5_invocation_produces_untrusted_candidate(self):
        request = _base_request_payload(
            request_id="req-run-candidate-cvc5", allowed_solvers=["cvc5"]
        )
        translate_response = run(
            lh.hammer_translate(
                request_id=request["request_id"],
                source_construct="goal",
                term=tautology_term(),
                target="smtlib",
            )
        )
        attempts = [
            {"translation": translate_response["data"]["translation"], "solver_name": "cvc5"}
        ]
        response = run(
            lh.hammer_run_candidate(
                request=request, attempts=attempts, confirm_native_execution=True
            )
        )
        _assert_envelope_shape(response, operation="run-candidate")
        assert response["status"] == "ok"
        assert response["success"] is True
        assert response["data"]["run_result"]["denied"] == []
        assert response["data"]["recommended_status"] in {"candidate", "unknown"}
        assert response["data"]["recommended_status"] != "verified"
        # No response from this operation may ever claim "verified".
        assert "verified" not in str(response["data"]).lower()

    def test_invalid_request_payload_is_a_structured_error(self):
        response = run(
            lh.hammer_run_candidate(request={"not": "a valid request"}, attempts=[])
        )
        assert response["status"] == "error"
        assert response["success"] is False

    def test_unknown_solver_in_policy_is_policy_denied(self):
        request = _base_request_payload(
            request_id="req-run-candidate-badpolicy", allowed_solvers=["not-a-real-solver"]
        )
        response = run(
            lh.hammer_run_candidate(
                request=request, attempts=[], confirm_native_execution=True
            )
        )
        _assert_envelope_shape(response, operation="run-candidate")
        assert response["status"] == "policy_denied"
        assert response["success"] is False


# ---------------------------------------------------------------------------
# reconstruct
# ---------------------------------------------------------------------------


def _minimal_candidate_payload(request_id: str) -> Dict[str, Any]:
    return {
        "candidate_id": f"{request_id}:candidate",
        "request_id": request_id,
        "solver_attempt_id": "native-automation-fallback",
        "premise_ids": [],
    }


class TestReconstruct:
    def test_requires_confirmation_before_launching_kernel(self):
        request_id = "req-reconstruct-confirm"
        request = _base_request_payload(request_id=request_id, allowed_solvers=[])
        response = run(
            lh.hammer_reconstruct(
                request=request,
                candidate=_minimal_candidate_payload(request_id),
                itp="lean",
                theorem_id=request["theorem_id"],
                native_source="theorem t1 : 1 = 1 := by sorry",
            )
        )
        _assert_envelope_shape(response, operation="reconstruct")
        assert response["status"] == "confirmation_required"
        assert response["success"] is False

    @pytest.mark.skipif(ISABELLE_AVAILABLE, reason="this host has isabelle installed")
    def test_unavailable_itp_reports_structured_capability(self):
        request_id = "req-reconstruct-unavailable"
        request = dict(_base_request_payload(request_id=request_id, allowed_solvers=[]))
        request["itp"] = "isabelle"
        response = run(
            lh.hammer_reconstruct(
                request=request,
                candidate=_minimal_candidate_payload(request_id),
                itp="isabelle",
                theorem_id=request["theorem_id"],
                native_source="theorem t1: \"1 = (1::nat)\" sorry",
                confirm_native_execution=True,
            )
        )
        _assert_envelope_shape(response, operation="reconstruct")
        assert response["status"] == "unavailable"
        assert response["capability"]["available"] is False

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean executable not available")
    def test_genuinely_provable_theorem_is_verified_via_real_kernel(self):
        request_id = "req-reconstruct-verified"
        request = _base_request_payload(request_id=request_id, allowed_solvers=[])
        request["theorem_id"] = "hammer013_recon_good"
        response = run(
            lh.hammer_reconstruct(
                request=request,
                candidate=_minimal_candidate_payload(request_id),
                itp="lean",
                theorem_id="hammer013_recon_good",
                native_source="theorem hammer013_recon_good : 1 = 1 := by sorry",
                confirm_native_execution=True,
            )
        )
        _assert_envelope_shape(response, operation="reconstruct")
        assert response["status"] == "ok"
        assert response["success"] is True
        assert response["data"]["status"] == "verified"
        assert response["data"]["reconstruction"]["kernel_accepted"] is True
        assert response["data"]["reconstruction"]["failure_reason"] is None
        assert response["data"]["environment_lock"]["itp"] == "lean"

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean executable not available")
    def test_false_theorem_is_never_verified_despite_real_kernel_invocation(self):
        """Adversarial case: the goal statement is false (``1 = 2``). Every
        native automation alternative genuinely fails and the real Lean
        kernel genuinely rejects the reconstruction -- this operation must
        never report ``verified`` regardless of what the (here, empty)
        candidate evidence claimed."""

        request_id = "req-reconstruct-false-theorem"
        request = _base_request_payload(request_id=request_id, allowed_solvers=[])
        request["theorem_id"] = "hammer013_recon_false"
        response = run(
            lh.hammer_reconstruct(
                request=request,
                candidate=_minimal_candidate_payload(request_id),
                itp="lean",
                theorem_id="hammer013_recon_false",
                native_source="theorem hammer013_recon_false : (1 : Nat) = 2 := by sorry",
                confirm_native_execution=True,
            )
        )
        _assert_envelope_shape(response, operation="reconstruct")
        assert response["status"] == "ok"
        assert response["data"]["status"] == "candidate"
        assert response["data"]["reconstruction"]["kernel_accepted"] is False
        assert response["data"]["reconstruction"]["failure_reason"]

    def test_invalid_candidate_payload_is_a_structured_error(self):
        request_id = "req-reconstruct-bad-candidate"
        request = _base_request_payload(request_id=request_id, allowed_solvers=[])
        response = run(
            lh.hammer_reconstruct(
                request=request,
                candidate={"not": "a valid candidate"},
                itp="lean",
                theorem_id=request["theorem_id"],
                native_source="theorem t1 : 1 = 1 := by sorry",
                confirm_native_execution=True,
            )
        )
        assert response["status"] == "error"
        assert response["success"] is False

    def test_unknown_itp_is_a_structured_error(self):
        request_id = "req-reconstruct-bad-itp"
        request = _base_request_payload(request_id=request_id, allowed_solvers=[])
        response = run(
            lh.hammer_reconstruct(
                request=request,
                candidate=_minimal_candidate_payload(request_id),
                itp="not-a-real-itp",
                theorem_id=request["theorem_id"],
                native_source="x",
                confirm_native_execution=True,
            )
        )
        assert response["status"] == "error"
        assert response["success"] is False


# ---------------------------------------------------------------------------
# retrieve-receipt (and persist-receipt)
# ---------------------------------------------------------------------------


class TestRetrieveReceipt:
    def test_persist_then_retrieve_round_trips(self, tmp_path):
        store_root = str(tmp_path / "receipts")
        receipt = _minimal_unsupported_receipt("receipt-req-round-trip")

        persist_response = run(
            lh.hammer_persist_receipt(
                receipt=receipt.to_dict(), publish=True, store_root=store_root
            )
        )
        _assert_envelope_shape(persist_response, operation="persist-receipt")
        assert persist_response["status"] == "ok"
        assert persist_response["data"]["receipt_id"] == receipt.receipt_id

        retrieve_response = run(
            lh.hammer_retrieve_receipt(receipt_id=receipt.receipt_id, store_root=store_root)
        )
        _assert_envelope_shape(retrieve_response, operation="retrieve-receipt")
        assert retrieve_response["status"] == "ok"
        assert retrieve_response["success"] is True
        assert retrieve_response["data"]["receipt"]["receipt_id"] == receipt.receipt_id
        assert retrieve_response["data"]["is_verified"] is False

        publishable_response = run(
            lh.hammer_retrieve_receipt(
                receipt_id=receipt.receipt_id, store_root=store_root, publishable=True
            )
        )
        assert publishable_response["status"] == "ok"
        assert publishable_response["data"]["publishable"] is True
        # The publishable view must never leak the raw goal statement.
        assert (
            publishable_response["data"]["receipt"]["result"]["request"]["goal_statement"]
            != receipt.result.request.goal_statement
        )

    def test_missing_receipt_is_structured_not_found(self, tmp_path):
        response = run(
            lh.hammer_retrieve_receipt(
                receipt_id="does-not-exist", store_root=str(tmp_path / "receipts")
            )
        )
        _assert_envelope_shape(response, operation="retrieve-receipt")
        assert response["status"] == "not_found"
        assert response["success"] is False

    def test_never_requires_native_confirmation(self):
        import inspect as _inspect

        for func in (lh.hammer_retrieve_receipt, lh.hammer_persist_receipt):
            signature = _inspect.signature(func)
            assert "confirm_native_execution" not in signature.parameters

    def test_invalid_receipt_payload_is_a_structured_error(self, tmp_path):
        response = run(
            lh.hammer_persist_receipt(
                receipt={"not": "a valid receipt"}, store_root=str(tmp_path / "receipts")
            )
        )
        assert response["status"] == "error"
        assert response["success"] is False


# ---------------------------------------------------------------------------
# Cross-cutting correlation id behavior
# ---------------------------------------------------------------------------


class TestCorrelationIdPropagation:
    def test_same_correlation_id_can_thread_through_multiple_operations(self):
        correlation_id = "corr-thread-1"

        select_response = run(
            lh.hammer_select_premises(
                goal_statement="forall x, p x -> p x",
                corpus_manifest=_corpus_manifest_payload(),
                correlation_id=correlation_id,
            )
        )
        translate_response = run(
            lh.hammer_translate(
                request_id="req-thread-1",
                source_construct="goal",
                term=tautology_term(),
                target="tptp",
                correlation_id=correlation_id,
            )
        )

        assert select_response["correlation_id"] == correlation_id
        assert translate_response["correlation_id"] == correlation_id

    def test_blank_correlation_id_is_replaced_with_a_generated_one(self):
        response = run(
            lh.hammer_translate(
                request_id="req-thread-2",
                source_construct="goal",
                term=tautology_term(),
                target="tptp",
                correlation_id="   ",
            )
        )
        assert response["correlation_id"].strip()
        assert response["correlation_id"] != "   "
