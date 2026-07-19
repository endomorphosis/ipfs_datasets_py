"""Tests for the ITP hammer release gate (HAMMER-015).

Covers the fail-closed acceptance criteria from
``docs/logic/itp_hammer_taskboard.todo.md``'s ``## HAMMER-015`` entry:

    The release gate must fail closed for missing corpus/environment
    locks, absent kernel proof, stale receipts, or any verified result
    without kernel acceptance evidence.

The gate script is loaded directly from its file path (the same pattern
``test_environment_probe.py`` uses for the HAMMER-002 probe script) so
these tests exercise the exact module the taskboard's validation command
runs, not a re-implementation.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ops" / "logic" / "release_itp_hammer_gate.py"


def _load_gate_module():
    assert SCRIPT_PATH.is_file(), f"release gate script missing at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("release_itp_hammer_gate", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate_module():
    return _load_gate_module()


@pytest.fixture(scope="module")
def generated_evidence(gate_module, tmp_path_factory):
    """Generate one real evidence bundle (genuine Lean/Coq kernel
    invocations included) shared read-only across tests in this module,
    and independently confirm it validates clean before any test mutates
    a copy of it."""

    workdir = tmp_path_factory.mktemp("hammer_release_gate")
    receipts_dir = workdir / "receipts"
    evidence = gate_module.generate_release_evidence(
        repo_root=REPO_ROOT,
        receipts_dir=receipts_dir,
        environment_lock_path=REPO_ROOT / "data" / "logic" / "itp_hammer" / "environment.json",
        benchmark_report_path=REPO_ROOT / "data" / "logic" / "itp_hammer" / "benchmark.json",
        golden_report_path=REPO_ROOT / "data" / "logic" / "itp_hammer" / "golden-report.json",
        max_receipt_age_days=gate_module.DEFAULT_MAX_RECEIPT_AGE_DAYS,
        max_environment_lock_age_days=gate_module.DEFAULT_MAX_ENVIRONMENT_LOCK_AGE_DAYS,
        max_benchmark_age_days=gate_module.DEFAULT_MAX_BENCHMARK_AGE_DAYS,
    )
    # The evidence's embedded paths are repo-relative; make them absolute
    # so validation works regardless of the pytest invocation cwd.
    evidence["environment_lock"]["path"] = str(
        (REPO_ROOT / evidence["environment_lock"]["path"]).resolve()
    )
    evidence["benchmark_report"]["path"] = str(
        (REPO_ROOT / evidence["benchmark_report"]["path"]).resolve()
    )
    evidence["golden_report"]["path"] = str(
        (REPO_ROOT / evidence["golden_report"]["path"]).resolve()
    )
    evidence["receipts_store"]["root_dir"] = str(receipts_dir.resolve())

    parser = gate_module.build_arg_parser()
    args = parser.parse_args([])
    report = gate_module.validate_release_evidence(evidence, REPO_ROOT, args)
    assert report.passed, [c.to_dict() for c in report.checks if not c.passed]

    return {"module": gate_module, "evidence": evidence, "receipts_dir": receipts_dir, "workdir": workdir}


def _args(gate_module):
    parser = gate_module.build_arg_parser()
    return parser.parse_args([])


class TestGeneratedEvidenceIsValid:
    def test_generation_produces_receipts_for_every_golden_case(self, generated_evidence):
        evidence = generated_evidence["evidence"]
        case_ids = {r["case_id"] for r in evidence["receipts"]}
        expected = {case_id for case_id, _, _ in generated_evidence["module"].GOLDEN_CASES}
        assert case_ids == expected

    def test_generation_includes_at_least_one_kernel_checked_verified_receipt(self, generated_evidence):
        evidence = generated_evidence["evidence"]
        verified = [r for r in evidence["receipts"] if r["expected_status"] == "verified"]
        assert len(verified) >= 1
        assert all(r["kernel_accepted"] is True for r in verified)

    def test_valid_evidence_passes_and_exits_zero_via_main(self, generated_evidence, tmp_path, monkeypatch):
        gate_module = generated_evidence["module"]
        evidence_path = tmp_path / "release-evidence.json"
        evidence_path.write_text(json.dumps(generated_evidence["evidence"]), encoding="utf-8")
        rc = gate_module.main(["--evidence", str(evidence_path)])
        assert rc == 0


class TestFailClosedOnMissingOrCorruptEvidence:
    def test_missing_evidence_file_fails_closed(self, generated_evidence, tmp_path):
        gate_module = generated_evidence["module"]
        rc = gate_module.main(["--evidence", str(tmp_path / "does-not-exist.json")])
        assert rc == 1

    def test_malformed_evidence_json_fails_closed(self, generated_evidence, tmp_path):
        gate_module = generated_evidence["module"]
        bad_path = tmp_path / "bad.json"
        bad_path.write_text("{not valid json", encoding="utf-8")
        rc = gate_module.main(["--evidence", str(bad_path)])
        assert rc == 1

    def test_missing_corpus_lock_fails_closed(self, generated_evidence):
        gate_module = generated_evidence["module"]
        evidence = json.loads(json.dumps(generated_evidence["evidence"]))
        del evidence["corpus_lock"]
        report = gate_module.validate_release_evidence(evidence, REPO_ROOT, _args(gate_module))
        assert not report.passed
        assert any(c.check_id == "corpus_lock_present" and not c.passed for c in report.checks)

    def test_missing_environment_lock_file_fails_closed(self, generated_evidence, tmp_path):
        gate_module = generated_evidence["module"]
        evidence = json.loads(json.dumps(generated_evidence["evidence"]))
        evidence["environment_lock"]["path"] = str(tmp_path / "does-not-exist.json")
        report = gate_module.validate_release_evidence(evidence, REPO_ROOT, _args(gate_module))
        assert not report.passed
        assert any(c.check_id == "environment_lock_present" and not c.passed for c in report.checks)

    def test_stale_environment_lock_fails_closed(self, generated_evidence, tmp_path):
        gate_module = generated_evidence["module"]
        evidence = json.loads(json.dumps(generated_evidence["evidence"]))
        live = json.loads((REPO_ROOT / "data" / "logic" / "itp_hammer" / "environment.json").read_text())
        live["generated_at"] = "2000-01-01T00:00:00Z"
        stale_path = tmp_path / "environment.json"
        stale_path.write_text(json.dumps(live), encoding="utf-8")
        evidence["environment_lock"]["path"] = str(stale_path)
        evidence["environment_lock"]["summary"] = live["summary"]
        report = gate_module.validate_release_evidence(evidence, REPO_ROOT, _args(gate_module))
        assert not report.passed
        assert any(c.check_id == "environment_lock_not_stale" and not c.passed for c in report.checks)

    def test_missing_receipt_fails_closed_as_absent_kernel_proof(self, generated_evidence):
        gate_module = generated_evidence["module"]
        evidence = json.loads(json.dumps(generated_evidence["evidence"]))
        evidence["receipts"][0]["receipt_id"] = "bafkrei" + "0" * 57
        report = gate_module.validate_release_evidence(evidence, REPO_ROOT, _args(gate_module))
        assert not report.passed
        assert any(".loadable" in c.check_id and not c.passed for c in report.checks)

    def test_stale_receipt_fails_closed(self, generated_evidence, tmp_path):
        gate_module = generated_evidence["module"]
        evidence = json.loads(json.dumps(generated_evidence["evidence"]))

        stale_receipts_dir = tmp_path / "stale_receipts"
        import shutil

        shutil.copytree(generated_evidence["receipts_dir"], stale_receipts_dir)
        ancient = (datetime.now(timezone.utc) - timedelta(days=9999)).isoformat()
        for full_file in (stale_receipts_dir / "full").glob("*.json"):
            payload = json.loads(full_file.read_text())
            payload["created_at"] = ancient
            full_file.write_text(json.dumps(payload), encoding="utf-8")

        evidence["receipts_store"]["root_dir"] = str(stale_receipts_dir)
        report = gate_module.validate_release_evidence(evidence, REPO_ROOT, _args(gate_module))
        assert not report.passed
        assert any(".not_stale" in c.check_id and not c.passed for c in report.checks)

    def test_receipt_status_drift_from_manifest_fails_closed(self, generated_evidence):
        gate_module = generated_evidence["module"]
        evidence = json.loads(json.dumps(generated_evidence["evidence"]))
        for entry in evidence["receipts"]:
            if entry["expected_status"] == "candidate":
                entry["expected_status"] = "verified"
                break
        report = gate_module.validate_release_evidence(evidence, REPO_ROOT, _args(gate_module))
        assert not report.passed
        assert any(".status_matches_manifest" in c.check_id and not c.passed for c in report.checks)

    def test_zero_verified_receipts_fails_closed(self, generated_evidence):
        gate_module = generated_evidence["module"]
        evidence = json.loads(json.dumps(generated_evidence["evidence"]))
        evidence["receipts"] = [
            r for r in evidence["receipts"] if r["expected_status"] != "verified"
        ]
        report = gate_module.validate_release_evidence(evidence, REPO_ROOT, _args(gate_module))
        assert not report.passed
        assert any(
            c.check_id == "at_least_one_kernel_checked_verified_receipt" and not c.passed
            for c in report.checks
        )

    def test_tampered_receipt_content_fails_closed(self, generated_evidence, tmp_path):
        """Directly hand-edit a persisted receipt's ``result.status`` to
        ``verified`` on disk (simulating tampering after the fact). The
        gate must not accept it: either the tampered record fails to
        reconstruct/validate at all (the trust invariant in
        ``HammerResult.__post_init__`` rejects a ``verified`` status with
        no kernel-accepted reconstruction), or -- if it somehow still
        loaded -- its digest would no longer match its ``receipt_id``.
        Either path must surface as a failed check, never a silent pass.
        """

        gate_module = generated_evidence["module"]
        evidence = json.loads(json.dumps(generated_evidence["evidence"]))

        tampered_dir = tmp_path / "tampered_receipts"
        import shutil

        shutil.copytree(generated_evidence["receipts_dir"], tampered_dir)
        candidate_only = next(r for r in evidence["receipts"] if r["case_id"] == "candidate_only")
        target_file = tampered_dir / "full" / f"{candidate_only['receipt_id']}.json"
        payload = json.loads(target_file.read_text())
        payload["result"]["status"] = "verified"
        target_file.write_text(json.dumps(payload), encoding="utf-8")

        evidence["receipts_store"]["root_dir"] = str(tampered_dir)
        report = gate_module.validate_release_evidence(evidence, REPO_ROOT, _args(gate_module))
        assert not report.passed


class TestGenerateRefusesIncompleteInputs:
    def test_generate_requires_existing_environment_lock(self, gate_module, tmp_path):
        with pytest.raises(gate_module.GateFailClosed):
            gate_module.generate_release_evidence(
                repo_root=REPO_ROOT,
                receipts_dir=tmp_path / "receipts",
                environment_lock_path=tmp_path / "does-not-exist.json",
                benchmark_report_path=REPO_ROOT / "data" / "logic" / "itp_hammer" / "benchmark.json",
                golden_report_path=REPO_ROOT / "data" / "logic" / "itp_hammer" / "golden-report.json",
                max_receipt_age_days=90,
                max_environment_lock_age_days=180,
                max_benchmark_age_days=30,
            )

    def test_generate_requires_existing_benchmark_report(self, gate_module, tmp_path):
        with pytest.raises(gate_module.GateFailClosed):
            gate_module.generate_release_evidence(
                repo_root=REPO_ROOT,
                receipts_dir=tmp_path / "receipts",
                environment_lock_path=REPO_ROOT / "data" / "logic" / "itp_hammer" / "environment.json",
                benchmark_report_path=tmp_path / "does-not-exist.json",
                golden_report_path=REPO_ROOT / "data" / "logic" / "itp_hammer" / "golden-report.json",
                max_receipt_age_days=90,
                max_environment_lock_age_days=180,
                max_benchmark_age_days=30,
            )
