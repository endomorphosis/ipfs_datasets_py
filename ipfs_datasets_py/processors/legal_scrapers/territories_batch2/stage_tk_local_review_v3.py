#!/usr/bin/env python3
"""Stage Tokelau Statistics Rules into TK/local_review_only/ (rights HOLD).
Optionally probe legislation.govt.nz robots + Tokelau Acts for open Crown CC-BY path.
"""
from __future__ import annotations
import json, pathlib, sys, time

sys.path.insert(0, "/workspace/staging/territories_batch2_20261105")
from batch2_common_v3 import (  # noqa: E402
    ROOT,
    Polite,
    copy_sanitized_script,
    guard,
    install_guard,
    mem_available_gib,
    peak_rss_mb,
    write_json_x,
    write_text_x,
)

install_guard()
guard("tk_start")

from bs4 import BeautifulSoup
import pyarrow as pa
import pyarrow.parquet as pq

source = json.load((ROOT / "TK_portal.json").open())
soup = BeautifulSoup(pathlib.Path(source["page"]["raw_path"]).read_bytes(), "html.parser")
content = soup.select_one("#c1204.component_ContentDisplay_Content")
if content is None:
    raise SystemExit("NO_VERIFIED_CONTENT_CONTAINER")
for n in content(["script", "style"]):
    n.extract()
text = content.get_text("\n", strip=True)
if len(text) < 10000:
    raise SystemExit("LAW_BODY_SHORT")

ready = ROOT / "TK" / "local_review_only"
if (ready / "data" / "laws.parquet").exists():
    raise SystemExit("TK_LOCAL_REVIEW_ALREADY_EXISTS")
(ready / "data").mkdir(parents=True, exist_ok=True)
row = {
    "id": "TK-statistics-rules-2013",
    "title": "Tokelau Statistics Rules 2013 / Tulafono mo Fuainumela Fakamaumau 2013",
    "text": text,
    "jurisdiction_code": "TK",
    "language": "en,tkl",
    "source_url": source["page"]["requested_url"],
    "source_sha256": source["page"]["sha256"],
    "retrieved_at": source["page"]["observed_local"],
    "source_type": "official_Tokelau_government_rule_HTML",
    "license": "Rights review required: government website footer says all rights reserved; no explicit open reuse licence located",
    "coverage": "One rule only, not the complete Tokelau rules corpus",
}
p = ready / "data" / "laws.parquet"
pq.write_table(pa.Table.from_pylist([row]), str(p), compression="zstd")

# Probe NZ legislation robots + Tokelau Acts listing (open Crown / CC-BY 4.0)
nz_probe = {"attempted": False}
nz_rows = []
try:
    client = Polite(["www.legislation.govt.nz"], min_delay=2.5)
    client.setup("https://www.legislation.govt.nz/")
    nz_probe["robots_delay"] = client.delay.get("www.legislation.govt.nz")
    nz_probe["attempted"] = True
    # search page for Tokelau
    search_url = "https://www.legislation.govt.nz/all/results.aspx?search=ta_act%40bill%40regulation%40deemedreg_Tokelau_25_ac%40bc%40rc%40dc%40apub%40aloc%40apri%40apro%40aimp%40bgov%40bloc%40bpri%40bmem%40rpub%40rimp_ac%40bc%40rc%40ainf%40anif%40bcur%40rinf%40rnif_a_aw_se&p=1"
    # Prefer a simpler known Act URL path if robots allows
    candidates = [
        ("https://www.legislation.govt.nz/act/public/1948/0024/latest/whole.html", "Tokelau Act 1948"),
        ("https://www.legislation.govt.nz/act/public/1967/0038/latest/whole.html", "Tokelau Amendment Act 1967"),
        ("https://www.legislation.govt.nz/act/public/1970/0027/latest/whole.html", "Tokelau Amendment Act 1970"),
        ("https://www.legislation.govt.nz/act/public/1986/0031/latest/whole.html", "Tokelau Amendment Act 1986"),
        ("https://www.legislation.govt.nz/act/public/1996/0001/latest/whole.html", "Tokelau Amendment Act 1996"),
    ]
    nz_probe["candidates_tried"] = []
    for url, title in candidates:
        guard("tk_nz")
        try:
            body, meta = client.get(url)
        except ValueError as e:
            nz_probe["candidates_tried"].append({"url": url, "error": str(e)})
            continue
        entry = {"url": url, "title": title, "status": meta["status"], "challenge": meta.get("challenge")}
        nz_probe["candidates_tried"].append(entry)
        if meta["status"] != 200 or meta.get("challenge"):
            continue
        doc = BeautifulSoup(body, "html.parser")
        for n in doc(["script", "style", "nav", "header", "footer"]):
            n.extract()
        body_el = doc.select_one("#legislationBody") or doc.select_one(".legislation") or doc.body or doc
        t = body_el.get_text("\n", strip=True)
        entry["text_len"] = len(t)
        # Confirm page mentions Tokelau
        if "Tokelau" not in t and "Tokelau" not in (doc.title.string if doc.title else ""):
            entry["error"] = "not_tokelau_page"
            continue
        if len(t) < 500:
            entry["error"] = "too_short"
            continue
        act_id = url.rstrip("/").split("/")[-3] if "/act/" in url else title
        nz_rows.append(
            {
                "id": f"TK-NZ-{act_id}-{title.replace(' ', '_')}",
                "title": title,
                "text": t,
                "jurisdiction_code": "TK",
                "parent_country": "NZ",
                "language": "en",
                "source_url": meta["requested_url"],
                "source_sha256": meta["sha256"],
                "retrieved_at": meta["observed_local"],
                "source_type": "official_NZ_legislation_HTML",
                "license": "CC-BY-4.0 / open Crown copyright as stated by legislation.govt.nz",
                "coverage": "NZ Parliament Acts concerning Tokelau published on legislation.govt.nz",
            }
        )
        print("TK_NZ", title, len(t), flush=True)
except Exception as e:  # noqa: BLE001
    nz_probe["error"] = str(e)

write_json_x(
    ready / "validation.json",
    {
        "laws_rows": 1,
        "articles_rows": 0,
        "articles_file_created": False,
        "min_law_text_chars": len(text),
        "HOLD_RIGHTS_UNRESOLVED": True,
        "DO_NOT_UPLOAD": True,
        "rights_review_required": True,
        "publication_hold": "Do not upload until copyright/licensing reviewed and explicit HF GO received",
        "scope": "One official bilingual rule from tokelau.org.nz; not all Tokelau legislation",
        "nz_legislation_probe": nz_probe,
        "nz_open_licensed_rows_staged_elsewhere": len(nz_rows),
        "datasets_streaming_validation": "Pending central verifier",
        "push": "NOT_PUSHED",
        "peak_rss_mb": peak_rss_mb(),
    },
)
write_text_x(
    ready / "HOLD_RIGHTS_UNRESOLVED.md",
    "DO_NOT_UPLOAD\n\nTokelau government site footer: all rights reserved. "
    "Local review only until rights cleared and Benjamin/CoS GO.\n",
)
write_text_x(
    ready / "README.md",
    """---
configs:
- config_name: laws
  data_files: data/laws.parquet
---
# Tokelau Statistics Rules 2013 — LOCAL REVIEW ONLY

One official bilingual English/Tokelauan rule from the substantive official government
HTML content container. PUBLICATION HOLD: website footer says all rights reserved.
Obtain rights review and explicit publication GO before any external upload.
""",
)
for src in [pathlib.Path(__file__), ROOT / "batch2_common_v3.py"]:
    copy_sanitized_script(src, ready / "scrapers_and_normalizers" / src.name)

# If NZ open-licensed Acts collected, stage separate upload_ready (NOT the rights-held portal rule)
if nz_rows:
    uready = ROOT / "TK" / "upload_ready"
    if not (uready / "data" / "laws.parquet").exists():
        (uready / "data").mkdir(parents=True, exist_ok=True)
        up = uready / "data" / "laws.parquet"
        pq.write_table(pa.Table.from_pylist(nz_rows), str(up), compression="zstd")
        write_json_x(
            uready / "validation.json",
            {
                "laws_rows": len(nz_rows),
                "articles_rows": 0,
                "articles_file_created": False,
                "min_law_text_chars": min(len(r["text"].strip()) for r in nz_rows),
                "license": "CC-BY-4.0 / open Crown copyright (legislation.govt.nz)",
                "source": "www.legislation.govt.nz Tokelau Acts",
                "target_hf_repo": "endomorphosis/ipfs_tokelau_laws",
                "note": "Excludes tokelau.org.nz Statistics Rules (rights unresolved) which remain in local_review_only/",
                "push": "NOT_PUSHED",
                "peak_rss_mb": peak_rss_mb(),
            },
        )
        write_json_x(
            uready / "manifest_upload_ready.json",
            {
                "dataset": "endomorphosis/ipfs_tokelau_laws",
                "jurisdiction_code": "TK",
                "parent_country": "NZ",
                "package_path": str(uready),
                "laws_rows": len(nz_rows),
                "created_local": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
                "push": "HOLD_PENDING_BENJAMIN_GO",
            },
        )
        write_text_x(
            uready / "README.md",
            """---
license: cc-by-4.0
language: en
configs:
- config_name: laws
  data_files: data/laws.parquet
---
# Tokelau — NZ Parliament Acts (open Crown / CC-BY 4.0)

Official Tokelau Acts and Amendment Acts published on legislation.govt.nz.
Does NOT include tokelau.org.nz rules that remain under rights review in local_review_only/.
No Hugging Face upload performed (CoS HOLD).
""",
        )
        for src in [pathlib.Path(__file__), ROOT / "batch2_common_v3.py"]:
            copy_sanitized_script(src, uready / "scrapers_and_normalizers" / src.name)
        print("TK_NZ_UPLOAD_READY", len(nz_rows), flush=True)
    else:
        print("TK_NZ_UPLOAD_READY_EXISTS", flush=True)

print(
    "TK_LOCAL_REVIEW_READY",
    1,
    "nz_rows",
    len(nz_rows),
    "rss",
    peak_rss_mb(),
    "mem",
    f"{mem_available_gib():.3f}",
    flush=True,
)
