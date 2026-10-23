#!/usr/bin/env python3
"""Re-fetch PL acts whose ELI text.pdf answers HTTP 406 (pre-2012 acts published per journal issue).

Root cause (2026-10-17): for these acts the e-Dziennik ELI API has no per-act PDF (`/api/eli/acts/<eli>/text.pdf` -> 406,
`text.html` -> 302 to 404_notfound). pl_run caught the 406, fell back to HTML, got nothing and logged
"no text (scanned PDF without text layer?)". The sites' own viewer serves the act through
  https://<host>/GetActPdf.ashx?year=<year>&book=<volume = journal issue Nr>&position=<pos>
which returns the whole issue PDF (usually with a text layer) or, for some, the act alone.
This job fetches each issue once, splits it at the position headers, and stages one record per act
(source tag `pldziss`). Issues without a text layer are real scans -> stay in the OCR queue with the corrected URL.
Polite: pl_dzienniki.Host (robots RFC 9309, >=1 s/host, backoff, 403 breaker), sequential, resumable (done sqlite).
Input: _state/pl/issue_refetch_queue.jsonl ; results: _state/pl/issue_refetch_results.jsonl
Usage: python3 tools/pl_issue_refetch.py [--test N_ISSUES]
"""
import argparse, gc, json, re, subprocess, sys, tempfile
from collections import defaultdict
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import pl_dzienniki as P  # noqa
from common.live import STAGE, Done, Stager, get_logger, utcnow  # noqa
ST = STAGE / "_state" / "pl"
QF = ST / "issue_refetch_queue.jsonl"
RES = ST / "issue_refetch_results.jsonl"
log = get_logger("pl_issue_refetch")
MAXB = 80 * 1024 * 1024
HEAD = re.compile(r"(?m)^[ \t]*(?:Poz\.\s*)?(\d{1,5})[ \t]*$")


def issue_url(host, y, v, pos):
    return f"https://{host}/GetActPdf.ashx?year={y}&book={v}&position={pos}"


def get_pdf(h, url):
    r = h.get(url, stream=True)
    with tempfile.NamedTemporaryFile(suffix=".pdf", dir="/tmp", delete=False) as tf:
        n = 0
        for ch in r.iter_content(65536):
            tf.write(ch); n += len(ch)
            if n > MAXB:
                break
        r.close()
    return tf.name, n


def text_of(path):
    p = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", path, "-"], capture_output=True, timeout=600)
    return p.stdout.decode("utf-8", "replace")


def pages(path):
    m = re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", path], capture_output=True, text=True).stdout or "")
    return int(m.group(1)) if m else 0


def split(text, poss, allpos):
    """segment per position: from its standalone header line to the next header of a known position in the issue."""
    heads = [(m.start(), int(m.group(1))) for m in HEAD.finditer(text) if int(m.group(1)) in allpos]
    # skip the table of contents: keep the LAST run in increasing order (body), i.e. the first header followed by act text
    out = {}
    for i, (at, p) in enumerate(heads):
        nxt = next((a for a, q in heads[i + 1:] if q != p), len(text))
        seg = text[at:nxt]
        body = re.sub(r"^\s*\d+\s*", "", seg)
        if re.match(r"\s*(UCHWAŁ|ZARZĄDZ|POROZUM|OBWIESZCZ|ROZPORZ|DECYZJ|POSTANOW|INFORMACJ|SPRAWOZD|ANEKS|OGŁOSZ|ROZSTRZYG|STATUT|REGULAMIN|U C H|Z A R|P O R|O B W|R O Z|S P R|ZESTAW|WYROK|UMOW|KOMUNIKAT|BILANS|ZMIAN|PLAN|PROGRAM|ORZECZ|OBJAŚ|\w)", body):
            if len(body.strip()) > len(out.get(p, "")):
                out[p] = body.strip()
    return {p: out[p] for p in poss if p in out}


STOPW = {"w", "i", "z", "na", "do", "oraz", "się", "sprawie", "dnia", "art", "nie", "od", "lub", "przez", "jest", "ust",
         "gminy", "rady"}


def quality(t):
    """share of very common Polish function words among word tokens (normal text ~0.2; garbled text layer < 0.08)."""
    w = re.findall(r"[^\W\d_]+", t.lower())
    return round(sum(x in STOPW for x in w) / max(len(w), 1), 3)


MOJI = str.maketrans({"³": "ł", "¹": "ą", "¿": "ż", "œ": "ś", "æ": "ć", "ê": "ę", "ñ": "ń", "Ÿ": "ź", "£": "Ł", "¥": "Ą",
                      "Œ": "Ś", "Æ": "Ć", "Ê": "Ę", "Ñ": "Ń", "¯": "Ż", "\x8f": "Ź"})


def demoji(t):
    """old CE fonts: Polish letters come out as Latin-1 look-alikes (Bia³ej). Fix only when that is clearly the case."""
    bad = sum(t.count(c) for c in "³¹¿œæê")
    good = sum(t.count(c) for c in "łążśćę")
    return t.translate(MOJI) if bad > 20 and bad > 3 * good else t


KIND = r"(?:U\s?C\s?H\s?W\s?A\s?[ŁL]\s?[AY]|ZARZĄDZENIE|POROZUMIENIE|OBWIESZCZENIE|ROZPORZĄDZENIE|DECYZJA|POSTANOWIENIE|ANEKS|INFORMACJA|SPRAWOZDANIE|UMOWA)"
NEXT = re.compile(r"\n[ \t]*" + KIND + r"\s+(?:NR|Nr|nr)\b")


def split_by_number(text, it):
    """fallback: find '<KIND> NR <act number from the title>' in the body (not the TOC) and cut at the next act header."""
    m = re.search(r"\bnr\.?\s+(\S+)", it.get("title") or "", re.I)
    if not m:
        return None
    num = m.group(1).rstrip(",.")
    pat = re.compile(KIND + r"\s+(?:NR|Nr|nr)\.?\s*" + r"\s*".join(re.escape(ch) for ch in num), re.I)
    best = None
    for mm in pat.finditer(text):
        nx = NEXT.search(text, mm.end() + 50)
        seg = text[mm.start(): nx.start() if nx else len(text)].strip()
        if len(seg) > 300 and (best is None or len(seg) > len(best)):
            best = seg
    return best


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--test", type=int)
    ap.add_argument("--retry-why", default="", help="comma list of done reasons to retry, e.g. split_failed")
    a = ap.parse_args()
    dbp = ST / ("issue_refetch_done_test.sqlite" if a.test else "issue_refetch_done.sqlite")
    if a.retry_why:
        import sqlite3
        con = sqlite3.connect(dbp)
        n = con.execute("delete from done where why in (%s)" % ",".join("?" * len(a.retry_why.split(","))),
                        a.retry_why.split(",")).rowcount
        con.commit(); con.close()
        log.info("retrying %d acts with done reason in %s", n, a.retry_why)
    done = Done(dbp)
    pm = P.PlaceMap()
    stg = Stager("PL", "pldziss", log, max_docs=200, stage=(STAGE / "_test_pl") if a.test else STAGE).graceful(done)
    items = [json.loads(l) for l in QF.open(encoding="utf-8")]
    groups = defaultdict(list)
    for it in items:
        groups[(it["voivodeship"], it["year"], it["volume"])].append(it)
    allpos = defaultdict(set)   # every position of each issue (from catalogs), for segment boundaries
    need = set(groups)
    for w in sorted({k[0] for k in need}):
        for l in (ST / f"catalog_{w}.jsonl").open(encoding="utf-8"):
            if '"volume"' in l:
                m = json.loads(l)
                k = (w, m.get("year"), m.get("volume"))
                if k in need:
                    allpos[k].add(int(m["pos"]))
    hosts, ng = {}, 0
    for k, its in sorted(groups.items()):
        todo = [it for it in its if not done.has(it["eli"])]
        if not todo:
            continue
        if a.test and ng >= a.test:
            break
        ng += 1
        w, y, v = k
        h = hosts.setdefault(w, P.Host(w))
        url = issue_url(h.host, y, v, todo[0]["pos"])
        res = {"woj": w, "year": y, "volume": v, "issue_url": url, "acts": [it["eli"] for it in todo], "at": utcnow()}
        path = None
        try:
            path, nbytes = get_pdf(h, url)
            np_ = pages(path)
            t = demoji(text_of(path))
            res.update(bytes=nbytes, pages=np_, chars=len(t.strip()))
            if len(re.sub(r"\s+", "", t)) < 150 * max(np_, 1):        # < 150 chars/page -> scanned issue
                res["outcome"] = "scanned_issue"
                for it in todo:
                    stg.add(None, it["eli"], "scanned_issue")
            else:
                pg = t.split("\f")
                low = sum(len(re.sub(r"\s+", "", x)) < 300 for x in pg) / max(len(pg), 1)
                res["low_text_page_share"] = round(low, 2)
                segs = split(t, [it["pos"] for it in todo], allpos[k] | {it["pos"] for it in todo})
                if not segs and len(todo) == 1 and np_ <= 8:            # per-act PDF
                    segs = {todo[0]["pos"]: t.strip()}
                res["split_ok"], res["split_missing"] = sorted(segs), sorted(set(it["pos"] for it in todo) - set(segs))
                res["outcome"] = "text_issue"
                for it in todo:
                    s = segs.get(it["pos"]) or split_by_number(t, it)
                    if not s or len(s) < 200:
                        # text only in the TOC / running headers, act pages are images -> a real scan
                        stg.add(None, it["eli"], "scanned_act_pages" if low > 0.5 else "split_failed")
                        continue
                    tq = quality(s)
                    if tq < 0.08:
                        stg.add(None, it["eli"], "garbled_text_layer")
                        continue
                    org, lvl = it.get("_org"), it.get("_lvl")
                    pl = pm.resolve_ext(w, org, lvl, it.get("title") or "", s)
                    pl = dict(pl, iso_3166_2=pl.get("iso_3166_2") or P.HOSTS[w][2])
                    row = P.build(h, it, org, lvl, pl, s, "pdf", {"pdf_issue_url": url, "pdf_issue_pages": np_,
                                                                   "text_scope": "act segment split from the journal issue PDF",
                                                                   "text_quality": tq})
                    row["pdf_url"] = url
                    stg.add(row, it["eli"])
        except P.HostParked as e:
            res["outcome"] = f"host_parked: {e}"
        except Exception as e:  # noqa: BLE001
            res["outcome"] = f"error: {str(e)[:200]}"
            if "404" in str(e):
                for it in todo:
                    stg.add(None, it["eli"], "issue_pdf_404")
        finally:
            if path:
                Path(path).unlink(missing_ok=True)
        with RES.open("a", encoding="utf-8") as f:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")
        log.info("%s %s/%s: %s %s", w, y, v, res.get("outcome"), {kk: res.get(kk) for kk in ("pages", "chars")})
        if stg.due():
            log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
            gc.collect()
    if stg.keys:
        log.info("flush %s | done %d", dict(stg.flush(done)), done.count())
    log.info("finished: %s", dict(stg.total))


if __name__ == "__main__":
    main()
