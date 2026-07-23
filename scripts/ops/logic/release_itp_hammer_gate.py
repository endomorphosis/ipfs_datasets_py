#!/usr/bin/env python3
"""Release gate for the ITP hammer pipeline (``## HAMMER-015`` in
``docs/logic/itp_hammer_taskboard.todo.md``).

This script answers a single question, deterministically: *"is
``data/logic/itp_hammer/release-evidence.json`` sufficient to cut a
release of the ITP hammer pipeline?"* It **fails closed**: any missing
file, any parse error, any stale artifact, any receipt that cannot be
independently reloaded and re-validated, or any claimed ``verified``
result lacking an actual kernel-acceptance record causes a non-zero exit
and a machine-readable failure report -- never a silent pass.

Two modes
---------
``--generate`` (operator/CI release-prep step): builds one fresh
:class:`~ipfs_datasets_py.logic.hammers.receipts.HammerReceipt` per
HAMMER-014 golden case (reusing the same shared builder module
``tests/integration/logic/hammers/_golden_helpers.py`` that
``benchmarks/bench_itp_hammer.py`` and
``tests/integration/logic/hammers/test_end_to_end_hammer.py`` use),
persists them to a repo-local :class:`~ipfs_datasets_py.logic.hammers.
receipts.ReceiptStore`, and writes ``--evidence`` referencing them plus
the current corpus/environment/benchmark/golden-report snapshots.

Default (no ``--generate``): loads ``--evidence`` and independently
re-validates every artifact it references -- this is the mode the
taskboard's validation command runs, and the mode a CI release gate
should call on every release candidate.

Required evidence (fail closed if any is missing/invalid/stale)
-----------------------------------------------------------------
1. **Corpus lock** -- a non-empty, content-derived manifest id/revision
   (HAMMER-003).
2. **Environment lock** -- ``data/logic/itp_hammer/environment.json``
   (HAMMER-002) must exist, parse, and be no older than
   ``--max-environment-lock-age-days``.
3. **Benchmark report** -- ``data/logic/itp_hammer/benchmark.json``
   (HAMMER-015's own ``benchmarks/bench_itp_hammer.py``) must exist,
   parse, and be no older than ``--max-benchmark-age-days``.
4. **Golden report** -- ``data/logic/itp_hammer/golden-report.json``
   (HAMMER-014) must exist and parse; every case it records with
   ``status == "verified"`` must also carry ``kernel_accepted: true`` and
   ``kind == "real_kernel"`` -- an absent kernel proof for a claimed
   verified case fails the gate.
5. **Receipts** -- every receipt id the evidence file references must be
   independently reloadable from the recorded :class:`ReceiptStore` root,
   must re-pass :meth:`HammerReceipt.validate` (the trust-contract
   invariant that a ``verified`` status requires a kernel-accepted
   :class:`~ipfs_datasets_py.logic.hammers.models.ReconstructionRecord`),
   must not have been tampered with (its content digest must still match
   its ``receipt_id``), must be bound to the same corpus revision as the
   corpus lock, and must be no older than ``--max-receipt-age-days``. At
   least one receipt must actually be ``verified`` with
   ``kernel_accepted: true`` -- a release with zero kernel-checked
   theorems does not pass.

Usage
-----
    # Validate an existing evidence file (the taskboard validation command):
    PYTHONPATH=. python scripts/ops/logic/release_itp_hammer_gate.py \\
        --evidence data/logic/itp_hammer/release-evidence.json

    # (Re)generate the evidence file and its backing receipt store:
    PYTHONPATH=. python scripts/ops/logic/release_itp_hammer_gate.py \\
        --evidence data/logic/itp_hammer/release-evidence.json --generate
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ipfs_datasets_py.logic.hammers.corpus import CorpusManifest  # noqa: E402
from ipfs_datasets_py.logic.hammers.receipts import (  # noqa: E402
    HammerReceipt,
    ReceiptError,
    ReceiptNotFoundError,
    ReceiptStore,
    compute_receipt_digest,
)

SCHEMA_VERSION = "1.0.0"

#: Case-id -> HAMMER-014 golden builder name and the result status it must
#: produce, mirroring ``benchmarks/bench_itp_hammer.py``'s ``PIPELINE_CASES``
#: so both scripts always describe the same fixed set of golden cases.
GOLDEN_CASES: Tuple[Tuple[str, str, str], ...] = (
    ("candidate_only", "build_candidate_only_case", "candidate"),
    ("counterexample", "build_counterexample_case", "counterexample"),
    ("timeout", "build_timeout_case", "timeout"),
    ("unsupported_translation", "build_unsupported_translation_case", "unsupported_translation"),
    ("unavailable_solver", "build_unavailable_solver_case", "unavailable"),
    ("verified_lean", "build_verified_lean_case", "verified"),
    ("verified_coq", "build_verified_coq_case", "verified"),
    (
        "verified_native_automation_fallback",
        "build_verified_via_native_automation_case",
        "verified",
    ),
)

DEFAULT_EVIDENCE = Path("data/logic/itp_hammer/release-evidence.json")
DEFAULT_RECEIPTS_DIR = Path("data/logic/itp_hammer/receipts")
DEFAULT_ENVIRONMENT_LOCK = Path("data/logic/itp_hammer/environment.json")
DEFAULT_BENCHMARK_REPORT = Path("data/logic/itp_hammer/benchmark.json")
DEFAULT_GOLDEN_REPORT = Path("data/logic/itp_hammer/golden-report.json")

DEFAULT_MAX_RECEIPT_AGE_DAYS = 90
DEFAULT_MAX_ENVIRONMENT_LOCK_AGE_DAYS = 180
DEFAULT_MAX_BENCHMARK_AGE_DAYS = 30


class GateFailClosed(Exception):
    """Raised for any condition that must cause the gate to fail closed
    (missing/unreadable input, corruption, or a violated trust invariant).
    Distinguishing this from an ordinary bug lets ``main`` always map it to
    a clean, structured failure report rather than a raw traceback, while
    still exiting non-zero either way."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve(path_str: str, repo_root: Path) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else repo_root / path


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age_days(timestamp: Optional[datetime]) -> Optional[float]:
    if timestamp is None:
        return None
    return (_now() - timestamp).total_seconds() / 86400.0


@dataclass
class CheckResult:
    check_id: str
    passed: bool
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {"check_id": self.check_id, "passed": self.passed, "detail": self.detail}


class GateReport:
    """Accumulates :class:`CheckResult` entries. The gate passes iff every
    accumulated check passed -- there is no "mostly fine" outcome."""

    def __init__(self) -> None:
        self.checks: List[CheckResult] = []

    def record(self, check_id: str, passed: bool, detail: str) -> None:
        self.checks.append(CheckResult(check_id=check_id, passed=passed, detail=detail))

    def ok(self, check_id: str, detail: str) -> None:
        self.record(check_id, True, detail)

    def fail(self, check_id: str, detail: str) -> None:
        self.record(check_id, False, detail)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        failures = [c.to_dict() for c in self.checks if not c.passed]
        return {
            "passed": self.passed,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "check_count": len(self.checks),
            "failure_count": len(failures),
            "checks": [c.to_dict() for c in self.checks],
            "failures": failures,
        }


def _load_json(path: Path, *, label: str) -> Dict[str, Any]:
    if not path.is_file():
        raise GateFailClosed(f"{label} not found at {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise GateFailClosed(f"{label} at {path} is not valid JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# Generation (--generate)
# ---------------------------------------------------------------------------


def _import_golden_helpers():
    try:
        from tests.integration.logic.hammers import _golden_helpers  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise GateFailClosed(
            "Could not import tests.integration.logic.hammers._golden_helpers "
            "(required to generate release evidence). Ensure the repository "
            f"root is on PYTHONPATH and the test tree is present: {exc}"
        ) from exc
    return _golden_helpers


def _reconstruction_evidence_from_built(case_id: str, built: Any) -> Optional[Any]:
    """Extract the out-of-band :class:`ReconstructionEvidence` a golden
    builder produced, if any -- the shape varies per builder (see
    ``tests/integration/logic/hammers/_golden_helpers.py``)."""

    if case_id in ("verified_lean", "verified_coq") and isinstance(built, tuple):
        return built[1]
    if case_id == "verified_native_automation_fallback" and isinstance(built, tuple):
        attempt = built[1]
        return getattr(attempt, "evidence", None)
    return None


def generate_release_evidence(
    *,
    repo_root: Path,
    receipts_dir: Path,
    environment_lock_path: Path,
    benchmark_report_path: Path,
    golden_report_path: Path,
    max_receipt_age_days: int,
    max_environment_lock_age_days: int,
    max_benchmark_age_days: int,
) -> Dict[str, Any]:
    """Build every golden receipt fresh, persist them to a repo-local
    :class:`ReceiptStore`, and assemble the full release-evidence payload.

    Requires the environment lock, benchmark report, and golden report to
    already exist (this function does not run the probe/benchmark/pytest
    steps that produce them -- see the taskboard validation command for
    the expected ordering) so that a generated evidence file always
    reflects genuinely-produced artifacts rather than fabricated
    placeholders.
    """

    if not environment_lock_path.is_file():
        raise GateFailClosed(
            f"Environment lock not found at {environment_lock_path}. Run "
            "'PYTHONPATH=. python scripts/ops/logic/probe_itp_hammer_environment.py "
            f"--out {environment_lock_path}' first."
        )
    if not benchmark_report_path.is_file():
        raise GateFailClosed(
            f"Benchmark report not found at {benchmark_report_path}. Run "
            "'PYTHONPATH=. python benchmarks/bench_itp_hammer.py --fixture "
            f"tests/fixtures/logic/hammers --out {benchmark_report_path}' first."
        )
    if not golden_report_path.is_file():
        raise GateFailClosed(
            f"Golden report not found at {golden_report_path}. Run "
            "'PYTHONPATH=. python -m pytest "
            "tests/integration/logic/hammers/test_end_to_end_hammer.py -q' first."
        )

    golden_helpers = _import_golden_helpers()
    manifest: CorpusManifest = golden_helpers.load_golden_corpus_manifest()

    store = ReceiptStore(root_dir=receipts_dir)
    receipts: List[Dict[str, Any]] = []

    for case_id, builder_name, expected_status in GOLDEN_CASES:
        builder: Callable[[CorpusManifest], Any] = getattr(golden_helpers, builder_name)
        built = builder(manifest)
        result = built[0] if isinstance(built, tuple) else built
        reconstruction_evidence = _reconstruction_evidence_from_built(case_id, built)

        if result.status.value != expected_status:
            raise GateFailClosed(
                f"Golden case {case_id!r} produced status "
                f"{result.status.value!r}, expected {expected_status!r}; refusing "
                "to generate release evidence from an inconsistent golden case."
            )

        receipt = HammerReceipt(
            result=result,
            reconstruction_evidence=reconstruction_evidence,
            notes=[f"HAMMER-015 release-evidence golden case: {case_id}"],
        )
        persist_result = store.put(receipt, publish=True)

        receipts.append(
            {
                "case_id": case_id,
                "expected_status": expected_status,
                "receipt_id": receipt.receipt_id,
                "theorem_id": result.request.theorem_id,
                "itp": result.request.itp.value,
                "corpus_revision": result.corpus_revision,
                "kernel_accepted": (
                    result.reconstruction.kernel_accepted
                    if result.reconstruction is not None
                    else None
                ),
                "created_at": receipt.created_at.isoformat(),
                "storage_backend": persist_result.full.backend,
            }
        )

    environment_lock_payload = _load_json(environment_lock_path, label="environment lock")
    benchmark_payload = _load_json(benchmark_report_path, label="benchmark report")
    golden_report_payload = _load_json(golden_report_path, label="golden report")

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corpus_lock": {
            "manifest_id": manifest.manifest_id,
            "revision": manifest.revision,
            "theorem_count": len(manifest.entries),
        },
        "environment_lock": {
            "path": _relative_or_absolute(environment_lock_path, repo_root),
            "generated_at": environment_lock_payload.get("generated_at"),
            "summary": environment_lock_payload.get("summary"),
        },
        "benchmark_report": {
            "path": _relative_or_absolute(benchmark_report_path, repo_root),
            "generated_at": benchmark_payload.get("generated_at"),
            "corpus_revision": (benchmark_payload.get("corpus") or {}).get("revision"),
        },
        "golden_report": {
            "path": _relative_or_absolute(golden_report_path, repo_root),
            "corpus_revision": (golden_report_payload.get("corpus") or {}).get("revision"),
            "case_count": len(golden_report_payload.get("cases", [])),
        },
        "receipts_store": {
            "root_dir": _relative_or_absolute(receipts_dir, repo_root),
        },
        "receipts": receipts,
        "policy": {
            "max_receipt_age_days": max_receipt_age_days,
            "max_environment_lock_age_days": max_environment_lock_age_days,
            "max_benchmark_age_days": max_benchmark_age_days,
        },
    }
    return evidence


# ---------------------------------------------------------------------------
# Validation (default mode)
# ---------------------------------------------------------------------------


def check_schema(evidence: Dict[str, Any], report: GateReport) -> None:
    version = evidence.get("schema_version")
    if version == SCHEMA_VERSION:
        report.ok("schema_version", f"release-evidence schema_version={version!r} supported")
    else:
        report.fail(
            "schema_version",
            f"release-evidence schema_version={version!r} is not the supported "
            f"version {SCHEMA_VERSION!r}",
        )


def check_corpus_lock(evidence: Dict[str, Any], report: GateReport) -> Optional[str]:
    lock = evidence.get("corpus_lock")
    if not isinstance(lock, dict):
        report.fail("corpus_lock_present", "release-evidence.corpus_lock is missing or not an object")
        return None
    manifest_id = lock.get("manifest_id")
    revision = lock.get("revision")
    if not isinstance(manifest_id, str) or not manifest_id.strip():
        report.fail("corpus_lock_present", "corpus_lock.manifest_id is missing/empty")
        return None
    if not isinstance(revision, str) or not revision.strip():
        report.fail("corpus_lock_present", "corpus_lock.revision is missing/empty")
        return None
    theorem_count = lock.get("theorem_count")
    if not isinstance(theorem_count, int) or theorem_count <= 0:
        report.fail(
            "corpus_lock_present",
            f"corpus_lock.theorem_count must be a positive integer, got {theorem_count!r}",
        )
        return None
    report.ok(
        "corpus_lock_present",
        f"corpus locked to manifest_id={manifest_id!r} revision={revision!r} "
        f"theorem_count={theorem_count}",
    )
    return revision


def check_environment_lock(
    evidence: Dict[str, Any], repo_root: Path, report: GateReport, *, max_age_days: int
) -> None:
    lock = evidence.get("environment_lock")
    if not isinstance(lock, dict) or not lock.get("path"):
        report.fail("environment_lock_present", "release-evidence.environment_lock.path is missing")
        return

    path = _resolve(lock["path"], repo_root)
    try:
        live_payload = _load_json(path, label="environment lock")
    except GateFailClosed as exc:
        report.fail("environment_lock_present", str(exc))
        return
    report.ok("environment_lock_present", f"environment lock file present at {path}")

    for key in ("schema_version", "generated_at", "summary", "surfaces"):
        if key not in live_payload:
            report.fail(
                "environment_lock_schema",
                f"environment lock at {path} is missing required key {key!r}",
            )
            return
    report.ok("environment_lock_schema", f"environment lock at {path} has the required shape")

    generated_at = _parse_timestamp(live_payload.get("generated_at"))
    age_days = _age_days(generated_at)
    if age_days is None:
        report.fail(
            "environment_lock_not_stale",
            f"environment lock at {path} has an unparsable generated_at timestamp",
        )
    elif age_days > max_age_days:
        report.fail(
            "environment_lock_not_stale",
            f"environment lock at {path} is {age_days:.1f} days old, exceeding the "
            f"{max_age_days}-day freshness budget; regenerate with "
            "scripts/ops/logic/probe_itp_hammer_environment.py",
        )
    else:
        report.ok(
            "environment_lock_not_stale",
            f"environment lock at {path} is {age_days:.1f} days old "
            f"(budget: {max_age_days} days)",
        )

    recorded_summary = lock.get("summary")
    live_summary = live_payload.get("summary")
    if recorded_summary != live_summary:
        report.fail(
            "environment_lock_matches_source",
            f"release-evidence's embedded environment_lock.summary does not match "
            f"the live file at {path} (drifted); regenerate release evidence",
        )
    else:
        report.ok(
            "environment_lock_matches_source",
            "release-evidence's embedded environment lock summary matches the live file",
        )


def check_benchmark_report(
    evidence: Dict[str, Any], repo_root: Path, report: GateReport, *, max_age_days: int
) -> None:
    ref = evidence.get("benchmark_report")
    if not isinstance(ref, dict) or not ref.get("path"):
        report.fail("benchmark_report_present", "release-evidence.benchmark_report.path is missing")
        return

    path = _resolve(ref["path"], repo_root)
    try:
        payload = _load_json(path, label="benchmark report")
    except GateFailClosed as exc:
        report.fail("benchmark_report_present", str(exc))
        return
    report.ok("benchmark_report_present", f"benchmark report present at {path}")

    generated_at = _parse_timestamp(payload.get("generated_at"))
    age_days = _age_days(generated_at)
    if age_days is None:
        report.fail(
            "benchmark_report_not_stale",
            f"benchmark report at {path} has an unparsable generated_at timestamp",
        )
    elif age_days > max_age_days:
        report.fail(
            "benchmark_report_not_stale",
            f"benchmark report at {path} is {age_days:.1f} days old, exceeding the "
            f"{max_age_days}-day freshness budget; regenerate with "
            "benchmarks/bench_itp_hammer.py",
        )
    else:
        report.ok(
            "benchmark_report_not_stale",
            f"benchmark report at {path} is {age_days:.1f} days old "
            f"(budget: {max_age_days} days)",
        )


def check_golden_report(
    evidence: Dict[str, Any], repo_root: Path, report: GateReport, *, corpus_revision: Optional[str]
) -> None:
    ref = evidence.get("golden_report")
    if not isinstance(ref, dict) or not ref.get("path"):
        report.fail("golden_report_present", "release-evidence.golden_report.path is missing")
        return

    path = _resolve(ref["path"], repo_root)
    try:
        payload = _load_json(path, label="golden report")
    except GateFailClosed as exc:
        report.fail("golden_report_present", str(exc))
        return
    report.ok("golden_report_present", f"golden report present at {path}")

    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        report.fail("golden_report_kernel_proof", f"golden report at {path} has no cases recorded")
        return

    verified_cases = [c for c in cases if isinstance(c, dict) and c.get("status") == "verified"]
    if not verified_cases:
        report.fail(
            "golden_report_kernel_proof",
            f"golden report at {path} records zero 'verified' cases; a release "
            "must demonstrate at least one kernel-checked theorem",
        )
        return

    missing_proof = [
        c.get("case_id")
        for c in verified_cases
        if c.get("kind") != "real_kernel" or c.get("kernel_accepted") is not True
    ]
    if missing_proof:
        report.fail(
            "golden_report_kernel_proof",
            f"golden report at {path} claims 'verified' for case(s) {missing_proof!r} "
            "without a real_kernel kernel_accepted=true record -- absent kernel proof",
        )
    else:
        report.ok(
            "golden_report_kernel_proof",
            f"every 'verified' case in the golden report ({len(verified_cases)} of "
            f"{len(cases)}) carries a real_kernel kernel_accepted=true record",
        )

    golden_corpus_revision = (payload.get("corpus") or {}).get("revision")
    if corpus_revision is not None and golden_corpus_revision != corpus_revision:
        report.fail(
            "golden_report_corpus_consistency",
            f"golden report corpus revision {golden_corpus_revision!r} does not match "
            f"release-evidence corpus_lock.revision {corpus_revision!r}",
        )
    else:
        report.ok(
            "golden_report_corpus_consistency",
            "golden report corpus revision matches release-evidence corpus lock",
        )


def check_receipts(
    evidence: Dict[str, Any],
    repo_root: Path,
    report: GateReport,
    *,
    corpus_revision: Optional[str],
    max_receipt_age_days: int,
) -> None:
    store_ref = evidence.get("receipts_store")
    if not isinstance(store_ref, dict) or not store_ref.get("root_dir"):
        report.fail("receipts_store_present", "release-evidence.receipts_store.root_dir is missing")
        return

    root_dir = _resolve(store_ref["root_dir"], repo_root)
    if not root_dir.is_dir():
        report.fail("receipts_store_present", f"receipts store root not found at {root_dir}")
        return
    report.ok("receipts_store_present", f"receipts store root present at {root_dir}")

    receipts_ref = evidence.get("receipts")
    if not isinstance(receipts_ref, list) or not receipts_ref:
        report.fail("receipts_present", "release-evidence.receipts is missing/empty")
        return

    store = ReceiptStore(root_dir=root_dir)
    verified_and_kernel_checked = 0

    for entry in receipts_ref:
        if not isinstance(entry, dict):
            report.fail("receipt_entry_shape", f"release-evidence receipt entry is not an object: {entry!r}")
            continue
        case_id = entry.get("case_id", "<unknown>")
        receipt_id = entry.get("receipt_id")
        expected_status = entry.get("expected_status")
        prefix = f"receipt[{case_id}]"

        if not isinstance(receipt_id, str) or not receipt_id.strip():
            report.fail(f"{prefix}.receipt_id", "receipt_id is missing/empty")
            continue

        try:
            receipt = store.get(receipt_id)
        except ReceiptNotFoundError as exc:
            report.fail(
                f"{prefix}.loadable",
                f"receipt {receipt_id!r} could not be loaded from {root_dir}: {exc} "
                "-- absent kernel proof / missing receipt evidence",
            )
            continue
        except Exception as exc:  # noqa: BLE001
            report.fail(
                f"{prefix}.loadable",
                f"receipt {receipt_id!r} could not be loaded from {root_dir}: {exc}",
            )
            continue
        report.ok(f"{prefix}.loadable", f"receipt {receipt_id!r} loaded from {root_dir}")

        try:
            receipt.validate()
        except ReceiptError as exc:
            report.fail(f"{prefix}.trust_contract_valid", f"receipt {receipt_id!r} failed validation: {exc}")
            continue
        report.ok(f"{prefix}.trust_contract_valid", f"receipt {receipt_id!r} passed trust-contract validation")

        recomputed_digest = compute_receipt_digest(receipt)
        if recomputed_digest != receipt.receipt_id:
            report.fail(
                f"{prefix}.not_tampered",
                f"receipt {receipt_id!r} content digest mismatch (recomputed "
                f"{recomputed_digest!r}) -- possible tampering",
            )
        else:
            report.ok(f"{prefix}.not_tampered", f"receipt {receipt_id!r} content digest matches receipt_id")

        result = receipt.result
        if corpus_revision is not None and result.corpus_revision != corpus_revision:
            report.fail(
                f"{prefix}.corpus_revision_consistent",
                f"receipt {receipt_id!r} corpus_revision {result.corpus_revision!r} does "
                f"not match release corpus_lock.revision {corpus_revision!r}",
            )
        else:
            report.ok(
                f"{prefix}.corpus_revision_consistent",
                f"receipt {receipt_id!r} corpus_revision matches release corpus lock",
            )

        age_days = _age_days(receipt.created_at if receipt.created_at.tzinfo else receipt.created_at.replace(tzinfo=timezone.utc))
        if age_days is None or age_days > max_receipt_age_days:
            report.fail(
                f"{prefix}.not_stale",
                f"receipt {receipt_id!r} is "
                f"{'of unknown age' if age_days is None else f'{age_days:.1f} days old'}, "
                f"exceeding the {max_receipt_age_days}-day freshness budget -- stale receipt",
            )
        else:
            report.ok(
                f"{prefix}.not_stale",
                f"receipt {receipt_id!r} is {age_days:.1f} days old "
                f"(budget: {max_receipt_age_days} days)",
            )

        if expected_status is not None and result.status.value != expected_status:
            report.fail(
                f"{prefix}.status_matches_manifest",
                f"receipt {receipt_id!r} status {result.status.value!r} does not match "
                f"release-evidence expected_status {expected_status!r} -- manifest drift",
            )
        else:
            report.ok(
                f"{prefix}.status_matches_manifest",
                f"receipt {receipt_id!r} status matches release-evidence manifest",
            )

        if result.status.value == "verified":
            reconstruction = result.reconstruction
            if reconstruction is None or reconstruction.kernel_accepted is not True:
                report.fail(
                    f"{prefix}.kernel_acceptance_evidence",
                    f"receipt {receipt_id!r} claims status='verified' without a "
                    "kernel_accepted=true ReconstructionRecord -- verified result "
                    "without kernel acceptance evidence",
                )
            else:
                report.ok(
                    f"{prefix}.kernel_acceptance_evidence",
                    f"receipt {receipt_id!r} 'verified' status is backed by a "
                    "kernel_accepted=true ReconstructionRecord",
                )
                verified_and_kernel_checked += 1

    if verified_and_kernel_checked == 0:
        report.fail(
            "at_least_one_kernel_checked_verified_receipt",
            "no receipt in release-evidence.receipts is both status='verified' and "
            "kernel_accepted=true -- a release must demonstrate at least one "
            "actual kernel-checked theorem",
        )
    else:
        report.ok(
            "at_least_one_kernel_checked_verified_receipt",
            f"{verified_and_kernel_checked} receipt(s) are verified with kernel "
            "acceptance evidence",
        )


def validate_release_evidence(evidence: Dict[str, Any], repo_root: Path, args: argparse.Namespace) -> GateReport:
    report = GateReport()
    check_schema(evidence, report)
    corpus_revision = check_corpus_lock(evidence, report)
    check_environment_lock(
        evidence, repo_root, report, max_age_days=args.max_environment_lock_age_days
    )
    check_benchmark_report(
        evidence, repo_root, report, max_age_days=args.max_benchmark_age_days
    )
    check_golden_report(evidence, repo_root, report, corpus_revision=corpus_revision)
    check_receipts(
        evidence,
        repo_root,
        report,
        corpus_revision=corpus_revision,
        max_receipt_age_days=args.max_receipt_age_days,
    )
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=DEFAULT_EVIDENCE,
        help=f"Path to release-evidence.json (default: {DEFAULT_EVIDENCE})",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="(Re)generate --evidence and its backing receipt store from fresh "
        "golden-case receipts, instead of validating an existing file.",
    )
    parser.add_argument(
        "--receipts-dir",
        type=Path,
        default=DEFAULT_RECEIPTS_DIR,
        help=f"Receipt store root used by --generate (default: {DEFAULT_RECEIPTS_DIR})",
    )
    parser.add_argument(
        "--environment-lock",
        type=Path,
        default=DEFAULT_ENVIRONMENT_LOCK,
        help=f"Environment lock snapshot used by --generate (default: {DEFAULT_ENVIRONMENT_LOCK})",
    )
    parser.add_argument(
        "--benchmark-report",
        type=Path,
        default=DEFAULT_BENCHMARK_REPORT,
        help=f"Benchmark report used by --generate (default: {DEFAULT_BENCHMARK_REPORT})",
    )
    parser.add_argument(
        "--golden-report",
        type=Path,
        default=DEFAULT_GOLDEN_REPORT,
        help=f"Golden corpus report used by --generate (default: {DEFAULT_GOLDEN_REPORT})",
    )
    parser.add_argument(
        "--max-receipt-age-days",
        type=int,
        default=DEFAULT_MAX_RECEIPT_AGE_DAYS,
        help=f"Reject receipts older than this many days (default: {DEFAULT_MAX_RECEIPT_AGE_DAYS})",
    )
    parser.add_argument(
        "--max-environment-lock-age-days",
        type=int,
        default=DEFAULT_MAX_ENVIRONMENT_LOCK_AGE_DAYS,
        help="Reject an environment lock older than this many days "
        f"(default: {DEFAULT_MAX_ENVIRONMENT_LOCK_AGE_DAYS})",
    )
    parser.add_argument(
        "--max-benchmark-age-days",
        type=int,
        default=DEFAULT_MAX_BENCHMARK_AGE_DAYS,
        help=f"Reject a benchmark report older than this many days (default: {DEFAULT_MAX_BENCHMARK_AGE_DAYS})",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    repo_root = _repo_root()
    evidence_path = args.evidence if args.evidence.is_absolute() else repo_root / args.evidence

    try:
        if args.generate:
            evidence = generate_release_evidence(
                repo_root=repo_root,
                receipts_dir=(
                    args.receipts_dir if args.receipts_dir.is_absolute() else repo_root / args.receipts_dir
                ),
                environment_lock_path=(
                    args.environment_lock
                    if args.environment_lock.is_absolute()
                    else repo_root / args.environment_lock
                ),
                benchmark_report_path=(
                    args.benchmark_report
                    if args.benchmark_report.is_absolute()
                    else repo_root / args.benchmark_report
                ),
                golden_report_path=(
                    args.golden_report if args.golden_report.is_absolute() else repo_root / args.golden_report
                ),
                max_receipt_age_days=args.max_receipt_age_days,
                max_environment_lock_age_days=args.max_environment_lock_age_days,
                max_benchmark_age_days=args.max_benchmark_age_days,
            )
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "generated": True,
                        "evidence_path": str(evidence_path),
                        "receipt_count": len(evidence["receipts"]),
                        "corpus_revision": evidence["corpus_lock"]["revision"],
                    },
                    sort_keys=True,
                )
            )
        else:
            evidence = _load_json(evidence_path, label="release evidence")

        report = validate_release_evidence(evidence, repo_root, args)
    except GateFailClosed as exc:
        # Fail closed: any input-loading problem is a hard failure, never a
        # silent pass.
        failure_report = {
            "passed": False,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "check_count": 0,
            "failure_count": 1,
            "checks": [],
            "failures": [{"check_id": "evidence_loadable", "passed": False, "detail": str(exc)}],
        }
        print(json.dumps(failure_report, indent=2, sort_keys=True))
        return 1
    except Exception as exc:  # noqa: BLE001 - fail closed on any unexpected error
        failure_report = {
            "passed": False,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "check_count": 0,
            "failure_count": 1,
            "checks": [],
            "failures": [
                {
                    "check_id": "unexpected_error",
                    "passed": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            ],
        }
        print(json.dumps(failure_report, indent=2, sort_keys=True))
        return 1

    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
