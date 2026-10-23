#!/usr/bin/env python3
"""Bremen (DE-HB) state law, live from the official Transparenzportal Bremen (www.transparenz.bremen.de) -> iso:DE-HB.

  de_hb.py [--limit N] [--review] [--types "Gesetze und Rechtsverordnungen,Staatsverträge"]

robots.txt (2026-10-17 PT): 200, empty => allow-all (RFC 9309); >= 2 s per host. Terms (nutzungsbedingungen-3964): reuse
under each document's listed licence (all 4,516 Vorschriften: CC BY-NC-ND), attribution "Verantwortliche Stelle" +
"Freie Hansestadt Bremen". Statute text itself is an amtliches Werk (§ 5 Abs. 1 UrhG).
Discovery: the portal's Vorschriften search, filtered by Dokumententyp (default: Gesetze und Rechtsverordnungen,
Staatsverträge), 50 per page; a second pass with Gültigkeit=Außer Kraft marks repealed ids (in_force=false).
Each document: /metainformationen/<slug>-<id>?asl=bremen203_tpgesetz.c.55340.de&template=20_gp_ifg_meta_detail_d (juris
consolidated full text + metadata). Municipal items (Ortsgesetze, Stadtgemeinde Bremen, Stadt Bremerhaven / Magistrat)
are skipped (municipal lanes). doc_id hb_transparenz:<portal id>.
"""
from __future__ import annotations
import argparse, json, logging, re, sys, time
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bs4 import BeautifulSoup  # noqa: E402
import common  # noqa: E402
from common import PoliteSession, utcnow, check_guards, STAGING  # noqa: E402
from arch_common import clean  # noqa: E402

BASE = "https://www.transparenz.bremen.de"
LIST = (BASE + "/vorschriften-72741?id=72743&fulltext=&gsid=kogis_tp_berlin01.c.60176.de&_article_id=72741"
        "&vorschriften%5B0%5D={typ}{extra}&skip={skip}&max=50&sort=titel&order=asc")
PLACE = dict(place_id="iso:DE-HB", country_code="DE", place_name="Freie Hansestadt Bremen", qid="Q1209",
             iso_3166_2="DE-HB", admin_level="adm1", platform="hb_transparenz", platform_place_id="HB")
MUNI = re.compile(r"\bOrtsgesetz|\bOrtsrecht|Stadtgemeinde|\bStadt Bremerhaven\b|\bMagistrat|Stadtverordnetenversammlung", re.I)
BLOCK = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div", "table", "pre", "dt", "dd"]
WORK = STAGING / "_work" / "de_hb"
log = logging.getLogger("de_hb")


def de_date(s):
    m = re.search(r"(\d\d)\.(\d\d)\.(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def block_text(node):
    for t in node.select("script, style, noscript, button, form, .noprint, .print_hide"):
        t.decompose()
    for br in node.find_all("br"):
        br.replace_with("\n")
    for t in node.find_all(BLOCK):
        t.append("\n")
    for t in node.find_all("td"):
        t.append(" ")
    return clean(node.get_text(""))


def list_items(sess, typ, extra="", cap=None):
    out, skip = [], 0
    while True:
        url = LIST.format(typ=quote_plus(typ), extra=extra, skip=skip)
        r, _ = sess.get(url)
        s = BeautifulSoup(r.text, "lxml")
        items = s.select("li.search-result-item[data-id]")
        for it in items:
            a = next((a for a in it.select("a.more") if "Vorschrift direkt" in a.get_text()), None)
            st = it.find(string=re.compile(r"Stand:"))
            out.append(dict(id=it["data-id"], title=it.h2.get_text(" ", strip=True), url=a["href"] if a else None,
                            typ=typ, stand=st.strip() if st else None))
        if len(items) < 50 or (cap and len(out) >= cap):
            return out
        skip += 50


def parse(url, html, item, repealed_ids):
    s = BeautifulSoup(html, "lxml")
    main = s.select_one("div.main_article div.docLayoutText")
    if main is None:
        return None, "no_doc_text"
    text = block_text(main)
    head = text[:3000]
    meta = {}
    for lab, rx in (("abk", r"(?:juris-Abkürzung|Amtliche Abkürzung):\s*([^\n]+)"), ("aus", r"Ausfertigungsdatum:\s*(\d\d\.\d\d\.\d{4})"),
                    ("gab", r"Gültig ab:\s*(\d\d\.\d\d\.\d{4})"), ("gbis", r"Gültig bis:\s*(\d\d\.\d\d\.\d{4})"),
                    ("typ", r"Dokumenttyp:\s*\n?\s*([^\n:]+)\n"), ("fund", r"Fundstelle:\s*([^\n]+)"),
                    ("glied", r"Gliederungs-Nr:?:?\s*([^\n]+)")):
        m = re.search(rx, head)
        if m and m.group(1).strip(" -"):
            meta[lab] = m.group(1).strip()
    typs = [t.strip() for t in re.findall(r"Dokumenttyp:\s*\n?\s*([^\n:]+)\n", head) if t.strip()]
    typs = [t for t in typs if t != "Gesetze und Rechtsverordnungen"] or typs
    if typs:
        meta["typ"] = typs[0]
    if meta.get("fund"):
        parts = []
        for x in re.split(r"\s*,\s*,\s*|;\s*(?=[A-Z])", meta["fund"]):
            x = x.strip(" ,")
            if x and x not in parts:
                parts.append(x)
        meta["fund"] = "; ".join(parts)
    jid = re.search(r"jgwsAiZDoc-(jlr-[A-Za-z0-9]+?)(?:NN\d{8,}|\")", html)
    title = item["title"] or (s.title.get_text(strip=True).split(" - Transparenzportal")[0] if s.title else "")
    if len(text) < 200:
        return None, "too_short"
    dtyp = (meta.get("typ") or "").lower()
    doc_type = "statute" if dtyp.startswith("gesetz") or "staatsvertrag" in dtyp else "regulation"
    rec = dict(PLACE, doc_id=f"hb_transparenz:{item['id']}", source_platform="hb_transparenz", source_url=url,
               doc_type=doc_type, language="de", title_native=title[:1000], consolidated=True, content_format="html",
               text=text, retrieved_at=utcnow(), source_official=True,
               in_force=(False if item["id"] in repealed_ids else True),
               source_org="Freie Hansestadt Bremen - Transparenzportal Bremen (Gesetzesportal, juris)",
               license_note="Transparenzportal Bremen: CC BY-NC-ND (portal licence; attribution: Verantwortliche Stelle, "
                            "Freie Hansestadt Bremen); statute text = amtliches Werk (§ 5 Abs. 1 UrhG)",
               source_policy="robots_allowed_rfc9309")
    if meta.get("fund"):
        rec["number"] = meta["fund"][:300]
    if de_date(meta.get("aus")):
        rec["adopted_date"] = de_date(meta["aus"])
    if de_date(meta.get("gab")):
        rec["effective_date"] = de_date(meta["gab"])
    if de_date(meta.get("gbis")) and de_date(meta["gbis"]) < utcnow()[:10]:
        rec["in_force"] = False
    stand = re.search(r"Stand:\s*(\d\d\.\d\d\.\d{4})", item.get("stand") or "")
    rec["extra_metadata"] = {k: v for k, v in dict(
        abkuerzung=meta.get("abk"), juris_doc_id=jid.group(1) if jid else None, gueltig_bis=de_date(meta.get("gbis")),
        dokumenttyp=meta.get("typ"), portal_dokumententyp=item["typ"], gliederungs_nr=meta.get("glied"),
        portal_stand=de_date(stand.group(1)) if stand else None, portal_id=item["id"]).items() if v not in (None, "", "-")}
    return rec, "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--review", action="store_true")
    ap.add_argument("--types", default="Gesetze und Rechtsverordnungen,Staatsverträge")
    ap.add_argument("--chunk", type=int, default=500)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    WORK.mkdir(parents=True, exist_ok=True)
    sess = PoliteSession(log=log.info)
    ok, pol = sess.allowed(BASE + "/vorschriften-72741")
    log.info("robots: allowed=%s policy=%s delay=%.1fs", ok, pol, sess.delay_for(BASE + "/"))
    if not ok:
        sys.exit("robots disallow")
    items, repealed = [], set()
    cache = WORK / "items.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
        d = json.loads(cache.read_text()); items, repealed = d["items"], set(d["repealed"])
    else:
        for typ in a.types.split(","):
            items += list_items(sess, typ.strip(), cap=(a.limit * 3 if a.limit else None))
            repealed |= {i["id"] for i in list_items(sess, typ.strip(), extra="&gltigkeit%5B0%5D=Au%C3%9Fer+Kraft")}
        if not a.limit:
            cache.write_text(json.dumps({"items": items, "repealed": sorted(repealed)}, ensure_ascii=False))
    log.info("listed %d items (%d repealed)", len(items), len(repealed))
    done = set()
    dp = WORK / "done.tsv"
    if dp.exists():
        done = {l.split("\t")[0] for l in dp.open()}
    seen, rows, keys, stats, files = set(), [], [], {}, []

    def flush():
        nonlocal rows, keys
        if rows:
            p, errs = common.stage_place("DE", "iso:DE-HB", rows, tag="hb_transparenz", review=a.review)
            log.info("staged %s rows=%d errs=%s", p, len(rows), json.dumps(errs)[:300] if errs else 0)
            files.append(str(p))
            with dp.open("a") as f:
                for k in keys:
                    f.write(f"{k}\t{'review' if a.review else 'staged'}\t{utcnow()}\n")
        rows, keys = [], []

    n = 0
    for it in items:
        if it["id"] in seen or it["id"] in done:
            continue
        seen.add(it["id"])
        if MUNI.search(it["title"]):
            stats["skip_municipal"] = stats.get("skip_municipal", 0) + 1; continue
        if not it["url"]:
            stats["no_url"] = stats.get("no_url", 0) + 1; continue
        if a.limit and n >= a.limit:
            break
        check_guards()
        try:
            r, _ = sess.get(it["url"])
        except PermissionError as e:
            log.error("stop: %s", e); break
        except Exception as e:
            log.warning("fetch fail %s: %s", it["url"], e); stats["fetch_fail"] = stats.get("fetch_fail", 0) + 1; continue
        if r.status_code != 200:
            stats[f"http_{r.status_code}"] = stats.get(f"http_{r.status_code}", 0) + 1; continue
        rec, why = parse(it["url"], r.text, it, repealed)
        if rec is None:
            stats[why] = stats.get(why, 0) + 1; continue
        rows.append(rec); keys.append(it["id"]); n += 1
        if len(rows) >= a.chunk:
            flush()
        if n % 50 == 0:
            log.info("progress %d %s", n, stats)
    flush()
    log.info("done: built=%d stats=%s files=%s", n, stats, files)


if __name__ == "__main__":
    main()
