"""American Legal Publishing (codelibrary.amlegal.com) scraper draft.

The public React SPA talks to unauthenticated JSON endpoints under
``https://codelibrary.amlegal.com/api/``:

  GET /api/clients/{slug}/
  GET /api/client-version/{slug}/latest/
  GET /api/code-toc/{code_uuid}/
  GET /api/section-toc/{section_id}/          # expand children
  GET /api/sec-info/{slug}/{version}/{code_slug}/{doc_id}/
  GET /api/render-doc/{slug}/{version}/{code_slug}/{doc_id}/

HTML from render-doc is React/JSX-ish (className, AnnotationDrawer, Link).
We sanitize it into ordinary HTML before emitting rows.

Target row shape matches ``parquet_writer.docs_to_html_rows`` Municode docs:
  Id, Title, TitleHtml, Content, DocOrderId
"""

from __future__ import annotations

import html as html_lib
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

PUBLISHER = "amlegal"
API = "https://codelibrary.amlegal.com/api"
SITE = "https://codelibrary.amlegal.com"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; JusticeDAO-MuniBot/1.0; "
        "+https://huggingface.co/datasets/justicedao/american_municipal_law)"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://codelibrary.amlegal.com/",
    "Origin": "https://codelibrary.amlegal.com",
}

AMLEGAL_URL_RE = re.compile(
    r"codelibrary\.amlegal\.com/codes/([^/?#]+)",
    re.I,
)


class RateLimitError(RuntimeError):
    def __init__(self, retry_after: float, message: str = "HTTP 429"):
        super().__init__(message)
        self.retry_after = retry_after


def parse_amlegal_url(url: str) -> Optional[str]:
    m = AMLEGAL_URL_RE.search(url or "")
    return m.group(1).lower() if m else None


def polite_get_json(
    url: str,
    *,
    sleep: float = 0.5,
    retries: int = 5,
    timeout: float = 90.0,
) -> Any:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            time.sleep(sleep + random.uniform(0, sleep * 0.25))
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                wait = float(e.headers.get("Retry-After") or (2 * (2**attempt)))
                time.sleep(wait)
                continue
            if e.code in (500, 502, 503, 504) and attempt < retries - 1:
                time.sleep((2**attempt) + random.uniform(0, 1))
                continue
            if e.code in (204, 404):
                return None
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep((2**attempt) + random.uniform(0, 1))
                continue
            raise
    raise last_err or RuntimeError(f"failed GET {url}")


def sanitize_amlegal_html(raw: str) -> str:
    """Convert JSX-ish render-doc HTML into something closer to normal HTML."""
    if not raw:
        return '<div class="chunk-content"></div>'
    s = raw
    # Drop React-only components (keep inner text if any by converting to span)
    for tag in ("AnnotationDrawer", "CodeOptions", "InterCodeLink"):
        s = re.sub(rf"<{tag}\b[^>]*>\s*</{tag}>", "", s, flags=re.I)
        s = re.sub(rf"<{tag}\b[^>]*/>", "", s, flags=re.I)
        s = re.sub(rf"<{tag}\b[^>]*>", "<span>", s, flags=re.I)
        s = re.sub(rf"</{tag}>", "</span>", s, flags=re.I)
    # <Link ...>text</Link> -> <a>
    s = re.sub(
        r'<Link\b([^>]*)\bto="\{\{\s*pathname:\s*\'([^\']+)\'[^}]*\}\}"([^>]*)>',
        r'<a href="\2"\1\3>',
        s,
        flags=re.I,
    )
    s = re.sub(r"<Link\b([^>]*)>", r"<a\1>", s, flags=re.I)
    s = re.sub(r"</Link>", "</a>", s, flags=re.I)
    s = s.replace("className=", "class=")
    # remove empty depth spans etc.
    s = re.sub(r'<span depth="\d+"></span>', "", s)
    if 'class="chunk-content"' not in s:
        s = f'<div class="chunk-content">{s}</div>'
    return s


def pick_primary_code(toc: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not toc:
        return None

    def rank(c: dict[str, Any]) -> tuple[int, str]:
        title = (c.get("title") or "").lower()
        slug = (c.get("slug") or "").lower()
        score = 0
        if "municipal code" in title or "code of ordinances" in title:
            score += 10
        if "code" in title:
            score += 3
        if "zoning" in title or "zoning" in slug:
            score -= 5
        if "charter" in title and "code" not in title:
            score -= 2
        return (-score, slug)

    return sorted(toc, key=rank)[0]


def expand_section_tree(
    section_id: int,
    *,
    sleep: float,
    max_nodes: int | None,
    collected: list[dict[str, Any]],
    seen_ids: set[int],
) -> None:
    if max_nodes is not None and len(collected) >= max_nodes:
        return
    if section_id in seen_ids:
        return
    seen_ids.add(section_id)
    data = polite_get_json(f"{API}/section-toc/{int(section_id)}/", sleep=sleep)
    if not data:
        return
    # The expanded node itself
    node = {
        "id": data.get("id") or section_id,
        "doc_id": data.get("doc_id"),
        "title": data.get("title") or "",
        "has_children": bool(data.get("children")),
        "parent_doc_id": data.get("parent_doc_id"),
        "code_uuid": data.get("code_uuid"),
    }
    collected.append(node)
    for child in data.get("children") or []:
        if max_nodes is not None and len(collected) >= max_nodes:
            return
        cid = child.get("id")
        if child.get("has_children") and cid is not None:
            expand_section_tree(
                int(cid),
                sleep=sleep,
                max_nodes=max_nodes,
                collected=collected,
                seen_ids=seen_ids,
            )
        else:
            # leaf: record child directly without extra section-toc roundtrip
            child_id = int(child.get("id") or 0)
            if child_id and child_id not in seen_ids:
                seen_ids.add(child_id)
                collected.append(
                    {
                        "id": child_id,
                        "doc_id": child.get("doc_id"),
                        "title": child.get("title") or "",
                        "has_children": False,
                        "parent_doc_id": child.get("parent_doc_id"),
                        "code_uuid": data.get("code_uuid"),
                    }
                )


def scrape_jurisdiction(
    source_url: str,
    *,
    sleep: float = 0.5,
    version: str = "latest",
    max_nodes: int | None = None,
    code_slug: str | None = None,
    render: bool = True,
) -> dict[str, Any]:
    """
    Scrape one amlegal jurisdiction.

    max_nodes caps how many TOC nodes we expand/render (smoke-test friendly).
    """
    slug = parse_amlegal_url(source_url)
    if not slug:
        # allow bare slug
        if re.fullmatch(r"[a-z0-9_\-]+", (source_url or "").lower()):
            slug = source_url.lower()
        else:
            return {"ok": False, "error": f"not an amlegal url: {source_url}", "docs": []}

    try:
        client = polite_get_json(f"{API}/clients/{slug}/", sleep=sleep) or {}
        cv = polite_get_json(f"{API}/client-version/{slug}/{urllib.parse.quote(version)}/", sleep=sleep)
    except Exception as e:
        return {"ok": False, "error": f"client/version fetch failed: {e}", "docs": []}

    if not cv or not cv.get("toc"):
        return {"ok": False, "error": f"no version/toc for {slug}/{version}", "docs": [], "client": client}

    toc = list(cv.get("toc") or [])
    if code_slug:
        code = next((c for c in toc if (c.get("slug") or "") == code_slug), None)
    else:
        code = pick_primary_code(toc)
    if not code:
        return {"ok": False, "error": "no code product in toc", "docs": [], "client": client, "version": cv}

    code_uuid = code.get("uuid")
    code_slug_final = code.get("slug") or ""
    top_sections = list(code.get("sections") or [])

    # Walk TOC
    nodes: list[dict[str, Any]] = []
    seen: set[int] = set()
    for sec in top_sections:
        if max_nodes is not None and len(nodes) >= max_nodes:
            break
        sid = sec.get("id")
        if sid is None:
            continue
        if sec.get("has_children") or sec.get("has_section_children"):
            expand_section_tree(
                int(sid),
                sleep=sleep,
                max_nodes=max_nodes,
                collected=nodes,
                seen_ids=seen,
            )
        else:
            if int(sid) not in seen:
                seen.add(int(sid))
                nodes.append(
                    {
                        "id": int(sid),
                        "doc_id": sec.get("doc_id"),
                        "title": sec.get("title") or "",
                        "has_children": False,
                        "parent_doc_id": None,
                        "code_uuid": code_uuid,
                    }
                )

    docs: list[dict[str, Any]] = []
    errors: list[str] = []
    for order, node in enumerate(nodes):
        doc_id = str(node.get("doc_id") or "")
        if not doc_id:
            continue
        title = node.get("title") or doc_id
        title_html = f'<div class="chunk-title">{html_lib.escape(title)}</div>'
        content = '<div class="chunk-content"></div>'
        if render:
            try:
                path = (
                    f"{API}/render-doc/{urllib.parse.quote(slug)}/"
                    f"{urllib.parse.quote(version)}/"
                    f"{urllib.parse.quote(code_slug_final)}/"
                    f"{urllib.parse.quote(doc_id, safe='')}/"
                )
                payload = polite_get_json(path, sleep=sleep) or {}
                content = sanitize_amlegal_html(payload.get("html") or "")
                if payload.get("title"):
                    title = payload["title"]
                    title_html = f'<div class="chunk-title">{html_lib.escape(title)}</div>'
            except Exception as e:
                errors.append(f"{doc_id}: {e}")
                continue
        docs.append(
            {
                "Id": doc_id,
                "Title": title,
                "TitleHtml": title_html,
                "Content": content,
                "DocOrderId": order,
                "_amlegal_id": node.get("id"),
                "_code_slug": code_slug_final,
            }
        )

    return {
        "ok": bool(docs),
        "error": None if docs else ("no docs; " + "; ".join(errors[:3])),
        "docs": docs,
        "client": client,
        "version": {"uuid": cv.get("uuid"), "name": cv.get("name"), "currency_info": cv.get("currency_info")},
        "code": {"uuid": code_uuid, "slug": code_slug_final, "title": code.get("title")},
        "nodes_expanded": len(nodes),
        "top_sections": len(top_sections),
        "fetch_errors": errors,
        "slug": slug,
        "place_name": client.get("name") or slug,
        "url": f"{SITE}/codes/{slug}/{version}/overview",
    }


def scrape_rows(
    source_url: str,
    *,
    sleep: float = 0.5,
    max_nodes: int | None = None,
) -> list[dict[str, Any]]:
    result = scrape_jurisdiction(source_url, sleep=sleep, max_nodes=max_nodes)
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "amlegal scrape failed")
    return list(result["docs"])


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Smoke-scrape one amlegal jurisdiction")
    ap.add_argument("url", nargs="?", default="https://codelibrary.amlegal.com/codes/silverton/latest/overview")
    ap.add_argument("--sleep", type=float, default=0.45)
    ap.add_argument("--max-nodes", type=int, default=12)
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()
    res = scrape_jurisdiction(
        args.url,
        sleep=args.sleep,
        max_nodes=args.max_nodes,
        render=not args.no_render,
    )
    print(json.dumps({k: v for k, v in res.items() if k not in {"docs", "client"}}, indent=2, default=str))
    print(f"docs={len(res.get('docs') or [])}")
    for d in (res.get("docs") or [])[:10]:
        html_len = len(d.get("Content") or "")
        print(f"  {d['DocOrderId']:>4} {d['Id']:<16} html={html_len:<5} {d['Title'][:70]}")
    sys.exit(0 if res.get("ok") else 1)
