"""End-to-end golden-corpus integration tests for the ITP hammer pipeline
(HAMMER-014).

These tests exercise the *full* HAMMER-001..HAMMER-012 pipeline end to end
against a small, deterministic golden corpus
(``tests/fixtures/logic/hammers/golden_corpus.json``), covering every
non-adversarial outcome the taskboard's acceptance criteria call out:

- ``verified`` -- via a genuine ``lean`` kernel subprocess
  (:class:`~ipfs_datasets_py.logic.hammers.reconstructors.lean.
  LeanReconstructor`), a genuine ``coqtop`` kernel subprocess
  (:class:`~ipfs_datasets_py.logic.hammers.reconstructors.coq.
  CoqReconstructor`), and the HAMMER-011 native-automation recovery
  fallback (:func:`~ipfs_datasets_py.logic.hammers.fallbacks.
  attempt_native_automation`) -- each gated with
  ``pytest.mark.skipif`` (mirroring ``test_reconstruction.py`` /
  ``test_itp_frontends.py``) so the suite still passes, via skip, on a host
  without the corresponding toolchain installed.
- ``candidate`` -- a solver reports a genuine, structurally-parsed proof
  listing that has not (yet) been reconstructed/kernel-checked.
- ``counterexample`` -- a solver reports a genuine countermodel.
- ``timeout`` -- every allowlisted solver exhausted its bounded budget.
- ``unavailable`` -- the only allowlisted solver has no resolvable
  executable in this environment.
- ``unsupported_translation`` -- a dependent ``Vec n`` type fails closed at
  translation time.

Adversarial cases (malformed proof trace, corrupted receipt,
premise-poisoning, and cancellation) live in ``test_adversarial_hammer.py``.

Every ``deterministic``-kind case is stamped with a fixed, non-wall-clock
timestamp (see ``_golden_helpers.FIXED_CREATED_AT``/``FIXED_COMPLETED_AT``)
so its full object graph -- and therefore its
:class:`~ipfs_datasets_py.logic.hammers.receipts.HammerReceipt` digest -- is
byte-for-byte reproducible across test runs and hosts; this is what "verify
stable corpus and receipt digests" is checked against operationally below.
The real-kernel ``verified`` cases legitimately embed real subprocess
wall-clock timing (start/finish timestamps, wall time) and are instead
checked for internal digest *self-consistency* (rebuilding twice reproduces
identical status/kernel-acceptance/structural content) and, critically,
that every one of them carries an actual, non-fabricated native kernel
acceptance record.
"""

from __future__ import annotations

import importlib.util as _importlib_util
import json
import shutil
from pathlib import Path as _Path

import pytest

# ``tests/unit_tests/logic/hammers`` and ``tests/integration/logic/hammers``
# both resolve to the plain top-level module name ``hammers`` under
# ``--import-mode=importlib`` (their shared ``logic`` parent directories are
# not themselves packages), so a package-relative ``from . import
# _golden_helpers`` here would nondeterministically resolve against
# whichever ``hammers`` package pytest happened to import first. Loading
# the sibling helper module directly by file path sidesteps that collision
# entirely.
_helpers_spec = _importlib_util.spec_from_file_location(
    "ipfs_datasets_py_hammer_test_golden_helpers",
    _Path(__file__).resolve().with_name("_golden_helpers.py"),
)
gh = _importlib_util.module_from_spec(_helpers_spec)
_helpers_spec.loader.exec_module(gh)

from ipfs_datasets_py.logic.hammers.corpus import verify_hammer_result_corpus
from ipfs_datasets_py.logic.hammers.models import HammerResultStatus
from ipfs_datasets_py.logic.hammers.receipts import (
    HammerReceipt,
    ReceiptStore,
    compute_receipt_digest,
)

LEAN_AVAILABLE = shutil.which("lean") is not None
COQ_AVAILABLE = shutil.which("coqtop") is not None


@pytest.fixture(scope="module")
def golden_manifest():
    return gh.load_golden_corpus_manifest()


# ---------------------------------------------------------------------------
# Golden corpus stability
# ---------------------------------------------------------------------------


class TestGoldenCorpusStability:
    def test_revision_is_stable_across_independent_builds(self):
        manifest_a = gh.load_golden_corpus_manifest()
        manifest_b = gh.load_golden_corpus_manifest()
        assert manifest_a.revision == manifest_b.revision
        assert manifest_a.revision.startswith("bafkrei") or manifest_a.revision.startswith(
            "sha256:"
        )

    def test_revision_changes_if_content_changes(self, golden_manifest):
        mutated = gh.load_golden_corpus_manifest()
        mutated.add_theorem(
            theorem_id="Hammer.Nat.extra_theorem_not_in_fixture",
            corpus_id="hammer-golden-fixture",
            statement="theorem extra : forall a : Nat, a = a",
            imports=["Mathlib.Data.Nat.Basic"],
        )
        assert mutated.revision != golden_manifest.revision


# ---------------------------------------------------------------------------
# Deterministic (fixed-timestamp) golden cases
# ---------------------------------------------------------------------------


class TestDeterministicGoldenCases:
    @pytest.mark.parametrize(
        "case_id, builder, expected_status",
        [
            ("candidate_only", "build_candidate_only_case", HammerResultStatus.CANDIDATE),
            ("counterexample", "build_counterexample_case", HammerResultStatus.COUNTEREXAMPLE),
            ("timeout", "build_timeout_case", HammerResultStatus.TIMEOUT),
            (
                "unsupported_translation",
                "build_unsupported_translation_case",
                HammerResultStatus.UNSUPPORTED_TRANSLATION,
            ),
        ],
    )
    def test_case_status_and_corpus_binding(
        self, golden_manifest, case_id, builder, expected_status
    ):
        build = getattr(gh, builder)
        outcome = build(golden_manifest)
        result = outcome[0] if isinstance(outcome, tuple) else outcome
        assert result.status is expected_status
        verify_hammer_result_corpus(result, golden_manifest)

    def test_unavailable_solver_case_status_and_denial_reason(self, golden_manifest):
        result, denied = gh.build_unavailable_solver_case(golden_manifest)
        assert result.status is HammerResultStatus.UNAVAILABLE
        assert result.errors
        assert denied and denied[0]["solver_name"] == "vampire"
        verify_hammer_result_corpus(result, golden_manifest)

    @pytest.mark.parametrize(
        "builder",
        [
            "build_candidate_only_case",
            "build_counterexample_case",
        ],
    )
    def test_result_is_byte_stable_across_independent_builds(self, golden_manifest, builder):
        build = getattr(gh, builder)
        result_a, _ = build(golden_manifest)
        result_b, _ = build(gh.load_golden_corpus_manifest())
        assert result_a.to_dict() == result_b.to_dict()

    def test_timeout_and_unsupported_are_byte_stable(self, golden_manifest):
        assert gh.build_timeout_case(golden_manifest).to_dict() == gh.build_timeout_case(
            gh.load_golden_corpus_manifest()
        ).to_dict()
        assert (
            gh.build_unsupported_translation_case(golden_manifest).to_dict()
            == gh.build_unsupported_translation_case(gh.load_golden_corpus_manifest()).to_dict()
        )

    @pytest.mark.parametrize(
        "builder",
        [
            "build_candidate_only_case",
            "build_counterexample_case",
        ],
    )
    def test_receipt_digest_is_stable_and_self_consistent(self, golden_manifest, builder, tmp_path):
        build = getattr(gh, builder)
        result, _ = build(golden_manifest)
        receipt_a = HammerReceipt(result=result)
        receipt_b = HammerReceipt(result=build(gh.load_golden_corpus_manifest())[0])
        assert receipt_a.receipt_id == receipt_b.receipt_id
        assert compute_receipt_digest(receipt_a) == receipt_a.receipt_id

        store = ReceiptStore(root_dir=tmp_path / "receipts")
        persisted = store.put(receipt_a, publish=True)
        reloaded = store.get(receipt_a.receipt_id)
        assert reloaded.to_dict() == receipt_a.to_dict()
        assert compute_receipt_digest(reloaded) == reloaded.receipt_id
        assert persisted.publishable is not None
        publishable = store.get_publishable(receipt_a.receipt_id)
        # The publishable view must never leak the raw goal statement.
        assert publishable["result"]["request"]["goal_statement"] != result.request.goal_statement


# ---------------------------------------------------------------------------
# Real-kernel "verified" golden cases
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean executable not available in this environment")
class TestVerifiedLeanGoldenCase:
    def test_verified_via_real_lean_kernel(self, golden_manifest):
        result, evidence = gh.build_verified_lean_case(golden_manifest)
        assert result.is_verified()
        assert result.reconstruction is not None
        assert result.reconstruction.kernel_accepted is True
        assert result.reconstruction.failure_reason is None
        assert evidence.returncode == 0
        assert "sorryAx" not in evidence.stdout
        assert evidence.command and evidence.command[0] == shutil.which("lean")
        verify_hammer_result_corpus(result, golden_manifest)

    def test_verified_result_is_structurally_reproducible(self, golden_manifest):
        result_a, evidence_a = gh.build_verified_lean_case(golden_manifest)
        result_b, evidence_b = gh.build_verified_lean_case(gh.load_golden_corpus_manifest())
        assert result_a.status == result_b.status == HammerResultStatus.VERIFIED
        assert result_a.reconstruction.kernel_accepted == result_b.reconstruction.kernel_accepted is True
        assert result_a.reconstruction.failure_reason == result_b.reconstruction.failure_reason
        assert evidence_a.checked_source == evidence_b.checked_source
        assert result_a.corpus_revision == result_b.corpus_revision

    def test_receipt_round_trips_through_storage(self, golden_manifest, tmp_path):
        result, _evidence = gh.build_verified_lean_case(golden_manifest)
        receipt = HammerReceipt(result=result)
        assert compute_receipt_digest(receipt) == receipt.receipt_id

        store = ReceiptStore(root_dir=tmp_path / "receipts")
        store.put(receipt)
        reloaded = store.get(receipt.receipt_id)
        assert reloaded.is_verified()
        assert reloaded.result.reconstruction.kernel_accepted is True
        assert compute_receipt_digest(reloaded) == reloaded.receipt_id


@pytest.mark.skipif(not COQ_AVAILABLE, reason="coqtop executable not available in this environment")
class TestVerifiedCoqGoldenCase:
    def test_verified_via_real_coq_kernel(self, golden_manifest):
        result, evidence = gh.build_verified_coq_case(golden_manifest)
        assert result.is_verified()
        assert result.reconstruction.kernel_accepted is True
        assert "Closed under the global context" in evidence.stdout
        assert evidence.command and evidence.command[0] == shutil.which("coqtop")
        verify_hammer_result_corpus(result, golden_manifest)


@pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean executable not available in this environment")
class TestVerifiedViaNativeAutomationFallback:
    def test_recovered_without_any_untrusted_solver(self, golden_manifest):
        result, attempt = gh.build_verified_via_native_automation_case(golden_manifest)
        assert result.is_verified()
        assert result.solver_attempts == []
        assert result.proof_candidate.solver_attempt_id == "native-automation-fallback"
        assert attempt.attempted is True
        assert attempt.recovered is True
        verify_hammer_result_corpus(result, golden_manifest)


# ---------------------------------------------------------------------------
# golden-report.json artifact
# ---------------------------------------------------------------------------


class TestGoldenReportArtifact:
    def test_report_is_internally_reproducible(self):
        report_a = gh.build_golden_report()
        report_b = gh.build_golden_report()
        assert report_a == report_b

    def test_every_verified_case_has_a_real_kernel_acceptance_record(self):
        report = gh.build_golden_report()
        verified_cases = [c for c in report["cases"] if c["status"] == "verified"]
        assert verified_cases, "golden report must include at least one verified case"
        for case in verified_cases:
            assert case["kind"] == "real_kernel"
            assert case["kernel_accepted"] is True
            assert case["kernel_command_executable_basename"] in {"lean", "coqtop"}

    def test_deterministic_cases_cover_every_required_outcome(self):
        report = gh.build_golden_report()
        statuses = {c["status"] for c in report["cases"]}
        required = {
            "verified",
            "candidate",
            "counterexample",
            "timeout",
            "unavailable",
            "unsupported_translation",
        }
        assert required.issubset(statuses)

    def test_report_matches_committed_artifact_or_is_written(self):
        """Regenerate ``data/logic/itp_hammer/golden-report.json`` and, if a
        copy is already committed, assert the freshly computed report is
        identical -- this is the regression check that catches any silent
        drift in the trust-contract pipeline (a changed corpus revision, a
        changed deterministic receipt digest, or a golden case that stops
        claiming ``verified``/``kernel_accepted``)."""

        report = gh.build_golden_report()
        gh.GOLDEN_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

        if gh.GOLDEN_REPORT_PATH.exists():
            committed = json.loads(gh.GOLDEN_REPORT_PATH.read_text(encoding="utf-8"))
            assert committed["corpus"]["revision"] == report["corpus"]["revision"]
            committed_by_id = {c["case_id"]: c for c in committed["cases"]}
            fresh_by_id = {c["case_id"]: c for c in report["cases"]}
            assert set(committed_by_id) == set(fresh_by_id)
            for case_id, fresh_case in fresh_by_id.items():
                committed_case = committed_by_id[case_id]
                assert committed_case["status"] == fresh_case["status"], case_id
                if fresh_case["kind"] == "deterministic":
                    assert committed_case["receipt_id"] == fresh_case["receipt_id"], case_id
                    assert committed_case["result_digest"] == fresh_case["result_digest"], case_id
                else:
                    assert committed_case["kernel_accepted"] == fresh_case["kernel_accepted"]

        gh.GOLDEN_REPORT_PATH.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        assert gh.GOLDEN_REPORT_PATH.exists()
