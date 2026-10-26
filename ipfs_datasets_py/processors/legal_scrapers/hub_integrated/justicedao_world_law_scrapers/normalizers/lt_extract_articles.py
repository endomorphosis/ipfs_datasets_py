#!/usr/bin/env python3
"""Lithuania (LT): ARTICLE_EXTRACT collector from e-seimas.lrs.lt.

Source: e-seimas.lrs.lt REST text endpoints (HTML export of the official ODT/DOCX):
  consolidated:  /portal/legalAct/lt/TAD/<docId>/asr -> /rs/actualedition/<docId>/<editionId>/
  original:      /rs/legalact/TAD/<docId>/
e-tar.lt / data.e-tar.lt are Cloudflare-blocked (403) and are NOT used.
e-tar hex doc IDs are NOT shared with e-seimas (verified: e-seimas returns
'Nurodytas teisėkūros objektas nerastas' / 404), so e-tar-only rows are probed
once on e-seimas and otherwise recorded as 'unmapped'.

Never thins: laws.parquet is copied unchanged (if missing) and never rewritten.
Only articles are appended (articles.jsonl) and articles.parquet is rebuilt by
streaming from jsonl. Does NOT publish to the Hub. Does NOT start IR/encode.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import html as htmlmod
import json
import logging
import os
import re
import shutil
import signal
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import requests

HUB_LAWS = Path(
    "/workspace/country-laws-ir/cache/hf/datasets--endomorphosis--ipfs_lithuania_laws/"
    "snapshots/15ca57dbb583dc263d13efa608f23b1b2184910a/data/laws.parquet"
)
ROOT = _CORPORA / "lt"
REL = Path("{_CORPORA}-releases/lithuania")
LAWS_PQ = REL / "data" / "laws.parquet"
ARTS_PQ = REL / "data" / "articles.parquet"
WORK = ROOT / "extract"
ARTS_JSONL = WORK / "articles.jsonl"
DONE_PATH = WORK / "done_law_ids.txt"
STATUS_JSONL = WORK / "law_status.jsonl"
STATE_PATH = WORK / "state.json"
PID_PATH = WORK / "lt_extract_articles.pid"

BASE = "https://e-seimas.lrs.lt"
UA = "CountryLawScraper/lt-extract (+https://huggingface.co/endomorphosis)"
FLOOR_LAWS = 7492
FETCH_SLEEP = float(os.environ.get("LT_FETCH_SLEEP", "0.4"))
CHECKPOINT_EVERY = 25
MAX_ARTS_PER_LAW = 3000
MEM_STOP_KB = int(3.5 * 1024 * 1024)  # 3.5 GiB
LIMIT = int(os.environ.get("LT_LIMIT", "0"))  # 0 = all
COLS = ["law_id", "id", "title", "text", "source_url", "document_number",
        "article_number", "record_type", "metadata_json"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("lt_extract")
STOP = False


def _sig(_s, _f):
    global STOP
    STOP = True
    log.info("signal received; stopping after current law")


signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)


def mem_available_kb() -> int:
    with open("/proc/meminfo") as f:
        for ln in f:
            if ln.startswith("MemAvailable:"):
                return int(ln.split()[1])
    return 0


def rss_kb() -> int:
    with open("/proc/self/status") as f:
        for ln in f:
            if ln.startswith("VmRSS:"):
                return int(ln.split()[1])
    return 0


# ---------------------------------------------------------------- fetching
def get(session: requests.Session, url: str) -> requests.Response | None:
    backoff = 3.0
    for attempt in range(5):
        try:
            r = session.get(url, timeout=(20, 90))
        except Exception as exc:  # network
            log.info("fetch err %s %s", url, exc)
            time.sleep(backoff); backoff = min(backoff * 2, 60)
            continue
        if r.status_code in (429, 502, 503, 504) or r.status_code >= 500:
            log.info("HTTP %s %s attempt=%s", r.status_code, url, attempt + 1)
            time.sleep(backoff); backoff = min(backoff * 2, 90)
            continue
        return r
    return None


def doc_id_for(row: dict) -> tuple[str, str]:
    """Return (docId, kind) where kind in {tais, hex, tar, none}."""
    url = str(row.get("source_url") or "")
    m = re.search(r"/TAD/(TAIS\.\d+)", url)
    if m:
        return m.group(1), "tais"
    ident = str(row.get("identifier") or "")
    lid = str(row.get("id") or "")
    m = re.search(r"legalAct/([0-9a-f]{32})", url) or re.match(r"^([0-9a-f]{32})$", ident)
    if m:
        return m.group(1), "hex"
    m = re.search(r"(TAR\.[0-9A-F]+)", url + " " + ident)
    if m:
        return m.group(1), "tar"
    m = re.match(r"^lt-tais\.(\d+)$", lid)
    if m:
        return f"TAIS.{m.group(1)}", "tais"
    return "", "none"


def fetch_text(session: requests.Session, doc_id: str) -> tuple[str, str, str, int]:
    """Returns (html, used_url, edition_kind, http_status_of_last)."""
    # 1) consolidated edition via /asr portal page
    asr = f"{BASE}/portal/legalAct/lt/TAD/{doc_id}/asr"
    r = get(session, asr)
    time.sleep(FETCH_SLEEP)
    if r is None:
        return "", asr, "fetch_fail", -1
    if r.status_code == 200 and "teisėkūros objektas nerastas" in r.text:
        return "", asr, "not_found", 404
    ed = None
    if r.status_code == 200:
        m = re.search(r"/rs/actualedition/" + re.escape(doc_id) + r"/([A-Za-z0-9]+)/", r.text)
        if m:
            ed = m.group(1)
    urls = []
    if ed:
        urls.append((f"{BASE}/rs/actualedition/{doc_id}/{ed}/", "consolidated"))
    urls.append((f"{BASE}/rs/legalact/TAD/{doc_id}/", "original"))
    last = r.status_code
    for u, kind in urls:
        rr = get(session, u)
        time.sleep(FETCH_SLEEP)
        if rr is None:
            last = -1
            continue
        last = rr.status_code
        if rr.status_code == 200 and len(rr.content) > 200:
            rr.encoding = rr.encoding or "utf-8"
            if "charset" not in (rr.headers.get("content-type") or ""):
                rr.encoding = "utf-8"
            return rr.text, u, kind, 200
    if last == 404:
        return "", urls[-1][0], "not_found", 404
    return "", urls[-1][0], "fetch_fail", last


# ---------------------------------------------------------------- parsing
NOTE_HDR = re.compile(
    r"^(Straipsnio|Straipsnių|Punkto|Punktų|Papunkčio|Papunkčių|Skyriaus|Skirsnio|Dalies|Priedo|Pastraipos|"
    r"Preambulės|Įstatymo|Pavadinimo|Papildyta|Pakeista)[^:]{0,60}"
    r"(pakeitimai|pakeitimas|naikinimas|papildymas|papildymai|pripažinimas negaliojančiu)\s*:$", re.I)
NOTE_REF = re.compile(r"^Nr\.\s*[^,]{1,40},\s*\d{4}-\d{2}-\d{2},\s*(paskelbta TAR|Žin|TAR)")
ART_RE = re.compile(r"^(\d+(?:\.\d+)*(?:\^\d+)?)\s*straipsnis\.?\s*(.*)$")
CH_RE = re.compile(
    r"^((?:[IVXLCDM]+|\d+|[A-ZĄČĘĖĮŠŲŪŽ]+(?:ASIS|OJI|IS|TASIS|SIS)?)\s+(?:SKYRIUS|SKIRSNIS|DALIS|KNYGA|"
    r"skyrius|skirsnis|dalis|knyga))\b(.*)$")
PT_RE = re.compile(r"^(\d{1,4})\.\s+(\S.*)$")


def html_to_lines(h: str) -> list[str]:
    h = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", h)
    h = re.sub(r"(?is)<sup[^>]*>\s*([0-9]+)\s*</sup>", r"^\1", h)
    h = re.sub(r"(?i)<br[^>]*>|</p>|</h\d>|</div>|</tr>|</li>|</td>", "\n", h)
    h = re.sub(r"<[^>]+>", "", h)
    t = htmlmod.unescape(h).replace("\xa0", " ").replace("\u00ad", "")
    out = []
    skip_refs = False
    for ln in t.split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip()
        if not ln or ln == "//":
            continue
        if NOTE_HDR.match(ln):
            skip_refs = True
            continue
        if skip_refs and NOTE_REF.match(ln):
            continue
        skip_refs = False
        # "3 ^1 straipsnis" -> "3^1 straipsnis"
        ln = re.sub(r"^(\d+)\s+\^(\d+)", r"\1^\2", ln)
        out.append(ln)
    return out


def split_units(lines: list[str]) -> tuple[list[dict], str]:
    """Split into straipsnis units; fallback to top-level punktai."""
    ctx: dict[str, str] = {}
    arts: list[dict] = []
    cur = None
    for ln in lines:
        m = ART_RE.match(ln)
        if m and len(m.group(2)) < 400:
            if cur:
                arts.append(cur)
            cur = {"num": m.group(1), "heading": m.group(2).strip(), "lines": [ln], "ctx": dict(ctx)}
            continue
        c = CH_RE.match(ln)
        if c and len(ln) < 250 and not ln.endswith("."):
            lvl = c.group(1).split()[-1].lower()
            ctx[lvl] = ln
            # a new higher-level heading resets lower levels
            if lvl in ("knyga", "dalis"):
                ctx.pop("skyrius", None); ctx.pop("skirsnis", None)
            if lvl == "skyrius":
                ctx.pop("skirsnis", None)
            if cur:
                arts.append(cur); cur = None
            continue
        if cur:
            cur["lines"].append(ln)
    if cur:
        arts.append(cur)
    arts = [a for a in arts if len(" ".join(a["lines"])) >= 30]
    if len(arts) >= 1:
        return arts[:MAX_ARTS_PER_LAW], "straipsnis"
    # fallback: numbered punktai (by-laws / orders), sequential guard
    pts: list[dict] = []
    cur = None
    prev = 0
    ctx = {}
    for ln in lines:
        c = CH_RE.match(ln)
        if c and len(ln) < 250 and not ln.endswith("."):
            ctx[c.group(1).split()[-1].lower()] = ln
            if cur:
                pts.append(cur); cur = None
            continue
        m = PT_RE.match(ln)
        if m:
            n = int(m.group(1))
            if n == prev + 1 or (n == 1 and prev > 1):
                if cur:
                    pts.append(cur)
                cur = {"num": m.group(1), "heading": "", "lines": [ln], "ctx": dict(ctx)}
                prev = n
                continue
        if cur:
            cur["lines"].append(ln)
    if cur:
        pts.append(cur)
    pts = [p for p in pts if len(" ".join(p["lines"])) >= 30]
    return pts[:MAX_ARTS_PER_LAW], "punktas" if pts else "none"


# ---------------------------------------------------------------- io
def load_done() -> set[str]:
    if not DONE_PATH.exists():
        return set()
    return {ln.strip() for ln in DONE_PATH.open(encoding="utf-8") if ln.strip()}


def append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def rebuild_articles_parquet() -> int:
    """Stream jsonl -> parquet in batches (dedupe by id via a set of ids only)."""
    schema = pa.schema([(c, pa.string()) for c in COLS])
    tmp = ARTS_PQ.with_suffix(".parquet.tmp")
    seen: set[str] = set()
    n = 0
    w = pq.ParquetWriter(tmp, schema, compression="zstd")
    batch: list[dict] = []
    if ARTS_JSONL.exists():
        with ARTS_JSONL.open(encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                rid = r.get("id")
                if not rid or rid in seen:
                    continue
                seen.add(rid)
                batch.append({c: ("" if r.get(c) is None else str(r.get(c))) for c in COLS})
                if len(batch) >= 2000:
                    w.write_table(pa.Table.from_pylist(batch, schema=schema)); n += len(batch); batch = []
    if batch:
        w.write_table(pa.Table.from_pylist(batch, schema=schema)); n += len(batch)
    w.close()
    prev = pq.ParquetFile(ARTS_PQ).metadata.num_rows if ARTS_PQ.exists() else 0
    if n < prev:
        log.warning("refuse arts thin %s -> %s", prev, n)
        tmp.unlink(missing_ok=True)
        return prev
    tmp.replace(ARTS_PQ)
    return n


def slug(s: str) -> str:
    return re.sub(r"[^0-9a-z^.]+", "-", s.lower()).strip("-") or "x"


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    (REL / "data").mkdir(parents=True, exist_ok=True)
    if not LAWS_PQ.exists():
        shutil.copy2(HUB_LAWS, LAWS_PQ)  # verbatim copy, never rewritten
    nl = pq.ParquetFile(LAWS_PQ).metadata.num_rows
    if nl < FLOOR_LAWS:
        log.error("laws %s < floor %s: refuse", nl, FLOOR_LAWS); sys.exit(2)
    ma = mem_available_kb()
    if ma <= MEM_STOP_KB:
        log.error("MemAvailable %s kB <= guard; refuse to start", ma); sys.exit(3)
    PID_PATH.write_text(f"{os.getpid()}\n")

    laws = pq.read_table(LAWS_PQ, columns=["id", "title", "source_url", "identifier", "source_type"]).to_pylist()
    # e-seimas-native rows first (reliable), then e-tar rows (probe only)
    laws.sort(key=lambda r: (0 if doc_id_for(r)[1] == "tais" else 1, r["id"]))
    done = load_done()
    st = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    c = {k: int(st.get(k, 0)) for k in ("processed", "with_arts", "articles", "empty", "fetch_fail",
                                          "unmapped", "straipsnis_laws", "punktas_laws", "consolidated")}
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "lt,en;q=0.5"})
    t0 = time.time(); run_n = 0
    log.info("start laws=%s done=%s mem_avail_kB=%s sleep=%s", nl, len(done), ma, FETCH_SLEEP)
    for row in laws:
        if STOP:
            break
        law_id = row["id"]
        if law_id in done:
            continue
        ma = mem_available_kb()
        if ma <= MEM_STOP_KB:
            log.error("MEM GUARD: MemAvailable %s kB <= 3.5G; stopping (do not restart)", ma)
            c["mem_guard_tripped"] = 1
            break
        doc_id, kind = doc_id_for(row)
        status = {"law_id": law_id, "doc_id": doc_id, "kind": kind}
        rows_out: list[dict] = []
        if not doc_id:
            status["status"] = "unmapped"; c["unmapped"] += 1
        else:
            h, used, ed_kind, code = fetch_text(session, doc_id)
            status.update({"url": used, "edition": ed_kind, "http": code})
            if ed_kind == "fetch_fail":
                status["status"] = "fetch_fail"; c["fetch_fail"] += 1
            elif ed_kind == "not_found":
                status["status"] = "unmapped" if kind != "tais" else "not_found"
                c["unmapped" if kind != "tais" else "fetch_fail"] += 1
            else:
                lines = html_to_lines(h)
                units, unit_kind = split_units(lines)
                src_page = f"{BASE}/portal/legalAct/lt/TAD/{doc_id}" + ("/asr" if ed_kind == "consolidated" else "")
                for i, u in enumerate(units):
                    num = u["num"]
                    label = f"{num} straipsnis" if unit_kind == "straipsnis" else f"{num} punktas"
                    title = f"{label}. {u['heading']}".strip().rstrip(".") if u["heading"] else label
                    rows_out.append({
                        "law_id": law_id,
                        "id": f"{law_id}-{'art' if unit_kind == 'straipsnis' else 'p'}-{slug(num)}-{i}"[:200],
                        "title": title[:500],
                        "text": "\n".join(u["lines"]),
                        "source_url": src_page,
                        "document_number": doc_id,
                        "article_number": num,
                        "record_type": "article",
                        "metadata_json": json.dumps({
                            "collector": "lt_extract_articles", "source": "e-seimas.lrs.lt",
                            "text_url": used, "edition": ed_kind, "unit": unit_kind,
                            "heading": u["heading"], "context": u["ctx"], "ordinal": i,
                        }, ensure_ascii=False),
                    })
                status.update({"status": "ok" if rows_out else "empty", "unit": unit_kind,
                               "n_arts": len(rows_out), "n_lines": len(lines)})
                if ed_kind == "consolidated":
                    c["consolidated"] += 1
                if rows_out:
                    c["with_arts"] += 1; c["articles"] += len(rows_out)
                    c["straipsnis_laws" if unit_kind == "straipsnis" else "punktas_laws"] += 1
                else:
                    c["empty"] += 1
        if rows_out:
            append_jsonl(ARTS_JSONL, rows_out)
        append_jsonl(STATUS_JSONL, [status])
        with DONE_PATH.open("a", encoding="utf-8") as f:
            f.write(law_id + "\n")
        c["processed"] += 1; run_n += 1
        log.info("law %s doc=%s status=%s ed=%s unit=%s arts=%s", law_id, doc_id, status.get("status"),
                 status.get("edition"), status.get("unit"), len(rows_out))
        if c["processed"] % CHECKPOINT_EVERY == 0:
            n = rebuild_articles_parquet()
            el = time.time() - t0
            state = dict(c, articles_parquet_rows=n, laws_rows=nl, run_processed=run_n,
                         run_elapsed_s=int(el), laws_per_min=round(run_n / el * 60, 2) if el else 0,
                         mem_avail_kB=mem_available_kb(), rss_kB=rss_kb(), updated=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            STATE_PATH.write_text(json.dumps(state, indent=2))
            log.info("checkpoint %s", json.dumps(state))
        if LIMIT and run_n >= LIMIT:
            break
    n = rebuild_articles_parquet()
    el = time.time() - t0
    state = dict(c, articles_parquet_rows=n, laws_rows=nl, run_processed=run_n, run_elapsed_s=int(el),
                 mem_avail_kB=mem_available_kb(), rss_kB=rss_kb(), stopped=bool(STOP),
                 done=(c["processed"] >= nl), updated=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    STATE_PATH.write_text(json.dumps(state, indent=2))
    log.info("END %s", json.dumps(state))
    try:
        PID_PATH.unlink()
    except Exception:
        pass


if __name__ == "__main__":
    main()
