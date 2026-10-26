"""Indonesia tranche-2 harvest driver.

Reuses tranche-1 machinery (id_campaign/harvest.py adapters + gates)
unchanged, adding:
  - a resilient pdf_text (Range-resume retries + %PDF offset tolerance)
    monkeypatched into the tranche-1 module — download robustness only;
    all validation/type gates are untouched;
  - a resolve_pdf dispatcher with three host-specific fixes:
      * inventarisasi family (Jepara et al.): prefer the encrypted-token
        /inventarisasi-hukum/download/<token> route over the placeholder
        'inggris_NO FILE.pdf' link the scorer used to pick;
      * Morowali (Nuxt): pull the lampiran file_path out of the embedded
        payload and try it as the PDF URL;
      * Jayapura (Yii): parse Nomor Peraturan / Tanggal Pengundangan from
        the detail page and prefer a non-lampiran file attachment;
  - two small enumerators for shapes the census may find: jdihn_list
    (/home/produk-hukum/... detail links) and prokum_list
    (/prokum/peraturan-daerah-<nomor>-<tahun> detail links);
  - enum_jayapura2: server-side jenis_peraturan=PERATURAN DAERAH filter
    on /dokumen/index, cards badged PERATURAN DAERAH only.

State: id_campaign_tranche2_state.json (per-BPS), resumable; staging is
the shared id_campaign/staging/ dir.
Phases: swing | generic | units:<bps,...>
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

WS = Path.home() / "workspace" / "goals" / "world-municipal-law-coverage" / "hidden_files"
CAMP = WS / "id_campaign"
sys.path.insert(0, str(CAMP))

import harvest as H  # noqa: E402  (tranche-1 module; sets up pilot + library)
from bs4 import BeautifulSoup  # noqa: E402

STATE2_PATH = CAMP / os.environ.get("ID_T2_STATE", "id_campaign_tranche2_state.json")
T1_STATE_PATH = CAMP / "id_campaign_tranche1_state.json"
CENSUS_PATH = CAMP / "generic_census_tranche2.json"
REGISTRY = WS / "id_jdih_registry_2026-10-12.json"
RETRIEVED = H.RETRIEVED

clean_ws, nomor_tahun, is_perda_title = H.clean_ws, H.nomor_tahun, H.is_perda_title
parse_id_date = H.parse_id_date

# ------------------------------------------------------- resilient pdf_text

def pdf_text_resilient(sess, url):
    """(text, n_bytes, err) — like pilot.pdf_text but resumes dropped
    transfers with Range requests and tolerates junk bytes before %PDF."""
    import fitz
    buf = bytearray()
    expected = None
    err = ""
    for attempt in range(6):
        headers = {"Accept-Encoding": "identity"}
        if buf:
            headers["Range"] = f"bytes={len(buf)}-"
        try:
            r = sess.get(url, timeout=180, stream=True, headers=headers)
            r.raise_for_status()
            if buf and r.status_code == 200:
                buf = bytearray()  # server ignored Range: start over
            cr = r.headers.get("Content-Range", "")
            m = re.search(r"/(\d+)\s*$", cr)
            if m:
                expected = int(m.group(1))
            elif r.headers.get("Content-Length"):
                cl = int(r.headers["Content-Length"])
                expected = cl if r.status_code == 200 else len(buf) + cl
            try:
                for chunk in r.iter_content(1 << 16):
                    if not chunk:
                        continue
                    buf.extend(chunk)
                    if len(buf) > H.MAX_PDF_BYTES:
                        return "", len(buf), f"pdf exceeds {H.MAX_PDF_BYTES} bytes cap"
            except Exception as exc:  # dropped mid-transfer -> resume
                err = f"{type(exc).__name__}: {exc}"
                time.sleep(2)
                continue
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            if attempt >= 2 and not buf:
                return "", 0, err
            time.sleep(2)
            continue
        if expected is None or len(buf) >= expected:
            break
        err = f"incomplete read {len(buf)}/{expected}"
        time.sleep(2)
    raw = bytes(buf)
    if expected is not None and len(raw) < expected:
        return "", len(raw), f"incomplete after retries ({err})"
    off = raw[:2048].find(b"%PDF")
    if off < 0:
        return "", len(raw), f"not a PDF (first bytes {raw[:20]!r})"
    try:
        doc = fitz.open(stream=raw[off:], filetype="pdf")
        text = "\n".join(p.get_text() for p in doc)
    except Exception as exc:
        return "", len(raw), f"fitz failed: {exc}"
    return text.strip(), len(raw), ""


H.pdf_text = pdf_text_resilient

# ------------------------------------------------------- resolve dispatcher

_orig_resolve_pdf = H.resolve_pdf


def _polish_from_detail(cand, soup):
    """Title/date/nomor improvements mirroring tranche-1 resolve_pdf."""
    plain = soup.get_text(" ")
    cur_title = cand.get("title", "")
    if not is_perda_title(cur_title) or cur_title == cur_title.lower():
        m = re.search(r"(Peraturan Daerah[^|•\n]{0,180})", plain)
        if m:
            cand["title"] = clean_ws(m.group(1))
    m = re.search(r"[Dd]iundangkan[^.]{0,40}?(\d{1,2}\s+[A-Za-z]+\s+\d{4})", plain)
    if m:
        cand["date_eff"] = parse_id_date(m.group(1))
    if not cand.get("nomor"):
        cand["nomor"], cand["tahun"] = nomor_tahun(cand.get("title", ""))
    return cand


def resolve_pdf2(sess, cand):
    if cand.get("unduh_url"):
        return _orig_resolve_pdf(sess, cand)
    detail = cand.get("detail_url", "")
    try:
        if "/inventarisasi-hukum/detail/" in detail:
            r = sess.get(detail, timeout=150)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            dl = [urljoin(detail, a["href"]) for a in soup.find_all("a", href=True)
                  if "/inventarisasi-hukum/download/" in a["href"]]
            if dl:
                cand["pdf_url"] = dl[0]
            if not dl:
                # some inventarisasi hosts (e.g. Rembang) attach the Perda
                # as a Google Drive share link on the detail page
                for a in soup.find_all("a", href=True):
                    gm = re.search(r"drive\.google\.com/file/d/([\w-]+)",
                                   a["href"])
                    if gm:
                        cand["pdf_url"] = ("https://drive.google.com/uc?"
                                           f"export=download&id={gm.group(1)}")
                        break
            if not cand.get("pdf_url"):
                found = H.find_pdf_in_detail(r.text, detail)
                # the bare /unduh nav page is an HTML index, not a file
                if found and not found.rstrip("/").endswith("/unduh"):
                    cand["pdf_url"] = found
            return _polish_from_detail(cand, soup)
        if "jdih.morowalikab.go.id" in detail:
            r = sess.get(detail, timeout=150)
            r.raise_for_status()
            m = re.search(r'"((?:\\u002F|/)JDIH_Dokumen(?:\\u002F|/)[^"]+?\.pdf)"',
                          r.text)
            if m:
                cand["pdf_url"] = urljoin(detail, m.group(1).replace("\\u002F", "/"))
                fname = cand["pdf_url"].rsplit("/", 1)[-1]
                cand["title"] = clean_ws(re.sub(
                    r"^\d+_", "", fname[:-4].replace("_", " ")).title())
                cand["nomor"], cand["tahun"] = nomor_tahun(cand["title"])
            return cand
        if "dokumen_view.php" in detail:
            # Way Kanan family (*.php JDIH app): the view page's sibling
            # dokumen_download.php is an HTML page embedding the real
            # file at /file/dokumen/<file>.pdf (abstracts live under
            # /file/abstrak/ and are not the act text).
            dl_page = detail.replace("dokumen_view.php", "dokumen_download.php")
            r = sess.get(dl_page, timeout=150)
            r.raise_for_status()
            m = re.search(r'(?:href|src)="(/?file/dokumen/[^"]+?\.pdf)"', r.text)
            if m:
                cand["pdf_url"] = urljoin(dl_page, m.group(1))
            return _polish_from_detail(cand, BeautifulSoup(r.text, "html.parser"))
        if "jdih.jayapurakab.go.id" in detail or cand.get("yii"):
            r = sess.get(detail, timeout=150)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            plain = soup.get_text(" ", strip=True)
            m = re.search(r"Nomor Peraturan\s+(\d+)", plain)
            if m:
                cand["nomor"] = m.group(1)
            m = re.search(r"Tanggal Pengundangan\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
                          plain)
            if m:
                cand["date_eff"] = parse_id_date(m.group(1))
            files = [urljoin(detail, a["href"]) for a in soup.find_all("a", href=True)
                     if "/dokumen/file/" in a["href"]]
            nonlamp = [f for f in files if "type=lampiran" not in f]
            if nonlamp:
                cand["pdf_url"] = nonlamp[0]
            elif files and not cand.get("pdf_url"):
                cand["pdf_url"] = files[0]
            return cand
    except Exception:
        # fall through to the stock resolver on any hiccup
        return _orig_resolve_pdf(sess, cand)
    return _orig_resolve_pdf(sess, cand)


H.resolve_pdf = resolve_pdf2

# ------------------------------------------------------- extra enumerators

def enum_jdihn_list(sess, base, unit):
    cands = H._detail_enum(
        sess, base + "/home/produk-hukum/peraturan-perundang-undangan-daerah",
        r"/peraturan-perundang-undangan-daerah/\d+")
    for c in cands.values():
        if not c.get("nomor"):
            c["nomor"], c["tahun"] = nomor_tahun(c.get("title", ""))
    return cands


def enum_prokum_list(sess, base, unit):
    cands = H._detail_enum(
        sess, base + "/prokum?kategori=Peraturan%20Daerah",
        r"/prokum/peraturan-daerah-\d+-\d{4}")
    for c in cands.values():
        m = re.search(r"peraturan-daerah-(\d+)-(\d{4})", c["detail_url"])
        if m:
            c["nomor"], c["tahun"] = m.group(1), m.group(2)
    return cands


def _jayapura_cards(html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for card in soup.select(".doc-card"):
        badge = card.select_one(".doc-badge-type")
        if not badge or "PERATURAN DAERAH" not in badge.get_text(" ", strip=True).upper():
            continue
        a = card.select_one(".doc-card__title a[href]")
        if not a:
            continue
        detail = urljoin(url, a["href"])
        pdf = ""
        for fa in card.find_all("a", href=True):
            if "/dokumen/file/" in fa["href"]:
                pdf = urljoin(url, fa["href"])
                break
        yr = re.search(r"Tahun\s+(\d{4})", card.get_text(" ", strip=True))
        out[detail] = dict(detail_url=detail, pdf_url=pdf,
                           title=clean_ws(a.get_text(" ", strip=True)),
                           nomor="", tahun=yr.group(1) if yr else "",
                           key=detail.rstrip("/").split("/")[-1], yii=True)
    return out


def enum_dokumen_view_perda(sess, base, unit):
    """Yii dokumen family with a dedicated Perda listing path
    (/dokumen/peraturan-daerah) — detail links /dokumen/view?id=N,
    PDFs resolved from detail pages (/common/dokumen/*.pdf)."""
    return H._detail_enum(sess, base + "/dokumen/peraturan-daerah",
                          r"/dokumen/view\?id=\d+")


def enum_slug_detail(sess, base, unit):
    """Dairi-family CMS: /peraturan listing, detail pages at
    /detail/peraturan/<type-slug>; Perda slugs start 'peraturan-daerah'."""
    cands = H._detail_enum(sess, base + "/peraturan",
                           r"/detail/peraturan/peraturan-daerah")
    for c in cands.values():
        if not c.get("nomor"):
            c["nomor"], c["tahun"] = nomor_tahun(c.get("title", ""))
    return cands


def enum_dih(sess, base, unit):
    """Aceh-family DIH app: the /dih/kategori page's inline JS maps
    category names to codes; documents are served by the DataTables
    endpoint /dih/jsondata?kat_dok=<code>. Rows carry Tahun/No metadata
    and /dih/detail/<uuid> links; detail pages expose
    /dih/download/produk-hukum/<uuid>. Aceh's Perda are titled 'Qanun' —
    those are counted and skipped here because this campaign's
    wrong-type guard requires Peraturan-Daerah-headed titles."""
    r = sess.get(base + "/dih/kategori/Peraturan%20Daerah", timeout=150)
    r.raise_for_status()
    kat = "15"
    m = re.search(r'\{display:\s*"Peraturan Daerah[^"]*",\s*value:\s*"(\d+)"\}',
                  r.text)
    if m:
        kat = m.group(1)
    out = {}
    qanun = 0
    start, total = 0, None
    while start < 600:
        u = f"{base}/dih/jsondata?draw=1&start={start}&length=100&kat_dok={kat}"
        rr = sess.get(u, timeout=150)
        rr.raise_for_status()
        d = rr.json()
        if total is None:
            total = d.get("recordsFiltered", 0)
        rows = d.get("data", [])
        if not rows:
            break
        for row in rows:
            snippet = row[0] if isinstance(row, list) else str(row)
            dm = re.search(r'href="([^"]*/dih/detail/[0-9a-fA-F-]{36})"', snippet)
            if not dm:
                continue
            detail = urljoin(base, dm.group(1))
            tm = re.search(r'<a[^>]*class="news-title"[^>]*>(.*?)</a>', snippet, re.S)
            title = clean_ws(re.sub(r"<[^>]+>", " ", tm.group(1))) if tm else ""
            ym = re.search(r"Tahun\s*:\s*(\d{4})", snippet)
            nm = re.search(r"No\.\s*Peraturan\s*:\s*([0-9A-Za-z./-]+)", snippet)
            if re.match(r"(?i)\s*qanun\b", title):
                qanun += 1
                continue
            if not is_perda_title(title):
                continue
            out[detail] = dict(detail_url=detail, pdf_url="", title=title,
                               nomor=nm.group(1) if nm else "",
                               tahun=ym.group(1) if ym else "",
                               key=detail.rstrip("/").split("/")[-1])
        start += len(rows)
        if total is not None and start >= total:
            break
    unit["dih_qanun_skipped"] = qanun
    unit["dih_catalog_total"] = total
    return out


def enum_jayapura2(sess, base, unit):
    routes = [
        base + "/dokumen/index?DokumenSearch%5Btipe_dokumen%5D=1"
               "&DokumenSearch%5Bjenis_peraturan%5D=PERATURAN%20DAERAH&per-page=50",
        base + "/dokumen/peraturan-daerah",
        base + "/dokumen/peraturan",
    ]
    for first in routes:
        cands = H.paginate(sess, first, _jayapura_cards, max_pages=200)
        if cands:
            return cands
    return {}


H.ENUMERATORS["jdihn_list"] = enum_jdihn_list
H.ENUMERATORS["prokum_list"] = enum_prokum_list
H.ENUMERATORS["jayapura2"] = enum_jayapura2
H.ENUMERATORS["dih"] = enum_dih
H.ENUMERATORS["slug_detail"] = enum_slug_detail
H.ENUMERATORS["dokumen_view_perda"] = enum_dokumen_view_perda
H.RESOLVER_ADAPTERS.update({"jdihn_list", "prokum_list", "jayapura2"})

# ------------------------------------------------------- unit tables

SWING_UNITS = [
    ("3210", "Kabupaten Majalengka", "jdih.majalengkakab.go.id", "common_dokumen"),
    ("3604", "Kabupaten Serang", "jdih.serangkab.go.id", "common_dokumen"),
    ("9104", "Kabupaten Teluk Bintuni", "jdih.telukbintunikab.go.id", "common_dokumen"),
    ("3306", "Kabupaten Purworejo", "jdih.purworejokab.go.id", "inventarisasi"),
    ("3317", "Kabupaten Rembang", "jdih.rembangkab.go.id", "inventarisasi"),
    ("5202", "Kabupaten Lombok Tengah", "jdih.lomboktengahkab.go.id", "lomboktengah"),
    ("1807", "Kabupaten Way Kanan", "jdih.waykanankab.go.id", "waykanan"),
    ("6303", "Kabupaten Banjar", "jdih.banjarkab.go.id", "banjar"),
    ("8105", "Kabupaten Kepulauan Aru", "jdih.kepulauanarukab.go.id", "aru"),
    ("3373", "Kota Salatiga", "jdih.salatiga.go.id", "common_dokumen"),
    ("6371", "Kota Banjarmasin", "jdih.banjarmasinkota.go.id", "banjarmasin"),
    ("3320", "Kabupaten Jepara", "jdih.jepara.go.id", "inventarisasi"),
    ("7203", "Kabupaten Morowali", "jdih.morowalikab.go.id", "morowali"),
    ("9403", "Kabupaten Jayapura", "jdih.jayapurakab.go.id", "jayapura2"),
]

_lock = threading.Lock()


def load_json(path, default):
    if Path(path).exists():
        return json.loads(Path(path).read_text())
    return default


def save_state2(state):
    with _lock:
        STATE2_PATH.write_text(json.dumps(state, indent=1, ensure_ascii=False))


MAIN_T2_PATH = CAMP / "id_campaign_tranche2_state.json"


def published_bps():
    """Units already published (either campaign) or staged in the main
    tranche-2 state — never re-harvest those from a side state file."""
    out = set()
    for p in (T1_STATE_PATH, MAIN_T2_PATH, STATE2_PATH):
        st = load_json(p, {})
        for bps, s in st.items():
            if isinstance(s, dict) and s.get("status") in ("published", "staged"):
                out.add(bps)
    return out


def drive(units, label):
    state = load_json(STATE2_PATH, {})
    pub = published_bps()
    todo = []
    for u in units:
        cur = state.get(u["bps"], {})
        if cur.get("status") in ("staged", "published"):
            print(f"[{u['bps']}] t2-state {cur['status']}, skip", flush=True)
            continue
        if u["bps"] in pub:
            print(f"[{u['bps']}] already published, skip", flush=True)
            continue
        todo.append(u)
    print(f"{label}: {len(todo)} units to harvest", flush=True)
    workers = int(os.environ.get("ID_WORKERS", "5"))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for man in ex.map(lambda u: H.harvest_unit(u, state), todo):
            state[man["bps"]] = dict(man)
            save_state2(state)
            print(json.dumps({k: man.get(k) for k in
                              ("bps", "name", "adapter", "status", "catalog_total",
                               "selected", "acts", "rows", "requests", "errors")},
                             ensure_ascii=False), flush=True)
    print(f"{label}: done", flush=True)


def generic_units():
    census = load_json(CENSUS_PATH, {})
    registry = {u["bps"]: u for u in load_json(REGISTRY, {})["units"]}
    out = []
    for bps, rec in census.items():
        adapter = rec.get("adapter")
        if not adapter:
            continue
        reg = registry.get(bps, {})
        unit = dict(bps=bps, name=reg.get("name", bps),
                    host=reg.get("best_host", ""), adapter=adapter,
                    family=rec.get("family", ""))
        if adapter == "common_dokumen":
            H.LIST_URLS["common_dokumen"][bps] = rec.get("listing_path") \
                or "/dokumen?tipe_dokumen=1"
        out.append(unit)
    return out


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else "swing"
    if phase == "swing":
        drive([dict(bps=b, name=n, host=h, adapter=a, family="swing_t1")
               for b, n, h, a in SWING_UNITS], "swing")
    elif phase == "generic":
        drive(generic_units(), "generic")
    elif phase.startswith("units:"):
        want = set(phase.split(":", 1)[1].split(","))
        allu = {b: (n, h, a) for b, n, h, a in SWING_UNITS}
        registry = {u["bps"]: u for u in load_json(REGISTRY, {})["units"]}
        census = load_json(CENSUS_PATH, {})
        units = []
        for b in want:
            if b in allu:
                n, h, a = allu[b]
                units.append(dict(bps=b, name=n, host=h, adapter=a, family="adhoc"))
            elif b in census and census[b].get("adapter"):
                reg = registry.get(b, {})
                a = census[b]["adapter"]
                if a == "common_dokumen":
                    H.LIST_URLS["common_dokumen"][b] = census[b].get("listing_path") \
                        or "/dokumen?tipe_dokumen=1"
                units.append(dict(bps=b, name=reg.get("name", b),
                                  host=reg.get("best_host", ""), adapter=a,
                                  family=census[b].get("family", "")))
            else:
                print(f"[{b}] no adapter known, skip", flush=True)
        drive(units, "units")
    else:
        print("unknown phase", phase)


if __name__ == "__main__":
    main()
