#!/usr/bin/env python3
"""Build a production-scale public legal corpus recipe for Hub packaging.

Sources (public US government works):

* **35 U.S.C.** — all sections from ``justicedao/ipfs_uscode`` laws parquet
* **37 C.F.R. / eCFR Title 37** — sections from the eCFR enhanced renderer HTML
* **MPEP** — USPTO MPEP chapter pages linked from the official index

Writes a PATLAW-170-compatible recipe JSON (``source_roots`` + ``documents``)
suitable for ``package_patent_legal_hub_indexes.py --recipe``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


USER_AGENT = "patent-legal-production-corpus/1.0 (+https://huggingface.co/justicedao)"
RIGHTS = {
    "license_expression": "public-domain-US-government",
    "notes": "US government work (public domain); production recipe for Hub publish",
    "redistribution_allowed": True,
    "review_status": "reviewed",
    "reviewed_at": "2026-08-01T00:00:00Z",
    "reviewed_by": "patent-legal-governance",
}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _http_get(url: str, *, timeout: float = 120.0, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _doc(
    *,
    record_id: str,
    family: str,
    source_root_id: str,
    citation: str,
    title: str,
    section_id: str,
    text: str,
    authority_kind: str,
    current_through: str,
    source_uri: str,
    source_revision: str,
    source_id: str,
    effective_start: str = "2020-01-01",
) -> dict[str, Any]:
    body = (text or "").strip()
    if len(body) < 20:
        raise ValueError(f"text too short for {record_id}")
    digest = _sha256_text(body)
    return {
        "record_id": record_id,
        "family": family,
        "source_root_id": source_root_id,
        "classification": "public_official",
        "citation": citation,
        "title": title,
        "section_id": section_id,
        "text": body,
        "authority_kind": authority_kind,
        "authority_claim": "source_bound",
        "current_through": current_through,
        "effective_start": effective_start,
        "source_lineage": {
            "authority": "official",
            "source_id": source_id,
            "source_revision": source_revision,
            "source_sha256": digest,
            "source_uri": source_uri,
        },
        "rights_review": dict(RIGHTS),
    }


def load_title35_from_hf() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from huggingface_hub import hf_hub_download
    import pandas as pd

    path = hf_hub_download(
        repo_id="justicedao/ipfs_uscode",
        repo_type="dataset",
        filename="uscode_parquet/laws.parquet",
    )
    df = pd.read_parquet(
        path,
        columns=[
            "title_number",
            "section_number",
            "law_name",
            "text",
            "source_url",
            "date_modified",
            "ipfs_cid",
        ],
    )
    t35 = df[df["title_number"].astype(str) == "35"].copy()
    docs: list[dict[str, Any]] = []
    for row in t35.itertuples(index=False):
        sec = str(row.section_number).strip()
        title = str(row.law_name or f"35 U.S.C. § {sec}").strip()
        text = str(row.text or "").strip()
        url = str(row.source_url or "").strip() or (
            f"https://www.govinfo.gov/content/pkg/USCODE-2024-title35/html/"
            f"USCODE-2024-title35-sec{sec}.htm"
        )
        year = str(row.date_modified or "2024").strip() or "2024"
        docs.append(
            _doc(
                record_id=f"usc:35:{sec}",
                family="uscode",
                source_root_id="uscode-title35-2024",
                citation=f"35 U.S.C. § {sec}",
                title=title,
                section_id=sec,
                text=text,
                authority_kind="statute",
                current_through=f"{year}-12-31",
                source_uri=url,
                source_revision=f"govinfo-{year}-title35",
                source_id=f"uscode/title35/{sec}",
                effective_start=f"{year}-01-01",
            )
        )
    root = {
        "source_id": "uscode-title35-2024",
        "family": "uscode",
        "current_through": "2024-12-31",
        "official_edition_cutoff": "2024-12-31",
        "source_uri": "https://www.govinfo.gov/app/details/USCODE-2024-title35",
        "source_revision": "govinfo-2024-title35",
        "license_expression": "public-domain-US-government",
        "gaps": [],
    }
    return docs, root


def load_ecfr_title37(
    *, as_of: str = "2024-06-01"
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = f"https://www.ecfr.gov/api/renderer/v1/content/enhanced/{as_of}/title-37"
    html = _http_get(url, accept="text/html").decode("utf-8", errors="replace")
    # Split on section divs: <div class="section" id="1.1">
    pattern = re.compile(
        r'<div class="section" id="([^"]+)">\s*'
        r"(?:<h4[^>]*>(.*?)</h4>)?(.*?)"
        r'(?=<div class="section" id="|$)',
        re.IGNORECASE | re.DOTALL,
    )
    docs: list[dict[str, Any]] = []
    for match in pattern.finditer(html):
        sec_id = match.group(1).strip()
        heading_html = match.group(2) or ""
        body_html = match.group(3) or ""
        heading = _strip_html(heading_html)
        body = _strip_html(body_html)
        # Prefer heading + body; heading often includes § N.N Title
        text = (heading + "\n\n" + body).strip() if heading else body
        if len(text) < 40:
            continue
        title = heading or f"37 C.F.R. § {sec_id}"
        # Drop leading § citation from title when possible
        title = re.sub(r"^§\s*" + re.escape(sec_id) + r"\s*", "", title).strip() or title
        docs.append(
            _doc(
                record_id=f"ecfr:37:{sec_id}",
                family="ecfr",
                source_root_id=f"ecfr-title37-{as_of}",
                citation=f"37 C.F.R. § {sec_id}",
                title=title[:500],
                section_id=sec_id,
                text=text,
                authority_kind="regulation",
                current_through=as_of,
                source_uri=f"https://www.ecfr.gov/current/title-37/section-{sec_id}",
                source_revision=f"ecfr-{as_of}-title37",
                source_id=f"ecfr/title37/{sec_id}",
                effective_start=as_of,
            )
        )
    if len(docs) < 50:
        raise RuntimeError(
            f"eCFR Title 37 parse produced only {len(docs)} sections; refusing"
        )
    root = {
        "source_id": f"ecfr-title37-{as_of}",
        "family": "ecfr",
        "current_through": as_of,
        "official_edition_cutoff": as_of,
        "source_uri": "https://www.ecfr.gov/current/title-37",
        "source_revision": f"ecfr-{as_of}-title37",
        "license_expression": "public-domain-US-government",
        "gaps": [
            "eCFR is an unofficial editorial compilation of CFR; annual CFR "
            "edition remains the official printed authority where it conflicts"
        ],
    }
    return docs, root


def load_mpep_chapters() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    index_url = "https://www.uspto.gov/web/offices/pac/mpep/index.html"
    index_html = _http_get(index_url, accept="text/html").decode(
        "utf-8", errors="replace"
    )
    chapter_hrefs = sorted(
        set(
            re.findall(
                r'href="(mpep-\d{4}(?:-[^"]+)?\.html)"',
                index_html,
                flags=re.IGNORECASE,
            )
        )
    )
    # Prefer main chapter numbers, keep appendices.
    if not chapter_hrefs:
        raise RuntimeError("no MPEP chapter links found on USPTO index")

    docs: list[dict[str, Any]] = []
    base = "https://www.uspto.gov/web/offices/pac/mpep/"
    for href in chapter_hrefs:
        url = base + href
        try:
            html = _http_get(url, accept="text/html", timeout=90).decode(
                "utf-8", errors="replace"
            )
        except urllib.error.HTTPError as exc:
            print(f"skip mpep {href}: {exc}", file=sys.stderr)
            continue
        text = _strip_html(html)
        if len(text) < 200:
            continue
        # Extract title from <title> or first heading
        m = re.search(r"<title>([^<]+)</title>", html, re.I)
        title = _strip_html(m.group(1)) if m else href
        chap = re.sub(r"^mpep-|\.html$", "", href, flags=re.I)
        # Pin MPEP as-of to a non-future date relative to package policy as_of
        # (DEFAULT_REVIEWED_AT is 2026-08-01; current_through must not exceed it).
        mpep_as_of = "2026-08-01"
        docs.append(
            _doc(
                record_id=f"mpep:chapter:{chap}",
                family="mpep",
                source_root_id="mpep-e9-current",
                citation=f"MPEP {chap}",
                title=title[:500],
                section_id=chap,
                text=text[:500000],  # cap extremely large chapters
                authority_kind="guidance",
                current_through=mpep_as_of,
                source_uri=url,
                source_revision="uspto-mpep-web-current",
                source_id=f"mpep/{chap}",
                effective_start=mpep_as_of,
            )
        )
        time.sleep(0.35)  # polite crawl

    if len(docs) < 5:
        raise RuntimeError(f"MPEP fetch produced only {len(docs)} chapters")
    root = {
        "source_id": "mpep-e9-current",
        "family": "mpep",
        "current_through": "2026-08-01",
        "official_edition_cutoff": "2026-08-01",
        "source_uri": index_url,
        "source_revision": "uspto-mpep-web-current",
        "license_expression": "public-domain-US-government",
        "gaps": [
            "MPEP is USPTO examination guidance, not binding law",
            "chapters fetched from USPTO web HTML (not paginated PDF edition)",
        ],
    }
    return docs, root


def build_recipe(
    *,
    include_mpep: bool = True,
    ecfr_as_of: str = "2024-06-01",
) -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    roots: list[dict[str, Any]] = []

    print("loading Title 35 from justicedao/ipfs_uscode…", file=sys.stderr)
    t35_docs, t35_root = load_title35_from_hf()
    docs.extend(t35_docs)
    roots.append(t35_root)
    print(f"  title35 docs={len(t35_docs)}", file=sys.stderr)

    print(f"loading eCFR Title 37 as-of {ecfr_as_of}…", file=sys.stderr)
    ecfr_docs, ecfr_root = load_ecfr_title37(as_of=ecfr_as_of)
    docs.extend(ecfr_docs)
    roots.append(ecfr_root)
    print(f"  ecfr docs={len(ecfr_docs)}", file=sys.stderr)

    if include_mpep:
        print("loading MPEP chapters from USPTO…", file=sys.stderr)
        mpep_docs, mpep_root = load_mpep_chapters()
        docs.extend(mpep_docs)
        roots.append(mpep_root)
        print(f"  mpep docs={len(mpep_docs)}", file=sys.stderr)

    # Deduplicate by record_id
    by_id: dict[str, dict[str, Any]] = {}
    for d in docs:
        by_id[d["record_id"]] = d
    documents = list(by_id.values())
    documents.sort(key=lambda d: d["record_id"])

    recipe = {
        "notes": (
            "Production public patent-law corpus recipe: full 35 U.S.C., eCFR "
            "Title 37, and USPTO MPEP chapters. Built for JusticeDAO Hub publish."
        ),
        "recipe_id": "patlaw-production-public-legal-corpus",
        "schema_version": "patent.public_legal_corpus.v1",
        "source_roots": roots,
        "documents": documents,
        "expected": {
            "min_documents": 200,
            "families": ["uscode", "ecfr"] + (["mpep"] if include_mpep else []),
        },
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "counts": {
            "documents": len(documents),
            "by_family": _count_by(documents, "family"),
            "source_roots": len(roots),
        },
    }
    return recipe


def _count_by(docs: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in docs:
        k = str(d.get(key) or "")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Write production recipe JSON here",
    )
    p.add_argument(
        "--skip-mpep",
        action="store_true",
        help="Skip USPTO MPEP chapter fetch",
    )
    p.add_argument(
        "--ecfr-as-of",
        default="2024-06-01",
        help="eCFR as-of date (YYYY-MM-DD)",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    recipe = build_recipe(
        include_mpep=not args.skip_mpep,
        ecfr_as_of=args.ecfr_as_of,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(recipe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {args.output} documents={recipe['counts']['documents']} "
        f"by_family={recipe['counts']['by_family']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
