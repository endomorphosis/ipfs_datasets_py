#!/usr/bin/env python3
"""USPTO portfolio operator CLI — public ODP automation + private import helpers.

Subcommands:
  discover       Search ODP by inventor name; merge into portfolio seed
  refresh        Batch public status sync for seed matters
  confirm        Mark application numbers as operator-confirmed ownership
  prepare-import Build export_manifest.json + authorization.json for a folder
  import-folder  Import a local export folder into the private store
  attended-export
                 Launch attended Patent Center browser export helper
  show           Print seed / last review summary

Credentials:
  Public ODP uses env:USPTO_ODP_API_KEY (never pass the raw key on the CLI).
  Patent Center passwords are never accepted.
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
    confirm_ownership,
    default_state_root,
    discover_public_by_inventor,
    import_export_folder,
    load_portfolio_seed,
    merge_matters,
    save_portfolio_seed,
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
    report = sync_public_status_batch(
        seed,
        store_root=store,
        force_refresh=not bool(args.use_cache),
        sleep_seconds=float(args.sleep_seconds),
    )
    out = state / "public_status_review.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass
    summary = {
        "ok": True,
        "review_path": str(out),
        "success_count": report.get("success_count"),
        "failure_count": report.get("failure_count"),
        "reviews_compact": report.get("reviews_compact"),
    }
    print(json.dumps(summary, indent=2))
    return 0 if int(report.get("failure_count") or 0) == 0 else 1


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
    if args.seal_only:
        cmd.append("--seal-only")
    if args.json:
        cmd.append("--json")
    if args.login_timeout_seconds is not None:
        cmd.extend(["--login-timeout-seconds", str(args.login_timeout_seconds)])
    if args.watch_seconds is not None:
        cmd.extend(["--watch-seconds", str(args.watch_seconds)])
    return subprocess.call(cmd)


def _cmd_show(args: argparse.Namespace) -> int:
    state = _state_root(args)
    seed_path = _seed_path(state)
    review_path = state / "public_status_review.json"
    payload: dict[str, Any] = {
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
    print(json.dumps(payload, indent=2))
    return 0


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
    r.set_defaults(func=_cmd_refresh)

    c = sub.add_parser("confirm", help="Mark apps as confirmed ownership")
    c.add_argument("--application-number", action="append", default=[])
    c.add_argument("--ownership", default="confirmed_operator")
    c.set_defaults(func=_cmd_confirm)

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
    att.add_argument("--seal-only", action="store_true")
    att.add_argument("--login-timeout-seconds", type=float, default=600.0)
    att.add_argument("--watch-seconds", type=float, default=120.0)
    att.add_argument("--json", action="store_true")
    att.set_defaults(func=_cmd_attended_export)

    s = sub.add_parser("show", help="Show portfolio seed summary")
    s.add_argument("--include-review", action="store_true")
    s.set_defaults(func=_cmd_show)

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
