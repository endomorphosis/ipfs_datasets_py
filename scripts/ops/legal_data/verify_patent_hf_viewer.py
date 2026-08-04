#!/usr/bin/env python3
"""Verify patent HF v2 public-release DLP, rights, and Dataset Viewer gates.

Default mode is **credential-free** and offline:

1. Refuse to run when Hub credentials are already resolved in the environment
   (admission must complete before tokens are available).
2. Load a staged multi-repo release tree and/or release rows.
3. Run :class:`PatentHFReleasePolicyV2` DLP/rights/integrity gates.
4. Validate Dataset Viewer contracts against an offline fake service.

A successful HTTP-shaped ``viewer: true`` payload alone is never sufficient.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.hf_release_policy_v2 import (  # noqa: E402
    DEFAULT_MAX_SOURCE_AGE_DAYS,
    RELEASE_POLICY_V2_SHA256,
    RELEASE_POLICY_V2_VERSION,
    VIEWER_ENDPOINTS,
    AdmissionRejectedError,
    CredentialPrematureError,
    FakeDatasetViewerService,
    FakeViewerGateway,
    PatentHFReleasePolicyV2,
    ReleasePolicyV2Error,
    assert_credentials_unresolved,
    inventory_from_release_object,
    load_staged_release_inventory,
)


class PatentHFViewerVerifyError(RuntimeError):
    """Raised when Viewer / DLP verification cannot complete fail-closed."""


def _load_json_rows(path: Path) -> list[Mapping[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise PatentHFViewerVerifyError(f"input is empty: {path}")
    if path.suffix.lower() == ".ndjson" or text.startswith("{"):
        # NDJSON or single object — prefer NDJSON when multi-line objects
        rows: list[Mapping[str, Any]] = []
        if "\n" in text and not text.lstrip().startswith("["):
            for line_no, line in enumerate(text.splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise PatentHFViewerVerifyError(
                        f"invalid NDJSON on line {line_no}: {exc}"
                    ) from exc
                if not isinstance(value, Mapping):
                    raise PatentHFViewerVerifyError(
                        f"NDJSON line {line_no} must be an object"
                    )
                rows.append(value)
            if rows:
                return rows
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PatentHFViewerVerifyError(f"invalid JSON input: {exc}") from exc
        if isinstance(payload, Mapping):
            if isinstance(payload.get("records"), list):
                payload = payload["records"]
            else:
                return [payload]
        if not isinstance(payload, list) or not payload:
            raise PatentHFViewerVerifyError(
                "input must be a non-empty JSON array of rows"
            )
        for index, item in enumerate(payload):
            if not isinstance(item, Mapping):
                raise PatentHFViewerVerifyError(f"row[{index}] must be an object")
        return list(payload)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PatentHFViewerVerifyError(f"invalid JSON input: {exc}") from exc
    if isinstance(payload, Mapping) and isinstance(payload.get("records"), list):
        payload = payload["records"]
    if not isinstance(payload, list) or not payload:
        raise PatentHFViewerVerifyError(
            "input must be a non-empty JSON array of rows"
        )
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise PatentHFViewerVerifyError(f"row[{index}] must be an object")
    return list(payload)


def verify_patent_hf_viewer(
    *,
    release_dir: str | Path | None = None,
    rows_path: str | Path | None = None,
    as_of: str = "2026-08-01",
    max_source_age_days: int = DEFAULT_MAX_SOURCE_AGE_DAYS,
    run_viewer_gate: bool = True,
    require_admitted: bool = True,
    force_viewer_invalid: bool = False,
) -> dict[str, Any]:
    """Run DLP/rights/Viewer admission gates without resolving credentials.

    Parameters
    ----------
    release_dir:
        Path to a staged multi-repo release tree (preferred).
    rows_path:
        Optional JSON/NDJSON of release rows for the row-level DLP gate.
    as_of:
        Reference date for mandatory source freshness.
    max_source_age_days:
        Maximum age of mandatory sources.
    run_viewer_gate:
        When True (default), validate Dataset Viewer contracts offline.
    require_admitted:
        When True, raise if admission is refused.
    force_viewer_invalid:
        Force fake Viewer is-valid=false (negative testing).
    """
    try:
        assert_credentials_unresolved()
    except CredentialPrematureError as exc:
        raise PatentHFViewerVerifyError(str(exc)) from exc

    policy = PatentHFReleasePolicyV2(
        as_of=as_of, max_source_age_days=max_source_age_days
    )
    rows: list[Mapping[str, Any]] | None = None
    if rows_path is not None:
        rows = _load_json_rows(Path(rows_path).expanduser().resolve())

    inventory = None
    staged_root = None
    if release_dir is not None:
        staged_root = Path(release_dir).expanduser().resolve()
        if not staged_root.is_dir():
            raise PatentHFViewerVerifyError(
                f"release_dir is not a directory: {staged_root}"
            )
        try:
            inventory = load_staged_release_inventory(staged_root)
        except ReleasePolicyV2Error as exc:
            raise PatentHFViewerVerifyError(str(exc)) from exc
    elif rows is not None:
        try:
            from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import (
                build_patent_hf_release_v2,
            )
        except ImportError as exc:
            raise PatentHFViewerVerifyError(
                "hf_release_v2 is required to materialize rows for Viewer gates"
            ) from exc
        try:
            release = build_patent_hf_release_v2(rows, dry_run=True)
            inventory = inventory_from_release_object(release)
        except Exception as exc:
            raise PatentHFViewerVerifyError(
                f"cannot materialize release from rows: {exc}"
            ) from exc
    else:
        raise PatentHFViewerVerifyError("provide --release-dir and/or --rows")

    viewer_gateway = None
    if inventory is not None and run_viewer_gate:
        service = FakeDatasetViewerService(
            inventory=inventory, force_invalid=force_viewer_invalid
        )
        viewer_gateway = FakeViewerGateway(service)

    decision = policy.admit_public_release(
        rows=rows,
        inventory=inventory,
        staged_root=None if inventory is not None else staged_root,
        viewer_gateway=viewer_gateway,
        run_viewer_gate=run_viewer_gate and inventory is not None,
    )

    result: dict[str, Any] = {
        "admitted": decision.admitted,
        "credentials_resolved": decision.credentials_resolved,
        "gate_results": [item.to_dict() for item in decision.gate_results],
        "policy_sha256": decision.policy_sha256,
        "policy_version": decision.policy_version,
        "reason_codes": list(decision.reason_codes),
        "finding_count": len(decision.findings),
        "findings": [item.to_dict() for item in decision.findings],
        "release_dir": str(staged_root) if staged_root is not None else None,
        "rows_path": str(rows_path) if rows_path is not None else None,
        "viewer_endpoints_checked": list(VIEWER_ENDPOINTS)
        if run_viewer_gate
        else [],
        "expected_policy_sha256": RELEASE_POLICY_V2_SHA256,
        "expected_policy_version": RELEASE_POLICY_V2_VERSION,
    }
    if decision.policy_sha256 != RELEASE_POLICY_V2_SHA256:
        result["reason_codes"] = sorted(
            set(result["reason_codes"]) | {"policy.drift"}
        )
        result["admitted"] = False

    if require_admitted and not result["admitted"]:
        raise AdmissionRejectedError(
            "public release rejected before credentials: "
            + ", ".join(result["reason_codes"])
        )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify patent HF v2 DLP, rights, and Dataset Viewer gates "
            "(credential-free; offline fake Viewer by default)."
        )
    )
    parser.add_argument(
        "--release-dir",
        type=Path,
        default=None,
        help="Staged multi-repo release tree to admit",
    )
    parser.add_argument(
        "--rows",
        type=Path,
        default=None,
        dest="rows_path",
        help="Optional JSON/NDJSON release rows for the row-level DLP gate",
    )
    parser.add_argument(
        "--as-of",
        default="2026-08-01",
        help="Reference date for mandatory source freshness (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--max-source-age-days",
        type=int,
        default=DEFAULT_MAX_SOURCE_AGE_DAYS,
        help=f"Maximum age of mandatory sources (default {DEFAULT_MAX_SOURCE_AGE_DAYS})",
    )
    parser.add_argument(
        "--skip-viewer-gate",
        action="store_true",
        help="Skip Dataset Viewer contract checks (not recommended)",
    )
    parser.add_argument(
        "--allow-reject",
        action="store_true",
        help="Exit 0 even when admission is refused (still prints reasons)",
    )
    parser.add_argument(
        "--force-viewer-invalid",
        action="store_true",
        help="Force fake Viewer is-valid=false (negative testing)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full admission receipt as JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_patent_hf_viewer(
            release_dir=args.release_dir,
            rows_path=args.rows_path,
            as_of=args.as_of,
            max_source_age_days=args.max_source_age_days,
            run_viewer_gate=not args.skip_viewer_gate,
            require_admitted=not args.allow_reject,
            force_viewer_invalid=args.force_viewer_invalid,
        )
    except AdmissionRejectedError as exc:
        payload = {
            "admitted": False,
            "error": str(exc),
            "policy_version": RELEASE_POLICY_V2_VERSION,
            "policy_sha256": RELEASE_POLICY_V2_SHA256,
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"REJECTED: {exc}", file=sys.stderr)
        return 1
    except (
        PatentHFViewerVerifyError,
        CredentialPrematureError,
        ReleasePolicyV2Error,
    ) as exc:
        payload = {
            "admitted": False,
            "error": str(exc),
            "policy_version": RELEASE_POLICY_V2_VERSION,
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "ADMITTED" if result["admitted"] else "REJECTED"
        print(
            f"{status} policy={result['policy_version']}"
            f" sha256={result['policy_sha256'][:16]}…"
            f" gates={len(result.get('gate_results') or [])}"
            f" findings={result.get('finding_count', 0)}"
        )
        if result.get("reason_codes"):
            print("reasons: " + ", ".join(result["reason_codes"]))
        for gate in result.get("gate_results") or []:
            mark = "PASS" if gate.get("passed") else "FAIL"
            extra = ""
            if gate.get("reason_codes"):
                extra = " " + ",".join(gate["reason_codes"])
            print(f"  [{mark}] {gate.get('name')}{extra}")
    return 0 if result["admitted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
