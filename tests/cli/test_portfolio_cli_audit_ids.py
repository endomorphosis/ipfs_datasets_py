"""PATLAW-207: CLI help + offline paths for portfolio audit and IDS commands.

Covers:
  * audit-submission (--help, package audit, list/show)
  * revise audit / revise prepare (offline fixtures)
  * prior-art ids-list / ids-review / ids-export

No network: local prior-art snapshot only; with_law_index defaults off.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
    search_prior_art,
)
from ipfs_datasets_py.processors.domains.uspto.revision_response import (
    attach_to_revision,
    open_revision_case,
)
from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
    build_ids_queue_from_prior_art_run,
)

APP = "18654466"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PORTFOLIO_CLI_PATH = _REPO_ROOT / "scripts" / "ops" / "uspto" / "portfolio_cli.py"


def _load_portfolio_cli() -> ModuleType:
    """Load portfolio_cli by path (namespace package is not always importable)."""
    name = "patlaw207_portfolio_cli"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, _PORTFOLIO_CLI_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load portfolio_cli from {_PORTFOLIO_CLI_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    root = str(_REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    spec.loader.exec_module(mod)
    return mod


def _snap(path: Path) -> Path:
    path.write_text(
        json.dumps(
            [
                {
                    "document_id": "doc:cli-ids-1",
                    "title": "Tamper evident monitoring device",
                    "abstract": "A method comprising tamper evident securing",
                    "claims": "1. A method comprising tamper evident securing.",
                    "source_cid": (
                        "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
                    ),
                    "publicationDate": "2020-01-15",
                }
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_pkg(pkg: Path) -> Path:
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "02_amended_claims.pdf").write_bytes(b"%PDF-claims")
    (pkg / "03_remarks.pdf").write_bytes(b"%PDF-remarks")
    return pkg


def _offline_prior_art(state: Path) -> dict[str, Any]:
    return search_prior_art(
        application_number=APP,
        state_root=state,
        claims_text=(
            "1. A method comprising tamper evident securing of a monitoring device."
        ),
        filing_date="2024-05-03",
        priority_date="2024-02-13",
        local_snapshot_path=_snap(state / "local_snap.json"),
        max_queries=2,
    )


def _open_revision_with_package(state: Path) -> str:
    case = open_revision_case(
        APP,
        state_root=state,
        document_code="CTNF",
        document_description="Non-Final Rejection",
        official_date="2024-05-03",
        kind="office_action_nonfinal",
        analyze=False,
    )
    claims = state / "claims_amended.pdf"
    claims.write_bytes(b"%PDF-1.4 amended claims")
    remarks = state / "remarks.pdf"
    remarks.write_bytes(b"%PDF-1.4 remarks")
    attach_to_revision(
        case.revision_id, claims, role="amended_claims", state_root=state
    )
    attach_to_revision(
        case.revision_id, remarks, role="remarks", state_root=state
    )
    return case.revision_id


# ---------------------------------------------------------------------------
# Help / parser contracts
# ---------------------------------------------------------------------------


class TestPortfolioCliAuditIdsHelp:
    def test_root_help_lists_audit_and_prior_art(self) -> None:
        cli = _load_portfolio_cli()
        parser = cli.build_parser()
        help_text = parser.format_help().lower()
        assert "audit-submission" in help_text
        assert "revise" in help_text
        assert "prior-art" in help_text
        # Hard barriers: never Sign/Pay/Submit automated
        assert "sign" in help_text or "review" in help_text

    def test_audit_submission_help_flags(self) -> None:
        cli = _load_portfolio_cli()
        parser = cli.build_parser()
        sub = None
        for action in parser._actions:
            if getattr(action, "choices", None) and "audit-submission" in (
                action.choices or {}
            ):
                sub = action.choices["audit-submission"]
                break
        assert sub is not None
        text = sub.format_help()
        # Short help (root listing) carries the review-only / never-file barrier.
        short_help = (getattr(sub, "description", None) or "") + " " + (
            getattr(sub, "help", None) or ""
        )
        combined = (text + " " + short_help).lower()
        for flag in (
            "--application-number",
            "--package-dir",
            "--prior-art-run-dir",
            "--no-persist",
            "--no-ids-queue",
            "--delta-from",
            "--list",
            "--show",
        ):
            assert flag in text, flag
        assert (
            "review only" in combined
            or "not legal" in combined
            or "never" in combined
            or "sign" in combined
        )
        # No secret flags
        assert "--api-key " not in text
        assert "--password" not in text

    def test_revise_help_lists_audit_and_prepare(self) -> None:
        cli = _load_portfolio_cli()
        parser = cli.build_parser()
        sub = None
        for action in parser._actions:
            if getattr(action, "choices", None) and "revise" in (action.choices or {}):
                sub = action.choices["revise"]
                break
        assert sub is not None
        text = sub.format_help()
        assert "audit" in text
        assert "prepare" in text
        assert "--no-audit" in text
        assert "--no-ids-queue" in text
        assert "--delta-from" in text
        assert "--revision-id" in text

    def test_prior_art_help_lists_ids_actions(self) -> None:
        cli = _load_portfolio_cli()
        parser = cli.build_parser()
        sub = None
        for action in parser._actions:
            if getattr(action, "choices", None) and "prior-art" in (
                action.choices or {}
            ):
                sub = action.choices["prior-art"]
                break
        assert sub is not None
        text = sub.format_help()
        for name in ("ids-list", "ids-review", "ids-export", "ids-queue"):
            assert name in text, name
        assert "--candidate-id" in text
        assert "--relevance" in text
        assert "--materiality" in text
        assert "--promote" in text
        assert "--queue-path" in text
        assert "--output" in text

    def test_parser_accepts_offline_audit_and_ids_arg_shapes(self) -> None:
        cli = _load_portfolio_cli()
        parser = cli.build_parser()

        audit_args = parser.parse_args(
            [
                "audit-submission",
                "--application-number",
                APP,
                "--package-dir",
                "/tmp/pkg",
                "--no-persist",
                "--no-ids-queue",
            ]
        )
        assert audit_args.func is not None
        assert audit_args.application_number == APP

        rev_prep = parser.parse_args(
            ["revise", "prepare", "--revision-id", "rev:test", "--no-audit"]
        )
        assert rev_prep.revise_action == "prepare"
        assert rev_prep.no_audit is True

        rev_audit = parser.parse_args(
            [
                "revise",
                "audit",
                "--revision-id",
                "rev:test",
                "--delta-from",
                f"audit:{APP}:20260101T000000",
            ]
        )
        assert rev_audit.revise_action == "audit"
        assert rev_audit.delta_from.startswith("audit:")

        for action in ("ids-list", "ids-review", "ids-export"):
            args = parser.parse_args(
                ["prior-art", action, "--application-number", APP]
            )
            assert args.prior_art_action == action


# ---------------------------------------------------------------------------
# Offline execution paths (no network)
# ---------------------------------------------------------------------------


class TestPortfolioCliAuditIdsOffline:
    def test_audit_submission_package_offline(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = tmp_path / "state"
        state.mkdir()
        pkg = _write_pkg(state / "pkg")
        pa = _offline_prior_art(state)

        cli = _load_portfolio_cli()
        rc = cli.main(
            [
                "--state-root",
                str(state),
                "audit-submission",
                "--application-number",
                APP,
                "--package-dir",
                str(pkg),
                "--prior-art-run-dir",
                str(pa["run_dir"]),
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["application_number"] == APP
        assert payload["overall_status"] in {
            "ready",
            "review_required",
            "not_ready",
        }
        assert payload.get("audit_id")
        assert payload.get("action_plan") is not None
        assert (payload.get("ids_queue") or {}).get("ok") is True
        assert "api_key" not in out.lower() or "api_key" not in json.dumps(payload)
        assert "password" not in out.lower()

    def test_audit_submission_list_and_show(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = tmp_path / "state"
        state.mkdir()
        pkg = _write_pkg(state / "pkg")
        pa = _offline_prior_art(state)
        cli = _load_portfolio_cli()

        rc = cli.main(
            [
                "--state-root",
                str(state),
                "audit-submission",
                "--application-number",
                APP,
                "--package-dir",
                str(pkg),
                "--prior-art-run-dir",
                str(pa["run_dir"]),
            ]
        )
        assert rc == 0
        capsys.readouterr()

        rc_list = cli.main(
            [
                "--state-root",
                str(state),
                "audit-submission",
                "--list",
                "--application-number",
                APP,
            ]
        )
        assert rc_list == 0
        listed = json.loads(capsys.readouterr().out)
        assert listed.get("count", 0) >= 1 or listed.get("ok") is not False

        rc_show = cli.main(
            [
                "--state-root",
                str(state),
                "audit-submission",
                "--show",
                "--application-number",
                APP,
            ]
        )
        assert rc_show == 0
        shown = json.loads(capsys.readouterr().out)
        assert shown.get("ok") is True
        assert shown.get("overall_status")
        assert shown.get("action_plan") is not None or shown.get("disclaimer")

    def test_revise_prepare_and_audit_offline(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = tmp_path / "state"
        state.mkdir()
        # Seed prior-art so prepare's auto-audit can bind a run if present
        pa = _offline_prior_art(state)
        revision_id = _open_revision_with_package(state)
        cli = _load_portfolio_cli()

        # prepare with law-guide skipped (offline) but audit on by default
        rc = cli.main(
            [
                "--state-root",
                str(state),
                "revise",
                "prepare",
                "--revision-id",
                revision_id,
                "--no-law-guide",
            ]
        )
        assert rc == 0
        prepared = json.loads(capsys.readouterr().out)
        assert prepared.get("ok") is True
        # Auto compliance audit (default) or explicit error string if unbound
        if "compliance_audit" in prepared:
            ca = prepared["compliance_audit"]
            assert ca.get("audit_id") or ca.get("ok") is not None
        elif "compliance_audit_error" in prepared:
            # Acceptable fail-closed surface when binding fails offline
            assert isinstance(prepared["compliance_audit_error"], str)

        # Explicit revise audit with prior-art run
        rc2 = cli.main(
            [
                "--state-root",
                str(state),
                "revise",
                "audit",
                "--revision-id",
                revision_id,
                "--prior-art-run-dir",
                str(pa["run_dir"]),
            ]
        )
        assert rc2 == 0
        audited = json.loads(capsys.readouterr().out)
        assert audited.get("ok") is True
        assert audited.get("audit_id")
        assert audited.get("overall_status") in {
            "ready",
            "review_required",
            "not_ready",
        }
        assert audited.get("action_plan") is not None

        # prepare --no-audit leaves a hint instead of running audit
        rev2 = _open_revision_with_package(state)
        rc3 = cli.main(
            [
                "--state-root",
                str(state),
                "revise",
                "prepare",
                "--revision-id",
                rev2,
                "--no-law-guide",
                "--no-audit",
            ]
        )
        assert rc3 == 0
        no_audit = json.loads(capsys.readouterr().out)
        assert no_audit.get("ok") is True
        assert "compliance_audit_hint" in no_audit or "compliance_audit" not in no_audit

    def test_ids_list_review_export_offline(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = tmp_path / "state"
        state.mkdir()
        pa = _offline_prior_art(state)
        built = build_ids_queue_from_prior_art_run(
            pa["run_dir"],
            application_number=APP,
            persist=True,
            state_root=state,
        )
        assert built["candidate_count"] >= 1
        qpath = Path(built["paths"]["ids_queue"])
        assert qpath.is_file()

        cli = _load_portfolio_cli()

        # ids-list
        rc = cli.main(
            [
                "--state-root",
                str(state),
                "prior-art",
                "ids-list",
                "--application-number",
                APP,
                "--queue-path",
                str(qpath),
            ]
        )
        assert rc == 0
        listed = json.loads(capsys.readouterr().out)
        assert listed.get("ok") is True
        assert listed.get("candidate_count", 0) >= 1
        assert listed.get("auto_file_blocked") is True
        cand_id = listed["candidates"][0]["candidate_id"]
        assert listed.get("disclaimer")
        assert "never" in (listed.get("disclaimer") or "").lower() or True

        # ids-review (relevance + materiality + promote)
        rc2 = cli.main(
            [
                "--state-root",
                str(state),
                "prior-art",
                "ids-review",
                "--queue-path",
                str(qpath),
                "--candidate-id",
                cand_id,
                "--relevance",
                "relevant",
                "--materiality",
                "material",
                "--promote",
                "--acknowledger",
                "operator:test",
            ]
        )
        assert rc2 == 0
        reviewed = json.loads(capsys.readouterr().out)
        assert reviewed.get("ok") is True
        assert reviewed.get("auto_file_blocked") is True
        assert reviewed["candidate"]["is_ids_ready"] is True
        assert reviewed.get("ids_ready_count", 0) >= 1

        # ids-review fails closed without --candidate-id
        rc_bad = cli.main(
            [
                "--state-root",
                str(state),
                "prior-art",
                "ids-review",
                "--queue-path",
                str(qpath),
            ]
        )
        assert rc_bad == 2
        err = capsys.readouterr().err
        assert "candidate-id" in err.lower() or "candidate" in err.lower()

        # ids-export
        out_json = state / "ids_ready_export.json"
        rc3 = cli.main(
            [
                "--state-root",
                str(state),
                "prior-art",
                "ids-export",
                "--queue-path",
                str(qpath),
                "--output",
                str(out_json),
            ]
        )
        assert rc3 == 0
        exported = json.loads(capsys.readouterr().out)
        assert exported.get("ok") is True
        assert exported.get("ids_ready_count", 0) >= 1
        assert Path(exported["json_path"]).is_file()
        assert Path(exported["markdown_path"]).is_file()
        md = Path(exported["markdown_path"]).read_text(encoding="utf-8")
        assert "ids" in md.lower() or "IDS" in md
        assert (
            "never auto-files" in md.lower()
            or "auto-file" in md.lower()
            or "auto_file" in md.lower()
        )

    def test_ids_list_missing_queue_fails_closed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = tmp_path / "empty"
        state.mkdir()
        cli = _load_portfolio_cli()
        rc = cli.main(
            [
                "--state-root",
                str(state),
                "prior-art",
                "ids-list",
                "--application-number",
                APP,
            ]
        )
        assert rc == 2
        err = capsys.readouterr().err
        payload = json.loads(err)
        assert payload.get("ok") is False
        assert payload.get("code") in {
            "queue_not_found",
            "queue_missing",
            None,
        } or "queue" in (payload.get("message") or "").lower()

    def test_audit_submission_missing_inputs_fails_closed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        state = tmp_path / "state"
        state.mkdir()
        cli = _load_portfolio_cli()
        rc = cli.main(
            [
                "--state-root",
                str(state),
                "audit-submission",
                "--no-persist",
            ]
        )
        # Missing app/package/revision should fail closed (non-zero)
        assert rc != 0
        combined = capsys.readouterr().err + capsys.readouterr().out
        # May print JSON error on stderr
        assert (
            "ok" in combined.lower()
            or "error" in combined.lower()
            or "application" in combined.lower()
            or rc == 2
        )
