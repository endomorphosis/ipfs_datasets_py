#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

DEFAULT_REPO = "endomorphosis/ipfs_datasets_py"
DEFAULT_TEMPLATES = [
    "docs/guides/legal_data/templates/HYBRID_LEGAL_WS11_ISSUE_BODIES_01_06.md",
    "docs/guides/legal_data/templates/HYBRID_LEGAL_WS11_ISSUE_BODIES_07_12.md",
]
DEFAULT_LABELS = ["hybrid-legal", "ws11"]


def run_cmd(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def parse_repo(repo: str) -> tuple[str, str]:
    owner, sep, name = repo.partition("/")
    if not sep or not owner or not name:
        raise ValueError(f"invalid repo format '{repo}', expected owner/name")
    return owner, name


def github_api_request(
    method: str,
    url: str,
    token: str,
    payload: dict | None = None,
) -> dict:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(url=url, method=method, data=data)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        message = f"GitHub API HTTP {exc.code}"
        try:
            error_payload = json.loads((exc.read() or b"").decode("utf-8") or "{}")
            api_message = str(error_payload.get("message") or "").strip()
            if api_message:
                message = f"{message}: {api_message}"
        except Exception:
            pass
        raise RuntimeError(message) from exc


def parse_ws11_issues(markdown_text: str) -> list[dict[str, str]]:
    pattern = re.compile(r"^##\s+(HL-WS11-\d{2}:[^\n]+)$", flags=re.MULTILINE)
    matches = list(pattern.finditer(markdown_text))
    issues: list[dict[str, str]] = []

    for index, match in enumerate(matches):
        section_start = match.end()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        section_text = markdown_text[section_start:section_end]

        ticket_header = match.group(1).strip()
        ticket_id = ticket_header.split(":", 1)[0].strip()

        title_match = re.search(r"Title:\s*\n\s*`([^`]+)`", section_text)
        title = title_match.group(1).strip() if title_match else ticket_header

        body_match = re.search(r"Body:\s*\n\s*```markdown\n(.*?)\n```", section_text, flags=re.DOTALL)
        if body_match:
            body = body_match.group(1).strip()
        else:
            body = section_text.strip()

        if not title or not body:
            continue

        issues.append(
            {
                "ticket_id": ticket_id,
                "title": title,
                "body": body,
            }
        )

    return issues


def load_issues_from_templates(template_paths: Iterable[Path]) -> list[dict[str, str]]:
    all_issues: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for path in template_paths:
        text = path.read_text(encoding="utf-8")
        parsed = parse_ws11_issues(text)
        for issue in parsed:
            ticket_id = issue["ticket_id"]
            if ticket_id in seen_ids:
                continue
            seen_ids.add(ticket_id)
            all_issues.append(issue)

    all_issues.sort(key=lambda item: item["ticket_id"])
    return all_issues


def issue_exists(repo: str, ticket_id: str) -> bool:
    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "all",
        "--limit",
        "5",
        "--search",
        f"{ticket_id} in:title",
        "--json",
        "number,title",
    ]
    result = run_cmd(cmd)
    payload = json.loads(result.stdout or "[]")
    for row in payload:
        title = str(row.get("title") or "")
        if ticket_id in title:
            return True
    return False


def issue_exists_api(repo: str, ticket_id: str, token: str) -> bool:
    query = f"repo:{repo} in:title {ticket_id} type:issue"
    encoded_query = urllib.parse.quote(query)
    url = f"https://api.github.com/search/issues?q={encoded_query}&per_page=5"
    payload = github_api_request("GET", url, token)
    for row in payload.get("items", []):
        title = str(row.get("title") or "")
        if ticket_id in title:
            return True
    return False


def create_issue(repo: str, title: str, body: str, labels: list[str]) -> str:
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]
    for label in labels:
        cmd.extend(["--label", label])
    result = run_cmd(cmd)
    return result.stdout.strip()


def create_issue_api(repo: str, title: str, body: str, labels: list[str], token: str) -> str:
    owner, name = parse_repo(repo)
    url = f"https://api.github.com/repos/{owner}/{name}/issues"
    payload = github_api_request(
        "POST",
        url,
        token,
        payload={"title": title, "body": body, "labels": labels},
    )
    html_url = str(payload.get("html_url") or "").strip()
    if not html_url:
        issue_number = payload.get("number")
        if issue_number is not None:
            return f"https://github.com/{owner}/{name}/issues/{issue_number}"
        raise RuntimeError("GitHub API response did not include issue URL")
    return html_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Create WS11 GitHub issues from template markdown files.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo in owner/name format")
    parser.add_argument(
        "--templates",
        nargs="*",
        default=DEFAULT_TEMPLATES,
        help="Template markdown file paths",
    )
    parser.add_argument("--label", action="append", default=None, help="Issue label (repeatable)")
    parser.add_argument(
        "--create",
        action="store_true",
        help="Actually create issues (default behavior is dry-run)",
    )
    parser.add_argument(
        "--allow-duplicates",
        action="store_true",
        help="Create even when ticket ID already exists in issue titles",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    template_paths = [repo_root / p for p in args.templates]

    missing = [str(p) for p in template_paths if not p.exists()]
    if missing:
        print("Missing template files:", file=sys.stderr)
        for path in missing:
            print(f"- {path}", file=sys.stderr)
        return 2

    labels = args.label if args.label else DEFAULT_LABELS
    github_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    gh_available = True
    try:
        run_cmd(["gh", "--version"])
    except Exception:
        gh_available = False

    if not gh_available and not github_token and args.create:
        print(
            "Neither `gh` CLI nor GH_TOKEN/GITHUB_TOKEN is available; cannot create issues.",
            file=sys.stderr,
        )
        return 2

    if gh_available:
        try:
            run_cmd(["gh", "auth", "status"], check=False)
        except Exception:
            pass
    elif github_token:
        print("[info] `gh` CLI not found; using GitHub REST API mode via GH_TOKEN/GITHUB_TOKEN")
    else:
        print("[warn] `gh` CLI not found; running template-only dry-run without duplicate checks")

    issues = load_issues_from_templates(template_paths)
    if not issues:
        print("No issues found in template files.")
        return 1

    created = 0
    skipped = 0
    failed = 0

    print(f"Repo: {args.repo}")
    print(f"Mode: {'CREATE' if args.create else 'DRY-RUN'}")
    print(f"Labels: {', '.join(labels)}")
    print(f"Tickets parsed: {len(issues)}")
    if gh_available:
        print("Create backend: gh")
    elif github_token:
        print("Create backend: github_api_token")
    else:
        print("Create backend: none (plan only)")

    for issue in issues:
        ticket_id = issue["ticket_id"]
        title = issue["title"]

        exists = False
        if not args.allow_duplicates:
            if gh_available:
                try:
                    exists = issue_exists(args.repo, ticket_id)
                except Exception as exc:
                    print(f"[warn] could not check existing for {ticket_id}: {exc}")
            elif github_token:
                try:
                    exists = issue_exists_api(args.repo, ticket_id, github_token)
                except Exception as exc:
                    print(f"[warn] could not check existing for {ticket_id} via API: {exc}")

        if exists:
            skipped += 1
            print(f"[skip] {ticket_id} already exists")
            continue

        if not args.create:
            print(f"[plan] {ticket_id} -> {title}")
            continue

        try:
            if gh_available:
                url = create_issue(args.repo, title, issue["body"], labels)
            elif github_token:
                url = create_issue_api(args.repo, title, issue["body"], labels, github_token)
            else:
                raise RuntimeError("no available backend for issue creation")
            created += 1
            print(f"[ok] {ticket_id} {url}")
        except Exception as exc:
            failed += 1
            print(f"[error] {ticket_id}: {exc}", file=sys.stderr)
            if github_token and ("HTTP 401" in str(exc) or "HTTP 403" in str(exc)):
                print("[error] stopping early due to authentication/permission failure", file=sys.stderr)
                break

    print(f"Summary: created={created} skipped={skipped} failed={failed} parsed={len(issues)}")
    return 1 if args.create and failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
