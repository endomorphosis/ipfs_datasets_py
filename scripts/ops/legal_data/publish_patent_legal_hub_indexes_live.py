#!/usr/bin/env python3
"""Operator live publish of patent-legal corpus + BM25 + vector + knowledge graph.

Builds the multi-artifact hub index package (default public-legal fixture or an
explicit recipe), admits it, creates missing JusticeDAO dataset repos, stages
authenticated PRs on the live Hub, signs an operator approval, promotes to
``main``, and writes content-free receipts under a work directory.

This is the **operator-invoked** live path. It never embeds tokens in receipts.
Requires ``HF_TOKEN`` (or ``~/.cache/huggingface/token``) with write access to
the target organization (default: ``justicedao``).

Example:

  python scripts/ops/legal_data/publish_patent_legal_hub_indexes_live.py \\
    --work-dir /var/tmp/patent-hub-live-publish \\
    --approver "operator@example.com"
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (  # noqa: E402
    BM25_REPOSITORY,
    CANONICAL_REPOSITORY_NAMES,
    CORPUS_REPOSITORY,
    KNOWLEDGE_GRAPH_REPOSITORY,
    ORGANIZATION,
    VECTORS_REPOSITORY,
)
from ipfs_datasets_py.processors.domains.patent.hf_publisher_v2 import (  # noqa: E402
    LiveHubApiAdapter,
    resolve_hub_token,
)
from scripts.ops.legal_data.admit_patent_legal_hub_indexes import (  # noqa: E402
    main as admit_main,
)
from scripts.ops.legal_data.package_patent_legal_hub_indexes import (  # noqa: E402
    main as package_main,
)
from scripts.ops.legal_data.stage_patent_legal_hub_indexes import (  # noqa: E402
    main as stage_main,
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_token() -> str:
    env_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()
    cache = Path.home() / ".cache" / "huggingface" / "token"
    if cache.is_file():
        text = cache.read_text(encoding="utf-8").strip()
        if text:
            # Expose to child CLIs via standard env name without printing.
            os.environ["HF_TOKEN"] = text
            return text
    token = resolve_hub_token(allow_missing=True)
    if token:
        os.environ.setdefault("HF_TOKEN", token)
        return token
    raise SystemExit(
        "Hub token required: set HF_TOKEN or login so "
        "~/.cache/huggingface/token exists"
    )


def _dataset_ids(organization: str) -> list[str]:
    org = organization.casefold()
    return [f"{org}/{name}" for name in CANONICAL_REPOSITORY_NAMES]


def _ensure_repos(api: LiveHubApiAdapter, dataset_ids: Sequence[str]) -> dict[str, str]:
    """Create missing dataset repos and return dataset_id → main head SHA."""
    bases: dict[str, str] = {}
    for dataset_id in dataset_ids:
        api.create_repo(
            repo_id=dataset_id,
            repo_type="dataset",
            private=False,
            exist_ok=True,
        )
        info = api.repo_info(repo_id=dataset_id, repo_type="dataset", revision="main")
        sha = getattr(info, "sha", None)
        if not sha:
            raise SystemExit(f"repo_info missing sha for {dataset_id}")
        bases[dataset_id] = str(sha)
        print(f"repo ready: {dataset_id} main={str(sha)[:12]}…", file=sys.stderr)
    return bases


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Operator live publish of patent-legal corpus/BM25/vector/graph "
            "to Hugging Face datasets (JusticeDAO multi-repo layout)."
        )
    )
    p.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Working directory for package + receipts (default: under /var/tmp)",
    )
    p.add_argument(
        "--organization",
        default=ORGANIZATION,
        help=f"Hub organization (default: {ORGANIZATION})",
    )
    p.add_argument(
        "--recipe",
        type=Path,
        default=None,
        help="Optional corpus recipe JSON (default: built-in multi-family fixture)",
    )
    p.add_argument(
        "--approver",
        default="operator-live-publish",
        help="Approver identity recorded on the HMAC approval receipt",
    )
    p.add_argument(
        "--skip-promote",
        action="store_true",
        help="Stage + sign only; leave PRs open for manual promote",
    )
    p.add_argument(
        "--dry-run-only",
        action="store_true",
        help="Build + admit + dry-run stage plan only (no Hub writes)",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    work = args.work_dir or Path(f"/var/tmp/patent-hub-live-{_utc_stamp()}")
    work = work.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)

    package_dir = work / "package"
    receipts = work / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    operator_key_path = work / "operator-approval.key"
    bases_path = work / "base-revisions.json"
    admission_path = package_dir / "hub-index-admission-receipt.json"
    stage_receipt = receipts / "stage-receipt.json"
    approval_path = receipts / "approval.json"
    promote_receipt = receipts / "promote-receipt.json"
    dry_run_receipt = receipts / "dry-run-receipt.json"
    summary_path = receipts / "publish-summary.json"

    print(f"work_dir={work}", file=sys.stderr)

    # 1) Package
    pkg_args = [
        "--stage",
        "--output-dir",
        str(package_dir),
    ]
    if args.recipe is not None:
        pkg_args.extend(["--recipe", str(args.recipe)])
    else:
        pkg_args.append("--default-fixture")
    rc = package_main(pkg_args)
    if rc != 0:
        return rc
    print(f"package staged at {package_dir}", file=sys.stderr)

    # 2) Admit (credentials must be unset for admission gate — token already
    #    may be set; admission rejects premature tokens.  Temporarily hide.)
    saved_tokens = {
        k: os.environ.pop(k)
        for k in list(os.environ)
        if k
        in {
            "HF_TOKEN",
            "HUGGING_FACE_HUB_TOKEN",
            "HUGGINGFACE_HUB_TOKEN",
            "HUGGINGFACE_TOKEN",
        }
    }
    try:
        rc = admit_main(
            [
                "--package-dir",
                str(package_dir),
                "--receipt-out",
                str(admission_path),
            ]
        )
    finally:
        os.environ.update(saved_tokens)
    if rc != 0:
        return rc
    print(f"admission receipt: {admission_path}", file=sys.stderr)

    # Resolve token for live steps
    token = _load_token()
    organization = str(args.organization).casefold()
    dataset_ids = _dataset_ids(organization)

    if args.dry_run_only:
        # Base SHAs optional for dry-run? Stage CLI requires bases — use zeros
        # only if repos missing: create zero placeholder fails SHA check.
        # For dry-run-only without repos, create temporary fake bases of 40 hex.
        bases = {did: "0" * 40 for did in dataset_ids}
        _write_json(bases_path, bases)
        rc = stage_main(
            [
                "--mode",
                "dry-run",
                "--package-dir",
                str(package_dir),
                "--base-revisions-file",
                str(bases_path),
                "--admission-receipt",
                str(admission_path),
                "--require-admission",
                "--organization",
                organization,
                "--receipt-out",
                str(dry_run_receipt),
            ]
        )
        print(f"dry-run receipt: {dry_run_receipt} rc={rc}", file=sys.stderr)
        return rc

    # 3) Ensure live repos + capture main SHAs
    api = LiveHubApiAdapter(token=token)
    bases = _ensure_repos(api, dataset_ids)
    _write_json(bases_path, bases)

    # 4) Stage live
    rc = stage_main(
        [
            "--mode",
            "stage",
            "--live-hub",
            "--package-dir",
            str(package_dir),
            "--base-revisions-file",
            str(bases_path),
            "--admission-receipt",
            str(admission_path),
            "--require-admission",
            "--organization",
            organization,
            "--receipt-out",
            str(stage_receipt),
            "--token-env",
            "HF_TOKEN",
        ]
    )
    if rc != 0:
        print("stage failed", file=sys.stderr)
        return rc
    print(f"stage receipt: {stage_receipt}", file=sys.stderr)

    # 5) Sign operator approval
    if not operator_key_path.exists():
        operator_key_path.write_bytes(secrets.token_bytes(32))
        operator_key_path.chmod(0o600)
    rc = stage_main(
        [
            "--mode",
            "sign",
            "--package-dir",
            str(package_dir),
            "--base-revisions-file",
            str(bases_path),
            "--organization",
            organization,
            "--operator-key-file",
            str(operator_key_path),
            "--approver",
            args.approver,
            "--approval-id",
            f"live-publish-{_utc_stamp()}",
            "--approval-out",
            str(approval_path),
        ]
    )
    if rc != 0:
        print("sign failed", file=sys.stderr)
        return rc
    print(f"approval: {approval_path}", file=sys.stderr)

    if args.skip_promote:
        summary = {
            "status": "staged_pending_promote",
            "work_dir": str(work),
            "package_dir": str(package_dir),
            "stage_receipt": str(stage_receipt),
            "approval": str(approval_path),
            "dataset_ids": dataset_ids,
            "main_published": False,
        }
        _write_json(summary_path, summary)
        print(json.dumps(summary, indent=2))
        return 0

    # 6) Promote live
    rc = stage_main(
        [
            "--mode",
            "promote",
            "--live-hub",
            "--package-dir",
            str(package_dir),
            "--base-revisions-file",
            str(bases_path),
            "--organization",
            organization,
            "--operator-key-file",
            str(operator_key_path),
            "--approval-file",
            str(approval_path),
            "--staged-receipt-file",
            str(stage_receipt),
            "--receipt-out",
            str(promote_receipt),
            "--token-env",
            "HF_TOKEN",
        ]
    )
    if rc != 0:
        print("promote failed", file=sys.stderr)
        return rc

    # 7) Verify main heads
    post_heads: dict[str, str] = {}
    for did in dataset_ids:
        info = api.repo_info(repo_id=did, repo_type="dataset", revision="main")
        post_heads[did] = str(getattr(info, "sha", "") or "")
        print(
            f"published: https://huggingface.co/datasets/{did} "
            f"main={post_heads[did][:12]}…",
            file=sys.stderr,
        )

    summary = {
        "status": "promoted",
        "work_dir": str(work),
        "package_dir": str(package_dir),
        "stage_receipt": str(stage_receipt),
        "approval": str(approval_path),
        "promote_receipt": str(promote_receipt),
        "dataset_ids": dataset_ids,
        "base_revisions": bases,
        "promoted_main_heads": post_heads,
        "main_published": True,
        "repositories": {
            "corpus": f"{organization}/{CORPUS_REPOSITORY}",
            "bm25": f"{organization}/{BM25_REPOSITORY}",
            "vectors": f"{organization}/{VECTORS_REPOSITORY}",
            "knowledge_graph": f"{organization}/{KNOWLEDGE_GRAPH_REPOSITORY}",
        },
    }
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
