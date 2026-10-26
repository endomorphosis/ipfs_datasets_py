"""Indonesia municipal-law pilot — JDIH federation template harvest.

Bounded pilot: 4 kabupaten/kota x up to 5 recent Peraturan Daerah (Perda).
LOCAL ONLY — no uploads. Sources: per-region JDIH portals (the JDIHN
federation). National aggregators checked 2026-10-12 and unusable from
this egress: peraturan.go.id + jdihn.go.id (proxy/TLS failure),
peraturan.bpk.go.id (robots OK but app returns 403 / timeouts).

Template family (4 variants mapped in recon):
  A "jdihn"    jdih.bandung.go.id      /home/produk-hukum/peraturan-.../<id>
                                       metadata table + /media/<id>?download=true
  B "surabaya" jdih.surabaya.go.id     /peraturan/<id>, PDF /peraturan/download/<id>
  C "semarang" jdih.semarangkota.go.id /dokumen?tipe_dokumen=1, PDFs in
                                       /assets/public/data_dokumen/
  D "malang"   jdih.malangkab.go.id    /prokum?kategori=Peraturan Daerah,
                                       detail /prokum/peraturan-daerah-<no>-<year>
Robots (2026-10-12): all four hosts allow crawling (Disallow empty or
admin-only). Denpasar is Disallow:/ for * and Sleman/Banyuwangi/Gianyar
are bot-walled — excluded, see pilot report.

Normalization: world_municipal 19-column schema. Jurisdiction IDs are
Kemendagri/BPS 4-digit wilayah codes. NOTE: world_municipal/jurisdiction.py
has NO ID scheme registered (SCHEMES = NL/PT/ES/PL/KR/BR/EU/US) — this
script mirrors the closest registered pattern (DicofreScheme: digit
string, zero-padded) at width 4 locally and flags the gap in the pilot
report. The repo file is NOT modified.
"""
import html as htmlmod
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from bs4 import BeautifulSoup

REPO = Path.home() / "workspace" / "ipfs_datasets_py"
sys.path.insert(0, str(REPO / "ipfs_datasets_py" / "processors" / "legal_scrapers"))
from world_municipal.normalize import make_row, finalize_rows  # noqa: E402
from world_municipal.schema import rows_to_table, validate_table, validation_report  # noqa: E402
from world_municipal.parquet_io import write_html_parquet, write_validation_report  # noqa: E402

OUT = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files" / "id_pilot"
OUT.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
DELAY = 2.0           # no crawl-delay published by these hosts; stay polite
SAMPLE = 5
MAX_CANDIDATES = 9    # per unit: try up to this many docs to fill SAMPLE
MAX_PDF_BYTES = 45 * 1024 * 1024
RETRIEVED = "2026-10-12"

UNITS = [
    dict(name="Kota Bandung",     bps="3273", host="jdih.bandung.go.id",      template="jdihn"),
    dict(name="Kota Surabaya",    bps="3578", host="jdih.surabaya.go.id",     template="surabaya"),
    dict(name="Kota Semarang",    bps="3374", host="jdih.semarangkota.go.id", template="semarang"),
    dict(name="Kabupaten Malang", bps="3507", host="jdih.malangkab.go.id",    template="malang"),
]

MONTHS = {"januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5,
          "juni": 6, "juli": 7, "agustus": 8, "september": 9, "oktober": 10,
          "november": 11, "desember": 12}


def bps_normalize(code: str) -> str:
    """Closest registered pattern (DICOFRE digit zfill), BPS/Kemendagri width 4."""
    s = str(code).strip()
    if not s.isdigit():
        raise ValueError(f"not a BPS wilayah code: {code!r}")
    return s.zfill(4)


def parse_id_date(s: str) -> str:
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s or "")
    if not m:
        return ""
    mo = MONTHS.get(m.group(2).lower(), 0)
    return f"{m.group(3)}-{mo:02d}-{int(m.group(1)):02d}" if mo else ""


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


class PoliteSession:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.last_start = 0.0
        self.n_requests = 0
        self.fetch_seconds = 0.0

    def get(self, url, timeout=90, **kw):
        wait = DELAY - (time.monotonic() - self.last_start)
        if self.last_start and wait > 0:
            time.sleep(wait)
        last_exc = None
        for attempt in range(2):
            self.last_start = time.monotonic()
            t0 = time.monotonic()
            try:
                r = self.s.get(url, timeout=timeout, **kw)
                self.fetch_seconds += time.monotonic() - t0
                self.n_requests += 1
                return r
            except Exception as exc:  # slow pemda servers: one retry
                self.fetch_seconds += time.monotonic() - t0
                self.n_requests += 1
                last_exc = exc
                time.sleep(3)
        raise last_exc


# ---------------------------------------------------------------- PDF text

def pdf_text(sess: PoliteSession, url: str):
    """(text, n_bytes, err) via PyMuPDF; streamed with a hard size cap."""
    import fitz
    r = sess.get(url, timeout=180, stream=True)
    r.raise_for_status()
    chunks, total = [], 0
    for chunk in r.iter_content(1 << 16):
        total += len(chunk)
        if total > MAX_PDF_BYTES:
            return "", total, f"pdf exceeds {MAX_PDF_BYTES} bytes cap"
        chunks.append(chunk)
    raw = b"".join(chunks)
    if raw[:4] != b"%PDF":
        return "", total, f"not a PDF (first bytes {raw[:20]!r})"
    doc = fitz.open(stream=raw, filetype="pdf")
    text = "\n".join(p.get_text() for p in doc)
    return text.strip(), total, ""


PASAL_RE = re.compile(r"(?m)^[ \t]*Pasal[ \t]+(\d{1,3}[A-Za-z]?)[ \t]*(?=\n|\()")
BAB_RE = re.compile(r"(?m)^[ \t]*BAB[ \t]+([IVXLC]+)[ \t]*\n[ \t]*([^\n]{3,90})")


def split_pasal(text: str):
    """Split Perda text into (suffix, node_label, bab_context, body) chunks."""
    penjelasan_at = None
    m = re.search(r"(?m)^[ \t]*PENJELASAN[ \t]*$", text)
    if m:
        penjelasan_at = m.start()
    babs = [(mm.start(), f"BAB {mm.group(1)} — {mm.group(2).strip()}")
            for mm in BAB_RE.finditer(text)]
    hits = list(PASAL_RE.finditer(text))
    chunks = []
    if not hits:
        return chunks
    pre = text[:hits[0].start()].strip()
    if len(pre) >= 300:
        chunks.append(("preambule", "Preambule", "", pre))
    for i, h in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        body = text[h.start():end].strip()
        if len(body) < 40:
            continue
        bab = ""
        for pos, label in babs:
            if pos < h.start():
                bab = label
            else:
                break
        sect = "penjelasan" if (penjelasan_at is not None and h.start() > penjelasan_at) else "batang-tubuh"
        chunks.append((f"pasal-{h.group(1).lower()}" + ("-penjelasan" if sect == "penjelasan" else ""),
                       f"Pasal {h.group(1)}", bab, body))
    return chunks


def text_to_html(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        paras = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "".join(f"<p>{htmlmod.escape(p)}</p>" for p in paras)


# ---------------------------------------------------------------- adapters
# Each returns (candidates, total_found_hint). A candidate:
# dict(detail_url, pdf_url|None, title, nomor, tahun, date_eff, size_hint_mb)

def enum_bandung(sess, base):
    cands, seen, total_hint = [], set(), None
    for page in range(1, 9):
        url = base + "/home/produk-hukum/peraturan-perundang-undangan-daerah"
        if page > 1:
            url += f"?page={page}"
        r = sess.get(url, timeout=120)
        r.raise_for_status()
        if total_hint is None:
            pages = [int(x) for x in re.findall(r"[?&]page=(\d+)", r.text)]
            if pages:
                total_hint = max(pages) * 15
        for href in re.findall(r'href="(https://[^"]*peraturan-perundang-undangan-daerah/\d+)"', r.text):
            if href not in seen:
                seen.add(href)
                cands.append(dict(detail_url=href))
        if len(cands) >= 60:
            break
    return cands, total_hint


def bandung_detail(sess, cand):
    r = sess.get(cand["detail_url"], timeout=120)
    r.raise_for_status()
    h = r.text

    def meta(label):
        m = re.search(rf"<th>{re.escape(label)}</th><th>:</th>\s*<td>(.*?)</td>", h, re.S)
        return re.sub(r"<[^>]+>|\s+", " ", m.group(1)).strip() if m else ""

    if meta("Jenis Dokumen") != "Peraturan Daerah":
        return None
    seg = h[h.find("Lampiran Dokumen"):]
    seg = seg[:seg.find("Perubahan Status")] if "Perubahan Status" in seg else seg
    best = None
    for tr in re.findall(r"<tr>(.*?)</tr>", seg, re.S):
        if "media-download" not in tr:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        mid = re.search(r"/media/(\d+)\?download=true", tr)
        if not mid or len(tds) < 4:
            continue
        tipe = re.sub(r"<[^>]+>", "", tds[1]).strip()
        name = re.sub(r"<[^>]+>", "", tds[2]).strip()
        size_m = re.search(r"([\d.]+)\s*MB", re.sub(r"<[^>]+>", "", tds[3]))
        size_mb = float(size_m.group(1)) if size_m else 0.0
        if tipe.lower().startswith("lampiran") and (best is None or size_mb > best[2]):
            best = (mid.group(1), name, size_mb)
    if not best:
        return None
    if best[2] and best[2] * 1024 * 1024 > MAX_PDF_BYTES:
        return dict(skip=f"lampiran {best[1]} declared {best[2]} MB over cap")
    return dict(
        detail_url=cand["detail_url"],
        pdf_url=f"{cand['detail_url'].split('/home/')[0]}/media/{best[0]}?download=true",
        title=meta("Judul Peraturan"),
        nomor=meta("Nomor"), tahun=meta("Tahun Terbit"),
        date_eff=parse_id_date(meta("Tanggal Pengundangan")),
        file_name=best[1],
    )


def enum_surabaya(sess, base):
    r = sess.get(base + "/", timeout=120)
    r.raise_for_status()
    cands, seen = [], set()
    for href, _pid, label in re.findall(r'href="(https://[^"]*/peraturan/(\d+))"[^>]*>([^<]*)</a>', r.text):
        if href in seen:
            continue
        m = re.search(r"PERDA\s+Nomor\s+(\d+)\s+Tahun\s+(\d{4})", label, re.I)
        if not m:
            continue
        seen.add(href)
        cands.append(dict(detail_url=href, nomor=m.group(1), tahun=m.group(2)))
    return cands, None


def surabaya_detail(sess, cand):
    r = sess.get(cand["detail_url"], timeout=120)
    r.raise_for_status()
    h = r.text
    t = re.search(r"<title>(.*?)</title>", h, re.S)
    title = re.sub(r"\s+", " ", t.group(1)).strip() if t else ""
    title = re.sub(r"\s+[-|]\s+JDIH\b.*$", "", title).strip()
    # Surabaya <title> quirk: "Peraturan Daerah Kota PERDA Nomor 5 ..." —
    # rebuild in the standard form used by the other templates.
    mm = re.match(r"(?i)peraturan daerah(?:\s+kota|\s+kabupaten)?\s+PERDA\s+"
                  r"Nomor\s+(\d+)\s+Tahun\s+(\d{4})\s+tentang\s+(.+)$", title)
    if mm:
        title = (f"Peraturan Daerah Nomor {mm.group(1)} Tahun {mm.group(2)} "
                 f"tentang {mm.group(3).strip()}")
    if "peraturan daerah" not in title.lower():
        # fall back to the meta description
        md = re.search(r'<meta name="description" content="([^"]+)"', h)
        if md and "peraturan daerah" in md.group(1).lower():
            title = md.group(1).strip()
        else:
            return None
    plain = BeautifulSoup(h, "html.parser").get_text(" ")
    m = re.search(r"[Tt]anggal [Pp]engundangan\s*:?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", plain)
    date_eff = parse_id_date(m.group(1)) if m else ""
    pid = cand["detail_url"].rstrip("/").split("/")[-1]
    return dict(detail_url=cand["detail_url"],
                pdf_url=f"{cand['detail_url'].split('/peraturan/')[0]}/peraturan/download/{pid}",
                title=title, nomor=cand.get("nomor", ""), tahun=cand.get("tahun", ""),
                date_eff=date_eff, file_name=f"peraturan-{pid}")


def clean_smg_title(t: str, tahun: str) -> str:
    """Strip card furniture the Semarang listing container drags into titles."""
    t = re.sub(r"\s+", " ", t or "").strip()
    for cut in (" Status ", " DOWNLOAD", " Download"):
        if cut in t:
            t = t[:t.index(cut)].strip()
    t = t.replace("Peraturan Daerah Abstrak Peraturan Daerah", "Peraturan Daerah")
    t = t.replace("Peraturan Daerah Peraturan Daerah", "Peraturan Daerah")
    if tahun and t.endswith(f" Tahun {tahun}") and t.count(f"Tahun {tahun}") > 1:
        t = t[: -len(f" Tahun {tahun}")].strip()
    return t


def enum_semarang(sess, base):
    cands = []
    for page in (1, 2):
        url = base + "/dokumen?tipe_dokumen=1" + (f"&page={page}" if page > 1 else "")
        r = sess.get(url, timeout=150)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"\.pdf$")):
            href = a["href"]
            fname = href.rsplit("/", 1)[-1]
            if "perda" not in fname.lower():
                continue
            title = ""
            node = a
            for _ in range(6):
                node = node.parent
                if node is None:
                    break
                txt = node.get_text(" ", strip=True)
                mm = re.search(r"(Peraturan Daerah[^\n]{0,160})", txt)
                if mm:
                    title = mm.group(1).strip()
                    break
            ym = re.search(r"(\d{4})perda", fname.lower())
            nm = re.search(r"__0*(\d+)\.pdf$", fname)
            tahun = ym.group(1) if ym else ""
            cands.append(dict(detail_url=url, pdf_url=href if href.startswith("http") else base + href,
                              title=clean_smg_title(title, tahun), tahun=tahun,
                              nomor=str(int(nm.group(1))) if nm else "",
                              file_name=fname))
        if len(cands) >= MAX_CANDIDATES:
            break
    return cands, None


def enum_malang(sess, base):
    r = sess.get(base + "/prokum?kategori=Peraturan%20Daerah", timeout=120)
    r.raise_for_status()
    found = {}
    for href in re.findall(r'href="(https?://[^"]*/prokum/peraturan-daerah-(\d+)-(\d{4}))"', r.text):
        found[href[0]] = (int(href[2]), int(href[1]))  # url -> (year, nomor)
    cands = [dict(detail_url=u, tahun=str(y), nomor=str(n))
             for u, (y, n) in sorted(found.items(), key=lambda kv: kv[1], reverse=True)]
    return cands, None


def malang_detail(sess, cand):
    r = sess.get(cand["detail_url"], timeout=120)
    r.raise_for_status()
    h = r.text
    pdfs = sorted(set(re.findall(r'href="([^"]*/dokumen/[^"]*/berkas/[^"]*)"', h)))
    pdfs += sorted(set(re.findall(r'href="([^"]*\.pdf[^"]*)"', h)))
    pdfs += sorted(set(re.findall(r'href="([^"]*(?:download|unduh)[^"]*)"', h, re.I)))
    if not pdfs:
        return None
    pdf = pdfs[0]
    if not pdf.startswith("http"):
        pdf = cand["detail_url"].split("/prokum/")[0] + pdf
    t = re.search(r"<title>(.*?)</title>", h, re.S)
    title = re.sub(r"<[^>]+>|\s+", " ", t.group(1)).strip() if t else ""
    title = re.sub(r"\s+-\s+JDIH\b.*$", "", title).strip()
    plain = BeautifulSoup(h, "html.parser").get_text(" ")
    m = re.search(r"[Dd]iundangkan[^.]{0,40}?(\d{1,2}\s+[A-Za-z]+\s+\d{4})", plain)
    return dict(detail_url=cand["detail_url"], pdf_url=pdf,
                title=title or f"Peraturan Daerah Kabupaten Malang Nomor {cand['nomor']} Tahun {cand['tahun']}",
                nomor=cand["nomor"], tahun=cand["tahun"],
                date_eff=parse_id_date(m.group(1)) if m else "",
                file_name=pdf.rsplit("/", 1)[-1])


DETAIL_RESOLVERS = {"jdihn": bandung_detail, "surabaya": surabaya_detail, "malang": malang_detail}
ENUMERATORS = {"jdihn": enum_bandung, "surabaya": enum_surabaya,
               "semarang": enum_semarang, "malang": enum_malang}


# ---------------------------------------------------------------- harvest

def harvest(unit: dict) -> dict:
    host, base = unit["host"], f'https://{unit["host"]}'
    bps = bps_normalize(unit["bps"])
    man = dict(unit, bps=bps, requests=0, fetch_seconds=0.0, wall_seconds=0.0,
               total_found=None, sampled=[], rows=0, errors=[])
    t_start = time.monotonic()
    sess = PoliteSession()
    try:
        cands, total_hint = ENUMERATORS[unit["template"]](sess, base)
        man["total_found"] = total_hint
        man["candidates_found"] = len(cands)
        rows = []
        tried = 0
        got = 0
        scan_budget = 45 if unit["template"] == "jdihn" else MAX_CANDIDATES + 4
        for cand in cands:
            if got >= SAMPLE or tried >= scan_budget:
                break
            tried += 1
            info = dict(title=cand.get("title", ""), nomor=cand.get("nomor", ""),
                        tahun=cand.get("tahun", ""), rows=0, mode="",
                        detail_url=cand.get("detail_url", ""), pdf_url=cand.get("pdf_url", ""))
            try:
                doc = cand
                resolver = DETAIL_RESOLVERS.get(unit["template"])
                if resolver:
                    doc = resolver(sess, cand)
                    if doc is None:
                        continue  # not a Perda / no lampiran — not an error
                    if "skip" in doc:
                        info["mode"] = f"skipped: {doc['skip']}"
                        man["sampled"].append(info)
                        continue
                    info.update({k: doc.get(k, info.get(k, "")) for k in
                                 ("title", "nomor", "tahun", "pdf_url", "detail_url")})
                text, nbytes, err = pdf_text(sess, doc["pdf_url"])
                info["pdf_bytes"] = nbytes
                if err or not text:
                    info["mode"] = f"pdf failed: {err or 'empty text (scanned?)'}"
                    man["sampled"].append(info)
                    continue
                chunks = split_pasal(text)
                if not chunks:
                    info["mode"] = "no Pasal structure parsed"
                    man["sampled"].append(info)
                    continue
                info["mode"] = "pdf-pasal"
                title = doc.get("title") or info["title"] or \
                    f"Peraturan Daerah {unit['name']} Nomor {doc.get('nomor','')} Tahun {doc.get('tahun','')}"
                info["title"] = title
                base_id = f"id-{bps}-perda-{doc.get('tahun','')}-{slug(str(doc.get('nomor','')))}"
                regeling_key = doc.get("detail_url", "").rstrip("/").split("/")[-1]
                if unit["template"] == "semarang":
                    # all candidates share the listing URL; key on the PDF file
                    regeling_key = Path(doc.get("file_name", "")).stem or regeling_key
                regeling = f"jdih:{host}:{regeling_key}"
                for suffix, label, bab, body in chunks:
                    rows.append(make_row(
                        jurisdiction_id=bps,
                        jurisdiction_name=unit["name"],
                        country="ID",
                        doc_id=f"{base_id}-{suffix}",
                        regeling_id=regeling,
                        regeling_work_id=regeling,
                        title=title,
                        structural_path=f"{title} > {bab}" if bab else title,
                        node_label=label,
                        body_html=text_to_html(body),
                        source_url=doc["pdf_url"],
                        date_effective=doc.get("date_eff", ""),
                        retrieved=RETRIEVED,
                    ))
                    info["rows"] += 1
            except Exception as exc:
                info["mode"] = f"failed: {exc!r}"
            man["sampled"].append(info)
            if info["rows"] > 0:
                got += 1

        rows = finalize_rows(rows)
        table = rows_to_table(rows)
        errors = validate_table(table, jurisdiction_id=bps,
                                jurisdiction_name=unit["name"], country="ID")
        man["validation_errors"] = errors
        report = validation_report(table, jurisdiction_id=bps,
                                   jurisdiction_name=unit["name"], country="ID")
        write_validation_report(OUT / f"{bps}_validation.json", report)
        if errors:
            man["errors"].append(f"validation FAILED: {errors}")
        elif table.num_rows:
            man["rows"] = write_html_parquet(OUT / f"{bps}_html.parquet", table)
    except Exception as exc:
        man["errors"].append(f"harvest failed: {exc!r}")
    finally:
        man["requests"] = sess.n_requests
        man["fetch_seconds"] = round(sess.fetch_seconds, 1)
        man["wall_seconds"] = round(time.monotonic() - t_start, 1)
    return man


def main():
    results = {}
    with ThreadPoolExecutor(max_workers=len(UNITS)) as ex:
        for unit, man in zip(UNITS, ex.map(harvest, UNITS)):
            results[unit["name"]] = man
            print(json.dumps({k: man[k] for k in
                              ("name", "total_found", "candidates_found", "rows",
                               "requests", "fetch_seconds", "wall_seconds", "errors") if k in man},
                             ensure_ascii=False), flush=True)
    (OUT / "run_manifest.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("manifest ->", OUT / "run_manifest.json", flush=True)


if __name__ == "__main__":
    main()
