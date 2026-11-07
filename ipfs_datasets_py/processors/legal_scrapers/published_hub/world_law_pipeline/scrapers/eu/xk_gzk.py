#!/usr/bin/env python3
"""Kosovo: Gazeta Zyrtare (gzk.rks-gov.net) - acts of local institutions (municipalities), "LocalInstActsList.aspx".

robots.txt (RFC 9309, checked per request): only /AppCode /App_Data /Controls /Images /Scripts /gzk.asmx ... disallowed.
list    LocalInstActsList.aspx  (ASP.NET grid; paging = read-only __doPostBack 'lbNext', no data submitted)
detail  ActDetail.aspx?ActID=N  (Lloji/Numri/Institucioni/Data e publikimit)
text    PDF via the detail page's read-only download postback (imgDownload); pdftotext. Scanned PDFs -> content_complete=false.
Place: "Komuna e X" -> Wikidata municipality (P31 Q2989682, sq label; data/wd_xk_municipalities.csv) -> candidate row for the
municipality QID, else its seat (P36). Not found -> _unmatched.
Usage: python3 xk_gzk.py catalog | fetch [--test N] | all | status
"""
from __future__ import annotations
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths

import argparse, csv, gc, html as H, json, random, re, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.live import STAGE, Done, PoliteSession, Stager, get_logger, utcnow  # noqa: E402

BASE = "https://gzk.rks-gov.net/"
STATE = STAGE / "_state" / "xk"
CAT = STATE / "catalog.jsonl"
CAND = Path((_wl_os.environ.get("GLOBAL_MUNICIPALITIES_ROOT", "/workspace/global_municipalities") + "/global_municipalities_candidate.csv"))
WD = Path(__file__).resolve().parent / "data" / "wd_xk_municipalities.csv"
log = get_logger("xk_gzk")
HID = re.compile(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"')


def hidden(t):
    return {m.group(1): H.unescape(m.group(2)) for m in HID.finditer(t)}


def clean(s):
    return " ".join(H.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def fold(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", "".join(c for c in s if not unicodedata.combining(c))).split())


XK_SEED = "wikidata/Q2989682"
# municipality QID -> candidate row keyed to the town QID (2026-10-30)
XK_ALIAS = {"Q2507287": "Q112657", "Q860157": "Q963121", "Q860171": "Q1527566", "Q794063": "Q59089",
            "Q6081267": "Q994263", "Q2605602": "Q2054378"}


# gazette issuer spellings missing from / differing from the Wikidata sq/en labels -> municipality QID (2026-10-30)
XK_NAMES = {"komuna e istogut": "Q2043104", "komuna e hani i elezit": "Q2347012", "komuna e drenasit": "Q860365",
            "komuna e suhareks": "Q794044", "opstina strpce": "Q2043155", "opstina partes": "Q2605602",
            "komuna partesh": "Q2605602", "komuna e novoberdes": "Q6081267", "komuna kllokot": "Q860171",
            "opstina ranilug": "Q15529552", "komuna ranillug": "Q15529552", "komuna e mitrovices se jugut": "Q134522751",
            "komuna e mitrovices se veriut": "Q12756670", "opstina leposavic": "Q2048354", "opstina orahovac": "Q794039",
            "opstina klina": "Q860157"}


class Places:
    def __init__(self):
        # 2026-10-30: only true municipality rows (wikidata/Q2989682 seed + the 6 original town-keyed rows), never the
        # ~1,161 Serbian cadastral-village XK rows that are also labelled admin_level=municipality.
        cand = {r["qid"]: r for r in csv.DictReader(CAND.open(encoding="utf-8")) if r["country_code"] == "XK"
                and r["admin_level"] == "municipality" and (r.get("seed_file") == XK_SEED or r["qid"] in XK_ALIAS.values())}
        self.by = {}
        for r in csv.DictReader(WD.open(encoding="utf-8")):
            q, seat = r["m"].rsplit("/", 1)[-1], (r["seat"] or "").rsplit("/", 1)[-1]
            if q in cand:
                c, how = cand[q], "wd_municipality"
            elif XK_ALIAS.get(q) in cand:
                c, how = cand[XK_ALIAS[q]], "wd_municipality->alias(town_qid)"
            else:
                c, how = cand.get(seat), "wd_municipality_seat(P36)"
            for lab in (r["sq"], r["en"]):
                if lab:
                    self.by[fold(lab)] = (q, c, how)
        qrow = {v[0]: v for v in self.by.values()}
        for lab, q in XK_NAMES.items():
            if q in qrow:
                self.by[lab] = qrow[q]

    def resolve(self, inst):
        k = fold(inst)
        k = re.sub(r"\s+(fusha|fush)\b.*$", "", k)
        # 2026-10-30: strip "komuna "/"opstina " too (old stem made "Komuna Kllokot/Ranillug/Partesh" hit "Komuna Istog")
        stem = lambda x: re.sub(r"^(komuna|opstina)( e)? ", "", x).replace(" municipality", "")[:6]
        hit = self.by.get(k) or next((v for kk, v in self.by.items() if re.match(r"(komuna|opstina) ", kk) and k
                                      and re.match(r"(komuna|opstina) ", k) and stem(kk) == stem(k)), None)
        if hit and hit[1]:
            c = hit[1]
            return dict(place_id=c["place_id"], qid=c["qid"], place_name=c["place_name"], match=hit[2], muni_qid=hit[0])
        return dict(place_id=None, qid=hit[0] if hit else None, place_name=inst, match="institution_not_in_candidate",
                    muni_qid=hit[0] if hit else None)


def post(sess, url, data):
    if not sess.robots.can_fetch(url):
        raise PermissionError(url)
    for a in range(5):
        time.sleep(sess.min_interval)
        try:
            r = sess.s.post(url, data=data, timeout=(20, 180))
            if r.status_code == 200:
                return r
        except Exception as e:  # noqa: BLE001
            log.warning("post err %s", e)
        time.sleep(10 * 2 ** a)
    raise RuntimeError("post failed " + url)


def catalog(sess):
    STATE.mkdir(parents=True, exist_ok=True)
    url = BASE + "LocalInstActsList.aspx"
    t = sess.get(url).text
    seen = set()
    if CAT.exists():
        seen = {json.loads(l)["id"] for l in CAT.open()}
    page = 1
    with CAT.open("a", encoding="utf-8") as f:
        while True:
            n = 0
            for aid, title in re.findall(r'href="ActDetail\.aspx\?ActID=(\d+)">([^<]+)</a>', t):
                if aid not in seen and title.strip():
                    seen.add(aid); n += 1
                    f.write(json.dumps({"id": aid, "title": clean(title)}, ensure_ascii=False) + "\n")
            f.flush()
            log.info("list page %d: +%d (total %d)", page, n, len(seen))
            m = re.search(r"__doPostBack\(&#39;([^&]+lbNext)&#39;", t)
            if not m:
                break
            d = hidden(t); d["__EVENTTARGET"] = m.group(1); d["__EVENTARGUMENT"] = ""
            t = post(sess, url, d).text
            page += 1
    (STATE / "catalog.state.json").write_text(json.dumps({"complete": True, "acts": len(seen), "pages": page}))


def detail(sess, aid):
    url = f"{BASE}ActDetail.aspx?ActID={aid}"
    t = sess.get(url).text
    plain = clean(re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", t))
    g = lambda a, b: (re.search(a + r"\s*(.*?)\s*(?:" + b + ")", plain) or [None, None])[1]
    meta = {"kind": g("Lloji i aktit:", "Numri i aktit:"), "number": g("Numri i aktit:", "Institucioni"),
            "inst": g("Institucioni", "Data e publikimit:"), "pub": g("Data e publikimit:", r"Baza ligjore|Zyra e Kryeministrit|$")}
    text = ""
    btn = re.search(r'name="(ctl00\$MainContent\$rAktet\$ctl00\$imgDownload)"', t)
    if btn:
        d = hidden(t); d[btn.group(1) + ".x"] = "10"; d[btn.group(1) + ".y"] = "10"
        r = post(sess, url, d)
        if r.content[:4] == b"%PDF" and len(r.content) < 80 * 1024 * 1024:
            with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
                tf.write(r.content); tf.flush()
                o = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", tf.name, "-"], capture_output=True, timeout=300)
                text = o.stdout.decode("utf-8", "replace").strip()
        del r
    return url, meta, text


def iso(d):
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", d or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


DT = [("rregullore", "regulation"), ("vendim", "decision"), ("statut", "statute"), ("udhëzim", "regulation")]


def build(a, url, meta, text, pl):
    k = (meta.get("kind") or a["title"]).lower()
    dt = next((v for w, v in DT if w in k), "gazette_act")
    ok = len(re.sub(r"\s", "", text)) >= 200
    title = re.sub(r"\s+\"?\s*type=.*$", "", a["title"])
    return {"place_id": pl["place_id"], "country_code": "XK", "doc_id": f"xk_gzk:{a['id']}", "source_platform": "xk_gzk",
            "source_url": url, "doc_type": dt, "language": "sq", "title_native": title, "number": meta.get("number"),
            "published_date": iso(meta.get("pub")), "in_force": None, "consolidated": False, "content_format": "pdf_text",
            "text": text if ok else None, "content_complete": ok, "retrieved_at": utcnow(), "place_name": pl["place_name"],
            "qid": pl["qid"], "admin_level": "municipality", "platform": "gzk.rks-gov.net", "platform_place_id": a["id"],
            "issuing_body_name": meta.get("inst"), "place_match": pl["match"], "muni_qid": pl.get("muni_qid"),
            "act_kind": meta.get("kind"), "source_official": True,
            "rights": "official act published in the Official Gazette of Kosovo; official texts are not protected by copyright"}


def fetch(sess, test=None):
    done = Done(STATE / ("done_test.sqlite" if test else "done.sqlite"))
    pm = Places()
    stg = Stager("XK", "xkgzk", log, max_docs=100, stage=(STAGE / "_test_xk") if test else STAGE)
    lines = CAT.read_text(encoding="utf-8").splitlines()
    it = random.Random(5).sample(lines, min(test, len(lines))) if test else lines
    for ln in it:
        a = json.loads(ln)
        if done.has(a["id"]):
            continue
        try:
            url, meta, text = detail(sess, a["id"])
            stg.add(build(a, url, meta, text, pm.resolve(meta.get("inst") or "")), a["id"])
        except PermissionError as e:
            log.warning("robots skip %s %s", a["id"], e); stg.add(None, a["id"], "robots_disallowed")
        except Exception as e:  # noqa: BLE001
            log.warning("FAIL %s: %s", a["id"], str(e)[:200])
            with (STATE / "failed.jsonl").open("a") as ff:
                ff.write(json.dumps({"id": a["id"], "error": str(e)[:300], "at": utcnow()}) + "\n")
        if stg.due():
            log.info("flush %s | done %d", dict(stg.flush(done)), done.count()); gc.collect()
    if stg.keys:
        log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
    log.info("fetch finished: %s", dict(stg.total))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["catalog", "fetch", "all", "status"])
    ap.add_argument("--test", type=int)
    a = ap.parse_args()
    st = STATE / "catalog.state.json"
    if a.cmd == "status":
        print(st.read_text() if st.exists() else "{}", "catalog", sum(1 for _ in CAT.open()) if CAT.exists() else 0,
              "done", Done(STATE / "done.sqlite").count()); return
    sess = PoliteSession(log, min_interval=1.5)
    if a.cmd == "catalog" or (a.cmd == "all" and not st.exists()):
        catalog(sess)
    if a.cmd in ("fetch", "all"):
        fetch(sess, a.test)


if __name__ == "__main__":
    main()
