#!/usr/bin/env python3
"""USPTO portfolio operator CLI — public ODP automation + private import helpers.

Subcommands:
  discover       Search ODP by inventor name; merge into portfolio seed
  refresh        Batch public status sync for seed matters
  confirm        Mark application numbers as operator-confirmed ownership
  prepare-import Build export_manifest.json + authorization.json for a folder
  import-folder  Import a local export folder into the private store
  attended-export
                 Launch Patent Center export (uses saved login session if present)
  export-ui      Automated Patent Center UI export (SSO + private APIs + eGrant/IFW)
  filing-checklist
                 Content-free filing checklist + hard barriers (never sign/pay/submit)
  filing-assist  Attended Patent Center assist (nav + checklist + receipt watch)
  watch-receipts Poll post_submit_receipts/<app>/ after human Submit and import
  revise         Respond to deficiency letters / office actions (scan, open, prepare)
  prior-art      Plan/search public prior art for claim distinguishability (no novelty conclusions)
  audit-submission
                 Audit package vs MPEP/CFR filing rules + prior-art coverage (review only)
  login / login-status / logout
                 Patent Center password+OTP login helper (refs/prompts; no secret echo)
  show           Print seed / last review summary

Credentials:
  Public ODP uses env:USPTO_ODP_API_KEY (never pass the raw key on the CLI).
  Patent Center login uses env:USPTO_USERNAME / USPTO_PASSWORD / USPTO_TOTP_SECRET
  (or prompts). Secrets are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (  # noqa: E402
    PortfolioAutomationError,
    PortfolioSeed,
    build_portfolio_dashboard,
    confirm_ownership,
    default_state_root,
    discover_public_by_inventor,
    drop_matters,
    import_export_folder,
    import_ready_inbox_folders,
    keep_only_matters,
    load_portfolio_seed,
    merge_matters,
    save_portfolio_seed,
    scan_private_inbox,
    summarize_public_documents,
    sync_public_status_batch,
    write_export_package_sidecar,
)


def _state_root(args: argparse.Namespace) -> Path:
    if getattr(args, "state_root", None):
        return Path(args.state_root).expanduser().resolve()
    return default_state_root()


def _seed_path(state: Path) -> Path:
    return state / "portfolio_seed.json"


def _ensure_env_key() -> None:
    if not os.environ.get("USPTO_ODP_API_KEY"):
        env_file = Path.home() / ".config" / "ipfs_datasets_py" / "uspto.env"
        if env_file.is_file():
            # Soft hint only — do not auto-source secrets into unrelated processes
            # without operator intent; print guidance.
            raise PortfolioAutomationError(
                f"USPTO_ODP_API_KEY not set; run: source {env_file}",
                code="missing_odp_key",
            )
        raise PortfolioAutomationError(
            "USPTO_ODP_API_KEY not set",
            code="missing_odp_key",
        )


def _cmd_discover(args: argparse.Namespace) -> int:
    _ensure_env_key()
    state = _state_root(args)
    state.mkdir(parents=True, exist_ok=True)
    found = discover_public_by_inventor(
        args.inventor_name,
        limit=int(args.limit),
    )
    seed_path = _seed_path(state)
    if seed_path.is_file():
        seed = load_portfolio_seed(seed_path)
        seed.matters = merge_matters(seed.matters, found)
    else:
        seed = PortfolioSeed(
            tenant_id=str(args.tenant),
            matters=found,
            credential_ref="env:USPTO_ODP_API_KEY",
            discovery={
                "method": "odp_public_search",
                "inventor_name": args.inventor_name,
                "note": "Candidates only until confirmed via portfolio_cli confirm",
            },
        )
    seed.discovery = {
        **dict(seed.discovery),
        "method": "odp_public_search",
        "inventor_name": args.inventor_name,
        "last_discover_count": len(found),
    }
    save_portfolio_seed(seed, seed_path)
    payload = {
        "ok": True,
        "seed_path": str(seed_path),
        "discovered": len(found),
        "portfolio_size": len(seed.matters),
        "applications": [m.application_number for m in found],
    }
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_refresh(args: argparse.Namespace) -> int:
    _ensure_env_key()
    state = _state_root(args)
    seed_path = _seed_path(state)
    if not seed_path.is_file():
        raise PortfolioAutomationError(
            f"missing seed at {seed_path}; run discover first",
            code="missing_seed",
        )
    seed = load_portfolio_seed(seed_path)
    store = state / "odp_store"
    docs_root = (
        Path(args.documents_root).expanduser().resolve()
        if getattr(args, "documents_root", None)
        else state / "public_docs"
    )
    report = sync_public_status_batch(
        seed,
        store_root=store,
        force_refresh=not bool(args.use_cache),
        sleep_seconds=float(args.sleep_seconds),
        with_documents=bool(args.with_documents),
        documents_root=docs_root,
        force_document_download=bool(args.force_document_download),
        documents_confirmed_only=not bool(args.documents_all_matters),
        document_codes=args.document_codes or None,
    )
    out = state / "public_status_review.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass
    docs = report.get("documents") or {}
    summary = {
        "ok": True,
        "review_path": str(out),
        "success_count": report.get("success_count"),
        "failure_count": report.get("failure_count"),
        "reviews_compact": report.get("reviews_compact"),
        "documents": {
            "enabled": bool(args.with_documents),
            "success_count": docs.get("success_count"),
            "failure_count": docs.get("failure_count"),
            "matter_count": docs.get("matter_count"),
            "documents_root": docs.get("documents_root"),
            "results": docs.get("results"),
        }
        if args.with_documents
        else {"enabled": False},
    }
    print(json.dumps(summary, indent=2))
    status_fail = int(report.get("failure_count") or 0)
    doc_fail = int(docs.get("failure_count") or 0) if args.with_documents else 0
    return 0 if status_fail == 0 and doc_fail == 0 else 1


def _cmd_confirm(args: argparse.Namespace) -> int:
    state = _state_root(args)
    seed_path = _seed_path(state)
    seed = load_portfolio_seed(seed_path)
    apps = list(args.application_number or [])
    if not apps:
        raise PortfolioAutomationError(
            "pass one or more --application-number",
            code="missing_application_numbers",
        )
    seed = confirm_ownership(seed, apps, ownership=str(args.ownership))
    save_portfolio_seed(seed, seed_path)
    print(
        json.dumps(
            {
                "ok": True,
                "seed_path": str(seed_path),
                "confirmed": apps,
                "ownership": args.ownership,
            },
            indent=2,
        )
    )
    return 0


def _cmd_drop(args: argparse.Namespace) -> int:
    state = _state_root(args)
    seed_path = _seed_path(state)
    seed = load_portfolio_seed(seed_path)
    apps = list(args.application_number or [])
    if not apps:
        raise PortfolioAutomationError(
            "pass one or more --application-number to drop",
            code="missing_application_numbers",
        )
    seed, dropped = drop_matters(seed, apps)
    save_portfolio_seed(seed, seed_path)
    print(
        json.dumps(
            {
                "ok": True,
                "seed_path": str(seed_path),
                "dropped": dropped,
                "remaining": len(seed.matters),
            },
            indent=2,
        )
    )
    return 0


def _cmd_keep_only(args: argparse.Namespace) -> int:
    state = _state_root(args)
    seed_path = _seed_path(state)
    if seed_path.is_file():
        seed = load_portfolio_seed(seed_path)
    else:
        seed = PortfolioSeed(tenant_id=str(args.tenant), matters=[])
    apps = list(args.application_number or [])
    seed, removed = keep_only_matters(
        seed, apps, mark_confirmed=not bool(args.no_confirm)
    )
    save_portfolio_seed(seed, seed_path)
    print(
        json.dumps(
            {
                "ok": True,
                "seed_path": str(seed_path),
                "kept": [m.application_number for m in seed.matters],
                "removed": removed,
            },
            indent=2,
        )
    )
    return 0


def _cmd_schedule(args: argparse.Namespace) -> int:
    helper = Path(__file__).resolve().parent / "install_portfolio_schedule.py"
    cmd = [sys.executable, str(helper)]
    if args.state_root:
        cmd.extend(["--state-root", args.state_root])
    if getattr(args, "repo_root", None):
        cmd.extend(["--repo-root", args.repo_root])
    action = str(args.schedule_action)
    cmd.append(action)
    if action == "install":
        cmd.extend(["--interval-hours", str(args.interval_hours)])
        if args.activate:
            cmd.append("--activate")
        if getattr(args, "with_documents", False):
            cmd.append("--with-documents")
        if getattr(args, "documents_all_matters", False):
            cmd.append("--documents-all-matters")
    if action == "tick" and args.dry_run:
        cmd.append("--dry-run")
    return subprocess.call(cmd)


def _cmd_prepare_import(args: argparse.Namespace) -> int:
    paths = write_export_package_sidecar(
        Path(args.export_dir),
        application_number=str(args.application_number),
        tenant_id=str(args.tenant),
        authorizing_user=str(args.authorizing_user),
        classification=str(args.classification),
    )
    print(
        json.dumps(
            {"ok": True, **{k: str(v) for k, v in paths.items()}},
            indent=2,
        )
    )
    return 0


def _cmd_import_folder(args: argparse.Namespace) -> int:
    state = _state_root(args)
    store = Path(args.store_root).expanduser() if args.store_root else state / "private_store"
    result = import_export_folder(
        Path(args.export_dir),
        tenant_id=str(args.tenant),
        application_number=str(args.application_number),
        authorizing_user=str(args.authorizing_user),
        store_root=store,
        tenant_key_path=Path(args.tenant_key_file) if args.tenant_key_file else None,
        classification=str(args.classification),
        fail_fast=bool(args.fail_fast),
    )
    out = state / "import_receipts"
    out.mkdir(parents=True, exist_ok=True)
    receipt = out / f"import-{args.application_number.replace('/', '_')}.json"
    receipt.write_text(json.dumps(result, indent=2) + "\n")
    try:
        os.chmod(receipt, 0o600)
    except OSError:
        pass
    print(json.dumps({"ok": True, "receipt": str(receipt), **result}, indent=2, default=str))
    return 0


def _cmd_attended_export(args: argparse.Namespace) -> int:
    helper = Path(__file__).resolve().parent / "attended_patent_center_export.py"
    cmd = [sys.executable, str(helper)]
    if args.state_root:
        cmd.extend(["--state-root", args.state_root])
    if args.export_dir:
        cmd.extend(["--export-dir", args.export_dir])
    for app in args.application_number or []:
        cmd.extend(["--application-number", app])
    if args.tenant:
        cmd.extend(["--tenant", args.tenant])
    if args.authorizing_user:
        cmd.extend(["--authorizing-user", args.authorizing_user])
    if args.training:
        cmd.append("--training")
    if args.user_data_dir:
        cmd.extend(["--user-data-dir", args.user_data_dir])
    if getattr(args, "session_name", None):
        cmd.extend(["--session-name", str(args.session_name)])
    if getattr(args, "no_saved_session", False):
        cmd.append("--no-saved-session")
    if getattr(args, "headless", False):
        cmd.append("--headless")
    if args.seal_only:
        cmd.append("--seal-only")
    if args.json:
        cmd.append("--json")
    if args.login_timeout_seconds is not None:
        cmd.extend(["--login-timeout-seconds", str(args.login_timeout_seconds)])
    if args.watch_seconds is not None:
        cmd.extend(["--watch-seconds", str(args.watch_seconds)])
    return subprocess.call(cmd)


def _cmd_export_ui(args: argparse.Namespace) -> int:
    """Run authenticated Patent Center UI export (saved session required)."""
    from ipfs_datasets_py.processors.domains.uspto.auth.login_session import LoginError
    from ipfs_datasets_py.processors.domains.uspto.auth.patent_center_export_client import (
        export_application_via_patent_center,
    )

    state = Path(args.state_root).expanduser() if args.state_root else default_state_root()
    apps = [str(a).strip() for a in (args.application_number or []) if str(a).strip()]
    if not apps:
        seed_path = state / "portfolio_seed.json"
        if seed_path.is_file():
            seed = load_portfolio_seed(seed_path)
            apps = [
                m.application_number
                for m in seed.matters
                if not str(m.ownership).startswith("candidate")
            ]
    if not apps:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "no application numbers; pass --application-number",
                }
            ),
            file=sys.stderr,
        )
        return 2

    headless = bool(getattr(args, "headless", False))
    if not headless and not os.environ.get("DISPLAY"):
        headless = True

    results: list[dict[str, Any]] = []
    exit_code = 0
    for app in apps:
        export_dir = None
        if args.export_dir:
            base = Path(args.export_dir).expanduser()
            export_dir = base if len(apps) == 1 else base / app
        try:
            result = export_application_via_patent_center(
                app,
                state_root=state,
                session_name=str(getattr(args, "session_name", None) or "patent_center"),
                export_dir=export_dir,
                authorizing_user=str(args.authorizing_user or "operator:local"),
                tenant_id=str(args.tenant or "operator-default"),
                headless=headless,
                download_ifw_via_odp=not bool(getattr(args, "no_odp_ifw", False)),
                max_ifw_downloads=int(getattr(args, "max_ifw_downloads", 200) or 200),
            )
            results.append(result.to_dict())
            if not result.ok:
                exit_code = 1
        except (LoginError, PortfolioAutomationError) as exc:
            results.append(
                {
                    "ok": False,
                    "application_number": app,
                    "error": str(exc),
                    "code": getattr(exc, "code", None),
                }
            )
            exit_code = 1
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "ok": False,
                    "application_number": app,
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
            exit_code = 1

    payload: dict[str, Any] = {
        "schema": "patlaw-portfolio-export-ui-v1",
        "ok": exit_code == 0,
        "results": results,
    }
    # Write receipt under state root (no secrets).
    try:
        receipt_dir = state / "exports"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt = receipt_dir / "export_ui_receipt.json"
        receipt.write_text(json.dumps(payload, indent=2, default=str) + "\n")
        try:
            os.chmod(receipt, 0o600)
        except OSError:
            pass
        payload["receipt"] = str(receipt)
    except Exception:
        pass
    print(json.dumps(payload, indent=2, default=str))
    return exit_code


def _cmd_login(args: argparse.Namespace) -> int:
    helper = Path(__file__).resolve().parent / "uspto_login_cli.py"
    cmd = [sys.executable, str(helper)]
    if args.state_root:
        cmd.extend(["--state-root", args.state_root])
    cmd.extend(["--session-name", str(args.session_name)])
    cmd.append("login")
    cmd.extend(["--username-ref", str(args.username_ref)])
    cmd.extend(["--password-ref", str(args.password_ref)])
    cmd.extend(["--otp-mode", str(args.otp_mode)])
    if args.totp_secret_ref:
        cmd.extend(["--totp-secret-ref", str(args.totp_secret_ref)])
    if args.otp_ref:
        cmd.extend(["--otp-ref", str(args.otp_ref)])
    if args.otp_code:
        cmd.extend(["--otp-code", str(args.otp_code)])
    if args.headless:
        cmd.append("--headless")
    if args.no_prompt:
        cmd.append("--no-prompt")
    cmd.extend(["--timeout-seconds", str(args.timeout_seconds)])
    return subprocess.call(cmd)


def _cmd_login_status(args: argparse.Namespace) -> int:
    helper = Path(__file__).resolve().parent / "uspto_login_cli.py"
    cmd = [sys.executable, str(helper)]
    if args.state_root:
        cmd.extend(["--state-root", args.state_root])
    cmd.extend(["--session-name", str(args.session_name), "status"])
    return subprocess.call(cmd)


def _cmd_logout(args: argparse.Namespace) -> int:
    helper = Path(__file__).resolve().parent / "uspto_login_cli.py"
    cmd = [sys.executable, str(helper)]
    if args.state_root:
        cmd.extend(["--state-root", args.state_root])
    cmd.extend(["--session-name", str(args.session_name), "logout"])
    return subprocess.call(cmd)


def _cmd_show(args: argparse.Namespace) -> int:
    state = _state_root(args)
    if args.dashboard:
        payload = build_portfolio_dashboard(state)
    else:
        seed_path = _seed_path(state)
        review_path = state / "public_status_review.json"
        payload = {
            "state_root": str(state),
            "seed_exists": seed_path.is_file(),
            "review_exists": review_path.is_file(),
        }
        if seed_path.is_file():
            seed = load_portfolio_seed(seed_path)
            payload["seed"] = {
                "tenant_id": seed.tenant_id,
                "matter_count": len(seed.matters),
                "matters": [
                    {
                        "application_number": m.application_number,
                        "ownership": m.ownership,
                        "title": m.title[:80],
                        "status_odp_search": m.status_odp_search,
                    }
                    for m in seed.matters
                ],
            }
        if review_path.is_file() and args.include_review:
            payload["review"] = json.loads(review_path.read_text(encoding="utf-8"))
        if args.include_docs:
            payload["public_documents"] = summarize_public_documents(
                state / "public_docs"
            )
        if args.include_inbox:
            inbox = state / "private_inbox"
            payload["private_inbox"] = scan_private_inbox(inbox)
    print(json.dumps(payload, indent=2))
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    state = _state_root(args)
    payload = build_portfolio_dashboard(state)
    out = state / "portfolio_dashboard.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass
    print(json.dumps({**payload, "dashboard_path": str(out)}, indent=2))
    return 0


def _cmd_inbox_import(args: argparse.Namespace) -> int:
    state = _state_root(args)
    inbox = (
        Path(args.inbox_root).expanduser().resolve()
        if args.inbox_root
        else state / "private_inbox"
    )
    store = (
        Path(args.store_root).expanduser().resolve()
        if args.store_root
        else state / "private_store"
    )
    result = import_ready_inbox_folders(
        inbox,
        tenant_id=str(args.tenant),
        authorizing_user=str(args.authorizing_user),
        store_root=store,
        require_ready_marker=bool(args.require_ready_marker),
        min_stable_seconds=float(args.min_stable_seconds),
        classification=str(args.classification),
    )
    receipt_dir = state / "import_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = receipt_dir / f"inbox-import-{result['generated_at_utc'].replace(':', '')}.json"
    receipt.write_text(json.dumps(result, indent=2, default=str) + "\n")
    try:
        os.chmod(receipt, 0o600)
    except OSError:
        pass
    print(json.dumps({"ok": True, "receipt": str(receipt), **result}, indent=2, default=str))
    return 0 if int(result.get("imported_count") or 0) >= 0 else 1


def _cmd_watch_inbox(args: argparse.Namespace) -> int:
    """Poll private_inbox and auto-import settled folders."""
    import time as _time

    state = _state_root(args)
    inbox = (
        Path(args.inbox_root).expanduser().resolve()
        if args.inbox_root
        else state / "private_inbox"
    )
    inbox.mkdir(parents=True, exist_ok=True)
    store = (
        Path(args.store_root).expanduser().resolve()
        if args.store_root
        else state / "private_store"
    )
    deadline = _time.time() + float(args.duration_seconds)
    cycles = 0
    total_imported = 0
    print(
        json.dumps(
            {
                "watching": str(inbox),
                "poll_seconds": args.poll_seconds,
                "duration_seconds": args.duration_seconds,
                "hint": "Drop Patent Center downloads into private_inbox/<application_number>/",
            },
            indent=2,
        ),
        flush=True,
    )
    while _time.time() < deadline:
        cycles += 1
        result = import_ready_inbox_folders(
            inbox,
            tenant_id=str(args.tenant),
            authorizing_user=str(args.authorizing_user),
            store_root=store,
            require_ready_marker=bool(args.require_ready_marker),
            min_stable_seconds=float(args.min_stable_seconds),
            classification=str(args.classification),
        )
        total_imported += int(result.get("imported_count") or 0)
        if result.get("imported_count") or args.verbose:
            print(json.dumps(result, indent=2, default=str), flush=True)
        _time.sleep(float(args.poll_seconds))
    print(
        json.dumps(
            {
                "ok": True,
                "cycles": cycles,
                "total_imported": total_imported,
                "inbox": str(inbox),
            },
            indent=2,
        )
    )
    return 0


def _cmd_revise(args: argparse.Namespace) -> int:
    """Deficiency / office-action revision workflow (never auto-files)."""
    from ipfs_datasets_py.processors.domains.uspto.revision_response import (
        RevisionError,
        analyze_revision_letter,
        attach_to_revision,
        close_revision_case,
        list_revision_cases,
        load_revision_case,
        mark_revision_submitted,
        open_revision_case,
        prepare_revision_package,
        scan_response_triggers,
    )
    from ipfs_datasets_py.processors.domains.uspto.revision_law_guide import (
        build_revision_law_guide,
        seed_authority_corpus_readme,
    )

    state = _state_root(args)
    state.mkdir(parents=True, exist_ok=True)
    action = str(args.revise_action or "").strip()

    try:
        if action == "scan":
            result = scan_response_triggers(
                str(args.application_number),
                state_root=state,
                include_all_outgoing=bool(args.include_all_outgoing),
            )
            print(json.dumps(result, indent=2, default=str))
            return 0 if int(result.get("trigger_count") or 0) >= 0 else 1

        if action == "open":
            case = open_revision_case(
                str(args.application_number),
                state_root=state,
                document_identifier=str(args.document_id or ""),
                document_code=str(args.document_code or ""),
                document_description=str(args.document_description or ""),
                official_date=str(args.official_date or ""),
                direction=str(args.direction or "OUTGOING"),
                local_path=str(args.local_path or ""),
                kind=str(args.kind or ""),
                period_months=int(args.period_months)
                if args.period_months is not None
                else None,
                notes=[str(args.note)] if args.note else (),
                analyze=not bool(getattr(args, "no_analyze", False)),
                force_ocr=bool(getattr(args, "force_ocr", False)),
                save_text=bool(getattr(args, "save_text", False)),
            )
            print(json.dumps({"ok": True, "case": case.to_dict()}, indent=2, default=str))
            return 0

        if action == "analyze":
            result = analyze_revision_letter(
                str(args.revision_id),
                state_root=state,
                letter_path=str(args.local_path or ""),
                force_ocr=bool(getattr(args, "force_ocr", False)),
                save_text=bool(getattr(args, "save_text", False)),
                max_pages=int(getattr(args, "max_pages", 40) or 40),
            )
            # Drop full text if present under nested extraction
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("ok") else 1

        if action == "list":
            cases = list_revision_cases(
                state_root=state,
                application_number=str(args.application_number or ""),
                include_closed=bool(args.include_closed),
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "count": len(cases),
                        "cases": [c.to_dict() for c in cases],
                    },
                    indent=2,
                    default=str,
                )
            )
            return 0

        if action == "show":
            case = load_revision_case(str(args.revision_id), state_root=state)
            print(json.dumps({"ok": True, "case": case.to_dict()}, indent=2, default=str))
            return 0

        if action == "attach":
            case = attach_to_revision(
                str(args.revision_id),
                Path(args.file),
                role=str(args.role or "other"),
                state_root=state,
            )
            print(json.dumps({"ok": True, "case": case.to_dict()}, indent=2, default=str))
            return 0

        if action == "prepare":
            result = prepare_revision_package(
                str(args.revision_id), state_root=state
            )
            # Optionally attach law guide after prepare
            if not bool(getattr(args, "no_law_guide", False)):
                try:
                    seed_authority_corpus_readme(state)
                    guide = build_revision_law_guide(
                        str(args.revision_id),
                        state_root=state,
                        application_type=str(
                            getattr(args, "application_type", None) or "utility"
                        ),
                    )
                    result["law_guide_path"] = guide.get("law_guide_path")
                    result["law_guide_brief"] = {
                        "matched_rule_ids": (guide.get("filing_obligations") or {}).get(
                            "matched_rule_ids"
                        ),
                        "missing_mandatory_count": (
                            guide.get("package_evidence") or {}
                        ).get("missing_mandatory_count"),
                        "authority_found_count": guide.get("authority_found_count"),
                        "revision_tips": guide.get("revision_tips"),
                    }
                except Exception as exc:  # noqa: BLE001
                    result["law_guide_error"] = f"{type(exc).__name__}:{exc}"
            # Point operators at prior-art search for claim distinguishability
            case = load_revision_case(str(args.revision_id), state_root=state)
            result["prior_art_hint"] = {
                "command": (
                    "portfolio_cli prior-art search "
                    f"--application-number {case.application_number} "
                    "--claims-file <amended_claims.json> --odp"
                ),
                "attach": (
                    "portfolio_cli prior-art attach-revision "
                    f"--revision-id {case.revision_id} "
                    "--run-id <run_id> "
                    f"--application-number {case.application_number}"
                ),
                "note": (
                    "Plan/search public prior art to draft distinguishing remarks. "
                    "Does not assert novelty; foreign/NPL gaps stay visible."
                ),
            }
            result["compliance_audit_hint"] = {
                "command": (
                    "portfolio_cli audit-submission "
                    f"--revision-id {case.revision_id} "
                    f"--application-number {case.application_number}"
                ),
                "or_revise": (
                    f"portfolio_cli revise audit --revision-id {case.revision_id}"
                ),
                "note": (
                    "Audit package inventory vs MPEP/CFR filing-obligation rules "
                    "and prior-art coverage (review only)."
                ),
            }
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("ok") else 1

        if action == "guide":
            seed_authority_corpus_readme(state)
            guide = build_revision_law_guide(
                str(args.revision_id),
                state_root=state,
                application_type=str(
                    getattr(args, "application_type", None) or "utility"
                ),
            )
            print(json.dumps(guide, indent=2, default=str))
            return 0

        if action == "seed-corpus":
            path = seed_authority_corpus_readme(state)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "authority_corpus": str(path),
                        "hint": (
                            "Copy scraped CFR/USC/MPEP text files into this tree "
                            "or set USPTO_AUTHORITY_CORPUS_ROOT. "
                            "Hybrid BM25/graph also loads from Hugging Face "
                            "justicedao/patent-legal-{corpus,bm25,vectors,knowledge-graph}."
                        ),
                    },
                    indent=2,
                )
            )
            return 0

        if action == "search-law":
            from ipfs_datasets_py.processors.domains.uspto.public_legal_index_client import (
                search_public_legal,
            )

            query = str(getattr(args, "query", None) or args.note or "").strip()
            if not query and args.revision_id:
                case = load_revision_case(str(args.revision_id), state_root=state)
                from ipfs_datasets_py.processors.domains.uspto.public_legal_index_client import (
                    retrieve_for_revision_case,
                )

                result = retrieve_for_revision_case(case, top_k=int(args.top_k or 8))
                print(json.dumps(result, indent=2, default=str))
                return 0 if result.get("ok") else 1
            if not query:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": "pass --query or --revision-id for search-law",
                        },
                        indent=2,
                    ),
                    file=sys.stderr,
                )
                return 2
            result = search_public_legal(query, top_k=int(args.top_k or 8))
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("hit_count", 0) >= 0 else 1

        if action == "mark-submitted":
            case = mark_revision_submitted(
                str(args.revision_id),
                authorizing_user=str(args.authorizing_user),
                package_digest=str(args.package_digest or ""),
                state_root=state,
                notes=[str(args.note)] if args.note else (),
            )
            print(json.dumps({"ok": True, "case": case.to_dict()}, indent=2, default=str))
            return 0

        if action == "close":
            case = close_revision_case(
                str(args.revision_id),
                state_root=state,
                cancel=bool(args.cancel),
                note=str(args.note or ""),
            )
            print(json.dumps({"ok": True, "case": case.to_dict()}, indent=2, default=str))
            return 0

        if action == "audit":
            from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
                audit_submission,
            )

            result = audit_submission(
                revision_id=str(args.revision_id or "") or None,
                application_number=str(args.application_number or "") or None,
                state_root=state,
                package_dir=str(getattr(args, "package_dir", "") or "") or None,
                prior_art_run_id=str(getattr(args, "prior_art_run_id", "") or "")
                or None,
                prior_art_run_dir=str(getattr(args, "prior_art_run_dir", "") or "")
                or None,
                application_type=str(
                    getattr(args, "application_type", None) or "utility"
                ),
                with_law_index=bool(getattr(args, "with_law_index", False)),
                persist=not bool(getattr(args, "no_persist", False)),
            )
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("ok") else 1

        if action == "filing-assist":
            case = load_revision_case(str(args.revision_id), state_root=state)
            # Delegate to filing-assist with response package
            helper = Path(__file__).resolve().parent / "attended_filing_assist.py"
            cmd = [
                sys.executable,
                str(helper),
                "--state-root",
                str(state),
                "--application-number",
                case.application_number,
                "--package-dir",
                case.package_dir,
                "--package-digest",
                case.package_digest or "",
                "--navigate",
                "application",
                "--json",
            ]
            if args.headless:
                cmd.append("--headless")
            if args.no_browser:
                cmd.append("--no-browser")
            if args.watch_seconds is not None:
                cmd.extend(["--watch-seconds", str(args.watch_seconds)])
            return subprocess.call(cmd)

        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"unknown revise action: {action}",
                    "actions": [
                        "scan",
                        "open",
                        "analyze",
                        "list",
                        "show",
                        "attach",
                        "prepare",
                        "guide",
                        "seed-corpus",
                        "search-law",
                        "audit",
                        "filing-assist",
                        "mark-submitted",
                        "close",
                    ],
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    except RevisionError as exc:
        print(
            json.dumps({"ok": False, "code": exc.code, "message": str(exc)}, indent=2),
            file=sys.stderr,
        )
        return 2


def _resolve_prior_art_run_dir(
    args: argparse.Namespace, state: Path
) -> Path:
    from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
        PriorArtSearchClientError,
        prior_art_app_dir,
    )

    run_dir = str(getattr(args, "run_dir", "") or "").strip()
    if run_dir:
        return Path(run_dir).expanduser().resolve()
    run_id = str(getattr(args, "run_id", "") or "").strip()
    app = str(getattr(args, "application_number", "") or "").strip()
    if run_id and app:
        return prior_art_app_dir(app, state_root=state) / run_id
    if run_id:
        base = state / "prior_art"
        if base.is_dir():
            for app_dir in base.iterdir():
                cand = app_dir / run_id
                if cand.is_dir():
                    return cand
    raise PriorArtSearchClientError(
        "pass --run-dir or --run-id + --application-number",
        code="missing_run_dir",
    )


def _cmd_audit_submission(args: argparse.Namespace) -> int:
    """Audit package inventory vs filing rules + prior-art coverage."""
    from ipfs_datasets_py.processors.domains.uspto.submission_compliance_audit import (
        SubmissionComplianceAuditError,
        audit_submission,
    )

    state = _state_root(args)
    state.mkdir(parents=True, exist_ok=True)
    try:
        result = audit_submission(
            application_number=str(args.application_number or "") or None,
            revision_id=str(args.revision_id or "") or None,
            state_root=state,
            package_dir=str(args.package_dir or "") or None,
            prior_art_run_dir=str(args.prior_art_run_dir or "") or None,
            prior_art_run_id=str(args.prior_art_run_id or "") or None,
            application_type=str(args.application_type or "utility"),
            scenario=str(args.scenario or "") or None,
            with_law_index=bool(getattr(args, "with_law_index", False)),
            persist=not bool(getattr(args, "no_persist", False)),
        )
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("ok") else 1
    except SubmissionComplianceAuditError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": getattr(exc, "code", None),
                    "message": str(exc),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


def _cmd_prior_art(args: argparse.Namespace) -> int:
    """Plan / search / list public prior art for distinguishability review."""
    from ipfs_datasets_py.processors.domains.uspto.prior_art_search_client import (
        PriorArtSearchClientError,
        attach_prior_art_to_revision,
        list_prior_art_runs,
        plan_prior_art,
        search_prior_art,
        show_prior_art_run,
    )
    from ipfs_datasets_py.processors.domains.uspto.prior_art_operator_extensions import (
        acknowledge_prior_art_run,
        build_pps_verification_checklist,
        persist_pps_checklist,
        record_pps_verification,
        show_pps_verification,
    )
    from ipfs_datasets_py.processors.domains.patent.prior_art import (
        PriorArtSearchPlan,
    )

    state = _state_root(args)
    state.mkdir(parents=True, exist_ok=True)
    action = str(args.prior_art_action or "").strip()
    classifications = [
        c.strip()
        for c in str(getattr(args, "classifications", "") or "").split(",")
        if c.strip()
    ]
    citation_seeds = [
        c.strip()
        for c in str(getattr(args, "citation_seeds", "") or "").split(",")
        if c.strip()
    ]
    family_seeds = [
        c.strip()
        for c in str(getattr(args, "family_seeds", "") or "").split(",")
        if c.strip()
    ]

    try:
        if action == "plan":
            if not args.application_number:
                raise PriorArtSearchClientError(
                    "--application-number is required",
                    code="missing_application_number",
                )
            result = plan_prior_art(
                application_number=str(args.application_number),
                state_root=state,
                claims_file=str(args.claims_file or "") or None,
                claims_text=str(args.claims_text or "") or None,
                filing_date=str(args.filing_date or "") or None,
                priority_date=str(args.priority_date or "") or None,
                classifications=classifications,
                rank_cutoff=int(args.rank_cutoff or 10),
                citation_seeds=citation_seeds,
                family_seeds=family_seeds,
                persist=not bool(getattr(args, "no_persist", False)),
            )
            # Drop full plan body from stdout unless --verbose
            if not bool(getattr(args, "verbose", False)):
                result = {
                    k: v
                    for k, v in result.items()
                    if k != "plan"
                }
                result["hint"] = "pass --verbose to print full plan JSON"
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("ok") else 1

        if action == "search":
            if not args.application_number:
                raise PriorArtSearchClientError(
                    "--application-number is required",
                    code="missing_application_number",
                )
            use_odp = bool(getattr(args, "odp", False))
            local_snap = str(getattr(args, "local_snapshot", "") or "").strip()
            foreign_hits = str(getattr(args, "foreign_hits", "") or "").strip()
            foreign_snap = str(getattr(args, "foreign_snapshot", "") or "").strip()
            npl_catalog = str(getattr(args, "npl_catalog", "") or "").strip()
            citation_graph = str(getattr(args, "citation_graph", "") or "").strip()
            family_graph = str(getattr(args, "family_graph", "") or "").strip()
            if use_odp:
                _ensure_env_key()
            has_us = use_odp or bool(local_snap)
            live_foreign = bool(getattr(args, "live_foreign", False))
            live_npl = bool(getattr(args, "live_npl", False))
            has_coverage = bool(
                getattr(args, "enable_foreign", False)
                or foreign_hits
                or foreign_snap
                or live_foreign
                or getattr(args, "enable_npl", False)
                or npl_catalog
                or live_npl
            )
            if not has_us and not has_coverage:
                raise PriorArtSearchClientError(
                    "pass --odp and/or --local-snapshot "
                    "(and optionally --foreign-hits / --live-foreign / --npl-catalog / --live-npl)",
                    code="no_search_backend",
                )
            npl_providers = [
                p.strip()
                for p in str(getattr(args, "npl_providers", "") or "openalex,crossref").split(
                    ","
                )
                if p.strip()
            ]
            result = search_prior_art(
                application_number=str(args.application_number),
                state_root=state,
                claims_file=str(args.claims_file or "") or None,
                claims_text=str(args.claims_text or "") or None,
                filing_date=str(args.filing_date or "") or None,
                priority_date=str(args.priority_date or "") or None,
                classifications=classifications,
                rank_cutoff=int(args.rank_cutoff or 10),
                citation_seeds=citation_seeds,
                family_seeds=family_seeds,
                use_odp=use_odp,
                local_snapshot_path=local_snap or None,
                max_odp_pages=int(getattr(args, "max_odp_pages", 1) or 1),
                max_queries=int(args.max_queries)
                if getattr(args, "max_queries", None) is not None
                else None,
                enable_foreign=bool(getattr(args, "enable_foreign", False))
                or bool(foreign_hits or foreign_snap or live_foreign),
                foreign_hits_path=foreign_hits or None,
                foreign_snapshot_path=foreign_snap or None,
                foreign_licensed=not bool(getattr(args, "foreign_unlicensed", False)),
                live_foreign=live_foreign,
                enable_npl=bool(getattr(args, "enable_npl", False))
                or bool(npl_catalog or live_npl),
                npl_catalog_path=npl_catalog or None,
                npl_licensed=bool(getattr(args, "npl_licensed", False)),
                live_npl=live_npl,
                npl_providers=tuple(npl_providers),
                citation_graph_path=citation_graph or None,
                family_graph_path=family_graph or None,
                max_live_results=int(getattr(args, "max_live_results", 10) or 10),
                build_report=not bool(getattr(args, "no_report", False)),
                build_pps_checklist=not bool(getattr(args, "no_pps_checklist", False)),
                auto_acknowledge=bool(getattr(args, "auto_acknowledge", False)),
                acknowledger_name=str(getattr(args, "acknowledger", "") or ""),
            )
            # Compact stdout: summary + paths (not full journal)
            out = {
                "ok": result.get("ok"),
                "run_id": result.get("run_id"),
                "run_dir": result.get("run_dir"),
                "application_number": result.get("application_number"),
                "plan_id": result.get("plan_id"),
                "journal_id": result.get("journal_id"),
                "chart_id": result.get("chart_id"),
                "coverage_id": result.get("coverage_id"),
                "report_id": result.get("report_id"),
                "adapter_status": result.get("adapter_status"),
                "paths": result.get("paths"),
                "summary": result.get("summary"),
                "disclaimer": result.get("disclaimer"),
            }
            if bool(getattr(args, "verbose", False)):
                out = result
            print(json.dumps(out, indent=2, default=str))
            return 0 if result.get("ok") else 1

        if action == "list":
            result = list_prior_art_runs(
                application_number=str(args.application_number or "") or None,
                state_root=state,
            )
            print(json.dumps(result, indent=2, default=str))
            return 0

        if action == "show":
            result = show_prior_art_run(
                run_id=str(args.run_id or "") or None,
                application_number=str(args.application_number or "") or None,
                run_dir=str(args.run_dir or "") or None,
                state_root=state,
                include_full=bool(getattr(args, "verbose", False)),
            )
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("ok") else 1

        if action == "attach-revision":
            if not args.revision_id:
                raise PriorArtSearchClientError(
                    "--revision-id is required", code="missing_revision_id"
                )
            run_dir = str(_resolve_prior_art_run_dir(args, state))
            result = attach_prior_art_to_revision(
                str(args.revision_id),
                run_dir,
                state_root=state,
            )
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("ok") else 1

        if action == "pps-checklist":
            run_dir = _resolve_prior_art_run_dir(args, state)
            plan_path = run_dir / "prior_art_plan.json"
            if not plan_path.is_file():
                raise PriorArtSearchClientError(
                    f"prior_art_plan.json missing in {run_dir}",
                    code="plan_missing",
                )
            plan = PriorArtSearchPlan.from_dict(
                json.loads(plan_path.read_text(encoding="utf-8"))
            )
            checklist = build_pps_verification_checklist(
                plan,
                application_number=str(args.application_number or ""),
                run_id=run_dir.name,
            )
            path = persist_pps_checklist(checklist, run_dir)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "pps_checklist_path": str(path),
                        "pps_url": checklist.get("pps_url"),
                        "item_count": checklist.get("item_count"),
                        "instructions": checklist.get("instructions"),
                        "disclaimer": checklist.get("disclaimer"),
                    },
                    indent=2,
                )
            )
            return 0

        if action == "pps-record":
            run_dir = _resolve_prior_art_run_dir(args, state)
            verified_by = str(getattr(args, "acknowledger", "") or args.note or "").strip()
            if not verified_by:
                verified_by = "operator:local"
            results_path = str(getattr(args, "pps_results", "") or "").strip()
            results: list[dict[str, Any]] = []
            if results_path:
                raw = json.loads(
                    Path(results_path).expanduser().read_text(encoding="utf-8")
                )
                if isinstance(raw, Mapping) and isinstance(raw.get("results"), list):
                    results = list(raw["results"])
                elif isinstance(raw, list):
                    results = list(raw)
                else:
                    raise PriorArtSearchClientError(
                        "pps results JSON must be a list or {results:[]}",
                        code="invalid_pps_results",
                    )
            elif getattr(args, "query_id", None) and getattr(
                args, "human_result_count", None
            ) is not None:
                results = [
                    {
                        "query_id": str(args.query_id),
                        "human_result_count": int(args.human_result_count),
                        "human_notes": str(args.note or ""),
                    }
                ]
            else:
                raise PriorArtSearchClientError(
                    "pass --pps-results FILE or --query-id + --human-result-count",
                    code="missing_pps_results",
                )
            result = record_pps_verification(
                run_dir,
                results=results,
                verified_by=verified_by,
                notes=str(args.note or ""),
            )
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("ok") else 1

        if action == "pps-show":
            run_dir = _resolve_prior_art_run_dir(args, state)
            result = show_pps_verification(run_dir)
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("ok") else 1

        if action == "acknowledge":
            run_dir = _resolve_prior_art_run_dir(args, state)
            name = str(getattr(args, "acknowledger", "") or "").strip()
            if not name:
                raise PriorArtSearchClientError(
                    "--acknowledger is required for acknowledge",
                    code="missing_acknowledger",
                )
            result = acknowledge_prior_art_run(
                run_dir,
                acknowledger_name=name,
                claim_search_complete=bool(
                    getattr(args, "claim_search_complete", False)
                ),
            )
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("ok") else 1

        if action == "distinguish-matrix":
            from ipfs_datasets_py.processors.domains.uspto.prior_art_operator_extensions import (
                build_and_persist_distinguishability_matrix,
            )

            run_dir = _resolve_prior_art_run_dir(args, state)
            result = build_and_persist_distinguishability_matrix(run_dir)
            print(json.dumps(result, indent=2, default=str))
            return 0 if result.get("ok") else 1

        if action == "pps-assist":
            helper = Path(__file__).resolve().parent / "attended_pps_assist.py"
            run_dir = _resolve_prior_art_run_dir(args, state)
            cmd = [
                sys.executable,
                str(helper),
                "--run-dir",
                str(run_dir),
                "--json",
            ]
            if args.application_number:
                cmd.extend(
                    ["--application-number", str(args.application_number)]
                )
            if getattr(args, "state_root", None):
                cmd.extend(["--state-root", str(args.state_root)])
            if bool(getattr(args, "no_browser", False)):
                cmd.append("--no-browser")
            if bool(getattr(args, "headless", False)):
                cmd.append("--headless")
            watch = getattr(args, "watch_seconds", None)
            if watch is not None:
                cmd.extend(["--watch-seconds", str(watch)])
            return subprocess.call(cmd)

        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"unknown prior-art action: {action}",
                    "actions": [
                        "plan",
                        "search",
                        "list",
                        "show",
                        "attach-revision",
                        "pps-checklist",
                        "pps-record",
                        "pps-show",
                        "pps-assist",
                        "acknowledge",
                        "distinguish-matrix",
                    ],
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    except PriorArtSearchClientError as exc:
        print(
            json.dumps(
                {"ok": False, "code": getattr(exc, "code", None), "message": str(exc)},
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


def _cmd_filing_checklist(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.processors.domains.uspto.filing_assist import (
        build_filing_checklist,
        prepare_receipt_inbox,
        write_filing_checklist,
    )

    state = _state_root(args)
    state.mkdir(parents=True, exist_ok=True)
    app = str(args.application_number or "").strip()
    package_dir = Path(args.package_dir).expanduser() if args.package_dir else None
    metadata_dir = Path(args.metadata_dir).expanduser() if args.metadata_dir else None
    checklist = build_filing_checklist(
        application_number=app,
        package_dir=package_dir,
        package_digest=str(args.package_digest or ""),
        training=bool(args.training),
        metadata_dir=metadata_dir,
        state_root=state,
    )
    if app:
        prepare_receipt_inbox(application_number=app, state_root=state)
    dest = (
        Path(args.output).expanduser()
        if args.output
        else state
        / "post_submit_receipts"
        / (app or "_unscoped")
        / "filing_checklist.json"
    )
    path = write_filing_checklist(checklist, dest)
    print(
        json.dumps(
            {"ok": True, "checklist_path": str(path), "checklist": checklist.to_dict()},
            indent=2,
            default=str,
        )
    )
    return 0


def _cmd_filing_assist(args: argparse.Namespace) -> int:
    helper = Path(__file__).resolve().parent / "attended_filing_assist.py"
    cmd = [sys.executable, str(helper)]
    if args.state_root:
        cmd.extend(["--state-root", args.state_root])
    if args.application_number:
        cmd.extend(["--application-number", args.application_number])
    if args.package_dir:
        cmd.extend(["--package-dir", args.package_dir])
    if args.package_digest:
        cmd.extend(["--package-digest", args.package_digest])
    if args.metadata_dir:
        cmd.extend(["--metadata-dir", args.metadata_dir])
    if args.training:
        cmd.append("--training")
    if args.session_name:
        cmd.extend(["--session-name", args.session_name])
    if args.no_saved_session:
        cmd.append("--no-saved-session")
    if args.headless:
        cmd.append("--headless")
    if args.no_browser:
        cmd.append("--no-browser")
    if args.watch_seconds is not None:
        cmd.extend(["--watch-seconds", str(args.watch_seconds)])
    if args.navigate:
        cmd.extend(["--navigate", args.navigate])
    cmd.append("--json")
    return subprocess.call(cmd)


def _cmd_watch_receipts(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.processors.domains.uspto.filing_assist import (
        watch_and_import_receipts,
    )

    state = _state_root(args)
    store = (
        Path(args.store_root).expanduser().resolve()
        if args.store_root
        else state / "private_store"
    )
    result = watch_and_import_receipts(
        application_number=str(args.application_number),
        state_root=state,
        store_root=store,
        tenant_id=str(args.tenant),
        authorizing_user=str(args.authorizing_user),
        duration_seconds=float(args.duration_seconds),
        poll_seconds=float(args.poll_seconds),
        min_stable_seconds=float(args.min_stable_seconds),
        require_acknowledgement_hint=not bool(args.no_require_ack_hint),
        classification=str(args.classification),
    )
    out = state / "import_receipts"
    out.mkdir(parents=True, exist_ok=True)
    receipt = out / f"watch-receipts-{args.application_number}.json"
    receipt.write_text(json.dumps(result, indent=2, default=str) + "\n")
    try:
        os.chmod(receipt, 0o600)
    except OSError:
        pass
    print(json.dumps({"receipt": str(receipt), **result}, indent=2, default=str))
    return 0 if result.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="portfolio_cli",
        description="Automate USPTO portfolio review helpers (public ODP + private import).",
    )
    p.add_argument(
        "--state-root",
        default="",
        help="Portfolio state directory (default under XDG_STATE_HOME).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="ODP inventor-name discovery → seed")
    d.add_argument("--inventor-name", required=True)
    d.add_argument("--limit", type=int, default=50)
    d.add_argument("--tenant", default="operator-default")
    d.set_defaults(func=_cmd_discover)

    r = sub.add_parser("refresh", help="Batch public ODP status refresh")
    r.add_argument("--sleep-seconds", type=float, default=2.0)
    r.add_argument("--use-cache", action="store_true")
    r.add_argument(
        "--with-documents",
        action="store_true",
        help="Also sync public document inventory/bytes (confirmed matters by default).",
    )
    r.add_argument(
        "--documents-all-matters",
        action="store_true",
        help="With --with-documents: include candidate (unconfirmed) matters too.",
    )
    r.add_argument(
        "--force-document-download",
        action="store_true",
        help="Re-download document bytes even when checkpoint says unchanged.",
    )
    r.add_argument(
        "--documents-root",
        default="",
        help="Durable public document store root (default: state-root/public_docs).",
    )
    r.add_argument(
        "--document-codes",
        default="",
        help="Optional comma-separated ODP documentCodes filter.",
    )
    r.set_defaults(func=_cmd_refresh)

    c = sub.add_parser("confirm", help="Mark apps as confirmed ownership")
    c.add_argument("--application-number", action="append", default=[])
    c.add_argument("--ownership", default="confirmed_operator")
    c.set_defaults(func=_cmd_confirm)

    drop = sub.add_parser("drop", help="Remove apps from the portfolio seed")
    drop.add_argument("--application-number", action="append", default=[])
    drop.set_defaults(func=_cmd_drop)

    keep = sub.add_parser(
        "keep-only",
        help="Replace seed with only the listed apps (marks confirmed by default)",
    )
    keep.add_argument("--application-number", action="append", default=[])
    keep.add_argument("--tenant", default="operator-default")
    keep.add_argument(
        "--no-confirm",
        action="store_true",
        help="Do not rewrite ownership to confirmed_operator",
    )
    keep.set_defaults(func=_cmd_keep_only)

    sch = sub.add_parser(
        "schedule",
        help="Install/activate/status/tick public ODP refresh schedule",
    )
    sch.add_argument(
        "schedule_action",
        choices=("install", "activate", "uninstall", "status", "tick"),
    )
    sch.add_argument("--interval-hours", type=int, default=24)
    sch.add_argument("--activate", action="store_true", help="With install: enable timer")
    sch.add_argument("--repo-root", default="")
    sch.add_argument(
        "--with-documents",
        action="store_true",
        help="With install: scheduled refresh includes public document sync",
    )
    sch.add_argument(
        "--documents-all-matters",
        action="store_true",
        help="With install --with-documents: include unconfirmed candidates",
    )
    sch.add_argument("--dry-run", action="store_true")
    sch.set_defaults(func=_cmd_schedule)

    prep = sub.add_parser("prepare-import", help="Write manifest+auth for a folder")
    prep.add_argument("--export-dir", required=True)
    prep.add_argument("--application-number", required=True)
    prep.add_argument("--tenant", default="operator-default")
    prep.add_argument("--authorizing-user", default="operator:local")
    prep.add_argument("--classification", default="confidential_application")
    prep.set_defaults(func=_cmd_prepare_import)

    imp = sub.add_parser("import-folder", help="Import local export into private store")
    imp.add_argument("--export-dir", required=True)
    imp.add_argument("--application-number", required=True)
    imp.add_argument("--tenant", default="operator-default")
    imp.add_argument("--authorizing-user", default="operator:local")
    imp.add_argument("--classification", default="confidential_application")
    imp.add_argument("--store-root", default="")
    imp.add_argument("--tenant-key-file", default="")
    imp.add_argument("--fail-fast", action="store_true")
    imp.set_defaults(func=_cmd_import_folder)

    att = sub.add_parser(
        "attended-export",
        help="Human-login Patent Center export (browser) then seal package",
    )
    att.add_argument("--export-dir", default="")
    att.add_argument("--application-number", action="append", default=[])
    att.add_argument("--tenant", default="operator-default")
    att.add_argument("--authorizing-user", default="operator:local")
    att.add_argument("--training", action="store_true")
    att.add_argument("--user-data-dir", default="")
    att.add_argument(
        "--session-name",
        default="patent_center",
        help="Use storage_state from uspto_login_cli (default patent_center)",
    )
    att.add_argument(
        "--no-saved-session",
        action="store_true",
        help="Ignore saved login session; require interactive login in browser",
    )
    att.add_argument(
        "--headless",
        action="store_true",
        help="Run export browser headless (auto if DISPLAY unset)",
    )
    att.add_argument("--seal-only", action="store_true")
    att.add_argument("--login-timeout-seconds", type=float, default=600.0)
    att.add_argument("--watch-seconds", type=float, default=120.0)
    att.add_argument("--json", action="store_true")
    att.set_defaults(func=_cmd_attended_export)

    exp_ui = sub.add_parser(
        "export-ui",
        help=(
            "Automated Patent Center UI export using saved login session "
            "(private metadata + eGrant UI download + optional ODP IFW PDFs)"
        ),
    )
    exp_ui.add_argument("--export-dir", default="")
    exp_ui.add_argument("--application-number", action="append", default=[])
    exp_ui.add_argument("--tenant", default="operator-default")
    exp_ui.add_argument("--authorizing-user", default="operator:local")
    exp_ui.add_argument(
        "--session-name",
        default="patent_center",
        help="Saved login session name (default patent_center)",
    )
    exp_ui.add_argument(
        "--headless",
        action="store_true",
        help="Force headless Chromium (auto when DISPLAY unset)",
    )
    exp_ui.add_argument(
        "--no-odp-ifw",
        action="store_true",
        help="Do not download IFW PDFs via public ODP (metadata only + eGrant UI)",
    )
    exp_ui.add_argument(
        "--max-ifw-downloads",
        type=int,
        default=200,
        help="Max IFW documents to pull via ODP (default 200)",
    )
    exp_ui.set_defaults(func=_cmd_export_ui)

    login = sub.add_parser(
        "login",
        help="Patent Center login (password+OTP via env refs/prompts)",
    )
    login.add_argument("--session-name", default="patent_center")
    login.add_argument("--username-ref", default="env:USPTO_USERNAME")
    login.add_argument("--password-ref", default="env:USPTO_PASSWORD")
    login.add_argument(
        "--otp-mode",
        choices=("prompt", "totp", "code", "none"),
        default="prompt",
    )
    login.add_argument("--totp-secret-ref", default="env:USPTO_TOTP_SECRET")
    login.add_argument("--otp-ref", default="")
    login.add_argument("--otp-code", default="")
    login.add_argument("--headless", action="store_true")
    login.add_argument("--no-prompt", action="store_true")
    login.add_argument("--timeout-seconds", type=float, default=180.0)
    login.set_defaults(func=_cmd_login)

    login_st = sub.add_parser("login-status", help="Show saved Patent Center session")
    login_st.add_argument("--session-name", default="patent_center")
    login_st.set_defaults(func=_cmd_login_status)

    logout = sub.add_parser("logout", help="Delete saved Patent Center session")
    logout.add_argument("--session-name", default="patent_center")
    logout.set_defaults(func=_cmd_logout)

    s = sub.add_parser("show", help="Show portfolio seed summary")
    s.add_argument("--include-review", action="store_true")
    s.add_argument("--include-docs", action="store_true")
    s.add_argument("--include-inbox", action="store_true")
    s.add_argument(
        "--dashboard",
        action="store_true",
        help="Emit full dashboard (seed + docs + exports + inbox + schedule)",
    )
    s.set_defaults(func=_cmd_show)

    dash = sub.add_parser(
        "dashboard",
        help="Write portfolio_dashboard.json (seed, docs, inbox, schedule)",
    )
    dash.set_defaults(func=_cmd_dashboard)

    inbox = sub.add_parser(
        "inbox-import",
        help="Import settled folders under private_inbox/<application_number>/",
    )
    inbox.add_argument("--inbox-root", default="")
    inbox.add_argument("--store-root", default="")
    inbox.add_argument("--tenant", default="operator-default")
    inbox.add_argument("--authorizing-user", default="operator:local")
    inbox.add_argument("--classification", default="confidential_application")
    inbox.add_argument(
        "--require-ready-marker",
        action="store_true",
        help="Only import folders that contain a READY file",
    )
    inbox.add_argument(
        "--min-stable-seconds",
        type=float,
        default=15.0,
        help="Without READY, wait until newest file is this old (default 15)",
    )
    inbox.set_defaults(func=_cmd_inbox_import)

    watch = sub.add_parser(
        "watch-inbox",
        help="Poll private_inbox and auto-import settled download folders",
    )
    watch.add_argument("--inbox-root", default="")
    watch.add_argument("--store-root", default="")
    watch.add_argument("--tenant", default="operator-default")
    watch.add_argument("--authorizing-user", default="operator:local")
    watch.add_argument("--classification", default="confidential_application")
    watch.add_argument("--require-ready-marker", action="store_true")
    watch.add_argument("--min-stable-seconds", type=float, default=15.0)
    watch.add_argument("--poll-seconds", type=float, default=10.0)
    watch.add_argument(
        "--duration-seconds",
        type=float,
        default=300.0,
        help="How long to watch before exiting (default 300)",
    )
    watch.add_argument("--verbose", action="store_true")
    watch.set_defaults(func=_cmd_watch_inbox)

    fcheck = sub.add_parser(
        "filing-checklist",
        help=(
            "Write filing checklist with hard barriers "
            "(Sign/Pay/Submit remain human-only)"
        ),
    )
    fcheck.add_argument("--application-number", default="")
    fcheck.add_argument("--package-dir", default="")
    fcheck.add_argument("--package-digest", default="")
    fcheck.add_argument("--metadata-dir", default="")
    fcheck.add_argument("--training", action="store_true")
    fcheck.add_argument("--output", default="")
    fcheck.set_defaults(func=_cmd_filing_checklist)

    fassist = sub.add_parser(
        "filing-assist",
        help=(
            "Attended Patent Center assist: open PC, show checklist, watch "
            "receipt downloads. Never clicks Sign/Pay/Submit."
        ),
    )
    fassist.add_argument("--application-number", default="")
    fassist.add_argument("--package-dir", default="")
    fassist.add_argument("--package-digest", default="")
    fassist.add_argument("--metadata-dir", default="")
    fassist.add_argument("--training", action="store_true")
    fassist.add_argument("--session-name", default="patent_center")
    fassist.add_argument("--no-saved-session", action="store_true")
    fassist.add_argument("--headless", action="store_true")
    fassist.add_argument(
        "--no-browser",
        action="store_true",
        help="Checklist + receipt folder only (no Playwright)",
    )
    fassist.add_argument("--watch-seconds", type=float, default=300.0)
    fassist.add_argument(
        "--navigate",
        choices=("home", "workbench", "new-submission", "application", "none"),
        default="home",
    )
    fassist.set_defaults(func=_cmd_filing_assist)

    wrec = sub.add_parser(
        "watch-receipts",
        help=(
            "Watch post_submit_receipts/<app>/ for human-downloaded EAR/payment "
            "files and seal+import when stable"
        ),
    )
    wrec.add_argument("--application-number", required=True)
    wrec.add_argument("--store-root", default="")
    wrec.add_argument("--tenant", default="operator-default")
    wrec.add_argument("--authorizing-user", default="operator:local")
    wrec.add_argument("--classification", default="confidential_application")
    wrec.add_argument("--duration-seconds", type=float, default=300.0)
    wrec.add_argument("--poll-seconds", type=float, default=10.0)
    wrec.add_argument("--min-stable-seconds", type=float, default=15.0)
    wrec.add_argument(
        "--no-require-ack-hint",
        action="store_true",
        help="Import even if filename does not look like an acknowledgement",
    )
    wrec.set_defaults(func=_cmd_watch_receipts)

    rev = sub.add_parser(
        "revise",
        help=(
            "Respond to USPTO deficiency letters / office actions: scan IFW, "
            "open a revision case, attach revised docs, prepare package, "
            "filing-assist (human Sign/Pay/Submit still required)"
        ),
    )
    rev.add_argument(
        "revise_action",
        choices=(
            "scan",
            "open",
            "analyze",
            "list",
            "show",
            "attach",
            "prepare",
            "guide",
            "seed-corpus",
            "search-law",
            "audit",
            "filing-assist",
            "mark-submitted",
            "close",
        ),
        help="Revision workflow action",
    )
    rev.add_argument("--application-number", default="")
    rev.add_argument("--revision-id", default="")
    rev.add_argument("--document-id", default="")
    rev.add_argument("--document-code", default="")
    rev.add_argument("--document-description", default="")
    rev.add_argument("--official-date", default="")
    rev.add_argument("--direction", default="OUTGOING")
    rev.add_argument("--local-path", default="")
    rev.add_argument(
        "--kind",
        default="",
        help="Trigger kind override (e.g. missing_parts, office_action_nonfinal)",
    )
    rev.add_argument("--period-months", type=int, default=None)
    rev.add_argument("--file", default="", help="With attach: path to revised document")
    rev.add_argument(
        "--role",
        default="other",
        help="With attach: amended_claims|remarks|substitute_specification|…",
    )
    rev.add_argument("--authorizing-user", default="operator:local")
    rev.add_argument("--package-digest", default="")
    rev.add_argument("--note", default="")
    rev.add_argument("--include-closed", action="store_true")
    rev.add_argument(
        "--include-all-outgoing",
        action="store_true",
        help="With scan: list all OUTGOING docs, not only classified triggers",
    )
    rev.add_argument("--cancel", action="store_true", help="With close: mark cancelled")
    rev.add_argument("--headless", action="store_true")
    rev.add_argument("--no-browser", action="store_true")
    rev.add_argument("--watch-seconds", type=float, default=300.0)
    rev.add_argument(
        "--no-analyze",
        action="store_true",
        help="With open: skip OCR/letter analysis even if PDF present",
    )
    rev.add_argument(
        "--force-ocr",
        action="store_true",
        help="With open/analyze: force local Tesseract OCR",
    )
    rev.add_argument(
        "--save-text",
        action="store_true",
        help="With open/analyze: save full OCR text under case_dir/triggering/ (mode 0600)",
    )
    rev.add_argument(
        "--max-pages",
        type=int,
        default=40,
        help="With analyze: max PDF pages to OCR (default 40)",
    )
    rev.add_argument(
        "--application-type",
        default="utility",
        help="With prepare/guide: utility|design|plant (default utility)",
    )
    rev.add_argument(
        "--no-law-guide",
        action="store_true",
        help="With prepare: skip filing-rule / authority law guide",
    )
    rev.add_argument(
        "--query",
        default="",
        help="With search-law: free-text query against HF patent-legal hybrid index",
    )
    rev.add_argument(
        "--top-k",
        type=int,
        default=8,
        help="With search-law: number of hybrid hits (default 8)",
    )
    rev.add_argument(
        "--package-dir",
        default="",
        help="With audit: package directory override",
    )
    rev.add_argument(
        "--prior-art-run-id",
        default="",
        help="With audit: bind a specific prior-art run id",
    )
    rev.add_argument(
        "--prior-art-run-dir",
        default="",
        help="With audit: bind a specific prior-art run directory",
    )
    rev.add_argument(
        "--with-law-index",
        action="store_true",
        help="With audit: query HF patent-legal hybrid index for MPEP/CFR hits",
    )
    rev.add_argument(
        "--no-persist",
        action="store_true",
        help="With audit: do not write audit artifacts under state-root",
    )
    rev.set_defaults(func=_cmd_revise)

    pa = sub.add_parser(
        "prior-art",
        help=(
            "Prior-art search for claim distinguishability: plans, ODP/local "
            "search, foreign/NPL adapters, citation/family expansion, PPS human "
            "verification checklist, coverage ack. Never asserts novelty/"
            "patentability; never scrapes Patent Public Search."
        ),
    )
    pa.add_argument(
        "prior_art_action",
        choices=(
            "plan",
            "search",
            "list",
            "show",
            "attach-revision",
            "pps-checklist",
            "pps-record",
            "pps-show",
            "pps-assist",
            "acknowledge",
            "distinguish-matrix",
        ),
        help="prior-art workflow action",
    )
    pa.add_argument("--application-number", default="")
    pa.add_argument(
        "--claims-file",
        default="",
        help="JSON/JSONL/text file of claims (list or {claims:[{claim_number,claim_text}]})",
    )
    pa.add_argument(
        "--claims-text",
        default="",
        help="Inline numbered claim text (e.g. '1. A method comprising…')",
    )
    pa.add_argument(
        "--filing-date",
        default="",
        help="YYYY-MM-DD (default: from export application_data if present)",
    )
    pa.add_argument(
        "--priority-date",
        default="",
        help="YYYY-MM-DD (default: earliest parent continuity or filing date)",
    )
    pa.add_argument(
        "--classifications",
        default="",
        help="Comma-separated CPC/IPC codes to seed queries",
    )
    pa.add_argument(
        "--citation-seeds",
        default="",
        help="Comma-separated document ids for citation-expansion queries",
    )
    pa.add_argument(
        "--family-seeds",
        default="",
        help="Comma-separated document ids for family-expansion queries",
    )
    pa.add_argument(
        "--rank-cutoff",
        type=int,
        default=10,
        help="Max hits kept per query (default 10)",
    )
    pa.add_argument(
        "--odp",
        action="store_true",
        help="With search: query USPTO ODP Patent File Wrapper (needs USPTO_ODP_API_KEY)",
    )
    pa.add_argument(
        "--local-snapshot",
        default="",
        help="With search: path to local public-patent JSON/JSONL snapshot",
    )
    pa.add_argument(
        "--max-odp-pages",
        type=int,
        default=1,
        help="With --odp: max result pages per query (default 1)",
    )
    pa.add_argument(
        "--max-queries",
        type=int,
        default=None,
        help="With search: cap number of plan queries executed (cost control)",
    )
    pa.add_argument(
        "--enable-foreign",
        action="store_true",
        help="With search: register foreign-patent adapter (needs hits/snapshot or records named gap)",
    )
    pa.add_argument(
        "--foreign-hits",
        default="",
        help="JSON/JSONL of foreign patent hits (EP/WO/… document_id + title)",
    )
    pa.add_argument(
        "--foreign-snapshot",
        default="",
        help="Local foreign-patent snapshot JSON converted to hits",
    )
    pa.add_argument(
        "--foreign-unlicensed",
        action="store_true",
        help="Mark foreign adapter unlicensed (corpus stays named gap)",
    )
    pa.add_argument(
        "--live-foreign",
        action="store_true",
        help=(
            "With search: live EPO OPS foreign search "
            "(needs EPO_OPS_KEY + EPO_OPS_SECRET from developers.epo.org)"
        ),
    )
    pa.add_argument(
        "--enable-npl",
        action="store_true",
        help="With search: register NPL adapter (needs --npl-catalog for real hits)",
    )
    pa.add_argument(
        "--npl-catalog",
        default="",
        help="JSON/JSONL NPL metadata catalog (rights_status required; body text rights-gated)",
    )
    pa.add_argument(
        "--npl-licensed",
        action="store_true",
        help="Assert NPL catalog is licensed for this operator (still no body redistrib without rights)",
    )
    pa.add_argument(
        "--live-npl",
        action="store_true",
        help=(
            "With search: live public NPL metadata via OpenAlex + Crossref "
            "(optional OPENALEX_API_KEY / CROSSREF_MAILTO)"
        ),
    )
    pa.add_argument(
        "--npl-providers",
        default="openalex,crossref",
        help="With --live-npl: comma list of providers (default openalex,crossref)",
    )
    pa.add_argument(
        "--max-live-results",
        type=int,
        default=10,
        help="With live foreign/NPL: max hits per query (default 10)",
    )
    pa.add_argument(
        "--no-browser",
        action="store_true",
        help="With pps-assist: checklist only (no Playwright)",
    )
    pa.add_argument(
        "--headless",
        action="store_true",
        help="With pps-assist: headless browser (landing page only)",
    )
    pa.add_argument(
        "--watch-seconds",
        type=float,
        default=300.0,
        help="With pps-assist: seconds to keep browser open (default 300)",
    )
    pa.add_argument(
        "--citation-graph",
        default="",
        help="JSON/JSONL citation edges {citing_id,cited_id,direction}",
    )
    pa.add_argument(
        "--family-graph",
        default="",
        help="JSON/JSONL family members {document_id,relation,related_to}",
    )
    pa.add_argument(
        "--no-report",
        action="store_true",
        help="With search: skip writing prior_art_report.json",
    )
    pa.add_argument(
        "--no-pps-checklist",
        action="store_true",
        help="With search: skip Patent Public Search human checklist",
    )
    pa.add_argument(
        "--auto-acknowledge",
        action="store_true",
        help="With search: write human coverage ack (requires --acknowledger)",
    )
    pa.add_argument(
        "--acknowledger",
        default="",
        help="Human name for acknowledge / pps-record / auto-acknowledge",
    )
    pa.add_argument(
        "--claim-search-complete",
        action="store_true",
        help="With acknowledge: request prior_art_search_complete if prerequisites hold",
    )
    pa.add_argument(
        "--pps-results",
        default="",
        help="With pps-record: JSON file of [{query_id, human_result_count, human_notes?}]",
    )
    pa.add_argument(
        "--query-id",
        default="",
        help="With pps-record: single query_id to update",
    )
    pa.add_argument(
        "--human-result-count",
        type=int,
        default=None,
        help="With pps-record + --query-id: hit count observed in PPS",
    )
    pa.add_argument(
        "--note",
        default="",
        help="Optional note for pps-record / other actions",
    )
    pa.add_argument("--run-id", default="", help="With show/attach-revision/pps-*/acknowledge")
    pa.add_argument("--run-dir", default="", help="With show/attach-revision/pps-*/acknowledge")
    pa.add_argument(
        "--revision-id",
        default="",
        help="With attach-revision: bind run into a revision case",
    )
    pa.add_argument(
        "--no-persist",
        action="store_true",
        help="With plan: print only, do not write under state-root/prior_art/",
    )
    pa.add_argument(
        "--verbose",
        action="store_true",
        help="Include full plan/journal payloads in stdout",
    )
    pa.set_defaults(func=_cmd_prior_art)

    audit = sub.add_parser(
        "audit-submission",
        help=(
            "Audit a response package against filing-obligation rules "
            "(MPEP/CFR pack citations) and prior-art coverage. Review only — "
            "not legal advice; never Sign/Pay/Submit."
        ),
    )
    audit.add_argument("--application-number", default="")
    audit.add_argument("--revision-id", default="")
    audit.add_argument(
        "--package-dir",
        default="",
        help="Response package directory (default: revision package_dir)",
    )
    audit.add_argument(
        "--prior-art-run-id",
        default="",
        help="Prior-art run id under state-root/prior_art/<app>/",
    )
    audit.add_argument(
        "--prior-art-run-dir",
        default="",
        help="Absolute prior-art run directory",
    )
    audit.add_argument(
        "--application-type",
        default="utility",
        help="utility|design|plant (default utility)",
    )
    audit.add_argument(
        "--scenario",
        default="",
        help="Filing scenario override (default from revision trigger or office_action_response)",
    )
    audit.add_argument(
        "--with-law-index",
        action="store_true",
        help="Also query JusticeDAO HF patent-legal hybrid index for cited MPEP/CFR",
    )
    audit.add_argument(
        "--no-persist",
        action="store_true",
        help="Print only; do not write under state-root/compliance_audits/",
    )
    audit.set_defaults(func=_cmd_audit_submission)

    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except PortfolioAutomationError as exc:
        print(
            json.dumps({"ok": False, "code": exc.code, "message": str(exc)}, indent=2),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
