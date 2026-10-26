#!/usr/bin/env python3
"""Brazil LexML: state (estadual) and municipal norms, metadata records from the URN resolver pages.

robots.txt (www.lexml.gov.br): Disallow /busca/ (=> the SRU endpoint /busca/SRU is NOT used), /doc/, /linker/;
Allow /urn, /sru; Crawl-delay 5. URNs come from the sitemaps (lexml_sitemaps.py -> _sitemaps/mapN.txt, judicial and
federal URNs dropped). Each /urn/<URN> page gives Localidade/Autoridade/Título/Data/Ementa + links to the original
publication (mostly the câmara's SAPL PDF). Records are metadata + ementa (content_complete=false); full texts are
fetched by the SAPL crawler where the câmara runs SAPL.
Place: municipal -> wd:<QID> via (state slug, municipality slug) vs Wikidata P1585 labels; estadual -> iso:BR-<UF>.
Resumable: sqlite _state/br_lexml.sqlite (done URNs). Municipal URNs first, then state. Re-passes every 12 h.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import difflib
import argparse, csv, glob, hashlib, json, logging, os, re, sqlite3, sys, time, unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup
HERE = Path(__file__).resolve().parent
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline")); sys.path.insert(0, str(HERE.parent / "es")); sys.path.insert(0, str(HERE.parent))
import schema as S  # noqa: E402
from es_bop import Fetcher, Blocked  # noqa: E402

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
OUT, UNM, QUAR, STATE = STAGE / "BR", STAGE / "_unmatched" / "BR", STAGE / "_quarantine" / "BR", STAGE / "_state"
log = logging.getLogger("br_lexml")
UFS = {"11": ("RO", "rondonia"), "12": ("AC", "acre"), "13": ("AM", "amazonas"), "14": ("RR", "roraima"), "15": ("PA", "para"),
       "16": ("AP", "amapa"), "17": ("TO", "tocantins"), "21": ("MA", "maranhao"), "22": ("PI", "piaui"), "23": ("CE", "ceara"),
       "24": ("RN", "rio.grande.do.norte"), "25": ("PB", "paraiba"), "26": ("PE", "pernambuco"), "27": ("AL", "alagoas"),
       "28": ("SE", "sergipe"), "29": ("BA", "bahia"), "31": ("MG", "minas.gerais"), "32": ("ES", "espirito.santo"),
       "33": ("RJ", "rio.de.janeiro"), "35": ("SP", "sao.paulo"), "41": ("PR", "parana"), "42": ("SC", "santa.catarina"),
       "43": ("RS", "rio.grande.do.sul"), "50": ("MS", "mato.grosso.do.sul"), "51": ("MT", "mato.grosso"), "52": ("GO", "goias"),
       "53": ("DF", "distrito.federal")}
STOP = {"de", "da", "do", "das", "dos", "e", "d"}


def ns(slug):
    """LexML locality slugs drop Portuguese connectives ('rio.grande.sul', 'caxias.sul', 'sao.joao.boa.vista');
    normalise both sides the same way before matching."""
    return ".".join(t for t in slug.split(".") if t and t not in STOP)


STATE_UF = {ns(v[1]): v[0] for v in UFS.values()}


def sl(n):
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", ".", n).strip(".")


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# LexML slug -> IBGE code, where the Wikidata label in wd_P1585.csv is non-Portuguese and too far for the fuzzy guard
ALIAS = {"rio.grande.sul;jaguarao": "4311007", "amazonas;manaus": "1302603", "sao.paulo;osasco": "3534401",
         "rio.janeiro;paraty": "3303807",
         # renamed municipalities (LexML keeps the former name): São Valério da Natividade -> São Valério; Presidente Juscelino (RN) -> Serra Caiada
         "tocantins;sao.valerio.natividade": "1720499", "rio.grande.norte;presidente.juscelino": "2410306"}


def load_wd():
    wd, dup = {}, set()
    for r in csv.DictReader(open(HERE / "wd_P1585.csv")):
        c = r["code"].strip()
        if len(c) == 7 and c[:2] in UFS:
            k = ns(UFS[c[:2]][1]) + ";" + ns(sl(re.sub(r"\s*\(.*?\)", "", r["itemLabel"])))  # 'Palmas (Paraná)' -> palmas
            v = (r["item"].rsplit("/", 1)[1], r["itemLabel"], c)
            if k in wd and wd[k][2] != c:
                dup.add(k)
            wd.setdefault(k, v)
    for k in dup:                      # two different IBGE municipalities collapse to one slug -> never guess
        wd.pop(k, None)
    # Official IBGE names (pipeline/codes/cache/ibge_municipios.json) + shared crosswalk br_ibge -> place_id take precedence
    import json, sys
    sys.path.insert(0, str(HERE.parent / "common"))
    from place_codes import code_to_place, CACHE
    c2p = code_to_place("br_ibge", "BR")
    for m in json.load(open(CACHE / "ibge_municipios.json", encoding="utf8")):
        c = str(m["id"]); pid = c2p.get(c)
        if len(c) == 7 and c[:2] in UFS and pid and pid.startswith("wd:"):
            wd[ns(UFS[c[:2]][1]) + ";" + ns(sl(m["nome"]))] = (pid[3:], m["nome"], c)
    bycode = {v[2]: v for v in wd.values()}
    for r in csv.DictReader(open(HERE / "wd_P1585.csv")):
        bycode.setdefault(r["code"].strip(), (r["item"].rsplit("/", 1)[1], r["itemLabel"], r["code"].strip()))
    for k, c in ALIAS.items():
        if c in bycode:
            wd[k] = bycode[c]
    return wd


def place_for(loc, wd):
    parts = loc.split(";")
    uf = STATE_UF.get(ns(parts[0]))
    if len(parts) == 1:
        return ({"place_id": f"iso:BR-{uf}", "place_name": parts[0], "admin_level": "state", "iso_3166_2": f"BR-{uf}", "state_code": uf}
                if uf else None)
    hit = wd.get(ns(parts[0]) + ";" + ns(parts[1]))
    if not hit and uf:                 # Wikidata label in another language ('Uruguayana', 'Yaguarón'): guarded fuzzy, same state only
        st = ns(parts[0]) + ";"
        cands = [k for k in wd if k.startswith(st)]
        sc = sorted(((difflib.SequenceMatcher(None, ns(parts[1]), k[len(st):]).ratio(), k) for k in cands), reverse=True)[:2]
        if sc and sc[0][0] >= 0.85 and (len(sc) == 1 or sc[0][0] - sc[1][0] >= 0.05):
            hit = wd[sc[0][1]]
    if not hit or not uf or not hit[2].startswith([k for k, v in UFS.items() if v[0] == uf][0]):
        return None
    return {"place_id": f"wd:{hit[0]}", "qid": hit[0], "place_name": hit[1], "ibge_code": hit[2], "admin_level": "municipality",
            "iso_3166_2": f"BR-{uf}", "state_code": uf}


def parse(html):
    soup = BeautifulSoup(html, "lxml")
    f = {}
    for tr in soup.select("tr"):
        tds = tr.find_all(["td", "th"])
        if len(tds) >= 2:
            k = tds[0].get_text(" ", strip=True)
            if k and k not in f:
                f[k] = tds[1].get_text(" ", strip=True)
    if not f:   # definition-list / label layouts
        txt = soup.get_text("\n", strip=True).split("\n")
        for i, k in enumerate(txt[:-1]):
            if k in ("Localidade", "Autoridade", "Título", "Data", "Ementa", "Nome Uniforme") and k not in f:
                f[k] = txt[i + 1]
    links = list(dict.fromkeys(a["href"] for a in soup.find_all("a", href=True)
                               if a["href"].startswith("http") and "lexml.gov.br" not in a["href"]))
    main = soup.find(id="content") or soup.body
    return f, links, (str(main) if main else None), (soup.title.get_text(" ", strip=True) if soup.title else "")


def dt_of(urn):
    t = urn.split(":")[4] if len(urn.split(":")) > 4 else ""
    return "ordinance" if re.match(r"lei|emenda|codigo|regimento", t) and ":municipal:" in urn or ":camara.municipal:" in urn and t.startswith("lei") else \
        ("statute" if re.match(r"lei|emenda|constituicao|codigo", t) else "regulation")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--max-docs", type=int, default=0)
    ap.add_argument("--only", choices=["municipal", "state", "all"], default="all")
    ap.add_argument("--repass-hours", type=float, default=12)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    STATE.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE / "br_lexml.sqlite")
    db.execute("create table if not exists done(urn text primary key, status text, at text)"); db.commit()
    wd, f = load_wd(), Fetcher(min_interval=a.interval)
    f.s.headers["Accept-Language"] = "pt-BR,pt;q=0.9,en;q=0.5"
    meta = json.loads((STATE / "br_lexml_meta.json").read_text()) if (STATE / "br_lexml_meta.json").exists() else {"batch": 0, "docs": 0, "unmatched": 0}
    bufs, last_flush, n_new = defaultdict(list), time.time(), 0

    def flush_all(force=False):
        nonlocal last_flush
        for key in list(bufs):
            rows = bufs[key]
            if not rows or (not force and len(rows) < a.batch):
                continue
            meta["batch"] += 1
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            name = f"lexml-p{meta['batch']:06d}-{ts}"
            if key.startswith("UNM:"):
                UNM.mkdir(parents=True, exist_ok=True)
                fin = UNM / f"{name}.jsonl"; tmp = UNM / f".{name}.tmp.jsonl"
                with tmp.open("w") as fh:
                    for r in rows:
                        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    fh.flush(); os.fsync(fh.fileno())
                os.rename(tmp, fin); meta["unmatched"] += len(rows)
                with open(STAGE / "_unmatched_br.csv", "a", newline="") as fh:
                    w = csv.writer(fh)
                    for r in rows:
                        w.writerow(["lexml", key[4:], r["doc_id"], r["source_url"]])
            else:
                pk = S.place_key(key, None, "BR")
                good = [r for r in rows if not S.validate_record(r)]
                bad = [r for r in rows if S.validate_record(r)]
                if bad:
                    QUAR.mkdir(parents=True, exist_ok=True)
                    with open(QUAR / f"{pk}.{name}.jsonl", "a") as q:
                        for r in bad:
                            q.write(json.dumps({"reasons": S.validate_record(r), "record": r}, ensure_ascii=False) + "\n")
                if good:
                    OUT.mkdir(parents=True, exist_ok=True)
                    fin = OUT / f"{pk}.{name}.jsonl"; tmp = OUT / f".{pk}.{name}.tmp.jsonl"
                    with tmp.open("w") as fh:
                        for r in good:
                            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                        fh.flush(); os.fsync(fh.fileno())
                    v = S.validate_file(tmp, expect_place_key=pk)
                    if not v["ok"]:
                        raise RuntimeError(f"validate_file {fin.name}: {v['errors'][:3]}")
                    os.rename(tmp, fin); meta["docs"] += len(good)
            for r in rows:
                db.execute("insert or replace into done values(?,?,?)", (r["lexml_urn"], "ok", now_utc()))
            bufs[key] = []
        db.commit()
        t = STATE / ".br_lexml_meta.tmp"; t.write_text(json.dumps(meta)); os.replace(t, STATE / "br_lexml_meta.json")
        if force:                          # only a forced flush resets the timer (round-robin queue rarely fills a 50-row batch)
            last_flush = time.time()

    while True:
        urns = []
        n_maps = len(glob.glob(str(HERE / "_sitemaps" / "map*.txt")))
        for fn in sorted(glob.glob(str(HERE / "_sitemaps" / "map*.txt")), key=lambda x: int(re.sub(r"\D", "", Path(x).name) or 0)):
            urns.extend(u.strip() for u in open(fn) if u.strip())
        done = {r[0] for r in db.execute("select urn from done")}
        muni = [u for u in urns if re.match(r"urn:lex:br;[^:;]+;[^:]+:", u)]
        est = [u for u in urns if re.match(r"urn:lex:br;[^:;]+:", u)]
        order = (muni if a.only != "state" else []) + (est if a.only != "municipal" else [])
        todo0 = [u for u in dict.fromkeys(order) if u not in done]
        groups = defaultdict(list)                 # round-robin across localities so coverage spreads over places
        for u in todo0:
            groups[re.match(r"urn:lex:br;([^:]+):", u).group(1)].append(u)
        del todo0
        todo, its = [], [iter(g) for g in groups.values()]
        while its:
            nxt = []
            for it in its:
                u = next(it, None)
                if u is not None:
                    todo.append(u); nxt.append(it)
            its = nxt
        groups.clear()
        log.info("pass: sitemap urns kept=%d municipal=%d state=%d done=%d todo=%d", len(urns), len(muni), len(est), len(done), len(todo))
        t_pass, rescan = time.time(), False
        for urn in todo:
            if a.max_docs and n_new >= a.max_docs:
                break
            if time.time() - t_pass > 3 * 3600 and len(glob.glob(str(HERE / "_sitemaps" / "map*.txt"))) != n_maps:
                rescan = True; break             # sitemap download still growing -> rebuild the (municipal-first) queue
            loc = re.match(r"urn:lex:br;([^:]+):", urn).group(1)
            url = "https://www.lexml.gov.br/urn/" + urn
            try:
                r = f.get(url)
            except Blocked as e:
                db.execute("insert or replace into done values(?,?,?)", (urn, "robots", now_utc())); continue
            except Exception as e:  # noqa: BLE001
                log.warning("fetch %s: %s", urn, e); time.sleep(30); continue
            if r.status_code != 200:
                db.execute("insert or replace into done values(?,?,?)", (urn, f"http {r.status_code}", now_utc())); continue
            fl, links, html, ptitle = parse(r.text)
            title = fl.get("Título") or ptitle.split("::")[0].strip()
            ementa = fl.get("Ementa")
            p = place_for(loc, wd)
            m = re.search(r":(\d{4}-\d{2}-\d{2})[;:]", urn)
            text = "\n".join(x for x in (title, ementa, fl.get("Localidade"), fl.get("Autoridade")) if x)
            rec = {"place_id": p["place_id"] if p else None, "country_code": "BR", "doc_id": "lexml-" + hashlib.sha1(urn.encode()).hexdigest()[:16],
                   "lexml_urn": urn, "source_platform": "br_lexml", "source_url": url, "doc_type": dt_of(urn), "language": "pt",
                   "html_title": title, "title_native": title, "adopted_date": m.group(1) if m else None, "consolidated": False,
                   "content_format": "html", "text": text, "html": html, "retrieved_at": now_utc(), "summary": ementa,
                   "lexml_localidade": fl.get("Localidade"), "lexml_autoridade": fl.get("Autoridade"),
                   "publication_urls": links or None, "platform": "br_lexml", "platform_place_id": loc,
                   "text_source": "lexml_metadata", "content_complete": False, "source_policy": "robots_allowed_rfc9309"}
            if p:
                rec.update({k: v for k, v in p.items() if k != "place_id"})
            rec = {k: v for k, v in rec.items() if v not in (None, "") or k == "place_id"}
            bufs[p["place_id"] if p else "UNM:" + loc].append(rec); n_new += 1
            if n_new % 200 == 0:
                log.info("progress new=%d staged_total=%d unmatched=%d", n_new, meta["docs"], meta["unmatched"])
            if time.time() - last_flush > 900 or any(len(v) >= a.batch for v in bufs.values()):
                flush_all(force=time.time() - last_flush > 900)
        flush_all(force=True)
        log.info("pass finished: new=%d staged_total=%d unmatched=%d", n_new, meta["docs"], meta["unmatched"])
        if a.max_docs:
            return
        if rescan:
            continue
        time.sleep(a.repass_hours * 3600)


if __name__ == "__main__":
    main()
