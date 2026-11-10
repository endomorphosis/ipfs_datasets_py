#!/usr/bin/env python3
"""Tokelau (TK) collector — tokelau.org.nz + NZ PCO catalogue (keyless).

Skips paclii.org (Content-Signal ai-train=no).
legislation.govt.nz may present AWS WAF; no WAF bypass — fall back to
catalogue.data.govt.nz metadata and tokelau.org.nz Allow paths only.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

os.environ.setdefault("MALLOC_ARENA_MAX", "2")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wave2b_common import (  # noqa: E402
    LAW_COLS,
    RAW,
    ROOT,
    StrikeStop,
    polite_get,
    require_mem,
    session,
    utcnow,
    verify_load_dataset,
    write_json,
    write_parquet,
)

LICENSE = (
    "Tokelau Government / New Zealand legislation. Where sourced from "
    "legislation.govt.nz, Crown copyright with typical CC BY 4.0 reuse as "
    "stated by Parliamentary Counsel Office. Not legal advice."
)


def strip_html(html: str) -> str:
    html = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?>.*?</style>", " ", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    html = re.sub(r"&nbsp;", " ", html)
    html = re.sub(r"&amp;", "&", html)
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def main() -> int:
    require_mem()
    sess = session()
    strikes: list[int] = []
    docs = []
    # 1) tokelau.org.nz — find legislation-ish links
    seeds = [
        "https://www.tokelau.org.nz/",
        "https://www.tokelau.org.nz/Tokelau+Government.html",
        "https://www.tokelau.org.nz/Tokelau+Government/Government+Departments.html",
    ]
    seen_urls = set()
    for seed in seeds:
        try:
            r = polite_get(sess, seed, delay=2.0, strikes=strikes)
        except StrikeStop:
            raise
        if r.status_code != 200:
            continue
        html = r.text
        for href in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I):
            url = urljoin(seed, href)
            if "tokelau.org.nz" not in url:
                continue
            if any(x in url.lower() for x in ("law", "rule", "fono", "legisl", "act", "constitution", "statute")):
                seen_urls.add(url.split("#")[0])
        # also keep seed page if substantial
        text = strip_html(html)
        if len(text) >= 200 and re.search(r"law|fono|rule|act|constitution", text, re.I):
            docs.append((seed, "Tokelau government page", text[:500000]))
    # fetch candidate URLs (cap 25)
    for url in sorted(seen_urls)[:25]:
        if url in {d[0] for d in docs}:
            continue
        try:
            r = polite_get(sess, url, delay=2.0, strikes=strikes)
        except StrikeStop:
            raise
        if r.status_code != 200 or "text/html" not in (r.headers.get("content-type") or ""):
            continue
        text = strip_html(r.text)
        if len(text) < 50:
            continue
        title = re.search(r"<title>(.*?)</title>", r.text, re.I | re.S)
        title_s = strip_html(title.group(1)) if title else url
        docs.append((url, title_s, text[:500000]))
    # 2) Try NZ legislation search page lightly (may WAF)
    nz_try = "https://www.legislation.govt.nz/act/public/1948/0044/latest/whole.html"  # Tokelau Act 1948 historic known path — may 403/WAF
    try:
        r = polite_get(sess, nz_try, delay=2.0, strikes=strikes)
        if r.status_code == 200 and len(r.text) > 500 and "challenge" not in r.text.lower()[:500]:
            text = strip_html(r.text)
            if len(text) >= 50:
                docs.append((nz_try, "Tokelau Act 1948 (NZ PCO HTML)", text[:500000]))
        else:
            write_json(RAW / "tk_nz_pco_probe.json", {"url": nz_try, "status": r.status_code, "waf_or_short": True})
    except StrikeStop:
        write_json(RAW / "tk_nz_pco_probe.json", {"stopped": "3-strike"})
        raise
    except Exception as e:
        write_json(RAW / "tk_nz_pco_probe.json", {"error": str(e)})

    out = ROOT / "TK" / "upload_ready"
    data = out / "data"
    scrapers = out / "scrapers_and_normalizers"
    data.mkdir(parents=True, exist_ok=True)
    scrapers.mkdir(parents=True, exist_ok=True)
    for name in ("collect_tk_tokelau.py", "wave2b_common.py"):
        src = Path(__file__).resolve().parent / name
        (scrapers / name).write_bytes(src.read_bytes())
    laws = []
    for i, (url, title, text) in enumerate(docs):
        if len(text) < 50:
            continue
        laws.append(
            {
                "id": f"tk-{i:04d}",
                "title": title,
                "text": text,
                "source_url": url,
                "source_type": "tokelau_gov_or_nz_pco",
                "jurisdiction": "TK",
                "country": "Tokelau",
                "language": "en",
                "eli": None,
                "date": None,
                "date_issued": None,
                "retrieved_at": utcnow(),
                "license": LICENSE,
                "law_status": "unknown",
                "identifier": url,
                "official_identifier": url,
                "article_count": 0,
                "json_path": None,
                "metadata_json": json.dumps({"paclii_skipped": True}, ensure_ascii=False),
            }
        )
    validation = {
        "jurisdiction": "TK",
        "target_hf_repo": "endomorphosis/ipfs_tokelau_laws",
        "laws": 0,
        "articles": 0,
        "paclii": "skipped_ai-train=no",
        "push": "NOT_PUSHED",
        "candidate_docs": len(docs),
    }
    if laws:
        n = write_parquet(data / "laws.parquet", laws, LAW_COLS)
        validation["laws"] = n
        validation["load_dataset_verify"] = verify_load_dataset(out)
        (out / "README.md").write_text(
            f"""# Tokelau laws

Sources: tokelau.org.nz (robots Allow) and keyless NZ PCO HTML when not WAF-blocked.
PacLII skipped (Content-Signal ai-train=no).

Laws: {n}
Retrieved: {utcnow()}
Push: NOT_PUSHED
""",
            encoding="utf-8",
        )
    else:
        (out / "README.md").write_text(
            "# Tokelau — code-only\n\nNo text>=50 documents retrieved (WAF or empty).\n",
            encoding="utf-8",
        )
    write_json(out / "validation.json", validation)
    write_json(RAW / "tk_docs_index.json", [{"url": u, "title": t, "text_len": len(x)} for u, t, x in docs])
    print(json.dumps({"laws": validation["laws"], "docs": len(docs)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
