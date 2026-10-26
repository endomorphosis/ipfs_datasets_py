#!/usr/bin/env python3
"""Mexico / Puebla: municipal normativity from the Orden Juridico Poblano (ojp.puebla.gob.mx, state government,
free public site; robots.txt 404 => allow-all per RFC 9309; Joomla K2 listing + PDF attachments).

/normatividad-municipal lists the 217 municipios -> /legislaciondelestado?catid=N (&start=20k pages) -> items with
title, 'Publicado: <date>' (+ abrogation/reform notes) and /media/k2/attachments/*.pdf. One record per PDF.
Places: INEGI 21xxx via Wikidata P3801 (mx/wd_P3801_sites.csv) -> candidate-list place_id (wd:Q...).
Resumable: _state/mx_ojp_puebla/<catid>.json. Staging: MX/<pk>.ojp_puebla-pNNNN-<ts>.jsonl (validate_file before rename).
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import argparse, csv, hashlib, json, logging, os, re, sys, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, str(HERE.parent / "es"))
import schema as S  # noqa: E402
from es_bop import Fetcher, Blocked, pdf_text  # noqa: E402

BASE = "https://ojp.puebla.gob.mx"
STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
OUT, QUAR, UNM, STATE = STAGE / "MX", STAGE / "_quarantine" / "MX", STAGE / "_unmatched" / "MX", STAGE / "_state" / "mx_ojp_puebla"
BOT = "ojp_puebla"
log = logging.getLogger(BOT)
MONTHS = {m: i + 1 for i, m in enumerate("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^(municipio|municipality)\s+de\s+|\s+municipality$", "", s.strip())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def load_places():
    cand = {r["qid"]: r for r in csv.DictReader(open((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv")))
            if r["country_code"] == "MX"}
    by = {}
    for r in csv.DictReader(open(HERE / "wd_P3801_sites.csv")):
        if not r["code"].startswith("21") or len(r["code"]) != 5:
            continue
        q = r["item"].rsplit("/", 1)[1]
        c = cand.get(q, {})
        names = {norm(r["label"]), norm(c.get("place_name", ""))} - {""}
        p = {"place_id": c.get("place_id") or f"wd:{q}", "qid": q, "place_name": (r["label"] or c.get("place_name", "")).replace("Municipio de ", ""),
             "inegi": r["code"], "pop": float(c.get("population") or 0) if re.match(r"^[\d.]+$", c.get("population") or "") else 0}
        for n in names:
            by.setdefault(n, []).append(p)
    return {n: v[0] for n, v in by.items() if len({x["qid"] for x in v}) == 1}


def pub_date(t):
    m = re.search(r"Publicado:\s*(\d{1,2})\s+de\s+([A-Za-zé]+)\s+de\s+(\d{4})", t, re.I)
    if m and m.group(2).lower() in MONTHS:
        return f"{int(m.group(3)):04d}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return None


def doc_type(title):
    t = title.lower()
    if re.search(r"reglament|bando|c[oó]digo|lineamiento|norma|manual", t):
        return "regulation"
    if re.match(r"\s*ley\b", t):
        return "statute"
    return "gazette_act"


def parse_list(html):
    s = BeautifulSoup(html, "lxml")
    items = []
    for blk in s.select("div.files-download"):
        h = blk.select("h3.fs-15")
        title = h[0].get_text(" ", strip=True) if h else ""
        note = " ".join((blk.select_one("p.attachments") or blk).get_text(" ", strip=True).split())
        intro = blk.select_one("div.introtext")
        for a in blk.select("a.button-download[href]"):
            items.append({"url": urljoin(BASE, a["href"]), "title": title, "note": note,
                          "intro": intro.get_text(" ", strip=True)[:1000] if intro else ""})
    starts = sorted({int(x) for x in re.findall(r"[?&;]start=(\d+)", html)})
    return items, starts


def munis(f):
    r = f.get(BASE + "/normatividad-municipal")
    s = BeautifulSoup(r.content, "lxml")
    out = []
    for a in (s.find("main") or s).find_all("a", href=True):
        m = re.search(r"catid=(\d+)$", a["href"])
        if m and a.get_text(strip=True):
            out.append((int(m.group(1)), a.get_text(" ", strip=True)))
    return out


def write(pk, name, rows, folder):
    folder.mkdir(parents=True, exist_ok=True)
    fin, tmp = folder / f"{name}.jsonl", folder / f".{name}.tmp.jsonl"
    with tmp.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        fh.flush(); os.fsync(fh.fileno())
    if pk:
        v = S.validate_file(tmp, expect_place_key=pk)
        if not v["ok"]:
            raise RuntimeError(f"validate_file {fin.name}: {v['errors'][:3]}")
    os.rename(tmp, fin)


def flush(st, place, rows, catid):
    if not rows:
        return
    st["batch"] = st.get("batch", 0) + 1
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if place:
        pk = S.place_key(place["place_id"], None, "MX")
        good = [r for r in rows if not S.validate_record(r)]
        bad = [r for r in rows if S.validate_record(r)]
        if bad:
            QUAR.mkdir(parents=True, exist_ok=True)
            with open(QUAR / f"{pk}.{BOT}-c{catid}-p{st['batch']:04d}-{ts}.jsonl", "a") as q:
                for r in bad:
                    q.write(json.dumps({"reasons": S.validate_record(r), "record": r}, ensure_ascii=False) + "\n")
        if good:
            write(pk, f"{pk}.{BOT}-p{st['batch']:04d}-{ts}", good, OUT)
            st["n_docs"] = st.get("n_docs", 0) + len(good)
    else:
        write(None, f"{BOT}-c{catid}-p{st['batch']:04d}-{ts}", rows, UNM)
        st["n_unmatched"] = st.get("n_unmatched", 0) + len(rows)


def st_save(catid, st):
    STATE.mkdir(parents=True, exist_ok=True)
    t = STATE / f".{catid}.tmp"; t.write_text(json.dumps(st, ensure_ascii=False)); os.replace(t, STATE / f"{catid}.json")


def run_muni(f, catid, mname, place, a):
    p = STATE / f"{catid}.json"
    st = json.loads(p.read_text()) if p.exists() else {"catid": catid, "municipio": mname, "done": {}}
    if st.get("status") == "done" and not a.redo:
        return st
    if "items" not in st:
        items, seen_pages, todo = [], {0}, [0]
        while todo:
            start = todo.pop(0)
            r = f.get(f"{BASE}/legislaciondelestado?catid={catid}" + (f"&start={start}" if start else ""))
            if r.status_code != 200:
                raise IOError(f"list HTTP {r.status_code}")
            its, starts = parse_list(r.text)
            items += its
            for s0 in starts:
                if s0 not in seen_pages:
                    seen_pages.add(s0); todo.append(s0)
        st["items"] = list({i["url"]: i for i in items}.values()); st_save(catid, st)
    rows = []
    for it in st["items"]:
        u = it["url"]
        if u in st["done"]:
            continue
        try:
            r = f.get(u)
        except Blocked:
            st["done"][u] = "robots"; continue
        except Exception as e:  # noqa: BLE001
            st["done"][u] = f"err {type(e).__name__}"; continue
        if r.status_code != 200 or r.content[:4] != b"%PDF":
            st["done"][u] = f"http {r.status_code}"; continue
        text = pdf_text(r.content)
        if len(text) < 200:
            st["done"][u] = "no_text"; continue
        title = it["title"] or Path(u).stem.replace("_", " ")
        rec = {"place_id": place["place_id"] if place else None, "country_code": "MX",
               "doc_id": f"{BOT}-" + hashlib.sha1(u.encode()).hexdigest()[:16], "source_platform": "mx_ojp_puebla",
               "source_url": u, "doc_type": doc_type(title), "language": "es", "html_title": title, "title_native": title,
               "adopted_date": pub_date(it["note"]), "consolidated": False, "content_format": "pdf_text", "text": text,
               "retrieved_at": now_utc(), "summary": it["intro"] or None, "publication_note": it["note"][:500],
               "repealed": bool(re.search(r"abrogad", it["note"], re.I)) or None,
               "platform": "ojp_puebla", "platform_place_id": f"catid={catid}", "issuer_name": mname,
               "text_source": "pdf_text", "content_complete": True, "source_policy": "robots_allowed_rfc9309",
               "content_sha256": hashlib.sha256(text.encode()).hexdigest()}
        if place:
            rec.update({"place_name": place["place_name"], "qid": place["qid"], "admin_level": "municipality",
                        "iso_3166_2": "MX-PUE", "inegi_code": place["inegi"]})
        rows.append({k: v for k, v in rec.items() if v not in (None, "") or k == "place_id"}); st["done"][u] = 1
        if len(rows) >= 25:
            flush(st, place, rows, catid); rows = []; st_save(catid, st)
    flush(st, place, rows, catid)
    st.update(status="done", finished=now_utc()); st_save(catid, st)
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--only", default="")
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    f = Fetcher(min_interval=a.interval)
    places = load_places()
    M = munis(f)
    M.sort(key=lambda m: -(places.get(norm(m[1])) or {}).get("pop", 0))
    log.info("OJP Puebla municipios: %d, place-mapped %d", len(M), sum(1 for m in M if norm(m[1]) in places))
    for catid, mname in M:
        if a.only and a.only.lower() not in mname.lower():
            continue
        place = places.get(norm(mname))
        try:
            st = run_muni(f, catid, mname, place, a)
            log.info("%s (catid %d) -> %s items=%d docs=%s unmatched=%s", mname, catid, place and place["place_id"],
                     len(st.get("items", [])), st.get("n_docs", 0), st.get("n_unmatched", 0))
        except Blocked as e:
            log.warning("%s blocked: %s", mname, e)
        except Exception as e:  # noqa: BLE001
            log.warning("%s error: %s", mname, e)
    log.info("finished")


if __name__ == "__main__":
    main()
