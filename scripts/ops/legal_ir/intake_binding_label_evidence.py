#!/usr/bin/env python3
"""Bind local declared label evidence while verification and admission stay pending."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer-packet", type=Path, required=True)
    parser.add_argument("--expected-packet-file-sha256", required=True)
    parser.add_argument("--recording-report", type=Path, required=True)
    parser.add_argument("--expected-recording-report-file-sha256", required=True)
    parser.add_argument("--evidence-package", type=Path, required=True)
    parser.add_argument("--expected-evidence-package-file-sha256", required=True)
    for name in ("organizer", "selected-process", "cohort-policy"):
        parser.add_argument("--" + name, nargs=2, metavar=("PATH", "SHA256"))
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from ipfs_datasets_py.logic.legal_ir import canonical_label_evidence_intake_workflow as owner

    expected = REPOSITORY_ROOT / "ipfs_datasets_py/logic/legal_ir/canonical_label_evidence_intake_workflow.py"
    if Path(owner.__file__).resolve() != expected:
        parser.error("label evidence intake import comes from another checkout")

    def selection(value):
        return None if value is None else {"path": value[0], "sha256": value[1]}

    try:
        report = owner.run_label_evidence_intake(
            args.reviewer_packet, args.expected_packet_file_sha256,
            args.recording_report, args.expected_recording_report_file_sha256,
            args.evidence_package, args.expected_evidence_package_file_sha256, args.output_directory,
            organizer_binding=selection(args.organizer), selected_process_binding=selection(args.selected_process),
            cohort_policy_binding=selection(args.cohort_policy), repository_root=REPOSITORY_ROOT,
        )
    except (ValueError, OSError, ImportError, RuntimeError) as error:
        print(json.dumps(dict(status="failed", reason=str(error), qualified=False)), file=sys.stderr)
        return 2
    print(json.dumps(dict(report=str(args.output_directory.absolute() / "report_private.json"),
        status=report["status"], item_count=report["item_count"],
        declared_package_item_count=report["declared_package_item_count"],
        verification_status="pending", admission_status="pending", qualified=False,
        content_sha256=report["content_sha256"]), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
